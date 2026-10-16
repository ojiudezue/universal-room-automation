# ARC: Energy Coordinator resilience (opened 2026-10-16)

Operator: "Setup an EC arc so we can prosecute it to the end." Origin: the 10-15 storm night. The Envoy was offline from 17:38, the storm hold never fired, and three plan reviews kept finding reserve-floor leaks across ~25 decision branches.

**Rule for this arc:** each step ships through its own tier gate and live validation before the next step is planned in detail. The steps are ordered, but an approved step keeps going without waiting on later ones. Every step's README carries a Validated table. The arc closes only when every row below is `done` or deliberately `parked` with a trigger.

## Planning rule (operator 2026-10-16)
"Keep them together and plan them together so they fit like jigsaw and not discordant." Steps 2–7 get **one integrated plan** (`PLANNING_ec_storm_and_blind_decisions.md`), written after step 1 ships and against the built governor. It has one decision model end to end:

alert arrives → local applicability (code + point/zone) → local forecast over the alert window → hold depth → floor registered with the governor → command (or, while the Envoy is offline, the governor's blind rules) → outage ledger records the outcome.

The top-rate primitive (step 7) is the single definition of "expensive period" that the blind de-escalation and the hold logic both use. The plan can ship as staged builds, but the design, invariants, knobs and acceptance criteria are written once, so the pieces can't contradict each other. Steps 8–11 are the same TOU-transition and self-heal paths, so they get their own joint plan.

## Steps

| # | Step | Card(s) | Tier | Status | Gate to start |
|---|---|---|---|---|---|
| 1 | **Reserve write governor**: dispatch history rows with floor_ok (floor observed, NOT enforced — single floor moves to Stage A) (WriteStatus vocabulary), reserve-write bypass lint, restart via the existing ledger | EC-RESERVE-WRITE-GOVERNOR-1 | 3 | **Shipped v5.103.66** (2026-10-16 10:47 restart); live row check waits on the Envoy coming back | Plan Rev 3.2 + ground-truth audit (done) |
| 2 | **Keep deciding while the Envoy is offline**: inclement decision runs above the blind gate; blind holds and releases go through the governor; the v5.17.5 no-command rule is preserved except the floor write | EC-INCLEMENT-HARDENING-1 (D-blind) | 3 | Waiting on step 1 | Governor live-validated; revise PLANNING_inclement_hardening.md against the built governor (review-3 findings P3-01..04 are the checklist) |
| 3 | **Storm alert matching** by NWS code, checked locally: add the freeze products the outage record supports (Hard Freeze, Extreme Cold, Wind Chill) alongside Winter Storm / Ice Storm; **Wind Advisory stays medium (no hold)**, per AUDIT_outage_alert_correlation.md (0 of 33 windows had an outage); point-in-polygon for storm warnings where geometry exists | EC-INCLEMENT-HARDENING-1 (D-match) | 3 | Waiting on step 1 | Same revision as step 2 |
| 4 | **Hold until the hazard ends**: Onset/Ends instead of Expires; alerts that haven't started are not active (operator-approved) | EC-INCLEMENT-HARDENING-1 (D-ends) | 3 | Waiting on step 1 | Same revision as step 2 |
| 5 | **Outage ledger**: log each real off-grid event plus the alerts active at the time (Enphase keeps only ~7 weeks of history) | EC-INCLEMENT-HARDENING-1 (new deliverable) | 2 | Waiting on step 1 | Same revision as step 2 |
| 6 | **Forecast slice**: alert → local applicability → local forecast over the alert window → energy decision; pre-charge before storms | EC-INCLEMENT-HARDENING-1 (D-forecast, unparked) | 3 | Not started | Provider probe first: which of the three weather providers forecasts hourly gusts / precip probability / condition |
| 7 | **Top-rate primitive**: replace the 35 literal "peak"/"mid_peak" name checks with rate rank from the TOU engine; first user is the blind de-escalation (shoulder/winter top rate is mid_peak) | EC-BLIND-DEESCALATE-TOP-RATE-1 | 3 | Waiting on step 1 | Classify all 35 sites ("means top rate" vs "means the named period") |
| 8 | **Observation mode bypass**: the TOU-transition and self-heal paths write the reserve in observation mode | EC-OBSERVATION-MODE-RESERVE-BYPASS-1 | 2 | Investigating | After step 1, so the lint and rows cover it |
| 9 | **TOU transition consumed twice** (manager vs timer) | EC-TOU-TRANSITION-DOUBLE-CONSUME-1 | 2 | Investigating | Measure how often the manager wins |
| 10 | **TOU-transition path ledger gap**: no ledger stamp, no write-verify call, swallowed failures | EC-EVALUATE-PATH-LEDGER-GAP-1 | 2 | Inbox | Pairs with steps 8 and 9 (same path) |
| 11 | **Unexplained self-heal re-sends** (10-14) | EC-SELFHEAL-UNEXPLAINED-RESENDS-1 | 2 | Investigating | Use the step-1 history rows |

Related, outside this arc: EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 (Envoy dropout handling, waiting on the post-10-18 re-count).

## Evidence base
- `docs/planning/AUDIT_nws_alert_history_lakeway.md`: alert history 2021–2026 at our zone and county; point-local storm polygons.
- `docs/planning/AUDIT_outage_alert_correlation.md`: outages vs alerts; the house is on PEC.
- `docs/reviews/code-review/audit_reserve_surface_ground_truth.md`: live reserve behaviour, 470 writes in 7 days.
- Plans: `PLANNING_reserve_write_governor.md`, `PLANNING_inclement_hardening.md` (Rev 3, to be revised after step 1).

## Status log
- 2026-10-16: arc opened. Step 1 building on Fable.
- 2026-10-16: step 1 deployed as v5.103.66; the optimizer reserve deny is kept in (operator: "Keep"). After the restart the Envoy setup hangs: `/info` answers, but the authenticated `/ivp/pdm/device_data` probe hangs, so the Envoy needs a gateway reboot. With the Envoy blind, EC holds and writes no reserve, so there are no `reserve_write` rows yet. Next: the integrated plan for steps 2-7.
