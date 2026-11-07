# PLANNING — Ask the house by text: `diag` menu over WhatsApp / iMessage (NM-INBOUND-HOUSE-QUERIES-1, option A)

**Card:** `NM-INBOUND-HOUSE-QUERIES-1` (`docs/planning/kanban.data.yaml:214`), fields `design_2026_11_07`, `shared_layer_2026_11_07`.
**Tier:** 2 (operator-elevation to 2-DB suggested, see §9). One adversarial plan review before build.
**Status:** rev 1, pre-review. Author: ura-planner, 2026-11-07.
**Mandatory reads done:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (read completely; the `hvac` answer displays zone state) and `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` + `docs/architecture/SENSOR_FLEET_CLASSES.md` (read completely; the `who` answer displays house state / persons). No HVAC §10 or presence §10 claim is re-asserted. Two doc facts this plan depends on are cited inline (HVAC §9.9 zone_1 status-feed lie, HVAC §9.9 "hvac_action useless on zone_1").

---

## 0. Shape in one paragraph

Texting `diag` to URA (WhatsApp or iMessage; Pushover too, same parser) returns a short numbered menu. Replying with a number (inside a short per-sender window) or a command name (any time) returns a read-only answer: `doors`, `garage`, `who`, `hvac`, `energy`, `alerts`, `health`. Answers come from a new pure read-only module `house_status.py` (functions over `hass` + coordinators that return structured data plus a short text render), so the OC agent can call the same functions as tools later. The NM change is one dispatch block inside the existing `_process_inbound_reply`; nothing in the alert path changes. The `1`/`2`/`3` conflict is resolved by two independent rails: a STATE rail (any NM alert not IDLE, digits keep their legacy meaning) and a SEND rail (any non-reply NM outbound send closes every open menu window at send start). The state rail alone has a real gap, because `async_notify` sends BEFORE it sets `ALERTING` (§2.3).

---

## 1. Institutional context verified (MANDATORY)

### 1.1 Prior-art scan: REUSE or BUILD per piece

