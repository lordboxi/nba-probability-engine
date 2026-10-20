"""Local forecast/outcome journal. Forecast inputs never change after issuance."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from nbaprob.data.schema import utc
from nbaprob.data.supabase_store import remote_store
from nbaprob.eval.metrics import binary_scores


@contextmanager
def journal(config):
    path = Path(config["data"]["database"]).with_name("prediction_journal.sqlite")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS forecasts (
                identity TEXT PRIMARY KEY, game_id TEXT, tipoff TEXT, as_of TEXT, issued_at TEXT,
                home_team TEXT, away_team TEXT, payload TEXT);
            CREATE TABLE IF NOT EXISTS outcomes (
                game_id TEXT, recorded_at TEXT, home_points INTEGER, away_points INTEGER,
                PRIMARY KEY (game_id, recorded_at));
        """)
        yield connection
        connection.commit()
    finally:
        connection.close()


def save_forecast(result, game, config):
    if utc(result["as_of"]) >= utc(game.date) or result["game_id"] != game.game_id:
        raise ValueError("Journal requires a matching pregame forecast")
    payload = json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False)
    identity = hashlib.sha256(payload.encode()).hexdigest()
    store = remote_store(config)
    if store is not None:
        store.request(
            "nba_forecasts",
            query={"on_conflict": "workspace,identity"},
            row={
                "identity": identity,
                "game_id": game.game_id,
                "tipoff": utc(game.date).isoformat(),
                "as_of": utc(result["as_of"]).isoformat(),
                "home_team": game.home_team,
                "away_team": game.away_team,
                "payload": payload,
            },
        )
        return identity
    with journal(config) as connection:
        connection.execute(
            "INSERT OR IGNORE INTO forecasts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                identity,
                game.game_id,
                utc(game.date).isoformat(),
                utc(result["as_of"]).isoformat(),
                datetime.now(UTC).isoformat(),
                game.home_team,
                game.away_team,
                payload,
            ),
        )
    return identity


def record_outcome(config, game_id, home_points, away_points, recorded_at):
    if (
        any(type(value) is not int or value < 0 for value in (home_points, away_points))
        or home_points == away_points
    ):
        raise ValueError("Final NBA scores require nonnegative integers and a winner")
    at = utc(recorded_at)
    if at > utc(datetime.now(UTC)):
        raise ValueError("Outcome recording time cannot be in the future")
    store = remote_store(config)
    if store is not None:
        games = store.request(
            "nba_forecasts", query={"game_id": f"eq.{game_id}", "select": "tipoff", "limit": 1}
        )
        if not games or at <= utc(games[0]["tipoff"]):
            raise ValueError("Record a final outcome only for a saved game after tipoff")
        store.request(
            "nba_outcomes",
            row={
                "game_id": game_id,
                "recorded_at": at.isoformat(),
                "home_points": home_points,
                "away_points": away_points,
            },
        )
        return
    with journal(config) as connection:
        game = connection.execute(
            "SELECT tipoff FROM forecasts WHERE game_id=? LIMIT 1", (game_id,)
        ).fetchone()
        if game is None or at <= utc(game["tipoff"]):
            raise ValueError("Record a final outcome only for a saved game after tipoff")
        connection.execute(
            "INSERT INTO outcomes VALUES (?, ?, ?, ?)",
            (game_id, at.isoformat(), home_points, away_points),
        )


def history(config):
    store = remote_store(config)
    if store is not None:
        forecasts = store.rows("nba_forecasts", "as_of.asc,identity.asc")
        outcomes = store.rows("nba_outcomes", "recorded_at.asc,game_id.asc")
        return forecasts, {row["game_id"]: row for row in outcomes}
    with journal(config) as connection:
        forecasts = [
            dict(row)
            for row in connection.execute("SELECT * FROM forecasts ORDER BY as_of, identity")
        ]
        outcomes = [
            dict(row) for row in connection.execute("SELECT * FROM outcomes ORDER BY recorded_at")
        ]
    return forecasts, {row["game_id"]: row for row in outcomes}


def journal_scores(config):
    forecasts, outcomes = history(config)
    # One latest pregame forecast per game, chosen without looking at its outcome.
    eligible = [
        row for row in forecasts if utc(row["as_of"]) <= utc(row["issued_at"]) < utc(row["tipoff"])
    ]
    latest = {
        row["game_id"]: row
        for row in sorted(
            eligible, key=lambda row: (utc(row["as_of"]), utc(row["issued_at"]), row["identity"])
        )
    }
    settled = [
        row
        for game_id, row in latest.items()
        if game_id in outcomes and utc(row["issued_at"]) < utc(row["tipoff"])
    ]
    samples = []
    for row in settled:
        payload = json.loads(row["payload"])
        outcome = outcomes[row["game_id"]]
        if payload.get("synthetic"):
            continue
        sample = {
            "actual": int(outcome["home_points"] > outcome["away_points"]),
            "model": payload["p_home_win"],
        }
        assisted = payload.get("market_assisted")
        if (
            assisted
            and assisted["market"] == "moneyline"
            and assisted["decision"] != "refresh_quote"
        ):
            first = assisted["sides"][0]
            sample.update(
                house=first["house_probability_no_push"],
                assisted=first["assisted_probability_no_push"],
            )
        samples.append(sample)
    matched = [row for row in samples if "house" in row]
    clip = config["evaluation"]["probability_clip"]
    return {
        "saved_forecasts": len(forecasts),
        "unique_games": len({row["game_id"] for row in forecasts}),
        "eligible_pregame_games": len(latest),
        "settled_games": len(samples),
        "matched_moneyline_games": len(matched),
        "model": binary_scores(
            [row["actual"] for row in samples], [row["model"] for row in samples], clip
        )
        if samples
        else None,
        "matched_models": {
            name: binary_scores(
                [row["actual"] for row in matched], [row[name] for row in matched], clip
            )
            for name in ("model", "house", "assisted")
        }
        if matched
        else {},
        "note": "Descriptive forward log, not a validated strategy. "
        "Latest prediction per game; synthetic and post-tipoff archives excluded. "
        "No automatic retraining.",
    }
