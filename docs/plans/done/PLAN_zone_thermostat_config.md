# Plan: Zone Thermostat Configuration

**Date:** 2026-03-03
**Status:** Planned (not yet implemented)
**Scope:** Add direct thermostat entity setting to zone configuration

---

## Current Behavior

Zone HVAC preset control is handled by `ZoneOccupancySensor` in `aggregation.py` (line ~2294).
When zone occupancy changes (all vacant / any occupied), `_handle_zone_occupancy_change()`
calls `_get_zone_climate_entity()` (line 2397) which resolves the thermostat by **room traversal**:

```python
def _get_zone_climate_entity(self) -> str | None:
    """Return the climate entity from the first zone room that has one configured."""
    for coord in self._get_zone_coordinators():
        climate = coord.entry.options.get(
            CONF_CLIMATE_ENTITY,
            coord.entry.data.get(CONF_CLIMATE_ENTITY),
        )
        if climate:
            return climate
    return None
```

This iterates over all room coordinators in the zone and returns the **first** room's
`climate_entity` it finds. This is **non-deterministic** — the order depends on coordinator
iteration order, which can change across restarts or when rooms are added/removed.

### Zone preset constants (const.py:686-689)

- `CONF_ZONE_VACANT_PRESET = "zone_vacant_preset"` (default: `"away"`)
- `CONF_ZONE_OCCUPIED_PRESET = "zone_occupied_preset"` (default: `"home"`)

These exist but have **no config flow UI**. They control occupancy-based preset switching
(zone vacant → "away", zone occupied → "home"). **Preset UI is deferred** — the HVAC
Coordinator (Cycle 6, v3.6.0-c6) will supersede this simple preset logic with richer
control strategies (PRESET_BASED / TEMPERATURE_BASED / HYBRID modes, energy constraint
response, sleep protection offsets, staggered heat calls). Adding preset UI now would
create throwaway work.

---

## Proposed Change

Add `CONF_ZONE_THERMOSTAT` — an optional climate entity selector on each zone configuration.

- **When set:** use this entity directly for HVAC preset control (deterministic)
- **When not set:** fall back to current room-traversal behavior (backward compatible)

This setting will also be consumed by the future HVAC Coordinator (C6), which needs
the same "which thermostat controls this zone?" mapping. Adding it now means C6 can
read it directly rather than re-inventing thermostat discovery.

---

## Implementation

### Step 1: Add constant — `const.py`

Add near line 82 (next to other `CONF_ZONE_*` constants):

```python
CONF_ZONE_THERMOSTAT: Final = "zone_thermostat"
```

### Step 2: Add config flow step — `config_flow.py`

#### 2a. Add `"zone_hvac"` to zone config menu

In `async_step_zone_config_menu()` (line 2199), add to `menu_options`:

```python
return self.async_show_menu(
    step_id="zone_config_menu",
    menu_options=[
        "zone_rooms",
        "zone_media",
        "zone_hvac",    # NEW
    ],
)
```

#### 2b. Add `async_step_zone_hvac()`

Model after `async_step_zone_media()` (line 2370). Shows only:
- Climate entity selector for `CONF_ZONE_THERMOSTAT`

```python
async def async_step_zone_hvac(self, user_input=None):
    """Configure zone thermostat."""
    # ... read current value from zone data using standard ZM pattern ...

    if user_input is not None:
        # ... write to zone data using standard ZM pattern ...
        return await self.async_step_zone_config_menu()

    data_schema = vol.Schema({
        vol.Optional(
            CONF_ZONE_THERMOSTAT,
            default=current_thermostat or vol.UNDEFINED,
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="climate")
        ),
    })

    return self.async_show_form(
        step_id="zone_hvac",
        data_schema=data_schema,
    )
```

#### 2c. Import `CONF_ZONE_THERMOSTAT` in config_flow.py const import block

### Step 3: Update thermostat resolution — `aggregation.py`

Modify `_get_zone_climate_entity()` at line 2397:

```python
def _get_zone_climate_entity(self) -> str | None:
    """Return the zone's climate entity.

    Priority:
    1. Zone-level thermostat (CONF_ZONE_THERMOSTAT) — deterministic
    2. First room in zone that has a climate entity — fallback
    """
    # 1. Check zone-level config
    zone_thermostat = self._get_zone_config(CONF_ZONE_THERMOSTAT)
    if zone_thermostat:
        return zone_thermostat

    # 2. Fallback: traverse rooms
    for coord in self._get_zone_coordinators():
        climate = coord.entry.options.get(
            CONF_CLIMATE_ENTITY,
            coord.entry.data.get(CONF_CLIMATE_ENTITY),
        )
        if climate:
            return climate
    return None
```

Add `_get_zone_config()` helper:

```python
def _get_zone_config(self, key, default=None):
    """Read a zone-specific config value from the zones dict."""
    merged = {**self.entry.data, **self.entry.options}
    zone_data = merged.get("zones", {}).get(self.zone, {})
    return zone_data.get(key, default)
```

