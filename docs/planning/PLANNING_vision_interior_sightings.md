# PLANNING: interior vision sightings (correct and supplement interior person counts; describe what is happening)

Card: VISION-INTERIOR-SIGHTINGS-1 (parent VISION-CROSSING-ANALYSIS-1, batch person-sightings, arc step 9). Tier 3 overall
(D4 touches the census deconfliction function); per-ship tiers in §16. One clean document (arc rule 5); its history is in
`docs/planning/archive/PLANNING_vision_interior_sightings_history.md` (NOT A BUILD SPEC). Nothing here edits another plan;
the edits other plans need are listed in §14.

Code base: `feature/layer-ship3b` @ 5d8b831d (ship 3b, CameraTwinHealth, shipping as v5.108.25) on top of develop
8d6eaa26 (v5.108.24, layer ship 3a live). Every `file:line` below is on 5d8b831d unless marked. A build starts only after
ship 3b is on develop.

Read completely before writing: charter `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md` (goals section),
`.claude/skills/ura-arc/SKILL.md`, `ARC_identity_vision_census_map.md`, `CONTRACT_person_awareness_layer.md`,
`PLANNING_person_awareness_layer_ship3.md` §5 D7 and §6, `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. the §10
corrections ledger; nothing below re-asserts a ledger claim, and §10 #41 is why every camera read here goes through ship
3b), `SENSOR_FLEET_CLASSES.md` (no radar or motion sensor is read by this plan), `IDENTITY_FUSION_CAMERAS_MANUAL.md` §4.5a
and §5.5, census deconfliction plan §3.2-§3.3, and both plan reviews of 2026-11-15. HVAC is not touched (no HVAC reader at
any rung), so the HVAC state of play does not apply.

## 1. Charter and operator direction

Charter, verbatim: "Vision is to assist census accuracy. And assist arrivals accuracy and personalization. Especially when
combined with facial recognition from the nvr systems. Frankly our job is to make it faster and faster until it can
eventually be used in security applications too." Hard constraint: "I need away to be fast acting." Charter 2026-11-14:
"vision will eventually be able to pull short clips of video to watch. Make sure no plan precludes that." "A dead camera is
not a presence or absence of signal. Its faulty equipment." "Switches should have a config flow entry"; "Name of switch.
not good yet."; "For all camera work I like to exercise both nvr platforms simultaneously, then cross compare"; "I assume if
even one nvr has the cam it doesn't count as dead"; registry: "Unacceptable to do the latter anymore"; "They need about 10
weeks. Foul. Why that long?" (gates sized to error rates, not calendar). Memory `feedback_no_shadow_mode_day1_correct`: no
shadow mode; features die when not switched on.

On this card: "We need this. Sequence is optional as long as you don't drop it."; "Ble is literal, Vision adds depth.
Eventually we should be able to see and decode emotion."; "[Path time-lapse] with interior vision but link the plans... I
Want this tight and not deferred. Make sure its useful."; "camera body counts: The problem is this is error prone when it
depends on nvr integration sensors. This vision should help. Did you measure the error in the camera body counts?";
"Interior vision is meant to supplement person counts sensors. And allow us to describe what is happening with people when
we need it. It should add depth (emotion is the deepest). Privacy in the main objection."; "Accept privacy now. If the
accuracy holds up, we should move to local"; "parking needs to ask me"; "It can be dynamic. Especially close to entires and
not so much in steady state." (sampling).

Goals: **G1** census accuracy (guests are the hard part), **G2** arrivals accuracy, **G3** personalization, **G4** faster,
toward security, **G5** depth (describe what is happening; emotion the deepest), **G6** move inference local once accuracy
holds (privacy).

Decisions recorded for this plan (orchestrator, 2026-11-15, relaying the operator): tight and not deferred; ship order is
review G's minimum path (§8c); the vision switch ships ON under call and cost caps with a name that does not say "shadow";
nothing before the D4 flip waits on NVR witness W2; every camera read is built on ship 3b; the F4 producer is
`PersonSightingProducer._emit_unnamed`; D4 is a pulled house scalar passed on its own `deconflict_house` keyword `interior_term=`, never inside `extra_guest_terms` (every entry there feeds `vis`, `census_deconflict.py:105`); `named` comes from
`persons_in_room` with the phone-left-behind filter; the affect field ships ON behind a module constant, recorded and
observational with no consumer yet (operator 2026-11-15: "Emotion yes as prep for the future"); naming people who are not
enrolled is a non-goal (operator 2026-11-15: "Not expecting new names. Names come from people I enrolled. This is few and
far between. Non goal").

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

## 1a. Decisions pending (operator); the build uses the recommended default unless the operator overrides

| # | Question | Default the build uses | Alternative | Where it lands |
|---|---|---|---|---|
| Q1 | Can interior move `aware_guests` on its own bar, or only after the crossing ledger is promoted to lead (one shared flag)? | **Interior gets its own leads argument on `deconflict_house`** (`interior_leads`, driven by `INTERIOR_VISION_TERM_LEADS`), so interior moves `aware_guests` once it passes ITS OWN bar (§9.D4), independent of the ledger's promotion. Reason: charter "tight and not deferred", "do the hard parts sooner"; the crossing ledger has never been known live, so coupling would park interior behind an unproven producer. **Tier 3 impact:** a signature change to `deconflict_house` (`census_deconflict.py:90-131`) and a second awareness-only rung; it amends census deconfliction plan §3.3 (function and rule 3) and §3.2 (ladder: interior gets its own leads rung). Owned by ship 5 (already Tier 3); the census plan text is edited by the orchestrator (§14). Trust view, AWAY inputs and `unidentified_count` are untouched either way | Share the one `CROSSING_VISION_AWARENESS_VISION_LEADS` flag (draft-3 rule: interior moves `aware_guests` only once the ledger leads) | §9.D4, §13, §14 |
| Q2 | Who may ask URA to `describe` a room or a person? | **Operator only.** Select `select.ura_interior_describe_access` (rung 3, CM device) with options `operator` (default), `operator_affect`, `residents`, `any_resolved`. "Operator" = the NM persons on `CONF_NM_SECURITY_ACK_PERSONS`, else the first `CONF_NM_PERSONS` entry's `CONF_NM_PERSON_ENTITY`. Build note (spot-check L-b): factor the resolution at `notification_manager.py:3460-3466` into a helper (`_operator_person_entities()`) used by both; do NOT call `_is_authorized_to_ack`, which returns `(True, "any")` for non-security hazards; compare the requester as a `CONF_NM_PERSON_ENTITY` value. `residents` = any person in `CONF_NM_PERSONS` (the configured household NM persons); `any_resolved` = any requester the channel resolves to a person. The NM reply NEVER includes affect unless the Select is `operator_affect` (operator requester only); `residents` / `any_resolved` never get affect | No gate (any resolved NM person, draft 3) | §9.D3, §12 |
| Q3 | Does interior D0 grading wait for, or share, the door-crossing labelling run? | **Door first.** Operator: "Is Vision working as designed is the central question. Starting with the door crossing version." Door-crossing labelling runs first; interior D0(b)/(c)/(g) grading starts once the door evaluation set is done, using the same grading tool (private labelling Artifact) and the same weekly budget, door rows always ahead of interior rows. D1 and the D5 no-model leg (no grading needed) build meanwhile | Share the run from the start, interleaved | §8c, §9.D0, §9.D7 |

## 2. What we know about count error today (honest)

NVR interior body counts have NEVER been measured against ground truth. The only truth on record is at doors: the operator
hand-labelled 30 door frames, and the Frigate person-tracking proxy agreed on 22 of 30 (73 %): 5 misses (one a 2-person
frame), 3 false positives (card VISION-CROSSING-ANALYSIS-1, `HANDLABEL_2026-11-13`). Camera-versus-BLE agreement is not an
error measure: BLE knows only residents, so both can agree while both miss a guest. D0 grades interior frames.

## 3. The product

Interior cameras sit only in shared spaces. The census reads them through `PersonCensus.interior_camera_entities()`
(`camera_census.py:2706`, person sensors, not `camera.*`). The 2026-11-14 read of that list resolved to 7 physical cameras
(playroom, master_hallway, staircase, foyer_fisheye, family_room, upstairs_hall, stairs_top, each with a Frigate and a
Protect leg); D0(a) re-reads it through the registry before any build. No bedroom or bathroom has a camera, and the plan
refuses one if it appears (INV-IV-SCOPE).

1. **Room record (F4, unnamed)** per covered room: bodies, who is named there, how many are unnamed, a status, provenance.
   Display: "2 people in the family room, 1 unnamed".
2. **Vision supplements the count sensors**: a sampling budget over the shared spaces, dense near entries and sparse in
   steady state, sized by each camera's measured error.
3. **Describe what is happening, on demand**: activity and context for a room or a person, structured, for personalization
   and when the operator asks. Affect (mood, energy) is recorded per person in each description, ON by default, observational, for future
   personalization and richer descriptions; no consumer reads it yet.
4. **Path time-lapse after a door entry**: where an entrant or a group went inside.
5. **Census term**: interior unnamed bodies enter `deconflict_house` as one house scalar, awareness view only.

Never: a name from vision; a trust reader of any output; a frame from a bedroom or bathroom.

## 4. F1-F5 and consumer classes

| Fact | Role in this plan | Through |
|---|---|---|
| F1 | consumed (per-room BLE residents, part of `named`) | `PersonTrackingCoordinator.persons_in_room(room, active_only=True)` (contract §2.4a, G6) |
| F2 | input only, awareness view (D4) | pulled term provider at `_compute_awareness`; the census stays the one writer |
| F3 | consumed (D5 trigger, entrant count) | `PresenceCoordinator.get_crossings_since`, `get_crossing`, `get_last_arrival_record` (pull, no listener) |
| F4 | PRODUCED, unnamed: room records, vision counts, descriptions, path records | `PersonSightingProducer._emit_unnamed` (contract §2.4); named interior face sightings read, not re-made |
| F5 | none | |

| Output | Readers (pinned in the guard, §6.3) | Class |
|---|---|---|
| Room records, path records | `sensor.ura_interior_awareness` (display); PERSON-PROFILE-PREFERENCES-1 (reserved, suggestion = display) | display |
| Description | the NM reply to the requester (D3); personalization (reserved) | notification for the reply (names only the person asked about, at ≥ `min_confidence("notification")`); display otherwise |
| Interior house term | `PersonCensus._interior_tick` only | F2 input, awareness view; `CROSSING_VISION_CONSUMER_CLASSES` = {display} today (`const.py:6676`) |
| Trip-wires, grading requests | NM | operator |

No reader in house_state, security, access, comfort (HVAC, fans, room occupancy) or presence inference. Promotion only by
the census plan §3.2 ladder.

## 5. Institutional context verified (REUSE / NEW, re-grepped 2026-11-15 on 5d8b831d)

Greps run (`git grep -nE ... 5d8b831d -- custom_components quality`, plus `docs/` for the NEW names): every symbol in the
table; the NEW-name pattern `InteriorVision|interior_vision|RoomSighting|_emit_unnamed|get_room_sightings|
get_room_description|request_room_description|get_last_path_record|ura_interior|INTERIOR_VISION|INTERIOR_ROOM_|
INTERIOR_DESCRIBE|area_evidence|interior_census_tick|inward_path_edges|PathRecord` = 0 hits in code and tests; docs hits are
only this plan, its reviews, the contract (§2.4 / §7 name `_emit_unnamed` as the planned ingest) and the leaks audit.
`INTERIOR_PATH_*` is TAKEN by the path-map constants (`const.py:3478-3497`), so this plan's time-lapse knobs are
`INTERIOR_TIMELAPSE_*`. There is no `options_flow.py`; options live in `config_flow.py`.

| Piece | Verdict | Where |
|---|---|---|
| F4 producer, store owner, emit pattern | REUSE `PersonSightingProducer` (`person_sighting.py:102`), its `_emit` (`:569`) as the pattern; NEW `_emit_unnamed` on the same class (contract §2.4) | `person_sighting.py` |
| Area to room | REUSE producer `_room_for_area` (`person_sighting.py:272`, reads presence `_room_area_ids` from room config entries, `presence.py:1785, 3396`) | |
| Per-member NVR bodies | NEW public `PersonCensus.area_evidence()` (copies, no arithmetic change) returning `{"by_entity": {eid: last_reading}}` from `_stream_last_reading` plus `_last_area_contributions` (`camera_census.py:1410`, written `:2140-2172`) and `_last_house_camera_bodies` for display only. The per-area contributions are NOT the record source: they are per AREA, merge held readings (`_held_value`), skip watchdog-discounted cameras and write a binary-only area as `{"max_count": n, "platform": "binary"}` (closure N3) | `camera_census.py` |
| Interior camera list | REUSE `PersonCensus.interior_camera_entities()` (`camera_census.py:2706`, ship 3b, on guard READ_LIST CENSUS) | |
| Camera device, members, own camera, twin group | REUSE `camera_device_for_entity` (`camera_stream_health.py:731`), `device_camera_members` (`:719`), `own_camera_entity_for_device` (`:744`), `twin_pair_for_device` (`:865`) | ship 3b §6.1 |
| Still-source member of a group | REUSE `frigate_member` (`camera_stream_health.py:880`, ship 3b) plus `own_camera_entity_for_device` (`:744`); §8's rule is that pair, not a second implementation | ship 3b |
| Per-member platform reading | REUSE census `_stream_last_reading` (`camera_census.py:1516`, written `:2804`, read `:2825`), copied per entity by `area_evidence()` (§7) | |
| Per-member liveness | REUSE `camera_stream_health.entity_stream_view(hass, eid, census=True)` (`:1201`); "every NVR lost it" REUSE `camera_twin_health.physical_camera_dead` (`camera_twin_health.py:1165`) | ship 3b §6.5 (this plan adds a display reader, §14) |
| Physical camera key | REUSE `camera_resolver.canonical_camera_key` (`camera_resolver.py:507`, min device id of a fusion's source set); interior key = min device id of the 3b twin group (equality checked in D0(a), §7) | |
| BLE residents in a room | REUSE contract G6 `PersonTrackingCoordinator.persons_in_room(room, *, active_only)` (on guard READ_LIST PC already; NOT built: card G6-ONE-BLE-ROOM-READ-1, planned). Its filter REUSES `_ble_corroboration.phone_trustworthy` (`_ble_corroboration.py:34`) / `trustworthy_persons_in_room` (`:69`) over `get_persons_in_room` (`person_coordinator.py:2498`). Seam in §14 | |
| Named interior faces | REUSE `get_last_person_sightings()` (`presence.py:6038`), records with `sighting_source` interior, `room`, `census_would_veto` | |
| Crossings | REUSE `get_crossings_since` (`presence.py:6142`, tracker `transit_validator.py:1197`), `get_crossing` (`presence.py:6151`), `get_last_arrival_record` (`presence.py:6228`) | contract §4.1 F3 |
| Path map | REUSE `interior_paths.PathMap` / `PathEdge(from_key, to_key, kind, window_s, ...)` (`interior_paths.py`), loaded on the tracker (`transit_validator.py:1135`); NEW public `EgressDirectionTracker.inward_path_edges(door)` (non-person, beside `path_map_status` `:2836`) | |
| Census term pull | EXTEND `deconflict_house` (`census_deconflict.py:90-131`) with NEW keywords `interior_term=None, interior_leads=False` (never `extra_guest_terms`, whose entries all feed `vis` at `:105` and so `aware` at `:117`); REUSE the `_ledger_tick` pull shape (`camera_census.py` `_ledger_tick` / `_compute_awareness`, call site `:6940`); NEW `PersonCensus._interior_tick()` | |
| Leads flag | REUSE `CROSSING_VISION_AWARENESS_VISION_LEADS` (`const.py:6720`) for the ledger; NEW `INTERIOR_VISION_TERM_LEADS` + `interior_leads` argument per Q1 default (§1a; 0 hits for the name) | |
| Describe authorization | REUSE the operator resolution of `_is_authorized_to_ack` (`notification_manager.py:3447`: `CONF_NM_SECURITY_ACK_PERSONS`, else first `CONF_NM_PERSONS`); NEW `select.ura_interior_describe_access` (Q2) | |
| Model calls | REUSE `perimeter_enrichment.analyze_crossing_frames` (`perimeter_enrichment.py:360`, llmvision `video_analyzer`, clip route) and P2-D8's `analyze_crossing_images` (llmvision `image_analyzer` with `image_entities`; on `feature/crossing-vision-fast-stage` 921c9c47, not on develop; seam §14) | |
| Provider, model, kill | REUSE `CROSSING_VISION_PROVIDER_ID` (`const.py:3587`), `CROSSING_VISION_MODEL` (`:3575`), `LLMVISION_ENRICHMENT_KILL` (`:2509`) | |
| Frigate clip events | REUSE `frigate_ingress.register_frigate_consumer` (`frigate_ingress.py:582`) | |
| Rows | REUSE `Database.log_memory_episode` (`database.py:10686`; a direct insert, not the batched write queue; bounded by the daily call cap); types join `MEMORY_EPISODE_TYPES` (`const.py:6336`) and `MEMORY_WRITER_BACKED_EPISODE_TYPES` (`:6399`) | |
| NM inbound and replies | REUSE `_process_inbound_reply` (`notification_manager.py:4055`), `_send_reply` (`:4725`), `RESPONSE_COMMANDS` (`:244`); Companion actions `_handle_companion_action` (`:3781`) | |
| Trip-wires | REUSE `_stuck_signal_nm.fire_stuck_signal` (`_stuck_signal_nm.py:173`) | |
| Diagnostics | REUSE `PresenceCoordinator.get_layer_diagnostics()` (`presence.py:6193`, config-entry download) | |
| Consumer classes | REUSE `CONSUMER_CLASS_MIN_CONFIDENCE` (`const.py:6660`), `CROSSING_VISION_CONSUMER_CLASSES` (`:6676`), `min_confidence` | |
| Room types | REUSE `CONF_ROOM_TYPE` (`const.py:457`), `ROOM_TYPE_BEDROOM` / `_BATHROOM` (`:583, :585`) | |
| Switch pattern | REUSE `CrossingVisionCensusAuthoritySwitch` (`switch.py:1103`, RestoreEntity, stored value wins) | |
| AWAY golden harness | REUSE `quality/tests/test_census_trust_golden.py` (`::test_away_tick_identical_with_vision_payload` `:70`, `::test_census_existing_fields_golden_all_classes` `:86`), fixture `fixtures/away_latency_golden_develop.json`, harness `_census_vision_harness.py` | also on develop |
| Layer guard | EXTEND `quality/tests/_layer_guard_engine.py` (MEMBER_CLASSES, READ_LIST, STORE_ATTRS_OWNER, RECORD_OWNERS, R2_STORE_OWNERS) and `person_awareness_layer_allowlist_PROVISIONAL.py` (`LAYER_ALLOWLIST_TOTAL = 259`, LISTED) | §6.3 |
| Reserved `CROSSING_VISION_INTERIOR_ENABLED` | 0 code hits; doc-only name, superseded by `switch.ura_interior_vision` | |
| `RoomSighting`, `RoomDescription`, `PathRecord`, `interior_vision.py`, `InteriorVisionSampler`, `sensor.ura_interior_awareness`, `switch.ura_interior_vision`, the `INTERIOR_*` knobs in §12 | NEW (0 hits, greps above) | |

Prior plans consulted: census deconfliction (§3.2 ladder, §3.3 function and dedup rules), crossing vision (P2-D8, P2-D10,
B-stage chains), person sighting layer (§2A, §15.7-§15.9), read API, camera input stream health, NVR witness, ship 3 (§5
D7 guard, §6 ship 3b). Memory bodies: identity model F1-F5, no shadow mode, registry not names, dead sensor is faulty
equipment, measure before build, fire check and forward trace. Config-first: no knob or setting produces interior counts or
descriptions today; nothing to turn.

## 6. Layer conformance (contract §6)

### 6.1 Host modules

- `person_sighting.py`, `PersonSightingProducer` (member): the ONE ingest `_emit_unnamed(kind, payload)` and the owner of
  three new stores: `_room_sightings` (room records), `_room_descriptions`, `_path_records`, plus the vision-count cache
  `_vision_counts` behind the records. It builds records on its OWN interval timer (§9.D1), never on a presence path.
- `interior_vision.py` (NEW): an HA-free core (record arithmetic, house term, sampling weights, Wilson bounds, schema
  parsing, name scrub) and `InteriorVisionSampler`, constructed and owned by the producer, a NEW layer member class. It
  schedules and makes model calls and hands every result to the producer through a callback; it owns no person-awareness
  store and sends no channel.
- `camera_census.py`: `area_evidence()` (public, member read) and `_interior_tick()` (the pull).
- `transit_validator.py`: `inward_path_edges(door)` (public, non-person).
- `presence.py`: read-API delegates only (§6.2). No change inside `_run_inference`, `_handle_census_update`,
  `_periodic_inference` or any house-state path.
- `sensor.py`: `sensor.ura_interior_awareness` (polled, display). `notification_manager.py`: the D3 command branch.

### 6.2 Conformance table

| # | Check | This plan |
|---|---|---|
| 1 | Facts | Produces F4 unnamed (room records, vision counts, descriptions, path records). Consumes F1 (BLE in room), F3 (crossings), F4 named (interior face sightings), evidence services (stream health, twin health, path map). Feeds F2-A as a term. |
| 2 | Ingest | F4 unnamed: `PersonSightingProducer._emit_unnamed` (contract §2.4 / §7). F2 term: pulled at the one call site `_compute_awareness` by `PersonCensus._interior_tick()` from `PresenceCoordinator.interior_census_tick()` → `PersonSightingProducer.interior_census_tick()`; nothing pushes a count into the census. New stores are owned by a member (producer): no direct write by anyone else. |
| 3 | Read | `persons_in_room` (PC read list), `get_last_person_sightings`, `get_crossings_since`, `get_crossing`, `get_last_arrival_record` (PRESENCE read list), `interior_camera_entities` (CENSUS read list), `area_evidence` (member-to-member), `entity_stream_view`, `physical_camera_dead` (evidence services), `inward_path_edges` (non-person). Classes: §4. No raw `person.*`, no store, no private of another member, no hass.data scan. The producer's state listener on interior Frigate / Protect person sensors is a layer-internal producer read in a member module (guard R3 (iv)), the same kind as its existing face-sensor listener. |
| 4 | Separation | F4 reaches F2 only inside `deconflict_house` (term provider). Nothing reaches access, security, house_state or comfort. |
| 5 | Delivery | No existing consumer's delivery changes. D4 changes what `aware_guests` shows only after admission AND `INTERIOR_VISION_TERM_LEADS` (Q1 default; truth table §9.D4), each an operator checkpoint, and only upward (lower-bound rule). The vision switch ON at ship is an operator decision (§1). |
| 6 | Guard delta | §6.3. Allowlist rows added: 0 (delta 0 to `LAYER_ALLOWLIST_TOTAL`, `_PROVISIONAL` and `len(A.ROWS)`, against develop at merge time). Listed listeners added: 0. Guard changes are written as deltas, never absolute totals (other ships move them, e.g. the music repair merge −3); the builder re-reads the current totals on develop when it merges. Only crossing-vision P3-D3 changes the totals (+1 R13 row, totals +1); a merge after it keeps that +1. |
| 7 | Seams | G6 (`persons_in_room`), P2-D8 (`analyze_crossing_images`), P2-D10 (grading branch), census §3.3 (interior term), NVR witness W2 (provenance; D4 flip), ship 3b (`physical_camera_dead` readers). Owners and rules in §14. |
| 8 | Clip path | §8: a frame-source interface with a still route and a clip route; D3 and D5 can take a clip. |

### 6.3 Guard changes (each in the build that first needs it)

| Guard structure | Change | Ship |
|---|---|---|
| `MEMBER_CLASSES` | add `"InteriorVisionSampler": "interior_vision.py"` (contract §2.7 member list) | 1 |
| `STORE_ATTRS_OWNER` | add `_room_sightings`, `_room_descriptions`, `_path_records`, `_vision_counts` → `person_sighting.py` | 1 (descriptions 2) |
| `RECORD_OWNERS` | add `RoomSighting`, `RoomDescription`, `PathRecord` → (`person_sighting.py`,) | 1 / 2 |
| `R2_STORE_OWNERS` / `R2_PRIVATE_STORES` | add the four stores, owner `person_sighting.py` | 1 |
| `READ_LIST["PRESENCE"]` | add `get_room_sightings`, `get_last_path_records` (ship 1), `get_room_description`, `request_room_description` (ship 2) | 1 / 2 |
| `READ_LIST["CENSUS"]` | none (`area_evidence` is read only by a member); contract §2.6 lists it | 1 |
| `LAYER_NON_PERSON_PUBLIC` | add `inward_path_edges` | 1 |
| NEW `PINNED_READERS` (not in the total, like `LISTED`) | every pin is a `(module, qualname)` pair; a call of a pinned method anywhere outside its pins is a hit. `get_room_sightings` / `get_last_path_records` → (`sensor.py`, `InteriorAwarenessSensor.*`) and their presence delegates (`presence.py`, `PresenceCoordinator.get_room_sightings` / `PresenceCoordinator.get_last_path_records`); `request_room_description` → (`notification_manager.py`, `NotificationManager._handle_describe_command`) and (`presence.py`, `PresenceCoordinator.request_room_description`); `get_room_description` → (`sensor.py`, `InteriorAwarenessSensor.*`), (`presence.py`, `PresenceCoordinator.get_room_description`) and the reserved personalization pin; `interior_census_tick` → (`camera_census.py`, `PersonCensus._interior_tick`) and (`presence.py`, `PresenceCoordinator.interior_census_tick`); reserved pin for PERSON-PROFILE-PREFERENCES-1. Without the delegate pins the delegates themselves trip the guard (closure L-6). Ship-1 fix-up (review B MEDIUM-2): `interior_tick`, `_emit_unnamed` and `PersonCensus.area_evidence` are pinned to (`person_sighting.py`, `PersonSightingProducer.*`). Stated static limits (not caught): a bound-method alias (`g = p.get_room_sightings; g()`) and a read of the display entity's state or attributes | 1 |
| NEW `FORBIDDEN_ATTR_READS` (closure N7) | an attribute read of `.affect` (or `["affect"]` on a description dict) in any module other than `person_sighting.py` and `interior_vision.py` is a hit; the check also flags `getattr(x, "affect")` with a literal name, and `dataclasses.asdict(...)` / `vars(...)` on a `RoomDescription` (spot-check L-a; same AST walk as R7). Accepted gap, stated: a dynamic `getattr` with a computed name is not caught; no module builds attribute names at runtime today, and the drill set covers the literal forms. The reply formatter that may include affect (Q2 `operator_affect`) lives in `interior_vision.py` | 2 |
| `LISTED` (R10) | none: no new channel listener; D5 pulls crossings | n/a |
| R6 / `CHANNEL_CONSTS` | none: `_emit_unnamed` sends nothing on `SIGNAL_PERSON_SIGHTING` (its listeners stay none, operator Q5) | n/a |
| `LAYER_ALLOWLIST_TOTAL` | delta 0 (re-read on develop at merge) | all |
| Drills | `test_guard_red_on_reverted_site[iv_trust_reader]` (a `get_room_sightings()` call injected into a copied `security.py`), `[iv_census_feed]` (an `interior_census_tick()` call injected into a copied presence inference function), `[iv_direct_store_write]` (a write with a NON-`self` receiver, `producer._room_sightings[...] = ...`, from `interior_vision.py`; the R7 check skips `self.` writes, `_layer_guard_engine.py:922-925`, so a `self._room_sightings` sibling store inside the sampler would stay GREEN and is not a valid drill; closure L-5), `[iv_unnamed_on_sighting_signal]` (an `async_dispatcher_send(SIGNAL_PERSON_SIGHTING, ...)` inside `_emit_unnamed`), and ship 2's `[iv_affect_reader]` (a `desc.affect` read injected into a copied `notification_manager.py` function) each go red | 1 / 2 |

## 7. Camera model (built on ship 3b; W2 not needed before the D4 flip)

- **Interior group.** For each entity in `interior_camera_entities()`: its device by `camera_device_for_entity`, the device's
  group by `twin_pair_for_device` (a Frigate device plus its admitted W1 sibling; one member for an unpaired device).
  `interior_camera_key(group)` = the minimum device id in the group. For a fusion whose source set is exactly that pair,
  this equals `canonical_camera_key` (both are min device id), and the path-map node keys use `canonical_camera_key`
  (`interior_paths.py` header). D0(a) asserts the three keys are equal for every interior camera on the live registry; a
  mismatch stops the build and goes to the orchestrator.
- **Room.** The group's area from the entity registry (entity area, else device area), then `_room_for_area`. A group with
  no room, or whose room's `CONF_ROOM_TYPE` is in `INTERIOR_VISION_EXCLUDED_ROOM_TYPES` (bedroom, bathroom), is dropped and
  counted (`groups_excluded_by_reason`).
- **Member liveness, per tick.** A member entity is LIVE when `entity_stream_view(hass, eid, census=True)` is None and its
  state is a real reading; HELD / RELEASED when the view says so; STUCK when the census watchdog discounts it this tick (`area_evidence()["discounted"]`; its count is saved before the discount, ship-1 fix-up, review D-M3), never LIVE; NO-READING when the view is None but the state is
  `unavailable` / `unknown` / missing. Ship 3b's device-level rule gives the Protect multi-channel devices a view (state of
  play §10 #41 was the gap).
- **Record rule (operator: "if even one nvr has the cam it doesn't count as dead"; "a dead camera is faulty equipment").**
  `bodies_nvr` = the max over LIVE members of that member's own last reading, `area_evidence()["by_entity"][eid]` (copied
  from the census's per-entity `_stream_last_reading`; a Frigate person-count sensor gives a count, a Protect binary gives
  0/1). The platform of a member comes from the entity registry, never from the reading's shape or the per-area
  `"platform"` tag (closure N3). The per-area `_last_area_contributions` is never read for a record. D0(a) also asserts
  one interior group per area on the live registry (7 distinct device areas on 2026-11-15); two groups in one area stop
  the build and go to the orchestrator. A held member's frozen reading is never used on the record, even though the census still counts
  it while held (census rule, unchanged). No LIVE member → status `missing`, `bodies` None, `liveness` = `lost` when
  `physical_camera_dead` is True, else `held` / `released` / `no_reading`. Never 0 from absence (INV-IV-MISSING).
- **W2.** Nothing in ships 1-4 needs NVR witness W2: liveness comes from ship 3b, twin dedup from the group max, and NVR
  agreement is not an input. W2 adds per-camera family agreement as record provenance (`nvr_agreement`, display) and is a
  gate on the D4 flip only (§9.D4). Proposed arc map edit in §14.

## 8. Frame source and privacy

- **Interface.** `FrameSource(kind, group_key, entities, video_file, event_id)` with `kind` ∈ {`still`, `clip`}; one call
  function `interior_vision.call_model(frame_source, prompt, structure)` routes `still` to `analyze_crossing_images(
  image_entities=...)` (llmvision `image_analyzer` fetches each entity's `entity_picture` through HA, no URL and no
  credentials in URA) and `clip` to `analyze_crossing_frames(video_file=...)` (llmvision `video_analyzer` on a Frigate
  event clip through HA's Frigate proxy). No deliverable calls llmvision any other way.
- **Which camera entity (registry rule, never a name or suffix).** For a group, the still source is the camera entity of the
  member device whose enabled camera entities all have registry platform `frigate` (Frigate devices carry exactly one
  enabled camera entity, 29 of 29 in ship 3b D0(f)). A group with no such device has no still source: it is counted
  (`no_still_source`) and D0(a) reports it with a recommended registry rule for the operator. Protect devices carry 2-4
  enabled channels and the registry marks no channel role (ship 3b §6.0, dual-lens finding), so this plan does not pick a
  Protect channel. The rule is REUSE: `frigate_member` (`camera_stream_health.py:880`) picks the member and
  `own_camera_entity_for_device` (`:744`) gives its camera entity; no second implementation.
- **The still source must be LIVE (closure N1, HIGH).** A still call (any deliverable: D2, D3, D5) is made only when the
  still-source member is LIVE by §7 at call time. Otherwise the call is skipped and counted with reason
  `still_source_not_live`, even when a LIVE Protect member carries the record. A dead Frigate leg's `entity_picture` is
  stale or frozen ("a dead camera is ... faulty equipment"), so it never produces a vision count; the record stays on the
  LIVE member's NVR reading. D3 replies "camera not available" with no call. Test `test_no_sample_from_non_live_still_source`
  (D2) and `test_describe_non_live_still_source_no_call` (D3).
- **One still per call (recorded decision, closure L-8).** Draft 2's 1-3 frames per call (`INTERIOR_VISION_MAX_FRAMES`)
  is dropped: the still route fetches one `entity_picture` per entity, so more frames means repeated fetches seconds
  apart, which the clip route does better. Multi-frame evidence is the clip route. D0(c) compares one still against the
  clip on the same moments; if the clip wins clearly, the clip knobs turn, not a frame count.
- **Clip route.** The Frigate event id for a group comes from `register_frigate_consumer` events on the group's Frigate
  camera. D3 uses a clip when `INTERIOR_DESCRIBE_USE_CLIP` is True and an event ended within
  `INTERIOR_CLIP_MAX_AGE_S`; D5 uses a clip per hop when `INTERIOR_TIMELAPSE_USE_CLIP` is True. Both default False until
  D0(c) compares still and clip accuracy on the same graded moments; a True value is a knob turn.
- **Privacy.** Every call sets `store_in_timeline` False, `use_memory` False (both forced inside the adapters) and
  `expose_images` False. Whether `expose_images` False writes nothing under `/media/llmvision/snapshots` is NOT verified:
  D0(f) lists the folder before and after its calls. If files appear, `call_model` deletes the files it caused after the
  call and counts them (`frames_deleted`). URA keeps no frame except grading frames (D7), held in
  `<config>/universal_room_automation/grading/interior/` until graded or `INTERIOR_GRADE_FRAME_MAX_AGE_S`, then deleted.
  D0 grading frames go to a private labelling Artifact (same route as the 30 door frames) and are deleted from its asset
  store after the grade.

## 8a. Producer and consumer checks, fire check, forward trace

| Value | Producer (arithmetic, dependency health) | Fire check (D0 measures) | Consumers (file, class) | Forward trace |
|---|---|---|---|---|
| `bodies_nvr` per group | census `area_evidence()` per platform, LIVE members only (§7). Health: NVR count error never measured (§2); Protect `binary_seen` is 0/1, so it undercounts groups | interior NVR on-time per group per day | room record (display) | record → sensor, personalization |
| `named` per room | `persons_in_room(room, active_only=True)` (BLE, phone-left-behind filter, ACTIVE only) ∪ fresh interior face sightings (`room` match, age ≤ `INTERIOR_ROOM_FACE_FRESH_S`, `census_would_veto` False), one union by canonical slug (`person_ids.slug_of`). Health: BLE fleet live (state of play §3); interior face sightings have their own zero-fire trip-wire (`face_sighting_zero`, manual §4.5a) | interior face sightings per day; BLE-placed residents in covered rooms per day | record | record → status |
| vision count per group | one model call on a LIVE still source (§8), schema `{people}`; valid only while `INTERIOR_VISION_TERM_MAX_AGE_S` has not passed AND the static-scene rule holds (§8b) | calls per day by trigger (D7 trip-wire) | record `bodies` | record → sensor; term |
| interior house term | §9.D4 formula | computed every interior tick into diagnostics, admitted or not | census `_compute_awareness` (awareness) | `aware_guests` → display sensors (`sensor.ura_census_guests_around`) and `view_for_class` readers in the legal set (display only today). No action today, by the ladder |
| description | one call, schema §9.D3, name scrub | requests per day | NM reply (notification), personalization (reserved) | reply text |
| path record | entry crossing + hop on-edges (+ vision) | entries per day on mapped doors; hop coverage | sensor attribute (display), personalization (reserved) | display |

Policy lives in the consumers: the producer computes counts and records for every reader; "never trust" is enforced at the
readers by the guard pins (§6.3), not by withholding values.

## 8b. Invariants (falsifiable; reviewer D breaks these)

**Static-scene rule (the one definition, used by §8a, D2, D4; closure N4).** A vision count for group g, taken at `t_call`,
expires at the first moment after `t_call` when ANY interior group's debounced `bodies_nvr` differs from its value at
`t_call`, or when `INTERIOR_VISION_TERM_MAX_AGE_S` passes, whichever is first. "Debounced": a group's `bodies_nvr` counts as
changed only when the new value has held for `INTERIOR_VISION_STATIC_DEBOUNCE_S` (rung 1, default 10 s; 0 = raw changes). A
Protect 0/1 flicker shorter than the debounce is not a change; a held, released or no-reading member is not a reading and
cannot cause a change (its group's `bodies_nvr` is the LIVE members' max or None; LIVE → None is a change). ANY, not "that
group's", because the walk-through case needs it (`test_walk_through_counts_once`). D0 measures the median and p25 time
between debounced interior changes across all groups (D0(i)); if the median is below `INTERIOR_VISION_SAMPLE_INTERVAL_S /
10` the vision correction lives too briefly to matter, and that is an operator question with the number (§15), not a
silent tune.

- **INV-IV-AWAY.** With every switch, cap and admission value, `_run_inference` call count, triggers and timing, and the AWAY
  inputs presence takes from the census equal develop. Choke points: no code is added to `_run_inference`,
  `_handle_census_update`, `_periodic_inference`, `_handle_geofence_change`, the census payload or the trust fields; the
  producer's interior work runs on its own timer and its own state listener (O(1) callback, no await); the census pull runs
  only when `INTERIOR_VISION_TERM_ADMITTED` is True and is sync, O(groups), never raises. Test: extend
  `test_census_trust_golden.py` VARIANTS with `interior_admitted_5_lead` (term 5, leads True) and `interior_records_on`
  (records and sampler running, caps > 0): `test_away_tick_identical_with_vision_payload` and
  `test_census_existing_fields_golden_all_classes` stay equal to the develop golden. The golden test's self-check `else`
  branch (`test_census_trust_golden.py:104-105`) asserts `aware == unidentified_count`, which `interior_admitted_5_lead`
  breaks by design; the variant gets its own branch, `elif variant == "interior_admitted_5_lead": assert aware ==
  [max(r["house"]["unidentified_count"], 5) for r in got]` (Q1 default: interior leads on its own argument and only raises,
  §9.D4). `interior_records_on` stays on the `else` branch (not admitted). Closure L-6.
- **INV-IV-NO-TRUST.** No module outside the §6.3 pins calls `get_room_sightings`, `get_last_path_records`,
  `get_room_description`, `request_room_description` or `interior_census_tick`, or constructs or writes a `RoomSighting`,
  `RoomDescription` or `PathRecord`. Enforced by the layer guard, drilled red (§6.3).
- **INV-IV-NO-NAME.** `named` comes only from `persons_in_room` and named interior face sightings. No vision output sets a
  slug, `person_id` or `identity_provenance`, and a description text never carries a tracked person's name or slug.
  Break it with a model response naming a resident.
- **INV-IV-DEDUP.** One body counts once: Frigate and Protect legs of one physical camera by max within the group; a vision
  count replaces, never adds to, the NVR count of its group; overlapping groups (`CONF_INTERIOR_CAMERA_OVERLAP_GROUPS`) by max
  of bodies with one union of named; one resident by slug across BLE and face, placed in exactly one room (§9.D4 (e)); a guest walking between groups is not
  carried by a stale vision correction (static-scene rule). Break it with the walk-through case in §9.D4.
- **INV-IV-MISSING.** A group with no LIVE member is `missing` (bodies None), never 0, on the record and in the term; all
  groups missing → term None (case D). No vision count is ever taken from a still-source member that is not LIVE (§8,
  closure N1). Break it with a held Frigate member and a LIVE Protect member reading 1.
- **INV-IV-OFF.** Switch off, `LLMVISION_ENRICHMENT_KILL` True, either daily cap 0, or the cost cap reached: zero model calls
  and zero frame fetches from this plan's code. D1 calls no model and has its own constant kill.
- **INV-IV-SCOPE.** Frames come only from interior groups (§7) or inward path-edge groups of the crossing's door, and never
  from a group whose room type is excluded.
- **INV-IV-NO-STORE.** After any call, no file caused by this plan remains under `/media/llmvision/snapshots`; grading frames
  exist only in the grading folder and none is older than `INTERIOR_GRADE_FRAME_MAX_AGE_S`.

## 8c. Ship order (operator: tight, not deferred; review G's minimum path)

1. **Ship 1:** D0 (read-only probe and grading) in parallel with D1 room records and the D5 no-model leg. No model in the
   runtime. Ship 3b must be on develop.
2. **Ship 2:** D3 describe on demand, switch ON, capped. Gate: the D0(g) 20-frame description pilot (one labelling run).
3. **Ship 3:** D2 sampling and correction, sized from D0(b)/(c).
4. **Ship 4:** D5 vision leg.
5. **Ship 5:** D4 census term: computed into diagnostics from ship 5 on, pulled into `deconflict_house` only after
   admission (closure L-8 wording); the flip is gated by a bar counted from D0 plus D7
   grades and sized by interval width (§9.D4), plus W2 for provenance.
D6 when its trigger fires. D7 ships with each producer. Labelling (Q3 default): the door-crossing evaluation set is
labelled first; interior D0 grading (and so the ship-2 gate and the D2 weights) starts when the door set is done, on the
same tool and weekly budget, door rows first. Ship 1 does not wait on labelling. Each ship updates the presence state of play and manual §4.5a in the
same commit. No gate parks a deliverable by itself: a failed D0 gate is an operator question with numbers and a
recommendation (charter rule 4).

## 9. Deliverables

### 9.D0 Interior count error probe (read-only plus a graded sample; ship 1)

(a) **Coverage, by registry:** each interior entity → device → twin group → `interior_camera_key`, `canonical_camera_key`
of the producer's resolved fusion, path-map node key (assert equal), area, URA room, room type, still source (§8), path-map
membership. (b) **Graded sample:** ≥ `INTERIOR_D0_FRAMES_PER_GROUP` (30) Frigate event snapshots per group, stratified by
moment: NVR and BLE agree, disagree, no resident placed, NVR 0, day / night, and known guest periods (house GUEST days on
record) to reach ≥ `INTERIOR_TERM_BAR_MIN_NONRESIDENT` (10) frames with a non-resident. Frigate only: fetching historical
Protect frames through HA is not verified (review B14); D0 records Frigate snapshot retention. Graded in a private labelling
Artifact with its database (route of `HANDLABEL_2026-11-13`). Truth = operator people count. Report per group: miss rate
(truth ≥ 1, NVR 0), false-positive rate (truth 0, NVR ≥ 1), multi-person undercount (truth ≥ 2, NVR < truth), exact rate,
Wilson 95 % intervals. (c) **Vision on the same frames** through `call_model` (still route; and the clip route on the
moments that have a clip): per-group vision error with intervals; measured cost per call (sets
`INTERIOR_VISION_EST_COST_PER_CALL`); 1 frame versus clip accuracy. (d) Census recorded attributes `area_raw_max_pre_cancel`
vs `ble_by_area`: agreement shares and disagreement durations (secondary). (e) Path map doors and inward edges; group entries
per day; hop coverage (share of entries reaching an inward camera; earlier measured 55-67 %). (f) Privacy: snapshot folder
before / after; call latency p50 / p90. (g) Description pilot: 20 frames, operator rates useful / wrong / empty. (h) Fire
checks of §8a table. (i) Static-scene lifetime (closure N4): from recorder history of the interior person sensors, the
median and p25 time between debounced (`INTERIOR_VISION_STATIC_DEBOUNCE_S`) `bodies_nvr` changes across ALL interior
groups, by hour of day; this is the expected life of a vision correction. Grading order (closure L-3): D0(b) is stratified
by moment as listed, so its pooled exact rate is not biased toward disagreements; D7's "disagreements first" queue IS
biased low (conservative for the lower-bound bars) and the scorer reports D0 and D7 rates separately, and pools them only
with per-stratum weights from D0's moment shares. Sequencing (Q3 default): D0(b)/(c)/(g) grading starts after the door
evaluation set is labelled; D0(a)/(d)/(e)/(f)/(h)/(i) are read-only and run at once.

- **Gates (each failure = an operator question with the numbers and a recommended answer, never an automatic park):**
  D0-P1 (D2 value): NVR exact Wilson LB ≥ `INTERIOR_D0_P1_NVR_EXACT_LB` (0.97) on every group AND vision not better on any
  group. D0-P2 (D5 vision leg): group entries < `INTERIOR_D0_P2_GROUP_ENTRIES_MIN` (1 / day) or hop coverage <
  `INTERIOR_D0_P2_HOP_COVERAGE_MIN` (0.50). D0-P3 (D3): useful < `INTERIOR_D0_P3_USEFUL_MIN` (12 of 20). D0(a) key mismatch
  or a group with no still source: orchestrator.
- **Verify:** `docs/planning/AUDIT_vision_interior_d0_<date>.md`, one table per item with intervals; Artifact asset store
  empty after grading. **Live:** none (read-only).

### 9.D1 Room records, no model (ship 1, Tier 2-DB)

`interior_vision.build_room_records(groups, evidence, liveness, named_by_room, vision, now)` (pure) builds one frozen
`RoomSighting(room, area_id, group_key, bodies, bodies_nvr, bodies_vision, bodies_source, named, named_sources, unnamed,
status, provenance, liveness, entered_via, census_as_of, as_of)` per covered room. `unnamed = max(0, bodies − |named|)`.
Status: `missing` (no LIVE member) > `unnamed_present` (unnamed ≥ 1) > `confirmed` (bodies ≥ 1, unnamed 0) >
`ble_unconfirmed` (bodies 0, a BLE-named resident) > `empty`. Provenance `nvr` / `vision` / `agree` (vision valid and equal).
The producer runs the build every `INTERIOR_ROOM_RECORD_INTERVAL_S` on its own `async_track_time_interval` (registered in
`async_setup`, removed in `async_teardown`) and writes through `_emit_unnamed("room", records)`. A state listener on the
groups' person sensors (same pattern as the face-sensor listener) stamps on-edges into a bounded ring for D2 / D5; its
callback is O(1). `get_room_sightings()` on presence returns the frozen tuple. `persons_in_room`: §14 seam.
`sensor.ura_interior_awareness` (the integration's Whole House device, where the census sensors sit; polled): state = total unnamed in covered rooms with a LIVE member;
attributes per room (status, bodies, unnamed, named count, provenance, liveness), all in `_unrecorded_attributes` (the raw
census inputs are already recorded on the census sensor).

- **Verify (discriminating):** family room bodies 2, BLE {ezinne} → `unnamed_present`, unnamed 1; BLE {ezinne, jaya} →
  `confirmed`; bodies 0, BLE {jaya} → `ble_unconfirmed`; the census guest count reads the same in all three (the record
  never moves it). Frigate member released, Protect member live reading 1 → bodies 1, not `missing` (one NVR has it). Both
  members held → `missing`, bodies None, not `empty`. A STALE resident placed in the room does not confirm (active_only).
  A bedroom-typed room with a camera → no record.
- **Tests:** `test_room_records_statuses`, `test_live_twin_carries_the_record`, `test_no_live_member_is_missing_not_empty`,
  `test_held_frozen_reading_not_used_on_record`, `test_named_union_dedups_ble_and_face`, `test_stale_resident_does_not_confirm`,
  `test_phone_left_behind_person_not_named`, `test_excluded_room_type_no_record`, `test_group_key_equals_canonical_key`,
  `test_record_build_off_inference_path` (the build is not reachable from `_run_inference` / `_handle_census_update`; drive
  a census update and assert no record build runs on that call stack), `test_kill_no_records`, INV-IV-AWAY golden variant
  `interior_records_on`, the §6.3 guard drills. Mutations: read census `_last_enhanced_area_contributions` (post-cancel)
  for bodies → statuses test red; drop the LIVE filter → held-frozen test red; drop `active_only` → stale test red.
- **Live:** within an hour `sensor.ura_interior_awareness` lists every covered room from D0(a); a BLE-placed resident on
  camera reads `confirmed`; census sensors unchanged (state and attributes); `get_layer_diagnostics()["interior_vision"]`
  shows record builds > 0.

### 9.D3 Describe what is happening, on demand (ship 2, Tier 2-DB)

`PresenceCoordinator.request_room_description(room, *, requester, reason)` and `describe_person(slug)` (room from
`get_person_location`, named in the reply only when the person's BLE confidence ≥ `min_confidence("notification")`; if BLE
cannot place them, the room of their newest named interior face sighting within `INTERIOR_ROOM_FACE_FRESH_S` (draft-2
fallback restored, closure L-8), reply worded "last seen in <room> <n> min ago"; else "can't place <person>").
**Who may ask (Q2 default):** the requester must pass `select.ura_interior_describe_access` (default `operator`, resolved
as in `_is_authorized_to_ack`); anyone else gets "Not available" with no call and a counted `describe_denied`. One call on the room's group (`call_model`, still by default, clip per §8), schema `{people,
activities: [{what, where_in_room}], context, confidence}` plus, only when `INTERIOR_DESCRIBE_AFFECT_ENABLED` is True,
`affect: [{mood, energy}]` per
person. Affect is a deliverable (operator 2026-11-15: "Emotion yes as prep for the future"): ON by default, recorded on the
description and its memory row, observational, no consumer yet; it exists for future personalization and descriptions, and
any future reader is display / suggestion class and needs its own plan. The prompt forbids names; the
parser scrubs any tracked display name or slug (`census.tracked_person_slugs()` + `person_ids.display_of`) to "a person" and
counts `description_name_scrubbed`. Result through `_emit_unnamed("description", ...)` into `_room_descriptions`; one
`interior_description` memory row (no frame). Triggers: (1) NM inbound text `describe <room>` / `describe <person>` on the
text channels: a branch in `_process_inbound_reply` after the echo rail and the messaging kill, before the
`RESPONSE_COMMANDS` lookup; `<room>` matches a URA room entry's `CONF_ROOM_NAME` case-insensitively (URA's own config);
requester = the channel's resolved NM person (None → no description); the method returns "" at once and the answer goes to
that person only through `_send_reply` when ready. The background call runs as a tracked task
(`hass.async_create_background_task`, held in the sampler's task set) and is cancelled in `async_teardown`, as D2's are
(closure L-8). The reply text is built by `interior_vision.format_description_reply(desc, include_affect)` with
`include_affect` True only when the Select is `operator_affect` and the requester is the operator; otherwise the reply
never contains affect (closure N7). NM `describe` has its own per-requester cooldown `INTERIOR_DESCRIBE_NM_COOLDOWN_S`
(closure L-4); (2) a personalization read through `get_room_description(room,
max_age_s)` (reserved pin), rate-limited per room by `INTERIOR_DESCRIBE_ROOM_COOLDOWN_S`. Every call counts against the
switch, the call cap and the cost cap. `INTERIOR_DESCRIBE_RESERVED_CALLS` of the daily call cap (and the same share of the
cost cap) are reserved for describe: D2 and D5 sampling skip with reason `reserved_for_describe` once `calls_today ≥ cap −
reserved` (closure N9).

- **Verify:** `describe family room` returns one structured description to the requester within D0(f) p90 +
  `INTERIOR_DESCRIBE_REPLY_SLACK_S`; a room without a camera replies "no camera there" with no call; switch off replies
  "Interior vision is off" with no call; cap reached replies "Interior vision limit reached today" with no call; a model
  text naming a resident is scrubbed; a non-operator requester gets "Not available" with no call under the default; with
  D2 having used `cap − reserved` calls, an operator `describe` still gets a description.
- **Tests:** `test_describe_schema_no_names`, `test_describe_scrubs_resident_names`, `test_describe_room_without_camera_no_call`,
  `test_describe_rate_limited`, `test_describe_counts_against_caps`, `test_describe_switch_off_no_call`,
  `test_describe_reply_to_requester_only`, `test_describe_affect_recorded_when_on`, `test_describe_affect_absent_when_off`,
  `test_describe_reply_excludes_affect` (affect ON and recorded; reply text for `operator`, `residents`, `any_resolved`
  contains no affect value; only `operator_affect` + operator requester includes it), `test_affect_has_no_reader` (the
  `FORBIDDEN_ATTR_READS` guard; drill `[iv_affect_reader]` red), `test_describe_access_default_operator_only`,
  `test_describe_nm_cooldown`, `test_describe_person_face_fallback`, `test_describe_non_live_still_source_no_call`,
  `test_describe_task_cancelled_on_teardown`, `test_sampling_leaves_describe_reserve` (D2 at cap − reserved skips; describe
  still calls), `test_describe_never_feeds_census` (drive descriptions with admission off and on; assert the
  `deconflict_house` arguments are unchanged).
- **Live:** one operator-requested description delivered; one `interior_description` row; `calls_today` ≤ cap.

### 9.D2 Sampling and correction budget (ship 3, Tier 2-DB)

Weight per group: `w = clamp(err_ub / INTERIOR_VISION_REF_ERR, INTERIOR_VISION_MIN_WEIGHT, 1)`, `err_ub` = Wilson 95 % upper
bound of (1 − vision exact) over the group's graded rows (D0 plus D7). With no rows `err_ub` = 1, so `w` = 1 (full rate)
until grades exist. Triggers, in priority order: (1) disagreement: a record in `unnamed_present` or `ble_unconfirmed` for
`INTERIOR_VISION_DISAGREE_PERSIST_S`; (2) near entry (operator "dynamic"): for `INTERIOR_VISION_ENTRY_WINDOW_S` after a door
entry crossing (pulled each interior tick) on the door's inward-edge groups, or after a group's `bodies_nvr` rises, one
sample per `INTERIOR_VISION_ENTRY_SAMPLE_S`, at most `INTERIOR_VISION_ENTRY_MAX_SAMPLES` per window; (3) an NVR count change
on a group with `w ≥ INTERIOR_VISION_CHANGE_WEIGHT_MIN`; (4) steady state: while `bodies_nvr ≥ 1` or BLE places someone in
the room, at most once per `INTERIOR_VISION_SAMPLE_INTERVAL_S / w`. Per-group cooldown, daily call cap, daily estimated cost
cap (`calls × INTERIOR_VISION_EST_COST_PER_CALL`; llmvision returns no usage); every skip counted by reason. Call: still
route, schema `{people}`, prompt forbids names. Each call writes one `log_memory_episode(episode_type="interior_vision",
node_id=f"ivision:{group_key}:{ts}", source_ref=group_key, dedup_source_ref=False, window_dedup=False)` (direct insert,
bounded by the call cap) with room, `bodies_nvr`, named count, vision people, trigger, outcome, latency, model,
`pipeline_version`. Results go to the producer (`_vision_counts`) and from there into the next record build.

- **Verify (discriminating):** ghost (NVR 1, truth 0, vision 0) → record `empty`, provenance `vision`, census unchanged;
  merged group (NVR 1, vision 3) → unnamed 3 on the record only; any interior group's debounced NVR changes (static-scene
  rule, §8b) → the record reverts to NVR at once, while a sub-debounce Protect flicker does not expire it; Frigate member
  held and Protect member LIVE reading 1 → no call, skip `still_source_not_live`, record stays NVR 1; weights: n = 100 at 99 % exact → `err_ub` 0.054, `w` 0.27, steady interval about 13 200 s; n = 100
  at 80 % → `w` 1, 3 600 s; no grades → `w` 1.
- **Tests:** `test_disagreement_needs_persistence`, `test_entry_window_dense_then_sparse`, `test_weight_from_wilson_upper_bound`
  (the three numeric cases above), `test_cost_cap_and_call_cap_skip`, `test_switch_off_no_call`, `test_kill_no_call`,
  `test_blank_frames_not_zero`, `test_no_name_reaches_named`, `test_privacy_flags_set`, `test_static_scene_rule_expires_vision`
  (any group, debounced), `test_static_scene_flicker_below_debounce_keeps_vision`, `test_no_sample_from_non_live_still_source`
  (closure N1), `test_sampling_leaves_describe_reserve`, `test_teardown_cancels_calls`, `test_scope_interior_groups_only`.
  Mutations: drop the call-time switch re-read; drop the weight; drop the static-scene rule; drop the still-source LIVE
  check (→ `test_no_sample_from_non_live_still_source` red); drop the describe reserve.
- **Live:** ≥ 1 `interior_vision` row per trigger type that occurred within a day; calls ≤ cap; 0 new files under the
  snapshot folder.

### 9.D5 Path time-lapse after an entry (no-model leg ship 1, vision leg ship 4, Tier 2-DB)

Each interior tick pulls `get_crossings_since(last_seen)`; an entry on a door with inward edges
(`EgressDirectionTracker.inward_path_edges(door)`, `PathEdge.window_s` = measured `lag_p90_s` or the map default) opens a
path window. **Windows are cumulative along the chain (closure N6).** The path map is a graph from the door
(live `interior_paths.json` for garage_a: garage_a → staircase 63 s → stairs_top 72 s → playroom 67 s / upstairs_hall
84 s; staircase → family_room 85 s). The window of a node v reached over edge (u → v) opens at `t_u` and closes at `t_u +
window_s(u → v)`, where `t_u` = u's first on-edge in its own window (for the door, `t_door` = E). If u was never seen, `t_u`
= the cumulative bound `E + Σ window_s` along the shortest chain to u, so the chain continues past a camera that missed
the entrant. Chains are followed to depth `INTERIOR_TIMELAPSE_MAX_HOPS`. On-edges (`off` -> `on` only) come from the
interior group members AND from every path-map node that has a person leg, resolved through the registry (node camera
entity -> resolver fusion -> its person binary sensors), interior group or not (ship-1 fix-up, review D-M1: the live
garage_a chain's first node `staircase_2` is a zone-only Frigate camera; a hop on such a node has room None). The
cumulative rule is unchanged: if the first node misses the entrant, a quick entrant at the next node before its window
opens is still lost (stated residual; opening a missed node's child at the parent's open was considered and not taken, it
widens every later window). The door of an entry is the door whose anchors (`DoorMap.anchors`) hold the entry camera's
key. No-model leg: the first on-edge of each reached
node inside its window (from the D1 on-edge ring) → `PathRecord(source_ref, door, ts, n, n_source, hops: (group_key,
room, first_on_ts, bodies_nvr_at_first_on, bodies_vision))`, closed at the cumulative max over reached nodes of their
window close + `INTERIOR_TIMELAPSE_CLOSE_PAD_S`, written through `_emit_unnamed("path",
...)` (ring `INTERIOR_TIMELAPSE_RING`). The hop rooms' records carry `entered_via` (door, crossing ts) for
`INTERIOR_TIMELAPSE_SEED_TTL_S` (display). `n`: the crossing's `vision_people_count` F3 attribute from `get_crossing(source_ref)`, written by crossing-vision
Phase 3 P3-D3 through G3 (not by the fast stage, which writes no G3 attribute; harmonization C3); until P3-D3 ships
that source is absent and `n_source` says so. Path windows merge by physical pass: windows whose crossings share a
non-None `pass_key` (the F3 creation-time field stamped by the tracker, crossing-vision P3-D9a, read from
`get_crossing`) open one `PathRecord`; before P3-D9a ships (`pass_key` None) windows of one door group within
`CROSSING_VISION_CLUSTER_S` merge instead (harmonization C4); test `test_d5_windows_merge_by_pass_key`; until then from `get_last_arrival_record()` when its `source_ref` matches; else the max
`bodies_nvr` on the first hop, i.e. of that hop's group over its window, from its first on-edge to its window close (`n_source` names which; ship-1 fix-up, review A M3). Never the crossing-vision row store (contract G8). Vision leg: when
`n ≥ INTERIOR_TIMELAPSE_VISION_MIN_N`, or a hop room's record shows unnamed ≥ 1 at its first on-edge (draft-2 "or
guests_unnamed ≥ 1" restored on the interior record, closure L-8), one still call per hop group at its first on-edge, at most
`INTERIOR_TIMELAPSE_MAX_CALLS` per crossing, inside the caps; the result fills `bodies_vision`. One `interior_path` row per
record. Coverage ceiling is stated (D0(e)), not tuned.

- **Tests:** `test_path_window_from_edge_window_s`, `test_path_windows_cumulative_on_live_chain` (the garage_a chain above:
  an entrant seen at staircase E+60, stairs_top E+130, playroom E+195 → three hops; the old per-hop `E + window_s` rule
  would drop playroom), `test_path_chain_continues_past_missed_camera`, `test_unnamed_hop_triggers_vision_leg`,
  `test_single_entrant_no_call`, `test_group_entry_calls_hops_capped`,
  `test_no_inward_edges_no_record`, `test_entered_via_ttl`, `test_n_source_order`, `test_no_egress_listener_added` (guard).
  Mutation: count approach edges as inward.
- **Live:** ship 1: ≥ 1 `interior_path` row WITH ≥ 1 hop after an entry on a mapped door (a hop-less row proves
  nothing; ship-1 fix-up, review D-M2); ship 4: ≥ 1 row with `bodies_vision` after a
  multi-person entry.

### 9.D4 Interior term in `deconflict_house` (ship 5, Tier 3)

**Formula.** Partition the groups by `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` (lists of camera device ids, rung 2; groups in no
listed set are singletons). For each partition `O`: `B_O` = max of `bodies` over its groups with a LIVE member (vision when
valid, else NVR); `N_O` = |union by slug of `named` over the rooms of `O`|; `U_O = max(0, B_O − N_O)`. The term:
`interior = Σ_O U_O` over partitions with at least one LIVE group; None when no partition has one (case D). Computed by
`interior_vision.interior_guest_term(...)` (pure), served by `PersonSightingProducer.interior_census_tick()` from the last
records, pulled by `PersonCensus._interior_tick()` inside `_compute_awareness` and passed as its own keyword `interior_term=term`, never inside
`extra_guest_terms` (spot-check M-1). `deconflict_house` combines it with the develop result by max only (rule 3, never a sum; the lower-bound rule
below), so the ledger and the interior term never add.

**One guest seen by several cameras counts once:** (a) the Frigate and Protect legs of one camera are one group, max;
(b) overlapping cameras are one partition, max of bodies with one union of named; (c) a vision count replaces its group's
NVR count; (d) moving between groups: the NVR legs are instantaneous readings, and a vision correction expires when any
interior group's NVR count changes (static-scene rule), so a walking guest is never carried in two groups by a stale
correction; (e) residents are subtracted once: before the per-room `named` union, each slug gets ONE placement, BLE ACTIVE
room if any, else the room of its newest fresh interior face sighting (closure N5). The same placement feeds D1's `named`
per room, so a slug never appears in two rooms' `named` in one build. Repro it closes: Ezinne BLE ACTIVE in the family
room, her face on the staircase 200 s ago, one guest on the staircase → staircase named {} , unnamed 1 (not 0). Residual (stated, same as
the census area sum today): during a hand-off both NVR legs can read on for a few seconds. D0 measures it; the term reads
the last record (`INTERIOR_ROOM_RECORD_INTERVAL_S` cadence).

**Admission and leads (Q1 default: interior leads on its own argument).** `INTERIOR_VISION_TERM_ADMITTED` (rung 1, False)
admits the term: False → `_interior_tick` is not called and awareness and trust are byte-identical to develop; True → the
term is pulled into `deconflict_house` as `interior_term` and only recorded in diagnostics. `INTERIOR_VISION_TERM_LEADS` (rung 1, False) is the
D4 flip, set when interior meets ITS OWN bar (below), and is passed as the new `interior_leads` argument. The ledger keeps
`CROSSING_VISION_AWARENESS_VISION_LEADS` (L). Signature change: `deconflict_house(..., extra_guest_terms=...,
interior_term=None, interior_leads=False)`; with the default, every existing caller and every existing test is unchanged.

**The interior term is a lower bound, never a whole-house estimate (closure N2).** It covers only the shared spaces with a
camera, so it may only RAISE awareness: `base` = what develop computes (`ledger` when L and the ledger term is present,
else `guest_cam`); `aware_guests = max(base, interior)` when admitted, interior leads and interior is not None; else
`base`. The interior term is excluded from develop's `vis = max(present terms)` (it never stands in for a missing ledger
term) and only enters through this max.

**Display fields (spot-check M-1).** `case`, `aware_agreement` and `count_provenance` stay byte-identical to develop in
every row, including when interior raises `aware_guests`: they are computed from `vis` (ledger and existing extra terms)
vs `guest_cam` exactly as today. Interior's own agreement (interior vs `guest_cam`, interior vs ledger) and an
`interior_raised` flag go to `get_layer_diagnostics()["interior_vision"]` only.

| Admitted | Ledger leads (L) | Interior leads | Ledger term | `aware_guests` | Interior effect |
|---|---|---|---|---|---|
| False | any | any | any | as develop | none |
| True | any | False | any | as develop | diagnostics only (display fields as develop) |
| True | False | True | any | `max(guest_cam, interior)` | raises awareness only |
| True | True | True | present | `max(ledger, interior)` | raises awareness only |
| True | True | True | None (unhealthy) | `max(guest_cam, interior)` | N2 repro: `guest_cam` 2, interior 0 → 2, as develop |
| True | any | True | any, interior None (case D) | as develop | none |

Alternative (if the operator overrides Q1): no `interior_leads`; interior moves awareness only when L is True, with the
same `max(base, interior)` lower-bound rule.

**Bar for the flip (counted from D0 plus D7 grades; no calendar floor).** Per group, the Wilson 95 % lower bound of vision
exact ≥ `INTERIOR_TERM_BAR_EXACT_LB` (0.85; about 57 of 60 graded rows clears it); pooled over resident-only graded rows,
the upper bound of the false-guest rate ≤ `INTERIOR_TERM_BAR_FALSE_GUEST_UB` (0.03; Wilson UB for 0 of n is z²/(n + z²),
0.0310 at n = 120, so 0 of ≥ 125 resident-only rows is needed; closure L-2); pooled over
graded NVR disagreements, the lower bound of "vision right" ≥ `INTERIOR_TERM_BAR_DISAGREE_LB` (0.70); ≥
`INTERIOR_TERM_BAR_MIN_NONRESIDENT` (10) graded rows with a non-resident present; NVR witness W2 live (record provenance).
D0 supplies ≥ 210 rows; `number.ura_interior_vision_grades_per_day` (default 20 while the bar is open) supplies the rest, so
the remainder to about 60 rows per group takes days, not weeks. The weekly scorer evaluates the bar at each labelling run and
pages the operator when it is met (Tier-3 checkpoint).

- **Tests:** `test_interior_term_formula` (two guests in two rooms → 2), `test_walk_through_counts_once` (vision 1 in family
  room with NVR 0, the guest then appears on the staircase NVR → term 1, not 2), `test_overlap_partition_max_with_union_named`,
  `test_term_none_when_all_missing`, `test_held_member_never_zero`, `test_admitted_false_no_pull`, `test_truth_table`
  (all six rows), `test_truth_table_row2_ledger_none` (admitted, interior leads False, L True, ledger None, `guest_cam` 2,
  interior 0 → 2), `test_display_fields_identical_when_interior_raises`, `test_interior_never_lowers_awareness` (the N2 repro: ledger None, `guest_cam` 2, interior 0 → 2),
  `test_one_placement_per_slug` (the N5 repro), `test_interior_leads_default_false_existing_callers_unchanged`,
  `test_false_guest_bar_needs_125` (0/120 fails, 0/125 passes), `test_trust_view_byte_identical_admitted_on`, golden
  variant `interior_admitted_5_lead` with its own self-check branch (§8b). Mutations: sum NVR and vision in a group; sum
  over overlap partitions; pass the term into `unidentified_count`; route interior through
  `extra_guest_terms` (→ row-2 test red); let interior replace `base` instead of max (→ N2 test
  red); drop the one-placement step (→ N5 test red).
- **Live:** with admission False (ship) the census sensors equal develop and diagnostics show the computed term; after the
  flip, `aware_guests` ≥ develop's value, `case` / `aware_agreement` / `count_provenance` and trust fields equal develop,
  and diagnostics carry interior's agreement.

### 9.D6 Local inference (Tier 2-DB; operator checkpoint to switch)

`INTERIOR_VISION_BACKEND` (`luna` / `local`, rung 2 options) where `local` is an llmvision provider entry (or an
OpenAI-compatible endpoint) served by a vision model on homelab hardware, never the Mac Ollama. Equivalence on the same
graded set (D0 plus D7, ≥ 200 rows): switch proposed when, per group, local exact LB is within
`INTERIOR_LOCAL_EXACT_MAX_DROP` (0.02) of Luna's point rate, the false-positive UB is not higher by more than
`INTERIOR_LOCAL_FP_MAX_RISE` (0.01), multi-person undercount not higher, and p90 latency ≤
`INTERIOR_VISION_LOCAL_LATENCY_P90_S`. Trigger to run the test: the D4 bar met, or every group's Luna exact LB ≥
`INTERIOR_TERM_BAR_EXACT_LB` (interval-based, no day count). After the switch the scorer pages if local's LB falls below the
bar on accumulated rows.
- **Tests:** `test_backend_switch_routes_calls`, `test_equivalence_report_per_group`. **Live:** equivalence audit file.

### 9.D7 Diagnostics, grading and trip-wires (with each producer)

Trip-wires (`fire_stuck_signal`): `interior_room_records_zero` (HIGH: interior `bodies_nvr` > 0 on ≥
`INTERIOR_ZERO_MIN_TICKS` ticks in 24 h and no record built); `interior_vision_zero_calls` (HIGH, the zero-fire check of the
vision producer: switch on, caps > 0, ≥ `INTERIOR_VISION_ZERO_MIN_TRIGGERS` triggers in 24 h, 0 calls);
`interior_path_zero` (LOW: ≥ `INTERIOR_TIMELAPSE_ZERO_MIN_ENTRIES` entries on mapped doors in 24 h, 0 path records);
`interior_vision_errors` (MEDIUM: error rate > `INTERIOR_VISION_ERROR_RATE_MAX`); `interior_frames_left` (HIGH: any file
INV-IV-NO-STORE finds; off when `INTERIOR_FRAMES_LEFT_CHECK_ENABLED` is False, closure L-4). Counters (`calls_today` by trigger, skips by reason, `cost_today_est`, latency p90, per-group `w`,
`err_ub`, exact rate, records built, groups by liveness, the computed term, `description_name_scrubbed`, `frames_deleted`)
go in `get_layer_diagnostics()["interior_vision"]`, not on entity attributes. Grading: up to
`number.ura_interior_vision_grades_per_day` rows a day (disagreements first; biased low, reported separately from D0, see
D0 grading order) are queued, behind the door-crossing rows in the same weekly run (Q3), with their frame for the weekly
labelling run; once P2-D10's Companion grading branch is on develop, interior rows use it with an interior discriminator in
the same `GRADE_URA_` handler (one handler). Weekly scorer: the crossing-vision scorer script, extended.

## 12. Knobs

| Knob | Default | Rung | Why / kill |
|---|---|---|---|
| `switch.ura_interior_vision` ("Interior Vision"), CM device; options-flow default `CONF_INTERIOR_VISION_ENABLED` | ON | 3 + 2 | Master for D2 / D3 / D5 vision; off = no calls. Stored switch state wins (pattern `switch.py:1103`) |
| `number.ura_interior_vision_daily_calls` | 60 (D0 resizes) | 3 | Separate from the door cap; 0 = no calls |
| `number.ura_interior_vision_daily_cost_usd` | 0.50 | 3 | Estimated spend cap; 0 = no calls |
| `number.ura_interior_vision_grades_per_day` | 20 | 3 | Grading volume; operator lowers once the D4 bar is met; 0 = none |
| `INTERIOR_ROOM_RECORDS_ENABLED` | True | 1 | D1 kill; False = no records, no term |
| `INTERIOR_ROOM_RECORD_INTERVAL_S` | 10 | 1 | Record cadence |
| `INTERIOR_ROOM_FACE_FRESH_S` | 300 | 1 | Named-face freshness |
| `INTERIOR_VISION_EXCLUDED_ROOM_TYPES` | {bedroom, bathroom} | 1 | Privacy scope; review to change |
| `INTERIOR_VISION_EST_COST_PER_CALL` | 0.0003 (D0(c) sets) | 1 | Cost estimate |
| `INTERIOR_VISION_REF_ERR` / `_MIN_WEIGHT` / `_CHANGE_WEIGHT_MIN` | 0.20 / 0.10 / 0.25 | 1 | Weight shape |
| `INTERIOR_VISION_SAMPLE_INTERVAL_S` | 3600 | 1 | Steady-state rate at w = 1 |
| `INTERIOR_VISION_ENTRY_WINDOW_S` / `_ENTRY_SAMPLE_S` / `_ENTRY_MAX_SAMPLES` | 180 / 45 / 3 | 1 | Dense near entries; MAX 0 = off |
| `INTERIOR_VISION_DISAGREE_PERSIST_S` | 120 | 1 | Ignores walk-through blips |
| `INTERIOR_VISION_CAMERA_COOLDOWN_S` | 120 | 1 | Calls per group bound |
| `INTERIOR_VISION_TERM_MAX_AGE_S` | 600 | 1 | Vision validity cap (also the static-scene rule) |
| `INTERIOR_VISION_TERM_ADMITTED` | False | 1 | D4 admission (term pulled, display effects); reviewed const edit |
| `INTERIOR_VISION_TERM_LEADS` | False | 1 | D4 flip (Q1 default: interior's own leads argument); set when interior's own bar is met; Tier-3 checkpoint; False = interior never moves `aware_guests` |
| `INTERIOR_VISION_STATIC_DEBOUNCE_S` | 10 | 1 | Static-scene rule debounce (§8b); 0 = raw changes |
| `INTERIOR_DESCRIBE_RESERVED_CALLS` | 10 | 1 | Daily calls (and cost share) kept for describe; sampling skips above `cap − reserved`; 0 = no reserve |
| `select.ura_interior_describe_access` | `operator` | 3 | Q2: who may ask (`operator` / `operator_affect` / `residents` / `any_resolved`); affect in the reply only for `operator_affect` |
| `INTERIOR_DESCRIBE_NM_COOLDOWN_S` | 60 | 1 | Per-requester NM describe cooldown; 0 = none (the call caps still bound it) |
| `INTERIOR_TIMELAPSE_MAX_HOPS` | 4 | 1 | Chain depth for cumulative path windows (D5); 1 = first hop only |
| `INTERIOR_FRAMES_LEFT_CHECK_ENABLED` | True | 1 | `interior_frames_left` trip-wire; False = off |
| `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` | [] (operator sets the measured pair) | 2 | Overlap partitions by camera device; built by D4 (census §3.3 rule 2) |
| `INTERIOR_DESCRIBE_ROOM_COOLDOWN_S` | 300 | 1 | Personalization reads |
| `INTERIOR_DESCRIBE_REPLY_SLACK_S` | 5 | 1 | Reply acceptance window |
| `INTERIOR_DESCRIBE_AFFECT_ENABLED` | True | 1 | Affect field (observational, no consumer); False = not requested or stored |
| `INTERIOR_DESCRIBE_USE_CLIP` / `INTERIOR_TIMELAPSE_USE_CLIP` | False / False | 1 | Clip route; True after D0(c) |
| `INTERIOR_CLIP_MAX_AGE_S` | 120 | 1 | Clip freshness |
| `INTERIOR_TIMELAPSE_CLOSE_PAD_S` / `_RING` / `_SEED_TTL_S` | 15 / 20 / 600 | 1 | Path leg |
| `INTERIOR_TIMELAPSE_VISION_MIN_N` / `_MAX_CALLS` | 2 / 3 | 1 | Vision leg; MIN_N 99 = off |
| `INTERIOR_GRADE_FRAME_MAX_AGE_S` | 691200 (8 d) | 1 | Grading frame retention |
| `INTERIOR_TERM_BAR_EXACT_LB` / `_FALSE_GUEST_UB` / `_DISAGREE_LB` / `_MIN_NONRESIDENT` | 0.85 / 0.03 / 0.70 / 10 | 1 | D4 bar (scorer) |
| `INTERIOR_D0_FRAMES_PER_GROUP` | 30 | 1 (probe script) | D0 sample |
| `INTERIOR_D0_P1_NVR_EXACT_LB` / `_P2_GROUP_ENTRIES_MIN` / `_P2_HOP_COVERAGE_MIN` / `_P3_USEFUL_MIN` | 0.97 / 1 per day / 0.50 / 12 of 20 | 1 (probe script) | Gates that produce operator questions |
| `INTERIOR_VISION_BACKEND` | `luna` | 2 | `local` after the D6 checkpoint |
| `INTERIOR_VISION_LOCAL_LATENCY_P90_S` / `INTERIOR_LOCAL_EXACT_MAX_DROP` / `_FP_MAX_RISE` | 10 / 0.02 / 0.01 | 1 | D6 acceptance |
| `INTERIOR_ZERO_MIN_TICKS` / `INTERIOR_VISION_ZERO_MIN_TRIGGERS` / `INTERIOR_TIMELAPSE_ZERO_MIN_ENTRIES` / `INTERIOR_VISION_ERROR_RATE_MAX` | 20 / 5 / 3 / 0.25 | 1 | Trip-wires; 0 (or > 1 for the rate) = off |
| `INTERIOR_LEDGER_FLOOR_ENABLED` / `_SUSTAIN_S` / `_RECORD_FRESH_S` / `_INPUT_ZERO_H` / `_LIFT_STORM_PER_DAY` | True / 60 / 30 / 24 / 6 | 1 | Ledger floor, §1b.7 |
| `INTERIOR_D0_FLOOR_PHANTOM_MAX_PER_WEEK` / `_OVERLAP_MAX` / `_FIRE_MIN_PER_WEEK` | 1 / 0.2 / 1 | 1 (probe script) | Floor D0 gates, §1b.6 |

## 13. Non-goals

- No identity from vision: no slug, `person_id`, face match or `identity_provenance` from any model output.
- No trust reader: house_state, security, access, comfort (room occupancy, HVAC, fans, music, lights), presence inference.
- No change to the trust view (F2-T), its fields or its payload; no change to AWAY triggers or timing.
- No new camera-liveness model and no per-NVR deadness: liveness is ship 3b's; W2 adds agreement later.
- No frames from bedrooms or bathrooms; no frame kept beyond grading.
- No `deconflict_house` change beyond the one `interior_leads` argument of the Q1 default (none at all if the operator
  takes the alternative). No change to the ledger's leads flag.
- **Periodic fixed-interval head count (draft 2 §10, sighting plan §15.8; closure E1). Decision: non-goal, with a revival
  trigger.** D2's steady-state trigger (4) already samples every occupied covered room at least once per
  `INTERIOR_VISION_SAMPLE_INTERVAL_S / w`, which is the useful part of a head count; a fixed whole-house sweep of empty
  rooms adds calls and no guest signal. Revival: the crossing ledger's bar (a) fails twice, or D0(i) shows vision
  corrections expire too fast to cover occupied rooms. Carded on the board (§14) with that trigger.
- Security use of interior vision: census ladder rung 5, plus D2 call latency p90 ≤ 15 s (draft-2 trigger restored, closure
  L-8; measured by D0(f) and D7).
- Multi-frame still calls (draft 2's 1-3 frames, `INTERIOR_VISION_MAX_FRAMES`): replaced by one still or the clip route
  (§8, closure L-8).
- No new push channel; no new listener on `ura_person_egress_event`, `SIGNAL_EGRESS_RECORD_AMENDED` or
  `SIGNAL_CENSUS_UPDATED`.
- No migration of existing BLE-in-room readers (that is G6).
- Naming people who are not enrolled (operator 2026-11-15: "Not expecting new names. Names come from people I enrolled.
  This is few and far between. Non goal"). Interior vision never tries to name, cluster or enroll an unknown person; named
  people come only from enrolled faces and BLE residents.
- Any consumer of affect (it is recorded only), except the operator's own describe reply when the operator sets
  `operator_affect` (Q2).

## 14. Edits other plans need (not made here) and seams

- **Arc map (proposed, for the orchestrator to apply):** step 9a "after layer ship 3b; before VISION-INTERIOR-SIGHTINGS-1
  (step 9 reads cameras)" becomes "after layer ship 3b; before the D4 flip of VISION-INTERIOR-SIGHTINGS-1 (ships 1-4 read
  cameras through ship 3b)". Card row → this doc; path chains merged here; D6 local inference added to the arc.
- **Contract:** §2.4 store gains the three unnamed stores (owner `person_sighting.py`), `_emit_unnamed(kind, payload)` sends
  no channel; §2.2 term providers: crossing vision and the sighting producer (`interior_census_tick`); §2.6 adds
  `PersonCensus.area_evidence()` (members only) and the two ship-3b reads used here; §2.7 adds `InteriorVisionSampler`; §4.1
  F4 row adds the four presence reads; guard `PINNED_READERS` (§6.3) described in §6 item 6.
- **Census deconfliction §3.3:** "Future terms" interior row = §9.D4 formula, admission, lower-bound rule, truth table;
  the bar lives here. Under the Q1 default, §3.3 (function signature, rule 3) gains `interior_leads` and the interior
  term's exclusion from `vis`, and §3.2 (ladder) gains an interior leads rung independent of the ledger's; Tier 3, ship 5.
  Census §3.6 gets the interior term's diagnostics line (draft-2 edit restored, closure L-8).
- **Sighting layer plan:** §15.8 (periodic head count) records the §13 non-goal and its revival trigger; §15.9.4 points
  its interior unnamed records at this plan's `_emit_unnamed` (draft-2 edits restored, closure L-8).
- **Crossing vision (ledger floor, §1b):** P2-D2 gains step 4b (the interior lift and its credit, after the resident
  lift) and `KIND_INTERIOR_LIFT`; P2-D3 diagnostics gain the floor fields and two trip-wires; §4 INV-P2-ONCE gains the
  interior credit clause. The checkpoint-anchor idea is recorded there as dropped.
- **Crossing vision:** B-stage chains → this plan D5; P2-D8 `analyze_crossing_images` is shared (whichever merges first owns
  it; the other rebases, same signature as 921c9c47); P2-D10 grading gains the interior discriminator.
- **G6-ONE-BLE-ROOM-READ-1:** owner of `persons_in_room`. If G6 has not merged when ship 1 builds, ship 1 adds
  `PersonTrackingCoordinator.persons_in_room(room, *, active_only=False)` exactly per contract §2.4a (phone filter inside,
  `phone_trustworthy` moved into `person_coordinator.py` with `_ble_corroboration` re-exporting it) and migrates no existing
  reader; G6 keeps the reader migration and its §2.4a probe. Contract §2.4a defines neither the return type nor
  `active_only`, so this plan pins both (closure L-7): returns a `tuple[str, ...]` of person names (the same names
  `get_persons_in_room` returns, `person_coordinator.py:2498`), and `active_only=True` keeps only persons whose
  `tracking_status == TRACKING_STATUS_ACTIVE` (`const.py:206`). The contract edit adds both lines.
- **Ship 3 plan §6.5 / state of play:** `physical_camera_dead` gains one display reader (the record `liveness` field).
- **NVR witness W2:** lists D1 records (provenance) and the D4 flip as readers.
- **State of play:** existing stale "NOT deployed" markers (read API ship 1, S1, person sightings, crossing-vision shadow,
  census-p2) are deployed; corrected in the ship-1 commit. Each ship adds its entry.
- **Manual §4.5a:** unnamed records beside named sightings (ship 1).
- **Board:** record the operator's affect and non-naming answers on the card (`operator_2026_11_15_*`); link P2-D8, P2-D10, G6.
  Card the periodic head count (§13) with its revival trigger; record Q1-Q3 as pending decisions with their defaults (§1a).

## 15. Revise when we learn

| Measurement | Changes |
|---|---|
| D0(a) keys and still sources | build go / orchestrator stop; registry rule for a group with no Frigate member |
| D0(b) NVR error per group | D2 weights, call cap, whether D0-P1 is asked |
| D0(c) vision error, still vs clip, cost | D2 value, D4 bar realism, `EST_COST_PER_CALL`, the clip knobs |
| D0(e) entries and hop coverage | D5 vision-leg question |
| D0(f) snapshot folder | whether the delete step runs |
| D0(g) description ratings | D3 schema, D0-P3 question |
| D0(i) median time between debounced interior count changes | whether vision corrections live long enough for D2 / D4 to matter; `INTERIOR_VISION_STATIC_DEBOUNCE_S`; an operator question if median < `SAMPLE_INTERVAL_S / 10`; head-count revival trigger |
| Operator answers to Q1-Q3 | Q1: D4 signature and truth table; Q2: describe access default; Q3: grading order |
| D7 grades over time | weights, the D4 bar, the D6 trigger |
| W2 agreement | record provenance; D4 flip gate |
| Local equivalence | D6 switch |

## 16. Tier, reviews, sequence

Plan: Tier 3; two plan reviews (completeness; build prediction) plus framing G, done 2026-11-15; this rewrite closes them
(§19) and the closure re-review's fixes are in §19; it needs an equivalence check by a reviewer before approval (arc rule 5). Ships 1-4 and D6: Tier 2-DB (A correctness
and edge cases; B async, lifecycle and write path; C test authority by per-site mutation, including the guard drills) plus
framing G. Ship 5 (D4): Tier 3 (A, B, C mutation, D completeness on INV-IV-AWAY and INV-IV-DEDUP including pre-existing
census readers; orchestrator re-grep and mutation; operator checkpoint before deploy; the flip itself is a second
checkpoint). Ship 1 can build as soon as ship 3b is on develop. The ledger floor (§1b, ship F): F-D0 probe first, then a Tier-3 build after ship 2 (§1b.9).

## 17. Drift check (ura-arc rule 7, at this rewrite)

| Operator said | Where it drifted | Correction | Status |
|---|---|---|---|
| "Make sure no plan precludes [clips]" | no clip path | §8 interface, clip route for D3 / D5 | fixed |
| "tight and not deferred"; no shadow mode | switch off at ship, "(shadow)" label | ON at ship, caps bound risk, renamed | fixed |
| "Foul. Why that long?" | D4 bar gated by grading throughput and a 7-day floor | interval-width bar counted from D0 + D7, no floor | fixed |
| "emotion is the deepest"; "Emotion yes as prep for the future" | emotion parked behind a long chain | affect field ON, recorded, no consumer | fixed |
| "if even one nvr has the cam it doesn't count as dead" | per-entity room getter | live member carries the record; `missing` only with no live member | fixed |
| One ingest per fact | sibling F4 store | `_emit_unnamed` on the one producer | fixed |
| AWAY fast | — | no code on inference paths; golden variants | zero drift |

## 18. Plan completion tracking

Filled at each ship: delivered, operator answers to any D0 gate question, deferrals with card
and reason, and the supersession check of the census per-area attributes once D1 reads them through `area_evidence()`.

## 19. Review finding closure

Reviews: completeness (C, H, M, L) and build prediction + goal fidelity (B, G), both 2026-11-15.

| Finding | Resolution | Plan section |
|---|---|---|
| C1 no conformance table; F4 producer contradicts contract | Table added; unnamed records, descriptions and paths through `PersonSightingProducer._emit_unnamed`, stores owned by the producer | §6.1, §6.2 |
| H1 D4 does not fit `deconflict_house` | Pulled house scalar on its own keyword `interior_term=` (never `extra_guest_terms`, spot-check M-1), formula stated; leads per Q1; truth table | §9.D4 |
| H2 guard / read-surface delta missing | Host modules named; every guard change listed; D5 pulls crossings, no listener; guard total delta 0 | §6.1, §6.3, §9.D5 |
| H3 room getter answers None for the foyer | `entity_stream_view` per member + `physical_camera_dead`; list from `interior_camera_entities()` | §7 |
| H4 BLE source returns counts | `persons_in_room(room, active_only=True)` with the phone filter; ACTIVE vs STALE split named; G6 seam | §8a table, §9.D1, §14 |
| H5 frame source and clip path | Frame-source section: Frigate-device registry rule, still route, clip route via `video_analyzer` | §8 |
| M1 AWAY anchor test missing; build placement | Placement: producer's own timer and listener, nothing on inference paths; golden variants added. Partly rejected: `test_away_tick_identical_with_vision_payload` exists at `quality/tests/test_census_trust_golden.py:70` on develop and 5d8b831d | §9.D1, §8b |
| M2 mixed dead-input semantics | Record uses LIVE members only; held frozen reading never on the record; term never reads a held group as 0 | §7, §8b |
| M3 stale cites | All cites re-grepped on 5d8b831d | §5 |
| M4 camera model seam with W2 | Interior key = min device id of the 3b group; equality with `canonical_camera_key` and path keys asserted in D0(a); W2 only for provenance and the D4 flip | §7, §14 |
| M5 numbers without knobs; switch label | Every gate, bar and D6 number named with a rung; Number entities named; switch renamed | §12 |
| M6 D3 and D5 read surfaces unnamed | D3: `_process_inbound_reply` branch, grammar, requester-only reply, notification class; D5 `n` read order | §9.D3, §9.D5 |
| M7 diagnostics on attributes | Counters in `get_layer_diagnostics()`; sensor attributes unrecorded | §9.D1, §9.D7 |
| L1 NO-TRUST is a list | Guard `PINNED_READERS` covers every module, drilled red | §6.3, §8b |
| L2 grading frames unowned | Grading folder, max age, deletion, trip-wire; Artifact assets deleted after D0 | §8, §8b |
| L3 state-of-play stale markers | Kept; corrected in the ship-1 commit | §14 |
| B1 sibling store | As C1 | §6 |
| B2 per-camera to house formula | Partition sum of `max(0, B_O − N_O)`, static-scene rule, walk-through test | §9.D4 |
| B3 weight arithmetic; pre-D0 weight | Wilson-UB weight with `REF_ERR`; numbers in Verify recomputed; no grades → w 1 | §9.D2 |
| B4 None rule and per-NVR deadness | Member liveness classes and the record rule; one live NVR carries it | §7 |
| B5 two leads flags | One ledger flag plus, under the Q1 default, interior's own `interior_leads` argument (an operator decision, not a second ledger flag); admission constant; truth table; bar recorded in census §3.3 | §1a, §9.D4, §14 |
| B6 overlap groups name-keyed | `CONF_INTERIOR_CAMERA_OVERLAP_GROUPS` by camera device id, built by D4 | §9.D4, §12 |
| B7 `area_to_room` source | Registry area → producer `_room_for_area` (room config entry area ids) | §7 |
| B8 build placement | Producer timer and listener; test that the build is not on the census-update stack | §9.D1 |
| B9 hollow tests | Guard drills; `test_describe_never_feeds_census` drives descriptions and compares `deconflict_house` arguments | §6.3, §9.D3 |
| B10 D3 inbound path | Text-channel branch, `describe <room|person>`, requester-only `_send_reply` | §9.D3 |
| B11 provider registration | Pulled term provider via presence delegate; no push | §6.2, §9.D4 |
| B12 cost per frame mismatch | Per-call estimate 0.0003, set by D0(c) | §12 |
| B13 memory rows | Accepted with a correction: `log_memory_episode` is a direct insert, not the write queue; rows bounded by the call cap, no per-tick rows | §9.D2 |
| B14 Protect historical frames | D0 uses Frigate snapshots only; stated | §9.D0 |
| G1 clip path | As H5 | §8 |
| G2 switch off at ship | ON at ship, renamed, caps | §1, §12 |
| G3 calendar-gated bar | Interval-width bar from D0 + D7; grading 20 a day while open; no 7-day floor | §9.D4 |
| G4 emotion parked | Operator answered "Emotion yes as prep for the future": affect field ships ON behind a constant, recorded, no consumer | §1, §9.D3, §12 |
| G5 counts never move the census | Formula fixed (B2), bar fixed (G3); truth table states when interior moves `aware_guests` | §9.D4 |
| G6 D6 14-day hold | Interval-based trigger, no day count | §9.D6 |
| G7, G8 no drift | Acknowledged; W2 relaxed to the D4 flip, arc map edit proposed | §7, §14 |

Closure re-review (`plan_review_vision_interior_closure_2026_11_15.md`, PLAN-FIX-REQUIRED: 1 HIGH, 9 MEDIUM, 8 LOW):

| Finding | Resolution | Plan section |
|---|---|---|
| N1 (HIGH) still from a non-live Frigate member | Still call only when the still-source member is LIVE; skip `still_source_not_live`; INV-IV-MISSING extended; tests `test_no_sample_from_non_live_still_source`, `test_describe_non_live_still_source_no_call`, mutation | §8, §8b, §9.D2, §9.D3 |
| N2 interior term defeats case-D fallback | Lower-bound rule: interior only raises (`max(base, interior)`), excluded from `vis`; truth-table row for ledger None; `test_interior_never_lowers_awareness` | §9.D4 |
| N3 `area_evidence()` is per area | Per-entity readings from `_stream_last_reading`; platform from the registry; one group per area asserted in D0(a) | §5, §7 |
| N4 static-scene scope and lifetime | One definition (ANY group, debounced, knob); D0(i) measures lifetime; §15 row | §8b, §9.D0, §9.D2, §12, §15 |
| N5 slug in two partitions | One placement per slug (BLE ACTIVE, else newest face) before the union; repro test | §8b, §9.D4 |
| N6 hop windows not cumulative | Cumulative chain windows, close at cumulative max + pad, max hops knob; live-chain test | §9.D5, §12 |
| N7 affect consumer and hollow test | Reply excludes affect except `operator_affect`; `FORBIDDEN_ATTR_READS` guard on `.affect`, drill `[iv_affect_reader]` | §6.3, §9.D3 |
| N8 describe authorization | Operator question Q2, default operator-only Select | §1a, §9.D3, §12 |
| N9 sampling starves describe | `INTERIOR_DESCRIBE_RESERVED_CALLS`; sampling skips `reserved_for_describe`; test | §9.D3, §9.D2, §12 |
| E1 head count dropped silently | Explicit non-goal with revival trigger; carded; sighting plan §15.8 edit | §13, §14 |
| L-1 `frigate_member` reuse | Marked REUSE | §5, §8 |
| L-2 false-guest arithmetic | 0 of ≥ 125 needed; test | §9.D4 |
| L-3 disagreement-first bias | D0 stratified; D7 rates reported separately, pooled with stratum weights | §9.D0, §9.D7 |
| Q4 | Interior ledger floor window: sustained minimum or max over the window? | **Sustained minimum** over `INTERIOR_LEDGER_FLOOR_SUSTAIN_S` (60 s, set by D0 F-a). Reason: the floor raises `L` until an exit or anchor, so a max turns a one-tick double-count (overlapping cameras, a walk-through) into a persistent phantom guest | Max over a short window (the original brief) | §1b.2 |
| L-4 describe cooldown; frames-left off value | `INTERIOR_DESCRIBE_NM_COOLDOWN_S`; `INTERIOR_FRAMES_LEFT_CHECK_ENABLED` | §9.D3, §9.D7, §12 |
| L-5 drill receiver | Non-`self` receiver stated, with the R7 reason | §6.3 |
| L-6 golden branch; pins | Own branch for `interior_admitted_5_lead`; pins are (module, qualname) including the presence delegates | §8b, §6.3 |
| L-7 `persons_in_room` contract gap | Return type and `active_only` pinned; contract edit listed | §14 |
| L-8 unrecorded drops | 1-3 frames: non-goal (one still or clip); D5 unnamed trigger: restored; `describe_person` face fallback: restored; security p90 ≤ 15 s: restored in non-goals; sighting §15.8 / §15.9.4 and census §3.6 edits: restored; §8c reworded; D3 task tracked and cancelled | §8, §8c, §9.D3, §9.D5, §13, §14 |
| Q1 / Q2 / labelling budget | Decisions pending with defaults | §1a |
