# PLANNING — Fan-recheck ↔ D2 precedence deadlock fix

**Card:** FAN-RECHECK-D2-DEADLOCK-1 (folds in FAN-RECHECK-SLEEP-VETO-SCOPE-1)
**Date:** 2026-08-19
**Tier:** **Tier 2-DB** (three framing-disjoint reviews + live validation)
**Branch:** develop → feature branch at build time
**Type:** Cross-coordinator (room ↔ presence) trust-hierarchy bug — regression-prone

---

## 0. TL;DR

The fan-interference recheck (`FanRecheckManager`) has **never vacated a
fan-ghosted empty room in production**. Root cause is a precedence
DEADLOCK between two occupancy-trust mechanisms that were built as
peers with mutual guards, but whose guards do not compose:

- **D2 mmwave-fan-demotion** (`coordinator.py:3320-3455`,
  `MMWAVE_FAN_CORROBORATION_ENABLED = True` default, `const.py:805`;
  `D2_PIR_STALENESS_MULTIPLIER = 2`, `const.py:586`) sets
  `data[STATE_OCCUPIED] = False` on the same room the recheck targets.
- The **recheck** requires `data["occupied"] is True` to leave `idle`
  (`presence_fan_recheck.py:378-379`).
- D2's "defer to recheck" guard only fires when the recheck is
  **already** non-idle (`coordinator.py:3370-3402`).

So on every tick: D2 pre-empts occupancy → recheck sees
`not_occupied` → recheck stays `idle` → D2's guard never trips → D2
demotes again next tick. Live proof (Living Room, since-boot):
`fan_recheck_veto_counts = {not_occupied: 1}`, `eval_count = 1`,
`fan_recheck_last_attempt_iso = 2026-08-13` (never vacated).

Fold-in: the hard `HouseState.SLEEP` veto
(`presence_fan_recheck.py:373-375, 854-856`) suppresses the recheck
house-wide during sleep. Even after the deadlock is broken it will
re-suppress the exact rooms this cycle targets (Study A, Living Room —
both non-bedroom, fans on through sleep by comfort logic). Scope must
be per-room using the v4.7.13 keep-on predicate
(`hvac_fans.py:1205-1209`), NOT house-wide.

D3 (secondary hardening): the per-room driver loop in
`presence.py:6893-6908` shares one `except → DEBUG`, so a single room
raising in `on_room_tick` silently skips every room after it.

---

## 1. Institutional context verified

### Greps run + results (REUSED / NEW)

| Proposed surface | Result |
|---|---|
| D2 demotion arithmetic | **REUSED** — `coordinator.py:3320-3455`, `MMWAVE_FAN_CORROBORATION_ENABLED` (`const.py:805`), `D2_PIR_STALENESS_MULTIPLIER` (`const.py:586`) |
| Recheck eligibility predicate | **REUSED** — `presence_fan_recheck.py:339-504` (9-gate) |
| Recheck state accessor (`fr_mgr.get_room_state`) | **REUSED** — already called at `coordinator.py:3375-3378`; the D2 defer-to-recheck point of contact is live |
| Keep-fan-on-through-sleep predicate | **REUSED** — bedroom night-trust block `hvac_fans.py:1205-1209` (`room_type == ROOM_TYPE_BEDROOM` + `FAN_TRUST_STATES`, `hvac_const.py:645`); D0-managed-fan audit §Q2 confirmed non-bedroom rooms skip this block |
| Recheck "recheck-eligible" query on the manager | **NEW** — the API currently exposes `get_room_state(room_name)` only; a `is_recheck_eligible(room_name)` (or equivalent read-only probe) is required so D2 can defer BEFORE arming, not only once armed. Nothing equivalent found in `presence_fan_recheck.py`. |
| Per-room exception guard in the fan-out loop | **NEW** — current single-`try` wraps whole loop (`presence.py:6893-6908`); no per-room guard exists |
| Scoped sleep-veto knob | **REUSED shape** — pattern is the same as existing `CONF_ROOM_FAN_RECHECK_ENABLED` per-room switch. The predicate itself (`room_type == BEDROOM AND house_state in FAN_TRUST_STATES AND fan on-hold`) is reused from `hvac_fans.py:1205-1209`; no new module constant needed unless we expose an operator kill (see knob ladder §7) |

