"""Forward-only market evaluation at the line and odds saved before tipoff."""

import json

from nbaprob.data.schema import utc
from nbaprob.eval.metrics import binary_scores
from nbaprob.pricing.reading import house_reading


def settle_market(market, line, home_points, away_points):
    if market == "moneyline":
        value = home_points - away_points
    elif market == "spread":
        value = home_points - away_points + line
    elif market == "total":
        value = home_points + away_points - line
    else:
        raise ValueError("Unknown settlement market")
    return 0.5 if abs(value) <= 1e-9 else int(value > 0)


def market_scores(forecasts, outcomes, config):
    latest = {}
    for row in sorted(
        forecasts, key=lambda r: (utc(r["as_of"]), utc(r["issued_at"]), r["identity"])
    ):
        if not utc(row["as_of"]) <= utc(row["issued_at"]) < utc(row["tipoff"]):
            continue
        payload = json.loads(row["payload"])
        comparison = payload.get("house_comparison")
        if payload.get("synthetic") or not comparison:
            continue
        latest[row["game_id"], comparison["market"]] = (row, payload, comparison)
    reports, details = {}, []
    for market in ("moneyline", "spread", "total"):
        samples = []
        for (game_id, kind), (row, payload, comparison) in latest.items():
            if (
                kind != market
                or game_id not in outcomes
                or comparison["decision"] == "refresh_quote"
            ):
                continue
            # as_of can be older than the actual server issue time. A price must
            # still be fresh when the forecast was really issued to count here.
            quoted_at = comparison.get("quoted_at")
            if quoted_at is not None:
                age = (utc(row["issued_at"]) - utc(quoted_at)).total_seconds() / 60
                if age < 0 or age > config["market"]["max_quote_age_minutes"]:
                    continue
            outcome = outcomes[game_id]
            actual = settle_market(
                market, comparison["line"], outcome["home_points"], outcome["away_points"]
            )
            first = comparison["sides"][0]
            reading = payload.get("house_reading") or house_reading(comparison)
            sample = {
                "actual": actual,
                "model": first["model_probability_no_push"],
                "house": first["house_fair_probability"],
            }
            assisted = payload.get("market_assisted")
            if assisted and assisted["market"] == market and assisted["line"] == comparison["line"]:
                sample["assisted"] = assisted["sides"][0]["assisted_probability_no_push"]
            samples.append(sample)
            detail = {
                "game_id": game_id,
                "forecast_id": row["identity"],
                "market": market,
                "line": comparison["line"],
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "tipoff": row["tipoff"],
                "home_points": outcome["home_points"],
                "away_points": outcome["away_points"],
            }
            for name, pick in (
                ("model", reading["most_likely_model"]),
                ("house", reading["most_likely_house"]),
            ):
                side = next((side for side in comparison["sides"] if side["side"] == pick), None)
                won = actual == (1 if pick == first["side"] else 0)
                result = (
                    "no_pick"
                    if side is None
                    else "push"
                    if actual == 0.5
                    else "win"
                    if won
                    else "loss"
                )
                price = side["offered_decimal"] if side else None
                detail[f"{name}_pick"] = pick
                detail[f"{name}_result"] = result
                detail[f"{name}_paper_return"] = (
                    None
                    if price is None or result == "no_pick"
                    else 0.0
                    if result == "push"
                    else price - 1
                    if result == "win"
                    else -1.0
                )
            details.append(detail)
        resolved = [sample for sample in samples if sample["actual"] != 0.5]
        matched = [sample for sample in resolved if "assisted" in sample]
        market_details = [row for row in details if row["market"] == market]
        report = {
            "settled_games": len(samples),
            "push_games": len(samples) - len(resolved),
            "scored_games": len(resolved),
            "scores": {
                name: binary_scores(
                    [r["actual"] for r in resolved],
                    [r[name] for r in resolved],
                    config["evaluation"]["probability_clip"],
                )
                for name in ("model", "house")
            }
            if resolved
            else {},
            "matched_assisted_games": len(matched),
            "matched_assisted_scores": {
                name: binary_scores(
                    [r["actual"] for r in matched],
                    [r[name] for r in matched],
                    config["evaluation"]["probability_clip"],
                )
                for name in ("model", "house", "assisted")
            }
            if matched
            else {},
            "picks": {},
        }
        for name in ("model", "house"):
            chosen = [r for r in market_details if r[f"{name}_result"] != "no_pick"]
            wins = sum(r[f"{name}_result"] == "win" for r in chosen)
            losses = sum(r[f"{name}_result"] == "loss" for r in chosen)
            priced = [r for r in chosen if r[f"{name}_paper_return"] is not None]
            report["picks"][name] = {
                "wins": wins,
                "losses": losses,
                "pushes": len(chosen) - wins - losses,
                "hit_rate": wins / (wins + losses) if wins + losses else None,
                "priced_picks": len(priced),
                "paper_profit_units": sum(r[f"{name}_paper_return"] for r in priced)
                if priced
                else None,
                "paper_roi": sum(r[f"{name}_paper_return"] for r in priced) / len(priced)
                if priced
                else None,
            }
        reports[market] = report
    return {
        "markets": reports,
        "details": details,
        "policy": "Latest real pregame forecast per game per market, at its saved line. "
        "Stale quotes excluded. Pushes excluded from conditional probability scores/hit rate "
        "and refunded in equal-unit paper returns. Tied picks abstain. "
        "Markets on the same game are correlated; this is descriptive, not validation.",
    }
