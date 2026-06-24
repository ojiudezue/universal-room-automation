# URA v5.6.1 — Config-flow label hotfix (Climate & Fans translations sync)

v5.6.0 shipped the new **Climate & Fans** step's rename + field labels in `strings.json` (the dev source), but `translations/en.json` — which Home Assistant actually serves to the config-flow UI — was never synced. Result: the live room config form showed the old title **"Climate & HVAC"** and **raw snake_case keys** (`humidity_fan_control_enabled`, `wet_room`, `humidity_fan_spike_enabled`, `humidity_fan_presence_runtime_*`) instead of friendly labels. Operator caught it live. This is a strings-only hotfix.

## What ships (Tier 1)
- **Synced `translations/en.json` from `strings.json`** for all config + options steps. The Climate & Fans step now serves the renamed title and friendly labels + help text for every new field: *Enable Humidity/Exhaust Fan Control*, *Wet Room (bathroom/laundry)*, *Enable Humidity Spike Detection*, *Enable Post-Vacancy Runtime*, *Post-Vacancy Base Runtime / Added Runtime per Minute Occupied / Runtime Cap*, *Comfort Range — Low/High (°F)*, *Climate/Thermostat Entity (fallback)*.
- **Also fixed two older stale labels** the same drift had left as raw keys: `disable_camera_presence` (camera-presence cycle) and `fan_recheck_enabled` (v4.7.22 fan-recheck).
- **New regression guard** `quality/tests/test_strings_en_translation_parity.py` (77 cases): asserts every `strings.json` config/options step title + `data`/`data_description` key exists in `translations/en.json`. This drift class — "update strings.json, forget en.json" — has recurred across several cycles; the test makes it un-shippable.
- **No logic change.** Pure translations + test.

## Why it drifted
HA loads config-flow UI text from `translations/<lang>.json`, not `strings.json`. The build edited the source and the suite (which never renders the config flow) stayed green. The new parity test closes that gap.

## Live Validation — Validated 2026-06-23 (post-restart)
| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Hotfix healthy | **PASS** | `update.universal_room_automation_update` installed_version = `v5.6.1`; zero URA ERROR entries in the system log at boot. |
| L2 | Translations synced | **PASS** | `translations/en.json` `options.step.climate.title` = "Climate & Fans" (was "Climate & HVAC"); all new field labels present; parity test `test_strings_en_translation_parity.py` 77/77. HA serves config-flow text from `en.json`, reloaded on this restart. |
| L3 | Visual render | **operator-confirm** | Reopen a room's **Climate & Fans** step — labels show friendly names (no raw snake_case keys). Code+file-proven; final confirmation is visual. |

## Known follow-up (not in this hotfix)
The spike/EMA + presence-runtime knobs render **flat**, not inside the collapsed `humidity_fan_advanced` section the plan intended (the `section()` grouping did not land in v5.6.0). Functional, but more cluttered than designed — a small config_flow.py follow-up if we want the advanced knobs collapsed.
