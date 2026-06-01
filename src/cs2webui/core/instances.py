"""Persistence and launch preview for isolated CS2 instances."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
import shlex
import sqlite3
from uuid import uuid4

from cs2webui.core.secrets import SecretCipher

_slug_pattern = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class Instance:
    id: str
    name: str
    slug: str
    server_dir: str
    game_port: int
    start_map: str
    preset: str
    install_source: str
    source_path: str | None
    metamod_enabled: bool
    counterstrikesharp_enabled: bool
    bridge_enabled: bool
    status: str

    def as_dict(self) -> dict[str, str | int | bool | None]:
        return asdict(self)


class InstanceStore:
    """SQLite repository for CS2 instance metadata and encrypted secrets."""

    def __init__(
        self,
        database_path: Path,
        instances_dir: Path,
        cipher: SecretCipher,
    ) -> None:
        self._database_path = database_path
        self._instances_dir = instances_dir
        self._cipher = cipher
        self._instances_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS instances (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    server_dir TEXT NOT NULL UNIQUE,
                    game_port INTEGER NOT NULL UNIQUE,
                    start_map TEXT NOT NULL,
                    preset TEXT NOT NULL,
                    install_source TEXT NOT NULL,
                    source_path TEXT,
                    metamod_enabled INTEGER NOT NULL DEFAULT 0,
                    counterstrikesharp_enabled INTEGER NOT NULL DEFAULT 0,
                    bridge_enabled INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    rcon_password TEXT NOT NULL,
                    gslt TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(instances)").fetchall()
            }
            if "source_path" not in columns:
                connection.execute("ALTER TABLE instances ADD COLUMN source_path TEXT")
            if "metamod_enabled" not in columns:
                connection.execute(
                    "ALTER TABLE instances ADD COLUMN metamod_enabled INTEGER NOT NULL DEFAULT 0"
                )
            if "counterstrikesharp_enabled" not in columns:
                connection.execute(
                    "ALTER TABLE instances ADD COLUMN counterstrikesharp_enabled INTEGER NOT NULL DEFAULT 0"
                )

    def list(self) -> list[Instance]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, slug, server_dir, game_port, start_map, preset,
                       install_source, source_path, metamod_enabled,
                       counterstrikesharp_enabled, bridge_enabled, status
                FROM instances ORDER BY created_at, name
                """
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, instance_id: str) -> Instance | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, name, slug, server_dir, game_port, start_map, preset,
                       install_source, source_path, metamod_enabled,
                       counterstrikesharp_enabled, bridge_enabled, status
                FROM instances WHERE id = ?
                """,
                (instance_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def create(
        self,
        *,
        name: str,
        game_port: int,
        start_map: str,
        preset: str,
        install_source: str,
        source_path: str | None,
        metamod_enabled: bool,
        counterstrikesharp_enabled: bool,
        rcon_password: str,
        gslt: str,
        bridge_enabled: bool,
    ) -> Instance:
        instance_id = str(uuid4())
        slug = self._unique_slug(name)
        server_dir = self._instances_dir / slug / "server"
        server_dir.mkdir(parents=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO instances (
                    id, name, slug, server_dir, game_port, start_map, preset,
                    install_source, source_path, metamod_enabled,
                    counterstrikesharp_enabled, bridge_enabled, status,
                    rcon_password, gslt
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_install', ?, ?)
                """,
                (
                    instance_id,
                    name,
                    slug,
                    str(server_dir),
                    game_port,
                    start_map,
                    preset,
                    install_source,
                    source_path,
                    metamod_enabled,
                    counterstrikesharp_enabled,
                    bridge_enabled,
                    self._cipher.encrypt(rcon_password),
                    self._cipher.encrypt(gslt),
                ),
            )
        instance = self.get(instance_id)
        if instance is None:
            raise RuntimeError("Created instance could not be read")
        return instance

    def used_ports(self) -> set[int]:
        with self._connect() as connection:
            rows = connection.execute("SELECT game_port FROM instances").fetchall()
        return {row["game_port"] for row in rows}

    def set_status(self, instance_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE instances SET status = ? WHERE id = ?",
                (status, instance_id),
            )

    def delete(self, instance_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM instances WHERE id = ?", (instance_id,))

    def launch_preview(self, instance_id: str, *, masked: bool = True) -> list[str]:
        instance = self.get(instance_id)
        if not instance:
            raise KeyError(instance_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT rcon_password, gslt FROM instances WHERE id = ?",
                (instance_id,),
            ).fetchone()
        rcon = "********" if masked else self._cipher.decrypt(row["rcon_password"])
        gslt = "********" if masked else self._cipher.decrypt(row["gslt"])
        return [
            "./game/cs2.sh",
            "-dedicated",
            "-port",
            str(instance.game_port),
            "+map",
            instance.start_map,
            "+rcon_password",
            rcon,
            "+sv_setsteamaccount",
            gslt,
        ]

    def launch_preview_shell(self, instance_id: str) -> str:
        return shlex.join(self.launch_preview(instance_id))

    def rcon_password(self, instance_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT rcon_password FROM instances WHERE id = ?",
                (instance_id,),
            ).fetchone()
        if not row:
            raise KeyError(instance_id)
        return self._cipher.decrypt(row["rcon_password"])

    def _unique_slug(self, name: str) -> str:
        base = _slug_pattern.sub("-", name.lower()).strip("-") or "cs2-server"
        slugs = {instance.slug for instance in self.list()}
        if base not in slugs:
            return base
        suffix = 2
        while f"{base}-{suffix}" in slugs:
            suffix += 1
        return f"{base}-{suffix}"

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Instance:
        return Instance(
            id=row["id"],
            name=row["name"],
            slug=row["slug"],
            server_dir=row["server_dir"],
            game_port=row["game_port"],
            start_map=row["start_map"],
            preset=row["preset"],
            install_source=row["install_source"],
            source_path=row["source_path"],
            metamod_enabled=bool(row["metamod_enabled"]),
            counterstrikesharp_enabled=bool(row["counterstrikesharp_enabled"]),
            bridge_enabled=bool(row["bridge_enabled"]),
            status=row["status"],
        )
