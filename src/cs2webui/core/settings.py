"""Application settings with Linux-oriented defaults."""

from dataclasses import dataclass
from os import environ
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    secure_cookies: bool = False
    game_host: str = "host.containers.internal"
    steam_web_api_key: str | None = None

    @classmethod
    def from_environment(cls) -> "Settings":
        data_dir = Path(
            environ.get("CS2WEBUI_DATA_DIR", "/var/lib/cs2webui/panel")
        )
        secure_cookies = environ.get("CS2WEBUI_SECURE_COOKIES", "false").lower() in {
            "1",
            "true",
            "yes",
        }
        game_host = environ.get("CS2WEBUI_GAME_HOST", "host.containers.internal")
        steam_web_api_key = environ.get("STEAM_WEB_API_KEY")
        return cls(
            data_dir=data_dir,
            secure_cookies=secure_cookies,
            game_host=game_host,
            steam_web_api_key=steam_web_api_key,
        )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "cs2webui.sqlite3"

    @property
    def secret_key_path(self) -> Path:
        return self.data_dir / "secret.key"

    @property
    def instances_dir(self) -> Path:
        return self.data_dir.parent / "instances"

    @property
    def imports_dir(self) -> Path:
        return self.data_dir.parent / "imports"

    @property
    def agent_socket_path(self) -> Path:
        return self.data_dir.parent / "agent.sock"

    @property
    def agent_token_path(self) -> Path:
        return self.data_dir.parent / "agent.token"
