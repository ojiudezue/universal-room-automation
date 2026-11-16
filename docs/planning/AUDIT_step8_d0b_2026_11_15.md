# AUDIT: step 8 D0b probe (arrival gates in practice), 2026-11-15

Read-only. Defined in `PLANNING_identity_actions_v6.md` rev 3.6.1 §4 (D0b). Run 2026-11-15 21:37 CDT against live HA with
`ssh ha "python3 -" < .claude/tmp/d0b_arrival_probe.py` (recorder and URA DB opened `mode=ro`; `.storage` read for selected
fields only). Read first: the D0b section, `AUDIT_step8_f5_source_semantics_2026_11_15.md`, `AUDIT_identity_actions_d0_2026_11_15.md`.
Not read end to end: the HVAC/PRESENCE state-of-play docs (this probe touches neither's logic; it only reads person edges, census and
visits). Times in tables below are UTC (the probe's native clock); the run itself is CDT.

## Method and definitions

- **Arrival universe:** `person.*` `not_home/zone -> home` edges in the recorder, window 2026-11-08 10:12 UTC to now (~7 days). 80
  arrivals: oji 51, ezinne 17, jaya 9, ziri 3. The recorder gives more than the 18 residency rows in `memory_episodes` (rows exist
  only from 2026-11-13 20:54 UTC); it is the same composed edge (audit §4).
- **Gate 3b:** last `person.*` home -> away edge before the arrival; away >= 900 s passes. "No departure visible": none in the window.
- **Guests detected:** URA DB `house_state_log` state `guest` in effect just before the edge, OR `census_snapshots` zone `house`
  (the trust view the comfort class reads, `census_view.py:24-49`; `unidentified_count` = `unidentified_or_guests`) with
  `unidentified_count >= 1`, using the latest snapshot at or before edge, +60 s, +180 s (snapshot cadence about 80 s; a snapshot
  older than 240 s counts as "no census").
- **Own rooms (PROXY, no ownership exists):** the room config entries carry NO person-to-room field (keys checked: nothing named
  owner / person / profile / resident on any room entry; `person_profiles` is not stored yet). So own rooms are derived, not read:
  the highest-dwell `room_type == bedroom` room plus the two highest-dwell `bathroom` rooms from `person_visits` since 2026-11-01,
  room type from the room entries (`room_name` -> `room_type`). Derived sets (dwell hours): ezinne Master Bedroom (111.9),
  Master Bathroom (4.3), Powder (2.4); oji Master Bedroom (51.2), Master Bathroom (22.1), Powder (1.6); jaya Jaya Bedroom (140.0),
  Powder (1.9), Guest Bedroom 2 Bathroom (0.3); ziri Jaya Bedroom (3.0), Ziri Bathroom (15.1), Powder (0.4). Ziri's own Ziri Bedroom
  does not top the list. Powder is in every set because it is each person's second bathroom by dwell: it loosens reach. The "any
  bedroom or bathroom" variant is reported beside it as a ceiling.
- **Room placement:** `person_visits` (entry/exit, local CST, converted), each open visit capped at the same person's next entry and
  next `person.*` departure (468 rows have `exit_time` NULL, stale). Reach = a visit to an own room with entry in [edge, edge+900 s].
- **Someone else there:** another tracked person's capped visit covering the edge in the person's own rooms, OR the room's last
  `occupancy_events` row before the edge is `entry` (rooms keyed by entry_id).

## 1. Gate 3b on counted arrivals

| Person | Arrivals | Away >= 900 s (pass) | Flap < 900 s | No departure visible |
|---|---|---|---|---|
| ezinne | 17 | 16 | 1 | 0 |
| oji_udezue | 51 | 33 | 18 | 0 |
| jaya | 9 | 9 | 0 | 0 |
| ziri | 3 | 3 | 0 | 0 |
| **All** | **80** | **61** | **19** | **0** |

No-departure is zero because every person's first recorded state in the window was `home`, so every arrival edge has a departure
before it. 19 of 19 flaps match the F5 audit's count. Of the 61 passes, 26 are 900-3600 s and 13 are 900-1800 s (Oji 21 / 12).

**Falsification of "a pass is a real return".** Gate 3b only tests the clock. For each passing arrival I asked: did the person
reach any room within 900 s, and was the person in the house census at +180 s?

| Person | Passes | No room visit within 900 s AND not in census at +180 s | Visit AND in census |
|---|---|---|---|
| ezinne | 16 | 0 | 16 |
| jaya | 9 | 0 | 9 |
| ziri | 3 | 0 | 3 |
| oji_udezue | 33 | **29** | 4 |

29 of Oji's 33 passing arrivals have no BLE room, no door visit and no body in the census 3 minutes later, over 3 separate
clusters (11-08 to 11-09 UTC, and 11-15 UTC). Their away durations run 903 s to 17,666 s (median about 1,800 s; 11 are over 3600 s), and
the 4 real Oji returns are 1814, 1815, 2521 and 428,382 s. No away threshold separates the two sets. These are `person.*` flips with
no body arriving (GPS-composed state; the F5 audit found all sub-900 s flaps GPS). I did not read the edge `source` for these 29, so "GPS" for them is inferred, not measured. The counter-observation
that would refute "phantom": a visit or census row for Oji within the window. There is none.

## 2. Guests detected at a resident's own arrival

Arrivals with house state `guest` before the edge: 3 (ziri 2 on 11-14, oji 1 on 11-14 22:39 UTC, the party night). The other 77
arrivals had a non-guest house state at the edge, so any "guests detected" there comes from the census.

All 80 arrivals (census unidentified >= 1 or guest state), by offset:

| Person | n | guest state before edge | census unid >= 1 at +0 | +60 | +180 | Any of the three, no guest pre-state |
|---|---|---|---|---|---|---|
| ezinne | 17 | 0 | 4 | 3 | 2 | 5 |
| oji_udezue | 51 | 1 | 2 (1 without guest pre) | 3 (2) | 2 (2) | 3 |
| jaya | 9 | 0 | 2 | 2 | 0 | 2 |
| ziri | 3 | 2 | 0 | 0 | 0 | 0 |
| **All** | 80 | 3 | 8 (7) | 8 (7) | 4 (4) | **10 of 77** |

Passing arrivals only (61; 3 have a guest pre-state, so 58 had no visitor state): census unidentified >= 1 at +0 for 6, +60 for 6,
+180 for 3; any of the three for 9 of 58 (15.5 %). Per person (passing, no guest pre-state): ezinne 4 of 16, jaya 2 of 9, oji 3
of 32 (counts include the 29 phantoms, whose census is empty), ziri 0 of 1.

Do the person's own body read as unidentified? Yes, on the arrivals I can see. The clearest rows (house state not guest, census
`total_persons` 1 and `identified_persons` empty at +0 and +60, the resident listed by +180):

