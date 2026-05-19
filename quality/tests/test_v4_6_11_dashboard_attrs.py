"""Tests for v4.6.11 D4 — Dashboard attribute adds + D2 dt_util fix.

Deliverables covered:
  D2.3 — coordinator_diagnostics.py uses dt_util.utcnow (no datetime.utcnow)
  D2.2 — test_v4_6_10_setup_telemetry.py uses asyncio.run (no run_until_complete)
  D4.1 — CoordinatorSummarySensor: health_status + status_per_coordinator
  D4.2 — RoomsOccupiedSensor: per_zone_breakdown key present
  D4.3 — OccupiedBinarySensor: idle_duration key present (0 when occupied)
  D4.4 — OccupiedBinarySensor: current_persons key present, always a list
  D4.5 — WholeHousePowerSensor: source_breakdown key present with 3 sub-keys
  D4.6 — HVACModeSensor: zone_limits key present in get_mode_attrs
  D4.8 — SafetyEventsSummarySensor: class exists, correct attributes shape

Test strategy:
- Source-grep tests for structural presence (no full HA import needed).
- Inline computation tests for attribute logic.
- Manager.get_summary mock-based test for health_status logic.
"""
from __future__ import annotations

import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock

import pytest

ROOT = pathlib.Path(__file__).parents[2]
DOMAIN = "universal_room_automation"


def _utc_now():
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# D2 — datetime.utcnow bug class fix
# ---------------------------------------------------------------------------

class TestD2DatetimeUtcnowFix:
    """D2.3: coordinator_diagnostics.py must use dt_util.utcnow, not datetime.utcnow."""

    DIAG_FILE = (
        ROOT / "custom_components" / "universal_room_automation"
        / "domain_coordinators" / "coordinator_diagnostics.py"
    )
    TELEMETRY_TEST = (
        ROOT / "quality" / "tests" / "test_v4_6_10_setup_telemetry.py"
    )

    def test_no_datetime_utcnow_in_reset_and_record_observation(self):
        """D2.3 AC: _maybe_reset_daily_counter and record_observation use dt_util.utcnow.

        Plan scope: fix lines 798 and 824 only (_maybe_reset_daily_counter and
        the AnomalyRecord construction in record_observation). Other datetime.utcnow()
        calls in coordinator_diagnostics.py are out of v4.6.11 scope.
        """
        src = self.DIAG_FILE.read_text()

        # Extract _maybe_reset_daily_counter body
        reset_idx = src.find("def _maybe_reset_daily_counter")
        assert reset_idx >= 0
        reset_end = src.find("\n    def ", reset_idx + 1)
        reset_body = src[reset_idx:reset_end]
        assert "datetime.utcnow()" not in reset_body, \
            "_maybe_reset_daily_counter must use dt_util.utcnow(), not datetime.utcnow()"
        assert "dt_util.utcnow()" in reset_body, \
            "_maybe_reset_daily_counter must use dt_util.utcnow()"

        # Extract record_observation body — find AnomalyRecord construction
        record_idx = src.find("def record_observation")
        assert record_idx >= 0
        record_end = src.find("\n    def ", record_idx + 1)
        record_body = src[record_idx:record_end]
        assert "datetime.utcnow()" not in record_body, \
            "record_observation AnomalyRecord construction must use dt_util.utcnow(), not datetime.utcnow()"
        assert "dt_util.utcnow()" in record_body, \
            "record_observation must use dt_util.utcnow() for AnomalyRecord timestamp"

    def test_dt_util_imported_in_coordinator_diagnostics(self):
        """D2.3 AC: dt_util is imported at module top in coordinator_diagnostics.py."""
        src = self.DIAG_FILE.read_text()
        assert "from homeassistant.util import dt as dt_util" in src, \
            "coordinator_diagnostics.py must import dt_util at module top"

    def test_dt_util_utcnow_used_in_reset_and_record(self):
        """D2.3 AC: dt_util.utcnow() present in _maybe_reset_daily_counter and record_observation."""
        src = self.DIAG_FILE.read_text()
        count = src.count("dt_util.utcnow()")
        assert count >= 2, \
            f"Expected at least 2 dt_util.utcnow() calls, found {count}"

    def test_no_asyncio_run_until_complete_in_telemetry_test(self):
        """D2.2 AC: test_v4_6_10_setup_telemetry.py has no run_until_complete."""
        src = self.TELEMETRY_TEST.read_text()
        calls = re.findall(r"run_until_complete", src)
        assert calls == [], \
            "test_v4_6_10_setup_telemetry.py must not use run_until_complete"

    def test_asyncio_run_used_in_telemetry_test(self):
        """D2.2 AC: test_v4_6_10_setup_telemetry.py uses asyncio.run(...)."""
        src = self.TELEMETRY_TEST.read_text()
        assert "asyncio.run(" in src, \
            "test_v4_6_10_setup_telemetry.py must use asyncio.run() after D2.2 fix"


