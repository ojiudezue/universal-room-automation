# Universal Room Automation v3.6.0-c0.2 — Integration Page Organization & Census Graceful Degradation

**Release Date:** 2026-02-27
**Internal Reference:** C0.2 (Domain Coordinators — Organization & Census Fix)
**Previous Release:** v3.6.0-c0.1
**Minimum HA Version:** 2024.1+
**Depends on:** v3.6.0-c0.1

---

## Summary

v3.6.0-c0.2 delivers two major fixes: (1) the HA integration page now shows a clean, non-duplicated hierarchy with separate config entries for Zone Manager and Coordinator Manager, and (2) the camera census system degrades gracefully when any camera platform is down, supporting 4 platforms (Frigate, UniFi Protect, Reolink, Dahua) with per-camera binary counting.

### What's New

- **Zone Manager config entry** — Zones are migrated from individual config entries into a single Zone Manager entry. Zones appear as a single collapsible group on the integration page instead of scattered entries.
- **Coordinator Manager config entry** — Coordinator sensors live under their own config entry, not nested under the integration entry. Clean separation on the HA integration page.
- **Genericized camera census** — Census supports 4 camera platforms: Frigate (numeric tier with face recognition) and UniFi/Reolink/Dahua (binary tier with per-camera person detection). Any configured platform contributes to the count.
- **Graceful degradation** — When Frigate is down, the system falls back to binary platforms only. When all platforms are down, census reports degraded mode. New `degraded_mode` and `active_platforms` attributes on census sensors.
- **Per-camera binary counting** — UniFi and other binary platforms now count per-camera detections instead of capping at 1.
- **Face recognition integration** — `_get_face_recognized_persons()` reads from `sensor.*_last_recognized_face` Frigate entities.
- **Platform availability detection** — `_is_entity_available()` helper checks entity exists and is not unavailable/unknown.

### What's Fixed

- **Duplicate zones on integration page** — Zones appeared both as standalone entries AND under the integration entry via `via_device` chains. Fixed by removing all `via_device` references and creating separate config entries.
- **Census capping UniFi count at 1** — `unifi_detected` was a single boolean, not per-camera. Now sums all non-Frigate camera detections.
- **Face recognition data unused** — `face_id_set` was hardcoded as `set()`. Now reads from Frigate `last_recognized_face` sensors.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `__init__.py` | Modified | Zone Manager migration, Coordinator Manager migration, removed `via_device` references, new entry type handlers (+264/-97 lines) |
| `aggregation.py` | Modified | Zone Manager sensor setup, removed `via_device` from zone sensors (+104/-30 lines) |
| `binary_sensor.py` | Modified | Zone Manager and Coordinator Manager entry type handlers (+19/-5 lines) |
| `camera_census.py` | Modified | Per-platform availability, binary counting, face recognition, degraded mode (+214/-70 lines) |
| `config_flow.py` | Modified | Zone Manager/Coordinator Manager migration steps, zone setup targets ZM entry (+152/-55 lines) |
| `const.py` | Modified | Added `ENTRY_TYPE_ZONE_MANAGER`, `ENTRY_TYPE_COORDINATOR_MANAGER`, version bump |
| `manifest.json` | Modified | Version bump to 3.6.0-c0.2 |
| `music_following.py` | Modified | Zone player config lookup checks Zone Manager entry first (+37/-10 lines) |
| `sensor.py` | Modified | Coordinator sensors created unconditionally via CM entry, removed `via_device` from coordinator DeviceInfo (+39/-15 lines) |
| `strings.json` | Modified | Added `zone_added` abort reason |
| `translations/en.json` | Modified | Added `zone_added` abort reason |

---

## How to Deploy

```bash
./scripts/deploy.sh "3.6.0-c0.2" "Fix integration page organization and census graceful degradation" \
  "- Migrate zones to Zone Manager config entry (single collapsible group)
- Create Coordinator Manager config entry (separate from integration)
- Remove via_device chains that caused duplicate zone display
- Genericize census for 4 camera platforms (Frigate/UniFi/Reolink/Dahua)
- Add per-camera binary counting and graceful degradation
- Add face recognition from Frigate last_recognized_face sensors"
```

---

## How to Verify It Works

### 1. Integration page organization

1. Open Settings > Devices & Services > Universal Room Automation
2. Verify you see separate collapsible groups:
   - **Universal Room Automation** (house-level, with integration entities)
   - **Zone Manager** (with all zone sensors underneath)
   - **Coordinator Manager** (with coordinator sensors)
   - Each **room** as its own standalone entry
3. Confirm NO duplicate zone entries — zones should NOT appear under both Zone Manager and the integration entry

### 2. Census graceful degradation

1. Check `sensor.universal_room_automation_persons_in_house` attributes
2. Verify `active_platforms` lists all available camera platforms
3. Verify `degraded_mode` is `false` when Frigate is running, `true` when Frigate is down
4. When Frigate is down, person count should still work using UniFi/Reolink/Dahua binary detection

### 3. Per-camera counting

1. Have multiple people visible on different cameras
2. Verify person count reflects actual camera-level detections, not capped at 1

---

## Graceful Degradation

| Scenario | Behavior |
|----------|----------|
| Frigate down, UniFi up | Binary counting from UniFi cameras, `degraded_mode: true` |
| UniFi down, Frigate up | Full numeric counting from Frigate, `degraded_mode: false` |
| All cameras down | Census reports 0, `degraded_mode: true`, `active_platforms: []` |
| No cameras configured | Census disabled, sensors show unknown |

---

## Version Mapping

| External Version | Cycle | Feature |
|-----------------|-------|---------|
| 3.6.0-c0 | C0 | Domain coordinator base infrastructure |
| 3.6.0-c0.1 | Hotfix | Camera census discovery + periodic updates |
| **3.6.0-c0.2** | **C0.2** | **Integration page organization + census graceful degradation (this release)** |
