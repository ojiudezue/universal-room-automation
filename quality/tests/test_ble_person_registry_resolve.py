"""BLE-PERSON-SENSOR-REGISTRY-RESOLVE-1: person -> Bermuda device -> sensors
through the REAL entity and device registries (plan
docs/planning/PLANNING_ble_person_sensor_registry_resolve.md rev 2).

Real ``hass`` (pytest-homeassistant-custom-component) with real ``er`` / ``dr``.
The fixture reproduces the live shape (audit §1): Oji has two ``mobile_app``
trackers, one ``private_ble_device`` tracker on device A and one ``bermuda``
tracker on device B; A and B both carry ``('private_ble_device', X)`` (the
same-identifier hazard: the registry index holds one device per identifier).
B holds area ``<uid>``, nearest ``<uid>_range``, per-scanner
``<uid>_<mac>_range`` / ``_range_raw``; most of Oji's per-scanner sensors are
disabled. Oji's phone carries ``distance_to_jaya_3`` (a scanner named after a
person): the old substring match counted it as Jaya's.

Oracles are hand-derived from the plan / audit tables, not from the code.
"""
from __future__ import annotations

import importlib
import itertools
import logging
import os
import sys

import pytest

from test_lock_arrival_hold_real_ha import (  # noqa: F401 - fixture reuse
    _real_core_globals,
    _real_ha_attrs,
    hass,
)

PKG = "custom_components.universal_room_automation"
DOMAIN = "universal_room_automation"

PBLE = "private_ble_device"

# Oji (live ids, audit §1)
OJI = "Oji Udezue"
OJI_X = "8ce182a9fd03aa"            # private_ble identifier == Bermuda uid
OJI_TRACKERS = [
    "device_tracker.phalanxiphone15promaxcflare",   # mobile_app
    "device_tracker.iphone_oji_bermuda_tracker",    # bermuda
    "device_tracker.private_ble_device_8ce182",     # private_ble_device
    "device_tracker.okosisipadmini6_2",             # mobile_app
]
# Jaya
JAYA = "Jaya"
JAYA_X = "249050aabbcc"
JAYA_TRACKERS = [
    "device_tracker.private_ble_device_249050",
    "device_tracker.iphone_jaya_bermuda_tracker",
]

SCANNERS = {  # mac -> scanner name (object-id tail)
    "aa:01": "jaya_3",
    "aa:02": "kitchen",
    "aa:03": "switch_shelly1pmgen3_wifi_ezinnemakeup",
}


# ---------------------------------------------------------------------------
# Module scope: real on-disk URA modules for each test, restored afterwards
# (pattern: test_person_gps_assistive._real_modules).
# ---------------------------------------------------------------------------

_REAL_MODULES = (
    (PKG, "universal_room_automation/__init__.py", "async_unload_entry"),
    (f"{PKG}.const", "universal_room_automation/const.py", "CONF_BERMUDA_AREA_SENSORS"),
    (f"{PKG}.person_ids", "person_ids.py", "tracked_person_entity_id"),
    (f"{PKG}.person_coordinator", "person_coordinator.py", "PersonTrackingCoordinator"),
    (f"{PKG}.aggregation", "aggregation.py", "PersonLocationSensor"),
)


# Real-HA attributes the resolver and coordinator depend on. A legacy donor
# that ``setattr``s stubs onto the REAL module (e.g.
# ``update_coordinator.DataUpdateCoordinator = MagicMock``,
# ``entity_registry.async_get = MagicMock()``) poisons them for every later
# file; the real value of each is defined in its own module.
# Not homeassistant.core: the shared ``_real_ha_attrs`` fixture restores its
# classes from phcc (a fresh core import would mint new class identities).
_HA_HELPER_MODULES = (
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.area_registry",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.event",
    "homeassistant.helpers.dispatcher",
    "homeassistant.components.sensor",
    "homeassistant.components.binary_sensor",
)


def _looks_stubbed(value) -> bool:
    """A donor's stand-in: a Mock (instance or class), ``dict`` / ``Exception``
    in place of a TypedDict / exception class, or a callable defined in a test
    module (``callback = lambda fn: fn``)."""
    from unittest.mock import NonCallableMock

    if isinstance(value, NonCallableMock):
        return True
    if isinstance(value, type) and issubclass(value, NonCallableMock):
        return True
    if value is dict or value is Exception:
        return True
    mod = getattr(value, "__module__", None)
    return isinstance(mod, str) and mod.split(".")[-1].startswith(("test_", "conftest"))


@pytest.fixture(autouse=True)
def _in_memory_storage(hass_storage):
    """Registries in memory, never on disk. The shared ``hass`` fixture
    (async_test_home_assistant without phcc's ``hass_storage``) otherwise
    loads and saves ``.storage/core.entity_registry`` under phcc's
    ``testing_config`` in the venv, so entities from an earlier test or an
    earlier RUN (any worktree) reappear in a fresh hass. Autouse, so it is
    active before ``hass`` starts."""
    yield hass_storage


