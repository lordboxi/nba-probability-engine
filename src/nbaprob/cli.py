"""Command-line interface for baseline evaluation and timestamped matchup analysis."""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from nbaprob.analysis import analyze_forecast
from nbaprob.config import load_config
from nbaprob.data.demo import generate_demo
from nbaprob.data.journal import save_forecast
from nbaprob.data.loaders import CSVAdapter
from nbaprob.data.nba_stats import NBAStatsAdapter
from nbaprob.data.snapshots import latest_snapshot, save_snapshot
from nbaprob.data.store import load_tables, save_tables
from nbaprob.eval.report import save_experiment
from nbaprob.eval.walkforward import walk_forward
from nbaprob.features.build import ReplayEngine
from nbaprob.models.team_snapshot import matchup_forecast


def parser():
    root = argparse.ArgumentParser(description="NBA Probability Engine — as-of analysis")
    root.add_argument("--config", default="config/default.yaml", help="YAML configuration file")
    sub = root.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Generate and import clearly labeled synthetic data")
    demo.add_argument("--output", default="data/demo", help="CSV export directory")
    ingest = sub.add_parser("ingest", help="Validate and import local CSV files")
    ingest.add_argument("directory")
    ingest.add_argument("--source-label", required=True)
    ingest.add_argument(
        "--usage-note",
        required=True,
        help="Record source and permitted usage; does not verify rights",
    )
    sub.add_parser("validate", help="Validate the configured database")
    backtest = sub.add_parser("backtest", help="Run and archive chronological walk-forward scores")
    backtest.add_argument("--start", help="Inclusive tipoff timestamp with timezone")
    backtest.add_argument("--end", help="Exclusive tipoff timestamp with timezone")
    backtest.add_argument("--as-of", help="Only evaluate results known by this timestamp")
    predict = sub.add_parser(
        "predict", help="Issue a pregame forecast with settlement probabilities"
    )
    predict.add_argument("game_id")
    predict.add_argument("--as-of", required=True)
    predict.add_argument("--spread", type=float, help="Home handicap; -6.5 means home gives 6.5")
    predict.add_argument("--total-line", type=float)
    predict.add_argument("--output", help="Optionally save JSON forecast")
    for command in (predict,):
        command.add_argument("--lineup", help="Optional impact/availability scenario JSON")
        command.add_argument("--selection", help="Optional simple roster selection JSON")
        command.add_argument("--house", help="House probability/odds JSON for comparison")
    fetch = sub.add_parser("nba-fetch", help="Fetch NBA Traditional team stats or a team roster")
    fetch.add_argument("resource", choices=["teams", "roster"])
    fetch.add_argument("--season", required=True, help="NBA season, e.g. 2026-27")
    fetch.add_argument(
        "--season-type", default="Preseason", choices=["Preseason", "Regular Season", "Playoffs"]
    )
    fetch.add_argument("--team-id", help="NBA team ID (roster only)")
    fetch.add_argument("--import-json", help="Import a saved response instead of making a request")
    fetch.add_argument(
        "--import-html", help="Import a saved rendered HTML page instead of requesting"
    )
    matchup = sub.add_parser(
        "matchup", help="Experimental forecast using an as-of NBA team snapshot"
    )
    matchup.add_argument("--season", required=True)
    matchup.add_argument(
        "--season-type", default="Preseason", choices=["Preseason", "Regular Season", "Playoffs"]
    )
    matchup.add_argument("--home-team-id", required=True)
    matchup.add_argument("--away-team-id", required=True)
    matchup.add_argument("--tipoff", required=True)
    matchup.add_argument("--as-of", required=True)
    matchup.add_argument(
        "--no-preseason-prior",
        action="store_true",
        help="Disable discounted same-year Preseason prior for Regular Season",
    )
    for option in ("lineup", "selection", "house", "output"):
        matchup.add_argument(f"--{option}")
    matchup.add_argument(
        "--use-market-prior",
        action="store_true",
        help="Blend a separate market reference with the House quote",
    )
    for command in (predict, matchup):
        command.add_argument(
            "--record",
            action="store_true",
            help="Archive forecast and actual issue time in the local journal",
        )
    return root


def _document(path, game_id):
    if path is None:
        return None
    result = json.loads(Path(path).read_text(encoding="utf-8"))
    result.setdefault("game_id", game_id)
    return result


