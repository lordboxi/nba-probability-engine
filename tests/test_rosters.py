import json
from pathlib import Path

from nbaprob.data.rosters import latest_roster
from nbaprob.data.snapshots import save_snapshot

ROOT = Path(__file__).parents[1]


def test_all_nba_teams_have_observed_rosters_without_cross_team_duplicates():
    teams = json.loads(
        (ROOT / "deployment/seed_snapshots/teams-2025-26-regular.json").read_text(encoding="utf-8")
    )["data"]
    docs = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in (ROOT / "deployment/roster_cache").glob("*.json")
    ]
    assert {doc["team_id"] for doc in docs} == {team["team_id"] for team in teams}
    seen = set()
    for doc in docs:
        assert doc["resource"] == "roster" and doc["provider"] == "NBA.com"
        assert doc["season"] == "2026-27" and len(doc["data"]) >= 5
        assert "raw_response" not in doc and doc["retrieved_at"]
        assert doc["source_url"] == f"https://www.nba.com/team/{doc['team_id']}"
        for player in doc["data"]:
            assert player["team_id"] == doc["team_id"]
            assert player["player_id"] not in seen
            seen.add(player["player_id"])


def test_roster_resolution_keeps_observed_cutoff_and_newer_database_versions(
    config, tmp_path, monkeypatch
):
    monkeypatch.setattr("nbaprob.data.rosters.BUNDLED_ROSTERS", tmp_path)
    doc = {
        "resource": "roster",
        "provider": "NBA.com",
        "team_id": "1",
        "season": "2026-27",
        "retrieved_at": "2026-10-20T01:00:00Z",
        "source_url": "https://www.nba.com/team/1",
        "data": [{"player_id": "99", "team_id": "1", "name": "Original"}],
    }
    (tmp_path / "1.json").write_text(json.dumps(doc), encoding="utf-8")
    assert latest_roster(config, "2026-27", "2026-10-20T00:00:00Z", "1") is None
    assert latest_roster(config, "2025-26", "2026-10-20T02:00:00Z", "1") is None
    first = latest_roster(config, "2026-27", "2026-10-20T02:00:00Z", "1")
    assert first["bundled"] and first["data"][0]["name"] == "Original"
    doc["retrieved_at"] = "2026-10-20T03:00:00Z"
    doc["data"][0]["name"] = "Updated"
    save_snapshot(doc, config)
    assert (
        latest_roster(config, "2026-27", "2026-10-20T02:00:00Z", "1")["identity"]
        == first["identity"]
    )
    newer = latest_roster(config, "2026-27", "2026-10-20T04:00:00Z", "1")
    assert not newer.get("bundled") and newer["data"][0]["name"] == "Updated"
