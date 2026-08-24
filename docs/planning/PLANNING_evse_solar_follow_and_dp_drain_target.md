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

**Revision 4 (2026-08-23) — MERGED, single source of truth.** Fourth plan review (peer-hold
framing) returned DO NOT DISPATCH on two blocking findings INSIDE the Rev-3 addition, plus
four smaller items. Rev-4 patches in place:

- **SF7-B1 (BLOCKING):** the surplus add-back `current_charging_load_w()` sums EVERY charging
  EVSE, no ELIGIBLE filter (`energy_pool.py:2300-2312` verified). A peer-held EVSE that keeps
  drawing (operator re-enabled from the Emporia app after a grid-cap dispatch) inflates S; the
  inflated surplus is allocated across the survivors → over-draw. INV-SF-4 was stated in a
  form that read as satisfied while physically violated. Rev-4 rebases the surplus formula
  over ELIGIBLE only (peer-held draw classifies as house load, which is what it physically
  is), restates INV-SF-4 with an ELIGIBLE-scoped sum, and updates the T-PEER-5 oracle
  accordingly.
- **SF7-B2 (BLOCKING):** the C17 mutation drill claimed T-PEER-1..5 must fail, but the
  restore-deferral guard lives in step 2a which runs before ELIGIBLE and is untouched by C17.
  T-PEER-4 exercises only step 2a → passes under C17 → step 2a is an untested site under
  framing C. Rev-4 splits the mutation drill: C17 loses T-PEER-4 from its expected-failure
  list; a new C17b deletes the step-2a peer-hold guard and asserts T-PEER-4 fails.
- **SF7-H1:** T-PEER-2 hollow — asserted `_original_amps` retention but no drill perturbs
  retention. Rev-4 pins a second explicit assertion (zero writes for that EVSE on tick 2).
- **SF7-H2:** `_original_amps` was not declared a `_prune_removed_evses` participant; step 2
  behaviour on no-resolvable-entity was unspecified. Rev-4 states the prune declaration and
  spells out step 2's CLEAR-on-no-entity path. Also notes that `_paused_by_load_shed`
  `persistence_kind="none"` means a load-shed-deferred EVSE restores on first post-restart
  tick — benign, but recorded.
- **SF7-M1:** `_paused_by_us` accounting recorded (TOU is subordinate to excess-solar
  in-session; restart-crossed state unreachable because `save_evse_state` writes both flags
  atomically at `database.py:4526-4535`).
- **SF7-L1:** stale docstring `_stronger_peer_holds` says "ANY of the five" but loop returns
  six (`blind_window` added later). Fix in-cycle via §6 docs drift.
- **SF7-L2 / Q8:** correct the D4 citation. The live compound-load mutex is
  `energy.py:6240-6263` (`charge_from_grid` chokepoint, phase-label-independent, covers
  arbitrage CHARGE, v5.3.8 ATTAIN, and future rungs) + `:6290-6328` (hardware read OR fail-
  closed latch) + `:6341-6365` (EV pauses dispatched before battery actions). Cite these,
  NOT `PLANNING_v4.5.0_TRANSITION_NOTES.md:60` (predates ATTAIN). The narrowing is MORE
  defensible: non-arbitrage grid charging is also covered.
- **Q5:** release-policy paragraph now names the `_blind_window_liveness_ride` latch so a
  reader can confirm the 60 s bound survives must-start releases.

Rev-3 items preserved unchanged: INV-SF-7, ELIGIBLE-set control-law, pause ENTRY policy,
`deferred_restore_evses` as a gauge with explicit discharge, P6 ADOPT, P8 REJECT-WITH-EVIDENCE.
Rev-2 items preserved unchanged: five R2 sites, helper signature + None-fallback, fleet
allocation, hardware-floor exception, persistence shape, always-on timer, R1/R3 preservation,
`SOLAR_FOLLOW_CAPTURE_SANITY_A`.

---

## 0. Tier-3 elevation and framing

Three independent risks converge:

* **D1/D2 is a NEW WRITER on a live cloud actuator at 1-min cadence.** URA has never written
  amps before. Wrong containment = write-flood incident class. Wrong restore = silently
  crippled next charge. Wrong reactivity direction = drives battery discharge harder than the
  binary version. Wrong FLEET ALLOCATION makes two chargers each pull full surplus (Rev-2
  B-3). Wrong PEER-HOLD SUBORDINATION makes solar-follow act on a device a stronger owner has
  claimed and laminate a wrong "original" for restore (Rev-3). **Wrong SURPLUS-DENOMINATOR
  ALIGNMENT causes over-draw when a peer-held EVSE keeps physically drawing (Rev-4).**
* **D3 threads a value through a state machine with FIVE R2 emission sites.** The static knob
  `_ev_battery_drain_soc` serves three incompatible roles at once. Missing one R2 site stamps
  `_dp_decision_soc = 80` on the first successful DP transition. Bug Class #53.
* **Both D1 and D3 have "silent success" failure modes** where every acceptance criterion I
  originally wrote PASSED against a shipped bug.

Tier 3.

---

## 1. Falsifiable invariants

Each stated as "under X, Y can never happen in ANY reachable path."

### INV-SF-1 (solar-follow non-perturbation)
Under any config, any TOU period, any tick, `SolarFollowController` emits no `switch.turn_on`
and no `switch.turn_off`. Writes only `number.set_value` to a **current-limit entity** and
only for an EVSE currently in `_excess_solar_active`. The controller cannot start, stop,
extend, or curtail a session.

### INV-SF-2 (writes only inside sessions)
Under any config, if `_excess_solar_active` is empty AND no `_original_amps` entries remain,
zero writes. When the set is non-empty, writes target ONLY EVSEs in the set. Release-edge
restore writes target ONLY EVSEs with a saved `_original_amps` entry.

### INV-SF-3 (restore is load-bearing, restart-safe)
Under any config, after an EVSE is removed from `_excess_solar_active` by any code path
(release gate `energy_pool.py:1699`, blind-window drop `:1564`, peak clear `:1369`, restart
reconciliation `energy.py:5183-5225`, or config removal via `_prune_removed_evses`), the
current-limit is restored to its saved `_original_amps` value (falling back to
`SOLAR_FOLLOW_RESTORE_AMPS=48` only if no value was saved) within one restore tick — subject
to INV-SF-7 (peer hold defers restore). Persisted through HA restart via existing KV blob
machinery.

### INV-SF-4 (draw bounded by measured surplus over ELIGIBLE — Rev-4 restatement)
Under any excess-solar-active state, let `ELIGIBLE = {evse_id in _excess_solar_active where
NOT _stronger_peer_holds(evse_id) AND evse_id not in _paused_by_dp}`. Let
`S_eligible = -grid_W + Σ_{ELIGIBLE} evse_power_w`. Then:

`Σ_{i ∈ ELIGIBLE} A_i · 240 · PHASES <= max(S_eligible, N_eligible · SOLAR_FOLLOW_MIN_AMPS · 240)`

**Rev-4 fix (SF7-B1):** the add-back and the allocation denominator MUST be aligned on
ELIGIBLE. Peer-held EVSE power is classified as house load (which is what it physically is —
it draws through the same panel; solar-follow does not own it). Prior Rev-3 form allowed a
peer-held EVSE that kept drawing (operator re-enabled from Emporia app after grid-cap
dispatch) to inflate S; the inflated surplus was then allocated across survivors → over-draw.
The `max(..., N·MIN·240)` clause is the hardware-floor exception (B-2). There is no
`SOLAR_FOLLOW_HEADROOM_KW`.

### INV-SF-5 (asymmetric reaction to a lagging signal)
Under any surplus movement, downward step: uncapped, fires within one tick. Upward step: gated
by `SOLAR_FOLLOW_UP_MIN_TICKS` consecutive ticks of headroom AND capped at
`SOLAR_FOLLOW_UP_STEP_A` per tick per EVSE.