def _write_analysis(args, base, game, config, synthetic=False):
    output = analyze_forecast(
        base,
        game,
        args.as_of,
        config,
        lineup=_document(args.lineup, game.game_id),
        selection=_document(args.selection, game.game_id),
        house=_document(args.house, game.game_id),
        spread=getattr(args, "spread", None),
        total_line=getattr(args, "total_line", None),
        synthetic=synthetic,
        use_market_prior=getattr(args, "use_market_prior", False),
    )
    if args.record:
        save_forecast(output, game, config)
    serialized = json.dumps(output, indent=2, allow_nan=False, ensure_ascii=False)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        config = load_config(args.config)
        database = config["data"]["database"]
        if args.command == "nba-fetch":
            if args.import_json and args.import_html:
                raise ValueError("Use only one import file")
            imported = (
                json.loads(Path(args.import_json).read_text(encoding="utf-8"))
                if args.import_json
                else None
            )
            if args.import_html:
                imported = Path(args.import_html).read_text(encoding="utf-8")
            snapshot = NBAStatsAdapter(config).fetch(
                args.resource,
                args.season,
                args.season_type,
                args.team_id,
                imported_payload=imported,
            )
            saved = save_snapshot(snapshot, config)
            print(
                json.dumps(
                    {
                        **saved,
                        "retrieved_at": snapshot["retrieved_at"],
                        "source": "NBA.com",
                        "season": args.season,
                        "season_type": snapshot["season_type"],
                    },
                    indent=2,
                )
            )
            return 0
        if args.command == "matchup":
            snapshot = latest_snapshot(config, "teams", args.season, args.as_of, args.season_type)
            previous_year = int(args.season[:4]) - 1
            previous = latest_snapshot(
                config,
                "teams",
                f"{previous_year}-{(previous_year + 1) % 100:02d}",
                args.as_of,
                "Regular Season",
            )
            preseason = latest_snapshot(config, "teams", args.season, args.as_of, "Preseason")
            catalog = snapshot or previous or preseason
            if catalog is None:
                raise ValueError(
                    "No NBA table snapshot was available at this as-of; fetch/import one first"
                )
            game, base = matchup_forecast(
                snapshot,
                args.home_team_id,
                args.away_team_id,
                args.tipoff,
                args.as_of,
                config,
                previous_snapshot=previous,
                preseason_snapshot=(
                    preseason
                    if args.season_type == "Regular Season" and not args.no_preseason_prior
                    else None
                ),
                season=args.season,
                season_type=args.season_type,
                team_catalog=catalog["data"],
            )
            _write_analysis(
                args,
                base,
                game,
                config,
                synthetic=any(
                    document and document.get("synthetic", False)
                    for document in (
                        snapshot,
                        previous,
                        preseason
                        if args.season_type == "Regular Season" and not args.no_preseason_prior
                        else None,
                    )
                ),
            )
            return 0
        if args.command in ("demo", "ingest"):
            if args.command == "demo":
                tables = generate_demo(config)
                output = Path(args.output)
                output.mkdir(parents=True, exist_ok=True)
                for name in ("games", "team_game_stats", "schedule"):
                    getattr(tables, name).to_csv(output / f"{name}.csv", index=False)
                (output / "metadata.json").write_text(
                    json.dumps(tables.metadata, indent=2), encoding="utf-8"
                )
            else:
                tables = CSVAdapter(
                    args.directory,
                    {
                        "source": args.source_label,
                        "synthetic": False,
                        "usage_note": args.usage_note,
                    },
                ).load()
                # Preserve demo provenance if generated CSVs are re-imported.
                metadata_path = Path(args.directory) / "metadata.json"
                if metadata_path.is_file():
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    if metadata.get("synthetic"):
                        tables.metadata["synthetic"] = True
            version = save_tables(tables, database, config["data"]["raw_directory"])
            print(
                json.dumps(
                    {
                        "database": str(Path(database).resolve()),
                        "data_version": version,
                        "games": len(tables.games),
                        "metadata": tables.metadata,
                    },
                    indent=2,
                )
            )
            return 0
        tables = load_tables(database)
        if args.command == "validate":
            print(
                json.dumps(
                    {"valid": True, "games": len(tables.games), "metadata": tables.metadata},
                    indent=2,
                )
            )
        elif args.command == "backtest":
            predictions = walk_forward(tables, config, args.start, args.end, args.as_of)
            directory = save_experiment(
                predictions,
                tables,
                config,
                {"start": args.start, "end": args.end, "as_of": args.as_of},
            )
            print(str((directory / "report.md").resolve()))
        else:
            engine = ReplayEngine(tables, config)
            forecast = engine.predict(args.game_id, args.as_of)
            _write_analysis(
                args,
                forecast,
                engine.games[args.game_id],
                config,
                synthetic=tables.metadata.get("synthetic", False),
            )
        return 0
    except (ValueError, OSError, KeyError, pd.errors.ParserError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
