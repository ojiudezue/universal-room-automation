# PLANNING: HVAC fast occupancy response (own release clock + event-driven entry and exit)

**Cards:** `HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1` (revived) + the parked W2 fast path
(`HVAC-W2-OCCUPANCY-TRUTH`, plan `PLANNING_hvac_w2_occupancy_fast_path.md` REV 4). Workstream `HVAC-W2-OCCUPANCY-TRUTH`.
**Status:** plan, not reviewed. Tier 3 (see section 11). Two plan reviews are required before any build dispatch.
**Base:** `develop` @ `b2868c0d1` (v5.103.18, W1-B shipped). Build waits for the night-tail B build (section 12).

**Operator decision (2026-09-27 ~22:00, verbatim):**
- "We wanted faster responses. This is nuts."
- On the still-person risk: "fast path catches it. The room type hold blunts it. Do it"

**Design premise (operator):**
1. A per-room-type hold blunts radar misses of still people.
2. An event-driven fast path re-arms a room the moment it is re-detected, so a wrongly released room recovers in
   seconds instead of waiting for the next 5-minute tick.

| Deliverable | What | Code? |
|---|---|---|
| D0 | Baselines and residual re-probe (read-only) | probe only |
| D1 | HVAC's own release clock (day), per-type holds, night unchanged | yes |
| D2 | Event-driven zone decision on entry AND exit | yes |
| D3 | Vacancy grace re-check (measure, knob only) | no |
| D4 | Operator config step: clear Jaya Bedroom's day hold override | config |

---

## 0. Institutional context verified

### 0.1 Mandatory read
- **`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` read completely (lines 1-470).** W1-B is SHIPPED
  (v5.103.18, §9e, four gates at the S1 site). Relevant to this plan: §2 (triggers; no occupancy trigger), §3.1-§3.3
  (producer, rollup, retreat gate, dwell, grace), §9c (override switches ride the hold), §9d (fast-path scope),
  §9.4 (placeholder readers), §9.7 (zone_1 away re-issue loop), §10.
- **C18:** entry latency 5-10 min came from the dwell skip; with dwell 0 (live) entry = wait for the next tick.
- **C24:** today HVAC occupancy is NOT a faster clock. It arms on the lighting rising edge and holds through the
  lighting timeout plus the tail. This plan builds that faster clock; it does not claim it exists.
- **§10 check.** This plan re-asserts none of C1-C25. In particular: no 1-minute tick (C8); suppression windows are
  15 s temp / 120 s preset (C17, C23); the S1 manual guard is superseded by the §9e four gates (C25).
- **State-of-play drift found (fix in the build commit, not a §10 entry):** §3.2 says knob 48 = 10 live and §8 says
  dwell = 2. Live `.storage/core.config_entries` (read 2026-09-27): `hvac_vacancy_grace_minutes: 5`,
  `hvac_vacancy_grace_constrained: 5.0`, `hvac_zone_entry_dwell: 0`.

### 0.2 Other docs and cards read
| Source | Use |
|---|---|
| Card `HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1` incl. `disposition_2026_09_26_groom` + `revived_2026_09_27` | Measured disposition: "execution is the safer design"; safe per-type tails; `_last_motion_time` misses camera/BLE. Revived by operator; Kitchen timeout stopgap 600 -> 300 s (verified live: Kitchen options `occupancy_timeout: 300.0`). |
| `docs/planning/AUDIT_hvac_raw_evidence_gaps_2026_09_26.md` | Per-type safe hold table (closet 60, generic 120, bath 180, bedroom 240, common 300; utility 120; media keep 120), MID/LATE zone-retreat counts, the `T + G` coupling, the implementation note on `coordinator.py:3589/3680/3867`. |
| `docs/planning/PLANNING_hvac_w2_occupancy_fast_path.md` REV 4 (PARKED) | Design reused (zone-cold gate, per-zone limiter, SLA, ceiling, teardown discipline, single lifecycle subscription, trigger label on the ledger row). Section 13 dispositions every F1-F15 finding. |
| Card `HVAC-W2-OCCUPANCY-TRUTH` `disposition_2026_09_26_groom` | The REV 4 second plan review failed with 4 HIGH: "a whole-house cycle triggered off-schedule keeps leaking into other zones: wrong-zone reruns, heat_cool/egress/fan/cover writes, sibling-zone wake-ups". The full review text is not on disk (grep of `docs/reviews/` and the repo found only the card summary). Section 13 answers each named leak. |
| `docs/planning/AUDIT_hvac_fast_path_rate_2026_09_26.md` | 16.6 zone-cold edges/day; cycle-duration proxy p95 27.6 s; per-zone L=60 denies 0/114 zone-cold edges. |
| `docs/planning/PLANNING_hvac_night_tail_follows_sleep.md` (building in parallel) | B adds `HVAC_NIGHT_HOLD_STATES = ("sleep", "waking")` and switches the selector at `hvac_zones.py:1046`. This plan uses that constant for "night" and builds after B (section 12). |
| Card `HVAC-ENTRY-DWELL-ROOM-CLOCK-1` (Stage B) | Supersession verdict in section 12. |
| Cards `HVAC-FAST-PATH-FAN-WARM-EDGES-1`, `HVAC-HOLD-SIZING-ALL-ROOMS-1`, `HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1`, `HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1`, `HVAC-WRITE-CONFIRMATION-ORACLE-1` | Adjacency (section 12). |
| vibememo entry 153 (dwell 0, grace 5, fast path parked) | Why the fast path was parked; this plan revives it on the operator's new decision. |

### 0.3 Code surveyed (develop @ b2868c0d1)
- `coordinator.py`: `_async_update_data` occupancy block `:3538-3643` (`_last_motion_time = now` only when a Tier-1
  sensor is active, `:3589`); camera override `:3663-3697` (seeds `_last_motion_time` only if unset, `:3679-3680`);
  BLE chain-hold override `:3699-3908` (seed only if unset `:3866-3867`; cap `:3810-3847`); override switches
  `:4790-4811`; skip-first `:4825-4851`; poll 30 s + 0-5 s jitter `:625-631`; event refresh rate-limited to 2 s with
  trailing edge `:1395-1411`, `:1616-1630`; entry debounce default 150 ms (`const.py:1154`); accessor pattern
  `get_became_occupied_time` `:5384-5395`.
- `domain_coordinators/hvac_zones.py`: `RoomCondition` `:61-84`; `ZoneState` fused property `:177-188`;
  `update_room_conditions` `:566-788` (coordinator-absent set `:686`, hallway exclusion `:724-735`, rollup writes
  `:771-788`); `_effective_hvac_hold_seconds` `:976-1046` (numeric night>=day clamp `:1028-1044`, selector `:1046`);
  `_compute_hvac_occupied` `:1048-1123`; `conditioning_retreat_ok` `:1522`; `hvac_occupied_diag` `:1585`.
- `domain_coordinators/hvac.py`: subscriptions `:1145-1230`; periodic timer `:1374-1382`; `_async_decision_cycle`
  `:1583-1617` (re-entrancy skip `:1611-1615`); `_track_task` `:1644`; `_run_decision_cycle` `:1873-2076`;
  `_apply_house_state_presets` `:2132-3320` (consensus defer gate `:2156-2197`, heat_cool enforcer over ALL zones
  `:2227-2256`, arriving return `:2261`, per-zone loop `:2282`, row-1 `:2339-2426`, D6 `:2437-2539`, D5 `:2568-2733`,
  dwell skip `:2738-2748`, D7 `:2780-2852`, row-1 transient hold `:2860-2911`, W1-B gates `:2918-2996`, S1 write +
  `preset_change` row `:3125-3271`, DPM overrides `:3319-3320`); `_handle_person_arriving` `:4567-4622`;
  `_compute_zone_presence_states` `:4775-4820`; `get_mode_attrs` `:5411`; `async_teardown` `:5555-5610`.
- `domain_coordinators/hvac_predict.py:583` (F8 pre-cool), `:1420` (F9 pre-heat); `hvac_override.py:2513-2560`
  (row-10 comfort delay); `hvac_fans.py:761`, `:997` (fans read LIGHTING `.occupied`); `presence.py:2147-2159`
  (D6 source 4 reads LIGHTING `.occupied`); `binary_sensor.py:745-920` (per-room HVAC Occupied display).
- HA `helpers/update_coordinator.py` (installed in `.venv-ha`): `async_add_listener` `:170-182` returns a remove
  callable; listeners are called after every successful refresh when `always_update` is True (default True, `:84`;
  `:528-533`). Room coordinators do not override `always_update` (`coordinator.py:626-631`).
