# Quality Context

**Version:** 4.0
**Last Updated:** March 18, 2026
**Current Production:** v3.16.0
**Status:** Active quality standards
**Bug Classes:** 17 documented (7 original + 10 new from Jan–Mar 2026)  

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
- **Location:** `ROADMAP_v10.md`
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

### Bug Class #7: Stale Data Source Driving Development Decisions ⚠️

**The Mistake:**
```
# ❌ WRONG - Acting on diagnostic data without verifying the data source is live/current
MCP ura-sqlite was configured to read ~/.cache/ura/universal_room_automation.db (a 12-day-old cached copy)
instead of the live Samba-mounted DB. "Missing table" diagnoses were phantom — tables existed on the live DB.
This motivated an entire 4-version repair cycle (v3.13.0-v3.13.3) with unnecessary urgency.
```

**Why it fails:**
- Cached/stale copies of databases, API responses, or config files diverge from live state
- Diagnoses based on stale data produce false negatives (missing tables, wrong schemas)
- Development work driven by phantom problems adds risk (new code paths, complexity) without fixing real issues
- The code itself may be individually correct, but the motivation was wrong — wasted effort

**The Fix:**
```
# ✅ CORRECT - Always verify data source freshness before acting on diagnostics
1. Check file modification timestamps (ls -la, stat) on the data source
2. Compare file sizes between cache and live copies
3. Run a known-good query (SELECT count(*) FROM sqlite_master) and cross-check
4. If using MCP tools, verify --db-path points to the live/mounted path, not a cache
5. When diagnosing "missing" resources, verify on the live system FIRST (HA API, SSH, etc.)
```

**Prevention:**
- [ ] Before any DB repair work: verify the MCP/tool data source is current (check mtime, file size)
- [ ] Cross-validate diagnostics against live HA instance (use ha-mcp, not just ura-sqlite)
- [ ] Never trust cached data for production diagnosis without freshness check
- [ ] If data source is a mount (Samba/NFS), verify mount is active before querying
- [ ] Document data source paths in project memory so stale configs are caught early

**Discovered:** v3.13.3 (March 2026)
**Impact:** 4 unnecessary development cycles, added code complexity with marginal value
**Severity:** HIGH (process — leads to wasted effort and unnecessary code risk)

---

### Bug Class #8: Type Safety in Dynamically-Structured Data ⚠️

**The Mistake:**
```python
# ❌ WRONG - Assumes AI parser always returns proper dicts
for action in parsed_actions:
    target = action["target"]  # KeyError if not dict-like
    service_call = {**target, **action["data"]}  # TypeError if not dict
```

**Why it fails:**
- AI rule parser (or any external/dynamic data) can return non-dict values
- No defensive type checking before dict unpacking with `{**obj}`
- Result: TypeError/KeyError crashes rule execution for all rules, not just the bad one

**The Fix:**
```python
# ✅ CORRECT - Validate type before unpacking
for action in parsed_actions:
    if not isinstance(action, dict):
        continue
    target = action.get("target", {})
    if not isinstance(target, dict):
        target = {}
    data = action.get("data", {})
    if not isinstance(data, dict):
        data = {}
    service_call = {**target, **data}
```

**Prevention:**
- [ ] Guard `{**obj}` unpacking with `isinstance(obj, dict)` checks
- [ ] Use `.get()` with default empty dict for nested fields
- [ ] Never trust external/dynamic data shape (AI, webhooks, DB JSON)
- [ ] Test with intentionally malformed input

**Discovered:** v3.12.1
**Impact:** AI automation execution crashes on malformed rules
**Severity:** HIGH

---

### Bug Class #9: Database Corruption Cascade from Single Table Failure ⚠️

**The Mistake:**
```python
# ❌ WRONG - Single try/except wraps all table creations
def initialize(self):
    try:
        conn.execute("CREATE TABLE energy_snapshots ...")
        conn.execute("CREATE TABLE energy_daily ...")  # Never runs if above fails
        conn.execute("CREATE TABLE evse_state ...")     # Never runs
        conn.commit()
    except:
        rollback()  # ALL tables rolled back
```

**Why it fails:**
- B-tree corruption in one table triggers exception, rolling back ALL subsequent CREATE TABLE statements
- 22 other tables never created, breaking any code expecting those tables
- Single transaction scope means one failure = total schema failure

