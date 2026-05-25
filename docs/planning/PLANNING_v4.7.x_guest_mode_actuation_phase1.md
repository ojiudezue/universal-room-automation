# PLANNING v4.7.x — Guest Mode Actuation Phase 1 (HVAC Preset Range Overrides)

**Status:** Plan ready for build
**Tier:** Tier 2 feature cycle (new shared schema; new sensor; options-flow changes across CM + Zone Manager; multi-coordinator surface area; touches HVAC preset apply path).
**Predecessor:** v4.6.2.2 (Guest Mode detection hardening — house_state machine already emits `guest` reliably).
**Companion plan (parallel):** `PLANNING_v4.7.x_dynamic_preset_management.md` will consume the schema defined here. This plan OWNS the schema and composition rule.
**Version:** user to assign.

## 1. Tier classification

Tier 2 (not Tier 2-DB). Justification:
- Touches `database.py`? No.
- Migrates ≥3 callers to a new DAO? No.
- Changes payload of a dispatched event or persisted record? No — overrides live in `config_entry.options`, not the DB.
- Adds behavioral test infra against real schemas? No.

Two independent staff-engineer reviews with different framings (Core A = correctness/edge cases/None handling, Core B = race conditions / restart / lifecycle / cross-coordinator). Tag `pre-review-v<version>` before applying any review fixes.

## 2. Goal + Why

**User's concrete ask (2026-05-15):** Back Hallway `home` preset narrows from 70–77 °F to **70–75 °F** when house state is `guest`. `sleep` and `away` unchanged. Generalize as per-(zone, preset) override tables so the user can tune any cell.

**Framework value:** The house_state machine has emitted `guest` reliably since v4.6.2.2 but URA does nothing with it. Phase 1 establishes the shared override schema, ships HVAC as the first opt-in coordinator, and proves the framework. Phase 2+ (lighting circadian suppression, music-following disable, NM routing, etc.) reuse the same schema and composition machinery without re-design.

**Why now:** Dynamic Preset Management (weather-forecast-driven daily range adjustment, file already in flight as `PLANNING_v4.7.x_dynamic_preset_management.md`) requires the SAME per-(zone, preset, range) override surface. Shipping Guest Mode Phase 1 first establishes the contract; weather layers on after.

## 3. Discovery — read before build (mandatory for builder)

- `custom_components/universal_room_automation/domain_coordinators/hvac.py`
  - `_apply_house_state_presets` (~line 663) — the call site that issues `climate.set_preset_mode`. **This method does NOT call `set_temperature` today; it relies on the thermostat's stored preset range.** New code must add an explicit `set_temperature(target_temp_high, target_temp_low)` call when an override is active for `(zone_id, effective_preset)`.
  - Verify the suppress/unsuppress dance around `OverrideArrester` so the new `set_temperature` call is also wrapped — otherwise the arrester will read URA's range change as a manual override.
- `domain_coordinators/hvac_preset.py` — `PresetManager.get_seasonal_setpoints(preset, season)` returns the BASELINE `(cool, heat)` tuple from `SEASONAL_DEFAULTS`. This is the canonical "before overrides" reference the engine asks for.
- `domain_coordinators/hvac_const.py` lines ~278–313 — `SEASONAL_DEFAULTS` (house-wide, per-season, per-preset) and `HOUSE_STATE_PRESET_MAP` (`"guest": "home"`). The override layer composes ON TOP OF the season×preset baseline; it does not replace it.
- `domain_coordinators/hvac_zones.py` lines ~213–300 — `async_discover_zones`. Zones are configured under the `ENTRY_TYPE_ZONE_MANAGER` entry's `zones` dict, keyed by zone name. **This is the natural attach point for per-(zone, preset) overrides.**
- `domain_coordinators/presence.py` — `_house_state` field and `SIGNAL_HOUSE_STATE_CHANGED` dispatch. HVAC already subscribes via `_handle_house_state_changed` and reads `self._house_state`. The OverrideEngine reads house_state from HVAC's local field; no new signal required.
- `config_flow.py` — locate the `coordinator_hvac` step (CM-level) and the Zone Manager zone-edit step. Schema lives on Zone Manager (per-zone). Master toggle (`guest_mode_actuation_enabled`) and global precedence config live on CM.
- `quality/QUALITY_CONTEXT.md` Bug Classes #1 (stale data source), #19 (untracked background tasks), #21 (`dt_util.utcnow` discipline), #22 (enum mismatch), #28 (untracked input fields), #32 (form field with no runtime reader), #33 (sibling helpers skipped), #34 (function-local import shadowing module name).
- `docs/planning/PLANNING_v4.5.10_hvac_runtime_tunables_and_labels.md` — pattern for new CONFs threading CM-step → __init__ → constructor → sub-controller → decision site. Reuse exactly.
- `docs/planning/PLANNING_v4.5.9_hvac_cover_intent.md` — pattern for per-room opt-out CONF (`CONF_COVER_HVAC_MANAGED`). Reuse for per-zone opt-out.
- `docs/BACKLOG.md` "Guest Mode Actuation" entry — the long-form list of Phase 2/3 candidates (lighting, music, NM, energy, security, Bayesian, covers).

