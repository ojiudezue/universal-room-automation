"""Hotfix v4.7.16.5 — EnergyImportTodaySensor state_class fix.

HA platform rejected `device_class=ENERGY` + `state_class=MEASUREMENT`
combination with a deprecation warning. The native_value of this
sensor is `import_kwh - export_kwh` which can go NEGATIVE on export-
heavy days; TOTAL_INCREASING would log a different warning when the
value dipped. TOTAL is the correct state_class — matches the
convention used by sibling net-energy sensors.
"""

import pytest


@pytest.fixture(scope="module")
def sensor_src() -> str:
    with open(
        "custom_components/universal_room_automation/sensor.py"
    ) as f:
        return f.read()


class TestEnergyImportTodaySensorStateClass:
    def test_uses_total_not_measurement(self, sensor_src):
        """Class body must declare TOTAL, not MEASUREMENT, for ENERGY."""
        idx = sensor_src.find("class EnergyImportTodaySensor")
        assert idx > 0
        # Class body up to next top-level class
        next_class = sensor_src.find("\nclass ", idx + 50)
        body = sensor_src[idx: next_class] if next_class > 0 else sensor_src[idx: idx + 3000]
        assert "_attr_device_class = SensorDeviceClass.ENERGY" in body
        assert "_attr_state_class = SensorStateClass.TOTAL" in body
        # Hardening: assert the wrong state_class is NOT used
        assert "_attr_state_class = SensorStateClass.MEASUREMENT" not in body
        assert "_attr_state_class = SensorStateClass.TOTAL_INCREASING" not in body

    def test_no_energy_measurement_combo_remains_anywhere(self, sensor_src):
        """Repo-wide sanity: no other ENERGY sensor uses MEASUREMENT.

        v4.7.16.5 audit: only EnergyImportTodaySensor was offending. If a
        future sensor reintroduces the combination, this test catches it
        before the HA warning recurs.
        """
        # Walk every class body in sensor.py; for any that declares
        # device_class=ENERGY, assert it does not also declare
        # state_class=MEASUREMENT.
        import re
        class_starts = [m.start() for m in re.finditer(r"^class \w+", sensor_src, re.MULTILINE)]
        offenders = []
        for i, start in enumerate(class_starts):
            end = class_starts[i + 1] if i + 1 < len(class_starts) else len(sensor_src)
            body = sensor_src[start: end]
            has_energy = "_attr_device_class = SensorDeviceClass.ENERGY" in body
            has_measurement = "_attr_state_class = SensorStateClass.MEASUREMENT" in body
            if has_energy and has_measurement:
                # Extract class name for the failure message
                header = body.split("\n", 1)[0]
                offenders.append(header.strip())
        assert not offenders, (
            "No sensor with device_class=ENERGY may also use "
            "state_class=MEASUREMENT (HA platform rejects this combo). "
            f"Offenders: {offenders}"
        )
