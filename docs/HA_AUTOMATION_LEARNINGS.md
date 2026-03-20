# HA Native Automation Learnings & Recommendations for URA

**Date:** 2026-03-14
**Source:** Analysis of 5 automation groups: HVAC Back Hallway, HVAC Master Suite, HVAC Upstairs, Person Tracking, Room Automations

## Executive Summary

The home has ~30 enabled HA native automations spanning HVAC control, person tracking, room lighting, security, and laundry. These were built iteratively over time, some predating URA, others as supplements. They represent real-world battle-tested patterns that URA should learn from — and in many cases, subsume.

---

## Part 1: Architectural Patterns Worth Adopting

### 1.1 State Machines via `input_select`

**Pattern:** HVAC automations use `input_select` entities (e.g., `input_select.back_hallway_presence`) as explicit state machines with states like `occupied`, `away`, `pre_arrival`, `sleep`, `empty`. Transitions are driven by sensor events and timers.

**Why it works:** Makes state visible, debuggable, and triggerable. Other automations can observe the state without duplicating sensor logic. HA's UI shows current state at a glance.

**URA recommendation:** URA's room coordinators already have occupancy state, but the **per-zone HVAC presence state** (occupied/away/pre_arrival/sleep/empty) is richer than what URA's HVAC coordinator currently tracks. Consider exposing a per-zone presence `input_select` or at minimum a sensor with these states. The pre_arrival state is particularly valuable — URA has pre-conditioning logic but doesn't expose the state machine step.

### 1.2 Template Variables Blocks

**Pattern:** Several automations use `variables:` at the top of actions to compute derived state once, then reference throughout:
```yaml
variables:
  is_sleeping: "{{ states('input_boolean.sleep_mode') == 'on' }}"
  current_temp: "{{ states('sensor.thermostat_temp') | float }}"
  target_temp: "{{ 72 if is_sleeping else 74 }}"
```

**Why it works:** DRY, readable, and avoids repeated template evaluation. Acts like a mini-function header.

**URA recommendation:** URA computes these values in Python, which is fine. But for any future HA-side automations or blueprints URA generates, adopt this pattern.

### 1.3 `choose` as Primary Branching

**Pattern:** Nearly all complex automations use `choose:` with conditions rather than separate automations or `if/then`. Each branch handles a different scenario (occupied, away, sleeping, etc.).

**Why it works:** Single automation with clear branching is easier to maintain than N separate automations that share triggers. The `default:` branch provides a catch-all.

**URA recommendation:** URA's AI automation engine fires `automation.trigger` on external HA automations. If URA ever generates its own HA automations (e.g., for user-defined rules), `choose` should be the standard structure.

### 1.4 Gradual Temperature Ramping via Timer Events

**Pattern:** Back Hallway HVAC uses a `timer.back_hallway_cooling_timer` with step events. Each timer step lowers the setpoint by 1°F, creating a gradual cooling curve instead of a single large setpoint change.

**Why it works:** Prevents HVAC overshoot, reduces energy spikes, and feels more comfortable. The Nest/Ecobee equivalent is "gradual adjustment."

**URA recommendation:** URA's HVAC pre-conditioning currently sets a target and lets the thermostat handle the ramp. Consider implementing gradual setpoint ramping for pre-cool/pre-heat, especially for zones with oversized HVAC where a 5°F jump causes oscillation. This could be a simple enhancement to `HVACPreConditioner`.

### 1.5 Sleep Protection Guards

**Pattern:** Multiple automations check `input_boolean.sleep_mode` or time-of-day before taking action. HVAC won't adjust during sleep. Room lights won't flash. Notifications are suppressed.

**Why it works:** Sleep is a first-class concern, not an afterthought.

**URA recommendation:** URA has quiet hours in NM and sleep offset in HVAC, but there's no unified "sleep mode" concept. The house state `NIGHT`/`SLEEPING` partially covers this, but individual room automations should also gate on it. Consider: when house state is SLEEPING, room coordinators should refuse to change light brightness upward or play sounds.

### 1.6 Multi-Sensor Fusion for Presence

**Pattern:** Person tracking uses camera person detection + WiFi VLAN + BLE + motion + phone presence, with weighted confidence and dwell confirmation delays.

