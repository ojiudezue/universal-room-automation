# v5.103.24: one "Fan Mode" per room decides who runs its fan; no thermostat writes while a thermostat is offline; a nudge no longer puts back an ended pre-cool; an override no longer cancels the AC-reset restore

**Batch D.** Branch `feature/hvac-batch-d` (from `develop` @ `ef836342a`, which includes v5.103.23). **Tier 2** (three framing-disjoint reviews + a focused fix-up review, all SHIP). **Shipped inside the v5.103.25 release on 2026-09-29** (one deploy, one restart, together with the anomaly-detector cycle).

**Cards / items**
1. PRIORITY: the HVAC fan controller ignored the room's fan settings. A guest was failed on 2026-09-28. Scope grew by operator ruling **option C**: one per-room **Fan Mode** replaces the two toggles.
2. `HVAC-WRITES-WHILE-THERMOSTAT-UNAVAILABLE-1`.
3. INFO-1, operator ruling **"B"**: the nudge restore after a person ends the borrow underneath it.
4. `HVAC-ARRESTER-EPISODE-CANCELS-AC-RESET-RESTORE-1`. `fix/arrester-episode-keeps-ac-reset-restore` @ `0297b1afc` is folded in. Review record: `docs/reviews/code-review/arrester_episode_keeps_ac_reset_restore.md`.

**Fix-up round 1** (all three reviews FIX-REQUIRED):
- Fan Mode migration keeps a mode stored in `entry.data`.
- Recheck ↔ room-tier handshake.
- The HVAC kill keeps room-tier holds.
- Climate Automation retired for fans (operator ruling).
- Shared-space auto-off exemption (operator ruling YES).
- INFO-1 under person protection: the person's own setpoints come back (operator ruling YES).
- A5 / A9 / A10 / B-LOW-1, and the missing tests.

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
- **First tick after a mode change (fix-up 1, B-LOW-2):**
  - **→ Follow thermostat:** a physically-on fan is adopted by the HVAC tier with a manual-ON hold (per-room hold time), then managed normally. It is never forced off.
  - **→ Room temperature:** the room tier takes over. Its external-change baseline was frozen while HVAC owned the room, so a fan it finds ON is booked as the person's (manual-ON hold), not turned off. This is the same conservative rule as its boot edge.
  - **→ Off:** nobody writes from the next tick.
- **The HVAC Fan Control kill** (`turn_off_all_managed`) clears the manual cooldown / ON-hold ledger only for HVAC-owned rooms (fix-up 1, B-M3). The ledger is shared with the room tier (`room:<name>`), so a Room-temperature or Off room keeps its holds.

### The fan recheck on a "Room temperature" room (fix-up 1, B-M1)
The recheck pauses and restores the fan through the HVAC FanController. The room tier used to read that pause OFF as a person turning the fan off (a 1 h cooldown), and the restore ON as a person turning it on (a manual-ON hold).

Now there is a handshake:
- `pause_for_recheck` calls `RoomAutomation.note_recheck_pause(until=<the recheck's suppress-until>)` **before** the pause OFF.
- While paused, the room tier skips its external-change detection and **makes no fan writes** (it used to be able to re-drive the fan over the recheck). The reconciler defers too (`is_recheck_paused`).
- `restore_after_recheck` discharges the window on **every** exit (skip, veto or restore), via `note_recheck_restore`. A restored ON is marked URA-issued (`mark_fan_on_issued`).
- **Backstop:** the window expires at the recheck's own suppress-until (default 600 s), so a lost restore cannot freeze the room tier.
- The recheck snapshot takes its speed from the **first ON entity** (A9), and the restore books tracking by **live** ownership (B-LOW-1).

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

