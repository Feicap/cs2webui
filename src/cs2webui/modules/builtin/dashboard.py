"""Optional dashboard backed by Valve A2S_INFO queries."""

import asyncio

from fastapi import APIRouter, Depends, Request

from cs2webui.api.auth import require_roles
from cs2webui.core.bridge import bridge_snapshot_status
from cs2webui.core.auth import User
from cs2webui.host.agent_client import AgentUnavailableError
from cs2webui.host.a2s import A2sError
from cs2webui.host.rcon import RconError
from cs2webui.modules.base import ModuleManifest


class DashboardModule:
    manifest = ModuleManifest(
        id="dashboard",
        name="Dashboard",
        version="0.1.0",
        description="Optional server overview module.",
        capabilities=("dashboard.summary",),
    )

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

        @router.get("/summary")
        async def summary(
            request: Request,
            _user: User = Depends(require_roles("admin", "operator", "viewer")),
        ) -> dict[str, object]:
            summaries = []
            try:
                await request.app.state.agent_client.health()
                agent_status = "available"
            except AgentUnavailableError:
                agent_status = "unavailable"
            for instance in request.app.state.instance_store.list():
                try:
                    info = await asyncio.to_thread(
                        request.app.state.a2s_client.query_info,
                        request.app.state.settings.game_host,
                        instance.game_port,
                    )
                    query_status = "online"
                    server = info.as_dict()
                except (A2sError, OSError):
                    query_status = "offline"
                    server = None
                try:
                    await asyncio.to_thread(
                        request.app.state.rcon_client.execute,
                        request.app.state.settings.game_host,
                        instance.game_port,
                        request.app.state.instance_store.rcon_password(instance.id),
                        "status",
                    )
                    rcon_status = "available"
                except (RconError, OSError):
                    rcon_status = "unavailable"
                summaries.append(
                    {
                        "instance": instance.as_dict(),
                        "query_status": query_status,
                        "rcon_status": rcon_status,
                        "bridge_status": bridge_snapshot_status(instance.server_dir),
                        "server": server,
                    }
                )
            return {
                "instances": summaries,
                "host": request.app.state.metrics_client.read().as_dict(),
                "integrations": {
                    "host_agent": agent_status,
                    "steam_web_api": (
                        "configured"
                        if request.app.state.settings.steam_web_api_key
                        else "disabled"
                    ),
                },
            }

        return router
