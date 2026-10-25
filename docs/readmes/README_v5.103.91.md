# v5.103.91: Census — face confirms, Bluetooth decides

Card: PERSON-BLE-WINS-OVER-STALE-GPS-1 (census follow-up of v5.103.90), triggered by FRIGATE-FACE-MISLABEL-OJI-1 (INSTANCE_2026_10_24_2142, stays with operator for retraining); plan `docs/planning/PLANNING_census_ble_over_face.md` rev 4. Tier 2, plan review + 3 framing-disjoint reviews. Deploy risk LOW-MEDIUM (house-level identified/unidentified counts).

## Problem
After v5.103.90 Oji (abroad) read Away by BLE, but the census still counted him home: Frigate face-matched Jaya as "Oji" and the face-latch guard (`camera_census.py` ~5891-5946) checked raw `person.oji_udezue`, still `home` from a frozen GPS fix. `sensor.universal_room_automation_identified_persons_in_house` = 3 with 2 people home.

## Change (one site)
- The face-latch guard reads raw state once (raw `not_home` drops as before). Otherwise, when `CENSUS_FACE_LATCH_FOLLOWS_BLE_LEADS` (const.py, review-only, default True) is on, it asks `person_state_for_trust`; a person BLE has overruled to away is not admitted by face. Errors keep the face.
- Same switch as v5.103.90: `switch.ura_presence_coordinator_ble_leads_home_away` off → decision identical to today.
- Counter `face_dropped_ble_overrule_count` on `sensor.universal_room_automation_persons_in_house` (excluded from the recorder).
- Unchanged: face confirms BLE-seen people; people without BLE; restart window; `_get_face_recognized_persons_fresh` (confidence), egress identity, room-level identity (BLE-only; `census.get_room_identified_persons` does not exist, documented).

## Accepted (operator 10-24)
- A body no longer explained by a wrong resident name becomes unidentified: D0 found 4 runs ≥300 s on 10-24 (13:40, 15:19, 15:43, 19:04; Family Room 3 bodies in one frame, 2 residents on BLE) — likely a visitor hidden behind "Oji". GUEST may now arm in such cases.
- Review B-1: a resident home without a phone, previously held home only by a mislabelled face, no longer blocks path α AWAY.

## Reviews
Plan review FIX-REQUIRED → rev 4. A SHIP, B SHIP (B-1 LOW above), C 14/17 RED → 2 tests added (fix-up 60c64d82a). Orchestrator mutation of the trust call → 7 RED. Full name-diff: CLEAN (18,462 passed, 0 new failures).

## Live acceptance criteria (prospective)
- No ERROR from camera_census after restart.
- While Oji reads Away by BLE (`away_ble_silent_only`), `face_recognized_persons` / `person_list` on the persons-in-house / identified sensors exclude `oji_udezue` even if `sensor.frigate_oji_last_camera_2` updates; `face_dropped_ble_overrule_count` > 0 when that happens.
- Ezinne and Jaya still face-confirmed when on camera.
