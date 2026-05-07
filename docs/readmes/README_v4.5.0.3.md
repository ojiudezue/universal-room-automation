# v4.5.0.3 — Default guard threshold sized for 60A breaker

**Date:** 2026-05-07
**Type:** Tier 1 hotfix (1 default change + 2 regression tests)
**Predecessor:** v4.5.0.2

## Summary

Lowers `DEFAULT_ARBITRAGE_GRID_IMPORT_GUARD_KW` from 20 → 12 kW. Sized for the 60A DER breaker (BR260) on the IQ System Controller 3/3G — Enphase's smaller breaker option, common on residential IQ Battery 5P installs.

## Math

NEC 80% continuous-load derating on a 60A × 240V branch:

```
60 A × 240 V × 0.8 = 11.52 kW  →  rounded up to 12 kW
```

For other DER breaker sizes:

| Breaker | Continuous (240V × 0.8) | Recommended guard |
|---|---|---|
| 60A (BR260) | 11.52 kW | **12 kW** ← v4.5.0.3 default |
| 80A (BR280) | 15.36 kW | 15 kW |
| 100A | 19.20 kW | 19 kW |
| 125A | 24.00 kW | 24 kW |
| 150A | 28.80 kW | 28 kW |

Users with 80A+ breakers should override via `entry.options[energy_arbitrage_grid_import_guard_kw]` until v4.5.1 exposes this in the config-flow form.

## Why the v4.5.0.2 default of 20 kW was wrong

The plan's "solo battery 20 kW (~83A) is well within main breaker capacity" assumption was based on hypothetical hardware, not the user's actual install. Enphase's own DER breaker options for the System Controller 3G top out at 80A — meaning even the LARGEST Enphase-supported DER breaker (19.2 kW continuous) is below the 20 kW default. **Any user on Enphase-recommended breakers would have had a default that doesn't protect them.**

12 kW is the safest default that still leaves room for arbitrage to actually do useful work on the smallest standard breaker (60A).

## Caveat: tick-frequency limitation persists

The guard fires at decision-cycle boundaries (every 5 min). A 30 kW ramp completes in seconds — faster than the next tick. The 12 kW threshold makes the guard **more likely** to catch a slow ramp on its next check, but does NOT guarantee preventing a fast trip in the gap between ticks.

The real fix remains barneyonline rate control (v4.5.1), which caps actual draw continuously. The guard is a software safety rail, not a substitute for hardware-rate cap.

## What changed

- `domain_coordinators/energy_const.py` — `DEFAULT_ARBITRAGE_GRID_IMPORT_GUARD_KW: Final = 12.0` (was 20.0); docstring updated with sizing rationale
- `quality/tests/test_energy_battery.py` — 2 new tests:
  - `test_default_guard_threshold_is_60A_breaker_sized` — asserts constant value
  - `test_charge_aborts_at_default_threshold_with_typical_8stack_load` — end-to-end exercise with 15 kW grid import → guard fires
- Test harness default updated to 12.0 to match constant
- This README

## Tier 1 Review

| Severity | Finding | Resolution |
|---|---|---|
| (none CRITICAL) | — | — |
| (none HIGH) | — | — |
| (none MEDIUM) | — | — |
| LOW | Existing tests with `grid_import_guard_kw=20.0` continue to test the explicit-override path; not regression | ✅ kept as-is |
| LOW | Users on 100A+ breakers will now see the guard fire at 12 kW (lower than they need) — they should override | Document in this README + memory |

**Verdict: READY TO DEPLOY.**

## Tests

- 181 passing (+2 from v4.5.0.2)
- 0 new regressions

## Live validation

After HA restart with v4.5.0.3:

1. `sensor.ura_energy_coordinator_battery_strategy` attribute `arbitrage_grid_import_guard_kw: 12.0` (was 20.0)
2. With Grid Arbitrage re-enabled and a poor-forecast day: if grid import ramps past 12 kW during CHARGE on any 5-min tick, log shows abort warning and chunk_completed=True

## Deploy notes

- One-line config change + tests; no behavior change for the strategy machinery itself
- HACS download required after deploy.sh per memory `feedback_verify_hacs_install.md`
- **User pre-action: confirm the new default matches your DER breaker rating.** If you have an 80A breaker, override to 15 kW before re-enabling Grid Arbitrage. If 100A+, override to higher. The v4.5.0.2 README's table covers all cases.

## Next

- **v4.5.1** — barneyonline charge-rate control + config-flow restructure (now blocked on barneyonline integration verification)
- **v4.5.2** — Test baseline cleanup
- **v4.6.0** — Routine Awareness
