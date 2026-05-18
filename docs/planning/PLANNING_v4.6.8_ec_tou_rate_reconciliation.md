# PLANNING v4.6.8 — EC TOU Rate Reconciliation + Zone/House Cost Surface

**Status:** Approved, ready to build (2026-05-18)
**Tier:** Tier 1 (hotfix-shaped, single review, no schema change, no DAO change)
**Predecessor:** v4.6.7 (anomaly_log NULL relaxation)
**Recall hint:** "Resume v4.6.8 — EC TOU rate reconciliation"

---

## TL;DR

Five things in one tight cycle:

1. **Migrate every cost calculation** from static `CONF_ELECTRICITY_RATE` to the Energy Coordinator's live TOU-aware rate (`current_effective_rate`), with the static rate as a clean fallback.
2. **Delete the dead sync TOU JSON loader** (production has been async via `async_from_json_file` since v4.0.5; the sync fallback was never reachable in prod).
3. **Reword the `electricity_rate` UI labels** at every config-flow entry point so users see this field as a fallback, not the primary mechanism.
4. **Fix a small dormant bug:** the house-level realized-cost sensors (`EnergyCostPerOccupiedHourSensor`, `MostExpensiveCircuitSensor`, `OptimizationPotentialSensor`) currently use a hardcoded `0.1 $/kWh` fallback if EC's `tou_engine` is briefly absent. Replace with the proper static-config fallback.
5. **Add three missing cost sensors:** `ZoneEnergyCostTodaySensor`, `ZoneCostPerHourSensor`, `WholeHouseCostTodaySensor` — close gaps on zone and house surfaces.

Retires three stale BACKLOG.md entries on the way out.

---

## Origin

- Audit during 2026-05-18 roadmap cleanup revealed `aggregation.py` D entry ("stub energy/cost prediction sensors") was already shipped in v4.2.27 — only the TOU-aware rate migration (E) remained open.
- Same audit found three house-level sensors that already migrated to EC's `tou_engine` but with a hardcoded `0.1` fallback (silently reports wrong cost when EC briefly unavailable).
- Same audit found zero zone-cost sensors despite zone energy + zone power sensors existing.
- Same audit found no `WholeHouseCostTodaySensor` — the realized-cost surface at the house level was missing entirely, leaving only EC's Envoy-derived `cost_today` (parallel accounting path).
- User decision (2026-05-18): label clarification because "if we're going to keep static rate fallback, and right away it is possible for us to exit the TOU at some point, in the rooms we should update the labels to show that any static rate input is just a fallback and not the primary mechanism."

---

## Deliverables

### D1: TOU async cleanup

**What:** Delete dead sync TOU JSON loader path.

**Sites:**
- `custom_components/universal_room_automation/domain_coordinators/energy_tou.py:84-94` — delete `from_json_file` classmethod
- `custom_components/universal_room_automation/domain_coordinators/energy.py:134-140` — collapse the `if tou_engine is not None` branch (always pre-loaded in production)
- `energy_tou.py:54` — remove "blocking I/O" caveat from `_read_json_file` docstring; async wrapper is the only path

**Why now:** Per `feedback_single_user_no_backcompat` memory — URA has one install, no need to maintain dead fallback paths. Closes the BACKLOG bug #2 ("Energy TOU blocking I/O").

### Acceptance Criteria D1
- **Test:** `test_tou_engine_sync_loader_removed` — `assert not hasattr(TOURateEngine, 'from_json_file')`
- **Test:** `test_energy_coordinator_requires_tou_engine` — instantiating `EnergyCoordinator(tou_engine=None)` raises `TypeError` or `ValueError` (no silent sync fallback)
- **Live:** No HA log warnings about blocking I/O on event loop from `energy_tou.py` post-restart

---

### D2: Unified rate helper `_get_effective_rate_kwh()`

**What:** A single helper function that returns `(rate, source)` — used by every cost calculation in the codebase.

**Behavior:**
```python
def _get_effective_rate_kwh(hass, *, room_entry=None) -> tuple[float, str]:
    """Return (rate_$/kWh, source) — EC TOU when configured, static fallback otherwise.
    
    Resolution order:
    1. EC's current_effective_rate (TOU-aware) → (rate, "ec_tou")
    2. Room entry's CONF_ELECTRICITY_RATE override (if room_entry given) → (rate, "static_config")
    3. Global integration CONF_ELECTRICITY_RATE → (rate, "static_config")
    4. DEFAULT_ELECTRICITY_RATE → (rate, "static_config")
    """
```

