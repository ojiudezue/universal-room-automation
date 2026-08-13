# AUDIT — Missed home_day → away transition, 2026-08-13 (~11:30–15:51 CT)

**Status:** Diagnosis of record. READ-ONLY incident audit — no fixes applied.
**Evidence:** HA recorder (`/config/home-assistant_v2.db`, mode=ro) + URA DB
(`house_state_log`, `notification_log`) + source trace on develop @ a7ff3574.
All timestamps below are **UTC (Z)**; CT = UTC−5.

## Verdict in one paragraph

The house never received a trustworthy "everyone is away" signal, and the one
fallback path that tolerates untrustworthy trackers was — by design — vetoed by
indoor occupancy. That indoor occupancy was a single phantom: the Living Room
Screek mmWave, pinned ON by the room's own comfort fan, which URA's fan policy
kept running *because the room read occupied* (a closed loop). Every shipped
mechanism that should have broken the loop was individually, deliberately
disabled for exactly this room: the mmWave-fan sustain demotion fails closed on
rooms with no PIR (`motion_sensors: []`), the continuous-stuck rule needs 4 h
(the hold was 2 h 01 m), and the duty-cycle rule is NOTIFY-ONLY by design.
When the operator killed the fans at 20:46Z, the mmWave released in **37
seconds** and the house went `away` 4½ minutes later — the fan was the occupant.

## (a) Incident timeline

| UTC | CT | Event | Evidence |
|---|---|---|---|
| 13:30:14 | 08:30 | `binary_sensor.guest_bedroom_1_occupied` ON (on/off all midday) | recorder |
| 14:37:49 | 09:37 | house `guest → home_day` (guest room cleared 14:32:49 + exit clear) | house_state_log |
| 16:43:02–:09 | 11:43 | `person.oji_udezue` and `person.ezinne` → not_home. **Census stays 2** — Jaya/Ziri trackers stale-home for another ~2.7 h | recorder |
| 15:53:53 | 10:53 | Guest Bedroom 1 occupied ON again | recorder |
| 16:23:59 | 11:23 | `home_day → guest`, trigger `guest_room_occupancy` — Path B 30-min threshold: 15:53:53 + 30:06 | house_state_log |
| 16:30:59 | 11:30 | `guest → home_day` (guest room off 16:25:59) | house_state_log |
| 18:40:08 | 13:40 | Living Room Screek presence ON (`binary_sensor.living_room_presence`); `living_room_occupied` ON 18:40:10 | recorder |
| 18:45:02 | 13:45 | `fan.towerfan_dreopilotmaxs_wifi_livingroom` ON; Screek re-latches ON 18:45:08 and **holds continuously 2 h 01 m** | recorder |
| 19:15:43 | 14:15 | `binary_sensor.living_room_fan_should_run` ON — comfort-fan policy sustains the fan because the room reads occupied. **Loop closed: occupancy→fan→mmWave→occupancy** | recorder |
| 19:24:17 | 14:24 | ALL FOUR persons excluded from trust: `excluded_persons = {Oji: lost, Ezinne: lost, Jaya: stale, Ziri: stale}`; `tracked_persons_count_trusted = 0`; `all_tracked_persons_away = false` (and stays false through the whole window) | house-state sensor attrs |
| 19:28–19:29 | 14:28 | Ziri → not_home; **census → 0** (19:29:17). From 19:29:47 the ONLY occupied zone is Entertainment, provenance `{mmwave: 1}`, `fan_on_rooms: ["Living Room"]`, `fan_interference_rooms: ["Living Room"]` | attrs |
| 19:29–20:46 | 14:29–15:46 | **82 minutes**: census 0, all persons away, house held `home_day` by one fan-pinned mmWave. `veto_path: "none"` on every tick | attrs |
| 20:15:03 | 15:15 | Jaya Bedroom fan ON (empty room) | recorder |
| 20:46:05–:16 | 15:46 | Operator turns off tower fan, `fan.fan_switch_4`, Jaya Bedroom fan (`context_user_id=None`, no parent context → vendor app / physical, not an HA dashboard call) | recorder |
| 20:46:42 | 15:46 | Screek presence OFF — **37 s after fan-off** | recorder |
| 20:51:06 | 15:51 | `home_day → away` conf 0.9 (trigger string `guest_room_occupancy` is just the inference-tick reason, not the cause); `living_room_occupied` OFF 20:51:40 | house_state_log |

