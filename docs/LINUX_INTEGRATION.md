# Linux Integration Checklist

The project is currently developed from Windows but targets Linux deployment.
Keep Linux-only behavior behind host integration interfaces and record real
host verification here.

## Verified Locally

- FastAPI application startup contract.
- Static setup wizard delivery.
- SQLite setup persistence.
- Argon2 password hashing.
- Sequential TCP port suggestion behavior.
- Optional module removal without breaking core health API.
- Restricted-agent allowlist and managed-path rejection tests.
- Bazzite path contract regression tests.
- Firewall rule parsing tests for the `ufw` shape.

## Implemented But Awaiting Linux Verification

- TCP listener process discovery through `ss -H -ltnp`.
- Firewall tool and read-only rule discovery for `ufw`, `firewall-cmd`, and
  `nft`.
- Default panel data path: `/var/lib/cs2webui/panel`.
- Rootless panel and CS2 Podman builds.
- User Quadlet for the panel and rootful system Quadlet for optional Caddy.
- Restricted local host agent over Unix socket.
- Root-owned external-access helper.
- Bootstrap and uninstall scripts.
- SteamCMD installation and CS2 validation.
- Host CPU `x86-64-v2` capability and disk-capacity preflight for the Valve
  documented roughly `65 GB` per isolated CS2 installation plus backups.
- UDP port diagnostics for CS2.
- A2S challenge negotiation and multipacket RCON behavior against a live CS2
  server.
- CounterStrikeSharp bridge build with .NET SDK container and live plugin load.
- CounterStrikeSharp bridge 30-second snapshot heartbeat and `stale` status
  after a stopped or incompatible bridge.
- Managed MetaMod and CounterStrikeSharp `with-runtime` prerequisite
  installation on a live server, including `gameinfo.gi` patch verification.
- Mixed standard and Workshop rotation after actual match-end events.
- Dashboard map-drift warning after a panel-applied standard-map transition
  followed by an external plugin or manual map change.
- Local plugin installation from both a managed ZIP archive and an extracted
  folder below `/var/lib/cs2webui/imports`.
- Bash syntax check for deployment scripts. The current Windows workstation
  routes `bash` through WSL, but no WSL distribution is installed.
- Read-only post-install report through `sudo bash
  /opt/cs2webui/scripts/verify-linux.sh` or the Bazzite `/var/opt` path.

## Required Test Hosts

Start with:

- Debian 12 or current Ubuntu LTS;
- systemd;
- Podman;
- a non-root service account;
- enough disk space for one CS2 installation.

Later add a second distribution using `firewalld` to verify that diagnostics
are not tied to `ufw`.

Add a Bazzite Desktop test host:

- verify `ID=bazzite` detection;
- verify `/var/opt/cs2webui` application placement;
- verify host `python3 -m venv`;
- verify rootless Podman image builds and user Quadlet services;
- verify that installation does not use `rpm-ostree`.
- run `bash -n scripts/*.sh`;
- run the bootstrap, browser wizard, domain Caddy helper, and uninstall flow;
- build and load MetaMod, CounterStrikeSharp, and the CS2 WebUI bridge;
- validate standard-to-Workshop and Workshop-to-standard transitions.
