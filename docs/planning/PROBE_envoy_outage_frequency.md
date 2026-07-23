# PROBE — Local Envoy Outage Frequency (D3 gate for blind-window EVSE guard)

**Run 2026-07-21 ~23:15 CDT** against the HA recorder (retention window
2026-07-13 → now), read-only. Method: for
`sensor.envoy_482543015950_current_power_production`, every `unavailable`
state row paired with the timestamp of the NEXT state row (recovery) via
window function; duration = gap. Caveat: gaps spanning HA
restarts/recorder downtime inflate the tail (the 1338-min max almost
certainly spans one); treat the >30min bucket as an upper bound.

## Findings

**Unavailability marks per day (production sensor):**
7-14: 8 · 7-15: 22 · 7-16: 22 · 7-17: 15 · 7-18: 8 · 7-19: 7 · 7-20: 29 · 7-21: 21
→ **chronic: every day of retention, 7–29 events/day.**

**Duration histogram (132 paired events, 8 days):**

| bucket | events | share | max |
|---|---|---|---|
| < 2 min | 87 | 66% | 1.6 min |
| 2–10 min | 15 | 11% | 9.9 min |
| 10–30 min | 8 | 6% | 21 min |
| > 30 min | 22 | 17% | 1338 min (restart-inflated) |

## Gate decisions this forces (per plan D3)

1. **A max-defer bound is MANDATORY for D1.** Long (>30 min) blind windows
   occur ~2-3×/day on this history — an unbounded defer posture would
   routinely strand overnight EVSE charging. D1 must integrate
   must-start-by: defer while blind UNTIL must-start-by pressure, then the
   force-charge-class escape applies (exact semantics per plan Q2/Q3).
2. **Sub-2-min blips (66%) must NOT flap the guard.** D1 needs a short
   entry-debounce (blind window "opens" only after N consecutive failed
   ticks or M minutes) or the fail-safe pause leg will cycle chargers
   on 90-second blips — the exact disconcerting-actuation class the fan
   pause work fought.
3. The 2026-07-21 incident (84 min) sits in the real tail — not a freak;
   the guard will exercise organically within days of shipping.
4. Q5 (correlate with HA restarts to test the load-recovery hypothesis):
   NOT answered by this probe; the >30min tail is restart-contaminated.
   Refinement pass belongs in the cycle's build phase if the hypothesis
   matters to design (it currently does not — the guard is
   posture-under-outage, cause-agnostic).
