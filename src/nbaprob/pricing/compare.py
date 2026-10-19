"""Separate house estimates, actual offered odds and model scenario sensitivity."""

from math import isfinite

from nbaprob.data.schema import utc
from nbaprob.lineups.scenarios import settlement_scenarios
from nbaprob.pricing.odds import american_to_decimal, decimal_to_probability


def compare_house(forecast, quote, game_id, as_of, config):
    if quote.get("game_id") != game_id:
        raise ValueError("House quote game_id does not match the forecast")
    as_of, quoted_at = utc(as_of), utc(quote["quoted_at"])
    if quoted_at > as_of:
        raise ValueError("House quote comes from the future")
    market, line = quote["market"], quote.get("line")
    if market == "moneyline" and line is not None:
        raise ValueError("Moneyline quotes must not have a spread/total line")
    if market in ("spread", "total") and (type(line) not in (int, float) or not isfinite(line)):
        raise ValueError("Spread and total quotes require a finite line")
    kind = quote["input_type"]
    first, second = quote["primary"], quote.get("secondary")
    if type(first) not in (int, float) or not isfinite(first):
        raise ValueError("House primary value must be finite numeric data")
    if second is not None and (type(second) not in (int, float) or not isfinite(second)):
        raise ValueError("House secondary value must be finite numeric data")
    prices = [quote.get("primary_decimal"), quote.get("secondary_decimal")]
    if kind in ("decimal_odds", "american_odds"):
        if second is None:
            raise ValueError("Both sides are required to remove the overround")
        prices = (
            [first, second]
            if kind == "decimal_odds"
            else [american_to_decimal(first), american_to_decimal(second)]
        )
        raw = [decimal_to_probability(value) for value in prices]
    elif kind in ("fair_probability", "implied_probability"):
        if second is None and kind == "fair_probability":
            second = 1 - first
        if second is None or not all(isfinite(p) and 0 < p < 1 for p in (first, second)):
            raise ValueError(
                "Probabilities must be fractions in (0, 1); implied inputs need both sides"
            )
        raw = [float(first), float(second)]
    else:
        raise ValueError("Unknown house input_type")
    total = sum(raw)
    if (
        kind == "fair_probability"
        and abs(total - 1) > config["market"]["probability_sum_tolerance"]
    ):
        raise ValueError("Declared fair probabilities must sum to 1")
    house = [raw[0] / total, raw[1] / total]
    for price in prices:
        if price is not None:
            if type(price) not in (int, float):
                raise ValueError("Offered decimal odds must be numeric")
            decimal_to_probability(price)
    rows = settlement_scenarios(forecast, market, line)
    labels = ("over", "under") if market == "total" else ("home", "away")
    sides = []
    cfg = config["market"]
    for index, label in enumerate(labels):
        wins = [row["win"] if index == 0 else row["loss"] for row in rows]
        losses = [row["loss"] if index == 0 else row["win"] for row in rows]
        win = sum(row["weight"] * value for row, value in zip(rows, wins, strict=True))
        push = sum(row["weight"] * row["push"] for row in rows)
        loss = sum(row["weight"] * value for row, value in zip(rows, losses, strict=True))
        if win + loss <= 0 or any(
            w + loss_value <= 0 for w, loss_value in zip(wins, losses, strict=True)
        ):
            raise ValueError(
                "Market is numerically all pushes; no conditional comparison is available"
            )
        conditional = win / (win + loss)
        scenario_p = [w / (w + loss_value) for w, loss_value in zip(wins, losses, strict=True)]
        price = prices[index]
        ev = stressed_ev = None
        if price is not None:
            ev = win * (price - 1) - loss
            stressed_values = []
            for w, loss_value in zip(wins, losses, strict=True):
                non_push = w + loss_value
                stressed_win = max(0.0, w - cfg["probability_stress_buffer"] * non_push)
                stressed_values.append(stressed_win * (price - 1) - (non_push - stressed_win))
            stressed_ev = min(stressed_values)
        sides.append(
            {
                "side": label,
                "model_win": win,
                "model_push": push,
                "model_loss": loss,
                "model_probability_no_push": conditional,
                "house_fair_probability": house[index],
                "probability_edge": conditional - house[index],
                "scenario_probability_min": min(scenario_p),
                "scenario_probability_max": max(scenario_p),
                "offered_decimal": price,
                "break_even_probability": 1 / price if price else None,
                "expected_value_per_unit": ev,
                "stress_expected_value_per_unit": stressed_ev,
            }
        )
    stale = (as_of - quoted_at).total_seconds() / 60 > cfg["max_quote_age_minutes"]
    uncertainty = max(s["scenario_probability_max"] - s["scenario_probability_min"] for s in sides)
    candidate = None
    if stale:
        decision, reason = "refresh_quote", "House quote is older than the configured maximum age"
    elif uncertainty > cfg["max_scenario_probability_range"]:
        decision, reason = (
            "wait_for_lineup",
            "Player availability changes the market probability too much",
        )
    elif not all(price is not None for price in prices):
        decision, reason = (
            "comparison_only",
            "Actual offered odds are needed to calculate expected value",
        )
    else:
        qualified = [
            s
            for s in sides
            if s["probability_edge"] >= cfg["min_probability_edge"]
            and s["expected_value_per_unit"] >= cfg["min_expected_value"]
            and s["stress_expected_value_per_unit"] >= cfg["min_expected_value"]
        ]
        if qualified:
            candidate = max(qualified, key=lambda row: row["stress_expected_value_per_unit"])[
                "side"
            ]
            decision, reason = (
                "analytical_candidate",
                "Price, edge and scenario stress checks qualify",
            )
        else:
            decision, reason = (
                "no_selection",
                "Neither side clears all configured value and stress checks",
            )
    return {
        "market": market,
        "line": line,
        "quoted_at": quoted_at.isoformat(),
        "input_type": kind,
        "raw_probability_sum": total,
        "overround": None if kind == "fair_probability" else total - 1,
        "sides": sides,
        "decision": decision,
        "candidate": candidate,
        "reason": reason,
        "model_validation": "experimental; not a validated selection strategy",
        "stress_definition": "Lineup stress minus a probability buffer, not a confidence interval",
    }
