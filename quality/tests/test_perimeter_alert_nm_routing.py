"""Tests for PerimeterAlertManager → NotificationManager routing.

Cycle: PLANNING_exterior_person_escalation.md
Bug Class #62: tests drive REAL production code paths, not fake reimplementations.
Fixture-state authority: construct realistic house-state + NM wiring; mutate
the fixture, not private helpers.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

# --- Stub homeassistant surfaces perimeter_alert.py touches --------------------

_ident = lambda fn: fn  # noqa: E731


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


# Simple in-process scheduler for async_call_later: record scheduled callbacks
# and let tests advance them manually.
_scheduled: list = []


def _fake_async_call_later(hass, delay, cb):
    _scheduled.append((delay, cb))
    return MagicMock()  # unsub


def _fake_async_track_state_change_event(hass, entities, cb):
    return MagicMock()


_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": MagicMock,
        "callback": _ident,
        "Event": MagicMock,
    },
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": MagicMock()},
    "homeassistant.helpers.entity_registry": {"async_get": MagicMock()},
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda *a, **kw: MagicMock(),
        "async_dispatcher_send": lambda *a, **kw: None,
    },
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _fake_async_track_state_change_event,
        "async_call_later": _fake_async_call_later,
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow,
        "now": datetime.now,
    },
}

for _n, _a in _mods.items():
    existing = sys.modules.get(_n)
    if existing is None:
        sys.modules[_n] = _mock_module(_n, **_a)
    else:
        for _k, _v in _a.items():
            if not hasattr(existing, _k):
                setattr(existing, _k, _v)

# Package plumbing (avoid __init__.py chain like test_notification_manager.py)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura = types.ModuleType("custom_components.universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura
_cc.universal_room_automation = _ura


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_const = _load(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_ura.const = _const

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc

_base = _load(
    "custom_components.universal_room_automation.domain_coordinators.base",
    os.path.join(_dc_path, "base.py"),
)
_dc.base = _base
Severity = _base.Severity

_perimeter = _load(
    "custom_components.universal_room_automation.perimeter_alert",
    os.path.join(_ura_path, "perimeter_alert.py"),
)
_ura.perimeter_alert = _perimeter
PerimeterAlertManager = _perimeter.PerimeterAlertManager

# Pin our scheduler stubs directly on the perimeter module (post-import) so
# other test modules that mutate homeassistant.helpers.event globally cannot
# poison the reference this module uses. Cross-test-pollution guard.
_perimeter.async_call_later = _fake_async_call_later
_perimeter.async_track_state_change_event = _fake_async_track_state_change_event


# --- Test helpers -------------------------------------------------------------

def _make_hass(
    house_state: str | None = "away",
    perimeter_cameras: list[str] | None = None,
    legacy_service: str = "",
    legacy_target: str = "",
    snapshot_offset_s: int | None = 0,  # tests default to no scheduler delay
    nm_enabled: bool = True,
    include_nm: bool = True,
):
    """Build a MockHass carrying all state PerimeterAlertManager reads."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.bus = MagicMock()
    hass.bus.async_listen = MagicMock(return_value=MagicMock())
    hass._states: dict = {}
    hass.states = MagicMock()
    hass.states.get = lambda eid: hass._states.get(eid)

    # Coordinator manager exposing house_state property (mirrors real path)
    cm = MagicMock()
    cm.house_state = house_state

    # NM mock — AsyncMock so async_notify awaits cleanly
    nm = MagicMock()
    nm.enabled = nm_enabled
    nm.async_notify = AsyncMock()

    # Camera manager returning CameraInfo-like objects
    cams = perimeter_cameras or ["camera.front_yard"]
    cam_manager = MagicMock()

    def _resolve(cam_id):
        info = MagicMock()
        info.person_binary_sensor = (
            "binary_sensor." + cam_id.split(".", 1)[1] + "_person_occupancy"
        )
        info.platform = _const.CAMERA_PLATFORM_FRIGATE
        info.entity_id = info.person_binary_sensor
        return [info]

    cam_manager.resolve_camera_entity = _resolve

    hass.data = {
        _const.DOMAIN: {
            "coordinator_manager": cm,
            "camera_manager": cam_manager,
        }
    }
    if include_nm:
        hass.data[_const.DOMAIN]["notification_manager"] = nm

    # Config entry
    entry = MagicMock()
    entry.data = {_const.CONF_ENTRY_TYPE: _const.ENTRY_TYPE_INTEGRATION}
    opts: dict = {
        _const.CONF_PERIMETER_CAMERAS: cams,
        _const.CONF_EGRESS_CAMERAS: [],
        _const.CONF_PERIMETER_ALERT_HOURS_START: 0,
        _const.CONF_PERIMETER_ALERT_HOURS_END: 0,  # full day
        _const.CONF_PERIMETER_ALERT_NOTIFY_SERVICE: legacy_service,
        _const.CONF_PERIMETER_ALERT_NOTIFY_TARGET: legacy_target,
    }
    if snapshot_offset_s is not None:
        opts[_const.CONF_EXTERIOR_SNAPSHOT_OFFSET_S] = snapshot_offset_s
    entry.options = opts
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[entry])

    # entity_picture for live-fallback snapshot resolution
    for cam_id in cams:
        st = MagicMock()
        st.attributes = {"entity_picture": f"/api/camera_proxy/{cam_id}"}
        hass._states[cam_id] = st

    return hass, nm


