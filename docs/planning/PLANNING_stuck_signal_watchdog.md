# PLANNING: Stuck-Signal Watchdog Cycle

## Post-review design rulings (2026-07-28 fix-up)

Applied AFTER two Tier-2 reviews returned DO-NOT-SHIP. These are
orchestrator-decided, do not re-litigate:

1. **D3 predicate replaced.** Prior rule required tracker↔person
   DISAGREEMENT — structurally blind to the motivating incident (the
   frozen tracker DRIVES `person.state` → they always agree → silent).
   New rule: `tracker.state in {"home","unknown"} AND age >=
   FROZEN_TRACKER_DAYS` → NM. Frozen-at-`not_home` is benign (fire axe:
   no user-actionable harm). Sibling-tracker disagreement is CONTEXT in
   the payload, not a gate. Ezinne repro is a named test.

2. **D2 becomes NOTIFY + DIAGNOSTIC ONLY.** D2 must NOT insert into the
   room's `stuck_sensors` exclusion set. A sleeping person is ~100%
   mmWave duty cycle with zero PIR — excluding would vacate sleeping
   bedrooms (home_night trust gap uncovered by v4.7.13 sleep-only
   person-trust). Exclusion graduates in a later cycle behind a
   house-state gate once the detector earns trust (stage-1 doctrine).

3. **D1 discount safety hardened.** (a) Camera with `area_id=None`:
   NEVER discount (one-time WARN + `notify_only_reason=no_area_id` in
   diagnostic). Silent auto-discount on a nameless area is unsafe.
   (b) Area with NO configured interior tier at all (no URA room mapped
   to the area_id): NEVER discount (`notify_only_reason=no_interior_tier`).
   A lone stationary guest in a camera-only area must not be
   census-dropped. Residual tradeoff: a stationary guest in an area WITH
   sensors that miss them is still discounted (documented in failure-modes).

4. **Boot-settle gate.** D1, D2, and D3 all short-circuit until the
   shared `presence._boot_settle_done` predicate flips True (same source
   consulted by `ActuatorReconciler`). No verdicts / no NM emits during
   boot storm.

5. **D2 corroboration shield tightened (FIX 4).** The prior
   `bool(motion_deque)` gate let one stale PIR blip inside the 60-min
   window disable detection permanently. New rule: corroborated iff
   `len(motion_deque) >= STUCK_D2_MIN_MOTION_TRANSITIONS` (=2) OR at
   least one transition within the last `STUCK_D2_FRESH_MOTION_SECONDS`
   (=300s). Named module constants (rung 1).

## Failure modes (post-fix)

- **D1 stationary-guest-in-sensored-area.** A lone motionless guest in
  a room that HAS interior sensors, if those sensors don't fire, will
  still be discounted from the census after the stuck window elapses.
  Acceptable tradeoff — the review-time alternative (never discount)
  reopens the foyer 11h silent-hold bug that motivated this cycle.
- **D2 sleeping-person false positive.** Held to notify-only per Ruling
  2; no census impact until later cycle graduates exclusion.

## Rung-2 vs rung-1 knobs (post-fix)

- `CONF_STUCK_SIGNAL_NM_ENABLED` — rung 2 (options-flow), operator kill
  switch during known outages.
- `STUCK_CAMERA_HOURS`, `STUCK_CAMERA_INTERIOR_TIERS_REQUIRED`,
  `FROZEN_TRACKER_DAYS`, `STUCK_D2_FRESH_MOTION_SECONDS`,
  `STUCK_D2_MIN_MOTION_TRANSITIONS`, all `STUCK_SENSOR_DUTYCYCLE_*` —
  rung 1 (module constants). The `CONF_STUCK_CAMERA_*`/`CONF_FROZEN_*`
  keys still exist in `const.py` for backward compatibility with the
  `merged.get()` reads in camera_census/person_coordinator (deprecated
  — a future cycle drops the options read entirely). They are NOT wired
  into the config flow.

