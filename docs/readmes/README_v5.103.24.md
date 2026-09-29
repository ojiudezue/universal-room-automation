# v5.103.24: one "Fan Mode" per room decides who runs its fan; no thermostat writes while a thermostat is offline; a nudge no longer puts back an ended pre-cool; an override no longer cancels the AC-reset restore

**Batch D.** Branch `feature/hvac-batch-d` (from `develop` @ `ef836342a`, which includes v5.103.23). **Tier 2** (two framing-disjoint reviews follow the build). Not deployed.

**Cards / items**
1. PRIORITY: the HVAC fan controller ignored the room's fan settings. A guest was failed on 2026-09-28. Scope grew by operator ruling **option C**: one per-room **Fan Mode** replaces the two toggles.
2. `HVAC-WRITES-WHILE-THERMOSTAT-UNAVAILABLE-1`.
3. INFO-1, operator ruling **"B"**: the nudge restore after a person ends the borrow underneath it.
4. `HVAC-ARRESTER-EPISODE-CANCELS-AC-RESET-RESTORE-1`. `fix/arrester-episode-keeps-ac-reset-restore` @ `0297b1afc` is folded in. Review record: `docs/reviews/code-review/arrester_episode_keeps_ac_reset_restore.md`.

---

## 1. Fan Mode — who runs a room's comfort fan (item 1)

### What went wrong
Guest Bedroom 2 had `fan_control_enabled: False` and `hvac_coordination_enabled: False`. The operator turned the room's Comfort Fan Control switch OFF at 2026-09-28 17:31. The HVAC-tier fan controller still ran `fan.fan_switch_4`:
- 20:25 and 21:15: fan_off;
- 23:43 and 03:09: sleep-onset fan_on;
- 06:01: fan_off.

The cause: `hvac_fans.discover_fans` registered every HVAC-zone room that has fans, and no HVAC-tier writer read either toggle.

It was not only that room. In the 7 days to 2026-09-29, the HVAC tier also wrote to Guest Bedroom 1 (4 fan_off) and Ziri Bedroom (5 fan_off). Both have `hvac_coordination_enabled` False. Guest Bedroom 1 and Jaya Bedroom (Comfort on, HVAC-managed off) were **dual-controlled**: the room tier ran them too.

### The rule (operator ruling option C)
There is ONE per-room setting, **Fan Mode**:
- Entity: `select.<room>_fan_mode`, unique_id `<room entry_id>_room_fan_mode`, named "Fan Mode".
- Knob rung 3: live-tunable from the dashboard, so a guest room can be turned off fast.
- Stored in the room entry's options as `room_fan_mode`, a reload-suppressed key. A change takes effect on the next tick with no room reload.
- The Fan Mode feeds `const.fan_owner()`, the one helper every fan writer uses.

