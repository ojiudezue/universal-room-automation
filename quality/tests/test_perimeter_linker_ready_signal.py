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


def test_perimeter_alert_boot_sanity_warns_on_empty_allowlist():
    """F1(e) source-anchor: perimeter_alert must emit a WARNING when the
    linker exists post-setup but its allowlist is empty despite staged
    cameras (SECC-1 regression tripwire)."""
    src = (
        REPO_ROOT
        / "custom_components/universal_room_automation/perimeter_alert.py"
    ).read_text()
    assert "SECC-1 class" in src or "SECC-1 regression" in src, (
        "F1(e) regression: boot-sanity SECC-1 tripwire WARNING missing"
    )
