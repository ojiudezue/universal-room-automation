# AUDIT: Media Room fan left running with stuck sensors, and the "stuck sensor -> fan recheck" idea (read-only, 2026-11-15)

Card: `MEDIAROOM-FAN-LEFT-ON-STUCK-SENSORS-1` (tier 2, investigating, created 2026-11-15).
Prober: read-only. No HA state changes, no edits to code, config, board or memory. Time of probe: Sun 2026-11-15 14:07-14:30 CST (`date`).
Read first, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (1141 lines, incl. section 10 corrections ledger), `docs/architecture/SENSOR_FLEET_CLASSES.md`, `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (748 lines, fan sections 4.2b / 4.2c / 9.3 and C19 / C27 / C37 in the ledger). None of the ledger's corrected claims is re-asserted here.

Code citations are `file:line` at tag **v5.108.24** (what HA ran during the incident: `/config/custom_components/universal_room_automation/manifest.json` read over ssh at 14:07 CST). The working tree moved to v5.108.25 at 14:15 CST (`coordinator.py` shifted by +93 lines); every `coordinator.py` line below is the v5.108.24 line. HA restarted at about 14:19 CST (state rows for Meross unavailable 14:19:38, switches re-written 14:19:44).

---

## 0. Answer

1. **The Media Room fan is off in HA now** (`fan.media_room_ceiling_fan_2` off, set 13:51:40 CST by an HA user context after a 1-second `on` at 13:51:39). Both radars are off and the room is vacant; after the 14:19 restart everything still reads off. The **physical** fan state is not observable from HA (see section 3). Indirect evidence says it stopped at 13:51:40: both radars dropped 90 s later (13:53:10 / 13:53:11) with the house empty, and nothing has re-asserted in 30 minutes.
2. **Mechanism.** The incident was not a failsafe misfire. For this room **no failsafe could have acted, for three independent reasons and a fourth blind spot**:
   - (i) the fan's Fan Mode is `off` (person-owned, URA writes nothing) -> recheck veto `fan_control_off`, zone sweep skip, shared-space sweep skip, reconciler `None`;
   - (ii) the room's Automation switch is OFF (paused, and has read `off` for the whole recorder window, since at least 2026-11-08 04:12 CST) -> recheck veto `room_paused`, zone sweep skips the room, room exit actions never run;
   - (iii) **HA never saw the fan ON**: `fan.media_room_ceiling_fan_2` has no `on` row in 7.5 days except the 1-second blip at 13:51:39. Every fan-noise mechanism (recheck `no_fan_on`, `occupancy_phantom`, `phantom_retro`, fan-interference gate, zone sweep's `state == "on"`) is keyed to HA's fan state, so each saw a fan that was off. The fan is a Bond (RF/IR bridge) ceiling fan whose state HA only knows from commands it sent;
   - (iv) the stuck-sensor machinery did act, and was inert for this purpose: the Matter radar was excluded at 4.0 h (23:41 CST) but the Meross radar-derived "motion" bit kept the room occupied through the night (`occupancy_source` alternates `motion` / `timeout`), the Meross chatter detector is in **shadow** mode (NM only), and neither stuck path is connected to any fan code.
   The 4 h room max-occupancy failsafe (P24) is also exempt in this room (no fan-immune witness) and would be refreshed anyway by the flapping motion bit.
3. **There is no AWAY action that turns a fan off.** The AWAY leave-on sweep is lights only; the comfort-fan AWAY veto only blocks fan turn-ON. Even an AWAY house with an empty, held room (AWAY at 13:43:29 CST, room held 10 more minutes) has no fan-off path.
4. **The operator's idea (stuck sensor -> recheck / quiet the fan)** would not have changed this incident: the recheck's binding vetoes are config + fan visibility, not the sensor condition. The useful kernel is different: when a fan's state is unobservable (RF / assumed), "radar-held room with nobody there" is the only evidence a fan is running. Merit and risks in section 5; simplest version in section 5.4.
5. **RF fans (Bond):** four URA-configured fans (Media, Game Room, Guest Bedroom 1, Master Bedroom) plus two unconfigured Bond ceiling fans (patio) and the Bond-platform twins of each. Nothing in URA reads `assumed_state` (grep: zero hits).
6. **Adjacency verdicts** (section 7): (a) left-on-fan failsafe gap = NEW; (b) stuck sensor -> fan recheck = ADJACENT (largely a duplicate of the recheck's own arm conditions); (c) RF fan state = NEW. All three fold into `MEDIAROOM-FAN-LEFT-ON-STUCK-SENSORS-1`.

---

## 1. Media Room config (read-only, `.storage/core.config_entries` over `ssh ha`)

Entry `01KNDX9D1TQKW5ZAG7M0GD8H2Q`, title "Media room", room_name "Media", `room_type media_room`, zone "Upstairs", `climate_entity climate.up_hallway_zone_2`. Merged = `{**data, **options}`; **options win**.

| Item | Value | Source |
|---|---|---|
| Fans (options) | `fan.media_room_ceiling_fan_2` (data still lists nothing; the old `fan.media_room_ceiling_fan` is not configured) | options.fans; `control_fans` attr on `binary_sensor.media_room_occupied` |
| Fan Mode | **`off`** (`room_fan_mode`), `select.media_room_media_room_fan_mode` = off since at least 2026-11-08 08:24 CST | options; recorder |
| Recheck | `room_fan_recheck_enabled: true`, `fan_recheck_l2_allowed: true`, `fan_recheck_trust_sensors_ok: true` | options |
| Presence (radar) | `presence_sensors`: Matter `binary_sensor.mmwave_motion_lux_matter_wifi_mediaroom_occupancy` | options |
| Motion | `motion_sensors`: meross_lan `binary_sensor.mmwave_motion_lux_meross_wifi_mediaroom_sensor_presence_motion` (radar-derived bit, SENSOR_FLEET_CLASSES "Meross MS600") | options |
| `occupancy_sensors` | none | options |
| Lights | none; `manual_switches`: dimmer + two Shelly relays (not the fan) | data |
| Shared space | `shared_space: true`, auto-off 23:00 | options |
| Automation switch | `switch.media_automation` = **off** in every recorder row 2026-11-08 08:24 CST -> now (26 rows, all `off`, one per restart) | recorder; restore: `switch.py:5484-5501` (AutomationSwitch restores last state) |
| Override switches | both off | live state |

Registry resolution (not names): Matter entity -> platform `matter`, device "Smart Presence Sensor" (Meross); Meross bit -> platform `meross_lan`, device id `889291c7...` model `ms600-un`; fan -> platform `homekit_controller`, config entry "Bond Bridge", device Olibra "Ceiling Fan (RCF94v2)". Its twin `fan.media_room_ceiling_fan` is platform `bond` (config entry "Madrone Bridge Pro"), same physical fan, **not** configured in any URA room.

Context: 20 of 47 room Automation switches read `off` for the whole window (sibling rooms: Kitchen, Master Bedroom, Jaya Bedroom, Guest Bedroom 1 and 2, Foyer, Patio, Study B, Exercise Room, Ziri Bedroom...). The activity log shows no `occupancy_entry` rows in 72 h for those rooms (paused rooms skip the activity write, `coordinator.py:5624`), so "off" is the effective state, not a display artefact. Whether this is deliberate is **unknown** (switches restore across restarts, `switch.py:5494-5501`; no history older than 2026-11-08).

---

## 2. Timeline (CST). Sources: HA recorder `/config/home-assistant_v2.db` (read-only), URA DB `memory_episodes` / `ura_activity_log` / `notification_log` / `house_state_log` (read-only)

Scripts: `/Users/okosisi/Code/universal-room-automation/.claude/tmp/mr*_probe.py`, run via `ssh ha "python3 -" < script`.

| Time | Event | Evidence |
|---|---|---|
| 11-13 12:38-12:59 | Last ordinary Media use: Matter on 12:38:31, off 12:40:00; again 12:51:02-12:53:24; room occupied off 12:58:33. Meross bit flaps while a person is present | recorder |
| 11-13 12:59 -> 11-14 19:05 | **30 h with zero radar edges** (restarts aside); fan state `off` | recorder |
| 11-14 19:05:28 | Room occupied (Matter on). Jaya BLE in room (`ble_persons`) 19:07-21:05 | `binary_sensor.media_room_occupied` attrs |
| 11-14 19:11:54 / 19:19:44 | Matter off twice (two short gaps) | recorder |
| **11-14 19:40:42** | **Matter on for the last time. Stays on 18 h 12 m 28 s, to 13:53:10 next day.** Meross bit flaps from here: 1,435 edges in 18.2 h, longest quiet gap 10.5 min (single sensors on a still person normally drop in 30-70 s, SENSOR_FLEET_CLASSES) | recorder |
| 11-14 19:44:16 | Meross chatter NM "WOULD quarantine sensor (shadow)", MEDIUM, channel `digest` | `notification_log` id 27272-27273 |
| 11-14 21:05 | Last BLE-confirmed person in Media until 02:13 (Oji, 3 rows) and 10:17-10:51 (Jaya) | attrs |
| 11-14 22:02:20 | HA restart. House `home_night` 22:08, `sleep` 22:10 | recorder; `house_state_log` |
| **11-14 23:41:08** | P22 continuous-stuck: Matter excluded after 4.0 h, NM "excluded from occupancy (stuck-sensor rule)", MEDIUM, `digest`. A second NM at 00:00:04 ("4.3 h") | `anomaly_log` 352219-352220; `notification_log` 27326, 27328 |
| 11-14 23:41 -> 11-15 13:58 | After exclusion `occupancy_source` is only `motion` / `timeout` (alternating ~50/50 per hour), never `mmwave`: the Meross bit alone holds the room | `binary_sensor.media_room_occupied` attr history |
| 11-15 05:42:21 | Second chatter shadow NM | `notification_log` 27384 |
| 11-15 06:00 / 06:01 | House `waking` / `home_day` (so the sleep veto ends at 06:01) | `house_state_log` |
| 11-15 10:17-10:51 | Jaya in Media (BLE), a real visit | attrs |
| 11-15 13:41:55 / 13:42:34 / 13:42:40 | Ezinne, Oji, Jaya `not_home` | recorder `person.*` |
| **11-15 13:43:29** | **House AWAY** (`census_update`; episode 18811 `away_transition_blocked` closed `unblocked`). Path alpha requires unidentified 0 and face 0, so the house was empty by the engine's own test | `house_state_log`; STATE_OF_PLAY section 2 |
| 11-15 13:43 -> 13:53 | Room still held; Meross still flapping; no fan action of any kind | recorder |
| **13:51:39 / 13:51:40** | `fan.media_room_ceiling_fan_2` on then off, 1 s apart, context user `66bda3b7...` (an HA user, no automation parent). The Bond twin mirrors it within 0.2 s | recorder |
| **13:53:10 / 13:53:11** | **Matter off, Meross off (90 s after the fan command).** Compare `phantom_retro` release delays in rooms where HA saw the fan: 40-53 s | recorder; `memory_episodes` 17377 etc. |
| 13:58:33 | Room vacated (5 min occupancy timeout) | recorder; `occupancy_events` exit |
| 14:19 | HA restart; all five entities read off | recorder |

Producer/consumer notes for the table: `occupancy_source` is produced at `coordinator.py` per tick (label of the CONF list, STATE_OF_PLAY section 10 item 10); consumers are dashboard, DB trigger and activity log only. `ble_persons` is produced by the BLE block (STATE_OF_PLAY 4.6).

Episode-type check for node `room:media`, 9 days (2026-11-06 -> 11-15), `memory_episodes`: `fan_recheck_outcome` **0**, `phantom_retro` **0**, `occupancy_phantom` **0**, `actuation_conflict` **0**, `away_transition_blocked` is house-level (45 in 7 d, none about Media). Anomaly log: `stuck_signal` rows only (`continuous` x2, `chatter` x2). The recorder retains 7.5 days (oldest row 2026-11-08 04:12 CST).

---

## 3. Fan truth: HA saw this fan ON exactly once in 7.5 days

`fan.media_room_ceiling_fan_2` recorder history 11-08 -> now: `off` (11-08 08:24), `on` 11-15 13:51:39, `off` 13:51:40. Bond twin: same plus an `unavailable` 28 s flap 11-14 12:49. The room was visibly in use on 11-13 and 11-14 (radar episodes, Jaya BLE). HA recorded no fan ON.

Why (registry + source, not names):
- Platform `bond` entity: `assumed_state: true` live. HA core `bond/entity.py`: `self._attr_assumed_state = self._hub.is_bridge and not self._device.trust_state` (raw source fetched 2026-11-15). So HA treats a Bond-bridge device without trust state as assumed.
- Bond community (not vendor-confirmed): the bridge cannot see physical RF remote presses, so its tracked state drifts (https://forum.bondhome.io/t/trust-tracked-state/3138: "Bond does not know when you click an RF remote"). HA's own Bond page says the integration "Duplicates your RF remote control" and offers actions that set the state HA holds.
- The URA-configured entity is the HomeKit twin `fan.media_room_ceiling_fan_2` (platform `homekit_controller`), which carries **no** `assumed_state` attribute (live attributes), so the "assumed" flag does not even reach the entity URA reads. URA reads `assumed_state` nowhere (`grep -rn assumed_state custom_components/...` = 0 hits).

Unknown: the physical state of the fan now (HA cannot see it); who turned it on and when (inference only: radar flapping began at 19:40:42 on 11-14, see section 6); whether Bond's `turn_off` is a true off or a toggle for this remote (forum reports toggle-only remotes misbehave; not verifiable from HA; bench test needed before any blind-off design).

---

## 4. Part 1: every failsafe that should turn off a fan in an empty room or AWAY house, and why it did not (v5.108.24 line numbers)

| # | Failsafe | What it does | Why it did not act for Media | Cite |
|---|---|---|---|---|
| 1 | **Room vacancy exit action** | `_handle_exit`: lights, auto switches, manual switches, covers. **Never touches fans** | (a) never ran for fans by design; (b) the room never vacated until 13:58:33; (c) room paused: the whole occupancy-change block sits under `elif self._is_automation_enabled()` and `switch.media_automation` is off | `automation.py:1432-1445`; `coordinator.py:5624`, `:3522-3530`; activity log has no Media `occupancy_entry`/`exit` rows |
| 2 | **Fan recheck** (pause, re-measure, drop occupancy) | arms on occupied + radar-sole N ticks + a fan ON | Vetoed four ways, in code order: `fan_control_off` (Fan Mode off -> `fan_owner` None), `room_paused`, `sleep_state` (media_room refused across `home_night`/`sleep`/`waking` = 22:08-06:01 CST), `no_fan_on` (HA state off). Live veto counters not readable: the `fan_recheck_state` sensor entity is disabled by integration. Zero episodes in 9 d | `presence_fan_recheck.py:550-551`, `:555-556`, `:575-579`, `:635-636`; `const.py:1453-1464`; `hvac_const.py:1104` (`FAN_TRUST_STATES`) |
| 3 | **D2 sustain demotion** (mmwave-fan demotion) | demotes a radar-sole hold when a fan-immune PIR witness has gone stale | `_d2_motion_sensors_present()` False: Media's only motion sensor is the MS600 radar bit, excluded as a witness (device `model ms600-un`, family unknown, falls to the `mmwave` name pattern; see side finding S1). Fails closed. Also the room's fan reads off (`fan_on: false`, `fan_interference_suspect: false`) | `coordinator.py:2254-2286`; `fan_veto.py:113-128`; STATE_OF_PLAY section 6 item 2 |
| 4 | **P24 max-occupancy failsafe (4 h)** | force-vacates a PIR-corroborated room after 4 h of stale PIR | Exempt: requires `_d2_motion_sensors_present()` (same witness test). Would also be deferred: freshness gate reads `_last_motion_bit_time`, refreshed on every `motion_detected` tick (the flapping Meross bit) | `coordinator.py:5075`, `:5006-5120`, `:4329`; `const.py:1925` (4 h default) |
| 5 | **Fan layer** (FanPolicyOracle) | arbitrates URA-issued fan writes (manual-ON hold, cooldown); no timers, no autonomous sweep | Not an actuator; nothing consulted it because no URA write was attempted | `fan_policy_oracle.py:1-60` |
| 6 | **AWAY leave-on sweep** | on house -> AWAY edge, turn off `lights_leave_on_when_empty` lights | Lights only. Media has none configured, and the room is paused | `coordinator.py:979-1033`; `automation.py:860-925` (docstring: "turn off ONLY leave-on lights") |
| 7 | **Comfort-fan AWAY veto** | blocks comfort-fan turn-ON in AWAY | ON paths only; "never from turn_off" | `fan_veto.py:496-507`; `hvac_fans.py` update loop gates `should_on and not room_fan.is_on` |
| 8 | **HVAC zone-vacancy sweep** (row-1 / D6 callers) | when a zone empties, turn off lights, manual devices and Follow-thermostat fans | Four gates, any one sufficient: zone must be empty (`zone.any_room_occupied` False; Media held Upstairs until 13:58:33); room skipped when paused; fans only if Fan Mode = Follow thermostat (`hvac_tier_owns_room_fans`); and only fans whose HA state is `on` | `hvac.py:6762-6783`, `:6827-6833`, `:6944`, `:7019`; `hvac_fans.py:89-130` |
| 9 | **Shared-space night failsafe** (23:00, vacant rooms only) | turns off a vacant shared room's lights/fans | Room was occupied at 23:00 so the tick returned; and fans are left alone when Fan Mode is Off. Activity log: Media fired it on 11-13 and 11-14 (05:00Z), **not** on 11-15; only "Media Room Closet" did | `automation.py:4518-4553` (occupied return `:4542`), `:4721-4727` |
| 10 | **ActuatorReconciler fan resolver** | re-asserts fan state on reconcile edges | `fan_owner` None -> returns None; and it only asserts ON/OFF for HA-believed state | `actuator_reconciler.py:1001-1030` |
| 11 | **Stuck-signal watchdog** | P22 continuous (4 h) exclusion + NM; D2 duty-cycle (notify, promotion needs a disagreeing corroborator); chatter (shadow) | Acted, but only on sensor trust, never on the fan: Matter excluded 23:41, Meross (a motion sensor, never a duty-cycle candidate and a corroborator) kept the room; chatter detector "WOULD quarantine" only. NMs went to the `digest` channel, MEDIUM | `coordinator.py:3663-3681`, `:401`, `:2375`, `:1953-1975`, `:2862`, `:3022`, `:3220`; `select.py:978`; `notification_log` ids above |
| 12 | **Away-block / zone-hold trip-wire** (`zone_hold_all_away`) | pages when the house is **held out of AWAY** by Tier-1 sensors for 2 h | Not applicable: the house went AWAY at 13:43:29 normally (path alpha ignores room occupancy). No trip-wire exists for "house AWAY but a room still held" | `presence.py:4478-4570`; `const.py:855` |

Answers to the brief's questions: the stuck input **did** hold the room occupied (Meross after Matter was excluded); recheck **vetoed** (config, pause, sleep, fan state); the fan state was **unreported** (never ON in HA); **AWAY was not blocked** (it fired at 13:43:29) but has no fan action; the fan was **manual in effect** (Fan Mode Off = person-owned, FAN-MANUAL-1 semantics: URA writes nothing).

Fire check, 14 d, `notification_log` `coordinator_id=stuck_signal`, non-audit rows: **64** (chatter 45 of which 43 are Garage A/B and Master Bathroom, dutycycle 11, continuous 4: Media x2, GB1, GB2, other 4). Media specifically: 4 rows, all inside this incident. None of the 64 reaches a fan action (`presence_fan_recheck.py` contains no reference to stuck / exclusion / chatter; the only reader of the per-sensor stuck map outside the room is `sensor.ura_stuck_signal_watchdog`, `sensor.py:5728`).

---

## 5. Part 2: the operator's suggestion, as producer and consumer checks

Operator, verbatim: "what if we used stuck sensors as a way to trigger fan recheck? Stuck sensors are often because of fans. So if we see stuck sensors we can quiet fans."

### 5.1 Producer check: what "stuck" is today, and what it emits

| Producer | Condition | Emits | Fan connection |
|---|---|---|---|
| P22 continuous | sensor on >= 4.0 h (`_stuck_sensor_hours`, hard-coded literal, `coordinator.py:401`), after boot settle and a post-restart live-ON | exclusion (`p22_continuous` client) + MEDIUM NM | none |
| D2 duty-cycle | on-ratio over window, no corroborator transitions; **motion sensors are never candidates** | notify-only; promoted to exclusion only if a corroborator disagrees >= 900 s and the house is not SLEEP/WAKING/HOME_NIGHT (STUCK-SENSOR-1 plan INV-STUCK-1/2) | none |
| Chatter | burst of sub-floor impossibility events | `WOULD quarantine` NM in default shadow mode | none |
| Camera stream health | camera entity unavailable | exclusion + hold rules (S1/S2) | recheck does not honour room exclusions (STATE_OF_PLAY S1 entry) |

Consumers: room fusion (exclusion set), `sensor.ura_stuck_signal_watchdog`, notification digest. **Nothing connects a stuck or frozen occupancy input to the fan recheck or any fan writer** (grep of `presence_fan_recheck.py`: 0 hits for stuck / exclusion / chatter; the recheck reads `room_coord.data["occupied"]` and the radar-sole ring, `presence_fan_recheck.py:581`, `:606-617`).

The parked D6 in `PLANNING_mmwave_corroboration_tier3.md` (section "D6: (PARKED)", lines 306-308 and 505-524) is "dead/stuck mmwave in the stuck-signal watchdog" (alerting), evidence trigger **fired** 2026-08-09, then absorbed into the chatter/reliability work. It is observability, not a fan trigger. STUCK-SENSOR-1 (card: `parked`, BLOCKED on SENSOR-CAPABILITY-1) is stale: its plan shipped (v5.75.0 per `coordinator.py` comments; `_promote_dutycycle_to_exclusion` at `:3220`).

### 5.2 Is "stuck while a fan runs" evidence the fan is the cause?

Partly, and only for radar-class sensors.
- **For:** recorder + memory: `phantom_retro` rows (fan-release correlated) 9 d: Jaya Bedroom x5 (holds 403 s to 46,793 s), Ziri x2, Master Bedroom x1 (67,230 s), Living Room x1; release delays 38-53 s after fan OFF every time (`memory_episodes`, e.g. 17377, 17388, 17910, 18646, 18805). SENSOR_FLEET_CLASSES: ZK/ZX fan-susceptible (measured), LD2410 68% false presence with fan on (ledger item 1), MS600 radar bit is "not a fan-immune witness".
- **Against:** stuck is multi-cause. The same 64 NMs are mostly non-fan: Garage A/B ratgdo chatter, Master Bathroom, cameras (CAMERA-STUCK-*, FRONT-SIDE-PTZ-CHATTER-1), frozen Zigbee `on` (STUCK-MOTION-FROZEN-ON-BLINDSPOT-1 was refuted into a Jaya radar+fan case). Fans also run mostly **because** the room is occupied (comfort logic), so "stuck + fan on" is the baseline for any long real stay and a sleeping person looks exactly like a stuck radar (D2 doc: "a sleeping person is ~100% mmWave duty cycle"). SENSOR-FANINDEP-1: motion-class corroborators are valid for stuck, **not** for fan demotion.
- **Discriminator that exists:** pause the fan and see if the radar clears (what the recheck does). A stuck flag only adds "this has lasted long enough", which the recheck's own N-tick radar-sole + fan-on precondition already approximates.

### 5.3 What "quiet the fan" would do, and risks

The recheck pauses (turns off) a fan, waits `window` (60 s base x media-room 2 x family factor; MS600 generic radar 1.5 -> ~180 s; `const.py:916`, `sensor_capability.py:408-415`), then: VACATED = leave the fan off and drop occupancy (`leave_off=True`, Rev 2 C1a); OCCUPIED_CONFIRMED = restore the fan ON. Cooldown 900 s, max 2 per hour (`const.py:921`, `:932`).
Risks of a stuck-triggered version:
1. **Turning off a fan someone is using.** Recorded operator rulings: a probe must not turn off a person's fan (HVAC doc 4.2b, review B-M1 2026-10-19; bedroom and media rooms refused across sleep, `presence_fan_recheck.py:575-579`). A 4 h-stuck radar with a running fan is also the shape of a sleeper or a movie watcher.
2. **Restore ON for a fan of unknown state.** If the pause targets an unobservable fan, the snapshot is "off" (HA belief), so the OCCUPIED_CONFIRMED restore would be a no-op, and a naive snapshot of "on" would turn on a fan that was off. The restore branch must never run for assumed-state fans.
3. **Bond command semantics unknown.** If the remote is toggle-only, a blind `turn_off` might toggle ON (not verifiable from HA; bench test on the Media fan needed).
4. **Wrong attribution.** A hardware-stuck radar does not clear on fan-off; the verdict is OCCUPIED_CONFIRMED and the room stays held (the recheck handles this correctly: it only drops occupancy on a real clear).
5. **Rare-fire path:** the 7-day recheck fire rate is 15 outcomes in 2 rooms (section 6.2); a new trigger path would be organically unobservable (marginal-benefit rule).

### 5.4 Marginal-benefit decomposition (simplest version first)

- The large component of the Media incident is not "recheck missed a radar-sole hold"; it is **"nobody is home, a room is held, and URA has no action and no page"**. The simplest capture is a **code trip-wire**: house AWAY (or no BLE/camera person) for N minutes while a room is still held by radar-only sources -> HIGH stuck-signal NM naming the room and its fans (including "fan state unreliable: assumed"). No actuation, no new writer, reuses `fire_stuck_signal`. Gap confirmed: `zone_hold_all_away` only fires when the house is held **out of** AWAY (`presence.py:4478-4570`).
- Next rung, needs an operator ruling: an AWAY-time **blind OFF** to fans whose state is untrusted (assumed / Bond), regardless of HA state. Zero-regret physically (house empty) but contradicts "Fan Mode Off = URA writes nothing". Operator rule needed before it is specced.
- The stuck-triggered recheck is the **most complex** variant: new trigger into a shared 5-state machine with sleep/HVAC handshakes, for the same fan-visibility gap. Margin does not pay until the simpler two exist. Park with a trigger: "stuck-triggered recheck revisited if a radar-held empty room with a fan-state-visible fan recurs where the recheck's own preconditions were met but unarmed".
- Config-first (CLAUDE.md Config-First): for rooms where the fan state IS visible, the fix is a setting (Fan Mode not Off, Automation on); JAYA-FAN-STILL-PHANTOM-1 was resolved exactly that way. That does not fix Media because of fan visibility (section 3).

---

## 6. Fire check, and the RF fan list

### 6.1 Falsifier checks run (observations that would have disproved the conclusions)

| Conclusion | Disproving observation sought | Result |
|---|---|---|
| HA never saw the fan on | any `on` row for `fan.media_room_ceiling_fan_2` before 13:51:39 | none in 7.5 d |
| Room paused | `switch.media_automation` reading `on`, or Media `occupancy_entry` rows | none; 26/26 rows `off`; 0 activity rows in 72 h |
| Recheck never armed for Media | any `fan_recheck_*` episode for `room:media` | none in 9 d (298 rows all-time since 2026-10-12, none Media) |
| The holds were not human | BLE persons in room after 21:05 other than 02:13 (Oji) / 10:17-10:51 (Jaya); a person at home at 13:43-13:53 | none beyond those; all residents `not_home` by 13:42:40; AWAY (alpha) at 13:43:29 |
| Fan was the driver | sensors clearing without the fan command, or re-asserting after | cleared 90 s after the command, stayed off through 14:19 restart. **Residual doubt:** n=1 on the clearing edge; radar flapping alone does not discriminate (a real person gives ~100 edges/h too). The discriminators are "no one there" + clear-after-command, not edge rate |
| MS600 radar bit as witness | Meross counted as fan-immune | excluded (via name fallback only, see S1) |

### 6.2 Recheck fire check, 7 days (2026-11-08 14:07 -> 11-15 14:07 CST)

`memory_episodes` `fan_recheck_outcome`: 21 rows = **15 outcomes + 6 five-minute follow-up rows**. Rooms: Study A 7, Living Room 8, **all others 0** (incl. Game Room, Media). Verdicts: aborted `ble_l1` 4, aborted `arm_expired_ineligible` 4, aborted `motion` 1, occupied_confirmed `pause_window_complete` 2, occupied_confirmed `cancel_driven` 2, **vacated 2** (both Study A; `fan_restored: false`). Activity log last 62 h: `fan_recheck_arm` 14, `cancel` 10, `outcome` 6. `occupancy_phantom` 4 (Living Room x2, Guest Bedroom 2 x2); `phantom_retro` 6 (Jaya x4, Living Room, Ziri).

**Recheck eligibility cohort (config + switch state read live):**

| Room | Fan (platform) | Fan Mode | Automation | Recheck rows 7 d |
|---|---|---|---|---|
| Study A | Dreo | follow | on | 7 |
| Living Room | Dreo | follow | on | 8 |
| Game Room | Bond via HomeKit | follow | on | 0 |
| Kitchen | Midea | follow | **off** | 0 |
| Master Bedroom | Bond (B2) + Dreo | follow | **off** | 0 |
| Jaya Bedroom | Tuya | room_temperature | **off** | 0 (phantom_retro x4, holds up to 13 h) |
| Guest Bedroom 1 | Bond via HomeKit | room_temperature | **off** | 0 |
| Media | Bond via HomeKit | **off** | **off** | 0 |
| Guest Bedroom 2 | Tuya | **off** | **off** | 0 (occupancy_phantom x2) |
| Ziri Bedroom | Tuya | **off** | **off** | 0 |
| Exercise Room | Tuya (entity unavailable) | **off** | **off** | 0 |
| Breakfast Nook | Midea (shared with Kitchen) | **off** | on | 0 |

Only **3 of 12** fan rooms can arm the recheck at all (Study A, Living Room, Game Room); outcomes come from 2. The JAYA-FAN-STILL-PHANTOM-1 revival trigger ("Upstairs held occupied by a Jaya fan-on, radar-only episode with no `fan_recheck_outcome` row for Jaya") looks fired: Jaya Bedroom has 5 `phantom_retro` episodes (11-07, 11-09, 11-11, 11-15 x2) and is a paused room. Not verified: whether Upstairs HVAC zone_2 was held during them.

### 6.3 RF / one-way fans (registry + integration, not names)

| Fan entity | Platform / config entry | Device | `assumed_state` | URA room | Fan Mode | HA ON events 7 d |
|---|---|---|---|---|---|---|
| `fan.media_room_ceiling_fan_2` | homekit_controller / Bond Bridge | Olibra RCF94v2 | **absent** (HomeKit) | Media | off | 1 (1 s blip) |
| `fan.game_room_ceiling_fan_2` | homekit_controller / Bond Bridge | Olibra RCF94v2 | absent | Game Room | follow | 6 (5.7 h) |
| `fan.guest_room_down_ceiling_fan_2` | homekit_controller / Bond Bridge | Olibra RCF94v2 | absent | Guest Bedroom 1 | room_temperature | 0 |
| `fan.master_ceiling_fan_2` | homekit_controller / Bond Bridge | Olibra B2 | absent | Master Bedroom | follow | 1 (10.8 h) |
| Bond-platform twins: `fan.media_room_ceiling_fan`, `fan.game_room_ceiling_fan`, `fan.guest_room_down_ceiling_fan`, `fan.ceilingfan_fanimaton_rf_masterbedroom` | bond / "Madrone Bridge Pro" | same devices | **true** | none | n/a | same counts |
| `fan.patio_ceiling_fan_1` / `fan.patio_ceikkng_fan_1`, `fan.patio_ceiling_fan_2_2` / `fan.patio_ceiling_fan_2` | homekit_controller + bond | Olibra RCF94v2 | mixed | none | n/a | 0 |

Not RF/assumed: Dreo (cloud), Tuya (cloud/local relay, report real switch state), Midea LAN, Shelly/Sonoff `switch_as_x` (relay state is real), Hubspace `fan.ceiling_fan_fan` (unconfigured, unavailable). Whether each Bond fan's remote is RF or IR is not provable from HA; the operator calls them RF, the master entity is literally named `..._rf_masterbedroom`, and `PLANNING_fan_noise_running_rejection.md:19` already calls the Master Bedroom fan an "RF fan" needing a physical fix.

How state is consumed, and what breaks when it lies:

| Consumer | Reads | If HA shows OFF but fan runs (the Media case) | If HA shows ON but fan is off |
|---|---|---|---|
| Recheck eligibility / arm-delay twin | `hass.states` `== "on"` (`presence_fan_recheck.py:635`, `:1272`, `:1337`) | `no_fan_on` veto: never arms | would arm and pause a fan that is not running |
| Presence fan listener, `_fan_known_good`, `_fan_on_since` (`presence.py:4136`, `:1821`, `:4083-4108`) | transitions | no `fan_interference` gate, no `occupancy_phantom` | spurious fan-on window (bounded by recheck cooldown) |
| `phantom_retro` writer | fan-off edge after a >= 300 s hold, release within 60 s (`const.py:6292-6296`) | silent (also would miss MS600's 90 s release even with a correct hold) | n/a |
| HVAC zone sweep, room fan oracle snapshots | `state.state == "on"` (`hvac.py:7019`, `:6995-7010`) | skips the fan | would command OFF (harmless) |
| Room-tier external-change detection, FAN-MANUAL-1 hold | ON/OFF edges (`automation.py` any_fan_on_now, FIX C cooldown) | a person's remote ON is never booked, no manual-ON hold | n/a |
| Comfort controllers (Follow / Room temperature rooms) | their own belief + HA state | may send ON to a running fan (idempotent) | will not re-send ON: fan stays physically off |

Only the first column is demonstrated (Media). The second column is reasoning from the code above; no instance measured.

---

## 7. Part 3: adjacency sweep

Surfaces read: `docs/planning/kanban.data.yaml` (722 cards + parked, all listed cards read), `docs/BACKLOG.md` (fan/stuck/bond/assumed greps), `docs/planning/PLANNING_*` / `AUDIT_*` (grep for fan/stuck/bond/assumed/forgotten, plus full reads of the named plans' relevant sections), memory episodes, code greps cited above.

| Card | Status (board) | Relation |
|---|---|---|
| `MEDIAROOM-FAN-LEFT-ON-STUCK-SENSORS-1` | investigating, tier 2 | the home for all three verdicts |
| `STUCK-SENSOR-1` | parked, BLOCKED on SENSOR-CAPABILITY-1 (card text stale: plan rev 2, shipped v5.75.0, `_promote_dutycycle_to_exclusion` live) | stuck -> **exclusion**; never -> fans. ADJACENT to (b) |
| `FAN-RECHECK-NOT-CLEARING-1` | done | recheck eligibility investigation; same "fan_control_off veto" class as Media |
| `FAN-RECHECK-SLEEP-VETO-SCOPE-1` | parked (stale: sleep-scoped veto is live, `presence_fan_recheck.py:575-579`, JAYA-FAN-STILL-PHANTOM-1 scope) | explains Media's night veto |
| `FAN-RECHECK-OBSERVABILITY-1` | done | veto counters exist, but `sensor.media_room_media_room_fan_recheck_state` is disabled by integration, so Media's veto reason is derived, not read |
| `FAN-RECHECK-D2-DEADLOCK-1` | parked | starve-vs-demote seam; Media is the fail-closed D2 variant |
| `FAN-MANUAL-1` | done | defines "person-owned" fan semantics; hold is time-bounded, not a left-on failsafe |
| `FAN-LAYER-1` / `FAN-LAYER-2` | done / parked | arbitration of URA writes; no sweep, no state-trust concept |
| `SENSOR-FANINDEP-1` | done | motion-class valid for stuck, not for fan demotion (limits (b)) |
| `FAN-PHANTOM-RETRO-EPISODES-1` | done | phantom_retro rate; writer blind to Media (hold < 300 s, release > 60 s) |
| `STUCK-MOTION-FROZEN-ON-BLINDSPOT-1` | done (refuted into a fan case) | "stuck PIR" turned out to be fan-held radar |
| `OC-STUCK-SENSOR-GENERALIZE-1` | done | optimizer finding for sensors that stop firing; different direction |
| `FAN-TRANSITION-COINCIDENCE-GATE-1`, `FAN-TRANSITION-GATE-FOLLOWS-CAPABILITY-1` | done / parked | onset gate (retired to 0.0); irrelevant when fan ON is never seen |
| `JAYA-FAN-STILL-PHANTOM-1` | parked, revival trigger appears fired | same veto class (fan_control_off / paused); fix there was config |
| `ROOM-OVERRIDE-SWITCH-FORGOTTEN-1` | done | paused/override-forgotten pattern; 20 rooms read Automation off |
| `BOND-BRIDGE-UNRESPONSIVE-1` | done 10-14 | Bond availability flaps only; not state truth |
| `D2-PIR-STAMP-FOLLOWS-FAN-IMMUNE-WITNESS-1`, `OCCUPANCY-SOURCE-FOLLOWS-CAPABILITY-1` | parked | radar-bit/MS600 fan-immunity (context for fail-closed D2 in Media) |
| `GUEST-ROOM-FAN-HOLD-1`, `AWAY-BLOCK-1` | parked / done | fan-self-sustain loops; AWAY-BLOCK-1 is the "held out of AWAY" side (zone_hold_all_away), not the "left on after AWAY" side |

**Verdicts**

- **(a) Left-on-fan failsafe gap: NEW.** No code or card covers "fan left running in an empty/AWAY house with a held room": no AWAY fan-off (`automation.py:860-925` lights only, `fan_veto.py:496-507` ON only), no comfort-fan max-runtime (only humidity fans, `const.py:1731`), no "room held while AWAY" trip-wire. Closest: FAN-MANUAL-1 (bounded hold), HVAC zone sweep (state- and mode-gated), ROOM-OVERRIDE-SWITCH-FORGOTTEN-1 (reminder pattern). **Folds into `MEDIAROOM-FAN-LEFT-ON-STUCK-SENSORS-1` as its primary deliverable (AWAY-while-held trip-wire first).**
- **(b) Stuck sensor -> fan recheck: ADJACENT, largely DUPLICATE of the recheck's own arm conditions.** The only new element is "stuck as an inference of fan presence when fan state is unobservable". Fold into the same card as a **parked design option** with the section 5.4 trigger; relate to STUCK-SENSOR-1 and FAN-RECHECK-D2-DEADLOCK-1.
- **(c) RF fan state: NEW.** No consumer of `assumed_state`; no state-trust class; BOND-BRIDGE-UNRESPONSIVE-1 covers availability only. Fold into the same card as the second deliverable (fan-state trust class: assumed-state fans are "unknown" to recheck, sweep, phantom writers), reusing the held-belief pattern (`presence.py:1821` `_fan_known_good`) and ActuatorReconciler flap quarantine; FAN-LAYER-2 is the state-in-one-place neighbour.
- Secondary (not minted here): the paused/Fan-Mode-Off cohort (section 6.2) is a config-first question for the operator ("is Media's Automation off intentional? is Fan Mode Off intended for a media-room fan?") plus the Jaya revival trigger; both fit under the same card's step 1.

---

## 8. Side findings (not part of the verdicts)

- **S1 MS600 model string vs the safety net.** The Meross entity's device record has `model ms600-un` (sw 9.4.37); a second device record with the **same meross_lan identifier** carries `ms600 9.0.0` (sw 9.4.34). `FAMILY_BY_MODEL_ID` has the exact `"ms600 9.0.0"` key and `FAMILY_BY_MODEL_TOKEN` matches the first whitespace token `ms600`, so `ms600-un` resolves **unknown** (`sensor_capability.py:395-430`, `fan_veto.py:80-128`). The radar bit is still kept out of the witness list only by the `MMWAVE_NAME_PATTERN` fallback on the entity_id (`fan_veto.py:125-127`), which is a name guess; a rename would make the fan-faked bit a "fan-immune witness". Registry-not-names residual; related to SENSOR_FLEET_CLASSES MS600 section and REGISTRY-NOT-NAMES-1.
- **S2 Chatter NM text** blames hardware ("Replace sensor... chatter pattern indicates hardware fault", `notification_log` 27272) for what the evidence shows was fan-driven; shadow mode means nobody was paged beyond the digest.
- **S3 Phantom-retro window** (`PHANTOM_RETRO_RELEASE_WINDOW_S = 60`, `const.py:6292`) is shorter than the MS600 clear delay observed here (90 s); even with a correct fan hold it would not have written an episode.
- **S4 `occupancy_events` exit row** for this stay reads `duration 322` (`occupancy_events` id 2318619) for an ~18.9 h occupancy; not investigated.
- **S5 Meross unavailable blip on every HA restart** (5 restarts in 48 h) resets nothing relevant here but each restart replays the stuck-state Store (`_async_load_stuck_state`); the 4.0 h exclusion at 23:41 CST matches the 19:40:42 onset exactly, so the persisted clock held across the 22:02 restart.

## 9. Not done / unknown

- Physical fan state, who started it, when; whether the Bond fans' remotes are RF or IR; Bond `trust_state` for these devices; how often the household uses the remote (not measurable from HA).
- Cost of the 18 h hold (Upstairs HVAC zone_2 held? lights none; energy): not measured. The room-level HVAC occupancy ran through the whole window (`binary_sensor.media_room_media_room_hvac_occupied` on 22:03 -> after 13:58).
- Live recheck veto counters: sensor disabled by integration; vetoes derived from code + config + state.
- Whether the 20 paused rooms are intentional.
- No HA service calls, no state changes, no Bermuda diagnostics. Token used from keychain only for GET `/api/states`.

## 10. Files

- This doc: `/Users/okosisi/Code/universal-room-automation/docs/planning/AUDIT_mediaroom_fan_left_on_stuck_sensors_2026_11_15.md`
- Probe scripts and raw outputs: `/Users/okosisi/Code/universal-room-automation/.claude/tmp/` (`mr*_probe.py`, `mrtl_out.txt`, `mrocc_out.txt`, `fanjoin_probe.py`, `bondfan_probe.py`, `stuckfire_probe.py`, `base_*.py` = v5.108.24 source snapshots used for line numbers)
- Sources fetched: https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/bond/entity.py ; https://www.home-assistant.io/integrations/bond/ ; https://forum.bondhome.io/t/trust-tracked-state/3138
