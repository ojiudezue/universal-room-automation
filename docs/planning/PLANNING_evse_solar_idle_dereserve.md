# PLANNING — Solar-follow: de-reserve long-idle EVSE bays (narrow parked-reservation fix)

**Supersedes** the full Tier-3 discard-and-move stop-conditions plan (`PLANNING_evse_solar_stop_conditions.md`, PARKED). This is the marginal-benefit-narrowed version: it captures the only real dollar value of "stop conditions" — a finished/absent bay no longer starving a charging sibling — **without** removing the bay from `_excess_solar_active` (so no oscillator, no suppression latch, no consumer ripple, not Tier-3).

Operator 2026-08-26: liked the narrowing; the probe is invalid (garage_b idle now, no history) so build it **forward-looking** — ready for when garage_b comes online, no probe gate.

## 0. Problem (marginal-benefit isolated)

`SolarFollowController._tick` (`energy_pool.py:~4200`) reserves a MIN-amp floor for EVERY eligible-but-not-drawing bay:
```
parked_w      = (n_eligible − n_drawing) × SOLAR_FOLLOW_MIN_AMPS × 240 × SOLAR_FOLLOW_PHASES
allocatable_w = max(0, s_eligible − parked_w)
```
A **long-idle** bay (finished car drawing ~0, or an unplugged/claimed bay) is `eligible` but not `drawing`, so it inflates `parked_w` and **steals ~1.44–2.88 kW (6 A × 240 × PHASES) of surplus from the bays that ARE drawing.** In the single-bay case this is harmless (surplus exports/charges the battery regardless). In the **multi-bay case** — one bay finished while a sibling charges on a sunny afternoon — the charging sibling is throttled. That is the entire dollar value of the stop-conditions cycle.

The parked floor exists for a good reason (a bay between claim and ramp-up should keep a foothold), so we do NOT remove it wholesale — only for bays idle **long enough** to be presumed finished/absent.

## 1. Institutional context verified

- **REUSED** `SolarFollowController` tick + `drawing` / `eligible` / `stale_power` set computation (`energy_pool.py:~4160-4205`); `_stale_ticks` per-bay counter pattern (`energy_pool.py:~4160`) is the precedent for the new idle counter.
- **REUSED** `SOLAR_FOLLOW_MIN_AMPS`, `SOLAR_FOLLOW_MAX_AMPS`, `SOLAR_FOLLOW_PHASES` (energy_const).
- **NEW** `SOLAR_FOLLOW_IDLE_DERESERVE_TICKS` (module constant) — no equivalent exists (grep energy_const: only `_stale_ticks`-style power-staleness bounds, a different concept).
- **NEW** `self._notdraw_ticks: dict[str,int]` per-bay counter — mirrors `_stale_ticks` lifecycle exactly.
- Bay is NOT discarded from `_excess_solar_active` — so none of the 11 consumers change, the CLAIM-ON-EDGE contract is untouched, and there is no oscillator (the founding problem of the parked Tier-3 plan simply does not arise).

## 2. Falsifiable invariant

- **INV-IDLE-1 (dereserve):** a bay whose power has been ≤ the drawing threshold for ≥ `SOLAR_FOLLOW_IDLE_DERESERVE_TICKS` consecutive ticks does NOT contribute to `parked_w`, so `allocatable_w` for the drawing bays rises by exactly `SOLAR_FOLLOW_MIN_AMPS × 240 × PHASES` per de-reserved bay. **Falsified by:** any tick where a bay idle ≥ threshold still appears in the parked-floor count.
- **INV-IDLE-2 (no starvation of a resuming bay):** the counter resets to 0 the tick a bay re-enters `drawing`, so a bay that resumes charging is immediately re-reserved and allocated normally. **Falsified by:** a resumed bay staying de-reserved for ≥1 tick after it draws.
- **INV-IDLE-3 (no membership change):** the de-reserve does NOT `discard` the bay from `_excess_solar_active` and issues no `switch.turn_off`. **Falsified by:** any `_excess_solar_active.discard` or `turn_off` on the idle path (byte-diff the claim leg — it must be untouched).

## 3. Deliverables

