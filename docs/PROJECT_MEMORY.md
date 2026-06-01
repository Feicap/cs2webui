# CS2 WebUI Project Memory

This document is the durable engineering log for the project. Update it when
requirements change, an architectural decision is made, or a non-obvious bug
is fixed. It summarizes decisions from planning conversations without storing
credentials or other secrets.

## Product Goal

Build a Linux-first WebUI for managing multiple isolated Counter-Strike 2
dedicated server instances. The panel must remain available when game servers
are offline. Deployment is Podman-only.

## Confirmed Requirements

### Core

- Use Python for backend implementation.
- Keep WebUI and CS2 instances independent.
- Support multiple CS2 instances with separate directories.
- Do not share one mutable CS2 installation between instances.
- Preserve CS2 server data when uninstalling the panel unless the user
  explicitly requests removal.
- Support Russian and English UI, with English as the primary documentation
  language and a linked Russian guide.

### Setup Wizard

- Run a minimal bootstrap script first, then move into WebUI setup as early as
  possible.
- Wizard order starts with language selection, then access mode.
- Access modes: local network, internet by domain, and internet by IP.
- Show occupied WebUI ports, suggest the first free port sequentially, and
  allow manual selection.
- For CS2, begin suggestions at port `27015` and continue sequentially.
- Diagnose firewall state and list ports that need to be opened.
- Ask for instance settings such as RCON password and GSLT.
- Offer MetaMod, CounterStrikeSharp, and the project bridge plugin during
  setup. Bridge installation is enabled by default but optional.

### Server Management

- Install with SteamCMD, import an existing installation, copy it, or move it.
- Clone an instance without copying GSLT, RCON password, or ports.
- Validate and update installations.
- Show launch arguments before starting, with secrets masked.
- Provide lifecycle operations, logs, RCON console, configuration editing,
  presets, reusable command buttons, backups, and scheduled maintenance.

### Modules

- Core operations must remain usable without optional modules.
- Modules add convenience UI and automation.
- Modules must not import each other's internal code or access each other's
  tables directly.
- Cross-module enhancements use optional capabilities exposed through core.
- Example: visual map rotation is optional; manual config editing and RCON
  still work without it.
- Example: a future SimpleAdmin manager configures the CS2 plugin through
  core APIs but is not required to install the plugin manually.

### Workshop And Rotation

- Accept a Workshop URL or numeric ID and derive `host_workshop_map <id>`.
- Fetch title and preview where possible, with manual metadata fallback.
- Keep external image URLs external by default; local files may be uploaded.
- Workshop preview caching is optional.
- Import Workshop collections by expanding them into independent map cards.
- Visual rotation module supports drag-and-drop, a persistent cycle, a
  one-time queue, history, rollback, and JSON import/export.
- Admin can change a map immediately without changing rotation, or skip to the
  next configured map.
- Bridge plugin should detect match completion and trigger Workshop rotation.

### Users And Safety

- Local login and password authentication.
- Roles: viewer, operator, admin.
- Audit log.
- Protect URL downloads against SSRF, archive extraction against path
  traversal, and installation endpoints against oversized uploads.
- Keep Podman socket away from the public WebUI.
- Use a restricted root helper only for explicitly supported system actions.

## Architecture Direction

```text
Browser
  -> WebUI and FastAPI core
      -> SQLite
      -> module registry
      -> scheduler
      -> host agent
          -> rootless Podman
          -> SteamCMD
          -> RCON and A2S
          -> isolated CS2 instances

Restricted system helper
  -> port and firewall diagnostics
  -> reverse proxy configuration
  -> systemd units
  -> panel uninstall
```

Python modules are discovered through the `cs2webui.modules` entry-point
group. Built-in modules use the same registration interface so modularity is
tested by normal development.

## Planned Delivery Order

1. Core application, module registry, health API, tests, and documentation.
2. Browser setup wizard foundation and non-mutating Linux diagnostics.
3. Bootstrap, Podman Quadlet files, restricted helper, and uninstall manifest.
4. Instance lifecycle, SteamCMD, paths, ports, and launch preview.
5. RCON, logs, config editor, presets, and quick commands.
6. Optional dashboard and A2S metrics.
7. CounterStrikeSharp bridge plugin.
8. Workshop library and visual map rotation modules.
9. CS2 plugin manager and plugin-specific convenience modules.
10. Scheduler, backup, restore, and update flows.