async def _setup_mgr(hass) -> PerimeterAlertManager:
    mgr = PerimeterAlertManager(hass)
    await mgr.async_setup()
    return mgr


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# --- D1/D2/D3: severity map + routing ----------------------------------------

@pytest.mark.parametrize(
    "house_state,expected",
    [
        ("away", Severity.CRITICAL),
        ("vacation", Severity.CRITICAL),
        ("sleep", Severity.CRITICAL),
        ("home_night", Severity.CRITICAL),
        ("guest", Severity.MEDIUM),
        ("home_day", Severity.LOW),
        ("home_evening", Severity.LOW),
        ("waking", Severity.LOW),
        ("arriving", Severity.LOW),
        ("", Severity.CRITICAL),           # empty → fail-safe
        (None, Severity.CRITICAL),         # missing → fail-safe
        ("mystery_state", Severity.CRITICAL),  # unknown → fail-safe
    ],
)
def test_severity_maps_by_house_state(house_state, expected):
    hass, nm = _make_hass(house_state=house_state)
    mgr = _run(_setup_mgr(hass))
    _run(mgr._async_handle_perimeter_trigger("binary_sensor.front_yard_person_occupancy"))
    assert nm.async_notify.await_count == 1
    kwargs = nm.async_notify.await_args.kwargs
    assert kwargs["severity"] == expected
    assert kwargs["hazard_type"] == _const.NM_HAZARD_EXTERIOR_PERSON
    assert kwargs["location"] == "binary_sensor.front_yard_person_occupancy"
    assert kwargs["coordinator_id"] == "perimeter_alert"


def test_perimeter_cooldown_bounds_phone_rate():
    hass, nm = _make_hass(house_state="away")
    mgr = _run(_setup_mgr(hass))
    for _ in range(3):
        _run(mgr._async_handle_perimeter_trigger("binary_sensor.front_yard_person_occupancy"))
    assert nm.async_notify.await_count == 1


def test_egress_suppression_preserved():
    hass, nm = _make_hass(house_state="away")
    mgr = _run(_setup_mgr(hass))
    # Simulate a recent egress crossing
    from homeassistant.util import dt as _dt
    mgr._last_egress_time = _dt.now()
    _run(mgr._async_handle_perimeter_trigger("binary_sensor.front_yard_person_occupancy"))
    assert nm.async_notify.await_count == 0


