"""Config and plugin backups for managed CS2 instances."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
import shutil
import stat
from uuid import uuid4
import zipfile

from cs2webui.core.instances import Instance

BACKUP_PATHS = (
    "game/csgo/cfg",
    "game/csgo/addons",
)
MAX_BACKUP_RESTORE_BYTES = 1024 * 1024 * 1024
MAX_BACKUP_MEMBERS = 20000


@dataclass(frozen=True, slots=True)
class Backup:
    name: str
    path: str
    size: int

    def as_dict(self) -> dict[str, str | int]:
        return asdict(self)


class BackupStore:
    """Create focused backups without duplicating the full CS2 installation."""

    def create(self, instance: Instance) -> Backup:
        server_dir = Path(instance.server_dir)
        backup_dir = server_dir.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        archive = backup_dir / f"{instance.slug}-{timestamp}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for relative in BACKUP_PATHS:
                source = server_dir / relative
                if not source.exists():
                    continue
                for file_path in source.rglob("*"):
                    if file_path.is_symlink():
                        continue
                    if file_path.is_file():
                        output.write(file_path, file_path.relative_to(server_dir))
        return self._describe(archive)

    def list(self, instance: Instance) -> list[Backup]:
        backup_dir = Path(instance.server_dir).parent / "backups"
        if not backup_dir.exists():
            return []
        return [self._describe(path) for path in sorted(backup_dir.glob("*.zip"))]

    def restore(self, instance: Instance, name: str) -> Backup:
        if Path(name).name != name or not name.endswith(".zip"):
            raise ValueError("Invalid backup name")
        server_dir = Path(instance.server_dir).resolve()
        archive = server_dir.parent / "backups" / name
        if not archive.is_file():
            raise ValueError("Backup not found")
        staging = server_dir.parent / "backup-restore" / str(uuid4())
        staging.mkdir(parents=True)
        try:
            try:
                package = zipfile.ZipFile(archive)
            except zipfile.BadZipFile as error:
                raise ValueError("Backup is not a valid ZIP file") from error
            with package:
                members = package.infolist()
                if len(members) > MAX_BACKUP_MEMBERS:
                    raise ValueError("Backup contains too many entries")
                extracted_bytes = 0
                for member in members:
                    if stat.S_ISLNK(member.external_attr >> 16):
                        raise ValueError("Backup contains a symbolic link")
                    extracted_bytes += member.file_size
                    if extracted_bytes > MAX_BACKUP_RESTORE_BYTES:
                        raise ValueError("Backup expands beyond size limit")
                    target = (staging / member.filename).resolve()
                    try:
                        target.relative_to(staging.resolve())
                    except ValueError as error:
                        raise ValueError("Backup contains an unsafe path") from error
                package.extractall(staging)
            shutil.copytree(staging, server_dir, dirs_exist_ok=True)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return self._describe(archive)

    @staticmethod
    def _describe(path: Path) -> Backup:
        return Backup(name=path.name, path=str(path), size=path.stat().st_size)
