"""Optional structured player list from the CounterStrikeSharp bridge."""

from pathlib import Path
import json

from fastapi import APIRouter, Depends, HTTPException, Request
import httpx

from cs2webui.api.auth import require_roles
from cs2webui.core.auth import User
from cs2webui.core.bridge import BRIDGE_STATE, bridge_snapshot_status
from cs2webui.modules.base import ModuleManifest


def _validate_players(raw_players: object) -> list[dict[str, object]]:
    if not isinstance(raw_players, list):
        raise ValueError("Bridge state must be a player list")
    players: list[dict[str, object]] = []
    for player in raw_players:
        if not isinstance(player, dict):
            raise ValueError("Bridge player must be an object")
        name = player.get("name")
        steam_id = player.get("steamId64")
        is_bot = player.get("isBot")
        team = player.get("team")
        score = player.get("score")
        if not isinstance(name, str):
            raise ValueError("Bridge player name must be a string")
        if isinstance(steam_id, bool) or not isinstance(steam_id, int) or steam_id < 0:
            raise ValueError("Bridge player SteamID64 must be a non-negative integer")
        if not isinstance(is_bot, bool):
            raise ValueError("Bridge player bot state must be a boolean")
        if isinstance(team, bool) or not isinstance(team, int):
            raise ValueError("Bridge player team must be an integer")
        if isinstance(score, bool) or not isinstance(score, int):
            raise ValueError("Bridge player score must be an integer")
        players.append(player)
    return players


class AdvancedPlayersModule:
    manifest = ModuleManifest(
        id="advanced-players",
        name="Advanced Players",
        version="0.1.0",
        description="Structured SteamID64 and bot state from the optional bridge.",
        capabilities=("bridge.players", "bridge.bots"),
    )

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/api/players", tags=["players"])

        @router.get("/{instance_id}")
        async def players(
            instance_id: str,
            request: Request,
            _user: User = Depends(require_roles("admin", "operator", "viewer")),
        ) -> dict[str, object]:
            instance = request.app.state.instance_store.get(instance_id)
            if not instance:
                raise HTTPException(status_code=404, detail="Instance not found")
            state_path = Path(instance.server_dir) / BRIDGE_STATE
            if not state_path.is_file():
                return {"status": "unavailable", "players": []}
            try:
                raw_players = _validate_players(
                    json.loads(state_path.read_text(encoding="utf-8"))
                )
            except (OSError, json.JSONDecodeError, ValueError) as error:
                raise HTTPException(status_code=502, detail="Bridge state is invalid") from error
            steam_ids = [
                str(player["steamId64"])
                for player in raw_players
                if not player["isBot"] and player["steamId64"]
            ]
            try:
                profiles = await request.app.state.steam_profiles.fetch(steam_ids)
                profile_status = (
                    "configured"
                    if request.app.state.settings.steam_web_api_key
                    else "disabled"
                )
            except (httpx.HTTPError, ValueError):
                profiles = {}
                profile_status = "unavailable"
            return {
                "status": bridge_snapshot_status(instance.server_dir),
                "steamProfileStatus": profile_status,
                "players": [
                    {
                        **player,
                        "steamProfileUrl": profiles.get(
                            str(player["steamId64"]), {}
                        ).get(
                            "profileUrl",
                            f"https://steamcommunity.com/profiles/{player['steamId64']}",
                        ),
                        "steamAvatarUrl": profiles.get(
                            str(player["steamId64"]), {}
                        ).get("avatarUrl"),
                    }
                    for player in raw_players
                ],
            }

        return router
