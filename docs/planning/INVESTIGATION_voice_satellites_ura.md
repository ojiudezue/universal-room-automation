# INVESTIGATION — Voice Satellites in URA

**Date:** 2026-07-11
**Status:** Investigation / vision — no build authorized
**Operator question (verbatim):** *"How can we use Voice Satellites in a practical and deeply valuable way in URA? And which coordinator should be extended to manage that?"*

---

## 0. Institutional context verified

Before proposing sensors / signals / coordinators, the following grep/reads were run against the URA codebase:

| Surface | Result |
|---|---|
| `custom_components/universal_room_automation/const.py` | No existing `assist_satellite` / `voice_satellite` / `wyoming` references. `TIER1_KINDS = ("motion", "mmwave", "occupancy")` at `const.py:342` — the substrate is currently a closed set. |
| `domain_coordinators/occupancy_substrate.py` | Substrate is per-room, per-kind, driven exclusively by `CONF_MOTION_SENSORS` / `CONF_MMWAVE_SENSORS` / `CONF_OCCUPANCY_SENSORS`. Kind is not extensible without touching `TIER1_KINDS`, `_KIND_PRECEDENCE`, `_KIND_TO_CONF`, and every consumer that iterates `TIER1_KINDS` (`binary_sensor.py:584`, `coordinator.py:1019` `_on_substrate_kind_changed`). |
| `domain_coordinators/presence.py` | Substrate consumer subscribes at `presence.py:2218`. No area/registry-sweep left for kind classification (v4.7.24 killed it). Adding a new kind requires touching the consumer, not adding sensors. |
| `domain_coordinators/notification_manager.py` | NM already has a `tts` channel (`_send_tts` at `notification_manager.py:1103`) that calls `tts.speak` against a flat `CONF_NM_TTS_SPEAKERS` list — **no room routing today**. Severity gating, quiet hours, dedup, safe-word ack, per-person delivery pref are all in place. |
| `music_following.py:1016-1035` | Room→media_player resolution exists via `room_media_player` config on each Room entry — this is the exact primitive an "announce to the room the person is IN" feature would reuse. |
| Person→room resolution | `PersonCoordinator` + zone person sensors already track `current_room` per person (see `sensor.py` `PersonCurrentRoom` family, well-established since v3.2.8.3). |
| Prior planning docs | No `PLANNING_voice_*` / `PLANNING_assist_*` / `PLANNING_satellite_*` exist. Voice is unbroken ground for URA. |
| HA docs verified (WebFetch) | `assist_satellite` domain, HA 2024.10+, states = `idle` / `listening` / `processing` / `responding`. Services: `assist_satellite.announce`, `ask_question`, `start_conversation`. Triggers: idle / started listening / started processing / started responding. Wake-word detection is **NOT exposed** as an entity state or attribute; only reachable via the `assist_satellite/intercept_wake_word` WebSocket API. Area/device_registry association is not documented; treat as **operator question** (needs live inspection of a real satellite in HA). |

**REUSED components** the investigation leans on:
- `room_media_player` per-room config (`music_following.py:1023`)
- NM `_send_tts` (`notification_manager.py:1103`) — will be extended, not replaced
- `PersonCoordinator` `current_room` per person
- `TIER1_KINDS` substrate mechanism (extension point for axis 1)

**NEW surfaces this doc contemplates:**
- `TIER1_KINDS` extension to add `"voice_activity"` — NEW (no equivalent kind exists)
- `CONF_NM_TTS_ROUTE_MODE` — NEW (no equivalent routing knob on the NM tts channel today)
- `assist_satellite_entities` per-room config field — NEW (analogous to `room_media_player` but distinct entity domain)

---

## 1. What voice satellites are in the HA world (2026)

Sourced from `developers.home-assistant.io/docs/core/entity/assist-satellite/` and `home-assistant.io/integrations/assist_satellite/`:

- The `assist_satellite` domain is a first-class HA entity domain since HA 2024.10. It generalizes over Wyoming Protocol satellites (ESP32-S3-BOX, Voice PE, DIY builds), the Home Assistant Voice Preview Edition hardware, and browser-based satellites.
- Each satellite entity has 4 canonical states: `idle`, `listening`, `processing`, `responding`.
- Services: `assist_satellite.announce` (message → speak), `assist_satellite.ask_question` (announce + await answer), `assist_satellite.start_conversation` (announce + open pipeline).
- Triggers fire on each state transition — automation-visible and dispatcher-friendly.
- **Wake-word detection does NOT surface as an entity state or attribute.** It is only interceptable via a WebSocket command (`assist_satellite/intercept_wake_word`). This is a material constraint for axis 1.
- Area/device_registry association: not called out in the developer docs. **Operator question:** we need a live inspection to confirm whether an `assist_satellite` entity carries `device_id` + `area_id` in the same way a Shelly relay does. Working assumption: yes (satellites are physical devices with a config entry), but this must be verified before the first cycle.

