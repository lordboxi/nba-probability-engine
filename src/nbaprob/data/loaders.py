"""Local CSV adapter; no network access or credentials are involved."""

from pathlib import Path
from typing import Protocol

import pandas as pd

from nbaprob.data.schema import SCHEMAS, Tables


class SourceAdapter(Protocol):
    def load(self) -> Tables: ...


class CSVAdapter:
    def __init__(self, directory: str | Path, metadata: dict):
        self.directory = Path(directory)
        self.metadata = metadata

    def load(self) -> Tables:
        frames = {}
        for name, columns in SCHEMAS.items():
            path = self.directory / f"{name}.csv"
            if not path.exists() and name != "games":
                frames[name] = pd.DataFrame(columns=columns)
            else:
                frames[name] = pd.read_csv(
                    path, dtype={"game_id": str, "team": str, "home_team": str, "away_team": str}
                )
        return Tables(**frames, metadata=self.metadata).validate()
