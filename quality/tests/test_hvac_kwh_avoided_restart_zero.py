"""HVAC-KWH-AVOIDED-TOTAL-NOT-MONOTONIC-1 — AC-ramp impact sensors must not
publish the arrester's seeded zeros before its first DB refresh, and the
30-day "total" kWh sensor must be allowed to decrease.

Drives the REAL sensor classes' ``native_value`` over a stub arrester cache.
Expected values are hand-written literals.
"""
from __future__ import annotations

import types

import pytest

pytest.importorskip("homeassistant.helpers.storage")

from homeassistant.components.sensor import SensorStateClass  # noqa: E402

from custom_components.universal_room_automation import sensor as sen  # noqa: E402
from custom_components.universal_room_automation.const import DOMAIN  # noqa: E402


def _seeded_cache() -> dict:
    """What OverrideArrester.__init__ seeds (written by hand, not imported)."""
    return {
        "nudges_today": 0,
        "resets_today": 0,
        "kwh_avoided_today": 0.0,
        "kwh_avoided_cycle": 0.0,
        "kwh_avoided_total": 0.0,
        "false_positive_rate": None,
        "fp_sample_size": 0,
        "savings_today": 0.0,
        "savings_cycle": 0.0,
        "savings_lifetime": 0.0,
        "last_refresh_ts": None,
    }


def _refreshed_cache() -> dict:
    return {
        "nudges_today": 7,
        "resets_today": 2,
        "kwh_avoided_today": 3.25,
        "kwh_avoided_cycle": 41.5,
        "kwh_avoided_total": 382.871,
        "false_positive_rate": 12.5,
        "fp_sample_size": 40,
        "savings_today": 0.4567,
        "savings_cycle": 5.1234,
        "savings_lifetime": 48.9876,
        "cycle_start_source": "ec",
        "last_refresh_ts": "2026-10-26T01:05:00-05:00",
    }


def _make(cls, cache):
    ent = object.__new__(cls)
    arrester = types.SimpleNamespace(_impact_cache=cache)
    hvac = types.SimpleNamespace(_override_arrester=arrester)
    mgr = types.SimpleNamespace(coordinators={"hvac": hvac})
    ent.hass = types.SimpleNamespace(data={DOMAIN: {"coordinator_manager": mgr}})
    return ent


# (class, value expected after the first refresh)
_NON_RESTORE = [
    (sen.HVACACNudgesTodaySensor, 7),
    (sen.HVACACResetsTodaySensor, 2),
    (sen.HVACACKwhAvoidedTodaySensor, 3.25),
    (sen.HVACACKwhAvoidedBillingCycleSensor, 41.5),
    (sen.HVACACRampSavingsTodaySensor, 0.46),
    (sen.HVACACRampSavingsBillingCycleSensor, 5.12),
    (sen.HVACACRampSavingsLifetimeSensor, 48.99),
    (sen.HVACACFalsePositiveRateSensor, 12.5),
]


@pytest.mark.parametrize("cls,_after", _NON_RESTORE, ids=lambda x: getattr(x, "__name__", ""))
def test_before_first_refresh_reads_unknown_not_zero(cls, _after):
    ent = _make(cls, _seeded_cache())
    assert ent.native_value is None


@pytest.mark.parametrize("cls,_after", _NON_RESTORE, ids=lambda x: getattr(x, "__name__", ""))
def test_no_coordinator_reads_unknown_not_zero(cls, _after):
    ent = object.__new__(cls)
    ent.hass = types.SimpleNamespace(data={DOMAIN: {}})
    assert ent.native_value is None


@pytest.mark.parametrize("cls,after", _NON_RESTORE, ids=lambda x: getattr(x, "__name__", ""))
def test_after_refresh_reads_cache(cls, after):
    ent = _make(cls, _refreshed_cache())
    assert ent.native_value == after


def test_total_before_first_refresh_returns_restored_value():
    ent = _make(sen.HVACACKwhAvoidedTotalSensor, _seeded_cache())
    ent._restored_value = 402.521
    assert ent.native_value == 402.521


def test_total_before_first_refresh_without_restore_is_unknown():
    ent = _make(sen.HVACACKwhAvoidedTotalSensor, _seeded_cache())
    ent._restored_value = None
    assert ent.native_value is None


def test_total_after_refresh_reads_cache_over_restored():
    ent = _make(sen.HVACACKwhAvoidedTotalSensor, _refreshed_cache())
    ent._restored_value = 402.521
    assert ent.native_value == 382.871


def test_thirty_day_kwh_sensor_may_decrease():
    kwh = _make(sen.HVACACKwhAvoidedTotalSensor, _refreshed_cache())
    usd = _make(sen.HVACACRampSavingsLifetimeSensor, _refreshed_cache())
    assert kwh.state_class == SensorStateClass.TOTAL
    assert kwh.state_class != SensorStateClass.TOTAL_INCREASING
    assert usd.state_class == SensorStateClass.TOTAL


def test_thirty_day_names_and_unique_ids():
    hass = types.SimpleNamespace(data={})
    entry = types.SimpleNamespace(entry_id="x", data={}, options={})
    kwh = sen.HVACACKwhAvoidedTotalSensor(hass, entry)
    usd = sen.HVACACRampSavingsLifetimeSensor(hass, entry)
    assert kwh._attr_name == "80 · AC kWh Avoided (30 days)"
    assert kwh._attr_unique_id == f"{DOMAIN}_hvac_ac_kwh_avoided_total"
    assert usd._attr_name == "78 · AC Ramp Savings (30 days)"
    assert usd._attr_unique_id == f"{DOMAIN}_hvac_ac_ramp_savings_lifetime"
