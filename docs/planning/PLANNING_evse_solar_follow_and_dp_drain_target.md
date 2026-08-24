# PLANNING — EVSE solar-following amp modulation + DP drain-target mis-sourcing fix

**Cycle name:** `evse-solar-follow-and-dp-drain-target`
**Tier:** **Tier 3** (operator ruling: "Tier 3 means cost in review. Code itself can be simple.")
**Threads:** `energy`
**Cards:** `EVSE-SOLAR-FOLLOW-AMPS-1` (D1, D2), `EVSE-DRAIN-PRECEDENCE-KNOB-80-1` (D3)
**Design source:** the two card bodies (esp. `DESIGN_CLOSED_2026_08_23`,
`SIGNAL_DESIGN_FINAL_2026_08_23`, `SENSOR_DELTA_MEASURED_2026_08_23`, `SCOPE_FENCE_2026_08_23`,
`OPERATOR_ANSWERS_AND_VERIFIED_FACTS_2026_08_23`, `RE_VERIFIED_2026_08_23_card_stands_memory_was_stale`,
`SCOPING_2026_08_20_ONE_NUMBER_THREE_ROLES`, `RECOMMENDED_DESIGN_D_SPLIT_THE_ROLES`) and
`docs/planning/AUDIT_excess_solar_and_evse_prior_art.md`.
**Probes:** `scripts/probes/delta_probe.py`, `scripts/probes/skew_probe.py`.

**Revision 7 (2026-08-23) — narrow.** Rev-6 rejected PB-1 (drain-protection skip) with a
telemetry counter as replacement, but wired the counter INSIDE
`determine_battery_drain_actions` — contradicting four other Rev-6 constraints that require
that function byte-identical (§8 Review B, orchestrator pre-deploy grep, §13 register,
cycle-close checklist). The irony worth recording: the replacement for a change that
reached into the safety gate was itself a change that reached into the safety gate. Small
and benign, but it lands in the same file, and the zero-diff grep is precisely what would
have caught a re-introduced skip — a counter bump makes that grep noisy and weakens the
guard the cycle just built.

**Rev-7 fix, narrow:** move the counter OUT. `SolarFollowController` already runs an
always-on 60 s tick and already reads `self._ev._paused_by_battery_drain` transitively via
`_stronger_peer_holds`. Derive the counter by EDGE DETECTION on D1's own tick: keep a
per-EVSE previous-membership snapshot; increment when an EVSE transitions from not-in
`_paused_by_battery_drain` to in it while it is in `_excess_solar_active`. Zero edits to
`determine_battery_drain_actions`. The zero-diff grep stays clean and stays load-bearing.
Three specific edge-detector footguns pinned in the spec (edge-not-level; restart seed-and-
skip; 60 s sampling floor as documented under-count).

Everything else in Rev-6 stands: PB-1 REJECTED with its evidence trail, framing retraction,
INV-SF-7's no-exceptions restatement, C18, `solar_replenishing` LEAVE-ALONE, §9 strategy-vs-
safety generalisation. Rev-1..Rev-5 items preserved. §12 change log names each edit.

---

## 0. Tier-3 elevation and framing

(Unchanged Rev-5/6.)

---

## 1. Falsifiable invariants

### INV-SF-1 (non-perturbation)
`SolarFollowController` emits no `switch.turn_on` / `switch.turn_off`. Writes only
`number.set_value` to a current-limit entity, only for an EVSE in `_excess_solar_active`.

### INV-SF-2 (writes only inside sessions)
Both sets empty → zero writes.

### INV-SF-3 (restore is load-bearing, restart-safe)
After removal from `_excess_solar_active` by any code path, current-limit restored to saved
`_original_amps` within one restore tick — subject to INV-SF-7.

### INV-SF-4 (draw bounded by measured surplus over ELIGIBLE)
`ELIGIBLE = {evse_id ∈ _excess_solar_active where NOT _stronger_peer_holds(evse_id) AND
evse_id ∉ _paused_by_dp AND _get_evse_state(evse_id).power_source == "sensor"}`.
`S_eligible = -grid_W + Σ_{ELIGIBLE} evse_power_w`.
`Σ_{i ∈ ELIGIBLE} A_i · 240 · PHASES ≤ max(S_eligible, N_eligible · MIN · 240)`.

### INV-SF-5 (asymmetric reaction to a lagging signal)
Down uncapped; up gated + capped. PRIMARY is 60 s average; up-gate contains ramp mismatch.

### INV-SF-6 (fleet allocation)
`A_total_target = floor(S_eligible/(240·PHASES))`; `A_per_evse = A_total_target //
N_eligible`; clamp `[MIN, MAX]`. Degenerate: all eligible hold at MIN.

### INV-SF-7 (stronger-peer subordination — NO EXCEPTIONS)
While `_stronger_peer_holds(evse_id) is True` OR `evse_id ∈ _paused_by_dp`, no write and
no capture. Applies to BOTH step 2a (restore) AND step 5 (modulation). `_paused_by_dp`
inline per two-site convention. **No exceptions carved out for individual peer owners.
`_paused_by_battery_drain` IS one of the six owners `iter_peer_holds()` returns.**

