# PLANNING — EVSE solar-following amp modulation

**Cycle name:** `evse-solar-follow-amps`
**Tier:** **Tier 3** (new writer on a live cloud actuator at 1-min cadence; peer-hold
subordination on a shared primitive; fleet allocation across two EVSEs).
**Threads:** `energy`
**Cards:** `EVSE-SOLAR-FOLLOW-AMPS-1`
**Design source:** the card body (esp. `DESIGN_CLOSED_2026_08_23`,
`SIGNAL_DESIGN_FINAL_2026_08_23`, `SENSOR_DELTA_MEASURED_2026_08_23`,
`SCOPE_FENCE_2026_08_23`, `OPERATOR_ANSWERS_AND_VERIFIED_FACTS_2026_08_23`) and
`docs/planning/AUDIT_excess_solar_and_evse_prior_art.md`.
**Probes:** `scripts/probes/delta_probe.py`, `scripts/probes/skew_probe.py`.

**Provenance.** Extracted from the combined plan
`PLANNING_evse_solar_follow_and_dp_drain_target.md` (Rev-1..Rev-8) so the moving design
here does not gate the stable DP fix. This doc carries the full solar-follow content
(D1/D2, all INV-SF-*, DRAWING/ELIGIBLE split, safe-parking, peer-hold subordination,
PB-1 REJECTED, P-item dispositions, C17-C20c mutation drills, closed-concerns register).
The DP drain-target fix lives in a separate doc,
`PLANNING_dp_drain_target_mis_sourcing.md`.

**Runtime relationship to the DP fix (informational, not a build dependency).**
The DP fix changes which drain target DP consumes, which changes when DP holds EVSEs via
`_paused_by_dp`. This controller reads `_paused_by_dp` as part of its ELIGIBLE set (per
INV-SF-7), but has NO code dependency on the DP fix.

**Sequencing preference: SHIP THE DP FIX FIRST.** This is a preference, not merely
acceptable — it is preferable. Building and live-validating this controller against a
known-wrong DP drain target (`drain_target_soc = 80` while `current_offpeak_drain_target
= 10`) means the ELIGIBLE-set observability we ship (`eligible_evses`,
`drain_trips_during_follow`) reflects behaviour under the defect. After the DP fix ships,
DP will actually transition for the first time in production, which changes which EVSEs
solar-follow observes in `_paused_by_dp` and when. Shipping DP first means this
controller's live validation sees the corrected DP behaviour. The DP fix is buildable
today; this cycle should follow it.

---

## 0. Tier-3 elevation and framing

Two independent risks:

* **NEW WRITER on a live cloud actuator at 1-min cadence.** URA has never written amps
  before. Wrong containment = write-flood incident class
  (`project_optimizer_db_write_flood_incident_2026_06_09`). Wrong restore = silently
  crippled next charge. Wrong reactivity = drives battery discharge harder than the binary
  version. Wrong fleet allocation makes two chargers each pull the full surplus (Rev-2
  B-3). Wrong peer-hold subordination makes solar-follow act on a device a stronger owner
  has claimed (Rev-3). Wrong surplus-denominator alignment causes over-draw when a
  peer-held EVSE keeps drawing (Rev-4 SF7-B1). Wrong signal-source discrimination lets
  `EVSE_ESTIMATED_POWER_W` fabrication reach the control law via the v4.2.19
  `_get_evse_state` fallback (Rev-5 BLOCKING-1). Idle-bay dilutes allocation denominator
  (Rev-8, operator-flagged).
* **"Silent success" failure modes.** Multiple review rounds shipped acceptance criteria
  that passed against defects; §11 register lists each one and the invariant that keeps
  it shut.

Tier 3.

---

## 1. Falsifiable invariants

Each: "under X, Y can never happen in ANY reachable path."

### INV-SF-1 (non-perturbation)
`SolarFollowController` emits no `switch.turn_on` / `switch.turn_off`. Writes only
`number.set_value` to a current-limit entity, only for an EVSE in `_excess_solar_active`.

### INV-SF-2 (writes only inside sessions)
Both sets empty → zero writes.

### INV-SF-3 (restore is load-bearing, restart-safe)
After removal from `_excess_solar_active` by any code path (release `energy_pool.py:1699`,
blind-window drop `:1564`, peak clear `:1369`, restart reconciliation
`energy.py:5183-5225`, or config prune via `_prune_removed_evses`), current-limit
restored to saved `_original_amps` within one restore tick — subject to INV-SF-7.

### INV-SF-4 (draw bounded by measured surplus — DRAWING vs ELIGIBLE)
`ELIGIBLE = {evse_id ∈ _excess_solar_active where NOT _stronger_peer_holds(evse_id) AND
evse_id ∉ _paused_by_dp AND _get_evse_state(evse_id).power_source == "sensor"}` — the
COMMANDABLE set (receives writes).
`DRAWING = {evse_id ∈ ELIGIBLE where _get_evse_state(evse_id).charging is True}`
(`charging = power > EVSE_CHARGING_POWER_THRESHOLD = 100 W`, `energy_pool.py:691`).
`S_eligible = -grid_W + Σ_{DRAWING} evse_power_w` — add-back sums only DRAWING bays.

**Bound on commanded amps at a given tick:**
`Σ_{i ∈ DRAWING} A_i · 240 · PHASES ≤ max(S_eligible, N_drawing · MIN · 240)`.
`Σ_{i ∈ ELIGIBLE \ DRAWING} A_i · 240 · PHASES ≤ (N_eligible - N_drawing) · MIN · 240`
(each non-drawing ELIGIBLE bay is commanded MIN safe-parking).

**Physical-draw bound within a ≤60 s window** (accounting for at-most-one bay
transitioning from non-DRAWING to DRAWING between ticks):
`Σ_{physically drawing at t} A_i · 240 · PHASES ≤ max(S_eligible, N_eligible · MIN · 240)`.
Plug-in mid-window over-commit bounded by `(N_eligible - N_drawing) · MIN · 240`,
≤60 s duration. On the ordinary N_eligible=2 install this is ≤1.44 kW × 60 s = ≤24 Wh —
trivial vs the yo-yo class this cycle prevents.

Fabricated-power (`power_source == "switch_status"`) EVSEs are EXCLUDED from ELIGIBLE
entirely; they route to D1.3's STALE path (increment stale counter; at MAX_TICKS, no
writes).

### INV-SF-5 (asymmetric reaction to a lagging signal)
Down-step uncapped, one tick. Up-step gated by `SOLAR_FOLLOW_UP_MIN_TICKS`, capped at
`SOLAR_FOLLOW_UP_STEP_A` per tick per EVSE. **PRIMARY is a 60 s AVERAGE while the
DRAWING add-back is INSTANTANEOUS.** During a ramp, `S_eligible` can over-read for up to
60 s and the controller could ratchet upward. The up-gate (`UP_MIN_TICKS × UP_STEP_A`)
is what contains this. **INV-SF-4 is arithmetic bookkeeping; the physical lag containment
is INV-SF-5.** A future cycle relaxing INV-SF-5 must not lean on INV-SF-4 to cover the lag.

### INV-SF-6 (fleet allocation)
`N_denom = max(1, N_drawing)`.
`A_total_target = floor(S_eligible / (240 · PHASES))`.
`A_per_drawing = clamp(A_total_target // N_denom, MIN, MAX)`.

Command routing:
- DRAWING bays receive `A_per_drawing`.
- ELIGIBLE \ DRAWING bays receive `SOLAR_FOLLOW_MIN_AMPS` (6 A) safe-parking.

Degenerate cases:
- `N_drawing == 0, N_eligible ≥ 1`: N_denom=1 prevents divide-by-zero; all ELIGIBLE get
  MIN safe-parking; `A_per_drawing` computed but routed to no one this tick (log INFO).
- `N_drawing = 1, N_eligible = 2`: drawing bay gets full commanded surplus; idle bay
  gets MIN safe-parking. Plug-in transient bounded by MIN·240 per INV-SF-4 within-window.
- `N_drawing == N_eligible ≥ 1`: standard equal-split.

