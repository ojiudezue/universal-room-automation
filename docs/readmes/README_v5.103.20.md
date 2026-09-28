# README v5.103.20 — HVAC fast occupancy response (evidence clock, zone-scoped fast runs, transit filter)

**Status:** BUILT on `feature/hvac-fast-occupancy-response` (2026-09-28). **NOT deployed** — Tier 3: four
framing-disjoint reviews, orchestrator re-grep + re-drill, then the operator checkpoint (four items below + D0c Gate A).
**Plan:** `docs/planning/PLANNING_hvac_fast_occupancy_response.md` REV 7 + fix-up round 1 (rulings R0–R8, O1, O2).
**Reviews:** four Tier-3 framing-disjoint reviews on `pre-review-v5.103.20` (00bb88473) — all FIX-REQUIRED, no CRIT/HIGH;
fix-up round 1 applied on the branch (see plan §18).
**Cards:** `HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1`, `HVAC-W2-OCCUPANCY-TRUTH` (fast path),
`HVAC-ENTRY-DWELL-ROOM-CLOCK-1` (folded as D5).
**Mandatory read done:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (complete; updated in this branch).

## What changed

| Deliverable | What | Where |
|---|---|---|
| D1 — HVAC's own release clock | In `home_day` / `home_evening` a room is HVAC-occupied while `evidence_active OR now < last_evidence + hold` (hold from `ROOM_TYPE_HVAC_HOLD`, operator rulings R1/R2: closet/infra 60 s, generic/utility/media/garage 120, bathroom/common 180, bedroom 240, hallway 0). The v5.103.19 machine keeps running as a SHADOW on the frozen `ROOM_TYPE_HVAC_TAIL_LEGACY`; `sleep`/`waking` = shadow OR evidence; `home_night`/`guest`/`arriving`/`away` are byte-identical to v5.103.19. `last_occupied_time` is back-filled to the exact release. | `coordinator.py` (`_stamp_hvac_evidence`, 3 accessors), `hvac_zones.py`, `const.py`, `hvac_const.py` |
| D2 — event-driven zone decisions | A room-coordinator refresh with an evidence advance into a cold zone queues a ZONE-SCOPED fast run (≤ 45 s SLA; 60 s per-zone limiter, exempt after an away; write ceiling 6/h, runaway guard 30/h → tick-only until local midnight + one NM). An exit timer fires a zone-scoped run at `release + grace + 2 s` (one-shot per vacancy episode, live grace at fire time). Periodic cycles wait behind a fast run and never double-run. Kill switch `switch.ura_hvac_coordinator_31_fast_room_response` (default ON) — **scope: OFF stops the fast path ONLY** (room-refresh runs and exit timers); D1 (the evidence release clock), D5 (the transit filter + pending hold), the back-fill and the nudge seed stay ON on the tick; knob 47 = 0 disables D5; D1 is rolled back only by a redeploy. Fast ENTRY runs in every house state (ruling R7: same outcome, sooner); exit timers only in evidence/night states. | `hvac.py`, `switch.py`, `number.py` |
| D5 — transit filter (ruling R3) | Knob 47 (`47 · Entry Wait`, default **1** min, live value stays 0 until the operator sets it) now gates arming on the away → home edge: a cold room arms after 60 s of persisted evidence (episodes join across gaps ≤ min(hold, W)); while a room is pending and the zone is otherwise HVAC-empty, S1 HOLDS the zone's preset in both directions (`preset_change_suppressed` reason `pending_arm_hold`, one row per spell). Room-only return exemption sized by **knob 52 `52 · Return Window (min)`** (default 15, 0–60, 0 = off; ruling R5). Per-room **"Skip entry wait"** (room options, climate step, default off; ruling R6) makes a pulse-only room count at once. A pending-hold spell is **capped at `HVAC_PENDING_HOLD_CAP_S` = 600 s** (ruling R4; one `pending_hold_capped` row per spell). The v4.2.2 lighting-session dwell skip is RETIRED. | `hvac_zones.py` (`_d5_update`), `hvac.py`, `number.py`, `config_flow.py` |
| Ledger | `preset_change` rows carry `trigger` (`periodic` / `house_state` / `pre_arrival` / `fast_entry` / `fast_exit`), `edge_ts`, `zone_empty_since`, `exempt_reason`, `established`, `last_away_reason` (the L15 predicate). | `hvac.py` |
| Labels | `Empty-room hold (day/night)`, `Entry wait (minutes)`, grace helpers, section `Thermostat and empty-room hold` (plain language; both string files identical). | `strings.json`, `translations/en.json` |
| Docs | State of play §2/§3.1/§3.2/§8/§9.5/§9c/§9d; SUPERSEDED banners on the REV 4 fast-path plan and both dwell plans; gap probe `--states` + T 240. | |

## Falsifiable invariants (plan §2)

