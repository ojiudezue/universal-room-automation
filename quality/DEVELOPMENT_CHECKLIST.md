# 🛡️ Development Checklist - Preventing Regression Cascades

**Purpose:** Ensure bulletproof code changes by following systematic validation  
**Created:** November 24, 2025  
**Based on:** v2.3.1-2-3 regression cascade lessons learned  

---

## 📋 Master Checklist - Use for EVERY Change

### Phase 1: Problem Analysis (Don't Rush This)
- [ ] **Read the error completely** - Full stack trace, not just the message
- [ ] **Identify root cause** - Why did this happen? Not just where?
- [ ] **Find all instances** - Search entire codebase for same pattern
- [ ] **Check related code** - What else might have this issue?
- [ ] **Document findings** - Write down what you found before fixing

**Time budget:** 15-20 minutes  
**Why:** Understanding prevents cascade fixes

---

### Phase 2: Comprehensive Search
- [ ] **Search all Python files** for the problematic pattern
  ```bash
  grep -r "pattern" *.py > search_results.txt
  cat search_results.txt  # Review ALL matches
  wc -l search_results.txt  # Know the scope
  ```
- [ ] **Search config files** if relevant (YAML, JSON)
- [ ] **Check coordinator** if sensor issue (and vice versa)
- [ ] **Check all platform files** (binary_sensor.py, sensor.py, switch.py, etc.)
- [ ] **Document total instances found** - Write it down: "Found 34 instances in 3 files"

**Time budget:** 5-10 minutes  
**Why:** Prevents fixing 32 of 34 instances (v2.3.2 mistake)

---

### Phase 3: Categorization & Planning
- [ ] **Group findings by type**
  - Return statements with defaults: `return data.get(KEY, DEFAULT)`
  - Return statements without defaults: `return data.get(KEY)`
  - Variable assignments: `var = data.get(KEY)`
  - Conditionals: `if data.get(KEY):`
  - Dictionary attributes: `{attr: data.get(KEY)}`
  - **Class definitions: DON'T TOUCH**
  - **Import statements: DON'T TOUCH**
- [ ] **Plan specific fix for each type** - Different patterns need different fixes
- [ ] **Identify special cases** - Anything unusual that needs manual review?
- [ ] **Document fix strategy** - Write out what you'll do for each type

**Time budget:** 10-15 minutes  
**Why:** Automated fixes need careful planning

---

### Phase 4: Implementation
- [ ] **Create backup first**
  ```bash
  cp -r integration integration_backup_$(date +%Y%m%d_%H%M%S)
  ```
- [ ] **Fix one category at a time** - Don't mix different fix types
- [ ] **Validate after each file** - Compile immediately, don't wait
  ```bash
  python3 -m py_compile filename.py
  ```
- [ ] **Keep running count** - "Fixed 5 of 34 instances"
- [ ] **Review each changed line** - Does it make sense?
- [ ] **Check for unintended changes** - Did script modify wrong lines?

**Time budget:** 20-30 minutes  
**Why:** Prevents class definition disasters (v2.3.1 mistake)

---

### Phase 5: Pre-Deployment Validation (MANDATORY)
- [ ] **Compile ALL Python files**
  ```bash
  for file in *.py; do
      python3 -m py_compile "$file" && echo "✅ $file" || echo "❌ $file FAILED"
  done
  ```
- [ ] **No syntax errors** - Every file must compile cleanly
- [ ] **Search for missed instances**
  ```bash
  grep -r "pattern" *.py | grep -v "if data" | grep -v "and data"
  wc -l  # Should be 0
  ```
- [ ] **Review git diff** (or manual comparison)
  - Any unexpected changes?
  - Class definitions unchanged?
  - Imports unchanged?
- [ ] **Version number updated** in const.py and manifest.json
- [ ] **Count total fixes** - "34 instances fixed in 3 files"

**Time budget:** 10-15 minutes  
**Why:** Catches syntax errors before deployment (would have caught v2.3.1)

---

### Phase 6: Documentation
- [ ] **Create CHANGELOG entry** - What changed and why
- [ ] **List all modified files** with line counts
- [ ] **Document fix patterns used** - For future reference
- [ ] **Note any known limitations** - What still needs work?
- [ ] **Create deployment instructions** - How to install this fix

