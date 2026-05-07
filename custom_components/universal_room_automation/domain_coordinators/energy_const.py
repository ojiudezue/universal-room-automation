"""Energy Coordinator constants — TOU rate tables, entity mappings, defaults."""

from __future__ import annotations

import re
from typing import Final

# ============================================================================
# PEC TOU Rate Table (2026 Interconnect Time-of-Use)
# ============================================================================
# Source: docs/plans/TOU.md — PEC Interconnection Metering < 50kW
# Import and export rates are symmetric.
# Hours use 24h convention: (start_inclusive, end_exclusive)

PEC_TOU_RATES: Final = {
    "summer": {
        "months": [6, 7, 8, 9],
        "periods": {
            "off_peak": {
                "hours": [(0, 14), (21, 24)],
                "import_rate": 0.043481,
                "export_rate": 0.043481,
            },
            "mid_peak": {
                "hours": [(14, 16), (20, 21)],
                "import_rate": 0.093169,
                "export_rate": 0.093169,
            },
            "peak": {
                "hours": [(16, 20)],
                "import_rate": 0.161843,
                "export_rate": 0.161843,
            },
        },
    },
    "shoulder": {
        "months": [3, 4, 5, 10, 11],
        "periods": {
            "off_peak": {
                "hours": [(0, 17), (21, 24)],
                "import_rate": 0.043481,
                "export_rate": 0.043481,
            },
            "mid_peak": {
                "hours": [(17, 21)],
                "import_rate": 0.086442,
                "export_rate": 0.086442,
            },
        },
    },
    "winter": {
        "months": [12, 1, 2],
        "periods": {
            "off_peak": {
                "hours": [(0, 5), (9, 17), (21, 24)],
                "import_rate": 0.043481,
                "export_rate": 0.043481,
            },
            "mid_peak": {
                "hours": [(5, 9), (17, 21)],
                "import_rate": 0.086442,
                "export_rate": 0.086442,
            },
        },
    },
}

PEC_FIXED_CHARGES: Final = {
    "service_availability": 32.50,
    "delivery_per_kwh": 0.022546,
    "transmission_per_kwh": 0.019930,
}

# ============================================================================
# Solar Day Classification Thresholds (kWh)
# ============================================================================

# Per-month solar thresholds (kWh) derived from actual Enphase production data
# (50 panels, 19.4kW DC). Keyed by month number → (P25, P50, P75).
# Classification: excellent >= P75, good >= P50, moderate >= P25, poor < P25.
SOLAR_MONTHLY_THRESHOLDS: Final = {
    1: (33.0, 61.0, 83.0),   # Jan (extrapolated from Dec)
    2: (49.0, 66.0, 80.0),
    3: (60.0, 80.0, 95.0),
    4: (73.0, 93.0, 108.0),
    5: (85.0, 103.0, 118.0),
    6: (106.0, 125.0, 136.0),
    7: (100.0, 120.0, 133.0),
    8: (88.0, 108.0, 124.0),
    9: (68.0, 88.0, 104.0),
    10: (50.0, 68.0, 83.0),
    11: (36.0, 52.0, 66.0),
    12: (33.0, 61.0, 83.0),
}

# Fallback static thresholds for custom override mode
SOLAR_DAY_THRESHOLDS: Final = {
    "excellent": 100.0,
    "good": 80.0,
    "moderate": 50.0,
    "poor": 30.0,
    # below poor = very_poor
}

# ============================================================================
# Battery Strategy Defaults
# ============================================================================

DEFAULT_RESERVE_SOC: Final = 10  # v4.3.0 D3: was 20; lowered to give arbitrage maneuvering room
DEFAULT_STORM_CHARGE_THRESHOLD: Final = 90
DEFAULT_DECISION_INTERVAL_MINUTES: Final = 5
DEFAULT_BILL_CYCLE_START_DAY: Final = 23