### INV-SF-7 (stronger-peer subordination — NO EXCEPTIONS)
While `_stronger_peer_holds(evse_id) is True` OR `evse_id ∈ _paused_by_dp`, no write to
that EVSE and no capture. Applies to BOTH step 2a (restore) AND step 5 (modulation).
`_paused_by_dp` checked INLINE per the two-site convention `energy_pool.py:394-400`.

**No exceptions carved out for individual peer owners.** `_paused_by_battery_drain` IS
one of the six owners `iter_peer_holds()` returns
(`energy_pool_owners.py:262-269`); solar-follow yields to drain-protection correctly
under this invariant.

### INV-RELEASE-1 (D2)
Release fires only when `not conditions_met OR solcast<floor` AND streak ≥ MIN_TICKS AND
session age ≥ MIN_ON_S.

---

## 2. Institutional context verified

Paths under `custom_components/universal_room_automation/domain_coordinators/`:

* `docs/planning/AUDIT_excess_solar_and_evse_prior_art.md` (all sections).
* `energy_pool.py` — `PoolOptimizer:58-160` (template shape only; `__init__:66-81` holds
  only `hass` + entity ids); `EVChargerController.__init__:186-317`;
  `determine_excess_solar_actions:1318-1701` (release `:1685-1699` = D2 hysteresis half);
  **`determine_battery_drain_actions:1776-1959` — the safety gate; BYTE-IDENTICAL
  post-cycle. Zero edits, zero counter bumps, zero comments, zero re-imports.** RESUME at
  `:2000` reads `solar_replenishing`; `_soc_envelope_admits_dp_transition:619-648`;
  `_stronger_peer_holds:383-412` (docstring "the five" stale — loop returns six via
  `EV_REGISTRY.iter_peer_holds()`); `_paused_by_dp` inline claim `:1621-1631`; **excess-
  solar CLAIM path at `:1650-1656`** (byte-identical post-cycle; the switch-on happens
  WITHOUT a plug check — an empty bay is ELIGIBLE-not-DRAWING per Rev-8, handled inside
  D1); `_get_evse_state:650` with v4.2.19 fallback `:690-697`
  (`power_source="switch_status"`, `power=EVSE_ESTIMATED_POWER_W=7600 W`) — the ELIGIBLE
  set gates on `power_source == "sensor"`; **`charging = power >
  EVSE_CHARGING_POWER_THRESHOLD` at `:691`** — the DRAWING subset predicate;
  `current_charging_load_w:2300-2312` (fleet-wide; NOT USED by D1);
  `_pause_dispatch_ts` / `_observed_off_since_pause` `:275-278`. **`_paused_by_grid_cap`
  pause site at `:1723-1735`** — the v4.0.18 grid-import cap (see §5 known couplings for
  the D4-overlap question surfaced in Rev-9's correction).
* `energy_pool_owners.py` — `iter_peer_holds()` = 6 owners INCLUDING `battery_drain`
  (`:262-269`); `persistence_kind` ∈ {`"per_evse_bool"`, `"list"`, `"none"`};
  `_paused_by_load_shed` `persistence_kind="none"` (`:298-300`).
* `energy.py` — `self._ev` at `:293` (EnergyCoordinator holds the EVChargerController);
  SLF001 convention at `:4141`, `:4517`, `:4929`, `:5031`; **`solar_replenishing`
  computed at `:5823`** from `_surplus_pct > DEFAULT_EV_SOLAR_REPLENISH_SURPLUS_PCT OR
  battery_power_w > 100`, byte-identical post-cycle; **live compound-load mutex at
  `:6240-6263`** (`charge_from_grid` chokepoint; phase-label-independent — covers
  arbitrage CHARGE, v5.3.8 ATTAIN, and future rungs) + `:6290-6328` (hardware read OR
  fail-closed latch) + `:6341-6365` (EV pauses dispatched before battery actions).
  Load-shed re-claim `:7259-7282`.
* `energy_battery.py` — `solar_production_w:1586-1612`; `net_power_w:1614-1623`.
* `energy_const.py` — `EVSE_ESTIMATED_POWER_W = 7600` (`:827`);
  `EVSE_CHARGING_POWER_THRESHOLD = 100` (`:826`); `DP_L1_RATE_THRESHOLD_KW = 3.0`;
  `DEFAULT_EV_SOLAR_REPLENISH_SURPLUS_PCT`.
* `database.py:4526-4535` — `save_evse_state` atomic for `paused_by_us` +
  `excess_solar_active` (SF7-M1 argument).
* `PLANNING_v4.7.x_APPLIANCE_SCHEDULER.md:41` — `flashg1/SolarCharger` anti-flap prior art.
* Historical git-log verification for §5 known-couplings item 8 (D4 attribution
  correction): `_paused_by_grid_cap` introduced in **v4.0.18** (commit `1a499f0b8`, "Fan
  manual-off cooldown + EV grid import cap"); `_paused_by_arbitrage` introduced in
  **v4.5.0** (commit `f3deabc84`, the battery-strategy redesign that became D4).
* Memory: `project_optimizer_db_write_flood_incident_2026_06_09`;
  `project_ev_drain_precedence_cycle` (parked hold-demotion cycle; explicit non-goal);
  `feedback_suppression_needs_discharge`; `feedback_hollow_test_anchors`;
  `feedback_mutation_verification_pycache_staleness`; `RESTART-SAFETY-DOCTRINE-1`.

---

## 3. Deliverables

### D1 — SolarFollowController

**Class shape:**

```python
class SolarFollowController:
    def __init__(
        self,
        hass: HomeAssistant,
        ev: EVChargerController,
        current_limit_entities: dict[str, str],
        solcast_next_hour_entity: str | None = None,
    ) -> None:
        self.hass = hass
        self._ev = ev
        self._current_limit_entities = current_limit_entities
        self._solcast_next_hour_entity = solcast_next_hour_entity
        self._original_amps: dict[str, float] = {}
        self._deferred_restore_evses: set[str] = set()
        self._up_streak_ticks: dict[str, int] = {}
        self._writes_this_hour: dict[str, int] = {}
        self._capture_rejected_low: int = 0
        self._stale_ticks: int = 0
        self._verify_fails: int = 0
        self._drain_trips_during_follow: int = 0
        self._prev_paused_by_battery_drain: set[str] | None = None
```

Cross-class reads use `self._ev.<attr>` with `# noqa: SLF001` per `energy.py:4141`/
`:4517`/`:4929`/`:5031` convention. Lifecycle: instantiated by
`EnergyCoordinator.async_setup` after `EVChargerController` construction;
`async_track_time_interval` timer at `SOLAR_FOLLOW_TICK_S` (=60 s) started here;
cancelled at `async_unload_entry`.

**Design points:**

1. **Always-on 60 s timer with empty-set fast path** — both `_excess_solar_active` empty
   AND `_original_amps` empty → cheap-membership no-op.
2. **Fleet allocation over DRAWING with commands over ELIGIBLE** (two-predicate split,
   see INV-SF-4 / INV-SF-6). Empty bays don't dilute; non-drawing ELIGIBLE bays get MIN
   safe-parking to cap plug-in transient at 1.44 kW.
3. **6 A hold instead of stop-writing when per-EVSE share < 1.44 kW** — pilot floor is
   hardware, not policy.
4. **`SOLAR_FOLLOW_HEADROOM_KW` does not exist** — headroom = permission to pull from
   battery, the harm INV-SF-4 forbids.
5. **`_original_amps` persistence via existing KV blob machinery.** Persist as an inline
   column sibling of `excess_solar_active` at `energy.py:1839` / restored at `:1365-1366`,
   OR a single new KV `evse_original_amps_v1` with `_KNOWN_HOOKS`-registered
   save/restore. **`_original_amps` IS a `_prune_removed_evses` participant.**
6. **Capture sanity guard.** Session ENTRY: read current-limit entity. Fresh in-range →
   save. Stale/unavailable → save 48 (INFO). `< SOLAR_FOLLOW_CAPTURE_SANITY_A` (=20) →
   save 48 + `capture_rejected_low++` (WARN).
7. **Always-on timer** collapses the "restart within 60 s of release" hazard.
8. **`EVSE_ESTIMATED_POWER_W` never reaches the control law.** Add-back gates on
   `state.get("power_source") == "sensor"`; `switch_status` fallback EVSEs route to
   STALE, not add-0. Strict-fail direction per the operator's "conservative down / cautious
   up" ruling.

**Per-tick control law:**

```
0. STEP 0 edge-detector (drain-trip counter — derived by D1, not by the safety fn):
   curr = set(self._ev._paused_by_battery_drain)  # noqa: SLF001
   if self._prev_paused_by_battery_drain is None:
       # First-tick after boot: seed and skip counting (documented harmless loss
       # of ≤1 boot-crossing edge; spurious-per-restart is what we prevent —
       # at ~2.9 restarts/day it would swamp the real signal).
       self._prev_paused_by_battery_drain = curr
   else:
       newly_paused = curr - prev                   # EDGE, not level
       excess_set = set(self._ev._excess_solar_active)  # noqa: SLF001
       for evse_id in newly_paused:
           if evse_id in excess_set:
               self._drain_trips_during_follow += 1
       self._prev_paused_by_battery_drain = curr
   # Runs UNCONDITIONALLY, BEFORE the empty-set fast-path exit.

1. If _excess_solar_active empty AND _original_amps empty: return.

2. RESTORE PASS (iterate list(self._original_amps) — snapshot avoids mutation-
   during-iteration):
   for evse_id in list(self._original_amps):
       if evse_id in self._ev._excess_solar_active: continue  # session open
       # 2a — INV-SF-7 defer gate:
       if (self._ev._stronger_peer_holds(evse_id)     # noqa: SLF001
           or evse_id in self._ev._paused_by_dp):     # noqa: SLF001
           self._deferred_restore_evses.add(evse_id)
           continue
       # 2b — resolve entity; CLEAR-on-unresolvable:
       resolved_entity = self._current_limit_entities.get(evse_id)
       if (resolved_entity is None
           or evse_id not in self._ev._evse):        # noqa: SLF001
           self._original_amps.pop(evse_id, None)
           self._deferred_restore_evses.discard(evse_id)
           continue
       # 2c — restore:
       value = self._original_amps.pop(evse_id)
       self._deferred_restore_evses.discard(evse_id)
       emit number.set_value(resolved_entity, value)

3. If _excess_solar_active empty: return.

4. Read grid_W via D1.2. If unavailable for STALE_MAX_TICKS: no writes.

5. Build ELIGIBLE (commandable set):
   ELIGIBLE = {evse_id in _excess_solar_active
               where NOT _stronger_peer_holds(evse_id)
               AND evse_id not in _paused_by_dp
               AND _get_evse_state(evse_id).power_source == "sensor"}.
   If ELIGIBLE empty: increment stale_ticks; no writes, no captures. Return.

   Build DRAWING ⊆ ELIGIBLE:
   DRAWING = {evse_id in ELIGIBLE
              where _get_evse_state(evse_id).charging is True}.

6. N_eligible = len(ELIGIBLE); N_drawing = len(DRAWING); N_denom = max(1, N_drawing).

7. Compute add-back over DRAWING:
   add_back_w = 0.0
   for evse_id in DRAWING:
       s = self._ev._get_evse_state(evse_id)          # noqa: SLF001
       if s.get("power_source") == "sensor":  # belt-and-braces; DRAWING implies
           p = s.get("power") or 0.0
           try: add_back_w += float(p)
           except (TypeError, ValueError): pass
   S_eligible = (-grid_W) + add_back_w
   A_total_target = floor(S_eligible / (240 * SOLAR_FOLLOW_PHASES))

8. A_per_drawing_raw = A_total_target // N_denom.

9. For each evse_id in ELIGIBLE:
   a. Capture _original_amps[evse_id] per point 6 (with sanity guard) if unset.
   b. If evse_id in DRAWING: A_target = clamp(A_per_drawing_raw, MIN, MAX).
      Else (ELIGIBLE \ DRAWING — safe-parking): A_target = SOLAR_FOLLOW_MIN_AMPS.
   c. A_current = read current-limit entity (unavailable => skip this EVSE).
   d. Deadband: skip if |A_target - A_current| < SOLAR_FOLLOW_DEADBAND_A.
   e. Step law (INV-SF-5): up-gate + step-cap; down uncapped.
   f. Write-budget: skip + WARN if hour bucket exceeded.
   g. Emit number.set_value(current_limit_entities[evse_id], A_write).
   h. Schedule readback verify via async_call_later(SOLAR_FOLLOW_VERIFY_S).
```

**Pause ENTRY policy (a stronger peer starts holding a modulated EVSE mid-session):**
LEAVE `_original_amps`; do NOT restore before yielding. Rationale — (1) restoring 48 A
under a stronger owner risks fighting them (arbitrage CHARGE explicitly pauses to bound
compound load; a restore-then-yield would blip the pilot); (2) the stronger owner has
turned the SWITCH off, current-limit is cosmetic until switch re-closes; (3) when the
stronger owner releases: excess-solar still active → step 9 resumes from
`_original_amps`; not active → step 2 fires restore on the NEXT tick.

**Pause RELEASE policy (peer holds clear):** D1 discovers the eligibility change on the
next 60 s tick by re-reading `_stronger_peer_holds` and `_paused_by_dp` — no signal
subscription (would re-introduce the bootstrap-observer hazard). **Worst-case release
latency: 60 s.** Direction of harm: UNDER-draw only. Charger sits at a solar-throttled
limit for up to 60 s while no stronger owner holds it. Fleet math still bounded by
`S_eligible` — cannot over-draw. INV-SF-4 unchanged — cannot pull from battery.

**Q5 must-start-release corner:** the 60 s bound survives DP must-start releases because
(a) DP discards `_paused_by_dp` at `energy.py:5089` and `:5116` when the must-start-by
timer fires (or on the paused-aware exit predicate), and (b) the blind-window grant path
uses the `_blind_window_liveness_ride` latch at `energy_pool.py:989-999` (sets
`will_pause=False`, discards prior `_paused_by_blind_window`). Both release paths mutate
the sets in the same tick the release logic runs. D1's next 60 s tick observes cleared
membership. `_blind_window_liveness_ride` is a GRANT, not a hold — correctly outside
`_stronger_peer_holds` and correctly does not gate D1.

**One-tick lag on startup transition** (bay transitions from non-DRAWING to DRAWING):
≤60 s; self-corrects; pre-written MIN command caps plug-in transient at 1.44 kW/bay
(not 11.5 kW); errs toward under-draw for the newly-drawing bay, which INV-SF-4 permits.

**D1.2 — surplus signal.**

* PRIMARY: `sensor.mains_vue_3_power_minute_average` (Emporia mains, signed **W**,
  negative = export). **60 s AVERAGE** — informs INV-SF-5.
* FALLBACK: `sensor.envoy_482543015950_current_net_power_consumption` (signed **kW**;
  ×1000 conversion in the fallback branch). Availability: existing `envoy_available`
  reliability signal (NOT `sensor.ura_energy_coordinator_envoy_status`).
* Fences: NOT `balanced_net_power_consumption`; NOT SPAN; NOT
  `sensor.mainw_vue_balance_power_minute_average` (dead/typo).
* Add-back inline over DRAWING only. Do NOT call `current_charging_load_w()`
  (fleet-wide). Sum uses `self._ev._get_evse_state(evse_id)` and requires
  `power_source == "sensor"`.

**D1.3 — self-consistency stop.** Both PRIMARY and FALLBACK unavailable OR ELIGIBLE
empty due to per-EVSE `switch_status` fallback → increment `_stale_ticks`; at
`SOLAR_FOLLOW_STALE_MAX_TICKS` (=2) → no writes, WARN. Fail-safe.

**D1.4 — current-limit entities.** Added to `DEFAULT_EVSE_ENTITIES` at
`energy_pool.py:168-183` under new key `current_limit`:
- `garage_a`: `number.garage_a_evse_emporia_wifi_garagea_current_limit`
- `garage_b`: `number.garage_b_evse_emporia_wifi_garageb_current_limit`
Passed to `SolarFollowController.__init__` as `current_limit_entities`. L1 chargers
excluded.

**D1.5 — Solcast next-hour stop signal.** New `CONF_SOLCAST_NEXT_HOUR_ENTITY` (rung 2)
populated from `sensor.solcast_pv_forecast_forecast_next_hour`. Consumed by D2.

**D1.6 — bounded in-controller write-verify.** After every write,
`async_call_later(SOLAR_FOLLOW_VERIFY_S=8)` reads back and checks ±1 A tolerance. WARN +
counter on mismatch. Does NOT extend `_maybe_schedule_write_verify` (surface-keyed).

**D1.7 — write-budget containment.** `SOLAR_FOLLOW_MAX_WRITES_PER_HOUR_PER_EVSE` (=30,
rung 1). Hour bucket per EVSE.

**D1.8 — status-sensor observability.**
`sensor.ura_energy_coordinator_solar_follow` attributes:

* `active: bool`
* `eligible_evses: list[str]` — the ELIGIBLE (commandable) set this tick.
* `drawing_evses: list[str]` — the DRAWING subset (counts toward allocation).
* `safe_parked_evses: list[str]` — ELIGIBLE \ DRAWING (bays receiving MIN safe-parking).
* `s_eligible_kw: float`
* `deferred_restore_evses: list[str]` — **gauge, not counter.** Membership: (a)
  `_original_amps[evse_id]` set, (b) `evse_id ∉ _excess_solar_active`, (c)
  `_stronger_peer_holds OR ∈ _paused_by_dp`. Discharge: (i) peer clears → step 2c
  restore, (ii) EVSE re-enters `_excess_solar_active`, (iii) config prune → step 2b
  clear-branch.
* `capture_rejected_low: int` — monotone; discrete event, no discharge.
* **`drain_trips_during_follow: int` — monotone, derived by D1's STEP 0 edge-detector.**
  Wire point ENTIRELY inside `SolarFollowController`. Zero edits to
  `determine_battery_drain_actions`. Explicitly UNDER-counts sub-tick flap; drain-
  protection pauses are STICKY until release conditions in `energy_pool.py:2000` are met
  so sub-tick flap doesn't occur; under-count is safe direction for a "are trips
  frequent?" signal.
* `writes_per_hour_per_evse: dict[str, int]`
* `current_amps: dict[str, int]`
* `original_amps: dict[str, float]`
* `stale_ticks: int`
* `excluded_switch_status_evses: list[str]` — EVSEs excluded by the `power_source !=
  "sensor"` gate.

**D1.9 — non-peer-hold owner accounting.** `_stronger_peer_holds` returns True for six
owners: `battery_drain`, `fill_priority`, `grid_cap`, `arbitrage`, `load_shed`,
`blind_window`. Plus inline `_paused_by_dp`. That leaves three EVSE-touching owners the
D1 fence accounts for here:

* **`_paused_by_us` (TOU).** NOT in `_stronger_peer_holds`. Benign — TOU is subordinate
  to excess-solar in-session: peak branch `continue`s on `_excess_solar_active` at
  `:906`; claim path discards `_paused_by_us` at `:1633-1635`. Restart-crossed corner
  unreachable — `save_evse_state` writes `paused_by_us` and `excess_solar_active`
  atomically (`database.py:4526-4535`).
* **`_proactive_offpeak_holds`** — intent-state, correctly excluded.
* **`_blind_window_liveness_ride`** — GRANT, correctly excluded (see Q5 above).

**Constants (D1 knob ladder):**

| Name | Rung | Value | Why this rung |
|---|---|---|---|
| `SOLAR_FOLLOW_TICK_S` | 1 | 60 | Protocol; matches Emporia 1-min average |
| `SOLAR_FOLLOW_MIN_AMPS` | 1 | 6 | J1772 pilot floor, hardware |
| `SOLAR_FOLLOW_MAX_AMPS` | 1 | 48 | Service ceiling |
| `SOLAR_FOLLOW_RESTORE_AMPS` | 1 | 48 | Fallback default |
| `SOLAR_FOLLOW_CAPTURE_SANITY_A` | 1 | 20 | Anti-captured-throttle |
| `SOLAR_FOLLOW_DEADBAND_A` | 3 (Number) | 1 | Operator-tunable |
| `SOLAR_FOLLOW_UP_STEP_A` | 3 (Number) | 2 | Operator-tunable |
| `SOLAR_FOLLOW_UP_MIN_TICKS` | 3 (Number) | 3 | Operator-tunable |
| `SOLAR_FOLLOW_STALE_MAX_TICKS` | 1 | 2 | Fail-safe |
| `SOLAR_FOLLOW_VERIFY_S` | 1 | 8 | Protocol |
| `SOLAR_FOLLOW_MAX_WRITES_PER_HOUR_PER_EVSE` | 1 | 30 | Safety containment |
| `SOLAR_FOLLOW_PHASES` | 1 | 1 | 240 V L2 single-phase (US) |
| `SOLAR_FOLLOW_NEXTHOUR_FLOOR_W` | 1 | 1000 | Protocol |
| `CONF_SOLCAST_NEXT_HOUR_ENTITY` | 2 | — | Per-deployment |
| `CONF_SOLAR_FOLLOW_ENABLED` | 3 (Switch) | True | Kill-switch |

**D1 acceptance (discriminating):**

* `test_solar_follow_writes_only_number_set_value_never_switch` (INV-SF-1)
* `test_solar_follow_no_writes_when_both_sets_empty` (INV-SF-2)
* `test_solar_follow_restore_after_restart_within_release_window` (INV-SF-3)
* `test_solar_follow_bounds_draw_by_surplus_hardware_floor_exception` (INV-SF-4
  parametric, with/without peer-held-drawing EVSE, N ∈ {1, 2})
* `test_solar_follow_up_gated_down_immediate` (INV-SF-5)
* `test_solar_follow_two_evses_split_surplus` (INV-SF-6, fixture: both bays
  `charging=True, power > 100 W`)
* `test_solar_follow_two_evses_below_floor_holds_at_min` (INV-SF-6 degenerate; fixture:
  both DRAWING at low share)
* `test_solar_follow_capture_rejects_stale_low_value` (A-HIGH-3)
* `test_solar_follow_stops_writing_when_both_sensors_unavailable` (D1.3)
* `test_solar_follow_write_budget_containment` (D1.7)
* `test_solar_follow_never_feeds_evse_estimated_power_into_control_law`
* `test_solar_follow_load_shed_deferral_clears_on_restart` (benign restart-restore)
* **T-STALE-1** `test_solar_follow_excludes_evse_with_switch_status_fallback` — garage_b
  fixture: `{charging:True, power:7600, power_source:"switch_status"}`; assert excluded
  from ELIGIBLE, `excluded_switch_status_evses` contains it, `stale_ticks` increments,
  no writes.
* **T-ITER-1** `test_solar_follow_restore_pass_iterates_snapshot` — pre-load two
  restore entries, both eligible for restore in one tick; assert no `RuntimeError` and
  both clear.
* **T-PEER-1..6** — peer-hold subordination + capture preservation + prune-during-
  deferral (see §7 test list).
* **T-DRAIN-1** `test_drain_protection_still_pauses_during_solar_follow` — drives real
  `EVChargerController.determine_battery_drain_actions` (not a fake). Assert (i)
  `switch.turn_off` in returned actions, (ii) `_paused_by_battery_drain` contains EVSE,
  (iii) `_drain_trips_during_follow` incremented, (iv) INV-SF-7 fires on next D1 tick
  (EVSE peer-held, ELIGIBLE excludes, no write).
* **T-DRAIN-2** `test_drain_trips_during_follow_counter_increments_once_per_event` —
  7-tick sequence [`{}, {a}, {a}, {}, {a}, {a,b}, {a,b}`]; correct counter=3; level-bug
  counter=5.
* **T-DRAIN-3** `test_drain_trips_during_follow_first_tick_seeds_without_counting` —
  restart into already-drain-paused session; tick 1 counter still 0; fresh trip
  post-boot → 1.
* **T-DRAIN-4** `test_drain_trips_during_follow_undercounts_sub_tick_flap_is_expected` —
  sub-tick pause+release between two D1 ticks; counter unchanged. Test docstring names
  §5 known-couplings item 10 (documented sampling-floor under-count).
* **T-DRAW-1** `test_solar_follow_full_surplus_to_single_drawing_bay_when_other_bay_idle`
  — garage_a `charging=True, power=5000`, garage_b `charging=False, power=0`,
  `grid_W=-5000`. Under Rev-8 correct: garage_a commanded **41 A** (9.84 kW), garage_b
  commanded **6 A** safe-parking. Under bug (denominator = `len(ELIGIBLE)`): garage_a
  commanded **20 A**. Discriminating 41 vs 20.
* **T-DRAW-2** `test_solar_follow_startup_transition_re_splits_next_tick` — tick 1 as
  T-DRAW-1; tick 2 garage_b transitions to DRAWING at 1440 W (pre-written 6 A × 240 V).
  Allocation re-splits.
* **T-DRAW-3** `test_solar_follow_all_idle_commands_min_safe_parking` — both
  `charging=False, power=0`; both commanded 6 A safe-parking; no divide-by-zero.

**Live validation:** sunny-day sensor attributes including `drawing_evses`,
`safe_parked_evses`, `s_eligible_kw`, `stale_ticks`, `excluded_switch_status_evses`,
`drain_trips_during_follow`; one-bay-active case; startup transition; release-edge
restore; INV-SF-7 if arbitrage overlap; BLOCKING-1 confirmation if Emporia cloud blip;
drain-trip counter per-event increments; plug-in transient bounded at 1.44 kW/bay for
≤60 s lag.

### D2 — Release-gate hysteresis (drain-protection skip REMOVED per PB-1 REJECTED)

**Where:** `EVChargerController.determine_excess_solar_actions:1685-1699` (release leg)
ONLY. `determine_battery_drain_actions:1776-1959` is NOT touched by this cycle
(drain-protection is a strong peer per INV-SF-7 and ships byte-identical).

**Changes:**

1. Add `_conditions_met_false_streak_ticks: dict[str, int]` and
   `_excess_solar_started_at: dict[str, datetime]`.
2. Stamp `_excess_solar_started_at[evse_id]` on session entry. Persist per-EVSE as an
   inline column sibling of `excess_solar_active`.
3. Release condition fires ALL of:
   - `not conditions_met` OR `solcast_next_hour_w < SOLAR_FOLLOW_NEXTHOUR_FLOOR_W`
   - streak `>= SOLAR_RELEASE_MIN_TICKS` (=3)
   - session age `>= SOLAR_RELEASE_MIN_ON_S` (=300)
4. On `conditions_met` True: reset streak.

**Discharge rule** per `feedback_suppression_needs_discharge`: streak dict RAM-only
(resets on restore); `_excess_solar_started_at` persisted so min-on-time honoured across
restart.

**Design provenance (P6 shape-match):** anti-flap duration-threshold pattern per
`PLANNING_v4.7.x_APPLIANCE_SCHEDULER.md:41` (`flashg1/SolarCharger`). Recorded so future
reviewers know the pattern is field-tested prior art, not re-derived.

**Constants:** `SOLAR_RELEASE_MIN_TICKS` (rung 1, 3); `SOLAR_RELEASE_MIN_ON_S`
(rung 3, 300).

**D2 acceptance:**

* `test_release_streak_gated` — SOC 95→94→95→94 over 5 ticks; no turn-off. Under
  no-hysteresis, first 94 fires turn-off.
* `test_release_min_on_time` — session starts, SOC drops 30 s later and stays; no
  turn-off until 300 s.
* `test_release_streak_persists_min_on_time_across_restart` — `_excess_solar_started_at`
  persists across restart.
* **Live:** on first cloudy transition day, membership persists through single-SOC-
  point dips of < 180 s.

**Non-substitutability:** D2 is finesse. D1 is the mechanism that makes the economics
work; D2 stops the flap.

---

## 4. Non-goals (explicit)

* NOT starting/stopping charges. NOT coordinating with DP. NOT changing the excess-solar
  TRIGGER at `energy_pool.py:1574-1579`. NOT changing the EC 5-minute tick. NOT extending
  `_maybe_schedule_write_verify`. NOT wiring HVAC coupling. NOT demoting
  `evse_battery_hold`. NOT changing `ev_battery_drain_soc` live value (still 80). NOT
  changing R1 / R3 sources (see `PLANNING_dp_drain_target_mis_sourcing.md`). NOT touching
  `sensor.mainw_vue_balance_power_minute_average`. NOT using
  `balanced_net_power_consumption`, SPAN, or `sensor.ura_energy_coordinator_envoy_status`.
  NOT wiring L1 chargers. NOT introducing a new `persistence_kind`. NOT auto-remediating
  offline Garage A / SPAN observability gap. NOT feeding `EVSE_ESTIMATED_POWER_W` into
  D1's control law (including via the v4.2.19 `power_source="switch_status"` fallback in
  `_get_evse_state:690-697`). NOT introducing priority ordering. NOT adding
  `_paused_by_dp` to `_stronger_peer_holds`. NOT re-solving compound-load in D1
  (see §5 known-couplings item 8). NOT building a per-EVSE "no-interference latch". NOT
  using `current_charging_load_w()` for the add-back.
* NOT modifying `determine_battery_drain_actions:1776-1959`. Zero edits, zero counter
  bumps, zero comments, zero re-imports. Solar-follow YIELDS to drain-protection via
  INV-SF-7; does NOT suppress it; does NOT observe its actions from inside its function
  body. Membership set `_paused_by_battery_drain` is D1's ONLY window into it, sampled
  from D1's tick.
* NOT modifying `solar_replenishing` (`energy.py:5823`, `energy_pool.py:2000`).
* NOT shortening D1's 60 s tick or subscribing to owner-set mutation events to catch
  sub-tick drain-protection flap. The under-count is documented; the pause mechanism
  does not produce sub-tick flap.
* NOT modifying the excess-solar CLAIM path at `energy_pool.py:1650-1656`. Rev-8 fixes
  the empty-bay defect in the CONSUMER (D1) only; the producer is byte-identical. Adding
  a plug-presence check to the CLAIM path is a separate cycle.

---

## 5. Known couplings

1. DP gate 6 (`energy_drain_precedence.py:652`) — L1-only crossover at 12.5 A. Documented,
   not coordinated. Same gate that MASKED the drain-target defect on 2026-08-20 — a
   diagnostician chasing "why did DP not drain" must know to check for throttled sessions.
2. DP gate 8 charge_hours blows up at low amps. Fit test may fail earlier at 6 A.
3. `_dp_house_load_kw` biased other way — non-monotone in amps.
4. `EVSE_ESTIMATED_POWER_W = 7600` never in D1's control law (double-closed via
   `power_source` gate). DP may still consume the fabricated value on Emporia outage —
   pre-existing pathology D1 exposes but does not create.
