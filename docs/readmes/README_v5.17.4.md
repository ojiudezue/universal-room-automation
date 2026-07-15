# URA v5.17.4 — Rung Projection Solar-Horizon Bound + Display Clamp

**Released:** 2026-07-15 · **Tier:** 2 (framings A+B, both SHIP) · **Commits:** b3518944 (build) + abcfc3e7 (review record)
**Review record:** `docs/reviews/code-review/v5_17_4_rung_projection_solar_bound.md` · **Baseline tag:** `pre-review-v5.17.4`

## Problem — the 836% / 521% projection artifact

Live evidence 2026-07-14 21:04 and 2026-07-15 03:16: `arb_projection_rung0` on
`sensor.ura_energy_coordinator_battery_strategy` read **836.3%** and **521%** —
physically impossible SOC projections. The rung-0/rung-1 attainability
projections extrapolated the observed K-tick net-charge rate linearly across
the FULL time-to-boundary (~17h overnight), with no recognition that the rate
is solar-driven and the sun sets.

## Root cause — a latent SHAPE bug, not just a horizon bug

Found during build: the projection computed

```
soc + (rate + solar_surplus) × hours        # WRONG
```

`solar_surplus` is a **%SOC total** (already daylight-window-sliced via
`_expected_solar_surplus_pct`), not a per-hour rate — multiplying it by hours
systematically over-trusted solar in daytime classification too. The fix
adopts the attain path's additive shape **plus** a solar-bounded rate horizon
(which attain itself does not have — see A-INFO-1):

```
soc + rate × min(hours_to_boundary, solar_hours_remaining) + solar_surplus
```

then clamps the stamped display value to [0, 100] (SOC cannot exceed 100%).
All three projection sites fixed: rung-0 entry, rung-1 counterfactual, rung-1
entry (`energy_battery.py`).

## Live consequence this fixes

On the morning of 2026-07-15 at 11:20, rung_0 wrongly **closed the gate** —
projection read 179%, classifying solar as sufficient — and the attain safety
net had to grid-charge anyway. Post-fix the ladder classifies honestly, in
agreement with the attain safety net (no divergence between the two layers).

## Review summary

Tier 2, framings A+B on `ura-reviewer-std`. Both **SHIP**.

- **Refuted ship-blocker candidate:** "nighttime rung_2 → intent=`breaker`
  pauses EVs all night (v5.15.0 incident redux)" — refuted by executed repro:
  the pause chokepoint (`energy.py:3985-4002`) triggers only on
  grid_charge_intent / phase==CHARGE / intent=="redirect"; `"breaker"` is
  consumed nowhere as a pause trigger; a pre-existing anchor test pins it.
- A-INFO-2 (LOW, pre-existing): observed rate already contains today's solar;
  +surplus may double-count during daylight charge — tracked, measure with
  recorder data before any fix.
- B-LOW-1 (LOW): `intent` attr reads "breaker" on nighttime gate-open ticks
  (diagnostic only) — tracked with observability follow-ups.
- Executed proofs: hand-computed the live 21:04 case (836.3 → 59.0), pre-dawn
  solar-window case, clamp decision-transparency; nighttime EV repro + dusk
  latch; 335 tests green across ladder/energy suites; 2 on-disk mutations RED.

## Deploy gate — PASSED

Deploy was held for the 2026-07-15 hold-proof window on v5.17.3: the chunk
held 80 from completion to the 14:00 boundary, and the boundary tick fired at
14:00:05.001. Gate satisfied; deploying.

## Tests

New class `TestV5174RungProjectionSolarHorizon` in
`quality/tests/test_arbitrage_solar_attainability_ladder.py` (nighttime bound,
daytime full-horizon non-truncation, display clamp) + retuned hysteresis
expectations to the corrected math. Suite baseline unchanged: **36 failed /
14 errors / 6821 passed** (pre-existing env-drift failures only).

## Shipwatch acceptance hypotheses

```yaml
project: ura
version: v5.17.4
hypotheses:
  - id: H1
    claim: installed_version == v5.17.4
    oracle: ha_state
  - id: H2
    claim: arb_projection_rung0 attribute ≤ 100 whenever non-null over 24h
    oracle: recorder
    window: 24h
  - id: H3
    claim: zero URA ERROR lines
    window: 24h
```

## Live Validation — Validated 2026-07-15

Deployed + HACS v5.17.4 installed (`installed_version: v5.17.4`); HA restarted
~14:04 CDT; energy decision cycles observed 14:06 (boot tick) and 14:11-14:26
(steady state).

| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Deploy healthy | **PASS** | HACS `installed_version = v5.17.4`; `sensor.ura_presence_coordinator_presence_house_state` available (`away`); `sensor.ura_energy_coordinator_battery_strategy` settled to `self_consumption` by 14:11; error_log grep `universal_room_automation` @ ERROR = **0 lines** post-restart |
| L2 | `arb_projection_rung0` ≤ 100 or null | **PASS (null branch)** | Daytime, arbitrage gate `n/a` (charge window opens 2026-07-16 11:00) → `arb_projection_rung0 = null`, `arb_projection_rung1 = null` on both boot tick and steady-state tick. Clamp assertion satisfied (≤100-or-null). True nighttime ≈-SOC check rides Shipwatch H2 (recorder oracle, 24h) |
| L3 | Rung/attain agreement on next poor-morning window | **DEFERRED (as planned)** | Beyond deploy-day observability (today `solar_day_class: poor`, tomorrow moderate); follow-up note stands |
| D2 | `arbitrage_chunk_completed` staleness ladder | **PASS** | 14:00 boundary passed pre-restart → latch correctly DROPPED on restore: `arbitrage_chunk_completed = false` on first post-boot read (14:06) and steady state. Restored-False/dropped is the correct staleness-ladder outcome |

Boot transients seen and dismissed: `mode: unknown` / "Envoy unavailable —
holding (no commands issued)" during Envoy warm-up (14:06 tick), resolved by
14:11. Non-URA anomaly noted: `envoy_available` flapped false at 14:26 with
`soc_source: cloud_fallback` — Envoy telemetry flakiness handled by the
designed fallback (see `PLANNING_envoy_telemetry_failover_map.md` workstream);
no URA errors, reserve write-verify `status: ok` (commanded 66 = oracle 66.0).
