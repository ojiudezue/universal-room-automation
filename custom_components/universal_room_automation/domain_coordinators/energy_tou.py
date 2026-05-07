"""TOU (Time-of-Use) rate engine for Energy Coordinator.

Resolves current season, TOU period, and import/export rates based on
the PEC Interconnect TOU rate schedule.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .energy_const import PEC_FIXED_CHARGES, PEC_TOU_RATES

_LOGGER = logging.getLogger(__name__)


class TOURateEngine:
    """Resolves TOU season, period, and rates from a rate table.

    The rate table defaults to PEC 2026 but can be overridden via config.
    Supports loading from a JSON file at /config/universal_room_automation/tou_rates.json.
    """

    # Normalize period names from JSON to internal names used by determine_mode()
    _PERIOD_ALIASES: dict[str, str] = {
        "on_peak": "peak",
        "on-peak": "peak",
        "onpeak": "peak",
        "off-peak": "off_peak",
        "offpeak": "off_peak",
        "mid-peak": "mid_peak",
        "midpeak": "mid_peak",
    }
    _VALID_PERIODS = {"peak", "mid_peak", "off_peak"}

    def __init__(
        self,
        rate_table: dict | None = None,
        fixed_charges: dict | None = None,
        rate_source: str = "built-in PEC 2026",
    ) -> None:
        """Initialize with optional rate table override."""
        self._rates = rate_table or PEC_TOU_RATES
        self._fixed = fixed_charges or PEC_FIXED_CHARGES
        self._last_period: str | None = None
        self._rate_file_loaded: bool = rate_table is not None
        self._rate_source: str = rate_source

    @classmethod
    def _read_json_file(cls, config_dir: str, filename: str) -> tuple[str, dict | None]:
        """Read and parse TOU JSON file (blocking I/O — run in executor)."""
        import json
        from pathlib import Path

        filepath = Path(config_dir) / filename
        if not filepath.exists():
            _LOGGER.debug("TOU rate file not found at %s, using PEC defaults", filepath)
            return str(filepath), None

        try:
            data = json.loads(filepath.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            _LOGGER.warning("Failed to load TOU rate file %s: %s — using PEC defaults", filepath, exc)
            return str(filepath), None

        return str(filepath), data

    @classmethod
    async def async_from_json_file(cls, hass, config_dir: str, filename: str) -> "TOURateEngine":
        """Load TOU rates from a JSON file without blocking the event loop.

        v4.0.5: Async wrapper around blocking file I/O.
        """
        filepath_str, data = await hass.async_add_executor_job(
            cls._read_json_file, config_dir, filename,
        )
        if data is None:
            return cls()
        return cls._from_parsed_data(data, filepath_str, filename)

    @classmethod
    def from_json_file(cls, config_dir: str, filename: str) -> "TOURateEngine":
        """Load TOU rates from a JSON file (sync — prefer async_from_json_file).

        Expected format: see docs/plans/ENERGY_COORDINATOR_PLAN.md section 11.5
        Falls back to PEC defaults if file not found or invalid.
        """
        filepath_str, data = cls._read_json_file(config_dir, filename)
        if data is None:
            return cls()
        return cls._from_parsed_data(data, filepath_str, filename)

    @classmethod
    def _from_parsed_data(cls, data: dict, filepath_str: str, filename: str) -> "TOURateEngine":
        """Build a TOURateEngine from already-parsed JSON data."""

        # Convert JSON format to internal rate table format
        try:
            rate_table = {}
            for season_name, season_data in data.get("seasons", {}).items():
                periods = {}
                for period_name, period_data in season_data.get("periods", {}).items():
                    # Normalize period names (e.g. "on_peak" → "peak")
                    internal_name = cls._PERIOD_ALIASES.get(period_name, period_name)
                    hours = [tuple(h) for h in period_data.get("hours", [])]
                    # Support separate import/export rates; fall back to
                    # symmetric "rate" field for backward compat.
                    symmetric_rate = period_data.get("rate", 0.0)
                    import_rate = period_data.get("import_rate", symmetric_rate)
                    export_rate = period_data.get("export_rate", symmetric_rate)
                    if internal_name not in cls._VALID_PERIODS:
                        _LOGGER.warning(
                            "Unknown TOU period '%s' (from '%s') in %s season %s — ignored",
                            internal_name, period_name, filepath_str, season_name,
                        )
                        continue
                    periods[internal_name] = {
                        "hours": hours,
                        "import_rate": import_rate,
                        "export_rate": export_rate,
                    }
                # off_peak is required — get_current_period() falls back to it
                if "off_peak" not in periods:
                    _LOGGER.error(
                        "TOU rate file %s missing required 'off_peak' period in season '%s' "
                        "— falling back to PEC defaults",
                        filepath_str, season_name,
                    )
                    return cls()
                rate_table[season_name] = {
                    "months": season_data.get("months", []),
                    "periods": periods,
                }

            fixed = data.get("fixed_charges", {})
            fixed_charges = {
                "service_availability": fixed.get("service_availability_monthly", 32.50),
                "delivery_per_kwh": fixed.get("delivery_per_kwh", 0.022546),
                "transmission_per_kwh": fixed.get("transmission_per_kwh", 0.019930),
            }

            utility = data.get("utility", "unknown")
            effective = data.get("effective_date", "unknown")
            rate_source = f"{filename} ({utility}, effective {effective})"

            _LOGGER.info(
                "Loaded TOU rates from %s (utility: %s, effective: %s)",
                filepath_str, utility, effective,
            )
            return cls(
                rate_table=rate_table,
                fixed_charges=fixed_charges,
                rate_source=rate_source,
            )
        except Exception:
            _LOGGER.exception("Failed to parse TOU rate file %s — using PEC defaults", filepath_str)
            return cls()

    @property
    def rate_source(self) -> str:
        """Return the source of TOU rates (file path or 'built-in PEC 2026')."""
        return self._rate_source

    def get_season(self, now: datetime | None = None) -> str:
        """Return the current TOU season: summer, shoulder, or winter."""
        if now is None:
            now = dt_util.now()
        month = now.month
        for season_name, season_data in self._rates.items():
            if month in season_data["months"]:
                return season_name
        return "shoulder"

    def get_current_period(self, now: datetime | None = None) -> str:
        """Return the current TOU period: off_peak, mid_peak, or peak."""
        if now is None:
            now = dt_util.now()
        season = self.get_season(now)
        hour = now.hour
        season_data = self._rates[season]
        for period_name, period_data in season_data["periods"].items():
            for start, end in period_data["hours"]:
                if start <= hour < end:
                    return period_name
        return "off_peak"

    def get_current_rate(self, now: datetime | None = None) -> float:
        """Return the current import rate in $/kWh (base power charge only)."""
        if now is None:
            now = dt_util.now()
        season = self.get_season(now)
        period = self.get_current_period(now)
        return self._rates[season]["periods"][period]["import_rate"]

    def get_export_rate(self, now: datetime | None = None) -> float:
        """Return the current export credit rate in $/kWh."""
        if now is None:
            now = dt_util.now()
        season = self.get_season(now)
        period = self.get_current_period(now)
        return self._rates[season]["periods"][period]["export_rate"]

    def get_effective_import_rate(self, now: datetime | None = None) -> float:
        """Return effective import cost: base power + delivery + transmission."""
        base = self.get_current_rate(now)
        return base + self._fixed["delivery_per_kwh"] + self._fixed["transmission_per_kwh"]

    def get_next_transition(self, now: datetime | None = None) -> dict[str, Any]:
        """Return info about the next TOU period transition.

        Returns dict with: next_period, hours_until, transition_hour
        """
        if now is None:
            now = dt_util.now()
        season = self.get_season(now)
        current_period = self.get_current_period(now)
        current_hour = now.hour

        # Build sorted list of transition hours for today's season
        transitions: list[tuple[int, str]] = []
        for period_name, period_data in self._rates[season]["periods"].items():
            for start, _end in period_data["hours"]:
                transitions.append((start, period_name))
        transitions.sort()

        # Find the next transition after current hour
        for t_hour, t_period in transitions:
            if t_hour > current_hour and t_period != current_period:
                return {
                    "next_period": t_period,
                    "hours_until": t_hour - current_hour,
                    "transition_hour": t_hour,
                }

        # Wrap to next day's first different period
        for t_hour, t_period in transitions:
            if t_period != current_period:
                return {
                    "next_period": t_period,
                    "hours_until": (24 - current_hour) + t_hour,
                    "transition_hour": t_hour,
                }

        return {"next_period": "off_peak", "hours_until": 24, "transition_hour": 0}

    def check_period_transition(self, now: datetime | None = None) -> str | None:
        """Check if TOU period has changed since last check.

        Returns the new period name if changed, None otherwise.
        """
        current = self.get_current_period(now)
        if self._last_period is not None and current != self._last_period:
            old = self._last_period
            self._last_period = current
            _LOGGER.info("TOU period transition: %s -> %s", old, current)
            return current
        self._last_period = current
        return None

    # v4.5.0 D8: high-rate transition awareness for arbitrage charge window
    # ------------------------------------------------------------------
    # `get_next_transition` only walks intra-day in the current season's
    # rate table; arbitrage charge windows can stretch across midnight
    # (summer off-peak 21:00→14:00 next day, winter 21:00→05:00 next day),
    # so we need a helper that walks forward in real time and changes
    # season/month if it has to.
    def _period_at(self, dt: datetime) -> str:
        """Return the TOU period for an arbitrary datetime (handles cross-month)."""
        return self.get_current_period(dt)

    def get_next_high_rate_transition(
        self,
        now: datetime | None = None,
        lookback_hours: int = 36,
    ) -> tuple[datetime, str] | None:
        """Return the next time TOU leaves off_peak and enters mid_peak/peak.

        v4.5.0 D8. Walks forward at hour granularity up to ``lookback_hours``
        into the future. The returned datetime is the (top-of-hour) start of
        the first non-off_peak hour. ``period_name`` is "mid_peak" or "peak".

        Returns None if no high-rate window is found in the lookback window
        (e.g. extended off-peak holiday rate, or future-PEC schedule with
        no peaks). Callers must handle None — typically by skipping the
        arbitrage gate that tick (no charge fires).

        Crosses midnight cleanly: scans `now` itself if currently off_peak,
        then steps to the top of the next hour and continues. Boundaries
        align with the underlying rate table which is hour-granular.
        """
        if now is None:
            now = dt_util.now()

        # Start from the top of `now`'s hour and step forward.
        # If we're already inside a high-rate hour, the immediate scan still
        # finds it — but the caller should be aware that "transition" then
        # equals "in progress" (we return now-on-the-hour).
        cursor = now.replace(minute=0, second=0, microsecond=0)
        end = cursor + timedelta(hours=int(lookback_hours))

        # Track whether we've seen at least one off_peak hour first;
        # if `now` itself is high-rate, returning that hour is correct
        # (the caller is asking "what's the next non-off_peak boundary?").
        # But we want a TRANSITION, so require a switch *into* high-rate.
        prev_period = self._period_at(cursor)
        cursor += timedelta(hours=1)
        while cursor <= end:
            cur_period = self._period_at(cursor)
            if cur_period != "off_peak" and prev_period == "off_peak":
                return (cursor, cur_period)
            prev_period = cur_period
            cursor += timedelta(hours=1)
        return None

    def get_today_high_rate_transitions(
        self,
        now: datetime | None = None,
    ) -> list[tuple[int, str]]:
        """Diagnostic helper — list of (hour, period) for today's high-rate windows.

        Used by sensors and tests for at-a-glance display of when arbitrage
        will/should fire. Reads the active season's rate table directly so
        we don't accidentally miss the "winter has two windows" case.
        """
        if now is None:
            now = dt_util.now()
        season = self.get_season(now)
        out: list[tuple[int, str]] = []
        for period_name, period_data in self._rates[season]["periods"].items():
            if period_name == "off_peak":
                continue
            for start, _end in period_data["hours"]:
                out.append((int(start), period_name))
        out.sort()
        return out

    def get_period_info(self, now: datetime | None = None) -> dict[str, Any]:
        """Return comprehensive info about current TOU state."""
        if now is None:
            now = dt_util.now()
        season = self.get_season(now)
        period = self.get_current_period(now)
        return {
            "season": season,
            "period": period,
            "import_rate": self.get_current_rate(now),
            "export_rate": self.get_export_rate(now),
            "effective_import_rate": self.get_effective_import_rate(now),
            "fixed_charges": self._fixed,
            "next_transition": self.get_next_transition(now),
            "rate_source": self._rate_source,
        }