@pytest.fixture(autouse=True, scope="module")
def _real_ha_helpers(_real_ha_attrs):  # noqa: F811 - real core.callback first
    """Self-sufficiency guard (runs before the shared ``hass`` fixture).

    Legacy donor files ``setattr`` stubs onto REAL HA helper modules at
    collection time (``update_coordinator.DataUpdateCoordinator = MagicMock``,
    ``entity_registry.async_get = MagicMock()``, ...). For every attribute of
    ``_HA_HELPER_MODULES`` that looks stubbed, bind the genuine value from a
    fresh import onto the module object everyone already holds. The prior
    values go back when this file ends (``import_scope(attrs=True)``), so
    the guard changes nothing outside this file.
    """
    from _d7_isolation import import_scope

    with import_scope(("homeassistant",), attrs=True):
        # Stub MODULES (no __file__ / __path__, e.g. a fake
        # homeassistant.util.dt) out first, so the fresh imports bind real ones.
        for name in [k for k, m in sys.modules.items()
                     if k.startswith("homeassistant.")
                     and not getattr(m, "__file__", None)
                     and not getattr(m, "__path__", None)]:
            sys.modules.pop(name, None)
        for name in _HA_HELPER_MODULES:
            held = importlib.import_module(name)
            bad = [a for a, v in list(vars(held).items())
                   if not a.startswith("__") and _looks_stubbed(v)]
            if not bad:
                continue
            # Prefer the ORIGINAL object, still bound in a real module that
            # imported it before the donor ran: a fresh import mints a new
            # class (MockConfigEntry subclasses the original ConfigEntry).
            fresh = None
            for a in bad:
                real = _original_from_importers(name, a, held)
                if real is None:
                    if fresh is None:
                        sys.modules.pop(name, None)
                        try:
                            fresh = importlib.import_module(name)
                        finally:
                            sys.modules[name] = held
                    real = vars(fresh).get(a)
                if real is not None and not _looks_stubbed(real):
                    setattr(held, a, real)
        yield


def _original_from_importers(modname, attr, held):
    for other_name, other in list(sys.modules.items()):
        if other is held or not other_name.startswith(("homeassistant", "pytest_homeassistant")):
            continue
        if not getattr(other, "__file__", None):
            continue
        try:
            val = vars(other).get(attr)
        except TypeError:
            continue
        if (val is not None and not _looks_stubbed(val)
                and getattr(val, "__module__", None) == modname
                and getattr(val, "__qualname__", None) == attr):
            return val
    return None


_REAL_CC_DIR = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")
)


def _is_real(mod, suffix, attr):
    from unittest.mock import Mock
    if mod is None or isinstance(mod, Mock):
        return False
    f = getattr(mod, "__file__", None)
    if not (isinstance(f, str) and f.replace("\\", "/").endswith(suffix)):
        return False
    if attr is not None and attr not in vars(mod):
        return False
    # An on-disk module imported while a donor had the HA helpers stubbed
    # keeps those stubs bound (e.g. PersonTrackingCoordinator subclassing
    # MagicMock): not usable, re-import it.
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
    cls = vars(mod).get(attr) if attr else None
    if isinstance(cls, type) and cls.__name__.endswith("Coordinator"):
        if not issubclass(cls, DataUpdateCoordinator):
            return False
    if isinstance(cls, type) and any(_looks_stubbed(b) for b in cls.__mro__[1:]):
        return False  # e.g. PersonLocationSensor built on a stub SensorEntity
    for alias, modname in (("er", "homeassistant.helpers.entity_registry"),
                           ("dr", "homeassistant.helpers.device_registry")):
        bound = vars(mod).get(alias)
        if bound is not None and bound is not sys.modules.get(modname):
            return False
    return True


@pytest.fixture(autouse=True)
def _real_modules():
    replaced: dict = {}
    _missing = object()
    for name, suffix, attr in _REAL_MODULES:
        cur = sys.modules.get(name)
        if _is_real(cur, suffix, attr):
            continue
        replaced[name] = cur if cur is not None else _missing
        sys.modules.pop(name, None)
    # The ``custom_components`` namespace package itself: a donor's stub
    # (``__path__ = []``) hides the real URA package from the imports below.
    cc = sys.modules.get("custom_components")
    if replaced and cc is not None and _REAL_CC_DIR not in [
        os.path.realpath(p) for p in (getattr(cc, "__path__", None) or [])
    ]:
        replaced["custom_components"] = cc
        sys.modules.pop("custom_components", None)
    before = set(sys.modules)
    try:
        if replaced:
            for name, _s, _a in _REAL_MODULES:
                importlib.import_module(name)
        yield
    finally:
        if replaced:
            for name in set(sys.modules) - before:
                if name.startswith(PKG) or name == "custom_components":
                    sys.modules.pop(name, None)
            for name, prev in replaced.items():
                if prev is _missing:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = prev


def _pc():
    return importlib.import_module(f"{PKG}.person_coordinator")


