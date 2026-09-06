# AUDIT — Battery ATTAIN grid-charge vs solar (aggression investigation)

**Date:** 2026-09-06. **Type:** read-only investigation (findings only — NOT built). **Card:** `ATTAIN-SOLAR-AGGRESSION-INVESTIGATE-1`.
**Trigger:** operator side-quest — "is the attain machinery being aggressive and charging from grid even when it could wait for solar?"
**Status of evidence:** agent investigation + orchestrator SPOT-CHECK (code + live recorder confirmed the two model-changing claims). Trustworthy. Economics NOT priced (see Open question).

## Verdict
**DEPENDS — leaning YES, structurally.** The attain path is NOT blind — it credits solar (forecast + observed) before pulling grid and declines when solar suffices. The aggression is three compounding design choices that front-load grid and finish ~1h before the deadline, after which solar is exported unused.

## Mechanism (code, spot-check confirmed)
Two solar-aware machineries in `domain_coordinators/energy_battery.py`:
- **Off-peak arbitrage CHARGE** — `_get_arbitrage_phase` → `_gate_is_open` → the solar-attainability ladder `_classify_attain_rung` (~:2795): rung_0 = today's solar alone attains target → gate CLOSED, no grid; rung_1 = solar + pausing EVs attains → no grid; rung_2 = neither → grid CHARGE. (This "wait for solar" ladder did NOT fire in the observed window — the live episodes were all the ATTAIN path below.)
- **Peak-buffer ATTAIN** (`ARBITRAGE_PHASE_ATTAIN`) — entry predicate `_should_attain_peak_buffer` (~:3978) credits solar at step 5: `projected = soc + (mins/60)*rate + solar_surplus`, `solar_surplus = _expected_solar_surplus_pct(now,mins)` (~:3731); grid-charges only when the solar-informed projected SOC at the boundary < target.

### The three aggression biases (structural, not "ignores solar")
1. **`SOLAR_CAPTURE_FACTOR = 0.5`** (energy_battery.py:260, spot-check confirmed) — only 50% of the Solcast remaining-day forecast is credited to the battery ("fail toward charging"). Systematically under-credits solar → leans grid.
2. **Entry-only latch** — `_should_attain_peak_buffer` is evaluated ONLY on entry (~11:00); once `_attain_active` it is not re-evaluated. A solar ramp AFTER entry cannot release it.
3. **Binary ~20 kW grid + demanding target/deadline** — `peak_buffer_target = 80%` (live) by the summer 14:00 mid_peak boundary; `charge_from_grid` is binary (~20 kW, cannot modulate to "top up only what solar misses"). So once attain commits it slams grid and hits target well before the deadline.
Stale/unavailable Solcast or unknown capacity collapses `solar_surplus` to 0 → grid.

## Live evidence (recorder, 09-04/05/06; ATTAIN fired ~11:00 each day, target 80% by 14:00)
| Day | Time (CDT) | Solar kW | Grid import kW | SOC% | Note |
|---|---|---|---|---|---|
| 09-06 | 11:50 | 5.2 | 20.6 | 47 | projected 79% vs 80% (1% gap) → full 20 kW pull, weak-solar morning |
| 09-06 | 12:50 | 2.7 | 0.7 | 82 | target hit ~70 min early |
| 09-05 | 12:30 | 4.2 | 15.1 | 69 | grid-charging mid-day |
| **09-05** | **13:25–13:32** | **~18.0** | **net −10 to −11 (EXPORT)** | **96** | **ORCHESTRATOR SPOT-CHECK CONFIRMED: battery full, ~18 kW solar EXPORTED unused after grid-charging earlier** |
| 09-04 | 11:30 | 6.6 | 20.3 | 27 | target_day=poor (legit) |
Solcast on these days was excellent (today 93 kWh, tomorrow 100 kWh).

**Spot-check note:** the sensor's `charge_from_grid` attribute read `None` in the recorder; grid-charging confirmed physically via the enpower `charge_from_grid` switch (ON) + 20 kW grid import with SOC climbing ~15%/30min. The 09-05 export-at-96%-SOC was independently re-queried by the orchestrator (correct UTC window) and confirmed.

## Aggression condition (falsifiable)
High-forecast-solar day + low SOC at the ~11:00 attain-entry tick + solar ramping AFTER entry → grid fills the battery early, solar exports later.

## Fix directions (NOT built — measure-gated)
- Re-evaluate attain EACH TICK (not entry-only) so a solar ramp releases it.
- Raise the solar capture credit (`SOLAR_CAPTURE_FACTOR`, module-rung knob) and/or modulate grid to fill only the solar shortfall.
- **GATE: price the peak-import vs solar-export tariff spread + the risk of missing 80% by 14:00 first** (measure-before-build) — is the early grid-charge actually net-negative, or conservative-by-design insurance against missing peak?

## Open question (the missing number)
Not established: whether the early grid-charge is economically net-negative. "Could have waited for solar" is PHYSICALLY true (solar available/exported while/after grid-charging) but the $ impact depends on the tariff spread, which was not priced. Decide bug-vs-conservative-design only after pricing it.

## Change-control note
Any change here is Tier-3 per `.claude/skills/ura-energy-invariants-campaign` (reserve/charge/discharge invariants, framing-disjoint reviews, no aggressive grid change without pricing). Do NOT touch the battery strategy without the tariff-spread number.

## Refs
`energy_battery.py:260` (SOLAR_CAPTURE_FACTOR), `_should_attain_peak_buffer`/`_expected_solar_surplus_pct` (~3731/3978, entry-only latch + solar credit), `_classify_attain_rung` (~2795, rung ladder), `docs/planning/PLANNING_arbitrage_solar_attainability_ladder.md`, live 09-04/05/06 recorder.
