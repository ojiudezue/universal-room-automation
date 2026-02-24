# Config Flow & Storage Validation Checklist

**Purpose:** Prevent entry.data vs entry.options bugs across ALL automation types  
**Created:** December 13, 2025  
**Triggered by:** v3.2.0.10 lights bug (config changes ignored)  
**Class:** Config storage/reading bugs  

---

## 🎯 THE BUG CLASS WE'RE PREVENTING

**Root Pattern:**
```python
# WRONG - Coordinator only reads entry.data
self.automation = RoomAutomation(hass, entry.data, self)

# WRONG - OptionsFlow writes to entry.data instead of entry.options
return self.async_create_entry(title="", data={**self._config_entry.options, **user_input})

# RIGHT - Coordinator merges both
config = {**entry.data, **entry.options}
self.automation = RoomAutomation(hass, config, self)

# RIGHT - OptionsFlow updates entry.options
self.hass.config_entries.async_update_entry(
    self._config_entry,
    options={**self._config_entry.options, **user_input}
)
return self.async_create_entry(title="", data={})
```

---

## 📋 VALIDATION CHECKLIST - Run This After v3.2.0.10

### Step 1: Verify ALL Automation Types Use Merged Config

**Search pattern:**
```bash
cd /config/custom_components/universal_room_automation
grep -n "RoomAutomation\|automation\s*=" coordinator.py
```

**What to check:**
- [ ] Light automation: Gets merged config ✅ (Fixed in v3.2.0.10)
- [ ] Fan automation: Check if uses same pattern
- [ ] Cover automation: Check if uses same pattern
- [ ] Climate automation: Check if uses same pattern
- [ ] Switch automation: Check if uses same pattern

**For each automation module:**
```python
# Check coordinator.py initialization
# Should see: config = {**entry.data, **entry.options}
# Before ANY automation handler creation
```

---

### Step 2: Verify Config Flow Correctly Saves to entry.options

**Search pattern:**
```bash
grep -n "async_step_.*\|async_create_entry" config_flow.py | grep -A 5 "async_step"
```

**Check EVERY options flow method:**
- [ ] `async_step_automation_behavior` - Line 1795
- [ ] `async_step_climate` - Find line number
- [ ] `async_step_covers` - Find line number  
- [ ] `async_step_notifications` - Find line number
- [ ] `async_step_occupancy` - Find line number
- [ ] `async_step_devices` - Find line number

**For each method, verify it uses:**
```python
# CORRECT pattern (OptionsFlow)
self.hass.config_entries.async_update_entry(
    self._config_entry,
    options={**self._config_entry.options, **user_input}
)
return self.async_create_entry(title="", data={})

# WRONG pattern (don't use this in OptionsFlow!)
return self.async_create_entry(
    title="",
    data={**self._config_entry.options, **user_input}  # ❌ Overwrites entry.data!
)
```

---

### Step 3: Domain Correctness Validation

**Check device domains match their entity types:**

```bash
# Search for device domain assignments
grep -n "DOMAIN\|domain=" coordinator.py automation.py
grep -n "Platform\." *.py
```

**Verify:**
- [ ] Lights use `light.turn_on/off` services
- [ ] Switches use `switch.turn_on/off` services  
- [ ] Fans use `fan.turn_on/off` services
- [ ] Covers use `cover.open/close` services
- [ ] Climate uses `climate.set_temperature` services

**Specific check (automation.py):**
```python
# Line ~400-500 - Entry light control
# Should separate lights vs switches correctly
lights = [e for e in light_entities if e.startswith('light.')]
switches = [e for e in light_entities if e.startswith('switch.')]

# Call correct services
if lights:
    await self.hass.services.async_call('light', 'turn_on', ...)
if switches:
    await self.hass.services.async_call('switch', 'turn_on', ...)
```

---

### Step 4: Test Each Automation Type Manually

Create test procedure for each automation type:

#### 4A: Light Automation Test
- [ ] Create room with "Turn On Always"
- [ ] Configure → Change to "None"  
- [ ] Reload integration
- [ ] Walk in room → Lights should NOT turn on
- [ ] Configure → Change back to "Turn On Always"
- [ ] Reload integration
- [ ] Walk in room → Lights should turn on

#### 4B: Fan Automation Test
- [ ] Create room with fan automation enabled
- [ ] Configure → Change fan settings
- [ ] Reload integration
- [ ] Check if new settings take effect
- [ ] Temperature change → Fan should respond with NEW settings

#### 4C: Cover Automation Test
- [ ] Create room with "Smart (Sun-Based)" covers
- [ ] Configure → Change to "Always"
- [ ] Reload integration  
- [ ] Walk in room → Covers should open (regardless of sun)

#### 4D: Climate Automation Test
- [ ] Create room with climate control
- [ ] Configure → Change setpoint or mode
- [ ] Reload integration
- [ ] Occupancy change → Should use NEW setpoint

#### 4E: Switch Automation Test
- [ ] Create room with switches (e.g., Shelly devices)
- [ ] Configure → Change switch behavior
- [ ] Reload integration
- [ ] Walk in room → Switches respond with NEW behavior

---

### Step 5: Config Dump Verification (Post v3.2.1.0)

**Once config dump buttons are added:**

For each automation type:
```bash
# Press config dump button
# Check logs for CONFIG DUMP output
# Verify entry.data matches UI settings
# Verify entry.options contains user changes
```

Expected output:
```
🔍 CONFIG DUMP [Room Name]:
  entry_light_action: turn_on          ← From entry.options (if changed)
  entry_fan_mode: auto                 ← From entry.options (if changed)
  covers_entry_action: smart           ← From entry.data (if unchanged)
  climate_setpoint: 22.0               ← From entry.options (if changed)
```

---

### Step 6: Code Review Specific Locations

**coordinator.py:**
- [ ] Line ~130-140: Automation initialization
- [ ] Verify: `config = {**entry.data, **entry.options}` BEFORE any automation creation
- [ ] Check: All automation handlers receive merged config

**config_flow.py:**
- [ ] Every `async_step_*` in OptionsFlow class (Line 1105+)
- [ ] Verify: Uses `async_update_entry` with options parameter
- [ ] Check: Never overwrites entry.data in options flow

**automation.py:**
- [ ] Line ~100-120: __init__ receives config dict
- [ ] Verify: Uses `config.get(KEY)` not `entry.data.get(KEY)`
- [ ] Check: No direct entry.data access

---

## 🔍 FAILURE MODE ANALYSIS

### Known Failure Modes

**1. Config Changes Ignored (FIXED in v3.2.0.10)**
- **Symptom:** UI shows "Turn On Always", runtime uses "turn_on_if_dark"
- **Cause:** Coordinator only reads entry.data, ignores entry.options
- **Prevention:** Always merge: `config = {**entry.data, **entry.options}`

**2. Wrong Service Domain**
- **Symptom:** Shelly switches don't turn on
- **Cause:** Calling light.turn_on on switch.entity_id
- **Prevention:** Separate by entity domain before service calls

**3. Options Flow Overwrites entry.data**
- **Symptom:** Initial config lost after first reconfigure
- **Cause:** OptionsFlow uses `data={**options, **input}` instead of updating options
- **Prevention:** Use `async_update_entry(options=...)` in OptionsFlow

**4. Default Values Missing**
- **Symptom:** KeyError or None when config key doesn't exist
- **Cause:** No default in `config.get(KEY)`
- **Prevention:** Always provide defaults: `config.get(KEY, DEFAULT)`

---

## 🎯 NEW FAILURE MODES TO WATCH FOR

### A. Presence Detection Config Ignored
**Check:**
- [ ] BLE scanner config uses merged config
- [ ] Confidence thresholds apply immediately after change
- [ ] Transition window updates take effect