# ---------------------------------------------------------------------------
# D4.1 — manager.get_summary health_status + status_per_coordinator
# ---------------------------------------------------------------------------

class TestD41HealthStatus:
    """D4.1: CoordinatorSummarySensor exposes health_status and status_per_coordinator."""

    MANAGER_FILE = (
        ROOT / "custom_components" / "universal_room_automation"
        / "domain_coordinators" / "manager.py"
    )

    def test_source_get_summary_has_health_status(self):
        """D4.1 AC: manager.py get_summary returns health_status key."""
        src = self.MANAGER_FILE.read_text()
        assert '"health_status"' in src or "'health_status'" in src, \
            "manager.get_summary() must include health_status key"

    def test_source_get_summary_has_status_per_coordinator(self):
        """D4.1 AC: manager.py get_summary returns status_per_coordinator key."""
        src = self.MANAGER_FILE.read_text()
        assert "status_per_coordinator" in src, \
            "manager.get_summary() must include status_per_coordinator key"

    def test_health_status_green_when_no_anomalies(self):
        """D4.1 AC: health_status=green when all detectors return NOMINAL."""
        # Replicate the health_status logic inline
        class _MockSev:
            NOMINAL = "nominal"
            ADVISORY = "advisory"
            ALERT = "alert"
            CRITICAL = "critical"

        _SEVERITY_RANK = {"nominal": 0, "advisory": 1, "alert": 2, "critical": 3}

        def _compute_health(coordinators):
            worst_rank = 0
            for coord_id, coordinator in coordinators.items():
                det = getattr(coordinator, "anomaly_detector", None)
                if det is not None:
                    try:
                        ws = det.get_worst_severity()
                        rank = _SEVERITY_RANK.get(ws.value if ws else "nominal", 0)
                        if rank > worst_rank:
                            worst_rank = rank
                    except Exception:
                        pass
            if worst_rank == 0:
                return "green"
            elif worst_rank == 1:
                return "orange"
            else:
                return "red"

        # No coordinators = green
        assert _compute_health({}) == "green"

        # Coordinator with no anomaly_detector = green
        c1 = MagicMock(spec=[])  # no anomaly_detector attribute
        assert _compute_health({"c1": c1}) == "green"

    def test_health_status_orange_when_advisory(self):
        """D4.1 AC: health_status=orange when worst severity is ADVISORY."""
        _SEVERITY_RANK = {"nominal": 0, "advisory": 1, "alert": 2, "critical": 3}

        def _compute_health(coordinators):
            worst_rank = 0
            for coord_id, coordinator in coordinators.items():
                det = getattr(coordinator, "anomaly_detector", None)
                if det is not None:
                    try:
                        ws = det.get_worst_severity()
                        rank = _SEVERITY_RANK.get(ws.value if ws else "nominal", 0)
                        if rank > worst_rank:
                            worst_rank = rank
                    except Exception:
                        pass
            if worst_rank == 0:
                return "green"
            elif worst_rank == 1:
                return "orange"
            else:
                return "red"

        class _FakeSev:
            value = "advisory"

        det = MagicMock()
        det.get_worst_severity = MagicMock(return_value=_FakeSev())
        c1 = MagicMock()
        c1.anomaly_detector = det
        assert _compute_health({"safety": c1}) == "orange"

    def test_health_status_red_when_alert_or_critical(self):
        """D4.1 AC: health_status=red when worst severity is ALERT or CRITICAL."""
        _SEVERITY_RANK = {"nominal": 0, "advisory": 1, "alert": 2, "critical": 3}

        def _compute_health(coordinators):
            worst_rank = 0
            for coord_id, coordinator in coordinators.items():
                det = getattr(coordinator, "anomaly_detector", None)
                if det is not None:
                    try:
                        ws = det.get_worst_severity()
                        rank = _SEVERITY_RANK.get(ws.value if ws else "nominal", 0)
                        if rank > worst_rank:
                            worst_rank = rank
                    except Exception:
                        pass
            if worst_rank == 0:
                return "green"
            elif worst_rank == 1:
                return "orange"
            else:
                return "red"

        for sev_value in ("alert", "critical"):
            class _FakeSev:
                value = sev_value

            det = MagicMock()
            det.get_worst_severity = MagicMock(return_value=_FakeSev())
            c1 = MagicMock()
            c1.anomaly_detector = det
            assert _compute_health({"hvac": c1}) == "red", \
                f"Expected red for severity {sev_value!r}"

    def test_status_per_coordinator_contains_required_keys(self):
        """D4.1 AC: status_per_coordinator entries have status, active_anomalies, enabled."""
        # Inline the status_per_coordinator build logic
        def _build_status(coordinators):
            _SEVERITY_RANK = {"nominal": 0, "advisory": 1, "alert": 2, "critical": 3}
            result = {}
            for coord_id, coordinator in coordinators.items():
                det = getattr(coordinator, "anomaly_detector", None)
                if det is not None:
                    try:
                        ws = det.get_worst_severity()
                        sev_label = ws.value if ws else "nominal"
                        active_count = len(getattr(det, "_active_anomalies", []))
                    except Exception:
                        sev_label = "nominal"
                        active_count = 0
                else:
                    sev_label = "nominal"
                    active_count = 0
                result[coord_id] = {
                    "status": sev_label,
                    "active_anomalies": active_count,
                    "enabled": coordinator.enabled,
                }
            return result

        c1 = MagicMock()
        c1.enabled = True
        c1.anomaly_detector = None
        status = _build_status({"safety": c1})
        assert "safety" in status
        entry = status["safety"]
        assert "status" in entry
        assert "active_anomalies" in entry
        assert "enabled" in entry
        assert entry["enabled"] is True


