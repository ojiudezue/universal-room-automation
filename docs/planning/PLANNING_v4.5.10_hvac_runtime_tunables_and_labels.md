# PLANNING v4.5.10 — HVAC runtime tunables, form-only thresholds, label renames

**Status:** Plan complete, ready to implement
**Tier:** Tier 2 cycle (3 categories of changes touching ≥5 files; runtime behavior change for the 5 form-only items because they were hardcoded → now configurable)
**Predecessor:** v4.5.9.2

## Why

v4.5.9 + v4.5.9.1 + v4.5.9.2 closed the immediate Bug Class #33 third-hit (HVAC cover dispatch tilt-awareness) and the half-shipped UI bits (mode sensor pick block, cover_hvac_managed strings, occupied-cover-close-delta promotion). That cycle surfaced a broader pattern: many HVAC-coordinator behavior values are climate- or comfort-specific and should be user-tunable, but they're hardcoded as module constants. User asked for the audit + fix in one cycle.

Three categories of changes, all in the HVAC Coordinator's surface area:

1. **Runtime sliders** for empirically-tuned values (occupied close threshold, solar-gain temps, manual override duration, banking floor, fan thresholds). User adjusts based on lived experience without reload cycles.
2. **Form-only thresholds** for set-and-forget climate-specific values (solar window hours, banking SOC threshold, pre-cool/pre-heat forecast triggers). These don't get tuned weekly but should be configurable for non-default homes.
3. **Master switch** for the entire solar-gain cover management feature, plus relabels of two opaque switch entities ("Zone Intelligence" → "Per-Zone HVAC Control"; "Zone Sweep" → "Vacancy Auto-Off").

## Scope

### A. Runtime Number entities + form fields (8 items)

| # | UI Name (Device side) | CONF | Range / unit | Default | Notes |
|---|---|---|---|---|---|
| 0 | **Solar Cover Management** | `CONF_HVAC_SOLAR_GAIN_COVER_ENABLED` | switch | True | Master toggle; `CoverController.update()` early-returns when False |
| 1 | **Cover Close Threshold** | `CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA` (existing v4.5.9.2) | 0.5–5.0°F | 2.0 | **Promote** to live Number entity; v4.5.9.2 has form field already |
| 2 | **Cover Close Temp** | `CONF_HVAC_COVER_CLOSE_TEMP` (new) | 75–95°F | 85 | Was `COVER_CLOSE_TEMP` constant |
| 3 | **Cover Open Temp** | `CONF_HVAC_COVER_OPEN_TEMP` (new) | 70–90°F | 80 | Was `COVER_OPEN_TEMP` constant. Validation: must be ≤ Close Temp − 3°F (hysteresis) |
| 4 | **Cover Override Duration** | `CONF_HVAC_COVER_OVERRIDE_HOURS` (new) | 0.5–24 hr | 2 | Was `COVER_MANUAL_OVERRIDE_HOURS` constant |
| 5 | **Solar Banking Cool Floor** | `CONF_HVAC_SOLAR_BANK_FLOOR` (new) | 65–80°F | 72 | Was `SOLAR_BANK_FLOOR` constant. Floor (not target — see plan critique) |
| 6 | **Fan On Threshold** | `CONF_HVAC_FAN_ACTIVATION_DELTA` (existing v3.8.6) | 0.5–5°F | 2.0 | **Promote** to live Number entity; form field already exists |
| 7 | **Fan Off Hysteresis** | `CONF_HVAC_FAN_HYSTERESIS` (existing v3.8.6) | 0.5–5°F | 1.5 | **Promote** to live Number entity |

### B. Form-only additions (5 items, no Number entity)

