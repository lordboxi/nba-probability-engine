"""Experimental current-team prior from timestamped NBA Traditional table snapshots."""

from types import SimpleNamespace

import numpy as np
from scipy.stats import norm

from nbaprob.data.schema import utc


def matchup_forecast(
    snapshot,
    home_team_id,
    away_team_id,
    tipoff,
    as_of,
    config,
    *,
    previous_snapshot=None,
    preseason_snapshot=None,
    season=None,
    season_type=None,
    team_catalog=None,
):
    as_of, tipoff = utc(as_of), utc(tipoff)
    season = season or (snapshot["season"] if snapshot else None)
    season_type = season_type or (snapshot["season_type"] if snapshot else "Regular Season")
    if season is None or season_type not in ("Preseason", "Regular Season", "Playoffs"):
        raise ValueError("A target NBA season and season type are required")
    for document in (snapshot, previous_snapshot, preseason_snapshot):
        if document is not None and utc(document["retrieved_at"]) > as_of:
            raise ValueError("NBA table snapshot was retrieved after prediction time")
    if snapshot and (snapshot["season"] != season or snapshot["season_type"] != season_type):
        raise ValueError("Current snapshot must match the target season and season type")
    if preseason_snapshot and (
        season_type != "Regular Season"
        or preseason_snapshot["season"] != season
        or preseason_snapshot["season_type"] != "Preseason"
    ):
        raise ValueError("Preseason prior must match the target Regular Season's year")
    previous_year = int(season[:4]) - 1
    previous_season = f"{previous_year}-{(previous_year + 1) % 100:02d}"
    if previous_snapshot and (
        previous_snapshot["season"] != previous_season
        or previous_snapshot["season_type"] != "Regular Season"
    ):
        raise ValueError("Prior must be the previous season's Regular Season table")
    if tipoff <= as_of:
        raise ValueError("Prediction must be before tipoff")
    if str(home_team_id) == str(away_team_id):
        raise ValueError("Select two different teams")
    current = {str(row["team_id"]): row for row in snapshot["data"]} if snapshot else {}
    previous = (
        {str(row["team_id"]): row for row in previous_snapshot["data"]} if previous_snapshot else {}
    )
    preseason = (
        {str(row["team_id"]): row for row in preseason_snapshot["data"]}
        if preseason_snapshot
        else {}
    )
    lookup = {str(row["team_id"]): row for row in (team_catalog or [])}
    lookup.update(previous)
    lookup.update(preseason)
    lookup.update(current)
    if str(home_team_id) not in lookup or str(away_team_id) not in lookup:
        raise ValueError("Team not present in the available team catalog")
    home, away = lookup[str(home_team_id)], lookup[str(away_team_id)]
    cfg = config["features"]

    def raw_ratings(row):
        possessions = row["fga"] + config["feed"]["possession_fta_weight"] * row["fta"]
        possessions += row["turnovers"] - row["oreb"]
        if possessions <= 0 or row["points"] - row["plus_minus"] <= 0:
            raise ValueError("Traditional table cannot produce valid estimated possessions/defense")
        pace = possessions * 48 / row["minutes"]
        offense = row["points"] * 100 / possessions
        defense = (row["points"] - row["plus_minus"]) * 100 / possessions
        return np.array([pace, offense, defense])

    basis = {}

    def ratings(team_id):
        team_id = str(team_id)
        row, prior = current.get(team_id), previous.get(team_id)
        preseason_row = preseason.get(team_id)
        preseason_games = float(preseason_row["gp"]) if preseason_row else 0.0
        preseason_effective = preseason_games * config["feed"]["preseason_game_weight"]
        prior_games = float(prior["gp"]) if prior else 0.0
        games = float(row["gp"]) if row else 0.0
        league = np.array([cfg["league_pace"], cfg["league_ortg"], cfg["league_ortg"]])
        k = config["feed"]["snapshot_shrink_k"]
        retained = config["ratings"]["prior_shrink"] * prior_games / (prior_games + k)
        prior_rating = (
            retained * raw_ratings(prior) + (1 - retained) * league if prior_games else league
        )
        preseason_weight = preseason_effective / (preseason_effective + k)
        if preseason_games:
            prior_rating = (
                preseason_weight * raw_ratings(preseason_row)
                + (1 - preseason_weight) * prior_rating
            )
        effective_games = games * (
            config["feed"]["preseason_game_weight"] if season_type == "Preseason" else 1
        )
        weight = effective_games / (effective_games + k)
        result = weight * raw_ratings(row) + (1 - weight) * prior_rating if games else prior_rating
        evidence = (
            effective_games
            + preseason_effective
            + config["market"]["prior_equivalent_games"] * prior_games / (prior_games + k)
        )
        basis[team_id] = {
            "team": lookup[team_id]["team"],
            "games": games,
            "effective_games": effective_games,
            "current_weight": weight,
            "previous_season_games": prior_games,
            "previous_rating_retention": retained,
            "preseason_games": preseason_games,
            "preseason_effective_games": preseason_effective,
            "preseason_weight_in_final_rating": (1 - weight) * preseason_weight,
            "evidence_games": evidence,
        }
        return (*result, result[1] - result[2])

    home_pace, home_o, home_d, home_net = ratings(home_team_id)
    away_pace, away_o, away_d, away_net = ratings(away_team_id)
    pace = (home_pace + away_pace) / 2
    mu_margin = (home_net - away_net) * pace / 100 + config["model"]["initial_hca"]
    mu_total = (home_o + away_d + away_o + home_d) / 2 * pace / 100
    sigma_margin = config["model"]["margin_sigma"] * np.sqrt(pace / cfg["league_pace"])
    sigma_total = config["model"]["total_sigma"] * np.sqrt(pace / cfg["league_pace"])
    game = SimpleNamespace(
        game_id=f"matchup-{season}-{home_team_id}-{away_team_id}-{int(tipoff.timestamp())}",
        date=tipoff,
        season=int(season[:4]),
        home_team=home["team"],
        away_team=away["team"],
    )
    base = {
        "model": "experimental_team_snapshot",
        "mu_margin": mu_margin,
        "mu_total": mu_total,
        "sigma_margin": float(sigma_margin),
        "sigma_total": float(sigma_total),
        "p_home_win": float(norm.cdf(mu_margin / sigma_margin)),
        "features": {
            "game_id": game.game_id,
            "as_of": as_of.isoformat(),
            "home_team": home["team"],
            "away_team": away["team"],
            "pace": pace,
            "home_rating": home_net,
            "away_rating": away_net,
            "training_games": 0,
            "snapshot_games_home": basis[str(home_team_id)]["games"],
            "snapshot_games_away": basis[str(away_team_id)]["games"],
        },
        "snapshot": {key: snapshot[key] for key in ("season", "season_type", "retrieved_at")}
        if snapshot
        else {"season": season, "season_type": season_type, "retrieved_at": None},
        "snapshot_id": snapshot.get("identity") if snapshot else None,
        "previous_snapshot": (
            {
                **{
                    key: previous_snapshot[key] for key in ("season", "season_type", "retrieved_at")
                },
                "identity": previous_snapshot.get("identity"),
            }
            if previous_snapshot
            else None
        ),
        "preseason_snapshot": (
            {
                **{
                    key: preseason_snapshot[key]
                    for key in ("season", "season_type", "retrieved_at")
                },
                "identity": preseason_snapshot.get("identity"),
            }
            if preseason_snapshot
            else None
        ),
        "data_readiness": {
            "teams": basis,
            "evidence_games": min(row["evidence_games"] for row in basis.values()),
            "season_type": season_type,
            "missing": [
                *(
                    ["current_season_stats"]
                    if any(row["games"] == 0 for row in basis.values())
                    else []
                ),
                *(
                    ["previous_season_stats"]
                    if any(row["previous_season_games"] == 0 for row in basis.values())
                    else []
                ),
                *(
                    ["preseason_stats"]
                    if season_type == "Regular Season"
                    and any(row["preseason_games"] == 0 for row in basis.values())
                    else []
                ),
                "player_impact_ratings",
                "rest_travel_context",
                "real_holdout_validation",
            ],
            "weight_policy": "Heuristic sample-size weights; not learned or calibrated",
        },
        "estimation": "Traditional FGA + coefficient*FTA - OREB + TOV; "
        "estimated pace/efficiency with small-sample shrinkage, not official ORtg/DRtg",
        "context_coefficients": {"hca": config["model"]["initial_hca"]},
    }
    return game, base