---



**Version target:** next minor after HEAD (v5.34.x → v5.35.0 candidate).
**Author date:** 2026-07-28.
**Tier proposal:** Tier 2 (two framing-disjoint reviews) + Live Validation. See Tier Classification section.
**Authoritative input:** `docs/planning/CATALOG_cross_correlation_primitives.md` (HEAD). The VERDICT there — *extend the thrice-proven "asserted-too-long ⇒ demand corroboration ⇒ act" shape (P22 / P24 / P18); do NOT roll a new correlation framework* — is ratified and is not re-litigated in this doc.

---

## Falsifiable invariant (stated up front)

> **No presence-implying signal (per-camera person count, per-room binary sensor, per-person device_tracker) can hold a house/zone/census state beyond `N` hours without corroboration from at least one other tier, silently.**

Operationally, the cycle must guarantee:

1. If any single signal is the *sole* reason a state (GUEST / OCCUPIED / HOME) is asserted for ≥ its stuck-window with zero independent corroborators from the other tiers already tallied in P12/P13, then within one presence tick either (a) the signal is discounted from the derived state, OR (b) an NM notification with diagnosis + suggested remedy fires — per-day deduped. Silent hold is not a legal outcome.

Reviewer D-analog (framing B below) must break this invariant, not just diff-review.

---

## Institutional context verified

**Adjudicator doc:** `docs/planning/CATALOG_cross_correlation_primitives.md` — the ~70-primitive exhaustive sweep. Every design choice here cites a primitive from that catalog.

**Code locations surveyed end-to-end during scoping:**
- `custom_components/universal_room_automation/coordinator.py` — Fix #9 (P22) at :193 (`_stuck_sensor_hours` init), :1502-1543 (detection + exclusion), Fix #10 grace hold :1482-1500, RESILIENCE-001 (P24), Fix #8, BLE-extend, entry debounce.
- `custom_components/universal_room_automation/sensor.py:2188, 2245` — existing readers of `_stuck_sensor_hours` (candidate stuck-set attribute surface).
- `custom_components/universal_room_automation/camera_census.py:1114-2221` — C1..C10 including the C7 peak/decay state machine at :1648-1798 (the "stuck floor" root of the 2026-07-28 foyer incident).
- `custom_components/universal_room_automation/person_coordinator.py:123-435` — C11 tracking_status / Bermuda decay (extension point for D3 frozen-tracker check).
- `custom_components/universal_room_automation/domain_coordinators/presence.py:5786-5839, 5650-5687` — P12 `signal_consensus` (deltas) + P13 camera/tier1/mmwave tally. **Reused as the "interior corroboration" input for D1; not re-implemented.**
- `custom_components/universal_room_automation/domain_coordinators/presence.py:1838-1940` + `.../hvac.py:1253-1303` — P18 zone stale-occupancy failsafe (the SHAPE we extend).
- `custom_components/universal_room_automation/actuator_reconciler.py` — X7 flap-quarantine (silent today; D4 wires it to NM).
- `custom_components/universal_room_automation/domain_coordinators/_nm_cycle_a.py` — NM Cycle A knob cache + per-(surface,type)/day latch pattern (X21). **All D1..D4 notifications reuse this latch mechanism.**
- `custom_components/universal_room_automation/const.py` — grepped for existing `STUCK_*` / `WATCHDOG_*` / `CORROBORATION_*` (see "greps" table).

**Prior planning docs consulted (skim):**
- `docs/planning/PLANNING_presence_pair_guest_latch_veto_gap.md` — GUEST-latch semantics (v5.16.0). D1's discount path must not reintroduce the pair-guest latch bug (it doesn't: D1 discounts the census *input*, GUEST derivation downstream is unchanged).
- `docs/planning/PLANNING_v3.6.0_REVISED.md` — milestone map (context only).
- CATALOG_cross_correlation_primitives.md — see above.

