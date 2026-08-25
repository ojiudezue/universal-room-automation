# PLANNING — DP drain-target mis-sourcing fix

**Cycle name:** `dp-drain-target-mis-sourcing`
**Tier:** **Tier 3** (delicate shared-primitive fix; five R2 emission sites; value stamped
into the commanded Enphase reserve floor — cost and safety impact).
**Threads:** `energy`
**Cards:** `EVSE-DRAIN-PRECEDENCE-KNOB-80-1`
**Design source:** the card body (esp. `RE_VERIFIED_2026_08_23_card_stands_memory_was_stale`,
`SCOPING_2026_08_20_ONE_NUMBER_THREE_ROLES`, `RECOMMENDED_DESIGN_D_SPLIT_THE_ROLES`,
`ACTIVATION_RISK_NOT_JUST_A_BUGFIX`) and `docs/planning/AUDIT_excess_solar_and_evse_prior_art.md`.

**Provenance.** Extracted from `PLANNING_evse_solar_follow_and_dp_drain_target.md`
(Rev-1..Rev-8). **Rev-11 addition:** operator supplied config-flow screenshots with
help-text and live values that add institutional context for the R1 knob. Does NOT
change the fix itself — the R2/R1/R3 site classification and the helper design stand.
Only §2 institutional context and the new §11 "R1 knob live-vs-default note" are added.

**Runtime relationship to solar-follow (informational, not a build dependency).**
Shipping this fix changes which drain target DP consumes → changes when DP holds EVSEs via
`_paused_by_dp` → changes solar-follow's ELIGIBLE set. Solar-follow has no code dependency
on this cycle. **Shipping THIS cycle FIRST is preferable, not merely acceptable** — the
solar-follow cycle then gets built and live-validated against corrected DP behaviour
rather than against a known-wrong drain target that has never fired a transition.

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
expensive-grid windows. Prevents the HIGHEST_PROBABILITY_BUILD_ERROR.

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
  `DP_CAPACITY_KWH_PER_SOC_PP=0.40` (`:1367`); **`DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD
  = 50` at `:857`** (verified); `CONF_ENERGY_EV_BATTERY_DRAIN_SOC =
  "energy_ev_battery_drain_soc"` at `:858` (verified); DP persistence key `:1390`;
  `DEFAULT_OFFPEAK_DRAIN_UNKNOWN` (builder task: record its numeric value in README).
* `sensor.py` — DP charging-plan sensor
  (`sensor.ura_energy_coordinator_ev_charging_plan`) emits `last_eval_snapshot.inputs.
  drain_target_soc` (display-only consumer; follows the new source automatically).
* `PLANNING_evse_drain_precedence.md` — the DP design doc with the **unbound `drain_target`
  symbol** (Producer-check plan gap; this cycle binds it in §6 docs drift).
* **Live values relevant to acceptance criteria (Rev-11 verified via operator screenshot
  + source):**
  - `number.ura_energy_coordinator_ev_battery_drain_soc = 80` (operator-set) vs
    `DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD = 50` in code (`energy_const.py:857`).
  - Config-flow help text (verbatim from screenshot, operator-authored):
    *"When the home battery is actively discharging below this SOC AND EV+L1 is
    charging, URA pauses to protect battery reserve. Default 50% (deep floor behind
    Pause EV Until Battery SOC). Range 5-95%. See README_v4.7.6.1 for the asymmetric-
    defaults rationale."*
  - Pointer: `README_v4.7.6.1` documents the asymmetric-defaults rationale for
    `fill_priority_soc` (default 80, "Pause EV Until Battery SOC") vs
    `ev_battery_drain_soc` (default 50, "deep floor BEHIND").
  - `sensor.ura_energy_coordinator_battery_strategy.current_offpeak_drain_target = 10`
    (forecast-based, live).
  - The forecast target (10) and the static knob live value (80) differ by 70 SOC
    points — this is the money-losing gap the fix addresses.
* Memory: `project_ev_drain_precedence_cycle` (parked hold-demotion cycle, explicitly
  non-goal here); `feedback_hollow_test_anchors`;
  `feedback_mutation_verification_pycache_staleness`.

---

