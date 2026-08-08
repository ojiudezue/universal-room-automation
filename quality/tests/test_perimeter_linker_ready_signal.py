"""F1(d) (2026-08-07 fix-up cycle-4): real-wiring test for the exterior
track linker allowlist install path.

The prior test surface only exercised set_allowed_cameras() by hand,
which hid SECC-1: the inline install in PerimeterAlertManager.async_setup()
runs BEFORE __init__.py registers the exterior_track_linker in
hass.data — so `_linker is None`, the install was a silent no-op, and
the fail-closed reject path would have bricked exterior tracking.

This file pins:
  (1) The linker admits events (bootstrap window) until set_allowed_cameras
      has been invoked at least once — pre-install must NOT drop real
      perimeter events (F1(c) design (i)).
  (2) After install, off-list cameras are rejected AND counted (F1e boot-
      sanity + F10 bounded counter interplay).
  (3) PerimeterAlertManager source subscribes to SIGNAL_EXTERIOR_LINKER_READY
      and installs the staged allowlist from that callback — mutation
      drill: deleting the subscription block MUST make this test RED.
"""

from __future__ import annotations

import importlib.util as _il
import sys
import types
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path
from unittest.mock import MagicMock


# --- HA stub prelude (matches sibling test files) ---------------------------

_ident = lambda fn: fn  # noqa: E731


def _mock(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


_HA = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": MagicMock, "callback": _ident,
                           "Event": MagicMock},
    "homeassistant.helpers": {},
    "homeassistant.helpers.event": {
        "async_call_later": lambda *a, **kw: MagicMock(),
        "async_track_state_change_event": lambda *a, **kw: MagicMock(),
        "async_track_time_interval": lambda *a, **kw: (lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda *a, **kw: MagicMock(),
        "async_dispatcher_send": lambda *a, **kw: None,
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: _dt.now(_tz.utc),
        "now": lambda: _dt.now(_tz.utc),
    },
}
for _n, _a in _HA.items():
    _existing = sys.modules.get(_n)
    if _existing is None:
        sys.modules[_n] = _mock(_n, **_a)
    else:
        for _k, _v in _a.items():
            if not hasattr(_existing, _k):
                setattr(_existing, _k, _v)


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Pre-register the package so `from .const` works during exec of the linker.
_PKG = "custom_components.universal_room_automation"
if _PKG not in sys.modules:
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [str(REPO_ROOT / "custom_components/universal_room_automation")]
    sys.modules[_PKG] = pkg
_CONST_NAME = _PKG + ".const"
if _CONST_NAME not in sys.modules:
    cspec = _il.spec_from_file_location(
        _CONST_NAME,
        REPO_ROOT / "custom_components/universal_room_automation/const.py",
    )
    cmod = _il.module_from_spec(cspec)
    sys.modules[_CONST_NAME] = cmod
    cspec.loader.exec_module(cmod)

_LINKER_PATH = REPO_ROOT / "custom_components/universal_room_automation/exterior_track_linker.py"
_spec = _il.spec_from_file_location(
    _PKG + ".exterior_track_linker", _LINKER_PATH,
)
_linker_mod = _il.module_from_spec(_spec)
sys.modules[_PKG + ".exterior_track_linker"] = _linker_mod
_spec.loader.exec_module(_linker_mod)

ExteriorTrackLinker = _linker_mod.ExteriorTrackLinker


# ---------------------------------------------------------------------------


def _fresh_linker():
    hass = MagicMock()
    return ExteriorTrackLinker(hass)


def test_bootstrap_window_admits_before_install():
    """F1(c) design (i): with no allowlist installed yet, observe()
    admits the event (falls through to open-a-track path). Preserves
    the pre-fail-closed behavior so a linker that runs BEFORE
    perimeter_alert.async_setup() cannot drop real perimeter events."""
    lk = _fresh_linker()
    now = _dt.now(_tz.utc)
    # Any camera, before install — must NOT be rejected on allowlist.
    track = lk.observe(
        camera="somecam", label="person",
        event_id="ev1", score=0.9, sub_label=None, now=now,
    )
    # A track was opened (admitted). If instead the pre-install path
    # rejected, track would be None AND ignored_offlist_events['somecam']
    # would be >= 1.
    assert track is not None, (
        "F1(c) regression: pre-install observe() rejected — bootstrap "
        "window would drop real perimeter events. Design (i) requires "
        "admit-all until set_allowed_cameras() is invoked."
    )
    assert lk._ignored_offlist_events.get("somecam", 0) == 0


