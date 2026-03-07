# v3.8.2 — Zone Manager Shallow Copy Bug Fix

## What Ships

### Critical Bug Fix: Zone options not persisting
Zone Manager options flow updates (zone_hvac, zone_media, zone_rooms, zone creation, climate auto-populate) used a **shallow copy** of the zones dict:

```python
zones = dict(merged.get("zones", {}))  # shallow — inner dicts are same references
zones[zone_name].update(user_input)     # mutates entry.options in-place!
```

Since the inner zone dicts were shared references with `entry.options`, the `.update()` call modified `entry.options` in-place. Then `async_update_entry()` compared old vs new options, found them equal (because of the in-place mutation), and **skipped the save to .storage**.

**Fix:** Deep copy inner zone dicts so mutations don't affect the original:
```python
zones = {k: dict(v) for k, v in merged.get("zones", {}).items()}
```

### Affected Paths (all 4 fixed)
1. `async_step_zone_hvac` — setting zone thermostat
2. `async_step_zone_rooms` — editing zone name/rooms/description
3. `async_step_zone_media` — setting zone media player
4. `async_step_climate` — auto-populating zone thermostat from room climate entity

## Modified Files
- `config_flow.py` — 4 shallow copy → deep copy fixes (lines ~631, ~3019, ~3136, ~3720)
- `const.py` — version bump to 3.8.2