### INV-SF-6 (fleet allocation, B-3)
Under N_eligible > 1, `A_total_target = floor(S_eligible / (240 · PHASES))` ONCE per tick;
`A_per_evse = A_total_target // N_eligible` (integer floor); clamp each share to `[MIN, MAX]`.
Degenerate case (`A_per_evse < MIN`): all eligible EVSEs hold at MIN (6 A). Session
termination remains D2's release gate's job.

### INV-SF-7 (stronger-peer subordination)
Under any config and any tick, while `_stronger_peer_holds(evse_id) is True` OR
`evse_id in self._paused_by_dp`, `SolarFollowController` performs NO write to `evse_id`'s
current-limit entity AND NO capture of `_original_amps[evse_id]`. Applies to BOTH the
release-restore path (step 2a) AND the modulation path (step 5 → ELIGIBLE). `_paused_by_dp`
is checked INLINE per the two-site convention `energy_pool.py:394-400` documents.

### INV-RELEASE-1 (D2)
Under an excess-solar-active EVSE and any tick where `conditions_met` transitions False, no
`switch.turn_off` fires until the False state has persisted `SOLAR_RELEASE_MIN_TICKS`
consecutive ticks AND session age >= `SOLAR_RELEASE_MIN_ON_S`.

### INV-DP-DRAIN-1 (D3, whole emission set)
Under any config where `_dp_carrier.state ∈ {HOLD_ONLY, HOLD_PRE_EVAL, EVAL_TRANSITION}`, and
under any code path that populates `TransitionInputs.drain_target_soc` OR that stamps a fresh
`_dp_decision_soc` via `_apply_dp_transition`, the value used equals
`_dp_drain_target_soc(period)` (the composed floor). Applies to ALL R2 sites in §3.D3.

### INV-DP-DRAIN-1b (revert predicate consistency)
Under any tick where the controller has just stamped `_dp_decision_soc = X`, `:4555`
comparison uses the SAME X, not `_ev_battery_drain_soc`.

### INV-DP-DRAIN-2 (R1 pause ceiling preserved)
`determine_battery_drain_actions(soc_threshold=...)` at `:5842`/`:5977` sources from
`self._ev_battery_drain_soc` unchanged.

### INV-DP-DRAIN-3 (R3 ride-proof floor preserved)
`_ev_battery_drain_soc` remains the ride-proof floor at `energy.py:3752`,
`energy_pool.py:954`, `energy_pool.py:1435`. Byte-identical.

### INV-DP-DRAIN-4 (offpeak-drain live-apply or documented reload)
The four `energy_offpeak_drain_*` Numbers either live-apply into
`BatteryStrategy._drain_targets` (setter mutates the ctor-frozen dict), or reload-required is
documented on each entity's help text AND on the README.

---

## 2. Institutional context verified

Paths under `custom_components/universal_room_automation/domain_coordinators/`:

* `docs/planning/AUDIT_excess_solar_and_evse_prior_art.md` (all sections).
* `energy_pool.py` — `PoolOptimizer:58-160`; `EVChargerController.__init__:186-317`;
  `determine_excess_solar_actions:1318-1701` (release `:1685-1699` is D2);
  `determine_battery_drain_actions:1776-1959`; `_soc_envelope_admits_dp_transition:619-648`;
  **`_stronger_peer_holds:383-412`** (docstring names TOU AND excess-solar as subordinate;
  loop iterates `EV_REGISTRY.iter_peer_holds()` = 6 owners: battery_drain, fill_priority,
  grid_cap, arbitrage, load_shed, blind_window; **docstring says "the five" — STALE, to be
  fixed in-cycle, SF7-L1**); `_paused_by_dp` inline check at excess-solar CLAIM `:1621-1631`;
  fill-priority `_excess_solar_active` skip prior art at `:2214-2219`; **`current_charging_load_w`
  at `:2300-2312` sums every charging EVSE with no ELIGIBLE filter (SF7-B1)**;
  `_pause_dispatch_ts` / `_observed_off_since_pause` at `:275-278` (evidence that the repo does
  NOT trust "peer-held ⇒ not drawing").
* `energy_pool_owners.py` — `EV_REGISTRY.iter_peer_holds()` = 6; `persistence_kind` in
  {`"per_evse_bool"`, `"list"`, `"none"`}. `_paused_by_load_shed` is
  `persistence_kind="none"` (`:298-300`). Dict-kind owners at `:345+` are `_prune_removed_evses`
  participants; `_original_amps` (this cycle) must be added.
* `energy_drain_precedence.py` — `evaluate_dp_transition:609-735`.
* `energy.py` — R2 sites `:4271`, `:4456`, `:4522`, `:4540`, `:4555`; R2-display `:3871`,
  `:4021`; reserve fold `:4733-4742` (update-in-place), `:4829-4833` (append); write-verify
  surface gate `:7587-7591`; R1 sites `:5842` / `:5977`; R3 site `:3752`; 10 h staleness gate
  `:1346`; save hooks `_KNOWN_HOOKS` at `:1603-1612`. **Live compound-load mutex (Rev-4
  citation, SF7-L2):** `:6240-6263` (`charge_from_grid` chokepoint, phase-label-independent —
  covers arbitrage CHARGE, v5.3.8 ATTAIN, future rungs); `:6290-6328` (hardware read OR
  fail-closed latch); `:6341-6365` (EV pauses dispatched BEFORE battery actions);
  `:7259-7282` (load-shed operator-resumed-mid-shed re-claim branch — precedent for
  "peer-held ≠ not drawing"). DP claim-release sites for Q5 verification: `:5089`, `:5116`.
* `energy_battery.py` — `compose_release_floor:264` (module fn, returns
  `(release_floor: int | None, is_offpeak: bool)`, release_floor can be None at `:286-289`).
* `energy_const.py` — `DP_L1_RATE_THRESHOLD_KW=3.0:1359`;
  `DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD=50:857`; `EVSE_ESTIMATED_POWER_W=7600`.
* `database.py:4526-4535` — `save_evse_state` writes `paused_by_us` and `excess_solar_active`
  atomically. Underwrites the SF7-M1 `_paused_by_us` restart-crossed-state argument.
* `PLANNING_v4.7.x_APPLIANCE_SCHEDULER.md:41` — `flashg1/SolarCharger` anti-flap prior art.
* Memory: `project_optimizer_db_write_flood_incident_2026_06_09`;
  `project_ev_drain_precedence_cycle`; `feedback_suppression_needs_discharge`;
  `feedback_hollow_test_anchors`; `feedback_mutation_verification_pycache_staleness`;
  `RESTART-SAFETY-DOCTRINE-1`.

---

## 3. Deliverables

### D1 — SolarFollowController

**Host:** new class `SolarFollowController` in `energy_pool.py`, modelled on
`PoolOptimizer:58-160`. `_execute_service_action` as write path.

**Design points:**

1. **Always-on 60 s timer with empty-set fast path (B-5).** `async_track_time_interval`
   started at `async_setup_entry`, cancelled at `async_unload_entry`. Both
   `_excess_solar_active` empty AND `_original_amps` empty → cheap-membership no-op. Collapses
   the PB-2 cross-clock window.
2. **Fleet allocation over ELIGIBLE (B-3 + INV-SF-7 + Rev-4 SF7-B1).** Surplus computed with
   an ELIGIBLE-scoped add-back (see D1.2). ELIGIBLE-scoped denominator.
