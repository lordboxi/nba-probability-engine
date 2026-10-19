"""Issue forecasts before tipoff, then score them only after results are available."""

import pandas as pd

from nbaprob.data.schema import utc
from nbaprob.features.build import ReplayEngine


def walk_forward(tables, config, start=None, end=None, as_of=None) -> pd.DataFrame:
    engine = ReplayEngine(tables, config)
    completed = tables.games[tables.games.results_available_at.notna()]
    if completed.empty:
        raise ValueError("No completed games available for evaluation")
    evaluation_as_of = utc(as_of) if as_of is not None else completed.results_available_at.max()
    engine.advance(evaluation_as_of)
    start = utc(start) if start is not None else None
    end = utc(end) if end is not None else None
    if start is not None and end is not None and start >= end:
        raise ValueError("start must precede end")
    rows = []
    for game in completed.sort_values(["date", "game_id"]).itertuples(index=False):
        if game.results_available_at > evaluation_as_of:
            continue
        if (start is not None and game.date < start) or (end is not None and game.date >= end):
            continue
        forecast = engine.forecasts.get(game.game_id)
        if forecast is None:
            continue
        features = forecast["features"]
        if features["training_games"] < config["evaluation"]["min_train_games"]:
            continue
        rows.append(
            {
                "game_id": game.game_id,
                "season": int(game.season),
                "date": game.date.isoformat(),
                "as_of": features["as_of"],
                "results_available_at": game.results_available_at.isoformat(),
                "home_team": game.home_team,
                "away_team": game.away_team,
                "home_win": int(game.home_pts > game.away_pts),
                "margin": float(game.home_pts - game.away_pts),
                "total": float(game.home_pts + game.away_pts),
                **{
                    key: forecast[key]
                    for key in (
                        "p_home_win",
                        "p_hca_only",
                        "p_home_frequency",
                        "mu_margin",
                        "mu_total",
                        "sigma_margin",
                        "sigma_total",
                    )
                },
                "pace": features["pace"],
                "training_games": features["training_games"],
            }
        )
    if not rows:
        raise ValueError("No evaluation games after warmup/date filters; add data or adjust config")
    return pd.DataFrame(rows)
