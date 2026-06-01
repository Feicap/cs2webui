"""Optional Workshop map library module."""

from dataclasses import asdict, dataclass, replace
from ipaddress import ip_address
from pathlib import Path
import re
import socket
import sqlite3
from typing import Protocol
from urllib.parse import parse_qs, urljoin, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
import httpx
from pydantic import BaseModel, Field

from cs2webui.api.auth import require_roles
from cs2webui.core.auth import User
from cs2webui.modules.base import ModuleManifest

_workshop_id = re.compile(r"^[0-9]{1,20}$")
_preview_media_types = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_PREVIEW_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class WorkshopMap:
    published_file_id: str
    title: str
    preview_url: str | None
    workshop_url: str

    def as_dict(self) -> dict[str, str | None]:
        return asdict(self)


class WorkshopMetadataClient(Protocol):
    async def fetch(self, published_file_id: str) -> WorkshopMap:
        """Fetch one map from the public Steam Workshop metadata endpoint."""

    async def fetch_collection(self, published_file_id: str) -> list[str]:
        """Return independent child IDs from one Workshop collection."""


class SteamWorkshopClient:
    endpoint = (
        "https://api.steampowered.com/"
        "ISteamRemoteStorage/GetPublishedFileDetails/v1/"
    )
    collection_endpoint = (
        "https://api.steampowered.com/"
        "ISteamRemoteStorage/GetCollectionDetails/v1/"
    )

    async def fetch(self, published_file_id: str) -> WorkshopMap:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                self.endpoint,
                data={
                    "itemcount": "1",
                    "publishedfileids[0]": published_file_id,
                },
            )
            response.raise_for_status()
        try:
            details = response.json()["response"]["publishedfiledetails"][0]
        except (KeyError, TypeError, IndexError) as error:
            raise ValueError("Workshop map response is invalid") from error
        if not isinstance(details, dict):
            raise ValueError("Workshop map response is invalid")
        if details.get("result") != 1:
            raise ValueError("Workshop map is not available")
        title = details.get("title") or f"Workshop {published_file_id}"
        preview_url = details.get("preview_url")
        if not isinstance(title, str) or (
            preview_url is not None and not isinstance(preview_url, str)
        ):
            raise ValueError("Workshop map response is invalid")
        return WorkshopMap(
            published_file_id=published_file_id,
            title=title,
            preview_url=preview_url,
            workshop_url=workshop_url(published_file_id),
        )

    async def fetch_collection(self, published_file_id: str) -> list[str]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                self.collection_endpoint,
                data={
                    "collectioncount": "1",
                    "publishedfileids[0]": published_file_id,
                },
            )
            response.raise_for_status()
        try:
            details = response.json()["response"]["collectiondetails"][0]
        except (KeyError, TypeError, IndexError) as error:
            raise ValueError("Workshop collection response is invalid") from error
        if not isinstance(details, dict):
            raise ValueError("Workshop collection response is invalid")
        if details.get("result") != 1:
            raise ValueError("Workshop collection is not available")
        children = details.get("children", [])
        if not isinstance(children, list):
            raise ValueError("Workshop collection response is invalid")
        published_file_ids = []
        for child in children:
            if not isinstance(child, dict):
                raise ValueError("Workshop collection response is invalid")
            published_file_id = child.get("publishedfileid")
            if not isinstance(published_file_id, str) or not _workshop_id.fullmatch(
                published_file_id
            ):
                raise ValueError("Workshop collection response is invalid")
            published_file_ids.append(published_file_id)
        return published_file_ids


class WorkshopStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS workshop_maps (
                    published_file_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    preview_url TEXT,
                    workshop_url TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def list(self) -> list[WorkshopMap]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT published_file_id, title, preview_url, workshop_url
                FROM workshop_maps ORDER BY title
                """
            ).fetchall()
        return [WorkshopMap(**dict(row)) for row in rows]

    def save(self, workshop_map: WorkshopMap) -> WorkshopMap:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workshop_maps (
                    published_file_id, title, preview_url, workshop_url
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(published_file_id) DO UPDATE SET
                    title = excluded.title,
                    preview_url = excluded.preview_url,
                    workshop_url = excluded.workshop_url
                """,
                (
                    workshop_map.published_file_id,
                    workshop_map.title,
                    workshop_map.preview_url,
                    workshop_map.workshop_url,
                ),
            )
        return workshop_map

    def get(self, published_file_id: str) -> WorkshopMap | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT published_file_id, title, preview_url, workshop_url
                FROM workshop_maps WHERE published_file_id = ?
                """,
                (published_file_id,),
            ).fetchone()
        return WorkshopMap(**dict(row)) if row else None


class WorkshopPayload(BaseModel):
    source: str = Field(min_length=1, max_length=512)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    preview_url: str | None = Field(default=None, max_length=1024)
    cache_preview: bool = False


def extract_workshop_id(source: str) -> str:
    value = source.strip()
    if _workshop_id.fullmatch(value):
        return value
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc not in {
        "steamcommunity.com",
        "www.steamcommunity.com",
    }:
        raise ValueError("Use a Steam Community Workshop URL or numeric ID")
    published_file_id = parse_qs(parsed.query).get("id", [""])[0]
    if not _workshop_id.fullmatch(published_file_id):
        raise ValueError("Workshop URL does not contain a valid id")
    return published_file_id


def workshop_url(published_file_id: str) -> str:
    return (
        "https://steamcommunity.com/sharedfiles/filedetails/"
        f"?id={published_file_id}"
    )


def manual_workshop_map(
    published_file_id: str, title: str | None, preview_url: str | None
) -> WorkshopMap:
    if not title:
        raise ValueError("Steam metadata is unavailable; provide a manual title")
    if preview_url and urlparse(preview_url).scheme != "https":
        raise ValueError("Manual preview URL must use https")
    return WorkshopMap(
        published_file_id=published_file_id,
        title=title,
        preview_url=preview_url,
        workshop_url=workshop_url(published_file_id),
    )


class WorkshopModule:
    manifest = ModuleManifest(
        id="workshop-library",
        name="Workshop Library",
        version="0.1.0",
        description="Optional Steam Workshop map cards and commands.",
        capabilities=("maps.workshop",),
    )

    def __init__(
        self, database_path: Path, metadata_client: WorkshopMetadataClient | None = None
    ) -> None:
        self._store = WorkshopStore(database_path)
        self._metadata = metadata_client or SteamWorkshopClient()
        self._media_dir = database_path.parent / "workshop-media"
        self._media_dir.mkdir(parents=True, exist_ok=True)
        self._metadata_status = "unknown"

    @staticmethod
    def _validate_preview_url(source: str) -> None:
        parsed = urlparse(source)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Preview URL must use https")
        for result in socket.getaddrinfo(parsed.hostname, 443):
            if not ip_address(result[4][0]).is_global:
                raise ValueError("Preview URL resolves to a non-public address")

    async def _cache_preview(self, workshop_map: WorkshopMap) -> WorkshopMap:
        if not workshop_map.preview_url:
            return workshop_map
        current = workshop_map.preview_url
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            for _ in range(3):
                self._validate_preview_url(current)
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("Preview redirect is missing location")
                        current = urljoin(current, location)
                        continue
                    response.raise_for_status()
                    media_type = response.headers.get("content-type", "").split(";")[0]
                    suffix = _preview_media_types.get(media_type)
                    if not suffix:
                        raise ValueError("Preview URL must return a supported image")
                    target = self._media_dir / f"{workshop_map.published_file_id}{suffix}"
                    total = 0
                    with target.open("wb") as output:
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > MAX_PREVIEW_BYTES:
                                target.unlink(missing_ok=True)
                                raise ValueError("Workshop preview exceeds size limit")
                            output.write(chunk)
                    return replace(
                        workshop_map,
                        preview_url=(
                            "/api/workshop/media/"
                            f"{workshop_map.published_file_id}"
                        ),
                    )
        raise ValueError("Preview URL has too many redirects")

    def _media_path(self, published_file_id: str) -> Path | None:
        if not _workshop_id.fullmatch(published_file_id):
            return None
        return next(self._media_dir.glob(f"{published_file_id}.*"), None)

    def _save_uploaded_preview(
        self, published_file_id: str, content: bytes, media_type: str
    ) -> WorkshopMap:
        workshop_map = self._store.get(published_file_id)
        if not workshop_map:
            raise ValueError("Workshop map not found")
        suffix = _preview_media_types.get(media_type)
        if not suffix:
            raise ValueError("Preview upload must be a supported image")
        if len(content) > MAX_PREVIEW_BYTES:
            raise ValueError("Workshop preview exceeds size limit")
        for previous in self._media_dir.glob(f"{published_file_id}.*"):
            previous.unlink(missing_ok=True)
        (self._media_dir / f"{published_file_id}{suffix}").write_bytes(content)
        return self._store.save(
            replace(
                workshop_map,
                preview_url=f"/api/workshop/media/{published_file_id}",
            )
        )

    async def _read_uploaded_preview(self, request: Request) -> bytes:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_PREVIEW_BYTES:
                    raise ValueError("Workshop preview exceeds size limit")
            except ValueError as error:
                if str(error) == "Workshop preview exceeds size limit":
                    raise
                raise ValueError("Invalid Content-Length header") from error
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_PREVIEW_BYTES:
                raise ValueError("Workshop preview exceeds size limit")
        return bytes(content)

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/api/workshop", tags=["workshop"])

        @router.get("/maps")
        async def maps(
            _user: User = Depends(require_roles("admin", "operator", "viewer")),
        ) -> list[dict[str, str | None]]:
            return [workshop_map.as_dict() for workshop_map in self._store.list()]

        @router.get("/status")
        async def status(
            _user: User = Depends(require_roles("admin", "operator", "viewer")),
        ) -> dict[str, str]:
            return {"steam_workshop_api": self._metadata_status}

        @router.post("/maps", status_code=201)
        async def add_map(
            payload: WorkshopPayload,
            _user: User = Depends(require_roles("admin", "operator")),
        ) -> dict[str, str | None]:
            try:
                published_file_id = extract_workshop_id(payload.source)
                try:
                    workshop_map = await self._metadata.fetch(published_file_id)
                    self._metadata_status = "available"
                except (ValueError, httpx.HTTPError):
                    self._metadata_status = "unavailable"
                    workshop_map = manual_workshop_map(
                        published_file_id, payload.title, payload.preview_url
                    )
                if payload.cache_preview:
                    workshop_map = await self._cache_preview(workshop_map)
            except (ValueError, httpx.HTTPError) as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            return self._store.save(workshop_map).as_dict()

        @router.get("/media/{published_file_id}", response_class=FileResponse)
        async def media(
            published_file_id: str,
            _user: User = Depends(require_roles("admin", "operator", "viewer")),
        ) -> FileResponse:
            path = self._media_path(published_file_id)
            if not path:
                raise HTTPException(status_code=404, detail="Cached preview not found")
            return FileResponse(path)

        @router.put("/media/{published_file_id}")
        async def upload_media(
            published_file_id: str,
            request: Request,
            _user: User = Depends(require_roles("admin", "operator")),
        ) -> dict[str, str | None]:
            if not _workshop_id.fullmatch(published_file_id):
                raise HTTPException(status_code=422, detail="Invalid Workshop id")
            try:
                workshop_map = self._save_uploaded_preview(
                    published_file_id,
                    await self._read_uploaded_preview(request),
                    request.headers.get("content-type", "").split(";")[0],
                )
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            return workshop_map.as_dict()

        @router.get("/maps/{published_file_id}/command")
        async def command(
            published_file_id: str,
            _user: User = Depends(require_roles("admin", "operator")),
        ) -> dict[str, str]:
            try:
                validated_id = extract_workshop_id(published_file_id)
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            return {"command": f"host_workshop_map {validated_id}"}

        @router.post("/collections", status_code=201)
        async def import_collection(
            payload: WorkshopPayload,
            _user: User = Depends(require_roles("admin", "operator")),
        ) -> list[dict[str, str | None]]:
            try:
                collection_id = extract_workshop_id(payload.source)
                child_ids = await self._metadata.fetch_collection(collection_id)
                self._metadata_status = "available"
                imported = []
                for child_id in child_ids:
                    imported.append(self._store.save(await self._metadata.fetch(child_id)))
            except (ValueError, httpx.HTTPError) as error:
                self._metadata_status = "unavailable"
                raise HTTPException(status_code=422, detail=str(error)) from error
            return [workshop_map.as_dict() for workshop_map in imported]

        return router
