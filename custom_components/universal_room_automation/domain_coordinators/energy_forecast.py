"""Energy forecasting and prediction for Energy Coordinator.

Sub-Cycle E5: Daily energy prediction, battery full time estimate,
forecast accuracy tracking with Bayesian adjustment.
v3.7.12: Sunrise refresh, DB-backed accuracy, temperature regression.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .energy_const import (
    CONF_R1_ESTIMATOR_SHADOW_ONLY,
    CONSUMPTION_REGRESSION_V1,
    DEFAULT_SOLCAST_REMAINING_ENTITY,
    DEFAULT_SOLCAST_TODAY_ENTITY,
    DEFAULT_WEATHER_ENTITY,
    PRED_CONSUMPTION_SOURCE_DOW_LEGACY,
    PRED_CONSUMPTION_SOURCE_FALLBACK,
    PRED_CONSUMPTION_SOURCE_V1_REGRESSION,
)

_LOGGER = logging.getLogger(__name__)

# Fallback battery capacity if Envoy entity unavailable (kWh)
BATTERY_TOTAL_CAPACITY_KWH_FALLBACK = 40.0
# Average charge rate from solar in kW
AVERAGE_CHARGE_RATE_KW = 3.5

# Rolling window for accuracy tracking
ACCURACY_WINDOW_DAYS = 30

# --- Forecast-accuracy display constants (rung 1 — module constants) ---
# Bounded pct-error metric floor + cap; see PLANNING_forecast_accuracy_fix.md.
MIN_DENOMINATOR_KWH = 5.0
PCT_ERROR_BOUND = 200.0
POOR_THRESHOLD_PCT = 50.0
STALE_EVAL_DAYS = 2

# Comfort midpoint for temperature regression (°F)
COMFORT_MIDPOINT_F = 72.0


class DailyEnergyPredictor:
    """Generates daily energy forecasts at start of day.

    Combines:
    - Solcast PV forecast (primary)
    - Weather conditions (secondary)
    - Historical baseline (Bayesian, accumulated over time)
    - Temperature regression (after 30+ days of paired data)
    """

    def __init__(
        self,
        hass: HomeAssistant,
        battery_soc_entity: str | None = None,
        solcast_today_entity: str | None = None,
        solcast_remaining_entity: str | None = None,
        weather_entity: str | None = None,
        battery_capacity_entity: str | None = None,
        bayesian_predictor: Any | None = None,
        power_profiles: Any | None = None,
        room_ids: list[str] | None = None,
        occupancy_enabled_fn: Any | None = None,
        battery_power_w_fn: Any | None = None,
    ) -> None:
        """Initialize daily predictor."""
        self.hass = hass
        # v4.3.1: envoy-derived entities (battery_soc, battery_capacity) have no
        # production fallback; B1 envoy validation gate ensures they're populated
        # when EC is enabled. Solcast/Weather still have legitimate hardcoded
        # defaults for non-Envoy users.
        self._battery_soc_entity = battery_soc_entity
        self._solcast_today_entity = solcast_today_entity or DEFAULT_SOLCAST_TODAY_ENTITY
        self._solcast_remaining_entity = solcast_remaining_entity or DEFAULT_SOLCAST_REMAINING_ENTITY
        self._weather_entity = weather_entity or DEFAULT_WEATHER_ENTITY
        self._battery_capacity_entity = battery_capacity_entity

        # v4.1.1 B4 L2: Occupancy-weighted prediction
        # bayesian_predictor is a callable (lazy lookup) to survive integration reloads
        self._get_bayesian = bayesian_predictor if callable(bayesian_predictor) else lambda: bayesian_predictor
        self._power_profiles = power_profiles
        self._room_ids = room_ids or []
        self._occupancy_enabled_fn = occupancy_enabled_fn
        # H2 (2026-07-13): live battery charge-power callable (Watts;
        # positive = charging, negative = discharging — Envoy convention).
        # None → fall back to solar-forecast model.
        self._battery_power_w_fn = battery_power_w_fn

        # H2 (2026-07-13): rich attrs for the battery_full_time surface.
        # basis: 'current_rate' | 'solar_forecast' | 'unavailable'
        # missing_input: 'solcast' | 'soc' | None when inputs available
        self._battery_full_time_attrs: dict[str, Any] = {}

        # Today's prediction
        self._prediction_date: str = ""
        self._predicted_production_kwh: float | None = None
        self._predicted_consumption_kwh: float | None = None
        self._predicted_net_kwh: float | None = None
        self._predicted_grid_import_kwh: float | None = None
        self._battery_full_time: str | None = None

        # R1: source marker for `energy_daily.predicted_consumption_source`.
        # One of PRED_CONSUMPTION_SOURCE_{V1_REGRESSION,DOW_LEGACY,FALLBACK}.
        # ``_predicted_consumption_kwh`` above is the CONSUMED value; while the
        # shadow gate is on (CONF_R1_ESTIMATOR_SHADOW_ONLY), the consumed value
        # stays on the legacy path and the v1 number is stashed alongside as
        # shadow-only so R2's future consumer gate (I-NE5) can gate on it.
        self._predicted_consumption_source: str | None = None
        self._shadow_predicted_consumption_kwh: float | None = None
        self._shadow_predicted_base_kwh: float | None = None
        self._shadow_predicted_ev_kwh: float | None = None

        # Historical baselines (day_of_week -> consumption kWh list)
        self._consumption_history: dict[int, deque] = {
            d: deque(maxlen=8) for d in range(7)
        }

        # Bayesian adjustment factor (starts at 1.0, adjusts with accuracy)
        self._adjustment_factor: float = 1.0

        # Temperature regression (learned after 30+ days)
        self._temp_regression_base: float | None = None
        self._temp_regression_coeff: float | None = None

        # Sunrise refresh tracking
        self._sunrise_refreshed_date: str = ""

        # Temperature captured at prediction time (more representative than midnight)
        self._prediction_temperature: float | None = None

    def _get_float(self, entity_id: str | None) -> float | None:
        """Get numeric state from entity. None entity_id → None (v4.3.1)."""
        if entity_id is None:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _get_current_temperature(self) -> float | None:
        """Get current temperature from weather entity (°F)."""
        weather_state = self.hass.states.get(self._weather_entity)
        if weather_state and weather_state.attributes:
            temp = weather_state.attributes.get("temperature")
            if temp is not None:
                try:
                    return float(temp)
                except (ValueError, TypeError):
                    pass
        return None

    def set_temp_regression(self, base: float, coeff: float) -> None:
        """Set learned temperature regression coefficients."""
        self._temp_regression_base = base
        self._temp_regression_coeff = coeff
        _LOGGER.info(
            "Temperature regression loaded: base=%.1f coeff=%.3f",
            base, coeff,
        )

    def generate_prediction(self) -> dict[str, Any]:
        """Generate daily energy prediction. Called once at start of day.

        Retries if Solcast was unavailable on first attempt (e.g., HA startup).
        """
        now = dt_util.now()
        today = now.date().isoformat()

        if self._prediction_date == today and self._predicted_production_kwh is not None:
            return self._get_current_prediction()

        self._prediction_date = today
        self._do_prediction(now)
        return self._get_current_prediction()

    def refresh_at_sunrise(self) -> bool:
        """Re-generate prediction with fresh Solcast data at sunrise.

        Returns True if a refresh was performed.
        """
        now = dt_util.now()
        today = now.date().isoformat()

        if self._sunrise_refreshed_date == today:
            return False  # Already refreshed today

        # Check if we're within 30 min after sunrise
        sunrise = self._get_sunrise(now)
        if sunrise is None:
            return False
        minutes_after = (now - sunrise).total_seconds() / 60
        if minutes_after < 0 or minutes_after > 30:
            return False

        self._sunrise_refreshed_date = today
        _LOGGER.info("Sunrise refresh: re-generating prediction with updated Solcast")
        self._do_prediction(now)
        return True

    def _get_sunrise(self, now: datetime) -> datetime | None:
        """Get today's sunrise from HA sun entity."""
        sun = self.hass.states.get("sun.sun")
        if sun is None:
            return None
        rising = sun.attributes.get("next_rising")
        if rising is None:
            return None
        try:
            sunrise_dt = dt_util.parse_datetime(rising)
            if sunrise_dt is None:
                return None
            # If next_rising is today, use it directly (before sunrise)
            if sunrise_dt.date() == now.date():
                return sunrise_dt
            # After sunrise, next_rising points to tomorrow — estimate today's
            approx_today = sunrise_dt - timedelta(hours=24)
            if approx_today.date() == now.date():
                return approx_today
        except (ValueError, TypeError):
            pass
        return None

    def _do_prediction(self, now: datetime) -> None:
        """Core prediction logic, used by both generate and sunrise refresh."""
        # PV production estimate from Solcast
        pv_forecast = self._get_float(self._solcast_today_entity)
        self._predicted_production_kwh = pv_forecast

        # Consumption estimate
        temp = self._get_current_temperature()
        self._prediction_temperature = temp
        adjusted_consumption = self._estimate_consumption(now, temp)
        self._predicted_consumption_kwh = round(adjusted_consumption, 1)

        # Net position (positive = net export, negative = net import)
        if pv_forecast is not None:
            self._predicted_net_kwh = round(pv_forecast - adjusted_consumption, 1)
        else:
            self._predicted_net_kwh = None

        # Battery full time estimate
        self._estimate_battery_full_time(now)

        _LOGGER.info(
            "Daily prediction: PV=%.1f kWh, consumption=%.1f kWh, net=%.1f kWh",
            pv_forecast or 0,
            adjusted_consumption,
            self._predicted_net_kwh or 0,
        )

    # -----------------------------------------------------------------
    # R1 v1 estimator — reviewed constants + EV term (season + HDD/CDD)
    # -----------------------------------------------------------------
    def _compute_v1(
        self, now: datetime, temp: float | None
    ) -> tuple[float | None, float | None, float, str]:
        """Return (total_kwh, base_kwh, ev_kwh, source).

        Returns (None, None, 0.0, FALLBACK) when temp is missing — the v1 arm
        requires temp; the caller decides fallback semantics.
        """
        if temp is None:
            return None, None, 0.0, PRED_CONSUMPTION_SOURCE_FALLBACK

        c = CONSUMPTION_REGRESSION_V1
        cdd = max(temp - c["cdd_base_f"], 0.0)
        hdd = max(c["hdd_base_f"] - temp, 0.0)
        m = now.month
        if m in (12, 1, 2):
            season_dummy = c["season_winter"]
        elif m in (3, 4, 5):
            season_dummy = c["season_spring"]
        elif m in (6, 7, 8):
            season_dummy = c["season_summer"]
        else:
            season_dummy = c["season_fall"]

        base_kwh = (
            c["base"]
            + c["cdd_coeff"] * cdd
            + c["hdd_coeff"] * hdd
            + season_dummy
        )

        # EV term — single reviewed constant, gated by ev_era_start date.
        # Parsimony per operator directive 2026-07-16: no per-session /
        # plan-aware modeling in R1. Richer term is R8-era.
        ev_era = datetime.strptime(c["ev_era_start"], "%Y-%m-%d").date()
        ev_kwh = c["ev_term_kwh"] if now.date() >= ev_era else 0.0

        total = base_kwh + ev_kwh
        return total, base_kwh, ev_kwh, PRED_CONSUMPTION_SOURCE_V1_REGRESSION

    # -----------------------------------------------------------------
    # Legacy estimator (shadow-phase fallback ONLY).
    # -----------------------------------------------------------------
    # When CONF_R1_ESTIMATOR_SHADOW_ONLY flips False (R2 prerequisite), this
    # arm becomes unreachable and can be removed in a follow-on cycle. Per
    # B0 §E day-of-week carries R²=0.01 — deliberately kept only as the
    # rollback path (I-NE6: rollback is a constant flip, no code revert).
    def _compute_legacy(
        self, now: datetime, temp: float | None
    ) -> tuple[float, str]:
        dow = now.weekday()
        history = list(self._consumption_history[dow])
        if history:
            baseline = sum(history) / len(history)
            source = PRED_CONSUMPTION_SOURCE_DOW_LEGACY
        else:
            baseline = 45.0  # legacy default (large home w/ AC/pool)
            source = PRED_CONSUMPTION_SOURCE_FALLBACK

        if (
            self._temp_regression_base is not None
            and self._temp_regression_coeff is not None
            and temp is not None
        ):
            regression_estimate = (
                self._temp_regression_base
                + self._temp_regression_coeff * abs(temp - COMFORT_MIDPOINT_F)
            )
            adjusted = regression_estimate * 0.7 + baseline * 0.3
        else:
            temp_adjustment = 1.0
            if temp is not None:
                if temp > 95:
                    temp_adjustment = 1.3
                elif temp > 85:
                    temp_adjustment = 1.15
                elif temp > 75:
                    temp_adjustment = 1.0
                elif temp < 40:
                    temp_adjustment = 1.2
                elif temp < 55:
                    temp_adjustment = 1.05
                else:
                    temp_adjustment = 0.9
            adjusted = baseline * temp_adjustment
        return adjusted, source

    def _estimate_consumption(self, now: datetime, temp: float | None) -> float:
        """Estimate daily consumption.

        R1 (2026-07-16): computes BOTH the v1 regression arm and the legacy
        DOW arm; publishes whichever the shadow gate selects. Shadow ON =
        legacy is consumed, v1 is stashed as shadow-only (I-NE5). Shadow OFF
        = v1 is consumed and legacy is unreachable except as a fallback when
        v1 has no temperature.
        """
        # 1. v1 arm — always compute so shadow scoring has a number.
        v1_total, v1_base, v1_ev, v1_source = self._compute_v1(now, temp)

        # 2. Legacy arm — computed while shadow gate is on OR when v1 has no
        #    temp signal (fallback).
        legacy_needed = CONF_R1_ESTIMATOR_SHADOW_ONLY or v1_total is None
        legacy_val: float | None = None
        legacy_source = PRED_CONSUMPTION_SOURCE_FALLBACK
        if legacy_needed:
            legacy_val, legacy_source = self._compute_legacy(now, temp)

        # 3. Decide which is CONSUMED.
        if CONF_R1_ESTIMATOR_SHADOW_ONLY:
            adjusted = legacy_val if legacy_val is not None else 45.0
            source = legacy_source
        else:
            if v1_total is not None:
                adjusted = v1_total
                source = v1_source
            else:
                adjusted = legacy_val if legacy_val is not None else 45.0
                source = legacy_source

        # 4. Stash shadow-only components for observability.
        self._shadow_predicted_consumption_kwh = (
            round(v1_total, 2) if v1_total is not None else None
        )
        self._shadow_predicted_base_kwh = (
            round(v1_base, 2) if v1_base is not None else None
        )
        self._shadow_predicted_ev_kwh = round(v1_ev, 2)

        if CONF_R1_ESTIMATOR_SHADOW_ONLY and v1_total is not None:
            _LOGGER.info(
                "R1 shadow: v1=%.1f kWh (base=%.1f, ev=%.1f) — CONSUMED "
                "path stays legacy=%.1f (source=%s)",
                v1_total, v1_base, v1_ev, adjusted, legacy_source,
            )

        # 5. Publish source marker for DAO write.
        self._predicted_consumption_source = source

        # v4.1.1 B4 L2: Occupancy-weighted blending (gated by toggle, off by default)
        bayesian = self._get_bayesian() if self._get_bayesian else None
        if (
            self._occupancy_enabled_fn
            and self._occupancy_enabled_fn()
            and bayesian
            and self._power_profiles
        ):
            occupancy_estimate = self._occupancy_weighted_estimate(now, bayesian)
            if occupancy_estimate is not None:
                weight = self._occupancy_blend_weight(bayesian)
                if weight > 0:
                    adjusted = adjusted * (1 - weight) + occupancy_estimate * weight

        return max(0.1, adjusted * self._adjustment_factor)

    def _occupancy_weighted_estimate(self, now: datetime, bayesian: Any = None) -> float | None:
        """Sum occupancy-weighted load across all rooms by time bin."""
        if bayesian is None:
            bayesian = self._get_bayesian() if self._get_bayesian else None
        if bayesian is None:
            return None

        day_type = 1 if now.weekday() >= 5 else 0
        rooms_kwh = 0.0
        rooms_with_data = 0

        for room_id in self._room_ids:
            for time_bin in range(6):
                hours_in_bin = BIN_HOURS[time_bin]
                baseline_w = self._power_profiles.get_baseline_watts(
                    room_id, time_bin, day_type)
                if baseline_w is None:
                    continue

                p_occupied = bayesian.predict_room_occupancy(
                    room_id, time_bin, day_type)
                if p_occupied is None:
                    p_occupied = 0.5  # No data — assume 50%

                standby_w = self._power_profiles.get_standby_watts(room_id) or 0
                weighted_w = standby_w + (baseline_w - standby_w) * p_occupied
                rooms_kwh += weighted_w * hours_in_bin / 1000.0
                rooms_with_data += 1

        if rooms_with_data < 3:
            return None  # Not enough room data to be useful
        return rooms_kwh

    def _occupancy_blend_weight(self, bayesian: Any = None) -> float:
        """Higher weight when more Bayesian cells are ACTIVE."""
        if bayesian is None:
            bayesian = self._get_bayesian() if self._get_bayesian else None
        if bayesian is None:
            return 0.0
        active = bayesian.count_active_cells()
        total = bayesian.count_total_cells()
        if total == 0:
            _LOGGER.debug("Occupancy weighting enabled but no Bayesian cells yet")
            return 0.0
        maturity = active / total
        return min(0.4, maturity * 0.5)

    def _remaining_occupancy_weighted_consumption(self, now: datetime) -> float | None:
        """Estimate remaining consumption today using occupancy-shaped curve."""
        bayesian = self._get_bayesian() if self._get_bayesian else None
        if not self._power_profiles or not bayesian:
            return None

        day_type = 1 if now.weekday() >= 5 else 0
        current_bin = get_time_bin(now.hour)
        remaining_kwh = 0.0
        any_data = False

        for room_id in self._room_ids:
            for time_bin in range(current_bin, 6):
                hours = BIN_HOURS[time_bin]
                if time_bin == current_bin:
                    # Partial bin — remaining hours
                    bin_start = PROFILE_TIME_BINS[time_bin][0]
                    bin_end = PROFILE_TIME_BINS[time_bin][1]
                    elapsed = now.hour - bin_start + now.minute / 60.0
                    hours = max(0, (bin_end - bin_start) - elapsed)

                baseline_w = self._power_profiles.get_baseline_watts(
                    room_id, time_bin, day_type)
                if baseline_w is None:
                    continue

                p_occupied = bayesian.predict_room_occupancy(
                    room_id, time_bin, day_type) or 0.5
                standby_w = self._power_profiles.get_standby_watts(room_id) or 0
                weighted_w = standby_w + (baseline_w - standby_w) * p_occupied
                remaining_kwh += weighted_w * hours / 1000.0
                any_data = True

        return remaining_kwh if any_data else None

    def _get_battery_capacity_kwh(self) -> float:
        """Get battery capacity in kWh from Envoy, fallback to default.

        Unit-consistency: Enphase Encharge reports capacity in Wh, but check
        the entity's uom rather than hardcoding the /1000 so a kWh-reporting
        firmware doesn't collapse capacity to ~0.04 kWh and silently use the
        fallback (mirrors the energy.py reader + the _read_power_w guard).
        """
        raw = self._get_float(self._battery_capacity_entity)
        if raw is not None and raw > 0:
            uom = ""
            if self._battery_capacity_entity is not None:
                state = self.hass.states.get(self._battery_capacity_entity)
                if state is not None:
                    uom = state.attributes.get("unit_of_measurement", "")
            return raw if uom in ("kWh", "kwh") else raw / 1000.0
        return BATTERY_TOTAL_CAPACITY_KWH_FALLBACK

    def _estimate_battery_full_time(self, now: datetime) -> None:
        """Estimate when battery will reach 100% SOC today.

        H2 (2026-07-13) — v2 per operator's mental model: "battery full
        time IF we charged to 100% at the CURRENT charge rate (solar or
        grid) minus consumption." No moving-target modeling — always to
        100%, always from the CURRENT observed rate.

        Two modes:
          - CURRENT_RATE — battery is currently charging (battery_power_w
            > 0). ETA is piecewise from current SOC to 100 at the
            current rate, taper-adjusted (rate scaled per band).
          - SOLAR_FORECAST — battery is not currently charging. Fall
            back to the pre-H2 model (net solar remaining vs remaining
            capacity), retaining ``unlikely_today`` semantics.

        Sign convention: battery_power_w positive = CHARGING, negative
        = DISCHARGING (Envoy convention).
        """
        soc = self._get_float(self._battery_soc_entity)
        remaining_forecast = self._get_float(self._solcast_remaining_entity)

        # H2: surface WHY, not bare unknown.
        if soc is None:
            self._battery_full_time = None
            self._battery_full_time_attrs = {
                "basis": "unavailable",
                "missing_input": "soc",
            }
            return
        if remaining_forecast is None:
            self._battery_full_time = None
            self._battery_full_time_attrs = {
                "basis": "unavailable",
                "missing_input": "solcast",
            }
            return

        if soc >= 99:
            self._battery_full_time = "already_full"
            self._battery_full_time_attrs = {
                "basis": "already_full",
                "current_soc": soc,
            }
            return

        # How much energy needed to fill battery
        total_capacity = self._get_battery_capacity_kwh()

        # H2 primary path — CURRENT_RATE. Consult the live battery power
        # callable (from the strategy) — positive value = charging.
        current_rate_kw: float | None = None
        if self._battery_power_w_fn is not None:
            try:
                raw_w = self._battery_power_w_fn()
                if raw_w is not None:
                    current_rate_kw = float(raw_w) / 1000.0
            except Exception:  # noqa: BLE001
                current_rate_kw = None

        # Piecewise band definition. Each band has a NOMINAL rate (kW)
        # — the OBSERVED rate is scaled per band to reflect Encharge
        # taper. When observed 0 < soc rate < AVERAGE, the ratio
        # (observed / nominal below-80) is applied to the higher bands.
        bands = [(80, AVERAGE_CHARGE_RATE_KW), (90, 2.5), (100, 1.5)]

        if current_rate_kw is not None and current_rate_kw > 0.05:
            # Actively charging — build ETA from CURRENT rate + taper.
            observed_ratio = current_rate_kw / AVERAGE_CHARGE_RATE_KW
            hours_to_fill = 0.0
            current_soc = soc
            taper_band = None
            for threshold, nominal_rate in bands:
                if current_soc >= threshold:
                    continue
                # Scale each band's nominal rate by the observed ratio
                # so we honor the CURRENT rate (not a modeled ideal).
                band_rate = max(0.1, nominal_rate * observed_ratio)
                band_kwh = total_capacity * (
                    min(threshold, 100) - current_soc
                ) / 100.0
                hours_to_fill += band_kwh / band_rate
                if taper_band is None:
                    taper_band = f"<{threshold}"
                current_soc = threshold

            # Review B-H2-2 (2026-07-13): clamp on hours_to_fill > 24.
            # A bare HH:MM ETA without a date is misleading when the fill
            # spans multiple days (e.g. dead-of-winter, degraded system).
            # Report "unlikely_today" and retain the current rate in
            # attrs so the operator sees WHY.
            if hours_to_fill > 24:
                self._battery_full_time = "unlikely_today"
                self._battery_full_time_attrs = {
                    "basis": "current_rate",
                    "current_charge_rate_kw": round(current_rate_kw, 2),
                    "taper_band": taper_band,
                    "current_soc": soc,
                    "hours_to_fill": round(hours_to_fill, 2),
                    "reason": "hours_to_fill_exceeds_24",
                    "taper_note": (
                        "bands scaled from observed rate; hardware may "
                        "taper harder near full"
                    ),
                    "inputs": "live battery_power_w + soc",
                }
                return
            estimated_time = now + timedelta(hours=hours_to_fill)
            self._battery_full_time = estimated_time.strftime("%H:%M")
            self._battery_full_time_attrs = {
                "basis": "current_rate",
                "current_charge_rate_kw": round(current_rate_kw, 2),
                "taper_band": taper_band,
                "current_soc": soc,
                "hours_to_fill": round(hours_to_fill, 2),
                # Review B-H2-1 (2026-07-13): honest caveat — the piecewise
                # bands are scaled from the OBSERVED rate; near 100% the
                # Encharge hardware can taper harder than our model, so
                # the HH:MM ETA is a best-effort estimate not a guarantee.
                "taper_note": (
                    "bands scaled from observed rate; hardware may "
                    "taper harder near full"
                ),
                "inputs": "live battery_power_w + soc",
            }
            return

        # SOLAR_FORECAST fallback — battery not currently charging.
        remaining_capacity_kwh = total_capacity * (100 - soc) / 100.0

        # v3.14.0: Deduct remaining home consumption from available solar
        # v4.1.1 B4 L2: Use occupancy-shaped curve when enabled
        remaining_consumption = None
        if (
            self._occupancy_enabled_fn
            and self._occupancy_enabled_fn()
        ):
            remaining_consumption = self._remaining_occupancy_weighted_consumption(now)

        if remaining_consumption is None:
            # Flat fallback
            hours_left = max(0, 20 - now.hour)
            daily_consumption = self._predicted_consumption_kwh or 30.0
            remaining_consumption = daily_consumption * (hours_left / 24.0)
        net_available_solar = remaining_forecast - remaining_consumption

        # Can we fill it with net available solar?
        if net_available_solar < remaining_capacity_kwh:
            self._battery_full_time = "unlikely_today"
            self._battery_full_time_attrs = {
                "basis": "solar_forecast",
                "net_solar_remaining_kwh": round(net_available_solar, 2),
                "assumed_consumption_kwh": round(remaining_consumption, 2),
                "remaining_capacity_kwh": round(remaining_capacity_kwh, 2),
                "current_charge_rate_kw": (
                    round(current_rate_kw, 2)
                    if current_rate_kw is not None else None
                ),
                "inputs": "solcast + capacity model (not currently charging)",
            }
            return

        # v3.14.0: SOC-based charge rate taper (Encharge behavior)
        # Calculate piecewise — each band has a different charge rate
        hours_to_fill = 0.0
        current_soc = soc
        taper_band = None
        for threshold, rate in bands:
            if current_soc >= threshold:
                continue
            band_kwh = total_capacity * (min(threshold, 100) - current_soc) / 100.0
            hours_to_fill += band_kwh / rate
            if taper_band is None:
                taper_band = f"<{threshold}"
            current_soc = threshold

        # Review B-H2-2 (2026-07-13) — solar_forecast branch symmetry
        # with the current_rate clamp above.
        if hours_to_fill > 24:
            self._battery_full_time = "unlikely_today"
            self._battery_full_time_attrs = {
                "basis": "solar_forecast",
                "net_solar_remaining_kwh": round(net_available_solar, 2),
                "assumed_consumption_kwh": round(remaining_consumption, 2),
                "taper_band": taper_band,
                "current_soc": soc,
                "current_charge_rate_kw": (
                    round(current_rate_kw, 2)
                    if current_rate_kw is not None else None
                ),
                "reason": "hours_to_fill_exceeds_24",
                "taper_note": (
                    "banded capacity model; hardware may taper harder near full"
                ),
                "inputs": "solcast + capacity model (not currently charging)",
            }
            return
        estimated_time = now + timedelta(hours=hours_to_fill)
        self._battery_full_time = estimated_time.strftime("%H:%M")
        self._battery_full_time_attrs = {
            "basis": "solar_forecast",
            "net_solar_remaining_kwh": round(net_available_solar, 2),
            "assumed_consumption_kwh": round(remaining_consumption, 2),
            "taper_band": taper_band,
            "current_soc": soc,
            "current_charge_rate_kw": (
                round(current_rate_kw, 2)
                if current_rate_kw is not None else None
            ),
            # Review B-H2-1 (2026-07-13): banded capacity model, near-full
            # taper may exceed nominal.
            "taper_note": (
                "banded capacity model; hardware may taper harder near full"
            ),
            "inputs": "solcast + capacity model (not currently charging)",
        }

    def restore_consumption_history(self, rows: list[dict]) -> None:
        """Restore per-DOW consumption history from DB rows on startup.

        Args:
            rows: list of dicts with 'date' (ISO str) and 'consumption_kwh'.
                  Most recent first (DESC order from DB).
        """
        from datetime import date as date_cls
        restored = 0
        # Process oldest first so that append() keeps the most recent entries
        # when deque maxlen=8 is exceeded (drops from left = oldest).
        for row in reversed(rows):
            date_str = row.get("date", "")
            kwh = row.get("consumption_kwh")
            if not date_str or kwh is None:
                continue
            try:
                d = date_cls.fromisoformat(date_str)
                dow = d.weekday()
                self._consumption_history[dow].append(kwh)
                restored += 1
            except (ValueError, TypeError):
                continue
        if restored:
            _LOGGER.info(
                "Restored consumption history: %d days across %d DOWs",
                restored,
                sum(1 for d in self._consumption_history.values() if d),
            )

    def record_actual_consumption(self, actual_kwh: float) -> None:
        """Record actual daily consumption for baseline learning.

        Called at midnight when the date rolls over, so actual_kwh is
        yesterday's consumption.  Attribute it to yesterday's day-of-week.
        """
        yesterday = dt_util.now() - timedelta(days=1)
        dow = yesterday.weekday()
        self._consumption_history[dow].append(actual_kwh)

    def _get_current_prediction(self) -> dict[str, Any]:
        """Return the current prediction as a dict."""
        return {
            "date": self._prediction_date,
            "predicted_production_kwh": self._predicted_production_kwh,
            "predicted_consumption_kwh": self._predicted_consumption_kwh,
            "predicted_net_kwh": self._predicted_net_kwh,
            "battery_full_time": self._battery_full_time,
            # H2 (2026-07-13): enriched attrs (basis, current rate,
            # taper band, missing_input on unavailable, …).
            "battery_full_time_attrs": dict(self._battery_full_time_attrs),
            "adjustment_factor": round(self._adjustment_factor, 3),
            # R1 (2026-07-16): source marker + shadow v1 components.
            # source describes which arm produced predicted_consumption_kwh.
            # shadow_* fields carry the v1 arm's number even when the shadow
            # gate keeps the legacy path as the consumed value — enables
            # R2's future consumer gate (I-NE5) + nightly self-scoring.
            "predicted_consumption_source": self._predicted_consumption_source,
            "shadow_predicted_consumption_kwh": self._shadow_predicted_consumption_kwh,
            "shadow_predicted_base_kwh": self._shadow_predicted_base_kwh,
            "shadow_predicted_ev_kwh": self._shadow_predicted_ev_kwh,
        }


