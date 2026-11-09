# PLANNING: Split "visitors present" from GUEST mode

**Card:** `GUEST-MODE-SPLIT-VISITORS-1` (`docs/planning/kanban.data.yaml:438`). Fields read: `origin`, `why`, `next`,
`f5_measured_2026_11_09`, `approved_2026_11_09`, `tier_2026_11_09`, `operator_answers_2026_11_09`, `links`,
`adjacency_2026_11_09`.
**Base:** `develop` @ `6b97e434` (v5.107.6); gate lines re-verified on `b1d0a3d5`. **Date:** 2026-11-09.
**Status:** rev 2 (plan review 1 of 2, completeness, applied: `docs/reviews/code-review/guest_split_plan_review_1.md`).
Not built. Plan review 2 (adversarial build-prediction) pending.
**Tier:** **3** (escalated from the card's Tier 2-DB minimum; trigger in §9).

| Deliverable | What | Gate |
|---|---|---|
| D0 | Read-only probe: locate the October stay, guest-room runs, cam-leg runs, WiFi device FP window, replay of the new rule | **dispatch gate for EVERY build deliverable (§5.0)** |
| D1 | WiFi guest-device producer: per-device list + "new and sustained" from live edges | D0 |
| D2 | `visitors_present` producer + `binary_sensor.ura_presence_coordinator_visitors_present` | D0 |
| D3 | GUEST entry = room leg AND (cam OR WiFi); hold and exit rules | D0; the Tier-3 site |
| D4 | Trip-wire: GUEST held without the room leg too long | D0 |
| D5 | Docs: presence state of play, identity manual, card text | same commit as the build |

**Rev 2 changes (operator answers 2026-11-09, binding):** (1) the room leg is MANDATORY for entry: entry = room + one
other leg (cam or WiFi); cam + WiFi without the room leg never enters. INV-GUEST-LEAD is kept, not relaxed. (2) A real
guest stayed 3-4 weeks in October; D0 locates the dates from history and uses them as ground truth; 10-17 is likely
inside that stay, so the 10-17 entry is probably a TRUE entry, not the FP shape rev 1 called it. (3) The operator adds a
BLE scanner to Guest Bedroom 2 (operator-owned physical action; §1.3).

---

## 0. Read first: what the card gets wrong about today, and what we do not yet know

The card describes GUEST as if a face or an unidentified body could enter it today. **That is not current code.**
Since GUEST-CENSUS D2 (2026-08-16) the only automatic GUEST entry is the guest-room path:

- `presence.py:6586-6612`: in HOME_* states `guest_armed = guest_room_gate_armed`. In GUEST it is again only the room
  gate. Path A (`_guest_gate_armed`, census unidentified + confidence + 300 s) is computed and used ONLY for
  `guest_reason` / confidence (`:6615-6665`). It arms nothing.
- `PLANNING_guest_census_correctness.md:63` states this as **INV-GUEST-LEAD**: GUEST entry requires
  `_guest_room_gate_armed()`.
- The F-5 audit saw the same thing from the data side (`AUDIT_face_source_registry_discovery_2026_11.md` §9.4): the
  11-03 12:51 Path-A run qualified but the house stayed `home_day`, cause "not traced". The cause is the line above.
- The room gate reads no face, camera or census value: its inputs are the guest-room occupancy listener / boot seed and
  `_is_known_person_in_room` (BLE `location`). Verified by grep in plan review 1 §2.5.

So "a Frigate face mislabel alone can never enter GUEST" **already holds today**. What changes:

1. **The room path alone decides.** A flagged guest room (Guest Bedroom 1, Guest Bedroom 2; threshold 30 min) occupied
   30 min by anyone whose BLE does not resolve INTO that room enters GUEST. GB2 has no scanner of its own today, so a
   resident there is invisible to `_is_known_person_in_room`.
2. **The FP rate of (1) is NOT measured.** Rev 1 cited the 10-17 21:06Z entry as the FP shape. The 10-17 audit itself
   says GUEST was "plausibly CORRECT" (`AUDIT_guest_mode_fp_2026_10_17.md:8`, `:99-101`), and the operator now confirms a
   real guest stayed 3-4 weeks in October with 10-17 likely inside it. `house_state_log` shows GUEST entries every few
   days from 09-17 to 10-17 and none since (read-only DB copy, 2026-11-09). GUEST-FP-RESIDUALS-1 measured the old
   FP population collapsing to zero after v5.79.0 (09-10). So the September-October entries may be mostly REAL, and
   requiring a second leg may mostly remove real GUEST episodes. D0 measures both sides before anything is built.
3. **No low-bar "visitors here" signal exists.** `binary_sensor.universal_room_automation_unexpected_person_detected`
   (`binary_sensor.py:1889`) is instantaneous (`unidentified_count > 0` this tick).

The plan keeps the face-alone guarantee (pinned by tests), adds the operator's mandatory second leg to the room path,
adds the WiFi leg as an alternative second leg, and publishes `visitors_present`, all behind the D0 gate.

---

## 1. Institutional context verified

Mandatory reads, completely, before writing: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (all 860
lines, §10 ledger 1-29 binding), `docs/architecture/SENSOR_FLEET_CLASSES.md`, `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`.
The plan touches HVAC only as a GUEST consumer (no HVAC code change), and `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`
was also read completely; no §10 claim is re-asserted.

Ledger items that bind this plan: presence §10 #29 (no GUEST → SLEEP edge; an armed gate holds GUEST all night),
#28 (face latch follows BLE leads; face labels have been wrong), #15 (classify by device/area, not entity name). Identity
manual §5.5(a): identity may only de-escalate or annotate, never actuate.

### 1.1 Prior-art scan: REUSE or BUILD per piece

| Proposed piece | Verdict | Existing symbol (file:line) |
|---|---|---|
| Guest-room leg | **REUSE** unchanged | `_guest_room_gate_armed` `presence.py:5941`; `CONF_ROOM_IS_GUEST_ROOM` / `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN` `const.py:463-464`; `GUEST_BOOT_SEED_MIN_RESIDUAL_S` `const.py:483`; `GUEST_KNOWN_STICKY_S` `const.py:495`; listener `_handle_guest_room_occupancy_change` `presence.py:5793`; discovery `_discover_guest_rooms` `presence.py:5620` |
| Camera leg (unidentified body, sustained) | **REUSE** unchanged | `_guest_gate_armed` `presence.py:5998` (unidentified > 0, confidence ≥ `CONF_GUEST_MODE_REQUIRE_CONFIDENCE`, ≥ `CONF_GUEST_MODE_PERSISTENCE_SECONDS` `const.py:4245`; defaults 300 s / `medium`) |
| WiFi guest-device filters | **REUSE**, refactored to return devices | `_get_wifi_guest_count` `camera_census.py:6001` (SSID `CONF_GUEST_VLAN_SSID` `const.py:4240`, hostname / tablet / family-tracker / MAC filters, `WIFI_GUEST_RECENCY_HOURS` `const.py:4325`) |
| "New + sustained" WiFi device | **BUILD** (small) | No equivalent. `wifi_guest_floor` uses `last_changed` recency, which a restart resets (see D1). Edge shape copied from `arrival_edges.py` (live `not_home → home`, boot exclusion), not imported (different entity class) |
| GUEST composition | **EXTEND** | `guest_armed` composition `presence.py:6586-6612`; `infer()` entry `:1425`, exit `:1399` |
| GUEST exit persistence | **REUSE** | `guest_exit` veto `presence.py:7328-7382` (`_guest_exit_quiet_since`, `_guest_persistence_seconds`); GUEST min dwell 300 s `house_state.py:137` |
| Kill switch for all guest detection | **REUSE** | `switch.ura_presence_guest_detection_enabled` (`PresenceGuestDetectionEnabledSwitch` `switch.py:3899`, field `_guest_detection_enabled`; the switch only sets the field, `switch.py:3785-3805`, no hook) |
| `visitors_present` entity | **BUILD** | grep `visitor` over the package: only a comment at `config_flow.py:5141`. `URAUnexpectedPersonSensor` (`binary_sensor.py:1889`) is instantaneous and keeps distinct semantics (KEEP). Device/unique-id shape copied from `binary_sensor.py:2420-2440` (`{DOMAIN}_guest_mode`, `identifiers={(DOMAIN, "presence_coordinator")}`) |
| `guest_reason` attribute | **EXTEND** | `presence.py:6615-6637`, published `sensor.py:5836`; RECORDED (not in `_unrecorded_attributes`, `sensor.py:5714-5724`), so it is the live oracle |
| Known-guest face / `identified_guests` | **REUSE as annotation only** | `CONF_KNOWN_FACE_GUESTS` `const.py:3355`; `_get_egress_guest_ids_fresh` → `_last_identified_guests_count` `camera_census.py:6355-6363`; published `sensor.py:3765-3772` |
| Trip-wire NM | **REUSE pattern** | stuck-signal NM shape of `sleep_raw_hold` / `zone_hold_all_away` (presence state of play §2, §9) |
| Confidence | **REUSE** unchanged | `_d5_guest_confidence` `presence.py:6645-6650` (room + unid 0.95, room 0.9) and override `:7236` guarded on `guest_room_gate_armed`. With the room leg mandatory these are already right for every allowed pair (rev 1's two new confidence constants are dropped) |

Greps run (2026-11-09): `GUEST_ROOM|guest_room_gate|GUEST_VLAN|WIFI_GUEST|identified_guests|guest_gate_armed|visitors|VISITOR`
over `const.py`; `HouseState.GUEST|"guest"|GUEST.value` over the package (explicit readers, §3.3); `FAN_TRUST_STATES|HVAC_EVIDENCE_RULE_STATES|HVAC_NIGHT_HOLD_STATES|_HOME_STATES`
(implicit readers, §3.3); `set_override(|HOUSE_STATE_OVERRIDE_OPTIONS|apply_restored` (entry writers, §4);
`_guest_room_gate_armed|_guest_gate_armed(|guest_armed|_unidentified_first_seen|_guest_reason|_disarm_guest_gate` over the
package (site list §4); `identified_guests|wifi_guest_floor|_get_wifi_guest|known_face_guests|is_guest` over
`camera_census.py`; `visitor` over the package; `wifi_guest|census_snapshots|house_state_log|unknown_devices` over
`database.py` (no WiFi column in `census_snapshots` `:1064`; `house_state_log` `:1494` has no `guest_reason`;
`unknown_devices` holds 0 rows live).

### 1.2 Prior plans, audits, memory consulted

| Doc | Use |
|---|---|
| `PLANNING_guest_census_correctness.md` (§INV-GUEST-LEAD :63, INV-GUEST-NO-RESIDENT :69, M1 trades :407-445) | The current design. This plan KEEPS INV-GUEST-LEAD and adds a second-leg requirement on top (operator answer 1) |
| `AUDIT_guest_mode_fp_2026_10_17.md` | The 10-17 entry ("plausibly CORRECT", :8), GUEST consumer effects, the WiFi devices (MacBookAir with hostname, edge 20:12:54Z; guest phone with none) |
| `AUDIT_face_source_registry_discovery_2026_11.md` §8-9 | F-5: 87 Ojini labels 11-02..11-08, all mislabels (operator); zero GUEST ticks 11-01..11-08; `wifi_guest_floor` non-zero most of the week |
| `PLANNING_presence_guest_latch_and_veto_gap.md` + memory `project_presence_guest_latch_and_veto_gap` | Exit above the sleep branch (v5.16.0); superseded memory, not re-planned |
| `PLANNING_v4.6.2.2_guest_mode_hardening.md` | Path A persistence/confidence guards (reused as the camera leg) |
| `PLANNING_hvac_guest_as_zone_person.md` | HVAC already treats GUEST as `home`; no thermostat work |
| `PLANNING_house_away_flap_untracked_occupant.md` Rev 4 (parked; (B) guest-room AWAY veto) | Its trigger "guest accuracy becomes a priority (a long stay or a party)" fires; §8 disposition |
| Cards `CENSUS-GUEST-FLOOR-1`, `GUEST-GATE-DOOR-IDENTITY-1`, `GUEST-FP-RESIDUALS-1`, `GUEST-IDENTITY-PHONE-LEFT-BEHIND-1`, `EGRESS-EXIT-JOINT-DEPART-ONE-ROW-1`, `GUEST-ROOM-FAN-HOLD-1` | §8 dispositions |
| Memory `feedback_marginal_benefit_pushback`, `feedback_suppression_needs_discharge`, `feedback_coincidental_equality_masks_concept_split`, `feedback_measure_before_build` | Shaped §2.3, §5.0, D4, the separate boot constant |

### 1.3 Config-first and the operator's GB2 scanner

No setting expresses "room plus a second leg". Un-flagging the guest rooms disables GUEST entirely; raising the room
threshold only delays the room-alone entry.

**Operator-owned precondition (answer 3, not a deliverable):** the operator adds a BLE scanner to Guest Bedroom 2.
Observation that it took effect: a resident sitting in GB2 reads `location == "Guest Bedroom 2"` on
`PersonCoordinator.data[<name>]` (so `_is_known_person_in_room("Guest Bedroom 2")` is True). It fixes the
resident-in-GB2 case only, not "who is this body", so it does not replace D3. D0 records whether the scanner was in place
for any measured window, and its FP numbers are re-read after it lands.

---

## 2. Design

### 2.1 Legs

Three evidence legs, each a boolean per inference tick:

| Leg | True when | Producer | Evaluated in |
|---|---|---|---|
| `room` | `_guest_room_gate_armed()` (unknown occupant ≥ room threshold in a flagged guest room) | presence, unchanged | HOME_* and GUEST only (today). NOT evaluated in other states: the method is not pure (it entry-resets `_guest_room_gate_fired_room`, clears `first_seen` on a known person, INFO-logs every armed tick, `presence.py:5953-5996`) |
| `cam` | `_guest_gate_armed()` returned True within the last `GUEST_CAM_LEG_LATCH_S` | presence: stamp `_guest_cam_leg_last_true` on each True return | stamped only where Path A runs today (HOME_*); read everywhere (pure read of the stamp) |
| `wifi` | ≥ 1 guest-SSID device with a live arrival edge seen by URA and continuously `home` for ≥ `GUEST_WIFI_SUSTAIN_S` (D1) | census, read by presence (pure read) | every tick; forced False when `GUEST_WIFI_LEG_ENABLED` is False |

**Known-guest faces are not a leg.** A `guest:*` name (`known_face_guests`, egress `identified_guests`) never sets a
leg. It is published as `visitor_names` on the `visitors_present` entity only while `visitors_present` is already on
from a leg (display; identity manual §5.5(a)).

### 2.2 Rules

- **`visitors_present`** (low bar) = house state is GUEST, OR any leg is true. Display + annotation only in this cycle.
- **GUEST entry** (high bar, operator answer 1) = `room` AND (`cam` OR `wifi`). Allowed: `room+cam`, `room+wifi`,
  `room+cam+wifi`. `room` alone, `cam` alone, `wifi` alone, and `cam+wifi` never enter. INV-GUEST-LEAD holds.
- **GUEST hold** (hysteresis, lower bar): stay in GUEST while `room` OR `wifi` is true. `cam` alone does not hold. With
  `GUEST_WIFI_LEG_ENABLED` False the hold is `room` only, which is today's hold exactly.
- **GUEST exit (explicit discharge):** the hold condition false continuously for `_guest_persistence_seconds`
  (existing `guest_exit` veto, unchanged), then GUEST → HOME_* via the existing exit at `infer()` `:1399`.
  The other existing discharges stay: guest-detection switch OFF, GUEST → AWAY, manual override.
- **Kill switch:** `GUEST_TWO_LEG_GATE_ENABLED` (rung 1, True). False = today's composition, byte-identical
  (`guest_armed = guest_room_gate_armed` in both branches; no leg read affects `guest_armed`, `guest_reason`, confidence
  or `infer()`).
- **Guest-detection switch OFF:** on the first tick that reads `_guest_detection_enabled` False, the compose step forces
  every leg False and clears `_guest_cam_leg_last_true` (level-triggered, same shape as the room gate's own clear at
  `presence.py:5957-5959`; the switch has no hook).

What changes for the house, versus today:

| Situation | Today | After |
|---|---|---|
| Unknown body 30 min in GB1/GB2, no camera run in the latch, no sustained new WiFi device | GUEST | `visitors_present` on, **no GUEST** (real guest who went straight to the room: a RECALL cost, measured by D0) |
| Guest walks past interior cameras (Path A qualifies), then 30 min in a guest room within the latch | GUEST | GUEST (`room+cam`) |
| Guest phone joins Revel and stays ≥ sustain, guest sits in GB1 30 min | GUEST (room) | GUEST (`room+wifi`), if the WiFi leg ships ON |
| Gathering in living room: cameras see unknown bodies ≥ 300 s, guest phones on Revel | no GUEST | no GUEST; `visitors_present` on (operator answer 1) |
| Frigate names a resident "Ojini" | no GUEST | no GUEST; not even `visitors_present` |
| Guest leaves the guest room for the kitchen | exits after 300 s quiet | same, unless their phone holds `wifi` |
| Restart mid-visit (restored GUEST) | room gate re-seeds; holds | holds only on `room` until the cam latch or a WiFi edge re-forms; see §7 residual |

### 2.3 Marginal-benefit pushback (done before the spec, per the rule)

- **The second leg on the room path is NOT yet shown to pay.** Its benefit is FPs removed (resident in a guest room
  without BLE in that room); its cost is real-guest GUEST episodes lost (guest goes straight to the room, unseen by
  interior cameras, phone without a hostname or the WiFi leg off). Since v5.79.0 the measured FP population collapsed
  (GUEST-FP-RESIDUALS-1), the remaining September-October entries are plausibly the real stay, and the operator's GB2
  scanner removes the resident-in-GB2 case without code. D0 Q3 prices both sides. If D0 shows ~0 room-alone FPs outside
  known visits AND a material recall loss on the stay, the planner recommends shipping D2 (`visitors_present`) only and
  parking D3 with a revival trigger ("a room-alone GUEST entry on a day the operator confirms no guest"), and pages the
  operator before any build. The operator's ruling stands unless they change it on that evidence.
- **Known-guest face as positive evidence: PARK.** F-5 measured 87/87 Ojini labels as mislabels; HomeLab removed the
  Ojini library and raised the face thresholds on 11-09. **Revival trigger:** `known_face_guests` non-empty AND ≥ 10
  guest-label face rows in 14 days that the operator confirms as real visits.
- **F-5 S7 subtraction (known-guest face lowers the unidentified count): PARK, not folded.** Same revival trigger.
- **WiFi "known device memory": PARK to CENSUS-GUEST-FLOOR-1**, which owns device lifetime/decay.
- **NM on `visitors_present`: PARK.** Revival trigger: the operator asks for a "visitors arrived" notification after
  seeing the entity for two weeks.

### 2.4 Falsifiable invariants

- **INV-SPLIT-1 (room mandatory, never alone).** For every reachable tick with `GUEST_TWO_LEG_GATE_ENABLED` True on which
  `infer()` proposes GUEST from a HOME_* state, `room` was true on that tick AND at least one of `cam`, `wifi` was true.
  Exempt by design: manual override (select / service) and restart restore (a restored GUEST is discharged by the hold
  rule within `_guest_persistence_seconds` + one tick of `room` and `wifi` both being false).
  Corollaries: a Frigate face label (resident or `guest:*`), alone or repeated, never enters GUEST and never sets
  `visitors_present`; `cam+wifi` never enters; `room` alone never enters.
  *Falsifiers to try:* a mislabelled face on two cameras for 30 min with a clean BLE census (face is not a leg; the body
  is cancelled by BLE so `cam` stays false); a resident without a GB2 BLE fix in GB2 for 2 h with no camera run (`room`
  only); a party in the living room with phones on Revel (`cam+wifi`, no `room`); an IoT device reconnecting every
  20 min while someone sits in GB1 (`wifi` needs a continuous sustain); a restart with a guest-SSID device already `home`
  (no live edge → no `wifi`); a cam run older than the latch followed by 30 min in GB1.
- **INV-SPLIT-2 (discharge).** GUEST is never held by `cam` alone, and every inferred GUEST episode ends within
  `_guest_persistence_seconds` + one inference tick of the last instant at which `room` OR `wifi` was true, unless an
  override or AWAY intervenes first.
- **INV-SPLIT-3 (kill switch).** With `GUEST_TWO_LEG_GATE_ENABLED` False, `guest_armed`, `guest_reason`,
  `_d5_guest_confidence` and the `infer()` result are byte-identical to `develop` @ `6b97e434` for every input.
- Carried unchanged: **INV-GUEST-LEAD**, **INV-GUEST-NO-RESIDENT** (the room leg never fires on known residents) and the
  v5.16.0 exit-before-sleep ordering (I-D1).

---

## 3. Producer and consumer checks

### 3.1 Producers

| Value | Arithmetic | Dependencies and their health |
|---|---|---|
| `room` leg | unknown occupant continuously present ≥ threshold (30 min) in a flagged room; known person in room (BLE `location` == room name, 120 s sticky) cancels | Room occupancy: GB1/GB2 ride the Matter MS600 presence radars (SENSOR_FLEET_CLASSES §Meross). BLE: GB2 has no own scanner today (`scanner_areas: ['guest_bedroom_2_closet']`), so residents in GB2 read unknown: **degraded for GB2 until the operator's scanner lands (§1.3)** |
| `cam` leg | Path A: `unidentified_count > 0` AND census confidence ≥ `medium` AND continuous ≥ 300 s; latched `GUEST_CAM_LEG_LATCH_S` | `unidentified_count` = clamped camera bodies minus the BLE/face union (`camera_census.py:6300-6410`, INV-CENSUS-ATTRIBUTION). Conservative: on 61/70 F-5 ticks the clamp zeroed it. Interior cameras do not cover the guest rooms. History: `census_snapshots` from 2026-08-10 |
| `wifi` leg | D1 | UniFi router trackers on SSID "Revel" (`CONF_GUEST_VLAN_SSID`). Hostname-less devices are skipped (Filter 1), so the 10-17 guest's phone (no hostname) would not count; her MacBookAir would. Resident phones are excluded only through `person.device_trackers`, device siblings and MAC cross-reference; a resident phone with a per-network private MAC that is not linked would look like a new guest device on every arrival. **FP measurable only on the last ~7 days (recorder `purge_keep_days: 7`); recall unmeasurable for October (D0)** |
| `visitors_present` | GUEST OR any leg | as above |
| GUEST | §2.2 | as above |

### 3.2 `visitors_present` consumers

New. Readers this cycle: the entity itself (display) and nothing else. It is not read by `infer()`; the GUEST gate reads
the legs directly.

### 3.3 GUEST consumers (re-enumerated in plan review 1; none changes code)

**Explicit readers** (grep `HouseState.GUEST|"guest"`):

| Consumer | file:line | Trust / display | Effect of the split |
|---|---|---|---|
| HVAC preset map guest → `home` | `hvac_const.py:1293` | trust | GUEST already behaves as `home` |
| HVAC Custom Preset Ranges predicate `house_state == "guest"` | `preset_overrides.py:115-148` | trust | only fires in GUEST; fewer episodes |
| Dynamic preset guest offset reset | `dynamic_preset.py:861` | trust | no offset keys configured (10-17 audit), moot |
| Arrester hold-preserving states | `hvac_const.py:229` | trust | an immune hold survives a GUEST edge; fewer edges |
| Security armed-state map guest → ARMED_HOME | `security.py:183` | trust (arming) | state-driven arming not live (10-17 audit) |
| SC lock regime: GUEST in sleep window engages lockouts; `_HOME_STATES` release | `security_lock_regime.py:764, 776, 808, 1410, 1477` | trust (lock actuation) | a lost GUEST night becomes SLEEP, which engages the same lockouts; equivalent |
| NM exterior-person severity: guest = MEDIUM | `const.py:2667`, `:2677`, `:2761-2762` | trust (severity) | **two directions:** by day GUEST is MEDIUM where `home_day` is LOW/HIGH; at night GUEST is MEDIUM where `home_night` / `sleep` are CRITICAL. A real-guest night that loses GUEST pages CRITICAL for the guest walking outside. D0 Q3 counts such nights |
| Bayesian learning suppressed in GUEST | `__init__.py:3278` | trust (learning) | learns more |
| Non-sleep person fallback (zone_persons_home) includes guest | `aggregation.py:4871-4873` | trust (zone occupancy) | none (GUEST and HOME_* both pass) |
| Occupancy-anomaly suppressed in GUEST | `binary_sensor.py:3570` | display | more anomaly evaluation in lost-GUEST periods |
| Routine forecaster passthrough | `routine_forecaster.py:101-105` | display | none |
| Memory facade guest → home | `memory_facade.py:279` | display | none |
| `binary_sensor.ura_guest_mode` | `binary_sensor.py:2450` | display | none |
| House-state sensor `guest_reason` | `sensor.py:5836` (recorded) | display + live oracle | gains `two_leg:<legs>` values (D3) |
| Census sensor `identified_guests_count`, `wifi_guest_floor` | `sensor.py:3765-3772`, `:3792` | display | unchanged; D1 adds `wifi_guest_devices_sustained` |
| Wall-panel brightness automation (HA YAML, not URA) | `automations.yaml:8270` per 10-17 audit | cosmetic | fewer episodes |
| Lighting in URA | grep found no URA lighting reader of GUEST | — | — |

**Implicit readers** (keyed on a state SET that excludes `guest`; a literal grep misses them):

| Consumer | file:line | Effect when a GUEST episode is lost |
|---|---|---|
| HVAC hold table: evidence rule only in `home_day`/`home_evening`, GUEST uses the legacy tail | `hvac_const.py:1097`, `hvac_zones.py:1482-1486` | guest's zone releases on the faster evidence clock by day |
| HVAC night tail only in `sleep`/`waking` | `hvac_const.py:1082`, `hvac_zones.py:1452` | a lost GUEST night becomes SLEEP: bedrooms get the 30-min night tail (more protection for a sleeping guest) |
| Fan night trust `FAN_TRUST_STATES` = (home_night, sleep, waking) | `hvac_const.py:1067`; `hvac_fans.py:580`, `:596`, `:1213`, `:1442`; `presence_fan_recheck` sleep veto | lost GUEST night → fan night-trust and the bedroom recheck sleep veto apply (house-wide) |
| Every SLEEP-keyed consumer (GUEST blocks SLEEP all night, presence §10 #29) | `house_state.py:116-121` | lost GUEST night → SLEEP consumers fire |

Direction: every consumer sees fewer GUEST episodes (room-alone and, for the WiFi-off build, room-without-a-camera-run
removed). There are no new GUEST episodes (operator answer 1 removed `cam+wifi`).

---

## 4. Decision-site enumeration (every site that reads or writes the gate)

From `grep -n "_guest_room_gate_armed|_guest_gate_armed(|guest_armed|_unidentified_first_seen|_guest_reason|_disarm_guest_gate"`
on develop (re-run independently in plan review 1; identical). The builder re-runs it; this list is a hypothesis.

| # | Site | Change |
|---|---|---|
| S1 | `presence.py:6586-6601` HOME_* branch: `unid_gate_armed`, `guest_room_gate_armed`, `guest_armed = guest_room_gate_armed` | stamp cam latch on `unid_gate_armed` True; read wifi leg; `guest_armed = _compose_guest_gate(legs, HOME)` = room AND (cam OR wifi) |
| S2 | `presence.py:6602-6609` GUEST branch: `guest_armed = guest_room_gate_armed` | `guest_armed = _compose_guest_gate(legs, GUEST)` = room OR wifi |
| S3 | `presence.py:6610-6613` else branch (all False) | legs for `visitors_present` only: `room` False (NOT evaluated), `cam` latch read, `wifi` read. The locals `unid_gate_armed`, `guest_room_gate_armed`, `guest_armed` stay False |
| S4 | `presence.py:6615-6637` `guest_reason` | precedence when the gate switch is on: `two_leg:<sorted legs>` (entry or hold with `guest_armed` True) > `guest_room:<room>` (room alone, now "visitor, not guest") > `unidentified_corroborator_only` > `override` > `none`. Switch off: unchanged |
| S5 | `presence.py:6645-6670` `_d5_guest_confidence` + debug canary | values unchanged (room+cam 0.95, room 0.9); canary condition narrowed to HOME_* ticks (a WiFi-only hold in GUEST is legal and must not log the canary) |
| S6 | `presence.py:7046` `infer(guest_gate_armed=guest_armed)` | unchanged literal (anchor) |
| S7 | `infer()` exit `:1399` and entry `:1425` | unchanged; they consume `guest_gate_armed` |
| S8 | `presence.py:7236` confidence override guarded on `guest_room_gate_armed` | unchanged (room is mandatory for entry, so the guard is already right) |
| S9 | `presence.py:7328-7382` `guest_exit` veto | unchanged (hold semantics come from S2) |
| S10 | `presence.py:7596-7603` `_disarm_guest_gate()` on GUEST edges; non-home disarm `:6568-6575`; teardown `:8227` | unchanged; must NOT clear `_guest_cam_leg_last_true` (separate state) |
| S11 | `_schedule_guest_persistence_recheck` `presence.py:6070` | unchanged (its recheck tick is where a late cam stamp lands) |
| S12 | `switch.py:3899` guest-detection kill switch (field only) | the compose step reads `_guest_detection_enabled` False → all legs False, latch cleared, entity off |
| S13 | `sensor.py:5836` `guest_reason` publish | unchanged code; new values |
| S14 | Override writers `select.py:280`, `__init__.py:6200`, `presence.set_house_state_override` `:8663-8683` | not gated (by design) |
| S15 | Restore `manager.py:688-719` (`apply_restored`) | not gated; discharged by S2's hold rule |

---

## 5. Deliverables

### 5.0 Build dispatch gate (applies to D1-D5)

No builder is dispatched for any deliverable until (a) `§D0-results` is committed in this plan with a verdict line
`D0 GATE: GO`, `D0 GATE: GO-WIFI-OFF` or `D0 GATE: STOP-PAGE-OPERATOR`, (b) the operator has confirmed the October stay
dates and the real/FP labels D0 asks for, and (c) on `STOP-PAGE-OPERATOR`, the operator has answered. A build dispatched
before this line exists is a process violation. Plan review 2 checks the gate wording.

### D0 — Read-only measurement probe (the gate)

`scripts/probes/guest_split_d0.py`, run as `ssh ha "python3 -" < script`, read-only on the HA recorder and the URA DB.
Report appended to this plan as §D0-results. Data limits (verified 2026-11-09): HA recorder `purge_keep_days: 7`;
URA DB `house_state_log` from June 2026, `occupancy_events` from 2025-11-20, `census_snapshots` from 2026-08-10;
`census_snapshots` has no WiFi column; `unknown_devices` is empty. The report states the actual oldest row per source.

Questions:
0. **Locate the October stay (operator answer 2).** From `house_state_log` GUEST runs, `occupancy_events` for GB1/GB2
   (sustained night occupancy with no resident BLE in the room), and `person_entry_exit_events` unnamed entries, propose
   the stay's start and end dates. The operator confirms them. All later questions label each day "stay" or "no-stay".
   Record whether the GB2 scanner (§1.3) existed on any measured day.
1. **Guest-WiFi devices (recorder, last ~7 days only, all no-stay).** For every router `device_tracker` on essid Revel
   passing the existing filters: home/not_home episodes, episode length, and how many start with a real
   `not_home → home` edge (not a boot restore; restarts from `homeassistant_start`). For sustain S ∈ {10, 30, 60, 120} min:
   per day, devices that would set `wifi`. Also: hostname-less phone-like devices (the filter gap) and any device whose
   edges coincide with a resident's arrival (± 2 min of a `person.*` `not_home → home`) = an unlinked resident phone.
   October WiFi recall is NOT measurable; the one known edge (10-17 MacBookAir 20:12:54Z) comes from the 10-17 audit.
2. **Guest rooms (`occupancy_events` + `house_state_log`, all history).** For GB1/GB2: occupied runs ≥ 30 min, split
   stay / no-stay, and every GUEST entry with trigger and confidence. Runs ≥ 30 min on no-stay days that entered GUEST =
   the room-alone FP count since v5.79.0 (09-10).
3. **Replay of the new rule (room + cam; WiFi only where Q1 covers).** For each GUEST entry and each ≥ 30-min guest-room
   run that did not enter: did `cam` (Path A qualifying run from `census_snapshots` unidentified/confidence history)
   fire within L ∈ {30, 60, 120, 240} min before? Tabulate today vs the new rule, separately for stay and no-stay days:
   entries kept, entries removed, each labelled real / FP / unknown with the operator. Also count stay NIGHTS on which
   GUEST would be lost (each = SLEEP instead of GUEST; NM exterior-person severity CRITICAL instead of MEDIUM).
4. **Cam leg alone:** Path A qualifying runs per day (stay vs no-stay), to size the latch's exposure.

**Go/no-go (written as the verdict line):**
- `GUEST_CAM_LEG_LATCH_S` = the smallest L in Q3 that keeps ≥ 80 % of the stay's GUEST entry-days (an entry-day is kept
  if at least one entry that day survives). If no L reaches 80 %, see the STOP clause.
- `GUEST_WIFI_LEG_ENABLED` default True only if, at the chosen sustain, `wifi` is false on every day in the Q1 window AND
  no device in Q1 matches resident arrivals. Otherwise False (`GO-WIFI-OFF`): the leg is computed and published as a
  shadow attribute. October recall cannot support turning it on; the operator may accept FP-only evidence explicitly.
- `GUEST_WIFI_SUSTAIN_S` from Q1 (the smallest S with zero no-stay devices; placeholder 1800).
- **STOP-PAGE-OPERATOR** if either: (a) no L keeps ≥ 80 % of stay entry-days and the WiFi leg is off; or (b) Q2 finds
  ~0 room-alone FPs on no-stay days since 09-10 (≤ 1). In (b) the planner recommends D2 only and parks D3 (§2.3); the
  operator decides.

**Acceptance criteria**
- **Verify:** the report has a table per question, with sources, row counts, the window, and the stay dates the operator
  confirmed.
- **Verify:** each default in D1/D3 cites its D0 row; the verdict line is present.
- **Test:** none (probe).
- **Live:** none (read-only; no HA state changed).

### D1 — WiFi guest-device producer

In `camera_census.py`:
- Refactor `_get_wifi_guest_count` into `_get_wifi_guest_devices(now) -> list[str]` (entity ids passing the SAME
  filters, including the 4 h recency) and `_get_wifi_guest_count = len(...)`. `wifi_guest_floor` byte-identical.
- New per-census-tick edge tracker over router trackers on the guest SSID that pass filters 1-4c (recency NOT applied
  here): keep `_wifi_guest_seen_away: set[str]` (seen not `home` on a prior tick this process) and
  `_wifi_guest_home_since: dict[str, datetime]` (set when a device seen away is now `home`; cleared when it reads
  anything but `home`). A device already `home` at the first tick after setup has NO entry, so a restart never
  manufactures arrivals (HA's restore stamps `last_changed` at boot, presence doc §8). Edges inside
  `GUEST_WIFI_BOOT_EXCLUDE_S` of census setup are ignored.
- `wifi_guest_devices_sustained(now)` = devices whose `home_since` ≤ now − `GUEST_WIFI_SUSTAIN_S` (clamped ≥ 60 s at
  read). Published on the census sensor as `wifi_guest_devices_sustained` (count, recorded; changes rarely) and in
  `_unrecorded_attributes` as the entity-id list.
- Discharge: an entry is removed on the first non-`home` read, on an entity that disappears, and on teardown.
  RAM only, not persisted (fail toward fewer legs).

**Acceptance criteria**
- **Verify:** `wifi_guest_floor` identical before/after on the same states (golden over a fixture of 8 devices).
- **Verify:** a device `home` at boot never counts; the same device after `not_home → home` counts once the sustain
  elapses; a disconnect resets it.
- **Discriminates:** under the fix, a restart with 3 IoT devices on Revel gives `wifi_guest_devices_sustained` 0 for the
  whole sustain window and after; under the plausible wrong build (reusing `last_changed`), it gives 3 after the sustain.
- **Test:** `test_guest_split_wifi_leg.py::test_floor_count_unchanged`, `::test_boot_home_device_never_counts`,
  `::test_live_edge_then_sustain_counts`, `::test_disconnect_resets`, `::test_boot_exclusion_window`,
  `::test_filters_still_apply`, `::test_sustain_clamped_to_60`.
- **Live:** after restart, `wifi_guest_devices_sustained` reads 0 on `sensor.universal_room_automation_persons_in_house`
  for at least the sustain window even though `wifi_guest_floor` may be > 0.

### D2 — `visitors_present` producer and entity

- `PresenceCoordinator` computes the three legs once per inference tick (S1-S3) into `_guest_legs: dict[str, bool]`,
  entry-reset at the top of the guest block, and `_visitors_present = house is GUEST or any(legs)`.
- New `binary_sensor.ura_presence_coordinator_visitors_present` (Presence Coordinator device, `has_entity_name`, unique
  id `{DOMAIN}_visitors_present`, device info as `binary_sensor.py:2430-2440`), push-updated with the house-state
  sensor. Attributes: `legs` (the three booleans), `since` (rising edge), `visitor_names` (sorted `guest:*` names from
  `identified_guests` + known-guest face names, only while on). `legs` and `visitor_names` in `_unrecorded_attributes`.
- Guest-detection switch OFF → all legs False, entity off.

**Acceptance criteria**
- **Verify:** a known-guest face with no leg leaves the entity off and `visitor_names` empty.
- **Verify:** `room` alone turns it on and does not enter GUEST; `cam+wifi` turns it on and does not enter GUEST.
- **Verify:** in SLEEP / AWAY, `room` is not evaluated (no `_guest_room_gate_armed` call; no INFO line).
- **Discriminates:** under the fix, a resident mislabelled as `guest:ojini` on two cameras for 30 min with BLE in the
  room gives entity off; under a build that let the face set a leg, it gives on.
- **Test:** `test_guest_split_visitors.py::test_face_alone_never_visitor`, `::test_room_alone_is_visitor_not_guest`,
  `::test_cam_wifi_is_visitor_not_guest`, `::test_room_not_evaluated_outside_home_guest`, `::test_names_only_when_on`,
  `::test_kill_switch_forces_off`.
- **Live:** the entity exists, reads `off` with house state not GUEST and `legs` all False; its unique id resolves in the
  registry.

### D3 — Room-mandatory two-leg GUEST gate (Tier-3 site)

Sites S1-S15 per §4. Composition in ONE helper, `PresenceCoordinator._compose_guest_gate(legs, current_state) -> bool`,
pure, called from S1 and S2; S3 does not call it. `GUEST_TWO_LEG_GATE_ENABLED` False returns `legs["room"]` in both
states (INV-SPLIT-3). The cam latch stamp happens at S1 only when `_guest_gate_armed` returns True; it is never cleared
by `_disarm_guest_gate` (S10); it is cleared by the compose step when `_guest_detection_enabled` is False (S12).

On every transition INTO GUEST, one INFO line `guest gate legs=<room,cam,wifi> reason=<guest_reason>` (convenience only;
URA INFO is not retained, so it is not an oracle).

**Acceptance criteria**
- **Verify (INV-SPLIT-1):** table-driven test over all 8 leg combinations × {HOME_DAY, HOME_EVENING, HOME_NIGHT}:
  GUEST proposed only for `room+cam`, `room+wifi`, `room+cam+wifi`. `cam+wifi` and every single leg: never.
- **Verify (INV-SPLIT-2):** in GUEST, `cam` true alone → exit after the persistence window; `wifi` true alone → hold;
  `room` true alone → hold.
- **Verify (INV-SPLIT-3):** switch False, replay a fixture of 200 recorded ticks: identical `guest_armed`,
  `guest_reason`, confidence and `infer()` output vs the pre-change function (golden captured on `6b97e434`).
- **Verify:** sleep-hour ordering unchanged (exit before the sleep branch, I-D1).
- **Verify (restore, F6):** a restored non-override GUEST with `room` false and no `wifi` exits after the persistence
  window; with `room` re-seeded by the boot seed it holds.
- **Config boundary:** room threshold 1 and 600 min; persistence 0 and 3600 s; boot-seed residual equal to persistence
  (300/300, today's coincidental equality); latch 0 (cam leg only on the qualifying tick) and max; sustain 0 (clamped
  to 60 s) and max; WiFi leg off/on.
- **Discriminates:** the 10-17 replay (room 30 min in a guest room, census clean, MacBookAir edge 20:12:54Z per the
  10-17 audit; 10-17 likely inside the real stay). With the WiFi leg ON and sustain ≤ 54 min: GUEST at 21:06Z, reason
  `two_leg:room+wifi`. With the WiFi leg OFF and no cam run in the latch: no GUEST, `visitors_present` on, reason
  `guest_room:<room>` (a RECALL loss on a real guest, which D0 must have priced). Under a build that kept
  `guest_armed = room`: GUEST at 21:06Z with reason `guest_room:<room>` in both configurations. Under a build that
  admitted `cam+wifi`: the living-room party fixture enters GUEST. The reason string and the party fixture separate all
  three.
- **Test:** `test_guest_split_gate.py::test_pair_matrix`, `::test_cam_wifi_never_enters`, `::test_hold_room_or_wifi_only`,
  `::test_cam_alone_never_holds`, `::test_kill_switch_byte_identical`, `::test_exit_before_sleep_branch`,
  `::test_cam_latch_survives_disarm`, `::test_detection_switch_off_clears_latch`, `::test_restored_guest_held_by_room_only`,
  `::test_config_extremes`, `::test_1017_replay`, `::test_party_fixture_no_guest`. Each of S1, S2, S3, S4, S10, S12 gets
  a named test that fails when that one site is neutered (framing C drill list).
- **Live:** `sensor.universal_room_automation_house_state` attribute `guest_reason` reads `none` or `guest_room:<room>`
  (not `two_leg:`) with no visitors. On the next real guest: for each `house_state_log` row with `state='guest'`, the
  RECORDED `guest_reason` attribute at that timestamp (recorder, house-state sensor) reads `two_leg:*` and contains
  `room`. A `guest_room:` or a `two_leg:` without `room` at a GUEST transition = FAIL.

### D4 — Trip-wire: GUEST held without the room leg

One HIGH stuck-signal NM (`kind=guest_wifi_only_hold`) when the house has been inferred GUEST (not override) for more
than `GUEST_WIFI_ONLY_HOLD_NM_S` with `room` false for that whole span (WiFi is then the only possible holder: `cam`
cannot hold). Once per GUEST episode; re-armed on GUEST exit. 0 = off. Rationale: the WiFi hold has no time bound of its
own; a device that slips the filters and stays connected would hold GUEST indefinitely (suppression-needs-discharge
rule). The NM is the discharge to a human, not an automatic exit. Inert when the WiFi leg ships OFF.

**Acceptance criteria**
- **Verify:** fires once after the bound with only `wifi`; does not fire if `room` was true at any point in the span;
  does not fire at 0; does not fire under a GUEST override.
- **Test:** `test_guest_split_tripwire.py::test_fires_once_wifi_only`, `::test_room_seen_resets`, `::test_zero_disables`,
  `::test_override_never_fires`.
- **Live:** no `guest_wifi_only_hold` row in `notification_log` on a day without guests.

### D5 — Docs (same commit as the build)

- Presence state of play §2 step 3 (GUEST = room + one other leg), §7 (visitors vs GUEST), §1 consumer table row for the
  new entity, §9 card list. Correct its claim at §2 step 3 that `_guest_gate_armed` "pre-evaluates" the GUEST decision
  (it is a corroborator since 08-16, and now a second leg) and add it to §10. Add the implicit-consumer list (§3.3).
- Identity manual §5.5: known-guest faces are annotation only.
- Card text: replace the `next` line's "visitors_present = unidentified>0 OR identified_guests>0" with this plan's rule.

**Acceptance criteria**
- **Verify:** the docs cite the new symbols at file:line on the build branch.
- **Live:** n/a.

---

## 6. Numbers and knobs

| Knob | Rung | Default | Why this rung | Kill-switch semantics |
|---|---|---|---|---|
| `GUEST_TWO_LEG_GATE_ENABLED` | 1 (const.py) | True | Changes house-state entry; reverting should be a reviewed change | False = today's room-only gate, byte-identical |
| `GUEST_WIFI_LEG_ENABLED` | 1 | from D0 (True only if clean; expected False) | A new producer feeding house state; turning it on must be reviewed against D0-style data | False = leg computed for display, never counted for entry or hold |
| `GUEST_WIFI_SUSTAIN_S` | 1 | from D0 (placeholder 1800) | Filters IoT reconnects; a fitted threshold | clamped to ≥ 60 at read |
| `GUEST_WIFI_BOOT_EXCLUDE_S` | 1 | 600 | Restart-transient guard. Own constant on purpose: equal today to `PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S` but a different concept (coincidental-equality rule) | 0 = no exclusion (edges still need a seen-away state) |
| `GUEST_CAM_LEG_LATCH_S` | 1 | from D0 Q3 (placeholder 7200) | How long a camera sighting stays evidence for the room path | 0 = cam leg only on the tick Path A is True |
| `GUEST_WIFI_ONLY_HOLD_NM_S` | 1 | 43200 (12 h) | Trip-wire bound | 0 = off |
| Room threshold `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN` | 2 (room options), REUSED | 30 | unchanged | — |
| Path A persistence / confidence `CONF_GUEST_MODE_PERSISTENCE_SECONDS` / `_REQUIRE_CONFIDENCE` | 2 (CM options), REUSED | 300 / medium | unchanged; also the exit persistence | — |
| `WIFI_GUEST_RECENCY_HOURS` | 1, REUSED | 4 | unchanged (diagnostic floor only) | — |
| Confidence 0.95 / 0.9 | existing literals, REUSED | unchanged | no new number this cycle (rev 1's `GUEST_TWO_LEG_CONFIDENCE` / `GUEST_CAM_WIFI_CONFIDENCE` dropped) | n/a |
| Operator toggle | 3, REUSED | `switch.ura_presence_guest_detection_enabled` | live kill for all guest detection | OFF = no GUEST entry, legs False, latch cleared, entity off |

No new Number or options-flow field. Parsimonious-config rule: these are review-gated constants.

---

## 7. Non-goals

- No GUEST → SLEEP edge (presence §10 #29). An overnight guest still holds GUEST; consumers keyed on SLEEP still do not
  fire those nights.
- No `cam+wifi` entry (operator answer 1). A party without anyone in a guest room never enters GUEST.
- No change to the census arithmetic, the unidentified clamp, face handling, or the F-5 subtraction (parked, §2.3).
- No WiFi device lifetime / known-device memory / hostname-less phone handling (CENSUS-GUEST-FLOOR-1).
- No door-identity input to the gate (GUEST-GATE-DOOR-IDENTITY-1 stays parked on its own trigger).
- No consumer changes (HVAC, fans, security, lock regime, NM); no NM on `visitors_present`.
- No persistence of the new legs across restarts (fail toward fewer legs). Accepted residuals, listed in the README:
  a restart mid-visit can drop a `wifi`-held GUEST; after a restart the WiFi leg cannot re-form for a device that stayed
  connected across it, so RE-ENTRY needs a fresh camera run until that phone disconnects and reconnects.
- No GB2 scanner work (operator-owned, §1.3).
- No DB schema change.

---

## 8. Related cards

| Card / parked item | Disposition |
|---|---|
| `CENSUS-GUEST-FLOOR-1` | Stays pre_planning. This cycle reuses its filters as a leg, not a census floor. Add a link; its lifetime/decay design is the revival path for a WiFi leg that D0 rejects |
| `GUEST-GATE-DOOR-IDENTITY-1` | Stays parked; trigger unchanged |
| `GUEST-FP-RESIDUALS-1` | Stays parked. Note: the 09-17..10-17 entries are plausibly the real October stay (operator answer 2), not a resumed FP population |
| `GUEST-IDENTITY-PHONE-LEFT-BEHIND-1` | Stays parked. D3 + the GB2 scanner reduce its class; link; re-measure after both land |
| `PLANNING_house_away_flap_untracked_occupant.md` Rev 4 (A) camera guard + (B) guest-room AWAY veto | **Trigger FIRED** ("guest accuracy becomes a priority (a long stay or a party)"). Not folded: AWAY-side, different invariant. Card a re-evaluation for the operator; D0 Q0/Q2 (stay dates, guest-room runs) are its inputs |
| `EGRESS-EXIT-JOINT-DEPART-ONE-ROW-1` | Not fired: `visitor_names` reads entry-registered guest ids for display; no consumer ACTS on exit `person_id` |
| `GUEST-ROOM-FAN-HOLD-1` | Not fired; no fan change. Note: lost GUEST nights put guest-room fans under `FAN_TRUST_STATES` rules |
| `FACE-SOURCE-REGISTRY-DISCOVERY-1` | Its F-5 residual folds here as PARKED (§2.3), with the revival trigger |

---

## 9. Tier classification

**Tier 3.** Trigger: the change recomposes `guest_armed`, which is threaded into `infer()` and governs both entry
(`:1425`) and exit (`:1399`) of the house-state machine (the card's own escalation condition). GUEST is consumed by lock
actuation (lock regime), security arming, HVAC presets and hold tables, fan night trust and NM severity, so one missed
composition site is a silent behaviour change.

Required: TWO framing-disjoint plan reviews before build (review 1 completeness: done, rev 2; review 2 adversarial
build-prediction: pending), the §5.0 D0 gate, then four code reviews A/B/C/D (D states INV-SPLIT-1 and tries to break it,
including pre-existing paths such as the manual override, restore and the boot seed), config-extreme tests (§D3),
orchestrator re-grep + one real source mutation on S1/S2 before ship, and an operator checkpoint before deploy.
Builder: `ura-super-builder`.

## 10. Live validation (post-restart, feeds the README)

| # | Check | Source |
|---|---|---|
| L1 | `binary_sensor.ura_presence_coordinator_visitors_present` exists, `legs` attribute has three keys | live entity |
| L2 | `wifi_guest_devices_sustained` = 0 for the first sustain window after restart | census sensor attribute |
| L3 | With no guest present, `guest_reason` is never `two_leg:*` over the first day, and the house never enters GUEST | recorder, house-state sensor + `house_state_log` |
| L4 | For every `house_state_log` row with `state='guest'` after deploy, the recorded `guest_reason` at that timestamp is `two_leg:*` and contains `room` | URA DB + recorder |
| L5 | First real guest: GUEST entry as L4; exit within persistence of the last room/wifi leg | recorder + `house_state_log`; organic, disposed by its binary discriminator per the soak-exit rule |
