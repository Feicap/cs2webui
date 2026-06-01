#!/usr/bin/env bash
set -euo pipefail

MODE=""
DOMAIN=""
WEBUI_PORT=""
SYSTEM_DIR="/var/lib/cs2webui-system"
CADDY_TEMPLATE="${SYSTEM_DIR}/share/cs2webui-caddy.container.in"
PANEL_TEMPLATE="${SYSTEM_DIR}/share/cs2webui-panel.container.in"
MANIFEST="${SYSTEM_DIR}/install-manifest.env"

fail() {
  printf 'CS2 WebUI access configuration error: %s\n' "$*" >&2
  exit 1
}

validate_path() {
  local label="$1"
  local value="$2"
  [[ "${value}" =~ ^/[A-Za-z0-9._/-]+$ ]] \
    || fail "${label} contains unsupported characters"
  [[ "${value}" != *".."* ]] || fail "${label} must not contain .."
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    --domain)
      DOMAIN="${2:-}"
      shift 2
      ;;
    --webui-port)
      WEBUI_PORT="${2:-}"
      shift 2
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

[[ "${EUID}" -eq 0 ]] || fail "run this script with sudo"
[[ "${MODE}" =~ ^(local|ip|domain)$ ]] || fail "mode must be local, ip, or domain"
[[ "${WEBUI_PORT}" =~ ^[0-9]+$ ]] || fail "WebUI port is required"
(( WEBUI_PORT >= 1024 && WEBUI_PORT <= 65535 )) || fail "invalid WebUI port"
[[ -f "${MANIFEST}" ]] || fail "install manifest not found: ${MANIFEST}"
[[ -f "${PANEL_TEMPLATE}" ]] || fail "panel Quadlet template not found: ${PANEL_TEMPLATE}"
[[ "$(stat -c '%u' "${MANIFEST}")" == "0" ]] || fail "install manifest must be root-owned"
[[ -z "$(find "${MANIFEST}" -perm /022 -print -quit)" ]] \
  || fail "install manifest must not be group or world writable"

# The manifest is root-owned and written by install.sh with fixed scalar values.
# shellcheck disable=SC1090
source "${MANIFEST}"
[[ "${SERVICE_USER}" =~ ^[a-z_][a-z0-9_-]*$ ]] || fail "invalid service user"
validate_path "DATA_DIR" "${DATA_DIR}"
[[ "${DATA_DIR}" == /var/lib/* ]] \
  || fail "refusing DATA_DIR outside /var/lib: ${DATA_DIR}"
secure_cookies=false
if [[ "${MODE}" == "domain" ]]; then
  secure_cookies=true
fi

uid="$(id -u "${SERVICE_USER}")"
panel_quadlet="/home/${SERVICE_USER}/.config/containers/systemd/cs2webui-panel.container"
sed \
  -e "s|__WEBUI_PORT__|${WEBUI_PORT}|g" \
  -e "s|__DATA_DIR__|${DATA_DIR}|g" \
  -e "s|__SECURE_COOKIES__|${secure_cookies}|g" \
  "${PANEL_TEMPLATE}" > "${panel_quadlet}"
chown "${SERVICE_USER}:${SERVICE_USER}" "${panel_quadlet}"
runuser -u "${SERVICE_USER}" -- env \
  HOME="/home/${SERVICE_USER}" \
  XDG_RUNTIME_DIR="/run/user/${uid}" \
  systemctl --user daemon-reload
runuser -u "${SERVICE_USER}" -- env \
  HOME="/home/${SERVICE_USER}" \
  XDG_RUNTIME_DIR="/run/user/${uid}" \
  systemctl --user restart cs2webui-panel.service

if [[ "${MODE}" != "domain" ]]; then
  systemctl disable --now cs2webui-caddy.service >/dev/null 2>&1 || true
  rm -f -- /etc/containers/systemd/cs2webui-caddy.container
  rm -f -- /etc/cs2webui/Caddyfile
  systemctl daemon-reload
  printf 'WebUI is available on TCP port %s.\n' "${WEBUI_PORT}"
  printf 'Open that port in the active firewall and router if external access is required.\n'
  exit 0
fi

[[ "${DOMAIN}" =~ ^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$ ]] \
  || fail "invalid domain"
command -v podman >/dev/null 2>&1 || fail "podman is required"
command -v systemctl >/dev/null 2>&1 || fail "systemctl is required"
[[ -f "${CADDY_TEMPLATE}" ]] || fail "Caddy Quadlet template not found: ${CADDY_TEMPLATE}"

install -d -m 755 /etc/cs2webui /etc/containers/systemd
install -d -m 755 "${SYSTEM_DIR}/caddy/data" "${SYSTEM_DIR}/caddy/config"
cat > /etc/cs2webui/Caddyfile <<EOF
${DOMAIN} {
  reverse_proxy 127.0.0.1:${WEBUI_PORT}
}
EOF
sed "s|__SYSTEM_DIR__|${SYSTEM_DIR}|g" "${CADDY_TEMPLATE}" \
  > /etc/containers/systemd/cs2webui-caddy.container
chmod 644 /etc/containers/systemd/cs2webui-caddy.container

systemctl daemon-reload
systemctl enable cs2webui-caddy.service
systemctl restart cs2webui-caddy.service

printf 'Caddy reverse proxy configured for https://%s\n' "${DOMAIN}"
printf 'Ensure TCP ports 80 and 443 are open in the active firewall and router.\n'