5. `evse_battery_hold` engages at 6 A — amp-independent.
6. Emergent actuation precedence.
7. INV-YIELD-1/2 (audit §6.4). D1 downstream of CLAIM; INV-SF-7 strictly stricter.

8. **Compound-load protection — grid_cap (v4.0.18) + D4 (v4.5.0) together (Rev-9
   corrected attribution).** Historical git-log verified:
   - `_paused_by_grid_cap` introduced in **v4.0.18** (commit `1a499f0b8`, "Fan
     manual-off cooldown + EV grid import cap"). Pause site at `energy_pool.py:1723-1735`:
     `if net_power_kw > grid_cap_kw: switch.turn_off + _paused_by_grid_cap.add`. This
     is a **REACTIVE** grid-import ceiling.
   - `_paused_by_arbitrage` introduced in **v4.5.0** (commit `f3deabc84`, the
     battery-strategy redesign that became D4). Live compound-load mutex at
     `energy.py:6240-6263` (`charge_from_grid` chokepoint, phase-label-independent) +
     `:6290-6328` (hardware read OR fail-closed latch) + `:6341-6365` (EV pauses
     dispatched before battery actions). This is **PREVENTIVE** — never creates the
     combination.
   - **They are OVERLAPPING, not proven redundant.** grid_cap is REACTIVE (measures net
     import, pauses after the fact); D4 is PREVENTIVE (never creates the combination).
     Different mechanisms.
   - **Breaker-protection caveat, stated plainly:** at a 5-minute decision cadence,
     neither is convincing for BREAKER protection specifically — a breaker trips in
     seconds. What D4 genuinely buys is not creating the combination in the first place;
     what grid_cap buys is bounding sustained import. The "134 A main breaker" framing
     the D4 memo used oversells both mechanisms; the honest story is that both bound
     sustained overdraw within their own cadence, and the primary protection is the
     panel breaker itself.
   - **Consequence for D1's scope:** compound-load import IS ALREADY BOUNDED by
     `_paused_by_grid_cap` (v4.0.18) AND the v4.5.0 mutex TOGETHER. D1 does NOT re-solve
     compound-load safety. INV-SF-7 subordinates D1 to `_paused_by_arbitrage` via
     `iter_peer_holds()` (and to `_paused_by_grid_cap` for the same reason). Both are
     strong peers.
   - **Correction on record:** Rev-4 of the combined plan cited `PLANNING_v4.5.0_
     TRANSITION_NOTES.md:60` (the D4 memo) as sole authority for "compound load is
     handled." Nobody checked what came before D4. `_paused_by_grid_cap` predates D4
     by five minor versions and covers the same hazard reactively. The scope-narrowing
     for D1 is still correct (D1 does not re-solve compound load); the attribution is
     grid_cap AND D4 together, not D4 alone.
9. `_pause_dispatch_ts` / `_observed_off_since_pause` (`energy_pool.py:275-278`) — the
   repo does NOT trust "peer-held ⇒ not drawing". SF7-B1's premise (operator re-enabling
   a paused charger from the Emporia app) is exactly the class of race these fields
   exist for. D1's ELIGIBLE-scoped add-back handles the physical draw by classifying it
   as house load rather than trying to detect the manual override.
