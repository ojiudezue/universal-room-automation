"""v4.5.12 — AC Ramp-Down Observability tests (slice 2).

Slice 2 deliverables:
  D7 — Per-zone state sensors (3 per AC zone)
  D8 — House-wide impact sensors (5)  [pending in this build]
  D10 — Diagnostic dump button         [pending]
  D11 — HC + EC user manuals           [pending]

These are source-grep + AST tests focused on the v4.5.12 surface.
Runtime smoke tests for D7/D8/D10 live in `test_runtime_smoke.py` and
activate when `pytest-homeassistant-custom-component` is installed.

The v4.5.11.x cycle proved that source-grep alone misses runtime bugs
(Bug Class #34, #35). v4.5.12 specifically guards against both:
- Every new per-zone sensor uses climate_entity (not zone_id) for
  the runtime lookup, bridging the v4.5.11.2 zone-id-drift gap.
- Every new sensor subscribes to SIGNAL_HVAC_ENTITIES_UPDATE so it
  refreshes per HVAC cycle (Bug Class #35 prevention).
"""

import ast
import json

import pytest


# ===========================================================================
# Source fixtures
# ===========================================================================


@pytest.fixture(scope="module")
def sensor_src() -> str:
    with open("custom_components/universal_room_automation/sensor.py") as f:
        return f.read()


@pytest.fixture(scope="module")
def hvac_override_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/hvac_override.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def hvac_zones_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/hvac_zones.py"
    ) as f:
        return f.read()


# ===========================================================================
# ZoneState — new D7 fields
# ===========================================================================


@pytest.mark.parametrize(
    "field_name",
    [
        "last_action_type",
        "last_action_ts",
        "last_action_triggered_by",
        "last_action_kwh_before",
        "last_action_kwh_after",
    ],
)
def test_zone_state_has_d7_action_field(hvac_zones_src, field_name):
    """ZoneState must carry last-action tracking fields so the
    HVACACRampLastActionSensor can read them without a DB query."""
    assert f"    {field_name}:" in hvac_zones_src


# ===========================================================================
# OverrideArrester — _track_zone_action helper + call sites
# ===========================================================================


class TestTrackerHelper:

    def test_track_zone_action_helper_exists(self, hvac_override_src):
        assert "def _track_zone_action(" in hvac_override_src

    def test_helper_sets_all_five_fields(self, hvac_override_src):
        idx = hvac_override_src.find("def _track_zone_action(")
        body = hvac_override_src[idx:idx + 2000]
        for field in (
            "zone.last_action_type",
            "zone.last_action_ts",
            "zone.last_action_triggered_by",
            "zone.last_action_kwh_before",
            "zone.last_action_kwh_after",
        ):
            assert field in body, (
                f"{field} not set by _track_zone_action — D7 last-action "
                f"sensor will show stale data for this attribute"
            )


@pytest.mark.parametrize(
    "event_constant",
    [
        # Most user-visible action events MUST track on ZoneState
        "AC_RAMP_EVENT_NUDGE_STARTED",
        "AC_RAMP_EVENT_NUDGE_RESTORED",
        "AC_RAMP_EVENT_NUDGE_EVALUATED",
        "AC_RAMP_EVENT_HARD_RESET_STARTED",
        "AC_RAMP_EVENT_HARD_RESET_COMPLETED",
        "AC_RAMP_EVENT_LOCKOUT_ENGAGED",
        "AC_RAMP_EVENT_CANCEL_INVOKED",
        "AC_RAMP_EVENT_DETECTION_FIRED",
    ],
)
def test_tracker_called_alongside_log_for_event(hvac_override_src, event_constant):
    """For each meaningful action event, `_track_zone_action` must be
    called near (within ~30 lines of) the `log_ac_ramp_event` site.
    This keeps the D7 last_action sensor in sync with the DB log.
    """
    log_idx = hvac_override_src.find(f"event_type={event_constant},")
    assert log_idx > 0, f"No log_ac_ramp_event call for {event_constant}"
    # Look in the ~30 lines before the event_type line for the tracker call
    window_start = max(0, log_idx - 1500)
    window = hvac_override_src[window_start:log_idx]
    # The tracker call uses the SAME event constant positionally
    assert f"_track_zone_action(" in window and event_constant in window, (
        f"_track_zone_action with {event_constant} not found within ~1500 "
        f"chars before the log_ac_ramp_event site — last_action sensor "
        f"won't reflect this event"
    )


