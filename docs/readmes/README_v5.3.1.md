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

## Live Validation (Review D) — prospective criteria

- [ ] Each snapshot row moves from "poisoned" to "expected post-fix" within one update cycle of restart (note: in-memory tiers re-anchor at boot → today values undercount until next midnight; `post_restart_window` attribute should read `true` if boot >00:05).
- [ ] Zero new URA ERRORs in HA log between restart and validation cutoff.
- [ ] `room_energy_baselines` contains the `__schema_version__` sentinel row with value 2; baselines repopulated for active rooms.
- [ ] Room cost_today values sane (no $45.99-style rooms).
- [ ] `energy_sensors_dead: true` visible on at least one upstairs-zone room (until SPAN remap).
- [ ] No `did not process within 35s` / write-queue saturation lines (migration is one bounded write).

*This section will be replaced with the observed-results table after Review D per the README write-back rule.*