### Prior planning docs / audits consulted (full read)

- `docs/planning/AUDIT_fan_recheck_bug_hunt.md` — Findings A/B/C/D; established D2-starves-recheck as the high-confidence hypothesis and identified the `_FakeRoomCoord` test-authority defect.
- `docs/planning/AUDIT_fan_recheck_not_clearing.md` — CONFIRMED house-wide SLEEP veto blocks the two target rooms; scope-to-keep-on rooms recommended; also home_night-too-short case (fixed as a side-effect of the SLEEP-scoping).
- `docs/planning/AUDIT_fan_recheck_managed_fan_d0.md` — D0 go/no-go: both target fans are MANAGED (`FanController._room_fans`); veto fix actuates as-is; Screek is observed via `presence_sensors` = `CONF_MMWAVE_SENSORS`.
- `docs/planning/AUDIT_fan_recheck_second_bug_and_transition_gate.md` — Ruled out the "occupancy_source precedence second bug"; established that vetoes leave no diagnosable trace (observability gap — flagged for a separate cycle, not scoped here).
- Referenced in-repo but not re-scoped by this cycle: `docs/planning/PLANNING_fan_trust_state_extension.md` (v4.7.13 keep-on contract — must be preserved).

### Design docs read

- `docs/Coordinator/presence.md` (relevant sections on fan-interference and recheck lifecycle).
- `docs/Coordinator/hvac_fans.md` (`_evaluate_temp_fan` bedroom night-trust block, sleep policy speed cap).

### Memory bodies pulled

