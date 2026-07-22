# PLANNING — Fill-priority daylight restoration (honest accounting)

**Status:** FILED 2026-07-22 (operator-directed). Not scheduled.
**Trigger:** 2026-07-22 morning — Garage A charged at 10:03 (off_peak) while
the house battery sat at 12–31% refilling from solar. Operator: "when the
sun comes out, first priority is filling the house batteries."

## The honest accounting — what was, and what changed

**Long-standing behavior (pre-v5.5.5, months):** fill-priority held EVs
whenever SOC < 80% and the solar forecast was healthy, ALL DAY; the only
daytime EV charging path was the excess-solar claim at SOC ≥ 95%. This is
the behavior the operator remembers: *"EVSE would not charge during the
day except good summer days above 95% house battery fill."* Correct
recollection — verified against the pre-v5.5.5 hold logic.

**Its real bug:** fill-priority also never released at NIGHT, because its
solar-health signal (`solcast_remaining`, "remaining today") rolls to the
next day's full forecast at midnight — so at 2am the hold looked
"solar-healthy" and the off_peak ensure-on deadlocked behind the
carry-over guard. Cars never completed charges ("good at pausing, bad at
starting").

**v5.5.5 (2026-06-18, Tier 3, evse-offpeak-fill-release):** fixed the
night deadlock. The operator's vetted spec IN THAT PLAN says, verbatim:
- "Fill-priority's 80% target is **daytime peak-rate protection** —
  during the day, fill home batteries first, then charge cars."
- "**After peak ends (~8pm summer)**, the 80% clamp disappears; …fire
  the chargers on cheap off_peak grid (**~9pm–3am**)."

**What the implementation actually did (D1):** made fill-priority inert
for the TOU period `off_peak` — using the TOU period as a PROXY for
"night." But the summer TOU calendar's off_peak runs **21:00 → 14:00**,
which includes ~7 hours of DAYLIGHT. Every artifact of that cycle framed
the release as nocturnal (spec: "~9pm–3am"; acceptance: "EVs charge
overnight"; cross-midnight test: "23:00→05:00 releases throughout");
none of the four reviews examined the 07:00–14:00 morning-sun slice. The
proxy silently surrendered the ratified "day = battery first" behavior
for those hours.

**Why it matters physically:** under the self-consumption profile with
charge-from-grid off, consumption is served by solar first — a morning
EV draw removes battery-fill 1:1 (battery max charge 30.7 kW >> array
~15 kW), it is NOT "cheap grid" as the release's rationale assumed.
Harmless on excellent-forecast days (battery fills anyway); real on
moderate days — which the pre-v5.5.5 design protected and today's does
not.

**Conclusion of record:** this cycle is a RESTORATION of the v5.5.5
ratified spec, not a new enhancement. The night-deadlock fix stays; the
over-broad proxy gets corrected.

## Deliverable (single, small)

D1: amend `fill_priority_inert` (`energy_pool.py`, determine_fill_priority_actions)
from `tou_period in ("peak","off_peak")` to day/night-aware off_peak:
- `peak` → inert (unchanged; TOU pause canonical).
- `off_peak` AND **night** (before civil sunrise / after sunset — TIME
  anchors, explicitly sanctioned by the v5.5.5 PHASE INVARIANT: "TOU
  period + day-boundary lookahead + sun/daylight bounds — i.e. TIME") →
  inert (cars charge overnight; the v5.5.5 fix preserved).
- `off_peak` AND **daylight** → NOT inert: normal hold logic applies
  (SOC < 80 + forecast healthy → hold; release at SOC ≥ 80 or forecast
  decay). Restores pre-v5.5.5 daytime behavior inside the summer
  off_peak morning.
- `mid_peak` → unchanged (peak_ahead gating).
Sun boundary source: REUSE whatever sun/daylight primitive URA already
consults (grep sun.sun / dawn/dusk helpers — institutional check at
build); never instantaneous PV (the invariant).

Interactions to verify at build: off_peak ensure-on + must-start-by (a
car needing charge by morning still completes overnight — sunrise ends
the fill window AFTER the night window closes, so no conflict); BAEC/DP
(fill-priority is a peer set; no ownership change); blind-window guard
(pending cycle — the new daylight hold must compose with
`_stronger_peer_holds` exactly as today's holds do).

**Tier: 2-DB minimum** (money path, EVSE precedence, regression-prone —
standing policy), with the v5.5.5 review docs re-read as prior art.

## Acceptance sketch
- Test matrix: off_peak × {night, daylight} × {soc<80, soc≥80} ×
  forecast health — hold/release per the corrected table; the v5.5.5
  cross-midnight case (23:00→05:00 releases throughout) MUST still pass.
- Mutation: removing the daylight branch re-creates today's morning
  charge-through (a test fails); removing the night branch re-creates
  the pre-v5.5.5 deadlock (the v5.5.5 test fails).
- Live: next moderate-forecast morning with a car plugged in after
  sunrise → EVSE holds until SOC ≥ 80, then charges; overnight sessions
  unaffected.
