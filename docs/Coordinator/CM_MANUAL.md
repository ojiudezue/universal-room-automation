# Coordinator Manager Manual (Operator Manual)

**Audience:** the homeowner running URA.
**Scope:** the URA **Coordinator Manager (CM)** entry — the central
options surface for every domain coordinator (presence, safety,
security, energy, HVAC, notifications, music-following, optimization,
signal responses), plus the CM device's own sensors and switches.
**Current through:** URA v5.45.0 (`const.py:34`).

Sibling of `HOUSE_MANUAL.md`, `ZONE_MANUAL.md`,
`ENERGY_COORDINATOR_MANUAL.md`, `HVAC_COORDINATOR_MANUAL.md`.

---

## 1. What the Coordinator Manager is

A single `ENTRY_TYPE_COORDINATOR_MANAGER` config entry that hosts
runtime configuration for every domain coordinator. Its options are the
authoritative store for cross-coordinator knobs (fan-recheck timings,
BAEC / arbitrage windows, NM routing, etc.) — a domain coordinator
that carries no `entry` of its own reads its knobs from CM options via
an entry-type sweep (`presence_fan_recheck.py:887-926` is a good
reference pattern).

Coordinators themselves are toggled on/off via **switch entities** on
the CM device (not the options flow); see §4.

---

## 2. Options menu map

**Settings → Devices & Services → URA: Coordinator Manager → Configure**

Menu (`config_flow.py:2608-2638`) — currently 11 steps:

| Step | Step id | What it edits |
|---|---|---|
| Presence | `coordinator_presence` | Fan-recheck timings, LOST-AWAY grace, boot-settle gates |
| Safety | `coordinator_safety` | Safety coordinator options |
| Security | `coordinator_security` | Alarmo integration; `CONF_SECURITY_AUTO_FOLLOW` |
| Energy | `coordinator_energy` | TOU windows, BAEC (folded in 2026-07-17), inclement, cloud verification |
| HVAC | `coordinator_hvac` | Fan trust states, vacancy timers, Dynamic Preset dwell / hysteresis |
| HVAC Settings | `coordinator_hvac_settings` | Deeper HVAC settings sub-form |
| Music Following | `coordinator_music_following` | Zone-follow policy |
| Notifications | `coordinator_notifications` | NM channels (Pushover / Companion / WhatsApp / iMessage / TTS / lights) |
| Notifications — Volume | `coordinator_notifications_volume` | NM Cycle A-2 rung-2 knobs (bucket capacity, digest windows) |
| Notifications — Routing | `coordinator_notifications_routing` | NM Cycle C-2: per-person routing matrix, hazard overrides, DND-bypass, mute-default duration |
| Signal Responses | `signal_responses` | Cross-coordinator signal-response overrides (v3.22.0) |
| Optimization | `coordinator_optimization` | Optimization Coordinator options (Phase 1 D7) |

Reached via the same step ids but through drill-in from `coordinator_notifications`:
`coordinator_notifications_persons`, `coordinator_notifications_quiet`,
`coordinator_notifications_cooldowns` (`config_flow.py:6188-6401`).

**Note on BAEC:** the standalone `coordinator_baec` menu item was
retired 2026-07-17; BAEC lives as sibling sections
(`baec` / `baec_advanced`) inside `coordinator_energy` now
(`config_flow.py:2631-2637`).

---

## 3. Notification Manager (routing details)

The NM (`domain_coordinators/notification_manager.py`) dispatches
severity-tagged events from every coordinator to configured channels.

### 3.1 Per-channel enable + severity floor

All in CM options, verified against `const.py:1426-1440`:

| Channel | Enable key | Severity key |
|---|---|---|
| Pushover | `nm_pushover_enabled` | `nm_pushover_severity` |
| HA Companion | `nm_companion_enabled` | `nm_companion_severity` |
| WhatsApp | `nm_whatsapp_enabled` | `nm_whatsapp_severity` |
| iMessage / BlueBubbles | `nm_imessage_enabled` | `nm_imessage_severity` |
| TTS | `nm_tts_enabled` | `nm_tts_severity` (+ `nm_tts_speakers`) |
| Alert Lights | `nm_lights_enabled` | `nm_lights_severity` (+ `nm_alert_lights`) |

The severity floor is the classic level ladder
(`off / errors / important / all`, `const.py:769-774`).

### 3.2 Per-person routing (`coordinator_notifications_persons`)

Under `CONF_NM_PERSONS` (`const.py:1443`) — a list of person entries
each carrying (`const.py:1444-1458`):
- `nm_person_entity` — the HA `person.` entity
- Delivery handles: `nm_person_pushover_key`,
  `nm_person_pushover_device`, `nm_person_companion_service`,
  `nm_person_whatsapp_phone`, `nm_person_imessage_handle`
- `nm_person_delivery_pref` — per-person channel preference order
- Digest cadence: `nm_person_digest_morning`,
  `nm_person_digest_evening_enabled`, `nm_person_digest_evening`,
  `nm_person_digest_channels`

**Watchdog fixed 2026-07-29:** recipients list was empty pre-fix and
all NM alerts were dropped. If you're not seeing notifications, this
step is the first place to check.

### 3.3 Quiet hours

`coordinator_notifications_quiet` (`const.py:1464-1466`):
- `nm_quiet_use_house_state` — use house-state-driven quiet
- `nm_quiet_manual_start` / `nm_quiet_manual_end` — manual override
  window

### 3.4 Cooldowns per hazard type

`coordinator_notifications_cooldowns` (`const.py:1469-1475`):
`nm_cooldown_smoke`, `_co`, `_flooding`, `_water_leak`, `_freeze`,
`_intrusion`, `_default`. Seconds.

