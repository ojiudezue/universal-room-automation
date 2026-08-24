# PLANNING — EVSE solar-following amp modulation

**Rev-20 — full rewrite.** Revisions 4-19 layered "authoritative" sections onto an unedited
body until the document argued with itself: two plan reviews returned 39 findings, five
CRITICAL, including a live 2× arithmetic fork and a siting decision that could not execute.
This document replaces all of it. **There are no pointers to prior revisions.** Where a prior
revision's decision survives, its text is here.

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

**INV-SF-1 (non-perturbation).** When no EVSE is in `_excess_solar_active`, D1 writes nothing
and reads no EVSE state beyond the empty-set check.

**INV-SF-2 (writes only inside sessions).** D1 writes a current limit ONLY to an EVSE in
`_excess_solar_active`.

**INV-SF-3 (restore is load-bearing and restart-safe).** When an EVSE leaves
`_excess_solar_active`, its `current_limit` returns to the saved `_original_amps` within one D1
tick, including across a restart — subject to INV-SF-7.

**INV-SF-4 (draw bounded by measured surplus).**
`ELIGIBLE = { e ∈ _excess_solar_active : NOT _stronger_peer_holds(e) AND e ∉ _paused_by_dp AND
_get_evse_state(e)["power_source"] == "sensor" }`.
`DRAWING = { e ∈ ELIGIBLE : _get_evse_state(e)["charging"] is True }`.
`S_eligible = -grid_W + Σ_{e ∈ DRAWING} _get_evse_state(e)["power"]`.
Then `Σ_{e ∈ DRAWING} A_e · 240 · PHASES ≤ max(S_eligible, N_drawing · MIN_AMPS · 240)`, and
each `e ∈ ELIGIBLE \ DRAWING` is commanded exactly `MIN_AMPS`.
The `max(...)` term is the hardware-floor exception: 6 A is the J1772 pilot minimum and cannot
be undercut. There is no headroom term.

**INV-SF-5 (asymmetric reaction to a lagging signal).** Down-steps are immediate and uncapped.
Up-steps require `SOLAR_FOLLOW_UP_MIN_TICKS` consecutive D1 ticks of higher surplus and are
capped at `SOLAR_FOLLOW_UP_STEP_A` per tick. *Measured justification:* the primary is a 60 s
average, and cooking/baking/laundry/dishwashing consume export surplus in multi-kilowatt STEPS,
so a fast-up controller chases each step and immediately reverses. The incumbent's own trace
shows +9 A/min swings; not reproducing that is deliberate.

**INV-SF-6 (fleet allocation).** `N_denom = max(1, N_drawing)`;
`A_per_drawing = clamp(A_total_target // N_denom, MIN_AMPS, MAX_AMPS)`. **This is the single
authority on the denominator.** A non-drawing bay never dilutes the split — it is either empty
or finished, and diluting for it under-uses solar by up to 50%.
Degenerate cases: `N_drawing = 0` → no bay receives an allocation, all ELIGIBLE get MIN
safe-parking; `N_drawing = 1, N_eligible = 2` → the drawing bay gets the full surplus, the other
gets MIN.

**INV-SF-7 (stronger-peer subordination — NO EXCEPTIONS).** While
`_stronger_peer_holds(e)` OR `e ∈ _paused_by_dp`, D1 writes nothing to `e` and captures nothing
from it, on every reachable path. No carve-out exists for any individual owner;
`_paused_by_battery_drain` IS one of the six.

**INV-SF-8 (D1 owns no session state).** D1 never mutates `_excess_solar_active`, never
dispatches a `switch` service call, and never decides a START or a STOP. It computes and writes
current limits, and it may RAISE a stop REQUEST that D2 acts on. Violations are review-blocking.

**INV-STOP-1 (stop requires a reason).** Every removal from `_excess_solar_active` writes a
non-null cessation reason from the closed set in D2.4, including the peak-clear and
blind-window-drop paths.

**INV-STOP-2 (a peer hold is never a stop).** While a stronger peer holds an EVSE, no stop
condition may fire against it and no stop timer may accrue. A peer hold suspends solar-follow's
authority over that bay; it does not end the session.

---

## 5. D1 — SolarFollowController (amp modulation only)

