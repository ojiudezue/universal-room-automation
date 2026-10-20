"""Billing and cost tracking for Energy Coordinator.

Sub-Cycle E4: Real-time cost awareness, bill cycle tracking, bill prediction.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .energy_const import (
    BILL_ACCURACY_HORIZONS,
    BILL_FORECAST_DOW_WEEKS,
    BILL_FORECAST_MIN_DAYS,
    BILL_FORECAST_TRAILING_DAYS,
    BILL_LEDGER_MAX_CYCLES,
    BILL_LEDGER_SCORE_DEADLINE_DAYS,
    BILLING_SOURCE_AUTO,
    BILLING_SOURCE_METER,
    BILLING_SOURCE_POWER,
    DEFAULT_BILL_CYCLE_START_DAY,
    DEFAULT_ENERGY_BILLING_SOURCE,
    PEAK_AVOIDANCE_MIN_SERVED_KW,
    PEC_FIXED_CHARGES,
    UTILITY_STATS_STALE_H,
)
from .energy_billing_counters import CounterAccrualTracker
from .energy_tou import TOURateEngine
from ..const import (
    CONF_ELECTRICITY_RATE,
    DEFAULT_ELECTRICITY_RATE,
)

_LOGGER = logging.getLogger(__name__)


def _get_effective_rate_kwh(
    hass: HomeAssistant,
    *,
    room_entry=None,
) -> tuple[float, str]:
    """Return (rate_$/kWh, source) — EC TOU when configured, static fallback otherwise.

    Resolution order:
    1. EC's current_effective_rate (TOU-aware)  → (rate, "ec_tou")
    2. Room entry's CONF_ELECTRICITY_RATE override (if room_entry given) → (rate, "static_config")
    3. Global integration CONF_ELECTRICITY_RATE  → (rate, "static_config")
    4. DEFAULT_ELECTRICITY_RATE                  → (rate, "static_config")

    v4.6.8: Centralises every cost-rate lookup so the magic 0.1 fallback is
    eliminated and TOU awareness reaches all cost sensors automatically.
    Never raises — always returns a usable float.
    """
    from ..const import DOMAIN

    # 1. Try Energy Coordinator's live TOU rate.
    try:
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is not None:
            ec = manager.coordinators.get("energy")
            if ec is not None:
                rate = ec.current_effective_rate
                if rate is not None and isinstance(rate, (int, float)) and rate > 0:
                    return float(rate), "ec_tou"
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("rate helper tier 1 (EC TOU) failed: %s", exc)

    # 2. Room-level static override.
    if room_entry is not None:
        try:
            room_rate = room_entry.options.get(
                CONF_ELECTRICITY_RATE,
                room_entry.data.get(CONF_ELECTRICITY_RATE),
            )
            if room_rate is not None:
                return float(room_rate), "static_config"
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("rate helper tier 2 (room override) failed: %s", exc)

    # 3. Global integration entry static rate. Read the canonical slot:
    # __init__.py stores the integration entry directly at hass.data[DOMAIN]["integration"]
    # (a ConfigEntry — NOT wrapped in a dict). v4.6.8 fix: prior loop assumed
    # dict-shaped values and never matched, silently falling through to step 4.
    try:
        integration_entry = hass.data.get(DOMAIN, {}).get("integration")
        if integration_entry is not None:
            global_rate = integration_entry.options.get(
                CONF_ELECTRICITY_RATE,
                integration_entry.data.get(CONF_ELECTRICITY_RATE),
            )
            if global_rate is not None:
                return float(global_rate), "static_config"
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("rate helper tier 3 (global integration) failed: %s", exc)

    # 4. Hardcoded module-level default (never 0.1).
    return DEFAULT_ELECTRICITY_RATE, "static_config"


class CostTracker:
    """Tracks energy costs by TOU period, daily, and per billing cycle.

    Accumulates cost each decision cycle by reading current power and
    multiplying by the effective rate for the time elapsed.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        tou_engine: TOURateEngine,
        bill_cycle_day: int = DEFAULT_BILL_CYCLE_START_DAY,
        net_power_entity: str | None = None,
        solar_entity: str | None = None,
        grid_import_entity: str | None = None,
        grid_export_entity: str | None = None,
        billing_source: str | None = None,
    ) -> None:
        """Initialize cost tracker.

        v4.2.0: Optional direct grid import/export sensors (e.g., Emporia mains).
        When configured, these are preferred over derived net_power values.
        """
        self.hass = hass
        self._tou = tou_engine
        self._bill_cycle_day = bill_cycle_day
        # v4.3.1: no production fallback. Envoy validation gate (v4.2.29) ensures
        # these are populated when EC is enabled; if they are None, downstream
        # methods (_get_net_power, etc.) handle gracefully via state.get(None).
        self._net_power_entity = net_power_entity
        self._solar_entity = solar_entity
        self._grid_import_entity = grid_import_entity
        self._grid_export_entity = grid_export_entity

        # Daily accumulators (reset at midnight)
        self._cost_today: float = 0.0
        self._import_kwh_today: float = 0.0
        self._import_cost_today: float = 0.0
        self._export_kwh_today: float = 0.0
        self._export_credit_today: float = 0.0
        self._last_date: str = ""

        # Billing cycle accumulators (reset on cycle day)
        self._cost_this_cycle: float = 0.0
        self._import_kwh_cycle: float = 0.0
        self._export_kwh_cycle: float = 0.0
        self._cycle_start_date: str = ""
        self._days_in_cycle: int = 0

        # Bill prediction
        self._predicted_bill: float | None = None
        self._last_accumulate_time: float | None = None
        # EC-BILL-PREDICTION-FORECAST-1: inputs pushed by the coordinator
        # (never fetched from here), the per-run forecast breakdown, the
        # single producer of `prediction_source`, and the accuracy ledger.
        self._utility_inputs: dict[str, Any] | None = None
        self._forecast: dict[str, Any] = {}
        self._prediction_source: str = "learning"
        self._cycle_end: date | None = None
        self._days_remaining: int | None = None
        self.ledger = BillForecastLedger()

        # PLANNING_ec_billing_emporia_counters §D2: counter accrual tracker.
        # Instantiated unconditionally so `_counters.last_net_kw()` is always
        # callable; the counter path is only taken when the configured
        # IMPORT/EXPORT slots are kWh counters (sniffed in `accumulate`).
        self._counters = CounterAccrualTracker(
            hass, tou_engine,
            import_entity=grid_import_entity,
            export_entity=grid_export_entity,
        )
        self._billing_source = (
            billing_source or DEFAULT_ENERGY_BILLING_SOURCE
        )
        # Day-flag written to `energy_daily.billing_source` at midnight.
        self._billing_source_today: str | None = None
        self._counter_last_update: str | None = None
        # A-MED (2026-10-09): one-shot diagnostic flags so the hot path
        # emits each log at most once per CostTracker instance.
        self._logged_power_mode_kwh_slot: bool = False
        self._logged_counter_mode_false_with_slots: bool = False
        # §D7 (REV 4 op req): single producer for the outage counter;
        # consumed by both the EC attribute and the dedicated sensor.
        self._outage_days_this_cycle: int = 0

    def _grid_slot_uom(self) -> str | None:
        """Return the uom of the IMPORT grid slot (None if unavailable).

        Used to detect counter-mode: a kWh/Wh slot signals the operator
        pointed GRID_IMPORT at a daily counter rather than a power sensor.
        """
        if not self._grid_import_entity:
            return None
        try:
            state = self.hass.states.get(self._grid_import_entity)
        except Exception:  # noqa: BLE001
            return None
        if state is None:
            return None
        return state.attributes.get("unit_of_measurement") or None

    def _is_counter_mode(self) -> bool:
        """Counter-mode is active when operator selects Meter totals OR
        under Auto when the import slot's uom is kWh/Wh."""
        if self._billing_source == BILLING_SOURCE_POWER:
            return False
        if self._billing_source == BILLING_SOURCE_METER:
            return bool(self._grid_import_entity and self._grid_export_entity)
        # Auto: sniff.
        uom = self._grid_slot_uom()
        return uom in ("kWh", "Wh") and bool(
            self._grid_import_entity and self._grid_export_entity
        )

    def _get_net_power(self) -> float | None:
        """Get net power in kW (positive=importing, negative=exporting).

        v4.2.0: Prefers direct grid import/export sensors when configured.
        Falls back to net_power entity (Envoy) otherwise.
        Both paths normalize to kW for consistent accumulation.

        ENVOY-PRODUCTION-STALE-1 D4-E (clean-core fix-up 3): BOTH branches
        fail-CLOSED on stale reads. Returns None on staleness → the
        accumulate tick is skipped (fail-CLOSED — no dollars accrued
        from frozen readings). Billing does its OWN freshness check
        via the shared helper rather than gating the shared
        `net_power_w` property, so the breaker / arbitrage path reads
        net_power exactly as develop does (Tier-3 MED-2).
        """
        # Deferred import to avoid a hard dependency at module load time.
        from .energy_battery import _state_age_s
        from .energy_const import DEFAULT_NET_POWER_MAX_AGE_S

        # PLANNING_ec_billing_emporia_counters §D6: counter-mode conditional.
        # When the GRID_IMPORT slot is a kWh/Wh counter, the raw slot value
        # is a daily total — reading it as kW would feed peak-avoidance a
        # 40 "kW" value at end-of-day. Hand off to the tracker's cached kW
        # (REV 4 LOW-1: that getter returns None when stale). On a cold
        # cache we FALL THROUGH to the Envoy net-power branch — do NOT
        # fall into the slot branch below, which would mis-read kWh as kW.
        _counter_mode = (
            self._counters is not None and self._is_counter_mode()
        )
        if _counter_mode:
            cached = self._counters.last_net_kw()
            if cached is not None:
                return cached
            # cold / stale tracker → skip the slot branch (would mis-read
            # kWh as kW); fall through to Envoy net-power below.

        # Prefer direct grid sensors (power mode only — kWh slots are
        # handled by the counter branch above).
        if (
            not _counter_mode
            and self._grid_import_entity
            and self._grid_export_entity
        ):
            import_state = self.hass.states.get(self._grid_import_entity)
            export_state = self.hass.states.get(self._grid_export_entity)
            # Operator 2026-10-09: when billing_source=power_readings is
            # explicitly selected but the configured grid slots are kWh/Wh
            # counters, DO NOT mis-read a daily-total kWh value as kW.
            # Fall through to the Envoy net-power branch instead. This is
            # distinct from counter-mode (which was skipped above because
            # the operator forced power mode); the slot_uom check is a
            # typing guard, not a mode gate.
            _imp_uom = (
                import_state.attributes.get("unit_of_measurement")
                if import_state is not None else None
            )
            if _imp_uom in ("kWh", "Wh"):
                if not self._logged_power_mode_kwh_slot:
                    _LOGGER.info(
                        "Billing power-readings mode selected but import "
                        "slot '%s' is a %s counter; ignoring kWh slots and "
                        "falling back to Envoy net power. (one-shot)",
                        self._grid_import_entity, _imp_uom,
                    )
                    self._logged_power_mode_kwh_slot = True
            elif (
                import_state and import_state.state not in ("unknown", "unavailable")
                and export_state and export_state.state not in ("unknown", "unavailable")
            ):
                # D4-E staleness gate — either leg stale = skip tick.
                # `age is None` (naive/missing stamp) → pass (no gate).
                imp_age = _state_age_s(import_state, stamp="last_reported")
                exp_age = _state_age_s(export_state, stamp="last_reported")
                if (
                    (imp_age is not None and imp_age > DEFAULT_NET_POWER_MAX_AGE_S)
                    or (exp_age is not None and exp_age > DEFAULT_NET_POWER_MAX_AGE_S)
                ):
                    return None
                try:
                    grid_import = float(import_state.state)
                    grid_export = float(export_state.state)
                    net = grid_import - grid_export  # positive=importing
                    # Normalize to kW (accumulate() expects kW).
                    # Emporia reports W, Envoy reports kW.
                    uom = import_state.attributes.get("unit_of_measurement", "")
                    if uom in ("W", "w"):
                        net /= 1000.0
                    return net
                except (ValueError, TypeError):
                    pass  # Fall through to net_power

        # Fallback: Envoy net power entity (None if not configured — v4.3.1)
        # v4.5.0 unit-consistency: normalize to kW.
        if self._net_power_entity is None:
            return None
        state = self.hass.states.get(self._net_power_entity)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        # D4-E staleness gate for Envoy fallback leg.
        age = _state_age_s(state, stamp="last_reported")
        if age is not None and age > DEFAULT_NET_POWER_MAX_AGE_S:
            return None
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            return None
        uom = state.attributes.get("unit_of_measurement", "")
        if uom in ("W", "w"):
            value /= 1000.0
        # If uom is "kW", value is already kW — pass through.
        return value

    def get_yesterday_totals(self) -> dict[str, float] | None:
        """Return yesterday's daily totals if we have them (before reset).

        Must be called BEFORE accumulate() on date change to capture
        the previous day's data before it's wiped. §D6b (REV 4): the
        returned dict carries `billing_source` — 'counter_gap' when
        counter mode AND measured staleness exceeded
        COUNTER_OUTAGE_FALLBACK_HRS at rollover; 'counters' when counter
        mode AND fresh; 'power_integration' otherwise. Writer-at-midnight
        for the day flag (no new timer).
        """
        if not self._last_date or self._last_date == dt_util.now().date().isoformat():
            return None  # No date change yet or same day

        # Determine the day flag source at rollover (operator req).
        from .energy_const import COUNTER_OUTAGE_FALLBACK_HRS
        source = None
        if self._billing_source != BILLING_SOURCE_POWER and self._counters is not None:
            try:
                stale_s = self._counters.staleness_s()
                in_counter_mode = self._is_counter_mode() or (
                    self._billing_source_today == "counters"
                )
                if in_counter_mode:
                    # B-M2 (REV 4 review fix-up): a counter that is
                    # AVAILABLE but has not ADVANCED beyond the stuck
                    # window during a day with known nonzero consumption
                    # should also count toward counter_gap. The stuck
                    # detector in CounterAccrualTracker already enforces
                    # the window; combine it with the staleness check so
                    # a "frozen but polling" counter is flagged.
                    is_stuck = False
                    try:
                        is_stuck = self._counters.is_stuck()
                    except Exception:  # noqa: BLE001
                        is_stuck = False
                    if (
                        (stale_s is not None and stale_s > (
                            COUNTER_OUTAGE_FALLBACK_HRS * 3600
                        ))
                        or is_stuck
                    ):
                        source = "counter_gap"
                    else:
                        source = "counters"
            except Exception:  # noqa: BLE001
                source = None
        if source is None:
            source = "power_integration"

        return {
            "date": self._last_date,
            "import_kwh": round(self._import_kwh_today, 4),
            "export_kwh": round(self._export_kwh_today, 4),
            "import_cost": round(self._import_cost_today, 4),
            "export_credit": round(self._export_credit_today, 4),
            "net_cost": round(self._cost_today, 4),
            "billing_source": source,
        }

    def accumulate(self) -> None:
        """Accumulate cost based on current power readings.

        Called each decision cycle (~5 minutes). Uses elapsed time
        to calculate energy consumed/produced since last call.
        """
        import time
        now_ts = time.time()
        now = dt_util.now()
        today = now.date().isoformat()

        # Reset daily counters if date changed
        if today != self._last_date:
            self._cost_today = 0.0
            self._import_kwh_today = 0.0
            self._import_cost_today = 0.0
            self._export_kwh_today = 0.0
            self._export_credit_today = 0.0
            self._last_date = today

        # Reset cycle counters if we passed the cycle day
        self._check_cycle_reset(now)

        # PLANNING_ec_billing_emporia_counters §D2 + §D6b: counter accrual.
        # Must run BEFORE the first-tick early return below so the counter
        # tracker seeds its baselines on the very first accumulate call;
        # otherwise the first real booking tick has no `_import_last_ts`
        # and the cap collapses to zero.
        # (dup header kept for diff clarity)

        # B-HIGH (2026-10-09 fix-up): the first accumulate after a
        # snapshot restore MUST book the restored-baseline delta — the
        # prior build threw that tick's slices away and lost
        # (midnight → first-tick) energy on every restart. In counter mode
        # we now fall through to the counter-mode block below; the tracker
        # knows how to produce slices from a restored baseline. The power
        # path still needs its seed (`_last_accumulate_time`) to compute a
        # legitimate elapsed window on the SECOND tick, so we capture the
        # prior stamp here and short-circuit the power path only.
        _prev_last_accumulate_time = self._last_accumulate_time
        self._last_accumulate_time = now_ts

        # PLANNING_ec_billing_emporia_counters §D2 + §D6b: counter accrual.
        # Under Auto / Meter totals with kWh slots, gross-per-leg kWh is
        # booked from the Emporia daily counters pro-rated across TOU
        # periods. Under Auto no intra-day power accrual happens during a
        # counter staleness window — counters catch up losslessly.
        # The elapsed > 1h guard is BYPASSED in counter mode (gap-recovery
        # deltas are legitimate and already capped per-leg).
        # A-MED (2026-10-09): one-shot diagnostic when both grid slots are
        # configured but counter mode evaluates False (the live-regression
        # signature). Captures source, uom, and both entity IDs so an
        # operator reload surfaces the exact gating condition.
        if (
            not self._logged_counter_mode_false_with_slots
            and self._grid_import_entity
            and self._grid_export_entity
            and self._counters is not None
            and not self._is_counter_mode()
        ):
            _LOGGER.info(
                "Billing counter mode evaluated FALSE while both slots "
                "set: source=%s uom=%s import=%s export=%s. (one-shot)",
                self._billing_source, self._grid_slot_uom(),
                self._grid_import_entity, self._grid_export_entity,
            )
            self._logged_counter_mode_false_with_slots = True

        if self._counters is not None and self._is_counter_mode():
            tick = self._counters.tick(now)
            if self._billing_source_today != "counters":
                _LOGGER.info(
                    "Billing entering counter mode: source=%s imp=%s exp=%s uom=%s",
                    self._billing_source, self._grid_import_entity,
                    self._grid_export_entity, self._grid_slot_uom(),
                )
            self._billing_source_today = "counters"
            self._counter_last_update = now.isoformat()
            if tick is not None:
                # TOU BY REFERENCE (operator 2026-10-09): price each slice
                # at the LIVE rate for the slice's instant via the shared
                # engine — never cache rates across slices or ticks.
                for period, imp_kwh, exp_kwh, slice_dt in tick.get("slices", []):
                    if imp_kwh > 0:
                        rate = self._tou.get_effective_import_rate(slice_dt)
                        cost = imp_kwh * rate
                        self._import_kwh_today += imp_kwh
                        self._import_cost_today += cost
                        self._cost_today += cost
                        self._import_kwh_cycle += imp_kwh
                        self._cost_this_cycle += cost
                    if exp_kwh > 0:
                        export_rate = self._tou.get_export_rate(slice_dt)
                        credit = exp_kwh * export_rate
                        self._export_kwh_today += exp_kwh
                        self._export_credit_today += credit
                        self._cost_today -= credit
                        self._export_kwh_cycle += exp_kwh
                        self._cost_this_cycle -= credit
            # Update bill prediction and return — do NOT also run the
            # power-integration path (would double-book).
            self._update_prediction(now)
            return

        # Power path: seed on the first tick (no prior stamp to measure
        # against), then integrate from the SECOND tick onward.
        if _prev_last_accumulate_time is None:
            return
        elapsed_hours = (now_ts - _prev_last_accumulate_time) / 3600.0
        if elapsed_hours <= 0 or elapsed_hours > 1:
            return  # Skip unreasonable intervals

        net_power = self._get_net_power()
        if net_power is None:
            return

        # net_power > 0 = importing from grid
        # net_power < 0 = exporting to grid
        # Envoy reports net power in kW, so kW * hours = kWh directly
        energy_kwh = abs(net_power) * elapsed_hours

        if net_power > 0:
            # Importing
            effective_rate = self._tou.get_effective_import_rate(now)
            cost = energy_kwh * effective_rate
            self._import_kwh_today += energy_kwh
            self._import_cost_today += cost
            self._cost_today += cost
            self._import_kwh_cycle += energy_kwh
            self._cost_this_cycle += cost
        else:
            # Exporting
            export_rate = self._tou.get_export_rate(now)
            credit = energy_kwh * export_rate
            self._export_kwh_today += energy_kwh
            self._export_credit_today += credit
            self._cost_today -= credit
            self._export_kwh_cycle += energy_kwh
            self._cost_this_cycle -= credit

        # Update bill prediction
        self._update_prediction(now)

    def _check_cycle_reset(self, now: datetime) -> None:
        """Reset billing cycle accumulators if we passed the cycle start day."""
        cycle_date = self._get_cycle_start(now)
        cycle_key = cycle_date.isoformat()

        if cycle_key != self._cycle_start_date:
            self._cycle_start_date = cycle_key
            self._cost_this_cycle = 0.0
            self._import_kwh_cycle = 0.0
            self._export_kwh_cycle = 0.0
            self._db_days_in_cycle = 0
            _LOGGER.info("Billing cycle reset: new cycle started %s", cycle_key)

        self._days_in_cycle = (now.date() - cycle_date).days

    def _get_cycle_start(self, now: datetime) -> date:
        """Get the start date of the current billing cycle."""
        day = self._bill_cycle_day
        if now.day >= day:
            return now.date().replace(day=day)
        # Before cycle day this month — cycle started last month
        first_of_month = now.date().replace(day=1)
        last_month = first_of_month - timedelta(days=1)
        try:
            return last_month.replace(day=day)
        except ValueError:
            # Cycle day doesn't exist in last month (e.g., 31st in Feb)
            return last_month

    def set_bill_cycle_day(self, day: int, now: datetime) -> bool:
        """EC-BILL-CYCLE-DAY-WIRED-1: change the cycle day mid-cycle.

        Re-keys `_cycle_start_date` to the new boundary WITHOUT zeroing the
        accumulators, so the next `_check_cycle_reset` does not wipe the
        running cycle. The caller re-seeds the totals for the new window
        from the DB (`reseed_cycle`). Returns True when the day changed.
        """
        if day == self._bill_cycle_day:
            return False
        self._bill_cycle_day = day
        self._cycle_start_date = self._get_cycle_start(now).isoformat()
        return True

    def reseed_cycle(self, db_cycle_data: dict) -> None:
        """Rebuild cycle totals = DB full days in the window + today so far.

        `get_energy_daily_for_cycle(start, today)` excludes today, so today's
        in-memory accumulators are added back. Used after a cycle-day change.
        """
        self._import_kwh_cycle = float(db_cycle_data.get("import_kwh", 0) or 0) + self._import_kwh_today
        self._export_kwh_cycle = float(db_cycle_data.get("export_kwh", 0) or 0) + self._export_kwh_today
        self._cost_this_cycle = float(db_cycle_data.get("net_cost", 0) or 0) + self._cost_today
        self._db_days_in_cycle = int(db_cycle_data.get("days", 0) or 0)

    def update_from_db(self, db_cycle_data: dict) -> None:
        """Update cycle accumulators from DB data on startup.

        Called once after coordinator starts, to restore cycle totals
        that would otherwise be lost on HA restart.
        Must set _cycle_start_date so _check_cycle_reset() doesn't wipe.
        """
        db_days = db_cycle_data.get("days", 0)
        if db_days > 0:
            self._import_kwh_cycle = db_cycle_data.get("import_kwh", 0)
            self._export_kwh_cycle = db_cycle_data.get("export_kwh", 0)
            self._cost_this_cycle = db_cycle_data.get("net_cost", 0)
            self._db_days_in_cycle = db_days
            # Set cycle start so _check_cycle_reset() recognizes this cycle
            self._cycle_start_date = self._get_cycle_start(
                dt_util.now()
            ).isoformat()
            _LOGGER.info(
                "Restored billing cycle from DB: %d days, $%.2f net cost",
                db_days, self._cost_this_cycle,
            )

    def restore_daily(self, snapshot: dict[str, Any]) -> None:
        """Restore today's billing accumulators from midnight snapshot.

        Called on startup to recover partial-day billing that would
        otherwise be lost on HA restart. Only restores if the snapshot
        date matches today.
        """
        snapshot_date = snapshot.get("snapshot_date", "")
        today = dt_util.now().date().isoformat()

        # PLANNING_ec_billing_emporia_counters §D5 LOW-2 (REV 4 verify):
        # restore the counter baseline BEFORE the date-mismatch early return.
        # Otherwise a restart spanning midnight would seed the first tick at
        # the current counter value and lose the midnight→restart energy.
        # The counter itself tracks a daily total — a stale (yesterday)
        # baseline value is still valid for the first-tick delta on the new
        # day because the counter will have reset at midnight (value-drop
        # reset detector handles that path).
        # B-L3 (REV 4 review fix-up): parse `updated_at` from the DB
        # snapshot and pass it to the tracker as `snapshot_ts` so the
        # first tick after restore has a real elapsed window + cap.
        _snap_ts: float | None = None
        _raw_updated = snapshot.get("updated_at")
        if _raw_updated:
            try:
                _parsed = dt_util.parse_datetime(_raw_updated)
                if _parsed is not None:
                    _snap_ts = _parsed.timestamp()
            except Exception:  # noqa: BLE001
                _snap_ts = None
        if self._counters is not None:
            self._counters.restore(
                snapshot.get("counter_import_last"),
                snapshot.get("counter_export_last"),
                snapshot_ts=_snap_ts,
            )
            src = snapshot.get("billing_source_today")
            if src:
                self._billing_source_today = src

        if snapshot_date != today:
            _LOGGER.debug(
                "Midnight snapshot date %s != today %s, skipping billing restore",
                snapshot_date, today,
            )
            return

        self._import_kwh_today = snapshot.get("import_kwh_today", 0)
        self._export_kwh_today = snapshot.get("export_kwh_today", 0)
        self._import_cost_today = snapshot.get("import_cost_today", 0)
        self._export_credit_today = snapshot.get("export_credit_today", 0)
        self._cost_today = snapshot.get("net_cost_today", 0)
        self._last_date = today
        _LOGGER.info(
            "Restored daily billing: import=%.3f kWh, export=%.3f kWh, cost=$%.4f",
            self._import_kwh_today, self._export_kwh_today, self._cost_today,
        )

    def _get_next_cycle_start(self, cycle_start: date) -> date:
        """First local date on which `_get_cycle_start` leaves `cycle_start`.

        This is the day the tracker rolls the cycle over, derived from the
        same helper (no hand-rolled month arithmetic).
        """
        d = cycle_start + timedelta(days=1)
        for _ in range(62):
            probe = datetime(d.year, d.month, d.day, 12)
            if self._get_cycle_start(probe) != cycle_start:
                return d
            d += timedelta(days=1)
        return cycle_start + timedelta(days=30)

    def set_utility_forecast_inputs(
        self, configured: bool, cache: dict[str, Any] | None,
    ) -> None:
        """Coordinator push: utility statistics config + current cache.

        `configured` is whether a utility import statistic id is set; `cache`
        is the coordinator's utility comparison (None when absent or
        describing other ids). Read by `_update_prediction` only.
        """
        self._utility_inputs = {"configured": bool(configured), "cache": cache}

    def _utility_cache_stale(self, cache: dict[str, Any] | None, now: datetime) -> bool:
        """Stale when missing, flagged stale, or newest hour older than the gate.

        The age is re-evaluated against `now` so a refresh that keeps
        failing (cache kept) still goes stale.
        """
        if not cache or cache.get("stale") is not False:
            return True
        newest = cache.get("newest_hour")
        if not newest:
            return True
        try:
            newest_dt = datetime.fromisoformat(str(newest))
        except (TypeError, ValueError):
            return True
        if newest_dt.tzinfo is None or now.tzinfo is None:
            return True
        return (now - newest_dt).total_seconds() / 3600.0 > UTILITY_STATS_STALE_H

    def _update_prediction(self, now: datetime) -> None:
        """Update the bill prediction (EC-BILL-PREDICTION-FORECAST-1, P3).

        Utility statistics configured and fresh: SmartHub-priced cost to date
        + remaining days forecast (same-weekday mean) + service charge once.
        Configured but stale/missing: unavailable (no EC fallback, D0 ratio
        stdev > 10 pp). Not configured: the legacy EC straight line, labelled
        `ec_uncorrected`.
        """
        # Entry reset: every run starts from an empty breakdown.
        self._forecast = {}
        cycle_start = self._get_cycle_start(now)
        next_start = self._get_next_cycle_start(cycle_start)
        self._cycle_end = next_start
        today = now.date()
        self._days_remaining = max(0, (next_start - today).days)
        day_of_cycle = (today - cycle_start).days
        svc = service_charge(self._tou)

        if day_of_cycle < BILL_FORECAST_MIN_DAYS:
            self._predicted_bill = None
            self._prediction_label = f"Learning ({day_of_cycle} days)"
            self._prediction_source = "learning"
            return

        inputs = self._utility_inputs or {}
        if inputs.get("configured"):
            cache = inputs.get("cache")
            fc = None
            if not self._utility_cache_stale(cache, now):
                fc = compute_bill_forecast(
                    cycle_start=cycle_start,
                    next_cycle_start=next_start,
                    today=today,
                    cache=cache,
                    svc=svc,
                )
            if fc is None:
                self._predicted_bill = None
                self._prediction_label = "Unavailable (utility stats stale)"
                self._prediction_source = "unavailable"
                return
            self._forecast = fc
            self._predicted_bill = fc["predicted"]
            self._prediction_label = None
            self._prediction_source = "utility"
            return

        # Not configured: legacy straight line on EC cost (known to read low).
        effective_days = getattr(self, "_db_days_in_cycle", 0) or self._days_in_cycle
        total_days = (next_start - cycle_start).days
        daily_rate = self._cost_this_cycle / max(effective_days, 1)
        self._prediction_label = None
        self._prediction_source = "ec_uncorrected"
        self._predicted_bill = round(daily_rate * total_days + svc, 2)

    def refresh_prediction(self, now: datetime) -> None:
        """Public re-run after the coordinator pushes new utility inputs."""
        self._update_prediction(now)

    def ledger_tick(
        self, now: datetime, last_cycle: dict[str, Any] | None,
    ) -> bool:
        """Snapshot today's prediction and score closed cycles.

        Returns True when the ledger changed (caller persists).
        """
        changed = False
        # Only a utility-sourced prediction (never None there) is scored.
        if self._prediction_source == "utility":
            cycle_start = self._get_cycle_start(now)
            changed |= self.ledger.record_snapshot(
                cycle_start,
                self._get_next_cycle_start(cycle_start),
                (now.date() - cycle_start).days,
                self._predicted_bill,
                self._forecast.get("actual_window_end"),
            )
        changed |= self.ledger.try_close(now.date(), last_cycle)
        return changed

    @property
    def cost_today(self) -> float:
        """Net cost today (import cost - export credit)."""
        return round(self._cost_today, 4)

    @property
    def cost_this_cycle(self) -> float:
        """Net cost so far in billing cycle."""
        return round(self._cost_this_cycle, 4)

    @property
    def import_kwh_cycle(self) -> float:
        """Total grid import kWh this billing cycle."""
        return round(self._import_kwh_cycle, 2)

    @property
    def predicted_bill(self) -> float | None:
        """Predicted bill for the current cycle (after BILL_FORECAST_MIN_DAYS)."""
        return self._predicted_bill

    @property
    def current_effective_rate(self) -> float:
        """Current effective import rate including delivery and transmission."""
        return self._tou.get_effective_import_rate()

    @property
    def prediction_label(self) -> str | None:
        """Status label: Learning / Unavailable, None when predicting."""
        return getattr(self, "_prediction_label", None)

    def get_status(self) -> dict[str, Any]:
        """Return billing status for sensors."""
        return {
            "cost_today": self.cost_today,
            "import_kwh_today": round(self._import_kwh_today, 3),
            "import_cost_today": round(self._import_cost_today, 4),
            "export_kwh_today": round(self._export_kwh_today, 3),
            "export_credit_today": round(self._export_credit_today, 4),
            "cost_this_cycle": self.cost_this_cycle,
            "import_kwh_cycle": round(self._import_kwh_cycle, 3),
            "export_kwh_cycle": round(self._export_kwh_cycle, 3),
            "days_in_cycle": self._days_in_cycle,
            "cycle_start_date": self._cycle_start_date,
            "predicted_bill": self.predicted_bill,
            "prediction_label": self.prediction_label,
            # EC-BILL-PREDICTION-FORECAST-1: sole producer of the source;
            # forecast breakdown; cycle length for every consumer (R5).
            "prediction_source": self._prediction_source,
            "actual_to_date": self._forecast.get("actual_to_date"),
            "remainder_cost": self._forecast.get("remainder_cost"),
            "remainder_days": self._forecast.get("remainder_days"),
            "fixed_charge": self._forecast.get("fixed_charge"),
            "actual_window_end": self._forecast.get("actual_window_end"),
            "cycle_end": self._cycle_end.isoformat() if self._cycle_end else None,
            "days_remaining": self._days_remaining,
            **self.ledger.attributes(
                date.fromisoformat(self._cycle_start_date)
                if self._cycle_start_date else None
            ),
            "current_effective_rate": round(self.current_effective_rate, 6),
            # PLANNING_ec_billing_emporia_counters §D7 — additive attributes.
            "billing_source_today": self._billing_source_today,
            "counter_last_update": self._counter_last_update,
            "counter_import_last": (
                self._counters.snapshot().get("counter_import_last")
                if self._counters is not None else None
            ),
            "counter_export_last": (
                self._counters.snapshot().get("counter_export_last")
                if self._counters is not None else None
            ),
            "outage_days_this_cycle": self._outage_days_this_cycle,
        }


