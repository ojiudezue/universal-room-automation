# Configuration UX — Review Findings

**Date:** 2026-03-02
**Reviewer:** ura-reviewer (opus)
**Scope:** config_flow.py, strings.json, translations/en.json, const.py, coordinator.py

## Key Metrics

| Metric | Value |
|--------|-------|
| Fields per room | 72 across 8 steps |
| 10-room house setup | 739 fields, 82 form submissions |
| vs Adaptive Lighting | 30s (1 step) vs 10-15 min (8 steps) |
| Area pre-population infrastructure | 80% exists, not wired up |

## P0 — Highest Impact

1. **Area-based entity pre-population** (~200 lines effort) — `area_id` collected in room_setup but never used to suggest entities. Coordinator already has `_get_entities_in_area()`. Presence and Safety do area-based discovery at runtime. Wire area registry queries into config_flow `suggested_value` params for sensors/devices steps. Saves 15+ manual selections per room.

2. **"Quick Setup" mode** — room_name + area_id + room_type → auto-discover → one confirmation screen → done. Current flow becomes "Advanced Setup" in options. Needed for mass adoption.

## P1 — Should Fix

3. **Cover config unconditional** — 12 fields (2 devices + 10 automation_behavior) shown even when no covers configured. Used by ~10-20% of rooms. Hide behind toggle or only show when covers selected.

4. **Auto-detect light/cover capabilities** — Query `supported_features` from entity registry instead of manual dropdown for `light_capabilities` and `cover_type`.

5. **Make Sleep/Energy/Notifications skippable** — Good defaults for most rooms. Making optional during initial setup reduces flow from 8 to 4-5 steps.

## P2 — Nice to Have

6. Night light fields (5) always shown — hide behind toggle
7. Fan speed fields (4) shown when fan_control off — conditional display
8. Scanner Areas field — only needed for sparse-scanner homes
9. Sunrise/sunset offset — rarely changed from default

## Conditional Field Analysis

| Section | Fields | Condition to Show | Currently |
|---------|--------|-------------------|-----------|
| Cover behavior | 10 | Covers configured | Always shown |
| Fan speed temps | 4 | fan_control_enabled | Always shown |
| Night light detail | 4 | Night lights selected | Always shown |
| Humidity fan | 2 | Humidity fans configured | Always shown |
| Sleep protection | 5 | Bedroom room type | Always shown |

## Implementation Notes

- HA config flows don't support dynamic show/hide within a single form
- Conditional display requires sub-steps or HA 2024.x+ "sections" feature
- `EntitySelectorConfig` does NOT support `area` filter — must use `suggested_value` approach
- Device fallback needed: many entities have `area_id` on device but NULL on entity (presence coordinator already handles this at lines 794-798)
