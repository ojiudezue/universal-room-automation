"""SNAP-1: at-detection perimeter snapshots — local-file delivery tests.

Test authority:
* Every expected value is INDEPENDENTLY AUTHORED — never computed from the
  expression under test.
* No test greps source text.
* No pytest.skip on ImportError — the HA stub prelude below assembles the
  minimal surfaces perimeter_alert.py + notification_manager.py touch.
* Drills:
  - detach snapshot_path (empty string / bogus) → media_path key absence
    is asserted RED-on-mutation upstream.
  - detach kill switch (True) → payload byte-identical to legacy URL form.
  - detach capture (make it always return None) → NM sees snapshot_path=None
    → media_url used.
  - retention prune must be age-primary (independently authored mtimes).
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
import time
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# --- HA stub prelude (sibling to test_perimeter_alert_nm_routing.py) --------

_ident = lambda fn: fn  # noqa: E731


def _fake_async_call_later(hass, delay, cb):
    return MagicMock()


def _fake_async_track_state_change_event(hass, entities, cb):
    return MagicMock()


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": MagicMock,
        "callback": _ident,
        "Event": MagicMock,
        "State": MagicMock,
        "CALLBACK_TYPE": type(None),
    },
    "homeassistant.config_entries": {"ConfigEntry": MagicMock},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict,
        "EntityCategory": MagicMock(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": MagicMock},
    "homeassistant.helpers.entity_registry": {"async_get": MagicMock()},
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": MagicMock,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": MagicMock(),
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {}),
    },
    "homeassistant.helpers.sun": {},
    "homeassistant.helpers.aiohttp_client": {
        "async_get_clientsession": lambda hass: MagicMock(),
    },
    "homeassistant.components": {},
    "homeassistant.components.webhook": {
        "async_register": lambda *a, **kw: None,
        "async_unregister": lambda *a, **kw: None,
    },
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": MagicMock(),
        "SensorStateClass": MagicMock(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": MagicMock(),
    },
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
    "homeassistant.components.switch": {
        "SwitchEntity": type("SwitchEntity", (), {}),
    },
    "homeassistant.components.number": {
        "NumberEntity": type("NumberEntity", (), {}),
    },
    "homeassistant.components.select": {
        "SelectEntity": type("SelectEntity", (), {}),
    },
    "aiosqlite": MagicMock(),
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda *a, **kw: MagicMock(),
        "async_dispatcher_send": lambda *a, **kw: None,
    },
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _fake_async_track_state_change_event,
        "async_call_later": _fake_async_call_later,
        "async_track_time_interval": lambda *a, **kw: (lambda: None),
        "async_track_time_change": lambda *a, **kw: (lambda: None),
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.now(timezone.utc),
        "now": lambda: datetime.now(timezone.utc),
        "as_local": lambda dt: dt,
        "start_of_local_day": lambda: datetime.now(),
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


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
_cc = sys.modules.get("custom_components") or types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura = sys.modules.get("custom_components.universal_room_automation")
if _ura is None:
    _ura = types.ModuleType("custom_components.universal_room_automation")
    _ura.__path__ = [_ura_path]
    _ura.__package__ = "custom_components.universal_room_automation"
    sys.modules["custom_components.universal_room_automation"] = _ura
    _cc.universal_room_automation = _ura


def _load(name: str, path: str):
    if name in sys.modules:
        return sys.modules[name]
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
_dc = sys.modules.get(
    "custom_components.universal_room_automation.domain_coordinators"
)
if _dc is None:
    _dc = types.ModuleType(
        "custom_components.universal_room_automation.domain_coordinators"
    )
    _dc.__path__ = [_dc_path]
    _dc.__package__ = (
        "custom_components.universal_room_automation.domain_coordinators"
    )
    sys.modules[
        "custom_components.universal_room_automation.domain_coordinators"
    ] = _dc
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
# NOTE: intentionally do NOT rebind _perimeter.async_call_later /
# async_track_state_change_event here. Rebinding these on the shared
# perimeter module poisons sibling test files (test_perimeter_alert_nm_routing
# owns its own scheduler-observation fake `_scheduled`; if MY fake wins the
# pin, sibling's dispatch-scheduling assertions read an empty list). We
# already inherit stubbed versions via the sys.modules HA prelude above,
# which is enough for my tests.

# Pin clock — cross-suite frozen datetime mocks were a repeat bite tonight.
_pin = types.ModuleType("dt_util_pin")
_pin.now = lambda: datetime.now(timezone.utc)
_pin.utcnow = lambda: datetime.now(timezone.utc)
_perimeter.dt_util = _pin


# --- Small helpers ----------------------------------------------------------

def _run(coro):
    # Cross-file hygiene: asyncio.run() leaves the default loop UNSET on
    # Python 3.9, which breaks any subsequent test that calls
    # asyncio.get_event_loop() (substrate tests do). Restore a fresh
    # default loop after every run so we don't poison downstream tests.
    try:
        return asyncio.run(coro)
    finally:
        try:
            asyncio.set_event_loop(asyncio.new_event_loop())
        except Exception:  # noqa: BLE001
            pass


def _make_hass(
    *,
    is_allowed_path=True,
    www_path=None,
    external_url="http://ha.local:8123",
    perimeter_camera="camera.front_yard",
):
    hass = MagicMock()
    cfg = MagicMock()
    cfg.external_url = external_url
    cfg.internal_url = None
    cfg.is_allowed_path = lambda p: is_allowed_path
    cfg.path = lambda sub: www_path if sub == "www" else "/config/" + sub
    hass.config = cfg
    hass.is_stopping = False

    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.bus = MagicMock()
    hass.bus.async_listen = MagicMock(return_value=MagicMock())
    hass.bus.async_listen_once = MagicMock(return_value=MagicMock())
    hass._states = {}
    hass.states = MagicMock()
    hass.states.get = lambda eid: hass._states.get(eid)

    # Route executor jobs through the current asyncio loop synchronously.
    async def _add_executor_job(fn, *a):
        return fn(*a)
    hass.async_add_executor_job = _add_executor_job
    hass.async_create_task = lambda coro: asyncio.get_event_loop().create_task(coro)

    cm = MagicMock()
    cm.house_state = "away"
    nm = MagicMock()
    nm.enabled = True
    nm.async_notify = AsyncMock()

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
            "notification_manager": nm,
        },
        "frigate": {},
    }
    entry = MagicMock()
    entry.data = {_const.CONF_ENTRY_TYPE: _const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        _const.CONF_PERIMETER_CAMERAS: [perimeter_camera],
        _const.CONF_EGRESS_CAMERAS: [],
        _const.CONF_PERIMETER_ALERT_HOURS_START: 0,
        _const.CONF_PERIMETER_ALERT_HOURS_END: 0,
        _const.CONF_EXTERIOR_SNAPSHOT_OFFSET_S: 0,
    }
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[entry])

    st = MagicMock()
    st.attributes = {"entity_picture": "/api/camera_proxy/" + perimeter_camera}
    hass._states[perimeter_camera] = st
    return hass, nm


_ORIG_SNAPSHOT_DIR = _perimeter.PERIMETER_SNAPSHOT_DIR


def _restore_snapshot_dir():
    """Restore original PERIMETER_SNAPSHOT_DIR — call from test teardown so
    globals do not bleed into sibling test files (a mutated dir pointing at
    a deleted TemporaryDirectory poisons any test that runs after)."""
    _perimeter.PERIMETER_SNAPSHOT_DIR = _ORIG_SNAPSHOT_DIR


@pytest.fixture(autouse=True)
def _snapshot_dir_hygiene():
    yield
    _restore_snapshot_dir()


def _mgr_with_dir(hass, tmp_dir, *, kill=False):
    """Setup a PerimeterAlertManager with PERIMETER_SNAPSHOT_DIR pointed at tmp_dir."""
    _perimeter.PERIMETER_SNAPSHOT_DIR = tmp_dir
    mgr = PerimeterAlertManager(hass)
    mgr._snapshot_kill_legacy_url = kill
    _run(mgr.async_setup())
    return mgr


# --- D1: NM channel-builder payload-shape tests live in
# test_notification_manager.py::TestSNAP1ChannelBuilders — that module already
# owns the full NM stub prelude. Keeping those tests here would duplicate
# the heavy prelude AND cause cross-file sys.modules pollution.


# --- D1: setup-time allowed-path fallback ----------------------------------

def test_snap1_allowed_path_failure_engages_kill_switch():
    with tempfile.TemporaryDirectory() as tmp:
        hass, _ = _make_hass(is_allowed_path=False)
        mgr = _mgr_with_dir(hass, tmp)
        assert mgr._snapshot_kill_legacy_url is True


def test_snap1_www_privacy_invariant_rejects_www_subpath():
    with tempfile.TemporaryDirectory() as tmp:
        www = os.path.join(tmp, "www")
        os.makedirs(www)
        snapshot_dir = os.path.join(www, "ura")
        hass, _ = _make_hass(www_path=www)
        mgr = _mgr_with_dir(hass, snapshot_dir)
        assert mgr._snapshot_kill_legacy_url is True


def test_snap1_healthy_setup_does_not_engage_kill_switch():
    with tempfile.TemporaryDirectory() as tmp:
        hass, _ = _make_hass()
        mgr = _mgr_with_dir(hass, tmp)
        assert mgr._snapshot_kill_legacy_url is False
        assert os.path.isdir(tmp)  # mkdir happened


# --- D2: capture — live grab writes a file, engine tagged -------------------

def test_snap1_live_grab_captures_file_and_tags_engine():
    with tempfile.TemporaryDirectory() as tmp:
        hass, nm = _make_hass()

        # camera.snapshot writes a file on the operator's side; simulate.
        async def _svc(domain, service, data, blocking=False):
            if domain == "camera" and service == "snapshot":
                with open(data["filename"], "wb") as fh:
                    fh.write(b"\xff\xd8\xff\xe0FAKEJPEG")
        hass.services.async_call = AsyncMock(side_effect=_svc)

        mgr = _mgr_with_dir(hass, tmp)
        # Force live-grab leg by ensuring no cached frigate event id.
        mgr._frigate_last_event_id.clear()
        mgr._sensor_to_camera["binary_sensor.front_yard_person_occupancy"] = (
            "camera.front_yard"
        )
        path = _run(mgr._capture_at_detection_snapshot(
            "binary_sensor.front_yard_person_occupancy"
        ))
        assert path is not None
        assert os.path.isfile(path)
        # Ledger records the engine — independently authored.
        cam_key = mgr._camera_key_for_sensor(
            "binary_sensor.front_yard_person_occupancy"
        )
        assert mgr._last_snapshot_capture[cam_key]["engine"] == "live_grab"


def test_snap1_capture_returns_none_when_kill_switch_engaged():
    with tempfile.TemporaryDirectory() as tmp:
        hass, _ = _make_hass()
        mgr = _mgr_with_dir(hass, tmp, kill=False)
        mgr._snapshot_kill_legacy_url = True  # detach kill-switch flag
        path = _run(mgr._capture_at_detection_snapshot(
            "binary_sensor.front_yard_person_occupancy"
        ))
        assert path is None


# --- D2: end-to-end — snapshot_path threaded through to NM ------------------

def test_snap1_perimeter_trigger_threads_snapshot_path_to_nm():
    with tempfile.TemporaryDirectory() as tmp:
        hass, nm = _make_hass()

        async def _svc(domain, service, data, blocking=False):
            if domain == "camera" and service == "snapshot":
                with open(data["filename"], "wb") as fh:
                    fh.write(b"BYTES")
        hass.services.async_call = AsyncMock(side_effect=_svc)

        mgr = _mgr_with_dir(hass, tmp)
        mgr._frigate_last_event_id.clear()
        mgr._sensor_to_camera["binary_sensor.front_yard_person_occupancy"] = (
            "camera.front_yard"
        )
        _run(mgr._async_handle_perimeter_trigger(
            "binary_sensor.front_yard_person_occupancy"
        ))
        assert nm.async_notify.await_count == 1
        kw = nm.async_notify.await_args.kwargs
        assert kw.get("snapshot_path") is not None
        assert kw["snapshot_path"].startswith(tmp)
        # URL fallback field also present (defense in depth) but the
        # DELIVERY (NM channel builder) prefers snapshot_path — that
        # invariant is asserted in the channel-builder tests above.


def test_snap1_kill_switch_snapshot_path_is_none_at_nm():
    """Detach-the-value drill: kill switch ON → snapshot_path must be None."""
    with tempfile.TemporaryDirectory() as tmp:
        hass, nm = _make_hass()
        mgr = _mgr_with_dir(hass, tmp)
        mgr._snapshot_kill_legacy_url = True  # DETACH
        _run(mgr._async_handle_perimeter_trigger(
            "binary_sensor.front_yard_person_occupancy"
        ))
        kw = nm.async_notify.await_args.kwargs
        assert kw.get("snapshot_path") is None


# --- D3: retention prune, age-primary ---------------------------------------

def test_snap1_retention_age_prune_deletes_files_older_than_age():
    with tempfile.TemporaryDirectory() as tmp:
        _perimeter.PERIMETER_SNAPSHOT_DIR = tmp
        # Independently authored: 3 files, mtime = now - {200h, 100h, 1h}.
        now = time.time()
        paths = {
            "old": (os.path.join(tmp, "cam_old.jpg"), now - 200 * 3600),
            "mid": (os.path.join(tmp, "cam_mid.jpg"), now - 100 * 3600),
            "new": (os.path.join(tmp, "cam_new.jpg"), now - 1 * 3600),
        }
        for path, mtime in paths.values():
            with open(path, "wb") as fh:
                fh.write(b"X")
            os.utime(path, (mtime, mtime))

        hass, _ = _make_hass()
        mgr = PerimeterAlertManager(hass)
        deleted, _freed = mgr._prune_snapshot_dir()

        assert deleted == 1
        assert not os.path.exists(paths["old"][0])
        assert os.path.exists(paths["mid"][0])
        assert os.path.exists(paths["new"][0])


def test_snap1_retention_count_backstop_drops_oldest_beyond_cap():
    """Detach: cap=3 → 5 files kept-by-age → prune 2 oldest by mtime."""
    with tempfile.TemporaryDirectory() as tmp:
        _perimeter.PERIMETER_SNAPSHOT_DIR = tmp
        # Override cap for this test — independently authored expected values.
        orig_cap = _perimeter.PERIMETER_SNAPSHOT_RETENTION_COUNT
        _perimeter.PERIMETER_SNAPSHOT_RETENTION_COUNT = 3
        try:
            now = time.time()
            ordered_paths: list[str] = []
            for i in range(5):
                p = os.path.join(tmp, f"cam_{i}.jpg")
                with open(p, "wb") as fh:
                    fh.write(b"X")
                mtime = now - (10 - i) * 3600  # older i's are older
                os.utime(p, (mtime, mtime))
                ordered_paths.append(p)
            hass, _ = _make_hass()
            mgr = PerimeterAlertManager(hass)
            deleted, _freed = mgr._prune_snapshot_dir()
            assert deleted == 2
            assert not os.path.exists(ordered_paths[0])
            assert not os.path.exists(ordered_paths[1])
            for keep in ordered_paths[2:]:
                assert os.path.exists(keep)
        finally:
            _perimeter.PERIMETER_SNAPSHOT_RETENTION_COUNT = orig_cap


# --- D4: privacy invariant — a www-subpath dir is refused (drilled above) --
# Covered by test_snap1_www_privacy_invariant_rejects_www_subpath.


# --- Const rung — sanity check the knob names + defaults --------------------

def test_snap1_const_defaults_are_ratified_values():
    assert _perimeter.PERIMETER_SNAPSHOT_RETENTION_AGE_H == 168
    assert _perimeter.PERIMETER_SNAPSHOT_ENGINE_PRECEDENCE[0] == "frigate_event"
    # Kill switch default OFF (feature on) — ratified in plan §D5.
    assert _const.PERIMETER_SNAPSHOT_KILL_LEGACY_URL is False
