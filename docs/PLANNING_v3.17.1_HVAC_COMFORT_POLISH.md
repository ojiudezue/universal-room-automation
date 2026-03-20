# PLANNING v3.17.1 — HVAC Comfort Polish: Setpoint Ramping + Fan Sleep Gate

**Version:** v3.17.1
**Date:** 2026-03-19
**Status:** Planning
**Parent plans:** PLANNING_v3.17.0_HVAC_ZONE_INTELLIGENCE.md, HA_AUTOMATION_LEARNINGS.md
**Depends on:** v3.17.0 (zone presence state machine used by D1)
**Estimated effort:** 2 deliverables, ~6 hours total
**Priority:** LOW — comfort refinement, not functional gap

---

## OVERVIEW

Two comfort-oriented refinements identified from the HA native automation audit (`HA_AUTOMATION_LEARNINGS.md §1.4, §1.5`):

1. **Gradual setpoint ramping** for pre-conditioning — instead of jumping 2°F instantly, step down 1°F at a time with dwell periods. Prevents HVAC overshoot on oversized systems.

2. **Fan sleep gate** in room automation — temperature-based and humidity-based fans currently activate regardless of sleep state, potentially waking inhabitants.

Both are low-severity comfort improvements. The HA automations learnings doc notes (§Critique 5) that modern thermostats may already handle ramping internally — **D1 requires investigation before implementation.**

---

## WHAT ALREADY EXISTS (Do Not Rebuild)

| Component | Status | Location |
|-----------|--------|----------|
| Pre-cool sets target setpoint | Single 2°F offset applied | `hvac_predict.py:333-363` |
| Pre-heat sets target setpoint | Single 2°F offset applied | `hvac_predict.py:365-395` |
| Fan temperature control | Hysteresis-based, occupancy-gated | `automation.py:928-999` |
| Fan humidity control | Threshold-based with timeout | `automation.py:1001-1041` |
| `is_sleep_mode_active()` | Time-based sleep detection | `automation.py:224-237` |
| Sleep gate on entry/exit automation | Blocks actions during sleep | `automation.py:261-290` |
| Sleep gate on covers | Blocks cover operations during sleep | `automation.py:737-738, 784-785` |
| Night light redirect during sleep | 15% brightness, 2000K warm | `automation.py:335-347` |
| HVAC sleep offset clamping | Limits energy offset during sleep | `hvac_preset.py:94-120` |

**Key finding:** Sleep gating is comprehensive for lights, covers, and notifications. Only fans are missing the gate. Alert lights are also ungated but this is likely intentional (safety/security should override sleep).

---

## DELIVERABLES

| # | Deliverable | Scope | Effort |
|---|-------------|-------|--------|
| D1 | Gradual setpoint ramping for pre-conditioning | Investigation + conditional implementation | ~4 hrs |
| D2 | Fan sleep gate | Add `is_sleep_mode_active()` check to both fan handlers | ~2 hrs |

---

## D1: Gradual Setpoint Ramping for Pre-Conditioning

### Problem

URA's `_execute_pre_cool()` sets the target setpoint in a single step (e.g., 77°F → 75°F). The HA native automations use `timer.back_hallway_cooling_timer` with step events, lowering by 1°F per step to create a gradual cooling curve.

On oversized HVAC systems, a 2°F instant drop can cause:
- Rapid temperature overshoot past target
- Short-cycling (compressor on/off in rapid succession)
- Uncomfortable cold blasts before stabilization

### Investigation Required

Before implementing, validate whether this is actually a problem:

1. **Check thermostat behavior**: Ecobee and Nest thermostats have internal PID controllers that ramp setpoints gradually. If the thermostat already smooths the transition, software ramping adds complexity for no benefit.

2. **Check HA climate entity behavior**: When `climate.set_temperature` is called with a new target, does the thermostat jump immediately or ramp? This varies by integration.

3. **Check historical data**: Review HA history for thermostat entities during pre-conditioning events. If temperature changes smoothly, no software ramping needed.

