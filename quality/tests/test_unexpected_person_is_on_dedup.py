"""UNEXPECTED-PERSON-IS-ON-DEDUP-MIGRATE-1 — behavioral tests for the
migrated ``URAUnexpectedPersonSensor.is_on``.

is_on now returns ``house.unidentified_count > 0`` (the DEDUPED
camera-minus-|face∪ble| count) instead of the naive ``camera_total >
ble_total``. Each test uses a config that DISCRIMINATES the two formulas:
identical camera/ble totals but a different unidentified_count, so a test
turning RED under the old formula proves the migration is live.
"""
from __future__ import annotations

import os
import sys
import types

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load():
    try:
        sys.path.insert(0, os.path.join(_REPO, "custom_components"))
        from universal_room_automation import binary_sensor as bs  # noqa: PLC0415
        from universal_room_automation.const import DOMAIN  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"binary_sensor not importable: {e}")
    return bs, DOMAIN


def _house(total_persons, unidentified_count):
    return types.SimpleNamespace(total_persons=total_persons,
                                 unidentified_count=unidentified_count)


def _census(house):
    return types.SimpleNamespace(last_result=types.SimpleNamespace(house=house))


def _person_coord(active_pids):
    data = {p: {"tracking_status": "active"} for p in active_pids}
    return types.SimpleNamespace(data=data)


def _make(bs, DOMAIN, census, person_coord):
    s = bs.URAUnexpectedPersonSensor.__new__(bs.URAUnexpectedPersonSensor)
    s.hass = types.SimpleNamespace(
        data={DOMAIN: {"census": census, "person_coordinator": person_coord}}
    )
    return s


def test_fires_on_unidentified_even_when_camera_equals_ble():
    """camera_total == ble_total (naive => OFF) but unidentified_count=1 => ON.
    Proves is_on reads the deduped count, not camera>ble."""
    bs, DOMAIN = _load()
    s = _make(bs, DOMAIN, _census(_house(2, 1)), _person_coord(["a", "b"]))
    assert s.is_on is True


def test_silent_when_all_identified_even_when_camera_exceeds_ble():
    """camera_total(3) > ble_total(1) (naive => ON) but unidentified_count=0
    (the other 2 are face-identified) => OFF. Proves dedup suppresses the
    naive false-positive."""
    bs, DOMAIN = _load()
    s = _make(bs, DOMAIN, _census(_house(3, 0)), _person_coord(["a"]))
    assert s.is_on is False


def test_off_when_no_census():
    bs, DOMAIN = _load()
    s = _make(bs, DOMAIN, None, _person_coord(["a"]))
    assert s.is_on is False


def test_off_when_no_last_result():
    bs, DOMAIN = _load()
    census = types.SimpleNamespace(last_result=None)
    s = _make(bs, DOMAIN, census, _person_coord(["a"]))
    assert s.is_on is False


def test_diagnostic_totals_still_populated():
    """_camera_total/_ble_total remain fresh for the diagnostic attrs."""
    bs, DOMAIN = _load()
    s = _make(bs, DOMAIN, _census(_house(4, 2)), _person_coord(["a", "b", "c"]))
    _ = s.is_on
    assert s._camera_total == 4
    assert s._ble_total == 3
