# v3.12.1 — AI Automation Type Safety Hotfix

**Date**: 2026-03-12
**Scope**: Post-review hardening of AI rule execution path
**Tests**: 1008 total (no change)

---

## Summary

Addresses type safety and code quality issues found in the v3.12.0 post-deploy reviews. No functional changes — purely defensive hardening against malformed AI parser output.

## Fixes

### Type Safety in AI Rule Execution (coordinator.py)
- Guard against non-dict `action` items in `_execute_rule_action`
- Guard against non-dict `target` field (AI could return string instead of object)
- Guard against non-dict `data` field (prevents `{**non_dict}` TypeError)
- Removed meaningless `asyncio.wait_for` wrapper around `blocking=False` service call

### Type Safety in AI Rule Validation (config_flow.py)
- Guard against non-dict action items in `_validate_parsed_actions`
- Guard against non-dict `target` field with error message
- Both guards provide clear error messages to the user during config flow

### Import Cleanup (safety.py, security.py)
- Moved `SafetyHazardPayload` and `SecurityEventPayload` imports to module level
- Removed per-invocation local imports in signal dispatch paths
- Used `hazard.value` directly instead of `getattr(hazard, "value", None)` (field is guaranteed by dataclass)

## Files Changed

| File | Changes |
|------|---------|
| `coordinator.py` | Type guards in `_execute_rule_action`, removed `asyncio.wait_for` |
| `config_flow.py` | Type guards in `_validate_parsed_actions` |
| `domain_coordinators/safety.py` | Module-level import, direct attribute access |
| `domain_coordinators/security.py` | Module-level import, removed local imports |
