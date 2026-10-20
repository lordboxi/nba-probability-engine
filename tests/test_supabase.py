import io
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from nbaprob.data.journal import history, save_forecast
from nbaprob.data.snapshots import latest_snapshot, save_snapshot
from nbaprob.data.supabase_store import StorageError, SupabaseStore, remote_store


def test_server_key_headers_and_workspace_cannot_be_overridden(monkeypatch):
    requests = []

    def send(request, timeout):
        requests.append(request)
        return io.BytesIO(b"[]")

    monkeypatch.setattr("nbaprob.data.supabase_store.urlopen", send)
    store = SupabaseStore("https://fixture.supabase.co", "sb_secret_fixture", "owner")
    store.request("nba_outcomes", row={"workspace": "attacker", "game_id": "a"})
    assert json.loads(requests[0].data)["workspace"] == "owner"
    assert requests[0].get_header("Apikey") == "sb_secret_fixture"
    assert requests[0].get_header("Authorization") is None
    assert "sb_secret_" not in requests[0].full_url
    store.request("nba_forecasts")
    assert parse_qs(urlsplit(requests[1].full_url).query)["workspace"] == ["eq.owner"]


def test_connection_failure_does_not_leak_or_fall_back(config, monkeypatch):
    monkeypatch.setenv("NBA_SUPABASE_URL", "https://fixture.supabase.co")
    monkeypatch.setenv("NBA_SUPABASE_SECRET_KEY", "sb_secret_fixture")

    def fail(*args, **kwargs):
        raise OSError("network problem with sb_secret_fixture")

    monkeypatch.setattr("nbaprob.data.supabase_store.urlopen", fail)
    with pytest.raises(StorageError) as error:
        history(config)
    assert "sb_secret_fixture" not in str(error.value)
    assert (
        not __import__("pathlib")
        .Path(config["data"]["database"])
        .with_name("prediction_journal.sqlite")
        .exists()
    )
    monkeypatch.delenv("NBA_SUPABASE_SECRET_KEY")
    with pytest.raises(StorageError, match="secret key"):
        remote_store(config)


def test_remote_history_paginates_even_with_low_server_row_cap(monkeypatch):
    offsets = []

    def read(self, table, *, query=None, row=None):
        offsets.append(query["offset"])
        return [{"n": n} for n in range(query["offset"], min(query["offset"] + 2, 5))]

    monkeypatch.setattr(SupabaseStore, "request", read)
    rows = SupabaseStore("", "", "owner").rows("nba_forecasts", "as_of,identity")
    assert [row["n"] for row in rows] == list(range(5))
    assert offsets == [0, 2, 4, 5]


def test_remote_snapshot_roundtrip_checks_hash_and_cutoff(config, monkeypatch):
    saved = []

    def request(self, table, *, query=None, row=None):
        if row is not None:
            saved.append(row)
            return []
        assert query["observed"] == "lte.2026-10-20T00:00:00+00:00"
        return saved[-1:]

    monkeypatch.setattr(SupabaseStore, "request", request)
    config["_supabase"] = {"url": "https://fixture.supabase.co", "secret_key": "sb_secret_fixture"}
    document = {
        "resource": "players",
        "season": "2026-27",
        "season_type": "Preseason",
        "retrieved_at": "2026-10-19T00:00:00Z",
        "data": [{"player_id": "99"}],
    }
    result = save_snapshot(document, config)
    assert result["path"] is None
    loaded = latest_snapshot(config, "players", "2026-27", "2026-10-20T00:00:00Z", "Preseason")
    assert loaded["identity"] == result["identity"]
    saved[-1]["payload"] += " "
    with pytest.raises(ValueError, match="hash mismatch"):
        latest_snapshot(config, "players", "2026-27", "2026-10-20T00:00:00Z", "Preseason")


def test_forecast_issue_time_is_generated_by_database(config, monkeypatch):
    from types import SimpleNamespace

    captured = []
    monkeypatch.setattr(
        SupabaseStore, "request", lambda self, table, **kwargs: captured.append(kwargs) or []
    )
    config["_supabase"] = {"url": "https://fixture.supabase.co", "secret_key": "sb_secret_fixture"}
    game = SimpleNamespace(game_id="g", home_team="H", away_team="A", date="2026-10-21T00:00:00Z")
    save_forecast({"game_id": "g", "as_of": "2026-10-20T00:00:00Z"}, game, config)
    assert "issued_at" not in captured[0]["row"]
    assert captured[0]["query"]["on_conflict"] == "workspace,identity"


