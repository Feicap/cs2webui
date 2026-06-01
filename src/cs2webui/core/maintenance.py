"""Persistent maintenance policies for CS2 instances."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3


@dataclass(frozen=True, slots=True)
class MaintenancePolicy:
    instance_id: str
    restart_every_minutes: int | None
    update_before_restart: bool
    defer_while_players_online: bool
    max_defer_minutes: int
    backup_before_update: bool
    notify_before_minutes: int

    def as_dict(self) -> dict[str, str | int | bool | None]:
        return asdict(self)


class MaintenanceStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS maintenance_policies (
                    instance_id TEXT PRIMARY KEY,
                    restart_every_minutes INTEGER,
                    update_before_restart INTEGER NOT NULL DEFAULT 0,
                    defer_while_players_online INTEGER NOT NULL DEFAULT 1,
                    max_defer_minutes INTEGER NOT NULL DEFAULT 120,
                    backup_before_update INTEGER NOT NULL DEFAULT 1,
                    notify_before_minutes INTEGER NOT NULL DEFAULT 10,
                    defer_started_at TEXT,
                    last_run_at TEXT
                );
                """
            )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(maintenance_policies)"
                ).fetchall()
            }
            if "last_run_at" not in columns:
                connection.execute(
                    "ALTER TABLE maintenance_policies ADD COLUMN last_run_at TEXT"
                )
            if "notify_before_minutes" not in columns:
                connection.execute(
                    """
                    ALTER TABLE maintenance_policies
                    ADD COLUMN notify_before_minutes INTEGER NOT NULL DEFAULT 10
                    """
                )
            if "defer_started_at" not in columns:
                connection.execute(
                    "ALTER TABLE maintenance_policies ADD COLUMN defer_started_at TEXT"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def get(self, instance_id: str) -> MaintenancePolicy:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM maintenance_policies WHERE instance_id = ?",
                (instance_id,),
            ).fetchone()
        if row:
            return self._from_row(row)
        return MaintenancePolicy(
            instance_id=instance_id,
            restart_every_minutes=None,
            update_before_restart=False,
            defer_while_players_online=True,
            max_defer_minutes=120,
            backup_before_update=True,
            notify_before_minutes=10,
        )

    def save(self, policy: MaintenancePolicy) -> MaintenancePolicy:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO maintenance_policies (
                    instance_id, restart_every_minutes, update_before_restart,
                    defer_while_players_online, max_defer_minutes,
                    backup_before_update, notify_before_minutes, last_run_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instance_id) DO UPDATE SET
                    restart_every_minutes = excluded.restart_every_minutes,
                    update_before_restart = excluded.update_before_restart,
                    defer_while_players_online = excluded.defer_while_players_online,
                    max_defer_minutes = excluded.max_defer_minutes,
                    backup_before_update = excluded.backup_before_update
                    , notify_before_minutes = excluded.notify_before_minutes
                """,
                (
                    policy.instance_id,
                    policy.restart_every_minutes,
                    policy.update_before_restart,
                    policy.defer_while_players_online,
                    policy.max_defer_minutes,
                    policy.backup_before_update,
                    policy.notify_before_minutes,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return policy

    @staticmethod
    def _from_row(row: sqlite3.Row) -> MaintenancePolicy:
        return MaintenancePolicy(
            instance_id=row["instance_id"],
            restart_every_minutes=row["restart_every_minutes"],
            update_before_restart=bool(row["update_before_restart"]),
            defer_while_players_online=bool(row["defer_while_players_online"]),
            max_defer_minutes=row["max_defer_minutes"],
            backup_before_update=bool(row["backup_before_update"]),
            notify_before_minutes=row["notify_before_minutes"],
        )

    def status(self, instance_id: str) -> dict[str, str | int | bool | None]:
        policy = self.get(instance_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT last_run_at FROM maintenance_policies WHERE instance_id = ?",
                (instance_id,),
            ).fetchone()
        last_run_at = row["last_run_at"] if row else None
        next_run_at = None
        if policy.restart_every_minutes is not None:
            last_run = (
                datetime.fromisoformat(last_run_at)
                if last_run_at
                else datetime.now(UTC)
            )
            next_run_at = (
                last_run + timedelta(minutes=policy.restart_every_minutes)
            ).isoformat()
        warning = bool(
            next_run_at
            and datetime.fromisoformat(next_run_at)
            - timedelta(minutes=policy.notify_before_minutes)
            <= datetime.now(UTC)
        )
        return {
            **policy.as_dict(),
            "last_run_at": last_run_at,
            "next_run_at": next_run_at,
            "warning": warning,
        }

    def due(self) -> list[MaintenancePolicy]:
        now = datetime.now(UTC)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM maintenance_policies
                WHERE restart_every_minutes IS NOT NULL
                """
            ).fetchall()
        policies = []
        for row in rows:
            last_run = (
                datetime.fromisoformat(row["last_run_at"])
                if row["last_run_at"]
                else None
            )
            if not last_run or last_run + timedelta(
                minutes=row["restart_every_minutes"]
            ) <= now:
                policies.append(self._from_row(row))
        return policies

    def mark_run(self, instance_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE maintenance_policies
                SET last_run_at = ?, defer_started_at = NULL
                WHERE instance_id = ?
                """,
                (datetime.now(UTC).isoformat(), instance_id),
            )

    def may_defer(self, instance_id: str, max_defer_minutes: int) -> bool:
        now = datetime.now(UTC)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT defer_started_at FROM maintenance_policies
                WHERE instance_id = ?
                """,
                (instance_id,),
            ).fetchone()
            if not row:
                connection.execute(
                    """
                    INSERT INTO maintenance_policies (
                        instance_id, defer_started_at
                    ) VALUES (?, ?)
                    """,
                    (instance_id, now.isoformat()),
                )
                return max_defer_minutes > 0
            if not row["defer_started_at"]:
                connection.execute(
                    """
                    UPDATE maintenance_policies SET defer_started_at = ?
                    WHERE instance_id = ?
                    """,
                    (now.isoformat(), instance_id),
                )
                return max_defer_minutes > 0
        started_at = datetime.fromisoformat(row["defer_started_at"])
        return started_at + timedelta(minutes=max_defer_minutes) > now
