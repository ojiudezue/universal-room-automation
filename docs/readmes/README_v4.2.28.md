# v4.2.28 — Room energy baseline persistence + restart resilience

**Date:** 2026-05-05
**Type:** Hotfix (Tier 2 protocols — feature-cycle scope due to new DB schema)

## Summary

Fixes the per-room `energy_today` inflation found during the May 5 sensor reconciliation cycle. Symptom: `study_a_closet_energy_today = 5,306 kWh` while `power = 0 W`.

Root cause in `coordinator.py:1444-1490`: room `_energy_baselines_today` was an in-memory dict that didn't survive coordinator restart. On every URA restart, the dict reset to empty; first read of each energy sensor set baseline = current cumulative reading. Worse, when a sensor was *unavailable* at midnight (e.g., Wi-Fi blip), the baseline didn't reset on rollover — it kept the previous day's value. Over multiple flaky midnights, drifted to a multi-week-old reference, producing the 5,306 kWh symptom.

This release persists baselines to URA's database and handles the unavailable-at-midnight edge case correctly.

## Changes

### `custom_components/universal_room_automation/database.py`

New table:

```sql
CREATE TABLE IF NOT EXISTS room_energy_baselines (
    room_id TEXT NOT NULL,
    sensor_id TEXT NOT NULL,
    baseline_value REAL NOT NULL,
    baseline_set_at TEXT NOT NULL,    -- ISO8601 UTC
    needs_reset INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (room_id, sensor_id)
);
```

Three new DAO methods: `save_room_energy_baseline`, `load_room_energy_baselines` (uses `cursor.fetchall()` for aiosqlite < 0.19 compat), `cleanup_room_energy_baselines` (batched DELETE per Bug Class #25).

### `custom_components/universal_room_automation/coordinator.py`

Energy loop refactor (`_async_update_data`):

- **Lazy load** baselines from DB on first refresh (sets flag BEFORE await to prevent concurrent re-entry — race fix from Tier 1 review).
- **Stale-baseline detection on load**: if persisted baselines are pre-today-midnight (URA was offline across the rollover), backdate `_last_energy_reset = yesterday-midnight` so the next update fires a clean midnight_reset. Without this, a 6am restart would compute delta against yesterday's baseline = 24h+ accumulation incorrectly attributed to "today" — caught by Tier 2 review CRITICAL.
- **Unavailable-at-midnight handling**: when `midnight_reset = True` AND a sensor is unavailable, set `needs_reset` flag (persisted) instead of leaving the old baseline in place. Next available read clears the flag and sets baseline = current_value.
- **Sanity guard** at 500 kWh per-update delta (raised from 200 per Tier 1 review HIGH #3 to accommodate legit multi-day EV/solar outages). Logs WARNING, resets baseline, contributes 0 for that cycle.

State added: `_energy_baselines_needs_reset: set[str]`, `_energy_baselines_loaded: bool`.

### `custom_components/universal_room_automation/__init__.py`

`cleanup_room_energy_baselines` registered in both `_cleanup_ops` and `_cleanup_ops_d` lists. Bug Class #27 prevention.

## Reviews — Tier 2 (per CLAUDE.md)

**Review 1 (Core A)** — adversarial bug-class audit:

| Severity | Finding | Status |
|---|---|---|
| CRITICAL | UTC/local timezone string compare (#11) | Pre-emptively fixed (all writes UTC) |
| HIGH | Race on `_energy_baselines_loaded` flag | Fixed (set before await) |
| HIGH | aiosqlite cursor `async for` version risk | Fixed (`fetchall()`) |
| HIGH | Sanity threshold too low (200) | Fixed (500) |
| MEDIUM/LOW | DB log level, atomicity, lifecycle, doc | Accepted |

**Review 2 (Core B)** — race / restart / lifecycle:

| Severity | Finding | Status |
|---|---|---|
| **CRITICAL** | **6am-after-midnight restart bug** | **Fixed (stale-baseline detector)** |
| MEDIUM | DB save log level | Fixed (debug → warning, 3 sites) |
| MEDIUM/LOW | Race duplicate, lifecycle, threshold | Accepted |

Full review at `docs/reviews/code-review/v4.2.28_room_energy_baseline_persistence.md`.

## What we parked

| Item | Reason |
|---|---|
| EC `envoy_status: online` while data sensors unavailable | Filed for v4.2.29 — out of v4.2.28 scope |
| Defect 3 (user-config: SPAN cumulative as daily source) | Mitigated by sanity guard; UX fix is separate |
| Lazy-load lifecycle move to `async_config_entry_first_refresh` | Functional now; future-cycle refactor |
| Test for 6am-restart scenario | Filed for future cycle |

## Live validation (Review 3 — post-deploy)

After HA restart:

1. Within 1 minute: log shows `"Room X: loaded N persisted energy baseline(s) from DB"` per room.
2. Within 5 minutes: rooms with previously absurd values (`study_a_closet_energy_today` etc.) drop to sane values.
3. `EnergyCoverageDeltaSensor` (was −17,457 kWh) returns to plausible.
4. `EnergyCostPerOccupiedHourSensor` (was $81/h) drops to <$5/h.
5. Watch for `"implausible delta"` warnings — should be zero in normal operation.
6. Tomorrow morning: true midnight reset fires correctly; `STATE_ENERGY_TODAY` starts at 0.

## Tests

All 3 modified files compile clean in Python 3.9 and 3.14. AST verification clean. Pre-existing test environment failures (Python 3.10+ syntax) unchanged.

## Deploy notes

- One HA restart creates the new DB table on next DB operation.
- Existing rooms with no persisted baselines fall through to existing `first_seen` branch on first refresh (no behavior change for first run).
- The cascade fixes (`EnergyCoverageDelta`, `EnergyCostPerOccupiedHour`) become visible on next polling cycle, no separate config change needed.

## Next

- **v4.2.29** — EC envoy_status defect (availability check tracks integration loaded-state, not data freshness)
- **v4.5.0** — Routine Awareness (B6 + B7) and/or Energy Architecture Alignment (BACKLOG E)
