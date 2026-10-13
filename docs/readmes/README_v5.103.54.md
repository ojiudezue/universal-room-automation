# URA v5.103.54 — Running-fan release ignores radar motion bits; house state "unknown" (not "away") at boot

Cards: D2-PIR-STAMP-FOLLOWS-FAN-IMMUNE-WITNESS-1, HOUSE-STATE-SENSOR-BOOT-AWAY-DISPLAY-1. Built and reviewed (A + B, fix-ups) overnight 2026-10-12; full-suite name-diff vs v5.103.53: 0 new (4 test-fake failures from the merge fixed before ship).

## 1. D2 PIR stamp follows the fan-immune witness (D2-PIR-STAMP-FOLLOWS-FAN-IMMUNE-WITNESS-1)
**Problem:** the running-fan release (D2) waits for real motion to go stale before releasing a radar-held room. Any entity in `motion_sensors` refreshed that clock — including a radar's motion bit (Meross MS600 in Guest Bedroom 1 / 2 and Media), which a running fan can trigger, so D2 never released in those rooms.
**Fix:** the PIR clock and the latch clear are stamped only by a fan-immune motion witness (`fan_veto.is_fan_immune_motion_witness`, capability + device-model filter, over the filtered motion list). The 4-hour stale-occupancy failsafe keeps the legacy any-motion-bit freshness, so sleeping-body protection is unchanged. `occupancy_source="motion"` unchanged.

## 2. House-state sensors read "unknown" before boot (HOUSE-STATE-SENSOR-BOOT-AWAY-DISPLAY-1)
**Problem:** at every HA restart the house-state sensors briefly showed "away" (fallback value while the coordinator manager wasn't up), which looked like a real Away transition on dashboards/history.
**Fix:** the sensors return None (unknown) while the manager is missing.

## Not built / deferred
None from either card.

## Validated 2026-10-12 (restart 09:03 CDT)
| Criterion | Result | Evidence |
|---|---|---|
| Installed + restarted | PASS | manifest v5.103.54; recorder `current_recorder_run` 14:03:43Z |
| Boot: 0 URA errors | PASS | HA system_log level ERROR, search universal_room_automation = 0 |
| House state never "away" across restart | PASS | `sensor.ura_presence_coordinator_presence_house_state` history 08:55–09:05: guest → home_day only, no away |
| D2 release in GB1/GB2/Media | PENDING (organic) | folds into the 2026-10-18 fan re-measure |

Deploy note: deploy.sh step 6 hit a GitHub "base branch was modified" race; master already held the merge commit (5ec1c88c1, code identical to develop), so the release was created by hand with deploy.sh's own command. PR #625 left open by the race.
