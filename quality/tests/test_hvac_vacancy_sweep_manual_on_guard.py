"""Regression anchor for HVAC zone-vacancy sweep FAN-MANUAL-1 guard.

The dual-tier hold check at
``hvac.py::HVACCoordinator._execute_vacancy_sweep`` (~lines 2419-2471,
FAN-MANUAL-1 room-tier + HVAC-tier lookup) had NO test coverage — no
test in the suite reached ``_execute_vacancy_sweep`` at all. Validator
mutation drill: neutering the guard leaves the full suite green. This
file drives the PRODUCTION ``_execute_vacancy_sweep`` (bound method,
called with `types.MethodType` on an instance built via ``__new__`` +
manual attribute injection so we skip the coordinator's heavy init).
The method's body is what we exercise; the guard discriminates between
a room whose fan carries a live manual-ON hold (skipped) vs a sibling
room whose fan does NOT (swept).

Harness pattern mirrors ``test_fan_manual_on_hold_hvac_tier.py`` for
sibling-module mocking, extended to cover the additional siblings
hvac.py depends on (base, hvac_covers, hvac_egress, hvac_override,
hvac_predict, hvac_preset, hvac_setpoint).
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# HA module mocking (ported from test_fan_manual_on_hold_hvac_tier.py)
# ---------------------------------------------------------------------------

def _mock_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_ha_mods: dict = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
        "CALLBACK_TYPE": object,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": _mock_module(
        "homeassistant.const",
        SERVICE_TURN_ON="turn_on",
        SERVICE_TURN_OFF="turn_off",
        STATE_ON="on",
        STATE_OFF="off",
        STATE_UNAVAILABLE="unavailable",
        STATE_UNKNOWN="unknown",
    ),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict, "EntityCategory": _mock_cls(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _mock_cls(),
        "async_track_time_interval": lambda hass, cb, interval: _mock_cls(),
        "async_call_later": lambda hass, delay, cb: _mock_cls(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda hass, signal, cb: _mock_cls(),
        "async_dispatcher_send": lambda hass, signal, data=None: None,
    },
    "homeassistant.helpers.storage": {"Store": _mock_cls},
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {"is_up": lambda hass: True},
    "homeassistant.util": {},
    "homeassistant.components": {},
    "homeassistant.components.recorder": {"get_instance": _mock_cls()},
    "homeassistant.components.recorder.history": {
        "get_significant_states": _mock_cls(),
    },
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(), "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
}

_dt_now_fn = lambda: datetime.now(timezone.utc)  # noqa: E731


def _parse_dt(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


_dt_mock = _mock_module(
    "homeassistant.util.dt",
    utcnow=lambda: _dt_now_fn(),
    now=lambda: _dt_now_fn(),
    as_local=lambda dt: dt,
    parse_datetime=_parse_dt,
)

for _name, _attrs in _ha_mods.items():
    if isinstance(_attrs, dict):
        _existing = sys.modules.get(_name)
        if _existing is None:
            sys.modules[_name] = _mock_module(_name, **_attrs)
        else:
            for _k, _v in _attrs.items():
                setattr(_existing, _k, _v)
    else:
        sys.modules.setdefault(_name, _attrs)

# Snapshot the ORIGINAL homeassistant.util.dt BEFORE our mock clobbers it,
# so we can restore it at the end of module load and not pollute sibling
# tests (e.g. safety_coordinator TVOC uses naive datetime.utcnow() and
# breaks if our offset-aware mock stays live).
_MISSING = object()
_HA_DT_ORIG = sys.modules.get("homeassistant.util.dt", _MISSING)
sys.modules["homeassistant.util.dt"] = _dt_mock
sys.modules.setdefault("aiosqlite", MagicMock())


_project_root = os.path.join(os.path.dirname(__file__), "..", "..")
_ura_root = os.path.join(
    _project_root, "custom_components", "universal_room_automation",
)


def _load_module(full_name: str, filepath: str) -> types.ModuleType:
    """Spec-load the REAL module, replacing any prior stub.

    Test-suite hygiene (2026-08-10): other test files register stub
    ``MagicMock``s or namespace shells for URA submodules. If we
    respect those stubs, the chain-load of hvac.py hits attribute
    misses (e.g. `cannot import CONF_COVERS from const`). Force a
    real load when the existing entry lacks ``__file__`` (mirrors the
    guard in ``test_reboot_pickup_d2.py::_load``).
    """
    existing = sys.modules.get(full_name)
    if (
        existing is not None
        and isinstance(existing, types.ModuleType)
        and isinstance(getattr(existing, "__file__", None), str)
        and os.path.isfile(existing.__file__)
    ):
        # A legitimately-loaded real module — reuse it.
        return existing
    spec = importlib.util.spec_from_file_location(full_name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


if "custom_components" not in sys.modules:
    _cc_pkg = _mock_module("custom_components")
    _cc_pkg.__path__ = [os.path.join(_project_root, "custom_components")]
    sys.modules["custom_components"] = _cc_pkg
else:
    # Repair another test's shim that may have left __path__ empty —
    # otherwise sibling test files that do `_ura.__path__[0]` will trip.
    _existing_cc = sys.modules["custom_components"]
    if not getattr(_existing_cc, "__path__", None):
        _existing_cc.__path__ = [os.path.join(_project_root, "custom_components")]
if "custom_components.universal_room_automation" not in sys.modules:
    _ura_pkg = _mock_module("custom_components.universal_room_automation")
    _ura_pkg.__file__ = os.path.join(_ura_root, "__init__.py")
    _ura_pkg.__path__ = [_ura_root]
    sys.modules["custom_components.universal_room_automation"] = _ura_pkg
else:
    _existing_ura = sys.modules["custom_components.universal_room_automation"]
    if not getattr(_existing_ura, "__path__", None):
        _existing_ura.__path__ = [_ura_root]
    if not getattr(_existing_ura, "__file__", None):
        _existing_ura.__file__ = os.path.join(_ura_root, "__init__.py")
# Snapshot every sys.modules entry we're about to clobber so we can restore
# them at the end of collection — otherwise our force-reload pollutes state
# that later-collected test modules depend on (empirically breaks ~11 sibling
# tests). Save the ORIGINAL reference; None marker means the key was absent.
_SNAPSHOT_KEYS = [
    "custom_components.universal_room_automation.const",
    "custom_components.universal_room_automation.fan_veto",
    "custom_components.universal_room_automation.domain_coordinators.house_state",
    "custom_components.universal_room_automation.domain_coordinators.signals",
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "custom_components.universal_room_automation.domain_coordinators.base",
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    "custom_components.universal_room_automation.domain_coordinators.hvac_fans",
    "custom_components.universal_room_automation.domain_coordinators.hvac_covers",
    "custom_components.universal_room_automation.domain_coordinators.hvac_egress",
    "custom_components.universal_room_automation.domain_coordinators.hvac_preset",
    "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
    "custom_components.universal_room_automation.domain_coordinators.hvac_predict",
    "custom_components.universal_room_automation.domain_coordinators.hvac",
]
_MODULE_SNAPSHOT: dict = {k: sys.modules.get(k, _MISSING) for k in _SNAPSHOT_KEYS}

_load_module(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_root, "const.py"),
)
if "custom_components.universal_room_automation.domain_coordinators" not in sys.modules:
    _dc_pkg = _mock_module(
        "custom_components.universal_room_automation.domain_coordinators",
    )
    _dc_pkg.__file__ = os.path.join(
        _ura_root, "domain_coordinators", "__init__.py",
    )
    _dc_pkg.__path__ = [os.path.join(_ura_root, "domain_coordinators")]
    sys.modules[
        "custom_components.universal_room_automation.domain_coordinators"
    ] = _dc_pkg

# fan_veto is a hard dep of hvac_fans — must load before it.
# house_state must load first (fan_veto imports it).
_load_module(
    "custom_components.universal_room_automation.domain_coordinators.house_state",
    os.path.join(_ura_root, "domain_coordinators", "house_state.py"),
)
_load_module(
    "custom_components.universal_room_automation.fan_veto",
    os.path.join(_ura_root, "fan_veto.py"),
)

# Preload every sibling hvac.py needs. Order matters — leaf deps first.
_SIBLING_LOAD_ORDER = [
    ("house_state", "domain_coordinators/house_state.py"),
    ("signals", "domain_coordinators/signals.py"),
    ("hvac_const", "domain_coordinators/hvac_const.py"),
    ("base", "domain_coordinators/base.py"),
    ("hvac_zones", "domain_coordinators/hvac_zones.py"),
    ("hvac_fans", "domain_coordinators/hvac_fans.py"),
    ("hvac_covers", "domain_coordinators/hvac_covers.py"),
    ("hvac_egress", "domain_coordinators/hvac_egress.py"),
    ("hvac_preset", "domain_coordinators/hvac_preset.py"),
    ("hvac_setpoint", "domain_coordinators/hvac_setpoint.py"),
    ("hvac_override", "domain_coordinators/hvac_override.py"),
    ("hvac_predict", "domain_coordinators/hvac_predict.py"),
]
for _leaf, _rel in _SIBLING_LOAD_ORDER:
    _fq = (
        "custom_components.universal_room_automation.domain_coordinators."
        + _leaf
    )
    _load_module(_fq, os.path.join(_ura_root, _rel))

_load_module(
    "custom_components.universal_room_automation.domain_coordinators.hvac",
    os.path.join(_ura_root, "domain_coordinators", "hvac.py"),
)

import custom_components.universal_room_automation.domain_coordinators.hvac as _hvac_mod  # noqa: E402
from custom_components.universal_room_automation.domain_coordinators.hvac import (  # noqa: E402
    HVACCoordinator,
)
from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_ENTRY_TYPE,
    CONF_FANS,
    CONF_LIGHTS,
    CONF_ROOM_NAME,
    DOMAIN,
    ENTRY_TYPE_ROOM,
)

# HVACCoordinator + the const symbols we need are now captured in our
# module namespace. Restore the sibling sys.modules entries to whatever
# state they were in before we clobbered them, so sibling tests that run
# AFTER us (or depend on module identity from tests that ran BEFORE us)
# see their expected stubs / originals, not our forced real loads.
for _k, _orig in _MODULE_SNAPSHOT.items():
    if _orig is _MISSING:
        sys.modules.pop(_k, None)
    else:
        sys.modules[_k] = _orig
# Restore homeassistant.util.dt to whatever was there before our _dt_mock
# clobbered it — this is what sibling tests rely on (naive datetime.utcnow()).
if _HA_DT_ORIG is _MISSING:
    sys.modules.pop("homeassistant.util.dt", None)
else:
    sys.modules["homeassistant.util.dt"] = _HA_DT_ORIG

_hvac_dt_util = _hvac_mod.dt_util


def _set_now(dt: datetime) -> None:
    fn = lambda: dt  # noqa: E731
    _dt_mock.now = fn
    _dt_mock.utcnow = fn
    _hvac_dt_util.now = fn
    _hvac_dt_util.utcnow = fn


def _run(coro):
    # Sibling tests in the full suite may close / detach the default loop
    # (RuntimeError: no current event loop in main thread). Prefer the
    # existing loop when live; otherwise install a fresh one.
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# Fixture: HVACCoordinator instance with only the attrs _execute_vacancy_sweep
# reads. Built via __new__ to sidestep the heavy real __init__. This preserves
# the production method under test (bound via normal attribute lookup) while
# keeping the fixture surgical.
# ---------------------------------------------------------------------------

class _StubEntry:
    def __init__(self, room_name: str, fans: list, lights: list, entry_id: str):
        self.entry_id = entry_id
        self.data = {
            CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
            CONF_ROOM_NAME: room_name,
            CONF_FANS: fans,
            CONF_LIGHTS: lights,
        }
        self.options: dict = {}


class _StubRoomCoordinator:
    """Minimum surface `_execute_vacancy_sweep` reads on a room coordinator."""

    def __init__(self, entry: _StubEntry):
        self.config_entry = entry


class _StubZone:
    def __init__(self, zone_name: str, rooms: list):
        self.zone_name = zone_name
        self.rooms = rooms


def _make_hvac_coord(room_hold_map: dict):
    """Return (coord, service_call_log).

    ``room_hold_map`` — {room_name: bool} for HVAC-tier hold state.
    Each room gets one fan entity ``fan.<room_lower>`` + one light
    entity ``light.<room_lower>``, both wired ON in hass.states so
    the sweep's per-entity `if state.state == "on"` check passes.
    """
    coord = HVACCoordinator.__new__(HVACCoordinator)
    coord._observation_mode = False

    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    log: list[tuple[str, str, dict]] = []

    async def _svc_call(domain, service, data=None, blocking=False):
        log.append((domain, service, dict(data or {})))

    hass.services = MagicMock()
    hass.services.async_call = _svc_call

    # Build entries + a states table + hass.config_entries.async_entries.
    entries: list[_StubEntry] = []
    states: dict[str, MagicMock] = {}
    for room in room_hold_map:
        fan = f"fan.{room.lower()}"
        light = f"light.{room.lower()}"
        entry = _StubEntry(
            room_name=room, fans=[fan], lights=[light],
            entry_id=f"entry_{room}",
        )
        entries.append(entry)
        for eid in (fan, light):
            st = MagicMock()
            st.state = "on"
            states[eid] = st
        # Register the room coordinator in hass.data[DOMAIN][entry_id]
        # — this is exactly the shape _get_room_coordinator expects.
        hass.data[DOMAIN][entry.entry_id] = _StubRoomCoordinator(entry)

    def _states_get(eid):
        return states.get(eid)

    hass.states = MagicMock()
    hass.states.get = _states_get

    def _entries(domain):
        assert domain == DOMAIN
        return list(entries)

    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = _entries
    coord.hass = hass

    # Stub the room-tier automation accessor path — the sweep does
    # `getattr(coordinator, "automation", None)`. Leave it None so the
    # room-tier branch is skipped and the HVAC-tier accessor is the
    # ONLY discriminator, isolating this test to the HVAC-tier lookup
    # (the room-tier accessor is covered by the reconciler + room-tier
    # test files).
    for entry in entries:
        # No .automation attribute means getattr returns None → the code
        # skips the room-tier check without raising.
        pass

    # FanController stub — the sweep only calls is_room_in_manual_on_hold.
    fc = MagicMock()
    fc.is_room_in_manual_on_hold = lambda room: bool(room_hold_map.get(room))
    coord._fan_controller = fc

    return coord, log


# ---------------------------------------------------------------------------
# T1 — B-HIGH-1: zone-vacancy sweep guard discriminates between rooms.
# hvac.py::_execute_vacancy_sweep ~2419-2471 (dual room-tier + HVAC-tier
# hold check before per-room fan turn_off).
#
# Mutation anchor: neuter the HVAC-tier `is_room_in_manual_on_hold` return
# so the guard reads False for every room — the discriminator test below
# MUST red (the "held" room's fan gets swept, breaking the invariant).
# ---------------------------------------------------------------------------


def test_vacancy_sweep_discriminates_held_vs_holdless_room():
    """A zone with two rooms — one fan under a live HVAC-tier manual-ON
    hold, one holdless. The sweep MUST turn_off the holdless room's fan
    but NOT the held room's fan. Proves the guard DISCRIMINATES per room
    (not that the sweep as a whole is dead)."""
    base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(base)

    coord, log = _make_hvac_coord({"HeldRoom": True, "FreeRoom": False})
    zone = _StubZone(zone_name="ZoneA", rooms=["HeldRoom", "FreeRoom"])

    _run(coord._execute_vacancy_sweep(zone))

    fan_off_targets = {
        (svc, tuple(sorted(d.get("entity_id", "")
                           if isinstance(d.get("entity_id"), str)
                           else [d.get("entity_id")])))
        for (_dom, svc, d) in log
        if svc == "turn_off" and (
            (isinstance(d.get("entity_id"), str)
             and d["entity_id"].startswith("fan."))
            or (isinstance(d.get("entity_id"), list)
                and any(e.startswith("fan.") for e in d["entity_id"]))
        )
    }
    # Reshape: extract just fan entity ids that received a turn_off.
    swept_fans = set()
    for (_dom, svc, d) in log:
        if svc != "turn_off":
            continue
        eid = d.get("entity_id")
        candidates = [eid] if isinstance(eid, str) else list(eid or [])
        for c in candidates:
            if c and c.startswith("fan."):
                swept_fans.add(c)

    assert "fan.freeroom" in swept_fans, (
        "Positive control: holdless-room fan must be swept "
        f"(swept_fans={swept_fans}, full_log={log})"
    )
    assert "fan.heldroom" not in swept_fans, (
        "FAN-MANUAL-1: room under a live HVAC-tier manual-ON hold MUST "
        "NOT be swept by _execute_vacancy_sweep (hvac.py :2419-2471). "
        f"swept_fans={swept_fans}, full_log={log}"
    )


def test_vacancy_sweep_sweeps_lights_regardless_of_fan_hold():
    """Scoping: the manual-ON hold is FAN-scoped only. Lights in a room
    with a held fan MUST still be swept (the FAN-MANUAL-1 rationale in
    hvac.py :2419-2425 explicitly documents "Lights are UNAFFECTED").
    Guards against a future refactor that widens the guard to lights.
    """
    base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(base)

    coord, log = _make_hvac_coord({"HeldRoom": True})
    zone = _StubZone(zone_name="ZoneA", rooms=["HeldRoom"])

    _run(coord._execute_vacancy_sweep(zone))

    light_off_targets = set()
    for (_dom, svc, d) in log:
        if svc != "turn_off":
            continue
        eid = d.get("entity_id")
        candidates = [eid] if isinstance(eid, str) else list(eid or [])
        for c in candidates:
            if c and c.startswith("light."):
                light_off_targets.add(c)

    assert "light.heldroom" in light_off_targets, (
        "Scoping: manual-ON hold is FAN-scoped; the held room's LIGHT "
        f"must still be swept off (light_off_targets={light_off_targets})"
    )


# ---------------------------------------------------------------------------
# NIGHT-LIGHT-NO-OFF-PATH-1 (D5, H1): HVAC vacancy sweep sleep-gated widen
# to CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS (non-sleep) / CONF_LIGHTS-only (sleep).
# Mutation anchor: neuter D5 union → non-sleep test RED; neuter D5 sleep gate
# → sleep test RED (a hallway night light gets swept off at 02:00).
# ---------------------------------------------------------------------------


def _make_hvac_coord_with_night_lights(room: str, sleep: bool):
    """Extended fixture: one room with a night-only entity + sleep predicate.

    Injects a `.automation.is_sleep_mode_active()` accessor on the stub
    room coordinator so the D5 sleep-gate read succeeds.
    """
    from custom_components.universal_room_automation.const import (
        CONF_NIGHT_LIGHTS,
    )

    coord = HVACCoordinator.__new__(HVACCoordinator)
    coord._observation_mode = False

    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    log: list = []

    async def _svc_call(domain, service, data=None, blocking=False):
        log.append((domain, service, dict(data or {})))

    hass.services = MagicMock()
    hass.services.async_call = _svc_call

    night_entity = f"switch.{room.lower()}_night"
    entry = _StubEntry(
        room_name=room, fans=[], lights=[],
        entry_id=f"entry_{room}",
    )
    entry.data[CONF_NIGHT_LIGHTS] = [night_entity]

    states = {}
    st = MagicMock()
    st.state = "on"
    states[night_entity] = st

    room_coord = _StubRoomCoordinator(entry)
    _auto = MagicMock()
    _auto.is_sleep_mode_active = lambda: sleep
    room_coord.automation = _auto
    hass.data[DOMAIN][entry.entry_id] = room_coord

    def _states_get(eid):
        return states.get(eid)

    hass.states = MagicMock()
    hass.states.get = _states_get

    def _entries(domain):
        assert domain == DOMAIN
        return [entry]

    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = _entries
    coord.hass = hass

    fc = MagicMock()
    fc.is_room_in_manual_on_hold = lambda _r: False
    coord._fan_controller = fc

    return coord, log, night_entity


def test_D5_hvac_sweep_nonsleep_turns_off_night_only_entity():
    """D5: non-sleep zone-vacancy sweep turns off a night-only entity
    (the widen)."""
    base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(base)

    coord, log, night_entity = _make_hvac_coord_with_night_lights(
        "Hall", sleep=False,
    )
    zone = _StubZone(zone_name="ZoneA", rooms=["Hall"])

    _run(coord._execute_vacancy_sweep(zone))

    off_targets = set()
    for (_dom, svc, d) in log:
        if svc != "turn_off":
            continue
        eid = d.get("entity_id")
        if eid == night_entity:
            off_targets.add(eid)

    assert night_entity in off_targets, (
        f"D5 non-sleep sweep MUST turn off night-only entity {night_entity}. "
        f"log={log}"
    )


def test_D5_hvac_sweep_sleep_does_NOT_turn_off_night_only_entity():
    """D5 DISCRIMINATING: sleep zone-vacancy sweep MUST NOT turn off a
    night-only entity (invariant #2 — the 02:00-kills-hallway-night-light
    anti-regression). Neutering the sleep gate turns this RED.
    """
    base = datetime(2026, 8, 10, 2, 0, 0, tzinfo=timezone.utc)
    _set_now(base)

    coord, log, night_entity = _make_hvac_coord_with_night_lights(
        "Hall", sleep=True,
    )
    zone = _StubZone(zone_name="ZoneA", rooms=["Hall"])

    _run(coord._execute_vacancy_sweep(zone))

    off_targets = set()
    for (_dom, svc, d) in log:
        if svc != "turn_off":
            continue
        eid = d.get("entity_id")
        if eid == night_entity:
            off_targets.add(eid)

    assert night_entity not in off_targets, (
        f"D5 sleep gate: sweep MUST NOT turn off night-only entity "
        f"{night_entity} during sleep. log={log}"
    )
