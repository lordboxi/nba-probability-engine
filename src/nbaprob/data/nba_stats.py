"""NBA Stats table/roster adapter. No API key; no retries or access-control workarounds."""

import json
import re
import time
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from nbaprob.data.nba_html import roster_from_html, teams_from_html

SEASON_TYPES = {
    "Preseason": "Pre Season",
    "Regular Season": "Regular Season",
    "Playoffs": "Playoffs",
}


def season_valid(season):
    if not re.fullmatch(r"\d{4}-\d{2}", season) or int(season[-2:]) != (int(season[:4]) + 1) % 100:
        raise ValueError("Season must look like 2026-27")


def result_frame(payload, name):
    if not isinstance(payload, dict):
        raise ValueError("NBA response must be a JSON object")
    sets = payload.get("resultSets", payload.get("resultSet", []))
    if isinstance(sets, dict):
        sets = [sets]
    if not isinstance(sets, list):
        raise ValueError("NBA resultSets must be an array")
    for result in sets:
        if result.get("name") == name:
            headers, rows = result.get("headers", []), result.get("rowSet", [])
            if not headers or len(headers) != len(set(headers)):
                raise ValueError("Missing or duplicate NBA response headers")
            if any(len(row) != len(headers) for row in rows):
                raise ValueError("NBA response row width does not match headers")
            return pd.DataFrame(rows, columns=headers)
    raise ValueError(f"NBA response did not include {name}")


def normalize_teams(payload):
    frame = result_frame(payload, "LeagueDashTeamStats")
    columns = {
        "TEAM_ID": "team_id",
        "TEAM_NAME": "team",
        "GP": "gp",
        "W": "wins",
        "L": "losses",
        "W_PCT": "win_pct",
        "MIN": "minutes",
        "PTS": "points",
        "PLUS_MINUS": "plus_minus",
        "FGA": "fga",
        "FTA": "fta",
        "OREB": "oreb",
        "TOV": "turnovers",
    }
    if not set(columns).issubset(frame.columns):
        raise ValueError(f"NBA team table requires {sorted(columns)}")
    frame = frame[list(columns)].rename(columns=columns)
    if frame[["team_id", "team"]].isna().any().any():
        raise ValueError("NBA team IDs and names must be present")
    frame["team_id"] = frame.team_id.astype(str)
    if frame.team_id.duplicated().any() or frame[["team_id", "team"]].isna().any().any():
        raise ValueError("NBA team IDs must be unique and names nonmissing")
    for column in set(frame.columns) - {"team_id", "team"}:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if not np.isfinite(frame[column]).all():
            raise ValueError(f"Invalid NBA team number: {column}")
        if column != "plus_minus" and (frame[column] < 0).any():
            raise ValueError(f"Negative NBA team number: {column}")
    if (frame.win_pct > 1).any() or ((frame.gp > 0) & (frame.minutes <= 0)).any():
        raise ValueError("Invalid NBA win percentage or minutes")
    return frame.to_dict(orient="records")


def normalize_roster(payload, team_id):
    frame = result_frame(payload, "CommonTeamRoster")
    if not {"PLAYER_ID", "PLAYER", "POSITION"}.issubset(frame.columns):
        raise ValueError("NBA roster requires PLAYER_ID, PLAYER and POSITION")
    if "TeamID" in frame and not frame.TeamID.astype(str).eq(str(team_id)).all():
        raise ValueError("NBA roster response belongs to a different team")
    if frame[["PLAYER_ID", "PLAYER"]].isna().any().any() or frame.PLAYER_ID.duplicated().any():
        raise ValueError("NBA roster has missing or duplicate player IDs")
    return [
        {
            "player_id": str(row["PLAYER_ID"]),
            "name": str(row["PLAYER"]),
            "team_id": str(team_id),
            "position": str(row["POSITION"] or ""),
            "jersey": str(row["NUM"]) if row.get("NUM") is not None else "",
        }
        for row in frame.to_dict(orient="records")
    ]


