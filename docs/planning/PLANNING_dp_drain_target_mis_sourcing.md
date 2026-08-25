# PLANNING — DP drain-target mis-sourcing fix

**Cycle name:** `dp-drain-target-mis-sourcing`
**Tier:** **Tier 3** (delicate shared-primitive fix; value threads into the commanded
Enphase reserve floor — cost + safety impact). **Rev-15 (this revision, operator ruling
2026-08-25): POSITIVE-STAMP BRANCH GATE.** The Rev-14 negative-inference gate
(`not _arbitrage_active AND not _attain_active AND hold_depth == "allow_discharge"`)
was INCOMPLETE. `_arbitrage_active` is cleared to `False` at THREE distinct call sites
in `energy_battery.py` — WAIT (`:3157`), envoy-blind hold (`:4705`), AND the drain-fallback
branch itself (`:5274`), and the attain-reboot-release + grid-disconnect paths never
touch it either — so the negative predicate is `True` on multiple non-draining branches.
Any conjunction of negative predicates is therefore a proof-by-elimination over an
enumeration that CANNOT be verified exhaustive from source. Rev-15 replaces inference
with a POSITIVE STAMP written inside the drain-fallback branch itself, and gates DP on
that stamp being fresh THIS tick. Operator: *"Stop inferring; stamp positively."*

**Threads:** `energy`
**Cards:** `EVSE-DRAIN-PRECEDENCE-KNOB-80-1`
**Related (NOT blocked_by):** `DRAIN-TARGET-DAY-STALENESS-1` —
`docs/planning/PLANNING_offpeak_drain_target_day_staleness.md`. DP inherits any accessor
fix; it does not wait.

**Provenance.** Rev-1..Rev-8 (extracted from `PLANNING_evse_solar_follow_and_dp_drain_target.md`).
Rev-11 R1 knob live note. Rev-12 `_last_reserve_level_desired` design (deleted at Rev-13).
Rev-13 chose C3 = `max(reserve_soc, current_offpeak_drain_target())` *without* a branch
gate; round-3 re-review found D-CRIT-1 (sim inaccuracy) and D-CRIT-2 (false whole-emitter
mirror). Rev-14 (OPTION A) added a negative-inference branch gate. Rev-14 re-review found
**C-CRIT-1/1b** — the negative predicate is `True` on arbitrage WAIT, envoy-blind hold,
attain-reboot-release, AND grid-disconnect, all non-drain branches; **C-HIGH-1** — the
shadow eval runs BEFORE the off-peak gate at `energy.py:4408 / :4416` so peak/mid_peak
ticks would consult the gate; **C-HIGH-2** — the None-`_drain_target` guard leaves a
TRANSITIONED carrier stranded (paused EVSE never releases) when the strategy transitions
mid-carrier; **C-HIGH-3** — the sim's `in_drain_branch` was DERIVED from the same
negative predicates the candidate consumed (tautology); **C-LOW-1** — raw string literal
for the reason code. Rev-15 fixes all five.

**Rev-15's load-bearing change (vs Rev-14):** relax the Rev-13/14 "NO change to
`energy_battery.py`" constraint. That constraint is precisely what forced the fragile
negative inference. One line added at `energy_battery.py:5274` (the existing
`_arbitrage_active = False` site inside the drain-fallback branch) stamps a positive
per-tick marker. One line added at the top of `_decision_cycle_body` (before
`determine_mode`) resets it. The gate reads the marker. This is exhaustive by
CONSTRUCTION — no enumeration of branches needed, immune to any future new branch (the
recurring Bug Class #53 seam is closed by construction, not by hoping the enumeration
was complete).

**Runtime relationship to solar-follow** unchanged: this cycle ships first; solar-follow
validates against corrected DP behaviour.

---

## 1. Falsifiable invariants

### INV-DP-DRAIN-1 (drain-fallback-branch mirror — CORRECTED at Rev-14, unchanged at Rev-15)
Under any config, **when the branch gate reports `emitter_in_drain_branch == True`**,
under any code path that populates `TransitionInputs.drain_target_soc` OR stamps a fresh
`_dp_decision_soc` via `_apply_dp_transition` OR compares SOC against the drain target
in the revert predicate, the value used equals
`max(getattr(battery, "reserve_soc", 0), battery.current_offpeak_drain_target())` for
the current tick. Applies to all five R2 sites (§3 table) AND to the shadow-eval site
at `:4271`.

Sourcing rule (RULED, operator 2026-08-24):
```
_dp_drain_target_soc(period) := max(reserve_soc, current_offpeak_drain_target())
```
Defensive `reserve_soc` handling unchanged from Rev-14 (§3 helper body). No `or 0`.

### INV-DP-DRAIN-1d (positive-stamp branch gate — LOAD-BEARING, REWRITTEN at Rev-15)
**Definition.** `emitter_in_drain_branch == True` iff, on the CURRENT decision-cycle
tick, `_get_off_peak_decision` executed its drain-fallback branch (at
`energy_battery.py:5269-5352`). This is stamped POSITIVELY by the drain-fallback branch
itself, not inferred from the absence of competing branches.

**Mechanism.** Two source edits in `energy_battery.py`:

1. **Reset** — top of `_decision_cycle_body` at `energy.py:5534`, BEFORE
   `determine_mode(...)` is called at `:5573`, the coordinator resets the marker on the
   battery:
   ```python
   self._battery._offpeak_drain_branch_this_tick = False
   ```
   This is the SOLE reset site. It runs unconditionally each cycle. The marker
   therefore transitions False→True at most once per tick, and only if the drain-fallback
   branch was reached.

2. **Stamp** — inside `_get_off_peak_decision`'s drain-fallback branch, adjacent to
   the existing `self._arbitrage_active = False` at `energy_battery.py:5274` (the line
   that already marks entry to this branch), add:
   ```python
   self._offpeak_drain_branch_this_tick = True
   ```
   Placed BEFORE the ladder-suffix build so it fires even if a downstream expression
   raises (defensive: the raise would propagate up and abort the tick, but the marker
   staying True on an aborted tick is safe — DP will consult it, but DP itself is
   wrapped in `try/except _DPSkip / Exception` at `energy.py:5629-5634`).

**Gate consumption.** The helper (§3):
```python
def _dp_emitter_in_drain_branch(self) -> bool:
    try:
        return bool(getattr(self._battery, "_offpeak_drain_branch_this_tick", False))
    except Exception:
        return False
```
Defensive default False (safe direction: DP declines).

**When the gate reports False**, DP MUST NOT emit a fit/transition. The tick publishes
`DP_REASON_EMITTER_NOT_DRAINING`; the shadow publishes `shadow_decision="not_applicable"`
+ `shadow_reason="emitter_not_draining"`. The DP carrier does not advance to
`TRANSITIONED`. See INV-DP-DRAIN-1e for the mid-carrier release rule.

**Why positive over negative.** The negative gate (Rev-14) required a conjunction over
an unbounded enumeration of "not-in-branch-X" predicates. Empirically:
`_arbitrage_active = False` at `energy_battery.py:3157` (WAIT), `:4705` (envoy-blind
hold), AND `:5274` (drain-fallback itself); attain-reboot-release (`:4118/:4131`) and
grid-disconnect (`:4890`) never touch it either. Any of those non-drain branches would
satisfy the negative conjunction while the emitter's actual reserve floor is NOT
`max(reserve, current_offpeak_drain_target())` — DP would mispredict. The positive
stamp is EXHAUSTIVE BY CONSTRUCTION: only the drain-fallback branch sets it, only the
tick-top resets it, so `True` means "this tick's `_get_off_peak_decision` executed the
drain branch" — no enumeration required. Immune to future new branches (Bug Class #53
seam CLOSED).

**Ordering coherence.** `_decision_cycle_body` (energy.py:5534) runs, in order:
`period = self._tou.get_current_period()` (:5540) → **reset marker** (new, immediately
after :5540) → `determine_mode(...)` (:5573, which invokes `_get_off_peak_decision` and
stamps the marker True iff drain branch fires) → `_dp_decision_tick(...)` (:5628, which
calls the gate helper). The marker is therefore fresh and coherent for the gate.
Verified this session: `_dp_decision_tick` at :5628 is called AFTER `determine_mode` at
:5573; the shadow eval called from within `_dp_decision_tick` at `:4408-4414` runs even
LATER (same tick, after determine_mode).

