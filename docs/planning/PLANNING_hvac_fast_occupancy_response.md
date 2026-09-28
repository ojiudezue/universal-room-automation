# PLANNING: HVAC fast occupancy response (own release clock + event-driven entry and exit) — REV 3

**Cards:** `HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1` (revived) + the parked W2 fast path
(`HVAC-W2-OCCUPANCY-TRUTH`, plan `PLANNING_hvac_w2_occupancy_fast_path.md` REV 4). Workstream `HVAC-W2-OCCUPANCY-TRUTH`.

**Status:** REV 3.
- REV 1: two Tier-3 plan reviews, both FIX-PLAN.
- REV 2: folded both; its re-review found the design sound (FIX-PLAN, text edits only).
- REV 3: folds those edits plus two operator hold-value rulings (section 0.6).

Changes are tagged `[REV 2 #n]`, `[REV 3 <id>]`, `[RULING R1/R2]`. Change logs: section 18. Departures: section 19.

**Checkpoint items needing explicit operator confirmation before deploy:** the Kitchen exception drop (section 7.1)
and the quick-return alarm threshold (section 14.1).

**Base:** current `develop` after v5.103.19 (night-tail B shipped). `hvac_zones.py` lines refreshed; `hvac.py`
unchanged.

**Operator decision (2026-09-27 ~22:00, verbatim):**
- "We wanted faster responses. This is nuts."
- On the still-person risk: "fast path catches it. The room type hold blunts it. Do it"