class NBAStatsAdapter:
    def __init__(self, config, transport=None):
        self.config = config
        self.transport = transport or self._get
        self.custom_transport = transport is not None
        self.last_request = None

    def _get(self, url):
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Referer": "https://www.nba.com/",
                "User-Agent": "NBAProbabilityEngine/0.2.0",
            },
        )
        try:
            with urlopen(request, timeout=self.config["feed"]["timeout_seconds"]) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError) as error:
            raise ValueError(
                "NBA Stats could not be reached or denied the request. "
                "No retry/proxy bypass was attempted; use a saved JSON response instead."
            ) from error

    def _html(self, url):
        request = Request(url, headers={"User-Agent": "NBAProbabilityEngine/0.2.0"})
        try:
            with urlopen(request, timeout=self.config["feed"]["timeout_seconds"]) as response:
                return response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError) as error:
            raise ValueError(
                "NBA team webpage is unavailable; use a saved roster response/CSV"
            ) from error

    def fetch(self, resource, season, season_type="Preseason", team_id=None, imported_payload=None):
        season_valid(season)
        if resource == "teams":
            if season_type not in SEASON_TYPES:
                raise ValueError("Unknown season type")
            parameters = dict.fromkeys(
                (
                    "Conference",
                    "DateFrom",
                    "DateTo",
                    "Division",
                    "GameScope",
                    "GameSegment",
                    "Location",
                    "Outcome",
                    "PORound",
                    "PlayerExperience",
                    "PlayerPosition",
                    "SeasonSegment",
                    "ShotClockRange",
                    "StarterBench",
                    "TeamID",
                    "VsConference",
                    "VsDivision",
                    "TwoWay",
                ),
                "",
            )
            parameters.update(
                Season=season,
                SeasonType=SEASON_TYPES[season_type],
                MeasureType="Base",
                PerMode="PerGame",
                LeagueID="00",
                LastNGames=0,
                Month=0,
                OpponentTeamID=0,
                PaceAdjust="N",
                PlusMinus="N",
                Rank="N",
                Period=0,
            )
            endpoint = "leaguedashteamstats"
        elif resource == "roster":
            if team_id is None or not str(team_id).isdigit():
                raise ValueError("NBA team_id must be numeric")
            endpoint = "commonteamroster"
            parameters = {"Season": season, "TeamID": str(team_id), "LeagueID": "00"}
        else:
            raise ValueError("NBA resource must be teams or roster")
        url = self.config["feed"]["base_url"] + "/" + endpoint + "?" + urlencode(parameters)
        current = datetime.now(UTC)
        current_year = current.year - (current.month < 7)
        current_season = f"{current_year}-{(current_year + 1) % 100:02d}"
        html_roster = (
            resource == "roster" and season == current_season and not self.custom_transport
        )
        if html_roster and imported_payload is None:
            url = f"https://www.nba.com/team/{team_id}"
        if imported_payload is None:
            interval = self.config["feed"]["min_request_interval_seconds"]
            if self.last_request is not None and time.monotonic() - self.last_request < interval:
                raise ValueError("Please wait before issuing another NBA request")
            self.last_request = time.monotonic()
            payload = self._html(url) if html_roster else self.transport(url)
        else:
            payload = imported_payload
        raw_response = payload
        acquisition = "saved_response" if imported_payload is not None else "http"
        if isinstance(payload, dict) and "_capture" in payload:
            capture = payload["_capture"]
            if capture.get("season") != season or capture.get("season_type") != season_type:
                raise ValueError("Captured NBA webpage season/type does not match import options")
            if capture.get("per_mode") != "PerGame":
                raise ValueError("Captured team table must be PerGame")
            url = "https://www.nba.com/stats/teams/traditional"
            acquisition = "visible_browser_table_capture"
        if isinstance(payload, str):
            payload = (
                teams_from_html(payload, season, SEASON_TYPES[season_type])
                if resource == "teams"
                else roster_from_html(payload, team_id)
            )
        data = (
            normalize_teams(payload) if resource == "teams" else normalize_roster(payload, team_id)
        )
        if not data:
            raise ValueError("NBA response is empty for the selected season/type/team")
        return {
            "provider": "NBA.com",
            "resource": resource,
            "season": season,
            "season_type": season_type if resource == "teams" else "",
            "team_id": str(team_id) if resource == "roster" else "",
            "retrieved_at": datetime.now(UTC).isoformat(),
            "source_url": url,
            "imported": imported_payload is not None,
            "acquisition_method": acquisition,
            "terms_url": self.config["feed"]["terms_url"],
            "terms_reviewed_on": self.config["feed"]["terms_reviewed_on"],
            "data": data,
            "raw_response": raw_response,
        }
