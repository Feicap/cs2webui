# CS2 WebUI Bridge Plugin

This optional CounterStrikeSharp plugin provides structured state for the
panel. The core panel continues to work through A2S and RCON when the bridge is
not installed or temporarily incompatible with a CS2 update.

## Output

The plugin writes JSON atomically below its plugin directory:

```text
state/players.json
state/match-ended.json
```

`players.json` contains SteamID64, bot state, team, and score. The match marker
is updated when `EventCsWinPanelMatch` fires.

## Build

```bash
bash scripts/build-bridge.sh
```

The Linux build script uses the .NET SDK through Podman and writes a ZIP archive
below `/var/lib/cs2webui/imports`. Install CounterStrikeSharp and its
prerequisites first, then use the **Install built-in bridge** action in the
panel. The plugin currently builds against the published stable
CounterStrikeSharp API `1.0.368`. The panel installs the latest stable Linux
`with-runtime` archive, so compatibility must be checked after CS2 and
CounterStrikeSharp updates.
