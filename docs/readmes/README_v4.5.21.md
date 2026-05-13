# v4.5.21 — HVAC Coordinator Device-Page Ordering (Experiment)

**Date:** 2026-05-12 CDT
**Type:** Tier 1 cosmetic experiment with easy revert
**Predecessor:** v4.5.20 (anomaly refresh signals + DOMAIN NameError fix)

## Summary

Prepends two-digit numeric prefixes to the `_attr_name` of every entity bound to the HVAC Coordinator device. The HA frontend sorts device-page entities by `stateName` (friendly_name), so this controls scan order within each cluster (Controls / Sensors / Configuration / Diagnostic).

**Approved scan order from earlier in the session** is now implemented. This is an experiment — if the visual cruft of `"10 · "` prefixes is unwelcome, `git revert` undoes the cycle with zero entity_id or DB side effects (only `_attr_name` strings changed).

After this validates on HC, the sweep can extend to Coordinator-Manager → House → Zone → other Coordinators → Room (per the approved sweep order, Room last because of its 2300+ entity blast radius).

## Prefix scheme

`"NN · Name"` — two-digit zero-padded number + space + middle-dot (U+00B7) + space + original name.

Gap of 10 between adjacent entries; per-zone sub-gap of 2 so additional zones slot in without renumbering.

## Cluster orderings (as built)

### Controls cluster

`CoordinatorEnabledSwitch` (friendly_name `"Enabled"`) is intentionally untouched — it's a shared class across all coordinators; conditionally prefixing only the HVAC-bound instance would require an `__init__` branch this cycle deliberately de-scoped. `"E"` sorts before `"F"` (force) and `"C"` (cancel) in locale-aware compare, so Enabled naturally appears above the action buttons.

Per-zone Force/Cancel buttons (prefix computed as `10 + zone_index*10 + offset`):
- `20 · Force AC Nudge (Back Hallway)`
- `22 · Cancel AC Nudge (Back Hallway)`
- `30 · Force AC Nudge (Entertainment + Master Suite)`
- `32 · Cancel AC Nudge (Entertainment + Master Suite)`
- `40 · Force AC Nudge (Upstairs)`
- `42 · Cancel AC Nudge (Upstairs)`

### Sensors cluster (no entity_category)

- `10 · Mode`
- `30 · HVAC Comfort Risk`
- `40 · HVAC Pre-Cool Likelihood`
- `50 · AC Nudges Today`
- `60 · AC Hard Resets Today`
- `70 · AC kWh Avoided Today`
- `80 · AC kWh Avoided (Total)`

### CONFIG cluster

- `10 · HVAC Observation Mode`
- `15 · AC Ramp-Down (Energy-Aware)`
- `20 · Override Arrester`
- `25 · AC Reset`
- `30 · Per-Zone HVAC Control`
- `35 · Pre-Arrival Conditioning`
- `40 · Fan Control`
- `45 · Solar Cover Management`
- `48 · Zone Entry Dwell` ← moved here per user direction
- `50 · Vacancy Auto-Off`
- `60-66 · 7 v4.5.10 tunables` (Cover Close Threshold → Fan Off Hysteresis)
- `70-75 · 6 v4.5.11 AC tunables` (AC Nudge Size → AC Hard Reset Min Interval)
- `90 · AC kWh Rate Threshold (per zone)`
- `95 · Clear AC Ramp Lockout (per zone)`

### DIAGNOSTIC cluster

- `10 · HVAC Anomaly`
- `15 · HVAC Compliance`
- `20 · HVAC Override Frequency`
- `25 · Override Arrester State`
- `30 · HVAC Arrester Status`
- `35 · HVAC Zone Intelligence`
- `40 · HVAC Pre-Arrival Status`
- `45 · AC Nudge False-Positive Rate`
- `50 · Zone {N} Status` (per zone)
- `55 · HVAC Zone Preset {…}` (per zone)
- `60 · AC Ramp State ({zone})`
- `62 · AC Ramp Last Action ({zone})`
- `64 · AC kWh Rate ({zone})`
- `90 · AC Ramp Diagnostic Dump`

## Files changed

