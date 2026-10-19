import pytest

from nbaprob.data.nba_html import roster_from_html, teams_from_html
from nbaprob.data.nba_stats import normalize_roster, normalize_teams


def test_visible_table_import_preserves_filter_identity_and_team_ids():
    labels = ["", "TEAM", "GP", "W", "L", "WIN%", "MIN", "PTS", "+/-", "FGA", "FTA", "OREB", "TOV"]
    values = [
        "1",
        '<a href="/stats/team/123/traditional">Fixture Team</a>',
        "4",
        "3",
        "1",
        ".750",
        "48.0",
        "110.0",
        "5.0",
        "85.0",
        "20.0",
        "10.0",
        "13.0",
    ]
    html = '<select><option selected value="2026-27"></option></select>'
    html += '<select><option selected value="Pre Season"></option></select>'
    html += '<select><option selected value="PerGame"></option></select>'
    html += "<table><tr>" + "".join(f"<th>{name}</th>" for name in labels) + "</tr><tr>"
    html += "".join(f"<td>{value}</td>" for value in values) + "</tr></table>"
    rows = normalize_teams(teams_from_html(html, "2026-27", "Pre Season"))
    assert rows[0]["team_id"] == "123"
    assert rows[0]["win_pct"] == 0.75
    with pytest.raises(ValueError, match="filters"):
        teams_from_html(html, "2025-26", "Pre Season")


def test_roster_import_excludes_retired_players_and_preserves_names():
    html = """<table><tr><th>Player</th><th>#</th><th>Pos</th></tr>
      <tr><td><a href="/player/1/fixture">Fixture Active</a></td><td>0</td><td>G</td></tr></table>
      <table><tr><th>Player</th><th>POS</th><th>Seasons With Team</th></tr>
      <tr><td><a href="/player/2/retired">Fixture Retired</a></td>
      <td>F</td><td>1990</td></tr></table>"""
    rows = normalize_roster(roster_from_html(html, "123"), "123")
    assert len(rows) == 1
    assert rows[0]["name"] == "Fixture Active"
    assert rows[0]["jersey"] == "0"


def test_server_html_without_a_rendered_team_table_is_not_misreported_as_data():
    html = '<select><option selected value="2026-27"></option></select>'
    html += '<select><option selected value="Pre Season"></option></select>'
    html += '<select><option selected value="PerGame"></option></select>'
    html += "<main>Loading team stats...</main>"
    with pytest.raises(ValueError, match="did not contain"):
        teams_from_html(html, "2026-27", "Pre Season")
