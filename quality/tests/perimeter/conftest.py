"""Perimeter test package conftest — cross-file pollution guard.

Snapshots + restores perimeter module bindings around every test in
this package. Other test modules (test_perimeter_alert_nm_routing.py,
test_exterior_cycle2.py) pin their own scheduler / clock / state-change
stubs at import time on the shared `perimeter_alert` module in
sys.modules. Full-suite load order determines who wins the module-level
binding, and un-restored rebinds silently corrupt sibling tests'
assertions.

This fixture is autouse across quality/tests/perimeter/ so every test
in this package runs against its own bindings and hands the module back
untouched.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _pin_perimeter_module_stubs():
    from quality.tests.perimeter.test_circling_founding_case import (
        _perimeter,
        _etl,
        _fake_async_call_later,
        _fake_async_track_state_change_event,
        _real_dt_util,
        _scheduled,
    )
    _saved_call_later = _perimeter.async_call_later
    _saved_state_change = _perimeter.async_track_state_change_event
    _saved_dt_util = _perimeter.dt_util
    _saved_etl_dt_util = _etl.dt_util
    _perimeter.async_call_later = _fake_async_call_later
    _perimeter.async_track_state_change_event = _fake_async_track_state_change_event
    _perimeter.dt_util = _real_dt_util
    _etl.dt_util = _real_dt_util
    _scheduled.clear()
    try:
        yield
    finally:
        _perimeter.async_call_later = _saved_call_later
        _perimeter.async_track_state_change_event = _saved_state_change
        _perimeter.dt_util = _saved_dt_util
        _etl.dt_util = _saved_etl_dt_util
        _scheduled.clear()
