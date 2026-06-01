# Linux Deployment

CS2 WebUI targets a Linux host with systemd and Podman. The current scripts
are an initial deployment slice and still require verification on a real Linux
host before production use.

## Requirements

- Debian 12 or a current Ubuntu LTS release;
- `systemd`;
- `podman`;
- `ss` from `iproute2`;
- `loginctl`;
- root access for the bootstrap step.

For each isolated CS2 instance, reserve at least `65 GB` plus backup space.
Valve currently documents Linux `glibc 2.31+` and an `x86-64-v2` CPU with
POPCNT/SSE4.2 for CS2. The game container uses Debian 12 and launches the
downloaded server through `game/cs2.sh`.

Valve reference:
[Counter-Strike 2 - Dedicated Servers](https://developer.valvesoftware.com/wiki/Counter-Strike_2/Dedicated_Servers).

## Install From A Checked-Out Repository

```bash
git clone https://github.com/feicap/cs2webui.git
cd cs2webui
sudo bash scripts/install.sh
```

For a minimal GitHub bootstrap:

```bash
curl -fsSL https://raw.githubusercontent.com/feicap/cs2webui/main/cs2webui.sh \
  -o cs2webui.sh
less cs2webui.sh
sudo bash cs2webui.sh
```

The script:

1. Creates the `cs2webui` service user if needed.
2. Copies application code to `/opt/cs2webui`.
3. Creates persistent data below `/var/lib/cs2webui`.
   Root-owned system helpers are stored separately below
   `/var/lib/cs2webui-system`.
4. Enables lingering for the service user.
5. Builds the panel image with rootless Podman.
6. Installs a user Quadlet unit.
7. Selects the first available TCP port starting at `8080`.
8. Prints the temporary browser setup URL.

Override defaults with environment variables:

```bash
sudo CS2WEBUI_PORT_START=8180 \
  CS2WEBUI_INSTALL_DIR=/opt/cs2webui \
  CS2WEBUI_DATA_DIR=/var/lib/cs2webui \
  bash scripts/install.sh
```

After installation, run the read-only Linux verification report:

```bash
sudo bash /opt/cs2webui/scripts/verify-linux.sh
```

On Bazzite, use `/var/opt/cs2webui/scripts/verify-linux.sh`. The report checks
host prerequisites, Valve CPU and disk requirements, shell syntax, rootless
Podman images, user services, and the restricted agent socket.

## Uninstall The Panel

```bash
sudo bash /opt/cs2webui/scripts/uninstall.sh
```

The uninstall script removes panel code and its Quadlet service. It preserves:

```text
/var/lib/cs2webui/instances
/var/lib/cs2webui/panel
```

This behavior is intentional. CS2 installations and panel settings must not
be deleted by an ordinary uninstall.

Remove panel settings as well:

```bash
sudo bash /opt/cs2webui/scripts/uninstall.sh --purge-panel-data
```

Removing CS2 instances requires a separate explicit flag and typed
confirmation:

```bash
sudo bash /opt/cs2webui/scripts/uninstall.sh --purge-panel-data --purge-instances
```

For a complete removal, including all managed data, the dedicated service
user, and its rootless Podman storage, use:

```bash
sudo bash /opt/cs2webui/scripts/uninstall.sh --purge-all
```

This mode requires typed confirmations before deleting CS2 files and before
removing the service user.

## Build The Optional Bridge

The advanced player list and automatic Workshop rotation after a match use the
optional CounterStrikeSharp bridge. The installer attempts this build by
default without making a failure fatal. Rebuild its archive manually on the
Linux host through Podman:

```bash
bash /opt/cs2webui/scripts/build-bridge.sh
```

The script pulls the .NET 8 SDK container and writes:

```text
/var/lib/cs2webui/imports/cs2webui-bridge.zip
```

The instance wizard offers MetaMod, CounterStrikeSharp, and the bridge as
recommended options. After SteamCMD succeeds, the panel resolves the latest
official Linux MetaMod tarball and latest CounterStrikeSharp `with-runtime`
archive, installs the selected prerequisites, and adds the built bridge archive
when available. The same actions are available manually on **Plugins**.
Restart the CS2 server and verify `meta list` through the console. The panel
remains functional when an optional component is absent or temporarily
incompatible with a CS2 update.

## Install A Local Plugin Archive Or Folder

Copy a trusted ZIP archive or extracted plugin folder below:

```text
/var/lib/cs2webui/imports
```

Open **Plugins**, select **Managed local archive / folder**, and enter the
relative item name, such as `simpleadmin.zip` or `simpleadmin-release`.
The panel validates archive paths, rejects symbolic links and conflicting
files, and enforces extraction limits before copying files into the selected
instance. HTTPS archive installation is also available for trusted release
URLs.