### INV-RELEASE-1 (D2 hysteresis half only)
Release fires only when `not conditions_met OR solcast<floor` AND streak ≥ MIN_TICKS AND
session age ≥ MIN_ON_S.

### INV-DP-DRAIN-1 / 1b / 2 / 3 / 4 (unchanged)
See §3.D3.

---

## 2. Institutional context verified

Paths under `custom_components/universal_room_automation/domain_coordinators/`:

* `docs/planning/AUDIT_excess_solar_and_evse_prior_art.md`.
* `energy_pool.py` — `PoolOptimizer:58-160` (shape only); `EVChargerController.__init__:186-317`;
  `determine_excess_solar_actions:1318-1701` (release `:1685-1699` = D2 hysteresis half);
  **`determine_battery_drain_actions:1776-1959` — the safety gate, triggers on physical
  evidence (`charging AND battery discharging AND SOC<threshold`); RESUME at `:2000` reads
  `solar_replenishing`. Rev-6/7: this function is BYTE-IDENTICAL post-cycle. Zero edits.
  Zero counter bumps. Zero comments. Any diff here fails the pre-deploy grep.**
  `_soc_envelope_admits_dp_transition:619-648`; `_stronger_peer_holds:383-412` (docstring
  "the five" stale; loop returns six via `EV_REGISTRY.iter_peer_holds()`);
  `_paused_by_dp` inline claim `:1621-1631`; **`_paused_by_battery_drain`** is the set
  D1's edge-detector reads (Rev-7); it is set at the drain-protection pause site inside
  `determine_battery_drain_actions` and discarded on the RESUME side; membership is what
  D1 samples on each tick — D1 does NOT observe the pause DISPATCH, only the resulting
  SET membership;
  `_get_evse_state:650` with v4.2.19 fallback `:690-697`; `_pause_dispatch_ts` /
  `_observed_off_since_pause` `:275-278`; `current_charging_load_w:2300-2312` (fleet-wide,
  NOT USED).
* `energy_pool_owners.py` — `iter_peer_holds()` = 6 owners INCLUDING `battery_drain`
  (`:262-269`); `persistence_kind` ∈ {`"per_evse_bool"`, `"list"`, `"none"`};
  `_paused_by_load_shed` `persistence_kind="none"` (`:298-300`).
* `energy_drain_precedence.py` — `evaluate_dp_transition:609-735`.
* `energy.py` — R2 sites `:4271`, `:4456`, `:4522`, `:4540`, `:4555`; R2-display `:3871`,
  `:4021`; reserve fold `:4733-4742`, `:4829-4833`; write-verify surface gate `:7587-7591`;
  R1 sites `:5842` / `:5977`; R3 site `:3752`; 10 h staleness gate `:1346`; `_KNOWN_HOOKS`
  `:1603-1612`; `self._ev` at `:293`; SLF001 convention at `:4141`, `:4517`, `:4929`,
  `:5031`; `solar_replenishing` at `:5823` (Rev-6 §5 item 11 — LEAVE ALONE); compound-load
  mutex `:6240-6263` + `:6290-6328` + `:6341-6365`; load-shed re-claim `:7259-7282`;
  DP claim-release `:5089`, `:5116`.
* `energy_battery.py` — `compose_release_floor:264`.
* `energy_const.py` — `EVSE_ESTIMATED_POWER_W = 7600` (`:827`); `DP_L1_RATE_THRESHOLD_KW=3.0`;
  `DEFAULT_EV_SOLAR_REPLENISH_SURPLUS_PCT`.
* `database.py:4526-4535` — `save_evse_state` atomic.
* `PLANNING_v4.7.x_APPLIANCE_SCHEDULER.md:41`.
* Memory as prior revisions.

---

## 3. Deliverables

### D1 — SolarFollowController

**Class shape (Rev-5 pin, Rev-7 adds one snapshot field):**

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
        # Rev-7 edge-detector snapshot. None sentinel = "not yet observed";
        # first tick after boot seeds the snapshot and skips counting, mirroring
        # the `previous_total is None` first-observation-skip pattern used
        # elsewhere. A boot-crossing edge is lost (harmless on a monotone
        # telemetry counter); a fabricated trip on every restart is not — at
        # ~2.9 restarts/day it would swamp the real signal.
        self._prev_paused_by_battery_drain: set[str] | None = None
```

Cross-class reads use `self._ev.<attr>` with `# noqa: SLF001`.

**Design points, per-tick control law, Pause ENTRY/RELEASE policies, D1.2 surplus signal
with `power_source` gate, D1.3 self-consistency stop, D1.4 current-limit entities, D1.5
Solcast wiring for D2's release, D1.6 bounded readback verify, D1.7 write-budget
containment, D1.9 non-peer-hold owner accounting:** all unchanged from Rev-5.

**Rev-7 addition to the per-tick control law — STEP 0 (edge-detector, runs unconditionally,
BEFORE the empty-set fast-path):**

