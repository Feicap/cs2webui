"""First-run setup API."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from cs2webui.api.auth import SESSION_COOKIE, set_session_cookie
router = APIRouter(prefix="/api/setup", tags=["setup"])


class LanguagePayload(BaseModel):
    language: Literal["en", "ru"]


class AccessPayload(BaseModel):
    mode: Literal["local", "domain", "ip"]
    domain: str | None = Field(
        default=None,
        max_length=253,
        pattern=(
            r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
        ),
    )


class PortPayload(BaseModel):
    port: int = Field(ge=1024, le=65535)


class AdminPayload(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)


def ensure_setup_is_open(request: Request) -> None:
    if request.app.state.setup_store.state().admin_created:
        raise HTTPException(status_code=403, detail="Initial setup is already complete")


def ensure_setup_is_open_or_admin(request: Request) -> None:
    if not request.app.state.setup_store.state().admin_created:
        return
    user = request.app.state.auth_store.user_for_token(
        request.cookies.get(SESSION_COOKIE)
    )
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required")


@router.get("/state")
async def state(request: Request) -> dict[str, object]:
    setup_state = request.app.state.setup_store.state()
    return {"completed": True} if setup_state.admin_created else setup_state.as_dict()


@router.put("/language")
async def language(payload: LanguagePayload, request: Request) -> dict[str, object]:
    ensure_setup_is_open(request)
    return request.app.state.setup_store.set_value(
        "language", payload.language
    ).as_dict()


@router.put("/access")
async def access(payload: AccessPayload, request: Request) -> dict[str, object]:
    ensure_setup_is_open(request)
    if payload.mode == "domain" and not payload.domain:
        raise HTTPException(status_code=422, detail="Domain is required")
    request.app.state.setup_store.set_value("access_mode", payload.mode)
    if payload.domain:
        request.app.state.setup_store.set_value("access_domain", payload.domain)
    return request.app.state.setup_store.state().as_dict()


@router.get("/diagnostics")
async def diagnostics(
    request: Request,
    start_port: Annotated[int, Query(ge=1024, le=65535)] = 8080,
    count: Annotated[int, Query(ge=1, le=50)] = 10,
) -> dict[str, object]:
    ensure_setup_is_open(request)
    if start_port + count > 65536:
        raise HTTPException(status_code=422, detail="Port range exceeds 65535")
    return request.app.state.diagnostics.inspect(start_port, count).as_dict()


@router.put("/port")
async def port(payload: PortPayload, request: Request) -> dict[str, object]:
    ensure_setup_is_open(request)
    report = request.app.state.diagnostics.inspect(payload.port, 1)
    if not report.ports[0].available:
        raise HTTPException(status_code=409, detail="Selected port is already in use")
    return request.app.state.setup_store.set_value(
        "webui_port", str(payload.port)
    ).as_dict()


@router.get("/access-plan")
async def access_plan(request: Request) -> dict[str, object]:
    ensure_setup_is_open_or_admin(request)
    state = request.app.state.setup_store.state()
    if not state.access_mode or not state.webui_port:
        raise HTTPException(status_code=409, detail="Access mode and WebUI port are required")
    if state.access_mode == "domain":
        return {
            "mode": "domain",
            "url": f"https://{state.access_domain}",
            "firewall_ports": [{"port": 80, "protocol": "tcp"}, {"port": 443, "protocol": "tcp"}],
            "caddyfile": f"{state.access_domain} {{\n  reverse_proxy 127.0.0.1:{state.webui_port}\n}}\n",
            "apply_command": (
                "sudo /var/lib/cs2webui-system/bin/apply-access.sh "
                f"--mode domain --domain {state.access_domain} "
                f"--webui-port {state.webui_port}"
            ),
        }
    return {
        "mode": state.access_mode,
        "url": f"http://SERVER_IP:{state.webui_port}",
        "firewall_ports": [{"port": state.webui_port, "protocol": "tcp"}],
        "caddyfile": None,
        "apply_command": (
            "sudo /var/lib/cs2webui-system/bin/apply-access.sh "
            f"--mode {state.access_mode} --webui-port {state.webui_port}"
        ),
    }


@router.post("/admin", status_code=201)
async def admin(
    payload: AdminPayload, request: Request, response: Response
) -> dict[str, object]:
    ensure_setup_is_open(request)
    state = request.app.state.setup_store.state()
    if not state.language or not state.access_mode or not state.webui_port:
        raise HTTPException(
            status_code=409,
            detail="Complete language, access mode, and WebUI port setup first",
        )
    try:
        state = request.app.state.setup_store.create_admin(
            payload.username, payload.password
        )
        result = request.app.state.auth_store.login(payload.username, payload.password)
        if not result:
            raise RuntimeError("Created administrator could not log in")
        token, _ = result
        set_session_cookie(response, request, token)
        return state.as_dict()
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
