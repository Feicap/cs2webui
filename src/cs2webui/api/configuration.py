"""Configuration editor with mandatory diff preview support."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from cs2webui.api.auth import require_roles
from cs2webui.core.auth import User

router = APIRouter(prefix="/api/instances", tags=["configuration"])


class ConfigurationPayload(BaseModel):
    content: str = Field(max_length=1024 * 1024)
    apply: bool = False


@router.get("/{instance_id}/config")
async def read_config(
    instance_id: str,
    request: Request,
    _user: Annotated[User, Depends(require_roles("admin", "operator", "viewer"))],
    path: Annotated[str, Query(max_length=512)] = "game/csgo/cfg/server.cfg",
) -> dict[str, str]:
    instance = request.app.state.instance_store.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    try:
        content = request.app.state.configuration_store.read(instance, path)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"path": path, "content": content}


@router.put("/{instance_id}/config")
async def update_config(
    instance_id: str,
    payload: ConfigurationPayload,
    request: Request,
    actor: Annotated[User, Depends(require_roles("admin"))],
    path: Annotated[str, Query(max_length=512)] = "game/csgo/cfg/server.cfg",
) -> dict[str, str | bool]:
    instance = request.app.state.instance_store.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    try:
        if payload.apply:
            request.app.state.backup_store.create(instance)
            change = request.app.state.configuration_store.write(
                instance, path, payload.content
            )
            request.app.state.audit_store.record(
                "instance.config.updated",
                f"actor={actor.username};instance={instance.id};path={path}",
            )
        else:
            change = request.app.state.configuration_store.preview(
                instance, path, payload.content
            )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"path": change.path, "diff": change.diff, "applied": payload.apply}