### INV-DP-DRAIN-1e (stranded-carrier release — NEW at Rev-15, C-HIGH-2 fix)
Under any tick where the DP carrier is `TRANSITIONED` AND the branch gate reports
`False` (the strategy has moved on: arbitrage HOLD kicked in, an inclement hold
elevated, attain latched, etc.), DP MUST release the carrier so paused EVSEs are freed.
Mechanism: on `TRANSITIONED + gate-closed`, force `_revert = True` regardless of
`_drain_target` (which is None on that tick — the helper is not invoked when the gate
is closed). The revert path then invokes `_apply_dp_reversion(tou_period=period)` at
`energy.py:4550` and unpauses.

Rationale: the DP transition was predicated on "emitter in drain-fallback branch." When
that predicate becomes False, the transition's precondition no longer holds; keeping
EVSE paused would be an invalid held state (suppression-needs-a-discharge). Comparing
against the stamped `_dp_decision_soc` (a plausible alternative) would work while the
prior stamp remains valid, but forcing revert is stricter and simpler: the carrier's
job is done for this cycle; if the strategy re-enters drain-fallback on a later tick,
DP re-evaluates and re-transitions cleanly.

### INV-DP-DRAIN-1c (revert predicate consistency — unchanged from Rev-14)
Under any tick where the controller has just stamped `_dp_decision_soc = X`, the revert
comparison at `energy.py:4555` uses the SAME value X. The revert guard MUST keep both
None-checks: `if _soc is not None and _drain_target is not None and int(_soc) <= _drain_target:`.
When the gate is closed AND no prior stamp exists, `_drain_target` is None and the SOC
comparison skips; MUST_START_FORCED + paused-idle + INV-DP-DRAIN-1e's TRANSITIONED-gate-
closed force-revert still fire.

### INV-DP-DRAIN-2 (R1 pause ceiling preserved) — unchanged
`determine_battery_drain_actions(soc_threshold=...)` at `energy.py:5842` (EV) and
`:5977` (plugs) sources from `self._ev_battery_drain_soc` unchanged.

### INV-DP-DRAIN-3 (R3 ride-proof floor preserved) — unchanged
`_ev_battery_drain_soc` remains the ride-proof floor at `energy.py:3752`,
`energy_pool.py:954`, and `energy_pool.py:1435`. Byte-identical.

### INV-DP-DRAIN-4 (offpeak-drain live-apply — CONFIRMED) — unchanged
Live-apply via `EnergyCoordinator.set_offpeak_drain` at `energy.py:8645-8653`.

**DISSOLVED at Rev-15 (Rev-14 wording):**
- The three-predicate negative-conjunction definition of the gate is deleted. Only the
  positive stamp is load-bearing. The old predicate reads (`_arbitrage_active`,
  `_attain_active`, `_last_inclement_decision.hold_depth`) are NO LONGER READ by DP.
  They remain in the battery for their existing consumers unchanged.

Reviewer D writes a legal-config repro for any leak in INV-DP-DRAIN-1 / 1c / 1d / 1e / 2 / 3 / 4.

---

## 2. Institutional context verified

Paths under `custom_components/universal_room_automation/domain_coordinators/` unless
noted. All line numbers re-verified against source THIS SESSION (Rev-15).

* `docs/planning/AUDIT_excess_solar_and_evse_prior_art.md` — DP mechanism §6.
* **Rev-15 source of truth:** `scripts/probes/dp_drain_target_candidate_sim.py`
  (v4 rebuilt this cycle — see §3a). `in_drain_branch` is an INDEPENDENT fixture field
  (not derived from `arb/attain/hold_depth`) so the sim can express the load-bearing
  non-drain fixtures where the OLD negative predicates all pass but the drain branch
  did NOT run: **N5 arbitrage-WAIT, N6 envoy-blind hold, N7 attain-reboot-release,
  N8 peak-period**. Two candidates compared: **C4 (Rev-14 negative-inference)** — FAILS
  N5-N8; **C5 (Rev-15 positive-stamp)** — 12/12.
* `energy_drain_precedence.py` — `evaluate_dp_transition:609-735`; `TransitionInputs`.
  **NEW constant** `DP_REASON_EMITTER_NOT_DRAINING = "emitter_not_draining"` alongside
  existing `DP_REASON_*` (`:489-498`).
