# v5.100.9 — Tier-1 gate-and-knobs (3 clean fixes)

**Batch:** `tier1-gate-and-knobs` · **Tier 1** · shipped 2026-09-11

Three independent, low-blast-radius fixes. No runtime behavior change to the integration
(one const rename, one additive display attribute, one test-only hardening). A fourth fix
(const-stub isolation) was **held** — see below.

## Shipped

### HVAC-TICK-LITERAL — name the HVAC decision-cycle quantum
The HVAC decision cycle was a hardcoded inline `timedelta(minutes=5)` in the
`async_track_time_interval` install site — the quantum that makes `zone_entry_dwell=3`
structurally sub-tick and `vacancy_grace_constrained=5` the minimum expressible grace.
Promoted to a named module constant `HVAC_DECISION_TICK` in `hvac_const.py` (rung-1: change
requires review — it bounds the cloud-API call rate). **Same value (5 min) — zero behavior
change.** Numbers-Get-Knobs compliance.

### ARBITRAGE-D2CLASS — self-describing `d2_offset` attribute
The battery-strategy sensor's `d2_class` attribute means "D+1-of-target" (at offset 0 it is
*tomorrow's* class, not calendar D+2), which a future tracer could misread. Added a sibling
`d2_offset` attribute (= `_target_day_offset + 1`) to the same `get_status` dict so the class
is self-describing. **Purely additive display attribute — no consumer, no decision-path change.**

### TEST-SOURCE-MUTATION-KILL — SIGKILL-safe mutation test
`test_owner_registry_mutation_matrix.py` wrote **production source** with only a `finally`
restore; the pytest concurrency guard manufactures hard kills (SIGKILL), which skip `finally`
and leave the repo mutated on disk — poisoning every subsequent baseline. Rewritten to mutate a
**temp copy** of the package tree; the real source is never opened for write (md5-invariant
asserted post-run). Test-only.

## Held (not in this release)

### PYTEST-CONST-STUB-ISOLATION — held pending suite order-pollution fix
The const-stub isolation fix is correct and makes the full test suite **collect** for the first
time (it was aborting on cross-test `sys.modules` const poisoning). But enabling collection
**exposed 87 pre-existing order-dependent pollution failures** across 7 test files
(`test_v47x_weather_manager` ×14, `test_v4_7_18_dpm_drift_guard` ×4, and others) — **all pass in
isolation**; they are latent debt that the collection-abort had masked, not regressions. Shipping
the fix would turn the full-suite gate from "abort" to "87 red," so it is held and ships with the
order-pollution / test-strategy re-architecture (`SUITE-ORDER-POLLUTION-1` / `TEST-STRATEGY-REARCH-1`).

## Validation

- **Cycle tests:** `test_hvac_decision_tick_const` (2), `test_arbitrage_gate_d2_offbyone` (4,
  incl. `d2_offset == 1` at offset 0), `test_owner_registry_mutation_matrix` (8, md5-invariant) —
  **14 passed** with conftest at its pre-cycle baseline.
- **Gate:** no conflict markers; `py_compile` clean on `hvac.py`, `hvac_const.py`,
  `energy_battery.py`.
- **Full-suite green is not the gate** for this cycle — the suite has never run green in-process
  (pre-existing order-pollution, now measured at 87 failures). The 3 code fixes introduce no new
  isolation failures (each passes in isolation; no runtime behavior change).

### Validated 2026-09-11 (post-restart, HA core-2026.9.1)

| Criterion | Result | Observed evidence |
|---|---|---|
| `d2_offset` attribute present alongside `d2_class` | **PASS** | `sensor.ura_energy_coordinator_battery_strategy` → `forecast_outlook: {d1_class: excellent, d2_class: excellent, **d2_offset: 2**, d2_kwh: 125.14}`. `d2_offset` = `_target_day_offset(1) + 1` = 2, with `target_day_source: solcast_tomorrow`. The additive attribute lands in the same `forecast_outlook` sub-dict as designed. |
| Integration loads / house tier live | **PASS** | `sensor.ura_presence_coordinator_presence_house_state` = `arriving` (available, presence coordinator computing). |
| `HVAC_DECISION_TICK` const in effect | **PASS (in-suite; no observable live change)** | Pure const extraction, same 5-min value — no runtime cadence change to observe. `test_hvac_decision_tick_const` asserts the named symbol reaches the `async_track_time_interval` call site. |

Boot transient seen and dismissed: the battery-strategy sensor's top-level `state` was `unknown`
("Envoy unavailable — holding") during warmup while its full attribute surface (incl. `d2_offset`)
was already populated — expected Envoy-warmup behavior, not related to this cycle.

The 87-failure suite order-pollution finding (which held Fix 2) is tracked under
`SUITE-ORDER-POLLUTION-1` / `TEST-STRATEGY-REARCH-1`.
