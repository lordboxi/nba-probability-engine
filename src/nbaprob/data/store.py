"""Single-file SQLite working dataset and immutable normalized Parquet archives."""

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

import pandas as pd

from nbaprob.data.schema import SCHEMAS, Tables


def data_version(tables: Tables) -> str:
    digest = hashlib.sha256()
    for name in SCHEMAS:
        digest.update(name.encode())
        digest.update(getattr(tables, name).to_csv(index=False).encode())
    digest.update(json.dumps(tables.metadata, sort_keys=True).encode())
    return digest.hexdigest()


def save_tables(tables: Tables, database: str | Path, raw_directory: str | Path) -> str:
    tables.validate()
    version = data_version(tables)
    archive = Path(raw_directory) / version
    archive.mkdir(parents=True, exist_ok=True)
    for name in SCHEMAS:
        getattr(tables, name).to_parquet(archive / f"{name}.parquet", index=False)
    (archive / "metadata.json").write_text(
        json.dumps(tables.metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    temporary = database.with_name(f"{database.name}.{uuid.uuid4().hex}.tmp")
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            for name in SCHEMAS:
                frame = getattr(tables, name).copy()
                for column in ("ts", "date", "results_available_at"):
                    if column in frame:
                        frame[column] = frame[column].map(
                            lambda value: value.isoformat() if pd.notna(value) else None
                        )
                frame.to_sql(name, connection, index=False, if_exists="replace")
            connection.execute("CREATE TABLE metadata (value TEXT NOT NULL)")
            connection.execute("INSERT INTO metadata VALUES (?)", (json.dumps(tables.metadata),))
            connection.commit()
        os.replace(temporary, database)
    finally:
        temporary.unlink(missing_ok=True)
    return version


def load_tables(database: str | Path) -> Tables:
    database = Path(database)
    if not database.is_file():
        raise ValueError(f"Database does not exist: {database}; run demo or ingest first")
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        frames = {name: pd.read_sql_query(f"SELECT * FROM {name}", connection) for name in SCHEMAS}
        metadata = json.loads(connection.execute("SELECT value FROM metadata").fetchone()[0])
    return Tables(**frames, metadata=metadata).validate()
