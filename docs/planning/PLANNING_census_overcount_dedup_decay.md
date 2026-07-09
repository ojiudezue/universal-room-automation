# PLANNING — Census Over-Count Fix (Spatial Dedup + Sustain-Before-Latch)

**Status:** DESIGN-ONLY (no build). Tier recommendation: **Tier 2-DB (3 framing-disjoint reviews)**.
**Author:** ura-planner, 2026-07-07 (original) / revised 2026-07-07 (live design session).

---

## Revision — 2026-07-07 (live design session)

The first draft framed the fix as "spatial dedup + a new per-input freshness
TTL". A live walkthrough with the operator produced three findings that
inverted the temporal half of the design, and the operator asked for
aggressive simplification. This revision restructures the deliverables and
demotes the TTL + explicit overlap-group config to out-of-scope / stretch.

### What we learned (verified against source this pass)

1. **The census ALREADY has a peak-hold + decay stage — and it AMPLIFIES the
   symptom.** `_apply_hold_decay` at `camera_census.py:1373`: any
   `fresh_count >= stored peak` LATCHES peak (:1394-1404), the peak is
   returned for the full hold window (`CONF_CENSUS_HOLD_INTERIOR`, default
   **15 minutes**, `const.py:1367`), then decays -1 per
   `CENSUS_DECAY_STEP_SECONDS = 300s` (`const.py:1369`). A ~5-15s
   thoroughfare handoff spike (hallway detection tail overlaps with the
   stairway trip) instantaneously reads `fresh=2` — the peak layer then
   holds "2" for **up to 15 min plus decay**. This one mechanism explains
   BOTH operator-confirmed symptoms (count too high AND lingers). The prior
   draft missed this — a second temporal mechanism (per-input TTL) would
   have been redundant with, and unable to prevent, the peak latch.

2. **Sequential (thoroughfare) handoff is a distinct case from overlap.**
   Two non-overlapping cameras in DIFFERENT HA areas serially detect one
   moving person. Area grouping doesn't cover it (different areas) and an
   input TTL doesn't cover it (both readings are genuinely fresh). The
   operator-approved fix is **sustain-before-latch**: a higher `fresh_count`
   only becomes the new peak if it holds for `CENSUS_PEAK_SUSTAIN_SECONDS`
   (default ~15s). Handoff spikes can't sustain — the trailing camera drops
   in seconds; a real second person does sustain. Downward moves keep
   existing instant/decay semantics.

3. **Camera config is already area-aware, zero new config needed.**
   Interior census cameras come from `CONF_CAMERA_PERSON_ENTITIES`
   (`const.py:958`), a flat integration-level camera.* list
   (`config_flow.py:2843`, EntitySelector `domain=camera multiple`).
   `CameraInfo.area_id` is auto-populated from the entity registry at
   resolve time (`camera_census.py:1228-1230`). Area-based spatial grouping
   therefore needs ZERO new CONF keys. Separately, `transit_validator.py`
   already records per-room camera checkpoint sightings with timestamps
   (`TRANSIT_CHECKPOINT_WINDOW_SECONDS`) — prior art for an optional
   transit-transfer refinement if D-A/B/C leave residual over-count.

### What changed (cuts + simplifications, with justification)

- **CUT: per-input freshness TTL (D1 in prior draft) + `CENSUS_INPUT_TTL_SECONDS`
  const + Number entity + `stale_inputs` attribute.** The peak layer (D-C)
  is the actual "lingers" mechanism; adding a second competing temporal
  layer would be duplicated policy in a shared primitive. `_is_entity_available`
  (`camera_census.py:1260`) already zeroes `unavailable`/`unknown`, so a
  stuck-off/disconnected sensor is already handled. The remaining edge —
  a sensor stuck reporting `on`/`count>0` while its state has stopped
  updating — is real but rare and gets partially caught by sustain-latch
  (a stuck-high sensor that only starts lying after a legit high count is
  already latched will not RE-latch a new high on its own; only a sustained
  real increase does). Moved to Stretch S-1 with an explicit
  "keep only if a verified consumer path is found where sustain-latch + hold
  decay + availability leaves a stuck sensor able to pin an inflated count"
  gate.