3. **6 A hold instead of stop-writing when per-EVSE share < 1.44 kW (B-2).**
4. **`SOLAR_FOLLOW_HEADROOM_KW` deleted (B-6).**
5. **`_original_amps` persistence via existing KV blob machinery (A-HIGH-2) — and Rev-4
   SF7-H2 fix.** Persist as an inline column sibling of `excess_solar_active`
   (`db.save_evse_state(evse_id, ...)` at `energy.py:1839`, restored at `:1365-1366`),
   OR a single KV `evse_original_amps_v1` (JSON dict `{evse_id: float}`) with a
   `_KNOWN_HOOKS`-registered save/restore. **`_original_amps` IS a `_prune_removed_evses`
   participant** — on config removal of an EVSE, the entry is dropped from `_original_amps`
   at the same time the six peer-hold sets prune. Step 2's behaviour on
   no-resolvable-entity is defined in the control law below.
6. **Capture sanity guard (A-HIGH-3).** Session ENTRY: read current-limit entity. Fresh &
   in-range → save. Stale/unavailable → save 48 (INFO). `< SOLAR_FOLLOW_CAPTURE_SANITY_A`
   (=20) → save 48 (WARNING, `capture_rejected_low` counter). Different door from INV-SF-7:
   INV-SF-7 excludes peer-held EVSEs from ELIGIBLE so no capture happens under a peer hold;
   the sanity guard catches stale-restart values on EVSEs that ARE eligible.
7. **Mirror the start condition to the stop condition (A-HIGH-4).** Always-on timer +
   empty-set-checks-BOTH-sets fast path.
8. **A-MED-1 / B-4.** D1 control law never feeds `EVSE_ESTIMATED_POWER_W`. If per-charger
   power is unavailable for `SOLAR_FOLLOW_STALE_MAX_TICKS` (=2), no writes.

**Per-tick control law (Rev-4):**

```
1. If _excess_solar_active empty AND _original_amps empty: return.
2. For each evse_id with _original_amps set but NOT in _excess_solar_active:
     a. If _stronger_peer_holds(evse_id) OR evse_id in _paused_by_dp:
          DEFER restore this tick — do NOT clear _original_amps. Mark evse_id
          in `deferred_restore_evses` (gauge). When the peer clears, the next
          tick's step 2 re-checks and either restores (2b) or lets steps 3-9
          resume modulation.
     b. Else:
          resolved_entity = self._evse.get(evse_id, {}).get("current_limit")
          If resolved_entity is None or unresolvable (evse_id no longer in
          `self._evse` after a config-removal prune):
              CLEAR _original_amps[evse_id], drop evse_id from
              deferred_restore_evses, emit no write, log INFO. (SF7-H2 fix —
              without this, a permanent entry keeps the empty-set fast path
              from ever firing and the gauge retains the id forever.)
          Else:
              emit ONE number.set_value(_original_amps[evse_id]); clear entry;
              drop evse_id from deferred_restore_evses.
3. If _excess_solar_active empty: return.
4. Read grid_W via D1.2 PRIMARY/FALLBACK. If both unavailable for STALE_MAX_TICKS:
   no writes.
5. ELIGIBLE = {evse_id in _excess_solar_active
               where NOT _stronger_peer_holds(evse_id)
               AND evse_id not in _paused_by_dp}.
   If ELIGIBLE empty: no writes, no captures (INV-SF-7).
6. N_eligible = len(ELIGIBLE).
7. Compute S_eligible = -grid_W + Σ_{evse_id ∈ ELIGIBLE} evse_power_w
   (SF7-B1 fix: sum ONLY over ELIGIBLE, not every charging EVSE).
   A_total_target = floor(S_eligible / (240 * PHASES)).
8. A_per_evse_raw = A_total_target // N_eligible.
9. For each evse_id in ELIGIBLE:
     a. Capture _original_amps[evse_id] per point 6 (with A-HIGH-3 sanity guard) if unset.
     b. A_target = clamp(A_per_evse_raw, MIN, MAX).
     c. A_current = read current-limit entity (unavailable => skip this EVSE this tick).
     d. Deadband: skip if |A_target - A_current| < DEADBAND_A.
     e. Step law (INV-SF-5): if A_target > A_current, require UP_MIN_TICKS streak AND
        A_write = min(A_target, A_current + UP_STEP_A). Else A_write = A_target.
     f. Write-budget cap (D1.7): if hour bucket exceeded, skip + WARN.
     g. Emit {number.set_value, current_limit_entity, A_write}.
     h. Schedule one-shot readback verify (D1.6).
```

**Pause ENTRY policy (stronger peer starts holding a modulated EVSE mid-session):** LEAVE
`_original_amps` in place; do NOT restore before yielding. Rationale — (1) restoring 48 A
under a stronger owner risks fighting them; arbitrage CHARGE explicitly pauses to bound
compound load. (2) The stronger owner has turned the SWITCH off; the current-limit is
cosmetic until the switch re-closes. (3) When the stronger owner releases: if excess-solar
is still active, step 9 resumes from the saved `_original_amps`; if not, step 2 fires the
restore on the NEXT tick.

**Pause RELEASE policy (peer holds clear):** D1 discovers the eligibility change on the next
60 s tick by re-reading `_stronger_peer_holds` and `_paused_by_dp` — no signal subscription
(would re-introduce the B-5 bootstrap-observer hazard). **Worst-case release latency: 60 s.**
Direction of harm: UNDER-draw only. In that window an EVSE released from
`_paused_by_arbitrage` (or any other peer) sits at a solar-throttled amp limit while no
stronger owner holds it; charger continues at (say) 14 A when it could go to 48 A. Fleet math
is still bounded by `S_eligible` in step 7, so cannot over-draw. INV-SF-4 unchanged, so cannot
pull from battery. Same bound class as PB-2's cross-clock window.

**Q5 must-start-release corner (Rev-4 addition):** the 60 s bound survives DP must-start
releases because (a) DP discards `_paused_by_dp` at `energy.py:5089` and `:5116` when the
must-start-by timer fires (or on the paused-aware exit predicate), and (b) the blind-window
grant path uses the `_blind_window_liveness_ride` latch at `energy_pool.py:989-999` which
sets `will_pause=False` and discards prior `_paused_by_blind_window` membership. Both
release paths mutate the sets in the same tick the release logic runs. D1's next 60 s tick
observes the cleared membership and (re-)computes ELIGIBLE correctly. The `_blind_window_liveness_ride`
latch is a GRANT, not a hold — it does not participate in `_stronger_peer_holds` and
correctly does not gate D1.

**D1.2 — surplus signal (Rev-4 SF7-B1 restatement).**

* PRIMARY grid reading: `sensor.mains_vue_3_power_minute_average` (Emporia mains, signed W,
  negative = export). Availability: `state ∉ {unknown, unavailable, None}`.
* FALLBACK grid reading: `sensor.envoy_482543015950_current_net_power_consumption` (signed
  **kW**, negative = export). Unit differs — kW → W conversion (`×1000`) in the fallback
  branch. Availability: existing `envoy_available` reliability signal (NOT
  `sensor.ura_energy_coordinator_envoy_status`).
* **Add-back over ELIGIBLE, not fleet-wide (SF7-B1 fix).** Do NOT call
  `current_charging_load_w()` (`energy_pool.py:2300-2312`) — it sums every charging EVSE with
  no ELIGIBLE filter. Instead, inline the sum over ELIGIBLE only:

  ```
  add_back_w = 0.0
  for evse_id in ELIGIBLE:
      state = self._ev._get_evse_state(evse_id)  # existing helper
      if state.get("charging"):
          p = state.get("power") or 0.0
          try: add_back_w += float(p)
          except (TypeError, ValueError): pass
  S_eligible = (-grid_W) + add_back_w
  ```

  Peer-held EVSE draw (e.g. the SF7-B1 repro: `garage_a` held by grid-cap, operator
  re-enabled it from the Emporia app, still drawing 7.4 kW physically) is now classified as
  house load — which is what it physically is. `garage_b`'s share is computed against the
  true surplus available AFTER `garage_a`'s uncontrollable draw.