* `energy.py` —
  * **`_decision_cycle_body` at `:5534`.** TOU period bound at `:5540`. **Insert
    marker reset immediately after `:5540` and before `determine_mode` at `:5573`**
    (§3, ~1 LoC). `_dp_decision_tick(decision, period, ev_load_w)` called at `:5628`.
  * **R2 sites** (`_dp_decision_tick` at `:4326-4573`): `:4456` real tick;
    `:4522` `_DPAct`; `:4540` `_DPActRescan`; `:4555` revert predicate `_drain`.
  * **Shadow R2 site** `_run_dp_shadow_eval` at `:4195-4324`; `:4271` shadow
    `drain_target_soc = int(self._ev_battery_drain_soc)`. Called at `:4408-4414`
    (kill-switch OFF path), which runs BEFORE the off-peak gate at `:4416`. On
    peak/mid_peak ticks the marker is False (drain branch cannot fire outside
    off_peak; determine_mode's off-peak branch is what stamps it), so the positive
    stamp already correctly closes the shadow gate outside off-peak. **Belt-and-
    suspenders (C-HIGH-1):** additionally guard the shadow block on
    `tou_period == "off_peak"` — publish `shadow_reason="wrong_period"` outside
    off_peak so post-hoc investigation can distinguish "gate closed because peak"
    from "gate closed because non-drain branch during off-peak."
  * **R2-display:** `:3871` is R3 blind-window static payload (NOT a valid live
    source); correct live payload is
    `sensor.ura_energy_coordinator_ev_charging_plan.last_eval_snapshot.inputs.drain_target_soc`.
  * **`_apply_dp_transition` at `energy.py:4873`.** Unchanged.
  * **`_apply_dp_reversion` at `energy.py:4959`.** Unchanged.
  * **R1 sites:** `:5842` EV, `:5977` plug. Unchanged.
  * **R3 site:** `:3752`. Unchanged.
  * **Off-peak gate at `:4416`** — unchanged; single-read TOU discipline preserved.
  * **Compute site (per-tick truth for in-body R2 uses):** immediately after the
    blind-hold snapshot at `:4437-4447` and before `_DPInputs(...)` at `:4448` — see §3.
  * **Safety branches that MUST run when the gate closes:**
    * MUST_START_FORCED → `_revert = True` at `:4558-4559`;
    * paused-but-nothing-charging reconciliation at `:4560-4565`;
    * state-machine revert edge at `:4546-4550`;
    * **NEW (INV-DP-DRAIN-1e) — TRANSITIONED + gate-closed force-revert.**
    See containment §3.
  * `_ev_battery_drain_soc`: init `:441`, getter `:8730`, setter `:8732-8738` —
    unchanged.
  * **Setter for `_drain_targets` (INV-DP-DRAIN-4):** `set_offpeak_drain` at
    `energy.py:8645-8653`.
* `energy_pool.py` — R3 callers `:954`, `:1435`; helper `:619-648`. Unchanged.
* `energy_battery.py` —
  * `reserve_soc: int` at `:349`.
  * `_arbitrage_active: bool` init at `:483`. CLEARED at `:3157` (WAIT), `:4705`
    (envoy-blind hold), `:5274` (drain-fallback branch entry). VERIFIED THIS SESSION
    via `Grep _arbitrage_active\s*=\s*False` — exactly four hits (init + three
    clearing sites). This four-way ambiguity is why negative inference cannot work.
  * **`current_offpeak_drain_target():1726-1747`** — RULED source. Returns int
    unconditionally. Does NOT apply partial_hold clamp.
  * **`_offpeak_drain_branch_this_tick: bool = False`** — **NEW instance attr.**
    Init in `BatteryStrategy.__init__` (~1 LoC alongside `_arbitrage_active` at
    `:483`). Reset by the coordinator each tick (see energy.py above). Stamped True
    by the drain-fallback branch (see below).
  * **Drain-fallback branch: `:5269-5352`.** ADD `self._offpeak_drain_branch_this_tick
    = True` immediately after the existing `self._arbitrage_active = False` at
    `:5274` (~1 LoC). Rationale for THIS placement: the line is already the
    canonical "we are entering the drain-fallback branch" marker (existing comment at
    :5272-5273 calls it out); pairing the positive stamp there keeps the two markers
    lockstep and gives reviewers a single grep target.
  * **NB: this cycle now DOES modify `energy_battery.py` (~2 LoC).** The Rev-13/14
    "NO change to energy_battery.py" constraint is explicitly RELAXED at Rev-15,
    justified in the preamble and §10.
  * `evaluate_inclement` full_hold short-circuit at `:4903`; arbitrage gate
    short-circuit at `:5236-5246`; attain-branch short-circuit at `:5253-5267`;
    partial_hold clamp at `:5321-5322`. Cited for reviewer orientation; NONE are
    consulted by the Rev-15 gate.
* `energy_const.py` — same constants as Rev-14; unchanged.
* `sensor.py` — `sensor.ura_energy_coordinator_ev_charging_plan` emits
  `last_eval_snapshot.inputs.drain_target_soc` — correct live-validation attribute.
* **Extract-exec test harnesses (framing-C precedent).** Rev-15 build MUST extend BOTH
  name lists in each file AND stub the marker attr + accessor on ALL fake batteries:
  * `quality/tests/test_evse_drain_precedence_session_b2c1_fixup.py`:
    - Extracted-name set at `:208-223`. **ADD** `_dp_drain_target_soc` AND
      `_dp_emitter_in_drain_branch`.
    - Second name list at `:322-334`. **ADD the same two names.**
    - `_StubBattery` at `:250`: stub `reserve_soc: int = 10`,
      `current_offpeak_drain_target = lambda self: 10`,
      `_offpeak_drain_branch_this_tick: bool = True` (default the drain-branch
      fixtures to "in branch"; N-scenario fixtures set it False explicitly).
    - `_SpyBattery` at `:465` — has raising `__getattr__`; add
      `_offpeak_drain_branch_this_tick` EXPLICITLY on the class so `__getattr__` is
      not consulted for it.
    - `_Boom` at `:522`: `__getattr__` raises; gate helper's try/except returns
      False (declines safely). No stub required, but tests that expect drain-branch
      behavior against `_Boom` must add the attr explicitly.
    - **Reset-site fixtures:** tests that drive `_decision_cycle_body` end-to-end
      must NOT pre-set the marker on the coordinator's battery — the reset site
      will overwrite it. Set it AFTER the reset or drive through the full path.
  * `quality/tests/test_evse_drain_precedence_session_b2c2_fixup.py` — same shape.
  * `quality/tests/test_baec_shadow_eval.py:34-42` — inherit via b2c1 or re-add.
* Memory: `project_ev_drain_precedence_cycle`, `feedback_hollow_test_anchors`,
  `feedback_mutation_verification_pycache_staleness`, `feedback_suppression_needs_discharge`
  (INV-DP-DRAIN-1e).
* **Live values (Rev-11 verified):**
  - `number.ura_energy_coordinator_ev_battery_drain_soc = 80`.
  - `sensor.ura_energy_coordinator_battery_strategy.current_offpeak_drain_target = 10`.
  - `reserve_soc = 10`.

---

## 3. Deliverable

### Full R2 emission-site table

| Site | Where | Class | Change |
|---|---|---|---|
| `energy.py:4271` | Shadow `TransitionInputs` (inside `_run_dp_shadow_eval`) | **R2 (shadow)** | `tou_period=="off_peak"` guard + branch-gate check + `_dp_drain_target_soc(period)`; on wrong period publish `shadow_reason="wrong_period"`; on gate-closed publish `shadow_reason="emitter_not_draining"`; on None publish `shadow_reason="drain_target_unavailable"`. Do NOT raise. |
| `energy.py:4456` | Real tick `TransitionInputs` | **R2** | Use per-tick `_drain_target` local, inside gated block |
| `energy.py:4522` (`_DPAct`) | Fresh-TRANSITIONED actuation | **R2** | Use per-tick `_drain_target`, inside gated block |
| `energy.py:4540` (`_DPActRescan`) | Second-plug rescan | **R2** | Use per-tick `_drain_target`, inside gated block |
| `energy.py:4555` (`_drain`) | Revert predicate | **R2 (revert consistency)** | Use per-tick `_drain_target`; keep two-part None guard; **NEW: force-revert on TRANSITIONED+gate-closed** (INV-DP-DRAIN-1e) |
| `energy.py:3871` | R3 blind-window static payload | R3-display | Unchanged |
| `energy.py:4021` region | DP eval decision-log | R2-display | Auto-follows |
| `energy.py:4873` (`_apply_dp_transition`) | Stamp site | R2 consumer | No change |
| `energy.py:3752` / `energy_pool.py:954` / `:1435` | R3 | R3 | Unchanged |
| `energy.py:5842` / `:5977` | R1 | R1 | Unchanged |

### Battery-side edits (`energy_battery.py`) — **RELAXATION of Rev-13/14 constraint**

**Edit 1 — init the marker** (in `BatteryStrategy.__init__`, adjacent to `:483`):
```python
self._arbitrage_active = False
# Rev-15: positive-stamp marker for the DP branch gate. Reset each tick
# by EnergyCoordinator._decision_cycle_body (energy.py, immediately after
# `period = self._tou.get_current_period()` at :5540). Set True below at
# :5274 (drain-fallback branch entry). See PLANNING §1 INV-DP-DRAIN-1d.
self._offpeak_drain_branch_this_tick: bool = False
```

**Edit 2 — stamp the marker** (in `_get_off_peak_decision`, at `:5274`):
```python
# v4.5.0 also clears the in-memory arbitrage flag so HOLD residue
# doesn't carry over after the gate closes.
self._arbitrage_active = False
# Rev-15: positive stamp for DP branch gate (INV-DP-DRAIN-1d). This is
# the SOLE setter site. Coordinator resets to False each tick before
# calling determine_mode. When DP consults the marker later this tick,
# True proves the drain-fallback branch actually ran — not inferred from
# absence of competing branches (which was ambiguous — _arbitrage_active
# is cleared to False at :3157/:4705/:5274 alike).
self._offpeak_drain_branch_this_tick = True
```

**No other `energy_battery.py` change.** In particular the branch-gate does NOT read
`_arbitrage_active`, `_attain_state`, or `_last_inclement_decision.hold_depth` — those
are unchanged in behaviour and readable by their existing consumers.

### Coordinator-side reset (`energy.py`, in `_decision_cycle_body`)

Immediately after `period = self._tou.get_current_period()` at `:5540` and before
`self._battery.determine_mode(...)` at `:5573`:

```python
# Rev-15: reset the positive-stamp marker BEFORE determine_mode runs.
# determine_mode may re-set it True if _get_off_peak_decision enters
# the drain-fallback branch (energy_battery.py:5274). The gate (invoked
# later this tick from _dp_decision_tick) reads the resulting value.
# Defensive: if _battery raises on attr set, log and continue — the
# gate helper defaults to False on read error (declines DP safely).
try:
    self._battery._offpeak_drain_branch_this_tick = False  # noqa: SLF001
except Exception:  # noqa: BLE001
    _LOGGER.debug("DP branch-gate marker reset failed (swallowed)", exc_info=True)
```

### `_dp_emitter_in_drain_branch()` helper on `EnergyCoordinator` (NEW)

```python
def _dp_emitter_in_drain_branch(self) -> bool:
    """Rev-15 positive-stamp branch gate. True iff the off-peak emitter's
    drain-fallback branch (energy_battery.py:5269-5352) actually ran on
    THIS tick, as evidenced by the positive stamp set at energy_battery.py:5274.

    Reset each tick in _decision_cycle_body BEFORE determine_mode; set True
    inside the drain-fallback branch itself. The stamp is EXHAUSTIVE BY
    CONSTRUCTION — no branch enumeration required, immune to any future new
    strategy branch (Bug Class #53 seam closed by construction).

    Defensive: on any exception, return False. Declining DP is the safe
    direction (operator ruling: "DP and Attain are almost mutually exclusive
    in practice"; a DP-off tick is not a regression).
    """
    try:
        return bool(getattr(self._battery, "_offpeak_drain_branch_this_tick", False))
    except Exception:  # noqa: BLE001
        return False
```

### `_dp_drain_target_soc(period)` helper on `EnergyCoordinator` (NEW)

Body unchanged from Rev-14 (invoked only when the gate is open).

```python
def _dp_drain_target_soc(self, tou_period: str) -> int | None:
    """DP drain-target source: mirror the emitter's drain-fallback branch.
    Caller MUST check self._dp_emitter_in_drain_branch() first —
    this helper does not self-gate.

    Returns max(reserve_soc, current_offpeak_drain_target()) with the
    operator-ruled safety floor at reserve_soc. reserve_soc read
    defensively via getattr; if None, accessor alone. NEVER `or 0`.

    Returns None only if the accessor itself raises AND reserve_soc is None.
    Callers MUST treat None as "skip R2 consumption this tick" without
    disturbing safety branches.
    """
    battery = self._battery
    try:
        drain = int(battery.current_offpeak_drain_target())
    except Exception:  # noqa: BLE001
        drain = None
    reserve = getattr(battery, "reserve_soc", None)
    if drain is None and reserve is None:
        return None
    if drain is None:
        return int(reserve)
    if reserve is None:
        return int(drain)
    return int(max(reserve, drain))
```

### New constant `DP_REASON_EMITTER_NOT_DRAINING` (C-LOW-1 fix)

Add to `energy_drain_precedence.py` alongside `DP_REASON_*` (`:489-498`):
```python
DP_REASON_EMITTER_NOT_DRAINING = "emitter_not_draining"
```
**All caller code MUST reference the constant, not the raw string** (C-LOW-1). The
shadow-path `shadow_reason` string is also emitted through the same constant.

### Containment shape — compute lazily, gate consumers, safety branches always run

Immediately after the blind-hold snapshot at `:4437-4447` and before `_DPInputs(...)`
at `:4448`, insert:

```python
# Rev-15: positive-stamp branch gate + single per-tick DP drain target.
# See _dp_emitter_in_drain_branch + _dp_drain_target_soc docstrings +
# PLANNING §1 (INV-DP-DRAIN-1, -1d, -1e) for the invariants.
from .energy_drain_precedence import DP_REASON_EMITTER_NOT_DRAINING
_in_drain_branch = self._dp_emitter_in_drain_branch()
_drain_target = self._dp_drain_target_soc(period) if _in_drain_branch else None
if not _in_drain_branch:
    _dp_decline_reason = DP_REASON_EMITTER_NOT_DRAINING
elif _drain_target is None:
    _dp_decline_reason = "drain_target_unavailable"
    _LOGGER.warning(
        "DP: drain target unavailable (current_offpeak_drain_target raised "
        "AND reserve_soc None); skipping fit evaluation, safety branches "
        "still active"
    )
else:
    _dp_decline_reason = None
```

Consumption gate — wrap `:4448-4542` in `if _drain_target is not None:`; on the skipped
path still emit the decision-log row via `_log_dp_eval_decision` carrying
`reason=_dp_decline_reason`.

**Revert predicate (`:4555`) — INV-DP-DRAIN-1e added:**

```python
_revert = False
if self._dp_carrier.state == _DPState.TRANSITIONED:
    if _soc is not None and _drain_target is not None and int(_soc) <= _drain_target:
        _revert = True
    # Rev-15 INV-DP-DRAIN-1e: TRANSITIONED + gate-closed = strategy has
    # moved on (arbitrage HOLD, inclement elevation, attain latch, envoy-
    # blind hold, etc.). The transition's precondition no longer holds;
    # release the carrier so paused EVSEs are freed. Comparing against a
    # stale _dp_decision_soc would keep EVSE paused across a strategy
    # change (suppression-needs-a-discharge). Force revert.
    if not _in_drain_branch:
        _revert = True
if self._dp_carrier.state == _DPState.MUST_START_FORCED:
    _revert = True
if (
    self._dp_carrier.state == _DPState.TRANSITIONED
    and not self._ev._paused_by_dp  # noqa: SLF001
    and not self._is_any_evse_charging()
):
    _revert = True
```

Keep both None-guards on the `_soc <= _drain_target` comparison.

**Shadow site containment (`:4271`) — C-HIGH-1 belt-and-suspenders:**

```python
# Inside _run_dp_shadow_eval, replacing the int(self._ev_battery_drain_soc) at :4271.
from .energy_drain_precedence import DP_REASON_EMITTER_NOT_DRAINING
if period != "off_peak":
    # C-HIGH-1: shadow eval called at :4408 runs BEFORE the off-peak gate
    # at :4416. Guard here so peak/mid_peak ticks publish a distinct
    # reason for post-hoc investigation. The positive stamp alone would
    # also close the gate (determine_mode's off-peak branch is what
    # stamps it, and that branch does not run outside off-peak), but the
    # explicit period guard is clearer and future-proofs against any
    # future path that might stamp outside off-peak.
    self._dp_carrier.shadow_decision = "not_applicable"
    self._dp_carrier.shadow_reason = "wrong_period"
    self._dp_carrier.shadow_last_eval_at = now
    self._dp_carrier.shadow_last_eval_snapshot = {}
    return
_shadow_in_drain = self._dp_emitter_in_drain_branch()
if not _shadow_in_drain:
    self._dp_carrier.shadow_decision = "not_applicable"
    self._dp_carrier.shadow_reason = DP_REASON_EMITTER_NOT_DRAINING
    self._dp_carrier.shadow_last_eval_at = now
    self._dp_carrier.shadow_last_eval_snapshot = {}
    return
_shadow_drain = self._dp_drain_target_soc(period)
if _shadow_drain is None:
    self._dp_carrier.shadow_decision = "not_applicable"
    self._dp_carrier.shadow_reason = "drain_target_unavailable"
    self._dp_carrier.shadow_last_eval_at = now
    self._dp_carrier.shadow_last_eval_snapshot = {}
    return
inputs = _DPInputs(
    ...
    drain_target_soc=int(_shadow_drain),
    ...
)
```

**TOU period — ONE read per tick** (unchanged from Rev-14). Bound at
`_decision_cycle_body:5540`, passed through.

**Producer / Consumer + call-site check.**
- **PRODUCER of the positive stamp:** `energy_battery.py:5274` (drain-fallback branch
  entry, SOLE setter). Dependencies: the branch itself running, which depends on TOU
  being off_peak and the branch matrix at `:5236-5267` (arbitrage / attain
  short-circuits both fall through only if their gates decline). Health: stamped iff
  drain branch runs; not stamped otherwise. **PRODUCER of the reset:**
  `energy.py:_decision_cycle_body` immediately after `:5540` (SOLE resetter).
- **CONSUMERS of the stamp:** `_dp_emitter_in_drain_branch()` (SOLE reader; trust-
  decision). Zero display-only readers. If a future consumer is added, it MUST reset
  at its own tick boundary or accept the coordinator's reset semantics.
- **PRODUCER of the drain-target value:** `current_offpeak_drain_target()` unchanged.
- **Should-be-consuming-but-isn't.** Deferred to post-ship supersession + consumer audit.

**Hold-demotion — OUT OF SCOPE.**

**Files changed.**
* `energy_battery.py` — **NEW at Rev-15:**
  * init `_offpeak_drain_branch_this_tick: bool = False` at ~`:483` (~1 LoC).
  * stamp `self._offpeak_drain_branch_this_tick = True` at `:5274` (~1 LoC).
* `energy.py` —
  * reset marker in `_decision_cycle_body` after `:5540` (~5 LoC with try/except).
  * add `_dp_emitter_in_drain_branch()` helper (~7 LoC).
  * add `_dp_drain_target_soc()` helper (~20 LoC).
  * insert branch-gate + compute + reason block after `:4447` (~15 LoC).
  * wrap `:4448-4542` in `if _drain_target is not None:` and substitute `_drain_target`
    at `:4456`, `:4522`, `:4540`.
  * substitute `_drain_target` at revert `:4555`; add INV-DP-DRAIN-1e force-revert.
  * `_log_dp_eval_decision` on skip path carries `reason=_dp_decline_reason`.
  * in `_run_dp_shadow_eval`, replace `int(self._ev_battery_drain_soc)` at `:4271`
    with the wrong-period + branch-gate + `_dp_drain_target_soc(period)` block.
* `energy_drain_precedence.py` — add `DP_REASON_EMITTER_NOT_DRAINING` constant.
* Test harnesses per §2 — extend name lists; add stubs + marker attr on all fake batteries.
* New tests per §7.

---

## 3a. Candidate simulation record (Rev-15 — rebuilt this cycle, C-HIGH-3 fix)

`scripts/probes/dp_drain_target_candidate_sim.py` (v4). Rebuilt HONESTLY:

- **`in_drain_branch` is an INDEPENDENT fixture field**, set BY HAND per scenario, NOT
  derived from any candidate's predicates. This closes C-HIGH-3 (Rev-14 sim's
  tautology — `in_drain_branch` was computed from `(not arb) and (not attain) and
  hold_depth=="allow_discharge"`, the exact predicate the Rev-14 candidate C4
  consumed, so C4 trivially matched the oracle on every fixture by construction).
