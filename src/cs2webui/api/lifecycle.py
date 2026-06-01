"""Reviewable lifecycle plans for Linux Podman operations."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
import httpx

from cs2webui.api.auth import require_roles
from cs2webui.core.auth import User
from cs2webui.host.agent_client import AgentUnavailableError

router = APIRouter(prefix="/api/instances", tags=["lifecycle"])


def _container_name(slug: str) -> str:
    return f"cs2webui-{slug}"


@router.get("/{instance_id}/plans/{operation}")
async def operation_plan(
    instance_id: str,
    operation: Literal["install", "start", "stop"],
    request: Request,
    _user: Annotated[User, Depends(require_roles("admin", "operator"))],
) -> dict[str, object]:
    instance = request.app.state.instance_store.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if operation == "start" and instance.status != "running":
        report = request.app.state.diagnostics.inspect_udp(instance.game_port, 1)
        if not report.ports[0].available:
            raise HTTPException(
                status_code=409, detail="Selected game port is already in use"
            )
    planner = request.app.state.lifecycle_planner
    commands = getattr(planner, operation)(instance)
    return {
        "instance_id": instance.id,
        "operation": operation,
        "commands": [command.as_dict() for command in commands],
    }


@router.post("/{instance_id}/actions/{operation}")
async def execute_operation(
    instance_id: str,
    operation: Literal["install", "start", "stop"],
    request: Request,
    actor: Annotated[User, Depends(require_roles("admin", "operator"))],
) -> dict[str, object]:
    if operation == "install" and actor.role != "admin":
        raise HTTPException(
            status_code=403, detail="Only administrators can install server files"
        )
    instance = request.app.state.instance_store.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if operation == "start" and instance.status != "running":
        report = request.app.state.diagnostics.inspect_udp(instance.game_port, 1)
        if not report.ports[0].available:
            raise HTTPException(
                status_code=409, detail="Selected game port is already in use"
            )
    planner = request.app.state.lifecycle_planner
    if operation == "start":
        commands = planner.start(instance, masked=False)
    else:
        commands = getattr(planner, operation)(instance)
    results = []
    try:
        if operation == "install" and instance.install_source != "steamcmd":
            await request.app.state.agent_client.import_server(
                instance.install_source,
                instance.source_path,
                instance.server_dir,
            )
        for command in commands:
            result = await request.app.state.agent_client.execute(command)
            results.append(result)
            if result["returncode"] != 0:
                request.app.state.instance_store.set_status(instance.id, "failed")
                break
    except AgentUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if results and all(result["returncode"] == 0 for result in results):
        status = {"install": "installed", "start": "running", "stop": "stopped"}[
            operation
        ]
        request.app.state.instance_store.set_status(instance.id, status)
    prerequisites = []
    if operation == "install" and results and all(result["returncode"] == 0 for result in results):
        if (
            instance.metamod_enabled
            and not request.app.state.plugin_store.has_plugin_named(
                instance.id, "MetaMod:Source"
            )
        ):
            try:
                plugin = await request.app.state.plugin_store.install_builtin_metamod(
                    instance
                )
                prerequisites.append({"component": "metamod", "status": "installed", "plugin": plugin.as_dict()})
            except (OSError, ValueError, httpx.HTTPError) as error:
                prerequisites.append({"component": "metamod", "status": "unavailable", "detail": str(error)})
        if (
            instance.counterstrikesharp_enabled
            and not request.app.state.plugin_store.has_plugin_named(
                instance.id, "CounterStrikeSharp"
            )
        ):
            try:
                plugin = (
                    await request.app.state.plugin_store.install_builtin_counterstrikesharp(
                        instance
                    )
                )
                prerequisites.append({"component": "counterstrikesharp", "status": "installed", "plugin": plugin.as_dict()})
            except (OSError, ValueError, httpx.HTTPError) as error:
                prerequisites.append({"component": "counterstrikesharp", "status": "unavailable", "detail": str(error)})
    bridge = None
    if (
        operation == "install"
        and results
        and all(result["returncode"] == 0 for result in results)
        and instance.bridge_enabled
        and not request.app.state.plugin_store.has_builtin_bridge(instance.id)
    ):
        try:
            plugin = request.app.state.plugin_store.install_builtin_bridge(instance)
            bridge = {"status": "installed", "plugin": plugin.as_dict()}
        except ValueError as error:
            bridge = {"status": "unavailable", "detail": str(error)}
    request.app.state.audit_store.record(
        f"instance.{operation}",
        f"actor={actor.username};instance={instance.id}",
    )
    return {
        "instance_id": instance.id,
        "operation": operation,
        "results": results,
        "prerequisites": prerequisites,
        "bridge": bridge,
    }


@router.get("/{instance_id}/logs")
async def instance_logs(
    instance_id: str,
    request: Request,
    _user: Annotated[User, Depends(require_roles("admin", "operator", "viewer"))],
) -> dict[str, object]:
    instance = request.app.state.instance_store.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    try:
        return await request.app.state.agent_client.container_logs(
            _container_name(instance.slug)
        )
    except AgentUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/{instance_id}/stats")
async def instance_stats(
    instance_id: str,
    request: Request,
    _user: Annotated[User, Depends(require_roles("admin", "operator", "viewer"))],
) -> dict[str, object]:
    instance = request.app.state.instance_store.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    try:
        return await request.app.state.agent_client.container_stats(
            _container_name(instance.slug)
        )
    except AgentUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
