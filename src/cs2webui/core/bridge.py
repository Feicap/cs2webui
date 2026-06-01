"""Stable filesystem contract shared with the optional CS2 bridge plugin."""

from pathlib import Path
import time

BRIDGE_STATE = (
    "game/csgo/addons/counterstrikesharp/plugins/"
    "CS2WebUI.Bridge/state/players.json"
)
MATCH_MARKER = (
    "game/csgo/addons/counterstrikesharp/plugins/"
    "CS2WebUI.Bridge/state/match-ended.json"
)
BRIDGE_STALE_SECONDS = 90


def bridge_snapshot_status(server_dir: str | Path) -> str:
    try:
        modified_at = (Path(server_dir) / BRIDGE_STATE).stat().st_mtime
    except OSError:
        return "unavailable"
    return "stale" if time.time() - modified_at > BRIDGE_STALE_SECONDS else "available"