**Memory bodies pulled:** `project_presence_guest_latch_and_veto_gap.md`, `project_session_pickup_2026_07_20.md` (current session state / NM Cycle A shipped).

**Design docs read:** `docs/Coordinator/presence.md`, `docs/Coordinator/camera_census.md` (if present — otherwise inferred from code + catalog).

### Greps run — REUSED / NEW table (proof-of-work for every new symbol)

| Proposed symbol | Grep target | Result |
|---|---|---|
| `CONF_STUCK_CAMERA_HOURS` | `STUCK_CAMERA` in `const.py`, `config_flow.py`, `options_flow.py` | NEW — no existing knob covers per-camera-count stuck window. Nearest: `_stuck_sensor_hours` (RAM-only, per-room binary). Justification: D1 operates at census/camera layer, distinct scope. |
| `CONF_STUCK_SENSOR_DUTYCYCLE_PCT`, `CONF_STUCK_SENSOR_DUTYCYCLE_WINDOW_MIN` | `DUTYCYCLE`, `DUTY_CYCLE` in `const.py` | NEW — Fix #9 is continuous-on only; no duty-cycle knobs exist. |
| `CONF_FROZEN_TRACKER_DAYS` | `FROZEN_TRACKER`, `TRACKER_STALE_DAYS` in `const.py`, `person_coordinator.py` | NEW — C11 decays Bermuda ACTIVE→STALE→LOST at 300s but has no *days*-scale frozen-tracker check on device_tracker `last_updated`. |
| Stuck-set attribute on `sensor.<room>_...` | grep `stuck_sensor` in `sensor.py` | REUSED — extend existing `_stuck_sensor_hours` surface at sensor.py:2188/2245 with a `stuck_kind: continuous|dutycycle` field; no new entity. |
| NM notification type `stuck_signal` | grep `notification_type` / `nm_type` in `_nm_cycle_a.py` + `notification_manager.py` | NEW category, REUSED plumbing (per-(surface,type)/day latch pattern X21). |
| Consensus consumer at census layer | grep `signal_consensus` in `camera_census.py` | NEW consumption site — presence computes it (P12), census does not yet read it. D1 will read the already-published consensus + P13 tally. **No new computation.** |
| Interior-corroboration primitive | grep P12 / P13 inputs | REUSED — `_zone_camera_counts`, `_zone_tier1_counts`, `_zone_mmwave_counts` at presence.py:5650-5687. |
| Duty-cycle helper | grep `dutycycle`, `on_ratio` in `coordinator.py`, utils | NEW — small ring-buffer helper alongside `_sensor_on_since`. |

If any "NEW" above turns out to have prior art the reviewer surfaces, the plan drops the new symbol and reuses.

---

## Non-goals (explicit — do not scope-creep)

- **No new consensus framework.** P12 `signal_consensus` exists and is the interior-corroboration source of truth. D1 consumes it; D1 does not compute a new one.
- **No auto-remediation.** D3 does NOT auto-prune trackers. D1 does NOT reload the Frigate config entry. All D1..D4 remediation is *notify-only*; auto-remediation is a Stage-2 cycle gated on Stage-1 operator-trust evidence (see "Follow-ups").
- **No abstraction/unification of P22/P24/P18** in this cycle. A separate abstraction decision is pending; premature unification would collide with the NM wiring shape and delay D4.
- **No new thresholds without knobs.** Every threshold introduced (or touched) in D1..D4 gets a named knob per "Numbers get knobs". Inline-literal debt in surrounding code is NOT expanded; existing debt flagged by the catalog (C9 stale docstring, presence sweeps) is out-of-scope unless touched in a diff.
- **No P14 vestigial-veto deletion, no C9 4h/24h docstring fix, no smoke+CO AND-gate** — flagged by catalog for separate hygiene work.

---

## Deliverables

### D1 — Census-layer per-camera stuck-count check (`camera_census.py`)

