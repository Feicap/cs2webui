"""Session login API and role-aware dependencies."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from cs2webui.core.auth import User

SESSION_COOKIE = "cs2webui_session"
router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        max_age=7 * 24 * 60 * 60,
        samesite="strict",
        secure=request.app.state.settings.secure_cookies,
    )


async def current_user(
    request: Request,
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> User:
    user = request.app.state.auth_store.user_for_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_roles(*roles: str) -> Callable[[User], User]:
    async def dependency(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return dependency


@router.post("/login")
async def login(payload: LoginPayload, request: Request, response: Response) -> dict[str, str]:
    client_host = request.client.host if request.client else "unknown"
    rate_limit_key = f"{client_host}:{payload.username.lower()}"
    limiter = request.app.state.login_rate_limiter
    if not limiter.allows(rate_limit_key):
        raise HTTPException(status_code=429, detail="Too many login attempts")
    result = request.app.state.auth_store.login(payload.username, payload.password)
    if not result:
        limiter.record_failure(rate_limit_key)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    limiter.clear(rate_limit_key)
    token, user = result
    set_session_cookie(response, request, token)
    return {"username": user.username, "role": user.role}


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    request.app.state.auth_store.logout(token)
    response.delete_cookie(SESSION_COOKIE)


@router.get("/me")
async def me(user: Annotated[User, Depends(current_user)]) -> dict[str, str]:
    return {"username": user.username, "role": user.role}
