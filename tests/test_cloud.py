import json
from pathlib import Path

import pytest
import yaml

from nbaprob.data.bootstrap import bootstrap_snapshots
from nbaprob.data.snapshots import latest_snapshot

ROOT = Path(__file__).parents[1]
SEEDS = ROOT / "deployment/seed_snapshots"


def test_cloud_bootstrap_is_idempotent_and_preserves_observation_time(config):
    local_data = Path(config["data"]["database"])
    local_data.write_bytes(b"owner data must not be changed")
    first = bootstrap_snapshots(config, SEEDS)
    assert len(first) == 4
    assert bootstrap_snapshots(config, SEEDS) == first
    assert local_data.read_bytes() == b"owner data must not be changed"
    document = json.loads((SEEDS / "teams-preseason.json").read_text(encoding="utf-8"))
    at = document["retrieved_at"]
    loaded = latest_snapshot(config, "teams", "2026-27", at, "Preseason")
    assert loaded["retrieved_at"] == at
    assert loaded["origin_snapshot_identity"] == document["origin_snapshot_identity"]
    assert latest_snapshot(config, "teams", "2026-27", "2026-10-18T00:00:00Z", "Preseason") is None
    assert "raw_response" not in loaded


def test_cloud_seed_bundle_contains_only_nba_statistics(config, tmp_path):
    for path in SEEDS.glob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["provider"] == "NBA.com"
        assert document["resource"] in {"teams", "roster", "players"}
        assert "house_quote" not in document
        assert "roster_selection" not in document
    (tmp_path / "private.json").write_text('{"resource":"journal"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Bundled data"):
        bootstrap_snapshots(config, tmp_path)


def test_cloud_entrypoint_starts_with_real_seed_data(config, tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setenv("NBA_CONFIG", str(cfg))
    # The entrypoint sets this flag; monkeypatch restores it for subsequent tests.
    monkeypatch.setenv("NBA_CLOUD_MODE", "0")
    app = AppTest.from_file(str(ROOT / "deployment/streamlit_app.py"))
    app.run(timeout=30)
    assert not app.exception
    assert not app.error
    assert any("Cloud:" in item.value for item in app.warning)
    assert (
        len([item for item in app.selectbox if item.key and item.key.startswith("starter_")]) == 10
    )
    assert (
        next(item for item in app.selectbox if item.label == "แหล่งข้อมูลคู่แข่งขัน").value == "ตาราง NBA"
    )
    assert (
        latest_snapshot(config, "teams", "2026-27", "2026-10-20T23:59:59Z", "Preseason") is not None
    )