- **CUT: `CONF_CAMERA_OVERLAP_GROUPS` (D3 in prior draft) + options-flow
  multi-select builder + `overlap_groups_applied` attribute.** Same-area
  overlap is covered by D-A (area grouping via existing `CameraInfo.area_id`);
  cross-area handoff is covered by D-B (sustain-latch). The only residual
  case is a SUSTAINED cross-area simultaneous overlap — two cameras in
  DIFFERENT HA areas continuously seeing the same physical spot — which
  is unusual and, per the operator, has not been observed. Deferred to
  D-DEFER-1: revisit only if live validation shows residual over-count
  after D-A/B/C ship.

- **CUT: Frigate zone-count entity preference (D2 in prior draft).** D-A
  makes it unnecessary for this house; if a Frigate zone-count entity exists
  it will still be one of the per-camera inputs, and area-max handles it
  correctly. Not worth the "verify at build time" branch.

- **KEPT + REFRAMED: D-C re-examines the EXISTING hold/decay defaults**
  (`CONF_CENSUS_HOLD_INTERIOR = 15 min`, `_EXTERIOR = 5 min`,
  `CENSUS_DECAY_STEP_SECONDS = 300s`) rather than adding new temporal
  policy. The 15-min interior hold is likely far too long once D-B is in
  place — D-B removes the handoff-spike source, so the hold no longer
  needs to protect against transient dropouts; it only needs to survive
  mmWave still-body gaps (seconds to a few minutes). Build phase proposes
  reducing the interior default and measuring.

- **New-config surface:** ONE constant (`CENSUS_PEAK_SUSTAIN_SECONDS`,
  default ~15s), ZERO new CONF keys, ZERO new Number entities, ZERO new
  options-flow fields. Per Configurability-Clarity, the sustain window is
  tunable in code, not exposed as a control.

- **Invariant updated** to cover sustain-latch (below).

### Consumer tolerance for the ~15s sustain delay

Two load-bearing consumers of `unidentified_count`:

- **v4.7.14 AWAY veto** (`presence.py:980-1030`): fires when
  `all_tracked_persons_away AND unidentified_count == 0`. No timing
  constraint on how long the condition must hold before the veto fires;
  a real second person will latch within ~15s, which precedes veto arming
  by orders of magnitude. **Tolerates.**
- **Guest gate arming** (`presence.py:4071`, `_guest_gate_armed`): the
  gate already applies `DEFAULT_GUEST_PERSISTENCE_SECONDS = 300s`
  (`const.py:1384`) before arming GUEST-state. A 15s sustain-latch is
  well inside that 300s persistence window and does not shift GUEST
  behavior perceptibly. **Tolerates.**

No consumer identified that cannot tolerate the 15s delay. Reviewer B
must re-verify this claim across the full consumer set at build time.

---

## Falsifiable Invariant (revised — the single property the fix must guarantee)

> Given N physical persons in the interior, at any time `t`:
> 1. **Same-area spatial dedup:** cameras sharing an HA `area_id` contribute
>    `max(fresh_count_per_camera)` to the total for that area; totals sum
>    across areas.
> 2. **Sustain-before-latch:** a `fresh_count` increase (`fresh > current
>    peak`) NEVER latches the peak — and therefore never propagates through
>    hold/decay — unless it is sustained for at least
>    `CENSUS_PEAK_SUSTAIN_SECONDS`. Transient increases below the sustain
>    threshold are ignored by the peak layer.
> 3. **Ordering (top to bottom):** availability + freshness → spatial dedup
>    (same-area max) → sustain-latch (peak update) → hold/decay → aggregate
>    → `_cross_correlate_persons` → `unidentified_count`.
> 4. `unidentified_count = max(0, camera_total_after_dedup_and_sustain − identified_count)`.

Reviewer D (adversarial) must break this by producing a **legal-config
repro** — e.g. one person walking garage-hallway → stairway pinning
`camera_total >= 2` for more than `CENSUS_PEAK_SUSTAIN_SECONDS`.

---

## Institutional Context Verified

