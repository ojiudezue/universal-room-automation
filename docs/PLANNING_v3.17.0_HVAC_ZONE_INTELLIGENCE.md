# PLANNING v3.17.0 — HVAC Zone Intelligence

**Version:** v3.17.0
**Date:** 2026-03-19
**Status:** Planning (post-critique, revision 2)
**Parent plans:** HVAC_COORDINATOR_DESIGN.md, HA_AUTOMATION_LEARNINGS.md
**Estimated effort:** 7 deliverables, ~25 hours total
**Priority:** HIGH — energy savings + design gap closure

---

## OVERVIEW

The HVAC coordinator treats all zones identically. An unoccupied zone runs the same preset as an occupied one. Pre-conditioning is house-wide — it either pre-cools all occupied zones or none. There's no mechanism to:
- Switch individual zones to `away` when empty
- Sweep off lights/fans in vacant zones to reclaim wasted energy
- Pre-cool a specific zone because a specific person is arriving
- Bank thermal mass using excess solar before peak pricing
- Limit HVAC runtime during peak load shedding

This plan makes HVAC zone-aware, person-aware, and solar-aware.

**Core principles:**
1. An unoccupied zone should go to `away` preset — saving energy is good policy regardless of constraint state. Constraints make it happen faster.
2. An `away` zone should still be pre-coolable when we have excess solar (bank free energy as thermal mass) or when we detect a specific person approaching (pre-arrival).
3. Pre-conditioning should be zone-specific, not house-wide. Person-to-zone mapping enables targeted pre-arrival.
4. Vacancy should sweep off URA-configured lights and fans — preset change alone doesn't reclaim room-level waste.

---

## WHAT ALREADY EXISTS (Do Not Rebuild)

| Component | Status | Location |
|-----------|--------|----------|
| `ZoneState.any_room_occupied` | Computed every cycle | `hvac_zones.py:71-73` |
| `ZoneState.room_conditions` | Aggregated from room coordinators | `hvac_zones.py:257-294` |
| `EnergyConstraint` signal | Received by HVAC (mode, solar_class, soc, forecast) | `hvac.py:459-474`, `signals.py:38-50` |
| `HVACZoneStatusSensor` + `HVACZonePresetSensor` | Per-zone sensors with occupancy/preset attrs | `sensor.py:6368-6425, 6836-6911` |
| Pre-cool/pre-heat in predictor | House-wide, skips empty zones | `hvac_predict.py:286-395` |
| `climate.set_preset_mode` service call | In `_apply_house_state_presets` | `hvac.py:376-383` |
| Geofence arrival detection | Fires on `person.*` state → "home" | `presence.py:982-999` |
| Person location tracking (BLE) | PersonCoordinator tracks per-person room | `person_coordinator.py:107-300` |
| `get_zone_occupants(zone_rooms)` | Query persons in a zone | `person_coordinator.py:989` |
| Excess solar detection | SOC ≥ threshold + remaining forecast ≥ kWh | `energy.py:1370-1376`, `energy_pool.py:256-348` |
| Room automation fan/light control | Per-room fans and lights via config | `automation.py:928-999` (fans), `automation.py:261-347` (lights) |
| Room sleep mode gating | Blocks entry/exit automation, covers during sleep | `automation.py:224-290` |
| HVAC FanController | Zone-level fan hysteresis + humidity | `hvac_fans.py` |
| Override Arrester suppress pattern | Used by pre-conditioning | `hvac_override.py` |

---

## DELIVERABLES

| # | Deliverable | Scope | Effort |
|---|-------------|-------|--------|
| D1 | Zone vacancy management | Away preset + vacancy sweep (lights/fans off) + zone override toggle | ~5 hrs |
| D2 | Zone-specific pre-conditioning | Solar banking + pre-arrival pre-cool + arrival fans | ~6 hrs |
| D3 | Person-to-zone mapping | Config + geofence routing + BLE arrival detection per zone | ~4 hrs |
| D4 | Zone presence state machine | 7-state per-zone sensor with full diagnostic attributes | ~3 hrs |
| D5 | HVAC duty cycle enforcement | Rolling 20-min window runtime limits during peak | ~3 hrs |
| D6 | Max-occupancy-duration failsafe | Stale occupancy guard for stuck sensors | ~2 hrs |
| D7 | Diagnostic sensors | Zone intelligence tracking sensors for URA device | ~2 hrs |

---

## D1: Zone Vacancy Management

### Problem

When a zone becomes unoccupied, the HVAC preset stays on `home`. Lights and fans configured in URA rooms within that zone continue running. The only way to reclaim this energy today is manual intervention or waiting for individual room exit timers.

### Design

**Three actions on zone vacancy (after grace period):**

1. **HVAC preset → `away`**: Relaxes setpoints (e.g., 77°F → 82°F cooling, 72°F → 60°F heating)
2. **Zone sweep — lights off**: Turn off all URA-configured light entities in zone rooms
3. **Zone sweep — fans off**: Turn off all URA-configured fan entities in zone rooms

**Two-tier grace period:**

| Condition | Grace Period | Rationale |
|-----------|-------------|-----------|
| Normal (no energy constraint) | 15 min | Brief absences (bathroom, kitchen trip) |
| Energy constrained (coast/shed) | 5 min | Peak TOU / load shedding — save fast |

**Zone sweep scope:** Only entities explicitly configured in URA room entries (`CONF_LIGHT_ENTITIES`, `CONF_FANS`, `CONF_SWITCHES`). NOT a blanket entity search. This prevents turning off non-URA devices (e.g., always-on night lights, security cameras on smart plugs).

**Override toggle per zone:** New boolean on Zone Manager zone config: `CONF_ZONE_VACANCY_SWEEP_ENABLED` (default: True). Some zones (e.g., utility zones with always-on equipment) should opt out.

### Implementation

**New fields on ZoneState** (`hvac_zones.py`):
```python
last_occupied_time: datetime | None = None  # UTC, when zone last had occupancy
vacancy_sweep_done: bool = False  # Tracks if sweep already executed this vacancy
vacancy_sweep_enabled: bool = True  # Per-zone config override
```

