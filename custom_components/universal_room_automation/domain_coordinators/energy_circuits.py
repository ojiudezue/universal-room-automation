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

# How long a circuit must be at zero to trigger tripped breaker alert (seconds).
# NM Cycle A (2026-07-20): 300 → 900 (module default). Runtime value is
# read from CoordinatorManager options via nm_cycle_a_knob(); this constant
# is now the fallback default. Rung-2 promotion of the actual config field
# lands in Cycle A-2.
TRIPPED_BREAKER_THRESHOLD_SECONDS = 900  # legacy alias — see DEFAULT_TRIPPED_BREAKER_ZERO_WINDOW_S
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

    def __init__(
        self,
        entity_id: str,
        friendly_name: str,
        panel: str,
        unique_id: str | None = None,
    ) -> None:
        self.entity_id = entity_id
        self.friendly_name = friendly_name
        self.panel = panel
        # v5.12.0 SPAN circuit-identity re-key: stable per-circuit id from HA
        # entity registry. Baselines are scoped to this instead of the
        # user-editable friendly_name (which SPAN re-syncs on rename).
        # None only when the entity has no registry entry (extras path, or
        # a race during boot); scope then falls back to entity_id.
        self.unique_id: str | None = unique_id
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

    def __init__(
        self,
        hass: HomeAssistant,
        extra_entities: list[str] | None = None,
        exclude_entities: list[str] | None = None,
        autodiscover_span: bool = True,
    ) -> None:
        """Initialize circuit monitor.

        v4.2.0: Accepts extra circuit entities and autodiscover toggle.
        v4.2.1: Accepts exclude list to filter out sub-panel feed circuits.
        """
        self.hass = hass
        self._circuits: dict[str, CircuitInfo] = {}
        self._discovered = False
        self._anomalies: list[dict[str, Any]] = []
        self._extra_entities = extra_entities or []
        self._exclude_entities = set(exclude_entities or [])
        self._autodiscover_span = autodiscover_span
        # v3.13.2: Per-circuit power baselines for z-score anomaly detection
        self._power_baselines: dict[str, MetricBaseline] = {}
        # v3.13.3: Dedup z-score alerts — cooldown per circuit (epoch timestamp)
        self._zscore_alerted: dict[str, float] = {}

    def _lookup_unique_id(self, entity_id: str) -> str | None:
        """Return the entity-registry unique_id for `entity_id`, or None.

        v5.12.0 SPAN circuit-identity re-key. Guarded — entity registry may
        not be populated at boot, or the entity may be state-only (no
        registry entry). Falls back to None; the scope chain in
        `_get_power_baseline` then uses entity_id.
        """
        try:
            from homeassistant.helpers import entity_registry as er
            registry = er.async_get(self.hass)
            entry = registry.async_get(entity_id)
            if entry is None:
                _LOGGER.debug(
                    "Circuit %s has no entity-registry entry; scope falls back to entity_id",
                    entity_id,
                )
                return None
            return entry.unique_id
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug(
                "Circuit unique_id lookup failed for %s: %s (fallback to entity_id)",
                entity_id, e,
            )
            return None

    def discover_circuits(self, force: bool = False) -> int:
        """Discover circuit power entities from multiple sources.

        v4.2.0: Three-tier discovery:
        1. SPAN auto-discover (if enabled) — existing pattern
        2. Extra entities — manually configured power sensors
        All deduplicated by entity_id.
        v5.12.0: Populates CircuitInfo.unique_id from entity registry so
        anomaly baselines can be persisted keyed on a rename-stable id.
        v5.14.1: ``force=True`` clears the existing cache and re-runs
        discovery — used by the post-EVENT_HOMEASSISTANT_STARTED migration
        re-pass to pick up SPAN circuits that hadn't populated
        ``hass.states`` yet during the initial (setup-time) discovery. The
        default ``force=False`` preserves the one-shot semantics that
        ``check_anomalies`` relies on.
        """
        if force:
            self._circuits = {}
            # v5.14.1 review MED-3: clear stale entity→baseline entries too,
            # so a force-rediscovery can't silently mask circuit renames via
            # leftover cache (restore re-merges from DB immediately after).
            self._power_baselines = {}
            self._discovered = False
        count = 0
        skipped_unknown = 0

        # Tier 1: SPAN auto-discovery (existing behavior)
        if self._autodiscover_span:
            for state in self.hass.states.async_all("sensor"):
                entity_id = state.entity_id
                if not entity_id.startswith("sensor.span_panel_") or not entity_id.endswith("_power"):
                    continue
                skip_patterns = (
                    "current_power", "feed_through_power",
                    "a_v_main_power",
                )
                if any(p in entity_id for p in skip_patterns):
                    continue

                friendly = state.attributes.get("friendly_name", entity_id)
                friendly_lower = friendly.lower()
                if any(kw in friendly_lower for kw in (
                    "unknown", "unfilled", "unused", "spare", "empty",
                )):
                    skipped_unknown += 1
                    continue

                panel = "left" if "_2" in entity_id or "Span Left" in friendly else "right"
                uid = self._lookup_unique_id(entity_id)
                self._circuits[entity_id] = CircuitInfo(
                    entity_id, friendly, panel, unique_id=uid,
                )
                count += 1

        # Tier 2: Extra manually-configured entities
        for entity_id in self._extra_entities:
            if entity_id in self._circuits:
                continue  # Dedup
            state = self.hass.states.get(entity_id)
            if state is None:
                _LOGGER.warning(
                    "Configured circuit entity %s not found — may not be loaded yet",
                    entity_id,
                )
                continue
            friendly = state.attributes.get("friendly_name", entity_id)
            uid = self._lookup_unique_id(entity_id)
            self._circuits[entity_id] = CircuitInfo(
                entity_id, friendly, "custom", unique_id=uid,
            )
            count += 1

        # v4.2.1: Remove excluded circuits (e.g., sub-panel feed that overlaps Emporia)
        excluded = 0
        for entity_id in self._exclude_entities:
            if entity_id in self._circuits:
                del self._circuits[entity_id]
                excluded += 1

        self._discovered = True
        _LOGGER.info(
            "Circuit monitor: %d circuits (skipped %d unknown, %d extra, %d excluded)",
            len(self._circuits), skipped_unknown, len(self._extra_entities), excluded,
        )
        return len(self._circuits)

    def _get_power_baseline(self, entity_id: str) -> MetricBaseline:
        """Get or create a power baseline for a circuit.

        v5.12.0 SPAN circuit-identity re-key: scope resolution order is
        unique_id → entity_id (F10 doc fix — friendly_name is DELIBERATELY
        excluded from the runtime chain because the whole point of the
        cycle is to move OFF friendly_name; the migration path in
        _restore_energy_baselines handles legacy friendly-scoped rows
        exactly once, then rewrites them to unique_id). entity_id is
        stable under SPAN's circuit-number naming mode but not under a
        SPAN-app rename in circuit-name mode. Fallback to entity_id is
        DEBUG-logged so post-migration boots surface any circuits that
        still landed on the fallback path.
        """
        if entity_id not in self._power_baselines:
            circuit = self._circuits.get(entity_id)
            if circuit is not None and circuit.unique_id:
                scope = circuit.unique_id
            elif circuit is not None:
                scope = entity_id
                _LOGGER.debug(
                    "Circuit baseline scope fell back to entity_id for %s "
                    "(no unique_id — check entity registry)",
                    entity_id,
                )
            else:
                scope = entity_id
                _LOGGER.debug(
                    "Circuit baseline scope fell back to entity_id for %s "
                    "(no CircuitInfo)",
                    entity_id,
                )
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
                elif not circuit.alerted:
                    # NM Cycle A A1: rung-2-ready knob (default 900s).
                    from ..const import (
                        CONF_TRIPPED_BREAKER_ZERO_WINDOW_S,
                        DEFAULT_TRIPPED_BREAKER_ZERO_WINDOW_S,
                    )
                    from ._nm_cycle_a import nm_cycle_a_knob
                    window_s = nm_cycle_a_knob(
                        self.hass,
                        CONF_TRIPPED_BREAKER_ZERO_WINDOW_S,
                        DEFAULT_TRIPPED_BREAKER_ZERO_WINDOW_S,
                    )
                    if (now - circuit.zero_since) <= window_s:
                        # not yet — record and continue
                        circuit.last_power = power
                        continue
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
