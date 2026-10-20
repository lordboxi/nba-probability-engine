from copy import deepcopy
from types import SimpleNamespace

import pytest

from nbaprob.data.nba_stats import NBAStatsAdapter, normalize_players
from nbaprob.data.snapshots import save_snapshot
from nbaprob.lineups.player_stats import player_statistics, rotation_document, rotation_rows
from nbaprob.lineups.scenarios import lineup_forecast


@pytest.fixture
def player_payload():
    return {
        "resultSets": [
            {
                "name": "LeagueDashPlayerStats",
                "headers": [
                    "PLAYER_ID",
                    "TEAM_ID",
                    "PLAYER_NAME",
                    "GP",
                    "MIN",
                    "PTS",
                    "REB",
                    "AST",
                    "STL",
                    "BLK",
                    "TOV",
                    "FGM",
                    "FGA",
                    "FG3M",
                    "FG3A",
                    "FTM",
                    "FTA",
                    "PLUS_MINUS",
                ],
                "rowSet": [
                    [99, 1, "Fixture Player", 10, 30, 20, 5, 4, 1, 1, 2, 7, 14, 2, 5, 4, 5, 3]
                ],
            }
        ]
    }


def test_player_adapter_efficiency_and_trade_stints(config, player_payload):
    traded = deepcopy(player_payload["resultSets"][0]["rowSet"][0])
    traded[1] = 2
    player_payload["resultSets"][0]["rowSet"].append(traded)
    doc = NBAStatsAdapter(config).fetch(
        "players", "2026-27", "Preseason", imported_payload=player_payload
    )
    assert doc["resource"] == "players" and doc["season_type"] == "Preseason"
    assert len(doc["data"]) == 2
    assert doc["data"][0]["efg_pct"] == pytest.approx(8 / 14)
    assert doc["data"][0]["ts_pct"] == pytest.approx(20 / (2 * (14 + 0.44 * 5)))
    with pytest.raises(ValueError, match="Duplicate"):
        player_payload["resultSets"][0]["rowSet"].append(traded)
        normalize_players(player_payload)


@pytest.mark.parametrize("index,value", [(3, 1.5), (4, -1), (5, float("nan")), (11, 99)])
def test_invalid_player_stats_rejected(player_payload, index, value):
    player_payload["resultSets"][0]["rowSet"][0][index] = value
    with pytest.raises(ValueError):
        normalize_players(player_payload)


def test_zero_attempts_are_missing_not_zero_efficiency(player_payload):
    row = player_payload["resultSets"][0]["rowSet"][0]
    for index in (5, 11, 12, 13, 14, 15, 16):
        row[index] = 0
    actual = normalize_players(player_payload)[0]
    assert actual["ts_pct"] is None and actual["efg_pct"] is None


def test_player_join_uses_ids_prior_season_and_asof(config, player_payload):
    selection = {"players": [{"player_id": "99", "name": "Renamed Player", "team_id": "2"}]}
    old = NBAStatsAdapter(config).fetch(
        "players", "2025-26", "Regular Season", imported_payload=player_payload
    )
    old["retrieved_at"] = "2026-10-19T00:00:00Z"
    save_snapshot(old, config)
    new = NBAStatsAdapter(config).fetch(
        "players", "2026-27", "Preseason", imported_payload=player_payload
    )
    new["retrieved_at"] = "2026-10-20T03:00:00Z"
    save_snapshot(new, config)
    rows = player_statistics(config, "2026-27", "Regular Season", "2026-10-20T02:00:00Z", selection)
    assert rows["99"]["season"] == "2025-26" and rows["99"]["different_team"]
    assert not player_statistics(
        config, "2026-27", "Regular Season", "2026-10-18T00:00:00Z", selection
    )


def test_rotation_changes_use_minutes_delta_and_keep_team_totals(config):
    as_of = "2026-10-20T02:00:00Z"
    game = SimpleNamespace(game_id="fixture", home_team="H", away_team="A")
    selection = {
        "players": [
            {
                "player_id": f"{team}{i}",
                "name": f"Player {i}",
                "team": team,
                "starter": i < 5,
                "plays": i < 5,
            }
            for team in ("H", "A")
            for i in range(6)
        ]
    }
    rows = rotation_rows(selection, {}, config)
    for team in ("H", "A"):
        assert sum(row["baseline_minutes"] for row in rows if row["team"] == team) == pytest.approx(
            240
        )
        assert sum(row["expected_minutes"] for row in rows if row["team"] == team) == pytest.approx(
            240
        )
    base = {
        "p_home_win": 0.5,
        "mu_margin": 0.0,
        "mu_total": 220.0,
        "sigma_margin": 12.0,
        "sigma_total": 19.0,
        "features": {"pace": 100},
    }
    neutral = rotation_document(rows, selection, {}, game, as_of, "User supplied fixture ratings")
    assert lineup_forecast(base, neutral, game, as_of, config)["p_home_win"] == 0.5
    # An absent positive-impact player reduces the home team's expected margin.
    rows[5]["offense_impact"] = 6.0
    adjusted = rotation_document(rows, selection, {}, game, as_of, "User supplied fixture ratings")
    result = lineup_forecast(base, adjusted, game, as_of, config)
    assert result["scenarios"][0]["mu_margin"] == pytest.approx(-5.0)
    assert result["p_home_win"] < 0.5
    for scenario in result["scenarios"]:
        assert all(
            sum(minutes.values()) == pytest.approx(240)
            for minutes in scenario["rotation_minutes"].values()
        )
    with pytest.raises(ValueError, match="source"):
        rotation_document(rows, selection, {}, game, as_of, "")
