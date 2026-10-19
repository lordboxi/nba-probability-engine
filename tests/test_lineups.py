from copy import deepcopy

import pandas as pd
import pytest
from scipy.stats import norm

from nbaprob.analysis import STARTING_POSITIONS, analyze_forecast, validate_selection
from nbaprob.features.build import ReplayEngine
from nbaprob.lineups.scenarios import lineup_forecast, mixture_summary, settlement_scenarios


@pytest.fixture
def matchup(tables, config):
    engine = ReplayEngine(tables, config)
    game = engine.games["demo-next"]
    as_of = game.date - pd.Timedelta(hours=1)
    base = engine.predict(game.game_id, as_of)
    return game, as_of, base


@pytest.fixture
def lineup(matchup):
    game, as_of, _ = matchup
    players = [
        {
            "player_id": f"{team}-{index}",
            "name": f"Player {index}",
            "team": team,
            "starter": index < 5,
            "status": "available",
            "play_probability": None,
            "expected_minutes": 30.0,
            "baseline_minutes": 30.0,
            "offense_impact": 2.0 if index == 0 else 0.0,
            "defense_impact": 1.0 if index == 0 else 0.0,
            "rating_as_of": as_of.isoformat(),
        }
        for team in (game.home_team, game.away_team)
        for index in range(8)
    ]
    return {
        "game_id": game.game_id,
        "reported_at": as_of.isoformat(),
        "rating_source": "synthetic fixture",
        "probability_source": "test assumptions",
        "synthetic": True,
        "players": players,
    }


def test_full_rotation_does_not_double_count_team_ratings(matchup, lineup, config):
    game, as_of, base = matchup
    forecast = lineup_forecast(base, lineup, game, as_of, config)
    assert forecast["p_home_win"] == pytest.approx(base["p_home_win"])
    assert len(forecast["scenarios"]) == 1
    assert mixture_summary(forecast, "margin")["mean"] == pytest.approx(base["mu_margin"])


def test_exact_mixture_and_minutes_conservation(matchup, lineup, config):
    game, as_of, base = matchup
    lineup["players"][0].update(status="questionable", play_probability=0.4, offense_impact=20.0)
    forecast = lineup_forecast(base, lineup, game, as_of, config)
    assert sorted(row["weight"] for row in forecast["scenarios"]) == pytest.approx([0.4, 0.6])
    assert forecast["p_home_win"] == pytest.approx(
        sum(
            row["weight"] * norm.cdf(row["mu_margin"] / row["sigma_margin"])
            for row in forecast["scenarios"]
        )
    )
    moment = mixture_summary(forecast, "margin")
    assert abs(forecast["p_home_win"] - norm.cdf(moment["mean"] / moment["sigma"])) > 1e-5
    for scenario in forecast["scenarios"]:
        for minutes in scenario["rotation_minutes"].values():
            assert sum(minutes.values()) == pytest.approx(240)
            assert all(0 <= value <= 48 for value in minutes.values())
    for team in (game.home_team, game.away_team):
        assert sum(
            row["weighted_minutes"] for row in forecast["players"] if row["team"] == team
        ) == pytest.approx(240)
        assert sum(
            row["starting_probability"] for row in forecast["players"] if row["team"] == team
        ) == pytest.approx(5)


def test_out_player_receives_zero_minutes_and_mixture_pricing_is_normalized(
    matchup, lineup, config
):
    game, as_of, base = matchup
    lineup["players"][0].update(status="out")
    forecast = lineup_forecast(base, lineup, game, as_of, config)
    assert forecast["players"][0]["weighted_minutes"] == 0
    assert forecast["p_home_win"] < base["p_home_win"]
    for market, line in (("moneyline", None), ("spread", -7), ("total", 228)):
        rows = settlement_scenarios(forecast, market, line)
        for row in rows:
            assert row["win"] + row["push"] + row["loss"] == pytest.approx(1)


@pytest.mark.parametrize(
    "mutation",
    [
        "future_report",
        "future_rating",
        "bad_probability",
        "bad_minutes",
        "duplicate",
        "too_few_active",
    ],
)
def test_invalid_or_future_inputs_rejected(matchup, lineup, config, mutation):
    game, as_of, base = matchup
    changed = deepcopy(lineup)
    if mutation == "future_report":
        changed["reported_at"] = (as_of + pd.Timedelta(seconds=1)).isoformat()
    elif mutation == "future_rating":
        changed["players"][0]["rating_as_of"] = (as_of + pd.Timedelta(seconds=1)).isoformat()
    elif mutation == "bad_probability":
        changed["players"][0].update(status="questionable", play_probability=2)
    elif mutation == "bad_minutes":
        changed["players"][0]["baseline_minutes"] = 10
    elif mutation == "duplicate":
        changed["players"][1]["player_id"] = changed["players"][0]["player_id"]
    else:
        for row in changed["players"][:4]:
            row["status"] = "out"
    with pytest.raises(ValueError):
        lineup_forecast(base, changed, game, as_of, config)


def test_simple_player_selection_is_recorded_without_invented_impacts(matchup, lineup, config):
    game, as_of, base = matchup
    selection = {
        "game_id": game.game_id,
        "reported_at": as_of.isoformat(),
        "players": [
            {"player_id": row["player_id"], "team": row["team"], "plays": True}
            for row in lineup["players"]
        ],
    }
    result = analyze_forecast(base, game, as_of, config, selection=selection, synthetic=True)
    assert result["roster_selection"] == selection
    assert result["lineup_adjustment_applied"] is False
    assert result["p_home_win"] == base["p_home_win"]
    selection["players"][0]["plays"] = False
    assert (
        analyze_forecast(base, game, as_of, config, selection=selection)["p_home_win"]
        == base["p_home_win"]
    )


def test_uncertainty_limit_is_explicit_not_silently_truncated(matchup, lineup, config):
    game, as_of, base = matchup
    config["lineups"]["max_uncertain_players"] = 0
    lineup["players"][0]["status"] = "questionable"
    with pytest.raises(ValueError, match="Too many uncertain"):
        lineup_forecast(base, lineup, game, as_of, config)


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "duplicate_position",
        "missing_starter",
        "bench_position",
        "starter_out",
        "duplicate_player",
    ],
)
def test_positioned_manual_selection(matchup, lineup, mutation):
    game, as_of, _ = matchup
    selection = {
        "game_id": game.game_id,
        "reported_at": as_of.isoformat(),
        "selection_type": "positioned_lineup",
        "players": [
            {
                "player_id": row["player_id"],
                "team": row["team"],
                "plays": index % 8 < 6,
                "starter": index % 8 < 5,
                "position": STARTING_POSITIONS[index % 8] if index % 8 < 5 else None,
            }
            for index, row in enumerate(lineup["players"])
        ],
    }
    players = selection["players"]
    if mutation == "duplicate_position":
        players[1]["position"] = "PG"
    elif mutation == "missing_starter":
        players[0].update(starter=False, position=None)
    elif mutation == "bench_position":
        players[5]["position"] = "PG"
    elif mutation == "starter_out":
        players[0]["plays"] = False
    elif mutation == "duplicate_player":
        players[1]["player_id"] = players[0]["player_id"]
    if mutation is None:
        validate_selection(selection, game, as_of)
    else:
        with pytest.raises(ValueError):
            validate_selection(selection, game, as_of)