# ===========================================================================
# D7 — Per-zone state sensors
# ===========================================================================


class TestACRampStateSensor:

    def test_class_exists(self, sensor_src):
        assert "class HVACACRampStateSensor(" in sensor_src

    def test_unique_id_includes_zone_id(self, sensor_src):
        idx = sensor_src.find("class HVACACRampStateSensor(")
        body = sensor_src[idx:idx + 3000]
        assert 'f"{DOMAIN}_hvac_ac_ramp_state_{zone_id}"' in body

    def test_native_value_reads_zone_ramp_state(self, sensor_src):
        idx = sensor_src.find("class HVACACRampStateSensor(")
        body = sensor_src[idx:idx + 3000]
        assert 'getattr(zone, "ramp_state"' in body

    def test_state_sensor_uses_diagnostic_category(self, sensor_src):
        idx = sensor_src.find("class HVACACRampStateSensor(")
        body = sensor_src[idx:idx + 3000]
        assert "EntityCategory.DIAGNOSTIC" in body

    def test_state_sensor_exposes_freshness_attrs(self, sensor_src):
        """Attributes must include kwh_samples_above_threshold so user
        can see how close detection is to firing."""
        idx = sensor_src.find("class HVACACRampStateSensor(")
        body = sensor_src[idx:idx + 4000]
        assert "kwh_samples_above_threshold" in body
        assert "last_overshoot_started" in body


class TestACRampLastActionSensor:

    def test_class_exists(self, sensor_src):
        assert "class HVACACRampLastActionSensor(" in sensor_src

    def test_is_timestamp_device_class(self, sensor_src):
        idx = sensor_src.find("class HVACACRampLastActionSensor(")
        body = sensor_src[idx:idx + 4000]
        assert "SensorDeviceClass.TIMESTAMP" in body

    def test_native_value_parses_iso_timestamp(self, sensor_src):
        idx = sensor_src.find("class HVACACRampLastActionSensor(")
        body = sensor_src[idx:idx + 4000]
        # Must convert the ISO string from ZoneState to a datetime
        assert "datetime.fromisoformat(" in body

    def test_attrs_expose_action_type_and_triggered_by(self, sensor_src):
        idx = sensor_src.find("class HVACACRampLastActionSensor(")
        body = sensor_src[idx:idx + 4000]
        assert '"action_type"' in body
        assert '"triggered_by"' in body
        assert '"kwh_rate_before"' in body
        assert '"kwh_rate_after"' in body


class TestACRampKwhRateSensor:

    def test_class_exists(self, sensor_src):
        assert "class HVACACRampKwhRateSensor(" in sensor_src

    def test_is_power_device_class_in_kw(self, sensor_src):
        idx = sensor_src.find("class HVACACRampKwhRateSensor(")
        body = sensor_src[idx:idx + 4000]
        assert "SensorDeviceClass.POWER" in body
        assert 'unit_of_measurement = "kW"' in body

    def test_native_value_reads_zone_last_kwh_rate(self, sensor_src):
        idx = sensor_src.find("class HVACACRampKwhRateSensor(")
        body = sensor_src[idx:idx + 4000]
        assert 'getattr(zone, "last_kwh_rate"' in body

    def test_exposes_stale_flag_with_threshold(self, sensor_src):
        """Risk R3 mitigation: sensor must surface staleness so user
        can see when the Span sensor stops reporting."""
        idx = sensor_src.find("class HVACACRampKwhRateSensor(")
        body = sensor_src[idx:idx + 4000]
        assert '"stale"' in body
        assert "AC_KWH_SENSOR_STALENESS_S" in body
        # Threshold should be exposed so user can see the per-zone setpoint
        assert '"kwh_threshold"' in body


