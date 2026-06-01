from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_root_bootstrap_downloads_repository_and_runs_installer() -> None:
    script = (ROOT / "cs2webui.sh").read_text()

    assert "https://github.com/feicap/cs2webui.git" in script
    assert 'git clone --depth 1 --branch "${REF}"' in script
    assert 'bash "${WORK_DIR}/cs2webui/scripts/install.sh"' in script


def test_access_helper_is_installed_outside_service_owned_data() -> None:
    install_script = (ROOT / "scripts" / "install.sh").read_text()
    setup_api = (ROOT / "src" / "cs2webui" / "api" / "setup.py").read_text()

    assert 'SYSTEM_DIR="/var/lib/cs2webui-system"' in install_script
    assert '"${SYSTEM_DIR}/bin/apply-access.sh"' in install_script
    assert "/var/lib/cs2webui-system/bin/apply-access.sh" in setup_api
    assert '"${SYSTEM_DIR}/share/cs2webui-panel.container.in"' in install_script


def test_caddy_quadlet_uses_persistent_system_directories() -> None:
    template = (
        ROOT / "deploy" / "quadlet" / "cs2webui-caddy.container.in"
    ).read_text()
    access_script = (ROOT / "scripts" / "apply-access.sh").read_text()

    assert "Volume=__SYSTEM_DIR__/caddy/data:/data:Z" in template
    assert "Volume=__SYSTEM_DIR__/caddy/config:/config:Z" in template
    assert 'sed "s|__SYSTEM_DIR__|${SYSTEM_DIR}|g"' in access_script


def test_panel_and_cs2_use_shared_selinux_labels_for_instance_data() -> None:
    panel_template = (
        ROOT / "deploy" / "quadlet" / "cs2webui-panel.container.in"
    ).read_text()
    lifecycle = (ROOT / "src" / "cs2webui" / "host" / "lifecycle.py").read_text()
    agent = (ROOT / "src" / "cs2webui" / "host" / "agent.py").read_text()

    assert "Volume=__DATA_DIR__:/data:z" in panel_template
    assert 'f"{server_dir}:/server:z"' in lifecycle
    assert 'suffix = ":/server:z"' in agent


def test_access_helper_applies_selected_panel_port_before_reverse_proxy() -> None:
    script = (ROOT / "scripts" / "apply-access.sh").read_text()

    render_position = script.index('s|__WEBUI_PORT__|${WEBUI_PORT}|g')
    restart_position = script.index("systemctl --user restart cs2webui-panel.service")
    caddy_position = script.index("cat > /etc/cs2webui/Caddyfile")

    assert render_position < restart_position < caddy_position


def test_domain_handover_enables_secure_session_cookies() -> None:
    template = (
        ROOT / "deploy" / "quadlet" / "cs2webui-panel.container.in"
    ).read_text()
    access_script = (ROOT / "scripts" / "apply-access.sh").read_text()
    install_script = (ROOT / "scripts" / "install.sh").read_text()

    assert "Environment=CS2WEBUI_SECURE_COOKIES=__SECURE_COOKIES__" in template
    assert 'secure_cookies=true' in access_script
    assert 's|__SECURE_COOKIES__|${secure_cookies}|g' in access_script
    assert 's|__SECURE_COOKIES__|false|g' in install_script


def test_access_helper_disables_stale_caddy_outside_domain_mode() -> None:
    script = (ROOT / "scripts" / "apply-access.sh").read_text()

    local_mode_position = script.index('if [[ "${MODE}" != "domain" ]]')
    disable_position = script.index(
        "systemctl disable --now cs2webui-caddy.service", local_mode_position
    )
    exit_position = script.index("exit 0", disable_position)

    assert local_mode_position < disable_position < exit_position


def test_access_helper_restarts_caddy_after_writing_domain_configuration() -> None:
    script = (ROOT / "scripts" / "apply-access.sh").read_text()

    caddyfile_position = script.index("cat > /etc/cs2webui/Caddyfile")
    restart_position = script.index("systemctl restart cs2webui-caddy.service")

    assert caddyfile_position < restart_position


def test_installer_restricts_recursive_directories_to_managed_prefixes() -> None:
    install_script = (ROOT / "scripts" / "install.sh").read_text()
    access_script = (ROOT / "scripts" / "apply-access.sh").read_text()
    uninstall_script = (ROOT / "scripts" / "uninstall.sh").read_text()

    assert '"${INSTALL_DIR}" == /opt/* || "${INSTALL_DIR}" == /var/opt/*' in (
        install_script
    )
    assert '"${DATA_DIR}" == /var/lib/*' in install_script
    assert '"${DATA_DIR}" == /var/lib/*' in access_script
    assert '"${INSTALL_DIR}" == /opt/* || "${INSTALL_DIR}" == /var/opt/*' in (
        uninstall_script
    )
    assert '"${DATA_DIR}" == /var/lib/*' in uninstall_script