**What.** For each Frigate camera contributing to `person_count`, track (a) the *unchanged-count assertion window* (`person_count > 0` and value unchanged) and (b) the *duty-cycle assertion window* (`person_count > 0` for ≥ X% of a rolling window with count value not strictly required to be constant). When either exceeds `CONF_STUCK_CAMERA_HOURS` (default 3h) AND **zero interior corroboration** in the camera's zone/room from the P12/P13 inputs (no tier1, no mmwave-on, no motion-on, no BLE-here), then:

1. **Discount** the camera's contribution from the census sum used by C7's `fresh` value on this tick. This ages the C7 `max(fresh, peak−steps)` floor — the exact failure mode of the 2026-07-28 foyer incident.
2. **Emit NM** `stuck_signal` notification, per-day deduped via X21 latch: surface=`camera_census`, key=`(camera_entity_id, kind)`, diagnosis text `"camera <id> asserted person_count=<n> for <h>h with no interior corroboration"`, suggested remedy `"reload Frigate config entry"`.

Discount is *truth-preserving downward*: it never raises a count. It never fires when interior corroboration is present (matches P18 shape).

**Rough size:** ~120 LOC in `camera_census.py` + ~40 LOC test helpers + 2 knobs.

**Knobs (numbers get knobs — module constants; require review to change):**
- `CONF_STUCK_CAMERA_HOURS` — module constant in `const.py`, default **3.0** — rung 1 (module const): stuck-window is a safety/protocol boundary, operator should not turn it live.
- `CONF_STUCK_CAMERA_INTERIOR_TIERS_REQUIRED` — module constant, default **1** — how many of {tier1, mmwave, motion, BLE-here} must be present to *skip* discount. Rung 1.

**Acceptance criteria:**
- **Verify:** with a mocked Frigate camera stuck at `person_count=2` for 3h+ and all room sensors quiet, next tick the census `fresh` value drops by 2 and C7 decay can now age the floor to 0 within `hold + 5*decay_step`.
- **Verify:** with the same mocked stuck camera but ONE interior corroborator active (e.g. mmwave-on in the room the camera covers), discount does NOT fire and NM does NOT notify.
- **Sensor:** `sensor.ura_camera_census` gains attribute `stuck_cameras: [{entity_id, kind, hours, interior_corroborators}]`; empty list on healthy.
- **Test:** `test_camera_census_stuck_discount_ages_floor`, `test_camera_census_stuck_skipped_when_corroborated`, `test_camera_census_stuck_nm_dedup_per_day`.
- **Live:** validator drill — SSH-scripted synthetic-stuck: `python3 -c "hass.states.async_set('sensor.frigate_foyer_fisheye_person_count', 2)"` held for the shortened test window (operator-set `CONF_STUCK_CAMERA_HOURS=0.1` under a dry-run switch), observe `stuck_cameras` attr populated and NM `stuck_signal` notification received once, `sensor.ura_camera_census` count drops. Restore knob.

---

### D2 — Fix #9 duty-cycle variant (`coordinator.py`)

**What.** Extend Fix #9 (P22) at `coordinator.py:1502-1543`. Today it detects *continuously-on* sensors; a flapping mmWave (Master Bedroom empty-suite cooling incident) evades it because every off-tick resets `_sensor_on_since`. Add a parallel duty-cycle check: per binary sensor, maintain a small ring (last `CONF_STUCK_SENSOR_DUTYCYCLE_WINDOW_MIN` minutes, default 60) of on/off ticks; if the on-ratio exceeds `CONF_STUCK_SENSOR_DUTYCYCLE_PCT` (default 0.85) AND the sensor is PIR-uncorroborated in the SAME room for the window (no motion transitions in the same window), classify it stuck. Same exclusion + WARN path as Fix #9 today; **plus** NM emit via D4's wiring.

**Rough size:** ~80 LOC + ring-buffer helper + 3 knobs.

