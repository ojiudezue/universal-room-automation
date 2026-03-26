# URA v3.18.x Plan: Fan Control, Config Flow Saves, Latent Issues

## Context

Four persistent issues need resolution:
1. **Fan control ignores sleep hours** and room-level / HVAC-level fan systems fight each other
2. **Fans turn off minutes after being turned on** even when room is occupied (occupancy timeout bug)
3. **Reconfig flow dialogs error on first save** (works on second try); Room Device HVAC sub-menu won't save at all
4. **Accumulated latent issues** from v3.14.0-v3.17.9 need triage and scheduling

Additionally:
- **Comfort Coordinator** should be absorbed into HVAC (analysis below)
- **Zone sweep** needs visibility: config toggle + switch entity

---

## Decision: Absorb Comfort Coordinator into HVAC

**Recommendation: Do NOT create a separate Comfort Coordinator.**

HVAC already implements ~80% of what the planned Comfort Coordinator would do:
- Zone-level room condition aggregation (`hvac_zones.py`)
- Comfort violation risk assessment (`hvac_predict.py:591`)
- Fan hysteresis with occupancy gating (`hvac_fans.py`)
- Solar cover management (`hvac_covers.py`)
- Sleep offset clamping (`hvac_preset.py`)
- Zone vacancy sweep (`hvac.py:677`)

What remains unimplemented:
- **Comfort scoring** (0-100 per room) — can be a sensor computed from existing HVAC zone data
- **Circadian lighting** — orthogonal to thermal comfort, add as HVAC sub-module if needed later
- **Per-person preferences** — low priority, single household setpoint works for 95% of homes

**Action:** Remove Comfort Coordinator from roadmap as separate entity. Add comfort scoring to HVAC sensors in v3.18.5. Mark `docs/Coordinator/COMFORT_COORDINATOR.md` as superseded.

---

## v3.18.0 — Config Flow Save Fix + Fan Turn-Off Bug (Priority 1)

### Issue A: Config flow save errors

**Root cause:**
- `_async_update_listener` (`__init__.py:1865`) calls `async_reload(entry.entry_id)` on every options change. Full unload+setup tears down coordinators, platforms, listeners.
- Room HVAC climate step (`config_flow.py:4239`) calls `async_update_entry(zm_entry, ...)` which triggers ZM entry reload *concurrently* with the room entry reload. During ZM unload, `hass.data[DOMAIN]["zone_manager_entry"]` is deleted, racing with the room entry reload.

#### Part A: Decouple ZM auto-populate from room climate save

**File:** `config_flow.py:4222-4248`

Remove synchronous `async_update_entry(zm_entry, ...)`. Use `hass.async_create_task()` to defer the ZM update:

```python
if user_input is not None:
    pending_zm_update = None
    climate_entity = user_input.get(CONF_CLIMATE_ENTITY)
    if climate_entity:
        room_zone = self._get_current(CONF_ZONE) or ""
        if room_zone:
            zm_entry = self._find_zone_manager_entry()
            if zm_entry:
                merged = {**zm_entry.data, **zm_entry.options}
                zones = {k: dict(v) for k, v in merged.get("zones", {}).items()}
                zone_cfg = zones.get(room_zone, {})
                if not zone_cfg.get(CONF_ZONE_THERMOSTAT):
                    zone_cfg[CONF_ZONE_THERMOSTAT] = climate_entity
                    zones[room_zone] = zone_cfg
                    pending_zm_update = (zm_entry, {**zm_entry.options, "zones": zones})

    result = self.async_create_entry(title="", data={**self._config_entry.options, **user_input})
    if pending_zm_update:
        async def _deferred():
            await asyncio.sleep(2)  # let room reload settle
            self.hass.config_entries.async_update_entry(
                pending_zm_update[0], options=pending_zm_update[1])
        self.hass.async_create_task(_deferred())
    return result
```

#### Part B: Skip reload for room entries (threshold-only changes)

**File:** `__init__.py:1865-1867`

Room entries already pick up options changes via `_refresh_config()` (called every coordinator update cycle at `coordinator.py:1380`). Only reload for entity-reference changes or non-room entries:

