# PLANNING — EVSE solar-following amp modulation (D1 only)

**Status:** build-ready pending a focused plan-review of the 2026-08-25 additions. Tier 3. Self-contained.

**Changelog 2026-08-25 (operator-directed, added post-review):**
- **INV-SF-10 (grid freshness).** Closed a stale-but-available hole: §5.4 previously declared blind
  only on BOTH sources *unavailable*, so a numeric-but-frozen grid reading (e.g. a stuck Emporia
  minute-average that never goes `unavailable`) would be sized on — overshooting into the battery,
  the exact harm this cycle prevents. The grid read now enforces a `last_reported` freshness gate
  (`SOLAR_FOLLOW_GRID_FRESH_S`, 300 s) and a stale PRIMARY hands off to the FALLBACK just like an
  absent one. **`last_reported`, not `last_updated`** — the grid sensors are minute-averages that
  re-emit unchanged values (§2), so `last_updated` would false-trip on a stable house.
- **DP-coupling observability** (`solar_follow_below_dp_l1_threshold`, `solar_follow_grid_source`).
  Read-only cross-reference so a DP `l1_only` no-drain is diagnosable as "solar-follow throttled the
  charger below 3 kW" without DP ever reading D1 state — closes the mis-attribution hazard the card
  raised (gate 6 masked the 2026-08-20 drain defect) while respecting the never-coordinate scope fence.
  This is the endorsed response to "adjust the DP arithmetic coupling?" — make it legible, not tune it.

These two additions touch the invariant + observability surface; per Plan Review tiering they get
one focused adversarial plan-review pass (freshness-field correctness, fallback-on-stale selection,
the read-only-ness of the DP flag) before build dispatch.

**Scope:** amp modulation ONLY. This cycle changes *how much current* an EVSE draws inside a
solar session. It does not change when sessions start or stop — the existing claim and release
logic in `determine_excess_solar_actions` is untouched.

**Why the scope is this narrow.** An earlier draft also reworked session start/stop (idle and
disconnected stops, a SOC hysteresis band, a cessation ledger). Three framing-disjoint plan
reviews found every *design*-level critical in that half and none in modulation — including a
stop/restart oscillator: a per-EVSE stop sited above the claim leg is re-claimed by the claim
leg on the next tick, forever. That work is carded separately as `EVSE-SOLAR-STOP-CONDITIONS-1`
with the oscillator as its founding problem. Modulation stands alone and is worth shipping
alone: it is where the value is, and it needs no new session semantics.

**Companion:** `PLANNING_dp_drain_target_mis_sourcing.md` ships FIRST. Solar-follow reads
`_paused_by_dp` but has no code dependency on it; shipping DP first means modulation is
validated against a corrected drain target rather than one that has never fired a transition.

---

## 1. Purpose

Excess-solar EV charging is binary today: 48 A, 11.5 kW, on or off, regardless of how much
surplus exists. This modulates the charger's current limit between 6 A and 48 A to track
measured export.

**This REPLACES Emporia's native solar mode**, which was managing `garage_a` (measured: 85
transitions on `number.garage_a_..._current_limit`, including a ~60 s ramp on 08-20 13:26-13:42
of `30, 29, 27, 23, 32, 26, 24, 19, 15, 24, 23` A) and which the operator has since turned off.
URA's version is worse on latency and signal proximity and better on context — it sees battery
intent, tariff, DP and the peer hierarchy. That trade is the justification.

**Deployment precondition:** Emporia native management must be OFF on any EVSE URA modulates.
Two controllers ramping the same limit at 60 s will chase each other.

**Honest regression:** the incumbent was autonomous; this is not. If URA is down or the grid
signal is blind, nothing modulates and the charger returns to its captured limit. Stated in the
README.

---

## 2. Measured facts this plan rests on

Measured 2026-08-23/24 against the live recorder. Re-verify before restating.

