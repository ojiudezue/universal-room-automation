"""FAN-ORACLE-BOOT-FALLBACK-NOISE-1.

Pre-attach fallback writes (rooms set up before the CoordinatorManager
attaches the FanPolicyOracle) must NOT WARN; genuine post-attach fallback
(oracle attached once, then missing) must still WARN. Behaviour unchanged:
the locally-stored value is picked up (hydrated) once the oracle attaches.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401

from custom_components.universal_room_automation.const import DOMAIN
from custom_components.universal_room_automation.domain_coordinators.manager import (  # noqa: E501
    CoordinatorManager,
)

LOGGER_NAME = "custom_components.universal_room_automation.automation"
ROOM = "BootRoom"


def _make_room(hass):
    from custom_components.universal_room_automation.automation import (  # noqa: E501
        RoomAutomation,
    )
    room = RoomAutomation.__new__(RoomAutomation)
    room.hass = hass
    room.config = {"room_name": ROOM}
    room._config_entry = None
    return room


def _hass():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.services = MagicMock()
    return hass


def _fallback_warnings(caplog):
    return [
        r for r in caplog.records
        if r.levelno >= logging.WARNING and "FanPolicyOracle fallback" in r.getMessage()
    ]


def test_pre_attach_write_does_not_warn(caplog):
    hass = _hass()
    room = _make_room(hass)
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    until = datetime(2026, 10, 3, 12, 0) + timedelta(minutes=10)
    room._fan_manual_on_until = until
    room._fan_manual_off_until = until
    assert room._fan_manual_on_until == until
    assert _fallback_warnings(caplog) == []
    assert any("pre-attach" in r.getMessage() for r in caplog.records)


def test_pre_attach_value_hydrates_after_real_cm_attach(caplog):
    hass = _hass()
    room = _make_room(hass)
    until = datetime(2026, 10, 3, 12, 0) + timedelta(minutes=10)
    room._fan_manual_on_until = until  # pre-attach, local only
    CoordinatorManager(hass)  # real CM attaches the oracle
    oracle = hass.data[DOMAIN]["fan_oracle"]
    assert hass.data[DOMAIN].get("fan_oracle_attached_once") is True
    assert room._fan_manual_on_until == until
    assert oracle.get_state(f"room:{ROOM}").manual_on_hold_until == until


def test_post_attach_then_missing_oracle_warns(caplog):
    hass = _hass()
    room = _make_room(hass)
    CoordinatorManager(hass)  # attach once
    hass.data[DOMAIN].pop("fan_oracle")  # lifecycle regression
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    room._fan_manual_off_until = datetime(2026, 10, 3, 12, 0)
    warns = _fallback_warnings(caplog)
    assert len(warns) == 1
    assert "write_off" in warns[0].getMessage()
