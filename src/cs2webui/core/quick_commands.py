"""Persist administrator-defined reusable RCON commands."""

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import re
import sqlite3
from uuid import uuid4

_parameter = re.compile(r"\{([A-Za-z][A-Za-z0-9_-]{0,31})\}")


@dataclass(frozen=True, slots=True)
class QuickCommand:
    id: str
    label: str
    command: str
    parameters: tuple[dict[str, str], ...]
    custom: bool = True

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class QuickCommandStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS quick_commands (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    command TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def list(self) -> list[QuickCommand]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, label, command, parameters_json
                FROM quick_commands ORDER BY created_at, label
                """
            ).fetchall()
        return [
            QuickCommand(
                id=row["id"],
                label=row["label"],
                command=row["command"],
                parameters=tuple(json.loads(row["parameters_json"])),
            )
            for row in rows
        ]

    def create(self, label: str, command: str) -> QuickCommand:
        names = dict.fromkeys(_parameter.findall(command))
        quick_command = QuickCommand(
            id=str(uuid4()),
            label=label,
            command=command,
            parameters=tuple(
                {"name": name, "type": "string", "default": ""} for name in names
            ),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO quick_commands (id, label, command, parameters_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    quick_command.id,
                    quick_command.label,
                    quick_command.command,
                    json.dumps(quick_command.parameters),
                ),
            )
        return quick_command

    def delete(self, quick_command_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM quick_commands WHERE id = ?", (quick_command_id,)
            )
        if cursor.rowcount == 0:
            raise ValueError("Quick command not found")