| Fan Mode | Owner | HVAC tier (temp path, sleep-onset, zone sweep, pre-arrival fans, HVAC-level fan kill) | Room tier (°F thresholds, room sleep-onset, reconciler) | Fan recheck (presence tier: pause → check → restore) |
|---|---|---|---|---|
| **Follow thermostat** | `hvac` | **runs it**: zone setpoint + fan assist | stands down while the HVAC tier runs the room. Takes over as "Room temperature" if it does not (HVAC coordinator off, or room not in an HVAC zone) | **yes**, through the FanController |
| **Room temperature** | `room` | never touches it | **runs it** | **yes**, through the FanController (the snapshot uses the fan's physical state). This applies only to rooms in an HVAC zone: a room outside any HVAC zone has no FanController entry, and the recheck abandons it (`no_managed_fan`) as before |
| **Off** | none (person-owned) | never touches it | never touches it | **never** (no pause, no restore) |

- **Follow thermostat is offered only to a room in an HVAC zone.** An HVAC zone is a Zone Manager zone with a `zone_thermostat` whose `zone_rooms` lists the room (`const.room_in_hvac_zone`, the same source HVAC discovery uses).
- Other rooms get **Room temperature / Off** only, in both the select and the options-flow dropdown.
- **Stored "Follow thermostat" that is no longer possible** (room removed from its zone): the select shows **Room temperature**, and the room tier runs it that way. ONE warning is logged per restart by the room tier ("Fan Mode is 'Follow thermostat' … running it as 'Room temperature'"). The stored value is kept, so re-adding the room to a zone restores it. Nothing is hidden: the select state says what actually runs.
- **Humidity / exhaust fans are out of scope.** They are always room-tier (`handle_humidity_based_fan_control`) and keep their own "Humidity Fan Control" switch.

### Changing the mode while a fan is running
Decided 2026-09-29, and pinned by `test_mode_set_to_off_releases_without_forcing_the_fan_off`.
- When a room leaves "Follow thermostat", the HVAC tier **releases** its tracking (`is_on`, trigger, speed, timers) and **does not turn the fan off**. The person's device is left exactly as it is.
- `turn_off_all_managed` (the HVAC coordinator-level Fan Control switch) is never called per room on a change. When it does run, it now switches off only fans whose owner is `hvac`.
- Back to "Follow thermostat": a fan that is physically on is adopted like any externally-lit fan (manual-ON hold), not forced off.
- A person turning the fan off while it is unmanaged opens no URA cooldown.

### Every HVAC-tier fan writer and its gate (live read at actuation)
| Site | Where | Gate | Drill (§4) |
|---|---|---|---|
| G0 discovery | `hvac_fans.discover_fans` :414 | keeps **every** zone fan room registered, because `_room_fans` is the recheck's write registry. It snapshots `hvac_managed` | covered by G1a/G2 |
| G1 chokepoint | `hvac_fans._set_fan_state` :1722 (`_allowed` :1769/:1771) | HVAC's own writes need `hvac`; recheck pause/restore need owner ≠ None | G1a, G1b |
| — temp on / off / speed | `FanController.update` → `_set_fan_state` | G2 + G1 | G2 |
| — external sync / adoption | `FanController.update` :642 | G2 (skip, so no cooldown or hold is opened from a person's own use) | G2 |
| — sleep-onset burst | `_sleep_onset_activation` :980 (eligibility :1030; a suppressed ON is no longer booked on :1130) | G3 + G1 | G3, G3b |
| — HVAC-level fan kill | `turn_off_all_managed` :532 → `_set_fan_state` | G1 | G1a |
| — recheck pause | `pause_for_recheck` :2053 → `_set_fan_state` | G1 (owner ≠ None) | G1b, G4b |
| — recheck restore (ON + preset / oscillate / direction) | `restore_after_recheck` :2095 (gate :2109) | G4: owner ≠ None; the attribute writes bypass the chokepoint | G4 |
| zone vacancy sweep (fans) | `hvac.py _execute_vacancy_sweep` :5744 | G5 `hvac_tier_owns_room_fans`: owner `hvac` AND registered by the FanController | G5, G5b |
| pre-arrival fan off | `hvac.py _deactivate_zone_fans` :6270 | G6 (same helper) | G6 |
| pre-arrival fan on | `hvac_predict._activate_zone_fans` :1500 | G7 (same helper); skipped rooms show `reason: not_hvac_managed` | G7 |
| smoke / CO safety stop | `hvac.py _safety_stop_one_fan` :5598 | **intentionally NOT gated** (safety beats preference) | — |

Other consumers of the same helper:
- **Room tier:** `automation.handle_temperature_based_fan_control` :1900 and `automation._is_hvac_managing_fans` :2891. The latter now derives from `fan_owner`, not the raw `hvac_coordination_enabled`.
- **Reconciler:** `actuator_reconciler._resolve_fan` :844.
- **Recheck eligibility:** `presence_fan_recheck._evaluate_eligibility` :472 and `_still_armed_eligible` :957.

This closes the seam FAN-RECHECK-GATE-HARDENING. The recheck keyed only on Comfort; it now follows the owner.

### Migration (one-time, per room, at setup)
The migration is `__init__._migrate_room_fan_mode` :1762, called at :1834. It runs after the zone sync and before any update listener.
- `hvac_coordination_enabled` on → **Follow thermostat**. If the room is not in an HVAC zone → **Room temperature**.
- else `fan_control_enabled` on → **Room temperature**.
- else → **Off**.

The legacy keys stay readable for one release: `const.room_fan_mode` falls back to them while `room_fan_mode` is absent. The options flow no longer shows them.

The 12 fan rooms, from the live `.storage` on 2026-09-29. All 12 are in an HVAC zone. The expected result is pinned by `test_migration_of_the_live_fan_rooms`.

| Room | hvac_coordination | fan_control (merged) | → Fan Mode | Behaviour change vs v5.103.23 |
|---|---|---|---|---|
| Study A | on | on | Follow thermostat | none |
| Living Room | on | on | Follow thermostat | none |
| Master Bedroom | on | on (data; options absent) | Follow thermostat | none |
| Kitchen | on | on | Follow thermostat | none |
| Game Room | on | on | Follow thermostat | none |
| Guest Bedroom 1 | off | on | Room temperature | HVAC tier stops (was dual control with the room tier) |
| Jaya Bedroom | off | on (options) | Room temperature | HVAC tier stops (was dual control); fan recheck still works |
| Guest Bedroom 2 | off | off (options) | Off | **HVAC tier stops (the incident)** |
| Breakfast Nook | off | off | Off | HVAC tier stops. Its fan `fan.151732606487193_fan` is shared with Kitchen, which still runs it |
| Ziri Bedroom (Bedroom 5) | off | off (options) | Off | HVAC tier stops |
| Media | off | off | Off | HVAC tier stops |
| Exercise Room | off | off | Off | HVAC tier stops |

**Recheck impact:** in the 14 days to 2026-09-29, fan recheck ran only in Game Room, Living Room and Study A. All three stay "Follow thermostat" and are unchanged.

### UI
- **Options flow**, Climate & Fans: a **"Fan mode"** dropdown at the top replaces "Enable HVAC-Managed Fans" and "Enable Comfort Fan Control".
  - Helper text: "Who controls this room's comfort fan: the thermostat zone, this room's own temperature settings, or nobody (you control it)."
  - The fan start and speed temperatures are described as "Used only when Fan mode is Room temperature".
- **New-room flow:** the same dropdown. Default **Off**. It offers Follow thermostat only when the chosen zone has a thermostat. The speed step follows only for Room temperature.
- **Retired:** `switch.<room>_comfort_fan_control` (RoomComfortFanControlSwitch). Its registry entry stays as "unavailable" until you remove it (Bug Class #46: code never deletes registry entries).

### Climate Automation switch — decision: NOT gated here (needs your ruling)
`switch.<room>_climate_automation` is "enable/disable climate-specific automation". It is disabled-by-default. Its only consumer is the room-tier temperature fan path (`coordinator.py:4970`).
- **Why it is not a gate here:** the live states conflict with the rooms' fan settings. Climate Automation is OFF on Master Bedroom and Kitchen (both HVAC-managed, Comfort on), and on Guest Bedroom 1, Jaya, Ziri, Breakfast Nook and Guest Bedroom 2 (restore_state, 2026-09-29). Gating the HVAC tier on it would silently stop the fans in your own bedroom and the kitchen tonight.
- **A latent bug to know about:** the room-tier reader builds the entity id from the room name (`switch.{room_slug}_climate_automation`). Guest Bedroom 2's real entity is `switch.upstairs_guestroom_climate_automation`, so that room's switch is never read.
- **Proposal:** retire it into Fan Mode, where "Off" already means "URA leaves this fan alone". Alternatively, make it a real room-wide climate kill switch (read by unique_id through the entity registry). Pending your call.

## 2. No thermostat writes while a thermostat is offline (item 2)
- On 2026-09-28 from 14:24 to 17:21 all three climate entities were unavailable during a run of restarts. zone_1 took 37 `B1_heat_cool_enforcer` writes with `values_before.hvac_mode = unavailable`, plus an S1 `away` write every tick.
- `ZoneState` keeps stale (or boot-default) values while the entity is unreadable, so both sites re-sent the same write on every tick.
- **Fix:** `HVACCoordinator._climate_unreadable` (`hvac.py` :2379) reads the **live** entity state. It is used at the heat_cool enforcer (:2578) and at S1 before its suppress stamp and write (:3552).
  - `unavailable` or `unknown` (`HVAC_CLIMATE_UNREADABLE_STATES`, `hvac_const.py` :513, rung 1, HA state vocabulary): no write, no suppress stamp, no write bookkeeping.
  - The first readable tick writes as normal.
- **One INFO line plus one `ura_activity_log` row `climate_write_held_unreadable` per outage episode** (details: `state`, `since`, `sites`). The end of an outage is logged at DEBUG.
- A missing entity (state `None`) is not treated as an outage (it is a config gap). A failed read counts as readable, so behaviour is unchanged.
- **Site guards, not a funnel guard.** W1-B's constraint is "nothing added to the emit_* funnels". A funnel-level refusal would also have changed every borrow restore's semantics (S4/S6/S7/S11/S13…), which was out of scope.

## 3. The nudge restore after a person ended the borrow under it (item 3, ruling "B")
- **The situation:** a person changes the setpoint while a nudge runs on top of a live non-nudge borrow. D13 applies: the nudge wins and is not ended. v5.103.23 D-L3 ends the borrow (`human_interrupt`) and latches the zone.
- **The problem:** the nudge's snapshot was taken on top of the borrow (`manual` plus its pre-cool setpoints). So S6 wrote the ended borrow's `original_target` back as a raw setpoint, and S7 pinned `manual`.
- **Now:**
  - `_handle_climate_change` records the zone (`hvac_override.py` :3850). It sets an arrival flag when the ended borrow was an `S12_pre_arrival`.
  - `_restore_after_nudge` (:5875, reference pop :5928) **skips S6** and pins, via S7 (:6002), the zone's **current S1 target preset**: `get_preset_for_house_state`.
  - For an interrupted pre-arrival it pins the **arrival target** (Q7): Sleep in sleep/waking, else Home, never Away.
  - Presets only. The reasons are `soft_nudge_restore_s1_target` and `soft_nudge_restore_arrival_target`. With no resolvable reference, nothing is written.
  - The record is dropped at every new nudge start (:5632) and at teardown.
- Nudges without an ended borrow underneath are unchanged (pinned by a control test).

## 4. The arrester no longer cancels the AC-reset restore (item 4)
- Cherry-picked cleanly onto v5.103.23 (`3e53b30ac`, `5ee400249`, `40f93e9ae`), with the Co-Authored-By trailers stripped.
- The three call sites (`hvac_override.py` :2606, :4261, :4335) all use `_cancel_arrester_timers` (:7940).
- `git grep _cancel_zone_timers -- custom_components quality/tests` returns docstring mentions only.
- The merge-step doc checklist is applied (`a730f276e`): B-L3 is recorded as FIXED in README_v5.103.23, PLANNING_hvac_w1_w2_finish and the v5.103.23 review record.
- Its tests pass, and its two recorded drills were re-run (X1, X2 below).

## 5. Tests and drills

**New test files:**
- `test_hvac_batch_d_fan_ownership.py` (32): the real FanController, one room per mode, plus the const helpers.
- `test_hvac_batch_d_fan_mode_select.py` (13): the real `RoomFanModeSelect` class body, the real `_migrate_room_fan_mode` and the real `_fan_mode_selector`, exec-extracted and run against the real const; plus wire-in anchors and translations.
- `test_hvac_batch_d_unreadable_thermostat.py` (6): the real `_apply_house_state_presets` on the W1-B harness.

**Batch D sections added to existing files:**
- `test_fan_oracle_w11_w12_behavioral.py` (G5–G7);
- `test_comfort_fan_away_veto_behavioral.py` (room tier + reconciler per mode);
- `test_fan_recheck_mode2_cycle.py` (recheck per mode);
- `test_hvac_w1w2_finish_part_a.py` (item 3).

**Fixture updates:** fixtures that model an HVAC-managed room now carry `hvac_coordination_enabled` (with the legacy fallback). Four AST-slice loaders gained the `_CONF_ROOM_FAN_MODE` alias. The DPM label guard allow-lists the retired keys.

**Per-site mutation drills** (bytecode off, `__pycache__` cleared, one site at a time, restored byte-for-byte; `git status` clean after every run):

| Drill | Site neutered | RED |
|---|---|---|
| G1a | chokepoint HVAC-own gate → True | `test_chokepoint_hvac_own_write_needs_follow_thermostat[Jaya/Guest]`, `test_turn_off_all_managed_leaves_unmanaged_fans_on` |
| G1b | chokepoint recheck gate → True | `test_chokepoint_recheck_write_follows_owner[Guest]`, `test_recheck_off_zero_writes` |
| G2 | update() loop gate removed | `test_update_temp_path_only_for_follow_thermostat`, `test_update_does_not_adopt_person_owned_running_fan` |
| G3 | sleep-onset eligibility gate removed | `test_sleep_onset_only_for_follow_thermostat` |
| G3b | sleep-onset `if not dispatched` removed | `test_sleep_onset_suppressed_on_is_not_booked` |
| G4 | restore gate → False | `test_restore_skipped_when_mode_set_to_off_mid_recheck` |
| G4b | physical-state snapshot → False | `test_recheck_room_temperature_pause_and_restore_work` |
| G5 | vacancy-sweep gate → False | `test_batch_d_g5_vacancy_sweep_only_sweeps_hvac_owned_fans`, `…_skips_room_not_registered…` |
| G5b | registry-membership check removed | `test_batch_d_g5_sweep_skips_room_not_registered_by_fan_controller` |
| G6 | pre-arrival fan-off gate → False | `test_batch_d_g6_prearrival_fan_off_only_for_hvac_owned_fans` |
| G7 | pre-arrival fan-on gate → False | `test_batch_d_g7_prearrival_fan_on_only_for_hvac_owned_fans` |
| R1 | room-tier `fan_owner` call → "room" | `test_room_tier_follows_fan_mode[follow_thermostat-True / off-*]` |
| R2 | `_is_hvac_managing_fans` owner check removed | `test_is_hvac_managing_fans_derives_from_fan_mode[room_temperature / off]` |
| R3 | reconciler `fan_owner` call → "room" | `test_reconciler_follows_fan_mode[follow_thermostat-True / off]` |
| C1 | recheck eligibility owner check removed | `test_batch_d_recheck_eligibility_follows_fan_mode[off]` (plus pre-existing harness reds) |
| C2 | recheck still-armed owner check removed | `test_batch_d_still_armed_aborts_when_fan_mode_set_to_off` (plus pre-existing reds) |
| H1 | `fan_owner` → always "hvac" | 16 reds across the ownership file |
| H2 | migration hvac rule removed | `test_migration_mapping[…follow_thermostat]`, `test_unmigrated_room_reads_legacy_toggles` |
| S1 | select options ignore the zone | `test_select_offers_follow_thermostat_only_in_an_hvac_zone`, `test_select_rejects_follow_thermostat_outside_an_hvac_zone` |
| S2 | select invalid-follow fallback removed | `test_select_invalid_follow_thermostat_falls_back_to_room_temperature` |
| S3 | select options write removed | `test_select_persists_across_restart` |
| M1 | migration zone check → True | `test_migration_follow_becomes_room_temperature_outside_a_zone` |
| M2 | migration one-time guard removed | `test_migration_is_one_time_and_skips_non_rooms` |
| M3 | migration call in setup removed | `test_wire_in_anchors` (source anchor) |
| M4 | suppress key removed | `test_wire_in_anchors` (source anchor) |
| U1 | B1 unreadable guard removed | `test_enforcer_held_during_arriving` (+3) |
| U2 | S1 unreadable guard removed | `test_s1_held_when_only_s1_would_write` (+3) |
| U3 | episode de-dup → every call | `test_one_ledger_row_per_outage_episode_and_writes_resume`, `test_s1_held_when_only_s1_would_write` |
| N1 | D-L3 reference record not set | `test_batch_d_nudge_restore_after_ended_borrow_uses_s1_target`, `…_pre_arrival_uses_arrival_target` |
| N2 | S6 not skipped | the same two |
| N3 | arrival flag → False | `…_pre_arrival_uses_arrival_target` |
| N4 | S7 keeps the snapshot preset | the same two as N1 |
| N5 | pop at nudge start removed | `test_batch_d_reference_record_does_not_outlive_its_nudge` |
| X1 | item 4: `_reset_timers` back in the helper | severe / normal / helper tests (3) |
| X2 | item 4: A-M1 defer guard → False | `test_episode_armed_before_verify_defers_preset_restore` |

**Name-diffs vs `origin/develop` @ `ef836342a` (`scripts/suite_namediff.py`, branch @ `2eeb02075`):**
- `--isolate --files` over the 21 touched and new files: **CLEAN, 0 new, 0 gone** (15 failing on both sides, all pre-existing).
- Full suite: **CLEAN, 0 new, 0 gone**. 153 failing/erroring on both sides (pre-existing). Branch 11,429 passed vs baseline 11,347 (+82).

## 6. Live acceptance criteria (prospective — write the observed results back after the restart)
| # | Criterion | How to check (discriminating) |
|---|---|---|
| L1 | **Guest Bedroom 2: 0 HVAC-coordinator fan actions** with Fan Mode Off | `ura_activity_log` `coordinator='hvac' AND room='Guest Bedroom 2' AND action IN ('fan_on','fan_off')` since the restart = **0** over the first night (sleep onset must pass). **Discriminator:** Living Room and Study A (Follow thermostat) still show hvac `fan_off` rows in the same window, so the HVAC fan controller is alive and only the owner rule stopped Guest Bedroom 2 |
| L2 | Migration ran once per fan room, matching the §1 table | the 12 INFO lines "Fan Mode migrated to …" at the first boot; `room_fan_mode` present in each room entry's options; **0** such lines at the second boot |
| L3 | Select shows the migrated mode and only possible options | `select.*_fan_mode` for Guest Bedroom 2 = `off`, Study A = `follow_thermostat`, Jaya = `room_temperature`; all 12 list three options (all are in a zone) |
| L4 | No HVAC-tier writes to Room-temperature rooms | hvac `fan_on`/`fan_off` rows for Guest Bedroom 1 / Jaya Bedroom since the restart = 0. Room-tier fan activity for them continues |
| L5 | Changing a Fan Mode from the dashboard takes effect with no reload | set Guest Bedroom 2 to Room temperature and back: no room reload in the log; the select updates at once |
| L6 | No writes to an unreadable thermostat | `climate_write` rows with site `B1_heat_cool_enforcer` or `S1_reason_ladder*` and `values_before.hvac_mode IN ('unavailable','unknown')` since the deploy = **0**. On the next outage (e.g. a restart before ha_carrier loads), exactly one `climate_write_held_unreadable` row per affected zone |
| L7 | Item 3 (rare) | any `S7_nudge_restore_preset*` row with reason `soft_nudge_restore_s1_target` / `…_arrival_target` has **no** `S6_nudge_restore_setpoint` row for the same nudge. Proven in-suite; live only if the event recurs |
| L8 | Item 4 (rare) | an AC hard reset whose zone books an override in the lag window still logs its restore (`ac_ramp_events` restore row), and the zone does not stay `off`. In-suite; live only if it recurs |
| L9 | Old Comfort Fan Control switch gone | `switch.*_comfort_fan_control` reads unavailable (registry orphan to remove by hand) |

## 7. Not done / decisions / flags (accounted for)
- **Seam row resolved by the migration rule.** The current "HVAC-Managed on + Comfort off" combination migrates to **Follow thermostat**, per your migration rule (hvac on wins). No live room is in that state. After migration only the Fan Mode matters.
- **Climate Automation switch not gated.** See §1. It needs your ruling. The slug-based reader bug is noted there.
- **Smoke/CO safety stop not gated.** Safety beats preference.
- **Discovery runs only at HVAC setup.** A room that gains fans or joins a zone at runtime stays with the room tier until the next HVAC setup (restart or CM reload). The hvac.py / predictor writers check the FanController registry so they do not act on it meanwhile.
- **Item 3 covers only S6/S7.** S8 (cancel-nudge button) and S9 (boot ramp audit) restore the snapshot as before. Neither has a live reference record: the record is RAM-only and dropped on a new nudge. Card if wanted.
- **Item 2: no funnel-level guard** (see §2). Only B1 and S1 are held.
- **Room-tier warning wording:** the pre-existing FIX C mismatch warning is reworded. It is the one warning for an impossible "Follow thermostat".
- **Board / cards:** no kanban edits were made on this branch. The orchestrator owns the board updates: close HVAC-WRITES-WHILE-THERMOSTAT-UNAVAILABLE-1 and HVAC-ARRESTER-EPISODE-CANCELS-AC-RESET-RESTORE-1 on ship; FAN-RECHECK-GATE-HARDENING is folded in; a card for the Climate Automation ruling; optionally a card for S8/S9 under item 3.
