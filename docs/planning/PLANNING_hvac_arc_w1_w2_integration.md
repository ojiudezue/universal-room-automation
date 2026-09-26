# PLANNING — HVAC arc W1 + W2 integration (the seams between the pieces)

*Orchestrator, 2026-09-26. READ `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` COMPLETELY FIRST.* Operator: "plan all of it so its lego pieces fit together or at least the w1 and w2." This doc owns the **contracts between** the piece-plans; each piece-plan owns its internals. Where a piece-plan conflicts with this doc, this doc wins and the piece-plan is amended.

| Piece | Plan | Tier | Status |
|---|---|---|---|
| W2-0 live-room gate | `PLANNING_hvac_live_room_establishment.md` | 2-DB | v5.103.15 final validation |
| W1-A write governance | `PLANNING_hvac_w1a_thermostat_write_governance.md` (+AM-A1/A2) | 2-DB | planned |
| W1-B thermostat definition | `PLANNING_hvac_w1b_thermostat_definition.md` + `docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` | **3** | planned; operator go needed |
| W2-1 occupancy fast path | `PLANNING_hvac_w2_occupancy_fast_path.md` | 2-DB | planned; D0 rate probe pending |
| W2-2 night still-sleeper (A) + placeholder readers (B) | `PLANNING_hvac_w2_night_sleeper_and_placeholder_readers.md` | 2-DB each | planned; D-A0 probe running |

## 1. The seams (contracts)

**C1 — One write path.** After W1-A, every URA climate write goes through `emit_set_preset_mode` / `emit_set_temperature` / `emit_set_hvac_mode` (`hvac_setpoint.py`); a CI lint fails any raw `climate` call. **W1-B builds ON the funnels, never around them**: the brand definition decides *what* to write, the funnel performs and records it. W2-1 and W2-2 add no write sites.

**C2 — The write-log row is W1-B's measuring instrument.** W1-A's `climate_write` row (bypassing activity-log dedup, AM-A1) MUST also carry, captured at write time: `preset_mode` (status-derived), `hold_activity` (config-derived), `excursion_id`, `site`, and the values written. Without the status/config pair, W1-B's coherence rule cannot be measured before or after, and its 72 h ship gate has no oracle. → amend W1-A D2.