**Site:** new class in `energy_pool.py`, modelled on `PoolOptimizer` (`:58-160`) as a decision
object. **Constructed and stored on `EnergyCoordinator`** (`energy.py`, alongside `self._ev` at
`:293`) as `self._solar_follow`, and given a reference to the pool controller:

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
        self._writes_this_hour: dict[str, list[float]] = {}
        self._stale_ticks: int = 0
        self._blind_since: float | None = None
        self._last_commanded: dict[str, float] = {}
        self._stop_requests: dict[str, str] = {}   # evse_id -> reason, drained by D2
```

**Cross-class access convention:** bare `self.` for D1's own attributes; `self._ev.<attr>` with
`# noqa: SLF001` for every read of pool state (`_excess_solar_active`, `_paused_by_dp`,
`_stronger_peer_holds`, `_get_evse_state`, `_evse`), matching the precedent at `energy.py:4141`,
`:4517`, `:4929`, `:5031`. **D1 performs no cross-class WRITES** (INV-SF-8).

**Cadence:** its own `async_track_time_interval` at 60 s, started in `async_setup_entry` after
the EC is constructed, cancelled in teardown. Always-on with an empty-set fast path — a lazy
start would require observing set mutations, which needs an EC-tick hook this cycle forbids.

### D1.1 — per-tick control law

```
0. If _ev._excess_solar_active is empty AND _original_amps is empty: return.   [INV-SF-1]

1. RESTORE PASS. For evse_id in list(self._original_amps):        [snapshot — the loop mutates]
     if _stronger_peer_holds(evse_id) or evse_id in _paused_by_dp:  continue   [INV-SF-7]
     if evse_id in _excess_solar_active:                            continue
     resolved = current_limit entity for evse_id (D1.4)
     if resolved is None or evse_id not in _ev._evse:
         self._original_amps.pop(evse_id, None); continue          [no write; prune]
     write resolved <- self._original_amps.pop(evse_id)

2. GRID READ (D1.2). If unavailable: handle staleness (D1.3) and return.

3. ELIGIBLE and DRAWING per INV-SF-4, using SUBSCRIPT access.

4. S_eligible = -grid_W + Σ_{DRAWING} power.
   Sanity: if S_eligible > nameplate_w * 1.15 -> WARNING, treat as stale (D1.3), return.

5. A_total_target = floor(S_eligible / (240 * PHASES)).
   N_denom = max(1, len(DRAWING)).
   A_per_drawing = clamp(A_total_target // N_denom, MIN_AMPS, MAX_AMPS).       [INV-SF-6]

6. For each evse_id in ELIGIBLE:
     if evse_id not in self._original_amps:
         cur = current value of the limit entity
         if cur is None or cur < SOLAR_FOLLOW_CAPTURE_SANITY_A:
             self._original_amps[evse_id] = MAX_AMPS      # WARN; do not laminate a throttle
         else:
             self._original_amps[evse_id] = cur
     A_target = A_per_drawing if evse_id in DRAWING else MIN_AMPS
     A_current = current value of the limit entity
     if A_target > A_current:                                     [INV-SF-5 up-gate]
         self._up_streak[evse_id] += 1
         if self._up_streak[evse_id] < SOLAR_FOLLOW_UP_MIN_TICKS: continue
         A_target = min(A_target, A_current + SOLAR_FOLLOW_UP_STEP_A)
     else:
         self._up_streak[evse_id] = 0
     if abs(A_target - A_current) < SOLAR_FOLLOW_DEADBAND_A: continue
     if hourly write budget for evse_id exhausted: WARN once; continue
     write A_target; record self._last_commanded[evse_id]; stamp the write time
```

**Ordering is total.** Restore precedes read precedes allocate precedes write. Step 1 runs even
when the session set is empty, which is what makes INV-SF-3 hold after a restart.

**First tick of a session:** the bay is in ELIGIBLE with no `_original_amps` entry; step 6
captures before commanding. **First tick after restart:** `_original_amps` is restored from
persistence (D1.5) before the timer's first fire, so step 1 can act on it.

### D1.2 — grid signal

* **PRIMARY:** the entity in `CONF_ENERGY_SOLAR_FOLLOW_GRID_ENTITY` (NEW, rung 2 — see §11),
  defaulting to `sensor.mains_vue_3_power_minute_average`. Emporia mains, **W, negative =
  export** (measured).