def test_post_install_rejects_offlist_and_counts_it():
    """After allowlist installed, an off-list camera is rejected AND
    counted for post-hoc verification."""
    lk = _fresh_linker()
    lk.set_allowed_cameras({"perimeter_a", "perimeter_b"})
    # F1: install flips _allowlist_installed=True and clears prior counters.
    assert lk._allowlist_installed is True
    assert lk._ignored_offlist_events == {}
    now = _dt.now(_tz.utc)
    track = lk.observe(
        camera="interior_playroom", label="person",
        event_id="ev2", score=0.9, sub_label=None, now=now,
    )
    assert track is None, "off-list camera must be rejected post-install"
    assert lk._ignored_offlist_events.get("interior_playroom", 0) == 1


def test_post_install_admits_allowlisted_camera():
    lk = _fresh_linker()
    lk.set_allowed_cameras({"perimeter_a"})
    now = _dt.now(_tz.utc)
    track = lk.observe(
        camera="perimeter_a", label="person",
        event_id="ev3", score=0.9, sub_label=None, now=now,
    )
    assert track is not None


def test_ignored_offlist_events_is_bounded_f10():
    """F10: the reject counter is capped so a spurious burst of unknown
    camera keys cannot grow the attr unbounded."""
    lk = _fresh_linker()
    lk.set_allowed_cameras({"perimeter_a"})
    cap = lk._ignored_offlist_cap
    now = _dt.now(_tz.utc)
    # Fire cap+50 unique unknown cams; unique key count must stay <= cap.
    for i in range(cap + 50):
        lk.observe(
            camera=f"cam_{i}", label="person",
            event_id=f"ev{i}", score=0.5, sub_label=None, now=now,
        )
    assert len(lk._ignored_offlist_events) <= cap, (
        f"F10 regression: reject counter unbounded "
        f"({len(lk._ignored_offlist_events)} > cap={cap})"
    )


def test_perimeter_alert_subscribes_to_linker_ready_source_anchor():
    """F1(a) source-anchor: PerimeterAlertManager.async_setup MUST both
    (i) subscribe to SIGNAL_EXTERIOR_LINKER_READY, and (ii) call
    set_allowed_cameras from that callback. Deleting either block is
    the SECC-1 regression this test guards.

    Mutation drill: removing the ``async_dispatcher_connect(... SIGNAL_
    EXTERIOR_LINKER_READY ...)`` block makes this assertion RED.
    """
    src = (
        REPO_ROOT
        / "custom_components/universal_room_automation/perimeter_alert.py"
    ).read_text()
    # Find the async_setup body — the wiring must be inside it, not in
    # some dead branch.
    idx = src.index("async def async_setup(self)")
    body = src[idx:idx + 20000]
    assert "SIGNAL_EXTERIOR_LINKER_READY" in body, (
        "F1(a) regression: perimeter_alert.async_setup does not reference "
        "SIGNAL_EXTERIOR_LINKER_READY — allowlist install would be dead "
        "code again (SECC-1)."
    )
    assert "async_dispatcher_connect" in body, (
        "F1(a) regression: perimeter_alert.async_setup does not subscribe "
        "to the READY signal via async_dispatcher_connect."
    )
    # And the deferred install must call set_allowed_cameras.
    assert "set_allowed_cameras" in body, (
        "F1(a) regression: set_allowed_cameras not called from async_setup"
    )


# ---------------------------------------------------------------------------
# BEHAVIORAL tests (added 2026-08-07 straggler-batch): drive the real
# PerimeterAlertManager.async_setup path end-to-end so the F1 CRITICAL
# fix is pinned by observable behavior (allowlist actually installed on
# the linker, off-list rejected, on-list admitted) rather than a
# source-string grep of the subscription block.
#
# Orchestrator mutation drill that motivated this: replacing
# ``_lk.set_allowed_cameras(self._perimeter_allowlist)`` with ``pass``
# inside ``_install_on_ready`` left the pre-existing suite GREEN. These
# tests neuter that mutation.
# ---------------------------------------------------------------------------

import asyncio as _asyncio
import importlib.util as _il2
import os as _os