## (b) Root-cause chain (file:line)

1. **Trust collapse emptied the away-veto denominator.** By 19:24Z all four
   person trackers were LOST/STALE → excluded → `tracked_persons_count_trusted=0`
   → `all_tracked_persons_away=False`. Path α (the v4.7.14 high-confidence AWAY
   veto, `domain_coordinators/presence.py:~1048-1057`) requires
   `all_tracked_persons_away AND unidentified_count==0 AND census_count==0`
   — it was structurally unreachable the entire window. This is the known
   "away⇒LOST empties the veto denominator" gap (v5.16.0 memory), operating as
   shipped.
2. **Path β (the LOST-tolerant veto built for exactly this) was blocked by the
   phantom zone.** `presence.py:~1093-1141`: β requires `not indoor_blocked`,
   where `indoor_blocked` = any indoor zone occupied. Entertainment was
   "occupied". This veto is intentional — invariant I1, never force AWAY while
   an indoor zone is occupied. Correct design, wrong input.
3. **The census-0 "nobody home" rule was blocked the same way.**
   `presence.py:~1026-1031`: `census_count==0 AND not any_zone_occupied`.
4. **The occupancy was fabricated by fan-on-mmWave.** Screek L13 2412S ON
   18:45:08 (6 s after fan-on) → 20:46:42 (37 s after fan-off). Sole provenance
   of the Entertainment zone from 19:29:47. Meanwhile
   `living_room_fan_should_run` kept the fan running because the room read
   occupied — a self-sustaining loop.
5. **Every breaker for that loop was disabled for this specific room** — see (c).

## (c) Which shipped mechanisms should have caught it, and why each didn't

| Mechanism | Where | Why it didn't fire |
|---|---|---|
| **D2 mmWave-fan sustain demotion** (v5.23.0+) | `coordinator.py:2740-2960` | Predicate requires `_d2_motion_sensors_present()` (`coordinator.py:1786-1815`, D-HIGH-1): **fail-closed when the room has zero PIR**. Living Room config: `motion_sensors: []`, `occupancy_sensors: []` (verified in `core.config_entries`). Leg (e) — PIR staleness ≥ MULT×timeout — is unsatisfiable, so the demotion is permanently off for this room. All other gates (house_state home_day allows, fan flagged: `fan_interference_rooms=["Living Room"]`) would have passed. |
| **Fan-transition CREATION gate** (v5.46.0) | `coordinator.py:~2290+`, `FAN_TRANSITION_SUSPECT_WINDOW_S=5.0` (`const.py:729`) | Creation-only by design (predicate (c): `not self._last_occupied_state`). Occupancy was created at 18:40:10 — fan turned on at 18:45:02, five minutes later. The fan captured an already-occupied room; that is sustain, not creation. Also possibly legitimate creation (Ziri/Jaya trackers still home at 18:40). |
| **Continuous-stuck rule (P22, Fix #9 — the one that DOES exclude)** | `coordinator.py:2117-2145`, `_stuck_sensor_hours=4.0` (`coordinator.py:283`) | Needs 4 h continuous-on. The final hold was 2 h 01 m (18:45:08→20:46:42), and every earlier off-tick that morning reset `_sensor_on_since`. Threshold simply not met — and the flapping-evades-continuous defect is exactly what the STUCK-SENSOR-1 card documents. |
| **D2 duty-cycle stuck detector** (v5.35.0) | `coordinator.py:2155-2200`; 60-min window, 85 % on-ratio, no PIR corroboration required here (none configured) | **Did detect — NOTIFY-ONLY by design** ("a sleeping person is ~100 % mmWave duty cycle... excluding would vacate sleeping bedrooms", FIX 2 B H-1 comment at `coordinator.py:2176-2183`). `notification_log` shows `Stuck signal: dutycycle` NM notes at 13:54, 17:10, 18:00, 18:20Z (room redacted `[audit]`; per-day dedup). Detection without consequence — the deliberate deferral recorded on the STUCK-SENSOR-1 card, blocked on SENSOR-CAPABILITY-1 + SignalTrustLedger criterion 4. |
| **Zone/house-tier stuck awareness** | none | `aggregation.py` / `presence.py` have no stuck-sensor input at all (verified on the card 2026-08-09 and re-confirmed: `veto_path="none"`, no discounting of the mmwave-only provenance). The house tier can see `fan_interference_rooms=["Living Room"]` and `tier1_provenance_breakdown={mmwave:1}` — it publishes both as attributes — but consumes neither in `infer()`. |
| **v4.7.13 sleep-only trust doctrine** | `coordinator.py:1821-1840` (`_d2_house_state_allows`) | Not the blocker here: it only vetoes demotion in SLEEP/WAKING/HOME_NIGHT; house was `home_day`, which **is** covered. The uncovered dimension in this incident is room capability (no PIR), not house state. |

Contributing (not primary): Jaya/Ziri phone trackers held stale-`home` from
~16:43Z to 19:28Z, keeping census at 2 for ~2.7 h after (per operator) everyone
had left — this delayed even reaching the census-0 precondition until 14:29 CT.

## Q6 — the guest flaps

Both flaps are the **guest-room Path B** (`presence.py:4550-4683`), not the
unidentified-census arithmetic: Guest Bedroom 1 (`room_is_guest_room=True`,
threshold 30 min) went occupied at 15:53:53Z; 16:23:59Z entry is exactly
15:53:53 + 30 min (+6 s tick). Exit 16:30:59 after it cleared at 16:25:59.
The earlier `guest → home_day` at 14:37:49 is the same room clearing at
14:32:49. Whether Guest Bedroom 1's midday occupancy was real (Jaya/Ziri were
plausibly home until ~19:28Z per their trackers) or the same phantom class was
not resolved — its input sensor trace was not pulled. The `away` transition's
trigger string `guest_room_occupancy` is only the inference-tick label.

