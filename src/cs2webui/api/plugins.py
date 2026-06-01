"""Universal CS2 plugin archive installation API."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
import httpx
from pydantic import BaseModel, Field

from cs2webui.api.auth import require_roles
from cs2webui.core.auth import User
from cs2webui.host.rcon import RconError

router = APIRouter(prefix="/api/instances", tags=["plugins"])


class PluginPayload(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    source_type: Literal["local", "url"]
    source: str = Field(min_length=1, max_length=2048)


class PluginEnabledPayload(BaseModel):
    enabled: bool


@router.get("/{instance_id}/plugins")
async def plugins(
    instance_id: str,
    request: Request,
    _user: Annotated[User, Depends(require_roles("admin", "operator", "viewer"))],
) -> list[dict[str, str | bool | None]]:
    if not request.app.state.instance_store.get(instance_id):
        raise HTTPException(status_code=404, detail="Instance not found")
    return [
        plugin.as_dict() for plugin in request.app.state.plugin_store.list(instance_id)
    ]


@router.get("/{instance_id}/plugins/runtime-status")
async def plugin_runtime_status(
    instance_id: str,
    request: Request,
    _user: Annotated[User, Depends(require_roles("admin", "operator", "viewer"))],
) -> dict[str, str]:
    instance = request.app.state.instance_store.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    try:
        response = request.app.state.rcon_client.execute(
            request.app.state.settings.game_host,
            instance.game_port,
            request.app.state.instance_store.rcon_password(instance.id),
            "meta list",
        )
    except (OSError, RconError) as error:
        return {"status": "unavailable", "output": str(error)}
    return {"status": "available", "output": response.body}


@router.post("/{instance_id}/plugins", status_code=201)
async def install_plugin(
    instance_id: str,
    payload: PluginPayload,
    request: Request,
    actor: Annotated[User, Depends(require_roles("admin"))],
) -> dict[str, str | bool | None]:
    instance = request.app.state.instance_store.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    try:
        if payload.source_type == "url":
            plugin = await request.app.state.plugin_store.install_url(
                instance, payload.name, payload.source
            )
        else:
            plugin = request.app.state.plugin_store.install_local(
                instance, payload.name, payload.source
            )
    except (OSError, ValueError, httpx.HTTPError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    request.app.state.audit_store.record(
        "instance.plugin.installed",
        f"actor={actor.username};instance={instance.id};plugin={plugin.name}",
    )
    return plugin.as_dict()


@router.post("/{instance_id}/plugins/builtin-bridge", status_code=201)
async def install_builtin_bridge(
    instance_id: str,
    request: Request,
    actor: Annotated[User, Depends(require_roles("admin"))],
) -> dict[str, str | bool | None]:
    instance = request.app.state.instance_store.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    try:
        plugin = request.app.state.plugin_store.install_builtin_bridge(instance)
    except (OSError, ValueError, httpx.HTTPError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    request.app.state.audit_store.record(
        "instance.plugin.installed",
        f"actor={actor.username};instance={instance.id};plugin={plugin.name}",
    )
    return plugin.as_dict()


@router.post("/{instance_id}/plugins/builtin-counterstrikesharp", status_code=201)
async def install_builtin_counterstrikesharp(
    instance_id: str,
    request: Request,
    actor: Annotated[User, Depends(require_roles("admin"))],
) -> dict[str, str | bool | None]:
    instance = request.app.state.instance_store.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    try:
        plugin = await request.app.state.plugin_store.install_builtin_counterstrikesharp(
            instance
        )
    except (OSError, ValueError, httpx.HTTPError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    request.app.state.audit_store.record(
        "instance.plugin.installed",
        f"actor={actor.username};instance={instance.id};plugin={plugin.name}",
    )
    return plugin.as_dict()


@router.post("/{instance_id}/plugins/builtin-metamod", status_code=201)
async def install_builtin_metamod(
    instance_id: str,
    request: Request,
    actor: Annotated[User, Depends(require_roles("admin"))],
) -> dict[str, str | bool | None]:
    instance = request.app.state.instance_store.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    try:
        plugin = await request.app.state.plugin_store.install_builtin_metamod(instance)
    except (OSError, ValueError, httpx.HTTPError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    request.app.state.audit_store.record(
        "instance.plugin.installed",
        f"actor={actor.username};instance={instance.id};plugin={plugin.name}",
    )
    return plugin.as_dict()


@router.put("/{instance_id}/plugins/{plugin_id}")
async def set_plugin_enabled(
    instance_id: str,
    plugin_id: str,
    payload: PluginEnabledPayload,
    request: Request,
    actor: Annotated[User, Depends(require_roles("admin"))],
) -> dict[str, str | bool | None]:
    instance = request.app.state.instance_store.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    try:
        plugin = request.app.state.plugin_store.set_enabled(
            instance, plugin_id, payload.enabled
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    request.app.state.audit_store.record(
        "instance.plugin.toggled",
        f"actor={actor.username};instance={instance.id};plugin={plugin.name};enabled={plugin.enabled}",
    )
    return plugin.as_dict()


@router.get("/{instance_id}/plugins/{plugin_id}/update-check")
async def check_plugin_update(
    instance_id: str,
    plugin_id: str,
    request: Request,
    _user: Annotated[User, Depends(require_roles("admin", "operator"))],
) -> dict[str, object]:
    if not request.app.state.instance_store.get(instance_id):
        raise HTTPException(status_code=404, detail="Instance not found")
    try:
        return await request.app.state.plugin_store.check_url_update(
            instance_id, plugin_id
        )
    except (OSError, ValueError, httpx.HTTPError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
