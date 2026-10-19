"""Manufactured forecasts exercise gate logic, not real-world NBA accuracy."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from nbaprob.eval.acceptance import assess_v1, paired_day_bootstrap
from nbaprob.eval.metrics import summarize


@pytest.fixture
def forecasts():
    n = 1200
    y = np.arange(n) % 2
    z = norm.ppf((np.arange(n) + 0.5) / n)
    return pd.DataFrame(
        {
            "date": pd.date_range("2023-10-01", periods=n // 2, tz="UTC").repeat(2),
            "season": np.where(np.arange(n) < n // 2, 2023, 2024),
            "home_win": y,
            "p_home_win": np.where(y, 0.99, 0.01),
            "p_hca_only": 0.55,
            "p_home_frequency": 0.5,
            "margin": np.where(y, 10.0, -10.0),
            "total": 228.0,
            "mu_margin": np.where(y, 10.0, -10.0) - z,
            "mu_total": 228.0 - 2 * z,
            "sigma_margin": 1.0,
            "sigma_total": 2.0,
        }
    )


def assess(forecasts, config, *, synthetic=False):
    metadata = {
        "synthetic": synthetic,
        "source": "manufactured-unit-test",
        "usage_note": "Test fixture only; never a real accuracy claim",
    }
    return assess_v1(forecasts, metadata, summarize(forecasts, config), config)


def test_qualifying_numerical_forecasts_pass_automated_gate(forecasts, config):
    result = assess(forecasts, config)
    assert result["status"] == "passed"
    assert result["automated_model_gate_passed"] is True
    assert all(item["passed"] for item in result["checks"])
    metrics = summarize(forecasts, config)
    assert metrics["models"]["baseline_gaussian_v1"]["ece"] == pytest.approx(0.01)
    assert set(metrics["by_season"]) == {"2023", "2024"}


def test_synthetic_data_cannot_pass_even_with_qualifying_scores(forecasts, config):
    result = assess(forecasts, config, synthetic=True)
    assert result["status"] == "demo_only"
    assert result["automated_model_gate_passed"] is False
    assert not next(c for c in result["checks"] if c["name"] == "real_data")["passed"]


def test_insufficient_sample_is_distinct_from_failed_quality(forecasts, config):
    result = assess(forecasts.iloc[:100], config)
    assert result["status"] == "insufficient_data"
    changed = forecasts.copy()
    changed["p_home_win"] = 1 - changed.p_home_win
    result = assess(changed, config)
    assert result["status"] == "failed"
    assert not result["automated_model_gate_passed"]


def test_unknown_provenance_does_not_pass_as_real(forecasts, config):
    result = assess_v1(forecasts, {}, summarize(forecasts, config), config)
    assert result["status"] == "insufficient_data"


@pytest.mark.parametrize("coverage", [0.85, 0.95])
def test_coverage_interval_includes_its_documented_boundaries(forecasts, config, coverage):
    metrics = summarize(forecasts, config)
    metrics["distributions"]["margin"]["coverage_90"] = coverage
    result = assess_v1(
        forecasts, {"synthetic": False, "source": "test", "usage_note": "test"}, metrics, config
    )
    assert next(c for c in result["checks"] if c["name"] == "margin_coverage")["passed"]


def test_no_uncertainty_claim_for_single_day(forecasts, config):
    forecasts["date"] = pd.Timestamp("2025-01-01T23:00:00Z")
    interval = paired_day_bootstrap(forecasts, config)
    assert interval["n_blocks"] == 1
    assert interval["lower"] is None and interval["upper"] is None
    assert assess(forecasts, config)["status"] == "insufficient_data"


def test_bootstrap_is_reproducible_paired_and_uses_local_dates(config):
    frame = pd.DataFrame(
        {
            "date": [
                "2025-01-01T23:00:00Z",
                "2025-01-02T01:00:00Z",
                "2025-01-03T23:00:00Z",
                "2025-01-04T01:00:00Z",
            ],
            "home_win": [1, 0, 1, 0],
            "p_home_win": [0.9, 0.1, 0.9, 0.1],
            "p_hca_only": [0.5, 0.5, 0.5, 0.5],
        }
    )
    first, second = paired_day_bootstrap(frame, config), paired_day_bootstrap(frame, config)
    assert first == second
    assert first["n_blocks"] == 2
    assert first["mean_delta"] == pytest.approx(-np.log(0.9) + np.log(0.5))
    assert first["lower"] == pytest.approx(first["upper"])


def test_each_season_must_pass_even_when_overall_loss_looks_good(forecasts, config):
    changed = forecasts.copy()
    mask = changed.season == 2024
    changed.loc[mask, "p_home_win"] = 0.6
    changed_config = deepcopy(config)
    changed_config["acceptance"]["max_season_log_loss_regression"] = 0
    result = assess(changed, changed_config)
    assert not next(c for c in result["checks"] if c["name"] == "season_stability")["passed"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_ece", 1.1),
        ("confidence_level", 1),
        ("min_evaluation_games", 2.5),
        ("bootstrap_samples", 1),
        ("max_abs_margin_bias", -1),
        ("policy_version", 1),
    ],
)
def test_policy_config_rejects_invalid_thresholds(config, tmp_path, field, value):
    import yaml

    from nbaprob.config import load_config

    config["acceptance"][field] = value
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)
