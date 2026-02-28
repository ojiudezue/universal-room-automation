# Universal Room Automation v3.6.0-c2.7 — Fix Toggle Switches Not Appearing

**Release Date:** 2026-02-28
**Internal Reference:** C2.7 (hotfix)
**Previous Release:** v3.6.0-c2.6
**Minimum HA Version:** 2024.1+
**Depends on:** v3.6.0-c2.5 (which introduced the toggle switches)

---

## Summary

v3.6.0-c2.7 is a one-line hotfix. The per-coordinator toggle switches added in c2.5 (`DomainCoordinatorsSwitch`, `CoordinatorEnabledSwitch`) never appeared in Home Assistant because `Platform.SWITCH` was missing from `INTEGRATION_PLATFORMS` — the platform list used when forwarding entity setup for the Integration, Coordinator Manager, and Zone Manager config entries.

Room-level switches (AutomationSwitch, ManualMode, etc.) were unaffected because room entries use the full `PLATFORMS` list which already included `Platform.SWITCH`.

---

## Root Cause

```python
# Before (broken) — __init__.py line 74
INTEGRATION_PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
]

# After (fixed)
INTEGRATION_PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SWITCH,  # v3.6.0-c2.5: DomainCoordinatorsSwitch, CoordinatorEnabledSwitch
]
```

Three places call `async_forward_entry_setups(entry, INTEGRATION_PLATFORMS)`:
- Integration entry setup (line 855) — hosts `DomainCoordinatorsSwitch`
- Zone Manager entry setup (line 910) — no switches currently, but forward-compatible
- Coordinator Manager entry setup (line 935) — hosts `CoordinatorEnabledSwitch` (Presence + Safety)

The unload paths also use `INTEGRATION_PLATFORMS`, so adding `Platform.SWITCH` there correctly handles both setup and teardown.

---

## Files Changed

| File | Change |
|------|--------|
| `__init__.py` | Added `Platform.SWITCH` to `INTEGRATION_PLATFORMS` list |

---

## How to Verify It Works

After HA restart with c2.7:

1. **URA Integration device** should now show:
   - `switch.ura_domain_coordinators_enabled` (master toggle, icon: mdi:robot)

2. **Presence Coordinator device** should now show:
   - `switch.ura_presence_coordinator_enabled` (icon: mdi:account-group)

3. **Safety Coordinator device** should now show:
   - `switch.ura_safety_coordinator_enabled` (icon: mdi:shield-check)

4. Turning off `switch.ura_domain_coordinators_enabled` should:
   - Gray out the House State Override dropdowns (available=False)
   - Reload the integration entry

5. Turning off an individual coordinator toggle should:
   - Reload the integration entry
   - That coordinator should not be registered on next startup

---

## Version Mapping

| Version | Cycle | Description |
|---------|-------|-------------|
| 3.6.0-c0 | C0 | Domain coordinator base infrastructure |
| 3.6.0-c0.1 | C0.1 | Integration page organization |
| 3.6.0-c0.2 | C0.2 | Census graceful degradation fix |
| 3.6.0-c0.3 | C0.3 | Coordinator entity unavailability fix |
| 3.6.0-c0.4 | C0-diag | Coordinator diagnostics framework |
| 3.6.0-c1 | C1 | Presence Coordinator |
| 3.6.0-c2 | C2 | Safety Coordinator |
| 3.6.0-c2.1 | C2.1 | Fix unnamed device spam, options wipe, orphan cleanup |
| 3.6.0-c2.2 | C2.2 | CM options menu |
| 3.6.0-c2.3 | C2.3 | Fix house state "away" — initial inference on startup |
| 3.6.0-c2.4 | C2.4 | Fix census signal dispatch, zone configure error |
| 3.6.0-c2.5 | C2.5 | Per-coordinator toggle switches (code added) |
| 3.6.0-c2.6 | C2.6 | Fix zone presence "unknown", safety false positives, sensor rename |
| **3.6.0-c2.7** | **C2.7** | **Fix toggle switches not appearing (Platform.SWITCH missing)** |