```python
RELOAD_REQUIRED_KEYS = {
    CONF_MOTION_SENSORS, CONF_MMWAVE_SENSORS, CONF_OCCUPANCY_SENSORS,
    CONF_LIGHTS, CONF_FANS, CONF_HUMIDITY_FANS, CONF_COVERS,
    CONF_CLIMATE_ENTITY, CONF_ROOM_NAME,
}

async def _async_update_listener(hass, entry):
    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM)
    if entry_type != ENTRY_TYPE_ROOM:
        await hass.config_entries.async_reload(entry.entry_id)
        return
    # Room entry: check if reload is needed
    changed = {k for k in entry.options if entry.options.get(k) != entry.data.get(k)}
    if changed & RELOAD_REQUIRED_KEYS:
        await hass.config_entries.async_reload(entry.entry_id)
    # else: _refresh_config() picks it up next cycle
```

#### Part C: Guard concurrent reload race

**File:** `__init__.py:1538-1542`

Set `zone_manager_entry` to `None` instead of deleting on unload. Add `is not None` checks where read.

### Issue B: Fan turn-off bug (occupancy timeout)

**Root cause found:** `coordinator.py:1116`:
```python
remaining = max(0, self._occupancy_timeout - int(elapsed))
data[STATE_OCCUPIED] = remaining > 0
```
When occupancy timeout expires (default 300s = 5 min after last sensor activity), `occupied` goes False. `automation.py:951` immediately turns fans off: `if not occupied: turn_off_fans`. No grace period for fan control.

Additionally, HVAC fan controller's min_runtime check (`hvac_fans.py:247`) is bypassed when `occupied=False`, so vacancy causes immediate fan shutoff even if the fan just turned on.

#### Fix 1: Fan-specific occupancy grace period

**File:** `automation.py:928-960`

Add a separate fan occupancy grace period. When occupancy transitions True→False, don't turn off fans immediately — hold for `CONF_FAN_VACANCY_HOLD` seconds (default 300s = 5 min):

```python
# After line 935 (fan_control_enabled check):
fan_vacancy_hold = self.config.get(CONF_FAN_VACANCY_HOLD, 300)

# Replace line 951's simple `not occupied` check:
if not occupied:
    if self._fan_vacancy_start is None:
        self._fan_vacancy_start = dt_util.now()
    vacancy_elapsed = (dt_util.now() - self._fan_vacancy_start).total_seconds()
    if vacancy_elapsed < fan_vacancy_hold:
        occupied = True  # Override: hold fans during grace period
else:
    self._fan_vacancy_start = None  # Reset on re-occupation
```

This means fans stay on for up to 5 additional minutes after occupancy timeout, giving mmWave/PIR time to re-trigger.

#### Fix 2: HVAC min_runtime applies regardless of occupancy

**File:** `hvac_fans.py:247-251`

Remove the `and occupied` condition:
```python
# Before (buggy):
if room_fan.is_on and room_fan.last_on_time and occupied:

# After (fixed):
if room_fan.is_on and room_fan.last_on_time:
```

Min runtime should protect against rapid cycling whether or not occupancy is True.

#### Fix 3: Minor — fix int() truncation

**File:** `coordinator.py:1116`
```python
# Before:
remaining = max(0, self._occupancy_timeout - int(elapsed))
# After:
remaining = max(0.0, self._occupancy_timeout - elapsed)
```

### Tests (12-15 new)
- `test_config_flow_save.py`: Room climate save succeeds, ZM not reloaded concurrently, first-save works
- Fan vacancy hold: fan stays on for grace period after occupancy goes False
- Fan vacancy hold expires: fan turns off after grace period
- HVAC min_runtime: fan stays on for min_runtime even when occupied=False
- Re-occupation during vacancy hold resets timer

### Files
- `config_flow.py` (~30 lines)
- `__init__.py` (~30 lines)
- `automation.py` (~20 lines)
- `coordinator.py` (~3 lines)
- `hvac_fans.py` (~3 lines)
- `const.py` (~2 lines: CONF_FAN_VACANCY_HOLD)

---

## v3.18.1 — Fan Sleep Awareness (Room + HVAC)

Combines the previously separate v3.18.1 and v3.18.2.

### Room-Level Sleep