10. **`_paused_by_load_shed` is `persistence_kind="none"`** — a load-shed-deferred EVSE
    loses the hold membership on restart. First post-restart tick's step 2b fires the
    restore. Benign because it restores to the captured original ≤48 A, not a spurious
    48 A blast under a still-active shed. Recorded.
11. **`solar_replenishing` already exists on the drain-protection RESUME side**
    (`energy.py:5823`, `energy_pool.py:2000`). **LEAVE ALONE.** D1 does not feed or read
    this signal. Reasoning: (a) it uses `_surplus_pct` (modelled) + `battery_power_w`
    (physical), not Emporia mains — adding D1 to its inputs would import D1's signal
    characteristics into a rule that already has its own sources; (b) fires on RELEASE
    side; D1 has no business influencing when a safety gate releases (same reasoning as
    PB-1 rejection); (c) no measured evidence of a defect this would fix; adding a
    coupling without a fired trigger is premature integration.
12. **`_paused_by_battery_drain` observed by D1 through set-membership sampling only.**
    D1 does not observe the pause dispatch, does not hook into the pause site, does not
    modify the set. Coupling is READ-ONLY set observation on D1's own tick cadence;
    under-counts sub-tick flap (documented safe direction).
13. **Empty-bay ELIGIBLE-not-DRAWING (Rev-8 close).** `_excess_solar_active.add`
    (`energy_pool.py:1656`) happens on switch-on without a plug check; an empty bay is
    ELIGIBLE but not DRAWING. D1's DRAWING subset is what the allocation denominator
    uses; safe-parking MIN command caps the plug-in transient. Distinct failure class
    from the `power_source == "sensor"` gate (that filters FABRICATED numerator; this
    filters ZERO-power denominator inflation).