## 3. Deliverable

### Full R2 emission-site table

| Site | Where | Class | Change |
|---|---|---|---|
| `energy.py:4271` | Shadow `TransitionInputs` | **R2** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:4456` | Real tick `TransitionInputs` | **R2** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:4522` (`_DPAct`) | Fresh-TRANSITIONED actuation | **R2** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:4540` (`_DPActRescan`) | Second-plug rescan | **R2** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:4555` (`_drain`) | Revert predicate | **R2 (revert consistency)** | Source from `_dp_drain_target_soc(period)` |
| `energy.py:3871` | DP snapshot sensor | R2-display | Auto |
| `energy.py:4021` | Same sensor payload | R2-display | Auto |
| `energy.py:4910` | `_apply_dp_transition` stamp site | R2 consumer | No change |
| `energy.py:3752` | Blind-hold envelope proof | **R3** | Unchanged |
| `energy_pool.py:954` | Blind-window off-peak ride | **R3** | Unchanged |
| `energy_pool.py:1435` | Excess-solar blind-window branch | **R3** | Unchanged |
| `energy_pool.py:619-648` (helper body) | ARG-based | Follows caller | R3 callers unchanged |
| `energy.py:5842` (EV) | `determine_battery_drain_actions(soc_threshold=)` | **R1** | Unchanged |
| `energy.py:5977` (plugs) | Plug mirror | **R1** | Unchanged |

### `_dp_drain_target_soc` helper

```python
from .energy_battery import compose_release_floor

def _dp_drain_target_soc(self, tou_period: str) -> int:
    """Composed off-peak drain target for the five R2 DP sites.

    Rev-2 (review finding 6): the previous version carried a
    "fall back to static reserve" branch that was UNREACHABLE. In the
    off-peak branch `compose_release_floor` returns None ONLY at
    `energy_battery.py:303`, which happens only when static_reserve is
    None AND park is None — and the fallback then read
    `battery.reserve_soc`, i.e. the same attribute already proven None.
    floor-is-None therefore ALWAYS implied static-reserve-is-None. Dead
    branch removed; raising is the correct and only behaviour.
    """
    floor, _is_offpeak = compose_release_floor(self._battery, tou_period)
    if floor is None:
        _LOGGER.warning(
            "DP drain-target unavailable (compose_release_floor returned None — "
            "reserve_soc and park floor both unset, typically an Envoy boot "
            "condition); skipping this tick's DP evaluation."
        )
        raise ValueError("dp drain-target unavailable")
    return int(floor)
```

**All five R2 sites sit inside the off-peak gate** (`energy.py:4416` raises `_DPSkip` when the
period is not `off_peak`; the shadow returns early at `:4245`), so the helper is only ever
invoked with `is_offpeak=True`. `compose_release_floor`'s non-off-peak branch
(`energy_battery.py:290-291`) is unreachable from this cycle — no non-off-peak behaviour change.

**ValueError containment — READ THIS BEFORE IMPLEMENTING `:4555`.** Containment already
exists structurally: `energy.py:5628-5634` wraps `_dp_decision_tick` in `except _DPSkip` AND a
broad `except Exception`, and the shadow call at `:4409-4414` has its own handler. So `:4271`
and `:4456` skip the tick correctly with no new code, and `:4522`/`:4540` decline to actuate.

**But `:4555` MUST NOT be written as a bare call.** A naive
`_drain = self._dp_drain_target_soc(period)` at `:4555` propagates to the OUTER handler and
aborts the entire remainder of `_dp_decision_tick` — which includes the
`MUST_START_FORCED → _revert = True` branch (`:4558-4559`) and the "paused but nothing charging"
branch (`:4560-4565`). The must-start-by revert is the safety path that unpauses the EV before
its deadline.

*Legal-config repro:* Envoy boot, `reserve_soc` unavailable → helper raises; carrier is in
`MUST_START_FORCED`; the forced revert never runs and EVSEs stay stuck in `_paused_by_dp`.

**Required shape at `:4555`:** compute the target defensively and skip ONLY the SOC-comparison
branch, never the enclosing block —

