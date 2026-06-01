#!/usr/bin/env bash
set -euo pipefail

SERVICE_USER="${CS2WEBUI_USER:-cs2webui}"
OS_ID="unknown"
if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  OS_ID="${ID:-unknown}"
fi
DEFAULT_INSTALL_DIR="/opt/cs2webui"
if [[ "${OS_ID}" == "bazzite" ]]; then
  DEFAULT_INSTALL_DIR="/var/opt/cs2webui"
fi
INSTALL_DIR="${CS2WEBUI_INSTALL_DIR:-${DEFAULT_INSTALL_DIR}}"
DATA_DIR="${CS2WEBUI_DATA_DIR:-/var/lib/cs2webui}"
SYSTEM_DIR="/var/lib/cs2webui-system"
PORT_START="${CS2WEBUI_PORT_START:-8080}"
BUILD_BRIDGE="${CS2WEBUI_BUILD_BRIDGE:-true}"
MANIFEST="${SYSTEM_DIR}/install-manifest.env"
AGENT_VENV="/home/${SERVICE_USER}/.local/share/cs2webui-agent-venv"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

fail() {
  printf 'CS2 WebUI install error: %s\n' "$*" >&2
  exit 1
}

validate_path() {
  local label="$1"
  local value="$2"
  [[ "${value}" =~ ^/[A-Za-z0-9._/-]+$ ]] \
    || fail "${label} must be an absolute path without spaces or shell metacharacters"
  [[ "${value}" != *".."* ]] || fail "${label} must not contain .."
  case "${value}" in
    "/"|"/opt"|"/var"|"/var/lib"|"/var/opt"|"/home"|"/usr")
      fail "${label} is too broad: ${value}"
      ;;
  esac
}

