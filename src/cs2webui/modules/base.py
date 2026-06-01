"""Public interfaces used by built-in and third-party modules."""

from dataclasses import dataclass, field
from typing import Protocol

from fastapi import APIRouter


@dataclass(frozen=True, slots=True)
class ModuleManifest:
    """Stable metadata exposed by a panel module."""

    id: str
    name: str
    version: str
    description: str
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    ui_path: str | None = None
    navigation_label: str | None = None


class Module(Protocol):
    """Small public contract for feature modules."""

    manifest: ModuleManifest

    def router(self) -> APIRouter | None:
        """Return API routes contributed by this module."""
