# PLANNING — DP drain-target mis-sourcing fix

**Cycle name:** `dp-drain-target-mis-sourcing`
**Tier:** **Tier 3** (delicate shared-primitive fix; five R2 emission sites; value stamped
into the commanded Enphase reserve floor — cost and safety impact).
**Threads:** `energy`
**Cards:** `EVSE-DRAIN-PRECEDENCE-KNOB-80-1`
**Design source:** the card body (esp. `RE_VERIFIED_2026_08_23_card_stands_memory_was_stale`,
`SCOPING_2026_08_20_ONE_NUMBER_THREE_ROLES`, `RECOMMENDED_DESIGN_D_SPLIT_THE_ROLES`,
`ACTIVATION_RISK_NOT_JUST_A_BUGFIX`) and `docs/planning/AUDIT_excess_solar_and_evse_prior_art.md`.

**Provenance.** Extracted from the combined plan
`PLANNING_evse_solar_follow_and_dp_drain_target.md` (Rev-1..Rev-8) so this fix can ship on
its own. Operator ruling (2026-08-23): the DP fix has been stable since Rev-3 of the
combined plan while D1/D2 were still producing BLOCKING findings at Rev-8. The DP fix
addresses a live money-losing defect — the commanded reserve floor stamps at 80 while SOC
is 40, and DP has never transitioned in production. It should not ride behind a moving
design. This doc is complete on its own; a builder needs nothing from the solar-follow doc.

**Runtime relationship to solar-follow (informational, not a build dependency).**
Shipping this fix changes which drain target DP consumes, which changes when DP holds
EVSEs via `_paused_by_dp`. Solar-follow (separate cycle,
`PLANNING_evse_solar_follow_amps.md`) reads `_paused_by_dp` as part of its ELIGIBLE set
computation, but has no code dependency on this cycle. **Shipping THIS cycle FIRST is
preferable, not merely acceptable** — the solar-follow cycle then gets built and
live-validated against corrected DP behaviour rather than against a known-wrong drain
target that has never fired a transition.

---

## 1. Falsifiable invariants

Each stated as "under X, Y can never happen in ANY reachable path."

### INV-DP-DRAIN-1 (whole R2 emission set)
Under any config where `_dp_carrier.state ∈ {HOLD_ONLY, HOLD_PRE_EVAL, EVAL_TRANSITION}`,
and under any code path that populates `TransitionInputs.drain_target_soc` OR that stamps
a fresh `_dp_decision_soc` via `_apply_dp_transition`, the value used equals
`_dp_drain_target_soc(period)` (the composed release floor). Applies to ALL R2 sites
enumerated in §3.

### INV-DP-DRAIN-1b (revert predicate consistency)
Under any tick where the controller has just stamped `_dp_decision_soc = X`, the revert
comparison at `energy.py:4555` uses the SAME value X, not `_ev_battery_drain_soc`. This
prevents the "TRANSITIONED and immediately revert on same tick" flap.

### INV-DP-DRAIN-2 (R1 pause ceiling preserved)
Under any config, `determine_battery_drain_actions(soc_threshold=...)` at
`energy.py:5842` (EV) and `:5977` (plugs) sources from `self._ev_battery_drain_soc`
unchanged. This is the R1 protective ceiling — the deep-discharge backstop during
expensive-grid windows. Prevents the HIGHEST_PROBABILITY_BUILD_ERROR: a builder "making
it consistent" and collapsing `soc_low = soc < 10` would silently delete the deep-discharge
backstop.

### INV-DP-DRAIN-3 (R3 ride-proof floor preserved)
Under any config, `_ev_battery_drain_soc` remains the ride-proof floor at `energy.py:3752`
(blind-hold envelope proof), `energy_pool.py:954`, and `energy_pool.py:1435`
(`env_lower >= drain_target`). Byte-identical.

### INV-DP-DRAIN-4 (offpeak-drain live-apply or documented reload)
The four `energy_offpeak_drain_*` Number entities either live-apply into
`BatteryStrategy._drain_targets` (setter mutates the ctor-frozen dict at
`energy_battery.py:464`), or the reload-required constraint is documented on each entity's
help text AND on the cycle README. INV-DP-DRAIN-1's practical value depends on this.

Reviewer D writes a legal-config repro for any leak in any of the above.

---

## 2. Institutional context verified

Paths under `custom_components/universal_room_automation/domain_coordinators/`:

* `docs/planning/AUDIT_excess_solar_and_evse_prior_art.md` (all sections; DP mechanism
  in §6).