## Known Risks To Test On Linux

- Exact UDP port requirements for multiple concurrent CS2 instances.
- Workshop map switching and mixed standard/Workshop rotation.
- Match-end events across game modes and duplicate event handling.
- CounterStrikeSharp compatibility after CS2 updates.
- Reverse proxy and rootless Podman behavior across distributions.
- Clean uninstall without touching user-owned CS2 data.

## Change Log

### 2026-05-30

- Created repository foundation.
- Added English and Russian usage documentation.
- Added this durable project memory file.
- Added initial FastAPI core, module registry, built-in dashboard example, and
  tests.
- Installed local development dependencies and verified the initial slice:
  `python -m pytest` passed 3 tests, `python -m ruff check .` passed, and
  `python -m compileall -q src tests` passed.
- Local verification currently emits a Starlette deprecation warning about
  `httpx` in `TestClient`; it does not fail tests and should be revisited when
  dependency versions are pinned for CI.
- Added the initial browser setup wizard with responsive styling and `en` /
  `ru` translations.
- Added SQLite-backed setup state, first administrator creation with Argon2,
  sequential WebUI TCP port suggestions, and anonymous setup lockout after
  setup completion.
- Added a host diagnostics interface. Linux diagnostics use `ss -H -ltnp` for
  best-effort listener process discovery and detect `ufw`, `firewall-cmd`, or
  `nft` without mutating host configuration.
- Added [LINUX_INTEGRATION.md](LINUX_INTEGRATION.md) to keep Windows-local
  checks separate from pending Linux host verification.
- Verified the setup slice locally on Windows: `python -m pytest` passed 9
  tests, `python -m ruff check .` passed, `python -m compileall -q src tests`
  passed, and `node --check src/cs2webui/web/setup.js` passed.
- Added Linux deployment artifacts: Podman Containerfiles, a rootless panel
  Quadlet template, bootstrap install script, uninstall manifest, and explicit
  purge flags that preserve CS2 instances by default.
- Added isolated CS2 instance persistence, encrypted RCON/GSLT secrets,
  sequential UDP port suggestions starting at `27015`, and masked launch
  preview API.
- Added local cookie sessions, Argon2 login verification, viewer/operator/admin
  roles, user administration, and audit records.
- Added a restricted host agent over a Unix socket. The panel does not receive
  a Podman socket; it submits preplanned Podman argv to the local agent.
- Added built-in configuration presets, reusable quick commands, and a minimal
  Source RCON client.
- Added a Bazzite deployment profile. On `ID=bazzite`, application code is
  placed in `/var/opt/cs2webui`; persistent data remains in
  `/var/lib/cs2webui`. Installation does not invoke `rpm-ostree`.
- Added the post-setup operator SPA with dashboard, instances, RCON console,
  quick commands, Workshop cards, visual rotation, plugin management,
  configuration diff preview, maintenance, backups, users, and bridge players.
- Added focused config/addons backups, persisted restart/update policies, and
  a one-minute background maintenance runner with player-aware defer.
- Added universal CS2 plugin archive installation from managed local ZIP or
  HTTPS URL, SSRF checks, archive size limits, ZIP traversal protection, and
  file-based enable/disable.
- Added import/copy/move execution through the restricted host agent followed
  by SteamCMD validation.
- Added Workshop collection expansion into independent cards and best-effort
  host disk, RAM, and load metrics.
- Added optional CounterStrikeSharp bridge source and an advanced players
  module that reads SteamID64, bot, team, and score snapshots. Local bridge
  compilation remains pending because the current Windows environment has no
  .NET SDK.
- Restricted host-agent commands to known SteamCMD install, CS2 start, and
  container stop shapes. Volumes outside the managed instances directory are
  rejected.
- Added optional Workshop library and visual map rotation modules. Workshop
  cards accept Steam URLs or IDs and support manual metadata fallback. Rotation
  stores a cycle, one-time queue, history, and generates safe standard or
  Workshop map commands.
