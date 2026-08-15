# AUDIT — Hierarchical-memory retro-value (MEMORY-RETRO-VALUE-1)

**Date:** 2026-08-14 · **Read-only** — live URA DB opened `mode=ro` over ssh only.
**Question:** for the last four investigations, how much of the answer was already
sitting in `memory_episodes` + the `memory_facade.py` verbs
(episodes/narrative/unusual/profile/facts), had we consulted memory FIRST?

**DB ground truth at audit time:** `memory_episodes` spans
2026-08-02T22:58Z → 2026-08-14T22:55Z. Type counts: `exterior_track` 1050,
`actuation_conflict` 639, `occupancy_phantom` 56, `fan_transition_suppressed` 41,
`comfort_fan_vetoed` 19.

---

## Structural finding first (explains half the verdicts)

**Memory writers ride the detectors, so every detector blind spot is a memory
blind spot.** The `occupancy_phantom` episode is written INSIDE the D2 demotion
path (`coordinator.py:3455-3490`, "the D2 demotion IS the phantom-adjudication
event"). D2 is fail-closed for rooms with no PIR (`_d2_motion_sensors_present`,
`coordinator.py:1786-1815`). Consequence, verified in the data: all 56
`occupancy_phantom` rows come from PIR-equipped rooms (Ziri 39, Exercise 10,
Kitchen 4, ...), and the three rooms that actually latched on 2026-08-13
(Living Room, Upstairs Guestroom, Jaya Bedroom — all no-PIR) have **zero**
phantom rows. Upstairs Guestroom has zero rows of ANY episode type, ever.
Memory currently records where the system already catches the problem, not
where it fails — the retro-value ceiling for incident forensics is set by the
writers' own gates, not by the query verbs.

---

## Investigation 1 — AWAY-BLOCK-1 (house stuck occupied 2026-08-13)

**Verdict: PARTIAL.**

Query run:

```sql
SELECT node_id, episode_type, started_at, attrs_json FROM memory_episodes
WHERE started_at BETWEEN '2026-08-13T13:00' AND '2026-08-13T21:30'
  AND episode_type != 'exterior_track' ORDER BY started_at;
```

Rows found in the incident window: 15× `actuation_conflict`
(master_bedroom/study_a `fan_off` suppressed, 5-min ticks), **one**
`occupancy_phantom` — `room:ziri_bedroom_(bedroom_5)` 16:36:22Z, reason
`mmwave_sole_fan_on_no_corroboration` — and one living_room
`actuation_conflict` at 20:40Z. **Nothing** for the three latched rooms during
the 18:40–20:46Z hold.

What memory WOULD have given us fast:
- `unusual()`/`profile()` over `occupancy_phantom` shows the house's dominant
  phantom class is exactly **fan-driven mmWave-sole occupancy** (56/56 rows,
  one reason string), recurring daily, including on incident day. Consulting it
  first would have primed the fan→mmWave hypothesis in minutes instead of
  emerging from a 4-hour recorder trace.
