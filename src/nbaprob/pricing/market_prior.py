"""A transparent cold-start market reference; never evidence of independent edge."""


def market_assisted_probability(comparison, evidence_games, config):
    if evidence_games < 0:
        raise ValueError("Evidence games must be nonnegative")
    weight = evidence_games / (evidence_games + config["market"]["model_weight_k"])
    sides = [
        {
            "side": row["side"],
            "independent_probability_no_push": row["model_probability_no_push"],
            "house_probability_no_push": row["house_fair_probability"],
            "assisted_probability_no_push": (
                weight * row["model_probability_no_push"]
                + (1 - weight) * row["house_fair_probability"]
            ),
        }
        for row in comparison["sides"]
    ]
    first, second = sides
    favorite = None
    if abs(first["house_probability_no_push"] - second["house_probability_no_push"]) > 1e-12:
        favorite = max(sides, key=lambda row: row["house_probability_no_push"])["side"]
    line = comparison["line"]
    return {
        "market": comparison["market"],
        "line": line,
        "model_weight": weight,
        "house_weight": 1 - weight,
        "evidence_games": evidence_games,
        "house_favored_outcome": favorite,
        "handicap_favorite": (
            ("home" if line < 0 else "away")
            if comparison["market"] == "spread" and line != 0
            else None
        ),
        "sides": sides,
        "decision": "refresh_quote"
        if comparison["decision"] == "refresh_quote"
        else "market_reference_only",
        "candidate": None,
        "uses_comparison_house_as_input": True,
        "note": "Sample-size blend, not calibrated. "
        "Same-house input cannot establish independent edge. "
        "Probabilities are conditional on no push; no assisted EV or stake is asserted.",
    }
