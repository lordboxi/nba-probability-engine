import json
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from nbaprob.eval.metrics import binary_scores, gaussian_crps
from nbaprob.eval.report import save_experiment
from nbaprob.eval.walkforward import walk_forward
from nbaprob.features.build import ReplayEngine
from nbaprob.models.baseline_gaussian import GaussianBaseline
from nbaprob.ratings.team_ratings import TeamRatings


def test_kalman_gain_declines_and_season_priors_shrink(config):
    config["ratings"]["process_noise"] = 0
    ratings = TeamRatings(config)
    gains = []
    for _ in range(20):
        gains.append(ratings.update(2024, "H", "A", 5, 100)[0])
    assert all(a > b for a, b in zip(gains, gains[1:], strict=False))
    assert ratings.value(2024, "H") == pytest.approx(-ratings.value(2024, "A"))
    previous = ratings.value(2024, "H")
    assert ratings.value(2025, "H") == pytest.approx(previous * config["ratings"]["prior_shrink"])
    assert ratings.state(2025, "H").games == 0


def test_walk_forward_uses_only_results_known_at_each_issue_time(tables, config):
    predictions = walk_forward(tables, config)
    for row in predictions.itertuples():
        stamp = pd.Timestamp(row.as_of)
        available = int((tables.games.results_available_at <= stamp).sum())
        assert row.training_games == available
        assert row.training_games >= config["evaluation"]["min_train_games"]
        assert stamp < pd.Timestamp(row.date) < pd.Timestamp(row.results_available_at)
    assert predictions.date.is_monotonic_increasing
    assert np.isfinite(predictions.select_dtypes(include="number")).all().all()
    assert predictions.p_home_win.between(0, 1).all()


def test_later_data_cannot_rewrite_earlier_backtest_predictions(tables, config):
    original = walk_forward(tables, config)
    cutoff = pd.Timestamp(original.date.iloc[len(original) // 2])
    modified = deepcopy(tables)
    mask = modified.games.date > cutoff
    modified.games.loc[mask, "home_pts"] += 200
    modified.team_game_stats.loc[modified.team_game_stats.ts > cutoff, "ortg"] *= 2
    modified.validate()
    later = walk_forward(modified, config)
    pd.testing.assert_frame_equal(
        original[original.date <= cutoff.isoformat()], later[later.date <= cutoff.isoformat()]
    )


def test_reproducible_runs_and_complete_experiment(tables, config):
    a, b = walk_forward(tables, config), walk_forward(tables, config)
    pd.testing.assert_frame_equal(a, b)
    one, two = save_experiment(a, tables, config), save_experiment(b, tables, config)
    first, second = [
        json.loads((p / "manifest.json").read_text(encoding="utf-8")) for p in (one, two)
    ]
    assert first["metrics"] == second["metrics"]
    assert first["config_hash"] == second["config_hash"]
    assert first["data_version"] == second["data_version"]
    assert first["data_metadata"]["synthetic"] is True
    assert {p.name for p in one.iterdir()} == {
        "report.md",
        "config.yaml",
        "manifest.json",
        "predictions.csv",
        "calibration.csv",
        "residual_qq.csv",
        "acceptance.json",
    }
    assessment = json.loads((one / "acceptance.json").read_text(encoding="utf-8"))
    assert assessment["status"] == "demo_only"
    assert not assessment["automated_model_gate_passed"]


def test_evaluation_cutoff_and_date_filters(tables, config):
    cutoff = "2024-12-01T00:00:00Z"
    predictions = walk_forward(tables, config, as_of=cutoff)
    assert pd.to_datetime(predictions.results_available_at, utc=True).max() <= pd.Timestamp(cutoff)
    filtered = walk_forward(tables, config, start="2025-01-01T00:00:00Z")
    assert pd.to_datetime(filtered.date, utc=True).min() >= pd.Timestamp("2025-01-01T00:00:00Z")
    with pytest.raises(ValueError, match="No evaluation games"):
        walk_forward(tables, config, end="2020-01-01T00:00:00Z")


def test_proper_scores_match_known_values():
    assert binary_scores([0, 1], [0.5, 0.5], 1e-9)["log_loss"] == pytest.approx(np.log(2))
    assert binary_scores([0, 1], [0.1, 0.9], 1e-9)["brier"] == pytest.approx(0.01)
    assert gaussian_crps(0, 0, 1) == pytest.approx((np.sqrt(2) - 1) / np.sqrt(np.pi))


def test_ot_pace_normalizes_full_game_possessions(tables, config):
    first = tables.games.sort_values("date").iloc[0]
    tables.games.loc[tables.games.game_id == first.game_id, "ot_periods"] = 1
    tables.team_game_stats.loc[tables.team_game_stats.game_id == first.game_id, "possessions"] = 110
    engine = ReplayEngine(tables.validate(), config)
    engine.advance(first.results_available_at)
    assert engine.stats[first.home_team][-1][0] == pytest.approx(110 * 48 / 53)


def test_context_regression_learns_signed_effects_from_past_observations(config):
    model = GaussianBaseline(config)
    for index in range(60):
        rest = 1.0 if index % 2 == 0 else -1.0
        b2b = 1.0 if index % 3 == 0 else -1.0
        features = {
            "hca": 1,
            "rest_diff": rest,
            "b2b_diff": b2b,
            "congestion_diff": 0,
            "travel": 0,
            "altitude": 0,
            "rating_diff": 0,
            "pace": 100,
            "total_rate": 228,
        }
        forecast = model.predict(features)
        model.observe(features, forecast, 2.5 + 4 * rest - 3 * b2b, 228)
    coefficients = model.coefficients()
    assert coefficients[1] > 2
    assert coefficients[2] < -1


def test_sigma_scales_with_pace_and_learns_prequential_residuals(config):
    config["model"]["residual_min_games"] = 4
    model = GaussianBaseline(config)
    prior = model.sigma(100, 0, "margin")
    features = {
        "hca": 1,
        "rest_diff": 0,
        "b2b_diff": 0,
        "congestion_diff": 0,
        "travel": 0,
        "altitude": 0,
        "rating_diff": 0,
        "pace": 100,
        "total_rate": 228,
    }
    forecast = model.predict(features)
    for residual in (-2, 2, -4, 4):
        model.observe(features, forecast, forecast["mu_margin"] + residual, 228)
    learned = model.sigma(100, forecast["mu_margin"], "margin")
    assert learned == pytest.approx(np.std([-2, 2, -4, 4], ddof=1))
    assert learned < prior
    assert model.sigma(400, forecast["mu_margin"], "margin") == pytest.approx(2 * learned)
