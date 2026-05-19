# PLANNING v4.6.12 — Dashboard Aggregator Sensors (Cycle B)

**Status:** Draft 2026-05-19, awaiting approval to build
**Tier:** Tier 1 (no schema, no DAO, no migration; three additive sensor classes — see "Tier justification" below)
**Predecessor:** v4.6.11 (anomaly persistence + polish + Cycle A attribute adds)
**Successor:** v4.6.13 (Cycle C — coordinator telemetry sensor set)
**Recall hint:** "Resume v4.6.12 — dashboard aggregator sensors"
**Audit source:** `docs/planning/DASHBOARD_v5_sensor_audit.md` rows tagged `(c) NEW SENSOR`

---

## TL;DR

Three net-new aggregator sensors on the integration entry, registered alongside the existing whole-house aggregators in `aggregation.py::async_setup_aggregation_sensors`:

1. `ZoneMotionEventCountSensor` — count of zones with motion in the last 5 minutes (`sensor.universal_room_automation_zones_with_motion`).
2. `HouseSystemDemandSensor` — HVAC system demand as a 0–100% value (`sensor.universal_room_automation_hvac_system_demand`).
3. `EnergyGridDemandSensor` — current grid import as a percentage of the configured grid import cap (`sensor.universal_room_automation_energy_grid_demand`).

All three feed the React dashboard's Home, House, HVAC, and Energy tabs. None touch the DB. Total estimated LoC: ~120 production + ~150 test.

---

## Origin

The dashboard sensor audit (`docs/planning/DASHBOARD_v5_sensor_audit.md`) inventoried every concrete value in the P6 prototype. Of ~60 values, ~40 wire directly to existing sensors and ~10 need one-line attribute adds (Cycle A — v4.6.11). The remaining six families need new sensor classes; three of those — the ones below — are blocking the React Home + Energy + HVAC tab live-wiring. The other three families (per-coordinator decision count / override / success-rate sets) land in Cycle C (v4.6.13).

User directive 2026-05-19: build the React tab shells with stubbed data first, then unblock live-wiring with the Python sensor cycles. v4.6.12 = the first of those unblocking cycles.

---

## Tier justification

Per CLAUDE.md § Review Protocol:

- No `database.py` changes.
- No DAO migrations.
- No new dispatched-event payloads.
- No persisted-record shape changes.
- No schema migration follow-on planned.
- No new behavioral test infrastructure against real schemas.

This is the canonical Tier 1 case: three additive read-only sensor classes that pull from in-memory coordinator state and existing HA entity states. Single staff-engineer review against `docs/QUALITY_CONTEXT.md` bug classes is sufficient. Live validation post-deploy still required.

---

## Deliverables — 3 total

### D1 — `ZoneMotionEventCountSensor`

**Goal:** Surface "N zones with recent motion" — feeds the House tab "3 zones with motion" widget and the Home tab activity ribbon.

**Definition:** Count of distinct zones (per `CONF_ZONE`) that contain at least one room whose `_last_motion_time` falls within the last 5 minutes. A zone with no room ever reporting motion is not counted. Window is 5 minutes per the prototype label `<div class="card-sub">motion events · 3 zones</div>` (`p6-light-styled.html:471`).

**Source of truth:** `UniversalRoomCoordinator._last_motion_time` (set at `coordinator.py:1354` on motion / mmWave / occupancy-sensor activity). This is the universal Tier-1 motion-freshness timestamp already used by the failsafe path; it's the right anchor for "zone has recent activity".

**Class shape (sketch — ~35 LoC):**

