"""Tests for v5.20.0 D2 cloud-reliance hardening.

Covers the READ-side telemetry observability + divergence detection added
to `BatteryStrategy` (energy_battery.py). Reuses the test-harness bootstrap
from `test_energy_battery.py` (import order matters — the module builds
the mock `custom_components.universal_room_automation` package tree).

D2 owns the SOC read-side witness; write-verify (v5.19.0) owns the write
side. These tests DO NOT touch write-verify surfaces.
"""

# Bootstrap the same mock HA / package tree the sibling test uses.
import test_energy_battery  # noqa: F401  (side-effect: builds sys.modules)

from datetime import datetime, timedelta

import pytest

from conftest import MockHass, MockState  # noqa: E402
from custom_components.universal_room_automation.domain_coordinators import (
    energy_const,  # noqa: E402
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
    BatteryStrategy,  # noqa: E402
)


CLOUD_SOC_ENTITY = energy_const.DEFAULT_CLOUD_BATTERY_SOC_FALLBACK_ENTITY
CLOUD_RESERVE_ENTITY = energy_const.DEFAULT_CLOUD_RESERVE_ORACLE_ENTITY
CLOUD_CFG_ENTITY = energy_const.DEFAULT_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY
CLOUD_STORAGE_MODE_ENTITY = energy_const.DEFAULT_CLOUD_STORAGE_MODE_ORACLE_ENTITY

PRIMARY_SOC_ENTITY = "sensor.test_envoy_battery"


def _make_strategy() -> BatteryStrategy:
    """Return a minimally-configured BatteryStrategy wired for D2 tests.

    Only the entity keys D2 reads are wired: primary SOC, cloud SOC
    fallback, and the three cloud oracle write-target entities.
    """
    hass = MockHass()
    # The three cloud oracle write entities (D2 cloud-lag reads these).
    hass.set_state(CLOUD_RESERVE_ENTITY, "20")
    hass.set_state(CLOUD_CFG_ENTITY, "off")
    hass.set_state(CLOUD_STORAGE_MODE_ENTITY, "Self-Consumption")
    strat = BatteryStrategy(
        hass,
        reserve_soc=20,
        arbitrage_enabled=False,
        entity_config={
            "battery_soc": PRIMARY_SOC_ENTITY,
            "battery_soc_cloud": CLOUD_SOC_ENTITY,
            # D2 cloud-lag reads the cloud oracle keys directly.
            "cloud_reserve_oracle": CLOUD_RESERVE_ENTITY,
            "cloud_charge_from_grid_oracle": CLOUD_CFG_ENTITY,
            "cloud_storage_mode_oracle": CLOUD_STORAGE_MODE_ENTITY,
        },
    )
    return strat


def _set_state_at(hass: MockHass, entity_id: str, state: str,
                  age_s: float = 0.0, unit: str = "%") -> None:
    """Set a state whose `last_updated` is age_s in the past.

    Cross-test pollution note: other test modules in the suite may
    monkeypatch `homeassistant.util.dt.utcnow` to return a tz-aware
    value, and mixing that with a naive `datetime.utcnow()` produces
    a TypeError inside the age subtraction. We compute the timestamp
    off whatever `dt_util.utcnow` is CURRENTLY bound to at call-time
    so the arithmetic stays in the same tz-domain as the production
    code path reads it.
    """
    from homeassistant.util import dt as dt_util
    when = dt_util.utcnow() - timedelta(seconds=age_s)
    mstate = MockState(
        entity_id, state, attributes={"unit_of_measurement": unit},
        last_changed=when,
    )
    mstate.last_updated = when
    hass._states[entity_id] = mstate


# ---------------------------------------------------------------------------
# D2.2 — tier observability
# ---------------------------------------------------------------------------

def test_soc_resolution_populated_primary_envoy_tier():
    """Primary Envoy present → tier=primary_envoy, cloud snapshot recorded."""
    strat = _make_strategy()
    _set_state_at(strat.hass, PRIMARY_SOC_ENTITY, "62.0")
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "61.0")
    # Drive the resolver so `_soc_source_last` stamps.
    _ = strat.battery_soc
    strat._evaluate_soc_resolution(strat.battery_soc)
    attrs = strat._soc_resolution_attrs()
    assert attrs["tier"] == "primary_envoy"
    assert attrs["primary_envoy_soc"] == pytest.approx(62.0)
    assert attrs["cloud_soc"] == pytest.approx(61.0)
    assert attrs["tier_disagreement_pp"] == pytest.approx(1.0)


