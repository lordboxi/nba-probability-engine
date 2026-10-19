import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pytest

from nbaprob.cli import main
from nbaprob.data.nba_stats import NBAStatsAdapter, normalize_roster, normalize_teams
from nbaprob.data.snapshots import latest_snapshot, save_snapshot
from nbaprob.models.team_snapshot import matchup_forecast


@pytest.fixture
def nba_payload():
    return {
        "resultSets": [
            {
                "name": "LeagueDashTeamStats",
                "headers": [
                    "TEAM_ID",
                    "TEAM_NAME",
                    "GP",
                    "W",
                    "L",
                    "W_PCT",
                    "MIN",
                    "PTS",
                    "PLUS_MINUS",
                    "FGA",
                    "FTA",
                    "OREB",
                    "TOV",
                ],
                "rowSet": [
                    [1, "Fixture Home", 10, 6, 4, 0.6, 48.0, 110.0, 5.0, 85.0, 20.0, 10.0, 13.0],
                    [2, "Fixture Away", 10, 4, 6, 0.4, 48.0, 105.0, -3.0, 86.0, 20.0, 11.0, 14.0],
                ],
            }
        ]
    }


def test_adapter_normalizes_table_and_explicitly_sends_season_type(config, nba_payload):
    urls = []

    def transport(url):
        urls.append(url)
        return nba_payload

    document = NBAStatsAdapter(config, transport=transport).fetch("teams", "2026-27", "Preseason")
    assert len(document["data"]) == 2
    assert document["data"][0]["team_id"] == "1"
    query = parse_qs(urlsplit(urls[0]).query)
    assert query["SeasonType"] == ["Pre Season"]
    assert query["Season"] == ["2026-27"]
    assert query["PerMode"] == ["PerGame"]
    assert pd.Timestamp(document["retrieved_at"]).tzinfo is not None
    assert document["provider"] == "NBA.com"


def test_saved_json_uses_import_time_not_a_fabricated_historical_timestamp(config, nba_payload):
    before = pd.Timestamp.now(tz="UTC")
    document = NBAStatsAdapter(config).fetch("teams", "2024-25", imported_payload=nba_payload)
    assert document["imported"] is True
    assert pd.Timestamp(document["retrieved_at"]) >= before


def test_request_interval_prevents_burst_and_does_not_retry(config, nba_payload):
    calls = []
    adapter = NBAStatsAdapter(config, transport=lambda url: calls.append(url) or nba_payload)
    adapter.fetch("teams", "2026-27")
    with pytest.raises(ValueError, match="wait"):
        adapter.fetch("teams", "2026-27")
    assert len(calls) == 1


def test_timeout_is_reported_without_retry(config, monkeypatch):
    calls = []

    def timeout(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("test timeout")

    monkeypatch.setattr("nbaprob.data.nba_stats.urlopen", timeout)
    with pytest.raises(ValueError, match="could not be reached"):
        NBAStatsAdapter(config).fetch("teams", "2026-27")
    assert len(calls) == 1


@pytest.mark.parametrize("mutation", ["missing_column", "duplicate_team", "nan", "row_width"])
def test_malformed_team_tables_rejected(nba_payload, mutation):
    table = nba_payload["resultSets"][0]
    if mutation == "missing_column":
        table["headers"][0] = "UNKNOWN"
    elif mutation == "duplicate_team":
        table["rowSet"][1][0] = table["rowSet"][0][0]
    elif mutation == "nan":
        table["rowSet"][0][7] = float("nan")
    else:
        table["rowSet"][0].append(1)
    with pytest.raises(ValueError):
        normalize_teams(nba_payload)


def test_roster_names_remain_roster_data_not_automatic_injury_status():
    payload = {
        "resultSets": [
            {
                "name": "CommonTeamRoster",
                "headers": ["TeamID", "PLAYER_ID", "PLAYER", "POSITION", "NUM"],
                "rowSet": [[1, 99, "Fixture Player", "G", "0"]],
            }
        ]
    }
    rows = normalize_roster(payload, "1")
    assert rows == [
        {
            "team_id": "1",
            "player_id": "99",
            "name": "Fixture Player",
            "position": "G",
            "jersey": "0",
        }
    ]
    with pytest.raises(ValueError, match="different team"):
        normalize_roster(payload, "2")


def test_snapshots_are_asof_filtered_and_versions_do_not_overwrite(config, nba_payload):
    first = NBAStatsAdapter(config).fetch("teams", "2026-27", imported_payload=nba_payload)
    first["retrieved_at"] = "2026-10-19T06:00:00Z"
    original = save_snapshot(first, config)
    changed = deepcopy(first)
    changed.update(retrieved_at="2026-10-19T08:00:00Z")
    changed["data"][0]["points"] = 999
    updated = save_snapshot(changed, config)
    assert original["identity"] != updated["identity"]
    assert latest_snapshot(config, "teams", "2026-27", "2026-10-19T05:59:59Z", "Preseason") is None
    prior = latest_snapshot(config, "teams", "2026-27", "2026-10-19T07:00:00Z", "Preseason")
    assert prior["identity"] == original["identity"]
    assert prior["data"][0]["points"] == 110
    assert Path(original["path"]).is_file() and Path(updated["path"]).is_file()
    assert (
        latest_snapshot(config, "teams", "2026-27", "2026-10-19T09:00:00Z", "Regular Season")
        is None
    )
    Path(original["path"]).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        latest_snapshot(config, "teams", "2026-27", "2026-10-19T07:00:00Z", "Preseason")


def test_snapshot_forecast_is_experimental_and_cannot_use_future_data(config, nba_payload):
    snapshot = NBAStatsAdapter(config).fetch("teams", "2026-27", imported_payload=nba_payload)
    snapshot["retrieved_at"] = "2026-10-19T06:00:00Z"
    game, forecast = matchup_forecast(
        snapshot, "1", "2", "2026-10-19T10:00:00Z", "2026-10-19T07:00:00Z", config
    )
    assert game.home_team == "Fixture Home"
    assert forecast["model"] == "experimental_team_snapshot"
    assert forecast["p_home_win"] > 0.5
    assert forecast["features"]["training_games"] == 0
    with pytest.raises(ValueError, match="after prediction"):
        matchup_forecast(snapshot, "1", "2", "2026-10-19T10:00:00Z", "2026-10-19T05:00:00Z", config)


def test_cli_import_and_snapshot_matchup_work_without_api_key(
    config, tmp_path, nba_payload, capsys
):
    import yaml

    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(config), encoding="utf-8")
    payload = tmp_path / "nba.json"
    payload.write_text(json.dumps(nba_payload), encoding="utf-8")
    prefix = ["--config", str(cfg)]
    assert (
        main([*prefix, "nba-fetch", "teams", "--season", "2026-27", "--import-json", str(payload)])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["rows"] == 2
    as_of = pd.Timestamp.now(tz="UTC") + pd.Timedelta(seconds=1)
    tipoff = as_of + pd.Timedelta(hours=4)
    assert (
        main(
            [
                *prefix,
                "matchup",
                "--season",
                "2026-27",
                "--home-team-id",
                "1",
                "--away-team-id",
                "2",
                "--tipoff",
                tipoff.isoformat(),
                "--as-of",
                as_of.isoformat(),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["model"] == "experimental_team_snapshot"
    assert result["snapshot_id"]
