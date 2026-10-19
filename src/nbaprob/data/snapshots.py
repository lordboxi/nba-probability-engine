"""Immutable JSON snapshots with publication-as-observed timestamps and local indexing."""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from nbaprob.data.schema import utc


def save_snapshot(document, config):
    document = dict(document)
    observed = utc(document["retrieved_at"])
    document["retrieved_at"] = observed.isoformat()
    serialized = json.dumps(document, sort_keys=True, ensure_ascii=False, allow_nan=False)
    identity = hashlib.sha256(serialized.encode()).hexdigest()
    directory = Path(config["feed"]["snapshot_directory"])
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{identity}.json"
    if not path.exists():
        path.write_text(serialized, encoding="utf-8")
    database = Path(config["feed"]["snapshot_database"])
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS snapshots (
            identity TEXT PRIMARY KEY, resource TEXT, season TEXT, season_type TEXT,
            team_id TEXT, observed REAL, path TEXT)""")
        connection.execute(
            "INSERT OR IGNORE INTO snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                identity,
                document["resource"],
                document["season"],
                document.get("season_type", ""),
                str(document.get("team_id", "")),
                observed.timestamp(),
                str(path.resolve()),
            ),
        )
        connection.commit()
    return {"identity": identity, "path": str(path.resolve()), "rows": len(document["data"])}


def latest_snapshot(config, resource, season, as_of, season_type="", team_id=""):
    database = Path(config["feed"]["snapshot_database"])
    if not database.exists():
        return None
    with closing(sqlite3.connect(database)) as connection:
        row = connection.execute(
            """SELECT identity, path FROM snapshots
            WHERE resource=? AND season=? AND season_type=? AND team_id=? AND observed<=?
            ORDER BY observed DESC, identity DESC LIMIT 1""",
            (resource, season, season_type, str(team_id), utc(as_of).timestamp()),
        ).fetchone()
    if row is None:
        return None
    payload = Path(row[1]).read_text(encoding="utf-8")
    if hashlib.sha256(payload.encode()).hexdigest() != row[0]:
        raise ValueError("Snapshot content hash mismatch")
    return {**json.loads(payload), "identity": row[0]}
