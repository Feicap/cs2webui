## Summary

Describe the change and the user-visible result.

## Verification

- [ ] `python -m pytest`
- [ ] `python -m ruff check .`
- [ ] `python -m compileall -q src tests`
- [ ] `node --check src/cs2webui/web/setup.js`
- [ ] `node --check src/cs2webui/web/panel.js`
- [ ] Linux-only behavior was checked or recorded in `docs/LINUX_INTEGRATION.md`

## Safety

- [ ] Secrets remain masked.
- [ ] Podman remains the only supported container runtime.
- [ ] Optional modules still degrade independently.
- [ ] Destructive filesystem behavior has explicit confirmation and managed
      path checks.
- [ ] `docs/PROJECT_MEMORY.md` was updated when a decision or verification
      boundary changed.
