# PLANNING: stuck-sensor truth and its consumers (crossing P3-D8 anchor prerequisites, the stuck-triggered fan check, assumed-state fans)

Rev 2, 2026-11-15 (one clean document; the change record is §9 at the end). Rev 1 = 82b013db.
Cards: MEDIAROOM-FAN-LEFT-ON-STUCK-SENSORS-1 (incl. INSTANCE_2026_11_15_upguest), CHATTER-MODE-SELECT-NOT-WIRED-1,
CENSUS-DECONFLICTION-LEDGER-1 (INSTANCE_2026_11_15_ledger_unknown_since_boot), VISION-CROSSING-ANALYSIS-1 (P3-D8 review
D/G: G-1, G-2, D-M1). Related: HA-ROOM-AUTOMATION-UNPAUSE-1 (re-enabling most paused rooms, so the paused-room exception
in S5 reaches fewer rooms; S5's design does not depend on it).
Arc: identity / vision / census (charter `docs/planning/ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`).
Charter goal served by S1-S3: "make census almost bullet proof at entry... You could even essentially base census
entirely on this". Door vision cannot reach the census (bars a / e, F-LEAD) without an empty-house anchor, and the anchor
has not fired once since the ledger went live (2026-11-14 16:06). S4-S6 serve the fan card (operator 2026-11-15:
"if we see stuck sensors we can quiet fans").
Code: develop b33dd68a; the P3-D8 code from `feature/crossing-p3-first` @ 48d4bc94 (built, reviewed SHIP, NOT merged).

**Read completely by this planner (rev 2):** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10),
`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (all 750 lines incl. §4.2b, §4.2c, §9.3, §10 C1-C39),
`docs/architecture/SENSOR_FLEET_CLASSES.md`, `v_crossing_p3_first_review_D_G.md`, both 11-15 audits, both rev-1 plan
reviews (`plan_review_stuck_sensor_truth_completeness_2026_11_15.md`, `plan_review_stuck_sensor_truth_buildpred_G_2026_11_15.md`),
the card and its INSTANCE field, `.claude/skills/ura-arc/SKILL.md`. No §10 claim of either STATE_OF_PLAY is re-asserted.
HVAC C27 (the 4 h rule removed Jaya's fan-tracking radar) is consistent with S1 keeping radars at tolerance 0 and with S5
refusing P22-radar triggers outside AWAY. HVAC §4.2b's "a probe must not turn a person's fan off" (review B-M1,
2026-10-19) is superseded for the stuck route only by D-OP3 / D-OP4 below; S5 schedules the doc update (§7).

---

## 0. Why a separate plan (ura-arc rules 5 and 6)

- **One clean document per scope (rule 5).** The crossing plan's scope is the vision PRODUCER. Five of six deliverables
  here change room-tier and fan code (the P22 primitive, the chatter wiring, the family resolver, the recheck state
  machine, Bond fans). S2 edits crossing-vision code, so it is ALSO written into the crossing plan as P3-D8b (a pointer
  block) and is built on the P3-D8 branch and reviewed with it.
- **Seam / merge check (rule 6), decided.**
  - S1 changes `_sensor_on_since`, which P3-D8 reads through the `p22_continuous` client: SEAM (different function, same
    value). S1 ships before P3-D8 is relied on.
  - S2 and P3-D8 share one room getter: same branch, one review set.
  - S3a fixes the chatter knob's two-entry split (CHATTER-MODE-SELECT-NOT-WIRED-1); no other plan edits `_chatter_mode`.
  - S5 / S6 change `presence_fan_recheck`, `hvac_fans._set_fan_state` / `pause_for_recheck` / `restore_after_recheck`,
    and `fan_policy_oracle._compute_off_verdict` (fan cards FAN-RECHECK-*, FAN-MANUAL-1, FAN-LAYER-2). No open plan edits
    those functions (grep of `docs/planning/PLANNING_*` for `pause_for_recheck` / `_evaluate_eligibility` /
    `_compute_off_verdict`: only shipped plans). No merge.
  - Interior plan, census plan, NVR W2: no shared function; the camera-stream client stays out of every stuck set here.
- Arc map: one row "stuck-sensor truth (S1-S3) -> unblocks crossing P3-D8 anchor", before step 2b.

## 1. Institutional context verified (greps re-run on develop b33dd68a; branch = `feature/crossing-p3-first`)

| Proposed piece | Verdict | Evidence |
|---|---|---|
| P22 continuous-on timer | REUSED, changed | `_sensor_on_since` `coordinator.py:400`; literal `_stuck_sensor_hours = 4.0` `:401`; stamp loop `:3713-3727` (stamps tick `now` at `:3720`, pops on ANY not-on reading at `:3727`, incl. `unavailable`); set builder `_p22_stuck_sensor_set` `:2375-2400`; promote `p22_continuous` `:3757-3762`; persistence `_async_load_stuck_state` `:2437-2470`, snapshot `:2495-2507`, payload `:2558-2570`. P22 has no class gate: it fires on presence radars (media Matter radar excluded 11-14 23:41, `anomaly_log` 352219; HVAC C27, Jaya) |
| Off-gap tolerance / P22 hours knobs | NEW `STUCK_P22_OFF_GAP_TOLERANCE_S`, `STUCK_P22_HOURS` | 0 hits for `OFF_GAP` / `off_gap` / `P22_` in `const.py`, `coordinator.py`, `config_flow.py`, `options_flow.py`, plans; `CONF_STUCK_SENSOR_*` (`const.py:5980-5989`) are duty-cycle only |
| Still-person-holder predicate | NEW `sensor_capability.is_still_holder` (pure) | `is_fan_immune_witness` (`sensor_capability.py:359-370`) is the WRONG predicate: it is True for `bed` / `camera_presence` / `ble_presence`, which hold a still person (SENSOR_FLEET_CLASSES rule 3 names the two properties separately). `RADAR_SENSOR_FAMILIES` `:408`; `is_radar_capability` `:484-492` reused |
| Readers of `_sensor_on_since` and of the exclusion set | enumerated §3 S1 | `coordinator.py` + `sensor.py:2526`, `:2597`; `_fusion_filter_active` `:2586-2597` call sites incl. `:2317`, `:4016-4058`, `_live_on_set` `:6158-6166` (caller `:4074`); `camera_input_room_quarantined` `:2790-2796` |
| Room stuck getter | REUSED from branch, changed | `camera_input_room_stuck_excluded` (branch) beside `camera_input_room_quarantined`; wrapper `input_room_stuck_excluded` branch `camera_stream_health.py:1245-1254` over `_ask` `:1091-1103` (any-True fold) |
| Anchor edge hook | REUSED, changed | `_on_substrate_edge` branch `crossing_vision.py:1334-1341` -> `note_rising_edge` `crossing_ledger.py:398-401` -> `_edge_since_sample` blocks the sample `:480`, resets `_t_start` `:498-499` |
| Per-(room, kind) entity list | EXTRACT, not new logic | inline comprehension `occupancy_substrate.py:382-385` becomes `OccupancySubstrate.entities_for(room, kind)`; `last_edge_entity_for` `:1004` is not usable (not set on the `recheck_entities` path) |
| House-state gate | REUSED with a fail-closed wrapper | `_d2_house_state_allows` `coordinator.py:2334` fails OPEN (True on missing presence / error); the anchor needs fail-closed |
| Chatter act/shadow | REUSED knob, WIRING BUG | `ChatterModeSelect` lives on the INTEGRATION entry (`select.py:50-60`) and writes that entry's options (`select.py:1030-1036`). The room resolver `_chatter_mode` (`coordinator.py:3216-3260`) reads `nm_cycle_a_knob` (`domain_coordinators/_nm_cycle_a.py:65-90`), which reads only the COORDINATOR_MANAGER entry. Live `.storage`: integration entry `chatter_mode=act`, CM entry absent -> rooms run `DEFAULT_CHATTER_MODE` = shadow (`const.py:6256`). Every chatter NM through 11-15 reads "WOULD quarantine (shadow)", Garage B 21:49Z included. Chatter has never acted. The select's state `act` (last_changed 15:47:51) is the integration option, not the room behaviour. Migration `__init__.py:5045-5066` also writes `CONF_CHATTER_MODE`: the build reads which entry it targets |
| MS600 family resolver | REUSED table, changed | `FAMILY_BY_MODEL_ID` `sensor_capability.py:385` (`"ms600 9.0.0"` `:400`), `FAMILY_BY_MODEL_TOKEN` `:429-430`, `family_for_model` `:436-450` (exact key, then first whitespace token). The media / GB bit's device has `model` = `ms600-un`, `model_id` None (verified in `core.device_registry` by the completeness review). Each room has TWO Meross device records (`ms600-un` and `ms600 9.0.0`, same meross_lan identifier). Unknown falls back to the name regex `fan_veto.py:124-127` (REGISTRY-NOT-NAMES residual) |
| Radar classification consumer | REUSED | `is_radar` `coordinator.py:6146-6156` -> `fan_veto.is_radar_entity`; `_radar_sole_on_set` `:6168-6175` -> recheck eligibility ring |
| AWAY-while-held page | NEW producer, REUSED sender `fire_stuck_signal` (`_stuck_signal_nm`) | opposite-direction sibling `zone_hold_all_away` `presence.py:4478-4570`; 0 hits for `away_room_held` |
| Stuck fan check | EXTEND | `presence_fan_recheck`: vetoes `_evaluate_eligibility` `:536-727`, arm twin `_still_armed_eligible` `:1218-1276`, cancels `_evaluate_cancellation_during_tick` `:1108-1190`, `_cancel_and_restore_async` `:1192-1216`, pause `_enter_paused` `:810-880`, verdict `_on_pause_window_done` `:889-912`, `_restore` `:915+`, `force_restore` `:396-407`, persist `_persist` `:1689-1721` (`snapshot_json`), rehydrate `_restore_row` `:1723-1880` (PAUSED -> `_restore(OCCUPIED_CONFIRMED)` `:1793-1796`). `hvac_fans`: `_set_fan_state` owner gate `:1840-1853`, exemption set `:1862-1864`, manual-ON hold `:1876-1889`, occupied harm-stop `:1890-1899`; `pause_for_recheck` `:2148-2205`; `restore_after_recheck` / body `:2207-2300` (Fan Mode Off skip, C1a manual-ON override to ON). Oracle `fan_policy_oracle._compute_off_verdict` (`:543-544` recheck ALLOW). 0 hits for stuck / exclusion / chatter in `presence_fan_recheck.py` |
| `phantom_retro` | REUSED, tagged | writer `memory_writers.write_phantom_retro` `memory_writers.py:138` (rev 1 cited `const.py:6292-6296`, wrong: those are chatter provenance lines) |
| Fan-state trust | NEW, REUSED HA flag | URA reads `assumed_state` nowhere (grep 0). HA `bond/entity.py:62` `_attr_assumed_state = is_bridge and not trust_state`; live: the four Bond-platform twins read `assumed_state: true` (`fan.media_room_ceiling_fan`, `fan.game_room_ceiling_fan`, `fan.guest_room_down_ceiling_fan`, `fan.ceilingfan_fanimaton_rf_masterbedroom`, read 2026-11-15). The configured fans are HomeKit twins (`homekit_controller`) on separate devices; no registry link joins them |
| Bond command | REUSED HA | HA `bond/fan.py` at tag **2026.11.1** (the installed version, `/Users/okosisi/ha-config/.HA_VERSION`; file identical to `dev`): `async_turn_off` `:192-196` sends `Action.turn_off()` (Bond `TurnOff`) whatever the template supports. The HA install's own copy is not readable over `ssh ha` (no docker socket in the SSH add-on) |

Prior plans: crossing plan (P3-D8, §6, §7), `PLANNING_stuck_signal_watchdog.md`, STUCK-SENSOR-1 (shipped v5.75.0),
`PLANNING_fan_noise_running_rejection.md` Rev 2, `PLANNING_paused_room_occupancy_lights_fans.md`, FAN-MANUAL-1 /
FAN-LAYER-2. Memory: `feedback_dead_sensor_is_faulty_equipment`, `reference_sensor_fleet_classes`,
`feedback_marginal_benefit_pushback`, `feedback_suppression_needs_discharge`, `feedback_registry_not_name_guessing`,
`feedback_tier2db_minimum_arc`.

## 2. Facts and operator decisions

**Facts.**
1. Upguest: ZG-204ZV (motion class, registry `model_id`) held the AWAY house's room; P22 fired 12:51:52; a 1.8 s off
   pulse seen at 13:51:48 popped `_sensor_on_since` and re-armed 4 h. Fan-off test 14:37:30: the ZV went off within
   ~30 s and stayed off 6.5 min; the room vacated ~5 min later. One trial; the fan drove it. Fan: Tuya WiFi (trusted state).
2. Media: Matter radar (presence class) P22-excluded at 4 h (23:41); the Meross bit (radar-derived, `motion_sensors`)
   flapped 1,435 times in 18.2 h and held the room; AWAY from 13:43:29, both cleared 13:53:10 after the fan command.
   Fan: Bond via HomeKit (HA never saw it on).
3. P22 fires on presence radars (§1 row 1).
4. Chatter has never acted (§1 chatter row).

**Operator decisions (2026-11-15), recorded as decided.**
- **D-OP1 (S1):** "Yup" to "a short off-pulse shouldn't restart the 4-hour stuck clock". Defaults taken: tolerance for
  motion-class only; unknown family -> tolerance 0.
- **D-OP2 (motion-class sensors trigger the fan check):** "Yup. Little harm. Or define radio based motion sensors. But
  better to admit motion sensors. Fans are motion although pir resists better". All motion-class inputs trigger (PIR, ZV
  mmWave-motion, radar-derived motion bits in AWAY per D-OP6). Technology by registry model + SENSOR_FLEET_CLASSES,
  never names. PIR gets the same trigger and verdict; every outcome row records `trigger_technology` (`pir` /
  `mmwave_motion` / `radar` / `radar_bit` / `unknown`) so accuracy per technology can be compared.
- **D-OP3 (paused rooms):** "Yes". Fault repair, not room automation. The stuck fan check's OFF is the ONLY exception to
  pause; pause keeps every other promise. Own kill switch.
- **D-OP4 (Fan Mode Off):** "This should be fine for turning off. What we don't want is turning on and active control."
  OFF only: never on, never restore on, never speed.
- **D-OP5 (untrusted-state fans):** "Makes sense. Assume on. Turn off." Plain `turn_off`, never on-then-off;
  `off_unverified` until the bench passes; toggle-only fans excluded.
- **D-OP6 (Q4, the "someone might be here" vetoes):** "reasonable. Agree." Default taken by the orchestrator: review G's
  refinement. Keep BLE L1/L2, the sleep-state veto, `still_holder_on` and the radar refusal in HOME_*, SLEEP, WAKING and
  GUEST. In AWAY, with no resident trust-home and no BLE person in the room, admit a P22-excluded radar and the MS600 bit
  as triggers and drop `still_holder_on`. Reason: without it the media case (the card's namesake) is not delivered, and
  rev 1's claim to the operator that the vetoes blocked neither case was wrong (they blocked media).
- **D-OP7 (Q7, S4):** "it should page longer like 2 hours. Time enough to self resolve". 7200 s, page only, widened per
  §3 S4.
- **D-OP8 (Q8):** the Bond bench test waits for the operator; until then Bond fans run `off_unverified`.

## 3. Deliverables

### S3a: chatter mode wiring (CHATTER-MODE-SELECT-NOT-WIRED-1). Tier 2.

**What.** One owner for `CONF_CHATTER_MODE`: the INTEGRATION entry, where the operator-facing select lives. The room
resolver `_chatter_mode` reads the integration entry's option (one helper `chatter_mode_option(hass)`), falling back to
the CM entry's option, then `DEFAULT_CHATTER_MODE`. The module kill const `CHATTER_QUARANTINE_ENABLED` keeps its
short-circuit. Cache invalidation: the select's `async_select_option` and the integration entry's update listener
flush the helper's cache (the `nm_cycle_a` cache flushes only on CM updates, so it is not reused for this key). The
`__init__.py:5045-5066` migration is read in the build and pointed at the same owner.
**Why Tier 2, not 1:** the code is one resolver, but its first live effect is house-wide (act has never run): Garage A/B
ratgdo and the Master Bathroom InvisOutlet (43 of 45 chatter NMs in 14 d) start being quarantined while they chatter.
**Operator decision Q-A (open):** **A (recommended):** act takes effect house-wide as the select already reads (Garage
A/B and Master Bathroom first). **B:** the build sets the select to shadow, the operator turns act on later.
**Invariant.** INV-S3a: the value `_chatter_mode()` returns in every room equals the select's current option (or `off`
when the module kill const is False).
**Acceptance.** Tests `test_chatter_select_write_is_room_mode`, `test_chatter_mode_cm_fallback`,
`test_chatter_cache_flushed_on_select`. Mutation: revert the resolver to `nm_cycle_a_knob` -> first test RED. Live: the
next chatter NM reads "quarantined" (not "WOULD quarantine (shadow)") and the room's `automation_health.excluded_sensors`
lists the input under client `chatter`.

### S3b: MS600 family by registry model. Tier 2.

**What.** `family_for_model` splits the first token on `[\s\-_]` (so `ms600-un` -> `ms600`) and `FAMILY_BY_MODEL_ID`
gains `"ms600-un"`. The resolver reads the registry `model` field (where `ms600-un` lives; `model_id` is None). The name
regex fallback stops being what keeps the bit out of the witness list. The bit's filing stays `motion_sensors` (settled).
**Behaviour change, per room (rev 1 wrongly said "none").** After S3b a tick where only the MS600 bit is on becomes
radar-sole, so the RADAR recheck route becomes reachable where it was not; the recheck window family factor becomes 1.5.

| Room | Fan Mode | Paused today | Radar-route recheck after S3b |
|---|---|---|---|
| Guest Bedroom 1 | room_temperature (URA-owned) | yes (Automation off) | eligible once unpaused (HA-ROOM-AUTOMATION-UNPAUSE-1): the recheck may pause GB1's Bond fan by day. New behaviour, intended |
| Guest Bedroom 2 | off | yes | still vetoed `fan_control_off` (the radar route is unchanged) |
| Media | off | yes | still vetoed `fan_control_off` |

D2 witness: unchanged in effect (the regex already excluded the bit). P24 freshness: unchanged (reads `motion_detected`).
**Invariant.** INV-S3b: every MS600 device record resolves to the radar family by registry `model`, and no other live
(model_id, model) pair changes family (golden over every live device; the fixture names which device record owns each
MS600 entity, since each room has two).
**Acceptance.** Tests `test_family_ms600_hyphen_model_is_radar`, `test_family_golden_live_models`,
`test_gb1_radar_route_eligible_after_s3b`, `test_media_bit_tick_is_radar_sole`. Mutation: revert the split -> first
test RED. Live: `binary_sensor.media_room_occupied` radar-sole tick attribute true when only the bit is on.

### S1 (K2): P22 off-pulse tolerance. Tier 2-DB. Approved (D-OP1). After S3b.

**What.** In the stamp loop (`coordinator.py:3713-3727`), for an input whose class is motion (below):
- **New run:** stamp `_sensor_on_since[s] = on_state.last_changed` (rev 1 left tick `now` vs `last_changed` open; one rule
  now: always `last_changed`; this starts the clock up to one poll earlier than today, stated).
- **Observed off:** `_p22_off_since[s] = off_state.last_changed` (OVERWRITE with the CURRENT off, never setdefault, so two
  polls inside two different short gaps never add up). Pop the run when `now − _p22_off_since[s] ≥ tolerance`.
- **Observed on with an open off:** gap = `on.last_changed − _p22_off_since[s]`; gap < tolerance keeps the run, else the
  run restarts at `on.last_changed`. Clear `_p22_off_since[s]`.
- **Off no tick saw (sub-tick):** on a tick that reads `on` with `on.last_changed` newer than the previous tick that read
  it `on`, the off happened between them and lasted at most `on.last_changed − _p22_last_on_tick[s]`; below tolerance
  the run continues, else it restarts at `on.last_changed`. (`_p22_last_on_tick` RAM.)
- **Unavailable / unknown:** does not run the 4 h clock. A dead stretch ≥ tolerance ends the run (the next `on` starts a
  fresh run at its `last_changed`); a shorter one is treated like an off pulse. So a sensor dead for 4 h that returns `on`
  is never excluded at once.
- Radar class and unknown family: tolerance 0, i.e. exactly develop (pop on any observed not-on).
- `_p22_off_since` / `_p22_last_on_tick` are RAM (a restart with the sensor off pops after the boot guards, as today).
- Tolerance 0 = develop byte-identical.

**Class gate (SENSOR_FLEET_CLASSES, not `is_fan_immune_witness`).** NEW pure `sensor_capability.is_still_holder(cap)`:
True for CONF kind `mmwave` (the `presence_sensors` list), a radar family (`RADAR_SENSOR_FAMILIES`, incl. MS600 after
S3b), kinds `bed`, `camera_presence`, `ble_presence`, and a `CONF_SENSOR_CAPABILITIES` override saying so. Motion class =
not a still holder AND a known non-radar family (ZG-204ZV, PIR families) or kind `motion`/`pir`/`pir_split` with a known
family. Unknown family (ESPHome boards, PRESENCE §10 #9) = tolerance 0.

**Impact, stated plainly (corrected).** A motion-class sensor that holds `on` with short blips is excluded by its room
4 h after the run started and stays excluded across the blips. Affected: room `STATE_OCCUPIED` (the room can time out
and vacate), and through it `hvac_occupied`, the HVAC zone rollup, HVAC retreat (row-1, D6) and the HVAC zone vacancy
sweep (lighting denomination). NOT affected: the presence zone tier, nobody-home, path β, the census and house state,
which read the substrate raw and ignore room exclusions (STEP-EXCLUDE-4); the only presence-side reader that changes is
the crossing anchor (S2 / P3-D8). A real occupant is excluded only if every off gap in 4 h is under 10 s; a ZV drops in
30-70 s on a still person; whether a fidgety person produces sub-10 s gaps for 4 h is measured by step 0, not argued.

**Consumers (every reader of the P22 verdict).**

| Consumer | file:line | Trust / display | Effect of S1 |
|---|---|---|---|
| Room fusion legs via `_fusion_filter_active` | `coordinator.py:2586-2597`; call sites `:2317`, `:4016-4058` | trust (room occupied) | excluded longer; room vacates |
| Trigger-source attribution loops | `coordinator.py:4040-4060` | display (occupancy_source / provenance) | the excluded input stops being named as the source |
| `STATE_MOTION_DETECTED` -> `_last_motion_bit_time` (P24 failsafe freshness) and recheck mid-flight motion cancel | `coordinator.py` motion block; `presence_fan_recheck.py:1147` | trust | an excluded ZV stops refreshing P24 (P24 can now fire where the ZV was the only fresh bit) and stops cancelling a recheck |
| Live on-set / radar-sole ring | `_live_on_set` `:6158-6166`, `_radar_sole_on_set` `:6168-6175`, caller `:4074` | trust (recheck eligibility, D1b ring feeding D2) | a room with a P22-excluded ZV and an on radar becomes radar-sole: the radar recheck route and D2 demotion become reachable there |
| Fan-immune witness (D2) | `_fan_immune_motion_witness_on` over the filtered list | trust (D2) | an excluded ZV is no witness (intended) |
| `_is_live_end` quarantine | `coordinator.py:2790-2796`; `occupancy_substrate._is_live_end` `:927` | trust (dead-camera hold end) | a stuck input cannot end a camera hold for longer (correct) |
| Crossing anchor P3-D8 / S2 | branch `crossing_vision.py:1305-1311` | trust (anchor, shadow today) | the upguest ZV stops holding the anchor (the goal) |
| Duty-cycle detector | `coordinator.py:3791+` | trust | none (reads its own ring; confirmed by the completeness review) |
| Stuck NM | `_emit_p22_stuck_sensor_for_tick` `:2404-2430` | display | one page per (room, sensor, day); `on_hours` counts across blips |
| Persistence | `:2437-2570` | restore | unchanged shape (`_sensor_on_since` only) |
| Room sensor attrs | `sensor.py:2526`, `:2597` | display | stable `on_since` |
| `sensor.ura_stuck_signal_watchdog` | `sensor.py:5728-5730` | display | lists it for longer |
| S5 stuck fan check | §3 S5 | trust (actuation) | new consumer |

**Producer / fire check.** One writer (the loop) plus the restore writer. P22 `continuous` NMs: 4 in 14 d. Replay of
11-15 upguest predicts exclusion from 12:51:52 with no re-arm at 13:51 / 14:14 / 14:31 / 14:32 (step 0 confirms).
**Tier 2-DB:** shared primitive in every room; indirect house-side reach is through HVAC and the anchor only, but the
house-state minimum (`feedback_tier2db_minimum_arc`) and the per-room blast radius justify three reviews (A correctness +
timestamps; B lifecycle: restart, reload, unavailable, two rooms listing one sensor; C per-site mutation).
**Invariant.** INV-S1: with tolerance > 0, a motion-class input whose every off and every dead stretch is shorter than
the tolerance is P22-excluded at run start (`last_changed` of its rising edge) + `STUCK_P22_HOURS`, whatever the poll
phase; an off or dead stretch ≥ tolerance restarts the run; a still holder, an unknown family and tolerance 0 behave
exactly as develop.
**Knobs.** `STUCK_P22_OFF_GAP_TOLERANCE_S` 10 (rung 1; 0 = develop; Hobeian pulses 1.3-4 s measured);
`STUCK_P22_HOURS` 4.0 (rung 1, replaces the literal; HVAC §9.3 notes it had no knob).
**Acceptance.**
- **Step 0 (go/no-go):** one read-only recorder replay, 7 days, every motion-class input: runs ≥ 4 h S1 would create, per
  room, against BLE / radar ground truth. GO = zero runs overlapping a BLE-confirmed person in the room for > 30 min.
- **Tests:** `test_p22_short_off_pulse_keeps_run`, `test_p22_long_off_resets_run`, `test_p22_two_polls_in_different_short_gaps_keeps_run`,
  `test_p22_subtick_off_bounded_by_last_on_tick`, `test_p22_new_run_stamped_at_last_changed`,
  `test_p22_unavailable_long_restarts_run`, `test_p22_unavailable_short_is_a_pulse`, `test_p22_tolerance_zero_is_develop`
  (golden over the 11-15 upguest sequence), `test_p22_still_holder_no_tolerance` (radar, bed, camera_presence),
  `test_p22_unknown_family_no_tolerance`, `test_p22_restart_with_open_gap`.
- **Mutation:** setdefault instead of overwrite -> `..._two_polls_...` RED; tick time instead of `last_changed` ->
  `..._subtick_...` RED; use `is_fan_immune_witness` as the gate -> `..._still_holder_...` (bed case) RED; let unavailable
  run the clock -> `..._unavailable_long_...` RED.
- **Live:** the next motion-class input holding ≥ 4 h with sub-10 s blips stays in `automation_health.stuck_sensors`
  across the blips (today it drops to `normal` at the first observed blip); one `continuous` NM that day, not two.

### S2 (EDGE = crossing P3-D8b): the anchor's stuck-aware edge and level rule. Tier 2. With P3-D8.

**What.** One room getter decides "this input's `on` is stuck, not a person", used for levels (P3-D8 `_held_inputs`) and
edges (`_on_substrate_edge`). `camera_input_room_stuck_excluded(eid)` returns True only when ALL hold:
1. the exclusion set has a client in `CROSSING_VISION_ANCHOR_STUCK_CLIENTS` for `eid`;
2. **same run (G7):** for `p22_continuous` / `stuck_dutycycle`, the input's current `on` state `last_changed` ≤ the run
   start the exclusion was computed from (`_sensor_on_since[eid]`); a rising edge after an off that the room has not yet
   re-evaluated is a NEW run and counts as a person. For `chatter` the exclusion is honoured while the client is engaged
   (chatter releases after `CHATTER_RELEASE_QUIET_S` of quiet; each flap is the chatter, not a new run);
3. **sleep gate (D-M1 default):** an exclusion held ONLY by `p22_continuous` on a still-holder input is not honoured in
   SLEEP, WAKING or HOME_NIGHT; on a motion-class input it is honoured in any state (Q2 default taken: motion class cannot
   be a still sleeper). The house-state read is a fail-CLOSED wrapper around `_d2_house_state_allows` (missing presence
   or error = treat as a sleep state).
The house wrapper `input_room_stuck_excluded` folds with ALL rooms that list the input agreeing (review D-L1, F12b): an
input listed by two rooms is stuck only if every room that lists it says so. Dead inputs always hold / count (P3-D8 rule
kept: a non on/off state or any stream view).
Edge rule: before `note_rising_edge`, read `substrate.entities_for(room, kind)` (extracted from
`occupancy_substrate.py:382-385`); DROP the edge iff at least one entity reads `on` and every entity reading `on` is live
(view None) and `input_room_stuck_excluded`. Errors, no list, any dead entity -> the edge counts. Counter
`edges_ignored_stuck` on the ledger diagnostics.
**Why the substrate keeps ignoring room exclusions (STEP-EXCLUDE-4).** The substrate is the one raw per-kind truth the
zone tier, night limb, nobody-home and census read; room exclusions are a room-tier trust policy kept out of the zone tier
on purpose (PICK R3-2): a radar P22-excluded at 4 h is often a still sleeper, and the night limb must keep seeing it.
Policy lives in the consumer.
**Producer / fire check.** Single writer of `SIGNAL_SUBSTRATE_KIND_CHANGED`: `OccupancySubstrate._dispatch` (`:954-998`).
Media 11-14/15: 1,435 flaps; they drop only once S3a makes chatter act.
**Invariant.** INV-S2: an anchor sample or window is never released by an input unless every room listing it excludes
it under a stuck client for the SAME run, the input is live, and (for a P22-only still holder) the house is not in a sleep
state; a dead input, a new run and any read error always hold / reset.
**Knobs.** Reused `CROSSING_VISION_LEDGER_ANCHOR_IGNORES_STUCK` (False = no level release, no edge filter),
`CROSSING_VISION_ANCHOR_STUCK_CLIENTS`; NEW `CROSSING_VISION_ANCHOR_P22_SLEEP_GATE` True (rung 1; False = honoured in any
state).
**Acceptance.** Tests `test_edge_stuck_excluded_only_on_input_ignored`, `test_edge_one_live_unexcluded_on_counts`,
`test_edge_dead_input_counts`, `test_edge_new_run_after_long_off_counts` (G7), `test_level_new_run_holds`,
`test_p22_still_holder_in_sleep_holds_and_counts`, `test_p22_motion_class_in_sleep_released`,
`test_chatter_in_sleep_ignored`, `test_two_room_input_needs_both`, `test_house_state_error_fails_closed`,
`test_edge_kill_switch_restores`. Mutation: drop the same-run check -> `..._new_run_...` RED; any-True fold ->
`test_two_room_input_needs_both` RED; fail-open wrapper -> `..._fails_closed` RED.
**Live (discriminating):** on the next AWAY afternoon with a stuck room, `edges_ignored_stuck` > 0, `held_ignored_stuck`
names the input, and `crossing_ledger_anchor` fires within `LEDGER_EMPTY_RESET_S` + one eval; with another live holder,
`held` names it and `edges_ignored_stuck` stays 0.

### S4 (K1): AWAY room / fan page. Tier 2. Approved at 7200 s (D-OP7).

**What.** Page only, never an entity write. Each presence tick while the house is AWAY (not VACATION, not override), for
each room, a CONDITION holds for ≥ `AWAY_ROOM_HELD_NM_AFTER_S` (7200 s) continuously within the AWAY episode:
- (a) the room reads `STATE_OCCUPIED` with empty `ble_persons` and no room camera person (F4 display fact: the room's fused
  `binary_sensor.<room>_camera_person_detected`; consumer class `notification`, no identity read), and no resident reads
  trust-home; OR
- (b) a configured fan of the room reads `on` (trusted fan), or is untrusted (S6) AND the room had a stuck exclusion
  engaged during this AWAY episode.
Then one HIGH `fire_stuck_signal(kind="away_room_held", key=(room, away_episode_id))` naming the room, condition (a)/(b),
holding inputs + exclusion clients, lights, fans with trust ("fan state assumed: HA may not know it is on"), pause and Fan
Mode. `away_episode_id` = the AWAY entry timestamp, so an episode crossing midnight pages once (the stuck-signal latch is
per (kind, key, day)). LOW recovered when the condition clears. The global stuck-signal kill switch also gates S4 (stated).
**Fire check.** Would have paged media (fan untrusted + P22 / chatter exclusion) at 15:43 and upguest at 15:43 had nothing
cleared; both were cleared by hand inside 2 h, which is the operator's "time enough to self resolve".
**Invariant.** INV-S4: the page never writes an entity, pages at most once per (room, AWAY episode), and never while a
resident reads trust-home.
**Knob.** `AWAY_ROOM_HELD_NM_AFTER_S` 7200 (rung 1; 0 = off).
**Acceptance.** Tests `test_away_room_held_pages_once_across_midnight`, `test_away_room_vacated_fan_on_pages`,
`test_untrusted_fan_pages_only_with_stuck_exclusion`, `test_no_page_with_resident_home`, `test_no_page_with_ble_person`,
`test_recovery_low`, `test_zero_is_off`. Live: first `notification_log` row `kind=away_room_held` naming room and fan.

### S5: a stuck sensor triggers a fan check. Tier 3.

**Trigger (class-correct, D-OP2 / D-OP6).** Eligibility on the stuck route does NOT require the room to read occupied
(G1: once S1 / S3a exclude the input, the room vacates, and the fan must still be checked). It arms when, for N ticks
(`CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS`, reused), an input of the room carries a live trigger-eligible exclusion AND a
configured fan reads `on` (trusted) or is untrusted (S6). Trigger-eligible:
- any house state: `p22_continuous` on a motion-class input (S1 class); `chatter` (engaged, act); `stuck_dutycycle`
  (promoted; already off in SLEEP / WAKING / HOME_NIGHT);
- additionally in AWAY with no resident trust-home and no BLE person in the room (D-OP6): `p22_continuous` on a still
  holder (radar, Matter, MS600 bit after S3b).
Outside AWAY a P22-excluded still holder is not a trigger (a 4 h radar `on` is a sleeper's signature; HVAC C27). The radar
route is unchanged; the stuck route is a second arm route, reason `stuck_trigger`, ladder layer `LAYER_STUCK`.
The arm-time trigger set is captured and PERSISTED (below); during the window eligibility reads the persisted set, not the
live exclusion (S1 pops a P22 exclusion once the input is off ≥ 10 s, which is the expected effect of the fan going off and
must not cancel or re-arm anything).

**Verdict.** VACATED iff every trigger input read `off` for ≥ `FAN_STUCK_CHECK_CLEAR_S` during the window and no
NON-trigger Tier-1 input went `on` (in AWAY: no input other than the triggers). Window = effective window (family factor)
floored at `FAN_STUCK_CHECK_MIN_WINDOW_S`. VACATED -> fan left off (C1a `leave_off`), `apply_fan_recheck_release`.
Not cleared -> `restore_allowed` decides (below): True -> restore ON, outcome `stuck_not_fan`; False -> fan stays off,
outcome `not_restored_fan_mode_off` (Fan Mode Off) or `stuck_not_fan_notified` (paused / person-owned / untrusted), plus
one NM.

**`restore_allowed` (computed at arm, persisted).** True only when ALL: `fan_owner` is `hvac` or `room`; room not paused;
fan trusted (S6); snapshot read the fan `on`; and URA was the last ON writer per the fan oracle ledger (a person-switched
fan under FAN-MANUAL-1 is person-owned). Otherwise False.

**Persistence and every exit path (F8, G5).** `_persist` writes in `snapshot_json` (existing column, no schema change):
`route` (`radar` / `stuck`), `trigger_inputs`, `trigger_technology`, `restore_allowed`, `untrusted`, `written_entities`.
`_restore` honours `restore_allowed` on EVERY path:
- verdict (`_on_pause_window_done`);
- rehydrate PAUSED (`_restore_row` `:1793-1796`, today `_restore(OCCUPIED_CONFIRMED)` = ON);
- every mid-flight cancel (`_evaluate_cancellation_during_tick` `:1108-1190`: sleep state, motion, L1);
- the C1a manual-ON override inside `_restore_after_recheck_body` (leave_off -> ON when a hold is live): on the stuck route
  with `restore_allowed` False the override does not fire; an NM names the live hold instead;
- the Fan Mode Off skip there already writes nothing (kept).
**One exception: `force_restore`** (`:396-407`, the operator's button) still restores ON for a radar-route check and, on the
stuck route, restores ON only when `restore_allowed`; otherwise it ends the check with no write and logs `forced_no_on`.
INV-S5-OFF-ONLY therefore has no exception for Fan Mode Off / paused rooms.
**Cancels on the stuck route:** motion from a TRIGGER input never cancels; motion from a non-trigger input or a BLE L1
person cancels (then `restore_allowed` decides); entering a sleep state cancels only a P22 trigger in a bedroom / media
room.

**The three `_set_fan_state` gates (F3, G4).** New trigger `FAN_TRIGGER_STUCK_CHECK_OFF`:
1. **Owner gate** (`hvac_fans.py:1840-1853`): allowed for any owner incl. None (Fan Mode Off) and for paused rooms, for
   `on=False` only; `on=True` with this trigger returns False at the gate (enforces INV-S5-OFF-ONLY at the chokepoint).
2. **Exemption set** (`:1862-1864`): the occupied harm-stop guard (`:1890-1899`) is bypassed for this trigger (the room
   reads occupied BECAUSE of the stuck input); the manual-ON hold guard (`:1876-1889`) is NOT bypassed (a person's hold
   wins; the arm-time `manual_on_hold_live` veto covers the usual case).
3. **Oracle** (`fan_policy_oracle._compute_off_verdict`): ALLOW for this trigger, beside the recheck-pause ALLOW
   (`:543-544`), under the room lock.
Restore ON on the stuck route uses the existing `FAN_TRIGGER_RECHECK_RESTORE` and only when `restore_allowed`.
**Ephemeral snapshot (G11).** For every Fan Mode Off or paused room, registered in `_room_fans` or not, the stuck route
builds a snapshot from HA state and never touches the `_room_fans` row (`fan_recheck_suppress_until`,
`manual_on_hold_paused_at` stay as they are); no tracking, reconciler or sweep state changes. The build verifies
`actuator_reconciler._resolve_fan` (`:1001-1030`) stays silent for a paused Room-temperature room during the window.
**One check per fan entity (G10).** A busy registry keyed by fan entity id; a second room sharing the fan (Kitchen /
Breakfast Nook) skips with `fan_busy`.
**`phantom_retro` (G9, F12e).** The writer (`memory_writers.py:138`) is a learning signal for "fan caused the hold"; stuck
route OFFs are TAGGED (`source=stuck_check`), not excluded, matched by (room, window from pause to verdict + spindown),
not by context (a Bond-twin write changes the HomeKit twin under another integration's context).

**Veto table (`_evaluate_eligibility` / `_still_armed_eligible`).** "Stuck route" = a `stuck_trigger` arm only; the radar
route keeps every veto exactly.

| Veto | Stuck route | Affects |
|---|---|---|
| `master_off` `:542`, `room_disabled` `:546` | KEPT | — |
| `fan_control_off` `:551` | RELAXED to OFF-only (D-OP4) | HVAC §4.2b "Off -> fan recheck never" (doc update, §7) |
| `room_paused` `:556` | RELAXED, the ONLY exception to pause (D-OP3), own kill switch | pause keeps: no lights, no covers, no other fan automation (zone sweep, comfort, sleep-onset, pre-arrival all still skip). D2 backstop: `is_recheck_eligible` keeps reading the RADAR route only, so a paused room's D2 demotion is unchanged (test) |
| `sleep_state` `:575-579` | KEPT for P22 triggers in bedroom / media; not applied to chatter / duty-cycle triggers | v4.7.13 keep-on contract |
| `not_occupied` `:583` | REPLACED by the stuck trigger condition (G1) | — |
| `override_occupied` `:605` | KEPT | operator intent |
| `capability_bootstrap` / `not_radar_sole` `:616-618`; legacy `mmwave_history_short` / `not_mmwave_sole` `:622-626` | REPLACED by the stuck trigger (both routings) | radar-sole ring unchanged |
| `no_fan_configured` `:634` | KEPT | — |
| `no_fan_on` `:636` | KEPT for trusted fans; skipped for untrusted (S6) | — |
| `boot_settle` `:640` | KEPT | — |
| `manual_off_cooldown` `:646`, `manual_on_hold_live` `:652` | KEPT where the fan has a `_room_fans` row | FAN-MANUAL-1 |
| `fan_quarantined` `:656` | KEPT | reconciler flap counter |
| `rate_cap` `:669` | KEPT, plus `FAN_STUCK_CHECK_MAX_PER_EPISODE` per (fan, exclusion episode) | — |
| `no_person_coord` `:674`, `ble_l1` `:683` | KEPT | — |
| `ble_l2` / tier ladder `:690-719` | KEPT outside AWAY; in AWAY the D-OP6 condition already requires no BLE person in the room, and L2 adjacency is kept | — |
| `trust_sensors_off` `:727` | KEPT: a room with `fan_recheck_trust_sensors_ok` False gets no stuck route (stated, not silent; default True `const.py:903`) | — |
| NEW `still_holder_on` | veto outside AWAY: a NON-excluded still-holder input reads `on` | D-OP6 |

**Zero-fire trip-wire (G8).** Computed from the DB, not RAM counters: a daily job compares 14 days of `anomaly_log` stuck
rows that engaged an exclusion (`continuous`, `chatter` act, `dutycycle` promoted) in rooms with a configured fan against
`memory_episodes fan_recheck_outcome` rows with `route=stuck`; engaged ≥ 1 and stuck outcomes 0 -> one LOW NM
`fan_stuck_check_zero`.
**Forward trace.** trigger -> arm -> OFF -> verdict -> room release -> HVAC zone vacancy; each link pinned by a test.
**Invariants.**
- **INV-S5-OFF-ONLY:** in a Fan Mode Off or paused room, URA issues only `fan.turn_off` to that room's fans, on every path
  (arm, pause, verdict, cancel, rehydrate, C1a, force).
- **INV-S5:** the stuck route writes OFF only when a trigger-eligible exclusion (per house state, D-OP6) is live on an input
  of the room, no veto in the table holds, and the fan has no other live check; it writes ON only when `restore_allowed`.
**Knobs (rung 1).** `FAN_STUCK_CHECK_ENABLED` (kill switch; ships ON once Tier 3 passes, "no shadow mode");
`FAN_STUCK_CHECK_ALLOW_PAUSED` True (D-OP3 kill switch); `FAN_STUCK_CHECK_ALLOW_FAN_MODE_OFF` True;
`FAN_STUCK_CHECK_AWAY_ADMITS_RADAR` True (D-OP6; False = radar refusal in every state); `FAN_STUCK_CHECK_CLEAR_S` 30
(upguest ZV cleared within ~30 s); `FAN_STUCK_CHECK_MIN_WINDOW_S` 180 (MS600 90 s × 2); `FAN_STUCK_CHECK_MAX_PER_EPISODE`
1; `FAN_STUCK_CHECK_ZERO_DAYS` 14 (0 = off).
**Tier 3.** New writer into the shared 5-state machine, person-owned fans in paused rooms, a contract change, HVAC
handshakes. Two plan reviews incl. framing G; four code reviews; orchestrator re-grep of every fan writer and the three
gates; operator checkpoint before deploy.
**Acceptance.**
- **Tests:** `test_stuck_route_arms_after_room_vacated` (G1), `test_stuck_route_arms_on_p22_motion_class`,
  `test_p22_radar_not_trigger_outside_away`, `test_away_admits_p22_radar_and_ms600_bit`, `test_chatter_triggers_any_class`,
  `test_still_holder_on_vetoes_outside_away`, `test_ble_l1_vetoes`, `test_sleep_bedroom_p22_vetoed`,
  `test_fan_mode_off_writes_off_only` (fails on ANY turn_on / set_percentage / set_preset_mode / toggle to the fan in a
  Fan Mode Off or paused room, across arm, pause, verdict, cancel, rehydrate, C1a and force),
  `test_rehydrate_paused_stuck_no_on`, `test_trigger_input_motion_does_not_cancel`, `test_s1_pop_during_window_no_cancel`,
  `test_c1a_hold_no_on_when_restore_disallowed`, `test_force_restore_stuck_no_on_when_disallowed`,
  `test_stuck_off_not_suppressed_by_occupied_guard`, `test_stuck_off_passes_owner_gate_fan_mode_off`,
  `test_stuck_on_refused_at_owner_gate`, `test_stuck_off_allowed_by_oracle`, `test_paused_room_d2_backstop_unchanged`,
  `test_ephemeral_snapshot_leaves_room_fans_row`, `test_one_check_per_fan_entity`, `test_phantom_retro_tagged`,
  `test_outcome_records_trigger_technology`, `test_not_cleared_fan_mode_off_stays_off`, `test_zero_fire_from_db`.
- **Mutation:** drop the owner-gate branch -> `..._owner_gate_fan_mode_off` RED; drop the occupied exemption ->
  `..._occupied_guard` RED; drop `restore_allowed` from rehydrate -> `test_rehydrate_paused_stuck_no_on` RED; let a trigger
  input cancel -> RED; drop the AWAY condition -> `test_p22_radar_not_trigger_outside_away` RED.
- **Replay fixtures (discriminating):** upguest 11-15 (ZV P22, AWAY, Fan Mode Off, paused, trusted Tuya fan): one
  `fan.turn_off`, ZV clears ≤ 30 s, VACATED, fan left off. Media 11-15 (Matter P22 + Meross chatter, AWAY, Fan Mode Off,
  paused, untrusted Bond fan): one `fan.turn_off` on the Bond twin, `off_unverified`, both clear, VACATED. Other failure
  (sensor stuck for a non-fan reason): `stuck_not_fan_notified`, fan off, NM.
- **Live:** the first `fan_recheck_outcome` row with `route=stuck` names the trigger and its technology.

### S6: assumed-state fans (Bond). Tier 3 with S5.

**Trust classification (registry only, F11).** A configured fan is UNTRUSTED iff it reports `assumed_state: true`, or the
operator-declared twin map (`FAN_ASSUMED_STATE_TWINS`, rung 1, keyed by entity-registry id of the configured fan -> registry
id of its Bond-platform twin) names a twin that reports `assumed_state: true`. No name or device-name fallback; a fan with
no declaration is classified by its own flag only.
**Command (D-OP5).** Assume on; send one `fan.turn_off` to the Bond twin; never on-then-off, belief, speed or toggle.
Outcome rows carry `off_unverified` until the bench row says `discrete`; a `toggle` or `suppressed_when_belief_off` row
excludes the fan (NM only, D-OP5). Untrusted fans are never restored ON.
**Write path (F11).** The stuck route's ephemeral snapshot sets `entities = [bond_twin]`, so the write goes through
`_set_fan_state(..., room_name, trigger_path=FAN_TRIGGER_STUCK_CHECK_OFF)` with the three gates and the oracle room lock;
the `fan_off` activity row names both the configured fan and the written twin (`written_entities`).
**Bench test (operator witnesses physically; Media, Game Room, Guest Bedroom 1, Master Bedroom; D-OP8: pending).**
1. Fan physically OFF, HA belief OFF: `fan.turn_off` on the Bond twin. Expect stays off (discrete) / starts (toggle).
2. Fan physically ON via the RF remote (belief OFF): `fan.turn_off`. Expect stops (discrete) / does not stop
   (`suppressed_when_belief_off`).
3. Toggle-only fans: is there a single command that stops a running fan and never starts a stopped one? Record for an
   operator decision; until then excluded.
Recorded per fan in `FAN_ASSUMED_STATE_COMMAND_BY_DEVICE` (rung 1, keyed by Bond device registry identifier).
**Invariant.** INV-S6: an untrusted fan receives only `fan.turn_off` from URA; a fan recorded toggle-only or suppressed
receives nothing; trust is classified only by the registry flag or the declared registry-keyed map.
**Knobs.** `FAN_ASSUMED_STATE_TWINS`, `FAN_ASSUMED_STATE_COMMAND_BY_DEVICE` (rung 1); `FAN_ASSUMED_STATE_TRUST_ENABLED`
True (rung 1; False = every fan trusted, develop).
**Acceptance.** Tests `test_untrusted_by_own_flag`, `test_untrusted_by_declared_twin`, `test_no_name_fallback`,
`test_untrusted_off_unverified_without_bench_row`, `test_toggle_row_excluded`, `test_untrusted_write_hits_bond_twin_through_chokepoint`,
`test_untrusted_never_on`. Live: bench table committed; the next media stuck episode writes one `turn_off` on
`fan.media_room_ceiling_fan`.

## 4. Non-goals

Moving room exclusions into the substrate / zone / census; a per-sensor chatter knob; refiling the MS600 bit; making P22
itself class-aware for room fusion; an AWAY blind fan-off without a stuck trigger; speed / preset / direction writes from
the stuck route; the Tuya duplicate integration and GB2 Fan Mode (operator config items); FAN-ZV-POWERON-TRANSIENT-GATE-1;
moving P24 onto the witness stamp.

## 5. Config-first items (operator, no code)

C1 lower the upguest ZV sensitivity 16 -> 8-12; C2 paused rooms (HA-ROOM-AUTOMATION-UNPAUSE-1 in progress); C3 GB2 Fan
Mode and the 1 %-step cloud entity; C4 drop the duplicate Tuya integration.

## 6. Sequence and tiers

1. Step 0s (read-only): S1 off-gap replay; S6 Bond action lists (bench preparation).
2. S3a chatter wiring (Tier 2) after operator Q-A; S3b MS600 family (Tier 2).
3. S1 (Tier 2-DB), after S3b (the class gate needs the MS600 family).
4. S2 on the P3-D8 branch, reviewed with P3-D8 (Tier 2); P3-D8 + S2 ship after S1.
5. S4 (Tier 2).
6. S5 + S6 (Tier 3, operator checkpoint); Bond fans run `off_unverified` until the bench (D-OP8).
Crossing plan §7: S1, S2, S3a, S3b precede P3-D3. S4-S6 do not gate the crossing arc.

## 7. Doc updates scheduled in the same commit as each ship (F10)

- S3a: PRESENCE §4.3 (chatter mode owner; act live).
- S3b: SENSOR_FLEET_CLASSES MS600 section (registry `model` `ms600-un` resolves radar; regex no longer load-bearing).
- S1: PRESENCE §4.4 / §6 item 3 (P22 tolerance, class gate, `STUCK_P22_HOURS`); HVAC §9.3 (the literal is now a knob).
- S2: PRESENCE header crossing-ledger entry (edge filter, same-run, sleep gate).
- S4: PRESENCE §9 trip-wires.
- S5: HVAC §4.2b Fan Mode table ("Off -> fan recheck: stuck route OFF only") and the paused-rooms bullet (the B-M1
  accepted consequence is superseded for the stuck route by D-OP3 / D-OP4; pause's other promises unchanged); PRESENCE §6
  item 3 (stuck route) and gold-patterns row.
- S6: HVAC §4.2b (untrusted fans, Bond twin writes).

## 8. Operator questions (remaining; recommended defaults)

- **Q-A chatter act:** A (recommended) act house-wide as the select reads (Garage A/B, Master Bathroom first); B shadow
  first, act on the operator's word.
- **Q-B GB1 radar-route recheck after S3b:** accept that GB1's URA-owned Bond fan becomes recheck-eligible by day once the
  room is unpaused. Recommended accept (that is the recheck's purpose).
- **Q-C S4 widening:** page an untrusted fan only when the room had a stuck exclusion in the AWAY episode (else every Bond
  room pages every AWAY). Recommended yes.
- **Bench test (D-OP8):** schedule when home.
Decided: Q1, Q2 (defaults taken), Q4 (D-OP6), Q5 (D-OP3), Q6 (D-OP4), Q7 (D-OP7), Q8 design (D-OP5).

## 9. Change record (history, NOT a build spec)

- **Rev 1 (82b013db):** S1-S6 first draft; D-OP1-D-OP5 recorded mid-draft.
- **Rev 2 (this):** fixes from the two Tier-3 plan reviews.

| Finding | Severity | Where fixed |
|---|---|---|
| Completeness F1 / build-pred 3: chatter never acted (two entries) | HIGH | §1 chatter row; §2 fact 4; S3a (new); §8 Q-A; crossing block corrected |
| F2: S3 changes fan eligibility in GB1/GB2/Media; `model` not `model_id`; two devices per room | HIGH | S3b per-room table, Tier 2, golden names the device |
| F3 / G4: three `_set_fan_state` gates | HIGH | S5 "three gates" + tests per gate |
| G1: stuck route required occupancy | HIGH | S5 trigger (no `not_occupied`), `test_stuck_route_arms_after_room_vacated` |
| G2: media case not delivered | HIGH | D-OP6; S5 AWAY admission; media replay fixture |
| G5 / F8 / G14: restart, cancel, C1a and force paths write ON; route not persisted; S1 pop loop | HIGH / MED / LOW | S5 persistence + every exit path; `force_restore` the one named rule; trigger-input motion does not cancel |
| F4: missing consumers (radar-sole ring, attribution, P24) | MED | S1 consumer table |
| F5: house-impact conflated zones | MED | S1 impact (corrected) |
| F6: wrong class predicate; S3 before S1 | MED | `is_still_holder`; §6 order |
| F7 / G6: S1 spec gaps (sub-tick, stamp, unavailable, setdefault) | MED | S1 "What" |
| F9: veto table incomplete | MED | S5 veto table (legacy routing, `trust_sensors_off`, ladder) |
| F10: doc updates not scheduled | MED | §7 |
| F11: S6 name test; write path | MED | S6 registry-only twin map; write path |
| G7: edge-filter race | MED | S2 same-run rule + tests |
| G8: zero-fire window had no store | MED | S5 DB trip-wire |
| G9: phantom tagging by context | MED | S5 tag by (room, window) |
| G10: shared fan two checks | MED | S5 one check per fan entity |
| F12a extract comprehension; F12b two-room input; F12c fail-open gate | LOW | S2 |
| F12d S4 midnight, F2/F4 fact, kill switch | LOW | S4 |
| F12e phantom cite; tag not exclude | LOW | §1, S5 |
| F12f trip-wire producer | LOW | S5 (anomaly_log rows) |
| F12g formatting | LOW | §2 rewritten |
| G11 ephemeral snapshot for every Off / paused room | LOW | S5 |
| G12 Bond source at 2026.11.1 | LOW | §1 Bond row |
| G13 S4 misses vacated-with-fan-on | LOW | S4 condition (b), D-OP7 |