- **INV-1** fast run == periodic outcome for the zone, within 45 s; non-cold rooms never delayed.
- **INV-2** no `vacant_past_grace` away while any live non-hallway room is active, held, or pending.
- **INV-3** exit run once per `(zone, release)` at `release + G + 2 s`; a pending room reschedules to `ev + J + 2 s` without consuming the key.
- **INV-4** zone scope: climate writes only for Z via S1 (+ Z's vacancy sweep); never the enforcer / egress / nudge / fans / covers / predictor / anomaly / DPM / arrester sweeps / Carrier freshness.
- **INV-5** the shadow runs byte-for-byte on every pass and alone owns `_hvac_armed` / `_hvac_prev_state_occupied` / `_hvac_tail_until`; legacy states unchanged.
- **INV-D5** an unpersisted away-edge episode never writes home while the house stays in an evidence state (any path).

## Tests

- New: `quality/tests/test_hvac_evidence_clock.py` (D1 + stamp), `test_hvac_fast_occupancy_response.py` (D2),
  `test_hvac_transit_filter.py` (D5 + REV 7 ledger/trigger/alarm), `test_hvac_fast_response_fixup1.py` (fix-up round 1:
  rulings R4–R7 + O2, A-MED1/2/3, D-M1/M3, B-M3, Review C 1–4, C LOW anchors, A-LOW-5, B-L1/L3, D-L2); two chained BLE
  tests in `test_ble_hold_cap.py`.
- Updated (plan §11c + two more legacy fakes that needed the evidence surface): `test_hvac_night_hold_follows_sleep.py`,
  `test_zzz_hvac_conditioning_demand.py` (3 tests), `test_hvac_vacancy_hold_ui_defaults.py`,
  `test_hvac_live_room_hold_wire_in.py` (fakes only).
- Every drill row 1–78 executed (see the build report); config extremes: grace 0/10, constrained 3, hold 0, hold < poll,
  day override > night, BLE-only room, camera ghost, ceiling, kill switch mid-flight, two zones same second, restart
  storm, evening → sleep crossing, knob 47 = 0 / 15.

## Checkpoint items (operator, before deploy)

1. Kitchen exception dropped (common-area hold 180 s).
2. Quick-return alarm threshold 12 per zone per day; alarm counts one event per applied vacancy away (O1).
3. D5 room-only return exemption — now knob 52 `52 · Return Window (min)`, default 15 (ruling R5); 0 turns it off.
4. Setting knob 47 to 1 minute (D4) and clearing Jaya Bedroom's day override.
5. Kill-switch scope (B-M4): `31 · Fast Room Response` OFF stops the fast path ONLY (room-refresh runs + exit timers).
   The evidence release clock (D1), the transit filter + pending hold (D5), the back-fill and the nudge seed stay ON on
   the 5-minute tick. Knob 47 = 0 disables D5. D1 is rolled back only by a redeploy.

## Knob inventory (fix-up round 1)

| Knob | Rung | Default / range | Where |
|---|---|---|---|
| `52 · Return Window (min)` (`number`, unique_id `{DOMAIN}_hvac_return_window_minutes`, `CONF_HVAC_RETURN_WINDOW_MINUTES`) — ALSO on the HVAC settings form as `Return window (minutes)` (presence-timing section, next to 47/48/49) | 3 | 15 / 0–60, 0 = off | `number.py`, `config_flow.py`; CM options (reload-suppressed, live push, boot-seeded via the coordinator constructor); reset button |
| `Skip entry wait` (`CONF_HVAC_SKIP_ENTRY_WAIT`, room options, climate step) | 2 | off | `config_flow.py`; read live every producer pass (reload-suppressed) |
| `HVAC_PENDING_HOLD_CAP_S` | 1 | 600 s — effective cap `max(600, W + J)` so one episode is never cut (fix-up 2) | `hvac_const.py`, `hvac.py` |

**Final label inventory (fix-up 2, for the operator's naming review — both string files identical):**
- Room climate step — `hvac_vacancy_hold` label `Empty-room hold (day)`; helper ends: *"From 9 pm until the house goes to sleep, and while the house is away, arriving or has guests, this same number (or, if left blank, a shorter built-in hold) is counted from when the room itself shows as empty instead."*
- Room climate step — `hvac_skip_entry_wait` label `Skip entry wait`; helper: *"For rooms whose sensor only gives short pulses. When on, anyone detected in this room switches a zone set to Away back to Home at once, without the Entry wait. Only matters during the day and evening."*
- HVAC settings — `hvac_zone_entry_dwell` label `Entry wait (minutes)`; helper: *"How long someone must be in a room before heating and cooling switch a zone that is set to Away back to Home, during the day and evening. People passing through faster than this do not switch it. Someone coming back to a room soon after it emptied counts at once (see Return window). Enter 0 to count any sign of someone at once. Recommended: 1."*
- HVAC settings — `hvac_return_window_minutes` label `Return window (minutes)`; helper: *"If someone comes back into a room within this many minutes after its hold ends — and their earlier stay lasted at least the Entry wait — a zone set to Away switches back to Home straight away instead of waiting the Entry wait again. 0 turns this off."*
- Entities — `47 · Entry Wait (min)`, `52 · Return Window (min)` (`number.ura_hvac_coordinator_52_return_window_min`), `31 · Fast Room Response`.
- Mode-sensor attrs — `quick_returns_today` = `same_room_returns_today` + `skip_entry_wait_returns_today` + `other_room_returns_today` (fix-up 2 D-L3).
| `47 · Entry Wait (min)` | 3 | 1 (live 0 until set) | unchanged |
| `31 · Fast Room Response` | 3 | ON | unchanged; scope above |
Plus D0c Gate A (residual re-probe at the ruled values).

## Live acceptance (plan §9) — prospective; write the observed table back after deploy

| # | Check | Pass | Failure looks like |
|---|---|---|---|
| L1 | Entry latency | knob 1: ≥ 90 % of away-edge `fast_entry` rows in `[60, 105] s` after `episode_start`; knob 0: ≤ 45 s | uniform 0–300 s |
| L2 | Exit exactness | every `fast_exit` away row: `row_ts - zone_empty_since` in `[g, g + 50] s` | spread / early |
| L3 | INV-2 | every room `release_at <= row_ts - g`; no pending room at the away | any |
| L4 | Re-arm | same-room return `fast_entry` within 45 s (zone_1 excluded while §9.7 is open) | tick only |
| L5 | Zone scope | no off-zone `climate_write` rows during fast runs; no heat_cool / nudge / cover / fan actions | any |
| L6 | Clock decoupled | `release_at == last_evidence_at + hold`; the `*_hvac_occupied` off transition lands by `release_at + 335 s` | off never precedes lighting off |
| L7 | Night / legacy unchanged | `rule` = `night` / `legacy`; no early release; no legacy back-fill | earlier release |
| L8 | Write rate | per-zone `climate_write`/day ≤ D0b + spread + 10; no ceiling trips | trips |
| L9 | Quick returns | 7-day per-zone `quick_returns_today` within 2× of D0c | much higher |
| L10 | Lifecycle | one listener per room after a room reload and a restart; timers re-armed by the first full cycle | duplicates / missing |
| L11 | Nudge skip | no `ac_ramp_events` `nudge_started` within 120 s of a fast write on that zone | a nudge seconds after a fast write |
| L12 | D5 C1 + C1-D + C3 | `transit_filtered_today` > 0 within 2× of D0c; arm-class split within 2× | ~0 filtered while flaps persist |
| L13 | No short arms | zero away-edge arms with `armed_at - episode_start < 60 s` and no exemption | any |
| L14 | No away with a pending room | zero `vacant_past_grace` aways while `pending_arm_rooms` is non-empty | any |
| L15 | No transit home write | zero S1 `preset_change` rows matching the full predicate (evidence state unchanged since the last applied away, `old_preset == away`, `last_away_reason == vacant_past_grace`, `manual_class == not_manual`, `new_preset` home/sleep, `any_room_hvac_occupied == false`, `trigger` not house_state/pre_arrival, `reason != pre_arrival`, `established == true`) | any such row |

Observability: `sensor.ura_hvac_coordinator_mode` attrs `fast_room_response_enabled`, `fast_entry_runs_today`,
`fast_exit_runs_today`, `fast_writes_today`, `fast_limited_today`, `fast_tripped_zones`, `quick_returns_today`,
`same_room_returns_today`, `other_room_returns_today`, `transit_filtered_today`, `last_fast_edge_to_write_s`; per-room
`binary_sensor.<room>_<room>_hvac_occupied` attrs `rule`, `last_evidence_at`, `evidence_active`, `release_at`,
`hvac_vacancy_hold_s`, and (fix-up 1 A-MED3) `armed` / `source` / `tail_expires_at` that follow the ACTIVE rule (never
contradicting the entity's own on/off; `source` ∈ idle / pending / evidence / shadow sources in legacy+night), the raw
shadow on `shadow_armed` / `shadow_source` / `shadow_tail_expires_at`, and the D5 diagnostics `episode_start`,
`armed_at`, `arm_span_s`, `arm_class`, `pending`, `exempt_reason`, `dwell_s`, `released_at`, `episode_active_s`,
`cold`; zone status attrs `hvac_empty_since`, `hvac_release_at`, `pending_arm_rooms`, `pending_hold_s_today` (accrues
live; the spell closes on any tick whose S1 block is skipped — fix-up 2 D-L1), `transit_filtered_today`; ledger action
`pending_hold_capped` (`held_s`, `cap_s` = `max(600, W + J)`, `pending_rooms`).

## Not done / deferred (accounted for)

- D0 probes: `hvac_raw_evidence_gap_probe.py` gained `--states` and T = 240; the REV 7 D5 replay, the D0a `--latency` +
  flap probe and the grace-probe adaptation are NOT built (measurement-step scripting owned by the orchestrator's D0 run;
  no runtime code depends on them).
- D3 (grace re-check) and D4 (config) are operator steps, not code.
- `current_session_start` DELETE waits for validation (W4), per plan §12.