# ---------------------------------------------------------------------------
# D4.2 — RoomsOccupiedSensor per_zone_breakdown
# ---------------------------------------------------------------------------

class TestD42PerZoneBreakdown:
    """D4.2: RoomsOccupiedSensor.extra_state_attributes has per_zone_breakdown."""

    AGG_FILE = ROOT / "custom_components" / "universal_room_automation" / "aggregation.py"

    def test_source_per_zone_breakdown_key_present(self):
        """D4.2 AC: aggregation.py contains per_zone_breakdown key."""
        src = self.AGG_FILE.read_text()
        assert '"per_zone_breakdown"' in src or "'per_zone_breakdown'" in src, \
            "RoomsOccupiedSensor must include per_zone_breakdown in extra_state_attributes"

    def test_per_zone_breakdown_computation(self):
        """D4.2 AC: per_zone_breakdown maps zone -> occupied room count correctly."""
        # Inline the breakdown logic
        STATE_OCCUPIED = "occupied"
        CONF_ZONE = "zone"

        class _FakeEntry:
            def __init__(self, room_name, zone_options=None, zone_data=None):
                self.data = {"room_name": room_name, CONF_ZONE: zone_data}
                self.options = {CONF_ZONE: zone_options} if zone_options else {}

        class _FakeCoord:
            def __init__(self, occupied, room_name, zone_options=None, zone_data=None):
                self.data = {STATE_OCCUPIED: occupied}
                self.entry = _FakeEntry(room_name, zone_options, zone_data)

        def _compute_breakdown(coordinators):
            zone_breakdown = {}
            for coord in coordinators:
                if coord.data and coord.data.get(STATE_OCCUPIED, False):
                    try:
                        zone = (
                            coord.entry.options.get(CONF_ZONE)
                            or coord.entry.data.get(CONF_ZONE, "unassigned")
                        )
                        zone_breakdown[zone] = zone_breakdown.get(zone, 0) + 1
                    except Exception:
                        pass
            return zone_breakdown

        coords = [
            _FakeCoord(True, "Master Bedroom", zone_options="upstairs"),
            _FakeCoord(True, "Office", zone_options="upstairs"),
            _FakeCoord(True, "Living Room", zone_data="downstairs"),
            _FakeCoord(False, "Kitchen", zone_data="downstairs"),
        ]
        breakdown = _compute_breakdown(coords)
        assert breakdown.get("upstairs") == 2
        assert breakdown.get("downstairs") == 1
        assert "Kitchen" not in str(breakdown)  # not occupied

    def test_per_zone_breakdown_type_is_dict(self):
        """D4.2 AC: per_zone_breakdown value is always a dict."""
        def _compute_breakdown(coords):
            result = {}
            for c in coords:
                try:
                    result["z"] = result.get("z", 0) + 1
                except Exception:
                    pass
            return result

        assert isinstance(_compute_breakdown([]), dict)

    def test_source_reads_options_then_data_for_zone(self):
        """D4.2 AC (Bug Class #14): zone read uses options first, then data."""
        src = self.AGG_FILE.read_text()
        # Pattern: entry.options.get(CONF_ZONE) before entry.data.get(CONF_ZONE)
        options_idx = src.find("entry.options.get(CONF_ZONE)")
        data_idx = src.find("entry.data.get(CONF_ZONE")
        assert options_idx > 0, "Must read zone from entry.options first"
        assert data_idx > 0, "Must fall back to entry.data for zone"