**Time budget:** 10-15 minutes  
**Why:** Continuity for future sessions

---

### Phase 7: Deployment
- [ ] **Deploy to test environment first** (if available)
- [ ] **Copy ALL modified files** - Don't skip any
- [ ] **Verify file permissions** - Must be readable by HA
- [ ] **Restart Home Assistant**
- [ ] **Don't walk away yet** - Monitor for 5 minutes

**Time budget:** 5 minutes  
**Why:** Catch issues immediately

---

### Phase 8: Post-Deployment Verification
- [ ] **Check logs immediately**
  ```bash
  tail -f /config/home-assistant.log | grep integration_name
  ```
- [ ] **Look for these errors** in first 2 minutes:
  - SyntaxError → Compilation missed something
  - ImportError → File missing or wrong location
  - AttributeError → Missed an instance
  - NameError → Undefined variable
  - TypeError → Wrong data type
- [ ] **Verify integration loaded** - Check Devices & Services
- [ ] **Test basic functionality** - Does main feature work?
- [ ] **Monitor for 5 minutes** - Watch for delayed errors
- [ ] **Test edge cases** - Restart HA, reload integration

**Time budget:** 10-15 minutes  
**Why:** Catch issues before they become user problems

---

### Phase 9: If Issues Found
- [ ] **DON'T deploy more fixes immediately** - Understand what went wrong
- [ ] **Document the new issue** - What happened?
- [ ] **Return to Phase 1** - Start checklist over
- [ ] **Check for missed instances** - Re-search codebase
- [ ] **Consider root cause changed** - Maybe first analysis was wrong

**Time budget:** Variable  
**Why:** Break the cascade (v2.3.1→2→3 happened because I rushed)

---

## 🎯 Scenario-Specific Checklists

### Scenario A: Fixing AttributeError / NoneType Issues

**Additional checks:**
- [ ] Search for `data.get(` in ALL files (not just reported file)
- [ ] Check coordinator AND all platform files
- [ ] Look for related patterns: `data[key]`, `data.keys()`, `data.values()`
- [ ] Verify data initialization in coordinator `__init__`
- [ ] Check if `data` starts as `None` or empty dict
- [ ] Test with fresh HA start (when data is None)
- [ ] Add None checks BEFORE accessing data:
  ```python
  if not self.coordinator.data:
      return None
  return self.coordinator.data.get(KEY)
  ```

**Common locations:**
- coordinator.py: `self.data`
- sensor.py: `self.coordinator.data`
- binary_sensor.py: `self.coordinator.data`
- Any platform file accessing coordinator

---

### Scenario B: Using Automated Scripts for Fixes

**DANGER ZONE - Extra precautions needed:**

- [ ] **Manual review first** - Find 5-10 examples by hand
- [ ] **Test script on single file** - Not entire codebase
- [ ] **Review output before applying** - Check diff carefully
- [ ] **Never modify these:**
  - [ ] Class definitions (`class Name:`)
  - [ ] Import statements (`import`, `from`)
  - [ ] Function definitions (`def name():`)
  - [ ] Decorators (`@property`, `@callback`)
  - [ ] Comments
  - [ ] Docstrings
- [ ] **Use strict regex patterns:**
  ```python
  # BAD - too broad
  re.sub(r'data.get', ...)
  
  # GOOD - specific context
  re.match(r'^(\s+)return self\.coordinator\.data\.get\(([^)]+)\)$', line)
  ```
- [ ] **Add explicit skips:**
  ```python
  if line.strip().startswith('class '):
      continue  # NEVER modify class definitions
  if line.strip().startswith('import '):
      continue  # NEVER modify imports
  if line.strip().startswith('def '):
      continue  # NEVER modify function defs
  ```
- [ ] **Validate each file in script:**
  ```python
  subprocess.run(['python3', '-m', 'py_compile', filepath], check=True)
  ```
- [ ] **Create before/after comparison** - Review every change
- [ ] **Count changes per file** - Does it match expectations?

**Remember:** Automated fixes caused v2.3.1 SyntaxError. Be VERY careful.

---

### Scenario C: Fixing Config Flow Issues

