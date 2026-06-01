from pathlib import Path
import io
import tarfile
import zipfile
import json

from fastapi.testclient import TestClient
import pytest

from cs2webui.app import create_app
from cs2webui.core.settings import Settings
from cs2webui.host.diagnostics import HostReport, PortStatus
from cs2webui.host.a2s import ServerInfo
from cs2webui.host.rcon import RconResponse
from cs2webui.modules.builtin.workshop import WorkshopMap
from cs2webui.core.plugins import PluginStore


class FakeDiagnostics:
    def inspect(self, start_port: int, count: int) -> HostReport:
        ports = tuple(
            PortStatus(
                port=port,
                available=port not in {8080, 8081},
                process="test-listener" if port in {8080, 8081} else None,
            )
            for port in range(start_port, start_port + count)
        )
        return HostReport(
            operating_system="Linux test-host",
            firewall="ufw",
            ports=ports,
        )

    def inspect_udp(self, start_port: int, count: int) -> HostReport:
        ports = tuple(
            PortStatus(
                port=port,
                available=port != 27015,
                process=None,
            )
            for port in range(start_port, start_port + count)
        )
        return HostReport(
            operating_system="Linux test-host",
            firewall="ufw",
            ports=ports,
        )


class FakeAgentClient:
    def __init__(self) -> None:
        self.commands = []

    async def execute(self, command):
        self.commands.append(command)
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    async def import_server(self, mode, source, destination):
        self.commands.append(("import", mode, source, destination))
        return {"status": "imported"}

    async def container_logs(self, container_name, tail=200):
        self.commands.append(("logs", container_name, tail))
        return {"returncode": 0, "stdout": "server log", "stderr": ""}

    async def container_stats(self, container_name):
        self.commands.append(("stats", container_name))
        return {
            "returncode": 0,
            "stats": [{"CPUPerc": "2.10%", "MemUsage": "1.2GiB / 8GiB"}],
            "stderr": "",
        }

    async def delete_server(self, destination):
        self.commands.append(("delete", destination))
        return {"status": "deleted"}

    async def health(self):
        return {"status": "ok"}


class FakeRconClient:
    def __init__(self) -> None:
        self.commands = []

    def execute(self, host, port, password, command):
        self.commands.append((host, port, password, command))
        return RconResponse(body="command accepted")


class FakeWorkshopClient:
    async def fetch(self, published_file_id):
        return WorkshopMap(
            published_file_id=published_file_id,
            title="AWP India",
            preview_url="https://example.test/awp-india.jpg",
            workshop_url=(
                "https://steamcommunity.com/sharedfiles/filedetails/"
                f"?id={published_file_id}"
            ),
        )

    async def fetch_collection(self, published_file_id):
        return ["3070290869", "3070290870"]


class UnavailableWorkshopClient:
    async def fetch(self, published_file_id):
        raise ValueError("Steam metadata unavailable")

    async def fetch_collection(self, published_file_id):
        raise ValueError("Steam metadata unavailable")


class FakeA2sClient:
    def query_info(self, host, port):
        return ServerInfo(
            name="Primary Server",
            map_name="de_mirage",
            players=5,
            max_players=12,
            bots=1,
            version="1.0",
        )


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(data_dir=tmp_path / "data")
    return TestClient(
        create_app(
            settings=settings,
            diagnostics=FakeDiagnostics(),
            agent_client=FakeAgentClient(),
            rcon_client=FakeRconClient(),
            workshop_client=FakeWorkshopClient(),
            a2s_client=FakeA2sClient(),
        )
    )


def create_admin_session(client: TestClient) -> None:
    assert client.put("/api/setup/language", json={"language": "en"}).status_code == 200
    assert client.put("/api/setup/access", json={"mode": "local"}).status_code == 200
    assert client.put("/api/setup/port", json={"port": 8082}).status_code == 200
    response = client.post(
        "/api/setup/admin",
        json={"username": "first-admin", "password": "a-secure-password"},
    )
    assert response.status_code == 201


