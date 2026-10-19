"""Validated YAML configuration. All modeling choices live in the config file."""

from copy import deepcopy
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import yaml


def load_config(path: str | Path) -> dict:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    expected = {
        "seed",
        "data",
        "ratings",
        "features",
        "model",
        "evaluation",
        "acceptance",
        "demo",
        "feed",
        "lineups",
        "market",
    }
    if not isinstance(config, dict) or set(config) != expected:
        raise ValueError(f"Config must contain exactly {sorted(expected)}")
    required = {
        "feed": {
            "base_url",
            "timeout_seconds",
            "min_request_interval_seconds",
            "snapshot_database",
            "snapshot_directory",
            "terms_url",
            "terms_reviewed_on",
            "possession_fta_weight",
            "snapshot_shrink_k",
            "preseason_game_weight",
        },
        "lineups": {"max_uncertain_players", "minutes_tolerance", "status_probabilities"},
        "market": {
            "min_probability_edge",
            "probability_stress_buffer",
            "min_expected_value",
            "max_quote_age_minutes",
            "max_scenario_probability_range",
            "probability_sum_tolerance",
            "model_weight_k",
            "prior_equivalent_games",
        },
        "data": {"database", "raw_directory", "calendar_timezone"},
        "ratings": {
            "prior_shrink",
            "season_blend_k",
            "initial_variance",
            "process_noise",
            "observation_noise",
        },
        "features": {
            "league_pace",
            "league_ortg",
            "stats_window",
            "stats_shrink_k",
            "initial_rest_days",
            "rest_cap_days",
            "travel_scale_km",
            "altitude_scale_m",
        },
        "model": {
            "initial_hca",
            "context_window",
            "context_min_games",
            "context_ridge",
            "residual_window",
            "residual_min_games",
            "margin_sigma",
            "total_sigma",
            "minimum_sigma",
            "spread_bins",
        },
        "evaluation": {
            "prediction_lead_minutes",
            "min_train_games",
            "probability_clip",
            "calibration_bins",
            "home_frequency_alpha",
            "home_frequency_beta",
            "qq_probabilities",
            "experiment_directory",
        },
        "demo": {
            "seasons",
            "games_per_season",
            "teams",
            "first_season",
            "start_month",
            "start_day",
            "days_between_rounds",
            "rating_sd",
            "pace_sd",
            "margin_sd",
            "total_sd",
            "result_delay_hours",
            "fixture_lead_days",
        },
        "acceptance": {
            "policy_version",
            "min_evaluation_games",
            "min_seasons",
            "min_games_per_season",
            "min_date_blocks",
            "min_log_loss_improvement",
            "max_season_log_loss_regression",
            "max_ece",
            "max_brier_regression",
            "max_coverage90_error",
            "max_abs_margin_bias",
            "max_abs_total_bias",
            "max_crps_regression",
            "bootstrap_samples",
            "confidence_level",
        },
    }
    for section, keys in required.items():
        if not isinstance(config[section], dict) or set(config[section]) != keys:
            raise ValueError(f"Config {section} must contain exactly {sorted(keys)}")
    for section in ("ratings", "features", "model", "evaluation", "demo", "acceptance", "market"):
        for key, value in config[section].items():
            if key in ("spread_bins", "qq_probabilities", "experiment_directory", "policy_version"):
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{section}.{key} must be numeric")
            if not np.isfinite(value) or value < 0:
                raise ValueError(f"{section}.{key} must be finite and nonnegative")
    if type(config["seed"]) is not int or config["seed"] < 0:
        raise ValueError("seed must be a nonnegative integer")
    for key in ("max_uncertain_players",):
        value = config["lineups"][key]
        if type(value) is not int or not 0 <= value <= 16:
            raise ValueError(f"lineups.{key} must be an integer in [0, 16]")
    probabilities = config["lineups"]["status_probabilities"]
    if not isinstance(probabilities, dict) or set(probabilities) != {
        "out",
        "doubtful",
        "questionable",
        "probable",
        "available",
    }:
        raise ValueError("Invalid lineup status probabilities")
    for value in probabilities.values():
        if type(value) not in (int, float) or not np.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Status probabilities must be in [0, 1]")
    if probabilities["out"] != 0 or probabilities["available"] != 1:
        raise ValueError("out must mean probability 0 and available must mean probability 1")
    tolerance = config["lineups"]["minutes_tolerance"]
    if type(tolerance) not in (int, float) or not np.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("minutes_tolerance must be positive and finite")
    for key in (
        "min_probability_edge",
        "probability_stress_buffer",
        "max_scenario_probability_range",
        "probability_sum_tolerance",
    ):
        if config["market"][key] >= 1:
            raise ValueError(f"market.{key} must be less than 1")
    if config["market"]["probability_sum_tolerance"] <= 0:
        raise ValueError("probability_sum_tolerance must be positive")
    if config["market"]["model_weight_k"] <= 0:
        raise ValueError("market.model_weight_k must be positive")
    value = config["feed"]["preseason_game_weight"]
    if type(value) not in (int, float) or not np.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("feed.preseason_game_weight must be in [0, 1]")
    for key in ("timeout_seconds", "min_request_interval_seconds"):
        value = config["feed"][key]
        if type(value) is not int or value <= 0:
            raise ValueError(f"feed.{key} must be a positive integer")
    for key in ("possession_fta_weight", "snapshot_shrink_k"):
        value = config["feed"][key]
        if type(value) not in (int, float) or not np.isfinite(value) or value <= 0:
            raise ValueError(f"feed.{key} must be positive and finite")
    for key in required["feed"] - {
        "timeout_seconds",
        "min_request_interval_seconds",
        "possession_fta_weight",
        "snapshot_shrink_k",
        "preseason_game_weight",
    }:
        if not isinstance(config["feed"][key], str) or not config["feed"][key].strip():
            raise ValueError(f"feed.{key} must be a nonempty string")
    if config["feed"]["base_url"] != "https://stats.nba.com/stats":
        raise ValueError("NBA adapter only calls the documented NBA stats origin")
    for key, value in config["data"].items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"data.{key} must be a nonempty string")
    try:
        ZoneInfo(config["data"]["calendar_timezone"])
    except ZoneInfoNotFoundError as error:
        raise ValueError("Unknown calendar_timezone") from error
    if not isinstance(config["evaluation"]["experiment_directory"], str):
        raise ValueError("experiment_directory must be a string")
    if not isinstance(config["acceptance"]["policy_version"], str):
        raise ValueError("acceptance.policy_version must be a string")
    if not 0 < config["acceptance"]["confidence_level"] < 1:
        raise ValueError("confidence_level must be in (0, 1)")
    for key in ("max_ece", "max_coverage90_error"):
        if config["acceptance"][key] > 1:
            raise ValueError(f"acceptance.{key} must be <= 1")
    if not 0 <= config["ratings"]["prior_shrink"] <= 1:
        raise ValueError("prior_shrink must be in [0, 1]")
    if not 0 < config["evaluation"]["probability_clip"] < 0.5:
        raise ValueError("probability_clip must be in (0, 0.5)")
    for section, keys in {
        "ratings": ["season_blend_k", "initial_variance", "observation_noise"],
        "features": [
            "league_pace",
            "league_ortg",
            "stats_shrink_k",
            "travel_scale_km",
            "altitude_scale_m",
        ],
        "model": ["context_ridge", "margin_sigma", "total_sigma", "minimum_sigma"],
        "evaluation": ["prediction_lead_minutes", "home_frequency_alpha", "home_frequency_beta"],
        "demo": ["result_delay_hours", "fixture_lead_days", "days_between_rounds"],
    }.items():
        for key in keys:
            if config[section][key] <= 0:
                raise ValueError(f"{section}.{key} must be positive")
    for section, keys in {
        "features": ["stats_window"],
        "model": ["context_window", "context_min_games", "residual_window", "residual_min_games"],
        "evaluation": ["min_train_games", "calibration_bins"],
        "acceptance": [
            "min_evaluation_games",
            "min_seasons",
            "min_games_per_season",
            "min_date_blocks",
            "bootstrap_samples",
        ],
        "demo": [
            "teams",
            "seasons",
            "games_per_season",
            "first_season",
            "start_month",
            "start_day",
        ],
    }.items():
        for key in keys:
            if not isinstance(config[section][key], int) or config[section][key] < 1:
                raise ValueError(f"{section}.{key} must be a positive integer")
    if config["demo"]["teams"] < 2 or config["demo"]["teams"] % 2:
        raise ValueError("demo.teams must be even and at least 2")
    if config["acceptance"]["bootstrap_samples"] < 2:
        raise ValueError("bootstrap_samples must be at least 2")
    for name in ("context", "residual"):
        if config["model"][f"{name}_min_games"] > config["model"][f"{name}_window"]:
            raise ValueError(f"{name}_min_games must not exceed window")
    if config["model"]["residual_min_games"] < 2:
        raise ValueError("residual_min_games must be at least 2")
    if not isinstance(config["model"]["spread_bins"], list):
        raise ValueError("spread_bins must be a list")
    if not isinstance(config["evaluation"]["qq_probabilities"], list):
        raise ValueError("qq_probabilities must be a list")
    edges = np.asarray(config["model"]["spread_bins"], dtype=float)
    if len(edges) < 2 or edges[0] != 0 or not np.all(np.isfinite(edges)):
        raise ValueError("spread_bins must start at zero and contain finite edges")
    if not np.all(np.diff(edges) > 0):
        raise ValueError("spread_bins must be strictly increasing")
    quantiles = np.asarray(config["evaluation"]["qq_probabilities"], dtype=float)
    if not len(quantiles) or not np.all((quantiles > 0) & (quantiles < 1)):
        raise ValueError("QQ probabilities must lie in (0, 1)")
    return deepcopy(config)
