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
| D5 — transit filter (ruling R3) | Knob 47 (`47 · Entry Wait`, default **1** min, live value stays 0 until the operator sets it) now gates arming on the away → home edge: a cold room arms after 60 s of persisted evidence (episodes join across gaps ≤ min(hold, W)); while a room is pending and the zone is otherwise HVAC-empty, S1 HOLDS the zone's preset in both directions (`preset_change_suppressed` reason `pending_arm_hold`, one row per spell). Room-only return exemption sized by **knob 52 `52 · Return Window (min)`** (default **10**, 0–60, 0 = off; rulings R5/R9 — only the part above the 5-min vacancy grace protects). Per-room **"Skip entry wait"** (room options, climate step, default off; ruling R6) makes a pulse-only room count at once. A pending-hold spell is **capped at `HVAC_PENDING_HOLD_CAP_S` = 600 s** (ruling R4; one `pending_hold_capped` row per spell). The v4.2.2 lighting-session dwell skip is RETIRED. | `hvac_zones.py` (`_d5_update`), `hvac.py`, `number.py`, `config_flow.py` |
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
2. "Early return alert" (the quick-return alarm; R10 user-facing name) threshold 12 per zone per day; counts one event per applied vacancy away (O1). NM title `Early return alert: {zone}`.
3. D5 room-only return exemption — now knob 52 `52 · Return Window (min)`, default 10 (rulings R5/R9); 0 turns it off.
4. Setting knob 47 to 1 minute (D4) and clearing Jaya Bedroom's day override.
5. Kill-switch scope (B-M4): `31 · Fast Room Response` OFF stops the fast path ONLY (room-refresh runs + exit timers).
   The evidence release clock (D1), the transit filter + pending hold (D5), the back-fill and the nudge seed stay ON on
   the 5-minute tick. Knob 47 = 0 disables D5. D1 is rolled back only by a redeploy.

## Knob inventory (fix-up round 1)

| Knob | Rung | Default / range | Where |
|---|---|---|---|
| `52 · Return Window (min)` (`number`, unique_id `{DOMAIN}_hvac_return_window_minutes`, `CONF_HVAC_RETURN_WINDOW_MINUTES`) — ALSO on the HVAC settings form as `Return window (minutes)` (presence-timing section, next to 47/48/49) | 3 | 10 / 0–60, 0 = off (R9) | `number.py`, `config_flow.py`; CM options (reload-suppressed, live push, boot-seeded via the coordinator constructor); reset button |
| `Skip entry wait` (`CONF_HVAC_SKIP_ENTRY_WAIT`, room options, climate step) | 2 | off | `config_flow.py`; read live every producer pass (reload-suppressed) |
| `HVAC_PENDING_HOLD_CAP_S` | 1 | 600 s — effective cap `max(600, W + J)` so one episode is never cut (fix-up 2) | `hvac_const.py`, `hvac.py` |

