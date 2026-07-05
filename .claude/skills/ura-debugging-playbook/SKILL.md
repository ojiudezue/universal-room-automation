---
name: ura-debugging-playbook
description: URA symptom-to-triage runbook for real production failure modes — light didn't turn on/off, presence flapping, zone flipping `away` while occupied, cold-boot actuation storm, house stuck in `sleep`, DB write-queue saturation, watchdog restart from event-loop stall, RestoreEntity boot-poisoning, config-entry reload hazards (never reload the URA parent entry), Bug Class #34 conditional-import UnboundLocalError. Use whenever a live symptom needs a discriminating experiment before blaming URA code — points at the exact log grep / ha-mcp call / DB query to run FIRST.
---

# URA Debugging Playbook

Discipline: **before you edit code, run the discriminating experiment.** In URA the same user-visible symptom ("the light didn't turn on") maps to at least four unrelated root causes, and three of the last four multi-hour incidents were spent debugging URA when the fault was outside URA (dead actuator, HA bootstrap timeout, Envoy LAN outage). This skill exists so the FIRST 60 seconds ask the right question.

## Audience & environment

You are a solo Sonnet-class session with:
- Terminal access to the URA repo at `/Users/okosisi/Code/universal-room-automation`.
- MCP tools `home-assistant` (`ha_get_state`, `ha_get_logs`, `ha_get_history`, `ha_get_integration`, `ha_call_service`) and `ura-sqlite`.
- Samba mount (may or may not be up) at `/Users/ojiudezue/ha-config/` giving read access to HA `.storage/`.
- **No subagent fleet** is assumed. Any "run 3 framing-disjoint reviews" step must be executed sequentially by you with the framings written down explicitly.

Optional accelerator: if the `ura-planner` / `ura-reviewer` / `ura-validator` agents exist in `.claude/agents/`, they can parallelize. Do not assume they exist.

## Definitions (one-time)

- **Actuator** — the HA entity URA calls `turn_on` / `turn_off` on (a light, switch, fan, climate). Distinct from input sensors (motion, lux, humidity, occupancy).
- **Parent entry** — the URA integration's top-level `ConfigEntry` (`ENTRY_TYPE_COORDINATOR_MANAGER`). Reloading it cascades into every room + zone.
- **Room / Zone entry** — per-room `ENTRY_TYPE_ROOM` and per-zone `ENTRY_TYPE_ZONE_MANAGER` sub-entries. Cheap to reload individually.
- **Write queue** — the single-writer asyncio queue in `custom_components/universal_room_automation/database.py` (documented ~line 45-51; re-verify with grep). ALL DB writes serialize through it; saturation stalls the event loop.
- **Trust hierarchy** — persistent signals (phone tracker, BLE, geofence) veto transient signals (mmWave, camera, PIR). See Bug Class #48.

## When NOT to use this skill

- **Writing a planning doc / scoping a new feature** → the operator's Institutional-Context-First protocol in `CLAUDE.md` + `ura-planner` agent. This skill is for post-hoc "something broke."
- **Deploying / releasing** → the `deploy` skill (`./scripts/deploy.sh`).
- **Reviewing a diff against QUALITY_CONTEXT bug classes** → use the QUALITY_CONTEXT doc directly + `ura-reviewer` if present; this skill is only the debug-triage subset.
- **Home Assistant automations / dashboards / helpers** → the `homeassistant_coding` and `ha-dashboard` skills.

---

## Ground rules (non-negotiable)