# ---------------------------------------------------------------------------
# Registry fixture builders (real er / dr)
# ---------------------------------------------------------------------------


class _World:
    def __init__(self, hass):
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er
        from pytest_homeassistant_custom_component.common import MockConfigEntry

        self.hass = hass
        self.dr = dr.async_get(hass)
        self.er = er.async_get(hass)
        # The enum of the module that built THIS registry instance: read from
        # the class's own globals, not sys.modules (a repaired ``async_get``
        # can come from a fresh import of entity_registry, whose enum is a
        # different class from the one in sys.modules).
        self.Disabler = type(self.er).async_get_or_create.__globals__[
            "RegistryEntryDisabler"
        ]
        self.berm = MockConfigEntry(domain="bermuda", entry_id="berm")
        self.berm.add_to_hass(hass)
        self.pble = MockConfigEntry(domain=PBLE, entry_id="pble")
        self.pble.add_to_hass(hass)
        self.mobile = MockConfigEntry(domain="mobile_app", entry_id="mob")
        self.mobile.add_to_hass(hass)
        self.devices: dict[str, str] = {}

    def _collide(self, device_id, x):
        """Give ``device_id`` the shared ``('private_ble_device', x)``
        identifier through the registry's own update path (the collision
        HA allows for get_or_create, device_registry.py:983-985)."""
        self.dr._async_update_device(
            device_id, merge_identifiers={(PBLE, x)}, allow_collisions=True,
        )

    def private_ble_device(self, x, tracker_eid):
        dev = self.dr.async_get_or_create(
            config_entry_id=self.pble.entry_id,
            identifiers={("tmp_pble", x)},
            name=f"pble {x}",
        )
        self._collide(dev.id, x)
        self.er.async_get_or_create(
            "device_tracker", PBLE, f"{x}_device_tracker",
            config_entry=self.pble, device_id=dev.id,
            suggested_object_id=tracker_eid.split(".", 1)[1],
        )
        self.devices[f"pble:{x}"] = dev.id
        return dev.id

    def bermuda_device(self, x, phone, tracker_eid, *, disabled_macs=(),
                       with_tracker=True):
        dev = self.dr.async_get_or_create(
            config_entry_id=self.berm.entry_id,
            identifiers={("bermuda", x)},
            name=phone,
        )
        self._collide(dev.id, x)
        if with_tracker:
            self.er.async_get_or_create(
                "device_tracker", "bermuda", x, config_entry=self.berm,
                device_id=dev.id, suggested_object_id=tracker_eid.split(".", 1)[1],
            )
        self.bermuda_sensors(dev.id, x, phone, disabled_macs=disabled_macs)
        self.devices[f"berm:{x}"] = dev.id
        return dev.id

    def bermuda_sensors(self, dev_id, x, phone, *, disabled_macs=()):
        def s(uid, obj, disabled=False):
            return self.er.async_get_or_create(
                "sensor", "bermuda", uid, config_entry=self.berm,
                device_id=dev_id, suggested_object_id=obj,
                disabled_by=self.Disabler.INTEGRATION if disabled else None,
            ).entity_id

        s(x, f"{phone}_area")
        s(f"{x}_range", f"{phone}_distance")
        s(f"{x}_scanner", f"{phone}_nearest_scanner")
        s(f"{x}_rssi", f"{phone}_nearest_rssi")
        s(f"{x}_floor", f"{phone}_floor")
        for mac, name in SCANNERS.items():
            off = mac in disabled_macs
            s(f"{x}_{mac}_range", f"{phone}_distance_to_{name}", off)
            s(f"{x}_{mac}_range_raw", f"{phone}_unfiltered_distance_to_{name}", off)

    def mobile_tracker(self, eid):
        self.er.async_get_or_create(
            "device_tracker", "mobile_app", eid, config_entry=self.mobile,
            suggested_object_id=eid.split(".", 1)[1],
        )

    def person(self, pid, trackers):
        self.hass.states.async_set(pid, "home", {"device_trackers": list(trackers)})


def _oji(w, *, pble_first=True, trackers=OJI_TRACKERS, disabled_macs=("aa:02", "aa:03")):
    """Oji's live shape. ``pble_first`` picks which device holds the
    identifier-index slot (the one indexed LAST wins)."""
    w.mobile_tracker(OJI_TRACKERS[0])
    w.mobile_tracker(OJI_TRACKERS[3])
    if pble_first:
        w.private_ble_device(OJI_X, OJI_TRACKERS[2])
        w.bermuda_device(OJI_X, "iphone_oji", OJI_TRACKERS[1], disabled_macs=disabled_macs)
    else:
        w.bermuda_device(OJI_X, "iphone_oji", OJI_TRACKERS[1], disabled_macs=disabled_macs)
        w.private_ble_device(OJI_X, OJI_TRACKERS[2])
    w.person("person.oji_udezue", trackers)


def _jaya(w):
    w.private_ble_device(JAYA_X, JAYA_TRACKERS[0])
    w.bermuda_device(JAYA_X, "iphone_jaya", JAYA_TRACKERS[1])
    w.person("person.jaya", JAYA_TRACKERS)