```python
class ZoneMotionEventCountSensor(AggregationEntity, SensorEntity):
    """Diagnostic sensor: count of zones with motion in the last N minutes.

    v4.6.12: New aggregator sensor for dashboard House tab. Counts DISTINCT
    zones (per CONF_ZONE) where at least one room coordinator's
    `_last_motion_time` is within `ZONE_MOTION_WINDOW_SECONDS` of now.
    """

    _attr_icon = "mdi:motion-sensor"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "zones"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_zones_with_motion"
        self._attr_name = "Zones With Motion"

    @property
    def native_value(self) -> int:
        now = dt_util.utcnow()  # bug class #21
        window = timedelta(seconds=ZONE_MOTION_WINDOW_SECONDS)
        zones_with_motion: set[str] = set()
        for coord in _get_room_coordinators(self.hass):
            last = coord._last_motion_time
            if last is None:
                continue
            # Tolerate naive datetimes from older state (bug class #21)
            if last.tzinfo is None:
                last = last.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            if (now - last) > window:
                continue
            zone = coord.entry.options.get(CONF_ZONE) or coord.entry.data.get(CONF_ZONE)
            if zone:
                zones_with_motion.add(zone)
        return len(zones_with_motion)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # Mirror the same calculation but emit the zone names too, for UI debug
        ...
        return {
            "zones": sorted(zones_with_motion),
            "window_minutes": ZONE_MOTION_WINDOW_SECONDS // 60,
        }
```

**New constant (in `const.py`):**
```python
ZONE_MOTION_WINDOW_SECONDS: Final = 300  # 5 minutes (matches dashboard "Activity (5 min)")
```
Reasoning for constant-not-config: 5 minutes is a UI-coupled definition. If the dashboard ever rewords "5 min" we change both the label and the constant in one cycle. Avoiding premature configurability per `feedback_configurability_clarity`.

**Update cadence:** Inherits the existing 30s polling cadence of all `AggregationEntity` sensors (no dispatcher signal currently fires on motion events, and the dashboard refresh rate is already in this range).