- 11-11 22:29 jaya and 22:30 ezinne (same arrival, 1 unid, ids empty at +0 and +60; ids ezinne+jaya at +180)
- 11-12 22:43 ezinne and 22:44 jaya (same shape)
- 11-12 14:33 ezinne (1 unid at +0, resolved by +60)
- 11-12 17:29 ezinne: away 0 s (a flap), 1 unid at +0, +60 and +180

Two rows persist at +180 as a real extra body or an unidentified own body (cannot tell from here): 11-08 19:58 (ezinne and oji
arrived together; unid 1, total 3 at +180) and 11-09 17:31 (oji; unid 1, total 2 with ezinne at +0, +60, +180).

Real visitors home (operator ground truth on the party night): 11-14 22:39 UTC oji arrival: census unid 3 (total 6) at +0, 5 (total 8)
at +60, 0 (total 4, all four residents named) at +180. The guest gate would have blocked this arrival, and the guest state that
night (set 11-14 12:03 UTC and again 17:34 UTC, cleared 11-15 04:08 UTC) already flagged it before the edge. Ziri's two arrivals on
11-14 19:39 and 21:22 UTC likewise had a guest pre-state, and the census read 0 unidentified at all three offsets, so the guest block
there came from the house state alone.

Without a visitor, an unidentified own body trips the census on 7 of 77 arrivals at the edge and on 4 at +180.

## 3. Reaching the own bedroom or bathroom within 900 s (proxy rooms)

Passing arrivals only (61):

| Person | Passes | Reached own room in 900 s | Reach time p50 / p95 / max (s) | Reached ANY bedroom/bathroom |
|---|---|---|---|---|
| ezinne | 16 | 8 (50 %) | 263 / 432 / 432 | 14 (87.5 %) |
| jaya | 9 | 9 (100 %) | 22 / 66 / 66 | 9 |
| ziri | 3 | 3 (100 %) | 29 / 92 / 92 | 3 |
| oji_udezue | 33 | 4 (12 %) | 306 / 344 / 344 | 4 |
| **All** | 61 | 24 | p50 101, p95 426, max 452 | 30 |

Oji is not a measurement of the person: 29 of his 33 passes have no BLE room data at all (section 1), so his 12 % is a data gap plus
phantoms, and only 4 arrivals are real. For the real 4 own-room reach is 4 of 4 (219 to 344 s). Ezinne's 8 non-reaches are real: she
walks in through the garage and goes to the kitchen, living room or powder before (or without) the master suite (first visits listed
in the probe output). A caution on the first 60 s: Ezinne's and Oji's first visit is often "Jaya Bedroom" at 14-44 s (a BLE
re-placement artefact right after the edge, e.g. 11-08 19:58 UTC), so reach credit under about 60 s is weak for adults. It does not
affect their own-room count (Jaya Bedroom is not in their set), but it does mean Jaya's and Ziri's 22 and 29 s reach times could be
partly the same artefact.

