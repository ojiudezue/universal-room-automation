"""Signal constants and shared data classes for domain coordinators."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

# ============================================================================
# Dispatcher signal constants
# ============================================================================

SIGNAL_HOUSE_STATE_CHANGED: Final = "ura_house_state_changed"
SIGNAL_ENERGY_CONSTRAINT: Final = "ura_energy_constraint"
SIGNAL_CENSUS_UPDATED: Final = "ura_census_updated"
SIGNAL_SAFETY_HAZARD: Final = "ura_safety_hazard"
SIGNAL_SAFETY_ENTITIES_UPDATE: Final = "ura_safety_entities_update"
SIGNAL_SECURITY_EVENT: Final = "ura_security_event"
SIGNAL_SECURITY_ENTITIES_UPDATE: Final = "ura_security_entities_update"
SIGNAL_NM_ENTITIES_UPDATE: Final = "ura_nm_entities_update"
SIGNAL_NM_ALERT_STATE_CHANGED: Final = "ura_nm_alert_state_changed"
SIGNAL_PERSON_ARRIVING: Final = "ura_person_arriving"
SIGNAL_ENERGY_ENTITIES_UPDATE: Final = "ura_energy_entities_update"
SIGNAL_ACTIVITY_LOGGED: Final = "ura_activity_logged"
SIGNAL_BAYESIAN_UPDATED: Final = "ura_bayesian_updated"
SIGNAL_OCCUPANCY_ANOMALY: Final = "ura_occupancy_anomaly"


# ============================================================================
# Shared data classes for inter-coordinator communication
# ============================================================================

@dataclass
class HouseStateChange:
    """Payload for SIGNAL_HOUSE_STATE_CHANGED."""

    previous_state: str
    new_state: str
    confidence: float
    trigger: str


@dataclass
class EnergyConstraint:
    """Payload for SIGNAL_ENERGY_CONSTRAINT."""

    mode: str  # normal | pre_cool | pre_heat | coast | shed
    setpoint_offset: float  # degrees F, negative = lower, positive = raise
    occupied_only: bool = True
    max_runtime_minutes: int | None = None
    fan_assist: bool = False
    reason: str = ""
    solar_class: str = ""
    forecast_high_temp: float | None = None
    soc: int | None = None


@dataclass
class SafetyHazard:
    """Payload for SIGNAL_SAFETY_HAZARD."""

    hazard_type: str  # smoke | co | water_leak | freeze | air_quality
    severity: str  # critical | high | medium | low
    source_entity: str = ""
    value: float | None = None
    details: str = ""


@dataclass
class SecurityEvent:
    """Payload for SIGNAL_SECURITY_EVENT."""

    event_type: str  # entry_alert | unknown_person | lock_check | armed_change
    severity: str  # critical | high | medium | low
    source_entity: str = ""
    armed_state: str = ""
    details: str = ""
