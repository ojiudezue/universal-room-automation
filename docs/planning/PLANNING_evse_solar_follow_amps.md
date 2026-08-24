# PLANNING — EVSE solar-following amp modulation

**Status:** build-ready, awaiting operator go. Tier 3. Self-contained — every deliverable is
specified in this file; there are no references to earlier drafts.

**Companion:** the DP drain-target fix lives in `PLANNING_dp_drain_target_mis_sourcing.md` and
ships FIRST. Solar-follow reads `_paused_by_dp` but has no code dependency on it; shipping DP
first means solar-follow is validated against a corrected drain target rather than one that has
never fired a transition.

---

## 1. Purpose

Excess-solar EV charging is binary today: 48 A, 11.5 kW, on or off, regardless of how much
surplus exists. This modulates the charger's current limit between 6 A and 48 A to track
measured export.

**This REPLACES Emporia's native solar mode**, which was managing `garage_a` (measured: 85
transitions on `number.garage_a_..._current_limit`, including a ~60 s ramp on 08-20 13:26-13:42
of `30, 29, 27, 23, 32, 26, 24, 19, 15, 24, 23` A) and which the operator has since turned off.
URA's version is worse on latency and signal proximity and better on context — it can see
battery intent, tariff, DP and the peer hierarchy. That trade is the justification.

**Deployment precondition:** Emporia native management must be OFF on any EVSE URA modulates.
Two controllers ramping the same limit at 60 s will chase each other.

**Honest regression:** the incumbent was autonomous; this is not. If URA is down or the grid
signal is blind, nothing modulates. Stated in the README.

---

## 2. Measured facts this plan rests on

All measured 2026-08-23/24 against the live recorder. Re-verify before restating.

