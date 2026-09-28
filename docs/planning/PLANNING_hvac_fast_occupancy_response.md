# PLANNING: HVAC fast occupancy response (own release clock + event-driven entry and exit) — REV 2

**Cards:** `HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1` (revived) + the parked W2 fast path
(`HVAC-W2-OCCUPANCY-TRUTH`, plan `PLANNING_hvac_w2_occupancy_fast_path.md` REV 4). Workstream `HVAC-W2-OCCUPANCY-TRUTH`.
**Status:** REV 2. REV 1 went through two Tier-3 plan reviews (R1 completeness, R2 build-prediction); both returned
FIX-PLAN. REV 2 folds every finding; each change is tagged `[REV 2 #n]` (n = the coordinator's finding number).
The change log is in section 18. A REV 2 re-review is still required before build.
**Base:** `develop` after v5.103.19 (night-tail B merged and shipped). `hvac_zones.py` lines refreshed (+1 to +3);
`hvac.py` lines unchanged (re-verified).

**Operator decision (2026-09-27 ~22:00, verbatim):**
- "We wanted faster responses. This is nuts."
- On the still-person risk: "fast path catches it. The room type hold blunts it. Do it"

**Design premise (operator), with its limit stated plainly [REV 2 #2]:**
1. A per-room-type hold blunts radar misses of still people. **This is the ONLY protection for a person who stays
   still.** A still person produces no new evidence, so the fast path cannot "catch" them. It can only react once
   they move again.
2. An event-driven fast path re-arms a room the moment it is re-detected, so a wrongly released room recovers in
   seconds instead of waiting for the next 5-minute tick.

| Deliverable | What | Code? |
|---|---|---|
| D0 | Baselines, residual re-probe, home_night gate probe (read-only) | probe only |
| D1 | HVAC's own release clock in measured day states; today's machine kept as a shadow; night unchanged | yes |
| D2 | Event-driven zone decision on entry AND exit | yes |
| D3 | Vacancy grace re-check (measure, knob only) | no |
| D4 | Operator config step: clear Jaya Bedroom's day hold override | config |

---

## 0. Institutional context verified

### 0.1 Mandatory read
- **`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` re-read for REV 2 [REV 2 preamble].** Header now records
  v5.103.19: D8 night tail-holds follow `HVAC_NIGHT_HOLD_STATES` (`sleep`, `waking`; `hvac_const.py:934`);
  `home_night` uses the DAY table; `FAN_TRUST_STATES` unchanged (§3.1, §3.3). W1-B is SHIPPED (v5.103.18, §9e four
  gates). Relevant: §2 (triggers; no occupancy trigger), §3.1-§3.3, §9c (override switches ride the hold), §9d,
  §9.4 (placeholder readers), §9.7 (zone_1 away re-issue loop), §10 C1-C25.
- **C18:** with dwell 0 (live), entry = wait for the next tick. **C24:** HVAC occupancy today is NOT a faster clock.
  This plan builds that clock; it does not claim it exists.
- **§10 check.** No C1-C25 claim is re-asserted (no 1-minute tick C8; suppression 15 s temp / 120 s preset C17/C23;
  S1 manual guard superseded by §9e C25).
- **State-of-play drift still open (fix in the build commit):** §3.2 says knob 48 = 10 live and §8 says dwell = 2.
  Live `.storage/core.config_entries` (2026-09-27): `hvac_vacancy_grace_minutes: 5`,
  `hvac_vacancy_grace_constrained: 5.0`, `hvac_zone_entry_dwell: 0`. §3.1 still cites pre-B line numbers
  (`_effective_hvac_hold_seconds` is now `hvac_zones.py:977`).

### 0.2 Other docs and cards read
| Source | Use |
|---|---|
| Card `HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1` (groom disposition + `revived_2026_09_27`) | Measured disposition; per-type safe tails; `_last_motion_time` misses camera/BLE; Kitchen timeout stopgap 600 -> 300 s (verified live). |
| `docs/planning/AUDIT_hvac_raw_evidence_gaps_2026_09_26.md` | Per-type table; MID/LATE counts; T + G coupling. **Its "day" bucket is `home_day` + `home_evening` only (82.4 h). `away`, `arriving` and `guest` were excluded (§8.6). Its night bucket lumps `home_night` with `sleep`/`waking` (§3 footnote), so `home_night` alone was never measured** [REV 2 #2]. |
| `docs/planning/PLANNING_hvac_w2_occupancy_fast_path.md` REV 4 (PARKED) + card `HVAC-W2-OCCUPANCY-TRUTH` | Design reused; section 13 dispositions F1-F15 and the four REV 4 re-review HIGHs (summary only on the card; full text not on disk). |
| `docs/planning/AUDIT_hvac_fast_path_rate_2026_09_26.md` | 16.6 zone-cold edges/day; cycle proxy p95 27.6 s; L=60 denies 0/114. |
| `docs/planning/PLANNING_hvac_night_tail_follows_sleep.md` (B shipped v5.103.19) | `HVAC_NIGHT_HOLD_STATES` reused. The "wait for B" gate is dropped [REV 2 preamble]. |
| Card `HVAC-ENTRY-DWELL-ROOM-CLOCK-1` (Stage B) | Supersession verdict in section 12. |
| Cards `HVAC-FAST-PATH-FAN-WARM-EDGES-1`, `HVAC-HOLD-SIZING-ALL-ROOMS-1`, `HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1`, `HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1`, `HVAC-WRITE-CONFIRMATION-ORACLE-1` | Section 12 (fan card: explicit decision) [REV 2 #11]. |
| vibememo entry 153 | Why the fast path was parked. |

### 0.3 Code surveyed (develop, post v5.103.19)
- `coordinator.py`: occupancy block `:3538-3643` (`_last_motion_time = now` only on Tier-1 activity `:3589`); camera
  override `:3663-3697` (seeds only if unset `:3679-3680`); BLE chain-hold `:3699-3908` (seed only if unset
  `:3866-3867`; cap `:3810-3847`); mmWave fan demotion source `OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED` `:4113`; failsafe
  source `"failsafe"` `:4361`, `_failsafe_fired = True` `:4369`; override switches `:4790-4811`; skip-first
  `:4825-4851`; `apply_fan_recheck_release` `:5249-5280` (sets `OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE` outside a
  refresh); poll 30 s + 0-5 s jitter `:625-631`; event refresh within 2 s `:1395-1411`, `:1616-1630`; accessor
  pattern `get_became_occupied_time` `:5384`.
- `domain_coordinators/hvac_zones.py` (post-B): `update_room_conditions` `:566`; entry loop `:611-647`;
  `_classify_all_rooms` call `:665`; zone loop `:666`, `room_conditions.clear()` `:667`; coordinator-absent add `:687`;
  `room_occupied` `:718`; hallway exclusion `:725-736`; rollup writes `:772-789`; `get_zone_status_attrs` `:791`;
  `_effective_hvac_hold_seconds` `:977-1049` (import `HVAC_NIGHT_HOLD_STATES` `:1005`, clamp `:1031-1047`, selector
  `:1049`); `_compute_hvac_occupied` `:1051-1126`; `conditioning_retreat_ok` `:1525`; `hvac_occupied_diag` `:1588`.
- `domain_coordinators/hvac.py` (unchanged by B): `_zones_written_this_cycle` init `:455`, reset `:1879`, add `:3194`,
  read by the arrester `hvac_override.py:4713`; `_async_decision_cycle` `:1583-1617`; `_track_task` `:1644`;
  `_run_decision_cycle` `:1873-2076`; `_apply_house_state_presets` `:2132-3320` (consensus gate `:2156-2197`,
  heat_cool enforcer `:2227-2256`, arriving `:2261`, zone loop `:2282`, row-1 + vacancy sweep `:2339-2426`, D6
  `:2437-2539`, D5 `:2568-2733`, dwell `:2738-2748`, D7 `:2780-2852`, transient hold `:2860-2911`, W1-B gates
  `:2918-2996`, S1 write `:3125-3271`, DPM `:3319-3320`); `_handle_energy_constraint` `:3843`;
  `_handle_zm_zones_updated` `:3908` (zone pops `:3987`, `:4010`); `_execute_vacancy_sweep` `:4266`;
  `_handle_person_arriving` `:4567`; `_expire_pre_arrival_zones` `:4624-4654`; `_compute_zone_presence_states`
  `:4775`; `get_mode_attrs` `:5411`; `async_teardown` `:5555`.
- `hvac_strategy.py`: per-platform cached strategy `strategy_for` `:254-266` (registry miss -> uncached generic);
  `last_sent` `:142`; `hold_preset` no-op needs `last_sent == preset` AND observed preset == preset `:187-197`, and a
  divergent observation clears `last_sent` `:195-197`.
- `hvac_override.py:174` `SUPPRESS_TTL_SECONDS_PRESET = 120`.
- `sensor.py:13684-13745` `HVACZoneIntelligenceSensor` (`sensor.ura_hvac_coordinator_zone_intelligence`) reads
  `zone_presence_state` [REV 2 #11].
- HA `helpers/update_coordinator.py` (`.venv-ha`): `async_add_listener` `:170-182`; listeners called after every
  successful refresh when `always_update` (default True `:84`; `:528-533`).
- Live config: only Jaya Bedroom has a day override (60, night 5400); 9 common rooms night 90; timeouts 300 s for
  most rooms, up to 900 s (Master Bathroom, Jaya Bathroom, Exercise Room); `switch.kitchen_override_vacant` restores
  `off`.
- Tests read for REV 2: `test_hvac_night_hold_follows_sleep.py` (whole file), `test_hvac_vacancy_hold_ui_defaults.py:140-171`.

### 0.4 Config-first check
| Candidate setting | Solves it? | Why |
|---|---|---|
| Room `occupancy_timeout` | Partly (used as the Kitchen stopgap) | Shortens lighting too; release still waits for two tick quantizations; no effect on entry or re-arm |
| Per-room `hvac_vacancy_hold` / `_night` | No | Today the hold starts only after the lighting timeout |
| Knob 48 grace (live 5) | No | Lowering further re-introduces MID risk (section 7) |
| Dwell (live 0) | Already 0 | Remaining entry wait is the tick itself |
| Shorter `HVAC_DECISION_TICK` | Rejected | Rung-1 Carrier call-rate bound; whole-house cycle = the REV 4 leak |
| Jaya Bedroom day override 60 | **Must change (D4)** | Under the new clock 60 s counts from the last evidence; audit Jaya Bedroom MID ZR at 60 = 2 / 6.74 d, at 240 = 0 |

### 0.5 Prior-art scan: REUSE or BUILD per piece
| Piece | Verdict | Existing symbol / justification |
|---|---|---|
| Evidence-rule hold table | **REUSE, change values** | `ROOM_TYPE_HVAC_HOLD` `const.py:1219-1224` (rung 1) — per the task |
| Shadow machine's day tail (today's v5.103.19 values) | **BUILD (frozen copy)** [REV 2 #1] | Changing `ROOM_TYPE_HVAC_HOLD` would change today's machine. `ROOM_TYPE_HVAC_TAIL_LEGACY` keeps bedroom 60, media 120, common 60, hallway 0 so the shadow stays byte-for-byte |
| Night table, per-room overrides, numeric night>=day clamp, flow validation | **REUSE unchanged** [REV 2 #1] | `const.py:1230-1241`, `:1252-1253`; clamp `hvac_zones.py:1031-1047`; `config_flow.py:599-610`. With the shadow reading the legacy tail the clamp no longer lifts the 9 common rooms' night 90 (90 >= 60), so REV 1's clamp/validation removal is withdrawn |
| Night-state tuple | **REUSE** | `HVAC_NIGHT_HOLD_STATES` `hvac_const.py:934` |
| Evidence-rule state tuple | **BUILD (constant)** [REV 2 #2] | `HVAC_EVIDENCE_RULE_STATES = ("home_day", "home_evening")`; no existing tuple of the audit-measured states |
| Last-evidence timestamp + "active now" | **BUILD (fields + 2 accessors)** | No existing field is correct (see REV 1 reasoning: `_last_motion_time` `:3589` misses camera/BLE; `_last_trigger_time` rising edges only; `_last_occupied_time` includes the timeout). Accessors follow `get_became_occupied_time` `:5384` |
| Camera / BLE evidence reads | **REUSE by extraction** | `_camera_person_sensor_on()` from `:3667-3697`; `_ble_cap_exceeded(now)` from `:3811-3837` |
| Room-change event source | **REUSE HA API** | `DataUpdateCoordinator.async_add_listener`; pattern `aggregation.py:1990`. Lighting binary sensor edge rejected (cannot see a re-arm while the light is on) |
| Listener lifecycle | **REUSE** | ONE `SIGNAL_ROOM_ENTRY_LIFECYCLE` subscription (`signals.py:199`), subscribe-then-enumerate [REV 2 #11] |
| Zone-scoped decision | **REUSE + parameterise** | `_apply_house_state_presets(zone_filter, trigger, edge_ts)`, `update_room_conditions(zone_ids)` |
| Same-tick nudge skip | **REUSE + extend** [REV 2 #4] | `_zones_written_this_cycle` (`hvac.py:455/1879/3194`, read `hvac_override.py:4713`), seeded from a new per-zone S1 write stamp |
| Limiter exemption key | **REUSE** [REV 2 #7] | `strategy_for(...).last_sent(entity, "set_preset_mode")` (`hvac_strategy.py:142`); fallback to the new S1 write stamp on a registry miss |
| Decision lock, task tracking, timers, NM, ledger row, mode-sensor attrs, zone-status attrs, per-room diag attrs, probes | **REUSE** | As REV 1 (`hvac.py:579`, `:1644`, `async_call_later`, `_note_s1_reclaim` NM path, `preset_change` details `:3232-3269`, `get_mode_attrs` `:5411`, `get_zone_status_attrs` `:791`, `hvac_occupied_diag` `:1588`, probes in `scripts/probes/`) |
| Kill switch | **BUILD (one switch)** | Pattern `HVACPreArrivalSwitch` `switch.py:4229` |

Memory bodies consulted: `feedback_suppression_needs_discharge`, `feedback_wire_in_anchor_mandatory`,
`feedback_hollow_test_anchors`, `feedback_marginal_benefit_pushback`, `feedback_measure_before_build`,
`feedback_coincidental_equality_masks_concept_split`, `feedback_unrestored_mutation_drill_poisons_evidence`,
`feedback_mutation_verification_pycache_staleness`, `project_zone_away_when_occupied_home_night_gap`.

---

## 1. Marginal-benefit note (recorded; operator has decided)

The audit said shortening common/bedroom holds "buys too little to justify a CRIT-1 revisit", weighing release speed
alone. The operator added a second lever: event-driven re-arm cuts the cost of a wrong release to two writes and
seconds of away, **provided the person moves again**. For a person who stays still, the hold is the whole defence
[REV 2 #2]. REV 2 narrows the new rule to the two house states the audit measured, keeps today's machine running
underneath, and leaves `home_night` on today's rule until measured.

---

## 2. Falsifiable invariants [REV 2 #7: restated]

Definitions. `ev(R)` = room R's last evidence time; `active(R)` = R has evidence at its latest refresh (section 4.1).
`hold_ev(R)` = per-room day override if set, else `ROOM_TYPE_HVAC_HOLD`. **Rule by house state:**
evidence states `HVAC_EVIDENCE_RULE_STATES` = (`home_day`, `home_evening`); night states `HVAC_NIGHT_HOLD_STATES`
= (`sleep`, `waking`); every other state (`home_night` until D0c passes, `guest`, `arriving`, `away`, `None`) is
legacy. `release(R)` = `ev(R) + hold_ev(R)` in evidence states; in night states the later of the shadow's tail end
and `ev + hold_ev`; in legacy states the shadow's tail end. `E(Z)` = max `release(R)` over live non-hallway rooms.
`P(Z, t)` = what a periodic cycle would write for zone Z at wallclock `t` given the same producer state and the same
`runtime_exceeded` (possibly nothing).

**INV-1 (re-arm = periodic outcome, within the SLA).** When a live non-hallway room of zone Z has an evidence advance
at refresh time `t_r` while Z's stored fused value is False, a zone-scoped fast run for Z starts by
`t_r + HVAC_FAST_PATH_SLA_S` (45 s) and issues exactly `P(Z, t_run)` for Z and nothing for any other zone.
In the case "Z was written away by a `vacant_past_grace` write and the house target is home/sleep", `P` is a
home/sleep write UNLESS one of the listed exceptions holds.

**INV-1 exception list (each is either "the periodic run would also not write" or "falls back to the tick"):**
| Exception | Outcome | Named where |
|---|---|---|
| Dwell > 0 (live 0) | dwell skip (`hvac.py:2738-2748`); write at the first tick after dwell | `preset_change` absent; documented on the dwell knob |
| Row-1 transient-room hold (`hvac.py:2360-2392`) | no write, `preset_change_suppressed transient_room_hold` | existing row |
| D5 shed force-away / D6 stale failsafe | effective away (no home write) | existing reasons |
| W1-B gates (a/b), (c), (d), (e) for a `manual` zone | deferral, `preset_change_deferred` with gate | existing row |
| Consensus defer gate (`hvac.py:2156-2197`) | whole call skipped | existing counter |
| `arriving`, egress pause, observation mode, zone intelligence off | no write | existing guards |
| D7 night trust (night only) | suppression row | existing row |
| §9.7 status feed already reads the target AND `last_sent` equals it | `SKIPPED_ALREADY_CORRECT`, zero calls | strategy no-op |
| Kill switch off, zone tripped (ceiling/runaway), boot-settle, teardown | no fast run; periodic tick backstop (<= 300 s) | counters |

**INV-2 (no early vacancy away, evidence states).** In an evidence state, S1 never issues a `vacant_past_grace` away
for Z at time `t` while any live non-hallway room R of Z has `active(R)` or `release(R) > t - G`. Any reachable path
(fast or periodic) that does so falsifies it.

**INV-3 (exit = periodic outcome at the due time, once).** When no new evidence arrives, a `fast_exit` run for Z starts
in `[E(Z) + G + SLACK, E(Z) + G + SLACK + SLA]` and issues exactly `P(Z, t_run)`. It starts at most once per vacancy
episode (key `(Z, E(Z))`); if that run is deferred by gate (e) (live borrow) or any row above, the key is consumed and
the periodic tick owns the rest of the episode.

**INV-4 (zone scope) [REV 2 #5: corrected].** A fast run for Z issues climate writes only for Z and only through S1.
Its only other actuation is **the vacancy sweep for Z** (`_execute_vacancy_sweep`, lights/fans of Z's rooms, inside
Z's row-1 branch). Its only house-wide effects are (a) a display-only `zone_presence_state` refresh for all zones and
(b) `_expire_pre_arrival_zones`, which may clear other zones' pre-arrival flags and schedule
`_deactivate_zone_fans` for timed-out pre-arrival zones — accepted, because it is time-driven and the next tick would
do the same [REV 2 #11]. It never calls the heat_cool enforcer, egress tick, `check_ac_reset`, fans, covers, predictor,
anomaly observations, DPM overrides, arrester sweeps or the Carrier freshness check, and never changes
`room_conditions`, `last_occupied_time`, `continuous_occupied_since` or `current_session_start` of another zone.

**INV-5 (shadow and night) [REV 2 #1].** On every producer pass, in every house state, today's machine runs
byte-for-byte on `data["occupied"]` and alone owns `_hvac_armed`, `_hvac_prev_state_occupied` and `_hvac_tail_until`.
In night and legacy states the room's output is at least the shadow's output. Consequently a room that crosses from
an evidence state into `sleep` mid-lighting-timeout is still held by the shadow (armed, riding `occupied`) and then by
its night tail.

**Equivalence (for reviewer B).** `fast run for Z at t` == `P(Z, t)` for Z's writes, over seeds that include cases
where S1 actually writes (home, away, sleep, manual write-through) [REV 2 #8].

---

## 3. Producer and consumer map for `hvac_occupied`

### 3.1 Producer
| Step | Today | After |
|---|---|---|
| Shadow (every state) | — | Today's machine (`hvac_zones.py:1051-1126`), unchanged, on `data["occupied"]`, tail from `_shadow_tail_seconds` (night table in night states, `ROOM_TYPE_HVAC_TAIL_LEGACY` otherwise, same overrides and clamp) |
| Evidence-state output | shadow | `active(R) OR now < ev(R) + hold_ev(R)` |
| Night-state output | shadow | `shadow OR active(R) OR now < ev(R) + hold_ev(R)` |
| Legacy-state output | shadow | shadow (byte-identical to v5.103.19) |
| Room refresh failing (`last_update_success is False`) [REV 2 #3] | shadow on stale data | hold the previous output; bounded by the D6 stale failsafe |
| Pass cadence | tick + house-state/pre-arrival | same + zone-scoped fast runs |
| Rollup | OR; `last_occupied_time = now` while fused | same + back-fill `last_occupied_time = max(lot, E(Z))` when fused False |

### 3.2 Consumers
| Consumer | Site | Kind | Effect |
|---|---|---|---|
| Zone rollup `any_room_hvac_occupied` | `hvac_zones.py:178` | feeds below | Flips sooner in evidence states; re-arms on evidence |
| `conditioning_retreat_ok` -> row-1 vacancy away | `hvac_zones.py:1525`; `hvac.py:2339-2426` | TRUST | INV-2/INV-3 |
| **Vacancy sweep** (lighting actuator, inside row-1) [REV 2 #5] | `hvac.py:2416-2426` -> `_execute_vacancy_sweep` `:4266` | ACTUATION (lights/fans of the zone) | Runs for Z inside fast runs; see 5.9 |
| Row-1 transient hold | `hvac.py:2360-2392`, `:2860-2911` | TRUST | unchanged logic |
| D6 stale failsafe | `hvac.py:2437-2539` | TRUST | fires less (shorter continuous spans) |
| D5 coast defer | `hvac.py:2643-2709` | TRUST | ends sooner when a zone empties |
| D7 night trust | `hvac.py:2780-2852` | TRUST | night output >= today (INV-5) |
| D9 compose-away (dormant) | `hvac.py:3484-3518` | TRUST | tick only |
| Arrester row-10 comfort delay | `hvac_override.py:2513-2557` | TRUST | grant in an emptied zone expires sooner |
| Pre-cool F8 / pre-heat F9 | `hvac_predict.py:583`, `:1420` | TRUST | tick only |
| `last_occupied_time` / grace | `hvac_zones.py:772-780`; `hvac.py:2340-2344` | TRUST | back-fill to exact release |
| `zone_presence_state` | `hvac.py:4775-4820` | DISPLAY | refreshed by fast runs |
| **`sensor.ura_hvac_coordinator_zone_intelligence`** [REV 2 #11] | `sensor.py:13684-13745` (counts `zone_presence_state == "away"`, lists occupied/away/pre-arrival zones) | DISPLAY | updates at fast-run cadence |
| W1-B four gates | `hvac.py:2918-2996` | TRUST (S1 intent) | same S1 body |
| Arrester same-tick nudge skip | `hvac_override.py:4713` reads `_zones_written_this_cycle` | TRUST | seeded from recent S1 writes [REV 2 #4] |
| Fans | `hvac_fans.py:761`, `:997` (LIGHTING `.occupied`) | — | unaffected |
| Pre-arrival | `hvac.py:4567-4654` | — | full cycle waits behind a fast run; expiry runs in fast runs [REV 2 #11] |
| Presence D6 source 4 | `presence.py:2147-2159` (LIGHTING) | — | unaffected |
| Per-room `binary_sensor.<room>_<room>_hvac_occupied` | `binary_sensor.py:745-920` | DISPLAY | attrs `rule`, `last_evidence_at`, `release_at`; `hvac_vacancy_hold_s` rule (4.6) [REV 2 #11] |
| Zone status sensor | `hvac_zones.py:791-895` | DISPLAY | `hvac_empty_since`, `away_due_at` |
| `sensor.ura_hvac_coordinator_mode` | `hvac.py:5411` | DISPLAY | fast-path counters |
| `optimization.py:2398-2430` | `continuous_occupied_since` | analysis | shorter spans |

---

## 4. D1: HVAC's own release clock

### 4.1 Evidence stamp (`coordinator.py`)
- Fields: `_last_hvac_evidence_time: datetime | None = None`; `_hvac_evidence_active: bool = False`.
- Accessors next to `get_became_occupied_time` (`:5384`): `get_last_hvac_evidence_time() -> datetime | None`,
  `is_hvac_evidence_active() -> bool` [REV 2 #3].
- Extract `_camera_person_sensor_on() -> str | None` (from `:3667-3697`) and `_ble_cap_exceeded(now) -> bool` (from
  `:3811-3837`, pure; NM stays in the block).
- **One stamp site**, after the override-switch block (after `:4811`, before skip-first `:4825`):
  ```
  source = data.get(STATE_OCCUPANCY_SOURCE)
  suppressed = source in (OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED, "failsafe",
                          OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE)        # [REV 2 #9]
  evidence_now = (not suppressed) and (not self._is_override_vacant()) and (
      any_sensor_active                                                 # post all fusion filters
      or (grace_hold and self._last_occupied_state)
      or (not self._failsafe_fired and self._camera_person_sensor_on() is not None)
      or (not self._failsafe_fired                                      # [REV 2 #9]
          and BLE_CHAIN_HOLD_ENABLED and ble_persons_present
          and self._last_occupied_state and not self._ble_cap_exceeded(now))
      or self._is_override_occupied()
  )
  if evidence_now or (self._hvac_evidence_active and not suppressed):   # falling-edge stamp
      self._last_hvac_evidence_time = now
  self._hvac_evidence_active = evidence_now
  ```
  On a suppressed tick there is no stamp and no falling-edge stamp, so a fan-induced or stuck signal cannot extend
  the hold [REV 2 #9].
- `apply_fan_recheck_release` (`:5249`, runs outside a refresh) sets `_hvac_evidence_active = False` and does not
  stamp [REV 2 #9].
- BLE counts only while the chain is unbroken and the cap has not fired: extend-not-create holds; BLE can never arm a
  cold room. Override Vacant: no evidence; the room releases at last evidence + hold (§9c updated in the build).
- In memory only; `None` until the first evidence after a restart (same as `_last_motion_time` today).

### 4.2 Producer: shadow plus rule output (`hvac_zones.py`) [REV 2 #1, #2, #3]
- `_compute_hvac_occupied` keeps its body as the **shadow** and gains `last_evidence`, `evidence_active`,
  `refresh_ok` keywords. Order inside:
  1. Run the shadow exactly as today (lines `:1073-1126`), with `hold_s` from `_shadow_tail_seconds` (today's
     `_effective_hvac_hold_seconds` logic, reading `ROOM_TYPE_HVAC_TAIL_LEGACY` for the day value). Store its result as
     `shadow_out`. Only the shadow writes `_hvac_armed`, `_hvac_prev_state_occupied`, `_hvac_tail_until`,
     `_hvac_arm_source`.
  2. If `refresh_ok is False`: return `self._hvac_output.get(room, shadow_out)` (hold previous output).
  3. `ev_out = evidence_active or (last_evidence is not None and now < last_evidence + hold_ev)`; store
     `_hvac_day_release_at[room] = last_evidence + hold_ev` (or pop when `last_evidence` is None). The evidence branch
     NEVER writes the shadow's dicts.
  4. Output: evidence state -> `ev_out`; night state -> `shadow_out or ev_out`; legacy -> `shadow_out`. Store in
     `_hvac_output[room]` and `_hvac_rule[room]`.
- `update_room_conditions` reads `last_evidence` with `isinstance(ev, datetime)` (anything else, including a MagicMock,
  = `None`) and `evidence_active` with `is True` [REV 2 #8]; `refresh_ok = coordinator.last_update_success is not False`.
  A legacy-only fake coordinator therefore produces `ev = None` and the shadow decides in night/legacy states.
- **Hold 0 and holds shorter than the poll [REV 2 #3].** With `active OR now < ev + hold`, a hold of 0 still keeps the
  room occupied while a sensor is on at the latest refresh, and a hold under ~35 s cannot drop a room between two
  polls of a continuously-on sensor (each poll re-stamps).
- Hallway exclusion unchanged (`:725-736`). Per-room day override wins in evidence states (as `hold_ev`) and in the
  shadow's non-night tail (as today).

### 4.3 Night and legacy states
- **`sleep`/`waking`:** shadow OR evidence rule. Never shorter than today (INV-5).
- **`home_night` [REV 2 #2]:** legacy (shadow only; the v5.103.19 day tail 60/60/120 after the lighting fall) until
  D0c measures `home_night` on its own. **Gate:** `home_night` MID zone retreats at the new table (G = 300) = 0 ->
  add `home_night` to `HVAC_EVIDENCE_RULE_STATES` in a reviewed follow-up; otherwise it stays legacy.
- **`guest`, `arriving`, `away` [REV 2 #2, disagreement recorded in section 19]:** legacy. The audit excluded them
  (§8.6). `arriving` makes S1 return early anyway; `away` targets away regardless of occupancy; `guest` is unmeasured.

### 4.4 Clamp and validation: unchanged [REV 2 #1]
The shadow reads the legacy tail, so the numeric night >= day clamp (`hvac_zones.py:1031-1047`) compares night with the
legacy day value exactly as today (common night 90 >= legacy 60: no clamp, no warning). The config-flow validation
`hvac_hold_night_below_day` stays. Monotonicity against the new evidence hold comes from the night OR. REV 1's removal
of both is withdrawn.

### 4.5 Exact release instant for the grace
On a pass where Z is fused-empty: `zone.last_occupied_time = max(lot, E(Z))`, `E(Z)` over rooms whose `release <= now`.
Helpers (pure, sync): `room_release_at(room)` reads the LIVE `coordinator.get_last_hvac_evidence_time()` and
`is_hvac_evidence_active()` (not the last pass) [REV 2 #10]; returns `None` if `active` (unbounded), or the shadow is
riding `occupied` in a night/legacy state. `zone_release_at(Z)` = max, `None` if any room is `None`.
`zone_away_due_at(Z, grace_s) = zone_release_at + grace_s`.

### 4.6 Tables (`const.py`, rung 1)
```
ROOM_TYPE_HVAC_HOLD: Final = {          # evidence rule (home_day, home_evening; night OR)
    ROOM_TYPE_CLOSET: 60, ROOM_TYPE_INFRASTRUCTURE: 60,
    ROOM_TYPE_GENERIC: 120, ROOM_TYPE_UTILITY: 120, ROOM_TYPE_MEDIA_ROOM: 120, ROOM_TYPE_GARAGE: 120,
    ROOM_TYPE_BATHROOM: 180, ROOM_TYPE_BEDROOM: 240, ROOM_TYPE_COMMON_AREA: 300,
    ROOM_TYPE_HALLWAY: 0,
}
ROOM_TYPE_HVAC_TAIL_LEGACY: Final = {   # FROZEN v5.103.19 day tail, used only by the shadow
    ROOM_TYPE_BEDROOM: 60, ROOM_TYPE_MEDIA_ROOM: 120, ROOM_TYPE_COMMON_AREA: 60, ROOM_TYPE_HALLWAY: 0,
}
```
Comment on `ROOM_TYPE_HVAC_HOLD`: each type's hold plus the vacancy grace (and the energy-saving grace, knob 49) must
stay at or above that type's measured max MID gap (common 603 s, bedroom 495 s, generic 396 s, utility 386 s).
`DEFAULT_HVAC_VACANCY_HOLD` (60) stays the fallback for both tables.

**Display rule for `hvac_vacancy_hold_s` (`binary_sensor.py:894`) [REV 2 #11]:** shows the hold of the active rule:
`hold_ev` in evidence states, the night value in night states, the legacy tail in legacy states. `release_at` shows
the effective release (the max in night states). `rule` ∈ {`evidence`, `night`, `legacy`}.

### D1 acceptance
- **Test (anchor):** `test_evidence_state_ignores_lighting_timeout` — `occupied=True`, evidence older than the hold,
  `home_day` -> output False, shadow still armed. Mutation: return `shadow_out` in evidence states -> RED.
- **Test (INV-5, the Jaya/Ziri repro) [REV 2 #1]:** `test_home_evening_to_sleep_mid_timeout_stays_held` — bedroom
  lighting `occupied` on, evidence 250 s old (released under the 240 s evidence hold), house switches to `sleep`: output
  True (shadow armed + riding `occupied`), and after `occupied` falls the tail is 1800 s. Parametrised variant with
  `home_night` added to the evidence states (the post-D0c case). **Drill:** make the evidence branch write
  `_hvac_armed[room] = False` when it releases -> this test goes RED.
- **Test:** `test_shadow_dicts_untouched_by_evidence_branch` (snapshot the three dicts across 50 random evidence-state
  passes; equal to a shadow-only run on the same `occupied` series).
- **Test:** `test_home_night_is_legacy_until_gate`, `test_guest_arriving_away_are_legacy`.
- **Test [REV 2 #3]:** `test_hold_zero_holds_while_active`, `test_hold_shorter_than_poll_no_drop_while_on`,
  `test_refresh_failure_holds_previous_output`.
- **Test [REV 2 #9]:** `test_no_stamp_on_fan_demoted_failsafe_recheck_sources` (each source, including no falling-edge
  stamp on the next tick), `test_ble_term_blocked_after_failsafe`.
- **Test:** camera/BLE/grace-hold/override stamps; `test_ble_cannot_arm_cold_room`; `test_falling_edge_refresh_stamps`;
  `test_last_occupied_time_backfilled_to_exact_release`; `test_tables_cover_every_room_type`;
  `test_legacy_tail_is_frozen_v5_103_19` (independent literals 60/120/60/0); `test_per_room_day_override_wins`;
  `test_accessor_fallback_uses_isinstance_datetime` (MagicMock coordinator -> `ev None`).
- **Tests that go red and are UPDATED, not deleted [REV 2 #8]** (see 11c for the full list).
- **Live [REV 2 #11, R2 M5]:** in `home_day`, for 10 consecutive releases across >= 3 room types: the per-room attr
  `release_at` equals `last_evidence_at + hold` (to the second), and the `*_hvac_occupied` off transition lands by
  `release_at + 335 s` (display updates on the next pass: tick <= 300 s + poll <= 35 s; a fast run makes it sooner).
  Discriminator: under the old rule the off transition could never precede the lighting `*_occupied` off.

---

## 5. D2: event-driven decisions on entry and exit

### 5.1 Fast run (never `_run_decision_cycle`) [REV 2 #6, #11]
```
async def _async_zone_fast_run(self, zone_id, trigger, edge_ts=None):
    wrote = False; fused_changed = False                       # [REV 2 R2 LOW] never unbound
    try:                                                       # [REV 2 #6] finally covers the whole coroutine
        if not self._fast_path_gates_open(zone_id, trigger): return
        async with self._decision_cycle_lock:
            if not self._fast_path_gates_open(zone_id, trigger): return   # re-check after the wait
            self._fast_path_running = True
            fused_before = zone.any_room_hvac_occupied
            zm.update_zone_climate_state(zone_id)
            zm.update_room_conditions(house_state=self._house_state, zone_ids={zone_id})
            if self._zone_intelligence_enabled:
                self._expire_pre_arrival_zones(dt_util.utcnow())            # [REV 2 R1 LOW-9]
            if not self._observation_mode:
                wrote = await self._apply_house_state_presets(
                    zone_filter={zone_id}, trigger=trigger, edge_ts=edge_ts)
            if self._zone_intelligence_enabled:
                self._compute_zone_presence_states(dt_util.utcnow())       # display, all zones
            fused_changed = fused_before != zone.any_room_hvac_occupied
            self._schedule_exit_timer(zone_id)
            if wrote or fused_changed:
                async_dispatcher_send(self.hass, SIGNAL_HVAC_ENTITIES_UPDATE)
    finally:
        self._fast_path_running = False
        self._fast_path_queued.discard(zone_id)
```
`_fast_path_gates_open` = not tearing down, enabled, boot-settle done, kill switch on, not observation mode, zone
intelligence on, zone still in `zm.zones`, zone not tripped. Re-checking after the lock wait catches a kill-switch flip,
teardown start, zone deletion or trip that happened while waiting.

### 5.2 `_apply_house_state_presets(*, zone_filter=None, trigger="periodic", edge_ts=None) -> bool`
- `zone_filter is None`: byte-identical.
- `zone_filter` set: skip the heat_cool enforcer (`:2227-2256`), `continue` for other zones at the loop top (`:2282`),
  skip DPM overrides (`:3319-3320`). Consensus gate, `arriving`, every per-zone rule and the vacancy sweep for Z run as
  today.
- `trigger`, `edge_ts`, and `zone_empty_since` (away rows) go into the `preset_change` details.
- **[REV 2 #4]** Every S1 write (fast or periodic) sets `self._zone_last_s1_write[zone_id] = (effective_preset, utcnow)`
  next to `:3194`.
- Returns `True` iff S1 applied a write.

### 5.3 `update_room_conditions(house_state, zone_ids=None)`
- `zone_ids` set: skip other zones BEFORE `zone.room_conditions.clear()` (`:667`).
- **[REV 2 #11, R2 M6]** Build `_coordinator_absent_this_pass` BEFORE the zone loop: in the entry loop (`:611-647`),
  for every ROOM entry in a zone whose coordinator is `None`. Remove the add at `:687`. The set is then pass-complete
  whether or not the pass is zone-filtered.
- `_classify_all_rooms` still runs over all rooms.

### 5.4 Entry trigger
Setup order [REV 2 R2 LOW]: subscribe to `SIGNAL_ROOM_ENTRY_LIFECYCLE` FIRST, then enumerate existing room
coordinators and attach `coordinator.async_add_listener(partial(self._on_room_refresh, entry_id))`. Attach is idempotent
(release-then-attach per `entry_id`), so a room that loads between the subscribe and the enumeration is attached once.
`loaded` attaches, `unloaded` releases, `options_updated` re-attaches.

`_on_room_refresh(entry_id)` (sync), short-circuits in order:
1. Gates as in 5.1 (except the zone checks).
2. Resolve room; skip hallways; resolve zone from `zm.zones` live; none -> return.
3. `ev = get_last_hvac_evidence_time()` (via `isinstance`). **None rule [REV 2 R2 LOW]:** `None` never counts as an
   advance and does not overwrite a stored value; the first non-`None` after `None` counts as an advance.
   Not advanced -> return; else store.
4. Zone-cold gate: stored `zone.any_room_hvac_occupied` True -> return.
5. Zone tripped -> count, return.
6. Per-zone limiter `HVAC_FAST_PATH_MIN_INTERVAL_S` on entry runs. **Exempt [REV 2 #7]** when
   `strategy_for(hass, zone.climate_entity).last_sent(zone.climate_entity, "set_preset_mode") == "away"`; on a
   registry miss (uncached generic strategy, `last_sent` always `None`) fall back to
   `_zone_last_s1_write[zone][0] == "away"`. Not keyed on `preset_mode`, which the §9.7 status feed can misreport.
7. Dedup: `zone_id in _fast_path_queued` -> return.
8. `_fast_path_queued.add(zone_id)`; `_track_task(async_create_task(_async_zone_fast_run(zone_id, "fast_entry", edge_ts=now)))`.

### 5.5 Lock rules
- Fast runs wait for the lock; `_fast_path_queued` stops pile-ups; `finally` always clears the queue entry [REV 2 #6].
- `_async_decision_cycle`: if the lock is held by a fast run, wait; if held by a full cycle, skip (today). After
  acquiring, skip if a full cycle started after this call was scheduled (`_last_full_cycle_started_at`), so no
  back-to-back full cycles double-sample `check_ac_reset` or anomaly counters.
- **[REV 2 #4] Same-tick nudge skip across ticks.** At `_run_decision_cycle` entry (`:1879`), replace
  `self._zones_written_this_cycle = set()` with the set of zones whose `_zone_last_s1_write` timestamp is within
  `SUPPRESS_TTL_SECONDS_PRESET` (120 s, `hvac_override.py:174`). A zone a fast run wrote seconds before a tick is then
  still skipped by the soft-nudge dispatch (`hvac_override.py:4713`) on that tick.

### 5.6 Exit timer [REV 2 #10]
`_schedule_exit_timer(zone_id)` at the end of every full cycle (all zones) and every fast run (its zone):
- Preconditions: kill switch on, zone intelligence on, not observation mode, zone established, current house state in
  `HVAC_EVIDENCE_RULE_STATES` or `HVAC_NIGHT_HOLD_STATES`, target preset home/sleep, `last_sent`/stamp not already
  `away`, not egress-paused, not tripped.
- `due = zm.zone_away_due_at(Z, grace_s) + HVAC_FAST_PATH_EXIT_SLACK_S`, `grace_s` chosen exactly as S1 does
  (`hvac.py:2271-2275`: constrained grace under coast/shed). `None` -> no timer.
- One-shot key `(Z, zone_release_at)`; a fired key is never rescheduled (stops the §9.7 loop).
- Callback: recompute from LIVE evidence; not due -> lazy reschedule (no run); due -> record key, queue `fast_exit`
  (exempt from the limiter).
- **Reschedule all zones' timers** when the grace knobs change (`number.py:571`, `:584`, `:677` call a new
  `hvac.reschedule_exit_timers()`) and when the energy constraint mode changes (`_handle_energy_constraint` `:3843`).
- Cancel on a fast entry that finds the zone fused-occupied; cancel on zone pruning in `_handle_zm_zones_updated`
  (`:3987`, `:4010`) [REV 2 R1 LOW-9].

### 5.7 Ceiling, runaway guard, trip-wire, kill switch
Unchanged from REV 1: write ceiling 6 per zone per hour; runaway guard 30 runs per zone per hour (lazy reschedules do
not count); quick-return trip-wire (900 s window, 8 per zone per day, one LOW NM); kill switch
`31 · Fast Room Response` (OFF = tick timing; the D1 clock stays). Global limiter G dropped (zone-scoped runs, lock
serialised, per-zone write ceiling bounds Carrier calls; G denied ~1 zone-cold edge/day, which breaks INV-1).
**Restart [REV 2 R2 LOW]:** all counters, trip states, `_fp_last_ev`, `_zone_last_s1_write` and exit timers are in
memory and reset on restart. Accepted: a restart ends any trip early (the next trip needs a fresh hour of breaches);
the first full cycle after boot-settle reschedules timers; the nudge-skip seed is empty for the first tick (same as
today).

### 5.8 Teardown
`_tearing_down = True`; release listeners, cancel exit timers, clear `_fast_path_queued` BEFORE the first `await`
(`hvac.py:5575`); tasks already cancelled at `:5565`; every callback checks `_tearing_down`.

### 5.9 Vacancy sweep timing [REV 2 #5] — decision: ACCEPT, no new gate
The sweep (`hvac.py:2416-2426`) runs only when the zone is past grace AND lighting-empty (`not zone.any_room_occupied`),
and is re-evaluated on every pass while the zone stays past grace. For a zone whose last room has a 900 s lighting
timeout, today the sweep lands on the away tick (~timeout + up to 5 min + 5 min); after this change the away write
lands at hold + 5 min (lights still on, no sweep) and the sweep lands on the first pass after the room's own lighting
timeout ends, i.e. up to ~5 min sooner than today. Accepted because (a) the room's own automation already turns its
lights off at that timeout, so the sweep is a backstop that never beats the room's own vacancy, and (b) the sweep still
requires every room in the zone to be lighting-empty. Test: `test_sweep_waits_for_lighting_empty_after_fast_exit`.

### D2 acceptance
- **Premise:** `test_rearm_while_lighting_still_on_triggers_fast_entry` (mutation: trigger on the lighting edge -> RED).
- `test_rearm_limiter_exempt_keyed_on_last_sent` (preset_mode reads `home` while `last_sent == "away"` -> exempt;
  registry-miss fallback case) [REV 2 #7]; `test_evidence_during_grace_prevents_away`.
- **[REV 2 #4]** `test_fast_write_seeds_nudge_skip_on_next_tick` — fast run writes zone_1 at t, periodic tick at
  t + 60 s: `check_ac_reset` sees zone_1 in `_zones_written_this_cycle` and does not nudge it; at t + 130 s it may.
  **Drill:** revert the seed to `set()` -> RED.
- **[REV 2 #6]** `test_queue_entry_cleared_on_every_exit_path` (gate fails before the lock; gate fails after the lock;
  exception inside; cancellation while waiting) and `test_gates_rechecked_after_lock_wait` (kill switch flipped while
  waiting -> no write).
- `test_fast_run_is_zone_scoped` (spies; per-spy drill), `test_fast_run_sweeps_only_its_zone` [REV 2 #5],
  `test_fast_run_leaves_sibling_zones_untouched`, `test_absent_set_built_before_zone_loop` [REV 2 R2 M6].
- **Equivalence [REV 2 #8]:** `test_fast_decision_equals_periodic_decision`; seeds MUST include writes (home from away,
  away from home, sleep, manual write-through under open gates) and non-writes (each INV-1 exception row). A seed set
  with no S1 write fails the test's own precondition assert.
- **Exit [REV 2 #10]:** `test_exit_timer_fires_at_release_plus_grace` with normal grace **10** and constrained grace
  **3** (not the coincident live 5/5), switching coast on and off while a timer is pending; `test_exit_timer_rescheduled_on_grace_knob_change`;
  `test_exit_timer_reads_live_evidence`; `test_exit_timer_lazy_reschedule`; `test_exit_timer_one_shot_under_feed_disagreement`;
  `test_exit_timer_one_shot_consumed_on_gate_e_deferral`; `test_exit_timer_cancelled_on_zone_prune` [REV 2 R1 LOW-9].
- **[REV 2 R2 LOW]** `test_two_zones_same_second` (evidence in zone_1 and zone_3 in the same loop turn: both run, each
  writes only its zone, order-independent); `test_fp_last_ev_none_rule`; `test_subscribe_then_enumerate_no_miss_no_double`.
- Lock rules, lifecycle idempotence, boot-settle, teardown-before-await, `_tearing_down` guards, ceiling/runaway/
  quick-return, kill switch, ledger fields (as REV 1).
- Config boundaries: grace 0; grace 60; per-room day hold 0; dwell 1.

---

## 6. Latency budget (before -> after)

Assumptions: live grace 300 s, dwell 0, tick 300.3-301.1 s, poll 30-35 s, event refresh within 2 s. Today the grace is
absorbed by tick quantization (the tick after the one that starts the tail both releases the room and clears
`now - lot > 300`). Kitchen at its old 600 s timeout -> ~18 min avg, matching the operator's "15-20 min".

| Path | Today (live) | After |
|---|---|---|
| Entry into a cold zone | avg ~2.5-3 min, worst ~5.5 min | usually under 5 s; <= 45 s SLA |
| Re-arm after a wrong away (person moves again) | avg ~2.5, worst ~5 min | usually under 5 s; <= 45 s; never rate-limited |
| Still person who does not move | held by timeout + tail | held by the hold ONLY; no re-arm until they move [REV 2 #2] |
| Re-detected during grace | no away write | no away write |
| Exit, `home_day`/`home_evening`, 300 s-timeout room | avg ~12.8 min (~10-15.6) | hold + 5 min: closet/infra 6, generic/utility/media/garage 7, bathroom 8, bedroom 9, common 10 min |
| Exit, same states, 900 s-timeout room | avg ~22.8 min | bathroom 8 / common 10 min |
| Exit, Kitchen | ~17.8 (old 600 s) / ~12.8 (300 s stopgap) | 10 min |
| Exit, `home_night`, `guest`, `arriving` [REV 2 #2] | today's rule | today's hold and start; away lands at release + 5 min (real grace; up to ~5 min later than today) |
| Exit, `sleep`/`waking` | timeout + night hold + tick quantization | same or later (shadow OR evidence); lands at release + 5 min |

"After" exits add ~2-5 s (stamp resolution + slack + run).

---

## 7. Residual risk (quantified from the audit, evidence states only)

Scope [REV 2 #2]: `home_day` + `home_evening` (the audit's 82.4 h). Nothing below applies to `home_night`, `guest`,
`arriving` or `away`, which stay on today's rule.

| Class | At the new table (G = 300) | Today |
|---|---|---|
| MID zone retreat (proxy for a still person) | **0 / 6.74 d** | 0 by construction |
| MID with Jaya's day override 60 left | +2 / 6.74 d | 0 (fixed by D4) |
| LATE zone retreat (ambiguous) | **~31 / 6.74 d (~4.6/day)**: Kitchen 28, Dining 1, Master Bath 1, Jaya Bath 1 | 0 by construction |

- **A still person is protected only by the hold [REV 2 #2].** If a seated person's sensors stay quiet longer than
  hold + grace, the zone goes to away and stays there until they move. The fast path helps only after that movement.
  The MID count is 0 in the sample because every measured still gap was shorter than hold + grace for its type.
- Knob coupling: the MID-zero result needs hold + grace >= max MID gap, for the normal grace (knob 48) AND the
  energy-saving grace (knob 49, used under coast/shed) [REV 2 R1 LOW-10]. Knob 49 at 5 min is at the common-area limit
  (300 + 300 >= 603 fails by 3 s; the audit counted 0 at T = 300 because the max gap was 603 with no retreat). Lowering
  knob 49 below 5 reintroduces MID risk in common areas; its helper text warns about this (section 14.2).
- ZR is now close to the expected rate (the fast exit removes the tick padding); still an upper bound because camera,
  BLE and grace-hold only shorten gaps. Fusion filters and phantom radars are unmeasured; D0c and the quick-return
  trip-wire measure them.
- Cost of one wrong retreat: one away + one home write (once the person moves) + drift. Upper bound ~9 extra writes/day.

---

## 8. D0: probes (read-only)
- **D0a latency baseline** — `hvac_fast_path_d0_probe.py --latency`, >= 3 occupied days (earliest 2026-09-30).
- **D0b write-rate baseline** — REV 4 F9 query, >= 3 days of W1-A rows (earliest 2026-09-30).
- **D0c residual at the exact table** — `hvac_raw_evidence_gap_probe.py --graces 300,600` with current config.
  Gate A: any zone's evidence-state ZR > 2x the audit figure -> stop, back to the operator.
- **D0c-home_night [REV 2 #2]** — same probe with a new `--states home_night` filter, >= 7 nights. Gate B: `home_night`
  MID ZR at the new table (G = 300 and G = knob 49) = 0 -> propose adding `home_night` to `HVAC_EVIDENCE_RULE_STATES`
  (reviewed rung-1 change); otherwise `home_night` stays legacy. Gate B does not block this cycle's deploy.

D0a/D0b block the live comparison; D0c Gate A blocks deploy.

---

## 9. Live acceptance (discriminating)

| # | Check | Pass | Plausible failure |
|---|---|---|---|
| L1 | Fast entry latency | >= 90 % of `fast_entry` rows: `row_ts - edge_ts <= 45 s`; median < 10 s | uniform 0-300 s (tick) |
| L2 | Exit exactness | every `fast_exit` away row: `row_ts - zone_empty_since` in `[300, 350] s` (or `[g, g + 50]` for the constrained grace) | `[300, 600]` spread; `< 300` (INV-2 break) |
| L3 | INV-2 live | for each evidence-state away row, every zone room's recorded `release_at <= row_ts - grace` and `rule == evidence` | any later `release_at` |
| L4 | Re-arm [REV 2 #7] | for every quick return, a `fast_entry` home/sleep row within 45 s of `edge_ts` — **zone_1 excluded while §9.7 is open** (its status feed can make the strategy skip or the tick re-issue) | home write only at the next tick |
| L5 | Zone scope | during fast runs, no `climate_write` rows for other zones; no heat_cool / nudge / cover / fan actions; sweep actions only for the run's zone | any off-zone write |
| L6 | Clock decoupled | D1 Live criterion | off never precedes lighting off |
| L7 | Night and legacy unchanged | in `sleep` and `home_night`, `rule` is `night` / `legacy` and releases never precede the room's `*_occupied` off + the shadow tail | earlier release |
| L8 | Write rate | per-zone `climate_write`/day <= D0b + spread + 10; no ceiling trips | trips or a jump |
| L9 | Quick returns | 7-day sum <= 2x D0c prediction | much higher |
| L10 | Lifecycle | after a room reload and an HA restart: one listener per room; timers re-armed | duplicates / missing |
| L11 | Nudge skip [REV 2 #4] | no `ac_ramp_events` `nudge_started` for a zone within 120 s after a `fast_entry`/`fast_exit` write on that zone | a nudge seconds after a fast write |

---

## 10. D3: vacancy grace re-check (measure; knob only)
Knob 48 (live 5), no code. Constraint first: common 300 + G >= 603 -> G >= 303 s; the same applies to knob 49
[REV 2 R1 LOW-10]. The grace cannot drop below 5 minutes without raising the common-area hold. Probe after D1+D2 live
>= 7 days (`hvac_vacancy_grace_probe.py` adapted): per zone, time from `zone_empty_since` to the next re-arm; for
G' ∈ {2, 3, 4} min, extra away/home pairs vs conditioning minutes saved, with the matching hold increase. Operator turns
the knob or not.

## 10b. D4: clear Jaya Bedroom's day hold override
Blank `hvac_vacancy_hold` on Jaya Bedroom (keep night 5400). Verify in `.storage`; live attr `hvac_vacancy_hold_s` = 240
in `home_day` (rule `evidence`), 5400 in `sleep`. Note the shadow's legacy tail for Jaya becomes 60 (table) instead of
the override 60: identical.

---

## 11. Tier: 3
Unchanged justification: changes the still-person safeguard; adds a trigger into the shared lock and S1 site; two
failed plan reviews on this surface. Protocol: REV 2 re-review (both framings) -> build -> four parallel reviews
(A local correctness; B integration/state machine; C per-site mutation; D adversarial completeness incl. pre-existing
paths) -> orchestrator re-grep + re-drill -> operator checkpoint before deploy.

### 11b. What a builder will most likely get wrong
REV 1 items 1-13 stand, with 11 replaced. Added [REV 2]:
- (11, replaced) Removing or re-pointing the numeric clamp. It stays, reading the legacy tail.
- 14. Letting the evidence branch write `_hvac_armed` / `_hvac_tail_until` / `_hvac_prev_state_occupied` (breaks INV-5).
- 15. Pointing the shadow at `ROOM_TYPE_HVAC_HOLD` instead of `ROOM_TYPE_HVAC_TAIL_LEGACY`.
- 16. Putting `guest`/`arriving`/`home_night` in the evidence states.
- 17. `finally` placed after the lock acquisition instead of around the whole coroutine.
- 18. Keying the limiter exemption on `zone.preset_mode`.
- 19. Resetting `_zones_written_this_cycle` to an empty set at cycle entry.
- 20. Reading `ev` with `if ev:` (a MagicMock is truthy) instead of `isinstance(ev, datetime)`.
- 21. Exit timer reading the last pass's evidence instead of the live accessor; not rescheduling on grace/constraint changes.
- 22. Stamping evidence on a fan-demoted / failsafe / fan-recheck tick, or falling-edge-stamping the tick after one.

### 11c. Test-file impact [REV 2 #8]
| Existing test | Why it changes | Disposition |
|---|---|---|
| `test_hvac_night_hold_follows_sleep.py:69-79` `test_home_night_uses_day_hold` | Compares the selector with `ROOM_TYPE_HVAC_HOLD[room_type]`; the shadow selector now reads `ROOM_TYPE_HVAC_TAIL_LEGACY` and the table values changed | **RED -> update** to compare with the legacy table |
| `:82-88` literals 60/60/120 in `home_night` | The shadow keeps the v5.103.19 tail | **stays GREEN by design** (see section 19 — the coordinator expected RED) |
| `:91-100`, `:103-121`, `:124-133` | shadow selector unchanged | GREEN |
| `:167-185` `test_producer_home_night_arms_day_tail` | drives `_compute_hvac_occupied` in `home_night` (legacy) | **stays GREEN by design**; add a sibling `home_day` test that asserts the evidence rule with `last_evidence` supplied |
| `:216-255` `test_update_room_conditions_hands_house_state_to_tail` | MagicMock coordinator -> `ev None` via `isinstance`; sleep/home_night decided by the shadow | **GREEN only if** the `isinstance` fallback is built as specified; RED if the builder uses truthiness — so it is a guard test for item 20 |
| `test_hvac_vacancy_hold_ui_defaults.py:159-172` `test_help_text_describes_reject_on_night_below_day` | asserts "rejects a night below day" and "0 = disabled" in `en.json`; section 14.2 rewrites both helpers | **RED -> update** to the new wording (still states that a night below day is rejected; states what 0 means) |
| `test_zzz_hvac_conditioning_demand.py` table tests (`test_d1_hold_tables_source_of_truth` et al.) | day table values changed | RED -> update; add the legacy-table oracle |
| `test_v5_103_8_hvac_knobs_and_obs.py:154-170` clamp test | clamp unchanged, now against the legacy tail | GREEN; add a case proving night 90 is not lifted to 300 |

### 11d. Per-site mutation drill table [REV 2 #8]
**R2's verbatim drill table was not provided to me and is not on disk** (grep of `docs/` and the repo). The table below
is mine; the orchestrator should replace or merge it with R2's verbatim table before build.
| # | Site (neuter the RETURN / value, not just the call) | Test that must go RED |
|---|---|---|
| 1 | Evidence-state output returns `shadow_out` | `test_evidence_state_ignores_lighting_timeout` |
| 2 | Evidence branch writes `_hvac_armed = False` on release | `test_home_evening_to_sleep_mid_timeout_stays_held` |
| 3 | Night output drops the shadow (`ev_out` only) | same + `test_night_release_never_before_shadow` |
| 4 | `home_night` added to evidence states | `test_home_night_is_legacy_until_gate` |
| 5 | `active` term removed from `ev_out` | `test_hold_zero_holds_while_active` |
| 6 | `refresh_ok` hold removed | `test_refresh_failure_holds_previous_output` |
| 7 | Suppressed-source check removed from the stamp | `test_no_stamp_on_fan_demoted_failsafe_recheck_sources` |
| 8 | `not _failsafe_fired` removed from the BLE term | `test_ble_term_blocked_after_failsafe` |
| 9 | Camera helper returns `None` in the stamp only | `test_camera_person_refreshes_evidence_inside_lighting_timeout` |
| 10 | `last_occupied_time` back-fill removed | `test_last_occupied_time_backfilled_to_exact_release` + `test_exit_timer_fires_at_release_plus_grace` |
| 11 | Zone filter moved after `clear()` | `test_fast_run_leaves_sibling_zones_untouched` |
| 12 | Absent set filled back inside the zone loop | `test_absent_set_built_before_zone_loop` |
| 13 | Heat_cool enforcer not skipped under `zone_filter` | `test_fast_run_is_zone_scoped` (enforcer spy) |
| 14 | DPM overrides not skipped under `zone_filter` | `test_fast_run_is_zone_scoped` (DPM spy) |
| 15 | Listener triggers on the lighting binary sensor edge | `test_rearm_while_lighting_still_on_triggers_fast_entry` |
| 16 | Limiter exemption keyed on `preset_mode` | `test_rearm_limiter_exempt_keyed_on_last_sent` |
| 17 | Nudge-skip seed reverted to `set()` | `test_fast_write_seeds_nudge_skip_on_next_tick` |
| 18 | `finally` moved inside the lock | `test_queue_entry_cleared_on_every_exit_path` |
| 19 | Post-lock gate re-check removed | `test_gates_rechecked_after_lock_wait` |
| 20 | One-shot key not recorded | `test_exit_timer_one_shot_under_feed_disagreement` |
| 21 | Exit timer reads pass-cached evidence | `test_exit_timer_reads_live_evidence` |
| 22 | No reschedule on grace/constraint change | `test_exit_timer_rescheduled_on_grace_knob_change` + the 10/3 grace test |
| 23 | Timer not cancelled on zone prune | `test_exit_timer_cancelled_on_zone_prune` |
| 24 | Waiting periodic does not skip after a full cycle | `test_waiting_periodic_skips_if_full_cycle_ran` |
| 25 | Teardown releases after the first await | `test_teardown_releases_before_first_await` |
| 26 | Write ceiling never trips | `test_write_ceiling_trips_and_clears_at_local_midnight` |
| 27 | `isinstance` replaced by truthiness | `test_accessor_fallback_uses_isinstance_datetime` + night-hold `:216-255` |
Every drill: bytecode disabled, file restored, `git status` clean before the next drill.

---

## 12. Sequencing, coordination, supersession
- **B is shipped (v5.103.19); no wait gate** [REV 2 preamble]. Build on current `develop`.
- **`HVAC-ENTRY-DWELL-ROOM-CLOCK-1` (Stage B): partly superseded** — the release half is absorbed (evidence states
  only); the arming-persistence half stays on the card, re-based on the evidence stamp.
- **REV 4 plan:** superseded; add a banner.
- **`HVAC-FAST-PATH-FAN-WARM-EDGES-1` — decision [REV 2 #11, R1 checklist 4]: keep it OUT of this cycle; recommend
  reviving it as the NEXT cycle.** The trigger ("fan latency becomes an explicit goal") is arguably met by "we wanted
  faster responses". But fans read the lighting `.occupied`, not the HVAC clock, and have their own counters and
  gates (fan-transition gate, recheck, demotion); calling them from fast runs would reintroduce REV 4's
  "fan writes off-schedule" HIGH into a Tier-3 cycle. A fan-only fast path (run `FanController` for one room on its
  lighting edge) is a separate Tier-2 cycle, with a D0 of warm-zone entry -> fan-on latency. Operator to confirm.
- `HVAC-HOLD-SIZING-ALL-ROOMS-1` -> D3/L9 input. `HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1` unchanged exposure.
  `HVAC-WRITE-CONFIRMATION-ORACLE-1`: one-shot timer keeps §9.7 at tick cadence; L4 excludes zone_1.
- W1-A baseline (D0b) >= 3 days, earliest 2026-09-30.

## 13. REV 4 findings and re-review HIGHs: disposition
As REV 1, plus: the "sibling-zone wake-ups" answer now includes the pass-complete absent set built before the zone
loop [REV 2 R2 M6]; F5's rerun replacement now covers the same-tick nudge skip across ticks [REV 2 #4].

## 14. Knobs and labels

### 14.1 Knob ladder
| Number | Value | Rung | Why |
|---|---|---|---|
| `ROOM_TYPE_HVAC_HOLD` | 4.6 | 1 | Measured; reopening CRIT-1 needs review |
| `ROOM_TYPE_HVAC_TAIL_LEGACY` [REV 2 #1] | 60/120/60/0 | 1 | Frozen v5.103.19 tail for the shadow; must not be tuned |
| `HVAC_EVIDENCE_RULE_STATES` [REV 2 #2] | (`home_day`, `home_evening`) | 1 | Which states use the new clock; adding one needs a probe and review |
| `HVAC_FAST_PATH_MIN_INTERVAL_S` | 60 | 1 | per-zone entry floor; exempt for re-arm |
| `HVAC_FAST_PATH_SLA_S` | 45 | 1 | observability target |
| `HVAC_FAST_PATH_EXIT_SLACK_S` | 2 | 1 | clears strict `>` |
| `HVAC_FAST_PATH_MAX_WRITES_PER_ZONE_PER_HOUR` | 6 | 1 | Carrier bound |
| `HVAC_FAST_PATH_MAX_RUNS_PER_ZONE_PER_HOUR` | 30 | 1 | runaway guard |
| `HVAC_QUICK_RETURN_WINDOW_S` / `_NM_PER_DAY` | 900 / 8 | 1 | trip-wire |
| Fast room response switch | ON | 3 | rollback without deploy; OFF = tick timing |
| Knob 48 / knob 49 grace | 5 / 5 | 3 (existing) | D3; coupling warning on both |

### 14.2 Labels (short config-flow phrase; plain helper; entity names <= 3 words; no jargon)
Banned in user text: tail, HVAC-occupied, clamp, gate, evidence, tick, fast path, debounce, CRIT, fused, rung, shadow, legacy.

**Room options, climate step:**
- `hvac_vacancy_hold` label: `Empty-room hold (day)`
- `hvac_vacancy_hold` helper [REV 2 #3]: `How many seconds heating and cooling keep treating this room as occupied during the day and evening. The time counts from the last sign of someone in the room, such as motion, presence, a camera or a phone. This covers people sitting still, and it is the only protection for someone who stays completely still. Leave blank to use the default for this room type: 1 minute for closets, 2 minutes for utility and media rooms, 3 for bathrooms, 4 for bedrooms and 5 for living areas. Enter 0 to hold only while a sensor still sees someone. From 9 pm until the house goes to sleep, this number is counted from when the room itself shows as empty.`
- `hvac_vacancy_hold_night` label: `Empty-room hold (night)`
- `hvac_vacancy_hold_night` helper [REV 2 #3]: `The hold used while the house is asleep or waking up. It counts from when the room itself shows as empty, so sleepers who lie still get extra time. Leave blank to use the default for this room type: 30 minutes for bedrooms and media rooms, 15 for living areas, 10 for bathrooms, garages and utility rooms, and 5 for closets. Enter 0 for no extra time once the room shows as empty. This form rejects a night value below the day value.`
- Error `hvac_hold_night_below_day` stays: `The night hold must be at least as long as the day hold. Raise the night value, or leave one of them blank to use the room type's default.`
- Section `climate_backstop` name: `Thermostat and empty-room hold`

**HVAC coordinator options (helper text only):**
- `hvac_vacancy_grace_minutes`: `Minutes a zone waits after its last room empties before heating and cooling switch to Away. If someone comes back sooner, nothing changes. Going below 5 minutes can switch a zone to Away while someone sits still in a living area.`
- `hvac_vacancy_grace_constrained` [REV 2 R1 LOW-10]: `The same wait, used while the house is saving energy. It must be no longer than the normal delay. Going below 5 minutes can switch a zone to Away while someone sits still in a living area.`
- `hvac_zone_entry_dwell`: `Minutes a zone must stay occupied before heating and cooling switch it from Away to Home. At 0, the switch happens within seconds of someone arriving. Above 0, it waits for the next regular 5-minute check.`

**New switch:** `31 · Fast Room Response` (`switch.ura_hvac_coordinator_31_fast_room_response`).

**Notifications:** as REV 1 (ceiling, quick returns, runaway guard).

**Acceptance:** `strings.json` == `en.json`; banned-word check clean; JSON parses; hassfest passes;
`test_hvac_vacancy_hold_ui_defaults.py` updated to the new wording.

## 15. Files
As REV 1, with: `const.py` also gains `ROOM_TYPE_HVAC_TAIL_LEGACY`; `hvac_const.py` gains `HVAC_EVIDENCE_RULE_STATES`;
`config_flow.py` is **no longer changed** (validation kept) [REV 2 #1]; `number.py` calls `reschedule_exit_timers()`
from the three grace setters [REV 2 #10]; `hvac_zones.py` gains `_shadow_tail_seconds`, `_hvac_output`, `_hvac_rule`,
`_hvac_day_release_at`; test-file updates per 11c; `scripts/probes/hvac_raw_evidence_gap_probe.py` gains `--states`.

## 16. Non-goals
REV 1 list, plus [REV 2]: no change to `home_night`, `guest`, `arriving` or `away` behaviour; no change to the numeric
clamp or the flow validation; no fan fast path (section 12).

## 17. Not done / parked
- R2's verbatim drill table (not provided; section 11d is a stand-in).
- Night-anchor unification (night hold from last evidence): parked; revival trigger unchanged from REV 1.
- `home_night` on the evidence rule: parked behind D0c Gate B.

## 18. REV 2 change log
| # | Finding | Change | Where |
|---|---|---|---|
| pre | B shipped | Wait gate dropped; `hvac_zones.py` lines refreshed; state of play re-read | header, 0.1, 0.3, 12 |
| 1 | INV-5 breaks at day->night (R1 CRIT-1 = R2 H1) | Shadow machine on every pass owns the three dicts; evidence output in its own dicts; night = shadow OR evidence; frozen legacy tail; clamp/validation kept; crossing test + drill | 0.5, 2 INV-5, 3.1, 4.2-4.4, 4.6, D1, 11d #1-3 |
| 2 | home_night never measured (R1 H2 = R2 H2) | Evidence rule only in `home_day`/`home_evening`; `home_night` legacy until D0c Gate B; still person = hold only | header, 1, 2, 4.3, 6, 7, 8 |
| 3 | Hold 0 / shorter than poll (R1 H3 = R2 M1) | `active OR now < ev + hold`; refresh failure holds; truthful "0" helpers | 4.1, 4.2, 14.2 |
| 4 | Same-tick nudge skip lost (R1 H4 = R2 H4) | `_zone_last_s1_write`; cycle-entry seed within 120 s; test + drill; L11 | 5.2, 5.5, D2, 9, 11d #17 |
| 5 | Vacancy sweep (R1 H5 = R2 M4) | In the consumer map; INV-4 corrected; timing change ACCEPTED with reason | 2, 3.2, 5.9 |
| 6 | Dedup leak / gate re-check (R2 H3) | `finally` around the whole coroutine; gates re-checked after the lock; tests | 5.1, 5.5, D2 |
| 7 | Falsifiable invariants (R1 M6 = R2 M3) | INV-1/INV-3 as "= periodic outcome within SLA"; exception table; exemption on `last_sent`; L4 excludes zone_1 | 2, 5.4, 9 |
| 8 | Test list (R1 M7 + R2 M7) | Test-impact table; `isinstance` fallback; drill table (R2's verbatim missing); equivalence seeds must write | 4.2, D2, 11c, 11d |
| 9 | Stamp gating (R1 M8) | No stamp on fan-demoted/failsafe/fan-recheck; BLE `not _failsafe_fired` | 4.1 |
| 10 | Exit timer (R2 M2) | Live evidence; reschedule on grace and constraint changes; 10/3 grace test | 4.5, 5.6, D2 |
| 11 | R2 M5, R2 M6, R1 LOW-9/10/11, R2 LOWs, R1 checklist 4 | Live criterion `release_at` + 335 s; absent set before loop; prune cancels timers + pre-arrival expiry in fast runs; knob 49 warning; zone-intelligence sensor; unbound locals; None rule; subscribe-then-enumerate; two-zones test; restart counters documented; display rule; fan card decision | throughout |

## 19. Where REV 2 departs from the coordinator's instructions
1. **`guest` and `arriving` are NOT on the evidence rule.** The instruction says the audit measured them; it did not.
   The audit's day bucket is `home_day` + `home_evening` only, and it excludes `away`, `arriving` and `guest` (audit
   §1 "82.4 h of day state (`home_day` / `home_evening`)", §8.6). They stay legacy until measured.
2. **Night-hold test lines `:82-88`, `:167-185`, `:216-255` stay GREEN, not RED.** Fix 1 requires the shadow to run
   today's machine byte-for-byte, so it keeps the v5.103.19 tails via the frozen legacy table. Only `:69-79` (which
   reads `ROOM_TYPE_HVAC_HOLD`) goes red. `:216-255` becomes the guard for the `isinstance` fallback.
3. **The numeric clamp and flow validation are kept** (REV 1 removed them). With the shadow on the legacy tail the clamp
   no longer causes the 90 -> 300 lift, and the night OR provides monotonicity against the new hold.
4. **Vacancy sweep "fires sooner" is bounded and accepted, not gated**: it never precedes the room's own lighting
   vacancy (5.9).