| # | Form label | CONF | Range / unit | Default | Helper text |
|---|---|---|---|---|---|
| B1 | "Solar Cover Start Hour" | `CONF_HVAC_COVER_SOLAR_START_HOUR` | 6–14 | 13 | "Hour HVAC starts watching for solar-gain conditions. Set earlier (e.g. 11) for east-facing homes; later for west-only." |
| B2 | "Solar Cover End Hour" | `CONF_HVAC_COVER_SOLAR_END_HOUR` | 14–20 | 18 | "Hour HVAC stops solar-gain cover management and reopens HVAC-closed covers. Pair with sunset in your area." |
| B3 | "Solar Banking Battery Threshold" | `CONF_HVAC_SOLAR_BANK_SOC_MIN` | 80–100% | 95 | "Battery state-of-charge above which surplus solar is dumped into thermal banking instead of grid export. Lower = more aggressive banking." |
| B4 | "Pre-Cool Trigger Temp" | `CONF_HVAC_PRECOOL_FORECAST_HIGH` | 80–100°F | 90 | "When tomorrow's forecast high exceeds this, HVAC pre-cools occupied zones before peak hours." |
| B5 | "Pre-Heat Trigger Temp" | `CONF_HVAC_PREHEAT_FORECAST_LOW` | 20–50°F | 35 | "When outdoor temp drops below this in winter, HVAC pre-heats occupied zones before off-peak ends." |

### C. Label-only renames (no CONF/entity_id change)

| Entity | `_attr_name` change | Strings update? |
|---|---|---|
| `HVACZoneIntelligenceSwitch` | "Zone Intelligence" → **"Per-Zone HVAC Control"** | Update strings.json `zone_intelligence_enabled` if it appears in any form step |
| `HVACZoneSweepSwitch` | "Zone Sweep" → **"Vacancy Auto-Off"** | Update strings.json `zone_vacancy_sweep_enabled` form label too |

CONF keys, entity_ids, dashboard tile references all stay the same.

## Out of scope (deferred)

