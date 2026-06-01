#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${CS2WEBUI_DATA_DIR:-/var/lib/cs2webui}"
SYSTEM_DIR="/var/lib/cs2webui-system"
MANIFEST="${SYSTEM_DIR}/install-manifest.env"
PURGE_PANEL_DATA=false
PURGE_INSTANCES=false
PURGE_ALL=false

fail() {
  printf 'CS2 WebUI uninstall error: %s\n' "$*" >&2
  exit 1
}

validate_removal_target() {
  local label="$1"
  local value="$2"
  [[ "${value}" =~ ^/[A-Za-z0-9._/-]+$ ]] \
    || fail "${label} contains unsupported characters"
  [[ "${value}" != *".."* ]] || fail "${label} must not contain .."
  case "${value}" in
    "/"|"/opt"|"/var"|"/var/lib"|"/var/opt"|"/home"|"/usr")
      fail "refusing unsafe ${label}: ${value}"
      ;;
  esac
}

[[ "${EUID}" -eq 0 ]] || fail "run this script with sudo"
[[ -f "${MANIFEST}" ]] || fail "install manifest not found: ${MANIFEST}"
[[ "$(stat -c '%u' "${MANIFEST}")" == "0" ]] || fail "install manifest must be root-owned"
[[ -z "$(find "${MANIFEST}" -perm /022 -print -quit)" ]] \
  || fail "install manifest must not be group or world writable"

for argument in "$@"; do
  case "${argument}" in
    --purge-panel-data)
      PURGE_PANEL_DATA=true
      ;;
    --purge-instances)
      PURGE_INSTANCES=true
      ;;
    --purge-all)
      PURGE_PANEL_DATA=true
      PURGE_INSTANCES=true
      PURGE_ALL=true
      ;;
    *)
      fail "unknown argument: ${argument}"
      ;;
  esac
done

# The manifest is written by install.sh with fixed scalar values.
# shellcheck disable=SC1090
source "${MANIFEST}"
[[ "${SERVICE_USER}" =~ ^[a-z_][a-z0-9_-]*$ ]] || fail "invalid service user"
validate_removal_target "INSTALL_DIR" "${INSTALL_DIR}"
validate_removal_target "DATA_DIR" "${DATA_DIR}"
validate_removal_target "SYSTEM_DIR" "${SYSTEM_DIR}"
validate_removal_target "AGENT_VENV" "${AGENT_VENV}"
[[ "${INSTALL_DIR}" == /opt/* || "${INSTALL_DIR}" == /var/opt/* ]] \
  || fail "refusing INSTALL_DIR outside /opt or /var/opt: ${INSTALL_DIR}"
[[ "${DATA_DIR}" == /var/lib/* ]] \
  || fail "refusing DATA_DIR outside /var/lib: ${DATA_DIR}"
[[ "${AGENT_VENV}" == "/home/${SERVICE_USER}/.local/share/cs2webui-agent-venv" ]] \
  || fail "refusing unexpected AGENT_VENV: ${AGENT_VENV}"

case "${INSTALL_DIR}" in
  "${DATA_DIR}"|"${DATA_DIR}/"*|*".."*)
    fail "refusing to remove install directory inside preserved data: ${INSTALL_DIR}"
    ;;
esac

uid="$(id -u "${SERVICE_USER}")"
runuser -u "${SERVICE_USER}" -- env \
  HOME="/home/${SERVICE_USER}" \
  XDG_RUNTIME_DIR="/run/user/${uid}" \
  systemctl --user disable --now cs2webui-panel.service || true
runuser -u "${SERVICE_USER}" -- env \
  HOME="/home/${SERVICE_USER}" \
  XDG_RUNTIME_DIR="/run/user/${uid}" \
  systemctl --user disable --now cs2webui-agent.service || true

quadlet="/home/${SERVICE_USER}/.config/containers/systemd/cs2webui-panel.container"
agent_service="/home/${SERVICE_USER}/.config/systemd/user/cs2webui-agent.service"
rm -f -- "${quadlet}"
rm -f -- "${agent_service}"
runuser -u "${SERVICE_USER}" -- env \
  HOME="/home/${SERVICE_USER}" \
  XDG_RUNTIME_DIR="/run/user/${uid}" \
  systemctl --user daemon-reload || true

rm -rf -- "${INSTALL_DIR}"
rm -rf -- "${AGENT_VENV}"
rm -f -- "${DATA_DIR}/agent.sock" "${DATA_DIR}/agent.token"
systemctl disable --now cs2webui-caddy.service || true
rm -f -- /etc/containers/systemd/cs2webui-caddy.container
rm -rf -- /etc/cs2webui
systemctl daemon-reload
rm -rf -- "${SYSTEM_DIR}"

printf 'Panel code and service were removed.\n'

if [[ "${PURGE_PANEL_DATA}" == true ]]; then
  rm -rf -- "${DATA_DIR}/panel"
  printf 'Panel settings were removed.\n'
else
  printf 'Panel settings remain at: %s/panel\n' "${DATA_DIR}"
fi

if [[ "${PURGE_INSTANCES}" == true ]]; then
  printf 'Type DELETE-CS2-INSTANCES to permanently remove %s/instances: ' "${DATA_DIR}"
  read -r confirmation
  [[ "${confirmation}" == "DELETE-CS2-INSTANCES" ]] \
    || fail "instance removal was not confirmed"
  rm -rf -- "${DATA_DIR}/instances"
  printf 'CS2 instance files were removed.\n'
else
  printf 'CS2 data was preserved at: %s/instances\n' "${DATA_DIR}"
fi

if [[ "${PURGE_ALL}" == true ]]; then
  command -v userdel >/dev/null 2>&1 \
    || fail "userdel is required for --purge-all"
  printf 'Type DELETE-CS2WEBUI-USER to remove %s and service user %s: ' \
    "${DATA_DIR}" "${SERVICE_USER}"
  read -r confirmation
  [[ "${confirmation}" == "DELETE-CS2WEBUI-USER" ]] \
    || fail "full panel removal was not confirmed"
  rm -rf -- "${DATA_DIR}"
  loginctl disable-linger "${SERVICE_USER}" || true
  userdel --remove "${SERVICE_USER}" || true
  printf 'Panel data, service user, and rootless Podman storage were removed.\n'
fi