**Location:** New helper in `custom_components/universal_room_automation/domain_coordinators/energy_billing.py` (or a new tiny `rate_helpers.py` module — builder's call). Importable from both `sensor.py`, `coordinator.py`, and `aggregation.py`.

**Critical:** Never return `0.1` as a magic fallback. The current `0.1` hardcoded in aggregation.py sites 6/7/8 is replaced by this helper.

### Acceptance Criteria D2
- **Test:** `test_effective_rate_returns_ec_when_configured` — mock EC with `current_effective_rate=0.21`, helper returns `(0.21, "ec_tou")`
- **Test:** `test_effective_rate_falls_back_to_room_override` — no EC, room entry has `electricity_rate=0.15`, helper returns `(0.15, "static_config")`
- **Test:** `test_effective_rate_falls_back_to_global_then_default` — no EC, no room override → global; no global → `DEFAULT_ELECTRICITY_RATE`; both with source `"static_config"`
- **Test:** `test_effective_rate_never_returns_0.1_magic_number` — exercise EC-missing path, assert returned rate != 0.1 (or matches DEFAULT_ELECTRICITY_RATE, whichever)

---

### D3: Migrate 8 existing cost calculation sites

**Sites (verified via 2026-05-18 audit):**

| # | File:Line | Sensor | Current rate path | After |
|---|---|---|---|---|
| 1 | `sensor.py:633-637` | `EnergyCostTodaySensor` (room) | `config.get(CONF_ELECTRICITY_RATE)` | `_get_effective_rate_kwh(hass, room_entry=entry)` |
| 2 | `coordinator.py:2113-2120` | `STATE_ENERGY_COST_WEEKLY`, `_MONTHLY`, `STATE_COST_PER_HOUR` (room) | `self._get_electricity_rate()` | Same helper |
| 3 | `aggregation.py:1865, 1904` | `PredictedCostTodaySensor` | `self._get_config(CONF_ELECTRICITY_RATE)` | Same helper (global scope, no room override) |
| 4 | `aggregation.py:1968` | `PredictedCostWeekSensor` | Same | Same |
| 5 | `aggregation.py:2032` | `PredictedCostMonthSensor` | Same | Same |
| 6 | `aggregation.py:2456-2461` | `EnergyCostPerOccupiedHourSensor._get_rate()` | `ec.tou_engine.get_effective_import_rate()` else `0.1` | Helper (which delegates to `current_effective_rate` then static, no magic) |
| 7 | `aggregation.py:2542-2562` | `MostExpensiveCircuitSensor._get_circuits()` | Same `0.1` fallback at line 2550 | Same fix |
| 8 | `aggregation.py:2599-2633` | `OptimizationPotentialSensor.native_value` / `extra_state_attributes` | Same `0.1` fallback at lines 2611, 2631 | Same fix |

**Implementation note:** `coordinator.py:_get_electricity_rate()` (line 795) can stay as a thin wrapper that calls the new helper with the room's entry, preserving any code that calls it.

**Attribute change:** Sensors that surface `rate_source` in `extra_state_attributes` must reflect actual source — `"ec_tou"` when live, `"static_config"` when fallback. Today three sensors already expose `rate_source` (`PredictedCostToday/Week/Month`); make sure it's accurate after migration. Adding `rate_source` to sites 6/7/8 is optional but encouraged for visibility.

### Acceptance Criteria D3
- **Test:** `test_room_cost_today_uses_ec_rate_when_configured` — site 1
- **Test:** `test_room_cost_weekly_monthly_uses_ec_rate` — site 2
- **Test:** `test_predicted_cost_uses_ec_rate_when_configured` — sites 3-5
- **Test:** `test_house_cost_per_hour_uses_static_fallback_when_ec_unavailable` — sites 6-8 (assert rate is NOT 0.1; matches `DEFAULT_ELECTRICITY_RATE`)
- **Live:** `sensor.universal_room_automation_predicted_cost_today` attribute `rate_source` shows `"ec_tou"` post-restart (EC is live in user's install)
- **Live:** When TOU period rolls peak → off-peak, `sensor.<room>_energy_cost_today` value reflects the new rate within one update cycle
- **Live:** `sensor.universal_room_automation_energy_cost_per_occupied_hour` does NOT report a value implying 0.1 $/kWh during any startup transient

---

### D4: UI label clarification

**Files:** `custom_components/universal_room_automation/strings.json` AND `custom_components/universal_room_automation/translations/en.json` (mirrored)

**Strings to update (4 surfaces × 2 files = 8 string blocks):**

**1. Top-level home setup (`strings.json:12, 22` + en.json mirror)**
- Label: `"Fallback Electricity Rate ($/kWh)"`
- Description: `"Used only when the Energy Coordinator is not configured. With the Energy Coordinator active, cost calculations use the TOU-aware rate automatically."`

**2. Room config setup (`strings.json:391, 397` + en.json mirror)**
- Label: `"Room Fallback Rate Override"`
- Description: `"Per-room fallback used only when the Energy Coordinator is not configured. With the Energy Coordinator active, room costs follow the live TOU rate and this value is ignored."`

**3. Options flow — global sensors (`strings.json:562, 569` + en.json mirror)**
- Label: `"Default Fallback Electricity Rate ($/kWh)"`
- Description: `"Used only when the Energy Coordinator is not configured. The Energy Coordinator's TOU-aware rate is preferred."`

**4. Options flow — room energy (`strings.json:1419` + en.json mirror)**
- Label: `"Fallback Electricity Rate ($/kWh)"` (no `data_description` block here today — leave structure as-is)

### Acceptance Criteria D4
- **Verify:** All 8 string mutations match exactly between `strings.json` and `translations/en.json`
- **Live:** Re-opening the options flow shows the new labels at every entry point

---

### D5: Two new zone cost sensors

**Sites:** Added to `aggregation.py` in the existing zone-sensor section (after `ZoneEnergyTodaySensor` at line 3247).

**1. `ZoneEnergyCostTodaySensor`** — `sensor.<zone>_energy_cost_today`
```
device_class = MONETARY
unit = "USD"
state_class = TOTAL_INCREASING
icon = mdi:currency-usd
entity_registry_enabled_default = True

native_value = ZoneEnergyTodaySensor.native_value × _get_effective_rate_kwh()[0]
attributes:
  rate_source: "ec_tou" | "static_config"
  rate_used: float
```

**2. `ZoneCostPerHourSensor`** — `sensor.<zone>_cost_per_hour`
```
device_class = MONETARY
unit = "USD/h"
state_class = MEASUREMENT
icon = mdi:currency-usd
entity_registry_enabled_default = True

native_value = (ZoneTotalPowerSensor.native_value / 1000.0) × _get_effective_rate_kwh()[0]
                                                                  # W → kW × $/kWh = $/h
attributes:
  rate_source: "ec_tou" | "static_config"
  rate_used: float
```

**Registration:** Both must be added to the zone-manager sensor list at `aggregation.py:349` and `aggregation.py:425` alongside `ZoneEnergyTodaySensor`.

### Acceptance Criteria D5
- **Test:** `test_zone_energy_cost_today_uses_ec_rate` — verify product `energy × rate` with mocked EC rate
- **Test:** `test_zone_cost_per_hour_tracks_power_and_rate` — verify W→kW conversion + rate product
- **Sensor:** `sensor.<zone>_energy_cost_today` is enabled by default; appears on Zone Manager device
- **Sensor:** `sensor.<zone>_cost_per_hour` is enabled by default; appears on Zone Manager device
- **Live:** After deploy, both sensors return non-None values for at least one zone with `energy_today > 0`
- **Live:** `rate_source` attribute shows `"ec_tou"`

---

### D6: New whole-house realized cost sensor

**Site:** Added to `aggregation.py` near `WholeHouseEnergySensor` (line 2105).

**`WholeHouseCostTodaySensor`** — `sensor.ura_whole_house_cost_today`
```
device_class = MONETARY
unit = "USD"
state_class = TOTAL_INCREASING
icon = mdi:currency-usd
entity_registry_enabled_default = True

native_value = WholeHouseEnergySensor.native_value × _get_effective_rate_kwh()[0]
               (returns None when WholeHouseEnergySensor returns None — i.e., user
               hasn't configured whole_house_energy_sensors)

attributes:
  rate_source: "ec_tou" | "static_config"
  rate_used: float
  source_energy_sensor_count: int  # forwarded from WholeHouseEnergySensor
```

**Registration:** Added to the home-setup sensor list in `aggregation.py` alongside `WholeHouseEnergySensor`. Attaches to the same device (Home Setup / CM).

### Acceptance Criteria D6
- **Test:** `test_whole_house_cost_today_multiplies_energy_by_rate` — mock EnergyToday=10 kWh, rate=0.21, assert cost=2.10
- **Test:** `test_whole_house_cost_today_returns_none_when_energy_unconfigured` — no `whole_house_energy_sensors` config, assert sensor returns None (not 0.0)
- **Sensor:** `sensor.ura_whole_house_cost_today` enabled-by-default; visible on house device
- **Live:** After deploy with EC active, sensor reports a non-None USD value (user has `whole_house_energy_sensors` configured per existing `WholeHouseEnergySensor` working)
- **Live:** `rate_source` attribute shows `"ec_tou"`

---

### D7: Retire stale BACKLOG entries

**Edits to `docs/BACKLOG.md`:**
- Delete bug "2. Energy TOU blocking I/O" (line ~282) — resolved by D1
- Delete entry "D. Stub energy/cost prediction sensors" (line ~311) — shipped in v4.2.27, audit confirmed
- Delete entry "E. Legacy fixed-cost-rate vs EC TOU rate reconciliation" (line ~313) — resolved by D3
- Delete bug "1. Config flow save timeout" (line ~278) — user directive 2026-05-18, treat as solved
- Delete the entire "URA DB Scale Management — ARCHIVED" section (lines 3-19) — user directive 2026-05-18, kill entirely

**New entries to add to `docs/BACKLOG.md`:**

**"House Energy/Cost Accounting Reconciliation"** (Tier 2 investigation, fork)
- Document the two parallel accounting paths: URA's `WholeHouseEnergySensor` (sums user-configured `whole_house_energy_sensors`) vs. EC's `cost_today` / `cost_this_cycle` (computed from Envoy lifetime deltas).
- Investigate why house cost surface has historically been thin/inconsistent.
- Decide canonical path: keep both with documented semantics, OR migrate one to the other.
- Scope question: should `WholeHouseCostTodaySensor` (D6 above) be the canonical realized-cost surface? If so, what happens to EC's `cost_today`?
- Trigger condition: revisit if a downstream feature (utility-meter integration, monthly billing UI, dashboard) needs a canonical figure.

**"AnomalyType discriminator promote"** (Tier 2-DB, active queue per user directive 2026-05-18)
- Move from B7 "ready to ship" sub-spec to a proper queued cycle entry.
- Concrete spec already in BACKLOG line 378 + 435: add `AnomalyType` column to `AnomalyRecord` + `anomaly_log` schema migration. Values: `point_in_time | regime_shift`. Default `point_in_time` for back-compat on existing rows.
- ~50 prod LoC + ~40 test LoC + migration script.
- Tier 2-DB ceremony (3x parallel reviews per CLAUDE.md).

**"Per-metric z-threshold customization"** (deferred, trigger conditions per user directive 2026-05-18)
- Currently `z_threshold` is global per coordinator (HVAC, Security, etc.).
- Promote ONLY when ANY of:
  - User reports an anomaly category flooding alerts (e.g., HVAC override_frequency hits every day even after baseline maturity)
  - Cardinality audit reveals a metric's natural variance is structurally different from its siblings in the same coordinator
  - Tier 3 dashboard surface needs per-metric tuning knobs (UX driving it, not algorithm)
- Estimated cost when promoted: ~80 prod LoC + ~60 test LoC. Tier 2 (touches config flow + options flow per coordinator).

### Acceptance Criteria D7
- **Verify:** Five entries removed from BACKLOG.md as listed
- **Verify:** Three new entries added to BACKLOG.md as listed
- **Verify:** Recommended-priority table at bottom of BACKLOG.md updated to reflect post-v4.6.8 state

---

## Out of scope (explicit)

- **Zone weekly/monthly energy/cost sensors** — no zone-level weekly/monthly state in coordinators today. Adding requires backing-data scaffolding (DB rollup or per-zone state). Not in v4.6.8.
- **Zone predicted energy/cost sensors** — `db.predict_energy()` is whole-house only. Per-zone prediction needs new historical-data scoping in `energy_history`. Cycle in its own right.
- **House weekly/monthly realized consumption + cost** — `WholeHouseEnergySensor` is today-only. Week/month aggregates need backing data (DB rollup or HA `utility_meter` plumbing). Forked into "House Energy/Cost Accounting Reconciliation" investigation.
- **Reconciling EC's `cost_today` vs `WholeHouseCostToday`** — two parallel accounting paths; reconciliation is the forked Tier 2 investigation, not part of v4.6.8.
- **Refactoring sensor.py's room-level `EnergyCostMonthlySensor` / `EnergyCostWeeklySensor` enabled-by-default flags** — those are user-discoverability decisions, separate from this cycle's correctness work.

---

## Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Rate helper imported from many sites — circular import risk | LOW | Put helper in a leaf module (`energy_billing.py` or new `rate_helpers.py`) that doesn't import from sensor / coordinator / aggregation |
| EC briefly unavailable at startup — rate falls back to static | LOW | Helper handles this transparently; tests cover both states |
| Existing rate sources change semantics during migration | MEDIUM | Each site is read-only after migration — verify with grep that no other code path writes to these state slots |
| New zone/house cost sensors register but value stays None forever (silent failure) | MEDIUM | Acceptance criterion D5/D6 "Live: non-None within one cycle" catches this |
| Label changes break user-saved entries with `electricity_rate` config | LOW | Field name is unchanged; only display labels change. Existing entries continue to work. |
| `_attr_entity_registry_enabled_default = True` on new sensors causes 3 new entities to appear unexpectedly | LOW | Documented in release notes; user explicitly asked for visibility |

---

## Total cost

- Production: ~150 LoC
- Strings: ~15 lines × 2 files (strings.json + en.json)
- Tests: ~90 LoC (10 behavioral tests across D1-D6)
- Documentation: BACKLOG.md surgery (~80 line edits)
- **Tier: 1** (single staff-engineer review)

---

## Review focus areas

Reviewer should adversarially check:

1. **Rate helper edge cases:** EC present but `current_effective_rate` returns 0 or None or raises? `tou_engine` attribute exists but is None? Helper must degrade gracefully to static fallback.
2. **Room override semantics:** `coordinator._get_electricity_rate()` currently checks room override first, then global. Migration must preserve that order when EC is absent.
3. **`rate_source` attribute accuracy:** sensors that surface this attribute must actually reflect what they used in the most recent `native_value` calc (not cached from a previous cycle).
4. **Zone sensor registration:** both new sensors must be added at both `aggregation.py:349` AND `aggregation.py:425` (the two zone-manager sensor list entries — easy to miss one).
5. **WholeHouseCostToday None semantics:** must return None (not 0.0) when source energy is None — pyspsorting tools and HA history charts care about the distinction.
6. **Bug Class #34 (function-local imports):** the helper should not trigger function-local-import patterns; import at module top in each consumer.
7. **Bug Class #19 (untracked background tasks):** N/A for this cycle (no new background tasks).
8. **Bug Class #21 (tz-naive datetime):** ensure any new code uses `dt_util.now()`, not `datetime.now()`.

---

## Ship plan

1. Branch: `feature/v4.6.8-ec-tou-rate-reconciliation`
2. Pre-review tag: `pre-review-v4.6.8`
3. Build all D1-D7 deliverables
4. Run `PYTHONPATH=quality python3 -m pytest quality/tests/ -v`
5. Tier 1 staff-engineer review
6. Address CRITICAL/HIGH findings
7. Re-run tests
8. Deploy via `./scripts/deploy.sh 4.6.8 <summary> <release-notes>`
9. Verify HACS installed_version, restart HA, live validation per acceptance criteria
10. Post-deploy: write review doc at `docs/reviews/code-review/v4.6.8_ec_tou_rate_reconciliation.md`