* `energy_drain_precedence.py` — `evaluate_dp_transition:609-735`; gates 6/7 at `:652` /
  `:656`; fit arithmetic `:709-712`; `TransitionInputs` dataclass; `try_transition` state
  machine; DP_KV persistence.
* `energy.py` — **R2 sites:** `:4271` (shadow `TransitionInputs` construction), `:4456`
  (real tick `TransitionInputs` construction), `:4522` (`_DPAct` fresh-TRANSITIONED
  actuation), `:4540` (`_DPActRescan` second-plug-in rescan while TRANSITIONED),
  `:4555` (revert predicate `_drain`). **R2-display:** `:3871`, `:4021` (sensor snapshot).
  **`_apply_dp_transition`** at `:4953` — reads `decision.drain_target_soc` and stamps
  `_dp_decision_soc`. **Reserve fold consumers:** `:4733-4742` (update-in-place `max()`),
  `:4829-4833` (append leg `max()`). **R1 sites:** `:5842` (EV drain-pause caller —
  `determine_battery_drain_actions(soc_threshold=self._ev_battery_drain_soc, ...)`),
  `:5977` (plug mirror). **R3 site:** `:3752` (blind-hold envelope proof reads
  `_ev_battery_drain_soc`). Init `:441` (from CONF), getter `:8730`, setter `:8732-8738`
  (Number entity slider path).
* `energy_pool.py` — R3 caller sites `:954` and `:1435` (both pass
  `_ev_battery_drain_soc` to `_soc_envelope_admits_dp_transition:619-648`; helper reads
  `drain_target_soc` as an ARG, so its classification follows its caller — DP eval
  callers pass the composed floor per this cycle, R3 callers pass the static knob
  unchanged).
