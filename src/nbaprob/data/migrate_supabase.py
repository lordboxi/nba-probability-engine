"""Explicit, idempotent transfer of existing local records to the configured NBA project."""

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from nbaprob.data.supabase_store import remote_store


def _rows(path, table):
    path = Path(path).resolve()
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            return []
        # Table names come only from the fixed calls below, never from user input.
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]


def migrate_local(config):
    store = remote_store(config)
    if store is None:
        raise ValueError("Configure the NBA Supabase project before migrating local data")
    counts = {}
    snapshots = _rows(config["feed"]["snapshot_database"], "snapshots")
    for row in snapshots:
        payload = Path(row.pop("path")).read_text(encoding="utf-8")
        if hashlib.sha256(payload.encode()).hexdigest() != row["identity"]:
            raise ValueError("Local snapshot content hash mismatch; migration stopped")
        row["observed"] = datetime.fromtimestamp(row["observed"], UTC).isoformat()
        store.request(
            "nba_snapshots",
            query={"on_conflict": "workspace,identity"},
            row={**row, "payload": payload},
        )
    counts["snapshots"] = len(snapshots)
    path = Path(config["data"]["database"]).with_name("prediction_journal.sqlite")
    for table in ("forecasts", "outcomes"):
        rows = _rows(path, table)
        for row in rows:
            if (
                table == "forecasts"
                and hashlib.sha256(row["payload"].encode()).hexdigest() != row["identity"]
            ):
                raise ValueError("Local forecast content hash mismatch; migration stopped")
            conflict = (
                "workspace,identity" if table == "forecasts" else "workspace,game_id,recorded_at"
            )
            store.request(f"nba_{table}", query={"on_conflict": conflict}, row=row)
        counts[table] = len(rows)
    return {"submitted": counts, "policy": "insert if absent; existing rows unchanged"}