def _coord(hass, options=None):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN, entry_id="ura",
        data={"tracked_persons": [OJI, JAYA]}, options=options or {},
    )
    entry.add_to_hass(hass)
    # Same as test_person_gps_assistive: the coordinator does not pass
    # config_entry, and HA's frame helper reports that; not under test.
    from unittest.mock import patch
    import homeassistant.helpers.frame as _frame
    with patch.object(_frame, "report_usage", lambda *a, **k: None):
        return _pc().PersonTrackingCoordinator(hass, entry)


def _pin_area_scanners(coord, scanners=("jaya_3", "kitchen")):
    async def _scan(_area):
        return list(scanners)
    coord._get_area_scanners = _scan


def _set_all(hass, w, value):
    for e in list(w.er.entities.values()):
        if e.platform == "bermuda" and e.domain == "sensor":
            hass.states.async_set(e.entity_id, value)


# ---------------------------------------------------------------------------
# D1 resolver
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_a_any_tracker_order(hass):
    w = _World(hass)
    _oji(w)
    coord = _coord(hass)
    berm_dev = w.devices[f"berm:{OJI_X}"]
    seen = 0
    for perm in itertools.permutations(OJI_TRACKERS):
        w.person("person.oji_udezue", perm)
        assert coord._bermuda_device_for_person("person.oji_udezue") == (
            berm_dev, "a", OJI_X,
        ), perm
        seen += 1
    assert seen == 24


@pytest.mark.asyncio
@pytest.mark.parametrize("pble_first", [True, False])
async def test_route_b_same_identifier_twin(hass, pble_first):
    w = _World(hass)
    no_bermuda = [t for t in OJI_TRACKERS if "bermuda" not in t]
    _oji(w, pble_first=pble_first, trackers=no_bermuda)
    coord = _coord(hass)
    berm_dev = w.devices[f"berm:{OJI_X}"]
    pble_dev = w.devices[f"pble:{OJI_X}"]
    assert berm_dev != pble_dev
    # Index-slot hazard is real in this fixture: one order hands the slot
    # to the private_ble device.
    slot = w.dr.async_get_device(identifiers={(PBLE, OJI_X)}).id
    assert slot == (berm_dev if pble_first else pble_dev)
    assert coord._bermuda_device_for_person("person.oji_udezue") == (
        berm_dev, "b", OJI_X,
    )
    area = await coord._find_bermuda_area_sensor(OJI)
    assert area == "sensor.iphone_oji_area"


@pytest.mark.asyncio
async def test_route_b_ignores_own_and_non_bermuda_devices(hass):
    """Route (b) candidates are OTHER devices carrying X that own a bermuda
    entity: a third device with X but no bermuda entity, and a bermuda
    entity sitting on the private_ble device itself, must not count."""
    w = _World(hass)
    no_bermuda = [t for t in OJI_TRACKERS if "bermuda" not in t]
    _oji(w, trackers=no_bermuda)
    pble_dev = w.devices[f"pble:{OJI_X}"]
    other = MockConfigEntryFactory(hass, "other_integration")
    third = w.dr.async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("tmp_other", OJI_X)},
        name="third",
    )
    w._collide(third.id, OJI_X)
    w.er.async_get_or_create(
        "sensor", "other_integration", "third_sensor", config_entry=other,
        device_id=third.id,
    )
    w.er.async_get_or_create(
        "binary_sensor", "bermuda", "stray_on_pble", config_entry=w.berm,
        device_id=pble_dev,
    )
    coord = _coord(hass)
    assert coord._bermuda_device_for_person("person.oji_udezue") == (
        w.devices[f"berm:{OJI_X}"], "b", OJI_X,
    )


def MockConfigEntryFactory(hass, domain):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    e = MockConfigEntry(domain=domain, entry_id=domain)
    e.add_to_hass(hass)
    return e


@pytest.mark.asyncio
async def test_two_bermuda_trackers_unresolved(hass):
    w = _World(hass)
    _oji(w)
    _jaya(w)
    w.person("person.oji_udezue", OJI_TRACKERS + [JAYA_TRACKERS[1]])
    coord = _coord(hass)
    assert coord._bermuda_device_for_person("person.oji_udezue") == (
        None, "multiple_bermuda_trackers", None,
    )
    assert await coord._find_bermuda_area_sensor(OJI) is None
    assert coord._bermuda_resolve_misses == {(OJI, "multiple_bermuda_trackers"): 1}


@pytest.mark.asyncio
async def test_no_bermuda_tracker_unresolved_counted(hass):
    w = _World(hass)
    w.mobile_tracker(OJI_TRACKERS[0])
    w.person("person.oji_udezue", [OJI_TRACKERS[0]])
    # A name-matching Bermuda area sensor exists on NO device of Oji's: the
    # old Strategy 3/4 name match would return it.
    hass.states.async_set("sensor.oji_udezue_area", "kitchen")
    coord = _coord(hass)
    assert await coord._find_bermuda_area_sensor(OJI) is None
    assert await coord._find_bermuda_area_sensor(OJI) is None
    assert coord._bermuda_resolve_misses == {(OJI, "no_bermuda_tracker"): 2}
    # No person state at all
    assert coord._bermuda_device_for_person("person.nobody") == (
        None, "no_person_state", None,
    )