**Timestamp tracking** (in `update_room_conditions()`):
```python
# Use dt_util.utcnow() consistently (RC2 fix from review cycle)
if zone.any_room_occupied:
    zone.last_occupied_time = dt_util.utcnow()
    zone.vacancy_sweep_done = False  # Reset sweep flag on re-occupation
```

**Initialize never-occupied zones** (in `async_discover_zones()`, RM1 fix):
```python
# Zones empty at startup should be immediately eligible for vacancy override
zone.last_occupied_time = dt_util.utcnow() - timedelta(minutes=grace + 1)
```

**Modified `_apply_house_state_presets()`** (`hvac.py`):
```python
async def _apply_house_state_presets(self) -> None:
    if not self._house_state:
        return

    target_preset = self._preset_manager.get_preset_for_house_state(self._house_state)
    if target_preset is None:
        return

    now = dt_util.utcnow()  # Standardize on UTC (RC2 fix)
    energy_constrained = self._energy_constraint_mode in ("coast", "shed")
    grace_minutes = (
        self._vacancy_grace_constrained if energy_constrained
        else self._vacancy_grace
    )

    for zone_id, zone in self._zone_manager.zones.items():
        effective_preset = target_preset

        # Per-zone vacancy override: empty zone → away preset
        # Only override "home" preset — sleep/away/vacation are already correct
        # Also override "manual" for vacant zones (RH3 fix — user left the room)
        zone_vacant_past_grace = (
            not zone.any_room_occupied
            and zone.last_occupied_time is not None
            and (now - zone.last_occupied_time).total_seconds() > grace_minutes * 60
        )

        if zone_vacant_past_grace and target_preset in ("home",):
            effective_preset = "away"

            # Zone sweep: turn off lights + fans (once per vacancy cycle)
            if not zone.vacancy_sweep_done and zone.vacancy_sweep_enabled:
                await self._execute_vacancy_sweep(zone)
                zone.vacancy_sweep_done = True

        # Skip if no change needed
        # Bypass should_change_preset() manual guard for vacancy (RH3 fix)
        if zone_vacant_past_grace and effective_preset == "away":
            if zone.preset_mode == "away":
                continue  # Already away
        elif not self._preset_manager.should_change_preset(
            zone.preset_mode, effective_preset
        ):
            continue

        # Suppress arrester for URA-initiated changes
        if self._override_arrester:
            self._override_arrester.suppress(zone.climate_entity)

        try:
            await self.hass.services.async_call(
                "climate", "set_preset_mode",
                {"entity_id": zone.climate_entity, "preset_mode": effective_preset},
                blocking=False,
            )
        except Exception as e:
            _LOGGER.error("HVAC: Failed to set preset on %s: %s", zone.climate_entity, e)
```

**Vacancy sweep method** (`hvac.py`):
```python
async def _execute_vacancy_sweep(self, zone: ZoneState) -> None:
    """Turn off URA-configured lights and fans in all rooms of a vacant zone."""
    for room_name in zone.rooms:
        coordinator = self._get_room_coordinator(room_name)
        if coordinator is None:
            continue
        config = {**coordinator.config_entry.data, **coordinator.config_entry.options}

        # Collect URA-configured entities only
        lights = config.get(CONF_LIGHT_ENTITIES, [])
        fans = config.get(CONF_FANS, [])
        switches = config.get(CONF_SWITCHES, [])  # Switches used as lights/fans

        for entity_id in lights + switches:
            domain = entity_id.split(".")[0]
            state = self.hass.states.get(entity_id)
            if state and state.state == STATE_ON:
                try:
                    await self.hass.services.async_call(
                        domain, "turn_off",
                        {"entity_id": entity_id}, blocking=False,
                    )
                except Exception:
                    pass  # Best effort

        for entity_id in fans:
            domain = entity_id.split(".")[0]
            state = self.hass.states.get(entity_id)
            if state and state.state == STATE_ON:
                try:
                    await self.hass.services.async_call(
                        domain, "turn_off",
                        {"entity_id": entity_id}, blocking=False,
                    )
                except Exception:
                    pass

    _LOGGER.info(
        "HVAC: Vacancy sweep executed for zone %s — lights and fans off",
        zone.zone_name,
    )
```

**Config flow** — Zone Manager zone options:
```python
CONF_ZONE_VACANCY_SWEEP_ENABLED: Final = "zone_vacancy_sweep_enabled"
# Added to zone options step alongside CONF_ZONE_THERMOSTAT, CONF_ZONE_ROOMS
```

### Edge Cases

1. **House state SLEEP**: `target_preset` is `sleep` (not `home`) → vacancy override skipped. Sleep zones keep `sleep` preset. Correct — people sleeping shouldn't have their zone go to `away`.
2. **House state AWAY**: House-level `away` preset already correct → no zone override needed.
3. **Person returns to zone**: Next cycle sees `any_room_occupied=True`, `vacancy_sweep_done` resets, zone preset returns to `home`. Room entry automation re-triggers lights.
4. **Zone sweep vs. room exit timer**: Room coordinator has its own exit timer (lights off after N minutes of vacancy). Zone sweep is a backstop — if room exit timer already turned lights off, sweep is a no-op (entities already off).
5. **Manual preset override for vacant zone**: Bypasses `should_change_preset()` manual guard per RH3 fix — user has left the room, manual preference is no longer relevant.
6. **Zone with `vacancy_sweep_enabled=False`**: HVAC preset still changes to `away`. Only sweep (lights/fans off) is disabled. Energy saving from relaxed setpoints still applies.

### Tests (~10)

- Zone unoccupied 16 min (normal) → away + sweep
- Zone unoccupied 6 min (constrained) → away + sweep
- Zone unoccupied 10 min (normal) → no change (within grace)
- Zone re-occupied → home preset restored, sweep flag reset
- House SLEEP → no vacancy override
- House AWAY → house-level away passthrough
- Zone with sweep disabled → away preset but no light/fan off
- Manual preset + vacant → override to away anyway
- Never-occupied zone at startup → immediately eligible
- Sweep only turns off URA-configured entities (not all entities in area)

---

## D2: Zone-Specific Pre-Conditioning

### Problem

Pre-conditioning is currently house-wide: if conditions are met, ALL occupied zones get pre-cooled by 2°F. There's no way to:
- Pre-cool a specific zone for a specific arriving person
- Bank thermal mass using truly excess solar (last resort before grid export)
- Turn on zone fans as a comfort bridge while AC catches up on arrival

