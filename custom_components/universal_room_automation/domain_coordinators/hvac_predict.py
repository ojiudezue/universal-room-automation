"""Predictive sensors and weather pre-conditioning for HVAC Coordinator.

Generates pre-cool/pre-heat likelihood, comfort violation risk,
per-zone demand, and daily outcome measurements.

v3.8.5-H4: Initial implementation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .hvac_const import (
    DEFAULT_ENERGY_PRECOOL_OFFSET,
    DEFAULT_ENERGY_PRECOOL_SCOPE,
    ENERGY_PRECOOL_EXPORT_THRESHOLD_W,
    ENERGY_PRECOOL_HOUR_START,
    ENERGY_PRECOOL_SCOPE_AUTO_PV_TIERED,
    ENERGY_PRECOOL_SCOPE_OCCUPIED_ONLY,
    ENERGY_PRECOOL_SCOPE_VALUES,
    ENERGY_PRECOOL_SCOPE_WHOLE_HOUSE,
    MIN_DEADBAND,
    SEASON_SHOULDER,
    SEASON_SUMMER,
    SEASON_WINTER,
    SEASONAL_DEFAULTS,
    SOLAR_BANK_FLOOR,
    SOLAR_BANK_SOC_MIN,
)
from .hvac_override import OverrideArrester
from .hvac_preset import PresetManager
from .hvac_setpoint import apply_setpoint_guards, emit_set_temperature
from .hvac_zones import ZoneManager
from .signals import EnergyConstraint

_LOGGER = logging.getLogger(__name__)

# Pre-conditioning thresholds
PRECOOL_FORECAST_HIGH: float = 90.0  # F — trigger pre-cool above this
PREHEAT_FORECAST_LOW: float = 35.0  # F — trigger pre-heat below this
PRECOOL_SOC_MIN: int = 30  # % — minimum battery SOC to allow pre-cool
PEAK_HOUR_START: int = 14  # 2PM — peak window start
PEAK_HOUR_END: int = 19  # 7PM — peak window end
PRECOOL_LEAD_HOURS: int = 2  # hours before peak to start pre-cooling
PREHEAT_LEAD_HOURS: int = 1  # hours before off-peak ends to start pre-heating
OFF_PEAK_END_HOUR: int = 6  # 6AM — typical off-peak end


@dataclass
class HVACOutcome:
    """Daily outcome measurement for HVAC performance."""

    date: str
    zone_satisfaction_pct: float  # % of cycle checks where zones were in-band
    total_overrides: int
    total_ac_resets: int
    energy_mode_minutes: dict[str, int]  # mode -> minutes spent in that mode
    pre_cool_triggered: bool
    pre_heat_triggered: bool


class HVACPredictor:
    """Generates predictive HVAC data and triggers pre-conditioning.

    Called from the HVAC decision cycle every 5 minutes.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        zone_manager: ZoneManager,
        preset_manager: PresetManager,
        override_arrester: OverrideArrester | None = None,
        net_power_entity: str | None = None,
        # v4.5.10: 3 new tunables (was hardcoded module constants)
        solar_bank_floor: float = SOLAR_BANK_FLOOR,
        solar_bank_soc_min: int = SOLAR_BANK_SOC_MIN,
        precool_forecast_high: float = PRECOOL_FORECAST_HIGH,
        preheat_forecast_low: float = PREHEAT_FORECAST_LOW,
    ) -> None:
        """Initialize predictor.

        v4.2.29: net_power_entity is optional. When None (e.g., Energy
        Coordinator disabled or envoy validation failed), solar-banking
        decisions cannot read live net power and are skipped — fail-safe
        rather than reading from a wrong-serial fallback that resolves to
        a non-existent entity.
        """
        self.hass = hass
        self._zone_manager = zone_manager
        self._preset_manager = preset_manager
        self._override_arrester = override_arrester

        # Current predictions
        self._pre_cool_likelihood: int = 0
        self._comfort_violation_risk: str = "low"
        self._zone_demand: dict[str, str] = {}  # zone_id -> "low"|"medium"|"high"

        # Pre-conditioning state
        self._pre_cool_active: bool = False
        self._pre_heat_active: bool = False
        self._pre_cool_triggered_today: bool = False
        self._pre_heat_triggered_today: bool = False

        # Daily outcome tracking
        self._in_band_checks: int = 0
        self._total_checks: int = 0
        self._energy_mode_start: str = ""
        self._energy_mode_minutes: dict[str, int] = {}
        self._last_outcome_date: str = ""
        self._last_outcome: HVACOutcome | None = None

        # Outdoor temp sensor
        self._outdoor_temp_entity: str = ""

        # v4.7.8 D8: EgressManager reference (set via set_egress_manager).
        # Used to skip predictive set_temperature dispatch for paused zones.
        self._egress_manager = None

        # v3.17.0: Zone-specific pre-conditioning tracking
        self._pre_conditioning_zones: set[str] = set()

        # Pre-arrival fan visibility (consumed by diagnostic sensor)
        self._last_fan_activation_rooms: list[str] = []
        self._last_fan_skipped_rooms: list[dict[str, Any]] = []
        self._energy_precool_zones: set[str] = set()  # v5.7.1 rename
        # v5.7.1 fix-up (LOW): dropped dead `_solar_bank_triggered_today`.
        self._net_power_entity: str | None = net_power_entity or None
        # v4.5.10: configurable tunables (URA mirror pattern: install-time
        # seeds; future Number entities can write to these instance attrs).
        self._solar_bank_floor: float = float(solar_bank_floor)
        self._solar_bank_soc_min: int = int(solar_bank_soc_min)
        self._precool_forecast_high: float = float(precool_forecast_high)
        self._preheat_forecast_low: float = float(preheat_forecast_low)
        # v5.7.1: renamed banking trackers -> pre-cool trackers.
        self._last_precool_gate_enabled: bool = True
        self._last_precool_zones: set[str] = set()
        # Tier 1 review HIGH-1: one-shot post-restart reconciliation flag.
        # `_last_banked_zones` is RAM-only — a restart mid-bank with the
        # gate subsequently flipped OFF would never release. On the first
        # eval after startup, if gate is OFF and any zone's live setpoints
        # are below baseline by > 0.5°F (in the banking direction), treat
        # them as banked-and-orphaned and release them once.
        self._first_eval_done: bool = False
        # HC pre-conditioning master gate (parent of weather/banking/
        # pre-arrival/pre-heat). Tracks last-cycle gate state + last-cycle
        # in-flight pre-conditioning zones so a mid-window flip-OFF can
        # release zones to baseline within ONE cycle (operator-required
        # parity with the solar banking sibling toggle). See
        # PLANNING_hc_precool_toggle_oc_observability.md (D1 disposition).
        self._last_pre_conditioning_gate_enabled: bool = True
        self._last_pre_conditioning_zones: set[str] = set()
        # Tier 1 review CRITICAL-1: HVAC coordinator backref so the
        # release path can source the TRUE baseline (`_last_emitted_range`)
        # rather than the LIVE thermostat setpoints (which already
        # reflect the banked values — a same-cycle re-write would be a
        # no-op). Wired post-construction via `set_hvac_coord`.
        self._hvac_coord = None

    def set_outdoor_temp_entity(self, entity_id: str) -> None:
        """Set outdoor temperature sensor entity."""
        self._outdoor_temp_entity = entity_id

    def set_hvac_coord(self, hvac_coord) -> None:
        """Wire HVAC coordinator backref.

        Tier 1 review CRITICAL-1: the banking release path reads
        `hvac_coord._last_emitted_range` to recover the TRUE baseline
        for each zone (last URA-emitted preset range). Falls back to
        preset-resolved baseline when the map has no entry.
        """
        self._hvac_coord = hvac_coord

    def _freeze_active(self) -> bool:
        """Current freeze-active state from HC; False when unwired.

        feature/freeze-floor: predictive setpoint emissions (banking restore,
        pre-cool, pre-heat) pass this to the chokepoint so they inherit the
        freeze floor. None-safe (freeze treated inactive before wiring).
        """
        coord = self._hvac_coord
        return bool(getattr(coord, "freeze_active", False)) if coord else False

    def set_egress_manager(self, egress_manager) -> None:
        """v4.7.8 D8: Wire EgressManager so predictive set_temperature
        dispatches can skip zones we paused via the egress feature.
        """
        self._egress_manager = egress_manager

    def flush_daily_outcome(self) -> None:
        """Store yesterday's outcome before zone counters are reset.

        Called from hvac.py's daily reset block so zone override/reset
        counts are captured before ZoneManager.reset_daily_counters() zeros them.
        """
        if self._last_outcome_date:
            self._store_daily_outcome()

    async def update(
        self,
        energy_constraint: EnergyConstraint | None,
        house_state: str,
        pre_arrival_zones: set[str] | None = None,
        zone_intelligence_enabled: bool = True,
    ) -> None:
        """Run prediction cycle.

        Called from the HVAC decision cycle every 5 minutes.
        """
        now = dt_util.now()

        # Daily reset (outcome storage is done via flush_daily_outcome()
        # called from hvac.py before zone counters are zeroed)
        today = now.date().isoformat()
        if today != self._last_outcome_date:
            self._last_outcome_date = today
            self._in_band_checks = 0
            self._total_checks = 0
            self._energy_mode_minutes.clear()
            self._pre_cool_triggered_today = False
            self._pre_heat_triggered_today = False
            self._pre_cool_active = False
            self._pre_heat_active = False
            # v5.7.1 fix-up (LOW): _solar_bank_triggered_today removed.

        # Cycle EC/HC reboot pickup — D2 #12. One-shot post-restart pass:
        # derive triggered_today flags from the clock so we do not re-fire
        # a daily-once trigger after rebooting past its window. Pure
        # function of current time + completion semantics; mirrors v5.3.7
        # always-register philosophy (idempotent re-eval).
        # NOTE: `_reboot_pickup_done` is lazily declared on the instance
        # here (not in __init__) to keep the public init body short — the
        # v4.5.10 test_predictor_has_4_v4510_runtime_fields check window is
        # 3000 chars from `def __init__` and we must not push fields past
        # it.
        if not getattr(self, "_reboot_pickup_done", False):
            self._reboot_pickup_done = True
            hour = now.hour
            # Cool window already passed today → mark triggered.
            # Inside lead window → leave False (one re-fire is acceptable).
            if hour >= PEAK_HOUR_START:
                self._pre_cool_triggered_today = True
            # Heat window already passed today (window completes before
            # OFF_PEAK_END_HOUR).
            if hour >= OFF_PEAK_END_HOUR:
                self._pre_heat_triggered_today = True
            _LOGGER.info(
                "HVAC reboot-pickup: hour=%d → cool_triggered=%s, "
                "heat_triggered=%s",
                hour, self._pre_cool_triggered_today,
                self._pre_heat_triggered_today,
            )

        # Track energy mode time
        if energy_constraint:
            mode = energy_constraint.mode
            self._energy_mode_minutes[mode] = (
                self._energy_mode_minutes.get(mode, 0) + 5
            )

        # Update predictions
        self._update_pre_cool_likelihood(energy_constraint, now)
        self._update_comfort_violation_risk(energy_constraint)
        self._update_zone_demand(now)
        self._track_zone_satisfaction()

        # Check pre-conditioning triggers (zone-specific in v3.17.0)
        await self._check_pre_conditioning(
            energy_constraint, house_state, now,
            pre_arrival_zones=pre_arrival_zones or set(),
            zone_intelligence_enabled=zone_intelligence_enabled,
        )

    def _update_pre_cool_likelihood(
        self,
        constraint: EnergyConstraint | None,
        now,
    ) -> None:
        """Compute pre-cool likelihood percentage.

        Combines: forecast high temp, TOU peak proximity, battery SOC.
        """
        likelihood = 0
        forecast_high = constraint.forecast_high_temp if constraint else None

        # Forecast temperature component (0-40%)
        # v4.5.10: threshold is now self._precool_forecast_high (configurable).
        if forecast_high is not None:
            if forecast_high >= self._precool_forecast_high + 10:
                likelihood += 40
            elif forecast_high >= self._precool_forecast_high:
                pct = (forecast_high - self._precool_forecast_high) / 10
                likelihood += int(pct * 40)

        # Time proximity to peak (0-30%)
        hour = now.hour
        hours_to_peak = PEAK_HOUR_START - hour
        if 0 < hours_to_peak <= PRECOOL_LEAD_HOURS:
            likelihood += 30
        elif hours_to_peak == 0 or (PEAK_HOUR_START <= hour < PEAK_HOUR_END):
            likelihood += 15  # Already in peak

        # Battery SOC component (0-20%)
        soc = constraint.soc if constraint else None
        if soc is not None:
            if soc < PRECOOL_SOC_MIN:
                likelihood += 20  # Low battery = more reason to pre-cool
            elif soc < 50:
                likelihood += 10

        # Season bonus (0-10%)
        season = self._preset_manager.current_season
        if season == SEASON_SUMMER:
            likelihood += 10

        self._pre_cool_likelihood = min(likelihood, 100)

    def _update_comfort_violation_risk(
        self, constraint: EnergyConstraint | None,
    ) -> None:
        """Compute comfort violation risk level.

        Based on current energy constraint mode and zone conditions.
        """
        if constraint is None or constraint.mode == "normal":
            self._comfort_violation_risk = "low"
            return

        # Check zone temperatures against setpoints
        violation_count = 0
        for zone in self._zone_manager.zones.values():
            if zone.current_temperature is None or zone.target_temp_high is None:
                continue
            delta = zone.current_temperature - zone.target_temp_high
            if delta > 2.0:
                violation_count += 1

        if violation_count >= 2 or constraint.mode == "shed":
            self._comfort_violation_risk = "high"
        elif violation_count >= 1 or constraint.mode == "coast":
            self._comfort_violation_risk = "medium"
        else:
            self._comfort_violation_risk = "low"

    def _update_zone_demand(self, now) -> None:
        """Compute per-zone demand based on outdoor trend and indoor delta."""
        outdoor_temp = self._get_outdoor_temp()
        self._zone_demand.clear()

        for zone_id, zone in self._zone_manager.zones.items():
            if zone.current_temperature is None or zone.target_temp_high is None:
                self._zone_demand[zone_id] = "unknown"
                continue

            indoor_delta = zone.current_temperature - zone.target_temp_high

            # Factor outdoor temperature
            outdoor_factor = 0
            if outdoor_temp is not None:
                if outdoor_temp > 95:
                    outdoor_factor = 2
                elif outdoor_temp > 85:
                    outdoor_factor = 1

            # Demand level
            total = indoor_delta + outdoor_factor
            if total >= 4:
                self._zone_demand[zone_id] = "high"
            elif total >= 2:
                self._zone_demand[zone_id] = "medium"
            else:
                self._zone_demand[zone_id] = "low"

    def _track_zone_satisfaction(self) -> None:
        """Track how many zones are within comfortable range."""
        self._total_checks += 1
        all_in_band = True

        for zone in self._zone_manager.zones.values():
            if zone.current_temperature is None:
                continue
            if zone.target_temp_high is not None:
                if zone.current_temperature > zone.target_temp_high + 2:
                    all_in_band = False
            if zone.target_temp_low is not None:
                if zone.current_temperature < zone.target_temp_low - 2:
                    all_in_band = False

        if all_in_band:
            self._in_band_checks += 1

    async def _check_pre_conditioning(
        self,
        constraint: EnergyConstraint | None,
        house_state: str,
        now,
        pre_arrival_zones: set[str] | None = None,
        zone_intelligence_enabled: bool = True,
    ) -> None:
        """Zone-specific pre-conditioning: weather, solar banking, pre-arrival.

        v3.17.0: Refactored to be zone-aware with floor protection on all offsets.
        When zone_intelligence_enabled is False, only weather pre-cool runs
        (pre-existing feature). Solar banking and pre-arrival are ZI features.

        v4.5.7: Per-feature gating on house_state. Solar banking now runs
        regardless of away/vacation — its design intent is "store thermal
        mass when surplus solar has nowhere better to go," which is
        independent of occupancy and most valuable when nobody's home
        (line 346 comment was correct; the unconditional early-return
        was the bug). Other pre-conditioning features (weather, pre-arrival,
        pre-heat) are occupant-comfort-driven and keep their away-skip.
        """
        hour = now.hour
        season = self._preset_manager.current_season
        pre_arrival_zones = pre_arrival_zones or set()
        is_unoccupied = house_state in ("away", "vacation")

        # Reset tracking sets each cycle
        self._pre_conditioning_zones = set()
        # v5.7.1: renamed _solar_banking_zones → _energy_precool_zones.
        self._energy_precool_zones = set()
        self._last_fan_activation_rooms = []
        self._last_fan_skipped_rooms = []
        # v5.7.1: per-cycle effective scope label (for the
        # energy_precool_scope_effective attr on the HVAC house-state
        # sensor). Default "n/a" — overwritten when the trigger fires.
        self._energy_precool_scope_effective: str = "n/a"

        # HC Pre-Conditioning master gate (D1). When the operator-facing
        # switch is OFF this short-circuits the ENTIRE pre-conditioning
        # decision chain — weather pre-cool, solar banking, pre-arrival,
        # pre-heat. Mirrors the EC Solar HVAC Banking sibling gate but at
        # a coarser (parent) level. Operator-required parity: a mid-window
        # flip-OFF must RELEASE any in-flight pre-conditioned zones to
        # their baseline range within ONE cycle (don't wait for the
        # natural peak / off-peak boundary). This mirrors
        # `_release_banked_zones` semantics for solar-banking; weather +
        # pre-arrival + pre-heat use the same baseline-write release.
        pre_cond_gate_on = self._is_pre_conditioning_enabled()
        if (
            not pre_cond_gate_on
            and self._last_pre_conditioning_gate_enabled
            and (
                self._last_pre_conditioning_zones
                or self._last_precool_zones
                or self._pre_cool_active
                or self._pre_heat_active
            )
        ):
            # Operator just flipped OFF mid-pre-cool/pre-heat → release
            # everything once. Includes the energy-pre-cool tracked set
            # so the parent gate is authoritative even over the EC-owned
            # energy-pre-cool gate (defense in depth: master "28" remains
            # the kill-switch above the unified pre-cool path).
            release_set = (
                set(self._last_pre_conditioning_zones)
                | set(self._last_precool_zones)
            )
            if release_set:
                await self._release_banked_zones(release_set)
            self._last_pre_conditioning_zones = set()
            self._last_precool_zones = set()
            # Clear in-flight flags so the natural peak/off-peak boundary
            # check doesn't double-release on a later cycle.
            if self._pre_cool_active:
                self._pre_cool_active = False
                _LOGGER.info(
                    "HVAC Pre-cool released: pre-conditioning master OFF",
                )
            if self._pre_heat_active:
                self._pre_heat_active = False
                _LOGGER.info(
                    "HVAC Pre-heat released: pre-conditioning master OFF",
                )
            # A-HIGH-1: also clear the daily-once "triggered_today" flags
            # so a same-day flip-back-ON can re-arm weather pre-cool /
            # pre-heat. Without this, the re-arm guards in
            # _should_weather_pre_cool / _should_pre_heat fail the
            # `not _*_triggered_today` check until the date rollover at
            # _update_outcomes, contradicting the D1 Live criterion
            # ("Flip back ON inside the pre-cool window → on the next
            # cycle, conditions-met branches re-engage").
            self._pre_cool_triggered_today = False
            self._pre_heat_triggered_today = False
        self._last_pre_conditioning_gate_enabled = pre_cond_gate_on
        if not pre_cond_gate_on:
            # Master gate OFF — all pre-conditioning branches skipped
            # this cycle. Tracking sets stay empty (already reset above).
            return

        # ====================================================================
        # v5.7.1 — Unified Energy Saver Pre-Cool (PV-aware, scope-aware)
        # ====================================================================
        # Replaces the v3.17.0 weather-pre-cool branch + the solar-banking
        # branch. Single trigger, single dispatch, single operator gate on
        # the EC device ("Energy Saver Pre-Cool"). PV surplus is REQUIRED
        # in ALL reachable paths (I1) — no pure-forecast-heat trigger.
        # See PLANNING_v5.7.x_energy_pre_cool_unification.md (D1).
        # ====================================================================
        precool_gate_on = self._is_energy_precool_enabled()

        # Post-restart reconciliation. RAM-only `_last_precool_zones` is
        # empty on cold boot — if HA restarted mid-pre-cool and the
        # operator subsequently flipped the gate OFF, no release would
        # ever fire. On the FIRST eval after startup, if gate is OFF, scan
        # zones whose CURRENT live setpoints sit BELOW the resolved
        # baseline by > 0.5°F and treat them as orphan-banked. Bounded:
        # runs exactly once per process lifetime. Same shape as the
        # deleted banking reconciliation.
        if not self._first_eval_done:
            self._first_eval_done = True
            if not precool_gate_on:
                orphans: set[str] = set()
                for zone_id, zone in self._zone_manager.zones.items():
                    cur_high = getattr(zone, "target_temp_high", None)
                    if cur_high is None:
                        continue
                    baseline = self._resolve_baseline_range(zone_id)
                    if baseline is None:
                        continue
                    _base_low, base_high = baseline
                    if cur_high < base_high - 0.5:
                        orphans.add(zone_id)
                if orphans:
                    _LOGGER.info(
                        "HVAC: post-restart energy-pre-cool reconciliation — "
                        "releasing %d orphan zones (%s)",
                        len(orphans), sorted(orphans),
                    )
                    await self._release_banked_zones(orphans)
            self._last_precool_gate_enabled = precool_gate_on

        # Mid-cycle flip-OFF: release within one cycle (I5).
        if (
            not precool_gate_on
            and self._last_precool_gate_enabled
            and self._last_precool_zones
        ):
            await self._release_banked_zones(set(self._last_precool_zones))
            self._last_precool_zones = set()
        self._last_precool_gate_enabled = precool_gate_on

        # Trigger + per-zone scope dispatch. Reads BOTH offset and scope
        # from EC once per cycle; the auto_pv_tiered branch re-reads
        # net power at per-zone dispatch time (I6, not cached from the
        # gate — operator-required so unoccupied-zone expansion only
        # happens during *current* export surplus).
        if precool_gate_on and self._should_energy_precool(constraint, now):
            offset_f = self._get_energy_precool_offset()
            scope = self._get_energy_precool_scope()
            net_power_now = self._get_net_power()
            export_surplus = (
                net_power_now < -ENERGY_PRECOOL_EXPORT_THRESHOLD_W
            )
            # Effective-scope label for the HVAC house-state sensor.
            if scope == ENERGY_PRECOOL_SCOPE_AUTO_PV_TIERED:
                self._energy_precool_scope_effective = (
                    "auto_pv_tiered(expanded)" if export_surplus
                    else "auto_pv_tiered(occupied_only)"
                )
            else:
                self._energy_precool_scope_effective = scope

            # snapshot: zones dict may be pruned by _handle_zm_zones_updated mid-await
            for zone_id, zone in list(self._zone_manager.zones.items()):
                is_occupied = bool(
                    getattr(zone, "any_room_occupied", False)
                )
                if scope == ENERGY_PRECOOL_SCOPE_OCCUPIED_ONLY:
                    if not is_occupied:
                        continue  # comfort-first; never bank empty zones
                elif scope == ENERGY_PRECOOL_SCOPE_AUTO_PV_TIERED:
                    # Default: occupied always; unoccupied ONLY under
                    # real export surplus (the operator-coined
                    # "free banking" case).
                    if not is_occupied and not export_surplus:
                        continue
                # ENERGY_PRECOOL_SCOPE_WHOLE_HOUSE: no per-zone gate.

                await self._execute_zone_pre_cool(
                    zone, offset=offset_f, reason="energy_precool",
                )
                self._pre_conditioning_zones.add(zone_id)
                self._energy_precool_zones.add(zone_id)
                self._last_precool_zones.add(zone_id)

        # End pre-cool when peak starts (run regardless of house_state so
        # the _pre_cool_active flag clears even if the user came home
        # mid-event).
        if self._pre_cool_active and hour >= PEAK_HOUR_START:
            self._pre_cool_active = False
            _LOGGER.info("HVAC Pre-cool ended: peak period started")

        # --- ZI-only features below (guarded by toggle) ---
        if not zone_intelligence_enabled:
            return

        # Prune `_last_precool_zones` against the LIVE zone setpoint.
        # The pre-cool window closes at hour >= 14 but thermostats
        # remain banked until the next preset cycle naturally re-aligns
        # them. We detect "no longer banked" by comparing the zone's
        # CURRENT cool target to the resolved baseline: within 0.5°F →
        # not banked anymore. Zones written THIS cycle are excluded from
        # the prune scan (just-written live values still propagating).
        if self._last_precool_zones:
            just_banked = set(self._energy_precool_zones)
            for zone_id in list(self._last_precool_zones):
                if zone_id in just_banked:
                    continue
                zone = self._zone_manager.zones.get(zone_id)
                if zone is None:
                    self._last_precool_zones.discard(zone_id)
                    continue
                cur_high = getattr(zone, "target_temp_high", None)
                if cur_high is None:
                    continue
                baseline = self._resolve_baseline_range(zone_id)
                if baseline is None:
                    continue
                _base_low, base_high = baseline
                if cur_high >= base_high - 0.5:
                    self._last_precool_zones.discard(zone_id)

        # --- Pre-arrival (person-routed; skip when away/vacation as a defensive
        # belt — pre_arrival_zones should be empty during away anyway, but the
        # explicit gate documents the contract) ---
        if not is_unoccupied:
            # snapshot: zones dict may be pruned by _handle_zm_zones_updated mid-await
            for zone_id, zone in list(self._zone_manager.zones.items()):
                if zone_id in pre_arrival_zones:
                    await self._execute_zone_pre_cool(zone, offset=-2.0, reason="pre_arrival")
                    # Fans as comfort bridge (skip during sleep — Critique 5 fix)
                    if house_state != "sleep":
                        await self._activate_zone_fans(zone)
                    self._pre_conditioning_zones.add(zone_id)

        # --- Pre-heat (winter, before off-peak ends; occupant-comfort driven) ---
        if not is_unoccupied:
            outdoor_temp = self._get_outdoor_temp()
            if (
                not self._pre_heat_active
                and not self._pre_heat_triggered_today
                and season == SEASON_WINTER
                and outdoor_temp is not None
                and outdoor_temp <= self._preheat_forecast_low  # v4.5.10: configurable
                and OFF_PEAK_END_HOUR - PREHEAT_LEAD_HOURS <= hour < OFF_PEAK_END_HOUR
            ):
                self._pre_heat_active = True
                self._pre_heat_triggered_today = True
                _LOGGER.info(
                    "HVAC Pre-heat triggered: outdoor=%.0fF, hour=%d",
                    outdoor_temp, hour,
                )
                await self._execute_pre_heat()

        # End pre-heat when off-peak ends (run regardless of house_state for
        # the same reason as the pre-cool end-flag clear above)
        if self._pre_heat_active and hour >= OFF_PEAK_END_HOUR:
            self._pre_heat_active = False
            _LOGGER.info("HVAC Pre-heat ended: off-peak period ended")

        # Snapshot this cycle's in-flight pre-conditioning set so a
        # subsequent flip-OFF cycle (D1) can release all in-flight zones
        # via _release_banked_zones (baseline-write path). Includes the
        # banking-zone subset implicitly since _pre_conditioning_zones is
        # the superset in `_check_pre_conditioning`.
        self._last_pre_conditioning_zones = set(self._pre_conditioning_zones)

    def _should_energy_precool(
        self, constraint: EnergyConstraint | None, now,
    ) -> bool:
        """Unified PV-aware energy pre-cool trigger (v5.7.1).

        Replaces the v3.17.0 weather-pre-cool + solar-banking branches.
        PV surplus is REQUIRED (I1) — no pure-forecast-heat trigger.
        Forecast heat raises aggressiveness (lower SOC threshold) when
        also solar-rich.

        Season-gated to summer/shoulder. Hour-window: [10, 14). SOC
        floor: 30% on hot days (forecast >= self._precool_forecast_high)
        else 95% (cool-day banking). `constraint.mode == "normal"` keeps
        the inclement-weather hold (v5.5.0) compatible — non-normal
        modes prevent pre-cool.

        Sets _pre_cool_active + _pre_cool_triggered_today (daily-once
        flap guard, shared with the deleted weather-pre-cool path).
        """
        if constraint is None:
            return False
        season = self._preset_manager.current_season
        if season not in (SEASON_SUMMER, SEASON_SHOULDER):
            return False

        hour = now.hour
        if not (ENERGY_PRECOOL_HOUR_START <= hour < PEAK_HOUR_START):
            return False

        # v5.7.1 fix-up (D-HIGH-1): PV+mode BEFORE re-engagement gate.
        net_power = self._get_net_power()
        if net_power >= -ENERGY_PRECOOL_EXPORT_THRESHOLD_W:
            return False
        if getattr(constraint, "mode", "normal") != "normal":
            return False

        if self._pre_cool_active and hour < PEAK_HOUR_START:
            return True  # already in-flight + still solar-rich + normal mode
        if self._pre_cool_active or self._pre_cool_triggered_today:
            return False  # daily-once guard (same as weather-pre-cool)

        forecast_high = constraint.forecast_high_temp
        soc = constraint.soc

        # SOC floor — must have enough battery to safely cool from house
        # mass. Hot day → lower floor (we WANT to bank aggressively even
        # if the battery isn't full because peak-AC cost >> mid-day
        # discharge). Cool day → higher floor (banking only for grid-
        # export-avoidance reasons; need a nearly-full battery first).
        is_hot = (
            forecast_high is not None
            and forecast_high >= self._precool_forecast_high
        )
        soc_floor = PRECOOL_SOC_MIN if is_hot else self._solar_bank_soc_min
        # v5.7.1 fix-up (A2 MED): SOC=None FAILS cool-day floor (mirrors
        # old `(soc or 0) < soc_floor`); hot-day fires on None.
        if soc is None:
            if not is_hot:
                return False
        elif soc < soc_floor:
            return False

        self._pre_cool_active = True
        self._pre_cool_triggered_today = True
        _LOGGER.info(
            "Energy Saver Pre-Cool triggered: forecast_high=%s, hour=%d, "
            "soc=%s, net_power=%.0fW (exporting), is_hot=%s, soc_floor=%d",
            forecast_high, hour, soc, net_power, is_hot, soc_floor,
        )
        return True

    def _is_pre_conditioning_enabled(self) -> bool:
        """Master operator gate for ALL HC pre-conditioning branches.

        Reads `pre_conditioning_enabled` from the HVACCoordinator via the
        coordinator_manager registry (same accessor pattern as
        `_is_solar_banking_enabled`). Defaults to True when HC is not yet
        registered — fail-safe = preserve current behavior, never silently
        disable a feature because HC was slow to register at startup.
        See PLANNING_hc_precool_toggle_oc_observability.md (D1).
        """
        try:
            from ..const import DOMAIN
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            hvac = manager.coordinators.get("hvac") if (
                manager is not None and hasattr(manager, "coordinators")
            ) else None
            if hvac is None:
                return True
            return bool(getattr(hvac, "pre_conditioning_enabled", True))
        except Exception:
            # Any unexpected lookup failure → preserve current behavior.
            return True

    def _is_energy_precool_enabled(self) -> bool:
        """Master operator gate for the unified Energy Saver Pre-Cool branch.

        Reads `energy_precool_enabled` from the EnergyCoordinator via the
        coordinator_manager registry (same accessor pattern used by the EC
        sub-switches in switch.py). Defaults to True when EC is not yet
        registered — fail-safe = preserve current behavior, never silently
        disable a feature because EC was slow to register at startup.
        v5.7.1 replaces the deleted _is_solar_banking_enabled.
        """
        try:
            from ..const import DOMAIN
            from .hvac_const import DEFAULT_ENERGY_PRECOOL_ENABLED
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            energy = manager.coordinators.get("energy") if (
                manager is not None and hasattr(manager, "coordinators")
            ) else None
            if energy is None:
                return DEFAULT_ENERGY_PRECOOL_ENABLED
            return bool(getattr(
                energy, "energy_precool_enabled",
                DEFAULT_ENERGY_PRECOOL_ENABLED,
            ))
        except Exception:  # noqa: BLE001
            return True

    def _get_energy_precool_offset(self) -> float:
        """Operator-configured pre-cool offset (°F from target_temp_high).

        Defaults to DEFAULT_ENERGY_PRECOOL_OFFSET when EC not yet
        registered. The 72°F floor (SOLAR_BANK_FLOOR) still clamps the
        resulting setpoint (I3) — an absurd configured value cannot
        breach the floor.
        """
        try:
            from ..const import DOMAIN
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            energy = manager.coordinators.get("energy") if (
                manager is not None and hasattr(manager, "coordinators")
            ) else None
            if energy is None:
                return DEFAULT_ENERGY_PRECOOL_OFFSET
            return float(getattr(
                energy, "energy_precool_offset",
                DEFAULT_ENERGY_PRECOOL_OFFSET,
            ))
        except Exception:  # noqa: BLE001
            return DEFAULT_ENERGY_PRECOOL_OFFSET

    def _get_energy_precool_scope(self) -> str:
        """Operator-configured pre-cool scope.

        Returns one of ENERGY_PRECOOL_SCOPE_VALUES. Invalid or missing
        values fall back to DEFAULT_ENERGY_PRECOOL_SCOPE.
        """
        try:
            from ..const import DOMAIN
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            energy = manager.coordinators.get("energy") if (
                manager is not None and hasattr(manager, "coordinators")
            ) else None
            if energy is None:
                return DEFAULT_ENERGY_PRECOOL_SCOPE
            scope = getattr(
                energy, "energy_precool_scope",
                DEFAULT_ENERGY_PRECOOL_SCOPE,
            )
            if scope not in ENERGY_PRECOOL_SCOPE_VALUES:
                return DEFAULT_ENERGY_PRECOOL_SCOPE
            return scope
        except Exception:  # noqa: BLE001
            return DEFAULT_ENERGY_PRECOOL_SCOPE

    def _resolve_baseline_range(self, zone_id: str) -> tuple[float, float] | None:
        """Return the TRUE (baseline_low, baseline_high) for a zone.

        Tier 1 review CRITICAL-1 fix: prefer `HVACCoordinator._last_emitted_range`
        (the last URA-emitted preset range, throttle map at hvac.py:213/1347) —
        this is what the thermostat "should" be at when not banked. `zone.
        target_temp_high/low` are NOT a valid baseline: they refresh every
        cycle from LIVE climate state (hvac_zones.py:448-449 via hvac.py:816),
        so once banking has dispatched, those fields equal the BANKED values
        → writing them back is a no-op.

        Fallback when `_last_emitted_range` has no entry (e.g. zone never
        had a preset cycle since boot): reconstruct from preset manager
        using the same shape DPM apply uses (cool_high = baseline_cool,
        cool_low = baseline_cool - 7.0 — see hvac.py:1337).

        NB (pre-existing, out of scope): the same live-state read causes
        banking itself to ratchet toward the SOLAR_BANK_FLOOR across
        cycles because `_execute_zone_pre_cool` reads
        zone.target_temp_high (already banked) and subtracts another -3°F
        offset each cycle. Flag for backlog — fixing the release path
        does not fix the ratchet, but using `_last_emitted_range` for
        release at least cleanly returns to a stable baseline.
        """
        coord = self._hvac_coord
        last_emitted = getattr(coord, "_last_emitted_range", None) if coord else None
        # A-MED-1 (benign edge): if a DPM preset emit fires for this zone
        # between the pre-cool write and the flip-OFF release,
        # `_last_emitted_range[zone]` advances to the new preset range, so
        # release writes the CURRENT preset target rather than the
        # pre-cool-time baseline. The value is still a valid current-preset
        # range (NOT a banked echo), so the behavior is correct — just
        # different from the "restore the pre-cool baseline" intuition.
        # Consistent with the preset-resolved fallback below, which is also
        # current-house-state based.
        if last_emitted is not None:
            entry = last_emitted.get(zone_id)
            if entry is not None:
                try:
                    low, high = entry
                    return float(low), float(high)
                except (TypeError, ValueError):
                    pass

        # Preset-resolved fallback (mirrors DPM apply at hvac.py:1330-1338).
        try:
            house_state = getattr(coord, "_house_state", None) if coord else None
            target_preset = self._preset_manager.get_preset_for_house_state(house_state)
            if target_preset is None:
                return None
            baseline = self._preset_manager.get_seasonal_setpoints(target_preset)
            if baseline is None:
                return None
            baseline_cool, _baseline_heat = baseline
            return (float(baseline_cool) - 7.0, float(baseline_cool))
        except Exception:  # noqa: BLE001
            return None

    async def _release_banked_zones(self, zone_ids: set[str]) -> None:
        """Release previously-banked zones by writing baseline setpoints back.

        Called once on the cycle where the master banking gate flips OFF
        while zones are still mid-bank. Issues `climate.set_temperature`
        with the TRUE preset baseline (sourced from
        `HVACCoordinator._last_emitted_range`, with preset-resolved
        fallback), undoing the -3°F banking offset.

        Mirrors the suppress/unsuppress pattern in _execute_zone_pre_cool so
        the release write is not flagged as a manual override by the
        OverrideArrester. Failures are logged but do not raise — releasing
        N-1 zones is better than failing all N.

        After release we also write the baseline pair back into
        `_last_emitted_range` so the next DPM apply cycle stays consistent
        (its throttle compares against this map — without the update,
        a benign re-emit would still happen on the next cycle, but no
        double-write risk because the values would match).
        """
        coord = self._hvac_coord
        last_emitted = getattr(coord, "_last_emitted_range", None) if coord else None
        for zone_id in zone_ids:
            zone = self._zone_manager.zones.get(zone_id)
            if zone is None:
                continue
            baseline = self._resolve_baseline_range(zone_id)
            if baseline is None:
                _LOGGER.warning(
                    "HVAC: cannot release banked zone %s — no baseline "
                    "(no _last_emitted_range entry and preset fallback "
                    "unavailable)", zone_id,
                )
                continue
            base_low, base_high = baseline
            if self._override_arrester:
                self._override_arrester.suppress(zone.climate_entity, kind="temp")  # v5.36.2 H6: B1 completeness
            # B-L1: store the POST-guard pair the chokepoint will actually
            # write (consistent with the DPM apply at hvac.py:1522-1529), so a
            # banking-release during a freeze doesn't leave a pre-guard value
            # in the throttle map that the next DPM cycle re-emits redundantly.
            freeze_active = self._freeze_active()
            emit_low, emit_high = apply_setpoint_guards(
                base_low, base_high, freeze_active=freeze_active,
            )
            try:
                await emit_set_temperature(
                    self.hass,
                    zone.climate_entity,
                    target_temp_low=base_low,
                    target_temp_high=base_high,
                    freeze_active=freeze_active,
                    blocking=False,
                )
                # Keep throttle map consistent with the value we just wrote.
                if last_emitted is not None:
                    last_emitted[zone_id] = (emit_low, emit_high)
                _LOGGER.info(
                    "HVAC: Solar banking master OFF — released %s to baseline "
                    "(low=%.1f high=%.1f)",
                    zone.zone_name, base_low, base_high,
                )
            except Exception as e:  # noqa: BLE001
                _LOGGER.error(
                    "HVAC: Failed to release banked zone %s: %s",
                    zone.climate_entity, e,
                )

    def _get_net_power(self) -> float:
        """Read real-time net power. Negative = exporting to grid.

        v4.2.29: Returns 0.0 when no net_power_entity is configured (e.g.,
        EC disabled or envoy validation failed). Solar banking decisions
        that require live net power are gated on the result and will skip.
        """
        if not self._net_power_entity:
            return 0.0
        entity = self.hass.states.get(self._net_power_entity)
        if entity is None or entity.state in ("unavailable", "unknown"):
            return 0.0
        try:
            return float(entity.state)
        except (ValueError, TypeError):
            return 0.0

    async def _execute_zone_pre_cool(
        self, zone, offset: float, reason: str,
    ) -> None:
        """Pre-cool a single zone with offset from target_temp_high.

        Applies floor: never go below SOLAR_BANK_FLOOR or within MIN_DEADBAND
        of target_temp_low (Ecobee requires >= 2F deadband in auto mode).
        """
        # v4.7.8 D8: skip predictive pre-cool dispatch for paused zones.
        if (
            self._egress_manager is not None
            and self._egress_manager.is_paused(zone.zone_id)
        ):
            return
        if zone.target_temp_high is None or zone.target_temp_low is None:
            return

        banked_high = zone.target_temp_high + offset  # offset is negative
        # v4.5.10: floor is now self._solar_bank_floor (configurable).
        floor = max(self._solar_bank_floor, zone.target_temp_low + MIN_DEADBAND)
        effective_high = max(banked_high, floor)

        if effective_high >= zone.target_temp_high:
            return  # Floor prevents any meaningful change

        # Suppress arrester
        if self._override_arrester:
            self._override_arrester.suppress(zone.climate_entity, kind="temp")  # v5.36.2 H6: B1 completeness

        try:
            await emit_set_temperature(
                self.hass,
                zone.climate_entity,
                target_temp_low=zone.target_temp_low,
                target_temp_high=effective_high,
                freeze_active=self._freeze_active(),
                blocking=False,
            )
            _LOGGER.info(
                "HVAC: Zone %s pre-cool (%s): %.1f -> %.1f (offset=%.1f, floor=%.1f)",
                zone.zone_name, reason,
                zone.target_temp_high, effective_high, offset, floor,
            )
        except Exception as e:
            _LOGGER.error("HVAC: Failed to pre-cool %s: %s", zone.climate_entity, e)

    async def _activate_zone_fans(self, zone) -> None:
        """Turn on zone fans for comfort bridge during pre-arrival.

        Only activates fans in rooms where the temperature is at or above
        the zone cooling setpoint. Skips rooms with unknown temperature
        (safe default: don't activate without data).
        """
        from ..const import CONF_FANS, CONF_ENTRY_TYPE, CONF_ROOM_NAME, DOMAIN, ENTRY_TYPE_ROOM

        setpoint_high = zone.target_temp_high

        for room_name in zone.rooms:
            coordinator = self._get_room_coordinator(room_name)
            if coordinator is None:
                continue
            config = {**coordinator.config_entry.data, **coordinator.config_entry.options}
            fans = config.get(CONF_FANS, [])
            if not fans:
                continue

            # Get room temperature from zone conditions
            room_temp = None
            for rc in zone.room_conditions:
                if rc.room_name == room_name:
                    room_temp = rc.temperature
                    break

            # Skip when we lack temperature data to make a decision
            if setpoint_high is None or room_temp is None:
                self._last_fan_skipped_rooms.append({
                    "room": room_name,
                    "temp": round(room_temp, 1) if room_temp is not None else None,
                    "setpoint": setpoint_high,
                    "reason": "no_data",
                })
                _LOGGER.info(
                    "HVAC: Pre-arrival fan skipped %s (temp=%s, setpoint=%s — insufficient data)",
                    room_name, room_temp, setpoint_high,
                )
                continue

            # Skip rooms already below cooling setpoint
            if room_temp < setpoint_high:
                self._last_fan_skipped_rooms.append({
                    "room": room_name,
                    "temp": round(room_temp, 1),
                    "setpoint": setpoint_high,
                    "reason": "below_setpoint",
                })
                _LOGGER.info(
                    "HVAC: Pre-arrival fan skipped %s (%.1f°F < %.1f°F setpoint)",
                    room_name, room_temp, setpoint_high,
                )
                continue

            # Activate fans — track whether at least one succeeded
            any_succeeded = False
            for fan_entity in fans:
                domain = fan_entity.split(".")[0]
                state = self.hass.states.get(fan_entity)
                if state and state.state != "on":
                    try:
                        await self.hass.services.async_call(
                            domain, "turn_on",
                            {"entity_id": fan_entity}, blocking=False,
                        )
                        any_succeeded = True
                    except Exception:  # noqa: BLE001
                        _LOGGER.warning(
                            "HVAC: Pre-arrival fan service call failed for %s",
                            fan_entity,
                        )
                else:
                    any_succeeded = True  # Already on counts as success

            if any_succeeded:
                self._last_fan_activation_rooms.append(room_name)
                _LOGGER.info(
                    "HVAC: Pre-arrival fan activated %s (%.1f°F >= %.1f°F setpoint)",
                    room_name, room_temp, setpoint_high,
                )

        _LOGGER.info(
            "HVAC: Pre-arrival fans for zone %s: activated=%s, skipped=%s",
            zone.zone_name,
            self._last_fan_activation_rooms,
            [s["room"] for s in self._last_fan_skipped_rooms],
        )

    def _get_room_coordinator(self, room_name: str):
        """Get room coordinator by room name."""
        from ..const import CONF_ENTRY_TYPE, CONF_ROOM_NAME, DOMAIN, ENTRY_TYPE_ROOM

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            if entry.data.get(CONF_ROOM_NAME) == room_name:
                return self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
        return None

    async def _execute_pre_heat(self) -> None:
        """Raise heating setpoints to pre-heat before on-peak."""
        # snapshot: zones dict may be pruned by _handle_zm_zones_updated mid-await
        for zone in list(self._zone_manager.zones.values()):
            # v4.7.8 D8: skip predictive pre-heat dispatch for paused zones.
            if (
                self._egress_manager is not None
                and self._egress_manager.is_paused(zone.zone_id)
            ):
                continue
            if not zone.any_room_occupied:
                continue
            if zone.target_temp_high is None or zone.target_temp_low is None:
                continue

            pre_heat_temp = zone.target_temp_low + 2  # Raise by 2F from current

            # Suppress override arrester for this change
            if self._override_arrester:
                self._override_arrester.suppress(zone.climate_entity, kind="temp")  # v5.36.2 H6: B1 completeness

            try:
                await emit_set_temperature(
                    self.hass,
                    zone.climate_entity,
                    target_temp_low=pre_heat_temp,
                    target_temp_high=zone.target_temp_high,
                    freeze_active=self._freeze_active(),
                    blocking=False,
                )
                _LOGGER.info(
                    "HVAC Pre-heat: %s set to %.0fF (was %.0fF)",
                    zone.zone_name, pre_heat_temp, zone.target_temp_low,
                )
            except Exception as e:
                _LOGGER.error("HVAC Pre-heat failed on %s: %s",
                              zone.climate_entity, e)

    def _store_daily_outcome(self) -> None:
        """Store daily outcome measurement."""
        satisfaction = (
            (self._in_band_checks / self._total_checks * 100)
            if self._total_checks > 0
            else 100.0
        )
        total_overrides = sum(
            z.override_count_today for z in self._zone_manager.zones.values()
        )
        total_resets = sum(
            z.ac_reset_count_today for z in self._zone_manager.zones.values()
        )
        self._last_outcome = HVACOutcome(
            date=self._last_outcome_date,
            zone_satisfaction_pct=round(satisfaction, 1),
            total_overrides=total_overrides,
            total_ac_resets=total_resets,
            energy_mode_minutes=dict(self._energy_mode_minutes),
            pre_cool_triggered=self._pre_cool_triggered_today,
            pre_heat_triggered=self._pre_heat_triggered_today,
        )
        _LOGGER.info(
            "HVAC Daily Outcome: satisfaction=%.1f%%, overrides=%d, resets=%d",
            satisfaction, total_overrides, total_resets,
        )

    def _get_outdoor_temp(self) -> float | None:
        """Read outdoor temperature."""
        if not self._outdoor_temp_entity:
            return None
        state = self.hass.states.get(self._outdoor_temp_entity)
        if state is None or state.state in ("unavailable", "unknown"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    # =========================================================================
    # Public accessors for sensors
    # =========================================================================

    @property
    def pre_cool_likelihood(self) -> int:
        """Return pre-cool likelihood percentage."""
        return self._pre_cool_likelihood

    @property
    def comfort_violation_risk(self) -> str:
        """Return comfort violation risk level."""
        return self._comfort_violation_risk

    @property
    def pre_cool_active(self) -> bool:
        """Return whether pre-cooling is active."""
        return self._pre_cool_active

    @property
    def pre_heat_active(self) -> bool:
        """Return whether pre-heating is active."""
        return self._pre_heat_active

    def get_zone_demand(self, zone_id: str) -> str:
        """Return demand level for a zone."""
        return self._zone_demand.get(zone_id, "unknown")

    def get_prediction_attrs(self) -> dict[str, Any]:
        """Return prediction attributes for sensor."""
        return {
            "pre_cool_likelihood": self._pre_cool_likelihood,
            "comfort_violation_risk": self._comfort_violation_risk,
            "pre_cool_active": self._pre_cool_active,
            "pre_heat_active": self._pre_heat_active,
            "pre_cool_triggered_today": self._pre_cool_triggered_today,
            "pre_heat_triggered_today": self._pre_heat_triggered_today,
            "zone_demand": dict(self._zone_demand),
        }

    def get_intent_attrs(self) -> dict[str, Any]:
        """Return D4 intent enrichment attributes for the pre-cool likelihood sensor.

        v4.6.9 D4: Adds reasoning context (forecast peak, TOU anchor, solar
        intent, prior-day baseline) to the existing pre-cool likelihood sensor.

        PWA contract guards:
        - All numeric attrs: float or None. Never "—" / "N/A" / "" strings.
        - Timestamps: ISO 8601 UTC strings, or None. Never naive datetime.
        - solar_intent / anchor_period: str or None.
        - Flat dict only. No nested objects.

        Bug-class prevention:
        - #8:  isinstance guards on forecast dict and list
        - #11: all timestamps UTC via dt_util.now().astimezone(UTC).isoformat()
        - #14: energy coordinator re-read at call time (not cached on self)
        - #29: null-forecast branch fully covered
        - #37: stable attribute shape — all 6 keys always present
        """
        from datetime import timezone

        from ..const import DOMAIN

        # Re-read at call time (Bug Class #14 — no stale cache).
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        energy = manager.coordinators.get("energy") if manager is not None else None

        # --- Forecast peak outside temp and time ---
        forecast_peak_outside_f: float | None = None
        forecast_peak_time_iso: str | None = None

        if energy is not None:
            try:
                cached_high = energy._cached_forecast_high
                if cached_high is not None:
                    forecast_peak_outside_f = float(cached_high)
                    # Derive the forecast peak time from today's TOU peak start
                    # hour (PEAK_HOUR_START = 14 / 2PM).  We anchor to midnight
                    # of today in local time, then convert to UTC ISO.
                    # Bug Class #11: result is always UTC-aware.
                    now = dt_util.now()
                    peak_local = now.replace(
                        hour=PEAK_HOUR_START,
                        minute=0,
                        second=0,
                        microsecond=0,
                    )
                    forecast_peak_time_iso = (
                        peak_local.astimezone(timezone.utc).isoformat()
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.debug("get_intent_attrs: failed to read forecast from EC")

        # --- TOU anchor period + minutes until it starts ---
        anchor_period: str | None = None
        anchor_starts_in_minutes: int | None = None

        if energy is not None:
            try:
                tou = energy.tou_engine
                transition = tou.get_next_transition()
                # Bug Class #8: guard the transition dict
                if isinstance(transition, dict):
                    next_period = transition.get("next_period")
                    hours_until = transition.get("hours_until")
                    if next_period in ("peak", "mid_peak"):
                        anchor_period = next_period
                        if hours_until is not None:
                            anchor_starts_in_minutes = int(
                                round(float(hours_until) * 60)
                            )
                    elif next_period == "off_peak":
                        # Currently in a peak window — anchor to the current period
                        try:
                            current = tou.get_current_period()
                            if current in ("peak", "mid_peak"):
                                anchor_period = current
                                anchor_starts_in_minutes = 0
                        except Exception:  # noqa: BLE001
                            pass
            except Exception:  # noqa: BLE001
                _LOGGER.debug("get_intent_attrs: failed to read TOU anchor from EC")

        # --- Solar intent ---
        # Derived from EC battery strategy phase and mode.
        # Mapping:
        #   arbitrage_phase == "charge"     → harvest (charging from grid/solar)
        #   arbitrage_phase == "discharge"  → export (discharging to house/grid)
        #   mode == "self_consumption"      → passthrough (balancing in place)
        #   anything else                   → unknown
        solar_intent: str | None = None

        if energy is not None:
            try:
                batt = energy.battery_status
                if isinstance(batt, dict):
                    phase = batt.get("arbitrage_phase", "n/a")
                    mode = batt.get("mode", "unknown")
                    if phase in ("charge", "attain"):
                        # Cycle EC/HC reboot pickup: ATTAIN is also a
                        # grid-charging phase (peak-buffer catch-up on a
                        # good-day-with-eaten-solar). Bug Class #22 — new
                        # enum value must be reflected in every consumer
                        # that string-matches on arbitrage_phase.
                        solar_intent = "harvest"
                    elif phase == "discharge":
                        solar_intent = "export"
                    elif mode == "self_consumption":
                        solar_intent = "passthrough"
                    else:
                        solar_intent = "unknown"
            except Exception:  # noqa: BLE001
                _LOGGER.debug("get_intent_attrs: failed to read battery strategy from EC")

        # --- Prior-day baseline ---
        # TODO(v4.7.x): no prior-day outdoor-temp tracking exists in the codebase.
        # Emit null until a historical baseline store is introduced.
        prior_day_at_this_hour_f: float | None = None

        _LOGGER.debug(
            "HVAC intent attrs: forecast_peak=%.1f anchor=%s solar_intent=%s",
            forecast_peak_outside_f or 0.0,
            anchor_period,
            solar_intent,
        )

        return {
            "forecast_peak_outside_f": forecast_peak_outside_f,
            "forecast_peak_time_iso": forecast_peak_time_iso,
            "anchor_period": anchor_period,
            "anchor_starts_in_minutes": anchor_starts_in_minutes,
            "solar_intent": solar_intent,
            "prior_day_at_this_hour_f": prior_day_at_this_hour_f,
        }

    def get_outcome_attrs(self) -> dict[str, Any]:
        """Return daily outcome for sensor."""
        if self._last_outcome is None:
            satisfaction = (
                (self._in_band_checks / self._total_checks * 100)
                if self._total_checks > 0
                else 100.0
            )
            return {
                "zone_satisfaction_pct": round(satisfaction, 1),
                "total_checks_today": self._total_checks,
                "in_band_checks_today": self._in_band_checks,
                "energy_mode_minutes": dict(self._energy_mode_minutes),
            }
        return {
            "date": self._last_outcome.date,
            "zone_satisfaction_pct": self._last_outcome.zone_satisfaction_pct,
            "total_overrides": self._last_outcome.total_overrides,
            "total_ac_resets": self._last_outcome.total_ac_resets,
            "energy_mode_minutes": self._last_outcome.energy_mode_minutes,
            "pre_cool_triggered": self._last_outcome.pre_cool_triggered,
            "pre_heat_triggered": self._last_outcome.pre_heat_triggered,
        }
