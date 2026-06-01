"""Core API routes that stay available without optional modules."""

from typing import Any

from fastapi import APIRouter, Request

from cs2webui import __version__

router = APIRouter(prefix="/api", tags=["core"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/modules")
async def modules(request: Request) -> list[dict[str, Any]]:
    registry = request.app.state.module_registry
    return registry.describe()