```
0. Drain-trip edge detection (Rev-7):
   curr = set(self._ev._paused_by_battery_drain)   # noqa: SLF001
   if self._prev_paused_by_battery_drain is None:
       # First-tick after boot: seed and skip counting (documented harmless
       # loss of at-most-one boot-crossing edge; see D1.8 counter rules).
       self._prev_paused_by_battery_drain = curr
   else:
       prev = self._prev_paused_by_battery_drain
       newly_paused = curr - prev                    # EDGE, not level
       excess_set = set(self._ev._excess_solar_active)  # noqa: SLF001
       for evse_id in newly_paused:
           if evse_id in excess_set:
               self._drain_trips_during_follow += 1
       self._prev_paused_by_battery_drain = curr
   # (Fall through to step 1 empty-set fast path.)
```

Rationale for STEP 0 sitting BEFORE the fast-path exit: an EVSE can be in
`_paused_by_battery_drain` on a tick where `_excess_solar_active` is empty (e.g. drain-
protection paused during a session, session then ended). We still want the snapshot to
track membership every tick so the next transition is detected correctly. The
`if evse_id in excess_set` gate ensures the counter only bumps for the specific
"trip-while-solar-follow-active" event class.

**Rev-7 pinned edge-detector footguns (spec-level, not just code comments):**

1. **Edge, not level.** Increment only on the set transition (`newly_paused = curr - prev`).
   Re-reading membership every tick and adding to the counter would be the double-count
   bug. T-DRAIN-2's "three trips → 3, not 6" oracle is the anchor for this exact bug class.
2. **Restart seed-and-skip.** `_prev_paused_by_battery_drain` starts `None`; first tick
   after boot seeds `_prev_paused_by_battery_drain = curr` WITHOUT counting. Mirrors the
   `previous_total is None` first-observation-skip pattern used elsewhere in the codebase
   for monotone-counter derivation. Choice made explicitly: losing at-most-one boot-
   crossing edge on a monotone telemetry counter is harmless; fabricating a trip on every
   restart is not. At ~2.9 restarts/day a spurious-per-restart implementation would swamp
   the real signal, defeating the counter's purpose ("are trips frequent?").
3. **60 s sampling floor as documented UNDER-count.** A 60 s observer sees a pause only if
   it persists past a tick boundary. This is acceptable because drain-protection pauses
   are STICKY until the release conditions in `energy_pool.py:2000` (`solar_replenishing
   AND SOC ≥ threshold+5`) or `battery_out_of_capacity` are met — they are not one-tick
   blips. The counter therefore under-counts brief-flap trips and never over-counts them.
   Under-count is the safe direction for a signal whose job is "are trips frequent?" —
   the answer 0/rare is trustworthy; a claim of "many" is trustworthy; the only blind spot
   is sub-tick flap, which the pause mechanism does not produce. Recorded so a future
   reader does not tighten the sampling in response to what they think is a bug.

**D1.8 — Status sensor (Rev-7 counter definition updated).**
`sensor.ura_energy_coordinator_solar_follow` attributes:

* `active: bool`
* `eligible_evses: list[str]`
* `s_eligible_kw: float`
* `deferred_restore_evses: list[str]` (gauge)
* `capture_rejected_low: int` (monotone; discrete event)
* **`drain_trips_during_follow: int` (Rev-7 — monotone; derived by D1's own STEP 0
  edge-detector).** Membership rule: incremented once per EVSE per transition from
  `evse_id ∉ _paused_by_battery_drain` to `evse_id ∈ _paused_by_battery_drain` observed
  on D1's 60 s tick, when `evse_id ∈ _excess_solar_active` at the moment of the
  transition-observation tick. **Wire point:** ENTIRELY inside `SolarFollowController`
  (STEP 0). Zero edits to `determine_battery_drain_actions`. The zero-diff grep against
  `energy_pool.py:1776-1959` stays clean and stays load-bearing. Counter class: monotone
  discrete-event, same class as `capture_rejected_low` (a counter that never needs to
  drain because it counts EVENTS rather than open PENDING state). Purpose: telemetry
  — if trips are frequent, ELIGIBLE-scoped surplus sizing is under-estimating something;
  if rare, PB-1's would-have-been-needed premise never materialised. Explicitly UNDER-
  counts sub-tick flap (safe direction, see footgun 3 above).
* `writes_per_hour_per_evse: dict[str, int]`
* `current_amps: dict[str, int]`
* `original_amps: dict[str, float]`
* `stale_ticks: int`
* `excluded_switch_status_evses: list[str]`

**Constants** (unchanged Rev-4 table).

**D1 acceptance (Rev-7 updates to T-DRAIN-1 / T-DRAIN-2):**

* All Rev-5 tests preserved (INV-SF-1..7, T-PEER-1..6, T-STALE-1, T-ITER-1, A-HIGH-3,
  restart, budget, etc.).
