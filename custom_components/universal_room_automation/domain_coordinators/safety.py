"""Safety Coordinator — environmental hazard detection and response.

Monitors smoke, CO, water leak, freeze risk, air quality, temperature
extremes, and humidity. Highest priority coordinator (100) — overrides
all other coordinators during safety events.

v3.6.0-c2: Initial implementation with full hazard type enumeration,
bidirectional rate-of-change detection, room-type-aware humidity
thresholds, flooding escalation, and alert deduplication.

Hazard types (12):
  SMOKE, FIRE, WATER_LEAK, FLOODING, CARBON_MONOXIDE, HIGH_CO2,
  HIGH_TVOC, FREEZE_RISK, OVERHEAT, HVAC_FAILURE, HIGH_HUMIDITY,
  LOW_HUMIDITY

Detection capabilities:
  - Binary sensor discovery (smoke, leak) via entity registry area_id
  - Numeric sensor monitoring (CO, CO2, TVOC, temperature, humidity)
  - Rate-of-change detection (bidirectional, date-based season)
  - Room-type-aware humidity thresholds (normal, bathroom, basement)
  - Flooding escalation (multi-sensor or sustained >15min)
  - Alert deduplication with per-severity suppression windows
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_AREA_ID,
    CONF_ENTRY_TYPE,
    CONF_ROOM_NAME,
    CONF_ROOM_TYPE,
    DOMAIN,
    ENTRY_TYPE_ROOM,
)
from .base import (
    BaseCoordinator,
    CoordinatorAction,
    ConstraintAction,
    Intent,
    NotificationAction,
    ServiceCallAction,
    Severity,
)
from .coordinator_diagnostics import MetricBaseline
from .signals import SIGNAL_SAFETY_HAZARD, SafetyHazard as SafetyHazardPayload

_LOGGER = logging.getLogger(__name__)

# States that mean an entity is not providing real data
_UNAVAILABLE_STATES = frozenset({"unavailable", "unknown"})

# v4.6.5.1 P2: Module-level suppression registry for safety. Companion to
# SafetyCoordinator.SAFETY_METRICS (defined as a class attribute). Every
# metric in SAFETY_METRICS must be EITHER wired (record_observation call
# with downstream store_event emit in this file) OR listed here. Today
# the only safety metric (`active_hazard_count`) is wired (v4.6.3 D2), so
# this set is empty; promoting it to a named constant codifies the
# v4.6.3.1 doctrine and gives future maintainers an obvious place to add
# a suppression rationale.
#
# Note: `hazard_trigger_frequency` was removed from SAFETY_METRICS entirely
# in v4.6.4 P2 (constant 1.0 → z=0 → never emitted). It is NOT listed here
# because it is no longer in SAFETY_METRICS at all — the parametric audit
# would treat its presence here as inconsistent.
SAFETY_SUPPRESSED_FROM_PERSISTENCE: frozenset[str] = frozenset()


# ============================================================================
# Enums
# ============================================================================


class EventSeverity(StrEnum):
    """PWA-facing severity vocabulary for the recent-events ring buffer.

    Maps from internal Severity (CRITICAL/HIGH/MEDIUM/LOW) to the four
    values the PWA RecentEventsAttrs contract expects.

    Bug Class #22: single StrEnum definition — never redefine this vocabulary
    at call sites. _record_event() calls EventSeverity.from_severity() to
    convert; get_recent_events() reads the already-converted strings from the
    buffer; severity_breakdown keys are exactly these four values.
    """

    INFO = "info"
    ADVISORY = "advisory"
    ALERT = "alert"
    CRITICAL = "critical"

    @classmethod
    def from_severity(cls, severity: "Severity") -> "EventSeverity":
        """Map internal Severity → PWA EventSeverity string."""
        if severity == Severity.CRITICAL:
            return cls.CRITICAL
        elif severity == Severity.HIGH:
            return cls.ALERT
        elif severity == Severity.MEDIUM:
            return cls.ADVISORY
        return cls.INFO


class HazardType(StrEnum):
    """Types of environmental hazards."""

    SMOKE = "smoke"
    FIRE = "fire"
    WATER_LEAK = "water_leak"
    FLOODING = "flooding"
    CARBON_MONOXIDE = "carbon_monoxide"
    HIGH_CO2 = "high_co2"
    HIGH_TVOC = "high_tvoc"
    FREEZE_RISK = "freeze_risk"
    OVERHEAT = "overheat"
    HVAC_FAILURE = "hvac_failure"
    HIGH_HUMIDITY = "high_humidity"
    LOW_HUMIDITY = "low_humidity"


# ============================================================================
# Data classes
# ============================================================================


@dataclass
class Hazard:
    """Represents a detected environmental hazard."""

    type: HazardType
    severity: Severity
    confidence: float
    location: str
    sensor_id: str
    value: Any
    threshold: Any
    detected_at: datetime
    message: str


# ============================================================================
# Thresholds
# ============================================================================

# Numeric sensor thresholds: hazard_type -> {severity: threshold}
# For CO, CO2, TVOC, HUMIDITY: higher value = worse (check >=)
# For FREEZE_RISK: lower value = worse (check <=)
NUMERIC_THRESHOLDS: dict[str, dict[Severity, float]] = {
    HazardType.CARBON_MONOXIDE: {
        Severity.CRITICAL: 100.0,
        Severity.HIGH: 50.0,
        Severity.MEDIUM: 35.0,
        Severity.LOW: 25.0,  # v3.6.0-c2.6: raised from 10 (WHO safe limit) to 25
    },
    HazardType.HIGH_CO2: {
        Severity.HIGH: 2500.0,
        Severity.MEDIUM: 1500.0,
        # NM Cycle A A5: LOW is now LOG-ONLY (see _handle_numeric_hazard).
        # Default 1200 = 2026-07-20 Study A CO2 p90; runtime override via
        # CONF_CO2_LOG_ONLY_CEILING_PPM.
        Severity.LOW: 1200.0,
    },
    HazardType.HIGH_TVOC: {
        # NM Cycle A A5: HIGH raised to 1500 (above observed Master Bath
        # max=1244). MEDIUM/LOW unchanged — MEDIUM is now the sustained-
        # window rung (30-min above 500 → HIGH). Absolute 1500 fires
        # immediately.
        Severity.HIGH: 1500.0,
        Severity.MEDIUM: 500.0,
        Severity.LOW: 250.0,
    },
    HazardType.FREEZE_RISK: {
        Severity.HIGH: 35.0,
        Severity.MEDIUM: 40.0,
        Severity.LOW: 45.0,
    },
    HazardType.OVERHEAT: {
        Severity.HIGH: 115.0,
        Severity.MEDIUM: 105.0,
        Severity.LOW: 100.0,  # v3.6.0-c2.6: raised from 95 to reduce false positives
    },
}

# Room-type humidity thresholds
# {room_type: {"low": threshold, "medium": threshold, "high": threshold, "window_hours": hours}}
# NM Cycle A A4: "normal" values are DEFAULTS — runtime lookup via
# _resolve_humidity_thresholds() honors CoordinatorManager options overrides
# (CONF_HUMIDITY_NORMAL_*_PCT). The "low" rung is now LOG-ONLY: crossing
# it starts the sustained-window clock but does NOT emit an NM hazard.
# Hazard emission requires reaching MEDIUM or HIGH ceilings sustained.
HUMIDITY_THRESHOLDS: dict[str, dict[str, float]] = {
    # A4 defaults 78/85/92 fitted to 2026-07-20 audit — see const.py DEFAULT_HUMIDITY_NORMAL_*
    "normal": {"low": 78.0, "medium": 85.0, "high": 92.0, "window_hours": 2.0},
    "bathroom": {"low": 80.0, "medium": 85.0, "high": 90.0, "window_hours": 4.0},
    "basement": {"low": 65.0, "medium": 75.0, "high": 85.0, "window_hours": 2.0},
    # A4: outdoor rooms (patios, decks, screened porches) never emit humidity
    # hazards — outdoor RH tracks weather, not indoor moisture management.
    # Sentinel entry consulted by _handle_humidity for a fast early-return.
    "outdoor": {"low": 200.0, "medium": 200.0, "high": 200.0, "window_hours": 999.0},
}

# Low humidity thresholds (universal)
LOW_HUMIDITY_THRESHOLDS: dict[Severity, float] = {
    Severity.MEDIUM: 25.0,
    Severity.LOW: 30.0,
}


# ============================================================================
# Zone chip safety-band projection (backlog #12, v5.38.0)
# ============================================================================
# Thin projection over the four EXISTING tables above (HUMIDITY_THRESHOLDS,
# LOW_HUMIDITY_THRESHOLDS, NUMERIC_THRESHOLDS[OVERHEAT|FREEZE_RISK]) for the
# Residence-tab zone chip (aggregation.ZoneSafetyAlertSensor). NOT a second
# copy: `resolve_safety_bands()` reads the tables at call time so any tuning
# to the safety-coordinator thresholds is inherited automatically.
#
# Rung selection is rung-1 (module constant): changing these is a safety
# semantics decision and must go through review — not an operator knob.
# The chip fires at MEDIUM (the "worth alerting a human" rung), above the
# LOG-ONLY LOW rung that only starts sustained-window clocks.

ZONE_CHIP_HUMIDITY_RUNG = "medium"          # HUMIDITY_THRESHOLDS[type][rung]
ZONE_CHIP_TEMP_HIGH_RUNG = Severity.MEDIUM  # NUMERIC_THRESHOLDS[OVERHEAT][r]
ZONE_CHIP_TEMP_LOW_RUNG = Severity.MEDIUM   # NUMERIC_THRESHOLDS[FREEZE][r]
ZONE_CHIP_LOW_HUMIDITY_RUNG = Severity.MEDIUM  # LOW_HUMIDITY_THRESHOLDS[r]

# Comfort-drift (D4a) uses the OLD chip thresholds — housekeeping/comfort
# grade, not safety. Populates an attribute only; does not affect is_on.
ZONE_CHIP_COMFORT_TEMP_HIGH = 85.0
ZONE_CHIP_COMFORT_TEMP_LOW = 55.0
ZONE_CHIP_COMFORT_HUMIDITY_HIGH = 70.0
ZONE_CHIP_COMFORT_HUMIDITY_LOW = 25.0


@dataclass(frozen=True)
class SafetyBands:
    """Per-room-type safety-alert bands consumed by the zone chip.

    All temperatures in °F, humidity in %RH. `None` on a humidity field or
    ``humidity_exempt=True`` means the chip must NOT evaluate humidity for
    this room type (garage / outdoor). ``temp_exempt=True`` means the chip
    must NOT evaluate temperature either (outdoor).
    """

    temp_high_medium: float
    temp_high_low: float
    temp_low_medium: float
    temp_low_low: float
    humidity_high_medium: float | None
    humidity_high_high: float | None
    humidity_low_medium: float | None
    humidity_exempt: bool
    temp_exempt: bool = False


def _humidity_table_key(room_type: str) -> str:
    """Map a CONF_ROOM_TYPE value to a HUMIDITY_THRESHOLDS key.

    Unknown / missing → "normal" (matches _resolve_humidity_thresholds
    fallback in the safety coordinator).
    """
    if room_type in ("bathroom",):
        return "bathroom"
    if room_type in ("basement",):
        return "basement"
    if room_type == "outdoor":
        return "outdoor"
    return "normal"


def resolve_safety_bands(
    room_type: str | None,
    hass=None,
) -> SafetyBands:
    """Return the zone-chip safety bands for ``room_type``.

    Reads directly from the four production threshold tables so the chip
    inherits any tuning applied to the safety coordinator. Room types not
    modeled in the config-flow enum (or ``None``) fall back to ``generic``
    == the "normal" humidity table + default OVERHEAT/FREEZE rungs.

    Fix-up A-HIGH-1 (CM knob drift): when ``hass`` is passed AND the room
    type resolves to the ``normal`` humidity table, medium/high humidity
    bands are resolved LIVE via the SAME ``nm_cycle_a_knob`` calls the
    safety coordinator uses in ``_check_high_humidity_hazard`` (see
    safety.py:2073-2098) so an operator-tuned normal ladder cannot drift
    the chip vs the coordinator. ``hass=None`` falls back to the static
    table (test/unit path — CM knobs not reachable without hass).

    Special cases:
      * ``outdoor`` → both temp AND humidity exempt (sentinel bands).
      * ``garage`` → humidity exempt (garage RH tracks weather); temp
        bands default (105/115 high, 40/35 low).
    """
    rt = (room_type or "").strip().lower() or "generic"

    temp_high_medium = NUMERIC_THRESHOLDS[HazardType.OVERHEAT][ZONE_CHIP_TEMP_HIGH_RUNG]
    temp_high_low = NUMERIC_THRESHOLDS[HazardType.OVERHEAT][Severity.LOW]
    temp_low_medium = NUMERIC_THRESHOLDS[HazardType.FREEZE_RISK][ZONE_CHIP_TEMP_LOW_RUNG]
    temp_low_low = NUMERIC_THRESHOLDS[HazardType.FREEZE_RISK][Severity.LOW]
    low_hum_medium = LOW_HUMIDITY_THRESHOLDS[ZONE_CHIP_LOW_HUMIDITY_RUNG]

    # Outdoor: fully exempt on both axes.
    if rt == "outdoor":
        return SafetyBands(
            temp_high_medium=temp_high_medium,
            temp_high_low=temp_high_low,
            temp_low_medium=temp_low_medium,
            temp_low_low=temp_low_low,
            humidity_high_medium=None,
            humidity_high_high=None,
            humidity_low_medium=None,
            humidity_exempt=True,
            temp_exempt=True,
        )

    # Garage: humidity exempt; temp default.
    if rt == "garage":
        return SafetyBands(
            temp_high_medium=temp_high_medium,
            temp_high_low=temp_high_low,
            temp_low_medium=temp_low_medium,
            temp_low_low=temp_low_low,
            humidity_high_medium=None,
            humidity_high_high=None,
            humidity_low_medium=None,
            humidity_exempt=True,
        )

    hkey = _humidity_table_key(rt)
    htable = HUMIDITY_THRESHOLDS[hkey]
    hi_medium = htable[ZONE_CHIP_HUMIDITY_RUNG]
    hi_high = htable["high"]

    # A-HIGH-1: honor operator overrides on the "normal" ladder via the
    # SAME knob calls the safety coordinator uses. Only reachable when a
    # hass instance is threaded through (aggregation._evaluate does).
    if hass is not None and hkey == "normal":
        try:
            from ..const import (
                CONF_HUMIDITY_NORMAL_MEDIUM_PCT,
                CONF_HUMIDITY_NORMAL_HIGH_PCT,
                DEFAULT_HUMIDITY_NORMAL_MEDIUM_PCT,
                DEFAULT_HUMIDITY_NORMAL_HIGH_PCT,
            )
            from ._nm_cycle_a import nm_cycle_a_knob
            hi_medium = float(nm_cycle_a_knob(
                hass, CONF_HUMIDITY_NORMAL_MEDIUM_PCT,
                DEFAULT_HUMIDITY_NORMAL_MEDIUM_PCT,
            ))
            hi_high = float(nm_cycle_a_knob(
                hass, CONF_HUMIDITY_NORMAL_HIGH_PCT,
                DEFAULT_HUMIDITY_NORMAL_HIGH_PCT,
            ))
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "resolve_safety_bands: knob lookup failed — falling back "
                "to static HUMIDITY_THRESHOLDS['normal']", exc_info=True,
            )

    return SafetyBands(
        temp_high_medium=temp_high_medium,
        temp_high_low=temp_high_low,
        temp_low_medium=temp_low_medium,
        temp_low_low=temp_low_low,
        humidity_high_medium=hi_medium,
        humidity_high_high=hi_high,
        humidity_low_medium=low_hum_medium,
        humidity_exempt=False,
    )


@dataclass(frozen=True)
class ZoneChipRoomInput:
    """Per-room snapshot the zone chip needs to evaluate safety bands.

    Fields are already-materialized values, so the helper stays pure and
    is trivial to test without importing HA / aggregation.
    """

    room_name: str
    room_type: str
    temperature: float | None
    humidity: float | None
    leak_sensor_entity_id: str | None
    leak_is_on: bool
    leak_device_class: str | None


def evaluate_zone_chip(
    rooms: list[ZoneChipRoomInput],
    zone_is_outdoor: bool,
    hass=None,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Pure helper: given per-room inputs, return (tripping, comfort_drift).

    ``tripping`` is a list of ``(room_name, reason)`` sorted by room name.
    ``comfort_drift`` is a list of room names crossing the OLD chip lines
    (85/55 F, 70/25 %RH) but NOT the new safety-grade lines.

    Callers (aggregation.ZoneSafetyAlertSensor) resolve outdoor authority
    upstream (see ``outdoor_zone_names_snapshot``) and pass
    ``zone_is_outdoor=True`` to force every room to outdoor bands.
    """
    tripping: list[tuple[str, str]] = []
    comfort_drift: list[str] = []
    for r in rooms:
        room_type = "outdoor" if zone_is_outdoor else (r.room_type or "generic")
        bands = resolve_safety_bands(room_type, hass=hass)
        temp = r.temperature
        humidity = r.humidity

        # Safety-grade temperature.
        if temp is not None and not bands.temp_exempt:
            if temp > bands.temp_high_medium:
                tripping.append((
                    r.room_name,
                    f"temperature {temp:g}F > {bands.temp_high_medium:g}F",
                ))
            elif temp < bands.temp_low_medium:
                tripping.append((
                    r.room_name,
                    f"temperature {temp:g}F < {bands.temp_low_medium:g}F",
                ))

        # Safety-grade humidity.
        if humidity is not None and not bands.humidity_exempt:
            if (
                bands.humidity_high_medium is not None
                and humidity > bands.humidity_high_medium
            ):
                tripping.append((
                    r.room_name,
                    f"humidity {humidity:g}% > {bands.humidity_high_medium:g}%",
                ))
            elif (
                bands.humidity_low_medium is not None
                and humidity < bands.humidity_low_medium
            ):
                tripping.append((
                    r.room_name,
                    f"humidity {humidity:g}% < {bands.humidity_low_medium:g}%",
                ))

        # Comfort-drift (attribute-only).
        is_drift = False
        if not bands.temp_exempt and temp is not None:
            if (
                (temp > ZONE_CHIP_COMFORT_TEMP_HIGH and temp <= bands.temp_high_medium)
                or (temp < ZONE_CHIP_COMFORT_TEMP_LOW and temp >= bands.temp_low_medium)
            ):
                is_drift = True
        if not bands.humidity_exempt and humidity is not None:
            hi_gate = (
                bands.humidity_high_medium
                if bands.humidity_high_medium is not None
                else float("inf")
            )
            lo_gate = (
                bands.humidity_low_medium
                if bands.humidity_low_medium is not None
                else float("-inf")
            )
            if (
                (humidity > ZONE_CHIP_COMFORT_HUMIDITY_HIGH and humidity <= hi_gate)
                or (humidity < ZONE_CHIP_COMFORT_HUMIDITY_LOW and humidity >= lo_gate)
            ):
                is_drift = True
        if is_drift and r.room_name not in comfort_drift:
            comfort_drift.append(r.room_name)

        # Leak — always evaluated (no room-type gate). Empty-string CONF
        # is falsy — treated as absent. Require binary_sensor. prefix; if
        # the entity exposes a device_class, require moisture.
        eid = r.leak_sensor_entity_id
        if (
            eid
            and isinstance(eid, str)
            and eid.startswith("binary_sensor.")
            and r.leak_is_on
            and (r.leak_device_class in (None, "moisture"))
        ):
            tripping.append((r.room_name, "water leak detected"))

    tripping.sort(key=lambda rr: rr[0])
    comfort_drift = sorted(comfort_drift)
    return tripping, comfort_drift