```python
try:
    _drain = self._dp_drain_target_soc(period)
except ValueError:
    _drain = None
if _drain is not None and _soc <= _drain:
    _revert = True
# MUST_START_FORCED and paused-but-idle branches below MUST still run.
```

**Producer / Consumer + call-site check** unchanged from prior revision.

**INV-DP-DRAIN-4 blocker resolution** unchanged (builder picks live-apply vs documented
reload; INV-DP-DRAIN-4 enforces whichever choice).

**Hold-demotion — OUT OF SCOPE.**

**Activation risk framing** unchanged.

**D3 acceptance criteria:** see §3b (Verify / Test / Live) and §7 for the T1..T5 fixtures.

**Files changed** — unchanged.

---

## 3b. Acceptance criteria

- **Verify:** on a fresh DP transition with static knob 80, composed off-peak floor 10 and
  SOC 40, `TransitionInputs.drain_target_soc` reads **10** at all five R2 sites, and the
  stamped `_dp_decision_soc` reads **10**, not 80. Under the bug it reads 80 and the reserve
  floor is commanded 70 points above SOC.
- **Verify:** no same-tick actuate-then-revert. At SOC 40 with composed 10, a fresh
  TRANSITIONED entry does NOT revert on the same tick (`:4555` sees 10, not 80).
- **Verify:** R1 sites (`:5842`, `:5977`) still receive the STATIC knob — the drain-protection
  pause ceiling is unchanged by this cycle.
- **Verify:** R3 sites (`:3752`, `energy_pool.py:954`, `:1435`) unchanged.
- **Verify:** when `compose_release_floor` returns `None` the helper RAISES (skipping the tick)
  and logs a WARNING. There is no static-reserve fallback — see §3, the branch was unreachable.
- **Test:** T1, T1b, T1c, T1d, T2, T3, T3b, T4, T5, each mutation-anchored per C1-C5.
- **Live:** after restart, with an EV plugged during off-peak, the DP snapshot sensor
  (`energy.py:3871` payload) shows `drain_target_soc` equal to the composed off-peak target
  for the current forecast class, NOT the static knob value. Record the observed number and
  the forecast class in the README validation table.
- **Live (discriminating) — PAIRED, both halves required.** (a) a DP transition ACTUALLY
  OCCURRED: carrier state reads `TRANSITIONED` AND `_dp_decision_soc` is non-`None` on that
  tick; AND (b) the commanded reserve floor does not exceed live battery SOC on that same
  tick. **Half (b) alone is NOT discriminating** — under the documented pre-fix status quo
  (DP has never fired a transition) `_dp_decision_soc` is never stamped, the `max()` folds at
  `energy.py:4733-4742`/`:4829-4832` skip the DP contributor, and (b) reads PASS for a
  feature that did nothing. Recording (b) alone would enter a false PASS in the README table.
- **Live:** scan logs for the helper's single WARNING. It should not appear in normal
  operation; its appearance means reserve_soc and the park floor are both unset (Envoy boot) and
  DP skipped that tick.

---

## 4. Non-goals

* NOT demoting `evse_battery_hold` to backstop.
* **NOT changing the live value of `ev_battery_drain_soc` (still 80) in this cycle.**
  See §11 for the operator-knob-turn question this cycle explicitly does NOT scope.
* NOT changing R1 (`:5842`, `:5977`) or R3 (`:3752`, `energy_pool.py:954`, `:1435`)
  source.
* NOT touching init (`:441`), getter (`:8730`), or setter (`:8732-8738`) of
  `_ev_battery_drain_soc`.
* NOT changing DP gate arithmetic. Only the value gates compare against changes.
* NOT re-wiring `compose_release_floor`. REUSED unchanged.
* NOT auto-fixing docs drift outside the files named in §3.

---

## 5. Known couplings

1-5 unchanged (DP gate 6 crossover, gate 8 charge_hours, `_dp_house_load_kw` bias,
`evse_battery_hold` pins reserve to live SOC, INV-YIELD-1/2 independence).

---

