# URA v5.108.30 — Stuck-sensor truth S3a, S3b, S1

Cards: CHATTER-MODE-SELECT-NOT-WIRED-1 (S3a), STUCK-SENSOR-S3B-S1-1 (S3b, S1; child of MEDIAROOM-FAN-LEFT-ON-STUCK-SENSORS-1, which keeps S4-S6),
census-reset prerequisites (arc map §4a row 4). Plan: `docs/planning/PLANNING_stuck_sensor_truth.md` rev 2 (d43633b5),
§3 S3a / S3b / S1 only. S2 shipped as P3-D8 (v5.108.27). S4-S6 not in this release.
Branch `feature/stuck-sensor-s1-s3` (from develop c67b8a78).

## What changes

### S3a — the chatter mode select reaches the rooms (Tier 2)
`select.ura_chatter_mode` writes the INTEGRATION entry, but rooms read the CM entry only, so chatter had never acted
(every chatter NM read "WOULD quarantine (shadow)"). Now one resolver, `_nm_cycle_a.chatter_mode_option`: integration
option, else the CM option (pre-D7 migrate target), else `shadow`. Rooms and the select both read it (INV-S3a). The
cache is flushed by the select write, the integration update listener and the CM knob flush. `chatter_mode` joins the
integration reload-suppress allowlist, so flipping the select no longer reloads the parent entry.
**Live effect (operator: act):** the select already reads `act`, so at deploy chattering inputs (Garage A/B ratgdo, the
Master Bathroom InvisOutlet, the media MS600 bit) are excluded from room fusion while they chatter.

### S3b — MS600 motion bit by registry model (Tier 2)
The meross_lan record that owns `..._sensor_presence_motion` has `model` `ms600-un` (model_id None) and resolved
`unknown`. `family_for_model` now splits the first token on whitespace / hyphen / underscore and lists `ms600-un`, so the
bit is `generic_radar` by registry model; the name regex is no longer load-bearing. Golden over every live device pair:
only `ms600-un` changes. Effect: a bit-only tick is radar-sole (recheck window factor 1.5); Guest Bedroom 1 (Fan Mode
Room temperature) becomes eligible for the radar recheck route once unpaused (Q-B); GB2 / Media stay vetoed
`fan_control_off`.

### S1 — P22 off-pulse tolerance (Tier 2-DB)
A MOTION-class room input (ZG-204ZV / PIR family, not a still holder) no longer restarts its 4 h continuous-on run on an
off or dead stretch shorter than 10 s, and the run starts at the rising edge's `last_changed`. Still holders (radar, bed,
camera, BLE, MS600 bit), unknown families and a knob of 0 keep the old rule exactly. Knobs (rung 1):
`STUCK_P22_OFF_GAP_TOLERANCE_S` 10, `STUCK_P22_HOURS` 4.0 (replaces the literal). New pure
`sensor_capability.is_still_holder` / `is_p22_motion_class`.
A not-on stretch is ONE stretch whatever its mix of off / unavailable / unknown / missing, measured from the moment the
input stopped reading `on` (fix pass: reviews A-1 / B-2 and the replay's 14:20:04-14:20:17 unavailable 6.1 s + unknown
6.6 s case, which the first build read as 6.6 s). An `off` read again with a new `last_changed` still starts a new
stretch (plan `two_polls`); the residual, an off → unseen unavailable → off, is pinned by a test. The tolerance knob
must stay below the ZV still-person drop time (~30 s).

## Pre-deploy gate (S1): GO
Plan step 0 replay, `docs/planning/AUDIT_stuck_s1_step0_replay_2026_11_15.md`: no S1 run ≥ 4 h overlaps a BLE-confirmed
person in the room; S1's effect is the two guest-bedroom ZVs (patio right near miss at 4.00 h).

