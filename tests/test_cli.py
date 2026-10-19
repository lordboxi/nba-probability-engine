import json

import pandas as pd
import yaml

from nbaprob.cli import main
from nbaprob.data.store import load_tables


def test_complete_local_workflow(config, tmp_path, capsys):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    prefix = ["--config", str(path)]
    demo_dir = str(tmp_path / "csv")
    assert main([*prefix, "demo", "--output", demo_dir]) == 0
    assert json.loads(capsys.readouterr().out)["metadata"]["synthetic"]
    assert main([*prefix, "validate"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"]
    assert main([*prefix, "backtest"]) == 0
    assert "report.md" in capsys.readouterr().out
    tables = load_tables(config["data"]["database"])
    target = tables.games[tables.games.game_id == "demo-next"].iloc[0]
    as_of = (target.date - pd.Timedelta(hours=1)).isoformat()
    output = tmp_path / "prediction.json"
    assert (
        main(
            [
                *prefix,
                "predict",
                "demo-next",
                "--as-of",
                as_of,
                "--spread",
                "-7",
                "--total-line",
                "228.5",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    forecast = json.loads(capsys.readouterr().out)
    assert forecast == json.loads(output.read_text(encoding="utf-8"))
    assert 0 < forecast["p_home_win"] < 1
    assert forecast["home_spread"]["push"] > 0
    assert forecast["over_total"]["push"] == 0
    assert (
        main(
            [
                *prefix,
                "ingest",
                demo_dir,
                "--source-label",
                "reimported-demo",
                "--usage-note",
                "Locally generated synthetic data",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["metadata"]["synthetic"] is True
    assert main([*prefix, "predict", "unknown", "--as-of", as_of]) == 2
    assert "Unknown game_id" in capsys.readouterr().err
