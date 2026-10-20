"""Shared analysis flow for the CLI and local roster/house comparison UI."""

import hashlib
import json

import yaml

from nbaprob.data.schema import utc
from nbaprob.lineups.scenarios import lineup_forecast, mixture_summary, settlement_scenarios
from nbaprob.pricing.compare import compare_house
from nbaprob.pricing.market_prior import market_assisted_probability
from nbaprob.pricing.reading import house_reading

STARTING_POSITIONS = ("PG", "SG", "SF", "PF", "C")


def validate_selection(document, game, as_of):
    if document.get("game_id") != game.game_id or utc(document["reported_at"]) > utc(as_of):
        raise ValueError("Roster selection belongs to another game or is from the future")
    players = document.get("players", [])
    keys = [str(row["player_id"]) for row in players]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate player in manual roster selection")
    for row in players:
        if row["team"] not in (game.home_team, game.away_team) or type(row["plays"]) is not bool:
            raise ValueError("Selection requires participating teams and boolean plays values")
        if document.get("selection_type") == "positioned_lineup":
            if type(row.get("starter")) is not bool:
                raise ValueError("Positioned lineup requires boolean starter values")
            if row["starter"]:
                if not row["plays"] or row.get("position") not in STARTING_POSITIONS:
                    raise ValueError("Each starter must play and have a starting position")
            elif row.get("position") is not None:
                raise ValueError("Only starters can have a starting position")
    for team in (game.home_team, game.away_team):
        if sum(row["plays"] for row in players if row["team"] == team) < 5:
            raise ValueError(f"Select at least five available players for {team}")
        if document.get("selection_type") == "positioned_lineup":
            positions = [
                row["position"] for row in players if row["team"] == team and row["starter"]
            ]
            if sorted(positions) != sorted(STARTING_POSITIONS):
                raise ValueError(f"Select exactly one starter at PG, SG, SF, PF and C for {team}")


def analyze_forecast(
    base,
    game,
    as_of,
    config,
    *,
    lineup=None,
    selection=None,
    house=None,
    spread=None,
    total_line=None,
    synthetic=False,
    use_market_prior=False,
):
    synthetic = bool(synthetic or (house is not None and house.get("synthetic", False)))
    current = base
    output = {
        "game_id": game.game_id,
        "as_of": utc(as_of).isoformat(),
        "model": base.get("model", "baseline_gaussian_v1"),
        "synthetic": bool(synthetic),
        "features": base["features"],
        "context_coefficients": base.get("context_coefficients", {}),
        "lineup_adjustment_applied": False,
    }
    if "snapshot" in base:
        output.update({key: base[key] for key in ("snapshot", "snapshot_id", "estimation")})
    if "data_readiness" in base:
        output["data_readiness"] = {
            **base["data_readiness"],
            "missing": list(base["data_readiness"]["missing"]),
        }
        output["previous_snapshot"] = base.get("previous_snapshot")
        output["preseason_snapshot"] = base.get("preseason_snapshot")
        if selection is None and lineup is None:
            output["data_readiness"]["missing"].append("selected_lineup")
    if selection is not None:
        validate_selection(selection, game, as_of)
        output["roster_selection"] = selection
        output["lineup_note"] = (
            "Selection recorded. Player names alone do not supply impact ratings."
        )
    if lineup is not None:
        if selection is not None:
            raise ValueError("Use either a basic roster selection or an impact lineup document")
        current = lineup_forecast(base, lineup, game, as_of, config)
        output.update(
            model=current["model"],
            lineup_adjustment_applied=True,
            lineup=current,
            synthetic=bool(synthetic or current["synthetic"]),
        )
        output["margin"] = mixture_summary(current, "margin")
        output["total"] = mixture_summary(current, "total")
        if "data_readiness" in output:
            output["data_readiness"]["missing"].remove("player_impact_ratings")
    else:
        output["margin"] = {
            "family": "normal",
            "mean": base["mu_margin"],
            "sigma": base["sigma_margin"],
        }
        output["total"] = {
            "family": "normal",
            "mean": base["mu_total"],
            "sigma": base["sigma_total"],
        }
    output["p_home_win"] = current["p_home_win"]
    for market, line, key in (
        ("spread", spread, "home_spread"),
        ("total", total_line, "over_total"),
    ):
        if line is not None:
            rows = settlement_scenarios(current, market, line)
            output[key] = {
                "line": line,
                **{
                    field: sum(row["weight"] * row[field] for row in rows)
                    for field in ("win", "push", "loss")
                },
            }
    if house is not None:
        output["house_comparison"] = compare_house(current, house, game.game_id, as_of, config)
        output["house_quote"] = house
        if use_market_prior:
            evidence = base.get("data_readiness", {}).get("evidence_games")
            if evidence is None:
                raise ValueError(
                    "Market-assisted mode requires explicit evidence from NBA snapshots"
                )
            output["market_assisted"] = market_assisted_probability(
                output["house_comparison"], evidence, config
            )
        if (
            "data_readiness" in base
            and output["house_comparison"]["decision"] == "analytical_candidate"
        ):
            output["house_comparison"].update(
                decision="insufficient_evidence",
                candidate=None,
                reason="Snapshot model has not passed real holdout validation; "
                "edge is exploratory only",
            )
        output["house_reading"] = house_reading(output["house_comparison"])
    elif use_market_prior:
        raise ValueError("Market-assisted mode requires a House quote")
    output["config_hash"] = hashlib.sha256(
        yaml.safe_dump(
            {key: value for key, value in config.items() if not key.startswith("_")}, sort_keys=True
        ).encode()
    ).hexdigest()
    output["model_validation"] = "Not yet validated on real NBA holdout data"
    # Validate serialization before UI/download writers receive a partial result.
    json.dumps(output, allow_nan=False)
    return output