- **Non-drain fixtures where the OLD negative predicates all pass** (the load-bearing
  additions):
  - **N5 arbitrage WAIT** — `arb=False, attain=False, hold_depth=allow_discharge` (all
    "allow drain" per Rev-14), but `_get_arbitrage_decision` returned WAIT and set
    `_arbitrage_active=False` at `energy_battery.py:3157`; the drain-fallback branch
    at `:5274` never ran, so `in_drain_branch=False`. Rev-14 C4 sees the negative
    predicates all satisfied and would ACT — WRONG.
  - **N6 envoy-blind hold** — early return at `:4696-4706` with
    `_arbitrage_active=False`, no branch ran. Rev-14 C4 acts — WRONG.
  - **N7 attain-reboot-release** — attain-reboot path returns at `:4118/:4131` before
    the drain branch; `_arbitrage_active` untouched from prior tick (could be False),
    `_attain_active=False` post-release. Rev-14 C4 acts — WRONG.
  - **N8 peak-period** — `_get_off_peak_decision` not invoked at all; drain branch
    could not have run. Rev-14 C4 with `hold_depth=allow_discharge` and no arb/attain
    would still ACT — WRONG. (In production the off-peak gate at `energy.py:4416`
    would separately close DP; but as a source predicate C4 is wrong.)
