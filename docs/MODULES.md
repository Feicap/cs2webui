# Third-Party Modules

[Русская версия](MODULES.ru.md)

CS2 WebUI modules add optional API routes and, when useful, an independent UI
page. A module must not import or call another optional module. Use core app
state or a documented capability instead, and degrade gracefully when an
optional integration is unavailable.

## Minimal Package

Expose a zero-argument factory through the `cs2webui.modules` Python entry
point group:

```toml
[project.entry-points."cs2webui.modules"]
simpleadmin = "cs2webui_simpleadmin:build_module"
```

```python
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from cs2webui.modules.base import ModuleManifest


class SimpleAdminModule:
    manifest = ModuleManifest(
        id="simpleadmin-settings",
        name="SimpleAdmin Settings",
        version="0.1.0",
        description="Convenience editor for SimpleAdmin.",
        capabilities=("simpleadmin.settings",),
        ui_path="/modules/simpleadmin",
        navigation_label="SimpleAdmin",
    )

    def router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/modules/simpleadmin", response_class=HTMLResponse)
        async def page() -> str:
            return "<h1>SimpleAdmin</h1>"

        return router


def build_module() -> SimpleAdminModule:
    return SimpleAdminModule()
```

Install the Python package into the panel environment and restart the panel.
The core discovers it through the entry point. `ui_path` and
`navigation_label` are optional; API-only modules may omit them.

## Manifest Contract

- `id`: stable unique identifier.
- `name`: human-readable module name.
- `version`: module version.
- `description`: short purpose.
- `capabilities`: stable feature identifiers exposed by the module.
- `ui_path`: optional same-origin page shown in a sandboxed iframe.
- `navigation_label`: optional sidebar label for `ui_path`.

The iframe receives the normal panel session cookie for same-origin API calls.
Modules must still enforce roles on every sensitive API route.

## Failure Isolation

Third-party modules are optional by contract. If entry-point loading or router
mounting raises an exception, the core logs the failure, keeps serving the
panel, and reports the module as unavailable through `GET /api/modules`.
Module authors should still catch integration-level errors inside their own
routes and return a controlled degraded state where possible.
