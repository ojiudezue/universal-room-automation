# Plan: Config UX Streamlining (v3.6.23+)

**Date:** 2026-03-02
**Status:** Planned (not yet implemented)
**Source:** `docs/REVIEW_CONFIG_UX.md`

## Context

URA config flow requires 72 fields across 8 steps per room. A 10-room house = 739 fields, 82 form submissions, 10-15 minutes. Adaptive Lighting does equivalent in 30 seconds. Area pre-population infrastructure is 80% built but not wired up. Many conditional fields shown unconditionally.

## Phase 1: Area Pre-Population (P0-1) — ~200 lines

### Problem
`area_id` is collected in `room_setup` step but never used to suggest entities. Coordinator already has `_get_entities_in_area()`. Users manually pick 15+ entities that could be auto-discovered.

### Implementation

#### Step 1: Add area entity discovery helper — `config_flow.py`

```python
async def _get_area_entities(self, area_id: str, domain: str) -> list[str]:
    """Get entity IDs in an area, checking both entity and device area_id."""
    er = entity_registry.async_get(self.hass)
    dr = device_registry.async_get(self.hass)
    entities = []
    for entry in er.entities.values():
        if entry.domain != domain:
            continue
        # Check entity area_id directly
        if entry.area_id == area_id:
            entities.append(entry.entity_id)
            continue
        # Fallback: check device area_id (many entities inherit from device)
        if entry.device_id:
            device = dr.async_get(entry.device_id)
            if device and device.area_id == area_id:
                entities.append(entry.entity_id)
    return entities
```

#### Step 2: Wire into form steps — `config_flow.py`

For each entity selector step (lights, sensors, covers, media_players, climate), call `_get_area_entities()` and pass results as `suggested_value` in the schema:

```python
# In async_step_lights():
area_id = self._room_data.get(CONF_ROOM_AREA)
if area_id:
    suggested_lights = await self._get_area_entities(area_id, "light")
    schema = vol.Schema({
        vol.Optional(CONF_ROOM_LIGHTS,
                     description={"suggested_value": suggested_lights}):
            selector.EntitySelector(EntitySelectorConfig(domain="light", multiple=True)),
    })
```

#### Step 3: Apply to all entity selection steps

| Step | Domain | Fields Pre-populated |
|------|--------|---------------------|
| `lights` | `light` | Room lights, night lights |
| `sensors` | `sensor`, `binary_sensor` | Motion, door, temperature, humidity |
| `covers` | `cover` | Room covers |
| `media_player` | `media_player` | Room speaker |
| `climate` | `climate` | Room thermostat |
| `fan` | `fan` | Room fan |

**Note:** `EntitySelectorConfig` does NOT support `area` filter directly — must use `suggested_value` approach. Device fallback is critical: many entities have `area_id` on device but NULL on entity (presence coordinator handles this at lines 794-798).

### Files Modified
- `config_flow.py` — Add helper, wire into 6 steps

---

## Phase 2: Conditional Field Display (P1-3, P2-6/7) — ~150 lines

### Problem
25+ fields shown unconditionally that only apply to specific configurations. Cover config (12 fields) shown even with no covers. Night light details (5 fields) shown without night lights. Fan speeds (4 fields) shown when fan_control is off.

### Implementation

HA config flows don't support dynamic show/hide within a single form. Solution: **sub-steps**.

#### Cover Behavior Sub-Step

Only show `async_step_cover_behavior()` when covers were selected in the devices step:

```python
async def async_step_devices(self, user_input=None):
    if user_input:
        self._room_data.update(user_input)
        if user_input.get(CONF_ROOM_COVERS):
            return await self.async_step_cover_behavior()
        return await self.async_step_automation_behavior()
```

#### Night Light Sub-Step

Only show night light detail fields when night lights were selected:

```python
async def async_step_lights(self, user_input=None):
    if user_input:
        self._room_data.update(user_input)
        if user_input.get(CONF_NIGHT_LIGHTS):
            return await self.async_step_night_light_detail()
        return await self.async_step_sensors()
```

#### Fan Speed Sub-Step

Only show fan speed temperatures when `fan_control_enabled` is True:

```python
# In async_step_automation_behavior():
if user_input.get(CONF_FAN_CONTROL_ENABLED):
    return await self.async_step_fan_speeds()
```

### Conditional Field Summary

| Sub-Step | Fields Hidden | Condition to Show | Rooms Affected |
|----------|--------------|-------------------|----------------|
| `cover_behavior` | 12 | Covers configured | ~10-20% |
| `night_light_detail` | 5 | Night lights selected | ~30% |
| `fan_speeds` | 4 | Fan control enabled | ~40% |
| `sleep_protection` | 5 | Room type = bedroom | ~25% |
| `humidity_fan` | 2 | Humidity fans configured | ~10% |

**Impact:** Typical room goes from 8 steps to 4-5 steps. Non-bedroom without covers/fans: 4 steps.

### Files Modified
- `config_flow.py` — Add 4 sub-step methods, modify routing logic
- `strings.json` — Add sub-step titles/descriptions
- `translations/en.json` — Mirror strings