## (d) Recommendations (ranked)

1. **Config-only — give the Living Room a corroborator (PIR or occupancy
   sensor).** `motion_sensors: []` is the single switch that disabled the
   already-shipped D2 sustain demotion for this room. One Zigbee PIR (or
   wiring the existing `rgbw_motion_lux_3rd_zigbee_livingroomhallway` if its
   coverage genuinely includes the seating area — verify placement first) turns
   the fail-closed gate open. Marginal benefit: very high (the entire 82-min
   hold releases at `MULT×occupancy_timeout`); marginal risk: near zero, no
   code. Applies to all six no-PIR rooms in
   `AUDIT_mmwave_only_rooms_2026-07-31.md`.
2. **Tier-1 — break the fan self-justification loop.** `fan_should_run` kept
   the fan on using occupancy whose sole provenance was mmWave in a room whose
   own fan is a known interferer. A small room-tier rule — comfort-fan sustain
   requires occupancy provenance other than mmwave-sole after N minutes, or a
   max mmwave-sole fan runtime — removes the loop without touching presence
   inference. Marginal benefit: high (fixes fans-in-empty-rooms even where the
   away transition isn't at stake); risk: moderate (fan policy churn — knob it,
   default generous).
3. **Tier 2-DB — let path β discount phantom-classed zones.** Today
   `indoor_blocked` treats a zone held ONLY by a fan-interference-flagged,
   mmwave-sole signal as full indoor truth, while the same payload already
   carries `fan_interference_rooms` + `tier1_provenance_breakdown`. Excluding
   such zones from the β indoor guard (NOT from occupancy itself) would have
   fired the LOST-tolerant away veto at ~19:29Z. This is a trust-hierarchy
   ripple on a shared primitive → Tier 2-DB minimum. Marginal benefit: high
   for the away transition specifically; risk: real (I1 erosion — must not
   force AWAY on a sleeping resident; the sleep-exempt gate already covers
   that, but reviews must prove it).
4. **STUCK-SENSOR-1 build** (corroboration-gated exclusion at the room tier) —
   the complete fix for the detector-without-consequence gap; NM notes fired
   all day and nothing consumed them. **Remains BLOCKED** on
   SENSOR-CAPABILITY-1 and the SignalTrustLedger criterion-4 golden-tap
   fixtures (hard blocker independent of approval, per the card). Note the
   card's own caveat applies to this incident: with no corroborator configured,
   Living Room would STAY notify-only even post-build — rec 1 is a
   prerequisite for rec 4 to help this room.
