# v4.7.16.2 — Two tier-1 hotfixes (combined release)

**Combined deploy** of two independent hotfixes triggered by live diagnostic during the Bug Class #48 sprint session. Tier 2 reviewed (parallel A/B framings + a final verification pass), 0 CRITICAL / 0 HIGH / 0 MEDIUM at deploy time.

## Hotfix A — AC Nudge overshoot gap 0.5°F → 0.0°F

**Symptom.** `sensor.ura_hvac_coordinator_ac_nudges_today` sat at 0 every day despite all upstream gates passing. Force nudge buttons worked; auto-detection didn't.

**Root cause.** `AC_NUDGE_OVERSHOOT_GAP = 0.5` at `hvac_const.py:213`, used at `hvac_override.py:993` for Gate 6:
```python
overshoot = (zone.current_temperature <= zone.target_temp_high - AC_NUDGE_OVERSHOOT_GAP)
```
On a variable-speed Bryant compressor, the system modulates to hold AT setpoint and rarely undershoots by 0.5°F. Gate 6 never tripped → auto-nudge never fired. The docstring at `hvac_override.py:988-990` named the modulation pattern explicitly — and that pattern **is** the waste the feature was designed to catch (docstring 880-882).

The downstream gates already provide three independent false-positive guards:
- Gate 7: `kwh_rate > zone threshold`
- Gate 7b: N consecutive samples
- Gate 8: overshoot sustained for `detection_time_gate` minutes

The 0.5°F gap was redundant safety blocking real detections.

**Fix.** Single constant change + docs/test updates:
- `hvac_const.py:213` — `AC_NUDGE_OVERSHOOT_GAP: Final = 0.0`
- `hvac_override.py:900,987-994` — docstring + inline comment rewritten
- `docs/HVAC_MANAGEMENT_EXPLAINER.md:144` — Gate 6 table cell
- `docs/user-manual/HVAC_COORDINATOR.md:161` — detection-time gate prose
- `test_v4511_ac_energy_aware_ramp_down.py` — `test_overshoot_gap_is_half_degree` renamed to `_is_zero_post_hotfix`; slicing window widened 6000→9000 to span the expanded Gate 6 comment

**Files touched (5):** `hvac_const.py`, `hvac_override.py`, 2 docs, 1 test.

## Hotfix B — Sleep-state occupied fan trust (bedroom-gated)

**Symptom.** Master bedroom ceiling fan turned off mid-sleep at 00:11 CDT during operator's bedtime. URA's `binary_sensor.master_bedroom_fan_should_run` had been off since 22:37 CDT (1h34m earlier), but the physical PolyFan kept running until 00:11.

**Root cause.** During the AC nudge diagnostic, Bryant Z1 preset oscillation pushed `target_high` from 75°F → 77°F while room was at 76°F. Delta dropped to -1°F. At `hvac_fans.py:387` the temperature off-threshold (`activation_delta - hysteresis = 2.0 - 1.5 = 0.5°F`) met `-1 ≤ 0.5` → fall-through to default off → `fan.turn_off` written.

Per the operator: *"during sleep, fans should run while occupied — people prefer cool moving air at sleep setpoint, and fans aid HVAC efficiency at sleep targets."* The v4.7.13 sleep-state vacancy hold extends the OFF-side timer when no one is detected. There was no symmetric ON-side guarantee.

**Surfaces audited and addressed:**

| Path | File | Status |
|---|---|---|
| A — HVAC per-room fan controller | `domain_coordinators/hvac_fans.py::_evaluate_temp_fan` | **Fixed** (HVAC-managed rooms) |
| B — Room-level automation engine | `automation.py::handle_temperature_based_fan_control` | **Fixed** (non-HVAC-managed rooms) |
| C — Humidity fans | `automation.py::handle_humidity_based_fan_control` | Out of scope (different domain) |
| D — Pre-arrival defan | `hvac.py::_deactivate_zone_fans` | Out of scope (orthogonal trigger) |

**Fix shape (operator product call: bedroom-only).**

Both Path A and Path B short-circuit the off-path during sleep + occupied **AND** `room_type == ROOM_TYPE_BEDROOM`. The bedroom gate uses the existing per-room `CONF_ROOM_TYPE` infrastructure (`const.py:290`, taxonomy at lines 300-307: bedroom / closet / bathroom / media_room / garage / utility / common_area / generic / infrastructure). No new config surface.

Path A inline structure:
```python
if (
    self._house_state == "sleep"
    and occupied
    and room_fan.room_type == ROOM_TYPE_BEDROOM
):
    room_fan.vacancy_detected_time = ""  # Reviewer B B-MED-1: prevent stale anchor
    if room_fan.is_on:
        return True, room_fan.trigger or "sleep_occupied_hold", room_fan.speed_pct
    return True, "sleep_occupied_activate", FAN_SPEED_LOW_PCT
```