**Test:**
```python
# Change transition window from 120s to 60s
# Walk between rooms
# Check logs - should use 60s window, not 120s
```

### B. Person Tracking Config Out of Sync
**Check:**
- [ ] Tracked persons list from entry.options
- [ ] Retention period updates work
- [ ] Person coordinator gets merged config

**Test:**
```python
# Configure → Remove a tracked person
# Reload integration
# Person sensors should disappear
```

### C. Zone Aggregation Config Mismatch
**Check:**
- [ ] Zone rooms list from entry.options
- [ ] Zone sensors recalculate when rooms change
- [ ] Adding/removing rooms from zone works

---

## 🛠️ AUTOMATED VALIDATION SCRIPT

**Create:** `validate_config_storage.py` in tests directory

```python
"""Validate config storage patterns across codebase."""
import re
import sys
from pathlib import Path

def check_coordinator_uses_merged_config():
    """Verify coordinator merges entry.data and entry.options."""
    coord_file = Path("coordinator.py")
    content = coord_file.read_text()
    
    # Look for config merge pattern
    merge_pattern = r'config\s*=\s*\{\*\*entry\.data,\s*\*\*entry\.options\}'
    if not re.search(merge_pattern, content):
        print("❌ FAIL: coordinator.py doesn't merge entry.data and entry.options")
        return False
    
    # Look for automation handler receiving config
    handler_pattern = r'RoomAutomation\(.*,\s*config\s*,.*\)'
    if not re.search(handler_pattern, content):
        print("❌ FAIL: RoomAutomation doesn't receive merged config")
        return False
    
    print("✅ PASS: Coordinator uses merged config")
    return True

def check_options_flow_updates_correctly():
    """Verify OptionsFlow updates entry.options, not entry.data."""
    flow_file = Path("config_flow.py")
    content = flow_file.read_text()
    
    # Find OptionsFlow class
    options_class = content.find("class UniversalRoomAutomationOptionsFlow")
    if options_class == -1:
        print("❌ FAIL: Can't find OptionsFlow class")
        return False
    
    options_content = content[options_class:]
    
    # Look for WRONG pattern (overwriting entry.data)
    wrong_pattern = r'data\s*=\s*\{\*\*self\._config_entry\.options'
    if re.search(wrong_pattern, options_content):
        print("❌ FAIL: OptionsFlow overwrites entry.data (should update entry.options)")
        return False
    
    print("✅ PASS: OptionsFlow uses correct storage pattern")
    return True

def check_automation_uses_config_dict():
    """Verify automation.py uses config dict, not entry.data."""
    auto_file = Path("automation.py")
    content = auto_file.read_text()
    
    # Look for direct entry.data access (BAD)
    if re.search(r'entry\.data\.get', content):
        print("❌ FAIL: automation.py accesses entry.data directly")
        return False
    
    # Look for config.get usage (GOOD)
    if not re.search(r'config\.get\(', content):
        print("❌ FAIL: automation.py doesn't use config dict")
        return False
    
    print("✅ PASS: Automation uses config dict correctly")
    return True

if __name__ == "__main__":
    checks = [
        check_coordinator_uses_merged_config,
        check_options_flow_updates_correctly,
        check_automation_uses_config_dict,
    ]
    
    results = [check() for check in checks]
    
    if all(results):
        print("\n✅ ALL CHECKS PASSED")
        sys.exit(0)
    else:
        print("\n❌ SOME CHECKS FAILED")
        sys.exit(1)
```

**Usage:**
```bash
cd /config/custom_components/universal_room_automation
python3 validate_config_storage.py
```

---

## 📊 COMPLETION CRITERIA

**This validation is complete when:**

- [ ] All automation types verified to use merged config
- [ ] All OptionsFlow methods use async_update_entry
- [ ] No direct entry.data access in automation modules
- [ ] Manual tests pass for all automation types
- [ ] Automated validation script passes
- [ ] No UI/runtime config mismatches found
- [ ] Config dump buttons added (v3.2.1.0)

