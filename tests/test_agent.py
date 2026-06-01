from pathlib import Path
from subprocess import CompletedProcess

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from cs2webui.host.agent import _validate, app


def test_agent_allows_planned_steamcmd_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instances = tmp_path / "instances"
    server = instances / "primary" / "server"
    server.mkdir(parents=True)
    monkeypatch.setenv("CS2WEBUI_INSTANCES_DIR", str(instances))

    _validate(
        [
            "podman",
            "run",
            "--rm",
            "--volume",
            f"{server}:/server:z",
            "localhost/cs2webui-steamcmd:local",
            "+force_install_dir",
            "/server",
            "+login",
            "anonymous",
            "+app_update",
            "730",
            "validate",
            "+quit",
        ]
    )


def test_agent_rejects_arbitrary_podman_command() -> None:
    with pytest.raises(HTTPException):
        _validate(["podman", "run", "--rm", "docker.io/library/alpine", "sh"])


def test_agent_rejects_volume_outside_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instances = tmp_path / "instances"
    instances.mkdir()
    monkeypatch.setenv("CS2WEBUI_INSTANCES_DIR", str(instances))

    with pytest.raises(HTTPException):
        _validate(
            [
                "podman",
                "run",
                "--rm",
                "--volume",
                "/etc:/server:z",
                "localhost/cs2webui-steamcmd:local",
                "+force_install_dir",
                "/server",
                "+login",
                "anonymous",
                "+app_update",
                "730",
                "validate",
                "+quit",
            ]
        )


def test_agent_rejects_nested_volume_inside_managed_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instances = tmp_path / "instances"
    nested = instances / "primary" / "server" / "nested"
    nested.mkdir(parents=True)
    monkeypatch.setenv("CS2WEBUI_INSTANCES_DIR", str(instances))

    with pytest.raises(HTTPException):
        _validate(
            [
                "podman",
                "run",
                "--rm",
                "--volume",
                f"{nested}:/server:z",
                "localhost/cs2webui-steamcmd:local",
                "+force_install_dir",
                "/server",
                "+login",
                "anonymous",
                "+app_update",
                "730",
                "validate",
                "+quit",
            ]
        )


def test_agent_imports_server_only_into_managed_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_path = tmp_path / "agent.token"
    token_path.write_text("secret-token")
    instances = tmp_path / "instances"
    instances.mkdir()
    source = tmp_path / "existing"
    (source / "game").mkdir(parents=True)
    (source / "game" / "cs2.sh").write_text("#!/bin/sh")
    destination = instances / "imported" / "server"
    monkeypatch.setenv("CS2WEBUI_AGENT_TOKEN", str(token_path))
    monkeypatch.setenv("CS2WEBUI_INSTANCES_DIR", str(instances))
    client = TestClient(app)

    response = client.post(
        "/import-server",
        headers={"X-CS2WebUI-Token": "secret-token"},
        json={
            "mode": "copy",
            "source": str(source),
            "destination": str(destination),
        },
    )

    assert response.status_code == 200
    assert (destination / "game" / "cs2.sh").is_file()


def test_agent_rejects_import_destination_outside_managed_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_path = tmp_path / "agent.token"
    token_path.write_text("secret-token")
    instances = tmp_path / "instances"
    instances.mkdir()
    source = tmp_path / "existing"
    (source / "game").mkdir(parents=True)
    (source / "game" / "cs2.sh").write_text("#!/bin/sh")
    monkeypatch.setenv("CS2WEBUI_AGENT_TOKEN", str(token_path))
    monkeypatch.setenv("CS2WEBUI_INSTANCES_DIR", str(instances))

    response = TestClient(app).post(
        "/import-server",
        headers={"X-CS2WebUI-Token": "secret-token"},
        json={
            "mode": "copy",
            "source": str(source),
            "destination": str(tmp_path / "outside"),
        },
    )

    assert response.status_code == 400


def test_agent_rejects_nested_import_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_path = tmp_path / "agent.token"
    token_path.write_text("secret-token")
    instances = tmp_path / "instances"
    instances.mkdir()
    source = tmp_path / "existing"
    (source / "game").mkdir(parents=True)
    (source / "game" / "cs2.sh").write_text("#!/bin/sh")
    monkeypatch.setenv("CS2WEBUI_AGENT_TOKEN", str(token_path))
    monkeypatch.setenv("CS2WEBUI_INSTANCES_DIR", str(instances))

    response = TestClient(app).post(
        "/import-server",
        headers={"X-CS2WEBUI-Token": "secret-token"},
        json={
            "mode": "copy",
            "source": str(source),
            "destination": str(instances / "nested" / "extra" / "server"),
        },
    )

    assert response.status_code == 400


def test_agent_rejects_overlapping_import_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_path = tmp_path / "agent.token"
    token_path.write_text("secret-token")
    instances = tmp_path / "instances"
    source = instances / "primary" / "server"
    (source / "game").mkdir(parents=True)
    (source / "game" / "cs2.sh").write_text("#!/bin/sh")
    monkeypatch.setenv("CS2WEBUI_AGENT_TOKEN", str(token_path))
    monkeypatch.setenv("CS2WEBUI_INSTANCES_DIR", str(instances))

    response = TestClient(app).post(
        "/import-server",
        headers={"X-CS2WEBUI-Token": "secret-token"},
        json={
            "mode": "copy",
            "source": str(source),
            "destination": str(source),
        },
    )

    assert response.status_code == 409


def test_agent_returns_logs_only_for_managed_container_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_path = tmp_path / "agent.token"
    token_path.write_text("secret-token")
    monkeypatch.setenv("CS2WEBUI_AGENT_TOKEN", str(token_path))
    monkeypatch.setattr(
        "cs2webui.host.agent.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, "server log", ""),
    )
    client = TestClient(app)

    response = client.get(
        "/containers/cs2webui-primary/logs",
        headers={"X-CS2WebUI-Token": "secret-token"},
    )

    assert response.status_code == 200
    assert response.json()["stdout"] == "server log"
    assert (
        client.get(
            "/containers/not-managed/logs",
            headers={"X-CS2WebUI-Token": "secret-token"},
        ).status_code
        == 400
    )


def test_agent_parses_container_stats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_path = tmp_path / "agent.token"
    token_path.write_text("secret-token")
    monkeypatch.setenv("CS2WEBUI_AGENT_TOKEN", str(token_path))
    monkeypatch.setattr(
        "cs2webui.host.agent.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(
            args[0], 0, '[{"CPUPerc":"1.00%","MemUsage":"1GiB / 8GiB"}]', ""
        ),
    )

    response = TestClient(app).get(
        "/containers/cs2webui-primary/stats",
        headers={"X-CS2WebUI-Token": "secret-token"},
    )

    assert response.status_code == 200
    assert response.json()["stats"][0]["CPUPerc"] == "1.00%"


def test_agent_deletes_only_managed_server_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_path = tmp_path / "agent.token"
    token_path.write_text("secret-token")
    instances = tmp_path / "instances"
    server = instances / "primary" / "server"
    server.mkdir(parents=True)
    (server / "marker.txt").write_text("test")
    monkeypatch.setenv("CS2WEBUI_AGENT_TOKEN", str(token_path))
    monkeypatch.setenv("CS2WEBUI_INSTANCES_DIR", str(instances))
    client = TestClient(app)

    response = client.post(
        "/delete-server",
        headers={"X-CS2WebUI-Token": "secret-token"},
        json={"destination": str(server)},
    )

    assert response.status_code == 200
    assert not server.parent.exists()
