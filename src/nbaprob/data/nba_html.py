"""Parse only rendered HTML tables; never infer an unseen season or use hidden app state."""

import re
from html.parser import HTMLParser


class TableReader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.selected_values = []
        self.table = None
        self.row = None
        self.cell = None
        self.table_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "option" and "selected" in attrs:
            self.selected_values.append(attrs.get("value", ""))
        if tag == "table":
            self.table_depth += 1
            if self.table_depth == 1:
                self.table = []
        if not self.table_depth:
            return
        if tag == "tr":
            self.row = {"cells": [], "links": []}
        elif tag in ("td", "th"):
            self.cell = []
        elif tag == "a" and self.row is not None and attrs.get("href"):
            self.row["links"].append(attrs["href"])

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            if self.row is not None:
                self.row["cells"].append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.table is not None:
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table_depth:
            self.table_depth -= 1
            if self.table_depth == 0:
                self.tables.append(self.table)
                self.table = None


def teams_from_html(html, season, season_type):
    reader = TableReader()
    reader.feed(html)
    if reader.selected_values[:3] != [season, season_type, "PerGame"]:
        raise ValueError(
            "NBA webpage filters do not match the requested season/type/PerGame. "
            "Do not relabel a different table; use an exported response for those filters."
        )
    aliases = {
        "TEAM": "TEAM_NAME",
        "GP": "GP",
        "W": "W",
        "L": "L",
        "WIN%": "W_PCT",
        "MIN": "MIN",
        "PTS": "PTS",
        "+/-": "PLUS_MINUS",
        "FGA": "FGA",
        "FTA": "FTA",
        "OREB": "OREB",
        "TOV": "TOV",
    }
    for table in reader.tables:
        if not table or not set(aliases).issubset(table[0]["cells"]):
            continue
        headers = table[0]["cells"]
        rows = []
        for row in table[1:]:
            links = [re.search(r"/stats/team/(\d+)", href) for href in row["links"]]
            ids = [match.group(1) for match in links if match]
            if not ids:
                continue
            values = [ids[0]]
            for label in aliases:
                index = headers.index(label)
                if index >= len(row["cells"]):
                    raise ValueError("NBA HTML table is missing a required cell")
                value = row["cells"][index]
                values.append(value if label == "TEAM" else float(value.replace(",", "")))
            rows.append(values)
        return {
            "resultSets": [
                {
                    "name": "LeagueDashTeamStats",
                    "headers": ["TEAM_ID", *aliases.values()],
                    "rowSet": rows,
                }
            ]
        }
    raise ValueError("NBA webpage did not contain a rendered Traditional team table")


def roster_from_html(html, team_id):
    reader = TableReader()
    reader.feed(html)
    rows = {}
    for table in reader.tables:
        if not table:
            continue
        headers = [value.upper() for value in table[0]["cells"]]
        if "PLAYER" not in headers or "SEASONS WITH TEAM" in headers:
            continue
        for row in table[1:]:
            ids = [re.search(r"/player/(\d+)", link) for link in row["links"]]
            player_ids = [match.group(1) for match in ids if match]
            if not player_ids:
                continue
            player_index = headers.index("PLAYER")
            if player_index >= len(row["cells"]):
                raise ValueError("NBA roster row has no player name")
            name = row["cells"][player_index]
            position = ""
            for label in ("POS", "POSITION"):
                if label in headers and headers.index(label) < len(row["cells"]):
                    position = row["cells"][headers.index(label)]
            jersey = row["cells"][headers.index("#")] if "#" in headers else ""
            rows[player_ids[0]] = [str(team_id), player_ids[0], name, position, jersey]
        if rows:
            break
    if not rows:
        raise ValueError("NBA team page did not contain a rendered roster table")
    return {
        "resultSets": [
            {
                "name": "CommonTeamRoster",
                "headers": ["TeamID", "PLAYER_ID", "PLAYER", "POSITION", "NUM"],
                "rowSet": list(rows.values()),
            }
        ]
    }