### Design

**Three pre-conditioning triggers, each zone-specific:**

| Trigger | Condition | Zones Affected | Offset |
|---------|-----------|----------------|--------|
| **Weather pre-cool** (existing) | Forecast ≥90°F + peak approaching + SOC ≥30% | Occupied zones only (current behavior) | -2°F from `target_temp_high` |
| **Solar banking** (new) | Truly excess: battery full + net-exporting + hot forecast + not peak | ALL zones including away | -3°F from `target_temp_high` (floored) |
| **Pre-arrival** (new) | Geofence "home" + person-to-zone mapping | Target person's preferred zone(s) only | -2°F from `target_temp_high` + fans on |

### Solar Banking Economics

**PEC 2026 TOU energy rates are symmetric** ($0.162 peak, $0.093 mid, $0.043 off) but that does NOT mean peak export has no value. The arbitrage is in the **time-shift**:

| Action | Effective $/kWh | Why |
|--------|----------------|-----|
| Import at off-peak | ~$0.086 | $0.043 energy + $0.023 delivery + $0.020 transmission |
| Import at peak | ~$0.204 | $0.162 energy + $0.023 delivery + $0.020 transmission |
| Export at peak | +$0.162 credit | Energy rate credit (delivery/transmission TBD) |
| Battery: off-peak charge → peak discharge | ~$0.118 net/kWh | Avoids $0.204 peak import, costs $0.086 off-peak import |

**Optimal strategy:** Import cheap off-peak ($0.086) → solar powers house during day → export surplus at peak ($0.162 credit). Battery amplifies this: charge off-peak/solar → discharge during peak to avoid $0.204/kWh imports. Every kWh exported at peak or displaced from peak import is worth 2-4× an off-peak kWh.

**Thermal banking is lossy.** 1 kWh of solar AC during off-peak displaces ~0.7 kWh of peak AC consumption (insulation losses, thermal mass decay). Value: ~$0.143 of avoided peak import, but displaces $0.043 of off-peak export = ~$0.100/kWh net. Battery storage (~$0.118/kWh net, 90% round-trip) beats this.

**Two distinct cascades — don't conflate them:**

*Excess solar ABSORPTION cascade* (what to do with surplus energy when battery is full):
1. **Battery charging** — highest ROI, 1:1 peak displacement. ~$0.118 net/kWh.
2. **EV charging** — displaces gas or future grid charging. Already implemented.
3. **Thermal banking** — lossy but captures otherwise-wasted solar. ~$0.100 net/kWh.
4. **Grid export** — default fallback. $0.043-0.162/kWh depending on TOU period.

*Load SHEDDING cascade* (reduce consumption during peak/constraint — separate concern):
1. Pool VSF speed reduction (94% power savings)
2. EV charger pause
3. Smart plugs pause
4. HVAC coast/shed

