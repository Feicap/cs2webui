# CS2 WebUI

[Русская версия](docs/README.ru.md)

CS2 WebUI is a Linux-first control panel for installing, configuring, and
operating multiple isolated Counter-Strike 2 dedicated server instances.
The panel runs independently from the game servers, so it remains available
while an instance is stopped, updated, or repaired.

The project is under active development. The repository now contains a
functional Linux-first implementation. Real Linux, Bazzite, and live CS2
integration runs are still required before treating it as production-ready.

## Quick Install

Review the bootstrap before running it on a Linux or Bazzite host:

```bash
curl -fsSL https://raw.githubusercontent.com/feicap/cs2webui/main/cs2webui.sh \
  -o cs2webui.sh
less cs2webui.sh
sudo bash cs2webui.sh
```

Continue setup in the browser using the temporary URL printed by the script.
For host requirements, verification, and uninstall options, read the
[Linux deployment guide](docs/DEPLOYMENT.md).

## How The Finished Service Will Be Used

The installer is intentionally small. Most setup happens in the browser:

1. Run the bootstrap script on the Linux server.
2. Open the temporary WebUI address printed by the script.
3. Select the interface language.
4. Choose local access, internet access by domain, or internet access by IP.
5. Review occupied ports and accept the first available suggested port or
   enter another one.
6. Create the first administrator account.
7. Create a CS2 instance and choose whether to download, import, copy, or move
   server files.
8. Enter the CS2 port, RCON password, GSLT, starting map, and desired preset.
9. Open **Servers**, press **Install / validate**, and confirm the SteamCMD plan.
10. Press **Start** and review the masked launch command before applying it.

Create additional isolated CS2 instances from the **Servers** screen.

## Implemented Features

- Podman-only deployment with separate storage for each CS2 instance.
- Bazzite deployment profile without host package layering.
- A browser-based setup wizard shortly after running the bootstrap script.
- Server install, import, clone, update, validate, start, stop, and scheduled
  restart.
- Port conflict detection with sequential suggestions starting at `27015`.
- Launch argument preview with masked secrets.
- RCON console, logs, configuration presets, and reusable quick commands.
- Optional dashboard, Workshop library, visual map rotation, and plugin
  integration modules.
- Russian and English UI.
- Backups, scheduled maintenance, user roles, and an audit log.
- Local password sessions with Argon2 hashes, strict cookies, and login
  attempt throttling.
- Clean panel uninstall that preserves CS2 server data by default.
- Optional local Workshop preview cache, plugin checksums, URL source update
  checks, and third-party Python modules with optional UI tabs.
- Managed latest MetaMod and CounterStrikeSharp `with-runtime` prerequisite
  installation from official release APIs.
- Managed plugin installation from an HTTPS archive or a local ZIP/extracted
  folder placed below `/var/lib/cs2webui/imports`.
- Visual-rotation tracking that records panel-applied map commands and warns
  when A2S reports a different standard map.

## Architecture

```text
Browser
  |
  v
WebUI + Python API
  |
  +-- SQLite
  +-- module registry
  +-- scheduler
  |
  v
Host agent
  |
  +-- rootless Podman
  +-- SteamCMD
  +-- RCON and A2S
  +-- isolated CS2 instances
```

Optional panel modules add convenience without replacing core operations.
For example, removing the visual map rotation module still leaves manual
configuration editing and RCON commands available.

## Development Setup

Python `3.12+` is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
uvicorn cs2webui.app:create_app --factory --reload
```

Open:

```text
http://127.0.0.1:8000/api/health
```

Run tests:

```bash
pytest
```

## Selected API

```text
GET /api/health
GET /api/modules
GET /api/dashboard/summary
GET /api/setup/state
GET /api/setup/diagnostics
GET /api/instances
GET /api/instances/{id}/plugins
GET /api/rotation/{id}
```

`/api/dashboard/summary` and `/api/rotation/{id}` are contributed by optional
built-in modules. They can be removed independently without disabling core
instance management, configuration editing, or RCON commands.

## Project Notes

Architecture decisions, implementation progress, and known risks are tracked
in [docs/PROJECT_MEMORY.md](docs/PROJECT_MEMORY.md). This file is intended to
remain useful during debugging and future development.

Deployment guides:

- [Documentation index](docs/README.md)
- [Linux deployment](docs/DEPLOYMENT.md)
- [Bazzite deployment](docs/BAZZITE.md)
- [Third-party module SDK](docs/MODULES.md)
- [Linux integration checklist](docs/LINUX_INTEGRATION.md)

Project contribution and security notes:

- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md)