# ===========================================================================
# Shared mixin — climate_entity-based lookup (Bug Class #34/#35 prevention)
# ===========================================================================


class TestACRampZoneSensorMixin:
    """The mixin is shared by all 3 D7 sensors. It encodes two critical
    patterns from the v4.5.11.x learnings:
      1. Look up zone by `climate_entity` (Bug Class #34-shape — zone_id
         naming drift between platforms and ZoneManager)
      2. Subscribe to SIGNAL_HVAC_ENTITIES_UPDATE in async_added_to_hass
         (Bug Class #35 — buttons/sensors without refresh signal stay
         cached unavailable forever)
    """

    def test_mixin_exists(self, sensor_src):
        assert "class _ACRampZoneSensorMixin" in sensor_src

    def test_lookup_by_climate_entity(self, sensor_src):
        idx = sensor_src.find("class _ACRampZoneSensorMixin")
        body = sensor_src[idx:idx + 3000]
        # Must iterate zones and match by climate_entity (not by zone_id)
        assert "z.climate_entity == self._climate_entity" in body

    def test_async_added_to_hass_subscribes_to_signal(self, sensor_src):
        idx = sensor_src.find("class _ACRampZoneSensorMixin")
        body = sensor_src[idx:idx + 3000]
        assert "async def async_added_to_hass(" in body
        assert "SIGNAL_HVAC_ENTITIES_UPDATE" in body
        assert "async_dispatcher_connect" in body

    def test_uses_async_on_remove_for_cleanup(self, sensor_src):
        idx = sensor_src.find("class _ACRampZoneSensorMixin")
        body = sensor_src[idx:idx + 3000]
        assert "self.async_on_remove(" in body

    def test_handler_is_callback_decorated(self, sensor_src):
        idx = sensor_src.find("class _ACRampZoneSensorMixin")
        body = sensor_src[idx:idx + 3000]
        assert "@callback" in body
        assert "def _handle_hvac_tick(" in body

    def test_handler_schedules_state_update(self, sensor_src):
        idx = sensor_src.find("class _ACRampZoneSensorMixin")
        body = sensor_src[idx:idx + 3000]
        assert "async_schedule_update_ha_state" in body


# ===========================================================================
# Setup wiring — sensors registered per AC zone
# ===========================================================================


class TestSetupWiring:

    def test_setup_loop_creates_all_three_sensors(self, sensor_src):
        # Find the v3.8.0 zone iteration loop
        idx = sensor_src.find("v3.8.0-H1: Add per-zone HVAC sensors")
        assert idx > 0
        body = sensor_src[idx:idx + 4000]
        assert "HVACACRampStateSensor(" in body
        assert "HVACACRampLastActionSensor(" in body
        assert "HVACACRampKwhRateSensor(" in body

    def test_sensors_receive_climate_entity(self, sensor_src):
        """All three D7 sensors must receive the thermostat entity_id
        (not just zone_id) so their runtime _get_zone() can look up
        the ZoneState by climate_entity."""
        idx = sensor_src.find("v3.8.0-H1: Add per-zone HVAC sensors")
        body = sensor_src[idx:idx + 4000]
        # All three constructor calls must include the thermostat var
        for cls in (
            "HVACACRampStateSensor",
            "HVACACRampLastActionSensor",
            "HVACACRampKwhRateSensor",
        ):
            call_idx = body.find(f"{cls}(")
            assert call_idx > 0
            call = body[call_idx:call_idx + 200]
            assert "_thermostat" in call, (
                f"{cls} constructor must receive _thermostat — see "
                f"setup_entry zone iteration loop"
            )


# ===========================================================================
# D8 — House-wide impact sensors (5)
# ===========================================================================


@pytest.fixture(scope="module")
def button_src() -> str:
    with open(
        "custom_components/universal_room_automation/button.py"
    ) as f:
        return f.read()


