# PLANNING — EVSE solar-following amp modulation

**Cycle name:** `evse-solar-follow-amps`
**Tier:** **Tier 3**
**Threads:** `energy`
**Cards:** `EVSE-SOLAR-FOLLOW-AMPS-1`
**Design source:** the card body and `docs/planning/AUDIT_excess_solar_and_evse_prior_art.md`.
**Probes:** `scripts/probes/delta_probe.py`, `scripts/probes/skew_probe.py`.

**Provenance.** Extracted from combined plan (Rev-1..Rev-8), split at Rev-9 (D4
attribution corrected), Rev-10 (safe-parking exit), Rev-11 (Emporia status sensor +
cessation ledger + parked design questions), Rev-12 (asymmetric SOC-band framing +
two grid-import protections + INV-SF-5 step-load rationale + nameplate sanity +
measured institutional context), Rev-13 (withdrawal reasoning recorded), **Rev-14
(withdrawal fully applied — all fleet circuit-capacity machinery removed from the
doc body; residue lives only in §5a reasoning and §13 change log).** DP fix lives
in `PLANNING_dp_drain_target_mis_sourcing.md`.

**Runtime relationship to DP fix.** Read-only observation of `_paused_by_dp` for
INV-SF-7 ELIGIBLE gate. No code dependency.

**Sequencing preference: SHIP DP FIRST.** Preferred, not merely acceptable.

---

## 0. Tier-3 elevation and framing

NEW writer on live cloud actuator with fleet allocation and peer-hold subordination.
Multiple "silent success" failure modes across revisions (see §12 register).

Tier 3.

---

## 1. Falsifiable invariants

### INV-SF-1 (non-perturbation)
Emits no `switch.turn_on`/`switch.turn_off`. Writes only `number.set_value` to a
current-limit entity, only for an EVSE in `_excess_solar_active`.

### INV-SF-2 (writes only inside sessions)
Both sets empty → zero writes.

### INV-SF-3 (restore is load-bearing, restart-safe)
After removal from `_excess_solar_active` by any code path, current-limit restored
to saved `_original_amps` within one restore tick — subject to INV-SF-7.

### INV-SF-4 (draw bounded by measured surplus — DRAWING vs ELIGIBLE)
`ELIGIBLE = {evse_id ∈ _excess_solar_active where NOT _stronger_peer_holds(evse_id)
AND evse_id ∉ _paused_by_dp AND _get_evse_state(evse_id).power_source == "sensor"
AND _read_status(evse_id) != "Disconnected"}`.
`DRAWING = {evse_id ∈ ELIGIBLE where _is_drawing(evse_id) is True}` where
`_is_drawing` prefers Emporia status (`Charging` → True; `Connected`/`Disconnected`
→ False; `unavailable`/None → power-based fallback via
`_get_evse_state(evse_id).charging`).
`S_eligible = -grid_W + Σ_{DRAWING} evse_power_w`.

Surplus-side bound: `Σ_{i ∈ DRAWING} A_i · 240 · PHASES ≤ max(S_eligible,
N_drawing · MIN · 240)`.
Safe-parking side: `Σ_{i ∈ ELIGIBLE \ DRAWING} A_i · 240 · PHASES ≤
(N_eligible - N_drawing) · MIN · 240`.

Fabricated-power (`power_source == "switch_status"`) EVSEs are EXCLUDED from
ELIGIBLE entirely; they route to D1.3 STALE (no writes at MAX_TICKS).

### INV-SF-5 (asymmetric reaction to a lagging signal)
Down-step uncapped, one tick. Up-step gated by `SOLAR_FOLLOW_UP_MIN_TICKS`, capped
at `SOLAR_FOLLOW_UP_STEP_A` per tick per EVSE. PRIMARY is a 60 s AVERAGE; the
up-gate is what contains the ramp mismatch. INV-SF-4 is bookkeeping; INV-SF-5 is
the physical lag containment.

**Measured rationale for asymmetry (beyond sensor-lag):** solar-hour household
loads — cooking, baking, laundry, dishwashing — are multi-kilowatt **STEP changes**,
not ramps. They consume export surplus. A symmetric or fast-up controller would
chase each step (surplus drops → chase down), then reverse when the step ends
(surplus returns → chase up), creating a synthetic oscillation on top of the
physical one. The asymmetric law (down fast, up gated) means D1 tracks the fall of
surplus immediately but requires a sustained rise before ramping back — matching
the natural profile of step-load consumers. Concrete house-specific reason for the
asymmetry beyond the sensor-lag defence.

### INV-SF-6 (fleet allocation)
`N_denom = max(1, N_drawing)`.
`A_total_target = floor(S_eligible / (240 · PHASES))`.
`A_per_drawing = clamp(A_total_target // N_denom, MIN, MAX)`.

Command routing: DRAWING bays receive `A_per_drawing`; ELIGIBLE \ DRAWING bays
receive `SOLAR_FOLLOW_MIN_AMPS` safe-parking. Degenerate cases preserved from
Rev-8.

### INV-SF-7 (stronger-peer subordination — NO EXCEPTIONS)
While `_stronger_peer_holds(evse_id) is True` OR `evse_id ∈ _paused_by_dp`, no
write and no capture. Applies to BOTH step 2a (restore) AND step 5 (modulation).
`_paused_by_dp` INLINE per two-site convention. No exceptions for individual peer
owners. `_paused_by_battery_drain` IS in `iter_peer_holds()`.

### INV-RELEASE-1 (D2 hysteresis path)
Release fires only when `not conditions_met OR solcast<floor` AND streak ≥
MIN_TICKS AND session age ≥ MIN_ON_S.

