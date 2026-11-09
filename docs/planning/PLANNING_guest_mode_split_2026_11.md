# PLANNING: Split "visitors present" from GUEST mode

**Card:** `GUEST-MODE-SPLIT-VISITORS-1` (`docs/planning/kanban.data.yaml:426`). Fields read: `origin`, `why`, `next`,
`f5_measured_2026_11_09`, `approved_2026_11_09`, `tier_2026_11_09`, `links`, `adjacency_2026_11_09`.
**Base:** `develop` @ `6b97e434` (v5.107.6). **Date:** 2026-11-09. **Status:** plan, not reviewed, not built.
**Tier:** **3** (escalated from the card's Tier 2-DB minimum; trigger in §9).

| Deliverable | What | Gate |
|---|---|---|
| D0 | Read-only probe: guest-WiFi device history, guest-room occupancy, replay of the new rule | **go/no-go for D1 and the default of D3's WiFi leg** |
| D1 | WiFi guest-device producer: per-device list + "new and sustained" from live edges | D0 |
| D2 | `visitors_present` producer + `binary_sensor.ura_presence_coordinator_visitors_present` | — |
| D3 | GUEST gate = two independent legs, one of them room or WiFi; hold and exit rules | the Tier-3 site |
| D4 | Trip-wire: GUEST held by the WiFi leg alone too long | — |
| D5 | Docs: presence state of play, identity manual, card text | same commit as the build |

---

## 0. Read first: what the card gets wrong about today

The card describes GUEST as if a face or an unidentified body could enter it today. **That is not current code.**
Since GUEST-CENSUS D2 (2026-08-16) the only automatic GUEST entry is the guest-room path:

- `presence.py:6586-6612`: in HOME_* states `guest_armed = guest_room_gate_armed`. In GUEST it is again only the room
  gate. Path A (`_guest_gate_armed`, census unidentified + confidence + 300 s) is computed and used ONLY for
  `guest_reason` / confidence (`:6615-6665`). It arms nothing.
- `PLANNING_guest_census_correctness.md:63` states this as **INV-GUEST-LEAD**: GUEST entry requires
  `_guest_room_gate_armed()`.
- The F-5 audit saw the same thing from the data side (`AUDIT_face_source_registry_discovery_2026_11.md` §9.4): the
  11-03 12:51 Path-A run qualified but the house stayed `home_day`, cause "not traced". The cause is the line above.

So "a Frigate face mislabel alone can never enter GUEST" **already holds today** on the entry path. The real
weaknesses are elsewhere:

1. **The room path alone decides.** A flagged guest room (Guest Bedroom 1, Guest Bedroom 2; threshold 30 min, live
   per `AUDIT_guest_mode_fp_2026_10_17.md` §1) occupied 30 min by anyone whose BLE does not resolve INTO that room
   enters GUEST. The 10-17 21:06Z entry was exactly that, with the census reading 0 unidentified. GB2 has no scanner of
   its own, so a resident there is invisible to `_is_known_person_in_room`. Guest entries ran ~2.2/day from 09-17
   (same audit §4), some of them real.
2. **No other path exists.** A guest who never sits 30 min in a flagged room (a gathering in the living room, a
   guest using a non-flagged bedroom) never enters GUEST. This was accepted in M1 of the 08-16 cycle and stays accepted
   except for the operator's new WiFi path.
3. **There is no low-bar "visitors here" signal.** `binary_sensor.universal_room_automation_unexpected_person_detected`
   (`binary_sensor.py:1889`) is instantaneous (`unidentified_count > 0` this tick). Nothing says "a non-resident has
   been around in the last while".

The plan therefore keeps the face-alone guarantee (and pins it with tests), and the work is: add a corroborating second
leg to the room path, add the WiFi path, and publish `visitors_present`.

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
| Camera leg (unidentified body, sustained) | **REUSE** unchanged | `_guest_gate_armed` `presence.py:5998` (unidentified > 0, confidence ≥ `CONF_GUEST_MODE_REQUIRE_CONFIDENCE`, ≥ `CONF_GUEST_MODE_PERSISTENCE_SECONDS`; `const.py` defaults 300 s / `medium`) |
| WiFi guest-device filters | **REUSE**, refactored to return devices | `_get_wifi_guest_count` `camera_census.py:6001` (SSID `CONF_GUEST_VLAN_SSID` `const.py:4240`, hostname / tablet / family-tracker / MAC filters, `WIFI_GUEST_RECENCY_HOURS` `const.py:4325`) |
| "New + sustained" WiFi device | **BUILD** (small) | No equivalent. `wifi_guest_floor` uses `last_changed` recency, which a restart resets (see D1). Edge shape copied from `arrival_edges.py` (live `not_home → home`, boot exclusion), not imported (different entity class) |
| GUEST composition | **EXTEND** | `guest_armed` composition `presence.py:6586-6612`; `infer()` entry `:1425`, exit `:1399` |
| GUEST exit persistence | **REUSE** | `guest_exit` veto `presence.py:7328-7380` (`_guest_exit_quiet_since`, `_guest_persistence_seconds`); GUEST min dwell 300 s `house_state.py:137` |
| Kill switch for all guest detection | **REUSE** | `switch.ura_presence_guest_detection_enabled` (`PresenceGuestDetectionEnabledSwitch` `switch.py:3899`, field `_guest_detection_enabled`) |
| `visitors_present` entity | **BUILD** | grep `visitor` over the package: only a comment at `config_flow.py:5141`. `URAUnexpectedPersonSensor` (`binary_sensor.py:1889`) is instantaneous and keeps distinct semantics (KEEP) |
| `guest_reason` attribute | **EXTEND** | `presence.py:6615-6637`, published `sensor.py:5836` |
| Known-guest face / `identified_guests` | **REUSE as annotation only** | `CONF_KNOWN_FACE_GUESTS` `const.py:3355`; `_get_egress_guest_ids_fresh` → `_last_identified_guests_count` `camera_census.py:6355-6363`; published `sensor.py:3765-3772` |
| Trip-wire NM | **REUSE pattern** | stuck-signal NM shape of `sleep_raw_hold` / `zone_hold_all_away` (presence state of play §2, §9) |
| Two-leg confidence | **EXTEND** | `_d5_guest_confidence` `presence.py:6645-6665`, override `:7236` |

Greps run (2026-11-09): `GUEST_ROOM|guest_room_gate|GUEST_VLAN|WIFI_GUEST|identified_guests|guest_gate_armed|visitors|VISITOR`
over `const.py`; `HouseState.GUEST|== "guest"|"guest"` over the package (consumer list §3.3);
`_guest_room_gate_armed|_guest_gate_armed(|guest_armed|_unidentified_first_seen|_guest_reason` over the package
(site list §4); `identified_guests|wifi_guest_floor|_get_wifi_guest|known_face_guests|is_guest` over `camera_census.py`;
`visitor` over the package; `wifi_guest|census_snapshots|house_state_log` over `database.py` (no WiFi column in
`census_snapshots`, `database.py:1064`; `house_state_log` `:1494`).

### 1.2 Prior plans, audits, memory consulted

| Doc | Use |
|---|---|
| `PLANNING_guest_census_correctness.md` (§INV-GUEST-LEAD :63, INV-GUEST-NO-RESIDENT, M1 trades :407-445) | The current design. This plan relaxes INV-GUEST-LEAD for one combination (cam + WiFi), on operator approval |
| `AUDIT_guest_mode_fp_2026_10_17.md` | The room-alone entry, GUEST consumer effects, the WiFi devices (MacBookAir with hostname; guest phone with none) |
| `AUDIT_face_source_registry_discovery_2026_11.md` §8-9 | F-5: 87 Ojini labels, all mislabels (operator); `wifi_guest_floor` non-zero most of the week |
| `PLANNING_presence_guest_latch_and_veto_gap.md` + memory `project_presence_guest_latch_and_veto_gap` | Exit above the sleep branch (v5.16.0); superseded memory, not re-planned |
| `PLANNING_v4.6.2.2_guest_mode_hardening.md` | Path A persistence/confidence guards (reused as the camera leg) |
| `PLANNING_hvac_guest_as_zone_person.md` | HVAC already treats GUEST as `home`; no thermostat work |
| Cards `CENSUS-GUEST-FLOOR-1` (pre_planning), `GUEST-GATE-DOOR-IDENTITY-1` (parked), `GUEST-FP-RESIDUALS-1` (parked) | §8 dispositions |
| Memory `feedback_marginal_benefit_pushback`, `feedback_suppression_needs_discharge`, `feedback_coincidental_equality_masks_concept_split` | Shaped §2.3, D4, the separate boot constant |

### 1.3 Config-first

No setting expresses "two independent legs". Un-flagging the guest rooms disables GUEST entirely; raising the room
threshold only delays the room-alone entry. The operator-side lever that does help, and is recommended regardless:
give Guest Bedroom 2 BLE coverage (a direct scanner or `scanner_areas` borrowing that resolves a resident INTO GB2), so
`_is_known_person_in_room` can see a resident there (10-17 audit, "smallest safe remedy"). That fixes the resident
case only, not the "who is this body" case, so code is still needed.

---

## 2. Design

### 2.1 Legs

Three evidence legs, each a boolean per inference tick:

| Leg | True when | Producer | Evaluated in |
|---|---|---|---|
| `room` | `_guest_room_gate_armed()` (unknown occupant ≥ room threshold in a flagged guest room) | presence, unchanged | HOME_* and GUEST (today), plus every other state for display (pure apart from its existing known-person correction) |
| `cam` | `_guest_gate_armed()` returned True within the last `GUEST_CAM_LEG_LATCH_S` | presence: stamp `_guest_cam_leg_last_true` on each True return | stamped only where Path A runs today (HOME_*); read everywhere |
| `wifi` | ≥ 1 guest-SSID device with a live arrival edge seen by URA and continuously `home` for ≥ `GUEST_WIFI_SUSTAIN_S` (D1) | census, read by presence | every tick; forced False when `GUEST_WIFI_LEG_ENABLED` is False |

**Known-guest faces are not a leg.** A `guest:*` name (`known_face_guests`, egress `identified_guests`) never sets a
leg. It is published as `visitor_names` on the `visitors_present` entity only while `visitors_present` is already on
from a leg. This satisfies the approval ("a guest face alone never even counts as a visitor without a second signal")
in the simplest way: the second signal is itself a leg, so the face adds nothing to the decision. See §2.3 for why the
face-as-evidence variant is parked.

### 2.2 Rules

- **`visitors_present`** (low bar) = house state is GUEST, OR any leg is true. Display + annotation only in this cycle.
- **GUEST entry** (high bar) = at least TWO DISTINCT legs are true, and at least one of them is `room` or `wifi`.
  Allowed pairs: `cam+room`, `cam+wifi`, `room+wifi`. A single leg never enters, so `room` alone (the 10-17 shape) and
  `wifi` alone (an IoT device that slipped the filters) both stop entering. This is the operator's rule ("visitors
  present AND (guest room OR guest WiFi)") with the independence condition written in. Without it, `wifi` could
  satisfy both halves.
- **GUEST hold** (hysteresis, lower bar): stay in GUEST while `room` OR `wifi` is true. `cam` alone does not hold.
- **GUEST exit (explicit discharge):** the hold condition false continuously for `_guest_persistence_seconds`
  (existing `guest_exit` veto, unchanged), then GUEST → HOME_* via the existing exit at `infer()` `:1399`.
  The other existing discharges stay: `switch.ura_presence_guest_detection_enabled` OFF, GUEST → AWAY, manual override.
- **Kill switch:** `GUEST_TWO_LEG_GATE_ENABLED` (rung 1, True). False = today's composition, byte-identical
  (`guest_armed = guest_room_gate_armed` in both branches; no leg reads affect it).

What changes for the house, versus today:

| Situation | Today | After |
|---|---|---|
| Unknown body 30 min in GB1/GB2, census clean, no new WiFi device (10-17) | GUEST | `visitors_present` on, **no GUEST** |
| Guest walks past interior cameras (Path A qualifies), then 30 min in a guest room | GUEST | GUEST (`cam+room`), if the camera run is within the latch |
| Guest phone joins Revel and stays, guest sits in GB1 30 min | GUEST (room) | GUEST (`room+wifi`) |
| Gathering in living room: cameras see unknown bodies ≥ 300 s, guest phones on Revel ≥ sustain | no GUEST | **GUEST** (`cam+wifi`) — new, operator-approved; relaxes INV-GUEST-LEAD |
| Frigate names a resident "Ojini" | no GUEST | no GUEST; not even `visitors_present` |
| Guest leaves the guest room for the kitchen | exits after 300 s quiet | same, unless their phone holds `wifi` |

### 2.3 Marginal-benefit pushback (done before the spec, per the rule)

- **Known-guest face as positive evidence: PARK.** F-5 measured 87/87 Ojini labels as mislabels; HomeLab removed the
  Ojini library and raised the face thresholds on 11-09, so there are no guest labels to use today. Its best case adds
  a few minutes of earlier `visitors_present`. A "same label on a second camera" corroborator is new fusion code for
  ~zero measured value. **Revival trigger:** `known_face_guests` non-empty AND ≥ 10 guest-label face rows in 14 days
  that the operator confirms as real visits.
- **F-5 S7 subtraction (known-guest face lowers the unidentified count): PARK, not folded.** With no guest labels it
  changes nothing here; the audit measured the upside at 4 of 34 episodes. Same revival trigger.
- **WiFi "known device memory" (devices seen on K of D days are household IoT): PARK to CENSUS-GUEST-FLOOR-1**, which
  owns the device lifetime/decay design. This cycle ships the WiFi leg only if D0 shows the live-edge + sustain filter
  is clean on its own; otherwise the leg ships OFF and GUEST runs on `cam+room` only.
- **NM on `visitors_present`: PARK.** No consumer is wired this cycle. Revival trigger: the operator asks for a
  "visitors arrived" notification after seeing the entity for two weeks.
- **What the simplest version captures:** requiring a second leg on the room path is the whole FP fix. The WiFi leg is
  the only addition with new-ingredient risk (a new producer feeding house state); D0 gates it.

### 2.4 Falsifiable invariants

- **INV-SPLIT-1 (no single modality).** For every reachable tick with `GUEST_TWO_LEG_GATE_ENABLED` True and no manual
  override, if the house transitions INTO GUEST then at least two of {`room`, `cam`, `wifi`} were true on that tick and
  at least one was `room` or `wifi`. Corollary: a Frigate face label (resident or `guest:*`), on its own or repeated,
  can never enter GUEST, and never sets `visitors_present`.
  *Falsifier to try:* a mislabelled face on two cameras for 30 min with a clean BLE census (no leg fires: face is not
  a leg, and the body is cancelled by BLE so `cam` stays false); a resident without a GB2 BLE fix in GB2 for 2 h
  (`room` only); an IoT device that reconnects every 20 min (`wifi` needs a continuous sustain); a restart with a
  guest-SSID device already `home` (no live edge → no `wifi`).
- **INV-SPLIT-2 (discharge).** GUEST is never held by `cam` alone, and every GUEST episode ends within
  `_guest_persistence_seconds` + one inference tick of the last instant at which `room` OR `wifi` was true, unless an
  override or AWAY intervenes first.
- **INV-SPLIT-3 (kill switch).** With `GUEST_TWO_LEG_GATE_ENABLED` False, `guest_armed`, `guest_reason`,
  `_d5_guest_confidence` and the `infer()` result are byte-identical to `develop` @ `6b97e434` for every input.
- Carried unchanged: **INV-GUEST-NO-RESIDENT** (the room leg never fires on known residents) and the v5.16.0 exit-before-
  sleep ordering (I-D1).

---

## 3. Producer and consumer checks

### 3.1 Producers

| Value | Arithmetic | Dependencies and their health |
|---|---|---|
| `room` leg | unknown occupant continuously present ≥ threshold (30 min) in a flagged room; known person in room (BLE `location` == room name, 120 s sticky) cancels | Room occupancy: GB1/GB2 ride the Matter MS600 presence radars (SENSOR_FLEET_CLASSES §Meross). BLE: GB2 has no own scanner (`scanner_areas: ['guest_bedroom_2_closet']`), so residents in GB2 read unknown — **degraded for GB2** |
| `cam` leg | Path A: `unidentified_count > 0` AND census confidence ≥ `medium` AND continuous ≥ 300 s; latched `GUEST_CAM_LEG_LATCH_S` | `unidentified_count` = clamped camera bodies minus the BLE/face union (`camera_census.py:6300-6410`, INV-CENSUS-ATTRIBUTION). Healthy but conservative: on 61/70 F-5 ticks the clamp zeroed it. Face labels were wrong (F-5), now thresholds raised. Interior cameras do not cover the guest rooms |
| `wifi` leg | D1 | UniFi router trackers on SSID "Revel" (live `CONF_GUEST_VLAN_SSID`). Hostname-less devices are skipped (Filter 1), so the 10-17 guest's phone (no hostname) would not count; her MacBookAir would. **Unmeasured for FPs: D0** |
| `visitors_present` | GUEST OR any leg | as above |
| GUEST | §2.2 | as above |

### 3.2 `visitors_present` consumers

New. Readers this cycle: the entity itself (display) and nothing else. It is not read by `infer()`; the GUEST gate reads
the legs directly so the gate does not depend on the entity's state machine.

### 3.3 GUEST consumers (verified by grep; none changes code)

| Consumer | file:line | Trust / display | Effect of the split |
|---|---|---|---|
| HVAC preset map guest → `home` | `hvac_const.py:1293` | trust (preset writes) | fewer GUEST episodes; GUEST already behaves as `home` (10-17 audit: no distinguishable effect) |
| HVAC Custom Preset Ranges predicate `house_state == "guest"` | `preset_overrides.py:115-148`; rollout zone_3, switch on (HVAC doc §8) | trust | only fires in GUEST; fewer episodes |
| Dynamic preset guest offset reset | `dynamic_preset.py:861` | trust | no offset keys configured (10-17 audit), moot |
| Arrester hold-preserving states | `hvac_const.py:229` | trust | none |
| Security armed-state map guest → ARMED_HOME | `security.py:183` | trust (arming) | state-driven arming not live (10-17 audit); fewer episodes |
| SC lock regime: GUEST in sleep window engages lockouts | `security_lock_regime.py:776, 808, 1410, 1477` | trust (lock actuation) | fewer false engagements; a real overnight guest still holds GUEST (§10 #29) |
| NM exterior-person severity guest = MEDIUM | `const.py:2761` | trust (severity) | fewer MEDIUM-instead-of-LOW alerts |
| Bayesian learning suppressed in GUEST | `__init__.py:3278` | trust (learning) | learns more |
| Occupancy-anomaly suppressed in GUEST | `binary_sensor.py:3570` | display | none |
| Routine forecaster passthrough | `routine_forecaster.py:101-105` | display | none |
| Memory facade guest → home | `memory_facade.py:279` | display | none |
| `binary_sensor.ura_guest_mode` | `binary_sensor.py:2450` | display | none |
| House-state sensor `guest_reason` | `sensor.py:5836` | display | gains `two_leg:<legs>` values (D3) |
| Census sensor `identified_guests_count`, `wifi_guest_floor` | `sensor.py:3765-3772`, `camera_census.py:6435` | display | unchanged; D1 adds `wifi_guest_devices_sustained` |
| Wall-panel brightness automation (HA YAML, not URA) | `automations.yaml:8270` per 10-17 audit | cosmetic | fewer episodes |
| Lighting in URA | grep found no URA lighting reader of GUEST | — | — |

Direction: every consumer sees fewer GUEST episodes (room-alone removed) plus the new `cam+wifi` episodes.

---

## 4. Decision-site enumeration (every site that reads or writes the gate)

From `grep -n "_guest_room_gate_armed|_guest_gate_armed(|guest_armed|_unidentified_first_seen|_guest_reason"` on develop.
The builder re-runs it; this list is a hypothesis.

| # | Site | Change |
|---|---|---|
| S1 | `presence.py:6586-6600` HOME_* branch: `unid_gate_armed`, `guest_room_gate_armed`, `guest_armed = guest_room_gate_armed` | stamp cam leg; read wifi leg; compose entry (§2.2) |
| S2 | `presence.py:6601-6609` GUEST branch: `guest_armed = guest_room_gate_armed` | compose HOLD (`room OR wifi`) |
| S3 | `presence.py:6610-6613` else branch (all False) | evaluate legs for `visitors_present` only; `guest_armed` stays False |
| S4 | `presence.py:6615-6637` `guest_reason` | add `two_leg:<a>+<b>`; keep existing precedence when the switch is off |
| S5 | `presence.py:6645-6665` `_d5_guest_confidence` + canary | two-leg confidence (0.9 any pair incl. room; 0.85 `cam+wifi`; rung 1); canary condition updated so it does not fire on `cam+wifi` |
| S6 | `presence.py:7046` `infer(guest_gate_armed=guest_armed)` | unchanged literal (anchor) |
| S7 | `infer()` exit `:1399` and entry `:1425` | unchanged; they consume `guest_gate_armed` |
| S8 | `presence.py:7236` confidence override guarded on `guest_room_gate_armed` | guard on "entered via two-leg gate" so `cam+wifi` also gets S5's value |
| S9 | `presence.py:7328-7380` `guest_exit` veto | unchanged (hold semantics come from S2) |
| S10 | `presence.py:7598-7603` `_disarm_guest_gate()` on GUEST edges | unchanged; must NOT clear `_guest_cam_leg_last_true` (the latch is separate state) |
| S11 | `_schedule_guest_persistence_recheck` `presence.py:6070` | unchanged |
| S12 | `switch.py:3903` guest-detection kill switch | OFF must also force every leg False and `visitors_present` off |
| S13 | `sensor.py:5836` `guest_reason` publish | unchanged code; new values |
| S14 | `HouseStateMachine.set_override(GUEST)` | not gated (by design, INV-GUEST-LEAD note) |

---

## 5. Deliverables

### D0 — Read-only measurement probe (go/no-go)

`scripts/probes/guest_split_d0.py`, run as `ssh ha "python3 -" < script`, read-only on the HA recorder and the URA DB.
Report appended to this plan as §D0-results. Data limits stated in the report: the recorder keeps ~7 days; URA DB
`house_state_log` and `census_snapshots` go further (report the actual oldest row).

Questions:
1. **Guest-WiFi devices (recorder, all retained days).** For every router `device_tracker` on essid Revel passing the
   existing filters: home/not_home episodes, each episode's length, and how many episodes start with a real
   `not_home → home` edge (not a restore at boot; report restarts from `homeassistant_start` events). For sustain
   S ∈ {10, 30, 60, 120} min: per day, the number of devices that would set `wifi`, split by days with and without an
   operator-known visit (operator supplies the visit days; the 10-14..10-17 long-term guest is one).
   Also: hostname-less devices that otherwise look like phones (the filter gap).
2. **Guest rooms (recorder + `house_state_log`).** For GB1/GB2: occupied runs ≥ 30 min, who BLE placed where during
   each run, and each GUEST entry in `house_state_log` (all history) with trigger and confidence.
3. **Replay.** For each historical GUEST entry in the recorder window, and for each 30-min guest-room run that did not
   enter GUEST: did `cam` (Path A qualifying run, from the census sensor's unidentified/confidence history) fire within
   L ∈ {30, 60, 120, 240} min before, and would `wifi` (from Q1) have been true? Tabulate today vs the new rule:
   entries kept, entries removed, entries added (`cam+wifi`), each labelled real / FP / unknown with the operator.
4. **Cam leg alone:** how often Path A qualifies per day (the old chronic 2-4/day arming), to size the latch's FP
   exposure.

**Go/no-go:**
- `GUEST_WIFI_LEG_ENABLED` default True only if, at the chosen sustain, `wifi` is false on every no-visit day in the
  window. Otherwise it ships False (the leg is computed and published as a shadow attribute) and the cycle is
  `cam+room` only. Either outcome is a valid cycle.
- `GUEST_CAM_LEG_LATCH_S` and `GUEST_WIFI_SUSTAIN_S` defaults come from Q3 / Q1.
- If Q3 shows that `cam+room` would have lost most known-real guest entries (guests go straight to the room, unseen by
  cameras) AND `wifi` is not usable, stop and page the operator before build: the high bar would then mean almost no
  GUEST at all.

**Acceptance criteria**
- **Verify:** the report has a table per question, with sources, row counts and the window.
- **Verify:** each default in D1/D3 cites its D0 row.
- **Test:** none (probe).
- **Live:** none (read-only; no HA state changed).

### D1 — WiFi guest-device producer

In `camera_census.py`:
- Refactor `_get_wifi_guest_count` into `_get_wifi_guest_devices(now) -> list[str]` (entity ids passing the SAME
  filters, including the 4 h recency) and `_get_wifi_guest_count = len(...)`. `wifi_guest_floor` byte-identical.
- New per-census-tick edge tracker over router trackers on the guest SSID that pass filters 1-4b (recency NOT applied
  here): keep `_wifi_guest_seen_away: set[str]` (seen not `home` on a prior tick this process) and
  `_wifi_guest_home_since: dict[str, datetime]` (set when a device seen away is now `home`; cleared when it reads
  anything but `home`). A device already `home` at the first tick after setup has NO entry, so a restart never
  manufactures arrivals (HA's restore stamps `last_changed` at boot, presence doc §8). Edges inside
  `GUEST_WIFI_BOOT_EXCLUDE_S` of census setup are ignored.
- `wifi_guest_devices_sustained(now)` = devices whose `home_since` ≤ now − `GUEST_WIFI_SUSTAIN_S`. Published on the
  census sensor as `wifi_guest_devices_sustained` (count) and in `_unrecorded_attributes` as the entity-id list.
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
  `::test_filters_still_apply`.
- **Live:** after restart, `wifi_guest_devices_sustained` reads 0 on `sensor.universal_room_automation_persons_in_house`
  for at least the sustain window even though `wifi_guest_floor` may be > 0.

### D2 — `visitors_present` producer and entity

- `PresenceCoordinator` computes the three legs once per inference tick (S1-S3) into `_guest_legs: dict[str, bool]`,
  entry-reset at the top of the guest block, and `_visitors_present = house is GUEST or any(legs)`.
- New `binary_sensor.ura_presence_coordinator_visitors_present` (Presence Coordinator device, `has_entity_name`, unique
  id `{DOMAIN}_visitors_present`), push-updated with the house-state sensor. Attributes: `legs` (the three booleans),
  `since` (rising edge), `visitor_names` (sorted `guest:*` names from `identified_guests` + known-guest face names,
  only while on). `legs` and `visitor_names` in `_unrecorded_attributes`.
- Guest-detection switch OFF → all legs False, entity off.

**Acceptance criteria**
- **Verify:** a known-guest face with no leg leaves the entity off and `visitor_names` empty.
- **Verify:** `room` alone turns it on and does not enter GUEST.
- **Discriminates:** under the fix, a resident mislabelled as `guest:ojini` on two cameras for 30 min with BLE in the
  room gives entity off; under a build that let the face set a leg, it gives on.
- **Test:** `test_guest_split_visitors.py::test_face_alone_never_visitor`, `::test_room_alone_is_visitor_not_guest`,
  `::test_names_only_when_on`, `::test_kill_switch_forces_off`.
- **Live:** the entity exists, reads `off` with house state not GUEST and `legs` all False; its unique id resolves in the
  registry.

### D3 — Two-leg GUEST gate (Tier-3 site)

Sites S1-S14 per §4. Composition in ONE helper, `PresenceCoordinator._compose_guest_gate(legs, current_state) -> bool`,
pure, called from S1 and S2; S3 does not call it. `GUEST_TWO_LEG_GATE_ENABLED` False returns `legs["room"]` in both
states (INV-SPLIT-3). The cam latch stamp happens at S1 only when `_guest_gate_armed` returns True; it is never cleared
by `_disarm_guest_gate` (S10); it is cleared by the guest-detection switch OFF.

On every transition INTO GUEST, one INFO line `guest gate legs=<room,cam,wifi> reason=<guest_reason>` (the L4 oracle).

`guest_reason` precedence when on: `two_leg:<sorted legs>` (entry or hold) > `guest_room:<room>` (room leg alone, now
"visitor, not guest") > `unidentified_corroborator_only` > `override` > `none`.

**Acceptance criteria**
- **Verify (INV-SPLIT-1):** table-driven test over all 8 leg combinations × {HOME_DAY, HOME_EVENING, HOME_NIGHT}:
  GUEST proposed only for the three allowed pairs and the triple.
- **Verify (INV-SPLIT-2):** in GUEST, `cam` true alone → exit after the persistence window; `wifi` true alone → hold.
- **Verify (INV-SPLIT-3):** switch False, replay a fixture of 200 recorded ticks: identical `guest_armed`,
  `guest_reason`, confidence and `infer()` output vs the pre-change function (golden captured on `6b97e434`).
- **Verify:** sleep-hour ordering unchanged (exit before the sleep branch, I-D1).
- **Config boundary:** room threshold 1 and 600 min; persistence 0 and 3600 s; latch 0 (cam leg off) and max; sustain 0
  (rejected at load: clamp to ≥ 60 s) and max; WiFi leg off/on.
- **Discriminates:** the 10-17 replay (room 30 min, census clean, MacBookAir edge at 20:12Z): under the fix with the
  WiFi leg ON and sustain ≤ 54 min, GUEST at 21:06Z via `room+wifi`; with the WiFi leg OFF, no GUEST and
  `visitors_present` on. Under a build that kept `guest_armed = room`, GUEST at 21:06Z with reason `guest_room:` in both
  configurations. The reason string separates them.
- **Test:** `test_guest_split_gate.py::test_pair_matrix`, `::test_hold_room_or_wifi_only`, `::test_cam_alone_never_holds`,
  `::test_kill_switch_byte_identical`, `::test_exit_before_sleep_branch`, `::test_cam_latch_survives_disarm`,
  `::test_config_extremes`, `::test_1017_replay`. Each of S1, S2, S5, S8, S10, S12 gets a named test that fails when
  that one site is neutered (framing C drill list).
- **Live:** `sensor.universal_room_automation_house_state` attribute `guest_reason` reads `none` or `guest_room:<room>`
  (not `two_leg:`) with no visitors; on the next real guest, a `house_state_log` GUEST row whose `guest_reason` at
  entry is `two_leg:*` (read from the recorder, not prose).

### D4 — Trip-wire: GUEST held by WiFi alone

One HIGH stuck-signal NM (`kind=guest_wifi_only_hold`) when the house has been GUEST for more than
`GUEST_WIFI_ONLY_HOLD_NM_S` with `room` false and `cam` false for that whole span (the WiFi leg is the only holder).
Once per GUEST episode; re-armed on GUEST exit. 0 = off. Rationale: the WiFi hold has no time bound of its own; a
device that slips the filters and stays connected would hold GUEST indefinitely (suppression-needs-discharge rule).
The NM is the discharge to a human, not an automatic exit.

**Acceptance criteria**
- **Verify:** fires once after the bound with only `wifi`; does not fire if `room` or `cam` was true at any point in
  the span; does not fire at 0.
- **Test:** `test_guest_split_tripwire.py::test_fires_once_wifi_only`, `::test_room_seen_resets`, `::test_zero_disables`.
- **Live:** no `guest_wifi_only_hold` row in `notification_log` on a day without guests.

### D5 — Docs (same commit as the build)

- Presence state of play §2 step 3 (GUEST = two legs), §7 (visitors vs GUEST), §1 consumer table row for the new
  entity, §9 card list. Correct its claim at §2 step 3 that `_guest_gate_armed` "pre-evaluates" the GUEST decision
  (it is a corroborator since 08-16) and add it to §10.
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
| `GUEST_WIFI_LEG_ENABLED` | 1 | from D0 (True only if clean) | A new producer feeding house state; turning it on must be reviewed against D0-style data | False = leg computed for display, never counted |
| `GUEST_WIFI_SUSTAIN_S` | 1 | from D0 (placeholder 1800) | Filters IoT reconnects; a fitted threshold | clamp to ≥ 60 at read |
| `GUEST_WIFI_BOOT_EXCLUDE_S` | 1 | 600 | Restart-transient guard. Own constant on purpose: equal today to `PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S` but a different concept (coincidental-equality rule) | 0 = no exclusion (edges still need a seen-away state) |
| `GUEST_CAM_LEG_LATCH_S` | 1 | from D0 (placeholder 7200) | How long a camera sighting stays evidence | 0 = cam leg only on the tick Path A is True |
| `GUEST_TWO_LEG_CONFIDENCE` / `GUEST_CAM_WIFI_CONFIDENCE` | 1 | 0.9 / 0.85 | Labels for `infer()` confidence; not gates | n/a |
| `GUEST_WIFI_ONLY_HOLD_NM_S` | 1 | 43200 (12 h) | Trip-wire bound | 0 = off |
| Room threshold `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN` | 2 (room options), REUSED | 30 | unchanged | — |
| Path A persistence / confidence `CONF_GUEST_MODE_PERSISTENCE_SECONDS` / `_REQUIRE_CONFIDENCE` | 2 (CM options), REUSED | 300 / medium | unchanged; also the exit persistence | — |
| `WIFI_GUEST_RECENCY_HOURS` | 1, REUSED | 4 | unchanged (diagnostic floor only) | — |
| Operator toggle | 3, REUSED | `switch.ura_presence_guest_detection_enabled` | live kill for all guest detection | OFF = no GUEST entry, legs False, entity off |

No new Number or options-flow field. Parsimonious-config rule: these are review-gated constants.

---

## 7. Non-goals

- No GUEST → SLEEP edge (presence §10 #29). An overnight guest still holds GUEST; consumers keyed on SLEEP still do not
  fire those nights.
- No change to the census arithmetic, the unidentified clamp, face handling, or the F-5 subtraction (parked, §2.3).
- No WiFi device lifetime / known-device memory / hostname-less phone handling (CENSUS-GUEST-FLOOR-1).
- No door-identity input to the gate (GUEST-GATE-DOOR-IDENTITY-1 stays parked on its own trigger).
- No consumer changes (HVAC, security, lock regime, NM); no NM on `visitors_present`.
- No persistence of the new legs across restarts (fail toward fewer legs; a restart mid-visit can drop a `wifi`-held
  GUEST, accepted and listed in the README).
- No DB schema change.

---

## 8. Related cards

| Card | Disposition |
|---|---|
| `CENSUS-GUEST-FLOOR-1` | Stays pre_planning. This cycle reuses its filters as a leg, not a census floor. Add a link; its lifetime/decay design is the revival path for a WiFi leg that D0 rejects |
| `GUEST-GATE-DOOR-IDENTITY-1` | Stays parked; trigger unchanged |
| `GUEST-FP-RESIDUALS-1` | Its first revival clause fired on 10-17 (~2.2 entries/day); this cycle is the response to that clause for the room-alone flavour. Add a link and note |
| `FACE-SOURCE-REGISTRY-DISCOVERY-1` | Its F-5 residual folds here as PARKED (§2.3), with the revival trigger |

---

## 9. Tier classification

**Tier 3.** Trigger: the change recomposes `guest_armed`, which is threaded into `infer()` and governs both entry
(`:1425`) and exit (`:1399`) of the house-state machine — the card's own escalation condition. GUEST is consumed by lock
actuation (lock regime), security arming and HVAC presets, so one missed composition site is a silent behaviour change.

Required: TWO framing-disjoint plan reviews before build (completeness re-enumeration of §4 and §3.3; adversarial
build-prediction), then four code reviews A/B/C/D (D states INV-SPLIT-1 and tries to break it, including pre-existing
paths such as the manual override and the boot seed), config-extreme tests (§D3), orchestrator re-grep + one real
source mutation on S1/S2 before ship, and an operator checkpoint before deploy. Builder: `ura-super-builder`.

## 10. Live validation (post-restart, feeds the README)

| # | Check | Source |
|---|---|---|
| L1 | `binary_sensor.ura_presence_coordinator_visitors_present` exists, `legs` attribute has three keys | live entity |
| L2 | `wifi_guest_devices_sustained` = 0 for the first sustain window after restart | census sensor attribute |
| L3 | `guest_reason` never `two_leg:*` while `visitors_present` is off | recorder, house-state sensor |
| L4 | No GUEST row in `house_state_log` whose entry tick had a single leg (query the presence INFO line `guest gate legs=` added at entry) | URA DB + log |
| L5 | First real guest: GUEST entry with `two_leg:*`, exit within persistence of the last room/wifi leg | recorder + `house_state_log`; organic, disposed by its binary discriminator per the soak-exit rule |
