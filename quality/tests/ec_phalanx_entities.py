"""This house's (Phalanx) energy role entities, for tests that model it.

EC-HOUSE-ENTITY-DEFAULTS-1 removed the house-specific entity ids from the
energy modules' DEFAULT_* constants (they are None / [] / {} now). Tests that
model THIS house — the post-migration state, where the one-shot pin has put
these ids into the CM options — opt in explicitly by importing from here.
Tests that exercise the second-install path simply don't, and see the real
None defaults.

Single source of truth: ``energy_const.EC_ROLE_KEY_DEFAULTS`` (the pin
migration's table). This module loads ``energy_const.py`` under a PRIVATE
module name (never registered in ``sys.modules``), so it cannot disturb any
sibling test's module bootstrap.
"""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

_EC_CONST_PATH = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "universal_room_automation"
    / "domain_coordinators"
    / "energy_const.py"
)
_spec = importlib.util.spec_from_file_location(
    "_ec_phalanx_private_energy_const", _EC_CONST_PATH,
)
_c = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_c)

ROLE_DEFAULTS: dict = copy.deepcopy(_c.EC_ROLE_KEY_DEFAULTS)

# Former module-level DEFAULT_* values, by role.
PHALANX_STORAGE_MODE_ENTITY: str = ROLE_DEFAULTS[_c.CONF_ENERGY_STORAGE_MODE_ENTITY]
PHALANX_RESERVE_SOC_ENTITY: str = ROLE_DEFAULTS[_c.CONF_ENERGY_RESERVE_SOC_ENTITY]
PHALANX_GRID_ENABLED_ENTITY: str = ROLE_DEFAULTS[_c.CONF_ENERGY_GRID_ENABLED_ENTITY]
PHALANX_CHARGE_FROM_GRID_ENTITY: str = ROLE_DEFAULTS[
    _c.CONF_ENERGY_CHARGE_FROM_GRID_ENTITY
]
PHALANX_SOLCAST_TODAY_ENTITY: str = ROLE_DEFAULTS[_c.CONF_ENERGY_SOLCAST_TODAY_ENTITY]
PHALANX_SOLCAST_TOMORROW_ENTITY: str = ROLE_DEFAULTS[
    _c.CONF_ENERGY_SOLCAST_TOMORROW_ENTITY
]
PHALANX_SOLCAST_REMAINING_ENTITY: str = ROLE_DEFAULTS[
    _c.CONF_ENERGY_SOLCAST_REMAINING_ENTITY
]
PHALANX_SOLCAST_DAY_3_ENTITY: str = ROLE_DEFAULTS[_c.CONF_ENERGY_SOLCAST_DAY_3_ENTITY]
PHALANX_WEATHER_ENTITY: str = ROLE_DEFAULTS[_c.CONF_ENERGY_WEATHER_ENTITY]
PHALANX_EVSE_GARAGE_A_POWER_ENTITY: str = ROLE_DEFAULTS[_c.CONF_ENERGY_EVSE_A_ENTITY]
PHALANX_EVSE_GARAGE_B_POWER_ENTITY: str = ROLE_DEFAULTS[_c.CONF_ENERGY_EVSE_B_ENTITY]
PHALANX_L1_CHARGER_ENTITIES: list = list(
    ROLE_DEFAULTS[_c.CONF_ENERGY_L1_CHARGER_ENTITIES]
)
PHALANX_CLOUD_RESERVE_ORACLE_ENTITY: str = ROLE_DEFAULTS[
    _c.CONF_ENERGY_CLOUD_RESERVE_ORACLE_ENTITY
]
PHALANX_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY: str = ROLE_DEFAULTS[
    _c.CONF_ENERGY_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY
]
PHALANX_CLOUD_STORAGE_MODE_ORACLE_ENTITY: str = ROLE_DEFAULTS[
    _c.CONF_ENERGY_CLOUD_STORAGE_MODE_ORACLE_ENTITY
]
PHALANX_CLOUD_BATTERY_SOC_FALLBACK_ENTITY: str = ROLE_DEFAULTS[
    _c.CONF_ENERGY_CLOUD_BATTERY_SOC_FALLBACK_ENTITY
]
PHALANX_CLOUD_LAST_SUCCESS_ENTITY: str = ROLE_DEFAULTS[
    _c.CONF_ENERGY_CLOUD_LAST_SUCCESS_ENTITY
]