def test_soc_resolution_tier_disagreement_pp_computed_over_all_tiers():
    """With primary=60, LKG=58, cloud=87 → disagreement is 87-58 = 29."""
    strat = _make_strategy()
    _set_state_at(strat.hass, PRIMARY_SOC_ENTITY, "60.0")
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "87.0")
    # Prime the LKG at 58 by driving the resolver once with primary=58.
    _set_state_at(strat.hass, PRIMARY_SOC_ENTITY, "58.0")
    _ = strat.battery_soc
    # Now flip primary to 60 for this tick.
    _set_state_at(strat.hass, PRIMARY_SOC_ENTITY, "60.0")
    _ = strat.battery_soc
    strat._evaluate_soc_resolution(strat.battery_soc)
    attrs = strat._soc_resolution_attrs()
    assert attrs["primary_envoy_soc"] == pytest.approx(60.0)
    assert attrs["cloud_soc"] == pytest.approx(87.0)
    # LKG got stamped at 60 on the last drive; disagreement = 87-60 = 27.
    assert attrs["tier_disagreement_pp"] == pytest.approx(27.0)


# ---------------------------------------------------------------------------
# D2.1 — SOC divergence detector (with dwell + hysteresis + latch)
# ---------------------------------------------------------------------------

def test_soc_divergence_no_alert_before_dwell():
    """Divergence held < dwell → no active alert.

    Two back-to-back calls with no time elapsed between them. Without a
    dwell gate, the second call would flip `_d2_soc_div_active` True.
    With the dwell gate in place, elapsed is ~0 << 5 min → stays False.
    This is the mutation anchor for the dwell branch.
    """
    strat = _make_strategy()
    _set_state_at(strat.hass, PRIMARY_SOC_ENTITY, "60.0")
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "87.0")
    strat._evaluate_soc_divergence(60.0, 87.0)  # stamp first_at, return
    assert strat._d2_soc_div_first_at is not None
    strat._evaluate_soc_divergence(60.0, 87.0)  # elapsed ~0, dwell not met
    assert strat._d2_soc_div_active is False


def test_soc_divergence_fires_after_dwell_and_latches():
    """Divergence 27 pp held past 5-min dwell → active alert set + NM latch."""
    from homeassistant.util import dt as dt_util
    strat = _make_strategy()
    strat._evaluate_soc_divergence(60.0, 87.0)
    assert strat._d2_soc_div_first_at is not None
    # Rewind dwell start-time past the threshold.
    strat._d2_soc_div_first_at = dt_util.utcnow() - timedelta(minutes=6)
    strat._evaluate_soc_divergence(60.0, 87.0)
    assert strat._d2_soc_div_active is True
    assert strat._d2_soc_div_last_delta == pytest.approx(27.0)
    # NM latched today.
    assert strat._d2_soc_div_nm_date == (
        dt_util.utcnow().date().isoformat()
    )


def test_soc_divergence_clears_with_hysteresis():
    """After firing, delta must drop below (threshold - hysteresis) for
    another dwell to clear. Hysteresis-band values (threshold - hyst <=
    delta <= threshold) must NEITHER fire NOR clear — they zero the
    dwell (neither branch qualifies). Mutation anchor: if hysteresis is
    removed (`clear_below == threshold`), delta=9 would incorrectly
    clear the alert.
    """
    from homeassistant.util import dt as dt_util
    strat = _make_strategy()
    strat._d2_soc_div_active = True
    strat._d2_soc_div_first_at = None
    # threshold=10, hysteresis=2 → clear_below=8. delta=9 is INSIDE the
    # hysteresis band — must not clear.
    strat._evaluate_soc_divergence(60.0, 69.0)
    # dwell start should NOT have been armed (neither branch matched).
    assert strat._d2_soc_div_first_at is None
    # Even after simulating dwell has passed, active must remain True.
    strat._d2_soc_div_first_at = dt_util.utcnow() - timedelta(minutes=6)
    strat._evaluate_soc_divergence(60.0, 69.0)
    assert strat._d2_soc_div_active is True
    # Now drop delta below clear_below → clears.
    strat._d2_soc_div_first_at = None
    strat._evaluate_soc_divergence(60.0, 63.0)
    assert strat._d2_soc_div_first_at is not None
    strat._d2_soc_div_first_at = dt_util.utcnow() - timedelta(minutes=6)
    strat._evaluate_soc_divergence(60.0, 63.0)
    assert strat._d2_soc_div_active is False


def test_soc_divergence_abstains_on_stale_or_unavailable():
    """When either side is None the detector resets its dwell and no-ops."""
    strat = _make_strategy()
    # Prime an active dwell.
    strat._evaluate_soc_divergence(60.0, 87.0)
    assert strat._d2_soc_div_first_at is not None
    strat._evaluate_soc_divergence(None, 87.0)
    assert strat._d2_soc_div_first_at is None
    assert strat._d2_soc_div_last_delta is None


