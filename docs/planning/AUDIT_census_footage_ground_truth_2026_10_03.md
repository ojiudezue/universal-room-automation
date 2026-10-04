# AUDIT: census ground truth from recorded footage, 2026-10-03 (CDT)

Read-only. Companion to `PLANNING_census_occupancy_estimator.md` §8a and `AUDIT_census_subsystem_2026_10_04.md`.
No images or guest identities are stored in the repo. Stills live only in the session scratchpad.

## Sources

| Source | 10-03 retained? | How read | Notes |
|---|---|---|---|
| Frigate 2 (`https://192.168.13.18:8971`) | **Yes.** All interior and egress cameras record with 5-day retention (`MadronePTUltra` is not recording). | `GET /api/<cam>/recordings/<unix_ts>/snapshot.jpg` and `GET /api/events?labels=person`, using the HA config-entry credentials | This is the source used. The overlay timestamps match the requested slot to within about 1 s. |
| UniFi Protect MCP | Recordings exist, but the MCP has no historical-still tool | `protect_get_snapshot` returns a **live** frame only, and `protect_export_clip` returns metadata only | Not usable for stills from past times. |

Method: one still per interior camera every 30 min from 12:00 to 23:55 (25 slots × 7 cameras = 175 stills), with people counted by eye. Egress was handled differently: Frigate person events on the exterior cameras in the 14:05–14:45 and 22:45–24:00 windows, plus stills at each event cluster.

Dedup rules applied:
- `foyer_fisheye` sees the family-room floor at its edge. Those people are counted only under `family_room`.
- `family_room` and `master_hallway` never showed the same person in the sampled slots.
- `staircase` is the Garage Hallway camera.
- The `family_room` count **includes the covered patio seen through the glass**. That area is on the property but outdoors. From 15:00 to 21:00 most of the visible guests were on the patio.

## Per-slot visible counts and estimated house total

`est_house_total` is the operator-truth band applied to the recorder's `person.*` tracker residents (`rh`), as follows:
- plus 8 guests from 14:24 (time verified on footage);
- plus the 9th visitor from 12:00 until 23:01 (verified);
- minus 1 guest from 23:56 (verified);
- plus the long-stay guest: included in `hi` all day, and in `lo` only from 23:00.

| slot | family_room | playroom | staircase | stairs_top | master_hall | upstairs_hall | foyer | deduped visible | tracker rh | est house (lo-hi) |
|---|---|---|---|---|---|---|---|---|---|---|
| 12:00 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 3 | 4-5 |
| 12:30 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 2 | 3-4 |
| 13:00 | 3 | 0 | 1 | 0 | 0 | 0 | 0 | 4 | 3 | 4-5 |
| 13:30 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 3 | 4-5 |
| 14:00 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 4-5 |
| 14:30 | 0 | 8 | 0 | 1 | 0 | 0 | 0 | 9 | 1 | 10-11 |
| 15:00 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 1 | 10-11 |
| 15:30 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 1 | 10-11 |
| 16:00 | 1 | 7 | 1 | 0 | 0 | 0 | 0 | 9 | (HA down) | — |
| 16:30 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 2 | 11-12 |
| 17:00 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | (HA down) | — |
| 17:30 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 2 | 11-12 |
| 18:00 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 2 | 11-12 |
| 18:30 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 7 | 2 | 11-12 |
| 19:00 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 8 | 2 | 11-12 |
| 19:30 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 2 | 11-12 |
| 20:00 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 2 | 11-12 |
| 20:30 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 2 | 11-12 |
| 21:00 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 2 | 11-12 |
| 21:30 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 2 | 11-12 |
| 22:00 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 2 | 2 | 11-12 |
| 22:30 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 10-11 |
| 23:00 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 11 |
| 23:30 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 3 | 12 |
| 23:55 | 4 | 5 | 0 | 0 | 0 | 0 | 0 | 9 | 3 | 12 |

Observations:
- The peak deduped visible count is 9, at 14:30, 16:00 and 23:55, against a truth of about 10–12. Single-slot visibility ranged from 0% to about 80% of the house, with a median of about 30%. **No single still sees the whole party.**
- After 21:30 the playroom sofas show bedding, which suggests guests were sleeping in an area with no camera. That fits the low visible counts at 21:30–23:00.
- Tracker `rh` falls to 1–2 in the afternoon. This was not cross-checked against footage. If it under-reports residents, the truth band is low by the same amount.

## Door group sizes (egress footage)

