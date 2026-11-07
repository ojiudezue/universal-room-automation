# PLANNING — Ask the house by text: `diag` menu over WhatsApp / iMessage (NM-INBOUND-HOUSE-QUERIES-1, option A)

**Card:** `NM-INBOUND-HOUSE-QUERIES-1` (`docs/planning/kanban.data.yaml:214`), fields `design_2026_11_07`, `shared_layer_2026_11_07`.
**Tier:** 2, build review ELEVATED to three framing-disjoint reviews (CRITICAL-ack parser; §9). Plan review 1 done (FIX-PLAN, `docs/reviews/code-review/nm_diag_text_menu_plan_review_1.md`); every finding folded in (§13).
**Status:** rev 2, post plan-review 1. Author: ura-planner, 2026-11-07.
**Mandatory reads done:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (read completely; the `hvac` answer displays zone state) and `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` + `docs/architecture/SENSOR_FLEET_CLASSES.md` (read completely; the `who` answer displays house state / persons). No HVAC §10 or presence §10 claim is re-asserted. Two doc facts this plan depends on are cited inline (HVAC §9.9 zone_1 status-feed lie, HVAC §9.9 "hvac_action useless on zone_1").

---

## 0. Shape in one paragraph

Texting `diag` to URA (WhatsApp or iMessage; Pushover too, same parser) returns a short numbered menu. Replying with a number (inside a short per-sender window) or a command name (any time) returns a read-only answer: `doors`, `garage`, `who`, `hvac`, `energy`, `alerts`, `health`. Answers come from a new pure read-only module `house_status.py` (functions over `hass` + coordinators that return structured data plus a short text render), so the OC agent can call the same functions as tools later. The NM change is one dispatch block inside the existing `_process_inbound_reply`; nothing in the alert path changes. The `1`/`2`/`3` conflict is resolved by two rails: a SEND rail (any non-reply NM text send closes every open menu window at send start) which is the PRIMARY and, for HIGH/MEDIUM/LOW alerts, the ONLY guard; and a STATE rail (NM alert state not IDLE keeps digits legacy) which adds defence only for CRITICAL, because `_enter_alerting` is reached only for CRITICAL (NM:2097-2099) and only after the sends (§2.3). Diag replies neither obey nor stamp rail 2's 30 s floor, so a diag query never swallows a later ack confirmation (§6.1).

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
| House state | **REUSE** | `CoordinatorManager.house_state` `manager.py:325-327` (returns a `HouseState` enum; render `.value`). NOT `PresenceCoordinator.house_state` `presence.py:1992`, which returns a fabricated `"away"` when the manager is missing (producer defect for a display: "unknown" must say unknown). |
| Census / persons | **REUSE** | `PresenceCoordinator.census_count` `presence.py:1987`; per-person `person_state_for_trust` `person_coordinator.py:130` (BLE-overrule-aware) and `PersonCoordinator.get_person_location(person_name)` `person_coordinator.py:1981` (takes the person NAME, not an entity id; file is at the package root, not under `domain_coordinators/`). |
| HVAC zones | **REUSE** | `HVACCoordinator.zone_manager` `hvac.py:996` → `ZoneManager.zones` `hvac_zones.py:420` → `ZoneState` `hvac_zones.py:128` (`current_temperature`, `target_temp_low/high`, `preset_mode`, `hvac_action`, `ac_load_sensor` `:215`). |
| Energy | **REUSE** | `BatteryStrategy.battery_soc` `energy_battery.py:1089` (Envoy → LKG → cloud resolver; memory `project_battery_soc_envoy_not_span`: never SPAN). Solar: `solar_production_w` `energy_battery.py:2553` (staleness-gated), NOT the raw `solar_production` `:2407`. Grid: `net_power_w` `energy_battery.py:2591` (W-normalized across kW/W firmware; NOT the raw `net_power` `:2412`; not staleness-gated, so the render shows source age, §3). Reached via `manager.coordinators.get("energy")` (pattern `time.py:139`). |
| Anomalies | **REUSE** | Each coordinator's `anomaly_detector.get_sensor_state()` (`coordinator_diagnostics.py:1314`; detectors at `hvac.py:1822`, `security.py:786`, `presence.py:2702`, `safety.py:1244`, `music_following.py:247`); NM `anomaly_status` `notification_manager.py:909`. |
| Unacked criticals | **REUSE** | `database.get_active_criticals(limit=50)` `database.py:4939` (read; no age bound). The age cap is applied in `house_status` reusing `NM_RECOVERY_MAX_AGE_H` (NM:324, 24 h; 0 = no bound) with the same semantics as `_recovery_row_is_stale` (NM:5157); the builder calls that static method rather than re-deriving it. |
| Unavailable entities per room | **REUSE** | `UnavailableEntitiesSensor` `sensor.py:1806` (state = count, attrs `unavailable_actuators`, `actuator_count`, `sensor_count` `:2055-2066`), unique_id `{entry_id}_unavailable_entities` (`entity.py:34`). Resolved through the entity registry by unique_id (ROOM-SWITCH-LOOKUP-BY-NAME-1 pattern, presence STATE_OF_PLAY §4.5), never by slug. |
| Integration problems | **REUSE** | HA issue registry entries for `DOMAIN` (URA creates repairs, 10 `async_create_issue` sites) + NM `channel_status` `notification_manager.py:810`. |
| Menu window state | **BUILD (NEW, RAM only)** | No existing per-sender conversational state in NM (grepped `_menu`, `_window`, `_pending_reply`, `_conversation`: only the safe-word perimeter window `_perimeter_silence_until` `:446`, a different concept). RAM dict, not persisted: a restart closes every window (correct direction). |
| Close-on-send hook | **BUILD (NEW, 4 sites)** | Added at the top of the four text senders `_send_pushover` `:2208`, `_send_companion` `:2255`, `_send_whatsapp` `:2311`, `_send_imessage` `:2355` (dry-run returns at `:2226`, `:2266`, `:2329`, `:2372`). See §4 enumeration. |

### 1.2 Greps run (reproduce)

