"""Persistent first-run setup state."""

from dataclasses import asdict, dataclass
from pathlib import Path
import sqlite3

from argon2 import PasswordHasher

_hasher = PasswordHasher()


@dataclass(frozen=True, slots=True)
class SetupState:
    language: str | None
    access_mode: str | None
    access_domain: str | None
    webui_port: int | None
    admin_created: bool

    @property
    def completed(self) -> bool:
        return bool(
            self.language
            and self.access_mode
            and self.webui_port
            and self.admin_created
        )

    def as_dict(self) -> dict[str, str | int | bool | None]:
        return {**asdict(self), "completed": self.completed}


class SetupStore:
    """SQLite store used before the full application database is introduced."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS setup_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def state(self) -> SetupState:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT key, value FROM setup_settings"
            ).fetchall()
            values = {row["key"]: row["value"] for row in rows}
            admin_created = (
                connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
            )
        port = values.get("webui_port")
        return SetupState(
            language=values.get("language"),
            access_mode=values.get("access_mode"),
            access_domain=values.get("access_domain"),
            webui_port=int(port) if port else None,
            admin_created=admin_created,
        )

    def set_value(self, key: str, value: str) -> SetupState:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO setup_settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            connection.execute(
                "INSERT INTO audit_log (action, details) VALUES (?, ?)",
                ("setup.setting.updated", key),
            )
        return self.state()

    def create_admin(self, username: str, password: str) -> SetupState:
        password_hash = _hasher.hash(password)
        with self._connect() as connection:
            if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
                raise ValueError("The first administrator already exists")
            connection.execute(
                """
                INSERT INTO users (username, password_hash, role)
                VALUES (?, ?, 'admin')
                """,
                (username, password_hash),
            )
            connection.execute(
                "INSERT INTO audit_log (action, details) VALUES (?, ?)",
                ("setup.admin.created", username),
            )
        return self.state()
