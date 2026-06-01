"""Backup and scheduled maintenance configuration API."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from cs2webui.api.auth import require_roles
from cs2webui.core.auth import User
from cs2webui.core.maintenance import MaintenancePolicy

router = APIRouter(prefix="/api/instances", tags=["maintenance"])


class MaintenancePayload(BaseModel):
    restart_every_minutes: int | None = Field(default=None, ge=5, le=525600)
    update_before_restart: bool = False
    defer_while_players_online: bool = True
    max_defer_minutes: int = Field(default=120, ge=0, le=10080)
    backup_before_update: bool = True
    notify_before_minutes: int = Field(default=10, ge=0, le=1440)


def get_instance(request: Request, instance_id: str):
    instance = request.app.state.instance_store.get(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    return instance


@router.get("/notices")
async def notices(
    request: Request,
    _user: Annotated[User, Depends(require_roles("admin", "operator", "viewer"))],
) -> list[dict[str, str | int | bool | None]]:
    result = []
    for instance in request.app.state.instance_store.list():
        status = request.app.state.maintenance_store.status(instance.id)
        if status["warning"]:
            result.append({"instance_name": instance.name, **status})
    return result


@router.get("/{instance_id}/backups")
async def backups(
    instance_id: str,
    request: Request,
    _user: Annotated[User, Depends(require_roles("admin", "operator", "viewer"))],
) -> list[dict[str, str | int]]:
    return [
        backup.as_dict()
        for backup in request.app.state.backup_store.list(
            get_instance(request, instance_id)
        )
    ]


@router.post("/{instance_id}/backups", status_code=201)
async def create_backup(
    instance_id: str,
    request: Request,
    actor: Annotated[User, Depends(require_roles("admin", "operator"))],
) -> dict[str, str | int]:
    backup = request.app.state.backup_store.create(get_instance(request, instance_id))
    request.app.state.audit_store.record(
        "instance.backup.created", f"actor={actor.username};instance={instance_id}"
    )
    return backup.as_dict()


@router.post("/{instance_id}/backups/{backup_name}/restore")
async def restore_backup(
    instance_id: str,
    backup_name: str,
    request: Request,
    actor: Annotated[User, Depends(require_roles("admin"))],
) -> dict[str, str | int]:
    try:
        backup = request.app.state.backup_store.restore(
            get_instance(request, instance_id), backup_name
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    request.app.state.audit_store.record(
        "instance.backup.restored",
        f"actor={actor.username};instance={instance_id};backup={backup.name}",
    )
    return backup.as_dict()


@router.get("/{instance_id}/maintenance")
async def maintenance(
    instance_id: str,
    request: Request,
    _user: Annotated[User, Depends(require_roles("admin", "operator", "viewer"))],
) -> dict[str, str | int | bool | None]:
    get_instance(request, instance_id)
    return request.app.state.maintenance_store.status(instance_id)


@router.put("/{instance_id}/maintenance")
async def save_maintenance(
    instance_id: str,
    payload: MaintenancePayload,
    request: Request,
    actor: Annotated[User, Depends(require_roles("admin"))],
) -> dict[str, str | int | bool | None]:
    get_instance(request, instance_id)
    policy = MaintenancePolicy(instance_id=instance_id, **payload.model_dump())
    request.app.state.maintenance_store.save(policy)
    request.app.state.audit_store.record(
        "instance.maintenance.updated",
        f"actor={actor.username};instance={instance_id}",
    )
    return policy.as_dict()


@router.post("/{instance_id}/maintenance/run")
async def run_maintenance(
    instance_id: str,
    request: Request,
    actor: Annotated[User, Depends(require_roles("admin"))],
) -> dict[str, str]:
    get_instance(request, instance_id)
    result = await request.app.state.maintenance_runner.run(
        request.app.state.maintenance_store.get(instance_id)
    )
    request.app.state.audit_store.record(
        "instance.maintenance.run",
        f"actor={actor.username};instance={instance_id};status={result['status']}",
    )
    return result