# Battery storage mode values (Enphase Enpower)
BATTERY_MODE_SELF_CONSUMPTION: Final = "self_consumption"
BATTERY_MODE_SAVINGS: Final = "savings"
BATTERY_MODE_BACKUP: Final = "backup"

# ============================================================================
# Entity ID Defaults (Enphase/Envoy)
# ============================================================================

# v4.3.1: The 13 envoy-derived DEFAULT_*_ENTITY constants were REMOVED.
# Production code now requires entity IDs to come via config (auto-derived
# in __init__.py from CONF_ENERGY_ENVOY_ENTITY), and consumer call sites
# handle None gracefully. Validation in validate_envoy_config() +
# __init__.py B1 startup gate ensures EC isn't started without resolved
# envoy entities. Test fixtures defined locally in test files.
#
# Removed: DEFAULT_SOLAR_PRODUCTION_ENTITY, DEFAULT_GRID_CONSUMPTION_ENTITY,
#   DEFAULT_BATTERY_SOC_ENTITY, DEFAULT_BATTERY_POWER_ENTITY,
#   DEFAULT_NET_POWER_ENTITY, DEFAULT_LIFETIME_*_ENTITY (×6),
#   DEFAULT_BATTERY_CAPACITY_ENTITY, DEFAULT_CONSUMPTION_TODAY_ENTITY.

# Enpower control entities
DEFAULT_STORAGE_MODE_ENTITY: Final = "select.enpower_482348004678_storage_mode"
DEFAULT_RESERVE_SOC_ENTITY: Final = "number.enpower_482348004678_reserve_battery_level"
DEFAULT_GRID_ENABLED_ENTITY: Final = "switch.enpower_482348004678_grid_enabled"
DEFAULT_CHARGE_FROM_GRID_ENTITY: Final = "switch.enpower_482348004678_charge_from_grid"

# Solcast forecast
DEFAULT_SOLCAST_TODAY_ENTITY: Final = "sensor.solcast_pv_forecast_forecast_today"
DEFAULT_SOLCAST_TOMORROW_ENTITY: Final = "sensor.solcast_pv_forecast_forecast_tomorrow"
DEFAULT_SOLCAST_REMAINING_ENTITY: Final = "sensor.solcast_pv_forecast_forecast_remaining_today"
DEFAULT_SOLCAST_PEAK_ENTITY: Final = "sensor.solcast_pv_forecast_peak_forecast_today"
DEFAULT_SOLCAST_PEAK_TIME_ENTITY: Final = "sensor.solcast_pv_forecast_peak_time_today"

# Weather
DEFAULT_WEATHER_ENTITY: Final = "weather.phalanxmadrone"

# EVSE (Emporia WiFi chargers)
DEFAULT_EVSE_GARAGE_A_POWER_ENTITY: Final = "sensor.garage_a_power_minute_average"
DEFAULT_EVSE_GARAGE_B_POWER_ENTITY: Final = "sensor.garage_b_power_minute_average"

# Monitored plugs (L1 charger — switch-only, no power sensor)
DEFAULT_L1_CHARGER_ENTITIES: Final = [
    "switch.smartplug_moes_wifi_garagealeftfront_socket_1",
    "switch.smartplug_moes_wifi_garagealeftfront_socket_2",
    "switch.smartplug_moes_wifi_garagealeftfront_socket_3",
    "switch.smartplug_moes_wifi_garagealeftfront_socket_4",
]

# TOU rate file path
DEFAULT_TOU_RATE_FILE: Final = "universal_room_automation/tou_rates.json"

# ============================================================================
# Config Keys (Energy-specific options flow)
# ============================================================================