**C3 — One read model.** W1-B introduces `observed_hold(zone)` (coherent read: a `manual` report counts as a person only when config `hold_activity == manual`; status/config disagreement inside an ownership window is URA's echo). Its consumers are exactly: S1 lockout (`should_change_preset` / `preset_change_locked_out`, `hvac_preset.py:212-217`, `hvac.py:2484-2539`), the arrester's detection (`hvac_override.py`), and resume-then-pin (`hvac_setpoint.py:163-218`). W2 does NOT consume thermostat state. No other component may read `preset_mode == "manual"` directly after W1-B — enforced by a grep test.

**C4 — One timing contract for "our own write".** Three windows exist today and are not reconciled: URA `suppress(kind="temp")` 5 s / preset suppression (`hvac_override.py:129`); ha_carrier's 5-min post-write re-assert guard (`carrier_data_update_coordinator.py:168-296`); W1-B's proposed post-return ownership window. W1-B must define ONE ownership window per zone that covers the ha_carrier guard (≥ 5 min after URA's last write to that zone), measured with W1-A rows, and retire the ad-hoc suppress windows it supersedes. Until measured, the composition is UNVERIFIED (state of play C16).

**C5 — Cloud call-rate budget.** The 5-min tick exists as a Carrier call-rate bound (`hvac_const.py:11-13`). W2-1 adds decision cycles; W1-B's no-op suppression removes writes. Budget rule: per-zone Carrier **writes** (W1-A rows) must not rise above the pre-W2-1 baseline by more than the W2-1 D0-sized margin. W2-1 limiter is sized from its D0 trigger-rate probe; the W1-A write log is the before/after oracle. → W2-1 ships after W1-A is live for ≥ 1 day.

**C6 — Occupancy producer ownership.** `ZoneManager.update_room_conditions` / `_compute_hvac_occupied` (`hvac_zones.py`) is edited by W2-0 (classification), W2-2A (night tail extension) and W2-2B (placeholder handling). Contract: W2-2 reuses W2-0's classifier (`is_zone_transient_blocked`, `_coordinator_absent_this_pass`, excluded = not defined) — no second liveness notion. W2-1 triggers on the **rising edge of the room's own `STATE_OCCUPIED`** (`binary_sensor.<room>_occupied`, unique_id `{entry_id}_occupied`) for a non-hallway room in an HVAC zone that is NOT already HVAC-armed — the HVAC-occupancy entity is recomputed only inside a decision cycle, so triggering on it would be circular (corrected 2026-09-26, W2-1 plan review). W2-2A's night hold keeps `_hvac_armed` True, so the armed-gate suppresses re-triggers; W2-2A must not synthesize `STATE_OCCUPIED` edges.

**C7 — Retreat authority is single.** All retreat paths route through `conditioning_retreat_ok` (live after W2-0 for row-1/D7/D9/F4). W2-2B moves D5 coast, D6 source-4 and the continuous-occupied clock onto it. No W1 piece may add a retreat path.

## 2. File-overlap map (build serialisation)

| Region | W1-A | W1-B | W2-1 | W2-2A | W2-2B |
|---|---|---|---|---|---|
| `hvac.py` subscribe block / `_async_decision_cycle` entry | | | ✎ | | |
| `hvac.py` S1 preset block + lockout | | ✎ | | | |
| `hvac.py` D5 coast site | | | | | ✎ |
| `hvac.py` heat_cool enforcer (raw `set_hvac_mode`) | ✎ | | | | |
| `hvac_override.py` borrow/nudge/reset/arrester sites | ✎ (mode sites) | ✎ (returns, detection) | | | |
| `hvac_egress.py`, `hvac_predict.py`, `hvac_excursion.py` sites | ✎ | ✎ | | | |
| `hvac_setpoint.py` funnels | ✎ | ✎ | | | |
| `hvac_zones.py` producer / tail | | | | ✎ | ✎ |
| `presence.py` D6 source-4 | | | | | ✎ |

**Rules:** W1-A before W1-B (same files, B consumes A). W2-2B before W2-2A (same producer). W2-1 is disjoint from W1-A and can build in parallel in its own worktree, but merges after W1-A so C5 is measurable. Every build rebases on the previous merge and re-resolves file:line by symbol.

## 3. Order and gates

1. **Ship v5.103.15 (W2-0).** Gate: suite name-diff clean, Reviewer C drill, orchestrator check.
2. **In parallel:** W1-A build · W2-1 D0 rate probe · W2-2 D-A0 probe (running).
3. **W1-A ship** → one clean day of attributed writes → **measure**: strand minutes by cause (C2 fields), Carrier writes/zone/day (C5 baseline).
4. **W2-1 fast path** (built in parallel, merged now) · **W2-2B placeholder readers**.
5. **W1-B (Tier 3)** — operator go + 2 plan reviews + 4 build reviews + pre-deploy checkpoint. Gate: its 72 h zero-falsifier query on W1-A rows.
6. **W2-2A night still-sleeper hold** (corroborator chosen by D-A0).
7. W2 guest-as-person (verify-first), then W3.

## 4. Shared invariants across the arc
- **I-W (writes):** no URA climate write bypasses a funnel; each produces exactly one durable row (W1-A).
- **I-R (reads):** URA never treats a status-lagged or status/config-incoherent `manual` as a person (W1-B).
- **I-B (borrows):** after any borrow returns, the zone sits on its snapshot named preset with no URA-created manual hold (W1-B).
- **I-O (occupancy):** a zone retreats only on its own live rooms' occupancy; loading rooms block; failed rooms don't count (W2-0/W2-2).
- **I-L (latency/rate):** an occupancy rising edge yields a decision within the fast-path SLA, and per-zone Carrier writes stay inside the C5 budget (W2-1).

## 5. Operator decisions needed (consolidated)
From W1-B (recommendations in brackets): (1) adopt `set_activity_setpoint` for no-hold nudges? [**no** — keep `set_temperature`; the interrupted-profile-edit risk outweighs it once returns are presets-only] · (2) Bryant schedule reduction vs a schedule-boundary guard [**reduce schedules**, matches the working assumption] · (3) reclaim window 30 vs 60 min [**30**] · (4) W1-B ship gate 72 h [**72 h**] · (5) Nest placeholder now [**skip**] · (6) `NAMED_PROFILE_MATCH_TOLERANCE_F` rung [**module constant**]. From W2-1: whole-house vs per-zone cycle — only if its D0 probe forces it (default whole-house).

## 6. Amendments this doc imposes on piece-plans
- W1-A D2: add C2 fields (`preset_mode`, `hold_activity` at write time).
- W1-B: define the single ownership window per C4 and list the suppress windows it retires; consumers of `observed_hold` exactly per C3 + grep test.
- W2-1: merge after W1-A (C5); limiter acceptance uses W1-A rows.
- W2-2A: must not create synthetic rising edges (C6).