**Additional checks:**
- [ ] Test with blank inputs
- [ ] Test with invalid inputs  
- [ ] Test with missing required fields
- [ ] Verify error messages are user-friendly
- [ ] Check translation strings exist
- [ ] Test reconfiguration (not just initial setup)
- [ ] Verify defaults work correctly
- [ ] Check for proper validation

**Common mistakes:**
- Missing `_LOGGER` import
- Required fields in options flow (should be optional)
- No validation on user input
- Missing error handling

---

### Scenario D: Adding New Features

**Additional checks:**
- [ ] Does this change existing behavior?
- [ ] Are there backwards compatibility concerns?
- [ ] Do old configs still work?
- [ ] Does this require database migration?
- [ ] Are there new None check locations?
- [ ] Does coordinator need updates?
- [ ] Do all platform files need updates?
- [ ] Is documentation updated?

---

## 🚨 Emergency Hotfix Procedures

**When production is broken and users are waiting:**

### Option 1: Targeted Fix (Preferred)
1. [ ] Find EXACT failing line from error log
2. [ ] Fix ONLY that line
3. [ ] Compile ONLY that file
4. [ ] Deploy ONLY that file + version bump
5. [ ] Monitor for 5 minutes
6. [ ] If stable, THEN search for related issues

**Time: 10-15 minutes**

### Option 2: Rollback (If Option 1 unclear)
1. [ ] Copy previous working version
2. [ ] Deploy immediately
3. [ ] THEN analyze problem thoroughly
4. [ ] Follow full checklist for proper fix

**Time: 5 minutes**

### DON'T:
- ❌ Deploy multiple fixes at once
- ❌ Use automated scripts under pressure
- ❌ Skip compilation checks
- ❌ Assume you found all instances

**Remember:** v2.3.1→2→3 cascade happened because I tried to fix fast. Slow down.

---

## 🎓 Code Patterns Reference

### ✅ SAFE: Always Check for None First

```python
# Pattern 1: Property with None check
@property
def native_value(self):
    if not self.coordinator.data:
        return None  # or appropriate default
    return self.coordinator.data.get(STATE_TEMPERATURE)

# Pattern 2: Inline conditional
@property
def native_value(self):
    return self.coordinator.data.get(STATE_TEMPERATURE) if self.coordinator.data else None

# Pattern 3: With default value
@property
def native_value(self):
    return self.coordinator.data.get(STATE_TEMPERATURE, 20.0) if self.coordinator.data else 20.0

# Pattern 4: In conditionals
if self.coordinator.data and self.coordinator.data.get(STATE_OCCUPIED):
    # Do something

# Pattern 5: Boolean checks
is_on = (self.coordinator.data and 
         self.coordinator.data.get(STATE_OCCUPIED, False))
```

---

### ❌ UNSAFE: Direct Access Without Checks

```python
# WRONG - Can crash if data is None
@property
def native_value(self):
    return self.coordinator.data.get(STATE_TEMPERATURE)

# WRONG - Assumes data exists
if self.coordinator.data.get(STATE_OCCUPIED):
    # Crashes if data is None

# WRONG - Direct dictionary access
temp = self.coordinator.data[STATE_TEMPERATURE]

# WRONG - Checking after access
value = self.coordinator.data.get(KEY)
if self.coordinator.data:  # Too late!
    return value
```

---

### 🎯 Coordinator-Specific Patterns

```python
# SAFE: Check self.data in coordinator
def _async_update_data(self):
    data = {}
    
    # Build new data...
    
    # When checking previous state:
    if motion_detected and (not self.data or not self.data.get(STATE_MOTION)):
        # Track trigger
        pass
    
    return data

# SAFE: Initialize data properly
def __init__(self, ...):
    super().__init__(...)
    # Don't leave data as None - use empty dict
    self._last_data = {}  # Not None
```

---

## 📊 Time Investment vs. Results

| Approach | Time | Quality | User Impact |
|----------|------|---------|-------------|
| **Quick fix** | 10 min | ⚠️ 30% chance of regression | Multiple broken versions |
| **Following checklist** | 70 min | ✅ 95% success rate | One working version |
| **Rushed + cascade fixes** | 3× 10 min | ❌ Multiple iterations | Frustrated users |

**Math:**
- Quick fix: 10 min × 3 attempts = 30 min coding + user frustration + lost credibility
- Proper fix: 70 min once = One stable version + user confidence

