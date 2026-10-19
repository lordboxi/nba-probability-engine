"""Strict v1 input contract with separate fixture and result availability times."""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

SCHEMAS = {
    "games": [
        "game_id",
        "season",
        "date",
        "home_team",
        "away_team",
        "home_pts",
        "away_pts",
        "ot_periods",
        "ts",
        "results_available_at",
    ],
    "team_game_stats": ["game_id", "team", "possessions", "ortg", "drtg", "ts"],
    "schedule": [
        "game_id",
        "rest_days_home",
        "rest_days_away",
        "b2b_home",
        "b2b_away",
        "games_last_7d",
        "travel_km",
        "altitude",
        "ts",
    ],
}


def utc(value) -> pd.Timestamp:
    """Reject naive timestamps rather than silently guessing their timezone."""
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError(f"Timestamp must include a timezone: {value!r}")
    return stamp.tz_convert("UTC")


def _numbers(frame, columns, *, minimum=None, integer=False):
    for column in columns:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        values = frame[column].dropna()
        if not np.isfinite(values).all():
            raise ValueError(f"Non-finite values in {column}")
        if minimum is not None and (values < minimum).any():
            raise ValueError(f"{column} must be >= {minimum}")
        if integer and (values % 1 != 0).any():
            raise ValueError(f"{column} must contain integers")


@dataclass
class Tables:
    games: pd.DataFrame
    team_game_stats: pd.DataFrame
    schedule: pd.DataFrame
    metadata: dict = field(default_factory=dict)

    def validate(self) -> "Tables":
        for name, required in SCHEMAS.items():
            frame = getattr(self, name).copy()
            if not set(required).issubset(frame.columns):
                raise ValueError(f"{name} requires columns {required}")
            frame = frame[required].copy()
            nullable = {"home_pts", "away_pts", "ot_periods", "results_available_at"}
            for col in set(required) - nullable:
                if frame[col].isna().any():
                    raise ValueError(f"Missing values in {name}.{col}")
            for col in ("game_id", "team", "home_team", "away_team"):
                if col in frame:
                    frame[col] = frame[col].astype(str)
                    if frame[col].str.strip().eq("").any():
                        raise ValueError(f"Empty identifier in {name}.{col}")
            for col in ("date", "ts", "results_available_at"):
                if col in frame:
                    frame[col] = pd.to_datetime(
                        [utc(x) if pd.notna(x) else pd.NaT for x in frame[col]], utc=True
                    )
            key = ["game_id", "team"] if name == "team_game_stats" else ["game_id"]
            if frame.duplicated(key).any():
                raise ValueError(f"Duplicate key in {name}: {key}")
            setattr(self, name, frame.sort_values(key).reset_index(drop=True))
        games = self.games
        if games.empty:
            raise ValueError("At least one game is required")
        _numbers(games, ["season"], minimum=1, integer=True)
        _numbers(games, ["home_pts", "away_pts", "ot_periods"], minimum=0, integer=True)
        games["season"] = games.season.astype(int)
        complete = games.home_pts.notna()
        for column in ("away_pts", "ot_periods", "results_available_at"):
            if not games[column].notna().equals(complete):
                raise ValueError("Scores, OT and results_available_at must be present together")
        if (games.home_team == games.away_team).any():
            raise ValueError("A team cannot play itself")
        if (games.ts >= games.date).any():
            raise ValueError("Fixtures must be available before tipoff")
        if (games.loc[complete, "results_available_at"] <= games.loc[complete, "date"]).any():
            raise ValueError("Results must be available after tipoff")
        if (games.loc[complete, "home_pts"] == games.loc[complete, "away_pts"]).any():
            raise ValueError("NBA final scores cannot be tied")
        for name in ("schedule", "team_game_stats"):
            frame = getattr(self, name)
            if not set(frame.game_id).issubset(set(games.game_id)):
                raise ValueError(f"Unknown game_id in {name}")
        stats = self.team_game_stats
        _numbers(stats, ["possessions", "ortg", "drtg"], minimum=0)
        if (stats[["possessions", "ortg", "drtg"]] <= 0).any().any():
            raise ValueError("Possessions and efficiencies must be positive")
        lookup = games.set_index("game_id")
        for row in stats.itertuples():
            game = lookup.loc[row.game_id]
            if row.team not in (game.home_team, game.away_team):
                raise ValueError("Stats team must participate in the game")
            if pd.isna(game.results_available_at) or row.ts < game.results_available_at:
                raise ValueError("Stats cannot precede the game's result availability")
        schedule = self.schedule
        _numbers(schedule, ["rest_days_home", "rest_days_away"], minimum=0)
        _numbers(schedule, ["games_last_7d", "travel_km", "altitude"])
        _numbers(schedule, ["b2b_home", "b2b_away"], minimum=0, integer=True)
        if not schedule[["b2b_home", "b2b_away"]].isin([0, 1]).all().all():
            raise ValueError("b2b flags must be 0 or 1")
        if any(row.ts >= lookup.loc[row.game_id, "date"] for row in schedule.itertuples()):
            raise ValueError("Schedule snapshots must precede tipoff")
        return self
