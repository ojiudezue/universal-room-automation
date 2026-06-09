"""Shared unit normalization helpers for the energy device class.

Bug Class #30 (Unit-of-Measurement Drift) fix on the energy surface.
Power-class normalization remains hand-rolled at the 5 existing sites
(domain_coordinators/energy_battery.py, energy_pool.py); see
PLANNING_energy_unit_normalization_and_attribution.md for the
explicit scoping decision to NOT refactor those in this cycle.
"""
from __future__ import annotations

from typing import Any

_UNAVAILABLE_STATES: frozenset[str] = frozenset({"unknown", "unavailable", "none", ""})


def energy_state_to_kwh(state: Any) -> float | None:
    """Read an energy device-class HA state and return value in kWh.

    Handles ``unit_of_measurement`` ∈ {kWh, kwh, Wh, wh, MWh, mwh}
    case-insensitive. Returns ``None`` when:

    - state is None
    - state.state is unavailable / unknown / empty / "none"
    - state.state is not parseable as float
    - unit_of_measurement is present but not a recognized energy unit

    When ``unit_of_measurement`` is absent, the raw value is returned
    AS IF kWh — sources that omit a uom are taken at face value to
    match HA's default energy semantics. This matches the pre-fix
    behavior at coordinator.py:1876 for already-correct sources.
    """
    if state is None:
        return None
    raw = state.state
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip().lower() in _UNAVAILABLE_STATES:
        return None
    try:
        value = float(raw)
    except (ValueError, TypeError):
        return None

    uom = ""
    try:
        attrs = state.attributes or {}
        uom = (attrs.get("unit_of_measurement") or "").strip()
    except Exception:
        uom = ""

    if not uom:
        return value

    uom_lc = uom.lower()
    if uom_lc == "kwh":
        return value
    if uom_lc == "wh":
        return value / 1000.0
    if uom_lc == "mwh":
        return value * 1000.0

    # Unrecognized unit on an energy-class read — refuse rather than
    # silently misattribute. Bug Class #30.
    return None


def today_delta_kwh(
    tracker: dict[str, dict[str, Any]],
    sensor_id: str,
    current_kwh: float,
    today,
) -> float:
    """Return today-scoped delta for an assumed-cumulative kWh reading.

    D2 in-memory today-delta helper, factored out of
    ``EnergyCoverageDeltaSensor._today_delta_kwh`` so it is testable
    without HA installed. The class method delegates here.

    ``tracker`` is mutated in place: ``tracker[sensor_id]`` becomes
    ``{"baseline_kwh": float, "anchor_date": today}``. First observation
    and date rollovers re-anchor and return 0.0. Negative deltas (counter
    reset / sensor swap) also re-anchor (returns 0.0). Subsequent
    same-date reads return ``current_kwh - baseline_kwh``.
    """
    entry = tracker.get(sensor_id)
    if entry is None or entry.get("anchor_date") != today:
        tracker[sensor_id] = {
            "baseline_kwh": current_kwh,
            "anchor_date": today,
        }
        return 0.0
    delta = current_kwh - entry["baseline_kwh"]
    if delta < 0:
        tracker[sensor_id]["baseline_kwh"] = current_kwh
        return 0.0
    return delta