* **FALLBACK:** `CONF_ENERGY_GRID_IMPORT_ENTITY` — already configured to
  `sensor.envoy_..._current_net_power_consumption`. **kW, negative = export.** Multiply by 1000.
* Availability test: `state not in {unknown, unavailable, None}` and float-parseable.
* **Unit handling is per-source and explicit** — read `unit_of_measurement`; accept `W`/`None`
  as identity and `kW`/`kw` as ×1000; **refuse anything else** and treat the source as
  unavailable (Bug Class #30, matching `mains_export_active`'s posture).

**D1 does NOT call `mains_export_active()` and does not change it.** That function returns
`bool | None`, D1 needs the signed number, and it has two live consumers
(`energy_pool.py:633`, `:1422`) plus a shim-and-drift-guard test. Widening it would put an
inverted signal into blind-window ride permission the day the primary is wired. A prior revision
proposed exactly that on the false premise of "no live consumers"; it is rejected here on
evidence.

**Why Emporia is PRIMARY when EC's global hierarchy prefers Envoy** — operator ruling: the two
answer different questions. EC's is a global source-trust order; solar-follow needs the most
accurate instantaneous grid-boundary reading. The Envoy has a reliability history (which is why
`envoy_available` machinery exists) and a production sensor observed stale for 16.5 h on
2026-08-24. Not a defect to reconcile.

### D1.3 — blind state (grid signal only)

Blind means BOTH primary and fallback are unavailable. It does **not** mean degraded EVSE
signals — status, power and the limit entity are a different integration and typically remain
available, as do battery SOC and the Solcast forecast.

* Under `SOLAR_FOLLOW_STALE_GRACE_S` (300 s) from first unavailability: no writes, no warning.
* At `SOLAR_FOLLOW_STALE_GRACE_S`: WARNING, set `_blind_since`, keep the session.
* At `SOLAR_FOLLOW_BLIND_EXIT_S` (900 s) from first unavailability: **raise a stop request**
  `self._stop_requests[evse_id] = "signal_lost"` for every EVSE in the session. D2 performs the
  stop on its next tick (INV-SF-8 — D1 does not stop sessions itself). Bounded latency ≤5 min.

Rationale: with no surplus reading we cannot size draw, and the charger otherwise holds its last
commanded limit — possibly 48 A against no surplus — indefinitely. **All other stop paths keep
working while blind**, because none of them reads the grid sensor.

### D1.4 — current-limit entities

Add `"current_limit"` to both entries of `DEFAULT_EVSE_ENTITIES` (`energy_pool.py:167-183`):
`garage_a` → `number.garage_a_evse_emporia_wifi_garagea_current_limit`, `garage_b` →
`number.garage_b_evse_emporia_wifi_garageb_current_limit`. L1 chargers excluded.

**Resolution order, and the trap:** `EVChargerController.__init__` uses
`evse_config or DEFAULT_EVSE_ENTITIES` (`:193-198`), so a deployment supplying `evse_config`
never sees additions to the DEFAULT map. D1 therefore resolves as
`self._ev._evse.get(evse_id, {}).get("current_limit") or DEFAULT_EVSE_ENTITIES.get(evse_id, {}).get("current_limit")`
and, if both are empty, **logs a WARNING once per EVSE and skips that bay entirely** rather than
silently no-op'ing. A silent no-op on the live install is the failure this guards.

### D1.5 — persistence of `_original_amps`

**Decision: the KV blob path. No schema change. No builder choice.** `save_evse_state`
(`database.py:4517`) writes a table created with `IF NOT EXISTS` (`:1202-1207`), so a new column
would require an `ALTER TABLE` migration on existing installs and would break
`restore_evse_state`'s `dict[str, dict[str, bool]]` annotation and the truthiness idiom at
`energy.py:1365-1366` (a saved `0.0 A` would restore as absent).

Use the existing KV mechanism with a new hook registered in `_KNOWN_HOOKS`
(`energy.py:1603-1612` — it RAISES on unrecognised names, so registration is mandatory):
key `solar_follow_original_amps_v1`, value `{evse_id: amps}`. Restored before D1's timer starts.

The KV path's 10 h staleness gate (`energy.py:1368-1374`) applies: if the blob is older, DISCARD
it and do NOT capture the current value as `_original_amps` — capture happens fresh in step 6
with the sanity floor. Laminating a throttle as "original" is the failure this avoids.

`_original_amps`, `_up_streak`, `_writes_this_hour`, `_last_commanded` and `_stop_requests` are
all per-EVSE and MUST be pruned by `_prune_removed_evses` (`energy_pool.py:213-216`).

### D1.6 — bounded write verification

After each write, re-read the limit entity once after `SOLAR_FOLLOW_VERIFY_S`. If it differs
from `_last_commanded[evse_id]`, log a WARNING and increment a counter. **No stop, no retry.**

A prior revision proposed a "foreign writer" detector that STOPPED the session when the entity
changed on a no-write tick. It is **rejected**: the Emporia cloud echoes writes with delay, so a
delayed echo landing on a deadband-suppressed tick would trip it and kill the session with a
misattributed cause. The precondition (Emporia native mode off) plus a warning counter is the
proportionate control.

---

## 6. D2 — session start and stop

**Site:** `EVChargerController.determine_excess_solar_actions`, `energy_pool.py:1318-1702`.

### D2.1 — the stop sweep (NEW placement, and the reason)

The existing release leg is inside `else:` at `:1685` and therefore runs ONLY when
`conditions_met` is False. The idle, disconnected and signal-lost stops must fire while
`conditions_met` is TRUE — a bay can sit finished for an hour on a perfect solar day. Placing
them in the release leg would make them dead code.

**Insert a per-EVSE stop sweep immediately before `conditions_met` is computed (`:1572`),** after
the blind-window handling:

```python
# Locals available at :1572 are ONLY the parameters (soc, remaining_forecast_kwh,
# tou_period, soc_threshold, kwh_threshold, dp_carrier_state, coord) and `actions`.
# `switch_entity` is NOT in scope here — it is bound inside the loops at :1359,
# :1549 and :1589. The sweep MUST resolve it per-EVSE or it raises NameError.
# `now` must be WALL CLOCK (not monotonic) because the duration tests in D2.2
# compare against entity `last_changed`, which is a datetime.
from homeassistant.util import dt as dt_util          # noqa: PLC0415
now = dt_util.utcnow()

for evse_id in list(self._excess_solar_active):       # snapshot — loop discards
    config = self._evse.get(evse_id, {})
    switch_entity = config.get("switch", "")
    if not switch_entity:
        continue                                       # unresolvable; leave the claim alone
    if self._stronger_peer_holds(evse_id) or evse_id in self._paused_by_dp:
        self._clear_stop_timers(evse_id)               # INV-STOP-2: reset, do not accrue
        continue
    reason = self._solar_stop_reason(evse_id, now)
    if reason:
        actions.append({"service": "switch.turn_off", "target": switch_entity, "data": {}})
        self._excess_solar_active.discard(evse_id)
        self._record_cessation(evse_id, reason, now)
```

**The claim leg (`:1581-1684`) and the release leg (`:1685-1700`) are BYTE-IDENTICAL.** The
sweep is additive.

**Placement relative to early returns.** The peak branch (`:1355-1374`) releases everything and
returns before the sweep — correct, nothing to sweep. The blind-window legs (`:1529`, `:1571`)
return before the sweep, so **sessions persist through a blind window**; the blind-window guard
owns that decision. Stated deliberately.

### D2.1a — session-start stamp (required by `SOLAR_MIN_ON_S`)

`SOLAR_MIN_ON_S` gates every stop on session age, and no field held it. Add
`_excess_solar_started_at: dict[str, datetime]` on `EVChargerController`.

* **Stamped** at every site that ADDS to `_excess_solar_active` — `energy_pool.py:1656`,
  `:1671`, `:1679` (the plain claim, the DP-yield claim and the TOU claim).
* **Cleared** at every site that discards — the sweep, the release leg `:1699`, the peak-clear
  `:1369`, the blind-window drop `:1564`. Same four sites as the ledger (INV-STOP-1), so they
  are maintained together or not at all.
* **Pruned** by `_prune_removed_evses`.
* **RAM-only, deliberately.** After a restart a running session's age resets, so the 300 s floor
  re-arms and stops are delayed by up to 5 minutes. That errs toward NOT stopping, which is the
  safe direction; persisting it would add a writer for a value whose only job is to suppress
  premature stops. **A missing stamp is treated as age 0** (i.e. immune until 300 s elapse),
  never as infinitely old — an unstamped bay must not be instantly stoppable.

---

### D2.2 — stop conditions, all expressed as DURATIONS

**No tick counting for stop conditions.** The EVSE `status` entity refreshes at median 130 s and
p90 1104 s, so counting controller ticks against it counts our own polling, not evidence.
Durations are measured against the entity's own `last_changed`, or against a stamped session
timestamp. This also removes every clock-ambiguity finding: D1's up-streak is the ONLY
tick-counting quantity left in the cycle.

`_solar_stop_reason(evse_id, now)` returns the first match, or None:

| Reason | Condition | Threshold |
|---|---|---|
| `signal_lost` | `evse_id in _solar_follow._stop_requests` | raised by D1.3 |
| `car_disconnected` | status has read `Disconnected` continuously | `SOLAR_STOP_DISCONNECTED_S` = 300 |
| `car_idle` | `charging` False continuously, status not `Disconnected` | `SOLAR_STOP_IDLE_S` = 1200 |
| `surplus_gone` | `soc < stop_soc` OR `remaining_forecast < kwh_threshold`, continuously | `SOLAR_STOP_MIN_S` = 600 |
| `forecast_poor` | `solcast_next_hour_w < SOLAR_FOLLOW_NEXTHOUR_FLOOR_W`, continuously | `SOLAR_STOP_MIN_S` = 600 |

All are additionally gated on session age ≥ `SOLAR_MIN_ON_S` (300).
`status == "unavailable"` advances nothing — it is a statement about the EVSE, not the car.

**Why disconnected is short and idle is long.** Disconnected is unambiguous — no car — so acting
fast costs nothing and acting slow holds a claim pointlessly. Idle is ambiguous: a mid-charge
pause for thermal throttling or cell balancing runs 5-15 minutes, and stopping early costs a
switch cycle and lost charging while stopping late costs one MIN-amp write.

### D2.3 — the SOC band (value hysteresis)

`conditions_met` at `:1572-1576` is ONE boolean serving both legs. Editing it in place would move
the START gate. Instead:

```
conditions_met = (soc is not None and soc >= start_soc                # UNCHANGED — claim leg
                  and remaining is not None and remaining >= kwh_threshold)
stop_soc = min(fill_priority_soc, start_soc)     # defensive: the ordering is NOT enforced
continue_ok = (soc is not None and soc >= stop_soc
               and remaining is not None and remaining >= kwh_threshold)
```

The release leg at `:1685` becomes `if not continue_ok:` — so the 80-95 dead band **holds a
running session without starting a new one**, which is the intended three-way behaviour and is
written nowhere in the prior design.

`start_soc` is the existing `soc_threshold` parameter. `fill_priority_soc` must be **threaded in
as a new parameter** from the caller's tick snapshot `fill_priority_soc_tick`
(`energy.py:5704`), NOT read live off the coordinator — the neighbouring comment at
`energy.py:5700-5703` documents exactly that race. Add `fill_priority_soc: int | None = None` to
the signature and pass it at `energy.py:5757-5762`; when None, `stop_soc = start_soc`
(today's behaviour).

**`number.py:1670-1675` states the ordering invariant `fill_priority_soc < excess_solar_soc` is
"NOT enforced today."** Hence the `min()`: an inverted config would otherwise put the stop
threshold above the start threshold and kill every session on its first tick. Log a WARNING once
when inverted.

### D2.4 — cessation ledger

**Owner: `EVChargerController`**, because every write point is already there. Three per-EVSE
dicts on it: `_last_stop_reason`, `_last_stop_at`, `_last_start_reason`. RAM-only — a lost
diagnostic after a restart is not a lost safety property.

**Closed vocabulary. Start:** `solar_surplus`, `dp_yield`, `tou_claim`.
**Stop:** `surplus_gone`, `forecast_poor`, `car_disconnected`, `car_idle`, `signal_lost`,
`peak_clear`, `blind_window_drop`.

**Every removal site writes one** (INV-STOP-1): the sweep, the release leg at `:1699`, the
peak-clear discard at `:1369` → `peak_clear`, and the blind-window DROP leg at `:1564` →
`blind_window_drop`. The last two are pre-existing paths that this cycle must not leave silent.

**`peer_hold` is NOT a stop reason** — a peer hold never ends a session (INV-STOP-2). Which owner
holds a bay is already published by `pause_reason_human` on the existing sensor.

**URA cannot read car SoC** — the Emporia is a relay plus a power meter with no J1772 SoC leg.
`car_idle` therefore conflates "finished", "hit an app-set limit" and "refused the handshake".
Do not add a heuristic that pretends otherwise; see §8 non-goals.

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
4. NOT modifying the excess-solar CLAIM leg (`:1581-1684`) or the release leg body (`:1685-1700`).
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
| `SOLAR_FOLLOW_VERIFY_S` | 1 | 8 | readback delay |
| `SOLAR_FOLLOW_MAX_WRITES_PER_HOUR` | 1 | 60 | matches the tick; the deadband does suppression |
| `SOLAR_FOLLOW_STALE_GRACE_S` | 1 | 300 | blind declared |
| `SOLAR_FOLLOW_BLIND_EXIT_S` | 1 | 900 | stop request raised |
| `SOLAR_FOLLOW_NEXTHOUR_FLOOR_W` | 1 | 500 | forecast stop |
| `SOLAR_STOP_DISCONNECTED_S` | 1 | 300 | duration on status `last_changed` |
| `SOLAR_STOP_IDLE_S` | 1 | 1200 | duration, power-derived |
| `SOLAR_STOP_MIN_S` | 1 | 600 | conditions/forecast confirm |
| `SOLAR_MIN_ON_S` | 1 | 300 | minimum session age before any stop |
| `CONF_ENERGY_SOLAR_FOLLOW_GRID_ENTITY` | 2 | — | NEW; primary grid entity |
| `CONF_SOLCAST_NEXT_HOUR_ENTITY` | 2 | — | NEW; forecast stop input |

---

## 10. Tests

Behavioural, mutation-anchored. `PYTHONDONTWRITEBYTECODE=1`, cleared `__pycache__`.
**No test contains its own mutation** — mutations live in §12.

**Fixture contract:** `_get_evse_state` is a dict; fixtures return dicts. Every fixture pins
`power_source` explicitly. Fleet fixtures pin `charging` for BOTH bays.

* **T-DICT-1** every D1 read of `_get_evse_state` subscripts. Fixture returns a plain dict with
  no attribute access support, so attribute access raises.
* **T-ELIG-1** a bay with `power_source="switch_status"` (7600 W fabricated) is excluded from
  ELIGIBLE and contributes 0 to `S_eligible`. Under the bug: `S` inflated 7.6 kW.
* **T-ALLOC-1** one drawing bay, one idle bay, 7 kW surplus → drawing bay 29 A, idle bay 6 A.
  Under the `len(ELIGIBLE)` bug: 14 A. Discriminating.
* **T-ALLOC-2** both bays drawing, 7 kW → 14 A each.
* **T-ALLOC-3** `N_drawing = 0` → no divide-by-zero; all ELIGIBLE get 6 A.
* **T-PEER-1** peer-held bay receives no write and no capture across 5 ticks.
* **T-PEER-2** mid-session peer add: `_original_amps` retained AND zero writes on tick 2, with
  the surplus moved DOWN 14 A between ticks so the deadband cannot mask the result.
* **T-STOPSWEEP-1** idle bay stops while `conditions_met` is TRUE. Under the release-leg siting:
  never stops. **This is the founding test for D2.1.**
* **T-BAND-1** session started at SOC 96 survives a dip to 85 for 6 ticks. Under the
  single-threshold bug: stops.
* **T-BAND-2** SOC 79 sustained → stops with `surplus_gone`.
* **T-BAND-3** inverted config (`fill_priority_soc=95`, `start=90`) → `stop_soc` clamps to 90,
  one WARNING, a session started at 91 does not immediately stop.
* **T-DISC-1** status `Disconnected` for 300 s → stop `car_disconnected`; at 290 s → no stop.
* **T-IDLE-1** not charging for 1200 s → stop `car_idle`; a 10-minute mid-charge pause that
  resumes → NO stop.
* **T-PEERSTOP-1** peer holds a bay whose status reads `Disconnected` for 400 s → **no stop**,
  timers cleared. Under the bug: stops with a false `car_disconnected`. (INV-STOP-2)
* **T-BLIND-1** both sources unavailable: no writes at 300 s, stop request at 900 s, D2 stops on
  its next tick with `signal_lost`. Session survives 299 s.
* **T-BLIND-2** while blind, the disconnected and idle stops still function.
* **T-LEDGER-1** every removal path writes a reason: sweep, release leg, peak-clear (`:1369`),
  blind-window drop (`:1564`). Assert non-null for all four.
* **T-RESTORE-1** restart mid-session restores `_original_amps` from the KV blob and the first
  tick restores the limit.
* **T-RESTORE-2** KV blob older than 10 h is DISCARDED; `_original_amps` is re-captured fresh
  with the sanity floor, not laminated from the current throttled value.
* **T-ENTITY-1** an `evse_config`-supplied deployment with no `current_limit` key logs a WARNING
  and skips the bay — it does not silently no-op.
* **T-UNIT-1** a fallback reading in kW is ×1000; an entity with an unexpected unit is treated as
  unavailable, not admitted.

---

## 11. REUSE vs NEW

| Item | Verdict | Evidence |
|---|---|---|
| `_stronger_peer_holds` + inline `_paused_by_dp` | REUSE | `energy_pool.py:383-412` |
| `_get_evse_state` (subscripted) | REUSE | `:650-707` |
| `DEFAULT_EVSE_ENTITIES` + `evse_config` override | REUSE | `:167-183`, `:193-198` |
| `determine_excess_solar_actions` claim/release legs | REUSE UNCHANGED | `:1581-1700` |
| `_prune_removed_evses` | REUSE | `:213-216` |
| KV persistence + `_KNOWN_HOOKS` | REUSE | `energy.py:1603-1612` |
| `sensor...ev_charging_status` | REUSE (extend) | 23 existing attributes |
| `switch...evse_solar_aware_charging` | REUSE | existing master enable |
| `resume_ev_at_battery_soc`, `fill_priority_soc` | REUSE | existing Numbers |
| `CONF_ENERGY_GRID_IMPORT_ENTITY` | REUSE as fallback | already configured |
| `mains_export_active` | REUSE UNCHANGED (not called) | two live consumers |
| `SolarFollowController` | NEW | no 60 s modulation loop exists |
| `CONF_ENERGY_SOLAR_FOLLOW_GRID_ENTITY` | NEW | no config field for the Emporia mains POWER entity |
| `CONF_SOLCAST_NEXT_HOUR_ENTITY` | NEW | existing Solcast fields are today/tomorrow/remaining/day3 |
| `number...excess_solar_confirm` | NEW | one control |

---

## 12. Mutation drills

Real per-site source mutation, ONE at a time, restore after each.

* **C1** attribute access instead of subscripting in ELIGIBLE → **T-DICT-1** fails.
* **C2** drop the `power_source == "sensor"` gate → **T-ELIG-1** fails.
* **C3** `N_denom = len(ELIGIBLE)` → **T-ALLOC-1** fails.
* **C4** remove `max(1, ...)` → **T-ALLOC-3** fails (crash).
* **C5** remove the peer guard from the D1 write path → **T-PEER-1** fails.
* **C6** remove the peer guard from the D2 stop sweep → **T-PEERSTOP-1** fails.
* **C7** move the stop sweep into the `else:` release leg → **T-STOPSWEEP-1** fails.
* **C8** revert the release leg to `if not conditions_met:` → **T-BAND-1** fails.
* **C9** drop the `min()` in `stop_soc` → **T-BAND-3** fails.
* **C10** count ticks instead of duration for disconnected → **T-DISC-1** fails at the boundary.
* **C11** remove the blind exit stop request → **T-BLIND-1** fails.
* **C12** skip the ledger write on the peak-clear path → **T-LEDGER-1** fails.
* **C13** ignore the 10 h KV staleness gate → **T-RESTORE-2** fails.
* **C14** fall back to `DEFAULT_EVSE_ENTITIES` only → **T-ENTITY-1** fails.

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

**D2.3 (band)**
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
