"""Safe archive installation and metadata for CS2 plugins."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from ipaddress import ip_address
from pathlib import Path
import shutil
import socket
import sqlite3
import stat
import tarfile
from urllib.parse import urljoin, urlparse
from uuid import uuid4
import zipfile

import httpx

from cs2webui.core.instances import Instance

MAX_PLUGIN_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_PLUGIN_EXTRACTED_BYTES = 512 * 1024 * 1024
MAX_PLUGIN_MEMBERS = 10000
COUNTERSTRIKESHARP_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/roflmuffin/CounterStrikeSharp/releases/latest"
)
METAMOD_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/alliedmodders/metamod-source/releases/latest"
)


@dataclass(frozen=True, slots=True)
class Plugin:
    id: str
    instance_id: str
    name: str
    source: str
    enabled: bool
    status: str
    checksum: str | None

    def as_dict(self) -> dict[str, str | bool | None]:
        return asdict(self)


class PluginStore:
    def __init__(self, database_path: Path, imports_dir: Path) -> None:
        self._database_path = database_path
        self._imports_dir = imports_dir
        self._imports_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cs2_plugins (
                    id TEXT PRIMARY KEY,
                    instance_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    checksum TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS cs2_plugin_files (
                    plugin_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    PRIMARY KEY (plugin_id, relative_path)
                );
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(cs2_plugins)").fetchall()
            }
            if "checksum" not in columns:
                connection.execute("ALTER TABLE cs2_plugins ADD COLUMN checksum TEXT")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def list(self, instance_id: str) -> list[Plugin]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, instance_id, name, source, enabled, status, checksum
                FROM cs2_plugins WHERE instance_id = ? ORDER BY name
                """,
                (instance_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def install_local(self, instance: Instance, name: str, source: str) -> Plugin:
        archive = self._resolve_local_source(source)
        if archive.is_dir():
            return self._install_directory(instance, name, archive, source)
        return self._install(instance, name, archive, source)

    def _resolve_local_source(self, source: str) -> Path:
        archive = Path(source)
        if not archive.is_absolute():
            archive = self._imports_dir / archive
        archive = archive.resolve()
        try:
            archive.relative_to(self._imports_dir.resolve())
        except ValueError as error:
            raise ValueError(
                "Local plugin source must be inside the managed imports directory"
            ) from error
        return archive

    async def install_url(self, instance: Instance, name: str, source: str) -> Plugin:
        archive = self._imports_dir / f"{uuid4()}.zip"
        try:
            await self._download_url(source, archive)
            return self._install(instance, name, archive, source)
        finally:
            archive.unlink(missing_ok=True)

    async def check_url_update(self, instance_id: str, plugin_id: str) -> dict[str, object]:
        plugin = self._get(instance_id, plugin_id)
        if not plugin:
            raise ValueError("Plugin not found")
        if not plugin.source.startswith("https://"):
            raise ValueError("Only URL-installed plugins can be checked for updates")
        archive = self._imports_dir / f"{uuid4()}.zip"
        try:
            await self._download_url(plugin.source, archive)
            source_checksum = self._checksum(archive)
        finally:
            archive.unlink(missing_ok=True)
        return {
            "plugin_id": plugin.id,
            "installed_checksum": plugin.checksum,
            "source_checksum": source_checksum,
            "update_available": plugin.checksum != source_checksum,
        }

    def install_builtin_bridge(self, instance: Instance) -> Plugin:
        archive = self._imports_dir / "cs2webui-bridge.zip"
        if not archive.is_file():
            raise ValueError(
                "Built-in bridge archive is unavailable; run scripts/build-bridge.sh first"
            )
        return self._install(instance, "CS2 WebUI Bridge", archive, "builtin:bridge")

    async def install_builtin_counterstrikesharp(self, instance: Instance) -> Plugin:
        version, source = await self._latest_counterstrikesharp_asset()
        return await self.install_url(
            instance,
            f"CounterStrikeSharp {version} with runtime",
            source,
        )

    async def install_builtin_metamod(self, instance: Instance) -> Plugin:
        version, source = await self._latest_metamod_asset()
        archive = self._imports_dir / f"{uuid4()}.tar.gz"
        try:
            await self._download_url(source, archive)
            return self._install_metamod_archive(
                instance, f"MetaMod:Source {version}", archive, source
            )
        finally:
            archive.unlink(missing_ok=True)

    async def _latest_counterstrikesharp_asset(self) -> tuple[str, str]:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                COUNTERSTRIKESHARP_LATEST_RELEASE_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "cs2webui",
                },
            )
            response.raise_for_status()
        return self._select_counterstrikesharp_asset(response.json())

    @staticmethod
    def _select_counterstrikesharp_asset(release: dict[str, object]) -> tuple[str, str]:
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise ValueError("Latest CounterStrikeSharp release response is invalid")
        for asset in assets:
            if not isinstance(asset, dict):
                raise ValueError("Latest CounterStrikeSharp release response is invalid")
            name = str(asset.get("name", "")).lower()
            source = str(asset.get("browser_download_url", ""))
            if (
                "linux" in name
                and "with-runtime" in name
                and name.endswith(".zip")
                and source
            ):
                return str(release.get("tag_name", "latest")), source
        raise ValueError(
            "Latest CounterStrikeSharp release does not provide a Linux with-runtime ZIP"
        )

    async def _latest_metamod_asset(self) -> tuple[str, str]:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                METAMOD_LATEST_RELEASE_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "cs2webui",
                },
            )
            response.raise_for_status()
        return self._select_metamod_asset(response.json())

    @staticmethod
    def _select_metamod_asset(release: dict[str, object]) -> tuple[str, str]:
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise ValueError("Latest MetaMod release response is invalid")
        for asset in assets:
            if not isinstance(asset, dict):
                raise ValueError("Latest MetaMod release response is invalid")
            name = str(asset.get("name", "")).lower()
            source = str(asset.get("browser_download_url", ""))
            if "mmsource-2." in name and "linux" in name and name.endswith(".tar.gz") and source:
                return str(release.get("tag_name", "latest")), source
        raise ValueError("Latest MetaMod release does not provide a Linux tarball")

    def has_builtin_bridge(self, instance_id: str) -> bool:
        return any(
            plugin.source == "builtin:bridge" for plugin in self.list(instance_id)
        )

    def has_plugin_named(self, instance_id: str, prefix: str) -> bool:
        return any(plugin.name.startswith(prefix) for plugin in self.list(instance_id))

    async def _download_url(self, source: str, archive: Path) -> None:
        current = source
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            for _ in range(5):
                self._validate_url(current)
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("Plugin URL redirect is missing location")
                        current = urljoin(current, location)
                        continue
                    response.raise_for_status()
                    total = 0
                    with archive.open("wb") as output:
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > MAX_PLUGIN_ARCHIVE_BYTES:
                                raise ValueError("Plugin archive exceeds size limit")
                            output.write(chunk)
                    return
        raise ValueError("Plugin URL has too many redirects")

    def set_enabled(self, instance: Instance, plugin_id: str, enabled: bool) -> Plugin:
        plugin = self._get(instance.id, plugin_id)
        if not plugin:
            raise ValueError("Plugin not found")
        server_dir = Path(instance.server_dir).resolve()
        disabled_dir = server_dir.parent / "disabled-plugins" / plugin.id
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT relative_path FROM cs2_plugin_files WHERE plugin_id = ?",
                (plugin.id,),
            ).fetchall()
            for row in rows:
                relative_path = Path(row["relative_path"])
                source = (server_dir if not enabled else disabled_dir) / relative_path
                target = (disabled_dir if not enabled else server_dir) / relative_path
                if not source.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
            connection.execute(
                """
                UPDATE cs2_plugins SET enabled = ?, status = ?
                WHERE id = ? AND instance_id = ?
                """,
                (enabled, "installed" if enabled else "disabled", plugin.id, instance.id),
            )
        updated = self._get(instance.id, plugin.id)
        if not updated:
            raise RuntimeError("Updated plugin could not be read")
        return updated

    def _install(self, instance: Instance, name: str, archive: Path, source: str) -> Plugin:
        if not archive.is_file() or archive.stat().st_size > MAX_PLUGIN_ARCHIVE_BYTES:
            raise ValueError("Plugin archive is missing or exceeds size limit")
        server_dir = Path(instance.server_dir).resolve()
        staging = server_dir.parent / "plugin-staging" / str(uuid4())
        staging.mkdir(parents=True)
        try:
            try:
                package = zipfile.ZipFile(archive)
            except zipfile.BadZipFile as error:
                raise ValueError("Plugin archive is not a valid ZIP file") from error
            with package:
                members = package.infolist()
                if len(members) > MAX_PLUGIN_MEMBERS:
                    raise ValueError("Plugin archive contains too many entries")
                extracted_bytes = 0
                for member in members:
                    if stat.S_ISLNK(member.external_attr >> 16):
                        raise ValueError("Plugin archive contains a symbolic link")
                    extracted_bytes += member.file_size
                    if extracted_bytes > MAX_PLUGIN_EXTRACTED_BYTES:
                        raise ValueError("Plugin archive expands beyond size limit")
                    target = (staging / member.filename).resolve()
                    try:
                        target.relative_to(staging.resolve())
                    except ValueError as error:
                        raise ValueError("Plugin archive contains an unsafe path") from error
                package.extractall(staging)
            files = [path.relative_to(staging) for path in staging.rglob("*") if path.is_file()]
            if not files:
                raise ValueError("Plugin archive does not contain files")
            conflicts = [path for path in files if (server_dir / path).exists()]
            if conflicts:
                raise ValueError(
                    f"Plugin archive would overwrite an existing file: {conflicts[0]}"
                )
            shutil.copytree(staging, server_dir, dirs_exist_ok=True)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return self._record_plugin(instance.id, name, source, archive, files)

    def _install_directory(
        self, instance: Instance, name: str, directory: Path, source: str
    ) -> Plugin:
        server_dir = Path(instance.server_dir).resolve()
        files: list[Path] = []
        extracted_bytes = 0
        members = list(directory.rglob("*"))
        if len(members) > MAX_PLUGIN_MEMBERS:
            raise ValueError("Plugin directory contains too many entries")
        for member in members:
            if member.is_symlink():
                raise ValueError("Plugin directory contains a symbolic link")
            if member.is_dir():
                continue
            if not member.is_file():
                raise ValueError("Plugin directory contains an unsupported entry")
            extracted_bytes += member.stat().st_size
            if extracted_bytes > MAX_PLUGIN_EXTRACTED_BYTES:
                raise ValueError("Plugin directory exceeds size limit")
            files.append(member.relative_to(directory))
        if not files:
            raise ValueError("Plugin directory does not contain files")
        conflicts = [path for path in files if (server_dir / path).exists()]
        if conflicts:
            raise ValueError(
                f"Plugin directory would overwrite an existing file: {conflicts[0]}"
            )
        shutil.copytree(directory, server_dir, dirs_exist_ok=True)
        return self._record_plugin(instance.id, name, source, directory, files)

    def _install_metamod_archive(
        self, instance: Instance, name: str, archive: Path, source: str
    ) -> Plugin:
        if not archive.is_file() or archive.stat().st_size > MAX_PLUGIN_ARCHIVE_BYTES:
            raise ValueError("MetaMod archive is missing or exceeds size limit")
        server_dir = Path(instance.server_dir).resolve()
        game_dir = server_dir / "game" / "csgo"
        gameinfo = game_dir / "gameinfo.gi"
        if not gameinfo.is_file():
            raise ValueError("CS2 gameinfo.gi is missing; install server files first")
        staging = server_dir.parent / "plugin-staging" / str(uuid4())
        staging.mkdir(parents=True)
        try:
            try:
                package = tarfile.open(archive, "r:gz")
            except tarfile.TarError as error:
                raise ValueError("MetaMod archive is not a valid tarball") from error
            with package:
                members = package.getmembers()
                if len(members) > MAX_PLUGIN_MEMBERS:
                    raise ValueError("MetaMod archive contains too many entries")
                extracted_bytes = 0
                for member in members:
                    if member.issym() or member.islnk():
                        raise ValueError("MetaMod archive contains a symbolic link")
                    if not (member.isfile() or member.isdir()):
                        raise ValueError("MetaMod archive contains an unsupported entry")
                    extracted_bytes += member.size
                    if extracted_bytes > MAX_PLUGIN_EXTRACTED_BYTES:
                        raise ValueError("MetaMod archive expands beyond size limit")
                    target = (staging / member.name).resolve()
                    try:
                        target.relative_to(staging.resolve())
                    except ValueError as error:
                        raise ValueError("MetaMod archive contains an unsafe path") from error
                package.extractall(staging, filter="data")
            addons = staging / "addons"
            if not addons.is_dir():
                raise ValueError("MetaMod archive does not contain an addons directory")
            files = [
                path.relative_to(staging)
                for path in staging.rglob("*")
                if path.is_file()
            ]
            installed_files = [Path("game/csgo") / path for path in files]
            conflicts = [path for path in installed_files if (server_dir / path).exists()]
            if conflicts:
                raise ValueError(
                    f"MetaMod archive would overwrite an existing file: {conflicts[0]}"
                )
            patched_gameinfo = self._patched_metamod_gameinfo(gameinfo.read_text())
            shutil.copytree(addons, game_dir / "addons", dirs_exist_ok=True)
            gameinfo.write_text(patched_gameinfo)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return self._record_plugin(
            instance.id, name, source, archive, installed_files
        )

    @staticmethod
    def _patched_metamod_gameinfo(content: str) -> str:
        directive = "Game csgo/addons/metamod"
        if directive in content:
            return content
        lines = content.splitlines(keepends=True)
        for index, line in enumerate(lines):
            if "Game_LowViolence csgo_lv" in line:
                indent = line[: len(line) - len(line.lstrip())]
                ending = "\r\n" if line.endswith("\r\n") else "\n"
                lines.insert(index + 1, f"{indent}{directive}{ending}")
                return "".join(lines)
        raise ValueError("CS2 gameinfo.gi does not contain the MetaMod insertion point")

    def _record_plugin(
        self,
        instance_id: str,
        name: str,
        source: str,
        archive: Path,
        files: list[Path],
    ) -> Plugin:
        plugin = Plugin(
            id=str(uuid4()),
            instance_id=instance_id,
            name=name,
            source=source,
            enabled=True,
            status="installed",
            checksum=self._checksum(archive),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cs2_plugins (
                    id, instance_id, name, source, enabled, status, checksum
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plugin.id,
                    plugin.instance_id,
                    plugin.name,
                    plugin.source,
                    plugin.enabled,
                    plugin.status,
                    plugin.checksum,
                ),
            )
            connection.executemany(
                "INSERT INTO cs2_plugin_files (plugin_id, relative_path) VALUES (?, ?)",
                [(plugin.id, str(path)) for path in files],
            )
        return plugin

    def _get(self, instance_id: str, plugin_id: str) -> Plugin | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, instance_id, name, source, enabled, status, checksum
                FROM cs2_plugins WHERE instance_id = ? AND id = ?
                """,
                (instance_id, plugin_id),
            ).fetchone()
        return self._from_row(row) if row else None

    @staticmethod
    def _checksum(archive: Path) -> str:
        digest = sha256()
        if archive.is_dir():
            for path in sorted(
                (path for path in archive.rglob("*") if path.is_file()),
                key=lambda path: path.relative_to(archive).as_posix(),
            ):
                digest.update(path.relative_to(archive).as_posix().encode())
                digest.update(b"\x00")
                with path.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
            return digest.hexdigest()
        with archive.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _validate_url(source: str) -> None:
        parsed = urlparse(source)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Plugin URL must use https")
        for result in socket.getaddrinfo(parsed.hostname, 443):
            address = ip_address(result[4][0])
            if not address.is_global:
                raise ValueError("Plugin URL resolves to a non-public address")

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Plugin:
        return Plugin(
            id=row["id"],
            instance_id=row["instance_id"],
            name=row["name"],
            source=row["source"],
            enabled=bool(row["enabled"]),
            status=row["status"],
            checksum=row["checksum"],
        )