**Decision gate:** If investigation shows thermostats already ramp internally, mark D1 as "not needed" and close. If thermostats jump instantly and short-cycling is observed, implement ramping.

### Design (Conditional — Only If Investigation Shows Need)

**Ramping strategy:**
- Total offset: 2°F (current pre-cool/pre-heat target)
- Step size: 1°F
- Dwell time: 10 minutes per step (configurable)
- Steps: 2 (for 2°F total offset)
- Total ramp time: 20 minutes

**Implementation approach:**

Option A: **Timer-based stepping** (matches HA automation pattern)
```python
# In hvac_predict.py, replace single setpoint call with stepped approach
async def _execute_pre_cool_ramped(self, zone: ZoneState) -> None:
    total_offset = 2.0  # F
    step_size = 1.0     # F
    dwell_minutes = 10

    current_target = zone.target_temp_high
    steps = int(total_offset / step_size)

    for i in range(steps):
        new_target = current_target - (step_size * (i + 1))
        await self.hass.services.async_call(
            "climate", "set_temperature",
            {"entity_id": zone.climate_entity, "temperature": new_target},
            blocking=False,
        )
        # Wait dwell_minutes before next step
        # Use async_call_later to avoid blocking the decision cycle
        if i < steps - 1:
            await asyncio.sleep(dwell_minutes * 60)
```

Option B: **State-machine stepping** (non-blocking, works with 5-min decision cycle)
```python
# Track ramp state on ZoneState
ramp_target: float | None = None    # Final target temperature
ramp_current_step: int = 0          # Current step (0 = not ramping)
ramp_total_steps: int = 0           # Total steps
ramp_step_started: datetime | None = None

# In decision cycle, advance ramp one step per cycle if dwell elapsed
if zone.ramp_target is not None:
    if zone.ramp_step_started is None or (now - zone.ramp_step_started) > dwell:
        zone.ramp_current_step += 1
        new_temp = base_temp - (step_size * zone.ramp_current_step)
        await set_temperature(zone, new_temp)
        zone.ramp_step_started = now
        if zone.ramp_current_step >= zone.ramp_total_steps:
            zone.ramp_target = None  # Ramp complete
```

**Recommended:** Option B (state-machine). It doesn't block the decision cycle, works naturally with the 5-minute interval, and is cancellable (clear ramp state if pre-conditioning is aborted).

**New config constants** (`hvac_const.py`):
```python
CONF_HVAC_RAMP_ENABLED: Final = "hvac_ramp_enabled"
CONF_HVAC_RAMP_STEP_SIZE: Final = "hvac_ramp_step_size"
CONF_HVAC_RAMP_DWELL_MINUTES: Final = "hvac_ramp_dwell_minutes"
DEFAULT_RAMP_ENABLED: Final = False  # Off by default until validated
DEFAULT_RAMP_STEP_SIZE: Final = 1.0  # F
DEFAULT_RAMP_DWELL_MINUTES: Final = 10
```

### Edge Cases

1. **Pre-conditioning aborted mid-ramp** (house state changes to AWAY): Clear ramp state, revert to house-level preset. The preset change in `_apply_house_state_presets()` handles this — it sets the away preset which overrides any ramp target.
2. **Energy constraint changes during ramp**: Ramp should abort if constraint mode changes to `shed` (HVAC curtailed). Check in decision cycle: if `runtime_exceeded` or constraint changed, clear ramp.
3. **User manually adjusts thermostat during ramp**: Override Arrester detects the manual change. Ramp should be cancelled on manual override. Add check: if arrester detected override on this zone, clear ramp state.
4. **Ramp dwell aligned with decision cycle**: 5-min cycle + 10-min dwell = one step every 2 cycles. This is coarse but acceptable for a 2-step ramp.

### Tests

- Ramp 2 steps × 1°F with 10-min dwell → total 20 min, reaches target
- Pre-conditioning aborted mid-ramp → ramp cancelled, preset restored
- Manual override during ramp → ramp cancelled
- Ramp disabled by config → single-step behavior (current)
- Edge: ramp with 0 steps (offset < step_size) → single-step fallback

