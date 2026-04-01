# v3.20.2 — Config Flow UX (Cycle B) + Stub Cleanup (Cycle C)

**Date:** 2026-03-31
**Review tier:** Hotfix (1 review each)

## What Changed

Two cycles shipped together: Config flow UX improvements (Cycle B) and stub entity
removal (Cycle C).

---

## Cycle B: Config Flow UX

### D1: Automation Chaining in Initial Room Setup
- Automation chaining (bind HA automations to enter/exit/lux triggers) now available
  during initial room creation, not just via reconfigure options flow

### D2: AI Rules in Initial Room Setup
- AI NLP rules can now be added during initial room creation
- Calls `_parse_rule_with_ai_init()` inline (review fix: no deferred parsing)

### D3: Split Oversized Options Step
- `automation_behavior` options step (15 fields) split into `options_lighting` (6 fields)
  and `options_covers` (10 fields)

### D4: Conditional Fields
- OptionsFlow: shared space detail fields only shown when toggle enabled
- OptionsFlow: notification override fields only shown when toggle enabled
- Initial flow: keeps all fields visible (linear flow, no back navigation)

### D5: AI Rule Person Selector
- `CONF_AI_RULE_PERSON` changed from TextSelector to EntitySelector(domain="person")

### Strings/Translations
- Added entries for all new step IDs in strings.json and translations/en.json

---

## Cycle C: Stub Cleanup

Removed 15 dead entities and 1 dead signal. All documented in
`docs/DEFERRED_TO_BAYESIAN.md` for v4.0.0 reimplementation.

### D1: Remove Non-Functional Buttons
- Removed `ClearDatabaseButton` (logged warning only, no action)
- Removed `OptimizeNowButton` (logged warning only, no action)

### D2: Remove Stub Sensors
- Removed 11 stub sensors from `sensor.py`: OccupancyPercentageTodaySensor,
  EnergyWasteIdleSensor, MostExpensiveDeviceSensor, OptimizationPotentialSensor,
  EnergyCostPerOccupiedHourSensor, TimeUncomfortableTodaySensor, AvgTimeToComfortSensor,
  WeekdayMorningOccupancyProbSensor, WeekendEveningOccupancyProbSensor,
  TimeOccupiedTodaySensor, OccupancyPatternDetectedSensor
- Removed 2 stub binary sensors: OccupancyAnomalyBinarySensor, EnergyAnomalyBinarySensor
- Removed orphaned `STATE_OCCUPANCY_PCT_TODAY` constant from `const.py`

### D3: Remove Dead Signal
- Removed `SIGNAL_COMFORT_REQUEST` and `ComfortRequest` dataclass from `signals.py`
  (defined but never dispatched or consumed)

### Documentation
- Created `docs/DEFERRED_TO_BAYESIAN.md` with all 15 entities + 1 signal mapped to
  v4.0.0 Bayesian Intelligence milestones (B1-B4)

## Files Changed
- `button.py`, `sensor.py`, `binary_sensor.py`, `const.py`, `domain_coordinators/signals.py`
- `quality/tests/test_domain_coordinators.py` (removed dead signal test refs)
- New: `docs/DEFERRED_TO_BAYESIAN.md`, `quality/tests/test_cycle_c_stub_cleanup.py`