- Live config (`/Users/okosisi/ha-config/.storage/core.config_entries`, 2026-09-27): only Jaya Bedroom has a day
  override (`hvac_vacancy_hold: 60.0`, night `5400.0`); 9 common rooms have night `90.0`; timeouts: most 300 s,
  Breakfast Nook 480, Ziri/Jaya Bedroom and Kitchen Pantry 500, Game Room, Study A and Ziri Bathroom 540, Oji Vanity
  600, Master Bathroom, Jaya Bathroom and Exercise Room 900. `switch.kitchen_override_vacant` restores `off`
  (`core.restore_state`), so the Kitchen does feed HVAC (answers the card's open question).

### 0.4 Config-first check
| Candidate setting | Solves it? | Why |
|---|---|---|
| Room `occupancy_timeout` (lower it per room) | Partly; already used as the Kitchen stopgap (600 -> 300) | Shortens lighting too; today's release is still timeout + tail + two tick quantizations; does nothing for entry or re-arm latency. |
| Per-room `hvac_vacancy_hold` / `_night` | No | Today the hold only starts after the lighting timeout, so no hold value can release sooner than the timeout. |
| Knob 48 vacancy grace (live 5) | No | Already lowered; the audit shows lowering it further re-introduces MID risk (section 7). |
| `number.ura_hvac_coordinator_zone_entry_dwell` (live 0) | Already 0 | The remaining entry wait is the 5-minute tick itself. |
| `HVAC_DECISION_TICK` shorter | Rejected | Rung-1 Carrier call-rate bound (`hvac_const.py:13`); runs the whole house, the exact leak the REV 4 review failed. |
| Jaya Bedroom day override 60 | **Must change (D4)** | Under the new clock 60 s means 60 s after the last evidence, not after a 500 s timeout. Audit: Jaya Bedroom MID ZR at T=60 is 2 per 6.74 days; at the bedroom default 240 it is 0. |

**Verdict:** a code change is required for D1 and D2; D4 is a config step; D3 is a knob decision after measurement.

### 0.5 Prior-art scan: REUSE or BUILD per piece
| Piece | Verdict | Existing symbol / justification |
|---|---|---|
| Per-type day hold table | **REUSE, change values** | `ROOM_TYPE_HVAC_HOLD` `const.py:1219-1224` (rung 1). |
| Night hold table and per-room overrides | **REUSE unchanged** | `ROOM_TYPE_HVAC_HOLD_NIGHT` `const.py:1230-1241`; `CONF_HVAC_VACANCY_HOLD[_NIGHT]` `const.py:1252-1253`; resolver `hvac_zones.py:976`. |
| Night-state tuple | **REUSE (from night-tail B)** | `HVAC_NIGHT_HOLD_STATES` added by `PLANNING_hvac_night_tail_follows_sleep.md` B. Not `FAN_TRUST_STATES`. |
| "Last raw evidence" timestamp | **BUILD (one field + accessor)** | Searched `coordinator.py` for `_last_motion_time`, `_last_trigger_time`, `_last_occupied_time`, `_ble_only_hold_since`, `_became_occupied_time`, `_last_pir_motion_time`. None is correct: `_last_motion_time` (`:3589`) misses camera/BLE (only seeded when unset, `:3680`, `:3867`); `_last_trigger_time` (`:3270-3289`) stamps only on rising edges; `_last_occupied_time` (`:3613`, `:3625`) includes the lighting timeout and is not refreshed under BLE hold. New `_last_hvac_evidence_time` + `get_last_hvac_evidence_time()` following the `get_became_occupied_time` accessor pattern (`:5384`). |
| Camera evidence read | **REUSE by extraction** | The loop at `coordinator.py:3667-3697` becomes helper `_camera_person_sensor_on() -> str | None`, called by the existing override and by the evidence stamp. No behaviour change to the override. |
| BLE evidence read | **REUSE by extraction** | The cap test at `coordinator.py:3811-3837` becomes a pure `_ble_cap_exceeded(now) -> bool`; the NM side effect stays in the block. |
| Room-change event source | **REUSE HA API** | `DataUpdateCoordinator.async_add_listener` on each room coordinator (HA `update_coordinator.py:170`). Prior-art usage pattern: `aggregation.py:1990` (`person_coordinator.async_add_listener`). No new dispatcher signal. REV 4's `binary_sensor.{entry_id}_occupied` trigger is REJECTED: it cannot see a re-arm while the lighting value is still `on`, which is the operator's premise case. |
| Listener lifecycle | **REUSE** | ONE `SIGNAL_ROOM_ENTRY_LIFECYCLE` subscription (`signals.py:199`; fired at `__init__.py:5081` loaded, `:5590` unloaded, `:7869` options_updated). Pattern: `presence.py:2624-2651`. |
| Zone-scoped decision | **REUSE + parameterise** | `_apply_house_state_presets` gains `zone_filter` and `trigger` keywords; `update_room_conditions` gains `zone_ids`. No copy of the S1 body. |
| Decision lock | **REUSE** | `_decision_cycle_lock` (`hvac.py:579`). |
| Task tracking | **REUSE** | `_track_task` (`hvac.py:1644`), `_pending_tasks` cancelled in teardown (`:5565`). |
| Exit timer | **BUILD (per-zone dict of one-shot timers)** | Pattern REUSE: `async_call_later` as used for the boot-settle kick. Nothing today schedules a decision at a computed instant. |
| Ledger surface | **REUSE** | `preset_change` row details (`hvac.py:3232-3269`) gain `trigger`, `edge_ts`, `zone_empty_since`. No new table, no new writer. |
| Counters / gauges | **REUSE entity** | `sensor.ura_hvac_coordinator_mode` attrs via `get_mode_attrs` (`hvac.py:5411`, `sensor.py:12082-12121`). REV 4 named `sensor.ura_hvac_coordinator_status`; that entity does not exist (grep of `sensor.py`). Per-zone attrs on the existing zone status sensor via `get_zone_status_attrs` (`hvac_zones.py:790`). |
| Per-room diagnostics | **REUSE entity** | `binary_sensor.<room>_<room>_hvac_occupied` attrs (`binary_sensor.py:826-920`), extended via `hvac_occupied_diag`. |
| Kill switch | **BUILD (one switch)** | Pattern REUSE: `HVACPreArrivalSwitch` (`switch.py:4229`, `SwitchEntity, RestoreEntity`, numbered name). No existing switch gates occupancy-triggered decisions (grep of `switch.py`). |
| Trip-wire notifications | **REUSE** | The NM path used by `_note_s1_reclaim` (`hvac.py:1653`) and `fire_stuck_signal` (`hvac.py:2513`). |
| Baseline probes | **REUSE** | `scripts/probes/hvac_fast_path_d0_probe.py` (room/zone/entity resolution), `hvac_raw_evidence_gap_probe.py`, `hvac_vacancy_grace_probe.py`. |

Memory bodies consulted: `feedback_suppression_needs_discharge`, `feedback_wire_in_anchor_mandatory`,
`feedback_hollow_test_anchors`, `feedback_marginal_benefit_pushback`, `feedback_measure_before_build`,
`feedback_coincidental_equality_masks_concept_split`, `project_zone_away_when_occupied_home_night_gap`,
`reference_hvac_state_of_play`.

---

## 1. Marginal-benefit note (recorded, operator has decided)

The 2026-09-26 audit concluded "for common_area and bedroom, the fix buys too little to justify a CRIT-1 revisit".
That weighed release speed alone. The operator's decision adds a second lever the audit did not price: with an
event-driven re-arm, the cost of a wrong release drops from "up to a tick of wrong away" to "two writes and seconds
of away". The pushback that remains is recorded in section 7 (residual) and section 10 D3 (the grace cannot safely
drop below 5 minutes without raising holds). The design below keeps the risky ingredient small: no new writer, no
new decision logic, the S1 body is reused as-is, and a kill switch reverts to tick-only in one flip.

---

## 2. Falsifiable invariants

Definitions. `ev(R)` = room R's last HVAC evidence time (section 4.1). `hold_day(R)` = per-room override if set,
else the type table. "Day" = house state not in `HVAC_NIGHT_HOLD_STATES`. `G` = live vacancy grace for the current
constraint mode. `release(R)` = `ev(R) + hold_day(R)` in day; at night, the unchanged night machine's tail end.
`E(Z)` = max `release(R)` over live non-hallway rooms of zone Z.

**INV-1 (the operator's premise, re-arm).** For an established zone Z whose house-state target is home or sleep:
(a) if raw evidence appears in any live non-hallway room of Z before Z's vacancy away write is issued, no vacancy
away write is issued for that vacancy episode; (b) if Z was written away by a `vacant_past_grace` write at `t_a`
and raw evidence then appears in a live non-hallway room of Z (room refresh at `t_r`, within about 2 s of the
sensor edge), S1 issues a home/sleep write for Z by `t_r + HVAC_FAST_PATH_SLA_S` (45 s). Allowed exceptions, each
with a named, logged refusal and the periodic tick (at most 300 s) as the backstop: kill switch off; zone tripped
by the ceiling; observation mode, zone intelligence off, or boot-settle; S1's own gates (W1-B four gates, consensus
defer, `arriving`, egress pause, D7).