**The Fix:**
```python
# ✅ CORRECT - Per-table isolation with independent commit
for table_def in TABLE_DEFINITIONS:
    try:
        conn.execute(table_def.sql)
        conn.commit()
    except Exception as e:
        conn.rollback()
        if "corrupt" in str(e) and table_def.name in REPAIRABLE_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table_def.name}")
            conn.execute(table_def.sql)
            conn.commit()
        else:
            _LOGGER.error("Table %s failed: %s", table_def.name, e)
```

**Prevention:**
- [ ] Wrap each DB table creation in its own try/except + commit
- [ ] Use whitelists (frozenset) for destructive auto-repair (DROP TABLE)
- [ ] Log failures but continue with other operations
- [ ] Test with intentionally corrupted tables

**Discovered:** v3.13.0
**Impact:** All coordinator DB operations broken by one corrupt table
**Severity:** CRITICAL

---

### Bug Class #10: Cross-Restart State Loss (In-Memory Only) ⚠️

**The Mistake:**
```python
# ❌ WRONG - Critical state in memory only
class EnergyCoordinator:
    def __init__(self):
        self.daily_consumption_kwh = 0.0  # Resets to 0 on restart
        self.load_shedding_level = 0      # Protection drops
        self.battery_full_time = None     # "unknown" until Envoy reconnects
        self.consumption_history = {}     # Prediction fallback to default
```

**Why it fails:**
- HA restart kills process → all in-memory state lost mid-day
- Midnight billing accumulators reset to zero
- Load shedding defenses drop instantly
- Battery timing unknown until next Envoy update
- Consumption predictions fall back to generic defaults

**The Fix:**
```python
# ✅ CORRECT - DB persistence with save/restore
async def async_setup(self):
    await self._restore_consumption_history()  # Per-DOW baselines
    await self._restore_midnight_snapshot()    # Billing + lifetime
    await self._restore_envoy_cache()          # Battery timing (4h staleness guard)
    await self._restore_load_shedding_level()  # 3-cycle grace period

async def async_teardown(self):
    await self._save_all_state()

# Also save periodically (every 15 min) for crash resilience
```

**Prevention:**
- [ ] Identify all critical state in each coordinator
- [ ] Persist to DB at shutdown + periodic intervals
- [ ] Restore at startup with date/staleness checks
- [ ] Add grace periods for restored state (e.g., 3-cycle hold on load shedding)
- [ ] Test: kill HA process, restart, verify state continuity

**Discovered:** v3.14.0, v3.15.0
**Impact:** Wrong energy calculations, lost load shedding protection, unknown battery timing
**Severity:** CRITICAL

---

### Bug Class #11: UTC vs Local Timezone Date Comparison ⚠️

**The Mistake:**
```python
# ❌ WRONG - Compare UTC date() against local date()
setting = sun_entity.attributes['setting']  # UTC datetime
now_local = dt_util.now()                   # Local timezone

if setting.date() == now_local.date():  # FALSE after midnight UTC!
    window_hours = (setting - rising).total_seconds() / 3600
else:
    window_hours = 4.0  # Fallback — wrong
```

**Why it fails:**
- Sunset at 7:40 PM CDT = 00:40 UTC **next day**
- `setting.date()` returns March 14 (UTC), `now_local.date()` returns March 13 (CDT)
- Date comparison fails → falls through to 4h default instead of correct 12h window
- All solar-dependent calculations (battery strategy, forecasting) are wrong

**The Fix:**
```python
# ✅ CORRECT - Convert to same timezone before comparing dates
rising_local = rising.astimezone(now_local.tzinfo)
setting_local = setting.astimezone(now_local.tzinfo)

if rising_local.date() == now_local.date():
    window_hours = (setting_local - rising_local).total_seconds() / 3600
```

**Prevention:**
- [ ] ALWAYS normalize datetimes to same timezone before `.date()` comparison
- [ ] Use `.astimezone(tz)` to convert UTC → local before date ops
- [ ] Never compare `.date()` between UTC-aware and local-aware datetimes
- [ ] Test across timezone boundaries (sunset near midnight UTC)

**Discovered:** v3.14.2
**Impact:** Solar window 4h instead of 12h, wrong battery strategy
**Severity:** HIGH

---

### Bug Class #12: Thread-Unsafe State Writes from Signal Handlers ⚠️