* **T-DRAIN-1** (Rev-7: retained; the operator ruling made testable, driven through the
  REAL function — not a source-text assertion). `test_drain_protection_still_pauses_during_solar_follow`:
  EVSE in `_excess_solar_active`; fixture makes drain-protection's PHYSICAL trigger true
  (`charging=True`, `battery_power_w=-500`, `battery_soc < soc_threshold`, `is_offpeak=True`
  or per real caller). **Drive `EVChargerController.determine_battery_drain_actions` as
  the actual production entry point** (not a fake, not a source-grep assertion). Assert:
  (i) the returned action list contains `{service: "switch.turn_off", target:
  <evse_switch>}` for the EVSE (drain-protection fires), (ii) `_paused_by_battery_drain`
  now contains the EVSE, (iii) INV-SF-7 fires on the NEXT D1 tick — the EVSE is now
  peer-held, ELIGIBLE excludes it, no write. **Discriminating vs bug (skip re-inserted):**
  (i) fails — no `switch.turn_off` because the drain-protection loop `continue`d on
  `_excess_solar_active` membership. Different observation. **Discriminating vs
  bug (INV-SF-7 relaxed):** (iii) fails — D1 writes despite the drain-pause.
* **T-DRAIN-2** (Rev-7: rewritten to anchor the new edge-detector wire point).
  `test_drain_trips_during_follow_counter_increments_once_per_event`:
  simulate three drain-protection trips over a session as a sequence of D1 ticks —
  tick 1: `_paused_by_battery_drain={}`, EVSE in `_excess_solar_active`. Seed tick.
  tick 2: `_paused_by_battery_drain={"garage_a"}` (drain fired between ticks). EDGE
  observed; counter 0→1.
  tick 3: `_paused_by_battery_drain={"garage_a"}` (unchanged — still paused).
  Assert counter still 1 (level, not edge, would be 2 — this is the double-count
  guard).
  tick 4: `_paused_by_battery_drain={}` (release fired between ticks). No edge in the
  count-direction; counter still 1.
  tick 5: `_paused_by_battery_drain={"garage_a"}` (second trip). Counter 1→2.
  tick 6: `_paused_by_battery_drain={"garage_a", "garage_b"}` (third trip, different
  EVSE, garage_b also in `_excess_solar_active`). Counter 2→3.
  tick 7: `_paused_by_battery_drain={"garage_a", "garage_b"}`. Counter still 3.
  **Final assertion: counter == 3, NOT 6, NOT 4.** Under level-not-edge bug (increment
  on every tick where the set is non-empty and intersects `_excess_solar_active`):
  ticks 2,3,5,6,7 all increment → counter reaches 5. Different observation.
* **T-DRAIN-3 (Rev-7 add) — restart seed-and-skip.**
  `test_drain_trips_during_follow_first_tick_seeds_without_counting`: instantiate
  `SolarFollowController` fresh; set `_paused_by_battery_drain={"garage_a"}` AND
  `_excess_solar_active={"garage_a"}` BEFORE the first tick fires (simulating restart
  into an already-drain-paused session). Tick 1: assert counter still 0
  (`_prev_paused_by_battery_drain` was None → seed-and-skip). Tick 2: still same set →
  counter still 0. Tick 3: `_paused_by_battery_drain={}` (release). Tick 4:
  `_paused_by_battery_drain={"garage_a"}` (fresh trip observed post-boot). Counter
  0→1. **Under spurious-per-restart bug (counter increments on first tick when the set
  is non-empty):** tick 1 → counter 1 → false report. Different observation.
* **T-DRAIN-4 (Rev-7 add) — under-count of sub-tick flap is DOCUMENTED, not a bug.**
  `test_drain_trips_during_follow_undercounts_sub_tick_flap_is_expected`:
  simulate a sub-tick pause+release that occurs entirely between two D1 ticks — set
  `_paused_by_battery_drain={"garage_a"}` and immediately clear before the next tick
  fires. Assert counter unchanged. Test docstring explicitly names this as the
  documented sampling-floor under-count from §D1.8 footgun 3; a future PR that
  "fixes" this by shortening the tick or subscribing to set-mutation events is
  reaching outside the cycle's scope-fence and should be rejected.

### D2 — Release-gate hysteresis only (Rev-6 — drain-protection skip REMOVED)

(Unchanged from Rev-6. `energy_pool.py:1685-1699` release leg only. `:1776-1959` NOT
touched. Streak + min-on-time + Solcast next-hour. Tests: `test_release_streak_gated`,
`test_release_min_on_time`, `test_release_streak_persists_min_on_time_across_restart`.)

### D3 — DP drain-target mis-sourcing fix (FIVE R2 sites)

(Unchanged Rev-3/4/5.) R2 sites `:4271`, `:4456`, `:4522`, `:4540`, `:4555` route through
`_dp_drain_target_soc(period)`. R1/R3 unchanged. Tests T1..T5.

---

## 4. Non-goals (explicit)

* NOT starting/stopping charges. NOT coordinating with DP. NOT changing the excess-solar
  TRIGGER. NOT changing the EC 5-min tick. NOT extending `_maybe_schedule_write_verify`.
  NOT wiring HVAC coupling. NOT demoting `evse_battery_hold`. NOT changing
  `ev_battery_drain_soc` live value (still 80). NOT changing R1 / R3 sources. NOT touching
  `sensor.mainw_vue_balance_power_minute_average`. NOT using `balanced_net_power_consumption`,
  SPAN, or `sensor.ura_energy_coordinator_envoy_status`. NOT wiring L1 chargers. NOT
  introducing a new `persistence_kind`. NOT auto-remediating offline Garage A / SPAN
  observability gap. NOT feeding `EVSE_ESTIMATED_POWER_W` into D1's control law. NOT
  introducing priority ordering. NOT adding `_paused_by_dp` to `_stronger_peer_holds`.
  NOT re-solving compound-load (live mutex bounds it). NOT building a per-EVSE "no-
  interference latch". NOT using `current_charging_load_w()` for the add-back.
