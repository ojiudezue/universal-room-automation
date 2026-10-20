"""EC-BILL-UTILITY-DIVERGENCE-FROM-STATS-1 D3 — predicted-bill sensor attrs.

Drives the REAL ``EnergyPredictedBillSensor.extra_state_attributes`` over the
REAL ``EnergyCoordinator.utility_meter_divergence`` producer (bound to a
plain stub). Expected dicts are hand-written literals.
"""
from __future__ import annotations

import types

import pytest

pytest.importorskip("homeassistant.helpers.storage")

from custom_components.universal_room_automation import sensor as sen  # noqa: E402
from custom_components.universal_room_automation.const import DOMAIN  # noqa: E402
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy as em,
)


class _St:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class _FakeEnergy:
    def __init__(self, imp_id="", cache=None):
        self.hass = types.SimpleNamespace(
            states=types.SimpleNamespace(
                get=lambda eid: _St("500", {"last_reset": "2026-10-01T00:00:00+00:00"}),
            ),
        )
        self._utility_meter_entity = "sensor.smarthub_monthly"
        self._utility_import_stat_id = imp_id
        self._utility_export_stat_id = ""
        self._utility_stats_cache = cache
        self._utility_stats_refreshed_at = "2026-10-19T09:00:00-05:00" if cache else None
        self._utility_stats_error = None
        self._billing = types.SimpleNamespace(
            import_kwh_cycle=400.0,
            get_status=lambda: {"cycle_start_date": "2026-10-23"},
        )
        self.billing_status = {
            "prediction_label": "Early",
            "days_in_cycle": 5,
            "cycle_start_date": "2026-10-23",
        }
        self.arbitrage_status = {}
        self.peak_avoidance_status = {}
        self.predicted_bill = 150.0

    def _utility_stat_ids(self):
        return em.EnergyCoordinator._utility_stat_ids(self)

    def _utility_statistics_divergence(self):
        return em.EnergyCoordinator._utility_statistics_divergence(self)

    @property
    def utility_meter_divergence(self):
        return em.EnergyCoordinator.utility_meter_divergence.fget(self)


def _attrs(energy):
    s = sen.EnergyPredictedBillSensor.__new__(sen.EnergyPredictedBillSensor)
    s.hass = types.SimpleNamespace(
        data={DOMAIN: {"coordinator_manager": types.SimpleNamespace(
            coordinators={"energy": energy})}},
    )
    return s.extra_state_attributes


def test_predicted_bill_attrs_unchanged_when_ids_blank():
    attrs = _attrs(_FakeEnergy(imp_id=""))
    assert attrs == {
        "status": "Early",
        "days_in_cycle": 5,
        "cycle_start_date": "2026-10-23",
        "prediction_source": "envoy",
        "utility_kwh": 500.0,
        "envoy_kwh": 400.0,
        "utility_divergence_pct": 20.0,
        "arbitrage_savings_this_cycle": 0.0,
        "arbitrage_savings_projected_cycle_total": 0.0,
        "peak_avoidance_savings_this_cycle": 0.0,
        "total_savings_this_cycle": 0.0,
        "predicted_bill_without_solar_battery": 150.0,
    }


def test_predicted_bill_attrs_statistics_keys_published():
    cur = {
        "window_start": "2026-09-23", "window_end": "2026-10-18",
        "utility_days": 25, "ec_days": 24,
        "utility_import_kwh": 600.0, "utility_net_cost": 55.7,
        "ec_import_kwh": 480.0, "ec_net_cost": 48.0,
        "divergence_kwh": 120.0, "divergence_kwh_pct": 20.0,
        "divergence_cost": 7.7, "divergence_cost_pct": 13.8,
        "ec_underpriced_days": 3,
    }
    last = {"utility_net_cost": 295.13, "utility_bill_estimate": 327.63}
    cache = {"current": cur, "last_cycle": last, "newest_hour": "x",
             "data_age_h": 28.0, "stale": False}
    attrs = _attrs(_FakeEnergy(imp_id="smarthub:a", cache=cache))
    # Legacy keys, like-for-like values from statistics (not the entity's 500).
    assert attrs["prediction_source"] == "envoy"
    assert attrs["utility_kwh"] == 600.0
    assert attrs["envoy_kwh"] == 480.0
    assert attrs["utility_divergence_pct"] == 20.0
    assert attrs["utility_source"] == "statistics"
    assert attrs["utility_cost"] == 55.7
    assert attrs["ec_cost"] == 48.0
    assert attrs["utility_divergence_cost"] == 7.7
    assert attrs["utility_divergence_cost_pct"] == 13.8
    assert attrs["utility_window"] == "2026-09-23..2026-10-18"
    assert attrs["utility_days"] == 25
    assert attrs["ec_days"] == 24
    assert attrs["ec_underpriced_days"] == 3
    assert attrs["utility_data_age_h"] == 28.0
    assert attrs["utility_stale"] is False
    assert attrs["utility_last_cycle"] == last