**INV-2 (no early away, day).** In a day house state, S1 never issues a `vacant_past_grace` away write for zone Z
at time `t` while any live non-hallway room R of Z has `release(R) > t - G`. Falsified by any reachable path (fast
or periodic) that writes such an away.

**INV-3 (exact exit).** When no new evidence arrives, the day vacancy away write for Z (trigger `fast_exit`) is
issued in `[E(Z) + G, E(Z) + G + HVAC_FAST_PATH_EXIT_SLACK_S + HVAC_FAST_PATH_SLA_S]`, and at most once per
vacancy episode (keyed by `E(Z)`).

**INV-4 (no leak into other zones).** A fast run for zone Z issues climate writes only for Z, and only through the
S1 site. It never calls the heat_cool enforcer, the egress tick, `check_ac_reset`, fans, covers, the predictor,
anomaly observations, DPM overrides, the arrester sweeps, or the Carrier freshness check. It never changes
`room_conditions`, `last_occupied_time`, `continuous_occupied_since` or `current_session_start` of any other zone.

**INV-5 (night unchanged).** In `HVAC_NIGHT_HOLD_STATES` a room is HVAC-occupied at least whenever today's machine
(ride room `occupied` + night hold) says so. The night release can only be equal or later than today's.

**Equivalence (for reviewer B).** For zone Z at wallclock `t`, the preset decision a fast run makes equals the
decision a periodic cycle would make for Z at `t` given the same producer state and the same `runtime_exceeded`.

---

## 3. Producer and consumer map for `hvac_occupied`

### 3.1 Producer (today -> after)
| Step | Today | After |
|---|---|---|
| Input | Room `data["occupied"]` (lighting, grace-held, includes timeout, camera, BLE, overrides) `hvac_zones.py:717` | Day: `coordinator.get_last_hvac_evidence_time()`. Night: `data["occupied"]` (unchanged) |
| Arm | Rising edge of `occupied` on a pass `:1075` | Day: any pass with `now < ev + hold_day`. Night: unchanged |
| Hold | Tail starts at the first pass that sees `occupied` fall `:1111` | Day: from `ev` exactly. Night: unchanged |
| Pass cadence | 5-min tick + house-state/pre-arrival cycles | Same, plus zone-scoped fast runs (section 5) |
| Zone rollup | OR of rooms `:178-188`; `last_occupied_time = now` while fused `:771-773` | Same, plus back-fill `last_occupied_time = max(lot, E(Z))` when fused is False (section 4.4) |

**Dependency health.** The evidence stamp depends on the room coordinator refresh (event-driven within 2 s, poll
30-35 s) and on the fusion filters (stuck-sensor exclusion, fan gate, mmWave-demoted latch) that already shape
lighting occupancy. Camera: only the Living Room has a firing person sensor (audit §6). BLE: 3 phones, often
`unknown` (audit §6). All healthy as inputs; camera and BLE only lengthen holds.

### 3.2 Consumers (every one; trust vs display)
| Consumer | Site | Kind | Effect of this plan |
|---|---|---|---|
| Zone rollup `any_room_hvac_occupied` | `hvac_zones.py:178` | feeds all below | Flips sooner in day; re-arms on evidence |
| `conditioning_retreat_ok` -> row-1 vacancy away | `hvac_zones.py:1522`; `hvac.py:2339-2426` | TRUST | Main consumer; INV-2/INV-3 |
| Row-1 transient-room hold | `hvac.py:2360-2392`, `:2860-2911` | TRUST | Unchanged logic; runs inside fast runs for the origin zone |
| D6 stale failsafe (row 4) | `hvac.py:2437-2539` | TRUST | Shorter holds break `continuous_occupied_since` more often; failsafe fires less. Safer |
| D5 energy-shed coast defer | `hvac.py:2643-2709` | TRUST | Coast defer ends sooner when a zone empties. Shed unchanged. Pre-existing bypass reader (§9.4) unchanged |
| D7 night-trust | `hvac.py:2780-2852` | TRUST | Night unchanged (INV-5) |
| D9 compose-away (dormant) | `hvac.py:3484-3518` | TRUST | Not run by fast runs; tick only (non-goal) |
| Arrester row-10 comfort delay | `hvac_override.py:2513-2557` | TRUST | A comfort grant in an emptied zone expires sooner (intended) |
| Pre-cool F8 / pre-heat F9 | `hvac_predict.py:583`, `:1420` | TRUST | Tick only; sees shorter day holds |
| `last_occupied_time` / grace math | `hvac_zones.py:771-779`; `hvac.py:2340-2344` | TRUST | Back-fill makes grace count from the exact release |
| `zone_presence_state` | `hvac.py:4775-4820` | DISPLAY | Recomputed by fast runs too |
| W1-B four gates / `manual_guard_verdict` | `hvac.py:2918-2996`, `hvac_preset.py` | TRUST (consumes S1 intent, not occupancy) | Unchanged; fast runs go through the same S1 body |
| Fans | `hvac_fans.py:761`, `:997` | reads LIGHTING `.occupied` | Unaffected; fans stay tick-driven (card `HVAC-FAST-PATH-FAN-WARM-EDGES-1` stays parked) |
| Pre-arrival | `hvac.py:4567-4622` | writes `_pre_arrival_zones`, triggers a full cycle | Unchanged; the full cycle waits behind a fast run instead of being dropped (section 5.5) |
| Presence D6 source 4 | `presence.py:2147-2159` | reads LIGHTING `.occupied` | Unaffected |
| Per-room `binary_sensor.<room>_<room>_hvac_occupied` | `binary_sensor.py:745-920` | DISPLAY | New attrs `last_evidence_at`, `release_at`, `rule` |
| Zone status sensor attrs | `hvac_zones.py:790-894` | DISPLAY | New attrs `hvac_empty_since`, `away_due_at` |
| `sensor.ura_hvac_coordinator_mode` attrs | `hvac.py:5411` | DISPLAY | New fast-path counters and gauges |
| `optimization.py:2398-2430` | `continuous_occupied_since` | finding/analysis | Sees shorter continuous spans |

---

## 4. D1: HVAC's own release clock

### 4.1 Evidence stamp in the room coordinator (`coordinator.py`)
- New fields: `_last_hvac_evidence_time: datetime | None = None`, `_hvac_evidence_active_prev: bool = False`.
- New accessor `get_last_hvac_evidence_time() -> datetime | None` next to `get_became_occupied_time` (`:5384`).
- Extract `_camera_person_sensor_on() -> str | None` from `:3667-3697` (same area lookup, same `state == "on"`
  test). The camera override calls it; behaviour unchanged.
- Extract `_ble_cap_exceeded(now) -> bool` from `:3811-3837` (cap enabled AND `_ble_only_hold_since` set AND
  duration > cap). The BLE block calls it and keeps its NM and logs.
- **One stamp site**, immediately after the override-switch block (after `:4811`, before skip-first at `:4825`):
  ```
  evidence_now = (
      any_sensor_active                                     # post debounce, fan gate, demote latch, stuck filter
      or (grace_hold and self._last_occupied_state)         # sensor unavailability grace keeps holding
      or (not self._failsafe_fired and self._camera_person_sensor_on() is not None)
      or (BLE_CHAIN_HOLD_ENABLED and ble_persons_present
          and self._last_occupied_state and not self._ble_cap_exceeded(now))
      or self._is_override_occupied()
  ) and not self._is_override_vacant()
  if evidence_now or self._hvac_evidence_active_prev:
      self._last_hvac_evidence_time = now                  # falling-edge tick stamps too (conservative)
  self._hvac_evidence_active_prev = evidence_now
  ```
  `ble_persons_present` is read once per tick from `person_coordinator.get_persons_in_room(room_name)`, the same
  call the BLE block makes. `any_sensor_active` must be the value after all filters, exactly what drives lighting.
- **Why the falling-edge stamp:** the refresh that first sees the sensor off runs within about 2 s of the edge, so
  `ev` is at most about 2 s late (longer hold, safe) instead of up to 35 s early.
- **BLE semantics (decided):** BLE counts only while the chain is unbroken (room lighting-occupied on the previous
  tick) and the cap has not fired. That matches today's effective HVAC hold (today BLE keeps `occupied` true
  indefinitely through the chain leg) and preserves extend-not-create: BLE can never arm a cold room.
