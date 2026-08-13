"""D3-AREA-INHERIT — CameraPersonDetectedSensor stamps room area on DeviceInfo.

Behavioral test that drives the production __init__ of
CameraPersonDetectedSensor with a stubbed coordinator + entry and asserts
that `suggested_area` on `_attr_device_info` reflects the room's
CONF_AREA_ID. Kill switch: when CONF_AREA_ID is absent/empty, suggested_area
must NOT be set (no-op — existing device registry state wins).

Neuter drill (per feedback_wire_in_anchor_mandatory + hollow-anchors rules):
removing the `self._attr_device_info["suggested_area"] = _area_id`
assignment turns test_area_stamped_from_conf red — validated by manual
mutation prior to check-in.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BINARY_SENSOR_TEXT = (
    _REPO_ROOT / "custom_components/universal_room_automation/binary_sensor.py"
).read_text()


def _d3_class_body() -> str:
    marker = "class CameraPersonDetectedSensor("
    start = _BINARY_SENSOR_TEXT.index(marker)
    end = _BINARY_SENSOR_TEXT.index("\nclass ", start + len(marker))
    return _BINARY_SENSOR_TEXT[start:end]


D3_BODY = _d3_class_body()


# ---------------------------------------------------------------------------
# Source anchor: guarantees the wire-in survives even when the harness lacks
# HA stubs (behavioral tests below skip in that case). Together with the
# behavioral tests this pins BOTH the value plumbing AND the source site.
# Neutering the assignment line makes both this anchor and
# test_area_stamped_from_conf red (validated by mutation).
# ---------------------------------------------------------------------------

def test_source_anchor_area_stamped_on_device_info():
    assert 'self._attr_device_info["suggested_area"] = _area_id' in D3_BODY, (
        "CameraPersonDetectedSensor.__init__ must stamp suggested_area on "
        "_attr_device_info from the room's CONF_AREA_ID (D3-AREA-INHERIT)"
    )


def test_source_anchor_reads_area_id_from_entry():
    # Read must consult BOTH options and data (options override).
    assert "options.get(CONF_AREA_ID)" in D3_BODY
    assert "data.get(CONF_AREA_ID)" in D3_BODY

_HERE = os.path.dirname(__file__)
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))


def _import_binary_sensor():
    sys.path.insert(0, os.path.join(_REPO, "custom_components"))
    try:
        from universal_room_automation import binary_sensor as bs  # noqa: PLC0415
        return bs
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"binary_sensor not importable in this harness: {e}")


def _construct(bs, coord):
    """Construct D3 sensor, tolerating poisoned CoordinatorEntity stubs.

    The full-suite runs poison ``CoordinatorEntity`` down to plain ``object``
    (sys.modules pollution — see conftest.py SUITE-HYGIENE-1 comment). Skip
    behavioral assertions in that case; source anchors below still pin the
    wire-in.
    """
    try:
        return bs.CameraPersonDetectedSensor(coord)
    except TypeError as e:
        pytest.skip(f"CoordinatorEntity stub too narrow for real init: {e}")


class _Entry:
    def __init__(self, area_id=None, room_name="Living Room"):
        self.entry_id = "entry_test_d3"
        self.data = {"room_name": room_name}
        if area_id is not None:
            self.data["area_id"] = area_id
        self.options = {}


class _Coord:
    """Minimal stub sufficient for UniversalRoomEntity.__init__."""
    def __init__(self, entry):
        self.entry = entry
        self.data = {}
        # CoordinatorEntity.__init__ reads a few coordinator attrs; provide
        # inert defaults.
        self.last_update_success = True

    # CoordinatorEntity subscribes to updates via async_add_listener; not
    # invoked here because we don't call async_added_to_hass.
    def async_add_listener(self, *_a, **_k):
        return lambda: None


def test_area_stamped_from_conf():
    bs = _import_binary_sensor()
    entry = _Entry(area_id="living_room")
    coord = _Coord(entry)
    sensor = _construct(bs, coord)
    di = sensor._attr_device_info
    assert di is not None, "DeviceInfo must be set by base entity"
    assert di.get("suggested_area") == "living_room", (
        f"Expected suggested_area='living_room' on D3 DeviceInfo, "
        f"got {di.get('suggested_area')!r}"
    )


def test_no_area_when_conf_missing():
    """Kill-switch semantics: CONF_AREA_ID unset -> suggested_area not stamped.

    Prevents the additive fix from asserting an empty/None area against the
    HA device registry (which would create a placeholder area or raise).
    """
    bs = _import_binary_sensor()
    entry = _Entry(area_id=None)
    coord = _Coord(entry)
    sensor = _construct(bs, coord)
    di = sensor._attr_device_info
    assert di is not None
    assert "suggested_area" not in di or not di.get("suggested_area"), (
        "D3 must not stamp suggested_area when CONF_AREA_ID is unset"
    )


def test_options_overrides_data():
    """CONF_AREA_ID in entry.options must override entry.data (URA convention)."""
    bs = _import_binary_sensor()
    entry = _Entry(area_id="stale_area")
    entry.options = {"area_id": "moved_room"}
    coord = _Coord(entry)
    sensor = _construct(bs, coord)
    assert sensor._attr_device_info.get("suggested_area") == "moved_room"
