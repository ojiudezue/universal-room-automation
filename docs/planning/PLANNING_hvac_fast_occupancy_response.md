# PLANNING: HVAC fast occupancy response (own release clock, transit filter, event-driven entry and exit) — REV 4

**Cards:**
- `HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1` (revived)
- the parked W2 fast path (`HVAC-W2-OCCUPANCY-TRUTH`, plan `PLANNING_hvac_w2_occupancy_fast_path.md` REV 4)
- **`HVAC-ENTRY-DWELL-ROOM-CLOCK-1`** (Stage B, folded in as D5) [REV 4]

Workstream `HVAC-W2-OCCUPANCY-TRUTH`.

**Status:** REV 4.
- REV 1: two Tier-3 plan reviews, both FIX-PLAN.
- REV 2: folded them; its re-review found the design sound (text edits only).
- REV 3: folded those edits plus operator hold rulings R1/R2.
- REV 4: adds D5, the transit filter (ruling R3).

Tags: `[REV 2 #n]`, `[REV 3 <id>]`, `[RULING Rn]`, `[REV 4]`. Change logs: section 18. Departures: section 19.
**A focused plan re-review of D5 is needed before build.** This file is self-contained: every REV 3 section is inline.

**Checkpoint items needing explicit operator confirmation before deploy:**
1. Kitchen exception drop (7.1).
2. Quick-return alarm threshold 12 (14.1).
3. D5 recent-return exemption (5b.3) [REV 4].
4. Setting knob 47 to 1 minute (10b) [REV 4].

**Base:** current `develop` after v5.103.19 (night-tail B shipped). `hvac_zones.py` lines refreshed; `hvac.py`
unchanged since REV 1.

**Operator decision (2026-09-27 ~22:00, verbatim):** "We wanted faster responses. This is nuts." / "fast path catches
it. The room type hold blunts it. Do it". Rulings R1-R3: section 0.6.