**Edge cases the code must handle:**
- `_last_motion_time = None` for a never-seen room → skip, do not count.
- `_last_motion_time` naive vs aware (bug class #21 — Timezone Naive/Aware Datetime Mix). Use the same `dt_util.utcnow()` + naive-fallback pattern as `coordinator.py:1438` failsafe.
- Room with no zone configured → skip (do not count "zoneless" rooms).
- Two rooms in the same zone both with recent motion → counted once (set semantics).
- Bug class #14 (Config Snapshot Staleness): read `CONF_ZONE` from `entry.options` first then `entry.data` on every call — never cache.

#### Acceptance Criteria D1

- **Test:** `test_zone_motion_count_basic` — 5 mock coordinators across 3 zones with `_last_motion_time` varied (now, 1m ago, 3m ago, 6m ago, None). Expected count = 2 distinct zones (the ones with at least one room < 5m).
- **Test:** `test_zone_motion_count_no_motion_ever` — coordinator with `_last_motion_time = None` is not counted.
- **Test:** `test_zone_motion_count_outside_window` — coordinator with `_last_motion_time = now - 6min` is not counted.
- **Test:** `test_zone_motion_count_dedup_same_zone` — two rooms in the same zone both recently active → counted as 1.
- **Test:** `test_zone_motion_count_naive_datetime_handled` — coordinator with naive `_last_motion_time` does not raise (bug class #21).
- **Test:** `test_zone_motion_count_attrs_window_and_zones` — `extra_state_attributes` returns `{"zones": [...], "window_minutes": 5}`.
- **Verify:** Entity ID = `sensor.universal_room_automation_zones_with_motion`. Unique ID = `universal_room_automation_zones_with_motion`. Device bound to integration device (`(DOMAIN, "integration")`).
- **Verify:** `entity_category = DIAGNOSTIC` (this is a "how many things moved" surface — operationally diagnostic, not user-facing comfort).
- **Live (post-restart):** Walk around the house; within 30s the sensor reflects expected count. Walk away, wait 6m, the count drops back. Cross-check via the `extra_state_attributes.zones` list naming the right rooms' zones.

---

### D2 — `HouseSystemDemandSensor`

**Goal:** "HVAC system demand 64%" on the HVAC tab page header. Communicates "how hard is the HVAC working right now relative to its full capability".

**Critical formula question — RESOLVED BY CODE READ, not fabrication:**

Per `hvac.py:1505–1515` the HVAC coordinator already counts "zones actively heating/cooling" via `zone.hvac_action in ("cooling", "heating")` against `self._zone_manager.zones`. The "active count over total zone count" ratio is the natural in-house definition that maps to existing instrumentation and is what `zone_call_frequency` anomaly observation already measures.

**Adopted formula:**
```
system_demand_percent = (active_zone_count / total_zone_count) * 100
```
where:
- `active_zone_count` = `sum(1 for z in zone_manager.zones.values() if z.hvac_action in ("cooling", "heating"))`
- `total_zone_count` = `len(zone_manager.zones)`

**Why this and not the alternatives:**

| Candidate | Why rejected |
|---|---|
| Sum of zone setpoint deltas / max-possible-delta | No "max-possible-delta" reference exists in the codebase. Would be fabricated. |
| Current kW / nameplate kW per HVAC unit | URA has no nameplate config field; would need new config. Punt to v5.x if user wants it. |
| `ramp_state` weighted sum | Only available on zones with `ac_load_sensor` configured; subset coverage. |
| Active-count / total-count (CHOSEN) | Uses already-instrumented `hvac_action` field, already used in anomaly path at `hvac.py:1511`. Single integer ratio, easy to reason about. Matches "5 zones · cool mode · system demand 64%" prototype subtitle math: 64% ≈ 3.2 / 5 active zones — consistent with the visual. |

**Bucketing for the user-facing description (extra_state_attributes):** 0% idle, 0–33% light, 34–66% moderate, 67–100% heavy. Used in attributes only, not in the integer value.

**Class shape (sketch — ~55 LoC):**

```python
class HouseSystemDemandSensor(AggregationEntity, SensorEntity):
    """Sensor: HVAC system demand — % of zones actively heating/cooling.

    v4.6.12: New aggregator for HVAC tab header. Defined as
    (zones_in_call / total_zones) * 100 using `zone.hvac_action` from the
    HVAC ZoneManager. Returns None if HVAC coordinator is not active or
    there are no zones configured.
    """

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:hvac"
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_system_demand"
        self._attr_name = "HVAC System Demand"

    def _get_hvac_coord(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("hvac")

    @property
    def available(self) -> bool:
        return self._get_hvac_coord() is not None

    @property
    def native_value(self) -> int | None:
        hvac = self._get_hvac_coord()
        if hvac is None:
            return None
        zones = hvac.zone_manager.zones
        total = len(zones)
        if total == 0:
            return None
        active = sum(
            1 for z in zones.values()
            if z.hvac_action in ("cooling", "heating")
        )
        return int(round((active / total) * 100))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        hvac = self._get_hvac_coord()
        if hvac is None:
            return {}
        zones = hvac.zone_manager.zones
        active_names = [
            z.zone_name for z in zones.values()
            if z.hvac_action in ("cooling", "heating")
        ]
        pct = self.native_value or 0
        if pct == 0:
            bucket = "idle"
        elif pct <= 33:
            bucket = "light"
        elif pct <= 66:
            bucket = "moderate"
        else:
            bucket = "heavy"
        return {
            "active_zones": sorted(active_names),
            "active_count": len(active_names),
            "total_zones": len(zones),
            "load_bucket": bucket,
            "formula": "active_zones / total_zones",
        }
```

**Edge cases the code must handle:**
- HVAC coordinator missing / disabled → `available = False`, `native_value = None` (don't return 0; bug class #7 dictates None vs 0 must mean "unconfigured" vs "configured-and-zero").
- Zero zones configured → `None` (do not divide by zero).
- All zones `hvac_action == ""` (offline thermostats) → 0%.
- Bug class #23 (Observation Mode Gating) does NOT apply here — this is a pure read sensor that doesn't act on state. It's safe to report during observation mode.
- Bug class #26 (High-Frequency DB Read from Sensor Platform): no DB reads in this sensor. Confirmed.

#### Acceptance Criteria D2

- **Test:** `test_hvac_demand_all_idle` — 5 zones all `hvac_action = "idle"` → value = 0.
- **Test:** `test_hvac_demand_all_calling` — 5 zones all `hvac_action = "cooling"` → value = 100.
- **Test:** `test_hvac_demand_partial` — 3 of 5 zones cooling → value = 60.
- **Test:** `test_hvac_demand_mixed_directions` — 2 cooling + 1 heating + 2 idle → value = 60 (heating + cooling both count as "calling").
- **Test:** `test_hvac_demand_no_coordinator` — no HVAC coordinator in hass.data → `native_value = None`, `available = False`.
- **Test:** `test_hvac_demand_zero_zones` — empty `zone_manager.zones` → `native_value = None`.
- **Test:** `test_hvac_demand_attrs_bucket_thresholds` — 0% → "idle", 20% → "light", 50% → "moderate", 80% → "heavy".
- **Verify:** Entity ID = `sensor.universal_room_automation_hvac_system_demand`. Unique ID = `universal_room_automation_hvac_system_demand`. Unit `%`. Device bound to integration device.
- **Verify:** `entity_category = None` (user-facing, not diagnostic — appears on HVAC tab header).
- **Live (post-restart):** With at least 2 zones in `hvac_action = "cooling"` (induce via a warm afternoon, or temporarily lower a zone setpoint), sensor shows non-zero. Confirm `extra_state_attributes.active_zones` lists the right zones.

---

### D3 — `EnergyGridDemandSensor`

**Goal:** "Demand 88%" on the Energy tab, showing current grid import as a percentage of the configured grid import cap. Visualizes whether the house is approaching its self-imposed peak-demand ceiling.

**Source of truth — RESOLVED BY CODE READ:**

`EnergyCoordinator._grid_import_cap_kw` (`energy.py:239`) is the configured cap (default 8 kW per `energy_const.py` `DEFAULT_GRID_IMPORT_CAP_KW`). It is set from `CONF_ENERGY_GRID_IMPORT_CAP_KW` (`energy_const.py:336`).

`EnergyCoordinator._grid_import_cap_enabled` (`energy.py:237`) gates whether the cap is active. If disabled, the sensor should return `None` (sensor inert, dashboard renders "—").

Current grid import in kW is already computed inside `EnergyCoordinator._log_energy_history` (`energy.py:1453`) as:
```python
grid_import_kw = max(net_power_w or 0, 0) / 1000.0
```
where `net_power_w` is the EnvoyBattery's `net_power_w` (positive = importing, negative = exporting). We mirror this exactly to avoid divergence from the path that drives anomalies and EV pausing.

**Per `feedback_single_user_no_backcompat`:** the user has one install. We check live whether the grid import cap is configured. If it is (which the user's prototype suggests at `<div class="knob-label">Grid import cap</div>` showing 8.0 kW), the sensor is always-on. If not, it returns None. We do not build a hybrid "show as zero when unset" path.

**No clamping at 100%:** Per brief and `feedback_post_deploy_ordering` "surface excess intentionally" — if current import = 16 kW and cap = 8 kW, the sensor reports 200%. The dashboard renders 100% bar with overflow indicator.

**Class shape (sketch — ~50 LoC):**

```python
class EnergyGridDemandSensor(AggregationEntity, SensorEntity):
    """Sensor: current grid import as percentage of configured grid cap.

    v4.6.12: New aggregator for the Energy tab. Reads
    EnergyCoordinator._grid_import_cap_kw + live grid_import_kw (mirrors
    energy.py:1453). Returns None when cap is not configured or coordinator
    not available (single-user install — see feedback_single_user_no_backcompat).
    Does NOT clamp at 100% — dashboard surfaces excess intentionally.
    """

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:gauge"
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_grid_demand"
        self._attr_name = "Energy Grid Demand"

    @property
    def available(self) -> bool:
        ec = _get_energy_coordinator(self.hass)
        if ec is None:
            return False
        if not getattr(ec, "_grid_import_cap_enabled", False):
            return False
        if getattr(ec, "_grid_import_cap_kw", 0.0) <= 0:
            return False
        return True

    @property
    def native_value(self) -> float | None:
        ec = _get_energy_coordinator(self.hass)
        if ec is None:
            return None
        cap_kw = getattr(ec, "_grid_import_cap_kw", 0.0)
        if cap_kw <= 0 or not getattr(ec, "_grid_import_cap_enabled", False):
            return None
        # Mirror energy.py:1453 — same source-of-truth math
        try:
            net_w = ec._battery.net_power_w  # bug class #30 normalizes units
        except AttributeError:
            return None
        if net_w is None:
            return None
        grid_kw = max(net_w, 0) / 1000.0
        return round((grid_kw / cap_kw) * 100.0, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ec = _get_energy_coordinator(self.hass)
        if ec is None:
            return {}
        cap_kw = getattr(ec, "_grid_import_cap_kw", 0.0)
        cap_enabled = getattr(ec, "_grid_import_cap_enabled", False)
        net_w = getattr(getattr(ec, "_battery", None), "net_power_w", None)
        grid_kw = max(net_w or 0, 0) / 1000.0 if net_w is not None else None
        return {
            "grid_import_kw": round(grid_kw, 3) if grid_kw is not None else None,
            "grid_import_cap_kw": cap_kw,
            "grid_import_cap_enabled": cap_enabled,
            "exporting": net_w is not None and net_w < 0,
        }
```

**Edge cases the code must handle:**
- Energy coordinator missing → `available = False`, value = None.
- Grid import cap disabled in EC config → `available = False`, value = None.
- Cap = 0 kW (config glitch) → don't divide by zero; value = None.
- Currently exporting (net_w < 0) → grid_kw = 0 (per the `max(0, ...)` clamp), value = 0.0%. The `extra_state_attributes.exporting = True` lets the dashboard render an "exporting" badge instead of "0%".
- `net_power_w` not available (Envoy down) → value = None.
- Bug class #30 (Unit-of-Measurement Drift): handled because we use `net_power_w` (already normalized by `EnvoyBattery`) not the raw `net_power` property.

#### Acceptance Criteria D3

- **Test:** `test_grid_demand_zero` — net import 0 W, cap 8 kW → value = 0.0.
- **Test:** `test_grid_demand_at_cap` — net import 8000 W, cap 8 kW → value = 100.0.
- **Test:** `test_grid_demand_double_cap_no_clamp` — net import 16000 W, cap 8 kW → value = 200.0 (no clamping; dashboard surfaces excess).
- **Test:** `test_grid_demand_half_cap` — net import 4000 W, cap 8 kW → value = 50.0.
- **Test:** `test_grid_demand_exporting_returns_zero` — net import = -2000 W → value = 0.0, attrs `exporting = True`.
- **Test:** `test_grid_demand_cap_disabled_returns_none` — `_grid_import_cap_enabled = False` → value = None, `available = False`.
- **Test:** `test_grid_demand_no_coordinator_returns_none` — no EC in hass.data → value = None, `available = False`.
- **Test:** `test_grid_demand_zero_cap_returns_none` — cap = 0 kW → value = None (no div-by-zero).
- **Test:** `test_grid_demand_net_power_none` — battery `net_power_w = None` → value = None.
- **Test:** `test_grid_demand_attrs_complete` — attrs dict has 4 expected keys.
- **Verify:** Entity ID = `sensor.universal_room_automation_energy_grid_demand`. Unique ID = `universal_room_automation_energy_grid_demand`. Unit `%`.
- **Verify:** `entity_category = None` (user-facing).
- **Live (post-restart):** With grid cap enabled at 8 kW and current real-time import of ~1 kW, sensor reads ~12%. Run dryer or oven to push import up; sensor scales accordingly. With cap disabled in EC config, sensor goes unavailable.

---

## Files touched

| File | Change | LoC delta |
|---|---|---|
| `custom_components/universal_room_automation/aggregation.py` | Add 3 sensor classes (D1, D2, D3) + register all three in `async_setup_aggregation_sensors` (~line 199). | ~140 prod |
| `custom_components/universal_room_automation/const.py` | Add `ZONE_MOTION_WINDOW_SECONDS: Final = 300`. | ~3 |
| `quality/tests/test_v4612_dashboard_aggregators.py` | New test file — one class per sensor — using `MockHass` + mock coordinators. | ~150 test |
| `custom_components/universal_room_automation/manifest.json` | Bump version to `4.6.12`. | 1 |
| `docs/readmes/README_v4.6.12.md` | New file describing the cycle, per CLAUDE.md release process. | ~40 |

No changes to:
- `database.py` / DAOs
- `coordinator.py` (read-only access to existing fields)
- `domain_coordinators/hvac.py` (read-only access to `zone_manager.zones`)
- `domain_coordinators/energy.py` (read-only access to `_grid_import_cap_kw` + `_battery.net_power_w`)
- Any signal / dispatcher

---

## Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| **R1: "System demand" formula ambiguity.** Dashboard prototype says "system demand 64%" without defining math. | MEDIUM | Resolved in plan: chose `active_zones / total_zones` because it (a) uses already-instrumented `hvac_action`, (b) matches the anomaly path `zone_call_frequency` math at `hvac.py:1511`, (c) the prototype's "5 zones · system demand 64%" reads as 3.2 of 5 active. Documented in code comment + `extra_state_attributes.formula` so the assumption is visible. If the user wants kW-based system demand later, file a v5.x enhancement — requires new nameplate config. |
| **R2: Duplicate sensor name with existing class.** | LOW | Grep'd: no existing class named `*MotionEventCount*`, `*SystemDemand*`, or `*GridDemand*`. Unique IDs scoped under `{DOMAIN}_` prefix — no collision. |
| **R3: Performance — 30s tick × 3 new sensors × N rooms.** | LOW | D1 iterates room coordinators (existing `_get_room_coordinators`), each iteration is one dict lookup + one datetime comparison. With 31 rooms, ~31 cheap ops every 30s. D2 iterates `zone_manager.zones` (typically 5 zones). D3 reads 2 attributes off EC. Total added work per tick < 1 ms. No DB reads — bug class #26 not applicable. |
| **R4: Bug class #21 timezone naive/aware.** | MEDIUM | D1 explicitly handles naive `_last_motion_time`. D3 doesn't deal with datetimes. D2 doesn't deal with datetimes. Tests cover the naive case in D1. |
| **R5: Bug class #7 None vs 0 confusion.** | MEDIUM | D2 returns None (not 0) when HVAC coordinator missing or zero zones. D3 returns None when cap disabled. Tests cover both. |
| **R6: Bug class #14 stale config snapshot.** | LOW | All three sensors read config / coordinator state on every `native_value` access. No `__init__`-time caching of `CONF_ZONE`, `_grid_import_cap_kw`, or `zone_manager.zones`. |
| **R9: Sensor availability flapping when EC restarts.** | LOW | `available` properties return False when coordinator is missing. After EC reload, sensors transparently pick up the new EC. |
| **R10: `_battery.net_power_w` AttributeError on partial Envoy init.** | LOW | D3 wraps the access in try/except. On AttributeError, returns None — graceful degrade. |

---

## Out of scope (explicit)

Not in v4.6.12, deferred to later cycles:

- **Per-zone HVAC demand sensor.** Per-zone `Demand 42%` rows on the HVAC tab — already implementable via `HouseSystemDemandSensor.extra_state_attributes.active_zones`. If they need dedicated sensors, file as v5.0 dashboard polish.
- **Decisions today / per-coordinator telemetry set.** Cycle C (v4.6.13) territory.
- **Coordinator health summary attribute adds.** Cycle A (v4.6.11) territory.
- **Zone-level energy cost rollup.** Already partially served by `ZoneEnergyCostTodaySensor`.
- **kW-based HVAC system demand.** Requires new nameplate config field per HVAC unit. v5.x enhancement.
- **Dispatcher-driven instant updates.** 30s polling is sufficient; dispatcher upgrade is premature.
- **D1 5-minute window configurability.** Hardcoded constant. If user later asks for configurable window, expose as Number entity per `feedback_configurability_clarity`.

---

## Review plan (Tier 1)

Per CLAUDE.md § Review Protocol Tier 1:

1. **Pre-review baseline tag:** `git tag pre-review-v4.6.12 -m "Pre-review baseline for v4.6.12"`.
2. **Single staff-engineer adversarial review** against `docs/QUALITY_CONTEXT.md` bug classes, with extra weight on:
   - #7 (None vs 0 sentinel hygiene)
   - #14 (Config snapshot staleness)
   - #21 (Timezone naive/aware)
   - #23 (Observation mode gating — confirm NA)
   - #26 (DB reads — confirm absent)
   - #30 (Unit-of-measurement drift — D3)
3. **Fix all CRITICAL/HIGH issues,** re-run tests.
4. **Deploy** via `./scripts/deploy.sh 4.6.12 "Dashboard aggregator sensors (Cycle B)" "..."`.
5. **Live validation:** see Post-deploy validation below.
6. **Post-review doc:** `docs/reviews/code-review/v4.6.12_dashboard_aggregators.md` per CLAUDE.md.

---

## Post-deploy validation

After deploy, verify on the live HA instance via ha-mcp + dashboard:

1. **D1 — zones with motion.**
   - Query `sensor.universal_room_automation_zones_with_motion` state via ha-mcp.
   - State is a non-negative integer ≤ number of configured zones.
   - Walk into one room of a zone with no recent activity → within 60s, sensor count increases by 1.
   - Confirm `extra_state_attributes.zones` lists the active zone's name.
   - Confirm `window_minutes = 5`.

2. **D2 — HVAC system demand.**
   - Query `sensor.universal_room_automation_hvac_system_demand` state.
   - With current outdoor weather mild + no active calls, state ≤ 33 (light bucket).
   - Cross-check `extra_state_attributes.total_zones == len(hvac_zone_manager.zones)`.
   - Force a zone to `hvac_action = "cooling"` (lower setpoint 5°F on one zone) — within 30s, sensor reflects new percentage.

3. **D3 — energy grid demand.**
   - Query `sensor.universal_room_automation_energy_grid_demand` state.
   - With grid cap enabled at 8 kW and night-time light load (~0.5 kW), state ≈ 6%.
   - `extra_state_attributes.grid_import_cap_kw == 8.0`, `grid_import_cap_enabled == True`.
   - Disable grid cap in EC switch entity → sensor goes `unavailable` within 60s.
   - Re-enable → sensor returns.

4. **Regression check:** existing whole-house sensors unchanged in value or attributes.

5. **No new ERROR / WARNING lines** in HA logs related to `aggregation` module within 5 minutes of restart.

---

## Plan completion tracking

After implementation, document in the post-cycle review:
- Did all 3 sensors ship with all listed acceptance criteria green?
- Any deferred items?
- Bug-class findings during review — append to `docs/QUALITY_CONTEXT.md` if any new class emerged.