### 5a. Open question for a future supersession audit (Rev-9 add, house-rule compliant)

**`grid_cap` vs `_paused_by_arbitrage` overlap — did v4.5.0 D4 duplicate a hazard v4.0.18
already covered, and if so which is the better mechanism?**

- **NOT a delete candidate** — per CLAUDE.md's post-ship supersession rule, dead-or-
  overlapping is never sufficient to remove, and neither is dead here; both are live.
- Framing for the audit: grid_cap is REACTIVE (nets to grid-import ceiling); D4 mutex is
  PREVENTIVE (never creates the compound load). Different mechanisms, overlapping
  purpose. The audit answers: which one bounds the compound-load hazard better, under
  what conditions, and does keeping both create a coordination burden.
- Trigger for the audit: a fired incident where the two mechanisms disagree on an EVSE's
  state, OR a cycle proposing to touch either that needs the semantics resolved first.
- Not this cycle's work. Read-only audit; separate cycle.

---

## 6. Docs drift to fix in-cycle

* `energy_pool.py:_stronger_peer_holds` docstring says "the five", loop returns six
  (SF7-L1). Add `blind_window` to the docstring.

(Other docs drift belongs to the DP fix cycle —
`PLANNING_dp_drain_target_mis_sourcing.md`.)

---

## 7. Test plan summary

