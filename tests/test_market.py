from copy import deepcopy

import pytest
from scipy.stats import norm

from nbaprob.pricing.compare import compare_house


@pytest.fixture
def forecast():
    return {
        "mu_margin": float(norm.ppf(0.6) * 12),
        "sigma_margin": 12.0,
        "mu_total": 228.0,
        "sigma_total": 19.0,
        "p_home_win": 0.6,
    }


@pytest.fixture
def quote():
    return {
        "game_id": "test",
        "market": "moneyline",
        "input_type": "decimal_odds",
        "primary": 2.0,
        "secondary": 2.0,
        "quoted_at": "2026-10-19T08:00:00Z",
    }


def compare(forecast, quote, config):
    return compare_house(forecast, quote, "test", "2026-10-19T08:00:00Z", config)


def test_value_selection_uses_price_and_stress_not_only_win_rate(forecast, quote, config):
    result = compare(forecast, quote, config)
    assert result["candidate"] == "home"
    assert result["decision"] == "analytical_candidate"
    home = result["sides"][0]
    assert home["expected_value_per_unit"] == pytest.approx(0.2)
    assert home["stress_expected_value_per_unit"] == pytest.approx(0.14)
    # A 60% favorite at 1.50 is a negative-value quote.
    quote.update(primary=1.5, secondary=2.8)
    result = compare(forecast, quote, config)
    assert result["sides"][0]["expected_value_per_unit"] < 0
    assert result["candidate"] != "home"


def test_probability_only_cannot_claim_expected_value(forecast, quote, config):
    quote.update(input_type="fair_probability", primary=0.5, secondary=0.5)
    result = compare(forecast, quote, config)
    assert result["decision"] == "comparison_only"
    assert result["candidate"] is None
    assert result["sides"][0]["probability_edge"] == pytest.approx(0.1)
    assert result["sides"][0]["expected_value_per_unit"] is None


def test_implied_probabilities_are_devigged(forecast, quote, config):
    quote.update(input_type="implied_probability", primary=0.55, secondary=0.55)
    result = compare(forecast, quote, config)
    assert result["overround"] == pytest.approx(0.1)
    assert result["sides"][0]["house_fair_probability"] == 0.5


def test_push_refund_is_included_in_ev(forecast, quote, config):
    quote.update(market="total", line=228)
    result = compare(forecast, quote, config)
    row = result["sides"][0]
    assert row["model_push"] > 0
    assert row["expected_value_per_unit"] == pytest.approx(0, abs=1e-12)
    assert row["expected_value_per_unit"] == pytest.approx(
        row["model_win"] * (row["offered_decimal"] - 1) - row["model_loss"]
    )


def test_high_lineup_sensitivity_waits_instead_of_choosing(forecast, quote, config):
    first, second = deepcopy(forecast), deepcopy(forecast)
    first.update(weight=0.5, mu_margin=-8)
    second.update(weight=0.5, mu_margin=8)
    result = compare({"scenarios": [first, second]}, quote, config)
    assert result["decision"] == "wait_for_lineup"
    assert result["candidate"] is None


def test_neither_side_qualifies_returns_no_selection(forecast, quote, config):
    forecast["mu_margin"] = 0
    quote.update(primary=1.91, secondary=1.91)
    result = compare(forecast, quote, config)
    assert result["decision"] == "no_selection"


@pytest.mark.parametrize(
    "mutation",
    ["future", "wrong_game", "bad_odds", "fair_sum", "percent", "missing_implied_side", "bad_line"],
)
def test_bad_or_misaligned_quotes_rejected(forecast, quote, config, mutation):
    if mutation == "future":
        quote["quoted_at"] = "2026-10-19T08:01:00Z"
    elif mutation == "wrong_game":
        quote["game_id"] = "other"
    elif mutation == "bad_odds":
        quote["primary"] = 1
    elif mutation == "fair_sum":
        quote.update(input_type="fair_probability", primary=0.6, secondary=0.6)
    elif mutation == "percent":
        quote.update(input_type="fair_probability", primary=60, secondary=40)
    elif mutation == "missing_implied_side":
        quote.update(input_type="implied_probability", primary=0.6, secondary=None)
    else:
        quote.update(market="spread", line=float("nan"))
    with pytest.raises(ValueError):
        compare(forecast, quote, config)


def test_stale_quote_requests_refresh(forecast, quote, config):
    quote["quoted_at"] = "2026-10-19T06:00:00Z"
    assert compare(forecast, quote, config)["decision"] == "refresh_quote"


def test_american_odds_match_decimal_odds(forecast, quote, config):
    expected = compare(forecast, quote, config)["sides"]
    quote.update(input_type="american_odds", primary=100, secondary=100)
    assert compare(forecast, quote, config)["sides"] == expected