| Fact | Value | Why it matters |
|---|---|---|
| Emporia mains sign | **negative = export** (-5924 W while exporting) | D1's `S = -grid_W + add_back` |
| Envoy net sign | **negative = export** (-6.177 kW, same moment) | same formula, unit differs |
| Emporia/Envoy skew | 253 W at that sample; median 259 W, scales with slew rate (241 W quiet → 1610 W fast, 6.7×) | why an agreement-gate was rejected; why up-ramp is damped |
| Emporia mains refresh | median 61 s, p90 120 s | D1's 60 s loop is matched to it |
| Envoy net refresh | median 70 s, p90 86 s | fallback is equally usable |
| EVSE power refresh | median 60 s, p90 250 s | `charging` derivation is timely |
| **EVSE `status` refresh** | **median 130 s, p90 1104 s (18 min)** | **tick-counting this signal is unsound; use durations** |
| `current_limit` accepts | ~60 s writes sustained (Emporia's own ramp) | 60 s cadence is proven, not assumed |
| Peak solar AC production | 18.2 kW = 75.8 A | bounds any surplus-derived draw |
| Peak grid import | 27.5 kW; >20 kW in 0.80% of samples; >8 kW in 20.8% | the shipped 8 kW cap default is wrong for this house |
| Service | 400 A / two 200 A panels; **EVSEs on SEPARATE 60 A circuits, different panels** | no shared-branch contention; 48 A IS the circuit bound |
| Single charger peak | 12.24 kW (51 A) | the binary behaviour this cycle replaces |

**`SOLAR_FOLLOW_MAX_AMPS = 48` is DERIVED, not a product spec:** 80% NEC continuous of a
dedicated 60 A branch, one circuit per EVSE. **DO NOT RAISE** because the hardware supports more.

---

## 3. Institutional context verified

* `EVChargerController.determine_excess_solar_actions` — `energy_pool.py:1318-1702`. Owns the
  claim path, peer guards, DP sticky-yield, TOU claim handoff, blind-window deferral, release.
  **Control flow (verified by reading):** peak branch releases all and returns at `:1374`;
  blind-window legs return early at `:1529`/`:1571`; `conditions_met` computed at `:1572-1576`;
  `if conditions_met:` claim leg at `:1581-1684`; `else:` release leg at `:1685-1700`.
* `_stronger_peer_holds` — `energy_pool.py:383-412`. Returns True for six owners via
  `EV_REGISTRY.iter_peer_holds()`: `grid_cap`, `battery_drain`, `arbitrage`, `load_shed`,
  `fill_priority`, `blind_window`. `_paused_by_dp` is deliberately excluded and checked inline
  (two-site convention documented in the docstring). Docstring says "the five"; the loop returns
  six — stale, fix in-cycle.
* **`_get_evse_state(evse_id)` returns a `dict`** — `energy_pool.py:650-707`, keys `is_on`,
  `power`, `status`, `charging`, `power_source`. **SUBSCRIPT IT.** Every existing call site does
  (`:1650`, `:1551`, `:2305`). Attribute access raises.
* `charging = power > EVSE_CHARGING_POWER_THRESHOLD` (100 W) at `:691`; the v4.2.19 fallback at
  `:690-697` sets `charging=True`, `power=EVSE_ESTIMATED_POWER_W` (**7600 W fabricated**),
  `power_source="switch_status"` when the power sensor is unavailable but the switch reads
  charging. **This is why ELIGIBLE gates on `power_source == "sensor"`.**
* **`current_charging_load_w()` (`:2286-2311`) is NOT USED by this cycle.** It is a fleet total
  with no per-EVSE breakdown AND it sums the 7600 W fabrication. D1 reads per-EVSE.
* `DEFAULT_EVSE_ENTITIES` — `energy_pool.py:167-183`, static map, "confirmed via HA", with an
  `evse_config` constructor override (`:193-198`, `evse_config or DEFAULT_EVSE_ENTITIES`).
  **A deployment supplying `evse_config` never sees additions to the DEFAULT map** — see D1.4.
* `mains_export_active()` — `energy.py:4044`. Returns `bool | None`, positive-export contract,
  W/kW normalisation, refuses unknown units (Bug Class #30). **Two live consumers:**
  `energy_pool.py:633` (`_blind_window_envelope_permits_ride`) and `:1422` (blind-window
  continue permission). A shim + source-drift guard exists at
  `quality/tests/test_blind_window_evse_guard.py:1282-1380`. **This cycle does NOT touch it** —
  see D1.2.
* `save_evse_state` — `database.py:4517-4538`, `INSERT OR REPLACE`; table created by
  `CREATE TABLE IF NOT EXISTS evse_state (evse_id, paused_by_energy, excess_solar_active,
  updated_at)` at `:1202-1207`. `IF NOT EXISTS` no-ops on existing installs, so a new column
  needs `ALTER TABLE`. `restore_evse_state` is typed `-> dict[str, dict[str, bool]]` (`:4540`).
  **This cycle adds NO column** — see D1.5.
* `_KNOWN_HOOKS` — `energy.py:1603-1612`, RAISES on an unrecognised hook name.
* `_prune_removed_evses` — `energy_pool.py:213-216`, the sweeper for per-EVSE state.
* Config surface enumerated per the `ura-config-and-flags` skill; see §11.

---

## 4. Falsifiable invariants

**INV-SF-1 (non-perturbation).** When `_excess_solar_active` is empty AND `_original_amps` is
empty, D1 writes nothing and reads no EVSE state beyond the empty-set check. When
`_original_amps` is non-empty the restore pass runs — that is the sole exception, and it only
ever writes a previously captured value back.

**INV-SF-2 (writes only inside sessions).** D1 writes a current limit ONLY to an EVSE in
`_excess_solar_active`, except the restore pass, which writes only to an EVSE that has just
left it.

**INV-SF-3 (restore is load-bearing and restart-safe).** When an EVSE leaves
`_excess_solar_active`, its `current_limit` returns to the saved `_original_amps` within one D1
tick, including across a restart — subject to INV-SF-7.

**INV-SF-4 (draw bounded by measured surplus).**
```
ELIGIBLE = { e ∈ _excess_solar_active :
             NOT _stronger_peer_holds(e)
             AND e ∉ _paused_by_dp
             AND _get_evse_state(e)["power_source"] == "sensor"
             AND _get_evse_state(e)["power"] parsed numerically this tick }
DRAWING  = { e ∈ ELIGIBLE :
             _get_evse_state(e)["charging"] is True
             AND age(power entity last_updated) <= SOLAR_POWER_FRESH_S }
S_eligible = -grid_W + Σ_{e ∈ DRAWING} _get_evse_state(e)["power"]
```
Then, quantified over **ELIGIBLE** (not DRAWING):
```
Σ_{e ∈ ELIGIBLE} A_e · 240 · PHASES  ≤  max(S_eligible, N_eligible · MIN_AMPS · 240)
```
The `max(...)` term is the hardware-floor exception: 6 A is the J1772 pilot minimum and cannot
be undercut, so an eligible-but-not-drawing bay parked at MIN is inside the bound by
construction. Quantifying over DRAWING alone would make the invariant FALSE in a routine
nightly state — two finished bays parked at 6 A each against a negative surplus — and an
invariant that is false in normal operation cannot serve as a falsification target.
**There is no headroom term.**

The `SOLAR_POWER_FRESH_S` gate on DRAWING membership exists because the per-EVSE power sensor
(median 60 s, **p90 250 s**) can lag the mains sensor (median 61 s, p90 120 s). Without it the
add-back describes a draw the grid term has already stopped seeing: a car that stops at 19:41
still reads 11.5 kW at 19:42 while grid reads 0, yielding `S_eligible = 11.5 kW` and 47 A
commanded into zero real surplus. The nameplate sanity check does not catch this — 11.5 kW is an
ordinary surplus for an 18.2 kW array.

**INV-SF-5 (asymmetric reaction to a lagging signal).** Down-steps are immediate and uncapped.
Up-steps require `SOLAR_FOLLOW_UP_MIN_TICKS` consecutive D1 ticks of higher surplus and are
capped at `SOLAR_FOLLOW_UP_STEP_A` per tick. *Measured justification:* the primary is a 60 s
average, and cooking/baking/laundry/dishwashing consume export surplus in multi-kilowatt STEPS,
so a fast-up controller chases each step and immediately reverses.

**INV-SF-6 (fleet allocation).** `N_denom = max(1, N_drawing)`;
`A_per_drawing = clamp(A_total_target // N_denom, MIN_AMPS, MAX_AMPS)`. **The single authority
on the denominator.** A non-drawing bay never dilutes the split.
Degenerate: `N_drawing = 0` → no bay receives an allocation, all ELIGIBLE get MIN.

**INV-SF-7 (stronger-peer subordination — NO EXCEPTIONS).** While `_stronger_peer_holds(e)` OR
`e ∈ _paused_by_dp`, D1 writes nothing to `e` and captures nothing from it, on every reachable
path including the restore pass. `iter_peer_holds()` yields exactly six owners: `grid_cap`,
`battery_drain`, `arbitrage`, `load_shed`, `fill_priority`, `blind_window`.
`_paused_by_us` (TOU) is deliberately NOT a hold — the claim leg establishes TOU as the one set
excess-solar legitimately claims against, so modulating a TOU-paused-but-solar-claimed bay is
designed behaviour, not a leak.

**INV-SF-8 (D1 owns no session state).** D1 never mutates `_excess_solar_active`, never
dispatches a `switch` service call, and never decides a START or a STOP. It computes and writes
current limits, and it may RAISE a stop REQUEST that D2 acts on. Violations are review-blocking.

**INV-STOP-1 (stop requires a reason).** Every removal from `_excess_solar_active` writes a
non-null cessation reason. Five sites exist, enumerated in D2.5 — four are cycle surface, the
fifth (`_prune_removed_evses`) carries a written carve-out.

**INV-STOP-2 (a peer hold is never a stop).** While a stronger peer holds an EVSE, no stop
condition may fire against it and every stop observation stamp for it is CLEARED, so the
duration restarts from zero when the peer releases. A peer hold suspends solar-follow's
authority over that bay; it does not end the session.

---

## 5. D1 — SolarFollowController (amp modulation only)

**Site:** new class in `domain_coordinators/energy_pool.py`, modelled on `PoolOptimizer`
(`:58-160`) as a decision object.

**Construction:** on `EnergyCoordinator` as `self._solar_follow`, **after the entity-config
block that reads grid entities** (`domain_coordinators/energy.py:478-499`) — NOT alongside
`self._ev` at `:293`, where `ec.get(...)` has not yet run and both entity arguments would be
`None`, leaving the feature silently dormant.

```python
class SolarFollowController:
    def __init__(self, hass, ev: EVChargerController,
                 grid_primary_entity: str | None,
                 grid_fallback_entity: str | None) -> None:
        self.hass = hass
        self._ev = ev
        self._grid_primary = grid_primary_entity
        self._grid_fallback = grid_fallback_entity
        self._original_amps: dict[str, float] = {}
        self._up_streak: dict[str, int] = {}
        self._writes: dict[str, list[float]] = {}      # monotonic stamps, rolling 3600 s
        self._last_commanded: dict[str, float] = {}
        self._stop_requests: dict[str, str] = {}       # evse_id -> reason; D2 drains
        self._blind_since: float | None = None         # monotonic
        self._pending_verify: dict[str, Callable[[], None]] = {}   # async_call_later handles
```

**Cross-class convention:** bare `self.` for D1's own attributes; `self._ev.<attr>` with
`# noqa: SLF001` for every READ of pool state (`_excess_solar_active`, `_paused_by_dp`,
`_stronger_peer_holds`, `_get_evse_state`, `_evse`), matching `energy.py:4141`, `:4517`,
`:4929`, `:5031`. **D1 performs no cross-class writes** (INV-SF-8).

**Self-pruning.** `_prune_removed_evses` (`energy_pool.py:773-808`) resolves targets as
`getattr(self, decl.attr)` on the **`EVChargerController`** and runs from its `__init__`,
before `self._solar_follow` exists. It therefore cannot prune D1's dicts, and giving the pool
controller a back-reference to mutate them would be a cross-class write. **D1 prunes its own
dicts at the top of every tick** against `set(self._ev._evse)`.

**Cadence:** its own `async_track_time_interval` at `SOLAR_FOLLOW_TICK_S` (60 s), started in
`async_setup_entry` after the EC is constructed, cancelled in teardown. Always-on with an
empty-set fast path.

### D1.1 — per-tick control law

```python
# 0. SELF-PRUNE, then fast path.
known = set(self._ev._evse)                                   # noqa: SLF001
for d in (self._original_amps, self._up_streak, self._writes,
          self._last_commanded, self._stop_requests, self._pending_verify):
    for gone in [k for k in d if k not in known]:
        d.pop(gone, None)
if not self._ev._excess_solar_active and not self._original_amps:   # noqa: SLF001
    return                                                     # INV-SF-1

# 1. RESTORE PASS — snapshot the keys; the loop mutates the dict.
for evse_id in list(self._original_amps):
    if self._ev._stronger_peer_holds(evse_id) or evse_id in self._ev._paused_by_dp:
        continue                                               # INV-SF-7
    if evse_id in self._ev._excess_solar_active:
        continue
    entity = self._limit_entity(evse_id)                       # D1.4
    if entity is None:
        self._original_amps.pop(evse_id, None)                 # unresolvable: drop, no write
        continue
    await self._write_amps(entity, self._original_amps.pop(evse_id))

# 2. GRID READ (D1.2). On unavailability: handle blind state (D1.3) and return.

# 3. ELIGIBLE and DRAWING per INV-SF-4 — dict SUBSCRIPTING, numeric witness, freshness gate.

# 4. S_eligible = -grid_W + Σ_{DRAWING} power
#    if S_eligible > nameplate_w * 1.15: WARNING; treat as blind (D1.3); return.

# 5. A_total_target = floor(S_eligible / (240 * PHASES))
#    N_denom       = max(1, len(DRAWING))
#    A_per_drawing = clamp(A_total_target // N_denom, MIN_AMPS, MAX_AMPS)   # INV-SF-6

# 6. PER-EVSE WRITE
for evse_id in ELIGIBLE:
    entity = self._limit_entity(evse_id)
    if entity is None:
        continue
    a_current = self._read_amps(entity)          # None if unavailable/non-numeric
    if a_current is None:
        self._up_streak[evse_id] = 0
        continue                                  # cannot compare; do not guess
    if evse_id not in self._original_amps:
        self._original_amps[evse_id] = (
            a_current if a_current >= SOLAR_FOLLOW_CAPTURE_SANITY_A
            else SOLAR_FOLLOW_RESTORE_AMPS       # WARN: do not laminate a throttle
        )
    a_target = A_per_drawing if evse_id in DRAWING else SOLAR_FOLLOW_MIN_AMPS
    if a_target > a_current:                                          # INV-SF-5 up-gate
        self._up_streak[evse_id] = self._up_streak.get(evse_id, 0) + 1
        if self._up_streak[evse_id] < SOLAR_FOLLOW_UP_MIN_TICKS:
            continue
        a_target = min(a_target, a_current + SOLAR_FOLLOW_UP_STEP_A)
    else:
        self._up_streak[evse_id] = 0
    if abs(a_target - a_current) < SOLAR_FOLLOW_DEADBAND_A:
        continue
    if not self._budget_allows(evse_id):          # D1.7
        continue
    await self._write_amps(entity, a_target)
    self._last_commanded[evse_id] = a_target
```

`a_current` is read ONCE per EVSE per tick and reused for the capture decision, the up-gate and
the deadband — two `hass.states.get` calls could straddle a cloud update and disagree.
`self._up_streak.get(evse_id, 0)` is required: a bare `+= 1` raises `KeyError` on the first
up-step of every session.

**First tick of a session:** the bay is in ELIGIBLE with no `_original_amps` entry; step 6
captures before commanding. **First tick after restart:** `_original_amps` is restored from
persistence (D1.5) before the timer's first fire, so step 1 can act on it.

### D1.2 — grid signal

D1 reads its own two entities. It does NOT reuse `CONF_ENERGY_GRID_IMPORT_ENTITY`: that
constant is documented in-repo as "Optional direct grid import/export sensors (Emporia mains)"
(`domain_coordinators/energy.py:483-490`) and is consumed by `CostTracker`, while this
deployment happens to have the Envoy net sensor wired there. Borrowing a field whose documented
meaning and live value disagree is how a sign fork gets shipped.

* **PRIMARY:** `CONF_ENERGY_SOLAR_FOLLOW_GRID_ENTITY` (NEW, rung 2), default
  `sensor.mains_vue_3_power_minute_average`.
* **FALLBACK:** `CONF_ENERGY_SOLAR_FOLLOW_GRID_FALLBACK_ENTITY` (NEW, rung 2), default
  `sensor.envoy_482543015950_current_net_power_consumption`.
* **Contract, enforced at read time on BOTH:** signed net power, **negative = export**
  (measured on both entities 2026-08-24). Read `unit_of_measurement`; `W`/`None`/`""` identity,
  `kW`/`kw` ×1000, **anything else → treat the source as unavailable** (Bug Class #30). A
  non-numeric state is unavailable, not zero.
* Availability: state not in `{unknown, unavailable, None}` and float-parseable.

**D1 does NOT call `mains_export_active()` and does not change it.** It returns `bool | None`,
D1 needs a signed number, and it has two live consumers (`energy_pool.py:633`, `:1422`) plus a
shim-and-drift-guard test. Widening it was considered and rejected: the premise that it has no
live consumers is false, and both consumers gate blind-window ride permission.

**Why Emporia is PRIMARY when EC's global hierarchy prefers Envoy** — operator ruling: the two
answer different questions. EC's is a global source-trust order; solar-follow needs the most
accurate instantaneous grid-boundary reading.

### D1.3 — blind state (grid signal only)

Blind means BOTH primary and fallback are unavailable. It does **not** mean degraded EVSE
signals — status, power and the limit entity are a different integration and typically remain
available, as do battery SOC and the Solcast forecast.

* Under `SOLAR_FOLLOW_STALE_GRACE_S` (300 s) from first unavailability: no writes, no warning.
* At `SOLAR_FOLLOW_STALE_GRACE_S`: WARNING, stamp `_blind_since`, keep the session.
* At `SOLAR_FOLLOW_BLIND_EXIT_S` (900 s): set `_stop_requests[e] = "signal_lost"` for every
  EVSE in the session. D2 drains it (INV-SF-8 — D1 does not stop sessions itself).
* On recovery of either source: clear `_blind_since` **and** discard any `signal_lost` entry
  from `_stop_requests`. A stale request must not stop a recovered session minutes later.

All other stop paths keep working while blind — none of them reads the grid sensor.

### D1.4 — current-limit entities

Add `"current_limit"` to both entries of `DEFAULT_EVSE_ENTITIES`
(`domain_coordinators/energy_pool.py:167-183`). `_limit_entity(evse_id)` resolves
`self._ev._evse.get(evse_id, {}).get("current_limit")` and returns `None` — logging a WARNING
once per EVSE — when absent.

**No `DEFAULT_EVSE_ENTITIES` fallback.** `__init__.py:3183-3187` builds `evse_config` on every
boot by copying `DEFAULT_EVSE_ENTITIES` per bay and overriding individual keys, so additions to
the DEFAULT map propagate and `evse_config` is never `None` in production. A second lookup keyed
by `evse_id` would add no coverage and could resolve a *different physical charger's* limit
entity on a deployment with renamed bays.

### D1.5 — persistence of `_original_amps`

**Decision: the generic energy-state KV, used directly. No schema change, no hook registration.**

Write with `db.save_energy_state("solar_follow_original_amps_v1", json.dumps(self._original_amps))`
and restore with
`db.restore_energy_state_with_age("solar_follow_original_amps_v1", max_age_hours=10)`, following
`_restore_wv_state` (`domain_coordinators/energy.py:1673-1684`), which uses this pair hook-free.

**Not `_KNOWN_HOOKS`.** That is a local allowlist inside `_restore_registry_owner_lists`
(`energy.py:1602-1612`) validating the `restore_hook` field of declarations from
`EV_REGISTRY.iter_persisted_lists()`. That loop requires `persistence_kind == "list"`, rejects a
non-list payload outright, and rehydrates via `getattr(self._ev, decl.attr).add(eid)` — it can
only fill a **set on `EVChargerController`**, never a `dict[str, float]` on a different object.
Registering a key there would be a silent no-op and `_original_amps` would restore empty.

**Not a new column.** `save_evse_state` (`database.py:4517`) writes a table created with
`IF NOT EXISTS` (`:1202-1207`), so a new column needs `ALTER TABLE` on existing installs and
would break `restore_evse_state`'s `dict[str, dict[str, bool]]` annotation.

If the blob is older than 10 h, DISCARD it and do NOT capture the current value as
`_original_amps` — capture happens fresh in step 6 with the sanity floor.

### D1.6 — bounded write verification

**Mechanism: `async_call_later`, following `energy_write_verify.py`** — the mature precedent in
this codebase (`domain_coordinators/energy_write_verify.py:572`), which already solves the three
things a naive implementation gets wrong. Do NOT `await asyncio.sleep()` inside the tick: with
two bays that would block the 60 s loop for `2 × SOLAR_FOLLOW_VERIFY_S`.

After each write to `evse_id`:

```python
async def _delayed(_now):
    self._pending_verify.pop(evse_id, None)      # clear own handle first
    try:
        observed = self._read_amps(entity)
        if observed is not None and abs(observed - commanded) >= 1:
            _LOGGER.warning(...)                  # counter++, no stop, no retry
    except Exception:                             # noqa: BLE001
        _LOGGER.debug("solar-follow verify raised (swallowed)", exc_info=True)

prev = self._pending_verify.pop(evse_id, None)
if prev is not None:
    prev()                                        # SUPERSEDE: a newer write invalidates the old check
self._pending_verify[evse_id] = async_call_later(
    self.hass, SOLAR_FOLLOW_VERIFY_S, _delayed)
```

Three requirements, each mirroring the precedent:
* **Supersession** — a second write to the same bay inside the verify window cancels the first
  pending check. Without it the earlier callback compares a stale `commanded` and fires a
  spurious warning on every ramp.
* **Teardown cancellation** — `cancel_all()` on the controller, invoked from the EC teardown
  path, calls every outstanding handle. Untracked `async_call_later` handles outliving the
  coordinator is a known bug class in this repo (`energy_write_verify.py:1301-1303` exists
  solely to close it).
* **Swallow in the callback** — a raising verify must not surface as an unhandled task exception.

`_pending_verify: dict[str, Callable[[], None]]` is declared in `__init__` and pruned with the
other per-EVSE dicts.

**No stop, no retry.** A foreign-writer detector that STOPS the session when the entity changes
on a no-write tick was considered and rejected: the Emporia cloud echoes writes with delay, so a
delayed echo landing on a deadband-suppressed tick would trip it and kill the session with a
misattributed cause. The precondition (Emporia native mode off) plus a warning counter is the
proportionate control.

### D1.7 — write budget

`_writes[evse_id]` holds monotonic stamps. `_budget_allows` prunes stamps older than 3600 s and
returns `len(stamps) < SOLAR_FOLLOW_MAX_WRITES_PER_HOUR`. **Rolling window, not a clock-hour
bucket**, and RAM-only — after a restart the budget starts empty, which errs toward allowing
writes and cannot strand a bay at a stale limit.

---

## 6. D2 — session start and stop

**Site:** `EVChargerController.determine_excess_solar_actions`
(`domain_coordinators/energy_pool.py:1318-1702`).

### D2.1 — the per-EVSE stop sweep

**Placement: immediately after the peak branch's `return actions` and BEFORE the blind-window
guard block** — i.e. between the statement `return actions` that closes the
`if tou_period == "peak":` block and the comment `# Blind-window guard for the excess-solar
path`. Anchor by code, not line number: the surrounding line numbers shift.

Two reasons this placement and no other:
1. **The release leg is unreachable for these conditions.** It sits inside `else:` and runs only
   when `conditions_met` is False, but an idle or disconnected bay must be stopped while
   `conditions_met` is TRUE — a bay can sit finished for an hour on a perfect solar day.
2. **The blind-window legs return early.** Both the CONTINUE and DROP legs `return actions`
   before `conditions_met` is computed. A sweep placed after them would be unreachable during a
   blind window — which is exactly when D1 raises `signal_lost`, and the two blindnesses share a
   cause (D1's fallback is the Envoy; the blind-window guard engages when the Envoy is blind).
   A sweep sited after the blind-window block would strand a `signal_lost` request for the
   entire outage, holding the charger at up to 48 A with no surplus reading — verbatim the state
   the mechanism exists to prevent.

The sweep handles **per-EVSE conditions only**: `signal_lost`, `car_disconnected`, `car_idle`.
Fleet-level conditions (`surplus_gone`, `forecast_poor`) belong to the `continue_ok` predicate in
D2.4 and are handled in the release leg, so the sweep needs no SOC value and can sit above the
predicate block.

```python
# Locals in scope here are ONLY the parameters (soc, remaining_forecast_kwh, tou_period,
# soc_threshold, kwh_threshold, dp_carrier_state, coord) and `actions`. `switch_entity` is
# bound inside the peak, DROP and claim loops and is NOT in scope — resolve it per-EVSE.
# `now` must be WALL CLOCK, matching the stamps in D2.3.
from homeassistant.util import dt as dt_util          # noqa: PLC0415
now = dt_util.utcnow()

for evse_id in list(self._excess_solar_active):        # snapshot — the loop discards
    config = self._evse.get(evse_id, {})
    switch_entity = config.get("switch", "")
    if not switch_entity:
        continue
    if self._stronger_peer_holds(evse_id) or evse_id in self._paused_by_dp:
        self._clear_solar_stop_stamps(evse_id)         # INV-STOP-2
        continue
    reason = self._solar_stop_reason(evse_id, now)
    if not reason:
        continue
    st = self._get_evse_state(evse_id)
    if st["is_on"]:                                    # sibling legs all guard on this
        actions.append({"service": "switch.turn_off", "target": switch_entity, "data": {}})
    self._excess_solar_active.discard(evse_id)
    self._proactive_offpeak_holds.discard(evse_id)     # mirrors the peak leg
    self._excess_solar_started_at.pop(evse_id, None)
    self._clear_solar_stop_stamps(evse_id)
    self._record_cessation(evse_id, reason, now)
```

**The claim leg and the release-leg BODY are byte-identical.** The sweep is additive. The
release leg's GUARD changes (D2.4) — see §8 non-goal 4, which states that boundary precisely.

**`_paused_by_dp` treatment.** The sweep treats any `_paused_by_dp` membership as a hold, while
the claim leg treats `HOLD_ONLY` as yieldable. That asymmetry is deliberate: a HOLD_ONLY-orphaned
bay is claimable but not stoppable-by-us, because the DP carrier may re-assert at any tick and a
stop would race it. `dp_carrier_state` is in scope if a future cycle wants to narrow this.

### D2.2 — per-EVSE state on `EVChargerController`

All owned by the pool controller, because every write point already lives there. All RAM-only.

| Field | Purpose |
|---|---|
| `_excess_solar_started_at: dict[str, datetime]` | session age for `SOLAR_MIN_ON_S` |
| `_solar_disconnected_since: dict[str, datetime]` | first observation of `status` disconnected |
| `_solar_idle_since: dict[str, datetime]` | first observation of not-drawing |
| `_solar_conditions_false_since: dict[str, datetime]` | first tick `continue_ok` read False |
| `_last_start_reason`, `_last_stop_reason`, `_last_stop_at` | the ledger (D2.5) |

**Stamped** at the three claim sites (`energy_pool.py:1656`, `:1671`, `:1679`) for
`_excess_solar_started_at`. **Cleared** at every removal site. **Pruned** by
`_prune_removed_evses` — these live on `EVChargerController`, so unlike D1's dicts they are
reachable by it.

A missing `_excess_solar_started_at` reads as age 0 — immune until 300 s elapse — never as
infinitely old. After a restart the floor re-arms, delaying stops by up to 5 minutes, which errs
toward not stopping.

### D2.3 — stop conditions, measured from stamped observations

**Not from `last_changed`.** `status` is an ATTRIBUTE of the switch entity
(`energy_pool.py:685-688`, `switch_state.attributes.get("status")`), and HA bumps `last_changed`
only on STATE change. `switch.garage_a.last_changed` measures how long the switch has been on —
it carries no information about `status` at all. Binding the debounce to it fails both ways: a
switch that has been on for 6 h satisfies a 300 s threshold on the FIRST disconnected sample
(no debounce at all), and any unrelated switch toggle grants a genuinely unplugged car a fresh
300 s. Stamped first-observation dicts are the only correct implementation.

`_solar_stop_reason(evse_id, now)` returns the first match, or None. All are additionally gated
on `now - _excess_solar_started_at[evse_id] >= SOLAR_MIN_ON_S`.

| Reason | Observation | Threshold |
|---|---|---|
| `signal_lost` | `evse_id in _solar_follow._stop_requests` | raised by D1.3 |
| `car_disconnected` | `_get_evse_state(e)["status"]` reads a disconnected value continuously since `_solar_disconnected_since[e]` | `SOLAR_STOP_DISCONNECTED_S` = 300 |
| `car_idle` | `_get_evse_state(e)["charging"]` False continuously since `_solar_idle_since[e]`, and not disconnected | `SOLAR_STOP_IDLE_S` = 1200 |

Each tick: if the condition holds and no stamp exists, stamp `now`; if it does not hold, clear
the stamp. `status == "unknown"` — the sentinel `_get_evse_state` actually returns when the
switch state or attributes are missing (`:685-686`) — clears both stamps and advances nothing.
It is a statement about the EVSE, not the car.

**Why disconnected is short and idle is long.** Disconnected is unambiguous — no car — so acting
fast costs nothing and acting slow holds a claim pointlessly. Idle is ambiguous: a mid-charge
pause for thermal throttling or cell balancing runs 5-15 minutes.

**Builder note on the vocabulary.** `_get_evse_state`'s `status` comes from the switch attribute,
whose observed values are `Standby`, `Charging`, `DeviceNotConnected`. A separate entity
`sensor.garage_*_evse_emporia_wifi_garage*_status` exists with values `Connected`,
`Disconnected`, `Charging`. **Establish which vocabulary the attribute actually carries before
implementing**, and put the disconnected-value set in one named constant rather than inline
string literals.

### D2.4 — the SOC band

`conditions_met` is ONE boolean serving both legs. Editing it in place would move the START gate.
Add a sibling:

```python
conditions_met = (soc is not None and soc >= soc_threshold           # UNCHANGED
                  and remaining_forecast_kwh is not None
                  and remaining_forecast_kwh >= kwh_threshold)
stop_soc = min(fill_priority_soc, soc_threshold) if fill_priority_soc is not None else soc_threshold
continue_ok = (soc is not None and soc >= stop_soc
               and remaining_forecast_kwh is not None
               and remaining_forecast_kwh >= kwh_threshold)
```

The resulting control structure is **exactly**:

```python
if conditions_met:
    ...claim leg, byte-identical...
elif not continue_ok:
    ...release leg body, byte-identical...
# else: 80-95 dead band — a running session HOLDS; an unclaimed bay is ignored.
```

`elif`, not a nested `if` inside `else:` — the two are behaviourally identical only while
`conditions_met ⇒ continue_ok`, which holds today because `stop_soc <= soc_threshold` and the
kWh term is shared. That implication is an unstated coupling; `elif` makes the structure
independent of it.

`fill_priority_soc: int | None = None` is a NEW parameter, passed from the caller's tick
snapshot `fill_priority_soc_tick` (`domain_coordinators/energy.py:5704`) at the call site
(`:5757-5762`) — NOT read live off the coordinator, per the race the comment at `:5700-5703`
documents. When None, `stop_soc = soc_threshold` (today's behaviour).

`number.py:1670-1675` states the ordering invariant `fill_priority_soc < excess_solar_soc` is
"NOT enforced today". Hence the `min()`: an inverted config would otherwise put the stop
threshold above the start threshold and kill every session on its first tick. WARN once.

**Release requires sustained failure, not one tick.** `continue_ok` going False must persist
for `SOLAR_STOP_MIN_S` (600 s) before the release leg acts, tracked by
`_solar_conditions_false_since: dict[str, datetime]` — stamped when `continue_ok` first reads
False, cleared whenever it reads True, cleared on removal, pruned with its siblings. Without it
a single dip below the band releases the fleet. Value hysteresis (the 80-95 band) and time
hysteresis are complementary: the band prevents boundary churn, the streak absorbs transients
inside the band.

The release-leg log line at `:1695` says "conditions no longer met", which is now imprecise in
the dead band. Updating a log string is a comment-class edit and does not breach non-goal 4.

### D2.5 — cessation ledger

Closed vocabulary. **Start:** `solar_surplus`, `dp_yield`, `tou_claim`.
**Stop:** `surplus_gone`, `forecast_poor`, `car_disconnected`, `car_idle`, `signal_lost`,
`peak_clear`, `blind_window_drop`.

**Every removal site writes one** (INV-STOP-1). Independently enumerated:

| Site | File:line | Reason |
|---|---|---|
| the sweep | new | per D2.3 |
| release leg | `energy_pool.py:1699` | `surplus_gone` or `forecast_poor` |
| peak clear | `energy_pool.py:1369` | `peak_clear` |
| blind-window DROP | `energy_pool.py:1564` | `blind_window_drop` |
| `_prune_removed_evses` set-pass | `energy_pool.py:787-791` | **carve-out, see below** |

`excess_solar` is declared with `prune_participant` defaulting True
(`energy_pool_owners.py:245-252`, `:139`), so prune does discard from the set. It runs only from
`EVChargerController.__init__`, before `energy.py:1366` restores membership, so the set is
empty in practice. **The carve-out is written down rather than left implicit**, because
INV-STOP-1 says "every removal" and a future cycle that calls prune at runtime would create a
silent null reason.

**`peer_hold` is NOT a stop reason** — a peer hold never ends a session (INV-STOP-2). Which owner
holds a bay is already published by `pause_reason_human`.

**URA cannot read car SoC** — the Emporia is a relay plus a power meter with no J1772 SoC leg.
`car_idle` therefore conflates "finished", "hit an app-set limit" and "refused the handshake".

---

## 7. Observability and control

**No new entity.** `sensor.ura_energy_coordinator_ev_charging_status` already publishes 23
attributes including `excess_solar_active`, `excess_solar_evses`, per-EVSE dicts (`is_on`,
`power`, `status`, `charging`, `power_source`), every pause set, `pause_dispatch_state`,
`pause_reason_human`, `fill_priority_target_soc` and `reasons_last_changed_at`. Solar-follow
adds to it. A second EVSE sensor would fragment state across two entities.

**Do not add — already derivable:** eligible set (membership minus published pause sets),
drawing set (per-EVSE `charging`), which peer holds a bay (`pause_reason_human`), drain trips
(`paused_by_battery_drain` + `reasons_last_changed_at`).

**Add exactly these five:**

| Attribute | Why it is not derivable |
|---|---|
| `solar_follow_surplus_kw` | the computed `S_eligible` — THE decision input; without it a sizing bug and a sensor bug look identical |
| `solar_follow_original_amps` | per-EVSE saved restore value; invisible otherwise, and what a stuck-throttle incident needs |
| `solar_follow_state` | per-EVSE `writing` / `yielded` / `blind` — names the state machine in one field |
| `solar_follow_last_start_reason` / `solar_follow_last_stop_reason` (+ `_at`) | the ledger; the "why did it do that" artifact |
| `solar_follow_blind_since` | makes the 900 s exit observable before it fires |

**Control surface: ONE new Number.** `number.ura_energy_coordinator_excess_solar_confirm` —
"Excess Solar Confirm", minutes, rung 3, default 3, range 1-10. It is the surface for
`SOLAR_FOLLOW_UP_MIN_TICKS`; the mapping is 1:1 because the D1 tick is 60 s, and the help text
must say "consecutive minutes of higher surplus before **increasing** the car's amps" — the name
alone could be read as the start gate, which is a different thing.

**No new switch:** `switch.ura_energy_coordinator_evse_solar_aware_charging` already exists and
is the master enable. **No new SOC knobs:** `resume_ev_at_battery_soc` (95) and
`fill_priority_soc` (80) are already Numbers.

---

## 8. Non-goals

1. NOT reading car SoC. No J1772 decoding.
2. NOT modifying `determine_battery_drain_actions` (`:1776-1959`) — byte-identical post-cycle.
   Solar-follow YIELDS to drain protection (INV-SF-7); it never suppresses it.
3. NOT modifying `mains_export_active()` or `solar_replenishing`.
4. NOT modifying the excess-solar CLAIM leg, and NOT modifying the release-leg BODY. The
   release-leg GUARD does change — `else:` becomes `elif not continue_ok:` (D2.4). The
   cycle-close grep must therefore be scoped to the leg BODY, not to the leg, or it will
   either fail spuriously or pass vacuously.
5. NOT adding a database column or migration.
6. NOT a foreign-writer STOP (see D1.6).
7. NOT a fleet circuit-capacity model — the EVSEs are on separate 60 A circuits and the per-EVSE
   48 A clamp already IS the circuit bound.
8. NOT changing EC's global source hierarchy.
9. NOT re-solving compound-load protection; `grid_cap` and the v4.5.0 D4 mutex own it.
10. NOT using `current_charging_load_w()`.
11. NOT a `self_modulates` behaviour change.
12. NOT shortening the D1 tick or subscribing to owner-set mutations.

---

## 9. Knobs

**Home:** every `SOLAR_*` constant is declared in
`domain_coordinators/energy_const.py` alongside the other EVSE constants; both `CONF_*`
fields are declared there too and parsed in the coordinator-manager options step of
`config_flow.py`, then threaded through `entity_config` in `__init__.py` the same way
`CONF_ENERGY_GRID_IMPORT_ENTITY` is (`domain_coordinators/energy.py:490`).

**The Number reaches D1 by push:** the `excess_solar_confirm` entity's setter calls an
`EnergyCoordinator` setter that assigns `self._solar_follow._up_min_ticks`, mirroring
`set_offpeak_drain` (`domain_coordinators/energy.py:8645`). D1 does NOT read the entity
state each tick; the module constant is the default the Number overrides.

| Constant | Rung | Value | Note |
|---|---|---|---|
| `SOLAR_FOLLOW_MIN_AMPS` | 1 | 6 | J1772 pilot floor |
| `SOLAR_FOLLOW_MAX_AMPS` | 1 | 48 | **DERIVED**: 80% of a 60 A branch. DO NOT RAISE |
| `SOLAR_FOLLOW_RESTORE_AMPS` | 1 | 48 | same derivation; used when capture was rejected |
| `SOLAR_FOLLOW_CAPTURE_SANITY_A` | 1 | 20 | below this, capture MAX not the observed value |
| `SOLAR_FOLLOW_DEADBAND_A` | 1 | 1 | write suppression |
| `SOLAR_FOLLOW_UP_STEP_A` | 1 | 4 | per-tick up cap |
| `SOLAR_FOLLOW_UP_MIN_TICKS` | 3 | 3 | **the only tick-counting knob**; D1 60 s clock; surfaced as "Excess Solar Confirm" |
| `SOLAR_FOLLOW_TICK_S` | 1 | 60 | D1 cadence |
| `SOLAR_FOLLOW_VERIFY_S` | 1 | 8 | readback delay, via `async_call_later` |
| `SOLAR_FOLLOW_MAX_WRITES_PER_HOUR` | 1 | 60 | matches the tick; the deadband does suppression |
| `SOLAR_FOLLOW_STALE_GRACE_S` | 1 | 300 | blind declared |
| `SOLAR_FOLLOW_BLIND_EXIT_S` | 1 | 900 | stop request raised |
| `SOLAR_FOLLOW_NEXTHOUR_FLOOR_W` | 1 | 500 | forecast stop |
| `SOLAR_POWER_FRESH_S` | 1 | 180 | max age of a per-EVSE power reading for DRAWING membership; p90 of that sensor is 250 s |
| `SOLAR_STOP_DISCONNECTED_S` | 1 | 300 | duration on status `last_changed` |
| `SOLAR_STOP_IDLE_S` | 1 | 1200 | duration, power-derived |
| `SOLAR_STOP_MIN_S` | 1 | 600 | `continue_ok`-False streak before the release leg acts |
| `SOLAR_MIN_ON_S` | 1 | 300 | minimum session age before any stop |
| `CONF_ENERGY_SOLAR_FOLLOW_GRID_ENTITY` | 2 | — | NEW; primary grid entity (Emporia mains, signed, negative=export) |
| `CONF_ENERGY_SOLAR_FOLLOW_GRID_FALLBACK_ENTITY` | 2 | — | NEW; fallback (Envoy net, signed, negative=export) |
| `CONF_SOLCAST_NEXT_HOUR_ENTITY` | 2 | — | NEW; forecast stop input |

---

## 10. Tests

Behavioural, mutation-anchored. `PYTHONDONTWRITEBYTECODE=1`, cleared `__pycache__`.
**No test contains its own mutation** — mutations live in §12.

**Fixture contract.** `_get_evse_state` returns a dict; fixtures return dicts. Every fixture
pins `power_source` explicitly. Fleet fixtures pin `charging` for both bays **and** the age of
each power reading. **Fixtures MUST be able to express a grid reading and a per-EVSE power
reading that DISAGREE** — an earlier contract required them to be consistent, which made the
add-back staleness failure untestable by construction.

**Allocation and eligibility**
* **T-DICT-1** every D1 read of `_get_evse_state` subscripts. The fixture returns a plain dict
  with no attribute support, so attribute access raises.
* **T-ELIG-1** a bay with `power_source="switch_status"` (7600 W fabricated) is excluded from
  ELIGIBLE and contributes 0 to the add-back. Under the bug: `S` inflated 7.6 kW.
* **T-ELIG-2** a bay whose power sensor is responsive but publishes a non-numeric state has
  `power_source == "sensor"` and `power == 0.0` (`energy_pool.py:668-681` assigns the source
  before the parse and swallows the exception). Assert it is EXCLUDED from ELIGIBLE by the
  numeric-witness clause. Under the bug it is admitted, reads as 0 W, and drags every other
  bay to MIN while `solar_follow_surplus_kw` shows a plausible small number.
* **T-STALE-POWER-1** grid reads 0 W; `garage_a` reports `charging=True, power=11500` with a
  power reading 200 s old (`SOLAR_POWER_FRESH_S = 180`). Assert `garage_a ∉ DRAWING`,
  `S_eligible == 0`, and the commanded value is MIN — not 47 A. **This is the founding test for
  the freshness gate**; without it the add-back is an unbounded headroom term.
* **T-ALLOC-1** one drawing bay, one idle bay, 7 kW surplus → drawing 29 A, idle 6 A.
  Under `len(ELIGIBLE)` as denominator: 14 A. Discriminating.
* **T-ALLOC-2** both drawing, 7 kW → 14 A each.
* **T-ALLOC-3** `N_drawing = 0` → no divide-by-zero; all ELIGIBLE get 6 A.
* **T-UPSTREAK-1** first up-step of a fresh session does not raise. Under a bare
  `self._up_streak[evse_id] += 1`: `KeyError`.
* **T-AMPS-NONE-1** the limit entity is `unavailable`: the bay is skipped, no write, no capture,
  streak reset. Under the bug: `TypeError` comparing `a_target > None`.

**Peer subordination**
* **T-PEER-1** peer-held bay receives no write and no capture across 5 ticks, including the
  restore pass.
* **T-PEER-2** mid-session peer add: `_original_amps` retained AND zero writes on tick 2, with
  the surplus moved DOWN 14 A between ticks so the deadband cannot mask the result.
* **T-PEERSTOP-1** a peer holds a bay whose status reads disconnected for 400 s → **no stop**,
  and both stop stamps are cleared. On peer release the duration restarts from zero, so no stop
  fires for a further `SOLAR_STOP_DISCONNECTED_S`. Under the bug: an immediate false
  `car_disconnected` the moment the peer releases. (INV-STOP-2)

**Stop conditions**
* **T-STOPSWEEP-1** an idle bay stops while `conditions_met` is TRUE. Under a sweep sited in the
  release leg: never stops. **Founding test for D2.1's placement.**
* **T-DISC-1** the switch has been `on` for 6 h; `status` reads disconnected for the FIRST time
  this tick. Assert **no stop** — the stamp was just created. Assert a stop only after
  `SOLAR_STOP_DISCONNECTED_S` of continuous disconnected observations. **Under a `last_changed`
  implementation this test fails at the first assertion**, because the switch's `last_changed`
  is 6 h old and the threshold is instantly satisfied.
* **T-DISC-2** a single disconnected sample followed by a reconnected sample clears the stamp;
  no stop.
* **T-IDLE-1** not charging for 1200 s → stop `car_idle`; a 10-minute mid-charge pause that
  resumes → NO stop.
* **T-STATUS-UNKNOWN-1** `status == "unknown"` (the sentinel `_get_evse_state` actually returns
  when the switch state or attributes are missing) clears both stamps and advances nothing.
* **T-STREAK-1** `continue_ok` False for 300 s → no release; for 600 s → release with
  `surplus_gone`. Under a missing streak: releases on the first tick below the band.
* **T-BAND-1** a session started at SOC 96 survives a dip to 85 for 6 ticks.
* **T-BAND-2** SOC 79 sustained past the streak → stop `surplus_gone`.
* **T-BAND-3** inverted config (`fill_priority_soc=95`, `soc_threshold=90`) → `stop_soc` clamps
  to 90, one WARNING, a session started at 91 does not immediately stop.
* **T-BAND-4** dead band, no session: SOC 85 with `conditions_met` False and `continue_ok` True
  → the claim leg does not run and the release leg does not run; an unclaimed bay is untouched.

**Blind state**
* **T-BLIND-1** both grid sources unavailable: no writes at 300 s, `_stop_requests` populated at
  900 s, D2 stops on its next sweep with `signal_lost`. Session survives 299 s.
* **T-BLIND-2** while blind, the disconnected and idle stops still function.
* **T-BLIND-SWEEP-1** the EC blind-window guard is ENGAGED and the CONTINUE leg returns early;
  a `signal_lost` request is outstanding. Assert the sweep still runs and the stop fires.
  **Under a sweep sited after the blind-window block this never fires** and the bay holds up to
  48 A for the whole outage. Founding test for the placement's second reason.
* **T-BLIND-RECOVER-1** a `signal_lost` request is raised, then the primary recovers before D2's
  next tick. Assert the request is discarded and NO stop occurs. Under a non-clearing
  implementation: a healthy session is stopped minutes later with a misattributed cause.

**Persistence and lifecycle**
* **T-RESTORE-1** restart mid-session: `_original_amps` restored via
  `db.restore_energy_state_with_age("solar_follow_original_amps_v1", max_age_hours=10)` and the
  first tick restores the limit.
* **T-RESTORE-2** a blob older than 10 h is DISCARDED; `_original_amps` is re-captured fresh with
  the sanity floor, not laminated from the current throttled value.
* **T-PRUNE-1** an EVSE removed from `self._ev._evse` has every D1 dict entry dropped on the next
  tick. Under reliance on `_prune_removed_evses`: entries persist, because that method resolves
  attributes on `EVChargerController` and runs from its `__init__` before D1 exists.
* **T-LEDGER-1** every removal path writes a reason: sweep, release leg, peak-clear (`:1369`),
  blind-window drop (`:1564`). Assert non-null for all four.
* **T-ENTITY-1** an EVSE with no `current_limit` key logs a WARNING once and is skipped — no
  write, no capture, no exception.
* **T-VERIFY-1** two writes to the same bay inside `SOLAR_FOLLOW_VERIFY_S`: the first pending
  check is cancelled and only one warning-eligible comparison runs, against the LATER commanded
  value. Under a non-superseding implementation: a spurious warning on every ramp step.
* **T-VERIFY-2** teardown with a verify outstanding cancels the handle; no callback fires after
  shutdown. Under the bug: an `async_call_later` handle outlives the coordinator.
* **T-UNIT-1** a fallback reading in kW is ×1000; an entity with an unexpected unit is treated as
  unavailable, not admitted.

---

## 11. REUSE vs NEW

| Item | Verdict | Evidence |
|---|---|---|
| `_stronger_peer_holds` + inline `_paused_by_dp` | REUSE | `energy_pool.py:383-412` |
| `_get_evse_state` (subscripted) | REUSE | `:650-707` |
| `DEFAULT_EVSE_ENTITIES` (+ `current_limit` key) | REUSE | `:167-183` |
| claim leg / release-leg body | REUSE UNCHANGED | `:1581-1700` |
| `db.save_energy_state` / `restore_energy_state_with_age` | REUSE | `database.py:4868`, `:4898`; precedent `energy.py:1673-1684` |
| `sensor...ev_charging_status` | REUSE (extend) | 23 existing attributes |
| `switch...evse_solar_aware_charging` | REUSE | existing master enable |
| `resume_ev_at_battery_soc`, `fill_priority_soc` | REUSE | existing Numbers |
| `mains_export_active` | REUSE UNCHANGED (not called) | two live consumers |
| Number-setter push pattern | REUSE | `energy.py:8645` `set_offpeak_drain` |
| `async_call_later` verify pattern + supersession + `cancel_all` | REUSE | `energy_write_verify.py:572`, `:1301-1303` |
| `SolarFollowController` | NEW | no 60 s modulation loop exists |
| `CONF_ENERGY_SOLAR_FOLLOW_GRID_ENTITY` / `_FALLBACK_ENTITY` | NEW | existing grid fields carry other contracts |
| `CONF_SOLCAST_NEXT_HOUR_ENTITY` | NEW | existing Solcast fields are today/tomorrow/remaining/day3 |
| `number...excess_solar_confirm` | NEW | one control |

---

## 12. Mutation drills

Real per-site source mutation, ONE at a time, restore after each.

* **C1** attribute access instead of subscripting in ELIGIBLE → **T-DICT-1** fails.
* **C2** drop the `power_source == "sensor"` gate → **T-ELIG-1** fails.
* **C3** drop the numeric-witness clause → **T-ELIG-2** fails.
* **C4** drop the `SOLAR_POWER_FRESH_S` gate on DRAWING → **T-STALE-POWER-1** fails.
* **C5** `N_denom = len(ELIGIBLE)` → **T-ALLOC-1** fails.
* **C6** remove `max(1, ...)` → **T-ALLOC-3** fails (crash).
* **C7** bare `self._up_streak[evse_id] += 1` → **T-UPSTREAK-1** fails.
* **C8** remove the peer guard from the D1 write path → **T-PEER-1** fails.
* **C9** remove the stamp-clearing from the sweep's peer branch → **T-PEERSTOP-1** fails.
* **C10** move the sweep into the `elif` release leg → **T-STOPSWEEP-1** fails.
* **C11** move the sweep BELOW the blind-window block → **T-BLIND-SWEEP-1** fails.
* **C12** bind `car_disconnected` to `switch.last_changed` instead of the stamp →
  **T-DISC-1** fails.
* **C13** never clear `_stop_requests` on grid recovery → **T-BLIND-RECOVER-1** fails.
* **C14** remove the `SOLAR_STOP_MIN_S` streak from the release leg → **T-STREAK-1** fails.
* **C15** drop the `min()` in `stop_soc` → **T-BAND-3** fails.
* **C16** restore the KV blob without the 10 h age gate → **T-RESTORE-2** fails.
* **C17** delegate D1 dict pruning to `_prune_removed_evses` → **T-PRUNE-1** fails.
* **C18** skip the ledger write on the peak-clear path → **T-LEDGER-1** fails.
* **C19** remove the supersession cancel before scheduling a verify → **T-VERIFY-1** fails.
* **C20** remove `cancel_all()` from teardown → **T-VERIFY-2** fails.

Every drill must bite. A site whose bypass leaves the suite green is untested.

---

## 13. Acceptance criteria

**D1**
* **Verify:** with 7 kW surplus, one drawing bay and one idle bay, the drawing bay is commanded
  29 A and the idle bay 6 A.
* **Verify:** a peer-held bay receives no write and no capture.
* **Verify:** a `switch_status` bay is excluded from ELIGIBLE and from the add-back.
* **Test:** T-DICT-1, T-ELIG-1, T-ALLOC-1/2/3, T-PEER-1/2, T-UNIT-1, T-ENTITY-1.
* **Live:** `solar_follow_surplus_kw` tracks measured export within the skew band; per-EVSE
  commanded amps move with it; `solar_follow_original_amps` is populated for every active bay.

**D2**
* **Verify:** an idle bay stops while `conditions_met` is TRUE.
* **Verify:** a peer-held bay accrues no stop timers.
* **Verify:** every removal path writes a cessation reason.
* **Test:** T-STOPSWEEP-1, T-DISC-1, T-IDLE-1, T-PEERSTOP-1, T-LEDGER-1, T-BLIND-1/2.
* **Live:** `solar_follow_last_stop_reason` is non-null for every session end observed, and the
  distribution across reasons is inspectable without reading logs.

**D2.4 (band)**
* **Verify:** a session started at 96 survives a dip to 85; a dip to 79 stops it.
* **Test:** T-BAND-1/2/3.
* **Live:** on a day with a mid-afternoon cloud, the session does NOT stop and the amp trace
  shows a throttle-down-and-recover rather than a stop-and-restart.

**Discriminating note:** repeated `surplus_gone` entries within one afternoon indicate boundary
churn at the SOC band and would argue for a restart offset. A single stop at dusk is the healthy
shape. The ledger distinguishes them; nothing else does.

---

## 14. Tier and review

**Tier 3.** Cost-impacting, touches a shared primitive consumed by multiple coordinators, and
threads a value through a peer-precedence system. Four framing-disjoint code reviews:
A local correctness · B integration and state machine · C test authority via real per-site
source mutation (§12) · D adversarial completeness, diff-blind, over the whole invariant surface
including pre-existing code.

Orchestrator verifies §12 personally before ship. Operator checkpoint BEFORE deploy.

## 15. Cycle-close

* [ ] All §12 drills bite.
* [ ] Suite name-diff vs baseline: zero regressions.
* [ ] `determine_battery_drain_actions` and the claim leg byte-identical (grep-verified).
* [ ] README carries the post-restart `Validated <date>` table.
* [ ] Post-ship supersession audit — including the `fill_priority_soc` DELETE-CANDIDATE gate and
      the `grid_cap` vs v4.5.0 D4 overlap question.