CONF_ENERGY_RESERVE_SOC: Final = "energy_reserve_soc"
CONF_ENERGY_DECISION_INTERVAL: Final = "energy_decision_interval"
CONF_ENERGY_BILL_CYCLE_DAY: Final = "energy_bill_cycle_day"
CONF_ENERGY_SOLAR_ENTITY: Final = "energy_solar_entity"
CONF_ENERGY_GRID_ENTITY: Final = "energy_grid_entity"
CONF_ENERGY_BATTERY_SOC_ENTITY: Final = "energy_battery_soc_entity"
CONF_ENERGY_BATTERY_POWER_ENTITY: Final = "energy_battery_power_entity"
CONF_ENERGY_NET_POWER_ENTITY: Final = "energy_net_power_entity"
CONF_ENERGY_STORAGE_MODE_ENTITY: Final = "energy_storage_mode_entity"
CONF_ENERGY_RESERVE_SOC_ENTITY: Final = "energy_reserve_soc_entity"
CONF_ENERGY_GRID_ENABLED_ENTITY: Final = "energy_grid_enabled_entity"
CONF_ENERGY_CHARGE_FROM_GRID_ENTITY: Final = "energy_charge_from_grid_entity"
CONF_ENERGY_SOLCAST_TODAY_ENTITY: Final = "energy_solcast_today_entity"
CONF_ENERGY_SOLCAST_REMAINING_ENTITY: Final = "energy_solcast_remaining_entity"
CONF_ENERGY_SOLCAST_TOMORROW_ENTITY: Final = "energy_solcast_tomorrow_entity"
CONF_ENERGY_WEATHER_ENTITY: Final = "energy_weather_entity"
CONF_ENERGY_SOLAR_CLASSIFICATION_MODE: Final = "energy_solar_classification_mode"
CONF_ENERGY_SOLAR_THRESHOLD_EXCELLENT: Final = "energy_solar_threshold_excellent"
CONF_ENERGY_SOLAR_THRESHOLD_GOOD: Final = "energy_solar_threshold_good"
CONF_ENERGY_SOLAR_THRESHOLD_MODERATE: Final = "energy_solar_threshold_moderate"
CONF_ENERGY_SOLAR_THRESHOLD_POOR: Final = "energy_solar_threshold_poor"

CONF_ENERGY_EVSE_A_ENTITY: Final = "energy_evse_a_entity"
CONF_ENERGY_EVSE_B_ENTITY: Final = "energy_evse_b_entity"
CONF_ENERGY_L1_CHARGER_ENTITIES: Final = "energy_l1_charger_entities"
CONF_ENERGY_TOU_RATE_FILE: Final = "energy_tou_rate_file"

# v4.0.12: Envoy auto-derive — one entity picker derives all Envoy entities
CONF_ENERGY_ENVOY_ENTITY: Final = "energy_envoy_entity"
CONF_ENERGY_BATTERY_CAPACITY_ENTITY: Final = "energy_battery_capacity_entity"
CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY: Final = "energy_lifetime_consumption_entity"
CONF_ENERGY_LIFETIME_PRODUCTION_ENTITY: Final = "energy_lifetime_production_entity"
CONF_ENERGY_LIFETIME_NET_IMPORT_ENTITY: Final = "energy_lifetime_net_import_entity"
CONF_ENERGY_LIFETIME_NET_EXPORT_ENTITY: Final = "energy_lifetime_net_export_entity"
CONF_ENERGY_LIFETIME_BATTERY_CHARGED_ENTITY: Final = "energy_lifetime_battery_charged_entity"
CONF_ENERGY_LIFETIME_BATTERY_DISCHARGED_ENTITY: Final = "energy_lifetime_battery_discharged_entity"
CONF_ENERGY_CONSUMPTION_TODAY_ENTITY: Final = "energy_consumption_today_entity"

# Solar classification modes
SOLAR_CLASS_MODE_AUTOMATIC: Final = "automatic"
SOLAR_CLASS_MODE_CUSTOM: Final = "custom"

# ============================================================================
# E6: Load Shedding + Constraint Config
# ============================================================================

CONF_ENERGY_LOAD_SHEDDING_ENABLED: Final = "energy_load_shedding_enabled"
CONF_ENERGY_LOAD_SHEDDING_THRESHOLD: Final = "energy_load_shedding_threshold_kw"
CONF_ENERGY_LOAD_SHEDDING_SUSTAINED_MINUTES: Final = "energy_load_shedding_sustained_minutes"
CONF_ENERGY_LOAD_SHEDDING_MODE: Final = "energy_load_shedding_mode"

