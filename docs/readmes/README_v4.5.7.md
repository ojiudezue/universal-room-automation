# v4.5.7 — Solar banking now fires during away/vacation

**Date:** 2026-05-09
**Type:** Tier 1 hotfix (~30 LoC structural change + 16 regression tests)
**Predecessor:** v4.5.6
**Reproducer:** Live diagnostic 2026-05-09 noon CDT. House state `away`, battery 58% charging at 14 kW, ~96.8 kWh of solar still forecast for the day. Solar banking would have been a strong candidate later in the afternoon once battery hit 95%, but the code was structurally blocked from firing during away/vacation.

## Summary

The `_check_pre_conditioning` function in `domain_coordinators/hvac_predict.py` had an unconditional `if house_state in ("away", "vacation"): return` at the top, blocking ALL pre-conditioning paths (weather pre-cool, solar banking, pre-arrival, pre-heat) when nobody was home. The early-return was added at some point as a "safety guard" but **silently broke solar banking's documented design intent** — line 346 explicitly comments *"Bank ALL zones including away — energy has nowhere better to go."*

The economic value of solar banking is precisely *because* the house is empty: surplus PV that can't go to the battery (already full) and has no comfort cost in over-cooling an unoccupied building should be stored as thermal mass instead of exported to the grid at the off-peak rate.

v4.5.7 replaces the unconditional early-return with per-feature gating. **Solar banking now runs regardless of house state.** Weather pre-cool, pre-arrival, and pre-heat (all occupant-comfort driven) keep their away-skip.

## Root cause

`hvac_predict.py:_check_pre_conditioning` pre-v4.5.7:

```python
async def _check_pre_conditioning(self, ..., house_state, ...):
    ...
    # Reset tracking sets each cycle
    self._pre_conditioning_zones = set()
    self._solar_banking_zones = set()
    ...

    # Skip if away/vacation
    if house_state in ("away", "vacation"):     # ← blocks EVERYTHING
        return

    # --- Weather pre-cool ---
    ...
    # --- Solar banking ---
    if self._should_solar_bank(constraint, now):
        for zone_id, zone in self._zone_manager.zones.items():
            # Bank ALL zones including away — energy has nowhere better to go
            await self._execute_zone_pre_cool(...)         # ← unreachable when away
    # --- Pre-arrival, pre-heat ---
    ...
```

The early-return on line 321 contradicted the comment on line 346. Three months of high-SOC away days have all been exporting surplus PV to grid at ~$0.043/kWh instead of dumping it into thermal mass.

This is a sibling shape of Bug Class #33 (partial fix / sibling helper skipped) — the design intent existed in code (the comment, the function name "Bank ALL zones including away," the threshold constants tuned for the away case), but a downstream change blocked the actual execution path.

## Fix

Restructured `_check_pre_conditioning` to gate per-feature instead of one unconditional early-return:

```python
async def _check_pre_conditioning(self, ..., house_state, ...):
    ...
    is_unoccupied = house_state in ("away", "vacation")
    self._pre_conditioning_zones = set()
    self._solar_banking_zones = set()
    ...

    # --- Weather pre-cool (occupant-comfort driven; skip when away) ---
    if not is_unoccupied and self._should_weather_pre_cool(constraint, now):
        for zone_id, zone in self._zone_manager.zones.items():
            if zone.any_room_occupied:
                await self._execute_zone_pre_cool(zone, offset=-2.0, reason="weather")
                ...

    # End pre-cool when peak starts (run regardless of house_state so the
    # _pre_cool_active flag clears even if the user came home mid-event)
    if self._pre_cool_active and hour >= PEAK_HOUR_START:
        ...

    # --- ZI-only features below (guarded by toggle) ---
    if not zone_intelligence_enabled:
        return

    # --- Solar banking (economics-driven — runs regardless of house_state) ---
    # Bank ALL zones including away/vacation — energy has nowhere better to
    # go (battery already ≥95% full, grid export is the only alternative).
    if self._should_solar_bank(constraint, now):
        for zone_id, zone in self._zone_manager.zones.items():
            await self._execute_zone_pre_cool(zone, offset=SOLAR_BANK_OFFSET, reason="solar_banking")
            ...

    # --- Pre-arrival (skip during away/vacation; defensive) ---
    if not is_unoccupied:
        for zone_id, zone in self._zone_manager.zones.items():
            if zone_id in pre_arrival_zones:
                ...

    # --- Pre-heat (winter; occupant-comfort driven) ---
    if not is_unoccupied:
        outdoor_temp = self._get_outdoor_temp()
        if (... season == SEASON_WINTER ...):
            ...

    # End pre-heat (run regardless of house_state)
    if self._pre_heat_active and hour >= OFF_PEAK_END_HOUR:
        ...
```

Note the two end-flag clears (pre-cool ended, pre-heat ended) now run regardless of `house_state` — they're state-machine cleanups that should always converge, not occupant-driven actions.

