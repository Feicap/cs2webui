"""Optional module isolation tests."""

from fastapi import APIRouter, FastAPI
import pytest

from cs2webui.modules.base import ModuleManifest
from cs2webui.modules.registry import ModuleRegistry


class _EntryPoint:
    name = "broken-discovery"

    def load(self):
        raise RuntimeError("discovery failed")


class _BrokenRouterModule:
    manifest = ModuleManifest(
        id="broken-router",
        name="Broken Router",
        version="0.1.0",
        description="Test module",
    )

    def router(self) -> APIRouter:
        raise RuntimeError("mount failed")


def test_registry_discovery_failure_does_not_break_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cs2webui.modules.registry.entry_points", lambda **_kwargs: [_EntryPoint()]
    )
    registry = ModuleRegistry()

    registry.discover()

    assert registry.describe() == [
        {
            "id": "broken-discovery",
            "name": "broken-discovery",
            "version": None,
            "description": "Optional module failed to load. Check panel logs.",
            "capabilities": [],
            "ui_path": None,
            "navigation_label": None,
            "status": "unavailable",
        }
    ]


def test_registry_mount_failure_does_not_break_core() -> None:
    registry = ModuleRegistry()
    registry.register(_BrokenRouterModule())

    registry.mount(FastAPI())

    assert registry.describe()[0]["id"] == "broken-router"
    assert registry.describe()[0]["status"] == "unavailable"