* NOT modifying `determine_battery_drain_actions:1776-1959`. **Rev-7 restated with full
  scope of the byte-identical guarantee: zero edits, zero counter bumps, zero comments,
  zero re-imports. Drain-protection ships untouched. Solar-follow YIELDS to it via
  INV-SF-7; does NOT suppress it; does NOT observe its actions from inside its function
  body. Membership set `_paused_by_battery_drain` is D1's ONLY window into it, sampled
  from D1's tick.**
* NOT modifying `solar_replenishing` (`energy.py:5823`, `energy_pool.py:2000`).
* **Rev-7 add:** NOT shortening D1's 60 s tick or subscribing to owner-set mutation
  events to catch sub-tick drain-protection flap. The under-count is documented (D1.8
  footgun 3, T-DRAIN-4); pause mechanism does not produce sub-tick flap; a future PR
  proposing either is scope-fence violation.

---

## 5. Known couplings

1. DP gate 6 crossover at 12.5 A. 2. Gate 8 charge_hours at low amps. 3. `_dp_house_load_kw`
biased other way. 4. `EVSE_ESTIMATED_POWER_W = 7600` never in D1's control law.
5. `evse_battery_hold` engages at 6 A. 6. Emergent actuation precedence. 7. INV-YIELD-1/2.
8. Live compound-load mutex `energy.py:6240-6263` + `:6290-6328` + `:6341-6365`.
9. `_pause_dispatch_ts` / `_observed_off_since_pause`. 10. `_paused_by_load_shed`
`persistence_kind="none"`.
11. **`solar_replenishing` already exists on the drain-protection RESUME side.** Rev-6
recommendation LEAVE ALONE stands verbatim.
12. **`_paused_by_battery_drain` observed by D1 through set-membership sampling only
(Rev-7).** D1 does not observe the pause dispatch, does not hook into the pause site, and
does not modify the set. Coupling is READ-ONLY set observation on D1's own tick cadence;
under-counts sub-tick flap (documented safe direction).

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
T-STALE-1; T-ITER-1; T-PEER-1..6;
**T-DRAIN-1** `test_drain_protection_still_pauses_during_solar_follow` (Rev-6, retained;
Rev-7 drives REAL function);
**T-DRAIN-2** `test_drain_trips_during_follow_counter_increments_once_per_event` (Rev-7
edge-detector anchor);
**T-DRAIN-3** `test_drain_trips_during_follow_first_tick_seeds_without_counting` (Rev-7
restart);
**T-DRAIN-4** `test_drain_trips_during_follow_undercounts_sub_tick_flap_is_expected` (Rev-7
sampling floor).

D2: `test_release_streak_gated`; `test_release_min_on_time`;
`test_release_streak_persists_min_on_time_across_restart`.

D3: T1..T5.

---

## 8. Review plan — Tier 3, four framing-disjoint passes

* **A — local correctness.** ELIGIBLE-scoped add-back with `power_source` gate; step
  2a/2b/2c attribute-access convention; N5 snapshot iteration; unit conversions;
  **Rev-7: STEP 0 edge-detector (edge-not-level; seed-and-skip; snapshot updated every
  tick regardless of fast-path exit).**
* **B — integration / state-machine + byte-identical no-op.** Class shape; SLF001;
  R1/R3 grep-diff clean; restart paths; must-start-release corner. **Rev-6/7 hard
  invariant: `determine_battery_drain_actions:1776-1959` and `solar_replenishing` path
  (`energy.py:5823` + `energy_pool.py:2000`) BOTH byte-identical to pre-cycle. Rev-7
  strengthens: the counter's edge-detector is in `SolarFollowController.STEP 0`, not
  inside the safety function. Any diff at the safety function fails the pre-deploy grep.**
* **C — REAL per-site source mutation. Rev-7 updated:**
  - C1..C16 as Rev-5.
  - C17/b/c/d/e/f as Rev-5.
  - C18 (Rev-6): re-insert the deleted PB-1 skip into
    `determine_battery_drain_actions` head-of-loop → **T-DRAIN-1 must fail**.
  - **C19 (Rev-7 re-targeted):** **inside `SolarFollowController.STEP 0`**, replace the
    edge-detector's `newly_paused = curr - prev` computation with `newly_paused = curr`
    (level-not-edge bug) → **T-DRAIN-2 must fail** (counter reaches 5 instead of 3 across
    the T-DRAIN-2 tick sequence). Confirms the counter is derived by EDGE, not LEVEL,
    and that the wire point is inside `SolarFollowController` (not the safety function).
  - **C19b (Rev-7 add):** replace the seed-and-skip pattern (delete the
    `if self._prev_paused_by_battery_drain is None: seed and skip` branch) so the first
    tick counts pre-existing membership → **T-DRAIN-3 must fail** (spurious increment on
    restart).