- `project_v4_7_13_bedroom_fan_trust.md` — the sleep-veto invariant this cycle must preserve.
- `feedback_hollow_test_anchors.md` — direct precedent for the mandatory test-authority requirement in §6.
- `feedback_suppression_needs_discharge.md` — informs the D0 window sizing (a suppression must have a discharge; the recheck IS D2's discharge).
- `feedback_measure_before_build.md` — motivates the D0 recorder probe (§4).

### Code locations surveyed end-to-end

- `custom_components/universal_room_automation/coordinator.py:3057-3110` (occupancy source production), `:3320-3465` (D2 block), `:4548-4550` (ring append), `:4578-4609` (`apply_fan_recheck_release`).
- `custom_components/universal_room_automation/domain_coordinators/presence_fan_recheck.py:1-1050` (full manager).
- `custom_components/universal_room_automation/domain_coordinators/presence.py:2688-2740, 4687-4700, 6890-6908` (setup + driver + per-tick fan-out).
- `custom_components/universal_room_automation/domain_coordinators/hvac_fans.py:320-397` (managed set), `:1101-1210` (sleep policy + night-trust block), `:1815-1900` (pause/restore/snapshot).
- `custom_components/universal_room_automation/const.py:580-830` (D2 + fan-recheck timing constants).
- `quality/tests/test_fan_recheck_mode2_cycle.py:220-260` (hollow `_FakeRoomCoord`).

---

## 2. Falsifiable invariant (single load-bearing property)

**INV-FR:** *Under a fan-ghosted, mmwave-sole EMPTY room whose fan is
managed by `FanController`, in any reachable house state (including
`sleep`), the recheck MUST arm, pause, observe, and VACATE the room
within a bounded time T (upper-bounded by
`ARM_DELAY_S + SPINDOWN_S + WINDOW_S + one 60 s driver tick +
D0-measured decay margin`). Conversely, under a genuinely-occupied
room (any of: motion within its motion timeout, BLE-trustworthy phone
in-room, camera-person, mmwave that survives a full pause window), the
recheck MUST NOT vacate.*

Falsification observations (D reviewer must break these or accept):

- INV-FR-A (must arm): a fixture that drives a real
  `UniversalRoomCoordinator` occupancy tick for a fan-ghosted empty
  mmwave-sole room (D2 bar met) sees `fan_recheck_state` transition
  `idle → armed` within one 60 s driver tick.
- INV-FR-B (must vacate): with mmwave decaying inside the pause
  window, outcome is `vacated` AND `apply_fan_recheck_release` runs
  AND `data[STATE_OCCUPIED]` reads False AND
  `data[STATE_OCCUPANCY_SOURCE]` reads `fan_recheck_release`.
- INV-FR-C (must preserve): with mmwave sustained through the pause
  window OR with a trustworthy in-room BLE phone, outcome is
  `occupied_confirmed`, room stays occupied, D2 does NOT pre-empt
  during the arm window.
- INV-FR-D (must not house-freeze): the same INV-FR-A/B holds with
  `house_state = sleep` for a non-bedroom / non-keep-on room; INV-FR-C
  holds with `house_state = sleep` AND `room_type = bedroom` (the
  v4.7.13 contract survives).

D's reachable-config repro requirement: every claimed violation must
be produced from legal config values (no synthesised state that a
config-flow validator would reject).

---

## 3. D1 — Resolve the D2 ↔ recheck precedence deadlock (primary)

### 3.1 Design options considered

**Option (a) — D2 defers to recheck for recheck-eligible rooms
(RECOMMENDED).** Reverse the guard direction: D2 asks the recheck
manager "is this room recheck-eligible right now?" BEFORE demoting.
If yes, D2 yields for that tick; the recheck arms, pauses, tests.
Recheck is now the first-line adjudicator for the exact rooms it was
built for; D2 remains the backstop for rooms the recheck cannot arm
(rate-capped, `trust_sensors_off`, `no_fan_on`, `ble_l1`,
`high_still_risk`, `no_person_coord`, etc.). The current
`recheck_in_flight` guard is kept as a second layer so an in-flight
cycle is never pre-empted mid-window.

- Pros: minimal blast radius; preserves both mechanisms; recheck runs
  when it *can*, D2 runs when it *must*; the "backstop for
  ineligible" role that D2's own comment already claims
  (`coordinator.py:3319-3323`) becomes literally true.
- Cons: adds one read-only API on `FanRecheckManager`
  (`is_recheck_eligible(room_name) -> bool`) — a NEW surface. Must not
  mutate manager state.
- Risk: eligibility drift between the deferral moment and the
  next-tick arm; mitigated by (i) D2's second-tick re-evaluation
  (deferrals cost at most one tick per non-armable transition) and
  (ii) explicit non-mutating contract on the eligibility probe.

**Option (b) — unify the two mechanisms behind one fan-ghost
adjudicator.** Larger rewrite; deletes D2's independent code path
into a `FanGhostAdjudicator`. Better long-term shape; substantially
higher blast radius (D2 has its own boot-settle, debounce,
motion-sensors-present, house-state-allows, PIR staleness, tracker
hold-clear side-effects that would need to move) and outsizes a
Tier-2-DB cycle. Parked as a future refactor if fusion becomes
warranted; the option (a) fix does not preclude it.

**Option (c) — hold occupied through the recheck's arm+pause window.**
Requires D2 to *see* `occupied=True` continuously across the arm delay
(currently 60 s) plus the pause window (~90 s). This means either D2
runs on stale data (correctness risk — D2 is designed to demote when
its bar is met) or occupancy is artificially latched (violates the
truth-preserving invariant D2 was built to defend). The mmwave-fan
demoted room is genuinely mis-attributed as occupied; latching that is
a step backwards. Rejected.

### 3.2 Recommended: Option (a) — D2 defers to recheck when
recheck-eligible

#### 3.2.1 New API on `FanRecheckManager`

Add a read-only, side-effect-free probe:

```python
def is_recheck_eligible(self, room_name: str) -> bool:
    """Return True iff a periodic tick RIGHT NOW would arm this room.

    Does NOT mutate state (no ctx creation, no timers scheduled, no
    _veto counter increments, no ring reads that alter cadence). Safe
    to call from the room coordinator's own _async_update_data.
    """
```

Implementation: extract the current `_is_eligible` predicate into a
pure-function evaluator that (a) is called by both `on_room_tick`
(existing path, still increments counters) and (b) is called by
`is_recheck_eligible` (new path, counter-free). The counter-free path
MUST NOT touch `self._veto_counts` or `self._eval_counts` or any
`ctx.*` attribute — this is enforced by passing an inert "record"
sink into the shared evaluator.

#### 3.2.2 D2 defer-to-recheck edit

In `coordinator.py:3369-3402`, extend the existing `recheck_in_flight`
guard block: before applying demotion, ALSO check
`fr_mgr.is_recheck_eligible(room_name)`. If either
`recheck_in_flight` OR `is_recheck_eligible` is True, skip demotion
this tick. Emit an existing-style debug line
(`fan-recheck-defer:eligible` vs `fan-recheck-defer:in-flight`) so the
observability gap does not deepen — both branches distinguishable.

#### 3.2.3 Discharge / bounded time

Without the fix: recheck never arms (unbounded — observed 5+ days).
With the fix: on any tick where D2's bar is met AND recheck is
eligible, D2 yields; within ≤60 s the recheck arms
(`_periodic_inference` cadence, `presence.py:2688-2692`); within
`ARM_DELAY_S (60) + SPINDOWN_S (30) + WINDOW_S (60) = 150 s`
(non-bedroom factor 1.0) the recheck concludes. Upper bound T on
INV-FR:

```
T = 60s (next driver tick) + ARM_DELAY_S + SPINDOWN_S + WINDOW_S
  + D0-measured post-fan-off mmwave decay margin
  ≤ 60 + 60 + 30 + 60 + <D0>
```

D0 (§4) chooses whether SPINDOWN_S/WINDOW_S remain at defaults or need
adjustment; the bound is stated in units so it survives constant
retuning.

#### 3.2.4 Backstop preservation

D2 must still fire (unchanged behavior) when the recheck is NOT
eligible — the enumerated ineligibility reasons listed in §3.2.1 above.
The `_still_armed_eligible` re-check at `presence_fan_recheck.py:840`
already covers "eligibility drifted during ARM_DELAY_S"; on that
drift, `_enter_cooldown` runs, `is_recheck_eligible` will return False
on subsequent ticks (cooldown veto), and D2 resumes fire as backstop.

---

## 4. D0 — Recorder probe: per-sensor fan-off → mmwave-clear lag

**Trigger:** Suppression-needs-discharge — the pause window IS D2's
discharge. Its size must be evidence-based, not assumed. Living Room
Screek cleared ~6 min after fan-off; causality is unproven (decay vs
still person vs HVAC vs coincidence). Current
`SPINDOWN_S + WINDOW_S = 90 s` may or may not cover real per-sensor
decay for the affected sensors (Zigbee mmwave at Study A, Screek L13
at Living Room).

**Scope:** read-only recorder probe over ≥7 days of existing history
for the fan-ghosted rooms in production (target set: Study A, Living
Room, plus 2-3 other rooms whose mmwave has co-fluctuated with fan
on/off). Per (fan, mmwave) pair, extract every fan-off edge and the
next-following mmwave-off edge on the SAME sensor; report per-sensor
distribution (p50 / p90 / p99 / max) of the lag, plus a flag for
"never cleared before the fan turned back on" (dominated by real
occupancy — legitimate exclusion).

**Deliverable:** `docs/planning/AUDIT_fan_off_mmwave_decay_probe.md`
with the manual per-sensor table + recommended `WINDOW_S` (either
"defaults are adequate" with p90 evidence, or a proposed new value
grounded in the measured distribution).

**Gate:** D1's INV-FR bound (§2) is only signed off after D0 is in
hand; if D0 shows p90 decay > current `WINDOW_S`, the fix bundle
includes a `DEFAULT_FAN_RECHECK_WINDOW_S` change (module constant per
knob ladder §7) BEFORE ship. Do NOT build D1's tests against
un-measured defaults.

**Non-goal:** D0 does NOT gate D1's code change (deadlock resolution
is independent of window sizing). D0 gates the *tuning* of the pause
window and the FIX-side value of T.