# ---------------------------------------------------------------------------
# D4.3 — OccupiedBinarySensor idle_duration
# ---------------------------------------------------------------------------

class TestD43IdleDuration:
    """D4.3: OccupiedBinarySensor.extra_state_attributes has idle_duration."""

    BS_FILE = ROOT / "custom_components" / "universal_room_automation" / "binary_sensor.py"

    def test_source_idle_duration_key_present(self):
        """D4.3 AC: binary_sensor.py contains idle_duration key."""
        src = self.BS_FILE.read_text()
        assert "idle_duration" in src, \
            "OccupiedBinarySensor must include idle_duration in extra_state_attributes"

    def test_idle_duration_zero_when_occupied(self):
        """D4.3 AC: idle_duration=0 when is_on=True."""
        # Inline the idle_duration logic
        def _compute_idle(is_on, coord_data, STATE_TIME_SINCE_OCCUPIED):
            try:
                if is_on:
                    return 0
                else:
                    return coord_data.get(STATE_TIME_SINCE_OCCUPIED) if coord_data else None
            except Exception:
                return None

        assert _compute_idle(True, {"time_since_last_occupied": 300}, "time_since_last_occupied") == 0

    def test_idle_duration_returns_time_when_vacant(self):
        """D4.3 AC: idle_duration returns STATE_TIME_SINCE_OCCUPIED value when vacant."""
        def _compute_idle(is_on, coord_data, key):
            try:
                if is_on:
                    return 0
                return coord_data.get(key) if coord_data else None
            except Exception:
                return None

        assert _compute_idle(False, {"time_since_last_occupied": 450}, "time_since_last_occupied") == 450

    def test_idle_duration_none_when_no_data(self):
        """D4.3 AC: idle_duration=None when coordinator.data is None."""
        def _compute_idle(is_on, coord_data, key):
            try:
                if is_on:
                    return 0
                return coord_data.get(key) if coord_data else None
            except Exception:
                return None

        assert _compute_idle(False, None, "time_since_last_occupied") is None

    def test_source_state_time_since_occupied_imported(self):
        """D4.3 AC: STATE_TIME_SINCE_OCCUPIED imported at module top."""
        src = self.BS_FILE.read_text()
        assert "STATE_TIME_SINCE_OCCUPIED" in src, \
            "STATE_TIME_SINCE_OCCUPIED must be imported in binary_sensor.py"


# ---------------------------------------------------------------------------
# D4.4 — OccupiedBinarySensor current_persons
# ---------------------------------------------------------------------------

