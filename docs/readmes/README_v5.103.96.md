# v5.103.96: a short Bluetooth blip no longer empties a room; BLE-leads floor scales with the fleet

Cards: BLE-LOCATION-QUALITY-1 (D1), PERSON-BLE-WINS-OVER-STALE-GPS-1 residual fleet fraction (D2). Plan: `docs/planning/PLANNING_ble_rearm_and_fleet_fraction.md` rev 2 (plan review fixed). Tier 2 presence, three reviews (A/B SHIP, C fixed). Deploy risk: LOW-MEDIUM (delays BLE-only exits by up to 90 s; floor identical for this house).

## Problem
- D1: on 10-28 and 10-29 at ~06:34 Jaya Bedroom was held by Bluetooth only (radars quiet). An ~10 s phone blip to the Upstairs Hallway emptied the room for one tick, and because BLE may extend but never create occupancy, it stayed vacant 27-30 min until a radar fired.
- D2: "Bluetooth leads home/away" needed >= 30 Bermuda proxies, a fixed number that doesn't fit other houses and that a shrinking Bermuda total can't express.

## Fix
- D1: a room held by Bluetooth only gets ONE grace of up to 90 s (`BLE_ABSENCE_GRACE_S`, 0 disables) when the person disappears for a tick. It never creates occupancy, cannot chain through a flip-flopping phone (once per BLE-only hold, re-armed only by a non-BLE confirmation or a new occupancy), respects the bathroom hold cap, and failsafe / Override Vacant / fan-recheck release still win. A blip shorter than the grace writes no exit/entry rows; a real BLE-only exit is written up to 90 s later.
- D2: floor = max(3, ceil(0.5 x the largest Bermuda total seen per day over the last 7 days)), stored in an HA Store, loaded before the first refresh. Falls back to 30 until a completed prior day is remembered (first boot, missing/corrupt store). This house: 62 → 31; no active count of exactly 30 in the recorded week (min non-zero 37), so behaviour is unchanged.
- PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md §3 and §4.6 updated.

## Tests
`test_ble_absence_grace.py` (30), `test_person_ble_fleet_fraction.py` (+boundary/date/corrupt cases), `test_person_coordinator_setup_wirein.py`; 52 mutation drills RED. Full-suite name-diff: one order-dependent failure in the new setup test, fixed test-only (scoped real-module fixture), verified in collection order.

## Known limits
- Repeated blips in one hold (10-29 shape) still exit after the one grace; a stricter re-arm is parked (plan §7).
- A BLE-only exit row's duration can read up to 90 s high.

## Live acceptance (prospective)
| Criterion | How to check |
|---|---|
| Blip survives | A BLE-only room with a sub-90 s person gap stays occupied (`occupancy_source=ble`), no exit row for the gap |
| Real exit still clears | A BLE-only room the person leaves goes vacant within ~120 s; one bleed-prone room checked |
| Floor | person coordinator floor 31 after one prior day remembered (30 before) |
| Load clean | No URA ERROR after restart |

Deployed 2026-11-01 without restart (operator); takes effect at the next restart.

## Validated 2026-11-02 (partial; overnight read-only pass, live since the 11-01 14:04 restart)
| Criterion | Result | Evidence |
|---|---|---|
| Floor | PASS | `.storage/universal_room_automation.ble_fleet_memory` ring = [["2026-11-01", 62], ["2026-11-02", 62]]: a completed prior day is remembered, so the floor is max(3, ceil(0.5 × 62)) = 31 (person_coordinator.py `_update_fleet_floor`). Derived from the Store and the code. The INFO "BLE leads: fleet floor 31" log line fell outside the log window and was not read |
| Load clean | PASS | `ha_get_logs source=system` (in-memory since the 14:04 restart), filtered to universal_room_automation: no ERROR. 3 WARNINGs only, none from this change: a census "all camera platforms unavailable" at 02:00 during a Frigate host blip, an Envoy consumption cross-check divergence, and rooms holding occupancy for 60 s with all sensors unavailable at 01:58-02:00 (the same blip) |
| Blip survives | FAIL (expected residual) | Checked 2026-11-04. Jaya Bedroom went vacant 11-02 06:30→06:56 and 11-03 06:31→06:52 (occupancy_events) while `sensor.iphone_jaya_area` flip-flopped Jaya Bedroom ↔ Upstairs Hallway every 10-90 s (11-02: 64 changes in 32 min, 71% in the bedroom) and Jaya Bathroom stayed empty. A flip-flopping phone uses up the single grace by design (plan §1, "10-29 06:34 is NOT rescued by rev 2"). This fires the plan §7 revival trigger (more than one BLE-only morning false vacancy a week); the K-tick re-arm is now planned on BLE-LOCATION-QUALITY-1 |
| Real exit still clears | as-expected | The two exits above were written at the end of a used grace, as specified; no stuck-occupied BLE hold was seen. A clean real BLE-only exit was not isolated in this read |