---

## 5. D2 (fold-in) — Scope the SLEEP veto to keep-fan-on rooms

Once D1 unblocks arming, the house-wide `HouseState.SLEEP` veto
(`presence_fan_recheck.py:373-375, 854-856`) re-suppresses the exact
non-bedroom rooms this cycle targets during the ~10-hour sleep window.
Preserve the v4.7.13 contract (bedroom fans stay running through
sleep; recheck must not pause them) by narrowing scope:

**Change:** replace the unconditional `house_state == SLEEP → veto`
with a room-scoped predicate that reuses the SAME condition
`hvac_fans.py:1205-1209` uses to hold bedroom fans on:

```
if (house_state in FAN_TRUST_STATES  # (home_night, sleep, waking) — hvac_const.py:645
    and room_fan is not None
    and room_fan.room_type == ROOM_TYPE_BEDROOM
    and room_fan.is_on):
    -> veto sleep_state
```

Apply symmetrically to both `_is_eligible` (:373-375) and
`_still_armed_eligible` (:854-856) so an in-flight bedroom cycle is
correctly aborted at the sleep edge.

**Access path to `room_fan.room_type`:** through the existing merged
config (`_merged_config`) — `room_type` is already read at
`presence_fan_recheck.py:450`. `hvac_fans.py`'s `is_on` fan predicate
is not required (the recheck already gates on `no_fan_on` at
`:402-404`); the room_type + `FAN_TRUST_STATES` conjunction is
sufficient to preserve the v4.7.13 contract.

