# NOT A BUILD SPEC: history of the interior ledger floor section (§1b)

This file is history only. Builders and reviewers read §1b of `docs/planning/PLANNING_vision_interior_sightings.md`,
never this file. Arc rule 5 (one clean document per scope).

| Version | Date | Base | What happened |
|---|---|---|---|
| §1b first spec | 2026-11-16 | develop c6230ade | Floor specified (sustained min only). |
| Q4 paragraph | 2026-11-16 | same | Operator chose a dropdown with both strategies; appended after §1b.10, never folded in. |
| plan reviews | 2026-11-17 | develop ef6149950 | `plan_review_ledger_floor_completeness_2026_11_17.md`, `plan_review_ledger_floor_buildpred_G_2026_11_17.md`: both PLAN-FIX-REQUIRED. |
| rewrite | 2026-11-17 | develop 335bf1284 | §1b replaced by one clean section with the ledger known-time precondition. The replaced text follows verbatim. |

## Replaced text (verbatim, superseded)

## 1b. Interior ledger floor (arc map §4a row 7; decided 2026-11-15, specified 2026-11-16)

Operator, verbatim: "Interior counting I still want just not for presence for now. For census instead and the ledger."
On the checkpoint anchor: "At quiet moments, when everyone is visible, an interior count could reset the ledger. How? This
didn't make sense". On dropping it: "Yes. I don't want to worry and derail from low probability concerns." Card
VISION-INTERIOR-SIGHTINGS-1 `operator_2026_11_15_ledger_floor_only`.

Code base for this section: develop @ c6230ade (ship 1 live as v5.108.28, 7 covered rooms; crossing ledger P2 and P3-D8
on develop). This is not the §9.D4 `deconflict_house` interior term, which stays as written. Ship 1 does not touch the
ledger; this section is its own build (call it **ship F**, after ship 2 per arc map §4a row 7).

### 1b.1 The rule

- The crossing ledger's level `L` is never below the visible interior floor `F` at a census tick while the ledger is
  `known`. When `F > L` the ledger **lifts `L` to exactly `F`** (it raises `L`, not just the displayed value), and opens
  an arrival credit of the lifted amount. `F` never lowers `L`, never sets `L` while `unknown`, never lifts above `F`,
  and never moves the anchor.
- **Dropped, not planned:** the checkpoint anchor (resetting `L` from interior counts at quiet moments). It needs every
  camera-less room provably empty, which is rare here and fragile.
- **Why lift `L` rather than clamp the display** (same reasoning as crossing plan P2-D2 step 4): a read-time
  `max(L, F)` leaves a missed entry as a hidden deficit. Repro with a clamp: true 3, `L = 2` (one entry missed), `F = 3`,
  display 3; a guest enters, `L = 3`, display 3, truth 4. With a lift, `L = 3` then 4. A clamp also violates the rule as
  the operator stated it ("L never below the visible interior count").
- **Why a credit:** the person the floor just counted usually has an entry term still in flight (the term's outcome lands
  ≈ 210 s after the crossing, the body shows up in the foyer within seconds). Without a credit that term would count
  them a second time. The lift reuses the resident floor's credit (`_credits`, consumed by `_consume_credits`
  `crossing_ledger.py:403-417`, window [`t − 300`, `t + 60`] via `CROSSING_VISION_GO_ARRIVAL_WINDOW_BEFORE_S` /
  `_AFTER_S`, expiry `_prune_credits` `:345-350`). One credit pool, so a resident lift and an interior lift for the same
  arrival cannot both fire: whichever runs first raises `L`, and the other then sees `L ≥` its target.

### 1b.2 The floor value `F` (producer)

- **Input:** the current room records, pulled at each `census_tick` by the crossing-vision wiring through
  `PresenceCoordinator.get_room_sightings()` (`domain_coordinators/presence.py:6048`). No new listener, no census change.
