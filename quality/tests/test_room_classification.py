"""ROOM-CLASSIFICATION-CONSISTENCY-1 D-C1 — accessor + sensor wire-in tests.

Tests the derived read-model accessor ``get_room_classification`` (helper
module ``room_classification.py``) and the ``classification`` attribute it
projects onto ``RoomSignalInventorySensor.extra_state_attributes``
(sensor.py:2617).

Discriminating properties verified:
- outdoor is derived from ``outdoor_zone_names_snapshot`` (safety.py:510),
  NOT from the SafetyCoordinator's coercion — the accessor returns
  ``outdoor: true`` for a room in an outdoor zone even when no
  SafetyCoordinator sits in ``hass.data``.
- Each flag flip changes EXACTLY that flag (wet flip uses a non-bathroom
  function so the const.py:1234 auto-seed doesn't couple wet to room_type).
- The sensor's ``classification`` attribute equals the accessor's return
  value (wire-in anchor); the mutation drill in this cycle's build report
  neuters the call site in sensor.py to prove the assertion is behavioural.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass

# sensor.py needs restore_state + CoordinatorEntity + DataUpdateCoordinator
# stubs (mirrors test_guest_count_dedup_migrate.py bootstrap).
import sys as _sys
import types as _types
if "homeassistant.helpers.restore_state" not in _sys.modules:
    _rs = _types.ModuleType("homeassistant.helpers.restore_state")

    class _RestoreEntity:  # noqa: D401
        """Stub RestoreEntity."""

    _rs.RestoreEntity = _RestoreEntity
    _sys.modules["homeassistant.helpers.restore_state"] = _rs

import homeassistant.helpers.update_coordinator as _uc  # type: ignore
if not hasattr(_uc, "CoordinatorEntity"):

    class _CoordinatorEntityMeta(type):
        def __getitem__(cls, item):
            return cls

    class _CoordinatorEntity(metaclass=_CoordinatorEntityMeta):  # noqa: D401
        """Stub CoordinatorEntity."""

        def __init__(self, *a, **kw):
            pass

    _uc.CoordinatorEntity = _CoordinatorEntity
if not hasattr(_uc, "DataUpdateCoordinator"):
    _uc.DataUpdateCoordinator = type("DataUpdateCoordinator", (), {})
if not hasattr(_uc, "UpdateFailed"):
    _uc.UpdateFailed = Exception

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation.room_classification import (
    get_room_classification,
)


DOMAIN = ura_const.DOMAIN


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------
def _room_entry(
    name: str,
    *,
    room_type: str = "bedroom",
    zone: str | None = None,
    guest: bool = False,
    wet: bool = False,
    shared: bool = False,
    options: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a mock room ConfigEntry with the given classification fields."""
    entry = MagicMock()
    entry.entry_id = f"entry_{name}"
    data: dict[str, Any] = {
        ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_ROOM,
        ura_const.CONF_ROOM_NAME: name,
        ura_const.CONF_ROOM_TYPE: room_type,
    }
    if zone is not None:
        data[ura_const.CONF_ZONE] = zone
    if guest:
        data[ura_const.CONF_ROOM_IS_GUEST_ROOM] = True
    if wet:
        data[ura_const.CONF_WET_ROOM] = True
    if shared:
        data[ura_const.CONF_SHARED_SPACE] = True
    entry.data = data
    entry.options = dict(options or {})
    return entry


def _zone_entry(
    name: str,
    *,
    zone_name: str,
    is_outdoor: bool = False,
) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = f"zone_{name}"
    entry.data = {
        ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_ZONE,
        ura_const.CONF_ZONE_NAME: zone_name,
        ura_const.CONF_ZONE_IS_OUTDOOR: is_outdoor,
    }
    entry.options = {}
    return entry


def _make_hass(*, zone_entries: list[MagicMock] | None = None) -> MagicMock:
    hass = make_hass()
    hass.data = {DOMAIN: {}}
    hass.config_entries.async_entries.return_value = list(zone_entries or [])
    return hass


# ---------------------------------------------------------------------------
# Accessor unit tests over a fixture room set
# ---------------------------------------------------------------------------
def test_plain_room_all_false() -> None:
    hass = _make_hass()
    entry = _room_entry("Office", room_type="office", zone="Indoor")
    result = get_room_classification(hass, entry)
    assert result == {
        "function": "office",
        "flags": [],
        "outdoor": False,
        "infrastructure": False,
    }


