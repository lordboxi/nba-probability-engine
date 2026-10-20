import json
from pathlib import Path

import pytest
import yaml

from nbaprob.data.store import save_tables

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402


def test_local_app_roster_selection_and_house_comparison(config, tables, tmp_path, monkeypatch):
    save_tables(tables, config["data"]["database"], config["data"]["raw_directory"])
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setenv("NBA_CONFIG", str(cfg))
    app = AppTest.from_file(str(Path(__file__).parents[1] / "src/nbaprob/app.py"))
    app.run(timeout=30)
    assert not app.exception
    assert not app.error
    starters = [item for item in app.selectbox if item.key and item.key.startswith("starter_")]
    assert len(starters) == 10
    assert all(item.value is None for item in starters)

    def calculate():
        return next(button for button in app.button if button.label == "คำนวณและเปรียบเทียบ")

    assert calculate().disabled
    # Assign each team's five positions, and exclude existing starters from other slots.
    for index, key in enumerate([item.key for item in starters]):
        item = app.selectbox(key=key)
        team = key.removeprefix("starter_demo-next_").rsplit("_", 1)[0]
        item.set_value(f"{team}-{index % 5}").run(timeout=30)
        assert not app.exception
    starters = [item for item in app.selectbox if item.key and item.key.startswith("starter_")]
    assert starters[0].options[1] not in starters[1].options
    assert not calculate().disabled
    # Five reserves per team plus an explicit opt-in to impact/minutes adjustments.
    assert len(app.checkbox) == 11
    reserve_key = app.checkbox[0].key
    app.checkbox(key=reserve_key).check().run(timeout=30)
    # Clearing/reassigning a position preserves reserve choices and blocks incomplete lineups.
    first_key, first_player = starters[0].key, starters[0].value
    app.selectbox(key=first_key).set_value(None).run(timeout=30)
    assert calculate().disabled
    assert app.checkbox(key=reserve_key).value
    app.selectbox(key=first_key).set_value(first_player).run(timeout=30)
    house = next(item for item in app.selectbox if item.label == "รูปแบบข้อมูล House")
    house.select("Decimal odds").run(timeout=30)
    next(button for button in app.button if button.label == "คำนวณและเปรียบเทียบ").click().run(
        timeout=30
    )
    assert not app.exception
    assert not app.error
    assert len(app.metric) == 3
    assert any("โมเดลให้โอกาสถูกสูงกว่า" in item.value for item in app.markdown)
    assert any("impact rating" in item.value for item in app.info)
    assert len(app.dataframe) >= 1
    result = json.loads(app.json[0].value)
    selection = result["roster_selection"]
    assert selection["selection_type"] == "positioned_lineup"
    assert result["house_reading"]["most_likely_model"] in ("home", "away", None)
    assert sum(row["starter"] for row in selection["players"]) == 10
    assert sum(row["plays"] for row in selection["players"]) == 11
    assert sum(row["position"] == "PG" for row in selection["players"]) == 2
    assert all(row["position"] is None for row in selection["players"] if not row["starter"])
    # Tabs rerun the app: keep the draft and its result, but hide stale results on edits.
    app.session_state["active_tab"] = "ประวัติและผลจริง"
    app.run(timeout=30)
    assert any("สะสม 1 คำทำนาย" in item.value for item in app.markdown)
    app.session_state["active_tab"] = "วิเคราะห์คู่แข่งขัน"
    app.run(timeout=30)
    assert app.selectbox(key=first_key).value == first_player
    assert app.checkbox(key=reserve_key).value
    assert json.loads(app.json[0].value) == result
    app.selectbox(key=first_key).set_value(None).run(timeout=30)
    assert not app.json and not app.metric


def test_impact_editor_requires_source_and_records_rotation(config, tables, tmp_path, monkeypatch):
    save_tables(tables, config["data"]["database"], config["data"]["raw_directory"])
    cfg = tmp_path / "impact-config.yaml"
    cfg.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setenv("NBA_CONFIG", str(cfg))
    app = AppTest.from_file(str(Path(__file__).parents[1] / "src/nbaprob/app.py")).run(timeout=30)
    keys = [item.key for item in app.selectbox if item.key and item.key.startswith("starter_")]
    for index, key in enumerate(keys):
        team = key.removeprefix("starter_demo-next_").rsplit("_", 1)[0]
        app.selectbox(key=key).set_value(f"{team}-{index % 5}").run(timeout=30)
    app.checkbox(key="use_player_impacts").check().run(timeout=30)

    def calculate():
        return next(item for item in app.button if item.label == "คำนวณและเปรียบเทียบ")

    assert calculate().disabled
    app.text_input(key="player_rating_source").set_value("UI fixture: neutral ratings").run(
        timeout=30
    )
    assert not calculate().disabled
    calculate().click().run(timeout=30)
    assert not app.error and not app.exception
    result = json.loads(app.json[0].value)
    assert result["lineup_adjustment_applied"]
    assert result["lineup"]["rating_source"] == "UI fixture: neutral ratings"
    rotations = result["lineup"]["scenarios"][0]["rotation_minutes"]
    assert all(sum(minutes.values()) == pytest.approx(240) for minutes in rotations.values())