* Fences: NOT `balanced_net_power_consumption`; NOT SPAN; NOT
  `sensor.mainw_vue_balance_power_minute_average` (dead/typo).

**D1.3 — self-consistency stop.** Both PRIMARY and FALLBACK unavailable for
`SOLAR_FOLLOW_STALE_MAX_TICKS` (=2) → no writes, WARNING. Fail-safe.

**D1.4 — current-limit entities.** Added to `DEFAULT_EVSE_ENTITIES` under new key
`current_limit`:
* `garage_a`: `number.garage_a_evse_emporia_wifi_garagea_current_limit`
* `garage_b`: `number.garage_b_evse_emporia_wifi_garageb_current_limit`
L1 chargers explicitly excluded.

**D1.5 — Solcast next-hour stop.** New `CONF_SOLCAST_NEXT_HOUR_ENTITY` (rung 2) populated
from `sensor.solcast_pv_forecast_forecast_next_hour`. Consumed by D2.

**D1.6 — bounded in-controller write-verify.** After every write,
`async_call_later(SOLAR_FOLLOW_VERIFY_S=8, ...)` reads back and checks ±1 A tolerance.
WARNING + counter on mismatch. Does NOT extend `_maybe_schedule_write_verify`.

**D1.7 — write-budget containment.** `SOLAR_FOLLOW_MAX_WRITES_PER_HOUR_PER_EVSE` (=30, rung
1). Hour bucket per EVSE.

**D1.8 — status-sensor observability.** `sensor.ura_energy_coordinator_solar_follow`
attributes:

* `active: bool`
* `eligible_evses: list[str]` — the ELIGIBLE set this tick (INV-SF-7 direct read).
* `s_eligible_kw: float` — the surplus computed after Rev-4's ELIGIBLE-scoped add-back
  (observability aid for the SF7-B1 fix; distinguishable at a glance from a fleet-wide sum).