| time (CDT) | door / cameras | direction | people in crossing | evidence |
|---|---|---|---|---|
| 14:22:44–14:24:50 | front: `front_side_ptz` (driveway), then `front_door_aerial` and `madrone_g6_entry` | entry | **8**, as one group arriving over about 2 min | 6–8 people on the driveway in one frame; 6 at once on `front_door_aerial` at 14:24:35 |
| 14:44:21 | front | crossing | 1 | single person at the door |
| 23:01:20 | front (`madrone_g6_entry`), then `front_side_ptz` to a car | exit | **1** (the 9th visitor) | |
| 23:24–23:30 | garage A (`garage_a`, `doorbell_lite`) | in/out, unclear | 1–2 | a person carrying bags along the garage side, plus 1 inside the garage. **Not reconciled** with operator truth. |
| 23:55:41 | front (`front_door_aerial`), then `front_side_ptz` | exit | **1** (the departing guest) | |

Calibration takeaways:
- An arrival group can be 8 people spread over about 120 s. Any per-crossing `person_count` max will undercount it: the door cameras peaked at 6 at once. `DOOR_GROUP_WINDOW_S` needs about 120 s, or the count should sum distinct tracked-object ids across the window.
- Departures were single people.

## Re-score: "simple" estimator vs footage truth

Replay method: `scripts/probes/census_d0/census_estimator_replay.py` (lines 1–318), with an appended slot scorer. It was run read-only via `ssh ha "python3 -"` and the recorder was opened `?mode=ro`. The estimators are defined as:
- `simple_inst` = `rh + max(0, house-max interior person_count − R_cam) + U_gr`;
- `simple_win20` = the same, with a 20-min window max on the camera term;
- `E_ref` = `run('house max', FLOOR_WINDOW_S=1200, useW=False)` ESTIMATE, which includes the anonymous entry/exit flow stock.

| slot | simple_inst | simple_win20 | E_ref | truth lo-hi |
|---|---|---|---|---|
| 12:00 | 5 | 6 | 8.0 | 4-5 |
| 12:30 | 4 | 5 | 6.0 | 3-4 |
| 13:00 | 5 | 5 | 11.0 | 4-5 |
| 13:30 | 4 | 6 | 12.0 | 4-5 |
| 14:00 | 4 | 7 | 14.0 | 4-5 |
| 14:30 | 8 | 9 | 14.0 | 10-11 |
| 15:00 | 1 | 5 | 13.0 | 10-11 |
| 15:30 | 3 | 5 | 13.0 | 10-11 |
| 16:30 | 4 | 5 | 10.0 | 11-12 |
| 17:30 | 2 | 4 | 10.0 | 11-12 |
| 18:00 | 5 | 5 | 10.0 | 11-12 |
| 18:30 | 7 | 7 | 10.0 | 11-12 |
| 19:00 | 4 | 6 | 10.0 | 11-12 |
| 19:30 | 3 | 4 | 9.0 | 11-12 |
| 20:00 | 2 | 4 | 9.0 | 11-12 |
| 20:30 | 2 | 3 | 9.0 | 11-12 |
| 21:00 | 3 | 5 | 9.0 | 11-12 |
| 21:30 | 2 | 6 | 10.0 | 11-12 |
| 22:00 | 2 | 3 | 9.0 | 11-12 |
| 22:30 | 2 | 2 | 8.0 | 10-11 |
| 23:00 | 2 | 3 | 8.0 | 11 |
| 23:30 | 4 | 5 | 14.0 | 12 |
| 23:55 | 6 | 11 | 14.0 | 12 |

Gate results over the 20 scored slots from 13:30 to 24:00 (excluding 16:00 and 17:00, when HA was down):

| gate | simple_win20 | E_ref |
|---|---|---|
| G4a: within ±2 of the truth band | **4/20 (20%)**: FAIL | **16/20 (80%)** |
| simple ≥ visible footage count (floor sanity) | fails at 15:30, 19:00, 20:30. The sensor counts are below what a person sees in the same still. | — |
| Pre-arrival 12:00–14:00 within ±1 | 4/5 | 1/5: overshoot of 6–14 before the guests arrived |

Verdict:
- **The camera-max floor without a flow term cannot hold a party.** Guests leave camera view, mostly to the patio edge, the playroom with no camera after 21:30, and the kitchen. The floor then collapses to `rh + 1–3`.
- The 93% G4a figure in §8a came from the flow-carrying run, not from the floor alone. The "re-scope D3 to floor + guest-room term + tracker residents" note in §8a should be revisited.
- The flow stock (E_ref) tracks the evening well. It overshoots before arrival and at 23:30–24:00, by up to +2 above the band. The likely cause is that the garage-A activity at 23:24–23:30 was counted as entries.
- The Frigate interior `person_count` sensors under-report against what is visible in the same frame: at 19:00 the sensor house-max was 2 while 8 people were visible.
