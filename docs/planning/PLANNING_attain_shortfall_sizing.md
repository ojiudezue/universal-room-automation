# PLANNING — ATTAIN precise ramp via CFG on/off modulation (target-generic)

**SUPERSEDES the shortfall-sizing/schedule-limit approach.** Read-only verification (2026-09-09) found
the Enphase charge-to-limit-separate-from-reserve is NOT supported on this site (charge_from_grid_schedule
unsupported; only force-CFG on/off, no target-SoC limit; URA actuates the LOCAL Envoy which has no limit
concept). So sizing via schedule_limit is dead here. Operator-chosen approach instead:

## Approach: modulate CFG on/off (reserve untouched)
Keep attain emitting reserve = `peak_buffer_target` (the DISCHARGE FLOOR stays at target -> no morning
drain, P1 safe). SOC still climbs to target via solar even with grid off (self-consumption charging is
always allowed) so the SOC-keyed latch/exit is unchanged (P2 safe). The ONLY new behavior: turn
`charge_from_grid` OFF once forecasted solar can finish the ramp to `peak_buffer_target` by the boundary,
and back ON if solar disappoints. Uses only the CFG switch URA already controls (local Envoy).

**TARGET-GENERIC (operator 2026-09-09):** `peak_buffer_target` is a CONFIG VARIABLE, not the literal 80.
The whole design must work identically at 60%, 80%, or any value / any pack size (e.g. 160 kWh @ 60%).
Never hard-code 80; everything reads `self._peak_buffer_target`.

## Target latched per-day (operator 2026-09-09)
`peak_buffer_target` is SNAPSHOTTED when the morning attain cycle starts and held IMMUTABLE for that day.
The CFG-modulation reads the snapshot, NOT the live config — a mid-day config change does NOT adjust the
in-progress ramp (no intra-day target seam). A changed target takes effect the NEXT morning. This is the
temporal 'treat the target as a fact' rule and removes the mid-ramp target-change edge case entirely.

## CFG-off condition (target-generic)
Turn CFG OFF when `credited_solar_before_boundary >= (peak_buffer_target - current_soc)` with a safety
margin; else CFG ON. Self-correcting each tick as the window shrinks (credited_solar falls -> CFG back on
in time). The over-credit guard (plan-review P3) is rate-feasibility: only stay OFF if solar can still
reach target within `[now, boundary - ATTAIN_PEAK_HANDOFF_LEAD_MIN]` at the observed charge rate.

## Falsifiable invariant
reserve_level emitted by attain is ALWAYS `peak_buffer_target` (never lowered) on every CHARGE/HOLD tick;
CFG is only turned OFF when solar can provably reach `peak_buffer_target` by the handoff at the observed
rate; a solar disappointment re-enables CFG with enough time to recover. allow_discharge/WAIT paths
byte-identical.

---

## (superseded) shortfall-sizing notes below — retained for history

# PLANNING — ATTAIN shortfall-sizing (size grid charge to forecasted shortfall, not flat target)

Card: `ATTAIN-SOLAR-AGGRESSION-INVESTIGATE-1`. Tier: 2-DB minimum, likely **Tier-3** (energy strategy,
threads reserve through CHARGE emission sites). **Plan-review required before build** (this doc).

## Problem (measured + code-diagnosed)
14-day probe: import 12.3× export (no export wash); solar-recoverable waste = 29–56% of morning
grid-charge = **~$140–270/yr** (off-peak $0.086, so small). ROOT (code): the attain path
grid-charges to a **flat `peak_buffer_target` (80%)**; the solar forecast is used ONLY as an on/off
gate, never to SIZE the charge — so it pulls grid for the full soc→80 span incl. the slice solar
would deliver before the 14:00 boundary. Compounded by a flat `SOLAR_CAPTURE_FACTOR=0.5`
(energy_battery.py:260) halving the forecast in the gate.

## Fix (tweak — all ingredients exist)
On the CHARGE emission branches, replace the flat `peak_buffer_target` reserve target with:
`sized_reserve = clamp(peak_buffer_target - credited_solar_before_boundary, safety_floor, peak_buffer_target)`
using the already-computed `_expected_solar_surplus_pct(now, mins_to_boundary)`. Self-correcting:
as the boundary nears the capturable window shrinks → credited_solar falls → sized_reserve rises
back toward 80%, so a solar disappointment is still covered by grid on later ticks. Keep the GATE's
0.5 pessimism (deciding whether to charge stays conservative); add a SEPARATE, less-pessimistic
**sizing** credit factor for the shortfall calc.

## Falsifiable invariant
On any CHARGE emission, the emitted `reserve_level` (grid target) is NEVER above
`peak_buffer_target - credited_solar_before_boundary` and NEVER below `safety_floor`
(= max(reserve_soc, inclement floor)). The `allow_discharge` / no-op paths are byte-identical.

## Emission sites (HYPOTHESIS from diagnosis — plan-review MUST re-enumerate independently)
- `energy_battery.py:3420-3441` — arbitrage CHARGE (`reserve_level=_floor_reserve(peak_buffer_target,...)`)
- `energy_battery.py:4148-4164` — attain CHARGE (same shape)
- (invariants-campaign Phase 1a found ~17 `reserve_level=` sites — reviewer re-greps to confirm no OTHER charge-to-target site needs the same sizing.)

## Knobs (Numbers-Get-Knobs)
- `SOLAR_CAPTURE_FACTOR=0.5` (existing, gate) — UNCHANGED (gate stays pessimistic).
- NEW `CHARGE_SOLAR_SIZING_FACTOR` (module const, energy_battery.py, review-gated — safety-adjacent;
  sizing too generously risks a missed buffer). Default TBD; optionally set by a 14-day
  Solcast-morning-forecast-vs-actual-captured probe (measure-before-build) before finalizing.
- `safety_floor` clamp: max(reserve_soc, active inclement floor) — reuse `_floor_reserve`.

## Non-goals
No new state machine; no blanket aggression cut (probe: solar couldn't refill on 11/13 days —
blanket restraint forces evening PEAK import at 2.4×, erasing savings). Keep the realized-divergence
detector (v5.3.8) as the safety net. Do NOT lower the gate's 0.5.

## Interactions to protect (for plan review + build)
attain latch integrity (I-5 from the invariants campaign); inclement `_floor_reserve` (must still
raise, never be lowered by sizing); no-flap hysteresis on the reserve; the two-charge-site
consistency; day/TOU boundary; the realized-divergence detector's assumptions.

## Review tier
Tier-3 (4 framing-disjoint per ura-change-control), operator checkpoint before deploy. Use the
`ura-energy-invariants-campaign` discipline (Phase 1 grep enumeration, Phase 4 per-site mutation).