- **Override Vacant:** no evidence while on; the room releases at the last real evidence + hold (it "rides the
  hold", as §9c records, minus the lighting timeout). §9c text is updated in the build commit.
- Restart: in-memory; `None` until the first evidence, same as `_last_motion_time` today. Zones stay unestablished
  until every live room is seen (reset-only backstop), unchanged.

### 4.2 Release rule in the producer (`hvac_zones.py`)
`update_room_conditions` reads `ev` for each room (`getattr(coordinator, "get_last_hvac_evidence_time", None)`; if
the accessor is missing, the legacy rule applies. That fallback exists only for test fakes; a guard test asserts
the production class has the accessor). `_compute_hvac_occupied` gains `last_evidence: datetime | None` and branches:

- **Day** (`house_state not in HVAC_NIGHT_HOLD_STATES`):
  `hvac_occupied = last_evidence is not None and now < last_evidence + hold_day`.
  `_hvac_armed` mirrors the result; `_hvac_tail_until[room] = last_evidence + hold_day` while occupied (for the
  diag and for `release()`); `_hvac_arm_source` = `"evidence"` / `"released_evidence_expired"`. `_hvac_prev_state_occupied`
  is still updated so a day -> night switch starts the night machine from a correct edge state.
  The lighting occupancy timeout no longer takes part in the day release.
- **Night** (`house_state in HVAC_NIGHT_HOLD_STATES`): today's machine, byte-for-byte (`:1066-1123`), with
  `hold_s` = the night value. **OR** the day rule (`last_evidence + hold_day`). The OR is what keeps night never
  shorter than day (section 4.3).
- **Hallway:** unchanged (`:724-735`), still marked seen.
- **Per-room day override** `hvac_vacancy_hold` wins over the table, as today (`:1019-1020`).

**Arming decision.** Day arming goes on raw evidence: a room re-arms on new evidence even while its lighting value is
still `on`, which today's edge-based arm cannot do. This is required for INV-1. Night arming is unchanged (a
lighting rising edge always coincides with evidence). CRIT-1 at night is preserved exactly (INV-5): the night hold
still starts when the room itself goes empty, including its lighting timeout, camera and BLE holds. The Stage B
arming-persistence filter is NOT built here (section 12).

