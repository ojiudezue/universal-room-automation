# PLANNING: HVAC fast occupancy response (own release clock, transit filter, event-driven entry and exit) — REV 5

**Cards:**
- `HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1` (revived)
- the parked W2 fast path (`HVAC-W2-OCCUPANCY-TRUTH`, plan `PLANNING_hvac_w2_occupancy_fast_path.md` REV 4)
- `HVAC-ENTRY-DWELL-ROOM-CLOCK-1` (Stage B, folded in as D5)

Workstream `HVAC-W2-OCCUPANCY-TRUTH`.

**Status:** REV 5.
- REV 1: two Tier-3 plan reviews, both FIX-PLAN.
- REV 2: folded them; its re-review found the design sound.
- REV 3: text edits + operator hold rulings R1/R2.
- REV 4: added D5 (ruling R3).
- REV 5: folds the focused D5 review (FIX-PLAN).

Tags: `[REV 2 #n]`, `[REV 3 <id>]`, `[RULING Rn]`, `[REV 4]`, `[REV 5 <id>]`. Change logs: section 18. Departures:
section 19. The file is self-contained.

**Checkpoint items needing explicit operator confirmation before deploy:**
1. Kitchen exception drop (7.1).
2. Quick-return alarm threshold 12 (14.1).
3. **D5 room-only 15-minute return exemption (5b.3)** [REV 5 wording].
4. Setting knob 47 to 1 minute (10b).

**Base:** current `develop` after v5.103.19 (night-tail B shipped). `hvac_zones.py` lines refreshed; `hvac.py`
unchanged since REV 1.

**Operator decision (2026-09-27 ~22:00, verbatim):** "We wanted faster responses. This is nuts." / "fast path catches
it. The room type hold blunts it. Do it". Rulings R1-R3: section 0.6.

**Design premise, with its limits:**
1. A per-room-type hold blunts radar misses of still people. **It is the ONLY protection for someone who stays
   still.** A still person produces no new evidence, so the fast path cannot catch them. It reacts only once they move
   again.
2. An event-driven fast path re-arms a re-detected room in seconds instead of at the next 5-minute tick.
3. A brief pass-through (under 60 s) does not switch a zone that URA set to Away back to Home. **D5 filters only that
   away -> home edge** [REV 5 HIGH-1].

| Deliverable | What | Code? |
|---|---|---|
| D0 | Baselines (latency, write rate, flap rate), residual + W replay, `home_night` gate probe | probe only |
| D1 | New release clock in `home_day`/`home_evening`; today's machine kept as a shadow; other states unchanged | yes |
| D2 | Event-driven zone decision on entry AND exit | yes |
| D3 | Vacancy grace re-check | no (knob) |
| D4 | Operator config: clear Jaya Bedroom's day override; set knob 47 to 1 | config |
| D5 | Transit filter on the away -> home edge only; knob 47 moves from the lighting-session dwell to this; the lighting-session dwell is retired | yes |

---

## 0. Institutional context verified

### 0.1 Mandatory read
**`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`:** read completely; re-read for REV 2.
- v5.103.19: D8 night tails follow `HVAC_NIGHT_HOLD_STATES` (`sleep`, `waking`; `hvac_const.py:934`). `home_night`
  uses the day table. `FAN_TRUST_STATES` is unchanged.
- W1-B shipped (v5.103.18, §9e four gates).
- §3.2 records the dwell's denomination defect (it reads the LIGHTING clock) and points at the Stage B card; D5
  resolves it.
- Relevant sections: §2, §3.1-§3.3, §9c, §9d, §9.4, §9.7, §10.
- **C18:** with dwell 0, entry = wait for the next tick.
- **C24:** HVAC occupancy is not a faster clock today; this plan builds one.
- **§10:** no C1-C25 claim is re-asserted.

**Drift to fix in the build commit:**
- §3.2 (knob 48 = 10) and §8 (dwell = 2) are stale. Live values: grace 5, constrained 5, dwell 0.
- §3.1 line numbers are pre-B.
- The §3.2 dwell row -> D5.

### 0.2 Other docs and cards read
| Source | Use |
|---|---|
| Card `HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1` | Disposition; per-type tails; camera/BLE caveat. Kitchen timeout 600 -> 300 s (operator, 2026-09-27, verified live) |
| Card `HVAC-ENTRY-DWELL-ROOM-CLOCK-1` | Arm only when raw presence persists N s; keep the post-arm hold; hallways excluded by construction; two dwell plans superseded; measure flaps first. Operator 2026-09-26: "Room clock is not good for HVAC" |
| `AUDIT_hvac_raw_evidence_gaps_2026_09_26.md` | Per-type MID/LATE; T >= max MID - G. Day bucket = `home_day` + `home_evening` (82.4 h). Excluded `away`/`arriving`/`guest` (§8.6). `home_night` lumped with `sleep`/`waking` |
| `PLANNING_hvac_w2_occupancy_fast_path.md` REV 4 + card `HVAC-W2-OCCUPANCY-TRUTH` | Reused (section 13). The REV 4 re-review HIGHs are known only from the card summary. Card `next` defines the flap metric |
| `AUDIT_hvac_fast_path_rate_2026_09_26.md` | 16.6 zone-cold edges/day; cycle p95 27.6 s; L=60 denies 0/114 |
| `PLANNING_hvac_night_tail_follows_sleep.md` (B shipped) | `HVAC_NIGHT_HOLD_STATES` |
| Other cards | Section 12 |
| vibememo 153 | Why the fast path was parked |

### 0.3 Code surveyed (develop, post v5.103.19)

**`coordinator.py`**
- Occupancy block `:3538-3643`; `_last_motion_time` set on Tier-1 activity `:3589`.
- Camera override `:3663-3697`: source `"camera"`, failsafe guard `:3667`.
- BLE `:3699-3908`: source `"ble"`, failsafe guard `:3706`, cap `:3810-3847`.
- Fan-demoted `:4113`; failsafe `:4361`/`:4369`; override switches `:4790-4811`; skip-first `:4825`;
  `apply_fan_recheck_release` `:5249`.
- Poll `:625-631`; event refresh within 2 s `:1395-1411`; debounce anchor `:3544`; accessor pattern `:5384`.

**`hvac_zones.py`**
- `update_room_conditions` `:566`: entry loop `:611-647`, classify `:665`, zone loop `:666`, `clear()` `:667`,
  absent add `:687`, `room_occupied` `:718`.
- **Hallway exclusion `:725-736`.**
- Rollup `:772-789`; `current_session_start` `:786-789`; zone attrs `:791`.
- `_effective_hvac_hold_seconds` `:977-1049` (clamp `:1031-1047`); `_compute_hvac_occupied` `:1051-1126`.
- `conditioning_retreat_ok` `:1525`; diag `:1588`.

**`hvac.py`**
- `_zones_written_this_cycle` `:455`/`:1879`/`:3194` (read `hvac_override.py:4713`); `_zone_entry_dwell` `:562`.
- `_async_decision_cycle` `:1583`; `_track_task` `:1644`; `_run_decision_cycle` `:1873`.
- `_apply_house_state_presets` `:2132-3320`:
  - consensus `:2156`; enforcer `:2227`; arriving `:2261`; grace `:2271-2275`; loop `:2282`
  - row-1 + sweep `:2339-2426` (vacancy away when `zone_vacant_past_grace`, from `last_occupied_time` `:2340-2344`)
  - D6 `:2437`; D5 `:2568`
  - **lighting-session dwell skip `:2735-2748`** (only reader of `_zone_entry_dwell` and `current_session_start`)
  - D7 `:2780`; transient hold `:2860`; W1-B gates `:2918`; S1 write `:3125-3271`; DPM `:3319`
- `_pre_arrival_zones` set by `_handle_person_arriving` `:4567-4622`, expired `:4624-4654`.
- `_handle_energy_constraint` `:3843`; `_handle_zm_zones_updated` `:3908`; sweep `:4266`; presence states `:4775`;
  `get_mode_attrs` `:5411`; teardown `:5555`.

**Knob 47**
- `number.py:415-502` (`47 · Entry Wait (min)`, MINUTES, 0-15, step 1, BOX); `hvac_const.py:416-421`.
- `config_flow.py:5929`, `:6475-6478`; `__init__.py:7379-7390`; `button.py:843-860`.
- Migration `__init__.py:719-757` (DONE live); strings `:1166`/`:1197`.

**Elsewhere**
- Grace writers outside `number.py`: `button.py:857-858`, `__init__.py:7339/7353/7565`.
- `hvac_strategy.py` `:142`, `:187-197`, `:254-266`; `hvac_override.py:174`; `sensor.py:13684-13745`.
- HA `update_coordinator.py:170-182`, `:528-533`.

**Live config**
- Only Jaya has a day override (60, night 5400); 9 common rooms have night 90; timeouts 300-900 s.
- `switch.kitchen_override_vacant` off.

**Tests read:** `test_hvac_night_hold_follows_sleep.py`; `test_hvac_vacancy_hold_ui_defaults.py:140-171`;
`test_zzz_hvac_conditioning_demand.py:240-331/:505-523/:636-716/:774-775/:903-916`;
`test_v5_103_8_hvac_knobs_and_obs.py:120-170/:359-430`; `test_hvac_presence_timer_knobs.py`;
`test_part2_ec_hc_writeback.py`; `test_cm_reload_suppression.py`; `test_dpm_cleanup_and_labels.py:179`.

### 0.4 Config-first check
| Candidate | Solves it? | Why |
|---|---|---|
| Room `occupancy_timeout` | Partly (Kitchen stopgap) | Still two tick quantizations; no effect on entry or re-arm |
| Per-room holds | No | Today the hold starts after the lighting timeout |
| Knob 48 grace | No | Section 7.2 |
| Shorter tick | Rejected | Carrier bound; whole-house cycle |
| Jaya day override 60 | **Change (D4)** | Audit MID retreats at 60 |
| Knob 47 as it is today, set to 1 | No | Reads the lighting session (~300 s for a 10 s transit), so the zone still flips; also delays entry to the tick |
| Hallway room type | Done | `hvac_zones.py:725-736`; D5 targets non-hallway pass-throughs |