* **`very_poor` drain target cannot be live-updated (pre-existing, now load-bearing).**
  `energy.py:8647` validates `quality` against `{excellent, good, moderate, poor}`, but
  `_drain_targets` carries `very_poor` (`energy_battery.py:466`) and `classify_tomorrow_solar`
  can return it. On a very-poor night the DP target comes from a value no Number entity can
  change. Out of scope for this cycle, but THIS cycle is what makes that target load-bearing
  for DP, so it is recorded here and needs a card.

## 6. Docs drift to fix in-cycle

* `docs/user-manual/ENERGY_COORDINATOR.md:642` — default-50 + R1-only description.
* `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md:455`.
* `docs/planning/PLANNING_evse_drain_precedence.md` — unbound `drain_target` symbol.
* `docs/planning/PLANNING_inclement_weather_reserve.md:66,82` — stale line refs.

---

## 7. Test plan summary

Behavioural, MUTATION-VERIFIED. `PYTHONDONTWRITEBYTECODE=1` and clear `__pycache__`.
Fixtures MUST construct through the real production path (NOT `_mk_inputs`).

**Fixture contract — binding on T1, T1b, T1c, T1d, T2.** The composed floor is
`max(int(static_reserve), int(park))` (`energy_battery.py:299`). Every fixture asserting `== 10`
MUST pin **`reserve_soc = 10` AND `park_floor = 10`** explicitly. `DEFAULT_RESERVE_SOC = 10`
(`energy_const.py:181`) makes 10 achievable but no fixture may rely on the default — a fixture
with any other reserve yields `max(reserve, 10)` and a builder will "fix" the assertion instead
of the fixture.

**Rule (Tier-3 framing C): a test NEVER contains its own mutation.** Tests assert unmutated
production behaviour; mutations live only in §8. A test that applies a mutation and then asserts
the mutated outcome cannot fail and proves nothing.

* **T1 (real tick, `:4456`):** static knob 80, composed 10, SOC 40, off-peak. Drive real
  `_evaluate_battery`; assert `TransitionInputs.drain_target_soc == 10`. Under bug: 80, and
  gate 7 (`energy_drain_precedence.py:656`, `soc <= drain_target_soc`) fires.
* **T1b (shadow, `:4271`):** same fixture; assert the shadow path emits 10.
* **T1c (`:4522` fresh actuation — A-CRIT-1 repro):** SOC 40, composed 10, fresh entry to
  TRANSITIONED. **Load-bearing assertion: `_dp_decision_soc == 10`.** Secondary: the folded
  reserve at `:4733`/`:4829`. Note the secondary is NOT discriminating on its own — with
  `evse_battery_hold` active (§5) the fold is live SOC 40 both under the fix and if DP never
  stamps at all. Do not drop the `_dp_decision_soc` assertion as redundant.
* **T1d (`:4540` rescan):** first EVSE plugged and TRANSITIONED; second plug-in triggers rescan.
  Assert `_dp_decision_soc` unchanged at 10 (idempotent). Under bug: second actuation stamps 80.
* **T2 (revert consistency — A-CRIT-2 repro):** post-TRANSITIONED at SOC 40 with
  `_dp_decision_soc == 10`. **Load-bearing assertion: the `_revert` outcome / carrier state** —
  `40 <= 10 → False` under the fix versus `40 <= 80 → True` under the bug. Unambiguous.
  A same-tick `turn_off`/`turn_on` flap is a SECONDARY check only: `_apply_dp_reversion` has not
  been verified to emit a same-tick `turn_on`, so do not anchor the test on it.
* **T3 (R1 preserved — no mutation):** plain assertion on the unmutated tree that
  `determine_battery_drain_actions` receives `soc_threshold` equal to
  `coord._ev_battery_drain_soc` at `:5842` and `:5977`. Its anchor is **C2**, not itself.
* **T4 (R3 preserved, `:3752` — no mutation):** plain assertion on the unmutated tree that the
  blind-hold envelope proof reads the static knob. Its anchor is **C8**.
* **T4b (R3 preserved, `energy_pool.py:954`/`:1435` — NEW, closes an unanchored invariant):**
  assert both excess-solar / blind-window ride sites still pass the STATIC knob into
  `_soc_envelope_admits_dp_transition`. Anchors: **C9**, **C10**. Without this, INV-DP-DRAIN-3
  has no test at either site, and a domain-wide replace of `_ev_battery_drain_soc` in the DP
  call graph would silently drop the ride floor from 80 to the composed 10 with a green suite.
