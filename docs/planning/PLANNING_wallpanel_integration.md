# Plan: Halo — wall-panel presentation integration (separate, opt-in HA integration)

Status: draft plan rev 2, 2026-10-20. PLAN-REVIEW-1 (completeness) and PLAN-REVIEW-2 (adversarial build-prediction) applied 2026-10-20; see §PLAN-REVIEW-2 for the binding build contract, which overrides earlier text where they differ. Moves to the new repo once it exists.
**Rev 3, 2026-10-22: S1a (Halo) is built and live. §S1b at the end of this doc is the build contract for the URA side (card WALLPANEL-URA-NOTIFY-1). Where it differs from D1.2 / D1.3 / R2-x, §S1b wins** (targeting changed by operator 2026-10-20; re-assert trigger changed by the shipped Halo code).
Name: **Halo** — repo `~/Code/halo-panels`, HA domain `halo`, services `halo.indicate` / `halo.release` / `halo.release_all` (PLAN-REVIEW-1 2026-10-20: naming settled).

Rev 2 changes, from operator feedback ("the message passing seems fragile vs a richer interface ... are you sure 'alerts' is the best coupling?"): the fire-and-forget `ura_room_alert` bus event is replaced by a typed service API the panel integration owns, which URA calls as one more Notification Manager (NM) delivery channel. Room `alert_lights` are folded into the same NM per-room delivery step. Layers cut from 8 to 4. Panel areas are now set for all 7 panels, so that decision is gone.

## What this is

A new Home Assistant custom integration, in its own repo, that owns the 7 Kiosk Satellite (KS) wall panels as a **presentation surface**: LED ring, spoken announce, on-screen card. It exposes a small typed service API keyed by HA area. Any caller (URA, an HA automation, a script) asks a surface for an *indication*; the integration decides what the hardware actually does (priority, preemption, restore, sleep policy) and publishes state entities so callers can see the result.

URA uses it through NM. NM already resolves who should hear about a notification and delivers through channels (Pushover, companion, WhatsApp, iMessage, TTS, alert lights), each one an HA service call (`notification_manager.py:2118-2335`). Panels become one more channel, gated on the service existing.

Ownership:
- **HomeLab owns the panels** (hardware, KS install, bridge APK, screen/screensaver) until handover.
- **URA owns targeting**: which rooms a notification should reach, computed once in NM.
- **The integration owns presentation** on panels: what the ring, speaker and screen do, and how competing requests resolve.

Opt-in: no panels, no integration, and URA's NM skips the channel. URA behaves identically.

## Institutional context verified

### Inputs read in full
- `docs/planning/AUDIT_wall_panel_fit_in_ura_2026_10_20.md` (incl. §6 correction).
- `~/Code/homelab-automation/docs/wallpanel-capability-brief.md`.
- `~/Code/homelab-automation/docs/plan-wallpanel-fleet.md` (staged plan, designs 1–10).
- KS docs: `events.md`, `led-control.md`, `plugins.md`, `sdk.md` (light/native), headings of `voice-satellite.md`, `screen.md`, `alarms.md`, `intercom.md`.
- `~/Code/wall-tablet` `LedController.kt`, `MQTTManager.kt` (effects, restore, availability).
- NM channel and light engine: `notification_manager.py:1334` (`async_notify`), `:2118-2335` (channel senders), `:2335-2420` (`_trigger_alert_lights`, snapshot, `_ura_light_call`, `_restore_alert_lights`).

PRESENCE and HVAC state-of-play docs were **not** read: this plan does not touch presence fusion or HVAC. The parked touch-witness item feeds a presence input and **must** read `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` + `SENSOR_FLEET_CLASSES.md` in full before it is planned.

### Verified facts (file:line)

| Fact | Where |
|---|---|
| Room `alert_lights` never fire: `handle_safety_alert` / `handle_security_alert` have no callers | `automation.py:4895`, `:4909` (audit §6) |
| The only live alert-light path is NM's one house-wide list | `CONF_NM_ALERT_LIGHTS` `const.py:3416`; `_trigger_alert_lights` `notification_manager.py:2335`, called at `:1696` |
| NM already has a light presentation engine: per-hazard `LIGHT_PATTERNS`, pre-alert snapshot (`_store_alert_light_states` `:2369`), restore (`:2399`), dry-run gate (`:2346`), URA write mark so room manual-hold listeners ignore it (`_ura_light_call` `:2381`) | `notification_manager.py:2335-2420` |
| That engine is house-wide: one `_light_original_states` dict, one `_light_pattern_task` | `:2357`, `:2360-2366` |
| All coordinator notifications funnel through one method | `NotificationManager.async_notify` `:1334` — carries `severity`, `hazard_type`, `location`. Coordinator `NotificationAction`s route into it at `domain_coordinators/manager.py:1074`. 34 real call sites in 16 files (PLAN-REVIEW-1: grep shows 36 `async_notify(` hits; 2 are a comment/docstring at `perimeter_alert.py:7` and `notification_manager.py:3947`). |
| Every NM channel is an HA service call | `hass.services.async_call` at `:2159`, `:2215`, `:2252`, `:2295`, `:2318`, `:2395` |
| The safety dispatcher payload has no location | `SafetyHazard` `signals.py:277`; `Hazard.location` (`safety.py:155-163`) is dropped at dispatch `safety.py:2534` |
| `location` is free-form, not a room key | `"property"` `security.py:1062`, `"house"` `security.py:1387`, entity_ids `security.py:1519`/`:1599` |
| Room adjacency exists and is cached | `CONF_ADJACENT_ROOMS` `const.py:720`; cache `presence.py:3243-3290` |
| Bridge LED | MQTT `light.wallpanel_<room>_led`; effects `solid, blink, pulse, alert, notify, cycle` (`LedController.kt:46`); 4-bit RGB; `unknown` until first command; bridge keeps its own `notify` restore memory (`LedController.kt:125`) |
| KS plugin path for bridge retirement | SDK `native` + `publishLight` (`sdk.md:201-214`) |
| Fleet gaps today | Study A bridge MQTT not configured; Study B offline; Kitchen `last_interaction` can republish a stale 2024 value (brief §1–3, audit §2) |

### REUSE / NEW verdicts

| Piece | Verdict |
|---|---|
| Producer of "something needs presenting" | **REUSE** `async_notify` (`:1334`). No new event, no new signal. |
| Room targeting data | **REUSE** `CONF_ADJACENT_ROOMS` (`const.py:720`), room occupancy, zone membership. |
| Room-targeting helper | **NEW**, one function in NM. Grep of `notification_manager.py`, `presence.py`, `aggregation.py` for location→room resolution: none generic exists (`location` is free-form). |
| Light presentation for room `alert_lights` | **REUSE** NM's light engine (`:2335-2420`), made per-room (keyed snapshot + task per room). Not the dead `automation.py:4895/4909` handlers. |
| Panel channel in NM | **NEW** sender `_send_panels`, same shape as `_send_tts` (`:2308`). |
| `ura_room_alert` bus event (rev 1) | **DROPPED.** Replaced by the service call. |
| Panel registry | **NEW in the new repo**, seeded from HomeLab's Stage 2 registry (`plan-wallpanel-fleet.md:39`); keyed by HA area. |
| LED actuator | **REUSE** bridge `light.wallpanel_<room>_led`; KS plugin light later is a config swap. |

Config-first check: no setting fixes this. Adding panel LEDs to `nm_alert_lights` flashes every panel for every alert, bedrooms included, with no priority or per-panel restore. Room `alert_lights` cannot be turned on by config because nothing calls their handlers.

## 1. Coupling: what joins URA to the panels

Requirement: URA asks for something to be shown in some rooms, and later takes it back. The panel side decides how. Failure must be visible.

| Option | Not loaded | Reload / restart | Lost messages | Testability | Observability | Verdict |
|---|---|---|---|---|---|---|
| (a) Bus event `ura_room_alert` (rev 1) | Event fires into nothing, silently | Integration restart forgets all active alerts; URA never knows | Yes, no ack; a missed `cleared` leaves a ring flashing until a timeout | Each side alone; contract is an untyped dict | URA cannot see whether anything was shown | Rejected |
| (b) Typed service API owned by the integration, called as an NM channel | `has_service` false → channel skipped, NM channel health says `absent` | Leases have TTL; NM re-asserts active leases when the service registers (one listener) | Service call raises or returns; NM records the failure like any other channel | Schema-validated service; integration tested with a fake light, NM tested with a fake service | Integration publishes per-area state entities; NM gets a response | **Chosen** |
| (c) Direct Python import between integrations | Import error or `hass.data` lookup of a missing key | Holds references across a reload of the other integration (stale object, the reload-storm class URA already fought) | n/a | Couples both test suites and both release cycles | Hidden | Rejected: two repos, two release cadences, HACS installs them independently; a hard import makes URA depend on the panel repo |
| (d) Panel integration reads URA state entities (e.g. a URA "room alert" sensor per room) | Fine | Fine, state is level-triggered | None, state is durable | Good | Good | Rejected as primary: needs ~40 new URA room entities and pushes targeting/priority back into URA's entity layer. Kept as the fallback if (b) fails in review |
| (e) MQTT topics | Retained topics survive restart | Good | Low | Medium | Medium | Rejected: a second transport for a single-host problem; HA services already give typing and errors |

