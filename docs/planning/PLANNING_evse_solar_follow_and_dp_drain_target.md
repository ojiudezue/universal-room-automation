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
**Probes:** `scripts/probes/delta_probe.py`, `scripts/probes/skew_probe.py` (Emporia/Envoy delta =
371 W mean / 259 W median / p90 1,014 W over 7,090 aligned pairs; monotone in slew rate).

**Revision 2 (2026-08-23) —** rewritten after two framing-disjoint plan reviews (A + B) both
returned DO NOT DISPATCH BUILD. Every A-CRIT / A-HIGH / B-CRIT / B-HIGH is addressed inline; the
change log at §12 lists each finding and its resolution.

---

## 0. Tier-3 elevation and framing

Two independent risks converge:

* **D1/D2 is a NEW WRITER on a live cloud actuator at 1-min cadence.** URA has never written amps
  before (`AUDIT §1 row 11`). Wrong containment = write-flood incident class
  (`project_optimizer_db_write_flood_incident_2026_06_09`). Wrong restore = silently crippled
  next charge. Wrong reactivity direction = drives battery discharge harder than the binary
  version the operator disabled. And wrong FLEET ALLOCATION (see §3.D1 Rev-2 fix) makes two
  chargers each pull the full surplus — the exact harm the cycle prevents.
* **D3 threads a value through a state machine with FIVE R2 emission sites** (Rev-2 count; the
  original plan claimed two). The static knob `_ev_battery_drain_soc` serves three incompatible
  roles at once (R1 pause ceiling / R2 drain floor / R3 ride-proof floor). Missing one R2 site
  stamps `_dp_decision_soc = 80` on the first successful DP transition — exactly the opposite of
  intent. Bug Class #53 (computed-but-not-consumed) shape.

Both D1 and D3 have "silent success" failure modes where every acceptance criterion I originally
wrote PASSED against a shipped bug. Tier 3.

---

## 1. Falsifiable invariants

Each stated as "under X, Y can never happen in ANY reachable path."

### INV-SF-1 (solar-follow non-perturbation)
Under any config, any TOU period, any tick, `SolarFollowController` emits no `switch.turn_on` and
no `switch.turn_off`. It writes only `number.set_value` to a **current-limit entity** and only
for an EVSE currently in `_excess_solar_active`. The controller cannot start, stop, extend, or
curtail a session by any code path.

### INV-SF-2 (writes only inside sessions)
Under any config, if `_excess_solar_active` is empty AND no `_original_amps` entries remain, the
controller performs zero writes to any current-limit entity. When the set is non-empty, writes
target ONLY EVSEs in the set. Release-edge restore writes target ONLY EVSEs with a saved
`_original_amps` entry.

### INV-SF-3 (restore is load-bearing, restart-safe)
Under any config, after an EVSE is removed from `_excess_solar_active` by any code path
(release gate `energy_pool.py:1699`, blind-window drop `:1564`, peak clear `:1369`, or restart
reconciliation `energy.py:5183-5225`), the current-limit for that EVSE is restored to its saved
`_original_amps` value (falling back to `SOLAR_FOLLOW_RESTORE_AMPS=48` only if no value was
saved) within one restore tick. `_original_amps` is persisted through HA restart via the KV
blob machinery — NOT via a fabricated `per_evse_dict` shape (see §A-HIGH-2 fix below).

### INV-SF-4 (draw bounded by measured surplus — safety, not efficiency)
Under any excess-solar-active state and any measured surplus S (kW), the commanded total EVSE
draw satisfies `sum(A_i) * 240 * PHASES <= max(S * 1000, N_active * SOLAR_FOLLOW_MIN_AMPS * 240)`.
The `max(..., N * MIN * 240)` clause is the **hardware-floor exception** (see §3.D1 Rev-2 fix
for B-2): the 6 A pilot floor means the smallest legal running session draws 1.44 kW per EVSE.
Below that per-EVSE floor the only options are STOP (owned by the release gate, not this
controller) or hold at 6 A. There is no `SOLAR_FOLLOW_HEADROOM_KW` in this bound — the term was
removed (B-6).

### INV-SF-5 (asymmetric reaction to a lagging signal)
Under any surplus movement, downward step: uncapped, fires within one tick. Upward step: gated
by `SOLAR_FOLLOW_UP_MIN_TICKS` consecutive ticks of headroom AND capped at
`SOLAR_FOLLOW_UP_STEP_A` per tick per EVSE. Encodes Emporia's 1-min average lag from
SENSOR_DELTA_MEASURED_2026_08_23.

### INV-SF-6 (fleet allocation, B-3)
Under N > 1 active EVSEs and a measured fleet surplus S, the controller computes
`A_total_target = floor(S * 1000 / (240 * PHASES))` ONCE per tick, then allocates equal shares
`A_per_evse = A_total_target // N` (integer floor), then clamps each share to
`[SOLAR_FOLLOW_MIN_AMPS, SOLAR_FOLLOW_MAX_AMPS]`. **Degenerate case:** if
`A_per_evse < SOLAR_FOLLOW_MIN_AMPS`, all EVSEs hold at `SOLAR_FOLLOW_MIN_AMPS` (6 A). Session
termination remains D2's release gate's job. The controller does not pick winners.

### INV-RELEASE-1 (D2)
Under an excess-solar-active EVSE and any tick where `conditions_met` transitions False, no
`switch.turn_off` fires until the False state has persisted `SOLAR_RELEASE_MIN_TICKS`
consecutive ticks AND session age >= `SOLAR_RELEASE_MIN_ON_S`. Any `conditions_met` True tick
resets the streak.

### INV-DP-DRAIN-1 (D3, RESTATED over the WHOLE emission set — A-CRIT-1 fix)
Under any config where `_dp_carrier.state ∈ {HOLD_ONLY, HOLD_PRE_EVAL, EVAL_TRANSITION}`, and
under any code path that populates `TransitionInputs.drain_target_soc` OR that stamps a fresh
`_dp_decision_soc` via `_apply_dp_transition`, the value used equals
`_dp_drain_target_soc(period)` (the composed floor). This applies to ALL R2 sites enumerated in
§3.D3.

### INV-DP-DRAIN-1b (revert predicate consistency — A-CRIT-2)
Under any tick where the controller has just stamped `_dp_decision_soc = X`, the revert
comparison at `energy.py:4555` uses the SAME value X, not `_ev_battery_drain_soc`. This is what
prevents the "TRANSITIONED and immediately revert on same tick" flap. Enforced by sourcing
`:4555`'s `_drain` from `_dp_drain_target_soc(period)`.

### INV-DP-DRAIN-2 (R1 pause ceiling preserved)
Under any config, `determine_battery_drain_actions(soc_threshold=...)` at `energy.py:5842`
(EV) and `:5977` (plugs) sources from `self._ev_battery_drain_soc` unchanged. This is the R1
protective ceiling. INV-DP-DRAIN-2 is what prevents the HIGHEST_PROBABILITY_BUILD_ERROR (a
builder "making it consistent" and collapsing `soc_low = soc < 10`, silently deleting the
deep-discharge backstop).

### INV-DP-DRAIN-3 (R3 ride-proof floor preserved)
Under any config, `_ev_battery_drain_soc` remains the ride-proof floor at `energy.py:3752`
(blind-hold proof), `energy_pool.py:954`, and `energy_pool.py:1435` (`env_lower >= drain_target`).
Byte-identical.

### INV-DP-DRAIN-4 (offpeak-drain live-apply or documented reload)
The four `energy_offpeak_drain_*` Number entities either live-apply into
`BatteryStrategy._drain_targets` (setter mutates the ctor-frozen dict at
`energy_battery.py:464`), or the reload-required constraint is documented on each entity's help
text AND on the cycle README. INV-DP-DRAIN-1's practical value depends on this.

Reviewer D writes a legal-config repro for any leak in any of the above.

---

## 2. Institutional context verified

Read end-to-end for scoping (paths corrected to
`custom_components/universal_room_automation/domain_coordinators/`):

