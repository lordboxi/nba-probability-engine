"""Chronological event replay: predictions, results and statistics never travel backward."""

from collections import defaultdict, deque

import numpy as np
import pandas as pd
from scipy.stats import norm

from nbaprob.data.schema import utc
from nbaprob.features.context import context_features
from nbaprob.models.baseline_gaussian import GaussianBaseline
from nbaprob.ratings.team_ratings import TeamRatings


class ReplayEngine:
    """Replay one validated dataset using its publication timestamps.

    Results and statistics at a shared timestamp are processed before forecasts.
    Thus publication at equality is usable, as specified by the as-of contract.
    """

    def __init__(self, tables, config):
        self.tables, self.config = tables, config
        self.ratings = TeamRatings(config)
        self.model = GaussianBaseline(config)
        self.games = {row.game_id: row for row in tables.games.itertuples(index=False)}
        self.stats = defaultdict(lambda: deque(maxlen=config["features"]["stats_window"]))
        self.forecasts: dict[str, dict] = {}
        self.completed = 0
        self.home_wins = 0
        self.events = []
        lead = pd.Timedelta(minutes=config["evaluation"]["prediction_lead_minutes"])
        for game in self.games.values():
            forecast_at = max(game.ts, game.date - lead)
            if forecast_at >= game.date:
                raise ValueError("prediction_lead_minutes must permit a pregame forecast")
            self.events.append((forecast_at, 2, game.game_id, "forecast", game))
            if pd.notna(game.results_available_at):
                self.events.append((game.results_available_at, 0, game.game_id, "result", game))
        for row in tables.team_game_stats.itertuples(index=False):
            self.events.append((row.ts, 1, row.game_id + ":" + row.team, "stats", row))
        self.events.sort(key=lambda event: event[:3])
        self.cursor = 0
        self.as_of = None

    def team_stats(self, team):
        rows = self.stats[team]
        cfg = self.config["features"]
        prior = np.array([cfg["league_pace"], cfg["league_ortg"], cfg["league_ortg"]])
        if not rows:
            return prior
        weight = len(rows) / (len(rows) + cfg["stats_shrink_k"])
        return weight * np.mean(rows, axis=0) + (1 - weight) * prior

    def features(self, game, as_of):
        home_stats = self.team_stats(game.home_team)
        away_stats = self.team_stats(game.away_team)
        rating_home = self.ratings.value(game.season, game.home_team)
        rating_away = self.ratings.value(game.season, game.away_team)
        return {
            "game_id": game.game_id,
            "as_of": as_of.isoformat(),
            "home_team": game.home_team,
            "away_team": game.away_team,
            "rating_home": rating_home,
            "rating_away": rating_away,
            "rating_diff": rating_home - rating_away,
            "pace": float((home_stats[0] + away_stats[0]) / 2),
            "total_rate": float(
                (home_stats[1] + away_stats[2] + away_stats[1] + home_stats[2]) / 2
            ),
            "training_games": self.completed,
            **context_features(self.tables, game, as_of, self.config),
        }

    def _forecast(self, game, at):
        features = self.features(game, at)
        forecast = self.model.predict(features)
        cfg = self.config
        alpha = cfg["evaluation"]["home_frequency_alpha"]
        beta = cfg["evaluation"]["home_frequency_beta"]
        forecast["p_home_frequency"] = (self.home_wins + alpha) / (self.completed + alpha + beta)

        forecast["p_hca_only"] = float(
            norm.cdf(cfg["model"]["initial_hca"] / cfg["model"]["margin_sigma"])
        )
        return {"features": features, **forecast}

    def advance(self, as_of):
        as_of = utc(as_of)
        if self.as_of is not None and as_of < self.as_of:
            raise ValueError("ReplayEngine can only advance forward in time")
        while self.cursor < len(self.events) and self.events[self.cursor][0] <= as_of:
            at, _, _, kind, row = self.events[self.cursor]
            if kind == "forecast":
                self.forecasts[row.game_id] = self._forecast(row, at)
            elif kind == "stats":
                game = self.games[row.game_id]
                # Convert full-game possessions (including OT) to a 48-minute pace.
                pace = row.possessions * 48 / (48 + 5 * game.ot_periods)
                self.stats[row.team].append((pace, row.ortg, row.drtg))
            else:
                forecast = self.forecasts[row.game_id]
                margin, total = row.home_pts - row.away_pts, row.home_pts + row.away_pts
                self.ratings.update(
                    row.season,
                    row.home_team,
                    row.away_team,
                    margin - forecast["mu_margin"],
                    forecast["features"]["pace"],
                )
                self.model.observe(forecast["features"], forecast, margin, total)
                self.completed += 1
                self.home_wins += int(margin > 0)
            self.cursor += 1
        self.as_of = as_of

    def predict(self, game_id, as_of):
        as_of = utc(as_of)
        if game_id not in self.games:
            raise ValueError(f"Unknown game_id: {game_id}")
        game = self.games[game_id]
        if game.ts > as_of:
            raise ValueError("Fixture was not known as of prediction time")
        if as_of >= game.date:
            raise ValueError("v1 predictions must be strictly before tipoff")
        self.advance(as_of)
        return self._forecast(game, as_of)


def build_features(game_id, as_of, tables, config) -> dict:
    """Return auditable as-of features; replay discards all unavailable outcomes."""
    return ReplayEngine(tables, config).predict(game_id, as_of)["features"]