CONF_ENERGY_CONSTRAINT_COAST_OFFSET: Final = "energy_constraint_coast_offset"
CONF_ENERGY_CONSTRAINT_PRECOOL_OFFSET: Final = "energy_constraint_precool_offset"
CONF_ENERGY_CONSTRAINT_PREHEAT_OFFSET: Final = "energy_constraint_preheat_offset"
CONF_ENERGY_CONSTRAINT_SHED_OFFSET: Final = "energy_constraint_shed_offset"
CONF_ENERGY_PREHEAT_TEMP_THRESHOLD: Final = "energy_preheat_temp_threshold"

# ============================================================================
# Off-Peak Drain Targets (% SOC) — based on tomorrow's solar forecast
# ============================================================================
# Aggressive drain: off-peak grid at $0.043 is 3.7x cheaper than peak ($0.162).
# Draining to low SOC overnight maximizes room for tomorrow's solar absorption.
# Risk is minimal: arbitrage catches poor-forecast + low-SOC scenarios.
# When SOC > target: drain stored solar (free energy) during cheap off-peak
# When SOC <= target: hold and import cheap grid at $0.043/kWh

DEFAULT_OFFPEAK_DRAIN_EXCELLENT: Final = 10
DEFAULT_OFFPEAK_DRAIN_GOOD: Final = 15
DEFAULT_OFFPEAK_DRAIN_MODERATE: Final = 20
DEFAULT_OFFPEAK_DRAIN_POOR: Final = 30
DEFAULT_OFFPEAK_DRAIN_UNKNOWN: Final = 40

CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT: Final = "energy_offpeak_drain_excellent"
CONF_ENERGY_OFFPEAK_DRAIN_GOOD: Final = "energy_offpeak_drain_good"
CONF_ENERGY_OFFPEAK_DRAIN_MODERATE: Final = "energy_offpeak_drain_moderate"
CONF_ENERGY_OFFPEAK_DRAIN_POOR: Final = "energy_offpeak_drain_poor"

# ============================================================================
# Grid Charge Arbitrage
# ============================================================================
# When tomorrow is poor/very_poor solar and SOC < trigger, charge from grid
# overnight at off-peak rate ($0.043) to avoid importing at mid-peak/peak later.

# v4.5.0 D2: DEFAULT_ARBITRAGE_SOC_TRIGGER and CONF_ENERGY_ARBITRAGE_SOC_TRIGGER
# removed — gate is now forecast-class only (no SOC trigger). The constant
# below is retained as a documented removed-field marker for the migration
# helper which strips the legacy CONF key from entry.options.
DEFAULT_ARBITRAGE_SOC_TARGET: Final = 80
CONF_ENERGY_ARBITRAGE_ENABLED: Final = "energy_arbitrage_enabled"
# Legacy key — kept on this line ONLY so the v4.5.0 D2 migration helper
# can pop it from entry.options. No production code reads this key.
CONF_ENERGY_ARBITRAGE_SOC_TRIGGER_LEGACY: Final = "energy_arbitrage_soc_trigger"
CONF_ENERGY_ARBITRAGE_SOC_TARGET: Final = "energy_arbitrage_soc_target"