- Replaced the dashboard placeholder with A2S_INFO polling and soft offline
  degradation.
- Verified the current Windows-local slice: `python -m pytest` passed 32
  tests, `python -m ruff check .` passed, `python -m compileall -q src tests`
  passed, and `node --check src/cs2webui/web/setup.js` passed.
- Added a managed external-access plan and a rootful Caddy Quadlet for domain
  mode. Root helpers and Caddy state live in root-owned
  `/var/lib/cs2webui-system`, independent of `/opt` versus `/var/opt` code
  placement and separate from service-owned panel data.
- Added read-only host-agent endpoints for managed-container logs and Podman
  stats. The server screen can load per-instance CPU, RAM, and recent logs
  without exposing a Podman socket to the panel.
- Added `--replace` to planned CS2 container starts so a stopped named
  container can be started again without an avoidable name conflict.
- Added Podman-based bridge packaging through `scripts/build-bridge.sh` and a
  WebUI action that installs the built bridge archive through the protected
  plugin archive pipeline. CounterStrikeSharp prerequisites remain a separate
  host integration step.
- Verified the latest Windows-local slice: `python -m pytest` passed 59 tests,
  `python -m ruff check .` passed, `python -m compileall -q src tests` passed,
  and `node --check src/cs2webui/web/panel.js` passed.
- Expanded visual rotation UI with one-time queue management, history restore,
  and JSON import/export while keeping the module optional.
- Expanded administration UI with local role creation and audit-log display.
- Added instance cloning as an explicit copy workflow with newly supplied
  RCON/GSLT secrets. Added separate metadata removal and confirmed managed-file
  purge through the restricted host agent.
- Surfaced the managed external-access plan on the final setup-wizard screen,
  including URL, firewall ports, helper command, and generated Caddyfile.
- Verified the latest Windows-local slice: `python -m pytest` passed 62 tests,
  `python -m ruff check .` passed, `python -m compileall -q src tests` passed,
  and both browser JavaScript files passed `node --check`.
- Added EN/RU language persistence from the setup wizard into the operator
  panel, with an in-panel language switch and localized navigation/actions.
- Extended third-party module manifests with optional same-origin iframe UI
  pages and documented the entry-point SDK in English and Russian.
- Added Workshop manual metadata fields and opt-in local preview caching with
  HTTPS-only public-address checks, redirect validation, supported-image MIME
  checks, and a 5 MiB limit.
- Added masked lifecycle-plan confirmation in the WebUI before install, start,
  or stop execution.
- Fixed new maintenance policies so their interval starts when saved instead
  of being due immediately. Added configurable warning lead time, calculated
  next-run timestamps, and global planned-restart notices.
- Added SHA-256 metadata for installed plugin archives and opt-in HTTPS source
  comparison without automatic update application.
- Verified the latest Windows-local slice: `python -m pytest` passed 65 tests,
  `python -m ruff check .` passed, `python -m compileall -q src tests` passed,
  and both browser JavaScript files passed `node --check`.
- Added separate dashboard degradation states for A2S, RCON, bridge snapshots,
  host-agent health, Steam profile enrichment, and Workshop metadata.
- Made Workshop cards and visual-rotation transitions execute map switches
  through RCON. Rotation advances only after successful RCON execution.
- Added best-effort read-only firewall rule reporting for `ufw`,
  `firewall-cmd`, and `nft` in the first-run diagnostics.
- Added persisted custom quick RCON commands with inferred `{parameter}`
  prompts, WebUI creation/removal, and audit records.
- Added estimated next-map display on dashboard as a graceful frontend
  enhancement when the optional visual-rotation module is installed.
- Versioned built-in presets and expanded the Linux bridge path: install.sh
  attempts a non-fatal Podman SDK bridge build, successful CS2 install actions
  auto-install the archive when available, and WebUI initially offered a
  fixed CounterStrikeSharp archive action. This was later replaced by latest
  stable release resolution together with managed MetaMod installation.
- Verified the latest Windows-local slice: `python -m pytest` passed 70 tests,
  `python -m ruff check .` passed, `python -m compileall -q src tests` passed,
  and both browser JavaScript files passed `node --check`.
