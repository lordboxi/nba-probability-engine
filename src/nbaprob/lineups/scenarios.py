"""Exact availability mixtures with 240-minute rotations in every supported scenario."""

from itertools import product
from math import isfinite

import numpy as np
from scipy.stats import norm

from nbaprob.data.schema import utc
from nbaprob.dist.gaussian import spread_probabilities, total_probabilities


def validate_lineup(document, game, as_of, config):
    if document.get("game_id") != game.game_id:
        raise ValueError("Lineup game_id does not match the selected game")
    if utc(document["reported_at"]) > as_of:
        raise ValueError("Lineup was not available as of prediction time")
    if not document.get("rating_source") or not document.get("probability_source"):
        raise ValueError("Lineup requires rating_source and probability_source")
    players = document.get("players", [])
    if not players:
        raise ValueError("Lineup requires player rows")
    ids = set()
    validated = []
    for player in players:
        row = dict(player)
        player_id = str(row["player_id"])
        row["player_id"] = player_id
        if player_id in ids:
            raise ValueError("Duplicate player_id in lineup")
        ids.add(player_id)
        if row["team"] not in (game.home_team, game.away_team):
            raise ValueError("Lineup player must belong to one of the game's teams")
        if type(row["starter"]) is not bool:
            raise ValueError("starter must be a boolean")
        if utc(row["rating_as_of"]) > as_of:
            raise ValueError("Player impact rating is from the future")
        status = row["status"]
        if status not in config["lineups"]["status_probabilities"]:
            raise ValueError(f"Unknown player status: {status}")
        probability = row.get("play_probability")
        if probability is None:
            probability = config["lineups"]["status_probabilities"][status]
        if (
            type(probability) not in (int, float)
            or not isfinite(probability)
            or not 0 <= probability <= 1
        ):
            raise ValueError("play_probability must be in [0, 1]")
        if (status == "out" and probability != 0) or (status == "available" and probability != 1):
            raise ValueError("Status conflicts with play_probability")
        row["play_probability"] = float(probability)
        for field in ("expected_minutes", "baseline_minutes", "offense_impact", "defense_impact"):
            if not isinstance(row[field], (int, float)) or not isfinite(row[field]):
                raise ValueError(f"{field} must be finite numeric data")
        for field in ("expected_minutes", "baseline_minutes"):
            if not 0 <= row[field] <= 48:
                raise ValueError(f"{field} must be in [0, 48]")
        validated.append(row)
    tolerance = config["lineups"]["minutes_tolerance"]
    for team in (game.home_team, game.away_team):
        roster = [row for row in validated if row["team"] == team]
        if sum(row["starter"] for row in roster) not in (0, 5):
            raise ValueError(f"Select either zero or five projected starters for {team}")
        if abs(sum(row["baseline_minutes"] for row in roster) - 240) > tolerance:
            raise ValueError(f"Baseline minutes for {team} must sum to 240")
        if sum(row["expected_minutes"] for row in roster) <= 0:
            raise ValueError("Expected minutes must have positive total weight")
    uncertain = [row for row in validated if 0 < row["play_probability"] < 1]
    if len(uncertain) > config["lineups"]["max_uncertain_players"]:
        raise ValueError("Too many uncertain players for exact scenario enumeration")
    return validated


def allocate_minutes(roster, available, tolerance):
    """Scale projected rotation weights, cap at 48, then redistribute remaining minutes."""
    active = np.asarray([row["player_id"] in available for row in roster], dtype=bool)
    if active.sum() < 5:
        raise ValueError("A supported scenario leaves fewer than five active players; add reserves")
    weights = np.asarray([row["expected_minutes"] for row in roster], dtype=float)
    minutes = np.zeros(len(roster))
    remaining = 240.0
    open_slots = active.copy()
    while remaining > tolerance:
        current_weights = np.where(open_slots, weights, 0)
        if current_weights.sum() == 0:
            current_weights = open_slots.astype(float)
        allocation = remaining * current_weights / current_weights.sum()
        allocation = np.minimum(allocation, np.where(open_slots, 48 - minutes, 0))
        minutes += allocation
        remaining = 240 - float(minutes.sum())
        open_slots = active & (minutes < 48 - tolerance)
        if remaining > tolerance and not open_slots.any():
            raise ValueError("Unable to allocate a complete rotation")
    starters = sorted(
        [index for index, row in enumerate(roster) if row["player_id"] in available],
        key=lambda index: (
            not roster[index]["starter"],
            -minutes[index],
            str(roster[index]["player_id"]),
        ),
    )[:5]
    return minutes, [roster[index]["player_id"] for index in starters]


