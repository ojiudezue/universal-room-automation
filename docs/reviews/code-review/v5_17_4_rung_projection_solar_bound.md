# Review record — v5.17.4: rung projection solar-horizon bound + display clamp

**Commit:** b3518944. Baseline tag `pre-review-v5.17.4`. Tier 2, framings A+B (ura-reviewer-std). Both **SHIP**.
**Root cause found during build:** the 836% artifact was a latent SHAPE bug — rung projections computed soc + (rate + solar_surplus_total) × hours (surplus, a %SOC total, multiplied by hours), systematically over-trusting solar in daytime classification too. Fix adopts the attain path's additive-surplus shape AND additionally bounds the rate horizon to solar-capable minutes (attain does not — A-INFO-1 narrative correction).

| ID | Sev | Finding | Outcome |
|---|---|---|---|
| (ship-blocker candidate) | — | nighttime rung_2 → intent="breaker" pausing EVs all night (would resurrect v5.15.0 incident) | **REFUTED by executed repro** — pause chokepoint (energy.py:3985-4002) triggers on grid_charge_intent / phase==CHARGE / intent=="redirect" only; "breaker" consumed nowhere as pause trigger; pre-existing anchor test pins it |
| A-INFO-1 | LOW | "mirrors attain" narrative inaccurate (rung additionally solar-bounds the horizon) | corrected in this record |
| A-INFO-2 | LOW | PRE-EXISTING: observed rate already contains today's solar; +surplus may double-count during daylight charge (inherited from attain design; optimistic direction) | tracked — measure with recorder data before any fix |
| B-LOW-1 | LOW | intent attr reads "breaker" on nighttime gate-open ticks (diagnostic only) | tracked with observability follow-ups |

**Executed proofs:** A hand-computed the live 21:04 case (836.3 → 59.0), pre-dawn solar-window case (no undercount), clamp decision-transparency (bands 77/83 inside [0,100]); B executed the nighttime EV repro + dusk latch (pre-existing no-solar short-circuit at :1740 unchanged, no resume-flap) + 335 tests green across ladder/energy suites. Builder executed 2 on-disk mutations RED.
**Deploy gate:** held until the 2026-07-15 11:00-14:00 arbitrage window completes on v5.17.3 (no stacking a ladder change onto the v5.17.1 hold's first live proof day).
