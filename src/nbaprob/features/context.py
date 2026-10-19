"""Rest and congestion from known fixtures; optional timestamped travel covariates."""

import numpy as np
import pandas as pd

CONTEXT_NAMES = ("hca", "rest_diff", "b2b_diff", "congestion_diff", "travel", "altitude")


def context_features(tables, game, as_of, config) -> dict:
    cfg = config["features"]
    fixtures = tables.games
    known = fixtures[(fixtures.ts <= as_of) & (fixtures.date < game.date)]
    timezone = config["data"]["calendar_timezone"]
    target_day = game.date.tz_convert(timezone).date()

    def rest(team):
        prior = known[(known.home_team == team) | (known.away_team == team)]
        if prior.empty:
            return min(cfg["initial_rest_days"], cfg["rest_cap_days"]), 0.0
        previous = prior.date.max().tz_convert(timezone).date()
        days = max(0, (target_day - previous).days - 1)
        return min(days, cfg["rest_cap_days"]), float(days == 0)

    def congestion(team):
        return len(
            known[
                ((known.home_team == team) | (known.away_team == team))
                & (known.date >= game.date - pd.Timedelta(days=7))
            ]
        )

    rest_home, b2b_home = rest(game.home_team)
    rest_away, b2b_away = rest(game.away_team)
    congestion_diff = float(congestion(game.home_team) - congestion(game.away_team))
    travel = altitude = 0.0
    override = tables.schedule
    override = override[(override.game_id == game.game_id) & (override.ts <= as_of)]
    if not override.empty:
        row = override.iloc[0]
        rest_home = min(row.rest_days_home, cfg["rest_cap_days"])
        rest_away = min(row.rest_days_away, cfg["rest_cap_days"])
        b2b_home, b2b_away = row.b2b_home, row.b2b_away
        congestion_diff = row.games_last_7d
        travel, altitude = row.travel_km, row.altitude
    return {
        "hca": 1.0,
        "rest_diff": float(rest_home - rest_away),
        "b2b_diff": float(b2b_home - b2b_away),
        "congestion_diff": congestion_diff,
        "travel": float(travel / cfg["travel_scale_km"]),
        "altitude": float(altitude / cfg["altitude_scale_m"]),
        "rest_days_home": float(rest_home),
        "rest_days_away": float(rest_away),
        "schedule_override": not override.empty,
    }


def context_vector(features: dict) -> np.ndarray:
    return np.asarray([features[key] for key in CONTEXT_NAMES], dtype=float)