## Acceptance (prospective, live)
| # | Criterion | Signal |
|---|---|---|
| S3a-1 | Next chatter NM reads "quarantined", not "WOULD quarantine (shadow)" | `notification_log` / NM text |
| S3a-2 | The chattering input is listed under client `chatter` | room `automation_health.excluded_sensors` |
| S3a-3 | Flipping `select.ura_chatter_mode` does not reload the parent entry | HA log: "in-place apply, suppressing reload (changed_keys=['chatter_mode'])" |
| S3b-1 | Media radar-sole tick true when only the MS600 bit is on | `binary_sensor.media_room_occupied` radar-sole attribute |
| S1-1 | A motion-class input holding ≥ 4 h with sub-10 s blips stays in `automation_health.stuck_sensors` across the blips | room Automation Health attributes |
| S1-2 | One `continuous` stuck NM per (room, sensor, day), not two | `notification_log` |

## Validated 2026-11-16 (restart ~06:37 CST, installed v5.108.32)
All 50 URA config entries `loaded`; no URA ERROR/CRITICAL in the system log.

| # | Result | Evidence |
|---|---|---|
| S3a-1 | PASS (title), row missing: residual | `select.ura_chatter_mode` = `act`; watchdog `last_fired.chatter` 06:38:30; NM dedup cache holds `stuck_signal:Chattering sensor: Garage B — binary_sensor.ratgdov25i_dbfe2a_motion:chatter` (act-form title, `coordinator.py:3304-3308`). Pre-deploy rows (e.g. 27504) used the shadow form. No `notification_log` row: NM boot-settle (`notification_manager.py:1797-1806`, 60 s) collapsed it into the dutycycle NM sent 9 s earlier (rows 27548/27549), and the stuck-signal day latch was still set. Carded on STUCK-SENSOR-S3B-S1-1 (`residual_2026_11_16_boot_settle_drops_chatter`). |
| S3a-2 | Criterion unobservable as written | `excluded_sensors` is built only from the dutycycle set (`sensor.py:2613-2616`); the chatter client in `_exclusion_set` (`coordinator.py:3267-3270`) is not exposed by any entity. Watchdog `stuck_sensors` shows `{'Garage B': {...motion: 'chatter'}}` but that label is mode-independent. In-suite proof only. |
| S3a-3 | Pending event / in-suite | Needs an operator flip; the INFO line is not in the WARNING+ system log. |
| S3b-1 | Pending event | Precondition holds: Media, Guest 1, Guest 2 MS600 devices resolve by registry `model` `ms600-un` (`model_id` None). Needs a bit-only tick. |
| S1-1 | Pending event | No qualifying ≥ 4 h motion-class run at validation time. |
| S1-2 | Pending event | No `continuous` rows since restart. |

Boot transients dismissed: one `RuntimeError` (`async_write_ha_state` off-loop) at `switch.py:1637`, the v4.7.x EC sub-switch deferred restore, not this release; recovery/zone-seed/linker-ordering WARNINGs, all boot ordering.

## Tests
`quality/tests/test_stuck_sensor_s3a_chatter_mode.py` (13), `test_stuck_sensor_s3b_ms600_family.py` (10),
`test_stuck_sensor_s1_p22_tolerance.py` (53, incl. the fix-pass stretch tests and review C c9 / e2 / e3 / e7 / c10 /
e9 / e10 / e13 / e19 / d12 gaps); stubs of `_nm_cycle_a` updated in three chatter test files; integration
allowlist pin and two AST-slice namespaces updated for `chatter_mode`.

## Not done / deferred
- S2 (shipped as P3-D8 in v5.108.27; its same-run check G7 and edge filter are NOT in this release).
- S4, S5, S6 (secondary fan work, out of scope).
- Review A-2 (cache the per-input capability lookup): deferred. A boot registry miss returns `unknown` uncached on
  purpose; a cache would need the same miss rule plus an options-change flush, for a cheap lookup.
- Review C e12 (state stub without `last_changed`): optional, equivalent in production.
