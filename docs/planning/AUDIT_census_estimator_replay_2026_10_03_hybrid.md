# AUDIT — D0-REPLAY: HYBRID census floor on 2026-10-03

**Plan:** `PLANNING_census_occupancy_estimator.md` §9 D0-REPLAY (gates §8.2, truth §8.1).
**Nature:** a one-shot, read-only offline replay. The HA recorder and URA DB were opened `?mode=ro` over `ssh ha "python3 -"`. No HA writes and no integration code changes.
**Script:** `scripts/probes/census_d0/census_estimator_replay.py`. It adds a HYBRID section ahead of the legacy P1–P8 sections. `HYBRID_ONLY=True` runs the hybrid report and exits. `VARIANTS_ONLY=True` prints only the sensitivity table. Raw outputs are in `scripts/probes/census_d0/out_hybrid_2026_10_03.md` and `out_hybrid_variants_2026_10_03.md`.
**Run date:** 2026-10-04.

## Verdict: **NO-GO for the D3 build as specified.** Gates 2, 3 and 5 fail. Gate 4 passes only by coincidence (see below).

## Model replayed

- `FLOOR = R + max(0, max(M_cam − R, 0), U_gr, T)` and `ESTIMATE = FLOOR + B`.
- **`R`** is the `person.*` home count (ezinne, oji_udezue, jaya, ziri).
- **`S`** is overlap-deduped Frigate `person_count`, sampled every 15 s. The components are {family_room, master_hallway} as a max, and each other camera standing alone (foyer_fisheye, staircase, stairs_top, playroom, upstairs_hall).
- **`M_cam`** is the held max of S over `FLOOR_WINDOW_S`, with the observed-exit shrink to 180 s for 600 s.
- **`U_gr`** counts guest-room presence with no resident phone in that room.
- **Revel** (`W`) is EXCLUDED.
- **Door pipeline**, run on the `person_entry_exit_events` ledger:
  1. Leg-collapse: same stem, same direction, 30 s.
  2. Same-person: same door group, same direction, 10 s.
  3. Round-trip: opposite direction at the same door group within 180 s, only when neither crossing carries a resident pid.
  4. Attribution, in order: resident pid; then a person-tracker edge within ±120 s (each edge used once, with the crossing counted provisionally until the edge arrives); then the main-entry prior at `garage_a` (provisional; final if an edge arrives within ±300 s, otherwise reversed into T at +300 s).
  5. T counts unattributed crossings: +1 per entry, −1 per exit, never below 0.
- **Door groups** (as the plan states them): front = {madrone_g6_entry, front_door_aerial, doorbell_lite}, garage_a = {garage_a}, garage_b = {garage_b}.
- **Empty anchor:** `R=0 ∧ M_cam=0 ∧ U_gr=0` held for 900 s. It is not armed for 600 s after a restart (boot settle). On firing, T, B and the M_cam history are cleared.
- **Tally age-out:** after `DOOR_TALLY_STALE_S` with no camera body, T decays.
- **Replay span:** full recorder retention, starting at T=0.

**Knob values used:** `FLOOR_WINDOW_S=1200, FLOOR_SHRINK_HOLD_S=600, shrink window=180, DOOR_ROUNDTRIP_S=180, DOOR_SAMEPERSON_S=10, stem dedup=30, DOOR_TALLY_STALE_S=3600, AMBIGUOUS_DECAY_S=1800, RESIDENT_CROSSING_MATCH_S=120, MAIN_ENTRY_PRIOR_S=300, EMPTY_ANCHOR_SETTLE_S=900, BOOT_SETTLE_S=600, DOOR_TALLY_MAX=30, ESTIMATE_DECAY_S=1800, CONF_MAIN_ENTRY_DOOR=garage_a`. Tick 60 s.

**P-AMB, T_amb and B were inert in this replay.** The ledger holds only `entry`/`exit` rows and no AMBIGUOUS ones, because production direction resolution always picks a direction. So B is non-zero only while a main-entry-prior crossing is still provisional.

## Truth revision applied (operator, 2026-10-04 — supersedes the §8.1 table where it differs)

