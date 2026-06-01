"""Stable bridge filesystem contract tests."""

from pathlib import Path
import os
import time

from cs2webui.core.bridge import BRIDGE_STATE, bridge_snapshot_status


def test_bridge_snapshot_status_reports_stale_file(tmp_path: Path) -> None:
    snapshot = tmp_path / BRIDGE_STATE
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("[]")
    stale_at = time.time() - 120
    os.utime(snapshot, (stale_at, stale_at))

    assert bridge_snapshot_status(tmp_path) == "stale"


def test_bridge_snapshot_status_reports_missing_file(tmp_path: Path) -> None:
    assert bridge_snapshot_status(tmp_path) == "unavailable"