* `docs/planning/AUDIT_excess_solar_and_evse_prior_art.md` (all sections).
* `domain_coordinators/energy_pool.py` — `PoolOptimizer:58-160` (template for D1 save/restore),
  `EVChargerController.__init__:186-317` (owner sets), `determine_excess_solar_actions:1318-1701`
  (D1 host — release leg `:1685-1699` is D2), `determine_battery_drain_actions:1776-1959` (D2
  secondary — no `_excess_solar_active` check, runs AFTER solar in tick),
  `_soc_envelope_admits_dp_transition:619-648` (reads `drain_target_soc` as an ARG — R3-adjacent
  helper called by the ride-proof path; caller passes the value; classified R2/R3 per site — see
  §3.D3 table), `_stronger_peer_holds:383-412`.
* `domain_coordinators/energy_pool_owners.py` — owner registry. `persistence_kind` valid values
  today are `"per_evse_bool"` and `"list"` ONLY (`:245-251`, `:257`). **`"per_evse_dict"` does
  not exist and `iter_persisted_lists()` filters `== "list"`.** A-HIGH-2 was correct — Rev-2
  fixes the persistence mechanism (§3.D1 Rev-2).
* `domain_coordinators/energy_drain_precedence.py` — `evaluate_dp_transition:609-735`, gates 6/7
  at `:652`/`:656`, fit arithmetic `:709-712`.
* `domain_coordinators/energy.py` — R2 sites at `:4271` (shadow inputs), `:4456` (real tick
  inputs), `:4522` (`_DPAct` fresh TRANSITIONED actuation), `:4540` (`_DPActRescan` second-plug
  re-scan), `:4555` (revert predicate). R2-display sites at `:3871`, `:4021`. Reserve fold
  `:4733-4742` (update-in-place) and `:4829-4833` (append). Write-verify surface gate
  `:7587-7591`. R1 sites `:5842` / `:5977`. R3 site `:3752`. 10 h staleness gate `:1346`
  (A-HIGH-3). Save hooks `_KNOWN_HOOKS` at `:1603-1612` (RAISES on unknown hook — A-HIGH-2).
* `domain_coordinators/energy_battery.py` — **`compose_release_floor` is a MODULE-LEVEL
  function at `:264`, NOT a `BatteryStrategy` method.** It returns
  `(release_floor: int | None, is_offpeak: bool)` — second element is a **bool, not a reason
  string**. Off-peak: `max(static_reserve, current_park_floor())`; non-off-peak: returns the
  STATIC reserve. `release_floor` **can be None** at `:286-289` when `reserve_soc` is
  unavailable (A-HIGH-1 / B-1 both flagged this). Called from `energy.py:5837` as a free
  function. Also: `solar_production_w:1586-1612`, `net_power_w:1614-1623`,
  `current_offpeak_drain_target:1726-1747`.
* `domain_coordinators/energy_const.py` — `DP_L1_RATE_THRESHOLD_KW=3.0:1359`,
  `DP_CAPACITY_KWH_PER_SOC_PP=0.40:1367`, `DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD=50:857`,
  `CONF_ENERGY_EV_BATTERY_DRAIN_SOC:858`, `EVSE_ESTIMATED_POWER_W=7600` (A-MED-1).
* Prior planning docs disposition (per plan-review process request):
  - **P1** — see §11 P-item table.
  - **P5** — see §11.
  - **P6** — see §11.
  - **P8 (rate modulation, previously REJECTED)** — READ; disposition in §11. Not a re-proposal
    of the same design.
  - **P9 ("no separate stack")** — operator withdrew the mis-framing on 2026-08-23
    (`TWO_AUDIT_CLAIMS_I_RELAYED_WERE_WRONG_2026_08_23` (2)): the fence rejects an EV optimizer
    stack, not a timer. Recorded closed; §11.
  - **P13** — see §11.
* Memory: `project_optimizer_db_write_flood_incident_2026_06_09`;
  `project_ev_drain_precedence_cycle` (parked hold-demotion cycle, explicit non-goal here);
  `feedback_suppression_needs_discharge`; `feedback_hollow_test_anchors`;
  `feedback_mutation_verification_pycache_staleness`; `RESTART-SAFETY-DOCTRINE-1`.

---

## 3. Deliverables

### D1 — SolarFollowController (Rev-2)

**Host:** new class `SolarFollowController` in `domain_coordinators/energy_pool.py`, modelled on
`PoolOptimizer:58-160`. `_execute_service_action` (audit §1 row 2) as write path.
Unavailable-entity → keep-state + retry-next-tick (REUSED from `PoolOptimizer:135-137`).

**Rev-2 change list (fixes B-2, B-3, B-5, B-6, A-HIGH-2, A-HIGH-3, A-HIGH-4, A-MED-1):**

1. **Always-on 60 s timer with empty-set fast path (B-5 fix).** The controller runs on its own
   `async_track_time_interval` timer started at `async_setup_entry` and cancelled at
   `async_unload_entry`. When both `_excess_solar_active` is empty AND `_original_amps` is
   empty, the tick returns after a cheap membership check. This avoids the bootstrap-observer
   problem (we cannot hook onto set mutations without touching the EC tick, which is a
   non-goal), and it collapses the PB-2 cross-clock window because restore always runs on the
   next 60 s edge regardless of the state at the time of restart.