**Design premise, with its limits:**
1. A per-room-type hold blunts radar misses of still people. **It is the ONLY protection for someone who stays
   still.** A still person produces no new evidence, so the fast path cannot catch them. It reacts only once they move
   again [REV 2 #2].
2. An event-driven fast path re-arms a re-detected room in seconds instead of at the next 5-minute tick.
3. A brief pass-through (under 60 s) of a cold room does not switch a zone to Home [REV 4].

| Deliverable | What | Code? |
|---|---|---|
| D0 | Baselines (latency, write rate, flap rate), residual re-probe, `home_night` gate probe | probe only |
| D1 | New release clock in `home_day`/`home_evening`; today's machine kept as a shadow; other states unchanged | yes |
| D2 | Event-driven zone decision on entry AND exit | yes |
| D3 | Vacancy grace re-check | no (knob) |
| D4 | Operator config: clear Jaya Bedroom's day override; set knob 47 to 1 | config |
| **D5** | Transit filter: a cold room arms only after 60 s of persisting evidence (evidence states only). Knob 47 moves from the lighting-session dwell to this; the lighting-session dwell is retired | yes |

---

## 0. Institutional context verified

### 0.1 Mandatory read
**`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`:** read completely; re-read for REV 2.
- v5.103.19: D8 night tails follow `HVAC_NIGHT_HOLD_STATES` = (`sleep`, `waking`) (`hvac_const.py:934`). `home_night`
  uses the day table. `FAN_TRUST_STATES` is unchanged.
- W1-B shipped (v5.103.18, §9e four gates).
- §3.2 records the dwell's **denomination defect** (it reads the LIGHTING clock) and points at the Stage B card. D5
  resolves it.
- Relevant sections: §2, §3.1-§3.3, §9c, §9d, §9.4, §9.7, §10.
- **C18:** with dwell 0, entry = wait for the next tick.
- **C24:** HVAC occupancy is not a faster clock today. This plan builds one; it does not claim it exists.
- **§10:** no C1-C25 claim is re-asserted (no 1-minute tick C8; suppression windows 15 s temp / 120 s preset
  C17/C23; S1 manual guard superseded by §9e C25).

**State-of-play drift to fix in the build commit:**
- §3.2 says knob 48 = 10 and §8 says dwell = 2. Live values: grace 5, constrained 5, dwell 0.
- §3.1 still cites pre-B line numbers.
- The §3.2 dwell row must be rewritten to describe D5.

### 0.2 Other docs and cards read
| Source | Use |
|---|---|
| Card `HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1` | Measured disposition; per-type tails; `_last_motion_time` misses camera/BLE. Kitchen timeout 600 -> 300 s (operator, 2026-09-27, verified live) |
| Card `HVAC-ENTRY-DWELL-ROOM-CLOCK-1` [REV 4] | Arm only when raw presence persists N s; keep the post-arm hold; hallways excluded by construction; two onset-anchored dwell plans superseded; measure the flap rate first. Operator 2026-09-26: "Room clock is not good for HVAC" |
| `AUDIT_hvac_raw_evidence_gaps_2026_09_26.md` | Per-type MID/LATE; T >= max MID - G. Day bucket = `home_day` + `home_evening` (82.4 h). Excluded `away`/`arriving`/`guest` (§8.6). `home_night` lumped with `sleep`/`waking` |
| `PLANNING_hvac_w2_occupancy_fast_path.md` REV 4 + card `HVAC-W2-OCCUPANCY-TRUTH` | Design reused (section 13). The REV 4 re-review's four HIGHs are known only from the card summary. The card's `next` defines the flap metric |
| `AUDIT_hvac_fast_path_rate_2026_09_26.md` | 16.6 zone-cold edges/day; cycle p95 27.6 s; L=60 denies 0/114 |
| `PLANNING_hvac_night_tail_follows_sleep.md` (B shipped) | `HVAC_NIGHT_HOLD_STATES` reused |
| Cards `HVAC-FAST-PATH-FAN-WARM-EDGES-1`, `HVAC-HOLD-SIZING-ALL-ROOMS-1`, `HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1`, `HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1`, `HVAC-WRITE-CONFIRMATION-ORACLE-1` | Section 12 |
| vibememo 153 | Why the fast path was parked |

### 0.3 Code surveyed (develop, post v5.103.19)

**`coordinator.py`**
- Occupancy block `:3538-3643`; `_last_motion_time = now` only on Tier-1 activity (`:3589`).
- Camera override `:3663-3697`: source `"camera"` (`:3677`), failsafe guard (`:3667`).
- BLE chain-hold `:3699-3908`: source `"ble"` (`:3851`), failsafe guard (`:3706`), cap `:3810-3847`.
- Sources: fan-demoted `:4113`; failsafe `:4361`, with `_failsafe_fired = True` at `:4369`.
- Override switches `:4790-4811`; skip-first `:4825`; `apply_fan_recheck_release` `:5249-5280`.
- Poll 30 s + 0-5 s jitter (`:625-631`); event refresh within 2 s (`:1395-1411`).
- Debounce anchor `_occupancy_first_detected` `:3544`; accessor pattern `get_became_occupied_time` `:5384`.

**`hvac_zones.py`**
- `update_room_conditions` `:566`: entry loop `:611-647`, `_classify_all_rooms` `:665`, zone loop `:666`,
  `clear()` `:667`, absent add `:687`, `room_occupied` `:718`.
- **Hallway exclusion `:725-736`** (confirmed): `room_type == ROOM_TYPE_HALLWAY` -> `hvac_occupied = False`,
  `arm_source = "hallway_excluded"`, still marked seen.
- Rollup `:772-789`; `current_session_start` written `:786-789`.
- `get_zone_status_attrs` `:791`.
- `_effective_hvac_hold_seconds` `:977-1049`: clamp `:1031-1047`, selector `:1049`.
- `_compute_hvac_occupied` `:1051-1126`; `conditioning_retreat_ok` `:1525`; `hvac_occupied_diag` `:1588`.

**`hvac.py`**
- `_zones_written_this_cycle`: init `:455`, reset `:1879`, add `:3194`; read by `hvac_override.py:4713`.
- `_zone_entry_dwell` init `:562`.
- `_async_decision_cycle` `:1583`; `_track_task` `:1644`; `_run_decision_cycle` `:1873`.
- `_apply_house_state_presets` `:2132-3320`:
  - consensus gate `:2156`; heat_cool enforcer `:2227`; arriving `:2261`; grace choice `:2271-2275`; loop `:2282`
  - row-1 + vacancy sweep `:2339-2426`; D6 `:2437`; D5 `:2568`
  - **lighting-session dwell skip `:2735-2748`** — the ONLY reader of `_zone_entry_dwell` and
    `current_session_start` (grep)
  - D7 `:2780`; transient hold `:2860`; W1-B gates `:2918`; S1 write `:3125-3271`; DPM `:3319`
- `_handle_energy_constraint` `:3843`; `_handle_zm_zones_updated` `:3908` (pops `:3987`, `:4010`).
- `_execute_vacancy_sweep` `:4266`; `_expire_pre_arrival_zones` `:4624-4654`; `_compute_zone_presence_states` `:4775`.
- `get_mode_attrs` `:5411`; `async_teardown` `:5555`.

**Knob 47**
- `number.py:415-502` `ZoneEntryDwellNumber`: name `47 · Entry Wait (min)`, MINUTES, 0-15, step 1, BOX.
- `hvac_const.py:416-421`; `config_flow.py:5929`, `:6475-6478`; in-place apply `__init__.py:7379-7390`.
- Reset button `button.py:843-860`; migration `__init__.py:719-757` (DONE live); strings `strings.json:1166`, `:1197`.

**Grace writers outside `number.py`:** `button.py:857-858`; `__init__.py:7339`, `:7353`, `:7565`.

**Elsewhere**
- `hvac_strategy.py`: `strategy_for` `:254-266` (registry miss -> uncached generic); `last_sent` `:142`; `hold_preset`
  no-op `:187-197`.
- `hvac_override.py:174` (`SUPPRESS_TTL_SECONDS_PRESET = 120`); `sensor.py:13684-13745` (zone-intelligence sensor).
- HA `update_coordinator.py:170-182` and `:528-533`: listeners called after every successful refresh.

**Live config**
- Only Jaya Bedroom has a day override (60, night 5400); 9 common rooms have night 90.
- Timeouts: most 300 s, up to 900 s.
- `switch.kitchen_override_vacant` restores `off`.

**Tests read**
- `test_hvac_night_hold_follows_sleep.py` (all).
- `test_hvac_vacancy_hold_ui_defaults.py:140-171`.
- `test_zzz_hvac_conditioning_demand.py:240-331`, `:505-523`, `:636-716`, `:774-775`, `:903-916`.
- `test_v5_103_8_hvac_knobs_and_obs.py:120-170`, `:359-430`.
- `test_hvac_presence_timer_knobs.py`; `test_part2_ec_hc_writeback.py:446/:633/:727/:1142`.
- `test_cm_reload_suppression.py`; `test_dpm_cleanup_and_labels.py:179`.

### 0.4 Config-first check
| Candidate | Solves it? | Why |
|---|---|---|
| Room `occupancy_timeout` | Partly (Kitchen stopgap) | Still two tick quantizations; no effect on entry or re-arm |
| Per-room holds | No | The hold starts only after the lighting timeout today |
| Knob 48 grace (5) | No | Section 7.2 |
| Shorter `HVAC_DECISION_TICK` | Rejected | Carrier call-rate bound; whole-house cycle |
| Jaya Bedroom day override 60 | **Change (D4)** | Under the new clock 60 counts from the last evidence; the audit shows MID retreats at 60 |
| Knob 47 dwell as it is today, set to 1 [REV 4] | No | Reads the lighting session: a 10 s transit holds lighting ~300 s, so the zone still flips. Also delays every entry to the next tick (C18) |
| Hallway room type [REV 4] | Already done | Hallways never arm (`hvac_zones.py:725-736`). D5 targets non-hallway pass-throughs (Kitchen, Dining, Breakfast Nook, pantries) |

### 0.5 Prior-art scan: REUSE or BUILD
| Piece | Verdict | Symbol / reason |
|---|---|---|
| Evidence-rule hold table | **REUSE, change values** | `ROOM_TYPE_HVAC_HOLD` `const.py:1219` |
| Shadow tail table | **BUILD (frozen copy, every type explicit)** | `ROOM_TYPE_HVAC_TAIL_LEGACY` |
| Shadow selector | **REUSE, behaviour unchanged** | `_effective_hvac_hold_seconds` `hvac_zones.py:977`: legacy table, night table, overrides, clamp |
| Evidence and display selectors | **BUILD** | `_evidence_hold_seconds`, `_display_hold` |
| Night table, overrides, clamp, flow validation | **REUSE unchanged** | `const.py:1230-1253`; `hvac_zones.py:1031-1047`; `config_flow.py:599-610` |
| State tuples | REUSE `HVAC_NIGHT_HOLD_STATES`; **BUILD** `HVAC_EVIDENCE_RULE_STATES` | |
| Evidence timestamp, active flag, onset | **BUILD (fields + 3 accessors)** | No existing field fits: `_last_motion_time` misses camera/BLE; `_last_trigger_time` = rising edges only; `_last_occupied_time` includes the timeout; `_occupancy_first_detected` is a debounce anchor cleared on inactivity |
| Camera/BLE evidence | **REUSE the override blocks' verdict** | `data[STATE_OCCUPANCY_SOURCE] in ("camera", "ble")` |
| Room-change event source | **REUSE HA API** | `DataUpdateCoordinator.async_add_listener`; pattern `aggregation.py:1990` |
| Listener lifecycle | **REUSE** | One `SIGNAL_ROOM_ENTRY_LIFECYCLE` subscription (`signals.py:199`); subscribe, then enumerate |
| Zone-scoped decision | **REUSE + parameterise** | `_apply_house_state_presets(zone_filter, trigger, edge_ts)`, `update_room_conditions(zone_ids)` |
| Lock, tasks, timers | **REUSE** | `_decision_cycle_lock`, `_track_task`, `async_call_later` |
| Same-tick nudge skip | **REUSE + extend** | `_zones_written_this_cycle`, seeded from `_zone_last_s1_write` |
| Limiter exemption | **REUSE** | `_zone_last_s1_write` first, then `strategy_for(...).last_sent` |
| Ledger, attrs, NM, probes | **REUSE** | `preset_change` details; `get_mode_attrs`; `get_zone_status_attrs`; `hvac_occupied_diag`; NM path; `scripts/probes/` |
| Kill switch | **BUILD (one switch)** | Pattern `HVACPreArrivalSwitch` `switch.py:4229` |
| Dwell knob [REV 4] | **REUSE, semantics moved** | Knob 47 / `CONF_HVAC_ZONE_ENTRY_DWELL` / `_zone_entry_dwell`; unit stays minutes |
| Arming episode state [REV 4] | **BUILD** | `_hvac_episode_start`, `_hvac_ev_released_at`, `_zone_vacancy_away_at` |
| Quick-return window [REV 4] | **REUSE** | `HVAC_QUICK_RETURN_WINDOW_S` bounds the D5 exemption |
| Lighting-session dwell [REV 4] | **RETIRE** | `hvac.py:2735-2748`; `current_session_start` loses its only reader |

Memory consulted: suppression-needs-discharge, wire-in anchors, hollow anchors, marginal-benefit,
measure-before-build, coincidental-equality, unrestored-drill, pyc staleness, zone-away-home-night gap.

### 0.6 Operator decision ledger
| # | Date | Ruling (verbatim) | Effect |
|---|---|---|---|
| R0 | 2026-09-27 ~22:00 | "fast path catches it. The room type hold blunts it. Do it" | Build the cycle |
| R1 | 2026-09-27 | "Shorter. I already articulated why it's not a big deal. We're measuring things that don't have the fast and slow protection and we're measuring without the time stacking." | Audit table for holds (rejects the 360/150 margin sizing); Kitchen exception dropped |
| R2 | 2026-09-27 | "3mins" | Common-area evidence hold = 180 s |
| R3 | 2026-09-27 | "I think you should add this to the fast response plan. We want no seams. My instinct is it should go to 1 minute to allow for transients also though hallways are now excluded right?" | Stage B folded in as D5, 1 minute. Hallways: yes, excluded (0.3) |

**Rationale for R1/R2 (the operator's, as recorded):**
- The audit's margin figures were measured on today's design, with no re-arm fast path and with the stacked timers
  (lighting timeout + tail + tick).
- The quick-return trip-wire and the kill switch measure and bound the residual live. **The quick-return trip-wire is
  the live measure of this choice.**

---

## 1. Marginal-benefit note
- The audit weighed release speed alone. The operator added event-driven re-arm, which works only when the person moves
  again. The plan keeps today's machine underneath and limits the new rule to the audit-measured states. Hold values
  are rulings; their arithmetic is context (7.2).
- **D5 [REV 4].** Today a 10 s pass-through of a cold room in an away zone always flips it: the lighting occupancy
  lasts about 300 s, longer than a tick. With fast entry that flip would come within seconds, so D5 keeps "faster" from
  meaning "more flaps".
- Cost of D5: 60 s extra on a genuine arrival into a cold zone, and nothing on re-arms after a recent release. Its risk
  is one more per-room timer and state, zone-scoped, reset cold on restart.

---

## 2. Falsifiable invariants

**Definitions**
- `ev(R)`: last evidence time. `active(R)`: evidence at the latest refresh. `onset(R)`: start of the current active
  stretch.
- `hold_ev(R)`: from `_evidence_hold_seconds`.
- States: evidence = (`home_day`, `home_evening`); night = (`sleep`, `waking`); legacy = every other state.
- `release(R)`:
  - evidence states: `ev + hold_ev`
  - night states: the later of the shadow's tail end and `ev + hold_ev`
  - legacy states: the shadow's tail end
- `E(Z)`: max `release(R)` over live non-hallway rooms of zone Z.
- `P(Z, t)`: what a periodic cycle would write for Z at `t` (possibly nothing).
- `W` = knob 47 × 60 s.
- **Cold room** [REV 4]: in an evidence state, output False, AND not released within `HVAC_QUICK_RETURN_WINDOW_S`, AND
  its zone has had no vacancy away within that window.
- **Persisted** [REV 4]: `W == 0`, OR `(active and now - episode_start >= W)`, OR `ev - episode_start >= W`.

**INV-1 (re-arm = periodic outcome within the SLA)**
- Trigger: a live non-hallway room of Z has an evidence advance at refresh `t_r` while Z's stored fused value is False.
  For a cold room, the trigger is "persisted became true", observed by the listener or by the arm re-check at
  `episode_start + W`.
- Required: a zone-scoped run for Z starts by `t_r + 45 s` and issues exactly `P(Z, t_run)` for Z only.
- After a `vacant_past_grace` away with target home/sleep, `P` is a home/sleep write unless one of the exceptions
  below holds. Non-cold rooms are never subject to D5.

| INV-1 exception | Outcome |
|---|---|
| Row-1 transient-room hold | suppressed row |
| D5 shed / D6 stale | effective away |
| W1-B gates (a/b), (c), (d), (e) on a `manual` zone | `preset_change_deferred` |
| Consensus defer gate | call skipped |
| `arriving`, egress pause, observation mode, zone intelligence off | no write |
| D7 night trust | suppression row |
| §9.7: status already reads the target and `last_sent` matches | `SKIPPED_ALREADY_CORRECT` |
| Kill switch off, zone tripped, boot-settle, teardown | tick backstop <= 300 s |
| Cold room not yet persisted [REV 4] | no arm (transit filter) |

**INV-D5 (transit filter, evidence states) [REV 4]**
- (a) A cold room whose episode spans under `W` (`ev - episode_start < W` and not active at `episode_start + W`) never
  produces `hvac_occupied = True`.
- (b) A cold room whose evidence persists at least `W` produces True by `t_persist + 45 s`, where `t_persist` is the
  first moment persistence is observable. The zone then gets `P(Z, t)`.
- (c) D5 never applies in night or legacy states, never to hallways, and never to non-cold rooms.

**INV-2 (no early vacancy away, evidence states)**
- No `vacant_past_grace` away for Z at `t` while any live non-hallway room has output True, or has an armed episode
  with `release > t - G`.
- A cold room inside its first `W` seconds does not count; that is the transit filter by design.
- The exit run recomputes, so a room that became persisted is armed before the away decision.

**INV-3 (exit = periodic outcome at the due time, once)**
- In evidence and night states, with no new evidence, a `fast_exit` run starts in
  `[E + G + SLACK, E + G + SLACK + SLA]` and issues `P(Z, t_run)`.
- At most one run per episode, key `(Z, E(Z))`. A deferral (e.g. gate (e)) consumes the key and the tick owns the rest
  of the episode.
- `G` is the live grace read when the timer fires.

**INV-4 (zone scope)**
- A fast run writes climate only for Z, through S1. Its only other actuation is Z's vacancy sweep.
- Accepted house-wide effects:
  - (a) a display-only `zone_presence_state` refresh for all zones;
  - (b) `_expire_pre_arrival_zones`, which may clear other zones' pre-arrival flags and schedule fan-off for timed-out
    ones (time-driven; the next tick would do the same).
- It never calls the heat_cool enforcer, egress tick, `check_ac_reset`, fans, covers, predictor, anomaly observations,
  DPM, arrester sweeps or the Carrier freshness check.
- It never changes another zone's `room_conditions`, `last_occupied_time` or `continuous_occupied_since`.

**INV-5 (shadow, night, legacy)**
- Today's machine runs byte-for-byte on every pass, in every state, and alone owns `_hvac_armed`,
  `_hvac_prev_state_occupied` and `_hvac_tail_until`.
- Night and legacy output is at least the shadow's output.
- In legacy states there is no `last_occupied_time` back-fill, no exit timer and no dwell. So `home_night`, `guest`,
  `arriving` and `away` behave as v5.103.19 at the live dwell value 0.
- A room crossing from an evidence state into `sleep` mid-lighting-timeout is still held by the shadow.

**Equivalence (for reviewer B).** A fast run for Z at `t` equals `P(Z, t)`. The seed set must include cases where S1
writes (home from away, away from home, sleep, manual write-through under open gates) and every exception row. A seed
set with no write fails the test's own precondition.

---

## 3. Producer and consumer map for `hvac_occupied`

### 3.1 Producer
| Step | After |
|---|---|
| Shadow (every state) | Today's machine on `data["occupied"]`; tail from `_effective_hvac_hold_seconds` |
| Evidence-state output | Non-cold: `active OR now < ev + hold_ev`. Cold: that AND persisted (D5). The evidence term is held through refresh failures for up to 600 s after `ev` |
| Night-state output | `shadow OR active OR now < ev + hold_ev` (no dwell) |
| Legacy-state output | shadow (== v5.103.19) |
| Rollup | As today; back-fill `last_occupied_time = max(lot, E)` when fused False, in evidence and night states only |

Dependency health:
- The stamp depends on the room refresh (event-driven within 2 s; poll 30-35 s) and on the existing fusion filters.
- Only the Living Room has a firing camera; 3 phones for BLE.

### 3.2 Consumers
| Consumer | Site | Kind | Effect |
|---|---|---|---|
| Zone rollup `any_room_hvac_occupied` | `hvac_zones.py:178` | feeds below | Flips sooner in evidence states; re-arms on evidence; cold rooms after 60 s |
| `conditioning_retreat_ok` -> row-1 vacancy away | `hvac_zones.py:1525`; `hvac.py:2339-2426` | TRUST | INV-2/INV-3 |
| Vacancy sweep | `hvac.py:2416-2426` -> `:4266` | ACTUATION (Z's lights/fans) | Runs for Z in fast runs; 5.9 |
| Row-1 transient hold | `hvac.py:2360-2392`, `:2860-2911` | TRUST | Unchanged |
| D6 stale failsafe | `hvac.py:2437-2539` | TRUST | Fires less |
| D5 energy-shed coast defer | `hvac.py:2643-2709` | TRUST | Ends sooner when a zone empties |
| D7 night trust | `hvac.py:2780-2852` | TRUST | Night >= today |
| D9 compose-away (dormant) | `hvac.py:3484-3518` | TRUST | Tick only |
| Arrester row-10 comfort delay | `hvac_override.py:2513-2557` | TRUST | Expires sooner in an emptied zone |
| Pre-cool F8 / pre-heat F9 | `hvac_predict.py:583`, `:1420` | TRUST | Tick only |
| Grace math | `hvac_zones.py:772-780`; `hvac.py:2340-2344` | TRUST | Back-fill |
| `zone_presence_state` | `hvac.py:4775` | DISPLAY | Fast runs refresh it |
| Zone-intelligence sensor | `sensor.py:13684-13745` | DISPLAY | Fast-run cadence |
| W1-B four gates | `hvac.py:2918-2996` | TRUST (S1 intent) | Same S1 body |
| Arrester nudge skip | `hvac_override.py:4713` | TRUST | Seeded from recent S1 writes |
| Lighting-session dwell | `hvac.py:2735-2748` | TRUST | **Retired; replaced by D5 in the producer** [REV 4] |
| Fans | `hvac_fans.py:761`, `:997` (LIGHTING) | — | Unaffected |
| Pre-arrival | `hvac.py:4567-4654` | — | Full cycle waits behind a fast run; expiry runs in fast runs |
| Presence D6 source 4 | `presence.py:2147-2159` (LIGHTING) | — | Unaffected |
| Per-room `binary_sensor.<room>_<room>_hvac_occupied` | `binary_sensor.py:745-920` | DISPLAY | Attrs `rule`, `last_evidence_at`, `release_at`, `episode_start`, `armed_at`, `dwell_s`; `hvac_vacancy_hold_s` via `_display_hold` |
| Zone status sensor | `hvac_zones.py:791-895` | DISPLAY | `hvac_empty_since`, `away_due_at` |
| `sensor.ura_hvac_coordinator_mode` | `hvac.py:5411` | DISPLAY | Fast-path counters |
| `optimization.py:2398-2430` | `continuous_occupied_since` | analysis | Shorter spans |

---

## 4. D1: HVAC's own release clock

### 4.1 Evidence stamp (`coordinator.py`)
- **Fields:** `_last_hvac_evidence_time: datetime | None`, `_hvac_evidence_active: bool`,
  `_hvac_evidence_onset: datetime | None` [REV 4].
- **Accessors** next to `get_became_occupied_time` (`:5384`): `get_last_hvac_evidence_time()`,
  `is_hvac_evidence_active()`, `get_hvac_evidence_onset()`.
- **One stamp site**, after the override-switch block (after `:4811`, before `:4825`):
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
      self._hvac_evidence_onset = now                    # [REV 4] start of this active stretch
  if evidence_now or (self._hvac_evidence_active and not suppressed):   # falling-edge stamp
      self._last_hvac_evidence_time = now
  self._hvac_evidence_active = evidence_now
  ```
- On a suppressed tick: no stamp, and no falling-edge stamp on the next tick.
- `apply_fan_recheck_release` (`:5249`, outside a refresh) sets `_hvac_evidence_active = False` and does not stamp.
- **Camera/BLE count only after the room's own lighting timeout ends,** because the override blocks run only then.
  They inherit their failsafe guards, the BLE chain rule (extend, never create) and the BLE cap.
  - Where timeout - `hold_ev` > 300 s, a still person held only by BLE can release, retreat, then re-arm when BLE takes
    over: a two-write flap. The D5 recent-return exemption makes that re-arm immediate.
  - Rooms at the ruled holds: Master Bathroom 720, Jaya Bathroom 720, Exercise Room 720, Oji Vanity 420, Study A 420,
    Kitchen Pantry 380, Ziri Bathroom 360, Game Room 360.
  - Living Room (the only firing camera): 300 - 180 = 120 < 300, so no flap.
- Override Vacant gives no evidence; the room releases at last evidence + hold (§9c text updated in the build).
- All three fields are in memory; `None`/False after a restart until the first evidence.

### 4.2 Producer: shadow plus rule output (`hvac_zones.py`)
`_compute_hvac_occupied` keeps its body as the **shadow** and gains `last_evidence`, `evidence_active`, `onset`,
`refresh_ok`, `entry_dwell_s` keywords.

1. **Shadow.** Runs exactly as today (`:1073-1126`) with `hold_s` from `_effective_hvac_hold_seconds` (legacy table
   outside night). Only the shadow writes `_hvac_armed`, `_hvac_prev_state_occupied`, `_hvac_tail_until`,
   `_hvac_arm_source`. Result: `shadow_out`.
2. **Evidence term.** `hold_ev = _evidence_hold_seconds(room_type, override_day)`;
   `ev_out = evidence_active or (last_evidence is not None and now < last_evidence + hold_ev)`.
   Store `_hvac_day_release_at[room]`.
3. **Refresh-failure hold (evidence states, evidence term only).** If `refresh_ok is False` and the previous output was
   True, keep `ev_out = True`, for at most `HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S` = 600 s after `last_evidence`
   (longest hold 240 + ~10 polls). Night and legacy states: the shadow rides stale data, as today.
4. **D5 (evidence states only) [REV 4].** If the room is cold (5b.1) and `W > 0`: `ev_out = ev_out and persisted`.
5. **Output.**
   - evidence -> `ev_out`
   - night -> `shadow_out or ev_out`, where `ev_out` has no dwell
   - legacy -> `shadow_out`
   - Store in `_hvac_output` and `_hvac_rule`; stamp `_hvac_ev_released_at[room]` on an evidence-state True -> False.
   - The evidence branch never writes the shadow's dicts.

Readers use `isinstance(ev, datetime)` / `isinstance(onset, datetime)` (a MagicMock counts as `None`) and
`evidence_active is True`; `refresh_ok = coordinator.last_update_success is not False`. The `active` term covers hold 0
and holds shorter than a poll.

### 4.3 States
- `sleep` / `waking`: shadow OR evidence (no dwell).
- `home_night`: legacy until D0c Gate B.
- `guest`, `arriving`, `away`, `None`: legacy (unmeasured).

### 4.4 Selectors
| Selector | Returns | Callers |
|---|---|---|
| `_effective_hvac_hold_seconds` (signature and logic unchanged) | Shadow tail: night table in night states, `ROOM_TYPE_HVAC_TAIL_LEGACY` otherwise; overrides; clamp | Shadow only |
| `_evidence_hold_seconds(room_type, override_day)` (new) | `override_day` or `ROOM_TYPE_HVAC_HOLD.get(type, DEFAULT_HVAC_VACANCY_HOLD)` | Evidence term, `room_release_at` |
| `_display_hold(room_type, house_state, override_day, override_night)` (new) | `(hold, rule)`, rule ∈ `evidence` / `night` / `legacy` | `binary_sensor.py:894` |

The clamp and flow validation are unchanged. The shadow's night >= legacy-day comparison matches today (common night
90 >= legacy 60), and the night OR gives monotonicity against the evidence hold.

### 4.5 Exact release instant
- **Back-fill** on a fused-empty pass, in evidence and night states only: `last_occupied_time = max(lot, E(Z))`.
- **`room_release_at(room)`** reads the live accessors. It returns `None` while `active`, while the shadow rides
  `occupied` (night/legacy), or while a cold room has an unarmed episode that could still persist [REV 4].
- **`zone_release_at` / `zone_away_due_at(Z, grace_s)`:** as defined.

### 4.6 Tables (`const.py`, rung 1) [RULING R1, R2]
```
ROOM_TYPE_HVAC_HOLD: Final = {            # evidence rule; values = audit table + operator rulings
    ROOM_TYPE_CLOSET: 60, ROOM_TYPE_INFRASTRUCTURE: 60,
    ROOM_TYPE_GENERIC: 120, ROOM_TYPE_UTILITY: 120,
    ROOM_TYPE_MEDIA_ROOM: 120, ROOM_TYPE_GARAGE: 120,
    ROOM_TYPE_BATHROOM: 180,
    ROOM_TYPE_COMMON_AREA: 180,           # operator ruling R2 "3mins"
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
- The comment cites the rulings (0.6) and names the quick-return trip-wire as the live check.
- `DEFAULT_HVAC_VACANCY_HOLD` (60) remains the unknown-type fallback.

### D1 acceptance
- **Anchors:**
  - `test_evidence_state_ignores_lighting_timeout`
  - `test_home_evening_to_sleep_mid_timeout_stays_held` (drill: evidence branch writes `_hvac_armed` -> RED)
  - `test_shadow_dicts_untouched_by_evidence_branch`
  - `test_home_night_is_legacy_until_gate`, `test_guest_arriving_away_are_legacy`
- **Holds and refresh failure:** `test_hold_zero_holds_while_active`,
  `test_hold_shorter_than_poll_no_drop_while_on`, `test_refresh_failure_hold_evidence_states_only_and_bounded`.
- **Stamping:** `test_camera_ble_stamp_only_from_override_verdict`,
  `test_no_stamp_on_fan_demoted_failsafe_recheck_sources`, `test_override_vacant_blocks_stamp`,
  `test_falling_edge_refresh_stamps`, `test_fan_recheck_release_clears_active`, `test_ble_cap_stops_stamp_after_cap`.
- **Back-fill:** `test_last_occupied_time_backfilled_to_exact_release`, `test_no_backfill_in_legacy_states`.
- **Tables:**
  - `test_evidence_hold_values`: closet 60, infra 60, generic 120, utility 120, media 120, garage 120, bathroom 180,
    **common 180**, bedroom 240, hallway 0. Independent literals.
  - `test_legacy_tail_is_frozen_v5_103_19`: every type explicit; independent literals.
  - `test_selectors_split`.
- **Other:** `test_per_room_day_override_wins`, `test_accessor_fallback_uses_isinstance_datetime`.
- **Live:** in `home_day`, for 10 releases across >= 3 types:
  - `release_at == last_evidence_at + hold_ev`;
  - the off transition lands by `release_at + 335 s`.
  - Discriminator: under the old rule the HVAC value could never drop while the lighting value is on.

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
                                          entry_dwell_s=self._zone_entry_dwell * 60)
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
                self._fast_path_running = False                             # cleared inside the lock
    finally:
        self._fast_path_queued.discard(zone_id)                             # every exit path
```
`_fast_path_gates_open` means all of: not tearing down, enabled, boot-settle done, kill switch on, not observation
mode, zone intelligence on, zone still in `zm.zones`, zone not tripped.

### 5.2 `_apply_house_state_presets(*, zone_filter=None, trigger="periodic", edge_ts=None) -> bool`
- `zone_filter is None`: byte-identical to today, except the lighting-session dwell skip (`:2735-2748`) is removed
  (D5).
- With `zone_filter`:
  - skip the heat_cool enforcer (`:2227-2256`);
  - loop-top `continue` for other zones (`:2282`);
  - skip DPM (`:3319-3320`).
  - Consensus gate, `arriving`, every per-zone rule and Z's vacancy sweep run as today.
- `trigger`, `edge_ts`, `zone_empty_since` (on away rows) and `exempt_reason` (D5) go into the `preset_change` details.
- Every S1 write sets `_zone_last_s1_write[zone] = (preset, utcnow)`.
- A `vacant_past_grace` away also sets `_zone_vacancy_away_at[zone]` [REV 4].
- Returns whether a write was applied.

### 5.3 `update_room_conditions(house_state, zone_ids=None, entry_dwell_s=None)`
- `zone_ids` set: skip other zones BEFORE `zone.room_conditions.clear()` (`:667`).
- `_coordinator_absent_this_pass` is built in the entry loop (`:611-647`) for every zoned room whose coordinator is
  `None`, and the add at `:687` is removed. The set stays pass-complete under a zone filter.
- `_classify_all_rooms` still runs over all rooms.
- `entry_dwell_s` feeds D5 (`None` -> 0).

### 5.4 Entry trigger
Setup: subscribe to `SIGNAL_ROOM_ENTRY_LIFECYCLE` first, then enumerate existing room coordinators and attach
`async_add_listener(partial(self._on_room_refresh, entry_id))`. Attach is idempotent (release-then-attach):
`loaded` attaches, `unloaded` releases, `options_updated` re-attaches.

`_on_room_refresh(entry_id)` (sync), in order:
1. Gates.
2. Skip hallways; resolve the zone from `zm.zones` live.
3. Evidence advance. `None` never counts and never overwrites; the first non-`None` counts.
4. **D5 [REV 4]:** update the arming episode. If the room is cold, not persisted, and the zone is cold: schedule the
   arm re-check and return.
5. Zone-cold gate (stored fused True -> return).
6. Tripped zone -> count, return.
7. Per-zone limiter `HVAC_FAST_PATH_MIN_INTERVAL_S` (60 s) on entry runs. **Exempt** iff
   `_zone_last_s1_write[zone][0] == "away"` (checked first), else if
   `strategy_for(...).last_sent(entity, "set_preset_mode") == "away"`. Never `preset_mode`.
8. Dedup (`_fast_path_queued`).
9. Queue `fast_entry` with `edge_ts = now`.

### 5.5 Lock rules
- Fast runs wait for the lock.
- `_async_decision_cycle`:
  - waits if the lock holder is a fast run (`_fast_path_running`, set only inside the lock);
  - skips if the holder is a full cycle;
  - after acquiring, skips if a full cycle started after it was scheduled.
- At `_run_decision_cycle` entry (`:1879`), `_zones_written_this_cycle` is seeded with zones whose `_zone_last_s1_write`
  is within `SUPPRESS_TTL_SECONDS_PRESET` (120 s). A fast write seconds before a tick still blocks that tick's nudge.

### 5.6 Exit timer
- `_schedule_exit_timer(Z)` runs at the end of every full cycle (all zones) and every fast run (its zone).
- Preconditions: kill switch on, zone intelligence on, not observation mode, zone established, house state in
  evidence or night states, target home/sleep, not already sent away, not egress-paused, not tripped.
- `due = zone_away_due_at(Z, grace_s) + HVAC_FAST_PATH_EXIT_SLACK_S`; `None` -> no timer.
- One-shot key `(Z, zone_release_at)`; a fired key is never rescheduled (stops the §9.7 loop from speeding up).
- **The callback recomputes `due` from live evidence and the live grace** (chosen as at `hvac.py:2271-2275`). Not due
  -> lazy reschedule; due -> record the key and queue `fast_exit` (exempt from the limiter).
- **The exit run's producer pass applies D5**, so a room that became persisted during grace is armed before S1
  decides [REV 4].
- Reschedule hooks (`number.py` grace setters, `_handle_energy_constraint` `:3843`) only reduce latency. Writers that
  bypass them (`button.py:857-858`, `__init__.py:7339/7353/7565`) can at worst delay a fire to the old due time.
- Pruned zones cancel their timers (`:3987`, `:4010`).

### 5.7 Ceiling, runaway guard, trip-wire, kill switch, restart
- **Write ceiling:** more than 6 fast-run writes per zone per rolling hour -> one NM; the zone is tick-only until
  local midnight.
- **Runaway guard:** more than 30 fast runs per zone per hour -> same fallback + NM. Lazy reschedules do not count.
- **Quick-return trip-wire:** a `fast_entry` within 900 s of a `vacant_past_grace` away on that zone counts; at 12 per
  zone per day, one LOW NM. It is the live measure of the hold rulings.
- **Kill switch** `31 · Fast Room Response` (default ON). OFF = tick timing; the D1 clock and D5 still apply at the
  next pass.
- **Global limiter G: dropped.** Fast runs are zone-scoped and serialised; the per-zone ceiling bounds Carrier calls.
- **Restart:** counters, trips, `_fp_last_ev`, `_zone_last_s1_write`, `_zone_vacancy_away_at`, episodes and timers are
  all in memory and reset. The first full cycle reschedules. Rooms start cold.

### 5.8 Teardown
Set `_tearing_down = True`. Before the first `await` (`hvac.py:5575`): release listeners, cancel exit and arm timers,
clear `_fast_path_queued`. Tasks are cancelled at `:5565`. Every callback checks `_tearing_down`.

### 5.9 Vacancy sweep timing (accepted, not gated)
- The sweep needs the zone past grace AND lighting-empty, and it is re-evaluated each pass.
- For 900 s-timeout rooms, the away write now precedes lighting-empty, and the sweep lands on the first pass after the
  room's own timeout. That is up to ~5 min sooner than today.
- It never precedes the room's own lighting vacancy.

### D2 acceptance
- **Premise:** `test_rearm_while_lighting_still_on_triggers_fast_entry`, `test_evidence_during_grace_prevents_away`,
  `test_rearm_limiter_exempt_keyed_on_last_sent`, `test_limiter_exemption_order`.
- **Nudge skip:** `test_fast_write_seeds_nudge_skip_on_next_tick`.
- **Queue and lock:** `test_queue_entry_cleared_on_every_exit_path`, `test_gates_rechecked_after_lock_wait`,
  `test_fast_path_running_only_true_while_holding_lock`.
- **Zone scope:** `test_fast_run_is_zone_scoped` (spies), `test_s1_writes_only_origin_zone`,
  `test_fast_run_sweeps_only_its_zone`, `test_fast_run_leaves_sibling_zones_untouched`,
  `test_absent_set_built_before_zone_loop`.
- **Equivalence:** `test_fast_decision_equals_periodic_decision`.
- **Exit timer:**
  - `test_exit_timer_fires_at_release_plus_grace` (normal grace 10, constrained 3, coast toggled)
  - `test_exit_timer_uses_grace_at_fire_time`, `test_exit_timer_reads_live_evidence`, `test_exit_timer_lazy_reschedule`
  - `test_exit_timer_one_shot_under_feed_disagreement`, `test_exit_timer_one_shot_consumed_on_gate_e_deferral`
  - `test_exit_timer_cancelled_on_zone_prune`
- **Listener:** `test_listener_ignores_refresh_without_evidence_advance`, `test_listener_skips_warm_zone`,
  `test_listener_skips_hallway`, `test_entry_limiter_denies_second_run_within_60s`, `test_two_zones_same_second`,
  `test_fp_last_ev_none_rule`, `test_subscribe_then_enumerate_no_miss_no_double`.
- **Lifecycle and teardown:** `test_periodic_waits_behind_fast_run`, `test_periodic_skips_behind_full_cycle`,
  `test_waiting_periodic_skips_if_full_cycle_ran`, `test_listener_lifecycle_idempotent`,
  `test_boot_settle_suppresses_fast_path`, `test_teardown_releases_before_first_await`,
  `test_tearing_down_guards_every_callback`.
- **Guards:** `test_write_ceiling_trips_and_clears_at_local_midnight`, `test_runaway_guard_trips_at_31_runs`,
  `test_quick_return_counter_and_nm_latch`, `test_kill_switch_off_restores_tick_only`,
  `test_preset_change_row_carries_trigger_edge_ts_zone_empty_since`.
- **Config boundaries:** grace 0, grace 60, per-room day hold 0, knob 47 = 0 and 15.

---

## 5b. D5: transit filter [REV 4, RULING R3]

### 5b.1 Rule (evidence states only)
```
cold = (not prev_output[R])
       and not (released_at[R] and now - released_at[R] <= HVAC_QUICK_RETURN_WINDOW_S)
       and not (zone_vacancy_away_at[Z] and now - zone_vacancy_away_at[Z] <= HVAC_QUICK_RETURN_WINDOW_S)
if not cold or W == 0:   output = ev_out                  # immediate (REV 3 rule)
else:                    output = ev_out and persisted(R, now)
persisted = (active and now - episode_start >= W) or (ev - episode_start >= W)
```
- Night states: `shadow_out or ev_out`, no dwell. Legacy states: shadow.
- Hallways are excluded upstream at `hvac_zones.py:725-736` and never reach this code.
- Pass-throughs this filters: Kitchen, Dining Room, Breakfast Nook, Butler Pantry (common_area); Kitchen Pantry and
  Laundry (utility); closets.

### 5b.2 Episode tracking (`ZoneManager._update_arming_episode`, from the listener and every producer pass)
- If the room is not cold: clear `episode_start`.
- Else, if there is no episode, or the latest `onset` is after the previous `ev + hold_ev`: `episode_start = onset`.
- Else keep it. Intermittent PIR pulses inside one hold window join one episode.
- If `now > ev + hold_ev` without an arm: clear the episode (the transit is over).

Examples (closet, hold 60, W = 60):
- A 10 s transit is never armed; the episode lapses at start + 70.
- A 90 s stay with pulses at 0, 50, 85 arms at the 85 s pulse.

Limit: a room whose evidence gaps exceed its hold cannot cold-arm until one episode spans 60 s. Only sparse-PIR closets
are plausible cases.

### 5b.3 Recent-return exemption (a correction to the brief)
The brief exempts "re-detected within its hold". The operator's premise case happens **after** the hold: a still person
is released, the zone goes away, then they move. The exemption therefore covers:
- a room released within 900 s, and
- any room in a zone that took a vacancy away within 900 s.

Cost: a transit within 15 min of a vacancy away re-arms immediately. That is at most one extra flap pair per episode,
counted by the quick-return trip-wire. **Checkpoint item.**

### 5b.4 Arm re-check timer
- Scheduled from `_on_room_refresh` for a cold, non-persisted room in a cold zone.
- Fires at `episode_start + W + HVAC_ARM_RECHECK_SLACK_S`.
- One timer per room, keyed by `episode_start`; stored in `_fast_path_arm_unsubs[room]`.
- Callback:
  - tearing down or gates closed -> return;
  - recompute from the live accessors;
  - persisted -> queue `fast_entry` (same dedup, limiter, ceiling);
  - lapsed -> drop;
  - otherwise -> nothing; the next evidence advance re-checks.
- Warm zones: no timer. The next pass arms the room, and exit runs recompute.
- Cancelled on episode lapse, room arm, zone prune, room unload and teardown (before the first await).

### 5b.5 Knob 47 moves; the lighting-session dwell retires
- Remove `hvac.py:2735-2748`. `_zone_entry_dwell` is now read only by D5, passed as `entry_dwell_s`.
- **Behaviour-neutral at the live value 0:** the old skip is guarded by `dwell_minutes > 0` (`:2740`).
- The old skip also covered `home_night`, `guest` and `waking`. D5 does not, consistent with "night and legacy
  unchanged at live values".
- Unchanged: key, entity, unique_id, in-place apply (`__init__.py:7379`), reset button, migration (`__init__.py:719`,
  DONE live).
- **Default** `DEFAULT_ZONE_ENTRY_DWELL_MINUTES` 0 -> **1**. This affects new installs, the reset button and the
  config-flow default. The live stored 0 stays until the operator sets 1 (D4).
- **Unit stays minutes** (1 min = the requested 60 s; step 1, max 15, BOX). No migration is needed.
- **0 means the transit filter is off:** any sign of someone arms a cold room at once.

### 5b.6 D5 acceptance (includes the Stage B card's own criteria)
**Card criteria**
- **C1. Brief transits stop flipping zones.**
  - Flap = an S1 home/sleep write followed by a `vacant_past_grace` away within 20 min on the same zone (definition from
    card `HVAC-W2-OCCUPANCY-TRUTH` `next`).
  - Live, knob 47 = 1: the 7-day evidence-state flap count is below the D0a baseline.
  - Every remaining flap's arming room shows `armed_at - episode_start >= 60 s`, or an `exempt_reason`.
  - Failure looks like: flaps whose arming evidence lasted under 60 s without an exemption.
- **C2. CRIT-1 untouched (arming edge only).** `test_d5_does_not_change_release`: release instants are identical at
  W = 0 and W = 60 for an armed room.
- **C3. Hallways excluded by construction.** `test_hallway_never_arms_with_dwell`.
- **C4.** The two onset-anchored dwell plans get SUPERSEDED banners; the card closes as folded (section 12).

**Tests (new)**
- `test_transit_under_60s_no_write` (cold `away` zone, 45 s continuous Kitchen radar -> no `preset_change`, room never
  `hvac_occupied`)
- `test_stay_60s_writes_within_sla` (continuous radar from `t0` -> home write with `row_ts - t0` in `[60, 105] s`,
  `trigger=fast_entry`)
- `test_intermittent_pir_stay_arms_on_pulse_after_window`, `test_gap_longer_than_hold_starts_new_episode`,
  `test_episode_lapses_after_hold_without_arm`
- `test_recent_release_rearms_immediately`, `test_zone_recent_vacancy_rearms_immediately`,
  `test_rearm_after_901s_is_cold`
- `test_warm_room_no_dwell`, `test_dwell_zero_is_rev3_behaviour`, `test_dwell_only_in_evidence_states`
- `test_arm_recheck_scheduled_at_onset_plus_w`, `test_arm_recheck_cancelled_on_lapse_arm_prune_unload_teardown`
- `test_exit_run_arms_persisted_room_before_away`, `test_lighting_session_dwell_removed`
- `test_d5_does_not_change_release`, `test_hallway_never_arms_with_dwell`, `test_evidence_onset_accessor`

**Live**
- New per-room attrs `episode_start`, `armed_at`, `dwell_s`, `exempt_reason`.
- For 10 evidence-state cold arms: `armed_at - episode_start` is in `[60, 105] s` when the evidence was continuous.
- The resulting `preset_change` rows carry `trigger=fast_entry`.

---

## 6. Latency budget (before -> after)
Assumptions: grace 300 s, tick 300.3-301.1 s, poll 30-35 s, event refresh within 2 s. Today the grace is absorbed by
tick quantization. Kitchen at its old 600 s timeout gives ~18 min, matching the operator's "15-20 min".

| Path | Today (live) | After |
|---|---|---|
| Entry into a cold zone, knob 47 = 1 | avg ~2.5-3 min, worst ~5.5 min | **60 s + a few seconds** (<= 105 s) |
| Entry into a cold zone, knob 47 = 0 | same | usually < 5 s; <= 45 s |
| Pass-through under 60 s of a cold room | home at the next tick, then away (a flap) | **no write** |
| Re-arm after a wrong away (person moves, within 15 min) | avg ~2.5, worst ~5 min | usually < 5 s; <= 45 s (exempt from D5) |
| Still person who does not move | held by timeout + tail | held by the hold ONLY |
| Re-detected during grace | no away | no away |
| Exit, `home_day`/`home_evening`, 300 s-timeout room | avg ~12.8 min (~10-15.6) | hold + 5 min (list below) |
| Exit, same states, 900 s-timeout room | avg ~22.8 min | bathroom 8 / common 8 min |
| Exit, Kitchen | ~17.8 (600 s) / ~12.8 (300 s stopgap) | 8 min |
| Exit, `home_night`, `guest`, `arriving` | today's rule | unchanged |
| Exit, `sleep`/`waking` | timeout + night hold + tick | same or later; lands at release + 5 min |

Exits in `home_day`/`home_evening` by type: closet/infra 6 min; generic/utility/media/garage 7; bathroom 8; common 8
(3 + 5); bedroom 9. Each adds ~2-5 s.

---

## 7. Residual risk (evidence states only)

### 7.1 Audit counts at the ruled values (G = 300, 6.74 days) — context, operator-accepted
| Class | At the ruled table | Today |
|---|---|---|
| MID zone retreat (proxy for a still person) | **~13** (common_area at T = 180, all Kitchen; generic/utility 120, bath 180, closet 60: 0; bedroom 240: between the audit's 1 at 180 and 0 at 300) | 0 |
| MID with Jaya's day override 60 left | +2 (D4 fixes) | 0 |
| LATE zone retreat (ambiguous) | **~36** (audit total at T = 180 was 37; Kitchen 29, Dining 2, Master Bath 1, Jaya Bath 1, bedrooms <= 1) | 0 |
| Total | ~49 / 6.74 d ≈ 7/day, mostly zone_3 | 0 |

- These are context, not a gate (R1). They come from a model of today's design without re-arm and with stacked timers.
  Each retreat costs two writes and minutes of away once the person moves, and each one is counted live by the
  trip-wire.
- A person who does not move stays at away until they do; the hold is their only protection.
- **Kitchen exception dropped: operator-accepted in spirit (R1); explicit confirmation at the checkpoint.**
  - The audit's §7 recommended "timeout + 60" for the Kitchen; under R1/R2 it gets `common_area` 180.
  - About 29 of the ~36 LATE and all ~13 MID retreats are the Kitchen.
  - In 30 of 30 Kitchen LATE events another room (mostly the Patio) had evidence.
  - The Kitchen timeout is already 300 s.
  - A per-room override (config, no code) remains available.
- **D5 residuals [REV 4]:**
  - Real arrivals into a cold zone wait 60 s longer.
  - A person who enters a cold room and stays completely still for the first 60 s is treated as a transit until they
    move.
  - Sparse-PIR closets may not cold-arm.
- Not measured: production fusion filters and phantom radars. D0c and the trip-wire cover them.

### 7.2 Context arithmetic (no recommendation) [RULING R2]
| Type | Sample max day MID gap | T + G at the ruled values |
|---|---|---|
| common_area | 603 s | **180 + 300 = 480 s** |
| bedroom | 495 s | 240 + 300 = 540 s |
| generic | 396 s | 120 + 300 = 420 s |
| utility | 386 s | 120 + 300 = 420 s |
| bathroom | 836 s | 180 + 300 = 480 s (audit measured 0 at T = 180: the zone was co-occupied) |
| closet | 204 s | 60 + 300 = 360 s |

- Recorded as context; the operator accepts it (R1, R2).
- Knob 49 enters the same sum under coast/shed.
- The quick-return trip-wire is the live measure.

---

## 8. D0: probes (read-only)
- **D0a (baselines)**, `hvac_fast_path_d0_probe.py --latency`, over >= 3 occupied days (earliest 2026-09-30):
  - per zone, entry latency (zone-cold room `*_occupied` rising edge -> `preset_change` home/sleep) and exit latency
    (last raw evidence -> `vacant_past_grace` away);
  - **flap rate** [REV 4]: S1 home/sleep -> `vacant_past_grace` away within 20 min, per zone per day. Where
    recoverable, each flap's arming room and its raw evidence duration.
- **D0b (write-rate baseline):** REV 4 F9 query on `climate_write`, >= 3 days (earliest 2026-09-30).
- **D0c (residual replay):** `hvac_raw_evidence_gap_probe.py --graces 300,600` with current config; T grid gains 240.
  - [REV 4] Adds a W = 60 s arming replay: predicted flap reduction, and stays under 60 s that would be filtered.
  - **Gate A:** any zone's ZR > 2x the audit figure at the ruled T -> stop, back to the operator. Blocks deploy.
- **D0c-home_night:** `--states home_night`, >= 7 nights.
  - **Gate B:** `home_night` MID ZR at the ruled table = 0 -> propose adding `home_night` to
    `HVAC_EVIDENCE_RULE_STATES` (reviewed follow-up); otherwise it stays legacy. Does not block deploy.

---

## 9. Live acceptance (discriminating)
| # | Check | Pass | Failure looks like |
|---|---|---|---|
| L1 | Entry latency | knob 47 = 1: >= 90 % of cold-zone `fast_entry` rows land in `[60, 105] s` after `episode_start`; knob 47 = 0: <= 45 s after `edge_ts` | uniform 0-300 s (tick) |
| L2 | Exit exactness | every `fast_exit` away: `row_ts - zone_empty_since` in `[g, g + 50] s` for the live grace `g` | `[g, g + 300]` spread; `< g` |
| L3 | INV-2 live | each evidence-state away: every zone room's `release_at <= row_ts - g`, `rule == evidence` | a later `release_at` |
| L4 | Re-arm | each quick return: `fast_entry` home/sleep within 45 s of `edge_ts`, **zone_1 excluded while §9.7 is open** | home only at the next tick |
| L5 | Zone scope | during fast runs no other-zone `climate_write`, no enforcer/nudge/cover/fan actions; sweep only for the run's zone | any off-zone write |
| L6 | Clock decoupled | D1 Live | off never precedes lighting off |
| L7 | Night/legacy unchanged | in `sleep` and `home_night`, `rule` is `night`/`legacy`; releases never precede the room's `*_occupied` off + the shadow tail; no legacy back-fill | earlier release / back-filled lot |
| L8 | Write rate | per-zone `climate_write`/day <= D0b + spread + 10; no ceiling trips | trips or a jump |
| L9 | Quick returns | 7-day sum within 2x D0c's prediction at the ruled values (~7/day house-wide) | much higher |
| L10 | Lifecycle | after a room reload and an HA restart: one listener per room; timers re-armed | duplicates / missing |
| L11 | Nudge skip | no `nudge_started` within 120 s after a fast write on the same zone | a nudge seconds after |
| L12 | D5 card criteria C1, C3 [REV 4] | 5b.6 | 5b.6 |
| L13 | No short arms [REV 4] | knob 47 = 1: zero `preset_change` rows attributable to an arming room with `armed_at - episode_start < 60 s` and no `exempt_reason` | any |

Results go into the README as a `Validated <date>` table.

---

## 10. D3: vacancy grace re-check (measure; knob only)
- Knob 48 (live 5). No code.
- Context: section 7.2. At the ruled holds any grace cut raises the retreat counts.
- After D1 + D2 have been live >= 7 days, adapt `hvac_vacancy_grace_probe.py`: per zone, time from `zone_empty_since` to
  the next re-arm. For G' in {2, 3, 4} min, report extra quick-return pairs against conditioning minutes saved.
- The operator decides.

## 10b. D4: config step
- Clear Jaya Bedroom's day override (live attr `hvac_vacancy_hold_s` = 240 in `home_day`, 5400 in `sleep`).
- **Set knob 47 (`number.ura_hvac_coordinator_zone_entry_dwell`) to 1** once D5 is live [REV 4]. Checkpoint item.
- Kitchen override only if the operator reverses the Kitchen ruling.

---

## 11. Tier: 3
**Why:**
- It changes the still-person safeguard (release) and the arming edge.
- It adds triggers and timers into the shared decision lock and the S1 site.
- This surface has two failed plan reviews behind it.

**Protocol:**
- focused D5 plan re-review;
- build;
- four parallel reviews: A local correctness; B integration and state machine; C per-site mutation; D adversarial
  completeness, including pre-existing paths;
- orchestrator re-grep and re-drill;
- operator checkpoint before deploy (four items in the header, plus D0c Gate A).

### 11b. Builder traps
1. Triggering on the lighting binary sensor edge instead of the evidence stamp.
2. Calling `_run_decision_cycle` for a fast run, or not skipping the enforcer/DPM under `zone_filter`.
3. Zone filter after `clear()`.
4. Absent set left inside the filtered zone loop.
5. Missing the `last_occupied_time` back-fill (early exit) or applying it in legacy states.
6. Stamping from `_last_motion_time`, or only on rising edges.
7. Re-deriving camera/BLE instead of reading this tick's source.
8. Rescheduling a fired exit key (§9.7 loop).
9. Keying the limiter exemption on `preset_mode`.
10. Letting a waiting periodic run a second full cycle.
11. Pointing the shadow at `ROOM_TYPE_HVAC_HOLD` or removing the clamp.
12. Releasing listeners or timers after the first `await`.
13. Putting `trigger` in a counter but not on the `preset_change` row.
14. Evidence branch writing shadow dicts.
15. `guest`/`arriving`/`home_night` in the evidence states.
16. `finally` placement: queue discard outer, `_fast_path_running` inner.
17. Resetting `_zones_written_this_cycle` to an empty set.
18. `if ev:` truthiness instead of `isinstance`.
19. Relying on reschedule hooks instead of recomputing at fire.
20. Stamping on suppressed sources, or falling-edge-stamping after them.
21. Refresh-failure hold outside evidence states, or unbounded.
22. **[REV 4]** Dwell applied to a room released within 900 s.
23. **[REV 4]** `onset` taken from the lighting session or `_occupancy_first_detected`.
24. **[REV 4]** Episodes joined across gaps longer than the hold, or never lapsing.
25. **[REV 4]** The lighting-session skip left alongside D5 (double dwell).
26. **[REV 4]** Dwell in night or legacy states.
27. **[REV 4]** Arm re-check scheduled for warm zones, or not cancelled.
28. **[REV 4]** Knob 47's unit or unique_id changed.

### 11c. Test-file impact
| Test | Result | Disposition |
|---|---|---|
| `test_zzz_hvac_conditioning_demand.py:909` (`ROOM_TYPE_HVAC_HOLD["bedroom"] == 60`) | **RED** | update to 240; add legacy-table 60 |
| `test_zzz_hvac_conditioning_demand.py:774-775` (dwell default 0) [REV 4] | **RED** | update to 1 |
| `test_hvac_night_hold_follows_sleep.py:69-79` | **RED** | compare with `ROOM_TYPE_HVAC_TAIL_LEGACY` |
| `test_hvac_vacancy_hold_ui_defaults.py:159-172` | **RED** | new helper wording |
| `test_zzz:246-269`, `:325-331`, `:505-523`, `:636-716` | GREEN | shadow selector; monotonic; migration untouched |
| `test_hvac_night_hold_follows_sleep.py` others | GREEN | `:216-255` guards the `isinstance` fallback |
| `test_v5_103_8_hvac_knobs_and_obs.py:127-170`, `:359-430` | GREEN | shadow + override |
| `test_hvac_presence_timer_knobs.py` [REV 4] | GREEN (verify `:686`, `:709-710`, `:860-865` at build) | reads the constant |
| `test_part2_ec_hc_writeback.py`, `test_cm_reload_suppression.py` [REV 4] | GREEN | key unchanged |
| `test_dpm_cleanup_and_labels.py:179` [REV 4] | GREEN if both string files change together | parity |

### 11d. Per-site mutation drill table (table of record)
For every drill: neuter the returned value or branch (not just the call), with bytecode disabled; restore the file and
check `git status` is clean afterwards.

| # | Site | RED test |
|---|---|---|
| 1 | Evidence-state output returns `shadow_out` | `test_evidence_state_ignores_lighting_timeout` |
| 2 | Evidence branch writes `_hvac_armed = False` | `test_home_evening_to_sleep_mid_timeout_stays_held` |
| 3 | Night output drops the shadow | same + `test_night_release_never_before_shadow` |
| 4 | `home_night` in evidence states | `test_home_night_is_legacy_until_gate` |
| 5 | `active` term removed | `test_hold_zero_holds_while_active` |
| 6 | Refresh-failure hold removed / unbounded / applied in night | `test_refresh_failure_hold_evidence_states_only_and_bounded` |
| 7 | Suppressed-source check removed | `test_no_stamp_on_fan_demoted_failsafe_recheck_sources` |
| 8 | Camera/BLE source term removed | `test_camera_ble_stamp_only_from_override_verdict` |
| 9 | Override-vacant exclusion removed | `test_override_vacant_blocks_stamp` |
| 10 | Falling-edge stamp removed | `test_falling_edge_refresh_stamps` |
| 11 | BLE cap neutered | `test_ble_cap_stops_stamp_after_cap` |
| 12 | `apply_fan_recheck_release` leaves active True | `test_fan_recheck_release_clears_active` |
| 13 | Back-fill removed | `test_last_occupied_time_backfilled_to_exact_release` + `test_exit_timer_fires_at_release_plus_grace` |
| 14 | Back-fill in legacy states | `test_no_backfill_in_legacy_states` |
| 15 | Zone filter after `clear()` | `test_fast_run_leaves_sibling_zones_untouched` |
| 16 | Loop-top `continue` removed | `test_s1_writes_only_origin_zone` |
| 17 | Absent set inside the zone loop | `test_absent_set_built_before_zone_loop` |
| 18 | Enforcer not skipped | `test_fast_run_is_zone_scoped` (enforcer spy) |
| 19 | DPM not skipped | `test_fast_run_is_zone_scoped` (DPM spy) |
| 20 | Listener on the lighting edge | `test_rearm_while_lighting_still_on_triggers_fast_entry` |
| 21 | Evidence-advance check removed | `test_listener_ignores_refresh_without_evidence_advance` |
| 22 | Zone-cold gate removed | `test_listener_skips_warm_zone` |
| 23 | Hallway skip removed | `test_listener_skips_hallway` |
| 24 | Base 60 s limiter removed | `test_entry_limiter_denies_second_run_within_60s` |
| 25 | Exemption keyed on `preset_mode` | `test_rearm_limiter_exempt_keyed_on_last_sent` |
| 26 | Registry-miss fallback removed | `test_limiter_exemption_order` |
| 27 | Stamp check order swapped / removed | `test_limiter_exemption_order` |
| 28 | Nudge-skip seed reverted to `set()` | `test_fast_write_seeds_nudge_skip_on_next_tick` |
| 29 | Queue discard inside the lock | `test_queue_entry_cleared_on_every_exit_path` |
| 30 | `_fast_path_running` cleared in the outer `finally` | `test_fast_path_running_only_true_while_holding_lock` |
| 31 | Post-lock gate re-check removed | `test_gates_rechecked_after_lock_wait` |
| 32 | `_tearing_down` guard removed (per site) | `test_tearing_down_guards_every_callback` |
| 33 | Teardown after the first await | `test_teardown_releases_before_first_await` |
| 34 | One-shot key not recorded | `test_exit_timer_one_shot_under_feed_disagreement` |
| 35 | Exit timer reads pass-cached evidence | `test_exit_timer_reads_live_evidence` |
| 36 | Callback uses the scheduled grace | `test_exit_timer_uses_grace_at_fire_time` |
| 37 | Constrained-grace choice removed | 10/3 variant of `test_exit_timer_fires_at_release_plus_grace` |
| 38 | Timer not cancelled on prune | `test_exit_timer_cancelled_on_zone_prune` |
| 39 | Waiting periodic does not skip after a full cycle | `test_waiting_periodic_skips_if_full_cycle_ran` |
| 40 | Write ceiling never trips | `test_write_ceiling_trips_and_clears_at_local_midnight` |
| 41 | Runaway guard never trips | `test_runaway_guard_trips_at_31_runs` |
| 42 | Quick-return trip-wire never counts | `test_quick_return_counter_and_nm_latch` |
| 43 | `isinstance` replaced by truthiness | `test_accessor_fallback_uses_isinstance_datetime` + night-hold `:216-255` |
| 44 | Shadow selector reads `ROOM_TYPE_HVAC_HOLD` | `test_legacy_tail_is_frozen_v5_103_19` + `test_zzz:246-269` |
| 45 | [REV 4] Dwell check removed | `test_transit_under_60s_no_write` |
| 46 | [REV 4] Arm re-check not scheduled | `test_stay_60s_writes_within_sla` |
| 47 | [REV 4] Recent-release exemption removed | `test_recent_release_rearms_immediately` |
| 48 | [REV 4] Zone-vacancy exemption removed | `test_zone_recent_vacancy_rearms_immediately` |
| 49 | [REV 4] Exemption window unbounded | `test_rearm_after_901s_is_cold` |
| 50 | [REV 4] Episode never lapses | `test_episode_lapses_after_hold_without_arm` |
| 51 | [REV 4] Episode always rejoins | `test_gap_longer_than_hold_starts_new_episode` |
| 52 | [REV 4] Dwell in night/legacy | `test_dwell_only_in_evidence_states` |
| 53 | [REV 4] Lighting-session skip left in place | `test_lighting_session_dwell_removed` |
| 54 | [REV 4] Exit run skips D5 | `test_exit_run_arms_persisted_room_before_away` |
| 55 | [REV 4] Arm re-check not cancelled | `test_arm_recheck_cancelled_on_lapse_arm_prune_unload_teardown` |
| 56 | [REV 4] Onset re-stamped on every active tick | `test_evidence_onset_accessor` |
| 57 | [REV 4] `W == 0` branch removed | `test_dwell_zero_is_rev3_behaviour` |

---

## 12. Sequencing and supersession
- **B is shipped (v5.103.19);** no wait gate.
- **REV 4 fast-path plan (`PLANNING_hvac_w2_occupancy_fast_path.md`):** superseded; add a banner.
- **`HVAC-ENTRY-DWELL-ROOM-CLOCK-1`:** fully folded here (release half in D1, arming half in D5). Close it as folded
  when D5 ships. SUPERSEDED banners go on `PLANNING_hvac_entry_dwell_room_clock.md` and
  `PLANNING_hvac_entry_dwell_hvac_clock.md` [REV 4].
- **`HVAC-FAST-PATH-FAN-WARM-EDGES-1`:** keep it out of this cycle; recommend a fan-only Tier-2 cycle next. Its trigger
  is arguably met by "we wanted faster responses", but fans read lighting, have their own gates, and would reintroduce
  REV 4's "fan writes off-schedule" HIGH. Operator to confirm.
- **Others:**
  - `HVAC-HOLD-SIZING-ALL-ROOMS-1` -> D3/L9 input.
  - `HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1`: unchanged exposure.
  - `HVAC-WRITE-CONFIRMATION-ORACLE-1`: one-shot timer; L4 excludes zone_1.
- **Supersession triage (post-ship audit)** [REV 4]:
  - `ZoneState.current_session_start` (`hvac_zones.py:135`, written `:786-789`) has no reader after D5. **DELETE**
    after live validation: it is the lighting clock the operator rejected. Card it under W4.
  - `_migrate_hvac_zone_entry_dwell_to_zero` (`__init__.py:719`): **KEEP + DOCUMENT** (already applied).
- **D0b:** >= 3 days (earliest 2026-09-30).

## 13. REV 4 fast-path findings (F1-F15) and re-review HIGHs: disposition
| Item | Disposition |
|---|---|
| Re-review HIGH: whole-house off-schedule cycle | Fast runs never call `_run_decision_cycle` |
| Re-review HIGH: wrong-zone reruns | Per-zone queue + wait-for-lock |
| Re-review HIGH: heat_cool/egress/fan/cover writes | Not called by a fast run |
| Re-review HIGH: sibling-zone wake-ups | Filter before `clear()`; absent set before the zone loop; S1 origin-only |
| F1 dwell follow-up | Replaced by the D5 arm re-check at `episode_start + W` [REV 4] |
| F2 origin_zones | Replaced by the zone-scoped run |
| F3 count-coupled skips | Moot; waiting periodic skip rule |
| F4 zone-cold gate | Kept |
| F5 lock / rerun | Wait-for-lock rules; nudge-skip seed |
| F6 teardown | Kept |
| F7, F8 | Moot / replaced by `trigger` and `edge_ts` on the row |
| F9 write-rate baseline | D0b |
| F10 ceiling | Re-based on writes; runaway guard |
| F11 lines | Refreshed |
| F12 zones live, F13 one lifecycle subscription | Kept |
| F14 trigger on the row + SLA consumer | Kept; the gauge is on `sensor.ura_hvac_coordinator_mode` (`_status` does not exist) |
| F15 anomaly | Not called |
| Global limiter G | Dropped |

---

## 14. Knobs and labels

### 14.1 Knob ladder
| Number | Value | Rung | Why |
|---|---|---|---|
| `ROOM_TYPE_HVAC_HOLD` | 4.6; common 180 | 1 | Rulings R1/R2. Changing a value re-opens the still-person trade and needs review; the live check is the quick-return trip-wire |
| `ROOM_TYPE_HVAC_TAIL_LEGACY` | frozen | 1 | Shadow; must not be tuned |
| `HVAC_EVIDENCE_RULE_STATES` | (`home_day`, `home_evening`) | 1 | Adding a state needs a probe and review |
| `HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S` | 600 | 1 | Longest hold 240 + ~10 polls; 0 disables |
| `HVAC_FAST_PATH_MIN_INTERVAL_S` / `_SLA_S` / `_EXIT_SLACK_S` | 60 / 45 / 2 | 1 | Per-zone entry floor (exempt for re-arm) / observability target / clears the strict `>` grace test |
| `HVAC_FAST_PATH_MAX_WRITES_PER_ZONE_PER_HOUR` / `_MAX_RUNS_PER_ZONE_PER_HOUR` | 6 / 30 | 1 | Carrier bound / runaway guard |
| `HVAC_QUICK_RETURN_WINDOW_S` | 900 | 1 | Trip-wire window; also bounds the D5 recent-return exemption |
| `HVAC_QUICK_RETURN_NM_PER_DAY` | 12 | 1 | ~2x the expected zone_3 rate at the ruled values; 8 would alert almost daily. **Checkpoint item** |
| Knob 47 `number.ura_hvac_coordinator_zone_entry_dwell` [REV 4] | default 1 min (was 0); live 0 until the operator sets 1 | 3 (existing) | Ruling R3; operator tunes by flap rate vs entry wait. 0 = transit filter off |
| `HVAC_ARM_RECHECK_SLACK_S` [REV 4] | 1 | 1 | Lands the re-check just past `episode_start + W` |
| Fast room response switch | ON | 3 | Rollback; OFF = tick timing |
| Knob 48 / 49 grace | 5 / 5 | 3 (existing) | D3 |

### 14.2 Labels
Rules: short config-flow phrase; plain helper; entity names 3 words max after the numbering prefix. Banned words: tail,
HVAC-occupied, clamp, gate, evidence, tick, fast path, debounce, CRIT, fused, rung, shadow, legacy, dwell, transit,
arm, episode.

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
- `hvac_zone_entry_dwell` label [REV 4]: `Entry wait (minutes)`
- `hvac_zone_entry_dwell` helper [REV 4]: `How long someone must be in a room during the day or evening before heating and cooling treat it as newly occupied. People passing through faster than this do not switch the zone from Away to Home. Someone coming back to a room or zone they left in the last 15 minutes counts at once. Enter 0 to count any sign of someone at once. Recommended: 1.`

**Entities:**
- Knob 47 name unchanged: `47 · Entry Wait (min)`.
- New switch: `31 · Fast Room Response` (`switch.ura_hvac_coordinator_31_fast_room_response`,
  unique_id `{DOMAIN}_hvac_fast_room_response`).

**Notifications:**
- Ceiling: `Fast room response paused for {zone}` / `{zone} changed its heating and cooling setting {n} times in the last hour. Fast response is off for this zone until midnight. The regular 5-minute check still runs.`
- Quick returns: `{zone} keeps switching to Away too soon` / `{zone} switched to Away and someone was back within 15 minutes {n} times today. The empty-room hold for a room in this zone may be too short.`
- Runaway: `Fast room response paused for {zone}` / `{zone} ran more checks than expected in the last hour. Fast response is off for this zone until midnight. The regular 5-minute check still runs.`

**Acceptance:**
- `strings.json` == `en.json`;
- banned-word check clean;
- JSON parses;
- hassfest passes;
- `test_hvac_vacancy_hold_ui_defaults.py` updated.

---

## 15. Files
| File | Change |
|---|---|
| `custom_components/universal_room_automation/const.py` | `ROOM_TYPE_HVAC_HOLD` values; `ROOM_TYPE_HVAC_TAIL_LEGACY` |
| `.../coordinator.py` | Evidence stamp, onset, three accessors |
| `.../domain_coordinators/hvac_zones.py` | Shadow + rule output; D5 (episode, cold, persisted); selectors; `zone_ids` filter; absent set in the entry loop; back-fill; release helpers; diag/zone attrs |
| `.../domain_coordinators/hvac.py` | Listeners + lifecycle; `_on_room_refresh`; `_async_zone_fast_run`; exit and arm timers; lock rules; nudge-skip seed; `_apply_house_state_presets(zone_filter, trigger, edge_ts)`; removal of `:2735-2748`; `_zone_vacancy_away_at`; ceiling/guard/trip-wire; teardown; `get_mode_attrs` |
| `.../domain_coordinators/hvac_const.py` | Section 14.1 constants; `DEFAULT_ZONE_ENTRY_DWELL_MINUTES = 1` |
| `.../binary_sensor.py` | Attrs per 3.2; `_display_hold` |
| `.../switch.py` | `31 · Fast Room Response` |
| `.../number.py` | Grace setters call `reschedule_exit_timers()` |
| `.../strings.json`, `.../translations/en.json` | Section 14.2 |
| `quality/tests/` | New `test_hvac_evidence_clock.py`, `test_hvac_fast_occupancy_response.py`, `test_hvac_transit_filter.py`; updates per 11c |
| `scripts/probes/` | `hvac_fast_path_d0_probe.py --latency` (+ flap rate); `hvac_raw_evidence_gap_probe.py --states`, T 240, W replay; `hvac_vacancy_grace_probe.py` adaptation |
| Docs | State of play (§1, §2, §3.1-§3.2, §8, §9.5, §9c, §9d, header); SUPERSEDED banners on the REV 4 fast-path plan and the two dwell plans; README (PATCH bump; the orchestrator may argue MINOR) |

`config_flow.py` is not changed (validation kept; the knob 47 field stays).

## 16. Non-goals
- No change to night hold values or anchor.
- No change to `home_night`, `guest`, `arriving` or `away` behaviour: no evidence rule, back-fill, exit timer or dwell
  there.
- No change to the clamp or the flow validation.
- No fan, cover, predictor, egress, arrester, DPM or D9 change; fans stay tick-driven.
- No change to `HVAC_DECISION_TICK`, the grace values, or knob 47's unit, range or entity id.
- No change to hallway exclusion. Override Vacant rides the hold from the last evidence.
- No new table, DB writer, sensor or dispatcher signal.
- No fix for §9.4 or §9.7 (only: do not speed up §9.7).
- No removal of `current_session_start` in this cycle.

## 17. Parked
- Night-anchor unification (night hold from last evidence). Revival trigger: a raw-evidence night probe shows every
  bedroom's max still-sleeper gap under its night hold with >= 15 min margin.
- `home_night` on the evidence rule (Gate B).
- A dwell for night or legacy states (needs its own measurement).

## 18. Change logs

### REV 4
| Item | Change | Where |
|---|---|---|
| D5 transit filter | Cold room arms only after 60 s persisted evidence, evidence states only; arm re-check at `episode_start + W`; non-cold rooms immediate | 0.5, 2, 3, 4.1, 4.2, 5b |
| Premise exemption | Room released within 900 s, or zone vacancy away within 900 s, re-arms immediately (corrects "within its hold") | 5b.3 |
| Knob 47 | Semantics moved to D5; default 0 -> 1; unit stays minutes; 0 = filter off; label + helper | 5b.5, 14 |
| Lighting-session dwell retired | `hvac.py:2735-2748` removed; `current_session_start` DELETE candidate | 5b.5, 12 |
| Hallway confirmation | Exclusion at `hvac_zones.py:725-736` | 0.3, 5b.1 |
| Latency | Cold-zone entry 60 s + seconds at knob 1; pass-through under 60 s = no write | 6 |
| Stage B card criteria | C1-C4; flap baseline in D0a; W replay in D0c | 5b.6, 8, 9 |
| Tests / drills | 17 new tests; `test_zzz:774` RED; drill rows 45-57 | 5b.6, 11c, 11d |
| Ledger | R3 verbatim | 0.6 |
| Self-contained file | All REV 3 detail inline (not "as REV 3") | whole doc |

### REV 3
| Item | Change |
|---|---|
| Rulings R1/R2 | Holds = audit table with common 180; ledger; arithmetic as context; trip-wire is the live measure |
| Quick-return threshold | 8 -> 12 per zone per day (checkpoint) |
| Kitchen | Dropped under R1; operator-accepted in spirit; confirm at checkpoint |
| N1 | Three selectors; legacy table every type; test-impact incl. `test_zzz:909` |
| N2 | `_fast_path_running` inside the lock; queue discard outer |
| N3 | Refresh-failure hold only on the evidence term in evidence states, bounded at 600 s |
| N4 | Exit callback recomputes with the live grace; hooks latency-only; bypass writers cited |
| N5 | Camera/BLE from this tick's override verdict; extractions dropped |
| N6 | Drill table extended to 44 rows; table of record |
| LOW-1 / LOW-2 / LOW-3 | Exemption order; no legacy back-fill; Kitchen pending confirmation |

### REV 2
| # | Change |
|---|---|
| pre | B shipped; lines refreshed; state of play re-read |
| 1 | Shadow machine owns today's dicts; night = shadow OR evidence; frozen legacy tail; clamp/validation kept |
| 2 | Evidence rule only in `home_day`/`home_evening`; Gate B; still person = hold only |
| 3 | `active OR now < ev + hold`; refresh-failure hold; truthful "0" helpers |
| 4 | `_zone_last_s1_write`; nudge-skip seed within 120 s |
| 5 | Vacancy sweep in the map; INV-4 corrected; timing accepted |
| 6 | Outer `finally`; post-lock gate re-check |
| 7 | Periodic-equivalence invariants; exception table; `last_sent` exemption; L4 excludes zone_1 |
| 8 | Test-impact table; `isinstance`; drill table; equivalence seeds must write |
| 9 | Stamp gating on suppressed sources |
| 10 | Exit timer: live evidence; reschedule; 10/3 grace test |
| 11 | +335 s live criterion; absent set; prune; pre-arrival expiry; knob 49; zone-intelligence sensor; LOWs; fan card |

## 19. Departures and notes
1. `guest` and `arriving` stay legacy: the audit excluded them (§1, §8.6).
2. Only four existing tests go RED: `test_zzz:909`, `test_zzz:774`, `night_hold:69-79`, `ui_defaults:159-172`.
3. The clamp and flow validation are kept.
4. Vacancy sweep timing is accepted, not gated.
5. N5 cost: camera/BLE count only after a room's own timeout. That can cause two-write flaps in eight long-timeout
   rooms. D5's recent-return exemption makes the re-arm immediate.
6. The quick-return threshold is 12, not 8 (checkpoint).
7. ~13 MID retreats per 6.74 days at common 180: operator-accepted context (R1/R2).
8. **[REV 4]** The recent-return exemption corrects the brief's "within its hold". Without it, D5 would add 60 s to
   the exact recovery the operator's premise relies on. Checkpoint.
9. **[REV 4]** Knob 47 keeps minutes. 1 minute = the requested 60 s, and changing the unit needs a stored-option
   migration for no gain.
10. **[REV 4]** The retired lighting-session dwell also covered `home_night`, `guest` and `waking`. Behaviour-neutral
    at live 0. A dwell there later needs its own measurement.