## 4. Schema design

### 4.1 Where overrides live

**Per-zone overrides** attach to each entry in the Zone Manager entry's existing `zones: dict[zone_name, zone_cfg]` structure. Adding a new key `preset_overrides` to each `zone_cfg`:

```yaml
zones:
  Back Hallway:
    zone_thermostat: climate.back_hallway
    zone_rooms: [<room_entry_id>, ...]
    zone_persons: [...]
    zone_cameras: [...]
    preset_overrides:
      - source: guest_mode
        preset: home
        cool_low: 70
        cool_high: 75
        priority: 50
    guest_mode_actuation_enabled: true
```

### 4.2 Override record shape

| Field | Type | Required | Meaning |
|---|---|---|---|
| `source` | str enum | yes | Override producer: `guest_mode`, `weather_forecast`, `vacation`, `manual` (reserved) |
| `preset` | str enum | yes | One of `home` / `sleep` / `away` / `vacation` |
| `cool_low` | float | optional | Lower bound of cooling target range, °F |
| `cool_high` | float | optional | Upper bound of cooling target range, °F |
| `heat_low` | float | optional | Reserved; not exposed in Phase 1 UI |
| `heat_high` | float | optional | Reserved; not exposed in Phase 1 UI |
| `priority` | int | yes | Higher wins. `guest_mode`=50, `weather_forecast`=30, `vacation`=70, `manual`=100 |
| `active_when` | predicate id | reserved | Phase 1 only uses `guest_mode` predicate ("house_state == 'guest'") |

A `None` field means "this source has no opinion on this dimension" — composition falls through.

### 4.3 Full example: Back Hallway under guest mode

Season = summer. `SEASONAL_DEFAULTS["summer"]["home"]` = `(77, 70)`. Baseline = 70–77.

```python
preset_overrides = [
    {"source": "guest_mode", "preset": "home", "cool_high": 75.0, "priority": 50},
    {"source": "guest_mode", "preset": "sleep", "priority": 50},  # identity / no-op
]
```

Resolved when `house_state == "guest"` and `effective_preset == "home"`:

| Field | Baseline | guest_mode override | Composed |
|---|---|---|---|
| `target_temp_low`  | 70 | (none) | 70 |
| `target_temp_high` | 77 | 75 | 75 |

URA then issues `climate.set_temperature(entity_id=climate.back_hallway, target_temp_low=70, target_temp_high=75)` after `set_preset_mode(home)`.

### 4.4 Schema invariants (form-save AND runtime)

1. `cool_low <= cool_high - MIN_DEADBAND` (`MIN_DEADBAND = 2.0 °F`)
2. `cool_low >= 60 and cool_high <= 90` (sanity)
3. `preset ∈ {home, sleep, away, vacation}`
4. At most ONE override per `(source, preset)` per zone
5. Form rejects save if resolved composition violates #1

## 5. Deliverables

### D1 — Schema + `OverrideEngine` module

Create `custom_components/universal_room_automation/domain_coordinators/preset_overrides.py`:
- `@dataclass PresetOverride` with §4.2 fields
- `class OverrideEngine`:
  - `get_active_overrides(zone_id, preset, context) -> list[PresetOverride]`
  - `resolve_range(baseline, overrides) -> ResolvedRange`
  - `describe_active(zone_id, preset, context) -> list[dict]` (for D4)
