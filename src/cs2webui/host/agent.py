"""Restricted host agent exposed only through a local Unix socket."""

from hmac import compare_digest
from os import environ
from pathlib import Path
import json
import re
import shutil
import subprocess

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="CS2 WebUI host agent", docs_url=None, redoc_url=None)
_container_name = re.compile(r"^cs2webui-[a-z0-9][a-z0-9-]*$")


class ExecutePayload(BaseModel):
    arguments: list[str] = Field(min_length=2, max_length=100)
    timeout: int = Field(default=3600, ge=1, le=86400)


class ImportPayload(BaseModel):
    mode: str
    source: str
    destination: str


class DeleteServerPayload(BaseModel):
    destination: str


def _expected_token() -> str:
    token_path = Path(environ.get("CS2WEBUI_AGENT_TOKEN", "/var/lib/cs2webui/agent.token"))
    return token_path.read_text(encoding="utf-8").strip()


def _authorize(token: str | None) -> None:
    if not token or not compare_digest(token, _expected_token()):
        raise HTTPException(status_code=401, detail="Invalid agent token")


def _validate(arguments: list[str]) -> None:
    if arguments[0] != "podman":
        raise HTTPException(status_code=400, detail="Only podman commands are allowed")
    if any("\x00" in argument or len(argument) > 4096 for argument in arguments):
        raise HTTPException(status_code=400, detail="Invalid command argument")
    if _valid_steamcmd(arguments) or _valid_server_start(arguments) or _valid_stop(arguments):
        return
    raise HTTPException(status_code=400, detail="Podman command is not allowed")


def _instances_dir() -> Path:
    return Path(environ.get("CS2WEBUI_INSTANCES_DIR", "/var/lib/cs2webui/instances"))


def _valid_volume(argument: str) -> bool:
    suffix = ":/server:z"
    if not argument.endswith(suffix):
        return False
    source = argument[: -len(suffix)]
    try:
        _managed_destination(source)
    except HTTPException:
        return False
    return True


def _valid_steamcmd(arguments: list[str]) -> bool:
    return (
        len(arguments) == 14
        and arguments[:4] == ["podman", "run", "--rm", "--volume"]
        and _valid_volume(arguments[4])
        and arguments[5:] == [
            "localhost/cs2webui-steamcmd:local",
            "+force_install_dir",
            "/server",
            "+login",
            "anonymous",
            "+app_update",
            "730",
            "validate",
            "+quit",
        ]
    )


def _valid_server_start(arguments: list[str]) -> bool:
    return (
        len(arguments) >= 16
        and arguments[:4] == ["podman", "run", "--detach", "--replace"]
        and arguments[4] == "--name"
        and _container_name.fullmatch(arguments[5]) is not None
        and arguments[6:9] == ["--network", "host", "--volume"]
        and _valid_volume(arguments[9])
        and arguments[10:13] == ["--workdir", "/server", "localhost/cs2webui-server:local"]
        and arguments[13:15] == ["./game/cs2.sh", "-dedicated"]
    )


def _valid_stop(arguments: list[str]) -> bool:
    return (
        len(arguments) == 4
        and arguments[:3] == ["podman", "stop", "--ignore"]
        and _container_name.fullmatch(arguments[3]) is not None
    )


def _managed_destination(destination: str) -> Path:
    target = Path(destination).resolve()
    instances_dir = _instances_dir().resolve()
    try:
        target.relative_to(instances_dir)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Destination is not managed") from error
    if target.name != "server" or target.parent.parent != instances_dir:
        raise HTTPException(status_code=400, detail="Invalid managed server directory")
    return target


def _paths_overlap(source: Path, destination: Path) -> bool:
    return (
        source == destination
        or source in destination.parents
        or destination in source.parents
    )


def _validated_container_name(container_name: str) -> str:
    if _container_name.fullmatch(container_name) is None:
        raise HTTPException(status_code=400, detail="Invalid managed container name")
    return container_name


@app.get("/health")
async def health(x_cs2webui_token: str | None = Header(default=None)) -> dict[str, str]:
    _authorize(x_cs2webui_token)
    return {"status": "ok"}


@app.post("/execute")
async def execute(
    payload: ExecutePayload,
    x_cs2webui_token: str | None = Header(default=None),
) -> dict[str, object]:
    _authorize(x_cs2webui_token)
    _validate(payload.arguments)
    result = subprocess.run(
        payload.arguments,
        check=False,
        capture_output=True,
        text=True,
        timeout=payload.timeout,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-20000:],
        "stderr": result.stderr[-20000:],
    }


@app.get("/containers/{container_name}/logs")
async def container_logs(
    container_name: str,
    tail: int = 200,
    x_cs2webui_token: str | None = Header(default=None),
) -> dict[str, object]:
    _authorize(x_cs2webui_token)
    name = _validated_container_name(container_name)
    if not 1 <= tail <= 1000:
        raise HTTPException(status_code=400, detail="Tail must be between 1 and 1000")
    result = subprocess.run(
        ["podman", "logs", "--tail", str(tail), name],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-100000:],
        "stderr": result.stderr[-20000:],
    }


@app.get("/containers/{container_name}/stats")
async def container_stats(
    container_name: str,
    x_cs2webui_token: str | None = Header(default=None),
) -> dict[str, object]:
    _authorize(x_cs2webui_token)
    name = _validated_container_name(container_name)
    result = subprocess.run(
        ["podman", "stats", "--no-stream", "--format", "json", name],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    stats: object | None = None
    if result.returncode == 0 and result.stdout.strip():
        try:
            stats = json.loads(result.stdout)
        except json.JSONDecodeError:
            stats = None
    return {
        "returncode": result.returncode,
        "stats": stats,
        "stderr": result.stderr[-20000:],
    }


@app.post("/import-server")
async def import_server(
    payload: ImportPayload,
    x_cs2webui_token: str | None = Header(default=None),
) -> dict[str, str]:
    _authorize(x_cs2webui_token)
    if payload.mode not in {"import", "copy", "move"}:
        raise HTTPException(status_code=400, detail="Unsupported import mode")
    source = Path(payload.source).resolve()
    destination = _managed_destination(payload.destination)
    if not (source / "game" / "cs2.sh").is_file():
        raise HTTPException(status_code=422, detail="Source is not a CS2 server directory")
    if _paths_overlap(source, destination):
        raise HTTPException(
            status_code=409, detail="Source and destination directories overlap"
        )
    if destination.exists() and any(destination.iterdir()):
        raise HTTPException(status_code=409, detail="Destination is not empty")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.rmdir()
    if payload.mode == "move":
        shutil.move(str(source), str(destination))
    else:
        shutil.copytree(source, destination)
    return {"status": "imported"}


@app.post("/delete-server")
async def delete_server(
    payload: DeleteServerPayload,
    x_cs2webui_token: str | None = Header(default=None),
) -> dict[str, str]:
    _authorize(x_cs2webui_token)
    destination = _managed_destination(payload.destination)
    shutil.rmtree(destination.parent, ignore_errors=True)
    return {"status": "deleted"}