1. **Device availability FIRST.** Every "URA broke" incident begins with `ha_get_state` on the exact actuator. Skip this at your peril — see the AV-closet Shelly story below.
2. **Live-source only.** Diagnostics off stale data are how v3.13.0–v3.13.3 (Bug Class #7) burned four cycles fixing a phantom. Verify the URA DB path and the Samba mount are live before quoting DB state (`stat` mtime, size, or `SELECT count(*) FROM sqlite_master`).
3. **NEVER reload the URA parent entry** to "test unload symmetry" or to force a re-init. It cascades → event-loop stall → HA supervisor watchdog restarts core (~5-min outage). Reload the specific room / zone / third-party entry only.
4. **No fabrication.** If you don't know a symbol's file:line, `grep` it; don't guess. Fake specificity has cost more time than admitting uncertainty.

---

## Symptom → triage table (start here)

| User-visible symptom | Skip to |
|---|---|
| Light / fan / cover didn't turn on or off | [S1 Silent actuator](#s1-room-didnt-actuate-silent-actuator) |
| HVAC preset flipping (`home → away → home`) every 60–90 s | [S2 Presence flapping](#s2-presence-flapping--transient-sensor-over-trust) |
| Zone flipped to `away` preset while someone is IN IT | [S2 Presence flapping](#s2-presence-flapping--transient-sensor-over-trust) or [S3 Sleep-state](#s3-house-stuck-in-sleep--sleep-wake-deadlock) |
| Cold boot storm — every room turns OFF on restart | [S4 Boot actuation storm](#s4-cold-boot-actuation-storm) |
| House stuck in `sleep` past sunrise, or never entered `sleep` | [S3 Sleep-state](#s3-house-stuck-in-sleep--sleep-wake-deadlock) |
| HA log spam "Update of sensor.X is taking over 10 seconds", app disconnects | [S5 DB write-queue saturation](#s5-database-is-locked--write-queue-saturation) |
| HA supervisor restarted core; ~5-min outage; "Bootstrap stage 2 timeout" | [S6 Watchdog / bootstrap timeout](#s6-watchdog-restart--bootstrap-stage-2-timeout) |
| A URA switch/select I had ON is silently OFF after restart | [S7 RestoreEntity poisoning](#s7-restoreentity-boot-poisoning-bug-class-52) |
| New URA entities all `unavailable` / greyed out after deploy | [S8 UnboundLocalError conditional import](#s8-unboundlocalerror--conditional-import-bug-class-34) |
| Save in options flow shows "Unknown error occurred" | [S9 Config-entry save silently drops](#s9-add_update_listener-sync-handler-bug-class-28) |

---

## S1: Room didn't actuate (silent actuator)

**Source of truth:** `CLAUDE.md:88-96` "Troubleshooting — room automation broke."

The URA integration cannot control an `unavailable` entity — the `turn_on`/`turn_off` call no-ops. It looks like an automation regression; it is a dead device. `sensor.<room>_unavailable_entities` covers **input sensors only**, NOT actuators (a documented gap; see `sensor.py:1712` `_get_unavailable_entities`, verified 2026-07-02). A dead light is invisible there.

### Step 1 — Read the room's actual actuator (not the friendly name you assume)

Do not assume the friendly name maps to the physical device. Verify from `.storage/core.config_entries` on the live Samba mount:

Confirm the Samba mount is live with `stat /Users/ojiudezue/ha-config/.storage/core.config_entries`; if stale, remount per `ura-diagnostics-and-tooling` § Live-access commands (fact-home for the `mount_smbfs` command).

Then locate the room's config entry — filter `domain == universal_room_automation` and the matching title. Read out `lights` / `night_lights` / `alert_lights` / `climate_entity`. **These are the entities URA will actually call.**

Historical trap (2026-07-01): the AV Closet "light" is the Shelly relay `switch.switch_shelly1pmgen3_wifi_avcloset`, NOT `light.light01_light01`. The lux/motion is the Zigbee `occupancy_lux_temp_humidity_avcloset`, NOT the AC-Infinity grow controller. An hour was lost debugging the wrong entity.

### Step 2 — Check the configured actuator's live state

```
ha_get_state(entity_id="switch.switch_shelly1pmgen3_wifi_avcloset")
```

Discriminator:

| State | Meaning | Next |
|---|---|---|
| `on` / `off` / normal | Device alive — URA logic bug is possible. Continue to Step 4. |
| `unavailable` with `restored: true` in attributes | **Device offline.** URA is exonerated. Go to Step 3. |
| `unknown` | Just-restarted, transient. Wait 60 s and re-check. |

Cross-check whole-device-dead vs one weird entity by reading a sibling power/voltage sensor from the same device (Shellys expose `sensor.*_power`, `sensor.*_voltage`).

### Step 3 — Device offline ≠ integration failed

```
ha_get_integration(domain="shelly")   # or sonoff / tuya / etc.
```

A Shelly config entry can stay `loaded` while its device is off-WiFi (entities go `unavailable`). Reloading a `loaded` entry only recovers a device that is **back on WiFi** — it will NOT revive a device that is physically off. A batch of unavailable devices across rooms usually means a **network event**, not URA.

**Recovery** — reload the SPECIFIC stuck config entry:

```
ha_call_service(
  domain="homeassistant",
  service="reload_config_entry",
  data={"entry_id": "<the shelly entry_id>"},
)
```

Do NOT blanket-reload all entries — every working device blinks. Cloud integrations (Sonoff, Tuya) are a single account entry covering many devices; a reload cycles them all.

### Step 4 — If actuator is alive, THEN look at URA

Only after Steps 1–3 exonerate the device:

1. `ha_get_logs(source="system", search="universal_room_automation")` — filter for the room name / entity_id.
2. `sensor.<room>_unavailable_entities` — dead input sensor (motion / lux) can suppress URA's decision.
3. `ha_get_history` on `binary_sensor.<room>_anyone` around the failure — did URA think the room was occupied?
4. Grep for the room's coordinator: `custom_components/universal_room_automation/domain_coordinators/base.py`, `presence.py`, `hvac.py`.

### The trap that cost real hours

Silent-actuator failure class was documented into `CLAUDE.md` only after the AV-closet incident. Prior instinct was "URA regressed"; the correct instinct is "check the physical device first." v5.7.2 added a structured `sensor.<room>_unavailable_entities` for input sensors but NOT actuators (backlog).

---

## S2: Presence flapping / transient-sensor over-trust

**Bug Class #48** (`docs/QUALITY_CONTEXT.md:1878-1928`).

### Shape

A high-variance transient signal (camera person-classifier, mmWave, PIR) fires positive while a reliable persistent signal (phone tracker, BLE, geofence) says the opposite. URA's older code paths treated the transient as authoritative → state oscillation → HVAC presets flip / fans cycle / notifications.

Two shipped fix exemplars — check these are still in effect before assuming a NEW instance (documented line numbers; re-verify with grep):

- **v4.7.13 sleep-state trust:** `aggregation.py:3178`, `hvac.py:915`, `hvac_fans.py:342` — when `house_state == "sleep"`, `ZoneAnyoneBinarySensor.is_on` falls back to `person.state == "home"` for any `zone_persons` entry.
- **v4.7.14 away-state veto:** `presence.py:1896-1922`, `presence.py:403-414`, `presence.py:1992-1998` — when `all_tracked_persons_away AND unidentified_count == 0` → force `HouseState.AWAY` at confidence 0.95. Guest path preserved by the `unidentified_count == 0` guard.

### Discriminating experiment

```
ha_get_history(entity_id="sensor.ura_presence_coordinator_presence_house_state", hours=2)
ha_get_history(entity_id="person.<name>", hours=2)
ha_get_history(entity_id="binary_sensor.<room>_anyone", hours=2)
```

| Pattern | Diagnosis |
|---|---|
| `house_state` bounces `away → arriving → home_day → away` every 60–90 s WHILE `person.*` all monotonic `not_home` | **Bug Class #48 recurrence.** Persistent-signal veto was removed or a new code path was added that ignores it. |
| `house_state` stable but a specific zone flaps `home → away` while occupied | Room-tier substrate / mmwave drop. Check the zone's motion+mmwave+occupancy sensors with `ha_get_history`. |
| `house_state == home_night` and zone Master flips `away` while sleeper is in bed | Historical finding (memo `project_zone_away_when_occupied_home_night_gap`). **Gap APPEARS CLOSED** — the night-trust gate now uses `FAN_TRUST_STATES` (home_night/sleep/waking) in `hvac.py` (~L1245-1290; anchor via log `"HVAC: night-trust person check errored"`). Do not cite `hvac.py:1151`. Re-verify by grepping `FAN_TRUST_STATES` before either dismissing or re-opening. |

### Check attribute exposure

The veto's introspection attrs live on `sensor.ura_presence_coordinator_presence_house_state`:

```
ha_get_state(entity_id="sensor.ura_presence_coordinator_presence_house_state")
# Expect attributes: tracked_persons_count, all_tracked_persons_away, unidentified_count
```

If these attrs are missing → the veto code path never wired up. Re-verify by grepping `presence.py` for `all_tracked_persons_away`.

### Trap

"Camera fires → move must be a person." No. Frigate person-classifier false-positives on shadows/objects were the direct cause of the empty-house `away → arriving` oscillation. **Always** check the phone tracker in parallel before believing a camera.

---

## S3: House stuck in `sleep` / sleep-wake deadlock

**Fixed** in v4.7.18.1 (memo `project_v4_7_18_1_sleep_wake_deadlock`, LIVE + validated). The fix was Option D: raw-signal wake timer + daytime backstop.

### Discriminator

```
ha_get_state(entity_id="sensor.ura_presence_coordinator_presence_house_state")
ha_get_history(entity_id="sensor.ura_presence_coordinator_presence_house_state", hours=12)
```

- Post-fix expected: entered `sleep` around household bedtime; exited cleanly at `sleep_end` (~06:00) OR via daytime backstop.
- If the state is `sleep` mid-morning with no wake → the raw-signal wake timer regressed. Check `presence.py` for the timer setup around `SIGNAL_HOUSE_STATE_*`.

### Known non-persistence

`HouseStateMachine` does NOT persist across restart — it boots `AWAY` by design. If you see `AWAY` immediately after a deploy-restart, that is expected; it should recover on the next presence tick.

### Trap

Do NOT paper over a stuck-sleep by force-setting the house_state via a service call. It masks the real regression and pollutes the fix analysis. Read the logs (`ha_get_logs`) for the wake-timer scheduling first.

---

## S4: Cold-boot actuation storm

**Documented** in memos `project_v4_7_19_live` and `project_v4_7_21_boot_storm_live` (v4.7.21 shipped settle gates).

### Shape

On a cold HA boot, slow cloud devices (Sonoff, some Shelly, Envoy) take 30–120 s to register. During that window their entities are `unavailable`. URA's presence tier sees empty rooms → house aggregates `AWAY` → every configured actuator gets `turn_off` even though a person is present. Recovers on the next inference cycle once entities backfill.

### Discriminating experiment

```
ha_get_logs(source="system", search="Setup of universal_room_automation")   # timing of URA setup
ha_get_history(entity_id="sensor.ura_presence_coordinator_presence_house_state", hours=1)
ha_get_history(entity_id="binary_sensor.<a-room>_anyone", hours=1)
```

If house_state briefly went `away` in the first 60–120 s post-restart AND settled correctly, that is the pre-v4.7.21 storm shape. Post-v4.7.21 the settle gates should suppress the away-actuation storm entirely.

- Presence Predicate A (`real_input`) suppresses 0-signal rooms.
- HVAC Gate 2 holds for 2 cycles.

If you see a fresh storm on a v4.7.21+ deploy, look for a new signal type not passing through the settle gates.

### Trap

Boot storms LOOK like a URA regression but usually indicate a NETWORK event (Wi-Fi outage, ISP hiccup) or a device firmware upgrade rebooting a fleet. Always check `ha_get_history` on non-URA cloud device entities in parallel — if they all flipped `unavailable` at the same wall-clock time, URA didn't do this to you.

---

## S5: "database is locked" / write-queue saturation

**Bug Class #25 (unbounded DELETE)**, **#26 (high-freq DB reads without cache)**, **#27 (orphaned cleanup)**, **#29 (unbudgeted scheduled maintenance)**. `docs/QUALITY_CONTEXT.md:908-1010`. Real incident: 2026-06-09 optimizer DB write-flood → same-day rollback of v5.0.0–v5.2.1 (memo `project_optimizer_db_write_flood_incident_2026_06_09`).

### Shape

The single-writer asyncio queue in `database.py` (documented ~line 45-51; re-verify) saturates. All DB callers block on 35 s timeouts. HA event loop starves. Supervisor watchdog eventually restarts core. Log spam:

- `Update of sensor.X is taking over 10 seconds` (200+ instances)
- `database is locked`
- App WebSocket disconnects

### Discriminating experiment

```
ha_get_logs(source="system", search="taking over 10 seconds")
ha_get_logs(source="system", search="database is locked")
```

Then check write volume via `ura-sqlite`:

```sql
-- rate of anomaly / optimization writes over the last hour
SELECT strftime('%Y-%m-%d %H:%M', timestamp) AS minute, COUNT(*) AS rows
FROM anomalies
WHERE timestamp >= datetime('now', '-1 hour')
GROUP BY minute
ORDER BY minute;
```

If any minute > ~50 rows/min from a single coordinator, you are in write-flood territory.

### Root-cause candidates (ranked)

1. **New per-cycle DB write introduced by a recent cycle.** The v5.0.0 optimizer wrote findings one-by-one (historical anchor `optimization.py:691` is stale; current batched path — `log_findings_batch`, `_cap_findings` — landed post-rollback; grep `optimization.py` for those names). Fix pattern: batch writes, suppress boot-transient findings, throttle per-room sensors.
2. **Sensor `async_update()` querying DB without a cache TTL.** Bug Class #26 — every 30 s. Fix: 5 min cache for zone queries, 30 min for accuracy queries; use `time.monotonic()`.
3. **DELETE without LIMIT** in the write queue (Bug Class #25). Every DELETE must use `WHERE rowid IN (SELECT rowid ... LIMIT 1000)` + batching loop + `asyncio.sleep(0.1)` between batches.
4. **Orphan cleanup catch-up** (Bug Class #27) — a `cleanup_*` / `prune_*` in `database.py` that was never scheduled fires for the first time with months of backlog.

### Recovery (in order)

1. If HA is thrashing NOW: disable the offending coordinator via its switch (e.g. optimization) rather than restarting. A restart re-enters the same storm.
2. If the storm was caused by a recent deploy: **roll back** via HACS to the last known-good version (the v5.0.0–v5.2.1 → v4.7.33 rollback path is the reference).
3. Fix forward: batch, throttle, cache.

### Trap

"database is locked" LOOKS like SQLite corruption. It usually is not. It is the write queue backed up. Do not run `VACUUM` in a panic — it makes the queue worse. Check write RATE first.

---

## S6: Watchdog restart / "Bootstrap stage 2 timeout"

Two distinct sub-causes; do NOT conflate.

### Sub-cause A — Parent-entry reload cascade

Memo: `feedback_parent_entry_reload_watchdog_hazard` (2026-06-03).

Reloading the URA **parent** config entry cascades into full re-setup → event-loop stall → supervisor watchdog restarts core (~5-min outage). Rule: **NEVER reload the URA parent entry.** Reload individual room/zone entries only.

If a watchdog restart follows an operator action, the operator action was very likely a parent-entry reload from the HA UI.

### Sub-cause B — Bug Class #46 re-entrant reload during setup

`docs/QUALITY_CONTEXT.md:1766-1811`.

Symptom in log:
```
CancelledError: Global task timeout: Bootstrap stage 2 timeout
```
with the traceback pointing at `async_setup_entry` (but the `file:line` in the trace is misleading — it catches whatever `await` was running when the 120 s budget hit zero).

Cause: `hass.config_entries.async_update_entry(entry, options=...)` was called from inside `async_setup_entry` AFTER `entry.add_update_listener` was registered. Fires the listener → re-entrant reload → doubles the setup path within one bootstrap window.

Detection grep:

```bash
grep -n "async_update_entry" custom_components/universal_room_automation/__init__.py
```

Cross-reference against the `add_update_listener` registration line. Every `async_update_entry` call MUST fire BEFORE the listener registration. Safe migration calls in `__init__.py` are documented at lines 621, 658, 676, 689, 701, 740, 1087 (pre-listener); listener is around line 2526. **Re-verify these line numbers via grep before quoting them** — they drift.

Fix pattern: **avoid** `async_update_entry` in the setup path entirely. Derive migrated values lazily at read time (see `config_flow.py::_get_shared_thermostat_siblings` for the canonical lazy-derivation pattern).

### Trap — the incomplete fix

v4.7.4.1 tried to fix Bug Class #46 by deferring `async_update_entry` via `hass.async_create_task`. **This did not work** — the deferred task still triggered the reload chain within bootstrap-2's window. v4.7.4.3 shipped the true fix (drop the persist step, derive lazily). Any "defer it" proposal for #46 is a red flag.

---

## S7: RestoreEntity boot-poisoning (Bug Class #52)

`docs/QUALITY_CONTEXT.md:2099-2164`. Real incident: 2026-06-12 Envoy LAN outage → 6 EC sub-switches silently flipped OFF on next boot (`project_envoy_boot_incident_2026_06_12`).

### Shape

A `RestoreEntity.async_added_to_hass` does `target = last_state.state == "on"` with no guard against `unavailable` / `unknown`. When the previous run wrote `unavailable` (any boot race or dependency-integration outage), the next boot coerces that to **False** → `setattr(coordinator, attr, False)` or `self._is_on = False` → user's intended-ON switch silently OFF. No error, no log, no repair issue.

### Discriminating experiment

If the user reports "I had X switched ON, now it's OFF and I don't know why":

```
ha_get_state(entity_id="switch.<the-suspect>")
# then history around the last restart
ha_get_history(entity_id="switch.<the-suspect>", hours=24)
```

If `off` state started at HA start time with no user action → suspect #52.

Grep for the switch factory:
```bash
grep -n 'last_state.state == "on"' custom_components/universal_room_automation/switch.py \
                                     custom_components/universal_room_automation/binary_sensor.py \
                                     custom_components/universal_room_automation/select.py
```

Any hit that is NOT preceded by `if last_state.state not in ("on", "off"): return` is a candidate. Fixed sites: `_ec_switch_factory` around `switch.py:617-648`, `HVACDynamicPresetSwitch` around `switch.py:1040-1075`. Re-verify with grep — line numbers may have drifted.

### Fix pattern (canonical)

```python
if last_state is None:
    return   # first install
if last_state.state not in ("on", "off"):
    _LOGGER.info("Skipping restore for %s — last_state=%s", self.unique_id, last_state.state)
    return   # constructor / options seed wins
target = last_state.state == "on"
```

Do NOT leave `_deferred_restore=True` on the skip path — a later `SIGNAL_*_READY` would still apply the coerced-False value.

### Trap

The prior integration (e.g. Envoy) being back-online now DOES NOT retroactively fix the poisoned RestoreEntity state. The switch stays OFF until the user notices and flips it back. Fix by shipping the guard AND manually re-flipping the affected entities via the UI or `ha_call_service`.

---

## S8: `UnboundLocalError` / conditional-import (Bug Class #34)

`docs/QUALITY_CONTEXT.md:1348-1411`. Recurrences: v4.5.11 (DOMAIN in HVACCoordinator.async_setup), v4.7.20 (`async_dispatcher_send` in `presence.py:_run_inference`).

### Shape

Function-local `from X import Y` inside a conditional branch. Python's compile-time lexical-scope rule promotes `Y` to a local for the entire function body. If ANY textual use of `Y` (before OR after the conditional import) runs when the import branch did not execute → `UnboundLocalError` at runtime.

**Key gotcha:** the v4.5.11 AST guard only caught the case where the use is BEFORE the import line. v4.7.20 evaded it because the uses were textually AFTER — but the import was CONDITIONAL, so line order did not imply execution order.

### Symptoms

- After a deploy: new URA entities appear in HA but are `unavailable` / greyed out forever.
- Log: `UnboundLocalError: local variable 'X' referenced before assignment` — often ~every tick from the coordinator.

### Discriminating experiment

```
ha_get_logs(source="system", search="UnboundLocalError")
ha_get_logs(source="system", search="universal_room_automation")   # look for coordinator setup failures
```

Then grep the presence / hvac coordinator files for bare function-local re-imports of names already imported at module top:

```bash
grep -n "^from \|^import " custom_components/universal_room_automation/domain_coordinators/presence.py | head -30
# then, INSIDE each function, look for `from ... import Y` where Y is on the list above
```

### Fix

Delete the redundant function-local import. Module-level import wins. Do NOT try to "defer" or "lazy" — a Home Assistant coordinator should not have surprise conditional imports.

### Guard

`test_v4_7_20_1_dispatcher_unbound_regression.py` (per QUALITY_CONTEXT) is the reference. It flags ANY bare function-local re-import of a module-top-imported name, regardless of textual use position. Adding a similar test whenever you touch presence.py / hvac.py is cheap insurance.

---

## S9: `add_update_listener` sync handler (Bug Class #28)

`docs/QUALITY_CONTEXT.md:967-1027`. v4.2.24 CRITICAL: months of Living Room / Dining / Patio config edits silently lost.

### Symptom

- User saves an options-flow change. UI shows "Unknown error occurred."
- Second save appears to "succeed" (no banner) but the change didn't actually persist — HA's diff check saw an identical merged dict and short-circuited.
- `core.config_entries` `modified_at` stuck on an old timestamp despite repeated edits.

### Discriminating experiment

```
ha_get_logs(source="system", search="a coroutine was expected, got None")
```

If present → a sync `@callback def` was passed to `entry.add_update_listener(...)`.

```bash
grep -B 3 "add_update_listener" custom_components/universal_room_automation/**/*.py | grep "@callback"
```

Any hit is a bug. Fix: drop `@callback`, change `def` → `async def`. Body unchanged.

Guard test lives at `quality/tests/test_update_listener_async.py` (per QUALITY_CONTEXT). Re-verify path with `ls quality/tests/ | grep update_listener` — the doc may have drifted.

---

## Cross-cutting: pre-blame-URA checklist

Before spending any time in URA code, run this 90-second checklist:

- [ ] `ha_get_state` on the actual actuator — is it `unavailable`?
- [ ] `ha_get_integration <domain>` on the actuator's integration — is the entry loaded?
- [ ] `ha_get_history` on `sensor.ura_presence_coordinator_presence_house_state` — is house state monotonic or bouncing?
- [ ] `ha_get_logs(source="system", search="universal_room_automation")` — any Python tracebacks?
- [ ] `ha_get_logs(source="system", search="taking over 10 seconds")` — any DB write-queue saturation?
- [ ] `stat` on the Samba mount — is the DB path live or stale?
- [ ] Was there a recent deploy? `git log --oneline -20` — a rollback candidate?

If ALL clear and URA still appears to misbehave, THEN dig into the coordinator code.

## Fallback path when MCP or the mount is down

- **`ha-mcp` unreachable** → SSH to HA and use `ha` CLI + core log at `/config/home-assistant.log`. `grep "universal_room_automation"` gives the same info.
- **`ura-sqlite` unreachable / stale cache warning** → SSH to HA and query the live DB directly at `/config/universal_room_automation/data/universal_room_automation.db`.
- **Samba mount stale** → remount per `ura-diagnostics-and-tooling` § Live-access commands (fact-home for the exact `mount_smbfs` invocation). If remount fails, work off SSH until the mount is back.

---

## POST_MORTEM lessons (durable, cite when relevant)

- **v2.3.1–v2.3.3 cascade** (`quality/POST_MORTEM_v2_3_1-2-3.md`): "search comprehensively, fix patterns not files." A None-check bug lived in `coordinator.py` too, not just `sensor.py`. Rushed regex fixes broke class definitions. **Never** run a broad regex without single-file tested + `py_compile` after each file.
- **v3.4.0 camera census** (`quality/POST_MORTEM_v3_4_0.md`): `deploy.sh` only staged `*.py` + `manifest.json` at the time; a strings.json fix was committed locally but never shipped. Lesson: after any deploy, verify the RENDERED artifact (UI labels visible, translations file present) — not just the local git tree.

---

## Provenance and maintenance

**Last verified:** 2026-07-02. All bug-class file:line citations were grepped this session against `develop` tip. Line numbers drift; re-verify with the commands below before quoting.

Re-verification commands (run these before quoting a specific line):

```bash
# Bug classes are the source of truth; re-index if adding a new class:
grep -n "^### Bug Class #" docs/QUALITY_CONTEXT.md

# Silent-actuator runbook lives here (canonical, do not duplicate):
sed -n '88,96p' CLAUDE.md

# Write queue location:
grep -n "queue\|_writer\|_worker" custom_components/universal_room_automation/database.py | head -10

# unavailable_entities sensor (input sensors only, NOT actuators):
grep -n "unavailable_entities\|_get_unavailable_entities" custom_components/universal_room_automation/sensor.py

# Bug Class #48 exemplar fix sites — verify still present:
grep -n "all_tracked_persons_away\|tracked_persons_count" custom_components/universal_room_automation/domain_coordinators/presence.py

# Bug Class #52 exemplar fix sites — verify guard still present:
grep -n 'last_state.state == "on"\|last_state.state not in' custom_components/universal_room_automation/switch.py

# Bug Class #46 — audit `async_update_entry` position vs add_update_listener:
grep -n "async_update_entry\|add_update_listener" custom_components/universal_room_automation/__init__.py

# Bug Class #34 — module-top imports on presence.py that must not be conditionally re-imported:
grep -n "^from \|^import " custom_components/universal_room_automation/domain_coordinators/presence.py | head -30
```

**Sibling docs (do not duplicate — cross-reference):**
- `CLAUDE.md` — canonical operator policy, especially "Troubleshooting" (S1) and "Data Source Verification".
- `docs/QUALITY_CONTEXT.md` — the 53 bug classes; this skill is the debug-triage subset only.
- `quality/POST_MORTEM_v2_3_1-2-3.md` — "search comprehensively, fix patterns not files."
- `quality/POST_MORTEM_v3_4_0.md` — deploy.sh staging gap (strings.json + translations/).
- Skills: `deploy` (release pipeline), `homeassistant_coding` (HA API depth), `ha-dashboard` (Lovelace).

**Open / candidate items** — do NOT state as fact until verified in-session:
- The exact write-queue line range in `database.py` (documented as ~line 45-51 from operator's discovery pass; `grep queue` will pin it).
- The `_get_shared_thermostat_siblings` line number in `config_flow.py` (documented in Bug Class #46 fix pattern; not re-verified this session).
- The `add_update_listener` registration line (~2526) and pre-listener migration call lines (621, 658, 676, 689, 701, 740, 1087) in `__init__.py` — from Bug Class #46; drift-prone.

When any of the above three matter to the decision, grep them first and update this skill's line references in the same commit as the finding.
