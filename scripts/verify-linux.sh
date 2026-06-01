#!/usr/bin/env bash
set -euo pipefail

SERVICE_USER="${CS2WEBUI_USER:-cs2webui}"
DATA_DIR="${CS2WEBUI_DATA_DIR:-/var/lib/cs2webui}"
MIN_FREE_BYTES="${CS2WEBUI_MIN_FREE_BYTES:-69793218560}"
OS_ID="unknown"
if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  OS_ID="${ID:-unknown}"
fi
INSTALL_DIR="${CS2WEBUI_INSTALL_DIR:-/opt/cs2webui}"
if [[ "${OS_ID}" == "bazzite" ]]; then
  INSTALL_DIR="${CS2WEBUI_INSTALL_DIR:-/var/opt/cs2webui}"
fi
failures=0

pass() {
  printf '[PASS] %s\n' "$*"
}

warn() {
  printf '[WARN] %s\n' "$*"
}

fail() {
  printf '[FAIL] %s\n' "$*"
  failures=$((failures + 1))
}

check_command() {
  if command -v "$1" >/dev/null 2>&1; then
    pass "command available: $1"
  else
    fail "required command missing: $1"
  fi
}

run_as_service() {
  local uid
  uid="$(id -u "${SERVICE_USER}")"
  runuser -u "${SERVICE_USER}" -- env \
    HOME="/home/${SERVICE_USER}" \
    XDG_RUNTIME_DIR="/run/user/${uid}" \
    "$@"
}

printf 'CS2 WebUI Linux verification\n'
printf 'Host profile: %s\n' "${OS_ID}"
printf 'Install directory: %s\n' "${INSTALL_DIR}"
printf 'Data directory: %s\n\n' "${DATA_DIR}"

for command in awk bash df getconf grep head id podman python3 runuser sort systemctl; do
  check_command "${command}"
done

if getconf GNU_LIBC_VERSION >/dev/null 2>&1; then
  glibc_version="$(getconf GNU_LIBC_VERSION)"
  glibc_version="${glibc_version##* }"
  if [[ "$(printf '%s\n' "2.31" "${glibc_version}" | sort -V | head -n1)" == "2.31" ]]; then
    pass "glibc ${glibc_version} satisfies Valve's 2.31+ requirement"
  else
    fail "glibc ${glibc_version} is older than Valve's 2.31+ requirement"
  fi
else
  fail "could not read glibc version"
fi

if grep -qm1 -w popcnt /proc/cpuinfo && grep -qm1 -w sse4_2 /proc/cpuinfo; then
  pass "CPU exposes POPCNT and SSE4.2 for Valve's x86-64-v2 requirement"
else
  fail "CPU does not expose both POPCNT and SSE4.2"
fi

if [[ -d "${DATA_DIR}" ]]; then
  free_bytes=""
  if free_bytes="$(df -PB1 "${DATA_DIR}" | awk 'NR == 2 { print $4 }')" \
    && [[ "${free_bytes}" =~ ^[0-9]+$ ]] \
    && (( free_bytes >= MIN_FREE_BYTES )); then
    pass "disk has at least 65 GiB free before backup growth"
  else
    fail "disk has less than 65 GiB free before backup growth"
  fi
else
  fail "data directory is missing: ${DATA_DIR}"
fi

if [[ -d "${INSTALL_DIR}/scripts" ]]; then
  if bash -n "${INSTALL_DIR}"/scripts/*.sh; then
    pass "deployment shell scripts pass bash syntax checks"
  else
    fail "deployment shell scripts failed bash syntax checks"
  fi
else
  fail "installed scripts directory is missing: ${INSTALL_DIR}/scripts"
fi

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  fail "service user is missing: ${SERVICE_USER}"
else
  pass "service user exists: ${SERVICE_USER}"
  for image in \
    localhost/cs2webui:local \
    localhost/cs2webui-steamcmd:local \
    localhost/cs2webui-server:local; do
    if run_as_service podman image exists "${image}"; then
      pass "rootless Podman image exists: ${image}"
    else
      fail "rootless Podman image is missing: ${image}"
    fi
  done
  for service in cs2webui-agent.service cs2webui-panel.service; do
    if run_as_service systemctl --user is-active --quiet "${service}"; then
      pass "user service is active: ${service}"
    else
      fail "user service is not active: ${service}"
    fi
  done
fi

if [[ -S "${DATA_DIR}/agent.sock" ]]; then
  pass "restricted host-agent socket exists"
else
  fail "restricted host-agent socket is missing: ${DATA_DIR}/agent.sock"
fi

if [[ "${failures}" -gt 0 ]]; then
  printf '\nVerification completed with %s failure(s).\n' "${failures}"
  exit 1
fi

printf '\nVerification completed successfully.\n'
