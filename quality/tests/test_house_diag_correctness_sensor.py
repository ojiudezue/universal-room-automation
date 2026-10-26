"""HOUSE-DIAG-CORRECTNESS (audit 2026-10-25 H7): the SafetyDiagnosticsSensor
``sensors_available`` attribute is wired to the safety coordinator's live
count, not to ``sensors_monitored`` (the old tautology: 94/94).
"""
from __future__ import annotations

from types import SimpleNamespace

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

from custom_components.universal_room_automation import sensor as sen  # noqa: E402
from custom_components.universal_room_automation.const import DOMAIN  # noqa: E402


def test_sensors_available_attribute_reads_live_count():
    safety = SimpleNamespace(
        sensors_monitored=94,
        count_available_sensors=lambda: 90,
        _hazards_detected_24h=0,
        _alerts_sent_24h=0,
    )
    manager = SimpleNamespace(coordinators={"safety": safety})
    fake = SimpleNamespace(hass=SimpleNamespace(data={DOMAIN: {"coordinator_manager": manager}}))
    attrs = sen.SafetyDiagnosticsSensor.extra_state_attributes.fget(fake)
    assert attrs["sensors_total"] == 94
    assert attrs["sensors_available"] == 90