---

## 🔄 ONGOING MAINTENANCE

**Before every new version:**
- [ ] Run automated validation script
- [ ] Check any new OptionsFlow methods
- [ ] Verify new automation types use merged config
- [ ] Test config changes for new features

**After any config flow changes:**
- [ ] Re-run full validation
- [ ] Manual test at least 3 automation types
- [ ] Check logs for config mismatches

---

## 📝 DOCUMENTATION UPDATES NEEDED

**v3.2.1.0 should include:**
- [ ] Fix OptionsFlow to use entry.options correctly (config_flow.py)
- [ ] Add config dump buttons for debugging
- [ ] Update DEVELOPMENT_CHECKLIST.md with config storage patterns
- [ ] Add this validation to test suite
- [ ] Create unit tests for config merging

---

**Version:** 1.0
**Created:** December 13, 2025
**Based on:** v3.2.0.10 config storage bug fix
**Status:** Active validation checklist

---

## v3.4.x: Camera Census Lessons

### Strings and Translations (v3.4.1–v3.4.3)

**Rule:** Every new config flow field MUST have a matching entry in `strings.json` for BOTH `config.step` AND `options.step`. Missing entries cause the raw config key to render in the UI instead of a human-readable label.

Checklist — after adding any new field to config_flow.py:
- [ ] `strings.json` has a `data` entry for the new key under every `config.step` that uses it
- [ ] `strings.json` has a `data_description` entry for the new key (optional but recommended)
- [ ] `strings.json` has matching entries under `options.step` if the field appears in OptionsFlow
- [ ] `translations/en.json` exists and is an exact copy of `strings.json`
  ```bash
  cp strings.json translations/en.json
  ```
- [ ] `translations/` directory is present — HA requires it at runtime even if strings.json exists

**What broke in v3.4.1:** Camera census added `camera_person_entities` to the sensor config step and `camera_census` as an options menu item with `egress_cameras`/`perimeter_cameras`. No `strings.json` entries were added. Users saw raw keys. `translations/en.json` did not exist at all — the directory was never created.

---

### Entity Selector Domain for Camera Config (v3.4.4)

**Rule:** Camera config fields that let users select camera-related entities should use `domain="camera"`, not `domain="binary_sensor"`. Code resolves person detection entities from the device registry automatically.

**Why it matters:** Using `domain="binary_sensor"` on a camera device exposes every binary_sensor on the device — motion, animal, bark, doorbell, etc. — not just person detection. Users cannot tell which sensor is correct and frequently pick the wrong one.

**Correct pattern:**
```python
# CORRECT — selector shows camera entities; code resolves person detection from device
vol.Optional(CONF_CAMERA_PERSON_ENTITIES): selector.EntitySelector(
    selector.EntitySelectorConfig(
        domain="camera",
        multiple=True,
    )
)

# WRONG — exposes every binary_sensor on camera devices
vol.Optional(CONF_CAMERA_PERSON_ENTITIES): selector.EntitySelector(
    selector.EntitySelectorConfig(
        domain="binary_sensor",
        device_class="occupancy",
        multiple=True,
    )
)
```

**Resolution pattern (camera → person detection entity):**
```python
# In the coordinator or camera manager:
# Get the device for the camera entity, then find its person detection binary_sensor
device_id = entity_registry.entities[camera_entity_id].device_id
person_sensor = next(
    (e.entity_id for e in entity_registry.entities.values()
     if e.device_id == device_id
     and e.domain == "binary_sensor"
     and ("person_detected" in e.entity_id or "person_occupancy" in e.entity_id)),
    None
)
```

- [ ] Any camera config selector uses `domain="camera"`, not `domain="binary_sensor"`
- [ ] Person detection entity resolution happens in code (coordinator or camera manager), not in the selector config
- [ ] Cross-validation toggle is present when both platforms (Frigate + UniFi) may be configured for the same room
