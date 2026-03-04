# Quality Context - Post v3.2.9

**Version:** 3.0  
**Last Updated:** January 4, 2026  
**Current Production:** v3.2.9  
**Status:** Active quality standards  

---

## 🎯 QUALITY PHILOSOPHY

**Core Principle:** Quality over speed. One systematic fix prevents three future regressions.

**Quality Metrics:**
- Zero syntax errors in production ✅
- All tests passing before deployment ✅
- Context read before every build ✅
- Backward compatibility maintained ✅
- Documentation up to date ✅

---

## 📚 MANDATORY PRE-BUILD READING

**Before ANY code changes, read these documents:**

### 1. This Document (QUALITY_CONTEXT.md)
- **Purpose:** Understand quality standards
- **Key:** Known bug classes and prevention
- **Time:** 15 minutes

### 2. Development Checklist
- **Location:** `Quality Context/DEVELOPMENT_CHECKLIST.md`
- **Purpose:** Step-by-step validation process
- **Key:** Prevents regression cascades
- **Time:** 10 minutes

### 3. Current Roadmap
- **Location:** `ROADMAP_v8.md`
- **Purpose:** Understand project direction
- **Key:** Where we've been, where we're going
- **Time:** 10 minutes (scan), 30 minutes (full read)

### 4. Planning Document (if applicable)
- **Location:** `PLANNING_v3.x.x.md`
- **Purpose:** Detailed spec for next build
- **Key:** What to build, how to build it
- **Time:** 20-30 minutes

**Total time:** 55-85 minutes (worth it to prevent mistakes!)

---

## 🐛 KNOWN BUG CLASSES (Do Not Repeat!)

### Bug Class #1: Coordinator Lifecycle Confusion ⚠️

**The Mistake:**
```python
# ❌ WRONG - async_added_to_hass NEVER runs on coordinators!
class UniversalRoomCoordinator(DataUpdateCoordinator):
    async def async_added_to_hass(self):
        self._register_event_listeners()  # Never called!
```

**Why it fails:**
- `async_added_to_hass()` only runs on ENTITIES
- Coordinators have different lifecycle
- Result: Event listeners never registered, polling only (10-30s delays)

**The Fix:**
```python
# ✅ CORRECT - async_config_entry_first_refresh runs on coordinators
async def async_config_entry_first_refresh(self):
    await super().async_config_entry_first_refresh()
    self._register_event_listeners()  # After coordinator initialized
```

**Prevention:**
- [ ] Understand coordinator vs entity lifecycle
- [ ] Never use async_added_to_hass on coordinators
- [ ] Always use async_config_entry_first_refresh
- [ ] Test event-driven response times

**Discovered:** v3.2.0.9  
**Impact:** 10-30s delays → 2-5s response  
**Severity:** HIGH  

---

### Bug Class #2: Config Storage Pattern Violation ⚠️

**The Mistake:**
```python
# ❌ WRONG - Only reads entry.data, ignores entry.options
self.automation = RoomAutomation(hass, entry.data, self)
```

**Why it fails:**
- HA stores config in TWO places:
  - `entry.data` = Initial setup (immutable)
  - `entry.options` = User changes via Configure button
- Coordinator only reading entry.data → Config changes ignored
- UI shows "Turn On Always" but runtime uses "turn_on_if_dark"

**The Fix:**
```python
# ✅ CORRECT - Merge both sources (options override data)
config = {**entry.data, **entry.options}
self.automation = RoomAutomation(hass, config, self)
```

**Prevention:**
- [ ] ALWAYS merge entry.data + entry.options
- [ ] Never read only entry.data
- [ ] Test config changes take effect immediately
- [ ] Check all coordinators follow pattern

**Discovered:** v3.2.0.10  
**Impact:** Config changes now immediate  
**Severity:** HIGH  

---

### Bug Class #3: OptionsFlow Implementation Error ⚠️