class AccuracyTracker:
    """Tracks forecast accuracy and adjusts predictions.

    Compares yesterday's prediction vs actual at end of day.
    Maintains rolling error metrics. Restores from DB on startup.
    """

    def __init__(self) -> None:
        """Initialize accuracy tracker."""
        self._daily_errors: deque[dict[str, float]] = deque(maxlen=ACCURACY_WINDOW_DAYS)
        self._last_eval_date: str = ""

    def restore_from_db(self, rows: list[dict]) -> None:
        """Restore accuracy history from DB rows.

        Each row should have: date, consumption_kwh, predicted_consumption_kwh,
        prediction_error_pct.
        """
        restored = 0
        for row in rows:
            actual = row.get("consumption_kwh")
            predicted = row.get("predicted_consumption_kwh")
            pct_error = row.get("prediction_error_pct")
            date_str = row.get("date", "")
            if actual is not None and predicted is not None and pct_error is not None:
                # Rev 2: pct_error restored verbatim (control-path byte-identity);
                # pct_error_bounded recomputed from (predicted, actual) — no schema
                # migration, homogeneous deque post-restore.
                error_kwh = actual - predicted
                denom = max(abs(predicted), abs(actual), MIN_DENOMINATOR_KWH)
                raw_bounded = (error_kwh / denom) * 100
                pct_error_bounded = max(
                    -PCT_ERROR_BOUND, min(PCT_ERROR_BOUND, raw_bounded)
                )
                self._daily_errors.append({
                    "date": date_str,
                    "predicted": predicted,
                    "actual": actual,
                    "error": round(error_kwh, 2),
                    "pct_error": round(pct_error, 1),
                    "pct_error_bounded": round(pct_error_bounded, 1),
                })
                restored += 1
                self._last_eval_date = date_str
        if restored:
            _LOGGER.info(
                "Restored %d accuracy records from DB (adj=%.3f)",
                restored, self.get_adjustment_factor(),
            )

    def evaluate_accuracy(
        self,
        predicted_kwh: float | None,
        actual_kwh: float | None,
        prediction_date: str,
    ) -> dict[str, Any] | None:
        """Evaluate prediction accuracy for a completed day.

        Returns accuracy metrics if both values available, None otherwise.
        """
        if prediction_date == self._last_eval_date:
            return None  # Already evaluated
        if predicted_kwh is None or actual_kwh is None:
            return None

        self._last_eval_date = prediction_date
        error = actual_kwh - predicted_kwh
        pct_error = (error / max(abs(predicted_kwh), 0.1)) * 100

        # Rev 2: parallel bounded metric — display-only. Never read by the
        # control path (get_adjustment_factor, energy_daily.prediction_error_pct
        # DAO write, _solar_forecast_error_baseline). See planning doc.
        denom = max(abs(predicted_kwh), abs(actual_kwh), MIN_DENOMINATOR_KWH)
        raw_bounded = (error / denom) * 100
        pct_error_bounded = max(
            -PCT_ERROR_BOUND, min(PCT_ERROR_BOUND, raw_bounded)
        )

        self._daily_errors.append({
            "date": prediction_date,
            "predicted": predicted_kwh,
            "actual": actual_kwh,
            "error": round(error, 2),
            "pct_error": round(pct_error, 1),
            "pct_error_bounded": round(pct_error_bounded, 1),
        })

        # Return dict is UNCHANGED — control-path consumers keep reading pct_error.
        return {
            "error_kwh": round(error, 2),
            "pct_error": round(pct_error, 1),
        }

    def get_adjustment_factor(self) -> float:
        """Calculate Bayesian adjustment factor from recent accuracy.

        If predictions consistently under-estimate, factor > 1.0.
        If predictions consistently over-estimate, factor < 1.0.
        """
        if len(self._daily_errors) < 3:
            return 1.0

        recent = list(self._daily_errors)[-7:]
        avg_pct_error = sum(e["pct_error"] for e in recent) / len(recent)

        # Dampen adjustment (don't swing wildly)
        adjustment = 1.0 + (avg_pct_error / 100.0) * 0.3
        return max(0.7, min(1.3, adjustment))

    @property
    def rolling_accuracy(self) -> float:
        """Rolling accuracy percentage (100 - abs(avg_bounded_pct_error)).

        Rev 2: reads ``pct_error_bounded`` (SMAPE-style, clamped ±PCT_ERROR_BOUND)
        so a single near-zero-prediction row cannot pin the sensor to 0. The
        control-path ``pct_error`` key is deliberately NOT read here.
        """
        if not self._daily_errors:
            return 0.0
        recent = list(self._daily_errors)[-7:]
        avg_abs_error = sum(
            abs(e.get("pct_error_bounded", e["pct_error"])) for e in recent
        ) / len(recent)
        return round(max(0, 100 - avg_abs_error), 1)

    def get_status(self) -> dict[str, Any]:
        """Return accuracy tracker status."""
        return {
            "rolling_accuracy_pct": self.rolling_accuracy,
            "samples": len(self._daily_errors),
            "adjustment_factor": round(self.get_adjustment_factor(), 3),
            "last_eval_date": self._last_eval_date,
            "eval_age_days": self._eval_age_days(),
        }

    def _eval_age_days(self) -> int | None:
        """Days since ``_last_eval_date`` (defensive parse).

        Returns None when never evaluated OR the stored date string is
        unparseable — the caller renders unparseable as ``status="stale"``.
        """
        if not self._last_eval_date:
            return None
        try:
            last = date.fromisoformat(self._last_eval_date)
        except (ValueError, TypeError):
            return None
        # dt_util.now() does not raise; the local-timezone `today` matches the
        # locally-stamped `_last_eval_date` (avoids the UTC/local one-day skew
        # near midnight that `datetime.utcnow().date()` would introduce, and
        # sidesteps the py3.12 `utcnow()` deprecation).
        today = dt_util.now().date()
        return (today - last).days