def test_soc_divergence_disabled_when_threshold_zero(monkeypatch):
    """Kill-switch: threshold=0 → no state ever changes."""
    import sys as _sys
    _live_ec = _sys.modules[
        "custom_components.universal_room_automation.domain_coordinators.energy_const"
    ]
    monkeypatch.setattr(_live_ec, "CONF_SOC_DIVERGENCE_THRESHOLD_PP", 0)
    strat = _make_strategy()
    strat._evaluate_soc_divergence(60.0, 87.0)
    assert strat._d2_soc_div_first_at is None
    assert strat._d2_soc_div_active is False


# ---------------------------------------------------------------------------
# D2.3 — cloud settings-lag
# ---------------------------------------------------------------------------

def test_cloud_settings_lag_reports_max_age():
    """`_read_cloud_settings_max_age_s` returns max across the 3 entities."""
    strat = _make_strategy()
    _set_state_at(strat.hass, CLOUD_RESERVE_ENTITY, "20", age_s=100)
    _set_state_at(strat.hass, CLOUD_CFG_ENTITY, "off", age_s=1900)
    _set_state_at(strat.hass, CLOUD_STORAGE_MODE_ENTITY,
                  "Self-Consumption", age_s=300)
    age = strat._read_cloud_settings_max_age_s()
    assert age is not None and age >= 1900


def test_cloud_settings_lag_fires_after_dwell():
    """max_age > 1800 for > 5 min → active alert + NM latched."""
    from homeassistant.util import dt as dt_util
    strat = _make_strategy()
    _set_state_at(strat.hass, CLOUD_RESERVE_ENTITY, "20", age_s=100)
    _set_state_at(strat.hass, CLOUD_CFG_ENTITY, "off", age_s=1900)
    _set_state_at(strat.hass, CLOUD_STORAGE_MODE_ENTITY,
                  "Self-Consumption", age_s=300)
    strat._evaluate_cloud_settings_lag()
    assert strat._d2_cloud_lag_first_at is not None
    assert strat._d2_cloud_lag_active is False
    strat._d2_cloud_lag_first_at = dt_util.utcnow() - timedelta(minutes=6)
    strat._evaluate_cloud_settings_lag()
    assert strat._d2_cloud_lag_active is True
    assert strat._d2_cloud_lag_nm_date == (
        dt_util.utcnow().date().isoformat()
    )


def test_cloud_settings_lag_healthy_no_alert():
    """max_age well below threshold → no active alert, no dwell."""
    strat = _make_strategy()
    _set_state_at(strat.hass, CLOUD_RESERVE_ENTITY, "20", age_s=60)
    _set_state_at(strat.hass, CLOUD_CFG_ENTITY, "off", age_s=90)
    _set_state_at(strat.hass, CLOUD_STORAGE_MODE_ENTITY,
                  "Self-Consumption", age_s=120)
    strat._evaluate_cloud_settings_lag()
    assert strat._d2_cloud_lag_active is False
    assert strat._d2_cloud_lag_last_age_s is not None
    assert strat._d2_cloud_lag_last_age_s < 200


def test_cloud_settings_lag_killswitch(monkeypatch):
    """CONF_CLOUD_LAG_ALERT_S=0 → attr populated, but no dwell/no NM."""
    import sys as _sys
    _live_ec = _sys.modules[
        "custom_components.universal_room_automation.domain_coordinators.energy_const"
    ]
    monkeypatch.setattr(_live_ec, "CONF_CLOUD_LAG_ALERT_S", 0)
    strat = _make_strategy()
    _set_state_at(strat.hass, CLOUD_RESERVE_ENTITY, "20", age_s=100)
    _set_state_at(strat.hass, CLOUD_CFG_ENTITY, "off", age_s=99999)
    _set_state_at(strat.hass, CLOUD_STORAGE_MODE_ENTITY,
                  "Self-Consumption", age_s=300)
    strat._evaluate_cloud_settings_lag()
    assert strat._d2_cloud_lag_first_at is None
    assert strat._d2_cloud_lag_active is False
    # attr still populated for observability
    assert strat._d2_cloud_lag_last_age_s is not None
    assert strat._d2_cloud_lag_last_age_s >= 99999


# ---------------------------------------------------------------------------
# Attribute-surface smoke: `soc_resolution` block shape.
# ---------------------------------------------------------------------------

def test_soc_resolution_attr_block_keys_stable():
    strat = _make_strategy()
    attrs = strat._soc_resolution_attrs()
    expected = {
        "tier", "tier_disagreement_pp",
        "primary_envoy_soc", "lkg_soc", "lkg_age_s",
        "cloud_soc", "cloud_soc_age_s",
        "divergence_pp", "divergence_active",
        "cloud_settings_lag_s", "cloud_settings_lag_active",
    }
    assert set(attrs.keys()) == expected
