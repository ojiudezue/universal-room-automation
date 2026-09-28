# PLANNING: HVAC fast occupancy response (own release clock, transit filter, event-driven entry and exit) — REV 7

**Cards:**
- `HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1` (revived)
- The parked W2 fast path: `HVAC-W2-OCCUPANCY-TRUTH`, plan `PLANNING_hvac_w2_occupancy_fast_path.md` REV 4
- `HVAC-ENTRY-DWELL-ROOM-CLOCK-1` (Stage B, folded in as D5)

Workstream `HVAC-W2-OCCUPANCY-TRUTH`.

**Status:** REV 7. Design confirmed; these are the final D5 text fixes, and D5 goes to the builder after this.

| Rev | What happened |
|---|---|
| REV 1 | Two Tier-3 plan reviews, both FIX-PLAN |
| REV 2 | Folded them |
| REV 3 | Text edits + operator hold rulings R1/R2 |
| REV 4 | Added D5 (ruling R3) |
| REV 5 | Folded the D5 review |
| REV 6 | Folded the D5 re-review |
| REV 7 | Final text fixes |

- Tags: `[REV 2 #n]`, `[REV 3 <id>]`, `[RULING Rn]`, `[REV 4]`, `[REV 5 <id>]`, `[REV 6 <id>]`, `[REV 7 <id>]`.
- Change logs are in §18; departures in §19.
- **Fully self-contained.** No section says "as REV n".

**Checkpoint items needing explicit operator confirmation before deploy:**
1. The Kitchen exception drop (§7.1).
2. The quick-return alarm threshold of 12; the alarm sums same-room returns (orchestrator decision O1) (§5.7, §14.1).
3. The D5 room-only 15-minute return exemption (§5b.3).
4. Setting knob 47 to 1 minute (§10b).

**Base:** current `develop` after v5.103.19 (night-tail B shipped). `hvac.py` has not changed since REV 1.

**Operator decision (2026-09-27 ~22:00, verbatim):** "We wanted faster responses. This is nuts." / "fast path catches
it. The room type hold blunts it. Do it". Rulings R1-R3 and O1 are in §0.6.

**Design premise, with its limits:**
1. A per-room-type hold blunts radar misses of still people. **It is the ONLY protection for someone who stays
   still.** A still person produces no new evidence, so the fast path cannot catch them. It reacts only once they move
   again.
2. An event-driven fast path re-arms a re-detected room in seconds.
3. A pass-through shorter than 60 s does not switch a zone URA set to Away back to Home. D5 filters only that away -> home
   edge. While a room in an otherwise empty zone is deciding whether it is a stay, the zone's preset is HELD.

| Deliverable | What | Code? |
|---|---|---|
| D0 | Baselines (latency, write rate, flap rate), residual + W replay, `home_night` gate probe | probe only |
| D1 | New release clock in `home_day`/`home_evening`; today's machine kept as a shadow; other states unchanged | yes |
| D2 | Event-driven zone decision on entry AND exit | yes |
| D3 | Vacancy grace re-check | knob only |
| D4 | Operator config: clear Jaya Bedroom's day override; set knob 47 to 1 | config |
| D5 | Transit filter on the away -> home edge; knob 47 moves from the lighting-session dwell to this; the lighting-session dwell is retired | yes |

---

## 0. Institutional context verified

### 0.1 Mandatory read
**`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`:** read completely, and re-read for REV 2.
- v5.103.19 night tails follow `HVAC_NIGHT_HOLD_STATES` = (`sleep`, `waking`) (`hvac_const.py:934`). `home_night`
  uses the day table. `FAN_TRUST_STATES` is unchanged.
- W1-B shipped (v5.103.18, §9e four gates).
- §3.2 records the dwell's denomination defect; D5 resolves it.
- Relevant sections: §2, §3.1-§3.3, §9c, §9d, §9.4, §9.7, §10.
- **C18:** with dwell 0, entry means waiting for the next tick.
- **C24:** HVAC occupancy is not a faster clock today; this plan builds one.
- **§10:** no C1-C25 claim is re-asserted.

**Drift to fix in the build commit:**
- §3.2 and §8 values: live grace is 5, constrained 5, dwell 0.
- §3.1 line numbers.
- The §3.2 dwell row -> D5.

### 0.2 Other docs and cards read
| Source | Use |
|---|---|
| Card `HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1` | Disposition; per-type tails; camera/BLE caveat. Kitchen timeout 600 -> 300 s (operator, 2026-09-27, verified live) |
| Card `HVAC-ENTRY-DWELL-ROOM-CLOCK-1` | Arm on persisted raw presence; keep the post-arm hold; hallways excluded by construction; two dwell plans superseded; measure flaps first. Operator 2026-09-26: "Room clock is not good for HVAC" |
| `AUDIT_hvac_raw_evidence_gaps_2026_09_26.md` | Per-type MID/LATE counts; T >= max MID - G; day bucket = `home_day` + `home_evening` (82.4 h); `away`/`arriving`/`guest` excluded (§8.6); `home_night` lumped with `sleep`/`waking` |
| `PLANNING_hvac_w2_occupancy_fast_path.md` REV 4 + card `HVAC-W2-OCCUPANCY-TRUTH` | Reused (§13). The REV 4 re-review HIGHs are known only from the card summary. Card `next` defines the flap metric |
| `AUDIT_hvac_fast_path_rate_2026_09_26.md` | 16.6 zone-cold edges/day; cycle p95 27.6 s; L=60 denies 0/114 |
| `PLANNING_hvac_night_tail_follows_sleep.md` (B shipped) | `HVAC_NIGHT_HOLD_STATES` |
| Other cards | §12 |
| vibememo 153 | Why the fast path was parked |

### 0.3 Code surveyed (develop, post v5.103.19)

**`coordinator.py`**
- Occupancy block `:3538-3643`; `_last_motion_time` set on Tier-1 activity at `:3589`.
- Camera override `:3663-3697` (source `"camera"`, failsafe guard `:3667`).
- BLE `:3699-3908` (source `"ble"`, failsafe guard `:3706`, cap `:3810-3847`).
- Fan-demoted `:4113`; failsafe `:4361`/`:4369`.
- Override switches `:4790-4811`; skip-first `:4825`; `apply_fan_recheck_release` `:5249-5280`.
- Poll `:625-631`; event refresh within 2 s `:1395-1411`; debounce anchor `:3544`; accessor pattern `:5384`.

**`hvac_zones.py`**
- `update_room_conditions` `:566`: entry loop `:611-647`, classify `:665`, zone loop `:666`, `clear()` `:667`,
  absent add `:687`, `room_occupied` `:718`.
- **Hallway exclusion `:725-736`.**
- Rollup `:772-789`; `current_session_start` `:786-789`; zone attrs `:791`.
- `_effective_hvac_hold_seconds` `:977-1049` (clamp `:1031-1047`).
- `_compute_hvac_occupied` `:1051-1126`; `conditioning_retreat_ok` `:1525`; diag `:1588`.

**`hvac.py`**
- `_zones_written_this_cycle` `:455`/`:1879`/`:3194` (read `hvac_override.py:4713`); `_zone_entry_dwell` `:562`.
- `_async_decision_cycle(self, _now=None)` `:1583-1617`, calling `await self._run_decision_cycle()` at `:1617`.
- `_track_task` `:1644`.
- `_run_decision_cycle(self)` `:1873`, calling `await self._apply_house_state_presets()` at `:2017`.
- `_apply_house_state_presets` `:2132-3320`:
  - consensus `:2156`; enforcer `:2227`; arriving `:2261`; grace `:2271-2275`; loop `:2282`
  - **row-1 transient hold `:2360-2399`**:
    - `_fused_empty` `:2360-2365`
    - eligibility `_row1_hold_eligible` `:2383-2387` (target home/sleep, not pre-arrival, house not away/vacation)
    - **`_row1_hold_write = (_transient_blocked_row1 and _fused_empty and _row1_hold_eligible)` `:2388-2392`**
    - branch `:2393`
  - vacancy flip + sweep `:2403-2426`; D6 `:2437`
  - D5 shed/coast `:2568-2733` (clears the row-1 hold at `:2719`)
  - lighting-session dwell `:2735-2748`; D7 `:2780-2852`
  - hold `continue` + episode-gated `preset_change_suppressed` row, latch `_row1_hold_logged_episode` `:2860-2911`
  - W1-B gates `:2918-2996`; S1 write `:3157-3191`; **APPLIED branch `:3192-3198`**
  - `preset_change` row `:3224-3271` (carries `any_room_hvac_occupied` `:3247`, `manual_class` `:3262`); DPM `:3319`
- `_handle_house_state_changed` `:3641-3686` (queues `_async_decision_cycle()` `:3683`).
- `_handle_energy_constraint` `:3843`; `_handle_zm_zones_updated` `:3908` (pops `:3987`, `:4010`).
- `_execute_vacancy_sweep` `:4266`.
- `_handle_person_arriving` `:4567-4622` (queues at `:4620`); `_expire_pre_arrival_zones` `:4624-4654`.
- `_compute_zone_presence_states` `:4775`; `get_mode_attrs` `:5411`; `async_teardown` `:5555`.
- Timer registration `:1374-1379` (`async_track_time_interval(..., self._async_decision_cycle, ...)`); setup call
  `:1382`; boot-settle kick via `async_call_later`.

**Knob 47**
- `number.py:415-502`; `hvac_const.py:416-421`; `config_flow.py:5929-5930`, `:6475-6478`.
- `__init__.py:7379-7390`; `button.py:843-860`; migration `__init__.py:719-757`; strings `:1166`/`:1197`.

**Elsewhere**
- Grace writers outside `number.py`: `button.py:857-858`; `__init__.py:7339/7353/7565`.
- `hvac_strategy.py:142`, `:187-197`, `:254-266`; `hvac_override.py:174`; `sensor.py:13684-13745`.
- HA `update_coordinator.py:170-182`, `:528-533`.

**Live config**
- Jaya Bedroom: day 60 / night 5400. 9 common rooms: night 90. Timeouts 300-900 s.
- `switch.kitchen_override_vacant` is off.

**Tests read**
- `test_hvac_night_hold_follows_sleep.py` (all); `test_hvac_vacancy_hold_ui_defaults.py:140-171`.
- `test_zzz_hvac_conditioning_demand.py:240-331/:505-523/:636-716/:774-775/:903-916`.
- `test_v5_103_8_hvac_knobs_and_obs.py:120-170/:359-430`; `test_hvac_presence_timer_knobs.py`.
- `test_part2_ec_hc_writeback.py`; `test_cm_reload_suppression.py`; `test_dpm_cleanup_and_labels.py:179`.

### 0.4 Config-first check
| Candidate | Solves it? | Why |
|---|---|---|
| Room `occupancy_timeout` | Partly (Kitchen stopgap) | Tick quantization remains; no entry or re-arm effect |
| Per-room holds | No | The hold starts after the lighting timeout today |
| Knob 48 grace | No | §7.2 |
| Shorter `HVAC_DECISION_TICK` | Rejected | Carrier bound; whole-house cycle |
| Jaya day override 60 | **Change (D4)** | Audit MID retreats at 60 |
| Knob 47 as it is today, set to 1 | No | Reads the lighting session; the zone still flips; entry waits for the tick |
| Hallway room type | Already done | `hvac_zones.py:725-736` |

