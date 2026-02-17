# Test Suite Access Pattern - Cross-Session Consistency

**Purpose:** Ensure Claude can always run tests, regardless of session  
**Created:** December 13, 2025  
**Test Directory:** `/Users/ojiudezue/Library/CloudStorage/OneDrive-Personal/2025/Download 2025/Madrone Labs/Integrations/Room Appliance Integration/Tests`

---

## 🎯 THE PATTERN

**Every build should:**
1. Read this file first
2. Validate test access
3. Run full test suite
4. Report results

**No excuses, no skipping.**

---

## 📍 TEST SUITE LOCATION (PERMANENT)

```bash
# Absolute path (always valid)
TEST_DIR="/Users/ojiudezue/Library/CloudStorage/OneDrive-Personal/2025/Download 2025/Madrone Labs/Integrations/Room Appliance Integration/Tests"

# Integration path (relative to project)
INTEGRATION_DIR="/Users/ojiudezue/Library/CloudStorage/OneDrive-Personal/2025/Download 2025/Madrone Labs/Integrations/Room Appliance Integration"

# Current version working directory
WORK_DIR="/Users/ojiudezue/Library/CloudStorage/OneDrive-Personal/2025/Download 2025/Madrone Labs/Integrations/Room Appliance Integration/v3.2.0.10"
```

---

## 🔧 FILESYSTEM MCP ACCESS

Claude has MCP access to user's computer via Filesystem tools.

**Allowed directories:**
```
/Users/ojiudezue/Library/CloudStorage/OneDrive-Personal/2025/Download 2025/ProductMind/Companies
/Users/ojiudezue/Library/CloudStorage/OneDrive-Personal/2025/Download 2025/Back Roots Initiative
/Users/ojiudezue/Library/CloudStorage/OneDrive-Personal/2025/Download 2025/Madrone Labs/Integrations/Room Appliance Integration
```

