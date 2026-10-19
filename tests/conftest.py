from copy import deepcopy
from pathlib import Path

import pytest

from nbaprob.config import load_config
from nbaprob.data.demo import generate_demo


@pytest.fixture
def config(tmp_path):
    config = load_config(Path(__file__).parents[1] / "config/default.yaml")
    config["data"]["database"] = str(tmp_path / "nba.sqlite")
    config["data"]["raw_directory"] = str(tmp_path / "raw")
    config["feed"]["snapshot_database"] = str(tmp_path / "snapshots.sqlite")
    config["feed"]["snapshot_directory"] = str(tmp_path / "snapshots")
    config["evaluation"].update(
        min_train_games=8, experiment_directory=str(tmp_path / "experiments")
    )
    config["demo"].update(teams=4, games_per_season=24)
    config["model"].update(context_min_games=6, residual_min_games=6)
    return deepcopy(config)


@pytest.fixture
def tables(config):
    return generate_demo(config)
