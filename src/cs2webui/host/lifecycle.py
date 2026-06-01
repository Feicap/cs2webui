"""Linux-first command planning for CS2 instance lifecycle operations."""

from dataclasses import asdict, dataclass
from pathlib import Path
import shlex

from cs2webui.core.instances import Instance, InstanceStore


@dataclass(frozen=True, slots=True)
class PlannedCommand:
    label: str
    arguments: tuple[str, ...]
    mutates_files: bool

    def as_dict(self) -> dict[str, object]:
        return {**asdict(self), "command": shlex.join(self.arguments)}


class LifecyclePlanner:
    """Create reviewable Podman commands without executing host operations."""

    steamcmd_image = "localhost/cs2webui-steamcmd:local"
    server_image = "localhost/cs2webui-server:local"

    def __init__(self, instances: InstanceStore) -> None:
        self._instances = instances

    def install(self, instance: Instance) -> list[PlannedCommand]:
        server_dir = Path(instance.server_dir)
        return [
            PlannedCommand(
                label="Download or validate CS2 server files with SteamCMD",
                arguments=(
                    "podman",
                    "run",
                    "--rm",
                    "--volume",
                    f"{server_dir}:/server:z",
                    self.steamcmd_image,
                    "+force_install_dir",
                    "/server",
                    "+login",
                    "anonymous",
                    "+app_update",
                    "730",
                    "validate",
                    "+quit",
                ),
                mutates_files=True,
            )
        ]

    def start(self, instance: Instance, *, masked: bool = True) -> list[PlannedCommand]:
        server_dir = Path(instance.server_dir)
        launch_arguments = self._instances.launch_preview(instance.id, masked=masked)
        return [
            PlannedCommand(
                label="Start isolated CS2 server container",
                arguments=(
                    "podman",
                    "run",
                    "--detach",
                    "--replace",
                    "--name",
                    f"cs2webui-{instance.slug}",
                    "--network",
                    "host",
                    "--volume",
                    f"{server_dir}:/server:z",
                    "--workdir",
                    "/server",
                    self.server_image,
                    *launch_arguments,
                ),
                mutates_files=False,
            )
        ]

    def stop(self, instance: Instance) -> list[PlannedCommand]:
        return [
            PlannedCommand(
                label="Stop CS2 server container",
                arguments=("podman", "stop", "--ignore", f"cs2webui-{instance.slug}"),
                mutates_files=False,
            )
        ]
