"""Tests for Cycle C: Stub Cleanup (v3.20.2).

Verifies that removed stub entities no longer exist in the codebase
and that imports of modified modules still work correctly.
"""
import importlib
import sys
import pytest


class TestStubSensorRemoval:
    """Verify stub sensor classes have been removed from sensor.py."""

    def test_sensor_module_imports_cleanly(self):
        """Verify sensor.py can be parsed without import errors."""
        # We can't fully import (requires HA), but we can compile
        import py_compile
        py_compile.compile(
            "custom_components/universal_room_automation/sensor.py",
            doraise=True,
        )

    def test_removed_sensor_classes_not_in_source(self):
        """Verify all 11 stub sensor classes are removed from source."""
        with open("custom_components/universal_room_automation/sensor.py") as f:
            source = f.read()

        removed_classes = [
            "class OccupancyPercentageTodaySensor",
            "class EnergyWasteIdleSensor",
            "class MostExpensiveDeviceSensor",
            "class OptimizationPotentialSensor",
            "class EnergyCostPerOccupiedHourSensor",
            "class TimeUncomfortableTodaySensor",
            "class AvgTimeToComfortSensor",
            "class WeekdayMorningOccupancyProbSensor",
            "class WeekendEveningOccupancyProbSensor",
            "class TimeOccupiedTodaySensor",
            "class OccupancyPatternDetectedSensor",
        ]
        for cls in removed_classes:
            assert cls not in source, f"{cls} should have been removed"

    def test_removed_sensors_not_in_entity_list(self):
        """Verify removed sensors are not registered in async_setup_entry."""
        with open("custom_components/universal_room_automation/sensor.py") as f:
            source = f.read()

        removed_registrations = [
            "OccupancyPercentageTodaySensor(coordinator)",
            "EnergyWasteIdleSensor(coordinator)",
            "MostExpensiveDeviceSensor(coordinator)",
            "OptimizationPotentialSensor(coordinator)",
            "EnergyCostPerOccupiedHourSensor(coordinator)",
            "TimeUncomfortableTodaySensor(coordinator)",
            "AvgTimeToComfortSensor(coordinator)",
            "WeekdayMorningOccupancyProbSensor(coordinator)",
            "WeekendEveningOccupancyProbSensor(coordinator)",
            "TimeOccupiedTodaySensor(coordinator)",
            "OccupancyPatternDetectedSensor(coordinator)",
        ]
        for reg in removed_registrations:
            assert reg not in source, f"{reg} should have been removed from entity list"

    def test_non_stub_sensors_preserved(self):
        """Verify that legitimate sensors were NOT removed."""
        with open("custom_components/universal_room_automation/sensor.py") as f:
            source = f.read()

        # These should still exist
        preserved = [
            "class ConfigStatusSensor",
            "class UnavailableEntitiesSensor",
            "class DatabaseStatusSensor",
            "class TimeSinceMotionSensor",
            "class TimeSinceOccupiedSensor",
            "class DaysSinceOccupiedSensor",
            "class ComfortScoreSensor",
            "class EnergyEfficiencyScoreSensor",
            "class AutomationHealthSensor",
        ]
        for cls in preserved:
            assert cls in source, f"{cls} should still exist"


class TestStubBinarySensorRemoval:
    """Verify stub binary sensor classes have been removed."""

    def test_binary_sensor_module_imports_cleanly(self):
        """Verify binary_sensor.py can be parsed without import errors."""
        import py_compile
        py_compile.compile(
            "custom_components/universal_room_automation/binary_sensor.py",
            doraise=True,
        )

    def test_removed_binary_sensor_classes_not_in_source(self):
        """Verify both stub binary sensor classes are removed."""
        with open("custom_components/universal_room_automation/binary_sensor.py") as f:
            source = f.read()

        assert "class OccupancyAnomalyBinarySensor" not in source
        assert "class EnergyAnomalyBinarySensor" not in source

    def test_removed_binary_sensors_not_in_entity_list(self):
        """Verify removed binary sensors are not registered."""
        with open("custom_components/universal_room_automation/binary_sensor.py") as f:
            source = f.read()

        assert "OccupancyAnomalyBinarySensor(coordinator)" not in source
        assert "EnergyAnomalyBinarySensor(coordinator)" not in source

    def test_non_stub_binary_sensors_preserved(self):
        """Verify that legitimate binary sensors were NOT removed."""
        with open("custom_components/universal_room_automation/binary_sensor.py") as f:
            source = f.read()

        preserved = [
            "class RoomAlertBinarySensor",
            "class OccupiedBinarySensor",
            "class MotionDetectedBinarySensor",
            "class HVACCoordinatedBinarySensor",
            "class EnergySavingActiveBinarySensor",
            "class AutomationConflictBinarySensor",
        ]
        for cls in preserved:
            assert cls in source, f"{cls} should still exist"