### Step 4: Auto-populate on room reconfigure — `config_flow.py`

When a room in a zone is reconfigured and `CONF_CLIMATE_ENTITY` is set, check if
the zone already has `CONF_ZONE_THERMOSTAT`. If not, auto-populate it:

```python
# At end of room climate/HVAC options step (~line 2915):
if user_input.get(CONF_CLIMATE_ENTITY):
    room_zone = self._get_current(CONF_ZONE) or ""
    if room_zone:
        zm_entry = self._find_zone_manager_entry()
        if zm_entry:
            merged = {**zm_entry.data, **zm_entry.options}
            zones = dict(merged.get("zones", {}))
            zone_cfg = zones.get(room_zone, {})
            if not zone_cfg.get(CONF_ZONE_THERMOSTAT):
                zone_cfg[CONF_ZONE_THERMOSTAT] = user_input[CONF_CLIMATE_ENTITY]
                zones[room_zone] = zone_cfg
                self.hass.config_entries.async_update_entry(
                    zm_entry,
                    options={**zm_entry.options, "zones": zones},
                )
```

### Step 5: Update strings — `strings.json` + `translations/en.json`

Add `zone_hvac` step:

```json
"zone_hvac": {
  "title": "Zone HVAC",
  "description": "Select the thermostat that controls this zone. If not set, falls back to the first room's thermostat.",
  "data": {
    "zone_thermostat": "Zone Thermostat"
  },
  "data_description": {
    "zone_thermostat": "Climate entity to control for this zone."
  }
}
```

Add to `zone_config_menu.menu_options`:

```json
"zone_hvac": "Zone HVAC"
```

### Step 6: Legacy migration — `__init__.py`

In the legacy zone migration block (line ~376), copy `CONF_ZONE_THERMOSTAT` if present.

---

## Fallback Behavior

- `CONF_ZONE_THERMOSTAT` set: direct entity reference, no traversal
- `CONF_ZONE_THERMOSTAT` not set (empty/None): room traversal via `_get_zone_coordinators()` unchanged
- Existing installations: no migration needed — field is optional, absence triggers fallback

### Deferred: Smarter Fallback (majority-vote)

Current fallback returns the **first** room's climate entity found. A better approach would
iterate all rooms, find the climate entity shared by the most rooms, and log discrepancies.
**Deferred** because:
- The fallback only runs when `CONF_ZONE_THERMOSTAT` is not set (increasingly rare once UI exists)
- Most zones share a single thermostat across all rooms — non-determinism is rarely visible
- Majority-vote + discrepancy logging adds complexity to a backup path
- Better ROI: prompt users to set the zone thermostat explicitly

---

## Relationship to HVAC Coordinator (C6)

The HVAC Coordinator (PLANNING_v3.6.0_REVISED.md, Cycle 6) will own zone-level climate
control with richer strategies:
- **Zone-to-room mapping** with weighted temperature averaging
- **Control modes:** PRESET_BASED / TEMPERATURE_BASED / HYBRID
- **Energy constraint response:** pre_cool, coast, shed, fan_assist relay
- **Sleep protection** with configurable max setpoint offsets
- **Staggered heat calls** across zones

`CONF_ZONE_THERMOSTAT` feeds directly into C6 — it answers "which climate entity does
this zone control?" which C6 needs. The current preset logic (`_handle_zone_occupancy_change`)
will be replaced by C6's `evaluate()` method, but `CONF_ZONE_THERMOSTAT` survives as the
canonical zone→thermostat mapping.

**Preset UI is intentionally omitted** from this plan. The existing hidden defaults
("away"/"home") work fine until C6 replaces them with the full control strategy model.

---

## Regression Risks

| # | Risk | Mitigation |
|---|------|------------|
| 1 | Zone data in nested `zones` dict vs entry top-level — wrong read path | Add `_get_zone_config()` helper; test both ZM and legacy paths |
| 2 | Auto-populate overwrites user-cleared zone thermostat | Only auto-populate if key absent, not if explicitly empty |
| 3 | Zone Manager reload after config change | Config flow already calls `async_reload()`; verify HVAC listeners re-setup |
| 4 | Presets currently read from wrong location (entry top-level vs zones dict) | Known latent bug — fix when implementing C6, not here |
| 5 | Missing strings show raw keys | Add all strings to both strings.json AND translations/en.json |

---

## Files to Modify

| File | Change |
|------|--------|
| `const.py` | Add `CONF_ZONE_THERMOSTAT` constant |
| `config_flow.py` | Add `zone_hvac` menu option + step; add auto-populate in room HVAC step |
| `aggregation.py` | Modify `_get_zone_climate_entity()`; add `_get_zone_config()` helper |
| `__init__.py` | Copy `CONF_ZONE_THERMOSTAT` during legacy zone migration |
| `strings.json` | Add `zone_hvac` step strings and menu option |
| `translations/en.json` | Mirror strings.json additions |