def test_explicit_migration_preserves_old_issue_times_and_score_revisions(config, monkeypatch):
    from types import SimpleNamespace

    from nbaprob.data.journal import record_outcome
    from nbaprob.data.migrate_supabase import migrate_local

    document = {
        "resource": "players",
        "season": "2019-20",
        "season_type": "Regular Season",
        "retrieved_at": "2020-01-01T00:00:00Z",
        "data": [{"player_id": "99"}],
    }
    save_snapshot(document, config)
    game = SimpleNamespace(game_id="g", home_team="H", away_team="A", date="2020-01-02T00:00:00Z")
    save_forecast({"game_id": "g", "as_of": "2020-01-01T00:00:00Z"}, game, config)
    record_outcome(config, "g", 100, 99, "2020-01-03T00:00:00Z")
    record_outcome(config, "g", 101, 99, "2020-01-04T00:00:00Z")
    forecasts, _ = history(config)
    captured = []
    monkeypatch.setenv("NBA_SUPABASE_URL", "https://fixture.supabase.co")
    monkeypatch.setenv("NBA_SUPABASE_SECRET_KEY", "sb_secret_fixture")
    monkeypatch.setattr(
        SupabaseStore,
        "request",
        lambda self, table, **kwargs: captured.append((table, kwargs["row"])) or [],
    )
    actual = migrate_local(config)
    assert actual["submitted"] == {"snapshots": 1, "forecasts": 1, "outcomes": 2}
    transferred = next(row for table, row in captured if table == "nba_forecasts")
    assert transferred["issued_at"] == forecasts[0]["issued_at"]
    assert len([row for table, row in captured if table == "nba_outcomes"]) == 2


def test_snapshot_session_cache_preserves_cutoffs_scope_and_expiry(monkeypatch):
    calls, clock, cache = [], [100.0], {}

    def send(request, timeout):
        calls.append(request)
        cutoff = parse_qs(urlsplit(request.full_url).query)["observed"][0]
        return io.BytesIO(json.dumps([{"cutoff": cutoff}]).encode())

    monkeypatch.setattr("nbaprob.data.supabase_store.urlopen", send)
    monkeypatch.setattr("nbaprob.data.supabase_store.monotonic", lambda: clock[0])
    store = SupabaseStore("https://fixture.supabase.co", "sb_secret_fixture", "owner", cache)
    query = {"limit": 1, "observed": "lte.2026-10-20T00:00:00Z"}
    first = store.request("nba_snapshots", query=query)
    first[0]["cutoff"] = "mutated by caller"
    assert store.request("nba_snapshots", query=query)[0]["cutoff"] == query["observed"]
    assert len(calls) == 1
    earlier = {**query, "observed": "lte.2026-10-19T00:00:00Z"}
    assert store.request("nba_snapshots", query=earlier)[0]["cutoff"] == earlier["observed"]
    assert len(calls) == 2  # Earlier forecasts must not reuse later data.
    for url, key, workspace in (
        (store.url, store.key, "other-owner"),
        (store.url, "sb_secret_other", store.workspace),
        ("https://other.supabase.co", store.key, store.workspace),
    ):
        SupabaseStore(url, key, workspace, cache).request("nba_snapshots", query=query)
    assert len(calls) == 5
    assert "sb_secret_" not in repr(cache)
    clock[0] += 61
    store.request("nba_snapshots", query=query)
    assert len(calls) == 6
    cache.clear()  # Same action as the UI's explicit refresh.
    store.request("nba_snapshots", query=query)
    assert len(calls) == 7
    for offset in range(100):
        store.request("nba_snapshots", query={**query, "offset": offset})
    assert len(cache) <= 64


def test_snapshot_cache_invalidates_misses_on_write_and_retries_errors(monkeypatch):
    cache, calls, fail = {}, [], [False]

    def send(request, timeout):
        calls.append(request)
        if fail[0]:
            raise TimeoutError()
        return io.BytesIO(b"[]")

    monkeypatch.setattr("nbaprob.data.supabase_store.urlopen", send)
    store = SupabaseStore("https://fixture.supabase.co", "sb_secret_fixture", "owner", cache)
    query = {"limit": 1, "observed": "lte.2026-10-20T00:00:00Z"}
    assert store.request("nba_snapshots", query=query) == []
    store.request("nba_snapshots", query=query)
    assert len(calls) == 1
    store.request("nba_snapshots", row={"identity": "new-snapshot"})
    store.request("nba_snapshots", query=query)
    assert len(calls) == 3
    cache.clear()
    fail[0] = True
    for _ in range(2):
        with pytest.raises(StorageError):
            store.request("nba_snapshots", query=query)
    assert len(calls) == 5 and not cache
    fail[0] = False
    store.request("nba_snapshots", query=query)
    # Journal reads are fresh, even with a populated snapshot cache.
    store.request("nba_forecasts", query={"limit": 1})
    store.request("nba_forecasts", query={"limit": 1})
    assert len(calls) == 8
