import math

import pytest
from scipy.stats import norm

from nbaprob.dist.gaussian import Gaussian, spread_probabilities, total_probabilities
from nbaprob.pricing.devig import proportional_devig
from nbaprob.pricing.odds import american_to_decimal, decimal_to_probability, fair_decimal


def test_half_point_matches_specification():
    result = spread_probabilities(4, 12, -6.5)
    assert result.win == pytest.approx(norm.sf((6.5 - 4) / 12))
    assert result.push == 0
    assert result.win + result.loss == pytest.approx(1)


def test_integer_matches_specification():
    result = spread_probabilities(4, 12, -7)
    assert result.win == pytest.approx(norm.sf((7.5 - 4) / 12))
    assert result.push == pytest.approx(norm.cdf((7.5 - 4) / 12) - norm.cdf((6.5 - 4) / 12))
    assert result.loss == pytest.approx(norm.cdf((6.5 - 4) / 12))


@pytest.mark.parametrize("line", [-1000, -7.5, -7, -0.5, 0, 0.25, 6.5, 7, 7.75, 1000])
def test_probabilities_are_normalized_and_nonnegative(line):
    result = spread_probabilities(2.5, 12, line)
    assert all(0 <= value <= 1 for value in (result.win, result.push, result.loss))
    assert result.win + result.push + result.loss == pytest.approx(1)


def test_no_push_on_pickem_and_arbitrary_lines_follow_integer_scores():
    result = spread_probabilities(4, 12, 0)
    assert result.win == pytest.approx(norm.cdf(4 / 12))
    assert result.push == 0
    assert spread_probabilities(4, 12, -7.25) == spread_probabilities(4, 12, -7.5)


def test_total_lines_and_monotonicity():
    assert total_probabilities(228, 19, 228.5).push == 0
    assert total_probabilities(228, 19, 228).push > 0
    assert total_probabilities(228, 19, 230).win < total_probabilities(228, 19, 220).win


def test_odds_and_push_refunds():
    assert american_to_decimal(-110) == pytest.approx(1 + 100 / 110)
    assert american_to_decimal(150) == 2.5
    assert decimal_to_probability(2) == 0.5
    assert proportional_devig(1.91, 1.91) == (0.5, 0.5)
    assert fair_decimal(0.45, 0.1) == 2


@pytest.mark.parametrize("sigma", [0, -1, math.inf, math.nan])
def test_invalid_distributions_rejected(sigma):
    with pytest.raises(ValueError):
        Gaussian(0, sigma)


def test_invalid_lines_rejected():
    with pytest.raises(ValueError):
        spread_probabilities(0, 12, math.nan)
