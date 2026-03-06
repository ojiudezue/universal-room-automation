# v3.6.39 — Cover automation redesign: 5 open modes + new time sources

## Summary

Complete redesign of cover open/close automation. Replaces the old 3-option
entry action (none/always/smart) with a 5-mode system that covers all real-world
use cases. Backwards compatible with legacy config keys.

## Cover Open Modes

| Mode | Behavior |
|------|----------|
| `none` | Manual only, no automation |
| `on_entry` | Open when room becomes occupied, any time of day |
| `at_time` | Open at scheduled time regardless of occupancy |
| `on_entry_after_time` | Open on occupancy, but only after sunrise/hour (replaces old "smart") |
| `at_time_or_on_entry` | Both: scheduled open AND occupancy-triggered open |

## Cover Close

- **Exit close**: unchanged (none / always / after sunset only)
- **Timed close**: sunset or specific hour (replaces old 4-mode timing system)

## New Config Keys

| Key | Values | Purpose |
|-----|--------|---------|
| `cover_open_mode` | 5 modes above | Which open trigger to use |
| `cover_open_time_source` | `sunrise` / `specific_hour` | What "time" means for open |
| `cover_open_hour` | 0-23 (default 7) | Hour for specific_hour source |
| `cover_close_time_source` | `sunset` / `specific_hour` | What "time" means for close |
| `cover_close_hour` | 0-23 (default 21) | Hour for specific_hour source |

## Legacy Compatibility

`_get_cover_open_mode()` maps old config to new modes:
- `COVER_ACTION_ALWAYS` → `on_entry`
- `COVER_ACTION_SMART` → `on_entry_after_time`
- `COVER_ACTION_NONE` → `none`

`_is_cover_open_time()` and `_is_cover_close_time()` check new config first,
fall back to old `CONF_OPEN_TIMING_MODE` / `CONF_CLOSE_TIMING_MODE` if not set.

## Sleep Mode

Sleep mode blocks ALL automated cover opens (all 5 modes). Manual opens unaffected.

## Manual Override

Before opening/closing, checks current cover state (`_are_covers_already_open()` /
`_are_covers_already_closed()`). Skips action if covers are already in the desired
state, preventing unnecessary service calls on manually adjusted covers.

## Files Changed

| File | Change |
|------|--------|
| `const.py` | New cover open mode constants, time source constants, hour defaults |
| `automation.py` | `_get_cover_open_mode()` with legacy fallback, `_is_cover_open_time()`, `_is_cover_close_time()`, refactored `_control_covers_entry()` for 5 modes, new `check_timed_cover_open()`, state-check guards, sleep mode blocking |
| `coordinator.py` | Wire `check_timed_cover_open()` into periodic tasks |
| `config_flow.py` | Replace old 3-option cover actions with new 5-mode dropdown, new time source selectors, compact close section; both setup and reconfig steps |