def test_health_is_available(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_dashboard_module_is_registered_by_default(client: TestClient) -> None:
    response = client.get("/api/modules")

    assert response.status_code == 200
    assert response.json()[0]["id"] == "dashboard"
    assert response.json()[0]["ui_path"] is None
    create_admin_session(client)
    assert client.get("/api/dashboard/summary").status_code == 200


def test_core_works_without_dashboard_module(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    client = TestClient(
        create_app(
            enable_dashboard=False,
            enable_workshop=False,
            enable_rotation=False,
            enable_players=False,
            settings=settings,
            diagnostics=FakeDiagnostics(),
        )
    )

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/modules").json() == []
    assert client.get("/api/dashboard/summary").status_code == 404


def test_setup_page_is_available(client: TestClient) -> None:
    launcher = client.get("/")
    response = client.get("/setup")

    assert launcher.status_code == 200
    assert 'window.location.replace(state.completed ? "/panel" : "/setup")' in launcher.text
    assert response.status_code == 200
    assert "CS2 WebUI Setup" in response.text


def test_operator_panel_page_is_available(client: TestClient) -> None:
    response = client.get("/panel")

    assert response.status_code == 200
    assert '<script src="/static/panel.js"></script>' in response.text


def test_diagnostics_suggest_first_available_port(client: TestClient) -> None:
    response = client.get("/api/setup/diagnostics?start_port=8080&count=4")

    assert response.status_code == 200
    assert response.json()["suggested_port"] == 8082
    assert response.json()["ports"][0] == {
        "port": 8080,
        "available": False,
        "process": "test-listener",
    }


def test_setup_state_is_persisted(client: TestClient) -> None:
    assert client.put("/api/setup/language", json={"language": "ru"}).status_code == 200
    assert (
        client.put(
            "/api/setup/access",
            json={"mode": "domain", "domain": "panel.example.com"},
        ).status_code
        == 200
    )
    assert client.put("/api/setup/port", json={"port": 8082}).status_code == 200
    response = client.post(
        "/api/setup/admin",
        json={"username": "server-admin", "password": "a-secure-password"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "language": "ru",
        "access_mode": "domain",
        "access_domain": "panel.example.com",
        "webui_port": 8082,
        "admin_created": True,
        "completed": True,
    }


def test_occupied_port_is_rejected(client: TestClient) -> None:
    response = client.put("/api/setup/port", json={"port": 8080})

    assert response.status_code == 409


def test_second_admin_creation_is_rejected(client: TestClient) -> None:
    payload = {"username": "first-admin", "password": "a-secure-password"}
    assert client.put("/api/setup/language", json={"language": "en"}).status_code == 200
    assert client.put("/api/setup/access", json={"mode": "local"}).status_code == 200
    assert client.put("/api/setup/port", json={"port": 8082}).status_code == 200

    assert client.post("/api/setup/admin", json=payload).status_code == 201
    assert client.post("/api/setup/admin", json=payload).status_code == 403


def test_admin_creation_requires_setup_prerequisites(client: TestClient) -> None:
    response = client.post(
        "/api/setup/admin",
        json={"username": "first-admin", "password": "a-secure-password"},
    )

    assert response.status_code == 409
    assert client.get("/api/setup/state").json()["admin_created"] is False


def test_completed_setup_cannot_be_reconfigured_anonymously(client: TestClient) -> None:
    assert client.put("/api/setup/language", json={"language": "en"}).status_code == 200
    assert client.put("/api/setup/access", json={"mode": "local"}).status_code == 200
    assert client.put("/api/setup/port", json={"port": 8082}).status_code == 200
    assert (
        client.post(
            "/api/setup/admin",
            json={"username": "first-admin", "password": "a-secure-password"},
        ).status_code
        == 201
    )

    assert client.put("/api/setup/language", json={"language": "ru"}).status_code == 403
    assert client.get("/api/setup/diagnostics").status_code == 403
    assert client.get("/api/setup/access-plan").status_code == 200
    assert client.get("/api/setup/state").json() == {"completed": True}
    client.cookies.clear()
    assert client.get("/api/setup/access-plan").status_code == 403


def test_domain_access_plan_contains_caddy_reverse_proxy(client: TestClient) -> None:
    assert client.put("/api/setup/language", json={"language": "en"}).status_code == 200
    assert (
        client.put(
            "/api/setup/access",
            json={"mode": "domain", "domain": "panel.example.com"},
        ).status_code
        == 200
    )
    assert client.put("/api/setup/port", json={"port": 8082}).status_code == 200

    response = client.get("/api/setup/access-plan")

    assert response.status_code == 200
    assert response.json()["url"] == "https://panel.example.com"
    assert "reverse_proxy 127.0.0.1:8082" in response.json()["caddyfile"]
    assert response.json()["apply_command"].startswith(
        "sudo /var/lib/cs2webui-system/bin/apply-access.sh "
    )


def test_domain_access_rejects_invalid_dns_name(client: TestClient) -> None:
    response = client.put(
        "/api/setup/access",
        json={"mode": "domain", "domain": ".invalid-domain"},
    )

    assert response.status_code == 422


def test_instance_ports_suggest_first_available_udp_port(client: TestClient) -> None:
    create_admin_session(client)
    response = client.get("/api/instances/ports?start_port=27015&count=3")

    assert response.status_code == 200
    assert response.json()["suggested_port"] == 27016
    assert response.json()["capacity"]["recommended_install_bytes"] == 65 * 1024**3
    assert isinstance(response.json()["capacity"]["disk_free_bytes"], int)


def test_create_instance_returns_masked_launch_preview(client: TestClient) -> None:
    create_admin_session(client)
    response = client.post(
        "/api/instances",
        json={
            "name": "Primary Server",
            "game_port": 27016,
            "start_map": "de_mirage",
            "preset": "competitive",
            "install_source": "steamcmd",
            "rcon_password": "rcon-secret",
            "gslt": "gslt-secret",
            "bridge_enabled": True,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert Path(payload["server_dir"]).parts[-3:] == (
        "instances",
        "primary-server",
        "server",
    )
    assert payload["status"] == "pending_install"
    assert "rcon-secret" not in payload["launch_preview"]
    assert "gslt-secret" not in payload["launch_preview"]
    assert payload["launch_preview"].count("********") == 2


def test_instance_runtime_logs_and_stats_are_available(client: TestClient) -> None:
    create_admin_session(client)
    instance = client.post(
        "/api/instances",
        json={
            "name": "Primary Server",
            "game_port": 27016,
            "start_map": "de_mirage",
            "preset": "competitive",
            "install_source": "steamcmd",
            "rcon_password": "rcon-secret",
            "gslt": "gslt-secret",
            "bridge_enabled": True,
        },
    ).json()

    logs = client.get(f"/api/instances/{instance['id']}/logs")
    stats = client.get(f"/api/instances/{instance['id']}/stats")

    assert logs.status_code == 200
    assert logs.json()["stdout"] == "server log"
    assert stats.status_code == 200
    assert stats.json()["stats"][0]["CPUPerc"] == "2.10%"


def test_instance_can_be_cloned_without_reusing_secrets(client: TestClient) -> None:
    create_admin_session(client)
    source = create_instance(client)

    response = client.post(
        f"/api/instances/{source['id']}/clone",
        json={
            "name": "Practice Clone",
            "game_port": 27017,
            "rcon_password": "new-rcon-secret",
            "gslt": "new-gslt-secret",
        },
    )

    assert response.status_code == 201
    clone = response.json()
    assert clone["install_source"] == "copy"
    assert clone["source_path"] == source["server_dir"]
    assert clone["game_port"] == 27017


def test_instance_file_purge_requires_confirmation(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)

    rejected = client.request(
        "DELETE",
        f"/api/instances/{instance['id']}",
        json={"purge_files": True},
    )
    deleted = client.request(
        "DELETE",
        f"/api/instances/{instance['id']}",
        json={"purge_files": True, "confirmation": "DELETE-CS2-FILES"},
    )

    assert rejected.status_code == 422
    assert deleted.status_code == 200
    assert deleted.json()["purged_files"] is True


def test_instance_port_cannot_be_reused(client: TestClient) -> None:
    create_admin_session(client)
    payload = {
        "name": "Primary Server",
        "game_port": 27016,
        "start_map": "de_dust2",
        "preset": "casual",
        "rcon_password": "rcon-secret",
        "gslt": "gslt-secret",
    }

    assert client.post("/api/instances", json=payload).status_code == 201
    payload["name"] = "Second Server"
    assert client.post("/api/instances", json=payload).status_code == 409


def test_secret_key_is_created_with_instance_store(client: TestClient, tmp_path: Path) -> None:
    assert (tmp_path / "data" / "secret.key").is_file()


def test_instance_api_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/instances").status_code == 401


def test_admin_creation_starts_browser_session(client: TestClient) -> None:
    create_admin_session(client)

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json() == {"username": "first-admin", "role": "admin"}


def test_logout_revokes_browser_session(client: TestClient) -> None:
    create_admin_session(client)

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_login_rate_limit_blocks_repeated_password_guesses(client: TestClient) -> None:
    create_admin_session(client)
    assert client.post("/api/auth/logout").status_code == 204

    for _ in range(5):
        assert (
            client.post(
                "/api/auth/login",
                json={"username": "first-admin", "password": "wrong-password"},
            ).status_code
            == 401
        )

    response = client.post(
        "/api/auth/login",
        json={"username": "first-admin", "password": "a-secure-password"},
    )

    assert response.status_code == 429
    assert response.json()["detail"] == "Too many login attempts"


def test_lifecycle_plans_use_podman_and_mask_secrets(client: TestClient) -> None:
    create_admin_session(client)
    created = client.post(
        "/api/instances",
        json={
            "name": "Primary Server",
            "game_port": 27016,
            "start_map": "de_mirage",
            "preset": "competitive",
            "rcon_password": "rcon-secret",
            "gslt": "gslt-secret",
        },
    ).json()

    install_plan = client.get(
        f"/api/instances/{created['id']}/plans/install"
    ).json()
    start_plan = client.get(f"/api/instances/{created['id']}/plans/start").json()

    assert "podman run --rm" in install_plan["commands"][0]["command"]
    assert "+app_update 730 validate" in install_plan["commands"][0]["command"]
    assert "podman run --detach --replace" in start_plan["commands"][0]["command"]
    assert "--network host" in start_plan["commands"][0]["command"]
    assert "rcon-secret" not in start_plan["commands"][0]["command"]
    assert "gslt-secret" not in start_plan["commands"][0]["command"]


def test_admin_can_create_operator_and_audit_records_action(client: TestClient) -> None:
    create_admin_session(client)

    created = client.post(
        "/api/users",
        json={
            "username": "server-operator",
            "password": "operator-password",
            "role": "operator",
        },
    )
    audit = client.get("/api/audit").json()

    assert created.status_code == 201
    assert created.json()["role"] == "operator"
    assert audit[0]["action"] == "user.created"
    assert "server-operator" in audit[0]["details"]


def test_operator_cannot_create_users_or_instances(client: TestClient) -> None:
    create_admin_session(client)
    assert (
        client.post(
            "/api/users",
            json={
                "username": "server-operator",
                "password": "operator-password",
                "role": "operator",
            },
        ).status_code
        == 201
    )
    client.cookies.clear()
    assert (
        client.post(
            "/api/auth/login",
            json={"username": "server-operator", "password": "operator-password"},
        ).status_code
        == 200
    )

    assert client.get("/api/instances").status_code == 200
    assert (
        client.post(
            "/api/users",
            json={
                "username": "another-user",
                "password": "another-password",
                "role": "viewer",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/instances",
            json={
                "name": "Forbidden server",
                "game_port": 27016,
                "preset": "custom",
                "rcon_password": "rcon-secret",
                "gslt": "gslt-secret",
            },
        ).status_code
        == 403
    )


def test_viewer_can_list_instances_but_cannot_create_them(client: TestClient) -> None:
    create_admin_session(client)
    create_instance(client)
    assert (
        client.post(
            "/api/users",
            json={
                "username": "server-viewer",
                "password": "viewer-password",
                "role": "viewer",
            },
        ).status_code
        == 201
    )
    client.cookies.clear()
    assert (
        client.post(
            "/api/auth/login",
            json={"username": "server-viewer", "password": "viewer-password"},
        ).status_code
        == 200
    )

    assert client.get("/api/instances").status_code == 200
    assert (
        client.post(
            "/api/instances",
            json={
                "name": "Forbidden server",
                "game_port": 27017,
                "preset": "custom",
                "rcon_password": "rcon-secret",
                "gslt": "gslt-secret",
            },
        ).status_code
        == 403
    )


def test_admin_can_execute_install_through_host_agent(client: TestClient) -> None:
    create_admin_session(client)
    created = client.post(
        "/api/instances",
        json={
            "name": "Primary Server",
            "game_port": 27016,
            "preset": "competitive",
            "rcon_password": "rcon-secret",
            "gslt": "gslt-secret",
        },
    ).json()

    response = client.post(f"/api/instances/{created['id']}/actions/install")

    assert response.status_code == 200
    assert response.json()["results"][0]["returncode"] == 0
    assert client.get("/api/instances").json()[0]["status"] == "installed"


def test_start_rechecks_game_port_conflict_after_instance_creation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_admin_session(client)
    instance = create_instance(client)

    monkeypatch.setattr(
        client.app.state.diagnostics,
        "inspect_udp",
        lambda start_port, count: HostReport(
            operating_system="Linux test-host",
            firewall="ufw",
            ports=(PortStatus(port=start_port, available=False),),
        ),
    )

    response = client.post(f"/api/instances/{instance['id']}/actions/start")

    assert response.status_code == 409


def test_instance_rejects_unsafe_start_map(client: TestClient) -> None:
    create_admin_session(client)

    response = client.post(
        "/api/instances",
        json={
            "name": "Unsafe map",
            "game_port": 27016,
            "start_map": "de_dust2; quit",
            "preset": "custom",
            "rcon_password": "rcon-secret",
            "gslt": "gslt-secret",
        },
    )

    assert response.status_code == 422


def test_operator_can_stop_server_but_cannot_install_files(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    assert (
        client.post(
            "/api/users",
            json={
                "username": "daily-operator",
                "password": "operator-password",
                "role": "operator",
            },
        ).status_code
        == 201
    )
    client.cookies.clear()
    assert (
        client.post(
            "/api/auth/login",
            json={"username": "daily-operator", "password": "operator-password"},
        ).status_code
        == 200
    )

    assert (
        client.post(f"/api/instances/{instance['id']}/actions/stop").status_code == 200
    )
    assert (
        client.post(f"/api/instances/{instance['id']}/actions/install").status_code
        == 403
    )


def test_quick_commands_and_presets_are_available_after_login(client: TestClient) -> None:
    create_admin_session(client)

    assert client.get("/api/presets").json()["competitive"]["label"] == "Competitive"
    assert client.get("/api/quick-commands").json()[0]["id"] == "restart-game"


def test_admin_can_create_parameterized_quick_command(client: TestClient) -> None:
    create_admin_session(client)

    created = client.post(
        "/api/quick-commands",
        json={"label": "Set bot quota", "command": "bot_quota {count}"},
    )
    listed = client.get("/api/quick-commands").json()

    assert created.status_code == 201
    assert created.json()["custom"] is True
    assert created.json()["parameters"] == [
        {"name": "count", "type": "string", "default": ""}
    ]
    assert listed[-1]["label"] == "Set bot quota"
    assert client.delete(f"/api/quick-commands/{created.json()['id']}").status_code == 204


def test_operator_can_execute_rcon_without_exposing_password(client: TestClient) -> None:
    create_admin_session(client)
    created = client.post(
        "/api/instances",
        json={
            "name": "Primary Server",
            "game_port": 27016,
            "preset": "competitive",
            "rcon_password": "rcon-secret",
            "gslt": "gslt-secret",
        },
    ).json()

    response = client.post(
        f"/api/instances/{created['id']}/rcon",
        json={"command": "status"},
    )

    assert response.status_code == 200
    assert response.json() == {"response": "command accepted"}
    assert "rcon-secret" not in response.text


def test_operator_can_apply_live_preset(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)

    response = client.post(
        f"/api/instances/{instance['id']}/preset",
        json={"preset": "competitive"},
    )

    assert response.status_code == 200
    assert response.json()["preset"] == "competitive"
    assert response.json()["results"][0]["command"] == "game_type 0"


def test_workshop_module_adds_card_from_steam_url(client: TestClient) -> None:
    create_admin_session(client)

    response = client.post(
        "/api/workshop/maps",
        json={
            "source": (
                "https://steamcommunity.com/sharedfiles/filedetails/"
                "?id=3070290869"
            )
        },
    )

    assert response.status_code == 201
    assert response.json()["published_file_id"] == "3070290869"
    assert response.json()["title"] == "AWP India"
    assert client.get("/api/workshop/maps").json()[0]["preview_url"].startswith(
        "https://"
    )


def test_workshop_module_builds_host_workshop_map_command(client: TestClient) -> None:
    create_admin_session(client)

    response = client.get("/api/workshop/maps/3070290869/command")

    assert response.status_code == 200
    assert response.json() == {"command": "host_workshop_map 3070290869"}


def test_workshop_manual_fallback_is_used_when_steam_metadata_is_unavailable(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            settings=Settings(data_dir=tmp_path / "data"),
            diagnostics=FakeDiagnostics(),
            agent_client=FakeAgentClient(),
            rcon_client=FakeRconClient(),
            workshop_client=UnavailableWorkshopClient(),
        )
    )
    create_admin_session(client)

    response = client.post(
        "/api/workshop/maps",
        json={
            "source": "3070290869",
            "title": "Manual AWP India",
            "preview_url": "https://example.test/awp-india.jpg",
        },
    )

    assert response.status_code == 201
    assert response.json()["title"] == "Manual AWP India"


def test_workshop_preview_cache_rejects_loopback_url(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            settings=Settings(data_dir=tmp_path / "data"),
            diagnostics=FakeDiagnostics(),
            agent_client=FakeAgentClient(),
            rcon_client=FakeRconClient(),
            workshop_client=UnavailableWorkshopClient(),
        )
    )
    create_admin_session(client)

    response = client.post(
        "/api/workshop/maps",
        json={
            "source": "3070290869",
            "title": "Unsafe preview",
            "preview_url": "https://127.0.0.1/image.jpg",
            "cache_preview": True,
        },
    )

    assert response.status_code == 422


def test_workshop_preview_can_be_uploaded_from_browser(client: TestClient) -> None:
    create_admin_session(client)
    assert client.post(
        "/api/workshop/maps", json={"source": "3070290869"}
    ).status_code == 201

    uploaded = client.put(
        "/api/workshop/media/3070290869",
        content=b"test image bytes",
        headers={"Content-Type": "image/png"},
    )
    downloaded = client.get("/api/workshop/media/3070290869")

    assert uploaded.status_code == 200
    assert uploaded.json()["preview_url"] == "/api/workshop/media/3070290869"
    assert downloaded.status_code == 200
    assert downloaded.content == b"test image bytes"


def test_workshop_preview_upload_rejects_oversized_content_length(
    client: TestClient,
) -> None:
    create_admin_session(client)
    assert client.post(
        "/api/workshop/maps", json={"source": "3070290869"}
    ).status_code == 201

    response = client.put(
        "/api/workshop/media/3070290869",
        content=b"small body",
        headers={
            "Content-Type": "image/png",
            "Content-Length": str(5 * 1024 * 1024 + 1),
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Workshop preview exceeds size limit"


def test_workshop_collection_is_expanded_into_independent_cards(
    client: TestClient,
) -> None:
    create_admin_session(client)

    response = client.post(
        "/api/workshop/collections",
        json={"source": "https://steamcommunity.com/sharedfiles/filedetails/?id=12345"},
    )

    assert response.status_code == 201
    assert [item["published_file_id"] for item in response.json()] == [
        "3070290869",
        "3070290870",
    ]
    assert len(client.get("/api/workshop/maps").json()) == 2


def test_workshop_module_can_be_removed_without_breaking_core(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    client = TestClient(
        create_app(
            settings=settings,
            diagnostics=FakeDiagnostics(),
            agent_client=FakeAgentClient(),
            rcon_client=FakeRconClient(),
            enable_workshop=False,
        )
    )

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/workshop/maps").status_code == 404


def test_rotation_module_handles_cycle_queue_and_history(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    endpoint = f"/api/rotation/{instance['id']}"
    cycle = {
        "maps": [
            {"kind": "standard", "identifier": "de_mirage", "title": "Mirage"},
            {
                "kind": "workshop",
                "identifier": "3070290869",
                "title": "AWP India",
            },
        ]
    }

    assert client.put(endpoint, json=cycle).status_code == 200
    first = client.post(f"{endpoint}/next").json()
    second = client.post(f"{endpoint}/next").json()
    assert first == {"command": "changelevel de_mirage"}
    assert second == {"command": "host_workshop_map 3070290869"}

    queued = {"kind": "standard", "identifier": "de_nuke", "title": "Nuke"}
    assert client.post(f"{endpoint}/queue", json=queued).status_code == 201
    assert client.post(f"{endpoint}/next").json() == {
        "command": "changelevel de_nuke"
    }

    replacement = {"maps": [queued]}
    assert client.put(endpoint, json=replacement).status_code == 200
    history = client.get(f"{endpoint}/history").json()
    assert history[0]["maps"][0]["identifier"] == "de_mirage"
    restored = client.post(
        f"{endpoint}/history/{history[0]['id']}/restore"
    )
    assert restored.status_code == 200
    assert restored.json()["cycle"][0]["identifier"] == "de_mirage"


def test_rotation_module_rejects_command_injection(client: TestClient) -> None:
    create_admin_session(client)

    response = client.put(
        "/api/rotation/server-1",
        json={
            "maps": [
                {
                    "kind": "standard",
                    "identifier": "de_dust2; quit",
                    "title": "Unsafe",
                }
            ]
        },
    )

    assert response.status_code == 422


def test_rotation_module_rejects_unknown_instance(client: TestClient) -> None:
    create_admin_session(client)

    response = client.post(
        "/api/rotation/not-a-server/queue",
        json={"kind": "standard", "identifier": "de_nuke", "title": "Nuke"},
    )

    assert response.status_code == 404


def test_rotation_next_executes_rcon_for_managed_instance(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    assert (
        client.put(
            f"/api/rotation/{instance['id']}",
            json={
                "maps": [
                    {"kind": "standard", "identifier": "de_nuke", "title": "Nuke"}
                ]
            },
        ).status_code
        == 200
    )

    response = client.post(f"/api/rotation/{instance['id']}/next")

    assert response.status_code == 200
    assert response.json()["command"] == "changelevel de_nuke"
    assert client.app.state.rcon_client.commands[-1][-1] == "changelevel de_nuke"
    assert client.get(f"/api/rotation/{instance['id']}").json()[
        "expected_current_command"
    ] == "changelevel de_nuke"


def test_rotation_module_can_be_removed_without_breaking_core(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    client = TestClient(
        create_app(
            settings=settings,
            diagnostics=FakeDiagnostics(),
            agent_client=FakeAgentClient(),
            rcon_client=FakeRconClient(),
            enable_rotation=False,
        )
    )

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/rotation/server-1").status_code == 404


def test_dashboard_reports_a2s_server_information(client: TestClient) -> None:
    create_admin_session(client)
    assert (
        client.post(
            "/api/instances",
            json={
                "name": "Primary Server",
                "game_port": 27016,
                "preset": "competitive",
                "rcon_password": "rcon-secret",
                "gslt": "gslt-secret",
            },
        ).status_code
        == 201
    )

    response = client.get("/api/dashboard/summary")

    assert response.status_code == 200
    server = response.json()["instances"][0]["server"]
    assert server["map_name"] == "de_mirage"
    assert server["players"] == 5
    assert server["bots"] == 1


def create_instance(client: TestClient) -> dict:
    return client.post(
        "/api/instances",
        json={
            "name": "Primary Server",
            "game_port": 27016,
            "preset": "competitive",
            "rcon_password": "rcon-secret",
            "gslt": "gslt-secret",
        },
    ).json()


def test_backup_captures_configs_and_addons(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    server_dir = Path(instance["server_dir"])
    config = server_dir / "game" / "csgo" / "cfg" / "server.cfg"
    addon = server_dir / "game" / "csgo" / "addons" / "example.txt"
    config.parent.mkdir(parents=True)
    addon.parent.mkdir(parents=True)
    config.write_text("hostname test")
    addon.write_text("plugin")

    response = client.post(f"/api/instances/{instance['id']}/backups")

    assert response.status_code == 201
    with zipfile.ZipFile(response.json()["path"]) as archive:
        assert "game/csgo/cfg/server.cfg" in archive.namelist()
        assert "game/csgo/addons/example.txt" in archive.namelist()


def test_backup_can_restore_user_files(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    config = Path(instance["server_dir"]) / "game" / "csgo" / "cfg" / "server.cfg"
    config.parent.mkdir(parents=True)
    config.write_text("hostname before")
    backup = client.post(f"/api/instances/{instance['id']}/backups").json()
    config.write_text("hostname after")

    response = client.post(
        f"/api/instances/{instance['id']}/backups/{backup['name']}/restore"
    )

    assert response.status_code == 200
    assert config.read_text() == "hostname before"


def test_backup_does_not_follow_symbolic_links(client: TestClient, tmp_path: Path) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    addons = Path(instance["server_dir"]) / "game" / "csgo" / "addons"
    addons.mkdir(parents=True)
    external = tmp_path / "outside-secret.txt"
    external.write_text("do not archive")
    link = addons / "outside-secret.txt"
    try:
        link.symlink_to(external)
    except OSError:
        pytest.skip("Symbolic links are unavailable on this workstation")

    response = client.post(f"/api/instances/{instance['id']}/backups")

    assert response.status_code == 201
    with zipfile.ZipFile(response.json()["path"]) as archive:
        assert "game/csgo/addons/outside-secret.txt" not in archive.namelist()


def test_maintenance_policy_is_persisted(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)

    response = client.put(
        f"/api/instances/{instance['id']}/maintenance",
        json={
            "restart_every_minutes": 720,
            "update_before_restart": True,
            "defer_while_players_online": True,
            "max_defer_minutes": 60,
            "backup_before_update": True,
        },
    )

    assert response.status_code == 200
    assert client.get(
        f"/api/instances/{instance['id']}/maintenance"
    ).json()["restart_every_minutes"] == 720


def test_maintenance_notice_reports_upcoming_restart(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)

    saved = client.put(
        f"/api/instances/{instance['id']}/maintenance",
        json={
            "restart_every_minutes": 5,
            "notify_before_minutes": 10,
            "update_before_restart": False,
            "defer_while_players_online": True,
            "max_defer_minutes": 60,
            "backup_before_update": True,
        },
    )
    notices = client.get("/api/instances/notices")

    assert saved.status_code == 200
    assert client.get(
        f"/api/instances/{instance['id']}/maintenance"
    ).json()["next_run_at"]
    assert notices.status_code == 200
    assert notices.json()[0]["instance_name"] == "Primary Server"


def test_local_plugin_archive_is_installed_safely(
    client: TestClient, tmp_path: Path
) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    archive = tmp_path / "imports" / "simple-admin.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("game/csgo/addons/simpleadmin/plugin.txt", "plugin")

    response = client.post(
        f"/api/instances/{instance['id']}/plugins",
        json={"name": "SimpleAdmin", "source_type": "local", "source": str(archive)},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "installed"
    assert len(response.json()["checksum"]) == 64
    assert (
        Path(instance["server_dir"])
        / "game"
        / "csgo"
        / "addons"
        / "simpleadmin"
        / "plugin.txt"
    ).is_file()


def test_local_plugin_directory_can_be_installed_by_managed_relative_name(
    client: TestClient, tmp_path: Path
) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    plugin_file = (
        tmp_path
        / "imports"
        / "simple-admin-folder"
        / "game"
        / "csgo"
        / "addons"
        / "simpleadmin"
        / "plugin.txt"
    )
    plugin_file.parent.mkdir(parents=True)
    plugin_file.write_text("plugin")

    response = client.post(
        f"/api/instances/{instance['id']}/plugins",
        json={
            "name": "SimpleAdmin Folder",
            "source_type": "local",
            "source": "simple-admin-folder",
        },
    )

    assert response.status_code == 201
    assert len(response.json()["checksum"]) == 64
    assert (
        Path(instance["server_dir"])
        / "game"
        / "csgo"
        / "addons"
        / "simpleadmin"
        / "plugin.txt"
    ).is_file()


def test_local_plugin_source_outside_managed_imports_is_rejected(
    client: TestClient, tmp_path: Path
) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    outside = tmp_path / "outside.zip"
    with zipfile.ZipFile(outside, "w") as package:
        package.writestr("game/csgo/addons/outside/plugin.txt", "plugin")

    response = client.post(
        f"/api/instances/{instance['id']}/plugins",
        json={"name": "Outside", "source_type": "local", "source": str(outside)},
    )

    assert response.status_code == 422


def test_plugin_archive_path_traversal_is_rejected(
    client: TestClient, tmp_path: Path
) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    archive = tmp_path / "imports" / "unsafe.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("../outside.txt", "unsafe")

    response = client.post(
        f"/api/instances/{instance['id']}/plugins",
        json={"name": "Unsafe", "source_type": "local", "source": str(archive)},
    )

    assert response.status_code == 422
    assert not (tmp_path / "outside.txt").exists()


def test_plugin_archive_expansion_limit_is_enforced(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    archive = tmp_path / "imports" / "expanded.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("game/csgo/addons/large.txt", "12345")
    monkeypatch.setattr("cs2webui.core.plugins.MAX_PLUGIN_EXTRACTED_BYTES", 4)

    response = client.post(
        f"/api/instances/{instance['id']}/plugins",
        json={"name": "Expanded", "source_type": "local", "source": str(archive)},
    )

    assert response.status_code == 422


def test_plugin_archive_cannot_overwrite_existing_server_file(
    client: TestClient, tmp_path: Path
) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    existing = Path(instance["server_dir"]) / "game" / "csgo" / "addons" / "shared.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("server-owned")
    archive = tmp_path / "imports" / "overwrite.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("game/csgo/addons/shared.txt", "plugin-owned")

    response = client.post(
        f"/api/instances/{instance['id']}/plugins",
        json={"name": "Overwrite", "source_type": "local", "source": str(archive)},
    )

    assert response.status_code == 422
    assert existing.read_text() == "server-owned"


def test_builtin_bridge_archive_can_be_installed(
    client: TestClient, tmp_path: Path
) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    archive = tmp_path / "imports" / "cs2webui-bridge.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(
            "game/csgo/addons/counterstrikesharp/plugins/"
            "CS2WebUI.Bridge/CS2WebUI.Bridge.dll",
            "test assembly",
        )

    response = client.post(
        f"/api/instances/{instance['id']}/plugins/builtin-bridge"
    )

    assert response.status_code == 201
    assert response.json()["source"] == "builtin:bridge"
    assert (
        Path(instance["server_dir"])
        / "game"
        / "csgo"
        / "addons"
        / "counterstrikesharp"
        / "plugins"
        / "CS2WebUI.Bridge"
        / "CS2WebUI.Bridge.dll"
    ).is_file()


def test_successful_install_action_adds_recommended_bridge_when_archive_exists(
    client: TestClient, tmp_path: Path
) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    archive = tmp_path / "imports" / "cs2webui-bridge.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(
            "game/csgo/addons/counterstrikesharp/plugins/"
            "CS2WebUI.Bridge/CS2WebUI.Bridge.dll",
            "test assembly",
        )

    response = client.post(f"/api/instances/{instance['id']}/actions/install")

    assert response.status_code == 200
    assert response.json()["bridge"]["status"] == "installed"
    assert client.get(f"/api/instances/{instance['id']}/plugins").json()[0][
        "source"
    ] == "builtin:bridge"


def test_install_action_reports_unavailable_optional_prerequisites(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_admin_session(client)

    async def unavailable(_instance):
        raise ValueError("release source is offline")

    monkeypatch.setattr(
        client.app.state.plugin_store, "install_builtin_metamod", unavailable
    )
    monkeypatch.setattr(
        client.app.state.plugin_store,
        "install_builtin_counterstrikesharp",
        unavailable,
    )
    instance = client.post(
        "/api/instances",
        json={
            "name": "Prerequisite Server",
            "game_port": 27016,
            "preset": "competitive",
            "rcon_password": "rcon-secret",
            "gslt": "gslt-secret",
            "metamod_enabled": True,
            "counterstrikesharp_enabled": True,
            "bridge_enabled": False,
        },
    ).json()

    response = client.post(f"/api/instances/{instance['id']}/actions/install")

    assert response.status_code == 200
    assert response.json()["prerequisites"] == [
        {
            "component": "metamod",
            "status": "unavailable",
            "detail": "release source is offline",
        },
        {
            "component": "counterstrikesharp",
            "status": "unavailable",
            "detail": "release source is offline",
        },
    ]
    assert client.get("/api/instances").json()[0]["status"] == "installed"


def test_plugin_can_be_disabled_and_enabled(client: TestClient, tmp_path: Path) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    archive = tmp_path / "imports" / "toggle.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("game/csgo/addons/toggle/plugin.txt", "plugin")
    installed = client.post(
        f"/api/instances/{instance['id']}/plugins",
        json={"name": "Toggle", "source_type": "local", "source": str(archive)},
    ).json()
    plugin_file = (
        Path(instance["server_dir"]) / "game" / "csgo" / "addons" / "toggle" / "plugin.txt"
    )

    disabled = client.put(
        f"/api/instances/{instance['id']}/plugins/{installed['id']}",
        json={"enabled": False},
    )
    assert disabled.json()["status"] == "disabled"
    assert not plugin_file.exists()

    enabled = client.put(
        f"/api/instances/{instance['id']}/plugins/{installed['id']}",
        json={"enabled": True},
    )
    assert enabled.json()["status"] == "installed"
    assert plugin_file.is_file()


def test_plugin_url_ssrf_guard_rejects_loopback() -> None:
    with pytest.raises(ValueError, match="non-public"):
        PluginStore._validate_url("https://127.0.0.1/plugin.zip")


def test_plugin_runtime_status_executes_meta_list(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)

    response = client.get(f"/api/instances/{instance['id']}/plugins/runtime-status")

    assert response.status_code == 200
    assert response.json() == {"status": "available", "output": "command accepted"}
    assert client.app.state.rcon_client.commands[-1][-1] == "meta list"


def test_counterstrikesharp_builtin_selects_linux_with_runtime_asset() -> None:
    release = {
        "tag_name": "v1.0.368",
        "assets": [
            {
                "name": "counterstrikesharp-linux-1.0.368.zip",
                "browser_download_url": "https://example.test/plain.zip",
            },
            {
                "name": "counterstrikesharp-with-runtime-linux-1.0.368.zip",
                "browser_download_url": "https://example.test/runtime.zip",
            },
        ],
    }

    assert PluginStore._select_counterstrikesharp_asset(release) == (
        "v1.0.368",
        "https://example.test/runtime.zip",
    )


def test_counterstrikesharp_builtin_rejects_release_without_runtime_asset() -> None:
    release = {
        "tag_name": "v1.0.368",
        "assets": [
            {
                "name": "counterstrikesharp-linux-1.0.368.zip",
                "browser_download_url": "https://example.test/plain.zip",
            }
        ],
    }

    with pytest.raises(ValueError, match="with-runtime"):
        PluginStore._select_counterstrikesharp_asset(release)


def test_counterstrikesharp_builtin_rejects_invalid_release_response() -> None:
    with pytest.raises(ValueError, match="response is invalid"):
        PluginStore._select_counterstrikesharp_asset({"assets": "unexpected"})


def test_metamod_builtin_selects_linux_tarball() -> None:
    release = {
        "tag_name": "2.0.0-git1401",
        "assets": [
            {
                "name": "mmsource-2.0.0-git1401-linux.tar.gz",
                "browser_download_url": "https://example.test/metamod.tar.gz",
            }
        ],
    }

    assert PluginStore._select_metamod_asset(release) == (
        "2.0.0-git1401",
        "https://example.test/metamod.tar.gz",
    )


def test_metamod_builtin_rejects_invalid_release_response() -> None:
    with pytest.raises(ValueError, match="response is invalid"):
        PluginStore._select_metamod_asset({"assets": [None]})


def test_metamod_archive_install_patches_gameinfo(client: TestClient, tmp_path: Path) -> None:
    create_admin_session(client)
    instance_payload = create_instance(client)
    instance = client.app.state.instance_store.get(instance_payload["id"])
    assert instance is not None
    server_dir = Path(instance.server_dir)
    game_dir = server_dir / "game" / "csgo"
    game_dir.mkdir(parents=True)
    gameinfo = game_dir / "gameinfo.gi"
    gameinfo.write_text("\t\tGame_LowViolence csgo_lv\n")
    source = tmp_path / "server.so"
    source.write_text("metamod")
    archive = tmp_path / "metamod.tar.gz"
    with tarfile.open(archive, "w:gz") as package:
        package.add(source, arcname="addons/metamod/bin/server.so")

    plugin = client.app.state.plugin_store._install_metamod_archive(
        instance,
        "MetaMod:Source test",
        archive,
        "https://example.test/metamod.tar.gz",
    )

    assert plugin.enabled is True
    assert (game_dir / "addons" / "metamod" / "bin" / "server.so").is_file()
    assert "\t\tGame csgo/addons/metamod\n" in gameinfo.read_text()


def test_metamod_archive_path_traversal_is_rejected(
    client: TestClient, tmp_path: Path
) -> None:
    create_admin_session(client)
    instance_payload = create_instance(client)
    instance = client.app.state.instance_store.get(instance_payload["id"])
    assert instance is not None
    game_dir = Path(instance.server_dir) / "game" / "csgo"
    game_dir.mkdir(parents=True)
    (game_dir / "gameinfo.gi").write_text("\t\tGame_LowViolence csgo_lv\n")
    archive = tmp_path / "metamod-traversal.tar.gz"
    with tarfile.open(archive, "w:gz") as package:
        member = tarfile.TarInfo("../outside.txt")
        member.size = 7
        package.addfile(member, io.BytesIO(b"outside"))

    with pytest.raises(ValueError, match="unsafe path"):
        client.app.state.plugin_store._install_metamod_archive(
            instance,
            "MetaMod:Source test",
            archive,
            "https://example.test/metamod.tar.gz",
        )

    assert not (tmp_path / "outside.txt").exists()


def test_config_editor_previews_diff_then_applies_change(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    endpoint = f"/api/instances/{instance['id']}/config"
    content = "hostname \"My CS2 Server\"\n"

    preview = client.put(endpoint, json={"content": content, "apply": False})
    assert preview.status_code == 200
    assert "+hostname" in preview.json()["diff"]
    assert client.get(endpoint).json()["content"] == ""

    applied = client.put(endpoint, json={"content": content, "apply": True})
    assert applied.json()["applied"] is True
    assert client.get(endpoint).json()["content"] == content


def test_config_editor_rejects_path_escape(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)

    response = client.get(
        f"/api/instances/{instance['id']}/config",
        params={"path": "../../etc/passwd"},
    )

    assert response.status_code == 422


def test_config_editor_can_update_mapcycle(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    endpoint = f"/api/instances/{instance['id']}/config"
    params = {"path": "game/csgo/mapcycle.txt"}
    content = "de_mirage\nde_dust2\n"

    applied = client.put(endpoint, params=params, json={"content": content, "apply": True})

    assert applied.status_code == 200
    assert client.get(endpoint, params=params).json()["content"] == content


def test_manual_maintenance_defers_when_players_are_online(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)

    response = client.post(f"/api/instances/{instance['id']}/maintenance/run")

    assert response.status_code == 200
    assert response.json()["status"] == "deferred_players_online"


def test_manual_maintenance_runs_when_player_defer_is_disabled(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    client.put(
        f"/api/instances/{instance['id']}/maintenance",
        json={
            "restart_every_minutes": 720,
            "update_before_restart": True,
            "defer_while_players_online": False,
            "max_defer_minutes": 60,
            "backup_before_update": True,
        },
    )

    response = client.post(f"/api/instances/{instance['id']}/maintenance/run")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert client.get("/api/instances").json()[0]["status"] == "running"


def test_manual_maintenance_runs_after_zero_maximum_player_defer(
    client: TestClient,
) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    client.put(
        f"/api/instances/{instance['id']}/maintenance",
        json={
            "restart_every_minutes": 720,
            "update_before_restart": False,
            "defer_while_players_online": True,
            "max_defer_minutes": 0,
            "backup_before_update": False,
        },
    )

    response = client.post(f"/api/instances/{instance['id']}/maintenance/run")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_manual_maintenance_stops_when_required_backup_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    monkeypatch.setattr(
        client.app.state.backup_store,
        "create",
        lambda _instance: (_ for _ in ()).throw(OSError("disk full")),
    )
    assert (
        client.put(
            f"/api/instances/{instance['id']}/maintenance",
            json={
                "restart_every_minutes": None,
                "defer_while_players_online": False,
                "backup_before_update": True,
            },
        ).status_code
        == 200
    )

    response = client.post(f"/api/instances/{instance['id']}/maintenance/run")

    assert response.status_code == 200
    assert response.json()["status"] == "backup_failed"
    assert client.get("/api/instances").json()[0]["status"] == "failed"


def test_import_instance_requires_source_path(client: TestClient) -> None:
    create_admin_session(client)

    response = client.post(
        "/api/instances",
        json={
            "name": "Imported Server",
            "game_port": 27016,
            "preset": "custom",
            "install_source": "copy",
            "rcon_password": "rcon-secret",
            "gslt": "gslt-secret",
        },
    )

    assert response.status_code == 422


def test_import_instance_runs_agent_import_then_validate(client: TestClient) -> None:
    create_admin_session(client)
    created = client.post(
        "/api/instances",
        json={
            "name": "Imported Server",
            "game_port": 27016,
            "preset": "custom",
            "install_source": "copy",
            "source_path": "/srv/existing-cs2",
            "rcon_password": "rcon-secret",
            "gslt": "gslt-secret",
        },
    ).json()

    response = client.post(f"/api/instances/{created['id']}/actions/install")

    assert response.status_code == 200
    assert response.json()["results"][0]["returncode"] == 0


def test_advanced_players_module_reads_bridge_snapshot(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    snapshot = (
        Path(instance["server_dir"])
        / "game"
        / "csgo"
        / "addons"
        / "counterstrikesharp"
        / "plugins"
        / "CS2WebUI.Bridge"
        / "state"
        / "players.json"
    )
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(
        json.dumps(
            [
                {
                    "name": "Player",
                    "steamId64": 76561198000000000,
                    "isBot": False,
                    "team": 3,
                    "score": 12,
                },
                {
                    "name": "Bot",
                    "steamId64": 0,
                    "isBot": True,
                    "team": 2,
                    "score": 2,
                },
            ]
        )
    )

    response = client.get(f"/api/players/{instance['id']}")

    assert response.status_code == 200
    assert response.json()["status"] == "available"
    assert response.json()["players"][1]["isBot"] is True
    assert response.json()["players"][0]["steamProfileUrl"].endswith(
        "/76561198000000000"
    )


def test_advanced_players_module_rejects_invalid_bridge_snapshot(
    client: TestClient,
) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    snapshot = (
        Path(instance["server_dir"])
        / "game"
        / "csgo"
        / "addons"
        / "counterstrikesharp"
        / "plugins"
        / "CS2WebUI.Bridge"
        / "state"
        / "players.json"
    )
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(json.dumps({"players": []}))

    response = client.get(f"/api/players/{instance['id']}")

    assert response.status_code == 502
    assert response.json()["detail"] == "Bridge state is invalid"


def test_bridge_match_marker_advances_rotation_once(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    assert (
        client.put(
            f"/api/rotation/{instance['id']}",
            json={
                "maps": [
                    {
                        "kind": "workshop",
                        "identifier": "3070290869",
                        "title": "AWP India",
                    }
                ]
            },
        ).status_code
        == 200
    )
    marker = (
        Path(instance["server_dir"])
        / "game"
        / "csgo"
        / "addons"
        / "counterstrikesharp"
        / "plugins"
        / "CS2WebUI.Bridge"
        / "state"
        / "match-ended.json"
    )
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"finishedAt": "2026-05-30T12:00:00+00:00"}))

    first = client.app.state.bridge_rotation_runner.run()
    second = client.app.state.bridge_rotation_runner.run()

    assert first == [{"instance_id": instance["id"], "status": "advanced"}]
    assert second == []
    assert not marker.exists()
    assert client.get(f"/api/rotation/{instance['id']}").json()[
        "expected_current_command"
    ] == "host_workshop_map 3070290869"


def test_bridge_invalid_match_marker_is_removed(client: TestClient) -> None:
    create_admin_session(client)
    instance = create_instance(client)
    marker = (
        Path(instance["server_dir"])
        / "game"
        / "csgo"
        / "addons"
        / "counterstrikesharp"
        / "plugins"
        / "CS2WebUI.Bridge"
        / "state"
        / "match-ended.json"
    )
    marker.parent.mkdir(parents=True)
    marker.write_text("{")

    result = client.app.state.bridge_rotation_runner.run()

    assert result == [{"instance_id": instance["id"], "status": "invalid_marker"}]
    assert not marker.exists()