| Piece | Verdict | Existing symbol (file:line) / why NEW |
|---|---|---|
| Inbound transport (WA, iMessage, Pushover, Companion) | **REUSE** | `_handle_whatsapp_reply` `notification_manager.py:3404`, `_handle_bb_webhook` `:3439`, `_handle_pushover_webhook` `:3418`, `_handle_companion_action` `:3373`. All funnel into `_process_inbound_reply` `:3547`. |
| Sender allowlist / authorization | **REUSE** | `_match_person_by_phone` `:3477`, `_match_person_by_imessage_handle` `:3495`, `_match_person_by_pushover_key` `:3486`. Unknown senders are dropped before parsing (WA `:3411-3413`, BB `:3468-3473` "Only process messages from known persons"). Diag inherits this unchanged. |
| Echo guard rail 1 (exact-match outbound ring) | **REUSE** | `_record_outbound_text` `:3511`, `_is_self_echo` `:3526`, applied first in `_process_inbound_reply` `:3553`; knobs `NM_ECHO_GUARD_TTL_S` / `NM_ECHO_GUARD_BUFFER_LEN` `:266-271`. Diag replies go out through `_send_reply` → `_send_imessage` / `_send_whatsapp`, which record the body (`:2349`, `:2392`), so their echoes are dropped like any reply. |
| Reply rate rail 2 (per person+channel floor) | **REUSE + EXTEND** | `NM_REPLY_MIN_INTERVAL_S = 30.0` `:272`, `NM_REPLY_RATE_LIMITED_CHANNELS` `:276`, `NM_REPLY_RATE_LIMIT_EXEMPT_COMMANDS` `:280-287`, enforced in `_log_and_reply` `:4019-4033`. EXTEND: diag commands are exempt from the 30 s floor (a person picking from a menu replies within 30 s, which would swallow every answer) and get their own budget (§6). |
| Kill switch for all replies | **REUSE** | `self._messaging_suppressed` check `:3576` returns before parsing. Diag sits after it. |
| Silence window | **REUSE (extend exemption)** | `:3651-3661`: while silenced, everything except `status`/`help`/safe word gets "Alerts silenced". Diag is read-only, so it joins the exemption. |
| Safe word + safe-word window pre-parse | **REUSE, untouched, runs first** | `_NM_SAFEWORD_WINDOW_RE` `:310`, pre-parse `:3586-3649`, `_match_safe_word` `:3017` called `:3650`, branch `:3674`. Diag resolution is computed only when `is_safe_word` is False, so a safe word that happens to equal `1` or `doors` keeps winning. |
| Command parse | **REUSE pattern** | `RESPONSE_COMMANDS` `:244-254` (exact whole-text match after `strip().lower()`). Diag uses a sibling exact-match table `DIAG_COMMANDS`; no substring or first-token parsing anywhere (load-bearing for the echo argument in §6.3). |
| Inbound audit row | **REUSE** | `database.log_inbound` `database.py:5051` into `notification_inbound` (`database.py:1476`, `parsed_command TEXT`). New `parsed_command` values `diag_menu`, `diag_<item>`, `diag_rate_limited`, `diag_bad_pick`. No schema change. |
| Inbound counters (sensor) | **REUSE + EXTEND** | `_inbound_by_command` `:461`, surfaced by `inbound_by_command` `:943`. Add key `diag` (dict, one key; no new entity). |
| Existing "status" answer | **REUSE, unchanged** | `_build_status_response` `:3874` (alert status only). `2`/`status` keep returning it. The new `alerts` item is a superset and is separate. |
| Help text | **EXTEND (help reply only)** | `RESPONSE_DICT_TEXT` `:256` is appended to EVERY alert body (`:1740-1742`), so it is NOT changed (alert bodies stay byte-identical). Only the `help` reply (`:3843-3851`) gains one line: `diag = house status menu`. |
| Read-only house-status module | **BUILD (NEW)** | Grepped `custom_components/universal_room_automation/*.py` + `domain_coordinators/*.py` for `house_status`, `context_pack`, `build_context`, `house_snapshot`, `def get_.*status` aggregators: none. `ura_context.py` is the URA write-context mark, unrelated. OC `docs/planning/oc_eval/tools.json` (32 tools) has only generic tools (`ha_get_state`, `ura_db_query`, ...), no house-status tool. |
| Lock / garage entity lists | **REUSE (config-first)** | Security coordinator config `CONF_SECURITY_LOCK_ENTITIES` / `CONF_SECURITY_GARAGE_ENTITIES` (`const.py:3406-3407`), held as `SecurityCoordinator._lock_entities` / `_garage_entities` (`security.py:559-560`). The plan does NOT hard-code the operator's 5 lock + 2 cover ids. |
| Lock state | **REUSE (live HA state, not the cache)** | `lock_compliance` `security.py:2314` is a cache refreshed by the periodic lock check (`:1685-1711`). The answer reads `hass.states` for the same ids (fresher); `lock_compliance` is not read. |
| House state | **REUSE** | `CoordinatorManager.house_state` `manager.py:325`. NOT `PresenceCoordinator.house_state` `presence.py:1992`, which returns a fabricated `"away"` when the manager is missing (producer defect for a display: "unknown" must say unknown). |
| Census / persons | **REUSE** | `PresenceCoordinator.census_count` `presence.py:1987`; per-person `person_state_for_trust` `person_coordinator.py:130` (BLE-overrule-aware) and `PersonCoordinator.get_person_location` `person_coordinator.py:1981`. |
| HVAC zones | **REUSE** | `HVACCoordinator.zone_manager` `hvac.py:996` → `ZoneManager.zones` `hvac_zones.py:420` → `ZoneState` `hvac_zones.py:128` (`current_temperature`, `target_temp_low/high`, `preset_mode`, `hvac_action`, `ac_load_sensor` `:215`). |
| Energy | **REUSE** | `BatteryStrategy.battery_soc` `energy_battery.py:1089` (Envoy → LKG → cloud resolver; memory `project_battery_soc_envoy_not_span`: never SPAN). Solar: `solar_production_w` `energy_battery.py:2553` (staleness-gated), NOT the raw `solar_production` `:2407`. Grid: `net_power` `:2412` (raw; see §3 producer row). Reached via `manager.coordinators.get("energy")` (pattern `time.py:139`). |
| Anomalies | **REUSE** | Each coordinator's `anomaly_detector.get_sensor_state()` (`coordinator_diagnostics.py:1314`; detectors at `hvac.py:1822`, `security.py:786`, `presence.py:2702`, `safety.py:1244`, `music_following.py:247`); NM `anomaly_status` `notification_manager.py:909`. |
| Unacked criticals | **REUSE** | `database.get_active_criticals` `database.py:4939` (read). |
| Unavailable entities per room | **REUSE** | `UnavailableEntitiesSensor` `sensor.py:1806` (state = count, attrs `unavailable_actuators`, `actuator_count`, `sensor_count` `:2055-2066`), unique_id `{entry_id}_unavailable_entities` (`entity.py:34`). Resolved through the entity registry by unique_id (ROOM-SWITCH-LOOKUP-BY-NAME-1 pattern, presence STATE_OF_PLAY §4.5), never by slug. |
| Integration problems | **REUSE** | HA issue registry entries for `DOMAIN` (URA creates repairs, 10 `async_create_issue` sites) + NM `channel_status` `notification_manager.py:810`. |
| Menu window state | **BUILD (NEW, RAM only)** | No existing per-sender conversational state in NM (grepped `_menu`, `_window`, `_pending_reply`, `_conversation`: only the safe-word perimeter window `_perimeter_silence_until` `:446`, a different concept). RAM dict, not persisted: a restart closes every window (correct direction). |
| Close-on-send hook | **BUILD (NEW, 4 sites)** | Added at the top of the four text senders `_send_pushover` `:2208`, `_send_companion` `:2255`, `_send_whatsapp` `:2311`, `_send_imessage` `:2355`. See §4 enumeration. |

### 1.2 Greps run (reproduce)

