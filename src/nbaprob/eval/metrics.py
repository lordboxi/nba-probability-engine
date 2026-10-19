"""Proper probability and distribution scores, plus calibration diagnostics."""

import numpy as np
import pandas as pd
from scipy.stats import norm


def binary_scores(y, p, clip):
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    bounded = np.clip(p, clip, 1 - clip)
    return {
        "log_loss": float(-np.mean(y * np.log(bounded) + (1 - y) * np.log1p(-bounded))),
        "brier": float(np.mean((p - y) ** 2)),
        "accuracy": float(np.mean((p >= 0.5) == y)),
    }


def gaussian_crps(actual, mean, sigma):
    """Closed-form CRPS for a continuous Normal forecast (lower is better)."""
    actual, mean, sigma = map(np.asarray, (actual, mean, sigma))
    z = (actual - mean) / sigma
    return sigma * (z * (2 * norm.cdf(z) - 1) + 2 * norm.pdf(z) - 1 / np.sqrt(np.pi))


def reliability(y, p, bins):
    frame = pd.DataFrame({"observed": y, "predicted": p})
    frame["bin"] = pd.cut(frame.predicted, np.linspace(0, 1, bins + 1), include_lowest=True)
    return (
        frame.groupby("bin", observed=False)
        .agg(
            count=("observed", "size"),
            mean_probability=("predicted", "mean"),
            observed_frequency=("observed", "mean"),
        )
        .reset_index()
        .assign(bin=lambda x: x["bin"].astype(str))
    )


def summarize(predictions, config):
    clip = config["evaluation"]["probability_clip"]
    y = predictions.home_win.to_numpy()
    candidates = {
        "baseline_gaussian_v1": predictions.p_home_win.to_numpy(),
        "hca_only": predictions.p_hca_only.to_numpy(),
        "expanding_home_frequency": predictions.p_home_frequency.to_numpy(),
        "coin_flip": np.full(len(y), 0.5),
    }
    metrics = {name: binary_scores(y, p, clip) for name, p in candidates.items()}
    for name, probabilities in candidates.items():
        calibration = reliability(y, probabilities, config["evaluation"]["calibration_bins"])
        error = (calibration.mean_probability - calibration.observed_frequency).abs().fillna(0)
        metrics[name]["ece"] = float((error * calibration["count"]).sum() / len(y))
    reference = metrics["hca_only"]["log_loss"]
    for values in metrics.values():
        values["log_loss_delta_vs_hca_only"] = values["log_loss"] - reference
    distributions = {}
    for target in ("margin", "total"):
        actual = predictions[target].to_numpy()
        mu, sigma = predictions[f"mu_{target}"], predictions[f"sigma_{target}"]
        distributions[target] = {
            "crps": float(np.mean(gaussian_crps(actual, mu, sigma))),
            "rmse": float(np.sqrt(np.mean((actual - mu) ** 2))),
            "mean_error": float(np.mean(actual - mu)),
            "coverage_90": float(np.mean(np.abs((actual - mu) / sigma) <= norm.ppf(0.95))),
        }
        baseline_mean = (
            config["model"]["initial_hca"]
            if target == "margin"
            else (2 * config["features"]["league_ortg"] * config["features"]["league_pace"] / 100)
        )
        baseline_crps = float(
            np.mean(gaussian_crps(actual, baseline_mean, config["model"][f"{target}_sigma"]))
        )
        distributions[target]["baseline_crps"] = baseline_crps
        distributions[target]["crps_delta_vs_baseline"] = (
            distributions[target]["crps"] - baseline_crps
        )
    by_season = {}
    for season, rows in predictions.groupby("season", sort=True):
        model = binary_scores(rows.home_win, rows.p_home_win, clip)
        baseline = binary_scores(rows.home_win, rows.p_hca_only, clip)
        by_season[str(season)] = {
            "n_games": len(rows),
            "log_loss": model["log_loss"],
            "log_loss_delta_vs_hca_only": model["log_loss"] - baseline["log_loss"],
        }
    return {
        "n_games": len(y),
        "models": metrics,
        "distributions": distributions,
        "by_season": by_season,
    }