## 4. Someone else already in the person's own room at arrival

Passing arrivals only:

| Person | Passes | Another tracked person in own room at edge | Own room occupied (occupancy rows) | Either |
|---|---|---|---|---|
| ezinne | 16 | 1 | 2 | 2 |
| jaya | 9 | 0 | 0 | 0 |
| ziri | 3 | 1 | 1 | 1 |
| oji_udezue | 33 | 8 | 7 | 9 |
| **All** | 61 | 10 | 10 | 12 (19.7 %) |

Of the 24 that reached their own room, another tracked person was already in that room when they got there in 4 (ezinne 1, oji 2,
ziri 1; ziri's proxy bedroom is Jaya Bedroom, which Jaya uses). Oji's and Ezinne's proxy room is the one Master Bedroom they share,
so "someone else there" is structural for them (the 8 of Oji's 33 are Ezinne asleep or in the room, on arrivals that include phantoms).
Jaya's and Ziri's proxy rooms also overlap (Jaya Bedroom).

## Implications

**900 s window.**
1. Reaching the own room is fast where it happens: p95 426 s, max 452 s across all four people. 900 s covers every measured reach
   with about 2x headroom; there is no evidence for a longer window and 600 s would also have covered every observed reach.
2. The window is not the main risk. Half of Ezinne's passing arrivals (8 of 16) never reach her own rooms in 900 s, so the
   "stop at window end outside own room" branch fires for her about once in two arrivals. That is a measured cost of the keep-or-stop
   rule, not an error; the operator should know it before D2.
3. Gate 3b (`ARRIVAL_MIN_AWAY_S` 900) filters 19 flaps (all Oji bar one Ezinne) but passes 29 phantom Oji arrivals (47 % of his
   passes, 48 % of all passes) with 903-17,666 s away. No clock threshold separates them from his 4 real returns (1814 s and up). 900 s
   is therefore a flap filter, not a presence confirmation. If the plan wants "someone actually arrived", it needs a body test
   (BLE room or census) at +60/+180 s, which is an operator decision (charter rule 3), and it would also be the answer to this
   producer-fires-with-nobody-there gap. Whether those 29 are GPS jitter at the geofence edge: inferred, source attribute not read.
4. The residency-row view (18 arrivals) understates the problem; it only exists since 11-13, after the 11-08/09 burst.

**Guest gate (guests detected blocks the arrival).**
1. With no visitor in the house, the census trips on 7 of 77 own arrivals at the edge and 4 of 77 at +180 s (10 of 77 across the
   three offsets); the passing-arrival figure is 9 of 58 (15.5 %). Most are the resident's own un-named body (total 1, ids empty) that
   self-heals by +60 to +180 s (most of the 10; I did not count exactly). Gating at the edge would silently drop about 1 arrival in 11 for a household with
   no guests; gating at +180 s drops about 1 in 19 (4 of 77). This is the number that "makes a gate look wrong": it goes to the
   operator.
2. With real guests the gate behaves as intended: the party-night arrival read 3 and 5 unidentified (blocked), and the `guest`
   house state alone blocked Ziri's two arrivals (census read 0).
3. House state `guest` is the clean signal (3 of 80, all real visitors). The census leg is the noisy one: it needs either a
   delay (re-evaluate at +180 s, since the own body is named by then in most of those) or a rule that discounts the arriving person's own
   body (the F2-F5 deconfliction in the identity model). I did not test either; they are options for the operator, not decisions.
4. Rule B (someone else already in the own room): 12 of 61 (20 %) passing arrivals have the room occupied or someone in it at the
   edge. For Oji and Ezinne the shared master suite makes this about "is the other
   adult in there"; the plan's occupied gate will block roughly 1 in 5 arrivals on that alone.

## Limits

- Own rooms are a derived proxy (section Method): Powder is in every set and Ziri's bedroom resolved to Jaya Bedroom. A saved
  profile would change items 3 and 4.
- Oji's visits are missing for 29 arrivals; his own-room numbers are not representative. The census read uses one snapshot at
  about 80 s cadence; "at +0" is the latest snapshot at or before the edge, not the edge itself.
- Window is 7 days with one party night; the visitor-home sample is 3 arrivals.
- 11-12 17:29 ezinne (away 0 s) is a flap that the census flagged; included in the counts above only where noted (all-80 tables), not in
  the passing-only tables.
- Raw output kept at `.claude/tmp/d0b_out_final.txt`; probe at `.claude/tmp/d0b_arrival_probe.py`.