- New CONFs in `const.py`: `CONF_GUEST_MODE_ACTUATION_ENABLED` (CM), `CONF_PRESET_OVERRIDES` (per-zone), `CONF_ZONE_GUEST_MODE_OPT_OUT` (per-zone)

**Acceptance**
- **Verify:** Unit test with Back Hallway override → `get_active_overrides("Back Hallway","home",ctx(house_state="guest"))` returns 1 record; `ctx(house_state="home_day")` returns 0
- **Verify:** `resolve_range((70,77),[guest_override(cool_high=75)])` → `ResolvedRange(70,75,sources={"cool_high":"guest_mode"})`
- **Test:** `test_override_engine_filters_by_house_state`, `test_override_engine_returns_baseline_when_no_overrides`, `test_resolve_range_partial_override_preserves_baseline`, `test_master_disable_short_circuits`, `test_zone_opt_out_short_circuits`

### D2 — HVAC preset apply path emits `set_temperature`

Modify `hvac.py:_apply_house_state_presets`:
1. Build `OverrideContext(house_state=self._house_state, now=dt_util.utcnow())`
2. `overrides = self._override_engine.get_active_overrides(zone_id, effective_preset, ctx)`
3. `baseline = self._preset_manager.get_seasonal_setpoints(effective_preset)`
4. `resolved = self._override_engine.resolve_range(baseline, overrides)`
5. Issue `set_preset_mode` as today (preserves UI clarity)
6. If `resolved != baseline_as_resolved`, also issue `climate.set_temperature(entity_id, target_temp_low=..., target_temp_high=...)`
7. Wrap both in `self._override_arrester.suppress(climate_entity)`
8. Always re-emit on `house_state` change (don't rely on thermostat-stored preset memory) — ecobee may persist override values into the named preset; restoring baseline on exit avoids drift
9. Throttle via `self._last_emitted_range: dict[zone_id, tuple[float,float]]` — skip when resolved range matches last-emitted

**Acceptance**
- **Verify:** Fire `SIGNAL_HOUSE_STATE_CHANGED({"new_state":"guest"})` → log contains `set_preset_mode(home)` + `set_temperature(target_temp_low=70, target_temp_high=75)` on `climate.back_hallway`, arrester suppressed+released
- **Verify:** Fire `{"new_state":"home_day"}` → next cycle re-emits `set_temperature(70, 77)` (baseline restored)
- **Verify:** Unchanged decision cycle does NOT re-emit
- **Sensor:** `sensor.ura_hvac_zone_<zone>_active_preset_range_high` updates to 75 when guest, 77 otherwise
- **Test:** `test_hvac_apply_emits_set_temperature_when_override_active`, `test_hvac_apply_skips_when_no_override`, `test_hvac_apply_restores_baseline_on_exit`, `test_hvac_apply_arrester_suppressed`, `test_hvac_apply_throttles_unchanged_range`
- **Live:** Trigger guest mode; observe `climate.back_hallway` `target_temp_high` 77→75 in HA logbook within 1 decision cycle (≤5 min). Exit guest → 75→77.

### D3 — CM master toggle + Zone Manager per-zone overrides UI

CM coordinator-manager options:
- `CONF_GUEST_MODE_ACTUATION_ENABLED` (bool, default True)

Zone Manager zone-edit step:
- `CONF_ZONE_GUEST_MODE_OPT_OUT` (bool, default False)
- 4 form fields per zone: `guest_home_cool_low`, `guest_home_cool_high`, `guest_sleep_cool_low`, `guest_sleep_cool_high` — blank = no override on that dim
- Validation per §4.4
- `strings.json` + `translations/en.json` entries

**Acceptance**
- **Verify:** CM options shows master toggle, round-trips
- **Verify:** Setting Back Hallway home_cool_high=75 produces §4.3 list in entry.options
- **Verify:** Saving home_cool_low=80, home_cool_high=75 rejected with "Cool low must be ≤ cool high − 2°F"
- **Test:** `test_cm_options_master_toggle_round_trip`, `test_zm_zone_options_override_round_trip`, `test_zm_zone_options_validation_rejects_inverted_range`, `test_zm_zone_options_blank_fields_produce_empty_overrides`

### D4 — `sensor.ura_active_preset_overrides` (diagnostic)

New sensor on CM device:
- State: integer count of active override records across all zones for current preset
- Attributes:
  - `by_zone`: `{zone_id: [{preset, source, cool_low, cool_high, ...}, ...]}` filtered to currently-active
  - `house_state`, `master_enabled`
  - `resolved_ranges`: `{zone_id: {"cool_low":.., "cool_high":.., "sources": {"cool_high":"guest_mode"}}}`

The "why is my Master capped at 74°F right now" debug surface.

**Acceptance**
- **Verify:** State 0 when house_state=home_day, ≥1 when guest (any zone has override)
- **Verify:** `by_zone["Back Hallway"]` lists guest_mode override with `cool_high=75`
- **Verify:** `resolved_ranges["Back Hallway"]["sources"]["cool_high"]=="guest_mode"`
- **Test:** `test_active_overrides_sensor_state_count`, `test_active_overrides_sensor_attributes_shape`, `test_active_overrides_sensor_clears_when_master_disabled`, `test_active_overrides_sensor_updates_on_house_state_change`

### D5 — Tests + source-contract regressions

New `quality/tests/test_v47x_guest_mode_actuation_phase1.py`:
- All unit tests from D1–D4
- Source-contract (Bug Class #32): AST-grep that each new CONF has a runtime reader
- Import-resolves (Bug Class #34): new module imports cleanly from `hvac.py`, `config_flow.py`, `sensor.py`
- Regression: confirm v4.6.2.2 guest-gate behavior unchanged

## 6. Override composition rule (decided)

**Rule: per-field highest-priority-wins, narrowest-range tiebreak.**

Algorithm in `OverrideEngine.resolve_range(baseline, overrides)`:
1. Init `resolved` from baseline; `sources = {field: "baseline"}`
2. For each field independently:
   - Candidates = `[(p, value, source) for ov in overrides if getattr(ov, field) is not None]`
   - Empty → keep baseline
   - Else max by priority; ties → narrowest (lower for `*_high`, higher for `*_low`); still tied → alphabetical source
3. Validate composed result against §4.4 #1; on violation log WARNING + baseline fallback

**Priorities shipped Phase 1:** `manual`=100, `vacation`=70, `guest_mode`=50, `weather_forecast`=30, `baseline`=0

## 7. Out of scope for Phase 1

Deferred to Phase 2+: lighting, music following, NM, security, energy, Bayesian/routine awareness, cover controller, exact per-zone overrides for SLEEP/AWAY/VACATION, heat dimension UI, time-of-day-conditional overrides, OverrideArrester suppression under guest.

## 8. Open questions

1. Default per-zone override seeds — Phase 1 ships ALL zones with `preset_overrides=[]`; user manually sets Back Hallway. Confirm.
2. Sleep preset under guest — ship UI fields anyway (future tuning) or hide entirely?
3. Heat dimension UI hidden — confirm.
4. Throttle re-emit on every house_state edge but skip steady-state ticks — confirm.
5. Composition tiebreak — narrowest-range matches mental model? Alternative: explicit source-precedence list.
6. Per-zone opt-out vs per-source-per-zone opt-out — Phase 1 per-zone is sufficient?

## 9. Risk register

1. **Arrester false-positive on URA's `set_temperature`.** Mitigation: explicit suppress wrapper in D2; Review B traces every path; AST regression checking `suppress(...)` call exists adjacent to `set_temperature`.
2. **Ecobee preset persistence** — writing `set_temperature` while a named preset is active may overwrite the preset's stored range AT THE THERMOSTAT. Mitigation: D2 always re-emits baseline on exit. **Highest single unknown** — research before shipping; possible fallback: switch to `manual` preset, set_temperature, switch back.
3. **Throttle staleness** — `_last_emitted_range` in-memory; restart mid-guest re-emits (idempotent, acceptable).
4. **Schema migration for existing Zone Manager entries** — new keys absent; defaults-to-empty everywhere; per `project_single_user_no_backcompat` no migration cycle needed.
5. **Composition violating MIN_DEADBAND** — §6 step 3 + defensive WARN + baseline fallback.
6. **Diagnostic sensor cardinality** — fine for Phase 1; revisit when Phase 2 adds 2-3 sources.
7. **CONF naming collision** — verify `CONF_GUEST_MODE_ACTUATION_ENABLED` ≠ v4.6.2.2's `CONF_GUEST_MODE_PERSISTENCE_SECONDS` / `CONF_GUEST_MODE_REQUIRE_CONFIDENCE`.
8. **Bug Class #34** — new `preset_overrides.py` must avoid function-local `DOMAIN` re-import.

## 10. Phasing summary

- **Phase 1 (this plan):** Schema, OverrideEngine, HVAC opt-in, diagnostic sensor, CM master + per-zone UI for home/sleep cooling overrides.
- **Phase 2 (separate Tier 2 cycles per coordinator):** Likely order based on backlog: (a) Arrester suppression under guest, (b) Lighting circadian suppression, (c) Music Following disable, (d) NM routing changes, (e) Cover Controller skips. Each adds per-zone CONF + tests, reuses engine.
- **Phase 3 (Tier 1 visibility):** `guest_minutes_today` attribute, `routine_status.guest_minutes_in_recent_window`, anomaly-detector exclusion of guest periods.
- **Parallel (Dynamic Preset Mgmt):** Adds `source="weather_forecast"`. Composes via this engine.

## 11. File touch list

- `const.py` — +3 CONF + defaults
- `domain_coordinators/preset_overrides.py` — NEW (~200 LoC)
- `domain_coordinators/hvac.py` — `_apply_house_state_presets` mods, `_last_emitted_range`, constructor wiring (~80 LoC delta)
- `config_flow.py` — CM master + ZM zone-edit fields + validation (~80 LoC)
- `sensor.py` — `ActivePresetOverridesSensor` on CM device (~80 LoC)
- `__init__.py` — singleton `OverrideEngine` in `hass.data[DOMAIN]["override_engine"]`; pass to HVAC ctor (~20 LoC)
- `strings.json` + `translations/en.json` — labels + helper text (~30 LoC)
- `quality/tests/test_v47x_guest_mode_actuation_phase1.py` — NEW (~350 LoC)

**Estimated:** ~470 prod LoC + ~350 test LoC across ~9 files.

## 12. Tier 2 review framings

- **Review A (correctness + edge cases):** composition matrix; None handling on optional override fields; `set_temperature` payload shape verified (`target_temp_low/_high`); validation enforced at form-save AND runtime; baseline restoration on `guest→home_day`; defaults preserve v4.6.x behavior; Bug Class #32 source-contract for every CONF.
- **Review B (async + lifecycle + race conditions):** arrester suppress/release symmetry; `_last_emitted_range` lifecycle (clear on unload, on house_state change, on master flip); HA restart mid-guest behavior; concurrent `_handle_house_state_changed` + scheduled decision reentrancy (existing `_decision_cycle_lock`); Bug Class #19 (no untracked tasks); Bug Class #34 (no module-name shadowing).

## 13. Live validation post-deploy

1. New sensor exists on CM device, state=0, attributes shape per D4
2. Set Back Hallway guest home_cool_high=75 via UI; reload; entry options match §4.3
3. Simulate guest mode → within 1 decision cycle:
   - HA logbook: `set_preset_mode(home)` + `set_temperature(target_temp_high=75, target_temp_low=70)` on `climate.back_hallway`
   - Sensor state ≥ 1; `by_zone["Back Hallway"]` includes override; `resolved_ranges["Back Hallway"]["cool_high"]==75`
4. Exit guest → next cycle: `set_temperature(target_temp_high=77, target_temp_low=70)` (baseline restored); sensor → 0
5. Toggle master OFF, re-trigger guest → no `set_temperature`; sensor stays 0
6. Toggle zone opt_out ON, master ON, guest active → no `set_temperature` on opted-out zone; others actuate
7. HVAC log shows NO arrester "user override detected" entries attributed to URA's `set_temperature`

## 14. Acceptance criteria summary

Release is "done" when:
- All v4.7.x tests pass; isolation check 0 failures
- Tier 2 review docs in `docs/reviews/code-review/v<version>_guest_mode_actuation_phase1_A.md` and `_B.md`; CRITICAL/HIGH fixed
- Live validation §13 passes on user's HA
- `sensor.ura_active_preset_overrides` reflects guest_mode override during guest, clears on exit, respects master + opt-out
- `climate.back_hallway` `target_temp_high` transitions 77 ↔ 75 with house_state
- Defaults preserve all existing zones' behavior — no zone changes range without explicit override
- README_v<version>.md describes user-visible changes
- BACKLOG.md "Guest Mode Actuation" entry updated: Phase 1=SHIPPED + Phase 2 menu of next opt-ins