# Minimum observations per (room, time_bin, day_type) cell before profile is trusted
MIN_SAMPLES_PER_CELL = 20

# EMA smoothing factor — higher = more responsive, lower = more stable
EMA_ALPHA = 0.1

# Time bin definitions (same as BayesianPredictor)
PROFILE_TIME_BINS = {
    0: (0, 6),    # NIGHT: 00-06
    1: (6, 9),    # MORNING: 06-09
    2: (9, 12),   # MIDDAY: 09-12
    3: (12, 17),  # AFTERNOON: 12-17
    4: (17, 21),  # EVENING: 17-21
    5: (21, 24),  # LATE: 21-24
}

# Hours per time bin (for kWh calculation)
BIN_HOURS = {0: 6, 1: 3, 2: 3, 3: 5, 4: 4, 5: 3}


def get_time_bin(hour: int) -> int:
    """Return time bin index for a given hour (0-23)."""
    for bin_idx, (start, end) in PROFILE_TIME_BINS.items():
        if start <= hour < end:
            return bin_idx
    return 0  # Fallback to NIGHT


class RoomPowerProfile:
    """Learns room power baselines by time bin and day type.

    v4.1.0: Stores exponential moving average (EMA) of room power draw per
    (time_bin, day_type) cell. Updated from room coordinator data during
    energy coordinator cycles.

    Standby power is learned from NIGHT-bin vacant observations rather than
    hardcoded — rooms with always-on servers or aquariums get accurate standby.
    """

    def __init__(self) -> None:
        """Initialize empty profiles."""
        # {room_id: {(time_bin, day_type): {"avg_watts": float, "samples": int}}}
        self._profiles: dict[str, dict[tuple[int, int], dict[str, float]]] = {}
        # {room_id: {"standby_watts": float, "standby_samples": int}}
        self._standby: dict[str, dict[str, float]] = {}

    def update(
        self,
        room_id: str,
        time_bin: int,
        day_type: int,
        current_watts: float,
        is_occupied: bool,
    ) -> None:
        """Update EMA for room/bin/day_type. Also learn standby from vacant NIGHT data."""
        if room_id not in self._profiles:
            self._profiles[room_id] = {}

        key = (time_bin, day_type)
        cell = self._profiles[room_id].get(key)

        if cell is None:
            # Cold start — first observation seeds the EMA
            self._profiles[room_id][key] = {
                "avg_watts": current_watts,
                "samples": 1,
            }
        else:
            # EMA update: new_avg = alpha * current + (1 - alpha) * old_avg
            cell["avg_watts"] = (
                EMA_ALPHA * current_watts + (1 - EMA_ALPHA) * cell["avg_watts"]
            )
            cell["samples"] += 1

        # Learn standby from NIGHT-bin vacant observations
        if time_bin == 0 and not is_occupied:
            standby = self._standby.get(room_id)
            if standby is None:
                self._standby[room_id] = {
                    "standby_watts": current_watts,
                    "standby_samples": 1,
                }
            else:
                standby["standby_watts"] = (
                    EMA_ALPHA * current_watts
                    + (1 - EMA_ALPHA) * standby["standby_watts"]
                )
                standby["standby_samples"] += 1

    def get_baseline_watts(
        self, room_id: str, time_bin: int, day_type: int
    ) -> float | None:
        """Return learned baseline watts, or None if insufficient data."""
        cell = self._profiles.get(room_id, {}).get((time_bin, day_type))
        if cell is None or cell["samples"] < MIN_SAMPLES_PER_CELL:
            return None
        return cell["avg_watts"]

    def get_standby_watts(self, room_id: str) -> float | None:
        """Return learned standby watts from NIGHT-bin vacant data."""
        standby = self._standby.get(room_id)
        if standby is None or standby["standby_samples"] < MIN_SAMPLES_PER_CELL:
            return None
        return standby["standby_watts"]

    def get_all_profiles(self) -> list[dict]:
        """Return all profiles as flat dicts for DB persistence."""
        rows = []
        for room_id, cells in self._profiles.items():
            for (time_bin, day_type), cell in cells.items():
                rows.append({
                    "room_id": room_id,
                    "time_bin": time_bin,
                    "day_type": day_type,
                    "avg_watts": round(cell["avg_watts"], 2),
                    "sample_count": cell["samples"],
                })
        # Include standby as a virtual row (time_bin=-1, day_type=-1)
        for room_id, standby in self._standby.items():
            rows.append({
                "room_id": room_id,
                "time_bin": -1,
                "day_type": -1,
                "avg_watts": round(standby["standby_watts"], 2),
                "sample_count": standby["standby_samples"],
            })
        return rows

    def restore_from_rows(self, rows: list[dict]) -> int:
        """Restore profiles from DB rows. Returns count of rows restored."""
        restored = 0
        for row in rows:
            room_id = row.get("room_id", "")
            time_bin = row.get("time_bin")
            day_type = row.get("day_type")
            avg_watts = row.get("avg_watts")
            sample_count = row.get("sample_count", 0)

            if not room_id or avg_watts is None:
                continue

            # Standby rows use time_bin=-1, day_type=-1
            if time_bin == -1 and day_type == -1:
                self._standby[room_id] = {
                    "standby_watts": avg_watts,
                    "standby_samples": sample_count,
                }
            else:
                if room_id not in self._profiles:
                    self._profiles[room_id] = {}
                self._profiles[room_id][(time_bin, day_type)] = {
                    "avg_watts": avg_watts,
                    "samples": sample_count,
                }
            restored += 1

        if restored:
            _LOGGER.info(
                "Restored power profiles: %d cells across %d rooms",
                restored, len(self._profiles),
            )
        return restored

    def get_status(self) -> dict[str, Any]:
        """Return profile status summary."""
        total_cells = sum(len(cells) for cells in self._profiles.values())
        mature_cells = sum(
            1
            for cells in self._profiles.values()
            for cell in cells.values()
            if cell["samples"] >= MIN_SAMPLES_PER_CELL
        )
        rooms_with_standby = sum(
            1 for s in self._standby.values()
            if s["standby_samples"] >= MIN_SAMPLES_PER_CELL
        )
        return {
            "rooms_tracked": len(self._profiles),
            "total_cells": total_cells,
            "mature_cells": mature_cells,
            "rooms_with_standby": rooms_with_standby,
            "min_samples_threshold": MIN_SAMPLES_PER_CELL,
        }
