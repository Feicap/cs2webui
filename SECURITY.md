# Security Policy

CS2 WebUI is under active development and has not yet completed its first
production-readiness integration run on Linux or Bazzite.

## Reporting A Vulnerability

Do not publish credentials, GSLT values, RCON passwords, session cookies,
private URLs, or exploit details in a public issue.

For now, contact the repository owner privately through their GitHub profile:
[Feicap](https://github.com/Feicap). Include a minimal reproduction, affected
version or commit, and the expected impact.

## Sensitive Components

Changes require extra review when they affect:

- the root-owned external-access helper;
- the restricted host-agent Unix socket and token;
- Podman command allowlists;
- plugin archive download or extraction;
- backup restore paths;
- local sessions, roles, or login throttling;
- GSLT and RCON secret storage or masking.

## Deployment Guidance

- Prefer domain mode with HTTPS for public access.
- Review `cs2webui.sh` before running it with `sudo`.
- Keep `/var/lib/cs2webui` private and backed up.
- Do not expose the host-agent socket or token outside the host.
- Run the read-only Linux verifier after installation.