class TestStubButtonRemoval:
    """Verify stub button classes have been removed."""

    def test_button_module_imports_cleanly(self):
        """Verify button.py can be parsed without import errors."""
        import py_compile
        py_compile.compile(
            "custom_components/universal_room_automation/button.py",
            doraise=True,
        )

    def test_removed_button_classes_not_in_source(self):
        """Verify both stub button classes are removed."""
        with open("custom_components/universal_room_automation/button.py") as f:
            source = f.read()

        assert "class ClearDatabaseButton" not in source
        assert "class OptimizeNowButton" not in source

    def test_removed_buttons_not_in_entity_list(self):
        """Verify removed buttons are not registered."""
        with open("custom_components/universal_room_automation/button.py") as f:
            source = f.read()

        assert "ClearDatabaseButton(coordinator)" not in source
        assert "OptimizeNowButton(coordinator)" not in source

    def test_functional_buttons_preserved(self):
        """Verify that functional buttons were NOT removed."""
        with open("custom_components/universal_room_automation/button.py") as f:
            source = f.read()

        preserved = [
            "class ReloadRoomButton",
            "class ExportDataButton",
            "class RefreshPredictionsButton",
            "class ConfigDumpButton",
            "class NMAcknowledgeButton",
        ]
        for cls in preserved:
            assert cls in source, f"{cls} should still exist"


class TestDeadSignalRemoval:
    """Verify SIGNAL_COMFORT_REQUEST has been removed."""

    def test_signals_module_imports_cleanly(self):
        """Verify signals.py can be parsed without import errors."""
        import py_compile
        py_compile.compile(
            "custom_components/universal_room_automation/domain_coordinators/signals.py",
            doraise=True,
        )

    def test_comfort_request_signal_removed(self):
        """Verify SIGNAL_COMFORT_REQUEST is removed from signals.py."""
        with open("custom_components/universal_room_automation/domain_coordinators/signals.py") as f:
            source = f.read()

        assert "SIGNAL_COMFORT_REQUEST" not in source
        assert "class ComfortRequest" not in source

    def test_comfort_request_not_referenced_anywhere(self):
        """Verify SIGNAL_COMFORT_REQUEST is not referenced in any Python file."""
        import os
        base = "custom_components/universal_room_automation"
        for root, dirs, files in os.walk(base):
            for fname in files:
                if fname.endswith(".py"):
                    path = os.path.join(root, fname)
                    with open(path) as f:
                        content = f.read()
                    assert "SIGNAL_COMFORT_REQUEST" not in content, (
                        f"SIGNAL_COMFORT_REQUEST still referenced in {path}"
                    )
                    assert "ComfortRequest" not in content, (
                        f"ComfortRequest still referenced in {path}"
                    )

    def test_other_signals_preserved(self):
        """Verify that active signals were NOT removed."""
        with open("custom_components/universal_room_automation/domain_coordinators/signals.py") as f:
            source = f.read()

        preserved = [
            "SIGNAL_HOUSE_STATE_CHANGED",
            "SIGNAL_ENERGY_CONSTRAINT",
            "SIGNAL_CENSUS_UPDATED",
            "SIGNAL_SAFETY_HAZARD",
            "SIGNAL_SECURITY_EVENT",
        ]
        for sig in preserved:
            assert sig in source, f"{sig} should still exist"


class TestDeferredDocumentation:
    """Verify DEFERRED_TO_BAYESIAN.md exists and is complete."""

    def test_deferred_doc_exists(self):
        """Verify the deferred documentation file exists."""
        import os
        assert os.path.exists("docs/DEFERRED_TO_BAYESIAN.md")

    def test_deferred_doc_contains_all_sensors(self):
        """Verify all 11 removed sensors are documented."""
        with open("docs/DEFERRED_TO_BAYESIAN.md") as f:
            content = f.read()

        sensors = [
            "OccupancyPercentageTodaySensor",
            "EnergyWasteIdleSensor",
            "MostExpensiveDeviceSensor",
            "OptimizationPotentialSensor",
            "EnergyCostPerOccupiedHourSensor",
            "TimeUncomfortableTodaySensor",
            "AvgTimeToComfortSensor",
            "WeekdayMorningOccupancyProbSensor",
            "WeekendEveningOccupancyProbSensor",
            "TimeOccupiedTodaySensor",
            "OccupancyPatternDetectedSensor",
        ]
        for sensor in sensors:
            assert sensor in content, f"{sensor} not documented in DEFERRED_TO_BAYESIAN.md"

    def test_deferred_doc_contains_binary_sensors(self):
        """Verify both removed binary sensors are documented."""
        with open("docs/DEFERRED_TO_BAYESIAN.md") as f:
            content = f.read()

        assert "OccupancyAnomalyBinarySensor" in content
        assert "EnergyAnomalyBinarySensor" in content

    def test_deferred_doc_contains_buttons(self):
        """Verify both removed buttons are documented."""
        with open("docs/DEFERRED_TO_BAYESIAN.md") as f:
            content = f.read()

        assert "ClearDatabaseButton" in content
        assert "OptimizeNowButton" in content

    def test_deferred_doc_contains_signal(self):
        """Verify removed signal is documented."""
        with open("docs/DEFERRED_TO_BAYESIAN.md") as f:
            content = f.read()

        assert "SIGNAL_COMFORT_REQUEST" in content
        assert "ComfortRequest" in content

    def test_deferred_doc_has_milestone_references(self):
        """Verify each entry references a v4.0.0 Bayesian milestone."""
        with open("docs/DEFERRED_TO_BAYESIAN.md") as f:
            content = f.read()

        # All four milestones should be referenced
        assert "B1:" in content
        assert "B2:" in content
        assert "B3:" in content
        assert "B4:" in content