**Sequence:** D2 (this fold-in) is a code-level rider on D1. Ship
together — scoping sleep before deadlock is fixed changes nothing
observable, and fixing deadlock without scoping sleep leaves the
target rooms still stuck during the sleep window.

---

## 6. D3 — Per-room exception guard in the fan-out loop

At `presence.py:6893-6908`, the `for entry in async_entries(DOMAIN)`
iteration sits inside ONE `try/except → DEBUG`. If `on_room_tick`
raises for room N, rooms N+1..M are silently skipped that tick, at
default log level. Fix:

```python
if self._fan_recheck_manager is not None:
    for entry in self.hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
            continue
        room_coord = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if room_coord is None or not hasattr(room_coord, "entry"):
            continue
        try:
            self._fan_recheck_manager.on_room_tick(room_coord)
        except Exception:  # noqa: BLE001 — per-room isolation
            _LOGGER.warning(
                "FanRecheck: on_room_tick failed for room=%s (isolated)",
                getattr(room_coord, "room_name", entry.entry_id),
                exc_info=True,
            )
```

Log level raised to WARNING (visible at default) and per-room isolated
so one room's raise cannot skip its siblings. This is a fragility
fix, not a functional fix — Tier-2-DB Review B should still trace it
for lifecycle safety (does an exception here already have a downstream
side-effect the caller relies on? Grep confirms `on_room_tick` returns
None and has no downstream contract; safe to isolate).

---

## 7. Knob ladder placement

| Knob | Value | Rung | Rationale |
|---|---|---|---|
| `is_recheck_eligible` API (new) | — (function, not a knob) | N/A | Read-only accessor; no configuration surface. |
| SLEEP-scope predicate (D2 fold-in) | Hard-coded to `room_type == BEDROOM AND is_on` | **Rung 1 (module code)** | Preserves v4.7.13 contract; changing it requires review. No operator use case for tuning per-room "should the recheck run during sleep for this specific room". If future data shows a common-area room where the recheck should be sleep-vetoed, add a per-room switch then (deferrable). |
| `DEFAULT_FAN_RECHECK_WINDOW_S` (potential D0-driven change) | Current default in `const.py`; possibly increased | **Rung 1 (module constant)** | Safety-adjacent: too short → false vacates; too long → excessive pauses. Reviewed change only. |
| D3 per-room log level (WARNING) | Fixed | **Rung 1** | Not operator-tunable. |
| Existing `switch.<room>_fan_recheck` (per-room enable) | Already exists | **Rung 3** (Switch entity) | Kill-switch for the whole feature per-room. No change required. |
| Master `switch.ura_presence_coordinator_fan_recheck` | Already exists | **Rung 3** | House-wide kill. Unchanged. |