# v4.5.0 D1/D2: rename of arbitrage_target → peak_buffer_target.
# Keeps DEFAULT_ARBITRAGE_SOC_TARGET as the canonical default for now;
# D2 swaps the public name. The number-entity hard min/max for the new
# live-tunable charge lead time are set per the plan's physics-floor
# analysis: 84 min minimum to charge 10→80% at 20 kW × 0.9 RTE; the 120
# floor adds ~36 min margin against Enphase stalls. Default 360 (6 h)
# biases earlier-start so same-day target windows benefit from intraday
# Solcast updates accumulated since sunrise.
DEFAULT_PEAK_BUFFER_TARGET: Final = DEFAULT_ARBITRAGE_SOC_TARGET  # 80
DEFAULT_ARBITRAGE_CHARGE_LEAD_TIME_MIN: Final = 360
MIN_ARBITRAGE_CHARGE_LEAD_TIME_MIN: Final = 120
MAX_ARBITRAGE_CHARGE_LEAD_TIME_MIN: Final = 720
CONF_ENERGY_PEAK_BUFFER_TARGET: Final = "energy_peak_buffer_target"
CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN: Final = (
    "energy_arbitrage_charge_lead_time_min"
)
# v4.5.0 D3: multi-day Solcast lookback (D+2 awareness). Default OFF
# during calibration cycle per Open Question #3.
DEFAULT_SOLCAST_DAY_3_ENTITY: Final = (
    "sensor.solcast_pv_forecast_forecast_day_3"
)
CONF_ENERGY_SOLCAST_DAY_3_ENTITY: Final = "energy_solcast_day_3_entity"
CONF_ENERGY_MULTI_DAY_HORIZON_ENABLED: Final = "energy_multi_day_horizon_enabled"

# ============================================================================
# EVSE Refinement
# ============================================================================

DEFAULT_EXCESS_SOLAR_SOC_THRESHOLD: Final = 95
DEFAULT_EXCESS_SOLAR_KWH_THRESHOLD: Final = 5.0
EVSE_CHARGING_POWER_THRESHOLD: Final = 100  # watts
EVSE_ESTIMATED_POWER_W: Final = 7600  # L2 charger estimated draw when sensor unavailable
CONF_ENERGY_EXCESS_SOLAR_ENABLED: Final = "energy_excess_solar_enabled"
CONF_ENERGY_EXCESS_SOLAR_SOC: Final = "energy_excess_solar_soc"
CONF_ENERGY_EXCESS_SOLAR_KWH: Final = "energy_excess_solar_kwh"

# EV Battery Drain Protection (v4.2.17)
DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD: Final = 50
CONF_ENERGY_EV_BATTERY_DRAIN_SOC: Final = "energy_ev_battery_drain_soc"
EV_BATTERY_DRAIN_COOLDOWN_SECONDS: Final = 3600  # 1 hour after manual override

# EV Grid Import Cap (v4.0.18)
DEFAULT_GRID_IMPORT_CAP_KW: Final = 8.0
DEFAULT_GRID_IMPORT_CAP_HYSTERESIS_KW: Final = 1.0
CONF_ENERGY_GRID_IMPORT_CAP_ENABLED: Final = "energy_grid_import_cap_enabled"
CONF_ENERGY_GRID_IMPORT_CAP_KW: Final = "energy_grid_import_cap_kw"

# v4.2.0: Circuit monitoring configurability
CONF_ENERGY_CIRCUIT_INTEGRATIONS: Final = "energy_circuit_integrations"
CONF_ENERGY_CIRCUIT_EXTRA_ENTITIES: Final = "energy_circuit_extra_entities"
CONF_ENERGY_CIRCUIT_AUTODISCOVER_SPAN: Final = "energy_circuit_autodiscover_span"
CONF_ENERGY_CIRCUIT_EXCLUDE_ENTITIES: Final = "energy_circuit_exclude_entities"
CONF_ENERGY_GENERATOR_ENTITY: Final = "energy_generator_entity"

# v4.2.0: Direct grid import/export sensors (e.g., Emporia mains)
CONF_ENERGY_GRID_IMPORT_ENTITY: Final = "energy_grid_import_entity"
CONF_ENERGY_GRID_EXPORT_ENTITY: Final = "energy_grid_export_entity"

# v4.2.17: Utility company net energy meter (SmartHub, etc.)
CONF_ENERGY_UTILITY_METER_ENTITY: Final = "energy_utility_meter_entity"

