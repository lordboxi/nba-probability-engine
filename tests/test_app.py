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
    assert len(app.checkbox) == 10  # Five reserves per team; starters have no bench checkbox.
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
    assert any("impact rating" in item.value for item in app.info)
    assert len(app.dataframe) >= 1
    result = json.loads(app.json[0].value)
    selection = result["roster_selection"]
    assert selection["selection_type"] == "positioned_lineup"
    assert sum(row["starter"] for row in selection["players"]) == 10
    assert sum(row["plays"] for row in selection["players"]) == 11
    assert sum(row["position"] == "PG" for row in selection["players"]) == 2
    assert all(row["position"] is None for row in selection["players"] if not row["starter"])
