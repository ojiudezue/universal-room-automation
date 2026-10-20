# URA v5.103.82 — Loaded vs installed version (restart-pending repair issue)

> Draft. The version number can change; renumber it at deploy time.

Card: EC-LOADED-VS-INSTALLED-VERSION-1 (Tier 1).

## Problem
After a deploy installs new files (HACS / deploy.sh) but before HA restarts, the running URA is older than the installed one, and nothing showed it. On 2026-10-19 the device registry reported sw_version v5.103.72 (loaded) while manifest.json on disk said 5.103.74. Live checks in that window read old code without any warning.

## Change
- New `version_check.py`. Loaded = `const.VERSION`, installed = `manifest.json` `version` read in the executor. A leading `v` is stripped before comparing.
- Runs once at integration-entry setup and then every `VERSION_CHECK_INTERVAL_S` (const.py, 3600 s, rung 1). The timer is released when the entry unloads.
- When the versions differ, one Repairs issue `restart_pending_version_mismatch` is raised (WARNING, not fixable, placeholders loaded/installed). It is deleted when they match again. If the manifest is missing or unreadable, installed = None and nothing changes.
- `sensor.ura_coordinator_manager` gains the attributes `loaded_version`, `installed_version` and `restart_pending`.
- Deploys deliberately separate install from restart (no restart while the house sleeps), so this state is normal. The issue is informational only.

## Tests
`quality/tests/test_loaded_vs_installed_version.py`. Mutation drills went RED for the comparison, issue create, issue delete, the setup wire-in call, the timer arm, and the sensor attrs.

## Live acceptance (one-shot, discriminating)
- **Live:** right after this deploy is installed but not yet restarted, the running code is the OLD build, which lacks this check, so it cannot report on itself. Validate on the NEXT deploy: once it is installed and before the restart, Repairs shows "Restart pending to load URA Y" with loaded=X installed=Y, and `sensor.ura_coordinator_manager` shows `restart_pending: true`.
- **Live:** after the restart the issue is gone and `loaded_version == installed_version`, `restart_pending: false`.
- Discrimination: if the check were broken, the issue would be absent while installed != loaded (a false negative), or present after the restart (a false positive). Each of those observations differs from the correct-behaviour one.