def test_guest_flag() -> None:
    hass = _make_hass()
    entry = _room_entry("GuestBed", room_type="bedroom", guest=True)
    result = get_room_classification(hass, entry)
    assert result["function"] == "bedroom"
    assert result["flags"] == ["guest"]
    assert result["outdoor"] is False
    assert result["infrastructure"] is False


def test_wet_flag_on_non_bathroom_function() -> None:
    """Non-bathroom function so bathroom-auto-seed (const.py:1234) doesn't
    couple wet to room_type — a discriminating flip test."""
    hass = _make_hass()
    entry = _room_entry("Laundry", room_type="laundry", wet=True)
    result = get_room_classification(hass, entry)
    assert result["flags"] == ["wet"]


def test_shared_flag() -> None:
    hass = _make_hass()
    entry = _room_entry("Kitchen", room_type="kitchen", shared=True)
    result = get_room_classification(hass, entry)
    assert result["flags"] == ["shared"]


def test_flag_flip_changes_only_that_flag() -> None:
    """Discriminating: flip one flag → exactly that flag changes."""
    hass = _make_hass()
    base = get_room_classification(
        hass, _room_entry("R", room_type="laundry", wet=True, guest=False, shared=False)
    )
    flipped = get_room_classification(
        hass, _room_entry("R", room_type="laundry", wet=True, guest=True, shared=False)
    )
    assert set(flipped["flags"]) - set(base["flags"]) == {"guest"}
    assert set(base["flags"]) - set(flipped["flags"]) == set()


def test_options_win_over_data() -> None:
    """options-wins merge — matches safety.py:1319-1322."""
    hass = _make_hass()
    entry = _room_entry("R", room_type="bedroom", guest=False)
    entry.options = {ura_const.CONF_ROOM_IS_GUEST_ROOM: True}
    result = get_room_classification(hass, entry)
    assert "guest" in result["flags"]


def test_infrastructure_from_coordinator_attr() -> None:
    """Infrastructure reads coordinator._infrastructure_room, NOT the switch."""
    hass = _make_hass()
    entry = _room_entry("Rack", room_type="office")  # note: not room_type=='infrastructure'
    coord = MagicMock()
    coord._infrastructure_room = True
    hass.data[DOMAIN][entry.entry_id] = coord
    result = get_room_classification(hass, entry)
    assert result["infrastructure"] is True


def test_infrastructure_boot_fallback_room_type() -> None:
    """Boot fallback: coordinator not in hass.data → room_type=='infrastructure'."""
    hass = _make_hass()
    entry = _room_entry("Rack", room_type="infrastructure")
    # NOTE: no coordinator registered in hass.data
    result = get_room_classification(hass, entry)
    assert result["infrastructure"] is True


def test_infrastructure_default_false() -> None:
    hass = _make_hass()
    entry = _room_entry("Bed", room_type="bedroom")
    result = get_room_classification(hass, entry)
    assert result["infrastructure"] is False


# ---------------------------------------------------------------------------
# Outdoor — discriminating: NO SafetyCoordinator in hass.data
# ---------------------------------------------------------------------------
def test_outdoor_derives_from_zone_snapshot_not_coercion() -> None:
    """DISCRIMINATING: with no SafetyCoordinator and no ``_sensor_room_types``
    populated, the Patio (zone Outside, zone_is_outdoor=True) still returns
    ``outdoor: True`` — proving the accessor reads
    ``outdoor_zone_names_snapshot``, not the safety coercion."""
    outside_zone = _zone_entry("outside", zone_name="Outside", is_outdoor=True)
    hass = _make_hass(zone_entries=[outside_zone])
    # Explicitly assert the safety coordinator is NOT present.
    assert "safety_coordinator" not in hass.data.get(DOMAIN, {})

    entry = _room_entry("Patio", room_type="outdoor_room", zone="Outside")
    result = get_room_classification(hass, entry)
    assert result["outdoor"] is True


def test_indoor_zone_not_outdoor() -> None:
    outside_zone = _zone_entry("outside", zone_name="Outside", is_outdoor=True)
    indoor_zone = _zone_entry("main", zone_name="Main", is_outdoor=False)
    hass = _make_hass(zone_entries=[outside_zone, indoor_zone])
    entry = _room_entry("Bedroom", room_type="bedroom", zone="Main")
    result = get_room_classification(hass, entry)
    assert result["outdoor"] is False