def outdoor_zone_names_snapshot(hass) -> set[str]:
    """Module-level twin of SafetyCoordinator._outdoor_zone_names_snapshot.

    Used by the aggregation zone chip so it can honor the SAME outdoor
    authority (CONF_ZONE_IS_OUTDOOR) that the safety coordinator uses,
    without importing / instantiating the coordinator. Fails OPEN (empty
    set) on any registry / shape error.
    """
    outdoor: set[str] = set()
    try:
        from ..const import (
            CONF_ENTRY_TYPE,
            CONF_ZONE_IS_OUTDOOR,
            CONF_ZONE_NAME,
            DEFAULT_ZONE_IS_OUTDOOR,
            ENTRY_TYPE_ZONE,
            ENTRY_TYPE_ZONE_MANAGER,
        )
        for entry in hass.config_entries.async_entries(DOMAIN):
            etype = entry.data.get(CONF_ENTRY_TYPE)
            if etype == ENTRY_TYPE_ZONE:
                merged = {**entry.data, **entry.options}
                if merged.get(CONF_ZONE_IS_OUTDOOR, DEFAULT_ZONE_IS_OUTDOOR):
                    zname = merged.get(CONF_ZONE_NAME) or merged.get("zone_name")
                    if zname:
                        outdoor.add(zname)
            elif etype == ENTRY_TYPE_ZONE_MANAGER:
                merged = {**entry.data, **entry.options}
                zones = merged.get("zones") or {}
                if isinstance(zones, dict):
                    for zname, zcfg in zones.items():
                        if not isinstance(zcfg, dict):
                            continue
                        if zcfg.get(CONF_ZONE_IS_OUTDOOR, DEFAULT_ZONE_IS_OUTDOOR):
                            outdoor.add(zname)
    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "ZoneChip: outdoor zone snapshot failed — treating all zones "
            "as indoor (fail-open)",
            exc_info=True,
        )
        return set()
    return outdoor

# Light patterns by hazard type
LIGHT_PATTERNS: dict[str, dict[str, Any]] = {
    "fire": {"color": (255, 100, 0), "effect": "flash", "interval_ms": 250},
    "water_leak": {"color": (0, 0, 255), "effect": "pulse"},
    "co": {"color": (255, 100, 0), "effect": "flash", "interval_ms": 500},
    "freeze": {"color": (100, 150, 255), "effect": "pulse"},
    "warning": {"color": (255, 255, 0), "effect": "pulse"},
}

# Flooding escalation: sustained leak threshold
FLOODING_SUSTAINED_MINUTES = 15


# ============================================================================
# Rate of Change Detector
# ============================================================================


class RateOfChangeDetector:
    """Track sensor history and detect rapid changes with adaptive baselines.

    Stores last N readings per entity_id. Computes rate over a full 30-minute
    window (no extrapolation). Feeds each rate observation into a per-sensor
    MetricBaseline (Welford's algorithm) to learn normal noise levels.

    Once a baseline is established (>= RATE_MIN_SAMPLES), uses z-score to
    detect anomalous rates — automatically adapting to each sensor's noise
    profile. During learning, uses generous fixed thresholds (2x normal).

    Absolute safety thresholds (smoke, CO, freeze <=35F, overheat >=100F)
    are handled separately and fire immediately — rate detection is only
    for gradual drift (HVAC failure, slow overheat).
    """

    # Fixed thresholds used during learning period (2x generous)
    RATE_THRESHOLDS: dict[str, dict[str, Any]] = {
        "temperature_drop": {
            "rate": -10.0,  # 2x during learning (was -5.0)
            "hazard": HazardType.HVAC_FAILURE,
            "active_season": "heating",
        },
        "temperature_rise": {
            "rate": 10.0,  # 2x during learning (was 5.0)
            "hazard": HazardType.HVAC_FAILURE,
            "active_season": "cooling",
        },
        "temperature_rise_extreme": {
            "rate": 20.0,  # 2x during learning (was 10.0)
            "hazard": HazardType.OVERHEAT,
            "active_season": "any",
        },
        "humidity_rise": {
            "rate": 40.0,  # 2x during learning (was 20.0)
            "hazard": HazardType.WATER_LEAK,
            "active_season": "any",
            "exclude_room_types": ["bathroom"],
        },
    }

    # Window for rate calculation
    WINDOW_MINUTES = 30
    MAX_HISTORY = 60  # readings to keep per entity

    # v3.6.0.10: Adaptive rate-of-change constants
    MIN_WINDOW_SECONDS = 1800  # Full 30-min window, no extrapolation
    RATE_MIN_SAMPLES = 60      # ~30 min of observations before baseline active
    Z_RATE_ALERT = 3.0         # 3σ = statistically significant
    Z_RATE_HIGH = 4.0          # 4σ = very unusual
    Z_RATE_CRITICAL = 5.0      # 5σ = extreme

    def __init__(self) -> None:
        """Initialize the rate-of-change detector."""
        # entity_id -> deque of (datetime, float)
        self._history: dict[str, deque] = {}
        # v3.6.0.10: Per-sensor rate baselines for adaptive thresholds
        self._rate_baselines: dict[str, MetricBaseline] = {}

    def record(self, entity_id: str, timestamp: datetime, value: float) -> None:
        """Record a sensor reading."""
        if entity_id not in self._history:
            self._history[entity_id] = deque(maxlen=self.MAX_HISTORY)
        self._history[entity_id].append((timestamp, value))

    def get_rate(self, entity_id: str, now: datetime | None = None) -> float | None:
        """Calculate rate of change over the window period.

        Returns rate in units per 30 minutes, or None if insufficient data.
        v3.6.0.10: Requires full 30-minute window (MIN_WINDOW_SECONDS=1800)
        to eliminate noise from short-term extrapolation.
        """
        history = self._history.get(entity_id)
        if not history or len(history) < 2:
            return None

        if now is None:
            now = dt_util.utcnow()

        window_start = now - timedelta(minutes=self.WINDOW_MINUTES)

        # Find the oldest reading within the window
        oldest_in_window = None
        for ts, val in history:
            if ts >= window_start:
                oldest_in_window = (ts, val)
                break

        if oldest_in_window is None:
            return None

        # Get the most recent reading
        latest = history[-1]

        # Require full 30-min window to avoid extrapolating noise
        time_diff = (latest[0] - oldest_in_window[0]).total_seconds()
        if time_diff < self.MIN_WINDOW_SECONDS:
            return None

        # Rate per 30 minutes (actual delta, no extrapolation)
        value_diff = latest[1] - oldest_in_window[1]
        rate_per_second = value_diff / time_diff
        rate_per_30min = rate_per_second * (30 * 60)

        return rate_per_30min

    def _get_rate_baseline(self, entity_id: str) -> MetricBaseline:
        """Get or create a rate baseline for a sensor."""
        if entity_id not in self._rate_baselines:
            self._rate_baselines[entity_id] = MetricBaseline(
                metric_name=f"rate:{entity_id}",
                coordinator_id="safety",
                scope="rate_of_change",
            )
        return self._rate_baselines[entity_id]

    def _record_rate_baseline(self, entity_id: str, rate: float) -> None:
        """Feed a rate observation into the per-sensor baseline."""
        baseline = self._get_rate_baseline(entity_id)
        baseline.update(rate)

    def _z_score_severity(self, z: float) -> Severity | None:
        """Map z-score to severity level. Returns None if below alert threshold."""
        if z >= self.Z_RATE_CRITICAL:
            return Severity.CRITICAL
        elif z >= self.Z_RATE_HIGH:
            return Severity.HIGH
        elif z >= self.Z_RATE_ALERT:
            return Severity.MEDIUM
        return None

    def check_thresholds(
        self,
        entity_id: str,
        sensor_type: str,
        room_type: str = "normal",
        now: datetime | None = None,
    ) -> list[tuple[str, HazardType, float, Severity | None]]:
        """Check if rate of change is anomalous.

        v3.6.0.10: Two modes:
        - Learning (< RATE_MIN_SAMPLES): use generous fixed thresholds
        - Active baseline: use z-score for per-sensor adaptive detection

        Args:
            entity_id: The sensor entity ID.
            sensor_type: "temperature" or "humidity".
            room_type: Room type for exclusion checks.
            now: Current time (for testing).

        Returns:
            List of (threshold_name, hazard_type, rate, severity) tuples.
            severity is None for learning-mode detections (caller assigns MEDIUM).
        """
        if sensor_type not in ("temperature", "humidity"):
            return []

        rate = self.get_rate(entity_id, now)
        if rate is None:
            return []

        # Feed rate into per-sensor baseline (always, even during learning)
        self._record_rate_baseline(entity_id, rate)

        baseline = self._get_rate_baseline(entity_id)
        season = self._get_current_season(now)
        results = []

        if baseline.sample_count >= self.RATE_MIN_SAMPLES:
            # ── Active baseline: z-score detection ──
            z = baseline.z_score(rate)
            severity = self._z_score_severity(z)
            if severity is not None:
                # Determine hazard type from rate direction and sensor type
                hazard_type, name = self._classify_rate_hazard(
                    rate, sensor_type, season, room_type
                )
                if hazard_type is not None:
                    results.append((name, hazard_type, rate, severity))
        else:
            # ── Learning period: generous fixed thresholds ──
            for name, config in self.RATE_THRESHOLDS.items():
                if sensor_type == "temperature" and "temperature" not in name:
                    continue
                if sensor_type == "humidity" and "humidity" not in name:
                    continue

                active_season = config.get("active_season", "any")
                if active_season != "any" and not self._season_matches(
                    season, active_season
                ):
                    continue

                excluded = config.get("exclude_room_types", [])
                if room_type in excluded:
                    continue

                threshold_rate = config["rate"]
                if threshold_rate > 0 and rate >= threshold_rate:
                    results.append((name, config["hazard"], rate, None))
                elif threshold_rate < 0 and rate <= threshold_rate:
                    results.append((name, config["hazard"], rate, None))

        return results

    def _classify_rate_hazard(
        self,
        rate: float,
        sensor_type: str,
        season: str,
        room_type: str,
    ) -> tuple[HazardType | None, str]:
        """Classify an anomalous rate into a hazard type and name."""
        if sensor_type == "temperature":
            if rate > 0:
                # Rising temperature
                if rate >= 10.0:
                    return HazardType.OVERHEAT, "temperature_rise_extreme"
                if season != "heating" or season == "shoulder":
                    return HazardType.HVAC_FAILURE, "temperature_rise"
                return None, ""
            else:
                # Dropping temperature
                if season != "cooling" or season == "shoulder":
                    return HazardType.HVAC_FAILURE, "temperature_drop"
                return None, ""
        elif sensor_type == "humidity":
            if rate > 0 and room_type not in ("bathroom",):
                return HazardType.WATER_LEAK, "humidity_rise"
        return None, ""

    @staticmethod
    def _get_current_season(now: datetime | None = None) -> str:
        """Determine current season from date.

        Nov-Mar = 'heating', May-Sep = 'cooling', Apr+Oct = 'shoulder'.
        """
        if now is None:
            now = dt_util.now()
        month = now.month
        if month in (11, 12, 1, 2, 3):
            return "heating"
        elif month in (5, 6, 7, 8, 9):
            return "cooling"
        else:  # April, October
            return "shoulder"

    @staticmethod
    def _season_matches(current_season: str, active_season: str) -> bool:
        """Check if the current season matches the active season.

        Shoulder season matches both heating and cooling.
        """
        if active_season == "any":
            return True
        if current_season == "shoulder":
            return True  # Both directions active in shoulder season
        return current_season == active_season

    def get_baseline_summary(self) -> dict[str, Any]:
        """Return summary of all rate baselines for diagnostics."""
        summary: dict[str, Any] = {}
        for entity_id, baseline in self._rate_baselines.items():
            summary[entity_id] = {
                "mean": round(baseline.mean, 4),
                "std": round(baseline.std, 4),
                "sample_count": baseline.sample_count,
                "active": baseline.sample_count >= self.RATE_MIN_SAMPLES,
            }
        return summary

    def clear(self, entity_id: str | None = None) -> None:
        """Clear history for an entity or all entities."""
        if entity_id is not None:
            self._history.pop(entity_id, None)
        else:
            self._history.clear()


