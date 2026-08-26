"""C-8 wire-in anchor for D1 auto-release sweep.

Two complementary checks:

1. **Helper behavior** — calling
   ``HVACCoordinator._schedule_excursion_autorelease_sweep`` on a shim
   registers an interval AND appends the unsub to
   ``self._unsub_listeners``. Removing the
   ``self._unsub_listeners.append(async_track_time_interval(...))``
   line inside the helper turns this test RED.

2. **Wire-in in async_setup** — AST parse of ``hvac.py`` asserts
   ``async_setup`` contains a call to
   ``self._schedule_excursion_autorelease_sweep()``. Removing that call
   turns this test RED — the defined-but-never-scheduled hazard
   Review C-8 named.
"""

from __future__ import annotations

import ast
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

_this_dir = os.path.dirname(__file__)
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

import _excursion_harness  # noqa: E402
_mods = _excursion_harness.bootstrap()
_hvac_mod = _mods["hvac"]
_ex = _mods["hvac_excursion"]


HVAC_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation",
    "domain_coordinators", "hvac.py",
)


def test_schedule_sweep_appends_unsub_to_listeners():
    HVACCoordinator = _hvac_mod.HVACCoordinator

    unsub_marker = object()
    calls = []
    orig_track = _hvac_mod.async_track_time_interval

    def _fake_track(hass, cb, interval):
        calls.append((hass, cb, interval))
        return unsub_marker

    _hvac_mod.async_track_time_interval = _fake_track
    try:
        fake_self = SimpleNamespace(
            hass=MagicMock(),
            _unsub_listeners=[],
        )
        HVACCoordinator._schedule_excursion_autorelease_sweep(fake_self)
    finally:
        _hvac_mod.async_track_time_interval = orig_track

    assert len(calls) == 1
    hass_arg, cb_arg, interval_arg = calls[0]
    assert hass_arg is fake_self.hass
    assert interval_arg.total_seconds() == _ex.EXCURSION_AUTORELEASE_SWEEP_S
    assert fake_self._unsub_listeners == [unsub_marker], (
        "sweep unsub must be appended to _unsub_listeners for teardown"
    )


def test_async_setup_calls_the_sweep_helper():
    with open(HVAC_PATH, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    found = False
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == "HVACCoordinator":
            for method in cls.body:
                if (
                    isinstance(method, ast.AsyncFunctionDef)
                    and method.name == "async_setup"
                ):
                    for call in ast.walk(method):
                        if (
                            isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and call.func.attr
                            == "_schedule_excursion_autorelease_sweep"
                            and isinstance(call.func.value, ast.Name)
                            and call.func.value.id == "self"
                        ):
                            found = True
                            break
    assert found, (
        "HVACCoordinator.async_setup must call "
        "self._schedule_excursion_autorelease_sweep() — otherwise the "
        "sweep is defined but never scheduled (Review C-8 hazard)."
    )