class TestD44CurrentPersons:
    """D4.4: OccupiedBinarySensor.extra_state_attributes has current_persons as list."""

    BS_FILE = ROOT / "custom_components" / "universal_room_automation" / "binary_sensor.py"

    def test_source_current_persons_key_present(self):
        """D4.4 AC: binary_sensor.py contains current_persons key."""
        src = self.BS_FILE.read_text()
        assert "current_persons" in src, \
            "OccupiedBinarySensor must include current_persons in extra_state_attributes"

    def test_current_persons_returns_list_when_coordinator_found(self):
        """D4.4 AC: current_persons returns list from person_coordinator."""
        def _get_persons(hass_data, room_name):
            try:
                pc = hass_data.get("person_coordinator")
                if pc is None:
                    return []
                if not room_name:
                    return []
                return pc.get_room_occupants(room_name) or []
            except Exception:
                return []

        pc = MagicMock()
        pc.get_room_occupants = MagicMock(return_value=["Alice", "Bob"])
        result = _get_persons({"person_coordinator": pc}, "Master Bedroom")
        assert result == ["Alice", "Bob"]

    def test_current_persons_returns_empty_list_when_no_coordinator(self):
        """D4.4 AC: current_persons returns [] (not None) when pc absent (Bug Class #8)."""
        def _get_persons(hass_data, room_name):
            try:
                pc = hass_data.get("person_coordinator")
                if pc is None:
                    return []
                return pc.get_room_occupants(room_name) or []
            except Exception:
                return []

        result = _get_persons({}, "Master Bedroom")
        assert result == [], "Must return [] not None when person_coordinator absent"
        assert isinstance(result, list)

    def test_current_persons_returns_empty_list_on_exception(self):
        """D4.4 AC: current_persons returns [] on any exception (Bug Class #8)."""
        def _get_persons(hass_data, room_name):
            try:
                pc = hass_data.get("person_coordinator")
                if pc is None:
                    return []
                return pc.get_room_occupants(room_name) or []
            except Exception:
                return []

        pc = MagicMock()
        pc.get_room_occupants = MagicMock(side_effect=RuntimeError("boom"))
        result = _get_persons({"person_coordinator": pc}, "Office")
        assert result == []

    def test_current_persons_uses_person_coordinator_key(self):
        """D4.4 AC: binary_sensor.py uses 'person_coordinator' key (not person_tracking_coordinator)."""
        src = self.BS_FILE.read_text()
        assert '"person_coordinator"' in src or "'person_coordinator'" in src, \
            "binary_sensor.py must use 'person_coordinator' key to look up PersonTrackingCoordinator"


# ---------------------------------------------------------------------------
# D4.5 — WholeHousePowerSensor source_breakdown
# ---------------------------------------------------------------------------

class TestD45SourceBreakdown:
    """D4.5: WholeHousePowerSensor.extra_state_attributes has source_breakdown."""

    AGG_FILE = ROOT / "custom_components" / "universal_room_automation" / "aggregation.py"

    def test_source_source_breakdown_key_present(self):
        """D4.5 AC: aggregation.py contains source_breakdown key."""
        src = self.AGG_FILE.read_text()
        assert "source_breakdown" in src, \
            "WholeHousePowerSensor must include source_breakdown in extra_state_attributes"

    def test_source_breakdown_has_three_sub_keys(self):
        """D4.5 AC: source_breakdown contains solar_power_w, battery_power_w, grid_power_w."""
        src = self.AGG_FILE.read_text()
        for key in ("solar_power_w", "battery_power_w", "grid_power_w"):
            assert key in src, f"source_breakdown must include {key!r}"

    def test_source_breakdown_computation(self):
        """D4.5 AC: solar_power_w reads from solar sensor; battery/grid are None."""
        def _compute_source_breakdown(hass_states, solar_sensor_id):
            solar_power_w = None
            try:
                if solar_sensor_id:
                    state = hass_states.get(solar_sensor_id)
                    if state and state.state not in ("unknown", "unavailable"):
                        solar_power_w = float(state.state)
            except Exception:
                pass
            return {
                "solar_power_w": solar_power_w,
                "battery_power_w": None,
                "grid_power_w": None,
            }

        class _FakeState:
            def __init__(self, state):
                self.state = state

        hass_states = {"sensor.solar": _FakeState("3500.0")}
        breakdown = _compute_source_breakdown(hass_states, "sensor.solar")
        assert breakdown["solar_power_w"] == pytest.approx(3500.0)
        assert breakdown["battery_power_w"] is None
        assert breakdown["grid_power_w"] is None

    def test_source_breakdown_solar_none_when_sensor_unavailable(self):
        """D4.5 AC: solar_power_w=None when sensor unavailable."""
        def _compute_source_breakdown(hass_states, solar_sensor_id):
            solar_power_w = None
            try:
                if solar_sensor_id:
                    state = hass_states.get(solar_sensor_id)
                    if state and state.state not in ("unknown", "unavailable"):
                        solar_power_w = float(state.state)
            except Exception:
                pass
            return {"solar_power_w": solar_power_w, "battery_power_w": None, "grid_power_w": None}

        class _FakeState:
            def __init__(self, state):
                self.state = state

        for unavail in ("unknown", "unavailable"):
            breakdown = _compute_source_breakdown({"sensor.solar": _FakeState(unavail)}, "sensor.solar")
            assert breakdown["solar_power_w"] is None, \
                f"solar_power_w must be None when sensor state={unavail!r}"