**Final label inventory (fix-up 2, for the operator's naming review — both string files identical):**
- Room climate step — `hvac_vacancy_hold` label `Empty-room hold (day)`; helper ends: *"From 9 pm until the house goes to sleep, and while the house is away, arriving or has guests, this same number (or, if left blank, a shorter built-in hold) is counted from when the room itself shows as empty instead."*
- Room climate step — `hvac_skip_entry_wait` label `Skip entry wait`; helper: *"For rooms whose sensor only gives short pulses. When on, anyone detected in this room switches a zone set to Away back to Home at once, without the Entry wait. Only matters during the day and evening."*
- HVAC settings — `hvac_zone_entry_dwell` label `Entry wait (minutes)`; helper: *"How long someone must be in a room before heating and cooling switch a zone that is set to Away back to Home, during the day and evening. People passing through faster than this do not switch it. Someone coming back to a room soon after it emptied counts at once (see Return window). Enter 0 to count any sign of someone at once. Recommended: 1."*
- HVAC settings — `hvac_return_window_minutes` label `Return window (minutes)`; helper: *"If someone comes back into a room within this many minutes after its hold ends — and their earlier stay lasted at least the Entry wait — a zone set to Away switches back to Home straight away instead of waiting the Entry wait again. 0 turns this off."*
- Entities — `47 · Entry Wait (min)`, `52 · Return Window (min)` (`number.ura_hvac_coordinator_52_return_window_min`), `31 · Fast Room Response`.
- Mode-sensor attrs — `quick_returns_today` = `same_room_returns_today` + `skip_entry_wait_returns_today` + `other_room_returns_today` (fix-up 2 D-L3; keys unchanged by R10).
- Notification (R10) — title `Early return alert: {zone}`; message `Early return alert: {zone} switched to Away and someone was back within {window_min} minutes {n} times today. The empty-room hold for a room in this zone may be too short.`.
| `47 · Entry Wait (min)` | 3 | 1 (live 0 until set) | unchanged |
| `31 · Fast Room Response` | 3 | ON | unchanged; scope above |
Plus D0c Gate A (residual re-probe at the ruled values).

## Validated 2026-09-29 (timed L1–L15)

**Method:** one-shot read-only queries against `ura_activity_log` (`preset_change`, `climate_write` actions) and the HA
recorder, window 2026-09-27 12:00 → 2026-09-29 03:00 CDT (`2026-09-27T17:00:00Z` → `2026-09-29T08:00:00Z`). Restarts at
09-28 19:22, 23:36 and 09-29 03:01 CDT excluded ±~5 min. **The fast-path ledger fields (`trigger`/`edge_ts`/
`zone_empty_since`/`exempt_reason`/`established`/`last_away_reason`) do not appear on any `preset_change` row before
2026-09-28T23:53:15Z (18:53 CDT, the v5.103.20 boot) — 186 of 213 in-window rows predate it and ran the pre-existing
tick-only code.** Only 27 rows in-window carry the ledger (7 `fast_entry`, 6 `fast_exit`, 8 `house_state`, 6 `periodic`),
spanning 18:53 CDT 09-28 → 23:43 CDT 09-28 (v5.103.20/.21/.22); nothing tagged appears between 23:43 CDT 09-28 and the
03:00 CDT cutoff other than a 3-zone simultaneous `house_state` flip at 23:41:21 CDT, 5 min after the 23:36 restart and
excluded as a boot-settle transient. **This is a thin, ~5-hour live sample, not a full occupied day** — several criteria
that need a multi-day baseline (D0b/D0c) are NOT-EXERCISED for lack of one; this pass reports what the mechanism
actually did, not a statistical confirmation.

| # | Check | Result | Evidence |
|---|---|---|---|
| L1 | Entry latency | PASS (mechanism-verified, not per-row `episode_start`-confirmed) | All 7 `fast_entry` rows are away-edges (`last_away_reason=vacant_past_grace`); `sensor.ura_hvac_coordinator_mode.last_fast_edge_to_write_s = 0.0` (edge-to-write is sub-second); knob 47 (`number.ura_hvac_coordinator_zone_entry_dwell`) is live `1`, so D5 requires 60 s of persisted evidence before an away-edge arm — total entry latency ≈ 60 s + ~0 s write dispatch, inside `[60,105] s`. Could not independently pull each event's room-level `episode_start` (the zone_3/zone_2 live-room set beyond the bedrooms in the night-sleeper probe's room list was not resolved in this pass) — flagged, not a full per-row confirmation |
| L2 | Exit exactness | PASS 6/6 | All 6 `fast_exit` rows: `row_ts − zone_empty_since` = 302.8 s, 302.1 s, 303.3 s, 302.9 s, 303.1 s, 302.0 s (grace live 5 min = 300 s + 2 s slack ⇒ expected ≈302 s; window `[300,350]`) |
| L3 | INV-2 | PASS (vacuous — no opportunity to violate) | `sensor.ura_hvac_coordinator_zone_2_status`/`_zone_3_status` sampled at every state-change in-window (746 / 618 rows): `pending_arm_rooms` empty at every sample. No `vacant_past_grace` away coincided with a pending room because no pending room existed in-window (the mechanism first engaged after the window — zone_3 `pending_arm_rooms=['Breakfast Nook']` as of the query, post-cutoff) |
| L4 | Re-arm | NOT-EXERCISED | No same-room return landed inside 45 s in-window; closest zone_3 `fast_exit→fast_entry` gaps were 61 s and 106 s. `same_room_returns_today = {}` (zero) on the mode sensor. No qualifying event to test |
| L5 | Zone scope | PASS (spot-checked, not row-by-row exhaustive) | `climate_write` site breakdown for the window (`S1_reason_ladder` 209+13, `B1_heat_cool_enforcer` 111, `S5_nudge_start` 39, `S6/S7_nudge_restore*` 91, `S12_pre_cool` 11, `S3_compromise` 4, `S4_revert*` 11, `auto_return:banking*` 9, `B5/B6_ac_reset*` 6) is consistent with the expected zone-scoped funnels; no anomalous cross-domain action names present |
| L6 | Clock decoupled | PASS (supported by L2) | The exit fires at exactly `release + grace + 2 s` per L2, confirming `zone_empty_since` (`release_at`) is computed from the evidence clock, not the legacy lighting timeout |
| L7 | Night/legacy unchanged | PASS | Sampled `binary_sensor.<room>_hvac_occupied` attrs: `rule=legacy` for zone_2 bedrooms during `home_night` (correct — `home_night` is not in `HVAC_NIGHT_HOLD_STATES`, so shadow/legacy applies); `rule=night` for zone_3 guest rooms during `sleep` (correct — D8 table applies only in `sleep`/`waking`). No early release or legacy back-fill anomaly seen |
| L8 | Write rate | NOT-EXERCISED (no D0b baseline read this pass); ceiling sub-check PASS | `fast_writes_today = 12`, `fast_limited_today = 0`, `fast_tripped_zones = []` — no zone tripped the 6/h or 30/h runaway ceiling |
| L9 | Quick returns | NOT-EXERCISED (no D0c baseline read this pass) | `quick_returns_today = {'zone_2': 1}` — far under the 12/day "Early return alert" threshold, but no 7-day D0c baseline was pulled to size "within 2×" |
| L10 | Lifecycle | NOT-EXERCISED | No duplicate-write or missing-timer symptom observed (`fast_limited_today=0`), but listener-count verification needs log inspection not done in this read-only pass |
| L11 | Nudge skip | PASS | 5 `S5_nudge_start` climate_write rows in-window (zone_1 ×2, zone_3 ×3); nearest to any zone_3 fast write is 25–34 min away — none within 120 s |
| L12 | D5 diagnostics vs D0c | NOT-EXERCISED (transit filter never engaged in-window) | `transit_filtered_today = 0` for the whole in-window period (first non-zero value, zone_3 = 7, appears only after the 03:00 cutoff, under v5.103.23) |
| L13 | No short arms | PASS (vacuous) | Zero pending-arm activity in-window (see L3); no arm bypassed the 60 s wait — consistent with `last_fast_edge_to_write_s=0.0` and no exemption rows logged |
| L14 | No away with a pending room | PASS | Same evidence as L3 — no `vacant_past_grace` away ever coincided with a non-empty `pending_arm_rooms` |
| L15 | No transit home write | PASS | Zero rows match the full predicate: every in-window `home`/`sleep` write tagged `fast_entry` or `periodic` off an `away` edge shows `any_room_hvac_occupied=true` — a real occupied room backed every one, none at `false` |