| Fact | Value | Why it matters |
|---|---|---|
| Emporia mains sign | **negative = export** (-5924 W while exporting) | D1's `S = -grid_W + add_back` |
| Envoy net sign | **negative = export** (-6.177 kW, same moment) | same formula, unit differs |
| Emporia/Envoy skew | 253 W at that sample; median 259 W, scales with slew (241 W quiet → 1610 W fast) | why an agreement-gate was rejected; why up-ramp is damped |
| Emporia mains refresh | median 61 s, p90 120 s | the 60 s loop is matched to it |
| Envoy net refresh | median 70 s, p90 86 s | fallback equally usable |
| **EVSE power refresh** | median 60 s, **p90 250 s** | why DRAWING needs a freshness gate |
| `current_limit` accepts | ~60 s writes sustained (Emporia's own ramp) | 60 s cadence proven, not assumed |
| Peak solar AC production | 18.2 kW = 75.8 A | **exceeds the 48 A clamp — the clamp is load-bearing** |
| Service | 400 A / two 200 A panels; **EVSEs on SEPARATE 60 A circuits, different panels** | no shared-branch contention; 48 A IS the circuit bound |
| Single charger peak | 12.24 kW (51 A) | the binary behaviour this replaces |

**`SOLAR_FOLLOW_MAX_AMPS = 48` is DERIVED:** 80% NEC continuous of a dedicated 60 A branch, one
circuit per EVSE. **DO NOT RAISE** because the hardware supports more. At peak production the
unclamped allocation is 75 A, so this clamp is the only thing keeping a 60 A branch inside code.

---

## 3. Institutional context verified

* `EVChargerController.determine_excess_solar_actions` — `domain_coordinators/energy_pool.py:1318-1702`.
  Owns claim, peer guards, DP sticky-yield, TOU claim handoff, blind-window deferral, release.
  **This cycle does not modify it.**
* **Its call site is double-gated** — `domain_coordinators/energy.py:5708` `if not
  self._observation_mode:` and `:5733` `if self._excess_solar_enabled:`. D1 must honour both
  (D1.8), or the master switch would not disable the feature and observation mode would not
  contain it (Bug Class #23).
* `_stronger_peer_holds` — `energy_pool.py:383-412`. True for six owners via
  `EV_REGISTRY.iter_peer_holds()`: `grid_cap`, `battery_drain`, `arbitrage`, `load_shed`,
  `fill_priority`, `blind_window`. `_paused_by_dp` is excluded and checked inline. Docstring
  says "the five"; the loop returns six — stale comment, fix in-cycle (comment-only edit).
* **`_get_evse_state(evse_id)` returns a `dict`** — `:650-707`, keys `is_on`, `power`, `status`,
  `charging`, `power_source`. **SUBSCRIPT IT.** Every existing call site does. **It carries no
  timestamp**, so the freshness gate must read `hass.states.get(power_entity).last_updated`
  directly.
* `charging = power > EVSE_CHARGING_POWER_THRESHOLD` (100 W) at `:691`. The v4.2.19 fallback at
  `:690-697` sets `charging=True`, `power=EVSE_ESTIMATED_POWER_W` (**7600 W fabricated**),
  `power_source="switch_status"`. Hence ELIGIBLE gates on `power_source == "sensor"`.
* `:668-681` assigns `power_source = "sensor"` **before** parsing and swallows `ValueError`, so
  a non-numeric state yields `power_source="sensor", power=0.0`. Hence the numeric witness.
* **`current_charging_load_w()` (`:2286-2311`) is NOT USED**: a fleet total that sums the 7600 W
  fabrication.
* `DEFAULT_EVSE_ENTITIES` — `:167-183`. `__init__.py:3183-3187` copies it per bay on every boot
  and overrides individual keys, so additions propagate and `evse_config` is never `None`.
* `mains_export_active()` — `energy.py:4044`, `bool | None`, positive-export contract, two live
  consumers (`energy_pool.py:633`, `:1422`) and a shim + drift-guard test at
  `quality/tests/test_blind_window_evse_guard.py:1282-1380`. **Not called, not modified.**
* `db.save_energy_state` / `db.restore_energy_state_with_age` — `database.py:4868`, `:4898`,
  **both `async def`**. Hook-free precedent: `_restore_wv_state`, `energy.py:1673-1684`.
* `_prune_removed_evses` — `energy_pool.py:773-808`. Registry-driven via
  `EV_REGISTRY.iter_prune_sets()/iter_prune_dicts()`, resolves `getattr` on
  `EVChargerController`, and runs from its `__init__`. **It cannot reach D1's state** — see D1.9.
  `energy_pool_owners.py:20-25` declares that module BEHAVIOR-FROZEN against
  `quality/tests/golden/owner_registry_v1.jsonl.gz`; this cycle adds no declarations.
* `async_call_later` verify pattern with supersession and `cancel_all` —
  `energy_write_verify.py:572`, `:1301-1303`.
* Config surface enumerated per the `ura-config-and-flags` skill.

---

## 4. Falsifiable invariants

**INV-SF-1 (non-perturbation).** When `_excess_solar_active` is empty AND `_original_amps` is
empty, D1 writes nothing and reads no EVSE state beyond the empty-set check. When
`_original_amps` is non-empty the restore pass runs — the sole exception, and it only writes a
previously captured value back.

**INV-SF-2 (writes only inside sessions).** D1 writes a current limit ONLY to an EVSE in
`_excess_solar_active`, except the restore pass, which writes only to one that has just left it.

**INV-SF-3 (restore is load-bearing and restart-safe).** When an EVSE leaves
`_excess_solar_active`, its `current_limit` returns to the saved `_original_amps` within one D1
tick, including across a restart — subject to INV-SF-7. **And a bay URA has throttled is never
left below `SOLAR_FOLLOW_CAPTURE_SANITY_A` with no path back** (D1.6 boot reconciliation).

**INV-SF-4 (draw bounded by measured surplus).**
```
ELIGIBLE = { e ∈ _excess_solar_active :
             NOT _stronger_peer_holds(e)
             AND e ∉ _paused_by_dp
             AND state(e)["power_source"] == "sensor"
             AND state(e)["power"] parsed numerically this tick }
DRAWING  = { e ∈ ELIGIBLE :
             state(e)["charging"] is True
             AND now - hass.states.get(power_entity(e)).last_updated <= SOLAR_POWER_FRESH_S }
S_eligible = -grid_W + Σ_{e ∈ DRAWING} state(e)["power"]
```
Then, quantified over **ELIGIBLE**:
```
Σ_{e ∈ ELIGIBLE} A_e · 240 · SOLAR_FOLLOW_PHASES  ≤  max(S_eligible, N_eligible · MIN_AMPS · 240)
```
**The allocator must NET the parked floor out before dividing** (D1.2 step 5). Allocating the
full surplus to DRAWING bays and then paying each parked bay's 6 A on top makes this invariant
false in the ordinary mixed fleet state: one bay at 29 A plus one parked at 6 A is 8400 W
against 7000 W of surplus. Netting first gives 23 A and 6960 W, which holds. **There is no
headroom term.**

**INV-SF-10 (grid freshness — no sizing on a stale grid read).** `S_eligible` is computed only
from a grid source whose `last_reported` age is `≤ SOLAR_FOLLOW_GRID_FRESH_S`. A source that is
`available` but whose `last_reported` is older than that threshold is treated as unavailable and
handed off to the fallback; if BOTH are stale-or-unavailable, D1 is blind (§5.4) and writes
nothing. **Falsified by:** any tick where `-grid_W` enters `S_eligible` from an entity whose
`last_reported` age exceeds the threshold. This is the stale-but-available failure the binary
`unavailable`-only check missed — sizing draw on a frozen export reading is how the controller
overshoots into the battery, the exact harm this cycle exists to prevent.

The `SOLAR_POWER_FRESH_S` gate exists because the per-EVSE power sensor (p90 250 s) can lag the
mains sensor (p90 120 s), so the add-back can describe a draw the grid term already stopped
seeing. **A stale reading excludes the bay from the add-back but does NOT re-target it** — see
D1.2 step 6; dropping it to MIN on a stale sample would throttle 48 A → 6 A and then take ~14
minutes to climb back, on ≥10% of ticks.

**INV-SF-5 (asymmetric reaction to a lagging signal).** Down-steps are immediate and uncapped.
Up-steps require `SOLAR_FOLLOW_UP_MIN_TICKS` consecutive ticks of higher surplus and are capped
at `SOLAR_FOLLOW_UP_STEP_A` per tick. *Measured justification:* the primary is a 60 s average,
and cooking/baking/laundry/dishwashing consume export surplus in multi-kilowatt STEPS, so a
fast-up controller chases each step and immediately reverses.

**INV-SF-6 (fleet allocation).** `N_denom = max(1, N_drawing)`. A non-drawing bay never dilutes
the split. Degenerate: `N_drawing = 0` → no bay receives an allocation, all ELIGIBLE get MIN.

**INV-SF-7 (stronger-peer subordination — NO EXCEPTIONS).** While `_stronger_peer_holds(e)` OR
`e ∈ _paused_by_dp`, D1 writes nothing to `e` and captures nothing from it, on every reachable
path including the restore pass. **Re-checked immediately before each write**, not once per
tick — the write loop awaits, and a peer can claim a bay inside that window.
`_paused_by_us` (TOU) is deliberately not a hold: the claim leg establishes TOU as the one set
excess-solar legitimately claims against.

**INV-SF-8 (D1 owns no session state).** D1 never mutates `_excess_solar_active`, never
dispatches a `switch` service call, and never decides a start or a stop. It writes current
limits and nothing else. Violations are review-blocking.

**INV-SF-9 (gated identically to the feature it serves).** D1 performs no writes when
`_observation_mode` is True or `_excess_solar_enabled` is False. On the enabled→disabled edge it
runs the restore pass once, then goes quiet — so turning the master switch off un-throttles
rather than freezing the fleet at a modulated limit.

---

## 5. D1 — SolarFollowController

**Site:** new class in `domain_coordinators/energy_pool.py`, modelled on `PoolOptimizer`
(`:58-160`).

**Construction:** on `EnergyCoordinator` as `self._solar_follow`, **after the entity-config
block that reads grid entities** (`domain_coordinators/energy.py:478-499`) — NOT alongside
`self._ev` at `:293`, where `ec.get(...)` has not run and both entity arguments would be `None`,
leaving the feature silently dormant.

```python
class SolarFollowController:
    def __init__(self, hass, coord, ev: EVChargerController, db,
                 grid_primary_entity: str | None,
                 grid_fallback_entity: str | None) -> None:
        self.hass = hass
        self._coord = coord            # EnergyCoordinator; passed as `self` at construction
        self._ev = ev
        self._db = db                                  # for D1.7 persistence
        self._grid_primary = grid_primary_entity
        self._grid_fallback = grid_fallback_entity
        self._up_min_ticks: int = SOLAR_FOLLOW_UP_MIN_TICKS   # Number overrides (D1.10)
        self._original_amps: dict[str, float] = {}
        self._up_streak: dict[str, int] = {}
        self._writes: dict[str, list[float]] = {}      # monotonic stamps, rolling 3600 s
        self._last_commanded: dict[str, float] = {}
        self._pending_verify: dict[str, Callable[[], None]] = {}
        self._blind_since: float | None = None          # monotonic
        self._was_enabled: bool = True                  # for the disable edge (INV-SF-9)
        self._touched: set[str] = set()                 # bays URA has throttled (D1.6)
```

**Cross-class convention:** bare `self.` for D1's own attributes; `self._ev.<attr>` with
`# noqa: SLF001` for every READ of pool state, matching `energy.py:4141`, `:4517`, `:4929`,
`:5031`. **D1 performs no cross-class writes** (INV-SF-8).

**Cadence:** `async_track_time_interval(hass, self._tick, timedelta(seconds=SOLAR_FOLLOW_TICK_S))`
registered in `async_setup_entry`, with the unsub handle passed to `entry.async_on_unload(...)`
so it cannot outlive the entry. `cancel_all()` (D1.8) is called from the EC teardown path.

### 5.1 — helpers, fully specified

* `_limit_entity(evse_id) -> str | None` — `self._ev._evse.get(evse_id, {}).get("current_limit")`
  or None, logging a WARNING once per EVSE when absent. No `DEFAULT_EVSE_ENTITIES` fallback:
  `evse_config` is always populated from it, and a second `evse_id`-keyed lookup could resolve a
  *different physical charger's* entity on a renamed deployment.
* `_read_amps(entity) -> float | None` — `hass.states.get(entity)`; None when the state is
  missing, `unknown`, `unavailable`, or non-numeric.
* `_write_amps(entity, amps) -> None` — `await hass.services.async_call("number", "set_value",
  {"entity_id": entity, "value": float(int(amps))}, blocking=False)`. Amps are integers on the
  wire; `int()` before `float()` so a `//` result never sends a fraction.
* `clamp(v, lo, hi)` is `max(lo, min(hi, v))` written inline — Python has no builtin; do not
  import one.
* `_restore_pass()` — specified at the end of 5.2. `_persist()` — 5.7. `_tick(now)` — the
  coroutine registered with `async_track_time_interval`; its body is 5.2.
* `_budget_allows(evse_id) -> bool` — prunes `self._writes[evse_id]` of stamps older than
  3600 s, returns `len(stamps) < SOLAR_FOLLOW_MAX_WRITES_PER_HOUR`. Rolling window, RAM-only.

### 5.2 — per-tick control law

```python
# 0. GATING (INV-SF-9) and SELF-PRUNE.
enabled = (self._coord._excess_solar_enabled                 # noqa: SLF001
           and not self._coord._observation_mode)           # noqa: SLF001
if not enabled:
    if self._was_enabled:
        await self._restore_pass()          # un-throttle once on the disable edge
        self._was_enabled = False
    return
self._was_enabled = True

known = set(self._ev._evse)                                            # noqa: SLF001
for d in (self._original_amps, self._up_streak, self._writes,
          self._last_commanded, self._pending_verify):
    for gone in [k for k in d if k not in known]:
        d.pop(gone, None)
self._touched &= known

if not self._ev._excess_solar_active and not self._original_amps:      # noqa: SLF001
    return                                                              # INV-SF-1

# 1. RESTORE PASS.
await self._restore_pass()

# 2. GRID READ (D1.3). If blind: handle staleness and return.

# 3. Build THREE sets per INV-SF-4 — dict subscripting, numeric witness, freshness gate.
#    ELIGIBLE     : passes the peer, DP, power_source and numeric-witness clauses.
#    DRAWING      : ELIGIBLE and charging and power reading fresh.
#    STALE_POWER  : ELIGIBLE and charging but power reading OLDER than SOLAR_POWER_FRESH_S.
#                   Excluded from the add-back AND from re-targeting (step 6 holds them).

# 4. S_eligible = -grid_W + Σ_{DRAWING} power
#    nameplate_w = self._coord entity-config value of CONF_ENERGY_SOLAR_NAMEPLATE_W
#      (live 19400; falls back to DEFAULT_ENERGY_SOLAR_NAMEPLATE_W when unset).
#    if nameplate_w and S_eligible > nameplate_w * 1.15:
#        WARNING; treat as blind (5.4); return.   # an impossible surplus is a signal fault

# 5. ALLOCATE — net the parked floor out FIRST (INV-SF-4).
parked_w      = (len(ELIGIBLE) - len(DRAWING)) * SOLAR_FOLLOW_MIN_AMPS * 240
allocatable_w = max(0, S_eligible - parked_w)
A_total       = int(allocatable_w // (240 * SOLAR_FOLLOW_PHASES))
N_denom       = max(1, len(DRAWING))
A_per_drawing = clamp(A_total // N_denom, SOLAR_FOLLOW_MIN_AMPS, SOLAR_FOLLOW_MAX_AMPS)

# 6. PER-EVSE WRITE.
for evse_id in ELIGIBLE:
    entity = self._limit_entity(evse_id)
    if entity is None:
        continue
    a_current = self._read_amps(entity)
    if a_current is None:
        self._up_streak[evse_id] = 0
        continue                                   # cannot compare; do not guess
    if evse_id not in self._original_amps:
        self._original_amps[evse_id] = (
            a_current if a_current >= SOLAR_FOLLOW_CAPTURE_SANITY_A
            else SOLAR_FOLLOW_RESTORE_AMPS)        # WARN; do not laminate a throttle
        self._touched.add(evse_id)
        await self._persist()
    if evse_id in STALE_POWER:                     # in ELIGIBLE, excluded from DRAWING
        continue                                   # HOLD current amps; do not re-target
    a_target = A_per_drawing if evse_id in DRAWING else SOLAR_FOLLOW_MIN_AMPS
    if a_target > a_current:                                           # INV-SF-5
        self._up_streak[evse_id] = self._up_streak.get(evse_id, 0) + 1
        if self._up_streak[evse_id] < self._up_min_ticks:
            continue
        a_target = min(a_target, a_current + SOLAR_FOLLOW_UP_STEP_A)
    else:
        self._up_streak[evse_id] = 0
    if abs(a_target - a_current) < SOLAR_FOLLOW_DEADBAND_A:
        continue
    if not self._budget_allows(evse_id):
        continue
    if self._ev._stronger_peer_holds(evse_id) or evse_id in self._ev._paused_by_dp:
        continue                                   # INV-SF-7: re-check across the await
    await self._write_amps(entity, a_target)
    self._last_commanded[evse_id] = a_target
    self._schedule_verify(evse_id, entity, a_target)                   # D1.8
```

`a_current` is read ONCE per EVSE per tick and reused for capture, the up-gate and the deadband
— two `hass.states.get` calls could straddle a cloud update and disagree.
`self._up_streak.get(evse_id, 0)` is required: a bare `+= 1` raises `KeyError` on the first
up-step of every session.

**`_restore_pass`** iterates `list(self._original_amps)` (snapshot — it mutates), skips any bay
that is peer-held or still in `_excess_solar_active`, pops and writes the saved value, drops the
entry when the entity is unresolvable, and persists.

### 5.3 — grid signal

* **PRIMARY:** `CONF_ENERGY_SOLAR_FOLLOW_GRID_ENTITY` (NEW, rung 2), default
  `sensor.mains_vue_3_power_minute_average`. **W, negative = export.**
* **FALLBACK:** `CONF_ENERGY_SOLAR_FOLLOW_GRID_FALLBACK_ENTITY` (NEW, rung 2), default
  `sensor.envoy_482543015950_current_net_power_consumption`. **kW, negative = export.**
* **Contract enforced at read time on both:** read `unit_of_measurement`; `W`/`None`/`""`
  identity, `kW`/`kw` ×1000, **anything else → source unavailable** (Bug Class #30). A
  non-numeric state is unavailable, not zero.
* **Freshness enforced at read time on both (NEW — closes the stale-but-available hole):** a
  source whose `hass.states.get(entity).last_reported` age exceeds `SOLAR_FOLLOW_GRID_FRESH_S`
  is treated as **unavailable**, exactly like a bad unit. **Use `last_reported`, NOT
  `last_updated`** — both grid entities are *minute-average* sensors (§2: they re-emit every
  ~60 s even when the value is unchanged), so `last_updated` freezes on a stable export and would
  false-trip blind on a healthy house; `last_reported` bumps on every emission, so a frozen
  `last_reported` means the source genuinely stopped reporting. (Contrast the per-EVSE power gate
  in INV-SF-4, which correctly uses `last_updated` because a charging load fluctuates continuously.)
* **Source selection:** PRIMARY if available-and-fresh; else FALLBACK if available-and-fresh; else
  blind (§5.4). A stale PRIMARY hands off to the FALLBACK the same as an unavailable one — this is
  the un-availability the operator flagged: the fallback must cover *stale*, not only *absent*.

D1 does not reuse `CONF_ENERGY_GRID_IMPORT_ENTITY` (documented in-repo as "Emporia mains",
consumed by `CostTracker`, live value is the Envoy — borrowing a field whose documented meaning
and live value disagree is how a sign fork ships) and does not call or modify
`mains_export_active()`.

**Why Emporia is PRIMARY when EC's global hierarchy prefers Envoy** — operator ruling: the two
answer different questions. EC's is a global source-trust order; modulation needs the most
accurate instantaneous grid-boundary reading.

### 5.4 — blind state

Blind means BOTH sources unavailable **or stale** (per the §5.3 freshness gate — a numeric-but-frozen reading counts as unavailable). It does not mean degraded EVSE signals.

* Under `SOLAR_FOLLOW_STALE_GRACE_S` (300 s) from first unavailability: no writes, no warning.
* At the grace: WARNING, stamp `_blind_since`.
* At `SOLAR_FOLLOW_BLIND_EXIT_S` (900 s): **run the restore pass and go quiet.** With no surplus
  reading D1 cannot size draw, and the charger must not hold a modulated limit indefinitely.
  D1 does NOT end the session — that is not its job (INV-SF-8); the existing release logic ends
  it on its own terms.
* On recovery of either source **to available-and-fresh**: clear `_blind_since` and resume normally. A source that returns to `available` but is still stale does NOT count as recovery.

### 5.5 — current-limit entities

Add `"current_limit"` to both entries of `DEFAULT_EVSE_ENTITIES` (`energy_pool.py:167-183`):

* `garage_a` → `number.garage_a_evse_emporia_wifi_garagea_current_limit`
* `garage_b` → `number.garage_b_evse_emporia_wifi_garageb_current_limit`

L1 chargers excluded.

### 5.6 — boot reconciliation (the un-throttle backstop)

`_original_amps` and `_excess_solar_active` are both restored under a 10 h age gate
(`energy.py:1348`). After a longer outage both restore empty, D1's fast path returns forever, and
a bay left at 6 A stays at 6 A — 1.4 kW — with no code path back.

`_touched` is persisted **without an age gate** (a tiny id list; the amps blob keeps its 10 h
gate). On the first tick after setup, for every `evse_id ∈ _touched` that is NOT in
`_excess_solar_active`, if its limit reads below `SOLAR_FOLLOW_CAPTURE_SANITY_A`, write
`SOLAR_FOLLOW_RESTORE_AMPS`, log INFO, and discard it from `_touched`. This cannot stomp a
deliberate operator setting on a bay URA never throttled, because membership in `_touched` is
the record of having throttled it.

### 5.7 — persistence

Two keys via `db.save_energy_state` / `db.restore_energy_state_with_age` (**both `async`**),
hook-free per `_restore_wv_state` (`energy.py:1673-1684`). Not `_KNOWN_HOOKS`, which is a local
allowlist for `iter_persisted_lists()` declarations requiring `persistence_kind == "list"` and a
set target on `EVChargerController` — registering there would silently no-op. Not a new column:
`save_evse_state` writes a table created with `IF NOT EXISTS`, so a column needs `ALTER TABLE`.

* `solar_follow_original_amps_v1` — `json.dumps(self._original_amps)`, restored with
  `max_age_hours=10`. Stale → discard; capture happens fresh in step 6.
* `solar_follow_touched_v1` — `json.dumps(sorted(self._touched))`, restored with **no age gate**.

**Written on mutation only**, never per tick — an unconditional 60 s write per EVSE is the shape
of the v5.0.0 write-flood incident. **Restored in `async_setup_entry` BEFORE the timer is
registered**, so the first tick can act on it (INV-SF-3).

### 5.8 — bounded write verification

`_schedule_verify` uses `async_call_later`, following `energy_write_verify.py:572`. Do NOT
`await asyncio.sleep()` inside the tick: with two bays that blocks the loop for
`2 × SOLAR_FOLLOW_VERIFY_S`.

```python
async def _delayed(_now):
    self._pending_verify.pop(evse_id, None)
    try:
        observed = self._read_amps(entity)
        if observed is not None and abs(observed - commanded) >= 1:
            _LOGGER.warning(...)                  # counter++, no stop, no retry
    except Exception:                             # noqa: BLE001
        _LOGGER.debug("solar-follow verify raised (swallowed)", exc_info=True)

prev = self._pending_verify.pop(evse_id, None)
if prev is not None:
    prev()                                        # SUPERSEDE
self._pending_verify[evse_id] = async_call_later(self.hass, SOLAR_FOLLOW_VERIFY_S, _delayed)
```

`cancel_all()` calls every outstanding handle from EC teardown — untracked `async_call_later`
handles outliving the coordinator is a known bug class here (`energy_write_verify.py:1301-1303`
exists solely to close it).

**No foreign-writer stop.** A detector that ends the session when the entity changes on a
no-write tick was considered and rejected: the Emporia cloud echoes writes with delay, so a
delayed echo on a deadband-suppressed tick would trip it and kill the session with a
misattributed cause.

### 5.9 — pruning

`_prune_removed_evses` is registry-driven, resolves `getattr` on `EVChargerController`, and runs
from its `__init__` before `self._solar_follow` exists. It cannot reach D1's state and no
`OwnerDeclaration` is added (`energy_pool_owners.py` is BEHAVIOR-FROZEN against a golden).
**D1 prunes its own dicts at the top of every tick** against `set(self._ev._evse)`.

### 5.10 — the operator knob

`number.ura_energy_coordinator_excess_solar_confirm` — "Excess Solar Confirm", minutes, rung 3,
default 3, range 1-10. Its setter calls an `EnergyCoordinator` setter that assigns
`self._solar_follow._up_min_ticks`, mirroring `set_offpeak_drain` (`energy.py:8645`), and
no-ops safely when `_solar_follow` is None. **D1 reads `self._up_min_ticks`, not the module
constant** — the constant is only the `__init__` default. Help text must say "consecutive
minutes of higher surplus before **increasing** the car's amps"; the name alone could be read as
the start gate, which is a different thing.

---

## 6. Observability

**No new entity.** `sensor.ura_energy_coordinator_ev_charging_status` already publishes 23
attributes including `excess_solar_active`, `excess_solar_evses`, per-EVSE dicts, every pause set
and `pause_reason_human`. Solar-follow adds four:

| Attribute | Why not derivable |
|---|---|
| `solar_follow_surplus_kw` | the computed `S_eligible`; without it a sizing bug and a sensor bug look identical |
| `solar_follow_original_amps` | per-EVSE saved restore value; what a stuck-throttle incident needs |
| `solar_follow_state` | per-EVSE `writing` / `yielded` / `blind` / `disabled` |
| `solar_follow_blind_since` | makes the 900 s restore observable before it fires |
| `solar_follow_grid_source` | which grid entity is live this tick (`primary` / `fallback` / `blind`) and whether the primary was demoted for **staleness** vs unavailability — so a stale-but-available Emporia is diagnosable, not silent |
| `solar_follow_below_dp_l1_threshold` | true when D1 is holding any bay's commanded rate ≤ `DP_L1_RATE_THRESHOLD_KW` (3.0 kW). **Read-only cross-reference, NOT coordination** (respects the scope fence): lets anyone diagnosing a DP `l1_only` no-drain see immediately that solar-follow's throttle is the cause, closing the mis-attribution hazard the card raised (the same gate that masked the 2026-08-20 drain-target defect) — without DP ever reading D1 state |

---

## 7. Non-goals

1. NOT changing session start or stop. The claim leg, the release leg and every existing removal
   path are byte-identical.
2. NOT reading car SoC. No J1772 decoding.
3. NOT modifying `determine_battery_drain_actions` — byte-identical. D1 YIELDS to drain
   protection (INV-SF-7); it never suppresses it.
4. NOT modifying `mains_export_active()` or `solar_replenishing`.
5. NOT adding a database column or migration.
6. NOT a foreign-writer stop.
7. NOT a fleet circuit-capacity model — separate 60 A circuits; the per-EVSE 48 A clamp IS the
   bound.
8. NOT changing EC's global source hierarchy.
9. NOT re-solving compound-load protection; `grid_cap` and the v4.5.0 D4 mutex own it.
10. NOT using `current_charging_load_w()`.
11. NOT adding `OwnerDeclaration` rows (the registry is behavior-frozen).
12. NOT shortening the tick or subscribing to owner-set mutations.

---

## 8. Knobs

**Home:** every `SOLAR_*` constant in `domain_coordinators/energy_const.py`; both `CONF_*` fields
declared there, parsed in the coordinator-manager options step of `config_flow.py`, threaded via
`entity_config` in `__init__.py` as `CONF_ENERGY_GRID_IMPORT_ENTITY` is (`energy.py:490`).

| Constant | Rung | Value | Note |
|---|---|---|---|
| `SOLAR_FOLLOW_MIN_AMPS` | 1 | 6 | J1772 pilot floor |
| `SOLAR_FOLLOW_MAX_AMPS` | 1 | 48 | **DERIVED**: 80% of a 60 A branch. DO NOT RAISE |
| `SOLAR_FOLLOW_RESTORE_AMPS` | 1 | 48 | same derivation; used when capture is rejected and by the boot backstop |
| `SOLAR_FOLLOW_PHASES` | 1 | **1** | single-phase 240 V. 48 A × 240 V = 11.52 kW reconciles with the measured 12.24 kW single-charger peak. Named because it appears in load-bearing arithmetic; a guess of 2 is a 2× error |
| `SOLAR_FOLLOW_CAPTURE_SANITY_A` | 1 | 20 | below this, capture MAX not the observed value |
| `SOLAR_FOLLOW_DEADBAND_A` | 1 | 1 | write suppression |
| `SOLAR_FOLLOW_UP_STEP_A` | 1 | 4 | per-tick up cap |
| `SOLAR_FOLLOW_UP_MIN_TICKS` | 3 | 3 | default for `_up_min_ticks`; surfaced as "Excess Solar Confirm" |
| `SOLAR_FOLLOW_TICK_S` | 1 | 60 | cadence |
| `SOLAR_FOLLOW_VERIFY_S` | 1 | 8 | readback delay, via `async_call_later` |
| `SOLAR_FOLLOW_MAX_WRITES_PER_HOUR` | 1 | 60 | tripwire; the deadband does the suppression |
| `SOLAR_FOLLOW_STALE_GRACE_S` | 1 | 300 | blind declared |
| `SOLAR_FOLLOW_BLIND_EXIT_S` | 1 | 900 | restore-and-go-quiet |
| `SOLAR_POWER_FRESH_S` | 1 | 180 | max age of a per-EVSE power reading for DRAWING; that sensor's p90 is 250 s |
| `SOLAR_FOLLOW_GRID_FRESH_S` | 1 | 300 | max **`last_reported`** age of a grid source before it is treated as unavailable (INV-SF-10). Generous vs the measured p90 (Emporia 120 s / Envoy 86 s, §2) so a healthy minute-average never false-trips; tight enough to catch a stuck sensor. Uses `last_reported` NOT `last_updated` (minute-average re-emits unchanged values) |
| `CONF_ENERGY_SOLAR_FOLLOW_GRID_ENTITY` | 2 | — | primary grid entity |
| `CONF_ENERGY_SOLAR_FOLLOW_GRID_FALLBACK_ENTITY` | 2 | — | fallback grid entity |

---

## 9. Tests

Behavioural, mutation-anchored. `PYTHONDONTWRITEBYTECODE=1`, cleared `__pycache__`.
**No test contains its own mutation** — mutations live in §10. **No test asserts on source text**
(Bug Class #62); §11's byte-identical greps are process gates, not tests.

**Fixture contract.**
* `_get_evse_state` returns a dict; fixtures return dicts with `power_source` pinned explicitly.
* **The freshness gate reads `hass.states.get(power_entity).last_updated`, which a dict fixture
  cannot express.** Fixtures MUST register real state objects — reuse the MockState at
  `quality/tests/conftest.py:151`, which carries `last_updated` and is already driven this way by
  `test_ac_ramp_pipeline_hardening.py:166`.
* **Clock: inject it.** Reuse the `fake_clock` pattern in
  `quality/tests/test_arrester_comfort_delay.py`. **Back-dating a private stamp
  (`test_blind_window_evse_guard.py:281`) is forbidden as a test's ONLY anchor** — it folds the
  mutation into the setup. Threshold assertions may back-date; lifecycle assertions must be
  driven by successive ticks with an injected `now`.
* **Every allocation fixture pins `a_current = 48`** so the target is reached in one *down*-step.
  At `a_current = 6` the up-gate and the +4 cap make fix and bug produce identical traces for
  several ticks, and the asserted value is unreachable.
* Fleet fixtures pin `charging` and the power-reading age for BOTH bays, and MUST be able to
  express a grid reading and a power reading that DISAGREE.

**Allocation and eligibility**
* **T-ALLOC-1** `a_current=48`, one drawing bay, one idle-eligible bay, `S=7000 W` → drawing bay
  **23 A**, idle bay 6 A, and `(23+6)·240 = 6960 ≤ 7000` (INV-SF-4 holds). Under an un-netted
  allocator: 29 A and 8400 W — the invariant is violated. Discriminating on tick 1.
* **T-ALLOC-2** both drawing, `S=7000`, `a_current=48` → 14 A each.
* **T-ALLOC-3** `N_drawing = 0` → no divide-by-zero; all ELIGIBLE get 6 A.
* **T-CLAMP-MAX-1** peak-solar fixture: `S = 18200 W`, one drawing bay, `a_current=48` →
  commanded **48**, not 75. **The 48 A circuit bound is the cycle's headline safety derivation
  and this is its only guard.**
* **T-INV-SF-4-PROP** parametrised bound check over surplus ∈ {−4000, 0, 7000, 18200} ×
  `N_drawing` ∈ {0,1,2} × parked-bay present/absent. Asserts the INV-SF-4 inequality directly.
  This is the falsification target reviewer D leans on.
* **T-ELIG-1** a `switch_status` bay (7600 W fabricated) is excluded from ELIGIBLE. Assert the
  **sibling bay's commanded amps**, not the display attribute: under the bug `S` rises 7600 W and
  the sibling gains 31 A.
* **T-ELIG-2** a responsive sensor publishing a non-numeric state (`power_source == "sensor"`,
  `power == 0.0`) is excluded by the numeric witness. Assert the sibling's commanded amps.
* **T-STALE-POWER-1** grid 0 W; `garage_a` `charging=True, power=11500` with a power reading
  200 s old, `a_current=48`. Assert `garage_a ∉ DRAWING`, `S_eligible == 0`, and **the bay HOLDS
  at 48 A** — no write. Under the bug: 47 A commanded off phantom surplus. Under the
  re-target-to-MIN variant: 6 A, and a 14-minute climb back.
* **T-UPSTREAK-1** first up-step of a fresh session does not raise (`KeyError` under a bare `+=`).
* **T-AMPS-NONE-1** the limit entity is `unavailable`: skipped, no write, no capture, streak reset.

**INV-SF-5**
* **T-UP-1** target 40 from `a_current=6`: ticks 1-2 no write; tick 3 writes 10 (gate + cap).
* **T-DOWN-1** target 6 from `a_current=48`: one tick, writes 6.

**Peer subordination and gating**
* **T-PEER-1** peer-held bay: no write, no capture, across 5 ticks, including the restore pass.
* **T-PEER-2** mid-session peer add: `_original_amps` retained AND zero writes on tick 2, with
  the surplus moved DOWN 14 A so the deadband cannot mask the result.
* **T-PEER-3** a peer claims a bay between the ELIGIBLE computation and its write (simulate by
  mutating the set inside the awaited call): no write to that bay. INV-SF-7's re-check.
* **T-GATE-1** `_observation_mode = True` → zero writes.
* **T-GATE-2** `_excess_solar_enabled` goes True→False with a throttled bay → the restore pass
  runs ONCE and the bay returns to `_original_amps`; subsequent ticks write nothing.
* **T-INV-SF-8-1** across a multi-tick run, `_excess_solar_active` is unchanged by D1 and no
  `switch` service call is emitted.

**Restore, persistence, lifecycle**
* **T-RESTORE-1** a bay leaves `_excess_solar_active` mid-run → its limit returns to
  `_original_amps` on the next tick. The ordinary case, previously untested.
* **T-RESTORE-2** restart mid-session: restored via `restore_energy_state_with_age(..., 10)` and
  the first tick restores the limit.
* **T-RESTORE-3** a blob older than 10 h is DISCARDED; capture happens fresh with the sanity
  floor, not laminated from the throttled value.
* **T-BOOT-1** `_touched` contains `garage_a`, both blobs older than 10 h, `garage_a` limit reads
  6 A and it is not in a session → boot reconciliation writes 48 A. **Under the bug the bay stays
  at 6 A forever.**
* **T-BOOT-2** a bay NOT in `_touched` reading 10 A is left alone — no stomping a deliberate
  operator setting.
* **T-PERSIST-1** the blob is written on mutation only, not per tick: 10 ticks with no capture
  change produce one save, not ten.
* **T-PRUNE-1** an EVSE removed from `self._ev._evse` has every D1 dict entry dropped next tick.
* **T-VERIFY-1** two writes inside `SOLAR_FOLLOW_VERIFY_S`: the first pending check is cancelled;
  one comparison runs, against the LATER value.
* **T-VERIFY-2** teardown with a verify outstanding cancels the handle; no callback after
  shutdown.
* **T-WIRE-1** after `async_setup_entry`, `coord._solar_follow` exists with **non-None** grid
  entities, and the timer unsub is registered on the entry.
* **T-WIRE-2** setting the `excess_solar_confirm` Number to 5 changes D1's behaviour: an up-step
  now requires 5 ticks, not 3. Anchors the push path end to end.
* **T-ENTITY-1** an EVSE with no `current_limit` key logs a WARNING once and is skipped.
* **T-UNIT-1** a fallback reading in kW is ×1000; an unexpected unit is treated as unavailable.
* **T-BLIND-1** both sources unavailable: no writes at 299 s; WARNING at 300 s; restore pass at
  900 s; session membership untouched throughout (INV-SF-8).
* **T-DEADBAND-1** a 0.5 A delta produces no write.

---

## 10. Mutation drills

Real per-site source mutation, ONE at a time, **restore after each and verify `git status` is
clean** before the next.

* **C1** attribute access instead of subscripting in ELIGIBLE → **T-ELIG-1** fails.
* **C2** drop the `power_source == "sensor"` gate → **T-ELIG-1** fails.
* **C3** drop the numeric-witness clause → **T-ELIG-2** fails.
* **C4** drop the `SOLAR_POWER_FRESH_S` gate → **T-STALE-POWER-1** fails.
* **C5** re-target stale bays to MIN instead of holding → **T-STALE-POWER-1** fails.
* **C6** skip the parked-floor netting in step 5 → **T-ALLOC-1** and **T-INV-SF-4-PROP** fail.
* **C7** `N_denom = len(DRAWING)` (no `max(1, …)`) → **T-ALLOC-3** fails.
* **C8** remove the MAX arm of the clamp → **T-CLAMP-MAX-1** fails.
* **C9** remove the MIN arm → **T-ALLOC-3** fails.
* **C10** bare `self._up_streak[evse_id] += 1` → **T-UPSTREAK-1** fails.
* **C11** remove the up-gate (`< self._up_min_ticks`) → **T-UP-1** fails.
* **C12** remove the `SOLAR_FOLLOW_UP_STEP_A` cap → **T-UP-1** fails.
* **C13** apply the up-gate to down-steps too → **T-DOWN-1** fails.
* **C14** read `SOLAR_FOLLOW_UP_MIN_TICKS` instead of `self._up_min_ticks` → **T-WIRE-2** fails.
* **C15** remove the pre-write peer re-check → **T-PEER-3** fails.
* **C16** remove the peer guard from the restore pass → **T-PEER-1** fails.
* **C17** remove the `_observation_mode` term from the gate → **T-GATE-1** fails.
* **C18** remove the disable-edge restore → **T-GATE-2** fails.
* **C19** delete the restore pass → **T-RESTORE-1** fails.
* **C20** restore the amps blob without the 10 h age gate → **T-RESTORE-3** fails.
* **C21** add an age gate to the `_touched` blob → **T-BOOT-1** fails.
* **C22** delete the boot reconciliation → **T-BOOT-1** fails.
* **C23** persist every tick instead of on mutation → **T-PERSIST-1** fails.
* **C24** delete the self-prune block at step 0 → **T-PRUNE-1** fails.
* **C25** remove the supersession cancel → **T-VERIFY-1** fails.
* **C26** remove `cancel_all()` from teardown → **T-VERIFY-2** fails.
* **C27** construct `SolarFollowController` at `energy.py:293` → **T-WIRE-1** fails (both grid
  entities None).
* **C28** drop the unit guard in the grid read → **T-UNIT-1** fails.
* **C29** warn immediately at t=0 instead of at the grace → **T-BLIND-1** fails.
* **C30** remove the deadband → **T-DEADBAND-1** fails.

Every drill must bite. A site whose bypass leaves the suite green is untested.

---

## 11. Acceptance criteria

* **Verify:** `a_current=48`, one drawing bay, one parked, 7 kW surplus → 23 A and 6 A, and the
  INV-SF-4 inequality holds.
* **Verify:** 18.2 kW surplus → 48 A, not 75.
* **Verify:** a peer-held bay receives no write and no capture, including across the write await.
* **Verify:** observation mode and the master switch each produce zero writes, and disabling
  un-throttles once.
* **Verify:** a bay leaving the session returns to `_original_amps` next tick.
* **Test:** all of §9, each anchored by a drill in §10.
* **Live:** the **`number.*_current_limit` entity's own recorder history** — not URA's
  attributes — shows ≥4 distinct values within one session, bracketing the surplus trace.
  URA's own attributes cannot confirm URA is working; `solar_follow_original_amps` is populated
  by capture even if every write is suppressed, so it reads PASS with the modulator inert.
* **Live:** on a peak-production day the commanded value never exceeds 48.
* **Live:** after a >10 h restart with a previously throttled bay, its limit reads 48 A.

---

## 12. Tier and review

**Tier 3.** Cost-and-safety impacting, threads a value through a peer-precedence system, and
writes a physical current limit. Four framing-disjoint code reviews: A local correctness ·
B integration and lifecycle · C test authority via real per-site source mutation (§10) ·
D adversarial completeness, diff-blind, over the whole invariant surface including pre-existing
code. Orchestrator verifies §10 personally before ship. Operator checkpoint BEFORE deploy.

## 13. Cycle-close

* [ ] All §10 drills bite; tree clean after each.
* [ ] Suite name-diff vs baseline: zero regressions.
* [ ] `determine_excess_solar_actions` and `determine_battery_drain_actions` byte-identical
      (grep-verified) — this cycle touches neither.
* [ ] `energy_pool_owners.py` unchanged; owner-registry golden still passes.
* [ ] README carries the post-restart `Validated <date>` table.
* [ ] Post-ship audit: the `fill_priority_soc` DELETE-CANDIDATE gate and the `grid_cap` vs
      v4.5.0 D4 overlap question.