```
grep -n "RESPONSE_COMMANDS\|NM_ECHO\|NM_REPLY_\|_messaging_suppressed\|_silence_until" domain_coordinators/notification_manager.py
grep -n "_send_imessage(\|_send_whatsapp(\|_send_pushover(\|_send_companion(" domain_coordinators/notification_manager.py
   → callers: 1909/1931/1958/1980 (async_notify), 2944-2966 (repeat), 4052-4065 (_send_reply), 5002-5049 (digest), 5359-5374
grep -n "_alert_state = AlertState" domain_coordinators/notification_manager.py   → ALERTING set at :2651 inside _enter_alerting (:2592), called :2099
grep -rn "house_status\|context_pack\|house_snapshot" custom_components/   → none
grep -n "CONF_SECURITY_LOCK_ENTITIES\|CONF_SECURITY_GARAGE_ENTITIES" const.py domain_coordinators/security.py
grep -n "def battery_soc\|def solar_production\|def net_power" domain_coordinators/energy_battery.py
grep -n "def zone_manager\|def zones" domain_coordinators/hvac.py domain_coordinators/hvac_zones.py
grep -n "class UnavailableEntitiesSensor" sensor.py ; grep -n "_attr_unique_id" entity.py
grep -n "async def log_inbound\|CREATE TABLE IF NOT EXISTS notification_inbound" database.py
```

### 1.3 Prior plans, memory, design docs

- `docs/plans/PLAN_notification_manager_c4b.md` (full skim): inbound + fixed response dictionary; its non-goal line 32 "Command processing beyond ack/status/stop ('lock all doors', 'arm security')" is kept here as a hard rule (read-only). Its "rate limiting inbound — probably not needed" (line 502) was overtaken by the 2026-08-05 echo incident (rails 1/2).
- `docs/PLAN_nm_bluebubbles_imessage.md` (skim of inbound sections): BB webhook, handle matching, `isFromMe` skip.
- `docs/Coordinator/NOTIFICATION_MANAGER.md` (skim; the design doc predates inbound details; §7 RateLimiter never shipped per the audit memo).
- Memory `project_nm_bb_wa_audit_2026_05_30.md` (body read): NM channel surface; the speced RateLimiter debt; sends append the response dict.
- Card `NM-BB-CHATGUID-SELFSEND-1` (`kanban.data.yaml:8564`): the operator's iMessage alerts arrive as texts from himself; BB runs on the Mac mini as the operator's Apple ID. Direct consequence for this plan: an operator-typed `diag` in his self-thread may arrive with `isFromMe=True` and be dropped at `:3456` before NM sees it. Whether operator iMessage inbound works at all today is UNVERIFIED and is a D0 gate.
- `docs/QUALITY_CONTEXT.md`: classes #7 (stale source), #19 (untracked tasks), #23 (observation gating), #42 (async_create_task from callbacks), #53 (computed-not-consumed / one missed site), #63 (coincidental equality) consulted; each maps to a test or rail below.
- `docs/reviews/URA_ARCHITECTURE_MAP.md`: NM is cross-cutting; the answers read room / zone / house values without writing any of them.
- `PLANNING_oc_live_eval_and_context_pack.md` and card `oc_followups_2026_11_07`: the OC agent's M2 failures were citation hygiene; the shared module returns `sources` (entity ids / getter names) per field so a tool caller can cite.

---

## 2. Design, and the `1`/`2`/`3` conflict

### 2.1 Grammar

| Text (whole message, `strip().lower()`) | Meaning | Window needed |
|---|---|---|
| `diag` (aliases `menu`, `house`) | open window, reply with the menu | no |
| `doors` / `garage` / `who` / `hvac` / `energy` / `alerts` / `health` | run that item | no, any time |
| `1`..`7` | run menu item N | yes, and both rails clear (§2.2) |
| `8`, `9`, `0`, `10`... inside an open window | "Pick 1-7 or a name" (`diag_bad_pick`) | yes |
| anything else | unchanged legacy path | — |

Menu text (fits one screen):
```
House menu (reply number or word):
1 doors  2 garage  3 who
4 hvac   5 energy  6 alerts
7 health
```

Exact whole-text match only. No first-token, substring or fuzzy parse (load-bearing for §6.3).

### 2.2 Precedence inside `_process_inbound_reply` (new order; existing steps unchanged)

1. Echo rail 1 (`:3553`) — unchanged.
2. `_messaging_suppressed` (`:3576`) — unchanged.
3. Counters, safe-word-window pre-parse, `_match_safe_word` (`:3580-3650`) — unchanged.
4. **NEW:** `diag = None if is_safe_word else self._resolve_diag(text, person_id, channel)`. Pure (no I/O). Returns an item key, `"menu"`, `"bad_pick"`, or `None`.
   - A digit resolves to an item ONLY IF the (person, channel) window is open AND `self._alert_state is AlertState.IDLE` (state rail) AND the window was not closed by the send rail. Otherwise `None` → the digit falls through to `RESPONSE_COMMANDS` exactly as today.
   - A name or `diag` resolves regardless of window and alert state.
5. Silence gate (`:3651`) — the exemption list gains "diag is not None".
6. Safe-word branch (`:3674`) — unchanged.
7. **NEW:** `if diag is not None:` → build answer via `house_status`, `_log_and_reply(..., f"diag_{item}", ...)`, return. Placed BEFORE `if command == "ack"`.
8. ack / status / silence / help / unknown — unchanged (help gains one line).

### 2.3 Why two rails, and why the state rail alone is not enough