**The Mistake:**
```python
# ❌ WRONG - Direct state write from dispatcher callback
def _handle_census_update(self, data):
    self._attr_native_value = data["count"]
    self.async_write_ha_state()  # RuntimeError: not from event loop
```

**Why it fails:**
- HA 2026+ / Python 3.14 enforce that `async_write_ha_state()` must be called from the event loop thread
- Dispatcher signal callbacks may run in worker threads
- Result: RuntimeError, frozen UI, entity updates lost

**The Fix:**
```python
# ✅ CORRECT - Use scheduler-safe method
def _handle_census_update(self, data):
    self._attr_native_value = data["count"]
    self.async_schedule_update_ha_state()  # Safe from any thread
```

**Prevention:**
- [ ] Never call `async_write_ha_state()` from signal handlers or callbacks
- [ ] Use `async_schedule_update_ha_state()` for thread-safe state pushes
- [ ] Audit all `async_dispatcher_connect` handlers for direct state writes
- [ ] Search for `async_write_ha_state` outside of `async def` methods

**Discovered:** v3.15.2
**Impact:** RuntimeError, entity not updating, frozen UI
**Severity:** HIGH

---

### Bug Class #13: DB Returns Strings Where Datetime Expected ⚠️

**The Mistake:**
```python
# ❌ WRONG - Assumes DB always returns datetime objects
last_time = db_result['last_occupant_time']
attributes = {'time': last_time.isoformat()}  # AttributeError if string
```

**Why it fails:**
- SQLite returns timestamps as strings (ISO format), not datetime objects
- Code assumed datetime, called `.isoformat()` on an already-formatted string
- Result: AttributeError or double-encoding

**The Fix:**
```python
# ✅ CORRECT - Type guard before method call
last_time = db_result['last_occupant_time']
if isinstance(last_time, str):
    time_str = last_time
else:
    time_str = last_time.isoformat() if last_time else None
```

**Prevention:**
- [ ] Always guard DB values with `isinstance()` before calling type-specific methods
- [ ] SQLite returns strings for TEXT columns — never assume datetime
- [ ] Test with raw DB data, not just mocks with datetime objects

**Discovered:** v3.15.2
**Impact:** AttributeError in sensor attributes
**Severity:** MEDIUM

---

### Bug Class #14: Config Snapshot Staleness (Read Once at Init) ⚠️

**The Mistake:**
```python
# ❌ WRONG - Read config once, cache forever
class NotificationManager:
    async def async_setup(self):
        self._severity_threshold = self.config_entry.options.get('severity', 'LOW')

    async def async_notify(self, alert):
        if alert.severity >= self._severity_threshold:  # Stale value
            await self._send(alert)
```

**Why it fails:**
- Config read once at setup, cached in instance variable
- User changes severity via OptionsFlow → `entry.options` updated
- Coordinator still has old value in memory → changes ignored until restart

**The Fix:**
```python
# ✅ CORRECT - Re-read config on each operation
async def async_notify(self, alert):
    self._refresh_config()  # Re-read entry.options each time
    if alert.severity >= self._severity_threshold:
        await self._send(alert)

def _refresh_config(self):
    config = {**self._config_entry.data, **self._config_entry.options}
    self._severity_threshold = config.get('severity', 'LOW')
```

**Prevention:**
- [ ] For user-editable config, re-read at operation time (not just init)
- [ ] Call `_refresh_config()` at top of every public method
- [ ] Test: Change config in OptionsFlow, verify immediate effect without restart
- [ ] Don't rely on config_entry_update listener for immediate effect (async race)

**Discovered:** v3.15.3
**Impact:** Severity/filter changes ignored until HA restart
**Severity:** HIGH

---

### Bug Class #15: Inbound Message Spam (No Sender/Context Filtering) ⚠️

**The Mistake:**
```python
# ❌ WRONG - Process ALL inbound messages indiscriminately
def _handle_webhook(self, data):
    sender = data['sender']
    message = data['message']
    self._process_inbound_reply(sender, message)  # Fires for everything
```

**Why it fails:**
- Webhook fires for every message (group chats, random texts, spam)
- Unknown senders get "Unknown command" responses → reply loops
- Known persons' random texts trigger reply bot without alert context
- Kill switch doesn't block inbound processing

