# v4.6.2.1 — Humidity Fan Hardening

**Date:** 2026-05-14 CDT
**Type:** Tier 1 hotfix during v4.6.2 soak
**Predecessor:** v4.6.2 (Routine Awareness — Day 1 of 7 soak)
**Severity:** Reliability gap — no max-runtime cap on humidity fans; Path A had no hysteresis; Path B silently ignored user's threshold config

## Problem

Live audit during v4.6.2 soak surfaced four issues in the humidity-fan control path:

1. **No max runtime cap.** A stuck humidity sensor or genuinely humid afternoon (cooking, laundry) ran the fan indefinitely. No safety cutoff in either code path.
2. **`CONF_HUMIDITY_FAN_TIMEOUT` was misnamed and misbehaved.** `_humidity_fan_triggered_time` only reset on turn-off — making `elapsed >= timeout` a **min-runtime gate**, not the "off-delay after humidity drops" the name implied. In steady state it was a no-op.
3. **No hysteresis in `automation.py` (Path A).** Single-threshold compare → fan chattered near 60% RH if humidity oscillated. Path B (HVAC-managed) had 60/50 hardcoded hysteresis but **ignored** `CONF_HUMIDITY_FAN_THRESHOLD` — user's setting silently had no effect when HVAC coordination was on.
4. **Three independent encodings of "60".** `const.py DEFAULT_HUMIDITY_THRESHOLD=60`, `hvac_const.py DEFAULT_HUMIDITY_FAN_ON=60`, literal `60` in `automation.py:1636` fallback. Silent drift risk.

## Fix

### D1 — Max runtime cap

New config `CONF_HUMIDITY_FAN_MAX_RUNTIME` (default `DEFAULT_HUMIDITY_FAN_MAX_RUNTIME = 3600`, 60 min; range 10–240 min). Applied in **both** Path A (room-level) and Path B (HVAC-managed). Tracks `_humidity_on_since` per fan; force-off when exceeded.

### D2 — Re-trigger suppression

After cap-fire, the fan does NOT re-activate even if humidity is still above ON threshold. Suppression clears only when humidity drops below the OFF threshold (`threshold − hysteresis`). Prevents the cap from being defeated by a stuck sensor.

### D3 — Hysteresis in Path A

Replaced single-threshold compare. ON if `humidity >= threshold`; stay-on if `humidity > (threshold − DEFAULT_HUMIDITY_FAN_HYSTERESIS)`; OFF otherwise. Eliminates chatter near 60% RH; matches Path B behavior.

### D4 — Path B respects user config

`hvac_fans._evaluate_humidity_fan` now reads `room_fan.humidity_fan_threshold` (from merged room config in `_register_room_fans`) instead of hardcoded `DEFAULT_HUMIDITY_FAN_ON`. OFF threshold tracks user's value (`threshold − 10`). HVAC-managed rooms finally honor `CONF_HUMIDITY_FAN_THRESHOLD`.

### D5 — Documentation-only

`CONF_HUMIDITY_FAN_TIMEOUT` helper text clarified to "Minimum continuous runtime before the fan is allowed to turn off after humidity drops below threshold." No code or default change; key preserved to avoid migration churn.

### D6 — Consolidate defaults

- Removed `DEFAULT_HUMIDITY_FAN_ON` and `DEFAULT_HUMIDITY_FAN_OFF` from `hvac_const.py`.
- Added `DEFAULT_HUMIDITY_FAN_HYSTERESIS = 10` to `const.py`.
- Replaced literal `60`/`600` fallbacks in `automation.py` with the canonical constants. Single source of truth.

## Files changed

- `const.py` — added `CONF_HUMIDITY_FAN_MAX_RUNTIME`, `DEFAULT_HUMIDITY_FAN_MAX_RUNTIME = 3600`, `DEFAULT_HUMIDITY_FAN_HYSTERESIS = 10`
- `domain_coordinators/hvac_const.py` — removed `DEFAULT_HUMIDITY_FAN_ON`/`OFF`
- `automation.py` — added `_humidity_on_since`, `_humidity_cap_suppressed`; rewrote `handle_humidity_based_fan_control` with max-runtime gate, hysteresis, suppression
- `domain_coordinators/hvac_fans.py` — added `humidity_fan_threshold`, `humidity_fan_max_runtime`, `humidity_on_since`, `humidity_cap_suppressed` to `RoomFanState`; plumbed config; rewrote `_evaluate_humidity_fan` to use user threshold + hysteresis + suppression
- `config_flow.py` — new field in climate step + options flow
- `strings.json` + `translations/en.json` — labels + clarified helper text
- `quality/tests/test_v4621_humidity_fan_hardening.py` — new file, 40 tests covering D1–D6

## Test count

- v4.6.2 baseline: 2920 passing on develop
- **v4.6.2.1: 2960 passing** (+40 new tests)

## What's NOT done in this hotfix (deferred to v4.6.2.3)

From the Tier 1 review (`docs/reviews/code-review/v4.6.2.1_humidity_fan_hardening.md`):

- **MEDIUM #1, #2 — Reload-mid-cycle state-anchor loss.** On options-flow reload while a fan is running, `_humidity_on_since` resets to `None`; if humidity is in the hysteresis band, the anchor never re-seeds and the cap silently disables until the fan fully cycles off→on. 5-line patch per path; bundled into v4.6.2.3.
- **LOW #3, #4, #5** — Cap/suppression edge cases (sleep clears suppression, HVAC-managing transition leaves stale state, cap-fire-clears-triggered-time undocumented).
- **LOW #8, #9 — Test honesty.** Path A tests are source-grep, not behavioral. Bundle behavioral driver tests into v4.6.2.3.

See `docs/BACKLOG.md` → "v4.6.2.3 — Review carry-overs from v4.6.2.1 + v4.6.2.2".

## Live validation plan

1. Confirm "Humidity Fan Max Runtime" field shows in any room's Climate options form with default 60 min.
2. Watch a bathroom for one shower cycle: fan should turn on at threshold, stay on through shower, turn off ~10 min after humidity drops below `threshold − 10`. No chatter near 60%.
3. Synthetic test (optional): set a test room's max_runtime to 600s, force humidity high; confirm fan turns off at the cap and INFO log fires.
4. With HVAC coordination ON: change `CONF_HUMIDITY_FAN_THRESHOLD` to 70%, reload entry, confirm fan activation point shifts (does NOT still activate at 60%).
5. No regression in the four family bedrooms — none have `humidity_fans` configured, so this is a no-op there (confirms no crash).