The proposed resolution (window closes when any alert is sent to that person) is right in direction but, as a sole rail, it needs a per-person stamp at every outbound site (5 caller groups, §4) and depends on person attribution at sites that only know a handle. I keep it but move it to the four sender choke points, house-wide (any non-reply text send closes ALL windows), and add a STATE rail as the primary guard:

- **State rail (one site):** digits map to the menu only while `_alert_state is IDLE`. ALERTING / REPEATING / COOLDOWN / RE_EVALUATE all keep digits legacy. One check at the parse site cannot be missed by a future emitter.
- **Send rail (four sites):** `async_notify` sends to every channel at `:1909-1980` and only then calls `_enter_alerting` (`:2099`), which sets ALERTING at `:2651`. During those send awaits the state is still IDLE, so a fast `1` (e.g. a person who already had the menu open and taps 1 the instant a CRITICAL lands) would pass the state rail. The send rail closes all windows synchronously at the TOP of each sender, before its first await and before the dry-run return, so the window is shut before the alert body can even reach a phone.
- Neither rail alone holds the invariant: state-only leaks during the send window; send-only leaks for any future emitter that bypasses the four senders (e.g. a new channel). Together they are independent.

Residual accepted by name: inside an open window with NO alert active, `3` means "who", not "silence" (pre-emptive silence). `3` with IDLE today silences non-critical alerts for 30 min; a person who just asked for the menu and sends `3` almost certainly means the menu. Word `silence`/`stop`/`mute` still silences. `1` with IDLE today replies "No active alerts" (no effect lost); `2` with IDLE replies "All clear" (no effect lost).

### 2.4 Verdict on the operator design, and alternatives considered

- **Operator design (numbered menu + window + names any time): BUILD, with the two-rail fix above.** The numeric path costs about 40 lines plus the two rails; the rails are what make it safe, not an add-on.
- **Alternative N (names only, `diag` lists names, no numbers):** zero interaction with ack. Captures most of the value (typing `doors` vs `1`). Kept as the fallback: setting `NM_DIAG_MENU_WINDOW_S = 0` gives exactly this (kill switch for the numeric path).
- **Alternative O (offset numbers 4-10, no window):** no collision and no state, but the menu reads oddly and `4` vs a future fourth legacy command collides. Rejected.
- **Alternative L (free-text LLM answers, option B on the card):** out of scope; the OC engine still fails M2 citation hygiene (card). This plan's shared module is the deterministic substrate B would call.

---

## 3. Producer AND consumer checks (every value an answer reads)

"Healthy today" columns marked UNVERIFIED-LIVE are confirmed by D0 (I did not touch HA in planning).

| Item / value | Producer (derivation that wins) | Dependency health today | Consumer of the new read | Trust vs display |
|---|---|---|---|---|
| doors: each lock state | HA `lock.*` state for ids in `SecurityCoordinator._lock_entities` (`security.py:559`, from `CONF_SECURITY_LOCK_ENTITIES`) | UNVERIFIED-LIVE: whether all 3 door locks and the 2 lockout locks (`lock.konnected_f0f5bd523b00_lock`, `lock.ratgdov25i_dbfe2a_lock_remotes`) are in that list. Z-Wave locks can read `unavailable`/`jammed`; render verbatim. | `house_status.doors()`; NM render; later OC tool | display only |
| garage: cover state + lockout | HA `cover.*` for ids in `_garage_entities` (`security.py:560`); lockout locks as above | Card GARAGE-REMOTE-LOCKOUT-SCHEDULE-1: whether ratgdo lockout blocks the keypad is UNVERIFIED physically; the answer reports the entity state only ("remotes locked out: on"), never "keypad blocked" | `house_status.garage()` | display |
| who: house state | `CoordinatorManager.house_state` `manager.py:325` | healthy path; NOT `presence.house_state` (`presence.py:1992` fabricates `away` when manager missing). Missing manager → `unknown` | `house_status.who()` | display |
| who: census | `presence.census_count` `presence.py:1987` | Census arc history: an additive derivation once double-counted residents into GUEST (CLAUDE.md producer rule origin); face recognition coverage partial. Render as "~N people (estimate)" | same | display |
| who: per person | `person_state_for_trust` `person_coordinator.py:130` + `get_person_location` `:1981` | Presence STATE_OF_PLAY §3: GPS-assistive BLE overrule live; raw state otherwise | same | display |
| hvac: temp per zone | `ZoneState.current_temperature` `hvac_zones.py:140` (from climate attr `:685`) | healthy (websocket keeps temperature current, HVAC STATE_OF_PLAY §5) | `house_status.hvac()` | display |
| hvac: range | `target_temp_low/high` `hvac_zones.py:142-143` | Carrier status-feed setpoints can be stale (HVAC §5 "status feed's setpoints go stale"); render "set" not "target confirmed" | same | display |
| hvac: preset | `ZoneState.preset_mode` (adapter `preset_of_for`, HVAC §4.4) | **Known producer defect:** zone_1 status feed reads `home` while physically `away` (HVAC §9.9). Render as "thermostat reports <preset>" | same | display |
| hvac: running | **NOT `hvac_action`**: HVAC §9.9 records `hvac_action` on zone_1 as "useless (cooling on every row)". Use the zone's `ac_load_sensor` (`hvac_zones.py:215`) kW > a threshold → "running"; no load sensor → omit the field ("running: not measured") | UNVERIFIED-LIVE: load sensors present on all 3 zones (nudge thresholds exist per zone, HVAC §6, which implies they do) | same | display |
| energy: SOC | `BatteryStrategy.battery_soc` `energy_battery.py:1089` (Envoy → LKG ≤5 min → cloud) | Envoy flapping history (memory `project_session_pickup_2026_09_23`); resolver handles it; None → "unknown" | `house_status.energy()` | display |
| energy: solar now | `solar_production_w` `energy_battery.py:2553` (stale CT → None) | ENVOY-PRODUCTION-STALE-1 gate present | same | display |
| energy: grid now | `net_power` `energy_battery.py:2412` (raw, sign + import / − export) | No freshness gate on this getter (UNVERIFIED whether a gated sibling exists; builder greps `_read_fresh_power_w` callers). Render with the source entity's age when > 5 min | same | display |
| alerts: NM state | `self._alert_state`, `_active_alert_data` (NM) | healthy | `house_status.alerts()` (called from NM with NM passed in) | display |
| alerts: unacked criticals | `database.get_active_criticals` `database.py:4939` | Memory NM-RECOVERY-AGEBOUND-1: an unbounded backlog of historical unacked CRITICALs existed (326 rows). Render count + newest 3 with age; cap age at the same bound the recovery uses (builder cites the constant) so a stale backlog is not reported as active | same | display |
| alerts: anomalies | each `coordinator.anomaly_detector.get_sensor_state()` | v5.103.25 made blind metrics read `partial`/`learning` instead of `nominal`; render non-nominal only | same | display |
| health: unavailable | per-room `sensor.<room>_unavailable_entities` state + `actuator_count` (registry lookup by unique_id) | healthy if every room has the sensor (UNVERIFIED-LIVE count) | `house_status.health()` | display |
| health: integration problems | HA issue registry for `DOMAIN`; NM `channel_status` | healthy | same | display |