* **T5 (off-peak drain live-apply, end to end):** set `energy_offpeak_drain_excellent` to 25;
  assert (a) `_drain_targets["excellent"] == 25` within one tick, AND (b) **the helper's output
  moves** — `_dp_drain_target_soc(off_peak)` reflects 25 under an `excellent` forecast class.
  (a) alone proves only the Number setter, not that the value reaches DP.

**T3b is DELETED.** It stubbed `compose_release_floor` to `(None, True)` while leaving
`reserve_soc` populated — a state the real function cannot produce (see §3, unreachable-branch
note). A test whose fixture is impossible in production proves nothing.

---

## 8. Review plan — Tier 3

A/B/C/D framings per the Tier-3 protocol. Two plan reviews before build (completeness +
adversarial build-prediction). Orchestrator pre-deploy verification mandatory. Operator
checkpoint BEFORE deploy.

**Mutation drills — REAL per-site source mutation, ONE site at a time, restore after each.**
Run with `PYTHONDONTWRITEBYTECODE=1` and a cleared `__pycache__` — stale bytecode has produced
a false PASS on this exact drill class before.

**Every R2 site gets its OWN drill.** C1 (neuter the helper) proves the helper is load-bearing
*in aggregate*, which is precisely the global-monkeypatch failure mode Tier-3 framing C forbids.
Aggregate coverage would let a builder convert three sites, leave two on the static knob, and
still see every drill bite.

- **C1:** neuter `_dp_drain_target_soc` to return `_ev_battery_drain_soc`
  → **T1, T1b, T1c, T1d must fail.** (Aggregate anchor only — not sufficient alone.)
- **C2:** swap the R1 site `energy.py:5842` argument to the composed value → **T3 must fail.**
- **C3:** revert `energy.py:4522` to `int(self._ev_battery_drain_soc)` → **T1c must fail.**
- **C4:** revert `energy.py:4540` → **T1d must fail.**
- **C5:** revert `energy.py:4555` (revert predicate) → **T2 must fail.**
- **C6:** revert `energy.py:4271` (shadow) → **T1b must fail.**
- **C7:** revert `energy.py:4456` (real tick) → **T1 must fail.**
- **C8:** route `energy.py:3752` through `_dp_drain_target_soc` → **T4 must fail.**
- **C9:** route `energy_pool.py:954` through the composed value → **T4b must fail.**
- **C10:** route `energy_pool.py:1435` through the composed value → **T4b must fail.**

A site whose bypass leaves the suite green is an untested site. **All ten must bite** — five R2
conversions (C3-C7), one aggregate (C1), and four preservation guards (C2, C8, C9, C10).

---

## 9. REUSE vs NEW

Unchanged. `compose_release_floor` REUSE; `_ev_battery_drain_soc` at R1/R3 REUSE
unchanged; `evaluate_dp_transition` gate arithmetic REUSE unchanged; helper NEW.

---

## 10. Closed concerns — must stay closed

Unchanged (parallel-derivation guard; R2 site count; revert flap; R1 collapse;
`compose_release_floor` signature).

---

## 11. R1 knob live-vs-default note (Rev-11 add, informational)

**Operator-authored config-flow help text (verbatim, verified 2026-08-24):**

> *"When the home battery is actively discharging below this SOC AND EV+L1 is
> charging, URA pauses to protect battery reserve. Default 50% (deep floor behind
> Pause EV Until Battery SOC). Range 5-95%. See README_v4.7.6.1 for the asymmetric-
> defaults rationale."*

**Verified in source:** `DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD = 50` at
`energy_const.py:857`. The knob is live at **80** (operator-set via options flow).

**Design intent stated in the help text:** `_ev_battery_drain_soc` is meant to sit as a
**deep floor BEHIND** `fill_priority_soc` (the "Pause EV Until Battery SOC" knob,
default 80). The intended asymmetric pattern is:

- `fill_priority_soc` (default 80) — the "pause EV until battery reaches this SOC"
  threshold. `determine_fill_priority_actions` pauses EV+L1 charging when SOC drops
  below this while solar forecast is healthy, so the battery fills first.