---

## Phase 3: Auto-Detect Capabilities (P1-4) — ~80 lines

### Problem
Users manually select `light_capabilities` (dimming, color_temp, rgb) and `cover_type` from dropdowns. This information is available from entity `supported_features`.

### Implementation

```python
async def _detect_light_capabilities(self, entity_ids: list[str]) -> str:
    """Detect light capabilities from supported_features."""
    er = entity_registry.async_get(self.hass)
    max_cap = "on_off"
    for eid in entity_ids:
        entry = er.async_get(eid)
        if not entry:
            continue
        state = self.hass.states.get(eid)
        if not state:
            continue
        features = state.attributes.get("supported_features", 0)
        if features & 16:  # SUPPORT_COLOR
            return "rgb"
        elif features & 2:  # SUPPORT_COLOR_TEMP
            max_cap = "color_temp"
        elif features & 1:  # SUPPORT_BRIGHTNESS
            if max_cap == "on_off":
                max_cap = "dimming"
    return max_cap
```

Wire as `suggested_value` for `CONF_LIGHT_CAPABILITIES` — user can still override.

### Files Modified
- `config_flow.py` — Add detection helpers, wire into lights/covers steps

---

## Phase 4: Quick Setup Mode (P0-2) — ~300 lines

### Problem
Mass adoption blocker. Each room requires expert knowledge of 8 config steps.

### Implementation

Add a "Setup Mode" choice at the start of room configuration:

```
┌─ Room Setup ─────────────────────┐
│                                   │
│  Room Name: [Kitchen          ]   │
│  Area:      [Kitchen ▼        ]   │
│                                   │
│  Setup Mode:                      │
│  ○ Quick (recommended)            │
│  ○ Advanced                       │
│                                   │
└───────────────────────────────────┘
```

**Quick mode flow:**
1. `room_setup` — name + area_id + room_type
2. Auto-discover all entities from area
3. `confirm` — show discovered entities, let user remove any
4. Apply sensible defaults for all behavior settings
5. Done (3 steps instead of 8)

**Defaults per room type:**

| Room Type | Key Defaults |
|-----------|-------------|
| bedroom | Sleep protection ON, night light ON, occupancy timeout 600s |
| bathroom | Humidity fan ON, short timeout 120s, motion-only occupancy |
| kitchen | Long timeout 900s, no sleep features |
| closet | Short timeout 60s, motion-only, no advanced features |
| living_room | Long timeout 1800s, media-aware occupancy |
| office | Medium timeout 600s, desk presence if sensor found |

Current 8-step flow becomes "Advanced Setup" accessible from options.

### Files Modified
- `config_flow.py` — Add quick mode branch, room type defaults
- `const.py` — Room type default profiles
- `strings.json` / `translations/en.json` — Quick mode strings

---

## Phase 5: Skippable Optional Steps (P1-5) — ~50 lines

### Problem
Sleep, Energy, and Notifications steps shown for every room. Most rooms use defaults.

### Implementation

Add "Skip (use defaults)" button to optional steps:

```python
async def async_step_sleep(self, user_input=None):
    if user_input is not None:
        if user_input.get("_skip"):
            # Apply defaults and proceed
            return await self.async_step_energy()
        self._room_data.update(user_input)
        return await self.async_step_energy()

    return self.async_show_form(
        step_id="sleep",
        data_schema=...,
        description_placeholders={"skip_hint": "Leave empty to use defaults"},
    )
```

### Files Modified
- `config_flow.py` — Add skip logic to 3 steps

---

## Implementation Order

| Phase | Priority | Effort | Impact |
|-------|----------|--------|--------|
| 1: Area Pre-Population | P0 | ~200 lines | Saves 15+ selections/room |
| 2: Conditional Fields | P1 | ~150 lines | Removes 25+ irrelevant fields |
| 3: Auto-Detect | P1 | ~80 lines | Removes 2 manual dropdowns |
| 5: Skippable Steps | P1 | ~50 lines | 8 steps → 5 steps |
| 4: Quick Setup | P0 | ~300 lines | 8 steps → 3 steps |

**Recommended:** Phases 1-3 + 5 in one cycle (v3.6.23), Phase 4 in a follow-up cycle.

## Regression Prevention

| # | Risk | Mitigation |
|---|------|------------|
| 1 | Options flow must preserve existing data | `data={**options, **user_input}` pattern (learned from v3.6.0-c2.1 wipe) |
| 2 | Sub-steps must preserve accumulated room data | Use `self._room_data` accumulator (existing pattern) |
| 3 | Suggested values must not override saved config | Only suggest on initial setup, not options flow edits |
| 4 | Area queries may be slow with large registries | Cache per config flow session |
| 5 | Device area_id fallback must match presence coordinator logic | Reuse same pattern from lines 794-798 |

## Deferred

- **Bulk room import** — CSV/YAML import for 10+ rooms at once
- **Template rooms** — Copy config from one room to similar rooms
- **Config validation warnings** — Warn about unusual combinations (e.g., bedroom without sleep config)
