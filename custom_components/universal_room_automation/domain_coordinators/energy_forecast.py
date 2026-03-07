"""Energy forecasting and prediction for Energy Coordinator.

Sub-Cycle E5: Daily energy prediction, battery full time estimate,
forecast accuracy tracking with Bayesian adjustment.
v3.7.12: Sunrise refresh, DB-backed accuracy, temperature regression.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .energy_const import (
    DEFAULT_BATTERY_CAPACITY_ENTITY,
    DEFAULT_BATTERY_SOC_ENTITY,
    DEFAULT_SOLCAST_REMAINING_ENTITY,
    DEFAULT_SOLCAST_TODAY_ENTITY,
    DEFAULT_WEATHER_ENTITY,
)

_LOGGER = logging.getLogger(__name__)

# Fallback battery capacity if Envoy entity unavailable (kWh)
BATTERY_TOTAL_CAPACITY_KWH_FALLBACK = 15.0
# Average charge rate from solar in kW
AVERAGE_CHARGE_RATE_KW = 3.5

# Rolling window for accuracy tracking
ACCURACY_WINDOW_DAYS = 30

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
    ) -> None:
        """Initialize daily predictor."""
        self.hass = hass
        self._battery_soc_entity = battery_soc_entity or DEFAULT_BATTERY_SOC_ENTITY
        self._solcast_today_entity = solcast_today_entity or DEFAULT_SOLCAST_TODAY_ENTITY
        self._solcast_remaining_entity = solcast_remaining_entity or DEFAULT_SOLCAST_REMAINING_ENTITY
        self._weather_entity = weather_entity or DEFAULT_WEATHER_ENTITY

        # Today's prediction
        self._prediction_date: str = ""
        self._predicted_production_kwh: float | None = None
        self._predicted_consumption_kwh: float | None = None
        self._predicted_net_kwh: float | None = None
        self._battery_full_time: str | None = None

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

    def _get_float(self, entity_id: str) -> float | None:
        """Get numeric state from entity."""
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

    def _estimate_consumption(self, now: datetime, temp: float | None) -> float:
        """Estimate daily consumption using regression or fallback bands.

        If we have 30+ days of temp-consumption paired data (regression loaded),
        use: base + coeff * |temp - 72|. Otherwise fall back to temp bands.
        """
        # Historical baseline
        dow = now.weekday()
        history = list(self._consumption_history[dow])
        if history:
            baseline = sum(history) / len(history)
        else:
            baseline = 30.0  # Default estimate: 30 kWh/day

        # Temperature adjustment
        if (
            self._temp_regression_base is not None
            and self._temp_regression_coeff is not None
            and temp is not None
        ):
            # Learned regression: consumption = base + coeff * |temp - 72|
            regression_estimate = (
                self._temp_regression_base
                + self._temp_regression_coeff * abs(temp - COMFORT_MIDPOINT_F)
            )
            # Blend with day-of-week baseline (70% regression, 30% dow)
            adjusted = regression_estimate * 0.7 + baseline * 0.3
        else:
            # Fallback: fixed multiplier bands
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

        return max(0.1, adjusted * self._adjustment_factor)

    def _get_battery_capacity_kwh(self) -> float:
        """Get battery capacity in kWh from Envoy, fallback to default."""
        capacity_wh = self._get_float(DEFAULT_BATTERY_CAPACITY_ENTITY)
        if capacity_wh is not None and capacity_wh > 0:
            return capacity_wh / 1000.0
        return BATTERY_TOTAL_CAPACITY_KWH_FALLBACK

    def _estimate_battery_full_time(self, now: datetime) -> None:
        """Estimate when battery will reach 100% SOC today."""
        soc = self._get_float(self._battery_soc_entity)
        remaining_forecast = self._get_float(self._solcast_remaining_entity)

        if soc is None or remaining_forecast is None:
            self._battery_full_time = None
            return

        if soc >= 99:
            self._battery_full_time = "already_full"
            return

        # How much energy needed to fill battery
        total_capacity = self._get_battery_capacity_kwh()
        remaining_capacity_kwh = total_capacity * (100 - soc) / 100.0

        # Can we fill it with remaining solar?
        if remaining_forecast < remaining_capacity_kwh:
            self._battery_full_time = "unlikely_today"
            return

        # Estimate hours to fill at average charge rate
        hours_to_fill = remaining_capacity_kwh / AVERAGE_CHARGE_RATE_KW
        estimated_time = now + timedelta(hours=hours_to_fill)
        self._battery_full_time = estimated_time.strftime("%H:%M")

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
            "adjustment_factor": round(self._adjustment_factor, 3),
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
                self._daily_errors.append({
                    "date": date_str,
                    "predicted": predicted,
                    "actual": actual,
                    "error": round(actual - predicted, 2),
                    "pct_error": round(pct_error, 1),
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

        self._daily_errors.append({
            "date": prediction_date,
            "predicted": predicted_kwh,
            "actual": actual_kwh,
            "error": round(error, 2),
            "pct_error": round(pct_error, 1),
        })

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
        """Rolling accuracy percentage (100 - abs(avg_pct_error))."""
        if not self._daily_errors:
            return 0.0
        recent = list(self._daily_errors)[-7:]
        avg_abs_error = sum(abs(e["pct_error"]) for e in recent) / len(recent)
        return round(max(0, 100 - avg_abs_error), 1)

    def get_status(self) -> dict[str, Any]:
        """Return accuracy tracker status."""
        return {
            "rolling_accuracy_pct": self.rolling_accuracy,
            "samples": len(self._daily_errors),
            "adjustment_factor": round(self.get_adjustment_factor(), 3),
            "last_eval_date": self._last_eval_date,
        }