Path B inline structure:
```python
room_type = self.config.get(CONF_ROOM_TYPE, ROOM_TYPE_GENERIC)
sleep_occupied_hold = (
    self.is_sleep_mode_active()
    and occupied
    and room_type == ROOM_TYPE_BEDROOM
)
if (temperature < effective_threshold or not occupied) and not sleep_occupied_hold:
    # ... existing turn-off path
```

**Preserved guarantees (all verified in review):**
- Manual-off cooldown (`hvac_fans.py:322-329`) runs **before** the new branch → explicit user override wins.
- `FAN_SLEEP_OFF` policy (`automation.py:1517`) returns early **before** the new guard → explicit user opt-out wins.
- v4.7.13 vacancy-hold sleep trust (unoccupied path) unchanged.
- Energy `fan_assist` branch intentionally bypassed during sleep+occupied (v3.18.1 sleep cap at line 239 would clamp any boost to LOW anyway — documented inline so future readers don't restore it).
- Distinct labels `sleep_occupied_hold` (preserve running fan) vs `sleep_occupied_activate` (turn on from off) for diagnostic audit fidelity.
- Default room_type = `ROOM_TYPE_GENERIC` for rooms without explicit classification → falls through to existing pre-hotfix behavior. Safe default.

**Files touched (4 prod + 2 tests):** `hvac_fans.py`, `automation.py`, plus mock-const fixture extension in `test_hvac_fan_control.py` and new test file `test_hotfix_sleep_occupied_fan_trust.py` (13 tests).

## Tier classification

Tier 1 (combined) — two independent surgical fixes, no DB / config-flow / migration surface, no new sensors. ~140 LoC across both, ~3 KB of doc changes. Per CLAUDE.md operator-elevated review protocol, ran Tier 2 (parallel A correctness/edge-cases + B async/lifecycle/race) on each branch plus a final verification pass after the bedroom-gate refinement.

## Test plan

```bash
PYTHONPATH=quality python3 -m pytest \
  quality/tests/test_v4511_ac_energy_aware_ramp_down.py \
  quality/tests/test_hotfix_sleep_occupied_fan_trust.py \
  quality/tests/test_hvac_fan_control.py \
  quality/tests/test_fan_control_v318.py \
  quality/tests/test_v4621_humidity_fan_hardening.py
```
Expected: 271 passed (state at deploy time).

## Live validation

**Hotfix A:**
- `sensor.ura_hvac_coordinator_ac_nudges_today` increments above 0 within the first cooling cycle where Bryant holds at setpoint AND kwh_rate exceeds the per-zone threshold for `_sustained_samples` consecutive ticks (default 3 samples × 5 min = 15 min, then `detection_time_gate` min sustained at default 10 min).
- No spurious nudges on transient ticks (Gates 7/7b/8 carry the FP defense).

**Hotfix B:**
- Tonight: master bedroom PolyFan should NOT turn off mid-sleep when Bryant Z1 preset oscillates or current temp drops slightly below target.
- Other bedrooms (Jaya Bedroom, Guest Bedroom 1/2, Ziri Bedroom) should behave identically — sleep trust applies because all are classified `bedroom` in room config.
- Common areas (Kitchen, Living Room, Patio, Hallways) — no behavior change. Sleep trust does NOT fire because their `room_type` is not `bedroom`. Spurious mid-night presence in those areas won't hold or activate fans.
- Trigger labels on diagnostic readouts: `sleep_occupied_hold` (preserve) and `sleep_occupied_activate` (newly turned on) — distinct from awake-state `temperature` / `fan_assist` / `humidity`.

## Rollback

Either:
- HACS install v4.7.16.1 (the prior LIVE version — drops both hotfixes), OR
- Disable per-feature:
  - Hotfix A: this gates `check_ac_reset` Gate 6 — disable via the existing `switch.ura_hvac_coordinator_26_ac_nudge` master.
  - Hotfix B: this affects sleep-time fan retention in bedrooms — set `CONF_FAN_SLEEP_POLICY` to `FAN_SLEEP_OFF` per room (explicit opt-out still wins).

## Sibling/follow-on

- **Reviewer B B-MED-2** (pre-existing, separate cycle): temp-fan reload-mid-cycle anchor seeding missing — analog to the v4.6.2.3 humidity-fan fix at `hvac_fans.py:259-270`. ~10 LoC, Tier 1, file as v4.7.x follow-on.
- **v4.7.17** (planned, separate cycle): dataclass reconciliation `RoomSignal`/`VetoVerdict` vs `ReliableSignal`/`VetoDecision`, plus flipping v4.7.16's D3 from diagnostic-only to gating.