### D1 — idle counter
Add `self._notdraw_ticks: dict[str,int]` (init in `__init__` alongside `_stale_ticks`). In `_tick`, after `drawing`/`eligible`/`stale_power` are known: for each `eid in eligible`, increment `_notdraw_ticks[eid]` if `eid not in drawing and eid not in stale_power`, else reset to 0 (pop). Do NOT count stale-power bays as idle (a dead sensor is not a finished car — that's the B7/C7 sensor-health lesson, reused here: a `stale_power` bay keeps its reservation, it is not de-reserved).

### D2 — de-reserve in the allocator
```
long_idle = {eid for eid in eligible if self._notdraw_ticks.get(eid, 0) >= SOLAR_FOLLOW_IDLE_DERESERVE_TICKS}
n_reserved = n_eligible - n_drawing - len(long_idle)      # >= 0 by construction
parked_w   = n_reserved * SOLAR_FOLLOW_MIN_AMPS * 240 * SOLAR_FOLLOW_PHASES
```
(Everything downstream — `allocatable_w`, `a_total`, `a_per_drawing` — unchanged.)

### D3 — de-reserved bays don't churn the write
In the per-EVSE write loop, a `long_idle` bay's target stays MIN and its write is issued at most once on entry to long-idle (skip the idempotent re-issue while it stays long-idle) — kills the per-tick 6 A safe-park churn. A drawing/ramping bay is unaffected. (Keep it simple: if this complicates the loop, leave the idempotent MIN write — the parked_w fix is the dollar value; the write-churn reduction is a bonus, not load-bearing.)

### D4 — knob
`SOLAR_FOLLOW_IDLE_DERESERVE_TICKS` — module constant in energy_const, default **10** (≈10 min at the 60 s loop). Rung: module constant (a behavioral safety/allocation bound whose change should require review — a too-low value would de-reserve a bay still ramping up from plug-in). Kill-switch: a very large value (e.g. 100000) effectively disables de-reserve (reverts to today's behavior). Document that on the constant.

## 4. Acceptance criteria — DISCRIMINATING

- **Verify (INV-IDLE-1):** with 2 eligible bays, one drawing and one idle ≥ threshold ticks, `parked_w` counts **0** idle reservations and the drawing bay's `a_per_drawing` is higher than it would be with the idle bay reserved. Under a plausible different failure (idle bay still reserved), the drawing bay gets `SOLAR_FOLLOW_MIN_AMPS × 240 × PHASES` less — the two outcomes differ numerically, so the test discriminates.
- **Verify (INV-IDLE-2):** feed the idle bay a drawing power sample → its counter resets → next tick it's re-reserved (parked_w includes it again if it drops out) and allocated as drawing.
- **Verify (INV-IDLE-3):** the claim leg (`energy_pool.py:1584-1687`) diff vs develop is EMPTY; no `discard`/`turn_off` added on the idle path.
- **Test:** `test_solar_follow_idle_dereserve.py` — multi-bay allocation with one long-idle bay; counter reset on resume; membership-unchanged assertion; the kill-switch (huge threshold) reverts to today's parked_w. Mutation-anchor: neuter `- len(long_idle)` → the drawing-bay allocation test goes RED.
- **Live:** when garage_b comes online and both bays are claimed with one finishing on a sunny afternoon, the still-charging bay is not throttled by the finished bay (observe `a_per_drawing` / commanded amps). Until then, forward-looking — validated in-suite.

## 5. Non-goals
- De-energizing an unplugged connector (turning the switch OFF) — an idle Emporia draws nothing; low value, and it's the part that needs the discard/oscillator machinery. Parked with the Tier-3 plan.
- Cleaning up the "claimed" bookkeeping across the 11 consumers — not a dollar/safety cost.
- The cessation ledger / stop-reason vocabulary — that was Tier-3 observability; revisit only if the narrow fix proves insufficient.

## 6. Tier / review
Tier 2 (shared primitive, cost-impacting, but contained additive change with a kill-switch and no membership/claim-leg change). 2 framing-disjoint reviews: A = allocator correctness + counter lifecycle + kill-switch; B = test-authority via mutation + claim-leg byte-identity. Orchestrator mutation-verify before ship.
