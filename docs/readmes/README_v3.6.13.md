# v3.6.13 — Security Coordinator Hardening

**Date:** 2026-03-02
**Cycle:** C3 post-deploy fixes
**Priority:** Bug fixes from post-deploy code review

---

## Summary

Hardens the Security Coordinator (v3.6.12) based on post-deploy code review findings. Six fixes addressing signal ordering, dead code, missing service definitions, input debouncing, device availability, and data freshness.

## Fixes

| # | Severity | Fix | Description |
|---|----------|-----|-------------|
| 1 | Must-fix | Signal ordering in auto-follow+alarm path | `async_dispatcher_send` now fires before alarm panel sync return, ensuring sensors update on every armed state change |
| 2 | Must-fix | Wire up CameraRecordDispatcher | Replaced hardcoded `camera.record` calls with platform-aware `_build_camera_actions()` (Frigate/UniFi/Reolink/generic) |
| 3 | Must-fix | Add services.yaml definitions | Added `security_arm`, `security_disarm`, `authorize_guest`, `add_expected_arrival` service definitions for HA Developer Tools |
| 4 | Warning | Entry sensor debouncing | Per-entity 10s cooldown prevents duplicate processing from noisy door/window sensors |
| 5 | Warning | Lock check unavailable handling | Distinguishes unavailable/unknown devices from unlocked; separate notification for offline locks instead of silent skip |
| 6 | Warning | Census data freshness validation | Stale census data (>5 min) returns INVESTIGATE verdict instead of trusting outdated person data |

## Modified Files

| File | Changes |
|------|---------|
| `domain_coordinators/security.py` | Fixes 1-2, 4-6: debouncing, unavailable handling, census freshness, camera dispatcher wiring |
| `services.yaml` | Fix 3: 4 new service definitions with field schemas |
| `const.py` | Version bump to 3.6.13 |
| `manifest.json` | Version bump to 3.6.13 |

## Tests

All existing tests pass. No regressions.
