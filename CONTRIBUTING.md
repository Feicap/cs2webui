# Contributing

Thanks for helping improve CS2 WebUI. The project targets Linux and Bazzite,
even when code is edited from another operating system.

## Development Setup

Use Python `3.12+`:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
uvicorn cs2webui.app:create_app --factory --reload
```

## Before Submitting A Change

Run:

```bash
python -m pytest
python -m ruff check .
python -m compileall -q src tests
node --check src/cs2webui/web/setup.js
node --check src/cs2webui/web/panel.js
```

On Linux, also run:

```bash
bash -n cs2webui.sh scripts/*.sh
sudo bash scripts/verify-linux.sh
```

## Design Rules

- Keep Podman as the only supported container runtime.
- Preserve isolated storage for every CS2 instance.
- Keep the core useful when optional dashboard, Workshop, player, or rotation
  modules are absent.
- Do not introduce a dependency from one optional module to another.
- Mask GSLT and RCON secrets in previews and logs.
- Treat URL-based plugin installation as untrusted input.
- Add focused regression tests for changed behavior.
- Update `docs/PROJECT_MEMORY.md` when a decision, verification checkpoint, or
  integration risk changes.

## Linux Integration

Windows-local tests cannot prove Podman, Quadlet, Caddy, SteamCMD, MetaMod,
CounterStrikeSharp, or live Workshop rotation behavior. Record real-host
results in [docs/LINUX_INTEGRATION.md](docs/LINUX_INTEGRATION.md).
