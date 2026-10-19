"""Proportional two-way de-vig; v1 helper only, not a forecast input."""

from nbaprob.pricing.odds import decimal_to_probability


def proportional_devig(home_decimal: float, away_decimal: float) -> tuple[float, float]:
    home, away = decimal_to_probability(home_decimal), decimal_to_probability(away_decimal)
    return home / (home + away), away / (home + away)
