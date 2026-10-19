"""Rolling context regression and prequential residual uncertainty estimates."""

import numpy as np
from scipy.stats import norm

from nbaprob.features.context import CONTEXT_NAMES, context_vector


class GaussianBaseline:
    def __init__(self, config):
        self.config = config
        self.observations: list[dict] = []

    def coefficients(self):
        cfg = self.config["model"]
        prior = np.zeros(len(CONTEXT_NAMES))
        prior[0] = cfg["initial_hca"]
        rows = self.observations[-cfg["context_window"] :]
        if len(rows) < cfg["context_min_games"]:
            return prior
        x = np.asarray([row["context"] for row in rows])
        y = np.asarray([row["margin"] - row["rating_margin"] for row in rows])
        penalty = cfg["context_ridge"] * np.eye(len(prior))
        return np.linalg.solve(x.T @ x + penalty, x.T @ y + penalty @ prior)

    def sigma(self, pace, predicted_margin, target):
        cfg = self.config["model"]
        rows = self.observations[-cfg["residual_window"] :]
        if target == "margin":
            edges = np.asarray(cfg["spread_bins"])
            bucket = np.searchsorted(edges, abs(predicted_margin), side="right")
            bucket_rows = [
                r
                for r in rows
                if np.searchsorted(edges, abs(r["mu_margin"]), side="right") == bucket
            ]
            if len(bucket_rows) >= cfg["residual_min_games"]:
                rows = bucket_rows
        sigma0 = cfg[f"{target}_sigma"]
        if len(rows) >= cfg["residual_min_games"]:
            residuals = [
                (r[target] - r[f"mu_{target}"])
                / np.sqrt(r["pace"] / self.config["features"]["league_pace"])
                for r in rows
            ]
            sigma0 = max(cfg["minimum_sigma"], float(np.std(residuals, ddof=1)))
        return float(sigma0 * np.sqrt(pace / self.config["features"]["league_pace"]))

    def predict(self, features):
        coefficients = self.coefficients()
        rating_margin = features["rating_diff"] * features["pace"] / 100
        mu_margin = float(rating_margin + context_vector(features) @ coefficients)
        mu_total = float(features["total_rate"] * features["pace"] / 100)
        sigma_margin = self.sigma(features["pace"], mu_margin, "margin")
        sigma_total = self.sigma(features["pace"], mu_margin, "total")
        return {
            "mu_margin": mu_margin,
            "mu_total": mu_total,
            "sigma_margin": sigma_margin,
            "sigma_total": sigma_total,
            "p_home_win": float(norm.cdf(mu_margin / sigma_margin)),
            "rating_margin": float(rating_margin),
            "context_coefficients": dict(zip(CONTEXT_NAMES, coefficients.tolist(), strict=True)),
        }

    def observe(self, features, forecast, margin, total):
        self.observations.append(
            {
                "context": context_vector(features),
                "pace": features["pace"],
                "margin": margin,
                "total": total,
                **{k: forecast[k] for k in ("rating_margin", "mu_margin", "mu_total")},
            }
        )
