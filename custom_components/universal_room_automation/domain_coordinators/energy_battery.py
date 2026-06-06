"""Battery strategy for Energy Coordinator.

Reads battery SOC, solar production, and grid state from Enphase entities.
Determines optimal battery storage mode based on TOU period and conditions.

v4.5.0 (Battery Strategy Redesign):
    Off-peak is now a four-phase state machine when arbitrage is enabled
    AND the next-high-rate-window day is forecast poor/very_poor:
        WAIT → CHARGE → HOLD → DISCHARGE
    Drain targets remain the fallback path when arbitrage is disabled or
    forecast is excellent/good/moderate/unknown. Reserve_level is a
    *discharge floor*, never a charge ceiling — solar can still charge
    above target during HOLD.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant

from .energy_const import (
    BATTERY_MODE_BACKUP,
    BATTERY_MODE_SELF_CONSUMPTION,
    DEFAULT_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
    DEFAULT_ARBITRAGE_GRID_IMPORT_GUARD_KW,
    DEFAULT_ARBITRAGE_SOC_TARGET,
    DEFAULT_CHARGE_FROM_GRID_ENTITY,
    DEFAULT_GRID_ENABLED_ENTITY,
    DEFAULT_OFFPEAK_DRAIN_EXCELLENT,
    DEFAULT_OFFPEAK_DRAIN_GOOD,
    DEFAULT_OFFPEAK_DRAIN_MODERATE,
    DEFAULT_OFFPEAK_DRAIN_POOR,
    DEFAULT_OFFPEAK_DRAIN_UNKNOWN,
    DEFAULT_PEAK_BUFFER_TARGET,
    DEFAULT_RESERVE_SOC,
    DEFAULT_RESERVE_SOC_ENTITY,
    DEFAULT_SOLCAST_REMAINING_ENTITY,
    DEFAULT_SOLCAST_TODAY_ENTITY,
    DEFAULT_SOLCAST_TOMORROW_ENTITY,
    DEFAULT_STORAGE_MODE_ENTITY,
    DEFAULT_STORM_CHARGE_THRESHOLD,
    DEFAULT_WEATHER_ENTITY,
    MAX_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
    MIN_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
    SOLAR_DAY_THRESHOLDS,
    SOLAR_MONTHLY_THRESHOLDS,
)

# v4.5.0 D1: arbitrage phase names. Single source of truth — used by the
# state matrix routing in determine_mode(), the sensor `arbitrage_phase`
# attribute (D6), and the D4 EV mutual-exclusion logic (which gates on
# `phase == ARBITRAGE_PHASE_CHARGE`).
ARBITRAGE_PHASE_WAIT = "wait"
ARBITRAGE_PHASE_CHARGE = "charge"
ARBITRAGE_PHASE_HOLD = "hold"
ARBITRAGE_PHASE_DISCHARGE = "discharge"
ARBITRAGE_PHASE_NA = "n/a"

_LOGGER = logging.getLogger(__name__)


class BatteryStrategy:
    """Determines battery mode and actions based on TOU period and system state."""

    def __init__(
        self,
        hass: HomeAssistant,
        reserve_soc: int = DEFAULT_RESERVE_SOC,
        entity_config: dict[str, str] | None = None,
        solar_classification_mode: str = "automatic",
        custom_solar_thresholds: dict[str, float] | None = None,
        offpeak_drain_targets: dict[str, int] | None = None,
        arbitrage_enabled: bool = False,
        arbitrage_soc_target: int = DEFAULT_ARBITRAGE_SOC_TARGET,
        peak_buffer_target: int | None = None,
        arbitrage_charge_lead_time_min: int = DEFAULT_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
        arbitrage_grid_import_guard_kw: float = DEFAULT_ARBITRAGE_GRID_IMPORT_GUARD_KW,
        tou_engine: Any = None,
        multi_day_horizon_enabled: bool = False,
        solcast_day_3_entity: str | None = None,
    ) -> None:
        """Initialize battery strategy.

        v4.5.0 D1 added:
            peak_buffer_target — replaces arbitrage_soc_target as the
                runtime knob for "stop charging at this SOC". Defaults to
                arbitrage_soc_target for migration ergonomics; D2 finalizes
                the rename in entity/coord call sites.
            arbitrage_charge_lead_time_min — minutes before next high-rate
                transition that the charge window opens. Live-tunable via
                D2's number-box entity. Hard-clamped to
                [MIN_…, MAX_…] in the setter.
            tou_engine — TOURateEngine reference for D8 charge-window math.
                Optional so older test paths and unit tests can construct
                BatteryStrategy without one (falls back to "n/a" phase).
            multi_day_horizon_enabled / solcast_day_3_entity — D3.

        Drain targets (Phase A) remain unchanged from v4.3.4 — they are
        the canonical fallback whenever arbitrage_enabled=False or
        target_day_class ∉ (poor, very_poor). State matrix in plan is
        authoritative.
        """
        self.hass = hass
        self.reserve_soc = reserve_soc
        self._entities = entity_config or {}
        self._last_mode: str | None = None
        self._last_reason: str = ""
        self._solar_classification_mode = solar_classification_mode
        self._custom_solar_thresholds = custom_solar_thresholds

        # Phase A: Off-peak drain targets by tomorrow's solar class
        dt = offpeak_drain_targets or {}
        self._drain_targets: dict[str, int] = {
            "excellent": dt.get("excellent", DEFAULT_OFFPEAK_DRAIN_EXCELLENT),
            "good": dt.get("good", DEFAULT_OFFPEAK_DRAIN_GOOD),
            "moderate": dt.get("moderate", DEFAULT_OFFPEAK_DRAIN_MODERATE),
            "poor": dt.get("poor", DEFAULT_OFFPEAK_DRAIN_POOR),
            "very_poor": dt.get("very_poor", dt.get("poor", DEFAULT_OFFPEAK_DRAIN_POOR)),
            "unknown": dt.get("unknown", DEFAULT_OFFPEAK_DRAIN_UNKNOWN),
        }

        # Phase B (v4.3.4 → v4.5.0): the SOC trigger gate is GONE. v4.5.0's
        # arbitrage gate is forecast-class only. The previous _arbitrage_trigger
        # field is removed per the D2 acceptance criteria.
        self._arbitrage_enabled = arbitrage_enabled
        # Canonical name post-v4.5.0 D2.
        self._peak_buffer_target = (
            peak_buffer_target if peak_buffer_target is not None
            else arbitrage_soc_target
        )
        self._arbitrage_active = False

        # v4.5.0 D1: phased state machine. WAIT/CHARGE/HOLD apply within
        # the off-peak chunk leading into the next high-rate transition.
        # DISCHARGE is the existing peak/mid_peak path. Phase resets to
        # "n/a" outside off-peak or when arbitrage gate doesn't fire.
        self._arbitrage_phase: str = ARBITRAGE_PHASE_NA
        self._arbitrage_chunk_completed: bool = False
        # One-shot flag — TRUE after first CHARGE-window forecast re-check
        # in this off-peak chunk (don't re-check repeatedly per plan).
        self._chunk_recheck_done: bool = False
        self._arbitrage_charge_lead_time_min: int = self._clamp_lead_time(
            arbitrage_charge_lead_time_min
        )
        # v4.5.0.2: defensive grid-import guard threshold (kW). When
        # actual grid import exceeds this during a CHARGE tick, the
        # chunk is aborted (chunk_completed=True, return WAIT) to
        # protect against undersized breakers. One-shot per chunk.
        try:
            self._arbitrage_grid_import_guard_kw: float = float(
                arbitrage_grid_import_guard_kw
            )
        except (TypeError, ValueError):
            self._arbitrage_grid_import_guard_kw = (
                DEFAULT_ARBITRAGE_GRID_IMPORT_GUARD_KW
            )
        # Diagnostic surface — populated when the guard fires, so the
        # sensor and tests can assert on the abort cause.
        self._arbitrage_guard_aborted_at: str | None = None
        self._arbitrage_guard_aborted_kw: float | None = None

        # v4.5.0 D8 hookup. May be None when constructed from a test
        # harness or before the EnergyCoordinator finishes wiring.
        self._tou = tou_engine

        # v4.5.0 D3: multi-day Solcast lookback toggle + entity ID.
        # Used by classify_solar_day_n + arbitrage gate broadening.
        self._multi_day_horizon_enabled: bool = multi_day_horizon_enabled
        self._solcast_day_3_entity: str | None = solcast_day_3_entity

    @staticmethod
    def _clamp_lead_time(value: int) -> int:
        """Clamp arbitrage_charge_lead_time_min to [MIN_…, MAX_…].

        v4.5.0 D2 enforces the same range at the entity layer
        (NumberMode.BOX with native_min/max), but coordinator-level
        callers (programmatic, tests) must also be safe — so we clamp
        here too. Caller should log a warning when clamping fires; this
        method is silent because it's called from __init__ where logging
        is OK to skip.
        """
        try:
            v = int(value)
        except (TypeError, ValueError):
            return DEFAULT_ARBITRAGE_CHARGE_LEAD_TIME_MIN
        return max(
            MIN_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
            min(MAX_ARBITRAGE_CHARGE_LEAD_TIME_MIN, v),
        )

    def _get_entity(self, key: str, default: str | None = None) -> str | None:
        """Get entity ID from config or default.

        v4.3.1: default is now optional (None). Envoy-derived entities have
        no production default — they MUST come via config (auto-derive seeds
        them in __init__.py). Non-envoy entities (Solcast, Enpower, Weather)
        still pass their hardcoded defaults explicitly.
        """
        return self._entities.get(key, default)

    def _get_state_float(self, entity_id: str | None) -> float | None:
        """Get numeric state from an entity. None entity_id → None."""
        if entity_id is None:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _get_state_str(self, entity_id: str | None) -> str | None:
        """Get string state from an entity. None entity_id → None."""
        if entity_id is None:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        return state.state

    def _get_state_bool(self, entity_id: str | None) -> bool | None:
        """Get boolean state from a switch entity. None entity_id → None."""
        if entity_id is None:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        return state.state == "on"

    @property
    def battery_soc(self) -> float | None:
        """Current battery state of charge (%). None if envoy not configured."""
        return self._get_state_float(self._get_entity("battery_soc"))

    @property
    def solar_production(self) -> float | None:
        """Current solar production in watts. None if envoy not configured."""
        return self._get_state_float(self._get_entity("solar_production"))

    @property
    def net_power(self) -> float | None:
        """Net power consumption (positive=importing, negative=exporting).

        None if envoy not configured.
        """
        return self._get_state_float(self._get_entity("net_power"))

    @property
    def battery_power(self) -> float | None:
        """Battery power (positive=charging, negative=discharging).

        The new Envoy ``current_battery_discharge`` sensor uses the opposite
        sign convention (positive=discharging), so we negate it here to keep
        the rest of the codebase consistent.

        UNITS: returned as-is from the underlying entity (some Envoy installs
        report W, newer ones report kW). For unit-correct math, use
        :py:attr:`battery_power_w` instead. This raw value is what's shown on
        the strategy sensor display for backward compatibility.
        """
        raw = self._get_state_float(self._get_entity("battery_power"))
        return -raw if raw is not None else None

    @property
    def battery_power_w(self) -> float | None:
        """Battery power normalized to W (positive=charging, negative=discharging).

        v4.3.4 fix: reads the underlying entity's ``unit_of_measurement``
        attribute and multiplies by 1000 if the entity reports in kW.
        Use this for any threshold math (e.g., "is the battery discharging
        more than 100W?") so behavior is correct regardless of Envoy
        firmware/integration version.

        Returns None if entity is missing/unavailable.
        """
        eid = self._get_entity("battery_power")
        if eid is None:
            return None
        state = self.hass.states.get(eid)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            value = -float(state.state)  # flip sign per battery_power convention
        except (ValueError, TypeError):
            return None
        uom = state.attributes.get("unit_of_measurement", "")
        if uom in ("kW", "kw"):
            value *= 1000.0
        return value

    def _read_power_w(self, entity_key: str) -> float | None:
        """Generic power reader normalized to W.

        v4.5.0 unit-consistency sweep: same pattern as battery_power_w but
        without the sign flip. Reads the entity, checks unit_of_measurement,
        scales kW → W if needed. Returns None if entity unavailable.

        Why this matters: callers that previously did `value / 1000.0` to
        convert "Envoy watts" → kW silently break when newer Envoy firmware
        reports the same sensor in kW (the value gets divided again).
        """
        eid = self._get_entity(entity_key)
        if eid is None:
            return None
        state = self.hass.states.get(eid)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            return None
        uom = state.attributes.get("unit_of_measurement", "")
        if uom in ("kW", "kw"):
            value *= 1000.0
        return value

    @property
    def solar_production_w(self) -> float | None:
        """Solar production normalized to W (always).

        v4.5.0: replaces direct reads of ``solar_production`` for any math
        that assumes a specific unit. Production code should use this
        property + a single `/1000.0` step at the kW boundary, never read
        the raw sensor and assume W.
        """
        return self._read_power_w("solar_production")

    @property
    def net_power_w(self) -> float | None:
        """Net power consumption normalized to W (positive=importing).

        v4.5.0: replaces direct reads of ``net_power`` for unit-sensitive
        math (grid_import_cap thresholding, peak-import accounting, billing
        accumulator). Older callers that survived only because the user's
        Envoy reported W are now safe across kW/W firmware variants.
        """
        return self._read_power_w("net_power")

    @property
    def current_storage_mode(self) -> str | None:
        """Current Enpower storage mode."""
        return self._get_state_str(
            self._get_entity("storage_mode", DEFAULT_STORAGE_MODE_ENTITY)
        )

    @property
    def grid_connected(self) -> bool:
        """Whether grid is connected."""
        result = self._get_state_bool(
            self._get_entity("grid_enabled", DEFAULT_GRID_ENABLED_ENTITY)
        )
        return result if result is not None else True

    @property
    def solcast_today(self) -> float | None:
        """Solcast forecast for today in kWh."""
        return self._get_state_float(
            self._get_entity("solcast_today", DEFAULT_SOLCAST_TODAY_ENTITY)
        )

    @property
    def solcast_remaining(self) -> float | None:
        """Solcast remaining forecast for today in kWh."""
        return self._get_state_float(
            self._get_entity("solcast_remaining", DEFAULT_SOLCAST_REMAINING_ENTITY)
        )

    @property
    def solcast_tomorrow(self) -> float | None:
        """Solcast forecast for tomorrow in kWh."""
        return self._get_state_float(
            self._get_entity("solcast_tomorrow", DEFAULT_SOLCAST_TOMORROW_ENTITY)
        )

    @property
    def solcast_day_3(self) -> float | None:
        """v4.5.0 D3: Solcast forecast for D+2 (day-after-tomorrow) in kWh.

        Solcast's `forecast_day_3` sensor is 1-indexed including today,
        i.e. "the third day starting today" == D+2. None when the entity
        isn't configured (multi-day horizon disabled or no Solcast subscription).
        """
        eid = self._solcast_day_3_entity or self._get_entity("solcast_day_3")
        return self._get_state_float(eid)

    def classify_tomorrow_solar(self) -> str:
        """Classify tomorrow's solar forecast using per-month thresholds.

        Same logic as classify_solar_day() but reads the tomorrow entity
        and uses tomorrow's month for threshold lookup.
        """
        forecast = self.solcast_tomorrow
        if forecast is None:
            return "unknown"

        if self._solar_classification_mode == "custom" and self._custom_solar_thresholds:
            for classification, threshold in sorted(
                self._custom_solar_thresholds.items(),
                key=lambda x: x[1],
                reverse=True,
            ):
                if forecast >= threshold:
                    return classification
            return "very_poor"

        from homeassistant.util import dt as dt_util
        from datetime import timedelta
        tomorrow = (dt_util.now() + timedelta(days=1)).month
        p25, p50, p75 = SOLAR_MONTHLY_THRESHOLDS.get(tomorrow, (50.0, 80.0, 100.0))
        if forecast >= p75:
            return "excellent"
        if forecast >= p50:
            return "good"
        if forecast >= p25:
            return "moderate"
        return "poor"

    def _get_offpeak_drain_target(self, tomorrow_class: str) -> int:
        """Get the SOC drain target for off-peak based on tomorrow's solar class."""
        return self._drain_targets.get(tomorrow_class, DEFAULT_OFFPEAK_DRAIN_UNKNOWN)

    def classify_solar_day_n(self, days_ahead: int) -> str:
        """v4.5.0 D3: classify the solar forecast for `days_ahead` from today.

        Reads the appropriate Solcast entity:
            days_ahead == 0 → today's entity (classify_solar_day)
            days_ahead == 1 → tomorrow's entity (classify_tomorrow_solar)
            days_ahead == 2 → solcast_day_3 entity (D+2)
        Uses per-month percentile thresholds keyed on the *target day's*
        month, so a forecast that crosses a month boundary uses correct
        thresholds. Returns "unknown" if the underlying entity is not
        configured or unavailable.
        """
        if days_ahead <= 0:
            return self.classify_solar_day()
        if days_ahead == 1:
            return self.classify_tomorrow_solar()
        if days_ahead != 2:
            # v4.5.0 only supports D+2; deeper horizons fall back to D+1.
            # Plan defers further-out (D+3+) to v4.6.x advanced topics.
            return self.classify_tomorrow_solar()

        forecast = self.solcast_day_3
        if forecast is None:
            return "unknown"

        if (
            self._solar_classification_mode == "custom"
            and self._custom_solar_thresholds
        ):
            for classification, threshold in sorted(
                self._custom_solar_thresholds.items(),
                key=lambda x: x[1],
                reverse=True,
            ):
                if forecast >= threshold:
                    return classification
            return "very_poor"

        from homeassistant.util import dt as dt_util
        target = (dt_util.now() + timedelta(days=days_ahead)).month
        p25, p50, p75 = SOLAR_MONTHLY_THRESHOLDS.get(target, (50.0, 80.0, 100.0))
        if forecast >= p75:
            return "excellent"
        if forecast >= p50:
            return "good"
        if forecast >= p25:
            return "moderate"
        return "poor"

    def classify_solar_day(self) -> str:
        """Classify today's solar forecast: excellent/good/moderate/poor/very_poor.

        Uses per-month percentile thresholds by default, or custom absolute
        thresholds if configured.
        """
        forecast = self.solcast_today
        if forecast is None:
            return "unknown"

        if self._solar_classification_mode == "custom" and self._custom_solar_thresholds:
            for classification, threshold in sorted(
                self._custom_solar_thresholds.items(),
                key=lambda x: x[1],
                reverse=True,
            ):
                if forecast >= threshold:
                    return classification
            return "very_poor"

        # Automatic (monthly) mode — use per-month P25/P50/P75
        from homeassistant.util import dt as dt_util
        month = dt_util.now().month
        p25, p50, p75 = SOLAR_MONTHLY_THRESHOLDS.get(month, (50.0, 80.0, 100.0))
        if forecast >= p75:
            return "excellent"
        if forecast >= p50:
            return "good"
        if forecast >= p25:
            return "moderate"
        return "poor"

    def has_storm_forecast(self) -> bool:
        """Check weather entity for storm/severe weather conditions."""
        weather_entity = self._get_entity("weather", DEFAULT_WEATHER_ENTITY)
        state = self.hass.states.get(weather_entity)
        if state is None:
            return False
        condition = state.state.lower()
        storm_conditions = {
            "lightning", "lightning-rainy", "hail",
            "tornado", "hurricane", "exceptional",
        }
        return condition in storm_conditions

    @property
    def envoy_available(self) -> bool:
        """Whether the Envoy is responding (SOC and storage mode both readable)."""
        return self.battery_soc is not None and self.current_storage_mode is not None

    # ------------------------------------------------------------------
    # v4.5.0 D1: arbitrage four-phase state machine
    # ------------------------------------------------------------------

    def _classify_target_day(self, now: datetime) -> str:
        """Class of the day containing the next high-rate transition.

        Without this, the gate would always read "tomorrow" (D+1 of now),
        which is wrong when the chunk crosses midnight: at 21:00 today
        "tomorrow" is the right day to forecast (target window 14:00 the
        next day), but at 08:00 the next morning the same chunk's target
        is now TODAY at 14:00 — and the right entity to read is today's
        Solcast, not tomorrow's.

        Falls back to `classify_tomorrow_solar()` when the TOU engine
        isn't wired (test path) or when no high-rate window is found in
        the lookback window. Either case: the legacy "tomorrow=poor" gate
        is a safe approximation.
        """
        if self._tou is None:
            return self.classify_tomorrow_solar()
        nxt = self._tou.get_next_high_rate_transition(now)
        if nxt is None:
            return self.classify_tomorrow_solar()
        target_dt, _ = nxt
        offset = (target_dt.date() - now.date()).days
        if offset <= 0:
            return self.classify_solar_day()
        if offset == 1:
            return self.classify_tomorrow_solar()
        # offset >= 2 — D3 multi-day path
        return self.classify_solar_day_n(offset)

    def _is_charge_window_open(self, now: datetime) -> bool:
        """True when (next_high_rate_transition - now) <= lead_time_min.

        Returns False when the TOU engine isn't wired or no high-rate
        window is found. v4.5.0 D8's `get_next_high_rate_transition`
        walks across midnight, so this works for cross-day off-peak
        chunks (summer 21:00 → 14:00 next day; winter 21:00 → 05:00).
        """
        if self._tou is None:
            return False
        nxt = self._tou.get_next_high_rate_transition(now)
        if nxt is None:
            return False
        target_dt, _ = nxt
        delta = target_dt - now
        return delta.total_seconds() <= self._arbitrage_charge_lead_time_min * 60

    def _recheck_forecast_on_charge_entry(self, now: datetime) -> bool:
        """Re-evaluate the gate at the moment WAIT→CHARGE would fire.

        For same-day target windows (e.g. summer 14:00 mid_peak from an
        08:00 CHARGE entry), this benefits from intraday solar telemetry
        Solcast has accumulated since sunrise. Returns True iff the
        target_day_class is still poor/very_poor (or D+2 equivalent when
        multi_day_horizon_enabled). Caller marks chunk_completed and
        stays in WAIT when this returns False.

        Idempotent within a chunk: the caller (`_get_arbitrage_phase`)
        only invokes this once per chunk via `_chunk_recheck_done`.
        """
        target_class = self._classify_target_day(now)
        if target_class in ("poor", "very_poor"):
            return True
        if self._multi_day_horizon_enabled:
            d2_class = self.classify_solar_day_n(2)
            if d2_class in ("poor", "very_poor"):
                return True
        return False

    def _grid_import_guard_triggered(self) -> bool:
        """True iff non-battery grid import (house + EV draw) exceeds the guard.

        Reads `net_power_w` (already unit-normalized via the v4.5.0 sweep —
        see Bug Class #30) and subtracts the battery's own charge power
        before comparing to the cap. The guard exists to prevent excess
        grid draw from house+EV loads tripping the panel breaker — not to
        constrain battery charge-from-grid itself. Without the subtraction,
        the act of arbitrage CHARGE drives `net_power` above the cap and
        self-aborts (observed live: net 18.6 kW with battery charging 15.8
        kW and non-battery draw flat ~2.8 kW tripped a 12 kW cap).

        Sign convention (see ``battery_power_w`` docstring): positive =
        charging, negative = discharging. We subtract only when charging
        (``max(0.0, battery_power_w)``) so that a discharging battery
        cannot *raise* the effective import.

        None-handling / fail-safe:
            * ``net_power_w`` is None (envoy unavailable) → return False;
              the envoy-unavailable branch upstream handles that case.
            * ``battery_power_w`` is None (battery sensor briefly
              unavailable) → do NOT subtract; fall back to comparing
              total ``net_power_w`` against the cap. A sensor dropout
              must never *uncap* the guard.

        Threshold default 12 kW (60A breaker sized). Configurable via
        ``arbitrage_grid_import_guard_kw`` constructor arg.
        """
        net_w = self.net_power_w
        if net_w is None:
            return False
        batt_w = self.battery_power_w
        # Fail-safe: if the battery sensor is unavailable, fall back to the
        # stricter total-import comparison. NEVER uncap the guard because a
        # sensor briefly went None — that would defeat the breaker-protection
        # purpose entirely.
        if batt_w is None:
            effective_w = net_w
        else:
            # Only subtract when charging (positive). A discharging battery
            # (negative battery_power_w) must not be added to net_power.
            effective_w = net_w - max(0.0, batt_w)
        effective_kw = effective_w / 1000.0
        return effective_kw > self._arbitrage_grid_import_guard_kw

    def _gate_is_open(self, now: datetime, target_day_class: str) -> bool:
        """Pre-conditions for *any* arbitrage phase consideration.

        Mirrors the cheat-sheet in the plan: arbitrage_enabled AND
        target_day_class poor/very_poor (or D+2 equivalent) AND grid
        connected. TOU period and storm short-circuit are checked
        upstream in determine_mode() (state matrix invariants 1, 6).
        """
        if not self._arbitrage_enabled:
            return False
        if target_day_class in ("poor", "very_poor"):
            return True
        if self._multi_day_horizon_enabled:
            d2_class = self.classify_solar_day_n(2)
            if d2_class in ("poor", "very_poor"):
                return True
        return False

    def _get_arbitrage_phase(
        self,
        soc: float | None,
        now: datetime,
        target_day_class: str,
    ) -> str:
        """Resolve the arbitrage phase for the current decision tick.

        Returns one of WAIT/CHARGE/HOLD/"n/a" (DISCHARGE is handled by
        the existing peak/mid_peak branches in determine_mode). Only
        called from the off_peak branch — caller must ensure that.

        Phase resolution (first-match wins):
            1. SOC ≥ peak_buffer_target → HOLD
            2. chunk_completed             → WAIT (no further action this chunk)
            3. charge_window_open AND
               forecast re-check passes    → CHARGE
            4. charge_window_open AND
               forecast re-check fails     → WAIT (sets chunk_completed)
            5. else                         → WAIT (window not yet open)
        """
        if not self._gate_is_open(now, target_day_class):
            return ARBITRAGE_PHASE_NA

        # Phase 1 — SOC already at/above target. HOLD locks the buffer
        # in place for the upcoming high-rate window. Also reached when
        # solar pushed SOC above target during HOLD itself, or starting
        # SOC was already there.
        if soc is not None and soc >= self._peak_buffer_target:
            return ARBITRAGE_PHASE_HOLD

        # Phase 2 — chunk locked (already completed CHARGE or aborted
        # via re-check). Stay in WAIT for the rest of the chunk; reset
        # only on TOU transition INTO off-peak.
        if self._arbitrage_chunk_completed:
            return ARBITRAGE_PHASE_WAIT

        # Phase 3/4 — charge window open. Recheck once per chunk; abort
        # cleanly if forecast improved (sets chunk_completed).
        if self._is_charge_window_open(now):
            if not self._chunk_recheck_done:
                self._chunk_recheck_done = True
                if not self._recheck_forecast_on_charge_entry(now):
                    self._arbitrage_chunk_completed = True
                    _LOGGER.info(
                        "Arbitrage CHARGE re-check aborted: target_day_class "
                        "improved at %s; chunk locked",
                        now.isoformat(timespec="minutes") if hasattr(now, "isoformat") else now,
                    )
                    return ARBITRAGE_PHASE_WAIT
            # v4.5.0.2 defensive guard: if actual grid import exceeds the
            # configured threshold, abort the chunk. Protects against
            # undersized breakers tripping under hardware peak draw that
            # the strategy can't directly throttle (Enphase
            # charge_from_grid is binary). One-shot per chunk; the
            # chunk_lock prevents flap. v4.5.1 will replace this with
            # proper rate control via barneyonline HACS.
            if self._grid_import_guard_triggered():
                self._arbitrage_chunk_completed = True
                from homeassistant.util import dt as dt_util
                self._arbitrage_guard_aborted_at = dt_util.now().isoformat()
                # Record the EFFECTIVE (non-battery) import that actually
                # exceeded the cap — that's what the guard compared.
                net_w = self.net_power_w or 0.0
                batt_w = self.battery_power_w
                if batt_w is None:
                    effective_kw = net_w / 1000.0
                else:
                    effective_kw = (net_w - max(0.0, batt_w)) / 1000.0
                self._arbitrage_guard_aborted_kw = effective_kw
                _LOGGER.warning(
                    "Arbitrage CHARGE aborted by grid-import guard: "
                    "effective_import=%.1f kW (net=%.1f kW, battery_charge=%.1f kW) "
                    "exceeds threshold=%.1f kW. Chunk locked; will retry "
                    "next off-peak chunk. (Likely panel breaker risk from "
                    "house+EV draw — consider rate control.)",
                    effective_kw,
                    net_w / 1000.0,
                    max(0.0, (batt_w or 0.0)) / 1000.0,
                    self._arbitrage_grid_import_guard_kw,
                )
                return ARBITRAGE_PHASE_WAIT
            return ARBITRAGE_PHASE_CHARGE

        # Phase 5 — window not open yet. Battery serves loads naturally.
        return ARBITRAGE_PHASE_WAIT

    def _get_arbitrage_decision(
        self,
        soc: float | None,
        now: datetime,
        target_day_class: str,
        tomorrow_class: str,
        current_mode: str | None,
        season: str,
    ) -> dict[str, Any]:
        """Wrap phase resolution + side-effects into the standard decision dict.

        Phase-to-action mapping (per plan's D1):
            WAIT:   reserve = reserve_soc;        no grid charge
            CHARGE: reserve = peak_buffer_target; grid charge ON
            HOLD:   reserve = peak_buffer_target; no grid charge

        Updates `self._arbitrage_phase` for sensor exposure (D6) and
        sets `self._arbitrage_chunk_completed = True` when CHARGE first
        reaches target (so the next tick goes to HOLD without re-firing).
        """
        phase = self._get_arbitrage_phase(soc, now, target_day_class)
        self._arbitrage_phase = phase

        if phase == ARBITRAGE_PHASE_HOLD:
            # If we just transitioned WAIT/CHARGE→HOLD via SOC reaching
            # target, mark the chunk completed so a momentary SOC dip
            # doesn't drop us back into CHARGE on the next tick. (Resets
            # only on TOU transition INTO off-peak.)
            self._arbitrage_chunk_completed = True
            self._arbitrage_active = True
            return self._result(
                BATTERY_MODE_SELF_CONSUMPTION,
                f"Arbitrage HOLD — buffer locked at {self._peak_buffer_target}% "
                f"(target_day={target_day_class})",
                current_mode,
                charge_from_grid=False,
                reserve_level=self._peak_buffer_target,
                season=season,
                tomorrow_solar_class=tomorrow_class,
                arbitrage_active=True,
                arbitrage_phase=phase,
                target_day_class=target_day_class,
            )

        if phase == ARBITRAGE_PHASE_CHARGE:
            self._arbitrage_active = True
            return self._result(
                BATTERY_MODE_SELF_CONSUMPTION,
                f"Arbitrage CHARGE — pulling grid to {self._peak_buffer_target}% "
                f"(target_day={target_day_class})",
                current_mode,
                charge_from_grid=True,
                reserve_level=self._peak_buffer_target,
                season=season,
                tomorrow_solar_class=tomorrow_class,
                arbitrage_active=True,
                arbitrage_phase=phase,
                target_day_class=target_day_class,
            )

        # WAIT — battery serves loads naturally; reserve = safety floor only.
        # Per plan Mistake #7: no artificial drain target. Overnight loads
        # come from battery + solar; CHARGE will refill before the high-rate
        # window regardless of how low SOC drifted during WAIT.
        self._arbitrage_active = False
        return self._result(
            BATTERY_MODE_SELF_CONSUMPTION,
            f"Arbitrage WAIT — charge window not yet open "
            f"(target_day={target_day_class}, lead_time={self._arbitrage_charge_lead_time_min}m)",
            current_mode,
            charge_from_grid=False,
            reserve_level=self.reserve_soc,
            season=season,
            tomorrow_solar_class=tomorrow_class,
            arbitrage_active=False,
            arbitrage_phase=phase,
            target_day_class=target_day_class,
        )

    def reset_arbitrage_chunk(self, reason: str = "off_peak entry") -> None:
        """Reset the per-chunk lock + recheck flag.

        Caller — typically EnergyCoordinator on TOU transition INTO
        off_peak. Used so each off-peak chunk gets exactly one CHARGE
        attempt (no oscillation if forecast wobbles or SOC dips post-
        completion).
        """
        if (
            self._arbitrage_chunk_completed
            or self._chunk_recheck_done
            or self._arbitrage_guard_aborted_at
        ):
            _LOGGER.info("Arbitrage chunk reset (%s)", reason)
        self._arbitrage_chunk_completed = False
        self._chunk_recheck_done = False
        # v4.5.0.2: clear guard diagnostic on chunk reset so each chunk's
        # state is fresh.
        self._arbitrage_guard_aborted_at = None
        self._arbitrage_guard_aborted_kw = None

    def determine_mode(
        self,
        tou_period: str,
        season: str = "summer",
        now: datetime | None = None,
        tou_transition_into: str | None = None,
    ) -> dict[str, Any]:
        """Determine optimal battery mode based on TOU period and conditions.

        Uses self_consumption mode exclusively with reserve level as primary control.
        See ENPHASE_CONTROL_CODICIL.md for rationale — Enphase does not support
        direct battery-to-grid export; savings mode gives up HA control.

        Season matters: shoulder/winter have no peak period, so mid-peak IS the
        highest-rate window.  Battery should discharge during mid-peak in those
        seasons rather than holding for a peak that never comes.

        v4.5.0 D1 added:
            now — current time, used by the phase machine for charge-window
                math. Defaults to dt_util.now().
            tou_transition_into — if EnergyCoordinator's
                `_tou.check_period_transition()` returned a new period name,
                pass it here. When it equals "off_peak" the per-chunk
                arbitrage lock (`_arbitrage_chunk_completed` + recheck flag)
                resets. Storm/disconnect/peak/mid_peak rows of the state
                matrix are unchanged — drain-target rows are byte-for-byte
                identical to v4.3.4 when arbitrage is OFF.

        Returns dict with: mode, reason, actions (list of service calls to make).
        v4.5.0 also includes `arbitrage_phase`, `target_day_class` keys.
        """
        from homeassistant.util import dt as dt_util
        if now is None:
            now = dt_util.now()

        # v4.5.0 D1: chunk lock reset on transition INTO off_peak.
        # `tou_transition_into` is the *new* period name — populated only
        # on the tick where TOU just changed. Other ticks pass None and
        # the lock state persists.
        if tou_transition_into == "off_peak":
            self.reset_arbitrage_chunk(reason="TOU transition INTO off_peak")

        soc = self.battery_soc
        current_mode = self.current_storage_mode

        # Envoy offline — do NOT issue commands when blind.
        # Hold whatever state the system is in until we can read it again.
        if not self.envoy_available:
            _LOGGER.warning(
                "Envoy unavailable (SOC=%s, mode=%s) — holding current state",
                soc, current_mode,
            )
            # v4.3.0 D1 cosmetic fix: keep in-memory _arbitrage_active in sync
            # with the returned dict so the sensor doesn't show "arbitrage_active=False"
            # while the in-memory state still says True. When envoy comes back the
            # next decision cycle will re-evaluate and re-set as needed.
            self._arbitrage_active = False
            self._arbitrage_phase = ARBITRAGE_PHASE_NA
            # v4.5.0.2 fix: also sync _last_reason. Pre-fix, this early-return
            # path mutated _arbitrage_phase + _arbitrage_active without touching
            # _last_reason, leaving the sensor's `reason` attribute holding a
            # stale CHARGE/HOLD message from a prior tick while phase/active
            # showed "n/a"/False. Looked like a self-contradicting state to the
            # user. Now: reason matches phase. Discovered live during v4.5.0
            # post-deploy validation when an Envoy blip co-occurred with the
            # battery breaker tripping.
            self._last_reason = "Envoy unavailable — holding (no commands issued)"
            self._last_mode = current_mode or "unknown"
            return {
                "mode": current_mode or "unknown",
                "reason": "Envoy unavailable — holding (no commands issued)",
                "actions": [],
                "soc": soc,
                "solar_production": self.solar_production,
                "net_power": self.net_power,
                "battery_power": self.battery_power,
                "solar_day_class": self.classify_solar_day(),
                "tomorrow_solar_class": "unknown",
                "envoy_available": False,
                "season": season,
                "arbitrage_active": False,
                "arbitrage_enabled": self._arbitrage_enabled,
                "arbitrage_phase": ARBITRAGE_PHASE_NA,
                "target_day_class": "unknown",
                "reserve_soc": self.reserve_soc,
            }

        # ── v4.5.0 D5: precedence chain — DO NOT REORDER ──────────────
        # The arbitrage phase machine (in the off_peak branch below) is
        # gated on grid_connected + no-storm + envoy_available. These
        # short-circuits MUST run before the off_peak branch:
        #   1. envoy_unavailable → hold state, no commands
        #   2. grid_disconnected → BACKUP mode
        #   3. storm forecast    → BACKUP / pre-charging
        #   4. peak / mid_peak   → existing discharge logic
        #   5. off_peak          → arbitrage phase OR drain-target fallback
        # Reordering will silently break v4.5.0 D5 acceptance: "storm
        # path wins over arbitrage HOLD" / "grid-disconnect skips
        # arbitrage entirely" / etc.
        # ──────────────────────────────────────────────────────────────

        # Grid disconnected — emergency backup
        if not self.grid_connected:
            return self._result(
                BATTERY_MODE_BACKUP,
                "Grid disconnected — backup mode",
                current_mode,
                season=season,
            )

        # Storm forecast — pre-charge and prepare for outage
        if self.has_storm_forecast():
            if soc is not None and soc < DEFAULT_STORM_CHARGE_THRESHOLD:
                return self._result(
                    BATTERY_MODE_SELF_CONSUMPTION,
                    f"Storm forecast — pre-charging (SOC {soc}%)",
                    current_mode,
                    charge_from_grid=True,
                    reserve_level=self.reserve_soc,
                    season=season,
                )
            # Already charged enough — switch to backup to hold charge
            return self._result(
                BATTERY_MODE_BACKUP,
                f"Storm forecast — holding charge (SOC {soc}%)",
                current_mode,
                season=season,
            )

        # Peak period — battery covers home load, solar exports
        # Strategy 3 from codicil: self_consumption + low reserve
        if tou_period == "peak":
            if soc is not None and soc > self.reserve_soc:
                return self._result(
                    BATTERY_MODE_SELF_CONSUMPTION,
                    "Peak — battery covers load, solar exports",
                    current_mode,
                    reserve_level=self.reserve_soc,
                    season=season,
                )
            return self._result(
                BATTERY_MODE_SELF_CONSUMPTION,
                f"Peak but SOC low ({soc}%) — minimal discharge",
                current_mode,
                reserve_level=max(int(soc or 0) - 5, self.reserve_soc),
                season=season,
            )

        # Mid-peak strategy depends on season:
        # - Summer: hold battery for upcoming peak (mid-peak is a bridge)
        # - Shoulder/Winter: mid-peak IS the highest-rate period (no peak exists).
        #   Discharge battery to cover load; solar exports at $0.086/kWh.
        if tou_period == "mid_peak":
            if season == "summer":
                # Summer mid-peak: hold charge for upcoming peak
                hold_reserve = int(soc) if soc is not None else 100
                return self._result(
                    BATTERY_MODE_SELF_CONSUMPTION,
                    "Mid-peak (summer) — holding charge for peak",
                    current_mode,
                    reserve_level=hold_reserve,
                    season=season,
                )
            # Shoulder/Winter mid-peak: discharge — this is the best rate window
            if soc is not None and soc > self.reserve_soc:
                return self._result(
                    BATTERY_MODE_SELF_CONSUMPTION,
                    f"Mid-peak ({season}) — discharging, best rate window",
                    current_mode,
                    reserve_level=self.reserve_soc,
                    season=season,
                )
            return self._result(
                BATTERY_MODE_SELF_CONSUMPTION,
                f"Mid-peak ({season}) but SOC low ({soc}%) — minimal discharge",
                current_mode,
                reserve_level=max(int(soc or 0) - 5, self.reserve_soc),
                season=season,
            )

        # Off-peak — v4.5.0 D1 phased arbitrage path OR v4.3.4 drain-target path
        # Guard: only run off-peak logic for recognized off_peak period
        if tou_period != "off_peak":
            # Unrecognized period — treat as off-peak with conservative behavior
            _LOGGER.warning("Unexpected TOU period '%s' — treating as off-peak", tou_period)
        tomorrow_class = self.classify_tomorrow_solar()
        target_day_class = self._classify_target_day(now)

        # v4.5.0 D1: arbitrage path overrides drain-target path when the
        # gate is open (arbitrage_enabled AND target_day in poor/very_poor,
        # extended via D3 multi_day if enabled). The new path is a four-
        # phase state machine; the drain-target path below is byte-for-
        # byte v4.3.4 behavior preserved for the single-user fallback
        # case (per state matrix invariant #1).
        if self._gate_is_open(now, target_day_class):
            return self._get_arbitrage_decision(
                soc=soc,
                now=now,
                target_day_class=target_day_class,
                tomorrow_class=tomorrow_class,
                current_mode=current_mode,
                season=season,
            )

        # ----- Drain-target fallback path (unchanged from v4.3.4) -----
        # Used when arbitrage_enabled=False OR target_day_class ∉
        # (poor, very_poor). Per state matrix invariants 1 + 2.
        # v4.5.0 also clears the in-memory arbitrage flag so HOLD residue
        # doesn't carry over after the gate closes.
        self._arbitrage_active = False
        # Keep _arbitrage_phase = "n/a" via _result() default.

        drain_class_for_target = tomorrow_class
        # v4.5.0 D3: when multi_day_horizon enabled AND arbitrage is OFF,
        # take the more conservative (higher) drain target between D+1
        # and D+2. This widens the "hold charge for tomorrow's bad day"
        # behavior across two days. When arbitrage is ON we never reach
        # this branch — arbitrage path wins.
        if self._multi_day_horizon_enabled:
            d2_class = self.classify_solar_day_n(2)
            d1_target = self._get_offpeak_drain_target(tomorrow_class)
            d2_target = self._get_offpeak_drain_target(d2_class)
            if d2_target > d1_target:
                drain_class_for_target = d2_class

        drain_target = self._get_offpeak_drain_target(drain_class_for_target)

        if soc is not None and soc > drain_target:
            # Above target — drain stored solar (free energy)
            return self._result(
                BATTERY_MODE_SELF_CONSUMPTION,
                f"Off-peak drain — SOC {soc}% > target {drain_target}% (tomorrow {tomorrow_class})",
                current_mode,
                reserve_level=drain_target,
                season=season,
                tomorrow_solar_class=tomorrow_class,
                target_day_class=target_day_class,
            )

        # At/below target — hold and import cheap grid
        hold_reserve = int(soc) if soc is not None else drain_target
        return self._result(
            BATTERY_MODE_SELF_CONSUMPTION,
            f"Off-peak hold — SOC {soc}% <= target {drain_target}% (tomorrow {tomorrow_class})",
            current_mode,
            reserve_level=hold_reserve,
            season=season,
            tomorrow_solar_class=tomorrow_class,
            target_day_class=target_day_class,
        )

    def _result(
        self,
        mode: str,
        reason: str,
        current_mode: str | None,
        charge_from_grid: bool = False,
        reserve_level: int | None = None,
        season: str | None = None,
        tomorrow_solar_class: str | None = None,
        arbitrage_active: bool = False,
        arbitrage_phase: str | None = None,
        target_day_class: str | None = None,
    ) -> dict[str, Any]:
        """Build battery decision result with actions.

        Uses reserve level as the primary control lever per Enphase codicil.
        Mode changes happen first, then reserve adjustment, then charge_from_grid.
        60-90s buffer built into decision cycle (5min interval) accommodates Enphase latency.
        """
        actions: list[dict[str, Any]] = []

        # 1. Storage mode — only change if different from current
        if current_mode is not None and mode != current_mode:
            actions.append({
                "service": "select.select_option",
                "target": self._get_entity("storage_mode", DEFAULT_STORAGE_MODE_ENTITY),
                "data": {"option": mode},
            })

        # 2. Reserve level — primary control lever
        if reserve_level is not None:
            current_reserve = self._get_state_float(
                self._get_entity("reserve_soc_number", DEFAULT_RESERVE_SOC_ENTITY)
            )
            target_reserve = max(0, min(100, reserve_level))
            if current_reserve is None or abs(current_reserve - target_reserve) >= 2:
                actions.append({
                    "service": "number.set_value",
                    "target": self._get_entity(
                        "reserve_soc_number", DEFAULT_RESERVE_SOC_ENTITY
                    ),
                    "data": {"value": target_reserve},
                })

        # 3. Charge from grid control
        if charge_from_grid:
            current_cfg = self._get_state_bool(
                self._get_entity("charge_from_grid", DEFAULT_CHARGE_FROM_GRID_ENTITY)
            )
            if current_cfg is not True:
                actions.append({
                    "service": "switch.turn_on",
                    "target": self._get_entity(
                        "charge_from_grid", DEFAULT_CHARGE_FROM_GRID_ENTITY
                    ),
                    "data": {},
                })
        else:
            current_cfg = self._get_state_bool(
                self._get_entity("charge_from_grid", DEFAULT_CHARGE_FROM_GRID_ENTITY)
            )
            if current_cfg is True:
                actions.append({
                    "service": "switch.turn_off",
                    "target": self._get_entity(
                        "charge_from_grid", DEFAULT_CHARGE_FROM_GRID_ENTITY
                    ),
                    "data": {},
                })

        self._last_mode = mode
        self._last_reason = reason
        # v4.5.0 D1: keep self._arbitrage_phase synced with the dict.
        # Defaults to "n/a" for any non-arbitrage code path (peak/mid_peak/
        # storm/disconnect), matching state matrix invariants 4 + 6.
        phase = arbitrage_phase if arbitrage_phase is not None else ARBITRAGE_PHASE_NA
        if mode != BATTERY_MODE_BACKUP and arbitrage_phase is None:
            # Peak/mid_peak rows of the matrix: arbitrage doesn't apply.
            # Use DISCHARGE label for sensor clarity when the existing
            # peak/mid_peak branches discharge the battery.
            if season is not None and ("Peak" in (reason or "")
                                        or "mid_peak" in (reason or "").lower()
                                        or "Mid-peak" in (reason or "")):
                phase = ARBITRAGE_PHASE_DISCHARGE
        self._arbitrage_phase = phase

        return {
            "mode": mode,
            "reason": reason,
            "actions": actions,
            "soc": self.battery_soc,
            "solar_production": self.solar_production,
            "net_power": self.net_power,
            "solar_day_class": self.classify_solar_day(),
            "tomorrow_solar_class": tomorrow_solar_class,
            "envoy_available": True,
            "season": season,
            "arbitrage_active": arbitrage_active,
            "arbitrage_enabled": self._arbitrage_enabled,
            "arbitrage_phase": phase,
            "target_day_class": target_day_class,
        }

    def _threshold_position(self, soc: float | None, tomorrow_class: str) -> str:
        """v4.3.0 D5 / v4.5.0 D1: narrate where SOC sits relative to thresholds.

        Updated for the phased model: arbitrage_trigger no longer exists
        as a separate gate — the gate is forecast-class only. Position
        commentary is now relative to peak_buffer_target + drain_target.
        """
        if soc is None:
            return "SOC unknown — Envoy not reporting"
        s = float(soc)
        if s <= self.reserve_soc:
            return (
                f"SOC={s:.0f}% at/below reserve_soc ({self.reserve_soc}%) — "
                f"safety floor reached, no further discharge"
            )
        if self._arbitrage_enabled and s >= self._peak_buffer_target:
            return (
                f"SOC={s:.0f}% at/above peak_buffer_target "
                f"({self._peak_buffer_target}%) — buffer locked when arbitrage gate is open"
            )
        drain = self._drain_targets.get(tomorrow_class, self._drain_targets.get("unknown", 40))
        if s <= drain:
            return (
                f"SOC={s:.0f}% at/below drain_target ({drain}%, tomorrow={tomorrow_class}) — "
                f"will hold at SOC during off-peak (when arbitrage gate closed)"
            )
        return (
            f"SOC={s:.0f}% above drain_target ({drain}%, tomorrow={tomorrow_class}) — "
            f"will drain to target during off-peak (when arbitrage gate closed)"
        )

    def _next_action_estimate(self, soc: float | None, tomorrow_class: str) -> str:
        """v4.3.0 D5 / v4.5.0 D1: short narration of expected next-cycle action.

        Phased model: estimate from current arbitrage_phase + gate state
        rather than the v4.3.4 SOC-trigger logic.
        """
        if soc is None:
            return "no estimate — Envoy unavailable"
        phase = self._arbitrage_phase
        if phase == ARBITRAGE_PHASE_CHARGE:
            return (
                f"grid charging to peak_buffer_target ({self._peak_buffer_target}%)"
            )
        if phase == ARBITRAGE_PHASE_HOLD:
            return (
                f"holding buffer at {self._peak_buffer_target}% until next high-rate window"
            )
        if phase == ARBITRAGE_PHASE_WAIT:
            if self._arbitrage_chunk_completed:
                return "arbitrage chunk completed — battery serves loads naturally"
            return (
                f"waiting for charge window (lead_time={self._arbitrage_charge_lead_time_min}m)"
            )
        if phase == ARBITRAGE_PHASE_DISCHARGE:
            return "discharging during high-rate window"
        # Fallback (gate closed or n/a): drain-target narration
        drain = self._drain_targets.get(tomorrow_class, self._drain_targets.get("unknown", 40))
        if float(soc) > drain:
            return f"drain to {drain}% during off-peak (tomorrow={tomorrow_class})"
        return "hold at current SOC"

    def get_status(self) -> dict[str, Any]:
        """Return current battery strategy status for sensor.

        v4.3.0 D3: includes threshold_warning when ladder is violated, plus
        the raw threshold values (arbitrage_trigger/target, drain_targets).
        v4.3.0 D5: includes threshold_position + next_action_estimate strings.
        v4.5.0 D1/D6: phased state machine attributes (arbitrage_phase,
        arbitrage_chunk_completed, peak_buffer_target, target_day_class,
        next_high_rate_transition, charge_window_opens_at).
        """
        from .energy_const import validate_threshold_ladder
        from homeassistant.util import dt as dt_util
        warning = validate_threshold_ladder(
            self.reserve_soc,
            self._drain_targets,
            arbitrage_trigger=None,  # v4.5.0: trigger removed (forecast-class gate)
            peak_buffer_target=self._peak_buffer_target,
        )
        soc = self.battery_soc
        tomorrow_class = self.classify_tomorrow_solar()
        now = dt_util.now()
        target_day_class = self._classify_target_day(now)

        # v4.5.0 D6: timing attributes
        next_transition_iso: str | None = None
        next_transition_period: str | None = None
        charge_window_opens_at_iso: str | None = None
        if self._tou is not None:
            nxt = self._tou.get_next_high_rate_transition(now)
            if nxt is not None:
                target_dt, period = nxt
                next_transition_iso = target_dt.isoformat()
                next_transition_period = period
                opens = target_dt - timedelta(
                    minutes=self._arbitrage_charge_lead_time_min
                )
                charge_window_opens_at_iso = opens.isoformat()

        # v4.5.0 D6: forecast outlook for cross-day reasoning
        d2_class = (
            self.classify_solar_day_n(2)
            if self._multi_day_horizon_enabled
            else "unknown"
        )

        return {
            "mode": self._last_mode or self.current_storage_mode or "unknown",
            "reason": self._last_reason or "initializing",
            "soc": soc,
            "solar_production": self.solar_production,
            "net_power": self.net_power,
            "battery_power": self.battery_power,
            "grid_connected": self.grid_connected,
            "envoy_available": self.envoy_available,
            "solar_day_class": self.classify_solar_day(),
            "tomorrow_solar_class": tomorrow_class,
            "target_day_class": target_day_class,
            "storm_forecast": self.has_storm_forecast(),
            "reserve_soc": self.reserve_soc,
            "arbitrage_active": self._arbitrage_active,
            "arbitrage_enabled": self._arbitrage_enabled,
            # v4.5.0 D2: rename arbitrage_target → peak_buffer_target.
            # Both keys present during migration window for any user
            # automations that read the old name. D6/v4.6.0 removes the
            # alias.
            "arbitrage_target": self._peak_buffer_target,
            "peak_buffer_target": self._peak_buffer_target,
            "arbitrage_phase": self._arbitrage_phase,
            "arbitrage_chunk_completed": self._arbitrage_chunk_completed,
            "arbitrage_charge_lead_time_min": self._arbitrage_charge_lead_time_min,
            # v4.5.0.2 grid-import guard surfaces
            "arbitrage_grid_import_guard_kw": self._arbitrage_grid_import_guard_kw,
            "arbitrage_guard_aborted_at": self._arbitrage_guard_aborted_at,
            "arbitrage_guard_aborted_kw": self._arbitrage_guard_aborted_kw,
            "next_high_rate_transition": next_transition_iso,
            "next_high_rate_transition_period": next_transition_period,
            "charge_window_opens_at": charge_window_opens_at_iso,
            "forecast_outlook": {
                "d1_class": tomorrow_class,
                "d1_kwh": self.solcast_tomorrow,
                "d2_class": d2_class,
                "d2_kwh": self.solcast_day_3,
                "horizon_enabled": self._multi_day_horizon_enabled,
            },
            "drain_targets": dict(self._drain_targets),
            "threshold_warning": warning,
            "threshold_position": self._threshold_position(soc, tomorrow_class),
            "next_action_estimate": self._next_action_estimate(soc, tomorrow_class),
        }
