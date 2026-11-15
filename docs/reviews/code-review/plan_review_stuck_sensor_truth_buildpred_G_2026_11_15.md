# Plan review 2 of 2: stuck-sensor truth (S1-S6), adversarial build-prediction + framing G

Subject: `docs/planning/PLANNING_stuck_sensor_truth.md` @ 82b013db (develop) and its P3-D8b block in
`docs/planning/PLANNING_crossing_vision.md` (:922-935). Read-only review, 2026-11-15.

Read first, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger, §6 fan
mechanisms, gold patterns) and the HVAC STATE_OF_PLAY fan sections (§4.2b comfort-fan ownership + paused rooms,
§4.2c sweep, §10 fan rows C19). No §10 claim of either doc is re-asserted. Code read on develop: 
`presence_fan_recheck.py` (state machine, persist/rehydrate, cancellation), `hvac_fans._set_fan_state`
/ `snapshot_room_fan` / `pause_for_recheck`, `coordinator.py` P22 loop + refresh triggers + `_chatter_mode`,
`select.py` ChatterModeSelect, `_nm_cycle_a.nm_cycle_a_knob`; live `.storage/core.config_entries` and
`.HA_VERSION` over the Samba mount.

**Verdict: PLAN-FIX-REQUIRED.** Five HIGH findings: two goal-fidelity (the plan does not quiet the fan in
either audited case as written), one broken premise (chatter `act` has never been in effect), two build
predictions that would ship a silently inert or ON-writing stuck route.

## Ranked findings