### 4.3 The numeric night >= day clamp is replaced by the OR
Raising `common_area` day to 300 would make the runtime clamp (`hvac_zones.py:1028-1044`) lift the 9 common rooms'
night `90` to `300`, undoing night-tail A and logging 9 warnings. The two holds now start from different anchors
(day from last evidence, night from the room going empty), so comparing their numbers is a coincidental-equality
trap (Bug Class #63). Replace the numeric clamp with the structural OR in section 4.2: night release =
`max(night machine release, ev + hold_day)`, which is never earlier than day. Also remove the config-flow
validation `hvac_hold_night_below_day` (`config_flow.py:599-610`) and its error string, because "night 90, day 300"
is now a legitimate, meaningful setting. `_effective_hvac_hold_seconds` keeps its signature and callers
(`hvac_zones.py:1100`, `binary_sensor.py:894`) and returns the raw day or night value.

### 4.4 Exact release instant for the grace
Today `last_occupied_time` is the last pass that saw the zone fused-occupied (`:771-773`), so the grace starts up to
one pass before the real release. New: on a pass where the zone is fused-empty, set
`zone.last_occupied_time = max(zone.last_occupied_time, E(Z))`, where `E(Z)` is the max `release()` over the zone's
live non-hallway rooms that are already `<= now`. This makes the 5-minute grace a real 5 minutes after the release.
Without it, the fast exit (INV-3) would fire up to one pass early and INV-2 would break.

Helpers (pure, sync, no side effects): `room_release_at(room_name) -> datetime | None` and
`zone_release_at(zone_id) -> datetime | None` (None when some room is held without a bound, e.g. night `occupied`
still on, or when the zone has no live rooms). `zone_away_due_at(zone_id, grace_s) = zone_release_at + grace_s`.

### 4.5 New day hold table (`const.py`, rung 1)
```
ROOM_TYPE_HVAC_HOLD: Final = {
    ROOM_TYPE_CLOSET: 60,          # audit §7: 0 MID zone retreats at any T
    ROOM_TYPE_INFRASTRUCTURE: 60,  # grouped with closet (audit §7)
    ROOM_TYPE_GENERIC: 120,        # max MID 396 s -> T >= 96
    ROOM_TYPE_UTILITY: 120,        # max MID 386 s -> T >= 86
    ROOM_TYPE_MEDIA_ROOM: 120,     # no data; keep today's value
    ROOM_TYPE_GARAGE: 120,         # no zoned garage; generic-like
    ROOM_TYPE_BATHROOM: 180,       # measured MID ZR = 0 from 180
    ROOM_TYPE_BEDROOM: 240,        # max MID 495 s -> T >= 195
    ROOM_TYPE_COMMON_AREA: 300,    # max MID 603 s -> T >= 303 (G = 300)
    ROOM_TYPE_HALLWAY: 0,          # circulation exclusion
}
```
The table must cover every `ROOM_TYPE_*` (test). `DEFAULT_HVAC_VACANCY_HOLD` (60) stays as the fallback for unknown
types. The Kitchen gets `common_area` 300; the audit's "keep today's behaviour for the Kitchen" exception is
overruled by the operator's decision (residual in section 7). The comment above the table must state the coupling:
**each type's hold plus the vacancy grace must stay at or above that type's measured max MID gap**
(common 603 s, bedroom 495 s, generic 396 s, utility 386 s).

### D1 acceptance
- **Test:** `test_day_release_is_last_evidence_plus_type_hold` (parametrised over every type).
- **Test:** `test_day_release_ignores_lighting_timeout` — `occupied=True` in `data`, evidence older than the hold ->
  `hvac_occupied False`. Mutation: restore the lighting ride in the day branch -> this test goes red. This is the
  discriminating anchor for the whole cycle.
- **Test:** `test_camera_person_refreshes_evidence_inside_lighting_timeout`, `test_ble_refreshes_evidence_only_with_chain_and_under_cap`,
  `test_ble_cannot_arm_cold_room`, `test_grace_hold_counts_as_evidence`, `test_override_occupied_is_evidence_override_vacant_is_not`,
  `test_falling_edge_refresh_stamps_evidence`.
- **Test:** `test_night_machine_unchanged` — scripted input sequence in `sleep` produces the same `hvac_occupied`
  series as the pre-change machine (golden series captured from `develop`, not hand-written).
- **Test:** `test_night_release_never_before_day_release` — config extremes: night 0 / day 300; night 90 / day 300;
  day 60 / night 5400; day 0 / night 0 (non-hallway).
- **Test:** `test_home_night_uses_day_evidence_rule` (with B merged).
- **Test:** `test_last_occupied_time_backfilled_to_exact_release`; `test_table_covers_every_room_type`;
  `test_per_room_day_override_wins`; `test_hallway_excluded_unchanged`; `test_night_below_day_now_accepted_by_flow`.
- **Test (updated, not deleted):** `test_zzz_hvac_conditioning_demand.py` table tests;
  `test_v5_103_8_hvac_knobs_and_obs.py::test_effective_hold_clamps_night_up_to_day_pure` becomes the OR test;
  `test_hvac_vacancy_hold_ui_defaults.py` if it pins day values.
- **Sensor:** `binary_sensor.kitchen_kitchen_hvac_occupied` attrs show `rule: day_evidence`, `last_evidence_at`,
  `release_at = last_evidence_at + 300 s`.
- **Live:** in a day state, for 10 consecutive day releases across at least 3 room types, recorder shows
  `*_hvac_occupied` off within `hold + 35 s` of `last_evidence_at` while `binary_sensor.<room>_occupied` is still
  `on` (the discriminator: under the old rule the HVAC value could never drop while the lighting value is on).

---

## 5. D2: event-driven decisions on entry and exit

### 5.1 Why not REV 4's whole-house cycle
REV 4 ran `_run_decision_cycle` off-schedule with an `origin_zones` write filter. Its second review failed on leaks
into other zones. This plan never calls `_run_decision_cycle` from an event. A fast run is a new, small method that
does only the zone's own occupancy decision:

```
async def _async_zone_fast_run(self, zone_id, trigger, edge_ts=None):
    # trigger in {"fast_entry", "fast_exit"}
    if not self._fast_path_gates_open(zone_id): return          # section 5.4 gates
    async with self._decision_cycle_lock:                        # waits behind a full cycle
        self._fast_path_running = True
        try:
            zm.update_zone_climate_state(zone_id)
            zm.update_room_conditions(house_state=self._house_state, zone_ids={zone_id})
            if not self._observation_mode:
                wrote = await self._apply_house_state_presets(
                    zone_filter={zone_id}, trigger=trigger, edge_ts=edge_ts)
            if self._zone_intelligence_enabled:
                self._compute_zone_presence_states(dt_util.utcnow())   # read-only, all zones
            self._schedule_exit_timer(zone_id)
            if wrote or fused_changed: async_dispatcher_send(self.hass, SIGNAL_HVAC_ENTITIES_UPDATE)
        finally:
            self._fast_path_running = False
            self._fast_path_queued.discard(zone_id)
```

### 5.2 `_apply_house_state_presets(*, zone_filter=None, trigger="periodic", edge_ts=None)`
- `zone_filter is None` (every existing caller): byte-identical behaviour.
- `zone_filter` set: skip the heat_cool enforcer loop (`:2227-2256`); `continue` at the top of the zone loop
  (`:2282`) for zones not in the filter; skip `_async_apply_preset_overrides` (`:3319-3320`). Honour the consensus
  defer gate, `arriving`, and every per-zone rule unchanged.
- `trigger` and `edge_ts` go into the `preset_change` details dict (`:3232-3269`), plus `zone_empty_since`
  (`last_occupied_time`) on away rows. `house_state` and `pre_arrival` full cycles keep `trigger="periodic"` in this
  cycle (no change to their callers).
- Return `True` when S1 applied a write (for the ceiling and the dispatch).

### 5.3 `update_room_conditions(house_state, zone_ids=None)`
- `zone_ids is None`: unchanged.
- `zone_ids` set: the per-zone loop (`:665`) skips other zones BEFORE `zone.room_conditions.clear()`, so sibling
  zones keep their room conditions and rollup fields untouched (INV-4).
- **The coordinator-absent set must stay pass-complete.** Today it is filled inside the zone loop (`:686`). Move
  the absent detection into the entry loop (`:610-646`), which already sees every room entry, so
  `is_zone_hvac_established` for a sibling zone never reads a partial set after a zone-scoped pass.
- `_classify_all_rooms` still runs over all rooms (read-only, queued events drain on the next full cycle).

### 5.4 Entry trigger (room coordinator listener)
At `async_setup`, for every loaded ROOM entry, attach `coordinator.async_add_listener(partial(self._on_room_refresh, entry_id))`.
Store the remove callables in `self._fast_path_room_unsubs: dict[entry_id, callable]`. One
`SIGNAL_ROOM_ENTRY_LIFECYCLE` subscription re-attaches on `loaded`, releases on `unloaded`, and does release-then-attach
on `options_updated` (idempotent).

`_on_room_refresh(entry_id)` (sync `@callback`), all short-circuit in this order:
1. `_tearing_down`, not enabled, boot-settle not done, kill switch off, observation mode, zone intelligence off -> return.
2. Resolve room name; skip hallways; resolve its zone from `zm.zones` LIVE (REV 4 F12); none -> return.
3. `ev = coordinator.get_last_hvac_evidence_time()`; if `ev` did not advance past `self._fp_last_ev[room]` -> return; store.
4. Zone-cold gate (REV 4 F4): if `zone.any_room_hvac_occupied` is True (last pass) -> return. A still-True stored
   value after an unobserved release is harmless: no away can have been written without a pass storing False.
5. Zone tripped by the ceiling -> count, return (tick backstop).
6. Per-zone limiter `HVAC_FAST_PATH_MIN_INTERVAL_S` on entry runs, **exempt when `zone.preset_mode == "away"`**
   (a re-arm write is due; this is the INV-1 case and must never be rate-limited).
7. Per-zone dedup: if `zone_id in self._fast_path_queued` -> return.
8. Queue: `self._fast_path_queued.add(zone_id)`; `self._track_task(hass.async_create_task(self._async_zone_fast_run(zone_id, "fast_entry", edge_ts=now)))`.

### 5.5 Lock rules (replaces REV 4's rerun machinery)
- Fast runs **wait** for the lock (`async with`) instead of skipping; `_fast_path_queued` stops pile-ups.
- `_async_decision_cycle` (periodic, house-state, pre-arrival, boot): if the lock is held by a fast run
  (`_fast_path_running`), wait instead of skipping. If held by a full cycle, skip as today. After acquiring,
  if a full cycle STARTED after this call was scheduled (`_last_full_cycle_started_at`), skip, so a waiting
  periodic never runs a second back-to-back full cycle (that would double-sample `check_ac_reset` and anomaly
  counters, REV 4 F3).
- Every producer mutation happens under `_decision_cycle_lock`. The producer is synchronous, so the only race it
  closes is a full cycle's zone loop awaiting mid-iteration while a fast run rewrites room conditions.

### 5.6 Exit timer
`_schedule_exit_timer(zone_id)` runs at the end of every full cycle (all zones) and every fast run (its zone):
- Preconditions: kill switch on, zone intelligence on, not observation mode, zone established, house target in
  (home, sleep), `zone.preset_mode != "away"`, not egress-paused, not tripped.
- `due = zm.zone_away_due_at(zone_id, grace_s) + HVAC_FAST_PATH_EXIT_SLACK_S` (the grace test is strict `>`,
  `hvac.py:2342-2343`). `None` -> no timer (tick backstop).
- **One-shot per vacancy episode.** Key = `(zone_id, zone_release_at)`. If `_fp_exit_fired[zone_id] == key`, do not
  schedule. This stops the §9.7 zone_1 feed-disagreement loop (the status feed reads `home` after an away write)
  from turning into a write every few seconds; re-issues stay on the tick as today.
- Replace an existing timer only if `due` changed. Store in `self._fast_path_exit_unsubs[zone_id]`.

Callback (sync): return if tearing down; recompute `due`; if `due > now + 1 s`, reschedule lazily (no run, no
counters); else record the fired key and queue `_async_zone_fast_run(zone_id, "fast_exit")`, exempt from the
per-zone limiter. While a zone stays occupied the timer re-fires about once per `hold + G` and only reschedules.

Cancel the zone's exit timer when a fast entry run finds the zone fused-occupied.

### 5.7 Ceiling, runaway guard, trip-wire, kill switch
- **Write ceiling:** fast-run writes per zone per rolling hour > `HVAC_FAST_PATH_MAX_WRITES_PER_ZONE_PER_HOUR` (6)
  -> one NM, zone falls back to tick-only until local midnight. Counts only runs where S1 applied a write (the
  Carrier call-rate bound). The periodic tick is unaffected.
- **Runaway guard:** fast runs per zone per rolling hour > `HVAC_FAST_PATH_MAX_RUNS_PER_ZONE_PER_HOUR` (30) -> same
  fallback + NM. Lazy timer reschedules do not count.
- **Quick-return trip-wire (measures the residual live):** a `fast_entry` run for a zone whose last `preset_change`
  was a `vacant_past_grace` away less than `HVAC_QUICK_RETURN_WINDOW_S` (900 s) ago increments
  `quick_returns_today[zone]`; at `HVAC_QUICK_RETURN_NM_PER_DAY` (8) one LOW NM per zone per day. This is how a
  too-short hold shows up, in code, with no soak watching.
- **Kill switch** `switch.ura_hvac_coordinator_31_fast_room_response` (default ON). OFF: listeners ignore events, exit
  timers are cancelled, behaviour is today's tick timing with the D1 clock still active. ON again: next full cycle
  reschedules timers.
- **Global limiter G: dropped (deliberate deviation from REV 4).** G existed to bound off-schedule whole-house cycles.
  Fast runs are zone-scoped, write at most one zone through S1, and are serialised by the lock; the per-zone write
  ceiling bounds Carrier calls. G also denied about 1 zone-cold edge per day, which would break INV-1.

### 5.8 Teardown
`async_teardown` sets `self._tearing_down = True` and, BEFORE its first `await` (the zone-state save at `:5575`),
releases every `_fast_path_room_unsubs` entry, cancels every `_fast_path_exit_unsubs` entry, and clears
`_fast_path_queued`. Fast-run tasks are in `_pending_tasks` and are already cancelled at `:5565`. Every callback
checks `_tearing_down` first (REV 4 F6).

### D2 acceptance
- **Test (premise):** `test_rearm_while_lighting_still_on_triggers_fast_entry` — room lighting `on`, HVAC released,
  zone written away; new evidence -> home write within one fast run. Mutation: switch the trigger back to the
  lighting binary sensor edge -> red.
- **Test:** `test_rearm_after_vacancy_away_bypasses_zone_limiter` (INV-1 b); `test_evidence_during_grace_prevents_away` (INV-1 a).
- **Test:** `test_fast_run_is_zone_scoped` — spies on heat_cool enforcer, `_egress_manager.async_tick`,
  `check_ac_reset`, `_fan_controller.update`, `_cover_controller.update`, `_predictor.update`,
  `_record_anomaly_observations`, `_async_apply_preset_overrides`, `sunset_immune_holds`, `_check_carrier_freshness`:
  zero calls. One mutation per spy (remove that site's skip -> the matching assertion goes red).
- **Test:** `test_fast_run_leaves_sibling_zones_untouched` (room_conditions, `last_occupied_time`,
  `continuous_occupied_since`, `current_session_start` identical before/after); `test_absent_set_pass_complete_under_zone_filter`.
- **Test:** `test_fast_decision_equals_periodic_decision` — seeded random zone states (occupancy, preset, manual +
  gates, house state, constraint mode): the fast run's S1 outcome for Z equals a periodic run's outcome for Z.
- **Test:** `test_exit_timer_fires_at_release_plus_grace` (INV-3 window); `test_exit_timer_lazy_reschedule`;
  `test_exit_timer_one_shot_under_feed_disagreement` (preset reads `home` after the away write: no second fast
  write; the tick re-issues as today); `test_exit_timer_cancelled_on_entry`.
- **Test:** `test_periodic_waits_behind_fast_run`, `test_periodic_skips_behind_full_cycle`,
  `test_waiting_periodic_skips_if_full_cycle_ran`, `test_fast_run_waits_and_dedups_per_zone`.
- **Test:** `test_listener_lifecycle_idempotent` (5 rapid options_updated -> one listener per room);
  `test_boot_settle_suppresses_fast_path`; `test_teardown_releases_before_first_await`;
  `test_tearing_down_guards_every_callback`.
- **Test:** `test_write_ceiling_trips_and_clears_at_local_midnight`; `test_runaway_guard`; `test_quick_return_counter_and_nm_latch`;
  `test_kill_switch_off_restores_tick_only`; `test_preset_change_row_carries_trigger_edge_ts_zone_empty_since`.
- **Test (config boundaries, Tier 3):** grace 0; grace 60; per-room day hold 0 on a non-hallway room; dwell 1
  (entry falls back to the tick, documented); constraint-mode grace switch while a timer is pending.
- **Sensor:** `sensor.ura_hvac_coordinator_mode` attrs `fast_entry_runs_today`, `fast_exit_runs_today`,
  `fast_writes_today`, `fast_limited_today`, `fast_tripped_zones`, `quick_returns_today`,
  `last_fast_edge_to_write_s`.
- **Live:** see section 9.

---

## 6. Latency budget (before -> after)

Assumptions: live grace G = 300 s, dwell 0, tick period 300.3-301.1 s (D0 audit §1), room poll 30-35 s, event
refresh within 2 s. "Today" exit derivation: the room's lighting value falls at `ev + timeout + r` (r up to ~35 s);
the next tick (0-300 s later) sees the fall and sets the tail; since tail <= 300 s and the tick period is slightly
over 300 s, the following tick both releases the room and clears the grace (`now - lot` = 300.x > 300). So today
the grace is absorbed by the tick quantization. Sanity check: Kitchen at its old 600 s timeout gives about 18 min
average, matching the operator's "15-20 min".

| Path | Today (live) | After |
|---|---|---|
| Entry into a cold zone | Wait for next tick + ~13 s cycle: avg ~2.5-3 min (median wait 142-181 s), worst ~5.5 min | Room refresh <= 2 s + one zone run: typically under 5 s; <= 45 s SLA when a full cycle holds the lock (~4 % of edges) |
| Re-arm after a wrong away | Next tick: avg ~2.5, worst ~5 min | Typically under 5 s; <= 45 s SLA; never rate-limited |
| Re-detected during grace | No away write | No away write (unchanged) |
| Exit, day, 300 s-timeout room | ~avg 12.8 min (range ~10-15.6) | Exactly hold + 5 min: closet/infra 6 min; generic/utility/media/garage 7; bathroom 8; bedroom 9; common 10 |
| Exit, day, 900 s-timeout room (Master Bath, Jaya Bath, Exercise) | avg ~22.8 min | bathroom 8 min; common (Exercise) 10 min |
| Exit, Kitchen | old 600 s timeout: ~17.8 min avg; stopgap 300 s: ~12.8 min | 10 min |
| Exit, night (sleep/waking) | Room timeout + night hold + tick quantization; grace absorbed | Same hold, same start; away lands exactly at hold end + 5 min, so up to ~5 min LATER than today (the grace becomes real; safer for sleepers) |

Each "after" exit figure adds about 2-5 s (evidence stamp resolution + slack + run).

---

## 7. Residual risk (quantified from the audit)

Source: `AUDIT_hvac_raw_evidence_gaps_2026_09_26.md` §2-§7, 6.74 days, 82.4 day-hours, G = 300 s.

| Class | Count at the new table | Today | Notes |
|---|---|---|---|
| MID zone retreat (evidence resumed within the room's old timeout; best proxy for a still person) | **0 / 6.74 d** | 0 by construction | Holds by construction because each type's T + G >= its max MID gap |
| MID, if Jaya's day override 60 is left in place | +2 / 6.74 d (Jaya Bedroom) | 0 | Fixed by D4 |
| LATE zone retreat (ambiguous: resumed within ~16 min) | **~31 / 6.74 d (~4.6/day)**: Kitchen 28, Dining 1, Master Bath 1, Jaya Bath 1 (bedrooms <= 1) | 0 by construction | 30/30 Kitchen events had evidence in another room (mostly Patio); a phone was in the room in 1/44. Most look like real departures |
| Night | unchanged | — | INV-5 |

- **What changes in the meaning of the count.** The audit called ZR an upper bound partly because it ignored the
  5-minute tick. The fast exit removes that tick, so ZR is now close to the expected rate (still an upper bound
  because camera, BLE and grace-hold evidence can only shorten gaps).
- **Not measured:** production fusion filters (stuck-sensor exclusion, fan gate, mmWave-demoted latch) can make
  production evidence less continuous than the audit's raw union; phantom radars (Patio 65 % duty, Master and Jaya
  Bedroom ~45 %) can make it more continuous. D0c re-probes; the quick-return trip-wire measures it live.
- **Cost of one wrong retreat:** one away write, then one home write within seconds of the person moving again
  (INV-1), plus the temperature drift during the away (LATE gaps end within ~16 min). Upper bound ~4.6 pairs/day =
  ~9 extra Carrier writes/day, against ~160/day W1-B added.
- **Write-rate bound:** fast-path writes <= 6 per zone per hour by the ceiling; entry writes replace tick writes
  one-for-one (same count, earlier).

---

## 8. D0: baselines and residual re-probe (read-only)

- **D0a (latency baseline).** Extend `scripts/probes/hvac_fast_path_d0_probe.py` with a `--latency` mode (REUSE its
  room/zone/entity resolution): per zone, over at least 3 occupied days (house occupied from 2026-09-27; earliest
  2026-09-30): entry = zone-cold room `*_occupied` rising edge -> `preset_change` home/sleep; exit = zone's last
  room raw-evidence end -> `vacant_past_grace` away. Report p50/p90/max. Expected from section 6: entry p50
  ~2.5-3 min; exit p50 ~12-13 min for 300 s-timeout zones.
- **D0b (write-rate baseline).** REV 4 F9 query on `ura_activity_log` `climate_write`, >= 3 full days from
  2026-09-26 15:25 CDT (earliest 2026-09-30). Verify the details column name against W1-A's writer before running.
- **D0c (residual at the exact table).** Re-run `hvac_raw_evidence_gap_probe.py --graces 300,600` with current
  config (Kitchen timeout 300, Jaya override both ways) and read ZR at each type's new hold. **Gate:** if any
  zone's day ZR at the new table exceeds 2x the audit figure (> ~64 per week), stop and go back to the operator.

D0 does not block build dispatch. D0a/D0b block the live acceptance comparison; D0c blocks deploy.

---

## 9. Live acceptance (discriminating)

| # | Check | Pass (fix working) | What a plausible failure looks like |
|---|---|---|---|
| L1 | Fast entry latency | >= 90 % of `preset_change` rows with `trigger=fast_entry` have `row_ts - edge_ts <= 45 s`; median < 10 s | Tick fallback: uniform 0-300 s, median ~150 s |
| L2 | Exit exactness | Every `vacant_past_grace` away row with `trigger=fast_exit` has `row_ts - zone_empty_since` in `[300, 350] s` | Tick: `[300, 600] s` spread; early fire: < 300 s (INV-2 break) |
| L3 | INV-2 on live data | For every day away row, each zone room's `release_at` attr (recorder) is <= `row_ts - 300 s` | Any room with a later `release_at` |
| L4 | Re-arm | For every quick return (away then evidence in the zone), a home/sleep `fast_entry` row within 45 s of `edge_ts` | Home write only at the next tick |
| L5 | No leak | During fast runs, zero `climate_write` rows for other zones and zero `B1_heat_cool_enforcer`, nudge, cover, fan actions stamped within the run window | Any off-zone write |
| L6 | Clock decoupled from lighting | Section 4 D1 Live: HVAC value drops while the lighting value is still `on` | HVAC value never drops before lighting |
| L7 | Night unchanged | In `sleep`, per-room `rule: night` and releases no earlier than the room's `occupied` off + night hold | Night release before that |
| L8 | Write rate | Per-zone `climate_write`/day <= D0b baseline + observed spread + 10/day; `fast_writes_today` <= 6/hour/zone; no ceiling trips | Ceiling trips, or a jump well past the residual bound |
| L9 | Quick returns | `quick_returns_today` summed over 7 days <= 2x D0c's prediction | Much higher: holds too short for real behaviour |
| L10 | Teardown / reload | After one room reload and one HA restart: exactly one listener per room (debug attr `fast_listener_count` = live room count), no `RuntimeError`, timers re-armed by the next full cycle | Duplicate or missing listeners |

Results go into the README as a `Validated <date>` table (CLAUDE.md rule).

---

## 10. D3: vacancy grace re-check (measure; knob only)

The grace is knob 48, `number.ura_hvac_coordinator_48_zone_vacancy_delay_minutes` (live 5). No code change.

- **Constraint from the audit (state it before measuring).** A MID gap can retreat a zone only if gap > T + G. At the
  new table the margins are: common 300 + G >= 603 -> **G >= 303 s**; bedroom 240 + G >= 495 -> G >= 255 s. So
  **the grace cannot drop below 5 minutes without raising the common-area hold by the same amount.** Lowering G is
  a trade between the two, not a free win.
- **Probe (after D1 + D2 live >= 7 days):** adapt `scripts/probes/hvac_vacancy_grace_probe.py` to read the new
  `preset_change` fields. Per zone, from each exact `zone_empty_since`, the time to the next evidence re-arm. For
  candidate G' in {2, 3, 4} min: extra away/home pairs per week (returns inside (G', G]) versus conditioning minutes
  saved (episodes with no return x (G - G')). Report alongside the matching hold increase needed to keep MID = 0.
- **Decision:** operator turns the knob (or not). No card-level code follow-up.

**Acceptance:** probe table in this doc's results section; operator decision recorded on the card.

## 10b. D4: clear Jaya Bedroom's day hold override (config)

At deploy, blank `hvac_vacancy_hold` (day) on Jaya Bedroom so it uses the bedroom default 240; keep night 5400. The
key is on the reload-suppression list (night-tail A precedent), so no reload.
- **Verify:** `.storage/core.config_entries` Jaya Bedroom options have no `hvac_vacancy_hold` (or `null`),
  `hvac_vacancy_hold_night: 5400.0`.
- **Live:** `binary_sensor.jaya_bedroom_jaya_bedroom_hvac_occupied` attr `hvac_vacancy_hold_s` = 240 in a day state
  and 5400 in `sleep`.

---

## 11. Tier: 3

**Why Tier 3 (each trigger fires):**
- It changes the still-person safeguard (CRIT-1 day release) — a comfort-and-cost decision where one wrong path
  retreats an occupied zone.
- It adds a new trigger into the decision-cycle lock and the S1 site, both shared primitives consumed by many paths;
  the failure mode is one missed path (REV 4's second review found exactly that: four leaks).
- History: this surface has had two failed plan reviews (REV 3/REV 4) and a parked build.

**Protocol:**
- **Two plan reviews before build:** (1) completeness: re-enumerate every S1 away path, every producer caller,
  every lock taker, every consumer in section 3.2, every place that writes `last_occupied_time`; (2) build
  prediction: section 11b plus whatever else a builder will misread.
- **Four build reviews, parallel, disjoint:** A local correctness (evidence stamp, release arithmetic, table,
  back-fill, timer math, config extremes); B integration and state machine (equivalence, lock rules, INV-4, W1-B
  gates, D5/D6/D7, §9.7 loop, restart, reload, teardown); C test authority by real per-site source mutation (each
  site in section 5 D2 and D1 tests, `.pyc` disabled, restore and status-check each drill); D adversarial
  completeness: falsify INV-1..INV-5 over the whole surface including pre-existing code (D5 coast bypass reader,
  reloading-room synthetic empty, egress, `arriving`, consensus defer, observation mode, pre-arrival, override
  switches, zone deletion via `SIGNAL_ZM_ZONES_UPDATED`), each leak with a legal-config repro.
- Orchestrator re-greps every S1 away path and re-runs the mutation on the day-rule anchor and the zone-scope anchor.
- **Operator checkpoint before deploy.**

### 11b. What a builder will most likely get wrong
1. Triggering on `binary_sensor.<room>_occupied` (REV 4) instead of the evidence stamp. That misses the premise case.
2. Calling `_run_decision_cycle` for a fast run, or forgetting to skip the heat_cool enforcer / DPM overrides under
   `zone_filter`.
3. Putting the zone filter AFTER `zone.room_conditions.clear()` in the producer, wiping sibling zones.
4. Leaving the coordinator-absent set filled only inside the filtered zone loop.
5. Forgetting the `last_occupied_time` back-fill, so the fast exit fires one pass early (INV-2 break).
6. Stamping evidence from `_last_motion_time` (misses camera/BLE) or only on rising edges.
7. Letting BLE evidence arm a cold room (breaks extend-not-create).
8. Rescheduling the exit timer after the away write when the status feed still reads `home` (§9.7 loop).
9. Rate-limiting the re-arm (limiter must be exempt when the zone preset is `away`).
10. Making a waiting periodic run a second back-to-back full cycle.
11. Keeping the numeric night >= day clamp, which silently lifts the 9 common rooms' night 90 to 300.
12. Releasing listeners or timers after the first `await` in teardown.
13. Threading `trigger` into a counter but not into the `preset_change` row (L1-L4 need it on the row).

---

## 12. Sequencing, coordination, supersession

- **Night-tail B first.** B edits `hvac_zones.py:1002/:1046` and the hold tests this plan also touches. Build this
  cycle on `develop` after B merges; reuse `HVAC_NIGHT_HOLD_STATES`. If B is not merged, this plan's "night" means
  B's set anyway (do not fall back to `FAN_TRUST_STATES`). Night-tail §L label changes to the two hold fields are
  superseded by section 14 below.
- **`HVAC-ENTRY-DWELL-ROOM-CLOCK-1` (Stage B): partly superseded.** Its release half (a 10 s transit holding a room
  ~5 min + tail, C24) is absorbed here: the day release now runs from raw evidence. Its arming half (arm only after
  raw evidence persists N s, to filter transits) is NOT built here and stays on the card, re-based on the new
  evidence stamp, still gated on the flap measurement. With dwell 0 and fast entry, a zone-cold transit writes home
  in seconds and away after hold + 5 min: the same two writes as today, less conditioning time.
- **REV 4 plan (`PLANNING_hvac_w2_occupancy_fast_path.md`):** superseded by this plan; add a banner pointing here.
- **`HVAC-OCCUPANCY-HOLD-CHAINED-AFTER-LIGHT-TIMEOUT-1`:** this cycle.
- **`HVAC-HOLD-SIZING-ALL-ROOMS-1`:** its probe re-run ("after the fast path ships") becomes D3/L9 input.
- **`HVAC-FAST-PATH-FAN-WARM-EDGES-1`:** stays parked; fans are untouched.
- **`HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1`:** unchanged exposure; fast runs keep the establishment gate.
- **`HVAC-WRITE-CONFIRMATION-ORACLE-1`:** the one-shot exit timer keeps the §9.7 loop at tick cadence.
- **W1-A baseline:** D0b needs >= 3 days (earliest 2026-09-30).

---

## 13. REV 4 findings and the failed re-review: disposition

| Item | Disposition here |
|---|---|
| Re-review HIGH: whole-house off-schedule cycle | Fast runs never call `_run_decision_cycle` (section 5.1) |
| Re-review HIGH: wrong-zone reruns | No rerun label; per-zone `_fast_path_queued` + wait-for-lock (5.5) |
| Re-review HIGH: heat_cool / egress / fan / cover writes | Not called by a fast run; test `test_fast_run_is_zone_scoped` (5.2, D2) |
| Re-review HIGH: sibling-zone wake-ups | Producer zone filter before `clear()`; pass-complete absent set; S1 origin-only (5.3) |
| F1 dwell follow-up, F7 pop-before-dispatch, F8 follow-up tag | Dropped: dwell is 0 live; dwell > 0 now means "wait for the tick" and is documented on the knob (non-goal) |
| F2 origin_zones | Replaced by the zone-scoped run |
| F3 count-coupled skips | Moot: those sites are never called; waiting periodic skip rule prevents double full cycles |
| F4 zone-cold gate on the fused value | Kept (5.4 step 4) |
| F5 lock ahead of DENY / rerun | Replaced by wait-for-lock rules (5.5) |
| F6 teardown before first await | Kept (5.8) |
| F9 write-rate baseline query | Kept (D0b) |
| F10 hard ceiling | Kept, re-based on writes per zone; plus runaway guard (5.7) |
| F11 line refresh | Done against b2868c0d1 |
| F12 zones read live | Kept |
| F13 one lifecycle subscription | Kept |
| F14 trigger on the ledger row + SLA consumer | Kept; the SLA gauge lives on `sensor.ura_hvac_coordinator_mode` (the named `_status` sensor does not exist) |
| F15 anomaly observation | Moot: not called by fast runs |
| Global limiter G | Dropped (5.7) |

---

## 14. Knobs (ladder) and labels

### 14.1 Knob ladder
| Number | Value | Rung | Why |
|---|---|---|---|
| `ROOM_TYPE_HVAC_HOLD` values | section 4.5 | 1 (`const.py`) | Measured-safe from a probe; changing them reopens CRIT-1, so review required. Per-room override (rung 2) exists |
| `HVAC_FAST_PATH_MIN_INTERVAL_S` | 60 | 1 (`hvac_const.py`) | Per-zone entry-run floor; D0: 0/114 zone-cold edges denied; exempt for re-arm |
| `HVAC_FAST_PATH_SLA_S` | 45 | 1 | Observability target: p95 cycle proxy 27.6 s + headroom. Consumer: `last_fast_edge_to_write_s` |
| `HVAC_FAST_PATH_EXIT_SLACK_S` | 2 | 1 | Clears the strict `>` grace test |
| `HVAC_FAST_PATH_MAX_WRITES_PER_ZONE_PER_HOUR` | 6 | 1 | Carrier call-rate bound; min flap period is hold + grace >= 6 min |
| `HVAC_FAST_PATH_MAX_RUNS_PER_ZONE_PER_HOUR` | 30 | 1 | Runaway guard for a producer/listener disagreement |
| `HVAC_QUICK_RETURN_WINDOW_S` | 900 | 1 | Audit: LATE gaps resumed within ~16 min |
| `HVAC_QUICK_RETURN_NM_PER_DAY` | 8 | 1 | ~2x the audit's ~4.6/day upper bound house-wide, applied per zone |
| Fast room response switch | ON | 3 (switch) | Tier-3 rollback lever without a deploy. OFF = tick-only timing; the D1 clock stays |
| Vacancy grace (knob 48) | 5 min | 3 (existing) | D3 decides; see its coupling with the holds |

### 14.2 Label style guide (user-facing text)
Rules: the config-flow label is a short phrase; the helper is plain sentences; entity names are 3 words max
(after the HVAC numbering prefix); no jargon (not: tail, HVAC-occupied, clamp, gate, evidence, tick, fast path,
debounce, CRIT, fused, rung).

**Room options, climate step (`strings.json` and `translations/en.json`, identical):**
- `hvac_vacancy_hold` label: `Empty-room hold (day)`
- `hvac_vacancy_hold` helper: `How many seconds heating and cooling keep treating this room as occupied after the last sign of someone in it, such as motion, presence, a camera or a phone. This covers people sitting still. Leave blank to use the default for this room type: 1 minute for closets, 2 minutes for utility and media rooms, 3 for bathrooms, 4 for bedrooms and 5 for living areas. Enter 0 to never hold.`
- `hvac_vacancy_hold_night` label: `Empty-room hold (night)`
- `hvac_vacancy_hold_night` helper: `The hold used while the house is asleep or waking up. It starts only when the room itself shows as empty, so sleepers who lie still get extra time. Leave blank to use the default for this room type: 30 minutes for bedrooms and media rooms, 15 for living areas, 10 for bathrooms, garages and utility rooms, and 5 for closets. It can be shorter than the day hold.`
- Remove the error `hvac_hold_night_below_day`.
- Section name `climate_backstop`: `Thermostat and empty-room hold`

**HVAC coordinator options (existing fields, helper text only):**
- `hvac_vacancy_grace_minutes` helper: `Minutes a zone waits after its last room empties before heating and cooling switch to Away. If someone comes back sooner, nothing changes. Going below 5 minutes can switch a zone to Away while someone sits still in a living area.`
- `hvac_zone_entry_dwell` helper: `Minutes a zone must stay occupied before heating and cooling switch it from Away to Home. At 0, the switch happens within seconds of someone arriving. Above 0, it waits for the next regular 5-minute check.`

**New switch:** entity name `31 · Fast Room Response` (entity `switch.ura_hvac_coordinator_31_fast_room_response`,
`unique_id` `{DOMAIN}_hvac_fast_room_response`). There is no config-flow field for it.

**Notifications (NM):**
- Write ceiling, title: `Fast room response paused for {zone}`; message: `{zone} changed its heating and cooling setting {n} times in the last hour. Fast response is off for this zone until midnight. The regular 5-minute check still runs.`
- Quick returns, title: `{zone} keeps switching to Away too soon`; message: `{zone} switched to Away and someone was back within 15 minutes {n} times today. The empty-room hold for a room in this zone may be too short.`
- Runaway guard, title: `Fast room response paused for {zone}`; message: `{zone} ran more checks than expected in the last hour. Fast response is off for this zone until midnight. The regular 5-minute check still runs.`

**Acceptance:** `strings.json` and `en.json` match; a banned-word check over the changed strings finds none of the
jargon list above; JSON parses; hassfest passes.

---

## 15. Files

| File | Change |
|---|---|
| `custom_components/universal_room_automation/const.py` | `ROOM_TYPE_HVAC_HOLD` values + full coverage + coupling comment |
| `.../coordinator.py` | Evidence stamp, accessor, `_camera_person_sensor_on`, `_ble_cap_exceeded` extractions |
| `.../domain_coordinators/hvac_zones.py` | Day/night branches in `_compute_hvac_occupied`; `zone_ids` filter; pass-complete absent set; back-fill; `room_release_at` / `zone_release_at` / `zone_away_due_at`; clamp removal; diag + zone attrs |
| `.../domain_coordinators/hvac.py` | Listeners + lifecycle; `_on_room_refresh`; `_async_zone_fast_run`; exit timers; lock rules; `_apply_house_state_presets(zone_filter, trigger, edge_ts)`; ceiling/guard/trip-wire; teardown; `get_mode_attrs` |
| `.../domain_coordinators/hvac_const.py` | Section 14.1 constants |
| `.../binary_sensor.py` | `last_evidence_at`, `release_at`, `rule` attrs |
| `.../switch.py` | `31 · Fast Room Response` |
| `.../config_flow.py` | Remove the night < day validation |
| `.../strings.json`, `.../translations/en.json` | Section 14.2 |
| `quality/tests/` | New `test_hvac_fast_occupancy_response.py`, `test_hvac_evidence_clock.py`; updates listed in D1 |
| `scripts/probes/` | `hvac_fast_path_d0_probe.py --latency`; `hvac_vacancy_grace_probe.py` adaptation |
| `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` | §1, §2 trigger table, §3.1-§3.2, §8 live values, §9.5, §9c, §9d, header (same commit) |
| `docs/planning/PLANNING_hvac_w2_occupancy_fast_path.md` | Superseded banner |
| `docs/readmes/README_v5.103.<n>.md` | PATCH bump (not a new capability class; per convention a MINOR is arguable — orchestrator decides) |

---

## 16. Non-goals
- No change to night hold values, night anchor, or `HVAC_NIGHT_HOLD_STATES` (night-tail B owns that).
- No Stage B arming-persistence filter.
- No fan, cover, predictor, egress, arrester, DPM or D9 change; fans stay tick-driven.
- No change to `HVAC_DECISION_TICK`, the vacancy grace value, or the dwell value.
- No REV 4 dwell follow-up; dwell > 0 means the entry waits for the tick (documented).
- No change to hallway exclusion or to Override Occupied/Vacant semantics beyond "Vacant rides the hold from the last evidence".
- No new table, DB writer, sensor, or dispatcher signal.
- No fix for §9.4 placeholder readers or §9.7 feed disagreement (only: do not amplify §9.7).
- No per-zone decision for D9 compose-away while it is dormant.

## 17. Not done from the requested scope
- The REV 4 second-review text is not on disk; section 13 answers the four HIGHs as summarised on the card. The
  completeness plan reviewer should confirm with the orchestrator that nothing else was in that review.
- Night-anchor unification (night hold from last evidence) was considered and PARKED: the night-sleeper probe
  measured gaps on the HVAC value, so the raw-evidence margin for Jaya's 5400 s is unknown. Revival trigger: a
  raw-evidence night probe shows every bedroom's max still-sleeper gap under its night hold with >= 15 min margin.