**Knobs (module constants — same reasoning as D1):**
- `CONF_STUCK_SENSOR_DUTYCYCLE_WINDOW_MIN` — default **60**, rung 1.
- `CONF_STUCK_SENSOR_DUTYCYCLE_PCT` — default **0.85**, rung 1.
- `CONF_STUCK_SENSOR_DUTYCYCLE_MIN_TICKS` — default **20**, rung 1 (warm-up floor — no verdict until this many ticks in window; prevents boot-transient false-positive).

**Acceptance criteria:**
- **Verify:** simulated mmWave that flaps on 5s / off 1s for 60min with zero motion transitions → classified `stuck_kind=dutycycle`, excluded from `presence_detected` computation, NM emitted once.
- **Verify:** same mmWave WITH motion transitions in the same window → NOT classified stuck (PIR corroboration present).
- **Verify:** boot transient (5 ticks of on) does not trip.
- **Sensor:** attribute added to existing per-room sensor exposure (sensor.py:2188 / 2245 area) — `stuck_kind: continuous|dutycycle|null` per stuck entry.
- **Test:** `test_fix9_dutycycle_variant_flapping_mmwave_excluded`, `test_fix9_dutycycle_skipped_with_pir_corroboration`, `test_fix9_dutycycle_warmup_floor`.
- **Live:** validator drill — pick a real quiet room, use HA `input_boolean` proxied into a room's mmwave list under a test config, script 10min of flap; observe `stuck_kind=dutycycle` on the room sensor's attribute and NM notification. Revert config.

---

### D3 — Frozen-tracker check (`person_coordinator.py`)

**What.** For each `device_tracker` entity in a person's aggregation, check `state.last_updated` age. If age ≥ `CONF_FROZEN_TRACKER_DAYS` (default 2.0) AND the person's other evidence (BLE, camera face, other trackers) disagrees with the frozen tracker's state, emit NM `stuck_signal` with diagnosis `"device_tracker <id> unchanged for <d> days; other evidence indicates <alt_state>"`. **No auto-prune.** Person tracking_status is unaffected; C11 keeps its decay semantics.

**Rough size:** ~60 LOC + 1 knob.

**Knob:**
- `CONF_FROZEN_TRACKER_DAYS` — module constant, default **2.0**, rung 1.

**Acceptance criteria:**
- **Verify:** synthetic tracker with `last_updated` 3d old + person face seen within the hour → NM emitted once/day.
- **Verify:** fresh tracker (updated within window) → no emit.
- **Verify:** stale tracker WITH agreeing other evidence (all evidence says "home") → no emit (agreement means no user-actionable divergence).
- **Sensor:** `sensor.ura_person_coordinator` gains attribute `frozen_trackers: [{entity_id, days, disagreeing_evidence}]`.
- **Test:** `test_person_frozen_tracker_notify_on_disagreement`, `test_person_frozen_tracker_silent_on_agreement`, `test_person_frozen_tracker_no_autoprune`.
- **Live:** validator drill — pick a tracker known to be dormant (e.g. an old phone), temporarily set `CONF_FROZEN_TRACKER_DAYS=0.01` via test config, force a disagreement (BLE ping / manual `person` set), observe NM emit once. Restore.

---

### D4 — NM surface for existing silent detectors

**What.** Wire the four existing silent detectors to NM via the X21 per-day dedup latch (reuse `_nm_cycle_a.py` machinery + NM Cycle A knob cache):

1. **P22 Fix #9 stuck set** — `coordinator.py:1517` currently only WARN-logs. Add NM emit alongside the log, keyed `(room, sensor_entity_id, kind=continuous)`.
2. **P24 RESILIENCE-001 failsafe fires** — `coordinator.py:1690-1754`. Emit `stuck_signal` with kind `max_active_failsafe` on force-vacant, keyed `(room, reason)`.
3. **P18 zone stale-occupancy force-away** — `hvac.py:1253-1303` + `presence.py:1838-1940`. Emit on force-away path with kind `zone_stale_occupancy`.
4. **X7 flap-quarantine** — `actuator_reconciler.py` quarantine transition. Emit with kind `actuator_flap_quarantine`; auto-recovery emits a resolution message (paired latch).

