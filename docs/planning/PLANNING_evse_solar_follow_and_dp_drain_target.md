# PLANNING — EVSE solar-following amp modulation + DP drain-target mis-sourcing fix

**Cycle name:** `evse-solar-follow-and-dp-drain-target`
**Tier:** **Tier 3** (operator ruling: "Tier 3 means cost in review. Code itself can be simple.")
**Threads:** `energy`
**Cards:** `EVSE-SOLAR-FOLLOW-AMPS-1` (D1, D2), `EVSE-DRAIN-PRECEDENCE-KNOB-80-1` (D3)
**Design source (do NOT relitigate):** the two card bodies (esp. `DESIGN_CLOSED_2026_08_23`,
`SIGNAL_DESIGN_FINAL_2026_08_23`, `SENSOR_DELTA_MEASURED_2026_08_23`, `SCOPE_FENCE_2026_08_23`,
`OPERATOR_ANSWERS_AND_VERIFIED_FACTS_2026_08_23`, `RE_VERIFIED_2026_08_23_card_stands_memory_was_stale`,
`SCOPING_2026_08_20_ONE_NUMBER_THREE_ROLES`, `RECOMMENDED_DESIGN_D_SPLIT_THE_ROLES`) and
`docs/planning/AUDIT_excess_solar_and_evse_prior_art.md`.
**Probes:** `scripts/probes/delta_probe.py`, `scripts/probes/skew_probe.py`.

**Revision 5 (2026-08-23) — MERGED, single source of truth.** Targeted re-review of Rev-4 (SF7-B1/B2
scope) returned DO NOT DISPATCH with 3 BLOCKING + 5 smaller items. Rev-5 patches in place:

- **BLOCKING-1:** the Rev-4 add-back snippet gated on `state.get("charging")` and
  `_get_evse_state` (`energy_pool.py:650`) has a v4.2.19 fallback at `:690-697` that sets
  `charging=True` + `power=EVSE_ESTIMATED_POWER_W` (7600 W) when the power sensor is
  unavailable but the switch is on with `status="charging"`. That fallback flag is what
  D1 point 8 forbids. Rev-3 had the same hole via `current_charging_load_w()`; Rev-4
  re-authored and walked back into it. Rev-5 gates the add-back on
  `state.get("power_source") == "sensor"`; a non-sensor read routes into the D1.3 STALE
  path (counts toward `SOLAR_FOLLOW_STALE_MAX_TICKS`, no writes), which is STRICTER than
  "add 0" — chosen deliberately because "add 0" under-draws but does not fail-safe against
  an intermittent Emporia cloud blip on a per-EVSE basis (an EVSE that is drawing but whose
  reading is stale is exactly the class we should not decide against). New test + new
  mutation drill C17f. **This is BLOCKING-1's second closure — see the new §13 "Closed
  concerns — must stay closed" register.**
- **BLOCKING-2:** the `SolarFollowController` class shape was ambiguous. Some snippets used
  bare `self._evse` / `self._paused_by_dp` / `self._stronger_peer_holds` (all
  `EVChargerController` members); others (Rev-4 add-back) implied `self._ev._get_evse_state`
  without saying so. `PoolOptimizer.__init__` (`:66-81`) holds only `hass` and entity ids —
  no `_ev`. Rev-5 pins the class as a STANDALONE controller with an injected
  `EVChargerController` reference under one attribute name `self._ev`, uses `self._ev.<attr>`
  consistently for every cross-class read, and marks private-attribute reads with
  `# noqa: SLF001` (matching the convention at `energy.py:4141`, `:4517`, `:4929`, `:5031`).
- **BLOCKING-3:** T-PEER-2's "zero writes on tick 2" assertion was NOT anchored by C17. C17
  drops the step-5 filter; on tick 2 the held EVSE re-enters ELIGIBLE and reaches step 9d
  (deadband). T-PEER-2's tick-2 fixture did not move surplus, so `A_target == A_current` →
  deadband short-circuits → zero writes fire → assertion passes under the mutation → C17
  does not falsify. Rev-5 pins the tick-2 fixture to move surplus DOWN by enough to
  overshoot the deadband and outside the up-gate: tick 1 `grid_W=-5000`, tick 2
  `grid_W=-1500`. Down-steps are uncapped (INV-SF-5), so correct code's silence is
  provably a peer-hold decision.
- **N1:** C17 + Rev-4 add-back iterate ELIGIBLE, so C17 moves both the set and the sum
  together — the denominator has no independent drill. New **C17d** (`N_eligible =
  len(_excess_solar_active)`) anchors the denominator alone. Rev-5 reframes as "disjoint
  mutations, overlapping oracles."
- **N2:** step-2b's clear-on-unresolvable path had no drill; C17b routes into 2b but 2b
  still clears. New **C17e** removes the clear branch → T-PEER-6 must fail.
- **N3:** T-PEER-5 spec now explicitly pins garage_b's own power below
  `EVSE_CHARGING_POWER_THRESHOLD` so the `add_back=0` step is discriminating (else 16 A is
  the correct answer and Rev-4's oracle collapses to Rev-3's).
- **N4:** the averaging mismatch (PRIMARY is 60 s average vs instantaneous add-back)
  belongs to **INV-SF-5**, not INV-SF-4. Rev-5 records this explicitly so a future cycle
  doesn't relax the up-gate believing INV-SF-4 covers it.
- **N5:** step 2 iterated `_original_amps` while mutating it → `RuntimeError` on first
  release + first prune. Rev-5 iterates `list(self._original_amps)` explicitly.

Rev-1..Rev-4 items preserved unchanged. **New §13 "Closed concerns — must stay closed"**
lists every previously-raised issue with its one-line invariant that keeps it shut; every
future revision diffs against that list before reporting.

---

## 0. Tier-3 elevation and framing

Three independent risks: NEW WRITER on a live cloud actuator at 1-min cadence with wrong
containment / restore / reactivity / fleet allocation / peer-hold subordination / surplus-
denominator alignment / stale-signal fallback (Rev-5 BLOCKING-1); FIVE R2 emission-site
threading in D3; silent-success failure modes on both. Tier 3.

---

## 1. Falsifiable invariants

Each: "under X, Y can never happen in ANY reachable path."

### INV-SF-1 (non-perturbation)
`SolarFollowController` emits no `switch.turn_on` / `switch.turn_off`. Writes only
`number.set_value` to a current-limit entity, only for an EVSE in `_excess_solar_active`.

### INV-SF-2 (writes only inside sessions)
Both sets empty → zero writes.

### INV-SF-3 (restore is load-bearing, restart-safe)
After removal from `_excess_solar_active` by any code path (release `:1699`, blind-window
drop `:1564`, peak clear `:1369`, restart reconciliation `energy.py:5183-5225`, or config
prune via `_prune_removed_evses`), current-limit is restored to saved `_original_amps`
(fallback `SOLAR_FOLLOW_RESTORE_AMPS=48`) within one restore tick — subject to INV-SF-7.