**The Mistake:**
```python
# ❌ WRONG - OptionsFlow overwrites entry.data
class UniversalRoomAutomationOptionsFlow(OptionsFlow):
    async def async_step_automation_behavior(self, user_input=None):
        return self.async_create_entry(
            title="",
            data={**self._config_entry.options, **user_input}  # Overwrites!
        )
```

**Why it's wrong:**
- `async_create_entry(data=...)` in OptionsFlow overwrites entry.data
- Should update entry.options instead
- Breaks initial configuration values

**The Fix:**
```python
# ✅ CORRECT - Update entry.options, preserve entry.data
async def async_step_automation_behavior(self, user_input=None):
    self.hass.config_entries.async_update_entry(
        self._config_entry,
        options={**self._config_entry.options, **user_input}
    )
    return self.async_create_entry(title="", data={})
```

**Prevention:**
- [ ] OptionsFlow should NEVER overwrite entry.data
- [ ] Use async_update_entry for options
- [ ] Return empty data dict from async_create_entry
- [ ] Check all OptionsFlow methods

**Status:** Fixed in v3.2.0.10 (coordinator merge masks symptom)  
**Severity:** MEDIUM (masked by Bug Class #2 fix)  

---

### Bug Class #4: Domain Mismatch in Service Calls ⚠️

**The Mistake:**
```python
# ❌ WRONG - Calling light.turn_on on switch.entity_id
light_entities = ["light.bedroom", "switch.shelly_dining"]
await hass.services.async_call(
    'light', 
    'turn_on', 
    target={'entity_id': light_entities}
)
```

**Why it fails:**
- Shelly devices are switches (switch.entity_id)
- Can't call light.turn_on on switch entities
- Result: Shelly switches don't turn on

**The Fix:**
```python
# ✅ CORRECT - Separate by domain before service calls
lights = [e for e in entities if e.startswith('light.')]
switches = [e for e in entities if e.startswith('switch.')]

if lights:
    await hass.services.async_call(
        'light', 'turn_on', 
        target={'entity_id': lights}
    )
if switches:
    await hass.services.async_call(
        'switch', 'turn_on',
        target={'entity_id': switches}
    )
```

**Prevention:**
- [ ] Always separate entities by domain
- [ ] Check domain before service call
- [ ] Support multi-domain device lists
- [ ] Test with mixed device types (Shelly, Hue, etc.)

**Discovered:** v3.2.0.8  
**Impact:** Shelly switches now working  
**Severity:** HIGH  

---

### Bug Class #5: Race Conditions on Startup ⚠️

**The Mistake:**
```python
# ❌ WRONG - Assume resources ready immediately
def __init__(self):
    self.coordinators = self._get_zone_coordinators()
    # coordinators might not exist yet!
```

**Why it fails:**
- Integration entry setup runs BEFORE room entries
- Zone sensors created before room coordinators
- When __init__ runs, coordinators don't exist yet
- Result: Sensors show "unavailable" until reload

**The Fix:**
```python
# ✅ CORRECT - Deferred initialization with retry
async def async_added_to_hass(self):
    if self._get_zone_coordinators():
        self._coordinators_ready = True
    else:
        # Retry after 5s
        async def _delayed_check():
            await asyncio.sleep(5)
            if self._get_zone_coordinators():
                self._coordinators_ready = True
                self.async_write_ha_state()
            else:
                # Retry after 15s total
                await asyncio.sleep(10)
                if self._get_zone_coordinators():
                    self._coordinators_ready = True
                    self.async_write_ha_state()
        
        asyncio.create_task(_delayed_check())
```

**Prevention:**
- [ ] Don't assume resources ready immediately
- [ ] Use deferred initialization for dependencies
- [ ] Add retry logic with timeouts
- [ ] Log warnings if resources not found
- [ ] Test startup race conditions

**Discovered:** v3.2.9  
**Impact:** Zone sensors auto-recover in 5-15s  
**Severity:** MEDIUM  

---

### Bug Class #6: Python Cache Persistence 💾

**The Problem:**
- Delete `__pycache__` directory
- Restart Home Assistant
- Old code still runs!

**Root Cause:**
- Python loads modules into RAM
- HA restart doesn't flush Python cache
- Bytecode cache persists in memory

**The Fix:**
1. Delete `__pycache__`: `rm -rf __pycache__`
2. Restart Home Assistant
3. **If still broken:** Full host reboot

**Prevention:**
- [ ] Recommend full system reboot for critical fixes
- [ ] Clear __pycache__ before deployment
- [ ] Test with fresh HA instance
- [ ] Document cache behavior to users

**Discovered:** v3.2.0.9 debugging  
**Impact:** Deployment confidence  
**Severity:** LOW (workflow issue)  

---

## ✅ MANDATORY VALIDATION CHECKLIST

**Before EVERY deployment, complete this checklist:**

### 1. Syntax Validation (5 minutes)
```bash
# All Python files must compile
for f in *.py; do 
    python3 -m py_compile "$f" && echo "✅ $f" || echo "❌ $f FAILED"
done

# JSON files must parse
python3 -c "import json; json.load(open('strings.json')); print('✅ strings.json')"
python3 -c "import json; json.load(open('manifest.json')); print('✅ manifest.json')"
```

**Pass criteria:** All files compile, no syntax errors

---

### 2. Config Storage Pattern (10 minutes)

**Check all coordinators:**
```python
# Search for: "= RoomAutomation(hass,"
# Verify pattern: config = {**entry.data, **entry.options}

# CORRECT pattern:
config = {**entry.data, **entry.options}
self.automation = RoomAutomation(hass, config, self)

# WRONG pattern:
self.automation = RoomAutomation(hass, entry.data, self)  # ❌
```

**Pass criteria:** All coordinators merge data + options

---

### 3. OptionsFlow Pattern (10 minutes)

**Check all OptionsFlow methods:**
```python
# Search for: "async_create_entry" in config_flow.py
# Verify pattern: async_update_entry + empty data

# CORRECT pattern:
self.hass.config_entries.async_update_entry(
    self._config_entry,
    options={**self._config_entry.options, **user_input}
)
return self.async_create_entry(title="", data={})

# WRONG pattern:
return self.async_create_entry(
    title="", 
    data={**self._config_entry.options, **user_input}  # ❌
)
```

**Pass criteria:** All OptionsFlow methods update entry.options

---

### 4. Domain Separation (15 minutes)

**Check all service calls:**
```python
# Search for: "hass.services.async_call"
# Verify: Entities separated by domain

# CORRECT pattern:
lights = [e for e in entities if e.startswith('light.')]
switches = [e for e in entities if e.startswith('switch.')]
fans = [e for e in entities if e.startswith('fan.')]

if lights:
    await hass.services.async_call('light', action, ...)
if switches:
    await hass.services.async_call('switch', action, ...)

# WRONG pattern:
await hass.services.async_call('light', action, 
    target={'entity_id': all_entities})  # ❌ Mixed domains
```

**Pass criteria:** All service calls separated by domain

---

### 5. Event Listener Registration (10 minutes)

**Check coordinators:**
```python
# Search for: "class.*Coordinator.*DataUpdateCoordinator"
# Verify: Event listeners in async_config_entry_first_refresh

# CORRECT pattern (coordinators):
async def async_config_entry_first_refresh(self):
    await super().async_config_entry_first_refresh()
    self._register_event_listeners()

# WRONG pattern (coordinators):
async def async_added_to_hass(self):  # ❌ Never runs!
    self._register_event_listeners()
```

**Check entities:**
```python
# CORRECT pattern (entities):
async def async_added_to_hass(self):
    self._register_event_listeners()
```

**Pass criteria:** Coordinators use first_refresh, entities use added_to_hass

---

### 6. Test Suite Execution (2 minutes)

```bash
cd Tests
bash pre_deployment_test.sh "VERSION"

# Must see output:
# ✅ ALL TESTS PASSED - Safe to deploy
```

**Pass criteria:** All tests passing, no failures

---

### 7. Version Numbers (2 minutes)

```bash
# Check all version references updated
grep -n "VERSION" const.py manifest.json

# Verify:
# const.py: VERSION = "X.X.X"
# manifest.json: "version": "X.X.X"
```

**Pass criteria:** Version consistent across files

---

### 8. Documentation (5 minutes)

**Required updates:**
- [ ] README updated with new features
- [ ] CHANGELOG entry added
- [ ] Context documents updated if needed
- [ ] Breaking changes documented

**Pass criteria:** All documentation current

---

## 🧪 TEST SUITE REQUIREMENTS

### Test Coverage Standards

**Minimum Coverage:** 90% (current: ~92%)

**Required Tests:**
- Unit tests for all sensor types
- Integration tests for automation logic
- Regression tests for known bug classes
- Config flow tests for all steps
- Database tests for all operations

### Test Organization

```
Tests/
├── conftest.py              # Fixtures
├── pytest.ini               # Config
├── test_automation.py       # Automation logic
├── test_sensors.py          # Sensor entities
├── test_config_flow.py      # Configuration
├── test_person_tracking.py  # Person tracking
├── test_regressions.py      # Known bug prevention
├── test_aggregation.py      # Whole-house sensors
└── pre_deployment_test.sh   # Deployment script
```

### Pre-Deployment Script

**Location:** `Tests/pre_deployment_test.sh`

**Usage:**
```bash
cd Tests
bash pre_deployment_test.sh "3.2.9"
```

**Expected Output:**
```
🧪 Pre-deployment test for v3.2.9
✅ ALL TESTS PASSED - Safe to deploy
```

**If tests fail:**
```
❌ TESTS FAILED - DO NOT DEPLOY
[Details of failures]
```

**Mandatory:** Run before every deployment, no exceptions!

---

## 📋 DEVELOPMENT WORKFLOW

### Standard Build Process

**Phase 1: Preparation (10 minutes)**
1. Read quality context (this document)
2. Read development checklist
3. Read planning document
4. Review roadmap for context

**Phase 2: Implementation (Variable)**
1. Create version directory
2. Copy base files
3. Make changes systematically
4. Validate syntax after each file
5. Update version numbers

**Phase 3: Validation (15 minutes)**
1. Run validation checklist (above)
2. Execute test suite
3. Verify all checks pass
4. Document any new learnings

**Phase 4: Deployment (10 minutes)**
1. Copy to outputs directory
2. Create release notes
3. Present files to user
4. Update context documents

**Total:** Variable + ~45 minutes validation/deployment

---

## 🎯 QUALITY METRICS

### Code Quality
- [x] Zero syntax errors
- [x] All tests passing (178+)
- [x] Test coverage > 90%
- [x] No hardcoded values
- [x] Proper error handling

### Architecture Quality
- [x] Follows HA patterns
- [x] Coordinator pattern used
- [x] Event-driven where possible
- [x] Config storage pattern correct
- [x] Domain separation maintained

### Documentation Quality
- [x] Code comments clear
- [x] Docstrings complete
- [x] User documentation updated
- [x] Context documents current
- [x] Examples provided

### Process Quality
- [x] Context read before building
- [x] Validation checklist completed
- [x] Tests run before deployment
- [x] Version numbers consistent
- [x] Learnings documented

---

## 🚨 REGRESSION PREVENTION

### Test-First Mindset

**For every bug fixed:**
1. Write regression test first
2. Verify test fails with bug
3. Fix the bug
4. Verify test passes
5. Add test to test_regressions.py

### Bug Class Prevention

**After discovering new bug class:**
1. Document in this file
2. Add to validation checklist
3. Create specific test
4. Update development checklist
5. Search codebase for similar patterns

### Continuous Monitoring

**After each deployment:**
1. Monitor for 7 days minimum
2. Track user feedback
3. Check error logs
4. Verify metrics stable
5. Plan improvements if needed

---

## 📚 DOCUMENTATION STANDARDS

### Code Documentation

**Every function needs:**
```python
def my_function(param1, param2):
    """Brief description (one line).
    
    Detailed description if needed (paragraph).
    
    Args:
        param1: Description of param1
        param2: Description of param2
    
    Returns:
        Description of return value
    
    Raises:
        ExceptionType: When and why
    """
```

### User Documentation

**Every feature needs:**
- Overview (what it does)
- Setup instructions (how to enable)
- Configuration options (what can be changed)
- Examples (how to use)
- Troubleshooting (common issues)

### Context Documentation

**After every version:**
- Update version history
- Document new learnings
- Add to known issues if applicable
- Update roadmap if priorities changed

---

## 🎓 LESSONS LEARNED

### What Works Well

**1. Quality-First Approach**
- Reading context prevents mistakes
- Systematic validation catches bugs early
- Test-first mindset builds confidence
- Documentation preserves knowledge

**2. Event-Driven Architecture**
- Sub-5-second response times
- Better user experience
- Scales well
- Coordinator pattern works

**3. Config Storage Pattern**
- Merging data + options is robust
- User changes take effect immediately
- Backward compatible
- Easy to understand

### What to Avoid

**1. Rushing Development**
- Skipping context → cascading regressions
- Skipping tests → bugs in production
- Skipping validation → config issues
- Skipping documentation → lost knowledge

**2. Assuming Resources Ready**
- Race conditions on startup
- Coordinators not initialized
- Entities not created yet
- Use deferred initialization

**3. Mixing Domains**
- Service calls fail
- Devices don't respond
- Confusing error messages
- Always separate by domain

---

## 🔄 CONTINUOUS IMPROVEMENT

### After Each Version

**Review Process:**
1. What went well?
2. What could be better?
3. New patterns discovered?
4. New bug classes found?
5. Documentation gaps identified?

**Update Documents:**
1. This quality context
2. Development checklist
3. Roadmap if needed
4. Planning docs for next version

**Share Learnings:**
1. Add to context documents
2. Update validation checklist
3. Create new tests
4. Document patterns

---

## ✅ FINAL CHECKLIST

**Before saying "I'm done":**

- [ ] All syntax checks pass
- [ ] All validation checks pass
- [ ] All tests pass (178+)
- [ ] Version numbers updated
- [ ] Documentation updated
- [ ] Context documents updated
- [ ] Release notes created
- [ ] Files in outputs directory
- [ ] No known issues outstanding
- [ ] Proud of the work

**Only if ALL checked → Present to user**

---

## 🎯 SUCCESS DEFINITION

**A successful build means:**

1. **Zero regressions** - Existing features still work
2. **All tests passing** - No broken functionality
3. **Quality maintained** - Standards upheld
4. **User value delivered** - Solves real problems
5. **Knowledge preserved** - Learnings documented

**Quality is not negotiable. Speed is variable.**

---

## 📋 TECH DEBT

### Music Following Device Group Duplication (v3.6.30)
Music Following was originally a house-level feature, later promoted to a coordinator. Its device appears in both the top-level "Universal Room Automation" integration group AND the "URA: Coordinator Manager" group. Other coordinators (Presence, Safety, Security, NM) only appear under Coordinator Manager. An orphaned "URA: Music Following" device (old identifier `coordinator_music_following`, 0 entities) also lingers in the registry.

**Risk:** MF initialization in `__init__.py` may be tied to the house config entry. Moving it or deleting the orphan could break MF functionality. No config flow entry point for MF exists in the house group.

**Status:** Parked. Orphan can be deleted via HA UI. Grouping fix requires investigating MF init path.

---

**Quality Context v3.0**  
**Last Updated:** January 4, 2026  
**Next Update:** After discovering new patterns  
**Status:** Active quality standards