# ============================================================================
# Alert Deduplicator
# ============================================================================


class AlertDeduplicator:
    """Prevent alert fatigue with per-severity suppression windows.

    Tracks the last alert time per hazard key (type:location). A new
    alert is suppressed if it arrives within the suppression window
    for that severity level.
    """

    SUPPRESSION_WINDOWS: dict[Severity, timedelta] = {
        Severity.CRITICAL: timedelta(minutes=1),
        Severity.HIGH: timedelta(minutes=5),
        Severity.MEDIUM: timedelta(minutes=15),
        Severity.LOW: timedelta(hours=1),
    }

    def __init__(self) -> None:
        """Initialize the deduplicator."""
        # hazard_key -> last alert datetime
        self._last_alert: dict[str, datetime] = {}

    def should_alert(self, hazard: Hazard, now: datetime | None = None) -> bool:
        """Check if an alert should be sent for this hazard.

        Returns True if alert should proceed, False if suppressed.
        """
        if now is None:
            now = dt_util.utcnow()

        key = f"{hazard.type.value}:{hazard.location}"
        window = self.SUPPRESSION_WINDOWS.get(hazard.severity, timedelta(hours=1))

        last = self._last_alert.get(key)
        if last is not None and (now - last) < window:
            return False

        self._last_alert[key] = now
        return True

    def clear(self) -> None:
        """Clear all deduplication state."""
        self._last_alert.clear()


# ============================================================================
# Safety Coordinator
# ============================================================================


