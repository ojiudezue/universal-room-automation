"""SPAN/Emporia circuit monitoring and anomaly detection for Energy Coordinator.

Sub-Cycle E3: Auto-discover SPAN circuits, monitor power per circuit,
detect tripped breakers (sudden zero), alert via NM.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# How long a circuit must be at zero to trigger tripped breaker alert (seconds)
TRIPPED_BREAKER_THRESHOLD_SECONDS = 120
# Minimum recent power for a circuit to be considered "normally loaded"
NORMALLY_LOADED_THRESHOLD_W = 5.0

# Generator status values
GEN_RUNNING = "running"
GEN_STANDBY = "standby"
GEN_OFF = "off"
GEN_UNAVAILABLE = "unavailable"

# Default generator entity
DEFAULT_GENERATOR_STATUS_ENTITY = "sensor.generac_2325624_status_2"


class CircuitInfo:
    """Tracks state for a single SPAN circuit."""

    def __init__(self, entity_id: str, friendly_name: str, panel: str) -> None:
        self.entity_id = entity_id
        self.friendly_name = friendly_name
        self.panel = panel
        self.last_power: float | None = None
        self.was_loaded: bool = False
        self.zero_since: float | None = None  # timestamp when went to zero
        self.alerted: bool = False
        self.controllable: bool = True  # discovered from SPAN breaker switch


class SPANCircuitMonitor:
    """Monitors SPAN panel circuits for anomalies.

    Auto-discovers circuit entities on startup by scanning for
    sensor.span_panel_*_power entities.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize circuit monitor."""
        self.hass = hass
        self._circuits: dict[str, CircuitInfo] = {}
        self._discovered = False
        self._anomalies: list[dict[str, Any]] = []

    def discover_circuits(self) -> int:
        """Auto-discover SPAN circuit power entities from HA state machine."""
        count = 0
        for state in self.hass.states.async_all("sensor"):
            entity_id = state.entity_id
            if not entity_id.startswith("sensor.span_panel_") or not entity_id.endswith("_power"):
                continue
            # Skip aggregate/feed-through/main meter entities
            skip_patterns = (
                "current_power", "feed_through_power",
                "a_v_main_power",  # aggregate AV
            )
            base_name = entity_id.replace("sensor.span_panel_", "").replace("_power", "")
            if any(p in entity_id for p in skip_patterns):
                continue

            friendly = state.attributes.get("friendly_name", entity_id)
            panel = "left" if "_2" in entity_id or "Span Left" in friendly else "right"
            self._circuits[entity_id] = CircuitInfo(entity_id, friendly, panel)
            count += 1

        self._discovered = True
        _LOGGER.info("SPAN circuit monitor: discovered %d circuits", count)
        return count

    def check_anomalies(self) -> list[dict[str, Any]]:
        """Check all circuits for anomalies. Returns new anomalies found."""
        if not self._discovered:
            self.discover_circuits()

        import time
        now = time.time()
        new_anomalies: list[dict[str, Any]] = []

        for entity_id, circuit in self._circuits.items():
            state = self.hass.states.get(entity_id)
            if state is None or state.state in ("unknown", "unavailable"):
                continue

            try:
                power = float(state.state)
            except (ValueError, TypeError):
                continue

            # Track if circuit was recently loaded
            if power > NORMALLY_LOADED_THRESHOLD_W:
                circuit.was_loaded = True
                circuit.zero_since = None
                circuit.alerted = False

            # Detect sudden zero on a normally loaded circuit
            if power <= NORMALLY_LOADED_THRESHOLD_W and circuit.was_loaded:
                if circuit.zero_since is None:
                    circuit.zero_since = now
                elif (
                    not circuit.alerted
                    and (now - circuit.zero_since) > TRIPPED_BREAKER_THRESHOLD_SECONDS
                ):
                    anomaly = {
                        "type": "tripped_breaker",
                        "circuit": circuit.friendly_name,
                        "entity_id": entity_id,
                        "panel": circuit.panel,
                        "last_power": circuit.last_power,
                        "zero_duration_seconds": int(now - circuit.zero_since),
                    }
                    new_anomalies.append(anomaly)
                    circuit.alerted = True
                    _LOGGER.warning(
                        "Circuit anomaly: %s — possible tripped breaker (zero for %ds)",
                        circuit.friendly_name,
                        int(now - circuit.zero_since),
                    )

            circuit.last_power = power

        self._anomalies = new_anomalies
        return new_anomalies

    def get_status(self) -> dict[str, Any]:
        """Return circuit monitor status for sensor."""
        active_anomalies = [
            c.friendly_name for c in self._circuits.values()
            if c.alerted
        ]
        return {
            "circuits_monitored": len(self._circuits),
            "discovered": self._discovered,
            "active_anomalies": active_anomalies,
            "anomaly_count": len(active_anomalies),
        }

    @property
    def latest_anomalies(self) -> list[dict[str, Any]]:
        """Return the latest anomaly list from the last check."""
        return self._anomalies


class GeneratorMonitor:
    """Monitors Generac generator status."""

    def __init__(
        self,
        hass: HomeAssistant,
        status_entity: str | None = None,
    ) -> None:
        """Initialize generator monitor."""
        self.hass = hass
        self._status_entity = status_entity or DEFAULT_GENERATOR_STATUS_ENTITY
        self._last_status: str = GEN_UNAVAILABLE
        self._alerted_running: bool = False

    @property
    def status(self) -> str:
        """Current generator status."""
        state = self.hass.states.get(self._status_entity)
        if state is None or state.state in ("unknown", "unavailable"):
            return GEN_UNAVAILABLE
        raw = state.state.lower()
        if "run" in raw:
            return GEN_RUNNING
        if "ready" in raw or "standby" in raw:
            return GEN_STANDBY
        return GEN_OFF

    def check_alerts(self) -> list[dict[str, Any]]:
        """Check for generator status changes that warrant alerts."""
        alerts: list[dict[str, Any]] = []
        current = self.status

        if current == GEN_RUNNING and not self._alerted_running:
            alerts.append({
                "type": "generator_running",
                "message": "Generator is running — possible power outage",
                "severity": "critical",
            })
            self._alerted_running = True

        if current != GEN_RUNNING:
            self._alerted_running = False

        self._last_status = current
        return alerts

    def get_status(self) -> dict[str, Any]:
        """Return generator status for sensor."""
        return {
            "status": self.status,
            "entity": self._status_entity,
        }