**This means:**
- ✅ Can read test files directly via Filesystem:read_text_file
- ✅ Can list test directory via Filesystem:list_directory
- ✅ Can run pytest via bash (if Python environment available)
- ❌ Cannot access /config (that's on HA server, different machine)

---

## 📋 STANDARD TEST RUN PROCEDURE

### Step 1: Verify Access
```python
# Use Filesystem MCP to verify test directory exists
from mcp import Filesystem

try:
    test_files = Filesystem.list_directory(TEST_DIR)
    print(f"✅ Test suite accessible: {len(test_files)} files")
except Exception as e:
    print(f"❌ Cannot access test suite: {e}")
    print("STOP: Fix access before proceeding")
```

### Step 2: Copy Integration Files to Tests Directory
```bash
# Tests expect integration code in specific structure
cd "$TEST_DIR"

# Create custom_components structure if needed
mkdir -p custom_components/universal_room_automation

# Copy current version files
cp "$WORK_DIR"/*.py custom_components/universal_room_automation/
cp "$WORK_DIR"/*.json custom_components/universal_room_automation/
```

### Step 3: Run Full Test Suite
```bash
cd "$TEST_DIR"

# Run with pytest
python3 -m pytest -v --tb=short

# Or use run_tests.py if available
python3 run_tests.py
```

### Step 4: Report Results
```
Expected output format:
=========================== test session starts ============================
collected 178 items

test_automation.py::test_occupancy_detection PASSED
test_automation.py::test_light_control PASSED
...
test_person_tracking.py::test_location_detection PASSED

======================== 178 passed in 0.28s ==========================
```

---

## 🚨 MANDATORY PRE-DEPLOYMENT CHECK

**Before EVERY version delivery:**

```bash
#!/bin/bash
# Pre-deployment test validation

set -e

echo "🧪 Running pre-deployment test suite..."

# 1. Navigate to test directory
cd "/Users/ojiudezue/Library/CloudStorage/OneDrive-Personal/2025/Download 2025/Madrone Labs/Integrations/Room Appliance Integration/Tests"

# 2. Clean previous test artifacts
rm -rf custom_components/__pycache__
rm -rf custom_components/universal_room_automation/__pycache__
rm -f .pytest_cache -rf

# 3. Copy new version
VERSION="$1"  # e.g., "3.2.0.10"
WORK_DIR="../$VERSION"

echo "📦 Copying v$VERSION files..."
mkdir -p custom_components/universal_room_automation

# Copy all Python and JSON files
cp "$WORK_DIR"/*.py custom_components/universal_room_automation/ 2>/dev/null || true
cp "$WORK_DIR"/*.json custom_components/universal_room_automation/ 2>/dev/null || true

# 4. Run tests
echo "🧪 Running test suite..."
python3 -m pytest -v --tb=short

# 5. Report
if [ $? -eq 0 ]; then
    echo "✅ ALL TESTS PASSED - Safe to deploy"
    exit 0
else
    echo "❌ TESTS FAILED - DO NOT DEPLOY"
    exit 1
fi
```

**Usage:**
```bash
bash pre_deployment_test.sh "3.2.0.10"
```

---

## 🎯 INTEGRATION WITH BUILD PROCESS

**Standard build workflow:**

1. **Read quality context**
   ```python
   # Read DEVELOPMENT_CHECKLIST.md
   # Read CONFIG_FLOW_VALIDATION_CHECKLIST.md
   # Read this file (TEST_SUITE_ACCESS.md)
   ```

2. **Make code changes**
   ```python
   # Follow systematic approach
   # Validate syntax: python3 -m py_compile
   ```

3. **Run validation suite** ⚡ **MANDATORY STEP**
   ```bash
   cd Tests
   bash pre_deployment_test.sh "3.2.0.10"
   ```

4. **Only if tests pass:**
   ```python
   # Copy to /mnt/user-data/outputs
   # Create release notes
   # Present files to user
   ```

---

## 📊 TEST SUITE STRUCTURE

**Current test files (as of v3.2.0):**
```
Tests/
├── conftest.py              # pytest fixtures, mocks
├── pytest.ini               # pytest configuration
├── run_tests.py             # convenience runner
│
├── test_automations.py      # Device control logic
├── test_occupancy.py        # Occupancy detection
├── test_sensors.py          # All sensor calculations
├── test_aggregation.py      # Whole-house features
├── test_person_tracking.py  # BLE person tracking (42 tests)
├── test_regressions.py      # Bug prevention
└── test_scenarios.py        # End-to-end scenarios
```

**Test coverage:**
- 178 tests total
- All core features covered
- Regression tests for known bugs
- Person tracking comprehensive tests

---

## 🔍 WHAT TESTS VALIDATE

### Automation Tests
- [ ] Occupancy detection from multiple sensors
- [ ] Light control (on/off/brightness/color)
- [ ] Fan control (temperature-based)
- [ ] Cover control (time-based, sun-based)
- [ ] Sleep protection logic
- [ ] Bypass mechanisms
- [ ] Shared space auto-off

### Sensor Tests
- [ ] All 72+ sensor calculations
- [ ] Person tracking sensors (4 per room)
- [ ] Zone aggregation sensors
- [ ] Integration-level sensors (3 per person)
- [ ] Prediction sensors
- [ ] Safety/security sensors

### Config Flow Tests
- [ ] Initial setup validation
- [ ] Options flow reconfiguration
- [ ] Device selection
- [ ] Error handling
- [ ] Translation strings

### Regression Tests
- [ ] v2.3.1-3 None check cascade
- [ ] v3.2.0.8 light/switch separation
- [ ] v3.2.0.10 config storage (ADD THIS!)
- [ ] Any future bugs we fix

---

## 🎓 CROSS-SESSION CONSISTENCY

**Problem:** Claude forgets test location between sessions

**Solution:** This document

**Usage in new session:**
```python
# Session start checklist:
# 1. Read memory/context (automatic via userMemories)
# 2. Read TEST_SUITE_ACCESS.md (this file)
# 3. Validate test access
# 4. Proceed with task

# Example:
test_dir = "/Users/ojiudezue/Library/CloudStorage/OneDrive-Personal/2025/Download 2025/Madrone Labs/Integrations/Room Appliance Integration/Tests"

# Use Filesystem MCP
files = Filesystem.list_directory(test_dir)
print(f"✅ Test suite accessible: {files}")
```

---

## 🚨 FAILURE MODES & RECOVERY

### Issue: "Cannot access test directory"
**Cause:** MCP permissions or path incorrect  
**Fix:** Verify allowed directories via `Filesystem:list_allowed_directories`

### Issue: "Tests fail after code changes"
**Cause:** New code breaks existing functionality  
**Fix:** Don't deploy! Fix code until tests pass

### Issue: "Import errors in tests"
**Cause:** Missing __init__.py or wrong directory structure  
**Fix:** Ensure custom_components/universal_room_automation/ exists

### Issue: "Tests pass locally but fail in production"
**Cause:** Environment differences  
**Fix:** Tests should mock HA environment properly (check conftest.py)

---

## 📈 QUALITY METRICS

**Target:** 100% test pass rate before deployment

**Current status:**
- v3.2.0: 178/178 tests passing ✅
- v3.2.0.10: Need to add config storage tests

**Red flags:**
- Any failing tests before deployment ❌
- Tests not run before deployment ❌
- "Tests are slow, skipping" ❌
- "Tests probably still pass" ❌

**Green flags:**
- All tests passing ✅
- New tests added for new features ✅
- Regression tests added for bugs ✅
- Test run time under 5 seconds ✅

---

## 🔄 MAINTENANCE

**After adding new features:**
```python
# 1. Write tests FIRST (TDD when possible)
# 2. Implement feature
# 3. Run tests
# 4. Fix until all pass
# 5. Deploy
```

**After fixing bugs:**
```python
# 1. Write regression test that fails
# 2. Fix bug
# 3. Verify test now passes
# 4. Add to test_regressions.py
# 5. Deploy
```

**Before major versions:**
```python
# 1. Review all test files
# 2. Add missing coverage
# 3. Update test data if needed
# 4. Run full suite multiple times
# 5. Deploy
```

---

## 📝 EXAMPLE: ADDING CONFIG STORAGE TEST

**For v3.2.1.0, add to test_regressions.py:**

```python
def test_config_storage_merge(hass):
    """Test that coordinator merges entry.data and entry.options.
    
    Regression test for v3.2.0.10 bug where config changes were ignored.
    Bug: Coordinator only read entry.data, ignored entry.options
    Fix: Merge both sources with options overriding data
    """
    from homeassistant.config_entries import ConfigEntry
    from custom_components.universal_room_automation.coordinator import UniversalRoomCoordinator
    
    # Create mock entry with data and options
    entry = ConfigEntry(
        version=1,
        domain="universal_room_automation",
        title="Test Room",
        data={
            "room_name": "Test",
            "entry_light_action": "turn_on_if_dark",  # Initial value
        },
        options={
            "entry_light_action": "turn_on",  # Changed via configure
        },
        source="user",
        entry_id="test123",
    )
    
    # Create coordinator
    coordinator = UniversalRoomCoordinator(hass, entry)
    
    # Verify automation receives merged config
    # Options should override data
    automation_config = coordinator.automation.config
    
    assert automation_config.get("entry_light_action") == "turn_on", \
        "Automation should use entry.options value, not entry.data"
```

---

## ✅ SUCCESS CRITERIA

**This pattern is working when:**

- [ ] Claude can run tests in every session
- [ ] No "can't find test directory" errors
- [ ] All tests pass before every deployment
- [ ] New features include new tests
- [ ] Bug fixes include regression tests
- [ ] Test suite runs in under 5 seconds
- [ ] 100% pass rate maintained

---

## 🎯 FINAL REMINDERS

**For Claude (me):**
- Read this file at session start
- Verify test access before building
- Run full suite before delivery
- Report pass/fail counts to user
- Add regression tests for bugs
- Never skip tests "to save time"

**For User:**
- Keep Tests directory in allowed paths
- Don't move test files
- Run tests before deploying manually
- Add tests for new features
- Review test failures carefully

---

**Version:** 1.0  
**Created:** December 13, 2025  
**Purpose:** Ensure consistent test access across sessions  
**Status:** Active - use before every build
