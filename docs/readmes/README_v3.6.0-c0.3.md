# Universal Room Automation v3.6.0-c0.3 — Fix Coordinator Entities Unavailable

**Release Date:** 2026-02-28
**Internal Reference:** C0.3 (Domain Coordinators — Coordinator Entity Fix)
**Previous Release:** v3.6.0-c0.2
**Minimum HA Version:** 2024.1+
**Depends on:** v3.6.0-c0.2

---

## Summary

v3.6.0-c0.3 fixes the three coordinator entities (Coordinator Manager, House State, Coordinator Summary) that were stuck as "unavailable" since the initial v3.6.0-c0 release. The root cause was a unique_id conflict: old entity registrations under the integration config entry blocked recreation under the new Coordinator Manager entry.

### What's Fixed

- **Coordinator entities unavailable** — The 3 coordinator sensors (`sensor.ura_coordinator_manager`, `sensor.ura_house_state`, `sensor.ura_coordinator_summary`) showed as "unavailable" with `restored: true` because:
  1. Old entity registrations from the integration entry occupied the unique_ids
  2. When the Coordinator Manager entry tried to create the same entities, the unique_id conflict silently prevented creation
  3. The old entries, no longer backed by any platform, remained in "restored/unavailable" state
- **Fix:** The `_ensure_coordinator_manager_entry` migration now removes old entity registrations from the entity registry before creating the new CM config entry, allowing the entities to be properly recreated.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `__init__.py` | Modified | Added entity registry cleanup in `_ensure_coordinator_manager_entry` — removes old coordinator entity registrations before creating CM entry (+18 lines) |
| `const.py` | Modified | Version bump to 3.6.0-c0.3 |
| `manifest.json` | Modified | Version bump to 3.6.0-c0.3 |

---

## How to Deploy

```bash
./scripts/deploy.sh "3.6.0-c0.3" "Fix coordinator entities unavailable after migration" \
  "- Remove old coordinator entity registrations before creating Coordinator Manager entry
- Prevents unique_id conflicts that left entities in restored/unavailable state"
```

---

## How to Verify It Works

### 1. Coordinator entities are live

1. Restart Home Assistant after updating
2. Navigate to Settings > Devices & Services > Universal Room Automation
3. Open the Coordinator Manager device
4. Verify these entities show values (not "unavailable"):
   - `sensor.ura_coordinator_manager` — should show "not_initialized" or "running"
   - `sensor.ura_house_state` — should show a house state value
   - `sensor.ura_coordinator_summary` — should show "all_clear" or similar

### 2. Entity registry is clean

1. Check Developer Tools > States
2. Search for `ura_coordinator` and `ura_house_state`
3. Verify none show `restored: true` in attributes

---

## Root Cause Analysis

**Entity Registry Conflict:** When v3.6.0-c0.2 introduced the Coordinator Manager as a separate config entry, it created a new config entry and attempted to register sensors with the same unique_ids (`universal_room_automation_coordinator_manager`, `universal_room_automation_house_state`, `universal_room_automation_coordinator_summary`). However, the old entity registrations from the integration config entry still existed in the entity registry. HA's entity registry enforces unique_id uniqueness per domain — the new sensors were silently rejected, and the old entries (no longer backed by a platform) showed as "restored/unavailable".

**Fix:** Added entity registry cleanup to `_ensure_coordinator_manager_entry()`:
```python
coordinator_unique_ids = [
    f"{DOMAIN}_coordinator_manager",
    f"{DOMAIN}_house_state",
    f"{DOMAIN}_coordinator_summary",
]
for uid in coordinator_unique_ids:
    entity = ent_reg.async_get_entity_id("sensor", DOMAIN, uid)
    if entity:
        ent_reg.async_remove(entity)
```

---

## Version Mapping

| External Version | Cycle | Feature |
|-----------------|-------|---------|
| 3.6.0-c0 | C0 | Domain coordinator base infrastructure |
| 3.6.0-c0.1 | Hotfix | Camera census discovery + periodic updates |
| 3.6.0-c0.2 | C0.2 | Integration page organization + census graceful degradation |
| **3.6.0-c0.3** | **C0.3** | **Fix coordinator entities unavailable (this release)** |