def _load_perimeter_module():
    """Load perimeter_alert.py with just enough package plumbing.

    Idempotent — if the module (or its sibling deps) is already loaded
    (e.g. because ``test_perimeter_alert_nm_routing.py`` ran first) we
    reuse the cached module.
    """
    _pa_name = _PKG + ".perimeter_alert"
    if _pa_name in sys.modules:
        return sys.modules[_pa_name]

    # Ensure a few additional HA helper stubs perimeter_alert may pull.
    for _n, _a in {
        "homeassistant.helpers.entity": {"DeviceInfo": dict,
                                          "EntityCategory": MagicMock()},
        "homeassistant.helpers.entity_registry": {"async_get": MagicMock()},
        "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    }.items():
        existing = sys.modules.get(_n)
        if existing is None:
            sys.modules[_n] = _mock(_n, **_a)
        else:
            for _k, _v in _a.items():
                if not hasattr(existing, _k):
                    setattr(existing, _k, _v)

    _ura_path = REPO_ROOT / "custom_components/universal_room_automation"

    # domain_coordinators.base is needed transitively
    _dc_name = _PKG + ".domain_coordinators"
    if _dc_name not in sys.modules:
        _dc = types.ModuleType(_dc_name)
        _dc.__path__ = [str(_ura_path / "domain_coordinators")]
        sys.modules[_dc_name] = _dc
    _base_name = _dc_name + ".base"
    if _base_name not in sys.modules:
        spec = _il2.spec_from_file_location(
            _base_name, _ura_path / "domain_coordinators" / "base.py",
        )
        mod = _il2.module_from_spec(spec)
        sys.modules[_base_name] = mod
        spec.loader.exec_module(mod)

    # camera_resolver — perimeter_alert imports _PERSON_SUFFIXES from it
    _cr_name = _PKG + ".camera_resolver"
    if _cr_name not in sys.modules:
        spec = _il2.spec_from_file_location(
            _cr_name, _ura_path / "camera_resolver.py",
        )
        mod = _il2.module_from_spec(spec)
        sys.modules[_cr_name] = mod
        spec.loader.exec_module(mod)

    spec = _il2.spec_from_file_location(
        _pa_name, _ura_path / "perimeter_alert.py",
    )
    mod = _il2.module_from_spec(spec)
    sys.modules[_pa_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _build_manager_captured(existing_linker=None):
    """Construct a PerimeterAlertManager wired to capture the READY
    subscription callback and stub out camera-resolution paths.

    Returns (manager, hass, captured_callbacks_by_signal).
    """
    pa_mod = _load_perimeter_module()
    from custom_components.universal_room_automation.const import (
        DOMAIN, CONF_PERIMETER_CAMERAS,
    )
    import homeassistant.helpers.dispatcher as _disp_mod

    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    if existing_linker is not None:
        hass.data[DOMAIN]["exterior_track_linker"] = existing_linker
    hass.bus = MagicMock()
    hass.bus.async_listen = MagicMock(return_value=MagicMock())
    hass.bus.async_listen_once = MagicMock(return_value=MagicMock())
    hass.config = MagicMock()
    hass.is_stopping = False

    mgr = pa_mod.PerimeterAlertManager(hass)

    # Return one perimeter camera whose person_binary_sensor collapses
    # to camera key "frontdoor" (via the _person_occupancy suffix).
    info = types.SimpleNamespace(
        person_binary_sensor="binary_sensor.frontdoor_person_occupancy",
        platform="frigate",
    )
    mgr._resolve_camera_infos = lambda conf_key: (
        [("camera.frontdoor", info)]
        if conf_key == CONF_PERIMETER_CAMERAS else []
    )
    mgr._resolve_legs = lambda *a, **kw: []
    mgr._entity_exists = lambda eid: False
    mgr._get_integration_config = lambda: {}

    # Capture dispatcher subscriptions on the module perimeter_alert.py
    # imports at CALL time (`from homeassistant.helpers.dispatcher import
    # async_dispatcher_connect` inside async_setup).
    captured: dict = {}

    def _fake_connect(_hass, signal, cb):
        captured.setdefault(signal, []).append(cb)
        return lambda: None

    _orig = _disp_mod.async_dispatcher_connect
    _disp_mod.async_dispatcher_connect = _fake_connect
    try:
        _asyncio.run(mgr.async_setup())
    finally:
        _disp_mod.async_dispatcher_connect = _orig
    return mgr, hass, captured


def test_ready_callback_installs_allowlist_on_late_linker():
    """F1 BEHAVIORAL (mutation-anchored): reproduces the real boot ordering
    where the exterior_track_linker is NOT in hass.data at async_setup()
    time. The READY-signal callback captured by the dispatcher stub MUST,
    when invoked after the linker registers, call set_allowed_cameras() so
    the linker's allowlist is populated. Neutering the install line inside
    ``_install_on_ready`` (e.g. ``_lk.set_allowed_cameras(...)`` -> ``pass``)
    MUST make this test RED.
    """
    from custom_components.universal_room_automation.const import DOMAIN
    from custom_components.universal_room_automation.domain_coordinators.signals import (
        SIGNAL_EXTERIOR_LINKER_READY,
    )

    mgr, hass, captured = _build_manager_captured(existing_linker=None)

    # (a) staged allowlist derived from the perimeter camera
    assert mgr._perimeter_allowlist == {"frontdoor"}, (
        "staged allowlist did not derive from _camera_key_for_sensor"
    )
    # (b) READY subscription captured
    cbs = captured.get(SIGNAL_EXTERIOR_LINKER_READY) or []
    assert cbs, (
        "async_setup did not subscribe a callback to "
        "SIGNAL_EXTERIOR_LINKER_READY"
    )

    # Now the linker REGISTERS (post-setup, as in real boot ordering).
    linker = _fresh_linker()
    assert not linker._allowed_cameras
    assert linker._allowlist_installed is False
    hass.data[DOMAIN]["exterior_track_linker"] = linker

    # Fire the captured READY callback
    for cb in cbs:
        cb()

    # F1 CORE ASSERTION — this is what the source-grep test missed.
    assert linker._allowlist_installed is True, (
        "F1 regression: READY callback ran but did not flip "
        "_allowlist_installed — set_allowed_cameras() was NOT called on "
        "the linker (SECC-1 dead-install returned)."
    )
    assert linker._allowed_cameras == {"frontdoor"}, (
        "F1 regression: linker _allowed_cameras not populated from the "
        f"staged perimeter allowlist (got {linker._allowed_cameras!r})"
    )

    # Behavioral tie-in: an off-list interior camera is rejected AND
    # counted; the on-list perimeter camera is admitted. This proves the
    # install is not just cosmetic — the observable fail-closed behavior
    # the F1 fix exists to enable is actually enabled.
    now = _dt.now(_tz.utc)
    rejected = linker.observe(
        camera="interior_playroom", label="person",
        event_id="evX", score=0.9, sub_label=None, now=now,
    )
    assert rejected is None, "off-list interior camera must be rejected"
    assert linker._ignored_offlist_events.get("interior_playroom", 0) == 1

    admitted = linker.observe(
        camera="frontdoor", label="person",
        event_id="evY", score=0.9, sub_label=None, now=now,
    )
    assert admitted is not None, (
        "on-list perimeter camera must be admitted after install"
    )


def test_perimeter_alert_boot_sanity_warns_on_empty_allowlist(caplog):
    """F1(e) BEHAVIORAL: when the linker IS present at async_setup time
    but somehow ends up with an empty allowlist (SECC-1 class regression
    — silent no-op install), production must emit a WARNING record. This
    used to be a source-grep; now it drives the real code path.

    Neutering the ``_LOGGER.warning(...)`` inside the boot-sanity block
    MUST make this test RED.
    """
    import logging as _logging
    from custom_components.universal_room_automation.const import DOMAIN

    # A stub linker whose set_allowed_cameras is a NO-OP — simulates the
    # regression class where the install site was silently broken.
    class _BrokenLinker:
        _allowed_cameras: set = set()
        _allowlist_installed: bool = False

        def set_allowed_cameras(self, cams):
            # Intentional no-op: the SECC-1 regression shape.
            return

    broken = _BrokenLinker()
    with caplog.at_level(_logging.WARNING,
                        logger="custom_components.universal_room_automation.perimeter_alert"):
        _build_manager_captured(existing_linker=broken)

    hits = [r for r in caplog.records
            if "SECC-1" in r.getMessage() and r.levelno >= _logging.WARNING]
    assert hits, (
        "F1(e) regression: boot-sanity WARNING did not fire when the "
        "linker was present post-setup but its allowlist stayed empty. "
        f"Records seen: {[r.getMessage() for r in caplog.records]!r}"
    )


# ---------------------------------------------------------------------------
# BOOTSANITY-1 (2026-08-08): the ONLY guard that fires on real cold-boot
# ordering (linker registered AFTER PerimeterAlertManager.async_setup)
# lives in the READY-signal callback, NOT at the end of async_setup. The
# following two tests pin that. Mutation drills documented inline.
# ---------------------------------------------------------------------------


def test_bootsanity1_ready_path_warns_when_set_allowed_is_noop(caplog):
    """BOOTSANITY-1: linker ABSENT at async_setup time (real cold boot),
    then registers, READY callback fires — but set_allowed_cameras is a
    silent no-op (SECC-1 class regression). Production must emit a
    WARNING from the READY callback path.

    Mutation drill: delete the ``if not getattr(_lk, "_allowed_cameras",
    None): _LOGGER.warning(...)`` block inside ``_install_on_ready`` in
    perimeter_alert.py -> this test goes RED. (End-of-setup guard cannot
    fire in this scenario — linker was None then.)
    """
    import logging as _logging
    from custom_components.universal_room_automation.const import DOMAIN
    from custom_components.universal_room_automation.domain_coordinators.signals import (
        SIGNAL_EXTERIOR_LINKER_READY,
    )

    # Setup with NO linker in hass.data (cold-boot ordering).
    mgr, hass, captured = _build_manager_captured(existing_linker=None)
    cbs = captured.get(SIGNAL_EXTERIOR_LINKER_READY) or []
    assert cbs, "async_setup did not subscribe to READY"

    class _BrokenLinker:
        _allowed_cameras: set = set()
        _allowlist_installed: bool = False

        def set_allowed_cameras(self, cams):
            return  # silent no-op — SECC-1 shape

    broken = _BrokenLinker()
    hass.data[DOMAIN]["exterior_track_linker"] = broken

    with caplog.at_level(
        _logging.WARNING,
        logger="custom_components.universal_room_automation.perimeter_alert",
    ):
        for cb in cbs:
            cb()

    hits = [r for r in caplog.records
            if "SECC-1" in r.getMessage() and r.levelno >= _logging.WARNING]
    assert hits, (
        "BOOTSANITY-1 regression: READY-path sanity WARNING did not fire "
        "when set_allowed_cameras returned but the allowlist stayed empty. "
        f"Records seen: {[r.getMessage() for r in caplog.records]!r}"
    )


def test_bootsanity1_diagnostic_sensor_exposes_allowlist_state():
    """BOOTSANITY-1: ExteriorOpenTracksDiagnosticSensor.extra_state_attributes
    must expose ``allowlist_installed`` (bool) and ``allowlist_camera_count``
    (int) sourced from the live linker. This is the LIVE observable that
    proves the install succeeded (log WARNING is silence-on-success).

    Mutation drill: remove either attribute from the sensor's attrs dict
    -> this test goes RED.
    """
    import importlib.util as _il3
    import types as _types

    # Ensure sensor.py deps are stubbed enough to source-load it.
    for _n, _a in {
        "homeassistant.helpers.restore_state": {"RestoreEntity": object},
        "homeassistant.helpers.entity": {"DeviceInfo": dict,
                                          "EntityCategory": MagicMock()},
        "homeassistant.helpers.entity_platform": {
            "AddEntitiesCallback": MagicMock(),
        },
        "homeassistant.components.sensor": {
            "SensorEntity": object, "SensorStateClass": MagicMock(),
            "SensorDeviceClass": MagicMock(),
        },
        "homeassistant.components.binary_sensor": {
            "BinarySensorEntity": object,
        },
        "homeassistant.config_entries": {"ConfigEntry": object},
        "homeassistant.const": {"PERCENTAGE": "%", "UnitOfEnergy": MagicMock(),
                                 "UnitOfPower": MagicMock(),
                                 "UnitOfTemperature": MagicMock(),
                                 "STATE_ON": "on", "STATE_OFF": "off",
                                 "STATE_UNAVAILABLE": "unavailable",
                                 "STATE_UNKNOWN": "unknown",
                                 "EntityCategory": MagicMock()},
    }.items():
        existing = sys.modules.get(_n)
        if existing is None:
            sys.modules[_n] = _mock(_n, **_a)
        else:
            for _k, _v in _a.items():
                if not hasattr(existing, _k):
                    setattr(existing, _k, _v)

    # We DO NOT source-load the whole sensor.py (heavy). Instead we test
    # the load-bearing attribute-computation snippet on a fake linker via
    # a direct call to the property body. To avoid duplicating logic, we
    # exercise the linker end and inline-mirror the two attrs the way the
    # property builds them -- BUT to guard against attribute-name drift
    # we ALSO grep the sensor source to prove the attrs are wired there.
    src = (
        REPO_ROOT
        / "custom_components/universal_room_automation/sensor.py"
    ).read_text()
    assert '"allowlist_installed"' in src, (
        "BOOTSANITY-1 regression: sensor.py does not expose "
        "allowlist_installed attribute"
    )
    assert '"allowlist_camera_count"' in src, (
        "BOOTSANITY-1 regression: sensor.py does not expose "
        "allowlist_camera_count attribute"
    )

    # Now drive the REAL linker's public state to prove the values the
    # sensor reads flip correctly on install.
    lk = _fresh_linker()
    # Before install
    assert lk._allowlist_installed is False
    assert len(lk._allowed_cameras) == 0
    # After install
    lk.set_allowed_cameras({"cam_a", "cam_b", "cam_c"})
    assert lk._allowlist_installed is True
    assert len(lk._allowed_cameras) == 3
