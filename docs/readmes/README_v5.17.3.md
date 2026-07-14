# URA v5.17.3 — At-Boundary TOU Decision Tick + Boundary-Window Hardening

**Released:** 2026-07-14 · **Tier:** 2 (framings A+B, both SHIP; LOWs folded) · **Commits:** a24a2d7c (build) + f911e526 (LOW fold-in) + 58af999c (review record)
**Review record:** `docs/reviews/code-review/v5_17_3_boundary_tick_meds.md` · **Baseline tag:** `pre-review-v5.17.3`

## Problem — boundary lag

Energy decision cycles run on a 5-minute periodic timer (`DEFAULT_DECISION_INTERVAL_MINUTES = 5`). A TOU period flip (e.g. off_peak → peak at 16:00 CDT) was therefore handled **0–5 minutes late** — whenever the next periodic tick happened to land. On top of that lag, the Enphase battery has its own command-acceptance latency, so the two delays compounded: the battery could still be in the old period's mode several minutes into peak, buying grid at peak rates (or discharging when it shouldn't).

## D1 — At-boundary TOU decision tick (+5s, real clock)

At each decision cycle, `_arm_tou_boundary_listener` computes the next TOU boundary from the real rate table and registers an `async_track_point_in_time` listener that fires one extra `_async_decision_cycle` at **boundary + 5 seconds** (`TOU_BOUNDARY_TICK_DELAY_S`, `energy_const.py`). The +5s guard rides past the second-of-boundary edge so `get_current_period` reliably reports the new period. The tick evaluates the *actual just-started period* exactly like a periodic tick — **no synthetic-clock override anywhere**; it is the real wall clock.

- **Kill switch:** set `TOU_BOUNDARY_TICK_DELAY_S` negative → `_arm_tou_boundary_listener` returns early, no listener registered, no boundary code path runs; fall back to the periodic timer only.
- **Anticipatory variant considered and REVERTED.** D1 was first specced as an anticipatory tick (-3min before the boundary, with a synthetic now-override) at operator suggestion, then reverted to the plain at-boundary variant after marginal-benefit decomposition (operator: "pause to consider this"). The anticipatory design is parked; its evidence trigger is boundary-lag data showing real cost. See the review record for the full history note.

## D-MED-2 — Eager latch-clear persist (reset edge)

Latch clears on the reset edge are now persisted eagerly rather than waiting for the next periodic persist. This closes the restart-into-fresh-chunk window where a restart landing between the in-memory clear and the deferred persist would resurrect a stale latch.

## D-MED-1 — Boot-safe EVSE clamp fallback

The EVSE overlay clamp now falls back to the **boot-restored commanded ledger** when the live commanded value is not yet available after restart, instead of clamping against a missing/default value. Clamp direction verified in review: overlay append is a raise-only guard; legitimate downward reserve moves are unaffected (normal `_result` path).

## Review summary

Tier 2, framings A+B on `ura-reviewer-std`. Both SHIP, LOW-only findings; all three LOWs folded (A1 delay==0 contract test, B1 one-shot WARNING on hypothetical HA API rename, B3 exception-clears-`_cycle_in_flight` test; B2 accepted as established pattern). Executed proofs: boundary-walk against the real rate table (7 cases incl. midnight wrap + Sep30→Oct1 season flip), DST analysis, thrown-exception flag-clear execution, 3 on-disk builder mutations all RED.

## Tests

`quality/tests/test_v5_17_3_boundary_and_latch.py` (575 lines). Suite baseline unchanged: **36 failed / 14 errors / 6818 passed** (pre-existing env-drift failures only).

## Shipwatch acceptance hypotheses

```yaml
project: ura
version: v5.17.3
hypotheses:
  - id: H1
    claim: installed_version == v5.17.3
    oracle: ha_state
  - id: H2
    claim: journal carries the "at-boundary TOU tick" INFO line within 60s
      after the next TOU transition (16:00 and 21:00 CDT today)
    oracle: log_search
    window: 12h
  - id: H3
    claim: zero URA ERROR lines
    window: 24h
  - id: H4
    claim: carryover — v5.17.1 poor-morning hold still pending
    oracle: carryover
```

## Live Validation — Validated 2026-07-14

Deployed + HACS v5.17.3 installed; HA restarted ~18:20 CDT (after the 16:00 boundary, so the 21:00 CDT boundary is the first live exercise).

| Criterion | Result | Observed evidence |
|---|---|---|
| L1a installed_version | PASS | `update.universal_room_automation_update` attrs: installed_version=v5.17.3, latest_version=v5.17.3 (read 18:26 CDT) |
| L1b house_state sane | PASS | `sensor.ura_presence_coordinator_presence_house_state` = `guest`, last_updated 18:24:33 CDT (post-boot) |
| L1c zero URA ERROR | PASS | error_log ERROR scan post-restart: 0 URA lines; all ERRORs non-URA (laundry template-sensor >255-char state, ESPHome logging_changed jobs, MQTT number range — known boot noise) |
| L2 "armed" INFO line | PASS (indirect) | Boot-time INFO line suppressed by WARNING-level file logger (known: v4.7.26 memo). Discriminating negative: the arm helper's failure WARNING ("…failed for %s — periodic timer only") is ABSENT from logs → `async_track_point_in_time` registration succeeded. Logger for `domain_coordinators.energy` bumped to INFO at 18:27 CDT so the 21:00 fire + re-arm lines land in the journal. |
| L3 boundary fire + decision cycle | PENDING | 16:00 CDT boundary passed pre-deploy; 21:00 CDT is outside the validation window. Shipwatch H2 (12h window, log-search oracle) tracks tonight's 21:00:05 fire line. Energy coordinator healthy meanwhile: `sensor.ura_energy_coordinator_battery_strategy` = self_consumption, reason "Peak — battery covers load, solar exports", last_updated 18:26:03 CDT (periodic cycle running). |

Boot transients dismissed: laundry_device_status >255-char ERROR loop (pre-existing template sensor, non-URA), SPAN circuit-anomaly WARNINGs and Envoy cross-check divergence WARNING (established boot/steady-state noise).
