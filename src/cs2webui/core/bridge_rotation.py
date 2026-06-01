"""Consume optional bridge match markers and advance visual rotations."""

from datetime import datetime
import json
from pathlib import Path
from typing import Protocol

from cs2webui.core.bridge import MATCH_MARKER
from cs2webui.core.instances import InstanceStore
from cs2webui.host.rcon import RconClient, RconError


class RotationCommands(Protocol):
    def peek_next_command(self, instance_id: str) -> str | None:
        """Return the next command without consuming it."""

    def next_command(self, instance_id: str) -> str | None:
        """Consume and return the next command."""

    def mark_current_command(self, instance_id: str, command: str) -> None:
        """Remember the map command applied by the panel."""


class BridgeRotationRunner:
    """Advance rotations once for each bridge match-end marker."""

    def __init__(
        self,
        instances: InstanceStore,
        rotations: RotationCommands,
        rcon: RconClient,
        game_host: str,
    ) -> None:
        self._instances = instances
        self._rotations = rotations
        self._rcon = rcon
        self._game_host = game_host
        self._processed: dict[str, datetime] = {}

    def run(self) -> list[dict[str, str]]:
        results = []
        for instance in self._instances.list():
            marker = Path(instance.server_dir) / MATCH_MARKER
            if not marker.is_file():
                continue
            try:
                payload = json.loads(marker.read_text(encoding="utf-8"))
                finished_at = datetime.fromisoformat(payload["finishedAt"])
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                results.append({"instance_id": instance.id, "status": "invalid_marker"})
                marker.unlink(missing_ok=True)
                continue
            if self._processed.get(instance.id) == finished_at:
                continue
            command = self._rotations.peek_next_command(instance.id)
            if not command:
                results.append({"instance_id": instance.id, "status": "empty_rotation"})
                self._processed[instance.id] = finished_at
                marker.unlink(missing_ok=True)
                continue
            try:
                self._rcon.execute(
                    self._game_host,
                    instance.game_port,
                    self._instances.rcon_password(instance.id),
                    command,
                )
            except (RconError, OSError):
                results.append({"instance_id": instance.id, "status": "rcon_failed"})
                continue
            self._rotations.next_command(instance.id)
            self._rotations.mark_current_command(instance.id, command)
            self._processed[instance.id] = finished_at
            marker.unlink(missing_ok=True)
            results.append({"instance_id": instance.id, "status": "advanced"})
        return results