- **Per record contribution:** `bodies` when `liveness == "live"` and `bodies` is not None, else 0. Dead, lost, held,
  released, stuck and no-reading members already yield `bodies = None` or a non-live record through ship 1's rules
  (`member_liveness` `interior_vision.py:49-63`, `group_bodies_nvr` `:66-85`, `group_liveness` `:88-103`), so a dead or
  stuck camera contributes nothing and never raises `F`. A record contributes 0 when its `as_of` is older than
  `INTERIOR_LEDGER_FLOOR_RECORD_FRESH_S`. Omitting a room can only lower `F`, so the lower-bound property survives.
- **Sample:** `S(t)` = the sum over covered rooms at tick `t`; `S = None` when there are no records at all (room records
  disabled, producer missing, or every record stale).
- **Floor:** `F(now)` = the **minimum** of `S` over the samples in [`now − INTERIOR_LEDGER_FLOOR_SUSTAIN_S`, `now`],
  provided the oldest sample in the ring is at or before the window start and no sample in the window is None; else
  `F = None` (no floor this tick). A count must be sustained to count.
- **Why min, not the max the brief proposed (operator question Q4, §1a):** `F` raises `L` and the raise persists until an
  exit term or the next anchor. A max over a window turns any one-tick spike into a persistent phantom person: a person
  seen at once by two overlapping covered cameras (staircase, stairs_top, upstairs_hall and master_hallway plausibly
  overlap), an NVR false positive, or a person walking between rooms as both records update. A sustained minimum is the
  conservative reading of "lower bound". Cost: a person visible for less than the window does not lift `L` (the
  ledger then waits for the anchor, as today).
- **Overlap between rooms is not deduplicated.** Summing per-room records double-counts a person visible from two covered
  rooms at once. The sustain window absorbs walk-throughs; a person standing in a shared field of view is the residual.
  D0 gate F-b measures it; if it fails, the build stops for an operator decision (no overlap config is built speculatively).

### 1b.3 Ledger mechanics (pure core, `crossing_ledger.py`)

`CrossingLedger.census_tick(now, resident_term, camera_bodies, camera_input_dark, interior_floor=None)`: the new keyword
defaults to None, so every existing caller and test is byte-identical. Order inside the tick: store inputs, prune
credits, resident lift (step 4, unchanged), then the interior lift: while `known`, `L` and `L_raw` not None, `F` not None
and `L < F`: `k = F − L`, `L += k`, `L_raw += k`, credit `(now, k)` appended, `_changed_since_anchor = True`, one
`LedgerEvent(kind=KIND_INTERIOR_LIFT, n=k, l_before, l_after, l_raw_after)`. `R_prev` is not touched by the interior
lift. Running the resident lift first means a resident arrival is credited as a resident arrival when both rise on the
same tick.

Interactions, each pinned by a test:
- **Anchor:** the anchor still needs the census camera body total to be 0 (P2-D2 step 2), so `F` and the anchor rarely
  disagree. If they do (the anchor sets `L = R` while a room record still shows a body), the next tick lifts and the
  counter `interior_lift_after_anchor` records it. The floor never blocks, delays or fires the anchor.
- **Exit term:** an exit lowers `L`; if the person is still visible for the whole sustain window the next tick lifts back
  (the exit was early or over-counted). Counted as `interior_lift_after_exit` (lift within `reconcile_delay_s` of an
  applied exit).
- **Departure reconcile:** unchanged; it can lower `L` below `F`, and the next tick lifts back (a resident's phone left
  the house but a body is still visible).
- **Late and unknown:** while `unknown` no lift (the floor never makes the ledger known). Late terms are unaffected.
- **Resident term:** `guest_vis = max(0, L − R)`. A lift for a resident whose BLE has not yet raised `R` reads as
  guest + 1 until `R` rises (the same accepted transient as P2-D2 step 5).

### 1b.4 Consumers and trust exposure