### Anchors read end-to-end (with file:line) — this session

- `camera_census.py:1373-1430` — `_apply_hold_decay`: peak-latch on
  `fresh_count >= peak` (:1394-1404), hold window using zone-configurable
  duration (:1385-1411), gradual decay `-1 / CENSUS_DECAY_STEP_SECONDS`
  after hold expires (:1414-1425). **THIS is the mechanism amplifying the
  handoff spike into a minutes-long over-count.**
- `camera_census.py:1220-1234` — `_get_interior_camera_entities` +
  `_get_integration_camera_list`: reads flat integration-level
  `CONF_CAMERA_PERSON_ENTITIES` (camera.* IDs) and resolves via
  `CameraIntegrationManager.resolve_configured_cameras`. Docstring at
  `:1228-1230` explicitly notes `CameraInfo.area_id` is auto-populated
  from the HA entity registry — **no per-room camera config needed for
  area grouping**.
- `camera_census.py:1260-1275` — `_is_entity_available` /
  `_is_entity_on` already zero `unavailable`/`unknown` states. Covers
  the "stuck-off/disconnected sensor" edge for free.
- `const.py:1365-1369` — `CONF_CENSUS_HOLD_INTERIOR`,
  `CONF_CENSUS_HOLD_EXTERIOR`, `DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES=15`,
  `DEFAULT_CENSUS_HOLD_EXTERIOR_MINUTES=5`, `CENSUS_DECAY_STEP_SECONDS=300`.
- `const.py:958-960` — `CONF_CAMERA_PERSON_ENTITIES`, `CONF_EGRESS_CAMERAS`,
  `CONF_PERIMETER_CAMERAS` (integration-level, flat camera.* lists).
- `const.py:1383-1384` — `CONF_GUEST_MODE_PERSISTENCE_SECONDS` /
  `DEFAULT_GUEST_PERSISTENCE_SECONDS=300`. Justifies "guest gate tolerates
  15s sustain".

### Consumers of `unidentified_count` (blast radius) — unchanged

- `presence.py:910-1104` — `infer()` with `unidentified_count`,
  `guest_gate_armed`, `all_tracked_persons_away`.
  - `:980-1030` — v4.7.14 AWAY-veto load-bearing consumer.
  - `:1088-1104` — guest-gate arming path (v4.6.2.2).
- `presence.py:3528-3569` — `_unidentified_count` cache + attribute surface.
- `presence.py:4071-4090` — `_guest_gate_armed` threshold/persistence guard
  (300s persistence).

### Prior art (REUSED vs NEW) — revised

- **REUSED — `CameraInfo.area_id`** (`camera_census.py:1228-1230`, populated
  by `CameraIntegrationManager.resolve_configured_cameras`). Same-area
  grouping in D-A reads this directly. No new config.
- **REUSED — existing peak-hold + decay layer** (`_apply_hold_decay`,
  `camera_census.py:1373`). D-B modifies this layer's latch condition
  in place (add sustain gate); D-C tunes its existing duration constants.
- **REUSED — availability zeroing** (`_is_entity_available`,
  `camera_census.py:1260`). Handles the trivial stuck-off case; obviates
  a separate freshness TTL for the common case.
- **REUSED (stretch only) — transit checkpoints**
  (`transit_validator.py`, `TRANSIT_CHECKPOINT_WINDOW_SECONDS`). Available
  if S-2 (transit-transfer suppression) is later needed.
- **NEW — ONE constant `CENSUS_PEAK_SUSTAIN_SECONDS`** (default ~15s) in
  `const.py`, adjacent to the census hold/decay block. Grep of const.py
  confirms nothing equivalent exists.
- **DROPPED from NEW (was in prior draft):** `CENSUS_INPUT_TTL_SECONDS`
  const, `ura_census_input_ttl_seconds` Number entity,
  `CONF_CAMERA_OVERLAP_GROUPS` list-of-lists CONF, options-flow builder,
  `CONF_FRIGATE_ZONE_COUNT_ENTITY`. See Revision above for rationale.

### Prior planning docs / memory bodies / design docs — unchanged

