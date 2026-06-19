# PLANNING — Expose the arbitrage grid-import guard in config flow + default it OFF

**Tier:** Tier 2-DB (battery/arbitrage CHARGE path — cost-AND-safety; small but regression-prone).
Three framing-disjoint reviews + live validation + README write-back.

## Problem / intent

The arbitrage grid-import guard (`energy_arbitrage_grid_import_guard_kw`, default **12 kW**)
is **hidden** — it has no config-flow surface and no enable toggle, so it is *always on* at
the 12 kW default. It aborts the battery's arbitrage grid-charge chunk whenever net import
crosses 12 kW. On a high-AC summer afternoon, AC + a 20 kW battery charge blows past 12 kW,
so the guard **aborts the entire pre-charge** — leaving the battery under-filled going into
peak (observed live 2026-06-19: `arbitrage_guard_aborted_kw: 13.537` at 10:34, battery at
26% at 15:35 with peak imminent).

Operator facts that make the guard obsolete:
1. The Enphase battery **firmware now auto-curtails its own draw based on breaker size**
   (additive-load aware) — so the software guard is **redundant for breaker safety**.
2. The operator's *visible* ceiling (the EV Grid Import Cap) is set to **20 kW**, but the
   battery silently obeys the hidden **12 kW** guard — "you set 20, the battery obeys 12."
3. "Hidden is unacceptable."

**Operator decision (this cycle): Option 2 — "Put it in config flow and turn off."**
Expose the existing knob with an enable toggle; default the toggle OFF (guard inert). Do
NOT delete the guard code (the more-invasive delete was the rejected Option 1). The guard
remains as a dormant opt-in for installs that genuinely want a software import throttle
below the hardware auto-limit.

**Explicitly OUT OF SCOPE (deferred, avoid scope creep — operator 2026-06-19):**
- Deleting the guard code (Option 1).
- Touching the EV Grid Import Cap or the load-shedding cascade — confirmed to be *distinct*
  mechanisms (admission-control vs whole-house graduated shed); kept as-is.
- The "universal / generalized demand-shed signal" — a separate future design.
- Refreshing the stale master design doc (`ENERGY_COORDINATOR_DESIGN_v2.3.md`, frozen at
  v3.6.0) — parked.

## Falsifiable invariant (Tier-level — state up front, D's job to break)

> When the guard is **DISABLED** (the new default), **no** battery grid-charge tick is ever
> aborted, throttled, or chunk-locked for a grid-import threshold — the *only* limit on
> battery grid-charge is the Enphase hardware curtailment. When **ENABLED**, behavior is
> byte-identical to the pre-change always-on guard at the configured kW.

## Institutional context verified

### Greps run + results (REUSED / NEW)
- **NEW** `CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED` (default `False`) — no enable
  flag exists for the guard today; it is unconditionally always-on. Grep of `energy_const.py`
  confirms only `CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW` (`:516`) + the bare default
  `DEFAULT_ARBITRAGE_GRID_IMPORT_GUARD_KW = 12.0` (`:515`). Justified NEW.
- **REUSED** the enable-toggle + kW-slider pattern from the EV Grid Import Cap:
  `CONF_ENERGY_GRID_IMPORT_CAP_ENABLED` (default `False`) + `..._KW`, rendered as
  `BooleanSelector()` + `NumberSelector(min/max/step, unit "kW")` at `config_flow.py:3284-3286`
  (key list) and `:3893-3902` (schema). strings.json labels at `:886-887` / `:945-946`.
- **REUSED** read-and-pass plumbing: the guard kW is read in `energy.py:191-208` and passed
  to `BatteryStrategy(arbitrage_grid_import_guard_kw=...)` at `:223`; stored at
  `energy_battery.py:235-240`.
- Guard consumption sites (all must be covered by the disable): helper
  `_grid_import_guard_triggered()` `energy_battery.py:1047,1058`; inline comparisons
  `snap[0] > self._arbitrage_grid_import_guard_kw` at `:1411`, `:2532`, `:2643`; the
  2-trip chunk-lock `ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK = 2` (`energy_const.py:526`).
- Sensor attr surface: `arbitrage_grid_import_guard_kw` at `energy_battery.py:3350`, plus
  `arbitrage_guard_aborted_at` / `arbitrage_guard_aborted_kw`.

### Design docs / prior art
- User manual `docs/user-manual/ENERGY_COORDINATOR.md` (current to v5.4.1) — the living EC
  doc; documents the guard as "grid-import guard during CHARGE" (lines 204, 210). Master
  `docs/Coordinator/ENERGY_COORDINATOR_DESIGN_v2.3.md` is stale (v3.6.0) — not updated this
  cycle (parked).
- Memory: `project_inclement_arbitrage_wait_floor_gap.md`, `project_battery_soc_envoy_not_span.md`.