* `deferred_restore_evses: list[str]` — **gauge, not counter.** Membership rule: an
  `evse_id` is in this list iff (a) `_original_amps[evse_id]` is set,
  (b) `evse_id not in _excess_solar_active`, (c) `_stronger_peer_holds(evse_id) OR
  evse_id in _paused_by_dp`. **Discharge:** an `evse_id` LEAVES this list when either
  (i) the peer clears AND the next tick's step 2b fires the restore + clears
  `_original_amps[evse_id]`, or (ii) the EVSE re-enters `_excess_solar_active`, or (iii)
  the EVSE is pruned from config (step 2b's no-resolvable-entity CLEAR path). A monotone
  counter is explicitly rejected here.
* `capture_rejected_low: int` — monotone; counts A-HIGH-3 event class, no discharge needed.
* `writes_per_hour_per_evse: dict[str, int]`
* `current_amps: dict[str, int]`
* `original_amps: dict[str, float]`

**D1.9 — non-peer-hold owner accounting (SF7-M1).** `_stronger_peer_holds` returns True for
six owners: `battery_drain`, `fill_priority`, `grid_cap`, `arbitrage`, `load_shed`,
`blind_window` (`EV_REGISTRY.iter_peer_holds()`, verified). Plus the inline `_paused_by_dp`
check. That leaves three EVSE-touching owners the D1 fence must account for; each is recorded
here so the coverage is closed on the record:

* **`_paused_by_us` (TOU).** NOT in `_stronger_peer_holds`. Benign for D1 because TOU is
  subordinate to excess-solar in-session: the peak branch `continue`s on
  `_excess_solar_active` membership at `energy_pool.py:906`, and the excess-solar claim
  path discards `_paused_by_us` at `:1633-1635`. So an EVSE cannot simultaneously be in
  `_excess_solar_active` (required for D1 to write) AND `_paused_by_us` after either
  path runs. Restart-crossed corner state is unreachable because
  `save_evse_state` writes `paused_by_us` and `excess_solar_active` atomically
  (`database.py:4526-4535`); no restart lands with both flags set.
* **`_proactive_offpeak_holds`.** Intent-state, not a pause; correctly excluded from
  `_stronger_peer_holds` and correctly outside D1's fence (does not gate a live actuator).
* **`_blind_window_liveness_ride`.** GRANT (not a hold); correctly excluded. See the Q5
  paragraph above for why the grant does not gate D1 and how it interacts with the release
  policy.

**Constants (D1 knob ladder):**

| Name | Rung | Value | Why this rung |
|---|---|---|---|
| `SOLAR_FOLLOW_TICK_S` | 1 | 60 | Protocol; matches Emporia 1-min average |
| `SOLAR_FOLLOW_MIN_AMPS` | 1 | 6 | J1772 pilot floor, hardware constant |
| `SOLAR_FOLLOW_MAX_AMPS` | 1 | 48 | Service ceiling |
| `SOLAR_FOLLOW_RESTORE_AMPS` | 1 | 48 | Fallback default only |
| `SOLAR_FOLLOW_CAPTURE_SANITY_A` | 1 | 20 | Anti-captured-throttle |
| `SOLAR_FOLLOW_DEADBAND_A` | 3 (Number) | 1 | Operator-tunable |
| `SOLAR_FOLLOW_UP_STEP_A` | 3 (Number) | 2 | Operator-tunable |
| `SOLAR_FOLLOW_UP_MIN_TICKS` | 3 (Number) | 3 | Operator-tunable |
| `SOLAR_FOLLOW_STALE_MAX_TICKS` | 1 | 2 | Fail-safe |
| `SOLAR_FOLLOW_VERIFY_S` | 1 | 8 | Protocol |
| `SOLAR_FOLLOW_MAX_WRITES_PER_HOUR_PER_EVSE` | 1 | 30 | Safety containment |
| `SOLAR_FOLLOW_PHASES` | 1 | 1 | 240 V L2 single-phase (US) |
| `SOLAR_FOLLOW_NEXTHOUR_FLOOR_W` | 1 | 1000 | Protocol |
| `CONF_SOLCAST_NEXT_HOUR_ENTITY` | 2 | — | Per-deployment entity id |
| `CONF_SOLAR_FOLLOW_ENABLED` | 3 (Switch) | True | Kill-switch |

**D1 acceptance (discriminating, Rev-4):**

* **INV-SF-1:** `test_solar_follow_writes_only_number_set_value_never_switch`.
* **INV-SF-2:** `test_solar_follow_no_writes_when_both_sets_empty`.
* **INV-SF-3 restart:** `test_solar_follow_restore_after_restart_within_release_window`.
* **INV-SF-4 (Rev-4 restatement):** parametric at `grid_W ∈ {-2000, -5000, -11500}`,
  `N_eligible ∈ {1, 2}`, with and without a peer-held-and-drawing EVSE. Assert
  `Σ_{ELIGIBLE} A · 240 ≤ max(S_eligible, N·MIN·240)` at every point. **Under the pre-Rev-4
  fleet-wide add-back bug (SF7-B1 repro), the parametric run at `grid_W=-2000` with
  `garage_a` in `_paused_by_grid_cap` charging 7.4 kW physical → `S_fleet = 9.4 kW`, N=1,
  survivor `garage_b` commanded 9.36 kW → total draw 16.76 kW against 2 kW true surplus.
  Test fails under the bug. Different observation from the Rev-4 fix (survivor commanded
  ≤ 2 kW).**
* **INV-SF-5:** `test_solar_follow_up_gated_down_immediate`.
* **INV-SF-6 fleet:** `test_solar_follow_two_evses_split_surplus`.
* **INV-SF-6 degenerate:** `test_solar_follow_two_evses_below_floor_holds_at_min`.
* **INV-SF-7 T-PEER-1:** EVSE in both `_excess_solar_active` AND `_paused_by_arbitrage`.
  Tick: zero writes AND `_original_amps` remains unset.
* **INV-SF-7 T-PEER-2 (Rev-4 SF7-H1 pin):** mid-session peer add — tick 1 modulation fires and
  captures original amps; add EVSE to `_paused_by_grid_cap`; tick 2 asserts **BOTH**
  (i) `_original_amps` PRESERVED unchanged, AND (ii) **zero `number.set_value` for that
  EVSE on tick 2**. The retention-only assertion was hollow (no drill perturbed retention);
  the zero-write assertion is the load-bearing one. Under bug (Rev-2 control law), tick 2
  writes AND overwrites capture with paused-charger reading — both assertions distinguishable.
* **INV-SF-7 T-PEER-3 (DP inline):** EVSE in `_excess_solar_active` AND `_paused_by_dp`
  with `_dp_carrier.state == HOLD_ONLY`. Assert zero writes.
* **INV-SF-7 T-PEER-4 (release deferred under peer hold, exercises STEP 2a):** save
  `_original_amps={"garage_a": 32}`; drop garage_a from `_excess_solar_active`; add garage_a
  to `_paused_by_load_shed`. Tick: no restore, `_original_amps` retained,
  `deferred_restore_evses` contains `garage_a`. Remove load_shed. Next tick: restore fires,
  `_original_amps` cleared, gauge drains.
* **INV-SF-7 T-PEER-5 (fleet+add-back over ELIGIBLE, Rev-4 SF7-B1 oracle rebase):**
  `garage_a` and `garage_b` in `_excess_solar_active`; `garage_a` additionally in
  `_paused_by_arbitrage` AND physically drawing 7.4 kW (operator re-enabled). `grid_W =
  -2000` (exporting 2 kW). Under Rev-4: ELIGIBLE = {garage_b}, add_back = 0 (garage_a not
  in ELIGIBLE), `S_eligible = 2 kW`, N=1, `A_total = 8 A`, `garage_b` commanded 8 A (1.92 kW).
  Total physical draw = 7.4 (garage_a, uncontrollable) + 1.92 (garage_b) = 9.32 kW against
  a house drawing what it draws + 2 kW export. Under Rev-3 bug: fleet add-back gives
  `S_fleet = 9.4 kW`, `garage_b` commanded 39 A → 9.36 kW → total 16.76 kW → over-draw.
  Prior Rev-3 T-PEER-5 oracle asserted "survivor takes the whole hand-fed 5 kW" — that
  oracle assumed `garage_a` was not drawing; Rev-4 corrects it.
* **SF7-H2 T-PEER-6 (prune-during-deferral):** save `_original_amps={"garage_a": 32}`;
  garage_a not in `_excess_solar_active`; garage_a in `_paused_by_grid_cap` (deferred).
  Remove garage_a from `self._evse` (config prune). Next tick: `_original_amps[garage_a]`
  is CLEARED without a write; `deferred_restore_evses` no longer contains `garage_a`; empty-
  set fast path fires. Under bug (undefined behaviour), the entry persists forever and the
  gauge never drains.
* **SF7-H2 load-shed restart (benign, recorded):**
  `test_solar_follow_load_shed_deferral_clears_on_restart` — save
  `_original_amps={"garage_a": 32}`, `_paused_by_load_shed = {"garage_a"}` (RAM-only,
  `persistence_kind="none"`); restart. Post-restart `_paused_by_load_shed` is empty; first
  tick fires the restore to 32. Assert the entity value is 32. Benign because it restores to
  the captured original ≤48 A — not a spurious 48 A blast. Recorded so the class of "load-
  shed forgot the hold on restart" is not surprising.
* **A-HIGH-3 capture guard:** `test_solar_follow_capture_rejects_stale_low_value`.
* **Live (sunny afternoon):** attribute sensor shows `active=True`, `eligible_evses`,
  `s_eligible_kw` (Rev-4 add), `current_amps` per EVSE, `writes_per_hour_per_evse < 30`,
  `original_amps` saved.
* **Live (release):** on release, current-limit returns to saved `_original_amps` within
  60 s.
* **Live (two-EVSE):** sum of amps × 240 ≤ S_eligible over a 15-min window.
* **Live (INV-SF-7):** if an arbitrage CHARGE overlap occurs, sensor `eligible_evses` shows
  arbitrage-held EVSE excluded, `s_eligible_kw` reflects the ELIGIBLE-scoped add-back, and
  `deferred_restore_evses` populates on release-edge.

### D2 — Release-gate hysteresis + drain-protection skip

**Where:** `EVChargerController.determine_excess_solar_actions:1685-1699` (release leg) and
`determine_battery_drain_actions:1776` (drain-protection).

**Changes:**

1. Add `_conditions_met_false_streak_ticks: dict[str, int]` and `_excess_solar_started_at:
   dict[str, datetime]`.
2. Stamp `_excess_solar_started_at[evse_id]` on session entry. Persist per-EVSE as an inline
   column sibling of `excess_solar_active`.
3. Release condition fires ALL of:
   - `not conditions_met` OR `solcast_next_hour_w < SOLAR_FOLLOW_NEXTHOUR_FLOOR_W`
   - streak `>= SOLAR_RELEASE_MIN_TICKS` (=3)
   - session age `>= SOLAR_RELEASE_MIN_ON_S` (=300)
4. On `conditions_met` True: reset streak.
5. **Drain-protection skip (PB-1):** in `determine_battery_drain_actions`, per-EVSE loop
   head, add `if evse_id in self._excess_solar_active: continue`. Prior art at
   `energy_pool.py:2214`.

**Discharge rule (per `feedback_suppression_needs_discharge`):** streak dict RAM-only (resets
on restore); `_excess_solar_started_at` persisted so min-on-time survives restart.

**Design provenance (P6 shape-match):** anti-flap duration-threshold pattern per
`PLANNING_v4.7.x_APPLIANCE_SCHEDULER.md:41`.

**Constants:** `SOLAR_RELEASE_MIN_TICKS` (rung 1, 3); `SOLAR_RELEASE_MIN_ON_S` (rung 3, 300).

**D2 acceptance:**
* `test_release_streak_gated`
* `test_release_min_on_time`
* `test_release_streak_persists_min_on_time_across_restart`
* `test_drain_protection_skips_solar_follow_active`
* **Live:** membership persists through single-SOC-point dips of < 180 s.

### D3 — DP drain-target mis-sourcing fix (FIVE R2 sites)

**R2 emission-site table (unchanged from Rev-3):**

| Site | Where | What it does | Class | Change |
|---|---|---|---|---|
| `energy.py:4271` | Shadow `TransitionInputs` construction | Feeds gate 7/8 shadow eval | **R2** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:4456` | Real tick `TransitionInputs` construction | Feeds gate 7/8 real eval | **R2** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:4522` (`_DPAct`) | Fresh-TRANSITIONED actuation | Sets reserve floor | **R2** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:4540` (`_DPActRescan`) | Second-plug-in rescan | Sets reserve floor | **R2** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:4555` (`_drain`) | Revert predicate | Reverts on same tick if SOC ≤ knob | **R2 (revert consistency)** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:3871` | DP snapshot sensor | Display | **R2-display** | Follows source (auto) |
| `energy.py:4021` | Same sensor payload | Display | **R2-display** | Auto |
| `energy.py:4910` | `_apply_dp_transition` reads `decision.drain_target_soc` | Stamp | **R2 consumer** | No change |
| `energy.py:3752` | Blind-hold envelope proof | R3 | **R3** | Unchanged |
| `energy_pool.py:954` | `_soc_envelope_admits_dp_transition` caller pass | R3 | **R3** | Unchanged |
| `energy_pool.py:1435` | Same helper, excess-solar blind-window branch | R3 | **R3** | Unchanged |
| `energy_pool.py:619-648` (helper body) | Reads `drain_target_soc` as ARG | Helper | **Follows caller** | R3 callers unchanged |
| `energy.py:5842` (EV) | `determine_battery_drain_actions(soc_threshold=)` | R1 | **R1** | Unchanged |
| `energy.py:5977` (plugs) | Plug mirror | R1 | **R1** | Unchanged |

**The `_dp_drain_target_soc` helper (unchanged from Rev-2):**

```python
from .energy_battery import compose_release_floor

def _dp_drain_target_soc(self, tou_period: str) -> int:
    floor, _is_offpeak = compose_release_floor(self._battery, tou_period)
    if floor is None:
        static_reserve = getattr(self._battery, "reserve_soc", None)
        if static_reserve is None:
            _LOGGER.warning(
                "DP drain-target: compose_release_floor None AND static reserve None; "
                "raising to skip this tick's DP evaluation."
            )
            raise ValueError("dp drain-target unavailable")
        _LOGGER.warning(
            "DP drain-target: compose_release_floor returned None; falling back to "
            "static reserve=%s (NOT _ev_battery_drain_soc)", static_reserve,
        )
        return int(static_reserve)
    return int(floor)
```

Callers wrap `ValueError`: `:4271`/`:4456` skip DP this tick; `:4522`/`:4540` decline to
actuate; `:4555` (revert) does NOT revert on unavailable value.

**Producer / Consumer + call-site check** (unchanged from Rev-3).

**INV-DP-DRAIN-4 blocker resolution** (unchanged; builder picks live-apply vs documented
reload; INV-DP-DRAIN-4 enforces whichever choice).

**Hold-demotion — OUT OF SCOPE.**

**Activation risk** (unchanged Rev-3 text).

**D3 acceptance (unchanged Rev-3):** T1, T1b, T1c, T1d, T2, T3, T3b, T4, T5.

**Files changed (D3):** `energy.py`, `sensor.py`, `quality/tests/test_dp_drain_target_source.py`,
docs drift.

---

## 4. Non-goals (explicit)

* NOT starting or stopping charges on any grounds. D1 modulates amps only.
* NOT coordinating with DP from D1/D2.
* NOT changing the excess-solar TRIGGER at `energy_pool.py:1574-1579`.
* NOT changing the EC 5-minute tick.
* NOT extending `_maybe_schedule_write_verify`.
* NOT wiring HVAC coupling.
* NOT demoting `evse_battery_hold` to backstop.
* NOT changing the live value of `ev_battery_drain_soc` (still 80).
* NOT changing R1 / R3 sources.
* NOT touching `sensor.mainw_vue_balance_power_minute_average` (dead/typo).
* NOT using `balanced_net_power_consumption`, SPAN, or
  `sensor.ura_energy_coordinator_envoy_status` as gates.
* NOT wiring L1 chargers.
* NOT introducing a new `persistence_kind`.
* NOT auto-remediating an offline Garage A / SPAN observability gap.
* NOT feeding `EVSE_ESTIMATED_POWER_W` into D1's control law.
* NOT introducing a priority ordering between EVSEs.
* NOT adding `_paused_by_dp` to the shared `_stronger_peer_holds` helper.
* NOT re-solving compound-load (134 A main-breaker) safety in D1. Live compound-load mutex
  at `energy.py:6240-6263` + `:6290-6328` + `:6341-6365` bounds it; INV-SF-7 subordinates D1
  to it.
* NOT building a per-EVSE "no-interference latch" that suppresses D1 for the remainder of a
  session after a manual write.
* NOT using `current_charging_load_w()` (`energy_pool.py:2300-2312`) for the surplus
  add-back (Rev-4 SF7-B1 fix: fleet-wide summation would over-draw when a peer-held EVSE
  keeps physically drawing). Inline sum over ELIGIBLE only.

---

## 5. Known couplings (independently enumerated)

1. **DP gate 6 (L1-only, `energy_drain_precedence.py:652`)** sees a throttled charger as
   sub-threshold at 12.5 A crossover.
2. **DP gate 8 charge_hours** blows up at low amps.
3. **`_dp_house_load_kw` biased the OTHER way** — non-monotone in amps. D1 does not care.
4. **`EVSE_ESTIMATED_POWER_W = 7600`** fabricated on Emporia outage. D1 never feeds this into
   its own control law. DP may still consume it — pre-existing pathology.
5. **`evse_battery_hold` still engages at 6 A** — amp-independent.
6. **Actuation precedence is EMERGENT.**
7. **INV-YIELD-1/2** (audit §6.4). D1 downstream of CLAIM; INV-SF-7 strictly stricter.
8. **Live compound-load mutex** (Rev-4 SF7-L2 corrected citation) at `energy.py:6240-6263`
   (`charge_from_grid` chokepoint, phase-label-independent — covers arbitrage CHARGE, v5.3.8
   ATTAIN, and future rungs), `:6290-6328` (hardware read OR fail-closed latch), `:6341-6365`
   (EV pauses dispatched BEFORE battery actions). Bounds the 134 A compound-load case
   INDEPENDENT of arbitrage phase label. INV-SF-7 subordinates D1 to it via
   `_paused_by_arbitrage` membership in `_stronger_peer_holds`. Non-arbitrage grid charging
   (ATTAIN, future rungs) is also covered; solar charging draws nothing through the panel and
   is out of scope.
9. **`_pause_dispatch_ts` / `_observed_off_since_pause`** (`energy_pool.py:275-278`) — the
   repo does NOT trust "peer-held ⇒ not drawing". SF7-B1's premise (an operator re-enabling
   a paused charger from the Emporia app) is exactly the class of race these fields exist for.
   D1's Rev-4 ELIGIBLE-scoped add-back handles the physical draw by classifying it as house
   load rather than trying to detect the manual override.
10. **`_paused_by_load_shed` is `persistence_kind="none"`** (`energy_pool_owners.py:298-300`).
    A load-shed-deferred EVSE loses the hold membership on restart → first post-restart
    tick's step 2b fires the restore. Benign because it restores to the captured original
    ≤48 A (not a 48 A blast under a still-active shed). Recorded so the class of "load-shed
    forgot the hold on restart" is not surprising.

---

## 6. Docs drift to fix in-cycle

* `docs/user-manual/ENERGY_COORDINATOR.md:642` — default-50 + R1-only description.
* `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md:455`.
* `docs/planning/PLANNING_evse_drain_precedence.md` — unbound `drain_target`.
* `docs/planning/PLANNING_inclement_weather_reserve.md:66,82` — stale by ~3200 lines.
* **`energy_pool.py:_stronger_peer_holds` docstring (SF7-L1)** — says "ANY of the five"
  and names five owners, but the loop returns six (`blind_window` added later via
  `EV_REGISTRY.iter_peer_holds()`). Update to name six.

---

## 7. Test plan summary

Behavioural, MUTATION-VERIFIED. `PYTHONDONTWRITEBYTECODE=1` and clear `__pycache__` before
each drill.

D1: `test_solar_follow_writes_only_number_set_value_never_switch`;
`test_solar_follow_no_writes_when_both_sets_empty`;
`test_solar_follow_restore_after_restart_within_release_window`;
`test_solar_follow_bounds_draw_by_surplus_hardware_floor_exception` (Rev-4 restated INV-SF-4);
`test_solar_follow_up_gated_down_immediate`;
`test_solar_follow_two_evses_split_surplus`;
`test_solar_follow_two_evses_below_floor_holds_at_min`;
`test_solar_follow_capture_rejects_stale_low_value`;
`test_solar_follow_stops_writing_when_both_sensors_unavailable`;
`test_solar_follow_write_budget_containment`;
`test_solar_follow_never_feeds_evse_estimated_power_into_control_law`;
`test_solar_follow_load_shed_deferral_clears_on_restart` (Rev-4 SF7-H2);
**T-PEER-1** `test_solar_follow_no_write_when_peer_holds_arbitrage`;
**T-PEER-2** `test_solar_follow_zero_write_and_original_preserved_on_mid_session_peer_add`
(Rev-4 SF7-H1 — TWO assertions);
**T-PEER-3** `test_solar_follow_no_write_under_paused_by_dp_hold_only`;
**T-PEER-4** `test_solar_follow_restore_deferred_under_peer_hold_fires_on_release`;
**T-PEER-5** `test_solar_follow_add_back_and_denominator_both_over_eligible` (Rev-4 SF7-B1 —
rebased oracle);
**T-PEER-6** `test_solar_follow_deferred_restore_clears_on_config_prune` (Rev-4 SF7-H2).

D2: `test_release_streak_gated`; `test_release_min_on_time`;
`test_release_streak_persists_min_on_time_across_restart`;
`test_drain_protection_skips_solar_follow_active`.

D3: T1, T1b, T1c, T1d, T2, T3, T3b, T4, T5 as named in Rev-3.

---

## 8. Review plan — Tier 3, four framing-disjoint passes

Per CLAUDE.md Tier 3. Run A/B/C/D in PARALLEL.

* **A — local correctness.** D1 arithmetic (ELIGIBLE-scoped add-back **and** denominator,
  clamp, step law, unit conversion, hardware-floor branch); D3 helper; D2 streak.
* **B — integration / state-machine + no-op path byte-identical.** D1 never perturbs
  TOU/DP/fill-priority/INV-YIELD; R1 and R3 grep-diff clean; restart paths; pause
  ENTRY/RELEASE observed; must-start release corner (Q5).
* **C — REAL per-site source mutation.** Enumerated:
  - C1: neuter D3 helper to return `_ev_battery_drain_soc` → T1/T1b/T1c/T1d must fail.
  - C2: swap D3 `:5842` argument to composed → T3 must fail.
  - C3: neuter `:4522` → T1c must fail.
  - C4: neuter `:4540` → T1d must fail.
  - C5: neuter `:4555` → T2 must fail.
  - C6: remove D2 streak → `test_release_streak_gated` must fail.
  - C7: remove D2 min-on-time → `test_release_min_on_time` must fail.
  - C8: symmetric step law → `test_solar_follow_up_gated_down_immediate` must fail.
  - C9: remove D1 restore branch → restart test must fail.
  - C10: remove D1 write-budget → budget test must fail.
  - C11: remove D2 drain-protection skip → `test_drain_protection_skips_solar_follow_active`
    must fail.
  - C12: drop ×1000 in fallback → INV-SF-4 test must fail.
  - C13: replace fleet-allocation with per-EVSE independent read → INV-SF-6 tests must fail.
  - C14: replace hardware-floor hold with stop-writing → INV-SF-4 degenerate test must fail.
  - C15: replace capture guard with naive capture → A-HIGH-3 test must fail.
  - C16: replace D3 None fallback with `_ev_battery_drain_soc` → T3b must fail.
  - **C17 (Rev-4 corrected list):** replace D1's ELIGIBLE-set computation in **step 5** with
    raw `_excess_solar_active` (drop the `_stronger_peer_holds` + `_paused_by_dp` filters at
    step 5 ONLY) → **T-PEER-1, T-PEER-2, T-PEER-3, T-PEER-5 must fail. T-PEER-4 is NOT in
    this list** — it exercises step 2a, which C17 does not perturb. (SF7-B2 fix.)
  - **C17b (Rev-4 new):** delete the `_stronger_peer_holds(evse_id) or evse_id in
    self._paused_by_dp` guard from **step 2a** ONLY → **T-PEER-4 must fail** (release fires
    under a still-active peer hold; `deferred_restore_evses` no longer populates). This
    anchors the deferral half of INV-SF-7. (SF7-B2 fix.)
  - **C17c (Rev-4 new):** replace D1's ELIGIBLE-scoped add-back with fleet-wide
    `current_charging_load_w()` → **T-PEER-5 must fail** (the Rev-4 oracle: under fleet-wide
    add-back, S inflates by the peer-held EVSE's draw and survivor over-draws). This anchors
    the add-back half of the SF7-B1 fix, distinct from the denominator half (which C17
    already anchors).
* **D — adversarial completeness / diff-blind.** Re-enumerate the ENTIRE R2 emission set from
  scratch. Re-enumerate all discard sites for `_excess_solar_active`: THREE at
  `energy_pool.py:1369`, `:1564`, `:1699`; restart-reconciliation at `energy.py:5183-5225` as
  a separate vector; `_prune_removed_evses` as a fifth vector. Re-enumerate ALL sites that
  mutate any of the six peer-hold owner sets + `_paused_by_dp`; confirm each either does not
  need to signal D1 (D1 re-reads eligibility each tick) or argues for adding a signal (defer
  to future cycle). Re-enumerate every writer to a `number.set_value` in `energy*.py` —
  currently none targets current-limit entities. Legal-config combinatorial: min == max,
  deadband > (max-min), `SOLAR_RELEASE_MIN_ON_S` > natural session length, N=3. Every leak
  must come with a concrete legal-config repro.

**Orchestrator pre-deploy verification:** personally re-grep every `drain_target_soc =`
assignment and `_ev_battery_drain_soc` read; confirm five R2 sites are the helper. Re-grep
the six peer-hold owner sets + `_paused_by_dp`; confirm ELIGIBLE computation runs before
every D1 write and capture AND step 2a's deferral guard runs before every restore. Personally
run source-mutation drills on `_dp_drain_target_soc`, on `:4522`/`:4555`, on the step-5
ELIGIBLE filter (C17), on the step-2a deferral guard (C17b), and on the ELIGIBLE-scoped
add-back (C17c). Confirm every `.py` file under `custom_components/…/domain_coordinators/`
has zero call sites to `current_charging_load_w()` inside `SolarFollowController` (the
Rev-4 SF7-B1 non-goal). **Operator checkpoint BEFORE deploy.**

---

## 9. REUSE vs NEW

| Item | Verdict | Cite |
|---|---|---|
| Save/restore pattern for `number` entity | REUSE | `PoolOptimizer` `energy_pool.py:58-160` |
| `number.set_value` write path | REUSE | `_execute_service_action` |
| `_excess_solar_active` membership | REUSE | `energy_pool.py:202` |
| Unavailable-entity keep-state | REUSE | `energy_pool.py:135-137` |
| Per-EVSE inline persistence for `_original_amps` | REUSE (extend inline column OR KV blob shape) | `energy.py:1839`, `:1365-1366` |
| **`_get_evse_state` (per-EVSE power read for ELIGIBLE add-back — Rev-4)** | REUSE | `energy_pool.py` existing helper (Rev-4 uses it directly inside `SolarFollowController`, NOT via `current_charging_load_w()`) |
| `compose_release_floor()` (module fn) | REUSE | `energy_battery.py:264` |
| `_ev_battery_drain_soc` at R1/R3 sites | REUSE unchanged | `:5842`, `:5977`, `:3752`, `energy_pool.py:954`, `:1435` |
| TOU peak-clear (never write during peak) | REUSE | `energy_pool.py:1354-1374` |
| Fill-priority `_excess_solar_active` skip (D2 prior art) | REUSE pattern | `energy_pool.py:2214-2219` |
| `_stronger_peer_holds` + `_paused_by_dp` inline check | REUSE unchanged | `energy_pool.py:383-412`, `:1621-1631` |
| Anti-flap duration-threshold (D2 shape-match) | REUSE (from `flashg1/SolarCharger` per P6) | `PLANNING_v4.7.x_APPLIANCE_SCHEDULER.md:41` |
| **Live compound-load mutex (Rev-4 corrected citation)** | REUSE unchanged | `energy.py:6240-6263` + `:6290-6328` + `:6341-6365` |
| **`_prune_removed_evses` participation for `_original_amps` (Rev-4 SF7-H2)** | REUSE mechanism | `energy_pool_owners.py:345+` dict-kind owners |
| `SolarFollowController` class | NEW | Zero amp control today |
| Session-scoped 60 s timer (always-on, empty-set fast path) | NEW | Bounded blast radius |
| **ELIGIBLE-scoped surplus add-back (Rev-4 SF7-B1)** | NEW | Inline sum, not a new helper |
| `_dp_drain_target_soc(period)` helper | NEW | D3 mechanism; ~15 LoC + None fallback |
| Release-gate streak + min-on-time | NEW | Audit §1 row 4 |
| Solcast next-hour stop signal | NEW | Audit §1 row 8 |
| `SOLAR_FOLLOW_*` constants + Numbers | NEW | No amp knobs exist |
| Drain-protection `_excess_solar_active` skip | NEW (mirrors fill-priority prior art) | `energy_pool.py:2214` |
| Bounded in-controller readback verify | NEW | Existing surface silently drops |
| `BatteryStrategy.set_offpeak_drain_target` (conditional) | NEW | Live-apply into ctor-frozen dict |

---

## 10. Design pushback recorded

* **PB-1** — drain-protection `_excess_solar_active` skip. ADOPTED as D2 fix 5.
* **PB-2** — sub-tick clock seam. WITHDRAWN.
* Signal design: either-or, no agreement gate. Recorded.

---

## 11. Parked P-items disposition

| ID | Content | Disposition | Rationale |
|---|---|---|---|
| P1 | (audit-listed) | DEFER | No fired trigger. |
| P5 | (audit-listed) | DEFER | Same. |
| P6 | `flashg1/SolarCharger` study | **ADOPT (shape-match)** | D2 anti-flap. |
| P8 | Enphase saw-tooth rate-modulation | **REJECT-WITH-EVIDENCE** | Verbatim `PLANNING_v4.5.0_TRANSITION_NOTES.md:55`: *"Enphase's `charge_from_grid` is a binary switch (no rate control). When ON, battery pulls at hardware rate ~20 kW. When OFF, ~0 kW. Saw-tooth threshold sits between these two states; hysteresis can't bridge them."* Load-bearing FOR THE ENPHASE BINARY SURFACE; does NOT transfer to Emporia EVSE continuous 6-48 A step 1 (43 legal intermediate values). **P8's replacement is the live compound-load mutex at `energy.py:6240-6263` + `:6290-6328` + `:6341-6365`** (Rev-4 corrected citation, replacing the `PLANNING_v4.5.0_TRANSITION_NOTES.md:60` reference which predates ATTAIN). That mutex bounds the 134 A compound-load case for arbitrage, ATTAIN, and future non-arbitrage grid-charging rungs. D1 does NOT re-solve compound-load; INV-SF-7 subordinates D1 to it. |
| P9 | "No separate stack" fence | REJECT (operator-withdrawn) | Session-scoped timer is not an EV optimizer stack. |
| P13 | (audit-listed) | DEFER | Not on critical path. |

---

## 12. Change log

**Rev-1 → Rev-2** — see prior table (14 items).

**Rev-2 → Rev-3** (from coordinator's P-item read):

| Finding | Severity | Change |
|---|---|---|
| Pause-owner precedence missed by D1 | BLOCKING | INV-SF-7; ELIGIBLE-set control law; pause ENTRY/RELEASE policies; T-PEER-1..5; C17; `deferred_restore_evses` gauge |
| P8 placeholder | Correction | UPGRADED to REJECT-WITH-EVIDENCE with verbatim quote and continuous-vs-binary argument |
| P6 not read | Correction | ADOPT shape-match |

**Rev-3 → Rev-4** (from fourth plan review, peer-hold framing):

| Finding | Severity | Change |
|---|---|---|
| **SF7-B1: fleet-wide surplus add-back inflates S when peer-held EVSE keeps drawing → over-draw** | BLOCKING | INV-SF-4 restated with ELIGIBLE-scoped sum. D1.2 surplus formula switched to inline sum over ELIGIBLE (do NOT call `current_charging_load_w()`). §4 adds explicit non-goal against fleet-wide helper. T-PEER-5 oracle rebased. `s_eligible_kw` observability attribute added. New mutation drill C17c anchors the add-back half. §9 REUSE table: `_get_evse_state` is REUSED for ELIGIBLE per-EVSE reads. |
| **SF7-B2: C17 leaves step 2a byte-identical; T-PEER-4 passes under drill → step 2a is an untested site** | BLOCKING | C17 expected-failure list corrected to T-PEER-1/2/3/5 (T-PEER-4 removed). New C17b anchors step 2a directly. |
| SF7-H1: T-PEER-2 hollow | HIGH | Pinned second explicit assertion (zero writes on tick 2). Test renamed to reflect both assertions. |
| SF7-H2: `_original_amps` not a prune participant; step 2 undefined on no-resolvable-entity | HIGH | D1 point 5 declares `_original_amps` a `_prune_removed_evses` participant; step 2b CLEARS on unresolvable entity. New T-PEER-6. Load-shed `persistence_kind="none"` corner recorded (benign) + `test_solar_follow_load_shed_deferral_clears_on_restart`. `deferred_restore_evses` discharge rule (iii) config-prune added. |
| SF7-M1: `_paused_by_us` accounting silent | MED | New D1.9 subsection accounts for `_paused_by_us`, `_proactive_offpeak_holds`, `_blind_window_liveness_ride` on the record. Cites `energy_pool.py:906`, `:1633-1635`, `database.py:4526-4535` (atomic-write argument). |
| SF7-L1: `_stronger_peer_holds` docstring says "five", loop returns six | LOW | Added to §6 docs drift; fixed in-cycle. |
| SF7-L2 / Q8: D4 citation wrong (transition notes predate ATTAIN) | LOW | Corrected to live mutex at `energy.py:6240-6263` + `:6290-6328` + `:6341-6365` in §2, §5 item 8, §9 REUSE table, §11 P8 disposition. Narrowing recorded as MORE defensible (non-arbitrage grid charging also covered). |
| Q5: release policy did not name `_blind_window_liveness_ride` latch | LOW | Named in the pause RELEASE policy paragraph with cites to `energy.py:5089`/`:5116` and `energy_pool.py:989-999`. |

---

## 13. Cycle-close checklist

* [ ] **Targeted re-review of SF7-B1 and SF7-B2 fixes** (coordinator-scoped).
* [ ] Build in one branch off `develop`.
* [ ] Suite green + baseline-diff clean.
* [ ] Four framing-disjoint reviews A/B/C/D returned; CRITICAL/HIGH fixed.
* [ ] Orchestrator pre-deploy re-grep + real source mutation drills on FIVE R2 sites +
      D3 helper + step-5 ELIGIBLE filter (C17) + step-2a deferral guard (C17b) +
      ELIGIBLE-scoped add-back (C17c) + zero-call-sites confirmation against
      `current_charging_load_w()` inside `SolarFollowController`.
* [ ] Operator checkpoint before deploy.
* [ ] `README_v<version>.md` with prospective Live criteria.
* [ ] Deploy via `./scripts/deploy.sh`.
* [ ] Live validation: sunny-day D1 attributes including `s_eligible_kw`; two-EVSE split;
      release edge restore; D3 DP snapshot with plugged EV; A-CRIT-1/A-CRIT-2 direct;
      INV-SF-7 if arbitrage overlap occurs (else mutation-drill only, deferred criterion
      recorded).
* [ ] README updated with observed `Validated <date>` table.
* [ ] Kanban cards shipped_organic; parked `project_ev_drain_precedence_cycle` retained.
* [ ] Post-ship supersession + consumer-gap audit per CLAUDE.md rule.
