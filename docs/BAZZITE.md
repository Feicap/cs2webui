# Bazzite Deployment

[Русская версия](BAZZITE.ru.md)

Bazzite is a supported deployment target for CS2 WebUI. Its container-first
model is a good fit for this project: the panel and CS2 instances run with
Podman, while Quadlet connects containers to systemd.

The installer detects `ID=bazzite` from `/etc/os-release` and uses:

```text
/var/opt/cs2webui       application code
/var/lib/cs2webui       persistent settings and CS2 instances
/var/lib/cs2webui-system root-owned helpers and optional Caddy state
```

This avoids relying on package layering or modifying the base operating-system
image.

## Requirements

Run the bootstrap from Bazzite Desktop Mode. The host must provide:

```text
podman
systemd
ss
loginctl
python3
python3 venv support
git
```

Bazzite already documents Podman and Quadlet as the preferred approach for
hosting services. The current installer checks required tools and stops with
an explicit error if one is missing. It does not invoke `rpm-ostree`.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/feicap/cs2webui/main/cs2webui.sh \
  -o cs2webui.sh
less cs2webui.sh
sudo bash cs2webui.sh
```

After installation, open the temporary URL printed by the script and continue
in the browser. The final wizard page prints the managed command for enabling
IP or domain access. Domain mode runs Caddy through a rootful system Quadlet;
the panel and CS2 instances continue to use rootless Podman.

Run the read-only host report after installation:

```bash
sudo bash /var/opt/cs2webui/scripts/verify-linux.sh
```

Shared panel, host-agent, and CS2 instance volumes use Podman's shared SELinux
label (`:z`). Caddy state stays private to the Caddy container (`:Z`).

## Uninstall

The default uninstall removes services and application code while preserving
panel settings and CS2 instances:

```bash
sudo bash /var/opt/cs2webui/scripts/uninstall.sh
```

Use `--purge-all` only when panel data, CS2 instances, and the dedicated
rootless Podman account must also be removed. The script requires explicit
typed confirmations.

## Current Verification Status

The Bazzite profile is implemented but still requires a real Bazzite host
integration run. Track results in [LINUX_INTEGRATION.md](LINUX_INTEGRATION.md).

## References

- [Bazzite: Installing and Managing Applications](https://docs.bazzite.gg/Installing_and_Managing_Software/)
- [Bazzite: Containers](https://docs.bazzite.gg/Installing_and_Managing_Software/Containers/)
- [Bazzite: Quadlet Services](https://docs.bazzite.gg/Installing_and_Managing_Software/Quadlet/)
