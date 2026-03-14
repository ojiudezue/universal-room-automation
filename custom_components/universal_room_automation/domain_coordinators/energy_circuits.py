"""SPAN/Emporia circuit monitoring and anomaly detection for Energy Coordinator.

Sub-Cycle E3: Auto-discover SPAN circuits, monitor power per circuit,
detect tripped breakers (sudden zero), alert via NM.
v3.13.2: MetricBaseline per-circuit z-score anomaly detection.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from .coordinator_diagnostics import MetricBaseline

_LOGGER = logging.getLogger(__name__)

# How long a circuit must be at zero to trigger tripped breaker alert (seconds)
TRIPPED_BREAKER_THRESHOLD_SECONDS = 300
# Minimum recent power for a circuit to be considered "normally loaded"
NORMALLY_LOADED_THRESHOLD_W = 5.0
# Minimum cumulative energy (Wh) a circuit must have delivered before tripped alerts fire.
# Prevents alerts on circuits that briefly spike above NORMALLY_LOADED_THRESHOLD_W
# but never actually deliver meaningful energy.
MINIMUM_LOADED_ENERGY_WH = 50.0

# MetricBaseline thresholds for circuit power z-scores
CIRCUIT_Z_ADVISORY = 3.0   # Log advisory
CIRCUIT_Z_ALERT = 4.0      # Generate anomaly alert
CIRCUIT_MIN_SAMPLES = 60   # ~5 hours at 5min intervals
CIRCUIT_ZSCORE_COOLDOWN_S = 1800  # 30min cooldown between repeated z-score alerts

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
        self.cumulative_energy_wh: float = 0.0  # Track energy delivery
        self._last_check_time: float | None = None  # For energy integration


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
        # v3.13.2: Per-circuit power baselines for z-score anomaly detection
        self._power_baselines: dict[str, MetricBaseline] = {}
        # v3.13.3: Dedup z-score alerts — cooldown per circuit (epoch timestamp)
        self._zscore_alerted: dict[str, float] = {}

    def discover_circuits(self) -> int:
        """Auto-discover SPAN circuit power entities from HA state machine."""
        count = 0
        skipped_unknown = 0
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

            # v3.16: Skip unfilled/unknown breaker slots — these generate
            # spurious tripped-breaker alerts because they briefly draw power
            # during panel resets but never deliver meaningful energy.
            friendly_lower = friendly.lower()
            if any(kw in friendly_lower for kw in (
                "unknown", "unfilled", "unused", "spare", "empty",
            )):
                skipped_unknown += 1
                continue

            panel = "left" if "_2" in entity_id or "Span Left" in friendly else "right"
            self._circuits[entity_id] = CircuitInfo(entity_id, friendly, panel)
            count += 1

        self._discovered = True
        _LOGGER.info(
            "SPAN circuit monitor: discovered %d circuits (skipped %d unknown/unfilled)",
            count, skipped_unknown,
        )
        return count

    def _get_power_baseline(self, entity_id: str) -> MetricBaseline:
        """Get or create a power baseline for a circuit."""
        if entity_id not in self._power_baselines:
            # Use circuit-friendly name as scope for readability
            circuit = self._circuits.get(entity_id)
            scope = circuit.friendly_name if circuit else entity_id
            self._power_baselines[entity_id] = MetricBaseline(
                metric_name="circuit_power",
                coordinator_id="energy",
                scope=scope,
            )
        return self._power_baselines[entity_id]

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

            # v3.13.2: Z-score anomaly detection via MetricBaseline
            baseline = self._get_power_baseline(entity_id)
            if baseline.sample_count >= CIRCUIT_MIN_SAMPLES and power > 0:
                z = baseline.z_score(power)
                if z >= CIRCUIT_Z_ALERT:
                    # v3.13.3: Dedup — only alert if cooldown has elapsed
                    last_alert = self._zscore_alerted.get(entity_id, 0)
                    if (now - last_alert) >= CIRCUIT_ZSCORE_COOLDOWN_S:
                        anomaly = {
                            "type": "consumption_anomaly",
                            "circuit": circuit.friendly_name,
                            "entity_id": entity_id,
                            "panel": circuit.panel,
                            "power": power,
                            "z_score": round(z, 2),
                            "baseline_mean": round(baseline.mean, 1),
                            "baseline_std": round(baseline.std, 1),
                        }
                        new_anomalies.append(anomaly)
                        self._zscore_alerted[entity_id] = now
                        _LOGGER.warning(
                            "Circuit anomaly: %s — unusual consumption %.0fW "
                            "(z=%.1f, mean=%.0fW, std=%.0fW)",
                            circuit.friendly_name, power, z,
                            baseline.mean, baseline.std,
                        )
                elif z >= CIRCUIT_Z_ADVISORY:
                    _LOGGER.debug(
                        "Circuit advisory: %s — elevated consumption %.0fW (z=%.1f)",
                        circuit.friendly_name, power, z,
                    )
            # Update baseline with current reading (after check)
            if power >= 0:
                baseline.update(power)

            # Track cumulative energy delivery (trapezoidal integration)
            if circuit._last_check_time is not None and power > 0:
                dt_hours = (now - circuit._last_check_time) / 3600.0
                prev = circuit.last_power if circuit.last_power is not None else power
                avg_power = (power + prev) / 2.0
                circuit.cumulative_energy_wh += avg_power * dt_hours
            circuit._last_check_time = now

            # Track if circuit was recently loaded
            if power > NORMALLY_LOADED_THRESHOLD_W:
                circuit.was_loaded = True
                circuit.zero_since = None
                circuit.alerted = False

            # Detect sudden zero on a circuit that has delivered real energy.
            # was_loaded + cumulative energy guard prevents false alerts on circuits
            # that briefly spike but never deliver meaningful energy.
            if (power <= NORMALLY_LOADED_THRESHOLD_W
                    and circuit.was_loaded
                    and circuit.cumulative_energy_wh >= MINIMUM_LOADED_ENERGY_WH):
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
        baselines_active = sum(
            1 for b in self._power_baselines.values()
            if b.sample_count >= CIRCUIT_MIN_SAMPLES
        )
        return {
            "circuits_monitored": len(self._circuits),
            "discovered": self._discovered,
            "active_anomalies": active_anomalies,
            "anomaly_count": len(active_anomalies),
            "baselines_tracked": len(self._power_baselines),
            "baselines_active": baselines_active,
        }

    @property
    def latest_anomalies(self) -> list[dict[str, Any]]:
        """Return the latest anomaly list from the last check."""
        return self._anomalies

    def get_baselines_for_save(self) -> dict[str, MetricBaseline]:
        """Return power baselines dict for persistence."""
        return self._power_baselines

    def restore_baselines(self, baselines: dict[str, MetricBaseline]) -> None:
        """Restore power baselines from persistence (merge, don't replace)."""
        self._power_baselines.update(baselines)


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
