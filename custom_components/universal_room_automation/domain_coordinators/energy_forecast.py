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
BATTERY_TOTAL_CAPACITY_KWH_FALLBACK = 40.0
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
        battery_capacity_entity: str | None = None,
        bayesian_predictor: Any | None = None,
        power_profiles: Any | None = None,
        room_ids: list[str] | None = None,
        occupancy_enabled_fn: Any | None = None,
    ) -> None:
        """Initialize daily predictor."""
        self.hass = hass
        self._battery_soc_entity = battery_soc_entity or DEFAULT_BATTERY_SOC_ENTITY
        self._solcast_today_entity = solcast_today_entity or DEFAULT_SOLCAST_TODAY_ENTITY
        self._solcast_remaining_entity = solcast_remaining_entity or DEFAULT_SOLCAST_REMAINING_ENTITY
        self._weather_entity = weather_entity or DEFAULT_WEATHER_ENTITY
        self._battery_capacity_entity = battery_capacity_entity or DEFAULT_BATTERY_CAPACITY_ENTITY

        # v4.1.1 B4 L2: Occupancy-weighted prediction
        # bayesian_predictor is a callable (lazy lookup) to survive integration reloads
        self._get_bayesian = bayesian_predictor if callable(bayesian_predictor) else lambda: bayesian_predictor
        self._power_profiles = power_profiles
        self._room_ids = room_ids or []
        self._occupancy_enabled_fn = occupancy_enabled_fn

        # Today's prediction
        self._prediction_date: str = ""
        self._predicted_production_kwh: float | None = None
        self._predicted_consumption_kwh: float | None = None
        self._predicted_net_kwh: float | None = None
        self._predicted_grid_import_kwh: float | None = None
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
            baseline = 45.0  # Default estimate: 45 kWh/day (large home with AC/pool)

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
        """Get battery capacity in kWh from Envoy, fallback to default."""
        capacity_wh = self._get_float(self._battery_capacity_entity)
        if capacity_wh is not None and capacity_wh > 0:
            return capacity_wh / 1000.0
        return BATTERY_TOTAL_CAPACITY_KWH_FALLBACK

    def _estimate_battery_full_time(self, now: datetime) -> None:
        """Estimate when battery will reach 100% SOC today.

        v3.14.0: Consumption-aware + taper-aware. Deducts remaining home
        consumption from available solar, and uses SOC-based charge rate
        taper (Encharge tapers significantly above 80% SOC).
        """
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
            return

        # v3.14.0: SOC-based charge rate taper (Encharge behavior)
        # Calculate piecewise — each band has a different charge rate
        bands = [(80, AVERAGE_CHARGE_RATE_KW), (90, 2.5), (100, 1.5)]
        hours_to_fill = 0.0
        current_soc = soc
        for threshold, rate in bands:
            if current_soc >= threshold:
                continue
            band_kwh = total_capacity * (min(threshold, 100) - current_soc) / 100.0
            hours_to_fill += band_kwh / rate
            current_soc = threshold

        estimated_time = now + timedelta(hours=hours_to_fill)
        self._battery_full_time = estimated_time.strftime("%H:%M")

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