- **Residents:** the operator WAS home from 15:42 (dropped Jaya off and came straight back). Afternoon and evening residents = 2 (operator + Ezinne). Jaya is out until about 23:24, when she returns with the operator via `garage_a`. The person trackers match this account, so truth now uses the **tracker R** for each bin, plus a guest band.
- **12:00–13:30 front-door burst:** the operator cleaning the front porch (resident in/out, net 0), plus one drop-off visitor who left with the operator by car (transient, net 0). Guest band for 12:00–13:30 is 0–1.
- **Long-stay guest:** a guest. Out in the morning, back in the evening.
- **Guest bands used:**

| Window (CDT) | Guests |
|---|---|
| 00–08 | 1 |
| 08–12 | 0 |
| 12–13:30 | 0–1 |
| 13:30–14:20 | 0 |
| 14:20–17 | 8–9 |
| 17–23 | 8–10 |
| 23–23:55 | 8–9 |
| after 23:55 | 7–8 |

  The script's `h_truth()` now encodes this. Gates 2–4 below were re-scored from the 15-min bin means using this truth. G5 is unchanged, because its window (morning, R=3, 0 guests) is the same.

## Gate table (re-scored against the revised operator truth, 15-min bins)

| Gate | Criterion | Result | GO/NO-GO |
|---|---|---|---|
| 1 Ordering | FLOOR ≤ ESTIMATE in 100% of bins | 100% | **GO** |
| 2 Floor soundness | FLOOR ≤ truth_hi in ≥95% of bins | **64%** (was 76% against §8.1; no anchor erasures on 10-03) | **NO-GO** |
| 3 Household-norm | \|FLOOR−truth\| ≤ 1 in ≥90% of bins before 14:20 | **81%** (was 75% against §8.1) | **NO-GO** |
| 4 Party band | \|FLOOR−truth\| ≤ 2 in ≥70% and FLOOR ≥ 4 in ≥80% after 14:20 | 100% / 100% (unchanged) | GO on paper, **but coincidental** (see finding 1) |
| 5 Resident-only false positive | guest_estimate = 0 in ≥90% of morning minutes with R=3 | 30% | **NO-GO** |
| 6 Anchor | T=0 and FLOOR=0 at every anchor | 19 anchor fires, all FLOOR=0 and T=0 (09-27, 09-28) | **GO** (with no T_pre>0 cases; not tested on 10-03, where the house was never empty) |
| 7 F5 / AWAY-safe | FLOOR > 0 at 15:53/16:01/17:02; AWAY blocked at 15:57 | 15:53: F=12 > R=2. 15:57, 16:01 and 17:02 fall in HA downtime. The persisted T gives F=11–12 > R across the restart. | **GO (conditional)** — this depends on T persisting across the restart (§7.7) |
| 8 23:24 garage_a | Both residents attributed, not counted as guests | 23:25:03 → `prior_final` (oji edge 23:28); 23:26:10 → `prior_final` (jaya edge 23:28) | **GO** |
| 9 Guest-side max | Synthetic R=2, U_gr=1, M_cam=3, T=0 gives FLOOR=3 | 3 | **GO** |

**`d0_front_14_20_entries_surviving` = 0** (14:10–14:40, front door). The upper bound before collapse is only 4 raw entry legs plus 2 exit legs. These became 2 logical entries after leg-collapse and 1 after same-person. That one (14:25:01) was then round-trip-paired with a 14:25:21 exit, which leaves 0. **The ≥6/8 acceptance criterion fails.** The ledger simply does not contain 8 front-door entries at 14:20.

## Findings

1. **The door tally does not see the 14:20 party, and it counts phantom guests at midday.** The revised truth confirms the midday crossings were resident porch-cleaning plus one transient visitor, net 0. The pipeline could not attribute any of them: the front door is not the main entry, and no tracker edges or pids were present. So every midday crossing became guest T. This is the concrete failure mode the plan's attribution does not cover: a resident making repeated in/out trips at a non-main door while their tracker stays `home`, so no tracker edge fires. T climbs to 8 between 12:06 and 13:02 (front entries at 12:38, 12:42 and 13:02; garage_b at 12:13; four reversed garage_a priors between 12:08 and 12:49). That puts FLOOR at about 11 from 13:00 against a truth of 3, then 1–2.
   - The 12:00–13:30 ledger burst is the §8.4 discrepancy, and it is now the dominant error. §8.4 option (a) or (b) is resolved: resident porch activity plus a transient visitor.
   - The party itself is visible only on camera: M_cam reaches 9.9 at 14:30. But M_cam bleeds away within the 20-min window.
   - Gate 4 passes only because the phantom T≈9–10 happens to equal the real party size.
   - When the midday false positives are removed (variant "doorbell→garage_a + prior permanent"), G4 falls to 8%. The hybrid has no durable way to hold the party.
