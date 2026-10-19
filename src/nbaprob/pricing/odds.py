"""Decimal/American odds and fair odds with pushes refunded."""

from math import isfinite


def american_to_decimal(odds: float) -> float:
    if not isfinite(odds) or abs(odds) < 100:
        raise ValueError("American odds must be <= -100 or >= +100")
    return 1 + (odds / 100 if odds > 0 else 100 / abs(odds))


def decimal_to_probability(odds: float) -> float:
    if not isfinite(odds) or odds <= 1:
        raise ValueError("Decimal odds must be finite and greater than 1")
    return 1 / odds


def fair_decimal(win: float, push: float = 0.0) -> float:
    if not isfinite(win) or not isfinite(push) or win <= 0 or push < 0 or win + push > 1:
        raise ValueError("Require win > 0, push >= 0, win + push <= 1")
    return (1 - push) / win
