# PLANNING: HVAC fast occupancy response (own release clock, transit filter, event-driven entry and exit) — REV 6

**Cards:**
- `HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1` (revived)
- the parked W2 fast path (`HVAC-W2-OCCUPANCY-TRUTH`, plan `PLANNING_hvac_w2_occupancy_fast_path.md` REV 4)
- `HVAC-ENTRY-DWELL-ROOM-CLOCK-1` (Stage B, folded in as D5)

Workstream `HVAC-W2-OCCUPANCY-TRUTH`.

**Status:** REV 6.
- REV 1: two Tier-3 plan reviews, both FIX-PLAN.
- REV 2: folded them.
- REV 3: text edits + operator hold rulings R1/R2.
- REV 4: added D5 (ruling R3).
- REV 5: folded the focused D5 review.
- REV 6: folds the D5 re-review (FIX-PLAN; design direction holds).

Tags: `[REV 2 #n]`, `[REV 3 <id>]`, `[RULING Rn]`, `[REV 4]`, `[REV 5 <id>]`, `[REV 6 <id>]`. Change logs: §18.
Departures: §19.

**This file is fully self-contained.** No section says "as REV n": earlier revisions were never committed, so every
detail is inline.

**Checkpoint items needing explicit operator confirmation before deploy:**
1. Kitchen exception drop (7.1).
2. Quick-return alarm threshold 12. The alarm sums same-room returns (orchestrator decision O1) (5.7, 14.1).
3. D5 room-only 15-minute return exemption (5b.3).
4. Setting knob 47 to 1 minute (10b).

**Base:** current `develop` after v5.103.19 (night-tail B shipped). `hvac.py` unchanged since REV 1.

**Operator decision (2026-09-27 ~22:00, verbatim):** "We wanted faster responses. This is nuts." / "fast path catches
it. The room type hold blunts it. Do it". Rulings R1-R3 and orchestrator decision O1: §0.6.

**Design premise, with its limits:**
1. A per-room-type hold blunts radar misses of still people. **It is the ONLY protection for someone who stays
   still.** A still person produces no new evidence, so the fast path cannot catch them; it reacts only once they move
   again.
2. An event-driven fast path re-arms a re-detected room in seconds, not at the next 5-minute tick.
3. A pass-through under 60 s does not switch a zone URA set to Away back to Home. D5 filters only that away -> home
   edge. While a room is still deciding whether it is a stay, its zone's preset is HELD in both directions
   [REV 6 N1].

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
- **`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`:** read completely; re-read for REV 2.
  - v5.103.19: night tails follow `HVAC_NIGHT_HOLD_STATES` = (`sleep`, `waking`) (`hvac_const.py:934`); `home_night`
    uses the day table; `FAN_TRUST_STATES` unchanged.
  - W1-B shipped (v5.103.18, §9e four gates).
  - §3.2 records the dwell's denomination defect (it reads the LIGHTING clock); D5 resolves it.
  - Relevant: §2, §3.1-§3.3, §9c, §9d, §9.4, §9.7, §10.
- **C18:** with dwell 0, entry = wait for the next tick.
- **C24:** HVAC occupancy is not a faster clock today; this plan builds one.
- **§10:** no C1-C25 claim is re-asserted (no 1-minute tick C8; suppression 15 s temp / 120 s preset C17/C23; S1
  manual guard superseded C25).
- **Drift to fix in the build commit:**
  - §3.2 (knob 48 = 10) and §8 (dwell = 2) are stale; live values are grace 5, constrained 5, dwell 0.
  - §3.1 line numbers are pre-B.
  - The §3.2 dwell row -> D5.

### 0.2 Other docs and cards read
| Source | Use |
|---|---|
| Card `HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1` | Disposition; per-type tails; `_last_motion_time` misses camera/BLE. Kitchen timeout 600 -> 300 s (operator, 2026-09-27, verified live) |
| Card `HVAC-ENTRY-DWELL-ROOM-CLOCK-1` | Arm only when raw presence persists N s; keep the post-arm hold; hallways excluded by construction; two dwell plans superseded; measure flaps first. Operator 2026-09-26: "Room clock is not good for HVAC" |
| `AUDIT_hvac_raw_evidence_gaps_2026_09_26.md` | Per-type MID/LATE; T >= max MID - G. Day bucket = `home_day` + `home_evening` (82.4 h). Excludes `away`/`arriving`/`guest` (§8.6). `home_night` lumped with `sleep`/`waking` |
| `PLANNING_hvac_w2_occupancy_fast_path.md` REV 4 + card `HVAC-W2-OCCUPANCY-TRUTH` | Reused (§13). The REV 4 re-review HIGHs are known only from the card summary. Card `next` defines the flap metric |
| `AUDIT_hvac_fast_path_rate_2026_09_26.md` | 16.6 zone-cold edges/day; cycle p95 27.6 s; L=60 denies 0/114 |
| `PLANNING_hvac_night_tail_follows_sleep.md` (B shipped) | `HVAC_NIGHT_HOLD_STATES` |
| Other cards | §12 |
| vibememo 153 | Why the fast path was parked |

### 0.3 Code surveyed (develop, post v5.103.19)
**`coordinator.py`**
- Occupancy block `:3538-3643`; `_last_motion_time` on Tier-1 activity `:3589`.
- Camera override `:3663-3697`: source `"camera"`, failsafe guard `:3667`.
- BLE `:3699-3908`: source `"ble"`, failsafe guard `:3706`, cap `:3810-3847`.
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
- `_async_decision_cycle` `:1583`; `_track_task` `:1644`; `_run_decision_cycle` `:1873`.
- `_apply_house_state_presets` `:2132-3320`:
  - consensus `:2156`; enforcer `:2227`; arriving `:2261`; grace choice `:2271-2275`; loop `:2282`
  - **row-1 transient hold `:2360-2399`**: `_row1_hold_write = transient_blocked and fused_empty and eligible`;
    eligibility at `:2383-2387` (target home/sleep, not pre-arrival, house not away/vacation); skips the vacancy flip
    at `:2393`
  - row-1 vacancy flip + sweep `:2403-2426`; D6 `:2437`
  - D5 shed/coast `:2568-2733` (clears the row-1 hold at `:2719`)
  - lighting-session dwell `:2735-2748`; D7 `:2780-2852`
  - **hold `continue` + episode-gated `preset_change_suppressed` row `:2860-2911`**
  - W1-B gates `:2918-2996`; S1 strategy write `:3157-3191`
  - **APPLIED branch `:3192-3198`**
  - `preset_change` row `:3224-3271` (already carries `any_room_hvac_occupied` `:3247`); DPM `:3319`
- `_handle_house_state_changed` `:3641-3686` (queues `_async_decision_cycle()` at `:3683`).
- `_handle_energy_constraint` `:3843`; `_handle_zm_zones_updated` `:3908` (pops `:3987`, `:4010`).
- `_execute_vacancy_sweep` `:4266`.
- `_handle_person_arriving` `:4567-4622` (queues a cycle `:4620`); `_expire_pre_arrival_zones` `:4624-4654`.
- `_compute_zone_presence_states` `:4775`; `get_mode_attrs` `:5411`; `async_teardown` `:5555`.

**Knob 47**
- `number.py:415-502` (`47 · Entry Wait (min)`, MINUTES, 0-15, step 1, BOX); `hvac_const.py:416-421`.
- `config_flow.py:5929-5930`, `:6475-6478`; in-place apply `__init__.py:7379-7390`; reset `button.py:843-860`.
- Migration `__init__.py:719-757` (DONE live); strings `:1166`/`:1197`.

**Elsewhere**
- Grace writers outside `number.py`: `button.py:857-858`; `__init__.py:7339/7353/7565`.
- `hvac_strategy.py`: `strategy_for` `:254-266` (registry miss -> uncached generic); `last_sent` `:142`; no-op `:187-197`.
- `hvac_override.py:174` (`SUPPRESS_TTL_SECONDS_PRESET = 120`); `sensor.py:13684-13745` (zone-intelligence sensor).
- HA `update_coordinator.py:170-182`, `:528-533`.

**Live config**
- Jaya Bedroom day 60 / night 5400; 9 common rooms night 90.
- Timeouts 300 s for most rooms, up to 900 s.
- `switch.kitchen_override_vacant` restores `off`.

**Tests read**
- `test_hvac_night_hold_follows_sleep.py` (all); `test_hvac_vacancy_hold_ui_defaults.py:140-171`.
- `test_zzz_hvac_conditioning_demand.py:240-331/:505-523/:636-716/:774-775/:903-916`.
- `test_v5_103_8_hvac_knobs_and_obs.py:120-170/:359-430`; `test_hvac_presence_timer_knobs.py`.
- `test_part2_ec_hc_writeback.py:446/:633/:727/:1142`; `test_cm_reload_suppression.py`;
  `test_dpm_cleanup_and_labels.py:179`.

### 0.4 Config-first check
| Candidate | Solves it? | Why |
|---|---|---|
| Room `occupancy_timeout` | Partly (Kitchen stopgap) | Still two tick quantizations; no effect on entry or re-arm |
| Per-room holds | No | The hold starts after the lighting timeout today |
| Knob 48 grace (5) | No | §7.2 |
| Shorter `HVAC_DECISION_TICK` | Rejected | Carrier call-rate bound; whole-house cycle |
| Jaya day override 60 | **Change (D4)** | Under the new clock it counts from the last evidence; audit MID retreats at 60 |
| Knob 47 as it is today, set to 1 | No | Reads the lighting session (~300 s for a 10 s transit), so the zone still flips; delays entry to the tick |
| Hallway room type | Already done | `hvac_zones.py:725-736`; D5 targets non-hallway pass-throughs |

