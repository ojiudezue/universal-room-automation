"""TOU (Time-of-Use) rate engine for Energy Coordinator.

Resolves current season, TOU period, and import/export rates based on
the PEC Interconnect TOU rate schedule.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .energy_const import PEC_FIXED_CHARGES, PEC_TOU_RATES

_LOGGER = logging.getLogger(__name__)

# Sane rate-magnitude ceiling for a residential $/kWh knob. PEC peaks at
# ~0.16 $/kWh; every real US residential tariff is well under 1.00. Ten
# dollars/kWh is a two-decimal-typo away from a real rate ("1.61" typed as
# "16.1") and safely above any legitimate future rate. Reject anything above.
_MAX_RATE_MAGNITUDE_USD_PER_KWH = 10.0

# All calendar months must be covered by exactly one season across the file.
_ALL_MONTHS: frozenset[int] = frozenset(range(1, 13))


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
        """Read and parse TOU JSON file (always called via async_from_json_file executor wrapper)."""
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
    def _validate_parsed_data(cls, data: Any) -> list[str]:
        """Return a list of validation errors for a parsed TOU rate JSON blob.

        WHOLE-FILE-REJECTION contract (mirrors ``exterior_seams.validate_seam_spec``):
        every violation is collected, so the operator sees ALL faults at once
        rather than one-at-a-time. A non-empty return means the caller MUST
        reject the file wholesale and fall back to the PEC built-ins — the
        SAME behaviour as a missing/unparseable file, so a bad file never
        leaves the system without rates.

        Rules enforced:
          * root is a dict with a non-empty ``seasons`` mapping;
          * every period declares a NUMERIC rate — no silent 0.0 defaulting
            on a mistyped field name (this is the whole point of the card);
          * import rates are >= 0 (a negative import rate is either a typo or
            an unsupported net-metering convention), export rates may be
            negative (some tariffs charge for export) but magnitudes on both
            sides are capped at ``_MAX_RATE_MAGNITUDE_USD_PER_KWH``;
          * ``hours`` are integer [start, end] pairs with 0 <= start < end <= 24
            and MUST NOT overlap other periods within the same season;
          * every season declares an ``off_peak`` period (existing invariant);
          * unknown period names (after alias normalization) are REJECTED
            wholesale — a deliberate semantic change from the previous
            warn+skip behaviour, so a misspelled period can no longer sneak
            through and drop that season's arbitrage window silently;
          * ``months`` are integers in 1..12, cover every month exactly once
            across all seasons (no gap, no double-claim).
        """
        errors: list[str] = []

        if not isinstance(data, dict):
            return ["TOU rate file root must be a JSON object"]

        seasons = data.get("seasons")
        if not isinstance(seasons, dict) or not seasons:
            errors.append("'seasons' must be a non-empty object")
            return errors

        months_seen: dict[int, str] = {}

        for season_name, season_data in seasons.items():
            if not isinstance(season_data, dict):
                errors.append(f"season '{season_name}': must be an object")
                continue

            # ── months ───────────────────────────────────────────────────
            months = season_data.get("months")
            if not isinstance(months, list) or not months:
                errors.append(
                    f"season '{season_name}': 'months' must be a non-empty list"
                )
            else:
                for m in months:
                    if isinstance(m, bool) or not isinstance(m, int) or not (1 <= m <= 12):
                        errors.append(
                            f"season '{season_name}': invalid month {m!r} (must be integer 1..12)"
                        )
                        continue
                    if m in months_seen:
                        errors.append(
                            f"month {m} claimed by both seasons '{months_seen[m]}' and '{season_name}'"
                        )
                    else:
                        months_seen[m] = season_name

            # ── periods ──────────────────────────────────────────────────
            periods = season_data.get("periods")
            if not isinstance(periods, dict) or not periods:
                errors.append(
                    f"season '{season_name}': 'periods' must be a non-empty object"
                )
                continue

            seen_internal: dict[str, str] = {}
            intervals: list[tuple[int, int, str]] = []

            for period_name, period_data in periods.items():
                internal_name = cls._PERIOD_ALIASES.get(period_name, period_name)
                if internal_name not in cls._VALID_PERIODS:
                    errors.append(
                        f"season '{season_name}': unknown period '{period_name}' "
                        f"(valid: {sorted(cls._VALID_PERIODS)} plus aliases like 'on_peak')"
                    )
                    continue
                if internal_name in seen_internal:
                    errors.append(
                        f"season '{season_name}': period '{internal_name}' declared twice "
                        f"(as '{seen_internal[internal_name]}' and '{period_name}')"
                    )
                    continue
                seen_internal[internal_name] = period_name

                if not isinstance(period_data, dict):
                    errors.append(
                        f"season '{season_name}' period '{period_name}': must be an object"
                    )
                    continue

                # Rate presence — the discriminating rule. A misspelled
                # 'rates' would previously default to 0.0 silently; require
                # at least one of import_rate / export_rate / rate, and
                # then validate whichever are present.
                has_import = "import_rate" in period_data
                has_export = "export_rate" in period_data
                has_sym = "rate" in period_data
                if not (has_import or has_export or has_sym):
                    errors.append(
                        f"season '{season_name}' period '{period_name}': missing rate — "
                        "require 'import_rate' + 'export_rate' (preferred) or a single "
                        "'rate' field; no default is applied"
                    )

                def _check(field: str, value: Any, allow_negative: bool) -> None:
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        errors.append(
                            f"season '{season_name}' period '{period_name}': "
                            f"'{field}' must be numeric (got {value!r})"
                        )
                        return
                    if not math.isfinite(value):
                        errors.append(
                            f"season '{season_name}' period '{period_name}': "
                            f"'{field}' must be finite (got {value!r})"
                        )
                        return
                    if not allow_negative and value < 0:
                        errors.append(
                            f"season '{season_name}' period '{period_name}': "
                            f"'{field}' must be >= 0 (got {value})"
                        )
                    if abs(value) > _MAX_RATE_MAGNITUDE_USD_PER_KWH:
                        errors.append(
                            f"season '{season_name}' period '{period_name}': "
                            f"'{field}' magnitude {value} exceeds sane limit "
                            f"{_MAX_RATE_MAGNITUDE_USD_PER_KWH} $/kWh"
                        )

                if has_import:
                    _check("import_rate", period_data["import_rate"], allow_negative=False)
                if has_export:
                    # Some tariffs charge for over-export; allow negatives.
                    _check("export_rate", period_data["export_rate"], allow_negative=True)
                if has_sym and not (has_import or has_export):
                    _check("rate", period_data["rate"], allow_negative=False)

                # Hours
                hours = period_data.get("hours")
                if not isinstance(hours, list) or not hours:
                    errors.append(
                        f"season '{season_name}' period '{period_name}': "
                        "'hours' must be a non-empty list of [start,end] pairs"
                    )
                    continue
                for i, h in enumerate(hours):
                    if not isinstance(h, (list, tuple)) or len(h) != 2:
                        errors.append(
                            f"season '{season_name}' period '{period_name}' hours[{i}]: "
                            "must be a 2-element [start,end] pair"
                        )
                        continue
                    start, end = h
                    if (
                        isinstance(start, bool) or isinstance(end, bool)
                        or not isinstance(start, int) or not isinstance(end, int)
                    ):
                        errors.append(
                            f"season '{season_name}' period '{period_name}' hours[{i}]: "
                            f"start/end must be integers (got {start!r}, {end!r})"
                        )
                        continue
                    if not (0 <= start < end <= 24):
                        errors.append(
                            f"season '{season_name}' period '{period_name}' hours[{i}]: "
                            f"[{start},{end}] out of range (need 0 <= start < end <= 24)"
                        )
                        continue
                    intervals.append((start, end, period_name))

            # off_peak invariant preserved
            if "off_peak" not in seen_internal:
                errors.append(
                    f"season '{season_name}': missing required 'off_peak' period"
                )

            # Overlap check across all validated intervals in this season
            sorted_ivs = sorted(intervals, key=lambda x: x[0])
            for i in range(len(sorted_ivs) - 1):
                s1, e1, n1 = sorted_ivs[i]
                s2, e2, n2 = sorted_ivs[i + 1]
                if s2 < e1:
                    errors.append(
                        f"season '{season_name}': overlapping hours between "
                        f"'{n1}' [{s1},{e1}] and '{n2}' [{s2},{e2}]"
                    )

        # Month coverage across the whole file
        uncovered = sorted(_ALL_MONTHS - set(months_seen))
        if uncovered:
            errors.append(f"months not covered by any season: {uncovered}")

        return errors

    @classmethod
    def _from_parsed_data(cls, data: dict, filepath_str: str, filename: str) -> "TOURateEngine":
        """Build a TOURateEngine from already-parsed JSON data.

        WHOLE-FILE REJECTION: run the validator first; if ANY rule fails, log
        all errors and return the built-in PEC engine — the same fail-safe as
        the missing-file path.
        """
        errors = cls._validate_parsed_data(data)
        if errors:
            _LOGGER.error(
                "TOU rate file %s rejected (%d validation error(s)) — falling back to PEC defaults:\n  - %s",
                filepath_str, len(errors), "\n  - ".join(errors),
            )
            return cls()

        # Convert JSON format to internal rate table format
        try:
            rate_table = {}
            for season_name, season_data in data["seasons"].items():
                periods = {}
                for period_name, period_data in season_data["periods"].items():
                    # Normalize period names (e.g. "on_peak" → "peak")
                    internal_name = cls._PERIOD_ALIASES.get(period_name, period_name)
                    hours = [tuple(h) for h in period_data["hours"]]
                    # Support separate import/export rates; fall back to
                    # symmetric "rate" field for backward compat. Validator
                    # guarantees at least one of the three is present and
                    # numeric — no 0.0 sentinel needed.
                    if "import_rate" in period_data or "export_rate" in period_data:
                        symmetric = period_data.get("rate")  # may be None; unused if both sides present
                        import_rate = period_data.get("import_rate", symmetric)
                        export_rate = period_data.get("export_rate", symmetric)
                    else:
                        symmetric = period_data["rate"]
                        import_rate = symmetric
                        export_rate = symmetric
                    periods[internal_name] = {
                        "hours": hours,
                        "import_rate": import_rate,
                        "export_rate": export_rate,
                    }
                rate_table[season_name] = {
                    "months": season_data["months"],
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

        # Wrap to next day's first different period.
        # Use the NEXT day's season table — a season-boundary day (e.g. Sep 30
        # → Oct 1, summer → shoulder) otherwise returns hours from today's
        # table, which is wrong for the post-midnight period. Intra-day path
        # above is unchanged.
        next_day_season = self.get_season(now + timedelta(days=1))
        next_day_transitions: list[tuple[int, str]] = []
        for period_name, period_data in self._rates[next_day_season]["periods"].items():
            for start, _end in period_data["hours"]:
                next_day_transitions.append((start, period_name))
        next_day_transitions.sort()
        for t_hour, t_period in next_day_transitions:
            if t_period != current_period:
                return {
                    "next_period": t_period,
                    "hours_until": (24 - current_hour) + t_hour,
                    "transition_hour": t_hour,
                }

        return {"next_period": "off_peak", "hours_until": 24, "transition_hour": 0}

    def get_next_period_change_dt(
        self,
        now: datetime | None = None,
        lookahead_hours: int = 36,
    ) -> datetime | None:
        """Return the wall-clock datetime of the next ANY-period change.

        v5.17.3 D1: TOU-boundary-aligned decision tick uses this to arm a
        point-in-time listener so a decision runs exactly at each period
        boundary (avoiding 0-5min lag from the periodic tick).

        Walks forward at hour granularity starting from the top of the next
        hour and returns the first datetime whose period differs from the
        current period. Season/month/midnight-safe because
        ``get_current_period`` re-derives from the wall-clock month+hour on
        every call. Returns None only if no transition is found within the
        lookahead window (pathological — extended flat-rate schedule).

        Unlike ``get_next_high_rate_transition`` this returns ANY transition
        (peak↔mid_peak↔off_peak) and unlike ``get_next_transition`` it
        returns a real datetime (not just an offset in hours).
        """
        if now is None:
            now = dt_util.now()
        current_period = self.get_current_period(now)
        cursor = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        end = cursor + timedelta(hours=int(lookahead_hours))
        while cursor <= end:
            if self.get_current_period(cursor) != current_period:
                return cursor
            cursor += timedelta(hours=1)
        return None

    def peak_ahead_before_offpeak(
        self,
        now: datetime | None = None,
        lookahead_hours: int = 24,
    ) -> bool:
        """Return True if a peak hour occurs before the next off_peak hour.

        Intent: called from a mid_peak tick to answer "is a real peak still
        ahead of me before off_peak resumes?" — used by BatteryStrategy to
        decide hold-vs-discharge during summer mid_peak, which is a *bracketed*
        period (pre-peak window then peak then post-peak window). Holding is
        correct PRE-peak; discharging is correct POST-peak.

        Walks forward at hour granularity starting from the top of the next
        hour, calling ``get_current_period(dt)`` each step. This is inherently
        season/month/midnight-safe because ``get_current_period`` derives both
        season (from ``dt.month``) and period (from ``dt.hour``) on every call.

        Returns True on the first hour whose period is ``"peak"``; returns
        False on the first hour whose period is ``"off_peak"``; keeps walking
        through ``"mid_peak"``. Returns False if neither is encountered within
        ``lookahead_hours``.

        Callers are expected to already know the current period (the walk
        excludes ``now``'s own hour by design — it starts at the top of the
        NEXT hour). Invoking this from outside a mid_peak hour is a no-op
        with a meaningful but caller-specific interpretation.

        ``get_next_high_rate_transition`` cannot be reused for this
        question: it requires a transition INTO high-rate (prev hour ==
        off_peak), so calling it from inside a mid_peak hour returns None
        (there is no prior off_peak hour to transition from).
        """
        if now is None:
            now = dt_util.now()
        cursor = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        end = cursor + timedelta(hours=int(lookahead_hours) - 1)
        while cursor <= end:
            period = self.get_current_period(cursor)
            if period == "peak":
                return True
            if period == "off_peak":
                return False
            cursor += timedelta(hours=1)
        return False

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