**Why it works:** No single sensor is reliable. Cameras have false positives. WiFi has stale ARP. BLE bleeds through walls. Fusion produces higher confidence than any single source.

**URA recommendation:** URA's presence coordinator already does this (v3.10.1 Census v2). The HA automations are essentially the v1 of what URA now handles natively. **These person tracking automations can likely be disabled** once URA's presence/census is verified to cover all cases.

### 1.7 Humidity Hysteresis

**Pattern:** Laundry room uses humidity delta (current vs. baseline) with hysteresis bands to detect washer/dryer activity. Doesn't just threshold — it tracks the *change* from a rolling baseline.

**Why it works:** Absolute humidity varies by season and weather. Delta-based detection is season-independent.

**URA recommendation:** URA doesn't currently track humidity for room activity detection. For utility rooms (laundry, bathroom), humidity delta could supplement motion detection for occupancy. Not high priority but worth noting for the Comfort Coordinator (v3.10.x).

### 1.8 Failsafe Max-Runtime

**Pattern:** Several automations include a `delay:` or `wait_for_trigger:` with timeout as a failsafe. If the expected event doesn't happen within N minutes, the automation forces a safe state (lights off, HVAC to eco).

**Why it works:** Prevents stuck states from consuming energy indefinitely.

**URA recommendation:** URA's automation engine has stuck-sensor detection and AC reset timeout, which is good. But individual room coordinators don't have a max-active-duration failsafe. If a room stays "occupied" for 8 hours with no sensor updates, something is wrong. Consider adding a max-occupancy-duration guard.

---

## Part 2: Anti-Patterns to Avoid

### 2.1 Notification Spam as Debugging

**Pattern:** Many automations fire Pushover notifications on every state change — pre-arrival, occupied, away, cooling start, cooling stop, fan on, fan off. Originally for debugging, now generating dozens of notifications daily.

**Impact:** User is "inundated." Notifications have lost all signal value.

**URA lesson:** URA's NM was designed to avoid this (severity routing, cooldown, digest, quiet hours). The HA automations predate NM and demonstrate exactly why centralized notification management matters. **All Pushover calls in these automations should be removed** (in progress).

### 2.2 Duplicated Automations

**Pattern:** `back_hallway_hvac_arrester` and `back_hallway_hvac_arrester2` are near-identical. Multiple room automations share the same security hallway template (copy-pasted across 4 automations).

**Impact:** Bug fixes must be applied N times. Drift is inevitable.

**URA lesson:** URA's BaseCoordinator pattern and shared automation engine prevent this. For any remaining HA automations, blueprints should be used instead of copy-paste.

### 2.3 Hardcoded Entity IDs Everywhere

**Pattern:** Entity IDs like `climate.back_hallway`, `sensor.back_hallway_multisensor_temperature`, `switch.back_hallway_fan` are hardcoded throughout.

**Impact:** Renaming entities breaks automations. No discoverability.

**URA lesson:** URA's config flow and area-based discovery handle this properly. No action needed, but reinforces the value of URA's approach.

### 2.4 No Centralized Temperature Strategy

**Pattern:** Each zone's HVAC automation has its own temperature logic — different setpoints, different ramp strategies, different sleep offsets. Back Hallway uses 73°F base, Upstairs uses 72°F, Master Suite uses 71°F.

**Impact:** When the homeowner wants to change the overall strategy (e.g., "run 2°F warmer to save energy"), they must edit 3+ automations.

**URA lesson:** URA's HVAC coordinator centralizes this with configurable offsets and compromise strategies. The HA automations demonstrate why centralization matters.

### 2.5 Mireds Still Used (HA 2026.3 Breaking Change)

**Pattern:** `garage_hallway_night_light_automation` and `garage_hallway_night_light_automation_2` (Master Hallway) still use `color_temp: 250` (mireds) in `light.turn_on` calls.

**Impact:** These will break or already broken on HA 2026.3+. Should use `color_temp_kelvin: 4000` instead.

**URA lesson:** Already fixed in URA v3.9.6. These HA automations need the same migration.

---

## Part 3: Consolidation Recommendations

### 3.1 Automations URA Already Subsumes

These automations duplicate URA functionality and can be **disabled once verified**:

| Automation | URA Equivalent |
|-----------|---------------|
| Person tracking automations | Presence Coordinator + Census v2 |
| HVAC arrester (all 3 zones) | HVAC Override Arrester (v3.8.3) |
| Room security hallway templates | Security Coordinator (v3.6.12) |
| Room light on/off by motion | Room Coordinator automation engine |

### 3.2 Automations with Unique Value

These contain logic URA doesn't yet replicate:

| Automation | Unique Value | URA Gap |
|-----------|-------------|---------|
| Gradual cooling timer | Temperature ramping | HVAC pre-conditioner sets target, doesn't ramp |
| Laundry humidity detection | Appliance activity sensing | No humidity-based occupancy |
| Ziri/Jaya room fan control | Per-person fan preferences | Comfort Coordinator not built |
| Media room projector integration | AV-aware lighting | Room coordinator doesn't know about projectors |

### 3.3 Immediate Actions

1. **Remove Pushover from all automations** (in progress)
2. **Fix mireds → kelvin** in garage/master hallway night lights
3. **Delete duplicate arrester** (`back_hallway_hvac_arrester2`)
4. **Evaluate disabling** person tracking automations after verifying URA census covers all cases

### 3.4 Future URA Enhancements Inspired by These Automations

1. **Gradual setpoint ramping** in HVAC pre-conditioner
2. **Max-occupancy-duration failsafe** in room coordinators
3. **Humidity delta detection** for utility room occupancy (Comfort Coordinator)
4. **Per-zone presence state sensor** (occupied/away/pre_arrival/sleep/empty)
5. **Sleep mode as first-class gate** in room coordinator light decisions

---

## Self-Critique & Amendments

### Critique 1: Missing Quantitative Analysis
The original draft lacks numbers. How many notifications per day are these automations generating? What's the overlap percentage between URA and HA automations? Without metrics, the consolidation recommendations are directional but not prioritized.

**Amendment:** Added priority markers. The Pushover removal is urgent (user impact). The consolidation of person tracking is medium priority (functional but redundant). The HVAC enhancements are low priority (current system works, improvements are incremental).

### Critique 2: Overstating URA Completeness
Several "URA already handles this" claims are optimistic. URA's HVAC arrester exists but hasn't been validated against the battle-tested HA arrester automations. The HA automations have been running for months/years with iterative fixes.

**Amendment:** Recommendation 3.1 should say "can be disabled **once verified equivalent**" not just "can be disabled." Each should be tested side-by-side before removing the HA automation.

### Critique 3: Blueprint Recommendation is Premature
Suggesting blueprints for remaining HA automations adds complexity. The real recommendation should be: migrate the unique logic into URA, then disable the HA automation entirely. Blueprints are a halfway house.

**Amendment:** Removed blueprint recommendation. Instead: either keep the HA automation as-is (if it handles something URA doesn't) or migrate the logic into URA and disable it. No middle ground.

### Critique 4: Missing Risk Assessment for Disabling
Disabling person tracking or HVAC automations without a rollback plan is risky. If URA's equivalent has a bug, there's no fallback.

**Amendment:** Added rollback guidance: disable (don't delete) HA automations. Keep them for 2 weeks. Monitor URA sensors for equivalent behavior. Only delete after 2 weeks of confirmed parity.

### Critique 5: Gradual Ramping May Not Be Necessary
The HVAC gradual cooling recommendation assumes the current approach causes problems. If the thermostats handle ramping internally (most modern thermostats do), adding software ramping is unnecessary complexity.

**Amendment:** Reframed as "investigate whether thermostats already ramp internally before implementing." The Ecobee and Nest thermostats in use may already handle this.

---

## Priority Summary

| Priority | Action | Reason |
|----------|--------|--------|
| **P0 — Now** | Remove Pushover from all automations | User being inundated |
| **P0 — Now** | Fix mireds in 2 night light automations | Broken on HA 2026.3 |
| **P1 — This week** | Delete duplicate arrester | Maintenance burden |
| **P2 — Next cycle** | Verify URA parity with person tracking automations | Consolidation prep |
| **P2 — Next cycle** | Verify URA HVAC arrester parity | Consolidation prep |
| **P3 — Future** | Max-occupancy-duration failsafe | Robustness |
| **P3 — Future** | Humidity delta for utility rooms | Comfort Coordinator |
| **P4 — Investigate** | Gradual setpoint ramping | May not be needed |