- `sensor.py` — 17 `_attr_name` renames across HC sensor classes
- `switch.py` — 9 HVAC switches (CoordinatorEnabledSwitch untouched)
- `number.py` — 15 renames (ZoneEntryDwell + 7 v4.5.10 + 6 v4.5.11 factories + per-zone kWh threshold)
- `button.py` — `_AC_RAMP_BUTTON_SPECS` extended with `cluster` + `action_offset` / `fixed_prefix`; `_make_ac_ramp_button` now takes `zone_index` and computes prefix; `async_setup_entry` uses `enumerate(..., start=1)`; AC Ramp Diagnostic Dump button gets `90 · ` prefix

Plus updates to pre-existing test files to track new prefixed names (v4510 / v4511 / v4512 test files).

## What's NOT changed

- **No entity_id / unique_id / device_info changes.** HA's entity registry preserves the entity_ids; only friendly_name strings shift.
- **No DB schema, no config keys, no behavioral changes.**
- **CoordinatorEnabledSwitch** stays unprefixed (shared across coords). "E" still sorts to top of Controls naturally.
- **Other coordinator devices (Safety, Security, Presence, NM, MF, EC, CM, Room, Zone, House)** — entirely untouched. Sweep to those is a separate cycle pending approval after HC validates.

## Side effects to watch

- **Voice assistants (Assist / Alexa)** will speak the friendly_name. `"10 · Override Arrester"` reads as "ten middle-dot override arrester". HA does not strip prefixes for voice. If voice is heavy in your daily use of HVAC entities, this is the place to roll back. Otherwise tolerable.
- **HA logbook** displays friendly_name; the prefix will appear in log lines for any state change to these entities.
- **Lovelace cards** that read `name:` from friendly_name will show the prefix unless the card overrides `name`. If you have URA dashboards displaying these entities, they'll need a once-over.

## Tier 1 Review

Cosmetic-only change, easy revert (no code logic touched). Single staff-engineer review focused on:
- Correct identification of HC-bound entities (no Safety/Security/etc. accidentally touched)
- Cluster integrity (no collisions within a cluster's prefix space)
- Test coverage assertions match the actual prefix scheme

Verdict: APPROVED. 0 CRITICAL/HIGH/MEDIUM/LOW.

## Test count

- v4.5.20: 476 tests
- **v4.5.21: 538** (+62 from `test_v4521_hc_device_ordering.py`; 1 skipped due to button.py importing HA deps not in test env — covered by AST-walk + source-grep instead)

Test classes:
- 20 sensor positive cases (per HC sensor class)
- 9 switch positive cases
- 1 number direct class + 13 factory call-sites + 1 per-zone kWh-threshold
- 1 button direct class + 1 functional unit test of the `_ac_ramp_prefix` helper (skipped if button.py not importable)
- 13 negative cases (Safety/Security classes' `_attr_name` confirmed unchanged)
- 4 cluster-integrity uniqueness checks (controls / sensors / config / diagnostic)

Plus 4 pre-existing test files updated for new prefixed names (v4.5.10, v4.5.11 ramp switch, v4.5.12 dump button).

## Live validation plan (post-restart)

1. **Open Settings → Devices & Services → URA → "URA: HVAC Coordinator" device page.**
2. **Verify each cluster's scan order matches the lists above.** Visual diff against the pre-deploy screenshot (recommended: take one before this cycle for comparison).
3. **Two outcomes:**
   - **Order matches + cruft tolerable** → proceed with sweep to other coordinators (Coordinator-Manager → House → Zone → other coord devices → Room last)
   - **Order broken OR cruft unacceptable** → `git revert <commit>` ships v4.5.21.1, no side effects

## Sweep order (after HC validates)

1. Coordinator-Manager device (singleton, small entity count, proves pattern on another coord)
2. House device (~12 entities, single instance, high user visibility)
3. Zone device (per-zone, modest scale)
4. Other Coordinators batched (NM, EC, Safety, Security, Music Following)
5. Room device LAST (74+ × 31 rooms ≈ 2300+ entities; highest dashboard-card consumer risk)

## Deploy notes

- 4 files touched + 4 pre-existing test files updated + 1 new test file
- HACS download required
- HA restart required
- Easy revert path: `git revert <commit>` followed by deploy.sh — no state cleanup needed

## Documents

- BACKLOG entry "Device-page ordering — HC experiment plan" → closed by this cycle
- Future cycles after HC validation: per-device sweep plans

## Next

- **v4.6.x — `likely_next_room` accuracy pipeline** — the OTHER prediction-quality work
- **v4.6.0 — Routine Awareness Phase 1** — existing roadmap
- **Winter morning peak strategy** (from late-evening discussion) — design cycle pending option choice (A/B/C/D)