### 0.5 Prior-art scan: REUSE or BUILD
| Piece | Verdict | Symbol / reason |
|---|---|---|
| Evidence hold table | **REUSE, change values** | `ROOM_TYPE_HVAC_HOLD` `const.py:1219` |
| Shadow tail table | **BUILD (frozen, every type explicit)** | `ROOM_TYPE_HVAC_TAIL_LEGACY` |
| Shadow selector | **REUSE unchanged** | `_effective_hvac_hold_seconds` |
| Evidence / display selectors | **BUILD** | `_evidence_hold_seconds`, `_display_hold` |
| Night table, overrides, clamp, flow validation | **REUSE unchanged** | |
| State tuples | REUSE `HVAC_NIGHT_HOLD_STATES`; **BUILD** `HVAC_EVIDENCE_RULE_STATES` | |
| Evidence timestamp, active flag, onset | **BUILD (fields + 3 accessors)** | No existing field fits (`_last_motion_time`, `_last_trigger_time`, `_last_occupied_time`, `_occupancy_first_detected` all wrong) |
| Camera/BLE evidence | **REUSE override verdict** | `data[STATE_OCCUPANCY_SOURCE] in ("camera", "ble")` |
| Event source; lifecycle; zone-scoped decision; lock/tasks/timers | **REUSE** | `async_add_listener`; one `SIGNAL_ROOM_ENTRY_LIFECYCLE` subscription; `_apply_house_state_presets(zone_filter, …)`; `_decision_cycle_lock`, `_track_task`, `async_call_later` |
| Nudge-skip seed; limiter exemption; D5 edge test | **REUSE + extend** | `_zones_written_this_cycle`; `_zone_last_s1_write`, then `strategy_for(...).last_sent` |
| Pre-arrival membership | **REUSE** | `_pre_arrival_zones` (`hvac.py:4590`) [REV 5 HIGH-1] |
| Ledger, attrs, NM, probes, kill-switch pattern | **REUSE / BUILD one switch** | |
| Dwell knob | **REUSE, semantics moved** | knob 47; unit stays minutes |
| Arming episode state | **BUILD** | `_hvac_episode_start`, `_hvac_episode_onsets`, `_hvac_episode_active_s`, `_hvac_ev_released_at` |
| Transit exemption window | **BUILD (own constant)** [REV 5 HIGH-3] | `HVAC_TRANSIT_EXEMPT_WINDOW_S`. Split from `HVAC_QUICK_RETURN_WINDOW_S`: one number for two concepts is Bug Class #63 |
| Lighting-session dwell | **RETIRE** | `hvac.py:2735-2748` |