@pytest.mark.asyncio
async def test_tracker_no_device_unresolved(hass):
    w = _World(hass)
    w.er.async_get_or_create(
        "device_tracker", "bermuda", OJI_X, config_entry=w.berm,
        suggested_object_id="iphone_oji_bermuda_tracker",
    )
    w.person("person.oji_udezue", ["device_tracker.iphone_oji_bermuda_tracker"])
    coord = _coord(hass)
    assert coord._bermuda_device_for_person("person.oji_udezue") == (
        None, "tracker_no_device", None,
    )


@pytest.mark.asyncio
async def test_private_ble_without_twin_unresolved(hass):
    w = _World(hass)
    w.private_ble_device(OJI_X, OJI_TRACKERS[2])
    w.person("person.oji_udezue", [OJI_TRACKERS[2]])
    coord = _coord(hass)
    assert coord._bermuda_device_for_person("person.oji_udezue") == (
        None, "private_ble_no_twin", None,
    )


@pytest.mark.asyncio
async def test_late_bermuda_load_resolves_next_tick(hass):
    w = _World(hass)
    # Tick 1: person lists the Bermuda tracker but Bermuda has not loaded
    # (no registry entry, no device).
    w.mobile_tracker(OJI_TRACKERS[0])
    w.person("person.oji_udezue", OJI_TRACKERS)
    coord = _coord(hass)
    assert await coord._find_bermuda_area_sensor(OJI) is None
    # Bermuda loads; the next tick resolves (no stale cache).
    w.private_ble_device(OJI_X, OJI_TRACKERS[2])
    w.bermuda_device(OJI_X, "iphone_oji", OJI_TRACKERS[1])
    assert await coord._find_bermuda_area_sensor(OJI) == "sensor.iphone_oji_area"


@pytest.mark.asyncio
async def test_warn_once_on_second_miss(hass, caplog):
    w = _World(hass)
    w.mobile_tracker(OJI_TRACKERS[0])
    w.person("person.oji_udezue", [OJI_TRACKERS[0]])
    coord = _coord(hass)
    caplog.set_level(logging.INFO, logger=f"{PKG}.person_coordinator")

    def warns():
        return [r for r in caplog.records
                if r.levelno == logging.WARNING and "No Bermuda area sensor" in r.getMessage()]

    await coord._find_bermuda_area_sensor(OJI)
    assert warns() == []
    await coord._find_bermuda_area_sensor(OJI)
    assert len(warns()) == 1
    assert "no_bermuda_tracker" in warns()[0].getMessage()
    await coord._find_bermuda_area_sensor(OJI)
    assert len(warns()) == 1
    assert coord._bermuda_resolve_misses[(OJI, "no_bermuda_tracker")] == 3
    # Recovery -> one INFO
    w.private_ble_device(OJI_X, OJI_TRACKERS[2])
    w.bermuda_device(OJI_X, "iphone_oji", OJI_TRACKERS[1])
    w.person("person.oji_udezue", OJI_TRACKERS)
    assert await coord._find_bermuda_area_sensor(OJI) == "sensor.iphone_oji_area"
    infos = [r for r in caplog.records
             if r.levelno == logging.INFO and "resolved again" in r.getMessage()]
    assert len(infos) == 1


@pytest.mark.asyncio
async def test_resolved_device_without_area_sensor_counted_warn_once(hass, caplog):
    """Device resolves but its area sensor is disabled: a counted miss
    'no_area_sensor', one WARN on the second tick, not one per tick."""
    w = _World(hass)
    _oji(w)
    w.er.async_update_entity(
        "sensor.iphone_oji_area", disabled_by=w.Disabler.USER,
    )
    coord = _coord(hass)
    caplog.set_level(logging.DEBUG, logger=f"{PKG}.person_coordinator")
    for _ in range(3):
        assert await coord._find_bermuda_area_sensor(OJI) is None
    warns = [r for r in caplog.records
             if r.levelno == logging.WARNING and "No Bermuda area sensor" in r.getMessage()]
    assert len(warns) == 1
    assert "route=a" in warns[0].getMessage()
    assert "reason=no_area_sensor" in warns[0].getMessage()
    assert coord._bermuda_resolve_misses == {(OJI, "no_area_sensor"): 3}


