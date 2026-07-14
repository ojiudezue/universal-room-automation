# PLANNING — Arbitrage HOLD unreachable behind rung-ladder gate (live regression 2026-07-14)

**Tier: 3** (delicate shared primitive — battery reserve state machine; failure
mode = one missed path silently loses money; direct resurrection of the
A-CRIT-1/D-HIGH-1 defect family). Four framing-disjoint reviews + orchestrator
independent verification + operator has pre-authorized ship ("Fix it… let's
ship it. Make sure we don't introduce other issues — context-wide").

## Falsifiable master invariant (I-AH1)

> While an arbitrage/attain chunk is completed (`_arbitrage_chunk_completed`)
> and the charge window's high-rate boundary is still AHEAD, no decision tick
> may emit `reserve_level` below `peak_buffer_target` (the inclement
> partial_hold floor may only RAISE it) — in ANY reachable path: rung_0/rung_1
> gate closure, attain lockout, drain fallback, unknown-TOU fallthrough, or
> post-restart first ticks.

Reviewer D's job is to falsify exactly this, diff-blind, across the whole
off_peak branch including pre-existing code.

## Live incident (evidence)

2026-07-14: 08:01 reserve→80 commanded+verified (arbitrage CHARGE, poor day,
window 08:00, boundary 14:00 mid_peak). SOC 31→79 by ~09:30. 09:31 tick:
SOC≈target → `_classify_attain_rung` returned rung_0 ("projects ≥ target at
boundary" — trivially true AT target) → `_gate_is_open` returned False →
`_get_arbitrage_decision` (and its phase rule 1 "SOC ≥ target → HOLD")
UNREACHABLE → attain branch locked out by chunk-completed gate (by design) →
drain-target fallback emitted reserve 30. Battery drained the purchased
charge into off_peak house load, hours before the boundary it was bought for.
Recorder: cloud reserve 80.0@08:01 → 30.0@09:31. All writes verified ok —
the write path is healthy; the DECISION was wrong.

## Root cause

The rung ladder (attainability D1) was inserted INSIDE `_gate_is_open`,
in FRONT of the phase machine that owns HOLD. rung_0's predicate is
satisfied by the success state of the phase it guards. Bug Class #53
state-machine cousin: HOLD computed-but-unreachable.

## Deliverables

### D1 — Completed-chunk HOLD precedence (the fix)
In `determine_mode`'s off_peak branch, BEFORE `_gate_is_open`/rung
consultation: if `_arbitrage_chunk_completed` and the target boundary is
ahead → route directly to the arbitrage HOLD emission:
`reserve_level = _floor_reserve(peak_buffer_target, …)`,
`charge_from_grid=False`, phase HOLD (or WAIT-holding), arbitrage_active
consistent with attrs. SOC below target while holding is fine — reserve >
SOC means the battery idles/absorbs residual solar back toward target
(desired: today it would recover 71→80 on residual sun).
- MUST NOT change pre-window WAIT behavior (early-night, window not yet
  open → existing drain-park path unchanged, byte-identical).
- MUST NOT re-enter CHARGE (chunk lock stands; no second grid pull).
- Rung ladder untouched for the not-yet-charged path.

### D2 — Restart resilience for the chunk latch
`_arbitrage_chunk_completed` is RAM-only; a restart mid-hold re-triggers the
exact incident (rung_0 closes gate on reboot). Persist the latch + window
identity (boundary datetime) via the EXISTING sqlite KV rider infra
(energy.py `_save_evse_state`/restore, v5.16.3 pattern — REUSE, incl.
staleness: drop restored latch if the persisted boundary has passed or the
window date differs). Follow the WV keys' no-clobber + preserved-timestamp
conventions.

### D3 — Context-wide interaction sweep (explicit operator directive)
Verify and test, do not assume:
1. **EV drain-release floor (INV-EV-DEADBAND)**: `compose_release_floor`
   reads the emitter's commanded park (`_last_reserve_level`). During HOLD
   the park is 80 → EV drain-pause release floor rises to 80 during the
   hold window. Assess: rung_2 already pauses EVs ("breaker" intent) during
   arbitrage; confirm no NEW EV blockage vs pre-fix behavior on off_peak
   mornings, and that overnight (post-boundary, post-chunk-reset) floors
   return to the drain-target park. Cite code paths.
2. **Inclement floors**: `_floor_reserve` may only raise; byte-identical
   when allow_discharge.
3. **Mid_peak transition**: at boundary the mid_peak branch takes over
   (summer peak-ahead hold / discharge). Confirm hand-off emits sane reserve
   (no flap between 80 and hold_reserve at the boundary tick).
4. **Chunk reset**: `reset_arbitrage_chunk` on transition INTO off_peak
   (v4.5.0 D1) still the sole reset; D2's restore must not resurrect a
   stale latch after the reset fired.
5. **attain latch (`_attain_state="holding"`)** already has its own HOLD
   (v5.5.3). Ensure the two hold paths cannot both fire / contradict
   (precedence documented + tested).
6. **Load-shed / EVSE force-charge / observation mode**: no interaction
   changes; grep + state one line each.

### D4 — Tests (mutation-anchored + combinatorial per Tier 3)
- Reproduction test FIRST: pre-fix code path (SOC≥target, chunk_completed,
  boundary ahead, rung_0 conditions) → assert reserve emitted == target
  (fails on parent, passes post-fix). This is the incident's regression test.
- Combinatorial: SOC {below, at, above} target × chunk_completed {T,F} ×
  window {pre-open, open, boundary-passed} × rung {0,1,2} × hold_depth
  {allow_discharge, partial_hold(floor>target and <target)}.
- Restart: save→restore latch mid-hold → first tick emits target, not 30;
  stale (boundary passed) restore → dropped.
- EXECUTED mutations (report table): (a) delete the D1 short-circuit →
  reproduction test RED; (b) invert boundary-ahead check → RED; (c) break
  D2 restore staleness → RED.

## Acceptance
- **Test:** reproduction test red-on-parent / green-on-fix (executed proof).
- **Live (today):** post-deploy restart restores the latch (D2) → reserve
  re-commands 80 while SOC ~71 → battery recovers toward 80 on residual sun
  and HOLDS until 14:00; at 14:00 mid_peak branch takes over. Sensor attrs:
  arbitrage_phase hold/wait-holding, current_commanded_reserve 80,
  park_floor_source commanded.
- **Live (next poor day):** full cycle charge→hold→boundary with no 09:xx
  release. Shipwatch hypothesis included in README.
