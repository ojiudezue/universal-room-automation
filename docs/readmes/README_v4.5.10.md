# v4.5.10 — HVAC runtime tunables, form-only thresholds, label renames

**Date:** 2026-05-10
**Type:** Tier 2 cycle (~1240 LoC across 8 production files; 92 new tests)
**Predecessor:** v4.5.9.2

## Summary

Promotes 7 hardcoded HVAC behavior values to runtime Number entities, adds 5 form-only thresholds for set-and-forget tuning, adds a master switch for the entire solar-gain cover management feature, and renames two opaque entity labels — without touching CONF/entity_id (dashboards safe). Defaults preserve v4.5.9.x behavior exactly.

## What's new

### A. 7 Number entities + 1 Switch on the URA: HVAC Coordinator device

| Device-UI label | Range / unit | What it controls |
|---|---|---|
| **Solar Cover Management** (Switch) | on/off | Master toggle for the entire solar-gain cover management feature. When OFF, no closes / opens fire regardless of per-room or per-decision settings. |
| **Cover Close Threshold** | 0.5–5.0°F | When occupied, how far above setpoint a room must be before HVAC closes its covers (was hardcoded `OCCUPIED_CLOSE_TEMP_DELTA = 2.0`) |
| **Cover Close Temp** | 75–95°F | Outdoor temp at which HVAC starts closing covers for solar gain (was `COVER_CLOSE_TEMP = 85`) |
| **Cover Open Temp** | 70–90°F | Outdoor temp at which HVAC reopens previously-closed covers (was `COVER_OPEN_TEMP = 80`) — must be ≥3°F below Close Temp |
| **Cover Override Duration** | 0.5–24 hr | How long HVAC respects a manual cover touch (was `COVER_MANUAL_OVERRIDE_HOURS = 2`) |
| **Solar Banking Cool Floor** | 65–80°F | Coolest setpoint solar banking will drive zones to (was `SOLAR_BANK_FLOOR = 72`) |
| **Fan On Threshold** | 0.5–5.0°F | Promoted from config-only (v3.8.6) to runtime slider |
| **Fan Off Hysteresis** | 0.5–5.0°F | Same — promoted to runtime |

All Number entities are RestoreEntity-backed → slider value survives restart. Each pushes to its sub-controller's runtime field on every change (no reload required). Form value is install-time seed; slider is runtime source of truth (URA mirror pattern).

### B. 5 form-only fields in Coordinator Manager → HVAC step

| Form label | Range / unit | What it controls |
|---|---|---|
| **Solar Cover Start Hour** | 6–14 | Hour HVAC starts watching for solar conditions (was `COVER_SOLAR_HOUR_START = 13`) |
| **Solar Cover End Hour** | 14–20 | Hour HVAC stops + reopens HVAC-closed covers (was `COVER_SOLAR_HOUR_END = 18`) |
| **Solar Banking Battery Threshold** | 80–100% | SOC above which surplus solar dumps into thermal banking (was `SOLAR_BANK_SOC_MIN = 95`) |
| **Pre-Cool Trigger Temp** | 80–100°F | Forecast-high above which HVAC pre-cools (was `PRECOOL_FORECAST_HIGH = 90`) |
| **Pre-Heat Trigger Temp** | 20–50°F | Outdoor-low below which HVAC pre-heats (was `PREHEAT_FORECAST_LOW = 35`) |

Set-and-forget — no Number entity surface. Reload required to change.

### C. Label-only renames

| Entity (entity_id unchanged) | Old label | New label |
|---|---|---|
| `switch.ura_hvac_coordinator_hvac_zone_intelligence` | "Zone Intelligence" | **"Per-Zone HVAC Control"** |
| `switch.ura_hvac_coordinator_zone_sweep` | "Zone Sweep" | **"Vacancy Auto-Off"** |

Underlying CONF + entity_id + unique_id stay the same → dashboards / automations / templates referring to these entities unaffected.

### Hysteresis validation

Cover Open Temp must be at least 3°F below Cover Close Temp (`COVER_HYSTERESIS_MIN_GAP = 3.0`). Form save rejects invalid pairs with localized error: *"Cover Open Temp must be at least 3°F below Cover Close Temp to prevent solar-gain flapping. Adjust either value and try again."*

## Architecture

### Three-layer gating model for solar-gain cover management

| Layer | Control | Scope | Where set |
|---|---|---|---|
| **Master** | `Solar Cover Management` (CONF_HVAC_SOLAR_GAIN_COVER_ENABLED) | House-wide on/off | HVAC Coordinator device + form |
| **Per-room** | `cover_hvac_managed` (CONF_COVER_HVAC_MANAGED, v4.5.9) | Room-wide opt-out | Per-room cover automation step |
| **Per-decision** | Intent + occupancy + manual override (v4.5.9) | Per-cover-per-cycle | Internal logic |