**Why (b).** It is the only option where the caller gets an answer (accepted, rejected, no surface in that area) and the integration holds the rich behaviour without URA knowing about panels. It is also the pattern NM already uses for every other channel, so the URA change is a sender, not a mechanism.

**The noun.** "Alert" is wrong for the interface. It names a URA concept (severity, hazard) and invites the integration to re-derive URA's meaning. The integration should accept a **lease on an indication**: "owner X asks area Y to show level L until it is released or TTL runs out." Leases make clear-by-owner, re-assert after restart and timeout-as-safety-net natural. The URA side still talks about notifications; the channel maps them to leases.

### The service API (integration-owned)

```
halo.indicate
  area_id:   one area or a list            (HA area; the registry maps area → panel)
  owner:     "ura" | any string            (who holds the lease)
  id:        string                        (stable per thing being indicated, e.g. ura:safety:water_leak:kitchen)
  level:     critical | alert | warn | info
  pattern:   optional override of the level's default effect
  ttl_s:     lease length; renewing with same owner+id extends it
  announce:  optional text (used only from slice 2)
  card:      optional {title, message} (slice 2)
  → response: {area_id: accepted | suppressed_sleep | no_surface | unavailable}

halo.release
  owner, id [, area_id]                    → releases that lease everywhere or in those areas

halo.release_all   (operator override, also a button entity)
```

State the integration publishes per panel: `sensor.halo_<area>_indication` (state = winning level or `idle`; attributes `active` leases, `last_cmd`, `last_cmd_at`) and `sensor.halo_<area>_status` (ok / led_unavailable / ks_unavailable / disabled).

Arbitration, restore and sleep live entirely in the integration: highest level wins, ties go to the newest lease, a lower lease is held (not shown) until the higher one releases, and the last release restores the pre-indication LED state (snapshot, or off if it was `unknown`).

## 2. Room `alert_lights` and panels: one presentation path

NM gains one per-room delivery step inside `async_notify`: resolve `location` to a room, compute `target_rooms` (source room + occupied adjacent + occupied same-zone rooms; house-wide for smoke/CO or unresolvable), then fan out to two presenters that share that list:
1. **Room alert_lights** — NM's existing light engine, keyed per room instead of house-wide. Reads each target room's existing `alert_lights` config.
2. **Panels** — `halo.indicate` for the target rooms' areas, if the service exists.

The existing house-wide `nm_alert_lights` list stays as is (it becomes the "house" target).

**NM vs Safety Coordinator vs both.** NM. Every coordinator, not just safety, already reaches NM through `async_notify` with `severity`, `hazard_type` and `location`, while `SIGNAL_SAFETY_HAZARD` drops location and covers only safety, so SC would need a payload change and would still miss security and the rest. Presentation is delivery, and delivery is NM's job; SC deciding which light flashes would put a second notification router in the house. SC keeps what it does today, deciding that a hazard exists and handing NM a notification.

## Layers

| Layer | What | Where | Verdict |
|---|---|---|---|
| S0 | Probe: what `location` holds in practice | URA DB, read-only | **Build first** (go/no-go for targeting) |
| S1 | First shippable slice: NM room targeting + panel channel; integration with `indicate`/`release`, LED arbiter, state entities | URA (NM) + new repo | **Build** — delivers safety/security rings |
| S2 | Room `alert_lights` through the same targeting; announce + card on panels | URA (NM) + new repo | **Build after S1 is live** |
| Parked | Touch witness, noise, night light, entertainment, bridge retirement | — | Parked with triggers below |

---

## S0 — Probe: what does `location` contain?

Read-only, one shot, over `notification_log.location` (TEXT, `database.py:1425`; written by `log_notification` `database.py:4478` from `async_notify` at `:1687`, `:1699` and the per-person/audit rows). PLAN-REVIEW-1 adequacy caveats: (1) a notify that hits the `:1405` quiet-hours early-return or the kill switch writes **no row**, so the probe undercounts night-time safety/security — supplement with a static classification of the 34 call sites (done in D1.2 note) and with `safety.py` `_sensor_locations` config (room names by construction); (2) rows repeat per channel/recipient — count DISTINCT `(timestamp, coordinator_id, hazard_type, location)`; (3) leaks are rare — 30 days may hold zero; widen to all history if <20 safety rows. Count distinct `(coordinator_id, hazard_type, location)` over 30 days and classify each as room name, zone name, `house`/`property`, entity_id, empty.

- **Verify:** a table in this doc with counts per class.
- **Gate:** if ≥80% of safety/security rows resolve to a room by (room name exact, or entity_id → area → room), S1 ships that resolver. Otherwise S1 adds the rules the data demands, and the rest go house-wide.
- **Discriminates:** a resolver that passes tests but sees mostly `house` live would make room targeting dead weight. The probe shows it before code.

## S1 — First shippable slice

### D1.1 Integration (new repo)
- HACS custom component; config flow with one entry per house and one subentry per panel: area, LED light entity, KS device, bedroom flag, enabled.
- Services `indicate`, `release`, `release_all` as above, voluptuous-validated; responses via `SupportsResponse.OPTIONAL`.
- Per-panel arbiter over leases (level priority critical > alert > warn > info > idle). One LED command per arbiter step. Restore owned here: snapshot before the first lease; always end with an explicit command (snapshot, or off if `unknown`). The builder verifies on Master whether the bridge's own `notify` restore fires after an explicit `solid`/`off`, and records it here.
- Sleep: while the configured sleep entity (PLAN-REVIEW-2: config-flow entity selector, default suggestion `binary_sensor.ura_presence_coordinator_house_sleeping`; the docstring at URA `binary_sensor.py:2322` says `binary_sensor.ura_house_sleeping`, so the builder confirms the live id, never hard-codes it) is on (read as a plain HA entity, no URA import), only `critical` and `alert` reach the LED; bedroom panels need `critical`. Boot debounce on that sensor.
- Availability: LED `unavailable` → lease kept, status shows it; on return the winning lease is re-sent once.
- Leases expire at TTL; leases are not persisted (the caller re-asserts, D1.2). PLAN-REVIEW-2: the restore *snapshot* IS persisted (see R2-3).

### D1.2 URA: NM targeting + panel channel
- One helper `_resolve_target_rooms(location, hazard_type, severity)` in NM (rules from S0). PLAN-REVIEW-1: REUSE, don't re-derive — Safety already maps entity→area→URA room in `_resolve_global_location` (`safety.py:1479`), and safety `location` is already a room name from `_sensor_locations` (`safety.py:1406-1464`) or `"unknown"`. The resolver must also split the multi-leak form `", ".join(sorted(rooms))` (`safety.py:1920`). Known non-room values: `"house"` (`security.py:1387`, `optimization.py:5030`), `"property"` (`security.py:1062`), entity_ids (`security.py:1519/1599`, `perimeter_alert.py:1530`, `button.py:2368`, `zone_monitoring_tripwire.py`), `str(kind…)` (`_stuck_signal_nm.py:227/311`), `finding.target_id` (`optimization.py:5574/5593`). 20 of 34 sites pass no location.
- One sender `_send_panels(...)`, called from `async_notify` alongside the existing channels, after NM's existing gates **except** quiet-hours/DND, which is about phones and speakers; the integration applies its own sleep rule. PLAN-REVIEW-1: this placement is under-specified as written. The quiet-hours gate at `:1405` is an **early `return`** before any channel runs, so "alongside the existing channels" (`:1675-1704`) inherits it. The plan must pick one: (i) call `_send_panels` before the `:1405` early-return but after `enabled` (`:1384`) and `_messaging_suppressed` (`:1388`) — recommended; or (ii) accept DND suppression. Dry-run (`_dry_run_active`, used by tts/lights at `:2343`) must also short-circuit `_send_panels` to `_log_dry_run(channel="panels")`. The panel row in `notification_log` is written with `channel="panels"` like `tts`/`lights` (`:1687`, `:1699`) — this is a NEW row on the switch-on path only. Skipped if `not hass.services.has_service("halo", "indicate")`.
- Level map (URA side): safety critical → `critical`; safety high/medium → `alert`; security → `warn`; info → not sent in S1.
- `id` = `ura:<coordinator>:<hazard_type>:<room or house>`. Release sites (PLAN-REVIEW-1 correction: NM has **no hazard-clear path**; the rev-2 citation was wrong). `_restore_alert_lights` has exactly three callers, none of them a clear: `:724` (messaging kill switch engaged), `:1326` (`async_stop` teardown), `:2962` (operator acknowledge). The only place NM learns a hazard ended is the post-cooldown re-evaluation `_re_evaluate_hazard` else-branch (`:3120-3124`, "Hazard cleared after cooldown"), which today restores nothing. Safety's own clear (`safety.py:3045 clear_hazard`) does not notify NM. So S1 releases on: ack (`:2962`) → release all URA leases of that episode; kill switch (`:724`) → `halo.release_all`-equivalent for owner `ura`; re-eval cleared (`:3120`) → release (new, small); `async_stop` (`:1326`) → **do not release** (leases are TTL-bounded; releasing on a URA reload would blank a live hazard). Everything else rides TTL. Choosing whether to add a real clear signal from Safety is out of scope (plan-wide non-goal: no SC change).
- NM keeps a small dict of active panel leases; when the service registers (`EVENT_SERVICE_REGISTERED` for `halo.indicate`), it re-issues them. This covers integration reload and an HA restart ordering where URA loads first.
- Channel health: `panels` reported like other channels (`_update_channel_health`): `absent`, `ok`, or last error.