### INV-RELEASE-2 (idle exit for safe-parking — Rev-11 status taxonomy)
Under any excess-solar-active EVSE with session age ≥ `SOLAR_RELEASE_MIN_ON_S`,
release fires when EITHER:
- **Disconnected path:** `_disconnected_streak_ticks[evse_id] ≥
  SOLAR_FOLLOW_DISCONNECTED_RELEASE_TICKS` (=2, 10 min at D2's 5-min cadence).
- **Idle path:** `_idle_streak_ticks[evse_id] ≥ SOLAR_FOLLOW_IDLE_RELEASE_TICKS`
  (=4, 20 min at D2's 5-min cadence).
- **`unavailable` status:** neither counter advances.
- **Peer-held (Rev-14 fix):** while `_stronger_peer_holds(evse_id)` OR
  `evse_id ∈ _paused_by_dp`, **neither counter advances, and both are RESET to 0 on the
  first tick of the hold.** Both counters are assertions about the CAR; while a stronger
  owner has opened the switch, the charger's not-drawing state says nothing about the car.

Independent of INV-RELEASE-1. See §D2 for status-taxonomy state machine.

---

## 2. Institutional context verified

Paths under `custom_components/universal_room_automation/domain_coordinators/`:

* `docs/planning/AUDIT_excess_solar_and_evse_prior_art.md` (all sections).
* `energy_pool.py` — `PoolOptimizer:58-160` (template shape only);
  `EVChargerController.__init__:186-317`;
  `determine_excess_solar_actions:1318-1701` (release `:1685-1699` = D2 hysteresis
  half); `determine_battery_drain_actions:1776-1959` — BYTE-IDENTICAL post-cycle;
  `_soc_envelope_admits_dp_transition:619-648`;
  `_stronger_peer_holds:383-412` (docstring "the five" stale — loop returns six);
  `_paused_by_dp` inline claim `:1621-1631`;
  fill-priority `_excess_solar_active` skip prior art `:2214-2219` (NOT template
  for D2); excess-solar CLAIM path at `:1650-1656` (byte-identical post-cycle);
  `_get_evse_state:650` with v4.2.19 fallback `:690-697`
  (`power_source="switch_status"`, `power=EVSE_ESTIMATED_POWER_W=7600 W`);
  `charging = power > EVSE_CHARGING_POWER_THRESHOLD` at `:691`;
  `current_charging_load_w:2300-2312` (NOT USED); `_pause_dispatch_ts` /
  `_observed_off_since_pause` `:275-278`; `_paused_by_grid_cap` pause site at
  `:1723-1735` (the v4.0.18 EV cap).
* `energy_pool_owners.py` — `iter_peer_holds()` = 6 owners INCLUDING
  `battery_drain`; `persistence_kind` ∈ {`per_evse_bool`, `list`, `none`};
  `_paused_by_load_shed` `persistence_kind="none"`.
* `energy.py` — `self._ev` at `:293`; SLF001 convention at `:4141`, `:4517`,
  `:4929`, `:5031`; `solar_replenishing` at `:5823`; live compound-load mutex at
  `:6240-6263` + `:6290-6328` + `:6341-6365`; load-shed re-claim `:7259-7282`.
* `energy_battery.py` — `solar_production_w:1586-1612`; `net_power_w:1614-1623`.
* `energy_const.py` — verified:
  - `EVSE_ESTIMATED_POWER_W = 7600` (`:827`).
  - `EVSE_CHARGING_POWER_THRESHOLD = 100` (`:826`).
  - `DEFAULT_EXCESS_SOLAR_SOC_THRESHOLD = 95` (`:824`);
    `CONF_ENERGY_EXCESS_SOLAR_SOC = "energy_excess_solar_soc"` (`:829`). Label
    "Resume EV at Battery SOC" per `translations/en.json:901`.
  - `DEFAULT_EXCESS_SOLAR_KWH_THRESHOLD = 5.0` (`:825`);
    `CONF_ENERGY_EXCESS_SOLAR_KWH` (`:830`). Label "Excess Solar Forecast
    Threshold".
  - `CONF_ENERGY_FILL_PRIORITY_SOC = "energy_fill_priority_soc"`
    (number.py:1576). Label "Pause EV Until Battery SOC".
  - `DEFAULT_GRID_IMPORT_CAP_KW = 8.0` (`:893`);
    `CONF_ENERGY_GRID_IMPORT_CAP_ENABLED` (`:895`), `CONF_ENERGY_GRID_IMPORT_CAP_KW`
    (`:896`). Live: **enabled, 20 kW**. The EV grid-import cap.
  - `DEFAULT_ARBITRAGE_GRID_IMPORT_GUARD_KW = 12.0` (`:787`);
    `CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED` (`:801`);
    `CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW` (`:788`). Live: **disabled**.
    Different mechanism from the EV cap.
  - `DEFAULT_ENERGY_SOLAR_NAMEPLATE_W = 19400` (`:854`);
    `CONF_ENERGY_SOLAR_NAMEPLATE_W = "energy_solar_nameplate_w"` (`:840`). Live
    19,400 W. D1.2 uses it for the nameplate sanity assertion.
* `translations/en.json:964-966` — verified help-text verbatim for the three
  SOC-band knobs.
* `database.py:4526-4535` — `save_evse_state` atomic.
* Historical git-log verification: `_paused_by_grid_cap` in v4.0.18
  (commit `1a499f0b8`); `_paused_by_arbitrage` in v4.5.0 (commit `f3deabc84`).
* Memory: `project_optimizer_db_write_flood_incident_2026_06_09`;
  `project_ev_drain_precedence_cycle`; `feedback_suppression_needs_discharge`;
  `feedback_hollow_test_anchors`;
  `feedback_mutation_verification_pycache_staleness`; `RESTART-SAFETY-DOCTRINE-1`.

### 2a. Operator-supplied measurements (institutional context)

* **Peak grid import observed** (8,341 samples): **27.50 kW** = 114.6 A. Cluster
  21:00-22:30, no solar, peaks 26-27.5 kW — during the intended off-peak EV
  charging window.
* **`DEFAULT_GRID_IMPORT_CAP_KW = 8.0` would fire in 20.8% of samples** in this
  house; live setting **20 kW fires in 0.80%**. Shipped default badly mismatched
  to this deployment; recorded so a future reader does not treat 8 kW as a sane
  baseline here.
* **`sensor.span_panel_car_charger_power` peaks at 12.24 kW (51 A)** — measured
  confirmation of the binary-48 A behaviour that motivates this cycle.
* **Service:** 400 A across two SPAN panels, 200 A each (160/150 A continuous per
  NEC 80%).
* **Peak single-panel load observed:** `sensor.span_panel_current_power` max
  21.78 kW = 90.8 A = 57% of that panel's 160 A continuous rating.
* **Peak AC production observed: 18.2 kW.** Load-bearing for the §5a
  never-invented capacity backstop reasoning.

### 2b. EVSE circuit topology (operator-supplied physical fact)

**Verbatim from operator:** *"the 2 chargers are on separate circuits by code.
Directly connected to diff 160/150A SPAN circuits using 60A each which is why they
are 48A max."*

- `garage_a` EVSE: dedicated 60 A branch on the 160 A SPAN panel.
- `garage_b` EVSE: dedicated 60 A branch on the 150 A SPAN panel.
- Each EVSE's 48 A maximum is NEC 80% continuous of its own 60 A branch, enforced
  in the EVSE hardware/pilot independently of URA.
- **No shared branch between the two EVSEs.** No fleet-level circuit contention on
  the branch layer.
- The two SPAN panels (200 A each; 160/150 A continuous respectively) are the
  next level up; each panel individually has ample continuous headroom over one
  EVSE's 48 A draw + the panel's other loads.

**Why this is institutional context, not derivable:** URA cannot discover which
subpanel each EVSE sits on from entity names or state. Recorded here so no future
cycle re-opens the shared-branch question. See §5a for the two-ground reasoning
that closes the associated capacity-backstop concern.

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
        status_entities: dict[str, str] | None = None,       # Rev-11
        solcast_next_hour_entity: str | None = None,
    ) -> None:
        self.hass = hass
        self._ev = ev
        self._current_limit_entities = current_limit_entities
        self._status_entities = status_entities or {}
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
        self._last_cessation_reason: dict[str, str] = {}
```

Cross-class reads use `self._ev.<attr>` with `# noqa: SLF001`. Lifecycle unchanged.

**Rev-11 helpers `_read_status(evse_id)` and `_is_drawing(evse_id)`:** unchanged.

> **Rev-14 consolidation.** Revisions 4-13 progressively replaced spec text with
> "unchanged from Rev-N" pointers, so this document stopped containing its own design:
> D1's design points, D1.3-D1.9, the pause policies and the WHOLE of D2 existed only in
> git history. That is the same defect as a delta file beside a base plan — a builder
> cannot follow a pointer to a revision that is not in the file. Rev-14 restores the full
> text inline. Where a later revision superseded a restored passage, the later decision
> governs and is stated in place; §13's change log remains the authority on what changed
> when. NO POINTER TO A PRIOR REVISION MAY STAND IN FOR SPEC TEXT.

**Design points (each with the review finding it addresses):**

1. **Always-on 60 s timer with empty-set fast path (B-5).** The controller runs on its own
   `async_track_time_interval` timer started at `async_setup_entry` and cancelled at
   `async_unload_entry`. When both `_excess_solar_active` is empty AND `_original_amps` is
   empty, the tick returns after a cheap membership check. Avoids the bootstrap-observer
   problem (cannot hook onto set mutations without touching the EC tick, a non-goal), and
   collapses the PB-2 cross-clock window because restore always runs on the next 60 s edge
   regardless of the state at the time of restart.
2. **Fleet allocation over ELIGIBLE, not raw membership (B-3 + Rev-3 INV-SF-7).** Compute
   surplus S once per tick. Compute `A_total_target = floor(S * 1000 / (240 * PHASES))`. Build
   `ELIGIBLE = {evse_id in _excess_solar_active where NOT _stronger_peer_holds(evse_id) AND
   evse_id not in _paused_by_dp}`. `N_eligible = len(ELIGIBLE)`.
   `A_per_evse = A_total_target // N_eligible`. If `N_eligible == 0`: no writes, no captures.
   Then per eligible EVSE: clamp `A_per_evse` to `[MIN, MAX]`, apply deadband and step law,
   write. Equal-split is operator-default; priority ordering is a non-goal (§4).
3. **6 A hold instead of stop-writing when per-EVSE share < 1.44 kW (B-2).** The 6 A pilot
   floor is a hardware constant, not a policy. Writing nothing while the last commanded amps
   are e.g. 20 A means the session draws 4.8 kW against 1 kW surplus for the entire release
   streak. Correct behaviour: clamp UP to 6 A and hold. The release gate (D2) owns actual
   session termination. INV-SF-4's `max(..., N*MIN*240)` clause is the formal statement.
4. **`SOLAR_FOLLOW_HEADROOM_KW` deleted (B-6).** Headroom is by definition permission to pull
   from the battery — the exact harm INV-SF-4 forbids.
5. **`_original_amps` persistence via existing KV blob machinery (A-HIGH-2).** Do NOT introduce
   a fake `persistence_kind="per_evse_dict"`. Persist as an inline bool-shape sibling of
   `excess_solar_active`: extend `db.save_evse_state(evse_id, ...)` at `energy.py:1839` with a
   new column `original_amps: float | None`, restored at `energy.py:1365-1366` alongside the
   existing `excess_solar_active` bool. Zero new persistence machinery. Alternative if the
   column add is undesirable: a single new KV `evse_original_amps_v1` (JSON dict
   `{evse_id: float}`) with a `_KNOWN_HOOKS`-registered save/restore pair matching the DP
   `drain_precedence_state_v1` shape (`energy_const.py:1390`). Builder picks; plan owns both
   acceptable shapes.
6. **`_original_amps` capture guarded against captured-throttle hazard (A-HIGH-3).** On session
   ENTRY (first tick where `evse_id ∈ ELIGIBLE` and no `_original_amps[evse_id]`), read the
   current-limit entity. THREE cases:
   a. State fresh, value in `[SOLAR_FOLLOW_MIN_AMPS, SOLAR_FOLLOW_MAX_AMPS]` — save it.
   b. State stale/unavailable — save `SOLAR_FOLLOW_RESTORE_AMPS` (48); log INFO.
   c. Value < `SOLAR_FOLLOW_CAPTURE_SANITY_A` (=20 A default, rung-1) — smoking gun of the
      10 h staleness scenario. Save `SOLAR_FOLLOW_RESTORE_AMPS` (48), log WARNING with the
      observed value, expose event on the status sensor as `capture_rejected_low` counter.
   **Different door from INV-SF-7:** INV-SF-7 excludes peer-held EVSEs from ELIGIBLE entirely
   so no capture happens under a peer hold; A-HIGH-3's sanity guard catches stale-restart
   values on EVSEs that ARE eligible.
7. **Mirror the start condition to the stop condition (A-HIGH-4).** The always-on timer
   already prevents the "restart within 60 s of release" hazard: at restart, if
   `_excess_solar_active` is empty but `_original_amps` is non-empty (persisted per point 5),
   the next 60 s tick fires the restore path (subject to INV-SF-7 deferral). Empty-set fast
   path explicitly checks BOTH sets before returning no-op.
8. **A-MED-1 / B-4 mitigation.** D1's surplus signal uses ONLY raw measured grid power (D1.2)
   plus raw Emporia per-charger power via `current_charging_load_w()`. If per-charger power is
   unavailable, the controller falls back to `SOLAR_FOLLOW_STALE_MAX_TICKS` (=2) grace then
   stops writing — it does NOT substitute `EVSE_ESTIMATED_POWER_W`. The wider concern (DP's
   fit arithmetic sees a throttled charger whose power reads through the same estimate
   fabrication on outage) is documented in §5 as a pre-existing pathology D1 exposes but does
   not create.

**Per-tick control law (Rev-8/Rev-11 form — pure surplus split, no circuit-cap
composition):**

```
0. STEP 0 edge-detector for _drain_trips_during_follow (Rev-7).
1. If _excess_solar_active empty AND _original_amps empty: return.
2. RESTORE PASS (iterate list(self._original_amps)).
3. If _excess_solar_active empty: return.
4. Read grid_W via D1.2. If unavailable for STALE_MAX_TICKS: no writes.
   (D1.2 nameplate sanity assertion also applies here — see D1.2.)
5. Build ELIGIBLE per Rev-11 (status-first with power fallback).
   Build DRAWING ⊆ ELIGIBLE per Rev-11.
6. N_eligible = len(ELIGIBLE); N_drawing = len(DRAWING); N_denom = max(1, N_drawing).
7. add_back over DRAWING; S_eligible = -grid_W + add_back_w;
   A_total_target = floor(S_eligible / (240 * PHASES)).
8. A_per_drawing_raw = A_total_target // N_denom.
9. For each evse_id in ELIGIBLE:
   a. Capture _original_amps[evse_id] if unset (Rev-8 A-HIGH-3 sanity guard).
   b. If evse_id in DRAWING:
        A_target = clamp(A_per_drawing_raw, MIN, MAX)
      Else (safe-parking):
        A_target = SOLAR_FOLLOW_MIN_AMPS
   c-h. read A_current; deadband; step law; write-budget; emit; readback verify.
```

**Pause ENTRY policy (a stronger peer starts holding an EVSE mid-session):** LEAVE
`_original_amps` in place; do NOT restore before yielding. Rationale — (1) restoring 48 A
under a stronger owner (arbitrage CHARGE mutex, grid-cap, load-shed) risks fighting them:
arbitrage CHARGE explicitly pauses to bound compound load; a restore-then-yield would blip
the pilot to 48 A momentarily. (2) The stronger owner has turned the SWITCH off; the
current-limit value on the (now off) charger is cosmetic until the switch re-closes. (3) When
the stronger owner releases: if excess-solar is still active, step 9 resumes modulation from
the saved `_original_amps` (correct); if not, step 2 fires the restore on the NEXT tick
(correct).

**Pause RELEASE policy (peer holds clear):** D1 discovers the eligibility change on the next
60 s tick by re-reading `_stronger_peer_holds` and `_paused_by_dp` — there is no signal
subscription. Subscribing to owner-set mutations would couple D1 into `energy_pool.py`
mutation sites, expand blast radius, and re-introduce the exact bootstrap-observer problem
B-5 rejected. **Worst-case release latency: 60 s.** In that window an EVSE released from
(e.g.) `_paused_by_arbitrage` sits at a solar-throttled amp limit while a stronger owner no
longer holds it. Direction of harm: UNDER-draw. The charger continues at (say) 14 A when it
could go to 48 A for that 60 s window. This is harmless: it leaves ≤60 s of potential
charging on the table but cannot over-draw against the service (fleet math is still bounded
by measured surplus in step 7) and cannot pull from the battery (INV-SF-4 unchanged). Same
bound class as PB-2's cross-clock window.

**D1.2 — surplus signal (nameplate sanity assertion, kept from prior exchange).**
All Rev-11 content preserved, plus:

```python
# Nameplate sanity — a signal-fault fail-safe (impossible surplus reading
# indicates a stuck sensor or mis-scaled fallback, not a capacity risk).
NAMEPLATE_W = <read CONF_ENERGY_SOLAR_NAMEPLATE_W field, default 19400>
if S_eligible > NAMEPLATE_W * 1.15:  # 15% headroom for measurement noise
    _LOGGER.warning(
        "solar-follow: computed S_eligible=%s exceeds nameplate=%s + 15%%; "
        "treating as signal fault, routing to STALE path.",
        S_eligible, NAMEPLATE_W,
    )
    self._stale_ticks += 1
    return
```

Rationale: `S_eligible > 22.3 kW` on a 19.4 kW array is not physically achievable;
indicates a signal fault. Fail-safe is STALE path. Cost is one comparison per tick;
no new knob (reads existing `CONF_ENERGY_SOLAR_NAMEPLATE_W`).

**D1.3 — self-consistency stop.** Both PRIMARY and FALLBACK unavailable for
`SOLAR_FOLLOW_STALE_MAX_TICKS` (=2) → no writes, WARNING logged. Fail-safe.

**D1.4 — current-limit entities.** Added to `DEFAULT_EVSE_ENTITIES` at
`energy_pool.py:168-183` under new key `current_limit`:
* `garage_a`: `number.garage_a_evse_emporia_wifi_garagea_current_limit`
* `garage_b`: `number.garage_b_evse_emporia_wifi_garageb_current_limit`
L1 chargers explicitly excluded.

**D1.5 — Solcast next-hour stop.** New `CONF_SOLCAST_NEXT_HOUR_ENTITY` (rung 2, per-deployment
entity id) populated from `sensor.solcast_pv_forecast_forecast_next_hour`. Consumed by D2 as
a second release condition. `SOLAR_FOLLOW_NEXTHOUR_FLOOR_W` (rung 1, 1000 W) is protocol.

**D1.6 — bounded in-controller write-verify.** After every write,
`async_call_later(SOLAR_FOLLOW_VERIFY_S=8, ...)` reads back and checks within 1 A tolerance.
WARNING + counter increment on mismatch. Does NOT extend `_maybe_schedule_write_verify`
(surface-keyed, silently drops non-reserve targets — audit §1 row 5). Widening the
write-verify surface is an explicit non-goal.

**D1.7 — write-budget containment.** `SOLAR_FOLLOW_MAX_WRITES_PER_HOUR_PER_EVSE` (=30, rung 1).
Hour bucket per EVSE; if exceeded, skip writes for remainder of the hour, WARN, expose on
status sensor.

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

**D1.9 — non-peer-hold owner accounting.** `_paused_by_us`, `_proactive_offpeak_holds` and
`_blind_window_liveness_ride` are each accounted for in §5; none is a peer-hold member and none
blocks a solar-follow write.


**Rev-14 defect found and fixed — peer holds were silently converting into stops.**
Before this fix the streak observation ran over every `evse_id ∈ _excess_solar_active` with
only an `unavailable` exclusion. A peer hold does NOT drop the claim (INV-SF-7 excludes the
bay from ELIGIBLE; it does not release it), so a peer-paused bay stayed in the session while
its charger stopped drawing. Consequences, both reachable on ordinary config:
1. **False cessation reason.** Drain protection or the grid cap pauses the bay; status reads
   `Disconnected` or `Connected`-not-drawing; the streak matures and the session is released
   as `car_disconnected` (10 min) or `car_idle` (20 min). The ledger would attribute a
   safety-gate pause to the car leaving or finishing — and `peer_hold` would almost never
   appear, because the streak paths would win the race. The ledger is the artifact the
   operator asked for; recording the wrong reason is worse than recording none.
2. **Premature termination.** A transient peer hold — a 10-minute drain-protection pause on
   a passing cloud — would permanently end the solar session rather than suspending it. On
   peer release the controller would have to re-acquire through the full start gate
   (`conditions_met` + forecast), which may not be satisfiable until the next day.
The fix keeps the model the operator settled on — solar-follow starts and stops, it never
pauses itself — while ensuring a PEER's pause is not mistaken for a STOP.

**D1.10 — session ledger: WHY it started, WHY it stopped (Rev-14 — specified here for the
first time; prior revisions declared `_last_cessation_reason` without a vocabulary or write
points, which made the field unimplementable).**

Three fields on `SolarFollowController`, all per-EVSE:

```python
self._last_start_reason: dict[str, str] = {}
self._last_cessation_reason: dict[str, str] = {}
self._last_cessation_at: dict[str, datetime] = {}
```

**Start vocabulary (closed set)** — written when an EVSE enters `_excess_solar_active`:
* `solar_surplus` — the normal path: `conditions_met` True (battery SOC above the resume
  threshold AND remaining forecast above the kWh threshold) and the bay was claimed.
* `dp_yield` — claimed from a deferred DP hold (`_dp_yield_ok`, carrier state HOLD_ONLY).
* `tou_claim` — claimed from a TOU pause (`_paused_by_us` discarded on claim).

**Cessation vocabulary (closed set)** — written on every path that removes an EVSE from
`_excess_solar_active`, alongside `_last_cessation_at`:
* `surplus_gone` — INV-RELEASE-1 fired on `not conditions_met` (house-side: SOC fell below
  the resume threshold, or remaining forecast fell below the kWh threshold).
* `forecast_poor` — INV-RELEASE-1 fired on `solcast_next_hour_w < SOLAR_FOLLOW_NEXTHOUR_FLOOR_W`.
* `car_disconnected` — INV-RELEASE-2 disconnected path; EVSE status read `Disconnected` for
  `SOLAR_FOLLOW_DISCONNECTED_RELEASE_TICKS`. The car left.
* `car_idle` — INV-RELEASE-2 idle path; status `Connected` but not drawing for
  `SOLAR_FOLLOW_IDLE_RELEASE_TICKS`. Car finished, or is refusing the pilot. **These two are
  NOT distinguishable further** — see the honesty note below.
* `peer_hold` — a stronger peer claimed the bay (INV-SF-7). Records WHICH owner in
  `_last_cessation_detail[evse_id]` from `iter_peer_holds()` plus the inline `_paused_by_dp`
  check, so `battery_drain` / `grid_cap` / `arbitrage` / `load_shed` / `fill_priority` /
  `blind_window` / `dp` are separable after the fact.
* `evse_unavailable` — status `unavailable` (the EVSE unit is offline, NOT a statement about
  the car). Neither streak counter advances in this state; release is deferred to the normal
  machinery, and this value is written only if some other path then releases.
* `stale_signal` — D1.3 self-consistency stop or the D1.2 nameplate sanity assertion; the
  controller stopped because it stopped trusting its own inputs.

**Surfaced on the D1 status sensor** as `last_start_reason`, `last_cessation_reason`,
`last_cessation_detail` and `last_cessation_at` (per-EVSE maps). Restart behaviour: RAM-only,
not persisted — a lost ledger entry after a restart is a lost diagnostic, never a lost
safety property, and persisting it would add a write path for a purely observational field.

**Honesty note on what the ledger CANNOT distinguish.** URA has no J1772 state-of-charge leg
— the Emporia is a relay plus a power meter — so `car_idle` conflates *car reached its own
charge target*, *car reached a target set in its own app*, and *car refused the handshake*.
All three present identically as `Connected` + not drawing. Do not add a knob or a heuristic
that pretends to separate them; a future cycle wanting that needs J1772 SoC decoding, which is
a hardware-capability question and is listed in §4 non-goals.

**Acceptance:** after a week of live running, every session end in the ledger carries a
non-null reason, and the distribution across reasons is inspectable without reading logs. A
reason that never appears is either dead code or an unexercised path — both worth knowing.


**Constants (D1 knob ladder):**

| Name | Rung | Value | Why this rung / derivation |
|---|---|---|---|
| `SOLAR_FOLLOW_TICK_S` | 1 | 60 | Protocol; matches Emporia 1-min average |
| `SOLAR_FOLLOW_MIN_AMPS` | 1 | 6 | J1772 pilot floor, hardware constant |
| **`SOLAR_FOLLOW_MAX_AMPS`** | **1** | **48** | **DERIVED, NOT ARBITRARY. 48 A = NEC 80% continuous rating of each EVSE's own dedicated 60 A branch circuit (§2b topology). One dedicated 60 A circuit per EVSE, per code. This constant IS the per-charger circuit-capacity bound for THIS install; the EVSE hardware/pilot enforces the same 48 A independently. DO NOT RAISE. A future cycle noticing the charger hardware supports higher, or an operator with a different EVSE model on a different circuit, must NOT casually re-tune this — raising it silently would exceed the 60 A branch's 48 A continuous rating and violate code. Rung 1 reviewed-change-only.** |
| **`SOLAR_FOLLOW_RESTORE_AMPS`** | **1** | **48** | **DERIVED. Same derivation as MAX_AMPS above (NEC 80% of 60 A branch). Restore path defaults to this when `_original_amps` was not captured. DO NOT RAISE for the same reason.** |
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
| `SOLAR_FOLLOW_DISCONNECTED_RELEASE_TICKS` | 1 | 2 | Rev-11. 10 min at D2's 5-min cadence. |
| `SOLAR_FOLLOW_IDLE_RELEASE_TICKS` | 1 | 4 | Rev-10. 20 min at D2's 5-min cadence. |

**D1 acceptance:**

All Rev-8/10/11 tests preserved (INV-SF-1..7, T-STALE-1, T-ITER-1, T-PEER-1..6,
T-DRAIN-1..4, T-DRAW-1..3, T-STATUS-1..5, T-IDLE-DISCONNECT-1, T-IDLE-CONNECTED-1,
T-IDLE-EMPTY-BAY-1, T-IDLE-UNAVAILABLE-1, T-CESSATION-1).

* **T-NAMEPLATE-1** `test_nameplate_sanity_routes_to_stale_on_impossible_surplus`.
  Fixture: `grid_W = -30000` (30 kW export — impossible on 19.4 kW array). Assert:
  WARN + `_stale_ticks` increments + no writes. Under bug (no assertion): 30 kW
  passes through, allocator commands unrealistic amps.

**Mutation drill:**
* **C24** remove the nameplate sanity assertion in D1.2 → **T-NAMEPLATE-1 must
  fail** (30 kW impossible surplus not caught).

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
   _excess_solar_active`, FIRST check peer ownership (Rev-14):
   - `_stronger_peer_holds(evse_id) or evse_id in self._ev._paused_by_dp` → set BOTH
     `_idle_streak_ticks[evse_id] = 0` and `_disconnected_streak_ticks[evse_id] = 0`,
     then `continue` — do not read status, do not advance either counter.
   Otherwise read `_get_evse_state(evse_id).charging`:
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

---

## 4. Non-goals (explicit)

All Rev-8/10/11 non-goals preserved.

* NOT re-tuning `DEFAULT_EXCESS_SOLAR_SOC_THRESHOLD=95` or
  `CONF_ENERGY_FILL_PRIORITY_SOC` in this cycle. See §14 design question (A).
* NOT changing the shipped `DEFAULT_GRID_IMPORT_CAP_KW = 8.0`. Live 20 kW is
  operator-tuned and correct here. §2a records mismatch as institutional context.
* NOT enabling `energy_arbitrage_grid_import_guard_enabled` (currently disabled).
  Operator's Envoy installer-level charge-rate setting supersedes it for this
  house; §11 supersession triage records KEEP+DOCUMENT.
* **NOT raising `SOLAR_FOLLOW_MAX_AMPS` above 48 A** — that is NEC 80% continuous
  of each EVSE's own dedicated 60 A branch (§2b topology). Raising it exceeds the
  circuit rating for THIS install. Any future cycle wanting to raise the constant
  MUST first verify the operator's branch-circuit rating supports the new value.

---

## 5. Known couplings

(Rev-8/9/10/11 items 1-14 unchanged.)

15. **Two grid-import protections, not one.** Verified in `energy_const.py`:
    - **EV grid-import cap** — `CONF_ENERGY_GRID_IMPORT_CAP_ENABLED`,
      `CONF_ENERGY_GRID_IMPORT_CAP_KW`, `DEFAULT_GRID_IMPORT_CAP_KW = 8.0`. Pause
      site at `energy_pool.py:1723-1735`. **Reactive** grid-import ceiling on EV.
      **Live in this house: enabled, 20 kW.**
    - **Arbitrage grid-charging guard** — `CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED`,
      `CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW`,
      `DEFAULT_ARBITRAGE_GRID_IMPORT_GUARD_KW = 12.0`. Bounds grid-charging the
      BATTERY during arbitrage. **Live in this house: DISABLED.** Operator: Envoy
      installer-level charge-rate setting supersedes it.
    - **Do NOT conflate them.** Different components, different hazards.

### 5a. Hazard model — TWO modes on TWO components, and why the fleet capacity backstop is not in this plan

**Mode 1 — Main-service sustained compound load.** Thermal-element trip of the
service breaker + conductor heating + insulation degradation, cumulative over
minutes to tens of minutes. A 5-minute control loop IS dimensioned for this. The
EV grid-import cap (REACTIVE, `energy_pool.py:1723-1735`) and the v4.5.0 D4
arbitrage/EV mutex (PREVENTIVE, `energy.py:6240-6263` + `:6290-6328` +
`:6341-6365`) both address this mode. OVERLAPPING (see §5b open supersession
question). D1 does NOT re-solve this. INV-SF-7 subordinates D1 to both (both are
strong peers via `iter_peer_holds()`).

**Mode 2 — Battery-breaker inrush transient.** ~32 kW TRANSIENT on grid-charge
initiation that reliably trips the battery breaker (operator-observed). Fast
(milliseconds to seconds), **beyond a 5-minute software loop's reach**. The real
fix is an installer-level charge-rate setting on the Envoy itself. The arbitrage
grid-charging guard exists as a software-level second-line defence for deployments
without the Envoy setting; disabled here because the Envoy setting supersedes it.

**Recording note (do not re-derive):** "software can't protect a breaker at this
cadence" is CORRECT for the inrush hazard and WRONG for the sustained one. Both
are true, of different components. This plan carries both.

**Why a fleet-level circuit-capacity backstop is NOT in this plan (recorded per
operator ruling, so it is not re-derived a fourth time).** Two independent
grounds, either sufficient:

1. **Topology closes the shared-branch scenario.** §2b: the two EVSEs are on
   separate dedicated 60 A branches on different SPAN panels (150/160 A each).
   No shared branch exists between them. Each charger's 48 A ceiling is the
   NEC 80% continuous rating of its own dedicated circuit, enforced by the EVSE
   pilot in hardware. **D1's existing per-EVSE clamp to `MAX = 48 A` already IS
   the circuit-capacity bound** for THIS install; a fleet-level bound would be
   guarding against a shared conductor that doesn't exist here.

2. **The failure mode the backstop would guard is not a safety failure.** A bug
   in the surplus arithmetic makes the EV draw more than the available surplus,
   which pulls from battery or grid. That is a **cost and battery-wear outcome,
   not a thermal or breaker one** — per-charger current is hardware-clamped at
   48 A on a dedicated 60 A circuit, so nothing overheats. And that cost/wear
   outcome is ALREADY bounded by two existing strong peers: drain protection
   (`_paused_by_battery_drain`, INV-SF-7 subordination applies) and the EV
   grid-import cap (see item 15 above). A backstop that guards a hazard which is
   (a) not reachable per-charger, (b) not shared across chargers, and (c)
   already covered by two live gates, earns nothing.

3. **Reachability.** The hostile two-chargers-at-MAX combination required ~23 kW
   of surplus (96 A × 240 V); measured peak AC production is 18.2 kW (§2a). A
   correctly-working surplus-follower could never command it, even setting aside
   grounds 1 and 2 above.

### 5b. Open question for a future supersession audit

**Do the EV grid-import cap (v4.0.18) and the D4 arbitrage/EV mutex (v4.5.0)
overlap on the sustained main-service hazard?** OVERLAPPING, not proven redundant.
The arbitrage grid-charging guard is a DIFFERENT component (battery breaker
inrush) and NOT part of this overlap question. NOT a delete candidate; both live.
Trigger: fired incident where the two disagree, OR a cycle proposing to touch
either. Read-only audit, separate cycle.

---

## 6. Docs drift to fix in-cycle

* `energy_pool.py:_stronger_peer_holds` docstring says "the five", loop returns
  six. Add `blind_window`.

---

## 7. Test plan summary

All Rev-11 tests preserved. Plus **T-NAMEPLATE-1**.

---

## 8. Review plan — Tier 3, four framing-disjoint passes

* **A — local correctness.** ELIGIBLE-scoped writes + DRAWING-scoped allocation +
  DRAWING-scoped add-back; step 2a/2b/2c convention; snapshot iteration; STEP 0
  edge-detector rules; `max(1, N_drawing)` divide-by-zero guard; safe-parking
  routing; idle-streak arithmetic; idle-release AND-clauses; nameplate sanity
  assertion (15% headroom, warn+stale, no writes).
* **B — integration / state-machine + byte-identical no-op.** Class shape; SLF001;
  restart paths; must-start-release corner (Q5). `determine_battery_drain_actions`
  and `solar_replenishing` path BOTH byte-identical. Excess-solar CLAIM path
  byte-identical. `_disconnected_streak_ticks` follows same lifecycle as
  `_idle_streak_ticks`.
* **C — REAL per-site source mutation.** Rev-8/10/11 drills preserved:
  C17/b/c/d/e/f, C18, C19/b, C20/b/c, C21/b/c, C22/b/c/d. Plus **C24** (nameplate
  sanity assertion).
* **D — adversarial completeness / diff-blind.** All Rev-8/10/11 tasks. Enumerate
  every code path that writes to a current-limit entity and confirm the MAX_AMPS
  clamp applies (per §2b topology, that clamp IS the circuit bound; a future
  writer bypassing the clamp would exceed the circuit rating). Legal-config
  combinatorial. Every leak → concrete legal-config repro.

**Orchestrator pre-deploy verification:** all prior grep set + run C24 drill;
grep-check that `SOLAR_FOLLOW_MAX_AMPS = 48` is the ONLY per-EVSE ceiling in the
clamp path and no code path bypasses it; grep-check that the derivation comment on
the constant survives. Operator checkpoint BEFORE deploy.

---

## 9. REUSE vs NEW

(All Rev-8/9/10/11 rows preserved.)

Additions:

| Item | Verdict | Cite |
|---|---|---|
| `CONF_ENERGY_SOLAR_NAMEPLATE_W` field (nameplate sanity uses it) | REUSE | `energy_const.py:840`; default 19,400 W |
| Nameplate sanity assertion in D1.2 | NEW | Cost-free (one comparison per tick); no new knob |

---

## 10. Design pushback recorded

### PB-1 — REJECTED (unchanged).
### PB-2 — WITHDRAWN.
### PB-3 (Rev-11) — TOU-defer-to-solar-follow — PARKED with falsifiable revival trigger.
### Rev-10 / Rev-12 hazard-framing history — RECORDED (§5a).

---

## 11. Supersession triage (Rev-12 pre-registered)

**Scope:** pre-registered analysis, NOT execution. Execution gated to the post-ship
supersession + consumer-gap audit per CLAUDE.md. No knob in this table is proposed
for deletion in this cycle.

| Knob | Live | Default | Premise | Modulation impact | Bucket | Gate / Note |
|---|---|---|---|---|---|---|
| `energy_fill_priority_soc` ("Pause EV Until Battery SOC") | 80 | 80 | Pauses EV+L1 when SOC drops below threshold so battery fills first — premise is that a binary 48 A EV would out-compete battery charging | Under D1 modulation, EV consumes only true export surplus; while battery is charging there IS no export; EV throttles toward MIN by construction. Premise removed. | **DELETE-CANDIDATE (GATED)** | Gate: solar-follow LIVE for N=4 weeks with `drain_trips_during_follow ≈ 0`, no observed `car_connected_not_drawing` cessation preceded by battery drain, AND no observed instance where the fill-priority pause was the mechanism that saved the battery from EV out-competition. Any signal argues KEEP. Do NOT delete in this cycle. |
| `energy_excess_solar_soc` ("Resume EV at Battery SOC") | 95 | 95 | Start gate for excess-solar sessions AND continue gate via `conditions_met` re-eval | Modulation does not decide when to begin | **KEEP** | Not a triage subject. |
| `energy_excess_solar_kwh` ("Excess Solar Forecast Threshold") | 5.0 | 5.0 | Avoid starting a session that will immediately end | Modulation degrades gracefully | **KEEP** | Prevents session churn at the day's edge. |
| `energy_ev_battery_drain_soc` ("EV Drain-Protection SOC Floor") | 80 | 50 | Safety gate: pause EV when battery discharges below floor. R1 protective ceiling. | Independent of modulation | **KEEP (unconditionally)** | Safety gate. INV-SF-7 subordinates D1 to it. Live-vs-default (80 vs 50) is DP-doc's concern. |
| `energy_grid_import_cap_enabled` + `_kw` ("EV Grid Import Cap") | enabled, 20.0 | disabled, 8.0 | Cost/policy ceiling on grid-import while EV is charging. Reactive pause. | Independent of modulation | **KEEP (unconditionally)** | Cost-policy AND part of sustained main-service hazard defence (§5a). §5b is the overlap open question. |
| `energy_arbitrage_grid_import_guard_enabled` + `_kw` (arbitrage grid-charging guard) | disabled, 12.0 | disabled, 12.0 | Software second-line defence against battery-breaker inrush during arbitrage grid-charging | Orthogonal to solar-follow | **KEEP + DOCUMENT** | Disabled here because operator has Envoy installer-level charge-rate setting that supersedes it. Per operator: "other homes may need it." Add code comment / field help-text: "retired in this house — Envoy installer setting supersedes. Available for deployments without that setting." |
| `energy_solar_nameplate_w` | 19,400 | 19,400 | Solar array nameplate for sanity bounds and forecast scaling | D1.2 makes it a NEW consumer for nameplate sanity assertion | **KEEP + WIRE** | D1.2 wires to it. Was previously read only by forecast scaling; now also gates D1's surplus math against impossible values. |
| `SOLAR_FOLLOW_HEADROOM_KW` | — | — | (Rev-1 speculative; deleted at Rev-2) | Never shipped | **N/A** | Recorded to prevent re-derivation. |

**What the sweep found the coordinator did not name:** `CONF_ENERGY_SOLAR_NAMEPLATE_W`
(now D1 consumer); `DEFAULT_GRID_IMPORT_CAP_HYSTERESIS_KW` (KEEP); the
`self_modulates` dormant hook (parked, not a triage subject).

---

## 12. Closed concerns — must stay closed

(All Rev-8/9/10/11 rows preserved.)

| Concern | Round originally closed | The one-line invariant that keeps it shut |
|---|---|---|
| [prior rows preserved] | | |
| **Two grid-import protections (EV cap v4.0.18, arbitrage guard v4.5.0) are distinct components with distinct hazards; do not conflate** | Rev-12 (operator-flagged; verified in `energy_const.py`) | §5a documents mode 1 (main-service sustained load, EV cap + D4 mutex) and mode 2 (battery-breaker inrush, Envoy installer setting, arbitrage guard as backup). §5b sharpens overlap open question to EV cap + D4 ONLY. §11 supersession triage: EV cap KEEP unconditionally, arbitrage guard KEEP+DOCUMENT. |
| **"5-point drawdown" framing conflated `fill_priority_soc` and `excess_solar_soc`** | Rev-12 (operator-corrected via screenshots + `translations/en.json:901-903, 964-966`) | Two DIFFERENT mechanisms on DIFFERENT functions. Asymmetric hysteresis band with two named ends, not single continue-gate at 95. §14 design question (A) is measurement-first for the composed behaviour. |
| **`SOLAR_FOLLOW_MAX_AMPS = 48` is derived from the circuit, not a magic charger characteristic; a future cycle raising it would silently exceed the branch continuous rating** | Rev-13 (operator-corrected via topology fact) | Knob table records the derivation (NEC 80% of 60 A dedicated branch per §2b) with an explicit "do not raise" note. Rung 1 reviewed-change-only. §4 non-goal explicit. §8 pre-deploy grep-check verifies the derivation comment survives on the constant. |
| **Fleet-level circuit-capacity backstop is not needed and would earn nothing on this install; the mechanism must not be re-derived** | Rev-13 (operator ruling), Rev-14 (fully removed from doc body) | §5a records the two-ground reasoning (topology closes the shared-branch scenario per §2b; the failure mode is cost/wear not thermal, and is already covered by two live strong peers `_paused_by_battery_drain` + EV grid-import cap). Reachability line (~23 kW required vs 18.2 kW measured peak) is a third independent argument. If a future revision proposes a fleet-level current bound, this row is the fourth-time-re-derivation warning. |

---

## 13. Change log

Combined-plan Rev-1..Rev-8 in git history. Split at Rev-9 (D4 attribution
correction). Rev-10 (breaker-caveat + safe-parking exit). Rev-11 (Emporia status
sensor + cessation ledger + parked design questions). Rev-12 (asymmetric-band
framing + two grid-import protections + INV-SF-5 step-load rationale + nameplate
sanity + measured institutional context + a fleet circuit-capacity invariant and
its config surface, all subsequently withdrawn). Rev-13 recorded the withdrawal
reasoning. Rev-14 fully applied the withdrawal:

| Finding | Severity | Change |
|---|---|---|
| **Rev-13's withdrawal reasoning was recorded but the machinery it withdrew was still in the doc body (invariant stub in §1, `__init__` params, helpers, control-law step-8 composition, knob-table rows, tests, mutation drills, OPEN INPUTS block, cross-references)** | Cleanup (operator ruling) | Rev-14: removed all remaining references. `__init__` returned to the Rev-11 signature (no `circuit_groups` / `circuit_continuous_amps` params). Helpers `_circuit_group_for` / `_circuit_cap_amps` removed. Control-law step 8 restored to pure surplus split. Knob-table rows for `CONF_SOLAR_FOLLOW_CIRCUIT_*` removed. Tests T-CIRCUIT-1..4 removed. Mutation drills C23/b removed. Rev-12's REV-12 OPEN INPUTS block at doc top removed. §1 no longer contains an invariant stub for the withdrawn item. §10 no longer carries a `## PB record` for it. §12 register carries a single row that consolidates the closure (two-ground reasoning + reachability), which is the durable residue per operator direction. The nameplate sanity assertion is renamed **T-NAMEPLATE-1 / C24** and kept — it is a signal-fault fail-safe, unrelated to any circuit concern. |
| **Rev-12 changes preserved unchanged** | Nothing | Measured default-vs-live grid cap mismatch (§2a); 21:00-22:30 clustering; 12.24 kW single-charger peak; two-hazard framing (§5a modes 1 + 2); INV-SF-5 step-load rationale; §11 supersession triage; §5b overlap scoping; asymmetric-band SOC framing (§14 design question A); §12 closed-concerns rows for the two-grid-protection distinction and the SOC-band conflation; `SOLAR_FOLLOW_MAX_AMPS` derivation note and "do not raise" warning; §2b topology institutional fact. |

---

## 14. Design questions on record

**(A) SOC-band tuning under modulation.** The asymmetric hysteresis band spans two
knobs: `fill_priority_soc` (Pause EV Until, live 80) and `excess_solar_soc`
(Resume EV at, live 95). Recommendation: measure via new observability BEFORE
retuning. Post-ship audit (§15 checklist) answers whether either end deserves
adjustment.

**(B) TOU-defer-to-solar-follow.** See §10 PB-3. PARKED with falsifiable revival
trigger.

---

## 15. Cycle-close checklist

* [ ] DP fix (`PLANNING_dp_drain_target_mis_sourcing.md`) shipped and validated.
* [ ] Targeted re-review that Rev-14 cleanup is complete: zero remaining
      references to a fleet circuit-capacity invariant or its config knobs; §12
      row captures the closure durably.
* [ ] Build in one branch off `develop`.
* [ ] Suite green + baseline-diff clean.
* [ ] Four framing-disjoint reviews A/B/C/D returned; CRITICAL/HIGH fixed.
* [ ] Orchestrator pre-deploy grep set as §8 (includes C24 nameplate drill;
      MAX_AMPS derivation comment verification).
* [ ] Operator checkpoint before deploy.
* [ ] `README_v<version>.md` with prospective Live criteria.
* [ ] Deploy via `./scripts/deploy.sh`.
* [ ] Live validation: sunny-day D1 attributes; one-bay-active case; startup
      transition; release-edge restore; INV-SF-7 if arbitrage overlap; drain-trip
      counter per-event; plug-in transient bounded; idle-release fires at 20 min
      for `Connected` and at 10 min for `Disconnected`; nameplate sanity assertion
      fires no false positives on a normal sunny day (S_eligible stays well below
      22.3 kW threshold on a 19.4 kW array).
* [ ] README updated with observed `Validated <date>` table.
* [ ] Kanban card `EVSE-SOLAR-FOLLOW-AMPS-1` moved to shipped_organic.
* [ ] Post-ship supersession + consumer-gap audit per CLAUDE.md rule — EXECUTES
      §11 supersession triage against N=4 weeks of live data. INCLUDES:
  - §5b open question (grid_cap vs D4 overlap).
  - §14 design question (A) — analyse SOC-band composed behaviour.
  - §10 PB-3 revival trigger check (TOU-defer-to-solar-follow).
  - §11 DELETE-CANDIDATE gate for `fill_priority_soc`.
  - Known interaction to observe: does 21:00-22:30 grid-import clustering create
    observable friction with the EV cap?