def test_legacy_fallback_when_nm_absent():
    hass, _nm = _make_hass(
        house_state="away",
        legacy_service="notify.pushover",
        include_nm=False,
    )
    mgr = _run(_setup_mgr(hass))
    _run(mgr._async_handle_perimeter_trigger("binary_sensor.front_yard_person_occupancy"))
    calls = hass.services.async_call.await_args_list
    assert calls, "legacy notify service should have been called"
    domain, service, data = calls[0].args[:3]
    assert domain == "notify"
    assert service == "pushover"
    assert "Perimeter Alert" in data["title"]


def test_legacy_fallback_when_nm_disabled():
    hass, nm = _make_hass(
        house_state="away",
        legacy_service="notify.pushover",
        nm_enabled=False,
    )
    mgr = _run(_setup_mgr(hass))
    _run(mgr._async_handle_perimeter_trigger("binary_sensor.front_yard_person_occupancy"))
    assert nm.async_notify.await_count == 0
    assert hass.services.async_call.await_count == 1


def test_legacy_and_nm_both_set_prefers_nm_with_deprecation_warning(caplog):
    hass, nm = _make_hass(
        house_state="away",
        legacy_service="notify.pushover",
        nm_enabled=True,
    )
    mgr = _run(_setup_mgr(hass))
    with caplog.at_level("WARNING"):
        _run(mgr._async_handle_perimeter_trigger("binary_sensor.front_yard_person_occupancy"))
    assert nm.async_notify.await_count == 1
    assert hass.services.async_call.await_count == 0  # legacy path NOT taken
    assert any("deprecated" in r.getMessage().lower() for r in caplog.records)
    # One-shot: second trigger (after clearing cooldown) should NOT re-warn
    mgr._last_alert.clear()
    caplog.clear()
    with caplog.at_level("WARNING"):
        _run(mgr._async_handle_perimeter_trigger("binary_sensor.front_yard_person_occupancy"))
    assert not any("deprecated" in r.getMessage().lower() for r in caplog.records)


# --- D4/D5: snapshot resolution ---------------------------------------------

def test_frigate_snapshot_url_when_event_cached():
    hass, nm = _make_hass(house_state="away")
    mgr = _run(_setup_mgr(hass))
    mgr._frigate_last_event_id["front_yard"] = "1735000000.123456-abcdef"
    _scheduled.clear()
    _run(mgr._async_handle_perimeter_trigger("binary_sensor.front_yard_person_occupancy"))
    # Frigate event snapshot → no scheduled delay (offset ignored)
    assert not _scheduled
    kwargs = nm.async_notify.await_args.kwargs
    assert kwargs["snapshot_url"] == (
        "/api/frigate/notifications/1735000000.123456-abcdef/snapshot.jpg"
    )


def test_snapshot_offset_honored_on_live_fallback():
    hass, nm = _make_hass(house_state="away", snapshot_offset_s=7)
    mgr = _run(_setup_mgr(hass))
    _scheduled.clear()
    _run(mgr._async_handle_perimeter_trigger("binary_sensor.front_yard_person_occupancy"))
    # Live fallback → dispatch scheduled with the configured offset
    assert _scheduled, "expected a scheduled delayed dispatch"
    delay, cb = _scheduled[-1]
    assert delay == 7
    # NM not yet notified — waiting for scheduler
    assert nm.async_notify.await_count == 0
    # Fire the scheduler callback (it dispatches a task; run its coroutine)
    cb(None)  # calls hass.async_create_task(_do_dispatch())
    # The MagicMock hass.async_create_task swallowed the coroutine; run it
    coro = hass.async_create_task.call_args.args[0]
    _run(coro)
    assert nm.async_notify.await_count == 1
    kwargs = nm.async_notify.await_args.kwargs
    assert kwargs["snapshot_url"] == "/api/camera_proxy/camera.front_yard"