def test_uninstall_validates_every_recursive_removal_target() -> None:
    script = (ROOT / "scripts" / "uninstall.sh").read_text()

    for name in ("INSTALL_DIR", "DATA_DIR", "SYSTEM_DIR", "AGENT_VENV"):
        assert f'validate_removal_target "{name}" "${{{name}}}"' in script


def test_uninstall_has_explicit_typed_full_purge_mode() -> None:
    script = (ROOT / "scripts" / "uninstall.sh").read_text()

    assert "--purge-all" in script
    assert "DELETE-CS2-INSTANCES" in script
    assert "DELETE-CS2WEBUI-USER" in script
    assert 'rm -rf -- "${DATA_DIR}"' in script
    assert 'userdel --remove "${SERVICE_USER}"' in script


def test_bridge_build_uses_podman_sdk_and_packages_game_root() -> None:
    script = (ROOT / "scripts" / "build-bridge.sh").read_text()

    assert "mcr.microsoft.com/dotnet/sdk:8.0" in script
    assert 'python3 -m zipfile -c "${OUTPUT}" game' in script


def test_linux_install_attempts_optional_bridge_build_without_making_it_fatal() -> None:
    script = (ROOT / "scripts" / "install.sh").read_text()

    assert 'BUILD_BRIDGE="${CS2WEBUI_BUILD_BRIDGE:-true}"' in script
    assert "Warning: optional bridge build failed" in script


def test_linux_installer_preflights_bazzite_host_dependencies() -> None:
    script = (ROOT / "scripts" / "install.sh").read_text()

    assert "python3 -m venv --help" in script
    assert 'require_command useradd' in script
    assert 'require_command realpath' in script
    assert 'run the installer from a checkout outside INSTALL_DIR' in script


def test_linux_verifier_checks_valve_capacity_cpu_and_rootless_services() -> None:
    script = (ROOT / "scripts" / "verify-linux.sh").read_text()

    assert 'MIN_FREE_BYTES="${CS2WEBUI_MIN_FREE_BYTES:-69793218560}"' in script
    assert "glibc ${glibc_version} satisfies Valve's 2.31+ requirement" in script
    assert "grep -qm1 -w popcnt /proc/cpuinfo" in script
    assert "grep -qm1 -w sse4_2 /proc/cpuinfo" in script
    assert "localhost/cs2webui-steamcmd:local" in script
    assert "cs2webui-panel.service" in script
    assert '"${DATA_DIR}/agent.sock"' in script


def test_panel_spa_degrades_when_optional_modules_are_removed() -> None:
    script = (ROOT / "src" / "cs2webui" / "web" / "panel.js").read_text()

    assert 'optionalPages = { dashboard: "dashboard"' in script
    assert 'if (!isPageVisible(state.page)) state.page = "instances"' in script
    assert "${escapeHtml(tr(label))}" in script
    assert "setInterval(refreshNotices, 30000)" in script
    assert 'button("Run maintenance now", "run-maintenance")' in script
    assert "/maintenance/run" in script


def test_setup_spa_escapes_host_diagnostics_and_domain_values() -> None:
    script = (ROOT / "src" / "cs2webui" / "web" / "setup.js").read_text()

    assert "escapeHtml(state.accessDomain)" in script
    assert "escapeHtml(item.process)" in script
    assert "escapeHtml(state.diagnostics.firewall)" in script
    assert "escapeHtml(error.message)" in script
    assert 'localStorage.getItem("cs2webui-language") || "en"' in script
    assert "diskCapacityHint(state.gameDiagnostics.capacity)" in script


def test_access_helper_rejects_malformed_domain_labels() -> None:
    script = (ROOT / "scripts" / "apply-access.sh").read_text()

    assert "[A-Za-z0-9-]{0,61}" in script
    assert '|| fail "invalid domain"' in script


def test_builtin_modules_do_not_import_each_other() -> None:
    modules_dir = ROOT / "src" / "cs2webui" / "modules" / "builtin"

    for module in modules_dir.glob("*.py"):
        assert "cs2webui.modules.builtin." not in module.read_text()


def test_panel_instance_form_shows_disk_capacity_preflight() -> None:
    script = (ROOT / "src" / "cs2webui" / "web" / "panel.js").read_text()

    assert "capacity.enough_for_recommended_install" in script
    assert "roughly 65 GiB per isolated CS2 installation" in script