def lineup_forecast(base, document, game, as_of, config):
    """Adjust the baseline by rotation changes, rather than adding full player ratings twice."""
    as_of = utc(as_of)
    players = validate_lineup(document, game, as_of, config)
    uncertain = [row for row in players if 0 < row["play_probability"] < 1]
    fixed = {row["player_id"] for row in players if row["play_probability"] == 1}
    expected_minutes = {row["player_id"]: 0.0 for row in players}
    start_probabilities = dict.fromkeys(expected_minutes, 0.0)
    scenarios = []
    for choices in product((False, True), repeat=len(uncertain)):
        weight = 1.0
        available = set(fixed)
        for player, plays in zip(uncertain, choices, strict=True):
            probability = player["play_probability"]
            weight *= probability if plays else 1 - probability
            if plays:
                available.add(player["player_id"])
        changes = {}
        rotations = {}
        for team in (game.home_team, game.away_team):
            roster = [row for row in players if row["team"] == team]
            minutes, starters = allocate_minutes(
                roster, available, config["lineups"]["minutes_tolerance"]
            )
            offense = defense = 0.0
            rotations[team] = {}
            for row, minute in zip(roster, minutes, strict=True):
                delta = (minute - row["baseline_minutes"]) / 48
                offense += row["offense_impact"] * delta
                defense += row["defense_impact"] * delta
                rotations[team][row["player_id"]] = float(minute)
                expected_minutes[row["player_id"]] += weight * minute
                start_probabilities[row["player_id"]] += weight * (row["player_id"] in starters)
            changes[team] = (offense, defense)
        home_o, home_d = changes[game.home_team]
        away_o, away_d = changes[game.away_team]
        factor = base["features"]["pace"] / 100
        scenarios.append(
            {
                "weight": weight,
                "mu_margin": base["mu_margin"] + factor * (home_o + home_d - away_o - away_d),
                "mu_total": base["mu_total"] + factor * (home_o - home_d + away_o - away_d),
                "sigma_margin": base["sigma_margin"],
                "sigma_total": base["sigma_total"],
                "unavailable_players": sorted(
                    row["player_id"] for row in players if row["player_id"] not in available
                ),
                "rotation_minutes": rotations,
            }
        )
    for scenario in scenarios:
        scenario["p_home_win"] = float(norm.cdf(scenario["mu_margin"] / scenario["sigma_margin"]))
    win = sum(row["weight"] * row["p_home_win"] for row in scenarios)
    return {
        "model": "experimental_lineup_v2",
        "p_home_win": win,
        "baseline_p_home_win": base["p_home_win"],
        "scenarios": scenarios,
        "availability_assumption": "independent players; exact enumeration",
        "rating_source": document["rating_source"],
        "probability_source": document["probability_source"],
        "reported_at": document["reported_at"],
        "synthetic": bool(document.get("synthetic", False)),
        "statistics_provenance": document.get("statistics_provenance", {}),
        "minutes_policy": document.get("minutes_policy"),
        "players": [
            {
                **row,
                "weighted_minutes": float(expected_minutes[row["player_id"]]),
                "starting_probability": float(start_probabilities[row["player_id"]]),
            }
            for row in players
        ],
    }


def settlement_scenarios(forecast, market, line=None):
    scenarios = forecast.get("scenarios", [{"weight": 1.0, **forecast}])
    rows = []
    for scenario in scenarios:
        if market == "moneyline":
            probability = float(norm.cdf(scenario["mu_margin"] / scenario["sigma_margin"]))
            values = {"win": probability, "push": 0.0, "loss": 1 - probability}
        elif market == "spread" and line is not None:
            values = spread_probabilities(
                scenario["mu_margin"], scenario["sigma_margin"], line
            ).as_dict()
        elif market == "total" and line is not None:
            values = total_probabilities(
                scenario["mu_total"], scenario["sigma_total"], line
            ).as_dict()
        else:
            raise ValueError(
                "Market must be moneyline, spread or total; spread/total require a line"
            )
        rows.append({"weight": scenario["weight"], **values})
    return rows


def mixture_summary(forecast, target):
    rows = forecast["scenarios"]
    mean = sum(row["weight"] * row[f"mu_{target}"] for row in rows)
    variance = sum(
        row["weight"] * (row[f"sigma_{target}"] ** 2 + (row[f"mu_{target}"] - mean) ** 2)
        for row in rows
    )
    return {
        "family": "normal_mixture",
        "mean": mean,
        "sigma": float(np.sqrt(variance)),
        "components": [
            {"weight": row["weight"], "mean": row[f"mu_{target}"], "sigma": row[f"sigma_{target}"]}
            for row in rows
        ],
    }