### 0.5 Prior-art scan: REUSE or BUILD
| Piece | Verdict | Symbol / reason |
|---|---|---|
| Evidence hold table | **REUSE, change values** | `ROOM_TYPE_HVAC_HOLD` `const.py:1219` |
| Shadow tail table | **BUILD (frozen, every type explicit)** | `ROOM_TYPE_HVAC_TAIL_LEGACY` |
| Shadow selector | **REUSE unchanged** | `_effective_hvac_hold_seconds` |
| Evidence / display selectors | **BUILD** | `_evidence_hold_seconds`, `_display_hold` |
| Night table, overrides, clamp, flow validation | **REUSE unchanged** | `const.py:1230-1253`; `hvac_zones.py:1031-1047`; `config_flow.py:599-610` |
| State tuples | REUSE `HVAC_NIGHT_HOLD_STATES`; **BUILD** `HVAC_EVIDENCE_RULE_STATES` | |
| Evidence stamp, active flag, onset | **BUILD (3 fields + 3 accessors)** | No existing field fits (`_last_motion_time`, `_last_trigger_time`, `_last_occupied_time`, `_occupancy_first_detected`) |
| Camera/BLE evidence | **REUSE the override verdict** | `data[STATE_OCCUPANCY_SOURCE] in ("camera", "ble")` |
| Room-change event source | **REUSE HA API** | `async_add_listener`; pattern `aggregation.py:1990` |
| Listener lifecycle | **REUSE** | one `SIGNAL_ROOM_ENTRY_LIFECYCLE` subscription; subscribe, then enumerate |
| Zone-scoped decision | **REUSE + parameterise** | `_apply_house_state_presets(zone_filter, trigger, edge_ts)`, `update_room_conditions(zone_ids, …)` |
| Lock, tasks, timers | **REUSE** | `_decision_cycle_lock`, `_track_task`, `async_call_later` |
| **Pending-arm preset hold** [REV 6 N1] | **REUSE pattern** | `_row1_hold_write` (`hvac.py:2360-2399`, `:2719`, `:2860-2911`); sibling flag `_pending_arm_hold_write`, reason `pending_arm_hold` |
| Nudge seed; limiter exemption; away edge | **REUSE + extend** | `_zones_written_this_cycle`; `_zone_last_s1_write` (APPLIED only [REV 6 N3]) then `strategy_for(...).last_sent` |
| Pre-arrival membership | **REUSE** | `_pre_arrival_zones` |
| Ledger, attrs, NM, probes | **REUSE** | `preset_change` details; `get_mode_attrs`; `get_zone_status_attrs`; `hvac_occupied_diag`; NM path; `scripts/probes/` |
| Kill switch | **BUILD (one switch)** | pattern `HVACPreArrivalSwitch` `switch.py:4229` |
| Dwell knob | **REUSE, semantics moved** | knob 47; unit stays minutes |
| Arming episode state | **BUILD** | `_hvac_episode_start`, `_hvac_episode_onsets`, `_hvac_episode_active_s`, `_hvac_arm_span_s`, `_hvac_ev_released_at` |
| Transit exemption window | **BUILD (own constant)** | `HVAC_TRANSIT_EXEMPT_WINDOW_S`, split from `HVAC_QUICK_RETURN_WINDOW_S` (Bug Class #63) |
| Lighting-session dwell | **RETIRE** | `hvac.py:2735-2748` |

Memory consulted: suppression-needs-discharge, wire-in anchors, hollow anchors, marginal-benefit,
measure-before-build, coincidental-equality (#63), unrestored-drill, pyc staleness, zone-away-home-night gap.

### 0.6 Decision ledger
| # | Date | Ruling (verbatim) | Effect |
|---|---|---|---|
| R0 | 2026-09-27 ~22:00 | "fast path catches it. The room type hold blunts it. Do it" | Build |
| R1 | 2026-09-27 | "Shorter. I already articulated why it's not a big deal. We're measuring things that don't have the fast and slow protection and we're measuring without the time stacking." | Audit table for holds; Kitchen exception dropped |
| R2 | 2026-09-27 | "3mins" | Common-area evidence hold = 180 s |
| R3 | 2026-09-27 | "I think you should add this to the fast response plan. We want no seams. My instinct is it should go to 1 minute to allow for transients also though hallways are now excluded right?" | D5, 1 minute; hallways excluded (confirmed) |
| O1 (orchestrator) | 2026-09-27 | The quick-return alarm SUMS same-room returns | §5.7 |

**R1/R2 rationale (the operator's, as recorded):**
- The audit's margins were measured on today's design, with no re-arm fast path and with stacked timers.
- The quick-return trip-wire and the kill switch measure and bound the residual live. The trip-wire is the live measure
  of the hold choice.

---

## 1. Marginal-benefit note
- The audit weighed release speed alone. The operator added event-driven re-arm, which helps only when the person moves
  again.
- Today's machine stays underneath, and the new rule runs only in audit-measured states. Holds are rulings; their
  arithmetic is context (§7.2).
- **D5** acts on the away -> home edge only.
  - Cost: 60 s on a genuine arrival into an away zone.
  - A pending room holds its zone's preset at most `J` (<= 60 s) after its last evidence.

---

## 2. Falsifiable invariants

**Definitions**
- `ev(R)`: last evidence. `active(R)`: evidence at the latest refresh. `onset(R)`: start of the current active stretch.
- `hold_ev(R)`: from `_evidence_hold_seconds`.
- States: evidence (`home_day`, `home_evening`); night (`sleep`, `waking`); legacy = all others.
- `release(R)`:
  - evidence states: `ev + hold_ev`
  - night: the later of the shadow tail end and `ev + hold_ev`
  - legacy: the shadow tail end
- **`E(Z)`:** max `release(R)` over live non-hallway rooms of Z whose current stretch was ARMED. Never-armed episodes
  (pending or lapsed unarmed) are excluded [REV 6 N1].
- `P(Z, t)`: what a periodic cycle would write for Z at `t` (possibly nothing).
- `W` = knob 47 × 60 s. `J(R) = min(hold_ev(R), W)`.
- **Away edge:** Z's last APPLIED S1 write was `away` (`_zone_last_s1_write`, else `last_sent`) AND
  `Z not in _pre_arrival_zones`. Unknown -> False.
- **Exempt:** R's last release (a) ended an arm with `arm_span_s >= W` [REV 6 N4] and (b) was within
  `HVAC_TRANSIT_EXEMPT_WINDOW_S`.
- **Cold room:** evidence state AND away edge AND output False AND not exempt.
- **Episode:** onsets each within `J` of the previous `ev`; lapses at `ev + J` unarmed.
- **Persisted:** `W == 0` OR `(active and now - episode_start >= W)` OR `ev - episode_start >= W`.
- **Pending room:** a cold room with a live, not-yet-persisted episode.

**INV-1 (re-arm = periodic outcome within the SLA)**
- Trigger: a live non-hallway room of Z has an evidence advance at `t_r` while Z's stored fused value is False. For a
  cold room the trigger is "persisted became true" (listener, or arm re-check).
- Required: a zone-scoped run for Z starts by `t_r + 45 s` and issues exactly `P(Z, t_run)`, for Z only. Non-cold rooms
  are never delayed by D5.

| INV-1 exception | Outcome |
|---|---|
| Row-1 transient-room hold | suppressed row |
| **Pending-arm hold** [REV 6] | suppressed row (`pending_arm_hold`) |
| D5 shed / D6 stale | effective away |
| W1-B gates (a/b), (c), (d), (e) on a `manual` zone | `preset_change_deferred` |
| Consensus defer gate | call skipped |
| `arriving`, egress pause, observation mode, zone intelligence off | no write |
| D7 night trust | suppression row |
| §9.7: status already reads the target and `last_sent` matches | `SKIPPED_ALREADY_CORRECT` |
| Kill switch off, zone tripped, boot-settle, teardown | tick backstop <= 300 s |
| Cold room not yet persisted | no arm |

**INV-D5 (transit filter)**
- (a) A cold room whose episode never persists never produces `hvac_occupied = True`.
- (b) A cold room that persists produces True by `t_persist + 45 s`.
- (c) D5 never applies in night or legacy states, to hallways, to non-cold rooms, to zones whose last applied write is
  not `away`, or to pre-arrival zones.
- **(d) [REV 6 N1] An unpersisted episode never causes a home/sleep write for Z, by any path** (fast run, periodic tick,
  house-state cycle, exit timer).
  - While any room of Z is pending, S1 holds Z's preset in both directions (`_pending_arm_hold_write`).
  - Pending and never-armed episodes never touch `last_occupied_time`.
  - When an episode lapses unarmed, Z's grace clock is exactly as it was.

**INV-2 (no early vacancy away, evidence states)**
- No `vacant_past_grace` away for Z at `t` while any live non-hallway room of Z:
  - has output True; or
  - has an armed release with `release > t - G`; or
  - is pending.
- The pending case is enforced by the pending-arm hold. It replaces REV 5's `last_occupied_time = now`, which made the
  tick write home during grace.
- Bounded by `J` after the last evidence.

**INV-3 (exit = periodic outcome at the due time, once)**
- A `fast_exit` run starts in `[E + G + SLACK, E + G + SLACK + SLA]` and issues `P(Z, t_run)`.
- One run per episode, key `(Z, E(Z))`. A deferral consumes the key.
- `G` is the live grace when the timer fires.
- A timer that comes due while Z has a pending room reschedules lazily to that room's `ev + J`, without consuming the
  key [REV 6 N1].

**INV-4 (zone scope)**
- A fast run writes climate only for Z, through S1, plus Z's vacancy sweep.
- Accepted house-wide effects: the display-only `zone_presence_state` refresh, and `_expire_pre_arrival_zones`
  (time-driven; the next tick would do the same).
- It never calls the heat_cool enforcer, egress tick, `check_ac_reset`, fans, covers, predictor, anomaly observations,
  DPM, arrester sweeps or the Carrier freshness check.
- It never changes another zone's room conditions or rollup fields.

**INV-5 (shadow, night, legacy)**
- Today's machine runs byte-for-byte on every pass and alone owns `_hvac_armed`, `_hvac_prev_state_occupied` and
  `_hvac_tail_until`.
- Night and legacy output is at least the shadow's.
- Legacy states: no back-fill, no exit timer, no D5, no pending hold.
- An evidence-state -> `sleep` crossing mid-lighting-timeout stays held by the shadow.

**Equivalence.** A fast run for Z at `t` equals `P(Z, t)`. Seeds must include S1 writes (home from away, away from
home, sleep, manual write-through under open gates), every exception row, and pending holds. A seed set with no write
fails the test's own precondition.

---

## 3. Producer and consumer map

### 3.1 Producer
| Step | After |
|---|---|
| Shadow (every state) | Today's machine on `data["occupied"]`; tail from `_effective_hvac_hold_seconds` |
| Evidence-state output | Non-cold: `active OR now < ev + hold_ev`. Cold: that AND persisted. Refresh-failure hold <= 600 s after `ev` |
| Night-state output | `shadow OR active OR now < ev + hold_ev` (no D5) |
| Legacy-state output | shadow |
| Zone pending list | `zone.hvac_pending_arm_rooms` (evidence states) [REV 6] |
| Rollup | As today, over armed rooms. Back-fill `last_occupied_time = max(lot, E)` on a fused-empty pass in evidence/night states. **Never-armed episodes never touch `last_occupied_time`** [REV 6] |

- **Dependency health:** event-driven refresh within 2 s, 30-35 s poll, existing fusion filters. One firing camera
  (Living Room); 3 phones.
- **Side-finding:** `binary_sensor.occupancy_lux_temp_humidity_hobeian_dining_presence` (Dining Room radar) has not been
  `on` in 24 h. The orchestrator is carding it.

### 3.2 Consumers
| Consumer | Site | Kind | Effect |
|---|---|---|---|
| Zone rollup `any_room_hvac_occupied` | `hvac_zones.py:178` | feeds below | sooner flips; re-arms; cold rooms after 60 s on the away edge |
| `conditioning_retreat_ok` -> row-1 vacancy away | `hvac_zones.py:1525`; `hvac.py:2339-2426` | TRUST | INV-2/INV-3 |
| **Pending-arm hold** | beside `hvac.py:2360-2399` + `:2860-2911` | TRUST | holds Z's preset while a room is pending |
| Vacancy sweep | `hvac.py:2416-2426` -> `:4266` | ACTUATION (Z's lights/fans) | for Z; not reached while held |
| Row-1 transient hold | `hvac.py:2360-2392`, `:2860-2911` | TRUST | unchanged |
| D6 stale failsafe | `hvac.py:2437-2539` | TRUST | fires less |
| D5 energy-shed coast defer | `hvac.py:2568-2733` | TRUST | ends sooner; shed clears both holds |
| D7 night trust | `hvac.py:2780-2852` | TRUST | night >= today |
| D9 compose-away (dormant) | `hvac.py:3484-3518` | TRUST | tick only |
| Arrester row-10 comfort delay | `hvac_override.py:2513-2557` | TRUST | expires sooner in an emptied zone |
| Pre-cool F8 / pre-heat F9 | `hvac_predict.py:583`, `:1420` | TRUST | tick only |
| Grace math | `hvac_zones.py:772-780`; `hvac.py:2340-2344` | TRUST | back-fill over armed rooms |
| `zone_presence_state`; zone-intelligence sensor | `hvac.py:4775`; `sensor.py:13684` | DISPLAY | fast-run cadence |
| W1-B four gates | `hvac.py:2918-2996` | TRUST | same S1 body |
| Arrester nudge skip | `hvac_override.py:4713` | TRUST | seeded from recent APPLIED S1 writes |
| Lighting-session dwell | `hvac.py:2735-2748` | — | retired |
| Pre-arrival | `hvac.py:4567-4654` | — | full cycle waits behind a fast run; expiry in fast runs; bypasses D5 |
| Fans; presence D6 source 4 | `hvac_fans.py:761/:997`; `presence.py:2147-2159` | LIGHTING | unaffected |
| Per-room `binary_sensor.<room>_<room>_hvac_occupied` | `binary_sensor.py:745-920` | DISPLAY | attrs `rule`, `last_evidence_at`, `release_at`, `episode_start`, `episode_onsets`, `episode_active_s`, `armed_at`, `arm_span_s`, `dwell_s`, `exempt_reason`, `pending`; `hvac_vacancy_hold_s` via `_display_hold` |
| Zone status sensor | `hvac_zones.py:791-895` | DISPLAY | `hvac_empty_since`, `away_due_at`, `pending_arm_rooms` |
| `sensor.ura_hvac_coordinator_mode` | `hvac.py:5411` | DISPLAY | counters incl. per-zone `quick_returns_today`, `same_room_returns_today`, `other_room_returns_today`, `transit_filtered_today` |
| `optimization.py:2398-2430` | `continuous_occupied_since` | analysis | shorter spans |

---

## 4. D1: HVAC's own release clock

### 4.1 Evidence stamp (`coordinator.py`)
- **Fields:** `_last_hvac_evidence_time`, `_hvac_evidence_active`, `_hvac_evidence_onset`.
- **Accessors** (next to `:5384`): `get_last_hvac_evidence_time()`, `is_hvac_evidence_active()`,
  `get_hvac_evidence_onset()`.
- **One stamp site**, after `:4811`, before `:4825`:
  ```
  source = data.get(STATE_OCCUPANCY_SOURCE)
  suppressed = source in (OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED, "failsafe",
                          OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE)
  evidence_now = (not suppressed) and (not self._is_override_vacant()) and (
      any_sensor_active                                  # after all fusion filters
      or (grace_hold and self._last_occupied_state)
      or source in ("camera", "ble")                     # the override blocks' own verdict this tick
      or self._is_override_occupied()
  )
  if evidence_now and not self._hvac_evidence_active:
      self._hvac_evidence_onset = now
  if evidence_now or (self._hvac_evidence_active and not suppressed):   # falling-edge stamp
      self._last_hvac_evidence_time = now
  self._hvac_evidence_active = evidence_now
  ```
- A suppressed tick gives no stamp and no falling-edge stamp on the next tick.
- `apply_fan_recheck_release` (`:5249`) sets `_hvac_evidence_active = False` without stamping.
- **Camera/BLE count only after the room's own lighting timeout** (the override blocks run only then, with their
  failsafe guards, the BLE chain rule and the cap).
  - A BLE-only still person can cause a two-write flap where timeout - `hold_ev` > 300 s: Master Bathroom 720,
    Jaya Bathroom 720, Exercise Room 720, Oji Vanity 420, Study A 420, Kitchen Pantry 380, Ziri Bathroom 360,
    Game Room 360.
  - Living Room: 120 s, no flap.
  - The room exemption makes those re-arms immediate.
- Override Vacant gives no evidence (§9c text updated in the build). All fields are in memory and cleared on restart.

### 4.2 Producer: shadow plus rule output (`hvac_zones.py`)
`_compute_hvac_occupied` keeps its body as the shadow and gains `last_evidence`, `evidence_active`, `onset`,
`refresh_ok`, `entry_dwell_s`, `away_edge` keywords.

1. **Shadow.** As today (`:1073-1126`), with `hold_s` from `_effective_hvac_hold_seconds`. It alone writes
   `_hvac_armed`, `_hvac_prev_state_occupied`, `_hvac_tail_until`, `_hvac_arm_source`. Result: `shadow_out`.
2. **Evidence term.** `ev_out = evidence_active or (last_evidence is not None and now < last_evidence + hold_ev)`.
   Store `_hvac_day_release_at`.
3. **Refresh-failure hold** (evidence states, evidence term only). If `refresh_ok is False` and the previous output
   was True, keep True for at most `HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S` = 600 s after `last_evidence` (longest hold
   240 + ~10 polls). Night/legacy: the shadow rides stale data, as today.
4. **D5 (evidence states).**
   - Update the episode (§5b.2).
   - If cold and `W > 0`: `ev_out = ev_out and persisted`; `pending = episode live and not persisted`.
   - Track `arm_span_s` for every evidence-state arm: `ev - first onset of the armed stretch` [REV 6 N4].
5. **Output.**
   - evidence: `ev_out`; night: `shadow_out or ev_out` (no D5); legacy: `shadow_out`.
   - Store `_hvac_output`, `_hvac_rule`, `_hvac_pending`.
   - On an evidence-state True -> False, stamp `_hvac_ev_released_at` **only if `arm_span_s >= W` (or `W == 0`)**
     [REV 6 N4].
   - The evidence branch never writes the shadow's dicts.
6. **Zone rollup:** `zone.hvac_pending_arm_rooms = [pending rooms]`.

Readers use `isinstance(..., datetime)` (a MagicMock counts as `None`) and `is True`;
`refresh_ok = last_update_success is not False`. The `active` term covers hold 0 and holds shorter than a poll.

### 4.3 States
- `sleep` / `waking`: shadow OR evidence (no D5).
- `home_night`: legacy until D0c Gate B.
- `guest`, `arriving`, `away`, `None`: legacy (unmeasured).

### 4.4 Selectors
| Selector | Returns | Callers |
|---|---|---|
| `_effective_hvac_hold_seconds` (unchanged) | Shadow tail: night table in night states, `ROOM_TYPE_HVAC_TAIL_LEGACY` otherwise; overrides; clamp | shadow only |
| `_evidence_hold_seconds(room_type, override_day)` | `override_day` or `ROOM_TYPE_HVAC_HOLD.get(type, DEFAULT_HVAC_VACANCY_HOLD)` | evidence term, `J`, `room_release_at` |
| `_display_hold(room_type, house_state, override_day, override_night)` | `(hold, rule)`, rule in `evidence` / `night` / `legacy` | `binary_sensor.py:894` |

The clamp and flow validation are unchanged. The shadow's night >= legacy-day comparison matches today (common night
90 >= 60); the night OR gives monotonicity against the evidence hold.

### 4.5 Release instant [REV 6 N1]
- **`room_release_at(room)`** reads the live accessors. It returns `None` while `active`, or while the shadow rides
  `occupied` (night/legacy).
- Pending and never-armed rooms are **excluded** from `E(Z)`. They neither contribute nor make `E(Z)` `None`; the
  pending hold (§5.2) and the exit-timer pending reschedule (§5.6) cover them.
- **Back-fill:** on a fused-empty pass in evidence/night states, `last_occupied_time = max(lot, E(Z))` over armed rooms.
- No rule sets `last_occupied_time = now` for a pending room (the REV 5 rule is removed: it made the tick write home
  during grace, which is the transit flap).

### 4.6 Tables (`const.py`, rung 1) [RULING R1, R2]
```
ROOM_TYPE_HVAC_HOLD: Final = {            # evidence rule; audit table + operator rulings
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
The comment cites the rulings and names the trip-wire as the live check. `DEFAULT_HVAC_VACANCY_HOLD` (60) is the
unknown-type fallback.

### D1 acceptance
- **Anchors**
  - `test_evidence_state_ignores_lighting_timeout`
  - `test_home_evening_to_sleep_mid_timeout_stays_held` (drill: evidence branch writes `_hvac_armed`)
  - `test_shadow_dicts_untouched_by_evidence_branch`
  - `test_home_night_is_legacy_until_gate`, `test_guest_arriving_away_are_legacy`
- **Holds:** `test_hold_zero_holds_while_active`, `test_hold_shorter_than_poll_no_drop_while_on`,
  `test_refresh_failure_hold_evidence_states_only_and_bounded`.
- **Stamping**
  - `test_camera_ble_stamp_only_from_override_verdict`
  - `test_no_stamp_on_fan_demoted_failsafe_recheck_sources`
  - `test_override_vacant_blocks_stamp`, `test_falling_edge_refresh_stamps`
  - `test_fan_recheck_release_clears_active`, `test_ble_cap_stops_stamp_after_cap`
- **Back-fill:** `test_last_occupied_time_backfilled_to_exact_release`; `test_no_backfill_in_legacy_states`;
  `test_never_armed_episode_excluded_from_e_and_backfill`.
- **Tables:** `test_evidence_hold_values` (closet 60, infra 60, generic 120, utility 120, media 120, garage 120,
  bathroom 180, common 180, bedroom 240, hallway 0; independent literals); `test_legacy_tail_is_frozen_v5_103_19`
  (every type explicit; independent literals); `test_selectors_split`.
- **Other:** `test_per_room_day_override_wins`, `test_accessor_fallback_uses_isinstance_datetime`.
- **Live:** in `home_day`, `release_at == last_evidence_at + hold_ev`, and the off transition lands by
  `release_at + 335 s`. Under the old rule it could never precede the lighting off.

---

## 5. D2: event-driven decisions

### 5.1 Fast run (never `_run_decision_cycle`)
```
async def _async_zone_fast_run(self, zone_id, trigger, edge_ts=None):
    wrote = False; fused_changed = False
    try:
        if not self._fast_path_gates_open(zone_id, trigger): return
        async with self._decision_cycle_lock:
            if not self._fast_path_gates_open(zone_id, trigger): return      # re-check after the wait
            self._fast_path_running = True                                  # only while holding the lock
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
        self._fast_path_queued.discard(zone_id)                             # every exit path
```
- `_fast_path_gates_open`: not tearing down, enabled, boot-settle done, kill switch on, not observation mode, zone
  intelligence on, zone in `zm.zones`, zone not tripped.
- `_zone_away_edge(Z)` implements §2. Periodic cycles pass the same function.

### 5.2 `_apply_house_state_presets(*, zone_filter=None, trigger="periodic", edge_ts=None) -> bool`
- `zone_filter is None`: byte-identical to today, except the lighting-session dwell skip (`:2735-2748`) is removed.
- With a filter: skip the heat_cool enforcer (`:2227-2256`); loop-top `continue` for other zones (`:2282`); skip DPM
  (`:3319-3320`). Consensus gate, `arriving`, every per-zone rule and Z's sweep run as today.
- **Pending-arm hold [REV 6 N1]**, a sibling of `_row1_hold_write`:
  - loop top: `_pending_arm_hold_write = bool(zone.hvac_pending_arm_rooms) and eligible`, same eligibility as
    `:2383-2387` (target home/sleep, zone not pre-arrival, house not away/vacation), so real house-state away/vacation
    transitions still land;
  - while set: skip the row-1 vacancy flip (no away), and reach the hold `continue` (`:2860-2911`) before S1 (no home);
  - D5 shed force-away clears it, as at `:2719`; D6 cannot fire (fused False);
  - one episode-gated `preset_change_suppressed` row per `(zone, house_state, target)`, reason `pending_arm_hold`,
    details `pending_rooms`.
- **`trigger` threading [REV 6 N2]:** `_handle_house_state_changed` (`:3683`) passes `trigger="house_state"`; pre-arrival
  (`:4620`) passes `trigger="pre_arrival"`. Observability only; both still run the full site list.
- **Ledger fields** on `preset_change`: `trigger`, `edge_ts`, `zone_empty_since`, `exempt_reason`, `established`
  [REV 6 N2].
- **`_zone_last_s1_write[zone] = (preset, utcnow)` is stamped ONLY in the APPLIED branch (`:3192-3198`)** [REV 6 N3].
  It is not stamped on `SKIPPED_ALREADY_CORRECT`, DEFERRED, FAILED, a hold, or a W1-B deferral.
- Only an APPLIED `vacant_past_grace` away sets `_zone_vacancy_away_at[zone]`.
- Returns whether a write was applied.

### 5.3 `update_room_conditions(house_state, zone_ids=None, entry_dwell_s=None, away_edge_fn=None)`
- `zone_ids`: skip other zones BEFORE `zone.room_conditions.clear()` (`:667`).
- `_coordinator_absent_this_pass` is built in the entry loop (`:611-647`) for every zoned room with no coordinator; the
  add at `:687` is removed.
- `_classify_all_rooms` still runs over all rooms.
- D5 inputs are threaded (`None` -> 0 / False). Rollup `hvac_pending_arm_rooms`.

### 5.4 Entry trigger
- **Setup:** subscribe to `SIGNAL_ROOM_ENTRY_LIFECYCLE` first, then enumerate existing room coordinators and attach
  `async_add_listener(partial(self._on_room_refresh, entry_id))`. Attach is idempotent (release-then-attach).
  `loaded` attaches, `unloaded` releases, `options_updated` re-attaches.

`_on_room_refresh(entry_id, *, from_step=1)` (sync), in order:
1. Gates (as `_fast_path_gates_open`, minus the zone checks).
2. Skip hallways; resolve the zone from `zm.zones` live.
3. Evidence advance: `None` never counts and never overwrites; the first non-`None` counts.
4. D5: update the episode. If the room is cold and not persisted: schedule the arm re-check if the zone is cold, then
   return.
5. Zone-cold gate (stored fused True -> return) + tripped zone (count, return).
6. Per-zone limiter `HVAC_FAST_PATH_MIN_INTERVAL_S` (60 s) on entry runs. Exempt iff
   `_zone_last_s1_write[zone][0] == "away"` (first), else `last_sent == "away"`. Never `preset_mode`.
7. Dedup (`_fast_path_queued`).
8. Queue `fast_entry` with `edge_ts = now`; `exempt_reason` if the room exemption skipped D5.

### 5.5 Lock rules
- Fast runs wait for the lock.
- `_async_decision_cycle`: waits while `_fast_path_running` (set only inside the lock); skips if a full cycle holds the
  lock; after acquiring, skips if a full cycle started after it was scheduled.
- At `_run_decision_cycle` entry (`:1879`), `_zones_written_this_cycle` is seeded with zones whose APPLIED S1 write is
  within `SUPPRESS_TTL_SECONDS_PRESET` (120 s).

### 5.6 Exit timer
- `_schedule_exit_timer(Z)` runs at the end of every full cycle (all zones) and fast run (its zone).
- Preconditions: kill switch on; zone intelligence on; not observation mode; established; evidence or night state;
  target home/sleep; not already sent away; not egress-paused; not tripped.
- `due = zone_away_due_at(Z, grace_s) + HVAC_FAST_PATH_EXIT_SLACK_S`; `None` -> no timer. One-shot key
  `(Z, zone_release_at)`.
- The callback recomputes from live evidence and the live grace (chosen as at `hvac.py:2271-2275`):
  - not due -> lazy reschedule;
  - **Z has a pending room -> reschedule lazily to that room's `ev + J`; key not consumed** [REV 6 N1];
  - due -> record the key; queue `fast_exit` (exempt from the limiter).
- The exit run's producer pass applies D5, so a room that became persisted is armed before S1 decides.
- Reschedule hooks (`number.py` grace setters, `_handle_energy_constraint` `:3843`) only reduce latency. Bypass writers
  (`button.py:857-858`, `__init__.py:7339/7353/7565`) can only delay.
- Pruned zones (`:3987`, `:4010`) cancel their timers.

### 5.7 Ceiling, runaway guard, quick-return alarm, kill switch, restart [REV 6 N5]
- **Write ceiling:** more than 6 fast writes per zone per rolling hour -> one NM; tick-only until local midnight.
- **Runaway guard:** more than 30 fast runs per zone per hour -> same. Lazy reschedules don't count.
- **Quick-return alarm (O1: sums same-room returns).**
  - A *quick-return event* for Z = the first `fast_entry` re-arm in Z, exempt or not, after an APPLIED
    `vacant_past_grace` away on Z, within `HVAC_QUICK_RETURN_WINDOW_S` of that away.
  - At most one event per away (keyed by the away's timestamp).
  - Per-zone counters:
    - `quick_returns_today[Z]`: all events (the alarm count);
    - `same_room_returns_today[Z]`: events whose re-arm carried `exempt_reason="same_room_return"`;
    - `other_room_returns_today[Z]`: the rest.
  - Alarm: `quick_returns_today[Z] >= HVAC_QUICK_RETURN_NM_PER_DAY` (12) -> one LOW NM per zone per day.
  - **Two windows, two anchors:**
    - the transit exemption (`HVAC_TRANSIT_EXEMPT_WINDOW_S`) runs from the ROOM's release;
    - the quick-return window (`HVAC_QUICK_RETURN_WINDOW_S`) runs from the ZONE's away write.
    - They are separate constants (Bug Class #63). A same-room return inside both is still one event.
  - The NM text reads its minutes from `HVAC_QUICK_RETURN_WINDOW_S` at runtime (§14.2).
- **Kill switch** `31 · Fast Room Response` (default ON). OFF = tick timing; D1 and D5 still apply at passes.
- **Global limiter G:** dropped. Zone-scoped, serialised runs; the per-zone ceiling bounds Carrier calls.
- **Restart:** counters, trips, `_fp_last_ev`, `_zone_last_s1_write`, `_zone_vacancy_away_at`, episodes, exemptions and
  timers are in memory and reset. Rooms start cold. `away_edge` stays False until the zone's first APPLIED S1 write.

### 5.8 Teardown
- Set `_tearing_down`.
- Before the first `await` (`hvac.py:5575`): release listeners, cancel exit and arm timers, clear the queue.
- Tasks are cancelled at `:5565`. Every callback checks `_tearing_down`.

### 5.9 Vacancy sweep timing (accepted, not gated)
- The sweep needs the zone past grace AND lighting-empty.
- For 900 s-timeout rooms it lands on the first pass after the room's own timeout, up to ~5 min sooner than today.
- It never precedes the room's own lighting vacancy, and it is not reached while a hold is armed.

### D2 acceptance
- **Premise:** `test_rearm_while_lighting_still_on_triggers_fast_entry`, `test_evidence_during_grace_prevents_away`,
  `test_rearm_limiter_exempt_keyed_on_last_sent`, `test_limiter_exemption_order`.
- **Nudge skip:** `test_fast_write_seeds_nudge_skip_on_next_tick`.
- **Queue/lock:** `test_queue_entry_cleared_on_every_exit_path`, `test_gates_rechecked_after_lock_wait`,
  `test_fast_path_running_only_true_while_holding_lock`.
- **Zone scope:**
  - `test_fast_run_is_zone_scoped` (spies on the enforcer, egress, `check_ac_reset`, fans, covers, predictor,
    anomaly, DPM, arrester sweeps, Carrier freshness)
  - `test_s1_writes_only_origin_zone`, `test_fast_run_sweeps_only_its_zone`
  - `test_fast_run_leaves_sibling_zones_untouched`, `test_absent_set_built_before_zone_loop`
- **Equivalence:** `test_fast_decision_equals_periodic_decision`.
- **Exit timer**
  - `test_exit_timer_fires_at_release_plus_grace` (normal grace 10, constrained 3, coast toggled)
  - `test_exit_timer_uses_grace_at_fire_time`, `test_exit_timer_reads_live_evidence`, `test_exit_timer_lazy_reschedule`
  - `test_exit_timer_one_shot_under_feed_disagreement`, `test_exit_timer_one_shot_consumed_on_gate_e_deferral`
  - `test_exit_timer_cancelled_on_zone_prune`
  - `test_exit_timer_reschedules_to_pending_lapse_without_consuming_key` [REV 6]
- **Listener**
  - `test_listener_ignores_refresh_without_evidence_advance`, `test_listener_skips_warm_zone`,
    `test_listener_skips_hallway`
  - `test_entry_limiter_denies_second_run_within_60s`, `test_two_zones_same_second`, `test_fp_last_ev_none_rule`
  - `test_subscribe_then_enumerate_no_miss_no_double`
- **Lifecycle**
  - `test_periodic_waits_behind_fast_run`, `test_periodic_skips_behind_full_cycle`,
    `test_waiting_periodic_skips_if_full_cycle_ran`
  - `test_listener_lifecycle_idempotent`, `test_boot_settle_suppresses_fast_path`
  - `test_teardown_releases_before_first_await`, `test_tearing_down_guards_every_callback`
- **Guards:** `test_write_ceiling_trips_and_clears_at_local_midnight`, `test_runaway_guard_trips_at_31_runs`,
  `test_quick_return_counter_and_nm_latch` (per §5.7), `test_kill_switch_off_restores_tick_only`.
- **Ledger [REV 6]:** `test_preset_change_row_carries_trigger_edge_ts_zone_empty_since`,
  `test_zone_last_s1_write_stamped_only_on_applied`, `test_house_state_and_pre_arrival_cycles_carry_trigger`,
  `test_preset_change_row_carries_established`.
- **Config boundaries:** grace 0/60; per-room day hold 0; knob 47 = 0/15.

---

## 5b. D5: transit filter on the away -> home edge [RULING R3]

### 5b.1 Rule (evidence states only)
```
away_edge = (_zone_last_s1_write[Z][0] == "away") if Z in _zone_last_s1_write   # APPLIED writes only
            else (strategy_for(...).last_sent(entity, "set_preset_mode") == "away")
away_edge = away_edge and Z not in _pre_arrival_zones
exempt    = released_at[R] is not None and now - released_at[R] <= HVAC_TRANSIT_EXEMPT_WINDOW_S
            # released_at is stamped only for releases of arms with arm_span_s >= W
cold      = away_edge and not prev_output[R] and not exempt
if not cold or W == 0:  output = ev_out
else:                   output = ev_out and persisted(R, now)     # pending while live and not persisted
```
- **Pending room -> the zone preset is held in both directions** (§5.2).
- **Periodic trace (the N1 case).** Zone 3 is `away`, grace 300, Kitchen hold 180. A Kitchen transit at t = 0 lasts
  20 s, so the episode lapses at 20 + 60 = 80.
  - A tick at t = 50: the Kitchen is pending, the hold is armed, no write, one `pending_arm_hold` row.
  - A tick at t = 350: no pending room, fused False, `last_occupied_time` untouched (still stale), past grace. The
    zone stays `away`; no write.
  - Under REV 5 the `lot = now` refresh would have made that tick write `home` "within grace". That was the flap.
- **Zone 3 repro.** The bedroom releases at 240; the Kitchen is entered at 510. The last applied write is `home`, so D5
  is off: the Kitchen arms at 510 and there is no away at 542.
- **Belt.** If `away_edge` is misjudged (a stale `last_sent`), the pending hold still blocks a vacancy away until the
  lapse.
- **Scope.** Night states have no D5; legacy states use the shadow; hallways never reach this code
  (`hvac_zones.py:725-736`). Filtered pass-throughs, only when the zone is set to away: Kitchen, Dining Room, Breakfast
  Nook, Butler Pantry, Kitchen Pantry, Laundry, closets.

### 5b.2 Episode tracking (`ZoneManager._update_arming_episode`, from the listener and every pass)
- `J = min(hold_ev, W)`.
- Not cold -> clear the episode.
- No episode, or `onset - prev_ev > J` -> new episode (`episode_start = onset`, onsets = 1). Otherwise join
  (onsets += 1). Accumulate `active_s`.
- `now > ev + J` unarmed -> lapse; `transit_filtered_today[Z]` += 1.

Examples:
- Closet (hold 60, W 60): a 10 s transit lapses at 70, filtered. A 90 s stay (pulses 0/50/85) arms at 85.
- Kitchen: pulses 70 s apart are never joined.

### 5b.3 Room-only return exemption
- A room whose last release ended an arm of span >= `W` re-arms immediately within `HVAC_TRANSIT_EXEMPT_WINDOW_S`
  (placeholder 900 s, sized from D0c's release -> re-detection gaps). This covers the still person who moves again in
  the same room.
- It renews only from such releases, so a ghosting sensor's short exempt re-arms cannot chain it [REV 6 N4].
- There is no zone-level exemption (§17).
- Exempt re-arms carry `exempt_reason="same_room_return"` and **are counted in the quick-return alarm**
  (`same_room_returns_today[Z]` within `quick_returns_today[Z]`; §5.7) [REV 6 N5].
- **Checkpoint item 3:** "room-only 15-minute return exemption".

### 5b.4 Arm re-check timer
- Scheduled from `_on_room_refresh` step 4 at `episode_start + W + HVAC_ARM_RECHECK_SLACK_S`. One per room, keyed by
  `episode_start`.
- Callback:
  - tearing down -> return;
  - recompute from live accessors;
  - persisted -> re-enter `_on_room_refresh(entry_id, from_step=5)` (never queue directly);
  - lapsed -> drop;
  - otherwise -> nothing.
- Kill switch off and a house-state exit are handled by the gates at fire time (pre-lock and post-lock). A re-check
  firing into a now-warm zone stops at step 5.
- Cancelled on lapse, arm, prune, unload and teardown (before the first await).

### 5b.5 Knob 47 moves; the lighting-session dwell retires
- Remove `hvac.py:2735-2748`. Behaviour-neutral at the live value 0 (guard `:2740`). The old skip also covered
  `home_night`, `guest` and `waking`; D5 does not.
- Key, entity, unique_id, in-place apply, reset button and migration are unchanged.
- `DEFAULT_ZONE_ENTRY_DWELL_MINUTES` 0 -> 1. The live value stays 0 until the operator sets it (D4).
- Unit stays minutes (1 min = 60 s).
- **0 = transit filter off.**

### 5b.6 D5 acceptance
**Card criteria**
- **C1:** the 7-day evidence-state flap count (S1 home/sleep -> `vacant_past_grace` away within 20 min, same zone) is
  below the D0a baseline. C1 alone is not a discriminator.
- **C1-D:** `transit_filtered_today` > 0 at a rate within 2x of D0c's prediction, AND the arm-class split (clean /
  joined-transit / exit-pulse, from `episode_onsets` and `episode_active_s`) is within 2x of D0c.
  - Defeated = filtered ~0 while flaps persist, or joined/exit-pulse arms dominate the remaining flaps.
  - L15 (§9) is the any-path discriminator alongside it.
- **C2:** `test_d5_does_not_change_release`.
- **C3:** `test_hallway_never_arms_with_dwell` — a **construction check** (the upstream exclusion keeps hallways out of
  D5).
- **C4:** SUPERSEDED banners on `PLANNING_hvac_entry_dwell_room_clock.md` and `PLANNING_hvac_entry_dwell_hvac_clock.md`;
  the card closes as folded.

**Tests**
- **Transit and stay**
  - `test_transit_under_60s_no_write` [REV 6 N1: periodic-tick horizon]:
    - zone `away`, grace 300, Kitchen hold 180, 20 s transit;
    - ticks at 50 (pending window), then every 300 s through lapse + G + hold_ev (80 + 300 + 180 = 560 -> ticks at
      350, 650);
    - assert no home/sleep `preset_change` at any tick, exactly one `pending_arm_hold` suppressed row, and
      `last_occupied_time` unchanged throughout;
    - Kitchen PIR-pulse variant (UP Sense pulses at 0 and 20 s), same horizon.
  - `test_stay_60s_writes_within_sla` (continuous radar -> write in `[60, 105] s`, `trigger=fast_entry`).
  - `test_intermittent_pir_stay_arms_on_pulse_after_window`.
- **Episodes:** `test_gap_longer_than_join_window_starts_new_episode`,
  `test_joined_transits_within_j_arm_and_are_classified`, `test_episode_lapses_at_ev_plus_j_and_counts_filtered`.
- **Pending hold [REV 6 N1]**
  - `test_pending_hold_blocks_both_directions`:
    - (a) zone `away`, pending Kitchen: no home write at a tick in the pending window;
    - (b) a stale `last_sent` makes `away_edge` True while the zone is `home` in grace past G: no away until the lapse,
      then away.
  - `test_pending_hold_cleared_by_d5_shed`, `test_pending_hold_not_armed_for_house_away_transition`
  - `test_never_armed_episode_excluded_from_e_and_backfill`
  - `test_zone3_repro_no_away_when_kitchen_enters_during_grace`, `test_unarmed_episode_blocks_vacancy_away`
- **D5 scope:** `test_d5_only_on_away_edge`, `test_pre_arrival_zone_bypasses_d5`,
  `test_away_edge_unknown_after_restart_fails_open`.
- **Exemption**
  - `test_same_room_return_rearms_immediately`
  - `test_exemption_renews_on_each_release` (only after a span >= `W` arm)
  - `test_exemption_not_renewed_by_ghost_blip_chain` [REV 6 N4]
  - `test_other_room_in_away_zone_waits_w`, `test_rearm_after_window_is_cold`
- **Alarm [REV 6 N5]**
  - `test_exempt_rearm_counted_once_in_quick_return_alarm`: one away, an exempt same-room re-arm, then another-room
    re-arm within the window -> exactly one event; `same_room_returns_today == 1`, `quick_returns_today == 1`
  - `test_quick_return_alarm_per_zone_and_sums`: zone_3 reaches 12 mixed events -> NM; zone_1 unaffected
  - `test_quick_return_nm_text_uses_constant`
- **Stamps:** `test_zone_vacancy_away_at_stamped_only_on_vacant_past_grace`.
- **Scope/knob:** `test_warm_room_no_dwell`, `test_dwell_zero_is_rev3_behaviour`, `test_dwell_only_in_evidence_states`.
- **Re-check**
  - `test_arm_recheck_scheduled_at_onset_plus_w`, `test_arm_recheck_reenters_at_step_5`,
    `test_arm_recheck_into_warm_zone_stops_at_gate`
  - `test_arm_recheck_kill_switch_off_no_run`, `test_arm_recheck_after_house_state_exit_runs_without_d5`
  - `test_arm_recheck_cancelled_on` × {lapse, arm, prune, unload, teardown}
- **Other**
  - `test_exit_run_arms_persisted_room_before_away`
  - `test_lighting_session_dwell_removed` (behavioural: knob 47 = 1, `home_night`, zone lighting session 20 s old, room
    armed by the shadow -> S1 still writes; re-inserting the skip turns it RED)
  - `test_d5_does_not_change_release`, `test_hallway_never_arms_with_dwell` (construction check)
  - `test_evidence_onset_accessor`, `test_transit_helper_text_matches_constant`

**Live:** per-room attrs `episode_*`, `armed_at`, `arm_span_s`, `dwell_s`, `exempt_reason`, `pending`; mode-sensor
counters. For 10 away-edge cold arms with continuous evidence, `armed_at - episode_start` is in `[60, 105] s`.

---

## 6. Latency budget (before -> after)
Assumptions: grace 300 s, tick 300.3-301.1 s, poll 30-35 s, refresh within 2 s. Today the grace is absorbed by tick
quantization (Kitchen at its old 600 s timeout ~18 min, matching the operator's "15-20 min").

| Path | Today (live) | After |
|---|---|---|
| Entry into an away zone, knob 47 = 1 | avg ~2.5-3 min, worst ~5.5 min | 60 s + a few seconds (<= 105 s) |
| Entry into an away zone, knob 47 = 0 | same | usually < 5 s; <= 45 s |
| Entry into a zone that is Home / in grace | no write needed | immediate arm |
| Pass-through under 60 s (away zone) | home at the next tick, then away (a flap) | no write; preset held while pending |
| Same-room re-arm after a wrong away (within the exemption window) | avg ~2.5, worst ~5 min | usually < 5 s; <= 45 s |
| Other-room entry into a just-away zone | avg ~2.5, worst ~5 min | 60 s + a few seconds |
| Still person who does not move | held by timeout + tail | held by the hold ONLY |
| Exit, `home_day`/`home_evening`, 300 s room | avg ~12.8 min (~10-15.6) | hold + 5 min: closet/infra 6; generic/utility/media/garage 7; bathroom 8; common 8; bedroom 9 |
| Exit, same states, 900 s room | avg ~22.8 min | bathroom 8 / common 8 |
| Exit, Kitchen | ~12.8 (300 s stopgap) | 8 min |
| `home_night`, `guest`, `arriving` | today's rule | unchanged |
| `sleep`/`waking` | timeout + night hold + tick | same or later; release + 5 min |

- Each exit adds ~2-5 s.
- A pending room can hold its zone's preset at most `J` (<= 60 s) after its last evidence.

---

## 7. Residual risk (evidence states only)

### 7.1 Audit counts at the ruled values (G = 300, 6.74 days) — context, operator-accepted
| Class | At the ruled table | Today |
|---|---|---|
| MID zone retreat | ~13 (common 180, all Kitchen; generic/utility/bath/closet 0; bedroom 240 between 1 and 0) | 0 |
| MID with Jaya 60 left | +2 (D4 fixes) | 0 |
| LATE zone retreat | ~36 (Kitchen 29, Dining 2, Master Bath 1, Jaya Bath 1, bedrooms <= 1) | 0 |
| Total | ~49 / 6.74 d ≈ 7/day, mostly zone_3 | 0 |

- Context, not a gate (R1). A person who does not move stays at away until they do.
- **Kitchen exception dropped:** operator-accepted in spirit; confirm at the checkpoint.
  - 29 of 36 LATE and all MID retreats are the Kitchen.
  - 30 of 30 Kitchen LATE events had evidence elsewhere (mostly the Patio).
  - The Kitchen timeout is already 300 s; a config override remains available.

**D5 known limitations**
- **Kitchen PIR joined transit:** passes within 60 s of each other that span >= 60 s arm.
- **Exit pulse:** a still entrant who leaves 60+ s later arms as they go.
- **Hobeian 31 s minimum on-time:** a 5 s pass shows 31 s active; two triggers within `J` reach 60 s.
- **Pending hold:** it can delay a legitimate home write (a real stay in a second room) by at most `J` if another room
  of the zone is pending. That stay has persisted by then anyway [REV 6].
- D0c reports these separately; C1-D uses them.

**Other D5 residuals**
- 60 s on real arrivals into an away zone.
- A still entrant is treated as a transit until they move.
- Sparse-PIR closets may not arm.
- Other-room returns wait 60 s.

**Unmeasured:** production fusion filters and phantom radars (D0c and the trip-wire cover them). **Side-finding:** the
Dining radar has been silent for 24 h (orchestrator card).

### 7.2 Context arithmetic (no recommendation) [RULING R2]
| Type | Sample max day MID gap | T + G at the ruled values |
|---|---|---|
| common_area | 603 s | 180 + 300 = 480 s |
| bedroom | 495 s | 540 s |
| generic / utility | 396 / 386 s | 420 s |
| bathroom | 836 s | 480 s (0 measured at 180: co-occupied) |
| closet | 204 s | 360 s |

- Recorded as context; the operator accepts it (R1, R2).
- Knob 49 enters the same sum under coast/shed.
- The quick-return trip-wire is the live measure.

---

## 8. D0: probes (read-only)
- **D0a**, `hvac_fast_path_d0_probe.py --latency`, >= 3 occupied days (earliest 2026-09-30):
  - per-zone entry latency and exit latency;
  - flap rate (S1 home/sleep -> `vacant_past_grace` away within 20 min);
  - each flap's arming room and raw evidence duration, where recoverable.
- **D0b:** REV 4 F9 `climate_write` baseline, >= 3 days (earliest 2026-09-30).
- **D0c**, `hvac_raw_evidence_gap_probe.py --graces 300,600`, T grid + 240, with the REV 6 D5 replay (away edge, `J`,
  span-gated room exemption, pending hold). Reported separately:
  - filtered episodes
  - clean / joined-transit / exit-pulse arms
  - pending holds (count and duration)
  - predicted flap reduction
  - same-room release -> re-detection gaps (sizes `HVAC_TRANSIT_EXEMPT_WINDOW_S`)
  - predicted quick-return events per zone
  - **Gate A:** any zone's ZR > 2x the audit figure at the ruled T -> stop. Blocks deploy.
- **D0c-home_night:** `--states home_night`, >= 7 nights. **Gate B:** `home_night` MID ZR at the ruled table = 0 ->
  propose adding it to `HVAC_EVIDENCE_RULE_STATES` (reviewed follow-up). Does not block deploy.

---

## 9. Live acceptance (discriminating)
| # | Check | Pass | Failure looks like |
|---|---|---|---|
| L1 | Entry latency | knob 1: >= 90 % of away-edge `fast_entry` rows in `[60, 105] s` after `episode_start`; knob 0: <= 45 s after `edge_ts` | uniform 0-300 s |
| L2 | Exit exactness | `fast_exit` away: `row_ts - zone_empty_since` in `[g, g + 50] s` | `[g, g + 300]` spread; `< g` |
| L3 | INV-2 live | each evidence-state away: every zone room `release_at <= row_ts - g`, `rule == evidence`, no pending rooms | any later release or pending room |
| L4 | Re-arm | each same-room quick return: `fast_entry` home/sleep within 45 s of `edge_ts` (zone_1 excluded while §9.7 is open) | home only at the next tick |
| L5 | Zone scope | during fast runs, no other-zone `climate_write`; no enforcer/nudge/cover/fan actions; sweep only for Z | any off-zone write |
| L6 | Clock decoupled | D1 Live | off never precedes lighting off |
| L7 | Night/legacy unchanged | in `sleep` and `home_night`: `rule` night/legacy; no early release; no legacy back-fill | earlier release / back-filled lot |
| L8 | Write rate | per-zone `climate_write`/day <= D0b + spread + 10; no ceiling trips | trips or a jump |
| L9 | Quick returns | 7-day per-zone `quick_returns_today` (distinct events, exempt + non-exempt) within 2x D0c's per-zone prediction; `same_room_returns_today` reported alongside | much higher |
| L10 | Lifecycle | after a room reload and an HA restart: one listener per room; timers re-armed | duplicates / missing |
| L11 | Nudge skip | no `nudge_started` within 120 s after a fast write on that zone | a nudge seconds after |
| L12 | D5 C1 + C1-D + C3 | §5b.6 | §5b.6 |
| L13 | No short arms | knob 1: zero away-edge arms with `armed_at - episode_start < 60 s` and no `exempt_reason` | any |
| L14 | No away with a pending room | zero `vacant_past_grace` aways while that zone had `pending_arm_rooms` | any |
| **L15** [REV 6 N2] | **No home without HVAC occupancy** | zero S1 `preset_change` rows with `new_preset` in (home, sleep) and `any_room_hvac_occupied == false`, excluding rows with `trigger` in (`house_state`, `pre_arrival`), `reason == pre_arrival`, or `established == false` | any such row: a transit or pending episode caused a home write (the N1 flap class); the filter is defeated |

L15 is the any-path discriminator alongside C1-D. Results go into the README as a `Validated <date>` table.

---

## 10. D3: vacancy grace re-check (knob only)
- Knob 48 (5), no code. §7.2 is context.
- After >= 7 days live, adapt `hvac_vacancy_grace_probe.py`: for G' in {2, 3, 4} min, extra quick-return events vs
  conditioning minutes saved.
- The operator decides.

## 10b. D4: config step
- Clear Jaya Bedroom's day override (attr `hvac_vacancy_hold_s` = 240 in `home_day`, 5400 in `sleep`).
- **Set knob 47 to 1** once D5 is live (checkpoint).
- Kitchen override only if the operator reverses the ruling.

---

## 11. Tier: 3
**Why:** it changes the still-person safeguard and the arming edge; it adds triggers and timers into the shared lock
and S1 site; two failed plan reviews before.

**Protocol:**
1. D5 re-review of REV 6.
2. Build.
3. Four parallel reviews: A local correctness; B integration/state machine; C per-site mutation; D adversarial
   completeness, including pre-existing paths.
4. Orchestrator re-grep and re-drill.
5. Operator checkpoint: four items + Gate A.

### 11b. Builder traps
1. Triggering on the lighting binary sensor edge instead of the evidence stamp.
2. Calling `_run_decision_cycle` for a fast run, or not skipping the enforcer/DPM under the filter.
3. Zone filter after `clear()`.
4. Absent set left inside the filtered zone loop.
5. Back-fill missing, or applied in legacy states.
6. Stamping from `_last_motion_time`, or only on rising edges.
7. Re-deriving camera/BLE instead of reading this tick's source.
8. Rescheduling a fired exit key (§9.7 loop).
9. Keying the limiter exemption on `preset_mode`.
10. A waiting periodic running a second full cycle.
11. The shadow reading `ROOM_TYPE_HVAC_HOLD`, or removing the clamp.
12. Releasing listeners or timers after the first `await`.
13. `trigger` only in a counter, not on the `preset_change` row.
14. The evidence branch writing the shadow dicts.
15. `guest`/`arriving`/`home_night` in the evidence states.
16. `finally` placement: queue discard outer, `_fast_path_running` inner.
17. Resetting `_zones_written_this_cycle` to an empty set.
18. `if ev:` truthiness instead of `isinstance`.
19. Relying on reschedule hooks instead of recomputing at fire.
20. Stamping on suppressed sources, or falling-edge-stamping after them.
21. Refresh-failure hold outside evidence states, or unbounded.
22. Dwell applied to an exempt room.
23. `onset` from the lighting session or the debounce anchor.
24. Episode joining beyond `J`, or never lapsing.
25. Leaving the lighting-session skip in place (double dwell).
26. Dwell in night or legacy states.
27. Arm re-check scheduled for warm zones, or not cancelled.
28. Changing knob 47's unit or unique_id.
29. D5 applied when the zone's last applied write is not `away`, or to pre-arrival zones.
30. A pending room not blocking the vacancy away.
31. Re-adding a zone-level exemption, or reusing `HVAC_QUICK_RETURN_WINDOW_S` for the exemption.
32. **[REV 6 N5, inverted]** Excluding exempt re-arms from the quick-return alarm, or counting several re-arms after
    one away as several events.
33. The arm re-check queuing directly instead of re-entering at step 5.
34. Stamping `_zone_vacancy_away_at` on anything but an APPLIED `vacant_past_grace` away.
35. **[REV 6 N1]** Setting `last_occupied_time` (to `now` or anything) because a room is pending.
36. **[REV 6 N1]** Letting a never-armed episode into `E(Z)` or the back-fill.
37. **[REV 6 N1]** Arming the pending hold for house-state away/vacation targets, or not clearing it on D5 shed.
38. **[REV 6 N1]** The exit timer consuming its key while a room is pending.
39. **[REV 6 N3]** Stamping `_zone_last_s1_write` on any non-APPLIED result.
40. **[REV 6 N4]** Renewing `released_at` after a short (span < `W`) arm.
41. **[REV 6 N2]** Not threading `trigger="house_state"` / `"pre_arrival"`, or omitting `established` from the row.

### 11c. Test-file impact
| Test | Result | Disposition |
|---|---|---|
| `test_zzz_hvac_conditioning_demand.py:909` (`ROOM_TYPE_HVAC_HOLD["bedroom"] == 60`) | **RED** | update to 240; add legacy-table 60 |
| `test_zzz_hvac_conditioning_demand.py:774-775` (dwell default 0) | **RED** | update to 1 |
| `test_hvac_night_hold_follows_sleep.py:69-79` | **RED** | compare with `ROOM_TYPE_HVAC_TAIL_LEGACY` |
| `test_hvac_vacancy_hold_ui_defaults.py:159-172` | **RED** | new helper wording |
| `test_zzz:246-269`, `:325-331`, `:505-523`, `:636-716` | GREEN | shadow selector; monotonic; migration untouched |
| other `test_hvac_night_hold_follows_sleep.py` tests | GREEN | `:216-255` guards the `isinstance` fallback |
| `test_v5_103_8_hvac_knobs_and_obs.py:127-170`, `:359-430` | GREEN | shadow + override |
| `test_hvac_presence_timer_knobs.py` | GREEN (verify `:686`, `:709-710`, `:860-865` at build) | reads the constant |
| `test_part2_ec_hc_writeback.py`, `test_cm_reload_suppression.py` | GREEN | key unchanged |
| `test_dpm_cleanup_and_labels.py:179` | GREEN if both string files change together | parity |

### 11d. Per-site mutation drill table (table of record)
Every drill: neuter the returned value or branch (not just the call), bytecode disabled; restore; `git status` clean.

| # | Site | RED test |
|---|---|---|
| 1 | Evidence output returns `shadow_out` | `test_evidence_state_ignores_lighting_timeout` |
| 2 | Evidence branch writes `_hvac_armed = False` | `test_home_evening_to_sleep_mid_timeout_stays_held` |
| 3 | Night drops the shadow | same + `test_night_release_never_before_shadow` |
| 4 | `home_night` in evidence states | `test_home_night_is_legacy_until_gate` |
| 5 | `active` term removed | `test_hold_zero_holds_while_active` |
| 6 | Refresh hold removed / unbounded / in night | `test_refresh_failure_hold_evidence_states_only_and_bounded` |
| 7 | Suppressed-source check removed | `test_no_stamp_on_fan_demoted_failsafe_recheck_sources` |
| 8 | Camera/BLE term removed | `test_camera_ble_stamp_only_from_override_verdict` |
| 9 | Override-vacant exclusion removed | `test_override_vacant_blocks_stamp` |
| 10 | Falling-edge stamp removed | `test_falling_edge_refresh_stamps` |
| 11 | BLE cap neutered | `test_ble_cap_stops_stamp_after_cap` |
| 12 | `apply_fan_recheck_release` leaves active True | `test_fan_recheck_release_clears_active` |
| 13 | Back-fill removed | `test_last_occupied_time_backfilled_to_exact_release` + `test_exit_timer_fires_at_release_plus_grace` |
| 14 | Back-fill in legacy states | `test_no_backfill_in_legacy_states` |
| 15 | Filter after `clear()` | `test_fast_run_leaves_sibling_zones_untouched` |
| 16 | Loop-top `continue` removed | `test_s1_writes_only_origin_zone` |
| 17 | Absent set inside the loop | `test_absent_set_built_before_zone_loop` |
| 18 | Enforcer not skipped | `test_fast_run_is_zone_scoped` (enforcer spy) |
| 19 | DPM not skipped | `test_fast_run_is_zone_scoped` (DPM spy) |
| 20 | Listener on the lighting edge | `test_rearm_while_lighting_still_on_triggers_fast_entry` |
| 21 | Evidence-advance check removed | `test_listener_ignores_refresh_without_evidence_advance` |
| 22 | Zone-cold gate removed | `test_listener_skips_warm_zone` |
| 23 | Hallway skip removed | `test_listener_skips_hallway` |
| 24 | 60 s limiter removed | `test_entry_limiter_denies_second_run_within_60s` |
| 25 | Exemption keyed on `preset_mode` | `test_rearm_limiter_exempt_keyed_on_last_sent` |
| 26 | Registry-miss fallback removed | `test_limiter_exemption_order` |
| 27 | Order swapped / removed | `test_limiter_exemption_order` |
| 28 | Nudge seed to `set()` | `test_fast_write_seeds_nudge_skip_on_next_tick` |
| 29 | Queue discard inside the lock | `test_queue_entry_cleared_on_every_exit_path` |
| 30 | Running flag cleared in the outer `finally` | `test_fast_path_running_only_true_while_holding_lock` |
| 31 | Post-lock gate re-check removed | `test_gates_rechecked_after_lock_wait` |
| 32 | `_tearing_down` guard removed (per site) | `test_tearing_down_guards_every_callback` |
| 33 | Teardown after the first await | `test_teardown_releases_before_first_await` |
| 34 | One-shot key not recorded | `test_exit_timer_one_shot_under_feed_disagreement` |
| 35 | Exit timer reads cached evidence | `test_exit_timer_reads_live_evidence` |
| 36 | Scheduled grace used at fire | `test_exit_timer_uses_grace_at_fire_time` |
| 37 | Constrained-grace choice removed | 10/3 variant of `test_exit_timer_fires_at_release_plus_grace` |
| 38 | Timer not cancelled on prune | `test_exit_timer_cancelled_on_zone_prune` |
| 39 | Waiting periodic doesn't skip | `test_waiting_periodic_skips_if_full_cycle_ran` |
| 40 | Ceiling never trips | `test_write_ceiling_trips_and_clears_at_local_midnight` |
| 41 | Runaway guard never trips | `test_runaway_guard_trips_at_31_runs` |
| 42 | Alarm never counts | `test_quick_return_counter_and_nm_latch` |
| 43 | `isinstance` -> truthiness | `test_accessor_fallback_uses_isinstance_datetime` + night-hold `:216-255` |
| 44 | Shadow selector reads `ROOM_TYPE_HVAC_HOLD` | `test_legacy_tail_is_frozen_v5_103_19` + `test_zzz:246-269` |
| 45 | Dwell check removed | `test_transit_under_60s_no_write` (+ PIR variant) |
| 46 | Arm re-check not scheduled | `test_stay_60s_writes_within_sla` |
| 47 | Room exemption removed | `test_same_room_return_rearms_immediately` |
| 48 | Zone exemption re-added | `test_other_room_in_away_zone_waits_w` |
| 49 | Exemption window unbounded | `test_rearm_after_window_is_cold` |
| 50 | Episode never lapses | `test_episode_lapses_at_ev_plus_j_and_counts_filtered` |
| 51 | Join window uses `hold` instead of `min(hold, W)` | `test_gap_longer_than_join_window_starts_new_episode` |
| 52 | Dwell in night/legacy | `test_dwell_only_in_evidence_states` |
| 53 | Lighting-session skip left in place | `test_lighting_session_dwell_removed` (behavioural) |
| 54 | Exit run skips D5 | `test_exit_run_arms_persisted_room_before_away` |
| 55a-e | Arm re-check not cancelled on {lapse, arm, prune, unload, teardown} | `test_arm_recheck_cancelled_on[...]` |
| 56 | Onset re-stamped every active tick | `test_evidence_onset_accessor` |
| 57 | `W == 0` branch removed | `test_dwell_zero_is_rev3_behaviour` |
| 58 | D5 applied regardless of the away edge | `test_d5_only_on_away_edge` + `test_zone3_repro_no_away_when_kitchen_enters_during_grace` |
| 59 | Pending room does not block away | `test_unarmed_episode_blocks_vacancy_away` + `test_pending_hold_blocks_both_directions` (b) |
| 60 | Pre-arrival not excluded | `test_pre_arrival_zone_bypasses_d5` |
| 61 | Unknown away edge treated as True | `test_away_edge_unknown_after_restart_fails_open` |
| 62 | Exemption not renewed after a real arm | `test_exemption_renews_on_each_release` |
| 63 [REV 6 N5, inverted] | Exempt re-arm **excluded** from the alarm, or one away counted twice | `test_exempt_rearm_counted_once_in_quick_return_alarm` |
| 64 | `_zone_vacancy_away_at` on any away | `test_zone_vacancy_away_at_stamped_only_on_vacant_past_grace` |
| 65 | Arm re-check queues directly | `test_arm_recheck_reenters_at_step_5` + `test_arm_recheck_into_warm_zone_stops_at_gate` |
| 66 | Joined-transit misclassified | `test_joined_transits_within_j_arm_and_are_classified` |
| 67 [REV 6 N1] | **Pending-arm hold removed** (flag never set, or `continue` skipped) | `test_transit_under_60s_no_write` (tick horizon) + `test_pending_hold_blocks_both_directions` (a) |
| 68 [REV 6 N1] | **Never-armed episode in `E(Z)` / back-fill, or `last_occupied_time = now` re-added** | `test_never_armed_episode_excluded_from_e_and_backfill` + `test_transit_under_60s_no_write` (`lot` unchanged assert) |
| 69 [REV 6 N1] | Pending hold not cleared by D5 shed / armed for a house-away target | `test_pending_hold_cleared_by_d5_shed` + `test_pending_hold_not_armed_for_house_away_transition` |
| 70 [REV 6 N1] | Exit timer consumes its key while pending | `test_exit_timer_reschedules_to_pending_lapse_without_consuming_key` |
| 71 [REV 6 N3] | `_zone_last_s1_write` stamped outside APPLIED | `test_zone_last_s1_write_stamped_only_on_applied` |
| 72 [REV 6 N4] | `released_at` stamped after a short arm | `test_exemption_not_renewed_by_ghost_blip_chain` |
| 73 [REV 6 N5] | Alarm counts global instead of per zone | `test_quick_return_alarm_per_zone_and_sums` |
| 74 [REV 6 N2] | `trigger` / `established` missing from the row | `test_house_state_and_pre_arrival_cycles_carry_trigger` + `test_preset_change_row_carries_established` |

---

## 12. Sequencing and supersession
- **B shipped (v5.103.19);** no wait gate.
- **REV 4 fast-path plan** (`PLANNING_hvac_w2_occupancy_fast_path.md`): superseded banner.
- **`HVAC-ENTRY-DWELL-ROOM-CLOCK-1`:** folded (release half in D1, arming half in D5). Close it as folded when D5 ships;
  banners on the two dwell plans.
- **`HVAC-FAST-PATH-FAN-WARM-EDGES-1`:** out of this cycle; recommend a fan-only Tier-2 cycle next. Its trigger is
  arguably met, but fans read lighting, have their own gates, and would reintroduce REV 4's "fan writes off-schedule"
  HIGH. Operator to confirm.
- **Other cards:**
  - `HVAC-HOLD-SIZING-ALL-ROOMS-1` -> D3/L9 input.
  - `HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1`: unchanged exposure.
  - `HVAC-WRITE-CONFIRMATION-ORACLE-1`: one-shot timer; L4 excludes zone_1.
  - Dining radar card (orchestrator).
- **Supersession triage:**
  - `ZoneState.current_session_start` (`hvac_zones.py:135`, written `:786-789`) has no reader after D5: DELETE after
    live validation (W4 card).
  - `_migrate_hvac_zone_entry_dwell_to_zero` (`__init__.py:719`): KEEP + DOCUMENT.
- **D0b:** >= 3 days (earliest 2026-09-30).

## 13. REV 4 fast-path findings (F1-F15) and re-review HIGHs: disposition
| Item | Disposition |
|---|---|
| Whole-house off-schedule cycle | Fast runs never call `_run_decision_cycle` |
| Wrong-zone reruns | Per-zone queue + wait-for-lock |
| Heat_cool/egress/fan/cover writes | Not called by a fast run |
| Sibling-zone wake-ups | Filter before `clear()`; absent set before the zone loop; S1 origin-only |
| F1 dwell follow-up | Replaced by the D5 arm re-check |
| F2 origin_zones | Replaced by the zone-scoped run |
| F3 count-coupled skips | Moot; waiting-periodic skip rule |
| F4 zone-cold gate | Kept |
| F5 lock/rerun | Wait-for-lock rules + nudge seed |
| F6 teardown | Kept |
| F7/F8 | Row fields (`trigger`, `edge_ts`) |
| F9 | D0b |
| F10 | Write ceiling + runaway guard |
| F11 | Lines refreshed |
| F12 zones live / F13 one lifecycle subscription | Kept |
| F14 | Gauge/counters on `sensor.ura_hvac_coordinator_mode` (`_status` does not exist) |
| F15 anomaly | Not called |
| Global limiter G | Dropped |

---

## 14. Knobs and labels

### 14.1 Knob ladder
| Number | Value | Rung | Why |
|---|---|---|---|
| `ROOM_TYPE_HVAC_HOLD` | §4.6; common 180 | 1 | Rulings R1/R2; changing a value re-opens the still-person trade; the trip-wire is the live check |
| `ROOM_TYPE_HVAC_TAIL_LEGACY` | frozen | 1 | Shadow; must not be tuned |
| `HVAC_EVIDENCE_RULE_STATES` | (`home_day`, `home_evening`) | 1 | Adding a state needs a probe and review |
| `HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S` | 600 | 1 | Longest hold 240 + ~10 polls; 0 disables |
| `HVAC_FAST_PATH_MIN_INTERVAL_S` / `_SLA_S` / `_EXIT_SLACK_S` | 60 / 45 / 2 | 1 | Per-zone entry floor (exempt for re-arm) / observability target / clears the strict `>` |
| `HVAC_FAST_PATH_MAX_WRITES_PER_ZONE_PER_HOUR` / `_MAX_RUNS_PER_ZONE_PER_HOUR` | 6 / 30 | 1 | Carrier bound / runaway guard |
| `HVAC_QUICK_RETURN_WINDOW_S` | 900 | 1 | Alarm window, anchored at the ZONE's away write |
| `HVAC_QUICK_RETURN_NM_PER_DAY` | 12 | 1 | Per zone; distinct events, exempt + non-exempt (O1). ~2x the expected zone_3 rate. **Checkpoint** |
| `HVAC_TRANSIT_EXEMPT_WINDOW_S` | 900 (placeholder) | 1 | Anchored at the ROOM's release after a span >= W arm; sized by D0c; the knob 47 helper states its minutes (test) |
| Knob 47 `number.ura_hvac_coordinator_zone_entry_dwell` | default 1 min; live 0 until set | 3 (existing) | R3; tuned by flap rate vs entry wait; 0 = filter off |
| `HVAC_ARM_RECHECK_SLACK_S` | 1 | 1 | Lands the re-check just past `episode_start + W` |
| Fast room response switch | ON | 3 | Rollback; OFF = tick timing |
| Knob 48 / 49 grace | 5 / 5 | 3 (existing) | D3 |

### 14.2 Labels
Rules: short config-flow phrase; plain helper; entity names 3 words max after the numbering prefix. Banned: tail,
HVAC-occupied, clamp, gate, evidence, tick, fast path, debounce, CRIT, fused, rung, shadow, legacy, dwell, transit, arm,
episode.

**Room options, climate step:**
- `hvac_vacancy_hold` label: `Empty-room hold (day)`
- `hvac_vacancy_hold` helper: `How many seconds heating and cooling keep treating this room as occupied during the day and evening. The time counts from the last sign of someone in the room, such as motion, presence, a camera or a phone. This covers people sitting still, and it is the only protection for someone who stays completely still. Leave blank to use the default for this room type: 1 minute for closets, 2 minutes for media, utility and general rooms and garages, 3 for bathrooms and living areas, and 4 for bedrooms. Enter 0 to hold only while a sensor still sees someone. From 9 pm until the house goes to sleep, this number is counted from when the room itself shows as empty.`
- `hvac_vacancy_hold_night` label: `Empty-room hold (night)`
- `hvac_vacancy_hold_night` helper: `The hold used while the house is asleep or waking up. It counts from when the room itself shows as empty, so sleepers who lie still get extra time. Leave blank to use the default for this room type: 30 minutes for bedrooms and media rooms, 15 for living areas, 10 for bathrooms, garages and utility rooms, and 5 for closets. Enter 0 for no extra time once the room shows as empty. This form rejects a night value below the day value.`
- Error `hvac_hold_night_below_day`: `The night hold must be at least as long as the day hold. Raise the night value, or leave one of them blank to use the room type's default.`
- Section `climate_backstop` name: `Thermostat and empty-room hold`

**HVAC coordinator options:**
- `hvac_vacancy_grace_minutes` helper: `Minutes a zone waits after its last room empties before heating and cooling switch to Away. If someone comes back sooner, nothing changes. A shorter wait saves energy but switches a zone to Away more often while someone sits still.`
- `hvac_vacancy_grace_constrained` helper: `The same wait, used while the house is saving energy. It must be no longer than the normal delay. A shorter wait saves energy but switches a zone to Away more often while someone sits still.`
- `hvac_zone_entry_dwell` label: `Entry wait (minutes)`
- `hvac_zone_entry_dwell` helper: `How long someone must be in a room before heating and cooling switch a zone that is set to Away back to Home, during the day and evening. People passing through faster than this do not switch it. Someone coming back to a room within 15 minutes counts at once. Enter 0 to count any sign of someone at once. Recommended: 1.` ("15" = `HVAC_TRANSIT_EXEMPT_WINDOW_S / 60`; test.)

**Entities:**
- `47 · Entry Wait (min)` (unchanged).
- `31 · Fast Room Response` (`switch.ura_hvac_coordinator_31_fast_room_response`, unique_id
  `{DOMAIN}_hvac_fast_room_response`).

**Notifications (numbers read from constants at runtime):**
- Ceiling: `Fast room response paused for {zone}` / `{zone} changed its heating and cooling setting {n} times in the last hour. Fast response is off for this zone until midnight. The regular 5-minute check still runs.`
- Quick returns: `{zone} keeps switching to Away too soon` / `{zone} switched to Away and someone was back within {window_min} minutes {n} times today. The empty-room hold for a room in this zone may be too short.` (`{window_min}` = `HVAC_QUICK_RETURN_WINDOW_S // 60`)
- Runaway: `Fast room response paused for {zone}` / `{zone} ran more checks than expected in the last hour. Fast response is off for this zone until midnight. The regular 5-minute check still runs.`

**Acceptance:** `strings.json` == `en.json`; banned-word check clean; JSON parses; hassfest passes;
`test_hvac_vacancy_hold_ui_defaults.py` updated.

---

## 15. Files
| File | Change |
|---|---|
| `custom_components/universal_room_automation/const.py` | `ROOM_TYPE_HVAC_HOLD` values; `ROOM_TYPE_HVAC_TAIL_LEGACY` |
| `.../coordinator.py` | Evidence stamp, onset, three accessors |
| `.../domain_coordinators/hvac_zones.py` | Shadow + rule output; D5 (away edge, episodes with `J`, span-gated room exemption, pending list); selectors; `zone_ids` filter; absent set in the entry loop; back-fill over armed rooms; never-armed exclusion; release helpers; diag/zone attrs |
| `.../domain_coordinators/hvac.py` | Listeners + lifecycle; `_on_room_refresh(from_step)`; `_async_zone_fast_run`; exit and arm timers; lock rules; nudge seed; `_apply_house_state_presets(zone_filter, trigger, edge_ts)`; pending-arm hold beside the row-1 hold; removal of `:2735-2748`; `_zone_away_edge`; APPLIED-only `_zone_last_s1_write`; `_zone_vacancy_away_at` (vacancy only); `trigger` from the house-state and pre-arrival handlers; `established` on the row; ceiling/guard; per-zone alarm counters with per-away dedup; teardown; `get_mode_attrs` |
| `.../domain_coordinators/hvac_const.py` | §14.1 constants; `DEFAULT_ZONE_ENTRY_DWELL_MINUTES = 1` |
| `.../binary_sensor.py` | Attrs per §3.2; `_display_hold` |
| `.../switch.py` | `31 · Fast Room Response` |
| `.../number.py` | Grace setters call `reschedule_exit_timers()` |
| `.../strings.json`, `.../translations/en.json` | §14.2 |
| `quality/tests/` | New `test_hvac_evidence_clock.py`, `test_hvac_fast_occupancy_response.py`, `test_hvac_transit_filter.py`; updates per §11c |
| `scripts/probes/` | `hvac_fast_path_d0_probe.py --latency` + flap rate; `hvac_raw_evidence_gap_probe.py --states`, T 240, REV 6 D5 replay with separate counts and exemption sizing; `hvac_vacancy_grace_probe.py` adaptation |
| Docs | State of play (§1, §2, §3.1-§3.2, §8, §9.5, §9c, §9d, header); SUPERSEDED banners (REV 4 fast-path plan, two dwell plans); README (PATCH; the orchestrator may argue MINOR) |

`config_flow.py` is not changed (validation kept; the knob 47 field stays).

## 16. Non-goals
- No change to night hold values or anchor.
- No change to `home_night`, `guest`, `arriving` or `away` behaviour: no evidence rule, back-fill, exit timer, D5 or
  pending hold there.
- No change to the clamp or the flow validation.
- No fan, cover, predictor, egress, arrester, DPM or D9 change; fans stay tick-driven.
- No change to `HVAC_DECISION_TICK`, the grace values, or knob 47's unit, range or entity id.
- No change to hallway exclusion. Override Vacant rides the hold from the last evidence.
- No new table, DB writer, sensor or dispatcher signal.
- No fix for §9.4 or §9.7 (only: do not speed up §9.7).
- No removal of `current_session_start` in this cycle.
- No D5 on a zone that is Home or in grace; no zone-level return exemption.
- Pending episodes never touch the grace clock.

## 17. Parked
- **Night-anchor unification** (night hold from last evidence). Revival trigger: a raw-evidence night probe shows every
  bedroom's max still-sleeper gap under its night hold with >= 15 min margin.
- **`home_night` on the evidence rule** (Gate B).
- **A dwell for night or legacy states** (needs its own measurement).
- **A zone-level return exemption.** Revive if D0c shows other-room returns within minutes of a wrong away are common.

## 18. Change logs

### REV 6
| Item | Change | Where |
|---|---|---|
| N1 CRITICAL | `last_occupied_time = now` removed. Pending rooms HOLD the zone preset both ways (`_row1_hold_write` pattern, same eligibility, cleared by D5 shed). Never-armed episodes excluded from `E(Z)` and back-fill. INV-D5(d). Exit timer reschedules to the pending lapse without consuming the key. Tick-horizon transit test; drills 67-70 | §2, §3, §4.2, §4.5, §5.2, §5.6, §5b.1, §5b.6, §11d |
| N2 HIGH | L15; `trigger` threaded from the house-state and pre-arrival cycles; `established` on the row; drill 74 | §5.2, §9, §11d |
| N5 HIGH | Alarm sums same-room returns (O1): per-zone distinct events deduped per away; per-zone `same_room_returns_today`; windows reconciled; NM text reads the constant; trap 32 and drill 63 inverted; L9; drill 73 | §0.6, §5.7, §5b.3, §9, §11b, §11d, §14 |
| N3 | `_zone_last_s1_write` stamps only on APPLIED; §19 #12 reworded; drill 71 | §5.2, §19 |
| N4 | Exemption renews only from releases of span >= W arms; ghost-chain test; drill 72 | §4.2, §5b.1, §5b.3 |
| Self-contained | No "as REV n" references remain | whole doc |

### REV 5
| Item | Change |
|---|---|
| HIGH-1 | D5 only on the away -> home edge (last applied S1 write `away`, not pre-arrival); a pending room blocks a vacancy away; zone 3 repro |
| HIGH-3 | Zone exemption dropped; room-only exemption with its own constant; tagged re-arms |
| MEDIUM-2 | Join window `J = min(hold, W)`; Kitchen PIR joined-transit, exit-pulse and Hobeian 31 s limitations; D0c separate counts; C1-D discriminator; Dining radar side-finding |
| MEDIUM (re-check) | Re-enters `_on_room_refresh` at step 5; gates at fire time |
| Tests | Behavioural `test_lighting_session_dwell_removed`; row 55 split; hallway construction check; PIR variant; new scope tests |
| Label | Helper tied to the constant |

### REV 4
| Item | Change |
|---|---|
| D5 | Transit filter added (ruling R3) |
| Knob 47 | Moved; default 1 |
| Lighting-session dwell | Retired |
| Hallway site | Confirmed |
| Card criteria | C1-C4 |
| Drills | 45-57 |
| File | Made self-contained |

### REV 3
| Item | Change |
|---|---|
| R1/R2 | Holds: audit table, common 180; arithmetic as context |
| Threshold | Quick-return threshold 12 |
| Kitchen | Pending confirmation |
| N1 | Three selectors |
| N2 | Lock flag |
| N3 | Scoped refresh hold |
| N4 | Fire-time grace |
| N5 | Override verdict |
| N6 | Drill table of record |
| LOW-1/2/3 | Exemption order; no legacy back-fill; Kitchen |

### REV 2
| Item | Change |
|---|---|
| Shadow machine | Added |
| Evidence rule | `home_day`/`home_evening` only |
| `active` term | Added |
| Nudge-skip seed | Added |
| Vacancy sweep | In the consumer map |
| Lock / queue | Outer `finally`; post-lock re-check |
| Invariants | Periodic-equivalence form |
| Tests | Test-impact table |
| Stamping | Gated on suppressed sources |
| Exit timer | Fixes |
| Misc | Other fixes |

## 19. Departures and notes
1. `guest` and `arriving` stay legacy: the audit excluded them (§1, §8.6).
2. Four existing tests go RED (§11c).
3. The clamp and flow validation are kept.
4. The vacancy sweep timing is accepted, not gated.
5. N5 camera/BLE-after-timeout cost in eight long-timeout rooms; the room exemption makes those re-arms immediate.
6. The quick-return threshold is 12 (checkpoint).
7. ~13 MID retreats at common 180: operator-accepted context (R1/R2).
8. The return exemption is room-only (§5b.3). The brief's original "within its hold" alone would miss the
   wrong-release case.
9. Knob 47 keeps minutes (1 min = 60 s; no migration).
10. The retired lighting-session dwell also covered `home_night`/`guest`/`waking` (behaviour-neutral at live 0).
11. **Resolved:** the quick-return alarm sums same-room returns (O1), which removes the REV 5 disagreement.
12. After a restart, `away_edge` is False (immediate arming) until the zone's first APPLIED S1 write. That allows at
    most one unfiltered transit per zone per restart. Fail-closed could instead delay a real arrival into a Home zone
    by 60 s.
13. The pending hold can delay a legitimate home write by at most `J` when another room of the zone is pending; that
    stay has persisted by then anyway.