All four share one notification type (`stuck_signal`) with a `kind` field so the operator sees one class of alert with sub-classifications. Existing behavior (log, exclusion, failsafe action) is UNCHANGED — this is a *notification-only* addition (Bug Class #34 discipline: no import-in-conditional; module-level import of `async_dispatcher_send` / NM helper).

**Rough size:** ~40 LOC touching 4 sites + shared helper.

**Knobs:**
- Per-day dedup window is inherited from X21 (already knobbed under NM Cycle A). No new knob.
- `CONF_STUCK_SIGNAL_NM_ENABLED` — options-flow switch (rung 2, operator-visible), default **True** — kill-switch. Rung 2 because operator may want to silence during a known-bad Frigate outage without a code push.

**Acceptance criteria:**
- **Verify:** each of the 4 sites, when triggered under test, emits exactly one NM per (site-key) per day.
- **Verify:** kill-switch False suppresses all 4 without disabling the underlying detection logic (exclusion / failsafe still runs).
- **Verify:** flap-quarantine resolution path emits a paired "recovered" notification and clears the latch.
- **Sensor:** none new; NM notification is the surface.
- **Test:** `test_nm_stuck_signal_p22_emit_and_dedup`, `test_nm_stuck_signal_p24_emit_on_failsafe`, `test_nm_stuck_signal_p18_emit_on_force_away`, `test_nm_stuck_signal_x7_emit_and_recover`, `test_nm_stuck_signal_kill_switch`.
- **Live:** validator drill — for each of the 4, either wait for a natural fire (P24/P18/X7 do fire organically in normal ops) or synthetic-force (P22: hold a test input_boolean on for the shortened window). Confirm one NM per site per day, and confirm kill-switch flipped to False cleanly suppresses.

---

## Tier classification (proposed)

**Tier 2** (two framing-disjoint reviews + Live Validation).

**Justification:**
- Scope crosses presence, census, person, HVAC-consumer, and reconciler surfaces (five files) → above Tier 1 hotfix.
- BUT no actuation change: D1 discount is truth-preserving downward at the census layer; D2 extends an exclusion path that already exists; D3 is notify-only; D4 is notify-only. No new writes to the shared state machines that would create cost/safety ripple.
- Not Tier 2-DB: no DB DAO changes, no schema, no persisted payload shape changes.
- Not Tier 3: does not thread a value through a state machine (unlike v5.5.3 reserve floor). NM notification is additive, not a shared primitive being invariant-threaded.

**Framing-disjoint reviews:**
- **Review A — Correctness + interior-corroboration semantics.** Per-deliverable arithmetic; discount is downward-only; PIR-corroboration definitions; boot-transient warm-up; dedup key granularity per site; the falsifiable invariant holds under legal configs. Cross-check every "corroboration" boolean against P12/P13's definition — no drift.
- **Review B — Async / lifecycle / cross-coordinator races + NM regression risk.** Ring-buffer memory bounds and cleanup on entity removal (Bug Class #22); NM emit paths use module-level imports (Bug Class #34); no reentrancy between D1 discount and C7 state machine within one tick; kill-switch flips do not orphan pending latches; per-day latch clock source (X21 pattern); no regression to P22/P24/P18/X7 behavior (byte-identical on the no-op / no-emit path); no new NM burst on boot.

Reviewers are given DIFFERENT framings by design; overlap on the invariant is the only shared surface.

---

## Files changed (expected)

| File | Change |
|---|---|
| `custom_components/universal_room_automation/camera_census.py` | D1: per-camera stuck check + discount + NM emit |
| `custom_components/universal_room_automation/coordinator.py` | D2: duty-cycle variant of Fix #9; D4-part-1: P22 NM emit; D4-part-2: P24 NM emit |
| `custom_components/universal_room_automation/person_coordinator.py` | D3: frozen-tracker check + NM emit |
| `custom_components/universal_room_automation/domain_coordinators/hvac.py` | D4-part-3: P18 NM emit on force-away |
| `custom_components/universal_room_automation/domain_coordinators/presence.py` | D4-part-3 companion: P18 zone force-away emit call (if the emit belongs on the presence side of the pair — resolve during build) |
| `custom_components/universal_room_automation/actuator_reconciler.py` | D4-part-4: quarantine enter/recover NM emit |
| `custom_components/universal_room_automation/const.py` | New CONF_* constants (see knobs) |
| `custom_components/universal_room_automation/config_flow.py` / `options_flow.py` | `CONF_STUCK_SIGNAL_NM_ENABLED` kill-switch (options-only) |
| `custom_components/universal_room_automation/sensor.py` | Attribute additions to existing per-room + camera-census + person-coordinator sensors (`stuck_cameras`, `stuck_kind`, `frozen_trackers`) |
| `custom_components/universal_room_automation/domain_coordinators/_nm_cycle_a.py` | Register `stuck_signal` notification type + `kind` subclassification |
| `quality/tests/` | New tests per deliverable |

No new sensor entities. No new number/select entities (only one options-flow switch).

---

## Cross-cutting risks + mitigations

- **C7 interaction (D1).** Discount must feed C7's *fresh* value before its peak-hold captures it. Verify D1 runs upstream of the C7 update in the tick order at `camera_census.py:1648-1798`. Test asserts the *floor* value drops post-discount.
- **Bug Class #34 (D4).** Every new `async_dispatcher_send` / NM emit is a module-level import. Reviewer B checks explicitly.
- **Bug Class #48 legacy (D4-part-3).** P18 force-away path is presence/HVAC shared; the NM emit must attach to exactly one caller to avoid double-emit. Reviewer B traces both sites; single-emit invariant tested.
- **Boot-transient false positives.** D1 requires wall-clock duration (safe across boot). D2 requires `CONF_STUCK_SENSOR_DUTYCYCLE_MIN_TICKS` warm-up. D3 wall-clock day-scale is safe. All four NM emits gated behind Predicate-A boot-settle if within `boot_settle_seconds`.
- **NM burst on migration.** First tick post-deploy could find pre-existing stuck signals (e.g. the real foyer camera today). Latch is per-day → operator sees each once, not a burst. Acceptable.
- **Dry-run for live validator drills.** Shortened `CONF_STUCK_CAMERA_HOURS=0.1` and `CONF_STUCK_SENSOR_DUTYCYCLE_WINDOW_MIN=2` must not persist. Validator restores after each drill; README `Validated <date>` records the restore.

---

## Plan-completion tracking (predictive)

Items expected to close within this cycle: D1, D2, D3, D4. Items explicitly NOT in cycle (parked with trigger):
- Stage-2 auto-remediation (Frigate entry reload, tracker prune) — trigger: 2 weeks of Stage-1 operator-trust with zero false-positive NMs.
- Abstraction/unification of P22/P24/P18/D1 into one primitive — trigger: after D1..D4 ship and the shape is proven at four sites; separate design cycle.
- Catalog-flagged hygiene (C9 docstring, P14 vestigial, presence inline literals not touched by this diff, smoke+CO AND-gate) — separate hygiene cycle.

---

## Live validation write-back (mandatory per CLAUDE.md)

Post-deploy, replace the prospective "Live" bullets in `docs/readmes/README_v<version>.md` with a `Validated <date>` results table: one row per acceptance-criterion Live drill, PASS/FAIL, evidence (entity_id + attribute value, NM notification log line, DB row where applicable), and the exact test config used (knob overrides + restore commit). Cycle does not close until the README carries this table.