Consumers of the new module: NM diag (this cycle) only. OC is a named future consumer (non-goal here). No trust decision anywhere reads `house_status`; an AST lint keeps it display-only (D1).

---

## 4. Emission / decision-site enumeration

**Inbound decision sites (where a text becomes an effect):** exactly one, `_process_inbound_reply` `:3547`. Entry points into it: `:3389`, `:3393`, `:3400` (companion, person None), `:3415` (WA), `:3437` (Pushover), `:3475` (BB). Grep `"_process_inbound_reply("` must return exactly these 6 calls plus the definition after the build.

**Outbound text sends (send-rail sites):** every NM text send goes through one of four senders. Callers today:
- `async_notify` `:1909, :1931, :1958, :1980`
- repeat cycle `:2944, :2951, :2959, :2966`
- `_send_reply` `:4052, :4056, :4061, :4065` (the ONLY caller allowed to pass `menu_safe=True`)
- daily digest `:5002-5049`
- `:5359-5374` (builder reads and names this caller in the review record)

The rail lives in the four sender bodies (`:2208`, `:2255`, `:2311`, `:2355`), so all callers are covered, including future ones. TTS (`_send_tts`) and wall panels do not reach a phone and are not rail sites (noted, not gated). Test D3-T4 enumerates sender callers by AST and fails if a fifth text sender function appears without the rail.

**Service calls reachable from inbound text (I2 surface):** today `async_acknowledge` (ack / safe word), `_silence_until` assignment (silence), `_ack_all_criticals_and_release`, perimeter-window open (safe-word window), `_announce_ack` (TTS), `async_notify` LOW notes from the safe-word window, and the reply senders. The diag branch adds NONE: only `house_status` reads plus `_log_and_reply`.

---

## 5. Falsifiable invariants

- **I1 (ack never swallowed):** For any inbound whose normalized text is `1`, `2` or `3`, if at processing time `_alert_state` is not IDLE, OR any non-reply text send began after the sender's window opened, the text is handled by the legacy `RESPONSE_COMMANDS` path with byte-identical effect and reply. In particular: a bare `1` sent at any moment after a CRITICAL send to that person began is treated as the legacy ack (which, for CRITICAL, replies "requires safe word").
- **I2 (read-only):** No inbound text whose normalized form is a diag token (`diag`, `menu`, `house`, an item name, or a digit resolved to an item) causes any `hass.services.async_call` other than the reply send through `_send_reply`, any DB write other than the one `log_inbound` row, any state mutation of NM other than the menu-window dict and the diag counters, or any signal other than the existing `SIGNAL_NM_ENTITIES_UPDATE`.
- **I3 (no echo loop):** No diag reply body, once echoed back verbatim or with the channel's title prefix, resolves to any command (legacy or diag). Holds because every sent reply contains a newline (title prefix `URA\n` / `*URA*\n`, `:2333`, `:2377`) and all matching is exact whole-text.
- **I4 (no regression for non-diag text):** For every inbound text that is not a diag token, and for digits when the window is closed, `_process_inbound_reply` returns the same string and performs the same calls as the pre-cycle code (golden comparison).
- **I5 (bounded reply):** No diag reply exceeds `NM_DIAG_MAX_REPLY_CHARS` after the title prefix; a truncated reply ends with `…(more: <item>)`.

