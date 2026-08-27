# v5.91.3 — Solar-follow: de-reserve long-idle EVSE bays

**Card:** `EVSE-SOLAR-IDLE-DERESERVE-1`
**Tier:** 2 — shared primitive (solar-follow allocator), cost-impacting, contained additive change with a kill-switch and no claim-leg / membership change. 2 framing-disjoint reviews + fix-up + orchestrator mutation-verify.
**Merge:** `feature/solar-follow-idle-dereserve@896e71a4a` → develop.

## What this ships

The marginal-benefit-narrowed replacement for the parked Tier-3 discard-and-move stop-conditions plan.

**Problem:** solar-follow reserves a 6 A parked floor for every claimed bay that isn't currently drawing. A car that finished (or a claimed bay with no car) keeps that ~1.44–2.88 kW reservation, which is subtracted from the surplus given to a sibling bay that IS charging — so on a sunny afternoon a live car is throttled by a dead one.

**Solution:** once a bay has drawn ~0 for ≥ `SOLAR_FOLLOW_IDLE_DERESERVE_TICKS` (10 ≈ 10 min), it stops counting in the parked floor, so the charging sibling gets the full surplus. The bay **stays claimed** (no `_excess_solar_active` discard, no `switch.turn_off`) — so nothing else changes and the re-claim oscillator that made the full stop-conditions cycle Tier-3 never arises. In-memory counter (conservative on restart: all bays re-reserve for ~10 min post-restart).

**Why narrow, not the Tier-3:** the marginal-benefit test isolated this parked-floor starvation as the *only* real dollar value of "stop conditions." The expensive discard-and-move machinery (suppression latch, oscillator resolution, 11-consumer ripple) existed solely to solve the oscillator that *discarding* creates — not discarding sidesteps it entirely. The full plan is parked (`EVSE-SOLAR-STOP-CONDITIONS-1`), available if the narrow fix proves insufficient.

**Forward-looking:** garage_b is idle today so there's no history to probe, and we don't want a code change when it comes online — so this ships now, validated in-suite, ready for the multi-bay case.

## Review
2 framing-disjoint reviews. Core (parked_w allocator, counter lifecycle, kill-switch, claim-leg byte-identity) SHIP-clean and mutation-anchored. The reviews caught an over-engineered "bonus" (D3, a write-churn latch) that added a real control-abdication risk for ~zero benefit (the deadband already prevents churn) — **deleted in fix-up**. Claim-loss counter clear added so a re-plugged car gets a fresh observation window (mutation-anchored). Orchestrator re-ran the parked_w mutation by hand → the discriminating test goes RED (14→20 A); D3 grep-clean; claim-leg byte-identical. Record: `docs/reviews/code-review/solar_follow_idle_dereserve.md`.

## Acceptance criteria
- **Verify:** with 2 eligible bays, one drawing + one idle ≥ threshold ticks, `parked_w` counts 0 idle reservations and the drawing bay's commanded amps are higher than with the idle bay reserved (test asserts 20 A vs the un-fixed 14 A — the numbers differ, so it discriminates).
- **Verify:** a bay that resumes drawing resets its counter the same tick (re-reserved); a re-claimed bay starts its counter from 0.
- **Verify:** no `_excess_solar_active.discard` / `switch.turn_off` on the idle path; claim leg (`energy_pool.py:1584-1687`) byte-identical to develop.
- **Verify:** kill-switch — a huge `SOLAR_FOLLOW_IDLE_DERESERVE_TICKS` reverts to the pre-cycle parked_w.
- **Live (forward-looking):** when garage_b comes online and both bays are claimed with one finishing on a sunny afternoon, the still-charging bay is not throttled by the finished bay. Until then, validated in-suite (single-bay case has no observable behavior change — surplus flows to battery/grid regardless).

## Post-deploy validation — (to be written back after restart)
