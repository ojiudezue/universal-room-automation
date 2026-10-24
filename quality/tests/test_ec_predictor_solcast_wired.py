"""EC-PREDICTOR-SOLCAST-UNWIRED-1 — the configured Solcast today/remaining
entity ids reach DailyEnergyPredictor through the REAL EnergyCoordinator
constructor (DEFAULT_SOLCAST_* are None, so a missing kwarg = no Solcast).

Scoped real-package fixture copied from test_ec_bill_cycle_day_wired.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

DOMAIN = "universal_room_automation"
# Hardcoded literal keys (Definition of done #6): independent of the CONF_* constants.
TODAY_KEY = "energy_solcast_today_entity"
REMAINING_KEY = "energy_solcast_remaining_entity"
TODAY_ID = "sensor.solcast_pv_forecast_forecast_today"
REMAINING_ID = "sensor.solcast_pv_forecast_forecast_remaining_today"


def _is_set_aside(name: str, mod) -> bool:
    if name == "custom_components" or name.startswith("custom_components."):
        return True
    if name == "homeassistant" or name.startswith("homeassistant."):
        import types
        return not isinstance(mod, types.ModuleType) or mod.__spec__ is None
    return False


@pytest.fixture(autouse=True, scope="module")
def _real_ura_package():
    import importlib

    from _d7_isolation import real_package_scope

    with real_package_scope(_is_set_aside):
        ec_const = importlib.import_module(
            "custom_components.universal_room_automation.domain_coordinators.energy_const",
        )
        # Guard the literal keys against drift from the production constants.
        assert ec_const.CONF_ENERGY_SOLCAST_TODAY_ENTITY == TODAY_KEY
        assert ec_const.CONF_ENERGY_SOLCAST_REMAINING_ENTITY == REMAINING_KEY
        yield


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


def test_predictor_gets_configured_solcast_today():
    c = _coord({TODAY_KEY: TODAY_ID, REMAINING_KEY: REMAINING_ID})
    assert c._predictor._solcast_today_entity == TODAY_ID


def test_predictor_gets_configured_solcast_remaining():
    c = _coord({TODAY_KEY: TODAY_ID, REMAINING_KEY: REMAINING_ID})
    assert c._predictor._solcast_remaining_entity == REMAINING_ID


def test_predictor_matches_battery_strategy_resolution():
    c = _coord({TODAY_KEY: TODAY_ID, REMAINING_KEY: REMAINING_ID})
    assert c._battery._get_entity("solcast_today") == c._predictor._solcast_today_entity
    assert c._battery._get_entity("solcast_remaining") == c._predictor._solcast_remaining_entity


def test_absent_keys_stay_none_without_crash():
    c = _coord({})
    assert c._predictor._solcast_today_entity is None
    assert c._predictor._solcast_remaining_entity is None