- Expanded RU operator-panel translations for the primary screens and actions.
- Final Windows-local verification still passes 70 tests, Ruff, compileall,
  and both JavaScript syntax checks. Local `dotnet --version` confirms that no
  .NET SDK is installed. `bash -n scripts/*.sh` could not run because this
  Windows workstation has no configured WSL distribution. Both checks remain
  explicit Linux-host integration items.
- Added per-card browser upload for Workshop preview images. Uploads are
  limited to supported image MIME types and 5 MiB, stored in the optional
  local media cache, and served back through the Workshop module.
- Final Windows-local verification passes 71 tests, Ruff, compileall, and both
  JavaScript syntax checks.
- Hardened Linux/Bazzite deployment handover: the selected WebUI port is
  rendered into the rootless panel Quadlet, domain mode enables secure session
  cookies, and leaving domain mode disables stale Caddy state.
- Restricted installer and uninstall paths to managed `/opt`, `/var/opt`, and
  `/var/lib` prefixes. Root-owned manifests are validated before privileged
  helpers source them.
- Added maximum player-defer enforcement for scheduled maintenance, resilient
  background cycles, focused backup restore, ZIP expansion limits, symlink
  rejection, and streaming Workshop preview uploads.
- Fixed viewer panel access and operator lifecycle permissions. The SPA now
  hides optional module tabs when modules are removed, falls back from a
  missing dashboard to the core Servers page, and polls planned restart
  notices.
- Added safe managed MetaMod installation from the official latest Linux
  release tarball, including idempotent `gameinfo.gi` patching. Replaced the
  pinned CounterStrikeSharp archive with latest official Linux `with-runtime`
  release resolution. Both prerequisites are offered by default in the setup
  wizard and remain soft-failing optional integrations.
- Extended bridge snapshots on player connect, disconnect, and death events.
  Processed match-end markers are deleted so panel restarts cannot repeat an
  old rotation transition.
- Latest Windows-local verification passes 93 tests, Ruff, compileall, and both
  JavaScript syntax checks. Live Linux/Bazzite, Podman Quadlet, MetaMod,
  CounterStrikeSharp, bridge compilation, and CS2 rotation checks remain
  explicit integration items.
- Added sequential CS2 UDP port display and a pre-start conflict recheck,
  installer dependency preflight, explicit `--purge-all`, and shared SELinux
  `:z` labels for panel, host-agent, and CS2 instance volumes on Bazzite.
- Moved the bridge filesystem contract into core so optional builtin modules
  do not import each other. Added runtime `meta list` reporting and made a
  required maintenance backup failure stop the scheduled update/restart.
- Added Valve A2S_INFO challenge negotiation and Source RCON multipacket
  response collection. External bridge, Steam profile, and Workshop metadata
  JSON contracts now fail as controlled degradation instead of uncaught
  server errors.
- Added a 30-second CounterStrikeSharp bridge snapshot heartbeat and shared
  `available`/`stale`/`unavailable` bridge status. The plugin now targets the
  published stable CounterStrikeSharp API `1.0.368`; live compatibility with
  the latest installed runtime remains a Linux integration check.
- Aligned SPA controls with backend roles: viewer screens are read-only,
  operators retain daily runtime controls, and administrator-only plugin,
  maintenance, configuration, and quick-command edits are hidden from other
  roles.
- Added MetaMod TAR traversal regression coverage. Latest Windows-local
  verification passes 112 tests, Ruff, compileall, and both JavaScript syntax
  checks. Live Linux/Bazzite, Podman Quadlet, MetaMod, CounterStrikeSharp,
  bridge compilation, and CS2 rotation checks remain explicit integration
  items.
- Isolated optional module discovery and router-mount failures. A broken
  third-party entry point is logged and exposed as unavailable without taking
  down core panel routes.
- Locked initial setup mutation routes after the first administrator is
  created, limited anonymous completed-state output, escaped setup diagnostics
  in the SPA, and kept access-plan recovery available only to an authenticated
  administrator.
- Tightened the host-agent volume contract to the exact managed
  `<instances>/<slug>/server` destination instead of permitting nested
  arbitrary paths.