**Design premise, with its limit [REV 2 #2]:**
1. A per-room-type hold blunts radar misses of still people. **It is the ONLY protection for someone who stays
   still.** A still person produces no new evidence, so the fast path cannot "catch" them. It reacts only once they
   move again.
2. An event-driven fast path re-arms a re-detected room in seconds instead of at the next 5-minute tick.

| Deliverable | What | Code? |
|---|---|---|
| D0 | Baselines, residual re-probe, `home_night` gate probe (read-only) | probe only |
| D1 | New release clock in `home_day`/`home_evening`; today's machine kept as a shadow; other states unchanged | yes |
| D2 | Event-driven zone decision on entry AND exit | yes |
| D3 | Vacancy grace re-check (measure, knob only) | no |
| D4 | Operator config step: clear Jaya Bedroom's day hold override | config |

---

## 0. Institutional context verified

### 0.1 Mandatory read
- **`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`:** read completely; re-read for REV 2.
  - v5.103.19: D8 night tails follow `HVAC_NIGHT_HOLD_STATES` = (`sleep`, `waking`) (`hvac_const.py:934`).
    `home_night` uses the day table. `FAN_TRUST_STATES` is unchanged.
  - W1-B shipped (v5.103.18, §9e four gates).
  - Relevant: §2, §3.1-§3.3, §9c, §9d, §9.4, §9.7, §10 C1-C25.
- **C18:** with dwell 0 (live), entry = wait for the next tick.
- **C24:** HVAC occupancy today is not a faster clock; this plan builds one.
- **§10:** no C1-C25 claim is re-asserted.
- **Drift to fix in the build commit:** §3.2 (knob 48 = 10) and §8 (dwell = 2) are stale; live values are grace 5,
  constrained 5, dwell 0. §3.1 still cites pre-B line numbers.

### 0.2 Other docs and cards read
| Source | Use |
|---|---|
| Card `HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1` | Disposition, per-type tails, camera/BLE caveat. Kitchen timeout 600 -> 300 s (operator, 2026-09-27, verified live) |
| `AUDIT_hvac_raw_evidence_gaps_2026_09_26.md` | Per-type MID/LATE counts and the T >= max MID - G rule. Day bucket = `home_day` + `home_evening` (82.4 h). Excluded: `away`/`arriving`/`guest` (§8.6). `home_night` lumped with `sleep`/`waking` |
| `PLANNING_hvac_w2_occupancy_fast_path.md` REV 4 + card `HVAC-W2-OCCUPANCY-TRUTH` | Reused; section 13 |
| `AUDIT_hvac_fast_path_rate_2026_09_26.md` | 16.6 zone-cold edges/day; cycle p95 27.6 s; L=60 denies 0/114 |
| `PLANNING_hvac_night_tail_follows_sleep.md` (B shipped) | `HVAC_NIGHT_HOLD_STATES` reused |
| Cards `HVAC-ENTRY-DWELL-ROOM-CLOCK-1`, `HVAC-FAST-PATH-FAN-WARM-EDGES-1`, `HVAC-HOLD-SIZING-ALL-ROOMS-1`, `HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1`, `HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1`, `HVAC-WRITE-CONFIRMATION-ORACLE-1` | Section 12 |

### 0.3 Code surveyed (develop, post v5.103.19)
- **`coordinator.py`:**
  - occupancy block `:3538-3643`; `_last_motion_time` set on Tier-1 activity `:3589`
  - camera override `:3663-3697` (source `"camera"` `:3677`, failsafe guard `:3667`)
  - BLE chain-hold `:3699-3908` (source `"ble"` `:3851`, failsafe guard `:3706`, cap `:3810-3847`)
  - fan-demoted source `:4113`; failsafe `:4361`/`:4369`; override switches `:4790-4811`; skip-first `:4825`
  - `apply_fan_recheck_release` `:5249-5280`
  - poll 30 s + jitter `:625-631`; event refresh within 2 s `:1395-1411`; accessor pattern `:5384`
- **`hvac_zones.py`:**
  - `update_room_conditions` `:566`; entry loop `:611-647`; `_classify_all_rooms` `:665`
  - zone loop `:666`; `clear()` `:667`; absent add `:687`; `room_occupied` `:718`; hallway `:725-736`
  - rollup `:772-789`; `get_zone_status_attrs` `:791`
  - `_effective_hvac_hold_seconds` `:977-1049` (clamp `:1031-1047`, selector `:1049`)
  - `_compute_hvac_occupied` `:1051-1126`; `conditioning_retreat_ok` `:1525`; `hvac_occupied_diag` `:1588`
- **`hvac.py`:**
  - `_zones_written_this_cycle` `:455`/`:1879`/`:3194` (read at `hvac_override.py:4713`)
  - `_async_decision_cycle` `:1583`; `_track_task` `:1644`; `_run_decision_cycle` `:1873`
  - `_apply_house_state_presets` `:2132-3320`: consensus gate `:2156`, enforcer `:2227`, arriving `:2261`,
    grace choice `:2271-2275`, loop `:2282`, row-1 + sweep `:2339-2426`, D6 `:2437`, D5 `:2568`, dwell `:2738`,
    D7 `:2780`, transient hold `:2860`, W1-B gates `:2918`, S1 write `:3125-3271`, DPM `:3319`
  - `_handle_energy_constraint` `:3843`; `_handle_zm_zones_updated` `:3908` (pops `:3987`, `:4010`)
  - `_execute_vacancy_sweep` `:4266`; `_expire_pre_arrival_zones` `:4624`; `_compute_zone_presence_states` `:4775`
  - `get_mode_attrs` `:5411`; `async_teardown` `:5555`
- **Grace writers outside `number.py`:** `button.py:857-858`; `__init__.py:7339`, `:7353`, `:7565`.
- **Elsewhere:**
  - `hvac_strategy.py`: `strategy_for` `:254-266`, `last_sent` `:142`, no-op `:187-197`
  - `hvac_override.py:174` (`SUPPRESS_TTL_SECONDS_PRESET = 120`)
  - `sensor.py:13684-13745` (zone-intelligence sensor)
  - HA `update_coordinator.py:170-182`, `:528-533`
- **Tests read:**
  - `test_hvac_night_hold_follows_sleep.py` (all)
  - `test_hvac_vacancy_hold_ui_defaults.py:140-171`
  - `test_zzz_hvac_conditioning_demand.py:240-331`, `:505-523`, `:903-916`
  - `test_v5_103_8_hvac_knobs_and_obs.py:120-170`, `:359-430`

### 0.4 Config-first check
| Candidate | Solves it? | Why |
|---|---|---|
| Room `occupancy_timeout` | Partly (Kitchen stopgap) | Still two tick quantizations; no effect on entry or re-arm |
| Per-room holds | No | Today the hold starts only after the lighting timeout |
| Knob 48 grace (5) | No | See section 7.2 context |
| Dwell (0) | Already 0 | — |
| Shorter tick | Rejected | Carrier call-rate bound; whole-house cycle |
| Jaya Bedroom day override 60 | **Change (D4)** | Under the new clock, 60 counts from the last evidence; the audit shows MID retreats in that room at 60 |

### 0.5 Prior-art scan: REUSE or BUILD
| Piece | Verdict | Symbol / reason |
|---|---|---|
| Evidence-rule hold table | **REUSE, change values** | `ROOM_TYPE_HVAC_HOLD` `const.py:1219` |
| Shadow tail table | **BUILD (frozen copy, every type explicit)** | `ROOM_TYPE_HVAC_TAIL_LEGACY` |
| Shadow selector | **REUSE, behaviour unchanged** | `_effective_hvac_hold_seconds` `hvac_zones.py:977`: legacy table, night table, overrides, clamp |
| Evidence and display selectors | **BUILD** | `_evidence_hold_seconds`, `_display_hold` |
| Night table, overrides, clamp, flow validation | **REUSE unchanged** | |
| State tuples | REUSE `HVAC_NIGHT_HOLD_STATES`; **BUILD** `HVAC_EVIDENCE_RULE_STATES` | |
| Evidence timestamp + active flag | **BUILD (fields + 2 accessors)** | pattern `coordinator.py:5384` |
| Camera/BLE evidence | **REUSE the override blocks' verdict** | `data[STATE_OCCUPANCY_SOURCE] in ("camera", "ble")` |
| Event source, lifecycle, lock, tasks, timers, NM, ledger, attrs, probes, kill-switch pattern | REUSE / BUILD as REV 2 | |
| Nudge-skip seed, limiter exemption | REUSE + extend | `_zones_written_this_cycle`; `_zone_last_s1_write` then `last_sent` |

Memory consulted: suppression-needs-discharge, wire-in anchors, hollow anchors, marginal-benefit, measure-before-build,
coincidental-equality, unrestored-drill, pyc staleness, zone-away-home-night gap.

### 0.6 Operator decision ledger (hold values) [RULING R1, R2]
| # | Date | Ruling (verbatim) | Effect |
|---|---|---|---|
| R0 | 2026-09-27 ~22:00 | "fast path catches it. The room type hold blunts it. Do it" | Build the cycle |
| R1 | 2026-09-27 (REV 3) | "Shorter. I already articulated why it's not a big deal. We're measuring things that don't have the fast and slow protection and we're measuring without the time stacking." | Rejects the planner/reviewer 360/150 margin values. Use the audit table: generic/utility 120, closet 60, bath 180, bedroom 240, common 300 (common superseded by R2). The Kitchen exception is dropped under the same rationale |
| R2 | 2026-09-27 (REV 3) | "3mins" | Common-area evidence hold = **180 s**. R1's rationale applies |

**Rationale (the operator's, as recorded).**
- The audit's margin figures were measured on today's design, with no re-arm fast path.
- They were measured with the stacked timers (lighting timeout + tail + tick), not the single clock built here.
- The quick-return trip-wire and the kill switch measure and bound the residual live. **The quick-return trip-wire is
  the live measure of this choice.**

---

## 1. Marginal-benefit note
The audit weighed release speed alone. The operator added event-driven re-arm, which helps only when the person moves
again. The plan keeps today's machine underneath and limits the new rule to the audit-measured states. The hold values
are operator rulings (0.6); section 7.2 records their arithmetic as context.

---

## 2. Falsifiable invariants

**Definitions.**
- `ev(R)`: the room's last evidence time. `active(R)`: the room has evidence at its latest refresh.
- `hold_ev(R)`: from `_evidence_hold_seconds`.
- Evidence states = (`home_day`, `home_evening`). Night states = (`sleep`, `waking`). Legacy = every other state.
- `release(R)`:
  - evidence states: `ev + hold_ev`
  - night states: the later of the shadow's tail end and `ev + hold_ev`
  - legacy states: the shadow's tail end
- `E(Z)`: max `release(R)` over live non-hallway rooms of Z.
- `P(Z, t)`: what a periodic cycle would write for Z at `t` (possibly nothing).

**INV-1 (re-arm = periodic outcome within the SLA).**
- Trigger: a live non-hallway room of Z has an evidence advance at refresh `t_r` while Z's stored fused value is False.
- Required: a zone-scoped run for Z starts by `t_r + 45 s` and issues exactly `P(Z, t_run)`, for Z only.
- After a `vacant_past_grace` away with target home/sleep, `P` is a home/sleep write unless an exception holds.

| INV-1 exception | Outcome |
|---|---|
| Dwell > 0 | dwell skip; tick |
| Row-1 transient-room hold | suppressed row |
| D5 shed / D6 stale | effective away |
| W1-B gates (a/b), (c), (d), (e) on a `manual` zone | `preset_change_deferred` |
| Consensus defer gate | call skipped |
| `arriving`, egress pause, observation mode, zone intelligence off | no write |
| D7 night trust | suppression row |
| §9.7: status already reads the target and `last_sent` matches | `SKIPPED_ALREADY_CORRECT` |
| Kill switch off, zone tripped, boot-settle, teardown | tick backstop <= 300 s |

**INV-2 (no early vacancy away, evidence states).** No `vacant_past_grace` away for Z at `t` while any live
non-hallway room R has `active(R)` or `release(R) > t - G`.

**INV-3 (exit = periodic outcome at the due time, once).**
- In evidence and night states, with no new evidence, a `fast_exit` run starts in `[E + G + SLACK, E + G + SLACK + SLA]`
  and issues `P(Z, t_run)`.
- At most one run per episode, key `(Z, E(Z))`. A deferral consumes the key and the tick owns the rest of the episode.
- `G` is the live grace read when the timer fires.

**INV-4 (zone scope).**
- Climate writes only for Z, via S1. Other actuation: Z's vacancy sweep.
- House-wide effects, accepted:
  - (a) a display-only `zone_presence_state` refresh;
  - (b) `_expire_pre_arrival_zones`, which may clear other zones' pre-arrival flags and schedule fan-off for timed-out
    ones (time-driven; the next tick would do the same).
- It never calls: the enforcer, egress tick, `check_ac_reset`, fans, covers, predictor, anomaly observations, DPM,
  arrester sweeps, or the Carrier freshness check.
- It never changes another zone's room conditions or rollup fields.

**INV-5 (shadow and legacy).**
- Today's machine runs byte-for-byte on every pass and alone owns `_hvac_armed`, `_hvac_prev_state_occupied` and
  `_hvac_tail_until`.
- Night and legacy output is at least the shadow's output.
- In legacy states `last_occupied_time` is not back-filled and no exit timer runs, so `home_night`, `guest`,
  `arriving` and `away` behave as v5.103.19.

**Equivalence.** fast run for Z at t == `P(Z, t)`. The seed set must include writes.

---

## 3. Producer and consumer map

### 3.1 Producer
| Step | After |
|---|---|
| Shadow (every state) | Today's machine on `data["occupied"]`; tail from `_effective_hvac_hold_seconds` |
| Evidence-state output | `active OR now < ev + hold_ev`; evidence term held through refresh failures up to 600 s after `ev` |
| Night-state output | `shadow OR active OR now < ev + hold_ev` |
| Legacy-state output | shadow |
| Rollup | as today; back-fill `last_occupied_time = max(lot, E)` when fused False, in evidence and night states only |

### 3.2 Consumers
The REV 2 table stands (row-1 retreat, vacancy sweep, row-1 hold, D5, D6, D7, D9, row-10, F8/F9, grace math,
`zone_presence_state`, zone-intelligence sensor, W1-B gates, nudge-skip reader, fans (unaffected, lighting), pre-arrival,
presence D6 source 4 (unaffected), per-room display, zone status, mode sensor, optimization). The per-room display now
reads `_display_hold`.

---

## 4. D1: HVAC's own release clock

### 4.1 Evidence stamp (`coordinator.py`)
- Fields `_last_hvac_evidence_time`, `_hvac_evidence_active`.
- Accessors `get_last_hvac_evidence_time()`, `is_hvac_evidence_active()`.
- One stamp site, after `:4811` and before `:4825`:
  ```
  source = data.get(STATE_OCCUPANCY_SOURCE)
  suppressed = source in (OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED, "failsafe",
                          OCCUPANCY_SOURCE_FAN_RECHECK_RELEASE)
  evidence_now = (not suppressed) and (not self._is_override_vacant()) and (
      any_sensor_active
      or (grace_hold and self._last_occupied_state)
      or source in ("camera", "ble")          # the override blocks' own verdict this tick
      or self._is_override_occupied()
  )
  if evidence_now or (self._hvac_evidence_active and not suppressed):
      self._last_hvac_evidence_time = now
  self._hvac_evidence_active = evidence_now
  ```
- **Camera/BLE count only after the room's own lighting timeout ends,** because the override blocks run only then
  (they inherit their failsafe guards, the BLE chain rule and the cap).
  - Where timeout - `hold_ev` > grace (300 s), a still person held only by BLE can release, retreat, and re-arm when BLE
    takes over: a two-write flap.
  - Rooms at the new holds: Master Bathroom 720, Jaya Bathroom 720, Exercise Room 720, Oji Vanity 420, Study A 420,
    Kitchen Pantry 380, Ziri Bathroom 360, Game Room 360.
  - Living Room (the only firing camera): 300 - 180 = 120 < 300, so no flap.
- `apply_fan_recheck_release` sets `_hvac_evidence_active = False` without stamping.
- In memory; `None` after restart until the first evidence.

### 4.2 Producer: shadow plus rule output (`hvac_zones.py`)
1. **Shadow:** runs exactly as today, with `hold_s` from `_effective_hvac_hold_seconds` (legacy table outside night).
   Only the shadow writes `_hvac_armed`, `_hvac_prev_state_occupied`, `_hvac_tail_until`, `_hvac_arm_source`.
   Result: `shadow_out`.
2. **Evidence term:** `ev_out = evidence_active or (last_evidence is not None and now < last_evidence + hold_ev)`.
   Store `_hvac_day_release_at[room]`.
3. **Refresh-failure hold (evidence states only):**
   - If `refresh_ok is False` and the previous output was True: keep `ev_out = True`, for at most
     `HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S` = 600 s after `last_evidence`.
   - 600 s = the longest evidence hold (240) + ~10 polls, so a dead room coordinator cannot hold a zone.
   - Night and legacy states: shadow on stale data, as today.
4. **Output:** evidence -> `ev_out`; night -> `shadow_out or ev_out`; legacy -> `shadow_out`. Store in `_hvac_output`
   and `_hvac_rule`. The evidence branch never writes the shadow's dicts.

Readers use `isinstance(ev, datetime)` and `evidence_active is True`;
`refresh_ok = coordinator.last_update_success is not False`. The `active` term covers hold 0 and holds shorter than a
poll.

### 4.3 States
- `sleep` / `waking`: shadow OR evidence.
- `home_night`: legacy until D0c Gate B.
- `guest`, `arriving`, `away`, `None`: legacy (unmeasured).

### 4.4 Selectors
| Selector | Returns | Callers |
|---|---|---|
| `_effective_hvac_hold_seconds` (unchanged signature and logic) | shadow tail: night table in night states, `ROOM_TYPE_HVAC_TAIL_LEGACY` otherwise; overrides; clamp | shadow only |
| `_evidence_hold_seconds(room_type, override_day)` (new) | `override_day` or `ROOM_TYPE_HVAC_HOLD.get(type, DEFAULT_HVAC_VACANCY_HOLD)` | evidence term, `room_release_at` |
| `_display_hold(...)` (new) | `(hold, rule)` with rule in `evidence` / `night` / `legacy` | `binary_sensor.py:894` |

Clamp and flow validation are unchanged.

### 4.5 Exact release instant
- Back-fill in evidence and night states only.
- `room_release_at` reads the live accessors; it returns `None` while `active` or while the shadow rides `occupied`.
- `zone_away_due_at(Z, grace_s)`.

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
- The comment on `ROOM_TYPE_HVAC_HOLD` cites the rulings (0.6) and says the quick-return trip-wire is the live check.
- `DEFAULT_HVAC_VACANCY_HOLD` (60) remains the fallback for unknown types.

### D1 acceptance
- **Anchors:**
  - `test_evidence_state_ignores_lighting_timeout`
  - `test_home_evening_to_sleep_mid_timeout_stays_held`, plus its drill
  - `test_shadow_dicts_untouched_by_evidence_branch`
  - `test_home_night_is_legacy_until_gate`, `test_guest_arriving_away_are_legacy`
- **Holds and refresh failure:**
  - `test_hold_zero_holds_while_active`, `test_hold_shorter_than_poll_no_drop_while_on`
  - `test_refresh_failure_hold_evidence_states_only_and_bounded`
- **Stamping:**
  - `test_camera_ble_stamp_only_from_override_verdict`
  - `test_no_stamp_on_fan_demoted_failsafe_recheck_sources`
  - `test_override_vacant_blocks_stamp`, `test_falling_edge_refresh_stamps`, `test_fan_recheck_release_clears_active`
- **Back-fill:** `test_last_occupied_time_backfilled_to_exact_release`, `test_no_backfill_in_legacy_states`.
- **Tables [RULING R2]:**
  - `test_evidence_hold_values`: closet 60, infra 60, generic 120, utility 120, media 120, garage 120, bathroom 180,
    **common 180**, bedroom 240, hallway 0. Independent literals.
  - `test_legacy_tail_is_frozen_v5_103_19`: every type explicit; independent literals.
  - `test_selectors_split`.
- **Other:** `test_per_room_day_override_wins`, `test_accessor_fallback_uses_isinstance_datetime`.
- **Live:** in `home_day`, `release_at == last_evidence_at + hold_ev`; the off transition lands by
  `release_at + 335 s`.

---

## 5. D2: event-driven decisions

### 5.1 Fast run
```
async def _async_zone_fast_run(self, zone_id, trigger, edge_ts=None):
    wrote = False; fused_changed = False
    try:
        if not self._fast_path_gates_open(zone_id, trigger): return
        async with self._decision_cycle_lock:
            if not self._fast_path_gates_open(zone_id, trigger): return
            self._fast_path_running = True                     # set only while holding the lock
            try:
                fused_before = zone.any_room_hvac_occupied
                zm.update_zone_climate_state(zone_id)
                zm.update_room_conditions(house_state=self._house_state, zone_ids={zone_id})
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
                self._fast_path_running = False                # cleared inside the lock
    finally:
        self._fast_path_queued.discard(zone_id)                # every exit path
```

### 5.2-5.3 S1 and producer parameters
As REV 2:
- `_apply_house_state_presets(zone_filter, trigger, edge_ts) -> bool`: skips the enforcer and DPM under the filter;
  loop-top `continue` for other zones; ledger fields; `_zone_last_s1_write` stamp.
- `update_room_conditions(zone_ids)`: filter before `clear()`; absent set built in the entry loop.

### 5.4 Entry trigger
- Subscribe to the lifecycle signal, then enumerate rooms; attach is idempotent.
- `_on_room_refresh`, in order:
  1. Gates.
  2. Hallway skip; zone resolved live.
  3. Evidence advance (None rule).
  4. Zone-cold gate.
  5. Tripped zone.
  6. 60 s per-zone limiter.
  7. Dedup.
  8. Queue.
- **Limiter exemption:** `_zone_last_s1_write[zone][0] == "away"` first, then `last_sent(...) == "away"`. Never
  `preset_mode`.

### 5.5 Lock rules
- A periodic cycle waits only while `_fast_path_running`; it skips behind a full cycle, and skips after acquiring if a
  full cycle ran in the meantime.
- Nudge-skip seed: zones with an S1 write within 120 s.

### 5.6 Exit timer
- The callback recomputes `due` from live evidence and the live grace (chosen as at `hvac.py:2271-2275`); if not due
  it reschedules lazily.
- Reschedule hooks (`number.py` setters, `_handle_energy_constraint`) only reduce latency. Bypass writers at
  `button.py:857-858` and `__init__.py:7339/7353/7565` can at worst delay a fire to the old due time.
- One-shot key; preconditions include evidence or night state; pruned zones cancel their timers.

### 5.7-5.9
Ceiling, runaway guard, trip-wire, kill switch, restart, teardown and sweep timing: as REV 2. The quick-return
threshold is revised in 14.1.

### D2 acceptance
All REV 2 tests stand, plus:
- `test_fast_path_running_only_true_while_holding_lock`
- `test_exit_timer_uses_grace_at_fire_time`
- `test_limiter_exemption_order`

---

## 6. Latency budget (before -> after) [RULING R2]
| Path | Today (live) | After |
|---|---|---|
| Entry into a cold zone | avg ~2.5-3 min, worst ~5.5 min | usually < 5 s; <= 45 s |
| Re-arm after a wrong away (person moves) | avg ~2.5, worst ~5 min | usually < 5 s; <= 45 s |
| Still person who does not move | held by timeout + tail | held by the hold ONLY |
| Re-detected during grace | no away | no away |
| Exit, `home_day`/`home_evening`, 300 s-timeout room | avg ~12.8 min (~10-15.6) | hold + 5 min (list below) |
| Exit, same states, 900 s-timeout room | avg ~22.8 min | bath 8 / common 8 min |
| Exit, Kitchen | ~17.8 (600 s) / ~12.8 (300 s stopgap) | **8 min** |
| Exit, `home_night`, `guest`, `arriving` | today's rule | unchanged |
| Exit, `sleep`/`waking` | timeout + night hold + tick | same or later; lands at release + 5 min |

Exits by type, `home_day`/`home_evening`: closet/infra 6 min; generic/utility/media/garage 7; bathroom 8; **common 8**
(3 + 5); bedroom 9. Each adds ~2-5 s.

---

## 7. Residual risk (evidence states only)

### 7.1 Counts from the audit at the ruled values (G = 300, 6.74 days) — context, operator-accepted
| Class | At the ruled table | Today |
|---|---|---|
| MID zone retreat (proxy for a still person) | **~13** — common_area at T=180 (Kitchen; audit ZR180 common = 13). generic/utility at 120, bath at 180, closet at 60: 0. Bedroom at 240: between the audit's 1 (T=180) and 0 (T=300) | 0 |
| MID with Jaya's day override 60 left | +2 (D4 fixes) | 0 |
| LATE zone retreat (ambiguous) | **~36** (audit headline at T=180 was 37 all rooms; Kitchen 29, Dining 2, Master Bath 1, Jaya Bath 1, bedrooms <= 1) | 0 |
| Total | ~49 / 6.74 d ≈ 7/day house-wide, mostly zone_3 | 0 |

**Why these numbers are context, not a gate (operator's rationale, R1).**
- They come from a model of today's design, with no re-arm fast path and with stacked timers.
- A retreat here costs two writes and minutes of away once the person moves; each one is a quick-return event that the
  trip-wire counts live.
- A still person who does not move stays at away until they do. The hold is their only protection; the operator
  accepts this.

**Kitchen exception dropped — operator-accepted in spirit (R1); explicit confirmation requested at the checkpoint.**
- The audit's §7 recommended keeping the Kitchen at "timeout + 60". Under R1/R2 it gets `common_area` 180.
- About 29 of the ~36 LATE and all ~13 MID retreats above are the Kitchen.
- In 30 of 30 Kitchen LATE events another room (mostly the Patio) had evidence.
- The Kitchen timeout is already 300 s (operator, tonight).
- A per-room override (config, no code) remains available if the operator changes his mind.

### 7.2 Context arithmetic (no recommendation) [RULING R2]
The audit's rule: a gap can retreat a zone only if gap > T + G.

| Type | Sample max day MID gap | T + G at the ruled values |
|---|---|---|
| common_area | 603 s | **180 + 300 = 480 s** |
| bedroom | 495 s | 240 + 300 = 540 s |
| generic | 396 s | 120 + 300 = 420 s |
| utility | 386 s | 120 + 300 = 420 s |
| bathroom | 836 s | 180 + 300 = 480 s (audit measured 0 at T = 180: the zone was co-occupied) |
| closet | 204 s | 60 + 300 = 360 s |

- Recorded as context. The operator accepts it (R1, R2).
- Knob 49 (energy-saving grace) enters the same sum under coast/shed.
- The quick-return trip-wire is the live measure.

---

## 8. D0: probes
As REV 2:
- D0a: latency baseline.
- D0b: write-rate baseline.
- D0c Gate A: blocks deploy if any zone's ZR exceeds 2x the audit figure at the RULED T values (section 7.1).
- D0c Gate B: `home_night`.

The probe's T grid gains 240. It already has 60/120/180.

## 9. Live acceptance
L1-L11 as REV 2/3. L9 (quick returns): the 7-day sum is compared with D0c's prediction at the ruled values (~7/day
house-wide). The discriminator is "within 2x" versus "much higher".

## 10. D3: vacancy grace re-check
As REV 2, with section 7.2 as context. At the ruled holds, any grace cut raises the retreat counts. The probe reports
extra quick returns against minutes saved; the operator decides.

## 10b. D4: config step
- Clear Jaya Bedroom's day override.
- Kitchen override only if the operator reverses the Kitchen ruling at the checkpoint.

---

## 11. Tier: 3
Unchanged. Operator checkpoint before deploy covers:
- the Kitchen confirmation;
- the quick-return threshold;
- D0c Gate A.

### 11b. Builder traps
REV 2/3 list stands (1-25).

### 11c. Test-file impact
| Test | Result | Disposition |
|---|---|---|
| `test_zzz_hvac_conditioning_demand.py:909` `ROOM_TYPE_HVAC_HOLD["bedroom"] == 60` | **RED** | update to 240; add `ROOM_TYPE_HVAC_TAIL_LEGACY["bedroom"] == 60` |
| `test_hvac_night_hold_follows_sleep.py:69-79` | **RED** | compare with `ROOM_TYPE_HVAC_TAIL_LEGACY` |
| `test_hvac_vacancy_hold_ui_defaults.py:159-172` | **RED** | new helper wording |
| `test_zzz:246-269`, `:325-331` | GREEN | shadow selector unchanged |
| `test_zzz:505-523` (night >= day per type) | GREEN | night 300-1800 >= day 60-240 |
| `test_hvac_night_hold_follows_sleep.py` other tests | GREEN | shadow; `:216-255` guards the `isinstance` fallback |
| `test_v5_103_8_hvac_knobs_and_obs.py:127-170`, `:359-430` | GREEN | shadow + override |
| New `test_evidence_hold_values` | — | pins common 180 [RULING R2] |

### 11d. Per-site mutation drill table (table of record)
The 44 rows as in the previous REV 3 draft. No row depends on a hold value except #44 and `test_evidence_hold_values`.
Every drill: bytecode disabled, file restored, `git status` clean after.

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
| 29 | `finally` inside the lock | `test_queue_entry_cleared_on_every_exit_path` |
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

---

## 12. Sequencing and supersession
As REV 2 (B shipped, no wait gate):
- Stage B card: partly superseded.
- REV 4 plan: banner.
- Fan card: keep out; recommend it as the next cycle (operator to confirm).
- D0b: earliest 2026-09-30.

## 13. REV 4 findings disposition
As REV 2.

## 14. Knobs and labels

### 14.1 Knob ladder
| Number | Value | Rung | Why |
|---|---|---|---|
| `ROOM_TYPE_HVAC_HOLD` | 4.6; **common 180** | 1 | Operator rulings R1/R2 (0.6). Changing a value re-opens the still-person trade and needs review. Live check: the quick-return trip-wire |
| `ROOM_TYPE_HVAC_TAIL_LEGACY` | frozen | 1 | shadow; must not be tuned |
| `HVAC_EVIDENCE_RULE_STATES` | (`home_day`, `home_evening`) | 1 | |
| `HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S` | 600 | 1 | longest hold 240 + ~10 polls; 0 disables |
| `HVAC_FAST_PATH_MIN_INTERVAL_S` / `_SLA_S` / `_EXIT_SLACK_S` | 60 / 45 / 2 | 1 | as REV 2 |
| `HVAC_FAST_PATH_MAX_WRITES_PER_ZONE_PER_HOUR` / `_MAX_RUNS_...` | 6 / 30 | 1 | as REV 2 |
| `HVAC_QUICK_RETURN_WINDOW_S` | 900 | 1 | |
| `HVAC_QUICK_RETURN_NM_PER_DAY` | **12** (was 8) | 1 | At the ruled values the audit implies ~7/day house-wide, mostly zone_3 (~6/day). 8 per zone would alert almost daily on expected behaviour. 12 is ~2x the expected zone_3 rate, so an alert means worse than the audit predicted. **Checkpoint item** |
| Fast room response switch | ON | 3 | rollback |
| Knob 48 / 49 grace | 5 / 5 | 3 | D3 |

### 14.2 Labels
REV 2 strings stand, with the day-hold helper updated [RULING R2]:
- `hvac_vacancy_hold` helper: `How many seconds heating and cooling keep treating this room as occupied during the day and evening. The time counts from the last sign of someone in the room, such as motion, presence, a camera or a phone. This covers people sitting still, and it is the only protection for someone who stays completely still. Leave blank to use the default for this room type: 1 minute for closets, 2 minutes for media, utility and general rooms and garages, 3 for bathrooms and living areas, and 4 for bedrooms. Enter 0 to hold only while a sensor still sees someone. From 9 pm until the house goes to sleep, this number is counted from when the room itself shows as empty.`
- Grace helpers: drop the specific "below 5 minutes" sentence (it came from the margin sizing the operator rejected).
  - `hvac_vacancy_grace_minutes`: `Minutes a zone waits after its last room empties before heating and cooling switch to Away. If someone comes back sooner, nothing changes. A shorter wait saves energy but switches a zone to Away more often while someone sits still.`
  - `hvac_vacancy_grace_constrained`: `The same wait, used while the house is saving energy. It must be no longer than the normal delay. A shorter wait saves energy but switches a zone to Away more often while someone sits still.`

Other strings are unchanged.

## 15. Files
As REV 3 draft:
- `const.py`: tables per 4.6.
- `hvac_const.py`: states tuple, refresh-fail bound, fast-path constants (quick-return threshold 12).
- `hvac_zones.py`: selectors, shadow + rule output, back-fill, helpers.
- `coordinator.py`: stamp and accessors.
- `hvac.py`: fast path.
- `binary_sensor.py`, `switch.py`, `number.py` hooks.
- `strings.json` / `en.json`, tests, probes, state of play, REV 4 banner, README.

## 16. Non-goals
REV 2/3 list stands.

## 17. Parked
- Night-anchor unification.
- `home_night` on the evidence rule (Gate B).

## 18. Change logs

### REV 3 (final)
| Item | Change | Where |
|---|---|---|
| **RULING R1 / R2** | Holds = audit table with common 180 (overrides the 360/150 margin sizing). Ledger 0.6. Arithmetic recorded as context. Quick-return trip-wire named as the live measure | 0.6, 4.6, 6, 7, 10, 11c, 14 |
| Quick-return threshold | 8 -> 12 per zone per day (expected rate at the ruled values); checkpoint item | 14.1 |
| Kitchen (LOW-3) | Dropped under R1; operator-accepted in spirit; explicit confirmation at checkpoint | header, 7.1, 10b, 11 |
| Camera/BLE flap room list | Recomputed for the ruled holds; Living Room no longer at risk | 4.1 |
| Refresh-fail bound rationale | 600 = 240 + ~10 polls | 4.2, 14.1 |
| N1-N6, LOW-1, LOW-2 | As folded earlier in REV 3 (selector split, N2 lock flag, N3 scoped bounded hold, N4 fire-time grace, N5 override verdict, 44-row drill table, exemption order, no legacy back-fill) | 2, 4, 5, 11 |
| Grace helper strings | Drop the "below 5 minutes" line (it came from the rejected margin sizing) | 14.2 |

### REV 2
The REV 2 table stands. Summary:
- (1) shadow machine
- (2) `home_day`/`home_evening` only
- (3) `active` term, refresh hold
- (4) nudge-skip seed
- (5) vacancy sweep
- (6) outer `finally`, post-lock gate re-check
- (7) periodic-equivalence invariants, `last_sent` exemption
- (8) tests
- (9) stamp gating
- (10) exit timer
- (11) misc

## 19. Departures and notes
1. `guest` and `arriving` stay legacy (the audit excluded them).
2. Only three existing tests go RED (11c).
3. Clamp and flow validation kept.
4. Vacancy sweep timing accepted, not gated.
5. N5 cost: camera/BLE count only after a room's own timeout. That causes possible two-write flaps in eight
   long-timeout rooms (4.1).
6. **The quick-return threshold moved from 8 to 12 per zone per day** to follow the operator's ruled values. Without
   it, the alarm would fire almost daily on expected behaviour. Flagged for the checkpoint.
7. At common 180 the audit's model predicts ~13 still-person-proxy retreats per 6.74 days (all Kitchen). This is
   recorded as operator-accepted context, not a recommendation (R1/R2).
