# v3.15.1: Automatic Guest Mode from Census

**Date:** 2026-03-13
**Branch:** develop -> main
**Tests:** 1092 total (no regressions)

## Problem

Guest mode (`HouseState.GUEST`) was defined in the state machine with valid transitions, security mapping (`ARMED_HOME`), HVAC mapping (`home` preset), and a binary sensor — but nothing ever triggered it automatically. Census already tracked `unidentified_count` (camera unrecognized + WiFi guest floor), but the presence inference engine ignored it.

## Solution

### `domain_coordinators/presence.py`

**`StateInferenceEngine.infer()`** — Added `unidentified_count` parameter and two new rules:
- **Guest entry**: If `unidentified_count > 0` while in `HOME_DAY`, `HOME_EVENING`, `HOME_NIGHT`, or `ARRIVING` → transition to `GUEST` (confidence 0.8)
- **Guest exit**: If in `GUEST` and `unidentified_count == 0` → return to time-based home state (DAY/EVENING/NIGHT)
- Guest mode is NOT entered during sleep hours (safety — don't disarm interior sensors at night for unidentified persons)

**`_handle_census_update()`** — Now captures `unidentified_count` from census signal (was already dispatched but ignored)

**`_run_inference()`** — Passes `unidentified_count` to inference engine

**`get_diagnostics_summary()`** — Exposes `unidentified_count` in diagnostics

### Flow
1. Census detects unidentified person (camera sees face not in known list, or WiFi guest VLAN device)
2. Census dispatches `SIGNAL_CENSUS_UPDATED` with `unidentified_count > 0`
3. Presence coordinator captures count, runs inference
4. Inference transitions to `GUEST` (if in a home state, not sleep)
5. Security stays `ARMED_HOME`, HVAC runs comfort preset
6. When unidentified persons leave, census updates count to 0
7. Inference exits `GUEST` → returns to time-based home state