5. **Low-marginal / observe-only — tracker LOST hygiene.** All four trackers
   LOST/STALE simultaneously (and two stale-home for 2.7 h) is what removed
   path α. Note path α **ignores zone occupancy entirely** — had the trackers
   stayed ACTIVE and reported away, α would have fired at ~19:29Z despite the
   phantom. The incident required BOTH failures: trust collapse (killed α) AND
   the phantom zone (killed β + nobody-home). So improving phone tracker
   liveness (Jaya/Ziri devices, WAT-timezone quirk) is a genuine independent
   mitigation —
   but it is device/app work, not URA code, and recs 1-3 cover the house-side
   hole regardless.

## Dig: why fan exclusion failed

Operator question: *"We are filtering fan start impulse right? Why was fan
exclusion failing?"* Answer, evidence-first (develop @ a7ff3574; live deploy
verified **v5.74.0**, so every mechanism below was in the running code).

### 1. The v5.46.0 fan-transition gate was ARMED and healthy — it was out of scope by design

- **Knob live:** `FAN_TRANSITION_SUSPECT_WINDOW_S = 5.0` in the DEPLOYED
  `/config/custom_components/universal_room_automation/const.py:729` (read
  over SSH; kill switch NOT tripped).
- **Mapping live:** the gate's fan→room mapping does NOT use the fan_veto
  fused-sensor registry or the `_N`-suffix stem resolver — those are the
  v5.46.0 **camera** fixes. The gate rides `CONF_FANS` from the room's config
  entry: `presence.py::_discover_room_fans` builds
  `_fan_entity_to_room` from each ROOM entry's `fans` list and subscribes
  `_handle_fan_change` (presence.py:3296), which stamps
  `_fan_last_transition[room]` on any state edge OR percentage change
  (presence.py:3345-3378). Living Room config (live `core.config_entries`):
  `fans: ['fan.towerfan_dreopilotmaxs_wifi_livingroom']`,
  `presence_sensors: ['binary_sensor.screek_human_sensor_l13_2412s_presence']`.
  So the tower fan IS registered and IS stamped — corroborated by the live
  attrs during the incident (`fan_on_rooms=["Living Room"]`,
  `fan_interference_rooms=["Living Room"]`, both derived from the same map).
- **Why it didn't fire:** predicate (c) at `coordinator.py:2335`
  (`not self._last_occupied_state`) — the gate suppresses **CREATION only**.
  Recorder (UTC): `binary_sensor.living_room_occupied` went ON at
  **18:40:10.95** and NEVER dropped through the entire window — the Screek's
  brief OFFs at 18:41:25 and 18:44:35 were bridged by the occupancy timeout.
  When the Screek re-latched at 18:45:08 the room was already occupied →
  sustain, not creation → gate correctly stands down. Nothing to suppress
  existed at the room tier.

### 2. The 6s-vs-5s question — the sensor edge WAS a fresh creation-shaped edge, and it ALSO missed the window

Recorder edges (exact):

| UTC | Entity | Edge |
|---|---|---|
| 18:40:10.405 | Screek presence | OFF→ON (initial, fan then OFF-transitioning at 18:43:35 — pre-existing occupancy, plausibly real) |
| 18:41:25.703 | Screek presence | ON→OFF |
| 18:43:35.600 | tower fan | →`off` (fan had been ON before; this is itself a stamped transition) |
| 18:44:02.178 | Screek presence | OFF→ON (Δ=26.6s after fan-off — outside window) |
| 18:44:35.411 | Screek presence | ON→OFF |
| 18:45:02.381 | tower fan | →`on` (attr update 18:45:02.424) |
| 18:45:08.056 | Screek presence | **OFF→ON — Δt = 5.68 s** after fan-on |

So "latched 18:45:08" was a **genuine OFF→ON sensor edge**, not a
continuation — but (a) the ROOM was continuously occupied, so the gate's
creation predicate could never see it, and (b) even ignoring (a), Δt=5.68s
falls **0.68s outside** the 5.0s window. The window was calibrated on the
separability probe's Δt ≤ 1-2s exact-second alignment; a WiFi/cloud fan
(Dreo) can report its `on` edge with lag relative to the physical motor
start, and the mmWave needs a few seconds to latch onto airflow — so for
cloud-reported fans the effective creation window is tighter than the
physical one. Secondary finding, not the cause here (the creation predicate
was the binding constraint), but worth carrying to any window-retune card.

### 3. D2 sustain demotion — WOULD have owned this shape, but is capability-disabled