No new operator-visible knobs proposed by this cycle. If Reviewer A/D
argues for a per-room "recheck-during-sleep" override, park it as a
follow-up — evidence-gated on a real non-bedroom room where sleep
suppression is desired.

---

## 8. Test authority — MANDATORY (Hollow-anchor prevention)

The `_FakeRoomCoord` at `quality/tests/test_fan_recheck_mode2_cycle.py:224-250`
hardcodes `occupancy_source="mmwave"` and `occupied=True` in its `data`
dict. This is WHY the D2 deadlock shipped invisibly and stayed
invisible for 5+ days. **The plan REQUIRES replacing it** — a hollow
re-anchor for this cycle is unacceptable.

**Replacement fixture (build-side deliverable):**

- Drive a real `UniversalRoomCoordinator` (or the closest usable
  in-suite construction) through `_async_update_data` with configured
  mmwave/motion/BLE inputs so that `data[STATE_OCCUPIED]` and
  `data[STATE_OCCUPANCY_SOURCE]` are PRODUCED by the real code path
  (`coordinator.py:3057-3110`), not hand-set.
- Wire the room into a live `FanRecheckManager` AND expose the D2
  block (`coordinator.py:3320-3455`) — the fixture must exercise BOTH
  mechanisms so the deadlock path is reachable.
- Test bodies drive the *scenario* (fan on, mmwave latched, PIR
  stale, no BLE, no motion), NOT the internal states.

**Mandatory acceptance tests (build must ship these):**

1. **T-DEADLOCK-FIRES-BEFORE-FIX (regression sentinel):** on the CURRENT
   code (pre-fix), the fixture must reproduce the deadlock — assert
   `fan_recheck_state == "idle"` AND `data[STATE_OCCUPIED] == False`
   AND `data[STATE_OCCUPANCY_SOURCE] == OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED`
   after N ticks. This test is committed marked
   `@pytest.mark.xfail(strict=True, reason="deadlock — cleared by D1")`
   in the pre-fix commit, then FLIPPED to a passing "post-fix vacates"
   assertion in the fix commit. This guarantees the test was really
   red before the fix and really green after — the discriminator
   Producer/Consumer requires.
2. **T-VACATES (INV-FR-A + B):** after D1, driving the same scenario
   asserts the room progresses `idle → armed → paused → vacated`
   AND `apply_fan_recheck_release` was called AND
   `data[STATE_OCCUPIED] == False` with source
   `fan_recheck_release`, within the T bound from §3.2.3.
3. **T-PRESERVES-OCCUPIED (INV-FR-C):** identical fixture with mmwave
   sustained through the entire pause window → outcome
   `occupied_confirmed`, room stays occupied,
   `apply_fan_recheck_release` NOT called.
4. **T-BLE-VETO (INV-FR-C):** identical scenario + trustworthy BLE
   phone in-room → recheck vetoes `ble_l1`, D2 fires as backstop
   (behavior unchanged from today).
5. **T-SLEEP-NON-BEDROOM (INV-FR-D):** `house_state = sleep`,
   `room_type = generic`, fan on, mmwave latched empty → recheck
   arms and vacates (D2 fold-in unblocks sleep for non-bedroom).
6. **T-SLEEP-BEDROOM-PRESERVED (v4.7.13 contract):** `house_state =
   sleep`, `room_type = bedroom`, fan on → recheck vetoes
   `sleep_state`; bedroom fan never paused. This test MUST fail if a
   future edit widens the SLEEP scope beyond bedrooms.
7. **T-D3-ISOLATION:** inject a room whose `on_room_tick` raises;
   assert a downstream room in the same tick is STILL evaluated.

**Mutation-anchoring (Tier-2-DB Review C requirement):** each test
above must be anchored by a real production-source mutation. E.g.
neutering the `is_recheck_eligible` deferral in D2 must make T-VACATES
fail; neutering the SLEEP-scope predicate must make T-SLEEP-NON-BEDROOM
fail. Reviewer C runs those mutations against the real files
(pyc-safe: `PYTHONDONTWRITEBYTECODE=1`, `find . -name '__pycache__' -exec rm -rf {} +`).

