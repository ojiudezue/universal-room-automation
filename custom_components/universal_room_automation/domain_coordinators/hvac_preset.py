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
    HOUSE_STATE_PRESET_MAP,
    SEASONAL_DEFAULTS,
    SEASON_SHOULDER,
    SEASON_SUMMER,
    SEASON_WINTER,
    SUMMER_MONTHS,
    WINTER_MONTHS,
)

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

        Returns None if preset not in seasonal defaults.
        """
        if season is None:
            season = self._current_season or self.determine_season()

        season_ranges = SEASONAL_DEFAULTS.get(season)
        if season_ranges is None:
            return None

        return season_ranges.get(preset)

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