- **C5 (Rev-15 positive-stamp candidate)** = `("act", max(reserve, drain)) if
  in_drain_branch else ("decline", None)`. Reads the independent fixture field
  directly (mirrors the production positive stamp).

Two oracles as in Rev-14 (ORACLE-A strict emitter, ORACLE-B RULED formula); D4
divergence unchanged (operator-ruled safety floor, no-op under live config).

Scorecard (12 fixtures — D1-D4 drain + N1-N8 non-drain):

| Candidate | ORACLE-A | ORACLE-B | Blocking failure |
|---|---|---|---|
| C0 static knob (pre-fix bug) | **0/12** | **0/12** | Acts everywhere with wrong value |
| C1 compose/park (BUILT, no gate) | **1/12** | **1/12** | Overlay pin; acts in all non-drain |
| C2 accessor alone (no gate) | **4/12** | **3/12** | Acts in all 8 non-drain |
| C3 RULED (Rev-13, no gate) | **3/12** | **4/12** | Acts in all 8 non-drain |
| C4 RULED + negative-inference gate (Rev-14) | **7/12** | **8/12** | Correctly declines N1-N4; **INCORRECTLY ACTS on N5 (WAIT), N6 (envoy-blind), N7 (attain-reboot-release), N8 (peak-period)** — the four fixtures where the negative predicates all pass but the drain branch did NOT run. Load-bearing C-CRIT-1 leak. |
| **C5 RULED + positive-stamp gate (Rev-15 proposal)** | **11/12** | **12/12** | Only D4 divergence from ORACLE-A remains (operator-ruled safety floor, no-op live). Correct on ALL 8 non-drain fixtures BY CONSTRUCTION — reads the fixture's independent `in_drain_branch` field, which mirrors the production positive stamp. |

**Reading the scorecard.** C4's four losses (N5-N8) are the exact reason Rev-14 was
rejected: the negative predicates cannot distinguish "drain branch ran" from four
other non-drain branches that also leave the predicates satisfied. C5's clean 12/12
under ORACLE-B is not a tautology this time: `in_drain_branch` is set BY HAND per
scenario, not derived from any of the candidate's inputs. C5 wins because the
production positive stamp is EXHAUSTIVE by construction, and the sim honestly
represents that (a fixture explicitly says "the drain branch ran" or "it didn't"; the
gate reads that fact directly rather than inferring it).

---

## 3b. Acceptance criteria

Each observation is chosen to DISCRIMINATE the fix from a plausible different failure.

- **Verify (drain-fallback branch, source, discriminating):** fresh DP tick with
  `_offpeak_drain_branch_this_tick=True` (drain branch fired), `reserve_soc=10`,
  `current_offpeak_drain_target()=10`, SOC=40, off-peak:
  `TransitionInputs.drain_target_soc == 10`; `_dp_decision_soc == 10`. Discriminates
  from static-knob bug (would emit 80) and compose/park (would emit 65 under EVSE hold).
- **Verify (mirror-the-emitter under EVSE hold):** `_evse_hold_soc=65`, SOC=40,
  accessor=10, `reserve_soc=10`, `_offpeak_drain_branch_this_tick=True`: DP drain
  target reads **10** (accessor), NOT 65.
- **Verify (positive-stamp — arbitrage WAIT, load-bearing at Rev-15):** arbitrage
  strategy returned WAIT this tick, `_arbitrage_active=False` (set at :3157),
  `_offpeak_drain_branch_this_tick=False` (drain branch never ran): DP does NOT
  populate `TransitionInputs`; decision-log carries
  `reason == DP_REASON_EMITTER_NOT_DRAINING`. Discriminating counter-fixture: force
  drain-branch to fire (fixture flips stamp True) → DP transitions. Rev-14 negative-
  inference gate would have opened here.
- **Verify (positive-stamp — envoy-blind hold):** envoy unavailable, early return at
  :4696-4706 with `_arbitrage_active=False`, `_offpeak_drain_branch_this_tick=False`:
  DP declines. Rev-14 gate would open.
- **Verify (positive-stamp — attain-reboot-release):** attain reboot returned via
  `:4131`, `_offpeak_drain_branch_this_tick=False`: DP declines. Rev-14 gate would
  open (both `_arbitrage_active` and `_attain_active` become False).
- **Verify (positive-stamp — peak-period):** peak tick, drain branch not invoked,
  stamp remains False from reset: DP declines with `wrong_period` (shadow) or
  `emitter_not_draining` (main path if it were reached).
- **Verify (positive-stamp — arbitrage HOLD/CHARGE, attain latched, inclement
  partial_hold/full_hold):** each case the drain branch does not run,
  `_offpeak_drain_branch_this_tick=False`: DP declines with
  `DP_REASON_EMITTER_NOT_DRAINING`.
- **Verify (INV-DP-DRAIN-1e — stranded-carrier release):** DP transitioned on tick T
  (drain branch ran, stamp True); on tick T+1 arbitrage HOLD kicks in (drain branch
  does not run, stamp resets False), carrier is TRANSITIONED, EVSE is
  `_paused_by_dp`: assert `_revert=True` fires via the new gate-closed branch;
  `_apply_dp_reversion` runs; EVSE released. Discriminates from "stranded" (paused
  EVSE never releases under Rev-14 None-guard semantics).
- **Verify (reset ordering):** in `_decision_cycle_body`, the marker is reset to
  False BEFORE `determine_mode` is called. Assertion: mock the battery so the reset
  side-effect is observable; call `_decision_cycle_body`; check marker was False
  when `determine_mode` was entered. Counter-fixture: reset placed AFTER
  determine_mode → drain-branch tick's stamp gets overwritten → gate stays False on
  every tick → DP never transitions → T1-T1d fail (safety-direction failure, still
  detectable).
- **Verify (accessor-consistent inside drain branch):** `hold_depth=allow_discharge`
  under WATCH-only inclement decision, drain branch fires, stamp True; DP mirrors
  accessor.
- **Verify (no same-tick actuate-then-revert):** SOC=40, drain target=10, stamp True,
  fresh TRANSITIONED does NOT revert same tick (`:4555` sees 10, not 80).
- **Verify:** R1 (`:5842`, `:5977`) STATIC knob unchanged.
- **Verify:** R3 (`:3752`, `energy_pool.py:954/1435`) unchanged.
- **Verify (containment — B/D-HIGH-1):** when the gate is closed OR `_dp_drain_target_soc`
  returns None: `_DPInputs`+`_dp_tick`+actuation+rescan skipped; MUST_START_FORCED
  revert (`:4558-4559`), paused-idle reconciliation (`:4560-4565`), state-machine
  revert edge (`:4546-4550`), and INV-DP-DRAIN-1e force-revert STILL RUN.
- **Verify (shadow containment):** on the shadow path — wrong-period publishes
  `shadow_reason="wrong_period"` EXACTLY; gate-closed publishes
  `shadow_reason=DP_REASON_EMITTER_NOT_DRAINING` EXACTLY; None-target publishes
  `shadow_reason="drain_target_unavailable"` EXACTLY. Shadow does NOT raise.
- **Verify (C-LOW-1 — constant reference):** grep production source for the raw string
  `"emitter_not_draining"` — zero hits outside `energy_drain_precedence.py`'s constant
  definition. All callers reference `DP_REASON_EMITTER_NOT_DRAINING`.
- **Test:** T1, T1b, T1c, T1d, T2, T2b, T3, T4, T4b, T5, T6, T7a-h (§7).
- **Live (correct source):** with an EV plugged during off-peak AND drain branch
  running, read
  `sensor.ura_energy_coordinator_ev_charging_plan.last_eval_snapshot.inputs.drain_target_soc`
  = `max(reserve_soc, current_offpeak_drain_target())` (expected 10).
