"""Signal constants and shared data classes for domain coordinators."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

# ============================================================================
# Dispatcher signal constants
# ============================================================================

SIGNAL_HOUSE_STATE_CHANGED: Final = "ura_house_state_changed"
SIGNAL_ENERGY_CONSTRAINT: Final = "ura_energy_constraint"
SIGNAL_COMFORT_REQUEST: Final = "ura_comfort_request"
SIGNAL_CENSUS_UPDATED: Final = "ura_census_updated"
SIGNAL_SAFETY_HAZARD: Final = "ura_safety_hazard"
SIGNAL_SAFETY_ENTITIES_UPDATE: Final = "ura_safety_entities_update"


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

    mode: str  # normal | pre_cool | coast | shed
    setpoint_offset: float  # degrees F, negative = lower, positive = raise
    occupied_only: bool = True
    max_runtime_minutes: int | None = None
    fan_assist: bool = False


@dataclass
class ComfortRequest:
    """Payload for SIGNAL_COMFORT_REQUEST."""

    room_id: str
    zone: str
    request_type: str  # zone_adjustment | fan_assist
    target_temp: float | None = None
    reason: str = ""


@dataclass
class SafetyHazard:
    """Payload for SIGNAL_SAFETY_HAZARD."""

    hazard_type: str  # smoke | co | water_leak | freeze | air_quality
    severity: str  # critical | high | medium | low
    source_entity: str = ""
    value: float | None = None
    details: str = ""
