"""Safe editable text configuration files for CS2 instances."""

from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path, PurePosixPath

from cs2webui.core.instances import Instance

ALLOWED_PREFIXES = ("game/csgo/cfg/",)
ALLOWED_FILES = {"game/csgo/mapcycle.txt"}
MAX_CONFIG_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ConfigChange:
    path: str
    content: str
    diff: str


class ConfigurationStore:
    def read(self, instance: Instance, path: str) -> str:
        target = self._target(instance, path)
        if not target.exists():
            return ""
        return target.read_text(encoding="utf-8")

    def preview(self, instance: Instance, path: str, content: str) -> ConfigChange:
        self._validate_content(content)
        current = self.read(instance, path)
        diff = "".join(
            unified_diff(
                current.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=f"{path}.before",
                tofile=f"{path}.after",
            )
        )
        return ConfigChange(path=path, content=content, diff=diff)

    def write(self, instance: Instance, path: str, content: str) -> ConfigChange:
        change = self.preview(instance, path, content)
        target = self._target(instance, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return change

    @staticmethod
    def _validate_content(content: str) -> None:
        if len(content.encode()) > MAX_CONFIG_BYTES:
            raise ValueError("Configuration file exceeds size limit")

    @staticmethod
    def _target(instance: Instance, path: str) -> Path:
        normalized = str(PurePosixPath(path))
        if (
            normalized.startswith("/")
            or ".." in PurePosixPath(normalized).parts
            or not (
                normalized in ALLOWED_FILES
                or any(normalized.startswith(prefix) for prefix in ALLOWED_PREFIXES)
            )
        ):
            raise ValueError("Configuration path is not allowed")
        server_dir = Path(instance.server_dir).resolve()
        target = (server_dir / normalized).resolve()
        try:
            target.relative_to(server_dir)
        except ValueError as error:
            raise ValueError("Configuration path escapes server directory") from error
        return target