* `energy_battery.py` — **`compose_release_floor` at `:264` is a MODULE-LEVEL function**
  (NOT a `BatteryStrategy` method). Returns `(release_floor: int | None, is_offpeak:
  bool)` — second element is a **bool**, not a reason string. Off-peak:
  `max(static_reserve, current_park_floor())` — reconciles static reserve + park state
  (arbitrage / attain parks, inclement partial holds). Non-off-peak: returns the STATIC
  reserve. **`release_floor` can be None at `:286-289`** when `reserve_soc` is
  unavailable (documented recurring boot condition). Called from `energy.py:5837` as a
  free function. Also: `current_offpeak_drain_target:1726-1747` (raw accessor,
  DELIBERATELY NOT used by this cycle's helper — see §3 helper docstring).
  `_drain_targets` frozen at ctor `:464`.
* `energy_const.py` — `DP_L1_RATE_THRESHOLD_KW=3.0` (`:1359`);
  `DP_CAPACITY_KWH_PER_SOC_PP=0.40` (`:1367`); `DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD=50`
  (`:857`); `CONF_ENERGY_EV_BATTERY_DRAIN_SOC` (`:858`); DP persistence key `:1390`;
  `DEFAULT_OFFPEAK_DRAIN_UNKNOWN` (builder task: record its numeric value in README).
* `sensor.py` — DP charging-plan sensor
  (`sensor.ura_energy_coordinator_ev_charging_plan`) emits `last_eval_snapshot.inputs.
  drain_target_soc` (display-only consumer; follows the new source automatically).
* `PLANNING_evse_drain_precedence.md` — the DP design doc with the **unbound `drain_target`
  symbol** (Producer-check plan gap; this cycle binds it in §6 docs drift).
* Live values relevant to acceptance criteria:
  `number.ura_energy_coordinator_ev_battery_drain_soc = 80` (static knob);
  `sensor.ura_energy_coordinator_battery_strategy.current_offpeak_drain_target = 10`
  (forecast-based, live). The two differ by 70 SOC points — this is the money-losing gap.
* Memory: `project_ev_drain_precedence_cycle` (parked hold-demotion cycle, explicitly
  non-goal here); `feedback_hollow_test_anchors`;
  `feedback_mutation_verification_pycache_staleness`.

---

## 3. Deliverable

### Full R2 emission-site table (per-site classification)

| Site | Where | What it does | Class | Change |
|---|---|---|---|---|
| `energy.py:4271` | Shadow `TransitionInputs` construction | Feeds gate 7/8 shadow eval | **R2** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:4456` | Real tick `TransitionInputs` construction | Feeds gate 7/8 real eval | **R2** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:4522` (`_DPAct`) | Fresh-TRANSITIONED actuation → `_apply_dp_transition` stamps `_dp_decision_soc` | Sets reserve floor via `max()` fold at `:4733/:4829` | **R2** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:4540` (`_DPActRescan`) | Second-plug-in rescan while TRANSITIONED | Sets reserve floor | **R2** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:4555` (`_drain`) | `if _soc <= _drain: _revert = True` in the same function as `:4522` | Reverts TRANSITIONED → HOLD_ONLY on same tick if SOC ≤ value | **R2 (revert consistency)** | Source from `_dp_drain_target_soc(period)` — same value stamped by `:4522` |
| `energy.py:3871` | DP snapshot dict for `sensor…ev_charging_plan` | Display | **R2-display** | Auto (reads inputs) |
| `energy.py:4021` | Same sensor snapshot payload | Display | **R2-display** | Auto |
| `energy.py:4910` | `_apply_dp_transition` reads `decision.drain_target_soc` and stamps `_dp_decision_soc` | The stamp itself | **R2 consumer** | No change — receives the composed value from the four upstream callers |
| `energy.py:3752` | Blind-hold envelope proof | Ride-proof floor | **R3** | Unchanged (INV-DP-DRAIN-3) |
| `energy_pool.py:954` | `_soc_envelope_admits_dp_transition` caller pass — blind-window off-peak ride | Ride-proof floor | **R3** | Unchanged |
| `energy_pool.py:1435` | Same helper called from excess-solar blind-window branch | Ride-proof floor | **R3** | Unchanged |
| `energy_pool.py:619-648` (helper body) | Reads `drain_target_soc` as an ARG | Follows caller | **Follows caller** | R3 callers unchanged |
| `energy.py:5842` (EV) | `determine_battery_drain_actions(soc_threshold=)` | R1 pause ceiling | **R1** | Unchanged (INV-DP-DRAIN-2) |
| `energy.py:5977` (plugs) | Plug mirror | R1 pause ceiling | **R1** | Unchanged |

**Verification the plan is complete over the entire read set.** `grep -n
"_ev_battery_drain_soc" domain_coordinators/*.py` returns exactly the above sites plus
`:441` (init from config), `:8730` / `:8732-8738` (Number getter/setter). This cycle
changes the FIVE R2 sites; leaves R1 + R3 byte-identical; touches none of
init/getter/setter.

### The `_dp_drain_target_soc` helper (A-HIGH-1 / B-1 correctly closed)

```python
# energy.py, near the DP construction path
from .energy_battery import compose_release_floor  # explicit at top of file

def _dp_drain_target_soc(self, tou_period: str) -> int:
    """R2 drain target for DP: composed release floor, with an explicit None fallback.

    compose_release_floor is a MODULE function (NOT a BatteryStrategy method).
    Return is (release_floor: int | None, is_offpeak: bool). release_floor can
    be None when battery.reserve_soc is unavailable at boot
    (energy_battery.py:286-289) — a documented recurring condition. Off-peak:
    max(static_reserve, current_park_floor()). Not off-peak: returns static_reserve.

    Fallback on None: return static reserve directly (self._battery.reserve_soc)
    and emit WARNING. DO NOT fall back to self._ev_battery_drain_soc — that
    would silently restore the exact bug this cycle is fixing (B-1 danger).
    If BOTH are None: raise; construction sites handle by skipping this tick.

    Why compose_release_floor and not the raw current_offpeak_drain_target()
    accessor: the composed helper already reconciles static reserve +
    current_park_floor() (arbitrage/attain parks, inclement partial holds).
    Using the raw accessor would re-introduce the parallel-derivation-blind-
    to-parks bug that energy_battery.py:289-292 closed. This is the single
    most important design call in the cycle.
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

Callers wrap `ValueError`:
- `:4271` (shadow) and `:4456` (real tick): skip DP that tick, log; the state machine
  holds.
- `:4522` (fresh actuation) and `:4540` (rescan): decline to actuate (equivalent to a
  gate-8 does_not_fit).
- `:4555` (revert): does NOT revert on unavailable value — leave TRANSITIONED in place.
  Revert flap is the failure mode we prevent; erring toward not-reverting is safer than
  reverting on stale data.

### Producer / Consumer + call-site check (mandatory rule)

* **Producer of R2's new value:** `compose_release_floor(battery, tou_period)[0]` at
  `energy_battery.py:264`. Dependencies: `battery.reserve_soc`,
  `battery.current_park_floor()`, `battery.current_offpeak_drain_target()`. Health checks:
  park state, static reserve entity available, Solcast tier freshness. External ground
  truth for live validation:
  `sensor.ura_energy_coordinator_battery_strategy.current_offpeak_drain_target` attribute
  (live 10).
* **Consumers of `TransitionInputs.drain_target_soc`:**
  - `energy_drain_precedence.py:656` (gate 7 `already_below_target`) — trust-decision.
  - `energy_drain_precedence.py:663-712` (gate 8 fit arithmetic) — trust-decision.
  - `energy_drain_precedence.py:546` (`to_dict` snapshot payload) — display-only.
* **Consumers of stamped `_dp_decision_soc`:**
  - `energy.py:4733-4742` (`max()` reserve fold, update-in-place) — trust; feeds the
    commanded Enphase reserve floor.
  - `energy.py:4829-4833` (`max()` reserve fold, append leg) — trust.
* **Consumers of the revert `_drain` at `:4555`:** local to the revert predicate only.
* **Non-consumers (mutation-tested to stay non-consumers):** R1 sites (`:5842`, `:5977`)
  and R3 sites (`:3752`, `energy_pool.py:954`, `:1435`) MUST NOT be routed through
  `_dp_drain_target_soc`. INV-DP-DRAIN-2 and INV-DP-DRAIN-3 enforce this; each is
  mutation-tested.

### INV-DP-DRAIN-4 — RESOLVED 2026-08-23 by code read. NOT a blocker, no operator decision.

Prior revisions carried this as an open blocker with two branches and an "operator picks at
review time" note. It needed neither — one trace settled it. **The live-apply path already
exists and is already correct.**

Chain, verified end to end:

1. `number.py` — the off-peak drain Number's `async_set_native_value` calls
   `energy.set_offpeak_drain(self._quality, int(value))` **BEFORE** the `entry.options`
   writeback. The in-source comment states the intent explicitly: *"Live-attr push via EC
   setter BEFORE async_update_entry so the next decision cycle picks up the new value even
   if the listener is still in flight."*
2. `energy.py:8645-8653` — `EnergyCoordinator.set_offpeak_drain(quality, value)` validates
   `quality` against `{excellent, good, moderate, poor}`, then does
   `self._battery._drain_targets[quality] = value`, logs at INFO, and calls
   `_check_threshold_ladder()`.
3. So `_drain_targets` — ctor-frozen at `energy_battery.py:464-465` — IS mutated live, and
   the ladder validator runs on every change.

Consequences for this cycle:

* **No builder task.** Do not add `BatteryStrategy.set_offpeak_drain_target`; it would
  duplicate `EnergyCoordinator.set_offpeak_drain`. Do not document reload-required — it is
  not required and documenting it would be false.
* **No operator decision.** Both branches are moot.
* INV-DP-DRAIN-4 is retained as a REGRESSION GUARD, not an open question: the live-apply
  chain must remain intact post-cycle. Anchor it with a mutation drill — neuter the
  `energy.set_offpeak_drain(...)` call in the Number setter (leaving only the options
  writeback) and assert a test fails, proving the live-apply leg is load-bearing rather
  than incidentally passing because a reload happened to occur in the fixture.
* The `__init__.py:5863-5867` reload-suppress listing was a correct hint, and the earlier
  note that it "SUGGESTS a live-apply path exists but does not confirm it" was the right
  posture — the confirmation is now recorded above with file:line so no future revision
  re-derives it.

Also: builder to READ and RECORD in README the numeric value of
`DEFAULT_OFFPEAK_DRAIN_UNKNOWN` (Solcast-dead fallback).

### Hold-demotion — OUT OF SCOPE

`evse_battery_hold` pins the battery reserve to LIVE SOC while an EV is charging. Its
value composes into the reserve fold via `max()` at `energy.py:4733-4742` and `:4829-4833`.
Because `hold_reserve == live SOC` and `dp_decision_soc = composed_floor` (typically 10),
`max(SOC, 10) = SOC` when SOC > 10. That means: fixing the drain-target ALONE may still
not drain the battery on nights when the hold is engaged — the hold pins the reserve to
SOC and the DP-composed 10 is swallowed by the `max()`.

**This cycle does NOT demote the hold.** The parked cycle
`project_ev_drain_precedence_cycle` (memory) is the next-cycle successor for that work.

**Consequence for acceptance criteria (below):** they do NOT claim "battery drains
overnight." That would be an undiscriminating criterion of exactly the kind
`WHY_THE_ORIGINAL_TRIPLE_VERIFY_FAILED` warns against — a shared observation across
multiple candidate mechanisms cannot discriminate the fix. The acceptance criteria assert
what this cycle DOES fix: `TransitionInputs.drain_target_soc` and stamped
`_dp_decision_soc` values.

### Activation risk — this fix ACTIVATES a dormant state machine

DP has never transitioned in production life (`AUDIT_dp_live_behavior.md`; 10 days of
recorder history show only `hold_only` / `hold_pre_eval`, never `transitioned`, never
`must_start_forced`). With drain_target 80 vs SOC typically < 80, gate 7
(`already_below_target`) fires every eval. Fixing the target to 10 makes gate 7 pass and
lets DP transition for the first time.

**Live validation must watch the ACTUATION path**, not just the target number:
`_apply_dp_transition` at `energy.py:4953`, `_paused_by_dp` claim,
`_claim_pause_dispatch_owner("dp")`, and the must-start-by timer. With the `:4522` +
`:4555` fixes together, a fresh TRANSITIONED at SOC 40 with composed floor 10 stamps
`_dp_decision_soc = 10`, and the revert at `:4555` compares `40 <= 10 → False` → no flap.
Under partial fix (only `:4271`/`:4456` fixed as Rev-1 originally proposed), `:4522`
stamps 80 → reserve pinned at 80 while SOC 40, AND `:4555` immediately reverts
(`40 <= 80`) → EVSE `switch.turn_off` + `switch.turn_on` on the same tick, every 5-minute
tick — an actuation flap. Classifying `:4522`, `:4540`, `:4555` as R2 and routing all
through the helper is what prevents this.

### Acceptance criteria (discriminating, over the ENTIRE R2 set)

* **T1 (real construction path — NOT `_mk_inputs`):** static knob 80, forecast 10, SOC
  40, off-peak. Drive real `_evaluate_battery` (or the eval entry point that populates
  `:4456`) and assert `TransitionInputs.drain_target_soc == 10`. Under bug at `:4456`,
  value is 80 and gate 7 fires. Different observation.
* **T1b (SHADOW path):** same fixture; assert shadow `:4271` also emits 10. Under partial
  fix (only `:4456`), shadow snapshot at `sensor…ev_charging_plan.shadow_inputs` shows 80.
* **T1c (`:4522` fresh actuation — the A-CRIT-1 repro):** SOC 40, composed 10, fresh
  entry to TRANSITIONED. Assert `_dp_decision_soc == 10` and reserve emitted at
  `:4733/:4829` = `max(existing, 10, hold_reserve)`. Under bug that missed `:4522`,
  `_dp_decision_soc == 80`, reserve pinned 70 points above target.
* **T1d (`:4540` rescan):** first EVSE plugged, TRANSITIONED, second plug-in triggers
  rescan; assert `_dp_decision_soc` unchanged at 10 (idempotent). Under bug, second
  actuation stamps 80.
* **T2 (revert consistency — the A-CRIT-2 repro):** post-TRANSITIONED at SOC 40 with
  stamped `_dp_decision_soc == 10`; assert revert predicate `:4555` does NOT fire
  (`40 <= 10 → False`). Under bug, `:4555` compares against 80 and fires; test observes
  an EVSE actuation flap (turn_off followed by turn_on within the same tick).
* **T3 (R1 unchanged, HIGHEST_PROBABILITY_BUILD_ERROR guard):** mutate
  `_dp_drain_target_soc` in production source to return `self._ev_battery_drain_soc`; T3
  asserts `determine_battery_drain_actions` STILL receives `soc_threshold=80` at both
  `:5842` and `:5977`. If T3 fails after fix, INV-DP-DRAIN-2 is broken. Complementary:
  mutate `:5842` argument to composed value; T3 asserts test failure — the mutation drill.
* **T3b (helper None fallback — B-1 danger guard):** stub `compose_release_floor` to
  return `(None, True)`; assert `_dp_drain_target_soc` returns static reserve AND logs
  WARNING. Under B-1 bug (fallback to `_ev_battery_drain_soc`), helper returns 80
  silently.
* **T4 (R3 unchanged):** mutate `energy.py:3752` to route through `_dp_drain_target_soc`;
  T4 asserts blind-hold envelope proof STILL uses the static knob.
* **T5 (INV-DP-DRAIN-4 — offpeak-drain live-apply):** mutate
  `energy_offpeak_drain_excellent` Number to 25; assert
  `_drain_targets["excellent"] == 25` within one tick. Under reload-only branch, T5 is
  replaced by an assertion that the Number entity's help text or attribute contains
  "requires reload".
* **Live (D3 with plugged EV, off-peak, healthy Envoy):**
  `sensor.ura_energy_coordinator_ev_charging_plan.last_eval_snapshot.inputs.drain_target_soc`
  equals `sensor.ura_energy_coordinator_battery_strategy.current_offpeak_drain_target`
  (live 10). Under fix that missed one R2 site, either shadow or real disagrees.
* **Live (A-CRIT-1 direct):** on the first fresh TRANSITIONED, `_dp_decision_soc` reads
  10, NOT 80. Reserve entity commanded to the composed floor.
* **Live (A-CRIT-2 direct):** during any TRANSITIONED tick with SOC > composed floor,
  EVSE switch does not oscillate. Verified against switch state history over TRANSITIONED
  window.
* **Live (deferred criterion, on record):** if no EV is plugged during the eval window
  post-deploy, the live check for the DP snapshot defers to the next plug-in; README
  carries the deferred-verification note.

### Files changed

* `energy.py` — new helper `_dp_drain_target_soc`; five construction/predicate sites
  updated (`:4271`, `:4456`, `:4522`, `:4540`, `:4555`); import of `compose_release_floor`
  at top; ~30 LoC total. Optional: `BatteryStrategy.set_offpeak_drain_target` if
  live-apply branch chosen.
* `sensor.py` — attribute `drain_target_source` on
  `sensor.ura_energy_coordinator_ev_charging_plan` = `"composed_release_floor"` or
  `"static_reserve_fallback"` (post-fix observability).
* Tests — new file `quality/tests/test_dp_drain_target_source.py` covering
  T1/T1b/T1c/T1d/T2/T3/T3b/T4/T5. Do NOT extend
  `test_evse_drain_precedence_session_b2a.py:126-149` `_mk_inputs` — that fake is the
  hollow-anchor pattern.
* Docs drift:
  - `docs/user-manual/ENERGY_COORDINATOR.md:642` — default-50 + R1-only description
    (becomes correct for R1 after this cycle; drop R2 language).
  - `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md:455`.
  - `docs/planning/PLANNING_evse_drain_precedence.md` — the unbound `drain_target` symbol
    (Producer-check plan-gap defect this cycle closes).
  - `docs/planning/PLANNING_inclement_weather_reserve.md:66,82` — stale line refs to
    `energy.py:2671/2672` (~3200 lines off).

---

## 4. Non-goals (explicit)

* NOT demoting `evse_battery_hold` to backstop. Parked as `project_ev_drain_precedence_cycle`.
  D3 acceptance criteria do NOT claim "battery drains overnight."
* NOT changing the live value of `ev_battery_drain_soc` (still 80). Operator knob turn if
  policy changes; separate from this code fix.
* NOT changing R1 (`:5842`, `:5977`) or R3 (`:3752`, `energy_pool.py:954`, `:1435`)
  source. INV-DP-DRAIN-2 and INV-DP-DRAIN-3 protect this.
* NOT touching init (`:441`), getter (`:8730`), or setter (`:8732-8738`) of
  `_ev_battery_drain_soc`.
* NOT changing DP gate arithmetic (`energy_drain_precedence.py:609-735`). Gates 6, 7, 8
  ship unchanged; only the value they compare against changes.
* NOT re-wiring `compose_release_floor` at `energy_battery.py:264`. It is REUSED
  unchanged; this cycle is a new CALLER, not a modifier.
* NOT auto-fixing docs drift outside the files named in §3.

---

## 5. Known couplings

1. **DP gate 6 (`energy_drain_precedence.py:652`) — L1-only guard at 3.0 kW threshold**
   (12.5 A crossover at 240 V). Independent of this fix; DP still declines to drain against
   a sub-threshold charger. Note (crossover with the parallel solar-follow cycle): a
   throttled solar-follow session below 12.5 A will trip this gate; the diagnostician
   chasing "why did DP not drain" must know to check charger rate before blaming the
   drain-target.
2. **DP gate 8 charge_hours** blows up at low amps (`charge_hours = needed_kwh /
   charger_rate_kw`). Non-monotone with amp modulation; independent of this cycle.
3. **`_dp_house_load_kw` biased the OTHER way** — house-load-minus-EV subtracts a smaller
   EV load when the EV is throttled → house load reads higher → DP sees MORE drain
   opportunity. Combined with (2), net DP effect is NON-MONOTONE in amps. Independent of
   this cycle.
4. **`evse_battery_hold` pins reserve to live SOC.** Composes into the reserve fold via
   `max()`. `max(SOC, composed_floor) = SOC` when SOC > composed_floor. Why D3 acceptance
   cannot claim "battery drains overnight." Parked next-cycle work.
5. **INV-YIELD-1/2** (from `PLANNING_dp_sticky_yields_to_excess_solar.md`). Independent
   of this cycle — the yield semantics between DP and excess-solar do not depend on the
   drain-target value.

---

## 6. Docs drift to fix in-cycle

* `docs/user-manual/ENERGY_COORDINATOR.md:642` — default-50 + R1-only description.
* `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md:455`.
* `docs/planning/PLANNING_evse_drain_precedence.md` — unbound `drain_target` symbol.
* `docs/planning/PLANNING_inclement_weather_reserve.md:66,82` — stale line refs
  (~3200 lines off).

---

## 7. Test plan summary

Behavioural, MUTATION-VERIFIED. `PYTHONDONTWRITEBYTECODE=1` and clear `__pycache__` before
each drill (`feedback_mutation_verification_pycache_staleness`).

`test_dp_drain_target_real_tick_sourced_from_composed_floor` (T1);
`test_dp_drain_target_shadow_tick_sourced_from_composed_floor` (T1b);
`test_dp_fresh_transition_stamps_composed_not_static` (T1c, A-CRIT-1 repro);
`test_dp_rescan_stamps_composed_not_static` (T1d);
`test_dp_revert_predicate_uses_composed_not_static` (T2, A-CRIT-2 repro);
`test_dp_pause_soc_threshold_still_sources_from_static_knob` (T3, INV-DP-DRAIN-2 guard);
`test_dp_drain_target_helper_none_fallback_static_reserve_not_ev_knob` (T3b, B-1 guard);
`test_dp_ride_proof_floor_still_sources_from_static_knob` (T4, INV-DP-DRAIN-3 guard);
`test_offpeak_drain_number_live_apply_or_documented_reload` (T5, INV-DP-DRAIN-4).

Fixtures MUST construct through the real production path; MUST NOT set
`drain_target_soc` as a literal on a fake coordinator (hollow-anchor pattern per
`feedback_hollow_test_anchors`).

---

## 8. Review plan — Tier 3, four framing-disjoint passes

Per CLAUDE.md Tier 3 protocol. Run A/B/C/D in PARALLEL.

* **A — local correctness.** `_dp_drain_target_soc` helper: signature matches module
  function; None fallback branches; ValueError raise; every one of the five R2 sites
  substituted correctly; no accidental substitution at R1/R3 sites.
* **B — integration / state-machine + byte-identical no-op path.**
  `evaluate_dp_transition` gate arithmetic unchanged; `_apply_dp_transition` unchanged;
  reserve fold `max()` semantics preserved; R1 grep-diff clean; R3 grep-diff clean;
  sensor snapshot round-trips.
* **C — REAL per-site source mutation.** `PYTHONDONTWRITEBYTECODE=1`, clear
  `__pycache__`, then per drill:
  - C1: neuter D3 helper to return `_ev_battery_drain_soc` → T1/T1b/T1c/T1d must fail.
  - C2: swap `:5842` argument to composed → T3 must fail (INV-DP-DRAIN-2 guard).
  - C3: neuter `:4522` back to `int(self._ev_battery_drain_soc)` → T1c must fail.
  - C4: neuter `:4540` back → T1d must fail.
  - C5: neuter `:4555` back → T2 must fail.
  - C6: replace None fallback with `_ev_battery_drain_soc` → T3b must fail.
  - C7: mutate `energy.py:3752` to route through helper → T4 must fail.
  Site whose mutation leaves suite green = untested = unacceptable.
* **D — adversarial completeness / diff-blind.** Re-enumerate the ENTIRE R2 emission set
  from scratch (grep `drain_target_soc`, `_dp_decision_soc`, `_ev_battery_drain_soc`),
  INCLUDING pre-existing code. Enumerate all sites reading `_dp_decision_soc` (reserve
  fold) and confirm no additional R2 emission sites emerged. Legal-config combinatorial:
  static reserve at extremes, park state active vs inactive, Solcast tier degraded,
  hold-active vs not, off-peak vs mid-peak boundaries. Every leak → concrete legal-config
  repro.

**Plan reviews (Tier 3 = TWO plan reviews before build dispatch):**

1. **Completeness** — independent re-enumeration of every `_ev_battery_drain_soc` read and
   every DP construction site.
2. **Adversarial build-prediction** — "what will the builder get wrong reading this?"
   Ambiguities, under-specified orderings.

**Orchestrator pre-deploy verification (MANDATORY per Tier 3):** personally re-grep every
`drain_target_soc =` assignment and `_ev_battery_drain_soc` read; confirm the FIVE R2
sites are now the helper and the R1/R3 sites are unchanged. Personally run source-mutation
drills on `_dp_drain_target_soc` and on `:4522` / `:4555` and confirm named tests fail.
**Operator checkpoint BEFORE deploy.**

---

## 9. REUSE vs NEW

| Item | Verdict | Cite |
|---|---|---|
| `compose_release_floor()` (module fn) | REUSE unchanged | `energy_battery.py:264` |
| `_ev_battery_drain_soc` at R1 sites | REUSE unchanged | `energy.py:5842`, `:5977` |
| `_ev_battery_drain_soc` at R3 sites | REUSE unchanged | `energy.py:3752`, `energy_pool.py:954`, `:1435` |
| `evaluate_dp_transition` gate arithmetic | REUSE unchanged | `energy_drain_precedence.py:609-735` |
| `_apply_dp_transition` reserve-fold behaviour | REUSE unchanged | `energy.py:4733-4742`, `:4829-4833` |
| DP sensor snapshot payload shape | REUSE (auto-follows) | `sensor.py`; `energy.py:3871`, `:4021` |
| `_dp_drain_target_soc(period)` helper | NEW | ~15 LoC + None fallback |
| `BatteryStrategy.set_offpeak_drain_target(tier, value)` | NEW (conditional on INV-DP-DRAIN-4 branch) | Live-apply into ctor-frozen dict |
| `drain_target_source` sensor attribute | NEW | Post-fix observability |

---

## 10. Closed concerns — must stay closed

| Concern | Round originally closed | The one-line invariant that keeps it shut |
|---|---|---|
| Parallel derivation of the DP drain target (`current_offpeak_drain_target()` bypassing park reconciliation) | Combined-plan Rev-2 (B-1 danger note) | `_dp_drain_target_soc` uses `compose_release_floor` ONLY; None fallback goes to static reserve, NEVER to `_ev_battery_drain_soc` or the raw `current_offpeak_drain_target()`. Future-revision grep-check for `current_offpeak_drain_target(` outside `energy_battery.py`. |
| Missed R2 emission site (5 sites, not 2) | Combined-plan Rev-2 (A-CRIT-1) | The R2 emission-site TABLE in §3 lists ALL five (`:4271`, `:4456`, `:4522`, `:4540`, `:4555`); every future revision touching DP grep-checks for `_ev_battery_drain_soc` under `domain_coordinators/` and confirms only R1/R3 sites remain. |
| Same-tick revert flap when `:4522` stamps and `:4555` reverts | Combined-plan Rev-2 (A-CRIT-2) | `:4555` sources from `_dp_drain_target_soc(period)`, same value stamped by `:4522`. INV-DP-DRAIN-1b. |
| R1 pause ceiling collapse to composed floor | Combined-plan Rev-2 (HIGHEST_PROBABILITY_BUILD_ERROR) | `determine_battery_drain_actions(soc_threshold=)` sources from `self._ev_battery_drain_soc` unchanged at `:5842` + `:5977`. INV-DP-DRAIN-2 + mutation drill C2. |
| `compose_release_floor` signature mistaken (was thought to be a method, second element thought to be a reason string, None-return not handled) | Combined-plan Rev-4 (A-HIGH-1 / B-1) | Helper importing as free function; signature `(release_floor: int | None, is_offpeak: bool)`; None fallback to STATIC RESERVE (not `_ev_battery_drain_soc`, not raw accessor). Test T3b. |

---

## 11. Cycle-close checklist

* [ ] Two plan reviews (Tier 3): completeness + adversarial build-prediction.
* [ ] Build in one branch off `develop`.
* [ ] Suite green + baseline-diff clean.
* [ ] Four framing-disjoint reviews A/B/C/D returned; CRITICAL/HIGH fixed with re-run
      drills.
* [ ] Orchestrator pre-deploy: re-grep every `drain_target_soc =` and
      `_ev_battery_drain_soc` read; confirm five R2 sites are the helper and R1/R3 sites
      unchanged; run source-mutation drills C1-C7; record numeric value of
      `DEFAULT_OFFPEAK_DRAIN_UNKNOWN`.
* [ ] Operator checkpoint before deploy.
* [ ] `README_v<version>.md` with prospective Live criteria (including the deferred
      criterion for the plugged-EV live check).
* [ ] Deploy via `./scripts/deploy.sh`.
* [ ] Live validation: DP snapshot with plugged EV (deferred if no plug during window);
      A-CRIT-1 direct (`_dp_decision_soc == 10` on first fresh TRANSITIONED); A-CRIT-2
      direct (no same-tick revert flap during TRANSITIONED); reserve entity commanded to
      composed floor.
* [ ] README updated with observed `Validated <date>` table.
* [ ] Kanban card `EVSE-DRAIN-PRECEDENCE-KNOB-80-1` moved to shipped_organic; parked
      `project_ev_drain_precedence_cycle` retained.
* [ ] Post-ship supersession + consumer-gap audit per CLAUDE.md rule.
