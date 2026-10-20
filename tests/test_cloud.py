import io
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pytest
import yaml

from nbaprob.data.bootstrap import bootstrap_snapshots
from nbaprob.data.snapshots import latest_snapshot
from nbaprob.models.team_snapshot import matchup_forecast

ROOT = Path(__file__).parents[1]
SEEDS = ROOT / "deployment/seed_snapshots"


def test_cloud_entrypoint_prefers_updated_checkout_to_previously_installed_wheel(tmp_path):
    package = tmp_path / "nbaprob"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "app.py").write_text("raise RuntimeError('old installed wheel')", encoding="utf-8")
    script = f"""
import sys, runpy
sys.path.insert(0, {str(tmp_path)!r})
def inspect_entry(frame, event, arg):
    if (event == "call" and frame.f_code.co_name == "run"
            and frame.f_globals.get("__name__") == "nbaprob.app"):
        from streamlit.file_util import file_in_pythonpath
        assert file_in_pythonpath(frame.f_code.co_filename)
        print(frame.f_code.co_filename)
        raise SystemExit(0)
sys.setprofile(inspect_entry)
runpy.run_path({str(ROOT / "deployment/streamlit_app.py")!r})
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert Path(completed.stdout.strip()).resolve() == ROOT / "src/nbaprob/app.py"


def test_cloud_bootstrap_is_idempotent_and_preserves_observation_time(config):
    local_data = Path(config["data"]["database"])
    local_data.write_bytes(b"owner data must not be changed")
    first = bootstrap_snapshots(config, SEEDS)
    assert len(first) == 6
    assert bootstrap_snapshots(config, SEEDS) == first
    assert local_data.read_bytes() == b"owner data must not be changed"
    document = json.loads((SEEDS / "teams-preseason.json").read_text(encoding="utf-8"))
    at = document["retrieved_at"]
    loaded = latest_snapshot(config, "teams", "2026-27", at, "Preseason")
    assert loaded["retrieved_at"] == at
    assert loaded["origin_snapshot_identity"] == document["origin_snapshot_identity"]
    assert latest_snapshot(config, "teams", "2026-27", "2026-10-18T00:00:00Z", "Preseason") is None
    assert "raw_response" not in loaded


def test_cloud_seed_bundle_contains_only_nba_statistics(config, tmp_path):
    for path in SEEDS.glob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["provider"] == "NBA.com"
        assert document["resource"] in {"teams", "roster", "players"}
        assert "house_quote" not in document
        assert "roster_selection" not in document
    (tmp_path / "private.json").write_text('{"resource":"journal"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Bundled data"):
        bootstrap_snapshots(config, tmp_path)


def test_real_regular_season_prior_has_30_teams_and_cannot_backfill_forecasts(config):
    bootstrap_snapshots(config, SEEDS)
    document = json.loads((SEEDS / "teams-2025-26-regular.json").read_text(encoding="utf-8"))
    at = document["retrieved_at"]
    prior = latest_snapshot(config, "teams", "2025-26", at, "Regular Season")
    assert len(prior["data"]) == 30
    assert len({row["team_id"] for row in prior["data"]}) == 30
    assert all(row["gp"] == 82 and row["wins"] + row["losses"] == 82 for row in prior["data"])
    assert (
        latest_snapshot(
            config, "teams", "2025-26", pd.Timestamp(at) - pd.Timedelta(seconds=1), "Regular Season"
        )
        is None
    )
    _, base = matchup_forecast(
        None,
        "1610612738",
        "1610612737",
        pd.Timestamp(at) + pd.Timedelta(hours=4),
        at,
        config,
        season="2026-27",
        season_type="Regular Season",
        previous_snapshot=prior,
    )
    assert "previous_season_stats" not in base["data_readiness"]["missing"]
    assert base["data_readiness"]["teams"]["1610612738"]["previous_season_games"] == 82


def test_cloud_entrypoint_starts_with_real_seed_data(config, tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setenv("NBA_CONFIG", str(cfg))
    # The entrypoint sets this flag; monkeypatch restores it for subsequent tests.
    monkeypatch.setenv("NBA_CLOUD_MODE", "0")
    app = AppTest.from_file(str(ROOT / "deployment/streamlit_app.py"))
    app.run(timeout=30)
    assert not app.exception
    assert not app.error
    assert any("Cloud:" in item.value for item in app.warning)
    assert (
        len([item for item in app.selectbox if item.key and item.key.startswith("starter_")]) == 10
    )
    assert (
        next(item for item in app.selectbox if item.label == "แหล่งข้อมูลคู่แข่งขัน").value == "ตาราง NBA"
    )
    assert (
        latest_snapshot(config, "teams", "2026-27", "2026-10-20T23:59:59Z", "Preseason") is not None
    )


def test_cloud_player_changes_skip_network_and_history_loads_once(config, tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setenv("NBA_CONFIG", str(cfg))
    monkeypatch.setenv("NBA_CLOUD_MODE", "0")
    monkeypatch.setenv("NBA_SUPABASE_URL", "https://fixture.supabase.co")
    monkeypatch.setenv("NBA_SUPABASE_SECRET_KEY", "sb_secret_fixture")
    monkeypatch.setattr("nbaprob.data.supabase_store.monotonic", lambda: 100.0)
    rows, calls = {}, []
    forecast = {
        "identity": "a" * 64,
        "game_id": "fixture",
        "home_team": "H",
        "away_team": "A",
        "tipoff": "2030-01-01T00:00:00Z",
        "as_of": "2026-10-20T00:00:00Z",
        "issued_at": "2026-10-20T01:00:00Z",
        "payload": json.dumps({"synthetic": True}),
    }

    def send(request, timeout):
        query = {
            key: value[0]
            for key, value in parse_qs(
                urlsplit(request.full_url).query, keep_blank_values=True
            ).items()
        }
        table = urlsplit(request.full_url).path.rsplit("/", 1)[-1]
        calls.append((request.method, table))
        if request.method == "POST":
            row = json.loads(request.data)
            rows[row["identity"]] = row
            return io.BytesIO(b"")
        if table == "nba_snapshots":
            selected = [
                row
                for row in rows.values()
                if all(
                    row[field] == query[field].removeprefix("eq.")
                    for field in ("resource", "season", "season_type", "team_id")
                )
                and pd.Timestamp(row["observed"])
                <= pd.Timestamp(query["observed"].removeprefix("lte."))
            ]
            result = sorted(
                selected, key=lambda row: (row["observed"], row["identity"]), reverse=True
            )[:1]
        else:
            result = [forecast] if table == "nba_forecasts" and query["offset"] == "0" else []
        return io.BytesIO(json.dumps(result).encode())

    monkeypatch.setattr("nbaprob.data.supabase_store.urlopen", send)
    app = AppTest.from_file(str(ROOT / "deployment/streamlit_app.py")).run(timeout=30)
    assert not app.error and not app.exception
    assert all(table == "nba_snapshots" for _, table in calls)
    calls.clear()
    starter = next(item for item in app.selectbox if item.key and item.key.startswith("starter_"))
    player = json.loads((SEEDS / "roster-1610612738.json").read_text(encoding="utf-8"))["data"][0]
    app.selectbox(key=starter.key).set_value(player["player_id"]).run(timeout=30)
    assert not app.error and not app.exception and not calls
    app.session_state["active_tab"] = "ประวัติและผลจริง"
    app.run(timeout=30)
    assert calls.count(("GET", "nba_forecasts")) == 2
    assert calls.count(("GET", "nba_outcomes")) == 1
    assert len(calls) == 3
    assert app.selectbox(key=starter.key).value == player["player_id"]
    calls.clear()
    app.session_state["active_tab"] = "วิเคราะห์คู่แข่งขัน"
    app.run(timeout=30)
    assert not calls
    next(item for item in app.button if item.label == "รีเฟรชข้อมูลที่บันทึกไว้").click().run(timeout=30)
    assert calls and all(table == "nba_snapshots" for _, table in calls)
    assert not app.error and not app.exception


def test_data_tab_rosters_and_saved_player_stats_work_without_new_regular_games(
    config, tmp_path, monkeypatch
):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    from nbaprob.data.nba_stats import NBAStatsAdapter

    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setenv("NBA_CONFIG", str(cfg))
    monkeypatch.setenv("NBA_CLOUD_MODE", "0")

    def offline(*args, **kwargs):
        raise ValueError("NBA Stats could not be reached")

    monkeypatch.setattr(NBAStatsAdapter, "fetch", offline)
    app = AppTest.from_file(str(ROOT / "deployment/streamlit_app.py")).run(timeout=30)
    app.session_state["active_tab"] = "ข้อมูล NBA"
    app.run(timeout=30)
    assert not app.error and not app.exception
    assert app.button(key="fetch_roster")  # Must remain available before Regular Season starts.
    assert app.selectbox(key="player_stats_basis").value == "Preseason ฤดูกาลที่เลือก"
    assert any(len(frame.value) == 577 for frame in app.dataframe)
    app.selectbox(key="player_stats_basis").set_value("Regular Season ฤดูกาลก่อน").run(timeout=30)
    assert any(len(frame.value) == 582 for frame in app.dataframe)
    app.button(key="fetch_players").click().run(timeout=30)
    assert not app.error and not app.exception
    assert any("ข้อมูลที่บันทึกไว้ไม่ได้ถูกลบ" in item.value for item in app.warning)
    assert any(len(frame.value) == 582 for frame in app.dataframe)

    def refreshed(*args, **kwargs):
        doc = json.loads((SEEDS / "players-2025-26-regular.json").read_text(encoding="utf-8"))
        doc["retrieved_at"] = pd.Timestamp.now(tz="UTC").isoformat()
        doc["data"] = doc["data"][:1]
        return doc

    monkeypatch.setattr(NBAStatsAdapter, "fetch", refreshed)
    app.button(key="fetch_players").click().run(timeout=30)
    assert not app.error and not app.exception
    assert any(len(frame.value) == 1 for frame in app.dataframe)  # Visible on the save run itself.
    app.session_state["active_tab"] = "วิเคราะห์คู่แข่งขัน"
    app.run(timeout=30)
    home = next(item for item in app.selectbox if item.label == "เจ้าบ้าน")
    home.set_value("1610612747").run(timeout=30)
    assert not app.error and not app.exception
    assert (
        len([item for item in app.selectbox if item.key and item.key.startswith("starter_")]) == 10
    )
    assert any(item.label == "Arthur Kaluma" for item in app.checkbox)
