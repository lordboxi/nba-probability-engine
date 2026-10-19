import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from nbaprob.analysis import analyze_forecast
from nbaprob.data.journal import history, journal_scores, record_outcome, save_forecast
from nbaprob.data.snapshots import save_snapshot
from nbaprob.models.team_snapshot import matchup_forecast


@pytest.fixture
def snapshot():
    return {
        "resource": "teams",
        "season": "2026-27",
        "season_type": "Regular Season",
        "retrieved_at": "2026-10-19T06:00:00Z",
        "identity": "fixture-current",
        "data": [
            {
                "team_id": str(index),
                "team": name,
                "gp": 0,
                "minutes": 48,
                "points": points,
                "plus_minus": net,
                "fga": 85,
                "fta": 20,
                "oreb": 10,
                "turnovers": 13,
                "win_pct": 0.5,
            }
            for index, name, points, net in (
                (1, "Fixture Home", 115, 8),
                (2, "Fixture Away", 105, -4),
            )
        ],
    }


def forecast(config, snapshot, previous=None):
    return matchup_forecast(
        snapshot,
        "1",
        "2",
        "2026-10-19T10:00:00Z",
        "2026-10-19T07:00:00Z",
        config,
        previous_snapshot=previous,
    )


def quote(game, market="moneyline", line=None):
    return {
        "game_id": game.game_id,
        "market": market,
        "line": line,
        "input_type": "decimal_odds",
        "primary": 1.5,
        "secondary": 2.8,
        "quoted_at": "2026-10-19T07:00:00Z",
    }


def test_zero_games_uses_explicit_league_prior_and_house_reference(config, snapshot):
    game, base = forecast(config, snapshot)
    assert base["features"]["home_rating"] == 0
    result = analyze_forecast(
        base, game, "2026-10-19T07:00:00Z", config, house=quote(game), use_market_prior=True
    )
    assisted = result["market_assisted"]
    assert assisted["model_weight"] == 0
    assert assisted["house_weight"] == 1
    assert assisted["house_favored_outcome"] == "home"
    assert assisted["sides"][0]["assisted_probability_no_push"] == pytest.approx(
        (1 / 1.5) / (1 / 1.5 + 1 / 2.8)
    )
    assert assisted["candidate"] is None
    assert assisted["decision"] == "market_reference_only"
    assert "current_season_stats" in result["data_readiness"]["missing"]
    assert "selected_lineup" in result["data_readiness"]["missing"]


def test_previous_season_is_regressed_and_current_games_replace_it(config, snapshot):
    prior = deepcopy(snapshot)
    prior.update(season="2025-26", identity="fixture-prior")
    for row in prior["data"]:
        row["gp"] = 82
    _, first = forecast(config, snapshot, prior)
    assert first["features"]["home_rating"] > 0
    assert first["previous_snapshot"]["identity"] == "fixture-prior"
    assert first["data_readiness"]["teams"]["1"]["current_weight"] == 0
    snapshot["data"][0].update(gp=82, plus_minus=-10)
    snapshot["data"][1].update(gp=82, plus_minus=10)
    _, later = forecast(config, snapshot, prior)
    assert later["features"]["home_rating"] < 0
    assert later["data_readiness"]["evidence_games"] > first["data_readiness"]["evidence_games"]
    assert later["data_readiness"]["teams"]["1"]["current_weight"] > 0.8


def test_missing_current_table_can_use_prior_or_catalog_without_fake_games(config, snapshot):
    prior = deepcopy(snapshot)
    prior["season"] = "2025-26"
    for row in prior["data"]:
        row["gp"] = 82
    for previous in (None, prior):
        _, base = matchup_forecast(
            None,
            "1",
            "2",
            "2026-10-19T10:00:00Z",
            "2026-10-19T07:00:00Z",
            config,
            previous_snapshot=previous,
            season="2026-27",
            team_catalog=snapshot["data"],
        )
        assert base["snapshot_id"] is None
        assert base["snapshot"]["retrieved_at"] is None
        assert base["features"]["snapshot_games_home"] == 0


