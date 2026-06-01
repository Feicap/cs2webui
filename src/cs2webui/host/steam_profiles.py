"""Optional Steam Web API profile enrichment."""

from typing import Protocol

import httpx


class SteamProfiles(Protocol):
    async def fetch(self, steam_ids: list[str]) -> dict[str, dict[str, str]]:
        """Fetch public summaries keyed by SteamID64."""


class SteamProfileClient:
    endpoint = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key

    async def fetch(self, steam_ids: list[str]) -> dict[str, dict[str, str]]:
        if not self._api_key or not steam_ids:
            return {}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                self.endpoint,
                params={"key": self._api_key, "steamids": ",".join(steam_ids[:100])},
            )
            response.raise_for_status()
        payload = response.json()
        try:
            players = payload["response"]["players"]
        except (KeyError, TypeError) as error:
            raise ValueError("Steam profile response is invalid") from error
        if not isinstance(players, list):
            raise ValueError("Steam profile response is invalid")
        profiles: dict[str, dict[str, str]] = {}
        for player in players:
            if not isinstance(player, dict):
                raise ValueError("Steam profile response is invalid")
            steam_id = player.get("steamid")
            profile_url = player.get("profileurl")
            avatar_url = player.get("avatarfull", "")
            display_name = player.get("personaname", "")
            if not isinstance(steam_id, str) or not isinstance(profile_url, str):
                raise ValueError("Steam profile response is invalid")
            if not isinstance(avatar_url, str) or not isinstance(display_name, str):
                raise ValueError("Steam profile response is invalid")
            profiles[steam_id] = {
                "profileUrl": profile_url,
                "avatarUrl": avatar_url,
                "displayName": display_name,
            }
        return profiles