class TestImpactCacheInfrastructure:
    """D8 sensors read from `OverrideArrester._impact_cache`, which is
    refreshed once per decision cycle. The cache pattern avoids per-tick
    DB queries from sync `native_value` properties.
    """

    def test_impact_cache_initialized_in_init(self, hvac_override_src):
        idx = hvac_override_src.find("def __init__(")
        body = hvac_override_src[idx:idx + 6000]
        assert "self._impact_cache: dict =" in body

    @pytest.mark.parametrize(
        "key",
        [
            "nudges_today",
            "resets_today",
            "kwh_avoided_today",
            "kwh_avoided_total",
            "false_positive_rate",
            "fp_sample_size",
            "last_refresh_ts",
        ],
    )
    def test_impact_cache_has_key(self, hvac_override_src, key):
        idx = hvac_override_src.find("self._impact_cache: dict =")
        body = hvac_override_src[idx:idx + 2000]
        assert f'"{key}"' in body

    def test_refresh_helper_exists(self, hvac_override_src):
        assert "async def _refresh_impact_cache(" in hvac_override_src

    def test_refresh_called_in_check_ac_reset(self, hvac_override_src):
        """The cache must refresh once per decision cycle at the end
        of check_ac_reset — so sensors reflect the current cycle's
        state on the very next state poll."""
        idx = hvac_override_src.find("async def check_ac_reset(")
        body = hvac_override_src[idx:idx + 12000]
        assert "await self._refresh_impact_cache()" in body

    def test_refresh_handles_db_none_gracefully(self, hvac_override_src):
        idx = hvac_override_src.find("async def _refresh_impact_cache(")
        body = hvac_override_src[idx:idx + 3000]
        assert "if self._db is None:" in body and "return" in body

    def test_refresh_excludes_manual_from_fp_math(self, hvac_override_src):
        """The DB method already excludes manual triggers (Risk R6 from
        slice 1). Refresh just reads the result — verify it calls
        get_ac_ramp_kwh_avoided which has that filter."""
        idx = hvac_override_src.find("async def _refresh_impact_cache(")
        body = hvac_override_src[idx:idx + 3000]
        assert "get_ac_ramp_kwh_avoided" in body

    def test_fp_rate_hidden_until_sample_size_5(self, hvac_override_src):
        """Risk R3: false-positive rate misleading at small N."""
        idx = hvac_override_src.find("async def _refresh_impact_cache(")
        body = hvac_override_src[idx:idx + 3000]
        # Must check evals_total >= 5 before publishing a rate
        assert "evals_total >= 5" in body


class TestImpactSensorsExist:

    @pytest.mark.parametrize(
        "cls,uid_suffix,unit",
        [
            ("HVACACNudgesTodaySensor", "_hvac_ac_nudges_today", "nudges"),
            ("HVACACResetsTodaySensor", "_hvac_ac_resets_today", "resets"),
            ("HVACACKwhAvoidedTodaySensor", "_hvac_ac_kwh_avoided_today", "kWh"),
            ("HVACACKwhAvoidedTotalSensor", "_hvac_ac_kwh_avoided_total", "kWh"),
            ("HVACACFalsePositiveRateSensor", "_hvac_ac_false_positive_rate", "%"),
        ],
    )
    def test_d8_sensor_class_exists(self, sensor_src, cls, uid_suffix, unit):
        assert f"class {cls}(" in sensor_src
        idx = sensor_src.find(f"class {cls}(")
        body = sensor_src[idx:idx + 4000]
        assert f"{{DOMAIN}}{uid_suffix}" in body
        assert f'"{unit}"' in body

    def test_kwh_avoided_total_uses_restore_entity(self, sensor_src):
        """kWh-avoided-total must persist across restart."""
        idx = sensor_src.find("class HVACACKwhAvoidedTotalSensor(")
        body = sensor_src[idx:idx + 4000]
        assert "RestoreEntity" in body
        assert "async_get_last_state" in body

    def test_kwh_avoided_sensors_carry_accuracy_caveat(self, sensor_src):
        """Risk: kWh-avoided is a rough estimate. The tech debt is
        documented in TECH_DEBT.md; the sensor entity must surface
        this in attributes so dashboards can disclose."""
        for cls in (
            "HVACACKwhAvoidedTodaySensor",
            "HVACACKwhAvoidedTotalSensor",
        ):
            idx = sensor_src.find(f"class {cls}(")
            body = sensor_src[idx:idx + 4000]
            assert '"accuracy"' in body
            assert "rough_estimate" in body

    def test_false_positive_sensor_diagnostic_category(self, sensor_src):
        idx = sensor_src.find("class HVACACFalsePositiveRateSensor(")
        body = sensor_src[idx:idx + 3000]
        assert "EntityCategory.DIAGNOSTIC" in body

    def test_false_positive_sensor_exposes_sample_size(self, sensor_src):
        idx = sensor_src.find("class HVACACFalsePositiveRateSensor(")
        body = sensor_src[idx:idx + 3000]
        assert '"sample_size"' in body
        assert '"min_sample_for_display"' in body