require_root() {
  [[ "${EUID}" -eq 0 ]] || fail "run this script with sudo"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

find_free_port() {
  local port="${PORT_START}"
  while ss -H -ltn "sport = :${port}" | grep -q .; do
    port=$((port + 1))
    [[ "${port}" -le 65535 ]] || fail "no free TCP port found"
  done
  printf '%s' "${port}"
}

run_as_service() {
  local uid
  uid="$(id -u "${SERVICE_USER}")"
  runuser -u "${SERVICE_USER}" -- env \
    HOME="/home/${SERVICE_USER}" \
    XDG_RUNTIME_DIR="/run/user/${uid}" \
    "$@"
}

require_root
[[ "${SERVICE_USER}" =~ ^[a-z_][a-z0-9_-]*$ ]] || fail "invalid service user"
[[ "${PORT_START}" =~ ^[0-9]+$ ]] || fail "invalid starting WebUI port"
(( PORT_START >= 1024 && PORT_START <= 65535 )) || fail "invalid starting WebUI port"
validate_path "INSTALL_DIR" "${INSTALL_DIR}"
validate_path "DATA_DIR" "${DATA_DIR}"
validate_path "SYSTEM_DIR" "${SYSTEM_DIR}"
[[ "${INSTALL_DIR}" == /opt/* || "${INSTALL_DIR}" == /var/opt/* ]] \
  || fail "INSTALL_DIR must stay below /opt or /var/opt"
[[ "${DATA_DIR}" == /var/lib/* ]] \
  || fail "DATA_DIR must stay below /var/lib"
[[ "${INSTALL_DIR}" != "${DATA_DIR}" && "${INSTALL_DIR}" != "${DATA_DIR}/"* ]] \
  || fail "INSTALL_DIR must stay outside DATA_DIR"
[[ "${SYSTEM_DIR}" != "${DATA_DIR}" && "${SYSTEM_DIR}" != "${DATA_DIR}/"* ]] \
  || fail "SYSTEM_DIR must stay outside DATA_DIR"
require_command podman
require_command ss
require_command loginctl
require_command python3
require_command runuser
require_command systemctl
require_command useradd
require_command realpath
require_command grep
require_command sed
require_command install
require_command cp
require_command chown
require_command chmod
require_command hostname
require_command awk
python3 -m venv --help >/dev/null 2>&1 \
  || fail "python3 venv support is required"
[[ "$(realpath -m "${SOURCE_DIR}")" != "$(realpath -m "${INSTALL_DIR}")" ]] \
  || fail "run the installer from a checkout outside INSTALL_DIR"

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${DATA_DIR}"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${DATA_DIR}/panel"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${DATA_DIR}/instances"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${INSTALL_DIR}"
install -d -m 755 "${SYSTEM_DIR}/bin" "${SYSTEM_DIR}/share"
chown -R root:root "${SYSTEM_DIR}"
chmod 755 "${SYSTEM_DIR}" "${SYSTEM_DIR}/bin" "${SYSTEM_DIR}/share"
cp -a "${SOURCE_DIR}/." "${INSTALL_DIR}/"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"
install -m 755 "${SOURCE_DIR}/scripts/apply-access.sh" \
  "${SYSTEM_DIR}/bin/apply-access.sh"
install -m 644 "${SOURCE_DIR}/deploy/quadlet/cs2webui-caddy.container.in" \
  "${SYSTEM_DIR}/share/cs2webui-caddy.container.in"
install -m 644 "${SOURCE_DIR}/deploy/quadlet/cs2webui-panel.container.in" \
  "${SYSTEM_DIR}/share/cs2webui-panel.container.in"

loginctl enable-linger "${SERVICE_USER}"
uid="$(id -u "${SERVICE_USER}")"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" "/run/user/${uid}"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" \
  "/home/${SERVICE_USER}/.config/containers/systemd"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" \
  "/home/${SERVICE_USER}/.config/systemd/user"

webui_port="$(find_free_port)"
sed \
  -e "s|__WEBUI_PORT__|${webui_port}|g" \
  -e "s|__DATA_DIR__|${DATA_DIR}|g" \
  -e "s|__SECURE_COOKIES__|false|g" \
  "${INSTALL_DIR}/deploy/quadlet/cs2webui-panel.container.in" \
  > "/home/${SERVICE_USER}/.config/containers/systemd/cs2webui-panel.container"
chown "${SERVICE_USER}:${SERVICE_USER}" \
  "/home/${SERVICE_USER}/.config/containers/systemd/cs2webui-panel.container"

run_as_service python3 -m venv "${AGENT_VENV}"
run_as_service "${AGENT_VENV}/bin/python" -m pip install "${INSTALL_DIR}"
run_as_service "${AGENT_VENV}/bin/python" -c \
  'from pathlib import Path; from secrets import token_urlsafe; Path("'"${DATA_DIR}"'/agent.token").write_text(token_urlsafe(48))'
chmod 600 "${DATA_DIR}/agent.token"
chown "${SERVICE_USER}:${SERVICE_USER}" "${DATA_DIR}/agent.token"
sed \
  -e "s|__DATA_DIR__|${DATA_DIR}|g" \
  -e "s|__AGENT_VENV__|${AGENT_VENV}|g" \
  "${INSTALL_DIR}/deploy/systemd/cs2webui-agent.service.in" \
  > "/home/${SERVICE_USER}/.config/systemd/user/cs2webui-agent.service"
chown "${SERVICE_USER}:${SERVICE_USER}" \
  "/home/${SERVICE_USER}/.config/systemd/user/cs2webui-agent.service"

run_as_service podman build --tag localhost/cs2webui:local "${INSTALL_DIR}"
run_as_service podman build --file "${INSTALL_DIR}/Containerfile.cs2" \
  --tag localhost/cs2webui-steamcmd:local "${INSTALL_DIR}"
run_as_service podman build --file "${INSTALL_DIR}/Containerfile.server" \
  --tag localhost/cs2webui-server:local "${INSTALL_DIR}"
if [[ "${BUILD_BRIDGE}" == "true" ]]; then
  if ! run_as_service bash "${INSTALL_DIR}/scripts/build-bridge.sh" \
    "${DATA_DIR}/imports/cs2webui-bridge.zip"; then
    printf 'Warning: optional bridge build failed. The panel remains usable.\n' >&2
  fi
fi
run_as_service systemctl --user daemon-reload
run_as_service systemctl --user enable --now cs2webui-agent.service
run_as_service systemctl --user enable --now cs2webui-panel.service

{
  printf 'SERVICE_USER=%q\n' "${SERVICE_USER}"
  printf 'INSTALL_DIR=%q\n' "${INSTALL_DIR}"
  printf 'DATA_DIR=%q\n' "${DATA_DIR}"
  printf 'SYSTEM_DIR=%q\n' "${SYSTEM_DIR}"
  printf 'WEBUI_PORT=%q\n' "${webui_port}"
  printf 'AGENT_VENV=%q\n' "${AGENT_VENV}"
} > "${MANIFEST}"
chmod 600 "${MANIFEST}"

host_ip="$(hostname -I | awk '{ print $1 }')"
printf '\nCS2 WebUI is running.\n'
printf 'Detected host profile: %s\n' "${OS_ID}"
printf 'Open: http://%s:%s/\n' "${host_ip:-127.0.0.1}" "${webui_port}"
printf 'Uninstall command: sudo %s/scripts/uninstall.sh\n' "${INSTALL_DIR}"
