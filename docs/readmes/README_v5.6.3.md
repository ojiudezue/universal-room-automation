# URA v5.6.3 — Climate & Fans section labels (collapsed-section strings)

Completes the v5.6.x strings cleanup. The room "Climate & Fans" step wraps its advanced knobs in two HA `section()` blocks — `humidity_fan_advanced` (collapsed: the EMA spike-tuning constants) and `climate_backstop` (the comfort-range temps + thermostat fallback). But `strings.json`/`translations/en.json` had no `sections` block, so when you scrolled/expanded those sections the **section headers and their fields rendered as raw snake_case keys**. v5.6.1 fixed only the top-level field labels.

## What ships (Tier 1)
- **Added a `sections` block** to the climate step in both `strings.json` and `translations/en.json`, both create + options flows:
  - `humidity_fan_advanced` — name "Advanced — Humidity Spike Tuning"; labels + help for Spike Delta (%), Baseline EMA Time-Constant (s), Baseline Mode.
  - `climate_backstop` — name "Climate Backstop (comfort range + thermostat fallback)"; labels + help for Comfort Range Low/High (°F) + Climate/Thermostat Entity (fallback).
- **Moved** `target_temp_heat`/`target_temp_cool`/`climate_entity` labels from the (HA-ignored) top-level `data` into `sections.climate_backstop.data` where they actually render.
- **Parity test extended** to assert `sections` parity (section keys, `name`, `data`/`data_description`) between strings.json and en.json — so a section-label drift is now caught alongside step/menu drift.
- No logic change.

## Live Validation — Validated 2026-06-28 (post-restart)
| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Hotfix healthy | **PASS** | installed_version = `v5.6.3`; zero URA ERROR entries at boot. |
| L2 | Section strings present | **PASS (file+test)** | `sections.humidity_fan_advanced` + `sections.climate_backstop` present in `translations/en.json` (both flows) with names + field labels; parity test 77/77 incl. sections; served post-restart. |
| L3 | Visual render | **operator-confirm** | In the room **Climate & Fans** step, expand "Advanced — Humidity Spike Tuning" + "Climate Backstop" — headers + fields show friendly labels. |