class TestImpactSensorMixin:
    """Shared mixin for D8 sensors. Same pattern as _ACRampZoneSensorMixin
    from D7 — cache lookup + signal subscription."""

    def test_mixin_exists(self, sensor_src):
        assert "class _ACRampImpactSensorMixin" in sensor_src

    def test_mixin_reads_arrester_impact_cache(self, sensor_src):
        idx = sensor_src.find("class _ACRampImpactSensorMixin")
        body = sensor_src[idx:idx + 3000]
        assert "_override_arrester" in body
        assert "_impact_cache" in body

    def test_mixin_subscribes_to_signal(self, sensor_src):
        idx = sensor_src.find("class _ACRampImpactSensorMixin")
        body = sensor_src[idx:idx + 3000]
        assert "SIGNAL_HVAC_ENTITIES_UPDATE" in body
        assert "async_dispatcher_connect" in body
        assert "self.async_on_remove(" in body


class TestD8SetupWiring:

    def test_setup_entry_registers_all_five_sensors(self, sensor_src):
        idx = sensor_src.find("v4.5.12 D8: 5 house-wide AC ramp-down")
        assert idx > 0
        body = sensor_src[idx:idx + 1500]
        for cls in (
            "HVACACNudgesTodaySensor",
            "HVACACResetsTodaySensor",
            "HVACACKwhAvoidedTodaySensor",
            "HVACACKwhAvoidedTotalSensor",
            "HVACACFalsePositiveRateSensor",
        ):
            assert f"{cls}(hass, entry)" in body


# ===========================================================================
# D10 — Diagnostic dump button
# ===========================================================================