---

## D2: Fan Sleep Gate

### Problem

`handle_temperature_based_fan_control()` (automation.py:928-999) and `handle_humidity_based_fan_control()` (automation.py:1001-1041) activate fans based on temperature/humidity thresholds without checking sleep state. A ceiling fan kicking on at 2 AM can wake inhabitants.

The sleep gate pattern is already used throughout `automation.py` — entry automation, exit automation, and covers all check `is_sleep_mode_active()`. Fans are the only room-level control missing this gate.

### Design

**Simple gate insertion:** Add `is_sleep_mode_active()` check at the top of both fan methods. During sleep:
- Temperature fans: do not turn on (but don't turn off if already running — avoid the noise of on/off cycling)
- Humidity fans: **do turn on** — humidity control in bathrooms is more important than sleep noise. Mold and moisture damage outweigh the brief noise.

**Rationale for humidity exception:** The HA automations learnings doc (§1.7) notes humidity fans are for utility rooms (laundry, bathroom). These rooms are unlikely to have sleeping occupants, and humidity damage is cumulative. A bathroom exhaust fan running for 10 minutes after a shower is acceptable during sleep hours.

### Implementation

**Temperature fan gate** (`automation.py`, in `handle_temperature_based_fan_control`):
```python
async def handle_temperature_based_fan_control(
    self, temperature: float | None, occupied: bool
) -> None:
    if not self.config.get(CONF_FAN_CONTROL_ENABLED, False):
        return

    fans = self.config.get(CONF_FANS, [])
    if not fans or temperature is None:
        return

    # Sleep gate: don't START fans during sleep, but allow running fans to continue
    if self.is_sleep_mode_active():
        # Check if any fan is currently on — if so, let it run (avoid on/off noise)
        any_fan_on = any(
            (s := self.hass.states.get(f)) is not None and s.state == STATE_ON
            for f in fans
        )
        if not any_fan_on:
            return  # Don't start fans during sleep
        # If fans already on, fall through to normal logic
        # (they'll turn off naturally when temp drops below threshold)

    # ... existing logic continues unchanged
```

**Humidity fan — NO GATE** (intentional):
```python
async def handle_humidity_based_fan_control(
    self, humidity: float | None
) -> None:
    # NOTE: No sleep gate — humidity control is critical for moisture/mold prevention
    # Humidity fans are typically in bathrooms/laundry, not bedrooms
    humidity_fans = self.config.get(CONF_HUMIDITY_FANS, [])
    # ... existing logic unchanged
```

Add a comment explaining the intentional asymmetry.

### Edge Cases

1. **Fan already on when sleep starts**: Fan continues running until temperature drops below threshold. Then it turns off and won't restart until sleep ends. This is the gentlest behavior — no sudden off/on noise.
2. **Temperature spike during sleep (AC failure)**: Fan won't start during sleep. This is a safety concern if temperature exceeds 85°F+. **Amendment:** Add temperature emergency override — if temp > 85°F, bypass sleep gate.
3. **Bedroom with humidity fan**: Unlikely config (humidity fans are typically bathrooms), but if configured, the humidity fan will run during sleep. This is acceptable — the user explicitly configured it.
4. **Sleep bypass threshold (3+ motion events)**: The existing sleep bypass mechanism (`can_bypass_sleep_mode()`) applies to entry/exit automation, not fans. Fans should respect sleep even after motion bypass — someone getting water at night shouldn't trigger the ceiling fan.

### Implementation (with emergency override)

```python
# Sleep gate with emergency temperature override
if self.is_sleep_mode_active():
    EMERGENCY_TEMP_F = 85.0
    if temperature >= EMERGENCY_TEMP_F:
        _LOGGER.warning(
            "Room %s: Temperature %.1f°F exceeds emergency threshold during sleep — activating fans",
            self.room_name, temperature,
        )
        # Fall through to normal logic
    else:
        any_fan_on = any(
            (s := self.hass.states.get(f)) is not None and s.state == STATE_ON
            for f in fans
        )
        if not any_fan_on:
            return
```

### Tests

- Sleep active, fans off, temp above threshold → fans NOT started
- Sleep active, fans already on, temp above threshold → fans continue running
- Sleep active, fans off, temp drops below threshold → no change (fans were already off)
- Sleep active, temp > 85°F emergency → fans started regardless
- Sleep inactive, normal fan behavior unchanged
- Humidity fans: no sleep gate, always respond to humidity threshold
- Sleep starts while fan running → fan continues until temp drops, then stays off

---

## FILE CHANGES SUMMARY

| File | Changes |
|------|---------|
| `domain_coordinators/hvac_predict.py` | D1: Ramp state machine in `_execute_pre_cool()` / `_execute_pre_heat()`, ramp cancellation on abort |
| `domain_coordinators/hvac_zones.py` | D1: Ramp state fields on ZoneState (if Option B) |
| `domain_coordinators/hvac_const.py` | D1: `CONF_HVAC_RAMP_*` constants |
| `automation.py` | D2: Sleep gate in `handle_temperature_based_fan_control()`, emergency override, comment on humidity exemption |
| `config_flow.py` | D1: Ramp toggle + step size + dwell in HVAC options (if implemented) |
| `quality/tests/test_hvac_comfort_polish.py` | New test file: ~15 tests covering D1-D2 |

---

## SELF-CRITIQUE & AMENDMENTS

### Critique 1: D1 May Be Entirely Unnecessary

The HA automations learnings doc (§Critique 5) explicitly warns: "The HVAC gradual cooling recommendation assumes the current approach causes problems. If the thermostats handle ramping internally, adding software ramping is unnecessary complexity."

The Ecobee thermostats in the home almost certainly have internal PID controllers that smooth setpoint transitions. Adding a software ramp on top of a hardware ramp creates double-ramping — the system would take twice as long to reach target.

**Amendment:** D1 is gated behind investigation. Default `CONF_HVAC_RAMP_ENABLED = False`. Implementation only proceeds if investigation shows thermostats jump instantly. If investigation shows thermostats ramp internally, D1 is closed as "not needed" and the planning doc is updated.

**Recommended investigation steps:**
1. Set pre-cool target manually via HA Developer Tools → Services → `climate.set_temperature`
2. Watch thermostat behavior in HA History for 30 minutes
3. If temperature curve is smooth (no overshoot, no short-cycling), ramping is handled by thermostat
4. If temperature drops sharply then oscillates, software ramping would help

### Critique 2: Fan Sleep Gate Emergency Threshold Is Hardcoded

85°F is reasonable for most climates but may be too low for homes without AC (fans are the only cooling) or too high for elderly/infant safety.

**Amendment:** Make configurable but don't add to config flow unless requested. Use const with clear name:
```python
# const.py
CONF_FAN_SLEEP_EMERGENCY_TEMP: Final = "fan_sleep_emergency_temp"
DEFAULT_FAN_SLEEP_EMERGENCY_TEMP: Final = 85  # °F
```

### Critique 3: Humidity Fan Exception Undocumented to User

User may expect sleep gate to apply to all fans. The humidity exemption is invisible in config flow.

**Amendment:** Add a note in the HVAC config flow description for humidity fans: "Humidity fans remain active during sleep hours to prevent moisture damage." This sets expectations without adding config complexity.

### Critique 4: D1 and D2 Have No Dependency

D1 (ramping) and D2 (fan sleep gate) are independent features bundled in one version for convenience. If D1 investigation shows "not needed," D2 can ship alone.

**Amendment:** D2 is standalone and should ship regardless of D1 outcome. If D1 is closed, v3.17.1 contains only D2 (fan sleep gate). Rename the version to reflect actual content if needed.

### Critique 5: Pool Tiers 2-3 Not Addressed

The Energy Coordinator audit found pool infinity edge shedding and full shutdown stubs. These are not in this plan.

**Amendment:** Pool Tiers 2-3 are explicitly out of scope. They save ~125W (1.5% of pool consumption) and the config options aren't exposed in the UI. They can be addressed in a future energy-focused cycle if pool circuit control becomes a priority.

---

## REVIEW CYCLE: Staff Engineer Critique (2026-03-19)

### CRITICAL Fixes Applied

**RC1: HVAC-level FanController (`hvac_fans.py`) completely missed (Reviewer C1)**

The plan identifies the fan sleep gate gap only in `automation.py` (room-level fans), but there is a **second, independent fan controller** at `domain_coordinators/hvac_fans.py`. This `FanController`:
- Manages the same fan entities via HVAC coordinator (called every 5-min decision cycle from `hvac.py` line 322)
- Has its own temperature hysteresis (`_evaluate_temp_fan`) and humidity logic (`_evaluate_humidity_fan`)
- Has **zero sleep awareness**

Even with D2's sleep gate in `automation.py`, the HVAC FanController would still turn on fans during sleep.

**Resolution:** D2 must gate BOTH controllers:

1. **Room-level** (`automation.py`): Use `is_sleep_mode_active()` as proposed (time-based, room config).
2. **HVAC-level** (`hvac_fans.py`): Pass `house_state` into `FanController.update()` (the HVAC coordinator already tracks `self._house_state`). Gate on `house_state == "sleep"` — consistent with HVAC coordinator patterns.

Updated implementation for `hvac_fans.py`:
```python
async def update(self, constraint: EnergyConstraint | None, house_state: str = "") -> None:
    """Update fan states based on conditions."""
    for zone_id, zone in self._zones.items():
        for fan_entity in zone.fan_entities:
            # Sleep gate: don't start fans during sleep (HVAC level)
            if house_state == "sleep":
                # Allow running fans to continue (avoid noise)
                state = self.hass.states.get(fan_entity)
                if state is None or state.state != STATE_ON:
                    continue  # Don't start new fans during sleep
            # ... existing evaluation logic
```

Caller change in `hvac.py` (line ~322):
```python
await self._fan_controller.update(self._energy_constraint, self._house_state)
```

**RC2: Dual fan controller conflict (Reviewer C2)**

Both `automation.py` and `hvac_fans.py` control the same fan entities independently. One could turn a fan on while the other turns it off.

**Resolution:** Document the intended interaction: HVAC FanController operates at the zone level using zone setpoints and energy constraints. Room-level fan control in `automation.py` uses absolute thresholds. In practice, both generally agree (hot room → fans on). The sleep gate must be consistent across both — if sleep blocks fans in one controller but not the other, the unblocked controller wins (turns fans on).

For v3.17.1: add sleep gate to BOTH controllers. Defer the broader fan controller consolidation question to a future cycle.

### HIGH Fixes Applied

**RH1: Remove Option A entirely (Reviewer H2)**

`asyncio.sleep(600)` inside a pre-conditioning method would block the entire HVAC coordinator for 10+ minutes, preventing all decisions including override arrest and energy constraint processing.

**Resolution:** Option A removed. Only Option B (state-machine stepping, non-blocking) is viable. The plan now presents only Option B.

**RH2: Wrong line numbers (Reviewer H3)**

`_execute_pre_cool` is at lines 333-363 and `_execute_pre_heat` at 365-395, not the plan's 350-380 and 395-430.

**Resolution:** Line numbers corrected in "WHAT ALREADY EXISTS" table.

**RH3: Dual-setpoint service call pattern (Reviewer H4)**

Option B pseudocode shows single `set_temperature(zone, new_temp)` but actual pre-conditioning uses both `target_temp_high` AND `target_temp_low` for Ecobee auto mode.

**Resolution:** Ramped version must pass both values:
```python
await self.hass.services.async_call(
    "climate", "set_temperature",
    {
        "entity_id": zone.climate_entity,
        "target_temp_high": ramped_high,  # Stepped value
        "target_temp_low": zone.target_temp_low,  # Unchanged
    },
    blocking=False,
)
```

### MEDIUM Fixes Applied

**RM1: Emergency temp hardcoded at 85°F — unit system assumption (Reviewer M1)**

URA assumes Fahrenheit throughout (all HVAC defaults in hvac_const.py are °F). Emergency threshold should be configurable.

**Resolution:** Add `CONF_FAN_SLEEP_EMERGENCY_TEMP` to `const.py` (room-level, not hvac_const.py) with default 85°F. Document that URA assumes Fahrenheit.

**RM2: Fan-already-on behavior depends on occupancy (Reviewer M2)**

The plan claims "fan continues until temp drops below threshold" but existing logic turns off fans when `not occupied` (line 951). During sleep, motion sensors stop firing → room becomes "unoccupied" → fan turns off immediately (not when temp drops).

**Resolution:** Clarify in plan: "Fan continues running subject to existing occupancy logic. If room becomes unoccupied during sleep (normal — no motion), fan turns off via existing vacancy logic. The sleep gate only prevents NEW fan activations, it doesn't override existing turn-off behavior." This is actually the correct behavior — if nobody is in the room (no motion detected), the fan should turn off regardless of sleep state.

**RM3: D1 ramp cancellation mechanism unspecified (Reviewer M3)**

No API exists for the predictor to query "did the arrester detect an override?"

**Resolution:** Add `OverrideArrester.was_recently_overridden(climate_entity: str, within_seconds: int = 300) -> bool` method. The predictor calls this each cycle; if True, clears ramp state. Alternative: clear ramp state in `_apply_house_state_presets()` when it detects zone preset changed externally (preset_mode != expected ramp target).

**RM4: Cancelled ramp should allow re-triggering (Reviewer M4)**

`_pre_cool_triggered_today` prevents re-triggering after cancellation, even if pre-cool goal wasn't achieved.

**Resolution:** On ramp cancellation (house state change, manual override), clear `_pre_cool_triggered_today` to allow re-triggering. Add test: "Ramp cancelled mid-step → pre_cool_triggered_today reset → re-triggering allowed."

---

## UPDATED FILE CHANGES SUMMARY

| File | Changes |
|------|---------|
| `domain_coordinators/hvac_predict.py` | D1: Ramp state machine (Option B only) in `_execute_pre_cool()` / `_execute_pre_heat()`, ramp cancellation, dual-setpoint service calls |
| `domain_coordinators/hvac_zones.py` | D1: Ramp state fields on ZoneState |
| `domain_coordinators/hvac_const.py` | D1: `CONF_HVAC_RAMP_*` constants |
| `domain_coordinators/hvac_fans.py` | D2: Sleep gate in `update()` using `house_state` param |
| `domain_coordinators/hvac.py` | D2: Pass `self._house_state` to `_fan_controller.update()` |
| `automation.py` | D2: Sleep gate in `handle_temperature_based_fan_control()`, emergency override, comment on humidity exemption |
| `const.py` | D2: `CONF_FAN_SLEEP_EMERGENCY_TEMP` |
| `config_flow.py` | D1: Ramp toggle + step size + dwell in HVAC options (if implemented) |
| `quality/tests/test_hvac_comfort_polish.py` | ~20 tests covering D1-D2 (expanded for dual-controller) |

---

## TEST PLAN

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/test_hvac_comfort_polish.py -v
```

**Test categories:**
1. D1 (if implemented): Ramp progression (Option B), abort on house state change, abort on manual override, config disabled fallback, dual-setpoint service call, re-trigger after cancellation
2. D2 — Room-level (`automation.py`): Sleep gate on temperature fans, emergency override, humidity fan exemption, fan-already-running passthrough
3. D2 — HVAC-level (`hvac_fans.py`): Sleep gate via house_state, fan-already-running passthrough, constraint interaction during sleep

**Target: ~20 tests**

---

## ROLLBACK PLAN

- D1: `CONF_HVAC_RAMP_ENABLED = False` (default) → disabled. No behavior change from v3.17.0.
- D2: Fan sleep gate is a simple early-return in both `automation.py` and `hvac_fans.py`. If problematic, remove the sleep checks — single line revert per file.

---

**Planning v3.17.1**
**Last Updated:** March 19, 2026 (post-review cycle)
**Status:** Ready for implementation (D1 pending investigation)