# ============================================================================
# Energy Savings Unification (cycle #7) — peak-avoidance accumulator
# ============================================================================
# Design (see docs/planning/PLANNING_energy_savings_unification.md §D1 RE-SITE):
#
#   served_locally_kW = max(0, solar + battery_discharge - battery_charge - grid_export)
#   credit_$ = served_locally_kW × Δh × get_effective_import_rate(now)
#
# Double-count guard (operator decision #4): battery-discharged kWh already
# get their off-peak-to-displaced delta booked by arbitrage. To avoid double
# credit, the battery portion of served_locally during displaced-rate periods
# (peak / mid_peak) is credited at only `max(0, effective_rate - displaced_rate)`
# per kWh; the solar portion is credited at the full effective_rate.
#
# This class is intentionally isolated from CostTracker so a fault here cannot
# touch `cost_today` / `cost_this_cycle` (the shared billing hot-path). It is
# also independent of any specific entity plumbing — the caller passes in a
# snapshot each tick, which makes it directly unit-testable end-to-end.

_DISPLACED_PERIODS = ("peak", "mid_peak")


class PeakAvoidanceTracker:
    """Tick-level accumulator for peak-avoidance $ and kWh-avoided.

    Reset semantics mirror CostTracker (local midnight for today; the
    `_check_cycle_reset` logic for billing_cycle via the same
    `_get_cycle_start` shape).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        bill_cycle_day: int = DEFAULT_BILL_CYCLE_START_DAY,
    ) -> None:
        self.hass = hass
        self._bill_cycle_day = bill_cycle_day

        # Per-scope accumulators (all reset on their scope boundary).
        self._pa_today: float = 0.0
        self._pa_cycle: float = 0.0
        self._kwh_avoided_today: float = 0.0
        self._kwh_avoided_cycle: float = 0.0
        # Lifetime "since baseline" — cumulative from cutover. The lifetime
        # sensor renders `baseline + this` so a DB prune of the source
        # arbitrage_cycles rows cannot silently shrink the lifetime number.
        self._pa_lifetime_delta: float = 0.0
        self._kwh_avoided_lifetime_delta: float = 0.0

        self._last_date: str = ""
        self._cycle_start_date: str = ""
        self._last_accumulate_ts: float | None = None
        # B-HIGH-1/2 (fix-up): tracks the local-date on which the
        # lifetime delta was last rolled into the persisted baseline row.
        # See pop_lifetime_delta_for_rollup().
        self._last_lifetime_rollup_date: str = ""

    # -- reset scaffolding (mirrors CostTracker._check_cycle_reset shape) --

    def _get_cycle_start(self, now: datetime) -> date:
        day = self._bill_cycle_day
        if now.day >= day:
            return now.date().replace(day=day)
        first_of_month = now.date().replace(day=1)
        last_month = first_of_month - timedelta(days=1)
        try:
            return last_month.replace(day=day)
        except ValueError:
            return last_month

    def set_bill_cycle_day(self, day: int, now: datetime) -> bool:
        """EC-BILL-CYCLE-DAY-WIRED-1: re-key the cycle without zeroing.

        PA has no per-day DB source, so the running cycle totals are kept
        (they may include the shifted day(s)); the next real boundary of the
        new day resets them cleanly. Returns True when the day changed.
        """
        if day == self._bill_cycle_day:
            return False
        self._bill_cycle_day = day
        if self._cycle_start_date:
            self._cycle_start_date = self._get_cycle_start(now).isoformat()
        return True

    def _maybe_reset(self, now: datetime) -> None:
        today = now.date().isoformat()
        if today != self._last_date:
            self._pa_today = 0.0
            self._kwh_avoided_today = 0.0
            self._last_date = today
        cycle_key = self._get_cycle_start(now).isoformat()
        if cycle_key != self._cycle_start_date:
            self._pa_cycle = 0.0
            self._kwh_avoided_cycle = 0.0
            self._cycle_start_date = cycle_key
            _LOGGER.info(
                "Peak-avoidance billing cycle reset: new cycle started %s",
                cycle_key,
            )

    # -- core accumulator --------------------------------------------------

    def accumulate(
        self,
        *,
        now: datetime,
        solar_kw: float | None,
        battery_power_kw: float | None,  # + charging, - discharging
        net_import_kw: float | None,  # + importing, - exporting
        effective_rate: float,
        displaced_rate: float,
        period: str | None,
    ) -> None:
        """Accumulate one tick of peak-avoidance value.

        All inputs are already in kW / $/kWh. Guarded — a bad input silently
        skips this tick rather than propagating any exception up into the
        decision cycle.
        """
        # Derive elapsed from the passed-in `now` (test-friendly — a fake
        # clock is threaded through by advancing `now`). Production always
        # supplies dt_util.now(); a None `now` is treated as a no-op tick
        # (mirrors the net_import guard below — never fabricate time).
        # LOW-1 (fix-up): removed the wall-clock fallback branch (dead;
        # never exercised in production and would have inflated elapsed
        # across a restart).
        if now is None:
            return
        now_ts = now.timestamp()
        self._maybe_reset(now)

        if self._last_accumulate_ts is None:
            self._last_accumulate_ts = now_ts
            return
        elapsed_h = (now_ts - self._last_accumulate_ts) / 3600.0
        self._last_accumulate_ts = now_ts
        if elapsed_h <= 0 or elapsed_h > 1:
            return

        try:
            solar_kw = max(0.0, float(solar_kw or 0.0))
            bp = float(battery_power_kw) if battery_power_kw is not None else 0.0
            discharge_kw = max(0.0, -bp)
            charge_kw = max(0.0, bp)
            # A-HIGH-1 (fix-up): mirror CostTracker.accumulate's None-guard
            # (energy_billing.py ~:244-246). Treating unknown grid flow as 0
            # would credit real EXPORT as served-locally during Envoy blind
            # windows (up to 50% over-credit). Skip the tick instead.
            if net_import_kw is None:
                return
            net = float(net_import_kw)
            export_kw = max(0.0, -net)

            served_kw = max(
                0.0,
                solar_kw + discharge_kw - charge_kw - export_kw,
            )
            if served_kw < PEAK_AVOIDANCE_MIN_SERVED_KW:
                return

            # Attribute the served-locally kW between battery-discharge and
            # solar. Battery gets attributed first (bounded by discharge_kw)
            # because that's the portion the double-count guard applies to.
            battery_served_kw = min(served_kw, discharge_kw)
            solar_served_kw = served_kw - battery_served_kw

            rate = float(effective_rate or 0.0)
            if period in _DISPLACED_PERIODS:
                # Decision #4 guard: arbitrage-discharged kWh already booked
                # the (displaced - off_peak) delta. Credit only the residual
                # (effective_rate - displaced_rate), clamped >= 0.
                battery_credit_per_kwh = max(
                    0.0, rate - float(displaced_rate or 0.0)
                )
            else:
                battery_credit_per_kwh = rate

            energy_kwh = served_kw * elapsed_h
            battery_energy_kwh = battery_served_kw * elapsed_h
            solar_energy_kwh = solar_served_kw * elapsed_h

            credit = (
                solar_energy_kwh * rate
                + battery_energy_kwh * battery_credit_per_kwh
            )
            if credit < 0:
                return  # defensive — should never happen with the clamps

            self._pa_today += credit
            self._pa_cycle += credit
            self._pa_lifetime_delta += credit
            self._kwh_avoided_today += energy_kwh
            self._kwh_avoided_cycle += energy_kwh
            self._kwh_avoided_lifetime_delta += energy_kwh
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("PeakAvoidanceTracker.accumulate skipped: %s", exc)

    # -- read-side ---------------------------------------------------------

    @property
    def peak_avoidance_today(self) -> float:
        return round(self._pa_today, 4)

    @property
    def peak_avoidance_cycle(self) -> float:
        return round(self._pa_cycle, 4)

    @property
    def peak_avoidance_lifetime_delta(self) -> float:
        return round(self._pa_lifetime_delta, 4)

    @property
    def kwh_avoided_today(self) -> float:
        return round(self._kwh_avoided_today, 4)

    @property
    def kwh_avoided_cycle(self) -> float:
        return round(self._kwh_avoided_cycle, 4)

    @property
    def kwh_avoided_lifetime_delta(self) -> float:
        return round(self._kwh_avoided_lifetime_delta, 4)

    METHODOLOGY: str = (
        "Peak-avoidance counterfactual: for each decision tick, credit "
        "served_locally_kW × Δh × effective_import_rate(now), where "
        "served_locally = max(0, solar + battery_discharge - battery_charge "
        "- grid_export). Double-count guard: during peak/mid_peak, the "
        "battery-served portion is credited only at max(0, effective_rate - "
        "displaced_rate) since arbitrage already booked the "
        "(displaced - off_peak) delta on that kWh. Ticks below "
        f"{PEAK_AVOIDANCE_MIN_SERVED_KW} kW served-locally are ignored as "
        "noise floor. Display-only; not billing-grade."
    )

    # -- restart persistence (mirrors CostTracker.restore_daily idiom) -----
    #
    # B-HIGH-1 / B-HIGH-2 (fix-up): without these, every HA restart wiped
    # peak_avoidance_today/_cycle and the lifetime_delta -> lifetime sensor
    # dropped to just the baseline row. Snapshot save+restore mirrors the
    # CostTracker daily/cycle idiom (energy_billing.py:325-351 +
    # :304-324); lifetime is preserved via pop_lifetime_delta_for_rollup()
    # which the coordinator writes into the savings_lifetime_baseline row
    # once/day at local midnight (writes = 2/day, not per-tick — respects
    # v5.2.1 write-flood lesson).

    def snapshot_state(self) -> dict[str, Any]:
        """Return an opaque snapshot dict for persistence."""
        return {
            "snapshot_date": self._last_date,
            "cycle_start_date": self._cycle_start_date,
            "pa_today": round(self._pa_today, 6),
            "pa_cycle": round(self._pa_cycle, 6),
            "kwh_avoided_today": round(self._kwh_avoided_today, 6),
            "kwh_avoided_cycle": round(self._kwh_avoided_cycle, 6),
            "pa_lifetime_delta": round(self._pa_lifetime_delta, 6),
            "kwh_avoided_lifetime_delta": round(
                self._kwh_avoided_lifetime_delta, 6
            ),
            "last_lifetime_rollup_date": self._last_lifetime_rollup_date,
        }

    def restore_snapshot(self, snapshot: dict[str, Any] | None) -> None:
        """Restore PA accumulators from a prior snapshot.

        `today`/`cycle` are only restored if their scope key matches current
        wall-time scope (so a stale snapshot from a prior day/cycle doesn't
        contaminate current-scope numbers). `lifetime_delta` is always
        restored — it's monotonic between midnight rollups.
        """
        if not snapshot:
            return
        try:
            now = dt_util.now()
            today = now.date().isoformat()
            cycle_key = self._get_cycle_start(now).isoformat()

            snap_date = snapshot.get("snapshot_date") or ""
            snap_cycle = snapshot.get("cycle_start_date") or ""

            if snap_date == today:
                self._pa_today = float(snapshot.get("pa_today", 0.0) or 0.0)
                self._kwh_avoided_today = float(
                    snapshot.get("kwh_avoided_today", 0.0) or 0.0
                )
                self._last_date = today
            if snap_cycle == cycle_key:
                self._pa_cycle = float(snapshot.get("pa_cycle", 0.0) or 0.0)
                self._kwh_avoided_cycle = float(
                    snapshot.get("kwh_avoided_cycle", 0.0) or 0.0
                )
                self._cycle_start_date = cycle_key

            # Lifetime delta is always restored (monotonic between midnight
            # rollups; coordinator will fold it into the baseline row on
            # the next local-midnight boundary).
            self._pa_lifetime_delta = float(
                snapshot.get("pa_lifetime_delta", 0.0) or 0.0
            )
            self._kwh_avoided_lifetime_delta = float(
                snapshot.get("kwh_avoided_lifetime_delta", 0.0) or 0.0
            )
            self._last_lifetime_rollup_date = (
                snapshot.get("last_lifetime_rollup_date") or ""
            )
            _LOGGER.info(
                "Restored peak-avoidance snapshot: today=$%.4f cycle=$%.4f "
                "lifetime_delta=$%.4f",
                self._pa_today, self._pa_cycle, self._pa_lifetime_delta,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "PeakAvoidanceTracker.restore_snapshot failed", exc_info=True
            )

    def pop_lifetime_delta_for_rollup(
        self, today_iso: str
    ) -> tuple[float, float] | None:
        """Return (usd_delta, kwh_delta) once per local-date, else None.

        Called by the coordinator at local-midnight snapshot time. If a
        rollup has already been done for `today_iso`, returns None (idempotent
        — enforces the 2-writes/day cap even if called on the per-3-cycle
        cadence). On success, zeros the in-RAM deltas so the lifetime sensor
        continues to render `baseline + delta` monotonically.
        """
        if not today_iso or today_iso == self._last_lifetime_rollup_date:
            return None
        usd = self._pa_lifetime_delta
        kwh = self._kwh_avoided_lifetime_delta
        if usd <= 0.0 and kwh <= 0.0:
            # Nothing to roll — still mark date to avoid re-checking every
            # cycle for the rest of the day.
            self._last_lifetime_rollup_date = today_iso
            return None
        self._pa_lifetime_delta = 0.0
        self._kwh_avoided_lifetime_delta = 0.0
        self._last_lifetime_rollup_date = today_iso
        return (usd, kwh)

    def get_status(self) -> dict[str, Any]:
        return {
            "peak_avoidance_today": self.peak_avoidance_today,
            "peak_avoidance_cycle": self.peak_avoidance_cycle,
            "peak_avoidance_lifetime_delta": self.peak_avoidance_lifetime_delta,
            "kwh_avoided_today": self.kwh_avoided_today,
            "kwh_avoided_cycle": self.kwh_avoided_cycle,
            "kwh_avoided_lifetime_delta": self.kwh_avoided_lifetime_delta,
            "methodology": self.METHODOLOGY,
        }


# =============================================================================
# EC-BILL-UTILITY-DIVERGENCE-FROM-STATS-1 — utility hourly statistics pricing
# (PLANNING_ec_bill_divergence_from_smarthub_stats.md D1/D2, Rev 2).
#
# Pure helpers (no hass): the coordinator fetches the recorder rows on the
# recorder executor and hands them here. Pricing goes through the SAME
# ``TOURateEngine`` functions counter mode uses (``get_effective_import_rate``
# / ``get_export_rate``, see ``CostTracker.accumulate`` counter branch), one
# call per hour at the hour-start LOCAL datetime: TOU by reference, no rate
# caching.
# =============================================================================


def _utility_row_start_local(row: dict, tz) -> datetime | None:
    """Hour-start of a recorder ``StatisticsRow`` as a local datetime.

    ``StatisticsRow["start"]`` is a float UTC timestamp in current HA
    (``recorder/statistics.py`` BaseStatisticsRow); a datetime is accepted
    defensively.
    """
    start = row.get("start")
    if start is None:
        return None
    if isinstance(start, datetime):
        if start.tzinfo is None:
            start = start.replace(tzinfo=dt_util.UTC)
        return start.astimezone(tz)
    try:
        return datetime.fromtimestamp(float(start), tz)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def price_hourly_utility_rows(
    rows_imp: list[dict] | None,
    rows_exp: list[dict] | None,
    tou: Any,
    tz,
    complete_last_hour: int | None = None,
) -> dict[date, dict[str, Any]]:
    """Price hourly utility ``change`` rows per LOCAL date.

    Returns ``{local_date: {imp_kwh, imp_cost, exp_kwh, exp_credit, hours,
    complete}}``. ``hours`` counts import rows for that date (23 / 24 / 25 on
    DST days). ``complete`` is True when the import series holds the date's
    local ``complete_last_hour`` (default ``UTILITY_DAY_COMPLETE_LAST_HOUR``)
    row; DST-safe, both 23- and 25-row days carry 23:00.
    """
    from .energy_const import UTILITY_DAY_COMPLETE_LAST_HOUR

    if complete_last_hour is None:
        complete_last_hour = UTILITY_DAY_COMPLETE_LAST_HOUR
    days: dict[date, dict[str, Any]] = {}

    def _day(d: date) -> dict[str, Any]:
        rec = days.get(d)
        if rec is None:
            rec = {
                "imp_kwh": 0.0, "imp_cost": 0.0,
                "exp_kwh": 0.0, "exp_credit": 0.0,
                "hours": 0, "complete": False,
            }
            days[d] = rec
        return rec

    for row in rows_imp or []:
        local = _utility_row_start_local(row, tz)
        if local is None:
            continue
        rec = _day(local.date())
        rec["hours"] += 1
        if local.hour == complete_last_hour:
            rec["complete"] = True
        kwh = row.get("change")
        if kwh is None:
            continue
        kwh = float(kwh)
        rec["imp_kwh"] += kwh
        rec["imp_cost"] += kwh * tou.get_effective_import_rate(local)

    for row in rows_exp or []:
        local = _utility_row_start_local(row, tz)
        if local is None:
            continue
        kwh = row.get("change")
        if kwh is None:
            continue
        kwh = float(kwh)
        rec = _day(local.date())
        rec["exp_kwh"] += kwh
        rec["exp_credit"] += kwh * tou.get_export_rate(local)

    return days


def utility_window_end(priced: dict[date, dict[str, Any]]) -> date | None:
    """Day AFTER the newest local date the utility series covers completely.

    None when no date is complete. A newer partial day (mid-day import) never
    advances the window.
    """
    complete = [d for d, rec in priced.items() if rec.get("complete")]
    if not complete:
        return None
    return max(complete) + timedelta(days=1)


def sum_utility_window(
    priced: dict[date, dict[str, Any]], start: date, end: date,
) -> dict[str, Any]:
    """Totals of ``priced`` over the local dates ``[start, end)``."""
    out: dict[str, Any] = {
        "days": 0, "import_kwh": 0.0, "import_cost": 0.0,
        "export_kwh": 0.0, "export_credit": 0.0,
    }
    for d, rec in priced.items():
        if start <= d < end:
            out["days"] += 1
            out["import_kwh"] += rec["imp_kwh"]
            out["import_cost"] += rec["imp_cost"]
            out["export_kwh"] += rec["exp_kwh"]
            out["export_credit"] += rec["exp_credit"]
    out["net_cost"] = out["import_cost"] - out["export_credit"]
    return out


def service_charge(tou: Any) -> float:
    """Monthly service-availability charge: rate file first, PEC constant fallback.

    Single producer for the bill's fixed charge (A-M2 rule): used by the
    predictor and by the coordinator's `last_cycle.utility_bill_estimate`.
    """
    svc = getattr(tou, "service_availability_monthly", None)
    if isinstance(svc, bool) or not isinstance(svc, (int, float)):
        svc = PEC_FIXED_CHARGES["service_availability"]
    return float(svc)


def daily_net_from_priced(
    priced: dict[date, dict[str, Any]], end: date | None,
) -> dict[str, float]:
    """``{iso_date: net $}`` for priced dates before ``end`` (exclusive).

    Same arithmetic as ``sum_utility_window`` (import cost - export credit),
    per day, so the remainder forecast reads the series the actual reads.
    """
    if end is None:
        return {}
    return {
        d.isoformat(): rec["imp_cost"] - rec["exp_credit"]
        for d, rec in priced.items()
        if d < end
    }


def forecast_remainder(
    daily_net: dict[date, float],
    cutoff: date,
    rem_start: date,
    rem_end: date,
    weeks: int = BILL_FORECAST_DOW_WEEKS,
    trailing_days: int = BILL_FORECAST_TRAILING_DAYS,
) -> float | None:
    """P3 remainder: each day in ``[rem_start, rem_end)`` priced at the mean of
    the same weekday over the last ``weeks`` weeks (only days before
    ``cutoff``, i.e. already covered by the utility series); a day with no
    such history uses the mean of the ``trailing_days`` before ``cutoff``.
    None when a day can be priced by neither.
    """
    trail = [
        daily_net[cutoff - timedelta(days=k)]
        for k in range(1, trailing_days + 1)
        if (cutoff - timedelta(days=k)) in daily_net
    ]
    trail_mean = sum(trail) / len(trail) if trail else None
    total = 0.0
    d = rem_start
    while d < rem_end:
        same_dow = []
        for k in range(1, weeks + 1):
            src = d - timedelta(days=7 * k)
            if src < cutoff and src in daily_net:
                same_dow.append(daily_net[src])
        if same_dow:
            total += sum(same_dow) / len(same_dow)
        elif trail_mean is not None:
            total += trail_mean
        else:
            return None
        d += timedelta(days=1)
    return total


def compute_bill_forecast(
    *,
    cycle_start: date,
    next_cycle_start: date,
    today: date,
    cache: dict[str, Any],
    svc: float,
) -> dict[str, Any] | None:
    """Predicted bill = utility cost to date + remainder forecast + svc once.

    The actual-to-date is the coordinator's published ``current.utility_net_cost``
    (no svc). Remaining days start at the utility window end (R2), not today:
    the window lags by a day or more and never holds a partial day. Before the
    window reaches the cycle start (R3) the actual is 0 and the whole cycle is
    forecast. None when the utility series has no complete day or a remaining
    day cannot be priced.
    """
    window_end_iso = cache.get("window_end")
    if not window_end_iso:
        return None
    cutoff = min(date.fromisoformat(window_end_iso), today)
    cur = cache.get("current")
    if cur:
        actual = float(cur.get("utility_net_cost") or 0.0)
        cutoff = date.fromisoformat(cur["window_end"])
    else:
        actual = 0.0
    rem_start = max(cutoff, cycle_start)
    daily_net = {
        date.fromisoformat(k): float(v)
        for k, v in (cache.get("daily_net") or {}).items()
    }
    remainder = forecast_remainder(daily_net, cutoff, rem_start, next_cycle_start)
    if remainder is None:
        return None
    actual = round(actual, 2)
    remainder = round(remainder, 2)
    fixed = round(float(svc), 2)
    return {
        "predicted": round(actual + remainder + fixed, 2),
        "actual_to_date": actual,
        "remainder_cost": remainder,
        "remainder_days": (next_cycle_start - rem_start).days,
        "fixed_charge": fixed,
        "actual_window_end": cutoff.isoformat(),
    }


def _pct_error(predicted: float, actual: float) -> float:
    # Same bounded reference as `_utility_pct`: a near-zero (net-export) bill
    # cannot blow the percentage up.
    return (predicted - actual) / max(abs(actual), 1.0) * 100.0


class BillForecastLedger:
    """Daily prediction snapshots per cycle, scored at cycle close (D2).

    Persisted as JSON in ``energy_state`` by the coordinator. Each cycle:
    ``{cycle_start, next_cycle_start, snapshots: {day: {predicted,
    actual_window_end}}, status: open|scored|unscored, actual,
    utility_net_cost, ec_net_cost, errors: {horizon: signed %}}``.
    """

    def __init__(self) -> None:
        self.cycles: list[dict[str, Any]] = []

    def _cycle(self, cycle_start: date) -> dict[str, Any] | None:
        key = cycle_start.isoformat()
        for c in self.cycles:
            if c["cycle_start"] == key:
                return c
        return None

    def record_snapshot(
        self,
        cycle_start: date,
        next_cycle_start: date,
        day_of_cycle: int,
        predicted: float,
        actual_window_end: str | None,
    ) -> bool:
        """One snapshot per local day; returns False (no change) on a repeat."""
        c = self._cycle(cycle_start)
        if c is None:
            c = {
                "cycle_start": cycle_start.isoformat(),
                "next_cycle_start": next_cycle_start.isoformat(),
                "snapshots": {},
                "status": "open",
                "actual": None,
                "errors": {},
            }
            self.cycles.append(c)
            self.cycles.sort(key=lambda x: x["cycle_start"])
            del self.cycles[:-BILL_LEDGER_MAX_CYCLES]
            if c not in self.cycles:
                return False
        if c["status"] != "open":
            return False
        key = str(int(day_of_cycle))
        if key in c["snapshots"]:
            return False
        c["snapshots"][key] = {
            "predicted": predicted,
            "actual_window_end": actual_window_end,
        }
        return True

    def try_close(self, today: date, last_cycle: dict[str, Any] | None) -> bool:
        """Score open cycles that have ended (I4, R4).

        Scored only from a utility ``last_cycle`` block covering exactly
        ``[cycle_start, next_cycle_start)``. Not covered by
        ``next_cycle_start + BILL_LEDGER_SCORE_DEADLINE_DAYS`` -> unscored.
        A lagging or stale refresh before the deadline leaves the cycle open.
        """
        changed = False
        for c in self.cycles:
            if c["status"] != "open":
                continue
            nxt = date.fromisoformat(c["next_cycle_start"])
            if today < nxt:
                continue
            covered = (
                last_cycle is not None
                and last_cycle.get("window_start") == c["cycle_start"]
                and last_cycle.get("window_end") == c["next_cycle_start"]
                and last_cycle.get("utility_bill_estimate") is not None
            )
            if covered:
                actual = float(last_cycle["utility_bill_estimate"])
                c["actual"] = actual
                c["utility_net_cost"] = last_cycle.get("utility_net_cost")
                c["ec_net_cost"] = last_cycle.get("ec_net_cost")
                c["errors"] = {
                    str(h): round(
                        _pct_error(c["snapshots"][str(h)]["predicted"], actual), 1,
                    )
                    for h in BILL_ACCURACY_HORIZONS
                    if str(h) in c["snapshots"]
                }
                c["status"] = "scored"
                changed = True
            elif today >= nxt + timedelta(days=BILL_LEDGER_SCORE_DEADLINE_DAYS):
                c["status"] = "unscored"
                c["actual"] = None
                c["errors"] = {}
                changed = True
        return changed

    def attributes(self, cycle_start: date | None = None) -> dict[str, Any]:
        scored = [c for c in self.cycles if c["status"] == "scored"]
        mape: dict[int, float] = {}
        for h in BILL_ACCURACY_HORIZONS:
            vals = [abs(c["errors"][str(h)]) for c in scored if str(h) in c["errors"]]
            if vals:
                mape[h] = round(sum(vals) / len(vals), 1)
        last = scored[-1] if scored else None
        current = self._cycle(cycle_start) if cycle_start else None
        return {
            "accuracy_mape_by_horizon": mape,
            "accuracy_cycles_scored": len(scored),
            "last_cycle_actual": last["actual"] if last else None,
            "last_cycle_error_by_horizon": (
                {int(k): v for k, v in last["errors"].items()} if last else {}
            ),
            "ledger_days_this_cycle": len(current["snapshots"]) if current else 0,
        }

    def to_json(self) -> str:
        import json
        return json.dumps({"v": 1, "cycles": self.cycles}, sort_keys=True)

    def load_json(self, raw: str | None) -> None:
        """Restore; a malformed payload leaves the ledger empty."""
        import json
        if not raw:
            return
        try:
            data = json.loads(raw)
            cycles = data.get("cycles")
            if isinstance(cycles, list):
                self.cycles = [c for c in cycles if isinstance(c, dict)][-BILL_LEDGER_MAX_CYCLES:]
        except (ValueError, TypeError, AttributeError):
            _LOGGER.debug("bill forecast ledger restore: bad payload", exc_info=True)


def tou_import_rate_floor(tou: Any, day: date, tz) -> float:
    """Lowest effective import rate the TOU engine returns on ``day``.

    Asks the engine for each local hour of the date (no new rate literal).
    """
    return min(
        tou.get_effective_import_rate(
            datetime(day.year, day.month, day.day, h, tzinfo=tz)
        )
        for h in range(24)
    )


def _utility_pct(diff: float, a: float, b: float) -> float:
    # Same reference as the legacy entity branch (energy.py
    # utility_meter_divergence): max(|utility|, |ec|, 1.0).
    return diff / max(abs(a), abs(b), 1.0) * 100.0


def build_utility_divergence_block(
    window_start: date,
    window_end: date,
    utility: dict[str, Any],
    ec: dict[str, Any],
    ec_underpriced_days: int | None,
    export_configured: bool,
) -> dict[str, Any]:
    """Same-window utility-vs-EC comparison block.

    Sign: utility minus EC (positive = EC under-counts).
    """
    u_imp = float(utility.get("import_kwh") or 0.0)
    u_net = float(utility.get("net_cost") or 0.0)
    e_imp = float(ec.get("import_kwh") or 0.0)
    e_net = float(ec.get("net_cost") or 0.0)
    d_kwh = u_imp - e_imp
    d_cost = u_net - e_net
    block: dict[str, Any] = {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "utility_days": int(utility.get("days") or 0),
        "ec_days": int(ec.get("days") or 0),
        "utility_import_kwh": round(u_imp, 2),
        "utility_import_cost": round(float(utility.get("import_cost") or 0.0), 2),
        "utility_net_cost": round(u_net, 2),
        "ec_import_kwh": round(e_imp, 2),
        "ec_export_kwh": round(float(ec.get("export_kwh") or 0.0), 2),
        "ec_net_cost": round(e_net, 2),
        "divergence_kwh": round(d_kwh, 2),
        "divergence_kwh_pct": round(_utility_pct(d_kwh, u_imp, e_imp), 1),
        "divergence_cost": round(d_cost, 2),
        "divergence_cost_pct": round(_utility_pct(d_cost, u_net, e_net), 1),
        "ec_underpriced_days": ec_underpriced_days,
    }
    # A-M1 fix-up: an EC side with no energy_daily rows in the window (DB
    # unavailable or no rows) is "no data", not "EC = 0". Publishing would
    # report a spurious +/-100 % divergence; publish None instead.
    if int(ec.get("days") or 0) <= 0:
        for _k in ("divergence_kwh", "divergence_kwh_pct",
                   "divergence_cost", "divergence_cost_pct"):
            block[_k] = None
    if export_configured:
        block["utility_export_kwh"] = round(
            float(utility.get("export_kwh") or 0.0), 2,
        )
        block["utility_export_credit"] = round(
            float(utility.get("export_credit") or 0.0), 2,
        )
    return block