- Added managed plugin installation from a local extracted folder as well as
  ZIP archives. Local sources must remain below `/var/lib/cs2webui/imports`;
  directory installs reject symbolic links, unsupported entries, conflicting
  files, and oversized trees.
- Added an administrator WebUI action for running maintenance immediately.
- Recorded panel-applied rotation commands after both manual and bridge-driven
  transitions. The dashboard now warns when A2S reports a different standard
  map, while Workshop commands remain visible without an unreliable
  ID-to-map-name comparison. Invalid bridge match markers are removed after a
  controlled error instead of being retried forever.
- Hardened domain setup validation in both FastAPI and the root-owned access
  helper, and preserved the selected browser language when a completed setup
  state intentionally returns only minimal public data.
- Escaped reusable SPA button labels so administrator-defined quick-command
  names cannot inject markup into the operator panel.
- Latest Windows-local verification passes 124 tests, Ruff, compileall, and
  both JavaScript syntax checks. Real Linux/Bazzite bootstrap, Podman Quadlet,
  rootful Caddy handover, live CS2, MetaMod, CounterStrikeSharp, bridge load,
  and mixed Workshop rotation remain explicit host integration checks.
- Rechecked the deployment contract against Valve's current CS2 dedicated
  server wiki: use appid `730`, launch through `game/cs2.sh`, require Linux
  glibc `2.31+` and an `x86-64-v2` CPU, and plan for roughly `65 GB` per
  isolated server installation before backup growth.
- Added core instance-capacity preflight data and visible warnings in both the
  first-server wizard and the regular instance-creation form. The warning
  remains available when the optional dashboard module is removed.
- Latest Windows-local verification after capacity preflight passes 125 tests,
  Ruff, compileall, and both JavaScript syntax checks.
- Added `scripts/verify-linux.sh`, a read-only post-install report for Linux
  and Bazzite. It checks host commands, glibc `2.31+`, POPCNT/SSE4.2, free
  disk, deployment shell syntax, rootless Podman images, user services, and
  the restricted host-agent socket. Live execution remains a Linux-host item.
- Added the root-level `cs2webui.sh` bootstrap entry point and updated Linux
  and Bazzite guides to use it. The older `scripts/bootstrap.sh` checkout
  entry point remains available for compatibility.
- Latest Windows-local verification after the bootstrap entry point passes
  127 tests, Ruff, compileall, and both JavaScript syntax checks.
- Added an in-process login failure limiter keyed by client host and normalized
  username. After five failed attempts within one minute, the login endpoint
  returns `429` until the short window expires. Domain mode already enables
  secure strict session cookies through the access helper.
- Bounded the login limiter to 4096 tracked failure keys and avoided allocating
  state for read-only checks, preventing unbounded memory growth from floods
  of invented usernames.
- Final Windows-local verification passes 129 tests, Ruff, compileall, and
  both JavaScript syntax checks. The remaining verification boundary is a
  real Linux/Bazzite host with Podman and a live CS2 server.
- Prepared the project for GitHub publication: added a documentation index,
  prominent EN/RU bootstrap instructions, `CONTRIBUTING.md`, `SECURITY.md`,
  and `CHANGELOG.md`. License selection remains an explicit repository-owner
  decision rather than an inferred default.
- GitHub publication audit: the connected account is `Feicap`, no existing
  `cs2webui` repository is visible, the available GitHub connector does not
  expose repository creation, and the local workstation has no `gh` CLI.
- Initialized the local Git repository on `main` and added `.gitattributes`
  with LF normalization so Linux shell scripts remain executable after edits
  from Windows. Windows-native batch and PowerShell files retain CRLF if added
  later.
- Created the local publication baseline commit:
  `6919fb0 Initial CS2 WebUI implementation`. Markdown relative links,
  deployment tests, staged whitespace checks, and shell-file LF attributes
  were verified before committing.
- GitHub remote publication is pending creation of the empty
  `Feicap/cs2webui` repository. The connected GitHub App can inspect installed
  repositories but cannot create a new one, `gh` is not installed locally,
  and no non-interactive `GH_TOKEN` or `GITHUB_TOKEN` is present.
