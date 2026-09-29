"""HVAC-ARRESTER-EPISODE-CANCELS-AC-RESET-RESTORE-1 (B-L3 in the
v5.103.23 W1/W2 finish review, pre-existing on develop).

A NEW governed override episode routes through the arrester's
`_handle_severe_override` / `_handle_normal_override` (and the
startup-audit stale-override branch). All three previously called
`_cancel_zone_timers`, which ALSO popped `_reset_timers` — the pending
AC hard-reset RESTORE timer. If a manual change was booked inside the
Carrier lag window after the reset's `off` write, the zone stayed off
until the arrester's own revert re-asserted heat_cool (~2 min on the
severe path, up to ~20 min on grace+compromise; indefinitely if the
revert stood down).

The fix renames `_cancel_zone_timers` -> `_cancel_arrester_timers` and
drops `_reset_timers` from its scope (mirroring the shape of
`_defer_arrester_to_borrow` after Round 3 LOW-2). Three sites updated:
`_handle_severe_override`, `_handle_normal_override`, and the
startup-audit stale-override branch in `async_startup_arrester_audit`.

Legitimate cancel sites for the reset restore timer — `teardown()`,
`ac_reset_enabled = False`, and the fire-time pop in
`_restore_after_reset` — handle `_reset_timers` directly and stay
intact. Verified by the negative tests below.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# HA stubs (setdefault so sibling test files can win their own registrations)
# ---------------------------------------------------------------------------

def _mock_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731


def _utcnow_real() -> datetime:
    return datetime.now(timezone.utc)


def _now_real() -> datetime:
    return datetime.now()


_mods: dict[str, dict] = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": MagicMock,
        "Event": MagicMock,
        "CALLBACK_TYPE": object,
        "callback": _identity,
    },
    "homeassistant.helpers": {},
    "homeassistant.helpers.event": {
        "async_call_later": MagicMock(return_value=lambda: None),
        "async_track_state_change_event": MagicMock(return_value=lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": _utcnow_real,
        "now": _now_real,
        "UTC": timezone.utc,
    },
    "homeassistant.components": {},
    "homeassistant.components.recorder": {"get_instance": MagicMock()},
    "homeassistant.components.recorder.history": {
        "get_significant_states": MagicMock(),
    },
}
for _name, _attrs in _mods.items():
    sys.modules.setdefault(_name, _mock_module(_name, **_attrs))


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_HERE = os.path.dirname(__file__)
_URA_PATH = os.path.join(_HERE, "..", "..", "custom_components",
                         "universal_room_automation")
_DC_PATH = os.path.join(_URA_PATH, "domain_coordinators")

if "custom_components" not in sys.modules:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [os.path.join(_HERE, "..", "..", "custom_components")]
    sys.modules["custom_components"] = _cc
if "custom_components.universal_room_automation" not in sys.modules:
    _ura = types.ModuleType("custom_components.universal_room_automation")
    _ura.__path__ = [_URA_PATH]
    sys.modules["custom_components.universal_room_automation"] = _ura


def _load(modname: str, relpath: str) -> types.ModuleType:
    cached = sys.modules.get(modname)
    if cached is not None and getattr(cached, "__file__", None):
        return cached
    spec = importlib.util.spec_from_file_location(
        modname, os.path.join(_URA_PATH, relpath),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


_load("custom_components.universal_room_automation.const", "const.py")
if "custom_components.universal_room_automation.domain_coordinators" not in sys.modules:
    _dc = types.ModuleType(
        "custom_components.universal_room_automation.domain_coordinators"
    )
    _dc.__path__ = [_DC_PATH]
    sys.modules[
        "custom_components.universal_room_automation.domain_coordinators"
    ] = _dc
for _m in (
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
):
    _c = sys.modules.get(_m)
    if _c is not None and not getattr(_c, "__file__", None):
        del sys.modules[_m]

_load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "domain_coordinators/hvac_const.py",
)
_load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    "domain_coordinators/hvac_zones.py",
)
_load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
    "domain_coordinators/hvac_setpoint.py",
)
hvac_override = _load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
    "domain_coordinators/hvac_override.py",
)
hvac_zones = sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones"
]
hvac_const = sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac_const"
]

OverrideArrester = hvac_override.OverrideArrester
ZoneState = hvac_zones.ZoneState


CLIMATE = "climate.zone_a"
ZONE_ID = "zone_a"


class _FakeClock:
    def __init__(self, start: datetime) -> None:
        self.t = start

    def now(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t = self.t + timedelta(seconds=seconds)


@pytest.fixture
def fake_clock(monkeypatch):
    clock = _FakeClock(datetime(2026, 9, 29, 14, 0, 0))
    fake_dt = types.SimpleNamespace(now=clock.now)
    monkeypatch.setattr(hvac_override, "dt_util", fake_dt)
    return clock


def _make_arrester() -> OverrideArrester:
    zone = ZoneState(
        zone_id=ZONE_ID, zone_name="Zone A", climate_entity=CLIMATE,
    )
    zone.hvac_mode = "heat_cool"
    zone.preset_mode = "home"
    zone.target_temp_high = 76.0
    zone.target_temp_low = 70.0
    zone.current_temperature = 74.0
    zone.ac_load_sensor = None

    zm = MagicMock()
    zm.zones = {ZONE_ID: zone}
    hass = MagicMock()
    hass.states.async_all = MagicMock(return_value=[])  # no immune persons
    a = OverrideArrester(hass, zm, compromise_minutes=30, ac_reset_timeout=60,
                         enabled=True)
    return a


def _sentinel_cancel() -> MagicMock:
    """A callable that records whether it was invoked (i.e. the timer was
    cancelled). Failing this assertion is the observable form of B-L3."""
    m = MagicMock(return_value=None)
    return m


# ===========================================================================
# POSITIVE: a new governed episode must NOT cancel the pending AC-reset
# restore timer (the B-L3 defect).
# ===========================================================================

class TestArresterEpisodePreservesResetRestore:

    def test_severe_override_does_not_cancel_pending_reset_restore(self, fake_clock):
        """AC hard-reset off has fired; restore timer is pending. A human
        books a large manual change inside the Carrier lag window ->
        `_handle_severe_override` runs. The reset restore timer MUST
        still be armed (not cancelled), so heat_cool will still be
        re-asserted at reset_timeout instead of the zone stranding off
        until the arrester's revert."""
        a = _make_arrester()
        zone = a._zone_manager.zones[ZONE_ID]

        # Simulate: hard reset has written `off`, restore is scheduled.
        restore_cancel = _sentinel_cancel()
        a._reset_timers[ZONE_ID] = restore_cancel

        # New severe override booked (human dropped 12 °F).
        a._handle_severe_override(zone, "home", 76.0, 70.0, delta=-12.0)

        # The arrester engaged its own grace timer (proves the path ran).
        assert ZONE_ID in a._grace_timers, (
            "severe path must arm its grace timer"
        )
        # The pending AC-reset restore timer MUST still be present and
        # MUST NOT have been cancelled.
        assert ZONE_ID in a._reset_timers, (
            "B-L3: severe override episode wrongly popped the pending "
            "AC-reset restore timer"
        )
        assert a._reset_timers[ZONE_ID] is restore_cancel
        restore_cancel.assert_not_called()

    def test_normal_override_does_not_cancel_pending_reset_restore(self, fake_clock):
        """Same as severe, on the normal (1-3 °F) path."""
        a = _make_arrester()
        zone = a._zone_manager.zones[ZONE_ID]

        restore_cancel = _sentinel_cancel()
        a._reset_timers[ZONE_ID] = restore_cancel

        a._handle_normal_override(
            zone, "home", 76.0, 70.0, delta=-2.0,
            new_high=74.0, new_low=68.0,
        )

        assert ZONE_ID in a._grace_timers, (
            "normal path must arm its grace timer"
        )
        assert ZONE_ID in a._reset_timers, (
            "B-L3: normal override episode wrongly popped the pending "
            "AC-reset restore timer"
        )
        assert a._reset_timers[ZONE_ID] is restore_cancel
        restore_cancel.assert_not_called()

    def test_helper_cancel_arrester_timers_leaves_reset_restore(self, fake_clock):
        """Direct call on the helper: only grace + compromise are popped;
        the AC-reset restore timer stays."""
        a = _make_arrester()
        grace_cancel = _sentinel_cancel()
        comp_cancel = _sentinel_cancel()
        restore_cancel = _sentinel_cancel()
        a._grace_timers[ZONE_ID] = grace_cancel
        a._compromise_timers[ZONE_ID] = comp_cancel
        a._reset_timers[ZONE_ID] = restore_cancel

        a._cancel_arrester_timers(ZONE_ID)

        assert ZONE_ID not in a._grace_timers
        assert ZONE_ID not in a._compromise_timers
        grace_cancel.assert_called_once()
        comp_cancel.assert_called_once()
        # Reset restore untouched.
        assert ZONE_ID in a._reset_timers
        assert a._reset_timers[ZONE_ID] is restore_cancel
        restore_cancel.assert_not_called()


# ===========================================================================
# NEGATIVE: legitimate cancel sites for `_reset_timers` still cancel it.
# ===========================================================================

class TestLegitimateResetRestoreCancelSites:

    def test_teardown_cancels_pending_reset_restore(self, fake_clock):
        a = _make_arrester()
        restore_cancel = _sentinel_cancel()
        a._reset_timers[ZONE_ID] = restore_cancel

        a.teardown()

        restore_cancel.assert_called_once()
        assert a._reset_timers == {}

    def test_disabling_ac_reset_cancels_pending_reset_restore(self, fake_clock):
        a = _make_arrester()
        restore_cancel = _sentinel_cancel()
        a._reset_timers[ZONE_ID] = restore_cancel

        a.ac_reset_enabled = False

        restore_cancel.assert_called_once()
        assert ZONE_ID not in a._reset_timers
