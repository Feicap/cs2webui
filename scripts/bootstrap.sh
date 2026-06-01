#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="${CS2WEBUI_REPOSITORY:-https://github.com/feicap/cs2webui.git}"
REF="${CS2WEBUI_REF:-main}"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

if [[ "${EUID}" -ne 0 ]]; then
  printf 'Run this bootstrap with sudo.\n' >&2
  exit 1
fi

command -v git >/dev/null 2>&1 || {
  printf 'git is required to download CS2 WebUI.\n' >&2
  exit 1
}

git clone --depth 1 --branch "${REF}" "${REPOSITORY}" "${WORK_DIR}/cs2webui"
bash "${WORK_DIR}/cs2webui/scripts/install.sh"