### D1.3 Site enumeration (Bug Class #53 guard)
34 real `async_notify` call sites in 16 files (PLAN-REVIEW-1 re-grep 2026-10-20): `binary_sensor.py`(1), `button.py`(2), `_stuck_signal_nm.py`(2), `energy.py`(1), `hvac.py`(9), `hvac_egress.py`(1), `hvac_override.py`(1), `manager.py`(1, funnel `:1074` — fed by `NotificationAction`s from `safety.py:2580` (1) and `security.py` (9)), `notification_manager.py`(6: `:3114` re-fire, `:3700`, `:3725`, `:5079`, `:5272`, `:5380`), `optimization.py`(3), `presence.py`(1), `security.py`(1 direct), `perimeter_alert.py`(2: `:1536`, `:2975`), `switch.py`(1), `transit_validator.py`(1), `zone_monitoring_tripwire.py`(1). All are covered by the one sender inside `async_notify`; the enumeration exists to classify level per caller. The direct `_trigger_alert_lights` caller outside `async_notify` (`notification_manager.py:5070`) is decided explicitly. Release sites: every caller of `_restore_alert_lights` gets a matching release.

### Knobs (S1)
| Knob | Rung | Default | Why / kill switch |
|---|---|---|---|
| `switch.ura_nm_panel_channel` | Switch (NM) | off | Opt-in; off = no service call, NM byte-identical |
| `ROOM_TARGET_HOUSEWIDE_HAZARDS` | module const (URA) | smoke, fire, carbon_monoxide | Life-safety list; change by review |
| `number.ura_nm_panel_lease_ttl_min` | Number (URA) | 30 | Safety net for kinds with no clear; also bounds a lost release |
| `switch.halo_led` | Switch (integration) | on | Master kill: off = no LED command ever |
| per-panel `enabled` | Options flow | on | Exclude a panel |
| `LEVEL_EFFECT_MAP` | module const (integration) | critical red `alert`; alert amber `pulse`; warn blue `blink`; info white `notify` | Safety signalling changes by review. PLAN-REVIEW-1 (verified `LedController.kt:136-160`): `alert` ignores the requested colour (hard-coded red, fine for critical); `notify` is **self-terminating** (3 flashes, then reverts to the bridge's `lastSolid`) so an `info` lease is not "held" — the arbiter must treat `notify` as one-shot and not expect it to persist; colours are 4-bit (r/17), so amber must be chosen in 0-15 space; LED has no brightness (`MQTTManager.kt:163`). |
| `BEDROOM_SLEEP_MIN_LEVEL` | module const | critical | Life-safety floor while people sleep |
| `number.halo_boot_debounce_s` | Number | 180 | Ignores the boot sleep/away transient |

### Falsifiable invariants (S1)
1. **URA:** with `switch.ura_nm_panel_channel` off, or the service absent, `async_notify` produces the same channels, DB rows and side effects as before for every caller. With it on, each qualifying notify makes exactly one `indicate` call, and a smoke/CO notify always targets every panel area.
2. **Integration:** for any panel and any reachable sequence of indicate, release, TTL expiry, sleep flips and LED unavailability: (a) while a higher-level lease is active, no lower-level or restore command is sent; (b) while sleeping, nothing below the sleep floor is sent; (c) within one arbiter step after the last lease ends, exactly one restore command is sent.

Reviewer D attacks with: release of the lower lease during the higher; LED unavailable at release; sleep turning on mid-`warn`; two `critical` leases releasing out of order; the integration reloading mid-lease (NM must re-assert, the panel must not stay dark or stuck).

### Acceptance (S1)
- **Verify:** switch off → `notification_log` rows for a scripted notify identical before/after (byte-compare test).
- **Verify:** leak in Kitchen with Media occupied and adjacent → `indicate` for kitchen + media areas; Media empty → kitchen only (discriminates targeting from flash-everything).
- **Verify:** `alert` then `warn` on Kitchen → command log shows amber pulse, no blue; release `alert` → blue blink; release `warn` → restore. A last-writer-wins build would show blue at step 2; the test asserts the command log, not final state.
- **Verify:** integration unloaded and reloaded with an active lease → NM re-issues within one service-registered event; panel shows the lease again.
- **Verify:** service absent → NM channel health `panels: absent`, no exception, other channels unchanged.
- **Test (URA):** `test_panel_channel_off_is_noop`, `test_panel_channel_absent_service_skips`, `test_one_indicate_per_notify`, `test_targets_occupied_adjacent_only`, `test_smoke_always_housewide`, `test_release_on_hazard_clear`, `test_reassert_on_service_registered`.
- **Test (integration):** `test_higher_level_preempts`, `test_lower_held_not_shown`, `test_out_of_order_release`, `test_sleep_floor`, `test_bedroom_sleep_floor`, `test_restore_from_unknown_is_off`, `test_replay_after_unavailable`, `test_ttl_expiry_restores`, `test_kill_switch_sends_nothing`, `test_no_panels_is_inert`, `test_unload_removes_listeners`, plus a property test over random lease sequences checking (a)–(c).
- **Verify (PLAN-REVIEW-1):** switch on, quiet hours active, leak (HIGH) → panels get `indicate` while TTS/lights stay suppressed (proves the sender sits before the `:1405` return). Dry-run on → no service call, one `dry_run=1` row with `channel=panels`.
- **Verify (PLAN-REVIEW-1):** ack an episode → `halo.release` for its lease ids; URA reload (`async_stop`) → no release.
- **Live:** call `halo.indicate` from Developer Tools on Master with `level: info` → white notify, `sensor.halo_master_indication` shows the lease, release restores. Then with the URA switch on, operator wets a leak probe → amber pulse only on the targeted panels; NM channel health shows `panels: ok`. Status sensors show Study B `ks_unavailable` and Study A `led_unavailable`, matching the brief.

### Tier
URA side: **Tier 2-DB** (new channel inside the funnel every coordinator uses; no-op path must be byte-identical). Three framing-disjoint reviews: A targeting/level mapping, B NM no-op preservation + async/reload/re-assert ordering, C test authority by mutating the sender, the targeting helper and the release site. Integration: same rigour plus a D completeness pass on invariant 2.

### Non-goals (S1)
Room `alert_lights`, announce, cards, info-level notifications, screen/brightness, any panel knowledge in URA beyond the service name.

## PLAN-REVIEW-2 — build contract (adversarial build-prediction, 2026-10-20)

Each item is what a builder would plausibly get wrong reading rev 2. These override earlier text.

**R2-1 HA restart loses every lease on both sides (HIGH).** NM's lease dict is in memory, so after an HA restart it is empty and the `EVENT_SERVICE_REGISTERED` re-assert has nothing to send. The "URA loads first" case in D1.2 only covers a *Halo* reload, not a restart. Contract: (a) NM's re-assert source on boot is NM's own restored alert state (`_active_alert_data` / `_active_episode_id`, `notification_manager.py:2523-2535`, already restored across restart for the ack registry), not a separate lease dict; if NM is ALERTING after restart, it issues `indicate` for that episode once the service exists (either at NM start if `has_service`, or on the registered event). (b) Anything not in NM's alert state rides TTL and is gone after restart; that is accepted and stated, not hidden. (c) Test `test_reassert_after_restart_from_restored_alert_state`.

**R2-2 Re-assert must not resurrect expired or released leases (HIGH).** NM's lease dict stores `expires_at` (UTC) per `(id, areas)`; re-assert sends only unexpired entries with the *remaining* TTL, and every release site deletes the entry before the `await` of `halo.release`. Test `test_reassert_skips_expired_and_released`.

**R2-3 Snapshot source is a lie during an active indication (HIGH).** Verified: the bridge publishes LED state once per command as `{state:ON, color}` with **no effect field** (`MQTTManager.kt:320-335`, called from `LedControlService.kt:107`), and `notify` reverts the LED to `lastSolid` without publishing (`LedController.kt:155-158`). So the HA entity shows "on, blue" while blinking, and still shows the notify colour after the LED went back. If Halo snapshots after its own command (e.g. Halo reloaded mid-lease, or a second lease arrives), restore paints solid blue forever. Contract: snapshot is taken only when the panel goes idle→active, persisted in a `Store` keyed by panel, and **not overwritten** while any lease is active or while a restore is pending; on setup with a persisted snapshot and zero leases, Halo sends the restore once (heals the stuck-ring-after-reload case). Snapshot `unknown`/`unavailable` → restore = `off`. Test `test_snapshot_not_taken_from_own_command`, `test_setup_with_stale_snapshot_restores`.

**R2-4 Unload behaviour is unspecified (MEDIUM).** Pick: on `async_unload_entry` Halo sends the restore for every active panel, then cancels TTL timers and listeners. A reload then re-indicates via NM re-assert (brief flicker accepted). Without this a removed integration leaves rings flashing forever. Test `test_unload_restores_and_cancels_timers`.

**R2-5 Sleep onset mid-lease: invariant 2(b) is hollowly satisfiable (HIGH).** A builder that simply stops sending when sleep turns on leaves the `warn` blink running on hardware, and 2(b) ("nothing below the floor is sent") still passes. Rewrite 2(b): *while sleeping, the last command sent to a panel is either (i) the effect of the highest eligible (≥ floor) lease, or (ii) the restore*. Sleep on → arbiter step re-evaluates every panel; sleep off → re-evaluate and re-show held leases. Boot debounce: during the debounce window treat sleep as **unknown → apply the floor** (fail toward quiet for non-safety, never suppress `critical`). Test `test_sleep_onset_demotes_running_warn`, `test_sleep_exit_reshows_held`.

**R2-6 Security at night is suppressed by the level map (MEDIUM, operator decision).** D1.2 maps security → `warn`; the sleep floor drops `warn`. An intrusion at 03:00 would never light a panel. Default in this plan: security HIGH/CRITICAL → `alert` (shows while sleeping, not in bedrooms), security below HIGH → `warn`. Added to Operator decisions.

**R2-7 `notify` and 4-bit colour (MEDIUM).** `info` uses `notify`, which self-terminates to the bridge's `lastSolid`, not to Halo's snapshot. Contract: an `info` lease is one-shot: Halo sends it, does not count it as "shown", and the panel's indication sensor reports `info` only for the lease's TTL. Halo never relies on bridge `lastSolid` for restore; restore is always an explicit `solid`/`off` from the snapshot. Colours in `LEVEL_EFFECT_MAP` are stored as 0-15 triples and converted ×17 on send (the bridge does `r*15/255`, `setColorFromHex`), so amber = (15, 8, 0), not an RGB guess. Test `test_effect_map_round_trips_4bit`.

**R2-8 One `indicate` per notify, defined (MEDIUM).** "Exactly one call" means one `halo.indicate` with `area_id` = the list of target areas, one `id` per notification. Multi-room safety location (`", ".join`, `safety.py:1920`) produces one lease id with the location string normalised (sorted room slugs joined by `+`), not one call per room. A repeat of the same notification renews (same owner+id) rather than creating a second lease.

**R2-9 Service call mechanics (MEDIUM).** Use `blocking=True, return_response=True` (a `SupportsResponse.OPTIONAL` service only returns a response when both are set), wrapped in `asyncio.timeout(5)`; a timeout or `HomeAssistantError`/`ServiceNotFound` marks channel health with the error and never propagates into `async_notify`. The call must not delay the other channels: run `_send_panels` as a tracked task (NM's existing task tracking, cancelled in `async_stop`), not inline before the `:1405` return. Room→area: URA room config entries carry an area; the resolver returns room keys and `_send_panels` maps them to `area_id`s via URA's existing room area field, dropping rooms with no area (counted in the log row).

**R2-10 Release ordering (LOW).** At every release site: pop from NM's lease dict first, then `await halo.release`. Kill switch release uses `halo.release` with `owner="ura"` and no id (add: `id` optional on release, owner-wide), not `release_all`, which is the operator's override and also clears non-URA owners.

**R2-11 Re-eval cleared release (LOW).** The `:3120` else-branch has `_active_alert_data` before it is set to None; capture the episode's lease id into a local before clearing, then release. Same capture-before-await rule at ack (`:2962`).

**R2-12 Test fixtures for the new repo (HIGH — none specified).** `~/Code/halo-panels` gets: `pyproject.toml` pinning `pytest-homeassistant-custom-component` to the HA version running live, `tests/conftest.py` with `auto_enable_custom_integrations`, a `MockConfigEntry` with two panel subentries (one bedroom), LED as `async_mock_service(hass, "light", "turn_on")` / `turn_off` capturing a **command log** (all ordering assertions run on this log, never on final state), the sleep sensor as `hass.states.async_set`, time via `async_fire_time_changed` + `freezer`. The property test uses `hypothesis` over sequences of {indicate(level, id), release(id), ttl_tick, sleep_on/off, led_unavailable/available} and checks 2(a), the rewritten 2(b) and 2(c) after every step. URA side fakes Halo with `hass.services.async_register("halo", "indicate", handler, supports_response=SupportsResponse.OPTIONAL)` registered *after* NM start to exercise the registered-event path. CI: GitHub Action running pytest + `hassfest` + HACS validation.

**R2-13 Invariant 2(c) "within one arbiter step" is hollow (MEDIUM).** Define an arbiter step as the synchronous handler run for one input event (service call, timer, state change). A test passes only if the restore is in the command log produced by the same event that removed the last lease. TTL expiry uses one `async_track_point_in_utc_time` per lease, cancelled on release/renew.

**R2-14 Invariant 1 byte-identical claim needs a scope (LOW).** "Switch on" adds a `channel="panels"` row; "switch off" must add nothing, including no `has_service` call side effects and no new listener. The `EVENT_SERVICE_REGISTERED` listener is registered only while the switch is on (subscribe on switch-on, unsub on off and in `async_stop`).

**R2-15 First shippable slice boundary.** S1 is two independently shippable halves: **S1a** Halo alone (services, arbiter, snapshot store, sleep, status/indication sensors, `switch.halo_led`, tests R2-12), live-validated from Developer Tools; **S1b** URA NM channel, built against S1a's released service contract. S1b does not merge until S1a is installed live. Out of S1: room `alert_lights`, announce/card, `info` from URA, the `:5070` direct light caller (left untouched; decided in S2).

## S2 — Room alert_lights and announce

### D2.1 Room alert_lights on the same targeting
NM's light engine becomes per-room: snapshot and pattern task keyed by room; target rooms' `alert_lights` driven with the existing patterns and `_ura_light_call` write mark. The house list `nm_alert_lights` maps to the `house` target. Then decide DELETE vs keep for `automation.py:4895/4909` and the early return at `aggregation.py:1421` (supersession triage, not assumed delete).

- **Verify:** leak in Kitchen → Kitchen `alert_lights` flash, Bedroom's do not; release restores only Kitchen's.
- **Test:** `test_room_alert_lights_target_only`, `test_room_restore_independent`, `test_house_list_unchanged`.
- **Live:** Kitchen alert light flashes on a leak test; another room's stays steady.
- Knob: `switch.ura_nm_room_alert_lights` (Switch, off) — opt-in, off = today's behaviour.

### D2.2 Announce and card on panels
`announce` and `card` fields on `indicate` become live: `assist_satellite.announce` for `critical`/`alert`; card via the KS notification action named in the registry row (Master's prefix differs, brief §2). Once per lease id, per-panel rate limit `number.halo_announce_min_interval_s` (120), sleep floor applies, `switch.halo_announce` default off.

- **Verify:** flapping leak (3 indicates in 60 s, same id) → one announcement.
- **Test:** `test_announce_once_per_lease`, `test_announce_rate_limit`, `test_action_name_from_registry`, `test_card_dismissed_on_release`.
- **Live:** one `esphome.kiosk_satellite_voice` event with `reason: announcement` per test leak on the targeted panel.

## Parked (unchanged triggers)
- **Touch witness** (`binary_sensor.halo_<area>_touched`, freshness-guarded): cheap, but it is a presence input. **Trigger:** a URA presence cycle that reads both presence docs and names the room that needs it (Study A).
- **Noise:** −96 dBFS floor, Master mic silent, fan-confounded. **Trigger:** HomeLab fixes the Master mic and a one-shot probe separates occupied-awake from empty.
- **Night light:** a second steady LED writer against the arbiter. **Trigger:** S1 runs a month with zero invariant violations in its command trail and the operator names a room where night lights fall short. If revived, it is just a low-level lease from an automation; no new arbiter.
- **Entertainment/guest/party:** **Trigger:** a named operator event after S1 is stable; same lease API at `info`, off during sleep.
- **Bridge retirement:** HomeLab Stage 7 (`publishLight`, `sdk.md:211`); the integration only needs the new light entity id per row. Verify effect names match `LEVEL_EFFECT_MAP` then.

## Plan-wide non-goals
- Screen wake-on-occupancy / display control and room quick-actions stay with `TABLET-FLEET-1` (kanban, adjacent, untouched by this plan) — PLAN-REVIEW-1.
- No screen, screensaver, dashboard view or brightness control (HomeLab).
- No change to presence fusion, house state, HVAC, or the Safety Coordinator.
- No bus event, no cross-integration Python import.
- No version numbers here; URA's slices get a PATCH at deploy.

## Operator decisions needed
1. ~~Integration name/domain~~ settled: Halo / `halo` / `~/Code/halo-panels` (GitHub + Gitea dual push).
2. Approve the targeting rule (own room + occupied adjacent + occupied zone; smoke/CO house-wide).
2b. (PLAN-REVIEW-1) Release policy: confirm ack / kill-switch / re-eval-cleared release and *no* release on URA stop (see D1.2).
3. Study A bridge MQTT and Study B physical check; S1 runs on whatever panels are healthy.
4. (PLAN-REVIEW-2) Security level map: HIGH/CRITICAL → `alert` so intrusions show during sleep (default proposed), or keep `warn`.

## Order of work
S0 probe → S1a (Halo) → S1b (NM channel; may be built in parallel against the contract, merges after S1a is live) → S2 → parked items by trigger.
Rev 3 (2026-10-22): S0 and S1a done; S1b is next, contract in §S1b below (plan review, then build).

## S0 RESULTS 2026-10-20

Probe run 2026-10-20 18:5x CDT, read-only. Source: `ssh ha sqlite3 /config/universal_room_automation/data/universal_room_automation.db`, table `notification_log` (8264 rows, 2026-09-20T22:53Z to 2026-10-20T23:43Z, so "all history" is only ~30 days; widening was not possible). Room list = 47 `entry_type == room` entries in `/config/.storage/core.config_entries`. Dedupe = distinct `(timestamp to the second, coordinator_id, hazard_type, location, title)`; raw rows are 2-10x higher (per recipient/channel).

### Table 1: logged `location` per distinct notification (safety / security classes)

| Class | Coordinator | Distinct notifications | Logged `location` | Resolves to a URA room |
|---|---|---|---|---|
| safety, room name logged | safety | 7 | `Master Bathroom`, `Garage A`, `Study A Closet` (all exact room titles) | 7 / 7 |
| safety, location logged BLANK (rows 2026-09-20 .. 2026-10-17T11:28Z; hazard_type also blank) | safety | 205 | empty; the title is `Safety alert: ... in <Room>` and the named room is an exact room title in all 205 | 205 / 205 via title only (not via `location`) |
| security lock-check | security | 74 (63 "Lock check unavailable device", 11 "Periodic lock check") | empty | 0 / 74 |
| perimeter person/vehicle | perimeter_alert | 2886 | 2874 camera `binary_sensor.*` entity_ids; 12 camera keys (`front_side_ptz`, `rear_ptz`, `reolinkstudybporchptz`) | 0 by room name; entity_id to area to room NOT tested (unknown), these are exterior cameras |

Other coordinators (not safety/security): energy = entity names / `battery` / `main_panel` / `garage_a|b` / `generator`; optimization = `house`; stuck_signal = kind strings; hvac, presence, bayesian = blank. No `comma list` location appears in the DB (0 rows). No fire/smoke/CO/leak/gas hazard exists in the window: safety rows are only `high_co2`, `low_humidity`, `high_tvoc`. So the multi-leak join (`safety.py:1920`) and the leak path are untested by data; they are covered only by static reading.

Unexplained: safety rows before 2026-10-18 carry blank `location`/`hazard_type`; from 2026-10-18T03:01Z on they are populated. I did not find the cause (the producer at `safety.py:2580-2590` passes `location=hazard.location` in the code as it stands now); treat the earlier blanks as a logging artefact of an older build, unverified.

### Table 2: static classification of the 34 `async_notify` call sites (location passed)

| Class | Sites (file:line) |
|---|---|
| room name | `hvac.py:5273` (`room_name`); safety via funnel `manager.py:1074` (`action.location`, = `hazard.location` from `safety.py:2589-2590`, room name from `_sensor_locations`/`_resolve_global_location` `safety.py:1479`, or `"unknown"`; may be a `", ".join(sorted(...))` list per `safety.py:1920`) |
| `house` | `security.py:1379`, `optimization.py:5030`; `optimization.py:5574/5593` (`finding.target_id or "house"`, so a target id when present) |
| `property` | security `NotificationAction` at `security.py:1062` (reaches NM through `manager.py:1074`) |
| entity id | `perimeter_alert.py:1536` (camera `entity_id`), `button.py:2368` (test), `zone_monitoring_tripwire.py:115`; security actions `security.py:1519/1599` via funnel; `perimeter_alert.py:2975` passes `cooldown_key` (camera key) |
| kind string | `_stuck_signal_nm.py:227/311` (`str(kind)`) |
| pass-through | `manager.py:1074` (`action.location or None`), `notification_manager.py:3114` (re-fire, replays `data.get("location")`), `energy.py:9895` (`location or None`) |
| explicit None | `notification_manager.py:5079/5272/5380`, `switch.py:4805` |
| none (kwarg absent) | `hvac.py:2050/2130/4458/5311/5340/5371/5764/8909`, `hvac_override.py:8257`, `hvac_egress.py:963`, `presence.py:6128`, `transit_validator.py:2173`, `binary_sensor.py:3469` (room name is in the title only), `notification_manager.py:3700/3725`, `button.py:648` |

Total 34 (the grep shows 36 hits; `perimeter_alert.py:7` and `notification_manager.py:3947` are prose). Absent or None: 20 sites, matching the plan's count. Security `NotificationAction`s (9 in `security.py`) and the safety action (1 in `safety.py:2580`) share the one funnel site.

### Share that resolves to one or more URA rooms

- Safety: 212 / 212 distinct notifications resolve to a room, but only 7 (3.3%) via the logged `location`; 205 only via the title string. Live code passes `hazard.location`, which is a room title by construction (`safety.py:1406-1464`) or `"unknown"` (0 observed). Comma lists need the split; none observed.
- Security: lock-check 0 / 74 (no location). Perimeter 0 / 2886 by room name. Security `NotificationAction` sites pass `house`/`property`/entity_id. Roughly 0% resolves to a room today. Pooled safety+security+perimeter is 212 / 3172 = 6.7%, dominated by perimeter volume.
- Gate as written in S0 ("80% of safety/security rows"): safety PASS (100% by title, 100% by code path, `location` itself only for post-2026-10-18 rows), security FAIL (~0%).

### Verdict: GO for room targeting, scoped to safety

1. S1 ships `_resolve_target_rooms` for **safety only**: exact room-title match plus the `", "` split, `"unknown"` or no match falls back to house-wide (all panels). Re-use `safety.py:1479`'s mapping; no new entity_id-to-area step is justified by the data.
2. Security (intruder, investigate, lock-check, perimeter) and everything else: **house-wide**. The data demands no new rules; do not build an entity_id-to-room resolver in S1. Revival trigger: an operator ask to show perimeter alerts only on the nearest panel, plus a probe showing the camera devices carry URA-room areas.
3. Caveats for the builder: the test fixture must use real room titles with a comma (e.g. none of the 47 room titles contains a comma; `Jaya Bedroom (Bedroom 4)` contains parentheses) and an `"unknown"` case. The probe cannot see quiet-hours/kill-switch suppressed notifications (plan caveat 1), and the window contains no life-safety hazard, so the leak/smoke path is verified by code reading only.
4. Falsifier checked: if safety locations were mostly non-room strings the verdict would flip; the 7 logged and 205 title-derived values are all exact room titles.

---

## S1b — URA NM panel channel (build contract, rev 3, 2026-10-22)

Card: WALLPANEL-URA-NOTIFY-1. S1a (Halo 0.1.x) is live on 7 panels. This section is the URA half. It overrides D1.2, D1.3, the S1 knob/test lists and R2-1/R2-2/R2-9/R2-14 where they differ; each override is marked **[supersedes …]**.

### S1b.0 What changed since rev 2

1. **Targeting is audience-based, not hazard-location-based** (operator 2026-10-20, via HomeLab: "occupied-rooms-only is too narrow, hallways rarely register occupied"). A panel shows a notification when people are likely to see it, not when it sits next to the hazard. **[supersedes D1.2 `_resolve_target_rooms(location, …)` and S0 verdict items 1-2]** The S0 location resolver is no longer needed for targeting; it survives only as an optional "also light the source room" term (S1b.2 rule T4, operator question Q2).
2. **Re-assert trigger is `halo_ready`, not `EVENT_SERVICE_REGISTERED`.** Halo registers its services in `async_setup` (`halo/__init__.py:110-129`), never per entry, so an entry reload never re-registers them; Halo fires `EVENT_HALO_READY = "halo_ready"` with `{"areas": [...]}` at the end of every entry start (`halo/const.py` `EVENT_HALO_READY`; `halo/runtime.py:163-165`). **[supersedes D1.2 last bullet, R2-1(a), R2-14]**
3. **`has_service` is true even with no Halo entry loaded.** With the integration installed but no entry, `halo.indicate` answers `no_surface` for every area (`halo/__init__.py:84-85`). Channel health must therefore read the response, not just `has_service`. **[supersedes D1.2 "Channel health … absent"]**
4. **Owner-wide release exists.** `halo.release` with `owner` and no `id` releases every lease of that owner (`halo/runtime.py:278-279`); `release_all` releases all owners (`:284-286`). R2-10 is satisfied by the shipped code.
5. **Halo `indicate` only adds.** Calling `indicate` again with the same `id` and a smaller area list does not remove the lease from areas no longer listed (`halo/runtime.py:242-259` loops only over the given areas). Retargeting therefore needs an explicit `release(owner, id, area_id=[dropped])`. This is the main new builder trap.

### S1b.1 Institutional context verified (S1b additions)

Read in full this session: card WALLPANEL-URA-NOTIFY-1 (`kanban.data.yaml:206-240`, incl. `targeting_operator_2026_10_20`, `split_decided_2026_10_20`, `AUDIT_2026_10_20_alert_lights`, `shipped_2026_10_21_halo_s1a`, `residual_halo_followups_2026_10_21`, `residual_2026_10_21_wake_adjacency`, `resolved_2026_10_21_bridge_colour`); this doc rev 2 plus the uncommitted S0 RESULTS section (kept unchanged above); Halo `services.yaml`, `__init__.py`, `const.py`, `runtime.py:125-300`; `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (all 730 lines) and `docs/architecture/SENSOR_FLEET_CLASSES.md` (all), because S1b **reads** room occupancy (a consumer of a presence value). HVAC state-of-play not read: no HVAC surface is touched.

Presence-doc facts this plan relies on: room occupancy truth is the room coordinator's `STATE_OCCUPIED` (presence doc §1 table, `coordinator.py:3613`); the zone tracker's per-room view is **lossy** in multi-sensor rooms (corrections ledger #19, #20) so S1b must not read occupancy from `ZonePresenceTracker.to_dict()["rooms"]`; phantom holds exist (fan-loop rooms, Study A ZK) and will light a panel needlessly (accepted; S1b.6). Nothing in the presence corrections ledger is re-asserted here.

REUSE / NEW per piece (greps re-run 2026-10-22; `grep -iE "halo|wallpanel|panel_channel"` over tracked URA `*.py` returns nothing, so no URA prior art for a panel channel):

| Piece | Verdict | Where |
|---|---|---|
| Notification funnel | REUSE | `NotificationManager.async_notify` `notification_manager.py:1334` (signature carries `coordinator_id`, `severity`, `hazard_type`, `location`) |
| Kill switch / enabled / dry-run gates | REUSE | `self.enabled` `:1365`; `_messaging_suppressed` `:1369`; `_dry_run_active` `:443`, `_log_dry_run` `:531` |
| Quiet-hours early return (must be bypassed for panels) | REUSE (placement only) | `_is_quiet_hours()` gate `:1412`; definition `:3854-3865` returns True for house state `sleep`/`home_night` when `CONF_NM_QUIET_USE_HOUSE_STATE` |
| House state read | REUSE | `coordinator_manager.house_state` (`manager.py:325`), same read as `:3859-3862` |
| Sender shape | REUSE pattern | `_send_tts` `:2317-2338` (dry-run short-circuit, `async_call`, `_update_channel_health`) |
| Channel health | REUSE | `_update_channel_health(channel, success)` `:5097` |
| Background task tracking | REUSE | CM-entry `async_create_background_task` pattern `:5138-5161`, `:5339-5352` |
| Room occupancy | REUSE | room coordinators via `aggregation._get_room_coordinators` `aggregation.py:767`; `coordinator.data[STATE_OCCUPIED]` (`const.py:1904`) |
| Room → HA area | REUSE | `UniversalRoomCoordinator._get_room_area()` `coordinator.py:3038-3044` (`CONF_AREA_ID`, options over data) |
| Room adjacency | REUSE | `PresenceCoordinator.get_adjacent_rooms(room_name)` `presence.py:3298-3310`, cache `_rebuild_adjacency_cache` `:3238-3296` (entry_id tokens resolved to room names; `CONF_ADJACENT_ROOMS` `const.py:720`) |
| Room → house zone | REUSE | `PresenceCoordinator._room_to_zone` `presence.py:3490-3494` (first-writer-wins) and `zone_trackers[z].room_names` (`:563-567`, `:1872`). Membership only; occupancy NOT read from the tracker (ledger #19) |
| Life-safety hazard set | REUSE | `NM_LIFE_SAFETY_HAZARDS` `const.py:3610` (smoke, fire, carbon_monoxide, water_leak, flooding, intruder, freeze_risk) |
| Episode state for re-assert after restart | REUSE | `_active_alert_data` / `_active_episode_id` set in `_enter_alerting` `:2511-2545`, restored at boot (`:1038`) |
| Release hooks | REUSE sites | kill switch `:698-735` (calls `_restore_alert_lights` `:724`); ack `async_acknowledge` `:2920` (`:2971`); re-eval cleared `_re_evaluate_hazard` else-branch `:3131-3136`; `async_stop` `:1326` (no release) |
| NM switch / number entity pattern | REUSE pattern | `NMDryRunSwitch` `switch.py:4906-4936` (`switch.ura_nm_dry_run`, RestoreEntity); NM bucket Numbers |
| Targeting helper `_panel_target_areas(...)` | NEW | nothing generic maps "where people are" to areas; `hvac_zones.occupied_rooms` (`hvac_zones.py:259`) is HVAC-zone scoped (HVAC zone ≠ house zone), `energy._get_occupancy_counts` (`energy.py:10238`) reads the lossy tracker view and returns counts only |
| Panel lease ledger `_panel_leases` | NEW | per-id `{areas, level, expires_at}`; no NM structure holds per-area state |
| `switch.ura_nm_panel_channel`, `number.ura_nm_panel_lease_ttl_min` | NEW | no CONF_NM_* / NM entity for panels (51 `CONF_NM_*` in `const.py`, none panel) |
| Module consts `NM_PANEL_*` | NEW | listed in S1b.5 |

Config-first: nothing to turn. Halo is live but has no caller; `nm_alert_lights` (`CONF_NM_ALERT_LIGHTS` `const.py:3525`) would flash every listed light for every qualifying alert with no targeting, no per-panel restore and no lease, and bedroom panels would fire at night. An HA automation calling `halo.indicate` could be written, but it would have to re-derive URA occupancy, adjacency and zones from entities — the duplication this card exists to avoid.

### S1b.2 Targeting rule (the new helper)

Inputs, read once per notify, captured into locals before any `await`:
- `occ` = set of room names whose room coordinator reports `data[STATE_OCCUPIED] is True`. Unknown/None data counts as not occupied.
- `adj(r)` = `presence.get_adjacent_rooms(r)`.
- `zone(r)` = `presence._room_to_zone.get(r)` (exposed through a new tiny public getter, not a private-attribute read across modules).

A room R is a **target** if any of:
- **T1 own room:** R ∈ `occ`.
- **T2 occupied zone:** `zone(R)` is not None and some room in that zone is in `occ`.
- **T3 adjacent to occupied:** some O ∈ `occ` with R ∈ adj(O) **or** O ∈ adj(R). Both directions, because `CONF_ADJACENT_ROOMS` is configured per room and is often one-directional (presence doc §6 item 3, Jaya). Recommended default; operator Q1.
- **T4 source room (safety only, optional):** R is the room named by `location` per the S0 rule (exact room title, `", "` split). Default **on** for coordinator `safety` (the hazard is there; someone walking in should see it). Operator Q2.

Overrides:
- **House-wide:** `hazard_type ∈ NM_PANEL_HOUSEWIDE_HAZARDS` (smoke, fire, carbon_monoxide) → every room with an area. This is the only case that ignores occupancy.
- **Empty audience:** `occ` empty and not house-wide → no call and no row (nobody can see a panel); a debug log line only. With T4 on, a safety notify still targets its source room, so this case applies to security and to safety with T4 off or an unresolvable location.

Output: the sorted, de-duplicated list of HA `area_id`s of target rooms (`_get_room_area()`; rooms with no area dropped). URA sends every target area; Halo answers `no_surface` for areas without a panel. URA keeps **no panel registry** (plan-wide non-goal stands).

Hallways: the operator's example (Upstairs Hallway rarely registers occupied) is covered by T2 if the hallway sits in a house zone with an occupied room, and by T3 if it is configured adjacent to an occupied room. Verify in the Live step that the Upstairs Hallway and Foyer rooms have a zone and adjacency set; if not, that is a config action, not code (config-first).

### S1b.3 Gating (what is sent at all)

Order inside the sender, all synchronous, before the first `await`:
1. `switch.ura_nm_panel_channel` off → return. No `has_service` call, no listener, no row (R2-14 byte-identical rule).
2. `coordinator_id ∉ NM_PANEL_COORDINATORS` (`safety`, `security`) → return. Perimeter (`"perimeter_alert"`, `perimeter_alert.py:1525/2960`, ~96 distinct/day in S0 Table 1), HVAC, energy, optimization and stuck-signal never reach panels in S1b.
3. Level from `NM_PANEL_LEVEL_MAP` (severity × coordinator, below); `None` → return.
4. **Night gate (URA side):** house state ∈ `NM_PANEL_NIGHT_STATES` (`sleep`, `home_night`) → only notifications with `coordinator_id == "safety"` **or** `hazard_type ∈ NM_LIFE_SAFETY_HAZARDS` pass (so `intruder` passes; lock-check does not). Halo then applies its own floor on top (house sleeping: ≥ `alert`; bedroom panels: `critical` only — `halo/const.py` `SLEEP_MIN_LEVEL`, `BEDROOM_SLEEP_MIN_LEVEL`). URA's gate is needed because Halo's sleep entity does not cover `home_night`.
5. Dry-run → `_log_dry_run(channel="panels", …)`, no service call.
6. Targeting (S1b.2); empty → return.

Level map (rung 1, `NM_PANEL_LEVEL_MAP`):

| Coordinator | CRITICAL | HIGH | MEDIUM | LOW |
|---|---|---|---|---|
| safety | critical | alert | alert | — |
| security | alert | alert | warn | — |

Security CRITICAL maps to `alert`, not `critical`, so it never wakes a bedroom panel (bedroom floor = critical). Security HIGH → `alert` adopts R2-6's default. Operator Q3.

Placement **[supersedes D1.2 placement]**: one call `self._schedule_panel_delivery(...)` in `async_notify` immediately after the `_messaging_suppressed` return (`:1369-1371`) and `_refresh_config()` (`:1375`), **before** the quiet-hours gate (`:1412`). It does the synchronous gating and targeting, then schedules the service call as a tracked background task, so a slow Halo never delays TTS/push and quiet hours do not suppress panels (the night gate above replaces DND for this channel).

### S1b.4 Lease lifecycle

- **id:** `ura:<coordinator_id>:<hazard_type or "none">:<location key>` where location key = normalised S0 room slugs joined by `+`, or `house`. Same notification repeated → same id → Halo renews TTL (R2-8 kept).
- **TTL:** `number.ura_nm_panel_lease_ttl_min` × 60, clamped to Halo's `[10, 86400]` s before the call.
- **Retarget on renew:** at each indicate for an id already in `_panel_leases`, compute `dropped = old_areas − new_areas`; pop/replace the ledger entry first, then `await indicate(new_areas)`, then if `dropped`, `await release(owner="ura", id, area_id=dropped)`. Only renewals retarget; there is **no occupancy listener** (S1b.6 marginal-benefit note). CRITICAL alerts re-fire every 30 s (life-safety) / 300 s (`NM_REPEAT_INTERVAL_*`, `const.py:3605-3606`), so active alerts follow people at that cadence.
- **Release sites** (ledger pop BEFORE the `await`, capture-before-await per R2-11):
  - ack (`async_acknowledge`, `:2920`, next to `:2971`) → release the episode's lease id(s).
  - re-eval cleared (`:3131-3136`) → capture id from `_active_alert_data` into a local before it is set None, then release.
  - kill switch engaged (`:698-735`, next to `:724`) → `halo.release(owner="ura")` with no id (owner-wide). Never `release_all`.
  - panel switch turned off → owner-wide release, then unsubscribe `halo_ready`.
  - `async_stop` (`:1326`) → **no release** (R2 decision kept; leases are TTL-bounded).
  - Non-CRITICAL notifications (no episode) ride TTL only.
- **Re-assert:** subscribe `halo_ready` while the switch is on. On the event, re-send every unexpired ledger entry with its **remaining** TTL (R2-2), and after an HA restart, rebuild one entry from restored `_active_alert_data` if NM is ALERTING (R2-1(a)) — targeting recomputed at that moment. Also attempt that rebuild once at NM start if Halo is already loaded.
- **Clear only what URA set:** every call carries `owner="ura"`; release predicates in Halo match owner (`halo/runtime.py:278-279`). URA never calls `release_all` and never sends an id it did not create.

Service call mechanics (R2-9 kept): `blocking=True, return_response=True`, `asyncio.timeout(NM_PANEL_CALL_TIMEOUT_S)`; `ServiceNotFound` → health `absent`; timeout/`HomeAssistantError` → health error; response with every area `no_surface` → health `no_surface`; any `accepted`/`suppressed_sleep` → `ok`. Exceptions never propagate into `async_notify`.

DB: one `notification_log` row per delivered indicate, `channel="panels"`, through the existing `database.log_notification` (queued writer, one row per notify, not per area). **This is the Tier 2-DB trigger** (new row shape on an existing table: new `channel` value). No schema change. Ledger is in memory only.

### S1b.5 Knobs

| Knob | Rung | Default | Why / kill semantics |
|---|---|---|---|
| `switch.ura_nm_panel_channel` | 3 Switch (NM, RestoreEntity) | off | Opt-in. Off = no call, no listener, no row; turning off releases owner `ura` |
| `number.ura_nm_panel_lease_ttl_min` | 3 Number | 30 (range 1-240) | Bounds a lost release; operator tunes by observation |
| `NM_PANEL_COORDINATORS` | 1 const | {safety, security} | Which coordinators may light panels; widening needs review (perimeter volume) |
| `NM_PANEL_LEVEL_MAP` | 1 const | table above | Safety signalling; review to change |
| `NM_PANEL_HOUSEWIDE_HAZARDS` | 1 const | {smoke, fire, carbon_monoxide} | Life-safety ignores occupancy; empty set = no house-wide override |
| `NM_PANEL_NIGHT_STATES` | 1 const | (sleep, home_night) | Matches `_is_quiet_hours` house-state set (`:3862`); empty = no URA night gate (Halo floor still applies) |
| `NM_PANEL_TARGET_ZONE_ENABLED` | 1 const | True | T2; False = drop the zone term |
| `NM_PANEL_TARGET_ADJACENT_ENABLED` | 1 const | True | T3; False = drop the adjacency term |
| `NM_PANEL_TARGET_SOURCE_ROOM_ENABLED` | 1 const | True | T4 (safety only); False = audience only |
| `NM_PANEL_CALL_TIMEOUT_S` | 1 const | 5 | Protocol bound |

Halo-side knobs (`switch.halo_led`, `number.halo_boot_debounce_s`, per-panel enabled/bedroom) are unchanged and remain the operator's hardware kill switch.

### S1b.6 Marginal-benefit notes (pushback recorded)

- **Live retargeting on occupancy change** (re-send when someone walks into an adjacent room mid-alert): rejected for S1b. Renewal-driven retargeting captures it at 30-300 s for CRITICAL episodes, which are the ones that last; the listener variant adds a new state-change subscription over ~47 room sensors, cross-coordinator state and a rare-fire path. **Revival trigger:** a Live leak/intruder test where a person in a newly occupied adjacent room did not see the panel within one repeat interval and the operator names it as a miss.
- **Phantom occupancy lights panels** (fan loops, Study A ZK): accepted; the cost is a blink in an empty room. Not worth a trusted-presence filter.
- **Using the zone tracker's occupancy** would have been one line, but ledger #19 says it wipes multi-sensor rooms; reading room coordinators costs one loop over ~47 entries per qualifying notify (safety/security only), which is cheap.

### S1b.7 Producer / consumer checks

| Value | Producer (arithmetic, dependency health) | Consumers |
|---|---|---|
| room occupied | room coordinator `STATE_OCCUPIED` (`coordinator.py:3613`), fused motion/presence/occupancy with debounce and stuck/chatter exclusion. Health: known phantom holds (presence doc §6, §9) | NEW: `_panel_target_areas` (trust decision for display only) |
| adjacency | `_rebuild_adjacency_cache` (`presence.py:3238`), built at zone discovery, keyed by room name, entry_id tokens resolved. Health: one-directional configs exist; stale tokens kept as-is. Cache only rebuilds on discovery (options change to adjacency needs a presence rediscovery) | existing: fan recheck L2 (`presence_fan_recheck.py:1400`); NEW: T3 |
| room → zone | `_room_to_zone` (`presence.py:3490-3494`), first-writer-wins. Health: ZONE-ROOM-NAME-DRIFT-1 (renamed room keeps old name until restart, presence doc §9) → a renamed room loses T2 until restart | existing: presence hot paths; NEW: T2 |
| room area | `_get_room_area()` options-over-data | existing: entity discovery; NEW: area list |
| house state | `coordinator_manager.house_state` | existing: quiet hours `:3859`; NEW: night gate |
| `panels` health | NEW `_update_channel_health("panels", …)` from Halo response | NM diagnostics / channel health sensor (display) |
| `notification_log` row `channel="panels"` | NEW, `log_notification` | display/analytics readers of `notification_log`; verify no reader enumerates a closed channel set (builder greps `channel IN` / `channel ==` over `database.py`, `sensor.py`, `websocket_api.py` and records result) |

Name-key consistency: occupancy is gathered from room coordinators by entry; adjacency and zone maps key by `CONF_ROOM_NAME or entry.title` (`presence.py:3266-3268`). The helper must key `occ` by the **same** expression, or T2/T3 silently miss. Test pins it with a room whose `room_name` differs from its title.

### S1b.8 Site enumeration (Bug Class #53)

- **Emission:** exactly one site, inside `async_notify` (S1b.3 placement). Every one of the 34 callers (D1.3 / S0 Table 2) passes through it; the gate decides. Callers that bypass `async_notify` and so never reach panels, by design: `_trigger_alert_lights` direct caller `notification_manager.py:~5070` (S2 decides), the REPEATING TTS path `:2832-2850` (re-fire goes through `async_notify` at `:3114`, which renews), `_send_*` per-person paths.
- **Release:** the five sites in S1b.4. Builder re-greps `_restore_alert_lights(` and `_active_alert_data = None` and maps each hit to "release" or "not a clear" in the build notes (rev 2 found 3 + 1; line numbers have moved: `:724`, `:1326`, `:2971`; `_active_alert_data = None` at `:730`, `:1099`, `:3101`, `:3133`). `:1099` (boot restore of a stale alert) and `:3101` (re-eval with no data) must be classified explicitly.
- **Re-assert:** `halo_ready` listener + NM-start rebuild. Two sites.

### S1b.9 Falsifiable invariants

- **I1 (no-op):** with `switch.ura_nm_panel_channel` off, for any caller and any house state, `async_notify` makes zero `halo.*` calls, registers zero listeners, and writes the same `notification_log` rows as before the cycle.
- **I2 (ownership):** in no reachable path does URA call `halo.release_all`, or `halo.release`/`indicate` with an `owner` other than `"ura"` or an `id` it did not mint. (A non-URA lease on a panel is never cleared by URA.)
- **I3 (night):** while house state ∈ {sleep, home_night}, URA sends no `indicate` for a notification that is not (coordinator `safety` or hazard ∈ `NM_LIFE_SAFETY_HAZARDS`).
- **I4 (audience):** for a non-house-wide notification, every area in the `indicate` call belongs to a room satisfying T1-T4 at send time, and after a renewal no area outside the new target set still holds the lease (dropped areas are released in the same delivery task).
- **I5 (no stuck URA lease):** every URA lease is released or expires within its TTL; re-assert never re-sends an expired or released id.

Reviewer D attacks with: renew with a shrunk target set (I4, Halo add-only); ack arriving between ledger update and `await indicate` (I5); `halo_ready` during a release; switch off mid-delivery task; restart while ALERTING with a security episode at `home_night`; a room whose `room_name ≠ title`; a room in two zones; `occ` empty with a smoke alarm (house-wide must still fire).

### S1b.10 Deliverables and acceptance

**D-S1b-1 Targeting helper** `_panel_target_areas(coordinator_id, hazard_type, location) -> list[str]` (+ public `PresenceCoordinator.get_room_zone(room)` getter).
- **Verify:** Kitchen occupied, Breakfast Nook in Kitchen's zone, Media adjacent to Kitchen, Master empty and not adjacent → areas = kitchen, breakfast nook, media; not master. A flash-everything build returns master too; an own-room-only build drops media and the nook.
- **Verify:** adjacency configured only on Media → Kitchen; Kitchen occupied → Media targeted (reverse direction).
- **Verify:** smoke with nobody occupied → every area; water leak with nobody occupied → no call.
- **Test:** `test_target_own_room`, `test_target_occupied_zone`, `test_target_adjacent_both_directions`, `test_target_source_room_safety_only`, `test_housewide_ignores_occupancy`, `test_empty_audience_no_call`, `test_room_name_differs_from_title`, `test_room_without_area_dropped`.

**D-S1b-2 Sender + gating + placement.**
- **Verify:** quiet hours on (`home_night`), leak HIGH in Kitchen → panels indicate fires, TTS/lights suppressed. A build that placed the sender with the other global channels shows no call.
- **Verify:** `home_night`, security lock-check MEDIUM → no call; `intruder` → call at `alert`.
- **Verify:** HVAC / perimeter / energy notify → no call at any severity.
- **Verify:** dry-run on → zero service calls, one `dry_run=1` row `channel=panels`.
- **Test:** `test_panel_channel_off_is_noop` (byte-compare rows, no listener), `test_panels_bypass_quiet_hours`, `test_night_gate_safety_only`, `test_coordinator_allowlist`, `test_level_map`, `test_dry_run_panels`, `test_sender_does_not_block_other_channels` (Halo fake sleeps 10 s; TTS call completes first), `test_call_timeout_marks_health`.

**D-S1b-3 Lease ledger, retarget, release, re-assert.**
- **Verify:** renew with Media no longer targeted → one `indicate` (kitchen, nook) then one `release(owner=ura, id, area_id=[media])`. An add-only build shows no release and Media keeps blinking.
- **Verify:** ack → `release(ura, id)`; kill switch → `release(ura)` with no id; `release_all` never called (assert on fake service call log).
- **Verify:** `halo_ready` after 10 min with TTL 30 → re-indicate with ~20 min; released id not re-sent.
- **Test:** `test_retarget_releases_dropped_areas`, `test_release_on_ack`, `test_release_on_reeval_cleared`, `test_killswitch_owner_wide_release`, `test_switch_off_releases_and_unsubscribes`, `test_never_release_all`, `test_reassert_on_halo_ready_remaining_ttl`, `test_reassert_skips_expired_and_released`, `test_reassert_after_restart_from_restored_alert_state`, `test_async_stop_does_not_release`.
- Fake Halo: `hass.services.async_register("halo", "indicate"|"release", handler, supports_response=SupportsResponse.OPTIONAL)` recording a call log; `halo_ready` via `hass.bus.async_fire`. All ordering asserts on the call log.

**D-S1b-4 Entities + health.** `switch.ura_nm_panel_channel`, `number.ura_nm_panel_lease_ttl_min` (NM device, RestoreEntity, pattern of `NMDryRunSwitch`); `panels` in channel health with `absent` / `no_surface` / `ok` / error.
- **Test:** `test_panel_switch_restores`, `test_panel_ttl_number_restores`, `test_health_no_surface_when_halo_unconfigured`.

**Live (post-deploy, switch turned on by the operator):**
1. `switch.ura_nm_panel_channel` on; NM channel health shows `panels: ok` after the first qualifying notify (or `no_surface`/`absent` with a reason).
2. Operator wets a leak probe in a room with a panel while one other panel room is occupied and a third is empty and not adjacent: amber pulse on the source and occupied/adjacent panels, nothing on the third; `sensor.halo_<area>_indication` shows lease id `ura:safety:water_leak:<room>`; `notification_log` has one `channel='panels'` row with non-empty `hazard_type` and `location`.
3. Acknowledge → every `sensor.halo_*_indication` returns to `idle` and the LEDs restore.
4. Reload the Halo entry during a test lease → lease reappears on the same panels within seconds (`halo_ready`).
5. Config check: Upstairs Hallway and Foyer rooms have a house zone and adjacency set (read `core.config_entries`); if missing, raise a config action, not a bug.
6. Operator `light` on a panel set by hand during the test is restored, not cleared, after release (ownership).

### S1b.11 Non-goals

- **Screen wake / sleep-after-grace migration into Halo** (card residuals (b) and `residual_2026_10_21_wake_adjacency`): separate follow-up, jointly with HomeLab. S1b does not touch display behaviour, even though it uses the same adjacency set.
- Room `alert_lights` and NM per-room light engine (S2). Announce and card fields (S2; URA does not send them in S1b).
- `info`-level and non-safety/security notifications; perimeter.
- Occupancy-change listener / live retargeting (S1b.6, parked with trigger).
- Any panel registry, panel names or bedroom flags in URA. Any change to Halo, Safety, Security, presence fusion or HVAC. Halo follow-ups (a) start-up delay on subentry reload and (c) `via_device` nesting stay on the card.
- No schema migration, no new table.

### S1b.12 Tier

**Tier 2-DB.** Triggers: a new `channel` value in `notification_log` rows (persisted-record shape), a new emission inside the funnel every coordinator uses (no-op path must be byte-identical), and cross-coordinator reads (presence adjacency/zones + room occupancy + house state). Not Tier 3: no cost or safety actuation is decided here (Halo owns the hardware and its own floors; worst case is a panel blinking wrongly or not at all, while push/TTS paths are unchanged). Three framing-disjoint reviews: **A** targeting + level/night gate correctness (I3, I4, name-key consistency); **B** NM no-op preservation, async/task lifecycle, ledger ordering, re-assert/restart (I1, I5); **C** test authority by per-site mutation of the sender placement, the night gate, the retarget release, each release site and the re-assert filter. One adversarial plan review (Tier 2 rule) before build dispatch. Build in a worktree; ura-builder.

### S1b.13 Operator questions (recommended defaults in bold)

**ANSWERED 2026-10-24: operator accepted all five recommended defaults (bold below).**

- **Q1** Adjacency direction: **both directions** (A adjacent to B if either lists the other), or only rooms the occupied room lists.
- **Q2** Light the hazard's own room even when nobody is there or nearby (safety only): **yes**.
- **Q3** Security levels: **CRITICAL/HIGH → `alert` (shows at night on non-bedroom panels, never bedrooms), MEDIUM → `warn`**; or security CRITICAL → `critical` (would reach bedroom panels at night).
- **Q4** Night gate scope: **safety coordinator + life-safety hazards (includes `intruder`)**, or safety coordinator only.
- **Q5** Empty audience for a non-house-wide alert: **send nothing**, or light the source-room panel anyway (that is Q2 with nobody home).