Master OFF overrides everything. Master ON + per-room OFF skips that room. Master ON + per-room ON evaluates per-decision gates.

### Number entity factory

All 7 Number entities use a single shared factory (`_hvac_tunable_number_factory` in `number.py`). Each invocation is a config dict (~10 lines): suffix, name, icon, sub-controller attr, runtime field, conf key, default, range, step, unit. Modeled on the existing `_ec_switch_factory` pattern (5 EC switches).

### Why label-only renames (no CONF/entity_id change)

Per user direction: a CONF rename + entity_id rename would break dashboard tiles and automation YAMLs that reference the old entity_id. The label-only rename gives 100% of the UI clarity benefit at 0% of the dashboard-breakage cost. Source-contract tests assert unique_id is unchanged so a future contributor can't accidentally rename it.

## Tier 2 Review

Pre-review baseline tagged: `pre-review-v4.5.10`. Two self-reviews + this README's live validation plan = full Tier 2.

| Severity | Total findings |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 1 (factory's setattr cast type — verified consistent across all 7 instantiations) |
| LOW | 6 (all documented as design trade-offs or backward-compat preservation) |

**Verdict: APPROVED for deploy.**

Detailed findings in `docs/reviews/code-review/v4.5.10_review.md`.

## Tests

92 new tests in `quality/tests/test_v4510_hvac_tunables_and_labels.py`:

- **Master switch (5):** class exists, friendly name, registered in setup, early-returns when off, init accepts kwarg
- **Number factory (5):** factory function exists, class inherits correctly, pushes to sub-controller, signal-deferred-push, exactly 7 v4.5.10 Numbers built
- **7 friendly names (parametrized, 7 tests):** each new Number has the right device-UI name
- **Setup wiring (1):** async_setup_entry adds all 7 v4.5.10 Numbers
- **Sub-controller wiring (4):** CoverController has 5 v4.5.10 fields; uses them in update(); HVACPredictor has 4 v4.5.10 fields; uses them at decision sites
- **CONF wiring end-to-end (40 parametrized):** 10 CONFs × 4 layers (defined / in form / read in init / accepted as kwarg)
- **Coord forwards to sub-controllers (1):** CoverController + HVACPredictor receive correct kwargs
- **Validation (3):** validation block present, error string localized, show_form passes errors
- **Renames (5):** Zone Intelligence renamed + unique_id unchanged + Zone Sweep renamed + unique_id unchanged + form label synced
- **Strings + translations (20 parametrized):** 10 CONFs × 2 files (label + helper present in strings.json AND translations/en.json)
- **Backward compat (10 parametrized):** each default matches the prior hardcoded value exactly

**Test count progression:**
- v4.5.9.2: 2070, 0 isolated failures across 58 files
- **v4.5.10: 2162** (+92), 0 isolated failures across 59 files

## Live validation plan (post-restart)

Detailed plan in `docs/reviews/code-review/v4.5.10_review.md` "Live validation plan." Summary:

1. **Immediate post-restart:** URA: HVAC Coordinator device shows 1 new switch + 7 new Number entities with friendly names. 2 renamed switches show new labels. Coordinator Manager → HVAC step shows 10 new form fields. Zero new ERRORs.
2. **Master switch flip-test:** toggle "Solar Cover Management" OFF; next decision cycle: no cover commands. Toggle back ON; behavior resumes.
3. **Number entity live-test:** adjust slider → next decision uses new value (no reload needed). Restart HA → slider value preserved.
4. **Validation reject-test:** set Close=82 + Open=80 → form rejects with localized error.

## Deploy notes

- No DB schema changes
- No migration needed (defaults preserve v4.5.9.x behavior; missing CONF reads as the default)
- HACS download required after deploy.sh
- HA restart required (8 production files touched)

## Documents

- Plan: `docs/planning/PLANNING_v4.5.10_hvac_runtime_tunables_and_labels.md`
- Review: `docs/reviews/code-review/v4.5.10_review.md`
- VibeMemo entry 010 captures decision trail (related to entries 008 + 009)

## Next

- **v4.6.0** — Routine Awareness with reconciled AnomalyEvent foundation
- **Sensor Health Surfacing** (backlog) — chattering + stuck-on detection
- **CM cleanup cycle** — `CONF_MUSIC_FOLLOWING_ENABLED` + `CONF_COMFORT_ENABLED` placeholders
- **Cover livability v2** (backlog) — L2-L7 from v4.5.9 plan: extended manual override, forecast-aware skip, per-orientation classification, sleep integration, soft-gradient close, heating-season inverse