---

## 9. Acceptance criteria (discriminating — must distinguish fix from plausible failures)

Per Producer/Consumer discriminating rule: state what an observation
looks like UNDER THE FIX vs UNDER A PLAUSIBLE DIFFERENT FAILURE.

### D1 — deadlock resolution

- **Verify (unit):** T-DEADLOCK-FIRES-BEFORE-FIX xfails on the pre-fix
  commit AND passes-as-vacate on the fix commit. (Under a fix that
  merely re-labels but doesn't unblock: T stays xfail — different
  observation.)
- **Verify (unit):** T-VACATES passes. (Under an off-by-one deferral —
  D2 defers only when recheck is already in-flight, not when eligible
  — this test stays failing: different observation.)
- **Verify (unit):** T-PRESERVES-OCCUPIED passes. (Under an overly
  aggressive fix that vacates all mmwave-sole rooms including truly
  occupied ones, this test fails: different observation.)
- **Sensor:** `sensor.<target_room>_<target_room>_fan_recheck_state`
  attribute `fan_recheck_last_outcome` reads `"vacated"` (not
  `"occupied_confirmed"`) for at least one target room within one
  sleep-cycle post-deploy. (Under "arms but never vacates" — decay
  window too short — attribute reads `occupied_confirmed`: different.)
- **Sensor:** for the target room, `fan_recheck_veto_counts` shows
  a DECREASE in `not_occupied` share vs the previous 24h (not zero —
  D2 still backs up ineligible tick windows).
- **Live:** `binary_sensor.<target_room>_occupied` reads `off` with
  `occupancy_source = fan_recheck_release` at least once per
  observation cycle when the room is genuinely empty and fan is on.
  (Under D2-only preserved behavior, the source would be
  `mmwave_fan_demoted` — different observation.)
- **DB:** `ura_activity_log` shows ≥1 `fan_recheck_outcome` row with
  `details_json.outcome == "vacated"` for the target rooms within the
  post-deploy soak. (This is the first time such a row has ever
  existed for these rooms — historic count is 0.)

### D2 fold-in — sleep-scoped veto

- **Verify (unit):** T-SLEEP-NON-BEDROOM passes; T-SLEEP-BEDROOM-PRESERVED
  passes.
- **Sensor:** during the sleep window, a bedroom room's
  `fan_recheck_state` remains `idle` with veto count
  `sleep_state` incrementing (contract preserved). A non-bedroom
  target room's state exits `idle` during sleep.
- **Live:** no bedroom fan is paused by the recheck across a full
  sleep window (grep `_LOGGER` for `FanRecheck.*paused` × bedroom
  rooms == 0). (Under a bad scope-widening this shows non-zero.)

### D3 — per-room isolation

- **Verify (unit):** T-D3-ISOLATION passes.
- **Live:** at DEBUG level, a synthetic `on_room_tick` failure in one
  room does NOT stop sibling rooms from evaluating that tick.

### D0 — probe

- **Deliverable:** `AUDIT_fan_off_mmwave_decay_probe.md` committed
  with per-sensor decay distribution + recommended `WINDOW_S`.
- **Gate:** if p90 > current default `WINDOW_S`, plan includes a
  const change; if p90 ≤ default, note "defaults adequate" with
  evidence table. NO code changes to timing constants without this
  evidence.

---

## 10. Non-goals

- **Not** fixing the observability gap that
  `AUDIT_fan_recheck_second_bug_and_transition_gate.md` flagged
  (surfaced-veto-counts / raise-log-level for the fan-out). D3 raises
  the fan-out log level as a side effect, but exposing veto counts on
  a sensor is a separate cycle (`FAN-RECHECK-OBSERVABILITY-1`).
- **Not** unifying D2 + recheck into a single fan-ghost adjudicator
  (Option (b) — parked).
- **Not** re-tuning `ARM_DELAY_S` / `SPINDOWN_S` (only `WINDOW_S`,
  and only if D0 requires).
- **Not** widening the SLEEP scope to allow bedroom recheck; the
  v4.7.13 contract is explicitly preserved.