Behavioural, MUTATION-VERIFIED. `PYTHONDONTWRITEBYTECODE=1` + clear `__pycache__` before
each drill.

D1: `test_solar_follow_writes_only_number_set_value_never_switch`;
`test_solar_follow_no_writes_when_both_sets_empty`;
`test_solar_follow_restore_after_restart_within_release_window`;
`test_solar_follow_bounds_draw_by_surplus_hardware_floor_exception`;
`test_solar_follow_up_gated_down_immediate`;
`test_solar_follow_two_evses_split_surplus` (both DRAWING);
`test_solar_follow_two_evses_below_floor_holds_at_min`;
`test_solar_follow_capture_rejects_stale_low_value`;
`test_solar_follow_stops_writing_when_both_sensors_unavailable`;
`test_solar_follow_write_budget_containment`;
`test_solar_follow_never_feeds_evse_estimated_power_into_control_law`;
`test_solar_follow_load_shed_deferral_clears_on_restart`;
T-STALE-1; T-ITER-1;
T-PEER-1 `test_solar_follow_no_write_when_peer_holds_arbitrage`;
T-PEER-2 `test_solar_follow_zero_write_and_original_preserved_on_mid_session_peer_add`;
T-PEER-3 `test_solar_follow_no_write_under_paused_by_dp_hold_only`;
T-PEER-4 `test_solar_follow_restore_deferred_under_peer_hold_fires_on_release`;
T-PEER-5 `test_solar_follow_add_back_and_denominator_both_over_eligible`;
T-PEER-6 `test_solar_follow_deferred_restore_clears_on_config_prune`;
T-DRAIN-1 `test_drain_protection_still_pauses_during_solar_follow` (drives REAL fn);
T-DRAIN-2 `test_drain_trips_during_follow_counter_increments_once_per_event`;
T-DRAIN-3 `test_drain_trips_during_follow_first_tick_seeds_without_counting`;
T-DRAIN-4 `test_drain_trips_during_follow_undercounts_sub_tick_flap_is_expected`;
T-DRAW-1 `test_solar_follow_full_surplus_to_single_drawing_bay_when_other_bay_idle`;
T-DRAW-2 `test_solar_follow_startup_transition_re_splits_next_tick`;
T-DRAW-3 `test_solar_follow_all_idle_commands_min_safe_parking`.

D2: `test_release_streak_gated`; `test_release_min_on_time`;
`test_release_streak_persists_min_on_time_across_restart`.

---

## 8. Review plan — Tier 3, four framing-disjoint passes

* **A — local correctness.** ELIGIBLE-scoped writes + DRAWING-scoped allocation +
  DRAWING-scoped add-back; step 2a/2b/2c convention; snapshot iteration; unit
  conversions; STEP 0 edge-detector rules (edge-not-level; seed-and-skip; snapshot
  updated every tick regardless of fast-path exit); `max(1, N_drawing)` divide-by-zero
  guard; safe-parking command routing to ELIGIBLE \ DRAWING.