# Load shedding defaults
DEFAULT_LOAD_SHEDDING_THRESHOLD_KW: Final = 5.0
DEFAULT_LOAD_SHEDDING_SUSTAINED_MINUTES: Final = 15
LOAD_SHEDDING_MODE_FIXED: Final = "fixed"
LOAD_SHEDDING_MODE_AUTO: Final = "auto"
LOAD_SHEDDING_AUTO_MIN_DAYS: Final = 30
LOAD_SHEDDING_AUTO_PERCENTILE: Final = 90  # 90th percentile of peak import

# Constraint offset defaults (degrees F)
DEFAULT_CONSTRAINT_COAST_OFFSET: Final = 3.0
DEFAULT_CONSTRAINT_PRECOOL_OFFSET: Final = -2.0
DEFAULT_CONSTRAINT_PREHEAT_OFFSET: Final = 2.0
DEFAULT_CONSTRAINT_SHED_OFFSET: Final = 5.0
DEFAULT_PREHEAT_TEMP_THRESHOLD: Final = 40.0  # F — forecast low below this triggers pre_heat

# Load shedding priority order (cascade)
LOAD_SHEDDING_PRIORITY: Final = ["pool", "ev", "smart_plugs", "hvac"]


# ============================================================================
# Envoy Auto-Derive (v4.0.12)
# ============================================================================

_ENVOY_SERIAL_RE = re.compile(r"envoy_(\d+)_")


def extract_envoy_serial(entity_id: str) -> str | None:
    """Extract Envoy serial number from any Envoy entity ID.

    >>> extract_envoy_serial("sensor.envoy_482543015950_current_power_production")
    '482543015950'
    >>> extract_envoy_serial("sensor.some_other_thing") is None
    True
    """
    match = _ENVOY_SERIAL_RE.search(entity_id)
    return match.group(1) if match else None


def derive_envoy_config(serial: str) -> dict[str, str]:
    """Return CONF_ENERGY_* keys → derived entity IDs for given Envoy serial.

    Used in __init__.py to inject auto-derived entities into energy_entity_config.
    Explicit per-entity config keys override these via dict.setdefault().

    NOTE: Enpower entities (storage_mode, reserve_soc, grid_enabled,
    charge_from_grid) have a DIFFERENT serial than the Envoy and are
    not derived here. They must be configured separately if hardware changes.
    """
    return {
        CONF_ENERGY_SOLAR_ENTITY: f"sensor.envoy_{serial}_current_power_production",
        CONF_ENERGY_GRID_ENTITY: f"sensor.envoy_{serial}_current_power_consumption",
        CONF_ENERGY_BATTERY_SOC_ENTITY: f"sensor.envoy_{serial}_battery",
        CONF_ENERGY_BATTERY_POWER_ENTITY: f"sensor.envoy_{serial}_current_battery_discharge",
        CONF_ENERGY_NET_POWER_ENTITY: f"sensor.envoy_{serial}_current_net_power_consumption",
        CONF_ENERGY_BATTERY_CAPACITY_ENTITY: f"sensor.envoy_{serial}_battery_capacity",
        CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY: f"sensor.envoy_{serial}_lifetime_energy_consumption",
        CONF_ENERGY_LIFETIME_PRODUCTION_ENTITY: f"sensor.envoy_{serial}_lifetime_energy_production",
        CONF_ENERGY_LIFETIME_NET_IMPORT_ENTITY: f"sensor.envoy_{serial}_lifetime_net_energy_consumption",
        CONF_ENERGY_LIFETIME_NET_EXPORT_ENTITY: f"sensor.envoy_{serial}_lifetime_net_energy_production",
        CONF_ENERGY_LIFETIME_BATTERY_CHARGED_ENTITY: f"sensor.envoy_{serial}_lifetime_battery_energy_charged",
        CONF_ENERGY_LIFETIME_BATTERY_DISCHARGED_ENTITY: f"sensor.envoy_{serial}_lifetime_battery_energy_discharged",
        CONF_ENERGY_CONSUMPTION_TODAY_ENTITY: f"sensor.envoy_{serial}_energy_consumption_today",
    }


