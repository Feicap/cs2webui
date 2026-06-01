"""Discovery and registration for optional panel modules."""

from importlib.metadata import entry_points
import logging
from typing import Any

from fastapi import FastAPI

from cs2webui.modules.base import Module

ENTRY_POINT_GROUP = "cs2webui.modules"
logger = logging.getLogger(__name__)


class ModuleRegistry:
    """Owns enabled feature modules and mounts their public routes."""

    def __init__(self) -> None:
        self._modules: dict[str, Module] = {}
        self._failures: list[dict[str, Any]] = []

    def register(self, module: Module) -> None:
        module_id = module.manifest.id
        if module_id in self._modules:
            raise ValueError(f"Module already registered: {module_id}")
        self._modules[module_id] = module

    def discover(self) -> None:
        for entry_point in entry_points(group=ENTRY_POINT_GROUP):
            try:
                module_factory = entry_point.load()
                self.register(module_factory())
            except Exception:
                logger.exception("Optional module discovery failed: %s", entry_point.name)
                self._failures.append(self._failure(entry_point.name))

    def mount(self, app: FastAPI) -> None:
        for module_id, module in list(self._modules.items()):
            try:
                router = module.router()
                if router is not None:
                    app.include_router(router)
            except Exception:
                logger.exception("Optional module mount failed: %s", module_id)
                self._failures.append(
                    self._failure(module_id, name=module.manifest.name)
                )
                del self._modules[module_id]

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "id": module.manifest.id,
                "name": module.manifest.name,
                "version": module.manifest.version,
                "description": module.manifest.description,
                "capabilities": list(module.manifest.capabilities),
                "ui_path": module.manifest.ui_path,
                "navigation_label": module.manifest.navigation_label,
                "status": "available",
            }
            for module in self._modules.values()
        ] + self._failures

    @staticmethod
    def _failure(module_id: str, *, name: str | None = None) -> dict[str, Any]:
        return {
            "id": module_id,
            "name": name or module_id,
            "version": None,
            "description": "Optional module failed to load. Check panel logs.",
            "capabilities": [],
            "ui_path": None,
            "navigation_label": None,
            "status": "unavailable",
        }
