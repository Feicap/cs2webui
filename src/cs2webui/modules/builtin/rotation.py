"""Optional map rotation module with queue and history."""

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import re
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from cs2webui.api.auth import require_roles
from cs2webui.core.auth import User
from cs2webui.host.rcon import RconError
from cs2webui.modules.base import ModuleManifest


@dataclass(frozen=True, slots=True)
class RotationMap:
    kind: str
    identifier: str
    title: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

    def command(self) -> str:
        if self.kind == "workshop":
            return f"host_workshop_map {self.identifier}"
        return f"changelevel {self.identifier}"


class RotationMapPayload(BaseModel):
    kind: Literal["standard", "workshop"]
    identifier: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_identifier(self) -> "RotationMapPayload":
        pattern = r"^[0-9]{1,20}$" if self.kind == "workshop" else r"^[A-Za-z0-9_/-]+$"
        if not re.fullmatch(pattern, self.identifier):
            raise ValueError("Invalid map identifier")
        return self


class RotationPayload(BaseModel):
    maps: list[RotationMapPayload] = Field(max_length=512)


class RotationStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS rotation_cycles (
                    instance_id TEXT PRIMARY KEY,
                    cycle_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rotation_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instance_id TEXT NOT NULL,
                    map_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rotation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instance_id TEXT NOT NULL,
                    cycle_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS rotation_runtime (
                    instance_id TEXT PRIMARY KEY,
                    expected_current_command TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def cycle(self, instance_id: str) -> list[RotationMap]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT cycle_json FROM rotation_cycles WHERE instance_id = ?",
                (instance_id,),
            ).fetchone()
        return self._decode(row["cycle_json"]) if row else []

    def replace_cycle(self, instance_id: str, maps: list[RotationMap]) -> None:
        encoded = self._encode(maps)
        with self._connect() as connection:
            current = connection.execute(
                "SELECT cycle_json FROM rotation_cycles WHERE instance_id = ?",
                (instance_id,),
            ).fetchone()
            if current:
                connection.execute(
                    """
                    INSERT INTO rotation_history (instance_id, cycle_json)
                    VALUES (?, ?)
                    """,
                    (instance_id, current["cycle_json"]),
                )
            connection.execute(
                """
                INSERT INTO rotation_cycles (instance_id, cycle_json) VALUES (?, ?)
                ON CONFLICT(instance_id) DO UPDATE SET cycle_json = excluded.cycle_json
                """,
                (instance_id, encoded),
            )

    def queue(self, instance_id: str) -> list[RotationMap]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT map_json FROM rotation_queue
                WHERE instance_id = ? ORDER BY id
                """,
                (instance_id,),
            ).fetchall()
        return [self._decode_one(row["map_json"]) for row in rows]

    def enqueue(self, instance_id: str, map_item: RotationMap) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO rotation_queue (instance_id, map_json) VALUES (?, ?)",
                (instance_id, json.dumps(map_item.as_dict())),
            )

    def next_command(self, instance_id: str) -> str | None:
        with self._connect() as connection:
            queued = connection.execute(
                """
                SELECT id, map_json FROM rotation_queue
                WHERE instance_id = ? ORDER BY id LIMIT 1
                """,
                (instance_id,),
            ).fetchone()
            if queued:
                connection.execute(
                    "DELETE FROM rotation_queue WHERE id = ?", (queued["id"],)
                )
                return self._decode_one(queued["map_json"]).command()
        cycle = self.cycle(instance_id)
        if not cycle:
            return None
        first = cycle.pop(0)
        cycle.append(first)
        with self._connect() as connection:
            connection.execute(
                "UPDATE rotation_cycles SET cycle_json = ? WHERE instance_id = ?",
                (self._encode(cycle), instance_id),
            )
        return first.command()

    def peek_next_command(self, instance_id: str) -> str | None:
        queue = self.queue(instance_id)
        if queue:
            return queue[0].command()
        cycle = self.cycle(instance_id)
        return cycle[0].command() if cycle else None

    def mark_current_command(self, instance_id: str, command: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO rotation_runtime (instance_id, expected_current_command)
                VALUES (?, ?)
                ON CONFLICT(instance_id) DO UPDATE
                SET expected_current_command = excluded.expected_current_command
                """,
                (instance_id, command),
            )

    def expected_current_command(self, instance_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT expected_current_command FROM rotation_runtime
                WHERE instance_id = ?
                """,
                (instance_id,),
            ).fetchone()
        return row["expected_current_command"] if row else None

    def history(self, instance_id: str) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, cycle_json, created_at FROM rotation_history
                WHERE instance_id = ? ORDER BY id DESC LIMIT 50
                """,
                (instance_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "maps": [item.as_dict() for item in self._decode(row["cycle_json"])],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def restore(self, instance_id: str, history_id: int) -> list[RotationMap]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT cycle_json FROM rotation_history
                WHERE instance_id = ? AND id = ?
                """,
                (instance_id, history_id),
            ).fetchone()
        if not row:
            raise ValueError("Rotation history entry not found")
        maps = self._decode(row["cycle_json"])
        self.replace_cycle(instance_id, maps)
        return maps

    @staticmethod
    def _encode(maps: list[RotationMap]) -> str:
        return json.dumps([item.as_dict() for item in maps])

    @staticmethod
    def _decode(value: str) -> list[RotationMap]:
        return [RotationMap(**item) for item in json.loads(value)]

    @staticmethod
    def _decode_one(value: str) -> RotationMap:
        return RotationMap(**json.loads(value))


class RotationModule:
    manifest = ModuleManifest(
        id="visual-map-rotation",
        name="Visual Map Rotation",
        version="0.1.0",
        description="Optional rotation cards, queue, and history.",
        capabilities=("rotation.queue", "rotation.history"),
    )

    def __init__(self, database_path: Path) -> None:
        self._store = RotationStore(database_path)

    @property
    def store(self) -> RotationStore:
        return self._store

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/api/rotation", tags=["rotation"])
        readable = require_roles("admin", "operator", "viewer")
        writable = require_roles("admin", "operator")

        def require_instance(request: Request, instance_id: str):
            instance = request.app.state.instance_store.get(instance_id)
            if not instance:
                raise HTTPException(status_code=404, detail="Instance not found")
            return instance

        @router.get("/{instance_id}")
        async def state(
            instance_id: str,
            request: Request,
            _user: User = Depends(readable),
        ) -> dict[str, object]:
            require_instance(request, instance_id)
            return {
                "cycle": [item.as_dict() for item in self._store.cycle(instance_id)],
                "queue": [item.as_dict() for item in self._store.queue(instance_id)],
                "expected_current_command": self._store.expected_current_command(
                    instance_id
                ),
            }

        @router.put("/{instance_id}")
        async def replace(
            instance_id: str,
            payload: RotationPayload,
            request: Request,
            _user: User = Depends(writable),
        ) -> dict[str, object]:
            require_instance(request, instance_id)
            self._store.replace_cycle(
                instance_id, [RotationMap(**item.model_dump()) for item in payload.maps]
            )
            return {"cycle": [item.model_dump() for item in payload.maps]}

        @router.post("/{instance_id}/queue", status_code=201)
        async def enqueue(
            instance_id: str,
            payload: RotationMapPayload,
            request: Request,
            _user: User = Depends(writable),
        ) -> dict[str, str]:
            require_instance(request, instance_id)
            self._store.enqueue(instance_id, RotationMap(**payload.model_dump()))
            return {"status": "queued"}

        @router.post("/{instance_id}/next")
        async def next_map(
            instance_id: str,
            request: Request,
            _user: User = Depends(writable),
        ) -> dict[str, str]:
            command = self._store.peek_next_command(instance_id)
            if not command:
                raise HTTPException(status_code=409, detail="Rotation is empty")
            instance = require_instance(request, instance_id)
            try:
                request.app.state.rcon_client.execute(
                    request.app.state.settings.game_host,
                    instance.game_port,
                    request.app.state.instance_store.rcon_password(instance.id),
                    command,
                )
            except (RconError, OSError) as error:
                raise HTTPException(status_code=503, detail="RCON is unavailable") from error
            self._store.next_command(instance_id)
            self._store.mark_current_command(instance_id, command)
            return {"command": command}

        @router.get("/{instance_id}/history")
        async def history(
            instance_id: str,
            request: Request,
            _user: User = Depends(readable),
        ) -> list[dict[str, object]]:
            require_instance(request, instance_id)
            return self._store.history(instance_id)

        @router.post("/{instance_id}/history/{history_id}/restore")
        async def restore(
            instance_id: str,
            history_id: int,
            request: Request,
            _user: User = Depends(writable),
        ) -> dict[str, object]:
            require_instance(request, instance_id)
            try:
                maps = self._store.restore(instance_id, history_id)
            except ValueError as error:
                raise HTTPException(status_code=404, detail=str(error)) from error
            return {"cycle": [item.as_dict() for item in maps]}

        return router