The sustain direction is exactly D2's charter. The live predicate
(`coordinator.py:2770-2779`): `occupied AND MMWAVE_FAN_CORROBORATION_ENABLED
AND mult>0 AND boot-settle AND debounce AND _d2_motion_sensors_present() AND
_d2_house_state_allows() AND occupancy_source=="mmwave"`, then PIR staleness
≥ MULT×occupancy_timeout, then BLE/camera truth checks. House `home_day`
passes `_d2_house_state_allows` (coordinator.py:1816-1843 vetoes only
SLEEP/WAKING/HOME_NIGHT); source was mmwave-sole; fan flagged. The single
failing leg is `_d2_motion_sensors_present` (coordinator.py:1786-1815):
`motion_sensors: []` after MMWAVE_NAME_PATTERN filtering → **fail-closed,
demotion permanently off for this room**. Had the Living Room owned one real
PIR, this exact shape (fan ON + mmwave-sole + PIR stale) demotes at
MULT×timeout and the 2h01m hold collapses. Confirms audit rec 1.

### 4. fan_veto — wrong axis entirely

`fan_veto.py:1-27` (docstring): it is the **comfort-fan house-AWAY actuation
veto** — suppresses fan `turn_on` at three actuation sites
(automation.py temperature fan control, hvac_fans.py, actuator_reconciler.py)
when `house_state ∈ {AWAY, VACATION}` and the room lacks non-mmWave trusted
presence. It vetoes the FAN, not the mmWave; and the house was `home_day`
the whole time (`_AWAY_STATES` check, fan_veto.py:54-56), so it was
structurally inapplicable. It is not, and never was, a "fan noise filters
occupancy" mechanism.

### 5. Taxonomy verdict

This incident is a **fan-latch (true RF motion, wrong attribution) in the
SUSTAIN direction** — the fan captured and re-armed a pre-existing occupancy
— NOT a stuck sensor (hardware released in 37s once the fan stopped) and NOT
a creation-window miss in any actionable sense (the room was already
occupied; the gate is scoped away from sustain on purpose).

| Class | Owner today | This incident |
|---|---|---|
| Fan-coincident mmwave-sole **CREATION** | v5.46.0 gate (armed, window 5s) | out of scope — room already occupied |
| Fan-driven mmwave-sole **SUSTAIN**, room HAS PIR | D2 demotion (v5.23.0+) | would have fired — but disabled |
| Fan-driven mmwave-sole **SUSTAIN**, room has NO corroborator | **NO OWNER** (D2 fail-closed; duty-cycle rule notify-only; STUCK-SENSOR-1 blocked AND itself corroboration-gated) | **← this incident lives here** |
| Fan **ACTUATION** while house away | fan_veto | inapplicable (home_day) |
| Hardware stuck-ON | P22 continuous 4h rule | not this (released in 37s) |

The precise unowned class: **mmwave-sole sustain in a corroborator-less room
under a non-away house state, duration < 4h.** Six rooms sit in this class
(`AUDIT_mmwave_only_rooms_2026-07-31.md`). The cheapest exit remains rec 1
(give the room a corroborator — turns the already-shipped D2 on); the
code-side exits are recs 2-3.

## Follow-up: other fans + carded coverage

Read-only follow-up (recorder mode=ro via `ssh ha`, scoped by `states_meta`;
kanban.data.yaml read end-to-end). Window 16:00–21:00Z unless noted.

### F1. Sweep of ALL fans ON in the window

