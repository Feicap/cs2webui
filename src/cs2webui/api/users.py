"""Local user and audit administration."""

import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from cs2webui.api.auth import require_roles
from cs2webui.core.auth import User

router = APIRouter(prefix="/api", tags=["administration"])


class UserPayload(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)
    role: Literal["viewer", "operator", "admin"]


@router.get("/users")
async def users(
    request: Request,
    _user: Annotated[User, Depends(require_roles("admin"))],
) -> list[dict[str, str | int]]:
    return [
        {"id": user.id, "username": user.username, "role": user.role}
        for user in request.app.state.auth_store.users()
    ]


@router.post("/users", status_code=201)
async def create_user(
    payload: UserPayload,
    request: Request,
    actor: Annotated[User, Depends(require_roles("admin"))],
) -> dict[str, str | int]:
    try:
        user = request.app.state.auth_store.create_user(**payload.model_dump())
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Username already exists") from error
    request.app.state.audit_store.record(
        "user.created", f"actor={actor.username};username={user.username};role={user.role}"
    )
    return {"id": user.id, "username": user.username, "role": user.role}


@router.get("/audit")
async def audit(
    request: Request,
    _user: Annotated[User, Depends(require_roles("admin"))],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, str | int]]:
    return [entry.as_dict() for entry in request.app.state.audit_store.recent(limit)]
