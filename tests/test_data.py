from copy import deepcopy

import pandas as pd
import pytest
import yaml

from nbaprob.config import load_config
from nbaprob.data.loaders import CSVAdapter
from nbaprob.data.store import data_version, load_tables, save_tables


def test_storage_round_trip_and_parquet_archive(tables, config):
    version = save_tables(tables, config["data"]["database"], config["data"]["raw_directory"])
    restored = load_tables(config["data"]["database"])
    assert restored.metadata == tables.metadata
    for name in ("games", "schedule", "team_game_stats"):
        pd.testing.assert_frame_equal(getattr(tables, name), getattr(restored, name))
    assert data_version(restored) == version
    archive = config["data"]["raw_directory"] + "/" + version
    assert len(pd.read_parquet(archive + "/games.parquet")) == len(tables.games)


@pytest.mark.parametrize(
    "kind",
    [
        "tie",
        "future_fixture",
        "early_result",
        "missing_score",
        "duplicate",
        "negative_pace",
        "early_stats",
        "naive",
    ],
)
def test_invalid_data_rejected(tables, kind):
    tables = deepcopy(tables)
    first = tables.games.index[0]
    if kind == "tie":
        tables.games.loc[first, "home_pts"] = tables.games.loc[first, "away_pts"]
    elif kind == "future_fixture":
        tables.games.loc[first, "ts"] = tables.games.loc[first, "date"]
    elif kind == "early_result":
        tables.games.loc[first, "results_available_at"] = tables.games.loc[first, "date"]
    elif kind == "missing_score":
        tables.games.loc[first, "home_pts"] = None
    elif kind == "duplicate":
        tables.games = pd.concat([tables.games, tables.games.iloc[:1]])
    elif kind == "negative_pace":
        tables.team_game_stats.loc[0, "possessions"] = -1
    elif kind == "early_stats":
        tables.team_game_stats.loc[0, "ts"] = tables.games.date.min()
    else:
        tables.games["ts"] = tables.games.ts.dt.tz_localize(None)
    with pytest.raises(ValueError):
        tables.validate()


def test_csv_identifiers_preserved_and_optional_tables_absent(tables, tmp_path):
    tables.games["game_id"] = [f"{i:06d}" for i in range(len(tables.games))]
    tables.games.to_csv(tmp_path / "games.csv", index=False)
    loaded = CSVAdapter(tmp_path, {"source": "test"}).load()
    assert loaded.games.game_id.iloc[0] == "000000"
    assert loaded.team_game_stats.empty and loaded.schedule.empty


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("ratings", "prior_shrink", 2),
        ("model", "margin_sigma", 0),
        ("feed", "preseason_game_weight", 2),
        ("feed", "preseason_game_weight", True),
        ("market", "model_weight_k", 0),
        ("market", "prior_equivalent_games", -1),
        ("model", "context_ridge", -1),
        ("evaluation", "probability_clip", 1),
        ("features", "stats_window", 2.5),
        ("model", "spread_bins", [0, 10, 5]),
        ("ratings", "typo_noise", 1),
        ("model", "margin_sigma", "fast"),
        ("ratings", "prior_shrink", True),
        ("evaluation", "prediction_lead_minutes", 0),
        ("evaluation", "home_frequency_alpha", 0),
        ("data", "calendar_timezone", "Not/A_Zone"),
        ("evaluation", "qq_probabilities", []),
    ],
)
def test_bad_configuration_rejected(config, tmp_path, section, key, value):
    config[section][key] = value
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)
