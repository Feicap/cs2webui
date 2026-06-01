"""FastAPI application factory."""

import asyncio
from contextlib import asynccontextmanager, suppress
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from cs2webui.api.core import router as core_router
from cs2webui.api.auth import router as auth_router
from cs2webui.api.instances import router as instances_router
from cs2webui.api.lifecycle import router as lifecycle_router
from cs2webui.api.console import router as console_router
from cs2webui.api.maintenance import router as maintenance_router
from cs2webui.api.plugins import router as plugins_router
from cs2webui.api.configuration import router as configuration_router
from cs2webui.api.users import router as users_router
from cs2webui.api.setup import router as setup_router
from cs2webui.core.instances import InstanceStore
from cs2webui.core.backups import BackupStore
from cs2webui.core.maintenance import MaintenanceStore
from cs2webui.core.maintenance_runner import MaintenanceRunner
from cs2webui.core.bridge_rotation import BridgeRotationRunner
from cs2webui.core.plugins import PluginStore
from cs2webui.core.quick_commands import QuickCommandStore
from cs2webui.core.configuration import ConfigurationStore
from cs2webui.core.auth import AuthStore, LoginRateLimiter
from cs2webui.core.audit import AuditStore
from cs2webui.core.secrets import SecretCipher
from cs2webui.core.settings import Settings
from cs2webui.core.setup import SetupStore
from cs2webui.host.diagnostics import SystemDiagnostics, default_diagnostics
from cs2webui.host.agent_client import AgentClient
from cs2webui.host.a2s import A2sClient
from cs2webui.host.lifecycle import LifecyclePlanner
from cs2webui.host.metrics import MetricsClient
from cs2webui.host.steam_profiles import SteamProfileClient, SteamProfiles
from cs2webui.host.rcon import RconClient
from cs2webui.modules.builtin.dashboard import DashboardModule
from cs2webui.modules.builtin.workshop import (
    SteamWorkshopClient,
    WorkshopMetadataClient,
    WorkshopModule,
)
from cs2webui.modules.builtin.rotation import RotationModule
from cs2webui.modules.builtin.players import AdvancedPlayersModule
from cs2webui.modules.registry import ModuleRegistry

logger = logging.getLogger(__name__)


def create_app(
    *,
    enable_dashboard: bool = True,
    enable_workshop: bool = True,
    enable_rotation: bool = True,
    enable_players: bool = True,
    settings: Settings | None = None,
    diagnostics: SystemDiagnostics | None = None,
    agent_client: AgentClient | None = None,
    rcon_client: RconClient | None = None,
    workshop_client: WorkshopMetadataClient | None = None,
    a2s_client: A2sClient | None = None,
    steam_profiles: SteamProfiles | None = None,
) -> FastAPI:
    """Build an application with independently registered feature modules."""
    settings = settings or Settings.from_environment()
    setup_store = SetupStore(settings.database_path)
    auth_store = AuthStore(settings.database_path)
    audit_store = AuditStore(settings.database_path)
    cipher = SecretCipher(settings.secret_key_path)
    instance_store = InstanceStore(
        settings.database_path, settings.instances_dir, cipher
    )
    backup_store = BackupStore()
    maintenance_store = MaintenanceStore(settings.database_path)
    plugin_store = PluginStore(settings.database_path, settings.imports_dir)
    quick_command_store = QuickCommandStore(settings.database_path)
    configuration_store = ConfigurationStore()
    lifecycle_planner = LifecyclePlanner(instance_store)
    registry = ModuleRegistry()
    if enable_dashboard:
        registry.register(DashboardModule())
    if enable_workshop:
        registry.register(
            WorkshopModule(
                settings.database_path, workshop_client or SteamWorkshopClient()
            )
        )
    rotation_module = RotationModule(settings.database_path) if enable_rotation else None
    if rotation_module:
        registry.register(rotation_module)
    if enable_players:
        registry.register(AdvancedPlayersModule())
    registry.discover()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        async def maintenance_loop() -> None:
            while True:
                await asyncio.sleep(60)
                try:
                    await application.state.maintenance_runner.run_due()
                    if application.state.bridge_rotation_runner:
                        application.state.bridge_rotation_runner.run()
                except Exception:
                    # One integration failure must not permanently stop scheduling.
                    logger.exception("Background integration cycle failed")
                    continue

        task = asyncio.create_task(maintenance_loop())
        application.state.maintenance_task = task
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="CS2 WebUI", version="0.1.0", lifespan=lifespan)
    app.state.module_registry = registry
    app.state.settings = settings
    app.state.setup_store = setup_store
    app.state.auth_store = auth_store
    app.state.login_rate_limiter = LoginRateLimiter()
    app.state.audit_store = audit_store
    app.state.instance_store = instance_store
    app.state.backup_store = backup_store
    app.state.maintenance_store = maintenance_store
    app.state.plugin_store = plugin_store
    app.state.quick_command_store = quick_command_store
    app.state.configuration_store = configuration_store
    app.state.lifecycle_planner = lifecycle_planner
    app.state.agent_client = agent_client or AgentClient(
        settings.agent_socket_path, settings.agent_token_path
    )
    app.state.rcon_client = rcon_client or RconClient()
    app.state.a2s_client = a2s_client or A2sClient()
    app.state.metrics_client = MetricsClient(settings.data_dir)
    app.state.steam_profiles = steam_profiles or SteamProfileClient(
        settings.steam_web_api_key
    )
    app.state.maintenance_runner = MaintenanceRunner(
        instance_store,
        maintenance_store,
        backup_store,
        lifecycle_planner,
        app.state.agent_client,
        app.state.a2s_client,
        settings.game_host,
    )
    app.state.bridge_rotation_runner = (
        BridgeRotationRunner(
            instance_store,
            rotation_module.store,
            app.state.rcon_client,
            settings.game_host,
        )
        if rotation_module
        else None
    )
    app.state.diagnostics = diagnostics or default_diagnostics()
    app.include_router(core_router)
    app.include_router(auth_router)
    app.include_router(setup_router)
    app.include_router(instances_router)
    app.include_router(lifecycle_router)
    app.include_router(users_router)
    app.include_router(console_router)
    app.include_router(maintenance_router)
    app.include_router(plugins_router)
    app.include_router(configuration_router)
    registry.mount(app)

    web_dir = Path(__file__).parent / "web"
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    @app.get("/setup", include_in_schema=False)
    async def setup_page() -> FileResponse:
        return FileResponse(web_dir / "setup.html")

    @app.get("/panel", include_in_schema=False)
    async def panel_page() -> FileResponse:
        return FileResponse(web_dir / "panel.html")

    return app