### INV-SF-4 (draw bounded by measured surplus over ELIGIBLE)
`ELIGIBLE = {evse_id ∈ _excess_solar_active where NOT _stronger_peer_holds(evse_id) AND
evse_id ∉ _paused_by_dp}`.
`S_eligible = -grid_W + Σ_{ELIGIBLE, power_source=="sensor"} evse_power_w`.
`Σ_{i ∈ ELIGIBLE} A_i · 240 · PHASES ≤ max(S_eligible, N_eligible · MIN · 240)`.
**Rev-5 refinement (BLOCKING-1):** the add-back sum is restricted to EVSEs whose
`_get_evse_state` returns `power_source == "sensor"` (a real reading). An EVSE with a
non-`sensor` power_source is EXCLUDED from ELIGIBLE for the tick (routes into the D1.3
STALE path); it does NOT contribute 0 to the sum while still counting in the denominator.

### INV-SF-5 (asymmetric reaction to a lagging signal)
Down-step: uncapped, one tick. Up-step: gated by `SOLAR_FOLLOW_UP_MIN_TICKS`, capped at
`SOLAR_FOLLOW_UP_STEP_A`/tick/EVSE.
**Rev-5 clarification (N4):** the primary signal `sensor.mains_vue_3_power_minute_average`
is a 60 s AVERAGE while the ELIGIBLE add-back is INSTANTANEOUS. During a ramp, `S_eligible`
can over-read for up to 60 s and the controller could ratchet upward. This is bounded by the
up-gate (`UP_MIN_TICKS × UP_STEP_A`). **INV-SF-4 is arithmetic bookkeeping; the physical
lag containment is INV-SF-5.** A future cycle relaxing INV-SF-5 must not lean on INV-SF-4
to cover the lag.

### INV-SF-6 (fleet allocation)
`A_total_target = floor(S_eligible / (240·PHASES))`; `A_per_evse = A_total_target //
N_eligible`; clamp `[MIN, MAX]`. Degenerate: all eligible hold at MIN.

### INV-SF-7 (stronger-peer subordination)
While `_stronger_peer_holds(evse_id) is True` OR `evse_id ∈ _paused_by_dp`, no write to
that EVSE and no capture. Applies to BOTH step 2a (restore) AND step 5 (modulation).
`_paused_by_dp` checked INLINE per the two-site convention `energy_pool.py:394-400`.

### INV-RELEASE-1 (D2)
Release fires only when `not conditions_met OR solcast<floor` AND streak ≥ MIN_TICKS AND
session age ≥ MIN_ON_S.

### INV-DP-DRAIN-1 / 1b / 2 / 3 / 4 (unchanged Rev-2/3/4)
See §3.D3.

---

## 2. Institutional context verified

Paths under `custom_components/universal_room_automation/domain_coordinators/`:

* `docs/planning/AUDIT_excess_solar_and_evse_prior_art.md`.
* `energy_pool.py` — `PoolOptimizer:58-160` (template shape only; `__init__:66-81` holds only
  `hass` + entity ids); `EVChargerController.__init__:186-317` (owner sets);
  `determine_excess_solar_actions:1318-1701` (release `:1685-1699` = D2);
  `determine_battery_drain_actions:1776-1959`; `_soc_envelope_admits_dp_transition:619-648`;
  `_stronger_peer_holds:383-412` (docstring says "ANY of the five" — STALE, loop returns
  six via `EV_REGISTRY.iter_peer_holds()`; SF7-L1); `_paused_by_dp` inline check at claim
  `:1621-1631`; fill-priority `_excess_solar_active` skip prior art `:2214-2219`;
  **`_get_evse_state:650`** with v4.2.19 fallback at `:690-697` setting `power =
  float(EVSE_ESTIMATED_POWER_W)` = 7600 W and `power_source = "switch_status"` when the
  power sensor is unavailable but switch is on with `status="charging"`; `power_source`
  returned at `:700-706` — Rev-5 BLOCKING-1 gates on this; `current_charging_load_w:2300-2312`
  (fleet-wide, no ELIGIBLE filter, NOT USED by D1); `_pause_dispatch_ts` /
  `_observed_off_since_pause` `:275-278`.
* `energy_pool_owners.py` — `iter_peer_holds()` = 6 owners; `persistence_kind` ∈
  {`"per_evse_bool"`, `"list"`, `"none"`}; `_paused_by_load_shed` `persistence_kind="none"`
  (`:298-300`); dict-kind owners at `:345+` are `_prune_removed_evses` participants.
* `energy_drain_precedence.py` — `evaluate_dp_transition:609-735`.
* `energy.py` — R2 sites `:4271`, `:4456`, `:4522`, `:4540`, `:4555`; R2-display `:3871`,
  `:4021`; reserve fold `:4733-4742`, `:4829-4833`; write-verify surface gate `:7587-7591`;
  R1 sites `:5842` / `:5977`; R3 site `:3752`; 10 h staleness gate `:1346`; `_KNOWN_HOOKS`
  `:1603-1612`; **`self._ev` = the `EVChargerController` instance held on EnergyCoordinator
  (`:293`); cross-class private-attribute reads take `# noqa: SLF001` at `:4141`, `:4517`,
  `:4929`, `:5031`** — Rev-5 BLOCKING-2 adopts this convention verbatim inside
  `SolarFollowController`. Live compound-load mutex (Rev-4 corrected): `:6240-6263`
  (`charge_from_grid` chokepoint, phase-label-independent), `:6290-6328` (hardware read OR
  fail-closed latch), `:6341-6365` (EV pauses before battery). Load-shed re-claim
  `:7259-7282`. DP claim-release `:5089`, `:5116`.
* `energy_battery.py` — `compose_release_floor:264` (module fn; returns
  `(release_floor: int|None, is_offpeak: bool)`; None at `:286-289`).
