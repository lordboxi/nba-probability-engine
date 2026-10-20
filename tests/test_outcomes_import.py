import csv
import io
from types import SimpleNamespace

import pytest

from nbaprob.data.journal import history, save_forecast
from nbaprob.data.outcomes_import import (
    FIELDS,
    import_outcomes,
    outcomes_template,
    prepare_outcomes,
)

AT = "2020-01-02T00:00:00Z"


def archive(config):
    game = SimpleNamespace(game_id="g", date="2020-01-01T12:00:00Z", home_team="H", away_team="A")
    save_forecast({"game_id": "g", "as_of": "2020-01-01T00:00:00Z"}, game, config)


def document(**changes):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerow(
        {
            "game_id": "g",
            "home_team": "H",
            "away_team": "A",
            "home_points": "110",
            "away_points": "100",
            "status": "Final",
            **changes,
        }
    )
    return buffer.getvalue()


def test_import_scores_is_idempotent_and_corrections_are_new_revisions(config):
    archive(config)
    forecasts, _ = history(config)
    assert "g,H,A,,,Final" in outcomes_template(forecasts, AT)
    assert "g,H,A" not in outcomes_template(forecasts, "2019-12-31T00:00:00Z")
    assert import_outcomes(config, document(), AT) == {"submitted": 1, "unchanged": 0}
    assert import_outcomes(config, document(), AT) == {"submitted": 0, "unchanged": 1}
    correction = document(home_points="111")
    assert import_outcomes(config, correction, "2020-01-03T00:00:00Z")["submitted"] == 1
    assert history(config)[1]["g"]["home_points"] == 111


@pytest.mark.parametrize(
    "changes",
    [
        {"game_id": "wrong"},
        {"home_team": "A", "away_team": "H"},
        {"status": "Live"},
        {"home_points": "-1"},
        {"home_points": "100"},
        {"home_points": "110.5"},
    ],
)
def test_invalid_result_rows_are_rejected_before_writing(config, changes):
    archive(config)
    with pytest.raises(ValueError):
        import_outcomes(config, document(**changes), AT)
    assert history(config)[1] == {}


def test_whole_file_validation_precedes_any_write_and_rejects_future_scores(config):
    archive(config)
    text = document() + document(game_id="unknown").splitlines()[1] + "\n"
    with pytest.raises(ValueError, match="Unknown"):
        import_outcomes(config, text, AT)
    assert history(config)[1] == {}
    forecasts, outcomes = history(config)
    with pytest.raises(ValueError, match="before"):
        prepare_outcomes(document(), forecasts, outcomes, "2019-12-31T00:00:00Z")
    with pytest.raises(ValueError, match="duplicate"):
        prepare_outcomes(document() + document().splitlines()[1], forecasts, outcomes, AT)