class SafetyCoordinator(BaseCoordinator):
    """Environmental hazard detection and response coordinator.

    Priority 100 (highest). Monitors smoke, CO, water leak, freeze risk,
    air quality, temperature extremes, and humidity. Can override all other
    coordinators during safety events.

    Sensor discovery:
    - Binary: smoke detectors, leak sensors (via entity registry area_id)
    - Numeric: CO, CO2, TVOC, temperature, humidity sensors

    Detection:
    - Binary hazards: immediate on state change
    - Numeric hazards: threshold-based severity classification
    - Rate-of-change: bidirectional, season-aware
    - Flooding escalation: multi-sensor or sustained >15min
    - Room-type humidity: normal/bathroom/basement thresholds

    Response:
    - CRITICAL: all lights 100%, notify all channels
    - HIGH: targeted response (HVAC override, valve close), notify
    - MEDIUM: request ventilation/dehumidification, notify
    - LOW: log only
    """

    COORDINATOR_ID = "safety"
    PRIORITY = 100

    # v3.6.0-c2.9: Anomaly detection metrics
    # v4.6.4 P2: dropped `hazard_trigger_frequency`. It was recorded as a constant
    # 1.0 per call (the comment said "Each trigger is a count observation"), so the
    # baseline mean converged to 1.0 with variance flooring to MIN_VARIANCE — every
    # observation matched the mean exactly → z=0 → NOMINAL severity → no emit ever
    # fired. Audit during v4.6.3.3 confirmed zero anomalies in production.
    # `active_hazard_count` has real variance (0..N) and is retained.
    SAFETY_METRICS = [
        "active_hazard_count",
    ]

    def __init__(
        self,
        hass: HomeAssistant,
        water_shutoff_valve: str | None = None,
        emergency_lights: list[str] | None = None,
    ) -> None:
        """Initialize the Safety Coordinator.

        Args:
            hass: Home Assistant instance.
            water_shutoff_valve: Optional valve entity to close on water leak.
            emergency_lights: Optional light entities for evacuation lighting.
        """
        super().__init__(
            hass,
            coordinator_id=self.COORDINATOR_ID,
            name="Safety Coordinator",
            priority=self.PRIORITY,
        )
        # v3.6.0-c2.1: Configurable entities from CM options
        self._water_shutoff_valve = water_shutoff_valve
        self._emergency_lights = emergency_lights or []

        # Active hazards: key="{type}:{location}" -> Hazard
        self._active_hazards: dict[str, Hazard] = {}
        # v4.0.11: Track occurrence count for repeated evaluations (like HA's "N occurrences")
        self._hazard_occurrences: dict[str, int] = {}
        self._deduplicator = AlertDeduplicator()
        self._rate_detector = RateOfChangeDetector()

        # Discovered sensors
        self._binary_sensors: dict[str, str] = {}  # entity_id -> hazard_type
        self._numeric_sensors: dict[str, str] = {}  # entity_id -> sensor_type
        self._sensor_locations: dict[str, str] = {}  # entity_id -> location
        self._sensor_room_types: dict[str, str] = {}  # entity_id -> room_type

        # Room mapping: room_name -> area_id
        self._room_area_ids: dict[str, str] = {}
        # Room types: room_name -> room_type
        self._room_types: dict[str, str] = {}

        # Leak tracking for flooding escalation
        self._leak_start_times: dict[str, datetime] = {}  # entity_id -> first leak time
        self._active_leak_sensors: set[str] = set()

        # Sustained humidity tracking: entity_id -> first_above_threshold_time
        self._humidity_above_since: dict[str, datetime] = {}
        # NM Cycle A A5: sustained TVOC tracking (mirrors humidity mechanism).
        self._tvoc_above_since: dict[str, datetime] = {}
        # v3.6.0-c2.6: Track whether we already fired a hazard for this sustained period
        # Prevents repeated hazard creation on every state change after window expires
        self._humidity_hazard_fired: set[str] = set()  # entity_ids with active fired hazard
        # NM Cycle A fix-up B-MED-1 / M2: swing has its OWN one-shot set so a
        # swing MEDIUM cannot mask a subsequent sustained HIGH on the same
        # entity, and the sustained else-branch's flag-discard cannot defeat
        # swing dedup while value is in [swing_floor, low).
        self._humidity_swing_fired: set[str] = set()

        # v3.6.0.8: Unit cache for temperature normalization
        self._sensor_units: dict[str, str] = {}  # entity_id -> unit_of_measurement

        # Observation mode: when True, hazard detection continues but no
        # actions are executed (NM alerts, service calls).  Controlled via
        # switch.ura_safety_observation_mode.
        self.observation_mode: bool = False

        # Diagnostics counters
        self._hazards_detected_24h: int = 0
        self._alerts_sent_24h: int = 0
        self._false_alarms_7d: int = 0
        self._total_hazards_7d: int = 0
        self._last_counter_reset: datetime | None = None
        self._response_times: list[float] = []  # seconds

        # v4.6.9 D5: Recent-events ring buffer — capped at 20 entries.
        # Bug Class #25 (bounded list): deque(maxlen=20) enforces the hard cap.
        # Each entry: { timestamp_iso, type, room, severity }
        # severity uses EventSeverity vocabulary (info|advisory|alert|critical).
        self._event_buffer: deque = deque(maxlen=20)

    @property
    def active_hazards(self) -> dict[str, Hazard]:
        """Return currently active hazards."""
        return dict(self._active_hazards)

    @property
    def sensors_monitored(self) -> int:
        """Return total number of monitored sensors."""
        return len(self._binary_sensors) + len(self._numeric_sensors)

    # =========================================================================
    # v4.6.9 D5: Recent-events ring buffer helpers
    # =========================================================================

    def _record_event(
        self,
        event_type: str,
        room: str | None,
        severity: Severity,
    ) -> None:
        """Append a safety event entry to the ring buffer.

        **Threading contract** (Tier 2-DB Reviewer A H1): MUST be called from
        the HA event loop. Do NOT invoke from a thread executor — deque mutation
        is safe under CPython's GIL but `get_recent_events()` snapshots via
        `list(buffer)` and a concurrent appender from a thread could observe
        a partial view. All current callers (`_respond_to_hazard`) are event-
        loop-bound.

        Bug Class #11: timestamp is UTC ISO 8601 string, never a datetime obj.
        Bug Class #22: severity converted via EventSeverity.from_severity() —
                       never redefine the vocabulary at call sites.
        Bug Class #25: deque(maxlen=20) enforces hard cap — no list growth.
        """
        entry: dict[str, Any] = {
            "timestamp_iso": dt_util.utcnow().isoformat(),
            "type": event_type,
            "room": room,
            "severity": EventSeverity.from_severity(severity).value,
        }
        self._event_buffer.append(entry)
        _LOGGER.debug(
            "Safety event recorded: type=%s room=%s severity=%s",
            event_type,
            room,
            entry["severity"],
        )

    def get_recent_events(self) -> dict[str, Any]:
        """Return recent-events data for the SafetyRecentEventsSensor.

        Returns a dict with:
          - events: list[dict] — last 20 events, newest first
          - count_24h: int — number of events in the last 24h
          - last_event_at_iso: str | None — timestamp of most recent entry
          - severity_breakdown: dict with exactly 4 int keys
            (info, advisory, alert, critical)

        Bug Class #29: covers empty-buffer branch (count_24h=0, empty list).
        Bug Class #37: stable shape — all four keys always present.
        Bug Class #25: list length capped at 20 by deque(maxlen=20).
        """
        # Stable empty shape — returned whenever buffer is empty
        _empty_breakdown: dict[str, int] = {
            "info": 0,
            "advisory": 0,
            "alert": 0,
            "critical": 0,
        }

        all_entries = list(self._event_buffer)  # oldest → newest
        newest_first = list(reversed(all_entries))

        if not newest_first:
            return {
                "events": [],
                "count_24h": 0,
                "last_event_at_iso": None,
                "severity_breakdown": dict(_empty_breakdown),
            }

        cutoff = dt_util.utcnow() - timedelta(hours=24)
        count_24h = 0
        breakdown: dict[str, int] = dict(_empty_breakdown)

        # Tier 2-DB Reviewer A H2 fix: import at function top, not loop body.
        from datetime import timezone as _tz

        for entry in all_entries:
            try:
                ts = datetime.fromisoformat(entry["timestamp_iso"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=_tz.utc)
                if ts >= cutoff:
                    count_24h += 1
                    sev_key = entry.get("severity", "info")
                    if sev_key in breakdown:
                        breakdown[sev_key] += 1
            except Exception:
                pass

        last_event_at_iso: str | None = (
            newest_first[0].get("timestamp_iso") if newest_first else None
        )

        return {
            "events": newest_first,
            "count_24h": count_24h,
            "last_event_at_iso": last_event_at_iso,
            "severity_breakdown": breakdown,
        }

    # =========================================================================
    # Setup
    # =========================================================================

    async def async_setup(self) -> None:
        """Set up the Safety Coordinator.

        Discovers safety-related sensors via entity registry area_id mapping,
        then subscribes to state changes.
        """
        # v3.6.0.3: Instantiate anomaly detector FIRST so it's always
        # available even if discovery fails.
        # v4.6.3 D10: Read sensitivity bucket from CM entry options.
        from .coordinator_diagnostics import AnomalyDetector
        from ..const import (  # noqa: PLC0415
            CONF_SAFETY_ANOMALY_SENSITIVITY,
            DEFAULT_ANOMALY_SENSITIVITY,
            ANOMALY_SENSITIVITY_MULTIPLIERS,
            ENTRY_TYPE_COORDINATOR_MANAGER,
        )
        _sensitivity_bucket = DEFAULT_ANOMALY_SENSITIVITY
        try:
            for _ce in self.hass.config_entries.async_entries(DOMAIN):
                if _ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                    _sensitivity_bucket = {**_ce.data, **_ce.options}.get(
                        CONF_SAFETY_ANOMALY_SENSITIVITY, DEFAULT_ANOMALY_SENSITIVITY
                    )
                    break
        except Exception:
            pass
        _sensitivity_mult = ANOMALY_SENSITIVITY_MULTIPLIERS.get(_sensitivity_bucket, 1.0)
        self.anomaly_detector = AnomalyDetector(
            hass=self.hass,
            coordinator_id="safety",
            metric_names=self.SAFETY_METRICS,
            minimum_samples=720,
            sensitivity_multiplier=_sensitivity_mult,
            # v4.6.5.3 surface fix (set is empty today — active_hazard_count wired)
            suppressed_metric_names=SAFETY_SUPPRESSED_FROM_PERSISTENCE,
        )
        try:
            await self.anomaly_detector.load_baselines()
        except Exception:
            _LOGGER.debug("Could not load safety anomaly baselines", exc_info=True)

        # v3.6.0.10: Load rate baselines from anomaly detector's SQLite store.
        # Rate baselines are stored with coordinator_id="safety_rate" to
        # distinguish from the anomaly detector's own baselines.
        try:
            await self._load_rate_baselines()
        except Exception:
            _LOGGER.debug("Could not load rate baselines", exc_info=True)

        # v3.6.0.3: Wrap discovery/subscription in try/except so partial
        # failures don't prevent the coordinator from functioning.
        try:
            self._build_room_mappings()
            self._discover_sensors()
            self._subscribe_to_sensors()

            # Periodic check for sustained conditions (flooding, humidity)
            unsub = async_track_time_interval(
                self.hass, self._async_periodic_check, timedelta(minutes=1)
            )
            self._unsub_listeners.append(unsub)

            # v3.6.0.10: Periodic save of rate baselines (every 30 min)
            unsub_save = async_track_time_interval(
                self.hass, self._async_save_rate_baselines, timedelta(minutes=30)
            )
            self._unsub_listeners.append(unsub_save)
        except Exception:
            _LOGGER.exception("Error during safety discovery (non-fatal)")

        _LOGGER.info(
            "Safety Coordinator set up: %d binary sensors, %d numeric sensors",
            len(self._binary_sensors),
            len(self._numeric_sensors),
        )

    def _build_room_mappings(self) -> None:
        """Build room_name -> area_id and room_name -> room_type mappings."""
        try:
            for config_entry in self.hass.config_entries.async_entries(DOMAIN):
                if config_entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                    continue
                merged = {**config_entry.data, **config_entry.options}
                room_name = merged.get(CONF_ROOM_NAME, "")
                area_id = merged.get(CONF_AREA_ID, "")
                room_type = merged.get(CONF_ROOM_TYPE, "generic")
                if room_name:
                    if area_id:
                        self._room_area_ids[room_name] = area_id
                    self._room_types[room_name] = room_type
        except Exception:
            _LOGGER.debug("Could not build room mappings", exc_info=True)

    def _outdoor_zone_names_snapshot(self) -> set[str]:
        """NM Cycle A H1 / B-HIGH-1: snapshot of zone_names flagged outdoor.

        Mirrors PresenceCoordinator._outdoor_zone_names_snapshot
        (presence.py:1508). Reads both legacy ENTRY_TYPE_ZONE entries and
        modern Zone Manager `zones` dict. Fails OPEN (empty set) on any
        registry / shape error — safety-humidity treats every room as
        indoor, which is the pre-fix behavior (no regression).

        Fix-up B-H3: delegates to the module-level ``outdoor_zone_names_snapshot``
        so the zone chip (aggregation) and the coordinator share ONE
        implementation — no drift risk.
        """
        return outdoor_zone_names_snapshot(self.hass)

    def _discover_sensors(self) -> None:
        """Discover safety sensors from URA room configs + SC global config.

        v3.6.0.7: Config-first discovery. Instead of scanning the entire
        entity registry and filtering inward, we start from the EXACT
        sensors the user configured:

        Source 1: URA room config entries — temperature_sensor,
                  humidity_sensor, water_leak_sensor per room.
                  We KNOW what type each sensor is from the config key.

        Source 2: SC global config — 5 explicit sensor lists for devices
                  not in any URA room.

        No entity registry scanning. No device_class guessing. No
        appliance filtering needed because the user already curated
        the sensor list.
        """
        from ..const import (
            CONF_TEMPERATURE_SENSOR,
            CONF_HUMIDITY_SENSOR, CONF_WATER_LEAK_SENSOR,
            CONF_GLOBAL_SMOKE_SENSORS, CONF_GLOBAL_LEAK_SENSORS,
            CONF_GLOBAL_AQ_SENSORS, CONF_GLOBAL_TEMP_SENSORS,
            CONF_GLOBAL_HUMIDITY_SENSORS, ENTRY_TYPE_COORDINATOR_MANAGER,
        )

        # NM Cycle A A5: safety-discovery blocklist. Mechanism is rung-1;
        # contents are rung-2-ready (CONF_SAFETY_DISCOVERY_BLOCKLIST) so
        # other households can exclude their own oddball sensors without a
        # code change. Applied uniformly to both room-config and global-
        # config discovery paths below.
        from ..const import (
            CONF_SAFETY_DISCOVERY_BLOCKLIST,
            DEFAULT_SAFETY_DISCOVERY_BLOCKLIST,
        )
        from ._nm_cycle_a import nm_cycle_a_knob
        blocklist_seq = nm_cycle_a_knob(
            self.hass,
            CONF_SAFETY_DISCOVERY_BLOCKLIST,
            DEFAULT_SAFETY_DISCOVERY_BLOCKLIST,
        )
        blocklist: set[str] = set(blocklist_seq) if blocklist_seq else set()
        if blocklist:
            _LOGGER.info(
                "Safety discovery: blocklist active (%d entries): %s",
                len(blocklist), sorted(blocklist),
            )
        # Pre-seed `seen_entity_ids` with the blocklist so ALL downstream
        # discovery loops skip them uniformly (both `if temp_id not in
        # seen_entity_ids` and the global-loop `if entity_id in
        # seen_entity_ids: continue` short-circuits).
        seen_entity_ids: set[str] = set(blocklist)
        room_count = 0

        # NM Cycle A fix-up H1 / B-HIGH-1: derive outdoor classification from
        # the zone's CONF_ZONE_IS_OUTDOOR flag (const.py:72, shipped v5.7.0).
        # The prior `room_type == "outdoor"` early-return in _handle_humidity
        # was dead: CONF_ROOM_TYPE's config-flow SelectSelector has no
        # "outdoor" option, so `_sensor_room_types[eid]` could never hold
        # that value. This mirrors PresenceCoordinator._outdoor_zone_names_snapshot
        # (presence.py:1508) — same authority, no new operator surface.
        outdoor_zone_names = self._outdoor_zone_names_snapshot()

        # ── Source 1: URA room-configured sensors ──
        for config_entry in self.hass.config_entries.async_entries(DOMAIN):
            if config_entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            merged = {**config_entry.data, **config_entry.options}
            room_name = merged.get(CONF_ROOM_NAME, "")
            room_type = merged.get(CONF_ROOM_TYPE, "generic")
            if not room_name:
                continue
            # H1: override to "outdoor" for rooms whose zone is flagged outdoor.
            from ..const import CONF_ZONE as _CONF_ZONE
            room_zone = merged.get(_CONF_ZONE) or ""
            if room_zone and room_zone in outdoor_zone_names:
                room_type = "outdoor"

            # Temperature sensor — configured by user for this room
            temp_id = merged.get(CONF_TEMPERATURE_SENSOR)
            if temp_id and temp_id not in seen_entity_ids:
                self._numeric_sensors[temp_id] = "temperature"
                self._sensor_locations[temp_id] = room_name
                self._sensor_room_types[temp_id] = room_type
                seen_entity_ids.add(temp_id)

            # Humidity sensor
            hum_id = merged.get(CONF_HUMIDITY_SENSOR)
            if hum_id and hum_id not in seen_entity_ids:
                self._numeric_sensors[hum_id] = "humidity"
                self._sensor_locations[hum_id] = room_name
                self._sensor_room_types[hum_id] = room_type
                seen_entity_ids.add(hum_id)

            # Water leak sensor
            leak_id = merged.get(CONF_WATER_LEAK_SENSOR)
            if leak_id and leak_id not in seen_entity_ids:
                self._binary_sensors[leak_id] = HazardType.WATER_LEAK
                self._sensor_locations[leak_id] = room_name
                self._sensor_room_types[leak_id] = room_type
                seen_entity_ids.add(leak_id)

            room_count += 1

        # ── Source 2: SC global config sensors ──
        # These are explicitly added by the user for devices not in any
        # URA room (attic smoke detector, water main leak sensor, etc.)
        global_count = 0
        for config_entry in self.hass.config_entries.async_entries(DOMAIN):
            if config_entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COORDINATOR_MANAGER:
                continue
            merged = {**config_entry.data, **config_entry.options}

            # Map: config key -> (sensor_type_or_hazard, is_binary)
            GLOBAL_KEYS = {
                CONF_GLOBAL_SMOKE_SENSORS: (HazardType.SMOKE, True),
                CONF_GLOBAL_LEAK_SENSORS: (HazardType.WATER_LEAK, True),
                CONF_GLOBAL_AQ_SENSORS: ("aq", False),
                CONF_GLOBAL_TEMP_SENSORS: ("temperature", False),
                CONF_GLOBAL_HUMIDITY_SENSORS: ("humidity", False),
            }
            for key, (sensor_info, is_binary) in GLOBAL_KEYS.items():
                vals = merged.get(key, [])
                if isinstance(vals, str) and vals:
                    vals = [vals]
                if not isinstance(vals, list):
                    continue
                for entity_id in vals:
                    if entity_id in seen_entity_ids:
                        continue  # Room config takes precedence
                    location = self._resolve_global_location(entity_id)
                    if is_binary:
                        self._binary_sensors[entity_id] = sensor_info
                    else:
                        # For AQ, classify by device_class
                        if sensor_info == "aq":
                            aq_type = self._classify_aq_sensor(entity_id)
                            self._numeric_sensors[entity_id] = aq_type
                        else:
                            self._numeric_sensors[entity_id] = sensor_info
                    self._sensor_locations[entity_id] = location
                    self._sensor_room_types[entity_id] = "normal"
                    seen_entity_ids.add(entity_id)
                    global_count += 1

        _LOGGER.info(
            "Safety sensor discovery: %d rooms, %d global, %d total "
            "(%d binary, %d numeric)",
            room_count,
            global_count,
            len(seen_entity_ids),
            len(self._binary_sensors),
            len(self._numeric_sensors),
        )

    def _resolve_global_location(self, entity_id: str) -> str:
        """Resolve location for a global sensor via device area_id.

        v3.6.0.7: Maps global sensors back to rooms when possible.
        """
        try:
            from homeassistant.helpers import entity_registry as er
            from homeassistant.helpers import device_registry as dr
            ent_reg = er.async_get(self.hass)
            dev_reg = dr.async_get(self.hass)

            entity = ent_reg.entities.get(entity_id)
            if not entity:
                return self._location_from_entity_id(entity_id)

            # Check entity area, then device area
            area_id = getattr(entity, "area_id", None)
            if not area_id:
                device_id = getattr(entity, "device_id", None)
                if device_id:
                    device = dev_reg.async_get(device_id)
                    if device:
                        area_id = device.area_id

            # Map area_id to URA room name
            if area_id:
                for room_name, room_area_id in self._room_area_ids.items():
                    if room_area_id == area_id:
                        return room_name

            return self._location_from_entity_id(entity_id)
        except Exception:
            return self._location_from_entity_id(entity_id)

    def _classify_aq_sensor(self, entity_id: str) -> str:
        """Classify an AQ sensor as co, co2, or tvoc by device_class.

        v3.6.0.7: For global AQ sensors, determine the specific type.
        """
        try:
            from homeassistant.helpers import entity_registry as er
            ent_reg = er.async_get(self.hass)
            entity = ent_reg.entities.get(entity_id)
            if entity:
                dc = (
                    getattr(entity, "device_class", None)
                    or getattr(entity, "original_device_class", None)
                    or ""
                ).lower()
                if dc == "carbon_monoxide":
                    return "co"
                elif dc == "carbon_dioxide":
                    return "co2"
                elif dc in ("volatile_organic_compounds", "volatile_organic_compounds_parts"):
                    return "tvoc"
        except Exception:
            pass
        # Fallback: guess from entity_id
        eid = entity_id.lower()
        if "co2" in eid or "carbon_dioxide" in eid:
            return "co2"
        elif "tvoc" in eid or "voc" in eid:
            return "tvoc"
        return "co"

    @staticmethod
    def _location_from_entity_id(entity_id: str) -> str:
        """Extract a location hint from an entity ID."""
        # binary_sensor.kitchen_smoke -> kitchen
        parts = entity_id.split(".", 1)
        if len(parts) < 2:
            return "unknown"
        name = parts[1]
        # Strip common suffixes
        for suffix in (
            "_smoke", "_leak", "_water_leak", "_carbon_monoxide",
            "_co2", "_tvoc", "_temperature", "_temp", "_humidity",
            "_co_level", "_volatile",
        ):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        return name.replace("_", " ").title() if name else "unknown"

    def _subscribe_to_sensors(self) -> None:
        """Subscribe to state changes for all discovered sensors."""
        all_entity_ids = list(self._binary_sensors.keys()) + list(
            self._numeric_sensors.keys()
        )
        if not all_entity_ids:
            return

        unsub = async_track_state_change_event(
            self.hass, all_entity_ids, self._async_sensor_state_changed
        )
        self._unsub_listeners.append(unsub)

    # =========================================================================
    # State change handler
    # =========================================================================

    @callback
    def _async_sensor_state_changed(self, event: Any) -> None:
        """Handle safety sensor state change."""
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        state_value = new_state.state
        if state_value in _UNAVAILABLE_STATES:
            return

        # v3.6.0.8: If the sensor was previously unavailable/unknown,
        # clear its rate history to prevent false rate-of-change spikes
        # from the unavailable→valid transition (e.g., after HA restart).
        old_state = event.data.get("old_state")
        if old_state is not None and old_state.state in _UNAVAILABLE_STATES:
            self._rate_detector.clear(entity_id)
            # v3.21.0 D3: Re-evaluate hazard state on recovery transition.
            # If the sensor was in a hazard state before going unavailable,
            # the hazard stays in _active_hazards. Check current reading
            # immediately (synchronous) to clear stale hazards or confirm
            # the hazard persists.
            self._evaluate_sensor_on_recovery(entity_id, state_value)

        # Queue an intent for this sensor change
        from .base import Intent

        intent = Intent(
            source="state_change",
            entity_id=entity_id,
            data={
                "state": state_value,
                "old_state": getattr(
                    event.data.get("old_state"), "state", None
                ),
            },
            coordinator_id=self.COORDINATOR_ID,
        )

        # Get the coordinator manager and queue the intent
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is not None:
            manager.queue_intent(intent)

    def _evaluate_sensor_on_recovery(
        self, entity_id: str, state_value: str
    ) -> None:
        """Re-evaluate a sensor immediately on unavailable→available transition.

        v3.21.0 D3: Synchronous hazard state check so stale hazards are cleared
        (or confirmed) without waiting for the async intent pipeline.

        Binary sensors: call _handle_binary_hazard to clear or re-raise.
        Numeric sensors: call _handle_numeric_hazard / _handle_temperature /
        _handle_humidity to update _active_hazards.
        """
        if entity_id in self._binary_sensors:
            hazard_type = self._binary_sensors[entity_id]
            self._handle_binary_hazard(entity_id, state_value, hazard_type)
            return

        if entity_id in self._numeric_sensors:
            try:
                value = float(state_value)
            except (ValueError, TypeError):
                return

            sensor_type = self._numeric_sensors[entity_id]

            # Normalize temperature if needed
            if sensor_type == "temperature":
                value = self._normalize_temperature(entity_id, value)

            if sensor_type == "co":
                self._handle_numeric_hazard(
                    entity_id, value, HazardType.CARBON_MONOXIDE
                )
            elif sensor_type == "co2":
                self._handle_numeric_hazard(
                    entity_id, value, HazardType.HIGH_CO2
                )
            elif sensor_type == "tvoc":
                self._handle_numeric_hazard(
                    entity_id, value, HazardType.HIGH_TVOC
                )
            elif sensor_type == "temperature":
                self._handle_temperature(entity_id, value, dt_util.utcnow())
            elif sensor_type == "humidity":
                self._handle_humidity(entity_id, value, dt_util.utcnow())

    # =========================================================================
    # Evaluate
    # =========================================================================

    async def evaluate(
        self,
        intents: list[Intent],
        context: dict[str, Any],
    ) -> list[CoordinatorAction]:
        """Evaluate safety intents and return proposed actions."""
        if not self._enabled:
            return []

        actions: list[CoordinatorAction] = []

        for intent in intents:
            entity_id = intent.entity_id
            state_value = intent.data.get("state", "")

            hazards = await self._process_sensor(entity_id, state_value)
            for hazard in hazards:
                response_actions = await self._respond_to_hazard(hazard)
                actions.extend(response_actions)

        return actions

    async def _process_sensor(
        self, entity_id: str, state_value: str
    ) -> list[Hazard]:
        """Process a sensor state change and return any detected hazards."""
        hazards: list[Hazard] = []

        # Binary sensor handling
        if entity_id in self._binary_sensors:
            hazard = self._handle_binary_hazard(
                entity_id,
                state_value,
                self._binary_sensors[entity_id],
            )
            if hazard is not None:
                hazards.append(hazard)

        # Numeric sensor handling
        elif entity_id in self._numeric_sensors:
            try:
                value = float(state_value)
            except (ValueError, TypeError):
                return hazards

            sensor_type = self._numeric_sensors[entity_id]
            now = dt_util.utcnow()

            # v3.6.0.8: Normalize temperature to Fahrenheit.
            # Thresholds are in °F but sensors may report °C.
            # Check the entity's unit_of_measurement attribute.
            if sensor_type == "temperature":
                value = self._normalize_temperature(entity_id, value)

            # Record for rate-of-change detection (after normalization)
            self._rate_detector.record(entity_id, now, value)

            # Check numeric thresholds
            if sensor_type == "co":
                hazard = self._handle_numeric_hazard(
                    entity_id, value, HazardType.CARBON_MONOXIDE
                )
                if hazard is not None:
                    hazards.append(hazard)

            elif sensor_type == "co2":
                hazard = self._handle_numeric_hazard(
                    entity_id, value, HazardType.HIGH_CO2
                )
                if hazard is not None:
                    hazards.append(hazard)

            elif sensor_type == "tvoc":
                hazard = self._handle_numeric_hazard(
                    entity_id, value, HazardType.HIGH_TVOC
                )
                if hazard is not None:
                    hazards.append(hazard)

            elif sensor_type == "temperature":
                temp_hazards = self._handle_temperature(entity_id, value, now)
                hazards.extend(temp_hazards)

            elif sensor_type == "humidity":
                humidity_hazards = self._handle_humidity(entity_id, value, now)
                hazards.extend(humidity_hazards)

            # Check rate-of-change thresholds (adaptive baselines)
            room_type = self._sensor_room_types.get(entity_id, "normal")
            roc_results = self._rate_detector.check_thresholds(
                entity_id, sensor_type, room_type, now
            )
            for name, hazard_type, rate, roc_severity in roc_results:
                location = self._sensor_locations.get(entity_id, "unknown")
                # Use z-score severity if available, otherwise MEDIUM for learning-mode
                effective_severity = roc_severity if roc_severity is not None else Severity.MEDIUM
                # Build threshold description
                baseline = self._rate_detector._get_rate_baseline(entity_id)
                if baseline.sample_count >= self._rate_detector.RATE_MIN_SAMPLES:
                    z = baseline.z_score(rate)
                    threshold_desc = f"z={z:.1f}σ (mean={baseline.mean:.2f}, std={baseline.std:.2f})"
                else:
                    threshold_desc = f"fixed={self._rate_detector.RATE_THRESHOLDS.get(name, {}).get('rate', '?')} (learning: {baseline.sample_count}/{self._rate_detector.RATE_MIN_SAMPLES})"
                hazard = Hazard(
                    type=hazard_type,
                    severity=effective_severity,
                    confidence=0.75,
                    location=location,
                    sensor_id=entity_id,
                    value=rate,
                    threshold=threshold_desc,
                    detected_at=now,
                    message=(
                        f"Rapid {sensor_type} change in {location}: "
                        f"{rate:.1f}/30min ({threshold_desc})"
                    ),
                )
                hazards.append(hazard)

        return hazards

    # =========================================================================
    # Binary hazard handling
    # =========================================================================

    def _handle_binary_hazard(
        self,
        entity_id: str,
        new_state: str,
        hazard_type: str,
    ) -> Hazard | None:
        """Handle a binary sensor state change (smoke, leak)."""
        location = self._sensor_locations.get(entity_id, "unknown")

        if new_state != "on":
            # Hazard cleared
            key = f"{hazard_type}:{location}"
            self._active_hazards.pop(key, None)
            self._hazard_occurrences.pop(key, None)
            # Clear leak tracking
            if hazard_type == HazardType.WATER_LEAK:
                self._leak_start_times.pop(entity_id, None)
                self._active_leak_sensors.discard(entity_id)
            # v3.6.0.3: Push entity updates on hazard clear
            self._notify_entity_update()
            return None

        now = dt_util.utcnow()

        if hazard_type == HazardType.SMOKE:
            severity = Severity.CRITICAL
            message = f"SMOKE DETECTED in {location}!"
            confidence = 0.95
        elif hazard_type == HazardType.WATER_LEAK:
            severity = Severity.HIGH
            message = f"Water leak detected in {location}!"
            confidence = 0.95
            # Track leak start for flooding escalation
            if entity_id not in self._leak_start_times:
                self._leak_start_times[entity_id] = now
            self._active_leak_sensors.add(entity_id)
            # Check flooding escalation
            flooding = self._check_flooding_escalation(now)
            if flooding is not None:
                return flooding
        else:
            severity = Severity.HIGH
            message = f"Hazard: {hazard_type} in {location}"
            confidence = 0.90

        return Hazard(
            type=HazardType(hazard_type),
            severity=severity,
            confidence=confidence,
            location=location,
            sensor_id=entity_id,
            value="on",
            threshold="on",
            detected_at=now,
            message=message,
        )

    def _check_flooding_escalation(self, now: datetime) -> Hazard | None:
        """Check if water leak should be escalated to flooding.

        Escalation triggers:
        1. Multiple leak sensors active simultaneously
        2. Single sensor active for >15 minutes
        """
        # Multi-sensor escalation
        if len(self._active_leak_sensors) >= 2:
            locations = [
                self._sensor_locations.get(eid, "unknown")
                for eid in self._active_leak_sensors
            ]
            return Hazard(
                type=HazardType.FLOODING,
                severity=Severity.CRITICAL,
                confidence=0.95,
                location=", ".join(set(locations)),
                sensor_id=",".join(self._active_leak_sensors),
                value="multiple_sensors",
                threshold="2+ sensors",
                detected_at=now,
                message=(
                    f"FLOODING: Multiple water leak sensors active in "
                    f"{', '.join(set(locations))}!"
                ),
            )

        # Sustained single sensor escalation
        for sensor_id, start_time in self._leak_start_times.items():
            if sensor_id in self._active_leak_sensors:
                duration = (now - start_time).total_seconds() / 60.0
                if duration >= FLOODING_SUSTAINED_MINUTES:
                    location = self._sensor_locations.get(sensor_id, "unknown")
                    return Hazard(
                        type=HazardType.FLOODING,
                        severity=Severity.CRITICAL,
                        confidence=0.90,
                        location=location,
                        sensor_id=sensor_id,
                        value=f"{duration:.0f} minutes",
                        threshold=f"{FLOODING_SUSTAINED_MINUTES} minutes",
                        detected_at=now,
                        message=(
                            f"FLOODING: Sustained water leak in {location} "
                            f"for {duration:.0f} minutes!"
                        ),
                    )

        return None

    # =========================================================================
    # Numeric hazard handling
    # =========================================================================

    def _handle_numeric_hazard(
        self,
        entity_id: str,
        value: float,
        hazard_type: HazardType,
    ) -> Hazard | None:
        """Handle a numeric sensor exceeding thresholds."""
        # NM Cycle A A5: CO2 LOW is log-only (occupied-room noise floor).
        # Runtime knob CONF_CO2_LOG_ONLY_CEILING_PPM adjusts the LOW ceiling.
        if hazard_type == HazardType.HIGH_CO2:
            from ..const import (
                CONF_CO2_LOG_ONLY_CEILING_PPM,
                DEFAULT_CO2_LOG_ONLY_CEILING_PPM,
            )
            from ._nm_cycle_a import nm_cycle_a_knob
            co2_low = float(nm_cycle_a_knob(
                self.hass, CONF_CO2_LOG_ONLY_CEILING_PPM,
                DEFAULT_CO2_LOG_ONLY_CEILING_PPM,
            ))
            # Substitute the LOW threshold with the operator-tunable ceiling.
            # If value is below MEDIUM but above co2_low, it's log-only.
            # Fix-up L5: read MEDIUM from NUMERIC_THRESHOLDS (single source of truth).
            co2_medium = NUMERIC_THRESHOLDS[HazardType.HIGH_CO2][Severity.MEDIUM]
            if value < co2_medium and value >= co2_low:
                location = self._sensor_locations.get(entity_id, "unknown")
                _LOGGER.info(
                    "CO2 log-only rung: %s at %s ppm (below MEDIUM 1500)",
                    location, value,
                )
                # Clear any stale LOW hazard so a resolved bump doesn't linger.
                key = f"{hazard_type}:{location}"
                self._active_hazards.pop(key, None)
                return None
        # NM Cycle A A5: TVOC sustained-30min-or-1500 gating.
        if hazard_type == HazardType.HIGH_TVOC:
            from ..const import (
                CONF_TVOC_ABSOLUTE_HIGH_PPB,
                CONF_TVOC_SUSTAINED_S,
                DEFAULT_TVOC_ABSOLUTE_HIGH_PPB,
                DEFAULT_TVOC_SUSTAINED_S,
            )
            from ._nm_cycle_a import nm_cycle_a_knob
            abs_high = float(nm_cycle_a_knob(
                self.hass, CONF_TVOC_ABSOLUTE_HIGH_PPB,
                DEFAULT_TVOC_ABSOLUTE_HIGH_PPB,
            ))
            sustained_s = float(nm_cycle_a_knob(
                self.hass, CONF_TVOC_SUSTAINED_S,
                DEFAULT_TVOC_SUSTAINED_S,
            ))
            medium_thresh = NUMERIC_THRESHOLDS[HazardType.HIGH_TVOC][Severity.MEDIUM]
            now_ts = dt_util.utcnow()
            # Absolute HIGH bypass — immediate fire.
            if value >= abs_high:
                pass  # fall through to normal severity classification
            elif value >= medium_thresh:
                # Start / continue sustained-above-MEDIUM tracking.
                first_at = self._tvoc_above_since.get(entity_id)
                if first_at is None:
                    self._tvoc_above_since[entity_id] = now_ts
                    return None  # hold — not yet sustained
                elapsed = (now_ts - first_at).total_seconds()
                if elapsed < sustained_s:
                    return None  # still within grace window
                # Sustained — proceed as HIGH severity.
            else:
                # Below MEDIUM — clear sustained tracker.
                self._tvoc_above_since.pop(entity_id, None)
        severity = self._classify_severity(hazard_type, value)
        if severity is None:
            # Below all thresholds — clear any active hazard
            location = self._sensor_locations.get(entity_id, "unknown")
            key = f"{hazard_type}:{location}"
            self._active_hazards.pop(key, None)
            self._hazard_occurrences.pop(key, None)
            # v3.6.0.3: Push entity updates on hazard clear
            self._notify_entity_update()
            return None

        location = self._sensor_locations.get(entity_id, "unknown")
        threshold = self._get_threshold(hazard_type, severity)

        messages: dict[HazardType, str] = {
            HazardType.CARBON_MONOXIDE: f"CO {value} ppm in {location}",
            HazardType.HIGH_CO2: f"High CO2 ({value} ppm) in {location}",
            HazardType.HIGH_TVOC: f"High TVOC ({value} ppb) in {location}",
        }

        return Hazard(
            type=hazard_type,
            severity=severity,
            confidence=0.85,
            location=location,
            sensor_id=entity_id,
            value=value,
            threshold=threshold,
            detected_at=dt_util.utcnow(),
            message=messages.get(hazard_type, f"{hazard_type.value}: {value}"),
        )

    @staticmethod
    def _classify_severity(hazard_type: HazardType, value: float) -> Severity | None:
        """Classify severity for a numeric sensor value.

        For FREEZE_RISK: lower value = worse (check <=).
        For everything else: higher value = worse (check >=).
        """
        thresholds = NUMERIC_THRESHOLDS.get(hazard_type)
        if thresholds is None:
            return None

        if hazard_type == HazardType.FREEZE_RISK:
            # Lower is worse
            for sev in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW):
                if sev in thresholds and value <= thresholds[sev]:
                    return sev
        else:
            # Higher is worse
            for sev in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW):
                if sev in thresholds and value >= thresholds[sev]:
                    return sev

        return None

    @staticmethod
    def _get_threshold(hazard_type: HazardType, severity: Severity) -> float | None:
        """Get the threshold value for a hazard type and severity."""
        thresholds = NUMERIC_THRESHOLDS.get(hazard_type)
        if thresholds is None:
            return None
        return thresholds.get(severity)

    # =========================================================================
    # Unit normalization
    # =========================================================================

    def _normalize_temperature(self, entity_id: str, value: float) -> float:
        """Normalize temperature to Fahrenheit for threshold comparison.

        v3.6.0.8: HA sensors report in their native unit (°C or °F).
        All safety thresholds are in °F. Check the entity's
        unit_of_measurement and convert if needed.
        """
        # Cache unit lookups to avoid repeated state reads
        if entity_id not in self._sensor_units:
            unit = "°F"  # Default assumption
            try:
                state = self.hass.states.get(entity_id)
                if state:
                    unit = state.attributes.get("unit_of_measurement", "°F")
            except Exception:
                pass
            self._sensor_units[entity_id] = unit

        unit = self._sensor_units[entity_id]
        if unit in ("°C", "℃", "C"):
            return value * 9.0 / 5.0 + 32.0
        return value

    # =========================================================================
    # Temperature handling
    # =========================================================================

    def _handle_temperature(
        self, entity_id: str, value: float, now: datetime
    ) -> list[Hazard]:
        """Handle temperature sensor readings.

        Checks for:
        1. Freeze risk (value <= threshold)
        2. Overheat (value >= threshold)
        Note: Rate-of-change is handled separately in _process_sensor.
        """
        hazards: list[Hazard] = []
        location = self._sensor_locations.get(entity_id, "unknown")

        # Freeze risk
        freeze_severity = self._classify_severity(HazardType.FREEZE_RISK, value)
        if freeze_severity is not None:
            threshold = self._get_threshold(HazardType.FREEZE_RISK, freeze_severity)
            hazards.append(
                Hazard(
                    type=HazardType.FREEZE_RISK,
                    severity=freeze_severity,
                    confidence=0.90,
                    location=location,
                    sensor_id=entity_id,
                    value=value,
                    threshold=threshold,
                    detected_at=now,
                    message=f"Freeze risk: {value}F in {location}",
                )
            )

        # Overheat
        overheat_severity = self._classify_severity(HazardType.OVERHEAT, value)
        if overheat_severity is not None:
            threshold = self._get_threshold(HazardType.OVERHEAT, overheat_severity)
            hazards.append(
                Hazard(
                    type=HazardType.OVERHEAT,
                    severity=overheat_severity,
                    confidence=0.85,
                    location=location,
                    sensor_id=entity_id,
                    value=value,
                    threshold=threshold,
                    detected_at=now,
                    message=f"Overheat warning: {value}F in {location}",
                )
            )

        return hazards

    # =========================================================================
    # Humidity handling
    # =========================================================================

    def _handle_humidity(
        self, entity_id: str, value: float, now: datetime
    ) -> list[Hazard]:
        """Handle humidity sensor readings with room-type-aware thresholds.

        v3.6.0-c2.6: Raised thresholds and added one-shot firing.
        Room type thresholds:
        - Normal: LOW=70, MEDIUM=80, HIGH=90, sustained 2hr
        - Bathroom: LOW=80, MEDIUM=85, HIGH=90, sustained 4hr
        - Basement: LOW=65, MEDIUM=75, HIGH=85, sustained 2hr

        High humidity hazards fire ONCE per sustained period (not on every
        state change after window expires). Cleared when value drops below
        threshold.
        """
        hazards: list[Hazard] = []
        location = self._sensor_locations.get(entity_id, "unknown")
        room_type = self._sensor_room_types.get(entity_id, "normal")

        # NM Cycle A A4: outdoor rooms are excluded from humidity ladder —
        # patio/deck RH tracks weather and firing indoor-moisture hazards
        # against outdoor sensors is pure noise (77% patio p50 was pre-A4
        # baseline). Discovery-time classification via CONF_ROOM_TYPE.
        if room_type == "outdoor":
            return hazards

        # Determine effective room type for thresholds
        if room_type == "bathroom":
            thresholds = HUMIDITY_THRESHOLDS["bathroom"]
        elif room_type == "basement":
            thresholds = HUMIDITY_THRESHOLDS["basement"]
        else:
            # NM Cycle A A4: honor operator overrides for the "normal" ladder.
            from ..const import (
                CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT,
                CONF_HUMIDITY_NORMAL_MEDIUM_PCT,
                CONF_HUMIDITY_NORMAL_HIGH_PCT,
                DEFAULT_HUMIDITY_NORMAL_LOG_ONLY_PCT,
                DEFAULT_HUMIDITY_NORMAL_MEDIUM_PCT,
                DEFAULT_HUMIDITY_NORMAL_HIGH_PCT,
            )
            from ._nm_cycle_a import nm_cycle_a_knob
            thresholds = {
                "low": float(nm_cycle_a_knob(
                    self.hass, CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT,
                    DEFAULT_HUMIDITY_NORMAL_LOG_ONLY_PCT,
                )),
                "medium": float(nm_cycle_a_knob(
                    self.hass, CONF_HUMIDITY_NORMAL_MEDIUM_PCT,
                    DEFAULT_HUMIDITY_NORMAL_MEDIUM_PCT,
                )),
                "high": float(nm_cycle_a_knob(
                    self.hass, CONF_HUMIDITY_NORMAL_HIGH_PCT,
                    DEFAULT_HUMIDITY_NORMAL_HIGH_PCT,
                )),
                "window_hours": HUMIDITY_THRESHOLDS["normal"]["window_hours"],
            }

        # NM Cycle A A4: swing trigger — fast-rise below the sustained ceiling
        # still emits MEDIUM. Consumes the existing rate detector's 30-min
        # humidity rate (no new EMA state). Kill-switch: delta<=0 disables.
        #
        # Fix-up H2 (HIGH): swing is gated to room_type "normal" ONLY. In
        # bathrooms a 50→85% shower is routine (not a moisture hazard) and
        # was pager-fodder every shower (Bug Class #21-adjacent — severity
        # miscall by scope). Basements are excluded too — their "low" band
        # starts at 65, so a swing landing at ~70 is inside their normal
        # ladder handled by the sustained window. Swing exists to catch
        # indoor-moisture events in general-purpose rooms.
        #
        # Fix-up B-MED-1 / M2: swing uses its OWN one-shot set
        # (`_humidity_swing_fired`). Prior code shared `_humidity_hazard_fired`
        # with the sustained ladder, which (a) let a swing MEDIUM mask a
        # subsequent sustained HIGH (severity demotion; QC #21) and (b) got
        # instantly discarded by the sustained else-branch when value was in
        # [swing_floor, low) — defeating swing dedup.
        try:
            from ..const import (
                CONF_HUMIDITY_SWING_DELTA_PCT,
                CONF_HUMIDITY_SWING_MIN_ABS_PCT,
                DEFAULT_HUMIDITY_SWING_DELTA_PCT,
                DEFAULT_HUMIDITY_SWING_MIN_ABS_PCT,
            )
            from ._nm_cycle_a import nm_cycle_a_knob
            swing_delta = float(nm_cycle_a_knob(
                self.hass, CONF_HUMIDITY_SWING_DELTA_PCT,
                DEFAULT_HUMIDITY_SWING_DELTA_PCT,
            ))
            swing_floor = float(nm_cycle_a_knob(
                self.hass, CONF_HUMIDITY_SWING_MIN_ABS_PCT,
                DEFAULT_HUMIDITY_SWING_MIN_ABS_PCT,
            ))
            # Fix-up H2: swing applies to the "normal" ladder only.
            swing_room_type_ok = room_type not in ("bathroom", "basement", "outdoor")
            if swing_room_type_ok and swing_delta > 0 and value >= swing_floor:
                rate = self._rate_detector.get_rate(entity_id, now)
                # rate is delta over the 30-min window (already per-30-min)
                if (rate is not None
                        and rate >= swing_delta
                        and entity_id not in self._humidity_swing_fired
                        and value < thresholds["high"]):
                    hazards.append(
                        Hazard(
                            type=HazardType.HIGH_HUMIDITY,
                            severity=Severity.MEDIUM,
                            confidence=0.70,
                            location=location,
                            sensor_id=entity_id,
                            value=value,
                            threshold=swing_delta,
                            detected_at=now,
                            message=(
                                f"Humidity swing in {location}: "
                                f"+{rate:.0f}pp/30min (now {value}%)"
                            ),
                        )
                    )
                    # Mark swing-fired (own set — leaves sustained ladder untouched).
                    self._humidity_swing_fired.add(entity_id)
            # Fix-up B-MED-1: clear swing-fired once value has decayed below
            # the swing floor (episode reset). Independent of the sustained
            # ladder's `_humidity_hazard_fired` clear (which uses `low`).
            if value < swing_floor:
                self._humidity_swing_fired.discard(entity_id)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("humidity swing check failed", exc_info=True)

        # High humidity check with sustained window enforcement
        if value >= thresholds["low"]:
            # Above at least the LOW threshold — start or continue tracking
            if entity_id not in self._humidity_above_since:
                self._humidity_above_since[entity_id] = now

            elapsed_hours = (now - self._humidity_above_since[entity_id]).total_seconds() / 3600.0
            window_hours = thresholds["window_hours"]

            if elapsed_hours >= window_hours:
                # v3.6.0-c2.6: Only fire hazard once per sustained period
                if entity_id not in self._humidity_hazard_fired:
                    self._humidity_hazard_fired.add(entity_id)

                    # Sustained window elapsed — classify severity
                    severity_key = "low"
                    if value >= thresholds["high"]:
                        severity = Severity.HIGH
                        severity_key = "high"
                    elif value >= thresholds["medium"]:
                        severity = Severity.MEDIUM
                        severity_key = "medium"
                    else:
                        # NM Cycle A A4: below MEDIUM = log-only for the
                        # "normal" room ladder only. Bathroom/basement keep
                        # firing LOW-severity hazards at their "low" rungs
                        # (untouched by A4). Sentinel: reaches here only for
                        # the room-type branches that DON'T explicitly set
                        # `thresholds` from HUMIDITY_THRESHOLDS (i.e. normal).
                        if room_type not in ("bathroom", "basement"):
                            _LOGGER.info(
                                "Humidity log-only rung: %s at %s%% sustained "
                                "%.1fh (below MEDIUM %s%%)",
                                location, value, elapsed_hours,
                                thresholds["medium"],
                            )
                            return hazards
                        severity = Severity.LOW
                        severity_key = "low"

                    hazards.append(
                        Hazard(
                            type=HazardType.HIGH_HUMIDITY,
                            severity=severity,
                            confidence=0.80,
                            location=location,
                            sensor_id=entity_id,
                            value=value,
                            threshold=thresholds[severity_key],
                            detected_at=now,
                            message=f"High humidity: {value}% in {location} sustained {elapsed_hours:.1f}h (room type: {room_type})",
                        )
                    )
        else:
            # Below all thresholds — clear sustained tracking and one-shot flag
            self._humidity_above_since.pop(entity_id, None)
            self._humidity_hazard_fired.discard(entity_id)

        # Low humidity check (universal thresholds, fires immediately)
        low_severity = None
        for sev in (Severity.MEDIUM, Severity.LOW):
            if sev in LOW_HUMIDITY_THRESHOLDS and value <= LOW_HUMIDITY_THRESHOLDS[sev]:
                low_severity = sev
                break

        if low_severity is not None:
            hazards.append(
                Hazard(
                    type=HazardType.LOW_HUMIDITY,
                    severity=low_severity,
                    confidence=0.80,
                    location=location,
                    sensor_id=entity_id,
                    value=value,
                    threshold=LOW_HUMIDITY_THRESHOLDS[low_severity],
                    detected_at=now,
                    message=f"Low humidity: {value}% in {location}",
                )
            )

        return hazards

    # =========================================================================
    # Response actions
    # =========================================================================

    async def _respond_to_hazard(self, hazard: Hazard) -> list[CoordinatorAction]:
        """Generate response actions for a detected hazard.

        v4.0.11: Only dispatches signals and logs for NEW hazards or severity
        changes. Repeated evaluations of the same active hazard increment an
        occurrence counter (like HA's "N occurrences" pattern) but don't
        re-fire signals, activity logs, or response actions.
        """
        # Track the hazard — detect transitions vs repeated evaluations
        key = f"{hazard.type.value}:{hazard.location}"
        existing = self._active_hazards.get(key)
        is_new = existing is None or existing.severity != hazard.severity
        self._active_hazards[key] = hazard

        if not is_new:
            # Same hazard, same severity — increment occurrence counter, skip response
            self._hazard_occurrences[key] = self._hazard_occurrences.get(key, 1) + 1
            return []

        # New hazard or severity change — reset occurrence counter
        self._hazard_occurrences[key] = 1
        self._hazards_detected_24h += 1

        # v4.6.9 D5: Record into the recent-events ring buffer.
        # Every new hazard (or severity change on an existing one) appends
        # one entry. room=hazard.location (str | None — "unknown" from
        # _location_from_entity_id but never None in practice; coerced to
        # None only when empty so the PWA gets clean null).
        _room_val: str | None = hazard.location if hazard.location else None
        self._record_event(
            event_type=hazard.type.value,
            room=_room_val,
            severity=hazard.severity,
        )

        # Generate actions based on severity
        actions: list[CoordinatorAction] = []

        # v3.21.1 D1: Observation mode — log what WOULD happen, skip actions + signals
        # Review fix R2-F2: Signal dispatch moved inside non-observation block
        # so AI automations chained to safety hazards are also suppressed
        if self.observation_mode:
            _LOGGER.info(
                "[observation mode] Safety would respond to %s hazard "
                "(%s) at %s — suppressed",
                hazard.severity.name,
                hazard.type.value,
                hazard.location,
            )
        else:
            # v3.12.0 M2: Dispatch safety hazard signal for automation chaining
            from homeassistant.helpers.dispatcher import async_dispatcher_send
            async_dispatcher_send(
                self.hass,
                SIGNAL_SAFETY_HAZARD,
                SafetyHazardPayload(
                    hazard_type=hazard.type.value,
                    severity=hazard.severity.name.lower(),
                    source_entity=hazard.sensor_id or "",
                    value=hazard.value,
                    details=hazard.message or "",
                ),
            )

            # Activity log: hazard detection
            from ..const import DOMAIN
            activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
            if activity_logger:
                self.hass.async_create_task(
                    activity_logger.log(
                        coordinator="safety",
                        action="hazard_detected",
                        description=f"{hazard.severity.name} hazard: {hazard.type.value} at {hazard.location}",
                        room=hazard.location,
                        importance="critical",
                        entity_id=hazard.sensor_id,
                        details={
                            "type": hazard.type.value,
                            "severity": hazard.severity.name,
                            "location": hazard.location,
                            "message": hazard.message or "",
                        },
                    )
                )

            if hazard.severity == Severity.CRITICAL:
                actions.extend(self._critical_response(hazard))
            elif hazard.severity == Severity.HIGH:
                actions.extend(self._high_response(hazard))
            elif hazard.severity == Severity.MEDIUM:
                actions.extend(self._medium_response(hazard))
            else:
                actions.extend(self._low_response(hazard))

            # Send notification if not deduplicated
            if self._deduplicator.should_alert(hazard):
                self._alerts_sent_24h += 1
                actions.append(
                    NotificationAction(
                        coordinator_id=self.COORDINATOR_ID,
                        severity=hazard.severity,
                        confidence=hazard.confidence,
                        description=f"Safety alert: {hazard.message}",
                        message=hazard.message,
                        channels=self._get_notification_channels(hazard.severity),
                    )
                )

        # Log decision
        if self.decision_logger is not None:
            try:
                await self.decision_logger.log_decision(
                    coordinator_id=self.COORDINATOR_ID,
                    decision_type=f"hazard_{hazard.type.value}",
                    context={"severity": hazard.severity.name, "location": hazard.location},
                    action=hazard.message,
                    scope=hazard.location,
                )
            except Exception:
                pass

        # v4.6.3 D2/D11/D12: Record hazard trigger as canonical AnomalyEvent +
        # ActivityLogger emit.  Replaces store_anomaly() wrapper with direct
        # store_event() so payload shape is canonical.
        # v4.6.4 P2: hazard_trigger_frequency block removed — recorded constant
        # 1.0, baseline mean converged to 1.0, |value-mean|=0 → z=0 → NOMINAL →
        # never emitted. Audit confirmed zero anomalies ever fired in production.
        # (v4.6.5 D4 audit had hypothesized this was Poisson-rate-suitable; that
        # analysis was wrong — a constant 1.0 carries no rate information once
        # the baseline learns. Resolved during v4.6.5 rebase in favor of v4.6.4's
        # empirical evidence.)
        # The remaining active_hazard_count emit has real 0..N variance and is
        # retained. v4.6.5 audit note worth preserving: in homes where active
        # hazards are sparse (0 most of the time, occasional 1), the metric
        # approaches binary-shape and may produce v4.6.3.1-style over-emits.
        # No suppression today — pre-existing v4.6.3 behavior; revisit with
        # Bayesian time-bin distribution if over-emit shows up in soak.
        if self.anomaly_detector is not None:
            try:
                from .anomaly_event import (
                    AnomalyEvent,
                    AnomalySeverity as _NewSev,
                    AnomalyType,
                    build_context_json,
                )
                # Record current active hazard count (well-shaped 0..N variance)
                anomaly2 = self.anomaly_detector.record_observation(
                    "active_hazard_count",
                    "house",
                    float(len(self._active_hazards)),
                )
                if anomaly2:
                    _ctx2 = build_context_json(
                        source_signal="SIGNAL_SAFETY_HAZARD",
                        extra={
                            "active_hazard_count": len(self._active_hazards),
                        },
                    )
                    _event2 = AnomalyEvent(
                        coordinator="safety",
                        type="safety.active_hazard_count",
                        # v4.6.6 D1: intentionally constant WARNING (not
                        # map_diag_severity) — `active_hazard_count` emits
                        # are binary-hazard reports with no z-score
                        # classifier band to translate. Per planning doc,
                        # binary hazards stay at WARNING; only
                        # classifier-driven sites need the 4-way mapping.
                        severity=_NewSev.WARNING,
                        anomaly_type=AnomalyType.HAZARD,
                        detected_at=anomaly2.timestamp.isoformat(),
                        payload=_ctx2,
                        observed_value=anomaly2.observed_value,
                        expected_mean=anomaly2.expected_mean,
                        expected_std=anomaly2.expected_std,
                        z_score=round(anomaly2.z_score, 3),
                        sample_size=anomaly2.sample_size,
                    )
                    await self.anomaly_detector.store_event(_event2)
                    _LOGGER.info(
                        "Safety active_hazard_count anomaly emitted: count=%d z=%.2f",
                        len(self._active_hazards), anomaly2.z_score,
                    )
                    # B3 fix: D12 activity_logger call was missing from this emit site.
                    # Every other migrated emit site fires activity_logger — add it here.
                    _activity_logger2 = self.hass.data.get(DOMAIN, {}).get("activity_logger")
                    if _activity_logger2:
                        await _activity_logger2.log(
                            coordinator="safety",
                            action="anomaly",
                            description=(
                                f"Safety active_hazard_count anomaly: count={len(self._active_hazards)} "
                                f"z={anomaly2.z_score:.2f}"
                            ),
                            importance="notable",
                            details={
                                "type": "safety.active_hazard_count",
                                "z_score": round(anomaly2.z_score, 3),
                                "active_hazard_count": len(self._active_hazards),
                            },
                        )
            except Exception:
                _LOGGER.debug("Anomaly recording failed", exc_info=True)

        # v3.6.0.3: Push entity updates on hazard change
        self._notify_entity_update()

        return actions

    def _critical_response(self, hazard: Hazard) -> list[CoordinatorAction]:
        """CRITICAL severity: Maximum response — designated emergency lights, full alert.

        v3.6.0-c2.8: Only uses explicitly configured emergency lights.
        Never targets entity_id "all" — if no emergency lights are configured,
        the response is notification-only (no light manipulation).
        """
        actions: list[CoordinatorAction] = []

        # Emergency lights: only configured lights, full brightness, white
        if self._emergency_lights:
            actions.append(
                ServiceCallAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.CRITICAL,
                    confidence=hazard.confidence,
                    description=f"Emergency lights for {hazard.type.value}",
                    service="light.turn_on",
                    service_data={
                        "entity_id": self._emergency_lights,
                        "brightness": 255,
                    },
                )
            )
        else:
            _LOGGER.warning(
                "CRITICAL hazard (%s) but no emergency lights configured — "
                "skipping light response. Configure emergency lights in "
                "Coordinator Manager → Safety Monitoring.",
                hazard.type.value,
            )

        # Flooding: water shutoff (if configured)
        if hazard.type == HazardType.FLOODING:
            actions.extend(self._water_shutoff_actions(hazard))

        return actions

    def _high_response(self, hazard: Hazard) -> list[CoordinatorAction]:
        """HIGH severity: Urgent response — targeted actions."""
        actions: list[CoordinatorAction] = []

        # Freeze risk: override HVAC to heat
        if hazard.type == HazardType.FREEZE_RISK:
            actions.append(
                ConstraintAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.HIGH,
                    confidence=hazard.confidence,
                    description="Freeze protection — forcing heat",
                    constraint_type="hvac",
                    constraint_data={"mode": "heat", "min_temp": 55},
                )
            )

        # Overheat: override HVAC to cool
        if hazard.type == HazardType.OVERHEAT:
            actions.append(
                ConstraintAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.HIGH,
                    confidence=hazard.confidence,
                    description="Overheat protection — forcing cooling",
                    constraint_type="hvac",
                    constraint_data={"mode": "cool", "max_temp": 78},
                )
            )

        # Water leak: water shutoff if configured
        if hazard.type in (HazardType.WATER_LEAK, HazardType.FLOODING):
            actions.extend(self._water_shutoff_actions(hazard))

        return actions

    def _medium_response(self, hazard: Hazard) -> list[CoordinatorAction]:
        """MEDIUM severity: Prompt response — ventilation, dehumidification."""
        actions: list[CoordinatorAction] = []

        if hazard.type in (HazardType.HIGH_CO2, HazardType.HIGH_TVOC):
            actions.append(
                ConstraintAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.MEDIUM,
                    confidence=hazard.confidence,
                    description=f"Ventilation request for {hazard.type.value}",
                    constraint_type="ventilation",
                    constraint_data={"mode": "boost", "reason": hazard.type.value},
                )
            )

        if hazard.type == HazardType.HIGH_HUMIDITY:
            actions.append(
                ConstraintAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.MEDIUM,
                    confidence=hazard.confidence,
                    description="Dehumidification request",
                    constraint_type="dehumidifier",
                    constraint_data={"mode": "on", "location": hazard.location},
                )
            )

        if hazard.type == HazardType.HVAC_FAILURE:
            actions.append(
                CoordinatorAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.MEDIUM,
                    confidence=hazard.confidence,
                    description=f"HVAC failure detected: {hazard.message}",
                )
            )

        return actions

    def _low_response(self, hazard: Hazard) -> list[CoordinatorAction]:
        """LOW severity: Advisory — log only."""
        return [
            CoordinatorAction(
                coordinator_id=self.COORDINATOR_ID,
                severity=Severity.LOW,
                confidence=hazard.confidence,
                description=f"Advisory: {hazard.message}",
            )
        ]

    def _water_shutoff_actions(self, hazard: Hazard) -> list[CoordinatorAction]:
        """Generate water shutoff actions if valve is configured."""
        valve_entity = self._water_shutoff_valve
        if valve_entity:
            return [
                ServiceCallAction(
                    coordinator_id=self.COORDINATOR_ID,
                    target_device=valve_entity,
                    severity=hazard.severity,
                    confidence=hazard.confidence,
                    description="Water shutoff — closing main valve",
                    service="valve.close",
                    service_data={"entity_id": valve_entity},
                )
            ]
        return []

    @staticmethod
    def _get_light_pattern_key(hazard_type: HazardType) -> str:
        """Map hazard type to light pattern key."""
        mapping = {
            HazardType.SMOKE: "fire",
            HazardType.FIRE: "fire",
            HazardType.WATER_LEAK: "water_leak",
            HazardType.FLOODING: "water_leak",
            HazardType.CARBON_MONOXIDE: "co",
            HazardType.FREEZE_RISK: "freeze",
        }
        return mapping.get(hazard_type, "warning")

    @staticmethod
    def _get_notification_channels(severity: Severity) -> list[str]:
        """Get notification channels based on severity."""
        if severity == Severity.CRITICAL:
            return ["imessage", "speaker", "lights"]
        elif severity == Severity.HIGH:
            return ["imessage", "speaker"]
        elif severity == Severity.MEDIUM:
            return ["imessage"]
        return []  # LOW = log only

    # =========================================================================
    # Periodic checks
    # =========================================================================

    @callback
    def _async_periodic_check(self, _now: Any = None) -> None:
        """Periodic check for sustained conditions (flooding escalation)."""
        now = dt_util.utcnow()

        # Check flooding escalation for active leak sensors
        if self._active_leak_sensors:
            flooding = self._check_flooding_escalation(now)
            if flooding is not None:
                key = f"{flooding.type.value}:{flooding.location}"
                if key not in self._active_hazards:
                    self._active_hazards[key] = flooding
                    # v3.6.0.6: Push entity updates on flooding escalation
                    self._notify_entity_update()
                    # Queue intent for the flooding detection
                    manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
                    if manager is not None:
                        intent = Intent(
                            source="periodic_check",
                            entity_id="safety.flooding_escalation",
                            data={"hazard_type": "flooding"},
                            coordinator_id=self.COORDINATOR_ID,
                        )
                        manager.queue_intent(intent)

    # =========================================================================
    # Test hazard service
    # =========================================================================

    async def handle_test_hazard(
        self, hazard_type: str, location: str, severity: str
    ) -> None:
        """Handle test_safety_hazard service call.

        Creates a test hazard for notification pipeline verification.
        Does NOT trigger real responses (no HVAC override, no valve close).
        Only sends notifications.
        """
        try:
            h_type = HazardType(hazard_type)
        except ValueError:
            _LOGGER.warning("Invalid hazard type for test: %s", hazard_type)
            return

        try:
            sev = Severity[severity.upper()]
        except (KeyError, AttributeError):
            sev = Severity.MEDIUM

        now = dt_util.utcnow()
        hazard = Hazard(
            type=h_type,
            severity=sev,
            confidence=1.0,
            location=location,
            sensor_id="test",
            value="test",
            threshold="test",
            detected_at=now,
            message=f"TEST: {h_type.value} in {location} (severity: {sev.name})",
        )

        # Only send notification, no real response actions
        if self._deduplicator.should_alert(hazard):
            channels = self._get_notification_channels(sev)
            _LOGGER.info(
                "Test safety hazard: %s in %s (severity: %s, channels: %s)",
                hazard_type,
                location,
                severity,
                channels,
            )

    # =========================================================================
    # Hazard clearing
    # =========================================================================

    def clear_hazard(self, hazard_type: HazardType, location: str) -> None:
        """Clear an active hazard."""
        key = f"{hazard_type.value}:{location}"
        self._active_hazards.pop(key, None)
        # v3.6.0.3: Push entity updates on hazard clear
        self._notify_entity_update()

    def clear_all_hazards(self) -> None:
        """Clear all active hazards."""
        self._active_hazards.clear()
        self._hazard_occurrences.clear()
        self._leak_start_times.clear()
        self._active_leak_sensors.clear()
        self._humidity_hazard_fired.clear()
        self._humidity_swing_fired.clear()
        # v3.6.0.3: Push entity updates on hazard clear
        self._notify_entity_update()

    # =========================================================================
    # Diagnostics
    # =========================================================================

    def get_diagnostics_summary(self) -> dict[str, Any]:
        """Return diagnostics summary for the Safety Coordinator."""
        summary = super().get_diagnostics_summary()

        summary["active_hazards"] = len(self._active_hazards)
        summary["active_hazard_details"] = {
            key: {
                "type": h.type.value,
                "severity": h.severity.name,
                "location": h.location,
                "detected_at": h.detected_at.isoformat(),
            }
            for key, h in self._active_hazards.items()
        }
        summary["sensors_monitored"] = self.sensors_monitored
        summary["binary_sensors"] = len(self._binary_sensors)
        summary["numeric_sensors"] = len(self._numeric_sensors)
        summary["rate_baselines"] = self._rate_detector.get_baseline_summary()
        summary["hazards_detected_24h"] = self._hazards_detected_24h
        summary["alerts_sent_24h"] = self._alerts_sent_24h
        summary["false_alarm_rate"] = (
            self._false_alarms_7d / max(self._total_hazards_7d, 1)
        )
        summary["response_times"] = {
            "count": len(self._response_times),
            "avg_seconds": (
                sum(self._response_times) / len(self._response_times)
                if self._response_times
                else 0.0
            ),
        }

        return summary

    def get_safety_status(self) -> str:
        """Return the overall safety status string."""
        if not self._active_hazards:
            return "normal"

        worst = max(
            (h.severity for h in self._active_hazards.values()),
            default=Severity.LOW,
        )
        if worst == Severity.CRITICAL:
            return "critical"
        elif worst == Severity.HIGH:
            return "alert"
        elif worst == Severity.MEDIUM:
            return "warning"
        # LOW severity = advisory (active hazard, but log-only response)
        return "advisory"

    def get_all_hazards_detail(self) -> list[dict]:
        """Return all active hazards as serializable dicts.

        v3.6.0.3: Full hazard detail for glanceable entities.
        Capped at 20, sorted by severity (critical first).
        """
        SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        hazards = []
        for hazard in self._active_hazards.values():
            hazards.append({
                "hazard_type": hazard.type.value,
                "severity": hazard.severity.name.lower(),
                "location": hazard.location,
                "sensor_id": hazard.sensor_id,
                "value": hazard.value,
                "threshold": hazard.threshold,
                "detected_at": hazard.detected_at.isoformat() if hazard.detected_at else None,
                "message": hazard.message,
            })
        hazards.sort(key=lambda h: SEVERITY_ORDER.get(h["severity"], 99))
        return hazards[:20]

    def get_water_leak_status(self) -> dict:
        """Return water leak status for binary sensor.

        v3.6.0.3: Dedicated water leak glanceable entity.
        """
        leak_hazards = {
            k: v for k, v in self._active_hazards.items()
            if v.type in (HazardType.WATER_LEAK, HazardType.FLOODING)
        }
        if not leak_hazards:
            return {"active": False}

        locations = list(set(h.location for h in leak_hazards.values()))
        sensor_ids = list(set(h.sensor_id for h in leak_hazards.values()))
        flooding = any(h.type == HazardType.FLOODING for h in leak_hazards.values())

        # Find earliest detection time
        detected_times = [
            h.detected_at for h in leak_hazards.values() if h.detected_at
        ]
        first_detected = min(detected_times).isoformat() if detected_times else None

        return {
            "active": True,
            "locations": locations,
            "sensor_ids": sensor_ids,
            "sensor_count": len(sensor_ids),
            "flooding_escalated": flooding,
            "first_detected": first_detected,
        }

    def get_air_quality_status(self) -> dict:
        """Return air quality status for binary sensor.

        v3.6.0.3: Dedicated air quality glanceable entity.
        """
        AQ_TYPES = {HazardType.SMOKE, HazardType.CARBON_MONOXIDE, HazardType.HIGH_CO2, HazardType.HIGH_TVOC}
        aq_hazards = {
            k: v for k, v in self._active_hazards.items()
            if v.type in AQ_TYPES
        }
        if not aq_hazards:
            return {"active": False}

        SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        hazard_types = list(set(h.type.value for h in aq_hazards.values()))
        locations = list(set(h.location for h in aq_hazards.values()))
        sensor_ids = list(set(h.sensor_id for h in aq_hazards.values()))
        severities = [
            h.severity.name.lower()
            for h in aq_hazards.values()
        ]
        worst = min(severities, key=lambda s: SEVERITY_ORDER.get(s, 99))

        return {
            "active": True,
            "hazard_types": hazard_types,
            "locations": locations,
            "sensor_ids": sensor_ids,
            "worst_severity": worst,
        }

    def get_affected_rooms(self) -> dict:
        """Return rooms with active hazards, grouped by zone.

        v3.6.0.6: Affected rooms entity data.
        """
        if not self._active_hazards:
            return {
                "affected_rooms": [],
                "affected_by_zone": {},
                "room_count": 0,
                "zone_count": 0,
                "worst_room": None,
            }

        SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

        # Collect rooms and their worst severity
        room_worst: dict[str, str] = {}  # room_name -> worst severity
        for hazard in self._active_hazards.values():
            loc = hazard.location
            sev = hazard.severity.name.lower()
            if loc not in room_worst or SEVERITY_ORDER.get(sev, 99) < SEVERITY_ORDER.get(room_worst[loc], 99):
                room_worst[loc] = sev

        affected_rooms = sorted(room_worst.keys())

        # Build room -> zone mapping from URA room config entries
        from ..const import (
            CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM, CONF_ROOM_NAME, CONF_ZONE,
        )
        room_to_zone: dict[str, str] = {}
        for config_entry in self.hass.config_entries.async_entries(DOMAIN):
            if config_entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            merged = {**config_entry.data, **config_entry.options}
            room_name = merged.get(CONF_ROOM_NAME, "")
            zone = merged.get(CONF_ZONE, "")
            if room_name and zone:
                room_to_zone[room_name] = zone

        # Group affected rooms by zone
        by_zone: dict[str, list[str]] = {}
        for room in affected_rooms:
            zone = room_to_zone.get(room, "Unassigned")
            by_zone.setdefault(zone, []).append(room)

        # Find worst room
        worst_room = min(room_worst, key=lambda r: SEVERITY_ORDER.get(room_worst[r], 99))

        return {
            "affected_rooms": affected_rooms,
            "affected_by_zone": by_zone,
            "room_count": len(affected_rooms),
            "zone_count": len(by_zone),
            "worst_room": worst_room,
        }

    def _notify_entity_update(self) -> None:
        """Fire dispatcher signal to update safety entities.

        v3.6.0.3: Push updates instead of polling.
        """
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        from .signals import SIGNAL_SAFETY_ENTITIES_UPDATE
        async_dispatcher_send(self.hass, SIGNAL_SAFETY_ENTITIES_UPDATE)

    def get_diagnostics_status(self) -> str:
        """Return diagnostics health status."""
        total_sensors = self.sensors_monitored
        if total_sensors == 0:
            return "degraded"

        # Check how many sensors are available
        available = 0
        for entity_id in list(self._binary_sensors.keys()) + list(
            self._numeric_sensors.keys()
        ):
            try:
                state = self.hass.states.get(entity_id)
                if state and state.state not in _UNAVAILABLE_STATES:
                    available += 1
            except Exception:
                pass

        if available >= total_sensors:
            return "healthy"
        elif available >= total_sensors * 0.5:
            return "degraded"
        return "degraded"

    # =========================================================================
    # Rate baseline persistence
    # =========================================================================

    async def _load_rate_baselines(self) -> None:
        """Load rate-of-change baselines from SQLite.

        v3.6.0.10: Uses the same metric_baselines table as AnomalyDetector,
        but with coordinator_id="safety_rate" to avoid collisions.
        """
        import aiosqlite
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            return

        try:
            async with aiosqlite.connect(database.db_file) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT metric_name, scope, mean, variance,
                           sample_count, last_updated
                    FROM metric_baselines
                    WHERE coordinator_id = ?
                """, ("safety_rate",))
                rows = await cursor.fetchall()

                for row in rows:
                    # metric_name is "rate:<entity_id>"
                    metric_name = row["metric_name"]
                    if metric_name.startswith("rate:"):
                        entity_id = metric_name[5:]  # strip "rate:" prefix
                        self._rate_detector._rate_baselines[entity_id] = MetricBaseline(
                            metric_name=metric_name,
                            coordinator_id="safety_rate",
                            scope=row["scope"],
                            mean=row["mean"],
                            variance=row["variance"],
                            sample_count=row["sample_count"],
                            last_updated=row["last_updated"],
                        )
                _LOGGER.debug(
                    "Loaded %d rate baselines for safety",
                    len(rows),
                )
        except Exception as e:
            _LOGGER.debug(
                "Error loading rate baselines (may not exist yet): %s", e,
            )

    async def _save_rate_baselines(self) -> None:
        """Persist rate-of-change baselines to SQLite."""
        import aiosqlite
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            return

        baselines = self._rate_detector._rate_baselines
        if not baselines:
            return

        try:
            async with aiosqlite.connect(database.db_file) as db:
                for entity_id, baseline in baselines.items():
                    await db.execute("""
                        INSERT OR REPLACE INTO metric_baselines
                        (coordinator_id, metric_name, scope,
                         mean, variance, sample_count, last_updated)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        "safety_rate",
                        baseline.metric_name,
                        baseline.scope,
                        baseline.mean,
                        baseline.variance,
                        baseline.sample_count,
                        baseline.last_updated,
                    ))
                await db.commit()
                _LOGGER.debug(
                    "Saved %d rate baselines for safety",
                    len(baselines),
                )
        except Exception as e:
            _LOGGER.error("Error saving rate baselines: %s", e)

    @callback
    def _async_save_rate_baselines(self, _now: Any = None) -> None:
        """Periodic callback to save rate baselines."""
        self.hass.async_create_task(self._save_rate_baselines())

    # =========================================================================
    # Teardown
    # =========================================================================

    def is_hazard_active(self, hazard_type: str, location: str) -> bool:
        """Check if a specific hazard is still active (for NM re-fire logic)."""
        key = f"{hazard_type}:{location}"
        # Also check without enum prefix
        for active_key in self._active_hazards:
            if key == active_key or active_key.endswith(f":{location}"):
                # Match by location and partial type
                active_type = active_key.split(":")[0]
                if hazard_type in active_type or active_type in hazard_type:
                    return True
        return key in self._active_hazards

    async def async_teardown(self) -> None:
        """Tear down the Safety Coordinator."""
        # v3.6.0.10: Save rate baselines before teardown
        try:
            await self._save_rate_baselines()
        except Exception:
            _LOGGER.debug("Could not save rate baselines on teardown", exc_info=True)

        # RESTART-SAFETY-DOCTRINE-1 F1: persist AnomalyDetector baselines.
        # Matches HVAC (hvac.py:3869), presence (presence.py:7448), music
        # (music_following.py:687), security (security.py:824). Safety +
        # setup detector (manager) were the only load-baselines-without-save
        # sites the audit surfaced. Event-driven baselines (safety hazards
        # fire rarely) NEVER arm without this — MINIMUM_SAMPLES=10 is
        # unreachable inside the measured 5.55h median restart interval.
        if self.anomaly_detector is not None:
            try:
                await self.anomaly_detector.save_baselines()
                _LOGGER.info("Safety: saved anomaly baselines on teardown")
            except Exception:
                _LOGGER.warning(
                    "Safety: failed to save anomaly baselines on teardown",
                    exc_info=True,
                )

        self._cancel_listeners()
        self._active_hazards.clear()
        self._hazard_occurrences.clear()
        self._deduplicator.clear()
        self._rate_detector.clear()
        self._leak_start_times.clear()
        self._active_leak_sensors.clear()
        self._humidity_hazard_fired.clear()
        self._humidity_swing_fired.clear()
        self._sensor_units.clear()
        _LOGGER.info("Safety Coordinator torn down")