* `energy_const.py` — `EVSE_ESTIMATED_POWER_W = 7600` at `:827` (never in D1's control law);
  `DP_L1_RATE_THRESHOLD_KW=3.0:1359`.
* `database.py:4526-4535` — `save_evse_state` atomic for `paused_by_us` + `excess_solar_active`.
* `PLANNING_v4.7.x_APPLIANCE_SCHEDULER.md:41`.
* Memory: `project_optimizer_db_write_flood_incident_2026_06_09`;
  `project_ev_drain_precedence_cycle`; `feedback_suppression_needs_discharge`;
  `feedback_hollow_test_anchors`; `feedback_mutation_verification_pycache_staleness`;
  `RESTART-SAFETY-DOCTRINE-1`.

---

## 3. Deliverables

### D1 — SolarFollowController

**Class shape (Rev-5 BLOCKING-2 pin, superseding all prior ambiguity):**

```python
# domain_coordinators/energy_pool.py
class SolarFollowController:
    """Standalone controller with an injected reference to the pool's
    EVChargerController. Modelled shape-wise on PoolOptimizer:58-160 (save/restore
    + unavailable-keep-state) but requires cross-class reads for the peer-hold and
    per-EVSE state helpers that live on the EVChargerController.
    """
    def __init__(
        self,
        hass: HomeAssistant,
        ev: EVChargerController,
        current_limit_entities: dict[str, str],  # {evse_id: entity_id}
        solcast_next_hour_entity: str | None = None,
    ) -> None:
        self.hass = hass
        self._ev = ev
        self._current_limit_entities = current_limit_entities
        self._solcast_next_hour_entity = solcast_next_hour_entity
        self._original_amps: dict[str, float] = {}       # per-EVSE saved value
        self._deferred_restore_evses: set[str] = set()   # gauge
        self._up_streak_ticks: dict[str, int] = {}       # per-EVSE up-gate
        self._writes_this_hour: dict[str, int] = {}      # write-budget bucket
        self._capture_rejected_low: int = 0              # monotone counter
        self._stale_ticks: int = 0                       # D1.3 stale counter
        self._verify_fails: int = 0
```

**Attribute access convention inside this class:**
- `self.hass`, `self._ev`, `self._current_limit_entities`, `self._original_amps`,
  `self._deferred_restore_evses`, `self._up_streak_ticks`, `self._writes_this_hour`,
  `self._capture_rejected_low`, `self._stale_ticks`, `self._verify_fails` — bare `self.`
- **All cross-class reads use `self._ev.<attr>`** with `# noqa: SLF001` where the attribute
  is private, matching the existing convention at `energy.py:4141`, `:4517`, `:4929`,
  `:5031`. Specifically:
  - `self._ev._excess_solar_active`  # noqa: SLF001
  - `self._ev._paused_by_dp`  # noqa: SLF001
  - `self._ev._stronger_peer_holds(evse_id)`  # noqa: SLF001
  - `self._ev._get_evse_state(evse_id)`  # noqa: SLF001
  - `self._ev._evse`  # noqa: SLF001  (the config dict; may be needed for prune checks)
- **Lifecycle:** instantiated by `EnergyCoordinator.async_setup` after `EVChargerController`
  is constructed (`energy.py:~1830`), passed the same instance. `async_track_time_interval`
  timer at `SOLAR_FOLLOW_TICK_S` (=60 s) started here; cancelled at `async_unload_entry`.

**Design points:**

1. **Always-on 60 s timer with empty-set fast path (B-5).** `_excess_solar_active` empty
   AND `_original_amps` empty → cheap no-op.
2. **Fleet allocation over ELIGIBLE (B-3 + INV-SF-7 + SF7-B1 + Rev-5 BLOCKING-1).** See
   control law.
3. **6 A hold instead of stop-writing when per-EVSE share < 1.44 kW (B-2).**
4. **`SOLAR_FOLLOW_HEADROOM_KW` deleted (B-6).**
5. **`_original_amps` persistence via existing KV blob machinery (A-HIGH-2 + SF7-H2).**
   Persist as an inline column sibling of `excess_solar_active` at
   `energy.py:1839` / restored at `:1365-1366`, OR a single KV `evse_original_amps_v1` (JSON
   dict) with a `_KNOWN_HOOKS`-registered save/restore. `_original_amps` IS a
   `_prune_removed_evses` participant; on EVSE config removal, the entry is dropped at the
   same tick the six peer-hold sets prune. Step 2b's no-resolvable-entity path (below)
   handles the RAM-cleanup half.
6. **Capture sanity guard (A-HIGH-3).** Session ENTRY: read current-limit entity. Fresh &
   in-range → save. Stale/unavailable → save 48 (INFO). `< SOLAR_FOLLOW_CAPTURE_SANITY_A`
   (=20) → save 48 + `capture_rejected_low++` (WARN).
7. **Mirror start/stop (A-HIGH-4).** Always-on timer.
8. **`EVSE_ESTIMATED_POWER_W` never reaches the control law (A-MED-1 + Rev-5 BLOCKING-1).**
   The surplus add-back gates on `state.get("power_source") == "sensor"` (D1.2 below); an
   EVSE with `power_source == "switch_status"` (the v4.2.19 fallback that fabricates
   7600 W) is excluded from ELIGIBLE FOR THIS TICK and routed into the D1.3 STALE path,
   NOT summed as 0. This is a strict-fail choice: add-0 would under-draw silently on a
   real cloud-blip drawing EVSE; STALE ensures the controller does not decide on stale
   signal at all, per the operator's "conservative down / cautious up" ruling. See §13
   for the invariant that keeps this closed.

**Per-tick control law (Rev-5):**

```
1. If self._ev._excess_solar_active is empty AND self._original_amps is empty: return.

2. RESTORE PASS — iterate a SNAPSHOT to avoid mutation-during-iteration (N5):
   for evse_id in list(self._original_amps):
       if evse_id in self._ev._excess_solar_active:        # noqa: SLF001
           continue  # session still open; no restore
       # 2a — INV-SF-7 defer gate:
       if (self._ev._stronger_peer_holds(evse_id)          # noqa: SLF001
           or evse_id in self._ev._paused_by_dp):          # noqa: SLF001
           self._deferred_restore_evses.add(evse_id)
           continue
       # 2b — resolve entity; CLEAR-on-unresolvable path:
       resolved_entity = self._current_limit_entities.get(evse_id)
       if (resolved_entity is None
           or evse_id not in self._ev._evse):              # noqa: SLF001
           # config prune or unknown EVSE: RAM-clear so the empty-set
           # fast path can eventually fire and the gauge drains.
           self._original_amps.pop(evse_id, None)
           self._deferred_restore_evses.discard(evse_id)
           _LOGGER.info("solar-follow: dropping _original_amps for pruned/unknown %s", evse_id)
           continue
       # 2c — restore:
       value = self._original_amps.pop(evse_id)
       self._deferred_restore_evses.discard(evse_id)
       await self._execute_service_action({
           "service": "number.set_value",
           "target": resolved_entity,
           "data": {"value": value},
       })

3. If self._ev._excess_solar_active is empty: return.  # noqa: SLF001

4. Read grid_W via D1.2 PRIMARY/FALLBACK. If both unavailable:
       self._stale_ticks += 1
       if self._stale_ticks >= SOLAR_FOLLOW_STALE_MAX_TICKS: return  (WARN)
   Else: self._stale_ticks = 0.

5. Build ELIGIBLE. An EVSE is in ELIGIBLE iff ALL of:
   (a) evse_id in self._ev._excess_solar_active            # noqa: SLF001
   (b) NOT self._ev._stronger_peer_holds(evse_id)          # noqa: SLF001
   (c) evse_id not in self._ev._paused_by_dp               # noqa: SLF001
   (d) let s = self._ev._get_evse_state(evse_id)           # noqa: SLF001
       s.get("power_source") == "sensor"                   # Rev-5 BLOCKING-1 gate
   Rationale for (d): the v4.2.19 fallback sets power_source="switch_status"
   and power=EVSE_ESTIMATED_POWER_W. Including such an EVSE would either (a)
   sum a fabricated 7600 W (D1 point 8 violation), or (b) sum 0 W while
   dividing surplus by a denominator that includes it → survivors over-draw.
   Neither is acceptable. Exclude for the tick; route into the STALE grace path.

   If ELIGIBLE is empty:
       any excluded EVSE by clause (d) counts as a stale tick for the whole
       controller (per-tick stale accounting): self._stale_ticks += 1;
       return with no writes and no captures.

6. N_eligible = len(ELIGIBLE).

7. add_back_w = 0.0
   for evse_id in ELIGIBLE:
       s = self._ev._get_evse_state(evse_id)               # noqa: SLF001
       if s.get("charging") and s.get("power_source") == "sensor":
           # Clause (d) already guarantees power_source=="sensor" for
           # ELIGIBLE members; the second predicate is defensive belt-and-
           # braces against a future refactor that widens ELIGIBLE.
           p = s.get("power") or 0.0
           try: add_back_w += float(p)
           except (TypeError, ValueError): pass
   S_eligible = (-grid_W) + add_back_w
   A_total_target = floor(S_eligible / (240 * SOLAR_FOLLOW_PHASES))

8. A_per_evse_raw = A_total_target // N_eligible

9. for evse_id in ELIGIBLE:
   a. CAPTURE if unset — read current-limit entity per point 6.
   b. A_target = clamp(A_per_evse_raw, SOLAR_FOLLOW_MIN_AMPS, SOLAR_FOLLOW_MAX_AMPS)
   c. A_current = read current-limit entity (unavailable => skip THIS EVSE this tick)
   d. Deadband: skip if |A_target - A_current| < SOLAR_FOLLOW_DEADBAND_A
   e. Step law (INV-SF-5):
        if A_target > A_current:
            self._up_streak_ticks[evse_id] = self._up_streak_ticks.get(evse_id, 0) + 1
            if self._up_streak_ticks[evse_id] < SOLAR_FOLLOW_UP_MIN_TICKS: skip
            A_write = min(A_target, A_current + SOLAR_FOLLOW_UP_STEP_A)
        else:
            self._up_streak_ticks[evse_id] = 0
            A_write = A_target  # down-step uncapped
   f. Write-budget: bucket check; skip + WARN if exceeded.
   g. Emit {number.set_value, current_limit_entities[evse_id], A_write}
   h. Schedule readback verify via async_call_later(SOLAR_FOLLOW_VERIFY_S).
```

**Pause ENTRY policy** (unchanged Rev-3/4): LEAVE `_original_amps`; do NOT restore before
yielding. Rationale: stronger owner has turned the switch off; current-limit is cosmetic
until switch re-closes; restore-then-yield would blip pilot to 48 A.

**Pause RELEASE policy** (unchanged Rev-4): 60 s worst-case discovery latency; direction of
harm is UNDER-draw only; fleet math still bounded by `S_eligible` in step 7; INV-SF-4
unchanged; same class as PB-2. **Q5 must-start-release corner:** DP discards `_paused_by_dp`
at `energy.py:5089` / `:5116` when the must-start-by timer fires; the blind-window grant
path uses the `_blind_window_liveness_ride` latch at `energy_pool.py:989-999` (sets
`will_pause=False`, discards prior `_paused_by_blind_window`). Both release paths mutate
sets in the same tick; D1's next 60 s tick observes cleared membership.
`_blind_window_liveness_ride` is a GRANT, not a hold — correctly outside
`_stronger_peer_holds` and correctly does not gate D1.

**D1.2 — surplus signal (Rev-5 stale-gate refinement).**

* PRIMARY grid: `sensor.mains_vue_3_power_minute_average` (Emporia mains, signed W, negative
  = export). **60 s AVERAGE** — informs INV-SF-5 up-gate (N4).
* FALLBACK grid: `sensor.envoy_482543015950_current_net_power_consumption` (signed kW; ×1000
  in the fallback branch). Availability: existing `envoy_available` reliability signal.
* Fences: NOT `balanced_net_power_consumption`; NOT SPAN; NOT
  `sensor.mainw_vue_balance_power_minute_average`; NOT
  `sensor.ura_energy_coordinator_envoy_status`.
* **Add-back is inline over ELIGIBLE only** — do NOT call
  `current_charging_load_w()` (`energy_pool.py:2300-2312`). Sum uses
  `self._ev._get_evse_state(evse_id)` and requires `power_source == "sensor"` (Rev-5
  BLOCKING-1). An EVSE with a `switch_status` fallback power_source is EXCLUDED from
  ELIGIBLE, not summed as 0.

**D1.3 — self-consistency stop.** Both PRIMARY and FALLBACK unavailable OR ELIGIBLE empty
due to per-EVSE `switch_status` fallback → increment `_stale_ticks`; at
`SOLAR_FOLLOW_STALE_MAX_TICKS` (=2) → no writes, WARN. Fail-safe. Note: the per-EVSE stale
accounting is coarse — a single stale EVSE flips the whole controller into grace. That is
deliberate; the alternative (per-EVSE grace) requires per-EVSE stale counters and a design
review of whether a partial-fleet stale window is a class we want to handle.

**D1.4 — current-limit entities.** New key `current_limit` under `DEFAULT_EVSE_ENTITIES`:
- `garage_a`: `number.garage_a_evse_emporia_wifi_garagea_current_limit`
- `garage_b`: `number.garage_b_evse_emporia_wifi_garageb_current_limit`
Passed to `SolarFollowController.__init__` as `current_limit_entities`. L1 excluded.

**D1.5** Solcast next-hour stop signal → D2. `CONF_SOLCAST_NEXT_HOUR_ENTITY` (rung 2).

**D1.6** Bounded readback: `async_call_later(SOLAR_FOLLOW_VERIFY_S=8)` ±1 A tolerance;
WARN + counter on mismatch. Does NOT extend `_maybe_schedule_write_verify`.

**D1.7** Write-budget: `SOLAR_FOLLOW_MAX_WRITES_PER_HOUR_PER_EVSE` (=30, rung 1).

**D1.8 — Status sensor.** `sensor.ura_energy_coordinator_solar_follow` attributes:
`active`, `eligible_evses`, `s_eligible_kw`, `deferred_restore_evses` (gauge — see below),
`capture_rejected_low` (monotone), `writes_per_hour_per_evse`, `current_amps`,
`original_amps`, **`stale_ticks`** (Rev-5 add — surfaces both grid-stale AND
per-EVSE-`switch_status` stale events for legibility of BLOCKING-1's behaviour),
**`excluded_switch_status_evses: list[str]`** (Rev-5 add — EVSEs currently excluded from
ELIGIBLE by the `power_source != "sensor"` gate; empty in the healthy path).

`deferred_restore_evses` membership: (a) `_original_amps[evse_id]` set, (b) `evse_id ∉
_excess_solar_active`, (c) `_stronger_peer_holds(evse_id) OR evse_id in _paused_by_dp`.
Discharge: (i) peer clears → step 2c restore + pop, (ii) EVSE re-enters
`_excess_solar_active`, (iii) EVSE pruned/unknown → step 2b clear-branch pops from
`_original_amps` and discards from gauge.

**D1.9 — Non-peer-hold owner accounting (SF7-M1)** (unchanged Rev-4).

**Constants** (unchanged Rev-4 table).

**D1 acceptance (Rev-5, discriminating):**

* **INV-SF-1** `test_solar_follow_writes_only_number_set_value_never_switch`.
* **INV-SF-2** `test_solar_follow_no_writes_when_both_sets_empty`.
* **INV-SF-3 restart** `test_solar_follow_restore_after_restart_within_release_window`.
* **INV-SF-4 (parametric):** at `grid_W ∈ {-2000, -5000, -11500}`, `N_eligible ∈ {1, 2}`,
  with/without peer-held-drawing EVSE. Assert `Σ_ELIGIBLE A · 240 ≤ max(S_eligible, N·MIN·240)`.
* **INV-SF-5** `test_solar_follow_up_gated_down_immediate`.
* **INV-SF-6 fleet** `test_solar_follow_two_evses_split_surplus`.
* **INV-SF-6 degenerate** `test_solar_follow_two_evses_below_floor_holds_at_min`.
* **INV-SF-7 T-PEER-1** `test_solar_follow_no_write_when_peer_holds_arbitrage`.
* **INV-SF-7 T-PEER-2 (Rev-5 BLOCKING-3 fixture pin):**
  `test_solar_follow_zero_write_and_original_preserved_on_mid_session_peer_add`.
  **Tick 1 fixture: `grid_W = -5000` (5 kW export), garage_b in `_excess_solar_active`
  alone, no peer holds. Modulation fires, captures original amps, commands ~20 A.
  Tick 2 fixture: `grid_W = -1500` (1.5 kW export) — a DOWN move by ~14 A, well outside
  `SOLAR_FOLLOW_DEADBAND_A=1` and outside the up-gate (down is uncapped/ungated per
  INV-SF-5). Meanwhile add garage_b to `_paused_by_grid_cap`.** Correct code: garage_b
  excluded from ELIGIBLE at step 5 → no write, `_original_amps` preserved. Under C17 bug
  (drop step-5 filter): garage_b re-enters ELIGIBLE → step 9d deadband check: |6−20|=14>1
  → deadband does NOT short-circuit → step 9e down-step uncapped → A_write=6 → **write
  fires under a still-active peer hold**. Both assertions (i) preserved unchanged AND
  (ii) zero writes are provably discriminating. Old Rev-4 fixture failed to move surplus
  and was hollow (BLOCKING-3).
* **INV-SF-7 T-PEER-3** `test_solar_follow_no_write_under_paused_by_dp_hold_only`.
* **INV-SF-7 T-PEER-4** `test_solar_follow_restore_deferred_under_peer_hold_fires_on_release`
  — exercises step 2a.
* **INV-SF-7 T-PEER-5 (Rev-5 N3 fixture pin):**
  `test_solar_follow_add_back_and_denominator_both_over_eligible`.
  Fixture: garage_a and garage_b both in `_excess_solar_active`. garage_a in
  `_paused_by_arbitrage` AND physically drawing 7.4 kW (`power_source="sensor"`,
  `charging=True`, `power=7400`). **garage_b's own power pinned BELOW
  `EVSE_CHARGING_POWER_THRESHOLD` (typically ≤50 W, `charging=False`) explicitly** — this
  makes `add_back_w = 0` the discriminating answer. `grid_W = -2000`. Under Rev-5:
  ELIGIBLE={garage_b}, add_back=0 (garage_a not in ELIGIBLE, garage_b not charging),
  `S_eligible = 2000 W`, N=1, `A_total = 8 A`, garage_b commanded 8 A (1.92 kW). Under
  Rev-3 fleet-wide bug: `S_fleet = 2000 + 7400 = 9400`, A=39, garage_b commanded 9.36 kW
  → total 16.76 kW over-draw. If garage_b were pinned to `charging=True` at ~7 kW, the
  Rev-5 correct answer would be 16 A (add_back=7000, S=9000, A=37 clamped up-gated), which
  is Rev-3's number and the test would not discriminate. **The `charging=False` pin is
  load-bearing for T-PEER-5 to distinguish Rev-5 from Rev-3.**
* **T-PEER-6 (SF7-H2)** `test_solar_follow_deferred_restore_clears_on_config_prune` —
  garage_a in `_original_amps` and `_paused_by_grid_cap` (deferred); prune from
  `self._ev._evse`; next tick step 2b CLEAR path fires.
* **Rev-5 BLOCKING-1 T-STALE-1** `test_solar_follow_excludes_evse_with_switch_status_fallback`:
  garage_b in `_excess_solar_active`, `_get_evse_state` returns
  `{charging: True, power: 7600.0, power_source: "switch_status"}` (simulates cloud blip).
  `grid_W = -2000`. Assert: garage_b excluded from ELIGIBLE, `excluded_switch_status_evses`
  contains garage_b, `stale_ticks` increments, no writes fired. Under bug (drop the
  `power_source == "sensor"` gate): garage_b included, `add_back += 7600`, `S = 9600`, A=40,
  → 9.6 kW commanded against 2 kW true surplus. Different observation.
* **A-HIGH-3** `test_solar_follow_capture_rejects_stale_low_value`.
* **N5 iteration safety** `test_solar_follow_restore_pass_iterates_snapshot`: pre-load
  `_original_amps={"garage_a": 32, "garage_b": 40}`; both fire restore in a single tick
  (both eligible for restore). Assert no `RuntimeError` and both entries clear. Under bug
  (iterate the dict directly), Python raises `RuntimeError: dictionary changed size during
  iteration` on the pop.
* **SF7-H2 load-shed restart benign** `test_solar_follow_load_shed_deferral_clears_on_restart`.
* **Live** (sunny afternoon): sensor shows `active=True`, `eligible_evses`, `s_eligible_kw`,
  `stale_ticks == 0`, `excluded_switch_status_evses == []` in the healthy path.
* **Live** (release): current-limit returns to saved `_original_amps` within 60 s.
* **Live** (two-EVSE): `Σ_ELIGIBLE A · 240 ≤ S_eligible` over a 15-min window.
* **Live** (INV-SF-7): if arbitrage overlap occurs, `eligible_evses` excludes arbitrage-held
  EVSE and `deferred_restore_evses` populates on release-edge.
* **Live** (BLOCKING-1): if an Emporia cloud blip fires during a session,
  `excluded_switch_status_evses` names the affected EVSE and `stale_ticks` climbs —
  observability confirmation of the strict-fail choice.

### D2 — Release-gate hysteresis + drain-protection skip

(Unchanged Rev-3.) Streak + min-on-time on `energy_pool.py:1685-1699`. Drain-protection
skip at `determine_battery_drain_actions:1776` (fill-priority prior art at `:2214`).
Solcast next-hour as second release trigger. Tests: `test_release_streak_gated`,
`test_release_min_on_time`, `test_release_streak_persists_min_on_time_across_restart`,
`test_drain_protection_skips_solar_follow_active`.

### D3 — DP drain-target mis-sourcing fix (FIVE R2 sites)

(Unchanged Rev-3.) R2 sites: `energy.py:4271`, `:4456`, `:4522`, `:4540`, `:4555` all route
through new `_dp_drain_target_soc(period)` helper importing `compose_release_floor` from
`energy_battery`. R1 (`:5842`, `:5977`) and R3 (`:3752`, `energy_pool.py:954`, `:1435`)
unchanged. None-fallback to static reserve (NOT `_ev_battery_drain_soc`, B-1 guard).
Callers wrap ValueError. Tests: T1, T1b, T1c, T1d, T2, T3, T3b, T4, T5 as named.

---

## 4. Non-goals (explicit)

* NOT starting/stopping charges. NOT coordinating with DP. NOT changing the excess-solar
  TRIGGER. NOT changing the EC 5-min tick. NOT extending `_maybe_schedule_write_verify`.
  NOT wiring HVAC coupling. NOT demoting `evse_battery_hold`. NOT changing
  `ev_battery_drain_soc` live value (still 80). NOT changing R1 / R3 sources. NOT touching
  `sensor.mainw_vue_balance_power_minute_average`. NOT using
  `balanced_net_power_consumption`, SPAN, or `sensor.ura_energy_coordinator_envoy_status`.
  NOT wiring L1 chargers. NOT introducing a new `persistence_kind`. NOT auto-remediating
  offline Garage A / SPAN observability gap. NOT feeding `EVSE_ESTIMATED_POWER_W` into D1's
  control law (Rev-5 restatement: including via the v4.2.19 `power_source="switch_status"`
  fallback in `_get_evse_state:690-697` — the D1 add-back gates on `power_source == "sensor"`).
  NOT introducing priority ordering. NOT adding `_paused_by_dp` to `_stronger_peer_holds`.
  NOT re-solving compound-load (live mutex at `energy.py:6240-6263` + `:6290-6328` +
  `:6341-6365` bounds it). NOT building a per-EVSE "no-interference latch". NOT using
  `current_charging_load_w()` (`energy_pool.py:2300-2312`) for the add-back.

---

## 5. Known couplings

1. DP gate 6 crossover at 12.5 A. 2. Gate 8 charge_hours at low amps.
3. `_dp_house_load_kw` biased other way. 4. `EVSE_ESTIMATED_POWER_W = 7600` never in D1's
control law (Rev-5 double-close via `power_source` gate). 5. `evse_battery_hold` engages at
6 A. 6. Emergent actuation precedence. 7. INV-YIELD-1/2. 8. Live compound-load mutex
`energy.py:6240-6263` + `:6290-6328` + `:6341-6365`. 9. `_pause_dispatch_ts` /
`_observed_off_since_pause` `:275-278` — SF7-B1's operator-re-enable premise is exactly
this class. 10. `_paused_by_load_shed` `persistence_kind="none"` — restores on first
post-restart tick, benign.

---

## 6. Docs drift to fix in-cycle

* `docs/user-manual/ENERGY_COORDINATOR.md:642` (default-50 + R1-only).
* `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md:455`.
* `docs/planning/PLANNING_evse_drain_precedence.md` (unbound `drain_target`).
* `docs/planning/PLANNING_inclement_weather_reserve.md:66,82`.
* `energy_pool.py:_stronger_peer_holds` docstring says "the five", loop returns six (SF7-L1).

---

## 7. Test plan summary

Behavioural, MUTATION-VERIFIED. `PYTHONDONTWRITEBYTECODE=1` + clear `__pycache__` before
each drill.

D1: `test_solar_follow_writes_only_number_set_value_never_switch`;
`test_solar_follow_no_writes_when_both_sets_empty`;
`test_solar_follow_restore_after_restart_within_release_window`;
`test_solar_follow_bounds_draw_by_surplus_hardware_floor_exception`;
`test_solar_follow_up_gated_down_immediate`;
`test_solar_follow_two_evses_split_surplus`;
`test_solar_follow_two_evses_below_floor_holds_at_min`;
`test_solar_follow_capture_rejects_stale_low_value`;
`test_solar_follow_stops_writing_when_both_sensors_unavailable`;
`test_solar_follow_write_budget_containment`;
`test_solar_follow_never_feeds_evse_estimated_power_into_control_law`;
`test_solar_follow_load_shed_deferral_clears_on_restart`;
**T-STALE-1** `test_solar_follow_excludes_evse_with_switch_status_fallback` (Rev-5 BLOCKING-1);
**T-ITER-1** `test_solar_follow_restore_pass_iterates_snapshot` (Rev-5 N5);
T-PEER-1 `test_solar_follow_no_write_when_peer_holds_arbitrage`;
**T-PEER-2** `test_solar_follow_zero_write_and_original_preserved_on_mid_session_peer_add`
(Rev-5 BLOCKING-3 fixture pin: tick 1 `grid_W=-5000`, tick 2 `grid_W=-1500`);
T-PEER-3 `test_solar_follow_no_write_under_paused_by_dp_hold_only`;
T-PEER-4 `test_solar_follow_restore_deferred_under_peer_hold_fires_on_release`;
**T-PEER-5** `test_solar_follow_add_back_and_denominator_both_over_eligible`
(Rev-5 N3 pin: garage_b `charging=False`);
T-PEER-6 `test_solar_follow_deferred_restore_clears_on_config_prune`.

D2/D3: unchanged from Rev-3/4.

---

## 8. Review plan — Tier 3, four framing-disjoint passes

* **A — local correctness.** ELIGIBLE-scoped add-back with `power_source` gate; step 2a/2b/2c
  attribute-access convention; N5 snapshot iteration; unit conversions.
* **B — integration / state-machine + byte-identical no-op.** Class shape as standalone with
  injected `_ev`; `# noqa: SLF001` sites match `energy.py:4141`/`:4517`/`:4929`/`:5031`
  convention; R1/R3 grep-diff clean; restart paths; must-start-release corner (Q5).
* **C — REAL per-site source mutation. Rev-5 corrected list:**
  - C1..C16 as Rev-4.
  - **C17 (Rev-5 refined):** replace step-5 ELIGIBLE with raw
    `self._ev._excess_solar_active` (drop the `_stronger_peer_holds` + `_paused_by_dp` +
    `power_source` filters at step 5 ONLY; DO NOT touch step 2a or step 7 add-back) →
    **T-PEER-1, T-PEER-2 (Rev-5 fixture), T-PEER-3, T-PEER-5, T-STALE-1 must fail. T-PEER-4
    is NOT in this list** (exercises step 2a).
  - **C17b:** delete step-2a peer-hold guard ONLY → T-PEER-4 must fail.
  - **C17c:** replace ELIGIBLE-scoped add-back with fleet-wide `current_charging_load_w()`
    (keep denominator = `len(ELIGIBLE)`) → **T-PEER-5 must fail** (add-back inflates by
    peer-held draw; survivor over-draws). Anchors the SUM half of SF7-B1.
  - **C17d (Rev-5 N1 add):** replace `N_eligible = len(ELIGIBLE)` with `N_eligible =
    len(self._ev._excess_solar_active)` (keep add-back over ELIGIBLE) → **T-PEER-5 must
    fail** (denominator too large, per-EVSE share halved, survivor under-draws vs the
    Rev-5 oracle). Anchors the DENOMINATOR half of SF7-B1, DISJOINT from C17c's SUM half.
    Disjointness note: C17c and C17d are disjoint MUTATIONS with overlapping ORACLES (both
    fail T-PEER-5) — that is what makes T-PEER-5 discriminate both halves.
  - **C17e (Rev-5 N2 add):** delete step-2b's `resolved_entity is None or evse_id not in
    self._ev._evse` CLEAR branch (turn it into a `continue` that leaves the entry in
    `_original_amps`) → **T-PEER-6 must fail** (entry persists forever, empty-set fast path
    never fires, gauge does not drain).
  - **C17f (Rev-5 BLOCKING-1 add):** delete the `power_source == "sensor"` clause from
    step 5(d) → **T-STALE-1 must fail** (garage_b included with fabricated 7600 W, S
    inflates, over-draw commanded).
* **D — adversarial completeness.** Re-enumerate ENTIRE R2 emission set; re-enumerate all
  `_excess_solar_active` discard sites (three at `energy_pool.py:1369`/`:1564`/`:1699` +
  restart-reconciliation + `_prune_removed_evses`); re-enumerate peer-hold owner mutation
  sites; re-enumerate every `number.set_value` writer in `energy*.py`. Legal-config
  combinatorial. Every leak → concrete legal-config repro.

**Orchestrator pre-deploy verification:** re-grep all five R2 sites; re-grep the six
peer-hold owner sets + `_paused_by_dp`; run mutation drills C17/b/c/d/e/f; confirm zero
call sites to `current_charging_load_w()` inside `SolarFollowController`; confirm every
cross-class `self._ev.<attr>` access carries `# noqa: SLF001` where the attribute is
private. **Operator checkpoint BEFORE deploy.**

---

## 9. REUSE vs NEW

(Additions in **bold**; rest unchanged Rev-4.)

| Item | Verdict | Cite |
|---|---|---|
| `PoolOptimizer` shape (save/restore + unavailable-keep-state) | REUSE (shape only; not the `__init__` signature) | `energy_pool.py:58-160` |
| `_execute_service_action` write path | REUSE | — |
| `_excess_solar_active` membership | REUSE | `energy_pool.py:202` |
| Per-EVSE inline persistence for `_original_amps` | REUSE | `energy.py:1839`, `:1365-1366` |
| `_get_evse_state` (per-EVSE state read) | REUSE | `energy_pool.py:650` |
| **`power_source` field discrimination (Rev-5 BLOCKING-1 close)** | REUSE | `energy_pool.py:700-706` |
| `compose_release_floor()` (module fn) | REUSE | `energy_battery.py:264` |
| `_ev_battery_drain_soc` at R1/R3 | REUSE unchanged | — |
| TOU peak-clear | REUSE | `energy_pool.py:1354-1374` |
| Fill-priority `_excess_solar_active` skip (D2 prior art) | REUSE pattern | `:2214-2219` |
| `_stronger_peer_holds` + inline `_paused_by_dp` | REUSE | `:383-412`, `:1621-1631` |
| **Cross-class private-read `# noqa: SLF001` convention (Rev-5 BLOCKING-2)** | REUSE | `energy.py:4141`, `:4517`, `:4929`, `:5031` |
| Anti-flap duration threshold (D2 shape-match) | REUSE | `PLANNING_v4.7.x_APPLIANCE_SCHEDULER.md:41` |
| Live compound-load mutex | REUSE unchanged | `energy.py:6240-6263` + `:6290-6328` + `:6341-6365` |
| `_prune_removed_evses` participation for `_original_amps` | REUSE mechanism | `energy_pool_owners.py:345+` |
| `SolarFollowController` class | NEW | Zero amp control today |
| Session-scoped 60 s timer | NEW | — |
| ELIGIBLE-scoped surplus add-back with `power_source` gate | NEW (inline sum) | — |
| `_dp_drain_target_soc(period)` helper | NEW | — |
| Release-gate streak + min-on-time | NEW | — |
| Solcast next-hour stop | NEW | — |
| `SOLAR_FOLLOW_*` constants + Numbers | NEW | — |
| Drain-protection `_excess_solar_active` skip | NEW | — |
| Bounded in-controller readback verify | NEW | — |
| `BatteryStrategy.set_offpeak_drain_target` (conditional) | NEW | — |

---

## 10. Design pushback recorded

PB-1 ADOPTED as D2 fix 5. PB-2 WITHDRAWN. Either-or signal design recorded.

---

## 11. Parked P-items disposition

P1/P5/P13 DEFER. P6 ADOPT (shape-match). P8 REJECT-WITH-EVIDENCE per Rev-4 (live mutex at
`energy.py:6240-6263` + `:6290-6328` + `:6341-6365`). P9 REJECT (operator-withdrawn).

---

## 12. Change log

Rev-1→Rev-2: 14 items (see Rev-2 for detail).
Rev-2→Rev-3: pause-owner precedence BLOCKING; P8 upgrade; P6 ADOPT.
Rev-3→Rev-4: SF7-B1/B2 BLOCKING; SF7-H1/H2 HIGH; SF7-M1 MED; SF7-L1/L2 LOW; Q5 LOW.
Rev-4→Rev-5:

| Finding | Severity | Change |
|---|---|---|
| **BLOCKING-1: Rev-4 add-back reintroduced `EVSE_ESTIMATED_POWER_W` reachability via `_get_evse_state`'s v4.2.19 fallback** | BLOCKING | Step 5(d) `power_source == "sensor"` gate; step 7 defensive re-check; STALE-path routing (not add-0); T-STALE-1; C17f; new observability attrs `stale_ticks` + `excluded_switch_status_evses`; §5 item 4 double-close; §13 "Closed concerns" register added. |
| **BLOCKING-2: SolarFollowController shape ambiguous — bare `self.` vs `self._ev.` mixed** | BLOCKING | Class shape pinned as standalone with `ev: EVChargerController` injection; every cross-class read uses `self._ev.<attr>` with `# noqa: SLF001`; `__init__` signature explicit; convention documented in §9. |
| **BLOCKING-3: T-PEER-2 still hollow — no fixture moved surplus, deadband masked the mutation** | BLOCKING | Tick-1 `grid_W=-5000`, tick-2 `grid_W=-1500` — a 14 A down-move well outside deadband and outside up-gate. Rationale for choosing DOWN documented (INV-SF-5 down uncapped). Test spec details discriminating behaviour under C17. |
| N1: C17 and C17c not disjoint — denominator had no independent drill | Correction | New C17d (`N_eligible = len(_excess_solar_active)` while keeping ELIGIBLE add-back). Reframed as "disjoint mutations, overlapping oracles." |
| N2: step-2b clear-on-unresolvable had no drill | Correction | New C17e. |
| N3: T-PEER-5 hollow if garage_b's own draw not pinned | Correction | Fixture pins garage_b `charging=False` (own power < `EVSE_CHARGING_POWER_THRESHOLD`) explicitly; oracle-discrimination argument spelled out. |
| N4: averaging mismatch (60 s avg vs instant) misattributed to INV-SF-4 | Correction | Recorded as INV-SF-5 concern (up-gate bounds it); future-cycle warning added. |
| N5: step-2 mutation-during-iteration would crash on first release + first prune | HIGH | Explicit `list(self._original_amps)` snapshot in the control law; T-ITER-1 test. |

---

## 13. Closed concerns — must stay closed (Rev-5 new)

Pattern-fix per coordinator: each future revision diffs the plan against this register
BEFORE reporting. Twice now, a fix re-authored a code path and walked back into a previously-
closed concern (A-MED-1 → SF7-B1's fleet-wide add-back → Rev-5 BLOCKING-1's re-opening via
`_get_evse_state`'s v4.2.19 fallback). This register makes the "did I re-open something?"
check cheap.

| Concern | Round originally closed | The one-line invariant that keeps it shut |
|---|---|---|
| `EVSE_ESTIMATED_POWER_W` reaches D1's control law | Rev-2 (A-MED-1); re-opened Rev-3 via `current_charging_load_w()`; re-opened Rev-4 via `_get_evse_state.charging` flag; re-closed Rev-5 | D1's surplus add-back sums ONLY EVSEs whose `_get_evse_state.power_source == "sensor"`. Every future revision that touches the add-back grep-checks its diff for `EVSE_ESTIMATED_POWER_W`, `current_charging_load_w`, `switch_status`, and `state.get("charging")` (the third is the class this closes). |
| Parallel derivation of the DP drain target (`current_offpeak_drain_target()` bypassing park reconciliation) | Rev-2 (B-1 danger note) | `_dp_drain_target_soc` uses `compose_release_floor` ONLY; None fallback goes to static reserve, NEVER to `_ev_battery_drain_soc` or the raw `current_offpeak_drain_target()`. Every future revision grep-checks its diff for `current_offpeak_drain_target(` outside `energy_battery.py`. |
| Fleet-wide surplus add-back over-drawing when a peer-held EVSE keeps physically drawing | Rev-4 (SF7-B1) | `S_eligible` sums add-back ONLY over ELIGIBLE (peer-held EVSEs excluded); §4 non-goal against `current_charging_load_w()` inside `SolarFollowController`. |
| New `persistence_kind` introduced when existing shapes suffice | Rev-2 (A-HIGH-2) | `_original_amps` persists via existing inline column at `energy.py:1839` OR existing KV blob shape via `_KNOWN_HOOKS`; no new persistence kind. |
| `SOLAR_FOLLOW_HEADROOM_KW` orphan (headroom = permission to pull from battery) | Rev-2 (B-6) | INV-SF-4 has no headroom term; the constant does not exist. |
| Missed R2 emission site (5 sites, not 2) | Rev-2 (A-CRIT-1) | The R2 emission-site TABLE in §3.D3 lists ALL five (`:4271`, `:4456`, `:4522`, `:4540`, `:4555`); every future revision that touches DP grep-checks for `_ev_battery_drain_soc` under `domain_coordinators/` and confirms only R1/R3 sites remain. |
| Same-tick revert flap when `:4522` stamps and `:4555` reverts | Rev-2 (A-CRIT-2) | `:4555` sources from `_dp_drain_target_soc(period)`, same value stamped by `:4522`. INV-DP-DRAIN-1b. |
| R1 pause ceiling collapse to composed floor | Rev-2 (HIGHEST_PROBABILITY_BUILD_ERROR guard) | `determine_battery_drain_actions(soc_threshold=)` sources from `self._ev_battery_drain_soc` unchanged at `:5842` + `:5977`. INV-DP-DRAIN-2 + mutation drill C2. |
| Solar-follow acts on a peer-held EVSE | Rev-3 (SF7 peer-hold-missed) | INV-SF-7 + ELIGIBLE-set at step 5 + guard at step 2a. C17 + C17b. |
| Restore-pass mutation-during-iteration crash | Rev-5 (N5) | Explicit `list(self._original_amps)` snapshot. T-ITER-1. |
| `SolarFollowController` shape ambiguous (bare `self.` vs `self._ev.`) | Rev-5 (BLOCKING-2) | `__init__(self, hass, ev: EVChargerController, ...)`; every cross-class read `self._ev.<attr>` with `# noqa: SLF001` per `energy.py:4141`/`:4517`/`:4929`/`:5031` convention. |
| Hollow test anchor via fixture that doesn't perturb the tested branch | Rev-3 (SF7-H1); re-opened Rev-4 as fixture-not-diagnostic; re-closed Rev-5 (BLOCKING-3) | Test fixtures for peer-hold tests MUST move surplus by more than DEADBAND and outside the up-gate between ticks so the correct code's silence is provably a peer-hold decision, not a coincidence of deadband or up-gate. Applies to T-PEER-2 specifically; template for any future mid-session peer test. |

---

## 14. Cycle-close checklist

* [ ] Targeted re-review of Rev-5 BLOCKING-1/2/3 fixes (coordinator-scoped).
* [ ] Build in one branch off `develop`.
* [ ] Suite green + baseline-diff clean.
* [ ] Four framing-disjoint reviews A/B/C/D returned; CRITICAL/HIGH fixed.
* [ ] Orchestrator pre-deploy: re-grep five R2 sites; re-grep six peer-hold owner sets +
      `_paused_by_dp`; run mutation drills C17/b/c/d/e/f; zero-call-sites confirmation
      against `current_charging_load_w()` and against bare `EVSE_ESTIMATED_POWER_W` inside
      `SolarFollowController`; **diff-check against §13 "Closed concerns" register.**
* [ ] Operator checkpoint before deploy.
* [ ] `README_v<version>.md` with prospective Live criteria.
* [ ] Deploy via `./scripts/deploy.sh`.
* [ ] Live validation: sunny-day D1 attributes including `s_eligible_kw`, `stale_ticks`,
      `excluded_switch_status_evses`; two-EVSE split; release-edge restore; D3 DP snapshot
      with plugged EV; A-CRIT-1/A-CRIT-2 direct; INV-SF-7 if arbitrage overlap occurs;
      BLOCKING-1 live confirmation if an Emporia cloud blip occurs mid-session.
* [ ] README updated with observed `Validated <date>` table.
* [ ] Kanban cards shipped_organic; parked `project_ev_drain_precedence_cycle` retained.
* [ ] Post-ship supersession + consumer-gap audit per CLAUDE.md rule.
