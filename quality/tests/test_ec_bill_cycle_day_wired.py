"""EC-BILL-CYCLE-DAY-WIRED-1 — the configured bill-cycle day reaches the
billing engine (CostTracker + PeakAvoidanceTracker), applies in place on an
options save, and a mid-cycle change re-keys without wiping the cycle.

Runs against the REAL integration package (scoped sys.modules fixture copied
from test_ec_role_defaults_rev5.py; restored exactly on teardown).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ura = None
ec_const = None
CONF_ENTRY_TYPE = "entry_type"
DOMAIN = "universal_room_automation"
ENTRY_TYPE_COORDINATOR_MANAGER = "coordinator_manager"


def _is_set_aside(name: str, mod) -> bool:
    if name == "custom_components" or name.startswith("custom_components."):
        return True
    if name == "homeassistant" or name.startswith("homeassistant."):
        # A stub is anything that isn't a really-imported module (MagicMock,
        # or a bare ModuleType, whose __spec__ is None).
        import types
        return not isinstance(mod, types.ModuleType) or mod.__spec__ is None
    return False


@pytest.fixture(autouse=True, scope="module")
def _real_ura_package():
    global ura, ec_const, CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_COORDINATOR_MANAGER
    import importlib

    before = dict(sys.modules)
    for name, mod in list(sys.modules.items()):
        if _is_set_aside(name, mod):
            del sys.modules[name]
    importlib.invalidate_caches()
    try:
        ura = importlib.import_module("custom_components.universal_room_automation")
        const = importlib.import_module("custom_components.universal_room_automation.const")
        ec_const = importlib.import_module(
            "custom_components.universal_room_automation.domain_coordinators.energy_const",
        )
        assert hasattr(ura, "_apply_in_place"), ura
        CONF_ENTRY_TYPE = const.CONF_ENTRY_TYPE
        DOMAIN = const.DOMAIN
        ENTRY_TYPE_COORDINATOR_MANAGER = const.ENTRY_TYPE_COORDINATOR_MANAGER
        yield
    finally:
        for name in list(sys.modules):
            if name not in before:
                del sys.modules[name]
        for name, mod in before.items():
            if sys.modules.get(name) is not mod:
                sys.modules[name] = mod



KEY = "energy_bill_cycle_day"
NOW = datetime(2026, 10, 20, 12, 0, 0)


def _coord(entity_config):
    from custom_components.universal_room_automation.domain_coordinators.energy import (
        EnergyCoordinator,
    )
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.config_entries.async_entries = lambda *_a, **_k: []
    return EnergyCoordinator(
        hass=hass, reserve_soc=20, decision_interval=10,
        entity_config=entity_config, tou_engine=MagicMock(name="tou_engine"),
    )


# --- construction site 1: CostTracker ---------------------------------------

def test_cost_tracker_uses_configured_cycle_day():
    c = _coord({KEY: 24})
    # Oracle: PEC bills 24th->24th; on 10-20 the cycle began 2026-09-24.
    assert c._billing._get_cycle_start(NOW).isoformat() == "2026-09-24"


# --- construction site 2: PeakAvoidanceTracker ------------------------------

def test_peak_avoidance_uses_configured_cycle_day():
    c = _coord({KEY: 24})
    assert c._peak_avoidance._get_cycle_start(NOW).isoformat() == "2026-09-24"


def test_public_accessor_follows_configured_day():
    c = _coord({KEY: 24})
    assert c.get_billing_cycle_start(NOW).isoformat() == "2026-09-24"


@pytest.mark.parametrize("raw,expected", [
    (None, 23), ("abc", 23), (40, 28), (0, 1), ("24", 24), (24.0, 24),
])
def test_cycle_day_coercion(raw, expected):
    c = _coord({KEY: raw} if raw is not None else {})
    assert c._billing._bill_cycle_day == expected
    assert c._peak_avoidance._bill_cycle_day == expected


# --- options save applies in place (no reload) ------------------------------

def test_key_is_reload_suppressed():
    assert KEY in ura.OPTIONS_RELOAD_SUPPRESS_KEYS


def test_apply_in_place_pushes_day_to_both_trackers():
    c = _coord({KEY: 23})
    c.hass.async_create_task = MagicMock(side_effect=lambda coro: coro.close())
    manager = SimpleNamespace(coordinators={"energy": c})
    hass = MagicMock()
    hass.data = {DOMAIN: {"coordinator_manager": manager}}
    with patch("homeassistant.util.dt.now", return_value=NOW):
        applied = ura._apply_in_place(hass, MagicMock(), {KEY}, {KEY: 24})
    assert KEY in applied
    assert c._billing._get_cycle_start(NOW).isoformat() == "2026-09-24"
    assert c._peak_avoidance._get_cycle_start(NOW).isoformat() == "2026-09-24"


# --- mid-cycle change safety -------------------------------------------------

def _tracker():
    from custom_components.universal_room_automation.domain_coordinators.energy_billing import (
        CostTracker,
    )
    t = CostTracker(MagicMock(), MagicMock(), bill_cycle_day=23)
    t._check_cycle_reset(NOW)          # keyed to 2026-09-23
    t._cost_this_cycle = 50.0
    t._import_kwh_cycle = 400.0
    return t


def test_mid_cycle_change_rekeys_without_wiping():
    t = _tracker()
    assert t.set_bill_cycle_day(24, NOW) is True
    assert t._cycle_start_date == "2026-09-24"
    t._check_cycle_reset(NOW)          # next tick must NOT reset the cycle
    assert t._cost_this_cycle == 50.0
    assert t._import_kwh_cycle == 400.0


def test_same_day_is_noop():
    t = _tracker()
    assert t.set_bill_cycle_day(23, NOW) is False
    assert t._cost_this_cycle == 50.0


def test_new_boundary_resets_on_the_new_day_only():
    t = _tracker()
    t.set_bill_cycle_day(24, NOW)
    t._check_cycle_reset(datetime(2026, 10, 23, 12))
    assert t._cost_this_cycle == 50.0          # 23rd is no longer a boundary
    t._check_cycle_reset(datetime(2026, 10, 24, 0, 5))
    assert t._cost_this_cycle == 0.0
    assert t._cycle_start_date == "2026-10-24"


def test_reseed_adds_today_to_db_full_days():
    t = _tracker()
    t._cost_today = 2.5
    t._import_kwh_today = 10.0
    t._export_kwh_today = 1.0
    t.reseed_cycle({"days": 26, "net_cost": 40.0, "import_kwh": 300.0, "export_kwh": 20.0})
    assert t._cost_this_cycle == 42.5
    assert t._import_kwh_cycle == 310.0
    assert t._export_kwh_cycle == 21.0
    assert t._db_days_in_cycle == 26


def test_peak_avoidance_mid_cycle_change_preserves_cycle():
    from custom_components.universal_room_automation.domain_coordinators.energy_billing import (
        PeakAvoidanceTracker,
    )
    p = PeakAvoidanceTracker(MagicMock(), bill_cycle_day=23)
    p._maybe_reset(NOW)
    p._pa_cycle = 7.0
    assert p.set_bill_cycle_day(24, NOW) is True
    p._maybe_reset(NOW)
    assert p._pa_cycle == 7.0
    assert p._cycle_start_date == "2026-09-24"


def test_coordinator_setter_reseeds_from_db_for_new_window():
    c = _coord({KEY: 23})
    c._billing._check_cycle_reset(NOW)
    c._billing._cost_this_cycle = 99.0
    c._billing._cost_today = 1.0
    db = MagicMock()
    db.get_energy_daily_for_cycle = AsyncMock(return_value={
        "days": 26, "net_cost": 40.0, "import_kwh": 300.0, "export_kwh": 20.0,
    })
    db.count_outage_days_in_cycle = AsyncMock(return_value=0)
    c.hass.data = {"universal_room_automation": {"database": db}}
    captured = []
    c.hass.async_create_task = MagicMock(side_effect=lambda coro: captured.append(coro))
    with patch("homeassistant.util.dt.now", return_value=NOW):
        c.set_bill_cycle_day(24)
        assert len(captured) == 1
        # Not asyncio.run(): it clears the thread's current event loop, which
        # breaks later suite files that call asyncio.get_event_loop().
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(captured[0])
        finally:
            loop.close()
    db.get_energy_daily_for_cycle.assert_awaited_once_with("2026-09-24", "2026-10-20")
    assert c._billing._cost_this_cycle == 41.0


def test_coordinator_setter_unchanged_day_schedules_nothing():
    c = _coord({KEY: 24})
    c.hass.async_create_task = MagicMock()
    with patch("homeassistant.util.dt.now", return_value=NOW):
        c.set_bill_cycle_day(24)
    c.hass.async_create_task.assert_not_called()


def _pending_task():
    t = MagicMock()
    t.done.return_value = False
    return t


def test_second_change_cancels_superseded_reseed():
    """Review B B1: a superseded reseed is cancelled, not left to finish last."""
    c = _coord({KEY: 23})
    first, second = _pending_task(), _pending_task()
    tasks = iter([first, second])

    def _create(coro):
        coro.close()
        return next(tasks)

    c.hass.async_create_task = MagicMock(side_effect=_create)
    with patch("homeassistant.util.dt.now", return_value=NOW):
        c.set_bill_cycle_day(15)
        c.set_bill_cycle_day(10)
    first.cancel.assert_called_once()
    second.cancel.assert_not_called()
    assert c._bill_cycle_reseed_task is second


def test_teardown_cancels_running_reseed():
    """Review B B2: teardown cancels a reseed still in flight."""
    c = _coord({KEY: 23})
    running = _pending_task()
    c._bill_cycle_reseed_task = running
    c._cancel_utility_refresh()
    running.cancel.assert_called_once()
    assert c._bill_cycle_reseed_task is None
