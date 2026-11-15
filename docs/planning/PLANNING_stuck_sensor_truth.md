# PLANNING: stuck-sensor truth and its consumers (anchor prerequisites for crossing-vision P3-D8, the stuck-triggered fan check, assumed-state fans)

Cards: MEDIAROOM-FAN-LEFT-ON-STUCK-SENSORS-1 (incl. INSTANCE_2026_11_15_upguest), CENSUS-DECONFLICTION-LEDGER-1
(INSTANCE_2026_11_15_ledger_unknown_since_boot), VISION-CROSSING-ANALYSIS-1 (P3-D8 review D/G: G-1, G-2, D-M1).
Arc: identity / vision / census (charter `docs/planning/ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`).
Charter goal served by S1-S3: "make census almost bullet proof at entry... You could even essentially base census
entirely on this". Door vision cannot reach the census (bars a / e, F-LEAD) without an empty-house anchor, and the anchor
has not fired once since the ledger went live (2026-11-14 16:06). S4-S6 serve the fan card (operator 2026-11-15).
Written 2026-11-15 by ura-planner on develop b33dd68a. The P3-D8 code is read from `feature/crossing-p3-first` @ 48d4bc94
(built, reviewed SHIP, NOT merged).

Read first, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (1149 lines incl. §10 ledger),
`docs/architecture/SENSOR_FLEET_CLASSES.md`, `docs/reviews/code-review/v_crossing_p3_first_review_D_G.md`, both 11-15
audits (`AUDIT_upguest_fan_held_occupancy_2026_11_15.md`, `AUDIT_mediaroom_fan_left_on_stuck_sensors_2026_11_15.md`),
the card and its INSTANCE field, `.claude/skills/ura-arc/SKILL.md`, crossing plan P3-D8 / §6 / §7. No §10 claim is
re-asserted. HVAC: S4 and S5 touch HVAC fan surfaces (`hvac_fans.FanController`); the HVAC STATE_OF_PLAY doc was NOT read
completely by this planner (disclosed gap). The S4/S5 build brief MUST require the builder and every reviewer to read it
completely first, and the plan reviewer to check S4/S5 against its §10 ledger before approval.

---

## 0. Why a separate plan (ura-arc rules 5 and 6)

- **One clean document per scope (rule 5).** The crossing plan's scope is the vision PRODUCER (counts, ledger, arrival
  record). Five of the six deliverables here change room-tier and fan code (the P22 primitive, the chatter knob, the
  model safety net, the recheck state machine, Bond fans). Layering them into the crossing plan would mix a room-tier
  shared primitive and fan actuation into a vision spec and force every vision reviewer to own fan safety. The one
  deliverable that edits crossing-vision code (S2, the edge filter) is a P3-D8 sibling and is ALSO written into the
  crossing plan as a short P3-D8b pointer, so the crossing plan stays complete for its own reader.
- **Seam / merge check (rule 6).** Seams, decided:
  - S1 (K2) changes `_sensor_on_since`, which P3-D8 consumes through the `p22_continuous` client. Different function,
    same value: SEAM, not merge. Recorded in both docs; S1 ships before P3-D8 is relied on (crossing §7).
  - S2 edits `crossing_vision._on_substrate_edge`, the same file as P3-D8 and the same branch family: built ON
    `feature/crossing-p3-first` (or after its merge) so P3-D8 and S2 share one getter and one review.
  - S4/S5 change `presence_fan_recheck` and `hvac_fans` (fan cards FAN-RECHECK-*, FAN-MANUAL-1, FAN-LAYER-2). No other
    in-flight plan edits those functions (grep of `docs/planning/PLANNING_*` for `pause_for_recheck` /
    `_evaluate_eligibility`: only the shipped fan-noise Rev 2 and paused-rooms plans). No merge needed.
  - Interior plan (`PLANNING_vision_interior_sightings.md`): no shared function; its ship 5 owns the `deconflict_house`
    signature, untouched here. Census plan (`PLANNING_census_deconfliction.md`): consumes the anchor only through the
    ledger; untouched. NVR witness W2: camera-stream client stays out of every stuck set here.
- Arc map: add one row "stuck-sensor truth (S1-S3) -> unblocks crossing P3-D8 anchor" before step 2b.

## 1. Institutional context verified

Greps re-run on develop b33dd68a unless marked (branch = `feature/crossing-p3-first` @ 48d4bc94).

