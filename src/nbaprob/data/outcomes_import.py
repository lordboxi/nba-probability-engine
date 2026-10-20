"""Preview and validate a whole final-score CSV before writing any score revisions."""

import csv
import io
import re

from nbaprob.data.journal import history, record_outcome
from nbaprob.data.schema import utc

FIELDS = ("game_id", "home_team", "away_team", "home_points", "away_points", "status")


def outcomes_template(forecasts, at):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FIELDS)
    writer.writeheader()
    games = {r["game_id"]: r for r in forecasts if utc(r["tipoff"]) < utc(at)}
    for game_id, row in games.items():
        writer.writerow(
            {
                "game_id": game_id,
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "status": "Final",
            }
        )
    return buffer.getvalue()


def prepare_outcomes(text, forecasts, outcomes, at):
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if (
        reader.fieldnames is None
        or len(reader.fieldnames) != len(set(reader.fieldnames))
        or set(reader.fieldnames) != set(FIELDS)
    ):
        raise ValueError("Results CSV requires exactly: " + ",".join(FIELDS))
    games = {r["game_id"]: r for r in forecasts}
    prepared, seen = [], set()
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("Results CSV row width does not match headers")
        row = {key: value.strip() for key, value in row.items()}
        game_id = row["game_id"]
        if game_id not in games or game_id in seen:
            raise ValueError("Unknown or duplicate game_id in results CSV")
        seen.add(game_id)
        game = games[game_id]
        if utc(game["tipoff"]) >= utc(at):
            raise ValueError("Cannot import results before the saved game's tipoff")
        if row["home_team"] != game["home_team"] or row["away_team"] != game["away_team"]:
            raise ValueError("Results CSV home/away teams must match the saved forecast")
        if row["status"] != "Final" or any(
            not re.fullmatch(r"[0-9]+", row[k]) for k in ("home_points", "away_points")
        ):
            raise ValueError("Results CSV needs Final status and integer final scores including OT")
        home, away = int(row["home_points"]), int(row["away_points"])
        if home == away:
            raise ValueError("Final NBA scores must have a winner")
        previous = outcomes.get(game_id)
        unchanged = previous and (previous["home_points"], previous["away_points"]) == (home, away)
        prepared.append(
            {
                **row,
                "home_points": home,
                "away_points": away,
                "action": "unchanged" if unchanged else "revision" if previous else "new",
            }
        )
    if not prepared:
        raise ValueError("Results CSV has no games")
    return prepared


def import_outcomes(config, text, at):
    forecasts, outcomes = history(config)
    rows = prepare_outcomes(text, forecasts, outcomes, at)
    submitted = 0
    for row in rows:
        if row["action"] != "unchanged":
            record_outcome(config, row["game_id"], row["home_points"], row["away_points"], at)
            submitted += 1
    return {"submitted": submitted, "unchanged": len(rows) - submitted}
