"""Load bundled NBA snapshots without copying local journals or changing observation time."""

import json
from pathlib import Path

from nbaprob.data.snapshots import save_snapshot


def bootstrap_snapshots(config, directory):
    saved = []
    for path in sorted(Path(directory).glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("provider") != "NBA.com" or document.get("resource") not in {
            "teams",
            "roster",
        }:
            raise ValueError("Bundled data must be an NBA team or roster snapshot")
        saved.append(save_snapshot(document, config)["identity"])
    return saved