| Proposed piece | Verdict | Evidence |
|---|---|---|
| P22 continuous-on timer | REUSED, changed | `_sensor_on_since` `coordinator.py:400`; hours literal `_stuck_sensor_hours = 4.0` `:401` (not a knob today); stamp/pop loop `:3713-3727` (pop at `:3727` on ANY observed off); set builder `_p22_stuck_sensor_set` `:2375-2400`; promote `p22_continuous` `:3757-3762`; persisted `_async_load_stuck_state` `:2437-2470`, snapshot `:2495-2507`, payload `:2558-2570` |
| Off-gap tolerance constant | NEW `STUCK_P22_OFF_GAP_TOLERANCE_S` | 0 hits for `OFF_GAP` / `off_gap` / `P22_` in `const.py`, `coordinator.py`, `config_flow.py`, `options_flow.py`, plans. The audit's name `P22_OFF_GAP_TOLERANCE_S` is renamed to the STUCK_ family prefix |
| P22 hours knob | NEW `STUCK_P22_HOURS` (rung 1, value 4.0) | replaces the literal at `:401` (Numbers Get Knobs); no CONF_ equivalent (`CONF_STUCK_SENSOR_*` are duty-cycle only, `const.py:5980-5989`) |
| Readers of `_sensor_on_since` | enumerated §3.1 | `coordinator.py` only + `sensor.py:2526`, `:2597` (display attrs) |
| Room stuck getter | REUSED from branch | `camera_input_room_stuck_excluded` (branch) beside `camera_input_room_quarantined` `coordinator.py:2790-2796`; wrapper `input_room_stuck_excluded` branch `camera_stream_health.py:1245-1254` over `_ask` `:1091-1103` |
| Anchor edge hook | REUSED, changed | `_on_substrate_edge` branch `crossing_vision.py:1334-1341` -> `note_rising_edge` `crossing_ledger.py:398-401` -> `_edge_since_sample` blocks the sample `:480`, resets `_t_start` `:498-499` |
| Per-(room, kind) entity list | NEW read-only getter `OccupancySubstrate.entities_for(room, kind)` | substrate holds `_entity_to_room_kind` (`occupancy_substrate.py` ctor); public getters today: `tier1_entity_ids` `:1025`, `last_edge_entity_for` `:1004` (set before `_dispatch`, `:920` region, but NOT on the `recheck_entities` path, so it cannot be the filter's source) |
| House-state gate for D-M1 | REUSED `_d2_house_state_allows` `coordinator.py:2334` | same predicate the duty-cycle promotion uses (`:3339`) |
| Chatter act/shadow | REUSED knob, CONFIG | ONE global Select `select.ura_chatter_mode` (`select.py:973-1007`, CM entry, `CONF_CHATTER_MODE` `const.py:6247`, default shadow `:6256`); NO per-sensor knob (grep `chatter` in `config_flow.py` / `options_flow.py` / room options: none per entity). **Live read 2026-11-15 ~16:00 CST: `select.ura_chatter_mode` = `act`, last_changed 15:47:51 (no user context; a restart restores it).** The 11-14 / 11-15 media NMs said "WOULD quarantine (shadow)", so the mode changed after them. Whether the STORED option is `act` is unverified (S3 step 0) |
| MS600 model safety net | REUSED table, changed | `FAMILY_BY_MODEL_ID` `sensor_capability.py:385` (`"ms600 9.0.0"` `:400`), `FAMILY_BY_MODEL_TOKEN` `:429-430` (`"ms600"`), `family_for_model` `:436-450` splits on whitespace, so `ms600-un` -> `ms600-un` -> unknown; `fan_veto.resolve_sensor_family` `fan_veto.py:81-110`; unknown falls back to the name regex `fan_veto.py:124-127` (the REGISTRY-NOT-NAMES residual) |
| AWAY-while-held page | NEW producer, REUSED sender `fire_stuck_signal` (`_stuck_signal_nm`) | opposite-direction sibling `zone_hold_all_away` `presence.py:4478-4570`, `ZONE_HOLD_ALL_AWAY_NM_BOUND_S` `const.py:855`; 0 hits for `away_room_held` / `AWAY_ROOM_HELD` |
| Stuck-triggered fan check | EXTEND `presence_fan_recheck` (vetoes `:542-727`, pause `:810-880`, verdict `:889-912`, restore `:915+`) and `hvac_fans.pause_for_recheck` `:2148-2205` / `restore_after_recheck` `:2207+` | 0 hits for `stuck` / `exclusion` / `chatter` in `presence_fan_recheck.py` (audit §5.1, re-run) |
| Fan-state trust | NEW, REUSED HA flag | URA reads `assumed_state` nowhere (grep 0); HA core `bond/entity.py:62` `_attr_assumed_state = is_bridge and not trust_state`; live: the four bond-platform twins read `assumed_state: true` (`fan.media_room_ceiling_fan`, `fan.game_room_ceiling_fan`, `fan.guest_room_down_ceiling_fan`, `fan.ceilingfan_fanimaton_rf_masterbedroom`, read 2026-11-15) |
| Bond belief service | REUSED HA | HA `bond/services.yaml`: `set_fan_speed_tracked_state`, `set_switch_power_tracked_state`; `fan.py:132-140` `async_set_power_belief` -> `Action.set_power_state_belief`; `async_turn_off` `fan.py:192-196` always sends `Action.turn_off()` (`TurnOff`) whatever the device supports (fetched from github `home-assistant/core` dev, 2026-11-15; the HA install's own copy could not be read over `ssh ha`: the SSH add-on has no docker socket. Version drift is a named risk for S6 step 0) |

Prior plans consulted: `PLANNING_crossing_vision.md` (P3-D8, §6, §7), `PLANNING_stuck_signal_watchdog.md` (D2), the
STUCK-SENSOR-1 plan (shipped v5.75.0, card stale), `PLANNING_fan_noise_running_rejection.md` (Rev 2 C1a/C2/C3/C4),
the paused-rooms plan (ROOM-OVERRIDE-SWITCH-FORGOTTEN-1), `PLANNING_mmwave_corroboration_tier3.md` D6 (parked,
observability only). Memory: `feedback_dead_sensor_is_faulty_equipment`, `reference_sensor_fleet_classes`,
`feedback_marginal_benefit_pushback`, `feedback_suppression_needs_discharge`, `feedback_registry_not_name_guessing`.

## 2. The facts this plan stands on (from the evidence, checked)

1. Upguest: ZG-204ZV (motion-class, registry `model_id`) held the AWAY house's room; P22 fired 12:51:52, a 1.8 s off
   pulse seen at 13:51:48 popped `_sensor_on_since` (`coordinator.py:3727`) and re-armed 4 h. Fan-off test 14:37:30:
   the ZV went off within ~30 s and stayed off 6.5 min; the room vacated ~5 min later. One trial; the fan drove it.
2. Media: Matter radar (presence class) P22-excluded at 4 h (23:41); the Meross `..._sensor_presence_motion` bit
   (radar-derived, filed `motion_sensors`) flapped 1,435 times in 18.2 h (longest quiet 10.5 min) and kept the room;
   each flap is a substrate rising edge that resets the anchor window (900 s).
3. **P22 fires on presence radars today.** The stamp loop iterates `motion_sensors + mmwave_sensors + occupancy_sensors`
   with no class gate (`coordinator.py:3713`); the media Matter radar (`presence_sensors`) was P22-excluded 11-14 23:41
   (`anomaly_log` 352219). So "P22 excluded" means "still person OR stuck" for a radar, and "stuck" only for a
   motion-class sensor.
4. `select.ura_chatter_mode` reads `act` live (above).

## 2a. Operator decisions recorded (2026-11-15)

- **D-OP1 (S1 approved).** "Yup" to "a short off-pulse shouldn't restart the 4-hour stuck clock".
- **D-OP2 (motion-class sensors admitted to the stuck fan check).** "Yup. Little harm. Or define radio based motion sensors.
  But better to admit motion sensors. Fans are motion although pir resists better". All motion-class inputs trigger
  (PIR, ZV mmWave-motion, radar-derived motion bits). Technology is classified through the registry model and
  SENSOR_FLEET_CLASSES (`sensor_capability` kind + `fan_veto.resolve_sensor_family`), never names. A PIR stuck under a
  running fan is weaker evidence that the fan is the cause; the recheck does NOTHING different for PIR (same trigger,
  same verdict), but every outcome row records `trigger_technology` (`pir` / `mmwave_motion` / `radar_bit` / `unknown`)
  so per-technology accuracy (`vacated` vs `stuck_not_fan`) can be compared later.
- **D-OP3 (paused rooms: yes).** A stuck-sensor fan check is allowed in a paused room: fault repair, not room automation.
  It is the ONLY exception to pause; pause keeps every other promise (no lights, no covers, no other fan automation).
  Own kill switch `FAN_STUCK_CHECK_ALLOW_PAUSED`.
- **D-OP4 (Fan Mode Off).** "This should be fine for turning off. What we don't want is turning on and active control."
  In a Fan Mode Off room the stuck check may turn the fan OFF; it never turns a fan on, never restores on, never sets
  speed. A not-cleared verdict leaves the fan off and records `not_restored_fan_mode_off`. For a person-owned fan
  (FAN-MANUAL-1) or a fan in a room found occupied, a not-cleared verdict is an NM, not an automatic turn-on.
  - **D-OP5 (untrusted-state fans).** "Makes sense. Assume on. Turn off." See S6.
  Q1, Q5, Q6, Q8 (design) below are therefore DECIDED.

## 3. Deliverables

### S1 (K2): P22 off-pulse tolerance

**What.** An `off` shorter than `STUCK_P22_OFF_GAP_TOLERANCE_S` (10 s) does not end a continuous-on run.
At the stamp loop (`coordinator.py:3713-3727`):
- sensor read `on`: if `_p22_off_since[s]` is set, the gap = (this `on` state's `last_changed`) − `_p22_off_since[s]`;
  gap < tolerance -> keep `_sensor_on_since[s]`; gap ≥ tolerance -> `_sensor_on_since[s] = on.last_changed` (the run
  restarts at the real rising edge, not the tick). Clear `_p22_off_since[s]`. No stamp yet -> stamp as today.
- sensor read not-on: `_p22_off_since.setdefault(s, off_state.last_changed)`; pop `_sensor_on_since[s]` only when
  `now − _p22_off_since[s] ≥ tolerance`.
- Timestamps come from the HA state's `last_changed`, never the tick time, so the 30 s poll cannot stretch a 2 s pulse
  into a 30 s gap. Several transitions between ticks make the measured gap longer (conservative: it resets).
- `unavailable` / `unknown` are NOT `off`: they neither end nor extend the run (dead sensor = faulty equipment; the
  current code treats them as not-on and pops, a latent reset: fixed here, named in tests).
- `_p22_off_since` is RAM only (a restart with the sensor off pops on the first post-settle tick, as today).
- Tolerance 0 = byte-identical to today.

**Impact, stated plainly (house behaviour change).** A sensor that holds `on` with short blips (the upguest ZV, the
Hobeian fading blip) is now excluded by its room 4 h after the run started, and stays excluded across the blips. While
excluded it creates no room occupancy, so the room can vacate (timeout), the zone can empty, HVAC zone vacancy can run,
and NM pages once (`stuck_signal continuous`). A REAL occupant who keeps a motion-class sensor busy for 4 h with
every off gap under 10 s would be excluded; a ZV drops in 30-70 s on a still person (SENSOR_FLEET_CLASSES), and a moving
person produces off gaps above 10 s at `fading_time` 30 s, so this needs continuous motion for 4 h with no gap ≥ 10 s.
For a PRESENCE radar (ZK / ZX / Matter) the same change makes a still sleeper or film-watcher whose radar blips briefly
reach the 4 h exclusion SOONER than today (today a blip re-arms the 4 h). That is the D-M1 class; S1 widens it. Two
gates contain it:
- S1 applies tolerance only to sensors whose capability is NOT a still-person holder
  (`sensor_capability.is_fan_immune_witness` false-family check reused: radar kind / radar family -> tolerance 0, today's
  rule). Knob `STUCK_P22_OFF_GAP_CLASSES` = {motion-class} (rung 1). **Recommended**; operator Q1.
- Downstream, S2 / P3-D8 never release a P22 radar in SLEEP / WAKING / HOME_NIGHT (D-M1 default).

**Producer check.** The value is `_sensor_on_since[s]` (one writer, the loop above; restore writer
`_async_load_stuck_state`). Dependencies: HA `last_changed` (healthy; Z2M `fading_time_2` 30 s), the room tick
(30 s poll + event refresh). Fire check, 14 d: P22 `continuous` NMs = 4 (media x2, GB1, GB2; media audit §4). With S1,
replaying 11-15 upguest: run from 08:51:21 stays continuous across 13:19 / 13:51 / 14:14 / 14:31 / 14:32 pulses ->
excluded from 12:51:52 onward with no re-arm (prediction; S1 step 0 replays it).

**Consumers (every reader of the P22 verdict).**

| Consumer | file:line | Trust / display | Effect of S1 |
|---|---|---|---|
| Room fusion (6 legs) via `_fusion_filter_active` | `coordinator.py:2586-2597` | trust (room `STATE_OCCUPIED`) | excluded longer; room vacates |
| Fan-immune witness for D2 / P24 freshness (`_fan_immune_motion_witness_on` iterates the filtered list) | fan-noise Rev 2 note, `coordinator.py` PIR stamp branch | trust (D2 demotion) | an excluded ZV is no witness: D2 may demote a radar-sole hold in that room (intended: a stuck witness is no witness) |
| S2 `_is_live_end` quarantine (`camera_input_room_quarantined`) | `coordinator.py:2790-2796`, `occupancy_substrate._is_live_end` `:927` | trust (dead-camera hold end) | a stuck sensor's `on->off` cannot end a camera hold for longer (correct) |
| Crossing anchor P3-D8 (`input_room_stuck_excluded`) | branch `crossing_vision.py:1305-1311` | trust (anchor, shadow today) | the upguest ZV stops holding the anchor (the point) |
| Duty-cycle detector | `coordinator.py:3791+` | trust (promotion) | none: it reads its own ring, not `_sensor_on_since` (re-verify in build) |
| Stuck NM `_emit_p22_stuck_sensor_for_tick` | `coordinator.py:2404-2430` | display | one page per (room, sensor, day), unchanged; `on_hours` now counts across blips |
| Persistence snapshot / Store | `:2495-2507`, `:2558-2570` | restore | unchanged shape; `_p22_off_since` not persisted |
| Room sensors `sensor.<room>_*` attrs | `sensor.py:2526`, `:2597` | display | `on_since` stable across blips |
| `sensor.ura_stuck_signal_watchdog` (label map) | `sensor.py:5728-5730` | display | lists the sensor for longer |
| Zone tier / substrate / census / fan recheck | STEP-EXCLUDE-4 | none | NOT honoured (unchanged); S2 and S4 add narrow honouring |

**House-state rule.** S1 changes no house-state code. It can change house state indirectly: a room it vacates can let a
zone empty, and zone occupancy feeds nobody-home and path β. **Tier 2-DB minimum** (memory
`feedback_tier2db_minimum_arc`: house-state-affecting changes get 3 reviews; plus a shared primitive across every room).
Not Tier 3: one site, kill switch, no cost path. Reviews: A correctness + timestamps; B lifecycle (restore, reload,
unavailable, two rooms listing one sensor, D-L1); C per-site mutation.

**Invariant (falsifiable).** INV-S1: with tolerance > 0, a motion-class input whose every `off` is shorter than the
tolerance is P22-excluded at `run_start + STUCK_P22_HOURS` whatever the poll phase; an `off` ≥ tolerance, any radar-class
input, and tolerance 0 behave exactly as develop; `unavailable` / `unknown` never restart a run.

**Knobs.** `STUCK_P22_OFF_GAP_TOLERANCE_S` 10 (rung 1; 0 = develop; why: Hobeian pulses 1.3-4 s measured, ZV still-drop
30-70 s); `STUCK_P22_OFF_GAP_CLASSES` {motion} (rung 1); `STUCK_P22_HOURS` 4.0 (rung 1, replaces the literal).

**Acceptance.**
- **Test:** `test_p22_short_off_pulse_keeps_run`, `test_p22_long_off_resets_run`, `test_p22_pulse_between_ticks_uses_last_changed`,
  `test_p22_unavailable_does_not_reset`, `test_p22_tolerance_zero_is_develop` (golden over the 11-15 upguest sequence),
  `test_p22_radar_class_gets_no_tolerance`, `test_p22_restart_with_open_gap`.
- **Mutation:** use tick time not `last_changed` -> `..._between_ticks_...` RED; drop the class gate ->
  `..._radar_class_...` RED; pop on unavailable -> `..._unavailable_...` RED.
- **Step 0 (measure first):** one read-only recorder replay over 7 days of every motion-class input: off-gap histogram
  (how many runs ≥ 4 h would S1 create, per room, against BLE / radar ground truth). Go/no-go: zero runs that overlap a
  BLE-confirmed person in the room for > 30 min. Discriminates: a real-occupant false exclusion shows up as overlap; a
  fan-latched ZV shows none.
- **Live:** the next time a motion-class input holds ≥ 4 h with sub-10 s blips, `automation_health` keeps
  `stuck_sensors` listing it across the blips (today it drops to `normal` at the first observed blip); `notification_log`
  has one `continuous` row, not two the same day.

### S2 (EDGE): the anchor's stuck-aware edge filter (crossing P3-D8b)

**What.** In `_on_substrate_edge` (branch `crossing_vision.py:1334`), before `note_rising_edge`: read
`substrate.entities_for(room, kind)` (NEW read-only getter); for each entity read `hass.states` and the stream view
(`_csh.entity_stream_view`, same as `_held_inputs`); DROP the edge iff every entity reading `on` is live (view None) and
`_csh.input_room_stuck_excluded` True, AND at least one entity reads `on`. Any dead entity (non on/off state or any
view), any `on` entity not excluded, any read error, or no entity list -> the edge counts (today's rule). Counter
`edges_ignored_stuck` on the ledger diagnostics.

**Why the substrate ignores room exclusions (STEP-EXCLUDE-4) and why the filter lives in the anchor.** The substrate is the
one per-kind raw truth that the zone tier, night limb, nobody-home and the census read; the room's exclusion set is a
room-tier trust policy (P22 / chatter / duty-cycle) that was deliberately kept out of the zone tier (PICK R3-2): a radar
P22-excluded at 4 h is often a still sleeper, and the zone's night limb must keep seeing it. Moving exclusions into the
substrate would change the zone, night, AWAY and census paths at once. Policy lives in the consumer: the anchor alone
decides that a stuck-excluded input's edge is not evidence of a person.

**Rules kept identical to P3-D8 and D-M1.** Same stuck client set (`CROSSING_VISION_ANCHOR_STUCK_CLIENTS`; the
camera-stream client is never in it); dead input = holds / counts; and the D-M1 default: in SLEEP, WAKING or HOME_NIGHT
an input excluded ONLY by `p22_continuous` is not ignored (neither its level in `_held_inputs` nor its edge), because a
P22 radar there may be a still sleeper. Built once as the room getter rule: `camera_input_room_stuck_excluded` returns
True for a `p22_continuous`-only exclusion only when `_d2_house_state_allows()` (`coordinator.py:2334`) is True. One
getter, two consumers (levels and edges): no second rule. Operator Q2 offers the class-aware refinement.

**Producer check.** Edges: `OccupancySubstrate._dispatch` (`:954-998`) is the single writer of
`SIGNAL_SUBSTRATE_KIND_CHANGED`; sources are live state changes and `recheck_entities` (stream discharge). Fire check:
media 11-14/15: 1,435 Meross flaps in 18.2 h (each a kind edge when the kind toggles). After S3 the Meross bit is
chatter-excluded (act), so its edges drop.

**Consumers.** `_on_substrate_edge` is the only crossing reader (one connect, branch `crossing_vision.py:439`); other
subscribers of the signal (zone tracker, room edge handler) are untouched (filter is local to the callback).

**Invariant.** INV-S2: a rising edge resets the anchor window unless every `on` input of that (room, kind) is a live input
its room excludes under a stuck client honoured by the D-M1 gate; a dead input's edge, a non-excluded input's edge, and
every edge in SLEEP / WAKING / HOME_NIGHT from a P22-only radar always reset it.

**Knobs.** Reuses `CROSSING_VISION_LEDGER_ANCHOR_IGNORES_STUCK` (False = no level release and no edge filter) and
`CROSSING_VISION_ANCHOR_STUCK_CLIENTS`. NEW `CROSSING_VISION_ANCHOR_P22_SLEEP_GATE` True (rung 1; False = D-M1 option (a),
release in any state).

**Tier.** Tier 2 (anchor is shadow / display until F-LEAD; one consumer; P3-D8 sibling). Reviewed WITH P3-D8 (one
review set covers both; the D-M1 gate changes P3-D8's getter).

**Acceptance.**
- **Test:** `test_edge_from_stuck_excluded_only_on_input_ignored`, `test_edge_with_one_live_unexcluded_on_counts`,
  `test_edge_from_dead_input_counts`, `test_edge_p22_radar_in_sleep_counts`, `test_edge_chatter_in_sleep_ignored`
  (chatter is not a sleeper), `test_edge_getter_error_counts`, `test_edge_kill_switch_restores`,
  `test_held_p22_radar_in_home_night_still_holds` (P3-D8 level path under the new gate).
- **Mutation:** drop the all-`on` check (any-excluded) -> `..._one_live_unexcluded_...` RED; drop the view check ->
  `..._dead_input_counts` RED; drop the house-state gate -> `..._p22_radar_in_sleep_counts` RED.
- **Live (discriminating):** with S1-S3 live, on the next AWAY afternoon with a stuck room, ledger diagnostics show
  `edges_ignored_stuck` > 0 and `held_ignored_stuck` naming the input, and `crossing_ledger_anchor` fires within
  `LEDGER_EMPTY_RESET_S` + one eval. Under the plausible other failure (some other live holder), `held` names it and
  `edges_ignored_stuck` stays 0: distinguishable.

### S3 (MEDIA): the Meross MS600 radar bit

**Config-first decision.**
0. Step 0 (read-only): read the CM entry's stored `chatter_mode` option and the select's history since 11-14. If the
   stored value is `act` (operator or a prior session set it today), the media chatter half is ALREADY a knob turn: no
   code. Verify the Meross bit was promoted `chatter` after 15:47 (room `automation_health.excluded_sensors`).
1. If it is not stored `act`: the knob is GLOBAL only (`select.ura_chatter_mode`; no per-sensor knob exists). Global
   `act` also excludes the other chatterers: 43 of 45 chatter NMs in 14 d are Garage A/B (ratgdo) and Master Bathroom.
   Act there means those rooms stop counting the chattering input while it chatters (it auto-releases after
   `CHATTER_RELEASE_QUIET_S`). That is the designed behaviour of act, but it is a house-wide behaviour change: operator Q3,
   recommended **global act** (the detector is physics-based: an impossibility burst is not a person, in any room).
2. **Reclassify through the registry model, NOT the sensor class of the bit.** The bit is radar-derived (SENSOR_FLEET_CLASSES
   MS600 section, settled): leave its filing in `motion_sensors` (do not re-litigate); fix the family resolver so the
   registry model `ms600-un` resolves to the generic radar family. Code: `family_for_model` token split on `[\s\-_]`
   (so `ms600-un` -> `ms600`), plus an exact `FAMILY_BY_MODEL_ID["ms600-un"]` row. Effect: the name-regex fallback
   (`fan_veto.py:124-127`) is no longer what keeps the bit out of the witness list; the media bit becomes registry-classified
   radar (no behaviour change today, a rename can no longer flip it).
3. Not chosen: a per-sensor chatter knob (new config surface for one sensor; the global detector is correct by physics);
   moving the bit to `presence_sensors` (settled doc says no).

**Producer / consumer.** `family_for_model` readers: `fan_veto.resolve_sensor_family` -> `is_fan_immune_motion_witness`
(D2 witness, P24 freshness gate, comfort-fan AWAY veto motion leg), recheck window family factor
(`presence_fan_recheck._family_factor` `:1488`), capability radar-sole producer (`fan_veto.is_radar_entity`). For `ms600-un`
the answer moves unknown -> generic radar: witness False (unchanged in effect: the regex already excluded it);
radar-sole ring now counts the media bit as radar-bearing (media ticks driven by the bit become radar-sole, which makes
media recheck-eligible on that condition: intended, and S4 depends on it); recheck window factor 1.5 (MS600 generic).
Fire check: the token path has matched 0 live devices with a hyphen; GB1 / GB2 / Media device records to be read in the
build (registry probe) and every MS600 model string listed in the README.

**Invariant.** INV-S3: every MS600 device resolves to the radar family by registry model, whatever its entity_id; no
non-MS600 model changes family (golden over every live device's (model_id, model) pair).

**Knobs.** none new (`select.ura_chatter_mode` reused, rung 3).

**Tier.** Tier 1 for the resolver fix (one table, golden test) with one review; the chatter knob is a config action.

**Acceptance.**
- **Test:** `test_family_ms600_hyphen_model_is_radar`, `test_family_golden_live_models` (fixture from the registry probe),
  `test_media_bit_radar_sole_tick`.
- **Mutation:** revert the split -> `..._hyphen_...` RED.
- **Live:** `binary_sensor.media_room_occupied` shows the bit classified radar (radar-sole tick attr true when only it is
  on); with chatter act, the next media flap burst lists the bit in `automation_health.excluded_sensors` (client
  `chatter`), and the NM says "quarantined" not "WOULD quarantine".

### S4 (K1): "room held while the house is AWAY with nobody corroborated" trip-wire (recommended default; operator approval pending)

**What.** NM page only; no actuation. Each presence tick: house AWAY (not VACATION, not override) for ≥
`AWAY_ROOM_HELD_NM_AFTER_S`, a room `STATE_OCCUPIED` True, the room's `ble_persons` empty, no camera person, and no
resident's trust state `home` -> one HIGH `fire_stuck_signal(kind="away_room_held", key=(room,))` naming the room, its
holding inputs (`tier1_provenance` + exclusion clients), its lights and fans with a fan-state-trust note ("fan state
assumed: HA may not know it is on" for an S6 untrusted fan), and the room's pause / Fan Mode. Once per episode and per
(room, day); LOW recovered on release. Reuses `fire_stuck_signal` (latching, per-day dedup).
**Producer/consumer.** Producer: presence coordinator tick, reading room coordinators' `data` (display trust only). Consumer:
NM only. Fire check after ship: zero-fire is expected on quiet weeks; trip-wire on the trip-wire is NOT added (its fire
rate is the measurement). Would have fired 11-15 for upguest (~14:07 with N = 900 s) and media (~13:58, it vacated at
13:58:33, so only with N < 870 s).
**Invariant.** INV-S4: the page never writes an entity; it fires at most once per (room, AWAY episode) and never when any
resident reads home.
**Knob.** `AWAY_ROOM_HELD_NM_AFTER_S` 900 (rung 1; 0 = off). Tier 2 (new producer, NM only).
**Acceptance.** Tests `test_away_room_held_pages_once`, `test_no_page_with_resident_home`, `test_no_page_with_ble_person`,
`test_recovery_low_on_vacate`, `test_zero_is_off`. Live: first page names room, input, fans; `notification_log` row
`kind=away_room_held`.

### S5: stuck triggers a fan check (operator 2026-11-15: a real deliverable)

Operator, verbatim: "We could relax these constraints? That would be trivial after checking every impact?"; on turning off
a fan someone is using: "No it doesn't. If it does then stuck sensor means nothing"; on Bond: "Assume state is wrong and
proceed accordingly. Ie toggle on and then off?"

**Planner pushback, stated before the spec (marginal-benefit duty).** "Stuck means stuck" is right for the SENSOR and
wrong for the ROOM when the fan caused the stuck. A fan-latched ZV (the upguest evidence) reads `on` because of the fan,
so it says nothing about whether a person is ALSO there. A guest asleep under a running fan in GB2 is exactly the shape
that latches the ZV and reaches P22 at 4 h. So the trigger is class-correct for the sensor, but the ACTION still needs an
independent "nobody here" test. The plan keeps that test small (a non-excluded still-person holder reading `on`, a BLE
L1 person, or a sleep-state bedroom vetoes) and drops every veto that only existed because the recheck was radar-sole.
Operator Q4 decides whether to keep it; recommended keep.

**Trigger (class-correct, SENSOR_FLEET_CLASSES).** A fan check arms when, for N ticks
(`CONF_FAN_RECHECK_MMWAVE_HISTORY_TICKS`, reused), the room is occupied and EVERY Tier-1 input reading `on` is excluded
by the room under one of:
- `p22_continuous` on a motion-class input (capability not a still-person holder; ZV / PIR / MS600 bit after S3 is radar,
  see next bullet): 4 h continuous on cannot be a still person -> stuck means stuck;
- `chatter` (act): an impossibility burst is not a person, any class;
- `stuck_dutycycle` (promoted; already gated off in SLEEP / WAKING / HOME_NIGHT and needs a disagreeing corroborator).
NOT a trigger: `p22_continuous` on a still-person holder (ZK / ZX / Matter / LD2410 / MS600 radar family). P22 does fire on
those (§2 fact 3), and a 4 h `on` radar is normal for a sleeper; making P22 itself class-aware would change room fusion
house-wide, so the recheck simply refuses those exclusions (policy in the consumer). The existing radar-sole trigger is
unchanged; the stuck trigger is a second arm route with reason `stuck_trigger`.

**Verdict (cannot reuse the radar verdict).** `_on_pause_window_done` (`:889-912`) decides VACATED iff no radar-bearing
input is on; for a motion-class trigger that would read VACATED instantly. Stuck route: VACATED iff every TRIGGER input
read `off` for ≥ `FAN_STUCK_CHECK_CLEAR_S` (30 s; the upguest ZV cleared within ~30 s, the MS600 in 90 s) during the
window and no non-excluded Tier-1 input went `on`. Window = existing effective window (family factor) with a floor of
`FAN_STUCK_CHECK_MIN_WINDOW_S` (180 s). VACATED -> leave the fan off (C1a `leave_off=True`) and `apply_fan_recheck_release`;
not cleared -> in a Fan Mode Off room or for a person-owned / occupied-room fan: leave the fan OFF, NM, record `not_restored_fan_mode_off` (Fan Mode Off) or `stuck_not_fan_notified`; only in a URA-owned (Follow / Room temperature), unpaused room is a trusted fan it observed `on` restored ON (record `stuck_not_fan`) (the sensor is stuck for
another reason: no further fan checks for that sensor until its exclusion ends).

**Gate relaxation, veto by veto (`presence_fan_recheck._evaluate_eligibility` `:542-727`, twin `_still_armed_eligible`
`:1218-1276`).** "Stuck route" below = only for a stuck-trigger arm; the radar-sole route keeps every veto as today.

| Veto | Today | Stuck route | What it affects (consumers) |
|---|---|---|---|
| `master_off` `:542`, `room_disabled` `:546` | kill switches | KEPT | — |
| `fan_control_off` `:551` (Fan Mode Off = person-owned, URA writes nothing, `const.fan_owner` `:1453`) | veto | RELAXED to OFF-only (DECIDED D-OP4): URA may call `fan.turn_off` on that fan through the stuck route and nothing else; no restore, no ON, no speed | Changes the FAN-MANUAL-1 / HVAC Batch D contract "Fan Mode Off = URA writes nothing" (HVAC STATE_OF_PLAY §4.2b, B-M1 ruling "a probe must not turn a person's fan off"). `hvac_fans.pause_for_recheck` returns None for an unmanaged room (`snapshot_room_fan`, `:2158-2160`) and `_restore_after_recheck_body` skips Fan Mode Off (`:2265-2275`): both need a stuck-route branch with an EPHEMERAL snapshot built from HA state (no `_room_fans` row is created, so comfort control, the reconciler (`actuator_reconciler.py:1001-1030`) and the zone sweep still see no owner). Writes go through `_set_fan_state` with a NEW trigger `FAN_TRIGGER_STUCK_CHECK` that the oracle ALLOWs like `FAN_TRIGGER_RECHECK_PAUSE` (`fan_policy_oracle.py` `_compute_off_verdict` `:543-544`) |
| `room_paused` `:556` (Automation off / Manual Mode) | veto | RELAXED, DECIDED D-OP3, the ONLY exception to pause: pause today promises no room-tier lights / switches / covers on occupancy, no HVAC sweep / comfort fans / pre-arrival fans, no recheck arm (§4.5); it does NOT promise "URA never writes a fan" (smoke/CO stop and `turn_off_all_managed` still write). A stuck fan check in a paused room writes OFF only, through the stuck route; the NM says the room is paused | 20 of 47 rooms read paused all week (intent unknown). D2 backstop (`is_recheck_eligible`, `test_paused_room_d2_backstop_not_deferred`) must keep reading the RADAR route only: the stuck route must not make paused rooms "recheck-eligible" for the D2 defer (else D2 stops demoting them). Pinned by a new test |
| `sleep_state` `:575-579` (bedroom / media in FAN_TRUST_STATES) | veto | KEPT for P22 triggers; relaxed for chatter / duty-cycle triggers only (not a sleeper by physics). Operator said a stuck sensor means nobody; the planner keeps this one because the fan that latched the sensor may be cooling a sleeper (pushback above); Q4 | HVAC v4.7.13 keep-fans-on-through-sleep (bedroom) |
| `not_occupied` `:583` | veto | KEPT | — |
| `override_occupied` `:605` | veto | KEPT (operator intent) | — |
| `capability_bootstrap` / `not_radar_sole` `:616-618` | veto | REPLACED on the stuck route by the stuck trigger above | radar-sole ring readers unchanged |
| `no_fan_configured` `:634` | veto | KEPT | — |
| `no_fan_on` `:636` | veto | RELAXED for untrusted-state fans (S6): HA `off` on an assumed-state fan is not evidence it is off; kept for trusted fans (a trusted `off` fan cannot be the cause) | phantom writers (`occupancy_phantom`, `phantom_retro`, `const.py:6292-6296`) key on HA fan edges; they will see the stuck check's writes as edges: stuck-route writes are tagged and excluded from `phantom_retro` (it would otherwise log the check's own OFF as a fan-release phantom) |
| `boot_settle` `:640` | veto | KEPT | — |
| `manual_off_cooldown` `:646`, `manual_on_hold_live` `:652` | veto | KEPT for managed fans (unmanaged fans have no hold row) | FAN-MANUAL-1 time-bounded hold |
| `fan_quarantined` `:656` | veto | KEPT (a flapping actuator is unreliable) | reconciler flap counter |
| `rate_cap` `:669` | veto | KEPT (shared per-room attempts) plus `FAN_STUCK_CHECK_MAX_PER_EPISODE` 1 per (room, exclusion episode) | — |
| `no_person_coord` `:674`, `ble_l1` `:683` | veto | KEPT: a BLE person in the room vetoes | — |
| `ble_l2` / tier ladder `:690-719` | veto | KEPT unchanged | — |
| `trust_sensors_off` `:727` | veto | KEPT | — |
| NEW `still_holder_on` | — | veto on the stuck route: any NON-excluded still-person-holder input of the room (radar family) reads `on` | the planner's independent "nobody here" test |

Other consumers: comfort-fan AWAY veto (`fan_veto.py:496-507`) blocks ON only, unaffected; HVAC zone sweep and
`turn_off_all_managed` unaffected (no ownership change); `SIGNAL_FAN_RECHECK_FINISHED` listeners receive outcome
`vacated` / `occupied_confirmed` plus `route="stuck"` (additive key: the build greps every listener and confirms tolerance);
`memory_episodes fan_recheck_outcome` gains `route`; `fan_recheck_state` sensor attrs gain the route.

**Producer / fire check.** Trigger producers: P22 (4 NMs / 14 d), chatter (45 / 14 d, mostly garage / master bath, which
have no fans in Follow / Off cohorts to check: the build lists every chatter room with a configured fan), duty-cycle (11).
New producer trip-wire: `fan_stuck_check_zero` LOW page when the stuck route has armed 0 times in 14 d while ≥ 1 stuck
exclusion lasted ≥ 30 min in a fan room (silence noticed in code). Forward trace: trigger -> arm -> pause OFF -> verdict
-> release room occupancy -> zone / HVAC vacancy; every link pinned by a test.

**Invariant.** INV-S5-OFF-ONLY: in a Fan Mode Off room (and in a paused room) URA issues only `fan.turn_off` service calls to that room's fans; never `turn_on`, `set_percentage`, `set_preset_mode`, `set_direction` or `toggle`. INV-S5: the stuck route writes a fan only when every `on` Tier-1 input of the room is excluded under a
trigger-eligible client, no non-excluded still-person holder reads `on`, no BLE L1 / L2 veto holds, and (for a P22 trigger)
the house is not in FAN_TRUST_STATES for a bedroom / media room; it writes OFF at most once per (room, exclusion episode)
and writes ON only to restore a trusted fan it observed `on`, or per S6 for an untrusted one.

**Knobs.** `FAN_STUCK_CHECK_ENABLED` False until operator Q4 (rung 1 kill switch; operator mandate "no shadow mode" means
it ships ON once approved); `FAN_STUCK_CHECK_CLEAR_S` 30 (rung 1, measured upguest); `FAN_STUCK_CHECK_MIN_WINDOW_S` 180
(rung 1, MS600 90 s × 2); `FAN_STUCK_CHECK_MAX_PER_EPISODE` 1 (rung 1); `FAN_STUCK_CHECK_ALLOW_PAUSED` True (rung 1, Q5);
`FAN_STUCK_CHECK_ALLOW_FAN_MODE_OFF` True (rung 1, Q6).

**Tier.** **Tier 3**: a new writer into the shared 5-state recheck machine, actuation of person-owned fans in paused rooms,
a contract change (Fan Mode Off), HVAC handshakes. Two plan reviews (completeness + adversarial build-prediction) plus
framing G; four code reviews; orchestrator re-grep of every fan writer; operator checkpoint before deploy.

**Acceptance.**
- **Test:** `test_stuck_route_arms_on_p22_motion_class`, `test_p22_radar_never_triggers`, `test_chatter_triggers_any_class`,
  `test_still_holder_on_vetoes`, `test_ble_l1_vetoes_stuck_route`, `test_sleep_bedroom_p22_vetoed`,
  `test_fan_mode_off_writes_off_only` (fails on ANY turn_on / set_percentage / toggle call to the fan in a Fan Mode Off or paused room, across arm, pause, verdict, cancel and restart-restore paths), `test_not_cleared_fan_mode_off_stays_off_records_not_restored`, `test_outcome_row_records_trigger_technology`, `test_paused_room_off_only_and_d2_backstop_unchanged`,
  `test_verdict_uses_trigger_inputs_not_radar`, `test_not_cleared_restores_trusted_fan`,
  `test_once_per_exclusion_episode`, `test_phantom_retro_ignores_stuck_writes`, `test_zero_fire_tripwire`.
- **Mutation:** drop `still_holder_on` -> its test RED; let a P22 radar trigger -> `test_p22_radar_never_triggers` RED;
  use the radar verdict -> `..._verdict_uses_trigger_inputs...` RED; drop the paused D2-backstop split -> RED.
- **Live (discriminating):** replay of 11-15 upguest as a fixture: P22 at 12:51:52 (S1) -> stuck route arms (paused room,
  Fan Mode Off, AWAY, Matter radar off, no BLE) -> OFF -> ZV clears ≤ 30 s -> VACATED, fan left off. Organic: first
  `fan_recheck_outcome` row with `route=stuck` and the trigger input named; under the other failure (sensor stuck for a
  non-fan reason) the row reads `occupied_confirmed` / `stuck_not_fan` and the fan is restored.

### S6: assumed-state fans (Bond)

**Trust classification (registry, never names).** A configured fan is UNTRUSTED iff it, or a fan entity on the SAME
physical device, reports `assumed_state: true`. Same physical device = shared device-registry identifier or connection,
or `via_device` to the same bridge device AND equal device name, resolved through the registry; if no registry link
exists (likely: the URA-configured entities are the HomeKit twins on separate devices; the media audit did not show a
shared identifier), the operator declares the twin per fan in the bench table (§ below). Live fact: all four Bond-platform
twins read `assumed_state: true`; the four HomeKit twins URA uses carry no flag.

**Command semantics (what the code shows).** HA's Bond fan `async_turn_off` always sends Bond `TurnOff` (`fan.py:192-196`);
HA does not check whether the device template has `TurnOff` or only `TogglePower`. Whether each fan has discrete
TurnOff / TurnOn is a Bond device property (its action list) that HA does not expose as an attribute. **Step 0
(read-only):** read each device's action list (Bond config-entry diagnostics download, small, or the bridge's local
`GET /v2/devices/{id}`), record `TurnOn`, `TurnOff`, `TogglePower` per fan.

**Design (DECIDED D-OP5, operator 2026-11-15: "Makes sense. Assume on. Turn off.").** For an untrusted fan the stuck
check assumes the fan is ON and sends one plain `fan.turn_off` to the Bond-platform twin (never the HomeKit twin). It never
sends on-then-off and never sets a belief first: the operator's earlier "toggle on then off" idea is replaced. This relies
on a discrete Bond `TurnOff`, which makes the call idempotent whatever the real state. Until a fan's bench row says
`discrete`, the check still sends `turn_off` and records `off_unverified` on the outcome row. A fan the bench finds
toggle-only is EXCLUDED from the check (NM only) until the operator decides otherwise. Untrusted fans are never restored
ON. The `no_fan_on` veto is skipped for untrusted fans (S5 table).

**Bench test (one-time, operator witnesses physically, per fan: Media, Game Room, Guest Bedroom 1, Master Bedroom).**
1. Fan physically OFF, HA belief OFF: call `fan.turn_off` on the Bond twin. Expect: stays off (discrete) / STARTS (toggle).
2. Fan physically ON via the RF remote (HA belief stays OFF): call `fan.turn_off`. Expect: stops (discrete) / stops only if
   Bond sends a toggle despite belief OFF (Bond may suppress TurnOff when belief is already off: record what happens).
3. Toggle-only fans only: is there any single command that stops a running fan and never starts a stopped one (a discrete
   OFF among the remote's learned codes)? If yes, record it for an operator decision; if no, the fan stays excluded.
   (Step 1 is the only moment a stopped fan may start; the operator is present.)
Record per fan: `off_command` = {discrete, toggle, suppressed_when_belief_off} (the third = a running fan with belief OFF
did not stop in step 2: treated like toggle, excluded, operator decides). Stored in rung-1 table
`FAN_ASSUMED_STATE_COMMAND_BY_DEVICE` keyed by Bond device identifier (registry), plus the HomeKit-to-Bond twin map.
A fan with no recorded row gets `turn_off` with `off_unverified`; a `toggle` row excludes it (NM only).

**Invariant.** INV-S6: to an untrusted fan URA sends only `fan.turn_off` (never on, toggle, belief or speed); a fan recorded toggle-only receives nothing; trust is classified only by the registry flag or the recorded table, never by entity_id.

**Knobs.** `FAN_ASSUMED_STATE_COMMAND_BY_DEVICE` (rung 1, filled from the bench); `FAN_ASSUMED_STATE_TRUST_ENABLED` True
(rung 1; False = treat every fan as trusted, today's behaviour). **Tier.** Tier 3 together with S5 (same writer).

**Acceptance.** Tests `test_untrusted_by_registry_twin_flag`, `test_untrusted_without_table_row_sends_off_records_off_unverified`, `test_toggle_only_row_excluded`,
`test_discrete_off_once`, `test_untrusted_never_on_off_sequence`,
`test_untrusted_never_restored_on`. Live: bench table committed; the next media stuck episode yields one `turn_off` on
`fan.media_room_ceiling_fan` and a VACATED row.

## 4. Non-goals

Moving room exclusions into the substrate / zone / census (STEP-EXCLUDE-4 stays); a per-sensor chatter knob; refiling the
MS600 bit; making P22 itself class-aware for room fusion; an AWAY blind fan-off independent of a stuck trigger (needs its
own ruling); fan speed / preset / direction writes from the stuck route; the Tuya duplicate integration and GB2 Fan Mode
(config items C3/C4, operator); FAN-ZV-POWERON-TRANSIENT-GATE-1; the P24 failsafe freshness stamp.

## 5. Config-first items (operator, no code)

C1 lower the upguest ZV sensitivity 16 -> 8-12; C2 decide the 20 paused rooms; C3 GB2 Fan Mode and the 1 %-step cloud
entity; C4 drop the duplicate Tuya integration; C5 confirm `select.ura_chatter_mode` = act is intended (S3 step 0).

## 6. Sequence and tiers

1. S3 step 0 (read the stored chatter option; 5 min) and S1 step 0 (off-gap replay) and S6 step 0 (Bond action lists).
2. S3 resolver fix (Tier 1) and S1 (Tier 2-DB) in parallel.
3. S2 on the P3-D8 branch, reviewed with P3-D8 (Tier 2); P3-D8 + S2 ship after S1.
4. S4 trip-wire (Tier 2) once the operator approves.
5. S6 bench test (operator), then S5 + S6 (Tier 3, operator checkpoint).
Crossing plan §7: S1, S2, S3 precede P3-D3 (they are the anchor prerequisites). S4-S6 do not gate the crossing arc.

## 7. Operator questions (recommended defaults)

- Q1 DECIDED (D-OP1); open sub-question: tolerance for motion-class only, radars keep today's reset. Recommended yes.
- Q2 Class-aware anchor gate: release a P22-excluded MOTION-class input in SLEEP / WAKING / HOME_NIGHT too (it cannot be a
  still sleeper); keep the gate for radars. Recommended yes (the D-M1 default stays for radars).
- Q3 `select.ura_chatter_mode` global act (it reads act now; confirm intended; affects Garage A/B and Master Bathroom).
  Recommended keep act.
- Q4 Stuck fan check keeps the independent "nobody here" vetoes (non-excluded still holder on, BLE L1/L2, P22 in a sleep-state
  bedroom). Recommended keep; the fan that latched the sensor may be cooling a person.
- Q5 DECIDED yes (D-OP3). Q6 DECIDED OFF-only (D-OP4).
- Q7 S4 AWAY-while-held page approval, N = 900 s. Recommended yes.
- Q8 DECIDED Assume on, turn off (D-OP5). Bench test still to schedule the operator's witness for the four fans before S5 builds. Required.