def test_preseason_can_seed_regular_season_without_becoming_regular_games(config, snapshot):
    preseason = deepcopy(snapshot)
    preseason.update(season_type="Preseason", identity="fixture-preseason")
    for row in preseason["data"]:
        row["gp"] = 5
    game, base = matchup_forecast(
        None,
        "1",
        "2",
        "2026-10-19T10:00:00Z",
        "2026-10-19T07:00:00Z",
        config,
        season="2026-27",
        preseason_snapshot=preseason,
    )
    assert base["snapshot"]["season_type"] == "Regular Season"
    assert base["snapshot_id"] is None
    assert base["preseason_snapshot"]["identity"] == "fixture-preseason"
    assert base["features"]["snapshot_games_home"] == 0
    assert base["features"]["home_rating"] > 0
    basis = base["data_readiness"]["teams"]["1"]
    assert basis["preseason_games"] == 5
    assert basis["preseason_effective_games"] == pytest.approx(0.5)
    assert basis["preseason_weight_in_final_rating"] == pytest.approx(0.5 / 20.5)
    result = analyze_forecast(
        base, game, "2026-10-19T07:00:00Z", config, house=quote(game), use_market_prior=True
    )
    assert result["market_assisted"]["model_weight"] == pytest.approx(0.5 / 20.5)
    assert result["preseason_snapshot"]["identity"] == "fixture-preseason"
    assert "current_season_stats" in result["data_readiness"]["missing"]
    assert "preseason_stats" not in result["data_readiness"]["missing"]
    # Regular Season games gradually replace the small Preseason contribution.
    for row in snapshot["data"]:
        row["gp"] = 20
    _, later = matchup_forecast(
        snapshot,
        "1",
        "2",
        "2026-10-19T10:00:00Z",
        "2026-10-19T07:00:00Z",
        config,
        preseason_snapshot=preseason,
    )
    assert later["data_readiness"]["teams"]["1"][
        "preseason_weight_in_final_rating"
    ] == pytest.approx(basis["preseason_weight_in_final_rating"] / 2)


@pytest.mark.parametrize("mutation", ["future", "wrong_year", "wrong_type", "wrong_target"])
def test_preseason_prior_rejects_misaligned_or_future_sources(config, snapshot, mutation):
    preseason = deepcopy(snapshot)
    preseason["season_type"] = "Preseason"
    target_type = "Regular Season"
    if mutation == "future":
        preseason["retrieved_at"] = "2026-10-19T08:00:00Z"
    elif mutation == "wrong_year":
        preseason["season"] = "2025-26"
    elif mutation == "wrong_type":
        preseason["season_type"] = "Regular Season"
    else:
        target_type = "Preseason"
    with pytest.raises(ValueError):
        matchup_forecast(
            None,
            "1",
            "2",
            "2026-10-19T10:00:00Z",
            "2026-10-19T07:00:00Z",
            config,
            season="2026-27",
            season_type=target_type,
            preseason_snapshot=preseason,
        )


@pytest.mark.parametrize("kind", ["future_prior", "wrong_year", "wrong_type", "wrong_current_type"])
def test_prior_sources_must_match_and_be_known_at_prediction(config, snapshot, kind):
    prior = deepcopy(snapshot)
    prior["season"] = "2025-26"
    if kind == "future_prior":
        prior["retrieved_at"] = "2026-10-19T08:00:00Z"
    elif kind == "wrong_year":
        prior["season"] = "2024-25"
    elif kind == "wrong_type":
        prior["season_type"] = "Preseason"
    else:
        with pytest.raises(ValueError, match="match"):
            matchup_forecast(
                snapshot,
                "1",
                "2",
                "2026-10-19T10:00:00Z",
                "2026-10-19T07:00:00Z",
                config,
                season_type="Preseason",
            )
        return
    with pytest.raises(ValueError):
        forecast(config, snapshot, prior)


def test_preseason_is_discounted_and_market_weight_grows_with_games(config, snapshot):
    weights = []
    for games, season_type in ((5, "Preseason"), (5, "Regular Season"), (40, "Regular Season")):
        snapshot["season_type"] = season_type
        for row in snapshot["data"]:
            row["gp"] = games
        game, base = forecast(config, snapshot)
        result = analyze_forecast(
            base, game, "2026-10-19T07:00:00Z", config, house=quote(game), use_market_prior=True
        )
        weights.append(result["market_assisted"]["model_weight"])
        assert sum(
            row["assisted_probability_no_push"] for row in result["market_assisted"]["sides"]
        ) == pytest.approx(1)
    assert 0 < weights[0] < weights[1] < weights[2] < 1


@pytest.mark.parametrize(
    "market,line,favorite",
    [("spread", -5, "home"), ("spread", 5, "away"), ("spread", 0, None), ("total", 228, None)],
)
def test_market_prior_keeps_market_meaning_and_does_not_assert_push_ev(
    config, snapshot, market, line, favorite
):
    game, base = forecast(config, snapshot)
    result = analyze_forecast(
        base,
        game,
        "2026-10-19T07:00:00Z",
        config,
        house=quote(game, market, line),
        use_market_prior=True,
    )
    assisted = result["market_assisted"]
    assert assisted["handicap_favorite"] == favorite
    assert "expected_value_per_unit" not in assisted["sides"][0]
    assert assisted["market"] == market
    assert assisted["line"] == line


