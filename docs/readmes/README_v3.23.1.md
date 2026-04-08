# v3.23.1 — Hotfix: Presence Coordinator DOMAIN Shadow

## Bug Fix

**Problem:** `UnboundLocalError: cannot access local variable 'DOMAIN'` in `presence.py:1374`, 45 occurrences per restart cycle. The activity logger wiring added in v3.23.0 included a local `from ..const import DOMAIN` import inside `_run_inference()` that shadowed the module-level import for the entire function scope. Python treats local imports as local variables for the whole function, so line 1374 (which runs before the import at line 1459) failed.

**Root cause:** Bug Class #22 (local import shadows module-level import) — same class as the person coordinator bug in v3.22.4.

**Fix:** Removed the redundant local import. `DOMAIN` is already imported at module level (line 39).

## Files Changed
- `domain_coordinators/presence.py` — removed 1 line