| # | Sev | Frame | Finding | Evidence | Fix in the plan |
|---|---|---|---|---|---|
| 1 | HIGH | G | **S5 arms only while the room is occupied, but S1/S3 make the stuck input stop holding the room.** The stuck route keeps `not_occupied` (`_evaluate_eligibility` :583) and the arm-delay twin re-checks `occupied` (`presence_fan_recheck.py:1253-1254`). Once S1 excludes the upguest ZV it no longer sets `motion_detected`, so the room vacates on its timeout (the card INSTANCE: "vacated 12:56", 5 min after the 12:51:52 exclusion). The check must fit 3 ticks (`DEFAULT_FAN_RECHECK_MMWAVE_HISTORY_TICKS` 3, `const.py:1037`) + arm delay 60 s (`:907`) inside that tail: it races the timeout and fails outright in a room with a shorter timeout or a momentary veto. After the vacate the fan runs on in an empty room with an excluded sensor, and nothing ever checks it. That is the operator's case ("if we see stuck sensors we can quiet fans"). | `presence_fan_recheck.py:583`, `:1253`; card INSTANCE_2026_11_15_upguest | On the stuck route, replace `not_occupied` with "a trigger-eligible exclusion is live on an input of this room and the fan reads on or is untrusted". The occupancy release is a side effect, not the precondition. Same change in `_still_armed_eligible`. Add test `test_stuck_route_arms_after_room_vacated`. |
| 2 | HIGH | G | **The media room case (the card's namesake) is not delivered.** Through the AWAY window (13:43:29 to 13:53:10) the Matter radar read `on` and was P22-excluded (from 23:41). The plan refuses P22-on-radar as a trigger and treats it as a non-excluded still holder, so the trigger condition ("every `on` input excluded under an eligible client") fails, and `still_holder_on` vetoes. The MS600 bit, which S3 re-families as radar, also loses its P22 trigger, which contradicts D-OP2 ("radar-derived motion bits" admitted). That leaves only the chatter route, which is inert (finding 3). The plan's discriminating Live replay covers upguest only. | media audit timeline :60-74; plan §S5 trigger bullets; D-OP2 | See the Q4 view below. At minimum, add a media replay fixture to S5's acceptance and state which route quiets it. |
| 3 | HIGH | premise | **`select.ura_chatter_mode` = `act` has never been in effect.** The Select is created on the INTEGRATION entry (`select.py:51-60`) and writes that entry's options (`select.py:1030-1036`). The resolver `_chatter_mode` reads `nm_cycle_a_knob`, which reads the first COORDINATOR_MANAGER entry (`_nm_cycle_a.py:65-90`), and the cache is flushed only on CM option updates. Live `.storage/core.config_entries`: integration entry `chatter_mode=act`, CM entry `<absent>`, so the resolver returns `DEFAULT_CHATTER_MODE` = shadow (`const.py:6256`). That is why the media NMs said "WOULD quarantine (shadow)". The plan's §1 row ("CM entry") is wrong, and S3 step 0 ("a knob turn: no code") is false. Q3 cannot be answered until this is fixed. The S2 media edge drop and the S5 chatter trigger are inert until then. | cited lines; live storage read | New Tier 1 deliverable S3a: one source of truth (the Select writes the CM entry, or the resolver reads the integration entry) plus a migration of the stored `act`. Card it (two-entry knob drift). Then re-ask Q3, because flipping it changes Garage A/B and Master Bathroom live for the first time. |
| 4 | HIGH | build | **The `_set_fan_state` chokepoint has three gates; the plan names only the oracle.** (a) The owner gate (`hvac_fans.py:1840-1853`): a trigger other than RECHECK_PAUSE/RESTORE needs `_is_room_hvac_managed`, which is False for Fan Mode Off, Room temperature and paused rooms. (b) The exemption set for the manual-ON hold and the occupied harm-stop guard (`:1862-1864`, `:1876-1896`): the stuck route writes while the room is occupied by design, so `occ == "on"` SUPPRESSES the OFF. (c) The oracle (`fan_policy_oracle._compute_off_verdict`). A builder who adds `FAN_TRIGGER_STUCK_CHECK` only to the oracle gets `_set_fan_state` returning False: the fan never stops, the verdict reads "not cleared", and the page or restore follows. | cited lines | List all three gates in the S5 table, with a test per gate: `test_stuck_off_not_suppressed_by_occupied_guard`, `..._by_owner_gate`, `..._by_oracle`. |
| 5 | HIGH | build | **Restart and cancel paths restore the fan ON, and the route is not persisted.** Rehydrating PAUSED inside the window calls `_restore(OCCUPIED_CONFIRMED)` (`presence_fan_recheck.py:1793-1796`). Mid-flight cancels (sleep state, `motion_detected`, L1; `:1124-1190`) also call `_restore(OCCUPIED_CONFIRMED)`. Both reach `_fan_restore(leave_off=False)`, which writes ON. The persisted row has no route, trigger or no-restore field (`:1700-1716`). After a restart, an untrusted Bond fan or a Fan Mode Off fan outside an HVAC zone (ephemeral snapshot) gets the radar-route treatment. Second trap: once the ZV has been off ≥ 10 s, S1 pops its exclusion. The ZV's next pulse then sets `motion_detected`, which cancels the check and restores ON (Room temperature / Follow rooms), and the fan re-latches the sensor: the §6 "27 of 28 releases undone by a restore loop" class. | cited lines; PRESENCE §6 measured efficacy | Encode `route`, `trigger_inputs`, `trigger_technology` and `restore_allowed` in `snapshot_json` (no schema change; say so). `_restore` honours `restore_allowed` on EVERY path, including rehydrate and `force_restore` (or state `force_restore` as the one exception). On the stuck route, motion from a trigger input does not cancel inside the window; only a non-trigger input or BLE does. Add tests for rehydrate PAUSED and for the trigger-input motion cancel. |
| 6 | MED | build (S1) | **`_p22_off_since.setdefault` keeps the first off.** Two samples that fall in different short gaps, with no sample of `on` between them, pop the run although every gap is under 10 s. Event refreshes fire per substrate KIND change (`coordinator.py:1620-1650`, 2 s limiter). Where a second same-kind input is on (ZV + MS600 bit, both `motion_sensors`, in GB1/GB2/Media), one input's off fires no refresh, so only the 30 s poll samples. Also, the §S1 claim "a moving person produces off gaps above 10 s at `fading_time` 30 s" is wrong reasoning: `fading_time` sets when an off starts, not how long it lasts. A fidgety person gives short offs. Step 0 is the real gate. An unknown family (ESPHome boards, ledger #9) is not specified. | `coordinator.py:3713-3727`, `:1620-1650` | Store the CURRENT off state's `last_changed` (overwrite, not setdefault) and pop when `now − that ≥ tolerance`. State that an unknown family gets tolerance 0. Add test `test_p22_two_polls_in_different_short_gaps_keeps_run`. |
| 7 | MED | build (S2) | **The edge filter races the room's re-evaluation.** `_on_substrate_edge` reads the room's exclusion synchronously. The room's own refresh for the same signal is a background task (`coordinator.py:1647-1650`). Scenario: a P22-excluded input goes off for ≥ 10 s, then a real person turns it on. The edge is dropped (the exclusion is still set), and the level at the next anchor sample can still read excluded. With the window at 890 s, the anchor fires with a person in the room. The anchor is shadow until F-LEAD. | cited lines | Drop an edge (and release a level) only when the entity's `last_changed` is not newer than the excluded run's start (`_sensor_on_since`): the same run. A new rising edge always counts. Add test `test_edge_new_run_after_long_off_counts`. |
| 8 | MED | build | **The zero-fire trip-wire's 14-day window has no store.** Recheck counters are RAM (`get_room_attrs` "since-boot"), and this house restarts often, so a RAM counter never reaches 14 days. | `presence_fan_recheck.py:413-418` | Compute the window from the DB: `anomaly_log` stuck rows ≥ 30 min in fan rooms vs `memory_episodes fan_recheck_outcome` with `route=stuck`. |
| 9 | MED | build | **The `phantom_retro` exclusion cannot use context for Bond-twin writes.** URA writes `fan.media_room_ceiling_fan` (bond), but the configured `..._2` (homekit_controller) changes with that integration's context. | media audit §1 registry row | Tag by (room, time window from pause to verdict + spindown), not by context. |
| 10 | MED | build | **A shared physical fan in two rooms (Kitchen / Breakfast Nook, HVAC §4.2b) can carry two concurrent stuck checks.** One leaves the fan off and the other restores it ON, or the second snapshot reads it off. | HVAC §4.2b shared-space ruling | One stuck check per fan entity: a second room waits or skips with `fan_busy`. |
| 11 | LOW | build | The plan says `pause_for_recheck` returns None for an "unmanaged room". It returns None only when there is no `_room_fans` row (rooms outside an HVAC zone, `hvac_fans.py:2083-2087`). HVAC-zone Fan Mode Off rooms stay registered (HVAC §4.2b). A builder may reuse the registered path and set `fan_recheck_suppress_until` / `manual_on_hold_paused_at` on a person-owned row. | cited | Use the ephemeral snapshot for every Fan Mode Off and paused room, registered or not. |
| 12 | LOW | build | The S6 Bond semantics were read from HA `dev`. The house runs HA 2026.11.1 (`/Users/okosisi/ha-config/.HA_VERSION`). | — | Read `bond/fan.py` at tag 2026.11.1. The bench test covers behaviour either way. |
| 13 | LOW | G | S4 keys on room `STATE_OCCUPIED`. After S1/S3 the audited shapes vacate while the fan keeps running, so S4 misses exactly those (the plan concedes media fires only with N < 870 s). | plan §S4 | Q7: also page "house AWAY, fan on or untrusted in a room that has a live stuck exclusion". |
| 14 | LOW | build | `force_restore` (the operator hatch) writes ON, which breaks INV-S5-OFF-ONLY as worded. | `presence_fan_recheck.py:396-407` | Name it as the one exception, or make it honour `restore_allowed`. |

Cleared (holds because):
- S1 restart mid-run: `_post_restart_seen_on` + boot settle (`coordinator.py:2375-2400`) still gate exclusion. Unavailable/unknown as "neither" is consistent with the dead-sensor ruling.
- S1 clock skew: `last_changed` and `now` are both host clock. Require tz-aware values in the build.
- The 9 s blipper: a motion-class input whose off gaps are all under 10 s is excluded at 4 h by design. One gap of 10 s or more resets it. Chatter covers sub-floor bursts.
- Two stuck rooms at once: per-room `_RoomCtx`, so they are independent, except a shared fan (finding 10).
- Fan Mode Off after the OFF: nothing turns it back on. `fan_owner` None gates the HVAC tier, room tier, reconciler and shared-space sweep (HVAC §4.2b). The comfort AWAY veto blocks ON only. Humidity fans are a separate config list.

## Framing G: goal fidelity

The operator asked for a stuck sensor to quiet the fan, with the constraints relaxed, Fan Mode Off off-only, paused rooms
allowed, and untrusted fans assumed on and turned off. The plan honours D-OP3/4/5 in the actuation rules, but as written
it does not deliver the outcome in either audited incident:
- **Upguest:** works only if the check wins a race with the 5-min occupancy timeout (finding 1).
- **Media:** blocked. The trigger rule refuses the fan-latched radar, S3 re-families the MS600 bit out of the P22 trigger,
  and the chatter route is inert (findings 2, 3).

Risk reductions that changed what is delivered: keeping `not_occupied` (1), refusing P22-on-radar triggers even in AWAY,
and re-familying the MS600 bit after D-OP2 admitted it (2).

### Q4 view (keep the "nobody here" vetoes?)

The planner's physics is right in an occupied house. P22 fires on presence radars (§2 fact 3), and a 4-hour radar `on` is
what a sleeper looks like, so radar P22 is not evidence of a fault. The operator's "if it does then stuck sensor means
nothing" holds for motion-class inputs, not for radars.

But the vetoes are not weighed against the cases. Neither incident had a BLE person or a sleep state: both were daytime
AWAY. The veto that blocks media is the radar refusal (trigger rule + `still_holder_on`), and it applies in AWAY, where
the engine has already ruled the house empty (path α: trackers away, unidentified 0, face 0).

Recommendation:
- Keep `ble_l1` / L2 and the bedroom/media `sleep_state` veto. They are cheap and blocked neither case.
- Keep `still_holder_on` and the radar refusal in HOME_* / SLEEP / WAKING / GUEST.
- **In AWAY**, with no resident trust-home and no BLE person in the room, admit a P22-excluded radar (and the MS600 bit) as
  a trigger and drop `still_holder_on`.

That delivers media without the sleeper risk the pushback names. As written, the pushback quietly restores the
radar-sole constraint in the one context where it has no basis.

### Q defaults

| Q | Default | View |
|---|---|---|
| Q1 | Tolerance for motion class only | Agree. Add: unknown family gets tolerance 0. |
| Q2 | Class-aware anchor sleep gate | Agree (shadow anchor; motion class cannot be a still sleeper). |
| Q3 | Chatter act | Cannot be answered until finding 3 is fixed. Today's effective mode is shadow, so "keep act" would be a first-time behaviour change for the garages and Master Bathroom. |
| Q4 | Keep the vetoes | Keep them outside AWAY; relax them in AWAY as above. |
| Q7 | S4 at 900 s | Yes, widened per finding 13. |
| Q8 | Bond bench test | Required. Note that the upguest fan is a Tuya WiFi fan (trusted state), so S6 matters only for the Bond rooms. |

Note: card HA-ROOM-AUTOMATION-UNPAUSE-1 (in progress) un-pauses 21 rooms, so D-OP3's paused-room exception will apply to
fewer rooms. It does not change S5's design.

## Must-fix before build dispatch
1. Stuck-route trigger and eligibility do not require room occupancy (finding 1).
2. AWAY admission of P22 radar / MS600 triggers, plus a media replay fixture (finding 2, Q4).
3. Chatter knob two-entry defect: new S3a code deliverable, then re-ask Q3 (finding 3).
4. All three `_set_fan_state` gates enumerated and tested (finding 4).
5. Route and no-restore flag persisted in `snapshot_json`, honoured on rehydrate, cancel and force paths; trigger-input
   motion does not cancel (finding 5).
6. S1 off-gap overwrite rule and unknown-family default (finding 6).
7. S2 same-run test for edges and levels (finding 7).
