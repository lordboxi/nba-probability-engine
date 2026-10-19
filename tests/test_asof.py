from copy import deepcopy

import pandas as pd
import pytest

from nbaprob.data.demo import generate_demo
from nbaprob.data.schema import SCHEMAS
from nbaprob.features.build import ReplayEngine, build_features


def target_and_cutoff(tables):
    target = tables.games[tables.games.game_id == "demo-2024-0010"].iloc[0]
    return target, target.date - pd.Timedelta(hours=1)


def test_future_outcomes_and_stats_cannot_change_forecast(tables, config):
    target, cutoff = target_and_cutoff(tables)
    before = ReplayEngine(tables, config).predict(target.game_id, cutoff)
    changed = deepcopy(tables)
    mask = changed.games.results_available_at > cutoff
    changed.games.loc[mask, "home_pts"] += 100
    changed.games.loc[mask, "away_pts"] += 5
    mask = changed.team_game_stats.ts > cutoff
    changed.team_game_stats.loc[mask, ["possessions", "ortg", "drtg"]] *= 3
    changed.validate()
    after = ReplayEngine(changed, config).predict(target.game_id, cutoff)
    assert before == after


def test_unpublished_schedule_snapshot_is_excluded(tables, config):
    target, cutoff = target_and_cutoff(tables)
    before = build_features(target.game_id, cutoff, tables, config)
    tables.schedule = pd.DataFrame(
        [
            {
                "game_id": target.game_id,
                "rest_days_home": 7,
                "rest_days_away": 0,
                "b2b_home": 0,
                "b2b_away": 1,
                "games_last_7d": 4,
                "travel_km": 9000,
                "altitude": 1000,
                "ts": cutoff + pd.Timedelta(minutes=1),
            }
        ],
        columns=SCHEMAS["schedule"],
    )
    tables.validate()
    assert before == build_features(target.game_id, cutoff, tables, config)
    available = build_features(target.game_id, cutoff + pd.Timedelta(minutes=1), tables, config)
    assert available["schedule_override"] is True
    assert available["travel"] == 9.0


def test_delayed_results_and_stats_are_not_used_early(config):
    config["demo"].update(teams=2, seasons=1, games_per_season=5)
    tables = generate_demo(config)
    first, second = tables.games.sort_values("date").iloc[:2].itertuples(index=False)
    late = second.date + pd.Timedelta(hours=1)
    tables.games.loc[tables.games.game_id == first.game_id, "results_available_at"] = late
    tables.team_game_stats.loc[tables.team_game_stats.game_id == first.game_id, "ts"] = late
    tables.validate()
    features = build_features(second.game_id, second.date - pd.Timedelta(hours=1), tables, config)
    assert features["training_games"] == 0
    assert features["rating_diff"] == 0
    assert features["pace"] == config["features"]["league_pace"]
    engine = ReplayEngine(tables, config)
    engine.advance(late - pd.Timedelta(nanoseconds=1))
    assert engine.completed == 0
    engine.advance(late)
    assert engine.completed == 1


def test_fixture_unknown_and_post_tipoff_requests_rejected(tables, config):
    target, _ = target_and_cutoff(tables)
    for at, message in [
        (target.ts - pd.Timedelta(seconds=1), "not known"),
        (target.date, "before tipoff"),
    ]:
        with pytest.raises(ValueError, match=message):
            build_features(target.game_id, at, tables, config)
    with pytest.raises(ValueError, match="timezone"):
        build_features(target.game_id, "2024-10-25", tables, config)


def test_replay_rejects_time_reversal(tables, config):
    engine = ReplayEngine(tables, config)
    engine.advance("2024-10-25T00:00:00Z")
    with pytest.raises(ValueError, match="forward"):
        engine.advance("2024-10-24T00:00:00Z")