def test_snapshot_offset_zero_dispatches_immediately_no_scheduler():
    hass, nm = _make_hass(house_state="away", snapshot_offset_s=0)
    mgr = _run(_setup_mgr(hass))
    _scheduled.clear()
    _run(mgr._async_handle_perimeter_trigger("binary_sensor.front_yard_person_occupancy"))
    assert not _scheduled
    assert nm.async_notify.await_count == 1


def test_snapshot_failure_does_not_block_alert():
    hass, nm = _make_hass(house_state="away")
    # Remove camera state so entity_picture lookup returns None
    hass._states.clear()
    mgr = _run(_setup_mgr(hass))
    _run(mgr._async_handle_perimeter_trigger("binary_sensor.front_yard_person_occupancy"))
    assert nm.async_notify.await_count == 1
    assert nm.async_notify.await_args.kwargs["snapshot_url"] is None


# --- Mutation drills (Bug Class #62 authority) --------------------------------
# Neuter production sites and confirm SPECIFIC tests fail; restore + verify.
# We do this in-process by patching module attributes (byte-restored in the
# `finally`); we do NOT persist source changes because the harness disables
# .pyc via PYTHONDONTWRITEBYTECODE and this is the closest we can get to
# per-site mutation in a fixture-driven suite.

def test_MUTATION_severity_map_load_bearing():
    """Neuter the severity map → home_day would incorrectly promote to CRITICAL."""
    # Patch the map on the perimeter module itself (from-import capture).
    orig = _perimeter.NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE
    try:
        _perimeter.NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE = {}
        hass, nm = _make_hass(house_state="home_day")
        mgr = asyncio.run(_setup_neutered(_perimeter.PerimeterAlertManager, hass))
        asyncio.run(mgr._async_handle_perimeter_trigger(
            "binary_sensor.front_yard_person_occupancy"))
        assert nm.async_notify.await_args.kwargs["severity"] == Severity.CRITICAL
    finally:
        _perimeter.NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE = orig
    # Restore proof: home_day back to LOW.
    hass, nm = _make_hass(house_state="home_day")
    mgr = asyncio.run(_setup_neutered(_perimeter.PerimeterAlertManager, hass))
    asyncio.run(mgr._async_handle_perimeter_trigger(
        "binary_sensor.front_yard_person_occupancy"))
    assert nm.async_notify.await_args.kwargs["severity"] == Severity.LOW


def test_MUTATION_snapshot_threading_load_bearing():
    """Neuter snapshot threading → frigate URL kw must vanish."""
    Mgr = _perimeter.PerimeterAlertManager
    orig = Mgr._resolve_snapshot_url_and_delay
    try:
        Mgr._resolve_snapshot_url_and_delay = lambda self, sid: (None, 0)
        hass, nm = _make_hass(house_state="away")
        mgr = asyncio.run(_setup_neutered(Mgr, hass))
        mgr._frigate_last_event_id["front_yard"] = "evt-1"
        asyncio.run(mgr._async_handle_perimeter_trigger(
            "binary_sensor.front_yard_person_occupancy"))
        assert nm.async_notify.await_args.kwargs["snapshot_url"] is None
    finally:
        Mgr._resolve_snapshot_url_and_delay = orig


def test_MUTATION_cooldown_load_bearing():
    """Neuter the cooldown short-circuit (set const to 0) → 3 triggers = 3 dispatches."""
    orig = _perimeter.PERIMETER_ALERT_COOLDOWN_SECONDS
    try:
        _perimeter.PERIMETER_ALERT_COOLDOWN_SECONDS = 0
        hass, nm = _make_hass(house_state="away")
        mgr = asyncio.run(_setup_neutered(_perimeter.PerimeterAlertManager, hass))
        for _ in range(3):
            asyncio.run(mgr._async_handle_perimeter_trigger(
                "binary_sensor.front_yard_person_occupancy"))
        assert nm.async_notify.await_count == 3
    finally:
        _perimeter.PERIMETER_ALERT_COOLDOWN_SECONDS = orig


async def _setup_neutered(cls, hass):
    mgr = cls(hass)
    await mgr.async_setup()
    return mgr
