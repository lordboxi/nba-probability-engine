"""Join observed player statistics by ID and construct explicit rotation adjustments."""

from nbaprob.data.schema import utc
from nbaprob.data.snapshots import latest_snapshot
from nbaprob.lineups.scenarios import allocate_minutes


def player_statistics(config, season, season_type, as_of, selection):
    year = int(season[:4]) - 1
    previous = f"{year}-{(year + 1) % 100:02d}"
    candidates = [(season, season_type), (previous, "Regular Season")]
    if season_type == "Regular Season":
        candidates.append((season, "Preseason"))
    documents = [
        latest_snapshot(config, "players", year, as_of, kind)
        for year, kind in dict.fromkeys(candidates)
    ]
    matched = {}
    for player in selection["players"]:
        for document in documents:
            if document is None:
                continue
            rows = [
                row
                for row in document["data"]
                if row["player_id"] == player["player_id"] and row["gp"] > 0
            ]
            if not rows:
                continue
            row = max(
                rows,
                key=lambda row: (
                    row["team_id"] == player.get("team_id"),
                    row["team_id"] == "0",
                    row["gp"],
                ),
            )
            matched[player["player_id"]] = {
                **row,
                "season": document["season"],
                "season_type": document["season_type"],
                "retrieved_at": document["retrieved_at"],
                "snapshot_id": document["identity"],
                "different_team": row["team_id"] not in ("0", player.get("team_id")),
            }
            break
    return matched


def rotation_rows(selection, statistics, config):
    """Minutes are normalized to 240; box scores never become invented impact ratings."""
    result = []
    tolerance = config["lineups"]["minutes_tolerance"]
    for team in dict.fromkeys(row["team"] for row in selection["players"]):
        players = [row for row in selection["players"] if row["team"] == team]
        if len(players) < 5 or sum(row["plays"] for row in players) < 5:
            raise ValueError("Select at least five players per team before projecting minutes")
        weights = [
            {**row, "expected_minutes": statistics.get(row["player_id"], {}).get("minutes", 12.0)}
            for row in players
        ]
        baseline, _ = allocate_minutes(weights, {row["player_id"] for row in players}, tolerance)
        projected, _ = allocate_minutes(
            weights, {row["player_id"] for row in players if row["plays"]}, tolerance
        )
        for row, normal, expected in zip(players, baseline, projected, strict=True):
            result.append(
                {
                    "player_id": row["player_id"],
                    "name": row["name"],
                    "team": team,
                    "starter": row["starter"],
                    "plays": row["plays"],
                    "baseline_minutes": float(normal),
                    "expected_minutes": float(expected),
                    "offense_impact": 0.0,
                    "defense_impact": 0.0,
                }
            )
    return result


def rotation_document(rows, selection, statistics, game, as_of, source):
    if not source.strip():
        raise ValueError("Specify the source of player impact ratings")
    selected = {row["player_id"]: row for row in selection["players"]}
    if len(rows) != len(selected) or {row["player_id"] for row in rows} != set(selected):
        raise ValueError("Rotation must contain exactly the selected roster's player IDs")
    players = []
    for row in rows:
        original = selected[row["player_id"]]
        players.append(
            {
                **row,
                "team": original["team"],
                "starter": original["starter"],
                "status": "available" if original["plays"] else "out",
                "play_probability": float(original["plays"]),
                "rating_as_of": utc(as_of).isoformat(),
            }
        )
    return {
        "game_id": game.game_id,
        "reported_at": utc(as_of).isoformat(),
        "rating_source": source.strip(),
        "probability_source": "manual active roster",
        "players": players,
        "statistics_provenance": {
            key: {
                field: value[field]
                for field in (
                    "season",
                    "season_type",
                    "retrieved_at",
                    "snapshot_id",
                    "team_id",
                    "different_team",
                )
            }
            for key, value in statistics.items()
        },
        "minutes_policy": "Per-game minutes normalized to 240 across current roster; "
        "missing players start at a 12-minute weight. Manual edits allowed.",
    }
