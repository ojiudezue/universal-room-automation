# Review B: CENSUS-BLE-OVER-FACE-1 (cross-coordinator ripple + lifecycle/timing)

- Branch `fix/census-ble-over-face`, diff `df3bb8412...ec9adbfa2` (merge-base verified = df3bb8412, one commit).
- Plan: `docs/planning/PLANNING_census_ble_over_face.md` rev 4.
- Read completely first: `IDENTITY_FUSION_CAMERAS_MANUAL.md`, `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (including the §10 ledger), and `SENSOR_FLEET_CLASSES.md`. No ledger claim is re-asserted here.
- Reviewer: framing B. No code edited.

## Verdict: SHIP

No CRITICAL, HIGH or MEDIUM findings. I found no harmful leak beyond the costs the operator accepted. The one AWAY-direction effect is the plan's stated intent; it is recorded as a LOW so the operator knows it is there.

## Findings

| # | SEV | Where | Finding / clearance |
|---|---|---|---|
| B-1 | LOW (disclosure) | `camera_census.py:5900-5945`, path α `presence.py:1206-1231` | **α can now fire AWAY on a stale mislabelled latch that used to hold the house.** Repro (legal config, live switches): BLE Leads on, the fleet armed for 360 s or more, and Oji abroad with GPS frozen `home`, so Oji is in `_gps_home_overruled` with location `away`. Ezinne is away. Jaya (BLE-only) has a dead phone, so her `person.jaya` reads `not_home`. Frigate mislabelled Jaya as Oji at T. Jaya then moves to an uncameraed room, so camera_total = 0 and unidentified = 0. Before this change, Oji's latched face (≤1800 s, re-stamped by `last_camera` flaps) kept `face_recognized_count` = 1, which blocked α. After it, the count is 0 and α returns AWAY even though a zone is occupied (α does not check zones, ledger §10 #12). This is the plan's §3 "benefit" seen from the other side, and the same class as HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1. The occupant was protected only by a wrong name. Option A ("home without phone = treated away like the kids") covers it. No fix required. The orchestrator should make sure the operator knows the accepted cost has an AWAY face as well as the GUEST face. |
| B-2 | LOW (holds) | `person_coordinator.py:1222-1227`, `:628-655`, `:1811-1814` | **Tick ordering.** `_gps_home_overruled` is assigned before `self.data` is published, and `get_person_location` reads `self.data`. On overrule onset the old data says room or home, so the helper returns raw and the face is admitted (today's behaviour) for one person tick. On overrule end (BLE back), the set and data both still say away for ≤ 1 person tick (~30 s), so the face is dropped while BLE is home. That is harmless: the census BLE list is built from the same stale `location`, so Oji is unidentified by both paths for that tick either way. A ≤ 30 s unidentified run is far below the 300 s GUEST persistence. |
| B-3 | LOW (holds) | `person_coordinator.py:226-231`, `:463-531`, `:124-145` | **Restart and reload.** The overrule set starts as `frozenset()`, is not restored, and `_fleet_healthy_since` is per instance (None at construction), so after a restart or a person-coordinator reload the site matches develop for ≥ 360 s. If the coordinator is popped mid-unload, `person_state_for_trust` falls back to raw (fail-open). The flag is read as a module attribute at call time. No listeners, timers or tasks were added. |
| B-4 | LOW (holds) | `camera_census.py:1717-1719`, `:5966` | **Counter lifecycle.** The reset sits beside `_face_lookup_missing_count` inside `_async_update_census_locked` (under `_update_lock`), and the only producer call is from `_apply_enhanced_house_census` in that same tick, so there is no double count. The sensor's new `_unrecorded_attributes` (`sensor.py:3729`) overrides nothing: `_CensusBaseSensor` / `AggregationEntity` define none, so the attributes D0 relied on stay recorded. |
| B-5 | INFO (holds) | `camera_census.py:2077-2079`, `:3586+` (untouched) | **GUEST gate confidence.** `_get_face_recognized_persons_fresh` (raw, no veto) is not in the diff, so the corroboration bundle and the divergence downgrade are unchanged. Confidence stays medium/high, which is why the D0 runs are GUEST-eligible. Accepted (Q1). |

## Consumer ripple sweep (`git grep` at ec9adbfa2)

| Consumer | Effect | Verdict |
|---|---|---|
| `identified_count` / `identified_persons` → unidentified math → GUEST gate | Name leaves; a body still in frame becomes unidentified (clamp/area-cancel unchanged) | accepted GUEST cost (resident home without phone; visitor hidden behind a mislabel) |
| `face_recognized_count` → path α (`presence.py:5184`, `:7024`, `:1231`) | No longer held by an overruled adult's latch | intended; see B-1 |
| nobody-home (`census_count == 0 AND NOT any_zone_occupied`) | census_count can drop by one when the latched body is off-camera; still guarded by zone occupancy | no leak |
| ARRIVING | census-driven ARRIVING needs `has_people`; presence's own camera-face ARRIVING (`presence.py:5400-5475`) reads Frigate faces raw, outside the census | unchanged |
| `ZoneGuestCountSensor` (`aggregation.py:6365-6447`), DB census rows (`database.py:4222+`), `person_list` / `face_recognized_persons` attrs | display / log | expected |
| Egress (`is_face_leg_person_vetoed`, `transit_validator`, `_get_egress_face_ids_fresh`) | untouched (non-goal; entry-crossing mislabel fence documented in plan §9) | unchanged |
| Security / perimeter | DetectionLeg only; no census identity | unchanged |
| Music following / NM / `persons_home` | person_coordinator location | unchanged |
| Room identity (`coordinator.py:1300-1303`) | dead `getattr` hook, comment only | unchanged |

## Bug-class tally

| Class | Count |
|---|---|
| Cross-coordinator ripple (presence ↔ census ↔ α/GUEST) | 1 LOW (B-1, disclosed) |
| Tick-ordering / one-tick lag | 1 LOW (holds) |
| Restart / reload safety | 0 (holds) |
| Untracked background tasks / listener leaks | 0 |

Summary: found 0 CRIT / 0 HIGH / 0 MED / 2 LOW findings (B-1, B-2) / 3 clearances. No fix required.
