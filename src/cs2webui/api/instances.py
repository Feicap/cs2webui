"""Core API for isolated CS2 instances."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator

from cs2webui.api.auth import require_roles
from cs2webui.core.auth import User
from cs2webui.host.agent_client import AgentUnavailableError

router = APIRouter(prefix="/api/instances", tags=["instances"])
admin_or_operator = require_roles("admin", "operator")
CS2_RECOMMENDED_INSTALL_BYTES = 65 * 1024**3


class InstancePayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    game_port: int = Field(ge=1024, le=65535)
    start_map: str = Field(
        default="de_dust2", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_/-]+$"
    )
    preset: Literal["competitive", "casual", "deathmatch", "workshop", "custom"]
    install_source: Literal["steamcmd", "import", "copy", "move"] = "steamcmd"
    source_path: str | None = Field(default=None, max_length=2048)
    rcon_password: str = Field(min_length=8, max_length=256)
    gslt: str = Field(min_length=1, max_length=256)
    metamod_enabled: bool = False
    counterstrikesharp_enabled: bool = False
    bridge_enabled: bool = True

    @model_validator(mode="after")
    def require_source_path_for_import(self) -> "InstancePayload":
        if self.install_source != "steamcmd" and not self.source_path:
            raise ValueError("Source path is required for import, copy, or move")
        return self


class CloneInstancePayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    game_port: int = Field(ge=1024, le=65535)
    rcon_password: str = Field(min_length=8, max_length=256)
    gslt: str = Field(min_length=1, max_length=256)


class DeleteInstancePayload(BaseModel):
    purge_files: bool = False
    confirmation: str | None = None


@router.get("")
async def instances(
    request: Request,
    _user: User = Depends(require_roles("admin", "operator", "viewer")),
) -> list[dict[str, object]]:
    return [instance.as_dict() for instance in request.app.state.instance_store.list()]


@router.get("/ports")
async def ports(
    request: Request,
    _user: User = Depends(admin_or_operator),
    start_port: Annotated[int, Query(ge=1024, le=65535)] = 27015,
    count: Annotated[int, Query(ge=1, le=50)] = 10,
) -> dict[str, object]:
    if start_port + count > 65536:
        raise HTTPException(status_code=422, detail="Port range exceeds 65535")
    report = request.app.state.diagnostics.inspect_udp(start_port, count)
    used_ports = request.app.state.instance_store.used_ports()
    response = report.as_dict()
    response["ports"] = [
        {
            **item,
            "available": item["available"] and item["port"] not in used_ports,
            "reserved_by_panel": item["port"] in used_ports,
        }
        for item in response["ports"]
    ]
    response["suggested_port"] = next(
        (item["port"] for item in response["ports"] if item["available"]), None
    )
    disk_free_bytes = request.app.state.metrics_client.read().disk_free_bytes
    response["capacity"] = {
        "disk_free_bytes": disk_free_bytes,
        "recommended_install_bytes": CS2_RECOMMENDED_INSTALL_BYTES,
        "enough_for_recommended_install": (
            disk_free_bytes >= CS2_RECOMMENDED_INSTALL_BYTES
        ),
    }
    return response


@router.post("", status_code=201)
async def create_instance(
    payload: InstancePayload,
    request: Request,
    actor: User = Depends(require_roles("admin")),
) -> dict[str, object]:
    report = request.app.state.diagnostics.inspect_udp(payload.game_port, 1)
    if (
        not report.ports[0].available
        or payload.game_port in request.app.state.instance_store.used_ports()
    ):
        raise HTTPException(status_code=409, detail="Selected game port is already in use")
    try:
        instance = request.app.state.instance_store.create(**payload.model_dump())
    except OSError as error:
        raise HTTPException(status_code=500, detail="Could not create instance path") from error
    request.app.state.audit_store.record(
        "instance.created",
        f"actor={actor.username};instance={instance.id};port={instance.game_port}",
    )
    return {
        **instance.as_dict(),
        "launch_preview": request.app.state.instance_store.launch_preview_shell(
            instance.id
        ),
    }


@router.get("/{instance_id}/launch-preview")
async def launch_preview(
    instance_id: str,
    request: Request,
    _user: User = Depends(admin_or_operator),
) -> dict[str, object]:
    try:
        arguments = request.app.state.instance_store.launch_preview(instance_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Instance not found") from error
    return {
        "arguments": arguments,
        "command": request.app.state.instance_store.launch_preview_shell(instance_id),
    }


@router.post("/{instance_id}/clone", status_code=201)
async def clone_instance(
    instance_id: str,
    payload: CloneInstancePayload,
    request: Request,
    actor: User = Depends(require_roles("admin")),
) -> dict[str, object]:
    source = request.app.state.instance_store.get(instance_id)
    if not source:
        raise HTTPException(status_code=404, detail="Instance not found")
    report = request.app.state.diagnostics.inspect_udp(payload.game_port, 1)
    if (
        not report.ports[0].available
        or payload.game_port in request.app.state.instance_store.used_ports()
    ):
        raise HTTPException(status_code=409, detail="Selected game port is already in use")
    instance = request.app.state.instance_store.create(
        name=payload.name,
        game_port=payload.game_port,
        start_map=source.start_map,
        preset=source.preset,
        install_source="copy",
        source_path=source.server_dir,
        metamod_enabled=source.metamod_enabled,
        counterstrikesharp_enabled=source.counterstrikesharp_enabled,
        rcon_password=payload.rcon_password,
        gslt=payload.gslt,
        bridge_enabled=source.bridge_enabled,
    )
    request.app.state.audit_store.record(
        "instance.cloned",
        f"actor={actor.username};source={source.id};instance={instance.id}",
    )
    return instance.as_dict()


@router.delete("/{instance_id}")
async def delete_instance(
    instance_id: str,
    payload: DeleteInstancePayload,
    request: Request,
    actor: User = Depends(require_roles("admin")),
) -> dict[str, object]:
    instance = request.app.state.instance_store.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if payload.purge_files:
        if payload.confirmation != "DELETE-CS2-FILES":
            raise HTTPException(status_code=422, detail="File deletion was not confirmed")
        if instance.status == "running":
            raise HTTPException(status_code=409, detail="Stop the server before deleting files")
        try:
            await request.app.state.agent_client.delete_server(instance.server_dir)
        except AgentUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
    request.app.state.instance_store.delete(instance.id)
    request.app.state.audit_store.record(
        "instance.deleted",
        f"actor={actor.username};instance={instance.id};purge_files={payload.purge_files}",
    )
    return {"instance_id": instance.id, "purged_files": payload.purge_files}