## Design (the chokepoint-safe disable)

When the guard is disabled, set the **effective threshold to `float('inf')`** in one place
(at config-read / `BatteryStrategy.__init__`), rather than editing each comparison site.
Then *every* consumer — the helper AND the three inline `snap[0] > guard` checks AND the
chunk-lock — naturally no-ops (`x > inf` is always `False`). This avoids the
"computed-but-not-consumed / one missed site" failure (Bug Class #53) that bit v5.5.3: there
is a **single** load-bearing assignment, not N per-site guards to keep in sync.

## Deliverables

### D1 — Enable toggle (NEW const, default OFF)
Add `CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED` (default `False`) to `energy_const.py`.
Read it in `energy.py` alongside the existing kW read; pass `enabled` into `BatteryStrategy`.
In `BatteryStrategy`, when `not enabled`, set `self._arbitrage_grid_import_guard_kw = inf`.

#### Acceptance criteria
- **Test:** with guard disabled, `_grid_import_guard_triggered()` returns `False` even at a
  snapshot of 100 kW import; the chunk-lock counter never increments.
- **Test:** with guard enabled at 12, behavior is identical to pre-change (trips at >12,
  locks after 2 consecutive trips).
- **Verify:** default install (no options set) → guard disabled → no abort.

### D2 — Config-flow surface (mirror grid_import_cap) — shape #1 + default (c)
Add a `BooleanSelector()` (enable, default OFF) + a `NumberSelector(min=6, max=20, step=0.5,
unit "kW")` with **NO default** (field renders blank) to the energy options step, adjacent to
the EV Grid Import Cap block. **Operator design decision 2026-06-19: "1 + c" — required when
enabled, no silent default.** Cross-field validation: if the toggle is ON and the kW field is
blank, the step re-shows the form with an error ("enter your DER breaker's continuous rating").
A guessed 12 (or any auto-default) is explicitly rejected — the threshold is install-specific
and must be entered deliberately the moment the guard goes live, so it can never silently
re-impose a limit that circumvents the operator's intent.

Add strings.json label + description ("Optional software cap on battery grid-charge import.
Default OFF — the battery hardware already curtails to the breaker. Only enable to throttle
*below* the hardware limit; when enabled you must enter your DER breaker's continuous rating
(amps × 240 × 0.8 ÷ 1000).").

#### Acceptance criteria
- **Verify:** the toggle + number render in Energy options; default toggle = OFF, kW field BLANK
  (no pre-filled 12).
- **Test:** enabling the toggle with a blank kW field is REJECTED (form re-shown with error);
  enabling with kw=15 persists and re-reads on reload.
- **Test:** runtime defence — `enabled=True` with a missing/None kw is treated as DISABLED
  (effective threshold `inf`), never as a silent finite default.
- **Live:** the two fields are visible; the kW field is empty on a default (guard-off) install.

### D3 — Sensor-attr honesty
`battery_strategy` attrs: add `arbitrage_grid_import_guard_enabled` (bool). When disabled,
report `arbitrage_grid_import_guard_kw` as `null` (not `inf`/`12`) so the sensor never
implies a 12 kW limit that isn't enforced.

#### Acceptance criteria
- **Sensor:** `sensor.ura_energy_coordinator_battery_strategy` attr
  `arbitrage_grid_import_guard_enabled: false` and `arbitrage_grid_import_guard_kw: null`
  on a default install.
- **Live:** after deploy, those two attrs reflect the disabled default.

## Tier 2-DB review framings (three, parallel, disjoint)
- **A — correctness:** the `inf` sentinel genuinely covers all 4 consumption sites; the
  enabled path is byte-identical to the old always-on guard; attr honesty.
- **B — state-machine integrity:** chunk-lock never engages when disabled; no regression to
  attain / HOLD / CHARGE handoff; restart-resilience (disabled survives reload; enabled
  restores kw).
- **C — config round-trip + test authority:** options-flow + RestoreEntity round-trip;
  **per-site mutation** — neuter the disable at each of the 4 sites in turn, confirm a
  specific test fails, restore. A site whose bypass leaves the suite green is untested.

## Live validation (Review D)
Post-restart, guard at the disabled default: observe (or, if no natural grid-charge,
in-suite-prove) that a >12 kW battery grid-charge tick is **not** aborted —
`arbitrage_guard_aborted_at` does not advance — and the attrs show
`arbitrage_grid_import_guard_enabled: false`. Write observed results back into the README.

## Plan-completion tracking
- Option 1 (delete the guard) — NOT done; deliberately deferred to keep churn low.
- EV Grid Import Cap / load-shed cascade — untouched by design.
- Universal demand-shed signal + master design-doc refresh — parked as separate future work.