**File:** `const.py` — Add:
```python
CONF_FAN_SLEEP_POLICY: Final = "fan_sleep_policy"
FAN_SLEEP_OFF = "off"
FAN_SLEEP_REDUCE = "reduce"
FAN_SLEEP_NORMAL = "normal"
DEFAULT_FAN_SLEEP_POLICY = FAN_SLEEP_REDUCE
```

**File:** `automation.py:928` — After enabled/entity/vacancy guards:
```python
sleep_speed_cap = None
if self.is_sleep_mode_active():
    policy = self.config.get(CONF_FAN_SLEEP_POLICY, DEFAULT_FAN_SLEEP_POLICY)
    if policy == FAN_SLEEP_OFF:
        await self._safe_service_call("homeassistant", SERVICE_TURN_OFF, {"entity_id": fans})
        return
    elif policy == FAN_SLEEP_REDUCE:
        sleep_speed_cap = 33
```
Cap speed: `speed_pct = min(speed_pct, sleep_speed_cap) if sleep_speed_cap else speed_pct`

Same for humidity fans at line 1001.

**File:** `config_flow.py` — Add to `async_step_sleep_protection` (line 4325).

### HVAC-Level Sleep

**File:** `hvac_fans.py:140` — Add `house_state: str` param to `update()`:
- When `house_state == "sleep"`, cap speed at `FAN_SPEED_LOW_PCT` (33%)
- Energy `fan_assist` during sleep: allow but capped

**File:** `hvac.py` — Pass `self._house_state` to `fan_controller.update()`

### Dual Control Deconfliction

**File:** `automation.py:928` — Add before fan logic:
```python
if self._is_hvac_managing_fans():
    return  # defer to HVAC coordinator
```

New method checks: `CONF_HVAC_COORDINATION_ENABLED` + HVAC coordinator enabled + room discovered in `fan_controller._room_fans`.

| Scope | Controller | Active when |
|-------|-----------|-------------|
| Room | `automation.py` | `FAN_CONTROL_ENABLED` AND NOT HVAC-managed |
| Zone | `hvac_fans.py` | Room in HVAC zone with discovered fans |
| House | Energy `fan_assist` | Energy constraint with `fan_assist=True` |

### Tests (10-12 new)
- Room fan sleep policy="off" turns fans off during sleep
- Room fan sleep policy="reduce" caps at 33% during sleep
- HVAC fan speed capped during sleep house state
- Energy fan_assist capped during sleep
- Room fans defer when HVAC is managing
- Room fans normal without HVAC coordination

### Files
- `automation.py` (~40 lines)
- `const.py` (~6 lines)
- `hvac_fans.py` (~20 lines)
- `hvac.py` (~5 lines)
- `config_flow.py` (~15 lines)
- `strings.json` + `translations/en.json`

---

## v3.18.2 — Zone Sweep Visibility + Zone State Persistence

### Part A: Zone Sweep Toggle + Sensor

**Problem:** Zone sweep (`hvac.py:677`) exists but is invisible to users:
- `CONF_ZONE_VACANCY_SWEEP_ENABLED` in `hvac_const.py` but NOT in config_flow.py
- No switch entity to toggle it live
- Status only visible as attributes on HVAC coordinator sensor

#### Add config flow UI

**File:** `config_flow.py` — In `async_step_coordinator_hvac` (line 2563), add:
```python
vol.Optional(
    CONF_HVAC_ZONE_SWEEP_ENABLED,
    default=self._get_current(CONF_HVAC_ZONE_SWEEP_ENABLED, True),
): selector.BooleanSelector(),
```

Also add to zone-level config in `async_step_zone_hvac` (line 3699) for per-zone control.

#### Add switch entity

**File:** `switch.py` — Add `URAHvacZoneSweepSwitch`:
- `switch.ura_hvac_zone_sweep` — global toggle for vacancy sweep
- RestoreEntity for persistence across restarts
- On toggle: update `zone.vacancy_sweep_enabled` for all zones
- Attributes: `last_sweep_time`, `sweeps_today`, `zones_swept`

**File:** `strings.json` — Add labels/descriptions.

### Part B: Zone Intelligence State Persistence

