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
        # HVAC W1-B §5.P1 (2026-09-27): the S1 manual rule reads four
        # legitimacy gates off the arrester / predictor / egress manager.
        # PresetManager is built BEFORE the arrester (hvac.py:248-249), so
        # the refs are injected post-construction (Also-1). Unwired
        # arrester => fail-CLOSED (`arrester_not_wired`): S1 keeps
        # respecting `manual` until the gates can be read.
        self._arrester: Any = None
        self._last_manual_verdict: dict[str, dict[str, Any]] = {}

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

    # ------------------------------------------------------------------
    # HVAC W1-B §5.P1 — S1 manual-guard replacement (Alt A, four gates)
    # ------------------------------------------------------------------
    # The v3.8.0 rule "Don't fight manual — that's the arrester's job" is
    # SUPERSEDED (state-of-play §9e / §10 C25, operator 2026-09-27). The
    # arrester only owns manuals it books as a genuine human change at
    # >= 1 F delta; URA-caused manuals (borrow returns, echoes,
    # compromises) fell through and locked S1 out of its own zones for
    # hours. S1 now takes a zone out of `manual` UNLESS one of four gates
    # says a legitimate holder exists. The rule lives ONLY here (plus the
    # arrester's own booking of gate (e)); nothing in the funnels, nothing
    # in borrow code.

    def set_arrester(self, arrester: Any) -> None:
        """Inject the OverrideArrester (gates a/b, c, d, e-arrester)."""
        self._arrester = arrester

    @staticmethod
    def _has(container: Any, key: str) -> bool:
        try:
            return bool(container) and key in container
        except TypeError:
            return False

    def _borrow_live_source(self, zone_id: str, arr: Any) -> str | None:
        """Gate (e) read: the source naming a live borrow on ``zone_id``, or
        None. Pure read; never raises (an accessor error names itself)."""
        e_source = None
        try:
            from . import hvac_excursion as _ex_mod  # noqa: PLC0415
            if _ex_mod.is_borrow_active(zone_id):
                e_source = "row"
        except Exception:  # noqa: BLE001
            e_source = "row_accessor_error"
        if e_source is None:
            if self._has(getattr(arr, "_nudge_restore_timers", None), zone_id):
                e_source = "nudge_restore_timer"
            elif self._has(getattr(arr, "_nudge_in_flight", None), zone_id):
                e_source = "nudge_in_flight"
            elif self._has(getattr(arr, "_compromise_timers", None), zone_id):
                e_source = "compromise_timer"
        return e_source

    def borrow_live(self, zone_id: str) -> str | None:
        """HVAC Batch C (CPR §3.2 step 4): gate (e) as a pure predicate —
        the live-borrow source for ``zone_id`` (None = no live borrow).
        Same read as `manual_guard_verdict`'s gate (e)."""
        return self._borrow_live_source(zone_id, self._arrester)

    def manual_guard_verdict(self, zone_id: str) -> dict[str, Any]:
        """Evaluate the four Alt-A gates for ``zone_id`` (pure read).

        Returns ``{"refused": bool, "reason": str | None,
        "gate_snapshot": {...}}``. ``reason`` is the FIRST armed gate in
        the order (a/b) -> (c) -> (d) -> (e); every gate's state is in the
        snapshot so the ledger can show the full picture (C-P1B falsifier).
        Never raises; an accessor error arms the gate it belongs to
        (fail-closed: an unreadable holder is treated as present).
        """
        arr = self._arrester
        snap: dict[str, Any] = {
            "a_b": False, "c": False, "c_source": None,
            "d": False, "e": False, "e_source": None,
        }
        if arr is None:
            snap["arrester_wired"] = False
            self._last_manual_verdict[zone_id] = {
                "refused": True, "reason": "arrester_not_wired",
                "gate_snapshot": snap,
            }
            return self._last_manual_verdict[zone_id]
        snap["arrester_wired"] = True

        # (a/b) person-protected hold: TAO switch ON or any immune-person
        # hold on this zone — the pre-existing OR the shave paths consult.
        try:
            snap["a_b"] = bool(arr._corrective_writes_suppressed(zone_id))
        except Exception:  # noqa: BLE001
            snap["a_b"] = True

        # (c) arrester grace / comfort-delay / compromise window. NOT
        # `_override_active` (M1): it leaks under the compromise
        # early-return at hvac_override.py:3366-3372.
        c_source = None
        try:
            if arr.comfort_delay_active(zone_id):
                c_source = "comfort_delay"
            elif self._has(getattr(arr, "_grace_timers", None), zone_id):
                c_source = "grace_timer"
            elif self._has(getattr(arr, "_compromise_timers", None), zone_id):
                c_source = "compromise_timer"
        except Exception:  # noqa: BLE001
            c_source = "accessor_error"
        snap["c"] = c_source is not None
        snap["c_source"] = c_source

        # (d) arrester DISABLED (passive mode): it still books
        # `override_detected` but never reverts, so S1 must keep
        # respecting manual (README_v3.9.0). Reload window (M10): the
        # arrester is CONSTRUCTED from the options value (hvac.py:249 /
        # __init__.py `arrester_enabled=`), and the switch's RestoreEntity
        # value only lands at/after SIGNAL_HVAC_COORDINATOR_READY, so this
        # read IS the options value until READY.
        try:
            snap["d"] = not bool(arr.enabled)
        except Exception:  # noqa: BLE001
            snap["d"] = True

        # (e) live borrow — D47 (2026-09-27): the registry row (pure read,
        # no reap) OR one of the arrester's SELF-DISCHARGING in-flight
        # timers (nudge restore timer / nudge in-flight set / compromise
        # timer — all set even when `begin_excursion` returned None).
        # Token dicts and predictor / egress state are NOT read: their
        # leftovers outlive the row (banking token after the 2 h sweep,
        # `_last_precool_zones` with Zone Intelligence OFF); S1 already
        # skips egress-paused zones. D51 retired the excursion kill switch,
        # so every borrow records a row — no no-row kind remains.
        # HVAC Batch C (CPR): the read now lives in `borrow_live` so S10 can
        # share it; the verdict is byte-identical.
        e_source = self._borrow_live_source(zone_id, arr)
        snap["e"] = e_source is not None
        snap["e_source"] = e_source

        reason: str | None = None
        if snap["a_b"]:
            reason = "person_protected_hold"
        elif snap["c"]:
            reason = "arrester_active_window"
        elif snap["d"]:
            reason = "arrester_disabled_passive"
        elif snap["e"]:
            reason = "active_borrow"
        verdict = {
            "refused": reason is not None,
            "reason": reason,
            "gate_snapshot": snap,
        }
        self._last_manual_verdict[zone_id] = verdict
        return verdict

    def last_manual_verdict(self, zone_id: str) -> dict[str, Any] | None:
        """The verdict computed by the most recent ``should_change_preset``
        for this zone (for the caller's `preset_change_deferred` row)."""
        return self._last_manual_verdict.get(zone_id)

    def should_change_preset(
        self,
        current_preset: str,
        target_preset: str,
        *,
        zone_id: str | None = None,
        climate_entity: str | None = None,
    ) -> bool:
        """Determine if preset should be changed (S1 decision site).

        * already at target -> False (benign no-op).
        * current is `manual` -> True UNLESS a §5.P1 gate refuses
          (person-protected hold / arrester window / arrester disabled /
          live borrow). ``zone_id`` is REQUIRED to read the gates; without
          it the manual case fails closed (refused, `no_zone_id`).
        * otherwise -> True.
        """
        if current_preset == target_preset:
            return False
        # W1-C P1: the zone's thermostat profile names the manual hold
        # (`climate_entity` None -> generic default; identical predicate).
        from .hvac_strategy import is_manual_hold_for  # noqa: PLC0415
        if is_manual_hold_for(self.hass, climate_entity, current_preset):
            if zone_id is None:
                self._last_manual_verdict["__no_zone__"] = {
                    "refused": True, "reason": "no_zone_id", "gate_snapshot": {},
                }
                return False
            verdict = self.manual_guard_verdict(zone_id)
            return not verdict["refused"]
        return True

    def get_status(self) -> dict[str, Any]:
        """Return preset manager status for diagnostics."""
        return {
            "current_season": self._current_season,
            "last_house_state": self._last_house_state,
            "max_sleep_offset": self._max_sleep_offset,
        }