## Behavioral matrix (tilt-style summary)

| Pre-conditioning feature | Pre-v4.5.7 (away) | Post-v4.5.7 (away) |
|---|---|---|
| Weather pre-cool | skip | skip ✓ (unchanged) |
| Solar banking | **silently skipped (bug)** | **runs ✓ (intent restored)** |
| Pre-arrival | skip | skip ✓ (unchanged, defensive) |
| Pre-heat | skip | skip ✓ (unchanged) |
| `_pre_cool_active` flag clear at peak | skipped | runs ✓ (state-machine hygiene) |
| `_pre_heat_active` flag clear at off-peak end | skipped | runs ✓ (state-machine hygiene) |

When house is occupied (home_day, sleep, guest, arriving, etc.): no behavior change. Every feature still fires per its existing per-feature triggers.

## Solar banking eligibility recap

For reference, solar banking still requires ALL of (`hvac_predict.py:_should_solar_bank`):
- Season is `summer` or `shoulder`
- Battery SOC ≥ 95% (`SOLAR_BANK_SOC_MIN`)
- Real-time net export > 500 W (battery is full, surplus has nowhere to go)
- Forecast high ≥ 85°F (`SOLAR_BANK_TEMP_MIN`)
- `constraint.mode == "normal"` (no other constraint active)
- Hour 10–13 local (before TOU peak)

When triggered, lowers `target_temp_high` by 3°F (`SOLAR_BANK_OFFSET`), with absolute floor at 72°F (`SOLAR_BANK_FLOOR`) and Ecobee 2°F deadband enforcement. Bypasses the override arrester so it overrides "manual" preset.

## Tier 1 Review

| Severity | Finding | Resolution |
|---|---|---|
| (no CRITICAL) | — | — |
| HIGH | Solar banking design intent silently disabled by an unconditional early-return — three months of away days exporting surplus PV to grid instead of banking thermal mass | Fixed: per-feature gating |
| MEDIUM | The two state-machine flag-clear branches (`_pre_cool_active` end, `_pre_heat_active` end) were also skipped during away — could leave stale flags if user came home mid-event | Fixed: flag-clear branches now run regardless of house_state |
| LOW | The line 346 comment ("Bank ALL zones including away — energy has nowhere better to go") was correct intent but unreachable; replaced with v4.5.7-anchored explanatory block | Documentation |

**Verdict: READY TO DEPLOY.**

## Tests

16 new tests in `quality/tests/test_v457_solar_banking_away.py`:

- **Solar banking gating (5):** fires during `away`, fires during `vacation`, fires during `home_day` (regression), blocked when `zone_intelligence_enabled=False`, skipped when `_should_solar_bank` returns False.
- **Other features keep away-skip (6):** weather pre-cool skipped during away/fires when home, pre-arrival skipped during away/fires when home, pre-heat skipped during vacation/fires when home.
- **Source contract (5):** unconditional away early-return is gone; solar-banking branch does NOT gate on `is_unoccupied`; weather pre-cool / pre-arrival / pre-heat blocks DO gate on `is_unoccupied`.

**Test count progression:**
- v4.5.6: 1978 tests, 0 isolated failures across 54 files
- **v4.5.7: 1994** (+16), 0 isolated failures across 55 files

## Live validation (post-restart)

Live signal will only fire when conditions converge — battery ≥ 95%, surplus solar, hour 10–13 local, summer/shoulder, away/vacation. On a sunny day with the house empty:

1. Around the time SOC crosses 95% (typically 12:30–14:00 local on excellent solar days), watch:
   - HVAC coordinator status sensor's `solar_banking_zones` attribute populates with zone IDs
   - URA log shows `HVAC: Zone N pre-cool (solar_banking): X.X -> Y.Y (offset=-3.0, floor=72.0)`
   - `climate.<zone>` `target_temp_high` drops by up to 3°F per zone (floored at 72°F)
2. Confirm the cooling drives net export back toward zero (you can see this on the Envoy net-power sensor).
3. After hour 14 (peak start), banking ends; `_pre_cool_active` clears; setpoints stay where banking left them until the next preset change or schedule.

If the user comes home mid-banking, occupancy detection re-triggers normal preset evaluation; banking stops at the next `_check_pre_conditioning` cycle (no explicit cancel — the banking offsets remain on the thermostat until next preset push).

## Deploy notes

- No DB schema changes
- No migration needed
- HACS download required after deploy.sh
- HA restart required (hvac_predict.py is in the loaded integration package)

## Next

- **v4.6.0** — Routine Awareness with reconciled AnomalyEvent foundation
- **Sensor Health Surfacing** (backlog) — chattering + stuck-on detection
- **CM cleanup cycle** — `CONF_MUSIC_FOLLOWING_ENABLED` + `CONF_COMFORT_ENABLED` + unused `"comfort"` slot
