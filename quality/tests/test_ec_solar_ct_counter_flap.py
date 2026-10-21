"""EC-SOLAR-LIFETIME-COUNTER-FLAP-1 (v5.103.82) behavioural tests.

The inverter-sum ``lifetime_energy_production`` counter flaps to ~0.046 MWh;
the EC now derives the monotonic production-CT counter, records snapshot
provenance across the swap, and rejects a flapped snapshot via a high-water
mark. All tests drive the real ``EnergyCoordinator`` methods.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_const as ec_const,
)
from test_ec_billing_d5a_baseline_guard_sites import _bare_ec  # noqa: E402

CT = "sensor.envoy_482543015950_production_ct_energy_delivered"


def _ec(monkeypatch, *, prod_snap, prod_now, hwm=None, last_reset="2026-10-08"):
    ec = _bare_ec()
    ec._lifetime_production_hwm = hwm
    ec._last_reset_date = last_reset
    ec._lifetime_production_snapshot = prod_snap
    ec._lifetime_net_import_snapshot = 10.0
    ec._lifetime_net_export_snapshot = 5.0
    ec._lifetime_battery_charged_snapshot = 1.0
    ec._lifetime_battery_discharged_snapshot = 1.0
    monkeypatch.setattr(ec, "_get_lifetime_consumption", lambda: 15.6)
    monkeypatch.setattr(ec, "_get_lifetime_production", lambda: prod_now)
    monkeypatch.setattr(ec, "_get_lifetime_net_import", lambda: 10.02)
    monkeypatch.setattr(ec, "_get_lifetime_net_export", lambda: 5.01)
    monkeypatch.setattr(ec, "_get_lifetime_battery_charged", lambda: 1.005)
    monkeypatch.setattr(ec, "_get_lifetime_battery_discharged", lambda: 1.008)
    ec._save_midnight_snapshot = AsyncMock()
    import homeassistant.util.dt as _dt
    monkeypatch.setattr(_dt, "now", lambda: datetime(2026, 10, 9, 0, 1))
    return ec


def _solar(ec):
    assert len(ec.saved_calls) == 1
    return ec.saved_calls[0]["solar_production_kwh"]


# --- D1: derive default --------------------------------------------------
def test_derive_default_is_production_ct_counter():
    d = ec_const.derive_envoy_config("482543015950")
    assert d[ec_const.CONF_ENERGY_LIFETIME_PRODUCTION_ENTITY] == CT


# --- normal day ----------------------------------------------------------
def test_normal_day_solar_delta(monkeypatch):
    # 20.000 -> 20.050 MWh = 50 kWh (hand-computed oracle).
    ec = _ec(monkeypatch, prod_snap=20.0, prod_now=20.05, hwm=20.04)
    ec._maybe_reset_daily()
    assert _solar(ec) == pytest.approx(50.0)
    assert ec._lifetime_production_snapshot == 20.05


# --- flap rejection ------------------------------------------------------
def test_both_ends_flapped_gives_null_not_zero(monkeypatch):
    """Snapshot AND current caught at 0.046 → delta 0.0 used to be accepted."""
    ec = _ec(monkeypatch, prod_snap=0.046, prod_now=0.046, hwm=20.6)
    ec._maybe_reset_daily()
    assert _solar(ec) is None


def test_snapshot_flapped_current_healthy_gives_null(monkeypatch):
    """snap 0.046, current 20.65 passes monotonic check → ~20604 kWh garbage."""
    ec = _ec(monkeypatch, prod_snap=0.046, prod_now=20.65, hwm=20.6)
    ec._maybe_reset_daily()
    assert _solar(ec) is None


def test_hwm_learned_from_same_day_tick(monkeypatch):
    """Drive the HWM-update site: a healthy same-day tick sets the mark,
    then the midnight tick with a flapped pair must be rejected."""
    ec = _ec(monkeypatch, prod_snap=0.046, prod_now=20.6, hwm=None,
             last_reset="2026-10-09")
    ec._maybe_reset_daily()          # same day: seeds hwm only
    assert ec._lifetime_production_hwm == 20.6
    assert ec.saved_calls == []
    ec._last_reset_date = "2026-10-08"
    monkeypatch.setattr(ec, "_get_lifetime_production", lambda: 0.046)
    ec._maybe_reset_daily()
    assert _solar(ec) is None
    assert ec._lifetime_production_hwm == 20.6   # flap did not drag it down


def test_drop_boundary_literal(monkeypatch):
    # hwm 20.0, fraction 0.5 → floor 10.0 (literals, not the constant).
    ec = _ec(monkeypatch, prod_snap=10.0, prod_now=10.01, hwm=20.0)
    ec._maybe_reset_daily()
    assert _solar(ec) == pytest.approx(10.0)
    ec2 = _ec(monkeypatch, prod_snap=9.99, prod_now=10.0, hwm=20.0)
    ec2._maybe_reset_daily()
    assert _solar(ec2) is None


# --- provenance: restore + save -----------------------------------------
def _restore(monkeypatch, stored_eid, snap=20.0):
    ec = _bare_ec()
    ec._entity_lifetime_production = CT
    ec._lifetime_production_hwm = None
    ec._billing = MagicMock()
    ec._peak_avoidance = MagicMock()

    async def _noop():
        return None

    ec._refresh_outage_days_this_cycle = _noop
    db = MagicMock()
    db.restore_midnight_snapshot = AsyncMock(return_value={
        "snapshot_date": "2026-10-09",
        "lifetime_consumption": 15.0, "lifetime_production": snap,
        "lifetime_net_import": 10.0, "lifetime_net_export": 5.0,
        "lifetime_battery_charged": 1.0, "lifetime_battery_discharged": 1.0,
    })

    async def _kv(key):
        if key == ec_const.ENERGY_STATE_KEY_PRODUCTION_SNAPSHOT_ENTITY:
            return stored_eid
        return None

    db.restore_energy_state = _kv
    ec.hass.data = {"universal_room_automation": {"database": db}}
    ec.hass.async_create_background_task = lambda coro, _n: coro.close()
    import homeassistant.util.dt as _dt
    monkeypatch.setattr(_dt, "now", lambda: datetime(2026, 10, 9, 9, 0))
    asyncio.run(ec._restore_midnight_snapshot())
    return ec


def test_restore_swapped_entity_invalidates_snapshot(monkeypatch):
    ec = _restore(monkeypatch, "sensor.envoy_482543015950_lifetime_energy_production")
    assert ec._lifetime_production_snapshot == 0.0
    assert ec._production_snapshot_poisoned is True
    assert ec._lifetime_net_import_snapshot == 10.0   # other legs untouched
    ec._billing.restore_daily.assert_called_once()    # rest of restore ran


def test_restore_absent_provenance_invalidates_snapshot(monkeypatch):
    ec = _restore(monkeypatch, None)
    assert ec._lifetime_production_snapshot == 0.0


def test_restore_matching_provenance_keeps_snapshot(monkeypatch):
    ec = _restore(monkeypatch, CT)
    assert ec._lifetime_production_snapshot == 20.0


def test_swapped_restore_then_midnight_writes_null_solar(monkeypatch):
    ec = _restore(monkeypatch, "sensor.old")
    ec._billing = _bare_ec()._billing   # real-shaped yesterday totals
    # Same-day tick must NOT re-seed the poisoned 0.0 baseline.
    monkeypatch.setattr(ec, "_get_lifetime_consumption", lambda: 15.6)
    monkeypatch.setattr(ec, "_get_lifetime_production", lambda: 20.6)
    monkeypatch.setattr(ec, "_get_lifetime_net_import", lambda: 10.02)
    monkeypatch.setattr(ec, "_get_lifetime_net_export", lambda: 5.01)
    monkeypatch.setattr(ec, "_get_lifetime_battery_charged", lambda: 1.005)
    monkeypatch.setattr(ec, "_get_lifetime_battery_discharged", lambda: 1.008)
    ec._save_midnight_snapshot = AsyncMock()
    ec._maybe_reset_daily()
    assert ec._lifetime_production_snapshot == 0.0
    import homeassistant.util.dt as _dt
    monkeypatch.setattr(_dt, "now", lambda: datetime(2026, 10, 10, 0, 1))
    monkeypatch.setattr(ec, "_get_lifetime_production", lambda: 20.65)
    ec._maybe_reset_daily()
    assert _solar(ec) is None
    assert ec._lifetime_production_snapshot == 20.65   # clean next-day baseline


def test_save_midnight_snapshot_records_provenance(monkeypatch):
    ec = _bare_ec()
    ec._entity_lifetime_production = CT
    ec._billing = MagicMock()
    ec._billing.get_status.return_value = {}
    ec._peak_avoidance = MagicMock()
    ec._peak_avoidance.snapshot_state.return_value = {}
    db = MagicMock()
    db.save_midnight_snapshot = AsyncMock()
    db.save_energy_state = AsyncMock()
    ec.hass.data = {"universal_room_automation": {"database": db}}
    asyncio.run(ec._save_midnight_snapshot())
    db.save_energy_state.assert_any_await(
        ec_const.ENERGY_STATE_KEY_PRODUCTION_SNAPSHOT_ENTITY, CT
    )


# --- Review A MEDIUM: production-rejected day must not learn via legacy ---
def _spy_learners(ec):
    ec._predictor = MagicMock()
    ec._predictor._get_current_prediction.return_value = {
        "predicted_consumption_kwh": 60.0,
        "predicted_consumption_source": "model",
    }
    ec._predictor._prediction_temperature = None
    ec._predictor._adjustment_factor = 1.0
    ec._accuracy = MagicMock()
    ec._accuracy.evaluate_accuracy.return_value = None
    ec._accuracy.get_adjustment_factor.return_value = 1.23
    ec._lifetime_consumption_snapshot = 15.0   # VALID legacy baseline (15.0 -> 15.6)
    return ec


def _assert_no_learning(ec):
    assert ec.saved_calls[0]["consumption_kwh"] is None
    ec._predictor.record_actual_consumption.assert_not_called()
    ec._accuracy.evaluate_accuracy.assert_not_called()
    assert ec._predictor._adjustment_factor == 1.0


def test_flapped_production_day_no_legacy_consumption(monkeypatch):
    ec = _spy_learners(_ec(monkeypatch, prod_snap=0.046, prod_now=0.046, hwm=20.6))
    ec._maybe_reset_daily()
    _assert_no_learning(ec)


def test_poisoned_production_day_no_legacy_consumption(monkeypatch):
    # The restore poison shape: snap 0.0 + flag. With any production reading
    # the flap guard (snap 0.0 < floor) also rejects, so the flag is the only
    # rejector when the production counter is UNAVAILABLE at midnight
    # (current None, no mark) — the case pinned here.
    ec = _spy_learners(_ec(monkeypatch, prod_snap=0.0, prod_now=None, hwm=None))
    ec._production_snapshot_poisoned = True
    ec._maybe_reset_daily()
    _assert_no_learning(ec)
    assert ec._production_snapshot_poisoned is False   # day-scoped, cleared


def test_legacy_fallback_kept_for_other_leg_failure(monkeypatch):
    """Original case: a NON-production leg invalid -> legacy delta still learns."""
    ec = _spy_learners(_ec(monkeypatch, prod_snap=20.0, prod_now=20.05, hwm=20.04))
    ec._lifetime_net_import_snapshot = None
    ec._maybe_reset_daily()
    assert ec.saved_calls[0]["consumption_kwh"] == pytest.approx(600.0)  # (15.6-15.0)*1000
    ec._predictor.record_actual_consumption.assert_called_once()
    ec._accuracy.evaluate_accuracy.assert_called_once()
    assert ec._predictor._adjustment_factor == 1.23