Same as prior draft: v4.7.14 (`PLANNING_v4.7.14_away_state_person_tracker_trust.md`,
`project_v4714_live.md`), BACKLOG v4.6.3.3 census over-emit suppression,
`INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md`,
`README_v4.7.18.1.md`. No `docs/Coordinator/CENSUS.md` (verified by Glob).

---

## Deliverables (restructured)

### D-A — Same-area spatial dedup (zero-config)

Group `CameraInfo` entries by `area_id`. Within a group, the group's
contribution is `max(fresh_count_per_camera)`. Cameras with no `area_id`
(shouldn't happen for correctly-registered cameras) contribute individually.
Total interior fresh count = SUM(area maxes) + SUM(unassigned camera counts).

Applies to BOTH Frigate `person_count` and non-Frigate binary paths in
`_calculate_house_census` (`camera_census.py:845-1001` in the prior draft's
anchors — build phase will re-verify current line ranges).

**Acceptance:**
- **Verify:** two cameras with the same `area_id`, both reporting `count=1`
  → area contributes 1.
- **Verify:** two cameras with DIFFERENT `area_id`, both reporting `count=1`
  → total contributes 2 (unchanged from today for cross-area).
- **Test:** `test_census_same_area_takes_max`,
  `test_census_cross_area_sums`,
  `test_census_missing_area_id_falls_back_to_individual`.
- **Sensor:** `sensor.ura_census_house` attribute `area_contributions:
  dict[str, {max_count, contributing_entity}]` for observability.
- **Live (data check):** at build time, verify EVERY interior camera in
  `CONF_CAMERA_PERSON_ENTITIES` resolves to a `CameraInfo` with a non-null
  `area_id` on the running instance. If any camera lacks `area_id`, surface
  a diagnostic log at setup — don't silently degrade.
- **Live:** walk into an area with two cameras and observe
  `area_contributions[<area>].max_count == 1` in attributes.

### D-B — Sustain-before-latch (peak layer)

Modify `_apply_hold_decay` (`camera_census.py:1373`): a fresh count higher
than the stored peak enters a **pending-latch** state timestamped `now`,
and only updates the peak once `now - pending_since >=
CENSUS_PEAK_SUSTAIN_SECONDS` AND `fresh_count` has remained `>= pending_peak`
across the interval. If `fresh_count` drops below the pending value before
the sustain window elapses, the pending latch is dropped and the current
(lower) peak stands. Downward moves keep instant/decay semantics (a real
departure shouldn't be delayed).

Per-zone pending state (`_pending_house_peak`, `_pending_house_peak_since`,
plus property equivalents) to match the existing per-zone peak fields.
No new CONF key — `CENSUS_PEAK_SUSTAIN_SECONDS` is a plain `const.py`
constant.

**Acceptance:**
- **Verify:** feed `fresh=1` for 60s, then `fresh=2` for 5s, then `fresh=1`.
  Peak MUST stay at 1 (2 never sustained).
- **Verify:** feed `fresh=1` for 60s, then `fresh=2` sustained for 20s.
  Peak MUST update to 2 (sustained past the 15s threshold).
- **Verify:** `fresh=3 → fresh=1` transition returns 1 without waiting
  (downward is instant).
- **Test:** `test_census_transient_spike_does_not_latch_peak`,
  `test_census_sustained_increase_latches_peak`,
  `test_census_downward_move_is_instant`,
  `test_census_pending_latch_reset_by_dip`.
- **Sensor:** attribute `pending_peak: {value, seconds_remaining}` when a
  latch is pending (diagnostic).
- **Live:** operator walks garage-hallway → stairway (thoroughfare handoff).
  `sensor.ura_census_house` MUST NOT latch a census of 2.
- **Live:** a real second person entering MUST cause the census to reach 2
  within ~30s of the second person becoming visible.

### D-C — Re-examine existing hold/decay defaults

With D-B removing the handoff-spike source, the existing 15-min interior
hold is likely oversized. Build phase to propose a reduced default (proposal:
2-3 min interior) with the operator's sign-off, and record the pre/post
default in the release notes. `CENSUS_DECAY_STEP_SECONDS` may follow.

**No new mechanism.** This is a defaults review, not a code-shape change.
Explicit non-goal: do NOT introduce a second competing temporal layer.

**Acceptance:**
- **Verify:** documented rationale for the new default in the README, with
  the pre-D-B and post-D-B expected timing curves.
- **Live:** one person walking through the house and stopping (real dwell)
  keeps the census stable — no false dropouts during typical mmWave
  still-body gaps.

### D-D — Cross-correlate remains byte-identical

`_cross_correlate_persons` formula unchanged:
`unidentified_count = max(0, camera_total − identified_count)`. The input
is corrected upstream by D-A + D-B; the line stays identical. Debug
assertion: `camera_total <= sum(area_maxes) + sum(unassigned_fresh)`.

**Acceptance:**
- **Test:** `test_census_unidentified_never_exceeds_area_dedup_total`.
- **Live:** with the house genuinely empty and all tracked persons away,
  `unidentified_count == 0` reproducibly — the v4.7.14 AWAY veto path
  re-verifies.

### D-E — Sensor attributes for observability

Attributes on `sensor.ura_census_house`:
- `area_contributions: dict[str, {max_count, contributing_entity}]` (D-A).
- `pending_peak: {value, seconds_remaining} | null` (D-B).
- `raw_pre_dedup_sum: int` — the old summing shape, retained as a diagnostic
  to measure D-A's impact in the field.

**Acceptance:**
- **Live:** attributes visible in Developer Tools → States within one
  census cycle post-restart.

### D-F — Tests + baseline diff

Extend `quality/tests/test_camera_census.py` + `test_census_v2.py`.
Per Tier 2-DB Review C protocol: behavioral fixture extracted from
production source; real per-site source mutation on (a) same-area max,
(b) sustain-latch gate, (c) cross-correlate call. Each mutation must
break at least one specific test.

**Acceptance:**
- **Test:** full suite green; new tests fail when their protected site
  is mutation-bypassed.

---

## Deferred / Stretch / Out of Scope

### D-DEFER-1 — Explicit cross-area overlap groups (deferred)

Revisit `CONF_CAMERA_OVERLAP_GROUPS` (or an area-grouping override) ONLY
if live validation after D-A + D-B + D-C reveals a residual over-count
from cameras in DIFFERENT HA areas continuously seeing the same physical
spot. Not observed to date; not worth the config surface pre-emptively.

### S-1 — Per-input freshness TTL (stretch, gated)

Add `CENSUS_INPUT_TTL_SECONDS` + freshness filter ONLY if a verified
consumer path is found where a stuck-reporting sensor (state stops updating
but continues to read `on` / `count>0`) can pin an inflated count past
D-B's sustain window (unlikely: sustain-latch prevents NEW inflated
latches, and downward moves are instant, so a sensor that goes stuck
AFTER a legit peak decays naturally). Not built without a concrete repro.

### S-2 — Transit-transfer suppression (stretch)

Reuse `transit_validator.py` per-room checkpoint sightings: if camera A
in area X cleared within `TRANSIT_CHECKPOINT_WINDOW_SECONDS` of camera B
in area Y firing, treat as transfer not increment. Only pursued if mixed
scenes still over-count after D-A/B/C. Requires read-only coupling into
the transit validator's state; scope carefully.

### Out of Scope (unchanged from prior draft)

- Room-tier occupancy dedup (`CONF_DISABLE_CAMERA_PRESENCE` surface).
- Property/exterior census (`_calculate_property_census`).
- Frigate MQTT track_id dedup.
- Face-recognition–based identification of unidentified guests.
- Anomaly-emit suppression (already shipped in v4.6.3.3).
- Any change to `HouseState` inference logic itself.

---

## Tier Classification: Tier 2-DB (3 framing-disjoint reviews)

**Why elevated (standing policy per CLAUDE.md):** regression-prone,
cross-coordinator ripple. `unidentified_count` is a shared primitive
consumed by:
1. HouseState AWAY veto (v4.7.14) — no timing constraint.
2. Guest gate arming + GUEST-state persistence (v4.6.2.2) — 300s
   persistence, tolerant of 15s sustain.
3. Presence confidence surfaces + dashboard attributes.

Three framings:

- **Review A — local correctness:** area-max grouping; sustain-latch
  state machine (pending → latched → decayed); ordering (availability →
  area-dedup → sustain → hold/decay → aggregate); downward moves stay
  instant; behavior when no camera has `area_id` (graceful fallback).
- **Review B — cross-coordinator + veto integrity:** every consumer of
  `unidentified_count` tolerates the 15s sustain delay; v4.7.14
  acceptance test still passes; guest-gate 300s persistence unchanged;
  AWAY-veto regression guard exercised with unidentified-guest walk-through
  (must reach `unidentified_count=1` within ~15s and block the veto).
- **Review C — new surfaces + test authority:** `CENSUS_PEAK_SUSTAIN_SECONDS`
  const wiring; new sensor attributes round-trip; behavioral fixture
  extracted from production; per-site source mutation proves each
  load-bearing site is tested.

Escalate to **Tier 3** and add Reviewer D if Reviewer C's mutation pass
leaves the suite green on any load-bearing site, OR if D-C proposes a
hold-default reduction the operator flags as high-blast-radius.

---

## Live Validation Path (post-deploy)

1. **Handoff (sustain-latch working):** operator walks
   garage-hallway → stairway (or any documented thoroughfare pair).
   `sensor.ura_census_house` MUST NOT latch a census of 2. Read
   `pending_peak.seconds_remaining` mid-walk to see the pending latch
   time out.
2. **Real second person (sustain-latch not over-shooting):** a second
   person enters and stays visible. Census MUST reach 2 within ~60s
   worst-case. B-H1 note: `SCAN_INTERVAL_CENSUS = 30s` (`const.py:963`)
   plus a 30s event-debounce means the 15s sustain gate is sampled at
   30s resolution. Worst case: a real second person becomes visible
   ~1s AFTER a periodic tick — the next tick is ~30s later (sustain
   window starts), the tick after that is ~30s later still (sustain
   window elapsed, peak promotes). Best case is ~15-30s. The event-
   driven path (state change on any interior camera) also fires the
   compute cycle, so an event-triggered sample between the two
   periodic ticks will promote earlier when a pending latch is due.
   The prior "within ~30s" figure was optimistic; ~60s is the honest
   worst case at current cadence.
3. **Same-area dedup:** operator walks into an area with two cameras
   (operator to name at build time). `area_contributions[<area>].max_count
   == 1`; `raw_pre_dedup_sum` shows the old-shape 2 for comparison.
4. **AWAY-veto regression guard:** the house genuinely empties, all
   tracked persons away, no unidentified. `unidentified_count == 0`,
   `sensor.ura_presence_coordinator_presence_house_state == AWAY`.
5. **Guest regression guard:** an unknown person (BLE-absent) walks
   through and stays. `unidentified_count` reaches 1 within ~15s (the
   sustain window) and the AWAY veto stays blocked. Guest gate arms
   after the existing 300s persistence — unchanged from today.
6. **Write back to README:** replace prospective "Live" bullets with a
   `Validated <date>` PASS/FAIL table citing observed attribute values
   (per the mandatory ceremony).

---

## Top Risks

1. **Sustain window too long for guest detection.** 15s is chosen to
   comfortably exceed handoff-tail durations (~5-15s observed) but stay
   well below guest-gate's 300s persistence. If field data shows tails
   >15s, tune the const — no config surface disturbed.
2. **A camera missing `area_id` in the entity registry.** D-A degrades
   gracefully (unassigned camera contributes individually) but the setup
   diagnostic must log loud enough for the operator to spot. Build phase
   asserts every configured interior camera resolves to a non-null
   `area_id`.
3. **D-C default reduction may prematurely drop the census through
   mmWave still-body gaps.** Operator sign-off required on the new default;
   the release notes must state the pre/post value and the expected
   dwell tolerance.
4. **Sustain-latch state not restored across reload.** Pending state
   lives in RAM; a reload resets the pending timer. Acceptable — worst
   case is a legitimate increase's latch is re-timed by 15s post-reload.
   Documented, not fixed.
