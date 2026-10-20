"""Server-only Supabase persistence for the private app's shared workspace."""

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class StorageError(ValueError):
    """A safe error message that never includes credentials or response bodies."""


def remote_store(config):
    settings = config.get("_supabase", {})
    url = settings.get("url") or os.environ.get("NBA_SUPABASE_URL", "")
    key = settings.get("secret_key") or os.environ.get("NBA_SUPABASE_SECRET_KEY", "")
    workspace = settings.get("workspace") or os.environ.get("NBA_WORKSPACE_ID", "nba-owner")
    if not url and not key:
        return None
    if not re.fullmatch(r"https://[a-z0-9-]+\.supabase\.co", url.rstrip("/")):
        raise StorageError("Set a valid NBA_SUPABASE_URL for the NBA Supabase project")
    if not key or key.startswith("sb_publishable_"):
        raise StorageError("Supabase requires a server-only secret key in Secrets")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", workspace):
        raise StorageError("Invalid server workspace identifier")
    return SupabaseStore(url.rstrip("/"), key, workspace)


class SupabaseStore:
    def __init__(self, url, key, workspace):
        self.url, self.key, self.workspace = url, key, workspace

    def request(self, table, *, query=None, row=None):
        if table not in {"nba_snapshots", "nba_forecasts", "nba_outcomes"}:
            raise StorageError("Unsupported NBA table")
        parameters = {**(query or {}), "workspace": f"eq.{self.workspace}"}
        headers = {"apikey": self.key, "Accept": "application/json"}
        # Modern secret keys are not JWTs. Legacy service_role JWTs need Bearer too.
        if not self.key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {self.key}"
        body = None
        if row is not None:
            parameters.pop("workspace")
            headers.update(
                {"Content-Type": "application/json", "Prefer": "resolution=ignore-duplicates"}
            )
            body = json.dumps({**row, "workspace": self.workspace}, allow_nan=False).encode()
        request = Request(
            f"{self.url}/rest/v1/{table}?{urlencode(parameters)}",
            data=body,
            headers=headers,
            method="POST" if row is not None else "GET",
        )
        try:
            with urlopen(request, timeout=20) as response:
                data = response.read()
                return json.loads(data) if data else []
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            raise StorageError(
                "Supabase read/write failed. Check project status, migration and server Secrets. "
                "No local fallback was used; please retry after fixing the connection."
            ) from None

    def rows(self, table, order):
        rows, offset = [], 0
        while True:
            page = self.request(table, query={"order": order, "limit": 1000, "offset": offset})
            rows.extend(page)
            # Continue even if the server's configured row cap is below 1000.
            if not page:
                return rows
            offset += len(page)
