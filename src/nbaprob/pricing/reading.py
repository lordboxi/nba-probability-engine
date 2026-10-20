"""Describe frozen House comparisons without treating an unvalidated edge as a pick."""


def house_reading(comparison):
    sides = comparison["sides"]

    def leader(field):
        if any(row[field] is None for row in sides):
            return None
        first, second = sides
        if abs(first[field] - second[field]) <= 1e-12:
            return None
        return max(sides, key=lambda row: row[field])["side"]

    return {
        "most_likely_model": leader("model_probability_no_push"),
        "most_likely_house": leader("house_fair_probability"),
        "highest_ev_side": leader("expected_value_per_unit"),
        "positive_ev_sides": [
            row["side"]
            for row in sides
            if row["expected_value_per_unit"] is not None and row["expected_value_per_unit"] > 0
        ],
        "decision": comparison["decision"],
        "candidate": comparison["candidate"],
        "policy": "Most likely means highest independent probability conditional on no push. "
        "EV uses offered odds; neither ranking establishes a validated betting strategy.",
    }