@pytest.mark.asyncio
async def test_fire_check_stats_per_person(hass):
    """Fire check: resolutions and misses per person, surfaced on the
    Person Tracking Status diagnostic (unrecorded attribute)."""
    w = _World(hass)
    _oji(w)
    hass.states.async_set("person.jaya", "home", {"device_trackers": []})
    coord = _coord(hass)
    await coord._find_bermuda_area_sensor(OJI)
    await coord._find_bermuda_area_sensor(OJI)
    await coord._find_bermuda_area_sensor(JAYA)
    stats = coord.get_bermuda_resolve_stats()
    assert stats == {
        JAYA: {"resolved": 0, "unresolved": 1,
               "misses": {"no_bermuda_tracker": 1},
               "last_route": "none", "last_reason": "no_bermuda_tracker"},
        OJI: {"resolved": 2, "unresolved": 0, "misses": {},
              "last_route": "a", "last_reason": None},
    }
    assert coord.get_diagnostic_data()["bermuda_resolve"] == stats

    agg = importlib.import_module(f"{PKG}.aggregation")
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    hass.data.setdefault(DOMAIN, {})["person_coordinator"] = coord
    diag = agg.PersonTrackingDiagnosticSensor(
        hass, MockConfigEntry(domain=DOMAIN, entry_id="d"),
    )
    assert diag.extra_state_attributes["bermuda_resolve"] == stats
    assert "bermuda_resolve" in diag._unrecorded_attributes


# ---------------------------------------------------------------------------
# D2 area sensor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_area_sensor_matches_today_for_four(hass):
    w = _World(hass)
    _oji(w)
    _jaya(w)
    w.private_ble_device("ezaa", "device_tracker.ezinne_iphone")
    w.bermuda_device("ezaa", "ezinne_iphone", "device_tracker.ezinne_iphone_bermuda_tracker")
    w.person("person.ezinne", ["device_tracker.ezinne_iphone",
                               "device_tracker.ezinne_iphone_bermuda_tracker"])
    w.private_ble_device("ziaa", "device_tracker.ziri_iphone")
    w.bermuda_device("ziaa", "iphone_ziri", "device_tracker.iphone_ziri_bermuda_tracker")
    w.person("person.ziri", ["device_tracker.ziri_iphone",
                             "device_tracker.iphone_ziri_bermuda_tracker"])
    _set_all(hass, w, "kitchen")
    coord = _coord(hass)
    assert await coord._find_bermuda_area_sensor(OJI) == "sensor.iphone_oji_area"
    assert await coord._find_bermuda_area_sensor("Ezinne") == "sensor.ezinne_iphone_area"
    assert await coord._find_bermuda_area_sensor("Ziri") == "sensor.iphone_ziri_area"
    assert await coord._find_bermuda_area_sensor(JAYA) == "sensor.iphone_jaya_area"


@pytest.mark.asyncio
async def test_area_sensor_survives_rename(hass):
    w = _World(hass)
    _oji(w)
    old = "sensor.iphone_oji_area"
    w.er.async_update_entity(old, new_entity_id="sensor.phone_x_area")
    coord = _coord(hass)
    assert await coord._find_bermuda_area_sensor(OJI) == "sensor.phone_x_area"


@pytest.mark.asyncio
async def test_override_still_wins(hass):
    w = _World(hass)
    _oji(w)
    hass.states.async_set("sensor.custom_oji_area", "office")
    coord = _coord(hass, options={"bermuda_area_sensors": {OJI: "sensor.custom_oji_area"}})
    from importlib import import_module
    assert import_module(f"{PKG}.const").CONF_BERMUDA_AREA_SENSORS == "bermuda_area_sensors"
    assert await coord._find_bermuda_area_sensor(OJI) == "sensor.custom_oji_area"


# ---------------------------------------------------------------------------
# D3 distance set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_foreign_phone_sensors(hass):
    """Oji's phone sees the Jaya-bedroom scanner at 2 ft; Jaya's own
    sensors are dead. Jaya must NOT inherit Oji's reading (old substring
    code: 'jaya' in sensor.iphone_oji_distance_to_jaya_3 -> 0.9)."""
    w = _World(hass)
    _oji(w, disabled_macs=())
    _jaya(w)
    _set_all(hass, w, "unavailable")
    hass.states.async_set("sensor.iphone_oji_distance_to_jaya_3", "2.0")
    coord = _coord(hass)
    _pin_area_scanners(coord)
    dev = w.devices[f"berm:{JAYA_X}"]
    _area, dist = coord._bermuda_person_sensors(dev, JAYA_X)
    # One sensor per scanner: the filtered one (review A-L1).
    assert sorted(dist) == sorted(
        f"sensor.iphone_jaya_distance_to_{n}" for n in SCANNERS.values()
    )
    assert await coord._calculate_confidence(JAYA, "jaya_3", "jaya_bedroom") == 0.3


@pytest.mark.asyncio
async def test_oji_resolves_own_device(hass):
    w = _World(hass)
    _oji(w)   # aa:02 / aa:03 disabled -> only aa:01 range + range_raw enabled
    _set_all(hass, w, "unavailable")
    coord = _coord(hass)
    _pin_area_scanners(coord)
    _area, dist = coord._bermuda_person_sensors(w.devices[f"berm:{OJI_X}"], OJI_X)
    assert sorted(dist) == ["sensor.iphone_oji_distance_to_jaya_3"]
    # Old code: no 'oji_udezue' in any entity id -> 0.5. New: inputs all
    # unavailable -> 0.3.
    assert await coord._calculate_confidence(OJI, "jaya_3", "jaya_bedroom") == 0.3
    # And a live own reading drives it: 2 ft from an area scanner -> 0.9.
    hass.states.async_set("sensor.iphone_oji_distance_to_jaya_3", "2.0")
    assert await coord._calculate_confidence(OJI, "jaya_3", "jaya_bedroom") == 0.9


