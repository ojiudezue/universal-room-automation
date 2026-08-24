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
`PLANNING_evse_solar_follow_and_dp_drain_target.md` (Rev-1..Rev-8) and revised through
Rev-9 (split + D4 attribution correction) and Rev-10 (breaker-caveat retraction + idle-
release exit for safe-parking). The DP drain-target fix lives in
`PLANNING_dp_drain_target_mis_sourcing.md`.

**Runtime relationship to the DP fix (informational, not a build dependency).**
The DP fix changes which drain target DP consumes, which changes when DP holds EVSEs via
`_paused_by_dp`. This controller reads `_paused_by_dp` as part of its ELIGIBLE set (per
INV-SF-7), but has NO code dependency on the DP fix.

**Sequencing preference: SHIP THE DP FIX FIRST.** Preferred, not merely acceptable —
this controller then live-validates against corrected DP behaviour rather than a known-
wrong drain target.

---

## 0. Tier-3 elevation and framing

Two independent risks:

* **NEW WRITER on a live cloud actuator at 1-min cadence.** URA has never written amps
  before. Wrong containment = write-flood incident class. Wrong restore = silently
  crippled next charge. Wrong reactivity = drives battery discharge harder than the
  binary version. Wrong fleet allocation makes two chargers each pull the full surplus.
  Wrong peer-hold subordination makes solar-follow act on a device a stronger owner has
  claimed. Wrong surplus-denominator alignment causes over-draw when a peer-held EVSE
  keeps drawing. Wrong signal-source discrimination lets `EVSE_ESTIMATED_POWER_W`
  fabrication reach the control law via the v4.2.19 `_get_evse_state` fallback. Idle-bay
  dilutes allocation denominator. **Safe-parking without an exit means empty bays and
  finished cars sit claimed indefinitely (Rev-10, operator-flagged).**
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
`energy.py:5183-5225`, config prune via `_prune_removed_evses`, **or idle-release per
INV-RELEASE-2**), current-limit restored to saved `_original_amps` within one restore
tick — subject to INV-SF-7.

### INV-SF-4 (draw bounded by measured surplus — DRAWING vs ELIGIBLE)
`ELIGIBLE = {evse_id ∈ _excess_solar_active where NOT _stronger_peer_holds(evse_id) AND
evse_id ∉ _paused_by_dp AND _get_evse_state(evse_id).power_source == "sensor"}`.
`DRAWING = {evse_id ∈ ELIGIBLE where _get_evse_state(evse_id).charging is True}`
(`charging = power > EVSE_CHARGING_POWER_THRESHOLD = 100 W`, `energy_pool.py:691`).
`S_eligible = -grid_W + Σ_{DRAWING} evse_power_w`.

**Bound on commanded amps:**
`Σ_{i ∈ DRAWING} A_i · 240 · PHASES ≤ max(S_eligible, N_drawing · MIN · 240)`.
`Σ_{i ∈ ELIGIBLE \ DRAWING} A_i · 240 · PHASES ≤ (N_eligible - N_drawing) · MIN · 240`.

**Physical-draw bound within ≤60 s window:**
`Σ_{physically drawing at t} A_i · 240 · PHASES ≤ max(S_eligible, N_eligible · MIN · 240)`.
Plug-in mid-window over-commit ≤ `(N_eligible - N_drawing) · MIN · 240` for ≤60 s.

Fabricated-power (`power_source == "switch_status"`) EVSEs are EXCLUDED from ELIGIBLE;
they route to D1.3 STALE (no writes at MAX_TICKS).

### INV-SF-5 (asymmetric reaction to a lagging signal)
Down uncapped; up gated + capped. PRIMARY is a 60 s AVERAGE; the up-gate contains ramp
mismatch. INV-SF-4 is bookkeeping; INV-SF-5 is the physical lag containment.

### INV-SF-6 (fleet allocation)
`N_denom = max(1, N_drawing)`.
`A_total_target = floor(S_eligible / (240 · PHASES))`.
`A_per_drawing = clamp(A_total_target // N_denom, MIN, MAX)`.

Command routing:
- DRAWING bays receive `A_per_drawing`.
- ELIGIBLE \ DRAWING bays receive `SOLAR_FOLLOW_MIN_AMPS` (6 A) safe-parking.

Degenerate cases:
- `N_drawing == 0, N_eligible ≥ 1`: N_denom=1 (no divide-by-zero); all ELIGIBLE get MIN
  safe-parking.
- `N_drawing = 1, N_eligible = 2`: drawing bay full commanded surplus; idle bay MIN
  safe-parking.
- `N_drawing == N_eligible ≥ 1`: standard equal-split.

### INV-SF-7 (stronger-peer subordination — NO EXCEPTIONS)
While `_stronger_peer_holds(evse_id) is True` OR `evse_id ∈ _paused_by_dp`, no write and
no capture. Applies to BOTH step 2a (restore) AND step 5 (modulation). `_paused_by_dp`
INLINE per two-site convention. No exceptions for individual peer owners.
`_paused_by_battery_drain` IS in `iter_peer_holds()`.

### INV-RELEASE-1 (D2 hysteresis path)
Release fires only when `not conditions_met OR solcast<floor` AND streak ≥ MIN_TICKS AND
session age ≥ MIN_ON_S.

### INV-RELEASE-2 (idle exit for safe-parking — Rev-10 new, INDEPENDENT of INV-RELEASE-1)
Under any excess-solar-active EVSE, if `_idle_streak_ticks[evse_id] >=
SOLAR_FOLLOW_IDLE_RELEASE_TICKS` AND session age ≥ `SOLAR_RELEASE_MIN_ON_S`, the release
path fires (switch.turn_off, drop from `_excess_solar_active`, D1's next tick restores
`_original_amps`). This exit is INDEPENDENT of `conditions_met` and
`solcast_next_hour_w` — a bay that has not been DRAWING for the streak represents
"nothing to do here" (finished car, empty bay, or terminally-refused pilot handshake);
safe-parking must not persist indefinitely. Safe-parking without an exit is a suppression
without a discharge, which violates `feedback_suppression_needs_discharge`.