Memory consulted: suppression-needs-discharge, wire-in anchors, hollow anchors, marginal-benefit,
measure-before-build, coincidental-equality (#63), unrestored-drill, pyc staleness, zone-away-home-night gap.

### 0.6 Operator decision ledger
| # | Date | Ruling (verbatim) | Effect |
|---|---|---|---|
| R0 | 2026-09-27 ~22:00 | "fast path catches it. The room type hold blunts it. Do it" | Build the cycle |
| R1 | 2026-09-27 | "Shorter. I already articulated why it's not a big deal. We're measuring things that don't have the fast and slow protection and we're measuring without the time stacking." | Audit table for holds; Kitchen exception dropped |
| R2 | 2026-09-27 | "3mins" | Common-area evidence hold = 180 s |
| R3 | 2026-09-27 | "I think you should add this to the fast response plan. We want no seams. My instinct is it should go to 1 minute to allow for transients also though hallways are now excluded right?" | Stage B folded in as D5, 1 minute; hallways excluded (confirmed) |

**R1/R2 rationale (the operator's, as recorded):**
- The audit's margins were measured on today's design, with no re-arm fast path and with stacked timers.
- The quick-return trip-wire and the kill switch measure and bound the residual live. **The trip-wire is the live
  measure of the hold choice.**

---

## 1. Marginal-benefit note
- The audit weighed release speed alone. The operator added event-driven re-arm, which works only when the person moves
  again. Today's machine stays underneath; the new rule runs only in audit-measured states. The holds are rulings, and
  their arithmetic is context.
- **D5.** A 10 s pass-through of a cold room in an away zone always flips it today. With fast entry that flip would come
  within seconds.
- **[REV 5]** D5 now acts only on the away -> home edge. It never slows a room joining a zone that is already set to
  Home or in grace. Its cost is 60 s on a genuine arrival into an away zone.

---

## 2. Falsifiable invariants

**Definitions**
- `ev(R)`, `active(R)`, `onset(R)`: last evidence time, evidence at the latest refresh, start of the current active
  stretch.
- `hold_ev(R)`: from `_evidence_hold_seconds`.
- States: evidence (`home_day`, `home_evening`); night (`sleep`, `waking`); legacy = all others.
- `release(R)`: `ev + hold_ev` (evidence states); later of the shadow tail and `ev + hold_ev` (night); shadow tail
  (legacy).
- `E(Z)`: max `release(R)` over live non-hallway rooms.
- `P(Z, t)`: the periodic outcome for Z at `t`.
- `W`: knob 47 × 60 s. `J(R)`: episode join window, `min(hold_ev(R), W)` [REV 5 MEDIUM-2].
- **Away edge [REV 5 HIGH-1]:** `away_edge(Z)` iff Z's last S1 write was `away` (`_zone_last_s1_write[Z][0]`,
  falling back to `strategy_for(...).last_sent(...)`) AND `Z not in _pre_arrival_zones`. If neither record exists
  (e.g. after a restart), `away_edge` is False: fail-open toward immediate arming.
- **Cold room:** evidence state AND `away_edge(Z)` AND output False AND not released within
  `HVAC_TRANSIT_EXEMPT_WINDOW_S` (room-only exemption) [REV 5 HIGH-3].
- **Episode:** a run of evidence onsets, each within `J` of the previous `ev`. It lapses when `now > ev + J` without
  an arm.
- **Persisted:** `W == 0` OR `(active and now - episode_start >= W)` OR `ev - episode_start >= W`.

**INV-1 (re-arm = periodic outcome within the SLA)**
- Trigger:
  - a live non-hallway room of Z has an evidence advance at `t_r` while Z's stored fused value is False;
  - for a cold room, the trigger is "persisted became true", observed by the listener or the arm re-check.
- Required: a zone-scoped run for Z starts by `t_r + 45 s` and issues exactly `P(Z, t_run)` for Z only.
- After a `vacant_past_grace` away with target home/sleep, `P` is a home/sleep write unless an exception holds.
- Non-cold rooms are never delayed by D5.

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
| Cold room not yet persisted | no arm (transit filter) |

**INV-D5 (transit filter)**
- (a) A cold room whose episode never persists never produces `hvac_occupied = True`.
- (b) A cold room whose episode persists produces True by `t_persist + 45 s`.
- (c) D5 never applies in these cases:
  - night or legacy states;
  - hallways;
  - non-cold rooms;
  - a zone whose last S1 write was not `away`;
  - pre-arrival zones [REV 5 HIGH-1].

**INV-2 (no early vacancy away, evidence states) [REV 5 HIGH-1: contradiction resolved]**
- No `vacant_past_grace` away for Z at `t` while any live non-hallway room of Z has:
  - output True; or
  - an armed release with `release > t - G`; or
  - **a live (unlapsed) episode that has not yet persisted.**
- Mechanism: while any room of Z has a live unpersisted episode, the producer refreshes
  `zone.last_occupied_time = now` (the grace cannot elapse), and `room_release_at` returns `None` (no exit timer
  fires).
- This replaces REV 4's "a cold room inside its first `W` seconds does not count".
- Bound: an unpersisted episode lapses at `ev + J` (<= 60 s after the last evidence), so it can delay an away by at most
  `J` beyond the last evidence.

**INV-3 (exit = periodic outcome at the due time, once)**
- In evidence and night states, a `fast_exit` run starts in `[E + G + SLACK, E + G + SLACK + SLA]` and issues `P`.
- One run per episode, key `(Z, E(Z))`. A deferral consumes the key.
- `G` is the live grace at fire time.

**INV-4 (zone scope)**
- Climate writes only for Z, through S1; Z's vacancy sweep.
- Accepted house-wide effects: the display-only `zone_presence_state` refresh; `_expire_pre_arrival_zones`.
- It never calls: the enforcer, egress, `check_ac_reset`, fans, covers, predictor, anomaly, DPM, arrester sweeps,
  Carrier freshness.
- It never changes another zone's room conditions or rollup fields.

**INV-5 (shadow, night, legacy)**
- Today's machine runs byte-for-byte on every pass and alone owns `_hvac_armed`, `_hvac_prev_state_occupied`,
  `_hvac_tail_until`.
- Night and legacy output is at least the shadow's.
- In legacy states there is no back-fill, no exit timer and no D5.
- An evidence-state -> `sleep` crossing mid-lighting-timeout is held by the shadow.

**Equivalence.** Fast run for Z at `t` == `P(Z, t)`. Seeds must include writes and every exception row.

---

## 3. Producer and consumer map

### 3.1 Producer
| Step | After |
|---|---|
| Shadow (every state) | Today's machine on `data["occupied"]`; tail from `_effective_hvac_hold_seconds` |
| Evidence-state output | Non-cold: `active OR now < ev + hold_ev`. Cold: that AND persisted (D5). Evidence term held through refresh failures up to 600 s after `ev` |
| Night-state output | `shadow OR active OR now < ev + hold_ev` (no D5) |
| Legacy-state output | shadow |
| Rollup | As today. While any room has a live unpersisted episode: `last_occupied_time = now` [REV 5]. Back-fill `last_occupied_time = max(lot, E)` when fused False and no live episode, in evidence/night states only |

Dependency health: the stamp depends on the room refresh (event-driven within 2 s; poll 30-35 s) and the existing
fusion filters. One firing camera (Living Room); 3 phones for BLE.

**Side-finding (D5 review) [REV 5]:** `binary_sensor.occupancy_lux_temp_humidity_hobeian_dining_presence` (the Dining
Room radar) has not been `on` in 24 h. That affects Dining Room evidence under every rule. The orchestrator will card
it; no plan action.

### 3.2 Consumers
| Consumer | Site | Kind | Effect |
|---|---|---|---|
| Zone rollup `any_room_hvac_occupied` | `hvac_zones.py:178` | feeds below | Flips sooner in evidence states; re-arms on evidence; cold rooms on the away edge after 60 s |
| `conditioning_retreat_ok` -> row-1 vacancy away | `hvac_zones.py:1525`; `hvac.py:2339-2426` | TRUST | INV-2/INV-3 |
| Vacancy sweep | `hvac.py:2416-2426` -> `:4266` | ACTUATION (Z's lights/fans) | For Z in fast runs; 5.9 |
| Row-1 transient hold | `hvac.py:2360-2392`, `:2860-2911` | TRUST | Unchanged |
| D6 stale failsafe | `hvac.py:2437-2539` | TRUST | Fires less |
| D5 energy-shed coast defer | `hvac.py:2643-2709` | TRUST | Ends sooner |
| D7 night trust | `hvac.py:2780-2852` | TRUST | Night >= today |
| D9 compose-away (dormant) | `hvac.py:3484-3518` | TRUST | Tick only |
| Arrester row-10 | `hvac_override.py:2513-2557` | TRUST | Expires sooner in an emptied zone |
| Pre-cool F8 / pre-heat F9 | `hvac_predict.py:583`, `:1420` | TRUST | Tick only |
| Grace math | `hvac_zones.py:772-780`; `hvac.py:2340-2344` | TRUST | Back-fill; held at `now` during a live episode |
| `zone_presence_state`; zone-intelligence sensor | `hvac.py:4775`; `sensor.py:13684` | DISPLAY | Fast-run cadence |
| W1-B four gates | `hvac.py:2918-2996` | TRUST | Same S1 body |
| Arrester nudge skip | `hvac_override.py:4713` | TRUST | Seeded from recent S1 writes |
| Lighting-session dwell | `hvac.py:2735-2748` | TRUST | Retired; replaced by D5 |
| Pre-arrival | `hvac.py:4567-4654` | — | Full cycle waits behind a fast run; expiry runs in fast runs; **pre-arrival zones bypass D5** [REV 5] |
| Fans; presence D6 source 4 | `hvac_fans.py:761/:997`; `presence.py:2147-2159` (LIGHTING) | — | Unaffected |
| Per-room `binary_sensor.<room>_<room>_hvac_occupied` | `binary_sensor.py:745-920` | DISPLAY | Attrs `rule`, `last_evidence_at`, `release_at`, `episode_start`, `episode_onsets`, `episode_active_s`, `armed_at`, `dwell_s`, `exempt_reason`; `hvac_vacancy_hold_s` via `_display_hold` |
| Zone status sensor | `hvac_zones.py:791-895` | DISPLAY | `hvac_empty_since`, `away_due_at`, `pending_arm_rooms` |
| `sensor.ura_hvac_coordinator_mode` | `hvac.py:5411` | DISPLAY | Counters incl. `transit_filtered_today`, `same_room_returns_today` |
| `optimization.py:2398-2430` | `continuous_occupied_since` | analysis | Shorter spans |

---

## 4. D1: HVAC's own release clock

### 4.1 Evidence stamp (`coordinator.py`)
- **Fields:** `_last_hvac_evidence_time`, `_hvac_evidence_active`, `_hvac_evidence_onset`.
- **Accessors** (next to `:5384`): `get_last_hvac_evidence_time()`, `is_hvac_evidence_active()`,
  `get_hvac_evidence_onset()`.
- **One stamp site** after `:4811`, before `:4825`:
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
- On a suppressed tick: no stamp and no falling-edge stamp on the next tick.
- `apply_fan_recheck_release` clears the active flag without stamping.
- **Camera/BLE count only after the room's own lighting timeout** (the override blocks run only then; they carry their
  failsafe guards, the BLE chain rule and the cap).
  - Possible two-write flap for a BLE-only still person where timeout - `hold_ev` > 300 s: Master Bathroom 720,
    Jaya Bathroom 720, Exercise Room 720, Oji Vanity 420, Study A 420, Kitchen Pantry 380, Ziri Bathroom 360,
    Game Room 360.
  - Living Room: 120 s, so no flap.
- Override Vacant gives no evidence. All fields are in memory and cleared on restart.

### 4.2 Producer: shadow plus rule output (`hvac_zones.py`)
`_compute_hvac_occupied` keeps its body as the shadow and gains `last_evidence`, `evidence_active`, `onset`,
`refresh_ok`, `entry_dwell_s`, `away_edge` keywords.

1. **Shadow.** As today, with `hold_s` from `_effective_hvac_hold_seconds`. Only the shadow writes `_hvac_armed`,
   `_hvac_prev_state_occupied`, `_hvac_tail_until`, `_hvac_arm_source`. Result: `shadow_out`.
2. **Evidence term.** `ev_out = evidence_active or (last_evidence is not None and now < last_evidence + hold_ev)`.
   Store `_hvac_day_release_at`.
3. **Refresh-failure hold (evidence states, evidence term only).** If `refresh_ok is False` and the previous output was
   True: keep True for at most `HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S` = 600 s after `last_evidence`.
4. **D5 (evidence states only).** Update the episode (5b.2). If the room is cold and `W > 0`:
   `ev_out = ev_out and persisted`. Record `pending_arm = episode live and not persisted`.
5. **Output.**
   - evidence -> `ev_out`; night -> `shadow_out or ev_out` (no D5); legacy -> `shadow_out`
   - Store `_hvac_output`, `_hvac_rule`, `_hvac_pending_arm`.
   - Stamp `_hvac_ev_released_at` on an evidence-state True -> False (every release, so the exemption renews).
   - The evidence branch never writes the shadow's dicts.

Readers use `isinstance(…, datetime)` and `is True`; `refresh_ok = coordinator.last_update_success is not False`.

### 4.3 States
- `sleep`/`waking`: shadow OR evidence (no D5).
- `home_night`: legacy until Gate B.
- `guest`, `arriving`, `away`, `None`: legacy.

### 4.4 Selectors
| Selector | Returns | Callers |
|---|---|---|
| `_effective_hvac_hold_seconds` (unchanged) | Shadow tail: night table in night states, legacy table otherwise; overrides; clamp | Shadow only |
| `_evidence_hold_seconds(room_type, override_day)` | `override_day` or `ROOM_TYPE_HVAC_HOLD.get(type, DEFAULT_HVAC_VACANCY_HOLD)` | Evidence term, `room_release_at`, `J` |
| `_display_hold(...)` | `(hold, rule)` | `binary_sensor.py:894` |

Clamp and flow validation are unchanged.

### 4.5 Release instant [REV 5 HIGH-1]
- **`room_release_at(room)`** reads the live accessors. It returns `None` (unbounded) while:
  - `active`; or
  - the shadow rides `occupied` (night/legacy); or
  - **the room has a live unpersisted episode (`pending_arm`).**
- **Back-fill:** on a fused-empty pass in evidence/night states with no pending room, `last_occupied_time =
  max(lot, E(Z))`. If any room is pending, set `last_occupied_time = now` instead.
- `zone_release_at` / `zone_away_due_at(Z, grace_s)` as defined.

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
The comment cites the rulings and names the trip-wire as the live check. `DEFAULT_HVAC_VACANCY_HOLD` (60) is the
unknown-type fallback.

### D1 acceptance
- **Anchors:** `test_evidence_state_ignores_lighting_timeout`; `test_home_evening_to_sleep_mid_timeout_stays_held`
  (drill: evidence branch writes `_hvac_armed`); `test_shadow_dicts_untouched_by_evidence_branch`;
  `test_home_night_is_legacy_until_gate`; `test_guest_arriving_away_are_legacy`.
- **Holds and refresh failure:** `test_hold_zero_holds_while_active`; `test_hold_shorter_than_poll_no_drop_while_on`;
  `test_refresh_failure_hold_evidence_states_only_and_bounded`.
- **Stamping:** `test_camera_ble_stamp_only_from_override_verdict`;
  `test_no_stamp_on_fan_demoted_failsafe_recheck_sources`; `test_override_vacant_blocks_stamp`;
  `test_falling_edge_refresh_stamps`; `test_fan_recheck_release_clears_active`; `test_ble_cap_stops_stamp_after_cap`.
- **Back-fill:** `test_last_occupied_time_backfilled_to_exact_release`; `test_no_backfill_in_legacy_states`.
- **Tables:** `test_evidence_hold_values` (independent literals, common 180); `test_legacy_tail_is_frozen_v5_103_19`;
  `test_selectors_split`.
- **Other:** `test_per_room_day_override_wins`; `test_accessor_fallback_uses_isinstance_datetime`.
- **Live:** in `home_day`, `release_at == last_evidence_at + hold_ev`, and the off transition lands by
  `release_at + 335 s`.

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
- `_fast_path_gates_open`: not tearing down, enabled, boot-settle done, kill switch on, not observation mode, zone
  intelligence on, zone in `zm.zones`, zone not tripped.
- `_zone_away_edge(Z)` implements the definition in section 2 [REV 5]. Periodic cycles pass the same function.

### 5.2 `_apply_house_state_presets(*, zone_filter=None, trigger="periodic", edge_ts=None) -> bool`
- `zone_filter is None`: byte-identical except that the lighting-session dwell skip (`:2735-2748`) is removed.
- With `zone_filter`: skip the enforcer and DPM; loop-top `continue` for other zones. Everything else as today,
  including Z's sweep.
- Ledger fields on `preset_change`: `trigger`, `edge_ts`, `zone_empty_since`, `exempt_reason`.
- Every S1 write sets `_zone_last_s1_write[zone] = (preset, utcnow)`. **Only** a `vacant_past_grace` away sets
  `_zone_vacancy_away_at[zone]` (kept for the trip-wire; no longer used by D5) [REV 5].
- Returns whether a write was applied.

### 5.3 `update_room_conditions(house_state, zone_ids=None, entry_dwell_s=None, away_edge_fn=None)`
- Zone filter before `clear()`.
- Absent set built in the entry loop.
- `_classify_all_rooms` over all rooms.
- D5 inputs threaded through; `away_edge_fn=None` means False.

### 5.4 Entry trigger
Setup: subscribe to `SIGNAL_ROOM_ENTRY_LIFECYCLE`, then enumerate and attach; attach is idempotent.

`_on_room_refresh(entry_id, *, from_step=1)` (sync), in order:
1. Gates.
2. Skip hallways; resolve the zone live.
3. Evidence advance (`None` rule).
4. D5: update the episode. If the room is cold and not persisted:
   - schedule the arm re-check if the zone is cold;
   - return.
5. Zone-cold gate (stored fused True -> return) **and** tripped zone -> count, return.
6. Per-zone limiter (60 s) on entry runs. Exempt iff `_zone_last_s1_write[zone][0] == "away"`, else
   `last_sent == "away"`.
7. Dedup.
8. Queue `fast_entry`, with `edge_ts = now` and `exempt_reason` carried if D5 was skipped by the room exemption.

### 5.5 Lock rules
- Fast runs wait for the lock.
- A periodic cycle waits only while `_fast_path_running` (set inside the lock); skips behind a full cycle; skips after
  acquiring if a full cycle ran in the meantime.
- Nudge-skip seed at cycle entry: zones with an S1 write within 120 s.

### 5.6 Exit timer
- Scheduled at the end of every full cycle (all zones) and fast run (its zone).
- Preconditions: kill switch on, zone intelligence on, not observation mode, established, evidence or night state,
  target home/sleep, not already sent away, not egress-paused, not tripped.
- `due = zone_away_due_at(Z, grace_s) + 2 s`; `None` (including a pending room) -> no timer.
- One-shot key `(Z, zone_release_at)`.
- **The callback recomputes from live evidence and the live grace** (`hvac.py:2271-2275`): not due -> lazy reschedule;
  due -> queue `fast_exit`, exempt from the limiter.
- The exit run's producer pass applies D5 and the pending rule.
- Reschedule hooks (`number.py`, `_handle_energy_constraint`) only reduce latency. Bypass writers
  (`button.py:857-858`, `__init__.py:7339/7353/7565`) can only delay.
- Pruned zones cancel their timers.

### 5.7 Ceiling, runaway guard, trip-wire, kill switch, restart
- **Write ceiling:** more than 6 fast writes per zone per hour -> NM; tick-only until local midnight.
- **Runaway guard:** more than 30 runs per zone per hour -> same.
- **Quick-return trip-wire [REV 5 HIGH-3]:**
  - Counts a `fast_entry` within `HVAC_QUICK_RETURN_WINDOW_S` (900 s) of a `vacant_past_grace` away on that zone,
    **excluding rows tagged `exempt_reason`** (room-exemption re-arms, per the D5 review).
  - At 12 per zone per day: one LOW NM.
  - Exempt re-arms are counted separately in `same_room_returns_today` (no NM). See section 19 #11.
- **Kill switch** `31 · Fast Room Response`: OFF = tick timing; D1 and D5 still apply at passes.
- **Global limiter G:** dropped.
- **Restart:** all counters, trips, `_fp_last_ev`, `_zone_last_s1_write`, `_zone_vacancy_away_at`, episodes, exemptions
  and timers are in memory and reset. Rooms start cold. `away_edge` is False until the first S1 write (fail-open).

### 5.8 Teardown
Set `_tearing_down`. Before the first `await`: release listeners; cancel exit and arm timers; clear the queue. Tasks
are cancelled at `:5565`. Every callback checks `_tearing_down`.

### 5.9 Vacancy sweep timing
Accepted, not gated. It never precedes the room's own lighting vacancy.

### D2 acceptance
- **Premise:** `test_rearm_while_lighting_still_on_triggers_fast_entry`; `test_evidence_during_grace_prevents_away`;
  `test_rearm_limiter_exempt_keyed_on_last_sent`; `test_limiter_exemption_order`.
- **Nudge skip:** `test_fast_write_seeds_nudge_skip_on_next_tick`.
- **Queue and lock:** `test_queue_entry_cleared_on_every_exit_path`; `test_gates_rechecked_after_lock_wait`;
  `test_fast_path_running_only_true_while_holding_lock`.
- **Zone scope:** `test_fast_run_is_zone_scoped`; `test_s1_writes_only_origin_zone`; `test_fast_run_sweeps_only_its_zone`;
  `test_fast_run_leaves_sibling_zones_untouched`; `test_absent_set_built_before_zone_loop`;
  `test_fast_decision_equals_periodic_decision`.
- **Exit timer:** `test_exit_timer_fires_at_release_plus_grace` (normal 10 / constrained 3);
  `test_exit_timer_uses_grace_at_fire_time`; `test_exit_timer_reads_live_evidence`; `test_exit_timer_lazy_reschedule`;
  `test_exit_timer_one_shot_under_feed_disagreement`; `test_exit_timer_one_shot_consumed_on_gate_e_deferral`;
  `test_exit_timer_cancelled_on_zone_prune`.
- **Listener:** `test_listener_ignores_refresh_without_evidence_advance`; `test_listener_skips_warm_zone`;
  `test_listener_skips_hallway`; `test_entry_limiter_denies_second_run_within_60s`; `test_two_zones_same_second`;
  `test_fp_last_ev_none_rule`; `test_subscribe_then_enumerate_no_miss_no_double`.
- **Lifecycle and teardown:** `test_periodic_waits_behind_fast_run`; `test_periodic_skips_behind_full_cycle`;
  `test_waiting_periodic_skips_if_full_cycle_ran`; `test_listener_lifecycle_idempotent`;
  `test_boot_settle_suppresses_fast_path`; `test_teardown_releases_before_first_await`;
  `test_tearing_down_guards_every_callback`.
- **Guards:** `test_write_ceiling_trips_and_clears_at_local_midnight`; `test_runaway_guard_trips_at_31_runs`;
  `test_quick_return_counter_and_nm_latch`; `test_kill_switch_off_restores_tick_only`;
  `test_preset_change_row_carries_trigger_edge_ts_zone_empty_since`.
- **Config boundaries:** grace 0/60; day hold 0; knob 47 = 0/15.

---

## 5b. D5: transit filter on the away -> home edge [RULING R3, REV 5]

### 5b.1 Rule (evidence states only)
```
away_edge = (_zone_last_s1_write[Z][0] == "away") if Z in _zone_last_s1_write
            else (strategy_for(...).last_sent(entity, "set_preset_mode") == "away")
away_edge = away_edge and Z not in _pre_arrival_zones
exempt    = released_at[R] is not None and now - released_at[R] <= HVAC_TRANSIT_EXEMPT_WINDOW_S
cold      = away_edge and not prev_output[R] and not exempt
if not cold or W == 0:  output = ev_out
else:                   output = ev_out and persisted(R, now)
```
- **Why only the away edge [REV 5 HIGH-1].** If the zone is Home or in grace, a room joining it is not a transit
  problem: nothing flips. Delaying that room would let the zone's grace expire and write away while someone is present.
- **Zone 3 repro:** bedroom evidence ends at t = 0, releases at 240. Kitchen entry at 510. Grace due at 542. Under REV
  4 the Kitchen was treated as cold, so the zone went away at 542 and flipped back at 570. Under REV 5 the zone's last
  write is `home`, so D5 does not apply: the Kitchen arms at 510 and there is no away.
- **Belt:** if `away_edge` is misjudged (e.g. the `last_sent` fallback), a pending episode still holds
  `last_occupied_time` (INV-2), so no vacancy away lands while it is live.
- Night states: `shadow_out or ev_out`, no D5. Legacy: shadow. Hallways never reach this code
  (`hvac_zones.py:725-736`).
- Pass-throughs filtered: Kitchen, Dining Room, Breakfast Nook, Butler Pantry, Kitchen Pantry, Laundry, closets — only
  when their zone is set to away.

### 5b.2 Episode tracking (`ZoneManager._update_arming_episode`, from the listener and every producer pass) [REV 5 MEDIUM-2]
- `J = min(hold_ev(R), W)`.
- If the room is not cold: clear the episode.
- Else, if there is no episode, or `onset - prev_ev > J`: start a new episode (`episode_start = onset`, onsets = 1).
- Else join the episode (onsets += 1).
- Accumulate `episode_active_s`.
- If `now > ev + J` without an arm: the episode lapses and `transit_filtered_today` += 1.

Examples:
- **Closet (hold 60, W 60, J 60):** a 10 s transit lapses at 70, filtered. A 90 s stay with pulses at 0/50/85 arms at
  85.
- **Kitchen (hold 180, W 60, J 60):** pulses 70 s apart start new episodes and are never joined.

### 5b.3 Room-only return exemption [REV 5 HIGH-3]
- A room released within `HVAC_TRANSIT_EXEMPT_WINDOW_S` re-arms immediately: the still person who moves again in the
  same room.
- The exemption renews on every release (`released_at` is stamped each time).
- The **zone** exemption from REV 4 is dropped. A person who moves to a different room of an away zone waits `W`.
- `HVAC_TRANSIT_EXEMPT_WINDOW_S`: rung 1, placeholder 900, **to be sized from the D0c replay** (distribution of
  same-room release -> re-detection gaps).
- Exempt re-arms carry `exempt_reason="same_room_return"` on the room attrs and the `preset_change` row. They are
  excluded from the quick-return trip-wire count and counted in `same_room_returns_today`.
- **Checkpoint item 3:** "room-only 15-minute return exemption".

### 5b.4 Arm re-check timer [REV 5 MEDIUM]
- Scheduled from `_on_room_refresh` step 4 for a cold, non-persisted room in a cold zone, at
  `episode_start + W + HVAC_ARM_RECHECK_SLACK_S`. One per room, keyed by `episode_start`.
- Callback:
  - tearing down -> return;
  - recompute the episode from live accessors;
  - persisted -> **re-enter `_on_room_refresh(entry_id, from_step=5)`** (zone-cold gate + tripped check, limiter, dedup,
    queue). It does not queue directly.
  - lapsed -> drop;
  - otherwise -> nothing (the next advance re-checks).
- **Kill switch off and a house-state exit** (leaving `home_day`/`home_evening`) are handled by the gates at fire time:
  - `_fast_path_gates_open` in the fast run (pre-lock and post-lock) blocks a run with the switch off;
  - a run in a non-evidence state computes `P(Z, t)` with no D5.
- A re-check that fires into a zone that has since become warm stops at the step-5 zone-cold gate.
- Cancelled on episode lapse, room arm, zone prune, room unload and teardown (before the first await).

### 5b.5 Knob 47 moves; the lighting-session dwell retires
- Remove `hvac.py:2735-2748`; `_zone_entry_dwell` is read only by D5 (passed as `entry_dwell_s`). This is
  behaviour-neutral at the live value 0 (the old guard `:2740`).
- The old skip also covered `home_night`, `guest` and `waking`; D5 does not.
- Unchanged: key, entity, unique_id, in-place apply, reset button, migration.
- Default `DEFAULT_ZONE_ENTRY_DWELL_MINUTES` 0 -> **1**. Live stays 0 until the operator sets it to 1 (D4).
- Unit stays minutes (1 min = 60 s).
- **0 = transit filter off.**

### 5b.6 D5 acceptance (includes the Stage B card's criteria)
**Card criteria**
- **C1. Brief transits stop flipping zones.**
  - Flap = an S1 home/sleep write followed by a `vacant_past_grace` away within 20 min, same zone.
  - Live, knob 47 = 1: the 7-day evidence-state flap count is below the D0a baseline.
  - **C1 alone is not a discriminator** (fewer flaps can also come from fewer people at home) [REV 5 MEDIUM-2].
- **C1-D (discriminator) [REV 5]. The filter is working iff:**
  - `transit_filtered_today` > 0 on occupied days, at a rate within 2x of D0c's predicted filtered episodes; AND
  - away -> home arms that remain split as predicted by D0c:
    - clean (one onset, `active_s >= W`),
    - joined-transit (onsets >= 2, `active_s < W`),
    - exit-pulse (last onset >= W after the start with a gap before it);
    - joined-transit + exit-pulse arms are <= 2x D0c's prediction.
- **The filter is defeated if:** `transit_filtered_today` ~ 0 while flaps persist, or joined-transit/exit-pulse arms
  dominate the remaining flaps. The per-room attrs (`episode_onsets`, `episode_active_s`, `armed_at`) classify each
  arm.
- **C2. CRIT-1 untouched:** `test_d5_does_not_change_release`.
- **C3. Hallways excluded by construction:** `test_hallway_never_arms_with_dwell` is labelled a **construction check**:
  it verifies that the upstream exclusion keeps hallways out of D5; it does not exercise D5 logic [REV 5].
- **C4.** SUPERSEDED banners on the two dwell plans; the card closes as folded.

**Tests**
- Transit and stay:
  - `test_transit_under_60s_no_write`, with a **Kitchen PIR-pulse variant**: UP Sense pulses at 0 and 20 s, cold away
    zone3 -> no write [REV 5].
  - `test_stay_60s_writes_within_sla` (continuous radar -> write in `[60, 105] s`, `trigger=fast_entry`).
  - `test_intermittent_pir_stay_arms_on_pulse_after_window`.
- Episodes:
  - `test_gap_longer_than_join_window_starts_new_episode` (`J = min(hold, W)`).
  - `test_joined_transits_within_j_arm_and_are_classified` (onsets 3, `active_s` 25 -> arm tagged joined-transit)
    [REV 5].
  - `test_episode_lapses_at_ev_plus_j_and_counts_filtered`.
- **Unarmed episode blocks away [REV 5 HIGH-1]:**
  - `test_zone3_repro_no_away_when_kitchen_enters_during_grace` (bedroom released 240, Kitchen 510, no away at 542;
    the Kitchen arms at 510 because `away_edge` is False).
  - `test_unarmed_episode_blocks_vacancy_away` (`away_edge` forced True by a stale `last_sent` while the zone is Home
    in grace: a pending episode holds `last_occupied_time`; no away until the lapse).
- D5 scope [REV 5 HIGH-1]:
  - `test_d5_only_on_away_edge` (zone last write `home` -> arms immediately; last write `away` -> dwell).
  - `test_pre_arrival_zone_bypasses_d5`.
  - `test_away_edge_unknown_after_restart_fails_open`.
- **Exemption [REV 5 HIGH-3]:** `test_same_room_return_rearms_immediately`; `test_exemption_renews_on_each_release`;
  `test_other_room_in_away_zone_waits_w` (no zone exemption); `test_rearm_after_window_is_cold` (boundary at
  `HVAC_TRANSIT_EXEMPT_WINDOW_S + 1`); `test_exempt_rearm_excluded_from_quick_return_count` (and counted in
  `same_room_returns_today`).
- `test_zone_vacancy_away_at_stamped_only_on_vacant_past_grace` (house-state away, D5 shed away and D6 stale away do
  not stamp) [REV 5].
- Scope and knob: `test_warm_room_no_dwell`; `test_dwell_zero_is_rev3_behaviour`; `test_dwell_only_in_evidence_states`.
- Re-check timer:
  - `test_arm_recheck_scheduled_at_onset_plus_w`.
  - `test_arm_recheck_reenters_at_step_5` (spy: step-5 entry, no direct queue) [REV 5].
  - `test_arm_recheck_into_warm_zone_stops_at_gate` [REV 5].
  - `test_arm_recheck_kill_switch_off_no_run`, `test_arm_recheck_after_house_state_exit_runs_without_d5` [REV 5].
  - `test_arm_recheck_cancelled_on` × {lapse, arm, prune, unload, teardown}, parametrized [REV 5].
- `test_exit_run_arms_persisted_room_before_away`.
- **`test_lighting_session_dwell_removed` (behavioural) [REV 5]:** knob 47 = 1, house `home_night`, zone lighting
  session 20 s old, room armed by the shadow -> S1 still writes the home/sleep target this pass. The old skip would
  have blocked it. Neutering the removal (re-inserting the skip) turns it RED.
- `test_d5_does_not_change_release`; `test_hallway_never_arms_with_dwell` (construction check);
  `test_evidence_onset_accessor`.
- `test_transit_helper_text_matches_constant` (the "15 minutes" in the knob 47 helper equals
  `HVAC_TRANSIT_EXEMPT_WINDOW_S / 60`) [REV 5].

**Live**
- Per-room attrs `episode_start`, `episode_onsets`, `episode_active_s`, `armed_at`, `dwell_s`, `exempt_reason`.
- Mode-sensor attrs `transit_filtered_today`, `same_room_returns_today`.
- For 10 away-edge cold arms with continuous evidence: `armed_at - episode_start` in `[60, 105] s`.

---

## 6. Latency budget (before -> after)
Grace 300 s, tick 300.3-301.1 s, poll 30-35 s, refresh within 2 s. Today the grace is absorbed by tick quantization.

| Path | Today (live) | After |
|---|---|---|
| Entry into an away zone, knob 47 = 1 | avg ~2.5-3 min, worst ~5.5 min | 60 s + a few seconds (<= 105 s) |
| Entry into an away zone, knob 47 = 0 | same | usually < 5 s; <= 45 s |
| Entry into a zone that is Home / in grace | no write needed | immediate arm; no write needed [REV 5] |
| Pass-through under 60 s of a room in an away zone | home at the next tick, then away (a flap) | no write |
| Same-room re-arm after a wrong away (within 15 min) | avg ~2.5, worst ~5 min | usually < 5 s; <= 45 s |
| Other-room entry into a zone just set away | avg ~2.5, worst ~5 min | 60 s + seconds (no zone exemption) [REV 5] |
| Still person who does not move | held by timeout + tail | held by the hold ONLY |
| Exit, `home_day`/`home_evening`, 300 s room | avg ~12.8 min | hold + 5: closet/infra 6; generic/utility/media/garage 7; bath 8; common 8; bedroom 9 |
| Exit, 900 s room | avg ~22.8 min | bath 8 / common 8 |
| Exit, Kitchen | ~12.8 (300 s stopgap) | 8 min |
| `home_night`, `guest`, `arriving` | today's rule | unchanged |
| `sleep`/`waking` | timeout + night hold + tick | same or later; release + 5 min |

A live unpersisted episode can hold an exit by at most `J` (<= 60 s) after the last evidence [REV 5].

---

## 7. Residual risk (evidence states only)

### 7.1 Audit counts at the ruled values (G = 300, 6.74 days) — context, operator-accepted
| Class | At the ruled table | Today |
|---|---|---|
| MID zone retreat | ~13 (common 180, all Kitchen; others 0; bedroom 240 between 1 and 0) | 0 |
| MID with Jaya override 60 left | +2 (D4) | 0 |
| LATE zone retreat | ~36 (Kitchen 29, Dining 2, Master Bath 1, Jaya Bath 1, bedrooms <= 1) | 0 |
| Total | ~49 / 6.74 d ≈ 7/day, mostly zone_3 | 0 |

- **Context, not a gate (R1).** A person who does not move stays at away until they do.
- **Kitchen exception dropped:** operator-accepted in spirit; confirm at the checkpoint. 29/36 LATE and all MID are the
  Kitchen; 30/30 Kitchen LATE had evidence elsewhere; timeout already 300 s; a config override stays available.

**D5 known limitations [REV 5 MEDIUM-2]:**
- **Kitchen PIR joined transit.** The Kitchen UP Sense PIR pulses briefly. Two or three passes through the Kitchen
  within `J` (60 s) of each other join into one episode. If the passes span >= 60 s, the room arms although nobody
  stayed.
- **Exit pulse.** A person who stands still just inside a room (no pulse) and leaves 60+ s after entering produces a
  second pulse on the way out, which lands >= `W` after the start. The room arms as they leave, and the zone flips.
- **Hobeian 31 s minimum on-time.** HOBEIAN radars hold `on` for at least ~31 s per trigger. A 5 s pass shows as a
  31 s active stretch; two triggers within `J` join to >= 60 s and arm.
- The D0c replay counts each case separately; C1-D uses them as the "defeated" signal.

**Other D5 residuals:**
- Real arrivals into an away zone wait 60 s.
- A person who enters a cold room and stays still for the first 60 s is treated as a transit until they move.
- Sparse-PIR closets may not arm.
- A person moving to a *different* room of a zone just set away waits 60 s (no zone exemption).

**Side-finding:** the Dining Room radar (`binary_sensor.occupancy_lux_temp_humidity_hobeian_dining_presence`) has not
been `on` in 24 h. The orchestrator is carding it.

### 7.2 Context arithmetic (no recommendation) [RULING R2]
| Type | Sample max day MID gap | T + G at the ruled values |
|---|---|---|
| common_area | 603 s | 180 + 300 = 480 s |
| bedroom | 495 s | 540 s |
| generic / utility | 396 / 386 s | 420 s |
| bathroom | 836 s | 480 s (audit measured 0 at 180: co-occupied) |
| closet | 204 s | 360 s |

Recorded as context; the operator accepts it. Knob 49 enters the same sum under coast/shed. The trip-wire is the live
measure.

---

## 8. D0: probes (read-only)
- **D0a baselines** (>= 3 occupied days, earliest 2026-09-30): entry and exit latency per zone; flap rate (S1
  home/sleep -> `vacant_past_grace` away within 20 min), with the arming room and its raw evidence duration where
  recoverable.
- **D0b:** `climate_write` baseline, >= 3 days.
- **D0c residual + W replay:** `hvac_raw_evidence_gap_probe.py --graces 300,600`, T grid + 240. The replay applies the
  REV 5 rule (away edge only, `J = min(hold, W)`, room exemption) and reports **separately** [REV 5 MEDIUM-2]:
  - filtered episodes;
  - clean arms;
  - **joined-transit arms**;
  - **exit-pulse arms**;
  - predicted flap reduction;
  - **the distribution of same-room release -> re-detection gaps, which sizes `HVAC_TRANSIT_EXEMPT_WINDOW_S`**
    [REV 5 HIGH-3].
  - Gate A: ZR > 2x the audit figure at the ruled T -> stop.
- **D0c-home_night:** Gate B, as before.

---

## 9. Live acceptance
| # | Check | Pass | Failure looks like |
|---|---|---|---|
| L1 | Entry latency | knob 1: >= 90 % of away-edge `fast_entry` rows in `[60, 105] s` after `episode_start`; knob 0: <= 45 s | uniform 0-300 s |
| L2 | Exit exactness | `fast_exit` away: `row_ts - zone_empty_since` in `[g, g + 50] s` | `[g, g + 300]` spread; `< g` |
| L3 | INV-2 live | each evidence-state away: every room `release_at <= row_ts - g`, no `pending_arm_rooms` | any pending room or later release |
| L4 | Re-arm | same-room quick return: `fast_entry` within 45 s of `edge_ts` (zone_1 excluded while §9.7 is open) | tick only |
| L5 | Zone scope | no other-zone writes; no enforcer/nudge/cover/fan; sweep only for Z | any |
| L6 | Clock decoupled | D1 Live | — |
| L7 | Night/legacy unchanged | `rule` night/legacy; no early release; no legacy back-fill | — |
| L8 | Write rate | per-zone `climate_write`/day <= D0b + spread + 10; no ceiling trips | — |
| L9 | Quick returns | 7-day non-exempt sum within 2x the D0c prediction | much higher |
| L10 | Lifecycle | one listener per room after reload and restart | — |
| L11 | Nudge skip | no `nudge_started` within 120 s of a fast write on that zone | — |
| L12 | D5 C1 + C1-D + C3 | 5b.6 | 5b.6 |
| L13 | No short arms | knob 1: zero away-edge arms with `armed_at - episode_start < 60 s` and no `exempt_reason` | any |
| L14 [REV 5] | No away-edge misfire | zero `vacant_past_grace` aways while that zone had `pending_arm_rooms` | any |

Results go into the README as a `Validated <date>` table.

---

## 10. D3: vacancy grace re-check
Knob 48 (5), no code. Section 7.2 is context. After >= 7 days live, adapt `hvac_vacancy_grace_probe.py`. The operator
decides.

## 10b. D4: config step
- Clear Jaya Bedroom's day override.
- **Set knob 47 to 1** once D5 is live (checkpoint).
- Kitchen override only if the operator reverses the ruling.

---

## 11. Tier: 3
**Why:** changes the still-person safeguard and the arming edge; adds triggers and timers into the shared lock and the
S1 site; two failed plan reviews before.

**Protocol:**
1. D5 re-review of REV 5.
2. Build.
3. Four parallel reviews: A local correctness; B integration/state machine; C per-site mutation; D adversarial
   completeness.
4. Orchestrator re-grep and re-drill.
5. Operator checkpoint: four items + Gate A.

### 11b. Builder traps
1. Trigger on the lighting edge.
2. Calling `_run_decision_cycle`, or not skipping the enforcer/DPM under the filter.
3. Filter after `clear()`.
4. Absent set inside the filtered loop.
5. Back-fill missing or applied in legacy states.
6. Stamping from `_last_motion_time`, or only on rising edges.
7. Re-deriving camera/BLE.
8. Rescheduling a fired exit key.
9. Exemption keyed on `preset_mode`.
10. Waiting periodic running a second full cycle.
11. Shadow reading `ROOM_TYPE_HVAC_HOLD`, or removing the clamp.
12. Releasing after the first await.
13. `trigger` only in a counter.
14. Evidence branch writing shadow dicts.
15. `guest`/`arriving`/`home_night` in the evidence states.
16. `finally` placement.
17. Resetting the nudge-skip set to empty.
18. `if ev:` truthiness.
19. Relying on reschedule hooks.
20. Stamping on suppressed sources.
21. Refresh hold outside evidence states or unbounded.
22. Dwell applied to a room released within the exemption window.
23. `onset` from the lighting session or the debounce anchor.
24. Episode joining beyond `J`, or never lapsing.
25. Leaving the lighting-session skip in place.
26. Dwell in night or legacy states.
27. Arm re-check for warm zones, or not cancelled.
28. Changing knob 47's unit or unique_id.
29. **[REV 5]** Applying D5 when the zone's last write is not `away`, or to pre-arrival zones.
30. **[REV 5]** Letting a pending episode not block the vacancy away (`room_release_at` bounded, or `last_occupied_time`
    not held).
31. **[REV 5]** Re-adding a zone-level exemption, or reusing `HVAC_QUICK_RETURN_WINDOW_S` for the exemption.
32. **[REV 5]** Counting exempt re-arms in the trip-wire.
33. **[REV 5]** Arm re-check queuing directly instead of re-entering at step 5.
34. **[REV 5]** Stamping `_zone_vacancy_away_at` on non-vacancy aways.

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
For every drill: neuter the returned value or branch, bytecode disabled; restore and confirm `git status` is clean.

| # | Site | RED test |
|---|---|---|
| 1 | Evidence-state output returns `shadow_out` | `test_evidence_state_ignores_lighting_timeout` |
| 2 | Evidence branch writes `_hvac_armed = False` | `test_home_evening_to_sleep_mid_timeout_stays_held` |
| 3 | Night output drops the shadow | same + `test_night_release_never_before_shadow` |
| 4 | `home_night` in evidence states | `test_home_night_is_legacy_until_gate` |
| 5 | `active` term removed | `test_hold_zero_holds_while_active` |
| 6 | Refresh hold removed / unbounded / in night | `test_refresh_failure_hold_evidence_states_only_and_bounded` |
| 7 | Suppressed-source check removed | `test_no_stamp_on_fan_demoted_failsafe_recheck_sources` |
| 8 | Camera/BLE source term removed | `test_camera_ble_stamp_only_from_override_verdict` |
| 9 | Override-vacant exclusion removed | `test_override_vacant_blocks_stamp` |
| 10 | Falling-edge stamp removed | `test_falling_edge_refresh_stamps` |
| 11 | BLE cap neutered | `test_ble_cap_stops_stamp_after_cap` |
| 12 | `apply_fan_recheck_release` leaves active True | `test_fan_recheck_release_clears_active` |
| 13 | Back-fill removed | `test_last_occupied_time_backfilled_to_exact_release` + `test_exit_timer_fires_at_release_plus_grace` |
| 14 | Back-fill in legacy states | `test_no_backfill_in_legacy_states` |
| 15 | Filter after `clear()` | `test_fast_run_leaves_sibling_zones_untouched` |
| 16 | Loop-top `continue` removed | `test_s1_writes_only_origin_zone` |
| 17 | Absent set inside the loop | `test_absent_set_built_before_zone_loop` |
| 18 | Enforcer not skipped | `test_fast_run_is_zone_scoped` (enforcer) |
| 19 | DPM not skipped | `test_fast_run_is_zone_scoped` (DPM) |
| 20 | Listener on the lighting edge | `test_rearm_while_lighting_still_on_triggers_fast_entry` |
| 21 | Evidence-advance check removed | `test_listener_ignores_refresh_without_evidence_advance` |
| 22 | Zone-cold gate removed | `test_listener_skips_warm_zone` |
| 23 | Hallway skip removed | `test_listener_skips_hallway` |
| 24 | 60 s limiter removed | `test_entry_limiter_denies_second_run_within_60s` |
| 25 | Exemption keyed on `preset_mode` | `test_rearm_limiter_exempt_keyed_on_last_sent` |
| 26 | Registry-miss fallback removed | `test_limiter_exemption_order` |
| 27 | Stamp check order swapped / removed | `test_limiter_exemption_order` |
| 28 | Nudge-skip seed to `set()` | `test_fast_write_seeds_nudge_skip_on_next_tick` |
| 29 | Queue discard inside the lock | `test_queue_entry_cleared_on_every_exit_path` |
| 30 | `_fast_path_running` cleared outer | `test_fast_path_running_only_true_while_holding_lock` |
| 31 | Post-lock gate re-check removed | `test_gates_rechecked_after_lock_wait` |
| 32 | `_tearing_down` guard removed (per site) | `test_tearing_down_guards_every_callback` |
| 33 | Teardown after the first await | `test_teardown_releases_before_first_await` |
| 34 | One-shot key not recorded | `test_exit_timer_one_shot_under_feed_disagreement` |
| 35 | Exit timer reads cached evidence | `test_exit_timer_reads_live_evidence` |
| 36 | Scheduled grace used at fire | `test_exit_timer_uses_grace_at_fire_time` |
| 37 | Constrained-grace choice removed | 10/3 variant |
| 38 | Timer not cancelled on prune | `test_exit_timer_cancelled_on_zone_prune` |
| 39 | Waiting periodic doesn't skip | `test_waiting_periodic_skips_if_full_cycle_ran` |
| 40 | Ceiling never trips | `test_write_ceiling_trips_and_clears_at_local_midnight` |
| 41 | Runaway guard never trips | `test_runaway_guard_trips_at_31_runs` |
| 42 | Trip-wire never counts | `test_quick_return_counter_and_nm_latch` |
| 43 | `isinstance` -> truthiness | `test_accessor_fallback_uses_isinstance_datetime` + night-hold `:216-255` |
| 44 | Shadow selector reads `ROOM_TYPE_HVAC_HOLD` | `test_legacy_tail_is_frozen_v5_103_19` + `test_zzz:246-269` |
| 45 | Dwell check removed | `test_transit_under_60s_no_write` (+ Kitchen PIR variant) |
| 46 | Arm re-check not scheduled | `test_stay_60s_writes_within_sla` |
| 47 | Room exemption removed | `test_same_room_return_rearms_immediately` |
| 48 | [REV 5] Zone exemption re-added | `test_other_room_in_away_zone_waits_w` |
| 49 | Exemption window unbounded | `test_rearm_after_window_is_cold` |
| 50 | Episode never lapses | `test_episode_lapses_at_ev_plus_j_and_counts_filtered` |
| 51 | [REV 5] Join window uses `hold` instead of `min(hold, W)` | `test_gap_longer_than_join_window_starts_new_episode` |
| 52 | Dwell in night/legacy | `test_dwell_only_in_evidence_states` |
| 53 | Lighting-session skip left in place | `test_lighting_session_dwell_removed` (behavioural) |
| 54 | Exit run skips D5 | `test_exit_run_arms_persisted_room_before_away` |
| 55a | [REV 5] Arm re-check not cancelled on lapse | `test_arm_recheck_cancelled_on[lapse]` |
| 55b | [REV 5] … on arm | `test_arm_recheck_cancelled_on[arm]` |
| 55c | [REV 5] … on prune | `test_arm_recheck_cancelled_on[prune]` |
| 55d | [REV 5] … on unload | `test_arm_recheck_cancelled_on[unload]` |
| 55e | [REV 5] … on teardown | `test_arm_recheck_cancelled_on[teardown]` |
| 56 | Onset re-stamped every active tick | `test_evidence_onset_accessor` |
| 57 | `W == 0` branch removed | `test_dwell_zero_is_rev3_behaviour` |
| 58 | [REV 5] D5 applied regardless of away edge | `test_d5_only_on_away_edge` + `test_zone3_repro_no_away_when_kitchen_enters_during_grace` |
| 59 | [REV 5] Pending episode does not hold `last_occupied_time` / `room_release_at` bounded | `test_unarmed_episode_blocks_vacancy_away` |
| 60 | [REV 5] Pre-arrival not excluded | `test_pre_arrival_zone_bypasses_d5` |
| 61 | [REV 5] Unknown away edge treated as True | `test_away_edge_unknown_after_restart_fails_open` |
| 62 | [REV 5] Exemption not renewed | `test_exemption_renews_on_each_release` |
| 63 | [REV 5] Exempt re-arm counted in the trip-wire | `test_exempt_rearm_excluded_from_quick_return_count` |
| 64 | [REV 5] `_zone_vacancy_away_at` stamped on any away | `test_zone_vacancy_away_at_stamped_only_on_vacant_past_grace` |
| 65 | [REV 5] Arm re-check queues directly | `test_arm_recheck_reenters_at_step_5` + `test_arm_recheck_into_warm_zone_stops_at_gate` |
| 66 | [REV 5] Joined-transit classification wrong | `test_joined_transits_within_j_arm_and_are_classified` |

---

## 12. Sequencing and supersession
- B shipped; no wait gate.
- REV 4 fast-path plan: banner.
- `HVAC-ENTRY-DWELL-ROOM-CLOCK-1`: folded (release half in D1, arming half in D5); close as folded when D5 ships;
  SUPERSEDED banners on `PLANNING_hvac_entry_dwell_room_clock.md` and `PLANNING_hvac_entry_dwell_hvac_clock.md`.
- `HVAC-FAST-PATH-FAN-WARM-EDGES-1`: out; recommend a fan-only Tier-2 cycle next (operator to confirm).
- Others: `HVAC-HOLD-SIZING-ALL-ROOMS-1` -> D3/L9; placeholder readers unchanged; write-oracle: one-shot timer, L4
  excludes zone_1.
- **New card (orchestrator) [REV 5]:** Dining Room radar silent 24 h.
- **Supersession triage:** `current_session_start` DELETE after validation (W4); migration KEEP + DOCUMENT.
- D0b >= 3 days.

## 13. REV 4 fast-path findings disposition
| Item | Disposition |
|---|---|
| Whole-house off-schedule cycle | Never called |
| Wrong-zone reruns | Per-zone queue + lock wait |
| Enforcer/egress/fan/cover writes | Not called |
| Sibling-zone wake-ups | Filter before `clear()`; absent set; S1 origin-only |
| F1 | Replaced by the D5 arm re-check |
| F2 | Zone-scoped run |
| F3 | Moot |
| F4 | Kept |
| F5 | Lock rules + nudge seed |
| F6 | Kept |
| F7/F8 | Row fields |
| F9 | D0b |
| F10 | Write ceiling + runaway guard |
| F11 | Refreshed |
| F12/F13 | Kept |
| F14 | Kept (`sensor.ura_hvac_coordinator_mode`; `_status` does not exist) |
| F15 | Not called |
| Global limiter G | Dropped |

---

## 14. Knobs and labels

### 14.1 Knob ladder
| Number | Value | Rung | Why |
|---|---|---|---|
| `ROOM_TYPE_HVAC_HOLD` | 4.6; common 180 | 1 | Rulings R1/R2; trip-wire is the live check |
| `ROOM_TYPE_HVAC_TAIL_LEGACY` | frozen | 1 | Shadow |
| `HVAC_EVIDENCE_RULE_STATES` | (`home_day`, `home_evening`) | 1 | |
| `HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S` | 600 | 1 | 0 disables |
| `HVAC_FAST_PATH_MIN_INTERVAL_S` / `_SLA_S` / `_EXIT_SLACK_S` | 60 / 45 / 2 | 1 | |
| `HVAC_FAST_PATH_MAX_WRITES_PER_ZONE_PER_HOUR` / `_MAX_RUNS_...` | 6 / 30 | 1 | |
| `HVAC_QUICK_RETURN_WINDOW_S` | 900 | 1 | Trip-wire only (no longer shared with D5) [REV 5] |
| `HVAC_QUICK_RETURN_NM_PER_DAY` | 12 | 1 | Checkpoint |
| **`HVAC_TRANSIT_EXEMPT_WINDOW_S`** [REV 5] | 900 (placeholder) | 1 | Same-room return exemption; sized from D0c's release -> re-detection gaps. The knob 47 helper text must state its value in minutes (test) |
| Knob 47 | default 1 min; live 0 until set | 3 (existing) | R3; 0 = filter off |
| `HVAC_ARM_RECHECK_SLACK_S` | 1 | 1 | |
| Fast room response switch | ON | 3 | Rollback |
| Knob 48 / 49 | 5 / 5 | 3 | D3 |

### 14.2 Labels
Rules: short config-flow phrase, plain helper, entity names 3 words max. Banned: tail, HVAC-occupied, clamp, gate,
evidence, tick, fast path, debounce, CRIT, fused, rung, shadow, legacy, dwell, transit, arm, episode.

**Room options, climate step:**
- `hvac_vacancy_hold` label: `Empty-room hold (day)`
- `hvac_vacancy_hold` helper: `How many seconds heating and cooling keep treating this room as occupied during the day and evening. The time counts from the last sign of someone in the room, such as motion, presence, a camera or a phone. This covers people sitting still, and it is the only protection for someone who stays completely still. Leave blank to use the default for this room type: 1 minute for closets, 2 minutes for media, utility and general rooms and garages, 3 for bathrooms and living areas, and 4 for bedrooms. Enter 0 to hold only while a sensor still sees someone. From 9 pm until the house goes to sleep, this number is counted from when the room itself shows as empty.`
- `hvac_vacancy_hold_night` label: `Empty-room hold (night)`
- `hvac_vacancy_hold_night` helper: `The hold used while the house is asleep or waking up. It counts from when the room itself shows as empty, so sleepers who lie still get extra time. Leave blank to use the default for this room type: 30 minutes for bedrooms and media rooms, 15 for living areas, 10 for bathrooms, garages and utility rooms, and 5 for closets. Enter 0 for no extra time once the room shows as empty. This form rejects a night value below the day value.`
- Error `hvac_hold_night_below_day`: `The night hold must be at least as long as the day hold. Raise the night value, or leave one of them blank to use the room type's default.`
- Section `climate_backstop`: `Thermostat and empty-room hold`

**HVAC coordinator options:**
- `hvac_vacancy_grace_minutes` helper: `Minutes a zone waits after its last room empties before heating and cooling switch to Away. If someone comes back sooner, nothing changes. A shorter wait saves energy but switches a zone to Away more often while someone sits still.`
- `hvac_vacancy_grace_constrained` helper: `The same wait, used while the house is saving energy. It must be no longer than the normal delay. A shorter wait saves energy but switches a zone to Away more often while someone sits still.`
- `hvac_zone_entry_dwell` label: `Entry wait (minutes)`
- `hvac_zone_entry_dwell` helper [REV 5]: `How long someone must be in a room before heating and cooling switch a zone that is set to Away back to Home, during the day and evening. People passing through faster than this do not switch it. Someone coming back to a room within 15 minutes counts at once. Enter 0 to count any sign of someone at once. Recommended: 1.`
  - "15 minutes" = `HVAC_TRANSIT_EXEMPT_WINDOW_S / 60`. Update it with the constant (test
    `test_transit_helper_text_matches_constant`).

**Entities:**
- `47 · Entry Wait (min)` (unchanged).
- `31 · Fast Room Response` (`switch.ura_hvac_coordinator_31_fast_room_response`, unique_id
  `{DOMAIN}_hvac_fast_room_response`).

**Notifications:**
- Ceiling: `Fast room response paused for {zone}` / `{zone} changed its heating and cooling setting {n} times in the last hour. Fast response is off for this zone until midnight. The regular 5-minute check still runs.`
- Quick returns: `{zone} keeps switching to Away too soon` / `{zone} switched to Away and someone was back within 15 minutes {n} times today. The empty-room hold for a room in this zone may be too short.`
- Runaway: `Fast room response paused for {zone}` / `{zone} ran more checks than expected in the last hour. Fast response is off for this zone until midnight. The regular 5-minute check still runs.`

**Acceptance:** `strings.json` == `en.json`; banned-word check clean; JSON parses; hassfest passes.

---

## 15. Files
| File | Change |
|---|---|
| `const.py` | Hold tables |
| `coordinator.py` | Stamp, onset, three accessors |
| `hvac_zones.py` | Shadow + rule output; D5 (away edge, episodes with `J`, room exemption, pending); selectors; `zone_ids`; absent set; back-fill + pending hold; release helpers; attrs |
| `hvac.py` | Listeners + lifecycle; `_on_room_refresh(from_step)`; fast run; exit and arm timers; lock rules; nudge seed; `_apply_house_state_presets(zone_filter, …)`; remove `:2735-2748`; `_zone_away_edge`; `_zone_vacancy_away_at` (vacancy only); ceiling/guard/trip-wire + `same_room_returns_today`, `transit_filtered_today`; teardown; `get_mode_attrs` |
| `hvac_const.py` | Constants 14.1; `DEFAULT_ZONE_ENTRY_DWELL_MINUTES = 1`; `HVAC_TRANSIT_EXEMPT_WINDOW_S` |
| `binary_sensor.py` | Attrs |
| `switch.py` | Kill switch |
| `number.py` | Grace setters -> `reschedule_exit_timers()` |
| `strings.json` / `en.json` | 14.2 |
| `quality/tests/` | `test_hvac_evidence_clock.py`, `test_hvac_fast_occupancy_response.py`, `test_hvac_transit_filter.py`; updates per 11c |
| `scripts/probes/` | `--latency` + flap rate; gap probe `--states`, T 240, REV 5 W replay with separate counts and the exemption-sizing distribution; grace probe |
| Docs | State of play; banners (REV 4 fast-path plan, two dwell plans); README |

## 16. Non-goals
- No night hold or anchor change.
- No change in `home_night`/`guest`/`arriving`/`away`.
- Clamp and validation unchanged.
- No fan/cover/predictor/egress/arrester/DPM/D9 change.
- No tick, grace or knob-47 unit change.
- Hallway exclusion unchanged.
- No new table/writer/sensor/signal.
- No §9.4/§9.7 fix.
- No `current_session_start` removal this cycle.
- **No D5 on a zone that is Home or in grace. No zone-level return exemption** [REV 5].

## 17. Parked
- Night-anchor unification.
- `home_night` on the evidence rule (Gate B).
- A dwell for night/legacy states.
- **A zone-level return exemption** (revive if the D0c replay shows other-room returns within minutes of a wrong away
  are common) [REV 5].

## 18. Change logs

### REV 5
| Item | Change | Where |
|---|---|---|
| HIGH-1 | D5 only on the away -> home edge (last S1 write `away`, not pre-arrival); a live unpersisted episode always blocks a vacancy away (`last_occupied_time` held; `room_release_at` None); §4.5/INV-2 contradiction resolved; zone 3 repro test; drills 58-61 | 2, 3.1, 4.2, 4.5, 5.1-5.4, 5b.1, 6, 9 L14, 11d |
| HIGH-3 | Zone exemption dropped; room-only exemption with its own `HVAC_TRANSIT_EXEMPT_WINDOW_S` (900 placeholder, sized by D0c); `exempt_reason` rows excluded from the trip-wire, counted in `same_room_returns_today`; renewal + exclusion tests | 0.5, 5.7, 5b.3, 8, 14 |
| MEDIUM-2 | Join window `J = min(hold, W)`; Kitchen PIR joined-transit, exit-pulse and Hobeian 31 s cases in 7.1; D0c reports them separately; C1-D discriminator; Dining radar side-finding | 5b.2, 5b.6, 7.1, 8 |
| MEDIUM (re-check) | Re-check re-enters `_on_room_refresh` at step 5; kill switch / house-state exit handled by gates at fire | 5.4, 5b.4 |
| Tests | Behavioural `test_lighting_session_dwell_removed`; row 55 -> 55a-e; hallway test labelled a construction check; Kitchen PIR variant; unarmed-episode, joined-transit, renewal, `_zone_vacancy_away_at`, warm-zone re-check, pre-arrival tests | 5b.6, 11d |
| Label | Knob 47 helper: "Someone coming back to a room within 15 minutes counts at once."; tied to the constant by test | 14.2 |
| Checkpoint | Item 3 -> "room-only 15-minute return exemption" | header |

### REV 4
- D5 added.
- Knob 47 moved; default 1; lighting-session dwell retired.
- Hallway site confirmed.
- Latency updated.
- Card criteria C1-C4.
- Drills 45-57.
- Ruling R3.
- File made self-contained.

### REV 3
- Rulings R1/R2 (common 180; audit table; arithmetic as context).
- Quick-return threshold 12.
- Kitchen pending confirmation.
- N1 selectors; N2 lock flag; N3 scoped refresh hold; N4 fire-time grace; N5 override verdict; N6 drill table.
- LOW-1 exemption order; LOW-2 no legacy back-fill.

### REV 2
- Shadow machine.
- Evidence rule in `home_day`/`home_evening` only.
- `active` term.
- Nudge seed.
- Sweep.
- Outer `finally` + post-lock re-check.
- Periodic-equivalence invariants.
- Test table.
- Stamp gating.
- Exit-timer fixes.
- Misc.

## 19. Departures and notes
1. `guest`/`arriving` legacy (the audit excluded them).
2. Four existing tests go RED (11c).
3. Clamp and validation kept.
4. Sweep timing accepted.
5. N5 camera/BLE-after-timeout cost (eight rooms); the room exemption makes those re-arms immediate.
6. Quick-return threshold 12 (checkpoint).
7. ~13 MID retreats at common 180: operator-accepted context.
8. The REV 4 recent-return exemption is now room-only (REV 5 HIGH-3). The brief's "within its hold" is still
   insufficient on its own, for the reason in 5b.3.
9. Knob 47 keeps minutes.
10. The retired lighting-session dwell also covered `home_night`/`guest`/`waking` (behaviour-neutral at live 0).
11. **[REV 5] Disagreement, followed but flagged: excluding exempt re-arms from the trip-wire.** A same-room return
    after a release is the most direct symptom of a hold that is too short, which is exactly what the trip-wire exists
    to measure for rulings R1/R2. Excluding those rows leaves the NM measuring mostly other-room returns, which are
    more often real departures. I followed the review, but kept the signal in `same_room_returns_today` (surfaced, no
    NM). **Recommendation for the checkpoint:** either put the NM on `same_room_returns_today` or on the sum.
12. **[REV 5]** `away_edge` fails open (False, so immediate arming) after a restart until the first S1 write: at most
    one unfiltered transit per zone per restart. The alternative, fail-closed, could delay a real arrival into a Home
    zone by 60 s.

## Orchestrator decision on §19 #11 (2026-09-27, REV 5)
The planner is right: with the ZONE exemption dropped, a SAME-ROOM return shortly after a release is exactly the "hold too short" signal the quick-return alarm exists to measure (operator rulings R1/R2). The review's #63 concern applied to the zone-exemption transit flaps, which no longer exist. Decision: the quick-return alarm counts the SUM of zone quick-returns and `same_room_returns_today`; the `exempt_reason` tag stays for attribution. The threshold (12/zone/day) is re-confirmed at the operator checkpoint with this counting rule.
