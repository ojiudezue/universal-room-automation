# AUDIT: step 8 D0 probe (identity actions), 2026-11-15

Plan: `PLANNING_identity_actions_v6.md` rev 3.4 §4 / §8 D0. Probe: `scripts/probes/identity_actions_d0.py`
(read-only: recorder and URA DB opened `mode=ro`, `.storage` read, nothing written), run
`ssh ha "python3 -" < scripts/probes/identity_actions_d0.py` on 2026-11-15 against live HA. Window 14 days (the
recorder keeps about 7, so recorder-based rows cover about 7 days; URA DB rows cover 14). Rev 3.4 additions to the
probe in the same commit: `a_gate` (§5.4 gate 5 on residency rows), `a2_near` (§12 Q4 near rules), `b2` (§5.6 wait).
Go/no-go: none (operator ruling); numbers that make a gate look wrong are listed for the operator at the end.

How "own room" and "owner" are derived here: no profile is saved yet, so a person's own rooms are their top 3
`person_visits` rooms by dwell (the D1 suggestion rule). That is a proxy, not the profile.

## Headline numbers

| Item | Value |
|---|---|
| Tracked residents | ezinne, oji_udezue, jaya, ziri |
| Rooms with a primary player | Garage B, Guest Bedroom 1, Guest Bedroom 2, Kitchen, Laundry, Living Room, Master Bathroom, Master Bedroom, Study A, Study B (Jaya Bedroom and Ziri Bedroom have none) |
| Arrival master stored | UNSET (consumer default ON applies) |
| F5 per day (HVAC `pre_arrival` rows, a lower bound) | geofence 10.8, ble 4.4; camera_egress 0 (step 7 not shipped) |
| Geofence edges per day | oji 3.57, ezinne 1.14, jaya 0.57, ziri 0.21 |
| F5 → first room with a player, within 900 s | n 54; p50 190 s, p95 720 s, max 757 s (fits `ARRIVAL_WINDOW_S` 900) |
| At that first entry | already playing 0 %, room occupied before 18.5 %, quiet 3.7 %, own room (proxy) 29.6 % |
| Classified confidence of that move | n 4, all 0.80 (expected 0.50 in the plan; few rows matched) |
| Day / evening split of entries (`resolve_slot`) | 36 day / 18 evening (per-part picks matter) |
| (d) Egress entries named at the crossing | 30 of 94 (31.9 %) |

## (a) gate 5, counted return (rev 3.4 rule, residency rows)

Residency rows (`memory_episodes` `person_arrival` / `person_departure`) only exist since the residency producer
shipped, so only F5s after the first row are judged.

| Source | Pass | Rejected |
|---|---|---|
| geofence (counted, non-stale, out-of-boot arrival within 120 s before) | 9 | 6 `skipped_not_counted_return` |
| ble (`left_at` ≥ 15 min before, no later arrival) | 0 | 6 `recent_departure`, 3 `no_departure_seen` |

- geofence: F5 minus the counted arrival = 0 s in all 9 (same call, as §5.4 states). `ARRIVAL_COUNTED_EDGE_LOOKBACK_S`
  120 is ample.
- ble: F5 minus the last departure p50 5,976 s, min 1,839 s: every BLE F5 with a departure seen had a LATER arrival
  edge first (GPS led), so it read `recent_departure`. On these days BLE never opens an intent; the geofence F5 does.
  That is the plan's accepted shape, but it means `ble` contributes nothing today.
- The older (a1) raw-state counted-return estimate reads 0 of 151 geofence and 0 of 62 BLE. That function is the
  rev 3.2 draft and disagrees with the residency rows (9 of 15); treat it as a probe defect, not a finding.

## (a2) onset vs BLE entry, and the §12 Q4 near rules

Own motion before the BLE entry (pairs within 900 s), seconds: Master Bedroom ezinne p50 292 / p95 823, oji p50 178 /
p95 769; Jaya Bedroom jaya p50 372 / p95 720; Master Bathroom oji p50 439 / p95 888. The 900 s pairing window lets
unrelated onsets pair, so the p95 tails are inflated; the p50s alone are already above the `ARRIVAL_OCCUPIED_LEAD_S`
default of 120 s.

**Per-bedroom near-check pass shares** (onsets that an owner walked into within 900 s; holder = that owner; placement
read at the onset):

| Bedroom (zone) | Owners (proxy) | Onsets | Placed this / other / away-unknown | (i) adjacency | (ii) adjacency + approach | (iii) same zone (default) | BLE after body, p50 |
|---|---|---|---|---|---|---|---|
| Master Bedroom (Master Suite) | ezinne, oji | 32 | 2 / 28 / 2 | 15.6 % | 59.4 % | 34.4 % | 47 s |
| Jaya Bedroom (Upstairs) | jaya, ziri | 21 | 16 / 5 / 0 | 76.2 % | 90.5 % | 100 % | −12 s |

- Master Bedroom holders at onset were mostly downstairs (Living Room 5, Study A 4, Receiving Room 3, Powder 3,
  Master Bathroom 3, Kitchen 2): the owner's BLE lags the body by about a minute, so the zone rule passes about a third.
- Ziri Bedroom and the guest bedrooms do not appear: no resident's top-3 visit rooms include them (Ziri's proxy owns
  Jaya Bedroom). Ziri's welcome scene is therefore unmeasured here.

## (b) departures and the §5.6 wait

Departures per day: oji 3.64, ezinne 1.21, jaya 0.64, ziri 0.29. Of the departures whose last room is known, that
room was almost always already vacant at the departure edge (departure → vacant p50 0 s for every resident; n 1-5);
0 departures stayed occupied past room timeout + 300 s. The wait rarely matters on this data; the samples are small.

## For the operator

1. **§12 Q4 (near rule).** Master Bedroom: adjacency 16 %, adjacency + approach hall 59 %, same zone 34 %. Jaya
   Bedroom: 76 / 91 / 100 %. The zone default gives the master bedroom a welcome scene on about 1 in 3 entries;
   mapping the approach hall would give about 3 in 5 but changes the fan recheck L2 veto, the fan-interference gate
   and NM panel targeting (§5.5).
2. **Lead knob.** Own motion leads BLE by a median of 3-7 minutes in the bedrooms. With `ARRIVAL_OCCUPIED_LEAD_S` 120 s
   the occupied gate would often block a person on their own motion (`skipped_occupied`). Sizing it to cover that
   (several hundred seconds) also lets an earlier occupant through for that long. This is a review-only rung-1 number;
   it needs a decision.
3. **No speakers in the children's bedrooms.** Jaya Bedroom and Ziri Bedroom have no primary player, so arrival music
   cannot start there; only the welcome scene can.
4. **BLE source.** 0 of 9 BLE F5s pass the departure-side bar on this data.