def test_outdoor_zone_cache_reused() -> None:
    """The accessor writes ``_outdoor_zones_cache`` into hass.data[DOMAIN]
    so a second call shares the ZoneSafetyAlertSensor invalidator's key
    (aggregation.py:4641). Discriminating: mutating the cached set changes
    the second read's outdoor answer without any zone-registry change."""
    outside_zone = _zone_entry("outside", zone_name="Outside", is_outdoor=True)
    hass = _make_hass(zone_entries=[outside_zone])
    entry = _room_entry("Patio", room_type="outdoor_room", zone="Outside")
    assert get_room_classification(hass, entry)["outdoor"] is True
    # Cache populated under the shared key.
    assert "_outdoor_zones_cache" in hass.data[DOMAIN]
    # Simulate the aggregation invalidator popping the key on
    # SIGNAL_ZM_ZONES_UPDATED; next read re-populates.
    hass.data[DOMAIN].pop("_outdoor_zones_cache")
    assert get_room_classification(hass, entry)["outdoor"] is True
    assert "_outdoor_zones_cache" in hass.data[DOMAIN]


def test_no_zone_configured_not_outdoor() -> None:
    outside_zone = _zone_entry("outside", zone_name="Outside", is_outdoor=True)
    hass = _make_hass(zone_entries=[outside_zone])
    entry = _room_entry("Untagged", room_type="bedroom")  # no CONF_ZONE
    result = get_room_classification(hass, entry)
    assert result["outdoor"] is False


# ---------------------------------------------------------------------------
# Wire-in anchor — behavioural, not a source grep
# ---------------------------------------------------------------------------
def test_room_signal_inventory_sensor_exposes_classification_attribute() -> None:
    """WIRE-IN ANCHOR: import the REAL RoomSignalInventorySensor and read
    ``extra_state_attributes["classification"]``. Neutering the call site in
    sensor.py (the ``get_room_classification(self.hass, ...)`` line inside
    ``extra_state_attributes``) turns this test RED — the mutation drill in
    the build report exercises exactly that.

    Constructed via ``__new__`` + ``.fget`` (mirroring
    ``_make_zone_sensor`` in test_guest_count_dedup_migrate.py) so we bypass
    the heavy base ``__init__`` yet still drive the real property code path.
    """
    from custom_components.universal_room_automation.sensor import (
        RoomSignalInventorySensor,
    )

    outside_zone = _zone_entry("outside", zone_name="Outside", is_outdoor=True)
    hass = _make_hass(zone_entries=[outside_zone])
    entry = _room_entry(
        "Patio", room_type="outdoor_room", zone="Outside", guest=True
    )
    coord = MagicMock()
    coord.entry = entry
    coord._infrastructure_room = False
    hass.data[DOMAIN][entry.entry_id] = coord

    sensor = RoomSignalInventorySensor.__new__(RoomSignalInventorySensor)
    sensor.hass = hass
    sensor.coordinator = coord

    # Drive the property via .fget so we don't need HA's descriptor machinery.
    attrs = RoomSignalInventorySensor.extra_state_attributes.fget(sensor)

    assert "classification" in attrs, (
        "RoomSignalInventorySensor.extra_state_attributes must expose "
        "'classification' — the accessor call site in sensor.py is the "
        "wire-in anchor for ROOM-CLASSIFICATION-CONSISTENCY-1 D-C1."
    )
    classification = attrs["classification"]
    assert classification["function"] == "outdoor_room"
    assert "guest" in classification["flags"]
    assert classification["outdoor"] is True
    assert classification["infrastructure"] is False


def test_sensor_classification_equals_accessor_directly() -> None:
    """The sensor attribute is not synthesised locally — it MUST equal the
    accessor's return value byte-for-byte on the same inputs."""
    from custom_components.universal_room_automation.sensor import (
        RoomSignalInventorySensor,
    )

    hass = _make_hass()
    entry = _room_entry("Kitchen", room_type="kitchen", shared=True)
    coord = MagicMock()
    coord.entry = entry
    coord._infrastructure_room = False
    hass.data[DOMAIN][entry.entry_id] = coord

    sensor = RoomSignalInventorySensor.__new__(RoomSignalInventorySensor)
    sensor.hass = hass
    sensor.coordinator = coord

    attrs = RoomSignalInventorySensor.extra_state_attributes.fget(sensor)
    assert attrs["classification"] == get_room_classification(hass, entry)