- **Not** adding a "recheck-during-sleep for this specific
  non-bedroom room" per-room switch (deferrable; add only if a
  concrete room requires it).
- **Not** touching the fan-transition creation gate
  (`coordinator.py:2843-2923`) — validated as correctly scoped in the
  transition-gate audit; a separate sustained-shake track owns any
  work there.
- **Not** re-categorizing Living Room's Zigbee mmWave out of
  `motion_sensors` (the latent precedence gap noted in the D0 audit —
  parked as a follow-up card).

---

## 11. Tier classification — Tier 2-DB rationale

**Why Tier 2-DB (three framing-disjoint reviews):**

- Trust-hierarchy ripple across presence ↔ hvac_fans ↔ coordinator —
  the exact "trust-hierarchy ripple" the operator-elevated Tier 2-DB
  policy calls out.
- Two occupancy-trust mechanisms with mutually-recursive guards; the
  cycle changes their precedence. Single-frame review will converge
  on either the D1 API surface OR the sleep-scoping OR the fixture
  authority — historically each frame surfaces findings the others
  miss.
- Test-authority defect (hollow `_FakeRoomCoord`) is a load-bearing
  part of the fix; Review C (new-surfaces / fixture-authority) MUST
  run.
- v4.7.13 keep-on contract is a live invariant that this cycle must
  preserve while changing the surrounding code — Review B
  (integration / state-machine integrity) must trace it.

**Recommended framings:**

- **Review A — local correctness + edge cases.** The new
  `is_recheck_eligible` predicate is truly side-effect-free; the D2
  defer condition composes correctly with the existing
  `recheck_in_flight` guard; the SLEEP-scope predicate evaluates
  correctly for every combination of (`house_state`, `room_type`,
  `is_on`).
- **Review B — cross-coordinator integration + state-machine
  integrity.** No double-arm hazard when D2 flip-flops across a tick
  boundary; `_still_armed_eligible` still aborts on sleep edge for
  bedrooms; v4.7.13 keep-on contract byte-identical for bedrooms;
  no new race between the D2 read of `is_recheck_eligible` (on the
  room's `_async_update_data`) and the recheck's own state
  transitions (on the presence 60 s tick).
- **Review C — test authority + new-surface round-trip.** The
  replacement fixture actually drives production code paths (not
  another hollow shim). The mutation-anchoring drills for each of the
  seven acceptance tests actually flip the tests red per-site (not in
  aggregate). The pre-fix xfail is real, not a stub.

**Elevation to Tier 3 declined** — this is precedence-fix work with
one load-bearing invariant (INV-FR), not a shared-primitive change
threading a value through N emission sites. If Review C's mutation
drill uncovers more than one D2-adjacent site where deferral must be
added (i.e. the fan-ghost logic has fanned out beyond the one D2
block since audit), escalate to Tier 3 at that time and add a 4th
adversarial-completeness pass.

---

## 12. Deliverables summary

| ID | Deliverable | Files touched (expected) | Ships with |
|---|---|---|---|
| D0 | Recorder probe + audit doc | `docs/planning/AUDIT_fan_off_mmwave_decay_probe.md` | Before D1 build |
| D1 | Deadlock resolution — `is_recheck_eligible` API + D2 defer | `presence_fan_recheck.py`, `coordinator.py` (D2 block) | D1+D2-foldin+D3 in one cycle |
| D2 (fold-in) | Sleep-veto scoping to bedroom keep-on rooms | `presence_fan_recheck.py:373-375, 854-856` | Same cycle as D1 |
| D3 | Per-room exception isolation in fan-out loop | `presence.py:6893-6908` | Same cycle as D1 |
| Tests | Replace `_FakeRoomCoord` + 7 acceptance tests + mutation anchors | `quality/tests/test_fan_recheck_mode2_cycle.py` (rewrite of `_FakeRoomCoord`), new test file if needed | Same cycle |
| Docs | README_v<version>.md prospective + post-live validation table | `docs/readmes/README_v<version>.md` | Deploy step + live-validation write-back |

---

*Read-only planning. No source files modified by this doc. All
`file:line` citations against `develop` at commit time.*