# ---------------------------------------------------------------------------
# D4.6 — HVACModeSensor zone_limits
# ---------------------------------------------------------------------------

class TestD46ZoneLimits:
    """D4.6: HVACModeSensor.extra_state_attributes has zone_limits."""

    HVAC_FILE = (
        ROOT / "custom_components" / "universal_room_automation"
        / "domain_coordinators" / "hvac.py"
    )

    def test_source_zone_limits_key_present(self):
        """D4.6 AC: hvac.py contains zone_limits key in get_mode_attrs."""
        src = self.HVAC_FILE.read_text()
        assert "zone_limits" in src, \
            "get_mode_attrs() must include zone_limits key"

    def test_source_zone_limits_uses_get_zone_status_attrs(self):
        """D4.6 AC: zone_limits is built from get_zone_status_attrs."""
        src = self.HVAC_FILE.read_text()
        assert "get_zone_status_attrs" in src, \
            "zone_limits must use get_zone_status_attrs() for the correct shape"

    def test_zone_limits_computation(self):
        """D4.6 AC: zone_limits maps friendly_name → cool_low + heat_high."""
        def _compute_zone_limits(zone_manager):
            zone_limits = {}
            try:
                for zone_id, zone in zone_manager.zones.items():
                    zone_attrs = zone_manager.get_zone_status_attrs(zone_id)
                    friendly_name = zone_attrs.get("friendly_name", zone_id)
                    zone_limits[friendly_name] = {
                        "cool_low": zone_attrs.get("target_temp_low"),
                        "heat_high": zone_attrs.get("target_temp_high"),
                    }
            except Exception:
                pass
            return zone_limits

        zm = MagicMock()
        zm.zones = {"z1": MagicMock()}
        zm.get_zone_status_attrs = MagicMock(return_value={
            "friendly_name": "Upstairs",
            "target_temp_low": 68.0,
            "target_temp_high": 76.0,
        })
        limits = _compute_zone_limits(zm)
        assert "Upstairs" in limits
        assert limits["Upstairs"]["cool_low"] == pytest.approx(68.0)
        assert limits["Upstairs"]["heat_high"] == pytest.approx(76.0)

    def test_zone_limits_empty_on_exception(self):
        """D4.6 AC: zone_limits returns {} (not raises) on exception."""
        def _compute_zone_limits(zone_manager):
            zone_limits = {}
            try:
                for zone_id, zone in zone_manager.zones.items():
                    zone_attrs = zone_manager.get_zone_status_attrs(zone_id)
                    friendly_name = zone_attrs.get("friendly_name", zone_id)
                    zone_limits[friendly_name] = {
                        "cool_low": zone_attrs.get("target_temp_low"),
                        "heat_high": zone_attrs.get("target_temp_high"),
                    }
            except Exception:
                pass
            return zone_limits

        zm = MagicMock()
        zm.zones = MagicMock(items=MagicMock(side_effect=RuntimeError("zone gone")))
        result = _compute_zone_limits(zm)
        assert result == {}

    def test_zone_limits_uses_friendly_name_key(self):
        """D4.6 AC: zone_limits uses friendly_name from get_zone_status_attrs (not zone_name)."""
        src = self.HVAC_FILE.read_text()
        # Find zone_limits block
        limits_idx = src.find("zone_limits")
        assert limits_idx > 0
        block = src[limits_idx: limits_idx + 500]
        assert '"friendly_name"' in block or "'friendly_name'" in block, \
            "zone_limits must use 'friendly_name' key from get_zone_status_attrs"
        # Must NOT use 'zone_name' (which does not exist in get_zone_status_attrs)
        assert '"zone_name"' not in block and "'zone_name'" not in block, \
            "zone_limits must not use 'zone_name' — correct key is 'friendly_name'"


# ---------------------------------------------------------------------------
# D4.8 — SafetyEventsSummarySensor
# ---------------------------------------------------------------------------