- `comfort_fan_vetoed` rows `room:jaya_bedroom_(bedroom_4)` 21:50/21:55/22:00Z
  with `house_state=away` record the **aftermath of the unreleased Jaya latch**
  (F1's negative control): a fan still demanding to run in an away house.

What memory could NOT answer:
- The actual loop rooms (no episodes — writer gate).
- The away-block mechanism itself: path-α trust collapse, path-β indoor veto,
  census arithmetic. No episode type touches person-tracker trust, house-state
  transitions, or zone/house-tier occupancy provenance.
- The F2 zone-vs-house-tier divergence (no zone-tier episodes exist at all).

## Investigation 2 — Guest-mode false positives

**Verdict: NONE.**

Query run: full `occupancy_phantom` dump (all 56 rows) + type census. Every
phantom row is a room-tier fan/mmWave phantom; none carries census,
`unidentified_count`, `excluded_persons`, or guest-gate state. There is no
episode type for house-state transitions or guest-gate arming — the audit's
recurrence check correctly used `house_state_log` (a non-memory table) plus
recorder attrs. Additionally, memory begins 2026-08-02 while the recurrence
window opened 2026-07-13, so even a perfect writer would have missed 20 days.
The `occupancy_phantom` type does NOT cover the phantom-*unidentified* (census)
pattern — different tier, different mechanism.

## Investigation 3 — Frigate ghost / F2 first-witness (AUDIT_f2_first_witness_daytime)

**Verdict: PARTIAL — useful for ghost attribution, structurally unable to
answer first-witness.**

Query run:

```sql
SELECT node_id, started_at, attrs_json FROM memory_episodes
WHERE episode_type='exterior_track' ORDER BY started_at DESC LIMIT 5;
-- plus attr-key census over all 1050 rows
```

All 1050 rows are `exterior:perimeter`, adjudication `observed`, attrs:
`track_id, label, sub_label, classification, path, hops[{camera, t_first,
t_last, best_score, best_event_id}], duration_s, camera_count, revisit_count,
identified, path_string`. Daily volume 64–215.

- **First-witness question (F2 vs Protect latency): NONE.** `best_event_id` is
  a Frigate event id — the episode records **Frigate-only** witnesses. There is
  no UniFi Protect or native-AI timestamp in the payload, so the F2−Protect
  delta (the audit's entire question) cannot be computed from memory. The
  recorder probe was necessary.
- **Ghost attribution: genuinely useful.** Per-track `hops` with per-camera
  `t_first`/`best_score` + `duration_s`/`camera_count` let `episodes()` rank
  ghost-shaped tracks directly (e.g. live rows with `best_score: 0.0`,
  single-camera 6-s "car" tracks). The evidence-chain questions ("what did
  camera X track at time T, along what path") ARE answerable — better shaped
  than raw recorder rows. It would also have flagged the 08-11 F2 outage
  (day-count query shows 137 rows on 08-11, so Frigate-2's tracker was alive —
  useful cross-check against the audit's zero-F2-binary-sensor anomaly that
  day).

## Investigation 4 — Guestroom Hobeian fan-latch ×2 (SENSOR-FANINDEP-1)

**Verdict: NONE.**

Queries run: full dumps of `fan_transition_suppressed` (41 rows) and
`comfort_fan_vetoed` (19 rows) + distinct-node census. **Upstairs Guestroom
appears in no episode of any type in the whole table.** Neither latch episode
(16:38→18:37Z release +36 s; 19:07→20:46Z release +22 s) is recorded:
- `fan_transition_suppressed` is creation-window-only (Δt ≤ 5 s at occupancy
  creation); both latches were sustain captures — out of the writer's scope by
  the same design the AWAY-BLOCK audit documented.
- `occupancy_phantom` can't fire there (no-PIR room, D2 gate).
- `comfort_fan_vetoed` fires only in away/vacation house states; house was
  home_day.

---

## Summary table

| # | Investigation | Verdict | What memory had | What it lacked |
|---|---|---|---|---|
| 1 | AWAY-BLOCK-1 (stuck occupied, fan self-loop) | **PARTIAL** | Dominant phantom class = fan-driven mmwave-sole (56 rows incl. incident day); Jaya post-away fan-veto rows date the unreleased latch | Zero episodes for the 3 actual loop rooms (writer inherits D2 no-PIR gate); nothing on trust collapse / away paths / zone tier |
| 2 | Guest-mode FPs | **NONE** | — | No house-state / census / guest-gate episode type; memory starts 08-02, window opened 07-13 |
| 3 | Frigate ghost / F2 first-witness | **PARTIAL** | Per-track path+hops+scores answer ghost-attribution + evidence-chain queries; 08-11 tracker-liveness cross-check | Frigate-only witnesses — no Protect/native timestamps, so first-witness latency unanswerable |
| 4 | Guestroom fan-latch ×2 | **NONE** | — | Room absent from table entirely: creation-only suppression writer + D2-gated phantom writer + away-only fan veto all miss sustain latches in no-PIR rooms |

Net: **0 FULL, 2 PARTIAL, 2 NONE.** Memory today accelerates hypothesis
formation for problem CLASSES it already detects, and is a good exterior
evidence chain — but it cannot yet replace recorder forensics for any of the
four incidents, chiefly because writers sit behind the same gates whose
failures caused the incidents.

## Episode types that earn distillation priority (input to compactor plan)

1. **`occupancy_phantom`** — highest signal density per row; already
   adjudicated (`d2_demotion`); one reason string, clean per-room recurrence
   profile (Ziri 39, Exercise 10). Distill to per-room phantom rate + typical
   fan_on_duration; this is the "which rooms have a fan/mmWave problem" answer.
2. **`comfort_fan_vetoed`** — small (19) but every row is a fan demanding to
   run in an away house = latch-aftermath tripwire. Distill per-room counts.
3. **`exterior_track`** — 1050 rows, per-row value low but attrs rich; distill
   to per-camera/label daily baselines + outlier tracks (score 0, long
   duration, multi-camera, identified). The raw rows can compact aggressively.
4. **`actuation_conflict`** — 639 rows dominated by identical 5-min-tick
   `fan_off temp_hvac suppressed` repeats (e.g. master_bedroom runs); lowest
   retro value per row; compact to (room, action, trigger, house_state) daily
   counts with first/last timestamps.
5. `fan_transition_suppressed` — keep as-is (41 rows, already sparse); its
   `count` attr already self-aggregates per streak.

## Missing episode types (candidates for future writers — list only, not built)

- **`occupancy_phantom` (retro, D2-independent)** — fan-release-correlation
  writer: mmwave released within ~60 s of fan-off after a sustained hold →
  retroactive phantom episode, no corroborator required. Would have recorded
  all three 08-13 latches and both Guestroom latches.
- **`away_transition_blocked`** — house-tier episode each tick the away
  fallback paths are vetoed, with attrs {blocking_zone, provenance,
  veto_path, trusted_count, census}. Would have made the 82-min block a
  first-class queryable object.
- **`tracker_trust_excluded`** — episode when a person tracker enters/leaves
  LOST/STALE exclusion; the all-four-excluded state was the α-killer and is
  invisible to memory.
- **`house_state_transition`** — guest/away/home transitions with the gate
  inputs snapshot (census, unidentified, excluded_persons). Covers the guest-FP
  recurrence question natively.
- **`zone_phantom` / zone-tier divergence** — zone occupied at zone tier while
  house tier reads it away (the F2 divergence has no witness anywhere today).
- **`exterior_track` multi-source witnesses** — optional Protect/native first-on
  timestamps in hops, enabling first-witness comparisons from memory.

*Read-only audit; no code or configuration changed.*