### 3.5 Kill switches

- **`nm_dry_run`** (`const.py:1516`) — top-level; when True, NM
  composes messages and logs them but does NOT dispatch to channels.
- **`nm_bucket_capacity`** (`const.py:1548`) — rate-limit bucket size
  (NM Cycle A-2 volume control).
- Per-room bypass: `CONF_OVERRIDE_NOTIFICATIONS` on any room
  (`const.py:57`).

Full detail: `docs/Coordinator/NOTIFICATION_MANAGER.md`.

---

## 4. CM-device entities (sensors / switches / selects)

The CM device (`URA: Coordinator Manager`) carries the
cross-coordinator control surface:

### 4.1 House policy sensor

- **Entity:** `sensor.ura_coordinator_manager_house_policy`
  (`sensor.py:4055-4125`; `HousePolicySensor`).
- **Value:** `CoordinatorManager.house_policy` — the live composed
  policy string (recomputed continuously). This is the single
  read-back of "what is the house currently doing?"

### 4.2 House-state override selects

Three redundant Select entities target the same override
(`select.py:172-235`):
- `select.ura_house_state_override` (integration device)
- `select.ura_cm_house_state_override` (CM device)
- `select.ura_presence_house_state_override` (presence device)

All three read/write via `presence.get_house_state_override()` and
`presence.set_house_state_override(option)` — pick whichever surface
is convenient. There is also a service
**`universal_room_automation.clear_house_state_override`**
(`services.yaml:24`) that returns to automatic inference.

Legal options are the `HouseState` members (`away`, `arriving`,
`home_day`, `home_evening`, `home_night`, `sleep`, `waking`,
`guest`, `vacation`) plus an unset / auto value.

### 4.3 Security auto-follow

`CONF_SECURITY_AUTO_FOLLOW` (`const.py:1266`, `security.py:715`) —
under `coordinator_security`. When True, the security coordinator
auto-maps house state to Alarmo arming (`away → armed_away`,
`home → armed_home`). **Default False** (`config_flow.py:5872-5873`).

### 4.4 Coordinator on/off switches

Coordinator enable/disable moved from options to **switch entities**
in v3.6.0-c2.4 (`const.py:1215-1234`). Each coordinator has its own
switch on the CM device (`presence`, `safety`, `security`, `energy`,
`hvac`, `comfort`, `music_following`, `notification_manager`).
Flipping a coordinator OFF here is the durable kill switch — do NOT
edit the options flow to disable a coordinator.

### 4.5 Fan-recheck master

- **Switch:** the master `FanRecheckEnabledSwitch` (writes through
  to CM options via `_mirror_options`). Read at
  `hass.data[DOMAIN]["fan_recheck_master_enabled"]`
  (`presence_fan_recheck.py:872-880`).
- **Default:** OFF (opt-in). Per-room opt-in is
  `room_fan_recheck_enabled` on the room, default ON
  (`const.py:417-418`).
- **Timing knobs** live in CM options under
  `coordinator_presence` — read at runtime by the recheck manager
  (`presence_fan_recheck.py:887-926`). Full list:
  `CONF_FAN_RECHECK_ARM_DELAY_S`, `_SPINDOWN_S`, `_WINDOW_S`,
  `_COOLDOWN_S`, `_MAX_PER_HOUR`, `_HVAC_SUPPRESS_S`,
  `_MMWAVE_HISTORY_TICKS`. Defaults in `const.py:437-462`.

### 4.6 Optimization / routine notification

- `select.ura_coordinator_manager_routine_change_notification_mode`
  (`select.py:309+`) — `silent` (default, use during 4-6 week
  warm-up) / `weekly_digest` / `event`.

---

## 5. Coordinator toggles vs. coordinator options

- **Coordinator ON/OFF:** switch entity on CM device (§4.4). Persisted
  via HA switch state; survives restart.
- **Coordinator knobs:** CM entry options via the relevant step in §2.

If a coordinator's behavior isn't changing after you flipped an
options value, verify: (a) the coordinator's own enable switch is ON;
(b) the coordinator has been reloaded — some options need a config
entry reload for the coordinator to pick them up. Fan-recheck
timings are the exception — they're re-read from CM options each
evaluation (`presence_fan_recheck.py:887-926`).

---

## 6. When to reach for what

| Symptom | Where to look |
|---|---|
| "House said away but somebody's home" | House-state override select (§4.2) or `HOUSE_MANUAL.md §5` |
| "No notifications firing" | NM persons list (§3.2), then per-channel enable (§3.1), then `nm_dry_run` (§3.5) |
| "Fan-recheck fired at wrong time" | Master switch + per-room enable (§4.5); timings in `coordinator_presence` |
| "Alarmo not tracking house state" | `CONF_SECURITY_AUTO_FOLLOW` (§4.3) |
| "Which coordinator is even running?" | Per-coordinator switch entities on CM device (§4.4) |

---

## 7. Related surfaces

- **House tier (state machine, AWAY veto, sleep/wake, guest gate):**
  `HOUSE_MANUAL.md §5`.
- **Zone tier (zone config, HVAC zones vs house zones):**
  `ZONE_MANUAL.md`.
- **Notification Manager (channels + audit history):**
  `docs/Coordinator/NOTIFICATION_MANAGER.md`.
- **Dynamic Preset per-zone knobs:**
  `docs/user-manual/DYNAMIC_PRESET.md`.

---

Relevant files:

- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/const.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/config_flow.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/select.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/sensor.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/services.yaml`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/presence_fan_recheck.py`
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/security.py`
