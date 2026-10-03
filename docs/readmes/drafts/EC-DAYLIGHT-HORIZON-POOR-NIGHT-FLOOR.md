# DRAFT — EC daylight-gated rung horizon + poor-night WAIT floor (version assigned at deploy)

**Status:** built on `feature/ec-daylight-poor-night`, not deployed. Tier 3 (4 framing-disjoint build
reviews + orchestrator re-verification + operator checkpoint before deploy; no restart while the house sleeps).
**Plan:** `docs/planning/PLANNING_ec_daylight_horizon_and_poor_night_floor.md` (plan reviews #1 and #2 binding).
**Cards:** EC-RUNG1-WAIT-EV-PINGPONG-1 (fix 1) + the poor-night WAIT-floor card (fix 2, mint at dispatch).

## What changed

### Fix 1 — no night-time EV pause/resume loop (rung 1)
- The rung ladder's charge-rate projection now counts the observed rate only while it is daylight
  (`sunrise <= now < sunset`, from `sun.sun`; fallback 07:00-19:00). Before sunrise and after sunset only the
  forecast solar term counts, so `arb_projection_rung1 == arb_projection_rung0` and rung 1 cannot start at night.
- 10-01 incident: SOC 8.9 %, EV 11.6 kW at 01:14 projected 100 % (EV load extrapolated over ~16 h of night).
  Now: 50.0 % for both projections, rung 2, EV left alone. Replay of the recorder night: 0 rung-1 ticks
  before sunrise (pre-fix code on the same inputs: 11 in 01:14-03:20).
- Daylight projections are unchanged (byte-identical; replayed against the recorder and an independent oracle).
- `EnergyProjector.project_soc_at_boundary` gained an optional `sunrise_dt` (default `None` = unchanged for every
  other caller).

### Fix 2 — poor nights hold the drain floor (operator ruling 2026-10-03)
- On poor/very_poor target days with arbitrage on, WAIT parks at the drain floor (`current_offpeak_drain_target`,
  30 % with the live sliders) while SOC is above it, and at `max(reserve_soc, SOC)` once SOC is at or below it.
  Before: WAIT parked at `reserve_soc` (10 %), so the poor/very_poor sliders did nothing while the gate was open.
- **Park only.** WAIT never grid-charges toward the floor. Any refill decision belongs to attain.
- Never lower than the old behaviour (new WAIT reserve >= old on every input). With SOC below `reserve_soc`
  (09-30 night, SOC 7-9 %) WAIT still emits 10, not 7-9.
- This deliberately reverses the v4.5.0 "Mistake #7" note (no artificial drain target in WAIT).

## Behaviour changes to know about
- **EV drain-release floor rises on poor nights** (plan review #1 R1-1). The commanded WAIT floor becomes the
  EV drain rule's release floor, so `effective_release_floor` is ~30 on a poor night (was 10). The EV runs on
  grid, not battery, while the battery is parked.
- **Abort-path WAIT holds the floor too** (review #2 F9): after a charge-window recheck abort the battery parks at
  the floor for the rest of the chunk instead of draining to `reserve_soc`.
- Status text: the WAIT reason reads "Arbitrage WAIT — holding drain floor N%"; `next_action_estimate` reads
  "waiting for charge window, holding N% floor (lead_time=…)" or "arbitrage chunk completed — holding N% floor".
- `current_park_floor` / `effective_release_floor` / `current_offpeak_drain_target` now agree with what is
  commanded on WAIT ticks (they showed 30 while 10 was commanded).
- The ledger behind `current_park_floor` moves in 1 % steps under the 2 % write deadband while SOC is below the
  floor, so it can lag by up to 1 point (review #1 R1-2).
- **Residual (not fixed, documented):** rung 1 can still enter just after sunrise if an EV session is still
  drawing (review #2 F6). Detector: the SPEC INV-1 trip-wire card (>2 strategy-caused EV toggles/h → NM).

## Kill switch
Set `number.ura_energy_coordinator_off_peak_drain_poor` and `_very_poor` equal to `reserve_soc`: WAIT then parks
exactly as before. Fix 1 has no knob (it only removes a night-time extrapolation).

## Live validation (prospective — replace with a `Validated <date>` table after restart)
- First poor post-midnight night with EV draw: `arbitrage_rung` stays `rung_2`, `arb_projection_rung1` ==
  `arb_projection_rung0` before sunrise, zero `evse_paused_by_arbitrage` entries between sunset and sunrise,
  EV turn-ons ≤ 2/h.
- Next poor-target night: `arbitrage_phase=wait`, `current_commanded_reserve` == `current_offpeak_drain_target`
  (30) while SOC > 30, `hold_owner=arbitrage_wait`, `park_floor_source=commanded`; morning CHARGE still fires at
  lead time and reaches the peak buffer by the boundary.
- Discriminator: commanded 30 but SOC still falls to 10 ⇒ the hardware write is not landing (check
  `command_trail`), not a strategy failure.