Reviewer D's job: break I1 (find an IDLE-and-no-send moment where a person intends ack, or an outbound path that bypasses the four senders) and I2 (find any service call or write reachable from a diag token).

---

## 6. Rate limiting, length, authorization, echo

### 6.1 Rate limiting
- Rail 2's 30 s floor stays for everything it covers today. Diag `parsed_command` values (`diag_menu`, `diag_<item>`, `diag_bad_pick`) are added to the exemption set, because a menu pick normally lands within 30 s of the menu.
- Replacement budget: at most `NM_DIAG_REPLY_BUDGET` diag replies per (person, channel) per `NM_DIAG_REPLY_BUDGET_WINDOW_S`. Over budget → one `"Too many requests, try again in N min"` reply (logged `diag_rate_limited`), then silence for the rest of the window (no reply, row still logged). This bounds any loop the echo rail misses.
- Why exempting is safe: rail 2 exists to break ping-pong when rail 1 misses. Ping-pong needs an echoed reply to parse as a command. I3 proves a diag reply cannot. The budget is the backstop if I3 is ever broken by a parser change.

### 6.2 Message length per channel
- One cap for all channels, `NM_DIAG_MAX_REPLY_CHARS = 900`, sized under the tightest channel: Pushover's message limit (1024 chars per the Pushover API docs; builder verifies at https://pushover.net/api and records it in the README, UNVERIFIED here). WhatsApp via ha-wa-bridge and BlueBubbles have no limit near this (UNVERIFIED; 900 is far below any plausible one). One knob avoids per-channel combinatorics.
- The renderer prioritises: problems first (unlocked, open, unavailable, non-nominal), then the rest; truncation drops the "all fine" tail.

### 6.3 Authorization
- Unchanged allowlist: only NM-configured persons reach the parser (§1.1). Diag answers go to every configured NM person who texts it (Open question Q3 asks whether to restrict to a subset).
- Companion: `_handle_companion_action` passes `person_id=None`, and `_log_and_reply` only sends when `person_id` is set (`:4017`), so Companion never gets a reply today, even for STATUS_URA. Diag over Companion is therefore out of scope; this pre-existing gap gets its own card (not fixed here).
- Pushover: same parser, so diag works if Pushover replies arrive; whether the Pushover reply webhook carries text in practice is UNVERIFIED (D0 counts rows).

### 6.4 Echo
- Rail 1 unchanged and still first. Diag replies are recorded in the outbound ring by the existing senders (proof-of-send, `:2349`, `:2392`).
- The send rail must NOT fire for `_send_reply` (else the menu reply closes its own window). `menu_safe=True` is passed only from `_send_reply`; an AST test pins that `_send_reply` is the sole caller passing it.

---

## 7. Deliverables

### D0 — Read-only probe (go/no-go gate; measure before build)
One-shot script (`scripts/probes/nm_diag_inputs_probe.py`, run by `ura-prober` via `ssh ha "python3 -"`), no writes:
1. `notification_inbound` last 60 days: rows by `channel` × `parsed_command`, and by `person_id`. Answers: does operator iMessage inbound arrive at all (self-send, NM-BB-CHATGUID-SELFSEND-1)? Does Pushover inbound exist?
2. Security coordinator options: contents of `security_lock_entities` / `security_garage_entities`; are the two lockout locks present?
3. Live state + `last_updated` age for every entity §3 reads (5 locks, 2 covers, 3 climate entities and their `ac_load_sensor`s, Envoy SOC/solar/net entities, all `*_unavailable_entities` sensors), and the count of rooms missing that sensor.
4. The 7-day share of time `hvac_action == cooling` per zone vs `ac_load_sensor` kW > 0.3, to confirm the "running" source choice.
- **Gate:** if (1) shows zero operator iMessage inbound in 60 days, D3's iMessage leg ships but its Live criterion moves to WhatsApp, and the README states iMessage inbound is blocked on NM-BB-CHATGUID-SELFSEND-1. If (2) shows lockouts absent, `garage` reports covers only plus a note, pending Q2.
- **Acceptance:** report pasted into this doc's §11 before D1 starts.

### D1 — `house_status.py` shared read-only module
New file `custom_components/universal_room_automation/house_status.py`. Functions `doors(hass)`, `garage(hass)`, `who(hass)`, `hvac(hass)`, `energy(hass)`, `alerts(hass, nm)`, `health(hass)`; each returns a frozen dataclass `StatusResult(item, as_of, fields: list[Field], problems: int)` where `Field(label, value, unit, source, age_s, note)`. `render(result, max_chars) -> str`. Every coordinator read is guarded (missing coordinator / getter raises → field value `unknown`, note `source unavailable`); a function never raises. `async` only where a DB read is needed (`alerts`).
- **Verify:** each function with a fully-mocked hass returns the documented fields; missing coordinator → `unknown`, never a default like `away` or `0`.
- **Verify:** module is display-only: AST lint finds no `async_call`, `services.`, `async_fire`, `async_dispatcher_send`, `database.log_`/`save_`/`execute(` write, no `async_create_task`, no assignment to any coordinator attribute.
- **Verify:** `render` never emits a single line (always contains `\n`) and respects `max_chars`, problems first.
- **Test:** `quality/tests/test_house_status.py::test_doors_reads_security_lists`, `::test_house_state_unknown_when_manager_missing`, `::test_hvac_running_from_load_sensor_not_hvac_action`, `::test_energy_solar_uses_staleness_gated_getter`, `::test_alerts_unacked_age_bounded`, `::test_health_resolves_by_unique_id`, `::test_module_is_read_only_ast_lint`, `::test_render_cap_and_problem_first`.
- **Live:** none directly (exercised through D3).

