"""D5a behavioural tests at ALL THREE lifetime-delta sites.

Drives the production methods on the real `EnergyCoordinator` class via
the shared `_energy_bootstrap`, with `object.__new__(EC)` + the minimal
attribute surface required by each method. For each site we assert the
baseline-validity guard fires and the downstream write / divergence
check is suppressed to NULL — the mechanism that produced the 4 bad
rows (2026-06-19, 08-20, 08-28, 08-30).

Sites:
- :2957 derived (`_maybe_reset_daily` primary path).
- :2992 legacy fallback (`_maybe_reset_daily` elif path).
- :3222 crosscheck (`_crosscheck_consumption`).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy as energy_mod,
)


EC = energy_mod.EnergyCoordinator


# ---------------------------------------------------------------------------
# Shared minimal EC fixture — only the attributes needed by the methods
# under test. We skip __init__ entirely with `object.__new__` so we don't
# have to satisfy the full coordinator wiring.
# ---------------------------------------------------------------------------
def _bare_ec() -> EC:
    """Return an EC with the minimum attribute surface for the 3 sites."""
    ec = object.__new__(EC)
    def _run(coro):
        # Drive the coroutine inline so the test can inspect side effects.
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(coro)
            loop.close()
        except Exception:
            pass

    ec.hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda _eid: None),
        data={"universal_room_automation": {"database": None}},
        async_create_task=_run,
    )
    # Entity ids (unused — lifetime getters are patched directly).
    ec._entity_lifetime_consumption = "sensor.e_cons"
    ec._entity_lifetime_production = "sensor.e_prod"
    ec._entity_lifetime_net_import = "sensor.e_ni"
    ec._entity_lifetime_net_export = "sensor.e_ne"
    ec._entity_lifetime_battery_charged = "sensor.e_bc"
    ec._entity_lifetime_battery_discharged = "sensor.e_bd"
    ec._entity_consumption_today = "sensor.e_today"
    # Snapshot state.
    ec._lifetime_consumption_snapshot = None
    ec._lifetime_production_snapshot = None
    ec._lifetime_net_import_snapshot = None
    ec._lifetime_net_export_snapshot = None
    ec._lifetime_battery_charged_snapshot = None
    ec._lifetime_battery_discharged_snapshot = None
    ec._last_reset_date = "2026-10-08"  # yesterday
    ec._tou_transition_count = 0
    ec._last_crosscheck_hour = -1
    # Collaborators (minimal — only members the methods touch).
    predictor = SimpleNamespace(
        record_actual_consumption=lambda *_a, **_k: None,
        _get_current_prediction=lambda: {
            "predicted_consumption_kwh": None,
            "predicted_consumption_source": None,
        },
        _prediction_temperature=None,
        _adjustment_factor=1.0,
    )
    ec._predictor = predictor
    ec._accuracy = SimpleNamespace(
        evaluate_accuracy=lambda *_a, **_k: None,
        get_adjustment_factor=lambda: 1.0,
    )
    ec._solar_forecast_error_baseline = SimpleNamespace(update=lambda _x: None)
    ec._daily_import_cost_baseline = SimpleNamespace(update=lambda _x: None)

    # Capture buffer for the (mocked) _save_daily_snapshot args.
    ec.saved_calls = []

    async def _fake_save(totals, consumption_kwh=None, **kw):
        ec.saved_calls.append({
            "totals": totals,
            "consumption_kwh": consumption_kwh,
            **kw,
        })

    ec._save_daily_snapshot = _fake_save
    ec._daily_db_cleanup = AsyncMock()
    # CostTracker-shaped stub returning a yesterday totals dict so the
    # DAO call path executes end-to-end.
    ec._billing = SimpleNamespace(
        get_yesterday_totals=lambda: {
            "date": "2026-10-08",
            "import_kwh": 10.0, "export_kwh": 1.0,
            "import_cost": 2.0, "export_credit": 0.1, "net_cost": 1.9,
            "billing_source": "power_integration",
        },
    )
    return ec


# ---------------------------------------------------------------------------
# Site :2957 — derived primary path
# ---------------------------------------------------------------------------
def test_d5a_derived_site_null_consumption_when_baseline_zero(monkeypatch):
    """Mock snapshot_production=0.0 (the 2026-08-28 shape). Expect
    `_save_daily_snapshot(consumption_kwh=None)` — NOT 15,584 kWh."""
    ec = _bare_ec()
    ec._lifetime_production_snapshot = 0.0          # the bug trigger
    ec._lifetime_net_import_snapshot = 10.0
    ec._lifetime_net_export_snapshot = 5.0
    ec._lifetime_battery_charged_snapshot = 1.0
    ec._lifetime_battery_discharged_snapshot = 1.0

    monkeypatch.setattr(ec, "_get_lifetime_consumption", lambda: 15.6)
    monkeypatch.setattr(ec, "_get_lifetime_production", lambda: 15.6)
    monkeypatch.setattr(ec, "_get_lifetime_net_import", lambda: 11.0)
    monkeypatch.setattr(ec, "_get_lifetime_net_export", lambda: 5.3)
    monkeypatch.setattr(ec, "_get_lifetime_battery_charged", lambda: 1.2)
    monkeypatch.setattr(ec, "_get_lifetime_battery_discharged", lambda: 1.5)
    # Fake today to force the date-changed branch.
    import homeassistant.util.dt as _dt
    monkeypatch.setattr(_dt, "now", lambda: datetime(2026, 10, 9, 0, 1))

    ec._maybe_reset_daily()
    # One snapshot call recorded; consumption_kwh is None (fail-closed).
    assert len(ec.saved_calls) == 1, ec.saved_calls
    assert ec.saved_calls[0]["consumption_kwh"] is None


# ---------------------------------------------------------------------------
# Site :2992 — legacy fallback path
# ---------------------------------------------------------------------------
def test_d5a_legacy_site_null_when_baseline_zero_current_nonzero(monkeypatch):
    """Mutation anchor on the legacy guard (:2992) — a strict `is not None`
    would ALLOW snap=0.0 → compute 15.6 MWh × 1000 = 15,600 kWh (the
    exact bug that produced the 2026-08-28 row). The guard rejects
    snap<=0 via `_is_valid_lifetime_baseline`."""
    ec = _bare_ec()
    ec._lifetime_consumption_snapshot = 0.0        # bug trigger
    monkeypatch.setattr(ec, "_get_lifetime_consumption", lambda: 15.6)
    monkeypatch.setattr(ec, "_get_lifetime_production", lambda: None)
    monkeypatch.setattr(ec, "_get_lifetime_net_import", lambda: None)
    monkeypatch.setattr(ec, "_get_lifetime_net_export", lambda: None)
    monkeypatch.setattr(ec, "_get_lifetime_battery_charged", lambda: None)
    monkeypatch.setattr(ec, "_get_lifetime_battery_discharged", lambda: None)
    import homeassistant.util.dt as _dt
    monkeypatch.setattr(_dt, "now", lambda: datetime(2026, 10, 9, 0, 1))
    ec._maybe_reset_daily()
    assert len(ec.saved_calls) == 1
    assert ec.saved_calls[0]["consumption_kwh"] is None, (
        "legacy guard FAILED: snap=0 current=15.6 produced non-None consumption"
    )


def test_d5a_helper_rejects_zero_and_non_monotonic():
    """Direct helper check — fails if the guard is loosened to is-not-None."""
    assert EC._is_valid_lifetime_baseline(0.0, 15.6) is False
    assert EC._is_valid_lifetime_baseline(None, 15.6) is False
    assert EC._is_valid_lifetime_baseline(5.0, 15.6) is True
    assert EC._is_valid_lifetime_baseline(5.0, 4.9) is False  # non-monotonic


def test_d5a_legacy_site_null_consumption_when_baseline_none(monkeypatch):
    """Only `_lifetime_consumption_snapshot` is None; the derived path
    is unreachable → legacy elif path. Guard forces NULL."""
    ec = _bare_ec()
    # All derived legs invalid (None) + legacy baseline None → both
    # branches fail → actual_kwh stays None.
    ec._lifetime_consumption_snapshot = None
    monkeypatch.setattr(ec, "_get_lifetime_consumption", lambda: 20.0)
    monkeypatch.setattr(ec, "_get_lifetime_production", lambda: None)
    monkeypatch.setattr(ec, "_get_lifetime_net_import", lambda: None)
    monkeypatch.setattr(ec, "_get_lifetime_net_export", lambda: None)
    monkeypatch.setattr(ec, "_get_lifetime_battery_charged", lambda: None)
    monkeypatch.setattr(ec, "_get_lifetime_battery_discharged", lambda: None)
    import homeassistant.util.dt as _dt
    monkeypatch.setattr(_dt, "now", lambda: datetime(2026, 10, 9, 0, 1))

    ec._maybe_reset_daily()
    assert len(ec.saved_calls) == 1
    assert ec.saved_calls[0]["consumption_kwh"] is None


# ---------------------------------------------------------------------------
# Site :3222 — crosscheck
# ---------------------------------------------------------------------------
def test_d5a_crosscheck_site_skips_divergence_log_when_baseline_zero(monkeypatch, caplog):
    """When snap=0 and current=15.6 MWh, the pre-D5a code logged a bogus
    15,586 kWh divergence vs Envoy's real today kWh. The guard must now
    return early — nothing logged, no warning."""
    ec = _bare_ec()
    ec._lifetime_consumption_snapshot = 0.0  # bug trigger
    monkeypatch.setattr(ec, "_get_lifetime_consumption", lambda: 15.6)
    # Envoy today sensor present and fresh.
    state = SimpleNamespace(state="42.0", attributes={})
    ec.hass = SimpleNamespace(states=SimpleNamespace(
        get=lambda eid: state if eid == "sensor.e_today" else None
    ))
    import homeassistant.util.dt as _dt
    monkeypatch.setattr(_dt, "now", lambda: datetime(2026, 10, 9, 14, 0))

    caplog.clear()
    import logging as _lg
    with caplog.at_level(_lg.WARNING, logger="custom_components.universal_room_automation.domain_coordinators.energy"):
        ec._crosscheck_consumption()
    assert not any("divergence" in rec.message.lower() for rec in caplog.records), (
        "D5a guard FAILED: a divergence warning was emitted against a zero baseline"
    )
