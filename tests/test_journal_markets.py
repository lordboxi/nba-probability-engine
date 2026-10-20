import json
from copy import deepcopy

import pytest

from nbaprob.eval.journal_markets import market_scores, settle_market
from nbaprob.pricing.reading import house_reading


def forecast(market="moneyline", line=None, *, game_id="g", probability=0.6, identity="a"):
    sides = ("over", "under") if market == "total" else ("home", "away")
    comparison = {
        "market": market,
        "line": line,
        "decision": "insufficient_evidence",
        "candidate": None,
        "sides": [
            {
                "side": side,
                "model_probability_no_push": p,
                "house_fair_probability": h,
                "offered_decimal": price,
                "expected_value_per_unit": p * price - 1,
            }
            for side, p, h, price in zip(
                sides, (probability, 1 - probability), (0.45, 0.55), (2.0, 1.8), strict=True
            )
        ],
    }
    payload = {"synthetic": False, "p_home_win": probability, "house_comparison": comparison}
    return {
        "game_id": game_id,
        "identity": identity,
        "tipoff": "2026-10-19T10:00:00Z",
        "as_of": "2026-10-19T07:00:00Z",
        "issued_at": "2026-10-19T07:01:00Z",
        "home_team": "Home",
        "away_team": "Away",
        "payload": json.dumps(payload),
    }


@pytest.mark.parametrize(
    "market,line,home,away,expected",
    [
        ("moneyline", None, 110, 100, 1),
        ("moneyline", None, 100, 110, 0),
        ("spread", -10, 110, 100, 0.5),
        ("spread", -10.5, 110, 100, 0),
        ("spread", 5.5, 100, 105, 1),
        ("total", 210, 110, 100, 0.5),
        ("total", 209.5, 110, 100, 1),
        ("total", 210.5, 110, 100, 0),
    ],
)
def test_market_settlement_uses_saved_home_handicap_and_pushes(market, line, home, away, expected):
    assert settle_market(market, line, home, away) == expected


def test_house_reading_keeps_likely_outcome_separate_from_price_value():
    payload = json.loads(forecast(probability=0.7)["payload"])
    comparison = payload["house_comparison"]
    # A 70% favorite at 1.1 can be worse value than the 30% underdog at 4.0.
    comparison["sides"][0]["expected_value_per_unit"] = 0.7 * 1.1 - 1
    comparison["sides"][1]["expected_value_per_unit"] = 0.3 * 4 - 1
    result = house_reading(comparison)
    assert result["most_likely_model"] == "home"
    assert result["most_likely_house"] == "away"
    assert result["highest_ev_side"] == "away" and result["positive_ev_sides"] == ["away"]
    assert result["candidate"] is None and result["decision"] == "insufficient_evidence"


def test_market_reports_keep_markets_separate_and_latest_line_without_lookahead(config):
    rows = [
        forecast(),
        forecast("spread", -9.5, identity="b"),
        forecast("total", 209.5, identity="c"),
    ]
    # Latest legitimate spread prediction is at -10 (push); no choosing the earlier winning line.
    latest = deepcopy(rows[1])
    latest.update(identity="d", as_of="2026-10-19T08:00:00Z", issued_at="2026-10-19T08:01:00Z")
    payload = json.loads(latest["payload"])
    payload["house_comparison"]["line"] = -10
    latest["payload"] = json.dumps(payload)
    rows.append(latest)
    retrospective = deepcopy(rows[0])
    retrospective.update(
        identity="z", as_of="2026-10-19T09:00:00Z", issued_at="2026-10-19T12:00:00Z"
    )
    rows.append(retrospective)
    outcomes = {"g": {"home_points": 110, "away_points": 100}}
    result = market_scores(rows, outcomes, config)
    moneyline, spread, total = (result["markets"][m] for m in ("moneyline", "spread", "total"))
    assert moneyline["scores"]["model"]["brier"] == pytest.approx(0.4**2)
    assert moneyline["scores"]["house"]["brier"] == pytest.approx(0.55**2)
    assert moneyline["picks"]["model"]["hit_rate"] == 1
    assert moneyline["picks"]["house"]["hit_rate"] == 0
    assert moneyline["picks"]["model"]["paper_profit_units"] == 1
    assert moneyline["picks"]["house"]["paper_profit_units"] == -1
    assert spread["settled_games"] == spread["push_games"] == 1
    assert spread["scored_games"] == 0 and not spread["scores"]
    assert spread["picks"]["model"]["paper_roi"] == 0
    assert spread["picks"]["model"]["hit_rate"] is None
    assert total["settled_games"] == total["scored_games"] == 1
    assert {r["forecast_id"] for r in result["details"]} == {"a", "c", "d"}


def test_synthetic_stale_and_missing_prices_do_not_create_claimed_returns(config):
    rows = [
        forecast(game_id="real", probability=0.5),
        forecast(game_id="fake"),
        forecast(game_id="stale"),
    ]
    for row in rows:
        payload = json.loads(row["payload"])
        if row["game_id"] == "fake":
            payload["synthetic"] = True
        elif row["game_id"] == "stale":
            payload["house_comparison"]["decision"] = "refresh_quote"
        else:
            for side in payload["house_comparison"]["sides"]:
                side.update(offered_decimal=None, expected_value_per_unit=None)
        row["payload"] = json.dumps(payload)
    outcomes = {key: {"home_points": 100, "away_points": 90} for key in ("real", "fake", "stale")}
    result = market_scores(rows, outcomes, config)
    report = result["markets"]["moneyline"]
    assert report["scored_games"] == 1
    assert report["picks"]["model"]["hit_rate"] is None  # A tied model abstains.
    assert report["picks"]["house"]["priced_picks"] == 0
    assert report["picks"]["house"]["paper_roi"] is None
    assert result["details"][0]["model_result"] == "no_pick"


def test_history_ui_displays_settled_market_scores_and_pushes(config, tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    import yaml
    from streamlit.testing.v1 import AppTest

    import nbaprob.app

    rows = [forecast(), forecast("spread", -10, identity="b")]
    outcomes = {"g": {"home_points": 110, "away_points": 100}}
    monkeypatch.setattr(nbaprob.app, "history", lambda cfg: (rows, outcomes))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(config), encoding="utf-8")
    app = AppTest.from_string(
        "from nbaprob.app import history_panel\nfrom nbaprob.config import load_config\n"
        f"history_panel(load_config({str(cfg)!r}))"
    ).run(timeout=30)
    assert not app.error and not app.exception
    assert any("ประเมิน probability 1 เกม" in item.value for item in app.markdown)
    app.selectbox(key="history_market").set_value("spread").run(timeout=30)
    assert not app.error and not app.exception
    assert any("คืนทุน 1 เกม" in item.value for item in app.markdown)
    assert any("นำเข้าผลจริงหลายเกม" in item.label for item in app.expander)