@pytest.mark.asyncio
async def test_never_enables_disabled(hass):
    w = _World(hass)
    _oji(w)
    _jaya(w)
    _set_all(hass, w, "unavailable")
    coord = _coord(hass)
    _pin_area_scanners(coord)
    before = {e.entity_id: e.disabled_by for e in w.er.entities.values()}
    assert sum(1 for v in before.values() if v is not None) == 4
    calls = []
    orig = w.er.async_update_entity

    def spy(*a, **k):
        calls.append((a, k))
        return orig(*a, **k)

    w.er.async_update_entity = spy
    try:
        await coord._find_bermuda_area_sensor(OJI)
        await coord._calculate_confidence(OJI, "jaya_3", "x")
        await coord._calculate_confidence(JAYA, "jaya_3", "x")
    finally:
        w.er.async_update_entity = orig
    assert calls == []
    after = {e.entity_id: e.disabled_by for e in w.er.entities.values()}
    assert after == before


@pytest.mark.asyncio
async def test_nearest_range_sensor_excluded(hass):
    """<uid>_range (nearest distance) and the _scanner/_rssi/_floor siblings
    are not per-scanner distance sensors. The nearest one reads 1 ft: if it
    leaked into the set, the area-scanner match ('distance' contains no
    scanner name, but the set must still exclude it) is pinned directly."""
    w = _World(hass)
    _oji(w, disabled_macs=())
    dev = w.devices[f"berm:{OJI_X}"]
    # Off-shape entities on the same device: a range-suffixed sensor whose
    # unique_id is not <uid>_..., and a non-sensor entity with a per-scanner
    # unique_id. Neither is a per-scanner distance sensor.
    w.er.async_get_or_create(
        "sensor", "bermuda", "otheruid_aa:09_range", config_entry=w.berm,
        device_id=dev, suggested_object_id="stray_range",
    )
    w.er.async_get_or_create(
        "number", "bermuda", f"{OJI_X}_aa:09_range", config_entry=w.berm,
        device_id=dev, suggested_object_id="iphone_oji_range_number",
    )
    coord = _coord(hass)
    _area, dist = coord._bermuda_person_sensors(dev, OJI_X)
    assert "sensor.stray_range" not in dist
    assert "number.iphone_oji_range_number" not in dist
    assert "sensor.iphone_oji_distance" not in dist
    assert "sensor.iphone_oji_area" not in dist
    assert "sensor.iphone_oji_nearest_scanner" not in dist
    assert len(dist) == 3   # 3 scanners, one sensor each


@pytest.mark.asyncio
async def test_scanner_counted_once_range_and_raw(hass):
    """Review A-L1: one scanner with BOTH a filtered and a raw distance
    sensor at 7 ft (close, not very close, at high=10) is ONE close scanner
    -> 0.7. Counting both gave close_scanners == 2 -> 0.9."""
    w = _World(hass)
    _oji(w)   # only aa:01 (jaya_3) enabled: range + range_raw
    _set_all(hass, w, "unavailable")
    hass.states.async_set("sensor.iphone_oji_distance_to_jaya_3", "7.0")
    hass.states.async_set("sensor.iphone_oji_unfiltered_distance_to_jaya_3", "7.0")
    coord = _coord(hass)
    coord.high_confidence_distance = 10
    _pin_area_scanners(coord)
    assert await coord._calculate_confidence(OJI, "jaya_3", "jaya_bedroom") == 0.7


@pytest.mark.asyncio
async def test_raw_used_only_when_filtered_absent(hass):
    """Fallback: the filtered sensor disabled -> the raw one stands in for
    that scanner; with the filtered one enabled the raw one is not read."""
    w = _World(hass)
    _oji(w)
    dev = w.devices[f"berm:{OJI_X}"]
    coord = _coord(hass)
    _area, dist = coord._bermuda_person_sensors(dev, OJI_X)
    assert dist == ["sensor.iphone_oji_distance_to_jaya_3"]
    w.er.async_update_entity(
        "sensor.iphone_oji_distance_to_jaya_3", disabled_by=w.Disabler.USER,
    )
    _area, dist = coord._bermuda_person_sensors(dev, OJI_X)
    assert dist == ["sensor.iphone_oji_unfiltered_distance_to_jaya_3"]


@pytest.mark.asyncio
async def test_registry_error_unresolved(hass):
    w = _World(hass)
    _oji(w)
    coord = _coord(hass)
    pc = _pc()
    orig = pc.er.async_get

    def boom(_h):
        raise RuntimeError("registry gone")

    pc.er.async_get = boom
    try:
        assert coord._bermuda_device_for_person("person.oji_udezue") == (
            None, "registry_error", None,
        )
    finally:
        pc.er.async_get = orig


