# Universal Room Automation v3.5.3 — Zone Device Duplication Fix

**Release Date:** 2026-02-25
**Internal Reference:** Cycle -1 (hotfix)
**Previous Release:** v3.5.2
**Minimum HA Version:** 2024.1+
**Depends on:** v3.5.2

---

## Summary

v3.5.3 is a targeted fix for duplicate zone devices appearing in the HA device registry. The duplicates were **orphaned zone devices from before the v3.3.5.6 migration** that were never cleaned up. This release adds startup orphan cleanup, hardens the migration guard, and adds preventive cleanup on zone rename, unload, and delete. No new entities or features — strictly a device registry hygiene release.

### What's Fixed

- **Startup orphan cleanup** — On integration entry setup, scans the device registry for zone devices whose zone name doesn't match any active zone config entry and removes them. Cleans up pre-migration orphans on first restart after the update.
- **Hardened migration guard** — Moved `zone_migration_done` flag from `entry.options` to `entry.data` so it survives option resets and isn't accidentally re-triggered.
- **Zone unload/delete cleanup** — When a zone entry is unloaded or deleted, its zone device is now removed from the device registry.
- **Zone rename cleanup** — When a zone is renamed via the options flow, the old zone device is removed before the new one is created, preventing orphans.
- **Disabled custom zone names in room options** — The zone selector in room basic setup no longer allows typing arbitrary zone names (`custom_value=False`). Users must create zones via the dedicated "Add Zone" flow.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `__init__.py` | Modified | Startup orphan cleanup (~20 lines), migration guard hardened (~3 lines), zone unload device removal (~8 lines) |
| `config_flow.py` | Modified | Zone rename device cleanup (~14 lines), disabled custom zone names (~1 line) |

---

## How to Deploy

### From source (development)

```bash
./scripts/deploy.sh "3.5.3" "Fix zone device duplication" "- Startup orphan cleanup removes stale zone devices from pre-v3.3.5.6 migration
- Harden migration guard (moved to entry.data from entry.options)
- Remove zone device from registry on zone entry unload/delete
- Remove orphaned zone device on zone rename
- Disable custom zone names in room options (must use Add Zone flow)"
```

### HACS update

After the GitHub release is published, HACS will detect v3.5.3 as an available update. Update through the HACS UI and restart Home Assistant.

### Manual install

1. Download the release zip from GitHub
2. Extract to `custom_components/universal_room_automation/`
3. Restart Home Assistant

---

## How to Verify It Works

### 1. Orphaned zone devices are removed on restart

1. Before updating, note any duplicate zone devices in **Settings > Devices & Services > Universal Room Automation**
2. Update to v3.5.3 and restart Home Assistant
3. Check the device list — orphaned zone devices should be gone
4. Check logs for: `Removed orphaned zone device: zone_<name>`
5. Only active zone devices (those with matching zone config entries) should remain

### 2. Zone rename removes old device

1. Go to **Settings > Devices & Services > Universal Room Automation > Configure**
2. Select a zone and rename it (e.g., "Upstairs" → "Second Floor")
3. Check devices — "Upstairs" device should be gone, "Second Floor" device should exist
4. No orphaned device left behind

### 3. Zone delete removes device

1. Delete a zone entry from the integration
2. Check devices — the zone device for the deleted zone should be removed from the registry

### 4. Room options zone selector

1. Go to room configuration > Basic Setup
2. The zone dropdown should only show existing zones — no free-text entry allowed
3. To create a new zone, use the "Add Zone" flow from the integration menu

### 5. Migration guard persists

1. Restart Home Assistant twice
2. Check logs — zone migration should not re-run on the second restart
3. The `zone_migration_done` flag is now stored in `entry.data` (durable) instead of `entry.options`

---

## Graceful Degradation

| Scenario | Behavior |
|---|---|
| No orphaned devices exist | Startup cleanup scans but finds nothing to remove. No errors. |
| Orphan cleanup fails | Caught as non-fatal warning. Integration setup continues normally. |
| Zone with no device is unloaded | `async_get_device` returns None, skip removal. No error. |
| Zone renamed to same name | Old name equals new name — no device removal triggered. |

---

## Version Mapping

| External Version | Cycle | Internal Plan Reference | Feature |
|-----------------|-------|------------------------|---------|
| 3.3.5.8 | Cycle 1 | — | Bug fixes + occupancy resiliency |
| 3.3.5.9 | Cycle 2 | — | Safe service calls + HVAC zone presets |
| 3.4.0 | Cycle 3 | PLANNING_v3.5.0_CYCLE_3.md | Camera census foundation |
| 3.4.1 – 3.4.6 | Cycle 3 patches | — | Camera config at integration level + stability |
| 3.5.0 | Cycle 4 Slim | PLANNING_v3.5.1_CYCLE_4_SLIM.md | Camera occupancy extension, zone aggregation, perimeter alerting |
| 3.5.1 | Cycle 5 | PLANNING_v3.4.0_CYCLE_5.md | Consistent sensor naming |
| 3.5.2 | Cycle 6 | PLANNING_v3.5.2_CYCLE_6.md | Transit validation + warehoused sensors |
| **3.5.3** | **Cycle -1** | **—** | **Zone device duplication fix (this release)** |
