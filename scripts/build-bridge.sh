#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
OUTPUT="${1:-${CS2WEBUI_BRIDGE_ARCHIVE:-/var/lib/cs2webui/imports/cs2webui-bridge.zip}}"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

command -v podman >/dev/null 2>&1 || {
  printf 'podman is required to build the bridge plugin.\n' >&2
  exit 1
}
command -v python3 >/dev/null 2>&1 || {
  printf 'python3 is required to package the bridge plugin.\n' >&2
  exit 1
}

mkdir -p -- "$(dirname -- "${OUTPUT}")" "${WORK_DIR}/publish"
podman run --rm \
  --userns keep-id \
  --volume "${SOURCE_DIR}:/src:Z" \
  --volume "${WORK_DIR}/publish:/out:Z" \
  mcr.microsoft.com/dotnet/sdk:8.0 \
  dotnet publish /src/bridge-plugin/CS2WebUI.Bridge/CS2WebUI.Bridge.csproj \
    --configuration Release \
    --output /out

PACKAGE_DIR="${WORK_DIR}/package/game/csgo/addons/counterstrikesharp/plugins/CS2WebUI.Bridge"
mkdir -p -- "${PACKAGE_DIR}"
cp -a "${WORK_DIR}/publish/." "${PACKAGE_DIR}/"
(
  cd -- "${WORK_DIR}/package"
  python3 -m zipfile -c "${OUTPUT}" game
)
printf 'Bridge archive created: %s\n' "${OUTPUT}"