### 0.5 Prior-art scan: REUSE or BUILD
| Piece | Verdict | Symbol / reason |
|---|---|---|
| Evidence hold table | **REUSE, change values** | `ROOM_TYPE_HVAC_HOLD` `const.py:1219` |
| Shadow tail table | **BUILD (frozen, every type explicit)** | `ROOM_TYPE_HVAC_TAIL_LEGACY` |
| Shadow selector | **REUSE unchanged** | `_effective_hvac_hold_seconds` |
| Evidence / display selectors | **BUILD** | `_evidence_hold_seconds`, `_display_hold` |
| Night table, overrides, clamp, flow validation | **REUSE unchanged** | |
| State tuples | REUSE `HVAC_NIGHT_HOLD_STATES`; **BUILD** `HVAC_EVIDENCE_RULE_STATES` | |
| Evidence stamp, active flag, onset | **BUILD (3 fields + 3 accessors)** | No existing field fits |
| Camera/BLE evidence | **REUSE override verdict** | `data[STATE_OCCUPANCY_SOURCE] in ("camera", "ble")` |
| Event source; lifecycle; zone-scoped decision; lock/tasks/timers | **REUSE** | `async_add_listener`; one `SIGNAL_ROOM_ENTRY_LIFECYCLE` subscription; `_apply_house_state_presets(zone_filter, …)`; `_decision_cycle_lock`, `_track_task`, `async_call_later` |
| Pending-arm preset hold | **REUSE pattern (true mirror)** [REV 7 H1] | `_row1_hold_write = transient_blocked and fused_empty and eligible` (`hvac.py:2388-2392`). The sibling is `_pending_arm_hold_write = bool(zone.hvac_pending_arm_rooms) and _fused_empty and _row1_hold_eligible`, riding the same branch, D5-shed clearing and `continue` + row path |
| `trigger` threading | **REUSE call chain** [REV 7 L3] | `_async_decision_cycle` `:1583` -> `_run_decision_cycle` `:1617` -> `_apply_house_state_presets` `:2017` |
| Nudge seed; limiter exemption; away edge | **REUSE + extend** | `_zones_written_this_cycle`; `_zone_last_s1_write` (APPLIED only; `(preset, reason, ts)`) then `last_sent` |
| Pre-arrival membership | **REUSE** | `_pre_arrival_zones` |
| Ledger, attrs, NM, probes | **REUSE** | |
| Kill switch | **BUILD (one switch)** | pattern `switch.py:4229` |
| Dwell knob | **REUSE, semantics moved** | knob 47 |
| Arming episode state | **BUILD** | `_hvac_episode_start`, `_hvac_episode_onsets`, `_hvac_episode_active_s`, `_hvac_arm_span_s`, `_hvac_ev_released_at` |
| Transit exemption window | **BUILD (own knob)** | Knob 52 `CONF_HVAC_RETURN_WINDOW_MINUTES` (fix-up 1 R5; was the constant `HVAC_TRANSIT_EXEMPT_WINDOW_S`, split from the alarm window, Bug Class #63) |
| Lighting-session dwell | **RETIRE** | `hvac.py:2735-2748` |

Memory consulted: suppression-needs-discharge, wire-in anchors, hollow anchors, marginal-benefit,
measure-before-build, coincidental-equality (#63), unrestored-drill, pyc staleness, zone-away-home-night gap.

### 0.6 Decision ledger
| # | Date | Ruling (verbatim) | Effect |
|---|---|---|---|
| R0 | 2026-09-27 ~22:00 | "fast path catches it. The room type hold blunts it. Do it" | Build |
| R1 | 2026-09-27 | "Shorter. I already articulated why it's not a big deal. We're measuring things that don't have the fast and slow protection and we're measuring without the time stacking." | Audit table for holds; Kitchen exception dropped |
| R2 | 2026-09-27 | "3mins" | Common-area evidence hold = 180 s |
| R3 | 2026-09-27 | "I think you should add this to the fast response plan. We want no seams. My instinct is it should go to 1 minute to allow for transients also though hallways are now excluded right?" | D5, 1 minute; hallways excluded |
| O1 (orchestrator) | 2026-09-27 | The quick-return alarm SUMS same-room returns | §5.7 |
| R4 (fix-up 1) | 2026-09-28 | Cap the pending hold: `HVAC_PENDING_HOLD_CAP_S` = 600 s, rung 1; a `pending_hold_capped` ledger row when it fires; tests + drill | §5.2, §14.1; §17 cap item BUILT |
| R5 (fix-up 1) | 2026-09-28 | "I'm most skeptical of the 15m so being a knob feels like a must but please naming and description is important. We have badly named timers all over the place." — the same-room return window is a KNOB: rung 3 Number entity `52 · Return Window (min)`, helper "If someone comes back into a room within this many minutes of it emptying, the zone turns back on straight away instead of waiting the Entry Wait. 0 turns this off.", default 15, range 0–60; the knob-47 helper carries no number | §5b.1, §5b.3, §14 |
| R6 (fix-up 1) | 2026-09-28 | Per-room "Skip entry wait" option (room options, climate step), helper "Turn on for rooms whose sensor only gives short pulses, so anyone detected counts at once. Other rooms still wait the Entry Wait.", default off; reload-suppressed (the producer reads `entry.options` every pass — consumer-proven) | §5b.1, §14 |
| R7 (fix-up 1) | 2026-09-28 | Keep fast ENTRY in ALL house states: the outcome is unchanged (INV-1 — the fast run computes exactly the periodic outcome for that state); it only arrives faster. Exit timers, the evidence rule, D5 and the pending hold stay evidence/night-scoped | §6, §16 |
| R8 (fix-up 1) | 2026-09-28 | No per-sensor-type waits (rejected) | — |
| R9 (post-GO) | 2026-09-28 | "I think it should be shorter. say 5 or 10 ... faster response and more wait time for increased transit debounce." — Return window default 15 → **10** (10 chosen because anything at or below the 5-min vacancy grace does nothing: the window only helps above the grace — effective protection = window − grace) | `DEFAULT_HVAC_RETURN_WINDOW_MINUTES`, §5b.3, §14 |
| R10 (post-GO) | 2026-09-28 | The quick-return alarm is named **"Early return alert"** for users (NM title/text) to avoid confusion with "Return window" — two different windows (15-min alarm vs 10-min mechanism). Internal names and attr keys unchanged | §5.7, §14.2 |
| O2 (operator, D-M2 overruled) | 2026-09-28 | "I think dropping it is right." — the shadow night tail is NOT carried across a night -> evidence crossing. D's repro: Jaya's radar loses her at 06:40 (house asleep, 30-min night tail would hold until ~07:11); `home_day` at 07:00; the evidence rule releases at 06:44, the zone's empty-since is back-filled to 06:44 and the 07:00 tick writes `away` (~07:03 on the live tick cadence). Pinned by `test_night_tail_not_carried_across_crossing_jaya_repro` | §4.3 |

**R1/R2 rationale:** the audit's margins were measured on today's design, with no re-arm and with stacked timers. The
quick-return trip-wire and the kill switch measure and bound the residual live. The trip-wire is the live measure of
the hold choice.

---

## 1. Marginal-benefit note
- The audit weighed release speed alone. The operator added event-driven re-arm, which works only when the person moves.
- Today's machine stays underneath; the new rule runs in the audit-measured states. Holds are rulings; their arithmetic
  is context (§7.2).
- **D5:** away -> home edge only. The cost is 60 s on a genuine arrival into an away zone.
- **Pending-hold duration [REV 7 H1]:**
  - The hold applies only while the zone is otherwise HVAC-empty.
  - A single pending episode holds at most `W + J` (< 2W = 120 s): it either persists within `W` of its start or
    lapses `J` after its last joined evidence.
  - A room that keeps going back to pending (evidence bursts spaced just over `J` apart, e.g. a ghosting sensor) can keep
    re-arming the hold with no upper bound. §7.1 states what that can and cannot block.

---

## 2. Falsifiable invariants

**Definitions**
- `ev(R)`, `active(R)`, `onset(R)`: last evidence, evidence now, start of the current active stretch. `hold_ev(R)`.
- States: evidence (`home_day`, `home_evening`); night (`sleep`, `waking`); legacy = everything else.
- `release(R)`: `ev + hold_ev` (evidence); the later of shadow tail and `ev + hold_ev` (night); shadow tail (legacy).
- `E(Z)`: max `release(R)` over live non-hallway rooms of Z whose current stretch was ARMED. Never-armed episodes are
  excluded.
- `P(Z, t)`: the periodic outcome for Z at `t`.
- `W` = knob 47 × 60 s. `J(R) = min(hold_ev(R), W)`.
- **Away edge:** Z's last APPLIED S1 write was `away` (`_zone_last_s1_write`, else `last_sent`) AND
  `Z not in _pre_arrival_zones`. Unknown -> False.
- **Exempt:** R's last release ended an arm with `arm_span_s >= W` AND was within the Return Window (knob 52,
  `CONF_HVAC_RETURN_WINDOW_MINUTES` × 60; 0 = off) [R5]; OR the room has "Skip entry wait" set [R6]
  (`exempt_reason` = `same_room_return` / `skip_entry_wait`).
- **Cold room:** evidence state AND away edge AND output False AND not exempt.
- **Episode:** onsets each within `J` of the previous `ev`; lapses at `ev + J` unarmed.
- **Persisted:** `W == 0` OR (`active` and `now - episode_start >= W`) OR `ev - episode_start >= W`.
- **Pending room:** a cold room with a live, not-yet-persisted episode.
- **Pending hold** [REV 7 H1]: `bool(zone.hvac_pending_arm_rooms) and fused_empty and eligible` (eligible as at
  `hvac.py:2383-2387`).

**INV-1 (re-arm = periodic outcome within the SLA)**
- Trigger: an evidence advance at `t_r` while Z's stored fused value is False. For a cold room: "persisted became
  true".
- Requirement: a zone-scoped run starts by `t_r + 45 s` and issues exactly `P(Z, t_run)`, for Z only.
- Non-cold rooms are never delayed.

| INV-1 exception | Outcome |
|---|---|
| Row-1 transient-room hold | suppressed row |
| Pending-arm hold | suppressed row |
| D5 shed / D6 stale | effective away |
| W1-B gates on a `manual` zone | `preset_change_deferred` |
| Consensus defer | call skipped |
| `arriving` / egress / observation / zone intelligence off | no write |
| D7 night trust | suppression row |
| §9.7 no-op | `SKIPPED_ALREADY_CORRECT` |
| Kill switch / trip / boot-settle / teardown | tick backstop <= 300 s |
| Cold room not yet persisted | no arm |

**INV-D5 (transit filter)**
- (a) A cold room whose episode never persists never produces `hvac_occupied = True`.
- (b) A cold room that persists produces True by `t_persist + 45 s`.
- (c) D5 never applies in night/legacy states, to hallways, to non-cold rooms, to zones whose last applied write is not
  `away`, or to pre-arrival zones.
- **(d) [REV 7 M2: scoped]** *While the house remains in an evidence state*, an unpersisted episode never causes a
  home/sleep write for Z, by any path (fast run, periodic tick, house-state cycle, exit timer).
  - The pending hold blocks S1 in both directions while Z is otherwise empty — **until the spell reaches the R4 cap**
    (`max(HVAC_PENDING_HOLD_CAP_S, W + J)`, fix-up 2 D-L2): past the cap the vacancy AWAY may proceed (a
    `pending_hold_capped` row is logged); the home/sleep direction stays blocked (unpersisted → not fused-occupied →
    no home write). The cap never bites within one episode.
  - Pending and never-armed episodes never touch `last_occupied_time`.
  - If another room of Z is armed (fused not empty), the hold is not set and Z gets its normal outcome. That room's
    occupancy, not the pending episode, drives the write [REV 7 H1].
  - **Accepted boundary:** when the house leaves the evidence states (e.g. 21:00 `home_evening` -> `home_night`), the
    legacy (shadow) rule decides. A room whose lighting occupancy is still on can arm and write home on that rule even
    if its evidence episode never persisted. This matches today's behaviour in those states and is accepted.

**INV-2 (no early vacancy away, evidence states)**
- No `vacant_past_grace` away for Z at `t` while any live non-hallway room of Z has output True, has an armed
  `release > t - G`, or is pending.
- The pending case is enforced by the pending hold (Z is fused-empty whenever a vacancy away is possible) — **carve-out
  (R4 / fix-up 2 D-L2):** once a pending spell has lasted longer than `max(HVAC_PENDING_HOLD_CAP_S, W + J)` — only
  possible for a CHAIN of episodes that never persisted — the vacancy away is allowed while a room is still pending.
- Duration: see §1 and §7.1.

**INV-3 (exit = periodic outcome, once)**
- The `fast_exit` run starts in `[E + G + SLACK, E + G + SLACK + SLA]`.
- One run per key `(Z, E(Z))`; a deferral consumes the key. `G` is live at fire time.
- A timer that comes due while Z has a pending room reschedules to `ev + J + HVAC_FAST_PATH_EXIT_SLACK_S` of that room
  and does not consume the key [REV 7 L2: never fires before the lapse].

**INV-4 (zone scope)**
- Climate writes only for Z, through S1, plus Z's sweep.
- Accepted house-wide effects: the `zone_presence_state` refresh (display) and `_expire_pre_arrival_zones`.
- Never calls: the enforcer, egress, `check_ac_reset`, fans, covers, predictor, anomaly, DPM, arrester sweeps, Carrier
  freshness.
- Never changes other zones' state.

**INV-5 (shadow, night, legacy)**
- The shadow runs byte-for-byte on every pass and alone owns `_hvac_armed`, `_hvac_prev_state_occupied`,
  `_hvac_tail_until`.
- Night/legacy output is at least the shadow's.
- Legacy states: no back-fill, no exit timer, no D5, no pending hold.
- An evidence-state -> `sleep` crossing stays held.

**Equivalence.** A fast run == `P(Z, t)`. The seeds include writes, every exception row, pending holds, and an armed
room with a pending sibling.

---

## 3. Producer and consumer map

### 3.1 Producer
| Step | After |
|---|---|
| Shadow (every state) | Today's machine on `data["occupied"]`; tail from `_effective_hvac_hold_seconds` |
| Evidence-state output | Non-cold: `active OR now < ev + hold_ev`. Cold: that AND persisted. Refresh-failure hold <= 600 s |
| Night-state output | `shadow OR ev_out` (no D5) |
| Legacy-state output | shadow |
| Zone pending list | `zone.hvac_pending_arm_rooms` (evidence states) |
| Rollup | Over armed rooms. Back-fill `last_occupied_time = max(lot, E)` on a fused-empty pass in evidence/night states. Never-armed episodes never touch `last_occupied_time` |

- Dependency health: 2 s event refresh, 30-35 s poll, existing fusion filters. One firing camera; 3 phones.
- **Side-finding:** the Dining Room radar (`binary_sensor.occupancy_lux_temp_humidity_hobeian_dining_presence`) has not
  been `on` in 24 h. The orchestrator is carding it.

### 3.2 Consumers
| Consumer | Site | Kind | Effect |
|---|---|---|---|
| Zone rollup `any_room_hvac_occupied` | `hvac_zones.py:178` | feeds below | sooner flips; re-arms; cold rooms after 60 s on the away edge |
| `conditioning_retreat_ok` -> row-1 vacancy away | `hvac_zones.py:1525`; `hvac.py:2339-2426` | TRUST | INV-2/INV-3 |
| Pending-arm hold | beside `hvac.py:2388-2392` + `:2860-2911` | TRUST | holds Z's preset while Z is otherwise empty and a room is pending |
| Vacancy sweep | `hvac.py:2416-2426` -> `:4266` | ACTUATION | for Z; not reached while held |
| Row-1 transient hold | `hvac.py:2360-2392`, `:2860-2911` | TRUST | unchanged |
| D6 stale failsafe | `hvac.py:2437-2539` | TRUST | fires less |
| D5 energy-shed | `hvac.py:2568-2733` | TRUST | ends sooner; shed clears both holds |
| D7 night trust | `hvac.py:2780-2852` | TRUST | night >= today |
| D9 compose-away (dormant) | `hvac.py:3484-3518` | TRUST | tick only |
| Arrester row-10 | `hvac_override.py:2513-2557` | TRUST | expires sooner |
| Pre-cool F8 / pre-heat F9 | `hvac_predict.py:583`, `:1420` | TRUST | tick only |
| Grace math | `hvac_zones.py:772-780`; `hvac.py:2340-2344` | TRUST | back-fill over armed rooms |
| `zone_presence_state`; zone-intelligence sensor | `hvac.py:4775`; `sensor.py:13684` | DISPLAY | fast-run cadence |
| W1-B four gates | `hvac.py:2918-2996` | TRUST | same S1 body |
| Arrester nudge skip | `hvac_override.py:4713` | TRUST | seeded from APPLIED writes |
| Lighting-session dwell | `hvac.py:2735-2748` | — | retired |
| Pre-arrival | `hvac.py:4567-4654` | — | full cycle waits behind a fast run; expiry in fast runs; bypasses D5 |
| Fans; presence D6 source 4 | lighting | — | unaffected |
| Per-room display | `binary_sensor.py:745-920` | DISPLAY | attrs `rule`, `last_evidence_at`, `release_at`, `episode_start`, `episode_onsets`, `episode_active_s`, `armed_at`, `arm_span_s`, `dwell_s`, `exempt_reason`, `pending`; `hvac_vacancy_hold_s` via `_display_hold` |
| Zone status | `hvac_zones.py:791-895` | DISPLAY | `hvac_empty_since`, `hvac_release_at`, `pending_arm_rooms`, `pending_hold_s_today` (accrues live during a spell, fix-up 1 A-LOW-5) [REV 7] |
| Mode sensor | `hvac.py:5411` | DISPLAY | per-zone `quick_returns_today`, `same_room_returns_today`, `other_room_returns_today`, `transit_filtered_today` |
| `optimization.py:2398-2430` | `continuous_occupied_since` | analysis | shorter spans |

---

## 4. D1: HVAC's own release clock

### 4.1 Evidence stamp (`coordinator.py`)
- Fields: `_last_hvac_evidence_time`, `_hvac_evidence_active`, `_hvac_evidence_onset`.
- Accessors, next to `:5384`: `get_last_hvac_evidence_time()`, `is_hvac_evidence_active()`, `get_hvac_evidence_onset()`.
- **One stamp site**, after `:4811` and before `:4825`:
  ```
  source = data.get(STATE_OCCUPANCY_SOURCE)
  suppressed = source in (OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED, "failsafe",
                          OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE)
  evidence_now = (not suppressed) and (not self._is_override_vacant()) and (
      any_sensor_active
      or (grace_hold and self._last_occupied_state)
      or source in ("camera", "ble")
      or self._is_override_occupied()
  )
  if evidence_now and not self._hvac_evidence_active:
      self._hvac_evidence_onset = now
  if evidence_now or (self._hvac_evidence_active and not suppressed):
      self._last_hvac_evidence_time = now
  self._hvac_evidence_active = evidence_now
  ```
- A suppressed tick gives no stamp and no falling-edge stamp.
- `apply_fan_recheck_release` clears the active flag without stamping.
- **Camera/BLE count only after the room's own lighting timeout**, since the override blocks run only then.
  - A BLE-only still person can cause a two-write flap where timeout - hold > 300 s:
    - Master Bathroom, Jaya Bathroom, Exercise Room: 720 s
    - Oji Vanity, Study A: 420 s
    - Kitchen Pantry: 380 s
    - Ziri Bathroom, Game Room: 360 s
  - Living Room is 120 s, so no flap.
  - The room exemption makes those re-arms immediate.
- Override Vacant gives no evidence. All fields are in memory only.

### 4.2 Producer (`hvac_zones.py`)
1. **Shadow.** Runs as today with `hold_s` from `_effective_hvac_hold_seconds`. Only the shadow writes `_hvac_armed`,
   `_hvac_prev_state_occupied`, `_hvac_tail_until` and `_hvac_arm_source`.
2. **Evidence term:** `ev_out = evidence_active or (ev is not None and now < ev + hold_ev)`.
3. **Refresh-failure hold** (evidence states, evidence term): if `refresh_ok is False` and the previous output was
   True, stay True for at most 600 s after `ev`.
4. **D5** (evidence states): update the episode.
   - If cold and `W > 0`: `ev_out = ev_out and persisted`; `pending = live and not persisted`.
   - Track `arm_span_s` for every arm.
5. **Output:** evidence `ev_out`; night `shadow_out or ev_out`; legacy `shadow_out`.
   - Store `_hvac_output`, `_hvac_rule`, `_hvac_pending`.
   - Stamp `_hvac_ev_released_at` on an evidence-state True -> False only if `arm_span_s >= W` (or `W == 0`).
   - The evidence branch never writes the shadow dicts.
6. **Zone:** `zone.hvac_pending_arm_rooms`; accumulate `pending_hold_s_today` while the zone's pending hold is set.

Readers use `isinstance(..., datetime)` and `is True`, with `refresh_ok = last_update_success is not False`. The
`active` term covers hold 0 and holds shorter than a poll.

### 4.3 States
- `sleep` / `waking`: shadow OR evidence.
- `home_night`: legacy until Gate B.
- `guest`, `arriving`, `away`, `None`: legacy.

### 4.4 Selectors
| Selector | Returns | Callers |
|---|---|---|
| `_effective_hvac_hold_seconds` (unchanged) | Shadow tail: night table / `ROOM_TYPE_HVAC_TAIL_LEGACY`; overrides; clamp | shadow |
| `_evidence_hold_seconds(room_type, override_day)` | `override_day` or `ROOM_TYPE_HVAC_HOLD.get(type, DEFAULT_HVAC_VACANCY_HOLD)` | evidence term, `J`, `room_release_at` |
| `_display_hold(...)` | `(hold, rule)` | `binary_sensor.py:894` |

The clamp and validation are unchanged.

### 4.5 Release instant
- `room_release_at` reads live accessors. It returns `None` while `active`, or while the shadow rides `occupied`.
- Pending and never-armed rooms are excluded from `E(Z)`.
- Back-fill: on a fused-empty pass in evidence/night states, `last_occupied_time = max(lot, E(Z))` over armed rooms.
- Nothing sets `last_occupied_time` because a room is pending.

### 4.6 Tables (`const.py`, rung 1) [RULING R1, R2]
```
ROOM_TYPE_HVAC_HOLD: Final = {
    ROOM_TYPE_CLOSET: 60, ROOM_TYPE_INFRASTRUCTURE: 60,
    ROOM_TYPE_GENERIC: 120, ROOM_TYPE_UTILITY: 120,
    ROOM_TYPE_MEDIA_ROOM: 120, ROOM_TYPE_GARAGE: 120,
    ROOM_TYPE_BATHROOM: 180,
    ROOM_TYPE_COMMON_AREA: 180,           # ruling R2 "3mins"
    ROOM_TYPE_BEDROOM: 240,
    ROOM_TYPE_HALLWAY: 0,
}
ROOM_TYPE_HVAC_TAIL_LEGACY: Final = {     # FROZEN v5.103.19 day tail, shadow only; every type explicit
    ROOM_TYPE_BEDROOM: 60, ROOM_TYPE_MEDIA_ROOM: 120, ROOM_TYPE_COMMON_AREA: 60,
    ROOM_TYPE_GENERIC: 60, ROOM_TYPE_CLOSET: 60, ROOM_TYPE_BATHROOM: 60,
    ROOM_TYPE_GARAGE: 60, ROOM_TYPE_UTILITY: 60, ROOM_TYPE_INFRASTRUCTURE: 60,
    ROOM_TYPE_HALLWAY: 0,
}
```
The comment on the first table cites the rulings and names the trip-wire as the live check. `DEFAULT_HVAC_VACANCY_HOLD`
(60) is the fallback.

### D1 acceptance
- **Anchors:** `test_evidence_state_ignores_lighting_timeout`; `test_home_evening_to_sleep_mid_timeout_stays_held`
  (drill: the evidence branch writes `_hvac_armed`); `test_shadow_dicts_untouched_by_evidence_branch`;
  `test_home_night_is_legacy_until_gate`; `test_guest_arriving_away_are_legacy`.
- **Holds:** `test_hold_zero_holds_while_active`; `test_hold_shorter_than_poll_no_drop_while_on`;
  `test_refresh_failure_hold_evidence_states_only_and_bounded`.
- **Stamping:** `test_camera_ble_stamp_only_from_override_verdict`;
  `test_no_stamp_on_fan_demoted_failsafe_recheck_sources`; `test_override_vacant_blocks_stamp`;
  `test_falling_edge_refresh_stamps`; `test_fan_recheck_release_clears_active`; `test_ble_cap_stops_stamp_after_cap`.
- **Back-fill:** `test_last_occupied_time_backfilled_to_exact_release`; `test_no_backfill_in_legacy_states`;
  `test_never_armed_episode_excluded_from_e_and_backfill`.
- **Tables:**
  - `test_evidence_hold_values`: independent literals — closet 60, infra 60, generic 120, utility 120, media 120,
    garage 120, bathroom 180, common 180, bedroom 240, hallway 0.
  - `test_legacy_tail_is_frozen_v5_103_19`: every type explicit, independent literals.
  - `test_selectors_split`.
- **Other:** `test_per_room_day_override_wins`; `test_accessor_fallback_uses_isinstance_datetime`.
- **Live:** `release_at == last_evidence_at + hold_ev`; the off transition lands by `release_at + 335 s`.

---

## 5. D2: event-driven decisions

### 5.1 Fast run (never `_run_decision_cycle`)
```
async def _async_zone_fast_run(self, zone_id, trigger, edge_ts=None):
    wrote = False; fused_changed = False
    try:
        if not self._fast_path_gates_open(zone_id, trigger): return
        async with self._decision_cycle_lock:
            if not self._fast_path_gates_open(zone_id, trigger): return
            self._fast_path_running = True
            try:
                fused_before = zone.any_room_hvac_occupied
                zm.update_zone_climate_state(zone_id)
                zm.update_room_conditions(house_state=self._house_state, zone_ids={zone_id},
                                          entry_dwell_s=self._zone_entry_dwell * 60,
                                          away_edge_fn=self._zone_away_edge)
                if self._zone_intelligence_enabled:
                    self._expire_pre_arrival_zones(dt_util.utcnow())
                if not self._observation_mode:
                    wrote = await self._apply_house_state_presets(
                        zone_filter={zone_id}, trigger=trigger, edge_ts=edge_ts)
                if self._zone_intelligence_enabled:
                    self._compute_zone_presence_states(dt_util.utcnow())
                fused_changed = fused_before != zone.any_room_hvac_occupied
                self._schedule_exit_timer(zone_id)
                if wrote or fused_changed:
                    async_dispatcher_send(self.hass, SIGNAL_HVAC_ENTITIES_UPDATE)
            finally:
                self._fast_path_running = False
    finally:
        self._fast_path_queued.discard(zone_id)
```
- `_fast_path_gates_open` = not tearing down, enabled, boot-settle done, kill switch on, not observation mode, zone
  intelligence on, zone in `zm.zones`, zone not tripped.
- `_zone_away_edge(Z)` implements §2. Periodic cycles pass the same function.

### 5.2 `_apply_house_state_presets(*, zone_filter=None, trigger="periodic", edge_ts=None) -> bool`
- **`zone_filter is None`:** byte-identical, except the lighting-session skip (`:2735-2748`) is removed.
- **With a filter:** skip the enforcer (`:2227-2256`); loop-top `continue` for other zones; skip DPM (`:3319-3320`).
  Everything else runs as today, including Z's sweep.
- **Pending-arm hold [REV 7 H1], a true mirror of `_row1_hold_write` (`:2388-2392`):**
  ```
  _pending_arm_hold_write = (
      bool(getattr(zone, "hvac_pending_arm_rooms", ()))
      and _fused_empty                     # same local as :2360-2365
      and _row1_hold_eligible              # same eligibility as :2383-2387
  )
  ```
  - Computed next to `_row1_hold_write`. It takes the same `:2393` branch (skip the vacancy flip: no away) and the same
    `continue` before S1 (no home).
  - D5 shed force-away clears it, as at `:2719`. D6 cannot fire because Z is fused-empty.
  - If another room of Z is armed, `_fused_empty` is False, the hold is not set, and Z's normal outcome is written
    (drill 75).
  - **Suppressed-row latch [REV 7 L1]:** one `preset_change_suppressed` row (reason `pending_arm_hold`, details
    `pending_rooms`, `episode_starts`) per hold spell. The latch `_pending_hold_logged[zone]` is **cleared when the
    hold drops**, so each new spell logs once, and a standing spell logs once, not every tick.
- **`trigger` threading [REV 7 L3]:**
  - `_async_decision_cycle(self, _now=None, *, trigger="periodic")` forwards
    `await self._run_decision_cycle(trigger=trigger)` (`:1617`).
  - `_run_decision_cycle(self, *, trigger="periodic")` forwards
    `await self._apply_house_state_presets(trigger=trigger)` (`:2017`).
  - The periodic timer (`:1374-1379`, called with HA's positional `now`), the setup call (`:1382`) and the boot-settle
    kick keep the default `"periodic"`.
  - `_handle_house_state_changed` (`:3683`) passes `trigger="house_state"`.
  - `_handle_person_arriving` (`:4620`) passes `trigger="pre_arrival"`.
  - This is observability only: all non-fast triggers still run the full site list.
- **Ledger fields on `preset_change`:** `trigger`, `edge_ts`, `zone_empty_since`, `exempt_reason`, `established`,
  `last_away_reason` [REV 7 M1: the reason of Z's last APPLIED away].
- **`_zone_last_s1_write[zone] = (preset, reason, utcnow)` is stamped ONLY in the APPLIED branch (`:3192-3198`).**
- Only an APPLIED `vacant_past_grace` away sets `_zone_vacancy_away_at[zone]`.
- Returns whether a write was applied.

### 5.3 `update_room_conditions(house_state, zone_ids=None, entry_dwell_s=None, away_edge_fn=None)`
- The zone filter runs before `clear()`.
- The absent set is built in the entry loop; the `:687` add is removed.
- `_classify_all_rooms` still covers all rooms.
- D5 inputs are threaded; rollup `hvac_pending_arm_rooms`.

### 5.4 Entry trigger
Setup: subscribe to the lifecycle signal first, then enumerate and attach `async_add_listener`. This is idempotent.

`_on_room_refresh(entry_id, *, from_step=1)`:
1. Gates.
2. Hallway skip; live zone lookup.
3. Evidence advance (`None` rule).
4. D5 episode update. If cold and not persisted: schedule the arm re-check if the zone is cold, then return.
5. Zone-cold gate + tripped check.
6. 60 s limiter. Exempt iff `_zone_last_s1_write[zone][0] == "away"`, else `last_sent == "away"`.
7. Dedup.
8. Queue `fast_entry` (`edge_ts`, `exempt_reason`).

### 5.5 Lock rules
- Fast runs wait for the lock.
- A periodic cycle waits while `_fast_path_running`, skips behind a full cycle, and skips after acquiring if a full
  cycle ran in the meantime.
- Nudge seed: APPLIED S1 writes within 120 s.

### 5.6 Exit timer
- Scheduled after full cycles (all zones) and fast runs (their zone).
- Preconditions: kill switch on, zone intelligence on, not observation mode, established, evidence or night state,
  target home/sleep, not already sent away, not paused, not tripped.
- `due = zone_away_due_at + HVAC_FAST_PATH_EXIT_SLACK_S`. One-shot key `(Z, zone_release_at)`.
- The callback recomputes from live evidence and the live grace:
  - not due -> lazy reschedule;
  - **a pending room in Z -> reschedule to `ev(room) + J(room) + HVAC_FAST_PATH_EXIT_SLACK_S`, key not consumed**
    [REV 7 L2];
  - due -> queue `fast_exit`, exempt from the limiter.
- Hooks only reduce latency. Pruned zones cancel their timers.

### 5.7 Ceiling, runaway guard, quick-return alarm, kill switch, restart
- **Write ceiling:** 6 writes per zone per hour. **Runaway guard:** 30 runs per zone per hour. On breach: NM, then
  tick-only until midnight.
- **Quick-return alarm (O1)**
  - Event: the first `fast_entry` re-arm in Z (exempt or not) after an APPLIED `vacant_past_grace` away, within
    `HVAC_QUICK_RETURN_WINDOW_S`. At most one per away.
  - Per-zone counters: `quick_returns_today` (the alarm count), `same_room_returns_today`, `other_room_returns_today`.
  - At 12 per zone per day: one LOW NM.
  - Windows: the exemption runs from the ROOM's release; the alarm runs from the ZONE's away. They are separate
    constants.
  - The NM text reads its minutes from the constant.
- **Kill switch** `31 · Fast Room Response`: OFF gives tick timing.
- **Global limiter G:** dropped.
- **Restart:** everything is in memory. Rooms start cold. `away_edge` is False until the zone's first APPLIED S1
  write.

### 5.8 Teardown
Set `_tearing_down`. Release listeners, cancel exit and arm timers, and clear the queue before the first await. Every
callback checks `_tearing_down`.

### 5.9 Vacancy sweep
Accepted, not gated. It never precedes the room's own lighting vacancy, and it is not reached while a hold is set.

### D2 acceptance
- **Premise:** `test_rearm_while_lighting_still_on_triggers_fast_entry`; `test_evidence_during_grace_prevents_away`;
  `test_rearm_limiter_exempt_keyed_on_last_sent`; `test_limiter_exemption_order`.
- **Nudge:** `test_fast_write_seeds_nudge_skip_on_next_tick`.
- **Queue/lock:** `test_queue_entry_cleared_on_every_exit_path`; `test_gates_rechecked_after_lock_wait`;
  `test_fast_path_running_only_true_while_holding_lock`.
- **Zone scope:** `test_fast_run_is_zone_scoped` (spies); `test_s1_writes_only_origin_zone`;
  `test_fast_run_sweeps_only_its_zone`; `test_fast_run_leaves_sibling_zones_untouched`;
  `test_absent_set_built_before_zone_loop`.
- **Equivalence:** `test_fast_decision_equals_periodic_decision`.
- **Exit timer:**
  - `test_exit_timer_fires_at_release_plus_grace` (10/3); `test_exit_timer_uses_grace_at_fire_time`;
    `test_exit_timer_reads_live_evidence`; `test_exit_timer_lazy_reschedule`
  - `test_exit_timer_one_shot_under_feed_disagreement`; `test_exit_timer_one_shot_consumed_on_gate_e_deferral`
  - `test_exit_timer_cancelled_on_zone_prune`
  - `test_exit_timer_reschedules_to_pending_lapse_without_consuming_key` (asserts fire time >= `ev + J + SLACK`)
    [REV 7 L2]
- **Listener:** `test_listener_ignores_refresh_without_evidence_advance`; `test_listener_skips_warm_zone`;
  `test_listener_skips_hallway`; `test_entry_limiter_denies_second_run_within_60s`; `test_two_zones_same_second`;
  `test_fp_last_ev_none_rule`; `test_subscribe_then_enumerate_no_miss_no_double`.
- **Lifecycle:** `test_periodic_waits_behind_fast_run`; `test_periodic_skips_behind_full_cycle`;
  `test_waiting_periodic_skips_if_full_cycle_ran`; `test_listener_lifecycle_idempotent`;
  `test_boot_settle_suppresses_fast_path`; `test_teardown_releases_before_first_await`;
  `test_tearing_down_guards_every_callback`.
- **Guards:** `test_write_ceiling_trips_and_clears_at_local_midnight`; `test_runaway_guard_trips_at_31_runs`;
  `test_quick_return_counter_and_nm_latch`; `test_kill_switch_off_restores_tick_only`.
- **Ledger:** `test_preset_change_row_carries_trigger_edge_ts_zone_empty_since`;
  `test_zone_last_s1_write_stamped_only_on_applied`;
  `test_trigger_threads_async_decision_cycle_to_run_to_apply` [REV 7 L3] (house-state handler -> the row says
  `house_state`; periodic timer -> `periodic`); `test_preset_change_row_carries_established_and_last_away_reason`.
- **Boundaries:** grace 0/60; day hold 0; knob 47 = 0/15.

---

## 5b. D5: transit filter on the away -> home edge [RULING R3]

### 5b.1 Rule (evidence states only)
```
away_edge = (_zone_last_s1_write[Z][0] == "away") if Z in _zone_last_s1_write   # APPLIED writes only
            else (strategy_for(...).last_sent(entity, "set_preset_mode") == "away")
away_edge = away_edge and Z not in _pre_arrival_zones
RW        = knob 52 "Return Window (min)" × 60          # live; 0 = off [R5]
exempt    = (RW > 0 and released_at[R] is not None and 0 <= now - released_at[R] <= RW)
            or skip_entry_wait[R]                          # per-room option [R6]
            # released_at = the room's EVIDENCE release (ev + hold) of an arm with arm_span_s >= W
cold      = away_edge and not prev_output[R] and not exempt
if not cold or W == 0:  output = ev_out
else:                   output = ev_out and persisted(R, now)
```
- **Pending room in an otherwise empty zone -> hold** (§5.2).
- **Periodic trace.** Zone 3 is `away`, grace 300, Kitchen hold 180. A 20 s Kitchen transit at t = 0 lapses at 80.
  - Tick 50: pending and fused-empty, so the hold is set; one row, no write.
  - Tick 350: no pending room, `last_occupied_time` untouched and past grace; the zone stays `away`.
  - Under REV 5's `lot = now`, tick 350 would have written `home`.
- **Zone 3 repro.** Bedroom releases at 240, Kitchen entered at 510. The last applied write is `home`, so D5 is off: the
  Kitchen arms at 510 and there is no away at 542.
- **Armed + pending sibling [REV 7 H1].** The zone is `away`, then Study A persists and arms while the Kitchen is still
  pending. Fused is not empty, so the hold is not set and S1 writes `home` because of Study A.
- **Belt.** If `away_edge` is misjudged while Z is Home in grace and empty, a pending room holds and no vacancy away
  lands until the lapse.
- **Scope.** Night has no D5; legacy uses the shadow; hallways never reach this code.
  - Filtered pass-throughs, only while the zone is set to away: Kitchen, Dining Room, Breakfast Nook, Butler Pantry,
    Kitchen Pantry, Laundry, closets.

### 5b.2 Episode tracking
- `J = min(hold_ev, W)`.
- Not cold -> clear.
- No episode, or `onset - prev_ev > J` -> new episode. Otherwise join and accumulate `active_s`.
- `now > ev + J` without arming -> lapse; `transit_filtered_today[Z] += 1`.
- An unarmed episode lives at most `W + J` (< 2W): once joined evidence spans `W`, it persists and arms.
- Examples: a closet 10 s transit lapses at 70; a 90 s stay (pulses 0/50/85) arms at 85; Kitchen pulses 70 s apart are
  never joined.

### 5b.3 Room-only return exemption
- A room whose last release ended an arm of span >= `W` re-arms immediately within the Return Window (knob 52
  `52 · Return Window (min)`, default **10** (R9), 0–60, 0 = off — ruling R5). The window only helps above the vacancy
  grace: a return inside the grace never saw an away in the first place, so the effective protection is
  `window − grace` (10 − 5 = 5 min at the live knobs); a value at or below the grace does nothing.
- A room with "Skip entry wait" (room options, climate step — ruling R6) never waits; `exempt_reason` = `skip_entry_wait`.
  The listener probe honours it too (a skip room's first evidence queues `fast_entry` at once).
- It renews only from such releases, so a ghosting sensor cannot chain it.
- There is no zone-level exemption.
- Exempt re-arms carry `exempt_reason="same_room_return"` and count in the alarm (`same_room_returns_today` within
  `quick_returns_today`).
- **Checkpoint item 3:** "room-only 15-minute return exemption".

### 5b.4 Arm re-check timer
- Fires at `episode_start + W + HVAC_ARM_RECHECK_SLACK_S`.
- Callback: if persisted -> `_on_room_refresh(from_step=5)`; lapsed -> drop; otherwise -> nothing.
- The kill switch and a house-state exit are handled by the gates at fire time; a warm zone stops at step 5.
- Cancelled on lapse, arm, prune, unload and teardown.

### 5b.5 Knob 47 moves; the lighting-session dwell retires
- Remove `hvac.py:2735-2748`. This is behaviour-neutral at the live value 0.
- Default 0 -> 1; the live value stays 0 until the operator sets it.
- Unit stays minutes. 0 = filter off.

### 5b.6 D5 acceptance
**Card criteria**
- **C1:** the 7-day evidence-state flap count is below the D0a baseline. On its own this is not a discriminator.
- **C1-D:** the filter is working if `transit_filtered_today` > 0 at a rate within 2x of D0c, AND the arm-class split
  (clean / joined-transit / exit-pulse) is within 2x of D0c. It is defeated if the filtered count is ~0 while flaps
  persist, or if joined/exit-pulse arms dominate. L15 is the any-path discriminator.
- **C2:** `test_d5_does_not_change_release`.
- **C3:** `test_hallway_never_arms_with_dwell` (construction check).
- **C4:** SUPERSEDED banners on both dwell plans; the card closes as folded.

**Tests**
- **Transit and stay:**
  - `test_transit_under_60s_no_write`: periodic-tick horizon — ticks at 50 (pending), 350, 650 (through
    lapse + G + hold_ev = 560). Asserts no home/sleep write, exactly one `pending_arm_hold` row, and
    `last_occupied_time` unchanged. Includes a Kitchen PIR-pulse variant.
  - `test_stay_60s_writes_within_sla`; `test_intermittent_pir_stay_arms_on_pulse_after_window`.
- **Episodes:** `test_gap_longer_than_join_window_starts_new_episode`;
  `test_joined_transits_within_j_arm_and_are_classified`; `test_episode_lapses_at_ev_plus_j_and_counts_filtered`;
  `test_unarmed_episode_lifetime_below_w_plus_j`.
- **Pending hold:**
  - `test_pending_hold_blocks_both_directions`: (a) zone `away` with a pending Kitchen gets no home write; (b) a stale
    `last_sent` with the zone Home in grace and empty gets no away until the lapse.
  - `test_pending_hold_cleared_by_d5_shed`; `test_pending_hold_not_armed_for_house_away_transition`.
  - **`test_armed_room_with_pending_sibling_still_writes_home`** [REV 7 H1].
  - **`test_pending_hold_row_latched_per_spell_and_relogged_after_drop`** [REV 7 L1].
  - `test_never_armed_episode_excluded_from_e_and_backfill`;
    `test_zone3_repro_no_away_when_kitchen_enters_during_grace`; `test_unarmed_episode_blocks_vacancy_away`.
  - **`test_evidence_to_legacy_boundary_may_write_home_on_legacy_rule`** [REV 7 M2]: pending Kitchen at 20:59:30 in
    `home_evening`; at 21:00 the house goes to `home_night` with the Kitchen lighting still on; the legacy rule arms and
    writes home. Documented and accepted: the test asserts the current behaviour so the acceptance is explicit.
- **D5 scope:** `test_d5_only_on_away_edge`; `test_pre_arrival_zone_bypasses_d5`;
  `test_away_edge_unknown_after_restart_fails_open`.
- **Exemption:** `test_same_room_return_rearms_immediately`; `test_exemption_renews_on_each_release`;
  `test_exemption_not_renewed_by_ghost_blip_chain`; `test_other_room_in_away_zone_waits_w`;
  `test_rearm_after_window_is_cold`.
- **Alarm:** `test_exempt_rearm_counted_once_in_quick_return_alarm`; `test_quick_return_alarm_per_zone_and_sums`;
  `test_quick_return_nm_text_uses_constant`.
- **Stamps:** `test_zone_vacancy_away_at_stamped_only_on_vacant_past_grace`.
- **Scope/knob:** `test_warm_room_no_dwell`; `test_dwell_zero_is_rev3_behaviour`; `test_dwell_only_in_evidence_states`.
- **Re-check:** `test_arm_recheck_scheduled_at_onset_plus_w`; `test_arm_recheck_reenters_at_step_5`;
  `test_arm_recheck_into_warm_zone_stops_at_gate`; `test_arm_recheck_kill_switch_off_no_run`;
  `test_arm_recheck_after_house_state_exit_runs_without_d5`;
  `test_arm_recheck_cancelled_on` × {lapse, arm, prune, unload, teardown}.
- **Other:**
  - `test_exit_run_arms_persisted_room_before_away`.
  - `test_lighting_session_dwell_removed` (behavioural): knob 1, `home_night`, a 20 s-old lighting session, shadow
    armed -> S1 writes.
  - `test_d5_does_not_change_release`; `test_hallway_never_arms_with_dwell` (construction check);
    `test_evidence_onset_accessor`; `test_transit_helper_text_matches_constant`.

**Live:** per-room attributes and mode-sensor counters. For 10 away-edge cold arms, `armed_at - episode_start` falls in
`[60, 105] s`.

---

## 6. Latency budget (before -> after)
| Path | Today (live) | After |
|---|---|---|
| Entry into an away zone, knob 47 = 1 | avg ~2.5-3 min, worst ~5.5 min | 60 s + a few seconds (<= 105 s) |
| Entry into an away zone, knob 47 = 0 | same | usually < 5 s; <= 45 s |
| Entry into a Home / in-grace zone | no write needed | immediate arm |
| Pass-through under 60 s (away zone) | a flap | no write; preset held while pending and the zone is otherwise empty |
| Same-room re-arm after a wrong away | avg ~2.5, worst ~5 min | < 5 s; <= 45 s |
| Other-room entry into a just-away zone | avg ~2.5, worst ~5 min | 60 s + a few seconds |
| Still person | timeout + tail | hold ONLY |
| Exit, `home_day`/`home_evening`, 300 s room | avg ~12.8 min | hold + 5 min: closet/infra 6; generic/utility/media/garage 7; bathroom 8; common 8; bedroom 9 |
| Exit, 900 s room | avg ~22.8 min | bathroom 8 / common 8 |
| Kitchen exit | ~12.8 | 8 |
| `home_night`, `guest`, `arriving`, `away` | avg ~2.5-3 min, worst ~5.5 min | outcome unchanged (legacy rule, INV-1); fast ENTRY arrives within 45 s [R7]. No exit timer, D5 or pending hold |
| `sleep`/`waking` | timeout + night hold + tick | same or later |

- Exits add ~2-5 s.
- A single pending episode holds its zone's preset for less than `W + J`. Repeated re-pending can extend the hold up
  to `HVAC_PENDING_HOLD_CAP_S` (600 s) per spell [R4]; past the cap the vacancy away proceeds and one
  `pending_hold_capped` row is logged (§7.1).

---

## 7. Residual risk (evidence states only)

### 7.1 Audit counts at the ruled values — context, operator-accepted
| Class | Ruled table | Today |
|---|---|---|
| MID | ~13 (Kitchen, common 180) | 0 |
| MID with Jaya 60 | +2 (D4) | 0 |
| LATE | ~36 (Kitchen 29, Dining 2, Master Bath 1, Jaya Bath 1) | 0 |
| Total | ~49 / 6.74 d ≈ 7/day, zone_3 | 0 |

- **Context, not a gate (R1).** A person who does not move stays at away until they do.
- **Kitchen exception dropped:** operator-accepted in spirit; confirm at the checkpoint. 29/36 LATE and all MID are the
  Kitchen; 30/30 Kitchen LATE had evidence elsewhere; the timeout is already 300 s; a config override remains
  available.

**D5 known limitations**
- **Kitchen PIR joined transit:** passes within 60 s that span >= 60 s arm.
- **Exit pulse:** a still entrant who leaves 60+ s later arms as they go.
- **Hobeian 31 s minimum on-time:** two triggers within `J` reach 60 s.
- **Pending-hold duration [REV 7 H1: corrected claim]:**
  - One episode holds for less than `W + J` (<= 120 s).
  - A room that keeps going back to pending (bursts spaced just over `J`, e.g. a ghosting sensor) can keep the zone
    held indefinitely, but only while the zone is otherwise HVAC-empty. Any armed room drops the hold.
  - In the normal case (`away_edge` true: the zone is already `away`), a standing hold blocks only a home write that the
    empty zone should not get, so it costs nothing.
  - In the misjudged-edge case (stale `last_sent`: the zone is Home in grace and empty), it can keep an empty zone at
    Home for as long as the ghosting lasts.
  - Exposure is measured by `pending_hold_s_today` on the zone status sensor and bounded in practice by the stale
    `last_sent` clearing on the next observed divergence (`hvac_strategy.py:195-197`).
- D0c reports each case separately.

**Other D5 residuals**
- 60 s on real arrivals into an away zone.
- A still entrant is treated as a transit until they move.
- Sparse-PIR closets.
- Other-room returns wait 60 s.
- The evidence -> legacy boundary may write home on the legacy rule (INV-D5(d) scope; accepted).

**Unmeasured:** production fusion filters and phantom radars.

**Side-finding:** the Dining radar has been silent for 24 h (orchestrator card).

### 7.2 Context arithmetic (no recommendation)
| Type | Max MID gap | T + G |
|---|---|---|
| common_area | 603 s | 480 s |
| bedroom | 495 s | 540 s |
| generic / utility | 396 / 386 s | 420 s |
| bathroom | 836 s | 480 s (co-occupied) |
| closet | 204 s | 360 s |

Operator-accepted. Knob 49 enters the same sum under coast/shed. The trip-wire is the live measure.

---

## 8. D0: probes
- **D0a** (>= 3 occupied days, earliest 2026-09-30): latency; flap rate; the arming room and its duration.
- **D0b:** `climate_write` baseline, >= 3 days.
- **D0c:** residual + REV 7 D5 replay (away edge, `J`, span-gated exemption, pending hold with the fused-empty
  condition). Report separately:
  - filtered episodes
  - clean / joined-transit / exit-pulse arms
  - pending-hold count, duration and re-pending spells
  - flap reduction
  - release -> re-detection gaps (to size the exemption)
  - quick-return events per zone
  - **Gate A:** blocks deploy.
- **D0c-home_night:** Gate B.

---

## 9. Live acceptance
| # | Check | Pass | Failure looks like |
|---|---|---|---|
| L1 | Entry latency | knob 1: >= 90 % of away-edge `fast_entry` in `[60, 105] s` after `episode_start`; knob 0: <= 45 s | uniform 0-300 s |
| L2 | Exit exactness | `row_ts - zone_empty_since` in `[g, g + 50] s` | spread / early |
| L3 | INV-2 | every room `release_at <= row_ts - g`; no pending room at the away | any |
| L4 | Re-arm | same-room return `fast_entry` within 45 s (zone_1 excluded while §9.7 is open) | tick only |
| L5 | Zone scope | no off-zone writes | any |
| L6 | Clock decoupled | D1 Live | — |
| L7 | Night/legacy unchanged | `rule` night/legacy; no early release; no legacy back-fill | — |
| L8 | Write rate | <= D0b + spread + 10; no trips | — |
| L9 | Quick returns | 7-day per-zone `quick_returns_today` (distinct, exempt + non-exempt) within 2x of D0c | much higher |
| L10 | Lifecycle | one listener per room | — |
| L11 | Nudge skip | none within 120 s of a fast write | — |
| L12 | D5 C1 + C1-D + C3 | §5b.6 | — |
| L13 | No short arms | zero away-edge arms with `armed_at - episode_start < 60 s` and no exemption | any |
| L14 | No away with a pending room | zero `vacant_past_grace` aways while `pending_arm_rooms` is non-empty | any |
| **L15** [REV 7 M1/M2] | **No transit home write** | zero S1 `preset_change` rows matching ALL of: `house_state` in (`home_day`, `home_evening`) and unchanged since Z's last applied away; `old_preset == "away"`; `last_away_reason == "vacant_past_grace"`; `manual_class == "not_manual"`; `new_preset` in (home, sleep); `any_room_hvac_occupied == false`; `trigger` not in (`house_state`, `pre_arrival`); `reason != "pre_arrival"`; `established == true` | any such row means an unpersisted episode (or any other path) wrote home into a vacancy-retreated zone with no HVAC occupancy while the house stayed in an evidence state; the filter is defeated |

L15 is the any-path discriminator alongside C1-D. It is scoped to "while the house remains in an evidence state"; the
evidence -> legacy boundary is excluded by design (§7.1). Results go into the README as a `Validated <date>` table.

---

## 10. D3: vacancy grace re-check
Knob 48, no code. The operator decides after >= 7 days live.

## 10b. D4: config step
- Clear Jaya's day override.
- Set knob 47 to 1 once D5 is live (checkpoint).
- A Kitchen override only if the ruling is reversed.

---

## 11. Tier: 3
**Why:** it touches the still-person safeguard and the arming edge, and adds triggers and timers into the shared lock
and the S1 site; there were two failed plan reviews before.

**Protocol:**
1. Build (the D5 design is confirmed; REV 7 is text fixes).
2. Four parallel reviews: A local correctness; B integration and state machine; C per-site mutation; D adversarial
   completeness.
3. Orchestrator re-grep and re-drill.
4. Operator checkpoint: four items + Gate A.

### 11b. Builder traps
1. Triggering on the lighting edge.
2. Calling `_run_decision_cycle` from a fast run, or not skipping the enforcer/DPM.
3. Zone filter after `clear()`.
4. Absent set inside the filtered loop.
5. Back-fill missing, or applied in legacy states.
6. Stamping from `_last_motion_time`, or only on rising edges.
7. Re-deriving camera/BLE.
8. Rescheduling a fired exit key.
9. Exemption keyed on `preset_mode`.
10. A waiting periodic running a second full cycle.
11. The shadow reading `ROOM_TYPE_HVAC_HOLD`, or removing the clamp.
12. Releasing after the first await.
13. `trigger` only in a counter.
14. The evidence branch writing shadow dicts.
15. `guest`/`arriving`/`home_night` in the evidence states.
16. `finally` placement.
17. Resetting the nudge set to empty.
18. `if ev:` truthiness.
19. Relying on hooks.
20. Stamping on suppressed sources.
21. Refresh hold outside evidence states, or unbounded.
22. Dwell on an exempt room.
23. `onset` from the lighting session or the debounce anchor.
24. Joining beyond `J`, or never lapsing.
25. Leaving the lighting-session skip in place.
26. Dwell in night/legacy states.
27. Re-check for warm zones, or not cancelled.
28. Changing knob 47's unit or unique_id.
29. D5 when the last applied write is not `away`, or in pre-arrival zones.
30. A pending room not blocking a vacancy away.
31. Zone exemption, or a shared window constant.
32. Excluding exempt re-arms from the alarm, or counting one away twice.
33. Re-check queuing directly.
34. `_zone_vacancy_away_at` stamped on non-vacancy aways.
35. Setting `last_occupied_time` because a room is pending.
36. Never-armed episodes in `E(Z)` or the back-fill.
37. The pending hold armed for house-away targets, or not cleared on D5 shed.
38. The exit timer consuming its key while pending.
39. `_zone_last_s1_write` on non-APPLIED results.
40. `released_at` after a short arm.
41. `trigger` not threaded, or `established` missing.
42. **[REV 7 H1]** Dropping `_fused_empty` from the pending hold (it would block a legitimate home write driven by an
    armed room).
43. **[REV 7 L1]** Latching the hold row forever (logs once per boot) or per tick (floods).
44. **[REV 7 L2]** Rescheduling a pending exit timer to exactly `ev + J` (it can fire one refresh before the lapse is
    observed).
45. **[REV 7 L3]** Adding `trigger` to `_async_decision_cycle` but not to `_run_decision_cycle`, or making it
    positional (the timer passes `now` positionally).
46. **[REV 7 M1]** L15 counting rows without the full predicate (e.g. house-state transitions, manual write-throughs,
    zones last set away by house state).

### 11c. Test-file impact
| Test | Result | Disposition |
|---|---|---|
| `test_zzz_hvac_conditioning_demand.py:909` | **RED** | 240; add legacy 60 |
| `test_zzz_hvac_conditioning_demand.py:774-775` | **RED** | default 1 |
| `test_hvac_night_hold_follows_sleep.py:69-79` | **RED** | compare with the legacy table |
| `test_hvac_vacancy_hold_ui_defaults.py:159-172` | **RED** | new wording |
| `test_zzz:246-269/:325-331/:505-523/:636-716` | GREEN | |
| Other night-hold tests | GREEN | `:216-255` guards `isinstance` |
| `test_v5_103_8_hvac_knobs_and_obs.py:127-170/:359-430` | GREEN | |
| `test_hvac_presence_timer_knobs.py` | GREEN (verify `:686`, `:709-710`, `:860-865`) | |
| `test_part2_ec_hc_writeback.py`, `test_cm_reload_suppression.py` | GREEN | |
| `test_dpm_cleanup_and_labels.py:179` | GREEN if both string files change together | |

### 11d. Per-site mutation drill table (table of record)
Every drill neuters the returned value or branch, with bytecode disabled; restore afterwards and confirm `git status`
is clean.

| # | Site | RED test |
|---|---|---|
| 1 | Evidence output returns `shadow_out` | `test_evidence_state_ignores_lighting_timeout` |
| 2 | Evidence branch writes `_hvac_armed = False` | `test_home_evening_to_sleep_mid_timeout_stays_held` |
| 3 | Night drops the shadow | same + `test_night_release_never_before_shadow` |
| 4 | `home_night` in evidence states | `test_home_night_is_legacy_until_gate` |
| 5 | `active` term removed | `test_hold_zero_holds_while_active` |
| 6 | Refresh hold removed / unbounded / in night | `test_refresh_failure_hold_evidence_states_only_and_bounded` |
| 7 | Suppressed check removed | `test_no_stamp_on_fan_demoted_failsafe_recheck_sources` |
| 8 | Camera/BLE term removed | `test_camera_ble_stamp_only_from_override_verdict` |
| 9 | Override-vacant exclusion removed | `test_override_vacant_blocks_stamp` |
| 10 | Falling-edge stamp removed | `test_falling_edge_refresh_stamps` |
| 11 | BLE cap neutered | `test_ble_cap_stops_stamp_after_cap` |
| 12 | Fan recheck leaves active | `test_fan_recheck_release_clears_active` |
| 13 | Back-fill removed | `test_last_occupied_time_backfilled_to_exact_release` + `test_exit_timer_fires_at_release_plus_grace` |
| 14 | Back-fill in legacy states | `test_no_backfill_in_legacy_states` |
| 15 | Filter after `clear()` | `test_fast_run_leaves_sibling_zones_untouched` |
| 16 | Loop-top `continue` removed | `test_s1_writes_only_origin_zone` |
| 17 | Absent set inside the loop | `test_absent_set_built_before_zone_loop` |
| 18 | Enforcer not skipped | `test_fast_run_is_zone_scoped` |
| 19 | DPM not skipped | `test_fast_run_is_zone_scoped` |
| 20 | Lighting-edge listener | `test_rearm_while_lighting_still_on_triggers_fast_entry` |
| 21 | Advance check removed | `test_listener_ignores_refresh_without_evidence_advance` |
| 22 | Zone-cold gate removed | `test_listener_skips_warm_zone` |
| 23 | Hallway skip removed | `test_listener_skips_hallway` |
| 24 | 60 s limiter removed | `test_entry_limiter_denies_second_run_within_60s` |
| 25 | Exemption on `preset_mode` | `test_rearm_limiter_exempt_keyed_on_last_sent` |
| 26 | Registry fallback removed | `test_limiter_exemption_order` |
| 27 | Order swapped / removed | `test_limiter_exemption_order` |
| 28 | Nudge seed `set()` | `test_fast_write_seeds_nudge_skip_on_next_tick` |
| 29 | Queue discard inside the lock | `test_queue_entry_cleared_on_every_exit_path` |
| 30 | Running flag outer | `test_fast_path_running_only_true_while_holding_lock` |
| 31 | Post-lock re-check removed | `test_gates_rechecked_after_lock_wait` |
| 32 | `_tearing_down` guard (per site) | `test_tearing_down_guards_every_callback` |
| 33 | Teardown after await | `test_teardown_releases_before_first_await` |
| 34 | One-shot key not recorded | `test_exit_timer_one_shot_under_feed_disagreement` |
| 35 | Cached evidence | `test_exit_timer_reads_live_evidence` |
| 36 | Scheduled grace | `test_exit_timer_uses_grace_at_fire_time` |
| 37 | Constrained grace removed | 10/3 variant |
| 38 | Not cancelled on prune | `test_exit_timer_cancelled_on_zone_prune` |
| 39 | Waiting periodic doesn't skip | `test_waiting_periodic_skips_if_full_cycle_ran` |
| 40 | Ceiling never trips | `test_write_ceiling_trips_and_clears_at_local_midnight` |
| 41 | Runaway never trips | `test_runaway_guard_trips_at_31_runs` |
| 42 | Alarm never counts | `test_quick_return_counter_and_nm_latch` |
| 43 | `isinstance` -> truthiness | `test_accessor_fallback_uses_isinstance_datetime` + night-hold `:216-255` |
| 44 | Shadow reads `ROOM_TYPE_HVAC_HOLD` | `test_legacy_tail_is_frozen_v5_103_19` + `test_zzz:246-269` |
| 45 | Dwell check removed | `test_transit_under_60s_no_write` (+ PIR variant) |
| 46 | Re-check not scheduled | `test_stay_60s_writes_within_sla` |
| 47 | Room exemption removed | `test_same_room_return_rearms_immediately` |
| 48 | Zone exemption re-added | `test_other_room_in_away_zone_waits_w` |
| 49 | Window unbounded | `test_rearm_after_window_is_cold` |
| 50 | Episode never lapses | `test_episode_lapses_at_ev_plus_j_and_counts_filtered` |
| 51 | Join window uses `hold` | `test_gap_longer_than_join_window_starts_new_episode` |
| 52 | Dwell in night/legacy | `test_dwell_only_in_evidence_states` |
| 53 | Lighting skip left in place | `test_lighting_session_dwell_removed` |
| 54 | Exit run skips D5 | `test_exit_run_arms_persisted_room_before_away` |
| 55a-e | Re-check not cancelled on {lapse, arm, prune, unload, teardown} | `test_arm_recheck_cancelled_on[...]` |
| 56 | Onset re-stamped | `test_evidence_onset_accessor` |
| 57 | `W == 0` removed | `test_dwell_zero_is_rev3_behaviour` |
| 58 | D5 regardless of edge | `test_d5_only_on_away_edge` + zone 3 repro |
| 59 | Pending doesn't block away | `test_unarmed_episode_blocks_vacancy_away` + `test_pending_hold_blocks_both_directions` (b) |
| 60 | Pre-arrival not excluded | `test_pre_arrival_zone_bypasses_d5` |
| 61 | Unknown edge = True | `test_away_edge_unknown_after_restart_fails_open` |
| 62 | Exemption not renewed after a real arm | `test_exemption_renews_on_each_release` |
| 63 | Exempt re-arm excluded / one away counted twice | `test_exempt_rearm_counted_once_in_quick_return_alarm` |
| 64 | Vacancy stamp on any away | `test_zone_vacancy_away_at_stamped_only_on_vacant_past_grace` |
| 65 | Re-check queues directly | `test_arm_recheck_reenters_at_step_5` + `test_arm_recheck_into_warm_zone_stops_at_gate` |
| 66 | Joined-transit misclassified | `test_joined_transits_within_j_arm_and_are_classified` |
| 67 | Pending hold removed | `test_transit_under_60s_no_write` (tick horizon) + `test_pending_hold_blocks_both_directions` (a) |
| 68 | Never-armed in `E`/back-fill, or `lot = now` | `test_never_armed_episode_excluded_from_e_and_backfill` + transit `lot` assert |
| 69 | Hold not cleared by shed / armed for house-away | `test_pending_hold_cleared_by_d5_shed` + `test_pending_hold_not_armed_for_house_away_transition` |
| 70 | Exit timer consumes its key while pending | `test_exit_timer_reschedules_to_pending_lapse_without_consuming_key` |
| 71 | `_zone_last_s1_write` outside APPLIED | `test_zone_last_s1_write_stamped_only_on_applied` |
| 72 | `released_at` after a short arm | `test_exemption_not_renewed_by_ghost_blip_chain` |
| 73 | Alarm global, not per zone | `test_quick_return_alarm_per_zone_and_sums` |
| 74 | `trigger` / `established` / `last_away_reason` missing from the row | `test_trigger_threads_async_decision_cycle_to_run_to_apply` + `test_preset_change_row_carries_established_and_last_away_reason` |
| **75** [REV 7 H1] | **`_fused_empty` dropped from the pending hold** | `test_armed_room_with_pending_sibling_still_writes_home` |
| 76 [REV 7 L1] | Hold-row latch never cleared / not latched | `test_pending_hold_row_latched_per_spell_and_relogged_after_drop` |
| 77 [REV 7 L2] | Pending reschedule without `+ SLACK` | `test_exit_timer_reschedules_to_pending_lapse_without_consuming_key` (fire time >= `ev + J + SLACK`) |
| 78 [REV 7 L3] | `trigger` not forwarded `_async_decision_cycle` -> `_run_decision_cycle` | `test_trigger_threads_async_decision_cycle_to_run_to_apply` |

---

## 12. Sequencing and supersession
- B has shipped; there is no wait gate.
- Banner on the REV 4 fast-path plan.
- The Stage B card is folded; banners on both dwell plans.
- The fan card stays out; recommended as the next cycle (operator to confirm).
- Other cards:
  - `HVAC-HOLD-SIZING-ALL-ROOMS-1` feeds D3/L9.
  - Placeholder readers: unchanged.
  - Write-oracle: one-shot timer; L4 excludes zone_1.
  - Dining radar card (orchestrator).
- Triage: `current_session_start` DELETE after validation (W4); the migration is KEEP + DOCUMENT.
- D0b needs >= 3 days (earliest 2026-09-30).

## 13. REV 4 fast-path findings disposition
| Item | Disposition |
|---|---|
| Re-review HIGHs | Never whole-house; per-zone queue; no enforcer/egress/fan/cover; filter before `clear()` + absent set |
| F1 | D5 re-check |
| F2 | Zone-scoped |
| F3 | Moot |
| F4, F6, F12, F13 | Kept |
| F5 | Lock rules + seed |
| F7, F8 | Row fields |
| F9 | D0b |
| F10 | Ceiling + guard |
| F11 | Refreshed |
| F14 | Mode sensor |
| F15 | Not called |
| Global limiter G | Dropped |

---

## 14. Knobs and labels

### 14.1 Knob ladder
| Number | Value | Rung | Why |
|---|---|---|---|
| `ROOM_TYPE_HVAC_HOLD` | §4.6; common 180 | 1 | R1/R2; trip-wire is the live check |
| `ROOM_TYPE_HVAC_TAIL_LEGACY` | frozen | 1 | Shadow |
| `HVAC_EVIDENCE_RULE_STATES` | (`home_day`, `home_evening`) | 1 | |
| `HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S` | 600 | 1 | 0 disables |
| `HVAC_FAST_PATH_MIN_INTERVAL_S` / `_SLA_S` / `_EXIT_SLACK_S` | 60 / 45 / 2 | 1 | `_EXIT_SLACK_S` also pads the pending reschedule [REV 7 L2] |
| `HVAC_FAST_PATH_MAX_WRITES_PER_ZONE_PER_HOUR` / `_MAX_RUNS_...` | 6 / 30 | 1 | |
| `HVAC_QUICK_RETURN_WINDOW_S` | 900 | 1 | Alarm window from the ZONE's away |
| `HVAC_QUICK_RETURN_NM_PER_DAY` | 12 | 1 | Per zone; distinct events (O1). Checkpoint |
| Knob 52 `52 · Return Window (min)` (`CONF_HVAC_RETURN_WINDOW_MINUTES`) | default 10 (R9), 0–60 | 3 | R5 — from the ROOM's evidence release after a span >= W arm; 0 = exemption off; live (`hvac._return_window_minutes`, in the CM reload-suppress allowlist) |
| `HVAC_PENDING_HOLD_CAP_S` | 600 | 1 | R4 — bounds a pending-hold spell; one `pending_hold_capped` row per spell |
| `CONF_HVAC_SKIP_ENTRY_WAIT` (room options, climate step) | off | 2 | R6 — per-room; reload-suppressed (read live every pass) |
| Knob 47 | default 1 min | 3 | R3; 0 = filter off |
| `HVAC_ARM_RECHECK_SLACK_S` | 1 | 1 | |
| Fast room response switch | ON | 3 | Rollback |
| Knob 48 / 49 | 5 / 5 | 3 | D3 |

### 14.2 Labels
Rules: short config-flow phrase; plain helper text; entity names 3 words max. Banned: tail, HVAC-occupied, clamp, gate,
evidence, tick, fast path, debounce, CRIT, fused, rung, shadow, legacy, dwell, transit, arm, episode.

**Room options, climate step**
- `hvac_vacancy_hold` label: `Empty-room hold (day)`
- `hvac_vacancy_hold` helper: `How many seconds heating and cooling keep treating this room as occupied during the day and evening. The time counts from the last sign of someone in the room, such as motion, presence, a camera or a phone. This covers people sitting still, and it is the only protection for someone who stays completely still. Leave blank to use the default for this room type: 1 minute for closets, 2 minutes for media, utility and general rooms and garages, 3 for bathrooms and living areas, and 4 for bedrooms. Enter 0 to hold only while a sensor still sees someone. From 9 pm until the house goes to sleep, and while the house is away, arriving or has guests, this same number (or, if left blank, a shorter built-in hold) is counted from when the room itself shows as empty instead.`
  - (fix-up 1 A-LOW-6 / fix-up 2 M1: in the legacy states — `home_night`, `away`, `arriving`, `guest` — the shadow tail applies: the per-room override when set, else the frozen `ROOM_TYPE_HVAC_TAIL_LEGACY` (60 s / media 120), counted from the room's lighting-fused empty.)
- `hvac_vacancy_hold_night` label: `Empty-room hold (night)`
- `hvac_vacancy_hold_night` helper: `The hold used while the house is asleep or waking up. It counts from when the room itself shows as empty, so sleepers who lie still get extra time. Leave blank to use the default for this room type: 30 minutes for bedrooms and media rooms, 15 for living areas, 10 for bathrooms, garages and utility rooms, and 5 for closets. Enter 0 for no extra time once the room shows as empty. This form rejects a night value below the day value.`
- Error `hvac_hold_night_below_day`: `The night hold must be at least as long as the day hold. Raise the night value, or leave one of them blank to use the room type's default.`
- Section `climate_backstop` name: `Thermostat and empty-room hold`

**HVAC coordinator options**
- `hvac_vacancy_grace_minutes` helper: `Minutes a zone waits after its last room empties before heating and cooling switch to Away. If someone comes back sooner, nothing changes. A shorter wait saves energy but switches a zone to Away more often while someone sits still.`
- `hvac_vacancy_grace_constrained` helper: `The same wait, used while the house is saving energy. It must be no longer than the normal delay. A shorter wait saves energy but switches a zone to Away more often while someone sits still.`
- `hvac_zone_entry_dwell` label: `Entry wait (minutes)`
- `hvac_zone_entry_dwell` helper [R5]: `How long someone must be in a room before heating and cooling switch a zone that is set to Away back to Home, during the day and evening. People passing through faster than this do not switch it. Someone coming back to a room soon after it emptied counts at once (see Return window). Enter 0 to count any sign of someone at once. Recommended: 1.`
- `hvac_return_window_minutes` form label [fix-up 2 M2]: `Return window (minutes)` — in the `presence_timing` section next to 47/48/49.
- `hvac_return_window_minutes` form helper [fix-up 2 M2]: `If someone comes back into a room within this many minutes after its hold ends — and their earlier stay lasted at least the Entry wait — a zone set to Away switches back to Home straight away instead of waiting the Entry wait again. 0 turns this off.`
  - Carries NO number (the window is knob 52, a live value) — enforced by `test_transit_helper_text_matches_constant`.
- `hvac_skip_entry_wait` label [R6]: `Skip entry wait`
- `hvac_skip_entry_wait` helper [R6, fix-up 2 L8]: `For rooms whose sensor only gives short pulses. When on, anyone detected in this room switches a zone set to Away back to Home at once, without the Entry wait. Only matters during the day and evening.`

**Entities**
- `47 · Entry Wait (min)`.
- `52 · Return Window (min)` (`number.ura_hvac_coordinator_52_return_window_min`, unique_id
  `{DOMAIN}_hvac_return_window_minutes`, 0–60, box, default 10 per R9) — the entity stays alongside the form field (fix-up 2 M2).
- `31 · Fast Room Response` (`switch.ura_hvac_coordinator_31_fast_room_response`, unique_id
  `{DOMAIN}_hvac_fast_room_response`).

**Notifications** (numbers are read from constants at runtime)
- Ceiling: `Fast room response paused for {zone}` / `{zone} changed its heating and cooling setting {n} times in the last hour. Fast response is off for this zone until midnight. The regular 5-minute check still runs.`
- Early return alert (R10; internally the quick-return alarm, attr keys `quick_returns_today` etc. unchanged): `Early return alert: {zone}` / `Early return alert: {zone} switched to Away and someone was back within {window_min} minutes {n} times today. The empty-room hold for a room in this zone may be too short.`
- Runaway: `Fast room response paused for {zone}` / `{zone} ran more checks than expected in the last hour. Fast response is off for this zone until midnight. The regular 5-minute check still runs.`

**Acceptance:** the two string files match; the banned-word check passes; the JSON parses; hassfest passes.

---

## 15. Files
| File | Change |
|---|---|
| `const.py` | Hold tables |
| `coordinator.py` | Stamp, onset, accessors |
| `hvac_zones.py` | Shadow + rule output; D5 (away edge, `J` episodes, span-gated exemption, pending list, `pending_hold_s_today`); selectors; `zone_ids`; absent set; back-fill over armed rooms; release helpers; attrs |
| `hvac.py` | Listeners + lifecycle; `_on_room_refresh(from_step)`; fast run; exit and arm timers (pending reschedule + SLACK); lock rules; nudge seed; `_apply_house_state_presets(zone_filter, trigger, edge_ts)`; pending hold as a true mirror of `:2388-2392` with a per-spell latch; removal of `:2735-2748`; `_zone_away_edge`; APPLIED-only `(preset, reason, ts)` stamp; vacancy-only `_zone_vacancy_away_at`; `trigger` keyword through `_async_decision_cycle` -> `_run_decision_cycle` -> `_apply_house_state_presets`; `established` and `last_away_reason` on the row; ceiling/guard; per-zone alarm; teardown; `get_mode_attrs` |
| `hvac_const.py` | §14.1; `DEFAULT_ZONE_ENTRY_DWELL_MINUTES = 1` |
| `binary_sensor.py` | Attrs |
| `switch.py` | Kill switch |
| `number.py` | Grace setters -> `reschedule_exit_timers()` |
| `strings.json` / `en.json` | §14.2 |
| `quality/tests/` | `test_hvac_evidence_clock.py`, `test_hvac_fast_occupancy_response.py`, `test_hvac_transit_filter.py`; updates per §11c |
| `scripts/probes/` | `--latency` + flap; gap probe `--states`, T 240, REV 7 D5 replay; grace probe |
| Docs | State of play; banners; README |

`config_flow.py` is not changed.

## 16. Non-goals
- No change to night holds or the night anchor.
- No OUTCOME change in `home_night`/`guest`/`arriving`/`away`: no evidence rule, back-fill, exit timer, D5 or pending
  hold there. Fast ENTRY does run in every house state [R7] — the same outcome, sooner.
- The clamp and validation are unchanged.
- No fan/cover/predictor/egress/arrester/DPM/D9 change.
- No change to the tick, grace, or knob 47's unit.
- Hallway exclusion unchanged.
- No new table, writer, sensor or signal.
- No fix for §9.4/§9.7.
- No `current_session_start` removal.
- No D5 on a Home/in-grace zone, and no zone exemption.
- Pending episodes never touch the grace clock.
- No filtering at the evidence -> legacy boundary [REV 7 M2].

## 17. Parked
- Night-anchor unification.
- `home_night` on the evidence rule (Gate B).
- A night/legacy dwell.
- A zone-level exemption.
- ~~A cap on repeated re-pending holds~~ — BUILT in fix-up 1 as `HVAC_PENDING_HOLD_CAP_S` (600 s) per operator ruling R4.

## 18. Change logs

### Fix-up round 1 (2026-09-28, after the four Tier-3 reviews; tag `pre-review-v5.103.20`)
| Item | Change | Where |
|---|---|---|
| R4 | Pending-hold cap 600 s + `pending_hold_capped` row (one per spell; latch closes with the spell) | `hvac.py` S1, §0.6, §6, §14.1, §17 |
| R5 | Return window -> knob 52 `52 · Return Window (min)` (rung 3, live, 0 = off); `HVAC_TRANSIT_EXEMPT_WINDOW_S` deleted; knob-47 helper carries no number | `hvac_const.py`, `number.py`, `__init__.py`, `button.py`, §5b, §14 |
| R6 | Per-room "Skip entry wait" (`CONF_HVAC_SKIP_ENTRY_WAIT`, climate step, reload-suppressed; producer AND listener probe) | `const.py`, `config_flow.py`, strings, `hvac_zones.py`, `__init__.py` |
| R7 | Fast entry in all house states — wording only (outcome unchanged, arrives faster) | §6, §16, README, state of play |
| O2 | D-M2 overruled: the night tail is not carried across a crossing; Jaya repro pinned | §0.6 |
| A-MED1 | Write ceiling counts `fast_entry`/`fast_exit` only | `hvac.py` S1 |
| A-MED2 | Fast-path buckets popped on trip start and on midnight expiry | `hvac.py` |
| A-MED3 | Per-room entity `armed`/`source`/`tail_expires_at` follow the active rule; `shadow_*` + D5 diagnostics exposed | `binary_sensor.py` |
| D-M1 | Coordinator-absent / hallway branches clear the episode + pending; rollup only over rooms classified live this pass; `_on_exit_timer` checks preconditions before the pending branch | `hvac_zones.py`, `hvac.py` |
| D-M3 | `_zone_vacancy_away_at` stamped only when the previous applied write was not `away` (§9.7 re-issue never re-anchors) | `hvac.py` S1 |
| B-M3 | Zone-filtered pass keeps other zones' absent set and classification | `hvac_zones.py` |
| B-M4 | Kill-switch scope documented (README, checkpoint) | docs |
| C 1–5 | Full-cycle exit-timer anchor; real `_run_decision_cycle` stamp; INV-5 per pass; switch OFF restore; deferred-write stamp | tests |
| Fix-up 2 (final) | M1 day-hold helper sentence; M2 knob 52 on the HVAC settings form (label `Return window (minutes)`) + entity kept, knob-47 helper `(see Return window)`, slug `…_52_return_window_min`; M3 boot-seeding test (ctor kwarg, drill M9) + in-place apply test; D-L1 pending spell closes whenever a zone's S1 block is skipped (per-tick seen set; arriving / no target / zone intelligence off / egress pause / observation mode); D-L2 cap = `max(HVAC_PENDING_HOLD_CAP_S, W + J)`; D-L3 `skip_entry_wait_returns_today` split out of `same_room_returns_today`; D-L4 a refresh with no evidence advance (suppressed-source falling edge) re-arms a warm zone's exit timer; D-L5 INV-2 / INV-D5(d) carve-outs; L3 helper test bans any `<n> minute`; L8 skip helper; L9 waking→home_day pin. **L4 / L6 (equivalent mutants, no test):** neutering the `_rooms_processed_this_pass` conjunct of the pending rollup is equivalent to the coordinator-absent clear (an unprocessed room is exactly a room whose clear ran), and neutering `_hvac_cold[room] = False` in the hallway branch is equivalent to the hallway `_hvac_pending = False` (cold without pending has no consumer) — both are noted here per re-review, not anchored | code + tests + docs |
| LOWs | A-LOW-1/2 stale per-pass fields reset; A-LOW-3 exemption anchored on ev + hold; A-LOW-5 live accrual; A-LOW-6 helper; A-LOW-7 annotation + docstring; attr name `hvac_release_at`; B-L1 warm-zone falling edge re-arms the exit timer; B-L3 latch closes on every exit; B-L4 quick return only on a real re-arm; D-L2 shed away booked `energy_shed_cap_reached`; D-L4 carded | code + tests |

### REV 7
| Item | Change | Where |
|---|---|---|
| H1 | Pending hold = `pending and fused_empty and eligible`, a true mirror of `:2388-2392`; armed + pending sibling writes home (test + drill 75); the "delay <= J" claim corrected to "< W + J per episode, unbounded under repeated re-pending, only while otherwise empty"; `pending_hold_s_today` | §0.5, §1, §2, §5.2, §5b.1, §5b.2, §6, §7.1, §11d, §17, §19 #13 |
| M1 | L15 predicate: evidence state, `old_preset == "away"`, last applied away `vacant_past_grace` (`last_away_reason` on the row), `manual_class == "not_manual"`, plus the earlier exclusions | §5.2, §9 |
| M2 | INV-D5(d) and L15 scoped to "while the house remains in an evidence state"; evidence -> legacy boundary write accepted (test) | §2, §7.1, §9, §16 |
| L1 | Hold-row latch cleared when the hold drops (one row per spell); drill 76 | §5.2 |
| L2 | Pending reschedule adds `HVAC_FAST_PATH_EXIT_SLACK_S`; drill 77 | §2 INV-3, §5.6 |
| L3 | `trigger` keyword threaded `_async_decision_cycle` (`:1617`) -> `_run_decision_cycle` (`:2017`) -> `_apply_house_state_presets`; timer/setup/boot keep the default; drill 78 | §0.3, §5.2 |

### REV 6
| Item | Change |
|---|---|
| N1 | `lot = now` replaced by the pending hold; never-armed excluded from `E`/back-fill; INV-D5(d); exit-timer pending reschedule |
| N2 | L15 introduced |
| N5 | Alarm sums same-room returns (O1) |
| N3 | APPLIED-only stamp |
| N4 | Span-gated exemption renewal |
| Structure | File made self-contained |

### REV 5
| Item | Change |
|---|---|
| HIGH-1 | Away edge only |
| HIGH-3 | Room-only exemption, own constant |
| MEDIUM-2 | `J`, limitations, C1-D, Dining side-finding |
| Re-check | Via step 5 |
| Other | Test restructuring; helper tied to the constant |

### REV 4
| Item | Change |
|---|---|
| D5 | Added |
| Knob 47 | Moved |
| Lighting dwell | Retired |
| Hallway site | Confirmed |
| Card criteria | Added |
| Drills | 45-57 |
| R3 | Recorded |

### REV 3
| Item | Change |
|---|---|
| R1/R2 | Holds |
| Threshold | 12 |
| Kitchen | Pending |
| N1-N6 | Folded |
| LOW-1/2/3 | Folded |

### REV 2
| Item | Change |
|---|---|
| Shadow machine | Added |
| Scope | Evidence states only |
| Behaviour | `active` term; nudge seed; sweep; `finally`; invariants |
| Tests | Stamp gating; exit timer; misc |

## 19. Departures and notes
1. `guest` and `arriving` stay legacy.
2. Four existing tests go RED.
3. The clamp and validation are kept.
4. The sweep timing is accepted.
5. The N5 camera/BLE cost is mitigated by the room exemption.
6. The quick-return threshold is 12 (checkpoint).
7. The ~13 MID retreats are accepted context.
8. The exemption is room-only.
9. Knob 47 keeps minutes.
10. The retired dwell's night/legacy coverage.
11. The alarm sums same-room returns (O1).
12. After a restart, `away_edge` is False until the zone's first APPLIED S1 write: at most one unfiltered transit per
    zone per restart.
13. **[REV 7 H1, corrected]** The pending hold applies only while the zone is otherwise HVAC-empty, so it never delays
    a home write driven by an armed room. A single episode holds for less than `W + J`. Repeated re-pending (a ghosting
    sensor) can hold indefinitely. That costs nothing in the normal away-edge case, and in the misjudged-edge case it
    can keep an empty zone at Home. It is measured by `pending_hold_s_today`, and a cap is parked (§17).
14. **[REV 7 M2]** The evidence -> legacy boundary (e.g. 21:00) may write home on the legacy rule for a room whose
    evidence episode never persisted. This is accepted, matches today's behaviour in legacy states, and is covered by
    an explicit test.