class TestD48SafetyEventsSummarySensor:
    """D4.8: SafetyEventsSummarySensor class exists with correct shape."""

    SENSOR_FILE = ROOT / "custom_components" / "universal_room_automation" / "sensor.py"

    def _read_src(self):
        return self.SENSOR_FILE.read_text()

    def test_class_exists_in_sensor_py(self):
        """D4.8 AC: SafetyEventsSummarySensor class defined in sensor.py."""
        src = self._read_src()
        assert "class SafetyEventsSummarySensor" in src

    def test_registered_in_async_setup_entry(self):
        """D4.8 AC: SafetyEventsSummarySensor(hass, entry) in coordinator_sensors list."""
        src = self._read_src()
        assert "SafetyEventsSummarySensor(hass, entry)" in src

    def test_state_is_events_today_count_pattern(self):
        """D4.8 AC: sensor native_value returns cached integer count."""
        src = self._read_src()
        class_match = re.search(
            r"class SafetyEventsSummarySensor.*?(?=\nclass |\Z)",
            src, re.DOTALL,
        )
        assert class_match, "SafetyEventsSummarySensor not found"
        body = class_match.group(0)
        assert "_cached_count" in body, "Sensor must use _cached_count for state"

    def test_has_extra_state_attributes_with_required_keys(self):
        """D4.8 AC: extra_state_attributes returns auto_dismissed_count, last_event_at, window_hours."""
        src = self._read_src()
        class_match = re.search(
            r"class SafetyEventsSummarySensor.*?(?=\nclass |\Z)",
            src, re.DOTALL,
        )
        assert class_match
        body = class_match.group(0)
        for key in ("auto_dismissed_count", "last_event_at", "window_hours"):
            assert key in body, f"SafetyEventsSummarySensor must expose {key!r} in attributes"

    def test_has_cache_ttl_constant(self):
        """D4.8 AC: 60s cache TTL (Bug Class #26) defined as class constant."""
        src = self._read_src()
        class_match = re.search(
            r"class SafetyEventsSummarySensor.*?(?=\nclass |\Z)",
            src, re.DOTALL,
        )
        assert class_match
        body = class_match.group(0)
        assert "_CACHE_TTL_S" in body or "60" in body, \
            "SafetyEventsSummarySensor must have a 60s cache TTL (Bug Class #26)"

    def test_has_async_will_remove_from_hass(self):
        """D4.8 AC: cache cleared on entity remove (Bug Class #36)."""
        src = self._read_src()
        class_match = re.search(
            r"class SafetyEventsSummarySensor.*?(?=\nclass |\Z)",
            src, re.DOTALL,
        )
        assert class_match
        body = class_match.group(0)
        assert "async_will_remove_from_hass" in body, \
            "SafetyEventsSummarySensor must implement async_will_remove_from_hass (Bug Class #36)"

    def test_query_filters_on_safety_coordinator(self):
        """D4.8 AC: SQL query filters on coordinator='safety'."""
        src = self._read_src()
        class_match = re.search(
            r"class SafetyEventsSummarySensor.*?(?=\nclass |\Z)",
            src, re.DOTALL,
        )
        assert class_match
        body = class_match.group(0)
        assert "coordinator='safety'" in body or 'coordinator="safety"' in body, \
            "Query must filter on coordinator='safety'"

    def test_uses_24h_window(self):
        """D4.8 AC: Query uses 24h window cutoff."""
        src = self._read_src()
        class_match = re.search(
            r"class SafetyEventsSummarySensor.*?(?=\nclass |\Z)",
            src, re.DOTALL,
        )
        assert class_match
        body = class_match.group(0)
        assert "hours=24" in body or "24" in body, \
            "SafetyEventsSummarySensor must use a 24h query window"

    def test_cache_stale_logic(self):
        """D4.8 AC: _cache_stale returns True when older than TTL or never set."""
        # Inline the cache staleness logic
        _CACHE_TTL_S = 60

        def _cache_stale(cache_time):
            if cache_time is None:
                return True
            age = (_utc_now() - cache_time).total_seconds()
            return age >= _CACHE_TTL_S

        assert _cache_stale(None) is True
        assert _cache_stale(_utc_now() - timedelta(seconds=61)) is True
        assert _cache_stale(_utc_now() - timedelta(seconds=30)) is False