| Fan | Room | ON intervals (UTC) | Room mmWave | Latch? |
|---|---|---|---|---|
| `fan.towerfan_dreopilotmaxs_wifi_livingroom` | Living Room | 18:45:02–20:46:05 | Screek L13 2412S | **YES** (audited: latch +4 s, release +37 s) |
| `fan.fan_switch_4` ("Fan Switch UpGuest") | Upstairs Guestroom | 16:40:03–18:36:59, 19:08:35–20:46:13 | `occupancy_lux_temp_humidity_hobeian_upguestroom_presence_2` | **YES, TWICE**: held 16:38:52→18:37:35 (release **36 s** after fan-off) and 19:07:59→**20:46:35** (release **22 s** after fan-off). Second episode: sensor was already flapping-on 36 s before fan-on — sustain capture, exactly the v5.46.0 creation-only gap. `upstairs_guest_bedroom_occupied` held 18:58:54→20:51:40 (cleared only by the away sweep). |
| `fan.fanswitch_treat_wifi_jayabedroom` + `fan.fan_temp_wifi_jayabedroom` | Jaya Bedroom | treat: 20:15:03–20:46:16; fan_temp: 15:34:49–18:54:51, 18:55:06→**past 21:31 (never off)** | `jaya_3` Screek (+ meross, zigbee mmWaves) | **YES, UNRELEASED**: `jaya_3` latched ON from 19:00:16 with `fan_temp` running continuously; operator turned off only `fanswitch_treat` at 20:46:16, `fan_temp` stayed on, and `jaya_3` + `jaya_bedroom_bedroom_4_occupied` were **still ON past 21:31 — after the house had gone away**. Negative control that confirms the mechanism: the one latched room whose fan was NOT killed is the one room that never released. |
| `fan.fanswitch_treat_wifi_ziribedroom` | Ziri Bedroom | 16:22:07–17:25:03 | `mmwave_zigbee_ziribedroom` | **NO** — sensor released 17:14:47 with the fan still running (10 min before fan-off). |
| `fan.polyfan_dreo704s_wifi_studya` | Study A | 16:29–17:14, 19:05–19:15 | `mmwave_zigbee_studya` | **NO** — sensor off 17:00:22 and 19:01:05 mid-fan-run. |
| `fan.air_circulator`, `fan.haf004s` | AV Closet | ON entire window | (AV Closet occupancy sensor) | **NO** — no occupancy activity recorded. |

So the fan→mmWave latch hit **three rooms, not one** (Living Room, Upstairs
Guestroom, Jaya Bedroom) — and did NOT hit two others with fans running
(Ziri, Study A): the latch is fan-model/placement-specific, not universal.

### F2. Were the other latched rooms also vetoing away? — No, but for a wrong reason

**Entertainment was genuinely the sole veto at the house tier — by
divergence, not because the other rooms were clean.** New unexplained
discrepancy, verified from recorder:

- `sensor.zone_upstairs_rooms_occupied` read **2** from 19:25:32 to 20:52:06
  (Upstairs Guestroom + Jaya Bedroom), and `binary_sensor.zone_upstairs_anyone`
  was **ON continuously from 04:34Z with no off through 22:00Z**.
- Yet `sensor.ura_presence_coordinator_presence_house_state` attrs at 19:45Z
  and 20:30Z show zone **Upstairs: mode='away'**, provenance all zeros,
  `fan_interference_rooms: []`, `fan_on_rooms: []` — the house tier could not
  see either latched Upstairs room (nor their running fans).
- Consequence both ways: (a) had Upstairs been counted the way Entertainment
  was, path β would have been blocked by THREE phantom-held zones, and killing
  the Living Room fan alone would NOT have released the house; (b) the actual
  `home_day → away` at 20:51:06 fired **while Jaya Bedroom was still
  URA-occupied and zone_upstairs_anyone was still ON**. Mechanism for the
  zone-tier vs house-tier divergence NOT established here (no source trace
  done) — flagged as its own follow-up; do not build on either behavior until
  it is explained.

### F3. The operator's multi-fan off — correction + multi-release

- The three fan-offs (`towerfan` 20:46:05, `fan_switch_4` 20:46:13,
  `fanswitch_treat_wifi_jayabedroom` 20:46:16) all carry
  `context_user_id=66bda3b7…` with no parent context — an HA-authenticated
  user action (app/dashboard). **This corrects the timeline's
  `context_user_id=None` / "vendor app / physical" note.**
- It released **two of the three** latches: Screek 2412S +37 s, Hobeian
  upguestroom +22 s. Jaya's did not release (second fan `fan_temp` untouched).
- The loop was live to the last minute: the tower fan turned **ON at 20:45:02
  with no user context** (URA re-assert) 63 s before the operator killed it.
  The release stuck only because nothing re-asserted in the 37 s before the
  Screek dropped — the v5.31.0 manual-OFF cooldown is the shipped mechanism
  that made the operator's off durable.

### F4. Carded-work coverage (kanban.data.yaml read end-to-end)

