"""Core RCON console, quick commands, and presets."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from cs2webui.api.auth import require_roles
from cs2webui.core.auth import User
from cs2webui.core.presets import PRESETS, QUICK_COMMANDS
from cs2webui.host.rcon import RconError

router = APIRouter(prefix="/api", tags=["console"])


class CommandPayload(BaseModel):
    command: str = Field(min_length=1, max_length=1024)


class PresetPayload(BaseModel):
    preset: str


class QuickCommandPayload(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    command: str = Field(min_length=1, max_length=1024, pattern=r"^[^\r\n]+$")


@router.get("/presets")
async def presets(
    _user: Annotated[User, Depends(require_roles("admin", "operator", "viewer"))],
) -> dict[str, object]:
    return PRESETS


@router.get("/quick-commands")
async def quick_commands(
    request: Request,
    _user: Annotated[User, Depends(require_roles("admin", "operator", "viewer"))],
) -> list[dict[str, object]]:
    return [
        *QUICK_COMMANDS,
        *[
            quick_command.as_dict()
            for quick_command in request.app.state.quick_command_store.list()
        ],
    ]


@router.post("/quick-commands", status_code=201)
async def create_quick_command(
    payload: QuickCommandPayload,
    request: Request,
    actor: Annotated[User, Depends(require_roles("admin"))],
) -> dict[str, object]:
    quick_command = request.app.state.quick_command_store.create(
        payload.label, payload.command
    )
    request.app.state.audit_store.record(
        "quick-command.created",
        f"actor={actor.username};quick_command={quick_command.id}",
    )
    return quick_command.as_dict()


@router.delete("/quick-commands/{quick_command_id}", status_code=204)
async def delete_quick_command(
    quick_command_id: str,
    request: Request,
    actor: Annotated[User, Depends(require_roles("admin"))],
) -> None:
    try:
        request.app.state.quick_command_store.delete(quick_command_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    request.app.state.audit_store.record(
        "quick-command.deleted",
        f"actor={actor.username};quick_command={quick_command_id}",
    )


@router.post("/instances/{instance_id}/rcon")
async def execute_rcon(
    instance_id: str,
    payload: CommandPayload,
    request: Request,
    actor: Annotated[User, Depends(require_roles("admin", "operator"))],
) -> dict[str, str]:
    instance = request.app.state.instance_store.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    password = request.app.state.instance_store.rcon_password(instance.id)
    try:
        response = request.app.state.rcon_client.execute(
            request.app.state.settings.game_host,
            instance.game_port,
            password,
            payload.command,
        )
    except RconError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    request.app.state.audit_store.record(
        "instance.rcon", f"actor={actor.username};instance={instance.id}"
    )
    return {"response": response.body}


@router.post("/instances/{instance_id}/preset")
async def apply_preset(
    instance_id: str,
    payload: PresetPayload,
    request: Request,
    actor: Annotated[User, Depends(require_roles("admin", "operator"))],
) -> dict[str, object]:
    instance = request.app.state.instance_store.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    preset = PRESETS.get(payload.preset)
    if not preset:
        raise HTTPException(status_code=422, detail="Unknown preset")
    responses = []
    for command in preset["commands"]:
        try:
            response = request.app.state.rcon_client.execute(
                request.app.state.settings.game_host,
                instance.game_port,
                request.app.state.instance_store.rcon_password(instance.id),
                command,
            )
        except RconError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        responses.append({"command": command, "response": response.body})
    request.app.state.audit_store.record(
        "instance.preset.applied",
        f"actor={actor.username};instance={instance.id};preset={payload.preset}",
    )
    return {"preset": payload.preset, "results": responses}
