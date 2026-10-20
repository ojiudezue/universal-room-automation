# v5.103.78: diagnostic sensors stop rewriting unchanged information

Card: RECORDER-CHURN-SWEEP-URASENSORS-1. Tier 2, two reviews (A correctness: SHIP; B recorder effect + lifecycle: SHIP with one MEDIUM, fixed). Deploy risk: LOW (diagnostic sensors only; no automation reads their published values).

## Problem

Measured 2026-10-20: URA wrote ~20k recorder rows/hr and ~7k new `state_attributes` rows/hr. Several diagnostic sensors published values that change every 30 s tick (countdowns, "x minutes ago", per-tick timestamps), so every tick became a history row even when nothing happened.

## Fix (all in `sensor.py`; constants in `const.py`)

- `AutomationHealthSensor`: countdown/elapsed attributes replaced by values that only change on a transition (`session_started_at`, `failsafe_at`, `debounce_started_at`, `grace_until`, stuck `on_since`). `failsafe_at` uses the room's real failsafe duration (60 min closets/bathrooms), fixing the old hard-coded 4 h. `excluded_sensors` no longer carries a per-tick timestamp.
- `time_ago` dropped from Last Automation Trigger/Action/Time and Last Occupant (timestamps kept).
- Time since motion and census validation age floored to whole minutes (`DIAG_TIME_SINCE_MOTION_QUANTUM_S`, `DIAG_CENSUS_VALIDATION_AGE_QUANTUM_S` = 60); census age clamps negative (clock skew) to 0.
- Occupancy timeout remaining rounded up to 30 s steps (`DIAG_OCCUPANCY_TIMEOUT_REMAINING_QUANTUM_S` = 30), never 0 while time remains.
- HVAC AC kWh-rate sensors: `age_seconds` removed, `last_updated` unrecorded.
- A quantum ≤ 1 disables rounding (kill switch). Coordinator data (raw seconds) is untouched, so no decision changes.

HA mechanism (review B, read from installed HA core.py:2313-2347): an identical state+attributes write only updates `last_reported` and fires `state_reported`, which the recorder ignores, so stable sensors produce no rows.

## Tests

- `test_recorder_churn_diag_sensors.py`: 38 tests on the real sensor classes; every site mutation-drilled RED (including the three fix-up guards).
- Full-suite name-diff vs develop c57e8b625: CLEAN, 11 = 11, 0 new / 0 gone (17,812 passed).

## Same restart (HA config, not URA code)

- Recorder excludes for ~18k rows/hr with no history consumer, and the corrupt Envoy lifetime production counter. Ledger + undo steps: `docs/planning/RUNBOOK_recorder_excludes.md`.

## Live validation (to fill after restart)

- URA states rows/hr and new state_attributes rows/hr vs 20.1k / 7.0k (2026-10-20 13:00-16:00).
- `*_automation_health` attributes identical across ticks in an occupied room.
- Excluded entities write 0 rows; 50/50 URA entries loaded, 0 URA ERRORs.