**Problem:** ZoneState fields lost on restart (`last_occupied_time`, `vacancy_sweep_done`, etc.).

**File:** `hvac_zones.py` — Add:
- `async_save_state(store)`: Serialize to `hass.helpers.storage.Store`
- `async_restore_state(store)`: Apply persisted state to ZoneState objects

**File:** `hvac.py`:
- After `async_discover_zones()`, call `zone_manager.async_restore_state(store)`
- Every 5 cycles (25 min): `zone_manager.async_save_state(store)`
- In `async_teardown`: `zone_manager.async_save_state(store)`

Use `Store(hass, 1, f"{DOMAIN}.hvac_zone_state")`.

### Part C: AC Reset Telemetry + Retry

**File:** `hvac_override.py`:
1. After restore service call, schedule verification at T+30s
2. Read climate entity state; if still "off", retry (max 2 retries)
3. After max retries, fire CRITICAL NM alert
4. Log pre/post state

### Tests (12-15 new)
- Zone sweep toggle enables/disables sweeps
- Zone sweep switch persists across restart
- Zone state persists and restores correctly
- Stale zone state (>4h) discarded on restore
- AC reset restore retries on failure
- AC reset alert fires after max retries

### Files
- `config_flow.py` (~20 lines)
- `switch.py` (~60 lines)
- `hvac_zones.py` (~60 lines)
- `hvac.py` (~25 lines)
- `hvac_override.py` (~40 lines)
- `strings.json` + `translations/en.json`

---

## v3.18.3 — Thread-Safety Audit

**Problem:** `async_write_ha_state()` in signal handlers. Partially fixed in v3.15.2.

**Fix:** In all `_handle_update`/`_handle_*_changed` methods registered via `async_dispatcher_connect`, replace `self.async_write_ha_state()` with `self.async_schedule_update_ha_state()`.

**Files:** `sensor.py`, `binary_sensor.py`, `switch.py`, `select.py`, `number.py`, `aggregation.py`
**Scope:** ~80 call sites, mechanical replacement.

### Tests (2-3 new)
- Signal-driven state update safe from threading errors

---

## v3.18.4 — Tech Debt: Comfort Scoring + Cleanup

- **Comfort scoring sensor** (`sensor.py`): Implement 0-100 per-room score using HVAC zone data (temp delta 40% + humidity 30% + occupancy-weighted 30%). House-level average.
- **Efficiency scoring sensor**: Duty cycle ratio from zone intelligence data.
- **Mark `docs/Coordinator/COMFORT_COORDINATOR.md` as superseded** by HVAC absorption.
- **Config flow UX**: Better person-zone mapping helper text.

### Files
- `sensor.py` (~100 lines)
- `config_flow.py`, `strings.json` (~20 lines)

---

## Sequencing

```
v3.18.0 Config Flow Save +     <-- Ship first: unblocks reconfiguration
         Fan Turn-Off Bug            + fixes the immediate fan annoyance
    |
v3.18.1 Fan Sleep +            <-- Fan policy constants + deconfliction
         Deconfliction
    |
v3.18.2 Zone Sweep Visibility  <-- Zone persistence + AC reset telemetry
         + Zone Persistence         + sweep toggle/switch
    |
v3.18.3 Thread Safety Audit    <-- Independent, mechanical
    |
v3.18.4 Tech Debt + Comfort    <-- Comfort scoring absorbed into HVAC
         Scoring
```

## Deferred (not in this series)
- BlueBubbles/Telegram NM channels (C4b+)
- Bayesian Predictive Intelligence (v4.0.0)
- Load Shedding activation (needs real-world testing)
- Circadian lighting (future HVAC enhancement if needed)
- Per-person temperature preferences (low priority)

## Verification

Each cycle:
1. `PYTHONPATH=quality python3 -m pytest quality/tests/ -v` — all 1169+ existing + new pass
2. Two-review protocol against `docs/QUALITY_CONTEXT.md`
3. Deploy via `./scripts/deploy.sh`, test on live HA instance
4. Config flow: manually test save on all entry types
5. Fan control: verify fans respect sleep hours + don't turn off prematurely
6. Zone sweep: verify toggle visible in config flow and switch entity works
