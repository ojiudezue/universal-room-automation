"""Preset management for HVAC Coordinator.

Manages house state -> preset mapping, seasonal range adjustment,
and time-based schedule fallback.

v3.8.0-H1: Initial implementation.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .hvac_const import (
    CONF_HVAC_BASELINE_SUMMER_HOME_COOL,
    CONF_HVAC_BASELINE_SUMMER_HOME_HEAT,
    CONF_HVAC_BASELINE_SUMMER_SLEEP_COOL,
    CONF_HVAC_BASELINE_SUMMER_SLEEP_HEAT,
    CONF_HVAC_BASELINE_SUMMER_AWAY_COOL,
    CONF_HVAC_BASELINE_SUMMER_AWAY_HEAT,
    CONF_HVAC_BASELINE_SUMMER_VACATION_COOL,
    CONF_HVAC_BASELINE_SUMMER_VACATION_HEAT,
    CONF_HVAC_BASELINE_SHOULDER_HOME_COOL,
    CONF_HVAC_BASELINE_SHOULDER_HOME_HEAT,
    CONF_HVAC_BASELINE_SHOULDER_SLEEP_COOL,
    CONF_HVAC_BASELINE_SHOULDER_SLEEP_HEAT,
    CONF_HVAC_BASELINE_SHOULDER_AWAY_COOL,
    CONF_HVAC_BASELINE_SHOULDER_AWAY_HEAT,
    CONF_HVAC_BASELINE_SHOULDER_VACATION_COOL,
    CONF_HVAC_BASELINE_SHOULDER_VACATION_HEAT,
    CONF_HVAC_BASELINE_WINTER_HOME_COOL,
    CONF_HVAC_BASELINE_WINTER_HOME_HEAT,
    CONF_HVAC_BASELINE_WINTER_SLEEP_COOL,
    CONF_HVAC_BASELINE_WINTER_SLEEP_HEAT,
    CONF_HVAC_BASELINE_WINTER_AWAY_COOL,
    CONF_HVAC_BASELINE_WINTER_AWAY_HEAT,
    CONF_HVAC_BASELINE_WINTER_VACATION_COOL,
    CONF_HVAC_BASELINE_WINTER_VACATION_HEAT,
    HOUSE_STATE_PRESET_MAP,
    SEASONAL_DEFAULTS,
    SEASON_SHOULDER,
    SEASON_SUMMER,
    SEASON_WINTER,
    SUMMER_MONTHS,
    WINTER_MONTHS,
)

# Map (season, preset) -> (CONF_COOL_KEY, CONF_HEAT_KEY) for D2 override lookup.
# Built once at module load so get_seasonal_setpoints pays zero dict-construction
# cost per call.
_BASELINE_CONF_MAP: dict[tuple[str, str], tuple[str, str]] = {
    (SEASON_SUMMER, "home"): (CONF_HVAC_BASELINE_SUMMER_HOME_COOL, CONF_HVAC_BASELINE_SUMMER_HOME_HEAT),
    (SEASON_SUMMER, "sleep"): (CONF_HVAC_BASELINE_SUMMER_SLEEP_COOL, CONF_HVAC_BASELINE_SUMMER_SLEEP_HEAT),
    (SEASON_SUMMER, "away"): (CONF_HVAC_BASELINE_SUMMER_AWAY_COOL, CONF_HVAC_BASELINE_SUMMER_AWAY_HEAT),
    (SEASON_SUMMER, "vacation"): (CONF_HVAC_BASELINE_SUMMER_VACATION_COOL, CONF_HVAC_BASELINE_SUMMER_VACATION_HEAT),
    (SEASON_SHOULDER, "home"): (CONF_HVAC_BASELINE_SHOULDER_HOME_COOL, CONF_HVAC_BASELINE_SHOULDER_HOME_HEAT),
    (SEASON_SHOULDER, "sleep"): (CONF_HVAC_BASELINE_SHOULDER_SLEEP_COOL, CONF_HVAC_BASELINE_SHOULDER_SLEEP_HEAT),
    (SEASON_SHOULDER, "away"): (CONF_HVAC_BASELINE_SHOULDER_AWAY_COOL, CONF_HVAC_BASELINE_SHOULDER_AWAY_HEAT),
    (SEASON_SHOULDER, "vacation"): (CONF_HVAC_BASELINE_SHOULDER_VACATION_COOL, CONF_HVAC_BASELINE_SHOULDER_VACATION_HEAT),
    (SEASON_WINTER, "home"): (CONF_HVAC_BASELINE_WINTER_HOME_COOL, CONF_HVAC_BASELINE_WINTER_HOME_HEAT),
    (SEASON_WINTER, "sleep"): (CONF_HVAC_BASELINE_WINTER_SLEEP_COOL, CONF_HVAC_BASELINE_WINTER_SLEEP_HEAT),
    (SEASON_WINTER, "away"): (CONF_HVAC_BASELINE_WINTER_AWAY_COOL, CONF_HVAC_BASELINE_WINTER_AWAY_HEAT),
    (SEASON_WINTER, "vacation"): (CONF_HVAC_BASELINE_WINTER_VACATION_COOL, CONF_HVAC_BASELINE_WINTER_VACATION_HEAT),
}

_LOGGER = logging.getLogger(__name__)


class PresetManager:
    """Manages thermostat presets based on house state, season, and schedule.

    Primary control lever: sets presets and adjusts preset temperature ranges
    on zone thermostats so manual thermostat use remains compatible.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        max_sleep_offset: float = 1.5,
    ) -> None:
        """Initialize preset manager."""
        self.hass = hass
        self._max_sleep_offset = max_sleep_offset
        self._current_season: str = ""
        self._last_house_state: str = ""

    @property
    def current_season(self) -> str:
        """Return current season."""
        return self._current_season

    def determine_season(self, now: datetime | None = None) -> str:
        """Determine current season from month."""
        if now is None:
            now = dt_util.now()
        month = now.month

        if month in SUMMER_MONTHS:
            self._current_season = SEASON_SUMMER
        elif month in WINTER_MONTHS:
            self._current_season = SEASON_WINTER
        else:
            self._current_season = SEASON_SHOULDER

        return self._current_season

    def get_preset_for_house_state(self, house_state: str) -> str | None:
        """Map house state to thermostat preset.

        Returns None if house state doesn't map to a preset.
        """
        return HOUSE_STATE_PRESET_MAP.get(house_state)

    def get_seasonal_setpoints(
        self,
        preset: str,
        season: str | None = None,
    ) -> tuple[float, float] | None:
        """Get (cool_setpoint, heat_setpoint) for a preset in current season.

        v4.7.3 D2: Prefers CM entry.options overrides over SEASONAL_DEFAULTS.
        Per-CONF granularity — saving one field does not silently override the
        other 23.  Falls back to SEASONAL_DEFAULTS for any field not present
        in entry.options, so existing users see zero behaviour change.

        Returns None if preset not in seasonal defaults.
        """
        if season is None:
            season = self._current_season or self.determine_season()

        season_ranges = SEASONAL_DEFAULTS.get(season)
        if season_ranges is None:
            return None

        default_pair = season_ranges.get(preset)
        if default_pair is None:
            return None

        # D2: check for per-CONF overrides stored in CM entry.options.
        conf_pair = _BASELINE_CONF_MAP.get((season, preset))
        if conf_pair is None:
            return default_pair

        cm_options: dict = {}
        try:
            from ..const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_COORDINATOR_MANAGER
            for ce in self.hass.config_entries.async_entries(DOMAIN):
                if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                    cm_options = ce.options
                    break
        except Exception:
            _LOGGER.debug(
                "HVAC: get_seasonal_setpoints could not read CM entry options "
                "(falling back to SEASONAL_DEFAULTS)",
                exc_info=True,
            )

        conf_cool_key, conf_heat_key = conf_pair
        cool = float(cm_options.get(conf_cool_key, default_pair[0]))
        heat = float(cm_options.get(conf_heat_key, default_pair[1]))
        _LOGGER.debug(
            "HVAC: baseline setpoints [%s/%s] cool=%.1f heat=%.1f "
            "(from_options=%s/%s)",
            season, preset, cool, heat,
            conf_cool_key in cm_options,
            conf_heat_key in cm_options,
        )
        return (cool, heat)

    def compute_energy_offset(
        self,
        base_cool: float,
        base_heat: float,
        energy_offset: float,
        is_sleep: bool,
    ) -> tuple[float, float]:
        """Apply energy offset to setpoints, respecting sleep limits.

        Returns (adjusted_cool, adjusted_heat).
        Energy offset positive = raise cool (coast), negative = lower cool (pre_cool).
        """
        if is_sleep and abs(energy_offset) > self._max_sleep_offset:
            # Clamp offset during sleep hours
            clamped = self._max_sleep_offset if energy_offset > 0 else -self._max_sleep_offset
            _LOGGER.debug(
                "HVAC: Sleep protection clamped offset %.1f -> %.1f",
                energy_offset, clamped,
            )
            energy_offset = clamped

        adjusted_cool = base_cool + energy_offset
        # Heat offset is inverted: coast raises cool but shouldn't raise heat
        # Pre-cool lowers cool but doesn't change heat
        adjusted_heat = base_heat

        return adjusted_cool, adjusted_heat

    def should_change_preset(
        self,
        current_preset: str,
        target_preset: str,
    ) -> bool:
        """Determine if preset should be changed.

        Skip change if already at target or if current preset is 'manual'
        (user manually set temperature — arrester handles this, not preset manager).
        """
        if current_preset == target_preset:
            return False
        # Don't fight manual — that's the arrester's job
        if current_preset == "manual":
            return False
        return True

    def get_status(self) -> dict[str, Any]:
        """Return preset manager status for diagnostics."""
        return {
            "current_season": self._current_season,
            "last_house_state": self._last_house_state,
            "max_sleep_offset": self._max_sleep_offset,
        }