# Critical Envoy-derived entities for V4 validation.
# Missing any of these breaks core EC capabilities (billing, battery decisions,
# daily lifetime accounting). Lifetime battery + capacity are NOT in this list
# because installs without battery legitimately won't have them.
ENVOY_REQUIRED_DERIVED_KEYS: Final = (
    CONF_ENERGY_NET_POWER_ENTITY,
    CONF_ENERGY_SOLAR_ENTITY,
    CONF_ENERGY_LIFETIME_NET_IMPORT_ENTITY,
    CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY,
)

# v4.3.1: Validator error codes — single source of truth.
# Keys MUST match strings.json `options.error.<code>` for HA's form
# rendering to localize them. Caller (validate_envoy_config) returns these
# as values in the errors dict; config_flow.py reads them and feeds them
# to async_show_form's `errors` param unchanged.
ENVOY_ERR_REQUIRED: Final = "envoy_required"
ENVOY_ERR_INVALID_FORMAT: Final = "envoy_invalid_format"
ENVOY_ERR_ENTITY_MISSING: Final = "envoy_entity_missing"
ENVOY_ERR_DERIVED_MISSING: Final = "derived_entity_missing"
ENVOY_ERR_BASE_DERIVED_MISSING: Final = "envoy_derived_missing"


# v4.3.0 D3: Threshold ladder validator.
# The coherent ladder is:
#   reserve_soc ≤ drain_excellent ≤ drain_good ≤ drain_moderate ≤ drain_poor
#   reserve_soc < arbitrage_trigger < drain_poor   (strict on both sides)
#   arbitrage_target > drain_poor                   (no immediate re-drain)
# Drains below reserve_soc are incoherent (Enphase clamps to floor).
# Arbitrage trigger collisions cause drain↔arbitrage oscillation thrash.

def validate_threshold_ladder(
    reserve_soc: int,
    drain_targets: dict,
    arbitrage_trigger: int | None = None,
    arbitrage_target: int = 80,
    peak_buffer_target: int | None = None,
) -> str | None:
    """Validate the SOC threshold ladder for coherence.

    v4.5.0 D2: arbitrage_trigger is OPTIONAL — v4.5.0 removed the SOC
    trigger gate entirely (the gate is forecast-class only). When None,
    trigger checks are skipped. peak_buffer_target is preferred over
    arbitrage_target as the buffer-ceiling check input; the latter is
    accepted for back-compat.

    Returns None if valid, else a human-readable warning string suitable
    for surfacing on a sensor attribute. Caller logs separately.
    """
    drain_excellent = int(drain_targets.get("excellent", 0))
    drain_good = int(drain_targets.get("good", 0))
    drain_moderate = int(drain_targets.get("moderate", 0))
    drain_poor = int(drain_targets.get("poor", 0))

    # Drain ladder: monotonic non-decreasing, all above reserve_soc
    if drain_excellent < reserve_soc:
        return (
            f"drain_excellent ({drain_excellent}) < reserve_soc "
            f"({reserve_soc}) — value will be clamped by Enphase floor"
        )
    if not (drain_excellent <= drain_good <= drain_moderate <= drain_poor):
        return (
            f"drain ladder not monotonic: "
            f"excellent={drain_excellent}, good={drain_good}, "
            f"moderate={drain_moderate}, poor={drain_poor}"
        )

    # v4.5.0: trigger checks are optional (kept for back-compat callers).
    if arbitrage_trigger is not None:
        if arbitrage_trigger <= reserve_soc:
            return (
                f"arbitrage_trigger ({arbitrage_trigger}) ≤ reserve_soc "
                f"({reserve_soc}) — arbitrage would never fire above safety floor"
            )
        if arbitrage_trigger >= drain_poor:
            return (
                f"arbitrage_trigger ({arbitrage_trigger}) ≥ drain_poor "
                f"({drain_poor}) — boundary collision causes drain↔arbitrage "
                f"oscillation when tomorrow=poor"
            )

    # Buffer ceiling (renamed from arbitrage_target in v4.5.0 D2).
    buffer_ceiling = (
        peak_buffer_target if peak_buffer_target is not None
        else arbitrage_target
    )
    if buffer_ceiling <= drain_poor:
        return (
            f"peak_buffer_target ({buffer_ceiling}) ≤ drain_poor "
            f"({drain_poor}) — drain path would immediately re-drain after "
            f"arbitrage CHARGE completes"
        )

    return None


