# Changelog

All notable project changes are tracked here. The project has not published a
stable release yet.

## Unreleased

### Added

- Podman-only Linux control panel with separate CS2 instance storage.
- Bazzite deployment profile and root-level `cs2webui.sh` bootstrap.
- Browser setup wizard with EN/RU language selection and access planning.
- Restricted local host agent, lifecycle previews, RCON console, A2S status,
  presets, quick commands, backups, maintenance scheduling, roles, and audit
  log.
- Optional dashboard, Workshop library, player bridge, and visual rotation
  modules.
- MetaMod, CounterStrikeSharp `with-runtime`, bridge, HTTPS archive, local ZIP,
  and extracted-folder plugin installation paths.
- Read-only Linux verification script for host prerequisites, Valve CPU and
  disk requirements, rootless Podman images, services, and agent socket.

### Security

- Encrypted RCON and GSLT storage with masked command previews.
- Strict session cookies in domain mode and bounded login attempt throttling.
- Archive traversal, symlink, expansion-size, SSRF, and managed-path checks.
- Typed confirmations for destructive instance and full-panel removal.

### Verification

- Windows-local regression suite currently passes `129` tests plus Ruff,
  compileall, and JavaScript syntax checks.
- Real Linux/Bazzite, Podman, live CS2, plugin-load, and mixed Workshop
  rotation verification remains required before the first stable release.