**The Fix:**
```python
# ✅ CORRECT - Three-layer inbound filter
def _handle_webhook(self, data):
    # Layer 1: Known sender only
    person_id = self._person_from_sender(data['sender'])
    if person_id is None:
        return  # Silently ignore

    # Layer 2: Context required (active alert or recent NM activity)
    if not self._is_reply_context_active():
        return

    # Layer 3: Kill switch
    if self._messaging_suppressed:
        return

    self._process_inbound_reply(person_id, data['message'])
```

**Prevention:**
- [ ] Add unknown sender filter to ALL inbound handlers
- [ ] Require alert/activity context before auto-replying
- [ ] Kill switch must block inbound processing too
- [ ] Test: unknown sender → no reply; known person without context → no reply

**Discovered:** v3.15.3.1
**Impact:** Unwanted replies to strangers, reply loops, spam
**Severity:** HIGH

---

### Bug Class #16: CRITICAL Severity Bypasses All Safety Filters ⚠️

**The Mistake:**
```python
# ❌ WRONG - Hardcode CRITICAL severity on routine alerts
async def _notify_circuit_anomaly(self, circuit):
    await self.nm.async_notify({
        'severity': 'CRITICAL',  # Bypasses quiet hours, kill switch, threshold
        'title': f"Breaker alert: {circuit.name}"
    })
```

**Why it fails:**
- CRITICAL is designed to bypass quiet hours, kill switch, and severity threshold
- Routine breaker alerts hardcoded as CRITICAL → bypass ALL NM protections
- Every unknown circuit spike → CRITICAL → unblockable notification spam

**The Fix:**
```python
# ✅ CORRECT - Severity appropriate to alert type
severity = 'HIGH'  # Important but not emergency
if circuit.name == 'unknown':
    return  # Filter unknown circuits entirely
if circuit.consumption_wh < 50:
    return  # Filter low-energy noise

await self.nm.async_notify({'severity': severity, 'title': ...})
```

**Prevention:**
- [ ] Reserve CRITICAL for true emergencies only (fire, break-in, generator failure)
- [ ] Derive severity from alert characteristics, never hardcode CRITICAL
- [ ] All filtering (kill switch, quiet hours) must apply to EVERY severity level
- [ ] Add energy/consumption threshold to filter noise alerts

**Discovered:** v3.16.0
**Impact:** Unblockable alert spam, kill switch ineffective
**Severity:** HIGH

---

### Bug Class #17: Unbounded Retry Loops on Dependent Initialization ⚠️

**The Mistake:**
```python
# ❌ WRONG - Retry forever without limit
async def async_added_to_hass(self):
    while True:
        try:
            await self._sync_to_nm()
            break
        except:
            await asyncio.sleep(10)  # No max retries!
```

**Why it fails:**
- If the dependent service (NM) never initializes, loop retries indefinitely
- Consumes asyncio task slot forever
- No logging after timeout → silent resource leak
- No cleanup on entity removal → orphaned task

**The Fix:**
```python
# ✅ CORRECT - Bounded retry with timeout
MAX_RETRIES = 18  # 18 * 10s = 3 minutes cap

async def async_added_to_hass(self):
    for attempt in range(MAX_RETRIES):
        try:
            await self._sync_to_nm()
            return
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(10)
            else:
                _LOGGER.warning("NM sync failed after %d attempts: %s", MAX_RETRIES, e)
                return  # Give up gracefully
```

**Prevention:**
- [ ] Every retry loop must have explicit max count
- [ ] Total wait time cap: max_retries * delay < 5 minutes
- [ ] Log warning and give up gracefully on timeout
- [ ] Store timer/task handle for cancellation on teardown
- [ ] Test: simulate dependency never initializing, verify cleanup

**Discovered:** v3.16.0
**Impact:** Resource leak, thread starvation, orphaned tasks
**Severity:** MEDIUM

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

**Minimum Coverage:** 90%
**Current Test Count:** 1,126 tests (as of v3.16.0)

**Required Tests:**
- Unit tests for all sensor types
- Integration tests for automation logic
- Regression tests for known bug classes
- Config flow tests for all steps
- Database tests for all operations
- Energy coordinator restart resilience tests
- Notification manager inbound/outbound tests
- AI automation type safety tests

### Test Execution

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/ -v
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
- [x] All tests passing (1,126+)
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
- [ ] All tests pass (1,126+)
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

**Quality Context v4.0**
**Last Updated:** March 18, 2026
**Next Update:** After discovering new patterns
**Status:** Active quality standards