- **Live (paired, discriminating):** DP carrier `TRANSITIONED` AND `_dp_decision_soc`
  non-None on tick T; `_dp_decision_soc == max(reserve, accessor)` on tick T.
- **Live (gate-closed reason surfaces):** during a known arbitrage HOLD/CHARGE or
  inclement partial_hold/full_hold or WAIT window, DP decision-log carries
  `reason == DP_REASON_EMITTER_NOT_DRAINING` AND carrier in `HOLD_ONLY`. If no
  natural window occurs, proved in-suite (T7a-h) with fact noted in validation table.
- **Live (stranded-carrier release, INV-DP-DRAIN-1e):** if a natural mid-carrier
  strategy change occurs (e.g. inclement upgraded partial→full mid-off-peak), DP
  releases the carrier and unpauses EVSE within one decision cycle. If no natural
  occurrence, proved in-suite (T7-strand).

---

## 4. Non-goals

Unchanged from Rev-14 (evse_battery_hold demotion; changing live drain-soc knob;
R1/R3 sourcing; init/getter/setter of `_ev_battery_drain_soc`; DP gate arithmetic;
`compose_release_floor` / `current_park_floor()` re-wiring; adding
`current_desired_release_floor()`; reading `_last_reserve_level_desired`;
cross-midnight staleness). Rev-15 additions:

* NOT restoring the Rev-13/14 "no-change-to-energy_battery.py" constraint. Rev-15
  explicitly relaxes it (~2 LoC, justified in preamble + §10).
* NOT extending DP into partial_hold with a partial_hold-clamped target — same park.
* NOT reading `_arbitrage_active`, `_attain_state`, or `_last_inclement_decision`
  from DP. The gate is the positive stamp only.

---

## 5. Known couplings

1-7 unchanged from Rev-14.
8. **Reset-then-set ordering.** The reset in `_decision_cycle_body` (immediately after
   `:5540`) MUST run BEFORE `determine_mode` at `:5573`. A builder who moves the
   reset AFTER `determine_mode` will overwrite the drain-branch's stamp every tick;
   DP will never transition. Test T-reset-order anchors this.
9. **Extract-exec harnesses.** Any fake battery consumed by tests that drive
   `_decision_cycle_body` (rather than calling `_dp_decision_tick` directly) will
   have `_offpeak_drain_branch_this_tick` reset to False before the fake `determine_mode`
   runs. Fake `determine_mode` implementations that want to simulate "drain branch
   fired" must set the marker True themselves.
10. **Future battery-side branches.** Any NEW branch inside `_get_off_peak_decision`
    that emits a floor equal to `max(reserve, current_offpeak_drain_target())` (an
    equivalent-drain branch) MUST also stamp `_offpeak_drain_branch_this_tick = True`
    if DP should transition on that path. Any new branch that emits a DIFFERENT
    floor must NOT stamp. The stamp is the contract.

---

## 6. Docs drift to fix in-cycle

Unchanged targets from Rev-14, with Rev-15 addendum:

* `docs/user-manual/ENERGY_COORDINATOR.md:642` — R2 role + positive-stamp branch-gate
  contract.
* `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md:455`.
* `docs/planning/PLANNING_evse_drain_precedence.md` — bind `drain_target` symbol to
  the Rev-15 positive-stamp branch-gated source.
* `docs/planning/PLANNING_inclement_weather_reserve.md:66,82` — stale line refs.

INV-DP-DRAIN-4 confirmed live-apply.

---

## 7. Test plan summary

Behavioural, MUTATION-VERIFIED. `PYTHONDONTWRITEBYTECODE=1` and clear `__pycache__`.

**Fixture contract — Rev-15 binding.**
* **All asserted drain-target values 4-way distinct** from `reserve_soc`, static
  `_ev_battery_drain_soc` (80), `current_offpeak_drain_target()`, and
  `_last_reserve_level`.
* Every drain-branch fixture MUST set `_offpeak_drain_branch_this_tick=True` on the
  fake battery (or drive through a real `determine_mode` path that stamps it).
* Every non-drain fixture MUST set `_offpeak_drain_branch_this_tick=False`.

**Rev-15 discriminating scenarios (drain-branch):**
1. EVSE-hold with captured SOC above accessor floor, stamp True. Assert
   `_dp_drain_target_soc==10`.
2. Multi-day D+1!=D+2, stamp True. Assert `_dp_drain_target_soc==25`.
3. Inclement `allow_discharge` under WATCH, stamp True. Assert accessor mirror.
4. `reserve_soc=15`, accessor=10, stamp True. Assert `_dp_drain_target_soc==15`.
5. Boot — accessor raises, `reserve_soc=15`, stamp True. Assert `_dp_drain_target_soc==15`.

**Rev-15 branch-gate scenarios (all → DP declines with `DP_REASON_EMITTER_NOT_DRAINING`):**
- **N1** arbitrage HOLD (stamp False, `_arbitrage_active=True`).
- **N2** attain latched (stamp False, `_attain_active=True`).
- **N3** inclement partial_hold (stamp False, `hold_depth=partial_hold`).
- **N4** inclement full_hold (stamp False, `hold_depth=full_hold`).
- **N5 arbitrage WAIT (Rev-15 load-bearing)** — stamp False, `_arbitrage_active=False`
  (cleared at :3157), `_attain_active=False`, `hold_depth=allow_discharge`. All Rev-14
  negative predicates satisfied; drain branch did not run.
- **N6 envoy-blind hold** — stamp False, `_arbitrage_active=False` (cleared at :4705),
  `_attain_active=False`, `hold_depth=allow_discharge`. Rev-14 gate opens; Rev-15 declines.
- **N7 attain-reboot-release** — stamp False, `_arbitrage_active=False`,
  `_attain_active=False` (post-release), `hold_depth=allow_discharge`. Rev-14 gate
  opens; Rev-15 declines.
- **N8 peak-period** — stamp False (reset each tick, drain branch not invoked outside
  off_peak); shadow publishes `wrong_period` (also exercised).

**Rule (framing C): a test NEVER contains its own mutation.**

* **T1 (`:4456`):** scenario 1 sans EVSE hold; assert `TransitionInputs.drain_target_soc == 10`. Anchor **C1, C7**.
* **T1b (`:4271` shadow, kill-switch OFF):** assert snapshot `inputs.drain_target_soc == 10`. Anchor **C6**.
* **T1c (`:4522`):** assert `_dp_decision_soc == 10`. Anchor **C3**.
* **T1d (`:4540`):** idempotent second-plug rescan. Anchor **C4**.
* **T2 (revert consistency):** post-TRANSITIONED SOC=40, `_dp_decision_soc=10`;
  assert `_revert=False`. Anchor **C5**.
* **T2b (mirror-emitter under EVSE hold):** scenario 1 with hold. Assert 10 not 65. Anchor **C11**.
* **T3 (R1 preserved):** unchanged. Anchor **C2**.
* **T4 (R3 preserved, `:3752`):** unchanged. Anchor **C8**.
* **T4b (R3 preserved, `energy_pool.py`):** unchanged. Anchors **C9, C10**.
* **T5 (off-peak drain live-apply):** unchanged. Anchor **C12**.
* **T6 (containment — safety branches survive None):** unchanged shape; add explicit
  assertion that INV-DP-DRAIN-1e force-revert branch executes on TRANSITIONED+stamp=False.
* **T7a (N1 arb HOLD):** stamp False, `_arbitrage_active=True`; assert decline. Anchor **C13a**.
* **T7b (N2 attain):** stamp False, `_attain_active=True`; assert decline. Anchor **C13b**.
* **T7c (N3 partial_hold):** stamp False, `hold_depth=partial_hold`; decline. Anchor **C13c**.
* **T7d (N4 full_hold):** stamp False, `hold_depth=full_hold`; decline. Anchor **C13d**.
* **T7e (shadow gate — N1):** kill-switch OFF; shadow_reason equality. Anchor **C6b**.
* **T7f (N5 WAIT — Rev-15 load-bearing):** stamp False, all Rev-14 negative predicates
  satisfied; assert decline. **Anchor C13e** — the mutation is "force
  `_dp_emitter_in_drain_branch` to return True unconditionally"; T7f MUST fail on
  that mutation. This is the primary evidence that Rev-15 fixes C-CRIT-1.
* **T7g (N6 envoy-blind):** stamp False; assert decline. Anchor **C13f**.
* **T7h (N7 attain-reboot-release):** stamp False; assert decline. Anchor **C13g**.
* **T-reset-order:** drive `_decision_cycle_body` end-to-end with a spy that records
  the marker value observed at entry to `determine_mode`; assert the value seen was
  False (reset ran first). Mutation anchor **C-reset**: move reset AFTER
  determine_mode → assertion fails.
