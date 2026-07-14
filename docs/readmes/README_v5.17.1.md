# URA v5.17.1 — Tier 3: Arbitrage Completed-Chunk HOLD Precedence

**Type:** Tier 3 (delicate shared-primitive / invariant-critical) fix cycle
**Plan:** `docs/planning/PLANNING_arbitrage_hold_rung_gate_regression.md`
**Review record:** `docs/reviews/code-review/v5_17_1_arbitrage_hold_tier3.md`
**Commits:** 9b8e3c91, 237f7986, c61f3124, aaab3598 (develop tip 3112de5d)

## The Incident (2026-07-14)

On a poor-solar-class arbitrage morning, the battery charged to the
arbitrage target (80%) by 08:01. At 09:31 — still well before the
high-rate boundary — the cloud reserve was **released to 30 (drain
target)** instead of holding at `peak_buffer_target`. The bought-cheap
buffer was silently given back to the house before the expensive window
it was purchased for.

Root cause: once SOC reached the arbitrage target, the ladder re-ranked
to **rung_0**, and rung_0 **closed the gate that guarded the HOLD
emission path**. The completed-chunk HOLD was computed but never
consumed (Bug Class #53 shape): the very success condition (target
reached) disabled the code path meant to defend the result.

## Invariant (I-AH1, falsifiable)

> Once an arbitrage charge chunk has completed (SOC reached the chunk
> target) and the high-rate boundary is still ahead, the emitted reserve
> can never drop below `peak_buffer_target` on ANY reachable path until
> that boundary passes.

## The Fix

1. **Dual-owner HOLD short-circuit** — completed-chunk HOLD is now
   evaluated BEFORE the rung gate, so rung re-ranking (incl. rung_0)
   cannot close the path that defends a completed chunk.
2. **Boundary-dt guard** — the hold only applies while the high-rate
   boundary is genuinely ahead (no stale hold past the boundary).
3. **EVSE append clamp** — fixed a latent EVSE reserve-append site that
   could oscillate the cloud reserve (found in review, pre-existing).
4. **Chunk-latch persistence with eager save** — `arbitrage_chunk_completed`
   latch persists across restart so a mid-window reboot cannot forget
   that the chunk completed and release the buffer.

## Review Chain

Tier 3 protocol: 4 framing-disjoint reviews (A local correctness, B
state-machine integrity, C mutation-anchored test authority, D
adversarial completeness) + a D re-pass after fix-up.

- **6 HIGH found and fixed**, including the latent EVSE reserve-append
  oscillation site.
- **2 MED deferred (tracked in review record):**
  - D-MED-1: boot clamp reference nuance.
  - D-MED-2: stale-latch-into-fresh-chunk edge (staleness ladder
    handles the common case; residual tracked).

## Shipwatch Acceptance Hypotheses

```yaml
version: v5.17.1
hypotheses:
  - id: H1
    claim: installed_version == v5.17.1
    oracle: hacs
  - id: H2
    claim: >
      NEXT poor-class arbitrage morning: after charge completes, cloud
      reserve (number.iq_battery_hacs_battery_reserve) stays at
      peak_buffer_target until the high-rate boundary — no drop to
      drain-target mid-window.
    oracle: ha-recorder
    window: 3d
  - id: H3
    claim: zero URA ERROR logs over 24h (boot transients excluded)
    oracle: ha-logs
```

## Live Validation — Validated 2026-07-14 (post-restart, ~12:14 CDT)

| Criterion | Result | Observed evidence |
|---|---|---|
| L1 — deploy healthy | **PASS** | HACS `installed_version = v5.17.1` (`pending_update: false`); `sensor.ura_presence_coordinator_presence_house_state` available (`arriving`, last_changed 12:13:30 CDT); zero URA ERROR in system log AND raw error_log (search `universal_room`, 0 hits). No "Envoy unavailable — holding" blind-hold ticks persisted past boot. |
| L2 — D2 latch restore | **PASS (as-expected)** | `sensor.ura_energy_coordinator_battery_strategy` attrs post-restart: `arbitrage_chunk_completed: False`, `arbitrage_phase: charge`, SOC 67 < target 80. No latch was persisted pre-restart (fix ships the persistence), and no chunk is currently complete, so a False latch is the correct restore outcome — the staleness ladder correctly declines to invent a completed chunk. `last_verified_write_*` attrs carry `restored: true`, proving the D2 restore path executed. |
| L3 — chunk reset at off_peak entry | **PENDING (by design)** | Fires at tonight's off_peak entry; recorder check tomorrow via the H2 3-day window (Shipwatch). |
| L4 — no reserve write oscillation | **PASS** | `write_mismatch_counts_24h` = `{reserve_soc: 0, charge_from_grid: 0, storage_mode: 0}`. Cloud reserve history (`number.iq_battery_hacs_battery_reserve`, 6h): 28 → 80 @08:01 → 30 @09:31 (the pre-fix incident itself) and NO further writes post-restart — no 80↔45 pattern. |

Boot-only transients seen and dismissed: none URA-attributable; the
known Envoy blind-hold transient did not surface as an ERROR.

Note: **H2 is the REAL acceptance** — reserve holding at
`peak_buffer_target` through a completed chunk until the high-rate
boundary — and can only land on the next poor-class arbitrage morning.
Shipwatch tracks it over the 3-day recorder window. Today's live attrs
already show the corrected posture: `arbitrage_active: true`,
`peak_buffer_target: 80`, `current_park_floor: 80`,
`effective_release_floor: 80`, `next_high_rate_transition` 14:00 CDT.
