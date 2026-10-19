"""Reproducible synthetic fixtures and scores, never presented as real NBA data."""

import numpy as np
import pandas as pd

from nbaprob.data.schema import SCHEMAS, Tables


def generate_demo(config) -> Tables:
    cfg = config["demo"]
    rng = np.random.default_rng(config["seed"])
    teams = [f"DEMO_{i:02d}" for i in range(cfg["teams"])]
    strengths = dict(zip(teams, rng.normal(0, cfg["rating_sd"], len(teams)), strict=True))
    games, stats = [], []
    for season in range(cfg["first_season"], cfg["first_season"] + cfg["seasons"]):
        start = pd.Timestamp(
            year=season, month=cfg["start_month"], day=cfg["start_day"], hour=23, tz="UTC"
        )
        per_round = cfg["teams"] // 2
        order = list(teams)
        for index in range(cfg["games_per_season"]):
            if index % per_round == 0:
                order = list(rng.permutation(teams))
            slot = (index % per_round) * 2
            home, away = order[slot : slot + 2]
            date = start + pd.Timedelta(days=(index // per_round) * cfg["days_between_rounds"])
            date += pd.Timedelta(minutes=index % per_round)
            pace = max(
                config["features"]["league_pace"] / 2,
                rng.normal(config["features"]["league_pace"], cfg["pace_sd"]),
            )
            mean = (strengths[home] - strengths[away]) * pace / 100
            mean += config["model"]["initial_hca"]
            margin = int(round(rng.normal(mean, cfg["margin_sd"])))
            if margin == 0:
                margin = int(rng.choice([-1, 1]))
            total = int(
                round(
                    rng.normal(2 * config["features"]["league_ortg"] * pace / 100, cfg["total_sd"])
                )
            )
            total = max(total, abs(margin) + 2)
            total += (total - margin) % 2
            home_pts, away_pts = (total + margin) // 2, (total - margin) // 2
            game_id = f"demo-{season}-{index:04d}"
            available = date + pd.Timedelta(hours=cfg["result_delay_hours"])
            games.append(
                {
                    "game_id": game_id,
                    "season": season,
                    "date": date,
                    "home_team": home,
                    "away_team": away,
                    "home_pts": home_pts,
                    "away_pts": away_pts,
                    "ot_periods": 0,
                    "ts": date - pd.Timedelta(days=cfg["fixture_lead_days"]),
                    "results_available_at": available,
                }
            )
            for team, pts, opponent_pts in ((home, home_pts, away_pts), (away, away_pts, home_pts)):
                stats.append(
                    {
                        "game_id": game_id,
                        "team": team,
                        "possessions": pace,
                        "ortg": pts / pace * 100,
                        "drtg": opponent_pts / pace * 100,
                        "ts": available,
                    }
                )
    upcoming = dict(games[-1])
    upcoming.update(
        game_id="demo-next",
        date=games[-1]["date"] + pd.Timedelta(days=cfg["days_between_rounds"]),
        home_pts=None,
        away_pts=None,
        ot_periods=None,
        results_available_at=None,
    )
    upcoming["ts"] = upcoming["date"] - pd.Timedelta(days=cfg["fixture_lead_days"])
    games.append(upcoming)
    return Tables(
        pd.DataFrame(games),
        pd.DataFrame(stats),
        pd.DataFrame(columns=SCHEMAS["schedule"]),
        {
            "source": "synthetic-demo",
            "synthetic": True,
            "seed": config["seed"],
            "usage_note": "Generated locally; no external data",
        },
    ).validate()