class TestDiagnosticDumpButton:

    def test_class_exists(self, button_src):
        assert "class HVACACRampDiagnosticDumpButton(" in button_src

    def test_registered_in_setup(self, button_src):
        idx = button_src.find("v4.5.12 D10: diagnostic dump button")
        assert idx > 0
        body = button_src[idx:idx + 500]
        assert "HVACACRampDiagnosticDumpButton(hass, entry)" in body

    def test_unique_id_and_label(self, button_src):
        idx = button_src.find("class HVACACRampDiagnosticDumpButton(")
        body = button_src[idx:idx + 4000]
        assert 'f"{DOMAIN}_hvac_ac_ramp_diagnostic_dump"' in body
        assert '_attr_name = "AC Ramp Diagnostic Dump"' in body

    def test_writes_to_ura_diagnostics_dir(self, button_src):
        """Dump must land in /config/ura_diagnostics/ with a timestamped
        filename so multiple dumps don't collide."""
        idx = button_src.find("class HVACACRampDiagnosticDumpButton(")
        body = button_src[idx:idx + 6000]
        assert "ura_diagnostics" in body
        assert "ac_ramp_" in body
        assert ".json" in body

    def test_uses_existing_db_method(self, button_src):
        """Reuse slice 1's get_ac_ramp_events_recent, don't reinvent."""
        idx = button_src.find("class HVACACRampDiagnosticDumpButton(")
        body = button_src[idx:idx + 6000]
        assert "get_ac_ramp_events_recent" in body
        # 7-day window per the planning doc
        assert "days=7" in body

    def test_dump_includes_aggregates(self, button_src):
        """Self-contained dump — include aggregate context so offline
        analysis doesn't need the DB to interpret the event sequence."""
        idx = button_src.find("class HVACACRampDiagnosticDumpButton(")
        body = button_src[idx:idx + 6000]
        assert "get_ac_ramp_kwh_avoided" in body
        assert '"aggregates"' in body

    def test_fires_persistent_notification(self, button_src):
        idx = button_src.find("class HVACACRampDiagnosticDumpButton(")
        body = button_src[idx:idx + 6000]
        assert '"persistent_notification"' in body
        assert '"create"' in body

    def test_subscribes_to_refresh_signal_bug_class_35(self, button_src):
        """Apply the v4.5.11.3 Bug Class #35 pattern to every new button
        even when `available` doesn't depend on the arrester. Defensive
        consistency — future changes to `available` are safe."""
        idx = button_src.find("class HVACACRampDiagnosticDumpButton(")
        body = button_src[idx:idx + 6000]
        assert "async def async_added_to_hass(" in body
        assert "SIGNAL_HVAC_ENTITIES_UPDATE" in body
        assert "async_dispatcher_connect" in body
        assert "self.async_on_remove(" in body

    def test_handler_is_callback_decorated(self, button_src):
        idx = button_src.find("class HVACACRampDiagnosticDumpButton(")
        body = button_src[idx:idx + 6000]
        assert "@callback" in body
        assert "async_schedule_update_ha_state" in body

    def test_diagnostic_entity_category(self, button_src):
        idx = button_src.find("class HVACACRampDiagnosticDumpButton(")
        body = button_src[idx:idx + 4000]
        assert "EntityCategory.DIAGNOSTIC" in body


# ===========================================================================
# Quality bar — applies new test patterns to v4.5.12 surface
# ===========================================================================


class TestQualityFrameworkApplied:
    """v4.5.12 reviews must continue to use the regression patterns
    that came out of slice 1. Re-runs the AST resolver from
    test_v4511 over the same files to catch shape drift.
    """

    def test_function_local_imports_dont_shadow_module_imports(self, sensor_src):
        """Bug Class #34 — same AST walk as test_v4511.

        Scoped check: only flags the actual bug pattern (name used
        BEFORE the local import in the same function).
        """
        tree = ast.parse(sensor_src)
        module_names = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_names.add(
                        (alias.asname or alias.name).split(".")[0]
                    )
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    module_names.add(alias.asname or alias.name)

        violations = []
        for func in ast.walk(tree):
            if not isinstance(
                func, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            for child in ast.walk(func):
                if not isinstance(child, (ast.Import, ast.ImportFrom)):
                    continue
                if isinstance(child, ast.ImportFrom):
                    names = [
                        alias.asname or alias.name
                        for alias in child.names
                        if alias.name != "*"
                    ]
                else:
                    names = [
                        (alias.asname or alias.name).split(".")[0]
                        for alias in child.names
                    ]
                for name in names:
                    if name not in module_names:
                        continue
                    # Check if `name` is referenced earlier in this function
                    for sub in ast.walk(func):
                        if (
                            isinstance(sub, ast.Name)
                            and sub.id == name
                            and sub.lineno < child.lineno
                        ):
                            violations.append(
                                f"sensor.py:{child.lineno} function "
                                f"`{func.name}` re-imports '{name}' but "
                                f"'{name}' is used earlier at line "
                                f"{sub.lineno} — UnboundLocalError at "
                                f"runtime (Bug Class #34)"
                            )
                            break
        assert not violations, "\n".join(violations)