```
grep -n "RESPONSE_COMMANDS\|NM_ECHO\|NM_REPLY_\|_messaging_suppressed\|_silence_until" domain_coordinators/notification_manager.py
grep -n "_send_imessage(\|_send_whatsapp(\|_send_pushover(\|_send_companion(" domain_coordinators/notification_manager.py
   → callers: 1909/1931/1958/1980 (async_notify), 2944-2966 (repeat), 4052-4065 (_send_reply), 5002-5049 (digest), 5359-5374
grep -n "_alert_state = AlertState" domain_coordinators/notification_manager.py   → ALERTING set at :2651 inside _enter_alerting (:2592), called :2099
grep -rn "house_status\|context_pack\|house_snapshot" custom_components/   → none
grep -n "CONF_SECURITY_LOCK_ENTITIES\|CONF_SECURITY_GARAGE_ENTITIES" const.py domain_coordinators/security.py
grep -n "def battery_soc\|def solar_production\|def net_power" domain_coordinators/energy_battery.py   → net_power :2412 (raw), net_power_w :2591 (W-normalized)
grep -n "_last_reply_at" domain_coordinators/notification_manager.py   → init :476, read :4019, stamp :4032 (stamped on every non-rate-limited send)
grep -n "_active_alert_data = " domain_coordinators/notification_manager.py   → set only at :2656 (_enter_alerting) and recovery :5278/:5311
grep -n "async_call(" domain_coordinators/notification_manager.py   → 2249, 2305, 2342, 2385 (the four senders), 2408/3923 tts, 2485 light, 5708 halo
grep -rn "services.async_call" aggregation.py button.py   → aggregation.py:1602 legacy notify.<CONF_NOTIFY_SERVICE>; button.py:482 export notify (out of scope, §4)
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

While `_alert_state` is not IDLE, `diag` returns the menu with the numbers removed and a header line instead:
```
Alert active: numbers mean ack/status/silence.
Use words: doors garage who hvac
energy alerts health
```
and does NOT open a window (a digit sent then is legacy by both rails anyway; not opening keeps the state simple).

Exact whole-text match only. No first-token, substring or fuzzy parse (load-bearing for §6.3).

**Post-close digit notice (MEDIUM-6, default chosen):** if a bare `1`/`2`/`3` arrives while the sender's window was closed by the SEND rail within the last `NM_DIAG_CLOSED_NOTICE_S` (window record still present, epoch mismatch), and `_alert_state is IDLE` with no `_active_alert_data` (i.e. no alert reply is being expected), the digit is NOT acted on. NM replies `Menu closed: an alert was just sent. Reply diag to reopen, or use words (ack, silence).`, logs `diag_closed_notice`, and drops the window record. This turns the silent-`3`-silences case into a visible prompt. If an alert reply IS expected (state not IDLE or `_active_alert_data` set), the digit goes to the legacy path unchanged (I1). Note that for non-CRITICAL alerts the state is IDLE, so a `3` meant as "silence" right after a HIGH alert gets the notice and costs one extra text (`silence`); this is the accepted price, recorded in §2.3.

### 2.2 Precedence inside `_process_inbound_reply` (new order; existing steps unchanged)

0. **NEW, first statement of `_process_inbound_reply`, before any await:** `epoch_at_entry = self._diag_send_epoch` and `now_at_entry = dt_util.utcnow()` (HIGH-1). Every window write and every epoch comparison on this inbound uses these locals, never a re-read of `self._diag_send_epoch`.
1. Echo rail 1 (`:3553`) — unchanged.
2. `_messaging_suppressed` (`:3576`) — unchanged.
3. Counters, safe-word-window pre-parse, `_match_safe_word` (`:3580-3650`) — unchanged.
4. **NEW:** `diag = None if (is_safe_word or person_id is None or not NM_DIAG_ENABLED) else self._resolve_diag(text, person_id, channel, epoch_at_entry, now_at_entry)`. Synchronous, no await, no I/O. Returns an item key, `"menu"`, `"bad_pick"`, `"closed_notice"`, or `None`. **`_resolve_diag` is where the window dict is written** (on `menu`: `self._diag_windows[(person_id, channel)] = (now_at_entry, epoch_at_entry)`, only when `_alert_state is IDLE`); it runs before the first await on the path, so a send racing the reply bumps the epoch AFTER the stored value and closes the window (HIGH-1 repro). A `diag` resent inside an open window refreshes both `opened_at` and the stored epoch (to `epoch_at_entry`). `person_id is None` (Companion) skips diag entirely (LOW-10).
   - A digit resolves to an item ONLY IF the (person, channel) window exists AND `stored_epoch == epoch_at_entry` (send rail) AND `now_at_entry - opened_at < NM_DIAG_MENU_WINDOW_S` AND `self._alert_state is AlertState.IDLE` (state rail). Epoch mismatch within `NM_DIAG_CLOSED_NOTICE_S` with no alert expected → `"closed_notice"` (§2.1). Otherwise `None` → the digit falls through to `RESPONSE_COMMANDS` exactly as today.
   - A name or `diag` resolves regardless of window and alert state.
5. Silence gate (`:3651`) — the exemption list gains "diag is not None".
6. Safe-word branch (`:3674`) — unchanged.
7. **NEW:** `if diag is not None:` → build answer via `house_status`, `_log_and_reply(..., f"diag_{item}", ...)`, return. Placed BEFORE `if command == "ack"`.
8. ack / status / silence / help / unknown — unchanged (help gains one line).

### 2.3 The safety case: send rail primary, state rail CRITICAL-only defence (rev 2, MEDIUM-3)

What a digit collision can actually cost (verified): `_active_alert_data` is set only in `_enter_alerting` (NM:2656) and recovery (NM:5278, 5311), and `_enter_alerting` is called only for `Severity.CRITICAL` (NM:2097-2099). So legacy `1` never acks anything by text: with a CRITICAL active it replies "requires safe word" (NM:3806), otherwise "No active alerts." Legacy `2` is a status text. **The only digit with a real effect is `3` = silence** (NM:3830-3836, 30 min suppression of non-CRITICAL, NM:1536-1542). So I1's stakes are: (a) `3` must keep silencing whenever the person plausibly means silence, and (b) `1`/`2` reply-text fidelity during a CRITICAL (the "requires safe word" prompt must not be replaced by a door list).

- **Send rail (primary, four sites).** Every HIGH/MEDIUM/LOW alert carries `Reply: 1=Ack 2=Status 3=Silence` (NM:1740-1742) but leaves `_alert_state` IDLE. For those alerts the send rail is the ONLY guard. It closes all windows synchronously at the TOP of each of the four senders, before the dry-run return and before any await. Its coverage is therefore the enforced invariant: an NM-wide AST test (D2 `test_no_text_service_call_outside_four_senders`) fails if any `hass.services.async_call` whose domain is `whatsapp`, `bluebubbles`, `notify`, or the pushover service (or a non-literal domain variable) appears outside `_send_pushover`, `_send_companion`, `_send_whatsapp`, `_send_imessage`, with an explicit allowlist for the known non-text calls (`tts` at :2408 / :3923, `light` :2485, `HALO_DOMAIN` :5708). A future emitter that bypasses the senders breaks this test, not the house.
- **State rail (CRITICAL-only defence in depth, one site).** Digits keep legacy meaning while `_alert_state is not IDLE`. This matters only for CRITICAL (ALERTING / REPEATING / COOLDOWN / RE_EVALUATE) and covers e.g. a window opened during a CRITICAL repeat lull; it is inert for every other severity. Rev 1's claim that the two rails are "independent" is withdrawn: for non-CRITICAL they are not; the send rail plus its AST test carry the load.
- **Out of scope by name (LOW-9):** `aggregation.py:1602` (zone safety alert via legacy `notify.<CONF_NOTIFY_SERVICE>`) and `button.py:482` (export notify) call `notify.*` outside NM. They append no response dictionary, so they do not invite digits and do not bump the epoch. If either ever gains `RESPONSE_DICT_TEXT`, it must route through NM.

Residuals accepted by name:
1. Pre-emptive silence: inside an open window with no alert sent since, `3` means "who". Word `silence`/`stop`/`mute` still silences.
2. Post-close `3` (MEDIUM-6): after a HIGH alert closes the window, `3` within `NM_DIAG_CLOSED_NOTICE_S` gets the "menu closed" notice instead of silencing; the person sends `silence` (one extra text). After `NM_DIAG_CLOSED_NOTICE_S`, `3` is plain legacy silence again.
3. `1` with IDLE today replies "No active alerts" and `2` "All clear"; no effect lost when the menu shadows them.

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
| garage: cover state + lockout | HA `cover.*` for ids in `_garage_entities` (`security.py:560`); the two lockout locks read DIRECTLY from `hass.states` by a module tuple `HOUSE_STATUS_GARAGE_LOCKOUT_ENTITIES` in `house_status.py` (default Q2: NOT added to the SC lock list, so the security lock check never evaluates or locks them) | Card GARAGE-REMOTE-LOCKOUT-SCHEDULE-1: whether ratgdo lockout blocks the keypad is UNVERIFIED physically; the answer reports the entity state only ("remotes locked out: on"), never "keypad blocked" | `house_status.garage()` | display |
| who: house state | `CoordinatorManager.house_state` `manager.py:325` | healthy path; NOT `presence.house_state` (`presence.py:1992` fabricates `away` when manager missing). Missing manager → `unknown` | `house_status.who()` | display |
| who: census | `presence.census_count` `presence.py:1987` | Census arc history: an additive derivation once double-counted residents into GUEST (CLAUDE.md producer rule origin); face recognition coverage partial. Render as "~N people (estimate)" | same | display |
| who: per person | `person_state_for_trust` `person_coordinator.py:130` + `get_person_location` `:1981` | Presence STATE_OF_PLAY §3: GPS-assistive BLE overrule live; raw state otherwise | same | display |
| hvac: temp per zone | `ZoneState.current_temperature` `hvac_zones.py:140` (from climate attr `:685`) | healthy (websocket keeps temperature current, HVAC STATE_OF_PLAY §5) | `house_status.hvac()` | display |
| hvac: range | `target_temp_low/high` `hvac_zones.py:142-143` | Carrier status-feed setpoints can be stale (HVAC §5 "status feed's setpoints go stale"); render "set" not "target confirmed" | same | display |
| hvac: preset | `ZoneState.preset_mode` (adapter `preset_of_for`, HVAC §4.4) | **Known producer defect:** zone_1 status feed reads `home` while physically `away` (HVAC §9.9). Render as "thermostat reports <preset>" | same | display |
| hvac: running | **NOT `hvac_action`**: HVAC §9.9 records `hvac_action` on zone_1 as "useless (cooling on every row)". Use the zone's `ac_load_sensor` (`hvac_zones.py:215`) kW > a threshold → "running"; no load sensor → omit the field ("running: not measured") | UNVERIFIED-LIVE: load sensors present on all 3 zones (nudge thresholds exist per zone, HVAC §6, which implies they do) | same | display |
| energy: SOC | `BatteryStrategy.battery_soc` `energy_battery.py:1089` (Envoy → LKG ≤5 min → cloud) | Envoy flapping history (memory `project_session_pickup_2026_09_23`); resolver handles it; None → "unknown" | `house_status.energy()` | display |
| energy: solar now | `solar_production_w` `energy_battery.py:2553` (stale CT → None) | ENVOY-PRODUCTION-STALE-1 gate present | same | display |
| energy: grid now | `net_power_w` `energy_battery.py:2591` (W-normalized via `_read_power_w`, sign + import / − export) | Unit-safe; NOT staleness-gated. Render with the source entity's age when > `HOUSE_STATUS_STALE_S` | same | display |
| alerts: NM state | `self._alert_state`, `_active_alert_data` (NM) | healthy | `house_status.alerts()` (called from NM with NM passed in) | display |
| alerts: unacked criticals | `database.get_active_criticals` `database.py:4939` | Memory NM-RECOVERY-AGEBOUND-1: an unbounded backlog of historical unacked CRITICALs existed (326 rows). Render count + newest 3 with age; drop rows older than `NM_RECOVERY_MAX_AGE_H` (NM:324) via `_recovery_row_is_stale` (NM:5157) so a stale backlog is not reported as active | same | display |
| alerts: anomalies | each `coordinator.anomaly_detector.get_sensor_state()` | v5.103.25 made blind metrics read `partial`/`learning` instead of `nominal`; render non-nominal only | same | display |
| health: unavailable | per-room `sensor.<room>_unavailable_entities` state + `actuator_count` (registry lookup by unique_id) | healthy if every room has the sensor (UNVERIFIED-LIVE count) | `house_status.health()` | display |
| health: integration problems | HA issue registry for `DOMAIN`; NM `channel_status` | healthy | same | display |

Consumers of the new module: NM diag (this cycle) only. OC is a named future consumer (non-goal here). No trust decision anywhere reads `house_status`. I2 is enforced by the D3 behavioural service-call / DB recorder test (the real guard); the D1 AST lint is a shallow syntax check of `house_status.py` only. Getters it calls may write RAM stamps (e.g. `solar_production_w` LKG stamps, `energy_battery.py:2577-2580`), which is benign; I2 is stated as "no actuation and no persistent write" (LOW-7).

---

## 4. Emission / decision-site enumeration

**Inbound decision sites (where a text becomes an effect):** exactly one, `_process_inbound_reply` `:3547`. Entry points into it: `:3389`, `:3393`, `:3400` (companion, person None), `:3415` (WA), `:3437` (Pushover), `:3475` (BB). Grep `"_process_inbound_reply("` must return exactly these 6 calls plus the definition after the build.

**Outbound text sends (send-rail sites):** every NM text send goes through one of four senders. Callers today:
- `async_notify` `:1909, :1931, :1958, :1980`
- repeat cycle `:2944, :2951, :2959, :2966`
- `_send_reply` `:4052, :4056, :4061, :4065` (the ONLY caller allowed to pass `menu_safe=True`)
- daily digest `:5002-5049`
- `async_test_notification` `:5340` (calls `:5359 / :5364 / :5369 / :5374`)

The rail lives in the four sender bodies (`:2208`, `:2255`, `:2311`, `:2355`), so all callers are covered, including future ones. TTS (`_send_tts`) and wall panels do not reach a phone and are not rail sites (noted, not gated). Enforcement is D2 `test_no_text_service_call_outside_four_senders` (MEDIUM-3; explicit allowlist of the four function names, not a payload-shape rule) plus `test_each_sender_bumps_epoch_first_ast` (the bump is the first statement of each of the four). Non-NM `notify.*` callers `aggregation.py:1602` and `button.py:482` are out of scope by name (§2.3).

**Service calls reachable from inbound text (I2 surface):** today `async_acknowledge` (ack / safe word), `_silence_until` assignment (silence), `_ack_all_criticals_and_release`, perimeter-window open (safe-word window), `_announce_ack` (TTS), `async_notify` LOW notes from the safe-word window, and the reply senders. The diag branch adds NONE: only `house_status` reads plus `_log_and_reply`.

---

## 5. Falsifiable invariants

- **I1 (alert digits never shadowed):** For any inbound whose normalized text is `1`, `2` or `3`, if `_alert_state` is not IDLE at entry, OR any non-reply text send began (epoch bumped) after the epoch value captured when the sender's window was written, the text is NEVER resolved to a diag item. It is handled by the legacy `RESPONSE_COMMANDS` path with byte-identical effect and reply, except the one named case: IDLE, no `_active_alert_data`, window closed by the send rail within `NM_DIAG_CLOSED_NOTICE_S` → the "menu closed" notice (no effect, no item answer). In particular a bare `1` after a CRITICAL send began replies "requires safe word", and a `3` with any alert expected silences.
- **I1b (diag never swallows an alert reply):** A diag reply neither checks nor stamps `_last_reply_at`; therefore any ack / safe-word / silence confirmation following a diag reply is rate-limited exactly as if the diag exchange had not happened.
- **I2 (read-only):** No inbound text whose normalized form is a diag token (`diag`, `menu`, `house`, an item name, a digit resolved to an item, or a closed-notice digit) causes any actuation (`hass.services.async_call` other than the reply send through `_send_reply`), any persistent write other than the one `log_inbound` row, any NM state mutation other than the menu-window dict, the diag budget dict and the diag counters (in particular NOT `_last_reply_at`, NOT `_silence_until`), or any signal other than the existing `SIGNAL_NM_ENTITIES_UPDATE`. RAM caches written by getters (LKG stamps) are allowed.
- **I3 (no echo loop):** No diag reply body, once echoed back verbatim or with the channel's title prefix, resolves to any command (legacy or diag). Holds because every sent reply contains a newline (title prefix `URA\n` / `*URA*\n`, `:2333`, `:2377`) and all matching is exact whole-text.
- **I4 (no regression for non-diag text):** For every inbound text that is not a diag token, and for digits when no window record exists, `_process_inbound_reply` returns the same string and performs the same calls with `NM_DIAG_ENABLED = True` as with `NM_DIAG_ENABLED = False`. **Oracle (MEDIUM-5):** the False arm. The kill switch is a single early guard at step 4 (`diag = None`), so the False arm executes exactly the pre-cycle code path; the test runs each golden input through both arms on fresh NM instances and diffs return text + recorded service calls + DB calls. Expectations are never hand-written from the new code. The builder additionally asserts the False arm against a small fixture set captured once from the merge-base (`quality/tests/fixtures/nm_inbound_golden_pre_diag.json`, committed with the merge-base sha in its header) to prove the False arm really is the old code.
- **I5 (bounded reply):** No diag reply exceeds `NM_DIAG_MAX_REPLY_CHARS` after the title prefix; a truncated reply ends with `…(more: <item>)`.

Reviewer D's job: break I1 / I1b (find an IDLE-and-no-send moment where a person intends ack, or an outbound path that bypasses the four senders) and I2 (find any service call or write reachable from a diag token).

---

## 6. Rate limiting, length, authorization, echo

### 6.1 Rate limiting
- Rail 2's 30 s floor stays for everything it covers today. **Diag replies bypass rail 2 entirely (HIGH-2): they neither check nor stamp `_last_reply_at`.** Mechanism: `_log_and_reply` gains keyword-only `rail2: bool = True`; the diag branch passes `rail2=False`, which skips both the floor check and the stamp at NM:4032 (it still logs and sends). Adding `diag_*` to `NM_REPLY_RATE_LIMIT_EXEMPT_COMMANDS` (NM:280-287) is NOT the mechanism, because that set skips the check but still stamps (NM:4031-4032), and a stamped diag reply would swallow a safe-word confirmation sent within 30 s (review repro: `doors` at t0, safe word at t0+20 s → "CRITICAL alert acknowledged" dropped). The per-sender diag budget below is the diag loop bound.
- Replacement budget: at most `NM_DIAG_REPLY_BUDGET` diag replies per (person, channel) per `NM_DIAG_REPLY_BUDGET_WINDOW_S`. Over budget → one `"Too many requests, try again in N min"` reply (logged `diag_rate_limited`), then silence for the rest of the window (no reply, row still logged). The closed-notice reply counts against the budget. This bounds any loop the echo rail misses.
- Why exempting is safe: rail 2 exists to break ping-pong when rail 1 misses. Ping-pong needs an echoed reply to parse as a command. I3 proves a diag reply cannot. The budget is the backstop if I3 is ever broken by a parser change.

### 6.2 Message length per channel
- One cap for all channels, `NM_DIAG_MAX_REPLY_CHARS = 900`, sized under the tightest channel: Pushover's message limit (1024 chars per the Pushover API docs; builder verifies at https://pushover.net/api and records it in the README, UNVERIFIED here). WhatsApp via ha-wa-bridge and BlueBubbles have no limit near this (UNVERIFIED; 900 is far below any plausible one). One knob avoids per-channel combinatorics.
- The renderer prioritises: problems first (unlocked, open, unavailable, non-nominal), then the rest; truncation drops the "all fine" tail.

### 6.3 Authorization
- Unchanged allowlist: only NM-configured persons reach the parser (§1.1). Diag answers go to every configured NM person who texts it (default Q3, §12; operator can restrict).
- Companion: `_handle_companion_action` passes `person_id=None`, and `_log_and_reply` only sends when `person_id` is set (`:4017`), so Companion never gets a reply today, even for STATUS_URA. Diag over Companion is therefore out of scope; this pre-existing gap gets its own card (not fixed here).
- Pushover: same parser, so diag works if Pushover replies arrive; whether the Pushover reply webhook carries text in practice is UNVERIFIED (D0 counts rows).

### 6.4 Echo
- Rail 1 unchanged and still first. Diag replies are recorded in the outbound ring by the existing senders (proof-of-send, `:2349`, `:2392`).
- The send rail must NOT fire for `_send_reply` (else the menu reply closes its own window). `menu_safe` is a **keyword-only** parameter (`*, menu_safe: bool = False`) on the four senders, so the 20+ positional callers (e.g. `:1909`, `:5016`) are unchanged. `menu_safe=True` is passed only from `_send_reply`; an AST test pins that `_send_reply` is the sole caller passing it.
- Dry-run: diag replies are dry-run short-circuited like every send (the senders return at `:2226/:2266/:2329/:2372`), and a dry-run send still bumps the epoch. The Live criteria assume dry-run is OFF (LOW-10).

---

## 7. Deliverables

### D0 — Read-only probe (go/no-go gate; measure before build)
One-shot script (`scripts/probes/nm_diag_inputs_probe.py`, run by `ura-prober` via `ssh ha "python3 -"`), no writes:
1. `notification_inbound` last 60 days: rows by `channel` × `parsed_command`, and by `person_id`. Answers: does operator iMessage inbound arrive at all (self-send, NM-BB-CHATGUID-SELFSEND-1)? Does Pushover inbound exist?
2. Security coordinator options: contents of `security_lock_entities` / `security_garage_entities` (informational; per default Q2 the lockouts are read directly by `house_status`, not via this list).
3. Live state + `last_updated` age for every entity §3 reads (5 locks, 2 covers, 3 climate entities and their `ac_load_sensor`s, Envoy SOC/solar/net entities, all `*_unavailable_entities` sensors), and the count of rooms missing that sensor.
4. The 7-day share of time `hvac_action == cooling` per zone vs `ac_load_sensor` kW > 0.3, to confirm the "running" source choice.
- **Gate:** if (1) shows zero operator iMessage inbound in 60 days, D3's iMessage leg ships but its Live criterion moves to WhatsApp, and the README states iMessage inbound is blocked on NM-BB-CHATGUID-SELFSEND-1. If a lockout entity is missing from HA entirely, `garage` reports covers only plus "lockout: not found".
- **Acceptance:** report pasted into this doc's §11 before D1 starts.

### D1 — `house_status.py` shared read-only module
New file `custom_components/universal_room_automation/house_status.py`. Functions `doors(hass)` (SC lock list only), `garage(hass)`, `who(hass)`, `hvac(hass)`, `energy(hass)`, `alerts(hass, nm)`, `health(hass)`; each returns a frozen dataclass `StatusResult(item, as_of, fields: list[Field], problems: int)` where `Field(label, value, unit, source, age_s, note)`. `render(result, max_chars) -> str`. Every coordinator read is guarded (missing coordinator / getter raises → field value `unknown`, note `source unavailable`); a function never raises. `async` only where a DB read is needed (`alerts`).
- **Verify:** each function with a fully-mocked hass returns the documented fields; missing coordinator → `unknown`, never a default like `away` or `0`.
- **Verify (shallow lint; I2's real guard is D3's recorder test):** module source no `async_call`, `services.`, `async_fire`, `async_dispatcher_send`, `database.log_`/`save_`/`execute(` write, no `async_create_task`, no assignment to any coordinator attribute.
- **Verify:** `render` never emits a single line (always contains `\n`) and respects `max_chars`, problems first.
- **Test:** `quality/tests/test_house_status.py::test_doors_reads_security_lists`, `::test_house_state_unknown_when_manager_missing`, `::test_hvac_running_from_load_sensor_not_hvac_action`, `::test_energy_solar_uses_staleness_gated_getter`, `::test_energy_grid_uses_net_power_w_with_age`, `::test_house_state_renders_enum_value`, `::test_person_location_called_by_name`, `::test_garage_reads_lockouts_directly_not_sc_list`, `::test_alerts_unacked_age_bounded`, `::test_health_resolves_by_unique_id`, `::test_module_is_read_only_ast_lint`, `::test_render_cap_and_problem_first`.
- **Live:** none directly (exercised through D3).

### D2 — Menu window + two rails in NM
RAM `self._diag_windows: dict[tuple[str, str], tuple[datetime, int]]` (opened_at, epoch captured at inbound entry); `self._diag_send_epoch: int` bumped by the send rail. The window is written ONLY inside the synchronous `_resolve_diag`, from the `epoch_at_entry` / `now_at_entry` locals captured as the first statement of `_process_inbound_reply` (§2.2 step 0), never after an await. A digit resolves only if `stored_epoch == epoch_at_entry`, age < `NM_DIAG_MENU_WINDOW_S`, and `_alert_state is IDLE`. Send rail: first statement of the four senders, `if not menu_safe: self._diag_send_epoch += 1` (sync, before dry-run return and before any await). Stale window records are pruned lazily on lookup after `max(NM_DIAG_MENU_WINDOW_S, NM_DIAG_CLOSED_NOTICE_S)`.
- **Verify:** `diag`, then CRITICAL `async_notify` to anyone, then `1` → legacy ack path ("CRITICAL alert requires safe word.").
- **Verify:** `diag`, alert state ALERTING (set directly), `1` → legacy.
- **Verify:** `diag` then `1` with IDLE and no send → doors answer; `diag` then `1` after window expiry → legacy ("No active alerts.").
- **Verify:** dry-run active: a dry-run send still bumps the epoch.
- **Verify (HIGH-1):** `diag` where the patched `_send_reply` bumps `_diag_send_epoch` (simulating a CRITICAL send landing during the menu reply's await) → a later `1` is legacy, not doors.
- **Verify (MEDIUM-6):** `diag`, a HIGH `async_notify` (state stays IDLE), then `3` within `NM_DIAG_CLOSED_NOTICE_S` → closed-notice reply, `_silence_until` unchanged; same `3` after the notice window → legacy silence; same `3` with `_alert_state` ALERTING → legacy.
- **Verify:** `diag` while ALERTING → the "Alert active: use words" menu and no window record.
- **Test:** `quality/tests/test_nm_diag_menu.py::test_digit_after_critical_send_is_ack` (send rail, IDLE state kept by patching `_enter_alerting` to a no-op to isolate the rail), `::test_digit_while_alerting_is_ack` (state rail with no send), `::test_digit_in_window_idle_runs_item`, `::test_window_expiry_restores_legacy`, `::test_reply_send_does_not_close_window`, `::test_window_per_person_and_channel`, `::test_restart_closes_windows` (fresh NM instance), `::test_only_send_reply_passes_menu_safe_ast`, `::test_menu_safe_is_keyword_only`, `::test_each_sender_bumps_epoch_first_ast` (explicit allowlist of the four names), `::test_no_text_service_call_outside_four_senders` (NM-wide AST, MEDIUM-3; replaces rev 1's `test_every_text_sender_bumps_epoch_ast`), `::test_epoch_captured_before_first_await` (HIGH-1: `_send_reply` patched to bump the epoch), `::test_digit_after_noncritical_send_gets_closed_notice`, `::test_closed_notice_expires_to_legacy`, `::test_menu_while_alerting_has_no_numbers`, `::test_diag_resend_refreshes_window`, `::test_companion_person_none_skips_diag`.
- Mutation anchors (Review C): deleting the `rail2=False` pass-through must fail `test_doors_then_safe_word_20s_confirmation_sent`; deleting the state-rail check must fail `test_digit_while_alerting_is_ack`; moving the epoch capture below the first await must fail `test_epoch_captured_before_first_await`; deleting the bump in any ONE sender must fail a per-sender parametrized case of `test_digit_after_critical_send_is_ack[whatsapp|imessage|pushover|companion]`.
- **Live:** see D3.

### D3 — Diag dispatch in `_process_inbound_reply`
Insert per §2.2. Silence exemption. Rate exemption + budget. Help line. Counter key `diag`. `log_inbound` row per diag.
- **Verify:** every non-diag golden input (the full `RESPONSE_COMMANDS` key set, safe word, `duke 2h`, unknown with and without context, silenced variants, digits with no window) produces identical return text and identical recorded calls with `NM_DIAG_ENABLED` False vs True, and the False arm matches the merge-base fixture (I4 oracle, §5).
- **Verify (HIGH-2 / I1b):** `doors` at t0, then the safe word at t0+20 s with a CRITICAL active → the "CRITICAL alert acknowledged" confirmation IS sent; same for `silence` and `ack` at t0+20 s; `_last_reply_at` has no entry after a diag-only exchange.
- **Verify:** while silenced, `doors` answers.
- **Verify:** safe word equal to `doors` (configured) → safe-word branch wins.
- **Verify:** `diag` twice within 30 s → both replied (rail-2 exemption); the 11th diag reply in the budget window → one over-budget reply, then silence.
- **Verify (I2):** hass mock records every service call: across all diag tokens × all channels, the only calls are `whatsapp.send_message` / `bluebubbles.send_message` / pushover notify for the reply; DB mock sees only `log_inbound`.
- **Verify (I3):** for every item, feed `"URA\n" + reply` and `"*URA*\n" + reply` back as inbound with the echo ring cleared → no command resolves (returns "" or the unknown path), no service call.
- **Test:** `quality/tests/test_nm_diag_dispatch.py::test_non_diag_inputs_byte_identical_golden`, `::test_diag_answers_while_silenced`, `::test_safe_word_beats_diag_name`, `::test_rate_exempt_and_budget`, `::test_diag_reply_does_not_stamp_last_reply_at`, `::test_doors_then_safe_word_20s_confirmation_sent`, `::test_doors_then_silence_20s_confirmation_sent`, `::test_golden_oracle_enabled_false_vs_true`, `::test_golden_false_arm_matches_merge_base_fixture`, `::test_diag_tokens_call_no_service_but_reply`, `::test_echoed_reply_never_parses`, `::test_help_mentions_diag_and_alert_body_unchanged`, `::test_unknown_sender_gets_nothing`.
- **Live (discriminating):**
  1. Operator texts `diag` on WhatsApp → menu arrives; `notification_inbound` gains a row `parsed_command='diag_menu'`, `success=1`. Under a parse miss the row would read `unknown` (or no row with no alert context), so the row's `parsed_command` discriminates.
  2. Reply `1` within the window → door list matching `ha_get_state` of each lock at that minute; row `diag_doors`. Under a rail bug the reply would be "No active alerts." and the row `ack`.
  3. Text `garage` with no window → garage answer, row `diag_garage`.
  4. `nm_routing`/log scan: zero `async_call` lines for non-notify domains in the 60 s around the test (I2 live check), zero ERROR from NM.
  5. Precondition for 1-4: NM dry-run OFF. Channel: WhatsApp (default Q4 if D0 shows no operator iMessage inbound).
  6. Do NOT fire a real CRITICAL to test I1 live; I1 is proven in-suite (the README states this and why).

### D4 — Docs
- `docs/Coordinator/NOTIFICATION_MANAGER.md`: new "Inbound house queries" section (grammar, precedence, rails, knobs).
- README `docs/readmes/README_v<x>.md` with Live criteria from D3; post-restart validation table written back.
- Card the Companion no-reply gap (`NM-COMPANION-STATUS-NO-REPLY-1`) after the adjacency sweep.
- **Verify:** doc section exists and cites the knobs.

---

## 8. Knobs (numbers get names)

| Knob | Default | Rung | Why this rung | Kill-switch semantics |
|---|---|---|---|---|
| `NM_DIAG_ENABLED` | True | 1 (module const, `notification_manager.py`) | bounds a new inbound path next to a safety ack path; changing it should need review | **the only true kill switch.** False → step 4 yields `diag = None` always; byte-identical to pre-cycle (it is the I4 oracle) |
| `NM_DIAG_MENU_WINDOW_S` | 120 | 1 | it bounds how long digits are shadowed; the operator does not tune it by observation | 0 → digits never map to the menu (names-only, Alternative N); names still work |
| `NM_DIAG_CLOSED_NOTICE_S` | 300 | 1 | how long after a send-rail close a bare digit gets the "menu closed" notice instead of acting (MEDIUM-6); a safety-adjacent UX bound | 0 → no notice; post-close digits go straight to legacy (rev 1 behaviour) |
| `NM_DIAG_REPLY_BUDGET` / `NM_DIAG_REPLY_BUDGET_WINDOW_S` | 10 / 600 | 1 | loop backstop, sister of `NM_REPLY_MIN_INTERVAL_S` (also rung 1, `:272`) | NOT a kill switch: budget 0 means the first diag of each window gets the over-budget reply and the rest get nothing. Use `NM_DIAG_ENABLED` to turn diag off (LOW-10) |
| `NM_DIAG_MAX_REPLY_CHARS` | 900 | 1 | channel protocol bound (Pushover 1024), not policy | none (a length cap has no off value) |
| `HOUSE_STATUS_AC_RUNNING_KW` | 0.3 | 1 (`house_status.py`) | display threshold for "running"; D0 item 4 sets it | none |
| `HOUSE_STATUS_STALE_S` | 300 | 1 | display "(N min old)" threshold | none |
| `HOUSE_STATUS_GARAGE_LOCKOUT_ENTITIES` | (`lock.konnected_f0f5bd523b00_lock`, `lock.ratgdov25i_dbfe2a_lock_remotes`) | 1 (`house_status.py`) | default Q2: read directly, not via SC config; ids verified in D0 item 3 | empty tuple → garage omits lockouts |

No config-flow or entity additions (config_flow is a large state machine; nothing here needs live tuning).

---

## 9. Tier classification

**Tier 2, build review ELEVATED to three framing-disjoint reviews** (2026-06-08 standing policy; recorded here as the decision for this cycle, plan review 1 concurred). Trigger: the change sits inside `_process_inbound_reply`, the single parser for CRITICAL acks and safe words; I1/I1b are safety-adjacent precedence guarantees where one missed sender, one mis-ordered capture, or one stamped reply is the failure mode (Bug Class #53 shape, plus the HIGH-1/HIGH-2 shapes found in plan review). Framings: **A** = local correctness + I4 golden oracle + closed-notice logic; **B** = async/ordering: epoch capture vs first await, send rail vs `_enter_alerting`, rail-2 stamp interaction, restart, dry-run, two concurrent inbounds; **C** = per-site source mutation (each sender's bump, the state rail, the step-0 capture, the `rail2=False` pass-through, the closed-notice gate) via `ura-reviewer-mutation`. Not Tier 3: no cost or actuation path, and the legacy path is pinned by the False-arm oracle. Live validation + README write-back as usual.

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

**D0 report (run 2026-11-07 by ura-builder, read-only: `ssh ha sqlite3 -readonly`, `.storage` reads, HA REST states/history with the oc_eval token):**

1. `notification_inbound`, all rows (every row is inside the last 60 days): **imessage only**, all `person.oji_udezue`: `unknown` 570, `safe_word` 37, `ack` 1 (latest 2026-11-07 16:48 UTC). **WhatsApp 0 rows, Pushover 0 rows, ever.** Operator iMessage inbound works (the self-thread receive copy arrives with `isFromMe=False`). The 570 `unknown` rows are mostly NM's own perimeter alert bodies echoing back (546 start "Perimeter Alert — Person Detected"), multi-line, so they can never match a diag token (I3 holds on real data). **Gate (Q4): iMessage is the Live channel; WhatsApp has no inbound evidence**, so D3 Live 1-4 run on iMessage.
2. SC options: `security_lock_entities = ['lock.doorlock_kwikset_zwave_frontentry']` (ONE lock), `security_garage_entities = ['cover.ratgdov25i_dbfe2a_door', 'cover.konnected_f0f5bd523b00_garage_door']`. Other door locks in HA but NOT in the SC list: `lock.garage_hallway_doorlock_kwikset916_zwave_garagehallway` (unlocked), `lock.master_bedroom_lock` (unlocked). Consequence: `doors` reports the front entry only until the operator adds the others in the SC options (config-first; adding them also puts them under the SC lock check, the operator's call). Not changed in code.
3. Live states: both lockout locks exist (`lock.konnected_f0f5bd523b00_lock` unlocked, `lock.ratgdov25i_dbfe2a_lock_remotes` unlocked), both covers closed. 3 climate entities live (`climate.thermostat_bryant_wifi_studyb_zone_1`, `climate.up_hallway_zone_2`, `climate.back_hallway_zone_3`). AC load sensors configured on all zones (`sensor.span_panel_ac1_power`, `_ac_2_power`, `_ac_3_power`) and they report **W, not kW**; house_status therefore reads them through the arrester's `_read_kwh_rate(warn=False)` (W to kW, kWh rejection, staleness). Envoy: `sensor.envoy_482543015950_battery` 42 % fresh; `envoy_stream_*` unavailable (resolver handles). `*_unavailable_entities`: 47/47 rooms have the registry entry, but **26 are disabled by the integration**, so only 21 report (health renders "rooms reporting 21/47").
4. 7-day time share: zone_1 `hvac_action == cooling` 0.91 vs load > 0.3 kW 0.91; zone_2 cooling 0.00 vs load 0.98; zone_3 cooling 0.00 vs load 0.00. `hvac_action` never reports cooling on zones 2/3 while zone 2 draws load, so the load-sensor source is the right one. Zone 2 shows a sustained ~0.7-0.9 kW draw (p25 734 W); whether that is compressor or blower is not established, so 0.3 kW is kept as the display default and the answer says "running", not "cooling".
5. Pushover message limit verified at https://pushover.net/api: 1024 chars (title 250). `NM_DIAG_MAX_REPLY_CHARS = 900` stands.

Go/no-go: all deliverables GO. No D0 gate stopped a deliverable.

---

## 12. Operator questions: DEFAULTS adopted (operator can override any of these)

These are planner defaults so the build is not blocked. They are NOT operator decisions; each can be overridden before build dispatch with no other plan change than the named knob or line.

| Q | Default adopted | How to override |
|---|---|---|
| Q1 numbers or names-only | **Numbered menu plus names** (window 120 s) | "names only" → `NM_DIAG_MENU_WINDOW_S = 0` |
| Q2 garage lockouts in the SC lock list | **NOT added.** `house_status` reads the two lockout locks directly (`HOUSE_STATUS_GARAGE_LOCKOUT_ENTITIES`), so the security lock check never evaluates or tries to lock them and GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 option B stays undecided | add them to SC config and empty the tuple |
| Q3 who may query | **Every NM-configured person** (Jaya included); the existing sender allowlist is the gate | add a person filter in `_resolve_diag` |
| Q4 iMessage inbound | **If D0 shows no operator iMessage inbound, ship WhatsApp-only for Live validation** until NM-BB-CHATGUID-SELFSEND-1 ships; the iMessage code path still ships (same parser) | n/a |
| Q5 menu contents | **Keep the 7 items** (doors, garage, who, hvac, energy, alerts, health) | edit `DIAG_COMMANDS` |

---

## 13. Plan review 1 → rev 2 resolution map

| Finding | Severity | Resolution in rev 2 | Where | Verified against |
|---|---|---|---|---|
| HIGH-1 epoch capture not ordered | HIGH | `epoch_at_entry`/`now_at_entry` captured as the first statement of `_process_inbound_reply`; window written only in synchronous `_resolve_diag` from those locals; test bumps the epoch inside a patched `_send_reply` | §2.2 step 0 + 4, D2, `test_epoch_captured_before_first_await` | `_log_and_reply` awaits `_send_reply` NM:4033; ALERTING set after sends NM:2097-2099 |
| HIGH-2 diag replies stamp rail 2 | HIGH | `_log_and_reply(..., rail2=False)` skips both the floor check and the stamp; exempt-set route rejected; test `doors` then safe word at +20 s | §6.1, I1b, D3 | stamp NM:4032 inside the not-rate-limited branch; exempt set NM:280-287 skips only the check |
| MEDIUM-3 safety case misdescribed | MEDIUM | Send rail restated as primary and sole guard for HIGH/MEDIUM/LOW; state rail CRITICAL-only; `3`=silence named as the effectful digit; NM-wide AST test for text `async_call` outside the four senders replaces the vague per-sender AST test | §0, §2.3, §4, D2 | `_enter_alerting` only for CRITICAL NM:2097-2099; `_active_alert_data` set only NM:2656/5278/5311; silence NM:3830-3836; `async_call` sites NM:2249/2305/2342/2385 (senders), 2408/3923/2485/5708 (non-text) |
| MEDIUM-4 raw `net_power` | MEDIUM | `net_power_w` (`energy_battery.py:2591`) with the age render kept | §1.1, §3, D1 test | `energy_battery.py:2591` docstring "normalized to W" |
| MEDIUM-5 I4 oracle unspecified | MEDIUM | Oracle = `NM_DIAG_ENABLED` False arm vs True arm on fresh instances; False arm also checked once against a committed merge-base fixture | §5 I4, D3 tests | kill switch is one early guard at step 4 |
| MEDIUM-6 post-close digit silently acts | MEDIUM | Decided: "menu closed" notice for a bare digit within `NM_DIAG_CLOSED_NOTICE_S` (300 s) of a send-rail close when no alert reply is expected; legacy otherwise. Menu text while not IDLE specified (no numbers, words only, no window) | §2.1, §2.3 residual 2, §8, D2 tests | silence effect NM:3830-3836 and non-CRITICAL leaves state IDLE |
| LOW-7 AST lint shallow | LOW | I2 restated as "no actuation, no persistent write"; D3 recorder test named as the real guard; LKG RAM stamps allowed | §3 footer, §5 I2, D1 | `energy_battery.py:2577-2580` |
| LOW-8 producer details | LOW | `get_person_location(person_name)` at package-root `person_coordinator.py:1981`; `house_state` enum `.value` (`manager.py:325-327`); criticals age-capped in `house_status` via `_recovery_row_is_stale` / `NM_RECOVERY_MAX_AGE_H` (NM:324, :5157) | §1.1, §3, D1 tests | greps in §1.2 |
| LOW-9 non-NM notify bypasses | LOW | `aggregation.py:1602` and `button.py:482` listed out of scope by name with the condition that would bring them in | §2.3, §4 | greps in §1.2 |
| LOW-10 window write site / resend | LOW | Write site = `_resolve_diag`; resend refreshes opened_at and epoch | §2.2 step 4 | — |
| LOW-10 AST "text sender" rule | LOW | Explicit four-name allowlist | §4, D2 | — |
| LOW-10 positional callers | LOW | `menu_safe` keyword-only; test `test_menu_safe_is_keyword_only` | §6.4, D2 | callers e.g. NM:1909, :5016 |
| LOW-10 Companion person None | LOW | diag skipped when `person_id is None` | §2.2 step 4, D2 test | NM:3389-3401, `_log_and_reply` sends only if person_id NM:4017 |
| LOW-10 dry-run | LOW | Stated: diag replies dry-run short-circuited; Live criteria assume dry-run off | §6.4, D3 Live 5 | dry-run returns NM:2226/2266/2329/2372 |
| LOW-10 budget 0 semantics | LOW | Documented as not a kill switch; `NM_DIAG_ENABLED` is the only one | §8 | — |
| Tier concurrence | — | Recorded as elevated to three framing-disjoint build reviews | §9 | — |

Not resolved in rev 2: none of the review findings. Still open by design: D0 results (iMessage inbound, lockout entity presence, load-sensor coverage, Pushover limit 1024 verification at https://pushover.net/api).
