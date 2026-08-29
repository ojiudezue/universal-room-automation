---
name: ura-ha-platform-reference
description: URA-specific Home Assistant platform reference — the theory you need to safely modify the URA integration. Config-entry types (ROOM/ZONE/CM/INTEGRATION), options-flow update-listener (reload vs in-place), custom coordinator hierarchy (URA does NOT use DataUpdateCoordinator), the SIGNAL_* dispatcher bus + subscription-cleanup trap (Bug Class #50), RestoreEntity unavailable→OFF poisoning (Bug Class #52), background-task tracking (Bug Class #19), function-local import shadow (Bug Class #34), after_dependencies stranding (Envoy 2026-06-12 incident), silent-actuator no-op on unavailable, and why .storage/ is read-only. Load this BEFORE touching __init__.py, config_flow.py, options_flow, any coordinator constructor / async_added_to_hass / async_will_remove_from_hass, or any manifest.json edit. Skip if you are only editing pure business logic inside an already-wired coordinator method — see homeassistant_coding for generic HA how-to.
---

# URA × Home Assistant Platform Reference

Ground truth as of **2026-07-02**, URA **v5.7.2**. All file:line citations were verified this session against the working tree at `/Users/okosisi/Code/universal-room-automation`.

This skill is the platform-plumbing pack. For generic HA how-to (template sensors, dashboards, generic coordinator boilerplate) use the sibling **homeassistant_coding** skill; it does not know URA's traps.

## When to use this skill

Load before you:

| Task | Why |
|---|---|
| Add/modify a `SIGNAL_*` producer or consumer | Cleanup trap (#50) + function-local import trap (#34) |
| Write any `RestoreEntity` subclass or `async_added_to_hass` | Unavailable-coercion (#52) is silent, no error/log/repair |
| Schedule a background task off a coordinator | Untracked task (#19); leaks across reload |
| Touch `manifest.json` (`dependencies`, `after_dependencies`, `requirements`) | `after_dependencies` stranded whole house 2026-06-12 |
| Add a new `CONF_ENTRY_TYPE` handler in `__init__.py` | Four types exist; each has its own setup/unload path |
| Add an OptionsFlow field | Decide: reload-on-change vs in-place push (allowlist) |
| Actuate an HA entity from a coordinator (`hass.services.async_call`) | Silent no-op when target is `unavailable` |
| Read/write anything under `.storage/` | Don't. Use the config-entry + options API |

## When NOT to use this skill

- **Pure business logic inside an existing coordinator method** (no lifecycle, no dispatcher, no restore) → the coordinator design doc `docs/Coordinator/<NAME>.md` is closer to your problem.
- **Dashboard / Lovelace / template-sensor** work → `.claude/skills/ha-dashboard/` and `.claude/skills/homeassistant_coding/`.
- **Anything mutating git** → `.claude/skills/deploy/`.

---

## 1. Entry-type dispatcher (`__init__.py`)

URA is one HA integration with **four config-entry types**, discriminated by `entry.data[CONF_ENTRY_TYPE]`. Each type has its own `async_setup_entry` branch, its own PLATFORMS list, and its own unload path. Do NOT collapse them.

Verified constants in `custom_components/universal_room_automation/const.py:50-54`:

| `CONF_ENTRY_TYPE` value | Constant | Role |
|---|---|---|
| `"integration"` | `ENTRY_TYPE_INTEGRATION` | Global CM parent-entry (DB, activity logger, integration-wide services) |
| `"coordinator_manager"` | `ENTRY_TYPE_COORDINATOR_MANAGER` | The CM (owns domain coordinators). Setup at `__init__.py:2955` |
| `"room"` | `ENTRY_TYPE_ROOM` | Per-room entry (~90+ entities). Forward at `__init__.py:3106` |
| `"zone_manager"` | `ENTRY_TYPE_ZONE_MANAGER` | Zone parent (owns zones). Forward at `__init__.py:3133` |
| `"zone"` | `ENTRY_TYPE_ZONE` | Individual zone entry. Forward at `__init__.py:3455` |

**Rule.** Every new setup path must:

1. Register update_listener via `entry.async_on_unload(entry.add_update_listener(_async_update_listener))` (canonical sites: `__init__.py:2958, 3108, 3344, 3452`).
2. Forward with `hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)` — the `s` matters (batched).
3. Unload with the matching `async_unload_platforms` (sites: `__init__.py:3530, 3690, 3713, 3721`).
4. Any listener registered outside `entry.async_on_unload` must be tracked in `hass.data[DOMAIN]` (e.g. `unsub_activity_prune` at `__init__.py:1322`) and explicitly cancelled in `async_unload_entry`.

---

## 2. `hass.data[DOMAIN]` conventions

URA does NOT store per-entry data under `hass.data[DOMAIN][entry.entry_id]`; it uses **named global slots** because coordinators are process-wide singletons owned by the CM entry.

Verified sites in `__init__.py`:

| Key | Owner | Notes |
|---|---|---|
| `"integration"` | CM parent entry | Set at `:1035`; the parent entry object |
| `"database"` | DB singleton | Guarded by `_db_init_lock` (asyncio.Lock) at `:1270` — **double-init race is real** |
| `"activity_logger"` | Activity logger | `:1296` |
| `"coordinator_manager"` | CM instance | Read by every domain coordinator |
| `"unsub_activity_prune"` | Time-listener unsub | Must be called in unload path |
| `"unsub_nightly_maintenance"` | Time-listener unsub | Same |
| `"room_last_applied_options"` | Options diff snapshot | `:4721` — feeds the reload-suppress allowlist |

**Idiom** (safe under concurrent setup): `hass.data.setdefault(DOMAIN, {})[key] = value`. See `__init__.py:984`.

**Never** assume the DOMAIN dict exists; other entry types can race you into a `KeyError` if you skip `setdefault`.

---

## 3. Options flow: reload vs in-place push

URA's `_async_update_listener` (`__init__.py:4688`) is NOT the default HA "just reload on any option change" pattern. Options writes are classified.

Two allowlists exist:

- **ROOM `_ROOM_SUPPRESS_KEYS`** (`__init__.py:4714`): comfort-slider keys that persist without a reload (a ROOM reload = ~90 entity teardown).
- **CM `OPTIONS_RELOAD_SUPPRESS_KEYS`**: CM keys pushed live to coordinator attributes.

Decision tree when adding an OptionsFlow field:

1. **Does anything read it at runtime OTHER THAN a Number/Switch entity in the same process?** If NO → add to the suppress-allowlist and push live (avoid the reload storm). If YES → default to reload.
2. **Is the field consumed by an already-instantiated coordinator via `getattr(...)`?** Then a live-push via `setattr` on the coordinator is enough — do NOT reload.
3. **Bug Class #32 trap** (`docs/QUALITY_CONTEXT.md:1144`): a form field with no runtime reader is dead config. Every new field must have a demonstrated read site — grep it before shipping.

**Historical anchor.** `v4.0.5` changed reload from `await async_reload()` (blocked OptionsFlow HTTP request >30s → aiohttp cancelled mid-reload → half-unloaded entry) to a background task. Don't undo this — see `__init__.py:4691-4695`.

---

## 4. Coordinators — URA does **not** use `DataUpdateCoordinator`

URA has its own hierarchy. If you inherit from `homeassistant.helpers.update_coordinator.DataUpdateCoordinator`, you are in the wrong file.

- Base: `BaseCoordinator` (ABC) at `custom_components/universal_room_automation/domain_coordinators/base.py:154`.
- Domain coordinators subclass `BaseCoordinator`, live in `domain_coordinators/` (28 files verified), and are owned by the **CoordinatorManager** (`domain_coordinators/manager.py`).
- Entities inherit from URA base classes (`UniversalRoomEntity`, etc.), NOT `CoordinatorEntity`.
- Coordinators are **process singletons** — you get them via `hass.data[DOMAIN]["coordinator_manager"]`, never by constructing directly.

When adding a new coordinator: read `docs/Coordinator/<CLOSEST_SIBLING>.md`, then copy the closest sibling's constructor + async_start + async_stop shape. Do not invent a new lifecycle.

---

## 5. Dispatcher signals (`async_dispatcher_connect` / `async_dispatcher_send`)

Signal constants live in `domain_coordinators/signals.py` (30+ signals verified). Prefix rule: `SIGNAL_<PRODUCER>_<VERB>` or `SIGNAL_<PRODUCER>_READY` for readiness gates.

### 5.1 Producer pattern

```python
from homeassistant.helpers.dispatcher import async_dispatcher_send
from custom_components.universal_room_automation.domain_coordinators.signals import (
    SIGNAL_DATABASE_READY,
)
async_dispatcher_send(hass, SIGNAL_DATABASE_READY)
```

Verified producer at `__init__.py:1287, 1692, 2680, 3389`.

### 5.2 Consumer pattern — **avoid Bug Class #34**

Function-local `from homeassistant.helpers.dispatcher import async_dispatcher_send` inside a `try:` branch shadows a module-level import → `UnboundLocalError` in the sibling branch. Shipped v4.7.20.0, hotfixed in v4.7.20.1. See `docs/QUALITY_CONTEXT.md:1348`.

**Correct shape:** import at module top or inside a single function scope with no rebinding elsewhere.

### 5.3 Cleanup — **avoid Bug Class #50**

The unsubscribe returned by `async_dispatcher_connect` MUST outlive periodic list rebuilds. Storing it in a list that a periodic worker clears (e.g. `self._subscriptions.clear()` inside `_update_signal_subscriptions()`) silently drops the sub, and consumers stop receiving. Exemplar: v4.7.24 substrate CRITICAL B-C1 (`docs/QUALITY_CONTEXT.md:1993`).

**Safe patterns:**
- Entity subscriber → return the unsub through `self.async_on_remove(unsub)` inside `async_added_to_hass`.
- Coordinator subscriber → store in a dict keyed by intent (`self._unsubs["substrate"] = unsub`), NOT a list that anything else rebuilds.
- On coordinator teardown, call every stored unsub in `async_stop`.

### 5.4 Readiness-gate signals

DB / NM / Bayesian / EnergyCoordinator all fire `SIGNAL_*_READY` after successful init. Downstream consumers that need them subscribe FIRST, then check `is not None`, then queue their setup. Do NOT block coordinator setup on another coordinator's readiness — subscribe-and-defer.

---

## 6. `RestoreEntity` — the unavailable-coercion trap (Bug Class #52)

**Silent failure mode.** If the previous run wrote `unavailable` to `core.restore_state`, then `target = last_state.state == "on"` coerces to `False`, and a `setattr(coordinator, attr, False)` silently flips a user-intended-ON switch OFF. No error, no log, no repair issue.

Verified live incident 2026-06-12: 6 EC sub-switches silently flipped OFF (`switch.py:617-648` at time of incident; `HVACDynamicPresetSwitch` at then-`switch.py:1040-1075` had identical risk).

### Canonical fix — verified live at `custom_components/universal_room_automation/switch.py:699-736`

```python
last_state = await self.async_get_last_state()
if last_state is None:
    # First install — constructor/options seed is source of truth.
    # Notify any pending-restore accounting so it doesn't stay >0.
    return
if last_state.state not in ("on", "off"):
    _LOGGER.info(
        "Skipping RestoreEntity restore for %s — last_state=%s — "
        "keeping options-seeded value %s",
        self.unique_id, last_state.state, current_value,
    )
    return  # DO NOT fall through to `target = last_state.state == "on"`
target = last_state.state == "on"
# ... apply target
```

**Checklist when writing a new `RestoreEntity`:**

- [ ] Guard `last_state is None` (first install).
- [ ] Guard `last_state.state not in ("on", "off")` — or the valid-enum set for your entity.
- [ ] If your entity feeds a pending-restore-count sensor, `notify_*_restore_complete()` on BOTH the None and skip paths (v4.7.34 D-fix).
- [ ] Options / constructor seed is authoritative on both skip paths.

---

## 7. Background tasks — Bug Class #19

`hass.async_create_task(...)` creates an untracked task that leaks across entry reload. Use `entry.async_create_background_task(...)` so it's cancelled on unload.

Verified correct sites: `__init__.py:1387, 1497, 2773 (comment), 2878`.

The one **verified-legitimate exception** in the tree is at `__init__.py:4808`:

```python
hass.async_create_task(  # noqa: untracked-ok — self-reload must outlive entry unload; standard HA core pattern (plex, flux_led, tile, epson)
    ...
)
```

Every other use of `hass.async_create_task` in URA code is a bug. If you must use it, follow the same `# noqa: untracked-ok — <why>` comment convention.

`entry.async_create_task` vs `entry.async_create_background_task`: prefer **background** for anything that fires-and-forgets after setup returns. `async_create_task` blocks setup completion.

---

## 8. Service calls silently no-op on `unavailable` targets (silent-actuator)

**Root cause.** `hass.services.async_call("light", "turn_on", {"entity_id": ...})` does not raise if the entity is `unavailable`. The room appears to detect occupancy, the coordinator emits the intent, the log says "turning on" — and nothing happens.

See CLAUDE.md § "Troubleshooting — room automation broke" for the on-call runbook. Verified call sites: `domain_coordinators/hvac.py:1104, 1326, 1742, 1798, 1811`.

**Before shipping any new actuation path:**

1. Enumerate every entity the coordinator writes.
2. Ensure `sensor.<room>_unavailable_entities` (`sensor.py:1623` `UnavailableEntitiesSensor`) covers the target — as of v5.7.2 this now covers actuators, not only input sensors (Recent MEMORY: "silent actuator failure").
3. If actuation is safety-critical, read the target's state BEFORE the call and either short-circuit-with-log or route through NM.

**Never** treat "no error in the log" as evidence the light turned on. Read `light.state` post-call, or the room's `last_changed`.

---

## 8.5 Camera entity-suffix resolution (Frigate `_2` disambiguation)

Frigate / UniFi Protect / Reolink / Amcrest / Dahua entity-suffix rules and `_2` disambiguation are in `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` §1. Never string-build Frigate entity ids — resolve via `_has_any_suffix_stripped` / `_resolve_face_entity_id`.

---

## 9. `manifest.json` — `after_dependencies` stranding

**Failure mode.** `after_dependencies: ["<domain>"]` blocks URA setup until that integration finishes. If the named integration HANGS (dead device, network partition), HA fires *"Setup timed out for stage 2 — moving forward"* and **cancels queued URA entry setups**. All URA entries stay `not_loaded`; whole-house automation down; zero URA code runs; zero URA errors logged.

Verified 2026-06-12 incident: `after_dependencies: ["enphase_envoy"]` (added v4.2.29, removed in the boot-decoupling cycle). Full write-up: `docs/planning/PLANNING_ec_envoy_boot_decoupling.md:17`.

**Rule.** URA's current `manifest.json` (verified 2026-07-02) declares `dependencies: ["http", "frontend", "logbook"]` and NO `after_dependencies`. Keep it that way. If a coordinator needs another integration's data, subscribe-and-defer via a readiness gate (§5.4), do NOT gate on the manifest.

`dependencies` is different — HA guarantees those are loaded before URA (`http`, `frontend`, `logbook` are all HA-core, they cannot hang). Do NOT add third-party integrations to `dependencies`.

---

## 10. `.storage/` is READ-ONLY from code

`.storage/core.config_entries`, `.storage/core.restore_state`, `.storage/core.device_registry`, etc. are HA's internal state. Editing them from URA code is not supported and will break on the next HA upgrade.

**Correct APIs:**

| Goal | Use this |
|---|---|
| Persist config | `entry.options` via `config_entries.async_update_entry(entry, options=...)` |
| Persist per-entity state across restart | `RestoreEntity.async_get_last_state()` (see §6) |
| Read config-entry state during an incident | Live-mount read only. Sequence in CLAUDE.md § Data Source Verification |
| Change a device area | Device registry API (`homeassistant.helpers.device_registry`) |

**Live-read via Samba mount** (during incident triage — read-only): exact `mount_smbfs` command + live DB path + MCP tool inventory (`ha_get_state`, `ha_get_integration`, `ha_get_logs`) live in `ura-diagnostics-and-tooling` § Live-access commands (fact-home). If the mount is down, MCP tools go over the HA REST/WebSocket API.

---

## 11. Fast reference — recurrent bug classes in URA/HA glue

| # | Class | Where | Fix in one line |
|---|---|---|---|
| 19 | Untracked background tasks | any `hass.async_create_task` in setup | Use `entry.async_create_background_task` |
| 32 | Form field with no runtime reader | new OptionsFlow field | Grep for a read site before ship |
| 34 | Function-local import shadow | try/except with import in one branch | Import at module top |
| 48 | Transient sensor over-trust | presence aggregation | Reliable-truth veto path |
| 50 | Dispatcher sub in a periodic-cleared list | coordinator subscription list | Store in dict or `async_on_remove` |
| 52 | RestoreEntity `unavailable` coercion | any `RestoreEntity` subclass | Guard `last_state.state not in ("on","off")` |
| 53 | Computed-but-not-consumed control value | shared clamp threaded through many emission sites | Adversarial-completeness re-enumeration |

Full catalogue: `docs/QUALITY_CONTEXT.md` (53 classes as of 2026-07-02; header may say 51 — stale).

---

## 12. Pre-ship gate for platform-plumbing changes

Before you deploy any change that touches this skill's surface, run:

- [ ] `PYTHONPATH=quality python3 -m pytest quality/tests/ -v` — full suite green vs baseline
- [ ] Grep for `hass.async_create_task` you added; each must have `# noqa: untracked-ok — <why>` or be `entry.async_create_background_task`
- [ ] Every new `SIGNAL_*` producer has ≥1 consumer; every new consumer's unsub is stored where a periodic worker cannot clear it
- [ ] Every new `RestoreEntity` has the `("on","off")` guard (§6 checklist)
- [ ] `manifest.json` diff has NO new `after_dependencies` entries
- [ ] `entry.data[CONF_ENTRY_TYPE]` handling exists for every entry-type branch you changed
- [ ] No path writes under `.storage/`
- [ ] Live-validation criteria written into `docs/readmes/README_v<version>.md` BEFORE deploy (CLAUDE.md mandate)

---

## Provenance and maintenance

Facts date-stamped **2026-07-02** against URA **v5.7.2**. Re-verify anything below if HA APIs or URA structure drift:

```bash
# Manifest
cat custom_components/universal_room_automation/manifest.json

# Entry-type constants
grep -n "^ENTRY_TYPE_" custom_components/universal_room_automation/const.py

# Update listener + forward/unload sites
grep -n "add_update_listener\|async_forward_entry_setups\|async_unload_platforms" \
  custom_components/universal_room_automation/__init__.py

# Signal catalogue
grep -n "^SIGNAL_" custom_components/universal_room_automation/domain_coordinators/signals.py

# RestoreEntity guard exemplar
sed -n '690,745p' custom_components/universal_room_automation/switch.py

# Background-task discipline
grep -n "async_create_background_task\|async_create_task" \
  custom_components/universal_room_automation/__init__.py

# Bug-class docs (stale header; count sections)
grep -c "^### Bug Class #" docs/QUALITY_CONTEXT.md
```

If any command above disagrees with this skill's text, the repo wins — update the skill.

## Cross-references

- `.claude/skills/homeassistant_coding/` — generic HA how-to (template sensors, dashboards, coordinator boilerplate). Not URA-specific.
- `.claude/skills/deploy/` — full deploy pipeline. Do not skip.
- `docs/QUALITY_CONTEXT.md` — canonical bug-class catalogue.
- `docs/Coordinator/<NAME>.md` — per-coordinator design intent; read before scoping changes.
- `CLAUDE.md` — project policy (tiered review, No-Fabrication, Institutional-Context-First, live-mount commands, silent-actuator runbook). Canonical over this skill.