---

## 2. Value axes — ranked by operator value for this house

**Ranking rationale:** the house has 41 URA rooms, an already-mature presence-fusion substrate, a working NM stack with 6 channels, working room→media_player routing via MF, and an operator who has repeatedly emphasized "announce to the room the person is IN" as a gap (NM `_send_tts` today just fans out to a flat speaker list). Axis 2 is the highest-value first slice because it turns hardware you already need to buy anyway into a solved feature the very same day; axis 1 is high-value but constrained by the wake-word non-exposure; axis 3 is highest-ceiling but the highest-effort and lowest-marginal because HA Assist already answers "make it cooler" without URA involvement.

### Axis 2 (RANKED #1) — Voice as an output / announce surface for NM

**Deeply-valuable claim:** the single sentence *"announce the alarm to the room Oji is in, not to every speaker in the house at 2am"* is not achievable today without URA. HA has no cross-integration room-routing for TTS; NM's `_send_tts` fans out to a flat list; MF's `room_media_player` resolution is the exact primitive needed but is scoped to music transfers, not notifications.

**Deliverable sketch:**
- New NM tts route mode: `flat` (today's behavior — backward compat), `to_person` (resolve via `PersonCoordinator.current_room[target_person] → room_media_player OR assist_satellite entity in that room`), `to_occupied_rooms` (broadcast to every room with `_room_occupied=True`), `everywhere` (CRITICAL escalation — announce on all satellites + speakers).
- Severity → route mode escalation ladder:
  - INFO/LOW: `to_person` (or drop if unoccupied)
  - MEDIUM/HIGH: `to_occupied_rooms`
  - CRITICAL (safety — smoke, CO, flood, freeze, intrusion): `everywhere` **plus** the existing alert-lights + push channels
- Reuses existing NM per-person `CONF_NM_PERSON_ENTITY` to name the target of `to_person`.
- Reuses `room_media_player` for TTS-capable speakers; adds a new optional per-room `CONF_ROOM_ASSIST_SATELLITE` for satellite entities (satellites can announce via `assist_satellite.announce` which is more reliable than `tts.speak` on some hardware — particularly the Voice PE, which has its own audio pipeline).
- Ack path: `assist_satellite.ask_question` for CRITICAL — the alarm ANNOUNCES *and* awaits a spoken safe-word ack, eliminating the "did they hear it" ambiguity that today only the safe-word-via-text path resolves.

**Owner:** **NotificationManager** — this is a channel/routing feature, not a presence feature. Extending `_send_tts` in place preserves all the plumbing NM already owns (quiet hours, dedup, cooldown, severity gating, DB row, channel health).

**Effort tier:** **Tier 2 feature cycle** (2 reviews + live). ~200-350 LoC across `notification_manager.py`, `const.py`, `config_flow.py` / `options_flow.py`, `coordinator.py` (per-room `assist_satellite_entity` field). No DB schema change. No cross-coordinator ripple beyond MF (which owns `room_media_player` — read-only borrow, no writes).

### Axis 1 (RANKED #2) — Voice satellite as a presence sensor

**Deeply-valuable claim:** a satellite that just heard a wake word is definitionally occupied by a human. That is an unfakeable, seated-stillness-immune presence signal — the exact class the mmwave/fan-noise saga (`v4.7.19` / `v4.7.20` / `v4.7.22`) has been chasing for a year. Even without wake-word interception, `assist_satellite.state == listening` (or `responding`) is a hard occupancy signal that outranks any single mmwave frame.

**Deeply-valuable **caveat**:** the docs say wake-word detection is NOT exposed as state — only via the WebSocket intercept. The `listening` state fires AFTER the pipeline accepts, which is *close enough* for occupancy purposes (a false-listening is nearly impossible; the wake word had to fire to get there). The trigger `assist_satellite.started_listening` is dispatcher-friendly.

**Deliverable sketch:**
- Add `"voice_activity"` to `TIER1_KINDS` in `const.py`.
- Add `CONF_ASSIST_SATELLITE_ENTITIES` to the Room config flow (multi-select of `assist_satellite.*` entities in this room).
- Extend `OccupancySubstrate._KIND_TO_CONF` and `_KIND_PRECEDENCE` (place `voice_activity` HIGH — above mmwave, below explicit motion; a listening satellite is unambiguous).
- Substrate's state-change listener treats `listening` / `processing` / `responding` as `True`, `idle` / unavailable as `False` — with a decay tail (e.g. 30-60s) so a brief command doesn't insta-drop the kind.
- New substrate kind flows automatically into `_room_provenance` (v4.7.19), `_room_occupied` OR-derivation, and every existing zone/room consumer without further wiring — the substrate abstraction is what makes this cycle small.

**Owner:** **PresenceCoordinator / OccupancySubstrate** (unambiguous — the substrate is the extension point; this is exactly what the substrate abstraction was built for).

**Effort tier:** **Tier 2-DB** — not because of the DB, but per operator standing policy (2026-06-08), any change touching a shared primitive (`TIER1_KINDS`) consumed by multiple coordinators (room + zone + presence + binary_sensor + coordinator) gets 3 framing-disjoint reviews. Framings: A = kind semantics + decay correctness; B = every consumer that iterates `TIER1_KINDS` was updated (bug class #53 completeness); C = boot-storm + unavailable satellite + fan-noise interplay (does a chatty satellite prevent the v4.7.20 fan-noise decay gate from firing).

### Axis 3 (RANKED #3) — Voice satellite as a control plane

**Deeply-valuable claim:** the satellite identity **is** the room context. When you say *"make it cooler"* into the Master satellite, URA knows the zone that maps to the room that maps to that satellite. HA's built-in Assist can already resolve intents against exposed entities, but it does NOT know URA's room→zone→HVAC-preset topology; without URA integration, "make it cooler" either fails to find a target or targets whichever climate entity is `preferred_area` — often the wrong one.

**Caveat:** the marginal value here is smaller than axes 1+2 because HA's out-of-the-box Assist + area exposure already handles the trivial cases. URA's leverage is when the intent needs to consult *URA state* (current preset, override lock, egress hold, DPM drift) rather than just call a climate service.

**Deliverable sketch (design-only in this doc — do not build in the first cycle):**
- URA registers a small set of custom intents via `conversation.async_set_agent` or `intent.async_register` — starter set: `URA_MakeCoolerHere`, `URA_MakeWarmerHere`, `URA_LightsOffHere`, `URA_ImHome`, `URA_ImSleeping`.
- Intent handler receives the `device_id` of the satellite that captured the utterance, resolves it to a room via device_registry `area_id` + URA's `CONF_ROOM_AREA`, then dispatches to the correct coordinator (HVAC override, room actuation, house-state transition).
- "Here" is the semantic core — URA is the only integration that unambiguously knows which room "here" is because URA owns the person→room, satellite→room, and room→zone mappings.

**Owner:** a **new thin VoiceCoordinator** (or a `voice.py` sidecar under an existing coordinator). Not NM (this is inbound, not outbound), not PresenceCoordinator (presence has no HVAC/light service knowledge), not per-room RoomCoordinator (intents are house-level and cross-coordinator). A thin new surface keeps the intent registration + satellite→room resolution in one file.

**Effort tier:** **Tier 3** if built end-to-end (cost-and-comfort-impacting, cross-coordinator, delicate). Recommend a **Tier 1 stub cycle first** — register ONE intent (`URA_ImSleeping` → dispatch existing house-state transition; already exists, no new logic), prove the satellite→room→coordinator wiring, then expand.

---

## 3. Coordinator ownership — recommendation

**The likely answer is SPLIT by axis (as the operator suspected):**
- Axis 1 (sensor) → **PresenceCoordinator / OccupancySubstrate** — unambiguous.
- Axis 2 (announce) → **NotificationManager** — unambiguous.
- Axis 3 (control) → **new thin VoiceCoordinator** — the only axis that doesn't fit an existing home.

**Argued alternatives and why they lose:**
- *(a) NM owns everything.* Loses: NM is outbound-only today; making it own inbound intents muddies the mental model, and axis 1 has nothing to do with notifications.
- *(b) PresenceCoordinator owns everything.* Loses: presence has no notification-channel or intent-dispatch responsibility; grafting them on violates single-responsibility and would bloat presence.py (already a large file with prior perf incidents).
- *(c) One new VoiceCoordinator owns all three axes.* Loses: pulls the sensor axis OUT of the substrate, which is exactly the primitive built to avoid tier-splintering (see v4.7.24 tier-vocabulary discipline). The sensor axis lives in the substrate or it lives nowhere useful.
- *(d) Per-room RoomCoordinator owns.* Loses: satellites and intents are house-level (a satellite might target a different room than the one it's in; NM routes across rooms). Per-room ownership can't express cross-room semantics.

**Primary recommendation (single owner for the FIRST cycle):** **NotificationManager, extending `_send_tts` to a routed TTS channel (axis 2).**

Rationale for picking axis 2 as the starting deliverable:
1. Highest immediate operator value (room-routed alarms — a repeatedly-cited gap).
2. Smallest blast radius — no new coordinator, no substrate change, no DB migration.
3. Forces us to solve the `assist_satellite`-entity-per-room config-flow question and the `assist_satellite.announce` vs `tts.speak` reliability question ONCE, in one place, and both axes 1 and 3 reuse the answer.
4. Buys the hardware justification — once axis 2 ships, every satellite in the house has a job even if axes 1 + 3 never ship.

---

## 4. Hardware / operator questions (must resolve BEFORE first cycle)

1. **What satellite hardware is landing in this house?** HA Voice PE (announce-capable, best-of-class mic), Wyoming ESP32-S3-BOX, an HAOS browser satellite on a wall tablet, or a mix? This determines whether `announce` supports_feature is universally available or per-device.
2. **Do `assist_satellite` entities in the live HA instance carry `device_id` + `area_id`?** Live inspection needed — this doc assumes yes, but that assumption is unverified.
3. **How many rooms get a satellite in the first tranche?** The first NM route-mode cycle needs a real routing target set to validate against. If <5 rooms have satellites, `to_person` falls back to `room_media_player` (existing Sonos/etc.) and the value story still works.
4. **Wake-word intercept — appetite?** Axis 1 could be MUCH stronger if URA subscribes to the wake-word intercept WebSocket (unfakeable presence, no `listening` state delay). But intercept means URA can silence wake words — a privacy consideration. Recommend deferring intercept to a later cycle; start with the `listening`-state approach.

---

## 5. Acceptance-criteria sketch — first cycle (NM route-mode, axis 2)

**Cycle name (proposed):** `v5.15.0_nm_tts_room_routing`

### D1: `CONF_NM_TTS_ROUTE_MODE` added to NM config

- **Verify:** OptionsFlow shows a select with 4 modes; default is `flat` (backward compat with today).
- **Sensor:** `sensor.ura_notification_manager_tts` gains attribute `route_mode` with the current value.
- **Test:** `test_nm_tts_route_mode_config_roundtrip` — set each mode via OptionsFlow, restart, confirm persistence.
- **Live:** attribute visible on the NM sensor entity post-restart with operator-selected value.

### D2: `to_person` routing

- **Verify:** `nm.async_notify(severity=MEDIUM, target_person=person.oji_udezue, ...)` speaks ONLY on the media_player / assist_satellite for the room `person.oji_udezue` is currently in.
- **Verify:** when target person is `away`, notification is dropped with DEBUG log (per NM's existing suppression pattern).
- **Test:** `test_nm_tts_to_person_room_resolution` — mock PersonCoordinator.current_room, assert `hass.services.async_call` targeted the expected entity.
- **Live:** operator triggers a test notification via a button; observes speaker for their current room fires and no others.

### D3: `to_occupied_rooms` routing

- **Verify:** at severity=HIGH, speaks on every room where `_room_occupied=True`; skips vacant rooms.
- **Test:** `test_nm_tts_to_occupied_rooms` — parametrized on 3-room occupancy matrix.
- **Live:** operator marks 2 rooms occupied via test switches; test notification fires on both, not on the third.

### D4: `everywhere` routing for CRITICAL

- **Verify:** at severity=CRITICAL, speaks on every configured speaker AND every configured assist_satellite AND every `room_media_player` — same volume, same message.
- **Verify:** existing CRITICAL channels (alert_lights, push) unaffected.
- **Test:** `test_nm_tts_critical_everywhere` — asserts fan-out across mock speakers/satellites.
- **Live:** operator triggers a synthetic CRITICAL; every speaker in the house fires simultaneously.

### D5: Per-room `CONF_ROOM_ASSIST_SATELLITE`

- **Verify:** Room OptionsFlow accepts an `assist_satellite.*` entity_id; router uses it in preference to `room_media_player` when both exist (satellites' `announce` is more reliable than `tts.speak` on browser-based media_players).
- **Sensor:** `binary_sensor.<room>_occupancy` attributes gain `assist_satellite` (echoing the config) for observability.
- **Test:** `test_room_assist_satellite_preferred_over_media_player`.
- **Live:** operator configures satellite on Master Bedroom; test announcement goes via `assist_satellite.announce`, not `tts.speak`.

### Invariant (Tier 2 review target)

*"NM tts channel MUST NOT emit an announcement to a speaker whose room is `vacant` for any severity < CRITICAL, and MUST NOT drop a CRITICAL announcement even when every room is vacant (falls back to `everywhere`)."*

---

## 6. Risks

- **Privacy — wake-word intercept.** Deferred out of the first cycle; flag for the axis-1 planning doc.
- **Wake-word reliability.** Voice PE's wake word is materially more reliable than ESP32-S3-BOX; hardware heterogeneity means axis 1's substrate signal is only as good as the worst mic in each room. Mitigation: substrate is OR-of-kinds, so a false-negative on voice_activity still leaves motion/mmwave/occupancy carrying the room.
- **Boot-storm interplay.** Satellites that boot in `unavailable` and settle to `idle` will emit a state-change; the substrate's boot-settle suppression (v4.7.21) must handle the new kind. Verify in axis-1 planning that `voice_activity=False` on boot is a no-op emit.
- **Announce loudness at 3am.** `to_person` at 3am on a bedroom satellite is potentially very unwelcome. Reuse NM quiet hours (already covers non-CRITICAL); for CRITICAL, that's the point.
- **Fabrication risk.** Two claims in this doc are un-live-verified: (a) `assist_satellite` entities carry `device_id`+`area_id`, (b) `assist_satellite.announce` is more reliable than `tts.speak` on the same device. Both go in the axis-2 planning doc's Institutional-context section as MUST-VERIFY items before build.
- **NM channel health.** New route modes need new channel-health rows or the existing `tts` health row must be split by mode; leaving it as one row is fine for v1 but should be revisited.

---

## 7. ≤30-line summary (for the operator)

Voice satellites unlock three URA-shaped value axes; rank order for THIS house:

1. **Announce (axis 2)** — room-routed NM TTS. HA has no cross-integration room routing today; NM's `_send_tts` fans out to a flat speaker list; MF already resolves room→media_player via `room_media_player`. Owner: **NotificationManager**. Value: "announce to the room Oji is IN, not every speaker at 2am." Effort: Tier 2, ~200-350 LoC, no DB schema change.
2. **Presence (axis 1)** — satellite `listening/responding` state → new `voice_activity` kind in `TIER1_KINDS`. Unfakeable, seated-stillness-immune. Owner: **PresenceCoordinator / OccupancySubstrate** (the substrate exists precisely for this). Effort: Tier 2-DB (shared-primitive change → 3 framing-disjoint reviews per standing policy). Caveat: wake-word itself is NOT exposed as state — only via WebSocket intercept, deferred.
3. **Control (axis 3)** — room-context-aware intents ("make it cooler here"). Owner: **new thin VoiceCoordinator**. Effort: Tier 3 end-to-end, Tier 1 for a single-intent stub. Lowest marginal value (HA Assist already handles trivial cases).

**Coordinator ownership** is SPLIT by axis (as suspected). No single coordinator should own all three; forcing that violates single-responsibility and either bloats presence.py or splinters the substrate.

**Recommended first-cycle deliverable:** NM `CONF_NM_TTS_ROUTE_MODE` + per-room `CONF_ROOM_ASSIST_SATELLITE` (axis 2, D1-D5 above). Highest value, smallest blast radius, no substrate change, no DB migration. Once shipped, every satellite in the house has a job even if axes 1+3 never ship.

**Blocking operator questions BEFORE first cycle:** (1) satellite hardware mix, (2) live confirmation that `assist_satellite` entities carry `device_id`+`area_id`, (3) which rooms get satellites in tranche 1, (4) appetite for the wake-word intercept privacy trade later.

---

## Sources

- [Assist satellite entity — HA Developer Docs](https://developers.home-assistant.io/docs/core/entity/assist-satellite/)
- [Assist Satellite integration — Home Assistant](https://www.home-assistant.io/integrations/assist_satellite/)
- URA in-repo: `custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py`, `notification_manager.py`, `music_following.py`, `const.py:342` (`TIER1_KINDS`).
