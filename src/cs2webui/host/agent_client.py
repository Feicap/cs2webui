"""Panel-side client for the local Unix-socket host agent."""

from pathlib import Path

import httpx

from cs2webui.host.lifecycle import PlannedCommand


class AgentUnavailableError(RuntimeError):
    pass


class AgentClient:
    def __init__(self, socket_path: Path, token_path: Path) -> None:
        self._socket_path = socket_path
        self._token_path = token_path

    async def execute(self, command: PlannedCommand) -> dict[str, object]:
        if not self._socket_path.exists() or not self._token_path.exists():
            raise AgentUnavailableError("Host agent is not available")
        transport = httpx.AsyncHTTPTransport(uds=str(self._socket_path))
        headers = {"X-CS2WebUI-Token": self._token_path.read_text().strip()}
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://agent") as client:
                response = await client.post(
                    "/execute",
                    headers=headers,
                    json={"arguments": list(command.arguments)},
                    timeout=3605,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as error:
            raise AgentUnavailableError("Host agent request failed") from error

    async def import_server(
        self, mode: str, source: str, destination: str
    ) -> dict[str, object]:
        if not self._socket_path.exists() or not self._token_path.exists():
            raise AgentUnavailableError("Host agent is not available")
        transport = httpx.AsyncHTTPTransport(uds=str(self._socket_path))
        headers = {"X-CS2WebUI-Token": self._token_path.read_text().strip()}
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://agent") as client:
                response = await client.post(
                    "/import-server",
                    headers=headers,
                    json={"mode": mode, "source": source, "destination": destination},
                    timeout=3605,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as error:
            raise AgentUnavailableError("Host agent import request failed") from error

    async def container_logs(self, container_name: str, tail: int = 200) -> dict[str, object]:
        return await self._get(f"/containers/{container_name}/logs", params={"tail": tail})

    async def container_stats(self, container_name: str) -> dict[str, object]:
        return await self._get(f"/containers/{container_name}/stats")

    async def health(self) -> dict[str, object]:
        return await self._get("/health")

    async def delete_server(self, destination: str) -> dict[str, object]:
        if not self._socket_path.exists() or not self._token_path.exists():
            raise AgentUnavailableError("Host agent is not available")
        transport = httpx.AsyncHTTPTransport(uds=str(self._socket_path))
        headers = {"X-CS2WebUI-Token": self._token_path.read_text().strip()}
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://agent") as client:
                response = await client.post(
                    "/delete-server",
                    headers=headers,
                    json={"destination": destination},
                    timeout=35,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as error:
            raise AgentUnavailableError("Host agent delete request failed") from error

    async def _get(
        self, path: str, *, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        if not self._socket_path.exists() or not self._token_path.exists():
            raise AgentUnavailableError("Host agent is not available")
        transport = httpx.AsyncHTTPTransport(uds=str(self._socket_path))
        headers = {"X-CS2WebUI-Token": self._token_path.read_text().strip()}
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://agent") as client:
                response = await client.get(
                    path, params=params, headers=headers, timeout=35
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as error:
            raise AgentUnavailableError("Host agent request failed") from error