* **T-strand (INV-DP-DRAIN-1e):** tick T stamps True + transitions; tick T+1 stamps
  False + carrier TRANSITIONED + EVSE `_paused_by_dp`; assert `_revert=True` fires
  via the new branch; assert `_apply_dp_reversion` called; assert EVSE released.
  Mutation anchor **C-strand**: remove the `if not _in_drain_branch: _revert = True`
  line → assertion fails.
* **T-shadow-wrong-period (C-HIGH-1):** peak-period shadow call; assert
  `shadow_reason == "wrong_period"` EXACTLY. Mutation anchor **C-wrong-period**:
  remove the period guard → publishes `emitter_not_draining` instead → assertion
  fails on equality.
* **T-const-ref (C-LOW-1):** grep-based test asserting no raw `"emitter_not_draining"`
  string outside `energy_drain_precedence.py` constant definition line.

---

## 8. Review plan — Tier 3

A/B/C/D framings per Tier-3 protocol. **Rev-15 re-review REQUIRED** — the gate
mechanism changed from negative inference to positive stamp; Rev-14 C-CRIT-1/1b are
DISSOLVED by construction. Two plan reviews before build (completeness + adversarial
build-prediction). Orchestrator pre-deploy verification mandatory. Operator checkpoint
BEFORE deploy.

**Mutation drills — REAL per-site source mutation, ONE at a time, restore after each.**

- **C1-C10** unchanged from Rev-14.
- **C11** unchanged (park-floor swap discriminator).
- **C12** unchanged (T5 setter anchor).
- **C13a-d** unchanged (branch-gate returns True → T7a-d fail).
- **C13e (N5 WAIT — Rev-15):** `_dp_emitter_in_drain_branch → return True` → **T7f fails.**
- **C13f (N6 envoy-blind — Rev-15):** same mutation → **T7g fails.**
- **C13g (N7 attain-reboot-release — Rev-15):** same mutation → **T7h fails.**
- **C-reset (Rev-15):** move the reset AFTER `determine_mode` → **T-reset-order fails**
  AND T1/T1b/T1c/T1d/T2b fail (stamp always overwritten, gate never opens).
- **C-strand (Rev-15):** remove `if not _in_drain_branch: _revert = True` → **T-strand fails.**
- **C-wrong-period (Rev-15):** remove period guard from shadow → **T-shadow-wrong-period fails.**
- **C-stamp-site (Rev-15, load-bearing):** remove the `self._offpeak_drain_branch_this_tick
  = True` line at `energy_battery.py:5274` → all drain-branch tests (T1, T1b, T1c,
  T1d, T2, T2b) fail — the marker never transitions True → gate never opens → DP
  never transitions. This mutation proves the stamp is load-bearing at the source.
- **C-init-drift (Rev-15):** delete the init `_offpeak_drain_branch_this_tick: bool
  = False` at `energy_battery.py:~483` → on a boot tick before any reset runs, the
  attr is missing → `getattr(..., False)` default kicks in → safe direction (decline)
  → no user-visible failure. Documented as SAFE-BY-CONSTRUCTION rather than a
  mutation anchor.

All twenty-plus mutations must bite where asserted (C1-C6, C6b, C7-C12, C13a-g,
C-reset, C-strand, C-wrong-period, C-stamp-site).

Framing hints for reviewers:
* **A** — local correctness of both helpers; revert-guard None-safety; INV-DP-DRAIN-1e
  force-revert arithmetic; new constant wiring.
* **B** — integration / containment: reset-then-set ordering; MUST_START_FORCED +
  paused-idle + shadow paths under gate-closed AND helper=None AND
  TRANSITIONED+gate-closed; TOU-period single-read; shadow wrong-period path.
* **C** — REAL per-site source mutation (C1-C13g, C-reset, C-strand, C-wrong-period,
  C-stamp-site); harness updates; fake-battery stubs on all three
  (`_StubBattery`/`_SpyBattery`/`_Boom`) INCLUDING the marker attr.
* **D** — adversarial completeness: falsify INV-DP-DRAIN-1 / 1d / 1e across the whole
  DP surface; re-enumerate emission sites + stamp sites (there MUST be exactly one
  stamp site and one reset site — audit the source). Any additional path that stamps
  the marker True outside the drain-fallback branch is a load-bearing leak (would
  falsely open the gate). Any additional path that resets the marker mid-tick is
  also a leak (would falsely close the gate). Legal-config repro required for every
  flagged leak.

---

## 9. REUSE vs NEW

* R1/R3 unchanged (`_ev_battery_drain_soc`).
* `evaluate_dp_transition` gate arithmetic — REUSE.
* `compose_release_floor` / `current_park_floor()` — REUSE for non-DP consumers.
* `current_offpeak_drain_target()` at `energy_battery.py:1726-1747` — REUSE as RULED
  source (inside branch-gated DP path).
* `battery.reserve_soc` — REUSE outer-max safety.
* `set_offpeak_drain(quality, value)` at `energy.py:8645` — REUSE.
* `battery._arbitrage_active`, `battery._attain_state`, `battery._last_inclement_decision`
  — **NOT READ by Rev-15 DP.** (Rev-14 read them; Rev-15 replaces with positive stamp.)
* `_last_reserve_level_desired` — NOT READ.
* `_dp_drain_target_soc(period)` on `EnergyCoordinator` — NEW (~20 LoC).
* `_dp_emitter_in_drain_branch()` on `EnergyCoordinator` — NEW (~7 LoC, positive-stamp
  reader only).
* `BatteryStrategy._offpeak_drain_branch_this_tick: bool` — **NEW instance attr** on
  `BatteryStrategy` (~1 LoC init at `energy_battery.py:~483`; SOLE setter at `:5274`
  inside the drain-fallback branch, ~1 LoC).
* Reset in `_decision_cycle_body` (SOLE resetter) — NEW (~5 LoC with try/except).
* `DP_REASON_EMITTER_NOT_DRAINING` in `energy_drain_precedence.py` — NEW constant.

Knob ladder (per CLAUDE.md): no new operator knobs. The positive stamp is a mechanical
implementation-detail attr, not tunable.

---

## 10. Closed concerns — must stay closed

Rev-14 items unchanged, plus Rev-15 additions/updates:

* **Negative-inference gate ambiguity (Rev-14 C-CRIT-1/1b) CLOSED-BY-CONSTRUCTION** —
  positive stamp is set only by the drain-fallback branch, read via a single defensive
  helper. No enumeration required.
* **Bug Class #53 (computed-but-not-consumed via missed branches) CLOSED-BY-
  CONSTRUCTION** — future strategy branches cannot silently open the DP gate; they
  can only affect DP if they explicitly stamp the marker.
* **"No-change-to-energy_battery.py" constraint RELAXED (Rev-15).** Justified: the
  constraint is what forced the fragile negative inference; ~2 LoC on the battery
  side (init + stamp) buy exhaustiveness by construction. The stamp is placed at the
  same line that already writes the sibling `_arbitrage_active = False` marker
  (`:5274`); reviewer cognitive load minimal.
* **Stranded-carrier release (Rev-14 C-HIGH-2) CLOSED** — INV-DP-DRAIN-1e's
  TRANSITIONED+gate-closed force-revert.
* **Shadow wrong-period false-open (Rev-14 C-HIGH-1) CLOSED** — belt-and-suspenders
  period guard in `_run_dp_shadow_eval` publishes `shadow_reason="wrong_period"`.
* **Sim tautology (Rev-14 C-HIGH-3) CLOSED** — v4 sim's `in_drain_branch` is
  independent fixture field, set by hand per scenario.
* **Raw-string reason code (Rev-14 C-LOW-1) CLOSED** — all callers reference
  `DP_REASON_EMITTER_NOT_DRAINING` constant; grep test T-const-ref anchors.
* All Rev-14 closed items remain closed (mirror-emitter contract inside drain branch;
  safety-branch starvation; EVSE-hold overlay circularity; DP self-fold; sim accuracy
  for accessor; INV-DP-DRAIN-4 live-apply; harness gaps; line-drift on
  `_apply_dp_transition`; two-oracle D4 divergence).

---

## 11. R1 knob live-vs-default note — unchanged from Rev-11.

---

## 12. Cycle-close checklist

* [ ] Two plan reviews (Tier 3): completeness + adversarial build-prediction.
      **Rev-15 re-review REQUIRED** — positive-stamp gate; sim v4 rebuilt with
      independent `in_drain_branch` fixture field; C-CRIT-1/1b/C-HIGH-1/2/3/C-LOW-1
      resolutions verified against source.
