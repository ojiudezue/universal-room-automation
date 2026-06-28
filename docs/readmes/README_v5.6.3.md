# URA v5.6.3 — Climate & Fans section labels (collapsed-section strings)

Completes the v5.6.x strings cleanup. The room "Climate & Fans" step wraps its advanced knobs in two HA `section()` blocks — `humidity_fan_advanced` (collapsed: the EMA spike-tuning constants) and `climate_backstop` (the comfort-range temps + thermostat fallback). But `strings.json`/`translations/en.json` had no `sections` block, so when you scrolled/expanded those sections the **section headers and their fields rendered as raw snake_case keys**. v5.6.1 fixed only the top-level field labels.

## What ships (Tier 1)
- **Added a `sections` block** to the climate step in both `strings.json` and `translations/en.json`, both create + options flows:
  - `humidity_fan_advanced` — name "Advanced — Humidity Spike Tuning"; labels + help for Spike Delta (%), Baseline EMA Time-Constant (s), Baseline Mode.
  - `climate_backstop` — name "Climate Backstop (comfort range + thermostat fallback)"; labels + help for Comfort Range Low/High (°F) + Climate/Thermostat Entity (fallback).
- **Moved** `target_temp_heat`/`target_temp_cool`/`climate_entity` labels from the (HA-ignored) top-level `data` into `sections.climate_backstop.data` where they actually render.
- **Parity test extended** to assert `sections` parity (section keys, `name`, `data`/`data_description`) between strings.json and en.json — so a section-label drift is now caught alongside step/menu drift.
- No logic change.

## Live Validation — *(prospective; written back post-restart)*
- **L1 — section labels render:** in the room **Climate & Fans** step, expand "Advanced — Humidity Spike Tuning" and "Climate Backstop" — headers + fields show friendly labels (no raw keys). *(fill observed)*