| Value | Readers | Class |
|---|---|---|
| `F`, `S` ring, lift counters | `get_layer_diagnostics()["crossing_vision"]["crossing_ledger"]` (`interior_floor`, `interior_lifts_today`, `interior_lift_after_anchor`, `interior_lift_after_exit`) | display |
| `interior_lift` ledger rows | the crossing-vision scorer, diagnostics | display |
| `L` raised by a lift | `guest_vis` → `census_tick` → `PersonCensus._ledger_tick` (`camera_census.py:6920-6937`) → `deconflict_house(guest_vis=...)` | F2 input, awareness view, display today |

**Admission bar (no F2 consumer moves):** `deconflict_house` sets `aware_guests = guest_cam` unless `vision_leads`
(`census_deconflict.py:90-131`), and `CROSSING_VISION_AWARENESS_VISION_LEADS` is False (`const.py:7010`); the ledger's
consumer classes are {display} (`CROSSING_VISION_CONSUMER_CLASSES`, `const.py:6966`). So a lift changes only the
awareness `case` / `count_provenance` / `aware_agreement` metadata and the ledger diagnostics. It reaches no trust field,
no house state, no AWAY trigger, no access, comfort or security reader. Promotion is the census plan §3.2 ladder (the
ledger's own leads flag at its operator checkpoint); this section adds no rung. INV-SHADOW (crossing plan §4) is
unchanged: the floor enters `L` only inside `census_tick`.

F1-F5: the floor **consumes F4** (unnamed room records, `PersonSightingProducer`) and **produces an F2 input** (the
ledger's `L`, through the one hand-off `census_tick`); the census stays the one F2 writer. Consumer classes: display today;
notification and security none (§5.5(b): no consumer below display reads it).

### 1b.5 Invariant (falsifiable; reviewer D breaks it)

**INV-IV-FLOOR.** With `INTERIOR_LEDGER_FLOOR_ENABLED` True, for any sequence of ticks, terms, anchors, reconciles,
room-record builds (any liveness, any staleness) and restarts:
1. at every `census_tick` return while `known` with `F` not None, `L ≥ F`;
2. the interior input changes `L` only by a lift to exactly `F` from below: never lowers `L`, never lifts above `F`,
   never acts while `unknown`, never changes `R_prev`, the anchor window, `last_anchor_ts`, the applied-exit store or a
   pending reconcile;
3. no person is counted twice by a lift and an entry term: for an entry term whose E lies in the window of an open
   interior credit of size k, `L` rises by `n − min(n, credit)`;
4. a member that is not LIVE (held, released, stuck, no reading, lost, dead) or a stale record never raises `F`;
5. with the knob False, or `interior_floor=None`, the ledger's event stream, `L`, `L_raw`, `guest_vis` and every
   counter are byte-identical to develop @ c6230ade.

Break it with a sequence where `L < F` after a tick while known, a lift above `F`, a lift while unknown, a lift that moves
the anchor window, a double count of one arrival (W-F2 below shaped), or a stuck or dead camera's frozen count raising
`F`.

### 1b.6 Deliverables

**F-D0 floor probe (read-only, first; gates the build).** Script outside the repo (`.claude/tmp/floorprobe/`), report
`docs/planning/AUDIT_interior_ledger_floor_d0.md`. Data: 14 days of recorder history for the interior member entities,
resolved through the entity registry from `PersonCensus.interior_camera_entities()` (no name parsing); per covered group
the max over its legs; `S(t)` at 30 s. Joined with house-state history, census rows (`census_snapshots`
`unidentified_count`, BLE resident count) and `crossing_vision_ledger` rows (`L_after`, state). Measures:
- (a) **phantom rate:** sustained `S ≥ 1` episodes during AWAY (no residents; guests rare and checked against door
  entries), per week, at sustain 0 / 30 / 60 / 120 / 300 s;
- (b) **overlap:** among sustained episodes where `S > R + unidentified_count`, the share in which two or more covered
  cameras report bodies at once; the 10 largest listed with their camera pair for a hand look;
- (c) **fire rate:** sustained episodes with `S > L` while the ledger is `known`, per week, and the ledger's `known`
  fraction; if `known` < 50 % of the window, the proxy `S > R + unidentified_count` is reported as well.

Gates (rung 1, probe script): **F-a** phantom episodes per week at the chosen sustain ≤
`INTERIOR_D0_FLOOR_PHANTOM_MAX_PER_WEEK` (1); set `INTERIOR_LEDGER_FLOOR_SUSTAIN_S` to the smallest tested value that
passes; none ≤ 300 s → STOP, operator. **F-b** overlap share ≤ `INTERIOR_D0_FLOOR_OVERLAP_MAX` (0.2) → build; above →
STOP, operator question (dedupe overlapping cameras, rung 2 config, or drop the floor). **F-c** fire episodes (or proxy) ≥
`INTERIOR_D0_FLOOR_FIRE_MIN_PER_WEEK` (1) → build; below → PARK with revival trigger "ledger misses an entry the anchor
later corrects ≥ 1 / week" (the residue rows show it). Discrimination: a working floor predicts F-c episodes clustered
within 5 min of door entries whose term was missing or `n` too small; a phantom-driven floor predicts episodes with no
nearby door entry and AWAY overlap. The report states which.
- **Live:** the audit file exists with all three measures and a GO / STOP / PARK line per gate.

**F-D1 pure core (Tier 3).** `crossing_ledger.py`: `KIND_INTERIOR_LIFT = "interior_lift"`, the `interior_floor` keyword,
the lift (§1b.3), counters, `snapshot()` fields; a pure helper `interior_floor_of(samples, now, sustain_s)` (min over a
covered window, None otherwise) and `interior_sum(records, now, fresh_s)` (live-only sum, None when no records).
- **Tests** (`test_crossing_ledger_interior_floor.py`): `test_floor_lifts_L_to_F_while_known`;
  `test_floor_never_lowers_L`; `test_floor_noop_while_unknown`; `test_floor_lift_opens_credit`;
  `test_entry_term_after_floor_lift_consumes_credit` (W-F2: known, `L = R = 1`; guest body sustained, tick at t = 100
  lifts to 2; entry term E = 70 lands at 280 → `L` stays 2); `test_entry_term_outside_credit_window_adds`;
  `test_resident_lift_runs_before_interior_lift` (R 1 → 2 and `F = 2` on one tick → one resident lift, no interior lift);
  `test_floor_does_not_touch_anchor_window` (`_t_start`, `last_anchor_ts` unchanged by a lift);
  `test_lift_after_exit_counted`; `test_lift_after_anchor_counted`; `test_floor_none_is_noop`;
  `test_floor_disabled_byte_identical` (replay of the P2-D2 W1-W8 sequences with the knob False and with `F = None`
  → identical event streams); `test_interior_sum_live_only` (held / released / stuck / no-reading / lost records → 0);
  `test_interior_sum_stale_record_zero`; `test_floor_min_over_window`; `test_floor_none_when_window_uncovered`;
  `test_floor_none_when_sample_missing`; `test_sustain_zero_uses_latest_sample`.
  Config extremes: sustain 0 and 3600; fresh 0 (every record stale → `F = 0`, no lift); `F` far above `L` (lift k = 5
  in one tick).
- **Mutation (framing C):** drop the `L < F` guard → `test_floor_never_lowers_L`; drop the credit append →
  `test_entry_term_after_floor_lift_consumes_credit`; skip the `known` check → `test_floor_noop_while_unknown`; use
  max instead of min → `test_floor_min_over_window`; count non-live bodies → `test_interior_sum_live_only`; run the
  interior lift before the resident lift → `test_resident_lift_runs_before_interior_lift`.

**F-D2 wiring (Tier 3).** `CrossingVisionShadow.census_tick` (`crossing_vision.py:1222-1235`) pulls
`presence.get_room_sightings()` (guarded; any error → `S = None`), appends `(now, S)` to a RAM ring bounded by
`INTERIOR_LEDGER_FLOOR_SUSTAIN_S` plus one tick, computes `F`, and passes `interior_floor=F` (None when the knob is
False). The ring is RAM only; a restart starts empty (`F = None` until the window fills). `interior_lift` events are
batched into the existing `crossing_vision_ledger` episode write (`drain_events`, same path as `KIND_LIFT`). Guard: the
crossing-vision module becomes a pinned reader of `get_room_sightings` (`_layer_guard_engine.py:121` reader set,
`test_person_awareness_layer_guard.py:610` PINNED_READERS); the guard's total delta is +1 pinned reader, recorded in
§6.3.
- **Tests:** `test_census_tick_passes_interior_floor`; `test_room_sightings_error_gives_no_floor`;
  `test_floor_knob_false_passes_none`; `test_interior_lift_row_batched`; `test_ring_empty_after_restart`;
  `test_guard_crossing_vision_pinned_room_sightings_reader`.
- **Mutation:** pass the raw latest `S` instead of `F` → `test_census_tick_passes_interior_floor`; ignore the knob →
  `test_floor_knob_false_passes_none`.

**F-D3 fire check and trip-wires.** Diagnostics fields above. `fire_stuck_signal`
(`domain_coordinators/_stuck_signal_nm.py:173`) kinds: `interior_floor_input_zero` LOW (knob on, room records enabled,
ledger `known` for ≥ `INTERIOR_LEDGER_FLOOR_INPUT_ZERO_H` of the last such hours, and no tick with `F` not None: the
input never reached the ledger; this is the zero-fire wire, because a floor that never lifts is a normal outcome when the
ledger is right, while a floor that never has an input is a fault); `interior_floor_lift_storm` MEDIUM (lifts in a local
day > `INTERIOR_LEDGER_FLOOR_LIFT_STORM_PER_DAY`: the overcount signature D0 F-a and F-b guard against). RAM latches,
re-armed at local midnight.
- **Tests:** `test_input_zero_pages_once`, `test_input_zero_silent_while_unknown`, `test_lift_storm_pages_once`,
  `test_lift_storm_zero_disables`.
- **Live:** within 1 h of restart with the ledger `known`, `crossing_ledger.interior_floor` is a number (not None) on the
  layer diagnostics; `interior_lifts_today` and every `interior_lift` row's `l_after` equal that tick's `F`. Discriminates
  a working floor (rows with `l_after = F` near door entries) from a broken input (diagnostics `interior_floor` None and
  `interior_floor_input_zero` paged) and from phantoms (rows without a door entry within 5 min, storm page). Over the
  first week the lift count is within 3x of D0 (c)'s predicted rate (outside it = finding, revise §15).

### 1b.7 Knobs (also in §12)

| Knob | Default | Rung | Why / kill |
|---|---|---|---|
| `INTERIOR_LEDGER_FLOOR_ENABLED` | True | 1 | Kill switch; False = ledger byte-identical (INV-IV-FLOOR 5). Ships ON (no shadow mode); the ledger itself is display-only |
| `INTERIOR_LEDGER_FLOOR_SUSTAIN_S` | 60 (set by D0 F-a) | 1 | A count must hold this long; 0 = latest sample only |
| `INTERIOR_LEDGER_FLOOR_RECORD_FRESH_S` | 30 | 1 | 3x `INTERIOR_ROOM_RECORD_INTERVAL_S` (10 s); older records contribute 0 |
| `INTERIOR_LEDGER_FLOOR_INPUT_ZERO_H` | 24 | 1 | Zero-input trip-wire window; 0 = off |
| `INTERIOR_LEDGER_FLOOR_LIFT_STORM_PER_DAY` | 6 | 1 | Overcount trip-wire; 0 = off |
| `INTERIOR_D0_FLOOR_PHANTOM_MAX_PER_WEEK` / `_OVERLAP_MAX` / `_FIRE_MIN_PER_WEEK` | 1 / 0.2 / 1 | 1 (probe script) | D0 gates |

Rung 1 for all: they bound a Tier-3 state machine's writer and should change only by reviewed code.

### 1b.8 Non-goals

The checkpoint anchor (dropped). Any change to the anchor predicate, the resident floor, terms, reconciles or the
ledger's leads flag. Cross-room overlap deduplication (only if D0 F-b fails, by operator decision). Vision counts
(ship 3's `bodies_vision`) get no special handling: the record's `bodies` already prefers them. Persisting the ring.
Any reader of `F` outside the ledger and diagnostics.

### 1b.9 Tier

Build: **Tier 3** (a new writer to `L` inside the crossing ledger's Tier-3 state machine; the failure mode is a double
count through one missed interaction, INV-P2-ONCE). Reviews A / B / C (mutation) / D (completeness on INV-IV-FLOOR and
INV-P2-ONCE / INV-P2-DISCHARGE, pre-existing ledger paths included) plus framing G; orchestrator re-grep and one source
mutation; operator checkpoint before deploy. Light consequence: every consumer is display today. Plan amendment: two
plan reviews (completeness; build prediction) plus G before build. Order: F-D0, then F-D1 + F-D2 + F-D3 in one ship
after ship 2.

### 1b.10 Prior art (REUSE / BUILD, greps on develop c6230ade)

`git grep -n "INTERIOR_LEDGER_FLOOR\|interior_lift\|KIND_INTERIOR" -- custom_components quality docs` → 0 hits. The
archived round-6 estimator's held-max FLOOR (`archive/HISTORY_census_occupancy_estimator_round6.md:66`, `FLOOR_WINDOW_S`
1200) was a different design (a max-hold census floor) and was discarded; nothing of it is in code.

| Piece | Verdict | Where |
|---|---|---|
| Room records (bodies, liveness, as_of) | REUSE | `build_room_records` `interior_vision.py:137-191`; store `person_sighting.py:908`, read `:928` |
| Pull API | REUSE | `PresenceCoordinator.get_room_sightings` `presence.py:6048-6053` |
| Liveness, dead and stuck handling | REUSE | `member_liveness` `interior_vision.py:49`, `group_bodies_nvr` `:66`, `group_liveness` `:88` |
| Lift + credit | EXTEND | resident floor in `CrossingLedger.census_tick` `crossing_ledger.py:352-395`; `_consume_credits` `:403`; `_prune_credits` `:345` |
| Event row | REUSE type, NEW kind | `LedgerEvent` `crossing_ledger.py:71`; kinds `:57-60`; `CROSSING_VISION_LEDGER_EPISODE_TYPE` `const.py:3705` |
| Hand-off | EXTEND | `CrossingVisionShadow.census_tick` `crossing_vision.py:1222-1235`; census caller `camera_census.py:6928` unchanged |
| Admission bar | REUSE | `deconflict_house` `census_deconflict.py:90-131`; `CROSSING_VISION_AWARENESS_VISION_LEADS` `const.py:7010`; `CROSSING_VISION_CONSUMER_CLASSES` `const.py:6966` |
| Trip-wires | REUSE helper, NEW kinds | `fire_stuck_signal` `_stuck_signal_nm.py:173` |
| Guard pin | EXTEND | `_layer_guard_engine.py:121`, `test_person_awareness_layer_guard.py:610` |
| Floor window, ring, sum | BUILD | no equivalent (the only other "floor" in the ledger is the resident lift) |

Config-first: no existing knob or setting yields a floor; the ledger has no interior input today.


**Operator 2026-11-16 on Q4 (floor strategy):** "Maybe we can test diff strategies using s drop down with a default. I agree with your reco. We can cleanup after we arrive at the best. Test in parallel. Unless you're sure." Decision: the floor strategy is a Select knob `select.ura_interior_floor_strategy` (rung 3, live-tunable) with options `sustained_min` (DEFAULT, 60 s) and `window_max`. Both strategies are computed every tick and written side by side to diagnostics and the `interior_floor` rows (`floor_min`, `floor_max`, `strategy_applied`); only the selected one may lift L. F-D0 replays 14 days under BOTH strategies and reports phantom rate, overlap double-count and fire rate per strategy. Cleanup: once one strategy wins on F-D0 plus live rows, remove the loser and the Select (card it at ship).