- `ev_battery_drain_soc` (default **50**) — the R1 deep-discharge backstop, sitting
  BEHIND the pause-until threshold. Fires only when the battery is actively discharging
  below this deeper level while EV is charging.

**Observation, not diagnosis (per operator rule: do not re-diagnose the card's root
cause):** the operator-set live value (80) equals the intended pause-until threshold
(80), which collapses the "deep floor behind" separation the help text describes. What
was designed as a two-level asymmetric pattern is currently operating as a single-level
one. This is an OPERATOR KNOB VALUE observation, not a code defect this cycle addresses.

**Does the D3 fix change what this knob effectively does?**

**No — the R1 semantic role is unchanged.** The knob continues to serve as:
- R1 pause ceiling at `energy.py:5842` (EV) and `:5977` (plugs) — unchanged
  (INV-DP-DRAIN-2 protects this).
- R3 ride-proof floor at `energy.py:3752`, `energy_pool.py:954`, `energy_pool.py:1435`
  — unchanged (INV-DP-DRAIN-3 protects this).

**What the D3 fix DOES remove** is the R2 role — the knob no longer determines the DP
drain target (that role migrates to `_dp_drain_target_soc(period)` composing over
`compose_release_floor`). Post-cycle, the knob:
- Still fires the R1 pause when battery discharges below its value while EV is charging.
- Still gates the R3 blind-hold envelope proof.
- Does NOT determine how deep DP is willing to drain the battery for EV charging (that
  becomes the forecast-based composed floor, live 10 today).

**Consequence for the operator (recorded for the post-ship discussion, NOT scoped as
this cycle's work):** with the D3 fix in place, the operator has a separate question
about whether the live value (80) should return to the documented default (50) — since
its R2 role is gone, keeping it at 80 means the R1 pause fires often (any battery
discharge below 80 while EV charges), which was tolerable pre-fix (because DP's own
mis-sourcing made the whole path inert anyway) but may now cause spurious EV pauses in
practice. **This is an OPERATOR KNOB TURN, not a code change.** It is called out in
the post-ship supersession + consumer-gap audit checklist (§12) as a question the audit
must answer with live data.

---

## 12. Cycle-close checklist

* [ ] Two plan reviews (Tier 3): completeness + adversarial build-prediction.
* [ ] Build in one branch off `develop`.
* [ ] Suite green + baseline-diff clean.
* [ ] Four framing-disjoint reviews A/B/C/D returned; CRITICAL/HIGH fixed.
* [ ] Orchestrator pre-deploy: re-grep every `drain_target_soc =` and
      `_ev_battery_drain_soc` read; confirm five R2 sites are the helper and R1/R3
      sites unchanged; run source-mutation drills C1-C10; record numeric value of
      `DEFAULT_OFFPEAK_DRAIN_UNKNOWN`.
* [ ] Operator checkpoint before deploy.
* [ ] `README_v<version>.md` with prospective Live criteria.
* [ ] Deploy via `./scripts/deploy.sh`.
* [ ] Live validation: DP snapshot with plugged EV (deferred if no plug during
      window); A-CRIT-1 direct (`_dp_decision_soc == 10` on first fresh TRANSITIONED);
      A-CRIT-2 direct (no same-tick revert flap during TRANSITIONED); reserve entity
      commanded to composed floor.
* [ ] README updated with observed `Validated <date>` table.
* [ ] Kanban card `EVSE-DRAIN-PRECEDENCE-KNOB-80-1` moved to shipped_organic; parked
      `project_ev_drain_precedence_cycle` retained.
* [ ] Post-ship supersession + consumer-gap audit per CLAUDE.md rule — **INCLUDES the
      R1-live-value question raised in §11: with the D3 fix in place, does the
      operator-set 80 (currently equal to `fill_priority_soc`) produce spurious EV
      pauses in observed data, and does returning it to the documented default 50
      restore the "deep floor behind" pattern the help text describes? Data source:
      count `_paused_by_battery_drain` events on days when EV was charging and battery
      SOC dipped into 50-80 range. Operator-knob-turn decision, not code.**