- **A Fan Mode already present anywhere is kept** (fix-up 1, HIGH). A new room's config flow writes `room_fan_mode` into `entry.data`; the migration now checks the merged data + options and skips.
- **The migration reads only `hvac_coordination_enabled` / `fan_control_enabled` — never the retired Climate Automation switch.** Many of those switches were turned off on 2026-09-29 as a stop-gap. Pinned by `test_migration_ignores_the_retired_climate_automation_switch`.
- **Rooms without fans** also get a Fan Mode (usually Off). It has no effect there.

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
- **Saving the form keeps a stored Follow thermostat** that is shown as Room temperature because the room is no longer in a zone (fix-up 1, A5). This is the same rule as the select.
- **New-room flow:** the same dropdown. Default **Off**. It offers Follow thermostat only when the chosen zone has a thermostat. The speed step follows only for Room temperature.
- **Retired:** `switch.<room>_comfort_fan_control` (RoomComfortFanControlSwitch). Its registry entry stays as "unavailable" until you remove it (Bug Class #46: code never deletes registry entries).

### Climate Automation switch — RETIRED for fans (operator ruling 2026-09-29, fix-up 1)
- **Consumers found:** exactly one. `coordinator.py` (was :4970) gated the room-tier temperature fan path (`handle_temperature_based_fan_control`) on `_is_climate_automation_enabled()`. That read the switch through a slug-built entity id (`switch.{room_slug}_climate_automation`), which did not match renamed rooms: Guest Bedroom 2's real entity is `switch.upstairs_guestroom_climate_automation`.
  - Nothing else read it: no HVAC-tier site, sensor, dashboard helper or test outside its own replica.
- **Changes:**
  - The gate is removed: the Fan Mode alone decides.
  - `_is_climate_automation_enabled` and its lookup are removed.
  - `ClimateAutomationSwitch` is no longer created, so it no longer appears on room devices.
  - The existing `switch.*_climate_automation` registry entries (43, 19 of them enabled) are **left orphaned** for you to remove (Bug Class #46: code never deletes registry entries).
- **Before this change,** a "Room temperature" room whose old switch read OFF (Guest Bedroom 1, Jaya) would have run no temperature fan logic at all (A2). Pinned by `test_room_temperature_runs_with_the_old_climate_automation_switch_off` and the AST anchor `test_climate_automation_no_longer_gates_the_room_tier_fan_path`.
- **The Fan Mode select is enabled by default** (`mdi:fan-auto`) and is the fan control on the room device page.

### Shared-space 11 PM auto-off (fix-up 1, B-M2 / A8) — operator ruling YES
`RoomAutomation._shared_space_turn_off_all` turned off `CONF_FANS` regardless of the Fan Mode.
- **Ruled and built:**
  - Fan Mode **Off** leaves the room's comfort fans alone.
  - A fan **another** room drives under Follow thermostat is never turned off by this room (e.g. the Breakfast Nook → Kitchen shared fan `fan.151732606487193_fan`).
  - Lights and switches are unchanged.
- It is its own commit (`ce5bf9ddb`: one `automation.py` hunk plus `test_hvac_batch_d_shared_space_fans.py`).

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
  - Presets only. The reasons are `soft_nudge_restore_s1_target` and `soft_nudge_restore_arrival_target`. With no resolvable reference, the pre-ruling snapshot restore runs (fix-up 1, A10).
  - The record is dropped at every new nudge start (:5632) and at teardown.
  - **No resolvable reference** (fix-up 1, A10 — e.g. no seasonal setpoints, or the resolver is unwired): the restore falls back to the pre-ruling snapshot restore (S6/S7). It no longer leaves the nudge's +°F setpoint on the thermostat.
- **Person protection (fix-up 1, operator ruling YES).** When gate (a/b) is active at restore time (Temp Arrester Override, or an immune-person hold on the zone; read live through `_corrective_writes_suppressed`):
  - the restore returns the zone to **the person's own setpoints** from the change that ended the borrow (captured with the reference record);
  - it writes them through S6 as a HUMAN_MANUAL raw restore (reason `human_manual_soft_nudge_person_restore`), per the W1-B rule;
  - it **skips S7's preset pin**.
  - If the person's values are unavailable, the pre-ruling snapshot restore runs.
  - Without gate (a/b), ruling B applies as built.
- Nudges without an ended borrow underneath are unchanged (pinned by a control test).

## 4. The arrester no longer cancels the AC-reset restore (item 4)
- Cherry-picked cleanly onto v5.103.23 (`3e53b30ac`, `5ee400249`, `40f93e9ae`), with the Co-Authored-By trailers stripped.
- The three call sites (`hvac_override.py` :2606, :4261, :4335) all use `_cancel_arrester_timers` (:7940).
- `git grep _cancel_zone_timers -- custom_components quality/tests` returns docstring mentions only.
- The merge-step doc checklist is applied (`a730f276e`): B-L3 is recorded as FIXED in README_v5.103.23, PLANNING_hvac_w1_w2_finish and the v5.103.23 review record.
- Its tests pass, and its two recorded drills were re-run (X1, X2 below).
- **Fix-up 1:**
  - The startup-audit call site (M50) and the deferred `restore_ok` scoring (M49) now have their own tests.
  - The defer guard's three overlapping terms (M46–M48) are documented in code as **defense in depth**: a single-term mutation is expected to stay green, and the anchor is the whole guard (X2).

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

**Fix-up 1 drills** (same discipline; script `.claude/worktrees/batchd_tools/drills_fixup1.py` inside this worktree; `git status` clean after the run):

| Drill | Site neutered | RED |
|---|---|---|
| F1 | migration guard back to options-only | `test_migration_keeps_a_fan_mode_stored_only_in_entry_data` |
| M2r | migration one-time guard removed | `test_migration_is_one_time_and_skips_non_rooms`, `…stored_only_in_entry_data` |
| F2a | recheck-pause handshake not called | `test_room_tier_does_not_book_the_recheck_as_a_person`, `test_room_tier_pause_window_has_a_backstop` |
| F2b | restore discharge not called | `test_room_tier_does_not_book_the_recheck_as_a_person` |
| F2c | room-tier skip-while-paused removed | the same |
| F2d | restored ON not marked URA-issued | the same |
| F2e | reconciler pause defer removed | `test_reconciler_defers_while_the_recheck_paused_the_fan` |
| F3 | HVAC-kill ledger gate removed | `test_hvac_kill_keeps_holds_of_rooms_it_does_not_own` |
| G4r | restore gate (relocated) → False | `test_restore_skipped_when_mode_set_to_off_mid_recheck` |
| A5 | options save keeps stored Follow removed | `test_options_save_keeps_stored_follow_outside_a_zone` |
| A9 | first-ON-entity filter removed | `test_recheck_snapshot_speed_is_the_first_on_entity` |
| A10 | unresolvable-reference fallback removed | `test_batch_d_unresolvable_reference_falls_back_to_snapshot_restore` |
| BL1 | restore tracking by snapshot, not live | `test_restore_tracks_by_live_ownership_not_the_pause_snapshot` |
| M32 | `room_fan_mode` suppress key removed | `test_solo_key_change_suppresses[room_fan_mode]`, `test_d1_virgin_room_first_save_default_materialization_suppresses` |
| M33 | options not-in-zone display removed | `test_options_form_not_in_zone_shows_room_temperature_for_stored_follow` |
| M34 | `_zone_name_has_thermostat` → always True | `test_zone_name_has_thermostat`, `test_new_room_form_offers_follow_only_with_a_thermostat_zone` |
| M35 | speed step for any non-Off mode | `test_new_room_speed_step_only_for_room_temperature[follow_thermostat-sleep]` |
| M49 | deferred `restore_ok` scored False | `test_episode_armed_before_verify_defers_preset_restore` |
| M50 | startup-audit site also pops the reset timer | `test_startup_audit_stale_override_does_not_cancel_reset_restore` |
| I6a | Climate Automation gate re-added around the handler | `test_climate_automation_no_longer_gates_the_room_tier_fan_path` |
| I6b | select enabled-by-default → False | `test_fan_mode_select_is_enabled_by_default_with_an_icon` |
| I4a | shared-space Off skip removed | `test_shared_space_auto_off_follows_fan_mode[off-False]` |
| I4b | shared-space other-room HVAC filter removed | `test_shared_space_auto_off_skips_another_rooms_hvac_owned_fan` |
| N1r | D-L3 reference record not set | `…uses_s1_target`, `…uses_arrival_target`, `test_batch_d_protected_person_gets_their_own_values_back[tao/immune]`, `…values_missing…` (+2) |
| P1 | gate (a/b) read → False | `test_batch_d_protected_person_gets_their_own_values_back[tao/immune]`, `…values_missing_falls_back_to_snapshot` |
| P2 | person values not captured | the same three + `test_batch_d_unprotected_zone_keeps_ruling_b` |
| P3 | person S6 writes the snapshot target | `…own_values_back[tao/immune]` |
| P4 | S7 pin not skipped for the person | `…own_values_back[tao/immune]` |
| P5 | values-missing fallback → reference restore | `test_batch_d_protected_person_values_missing_falls_back_to_snapshot` |

**Name-diffs vs `origin/develop` @ `ef836342a` (`scripts/suite_namediff.py`, branch @ `2eeb02075`):**
- `--isolate --files` over the 21 touched and new files: **CLEAN, 0 new, 0 gone** (15 failing on both sides, all pre-existing).
- Full suite: **CLEAN, 0 new, 0 gone**. 153 failing/erroring on both sides (pre-existing). Branch 11,429 passed vs baseline 11,347 (+82).
- **After fix-up 1** (branch @ `4fc7c6eae`):
  - `--isolate --files` over 28 touched/new files: **CLEAN, 0 new, 0 gone** (15 pre-existing on both sides).
  - Full suite: **CLEAN, 0 new, 0 gone**. 153 pre-existing on both sides; 11,458 passed vs 11,347 (+111).

## 6a. Validated 2026-09-29 (post-restart, ~19:17-19:22 CDT)

Restart occurred 2026-09-29 19:17 CDT. House state at validation time: `away` (real value, URA loaded). Validation window was short (~5 min post-restart, house away, no sleep-onset yet), so several criteria that need a real occupancy/sleep event are PENDING.

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L2 | Migration ran once per room, matching the §1 table | PASS | `.storage/core.config_entries` (live mount, written 19:17): 43/43 room entries carry `room_fan_mode` in options. Spot-checked exact values: Study A → `follow_thermostat`, Guest Bedroom 1 → `room_temperature`, Guest Bedroom 2 → `off` — all match the §1 table. INFO-line count could not be verified: HA's `error_log`/file logging captures WARNING+ only in this environment, and the MCP `system`/`logbook` log sources timed out repeatedly (WebSocket handshake timeout) against this instance — a live-environment tooling gap, not a code defect. The config-file evidence is a stronger oracle than the log-line count for this criterion. |
| L3 | Select shows the migrated mode and only possible options | PASS | Live entity states (`ha_search`/`ha_get_state`): `select.guest_bedroom_2_guest_bedroom_2_fan_mode` = `off`; `select.study_a_study_a_fan_mode` = `follow_thermostat`; `select.guest_bedroom_1_guest_bedroom_1_fan_mode` = `room_temperature`. 8 `select.*_fan_mode` entities found live and enabled (not `unavailable`). Note: the Samba-mounted `core.entity_registry` file predates these entities (last written 19:16, before their first-boot creation) and is stale for this specific check — live entity state was used instead, per this repo's stale-cache caution. |
| L1 | Guest Bedroom 2: 0 HVAC-coordinator fan actions with Fan Mode Off | PARTIAL PASS / PENDING full discriminator | `ura_activity_log` (copied live DB + WAL/SHM to bypass an SMB/WAL lock on the network mount): `SELECT count(*) FROM ura_activity_log WHERE coordinator='hvac' AND room='Guest Bedroom 2' AND action IN ('fan_on','fan_off') AND timestamp >= '2026-09-30T00:17:00'` = **0**. Consistent with the fix. The positive half of the discriminator (Living Room / Study A still showing hvac `fan_off`) could not be checked yet — 0 hvac fan rows of any kind exist since restart (house is `away`, no sleep-onset has occurred). Re-check after the first sleep-onset window. |
| L4 | No HVAC-tier writes to Room-temperature rooms (Guest Bedroom 1 / Jaya) | PENDING | 0 hvac fan rows of any kind since restart (see L1) — too early to observe either a violation or the room tier's own activity. Not falsified; not yet exercised. |
| L4b | Recheck on a Room-temperature room opens no false hold | PENDING (as documented — live only if a recheck runs) | No `fan_recheck_outcome` rows for Guest Bedroom 1 / Jaya since restart. |
| L10 | Climate Automation retired | PASS | `custom_components.universal_room_automation` log scan (structured `error_log`, WARNING+, restart window): no new `switch.*_climate_automation` setup activity; no ERROR/Traceback from `coordinator.py`'s temperature-fan path. `switch.upstairs_guestroom_climate_automation` and `switch.guest_bedroom_2_guest_bedroom_2_comfort_fan_control` return `404 ENTITY_NOT_FOUND` via `ha_get_state` (not published to the live state machine at all — stronger than "unavailable"). Registry entries confirmed still present (orphaned) via a direct grep of `.storage/core.entity_registry`: 42 `switch.*_climate_automation` and 43 `switch.*_comfort_fan_control` entries found. |
| L11 | Fan Mode select prominent | PASS | All 8 live `select.*_fan_mode` entities read a real mode value (not `unavailable`/`unknown`), confirming they are enabled and created. |
| L5 | Changing a Fan Mode from the dashboard takes effect with no reload | PENDING (not exercised — read-only validation; this task did not perform a dashboard-side config-flow reload test) | Not checked this pass. |
| L6 | No writes to an unreadable thermostat | PASS (not falsified — no outage recurred) | `SELECT count(*) FROM ura_activity_log WHERE coordinator='hvac' AND action='climate_write' AND (details_json LIKE '%B1_heat_cool_enforcer%' OR details_json LIKE '%S1_reason_ladder%') AND details_json LIKE '%"hvac_mode": "unavailable"%' AND timestamp >= '2026-09-29T00:00:00'` = **0**; `climate_write_held_unreadable` rows total = **0**. No thermostat outage has occurred since deploy to positively exercise the guard; the negative is consistent with both the old and new code (no outage happened), so this is "not falsified" rather than "positively proven live." Proven in-suite per the README's own note. |
| L7b | Item 3 under person protection (rare) | PENDING (in-suite only, as documented) | Not exercised live. |
| L7 | Item 3 (rare) | PENDING (in-suite only, as documented) | Not exercised live. |
| L8 | Item 4 (rare) | PENDING (in-suite only, as documented) | Not exercised live. |
| L9 | Old Comfort Fan Control switch gone | PASS | `switch.guest_bedroom_2_guest_bedroom_2_comfort_fan_control` and `switch.guest_bedroom_1_guest_bedroom_1_comfort_fan_control` return `404 ENTITY_NOT_FOUND` (gone from the live state machine). Registry entries remain as orphans per L10 evidence — matches "registry entry stays, you remove it by hand." |

**Log scan (restart window, structured `error_log`, WARNING+):** no ERROR/Traceback attributable to Batch D code (Fan Mode, unreadable-thermostat guard, nudge restore, arrester restore). All `custom_components.universal_room_automation` WARNING-level lines in the window are recognizable boot transients: per-room "all N energy sensor(s) unavailable" (SPAN/sensor-availability boot race), "All 3 sensors unavailable — holding occupancy state for 60s", "Census: all camera platforms unavailable", "DB write worker slow: no connection after 35.0s" (~10 occurrences; NOT a DB problem: the whole event loop froze ~148 s at boot, see AUDIT_db_write_worker_slow_2026_09_29.md / BOOT-EVENT-LOOP-FREEZE-1), "HVAC boot-settle: released via TIMEOUT after 60s", Envoy degraded-at-boot warning. One line worth a flag though outside this cycle's scope: `FanPolicyOracle fallback: read_on/write_on served from RoomAutomation __dict__ (oracle unavailable) for room=room:Living Room — check CoordinatorManager lifecycle` (3x, 19:17:17-19:19:55) — a boot-ordering warning, not an ERROR, but worth a follow-up look if it persists past boot-settle.

## 6. Live acceptance criteria (prospective — write the observed results back after the restart)
| # | Criterion | How to check (discriminating) |
|---|---|---|
| L1 | **Guest Bedroom 2: 0 HVAC-coordinator fan actions** with Fan Mode Off | `ura_activity_log` `coordinator='hvac' AND room='Guest Bedroom 2' AND action IN ('fan_on','fan_off')` since the restart = **0** over the first night (sleep onset must pass). **Discriminator:** Living Room and Study A (Follow thermostat) still show hvac `fan_off` rows in the same window, so the HVAC fan controller is alive and only the owner rule stopped Guest Bedroom 2 |
| L2 | Migration ran once per ROOM, matching the §1 table for the 12 fan rooms | ~43 INFO lines "Fan Mode migrated to …" at the first boot (one per room entry, including rooms without fans), with the 12 fan rooms as in §1; `room_fan_mode` present in every room entry's options; **0** such lines at the second boot |
| L3 | Select shows the migrated mode and only possible options | `select.*_fan_mode` for Guest Bedroom 2 = `off`, Study A = `follow_thermostat`, Jaya = `room_temperature`; all 12 list three options (all are in a zone) |
| L4 | No HVAC-tier writes to Room-temperature rooms | hvac `fan_on`/`fan_off` rows for Guest Bedroom 1 / Jaya Bedroom since the restart **excluding recheck triggers** (`trigger=recheck_pause` / `recheck_restore` — those are the presence recheck, which follows the owner) = 0. Room-tier fan activity for them continues |
| L4b | A recheck on a Room-temperature room opens no false hold | after any `fan_recheck_outcome` row for Guest Bedroom 1 / Jaya: no "fan turned off externally — room-tier cooldown" or "manual-ON hold" INFO line for that room within the recheck window. In-suite; live only if a recheck runs there |
| L10 | Climate Automation retired | no new `switch.*_climate_automation` entities are created (the old ones read unavailable); a Room-temperature room runs its temperature fan logic whatever the old switch said |
| L11 | Fan Mode select prominent | `select.<room>_fan_mode` is enabled (not hidden) on every room device |
| L5 | Changing a Fan Mode from the dashboard takes effect with no reload | set Guest Bedroom 2 to Room temperature and back: no room reload in the log; the select updates at once |
| L6 | No writes to an unreadable thermostat | `climate_write` rows with site `B1_heat_cool_enforcer` or `S1_reason_ladder*` and `values_before.hvac_mode IN ('unavailable','unknown')` since the deploy = **0**. On the next outage (e.g. a restart before ha_carrier loads), exactly one `climate_write_held_unreadable` row per affected zone |
| L7b | Item 3 under person protection (rare) | with TAO or an immune hold active: an `S6_nudge_restore_setpoint` row with reason `human_manual_soft_nudge_person_restore` carrying the person's values, and **no** `S7_nudge_restore_preset*` row for that nudge. In-suite |
| L7 | Item 3 (rare) | any `S7_nudge_restore_preset*` row with reason `soft_nudge_restore_s1_target` / `…_arrival_target` has **no** `S6_nudge_restore_setpoint` row for the same nudge. Proven in-suite; live only if the event recurs |
| L8 | Item 4 (rare) | an AC hard reset whose zone books an override in the lag window still logs its restore (`ac_ramp_events` restore row), and the zone does not stay `off`. In-suite; live only if it recurs |
| L9 | Old Comfort Fan Control switch gone | `switch.*_comfort_fan_control` reads unavailable (registry orphan to remove by hand) |

## 7. Not done / decisions / flags (accounted for)
- **Seam row resolved by the migration rule.** The current "HVAC-Managed on + Comfort off" combination migrates to **Follow thermostat**, per your migration rule (hvac on wins). No live room is in that state. After migration only the Fan Mode matters.
- **Climate Automation:** retired for fans, per your ruling (§1). The registry entries are orphaned.
- **Operator rulings applied in fix-up 1:**
  - Climate Automation retired for fans: `7e18e7272`.
  - The shared-space auto-off exemption: `ce5bf9ddb`.
  - INFO-1 under person protection: `9520f6c3b`.
  - Nothing is left pending on this branch.
- **Smoke/CO safety stop not gated.** Safety beats preference.
- **Discovery runs only at HVAC setup.** A room that gains fans or joins a zone at runtime stays with the room tier until the next HVAC setup (restart or CM reload). The hvac.py / predictor writers check the FanController registry so they do not act on it meanwhile.
- **Item 3 covers only S6/S7.** S8 (cancel-nudge button) and S9 (boot ramp audit) restore the snapshot as before. Neither has a live reference record: the record is RAM-only and dropped on a new nudge. Card if wanted.
- **Item 2: no funnel-level guard** (see §2). Only B1 and S1 are held.
- **Room-tier warning wording:** the pre-existing FIX C mismatch warning is reworded. It is the one warning for an impossible "Follow thermostat".
- **Board / cards:** no kanban edits were made on this branch. The orchestrator owns the board updates: close HVAC-WRITES-WHILE-THERMOSTAT-UNAVAILABLE-1 and HVAC-ARRESTER-EPISODE-CANCELS-AC-RESET-RESTORE-1 on ship; FAN-RECHECK-GATE-HARDENING is folded in; the Climate Automation registry orphans (operator clean-up); optionally a card for S8/S9 under item 3.