* **D — adversarial completeness / diff-blind.** Re-enumerate ENTIRE R2 set; discard
  sites; peer-hold mutation sites; `number.set_value` writers. Rev-6 additional D task
  retained: enumerate every place `_excess_solar_active` is READ from OUTSIDE
  `SolarFollowController` and confirm each reader either subordinates to strong-peer
  safety correctly or is not a safety gate. **Rev-7 additional D task: enumerate every
  READ or WRITE of `_paused_by_battery_drain` from OUTSIDE `determine_battery_drain_actions`
  (the writer is inside; readers include D1's STEP 0 Rev-7); confirm all readers are
  passive observers.** Legal-config combinatorial. Every leak → concrete legal-config
  repro.

**Orchestrator pre-deploy verification:** re-grep all five R2 sites; re-grep six peer-hold
owner sets + `_paused_by_dp`; run mutation drills C17/b/c/d/e/f + C18 + C19 + C19b;
zero-call-sites confirmation against `current_charging_load_w()` and bare
`EVSE_ESTIMATED_POWER_W` inside `SolarFollowController`; **grep-check that
`determine_battery_drain_actions` has zero diff in the cycle (Rev-7 preserves this — the
Rev-6 addition that walked into this function is retracted); grep-check that the
`_drain_trips_during_follow` increment site is INSIDE `SolarFollowController` only (a
single occurrence, in STEP 0, no occurrences under `determine_battery_drain_actions` or
elsewhere in `energy_pool.py:1776-1959`)**; grep-check that `solar_replenishing` path has
zero diff; diff-check against §13 register.
Operator checkpoint BEFORE deploy.

---

## 9. REUSE vs NEW

| Item | Verdict | Cite |
|---|---|---|
| `PoolOptimizer` shape | REUSE (shape only) | `energy_pool.py:58-160` |
| `_execute_service_action` | REUSE | — |
| `_excess_solar_active` membership | REUSE | `energy_pool.py:202` |
| Per-EVSE inline persistence for `_original_amps` | REUSE | `energy.py:1839`, `:1365-1366` |
| `_get_evse_state` | REUSE | `energy_pool.py:650` |
| `power_source` field discrimination | REUSE | `energy_pool.py:700-706` |
| `compose_release_floor()` | REUSE | `energy_battery.py:264` |
| `_ev_battery_drain_soc` at R1/R3 | REUSE unchanged | — |
| TOU peak-clear | REUSE | `energy_pool.py:1354-1374` |
| `_stronger_peer_holds` + inline `_paused_by_dp` (six owners including `battery_drain`) | REUSE | `energy_pool.py:383-412`, `:1621-1631` |
| Cross-class SLF001 convention | REUSE | `energy.py:4141`, `:4517`, `:4929`, `:5031` |
| Anti-flap duration threshold (D2) | REUSE | `PLANNING_v4.7.x_APPLIANCE_SCHEDULER.md:41` |
| Live compound-load mutex | REUSE unchanged | `energy.py:6240-6263` + `:6290-6328` + `:6341-6365` |
| `_prune_removed_evses` participation for `_original_amps` | REUSE mechanism | `energy_pool_owners.py:345+` |
| `determine_battery_drain_actions` (unchanged, byte-identical guarantee — Rev-6/7) | REUSE unchanged | `energy_pool.py:1776-1959` |
| `solar_replenishing` on RESUME side (unchanged) | REUSE unchanged | `energy.py:5823`, `energy_pool.py:2000` |
| **`_paused_by_battery_drain` set-membership as an observable (Rev-7)** | REUSE (READ-ONLY, from D1's tick) | `energy_pool.py:_paused_by_battery_drain` mutated inside `determine_battery_drain_actions`; D1's STEP 0 samples it without writing |
| `SolarFollowController` class | NEW | — |
| Session-scoped 60 s timer | NEW | — |
| ELIGIBLE-scoped surplus add-back with `power_source` gate | NEW | — |
| `_dp_drain_target_soc(period)` helper | NEW | — |
| Release-gate streak + min-on-time | NEW | — |
| Solcast next-hour stop | NEW | — |
| `SOLAR_FOLLOW_*` constants + Numbers | NEW | — |
| **`drain_trips_during_follow` counter derived by D1's STEP 0 edge-detector (Rev-7)** | NEW | Wire point INSIDE `SolarFollowController.STEP 0`, NOT inside `determine_battery_drain_actions`. Preserves zero-diff invariant on the safety function. |
| Bounded in-controller readback verify | NEW | — |
| `BatteryStrategy.set_offpeak_drain_target` (conditional) | NEW | — |

**Note on why observing a set rather than a dispatch is the right shape (Rev-7):** D1 is
already reading `_paused_by_battery_drain` transitively via `_stronger_peer_holds` for
INV-SF-7. Adding STEP 0 makes an existing implicit read explicit and derives telemetry
from it. Zero new coupling; the pause site is untouched.

---

## 10. Design pushback recorded

### PB-1 — REJECTED (Rev-6, retained Rev-7)

(Full evidence trail unchanged from Rev-6: operator challenge quoted verbatim, INV-SF-7
contradiction (`_paused_by_battery_drain` in `iter_peer_holds()` at
`energy_pool_owners.py:262-269`), Rev-2 skew probe numbers (241 W → 1,610 W, 6.7×
degradation in fast-solar regime), agreement-gate symmetry callout, cost-asymmetry
argument, fill-priority-analogy retraction with strategy-vs-safety-gate generalisation,
retracted "runs after solar = defect" framing.)

**Rev-7 addendum to PB-1's replacement:** the telemetry counter that replaced the skip
lives INSIDE `SolarFollowController` (STEP 0 edge-detector on D1's own tick), NOT inside
`determine_battery_drain_actions`. Rev-6 wired it inside the safety function, which
contradicted the zero-diff constraint that keeps the safety function's byte-identical
guarantee load-bearing. Rev-7 corrects.

### PB-2 — WITHDRAWN (Rev-2).
### Signal design (either-or, no agreement gate) — RECORDED (Rev-2).

---

## 11. Parked P-items disposition

P1/P5/P13 DEFER. P6 ADOPT. P8 REJECT-WITH-EVIDENCE. P9 REJECT.

---

## 12. Change log

Rev-1→Rev-2: 14 items.
Rev-2→Rev-3: pause-owner precedence BLOCKING; P8 upgrade; P6 ADOPT.
Rev-3→Rev-4: SF7-B1/B2 BLOCKING; SF7-H1/H2 HIGH; SF7-M1 MED; SF7-L1/L2 LOW; Q5 LOW.
Rev-4→Rev-5: BLOCKING-1/2/3; N1-N5; §13 register created.
Rev-5→Rev-6: PB-1 REJECTED with evidence; `determine_battery_drain_actions` byte-identical
constraint; `solar_replenishing` LEAVE-ALONE; strategy-vs-safety-gate generalisation;
§13 register gains "solar-follow never suppresses a strong-peer safety gate" row.

**Rev-6→Rev-7:**

| Finding | Severity | Change |
|---|---|---|
| **Rev-6's counter wire-point contradicted Rev-6's own zero-diff constraint on `determine_battery_drain_actions`** | BLOCKING (self-contradiction) | Counter moved OUT: derived by D1's own STEP 0 edge-detector reading `_paused_by_battery_drain` set membership across D1 ticks. Zero edits to the safety function. §D1.8 counter definition rewritten to name the new wire point + edge-detector rules. Three footguns pinned in spec: (1) edge-not-level (T-DRAIN-2 anchor); (2) restart seed-and-skip pattern (T-DRAIN-3 anchor); (3) 60 s sampling-floor documented under-count (T-DRAIN-4 anchor, plus §4 non-goal against shortening the tick or subscribing to set-mutation events). New tests T-DRAIN-3 + T-DRAIN-4. Mutation drill C19 re-targeted (edge→level → T-DRAIN-2 fails); new C19b (delete seed-and-skip → T-DRAIN-3 fails). §9 REUSE row updated: `_paused_by_battery_drain` is a READ-ONLY observable from D1's tick; counter wire point INSIDE `SolarFollowController`. §5 known couplings gains item 12 documenting the set-observation coupling. Rev-6's §D1.8 wire-point text ("`EVChargerController.determine_battery_drain_actions` bumps …") is RETRACTED. Rev-6's PB-1 evidence trail, INV-SF-7 restatement, C18, strategy-vs-safety-gate generalisation, `solar_replenishing` LEAVE-ALONE, and §13 register row all UNCHANGED. |
| T-DRAIN-1 assertion drove source text implicitly | Correction | T-DRAIN-1 test spec updated to explicitly drive `EVChargerController.determine_battery_drain_actions` as the production entry point (real function, not a fake, not a source-grep assertion). Also gains discriminating case against a hypothetical "INV-SF-7 relaxed" bug (D1 writes despite drain-pause). |
| Orchestrator pre-deploy grep needed strengthening | Correction | §8 orchestrator verification adds: grep-check that `_drain_trips_during_follow` increment site occurs exactly ONCE, INSIDE `SolarFollowController`; ZERO occurrences under `energy_pool.py:1776-1959`. |
| Review D task | Correction | §8 Review D adds task to enumerate every READ / WRITE of `_paused_by_battery_drain` outside `determine_battery_drain_actions`; confirm all readers (including D1's STEP 0) are passive observers. |

---

## 13. Closed concerns — must stay closed

(Rev-7 refines the Rev-6 row.)

| Concern | Round originally closed | The one-line invariant that keeps it shut |
|---|---|---|
| `EVSE_ESTIMATED_POWER_W` reaches D1's control law | Rev-2 (A-MED-1); re-opened Rev-3 via `current_charging_load_w()`; re-opened Rev-4 via `_get_evse_state.charging`; re-closed Rev-5 | D1's surplus add-back sums ONLY EVSEs whose `_get_evse_state.power_source == "sensor"`. Future-revision grep-check for `EVSE_ESTIMATED_POWER_W`, `current_charging_load_w`, `switch_status`, `state.get("charging")` in D1's diff. |
| Parallel derivation of the DP drain target | Rev-2 (B-1) | `_dp_drain_target_soc` uses `compose_release_floor` ONLY; None fallback to static reserve. Future-revision grep-check for `current_offpeak_drain_target(` outside `energy_battery.py`. |
| Fleet-wide surplus add-back over-drawing | Rev-4 (SF7-B1) | `S_eligible` sums add-back ONLY over ELIGIBLE. §4 non-goal against `current_charging_load_w()`. |
| New `persistence_kind` introduced | Rev-2 (A-HIGH-2) | Existing inline column OR existing KV shape. |
| `SOLAR_FOLLOW_HEADROOM_KW` orphan | Rev-2 (B-6) | INV-SF-4 has no headroom term. |
| Missed R2 emission site | Rev-2 (A-CRIT-1) | §3.D3 lists all five. Grep-check `_ev_battery_drain_soc` confirms only R1/R3 remain. |
| Same-tick revert flap | Rev-2 (A-CRIT-2) | `:4555` sources from `_dp_drain_target_soc(period)`. INV-DP-DRAIN-1b. |
| R1 pause ceiling collapse | Rev-2 (HIGHEST_PROBABILITY_BUILD_ERROR) | `determine_battery_drain_actions(soc_threshold=)` unchanged at `:5842` + `:5977`. INV-DP-DRAIN-2 + drill C2. |
| Solar-follow acts on a peer-held EVSE | Rev-3 (SF7 peer-hold-missed) | INV-SF-7 + ELIGIBLE step 5 + guard step 2a. C17 + C17b. |
| Restore-pass mutation-during-iteration crash | Rev-5 (N5) | `list(self._original_amps)` snapshot. T-ITER-1. |
| `SolarFollowController` shape ambiguous | Rev-5 (BLOCKING-2) | `__init__(hass, ev: EVChargerController, ...)`; SLF001 convention. |
| Hollow test anchor via fixture that doesn't perturb the tested branch | Rev-3 (SF7-H1); re-closed Rev-5 (BLOCKING-3) | Peer-hold test fixtures MUST move surplus beyond DEADBAND and outside up-gate. |
| **Solar-follow suppresses a strong-peer safety gate — OR reaches into its function body for any purpose, including telemetry** | Rev-6 (PB-1 REJECTED); **strengthened Rev-7** | INV-SF-7 has NO exceptions. `_paused_by_battery_drain` IS in `iter_peer_holds()`; solar-follow yields to it. **`determine_battery_drain_actions:1776-1959` is BYTE-IDENTICAL post-cycle: zero edits, zero counter bumps, zero comments, zero re-imports.** Any observable derived from drain-protection state comes from EXTERNAL set-membership sampling (D1's STEP 0 edge-detector), never from inside the safety function. C18 mutation drill re-inserts the skip → T-DRAIN-1 fails. **Rev-7: the counter that replaced the skip lives INSIDE `SolarFollowController.STEP 0`; C19 and C19b anchor its correctness (edge-not-level; restart seed-and-skip); the pre-deploy grep confirms the increment site occurs ZERO times inside the safety function.** Future-revision grep-check that any code touching `determine_battery_drain_actions` does NOT add a membership skip or a counter/observability hook. Rule generalizes: telemetry from a safety gate is derived externally by observation, not by reaching in. |

---

## 14. Cycle-close checklist

* [ ] Targeted re-review of Rev-7 counter wire-point (coordinator-scoped).
* [ ] Build in one branch off `develop`.
* [ ] Suite green + baseline-diff clean.
* [ ] Four framing-disjoint reviews A/B/C/D returned; CRITICAL/HIGH fixed.
* [ ] Orchestrator pre-deploy: re-grep five R2 sites; re-grep six peer-hold owner sets +
      `_paused_by_dp`; run mutation drills C17/b/c/d/e/f + C18 + C19 + C19b;
      zero-call-sites confirmation against `current_charging_load_w()` and bare
      `EVSE_ESTIMATED_POWER_W` inside `SolarFollowController`;
      **grep-check `determine_battery_drain_actions:1776-1959` has ZERO diff**;
      **grep-check `_drain_trips_during_follow` increment site occurs exactly ONCE, inside
      `SolarFollowController.STEP 0`, and ZERO occurrences under
      `energy_pool.py:1776-1959`**;
      grep-check `solar_replenishing` path has ZERO diff; diff-check against §13 register.
* [ ] Operator checkpoint before deploy.
* [ ] `README_v<version>.md` with prospective Live criteria.
* [ ] Deploy via `./scripts/deploy.sh`.
* [ ] Live validation: sunny-day D1 attributes including `s_eligible_kw`, `stale_ticks`,
      `excluded_switch_status_evses`, `drain_trips_during_follow`; two-EVSE split;
      release-edge restore; D3 DP snapshot with plugged EV; A-CRIT-1/A-CRIT-2 direct;
      INV-SF-7 if arbitrage overlap; BLOCKING-1 live confirmation if Emporia cloud blip;
      **Rev-7: if a drain-protection trip fires while solar-follow is active,
      `drain_trips_during_follow` increments by exactly 1 per trip event (not per tick
      of persistence); `determine_battery_drain_actions` still fires `switch.turn_off`
      (T-DRAIN-1 live-analogue).**
* [ ] README updated with observed `Validated <date>` table.
* [ ] Kanban cards shipped_organic; parked `project_ev_drain_precedence_cycle` retained.
* [ ] Post-ship supersession + consumer-gap audit per CLAUDE.md rule.