# ---------------------------------------------------------------------------
# Wire-in: the tick path (_async_update_data) consumes both helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_uses_registry_area_and_confidence(hass):
    w = _World(hass)
    _oji(w)
    _set_all(hass, w, "unavailable")
    hass.states.async_set("sensor.iphone_oji_area", "jaya_3")
    hass.states.async_set("sensor.iphone_oji_distance_to_jaya_3", "2.0")
    coord = _coord(hass)
    coord.tracked_persons = [OJI]
    _pin_area_scanners(coord)
    data = await coord._async_update_data()
    assert data[OJI]["confidence"] == 0.9
    assert data[OJI]["method"] == "bermuda"


@pytest.mark.asyncio
async def test_tick_resolves_once_per_person(hass):
    """Review A-L3: one tick = ONE resolver call per person, its result fed
    to both the area lookup and the confidence calc; a second tick resolves
    afresh (no cross-tick cache)."""
    w = _World(hass)
    _oji(w)
    _set_all(hass, w, "unavailable")
    hass.states.async_set("sensor.iphone_oji_area", "jaya_3")
    hass.states.async_set("sensor.iphone_oji_distance_to_jaya_3", "2.0")
    coord = _coord(hass)
    coord.tracked_persons = [OJI]
    _pin_area_scanners(coord)
    calls = []
    orig = coord._bermuda_device_for_person

    def spy(pid):
        calls.append(pid)
        return orig(pid)

    coord._bermuda_device_for_person = spy
    data = await coord._async_update_data()
    assert data[OJI]["confidence"] == 0.9
    assert calls == ["person.oji_udezue"]
    await coord._async_update_data()
    assert calls == ["person.oji_udezue"] * 2


@pytest.mark.asyncio
async def test_tick_room_change_event_carries_ble_facts(hass):
    """MUSIC-FOLLOWING-TRANSFER-REPAIR-1 D1, review C-8 (G1-G3): the PRODUCER
    puts ``method``, ``bermuda_area`` and ``area_sensor`` on the
    ``ura_person_location_change`` event it fires when a tick moves the
    person (the detector only copies them)."""
    w = _World(hass)
    _oji(w)
    _set_all(hass, w, "unavailable")
    hass.states.async_set("sensor.iphone_oji_area", "jaya_3")
    coord = _coord(hass)
    coord.tracked_persons = [OJI]
    _pin_area_scanners(coord)
    events = []
    unsub = hass.bus.async_listen(
        "ura_person_location_change", lambda e: events.append(dict(e.data)))
    try:
        coord.data = await coord._async_update_data()   # first fix: no move
        await hass.async_block_till_done()
        assert events == []
        first_room = coord.data[OJI]["location"]
        hass.states.async_set("sensor.iphone_oji_area", "kitchen")
        coord.data = await coord._async_update_data()
        await hass.async_block_till_done()
    finally:
        unsub()
    assert len(events) == 1, (first_room, events)
    assert events[0]["previous_location"] == first_room
    ev = events[0]
    assert ev["method"] == "bermuda"
    assert ev["bermuda_area"] == "kitchen"
    assert ev["area_sensor"] == "sensor.iphone_oji_area"
    assert ev["previous_location"] != ev["current_location"]


# ---------------------------------------------------------------------------
# D4 PersonLocationSensor: no Bermuda name scan, coordinator listener only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_location_sensor_no_bermuda_scan_warning(hass, caplog):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    agg = importlib.import_module(f"{PKG}.aggregation")
    # A state matching the old sensor.bermuda_<first>_* scan: the old code
    # would have attached a state listener to it.
    hass.states.async_set("sensor.bermuda_oji_kitchen", "1")

    listeners = []

    class _PC:
        def async_add_listener(self, cb):
            listeners.append(cb)
            return lambda: listeners.remove(cb)

        def get_person_location(self, _p):
            return "kitchen"

        def get_person_confidence(self, _p):
            return 0.3

        def __getattr__(self, _n):
            return lambda *a, **k: None

    hass.data.setdefault(DOMAIN, {})["person_coordinator"] = _PC()
    entry = MockConfigEntry(domain=DOMAIN, entry_id="agg")
    sensor = agg.PersonLocationSensor(hass, entry, "oji_udezue")
    caplog.set_level(logging.DEBUG, logger=f"{PKG}.aggregation")
    await sensor.async_added_to_hass()
    try:
        assert not [r for r in caplog.records if "No Bermuda sensors found" in r.getMessage()]
        assert len(sensor._unsub_state_listeners) == 1
        assert sensor._unsub_decay_timer is not None
        assert not hasattr(sensor, "_find_bermuda_sensors")
    finally:
        await sensor.async_will_remove_from_hass()
        unsub = getattr(sensor, "_agg_retry_unsub", None)
        if unsub:
            unsub()