* [ ] Build in one branch off `develop`.
* [ ] Suite green + baseline-diff clean (harness updates: two name lists per file +
      marker attr stub on all three fake batteries).
* [ ] Four framing-disjoint reviews A/B/C/D returned; CRITICAL/HIGH fixed.
* [ ] Orchestrator pre-deploy: re-grep every `drain_target_soc =`, every
      `_ev_battery_drain_soc` read, every `_offpeak_drain_branch_this_tick` write
      (must be exactly TWO: init at `energy_battery.py:~483`, stamp at
      `energy_battery.py:5274`) and every reset (must be exactly ONE:
      `energy.py:_decision_cycle_body` immediately after `:5540`). Run source-mutation
      drills C1-C13g + C-reset + C-strand + C-wrong-period + C-stamp-site.
* [ ] Operator checkpoint before deploy.
* [ ] `README_v<version>.md` with prospective Live criteria (sensor attribute; gate-
      closed reason; stranded-carrier release).
* [ ] Deploy via `./scripts/deploy.sh`.
* [ ] Live validation per §3b.
* [ ] README updated with observed `Validated <date>` table.
* [ ] Kanban card `EVSE-DRAIN-PRECEDENCE-KNOB-80-1` → shipped_organic.
* [ ] Post-ship supersession + consumer-gap audit per CLAUDE.md — includes gate-decline
      volume observation (informs whether partial_hold-clamped-DP variant merits un-
      parking) AND R1-live-value (§11) AND card `VERY-POOR-DRAIN-LIVE-UPDATE-1` (§5.6).

---

## 13. Rev-15 fix-up log — Rev-14 findings → resolution

| Finding | Severity | Rev-15 disposition |
|---|---|---|
| **C-CRIT-1 (Rev-14 negative-inference gate opens on non-drain branches — `_arbitrage_active` cleared to False at three sites (:3157 WAIT, :4705 envoy-blind, :5274 drain-fallback); attain-reboot-release + grid-disconnect never touch it either; the negative conjunction cannot distinguish "drain branch ran" from these non-drain branches)** | CRITICAL | **CLOSED-BY-CONSTRUCTION.** Gate replaced with positive stamp set by the drain-fallback branch itself at `energy_battery.py:5274`, reset by the coordinator immediately after `energy.py:5540`. Read via `_dp_emitter_in_drain_branch()` (§3). INV-DP-DRAIN-1d rewritten. Tests T7f (N5 WAIT), T7g (N6 envoy-blind), T7h (N7 attain-reboot-release) + mutations C13e/f/g anchor. Sim v4 fixtures N5-N8 prove: C4 (negative) FAILS N5-N8; C5 (positive) 12/12. |
| **C-CRIT-1b (same defect — restatement)** | CRITICAL | Same resolution as C-CRIT-1. |
| **C-HIGH-1 (shadow eval at `energy.py:4408` runs BEFORE off-peak gate at `:4416` — on peak/mid_peak the shadow gate would consult a stamp that is False for the right reason but publishes the wrong `shadow_reason`)** | HIGH | **FIXED.** Shadow method gets an explicit `if period != "off_peak"` guard at the top of `_run_dp_shadow_eval` (§3); publishes `shadow_reason="wrong_period"` and returns without invoking the gate helper. Belt-and-suspenders — the positive stamp would also correctly close the gate on peak (drain branch cannot fire outside off_peak) but the explicit period guard is clearer and future-proof. Test T-shadow-wrong-period + mutation C-wrong-period anchor. |
| **C-HIGH-2 (gate closes while carrier TRANSITIONED — Rev-14 None-guard leaves `_drain_target` None, so `_soc <= _drain_target` skips; MUST_START_FORCED + paused-idle would not fire; paused EVSE stranded — suppression-needs-a-discharge)** | HIGH | **FIXED.** New INV-DP-DRAIN-1e + new revert-predicate branch: on `TRANSITIONED + not _in_drain_branch`, force `_revert=True` regardless of `_drain_target` (§3). Test T-strand + mutation C-strand anchor. |
| **C-HIGH-3 (sim's `in_drain_branch` derived from the same negative predicates the candidate consumed — tautology; scorecard trivially favored C4)** | HIGH | **FIXED.** Sim v4 makes `in_drain_branch` an INDEPENDENT fixture field set by hand per scenario. Non-drain fixtures N5-N8 (WAIT / envoy-blind / attain-reboot / peak) have `in_drain_branch=False` while the OLD negative predicates all pass. C4 (Rev-14) scores 7/12 or 8/12 (fails N5-N8); C5 (Rev-15 positive) scores 11/12 or 12/12. |
| **C-LOW-1 (raw string literal `"emitter_not_draining"` in Rev-14 emit sites)** | LOW | **FIXED.** New constant `DP_REASON_EMITTER_NOT_DRAINING` in `energy_drain_precedence.py`; all callers reference it. Test T-const-ref anchors with a grep-based assertion. |
| D-CRIT-1 / D-CRIT-2 (Rev-13 findings) | CRITICAL | **PRESERVED-fixed from Rev-14.** Sim v4 retains the accurate `c2_accessor` (no partial_hold clamp); the branch-gate (now positive-stamp) closes D-CRIT-2. |
| A-CRIT-1 / A-CRIT-2 (Rev-12 findings) | CRITICAL | **PRESERVED-fixed from Rev-13/14.** |
| B-HIGH-1 / D-HIGH-1 (safety-branch starvation) | HIGH | **PRESERVED-fixed from Rev-14** (lazy compute + gate consumers with `if _drain_target is not None:`); EXTENDED with INV-DP-DRAIN-1e force-revert. |
| B-HIGH-2 / B-HIGH-3 | HIGH | **DISSOLVED from Rev-13/14. Remain dissolved.** |
| B-MED-1 / A-LOW-1 / D-MED-1 (stale TOU period) | MEDIUM | **FIXED from Rev-13. Preserved.** |
| Shadow-site containment | HIGH | **FIXED (extended at Rev-15).** Wrong-period + gate-closed + None each publishes distinct exact `shadow_reason`; do not raise. |
| D-MED-2 (live acceptance) | MEDIUM | **FIXED from Rev-13.** |
| B-LOW-1 / C-C11 (INV-DP-DRAIN-4) | LOW / GAP | **FIXED from Rev-13.** |
| C-CRITICAL (extract-exec harnesses) | CRITICAL | **FIXED (extended at Rev-15).** Marker attr stub on all three fake batteries; two name lists per file. |
| CRIT-2 revert-guard framing (both None checks) | CRITICAL | **PRESERVED-fixed.** |
| Fixture-contract leak (`reserve == park == 10`) | HIGH | **FIXED + EXTENDED at Rev-15** (per-fixture explicit stamp value + Rev-15 scenarios N5-N8). |
| Sim traceability | INFO | **FIXED at v4** (independent `in_drain_branch`; two-oracle scorecard preserved; C5 added). |
| Line-drift on `_apply_dp_transition` | INFO | **FIXED.** `energy.py:4873` throughout. |
| `period` re-read / shadow at `:4416` | MEDIUM | **FIXED.** |
| `very_poor` validator | HIGH (round-3 card) | **DOCUMENTED + CARDED** (`VERY-POOR-DRAIN-LIVE-UPDATE-1`). |
| **No-change-to-`energy_battery.py` constraint (Rev-13/14 self-imposed)** | POLICY | **EXPLICITLY RELAXED at Rev-15.** ~2 LoC on the battery side (init + stamp), justified in the preamble and §10. The constraint was preventing the correct architectural fix. |

**Parked (would only be un-parked if post-ship data supports it):**
- **Partial_hold-clamped DP variant** — unchanged from Rev-14. Trigger: post-ship
  decision-log shows `emitter_not_draining` firing on partial_hold ticks at a rate
  that materially reduces DP's addressable window.
- **Passing a decision-tick sequence counter through `determine_mode`** — considered
  as an alternative to the reset-then-set boolean but rejected as heavier for no
  gain: the boolean is coherent because the reset and stamp both live on the same
  well-defined tick boundary (`_decision_cycle_body`), and no other DP-adjacent code
  path could set the marker True out-of-band (the stamp site is uniquely inside
  `_get_off_peak_decision`'s drain-fallback branch, verified via grep this session).
  If a future need for finer tick identity emerges (e.g. multiple determine_mode
  calls per cycle), un-park.

**Findings that no longer apply** (Rev-12/Rev-13-specific, dissolved by RULED source
and by positive stamp): unchanged from Rev-14.
