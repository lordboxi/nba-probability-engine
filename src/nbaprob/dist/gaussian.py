"""Pricing conventions from specification section 5.5."""

from dataclasses import asdict, dataclass
from math import floor, isfinite

from scipy.stats import norm


@dataclass(frozen=True)
class Settlement:
    win: float
    push: float
    loss: float

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Gaussian:
    mean: float
    sigma: float

    def __post_init__(self):
        if not isfinite(self.mean) or not isfinite(self.sigma) or self.sigma <= 0:
            raise ValueError("Gaussian requires a finite mean and positive finite sigma")

    def above(self, line: float, *, no_tie_at_zero=False) -> Settlement:
        if not isfinite(line):
            raise ValueError("Line must be finite")
        if no_tie_at_zero and line == 0:
            win = float(norm.cdf(self.mean / self.sigma))
            return Settlement(win, 0.0, 1 - win)
        if float(line).is_integer():
            lower = float(norm.cdf((line - 0.5 - self.mean) / self.sigma))
            upper = float(norm.cdf((line + 0.5 - self.mean) / self.sigma))
            return Settlement(float(norm.sf((line + 0.5 - self.mean) / self.sigma)),
                              upper - lower, lower)
        # For arbitrary non-integer lines, settlement follows integer NBA scores.
        threshold = floor(line) + 0.5
        win = float(norm.sf((threshold - self.mean) / self.sigma))
        return Settlement(win, 0.0, 1 - win)

    def as_dict(self):
        return {"family": "normal", "mean": self.mean, "sigma": self.sigma}


def spread_probabilities(mean: float, sigma: float, spread: float) -> Settlement:
    """Home spread -6.5 means home must win by more than 6.5 points."""
    return Gaussian(mean, sigma).above(-spread, no_tie_at_zero=True)


def total_probabilities(mean: float, sigma: float, line: float) -> Settlement:
    """Win means over, loss means under; integer lines allow a push."""
    return Gaussian(mean, sigma).above(line)
