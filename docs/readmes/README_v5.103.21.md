# v5.103.21: cars wait for the battery after a grid charge, and the battery reason says what is happening

**Card:** `EV-ARBITRAGE-RELEASE-IGNORES-FILL-PRIORITY-1` (Tier 1)

## Problem

**1. A car could be switched on for a moment and then off again.**
On a summer morning (off-peak, daylight) URA holds the cars until the home battery reaches the fill target (80%). This is called fill priority. While URA grid-charges the battery ("attain"), a second rule, the breaker hold, also keeps the cars off. When grid charging ends, the breaker hold lets go and turns the cars back on. It did not check fill priority. If the battery was still below 80% at that point, fill priority turned the car off again a moment later. Fill priority only takes charge of cars that are already on, so it never took charge of a car the breaker hold had switched off.

The 2026-09-28 12:51 event was not this bug. The battery was at 81%, so turning the car on was correct (manual §5.5a).

**2. The battery reason text made a false claim.**
From 11:01 to 12:46 CDT on 2026-09-28, `sensor.ura_energy_coordinator_battery_strategy` showed reasons like "projected SOC 129% < target 80%". The projection ran from 147% to 191% across that window. The claim "129 < 80" is false.

**Verdict: the text was wrong, but the decision was not.** The evidence:
- The only place that compares the projection with the target is the entry check (`_should_attain_peak_buffer`, `energy_battery.py` `if projected < self._peak_buffer_target`). It fired at about 11:01 with a projection of 75% against a target of 80%, which was a correct comparison.
- After entry, the charge is locked in and is not compared again. It ends only when the SOC reaches the target, at a TOU handoff, on a guard trip, or on operator drift. This is by design (A-CRIT-1): once the charge starts, the measured rate includes URA's own grid charging. At 12:20 the rate was +39.7 %/h at 15.9 kW battery power. The projection therefore overshoots: 65 + 103/60 × 39.7 + 26.2 solar ≈ 157%.
- The locked-in branch still computed that projection and printed it in the old sentence, "< target". The value is deliberately not clamped: attain uses `raw_soc_pct`, and the clamp in `energy_projector.py:66` applies only to the rung display.
- The SOC rose 16% → 81% and the charge stopped at 12:46:57 on "SOC 81% reached target 80%". No wrong number fed any decision.

## Fix

- `energy_pool.py`, arbitrage release (`determine_arbitrage_actions`, release loop):
  - Fill priority is now one of the rules that can keep a car paused, the same way ensure-on already respects it through `_stronger_peer_holds`.
  - If a car is off, fill priority wants the battery filled first, and force-charge is not active, the release hands the car to fill priority instead of turning it on. It records the same pause details fill priority uses, so a manual turn-on is still honoured.
  - Fill priority's own resume turns the car on at 80%.
- `energy_pool.py`, `determine_fill_priority_actions`: saves a new value, `_fill_priority_would_hold` ("wants a hold": not inert, SOC below the target, forecast healthy, no force-charge). It is reset when fill priority goes inert (night, peak, or mid-peak after peak) and in `release_all_fill_priority` (toggle off), so the value cannot go stale. The release reads the value saved on the previous tick, because the release runs before fill priority within a tick.
- `energy_battery.py` `_get_attainability_decision`: the "projected X% < target" wording appears only when it is true and the charge is not locked in. While the charge is locked in, the reason now reads, for example: **"Charging the battery from the grid to 80% before 14:00 (now 72%)"**. The locked-in call passes `latched=True`. The `attain_projected_soc_at_boundary` attribute keeps the raw value, unchanged.
- `ENERGY_COORDINATOR_MANUAL.md` §5.5a: no longer says fill priority is "the ONLY owner". The breaker hold is a second owner while grid charging, and the manual now describes the handoff.

## Tests

- New `quality/tests/test_ev_arbitrage_release_fill_priority.py` covers:
  - Grid charging ends at SOC 75 with a target of 80: no turn-on, and the car is handed to fill priority.
  - On the next tick ensure-on does not turn the car on, and fill priority turns it on at 80.
  - The car is still turned on when SOC ≥ 80, at night (inert), and with the toggle off.
  - Existing fill-priority membership is respected.
  - A manual turn-on after the handoff is honoured.
- New `quality/tests/test_attain_latched_reason_plain.py`:
  - While locked in at +40 %/h, the reason is the plain sentence and never contains a false "<".
  - Defensive branch in the reason builder.
  - The entry wording is kept when it is true.
  - A wire-in check confirms the locked-in call passes `latched=True`.
- Updated tests:
  - `test_r7_attain_raw_consumption.py`: the raw-projection check now reads the published mirror, not the reason text.
  - `test_r7_1_attain_reason_mirrors_decision.py`: the fixture is now a real entry. The old fixture projected 139% against 90%, the entry check refused it, and the test was asserting on the false sentence.
- Mutation drills: M1–M8. Each disabled line turned a named test red, and each was restored with `git status` clean.

## Live validation (prospective)

- **L1:** While attain is grid-charging, `sensor.ura_energy_coordinator_battery_strategy` has a `reason` starting "Charging the battery from the grid to 80% before 14:00 (now N%)". The phrase "projected SOC" appears only on the entry tick, and only with X < target.
- **L2:** If grid charging ends with SOC < 80 in daylight off-peak:
  - No `switch.turn_on` for a garage EVSE in the activity log at the release.
  - The log shows "arbitrage release (breaker): battery still below fill target — handed to fill-priority".
  - `paused_by_fill_priority` on the EV status sensor lists the charger.
  - The charger turns on when SOC reaches 80, logged as "EV fill-priority: resuming … (SOC reached fill target)".
- **L3:** If grid charging ends with SOC ≥ 80 (the 09-28 shape), the car is turned on as before, logged as "resumed (arbitrage released…)".
- **Discriminator:** a turn-on and then a turn-off within one tick for the same charger at the end of a grid charge would show the fix is not working.

## Rollback
Revert the merge. No schema, config or entity changes.