**On observability of "target reached":** URA CANNOT directly observe a car's SOC or its
"target reached" state. The Emporia is a relay plus power meter; no J1772 SOC leg is
exposed, and Emporia's own status field does not distinguish "car finished" from "car not
plugged." The sustained-`charging == False` proxy is what URA has. It correctly conflates
finished-car, empty-bay, and pilot-refusal into the same "nothing to do" bucket, which is
the right conflation for a release trigger (all three mean the same thing to a solar-
allocation policy: don't hold this bay).

---

## 2. Institutional context verified

Paths under `custom_components/universal_room_automation/domain_coordinators/`:

* `docs/planning/AUDIT_excess_solar_and_evse_prior_art.md` (all sections).
* `energy_pool.py` — `PoolOptimizer:58-160` (template shape only); `EVChargerController.__init__:186-317`;
  `determine_excess_solar_actions:1318-1701` (release `:1685-1699` = D2 hysteresis half);
  `determine_battery_drain_actions:1776-1959` — BYTE-IDENTICAL post-cycle;
  `_soc_envelope_admits_dp_transition:619-648`;
  `_stronger_peer_holds:383-412` (docstring "the five" stale — loop returns six via
  `EV_REGISTRY.iter_peer_holds()`); `_paused_by_dp` inline claim `:1621-1631`;
  fill-priority `_excess_solar_active` skip prior art `:2214-2219` (NOT template for D2);
  excess-solar CLAIM path at `:1650-1656` (byte-identical post-cycle; switch-on happens
  WITHOUT a plug check — empty bay is ELIGIBLE-not-DRAWING, handled inside D1);
  `_get_evse_state:650` with v4.2.19 fallback `:690-697`
  (`power_source="switch_status"`, `power=EVSE_ESTIMATED_POWER_W=7600 W`); `charging =
  power > EVSE_CHARGING_POWER_THRESHOLD` at `:691`; `current_charging_load_w:2300-2312`
  (fleet-wide; NOT USED); `_pause_dispatch_ts` / `_observed_off_since_pause`
  `:275-278`; **`_paused_by_grid_cap` pause site at `:1723-1735`** — the v4.0.18
  grid-import cap (see §5 item 8).
* `energy_pool_owners.py` — `iter_peer_holds()` = 6 owners INCLUDING `battery_drain`
  (`:262-269`); `persistence_kind` ∈ {`"per_evse_bool"`, `"list"`, `"none"`};
  `_paused_by_load_shed` `persistence_kind="none"` (`:298-300`).
* `energy.py` — `self._ev` at `:293`; SLF001 convention at `:4141`, `:4517`, `:4929`,
  `:5031`; `solar_replenishing` at `:5823`; live compound-load mutex at `:6240-6263` +
  `:6290-6328` + `:6341-6365`; load-shed re-claim `:7259-7282`.
* `energy_battery.py` — `solar_production_w:1586-1612`; `net_power_w:1614-1623`.
* `energy_const.py` — `EVSE_ESTIMATED_POWER_W = 7600` (`:827`);
  `EVSE_CHARGING_POWER_THRESHOLD = 100` (`:826`).
* `database.py:4526-4535` — `save_evse_state` atomic for `paused_by_us` +
  `excess_solar_active`.
* Historical git-log verification for §5 item 8: `_paused_by_grid_cap` introduced in
  **v4.0.18** (commit `1a499f0b8`); `_paused_by_arbitrage` in **v4.5.0**
  (commit `f3deabc84`).
* Memory: `project_optimizer_db_write_flood_incident_2026_06_09`;
  `project_ev_drain_precedence_cycle`; **`feedback_suppression_needs_discharge`** (the
  standing rule Rev-10 INV-RELEASE-2 discharges);
  `feedback_hollow_test_anchors`;
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

Cross-class reads use `self._ev.<attr>` with `# noqa: SLF001`. Lifecycle: instantiated
by `EnergyCoordinator.async_setup` after `EVChargerController` construction;
`async_track_time_interval` timer at `SOLAR_FOLLOW_TICK_S` (=60 s) started here.

**Design points 1-8 unchanged from Rev-8** (always-on timer + empty-set fast path;
fleet allocation over DRAWING with commands over ELIGIBLE; 6 A hold; no
`SOLAR_FOLLOW_HEADROOM_KW`; `_original_amps` persistence via existing shape and prune
participation; capture sanity guard; timer-based restart mirror; `EVSE_ESTIMATED_POWER_W`
never reaches control law).

**Per-tick control law (unchanged from Rev-8; steps 0-9 as spec'd, using the
`_ev._paused_by_battery_drain` observation for STEP 0 and ELIGIBLE/DRAWING split in
steps 5-9).**

**Pause ENTRY/RELEASE policies, Q5 must-start-release corner, one-tick lag on startup
transition:** unchanged from Rev-8.

**D1.2 surplus signal, D1.3 self-consistency stop, D1.4 current-limit entities, D1.5
Solcast wiring, D1.6 bounded readback verify, D1.7 write-budget containment, D1.9
non-peer-hold accounting:** unchanged from Rev-8.

**D1.8 — status-sensor observability (Rev-10 adds two attributes for idle-release):**
`sensor.ura_energy_coordinator_solar_follow` attributes:
* `active`, `eligible_evses`, `drawing_evses`, `safe_parked_evses`, `s_eligible_kw`,
  `deferred_restore_evses` (gauge), `capture_rejected_low` (monotone),
  `drain_trips_during_follow` (monotone), `writes_per_hour_per_evse`, `current_amps`,
  `original_amps`, `stale_ticks`, `excluded_switch_status_evses` — unchanged Rev-8.
* **`idle_streak_ticks: dict[str, int]` (Rev-10 add)** — per-EVSE current idle-streak
  value; observability aid for T-IDLE-3's mid-charge-pause-not-released oracle.
* **`idle_released_this_session: int` (Rev-10 add)** — monotone counter, incremented
  once each time an EVSE is idle-released via INV-RELEASE-2. Same discrete-event class
  as `capture_rejected_low` (no discharge needed).

**Constants (D1 knob ladder — Rev-10 adds one row):**

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
| **`SOLAR_FOLLOW_IDLE_RELEASE_TICKS`** | **1** | **4** | **Rev-10. Ticks counted on the D2 cadence (called from EC 5-min tick), so 4 × 5 min = 20 min. Justification: (a) covers typical onboard-charger pause events (thermal throttle 5-10 min, cell-balancing similar); (b) exceeds D2's `SOLAR_RELEASE_MIN_TICKS=3` (15 min) so a car pausing right at end-of-charge cannot be released by idle before it can be released by hysteresis; (c) represents "there is nothing left to do" rather than a transient pause. Rung-1 protocol constant tuned to EVSE behaviour, not policy the operator would tune weekly.** |

**D1 acceptance (Rev-10 unchanged from Rev-8 except adds the T-IDLE-* tests
under D2 below — those tests exercise D2 machinery but the observability lives on D1's
sensor).**

### D2 — Release-gate hysteresis + idle-release exit for safe-parking

**Where:** `EVChargerController.determine_excess_solar_actions:1685-1699` (release leg)
ONLY. `determine_battery_drain_actions:1776-1959` is NOT touched (drain-protection is a
strong peer per INV-SF-7; byte-identical).

**Rev-8 changes (unchanged):**

1. Add `_conditions_met_false_streak_ticks: dict[str, int]` and
   `_excess_solar_started_at: dict[str, datetime]` on `EVChargerController`.
2. Stamp `_excess_solar_started_at[evse_id]` on session entry. Persist per-EVSE as an
   inline column sibling of `excess_solar_active`.
3. **Release condition (hysteresis path, INV-RELEASE-1)** fires ALL of:
   - `not conditions_met` OR `solcast_next_hour_w < SOLAR_FOLLOW_NEXTHOUR_FLOOR_W`
   - streak `>= SOLAR_RELEASE_MIN_TICKS` (=3)
   - session age `>= SOLAR_RELEASE_MIN_ON_S` (=300)
4. On `conditions_met` True: reset streak.

**Rev-10 additions — idle-release exit (INV-RELEASE-2):**

5. Add `_idle_streak_ticks: dict[str, int]` on `EVChargerController`. Initialize to 0
   for `evse_id` at session entry (when `_excess_solar_active.add` fires, alongside the
   `_excess_solar_started_at` stamp). Clear on session end (any release path).
6. **Idle-streak observation.** On each D2 tick, for each `evse_id ∈
   _excess_solar_active`, read `_get_evse_state(evse_id).charging`:
   - `charging is True` → `_idle_streak_ticks[evse_id] = 0`
   - `charging is False` → `_idle_streak_ticks[evse_id] += 1`
   Applies uniformly regardless of whether the bay has ever drawn this session (see
   "Interaction with startup case" below for justification).
7. **Idle-release condition (INDEPENDENT of INV-RELEASE-1)** fires when BOTH:
   - `_idle_streak_ticks[evse_id] >= SOLAR_FOLLOW_IDLE_RELEASE_TICKS` (=4, i.e. 20 min
     at 5-min cadence)
   - session age `>= SOLAR_RELEASE_MIN_ON_S` (=300, i.e. 5 min)
   Release path is the same as INV-RELEASE-1: emit `switch.turn_off`, drop from
   `_excess_solar_active`, clear `_idle_streak_ticks[evse_id]`. D1's next tick observes
   the membership drop and step 2 fires `_original_amps` restore.
8. **`idle_released_this_session` counter** (D1.8) bumped when an idle-release fires.

**Interaction with startup case (Rev-10 explicit — the "pick one and justify" decision).**
Two options considered:

- **Option A:** idle-streak starts only after the bay has drawn at least once in the
  session (per-EVSE `_has_drawn_this_session` flag).
- **Option B (CHOSEN):** single counter increments every tick where `charging == False`;
  `SOLAR_RELEASE_MIN_ON_S` (5 min) covers the pilot-handshake + car-ramp time.

**Rationale for Option B:** modern EVSE-car pairs complete J1772 pilot handshake in ~1s
and ramp to full amps in <30 s. 5 min is 10× that. A newly-commanded bay has 5 min under
the `MIN_ON_S` floor before any release can fire, then must accumulate 4 idle ticks (20
min) before the idle path triggers — 25 min total from session start for a bay that never
draws. A car taking >5 min to start drawing is a hardware issue outside this cycle's
scope. Option A would require an extra field and produce identical behaviour for the
common case; Option B is simpler and covers both empty-bay and finished-car cases
identically, which is the correct conflation given URA cannot observe "target reached"
directly (see INV-RELEASE-2 note).

**Why the idle-release path is INDEPENDENT of the hysteresis path** (not folded into
INV-RELEASE-1's conditions). `conditions_met` is house-side: battery SOC threshold AND
Solcast remaining. It can be True indefinitely while a bay sits idle (finished car,
empty bay). Requiring the conditions-met streak alongside the idle streak would prevent
release in exactly the scenarios INV-RELEASE-2 exists to catch. The two paths share only
the `MIN_ON_S` floor, which prevents both from firing during startup ramp.

**Discharge rule per `feedback_suppression_needs_discharge`:** the idle counter counts
"suppression state" (bay held despite not drawing). Discharge paths: (i) `charging`
becomes True → counter resets to 0 (car resumed); (ii) idle-release fires → counter
cleared as part of session-end cleanup; (iii) session ends via any other path
(hysteresis release, peak clear, blind-window drop, etc.) → same cleanup. No discharge
path is missing.

**Design provenance (P6 shape-match):** anti-flap duration-threshold pattern per
`PLANNING_v4.7.x_APPLIANCE_SCHEDULER.md:41` (`flashg1/SolarCharger`) applies equally to
the idle streak — same shape as `SOLAR_RELEASE_MIN_TICKS`. Recorded so future reviewers
know both duration-threshold uses are field-tested prior art.

**Constants:** `SOLAR_RELEASE_MIN_TICKS` (rung 1, 3); `SOLAR_RELEASE_MIN_ON_S`
(rung 3, 300); **`SOLAR_FOLLOW_IDLE_RELEASE_TICKS` (rung 1, 4)** — see D1 knob table for
full rationale.

**D2 acceptance:**

* `test_release_streak_gated` — SOC 95→94→95→94; no turn-off (hysteresis path,
  unchanged Rev-8).
* `test_release_min_on_time` — session starts, SOC drops at 30 s; no turn-off until
  300 s (hysteresis path).
* `test_release_streak_persists_min_on_time_across_restart` (hysteresis path).
* **T-IDLE-1** (Rev-10 add) `test_idle_release_after_finished_car`. Fixture: garage_a
  in `_excess_solar_active`, `charging=True, power=5000` for ticks 1-5 (draws through
  MIN_ON_S floor), then `charging=False, power=0` for ticks 6-9. At tick 6:
  `_idle_streak_ticks[garage_a]=1`. At tick 9: `_idle_streak_ticks=4 ≥
  IDLE_RELEASE_TICKS`; session age 45 min ≥ 5 min. Assert: release fires — actions
  contain `switch.turn_off` for garage_a; `_excess_solar_active` no longer contains
  garage_a; `idle_released_this_session` incremented; next D1 tick emits
  `number.set_value` restore. Under bug (idle-release branch removed): garage_a stays
  claimed indefinitely; no `switch.turn_off`; `idle_released_this_session` stays 0.
  Different observation.
* **T-IDLE-2** (Rev-10 add) `test_idle_release_for_empty_bay`. Fixture: garage_b added
  to `_excess_solar_active` by the CLAIM path (switch-on with no vehicle plugged);
  `charging=False, power=0` for all ticks. Tick 1: `_idle_streak_ticks[garage_b]=1`.
  MIN_ON_S floor (5 min) passes at tick 1 (5 min at 5-min cadence). At tick 4:
  streak=4 ≥ IDLE_RELEASE_TICKS; session age 20 min ≥ 5 min. Release fires. Assert:
  same shape as T-IDLE-1 for the empty-bay case. Under bug: garage_b stays claimed
  indefinitely.
* **T-IDLE-3 (discriminating negative — Rev-10 add)**
  `test_mid_charge_pause_not_released`. Fixture: garage_a in `_excess_solar_active`,
  `charging=True, power=5000` ticks 1-4 (draws through MIN_ON_S floor); pauses
  `charging=False, power=0` ticks 5-6 (10 min pause — simulates thermal throttle);
  resumes `charging=True, power=5000` ticks 7+. Assert: at tick 6,
  `_idle_streak_ticks[garage_a]=2` (below IDLE_RELEASE_TICKS=4); at tick 7, streak
  resets to 0 on resume; release NEVER fires; garage_a remains in
  `_excess_solar_active` throughout. Under bug (streak doesn't reset on resume): tick 7
  streak stays at 2, tick 8 increments to 3, tick 9 to 4 → false release. Different
  observation from correct code.
* **T-IDLE-4 (Rev-10 add) restart / session-boundary cleanup**
  `test_idle_streak_clears_at_session_end`: idle-release fires on garage_a; assert
  `_idle_streak_ticks[garage_a]` cleared. Then simulate a NEW session on garage_a next
  day; assert streak starts at 0, not from where the prior session left off.

* **Live:** on first cloudy transition day, hysteresis release survives single-SOC-
  point dips of < 180 s. **Rev-10:** if a car finishes charging and enters idle,
  observe idle-release fires ~20 min after last draw (attributes `idle_streak_ticks`
  and `idle_released_this_session` on the D1 sensor).

**Non-substitutability:** D1 is the mechanism that makes economics work; D2's
hysteresis stops flap; D2's idle-release provides the missing exit for safe-parking
(Rev-10 close).

---

## 4. Non-goals (explicit)

* NOT starting/stopping charges on any grounds. NOT coordinating with DP. NOT changing
  the excess-solar TRIGGER at `energy_pool.py:1574-1579`. NOT changing the EC 5-minute
  tick. NOT extending `_maybe_schedule_write_verify`. NOT wiring HVAC coupling. NOT
  demoting `evse_battery_hold`. NOT changing `ev_battery_drain_soc` live value (still
  80). NOT changing R1 / R3 sources (see `PLANNING_dp_drain_target_mis_sourcing.md`).
  NOT touching `sensor.mainw_vue_balance_power_minute_average`. NOT using
  `balanced_net_power_consumption`, SPAN, or
  `sensor.ura_energy_coordinator_envoy_status`. NOT wiring L1 chargers. NOT introducing
  a new `persistence_kind`. NOT auto-remediating offline Garage A / SPAN observability
  gap. NOT feeding `EVSE_ESTIMATED_POWER_W` into D1's control law (including via
  v4.2.19 `power_source="switch_status"` fallback). NOT introducing priority ordering.
  NOT adding `_paused_by_dp` to `_stronger_peer_holds`. NOT re-solving compound-load in
  D1. NOT building a per-EVSE "no-interference latch". NOT using
  `current_charging_load_w()` for the add-back.
* NOT modifying `determine_battery_drain_actions:1776-1959`. Byte-identical: zero edits,
  zero counter bumps, zero comments, zero re-imports. Solar-follow YIELDS via INV-SF-7.
* NOT modifying `solar_replenishing` (`energy.py:5823`, `energy_pool.py:2000`).
* NOT shortening D1's 60 s tick or subscribing to owner-set mutation events to catch
  sub-tick drain-protection flap.
* NOT modifying the excess-solar CLAIM path at `energy_pool.py:1650-1656`. Rev-8 fixes
  the empty-bay defect in the CONSUMER (D1) only; producer byte-identical.
* **NOT reading car SoC directly (Rev-10).** The Emporia is a relay plus power meter;
  URA has no direct visibility to a car's SoC or "target reached" state. The
  sustained-`charging == False` proxy is the observable INV-RELEASE-2 uses; it correctly
  conflates finished-car, empty-bay, and pilot-refusal into "nothing to do here" for
  solar-allocation purposes. A future cycle wanting granular per-case handling would
  need to add J1772 SoC decoding or an alternative EVSE integration.

---

## 5. Known couplings

1. DP gate 6 (`energy_drain_precedence.py:652`) — L1-only crossover at 12.5 A.
2. DP gate 8 charge_hours blows up at low amps.
3. `_dp_house_load_kw` biased other way — non-monotone in amps.
4. `EVSE_ESTIMATED_POWER_W = 7600` never in D1's control law (double-closed via
   `power_source` gate).
5. `evse_battery_hold` engages at 6 A — amp-independent.
6. Emergent actuation precedence.
7. INV-YIELD-1/2 (audit §6.4). D1 downstream of CLAIM; INV-SF-7 strictly stricter.

8. **Compound-load protection — `_paused_by_grid_cap` (v4.0.18) + D4 mutex (v4.5.0)
   TOGETHER (Rev-9 corrected attribution; Rev-10 breaker-caveat retraction).**
   Historical git-log verified:
   - `_paused_by_grid_cap` introduced in **v4.0.18** (commit `1a499f0b8`, "Fan
     manual-off cooldown + EV grid import cap"). Pause site at
     `energy_pool.py:1723-1735`: `if net_power_kw > grid_cap_kw: switch.turn_off +
     _paused_by_grid_cap.add`. **REACTIVE** grid-import ceiling.
   - `_paused_by_arbitrage` introduced in **v4.5.0** (commit `f3deabc84`, the
     battery-strategy redesign that became D4). Live compound-load mutex at
     `energy.py:6240-6263` (`charge_from_grid` chokepoint, phase-label-independent) +
     `:6290-6328` (hardware read OR fail-closed latch) + `:6341-6365` (EV pauses
     dispatched before battery actions). **PREVENTIVE** — never creates the
     combination.

   **The hazard is SUSTAINED OVERLOAD, not instantaneous trip (Rev-10 correction).**
   Sustained ~134 A on this service is a thermal-element trip hazard AND a conductor-
   heating / insulation-degradation hazard. Both act cumulatively over minutes to tens
   of minutes — precisely the timescale a 5-minute control loop can act on. Breakers
   trip TWO ways: magnetic/instantaneous for short circuits (milliseconds — outside any
   control-loop's reach and outside this hazard class), and **thermal for sustained
   overcurrent** (minutes to tens of minutes — matched to this cadence). Conductor
   heating and insulation degradation are likewise cumulative. **Both `_paused_by_grid_cap`
   (reactive, bounds sustained import) and D4 (preventive, avoids creating the
   combination) are appropriately matched to the real hazard.** The "134 A main breaker"
   framing points at the correct thermal-element hazard, not at an instantaneous trip.

   Overlapping, not proven redundant. Different mechanisms (reactive vs preventive).
   Consequence for D1's scope: compound-load import IS BOUNDED by grid_cap AND D4
   together. D1 does NOT re-solve compound-load safety. INV-SF-7 subordinates D1 to both
   via `iter_peer_holds()` (both are strong peers).

9. `_pause_dispatch_ts` / `_observed_off_since_pause` (`energy_pool.py:275-278`) — repo
   does NOT trust "peer-held ⇒ not drawing". D1's ELIGIBLE-scoped add-back handles the
   physical draw by classifying it as house load.
10. `_paused_by_load_shed` is `persistence_kind="none"` — a load-shed-deferred EVSE
    loses hold on restart; first post-restart tick fires the restore to captured
    original ≤48 A. Benign.
11. **`solar_replenishing` already exists on the drain-protection RESUME side** — LEAVE
    ALONE. D1 does not feed or read this signal.
12. **`_paused_by_battery_drain` observed by D1 through set-membership sampling only.**
    D1 does not observe the pause dispatch. Coupling is READ-ONLY set observation on
    D1's own tick cadence.
13. **Empty-bay ELIGIBLE-not-DRAWING (Rev-8 close, Rev-10 exit added).**
    `_excess_solar_active.add` (`energy_pool.py:1656`) happens on switch-on without a
    plug check; an empty bay is ELIGIBLE but not DRAWING. D1's DRAWING subset is what
    the allocation denominator uses; safe-parking MIN command caps the plug-in
    transient. **Rev-10 adds INV-RELEASE-2: the empty bay is released after
    `SOLAR_FOLLOW_IDLE_RELEASE_TICKS` (20 min) of sustained `charging == False`.**

### 5a. Open question for a future supersession audit

**`grid_cap` vs `_paused_by_arbitrage` overlap — did v4.5.0 D4 duplicate a hazard
v4.0.18 already covered, and if so which is the better mechanism?**

- **NOT a delete candidate** — per CLAUDE.md's post-ship supersession rule.
- Framing: grid_cap is REACTIVE, D4 mutex is PREVENTIVE. Different mechanisms,
  overlapping purpose against the SUSTAINED-OVERLOAD hazard. The audit answers: which
  bounds the hazard better under what conditions, and does keeping both create a
  coordination burden.
- Trigger: a fired incident where the two disagree, OR a cycle proposing to touch either.
- Not this cycle's work; read-only audit; separate cycle.

---

## 6. Docs drift to fix in-cycle

* `energy_pool.py:_stronger_peer_holds` docstring says "the five", loop returns six.
  Add `blind_window`.

---

## 7. Test plan summary

Behavioural, MUTATION-VERIFIED. `PYTHONDONTWRITEBYTECODE=1` + clear `__pycache__`.

D1 tests: unchanged Rev-8 list (INV-SF-1..7, T-STALE-1, T-ITER-1, T-PEER-1..6,
T-DRAIN-1..4, T-DRAW-1..3).

D2 tests: `test_release_streak_gated`; `test_release_min_on_time`;
`test_release_streak_persists_min_on_time_across_restart`;
**T-IDLE-1** `test_idle_release_after_finished_car` (Rev-10);
**T-IDLE-2** `test_idle_release_for_empty_bay` (Rev-10);
**T-IDLE-3** `test_mid_charge_pause_not_released` (Rev-10 — discriminating negative);
**T-IDLE-4** `test_idle_streak_clears_at_session_end` (Rev-10).

---

## 8. Review plan — Tier 3, four framing-disjoint passes

* **A — local correctness.** ELIGIBLE-scoped writes + DRAWING-scoped allocation +
  DRAWING-scoped add-back; step 2a/2b/2c convention; snapshot iteration; STEP 0
  edge-detector rules; `max(1, N_drawing)` divide-by-zero guard; safe-parking routing;
  **idle-streak arithmetic (increments on `charging==False`, resets on True); idle-
  release AND-clauses (streak ≥ IDLE_RELEASE_TICKS AND session age ≥ MIN_ON_S);
  session-end cleanup clears `_idle_streak_ticks` alongside `_conditions_met_false_streak_ticks`.**
* **B — integration / state-machine + byte-identical no-op.** Class shape; SLF001;
  restart paths; Q5 must-start-release corner. `determine_battery_drain_actions` and
  `solar_replenishing` path BOTH byte-identical. Excess-solar CLAIM path byte-identical.
  **Rev-10: idle-release fires through the same release-path shape as INV-RELEASE-1
  (switch.turn_off + `_excess_solar_active.discard`); no new dispatch site introduced.
  Persistence: `_idle_streak_ticks` is RAM-only (fresh at session start); no persistence
  hook needed because a restart mid-session correctly starts a fresh streak — worst-case
  loss is a partial streak, which is the safe direction (delays release, does not fire
  a false release).**
* **C — REAL per-site source mutation.**
  - C17/b/c/d/e/f, C18, C19/b, C20/b/c as prior revisions.
  - **C21 (Rev-10 add):** remove the idle-release condition entirely (delete the
    `if _idle_streak_ticks[evse_id] >= IDLE_RELEASE_TICKS and session_age >= MIN_ON_S`
    block from D2) → **T-IDLE-1 and T-IDLE-2 must fail** (finished car and empty bay
    stay claimed indefinitely; `idle_released_this_session` stays 0).
  - **C21b (Rev-10 add):** remove the `charging is True` streak-reset (keep the
    increment but never reset) → **T-IDLE-3 must fail** (mid-charge pause accumulates
    and false-releases at tick 4 of the pause; discriminating negative test triggers).
  - **C21c (Rev-10 add):** replace `session_age >= MIN_ON_S` in the idle-release
    condition with `True` (skip the floor) → a fresh-commanded bay that has not yet
    drawn is released on tick 1 of the session; add a targeted test
    `test_idle_release_respects_min_on_time_startup_floor` (fixture: newly commanded
    bay, `charging=False` at tick 1; assert no release before tick 1 hits MIN_ON_S)
    which C21c breaks.
* **D — adversarial completeness / diff-blind.** Re-enumerate all `_excess_solar_active`
  discard sites; readers from OUTSIDE `SolarFollowController`; peer-hold mutation sites;
  every `number.set_value` writer; every code path that adds to `_excess_solar_active`.
  **Rev-10: enumerate every place `_idle_streak_ticks` is mutated (init at session
  entry; increment/reset in D2 tick; clear at session end via each release path) and
  confirm no discharge path is missing per `feedback_suppression_needs_discharge`.**
  Legal-config combinatorial. Every leak → concrete legal-config repro.

**Orchestrator pre-deploy verification:** re-grep the six peer-hold owner sets +
`_paused_by_dp`; run mutation drills C17..C20c + C18 + C19..C19b + **C21..C21c** (Rev-10);
zero-call-sites confirmation against `current_charging_load_w()` and bare
`EVSE_ESTIMATED_POWER_W` inside `SolarFollowController`; grep-check
`determine_battery_drain_actions:1776-1959` ZERO diff; grep-check
`_drain_trips_during_follow` increment site occurs exactly ONCE inside
`SolarFollowController.STEP 0`, ZERO under `energy_pool.py:1776-1959`; grep-check
`solar_replenishing` ZERO diff; grep-check excess-solar CLAIM path
`energy_pool.py:1650-1656` ZERO diff; grep-check D1's step 8 uses `max(1, N_drawing)`;
grep-check D1's step 9b has `else: A_target = SOLAR_FOLLOW_MIN_AMPS`; **grep-check
`_idle_streak_ticks` is initialized, incremented, reset, and cleared at exactly the four
sites specified in §3.D2 (session entry init; D2 tick increment/reset; each release path
clear)**; diff-check against §11 register.
**Operator checkpoint BEFORE deploy.**

---

## 9. REUSE vs NEW

(Rev-8/9 rows preserved; Rev-10 additions in **bold**.)

| Item | Verdict | Cite |
|---|---|---|
| `PoolOptimizer` shape (save/restore + unavailable-keep-state) | REUSE (shape only) | `energy_pool.py:58-160` |
| `_execute_service_action` | REUSE | — |
| `_excess_solar_active` membership | REUSE | `energy_pool.py:202` |
| Per-EVSE inline persistence for `_original_amps` | REUSE | `energy.py:1839`, `:1365-1366` |
| `_get_evse_state` | REUSE | `energy_pool.py:650` |
| `_get_evse_state(...).power_source` field discrimination | REUSE | `energy_pool.py:700-706` |
| `_get_evse_state(...).charging` as DRAWING predicate AND idle-streak observable | REUSE | `energy_pool.py:691` |
| `_ev_battery_drain_soc` at R1/R3 (DP fix's concern) | REUSE unchanged | — |
| TOU peak-clear | REUSE | `energy_pool.py:1354-1374` |
| `_stronger_peer_holds` + inline `_paused_by_dp` (6 owners) | REUSE | `energy_pool.py:383-412`, `:1621-1631` |
| Cross-class SLF001 convention | REUSE | `energy.py:4141`, `:4517`, `:4929`, `:5031` |
| Anti-flap duration threshold (D2 hysteresis + idle-release both shape-match) | REUSE | `PLANNING_v4.7.x_APPLIANCE_SCHEDULER.md:41` |
| Live compound-load mutex (D4, v4.5.0) | REUSE unchanged | `energy.py:6240-6263` + `:6290-6328` + `:6341-6365` |
| Grid-import cap (v4.0.18, predates D4) | REUSE unchanged | `energy_pool.py:1723-1735`. Overlapping with D4 for sustained-overload coverage; see §5 item 8 and §5a. |
| `_prune_removed_evses` participation for `_original_amps` | REUSE mechanism | `energy_pool_owners.py:345+` |
| `determine_battery_drain_actions` (byte-identical) | REUSE unchanged | `energy_pool.py:1776-1959` |
| `solar_replenishing` on RESUME side (unchanged) | REUSE unchanged | `energy.py:5823`, `energy_pool.py:2000` |
| `_paused_by_battery_drain` set-membership as observable | REUSE (READ-ONLY, D1 tick) | — |
| Excess-solar CLAIM path (byte-identical) | REUSE unchanged | `energy_pool.py:1650-1656` |
| **D2 release-path shape (`switch.turn_off` + `_excess_solar_active.discard`) reused for INV-RELEASE-2** | REUSE (Rev-10) | Same site as hysteresis release at `energy_pool.py:1685-1699`. Idle-release joins as a second trigger with the same exit path; no new dispatch site. |
| `SolarFollowController` class | NEW | — |
| Session-scoped 60 s timer (always-on, empty-set fast path) | NEW | — |
| ELIGIBLE-scoped surplus add-back with `power_source` gate | NEW (inline sum) | — |
| DRAWING subset derivation inside D1 | NEW (step 5) | — |
| `max(1, N_drawing)` divide-by-zero guard | NEW (step 6) | — |
| Safe-parking MIN command for ELIGIBLE \ DRAWING | NEW (step 9b) | — |
| Release-gate streak + min-on-time (hysteresis) | NEW | — |
| Solcast next-hour stop | NEW | — |
| `SOLAR_FOLLOW_*` constants + Numbers | NEW | — |
| `drain_trips_during_follow` counter (D1 STEP 0 edge-detector) | NEW | — |
| `drawing_evses` + `safe_parked_evses` status attributes | NEW | — |
| Bounded in-controller readback verify | NEW | — |
| **`_idle_streak_ticks: dict[str, int]` on `EVChargerController` (Rev-10)** | NEW | Rev-10 |
| **`SOLAR_FOLLOW_IDLE_RELEASE_TICKS` constant (rung 1, 4)** | NEW | Rev-10 |
| **INV-RELEASE-2 idle-release branch in D2** | NEW | Rev-10 |
| **`idle_streak_ticks` + `idle_released_this_session` sensor attributes** | NEW | Rev-10 |

---

## 10. Design pushback recorded

### PB-1 — drain-protection `_excess_solar_active` skip — REJECTED (operator-ruled)

(Full evidence trail unchanged from Rev-6: INV-SF-7 contradiction; skew probe 6.7×
degradation in fast-solar regime; cost asymmetry; retracted fill-priority analogy;
retracted "runs after solar = defect" framing.)

Replacement: `drain_trips_during_follow` telemetry counter, wired via D1's STEP 0
edge-detector INSIDE `SolarFollowController` (Rev-7 correction: NOT inside the safety
function).

### PB-2 — sub-tick clock seam — WITHDRAWN.

### Signal design (either-or, no agreement gate) — RECORDED.

### **Rev-10 retraction: breaker-timescale caveat on §5 item 8.**

An earlier revision wrote that at a 5-minute cadence neither `grid_cap` nor D4 is
convincing for "breaker protection" because "a breaker trips in seconds," and that the
"134 A framing oversells both." That reasoning is retracted on operator correction. The
hazard is **sustained overload** (thermal-element trip + conductor heating + insulation
degradation), which is cumulative over minutes to tens of minutes — matched to a 5-minute
control cadence. Breakers trip two ways: magnetic/instantaneous (short circuits,
milliseconds, outside any control-loop's reach) and thermal (sustained overcurrent,
minutes). The retracted caveat conflated the two trip modes and then discounted the
machinery for not solving a problem it was never aimed at. §5 item 8 now states the
sustained-overload framing correctly.

---

## 11. Closed concerns — must stay closed

(Rev-8/9 rows preserved; Rev-10 add.)

| Concern | Round originally closed | The one-line invariant that keeps it shut |
|---|---|---|
| `EVSE_ESTIMATED_POWER_W` reaches D1's control law | Combined-plan Rev-2 (A-MED-1); re-opened Rev-3 / Rev-4; re-closed Rev-5 | D1's surplus add-back sums ONLY EVSEs whose `_get_evse_state.power_source == "sensor"`. Future-revision grep-check for `EVSE_ESTIMATED_POWER_W`, `current_charging_load_w`, `switch_status`, `state.get("charging")` in D1's diff. |
| Fleet-wide surplus add-back over-drawing | Combined-plan Rev-4 (SF7-B1) | `S_eligible` sums add-back ONLY over DRAWING (⊆ ELIGIBLE); §4 non-goal against `current_charging_load_w()`. |
| New `persistence_kind` introduced | Combined-plan Rev-2 (A-HIGH-2) | Existing inline column OR existing KV shape. |
| `SOLAR_FOLLOW_HEADROOM_KW` orphan | Combined-plan Rev-2 (B-6) | INV-SF-4 has no headroom term. |
| Solar-follow acts on a peer-held EVSE | Combined-plan Rev-3 | INV-SF-7 + ELIGIBLE step 5 + guard step 2a. C17 + C17b. |
| Restore-pass mutation-during-iteration crash | Combined-plan Rev-5 (N5) | `list(self._original_amps)` snapshot. T-ITER-1. |
| `SolarFollowController` shape ambiguous | Combined-plan Rev-5 (BLOCKING-2) | `__init__(self, hass, ev: EVChargerController, ...)`; SLF001 convention. |
| Hollow test anchor via fixture that doesn't perturb the tested branch | Combined-plan Rev-3 (SF7-H1); re-closed Rev-5 (BLOCKING-3) | Peer-hold test fixtures MUST move surplus beyond DEADBAND and outside the up-gate. |
| Solar-follow suppresses a strong-peer safety gate OR reaches into its function body for any purpose, including telemetry | Combined-plan Rev-6 (PB-1 REJECTED); strengthened Rev-7 | INV-SF-7 has NO exceptions. `determine_battery_drain_actions:1776-1959` BYTE-IDENTICAL post-cycle. Telemetry from a safety gate is derived externally by observation (D1's STEP 0), never from inside the safety function. C18 + C19 + C19b. |
| An idle or unplugged bay dilutes the allocation denominator | Combined-plan Rev-8 (operator-flagged) | `N_denom = max(1, N_drawing)`, NOT `len(ELIGIBLE)`. DRAWING ⊆ ELIGIBLE. Non-DRAWING ELIGIBLE bays receive MIN safe-parking. C20/b/c. CLAIM path byte-identical. Rule: when a producer emits a set with mixed semantic content, the consumer distinguishes by attribute rather than filtering the producer. |
| **Safe-parking, or any hold state, must carry an exit condition** | **Rev-10 (operator-flagged)** | **INV-RELEASE-2. A claimed EVSE that has not been DRAWING for `SOLAR_FOLLOW_IDLE_RELEASE_TICKS` (4 = 20 min) AND session age ≥ `MIN_ON_S` (5 min) is released via the D2 release path. Applies uniformly to finished-car, empty-bay, and pilot-refusal cases — URA cannot observe "target reached" directly (Emporia is relay + power meter, no SoC), so sustained-`charging == False` is the correct proxy. Mid-charge pause resets the streak on resume. C21/b/c mutation drills. Rule generalizes: any hold state introduced in this or a future cycle MUST specify (a) discharge paths per `feedback_suppression_needs_discharge`, AND (b) at least one exit trigger independent of the conditions that established the hold — a hold that persists indefinitely while its establishing conditions hold is a suppression without discharge.** |

(DP-related closed-concerns rows live in `PLANNING_dp_drain_target_mis_sourcing.md`.)

---

## 12. Change log

Combined-plan Rev-1..Rev-8 change log preserved in git history of the deleted
`PLANNING_evse_solar_follow_and_dp_drain_target.md`. Summary of what shipped in the split
and subsequent narrow corrections:

- **Rev-9 (split + D4 attribution correction):**
  - Combined plan split into DP-fix + solar-follow docs (operator ruling — DP fix
    stable, solar-follow moving).
  - Runtime relationship + sequencing note (top of doc): ship DP fix first, preferably.
  - §5 known-couplings item 8 rewritten: D4 (v4.5.0) does NOT stand alone; `_paused_by_grid_cap`
    (v4.0.18) predates it and covers the same hazard reactively. Both live.
  - §5a open question added: `grid_cap` vs `_paused_by_arbitrage` overlap; separate
    read-only audit cycle. NOT a delete candidate.
  - §9 REUSE table gains explicit row for `_paused_by_grid_cap`.

- **Rev-10 (breaker-caveat retraction + idle-release for safe-parking):**

| Finding | Severity | Change |
|---|---|---|
| **Breaker-timescale caveat on §5 item 8 was wrong** — an earlier revision said "trips in seconds" and "oversells both," which conflated magnetic/instantaneous trips (milliseconds, outside any control-loop's reach) with thermal/sustained-overcurrent trips (minutes, matched to 5-min cadence). Operator correction: hazard is SUSTAINED OVERLOAD (thermal-element trip + conductor heating + insulation degradation), cumulative over minutes. | Correction | §5 item 8 rewritten with sustained-overload framing; §10 records the retraction with thermal-vs-magnetic reason so the caveat is not re-derived. Honest history (v4.0.18 predates v4.5.0; overlapping not proven redundant) and §5a open question preserved. |
| **Safe-parking has no exit — a bay that is ELIGIBLE-but-not-DRAWING gets a 6 A command every tick and stays claimed indefinitely** (finished car OR empty bay both sit in that state forever while `conditions_met` holds). Rev-8 introduced safe-parking as a bounded transient and never gave it an exit — a suppression with no discharge. | BLOCKING (operator-flagged) | New INV-RELEASE-2 (idle exit, INDEPENDENT of INV-RELEASE-1). New `SOLAR_FOLLOW_IDLE_RELEASE_TICKS` (rung 1, 4 = 20 min at 5-min cadence). New `_idle_streak_ticks: dict[str, int]` on `EVChargerController`. D2 tick increments on `charging==False`, resets on `charging==True`. Release fires when streak ≥ IDLE_RELEASE_TICKS AND session age ≥ MIN_ON_S; same release path as INV-RELEASE-1 (no new dispatch). Startup interaction: chose Option B (MIN_ON_S covers ramp) over Option A (`_has_drawn_this_session` flag) — simpler, covers empty-bay + finished-car uniformly, 5-min MIN_ON_S is 10× typical J1772 pilot-handshake + car-ramp time. Four new tests T-IDLE-1..4 (finished car; empty bay; discriminating negative for mid-charge pause; session-end cleanup). Three new mutation drills C21/b/c. Two new sensor attributes `idle_streak_ticks` + `idle_released_this_session`. New §4 non-goal: NOT reading car SoC directly (Emporia is relay + power meter; sustained-`charging==False` is the correct conflation). §11 closed-concerns row added with the generalized rule: any hold state MUST specify discharge paths AND at least one exit trigger independent of the establishing conditions. |

---

## 13. Cycle-close checklist

* [ ] DP fix cycle (`PLANNING_dp_drain_target_mis_sourcing.md`) shipped and validated.
* [ ] Targeted re-review of Rev-10 idle-release + breaker-caveat retraction.
* [ ] Build in one branch off `develop`.
* [ ] Suite green + baseline-diff clean.
* [ ] Four framing-disjoint reviews A/B/C/D returned; CRITICAL/HIGH fixed.
* [ ] Orchestrator pre-deploy grep set as §8 above (includes Rev-10 C21/b/c drills and
      `_idle_streak_ticks` lifecycle grep-check).
* [ ] Operator checkpoint before deploy.
* [ ] `README_v<version>.md` with prospective Live criteria.
* [ ] Deploy via `./scripts/deploy.sh`.
* [ ] Live validation: sunny-day D1 attributes including `drawing_evses`,
      `safe_parked_evses`, `s_eligible_kw`, `stale_ticks`, `excluded_switch_status_evses`,
      `drain_trips_during_follow`, **`idle_streak_ticks`, `idle_released_this_session`**;
      one-bay-active case; startup transition; release-edge restore; INV-SF-7 if
      arbitrage overlap; BLOCKING-1 confirmation if Emporia cloud blip; drain-trip
      counter per-event; plug-in transient bounded at 1.44 kW/bay for ≤60 s lag;
      **Rev-10: idle-release fires ~20 min after last DRAWING event when a car finishes
      or a bay was never plugged in (visible via `idle_released_this_session`
      incrementing and next-tick restore to `_original_amps`).**
* [ ] README updated with observed `Validated <date>` table.
* [ ] Kanban card `EVSE-SOLAR-FOLLOW-AMPS-1` moved to shipped_organic.
* [ ] Post-ship supersession + consumer-gap audit per CLAUDE.md rule — INCLUDES surfacing
      §5a open question (grid_cap vs D4 overlap) as a candidate for the next audit cycle.
