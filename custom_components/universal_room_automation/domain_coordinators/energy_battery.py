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
    ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK,
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
# Cycle EC/HC reboot pickup: peak-buffer attainability branch. Distinct
# from CHARGE so the sensor + downstream consumers can tell "forecast-class
# arbitrage CHARGE" apart from "good-day catch-up because solar got eaten
# by house/EV loads". Per operator decision 2026-06-12, EVSE coordination
# is OUT of scope for v1 — `attain` must NOT pause EVSE (see energy.py
# arbitrage_charging gate, which stays `== CHARGE` only).
ARBITRAGE_PHASE_ATTAIN = "attain"

# Cycle EC/HC reboot pickup: trailing-window length (decision cycles) used
# to smooth the observed net charge rate for the attainability projection.
# K=3 at 5-min cadence = 15 minutes of smoothing — long enough to filter
# tick-level noise, short enough that an EV finishing or a cloud lifting
# is reflected in the projection within ~2 cycles.
ATTAIN_RATE_WINDOW_TICKS = 3

# Fix-up pass (Reviews A-CRIT-1 / A-HIGH-2 / B-HIGH-1/3 / C-HIGH-1):
# attainability redesign — latch, solar-informed entry, floor, peak handoff.
#
# SOLAR_CAPTURE_FACTOR: fraction of Solcast remaining-day kWh forecast we
# expect to actually capture into the battery before the high-rate
# boundary. Conservative constant (operator-ratified 2026-06-12) — captures
# uncertainty in how much remaining-day forecast lands in the pre-boundary
# window vs. after, plus how much is consumed by house/EV loads vs. stored.
# Unavailable/stale Solcast → treat surplus as 0 (fail toward charging —
# buffer matters more than a wasted cheap charge).
SOLAR_CAPTURE_FACTOR = 0.5
# Minimum minutes-to-boundary required to ENTER attain. Below this we
# decline (charge_from_grid actuation lag ~35 min per addendum — entering
# with <30m can't deliver meaningful charge before the boundary). Latched
# attain CONTINUES below this floor; only ENTRY is gated.
ATTAIN_MIN_REMAINING_MIN = 30
# Lead minutes before a PEAK boundary at which a latched attain commands
# its turn-off / handoff so the Enphase cloud write lands before peak.
# Operator-ratified ("as long as turn off can cycle in 15m before peak").
ATTAIN_PEAK_HANDOFF_LEAD_MIN = 15

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
        # Consecutive guard-trip counter — only lock the chunk after the
        # cap is exceeded on N consecutive CHARGE ticks, so a single
        # battery-CT-lag tick at charge entry can't kill the whole chunk.
        self._arbitrage_guard_consecutive_trips: int = 0

        # v4.5.0 D8 hookup. May be None when constructed from a test
        # harness or before the EnergyCoordinator finishes wiring.
        self._tou = tou_engine

        # Cycle EC/HC reboot pickup — D1 attainability rate observation.
        # Trailing window of (timestamp, soc) samples used to compute the
        # observed net charge rate (%/hour). Capped at ATTAIN_RATE_WINDOW_TICKS
        # + 1 (need K samples to compute K deltas). Empty on cold boot →
        # predicate defers one cycle so we don't trigger on a synthetic rate.
        self._attain_soc_history: list[tuple[datetime, float]] = []

        # Fix-up pass 3 (Pass-2 reviewers P2A-CRIT-1 / P2B-CRIT-1 /
        # C2-CRIT-1): tri-state attain phase. {"inactive", "charging",
        # "holding"}. "holding" is a PERSISTENT state (re-emitted every
        # tick) — not a one-shot — so the buffer is held at peak_buffer_
        # target through boundary handoff. The OLD one-tick HOLD emission
        # let the drain-target fallback release the buffer pre-boundary
        # (A-CRIT-1 defect 3 / P2A-CRIT-1 / C2-CRIT-1 / P2B-CRIT-1).
        # Reboot recovery is now derived from observable hardware state
        # (see _adopt_attain_state_from_hardware) — RAM-only latch
        # behavior caused B-HIGH-3 / P2A-CRIT-2 / P2B-CRIT-2 / C2-CRIT-2.
        self._attain_state: str = "inactive"
        # First-decision-tick reboot adoption guard — clears once we have
        # run reboot recovery exactly once.
        self._attain_reboot_recovered: bool = False
        # M5: one-shot operator/Enphase-drift log gate — fire INFO once
        # per chunk when cfg is observed OFF while we are charging.
        self._attain_drift_logged: bool = False
        # Tick counter for M5: only enforce the cfg-OFF drift policy
        # after our own command has had a chance to land (cfg actuation
        # has measured ~35-min cloud lag). Counts charging ticks; reset
        # on any non-charging transition.
        self._attain_charging_ticks: int = 0

        # v4.5.0 D3: multi-day Solcast lookback toggle + entity ID.
        # (Property `_attain_active` defined later as a tri-state
        # compatibility alias — tests / external readers that set
        # `_attain_active = True` historically map to `charging`.)
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

    def _effective_import_kw(self) -> tuple[float, float, float] | None:
        """Single-snapshot non-battery grid import (house + EV draw), in kW.

        Returns ``(effective_kw, net_kw, battery_charge_kw)`` from ONE read
        of each sensor, or ``None`` when ``net_power_w`` is unavailable.
        This is the single source of truth for both the guard predicate and
        its diagnostic record — computing it once and threading the result
        means the value the guard compared is exactly the value recorded
        (no second-read divergence between decision and diagnostic).

        ``net_power_w`` is already unit-normalized via the v4.5.0 sweep (Bug
        Class #30). The battery's own charge power is subtracted before
        comparison: the guard exists to keep house+EV draw from tripping the
        panel breaker, NOT to constrain battery charge-from-grid itself.
        Without the subtraction, arbitrage CHARGE drives ``net_power`` above
        the cap and self-aborts (observed live: net 18.6 kW with battery
        charging 15.8 kW and non-battery draw flat ~2.8 kW tripped 12 kW).

        Sign convention (see ``battery_power_w`` docstring): positive =
        charging, negative = discharging. We subtract only when charging
        (``max(0.0, battery_power_w)``) so a discharging battery cannot
        *raise* the effective import.

        Fail-safe: ``battery_power_w`` None (sensor briefly unavailable) →
        treat battery charge as 0 (do NOT subtract) → effective collapses to
        total ``net_power_w``. A sensor dropout must never *uncap* the guard.
        """
        net_w = self.net_power_w
        if net_w is None:
            return None
        batt_w = self.battery_power_w
        batt_charge_w = max(0.0, batt_w) if batt_w is not None else 0.0
        effective_w = net_w - batt_charge_w
        return (effective_w / 1000.0, net_w / 1000.0, batt_charge_w / 1000.0)

    def _grid_import_guard_triggered(self) -> bool:
        """True iff non-battery grid import exceeds the configured guard.

        Thin predicate over :meth:`_effective_import_kw`. A None reading
        (envoy unavailable) is not a trip — the envoy-unavailable branch
        upstream handles that case. Threshold default 12 kW (60A breaker
        sized); configurable via ``arbitrage_grid_import_guard_kw``.
        """
        snap = self._effective_import_kw()
        if snap is None:
            return False
        return snap[0] > self._arbitrage_grid_import_guard_kw

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
            # Defensive guard: if non-battery grid import (house + EV draw)
            # exceeds the configured cap, abort the chunk. Protects against
            # undersized breakers tripping under hardware peak draw the
            # strategy can't directly throttle (Enphase charge_from_grid is
            # binary). v4.5.1 will replace this with proper rate control.
            #
            # ONE snapshot drives both the comparison and the diagnostic, so
            # the recorded kW is exactly what the guard compared. The chunk
            # locks only after the cap is exceeded on N consecutive ticks:
            # at CHARGE entry battery_power_w lags net_power_w by one Envoy
            # poll, so a single tick can read full inrush on net while the
            # battery still reads ~0 — a one-shot lock would lose the whole
            # chunk to sensor lag. A real house+EV overdraw still locks (one
            # extra ~30s tick is within the physical breaker margin).
            snap = self._effective_import_kw()
            if snap is not None and snap[0] > self._arbitrage_grid_import_guard_kw:
                effective_kw, net_kw, batt_charge_kw = snap
                self._arbitrage_guard_consecutive_trips += 1
                if (
                    self._arbitrage_guard_consecutive_trips
                    < ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK
                ):
                    _LOGGER.info(
                        "Arbitrage grid-import guard trip %d/%d "
                        "(effective=%.1f kW > %.1f kW cap; net=%.1f, "
                        "battery_charge=%.1f) — deferring chunk lock one tick "
                        "to absorb battery-CT lag at charge entry",
                        self._arbitrage_guard_consecutive_trips,
                        ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK,
                        effective_kw,
                        self._arbitrage_grid_import_guard_kw,
                        net_kw,
                        batt_charge_kw,
                    )
                    return ARBITRAGE_PHASE_CHARGE
                self._arbitrage_chunk_completed = True
                from homeassistant.util import dt as dt_util
                self._arbitrage_guard_aborted_at = dt_util.now().isoformat()
                self._arbitrage_guard_aborted_kw = effective_kw
                _LOGGER.warning(
                    "Arbitrage CHARGE aborted by grid-import guard: "
                    "effective_import=%.1f kW (net=%.1f kW, battery_charge=%.1f kW) "
                    "exceeds threshold=%.1f kW on %d consecutive ticks. Chunk "
                    "locked; will retry next off-peak chunk. (Likely panel "
                    "breaker risk from house+EV draw — consider rate control.)",
                    effective_kw,
                    net_kw,
                    batt_charge_kw,
                    self._arbitrage_grid_import_guard_kw,
                    self._arbitrage_guard_consecutive_trips,
                )
                return ARBITRAGE_PHASE_WAIT
            # Under the cap (or net unavailable) → reset the streak so an
            # earlier transient trip can't carry over into a later window.
            self._arbitrage_guard_consecutive_trips = 0
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

    # ── Tri-state attain phase compatibility shim ──────────────────────────
    # Historically callers/tests poked `strat._attain_active = True` to
    # force the latched path. Tri-state preserves the historical semantics:
    # reads non-inactive as True; writes True → "charging"; writes False →
    # "inactive".
    @property
    def _attain_active(self) -> bool:  # noqa: D401 — compat alias
        return self._attain_state != "inactive"

    @_attain_active.setter
    def _attain_active(self, value: bool) -> None:
        if value:
            # Default to "charging" when callers/tests assert True.
            if self._attain_state == "inactive":
                self._attain_state = "charging"
        else:
            self._attain_state = "inactive"
            self._attain_drift_logged = False

    # ── Cycle EC/HC reboot pickup — D1 attainability branch ────────────────
    def _record_attain_sample(self, now: datetime, soc: float | None) -> None:
        """Append (now, soc) to the trailing window; trim to K+1 samples.

        Called once per off-peak decision tick (only when attainability is
        eligible) to feed the projection. None SOC samples are skipped —
        an Envoy blip must not poison the rate estimate.
        """
        if soc is None:
            return
        try:
            soc_f = float(soc)
        except (TypeError, ValueError):
            return
        self._attain_soc_history.append((now, soc_f))
        # K samples + 1 = K deltas. Trim from the head.
        max_len = ATTAIN_RATE_WINDOW_TICKS + 1
        if len(self._attain_soc_history) > max_len:
            self._attain_soc_history = self._attain_soc_history[-max_len:]

    def _observed_net_charge_rate_per_hour(self) -> float | None:
        """Smoothed net charge rate in %/hour over the trailing K-tick window.

        Returns None when fewer than 2 samples are available (cold boot)
        — caller treats None as "defer one cycle, do not trigger". This is
        an end-to-end smoothing over the window: (soc_last - soc_first) /
        elapsed_hours. Equivalent to averaging per-tick deltas, but
        immune to single-tick zero-elapsed degeneracy when timestamps
        collide in tests.
        """
        hist = self._attain_soc_history
        if len(hist) < 2:
            return None
        t0, s0 = hist[0]
        t1, s1 = hist[-1]
        elapsed_s = (t1 - t0).total_seconds()
        if elapsed_s <= 0:
            return None
        return (s1 - s0) / (elapsed_s / 3600.0)

    def _minutes_to_high_rate_boundary(self, now: datetime) -> int | None:
        """Minutes until the next high-rate TOU transition; None if unknown."""
        if self._tou is None:
            return None
        nxt = self._tou.get_next_high_rate_transition(now)
        if nxt is None:
            return None
        target_dt, _ = nxt
        delta_s = (target_dt - now).total_seconds()
        if delta_s <= 0:
            return 0
        return int(delta_s // 60)

    # Fix-up pass: capacity helper used by the solar-informed projection.
    # Same shape as EnergyCoordinator._get_battery_capacity_kwh but lives on
    # the strategy so the predicate has no coordinator backref. Returns None
    # when capacity is unknown — caller treats expected solar surplus as 0
    # in that case (fail toward charging).
    def _battery_capacity_kwh(self) -> float | None:
        """Best-effort battery capacity in kWh; None if unknown."""
        eid = self._get_entity("battery_capacity")
        if eid is None:
            return None
        state = self.hass.states.get(eid)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            raw = float(state.state)
        except (ValueError, TypeError):
            return None
        uom = state.attributes.get("unit_of_measurement", "")
        if uom in ("kWh", "kwh"):
            return raw
        return raw / 1000.0  # Wh → kWh

    def _expected_solar_surplus_pct(
        self, now: datetime, mins_to_boundary: int | None,
    ) -> float:
        """M4 — time-sliced solar-informed entry term.

        Fraction of the Solcast forecast (in %SOC) we expect to capture
        into the battery before the high-rate boundary. The remaining-day
        forecast is pro-rated by the OVERLAP between the [now, boundary]
        window and the remaining daylight/production window so that
        production landing AFTER the boundary cannot inflate the term
        (C2-MED-1 / C2-HIGH-1).

        Winter pre-dawn case (window crosses midnight — e.g. 23:00 →
        05:00): "remaining today" ≈ 0 overnight, so use TOMORROW's
        forecast sliced to [tomorrow_sunrise, boundary]. If neither
        forecast is available → 0 (fail toward charging).

        Conservative bias by design: SOLAR_CAPTURE_FACTOR=0.5 captures
        losses, non-battery load, and skew. We'd rather fire ATTAIN on a
        borderline morning than skip it.
        """
        if mins_to_boundary is None or mins_to_boundary <= 0:
            return 0.0
        capacity_kwh = self._battery_capacity_kwh()
        if capacity_kwh is None or capacity_kwh <= 0:
            return 0.0
        boundary_dt = now + timedelta(minutes=mins_to_boundary)

        # Daylight envelope — sunrise/sunset for the operative day.
        try:
            sunrise_today, sunset_today = self._daylight_bounds(now)
        except Exception:  # noqa: BLE001
            sunrise_today, sunset_today = (None, None)

        # Branch by whether ANY of [now, boundary] lies in remaining
        # daylight today vs requires tomorrow's forecast.
        # When boundary is BEFORE today's sunrise (winter pre-dawn window
        # closing at 05:00 with sunrise ~07:00), remaining-today is 0 and
        # we must walk to tomorrow's forecast sliced to its own sunrise.
        if (
            sunset_today is not None
            and now < sunset_today
            and boundary_dt > now
        ):
            # Some overlap with today.
            window_start = max(now, sunrise_today) if sunrise_today else now
            window_end = min(boundary_dt, sunset_today)
            overlap_h = max(0.0, (window_end - window_start).total_seconds() / 3600.0)
            remaining_h = max(
                0.001,
                (sunset_today - max(now, sunrise_today or now)).total_seconds() / 3600.0,
            ) if sunrise_today else max(
                0.001, (sunset_today - now).total_seconds() / 3600.0,
            )
            remaining_kwh = self.solcast_remaining
            if remaining_kwh is None or remaining_kwh <= 0:
                return 0.0
            fraction = min(1.0, overlap_h / remaining_h) if remaining_h > 0 else 0.0
            sliced_kwh = remaining_kwh * fraction
            expected_kwh_to_battery = sliced_kwh * SOLAR_CAPTURE_FACTOR
            return (expected_kwh_to_battery / capacity_kwh) * 100.0

        # No today-overlap: winter pre-dawn case → tomorrow forecast,
        # sliced to [tomorrow_sunrise, boundary].
        try:
            tomorrow_anchor = now + timedelta(days=1)
            sunrise_tom, sunset_tom = self._daylight_bounds(tomorrow_anchor)
        except Exception:  # noqa: BLE001
            sunrise_tom, sunset_tom = (None, None)
        tomorrow_kwh = self.solcast_tomorrow
        if (
            tomorrow_kwh is None
            or tomorrow_kwh <= 0
            or sunrise_tom is None
            or sunset_tom is None
            or boundary_dt <= sunrise_tom
        ):
            return 0.0
        window_start = sunrise_tom
        window_end = min(boundary_dt, sunset_tom)
        overlap_h = max(0.0, (window_end - window_start).total_seconds() / 3600.0)
        daylight_h = max(
            0.001, (sunset_tom - sunrise_tom).total_seconds() / 3600.0,
        )
        fraction = min(1.0, overlap_h / daylight_h)
        sliced_kwh = tomorrow_kwh * fraction
        expected_kwh_to_battery = sliced_kwh * SOLAR_CAPTURE_FACTOR
        return (expected_kwh_to_battery / capacity_kwh) * 100.0

    def _daylight_bounds(
        self, anchor: datetime,
    ) -> tuple[datetime | None, datetime | None]:
        """Return (sunrise, sunset) on the same local date as ``anchor``.

        Best-effort; falls back to a conservative 07:00 / 19:00 envelope
        when the HA sun integration is unavailable in the test sandbox.
        """
        try:
            sun_state = self.hass.states.get("sun.sun") if self.hass else None
        except Exception:  # noqa: BLE001
            sun_state = None
        sunrise_iso = None
        sunset_iso = None
        if sun_state is not None:
            attrs = getattr(sun_state, "attributes", None) or {}
            sunrise_iso = attrs.get("next_rising") or attrs.get("next_dawn")
            sunset_iso = attrs.get("next_setting") or attrs.get("next_dusk")
        if sunrise_iso:
            try:
                sr = datetime.fromisoformat(str(sunrise_iso).replace("Z", "+00:00"))
                # Project onto anchor's date so we have same-day bounds.
                sunrise = anchor.replace(
                    hour=sr.hour, minute=sr.minute, second=0, microsecond=0,
                )
            except Exception:  # noqa: BLE001
                sunrise = anchor.replace(hour=7, minute=0, second=0, microsecond=0)
        else:
            sunrise = anchor.replace(hour=7, minute=0, second=0, microsecond=0)
        if sunset_iso:
            try:
                ss = datetime.fromisoformat(str(sunset_iso).replace("Z", "+00:00"))
                sunset = anchor.replace(
                    hour=ss.hour, minute=ss.minute, second=0, microsecond=0,
                )
            except Exception:  # noqa: BLE001
                sunset = anchor.replace(hour=19, minute=0, second=0, microsecond=0)
        else:
            sunset = anchor.replace(hour=19, minute=0, second=0, microsecond=0)
        return (sunrise, sunset)

    def _attain_target_boundary(
        self, now: datetime, tou_period: str,
    ) -> tuple[datetime | None, str | None, int | None]:
        """Return (boundary_dt, period_name, minutes) for the attain target.

        D1b mid-peak continuation: when in mid_peak, target re-points to the
        PEAK boundary so attain can continue covering peak.  In off_peak we
        target the next high-rate transition (mid_peak or peak — whichever
        comes first).
        """
        if self._tou is None:
            return (None, None, None)
        if tou_period == "mid_peak":
            # Walk forward looking for the next "peak" hour. Reuse hour-
            # granular scan from energy_tou's pattern.
            cursor = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            end = cursor + timedelta(hours=24)
            while cursor <= end:
                try:
                    if self._tou.get_current_period(cursor) == "peak":
                        delta_s = (cursor - now).total_seconds()
                        return (cursor, "peak", int(delta_s // 60) if delta_s > 0 else 0)
                except Exception:  # noqa: BLE001
                    return (None, None, None)
                cursor += timedelta(hours=1)
            return (None, None, None)
        # Default: next high-rate transition (off_peak path)
        nxt = self._tou.get_next_high_rate_transition(now)
        if nxt is None:
            return (None, None, None)
        target_dt, period_name = nxt
        delta_s = (target_dt - now).total_seconds()
        mins = int(delta_s // 60) if delta_s > 0 else 0
        return (target_dt, period_name, mins)

    def _attain_target_period_at_or_above_current(
        self, now: datetime, tou_period: str, target_period: str | None,
    ) -> bool:
        """M3 — generalized boundary handoff lead trigger.

        Returns True when the period BEGINNING at the attain target
        boundary has a rate >= the current period's rate. Every boundary
        attain ever targets satisfies this (the whole point is to cover
        an upcoming high-rate window) — so this is True whenever the
        target boundary is reachable. Implemented as a property of the
        target boundary rather than a literal period-name check (per
        Pass-2 A's P2A-HIGH-1 / P2B-MED-2 — winter mid_peak boundary
        ALSO needs the 15-min lead, not only summer peak).

        Returns False conservatively when rates cannot be read; the
        regular boundary-reached fallback (mins<=0) still handles that.
        """
        if self._tou is None or target_period is None:
            return False
        try:
            season = self._tou.get_season(now)
            periods = self._tou._rates[season]["periods"]
            cur = periods.get(tou_period, {}).get("import_rate")
            tgt = periods.get(target_period, {}).get("import_rate")
            if cur is None or tgt is None:
                return False
            return float(tgt) >= float(cur)
        except Exception:  # noqa: BLE001
            return False

    def _midpeak_rate_lt_peak(self, now: datetime) -> bool:
        """D1b gate: mid_peak rate strictly less than peak rate (real rates).

        Operator: extension into mid_peak only when the rate-spread economics
        justify it. Read real rates from TOU engine — no hardcoded prices.
        Returns False conservatively when rates cannot be read.
        """
        if self._tou is None:
            return False
        try:
            season = self._tou.get_season(now)
            periods = self._tou._rates[season]["periods"]
            mp = periods.get("mid_peak", {}).get("import_rate")
            pk = periods.get("peak", {}).get("import_rate")
            if mp is None or pk is None:
                return False
            return float(mp) < float(pk)
        except Exception:  # noqa: BLE001
            return False

    def _should_attain_peak_buffer(
        self,
        soc: float | None,
        now: datetime,
        tou_period: str = "off_peak",
    ) -> tuple[bool, float | None, float | None, int | None]:
        """ENTRY predicate (fix-up pass — entry-only, not re-evaluated while latched).

        Returns (should_attain, projected_soc, observed_rate, minutes_to_boundary).

        True iff ALL of:
          1. arbitrage_enabled.
          2. peak_buffer_target set + soc not None + soc < peak_buffer_target.
          3. tou_period is off_peak (always eligible) OR mid_peak with D1b
             rate-spread gate open (mid_peak rate < peak rate). Off_peak
             additionally requires the charge window open per
             `_is_charge_window_open`.
          4. minutes_to_attain_boundary >= ATTAIN_MIN_REMAINING_MIN (30 min
             floor — operator-ratified: don't enter when actuation lag will
             eat the whole window).
          5. observed net charge rate is known (≥2 trailing samples) AND
             solar-informed projected SOC at boundary <
             peak_buffer_target. The projection now includes an expected
             solar-surplus term so good-day morning starts (winter 23:00,
             summer 08:00) don't fire when even forecast solar will deliver.

        On cold boot when the window is empty, returns (False, None, None, mins)
        — predicate DEFERS one cycle to let the window seed.

        ONLY consulted on ENTRY. Once `_attain_active=True` we do NOT call
        this — eliminating the A-CRIT-1 / B-HIGH-1 self-referential rate
        loop where attain's own grid-charge inflated K-tick rate, flipped
        predicate False, and unwound mid-charge. See `determine_mode` for
        exit conditions.

        D2-style chunk-lock gate: respect `_arbitrage_chunk_completed`
        (A-HIGH-1 / B-HIGH-2 / C-HIGH-1 — three-way convergence). After
        the guard aborts the chunk, attain stays out until the next
        off-peak chunk reset.
        """
        if not self._arbitrage_enabled:
            return (False, None, None, None)
        if self._peak_buffer_target is None or soc is None:
            return (False, None, None, None)
        if soc >= self._peak_buffer_target:
            return (False, None, None, None)
        # Chunk-lock gate (A-HIGH-1 / B-HIGH-2 / C-HIGH-1).
        if self._arbitrage_chunk_completed:
            return (False, None, None, None)
        # Off_peak requires charge window open; mid_peak requires D1b gate.
        if tou_period == "off_peak":
            if not self._is_charge_window_open(now):
                return (False, None, None, None)
        elif tou_period == "mid_peak":
            if not self._midpeak_rate_lt_peak(now):
                return (False, None, None, None)
        else:
            # A-LOW-2: unknown TOU fall-through — only allow attain in
            # explicitly recognized off_peak or mid_peak periods.
            return (False, None, None, None)
        _, _period_name, mins = self._attain_target_boundary(now, tou_period)
        if mins is None or mins <= 0:
            return (False, None, None, mins)
        # Operator-ratified entry floor: don't enter with <30 min remaining;
        # actuation lag swallows the window.
        if mins < ATTAIN_MIN_REMAINING_MIN:
            return (False, None, None, mins)
        rate = self._observed_net_charge_rate_per_hour()
        if rate is None:
            return (False, None, None, mins)
        # Solar-informed projection (A-HIGH-2): observed-rate term +
        # expected-solar-surplus term. Stale/unavailable Solcast → surplus
        # collapses to 0 (fail toward charging).
        solar_surplus = self._expected_solar_surplus_pct(now, mins)
        projected = soc + (mins / 60.0) * rate + solar_surplus
        if projected < self._peak_buffer_target:
            return (True, projected, rate, mins)
        return (False, projected, rate, mins)

    def _get_attainability_decision(
        self,
        soc: float | None,
        now: datetime,
        target_day_class: str,
        tomorrow_class: str,
        current_mode: str | None,
        season: str,
        projected: float | None,
        rate: float | None,
        mins: int | None,
        tou_period: str = "off_peak",
        stage_note: str | None = None,
    ) -> dict[str, Any]:
        """Build the ATTAIN-phase CHARGE decision dict.

        Same action shape as arbitrage CHARGE (charge_from_grid=True,
        reserve_level=peak_buffer_target). Idempotent via _result()'s
        diff-against-current state — "command once, then verify-only" while
        the latch persists across ticks (fix-up pass).

        Dead-code latch at the old location removed: marking
        `_arbitrage_chunk_completed = True` here was unreachable (caller
        only invoked this when soc < target). The proper completion
        transition now lives in `_get_attainability_hold_decision`
        emitted by `determine_mode` when the latch exits via SOC >= target.
        """
        self._arbitrage_active = True
        # Plain-English reason — operator-mandated explicit WHY.
        boundary_str = "boundary"
        try:
            tou_target_dt, _, _m = self._attain_target_boundary(now, tou_period)
            if tou_target_dt is not None:
                boundary_str = tou_target_dt.strftime("%H:%M")
        except Exception:  # noqa: BLE001
            pass
        stage = f" ({stage_note})" if stage_note else ""
        # D1b: name the stage in the reason when continuation into mid_peak
        # targets the PEAK boundary, so reviewers + sensor narratives can
        # distinguish "off_peak attain" from "mid_peak attain covering peak".
        proj_str = f"{projected:.0f}%" if projected is not None else "?"
        rate_str = f"{rate:+.1f}%/h" if rate is not None else "?"
        mins_str = f"{mins} min" if mins is not None else "?"
        reason = (
            f"Peak-buffer attainability{stage} — projected SOC "
            f"{proj_str} < target {self._peak_buffer_target}% "
            f"at {boundary_str} (observed net rate "
            f"{rate_str} over {ATTAIN_RATE_WINDOW_TICKS} ticks, "
            f"{mins_str} remaining; solar consumed by house/EV loads)"
        )
        return self._result(
            BATTERY_MODE_SELF_CONSUMPTION,
            reason,
            current_mode,
            charge_from_grid=True,
            reserve_level=self._peak_buffer_target,
            season=season,
            tomorrow_solar_class=tomorrow_class,
            arbitrage_active=True,
            arbitrage_phase=ARBITRAGE_PHASE_ATTAIN,
            target_day_class=target_day_class,
        )

    def _get_attainability_hold_decision(
        self,
        soc: float | None,
        now: datetime,
        target_day_class: str,
        tomorrow_class: str,
        current_mode: str | None,
        season: str,
    ) -> dict[str, Any]:
        """ATTAIN exit via SOC reaching target — HOLD-shaped.

        Mirrors arbitrage HOLD (charge_from_grid=False, reserve=target,
        chunk_completed=True) so the reserve stays locked at target until
        the boundary transition takes over — see arbitrage HOLD at
        :717-718 + :822-827. This is the structural fix for A-CRIT-1
        defect 3: previously, reaching target made the predicate False
        and the drain-target fallback released the buffer pre-boundary;
        now we hold.
        """
        self._arbitrage_active = True
        # Mark chunk completed so the entry predicate stays locked out.
        # The latch (`_attain_state="holding"`) is OWNED by the routing
        # logic — do NOT flip it here (Pass-2 P2A-CRIT-1: dropping the
        # latch let the drain-target fallback release the buffer on the
        # very next tick).
        self._arbitrage_chunk_completed = True
        reason = (
            f"Peak-buffer attainability HOLD — SOC {soc:.0f}% reached "
            f"target {self._peak_buffer_target}%; locking reserve until boundary"
            if soc is not None
            else f"Peak-buffer attainability HOLD — locking reserve at "
                 f"{self._peak_buffer_target}% until boundary"
        )
        return self._result(
            BATTERY_MODE_SELF_CONSUMPTION,
            reason,
            current_mode,
            charge_from_grid=False,
            reserve_level=self._peak_buffer_target,
            season=season,
            tomorrow_solar_class=tomorrow_class,
            arbitrage_active=True,
            arbitrage_phase=ARBITRAGE_PHASE_ATTAIN,
            target_day_class=target_day_class,
        )

    def _get_attainability_hold_current_decision(
        self,
        soc: float | None,
        current_mode: str | None,
        season: str,
        tomorrow_class: str,
        target_day_class: str,
    ) -> dict[str, Any]:
        """B-HIGH-3 — reboot-mid-ATTAIN HOLD-CURRENT (zero hardware commands).

        On the cold-boot K-tick warm-up after restarting while the Enphase
        was mid-charge (charge_from_grid ON + reserve 80), the old code
        fell through to the drain/hold fallback which read cfg=ON and
        emitted `switch.turn_off` plus a reserve drop — exactly the
        unwind the cycle exists to prevent.

        This path emits a decision dict with NO actions (empty list) and
        records no command intent, so `_result`'s normal idempotent
        comparison can't accidentally toggle anything. Reviewer B's note
        captured in the live-validation table.
        """
        reason = (
            "Peak-buffer attainability — post-reboot HOLD CURRENT "
            "(K-tick rate-window warm-up; preserving in-flight Enphase "
            "state, no commands issued)"
        )
        # P2A-MED-3: update _last_mode/_last_reason/_arbitrage_phase so
        # get_status() reflects the current phase/reason (do not bypass).
        self._arbitrage_active = True
        self._last_mode = current_mode or BATTERY_MODE_SELF_CONSUMPTION
        self._last_reason = reason
        self._arbitrage_phase = ARBITRAGE_PHASE_ATTAIN
        return {
            "mode": current_mode or BATTERY_MODE_SELF_CONSUMPTION,
            "reason": reason,
            "actions": [],
            "soc": soc,
            "solar_production": self.solar_production,
            "net_power": self.net_power,
            "battery_power": self.battery_power,
            "solar_day_class": self.classify_solar_day(),
            "tomorrow_solar_class": tomorrow_class,
            "envoy_available": True,
            "season": season,
            "arbitrage_active": True,
            "arbitrage_enabled": self._arbitrage_enabled,
            "arbitrage_phase": ARBITRAGE_PHASE_ATTAIN,
            "target_day_class": target_day_class,
            "reserve_soc": self.reserve_soc,
        }

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
        self._arbitrage_guard_consecutive_trips = 0
        # Cycle EC/HC reboot pickup: attainability rate window is
        # per-chunk by design. Each off-peak chunk resets the trailing
        # SOC samples so a stale (yesterday's) rate cannot influence
        # the new chunk's projection.
        self._attain_soc_history.clear()
        # Fix-up pass: latch is per-chunk. New off-peak chunk → fresh
        # entry decision. M5: also reset drift-log gate + tick counter.
        self._attain_state = "inactive"
        self._attain_drift_logged = False
        self._attain_charging_ticks = 0

    # ── Fix-up pass 3 — tri-state attain branch (shared off_peak + mid_peak D1b)
    def _adopt_attain_state_from_hardware(
        self,
        soc: float | None,
        now: datetime,
        tou_period: str,
    ) -> str:
        """M2 — derive attain state from observable hardware on first tick.

        Reads the LIVE charge_from_grid switch + current reserve + SOC +
        TOU period to classify into {"inactive","charging","holding",
        "release"}. Called exactly once per process boot (the first time
        any attain branch evaluates). "release" is a sentinel: caller
        invokes the normal release path (turn_off + reserve restore) when
        we boot mid-charge but outside any valid charge window (e.g. boot
        landed during peak).

        Skips the K-tick warm-up requirement for ADOPTION specifically —
        we trust hardware state more than a stale RAM-only latch.
        """
        # Read the live cfg switch state.
        cfg = self._get_state_bool(
            self._get_entity("charge_from_grid", DEFAULT_CHARGE_FROM_GRID_ENTITY)
        )
        if cfg is not True:
            # cfg OFF or unknown — fall through to normal cold-boot path.
            return "inactive"

        # cfg ON post-reboot — classify by window/period/SOC.
        target_dt, target_period, mins = self._attain_target_boundary(now, tou_period)
        in_off_peak_window = (
            tou_period == "off_peak"
            and self._is_charge_window_open(now)
        )
        in_midpeak_window = (
            tou_period == "mid_peak"
            and self._midpeak_rate_lt_peak(now)
            and self._tou is not None
            and self._tou.peak_ahead_before_offpeak(now)
        )

        # SOC >= target with a boundary ahead → HOLD adoption.
        if (
            soc is not None
            and self._peak_buffer_target is not None
            and soc >= self._peak_buffer_target
            and mins is not None
            and mins > 0
            and (in_off_peak_window or in_midpeak_window)
        ):
            return "holding"
        # SOC < target inside an active charge window → CHARGING adoption.
        if (
            soc is not None
            and self._peak_buffer_target is not None
            and soc < self._peak_buffer_target
            and mins is not None
            and mins > 0
            and (in_off_peak_window or in_midpeak_window)
        ):
            return "charging"
        # cfg ON but no valid window (e.g. boot landed during peak) →
        # orderly release.
        return "release"

    def _maybe_run_reboot_recovery(
        self,
        soc: float | None,
        now: datetime,
        tou_period: str,
        target_day_class: str,
        tomorrow_class: str,
        current_mode: str | None,
        season: str,
    ) -> dict[str, Any] | None:
        """M2 driver: invoke adoption exactly once post-boot.

        Returns a decision dict (orderly-release path) or None to let the
        caller continue with the routing logic. Side-effect: sets
        `_attain_state` from hardware on first invocation.
        """
        if self._attain_reboot_recovered:
            return None
        self._attain_reboot_recovered = True
        adopted = self._adopt_attain_state_from_hardware(soc, now, tou_period)
        if adopted == "inactive":
            self._attain_state = "inactive"
            return None
        if adopted == "release":
            # Orderly release via the normal release path: emit a
            # charge_from_grid=False + reserve restore decision, log
            # operator-visible WARN. Distinct from the drain-fallback's
            # incidental unwind.
            _LOGGER.warning(
                "Attainability reboot recovery: charge_from_grid was ON "
                "but boot landed outside any valid attain window "
                "(tou_period=%s, soc=%s) — orderly release: turning OFF + "
                "restoring reserve",
                tou_period, soc,
            )
            self._attain_state = "inactive"
            return self._result(
                BATTERY_MODE_SELF_CONSUMPTION,
                "Peak-buffer attainability — reboot recovery: "
                "orderly release (boot landed outside charge window)",
                current_mode,
                charge_from_grid=False,
                reserve_level=self.reserve_soc,
                season=season,
                tomorrow_solar_class=tomorrow_class,
                arbitrage_active=False,
                arbitrage_phase=ARBITRAGE_PHASE_NA,
                target_day_class=target_day_class,
            )
        # Adopted as charging or holding — set state, caller routes.
        self._attain_state = adopted
        _LOGGER.info(
            "Attainability reboot recovery: hardware shows cfg=ON, "
            "adopting state=%s (soc=%s, tou_period=%s)",
            adopted, soc, tou_period,
        )
        return None

    def _run_attain_branch(
        self,
        soc: float | None,
        now: datetime,
        tou_period: str,
        target_day_class: str,
        tomorrow_class: str,
        current_mode: str | None,
        season: str,
    ) -> dict[str, Any] | None:
        """Run the tri-state attain decision flow (M1).

        Routing order — operator-mandated:
          0. Reboot recovery (M2) — on first decision tick after boot,
             derive `_attain_state` from observable hardware. May emit an
             orderly-release decision if cfg ON but no valid window.
          1. ``holding`` → return HOLD decision EVERY TICK (reserve pinned
             at target, charge_from_grid OFF). Routed BEFORE the entry
             predicate AND the chunk-lock check. Exits via boundary
             handoff (M3) OR charge window close. SOC sagging below target
             while holding STAYS holding (reserve pins it).
          2. ``charging`` → verify-only maintenance. Transition to
             ``holding`` when SOC >= target. M5 drift policy applies.
          3. ``inactive`` → entry predicate (with solar term + floor + rate
             gate) may fire. Sets state=charging on entry.

        Returns the decision dict to emit, OR None when the caller should
        fall through to the default branch.
        """
        # ---- M2: reboot recovery (runs exactly once per process boot) --
        recovery = self._maybe_run_reboot_recovery(
            soc, now, tou_period, target_day_class, tomorrow_class,
            current_mode, season,
        )
        if recovery is not None:
            return recovery

        # Always record the sample so the trailing window seeds.
        self._record_attain_sample(now, soc)

        # ---- Route HOLDING first (before predicate + chunk-lock) -------
        if self._attain_state == "holding":
            # M7 (P2A-MED-2 / P2B-MED-3): re-verify D1b rate gate every
            # tick when holding through mid_peak. Rate-schedule shift
            # (rare) → orderly release.
            if tou_period == "mid_peak" and not self._midpeak_rate_lt_peak(now):
                _LOGGER.info(
                    "Attainability HOLDING released — mid_peak rate gate "
                    "closed (rate schedule shift); orderly release"
                )
                self._attain_state = "inactive"
                return None
            # Boundary lookahead + handoff lead.
            _, target_period, mins = self._attain_target_boundary(now, tou_period)
            # Window closed (boundary reached / past) → orderly release.
            if mins is None or mins <= 0:
                self._attain_state = "inactive"
                return None
            # M3 generalized handoff lead — applies whenever target
            # boundary's period rate >= current period rate.
            if (
                mins <= ATTAIN_PEAK_HANDOFF_LEAD_MIN
                and self._attain_target_period_at_or_above_current(
                    now, tou_period, target_period,
                )
            ):
                _LOGGER.info(
                    "Attainability HOLDING handoff (%dm to %s ≤ %dm lead): "
                    "release for boundary takeover, reserve stays at target",
                    mins, target_period or "?", ATTAIN_PEAK_HANDOFF_LEAD_MIN,
                )
                self._attain_state = "inactive"
                # Emit HOLD-shape one more tick so reserve stays at target
                # while the boundary takeover commands its own setpoint.
                return self._get_attainability_hold_decision(
                    soc=soc, now=now,
                    target_day_class=target_day_class,
                    tomorrow_class=tomorrow_class,
                    current_mode=current_mode, season=season,
                )
            # Persistent HOLD: re-emit every tick (charge_from_grid=False
            # via _result, reserve pinned at target). _result is
            # idempotent — no repeated commands if already commanded.
            return self._get_attainability_hold_decision(
                soc=soc, now=now,
                target_day_class=target_day_class,
                tomorrow_class=tomorrow_class,
                current_mode=current_mode, season=season,
            )

        # ---- Route CHARGING (after holding-first) -----------------------
        if self._attain_state == "charging":
            # Transition to holding when SOC reaches target.
            if (
                soc is not None
                and self._peak_buffer_target is not None
                and soc >= self._peak_buffer_target
            ):
                _LOGGER.info(
                    "Attainability HOLDING entered: SOC %.0f%% reached target %d%%; "
                    "reserve held at target until boundary",
                    soc, self._peak_buffer_target,
                )
                self._attain_state = "holding"
                self._arbitrage_chunk_completed = True
                self._attain_drift_logged = False
                return self._get_attainability_hold_decision(
                    soc=soc, now=now,
                    target_day_class=target_day_class,
                    tomorrow_class=tomorrow_class,
                    current_mode=current_mode, season=season,
                )
            # Chunk lock raised elsewhere → drop to inactive, fall through.
            if self._arbitrage_chunk_completed:
                self._attain_state = "inactive"
                return None
            # M7 (P2A-MED-2 / P2B-MED-3): re-verify D1b rate gate while
            # charging through mid_peak.
            if tou_period == "mid_peak" and not self._midpeak_rate_lt_peak(now):
                _LOGGER.info(
                    "Attainability CHARGING released — mid_peak rate gate "
                    "closed (rate schedule shift); orderly release"
                )
                self._attain_state = "inactive"
                return None
            # Compute boundary for handoff + reason narrative.
            _, target_period, mins = self._attain_target_boundary(now, tou_period)
            if mins is None or mins <= 0:
                self._attain_state = "inactive"
                return None
            # M3 generalized boundary-handoff lead.
            if (
                mins <= ATTAIN_PEAK_HANDOFF_LEAD_MIN
                and self._attain_target_period_at_or_above_current(
                    now, tou_period, target_period,
                )
            ):
                _LOGGER.info(
                    "Attainability CHARGING handoff (%dm to %s ≤ %dm lead): "
                    "transition to HOLDING for boundary takeover",
                    mins, target_period or "?", ATTAIN_PEAK_HANDOFF_LEAD_MIN,
                )
                self._attain_state = "holding"
                return self._get_attainability_hold_decision(
                    soc=soc, now=now,
                    target_day_class=target_day_class,
                    tomorrow_class=tomorrow_class,
                    current_mode=current_mode, season=season,
                )
            # Guard re-check while charging.
            snap = self._effective_import_kw()
            if snap is not None and snap[0] > self._arbitrage_grid_import_guard_kw:
                effective_kw, net_kw, batt_charge_kw = snap
                self._arbitrage_guard_consecutive_trips += 1
                if (
                    self._arbitrage_guard_consecutive_trips
                    >= ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK
                ):
                    from homeassistant.util import dt as dt_util
                    self._arbitrage_chunk_completed = True
                    self._arbitrage_guard_aborted_at = dt_util.now().isoformat()
                    self._arbitrage_guard_aborted_kw = effective_kw
                    self._attain_state = "inactive"
                    _LOGGER.warning(
                        "Attainability CHARGE aborted by grid-import guard: "
                        "effective_import=%.1f kW (net=%.1f, battery_charge=%.1f) "
                        "exceeds %.1f kW on %d consecutive ticks. Chunk locked "
                        "(will retry next off-peak chunk).",
                        effective_kw, net_kw, batt_charge_kw,
                        self._arbitrage_grid_import_guard_kw,
                        self._arbitrage_guard_consecutive_trips,
                    )
                    return None
                # under N consecutive — keep CHARGE (one tick to absorb lag).
            else:
                self._arbitrage_guard_consecutive_trips = 0

            # M5: operator/Enphase drift policy. While we are charging,
            # if the cfg switch reads OFF (operator manual flip or
            # Enphase revert), DO NOT fight it — log once, transition to
            # inactive + chunk-lock; retry next chunk. Guarded by tick
            # counter: cfg actuation has measured ~35-min cloud lag, so
            # don't enforce until our own command has had a chance to
            # land (>=3 charging ticks ≈ 15 min — comfortably under the
            # actuation envelope but past the test-fixture single-tick
            # window where cfg is intentionally still "off").
            self._attain_charging_ticks += 1
            if self._attain_charging_ticks > 3:
                cfg = self._get_state_bool(
                    self._get_entity("charge_from_grid", DEFAULT_CHARGE_FROM_GRID_ENTITY)
                )
                if cfg is False:
                    if not self._attain_drift_logged:
                        _LOGGER.warning(
                            "Attainability CHARGING — observed charge_from_grid OFF "
                            "after %d ticks of commanded ON (operator manual flip "
                            "or Enphase revert). Operator wins; transitioning to "
                            "inactive + chunk-lock. Will retry next off-peak chunk.",
                            self._attain_charging_ticks,
                        )
                        self._attain_drift_logged = True
                    self._attain_state = "inactive"
                    self._attain_charging_ticks = 0
                    self._arbitrage_chunk_completed = True
                    return None

            # Verify-only re-emit (idempotent via _result()'s diff).
            rate = self._observed_net_charge_rate_per_hour()
            # B-HIGH-3 / P2A-CRIT-2: post-reboot warm-up — when we are
            # latched in charging but the K-tick rate window has not yet
            # filled (rate is None), emit HOLD-CURRENT (zero actions) so
            # we never unwind an in-flight Enphase charge while the
            # window seeds. The M2 hardware-derived state adoption already
            # set us to "charging" before this point (or the test injected
            # the state directly).
            if rate is None:
                _LOGGER.info(
                    "Attainability latched + post-reboot warm-up "
                    "(K-tick rate window reseeding) — HOLD CURRENT, "
                    "no Enphase commands this tick"
                )
                return self._get_attainability_hold_current_decision(
                    soc=soc, current_mode=current_mode, season=season,
                    tomorrow_class=tomorrow_class,
                    target_day_class=target_day_class,
                )
            stage_note = (
                "mid_peak→peak coverage" if tou_period == "mid_peak" else None
            )
            solar_surplus = self._expected_solar_surplus_pct(now, mins)
            projected = (
                soc + (mins / 60.0) * rate + solar_surplus
                if soc is not None and rate is not None else None
            )
            return self._get_attainability_decision(
                soc=soc, now=now,
                target_day_class=target_day_class,
                tomorrow_class=tomorrow_class,
                current_mode=current_mode, season=season,
                projected=projected, rate=rate, mins=mins,
                tou_period=tou_period, stage_note=stage_note,
            )

        # ---- Route INACTIVE — entry predicate may fire -----------------
        should_attain, projected, rate, mins = self._should_attain_peak_buffer(
            soc, now, tou_period=tou_period,
        )
        if not should_attain:
            return None
        # Guard precedence on entry.
        snap = self._effective_import_kw()
        if snap is not None and snap[0] > self._arbitrage_grid_import_guard_kw:
            effective_kw, net_kw, batt_charge_kw = snap
            self._arbitrage_guard_consecutive_trips += 1
            if (
                self._arbitrage_guard_consecutive_trips
                >= ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK
            ):
                from homeassistant.util import dt as dt_util
                self._arbitrage_chunk_completed = True
                self._arbitrage_guard_aborted_at = dt_util.now().isoformat()
                self._arbitrage_guard_aborted_kw = effective_kw
                _LOGGER.warning(
                    "Attainability entry aborted by grid-import guard: "
                    "effective_import=%.1f kW (net=%.1f, battery_charge=%.1f) "
                    "exceeds %.1f kW on %d consecutive ticks. Chunk locked "
                    "(will retry next off-peak chunk).",
                    effective_kw, net_kw, batt_charge_kw,
                    self._arbitrage_grid_import_guard_kw,
                    self._arbitrage_guard_consecutive_trips,
                )
                return None
            # under N — still enter to absorb battery-CT lag.
        else:
            self._arbitrage_guard_consecutive_trips = 0

        # Enter charging state + emit first CHARGE (log on entry only —
        # A-LOW-1 — no per-tick spam while latched).
        self._attain_state = "charging"
        self._attain_drift_logged = False
        self._attain_charging_ticks = 1
        stage_note = (
            "mid_peak→peak coverage" if tou_period == "mid_peak" else None
        )
        _LOGGER.info(
            "Attainability ENTERED%s: projected SOC %.0f%% < target %d%% at "
            "boundary (rate=%+.1f%%/h, %dm left)",
            f" [{stage_note}]" if stage_note else "",
            projected if projected is not None else float("nan"),
            self._peak_buffer_target,
            rate if rate is not None else float("nan"),
            mins if mins is not None else -1,
        )
        return self._get_attainability_decision(
            soc=soc, now=now,
            target_day_class=target_day_class,
            tomorrow_class=tomorrow_class,
            current_mode=current_mode, season=season,
            projected=projected, rate=rate, mins=mins,
            tou_period=tou_period, stage_note=stage_note,
        )

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
            # D1b — operator-mandated mid_peak attainability continuation
            # (covers PEAK when off_peak couldn't fill the buffer). State-
            # matrix invariant change: charging is now permitted in mid_peak
            # IFF (a) attain is latched OR entry predicate fires, (b)
            # mid_peak rate < peak rate, (c) soc < peak_buffer_target, and
            # (d) peak is still ahead. Charging during PEAK remains
            # structurally impossible (no attain branch in the peak path).
            # Operator: "arbitrage IS arbitrage... if we can't cover
            # mid_peak we absolutely need to cover peak."
            if (
                self._arbitrage_enabled
                and self._peak_buffer_target is not None
                and soc is not None
                and soc < self._peak_buffer_target
                and season == "summer"
                and self._tou is not None
                and self._tou.peak_ahead_before_offpeak(now)
            ):
                tomorrow_class_mp = self.classify_tomorrow_solar()
                target_day_class_mp = self._classify_target_day(now)
                attain_result = self._run_attain_branch(
                    soc=soc,
                    now=now,
                    tou_period="mid_peak",
                    target_day_class=target_day_class_mp,
                    tomorrow_class=tomorrow_class_mp,
                    current_mode=current_mode,
                    season=season,
                )
                if attain_result is not None:
                    return attain_result
            # Summer mid_peak is a *bracketed* period: pre-peak window (14-16)
            # then peak (16-20) then post-peak window (20-21). Holding for
            # peak is correct PRE-peak but wastes grid POST-peak (off_peak
            # at 21:00, tomorrow's solar refills). Gate the hold on a real-
            # time, season/midnight-safe lookahead. If no peak is ahead before
            # the next off_peak hour, fall through to the shoulder/winter
            # discharge branch below — same code path, no duplicated logic.
            # When no TOU engine is wired (legacy / non-arbitrage harnesses),
            # preserve the prior summer-always-hold behavior — we cannot
            # discriminate pre/post-peak without the engine.
            summer_peak_ahead = season == "summer" and (
                self._tou is None
                or self._tou.peak_ahead_before_offpeak(now)
            )
            if summer_peak_ahead:
                # Summer mid-peak, peak still ahead: hold charge for upcoming peak
                hold_reserve = int(soc) if soc is not None else 100
                return self._result(
                    BATTERY_MODE_SELF_CONSUMPTION,
                    "Mid-peak (summer) — holding charge for peak",
                    current_mode,
                    reserve_level=hold_reserve,
                    season=season,
                )
            # Shoulder/Winter mid-peak: discharge — this is the best rate window.
            # Summer post-peak mid_peak ALSO reaches here (no peak ahead before
            # off_peak) and shares the same discharge logic with a distinct reason.
            summer_post_peak = season == "summer" and not summer_peak_ahead
            if soc is not None and soc > self.reserve_soc:
                if summer_post_peak:
                    reason = (
                        "Mid-peak (summer, post-peak) — discharging, off_peak imminent"
                    )
                else:
                    reason = (
                        f"Mid-peak ({season}) — discharging, best rate window"
                    )
                return self._result(
                    BATTERY_MODE_SELF_CONSUMPTION,
                    reason,
                    current_mode,
                    reserve_level=self.reserve_soc,
                    season=season,
                )
            if summer_post_peak:
                reason = (
                    f"Mid-peak (summer, post-peak) but SOC low ({soc}%) — minimal discharge"
                )
            else:
                reason = (
                    f"Mid-peak ({season}) but SOC low ({soc}%) — minimal discharge"
                )
            return self._result(
                BATTERY_MODE_SELF_CONSUMPTION,
                reason,
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

        # ── Attainability branch (fix-up pass — latched, solar-informed) ────
        # Arbitrage forecast gate closed but solar may still fail to deliver
        # (EV ensure-on, HVAC pre-cool, pool filtration etc.). When projection
        # at boundary < peak_buffer_target, pull grid to catch up. v1
        # observe-only on EVs (no EVSE coupling).
        if self._arbitrage_enabled:
            attain_result = self._run_attain_branch(
                soc=soc,
                now=now,
                tou_period="off_peak",
                target_day_class=target_day_class,
                tomorrow_class=tomorrow_class,
                current_mode=current_mode,
                season=season,
            )
            if attain_result is not None:
                return attain_result
            # else: fall through to drain-target fallback below.

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
        if phase == ARBITRAGE_PHASE_ATTAIN:
            return (
                f"attainability grid charging to peak_buffer_target "
                f"({self._peak_buffer_target}%) — projection-driven catch-up"
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