### D2 — Menu window + two rails in NM
RAM `self._diag_windows: dict[tuple[str, str], datetime]` (opened_at); `self._diag_send_epoch: int` bumped by the send rail; each window stores the epoch at open; a digit resolves only if `window.epoch == current epoch`, age < `NM_DIAG_MENU_WINDOW_S`, and `_alert_state is IDLE`. Send rail: first statement of the four senders, `if not menu_safe: self._diag_send_epoch += 1` (sync, before dry-run return and before any await).
- **Verify:** `diag`, then CRITICAL `async_notify` to anyone, then `1` → legacy ack path ("CRITICAL alert requires safe word.").
- **Verify:** `diag`, alert state ALERTING (set directly), `1` → legacy.
- **Verify:** `diag` then `1` with IDLE and no send → doors answer; `diag` then `1` after window expiry → legacy ("No active alerts.").
- **Verify:** dry-run active: a dry-run send still bumps the epoch.
- **Test:** `quality/tests/test_nm_diag_menu.py::test_digit_after_critical_send_is_ack` (send rail, IDLE state kept by patching `_enter_alerting` to a no-op to isolate the rail), `::test_digit_while_alerting_is_ack` (state rail with no send), `::test_digit_in_window_idle_runs_item`, `::test_window_expiry_restores_legacy`, `::test_reply_send_does_not_close_window`, `::test_window_per_person_and_channel`, `::test_restart_closes_windows` (fresh NM instance), `::test_only_send_reply_passes_menu_safe_ast`, `::test_every_text_sender_bumps_epoch_ast` (enumerates `_send_*` functions with a text payload).
- Mutation anchors (Review C): deleting the state-rail check must fail `test_digit_while_alerting_is_ack`; deleting the bump in any ONE sender must fail a per-sender parametrized case of `test_digit_after_critical_send_is_ack[whatsapp|imessage|pushover|companion]`.
- **Live:** see D3.

### D3 — Diag dispatch in `_process_inbound_reply`
Insert per §2.2. Silence exemption. Rate exemption + budget. Help line. Counter key `diag`. `log_inbound` row per diag.
- **Verify:** every non-diag golden input (the full `RESPONSE_COMMANDS` key set, safe word, `duke 2h`, unknown with and without context, silenced variants) produces identical return text and identical recorded calls before vs after (I4).
- **Verify:** while silenced, `doors` answers.
- **Verify:** safe word equal to `doors` (configured) → safe-word branch wins.
- **Verify:** `diag` twice within 30 s → both replied (rail-2 exemption); the 11th diag reply in the budget window → one over-budget reply, then silence.
- **Verify (I2):** hass mock records every service call: across all diag tokens × all channels, the only calls are `whatsapp.send_message` / `bluebubbles.send_message` / pushover notify for the reply; DB mock sees only `log_inbound`.
- **Verify (I3):** for every item, feed `"URA\n" + reply` and `"*URA*\n" + reply` back as inbound with the echo ring cleared → no command resolves (returns "" or the unknown path), no service call.
- **Test:** `quality/tests/test_nm_diag_dispatch.py::test_non_diag_inputs_byte_identical_golden`, `::test_diag_answers_while_silenced`, `::test_safe_word_beats_diag_name`, `::test_rate_exempt_and_budget`, `::test_diag_tokens_call_no_service_but_reply`, `::test_echoed_reply_never_parses`, `::test_help_mentions_diag_and_alert_body_unchanged`, `::test_unknown_sender_gets_nothing`.
- **Live (discriminating):**
  1. Operator texts `diag` on WhatsApp → menu arrives; `notification_inbound` gains a row `parsed_command='diag_menu'`, `success=1`. Under a parse miss the row would read `unknown` (or no row with no alert context), so the row's `parsed_command` discriminates.
  2. Reply `1` within the window → door list matching `ha_get_state` of each lock at that minute; row `diag_doors`. Under a rail bug the reply would be "No active alerts." and the row `ack`.
  3. Text `garage` with no window → garage answer, row `diag_garage`.
  4. `nm_routing`/log scan: zero `async_call` lines for non-notify domains in the 60 s around the test (I2 live check), zero ERROR from NM.
  5. Do NOT fire a real CRITICAL to test I1 live; I1 is proven in-suite (the README states this and why).

### D4 — Docs
- `docs/Coordinator/NOTIFICATION_MANAGER.md`: new "Inbound house queries" section (grammar, precedence, rails, knobs).
- README `docs/readmes/README_v<x>.md` with Live criteria from D3; post-restart validation table written back.
- Card the Companion no-reply gap (`NM-COMPANION-STATUS-NO-REPLY-1`) after the adjacency sweep.
- **Verify:** doc section exists and cites the knobs.