- **Behavior change**: making "Solar Banking Cool Floor" actually a target (per critique #1). Today it's a floor + a -3°F offset on the existing setpoint. Changing to "set absolute target" is a separate cycle if user requests.
- **L2-L7 from v4.5.9 plan** (extended manual override, forecast-aware skip, per-orientation classification, sleep integration, soft-gradient close, heating-season inverse).
- **Per-room runtime promotion** of CONF_OCCUPANCY_TIMEOUT, CONF_SUNRISE_OFFSET, etc. — separate audit if user wants room-level live sliders.
- **Override Arrester** label — the audit candidate noted in v4.5.9.2 README; defer unless user flags as opaque.

## Deliverables

### D1 — Master switch `CONF_HVAC_SOLAR_GAIN_COVER_ENABLED`

- Const + DEFAULT in `hvac_const.py`
- Form field in `coordinator_hvac` step (config_flow.py)
- Read in `__init__.py`, passed to `HVACCoordinator(solar_gain_cover_enabled=…)`
- `HVACCoordinator.__init__` accepts kwarg + forwards to `CoverController`
- New `HVACSolarCoverSwitch` class (parallels `HVACFanControlSwitch`) with `_attr_name = "Solar Cover Management"`
- `CoverController.update()`: early-return when `self._solar_gain_enabled is False`
- Strings + translations
- Tests: switch off → controller no-ops; switch on → existing v4.5.9 logic runs; on/off restore across coordinator-init

### D2 — Promote `OCCUPIED_CLOSE_TEMP_DELTA` to runtime Number entity

- New `HVACOccupiedCoverCloseThresholdNumber` (parallels `OffPeakDrainNumber`)
- Reads/writes `CoverController._occupied_close_delta` directly (live, no reload)
- RestoreEntity-backed
- `_attr_name = "Cover Close Threshold"`
- The existing v4.5.9.2 form field stays as the install-time seed; the Number entity is the runtime source of truth (URA mirror pattern)
- Strings + translations

### D3 — New CONFs + Number entities for items 2–5 (Cover Close Temp / Open Temp / Override Duration / Banking Floor)

For each:
- Const + DEFAULT in `hvac_const.py` (defaults match the existing module constants for backward-compat)
- Form field in `coordinator_hvac` step
- Read in `__init__.py`, passed to `HVACCoordinator(...)` constructor
- `HVACCoordinator.__init__` accepts kwarg + forwards to relevant sub-controller (CoverController for items 2/3/4; HVACPredictor for item 5)
- New Number entity class (4 of them)
- Sub-controller stores as instance attr (`self._cover_close_temp` etc.) and uses instance attr in decision sites instead of module constant
- Module constants stay as DEFAULT references
- Validation: form save handler ensures Cover Open Temp is ≥3°F below Cover Close Temp (hysteresis safety)
- Strings + translations

### D4 — Promote `fan_activation_delta` and `fan_hysteresis` to runtime Number entities

For each:
- Form field already exists (v3.8.6); no const/form changes needed
- New Number entity class (2 of them)
- Reads/writes the runtime field on `FanController` directly (live, no reload)
- `_attr_name = "Fan On Threshold"` / "Fan Off Hysteresis"
- RestoreEntity-backed
- Strings + translations

### D5 — Form-only additions (B1-B5)

For each (5 total):
- Const + DEFAULT in appropriate file (hvac_const.py for B1-B3; hvac_predict.py for B4-B5 — that's where the existing constants live)
- Form field in `coordinator_hvac` step
- Read in `__init__.py`, passed to `HVACCoordinator(...)` constructor
- `HVACCoordinator.__init__` accepts kwarg + forwards
- Sub-controller stores as instance attr; decision sites use instance attr
- Strings + translations
- NO Number entity (config-only, set-and-forget)

### D6 — Label renames

- `HVACZoneIntelligenceSwitch._attr_name = "Per-Zone HVAC Control"`
- `HVACZoneSweepSwitch._attr_name = "Vacancy Auto-Off"`
- Update form-step strings if the corresponding form labels exist (zone_vacancy_sweep_enabled does — see strings.json:851)
- No CONF/entity_id/unique_id changes

### D7 — Tests + docs

- Mirror-style test file `quality/tests/test_v4510_hvac_tunables_and_labels.py`
- Each new CONF: source-contract test asserting end-to-end wiring (Bug Class #32 prevention)
- Each new Number entity: source-contract test asserting it's a NumberEntity + RestoreEntity
- Master switch: behavior tests (off → no-op; on → runs; restore across restart)
- Validation: cover open ≤ close − 3°F enforced
- Renames: source-contract tests for new `_attr_name` values
- Plus regression tests on existing v4.5.6 / v4.5.9 / v4.5.9.x cover behavior (gates still consult intent + occupancy + manual override)
- README_v4.5.10.md describing all 17 user-visible changes
- VibeMemo entry 010 capturing decision trail (link to entries 008 + 009)
- QUALITY_CONTEXT.md update: note Bug Class #32 prevention enforcement (source-contract tests for every new CONF)

## Tier 2 review plan

### Pre-review baseline tag
Tagged `pre-review-v4.5.10` (done before D1 implementation starts).

### Review 1 (Core A — domain logic)
- Each new CONF wired end-to-end (form → __init__ → constructor → instance attr → decision site)
- Each Number entity reads from + writes to the runtime field (not entry.options) — URA mirror pattern compliance
- Master switch early-return is BEFORE other gates so per-room/intent/occupancy don't waste cycles
- Validation logic for Cover Open ≤ Close − 3°F: must enforce on form save, not just runtime (catch bad state at config time)
- Bug class checklist (QUALITY_CONTEXT.md):
  - #1 Stale data source: Number entity reads runtime field, not stale snapshot
  - #28 Untracked input fields: every CONF read at runtime (8 + 5 = 13 new readers)
  - #32 Form field with no runtime reader: source-contract tests assert each
  - #33 Sibling helpers: when threading new CONFs through HVACCoordinator → sub-controllers, every consumer uses instance attr (not module constant)

### Review 2 (Core B — race conditions, restart, lifecycle)
- Master switch toggled OFF mid-window: covers HVAC closed before toggle stay closed (acceptable; user reopens manually)
- Number entity values lost on restart: RestoreEntity covers it; default-to-form-seed fallback for first-install
- Validation: form save with bad Cover Open/Close pair must reject (not silently accept)
- Module constants kept as constructor DEFAULT references — code that constructs sub-controller without kwargs still works (backward-compat)
- Renames: `_attr_name` change doesn't reset state (RestoreEntity keyed on unique_id, not name); existing on/off survives

### Live validation (Review 3, post-deploy)
- After HACS download + restart:
  - URA: HVAC Coordinator device shows 7 new Number entities + 1 new Switch + 2 renamed switches
  - Coordinator Manager → HVAC config step shows 5 new form fields (B1-B5) + new master switch field
  - Solar Cover Management toggle: flip OFF, watch HVAC log "CoverController disabled" + verify no close commands fire on next solar window; flip ON, verify normal behavior resumes
  - Cover Close/Open/Override/Floor Number entities: change values via slider, verify next decision uses the new values (no reload)
  - Form-only B1-B5: change in form, reload, verify new values active in decisions

## Cost

| Component | Effort | LoC |
|---|---|---|
| D1 master switch | 45 min | ~80 |
| D2 OCCUPIED promote to Number | 30 min | ~70 |
| D3 4 new CONFs + Number entities | 2 hr | ~200 |
| D4 2 fan params promote to Number | 45 min | ~120 |
| D5 5 form-only additions | 1.5 hr | ~150 |
| D6 2 label renames | 15 min | ~10 |
| D7 tests | 3 hr | ~400 |
| Strings + translations sync | 30 min | ~60 |
| Docs (planning, review, README, vibememo, QUALITY_CONTEXT) | 1 hr | ~150 |
| **Total** | **~10 hr** | **~1240 LoC** |

## Risks ranked

1. **Validation race**: user submits form with Cover Open Temp = 84 + Cover Close Temp = 85 (only 1°F gap, below the 3°F hysteresis safety). If validated only at runtime, banking can flap. Mitigation: validate at form-save time AND at runtime with a defensive log warning.
2. **RestoreEntity unique_id collisions**: 7 new Number entities. Each must have a globally-unique `_attr_unique_id`. Mitigation: enforce naming convention `f"{DOMAIN}_hvac_{tunable_name}"`; source-contract test checks no two are identical.
3. **Master switch + per-room opt-out interaction**: master OFF should override per-room ON (master is the bigger hammer). Per-room OFF + master ON should still skip per-room. Document the precedence: master gates discovery; per-room gates per-cover during discovery; threshold gates per-decision.
4. **Module constant removal could break old code paths I didn't audit**: keep module constants in place as DEFAULT references and constructor defaults. Sub-controllers default to the module constant if kwarg not provided. This preserves any code that constructs sub-controllers directly (test fixtures, etc.).
5. **Backward-compat for users who don't reconfigure**: defaults must match prior hardcoded values exactly. Tests assert this.

## Acceptance criteria summary

The release is "done" when:
- All v4.5.10 source-contract tests pass; isolation check 0 failures across the suite
- Tier 2 review docs in `docs/reviews/code-review/v4.5.10_*.md` (Review 1 + Review 2)
- 7 new Number entities + 1 new Switch + 2 renamed switches visible on URA: HVAC Coordinator device
- 5 new form fields visible in coordinator_hvac config step
- Master switch live-test: OFF disables CoverController.update(); ON resumes
- Defaults preserve v4.5.9.x behavior (no reconfiguration required for existing users)
- README_v4.5.10.md describes all changes; vibememo entry 010 captures decisions; QUALITY_CONTEXT.md notes the Bug Class #32 prevention enforcement
- Pre-review baseline tag preserved for diff comparison
