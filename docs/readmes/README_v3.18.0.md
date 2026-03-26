# v3.18.0 — Hardening: Fan Control, Config Flow, Zone Sweep, Thread Safety

**Date:** 2026-03-25
**Tests:** 1201 passed (35 new: 17 fan control, 18 HVAC/zone/scoring)
**Sub-cycles:** v3.18.0 through v3.18.4, shipped as a single release

---

## Summary

5 sub-cycles addressing persistent production issues: fan turn-off bug, config flow save errors, fan sleep unawareness, zone sweep invisibility, thread safety audit, and comfort scoring. The Comfort Coordinator (C7) was evaluated and absorbed into the HVAC coordinator — ~80% of its scope already existed.

## Changes

### v3.18.0 — Config Flow Save Fix + Fan Turn-Off Bug

**Config flow race condition:**
- Deferred Zone Manager auto-populate prevents concurrent entry reloads that caused save failures
- Room entries skip reload entirely (picked up by `_refresh_config` every 30s)
- Zone Manager unload race guard added

**Fan turn-off fix:**
- Added 300s fan vacancy hold grace period in `automation.py` — fans stay on briefly after room goes vacant
- Fixed `int()` truncation on occupancy timeout in `coordinator.py` (was silently flooring fractional values)
- HVAC fan `min_runtime` now applies regardless of occupancy state

### v3.18.1 — Fan Sleep Awareness + Deconfliction

**Sleep policy:**
- New `CONF_FAN_SLEEP_POLICY` with three modes: `off`, `reduce` (default), `normal`
- In `reduce` mode, fans cap at 33% speed during sleep hours
- In `off` mode, fans turn off entirely during sleep

**HVAC fan sleep integration:**
- `house_state` passed to `FanController`; speed capped at 33% during sleep for all triggers including energy `fan_assist`

**Fan deconfliction:**
- Room-level fan control defers to HVAC coordinator when HVAC is actively managing the room's fans
- Prevents automation.py and HVAC from fighting over the same fan entity

### v3.18.2 — Zone Sweep Visibility + Persistence + AC Reset

**Zone sweep switch:**
- New `switch.ura_hvac_zone_sweep` (RestoreEntity, `mdi:broom`)
- `sweeps_today` attribute for observability
- Config flow: zone vacancy sweep toggle added to `coordinator_hvac` options step

**Zone state persistence:**
- `ZoneState` saved to `hass.helpers.storage.Store` every 25 minutes and on shutdown
- Restored on startup with 4-hour staleness guard (stale state is discarded)

**AC reset telemetry:**
- Pre/post state logging for AC reset operations
- 30s verification delay with 2 retries on failure
- CRITICAL NM alert on persistent AC reset failure
- Tracked tasks cancelled on teardown

### v3.18.3 — Thread-Safety Audit

- 58 instances of `async_write_ha_state()` replaced with `async_schedule_update_ha_state()` in signal handlers
  - `sensor.py`: 40 replacements
  - `binary_sensor.py`: 5 replacements
  - `aggregation.py`: 13 replacements
- Ensures HA event loop safety per HA 2026 / Python 3.14 enforcement

### v3.18.4 — Comfort Scoring + Tech Debt

**Comfort scoring sensor:**
- 0-100 per-room score: temperature (40%) + humidity (30%) + occupancy (30%)
- Full attribute breakdown showing per-component scores

**Efficiency scoring sensor:**
- HVAC zone mode: duty cycle + override penalty
- Temperature proximity fallback when HVAC zone data unavailable

**Comfort Coordinator disposition:**
- Marked as superseded — absorbed into HVAC coordinator
- Remaining items (circadian lighting, per-person preferences) deferred as thin features

## Review Findings

2-review adversarial protocol found 16 issues:

| Severity | Found | Fixed | Deferred |
|----------|-------|-------|----------|
| CRITICAL | 4 | 4 | 0 |
| HIGH | 5 | 4 | 1 |
| MEDIUM | 4 | 4 | 0 |
| LOW | 3 | 3 | 0 |
| **Total** | **16** | **15** | **1** |

Full details: `docs/reviews/code-review/v3.18.x_hardening.md`

New bug classes added to `docs/QUALITY_CONTEXT.md`:
- **Bug Class #19:** Untracked Background Tasks
- **Bug Class #20:** Concurrent Config Entry Reload Race
- **Bug Class #21:** Timezone Naive/Aware Datetime Mix

## Files Changed

14 integration source files, 2 new test files, 3 doc files.

| File | Changes |
|------|---------|
| `automation.py` | 300s fan vacancy hold grace period |
| `coordinator.py` | Occupancy timeout int() truncation fix, fan min_runtime enforcement |
| `config_flow.py` | Deferred ZM auto-populate, room entry reload skip, zone sweep toggle, unload race guard |
| `domain_coordinators/hvac.py` | Fan sleep policy, fan deconfliction, zone sweep switch wiring |
| `domain_coordinators/hvac_const.py` | CONF_FAN_SLEEP_POLICY, CONF_FAN_VACANCY_HOLD, zone sweep constants |
| `domain_coordinators/hvac_zones.py` | ZoneState persistence (Store save/restore), staleness guard |
| `domain_coordinators/hvac_predict.py` | AC reset telemetry (logging, verification, retries, NM alert) |
| `sensor.py` | Comfort scoring sensor, efficiency scoring sensor, 40x thread-safety fix |
| `binary_sensor.py` | 5x thread-safety fix |
| `aggregation.py` | 13x thread-safety fix |
| `switch.py` | HVACZoneSweepSwitch (RestoreEntity) |
| `const.py` | New constants, version 3.18.0 |
| `manifest.json` | Version 3.18.0 |
| `strings.json` | Fan sleep policy labels, zone sweep toggle |
| `quality/tests/test_fan_control.py` | 17 new tests (vacancy hold, sleep policy, deconfliction) |
| `quality/tests/test_hvac_scoring.py` | 18 new tests (comfort score, efficiency score, zone sweep, AC reset) |

## Deferred Items

| Item | Why Deferred | Future Tracking |
|------|-------------|-----------------|
| Zone sweep switch re-apply after HVAC setup | Needs HVAC-ready dispatcher signal; low risk since manual toggle works | Review doc H2 |
| CONF_FAN_VACANCY_HOLD config flow UI | Works with 300s default; niche setting | Next config flow UX pass |
| Options flow sleep_protection data_description | Cosmetic — labels present, help text missing | Next strings.json pass |
| Comfort score occupancy weight adjustment | Design decision (score range 15-100 vs 0-100) | Design discussion |
| FAN_SLEEP_NORMAL constant cleanup | Defined but unused; implicit fallback for "normal" policy | Next cleanup |
| Circadian lighting | Deferred from absorbed Comfort Coordinator; orthogonal to thermal comfort | Future HVAC enhancement |
| Per-person temperature preferences | Low priority; single household setpoint works for 95% of homes | v4.0.0 if needed |

## Decision Record

**Comfort Coordinator (C7) absorbed into HVAC:** ~80% overlap with existing HVAC features (thermal comfort, zone management, preset control). Remaining items — circadian lighting and per-person temperature preferences — are thin features that fit as sub-modules rather than a standalone coordinator. See `docs/Coordinator/COMFORT_COORDINATOR.md` (marked superseded).