# BatteryStrategy role-key -> entity for the roles whose `_get_entity(key,
# DEFAULT_X)` lookups used to fall back to a module default. The three cloud
# WRITE-ROUTING oracle keys are deliberately NOT included: `_cloud_write_target`
# reads them with no default, so pre-change tests that did not configure them
# routed writes to the LOCAL leg. Including them here would silently flip
# those tests to cloud routing. Opt in with `phalanx_cloud_oracles()`.
_BATTERY_ROLE_MAP: dict[str, str] = {
    "storage_mode": PHALANX_STORAGE_MODE_ENTITY,
    "reserve_soc_number": PHALANX_RESERVE_SOC_ENTITY,
    "grid_enabled": PHALANX_GRID_ENABLED_ENTITY,
    "charge_from_grid": PHALANX_CHARGE_FROM_GRID_ENTITY,
    "solcast_today": PHALANX_SOLCAST_TODAY_ENTITY,
    "solcast_tomorrow": PHALANX_SOLCAST_TOMORROW_ENTITY,
    "solcast_remaining": PHALANX_SOLCAST_REMAINING_ENTITY,
    "battery_soc_cloud": PHALANX_CLOUD_BATTERY_SOC_FALLBACK_ENTITY,
    "cloud_last_success": PHALANX_CLOUD_LAST_SUCCESS_ENTITY,
}


def phalanx_cloud_oracles() -> dict:
    """The three cloud write-routing oracle roles (opt-in)."""
    return {
        "cloud_reserve_oracle": PHALANX_CLOUD_RESERVE_ORACLE_ENTITY,
        "cloud_charge_from_grid_oracle": (
            PHALANX_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY
        ),
        "cloud_storage_mode_oracle": PHALANX_CLOUD_STORAGE_MODE_ORACLE_ENTITY,
    }


def phalanx_battery_entities(overrides: dict | None = None) -> dict:
    """BatteryStrategy ``entity_config`` for this house; ``overrides`` win."""
    out = dict(_BATTERY_ROLE_MAP)
    if overrides:
        out.update(overrides)
    return out


def phalanx_evse_config() -> dict:
    """Fresh EVChargerController config for this house (mutable copy)."""
    r = ROLE_DEFAULTS
    return {
        "garage_a": {
            "switch": r[_c.CONF_ENERGY_EVSE_A_SWITCH_ENTITY],
            "power": r[_c.CONF_ENERGY_EVSE_A_ENTITY],
            "energy_today": r[_c.CONF_ENERGY_EVSE_A_ENERGY_TODAY_ENTITY],
            "energy_month": r[_c.CONF_ENERGY_EVSE_A_ENERGY_MONTH_ENTITY],
            "span_breaker": r[_c.CONF_ENERGY_EVSE_A_SPAN_BREAKER],
            "current_limit": r[_c.CONF_ENERGY_EVSE_A_CURRENT_LIMIT_ENTITY],
        },
        "garage_b": {
            "switch": r[_c.CONF_ENERGY_EVSE_B_SWITCH_ENTITY],
            "power": r[_c.CONF_ENERGY_EVSE_B_ENTITY],
            "energy_today": r[_c.CONF_ENERGY_EVSE_B_ENERGY_TODAY_ENTITY],
            "energy_month": r[_c.CONF_ENERGY_EVSE_B_ENERGY_MONTH_ENTITY],
            "span_breaker": r[_c.CONF_ENERGY_EVSE_B_SPAN_BREAKER],
            "current_limit": r[_c.CONF_ENERGY_EVSE_B_CURRENT_LIMIT_ENTITY],
        },
    }


def phalanx_options() -> dict:
    """Fresh copy of this house's role-keyed options (pin-migration table)."""
    return copy.deepcopy(ROLE_DEFAULTS)
