# v3.6.22: Transition Detection Hotfix

**Date:** 2026-03-03
**Type:** Hotfix
**Severity:** High — silently broke music following and all transition-dependent features

## Bug

`NameError` in `transitions.py:270` — `_classify_path_type()` had broken indentation causing `loc_lower` to be referenced outside the scope where it was assigned.

**Error:**
```
NameError: cannot access free variable 'loc_lower' where it is not associated with a value in enclosing scope
```

**Impact:** 5 occurrences between 3:41-4:25 PM. Every person movement through a room matching from/to in history triggered the error, killing the entire transition detection pipeline. Music following health sensor showed stale data because no transitions flowed through.

## Root Cause

In the `for entry in recent:` loop, `loc_lower = location.lower()` was inside `if location not in [from_room, to_room]:`, but the subsequent `if any(term in loc_lower ...)` check was at the wrong indentation — outside that block. When `location` matched `from_room` or `to_room`, `loc_lower` was never assigned but the generator expression tried to access it.

## Fixes

### Fix 1: Indentation correction (`transitions.py:268-274`)
Moved `if any(term in loc_lower ...)` and its `return` statement inside the same `if` block as the `loc_lower` assignment.

### Fix 2: Error handling hardening (`transitions.py:138`)
Wrapped `_detect_transition()` call in try/except so future errors in path classification:
- Log the error with context (person, from, to)
- Update history (so the person's location tracking stays current)
- Return gracefully instead of becoming unhandled task exceptions

## Files Changed
- `custom_components/universal_room_automation/transitions.py` — 2 fixes