| Card (spec as written) | Verdict | Reasoning from spec text |
|---|---|---|
| **AWAY-BLOCK-1** (waiting_on_operator) | — | This incident's own card; carries all five ranked recs. It is the coverage vehicle, not prior art. |
| **STUCK-SENSOR-1** (planned, approved 08-13) | **NO-IMPACT alone / WOULD-HAVE-FIXED with rec 1** | Spec = corroboration-gated exclusion: exclude a duty-stuck sensor when NO independent corroborator supports occupancy. Its own CAVEAT: "rooms whose ONLY input is a single mmWave have no corroborator … notify-only remains correct." Living Room (`motion_sensors: []`) is exactly that room — as specced it stays notify-only there. The D2 duty flag DID fire (4 NM notes), so once a corroborator exists the exclusion keys off a signal that was live. Same caveat applies to Jaya (in the six no-PIR rooms). |
| **SENSOR-CAPABILITY-1** (shipped v5.65.0, pre-incident) | **NO-IMPACT as shipped** | I1 guarantees byte-identical behavior until a capability is DECLARED; none is declared for these rooms. It is the enabler that lets a non-PIR corroborator (camera person, BLE, bed) be nameable — prerequisite for STUCK-SENSOR-1 to cover no-PIR rooms without new hardware, zero effect by itself. |
| **GUEST-FP-RESIDUALS-1** (planned) | **NO-IMPACT** | A1 is explicitly "diagnostic clarity only — guest gate does not read them": it relabels path-α's `excluded_persons`, it does not restore the trusted denominator, so α stays dead. B1 (outdoor camera filter) untouched by this incident. **No card on the board fixes the α LOST-denominator gap itself** — the only α-side mitigation anywhere is AWAY-BLOCK-1 rec 5 (tracker liveness, device-side). |
| **FAN-LAYER-1/2** (FanPolicyOracle, shipped v5.70.0/v5.73.2) | **NO-IMPACT as specced** | The oracle arbitrates WHO may actuate (12 writers, consult+note); its policy predicates contain no occupancy-provenance test. `fan_should_run` sustaining on mmwave-sole occupancy is policy-legal under INV-FLA. It is, however, the natural single chokepoint to host rec 2 (mmwave-sole sustain cap) — one predicate, all 12 writers covered. |
| **FAN-MANUAL-1** (shipped v5.68.0) | **SHORTENED (already live)** | Not on the latch itself — on the release: the manual-OFF side (v5.31.0 cooldown + the v5.68.0 hold machinery) is why URA did not re-assert the tower fan in the 37 s between operator-off and Screek release (it had re-asserted at 20:45:02). Without it the operator's off could have lost the race. |
| **WATCHDOG-INERT-1 / P24 failsafe fix** (shipped v5.67.0) | **NO-IMPACT by design** | The CRIT-A1 fix-up explicitly guards: "failsafe simply does not apply to no-PIR rooms" (deliberate sleeping-body protection, mirrors `_d2_motion_sensors_present`). Living Room and Jaya are no-PIR → excluded on purpose. |

**Verdict: no genuinely NEW work is needed — but the incident is not covered
by building the backlog in any order.** The binding constraint is the same
fail-closed predicate in two shipped/approved mechanisms (D2 demotion,
STUCK-SENSOR-1 exclusion, P24 failsafe all key off a corroborator the room
doesn't have). The coverage path is:

1. **AWAY-BLOCK-1 rec 1 (config-only corroborators for the no-PIR rooms)** —
   the unlock for everything already built/approved. Now three-rooms-justified,
   not one. Not carded as a build because it isn't one; it is the pending
   operator decision on AWAY-BLOCK-1.
2. **STUCK-SENSOR-1** as specced (already approved; blocked on criterion-4
   supplements) — becomes effective in these rooms only after (1).
3. **AWAY-BLOCK-1 rec 2** (mmwave-sole sustain cap) — small NEW policy, but
   it has a shipped home now (FanPolicyOracle predicate) so it is an
   increment on FAN-LAYER, not a new surface. Covers rooms where (1) is
   impractical, and fixes fans-burning-in-empty-rooms independent of away.
4. **AWAY-BLOCK-1 rec 3** (β discounts phantom-classed zones) — hold unless
   evidence recurs after 1–3; note F2 weakens its payoff: the house tier
   already couldn't see two of the three phantom zones.
5. **NEW follow-up (small, uncarded until now): the F2 zone-tier vs
   house-tier divergence** — Upstairs occupied at room+zone tier, 'away' with
   zero provenance at house tier, and an away transition that fired through a
   still-occupied room. That is not on any card and needs a source trace
   before rec 3 could even be scoped safely.