**Churn vs. fast-path verdict (09-28 preset-change volume, 49–64 writes/zone, board groom note):** decomposes into two
sources, NEITHER of which is new flapping introduced by this release. (1) Zone_1 shows ~35 repeated `home→away`
re-writes 12:08–17:43 CDT while the CONFIG feed never actually held `away` — this is the pre-existing, already-documented
`HVAC-ZONE1-MANUAL-OSCILLATION-1` / §9.7 status-feed-oscillation defect, unrelated to v5.103.20. (2) Zone_2/zone_3 show
several sub-10-minute `fast_exit→fast_entry` pairs (e.g. zone_3 00:04:43→00:05:44, 61 s; 03:01:48→03:06:33, 285 s;
04:17:27→04:25:37, 490 s) — these are genuine quick room transits resolved correctly by the D5/D2 machinery (exit fires
at grace-exactness per L2, re-entry re-arms per the away-edge W-gate), not oscillation: `same_room_returns_today={}` and
`quick_returns_today={'zone_2':1}` sit far under the 12/day alarm. **Verdict: fast-path working as designed** (faster,
more granular entries/exits than the old 5-min tick would have produced), with the elevated raw count mostly
attributable to the pre-existing zone_1 defect plus more numerous but individually correct fast writes.

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

## Live validation — boot, 2026-09-28 (HACS v5.103.20, HA restarted 18:45 CDT; URA loaded 18:54)

| # | Check | Result | Evidence |
|---|---|---|---|
| — | Installed code | PASS | PR #592 carries hvac_zones.py / hvac.py / coordinator.py / hvac_const.py; host manifest v5.103.20; `_evidence_rule_output` present in installed hvac_zones.py |
| — | Zero URA ERRORs at boot | PASS | system_log ERROR filter on `universal_room_automation`: none |
| — | New settings live | PASS | `number.ura_hvac_coordinator_52_return_window_min` = 10; `switch.ura_hvac_coordinator_31_fast_room_response` present; `number.ura_hvac_coordinator_zone_entry_dwell` set to **1** by the orchestrator (operator-approved checkpoint item 4) and verified |
| — | Evidence rule active in home_evening | PASS | house `home_evening`; Kitchen / Living Room `rule=evidence`, hold 180 s (common, R1); Master Bedroom `rule=evidence`, hold 240 s |
| — | Zones establish on live rooms | PASS | zone_1/2/3 status: `live_rooms` 12/14/14, `pending_arm_rooms` [], `transit_filtered_today` 0 |
| L1–L15 | Timed behaviour checks | PENDING | evaluated by one-shot DB/recorder query after the first full occupied day (2026-09-29 evening) — not a soak |