**Conclusion:** Following the checklist is actually FASTER when counting total time.

---

## 🔍 Red Flags - When to Stop and Reassess

**Stop and return to Phase 1 if:**
- [ ] You've deployed 2+ fixes for same issue
- [ ] You're not sure what caused the problem
- [ ] You haven't searched all files
- [ ] You're using automated scripts without testing
- [ ] You're under time pressure and feeling rushed
- [ ] You found "just one more instance" 3+ times
- [ ] Users are reporting new errors after your fix
- [ ] You're fixing errors in your error fixes

**These are signs of:**
- Incomplete problem analysis
- Cascading regressions
- Need to slow down and be systematic

---

## ✅ Success Criteria

**You've succeeded when:**
- [ ] All instances of pattern fixed (not just reported ones)
- [ ] All files compile without errors
- [ ] Integration loads successfully
- [ ] No errors in logs for 5+ minutes
- [ ] Basic functionality works
- [ ] Edge cases tested (restart, reload, etc.)
- [ ] No follow-up hotfixes needed
- [ ] Users report success

---

## 📝 Templates

### Bug Fix Commit Template
```
Fix: [Brief description]

Issue: [What was broken]
Root cause: [Why it was broken]
Instances fixed: [X locations in Y files]
Files modified: [List of files]
Validation: [All compile, no errors in logs]

Fixes #[issue number if applicable]
```

### Pre-Deployment Checklist Summary
```
□ Searched all files for pattern
□ Fixed [X] instances in [Y] files
□ All [Y] files compile successfully
□ No instances remain unfixed
□ Version bumped to [version]
□ Documentation updated
□ Ready for deployment
```

---

## 🎯 The Golden Rules

1. **Slow is smooth, smooth is fast** - Taking time upfront prevents cascades
2. **Search everywhere, not just error locations** - Bugs aren't isolated
3. **Validate continuously, not at the end** - Catch issues early
4. **One pattern, one systematic fix** - Not file-by-file
5. **Test in production mindset** - Users will find what you miss
6. **Document everything** - Future you will thank present you
7. **When in doubt, go slower** - Speed causes regressions

---

## 📖 Real Example: v2.3.1-2-3 Cascade

**What went wrong:**
- v2.3.1: Broad regex broke class definitions (no syntax check)
- v2.3.2: Fixed sensors, missed coordinator (incomplete search)
- v2.3.3: Found coordinator instances (finally systematic)

**What should have happened:**
1. Search ALL files: `grep -r "coordinator.data.get\|self.data.get" *.py`
2. Would have found: 32 in sensors + 2 in coordinator = 34 total
3. Fix all 34 systematically
4. Validate syntax before deploy
5. Deploy once, successfully

**Time comparison:**
- What happened: 3 iterations × 15 min = 45 min + user frustration
- What should have happened: 70 min once = Done right

---

## 🎓 Learning Resources

**When to use this checklist:**
- Every bug fix
- Every new feature
- Every automated change
- Every "quick fix"
- **Especially** when under time pressure

**How to use this checklist:**
- Print it out or keep it visible
- Check off items as you go
- Don't skip steps
- If you're tempted to skip, that's when you need it most

**Signs you need the checklist:**
- You've deployed same issue twice
- Users reporting new issues after your fix
- You're fixing errors in your fixes
- You're feeling rushed or pressured
- "Just one more quick fix..."

---

## 📞 When Things Go Wrong Anyway

**If you follow this and still have issues:**

1. **Don't panic** - You did your best
2. **Document what happened** - For learning
3. **Rollback if needed** - No shame in that
4. **Analyze what checklist missed** - Improve process
5. **Update this document** - Make it better

**Remember:** Even careful processes have gaps. The goal is continuous improvement.

---

## ✨ Final Thoughts

**This checklist exists because:**
- I made these mistakes so you don't have to
- Rushing causes more delays than being careful
- Systematic approaches prevent regressions
- User trust is earned through reliability

**Use this checklist when:**
- You want to fix it right the first time
- You value user experience
- You want to sleep well at night
- You care about code quality

**The v2.3.3 lesson:** "Measure twice, cut once" applies to code too.

---

**Version:** 1.0  
**Last Updated:** November 24, 2025  
**Based on:** Real regression cascade experience  
**Status:** Living document - update as you learn