2. **Main-entry prior reversals are the largest source of false T.** 11 garage_a crossings on 10-03 were reversed (6 entries, 5 exits), because tracker edges rarely land within 300 s; this matches the §8.0 P3 finding that edges cover about 19% of crossings.
   - Making the prior permanent improves G2 and G3 slightly (81% / 79%) and is still NO-GO.
   - This points to the prerequisite card `EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1`.
3. **doorbell_lite fires together with garage_a.** It fired at 23:25:56 and 23:30:57, alongside garage_a at 23:25:03 and 23:30:57.
   - Mapped to `front` as the plan specifies, it adds a phantom guest entry at 23:25, giving FLOOR=14 at 23:45 against a truth of 12.
   - Mapped to garage_a, FLOOR at 23:45 is 10.
   - The plan's door-group mapping (§4.3) needs operator confirmation, because the prior D0 script had doorbell_lite in garageA.
4. **G5 fails on the camera term, not on T.** Between 10:00 and 11:15, M_cam reads 4–5 while R=3 and truth is 3, so the camera term adds 1–2 guests. Possible causes:
   - interior over-count from mirrors or reflections;
   - an unlisted overlap pair;
   - the 20-min hold stacking per-component peaks that never happen at the same time.

   Shortening `FLOOR_WINDOW_S` to 600 only moves G5 from 30% to 41%. The CSV fixture also says 4–5 at 12:00, so the "long-stay guest out in AM" truth may itself be wrong (§8.1 FLAG). The operator has now confirmed the guest was out in the morning, so this IS an estimator / camera over-count defect.
5. **Overnight 00:00–07:30:** FLOOR is 3 against truth 4, because the sleeping long-stay guest is invisible (U_gr is mostly 0 and T=0 from the start). This is within the ±1 tolerance, but it is a systematic under-count.
6. **The anchor fired about every 30 min while the house was empty on 09-27.** This is an artifact of the replay re-arming its anchor loop, and it is harmless. No anchor fired on 10-03.

## Sensitivity (warm-up from 10-01)

| variant | G1 | G2 | G3 | G4 within 2 | G4 F≥4 | G5 | FLOOR 13:00 | FLOOR 23:45 |
|---|---|---|---|---|---|---|---|---|
| baseline (plan) | 100% | 76% | 75% | 100% | 100% | 30% | 10 | 14 |
| doorbell_lite→garage_a | 100% | 82% | 75% | 82% | 100% | 34% | 9 | 10 |
| prior permanent | 100% | 81% | 79% | 92% | 100% | 31% | 6 | 12 |
| FLOOR_WINDOW_S=600 | 100% | 77% | 75% | 100% | 100% | 41% | 10 | 14 |
| no main-entry prior | 100% | 77% | 75% | 95% | 100% | 30% | 9 | 15 |
| doorbell→garage_a + prior permanent | 100% | 83% | 81% | 8% | 97% | 36% | 4 | 8 |

No variant passes G2, G3 and G5 together. (The sensitivity runs were scored against the §8.1 truth. The revised truth lowers G2 further, so the verdict does not change.)

## NO-GO routing (§8.3)

- **The plan's gate-8 failure mode did not occur** (gate 8 passed). The real failure is the converse: the prior *reverses* too often and creates false T. That routes to the BLE provenance prerequisite.
- **D7-class gap (door group count):** the 14:20 group of 8 is not recoverable from the ledger, where 1 logical entry survives.

## Open items for the operator (listed, not resolved)

- Confirm whether doorbell_lite belongs to `front` or `garage_a`.
- ~~Confirm the 12:00–13:30 activity~~ — RESOLVED by the operator: porch cleaning plus a transient drop-off visitor. Still open: the garage_a and garage_b crossings at 12:08–12:49 (Ezinne's tracker was out 12:19–12:57, and those crossings did not match it within 300 s).
- The operator confirms the long-stay guest was out in the morning. So the 10:00–11:15 M_cam reading of 4–5 (with the CSV also saying 4–5 at 12:00) is a **camera over-count**, which makes G5 a confirmed estimator defect.
- Confirm the 14:20 arrival route. The front door logged only one round-trip at 14:25.
