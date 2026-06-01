"""Append-only audit log for administrative actions."""

from dataclasses import asdict, dataclass
from pathlib import Path
import sqlite3


@dataclass(frozen=True, slots=True)
class AuditEntry:
    id: int
    action: str
    details: str
    created_at: str

    def as_dict(self) -> dict[str, str | int]:
        return asdict(self)


class AuditStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def record(self, action: str, details: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO audit_log (action, details) VALUES (?, ?)",
                (action, details),
            )

    def recent(self, limit: int = 100) -> list[AuditEntry]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, action, details, created_at
                FROM audit_log ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [AuditEntry(**dict(row)) for row in rows]
