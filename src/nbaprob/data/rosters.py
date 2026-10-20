"""Resolve observed NBA rosters without requiring a current-season team stats table."""

import hashlib
import json
from pathlib import Path

from nbaprob.data.schema import utc
from nbaprob.data.snapshots import latest_snapshot

BUNDLED_ROSTERS = Path(__file__).resolve().parents[3] / "deployment/roster_cache"


def latest_roster(config, season, as_of, team_id):
    if not str(team_id).isdigit():
        raise ValueError("NBA team_id must be numeric")
    stored = latest_snapshot(config, "roster", season, as_of, team_id=team_id)
    path = BUNDLED_ROSTERS / f"{team_id}.json"
    if not path.is_file():
        return stored
    bundled = json.loads(path.read_text(encoding="utf-8"))
    if (
        bundled.get("provider") != "NBA.com"
        or bundled.get("resource") != "roster"
        or bundled.get("season") != season
        or bundled.get("team_id") != str(team_id)
        or utc(bundled["retrieved_at"]) > utc(as_of)
    ):
        return stored
    if stored is not None and utc(stored["retrieved_at"]) >= utc(bundled["retrieved_at"]):
        return stored
    serialized = json.dumps(bundled, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return {**bundled, "identity": hashlib.sha256(serialized.encode()).hexdigest(), "bundled": True}