def validate_envoy_config(
    hass,
    energy_entity_config: dict,
) -> dict:
    """Validate envoy entity is set, parseable, present, and critical derived entities exist.

    v4.2.29: Replaces silent-fallback-to-wrong-default with explicit validation.

    Returns a dict:
      - ok (bool): True iff no hard-fail check tripped.
      - errors (dict[str, str]): {field_or_'base': error_code}. Empty if ok.
      - warnings (list[str]): non-blocking issues (e.g., entity unavailable now).
      - serial (str | None): parsed serial when V1 passes, else None.
      - resolved (dict[str, str]): entities the EC would actually use, after
        applying explicit overrides on top of derived-from-serial defaults.

    Validation tiers:
      V0: envoy_entity field is set (non-empty)
      V1: extract_envoy_serial returns a serial
      V2: hass.states.get(envoy_entity) is not None
      V3: state is not 'unavailable'/'unknown'  (warning only)
      V4: critical derived entities (NET_POWER, SOLAR, LIFETIME_NET_IMPORT,
          LIFETIME_CONSUMPTION) all exist in HA. If user explicitly overrode
          a CONF_ENERGY_*_ENTITY, the override is checked instead of derived.

    Used by:
      - config_flow.async_step_coordinator_energy: reject save on hard-fail
      - __init__.py: skip EC registration + raise repair issue on hard-fail
    """
    errors: dict[str, str] = {}
    warnings: list[str] = []
    resolved: dict[str, str] = {}

    envoy_eid = (energy_entity_config or {}).get(CONF_ENERGY_ENVOY_ENTITY)

    # V0: required
    if not envoy_eid:
        errors[CONF_ENERGY_ENVOY_ENTITY] = ENVOY_ERR_REQUIRED
        return {
            "ok": False, "errors": errors, "warnings": warnings,
            "serial": None, "resolved": resolved,
        }

    # V1: parseable
    serial = extract_envoy_serial(envoy_eid)
    if not serial:
        errors[CONF_ENERGY_ENVOY_ENTITY] = ENVOY_ERR_INVALID_FORMAT
        return {
            "ok": False, "errors": errors, "warnings": warnings,
            "serial": None, "resolved": resolved,
        }

    # V2: entity exists in HA
    state = hass.states.get(envoy_eid)
    if state is None:
        errors[CONF_ENERGY_ENVOY_ENTITY] = ENVOY_ERR_ENTITY_MISSING
        return {
            "ok": False, "errors": errors, "warnings": warnings,
            "serial": serial, "resolved": resolved,
        }

    # V3: state not unavailable (warning only — Envoy can blip)
    if state.state in ("unavailable", "unknown"):
        warnings.append(
            f"Envoy entity '{envoy_eid}' is currently '{state.state}' — "
            "config saved, but verify Enphase integration is online"
        )

    # V4: critical derived entities exist (after explicit-override layering)
    derived = derive_envoy_config(serial)
    for key, derived_eid in derived.items():
        # Explicit override wins over derived; mirrors __init__.py:1386 setdefault
        resolved[key] = (energy_entity_config or {}).get(key) or derived_eid

    for key in ENVOY_REQUIRED_DERIVED_KEYS:
        eid = resolved.get(key)
        if not eid or hass.states.get(eid) is None:
            errors[key] = ENVOY_ERR_DERIVED_MISSING

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "serial": serial,
        "resolved": resolved,
    }