---

## 8. Knobs (numbers get names)

| Knob | Default | Rung | Why this rung | Kill-switch semantics |
|---|---|---|---|---|
| `NM_DIAG_ENABLED` | True | 1 (module const, `notification_manager.py`) | bounds a new inbound path next to a safety ack path; changing it should need review | False → `_resolve_diag` returns None always; byte-identical to pre-cycle (I4 test runs with both values) |
| `NM_DIAG_MENU_WINDOW_S` | 120 | 1 | it bounds how long digits are shadowed; the operator does not tune it by observation | 0 → digits never map to the menu (names-only, Alternative N) |
| `NM_DIAG_REPLY_BUDGET` / `NM_DIAG_REPLY_BUDGET_WINDOW_S` | 10 / 600 | 1 | loop backstop, sister of `NM_REPLY_MIN_INTERVAL_S` (also rung 1, `:272`) | budget 0 → every diag gets the over-budget reply once per window (effectively off) |
| `NM_DIAG_MAX_REPLY_CHARS` | 900 | 1 | channel protocol bound (Pushover 1024), not policy | none (a length cap has no off value) |
| `HOUSE_STATUS_AC_RUNNING_KW` | 0.3 | 1 (`house_status.py`) | display threshold for "running"; D0 item 4 sets it | none |
| `HOUSE_STATUS_STALE_S` | 300 | 1 | display "(N min old)" threshold | none |

No config-flow or entity additions (config_flow is a large state machine; nothing here needs live tuning).

---

## 9. Tier classification

**Tier 2** by the base rules: new capability, 2-3 files (`house_status.py` new, `notification_manager.py`, tests), no DB schema, no actuation. **Suggested operator elevation to the 3-review (2-DB) protocol** under the 2026-06-08 standing policy: the change sits inside `_process_inbound_reply`, the single parser for CRITICAL acks and safe words, and I1 is a safety-adjacent precedence guarantee where one missed sender is the failure mode (Bug Class #53 shape). Suggested framings: A = local correctness + golden I4; B = async/ordering of the send rail vs `_enter_alerting`, restart, dry-run, concurrency of two inbounds; C = per-site mutation (each sender's epoch bump, the state rail, the rail-2 exemption). Not Tier 3: no cost or actuation path, and the legacy path is pinned byte-identical.

---

## 10. Non-goals

- No actuation of any kind from text (no lock, unlock, garage, arm, HVAC, fan). Only the existing ack / silence / safe-word effects remain.
- No free-text / LLM answering (card option B); no OC tool wiring (the module is ready for it; OC side not built).
- No change to alert bodies, `RESPONSE_DICT_TEXT`, `CRITICAL_RESPONSE_TEXT`, routing, severities, the echo rail 1, or rail 2 for non-diag commands.
- No fix for iMessage self-send (NM-BB-CHATGUID-SELFSEND-1) or the Companion no-reply gap (new card).
- No new entities, config-flow fields, DB tables or columns. No persistence of menu windows.
- No per-room drill-down (`hvac zone 2`, `doors front`); one level only.
- No change to `_build_status_response` (`2`/`status` stays the alert summary).

---

## 11. Config-First check and marginal benefit

**Config-First:** no setting does this. NM's command set is a code constant (`RESPONSE_COMMANDS` `:244`); there is no options-flow field for extra commands; HA has no native WhatsApp/iMessage conversational agent; an HA automation could answer a WhatsApp event but would duplicate NM's sender matching, echo rails and rate limits outside URA (worse). Dashboards (ura-v8, PWA) already show all of this, which is why the value is convenience away from the app plus the OC substrate, and why the menu is kept to 7 items.

**Marginal benefit:** the names-only version captures most of the operator value; the numeric menu adds a few keystrokes saved per query at the cost of the two rails. The rails are small, single-purpose and test-pinned, and `NM_DIAG_MENU_WINDOW_S = 0` reverts to names-only with no code change, so the numeric path is built rather than parked. The shared module pays twice (NM now, OC later) and is the main reason to build this cycle at all. Parked with revival trigger: per-room drill-down and free-text, revive when D3's `notification_inbound` shows ≥ 20 diag queries in 30 days.

**D0 report:** (pending, pasted here before D1)

---

## 12. Open questions (operator only)

- **Q1** Numbers or names-only? Plan builds numbers + names (window 120 s). Say "names only" to ship with the window at 0.
- **Q2** Should the two garage remote lockouts be added to the Security coordinator's lock list? That makes `doors`/`garage` show them with zero new config, BUT the security lock check would then also evaluate them (and could try to lock them), which overlaps GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 option B. Alternative: keep them out and the answer omits lockouts until that card decides.
- **Q3** Who may query: every NM-configured person (Jaya too), or only you? Default: every configured NM person.
- **Q4** Is iMessage inbound expected to work from your phone today (BB runs as your Apple ID; your texts to the self-thread may be dropped as `isFromMe`)? D0 measures it; if it does not work, is WhatsApp-only acceptable until NM-BB-CHATGUID-SELFSEND-1 ships?
- **Q5** Menu contents: OK with exactly doors / garage / who / hvac / energy / alerts / health? (I dropped nothing; I did not add weather or EV because they are not "is the house OK" questions.)