Pool is a load shedding strategy (reduce consumption), NOT an energy absorption strategy (it doesn't store anything). It belongs only in the shedding cascade.

**Solar banking is LAST resort before grid export in the absorption cascade.** It should only trigger when battery is full AND EV is charged/charging AND we're still net-exporting. The user's guidance: **grid export wins over banking unless energy has literally nowhere better to go.** Inhabitants can take their chances with an initially hot house.

**Trigger conditions (all must be true):**
- Battery nearly full: SOC ≥ 95% (battery has nowhere to put energy)
- Net-exporting right now: `net_power < 0` (home consumption + battery charging already met)
- Hot forecast: `forecast_high ≥ 85°F` (banking matters for comfort/energy)
- Not peak/mid-peak: `tou_period == "off_peak"` (don't consume during expensive hours)
- Summer/shoulder season only
- Not already triggered today

This ensures banking ONLY happens when we're literally dumping energy to grid with nothing better to do, AND it's going to be hot enough that the thermal mass actually helps.

### Offset Mechanics

**The offset applies to `target_temp_high`** (the cooling setpoint in heat_cool mode):

```
Preset: target_temp_low=70, target_temp_high=76 (heat at 70, cool at 76)
Banking offset: -3°F → new target_temp_high = 76 - 3 = 73°F
Floor: 72°F → 73°F > 72°F → use 73°F ✓
Deadband: 73 - 70 = 3°F ≥ MIN_DEADBAND (2°F) → OK ✓

Preset: target_temp_low=71, target_temp_high=74 (tight band)
Banking offset: -3°F → new target_temp_high = 74 - 3 = 71°F
Floor: 72°F → 71°F < 72°F → clamp to 72°F
Deadband: 72 - 71 = 1°F < MIN_DEADBAND (2°F) → clamp to 71 + 2 = 73°F
Final target_temp_high: 73°F (effective offset: only -1°F)
```

**Floor formula:**
```python
MIN_DEADBAND = 2.0  # °F, Ecobee minimum in auto mode
SOLAR_BANK_FLOOR = 72.0  # Absolute minimum cooling setpoint

banked_high = zone.target_temp_high + offset  # offset is negative
floor = max(SOLAR_BANK_FLOOR, zone.target_temp_low + MIN_DEADBAND)
effective_high = max(banked_high, floor)
```

The same floor logic applies to weather pre-cool and pre-arrival offsets.

### Implementation

**Refactor `_check_pre_conditioning()`** to be zone-aware (`hvac_predict.py`):

```python
async def _check_pre_conditioning(
    self,
    constraint: EnergyConstraint | None,
    house_state: str,
    now,
) -> None:
    """Zone-specific pre-conditioning: weather, solar banking, pre-arrival."""

    # Track which zones are being pre-conditioned (for D4 state machine)
    self._pre_conditioning_zones: set[str] = set()
    self._solar_banking_zones: set[str] = set()

    # --- Weather pre-cool (existing, zone-specific) ---
    if self._should_weather_pre_cool(constraint, now):
        for zone_id, zone in self._zone_manager.zones.items():
            if zone.any_room_occupied:
                await self._execute_zone_pre_cool(zone, offset=-2.0, reason="weather")
                self._pre_conditioning_zones.add(zone_id)

    # --- Solar banking (new, lowest priority — truly excess only) ---
    if self._should_solar_bank(constraint, now):
        for zone_id, zone in self._zone_manager.zones.items():
            # Bank ALL zones including away — energy has nowhere better to go
            await self._execute_zone_pre_cool(zone, offset=-3.0, reason="solar_banking")
            self._pre_conditioning_zones.add(zone_id)
            self._solar_banking_zones.add(zone_id)

    # --- Pre-arrival (new, person-routed) ---
    for zone_id, zone in self._zone_manager.zones.items():
        if zone_id in self._pre_arrival_zones:
            await self._execute_zone_pre_cool(zone, offset=-2.0, reason="pre_arrival")
            # Fans as comfort bridge (skip during sleep — Critique 5 fix)
            if house_state != "sleep":
                await self._activate_zone_fans(zone)
            self._pre_conditioning_zones.add(zone_id)
```

**Solar banking trigger — truly excess only:**
```python
def _should_solar_bank(self, constraint: EnergyConstraint | None, now) -> bool:
    """Bank thermal mass ONLY when solar is truly excess.

    Priority: battery charging > EV > pool > thermal banking > grid export.
    Banking is last resort before grid export. All higher-priority loads
    must be saturated first.
    """
    if constraint is None:
        return False

    season = self._preset_manager.current_season
    if season not in (SEASON_SUMMER, SEASON_SHOULDER):
        return False

    soc = constraint.soc or 0
    forecast_high = constraint.forecast_high_temp or 0

    # Check real-time net export from Energy Coordinator
    net_power = self._get_net_power()  # Watts, negative = exporting

    return (
        not self._solar_bank_triggered_today
        and soc >= SOLAR_BANK_SOC_MIN          # 95% — battery is full
        and net_power < -500                    # Actively exporting >500W to grid
        and forecast_high >= SOLAR_BANK_TEMP_MIN  # 85°F — hot enough to matter
        and constraint.mode == "normal"         # Off-peak only, no constraint active
        and now.hour >= 10                      # Late morning (solar producing)
        and now.hour < 14                       # Before peak starts (summer peak=14-19)
    )

def _get_net_power(self) -> float:
    """Read real-time net power from Envoy sensor. Negative = exporting."""
    entity = self.hass.states.get(self._net_power_entity)
    if entity is None or entity.state in ("unavailable", "unknown"):
        return 0.0
    try:
        return float(entity.state)
    except (ValueError, TypeError):
        return 0.0
```

**Zone pre-cool with floor protection** (`hvac_predict.py`):
```python
async def _execute_zone_pre_cool(
    self, zone: ZoneState, offset: float, reason: str
) -> None:
    """Pre-cool a single zone with offset from target_temp_high.

    Applies floor: never go below SOLAR_BANK_FLOOR or within MIN_DEADBAND
    of target_temp_low (Ecobee requires ≥2°F deadband in auto mode).
    """
    if zone.target_temp_high is None or zone.target_temp_low is None:
        return

    banked_high = zone.target_temp_high + offset  # offset is negative
    floor = max(SOLAR_BANK_FLOOR, zone.target_temp_low + MIN_DEADBAND)
    effective_high = max(banked_high, floor)

    if effective_high >= zone.target_temp_high:
        return  # Floor prevents any meaningful change

    # Suppress arrester
    if self._override_arrester:
        self._override_arrester.suppress(zone.climate_entity)

    try:
        await self.hass.services.async_call(
            "climate", "set_temperature",
            {
                "entity_id": zone.climate_entity,
                "target_temp_high": effective_high,
                "target_temp_low": zone.target_temp_low,  # Unchanged
            },
            blocking=False,
        )
        _LOGGER.info(
            "HVAC: Zone %s pre-cool (%s): %.1f -> %.1f (offset=%.1f, floor=%.1f)",
            zone.zone_name, reason,
            zone.target_temp_high, effective_high, offset, floor,
        )
    except Exception as e:
        _LOGGER.error("HVAC: Failed to pre-cool %s: %s", zone.climate_entity, e)
```

**Constants:**
```python
SOLAR_BANK_SOC_MIN = 95        # Battery must be effectively full
SOLAR_BANK_TEMP_MIN = 85.0     # °F — forecast must be hot enough to matter
SOLAR_BANK_OFFSET = -3.0       # °F from target_temp_high
SOLAR_BANK_FLOOR = 72.0        # °F — absolute minimum cooling setpoint
MIN_DEADBAND = 2.0             # °F — Ecobee auto mode minimum
PRE_ARRIVAL_FAN_TIMEOUT = 15   # Minutes before auto-off
```

**Pre-arrival fan activation** (`hvac_predict.py`):
```python
async def _activate_zone_fans(self, zone: ZoneState) -> None:
    """Turn on zone fans for comfort bridge during pre-arrival.

    Fans provide immediate perceived cooling via wind chill while AC ramps.
    """
    for room_name in zone.rooms:
        coordinator = self._get_room_coordinator(room_name)
        if coordinator is None:
            continue
        config = {**coordinator.config_entry.data, **coordinator.config_entry.options}
        fans = config.get(CONF_FANS, [])
        for fan_entity in fans:
            domain = fan_entity.split(".")[0]
            state = self.hass.states.get(fan_entity)
            if state and state.state != STATE_ON:
                try:
                    await self.hass.services.async_call(
                        domain, "turn_on",
                        {"entity_id": fan_entity}, blocking=False,
                    )
                except Exception:
                    pass
    _LOGGER.info("HVAC: Pre-arrival fans activated for zone %s", zone.zone_name)
```

### Edge Cases

1. **Solar banking + already pre-cooled by weather**: If both trigger simultaneously, the larger offset wins. `_execute_zone_pre_cool` checks if `effective_high >= zone.target_temp_high` — if weather already lowered it, banking is a no-op unless its offset exceeds the weather offset.
2. **Solar banking while EV is charging**: Correct — EV charging is higher priority in the excess solar cascade. If EV is consuming the excess, `net_power` stays positive (importing) → banking doesn't trigger. Banking only fires when we're net-exporting despite EV + pool + battery.
3. **Solar banking on an away zone at 82°F**: Banking offset: 82 - 3 = 79°F. Floor: max(72, heat_setpoint + 2). If away heat setpoint is 60°F, floor = 72°F. 79°F > 72°F → cools to 79°F. Meaningful — zone is 3°F cooler when person arrives.
4. **Tight heat_cool band (71-74)**: Banking: 74 - 3 = 71°F. Floor: max(72, 71+2) = 73°F. Effective offset: only -1°F. Small but still worth it with free energy.
5. **Pre-arrival + solar banking**: Compatible. Pre-arrival adds fans; banking adds more aggressive offset. Both benefit the arriving person. Use the larger offset.
6. **Nobody arrives after pre-arrival**: Fans auto-off after 15 min. Pre-cooled zone gradually returns to away setpoint. The banked energy was free (net-exporting anyway), so waste is minimal.
7. **Net power sensor unavailable**: `_get_net_power()` returns 0 → banking doesn't trigger. Safe fallback.

### Tests (~10)

- Weather pre-cool: occupied zones cooled, empty zones skipped
- Solar banking: only triggers when SOC ≥ 95% + net-exporting >500W + forecast ≥ 85°F
- Solar banking: does NOT trigger when SOC is 90% (battery should keep charging)
- Solar banking: does NOT trigger during peak/coast/shed
- Solar banking: offset floored at max(72, target_temp_low + 2)
- Solar banking on away zone (82°F) → cools to 79°F
- Solar banking on tight band (71-74) → clamped to 73°F
- Pre-arrival: only target zone pre-cooled, fans activated
- Pre-arrival fans: auto-off after 15 min; skipped during sleep
- `_solar_bank_triggered_today` prevents re-triggering

---

## D3: Person-to-Zone Mapping

### Problem

Pre-arrival is useless without knowing WHICH zone to target. Today, geofence fires a house-level `ARRIVING` state — all zones are treated equally. The HA automations have hardcoded per-zone presence logic, but URA needs a configurable mapping.

### Design

**Two-layer person-to-zone routing:**

1. **Config layer** (explicit): `CONF_PERSON_PREFERRED_ZONES` — dict mapping person entity → list of zone IDs. Set in Coordinator Manager config flow. Example: `{"person.john": ["zone_1", "zone_3"], "person.jane": ["zone_2"]}`.

2. **Learning layer** (future, deferred): Track which zone each person enters first after geofence arrival. Build historical affinity. Not in v3.17.0 — config-based mapping is sufficient and deterministic.

**Geofence → zone routing flow:**

```
person.john geofence → "home"
    ↓
PresenceCoordinator._handle_geofence_change()
    ↓
New: async_dispatcher_send(SIGNAL_PERSON_ARRIVING, {"person": "person.john"})
    ↓
HVACCoordinator._handle_person_arriving()
    ↓
Lookup: person.john → preferred zones ["zone_1", "zone_3"]
    ↓
Mark: self._pre_arrival_zones = {"zone_1", "zone_3"}
    ↓
Next decision cycle: D2 pre-conditions those zones + activates fans
```

**BLE confirmation clears pre-arrival:**

```
PersonCoordinator detects john in "master_bedroom" (zone_1)
    ↓
ZoneState.any_room_occupied → True
    ↓
Zone transitions: pre_arrival → occupied
    ↓
Pre-arrival fans auto-off (zone now occupied, normal fan logic takes over)
```

### Implementation

**New signal** (`signals.py`):
```python
SIGNAL_PERSON_ARRIVING: Final = "ura_person_arriving"
# Payload: {"person_entity": "person.john", "source": "geofence"}
```

**Dispatch from PresenceCoordinator** (`presence.py`, in `_handle_geofence_change()`):
```python
# After existing geofence processing (line ~999)
if new_zone == "home" and old_zone != "home":
    async_dispatcher_send(
        self.hass,
        SIGNAL_PERSON_ARRIVING,
        {"person_entity": entity_id, "source": "geofence"},
    )
```

**HVAC handler** (`hvac.py`):
```python
@callback
def _handle_person_arriving(self, data: dict) -> None:
    """Route arriving person to preferred zones for pre-conditioning."""
    person_entity = data.get("person_entity", "")
    preferred_zones = self._person_zone_map.get(person_entity, [])

    if not preferred_zones:
        _LOGGER.debug("HVAC: No preferred zones for %s", person_entity)
        return

    for zone_id in preferred_zones:
        if zone_id in self._zone_manager.zones:
            self._pre_arrival_zones.add(zone_id)
            self._pre_arrival_persons[zone_id] = person_entity

    _LOGGER.info(
        "HVAC: Pre-arrival for %s → zones %s",
        person_entity, preferred_zones,
    )
```

**Pre-arrival timeout** (in `_async_decision_cycle()`):
```python
# Clear stale pre-arrival zones (person didn't show up within 30 min)
PRE_ARRIVAL_TIMEOUT = timedelta(minutes=30)
for zone_id in list(self._pre_arrival_zones):
    if zone_id not in arriving_since:
        arriving_since[zone_id] = now
    elif (now - arriving_since[zone_id]) > PRE_ARRIVAL_TIMEOUT:
        self._pre_arrival_zones.discard(zone_id)
        arriving_since.pop(zone_id, None)
        _LOGGER.info("HVAC: Pre-arrival timeout for zone %s", zone_id)
```

**Config** (`const.py` + `config_flow.py`):
```python
CONF_PERSON_PREFERRED_ZONES: Final = "person_preferred_zones"
# JSON dict in Coordinator Manager options: {"person.john": ["zone_1"], ...}
```

Config flow presents a multi-select per tracked person: for each `person.*` entity in `CONF_TRACKED_PERSONS`, allow selecting one or more HVAC zones.

### Edge Cases

1. **Person not in map**: No pre-arrival — house-level ARRIVING state still triggers, but no zone targeting. Degradation to current behavior.
2. **Person mapped to multiple zones**: All mapped zones get pre-arrival. This is intentional — a person may use the living room AND bedroom.
3. **Two people arriving simultaneously**: Both get their zones pre-conditioned. Zones may overlap — that's fine, pre-cool is idempotent.
4. **Person arrives but goes to unmapped zone**: Pre-arrival was wrong. Fans auto-off after timeout. Minor energy waste from pre-cooling wrong zone, but the cost is low (especially during solar banking when energy is free).
5. **BLE detects person before geofence fires**: BLE detection in a zone triggers `any_room_occupied=True` → zone goes from `away` to `occupied` via D1 logic. No pre-arrival needed — person is already there.

### Tests (~6)

- Geofence arrival → preferred zones marked for pre-arrival
- Person not in map → no zone targeting
- BLE confirms arrival → pre-arrival cleared, zone → occupied
- Pre-arrival timeout (30 min) → pre-arrival cleared
- Two persons arriving → both get zone pre-conditioning
- Config: person mapped to multiple zones → all zones targeted

---

## D4: Zone Presence State Machine

### Problem

Zone behavior is invisible — no sensor shows why a zone is in its current state or what decision the HVAC coordinator made. The HA automations expose a per-zone `input_select` with `occupied/away/pre_arrival/sleep/empty` for debugging and dashboard visibility.

### Design

**7-state machine per zone** (expanded from original 5):

| State | Meaning | Triggers |
|-------|---------|----------|
| `occupied` | At least one room in zone has active occupancy | `any_room_occupied == True` |
| `vacant` | No rooms occupied, within grace period | Vacancy < grace minutes |
| `away` | Grace expired, zone on away preset | Grace elapsed, sweep done |
| `sleep` | House state is SLEEP | House state SLEEP |
| `pre_conditioning` | Weather or solar banking pre-cool active | In `_pre_conditioning_zones` set |
| `pre_arrival` | Person arriving, zone targeted for pre-cool + fans | In `_pre_arrival_zones` set |
| `runtime_limited` | Duty cycle exceeded, zone forced to away | D5 enforcement |

**State priority** (highest wins):
1. `sleep` — absolute override
2. `runtime_limited` — energy protection
3. `pre_arrival` — person approaching
4. `pre_conditioning` — solar/weather banking
5. `occupied` — active use
6. `vacant` — grace period
7. `away` — empty

### Implementation

**New field on ZoneState** (`hvac_zones.py`):
```python
zone_presence_state: str = "unknown"
```

**State computation** (in `_async_decision_cycle()`, after all other logic):
```python
for zone_id, zone in self._zone_manager.zones.items():
    if self._house_state == "sleep":
        zone.zone_presence_state = "sleep"
    elif zone.runtime_exceeded:
        zone.zone_presence_state = "runtime_limited"
    elif zone_id in self._pre_arrival_zones:
        zone.zone_presence_state = "pre_arrival"
    elif zone_id in self._predictor._pre_conditioning_zones:
        zone.zone_presence_state = "pre_conditioning"
    elif zone.any_room_occupied:
        zone.zone_presence_state = "occupied"
    elif (
        zone.last_occupied_time is not None
        and (now - zone.last_occupied_time).total_seconds() <= grace_minutes * 60
    ):
        zone.zone_presence_state = "vacant"
    else:
        zone.zone_presence_state = "away"
```

**Expose on existing `HVACZoneStatusSensor`** (`sensor.py`):
```python
# In get_zone_status_attrs():
attrs["zone_presence_state"] = zone.zone_presence_state
attrs["vacancy_grace_remaining_s"] = max(0, grace_seconds - elapsed) if not occupied else 0
attrs["pre_arrival_person"] = self._pre_arrival_persons.get(zone_id, "")
attrs["solar_banking_active"] = zone_id in self._predictor._solar_banking_zones
```

### Tests (~6)

- All 7 state transitions verified
- Priority ordering: sleep > runtime_limited > pre_arrival > pre_conditioning > occupied > vacant > away
- Grace period countdown in attributes
- Pre-arrival person attribution

---

## D5: HVAC Duty Cycle Enforcement

### Problem

During peak TOU with load shedding, HVAC can run indefinitely. The Energy Coordinator sends `max_runtime_minutes` but it equals the remaining period duration (e.g., peak lasts 4 hours → `max_runtime_minutes=240`) — useless as a budget.

### Design

**Duty cycle model** (rolling 20-min window):

| Constraint Mode | Duty Cycle | Meaning |
|----------------|-----------|---------|
| `normal` | 100% | No limit |
| `coast` | 75% | Max 15 min active per 20-min window |
| `shed` | 50% | Max 10 min active per 20-min window |

Tracked per zone. When a zone exceeds its duty cycle, force to `away` until the window resets.

### Implementation

**New fields on ZoneState** (`hvac_zones.py`):
```python
runtime_seconds_this_window: float = 0.0
window_start: datetime | None = None
runtime_exceeded: bool = False
```

**Runtime accumulation** (new method `_accumulate_zone_runtime()`, called in `_async_decision_cycle()` BEFORE `_apply_house_state_presets()` — RC3 ordering fix):
```python
async def _accumulate_zone_runtime(self, now: datetime) -> None:
    """Track per-zone HVAC active runtime in rolling 20-min window."""
    WINDOW_SECONDS = 20 * 60  # 20 minutes

    for zone_id, zone in self._zone_manager.zones.items():
        # Initialize window
        if zone.window_start is None:
            zone.window_start = now
            zone.runtime_seconds_this_window = 0.0
            zone.runtime_exceeded = False

        # Check window expiry → reset
        if (now - zone.window_start).total_seconds() >= WINDOW_SECONDS:
            zone.window_start = now
            zone.runtime_seconds_this_window = 0.0
            zone.runtime_exceeded = False

        # Accumulate if actively heating/cooling
        if zone.hvac_action in ("heating", "cooling"):
            # Add 5 minutes (one decision cycle interval)
            zone.runtime_seconds_this_window += min(
                300, (now - (zone.window_start or now)).total_seconds()
            )

        # Check duty cycle
        mode = self._energy_constraint_mode
        if mode == "shed":
            max_seconds = WINDOW_SECONDS * 0.50
        elif mode == "coast":
            max_seconds = WINDOW_SECONDS * 0.75
        else:
            continue  # No limit in normal mode

        # Skip enforcement during sleep (RH4 fix)
        if self._house_state == "sleep":
            continue

        if zone.runtime_seconds_this_window >= max_seconds:
            zone.runtime_exceeded = True
```

**Enforcement in `_apply_house_state_presets()`:**
```python
# After vacancy check, before service call:
if zone.runtime_exceeded and self._house_state != "sleep":
    effective_preset = "away"
```

**Reset on constraint mode change** (in `_handle_energy_constraint()`):
```python
if old_mode != constraint.mode:
    for zone in self._zone_manager.zones.values():
        zone.runtime_seconds_this_window = 0.0
        zone.window_start = None
        zone.runtime_exceeded = False
```

### Tests (~6)

- Zone runs 16 min in 20-min window during shed (50%) → exceeded
- Zone runs 10 min in 20-min window during shed → OK
- Zone runs 16 min in 20-min window during coast (75%) → OK
- Window expires → counters reset, zone can run again
- Sleep state → no enforcement
- Constraint changes → counters reset

---

## D6: Max-Occupancy-Duration Failsafe

### Problem

A stuck occupancy sensor (dead batteries, firmware bug) keeps a zone "occupied" indefinitely. D1's vacancy logic never triggers because `any_room_occupied` never goes False.

### Design

If a zone reports occupied continuously for > `max_occupancy_hours` (default: 8), treat as stale — force vacancy logic.

### Implementation

**New field on ZoneState:**
```python
continuous_occupied_since: datetime | None = None
```

**Tracking** (in `update_room_conditions()`):
```python
if zone.any_room_occupied:
    if zone.continuous_occupied_since is None:
        zone.continuous_occupied_since = dt_util.utcnow()
else:
    zone.continuous_occupied_since = None
```

**Failsafe** (in `_apply_house_state_presets()`, alongside D1):
```python
# Stale occupancy failsafe — skip during sleep (RH4 fix)
if (
    zone.any_room_occupied
    and self._house_state != "sleep"
    and zone.continuous_occupied_since is not None
    and (now - zone.continuous_occupied_since).total_seconds() > self._max_occupancy_hours * 3600
):
    effective_preset = "away"
    if not zone.vacancy_sweep_done and zone.vacancy_sweep_enabled:
        await self._execute_vacancy_sweep(zone)
        zone.vacancy_sweep_done = True
    _LOGGER.warning(
        "HVAC: Zone %s occupied >%dh — treating as stale sensor",
        zone.zone_name, self._max_occupancy_hours,
    )
    # NM alert (optional)
    async_dispatcher_send(self.hass, SIGNAL_NM_ALERT, {
        "severity": "MEDIUM",
        "title": f"Zone {zone.zone_name}: possible stuck sensor",
        "message": f"Zone occupied continuously for {self._max_occupancy_hours}+ hours",
    })
```

### Tests (~4)

- Zone occupied 9 hours → failsafe triggers
- Zone occupied 7 hours → no failsafe
- Zone occupied 9 hours during SLEEP → no failsafe
- Zone goes vacant at hour 6, re-occupied → counter resets

---

## D7: Diagnostic Sensors

### Problem

Zone intelligence behavior needs to be observable in HA dashboards and the URA device hierarchy for debugging and user confidence.

### Design

**New attributes on existing sensors** (no new entities — extend existing):

On `HVACZoneStatusSensor` (per zone):
- `zone_presence_state`: The 7-state value (D4)
- `vacancy_grace_remaining_s`: Seconds until grace expires
- `vacancy_sweep_done`: Whether sweep has been executed
- `pre_arrival_person`: Which person triggered pre-arrival
- `solar_banking_active`: Whether solar banking is active for this zone
- `runtime_duty_cycle_pct`: Current runtime utilization (e.g., 45% of 50% limit)
- `runtime_exceeded`: Whether duty cycle is exceeded
- `continuous_occupied_hours`: Hours continuously occupied (for failsafe visibility)

On `HVACModeSensor` (house-level):
- `pre_arrival_zones`: List of zone IDs in pre-arrival state
- `solar_banking_zones`: List of zone IDs being solar-banked
- `vacancy_override_zones`: List of zone IDs overridden to away
- `person_zone_map`: Current person-to-zone mapping (from config)

**New standalone sensor** — `HVACZoneIntelligenceSensor` (1 per coordinator):
- **State:** Number of zones currently on away-override (energy savings indicator)
- **Attributes:**
  - `zones_occupied`: count
  - `zones_away_override`: count + list
  - `zones_pre_arrival`: count + list
  - `zones_solar_banking`: count + list
  - `zones_runtime_limited`: count + list
  - `total_vacancy_sweeps_today`: count
  - `estimated_savings_today`: rough kWh estimate (zones × hours at away × delta setpoint)

### Implementation

Add attributes to existing sensor `get_zone_status_attrs()` and `get_mode_attrs()` methods.

Create `HVACZoneIntelligenceSensor` in `sensor.py` as a new sensor class under the Coordinator Manager device, similar to existing `HVACModeSensor`.

### Tests (~3)

- All new attributes populated correctly
- Zone intelligence sensor state = count of away-override zones
- Attributes update when zone states change

---

## FILE CHANGES SUMMARY

| File | Changes |
|------|---------|
| `domain_coordinators/hvac.py` | D1: vacancy override + sweep in `_apply_house_state_presets()`. D2: pre-arrival handler + fan activation. D3: `_handle_person_arriving()` callback. D5: `_accumulate_zone_runtime()`. D6: stale failsafe. |
| `domain_coordinators/hvac_zones.py` | D1: `last_occupied_time`, `vacancy_sweep_done`, `vacancy_sweep_enabled`. D4: `zone_presence_state`. D5: runtime fields. D6: `continuous_occupied_since`. |
| `domain_coordinators/hvac_predict.py` | D2: zone-specific `_check_pre_conditioning()`, `_should_solar_bank()`, `_activate_zone_fans()`, `_pre_conditioning_zones` set. |
| `domain_coordinators/hvac_const.py` | D1: vacancy grace constants. D2: solar banking constants. D5: duty cycle constants. D6: max occupancy constant. |
| `domain_coordinators/signals.py` | D3: `SIGNAL_PERSON_ARRIVING`. |
| `domain_coordinators/presence.py` | D3: Dispatch `SIGNAL_PERSON_ARRIVING` on geofence arrival. |
| `sensor.py` | D4: zone_presence_state + diagnostic attrs on `HVACZoneStatusSensor`. D7: `HVACZoneIntelligenceSensor`. |
| `config_flow.py` | D1: `CONF_ZONE_VACANCY_SWEEP_ENABLED` in zone options. D3: `CONF_PERSON_PREFERRED_ZONES` in CM options. D5/D6: grace/max-occupancy in HVAC options. |
| `const.py` | New constants for all deliverables. |
| `__init__.py` | RH2: Wire new CONF_ constants into HVACCoordinator constructor. |
| `quality/tests/test_hvac_zone_intelligence.py` | ~43 tests across D1-D7. |

---

## INTERACTION MAP

```
D3 (Person Mapping) ──→ D2 (Pre-Arrival Pre-Cool + Fans)
                              ↓
D1 (Vacancy → Away + Sweep) ←─── away zones become pre-coolable
                              ↓
D4 (State Machine) ←─── reads states from D1, D2, D5
                              ↓
D5 (Duty Cycle) ──→ D4 (runtime_limited state)
                              ↓
D6 (Stale Failsafe) ──→ D1 (triggers vacancy logic for stuck sensors)
                              ↓
D7 (Diagnostics) ←─── reads all states from D1-D6
```

**Implementation order:** D1 → D5 → D6 → D2 → D3 → D4 → D7
(D1 is foundational. D2/D3 depend on D1's vacancy infrastructure. D4 reads from everything. D7 last.)

---

## SELF-CRITIQUE & AMENDMENTS

### Critique 1: Scope Creep — 7 Deliverables Is a Lot

The original plan had 4 deliverables (~12 hrs). This revision has 7 (~25 hrs). That's a significant cycle.

**Amendment:** D1 + D5 + D6 are the core energy savings (vacancy management + runtime limits + failsafe). Ship these first as v3.17.0a. D2 + D3 (solar banking + person mapping) are the smart features — ship as v3.17.0b. D4 + D7 (diagnostics) can ship with either.

### Critique 2: Person-to-Zone Config Is Manual

Users must manually assign persons to zones. No learning.

**Amendment:** Accepted for v3.17.0. Config-based mapping is deterministic and debuggable. Learning layer (track which zone each person enters first after arrival) is deferred to v3.18.x. The infrastructure (signals, zone routing) is designed to support it.

### Critique 3: Solar Banking Economics — Grid Export Should Win

Original plan had solar banking at SOC ≥ 90% which competes with battery charging. PEC 2026 TOU rates are symmetric (export = import at every tier), so there's no premium for peak export. But battery charging (1:1 displacement of peak import) is still more valuable than lossy thermal banking.

**Amendment:** Banking trigger raised to SOC ≥ 95% + net-exporting + hot forecast ≥ 85°F. This ensures banking ONLY happens when battery is full, all other loads are met, and we're literally dumping energy to grid. Banking is last resort before grid export in the excess solar cascade: battery → EV → pool → thermal banking → grid export. Users take their chances with an initially hot house rather than sacrifice export revenue.

### Critique 3b: Offset Floor Must Respect Thermostat Deadband

Raw -3°F offset could produce a cooling setpoint below or too close to the heating setpoint. Ecobee requires ≥2°F deadband in auto mode.

**Amendment:** Floor formula: `max(SOLAR_BANK_FLOOR, target_temp_low + MIN_DEADBAND)` where `MIN_DEADBAND = 2.0°F`. This means a tight 71-74 band gets floored to 73°F (effective offset only -1°F). Acceptable — small savings with free energy.

### Critique 4: Vacancy Sweep Could Conflict With Room Exit Timer

Room coordinator has its own exit timer that turns off lights after vacancy. Zone sweep fires after the zone-level grace period (15 min). If room exit timer is 5 min, lights are already off by zone sweep time — sweep is a no-op. If room exit timer is 30 min (longer than zone grace), zone sweep fires first — room exit timer then has nothing to turn off.

**Amendment:** No conflict — sweep is idempotent. It checks entity state before sending turn_off. If already off, skip. The only oddity: if room exit timer is longer than zone grace, the zone sweep preempts it. This is intentional — zone-level energy policy should override room-level timers.

### Critique 5: Pre-Arrival Fans Without Sleep Check

If someone's geofence triggers at 3 AM (coming home late), pre-arrival would turn on fans in a zone where someone else is sleeping.

**Amendment:** Pre-arrival should check house state — if SLEEP, don't activate fans (only pre-cool). Add `if self._house_state != "sleep":` guard before `_activate_zone_fans()`.

---

## REVIEW CYCLE FIXES (Carried Forward From Rev 1)

All fixes from the first review cycle remain in effect:
- **RC2:** All timestamps use `dt_util.utcnow()` consistently
- **RC3:** `_accumulate_zone_runtime()` called before `_apply_house_state_presets()`
- **RH2:** `__init__.py` wiring for all new CONF_ constants
- **RH3:** Manual preset bypassed for vacant zones
- **RH4:** SLEEP exemption on D5 duty cycle and D6 failsafe

---

## TEST PLAN

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/test_hvac_zone_intelligence.py -v
```

**Target: ~43 tests across D1-D7**

| Deliverable | Tests | Key Scenarios |
|-------------|-------|---------------|
| D1 | 10 | Grace periods, sweep, override toggle, re-occupation, sleep/away passthrough |
| D2 | 8 | Weather pre-cool, solar banking, pre-arrival fans, offset floors, sleep fan guard |
| D3 | 6 | Person mapping, geofence routing, BLE confirmation, timeout, unmapped person |
| D4 | 6 | All 7 states, priority ordering, attribute values |
| D5 | 6 | Duty cycle 50%/75%, window reset, sleep exemption, constraint change |
| D6 | 4 | Stale detection, sleep exemption, NM alert, counter reset |
| D7 | 3 | Sensor attributes, zone intelligence state, sweep count |

---

## ROLLBACK PLAN

All changes are additive:
1. `CONF_HVAC_VACANCY_GRACE_MINUTES` to 9999 → disables D1
2. `CONF_ZONE_VACANCY_SWEEP_ENABLED` to False per zone → disables sweep
3. Solar banking constants: set `SOLAR_BANK_SOC_MIN` to 100 → never triggers
4. `CONF_PERSON_PREFERRED_ZONES` empty → no pre-arrival routing
5. Duty cycle: set factor to 1.0 → no runtime enforcement
6. `CONF_HVAC_MAX_OCCUPANCY_HOURS` to 9999 → disables failsafe
7. D4 and D7 are read-only sensors → no control impact

---

**Planning v3.17.0**
**Last Updated:** March 19, 2026 (revision 2, post-critique)
**Status:** Ready for implementation