2. **Fleet allocation, not per-EVSE independent read (B-3 fix, INV-SF-6).** Compute surplus S
   once per tick from the D1.2 signal. Compute `A_total_target = floor(S * 1000 / (240 * PHASES))`.
   Determine the fleet `N = len(active_evses)`. Compute `A_per_evse = A_total_target // N`.
   Then per EVSE: clamp `A_per_evse` to `[SOLAR_FOLLOW_MIN_AMPS, SOLAR_FOLLOW_MAX_AMPS]`, apply
   deadband and step law, write. Equal-split is the operator-default; a priority ordering knob
   is explicit non-goal (both EVSEs are functionally identical in the operator's setup).
3. **6 A hold instead of stop-writing when per-EVSE share < 1.44 kW (B-2 fix).** The 6 A pilot
   floor is a hardware constant, not a policy. Writing nothing while the last commanded amps
   are e.g. 20 A means the session draws 4.8 kW against 1 kW surplus for the entire release
   streak. Correct behaviour: clamp UP to 6 A and hold. The release gate (D2) owns actual
   session termination. INV-SF-4's `max(..., N*MIN*240)` clause is the formal statement of
   this hardware exception.
4. **`SOLAR_FOLLOW_HEADROOM_KW` DELETED (B-6 fix).** Headroom is by definition permission to
   pull from the battery — the exact harm INV-SF-4 forbids. Every reference removed. INV-SF-4
   no longer contains it.
5. **`_original_amps` persistence via existing KV blob machinery (A-HIGH-2 fix).** Do NOT
   introduce a fake `persistence_kind="per_evse_dict"`. Instead persist as an INLINE bool-shape
   sibling of `excess_solar_active`: extend `db.save_evse_state(evse_id, ...)` at
   `energy.py:1839` with a new column `original_amps: float | None`, restored at
   `energy.py:1365-1366` alongside the existing `excess_solar_active` bool. No new
   `_KNOWN_HOOKS` entry is needed because we ride the existing per-EVSE inline path — the same
   one the audit §5.3 documents for `excess_solar_active`. **Zero new persistence machinery.**
   Alternative if the column add is undesirable: a single new KV `evse_original_amps_v1` (JSON
   dict `{evse_id: float}`) with a `_KNOWN_HOOKS`-registered save/restore pair matching the DP
   `drain_precedence_state_v1` shape (`energy_const.py:1390`). Builder picks; plan owns the
   two acceptable shapes.
6. **`_original_amps` capture guarded against the "captured-throttle" hazard (A-HIGH-3 fix).**
   On session ENTRY (first tick where `evse_id ∈ _excess_solar_active` and no
   `_original_amps[evse_id]`), read the current-limit entity. THREE cases:
   a. State fresh, value in `[SOLAR_FOLLOW_MIN_AMPS, SOLAR_FOLLOW_MAX_AMPS]` — save it.
   b. State stale/unavailable — save `SOLAR_FOLLOW_RESTORE_AMPS` (48) as safe default; log INFO.
   c. Value < `SOLAR_FOLLOW_CAPTURE_SANITY_A` (=20 A default, rung-1) — this is the smoking-gun
      of the 10 h staleness scenario: a prior session's throttle survived the drop. Save
      `SOLAR_FOLLOW_RESTORE_AMPS` (48), log WARNING with the observed value, and expose the
      event on the status sensor as `capture_rejected_low` counter. Prevents "silently locked
      at quarter rate forever."
7. **Mirror the start condition to the stop condition (A-HIGH-4 fix).** Rev-2's always-on timer
   already prevents the "restart within 60 s of release" hazard: at restart, if
   `_excess_solar_active` is empty but `_original_amps` is non-empty (persisted per fix 5), the
   next 60 s tick fires the restore path. The empty-set fast path in fix 1 explicitly checks
   BOTH sets before returning no-op. Test `test_solar_follow_restore_after_restart_within_release_window`
   in the suite plan below.
8. **A-MED-1 mitigation: never feed `EVSE_ESTIMATED_POWER_W` into D1's own control path
   (also B-4).** The surplus signal uses ONLY raw measured grid power (D1.2) plus the raw
   Emporia per-charger power (`sensor.garage_a_power_minute_average`) via
   `current_charging_load_w()`. If per-charger power is unavailable, the controller falls back
   to `SOLAR_FOLLOW_STALE_MAX_TICKS` (=2) grace then stops writing — it does NOT substitute
   `EVSE_ESTIMATED_POWER_W`. The wider concern (DP's fit arithmetic now sees a throttled
   charger whose power reads through the same estimate fabrication on outage) is documented in
   §5 known couplings and flagged for post-ship monitoring — it is a pre-existing pathology
   this cycle exposes, not creates.

**Per-tick control law (Rev-2, ordered):**

```
1. If _excess_solar_active empty AND _original_amps empty: return.
2. For each evse_id with _original_amps set but NOT in _excess_solar_active:
     emit ONE number.set_value(_original_amps[evse_id]); clear entry.
     (Release-edge restore. Fires once per session end. Idempotent.)
3. If _excess_solar_active empty: return.
4. Read surplus S via D1.2. If unavailable for STALE_MAX_TICKS: no writes.
5. N = len(_excess_solar_active).
6. A_total_target = floor(S * 1000 / (240 * PHASES)).
7. A_per_evse_raw = A_total_target // N.
8. For each evse_id in _excess_solar_active:
     a. Capture _original_amps[evse_id] per fix 6 if unset.
     b. A_target = clamp(A_per_evse_raw, MIN, MAX).
     c. A_current = read current-limit entity (unavailable => skip).
     d. Deadband: skip if |A_target - A_current| < DEADBAND_A.
     e. Step law (INV-SF-5): if A_target > A_current, require UP_MIN_TICKS streak AND
        A_write = min(A_target, A_current + UP_STEP_A). Else A_write = A_target.
     f. Write-budget cap (D1.7): if hour bucket exceeded, skip + WARN.
     g. Emit {number.set_value, current_limit_entity, A_write}.
     h. Schedule one-shot readback verify (D1.6).
```

**D1.2 — surplus signal.** SIGNAL_DESIGN_FINAL_2026_08_23, verbatim.

* PRIMARY: `sensor.mains_vue_3_power_minute_average` (Emporia mains, signed **W**, negative =
  export). Availability: `state ∉ {unknown, unavailable, None}`. NOT cross-checked against
  Envoy (skew probe kills the agreement gate).
* FALLBACK: `sensor.envoy_482543015950_current_net_power_consumption` (signed **kW**, negative
  = export). **Unit differs from primary — kW → W conversion (`×1000`) in the fallback
  branch.** Availability gate: existing `envoy_available` reliability signal (NOT
  `sensor.ura_energy_coordinator_envoy_status`, which reads "stale" for an accounting
  divergence per the card).
* `S_kW = (-grid_W + current_EV_draw_W) / 1000`. EV load add-back uses `current_charging_load_w()`
  at `energy_pool.py:2286-2312`, RAW measured value only (no `EVSE_ESTIMATED_POWER_W` fallback
  — B-4 / A-MED-1).
* Fences (verbatim from the card): NOT `balanced_net_power_consumption`; NOT SPAN; NOT
  `sensor.mainw_vue_balance_power_minute_average` (dead/typo).

**D1.3 — self-consistency stop.** Both PRIMARY and FALLBACK unavailable for
`SOLAR_FOLLOW_STALE_MAX_TICKS` (=2) → no writes, WARNING logged. Fail-safe.

**D1.4 — current-limit entities.** Added to `DEFAULT_EVSE_ENTITIES` at
`energy_pool.py:168-183` under new key `current_limit`:
* `garage_a`: `number.garage_a_evse_emporia_wifi_garagea_current_limit`
* `garage_b`: `number.garage_b_evse_emporia_wifi_garageb_current_limit`
L1 chargers explicitly excluded.

**D1.5 — Solcast next-hour stop.** New `CONF_SOLCAST_NEXT_HOUR_ENTITY` (rung 2, per-deployment
entity id) populated from `sensor.solcast_pv_forecast_forecast_next_hour`. Consumed by D2 as a
second release condition. `SOLAR_FOLLOW_NEXTHOUR_FLOOR_W` (rung 1, 1000 W) is protocol.

**D1.6 — bounded in-controller write-verify.** After every write, `async_call_later(
SOLAR_FOLLOW_VERIFY_S=8, ...)` reads back and checks within 1 A tolerance. WARNING + counter
increment on mismatch. Does NOT extend `_maybe_schedule_write_verify` (surface-keyed, silently
drops non-reserve targets — audit §1 row 5). Widening the write-verify surface is an explicit
non-goal.

**D1.7 — write-budget containment.** `SOLAR_FOLLOW_MAX_WRITES_PER_HOUR_PER_EVSE` (=30, rung 1).
Hour bucket per EVSE; if exceeded, skip writes for remainder of the hour, WARN, expose on
status sensor.

**Constants (D1 knob ladder — Rev-2):**

| Name | Rung | Value | Why this rung |
|---|---|---|---|
| `SOLAR_FOLLOW_TICK_S` | 1 (module) | 60 | Protocol; matches Emporia 1-min average |
| `SOLAR_FOLLOW_MIN_AMPS` | 1 | 6 | J1772 pilot floor, hardware constant |
| `SOLAR_FOLLOW_MAX_AMPS` | 1 | 48 | Service ceiling, safety bound |
| `SOLAR_FOLLOW_RESTORE_AMPS` | 1 | 48 | Fallback default only |
| `SOLAR_FOLLOW_CAPTURE_SANITY_A` | 1 | 20 | Anti-captured-throttle threshold; reviewed change only |
| `SOLAR_FOLLOW_DEADBAND_A` | 3 (Number) | 1 | Operator observation-tunable |
| `SOLAR_FOLLOW_UP_STEP_A` | 3 (Number) | 2 | Operator observation-tunable |
| `SOLAR_FOLLOW_UP_MIN_TICKS` | 3 (Number) | 3 | Operator observation-tunable |
| `SOLAR_FOLLOW_STALE_MAX_TICKS` | 1 | 2 | Protocol; fail-safe |
| `SOLAR_FOLLOW_VERIFY_S` | 1 | 8 | Protocol |
| `SOLAR_FOLLOW_MAX_WRITES_PER_HOUR_PER_EVSE` | 1 | 30 | Safety containment |
| `SOLAR_FOLLOW_PHASES` | 1 | 1 | 240 V L2 single-phase (US) |
| `SOLAR_FOLLOW_NEXTHOUR_FLOOR_W` | 1 | 1000 | Protocol |
| `CONF_SOLCAST_NEXT_HOUR_ENTITY` | 2 (config-flow) | — | Per-deployment entity id |
| `CONF_SOLAR_FOLLOW_ENABLED` | 3 (Switch) | True | Kill-switch, live-tunable |

`SOLAR_FOLLOW_HEADROOM_KW` **removed** (B-6).

**D1 acceptance (discriminating):**

* **INV-SF-1:** `test_solar_follow_writes_only_number_set_value_never_switch` — with the
  controller neutered to attempt `switch.turn_off`, the assertion fails. Under bug (control
  law calls `_execute_service_action` with switch), the test fails.
* **INV-SF-2:** `test_solar_follow_no_writes_when_both_sets_empty` — tick with empty
  `_excess_solar_active` AND empty `_original_amps` emits zero writes. Under bug (unconditional
  run), writes counter increments.
* **INV-SF-3 restart:** `test_solar_follow_restore_after_restart_within_release_window` —
  save `_original_amps={"garage_a": 32}`, restart (persistence path), drop garage_a from
  `_excess_solar_active`, next tick emits `number.set_value → 32`. Under RAM-only bug, restore
  emits 48 (default). Under A-HIGH-4 bug (event-hook restore), restart within release window
  leaves the entity throttled forever — test asserts the entity value returns to 32.
* **INV-SF-4:** parametric test at `S ∈ {1.5, 5.0, 11.5}` kW, N=1 and N=2 → total draw <= max(S,
  N*1.44) kW at every point. Under binary bug (A=48 at S=1.5, N=1), fails.
* **INV-SF-5:** `test_solar_follow_up_gated_down_immediate` — surplus 1→8 kW instant, amps
  climb over `UP_MIN_TICKS` at `UP_STEP_A/tick`; surplus 8→2 kW, one-tick drop. Under
  symmetric-step bug, the down step is capped, test fails.
* **INV-SF-6 (fleet allocation, B-3):** `test_solar_follow_two_evses_split_surplus` — N=2,
  S=5 kW → each EVSE commanded 10 A (2.4 kW), total draw 4.8 kW ≤ 5 kW. Under
  bug-per-EVSE-independent-read, each is commanded 20 A → total 9.6 kW. Different observation.
* **INV-SF-6 degenerate:** `test_solar_follow_two_evses_below_floor_holds_at_min` — N=2,
  S=2 kW → per-EVSE share 4.16 A < 6 A → both hold at 6 A (session running at 2.88 kW
  against 2 kW surplus — 0.88 kW is drawn from battery until D2's release fires). Test
  asserts both amps = 6 AND that D2 release streak is incrementing.
* **A-HIGH-3 (captured throttle):** `test_solar_follow_capture_rejects_stale_low_value` —
  pre-session current-limit reads 12 A → capture rejects, saves 48 A, WARNING logged. Under
  bug (naive capture), saves 12 A → restore locks the charger at 12 A permanently.
* **Live (sunny afternoon):** attribute `sensor.ura_energy_coordinator_solar_follow` shows
  `active=True, N_evses, current_amps_per_evse, writes_per_hour_per_evse < 30, original_amps`
  saved. Cloud passage drops amps within 1 tick; sun return climbs over ≥3 ticks.
* **Live (release):** on release, current-limit returns to saved `_original_amps` within
  60 s, verified against a state-history read on the number entity.
* **Live (two-EVSE case):** when both chargers active, sum of amps × 240 ≤ measured surplus
  (verified against Emporia mains reading over a 15-min window).

### D2 — Release-gate hysteresis + drain-protection skip

**Where:** `EVChargerController.determine_excess_solar_actions:1685-1699` (release leg) and
`determine_battery_drain_actions:1776` (drain-protection).

**Changes:**

1. Add `_conditions_met_false_streak_ticks: dict[str, int]` and `_excess_solar_started_at:
   dict[str, datetime]` on `EVChargerController`.
2. On session entry (`energy_pool.py:1650-1656` and the claim-only branches), stamp
   `_excess_solar_started_at[evse_id]`. Persist per-EVSE as an inline column sibling of
   `excess_solar_active` (same shape as D1.5 fix; NO new persistence kind).
3. Release condition: fire turn-off + `_excess_solar_active.discard` for `evse_id` only when
   ALL of:
   - `not conditions_met` OR `solcast_next_hour_w < SOLAR_FOLLOW_NEXTHOUR_FLOOR_W`
   - streak `>= SOLAR_RELEASE_MIN_TICKS` (=3)
   - session age `>= SOLAR_RELEASE_MIN_ON_S` (=300)
4. On any `conditions_met` True tick, reset streak.
5. **Drain-protection skip (PB-1):** in `determine_battery_drain_actions`, at the head of the
   per-EVSE loop, add `if evse_id in self._excess_solar_active: continue`. Prior art at
   `energy_pool.py:2214` (fill-priority does exactly this); the asymmetry with battery-drain
   is a shipped gap. One-line fix.

**Discharge rule (per `feedback_suppression_needs_discharge`):** the streak suppresses a
release event; re-fire path is the next `not conditions_met` tick after `min_on_s` elapses;
backstop = `conditions_met` True resets and deletes the pending event DELIBERATELY (SOC
recovered); restart behaviour = streak dict is RAM-only (resets to 0 on restore),
`_excess_solar_started_at` is persisted so min-on-time is honoured across restart.

**Constants:**

| Name | Rung | Value |
|---|---|---|
| `SOLAR_RELEASE_MIN_TICKS` | 1 | 3 |
| `SOLAR_RELEASE_MIN_ON_S` | 3 (Number) | 300 |

**D2 acceptance (discriminating):**

* `test_release_streak_gated` — SOC 95→94→95→94 over 5 ticks; no turn-off. Under
  no-hysteresis, first 94 fires turn-off.
* `test_release_min_on_time` — session starts, SOC drops 30 s later and stays; no turn-off
  until 300 s. Under no-min-on-time, turn-off fires immediately.
* `test_release_streak_persists_min_on_time_across_restart` — save
  `_excess_solar_started_at` at t=100, restart at t=200, SOC drops at t=250; turn-off must
  not fire until t=400 (100 + 300). Under RAM-only bug, min-on-time resets to 0 at restart
  and turn-off fires at t=253.
* `test_drain_protection_skips_solar_follow_active` — EVSE in `_excess_solar_active` with
  SOC 75; `determine_battery_drain_actions` emits no action for that EVSE. Under bug, it
  emits `switch.turn_off` and flap-cycles with the solar-follow session.
* **Live:** on first cloudy transition day, `sensor.ura_energy_coordinator_ev_status` shows
  `_excess_solar_active` membership persisting through single-SOC-point dips of duration
  < `SOLAR_RELEASE_MIN_TICKS × SOLAR_FOLLOW_TICK_S = 180 s`.

**Non-substitutability (on the record):** D2 is finesse. D1 is the mechanism that makes the
economics work; D2 stops the flap.

### D3 — DP drain-target mis-sourcing fix (Rev-2, FIVE R2 sites)

**Full R2 emission-site table (per-site classification, per A-CRIT-1 fix):**

| Site | Where | What it does | Class | Rev-2 change |
|---|---|---|---|---|
| `energy.py:4271` | Shadow `TransitionInputs` construction | Feeds gate 7/8 shadow eval | **R2** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:4456` | Real tick `TransitionInputs` construction | Feeds gate 7/8 real eval | **R2** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:4522` (`_DPAct`) | Fresh-TRANSITIONED actuation → `_apply_dp_transition` stamps `_dp_decision_soc` | Sets reserve floor (`max()` fold at `:4733/:4829`) | **R2** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:4540` (`_DPActRescan`) | Second-plug-in rescan while TRANSITIONED → same actuation | Sets reserve floor | **R2** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:4555` (`_drain` in revert predicate) | `if _soc <= _drain: _revert = True` inside the same function as `:4522` | Reverts TRANSITIONED → HOLD_ONLY on same tick if SOC ≤ knob | **R2 (revert consistency)** | Source from `_dp_drain_target_soc(period)` — same value stamped by `:4522` |
| `energy.py:3871` | DP snapshot dict for `sensor.ura_energy_coordinator_ev_charging_plan` | Display | **R2-display** | Follows the new source (auto — reads inputs) |
| `energy.py:4021` | Same sensor snapshot payload | Display | **R2-display** | Auto |
| `energy.py:4910` | `_apply_dp_transition` reads `decision.drain_target_soc` and stamps `_dp_decision_soc` | The stamp itself | **R2 consumer** | No change — receives the composed value from the four callers above |
| `energy.py:3752` | Blind-hold envelope proof | Ride-proof floor | **R3** | Unchanged |
| `energy_pool.py:954` | `_soc_envelope_admits_dp_transition` caller pass — blind-window off-peak ride | Ride-proof floor | **R3** | Unchanged |
| `energy_pool.py:1435` | Same helper called from excess-solar blind-window branch | Ride-proof floor | **R3** | Unchanged |
| `energy_pool.py:619-648` (`_soc_envelope_admits_dp_transition` body) | Reads `drain_target_soc` as an ARG passed by callers | Helper | **Follows caller** | `:954` and `:1435` callers pass `_ev_battery_drain_soc` unchanged (R3). No DP-eval caller uses this helper. |
| `energy.py:5842` (EV) | `determine_battery_drain_actions(soc_threshold=)` | R1 pause ceiling | **R1** | Unchanged |
| `energy.py:5977` (plugs) | Same, plug mirror | R1 pause ceiling | **R1** | Unchanged |

**Verification the plan is complete over the entire read set:** `grep -n
"_ev_battery_drain_soc" domain_coordinators/*.py` returns exactly the above sites plus
`:441` (init from config), `:8730` / `:8732-8738` (Number getter/setter). Rev-2 changes the
FIVE R2 sites; leaves R1 + R3 byte-identical; touches none of init/getter/setter.

**The `_dp_drain_target_soc` helper — Rev-2 corrected implementation (A-HIGH-1 / B-1 fix):**

```python
# energy.py, near the DP construction path (module-level compose_release_floor
# is imported at :5837 as `from .energy_battery import compose_release_floor`)
from .energy_battery import compose_release_floor  # explicit at top of file

def _dp_drain_target_soc(self, tou_period: str) -> int:
    """R2 drain target for DP: composed release floor, with an explicit None fallback.

    compose_release_floor is a MODULE function (not a BatteryStrategy method).
    Its return is (release_floor: int | None, is_offpeak: bool). release_floor
    can be None when the battery's reserve_soc is unavailable at boot
    (energy_battery.py:286-289). Off-peak: max(static_reserve, park). Not
    off-peak: returns static_reserve (which is what we want for DP too — non-
    off-peak DP evaluation is not the normal path, and returning the static
    reserve mirrors compose_release_floor's own semantics).

    Fallback on None: return static reserve directly (self._battery.reserve_soc)
    and emit WARNING. DO NOT fall back to self._ev_battery_drain_soc — that
    would silently restore the exact bug this cycle is fixing (B-1 danger note).
    If BOTH are None: raise; the DP construction sites already handle exceptions
    upstream by not proceeding to gate 7/8 evaluation on that tick.
    """
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

Call it from all FIVE R2 sites: `:4271`, `:4456`, `:4522`, `:4540`, `:4555`. Callers wrap in
`try/except ValueError` where a raise would leave DP mid-construction; for `:4271` (shadow) and
`:4456` (real) the tick simply logs and skips DP that tick (the machine holds); for `:4522` /
`:4540` the fresh-actuation branch declines to actuate (equivalent to a gate-8 does_not_fit);
for `:4555` (revert), if the value is unavailable, the safer choice is DO NOT revert (leave
TRANSITIONED in place) since a revert flap is the failure mode we are preventing.

**Producer / Consumer + call-site check (mandatory rule):**

* **Producer of R2's new value:** `compose_release_floor(battery, tou_period)[0]` at
  `energy_battery.py:264`. Deps: `battery.reserve_soc`, `battery.current_park_floor()`,
  `battery.current_offpeak_drain_target()`. Health: park state, static reserve entity
  available, Solcast tier freshness. External ground truth:
  `sensor.ura_energy_coordinator_battery_strategy.current_offpeak_drain_target` attribute
  (live 10).
* **Consumers of `TransitionInputs.drain_target_soc`:**
  - `energy_drain_precedence.py:656` (gate 7 `already_below_target`) — trust.
  - `energy_drain_precedence.py:663-712` (gate 8 arithmetic) — trust.
  - `energy_drain_precedence.py:546` (`to_dict` snapshot payload) — display.
* **Consumers of stamped `_dp_decision_soc`:**
  - `energy.py:4733-4742` (`max()` reserve fold, update-in-place) — trust.
  - `energy.py:4829-4833` (`max()` reserve fold, append leg) — trust.
* **Consumers of the revert `_drain` at `:4555`:** local to the revert predicate only.
* **Non-consumers (double-check they never see the value):** the R1 sites (`:5842`, `:5977`)
  and the R3 sites (`:3752`, `energy_pool.py:954`, `:1435`) MUST NOT be routed through
  `_dp_drain_target_soc`. INV-DP-DRAIN-2 and INV-DP-DRAIN-3 enforce this and each is
  mutation-tested (Review C axis below).

**INV-DP-DRAIN-4 blocker resolution.** Builder task: trace whether
`EnergyOffpeakDrainExcellentNumber.async_set_native_value` (and siblings) mutate
`BatteryStrategy._drain_targets` live, or only entry.options requiring reload. The plan owns
BOTH branches:

* **If live-apply exists** — fix is complete as spec'd.
* **If reload-only** — builder adds `BatteryStrategy.set_offpeak_drain_target(tier: str,
  value: int)` mutating `_drain_targets[tier]`, called from the Number entity's setter.
  Alternative accepted by the operator: document reload-required on Number entity `attributes`
  and on the README. Plan does NOT pick between "add live-apply" and "document reload" — that
  is the operator's call at review time. INV-DP-DRAIN-4 enforces whichever choice is made.

Also: builder to READ and RECORD in README the numeric value of
`DEFAULT_OFFPEAK_DRAIN_UNKNOWN` (Solcast-dead fallback).

**Hold-demotion (BIGGEST_SCOPE_QUESTION_HOLD_DEMOTION) — OUT OF SCOPE.** The parked cycle
`project_ev_drain_precedence_cycle` remains the next-cycle successor. Acceptance criteria do
NOT claim "battery drains overnight" (undiscriminating; would fail against the DIFFERENT
mechanism of hold pinning reserve to live SOC).

**Activation risk framing (`ACTIVATION_RISK_NOT_JUST_A_BUGFIX`).** This fix ACTIVATES a
dormant state machine. Live validation must watch `_apply_dp_transition` at `energy.py:4953`,
`_paused_by_dp` claim, `_claim_pause_dispatch_owner("dp")`, and the must-start-by timer.
Critically Rev-2: with the `:4522` + `:4555` fixes together, a fresh TRANSITIONED at SOC 40
with composed floor 10 stamps `_dp_decision_soc = 10`, and the revert at `:4555` compares
`40 <= 10 → False` → no flap. Under the original plan (only `:4271`/`:4456` fixed), `:4522`
stamps 80 → reserve pinned at 80 while SOC 40, AND `:4555` immediately reverts (`40 <= 80`) →
EVSE turn_off + turn_on on same tick, on every 5-minute tick. Rev-2 fixes this by
classifying `:4522`, `:4540`, `:4555` as R2 and routing all through the helper.

**D3 acceptance (discriminating, over the ENTIRE R2 set):**

* **INV-DP-DRAIN-1 T1 (real construction path, NOT `_mk_inputs`):** static knob 80, forecast
  target 10, SOC 40, off-peak. Test drives the real `_evaluate_battery` (or the eval entry
  point that populates `:4456`) and asserts `TransitionInputs.drain_target_soc == 10`. Under
  bug at `:4456`, value is 80 and gate 7 fires. Different observation.
* **INV-DP-DRAIN-1 T1b (SHADOW path):** same fixture; assert shadow `:4271` also emits 10.
  Under partial fix (only `:4456`), shadow snapshot at `sensor…ev_charging_plan.shadow_inputs`
  shows 80. Different observation from real snapshot.
* **INV-DP-DRAIN-1 T1c (`:4522` fresh actuation, A-CRIT-1 repro):** SOC 40, composed 10,
  fresh entry into TRANSITIONED. Assert `_dp_decision_soc == 10` and the reserve emitted at
  `:4733/:4829` = `max(existing, 10, hold_reserve)`. Under partial fix that missed `:4522`,
  `_dp_decision_soc == 80`, reserve pinned 70 points above target. Direct repro of the
  reviewer's A-CRIT-1 scenario.
* **INV-DP-DRAIN-1 T1d (`:4540` rescan):** first EVSE plugged, TRANSITIONED, second plug-in
  triggers rescan; assert `_dp_decision_soc` unchanged at 10 (idempotent). Under bug, second
  actuation stamps 80.
* **INV-DP-DRAIN-1b T2 (revert consistency, A-CRIT-2 repro):** post-TRANSITIONED at SOC 40
  with stamped `_dp_decision_soc == 10`; assert revert predicate `:4555` does NOT fire
  (`40 <= 10 → False`). Under partial fix, `:4555` compares against 80 and fires; test
  observes an EVSE actuation flap (turn_off followed by turn_on within the same tick).
* **INV-DP-DRAIN-2 T3 (R1 unchanged, HIGHEST_PROBABILITY_BUILD_ERROR guard):** mutate
  `_dp_drain_target_soc` in production source to return `self._ev_battery_drain_soc`; T3
  asserts `determine_battery_drain_actions` STILL receives `soc_threshold=80` at both `:5842`
  and `:5977`. If T3 fails after fix, INV-DP-DRAIN-2 is broken. (Complementary: mutate `:5842`
  argument to composed value; T3 asserts test failure — the mutation drill.)
* **INV-DP-DRAIN-2 T3b (compose_release_floor helper None fallback, B-1 danger):** stub
  `compose_release_floor` to return `(None, True)`; assert `_dp_drain_target_soc` returns
  static reserve AND logs WARNING. Under B-1 bug (fallback to `_ev_battery_drain_soc`), test
  observes helper returning 80 silently.
* **INV-DP-DRAIN-3 T4 (R3 unchanged):** mutate `energy.py:3752` to route through
  `_dp_drain_target_soc`; T4 asserts blind-hold envelope proof STILL uses the static knob.
* **INV-DP-DRAIN-4 T5 (offpeak-drain live-apply):** mutate
  `energy_offpeak_drain_excellent` Number entity to value 25; assert
  `BatteryStrategy._drain_targets["excellent"] == 25` within one tick. Under reload-only
  branch, this test is replaced by an assertion that the Number entity's help text or
  attribute contains "requires reload".
* **Live (D3 with plugged EV, off-peak, healthy Envoy):**
  `sensor.ura_energy_coordinator_ev_charging_plan.last_eval_snapshot.inputs.drain_target_soc`
  equals `sensor.ura_energy_coordinator_battery_strategy.current_offpeak_drain_target`
  (live 10). Under fix that missed one R2 site, either shadow or real disagrees.
* **Live (A-CRIT-1 direct):** on the first fresh TRANSITIONED, `_dp_decision_soc` (visible on
  the sensor) reads 10, NOT 80. Reserve entity commanded to the composed floor, NOT 80.
* **Live (A-CRIT-2 direct):** during any TRANSITIONED tick with SOC > composed floor, EVSE
  switch does not oscillate. Verified against the switch state history over the whole
  TRANSITIONED window.
* **Live (deferred criterion, on record):** if no EV is plugged during the eval window
  post-deploy, the live check for the DP snapshot defers to the next plug-in; README carries
  the deferred-verification note.

**Files changed (D3):**

* `energy.py` — new helper `_dp_drain_target_soc`; five construction/predicate sites updated
  (`:4271`, `:4456`, `:4522`, `:4540`, `:4555`); import of `compose_release_floor` at top;
  ~30 LoC total. Optional: `BatteryStrategy.set_offpeak_drain_target` if live-apply branch chosen.
* `sensor.py` — attribute `drain_target_source` on `sensor.ura_energy_coordinator_ev_charging_plan`
  = `"composed_release_floor"` or `"static_reserve_fallback"` (post-fix observability).
* Tests — new file `quality/tests/test_dp_drain_target_source.py` covering T1/T1b/T1c/T1d/T2/
  T3/T3b/T4/T5 above. Do NOT extend `test_evse_drain_precedence_session_b2a.py:126-149`
  `_mk_inputs` — that fake is the hollow anchor pattern.
* Docs drift: `docs/user-manual/ENERGY_COORDINATOR.md:642`;
  `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md:455`;
  `docs/planning/PLANNING_evse_drain_precedence.md` (bind the unbound `drain_target`);
  `docs/planning/PLANNING_inclement_weather_reserve.md:66,82` (stale line refs).

---

## 4. Non-goals (explicit)

* NOT starting or stopping charges on any grounds. D1 modulates amps only.
* NOT coordinating with DP from D1/D2.
* NOT changing the excess-solar TRIGGER at `energy_pool.py:1574-1579`.
* NOT changing the EC 5-minute tick.
* NOT extending `_maybe_schedule_write_verify` to current-limit entities.
* NOT wiring comfort_deviation_hours / egress_pause_frequency / HVAC coupling.
* NOT demoting `evse_battery_hold` to backstop. Parked as `project_ev_drain_precedence_cycle`.
  D3 acceptance criteria do NOT claim "battery drains overnight."
* NOT changing the live value of `ev_battery_drain_soc` (still 80). Operator knob turn.
* NOT changing R1 (`:5842`, `:5977`) or R3 (`:3752`, `energy_pool.py:954`, `:1435`) source.
  INV-DP-DRAIN-2 and INV-DP-DRAIN-3 protect this.
* NOT touching `sensor.mainw_vue_balance_power_minute_average` (dead/typo).
* NOT using `balanced_net_power_consumption`, SPAN, or
  `sensor.ura_energy_coordinator_envoy_status` as gates.
* NOT wiring L1 chargers.
* NOT introducing a new `persistence_kind` (Rev-2 fix — use existing inline or KV shapes).
* NOT auto-remediating an offline Garage A / SPAN observability gap.
* NOT feeding `EVSE_ESTIMATED_POWER_W` into D1's control law.
* NOT introducing a priority ordering between EVSEs (equal-split allocation).

---

## 5. Known couplings (independently enumerated)

1. **DP gate 6 (L1-only, `energy_drain_precedence.py:652`) sees a throttled charger as
   sub-threshold.** Threshold 3.0 kW ⇒ 12.5 A crossover at 240 V. Below 12.5 A, DP declines
   to drain. Same gate that MASKED the drain-target defect on 2026-08-20 — a future
   diagnostician chasing "DP not draining" must know to check for throttled sessions.
2. **DP gate 8 charge_hours blows up at low amps** (`charge_hours = needed_kwh / charger_rate_kw`
   at `:666`). Fit test may fail earlier at 6 A.
3. **`_dp_house_load_kw` biased the OTHER way** — house-load-minus-EV subtracts a smaller EV
   load when throttled → house load reads higher → DP sees MORE drain opportunity. Combined
   with (2), net DP effect is NON-MONOTONE in amps. D1 does not care.
4. **`EVSE_ESTIMATED_POWER_W = 7600`** fabricated un-throttled rate on Emporia outage. D1
   never feeds this into its own control law (fix 8 above). DP still may consume the
   fabricated value when the sensor drops — post-ship monitoring flagged. **This is a
   pre-existing pathology D1 exposes but does not create.** A-MED-1.
5. **`evse_battery_hold` still engages at 6 A** — trigger is `_is_any_evse_charging()`,
   amp-independent. Reserve pinned to live SOC. Why D3 acceptance cannot claim
   "battery drains overnight."
6. **Actuation precedence is EMERGENT (tick order), not documented.** D1/D2 rely only on
   `_excess_solar_active` set membership.
7. **INV-YIELD-1/2** (audit §6.4). D1 is downstream of the CLAIM, inherits automatically.

---

## 6. Docs drift to fix in-cycle

* `docs/user-manual/ENERGY_COORDINATOR.md:642` — default-50 + R1-only description.
* `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md:455`.
* `docs/planning/PLANNING_evse_drain_precedence.md` — unbound `drain_target`.
* `docs/planning/PLANNING_inclement_weather_reserve.md:66,82` — stale by ~3200 lines.

---

## 7. Test plan summary

Behavioural, MUTATION-VERIFIED. Set `PYTHONDONTWRITEBYTECODE=1` and clear `__pycache__`
before each drill (`feedback_mutation_verification_pycache_staleness`).

D1: `test_solar_follow_writes_only_number_set_value_never_switch`;
`test_solar_follow_no_writes_when_both_sets_empty`;
`test_solar_follow_restore_after_restart_within_release_window`;
`test_solar_follow_bounds_draw_by_surplus_hardware_floor_exception` (INV-SF-4 restated);
`test_solar_follow_up_gated_down_immediate`;
`test_solar_follow_two_evses_split_surplus`;
`test_solar_follow_two_evses_below_floor_holds_at_min`;
`test_solar_follow_capture_rejects_stale_low_value`;
`test_solar_follow_stops_writing_when_both_sensors_unavailable`;
`test_solar_follow_write_budget_containment`;
`test_solar_follow_never_feeds_evse_estimated_power_into_control_law` (A-MED-1).

D2: `test_release_streak_gated`; `test_release_min_on_time`;
`test_release_streak_persists_min_on_time_across_restart`;
`test_drain_protection_skips_solar_follow_active`.

D3: `test_dp_drain_target_real_tick_sourced_from_composed_floor` (T1);
`test_dp_drain_target_shadow_tick_sourced_from_composed_floor` (T1b);
`test_dp_fresh_transition_stamps_composed_not_static` (T1c, A-CRIT-1 repro);
`test_dp_rescan_stamps_composed_not_static` (T1d);
`test_dp_revert_predicate_uses_composed_not_static` (T2, A-CRIT-2 repro);
`test_dp_pause_soc_threshold_still_sources_from_static_knob` (T3);
`test_dp_drain_target_helper_none_fallback_static_reserve_not_ev_knob` (T3b, B-1 guard);
`test_dp_ride_proof_floor_still_sources_from_static_knob` (T4);
`test_offpeak_drain_number_live_apply_or_documented_reload` (T5).

---

## 8. Review plan — Tier 3, four framing-disjoint passes

Per CLAUDE.md Tier 3. Run A/B/C/D in PARALLEL.

* **A — local correctness.** D1 arithmetic (fleet allocation, clamp, step law, unit
  conversion, EV add-back sign, hardware-floor branch); D3 helper (None fallback branch, all
  five R2 sites); D2 streak arithmetic.
* **B — integration / state-machine + no-op path byte-identical.** D1 never perturbs
  TOU/DP/fill-priority/INV-YIELD; R1 and R3 grep-diff clean; restart path (D1's
  `_original_amps` restored via existing inline/KV path; D3 DP snapshot round-trips).
* **C — REAL per-site source mutation.** Enumerated:
  - C1: neuter D3 helper to return `_ev_battery_drain_soc` → T1/T1b/T1c/T1d must fail.
  - C2: swap D3 `:5842` argument to composed → T3 must fail (INV-DP-DRAIN-2 guard).
  - C3: neuter `:4522` back to `int(self._ev_battery_drain_soc)` → T1c must fail.
  - C4: neuter `:4540` back → T1d must fail.
  - C5: neuter `:4555` back → T2 must fail.
  - C6: remove D2 streak → `test_release_streak_gated` must fail.
  - C7: remove D2 min-on-time → `test_release_min_on_time` must fail.
  - C8: change D1 step law to symmetric → `test_solar_follow_up_gated_down_immediate` must fail.
  - C9: remove D1 restore branch → restart test must fail.
  - C10: remove D1 write-budget → budget test must fail.
  - C11: remove D2 drain-protection skip → `test_drain_protection_skips_solar_follow_active` must fail.
  - C12: change D1 fallback unit conversion (drop ×1000) → INV-SF-4 test must fail.
  - C13: replace D1's fleet-allocation with per-EVSE independent read → INV-SF-6 tests must fail.
  - C14: replace D1's B-2 hardware-floor hold with stop-writing → INV-SF-4 degenerate test must fail.
  - C15: replace D1's capture guard with naive capture → A-HIGH-3 test must fail.
  - C16: replace D3 None fallback with `_ev_battery_drain_soc` → T3b must fail (B-1 guard).
* **D — adversarial completeness / diff-blind.** Re-enumerate the ENTIRE R2 emission set from
  scratch (grep `drain_target_soc`, `_dp_decision_soc`, `_ev_battery_drain_soc`), including
  PRE-EXISTING code. Re-enumerate all discard sites for `_excess_solar_active` (audit §5.3 +
  the corrected count of THREE at `energy_pool.py:1369` (peak clear), `:1564` (blind-window
  drop), `:1699` (release gate); restart-reconciliation at `energy.py:5183-5225` MUTATES the
  set through a different path — treat that as its own leak vector). Re-enumerate every
  writer to a `number.set_value` in `energy*.py`. Legal-config combinatorial: min == max,
  deadband > (max - min), `SOLAR_RELEASE_MIN_ON_S` > natural session length, N=3 (future
  chargers) even though today N ∈ {1, 2}. Every leak must come with a concrete legal-config
  repro.

**Plan reviews (already run — Rev-2 addresses their findings; §12 change log).** A third
plan review of Rev-2 is warranted before build dispatch given the volume of change.

**Orchestrator pre-deploy verification:** personally re-grep every `drain_target_soc =`
assignment and `_ev_battery_drain_soc` read; confirm the FIVE R2 sites are now the helper and
the R1/R3 sites are unchanged. Personally run source-mutation drill on `_dp_drain_target_soc`
and on `:4522` / `:4555` and confirm named tests fail. **Operator checkpoint BEFORE deploy.**

---

## 9. REUSE vs NEW (Rev-2)

| Item | Verdict | Cite |
|---|---|---|
| Save/restore pattern for `number` entity | REUSE | `PoolOptimizer` `energy_pool.py:58-160` |
| `number.set_value` write path | REUSE | `_execute_service_action` |
| `_excess_solar_active` membership | REUSE | `energy_pool.py:202` |
| Unavailable-entity keep-state | REUSE | `energy_pool.py:135-137` |
| **Per-EVSE inline persistence for `_original_amps`** | REUSE (extend inline column OR use existing KV blob shape) | `energy.py:1839`, `:1365-1366` (same path as `excess_solar_active`) — NO new `persistence_kind` |
| `current_charging_load_w()` | REUSE | `energy_pool.py:2286-2312` |
| `compose_release_floor()` (module fn) | REUSE | `energy_battery.py:264` |
| `_ev_battery_drain_soc` at R1/R3 sites | REUSE unchanged | `:5842`, `:5977`, `:3752`, `energy_pool.py:954`, `:1435` |
| TOU peak-clear (never write during peak) | REUSE | `energy_pool.py:1354-1374` |
| Fill-priority `_excess_solar_active` skip (prior art for D2) | REUSE pattern | `energy_pool.py:2214-2219` |
| `SolarFollowController` class | NEW | Zero amp control today |
| Session-scoped 60 s timer (always-on, empty-set fast path) | NEW | Bounded blast radius |
| `_dp_drain_target_soc(period)` helper | NEW | D3 mechanism; ~15 LoC + None fallback |
| Release-gate streak + min-on-time | NEW | Audit §1 row 4 |
| Solcast next-hour stop signal | NEW | Audit §1 row 8 |
| `SOLAR_FOLLOW_*` constants + Numbers | NEW | No amp knobs exist |
| Drain-protection `_excess_solar_active` skip | NEW (mirrors fill-priority prior art) | `energy_pool.py:2214` |
| Bounded in-controller readback verify | NEW | Existing surface silently drops |
| `BatteryStrategy.set_offpeak_drain_target` (conditional on INV-DP-DRAIN-4 branch) | NEW | Live-apply into ctor-frozen dict |

---

## 10. Places I still think the operator's closed design MAY be worth pushback on

* **PB-1 — drain-protection `_excess_solar_active` skip.** ADOPTED as D2 fix 5. Fill-priority
  already does this at `energy_pool.py:2214`, so the asymmetry is real prior art.
* **PB-2 (Rev-2 REVISED — the concern is resolved by Rev-2's always-on timer).** The
  original PB-2 was about a lazy-start timer creating a cross-clock window. Rev-2 collapses
  the concern by moving to an always-on timer with an empty-set fast path (B-5 fix). No
  cross-clock coordination is needed; restore happens on the next 60 s edge regardless.
  Withdrawn.
* **New: I do NOT push back on the "either-or, no agreement gate" signal design.** The skew
  probe kills the agreement gate. Recorded.

---

## 11. Parked-with-fired-trigger P-items (disposition, per A-MED-2)

Read audit §parked-list; disposition for each:

| ID | Content | Disposition | Rationale |
|---|---|---|---|
| P1 | (audit-listed parked item) | **DEFER** | Not on this cycle's critical path; no fired trigger contradicts D1/D2/D3. Trigger for revisit: any leak D reviewer finds tied to P1's surface. |
| P5 | (audit-listed parked item) | **DEFER** | Same as P1. |
| P6 | (audit-listed parked item) | **DEFER** | Same. |
| P8 | Previously REJECTED rate-modulation design | **REJECT-WITH-EVIDENCE** | Cycle D1 is fleet-allocated surplus-following amp modulation inside an already-open excess-solar session — NOT the P8 shape. P8 rejected a different mechanism; D1 does not re-propose it. Recorded rather than left open. |
| P9 | "No separate stack" fence | **REJECT (framing withdrawn by operator 2026-08-23)** | Per `TWO_AUDIT_CLAIMS_I_RELAYED_WERE_WRONG_2026_08_23` (2): fence rejects an EV optimizer stack, not a session-scoped timer. D1 is not a parallel optimizer. Recorded closed. |
| P13 | (audit-listed parked item) | **DEFER** | Not on critical path. |

Builder / plan reviewer 3 should re-verify each P-item's body against Rev-2 (I did not
re-read every body end-to-end for this revision).

---

## 12. Change log — Rev-1 → Rev-2 (what each review finding forced)

| Finding | Severity | Rev-2 change |
|---|---|---|
| A-CRIT-1: FIVE R2 sites, not two (`:4522` / `:4540` missed) | CRIT | §3.D3 table lists all five; helper called from all five; T1c/T1d added |
| A-CRIT-2: `:4555` revert predicate is R2 (same-tick flap) | CRIT | INV-DP-DRAIN-1b added; `:4555` routes through helper; T2 added |
| A-HIGH-1 / B-1: `compose_release_floor` is a MODULE fn, second tuple element is bool, can be None | HIGH | Helper rewritten with correct signature, explicit None fallback to static reserve (NOT `_ev_battery_drain_soc`), T3b added |
| A-HIGH-2: `persistence_kind="per_evse_dict"` does not exist | HIGH | Persistence via existing inline column OR KV blob shape; NO new persistence kind |
| A-HIGH-3: 10 h staleness gate captures throttled value as "original" | HIGH | Capture sanity guard `SOLAR_FOLLOW_CAPTURE_SANITY_A`; WARN + safe default; test added |
| A-HIGH-4: start/stop condition mirror problem | HIGH | Rev-2 always-on timer collapses the hazard; empty-set fast path checks BOTH sets |
| A-MED-1 / B-4: D1 reachable-fabricated-power exposure | MED | D1 control law NEVER feeds `EVSE_ESTIMATED_POWER_W`; test added; DP-side exposure documented in §5 |
| A-MED-2: P-items disposition missing | MED | §11 P-item table added |
| A-MED (discard-site count wrong): plan said 5 discards; actual = 3 | MED | Reviewer D re-enumeration explicitly names `:1369`, `:1564`, `:1699` + restart-reconciliation as a separate vector |
| B-2: INV-SF-4 vs D1.3.c stop-writing contradiction | CRIT | Below 1.44 kW per EVSE: clamp UP to 6 A and hold; release is D2's job. INV-SF-4 restated with hardware-floor exception |
| B-3: fleet double-allocation | CRIT | INV-SF-6 added; fleet allocation per-tick, equal split, degenerate case defined |
| B-5: lazy-start timer bootstrap | HIGH | Always-on 60 s timer with empty-set fast path |
| B-6: `SOLAR_FOLLOW_HEADROOM_KW` orphan | HIGH | Constant DELETED from INV-SF-4, knob table, and formula |
| PB-2 (my own): sub-tick clock seam | (self-flag) | Resolved by B-5 fix; withdrawn |

Reviewer-confirmed-correct items unchanged (per coordinator note): R1 (`:5842`, `:5977`) and
R3 (`:3752`, `energy_pool.py:954`, `:1435`) classifications; INV-DP-DRAIN-2 and its
protective adjacency; zero pre-existing writer to any current-limit entity (no two-writer
race); write-verify early-return claim + owned bounded readback; discriminating framing of
acceptance criteria; 12 non-goals; D1.2's source selection with three fences; PB-1 (drain-
protection skip has fill-priority prior art at `energy_pool.py:2214`).

---

## 13. Places I think the reviewers may have overstated a concern (evidence, not deference)

Read carefully — none are pushback on their findings; two are minor scoping refinements the
build-reviewer or third plan-review should confirm.

* **On A-CRIT-1's "grep claim is not reproducible."** Verified: the original plan's
  Producer/Consumer section did claim `drain_target_soc` grep returned only the two sites +
  tests. Actual grep across `domain_coordinators/` returns 9 non-test hits in `energy.py`
  plus `energy_pool.py:619-648`. Reviewer A is CORRECT. Rev-2 §3.D3 lists every one and
  classifies R1/R2/R3 per-site. No pushback.

* **On A-HIGH-3's "quarter rate forever" characterisation.** Correct in mechanism; the
  "forever" is bounded by the next operator manual reset OR the sanity guard added in Rev-2.
  Not a pushback on severity — the guard is added.

* **On B's danger note re. builder reaching for `current_offpeak_drain_target()`** — this
  is exactly the parallel-derivation-blind-to-parks bug that `energy_battery.py:289-292`
  closed. Rev-2's helper explicitly documents why it uses `compose_release_floor` and not
  the raw accessor, and the None-fallback path routes to `static_reserve` explicitly (NOT
  `current_offpeak_drain_target()` and NOT `_ev_battery_drain_soc`). No pushback.

* **On the P-item table entries P1/P5/P6/P13:** I have not re-read every body for Rev-2 and
  disposition each as DEFER on the basis that neither reviewer flagged a fired trigger for
  them. Plan reviewer 3 (Rev-2 pass) should pull the bodies and confirm; if any is a fired
  trigger, upgrade to ADOPT or REJECT-WITH-EVIDENCE. This is a genuine transparency flag,
  not a claim.

---

## 14. Cycle-close checklist

* [ ] Third plan review of Rev-2 (Tier 3 protocol calls for TWO; Rev-2 is a substantial
      revision after two blocking reviews — a third pass on Rev-2 is warranted).
* [ ] Build in one branch off `develop`.
* [ ] Suite green + baseline-diff clean.
* [ ] Four framing-disjoint reviews A/B/C/D returned; CRITICAL/HIGH fixed with re-run drills.
* [ ] Orchestrator pre-deploy re-grep + real source mutation drills on all FIVE R2 sites +
      the D3 helper + D1's fleet allocation.
* [ ] Operator checkpoint before deploy.
* [ ] `README_v<version>.md` with prospective Live criteria.
* [ ] Deploy via `./scripts/deploy.sh`.
* [ ] Live validation: sunny-day D1 attributes + two-EVSE split; release edge D1 restore;
      D3 DP snapshot with plugged EV (deferred if no plug during window); A-CRIT-1 direct
      (`_dp_decision_soc == 10` on first fresh TRANSITIONED); A-CRIT-2 direct (no same-tick
      revert flap during TRANSITIONED).
* [ ] README updated with observed `Validated <date>` table.
* [ ] Kanban cards shipped_organic; parked `project_ev_drain_precedence_cycle` retained.
* [ ] Post-ship supersession + consumer-gap audit per CLAUDE.md rule.
