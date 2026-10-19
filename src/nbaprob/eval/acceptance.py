"""Project-owned v1 statistical gates; policy is frozen in each experiment config."""

import numpy as np
import pandas as pd


def paired_day_bootstrap(predictions, config):
    """Resample whole local game dates, preserving within-day dependence and pairing.

    Each replicate is a game-weighted mean of paired log-loss differences. This
    is a descriptive block bootstrap, not a correction for repeated model searches.
    """
    clip = config["evaluation"]["probability_clip"]
    y = predictions.home_win.to_numpy(dtype=float)

    def losses(p):
        p = np.clip(np.asarray(p, dtype=float), clip, 1 - clip)
        return -(y * np.log(p) + (1 - y) * np.log1p(-p))

    days = (
        pd.to_datetime(predictions.date, utc=True)
        .dt.tz_convert(config["data"]["calendar_timezone"])
        .dt.strftime("%Y-%m-%d")
    )
    grouped = (
        pd.DataFrame(
            {
                "day": days,
                "delta": losses(predictions.p_home_win) - losses(predictions.p_hca_only),
            }
        )
        .groupby("day")
        .delta.agg(["sum", "count"])
    )
    result = {
        "reference": "hca_only",
        "unit": "local_game_date",
        "n_blocks": len(grouped),
        "mean_delta": float(grouped["sum"].sum() / len(y)),
        "confidence_level": config["acceptance"]["confidence_level"],
        "lower": None,
        "upper": None,
    }
    if len(grouped) < 2:
        return result
    rng = np.random.default_rng(config["seed"])
    draws = rng.integers(
        0, len(grouped), size=(config["acceptance"]["bootstrap_samples"], len(grouped))
    )
    sums, counts = grouped["sum"].to_numpy(), grouped["count"].to_numpy()
    samples = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    tail = (1 - result["confidence_level"]) / 2
    result["lower"], result["upper"] = [float(x) for x in np.quantile(samples, [tail, 1 - tail])]
    return result


def assess_v1(predictions, metadata, metrics, config):
    """Assess numerical model gates, without claiming protocol or software verification."""
    policy = config["acceptance"]
    bootstrap = paired_day_bootstrap(predictions, config)
    checks = []

    def check(name, passed, observed, rule):
        checks.append({"name": name, "passed": bool(passed), "observed": observed, "rule": rule})

    check(
        "real_data",
        metadata.get("synthetic") is False
        and bool(metadata.get("source"))
        and bool(metadata.get("usage_note")),
        metadata.get("synthetic"),
        "Explicit real-data metadata, source and usage note required",
    )
    check(
        "evaluation_games",
        len(predictions) >= policy["min_evaluation_games"],
        len(predictions),
        f">= {policy['min_evaluation_games']}",
    )
    season_counts = {str(k): int(v) for k, v in predictions.groupby("season").size().items()}
    check(
        "evaluation_seasons",
        len(season_counts) >= policy["min_seasons"],
        len(season_counts),
        f">= {policy['min_seasons']}",
    )
    check(
        "games_per_season",
        min(season_counts.values()) >= policy["min_games_per_season"],
        season_counts,
        f"every season >= {policy['min_games_per_season']}",
    )
    check(
        "date_blocks",
        bootstrap["n_blocks"] >= policy["min_date_blocks"],
        bootstrap["n_blocks"],
        f">= {policy['min_date_blocks']}",
    )
    eligibility = all(item["passed"] for item in checks)
    model = metrics["models"]["baseline_gaussian_v1"]
    improvement = -model["log_loss_delta_vs_hca_only"]
    check(
        "log_loss_improvement",
        improvement >= policy["min_log_loss_improvement"],
        improvement,
        f">= {policy['min_log_loss_improvement']} versus HCA-only",
    )
    check(
        "paired_log_loss_interval",
        bootstrap["upper"] is not None and bootstrap["upper"] < 0,
        bootstrap["upper"],
        "Upper endpoint of paired date-block CI < 0",
    )
    other_best = min(
        metrics["models"][name]["log_loss"]
        for name in ("hca_only", "expanding_home_frequency", "coin_flip")
    )
    check(
        "simple_baselines",
        model["log_loss"] <= other_best,
        model["log_loss"] - other_best,
        "Log loss <= every simple comparator on identical games",
    )
    worst_season = max(s["log_loss_delta_vs_hca_only"] for s in metrics["by_season"].values())
    check(
        "season_stability",
        worst_season <= policy["max_season_log_loss_regression"],
        worst_season,
        f"each season delta <= {policy['max_season_log_loss_regression']}",
    )
    check(
        "calibration_ece",
        model["ece"] <= policy["max_ece"],
        model["ece"],
        f"<= {policy['max_ece']}",
    )
    brier_delta = model["brier"] - metrics["models"]["hca_only"]["brier"]
    check(
        "brier",
        brier_delta <= policy["max_brier_regression"],
        brier_delta,
        f"delta vs HCA-only <= {policy['max_brier_regression']}",
    )
    for target in ("margin", "total"):
        dist = metrics["distributions"][target]
        check(
            f"{target}_coverage",
            0.9 - policy["max_coverage90_error"]
            <= dist["coverage_90"]
            <= 0.9 + policy["max_coverage90_error"],
            dist["coverage_90"],
            f"abs(coverage - 0.9) <= {policy['max_coverage90_error']}",
        )
        check(
            f"{target}_bias",
            abs(dist["mean_error"]) <= policy[f"max_abs_{target}_bias"],
            dist["mean_error"],
            f"abs(bias) <= {policy[f'max_abs_{target}_bias']}",
        )
        check(
            f"{target}_crps",
            dist["crps_delta_vs_baseline"] <= policy["max_crps_regression"],
            dist["crps_delta_vs_baseline"],
            f"delta <= {policy['max_crps_regression']}",
        )
    passed = all(item["passed"] for item in checks)
    if metadata.get("synthetic"):
        status = "demo_only"
    elif not eligibility:
        status = "insufficient_data"
    else:
        status = "passed" if passed else "failed"
    return {
        "policy_version": policy["policy_version"],
        "status": status,
        "automated_model_gate_passed": passed,
        "checks": checks,
        "paired_log_loss_bootstrap": bootstrap,
        "scope": "Automated model gates only; software and locked-holdout protocol review separate",
    }