* **B — integration / state-machine + byte-identical no-op.** Class shape; SLF001;
  restart paths; must-start-release corner (Q5). **`determine_battery_drain_actions:
  1776-1959` and `solar_replenishing` path (`energy.py:5823` + `energy_pool.py:2000`)
  BOTH byte-identical.** Excess-solar CLAIM path `:1650-1656` byte-identical (producer
  untouched — Rev-8's fix lives in D1). The counter's edge-detector is in
  `SolarFollowController.STEP 0`, not inside the safety function. Any diff at the safety
  function fails the pre-deploy grep.
* **C — REAL per-site source mutation.**
  - **C17:** replace step-5 ELIGIBLE with raw `self._ev._excess_solar_active` (drop
    `_stronger_peer_holds` + `_paused_by_dp` + `power_source` filters at step 5 ONLY;
    DO NOT touch step 2a or step 7 add-back) → T-PEER-1, T-PEER-2, T-PEER-3, T-PEER-5,
    T-STALE-1 must fail. T-PEER-4 NOT in this list (exercises step 2a).
  - **C17b:** delete step-2a peer-hold guard ONLY → T-PEER-4 must fail.
  - **C17c:** replace ELIGIBLE-scoped add-back with fleet-wide
    `current_charging_load_w()` (keep denominator = `len(ELIGIBLE)`) → T-PEER-5 must
    fail. Anchors SUM half of SF7-B1.
  - **C17d:** replace `N_eligible = len(ELIGIBLE)` with
    `len(self._ev._excess_solar_active)` (keep add-back over ELIGIBLE) → T-PEER-5 must
    fail. Anchors DENOMINATOR half of SF7-B1, DISJOINT from C17c's SUM half.
  - **C17e:** delete step-2b's `resolved_entity is None or evse_id not in self._ev._evse`
    CLEAR branch → T-PEER-6 must fail.
  - **C17f:** delete `power_source == "sensor"` clause from step 5(d) → T-STALE-1 must
    fail.
  - **C18:** re-insert the deleted PB-1 skip into `determine_battery_drain_actions`
    head-of-loop → T-DRAIN-1 must fail. Anchors PB-1 REJECTED — any future PR that
    re-introduces the skip trips this drill.
  - **C19:** inside `SolarFollowController.STEP 0`, replace `newly_paused = curr - prev`
    with `newly_paused = curr` (level bug) → T-DRAIN-2 must fail.
  - **C19b:** delete the seed-and-skip branch so first tick counts pre-existing
    membership → T-DRAIN-3 must fail.
  - **C20:** revert D1's `N_denom = max(1, N_drawing)` to `len(ELIGIBLE)` → T-DRAW-1
    must fail (garage_a=20 instead of 41).
  - **C20b:** change step 9b's non-DRAWING branch from `A_target = MIN` to `continue`
    → T-DRAW-2 must fail (plug-in transient uncapped).
  - **C20c:** replace `max(1, N_drawing)` with `N_drawing` → T-DRAW-3 must fail (crash).
* **D — adversarial completeness / diff-blind.** Re-enumerate all `_excess_solar_active`
  discard sites: three at `energy_pool.py:1369`/`:1564`/`:1699`; restart-reconciliation
  at `energy.py:5183-5225` as a separate vector; `_prune_removed_evses` as a fifth
  vector. Re-enumerate every place `_excess_solar_active` is READ from OUTSIDE
  `SolarFollowController` and confirm each reader subordinates to strong-peer safety
  correctly or is not a safety gate (PB-1 was a solar-active-membership READ used to
  skip a safety gate — the class of defect D should keep hunting). Re-enumerate every
  READ / WRITE of `_paused_by_battery_drain` from OUTSIDE `determine_battery_drain_actions`;
  confirm all readers (including D1's STEP 0) are passive observers. Enumerate every
  code path that adds to `_excess_solar_active` and confirm none establish plug presence
  (source of the "empty bay is ELIGIBLE" fact D1 has to cope with; producer-side fix is
  a separate cycle). Legal-config combinatorial: min == max, deadband > (max-min),
  `SOLAR_RELEASE_MIN_ON_S` > natural session length, N=3 (future chargers). Every leak →
  concrete legal-config repro.

**Orchestrator pre-deploy verification:** re-grep the six peer-hold owner sets +
`_paused_by_dp`; run mutation drills C17/b/c/d/e/f + C18 + C19 + C19b + C20 + C20b +
C20c; zero-call-sites confirmation against `current_charging_load_w()` and bare
`EVSE_ESTIMATED_POWER_W` inside `SolarFollowController`; grep-check that
`determine_battery_drain_actions:1776-1959` has ZERO diff; grep-check that
`_drain_trips_during_follow` increment site occurs exactly ONCE, inside
`SolarFollowController.STEP 0`, and ZERO occurrences under
`energy_pool.py:1776-1959`; grep-check that `solar_replenishing` path has ZERO diff;
grep-check that excess-solar CLAIM path `energy_pool.py:1650-1656` has ZERO diff
(producer untouched); grep-check D1's step 8 uses `max(1, N_drawing)` (not
`len(ELIGIBLE)`, not bare `N_drawing`); grep-check D1's step 9b has an `else: A_target
= SOLAR_FOLLOW_MIN_AMPS` branch (not `else: continue`); diff-check against §11 register.
**Operator checkpoint BEFORE deploy.**

---

## 9. REUSE vs NEW

| Item | Verdict | Cite |
|---|---|---|
| `PoolOptimizer` shape (save/restore + unavailable-keep-state) | REUSE (shape only) | `energy_pool.py:58-160` |
| `_execute_service_action` | REUSE | — |
| `_excess_solar_active` membership | REUSE | `energy_pool.py:202` |
| Per-EVSE inline persistence for `_original_amps` | REUSE | `energy.py:1839`, `:1365-1366` |
| `_get_evse_state` | REUSE | `energy_pool.py:650` |
| `power_source` field discrimination | REUSE | `energy_pool.py:700-706` |
| `_get_evse_state(...).charging` as DRAWING predicate | REUSE | `energy_pool.py:691` |
| `_ev_battery_drain_soc` at R1/R3 (unchanged; DP fix's concern) | REUSE unchanged | — |
| TOU peak-clear | REUSE | `energy_pool.py:1354-1374` |
| `_stronger_peer_holds` + inline `_paused_by_dp` (6 owners including `battery_drain`) | REUSE | `energy_pool.py:383-412`, `:1621-1631` |
| Cross-class SLF001 convention | REUSE | `energy.py:4141`, `:4517`, `:4929`, `:5031` |
| Anti-flap duration threshold (D2 shape-match from `flashg1/SolarCharger`) | REUSE | `PLANNING_v4.7.x_APPLIANCE_SCHEDULER.md:41` |
| Live compound-load mutex (D4, v4.5.0) | REUSE unchanged | `energy.py:6240-6263` + `:6290-6328` + `:6341-6365` |
| **Grid-import cap (v4.0.18, predates D4)** | REUSE unchanged | `energy_pool.py:1723-1735`. Overlapping with D4 for compound-load coverage; see §5 item 8 and §5a open question. |
| `_prune_removed_evses` participation for `_original_amps` | REUSE mechanism | `energy_pool_owners.py:345+` dict-kind owners |
| `determine_battery_drain_actions` (byte-identical) | REUSE unchanged | `energy_pool.py:1776-1959` |
| `solar_replenishing` on RESUME side (unchanged) | REUSE unchanged | `energy.py:5823`, `energy_pool.py:2000` |
| `_paused_by_battery_drain` set-membership as an observable | REUSE (READ-ONLY, from D1's tick) | Mutated inside `determine_battery_drain_actions`; D1's STEP 0 samples without writing |
| Excess-solar CLAIM path (byte-identical) | REUSE unchanged | `energy_pool.py:1650-1656` |
| `SolarFollowController` class | NEW | — |
| Session-scoped 60 s timer (always-on, empty-set fast path) | NEW | — |
| ELIGIBLE-scoped surplus add-back with `power_source` gate | NEW (inline sum) | — |
| DRAWING subset derivation inside D1 | NEW (inline in step 5) | — |
| `max(1, N_drawing)` divide-by-zero guard | NEW (step 6) | — |
| Safe-parking MIN command for ELIGIBLE \ DRAWING | NEW (step 9b) | Caps plug-in transient at 1.44 kW/bay for ≤60 s |
| Release-gate streak + min-on-time | NEW | — |
| Solcast next-hour stop | NEW | — |
| `SOLAR_FOLLOW_*` constants + Numbers | NEW | — |
| `drain_trips_during_follow` counter derived by D1's STEP 0 edge-detector | NEW | Inside `SolarFollowController`; preserves zero-diff on safety function |
| `drawing_evses` + `safe_parked_evses` status attributes | NEW | Observability for DRAWING/ELIGIBLE distinction |
| Bounded in-controller readback verify | NEW | — |

---

## 10. Design pushback recorded

### PB-1 — drain-protection `_excess_solar_active` skip — REJECTED (operator-ruled)

**Operator challenge (2026-08-23):** *"What's wrong with turning it off when it's
supposed to be turned off?"*

**Evidence:**

1. **INV-SF-7 contradiction.** `_paused_by_battery_drain` is one of the six owners
   `EV_REGISTRY.iter_peer_holds()` returns (`energy_pool_owners.py:262-269`), so it IS
   a strong peer. INV-SF-7 says solar-follow yields to any strong peer. PB-1's skip
   said drain-protection should yield to solar-follow. Circular precedence; an
   invariant with an exception carved out for one of its own owners is not an invariant.
2. **Premise weakest exactly when it fires.** Drain-protection triggers on physical
   evidence (`charging AND battery discharging AND SOC<threshold`), no EV attribution.
   PB-1's argument was "a correctly-sized solar-follow session cannot be the cause";
   that assumes surplus reading accuracy. Skew probe measured 6.7× degradation in
   fast-solar regime (241 W median → 1,610 W median). Daytime battery discharge usually
   means solar is dropping fast — precisely when the reading is worst. Same reasoning
   that killed the earlier agreement-gate design; symmetric mistake in opposite
   direction.
3. **Cost asymmetry.** Spurious pause: cents. Wrong skip: pull battery below floor into
   potentially expensive windows. Trading bounded small loss for unbounded on a
   degraded measurement is not a favourable trade.

**Replacement:** telemetry counter `drain_trips_during_follow` derived by D1's STEP 0
edge-detector (INSIDE `SolarFollowController`, NOT inside the safety function). A trip
while solar-follow is active is EVIDENCE the ELIGIBLE-scoped surplus sizing was wrong;
suppressing the pause would destroy that information.

**Retracted analogy:** the fill-priority `_excess_solar_active` skip at `:2214-2219` is
NOT a template for D2. Fill-priority is a STRATEGY owner; drain-protection is a SAFETY
gate; safety gates do not defer to strategy layers.

**Retracted framing:** earlier revisions described `determine_battery_drain_actions` as
"runs after solar in the tick, so it gets the last word" as if that were a defect. It
is not — that is precedence working as designed. INV-SF-7 encodes it.

### PB-2 — sub-tick clock seam — WITHDRAWN.

### Signal design (either-or, no agreement gate) — RECORDED.

---

## 11. Closed concerns — must stay closed

| Concern | Round originally closed | The one-line invariant that keeps it shut |
|---|---|---|
| `EVSE_ESTIMATED_POWER_W` reaches D1's control law | Combined-plan Rev-2 (A-MED-1); re-opened Rev-3 via `current_charging_load_w()`; re-opened Rev-4 via `_get_evse_state.charging` flag; re-closed Rev-5 | D1's surplus add-back sums ONLY EVSEs whose `_get_evse_state.power_source == "sensor"`. Future-revision grep-check for `EVSE_ESTIMATED_POWER_W`, `current_charging_load_w`, `switch_status`, and `state.get("charging")` in D1's diff. |
| Fleet-wide surplus add-back over-drawing | Combined-plan Rev-4 (SF7-B1) | `S_eligible` sums add-back ONLY over DRAWING (⊆ ELIGIBLE); §4 non-goal against `current_charging_load_w()`. |
| New `persistence_kind` introduced | Combined-plan Rev-2 (A-HIGH-2) | Existing inline column OR existing KV shape. |
| `SOLAR_FOLLOW_HEADROOM_KW` orphan | Combined-plan Rev-2 (B-6) | INV-SF-4 has no headroom term. |
| Solar-follow acts on a peer-held EVSE | Combined-plan Rev-3 | INV-SF-7 + ELIGIBLE step 5 + guard step 2a. C17 + C17b. |
| Restore-pass mutation-during-iteration crash | Combined-plan Rev-5 (N5) | `list(self._original_amps)` snapshot. T-ITER-1. |
| `SolarFollowController` shape ambiguous | Combined-plan Rev-5 (BLOCKING-2) | `__init__(self, hass, ev: EVChargerController, ...)`; SLF001 convention. |
| Hollow test anchor via fixture that doesn't perturb the tested branch | Combined-plan Rev-3 (SF7-H1); re-closed Rev-5 (BLOCKING-3) | Peer-hold test fixtures MUST move surplus beyond DEADBAND and outside the up-gate between ticks. |
| Solar-follow suppresses a strong-peer safety gate OR reaches into its function body for any purpose, including telemetry | Combined-plan Rev-6 (PB-1 REJECTED); strengthened Rev-7 | INV-SF-7 has NO exceptions. `determine_battery_drain_actions:1776-1959` BYTE-IDENTICAL post-cycle. Any observable from drain-protection state comes from EXTERNAL set-membership sampling (D1's STEP 0), never from inside the safety function. C18 + C19 + C19b. Rule generalizes: telemetry from a safety gate is derived externally by observation, not by reaching in. |
| An idle or unplugged bay dilutes the allocation denominator | Combined-plan Rev-8 (operator-flagged) | Allocation denominator uses `N_denom = max(1, N_drawing)`, NOT `len(ELIGIBLE)`. DRAWING ⊆ ELIGIBLE. Non-DRAWING ELIGIBLE bays receive MIN safe-parking. C20/b/c. CLAIM path at `energy_pool.py:1650-1656` byte-identical. Rule: when a producer emits a set with mixed semantic content, the consumer distinguishes by attribute rather than filtering the producer, unless the producer's set has only one consumer. |

(DP-related closed-concerns rows live in `PLANNING_dp_drain_target_mis_sourcing.md`.)

---

## 12. Change log (extracted from combined plan)

Combined plan Rev-1..Rev-8 change log preserved in git history of the deleted
`PLANNING_evse_solar_follow_and_dp_drain_target.md`. Summary of what shipped in this
split:

- All Rev-1..Rev-8 findings addressed inline; §11 register carries the invariants.
- **Rev-9 corrections (from the split correction):**
  - §5 known-couplings item 8 rewritten: D4 (v4.5.0) does NOT stand alone as the
    compound-load bound; `_paused_by_grid_cap` (v4.0.18) predates it and covers the
    same hazard reactively. Both are live. The scope-narrowing for D1 (does NOT
    re-solve compound load) is still correct; the attribution is grid_cap AND D4
    together. Breaker-protection caveat stated plainly (5-min cadence is not
    convincing for a mechanism that trips in seconds).
  - §9 REUSE table gains an explicit row for `_paused_by_grid_cap`.
  - §5a open question added: `grid_cap` vs `_paused_by_arbitrage` overlap for a future
    read-only supersession audit. Explicitly NOT a delete candidate; both live.
  - Runtime relationship + sequencing note added (top of doc): ship DP fix first,
    preferably.

---

## 13. Cycle-close checklist

* [ ] DP fix cycle (`PLANNING_dp_drain_target_mis_sourcing.md`) shipped and validated.
* [ ] Targeted re-review of the peer-hold + DRAWING-split framings.
* [ ] Build in one branch off `develop`.
* [ ] Suite green + baseline-diff clean.
* [ ] Four framing-disjoint reviews A/B/C/D returned; CRITICAL/HIGH fixed.
* [ ] Orchestrator pre-deploy grep set as §8 above.
* [ ] Operator checkpoint before deploy.
* [ ] `README_v<version>.md` with prospective Live criteria.
* [ ] Deploy via `./scripts/deploy.sh`.
* [ ] Live validation as §3 D1 live-validation subsection.
* [ ] README updated with observed `Validated <date>` table.
* [ ] Kanban card `EVSE-SOLAR-FOLLOW-AMPS-1` moved to shipped_organic.
* [ ] Post-ship supersession + consumer-gap audit per CLAUDE.md rule — INCLUDES surfacing
      §5a open question (grid_cap vs D4 overlap) as a candidate for the next audit cycle.