def test_snapshot_edge_remains_research_only_and_stale_quote_is_flagged(config, snapshot):
    for row in snapshot["data"]:
        row["gp"] = 50
    game, base = forecast(config, snapshot)
    odds = quote(game)
    odds.update(primary=2.0, secondary=2.0)
    result = analyze_forecast(
        base, game, "2026-10-19T07:00:00Z", config, house=odds, use_market_prior=True
    )
    assert result["house_comparison"]["decision"] == "insufficient_evidence"
    assert result["house_comparison"]["candidate"] is None
    odds["quoted_at"] = "2026-10-19T06:00:00Z"
    result = analyze_forecast(
        base, game, "2026-10-19T07:00:00Z", config, house=odds, use_market_prior=True
    )
    assert result["market_assisted"]["decision"] == "refresh_quote"


def set_clock(monkeypatch, hour):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 19, hour, tzinfo=UTC)

    monkeypatch.setattr("nbaprob.data.journal.datetime", Clock)


def test_journal_records_inputs_once_and_scores_matched_games(config, snapshot, monkeypatch):
    game, base = forecast(config, snapshot)
    result = analyze_forecast(
        base, game, "2026-10-19T07:00:00Z", config, house=quote(game), use_market_prior=True
    )
    set_clock(monkeypatch, 7)
    identity = save_forecast(result, game, config)
    assert save_forecast(result, game, config) == identity
    assert journal_scores(config)["settled_games"] == 0
    set_clock(monkeypatch, 14)
    record_outcome(config, game.game_id, 110, 100, "2026-10-19T14:00:00Z")
    summary = journal_scores(config)
    assert summary["saved_forecasts"] == 1
    assert summary["matched_moneyline_games"] == 1
    assert summary["matched_models"]["house"]["brier"] == pytest.approx(
        (1 - result["market_assisted"]["sides"][0]["house_probability_no_push"]) ** 2
    )
    # A later retrospective recomputation cannot replace a genuinely pregame issue.
    revised = deepcopy(result)
    revised["as_of"] = "2026-10-19T09:00:00Z"
    revised["p_home_win"] = 0.99
    save_forecast(revised, game, config)
    assert journal_scores(config)["model"] == summary["model"]
    records, _ = history(config)
    assert len(records) == 2
    assert json.loads(records[0]["payload"]) == result


def test_journal_excludes_synthetic_and_backfilled_predictions(config, snapshot, monkeypatch):
    game, base = forecast(config, snapshot)
    result = analyze_forecast(base, game, "2026-10-19T07:00:00Z", config, synthetic=True)
    set_clock(monkeypatch, 7)
    save_forecast(result, game, config)
    set_clock(monkeypatch, 14)
    record_outcome(config, game.game_id, 110, 100, "2026-10-19T14:00:00Z")
    result["synthetic"] = False
    save_forecast(result, game, config)
    assert journal_scores(config)["settled_games"] == 0
    with pytest.raises(ValueError, match="winner"):
        record_outcome(config, game.game_id, 100, 100, "2026-10-19T14:00:00Z")
    with pytest.raises(ValueError, match="future"):
        record_outcome(config, game.game_id, 110, 100, "2026-10-19T15:00:00Z")


def test_opening_app_without_regular_season_or_roster_can_use_house(
    config, snapshot, tmp_path, monkeypatch
):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    snapshot["season_type"] = "Preseason"
    for row in snapshot["data"]:
        row["gp"] = 5
    snapshot.pop("identity")
    save_snapshot(snapshot, config)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setenv("NBA_CONFIG", str(cfg))
    app = AppTest.from_file(str(Path(__file__).parents[1] / "src/nbaprob/app.py"))
    app.run(timeout=30)
    assert not app.exception
    assert not app.error
    assert any("ยังไม่มีสถิติประเภทนี้" in row.value for row in app.info)
    next(row for row in app.checkbox if row.label == "วิเคราะห์ระดับทีมโดยยังไม่ระบุตัวจริง").check().run(
        timeout=30
    )
    next(row for row in app.selectbox if row.label == "รูปแบบข้อมูล House").select("Decimal odds").run(
        timeout=30
    )
    next(
        row for row in app.checkbox if row.label == "ราคาตัวอย่างสำหรับทดสอบ (ไม่รวมในสถิติ)"
    ).check().run(timeout=30)
    next(row for row in app.button if row.label == "คำนวณและเปรียบเทียบ").click().run(timeout=30)
    assert not app.exception
    assert not app.error, [row.value for row in app.error]
    result = json.loads(app.json[0].value)
    assert result["synthetic"] is True
    assert result["market_assisted"]["house_weight"] == pytest.approx(1 - 0.5 / 20.5)
    assert result["features"]["snapshot_games_home"] == 0
    assert result["preseason_snapshot"]["season_type"] == "Preseason"
    assert "selected_lineup" in result["data_readiness"]["missing"]
    assert len(history(config)[0]) == 1
