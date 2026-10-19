"""Adaptive Kalman-style team net ratings with season priors and shrinkage."""

from dataclasses import dataclass


@dataclass
class Rating:
    prior: float
    season_rating: float
    variance: float
    games: int = 0

    def effective(self, blend_k: float) -> float:
        weight = self.games / (self.games + blend_k)
        return weight * self.season_rating + (1 - weight) * self.prior


class TeamRatings:
    def __init__(self, config):
        self.config = config["ratings"]
        self.states: dict[tuple[int, str], Rating] = {}

    def state(self, season: int, team: str) -> Rating:
        key = (season, team)
        if key not in self.states:
            previous = [(s, r) for (s, t), r in self.states.items() if t == team and s < season]
            prior = 0.0
            if previous:
                _, rating = max(previous, key=lambda pair: pair[0])
                prior = self.config["prior_shrink"] * rating.effective(
                    self.config["season_blend_k"]
                )
            self.states[key] = Rating(prior, prior, self.config["initial_variance"])
        return self.states[key]

    def value(self, season: int, team: str) -> float:
        return self.state(season, team).effective(self.config["season_blend_k"])

    def update(self, season, home, away, residual, pace):
        home_state, away_state = self.state(season, home), self.state(season, away)
        q = self.config["process_noise"]
        home_var, away_var = home_state.variance + q, away_state.variance + q
        denominator = home_var + away_var + self.config["observation_noise"]
        gain_home, gain_away = home_var / denominator, away_var / denominator
        delta = residual * 100 / pace
        home_state.season_rating += gain_home * delta
        away_state.season_rating -= gain_away * delta
        home_state.variance = (1 - gain_home) * home_var
        away_state.variance = (1 - gain_away) * away_var
        home_state.games += 1
        away_state.games += 1
        return gain_home, gain_away
