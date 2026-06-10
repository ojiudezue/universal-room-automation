# URA v5.3.1 — Energy Unit Normalization + 4-Tier Attribution Fix

**Tier:** Operator-elevated Tier 2-DB (3 framing-disjoint reviews + 4th-pass spot-check + live validation)
**Plan:** `docs/planning/PLANNING_energy_unit_normalization_and_attribution.md`
**Review ledger:** `docs/reviews/code-review/energy_unit_normalization_and_attribution.md`
**Trigger:** 2026-06-09 live audit — zone/room energy poisoning (Bug Class #30 recurrence on the energy device class).

## What was broken (live, v5.3.0)

| Sensor | Observed (poisoned) |
|---|---|
| `zone master_suite energy_today` | 1,671 kWh "today" at ~1 kW draw (+~28 kWh/min) — Wh source summed as kWh (1000×) |
| `zone entertainment energy_today` | 960.8 kWh at 57 W (1000×) |
| `energy_coverage_delta` | −839,746,910 kWh; `zones_total` = 839.7M (raw lifetime counters summed into a today-scope equation) |
| `attribution_coverage_pct` | 24,558,907,924% — yet rated "Excellent" |
| `cost_per_occupied_hour` | $48.03/h |
| `zone upstairs energy_today` | stuck 0.0 all day despite 103 W live power (dead/renamed energy sensor entity_ids, silent) |

## What shipped

1. **D1 — Unit normalization.** New shared helper `energy_state_to_kwh` (`domain_coordinators/_units.py`) handles Wh/kWh/MWh at the room energy-tracking read (`coordinator.py`) and all aggregation energy reads. Version-gated one-shot `room_energy_baselines` reset (sentinel row `__schema_version__`, atomic single-write migration, race-free, cleanup-proof). Sanity guard now two-sided; any negative delta re-anchors.
2. **D2 — 4-tier today-scope semantics.** Coverage-delta zone / house-device / whole-house tiers now today-scoped via in-memory midnight-anchored baselines (zero new DB writes), per-sensor cumulative-vs-today classification (>1000 kWh heuristic, midnight re-eval, immediate flip), mixed-scope tiers skipped with `scope_mismatch_warning`. `WholeHouseEnergySensor` gets the same treatment.
3. **D3 — Rating guard.** `coverage_rating` returns new **"Anomalous"** for delta_percent < −2% or > 100% (with ε-band for small negatives); post-restart re-anchor window rates **"Incomplete"** instead, with `post_restart_window` attribute.
4. **D4 — Dead-sensor observability.** All-energy-sensors-dead rooms now report `STATE_ENERGY_TODAY = None` (not 0.0), log a rate-limited WARNING, and expose `energy_sensors_dead: true` on the room Energy Today sensor.
5. Monotonic day-reset guards switched from magnitude (`< 0.1`) to local-date-change acceptance at all 5 sites.

## Known accepted gaps (documented in review ledger)

- HA recorder long-term statistics keep the historical 1000× datapoints (cosmetic; ages out per retention). Accepted for single-user install.
- Same-day counter reset holds the prior value until midnight (C-H1 trade-off).
- Upstairs/outside zone recovery requires the SPAN circuit entity_id remap — **operator config work** (hygiene-bucket memo), not code. D4 makes the failure visible meanwhile.
- Uom-less energy sensors are assumed kWh (A-L1).

## Pre-deploy snapshot (2026-06-09, v5.3.0 live)

| Sensor | Pre-deploy (poisoned) | Expected post-fix |
|---|---|---|
| `sensor.master_suite_energy_today` (zone) | ~1,671 kWh | < 50 kWh, plausible vs draw |
| `sensor.entertainment_energy_today` (zone) | 960.8 kWh | < 10 kWh |
| `...energy_coverage_delta` state | −839,746,910 kWh | sane kWh, plausibly positive |
| `...attribution_coverage_pct` | 24,558,907,924% | 0–100% |
| `...coverage_rating` | "Excellent" (false) | bounded set incl. Anomalous/Incomplete, no false Excellent |
| `...rooms_total` attr | 2,249.78 kWh | sane today sum |
| `...zones_total` attr | 839.7M kWh | sane today sum |
| `...cost_per_occupied_hour` | $48.03/h | < $5/h typical |
| upstairs zone energy | 0.0 stuck, silent | 0/None **plus** `energy_sensors_dead: true` on ≥1 room |

## Live Validation (Review D) — Validated 2026-06-10 ~00:45 UTC (~6 min post-restart)

| Criterion | Result | Observed evidence |
|---|---|---|
| Integration loaded on v5.3.1 | PASS | 40 URA config entries all `loaded`, zero setup errors |
| Zone master_suite energy sane | PASS | `sensor.zone_master_suite_energy_today` = 0.07 kWh (was 1,671) — post-boot re-accrual, correct |
| Zone entertainment energy sane | PASS | `sensor.zone_entertainment_energy_today` = 0.0 kWh (was 960.8) |
| Coverage delta sane | PASS | state −0.0 kWh; `rooms_total` 0.004; `post_restart_window: true`; `whole_house_scope: "today_derived"`; `coverage_rating: "No data"` — no false "Excellent" |
| Cost per occupied hour | PASS | $0.0008/h (was $48.03); Study A $0.0003/h over 7.87 occupied hours |
| Room cost sanity | PASS | Study A cost_today $0.0025 (was $45.99); Master Bedroom 0.0017 kWh, `energy_sensors_dead: false` |
| Dead-sensor observability (D4) | PASS | `sensor.jaya_bedroom_bedroom_4_energy_today` = `unknown`, `energy_sensors_dead: true`; WARNING names the unavailable entity; multiple upstairs/closet rooms reporting None correctly |
| Zero new URA ERRORs | PASS | system_log ERROR + URA filter: 0 entries; no KeyError/TypeError/`did not process within 35s`/`held connection` |
| Write-queue health | PASS | No saturation lines in the 00:39 restart window (prior 19:38 boot showed only the expected bounded boot-burst peak, max 26 items / 0.082s) |
| Migration evidence | PARTIAL (in-suite) | Sentinel/reset INFO lines hidden by WARNING-level file logger (known logger config); functional signature visible as implausible-delta re-anchor WARNINGs on both boots; migration one-shot/idempotent/cleanup-proof proven by behavioral tests against the real DAO |

**Boot-only transients seen and dismissed:** websocket clients kicked at 4096
pending messages during the first ~4 min post-restart (boot event storm —
chattiest sources were ESPHome mmWave `move_energy` sensors + UniFi
device_tracker churn, NOT URA; last kick 00:43:00 UTC, none after);
non-URA Dreo "Event loop is closed" callbacks at shutdown of the prior boot.

**Optimizer:** `optimizer_status` = initializing, mode = shadow (L1) at T+6min —
expected; no write-flood.

**Operator follow-up (not blocking):** SPAN circuit entity_id remap for the
upstairs-zone rooms (hygiene bucket) — until then those rooms intentionally
report `unknown` + `energy_sensors_dead: true` instead of silent 0.0.
