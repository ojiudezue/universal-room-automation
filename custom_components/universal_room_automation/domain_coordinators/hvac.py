"""HVAC Coordinator for Universal Room Automation.

Manages HVAC zones, presets, fans, covers, and energy constraint response.
Priority 30 (below Energy at 40).

v3.8.0-H1: Core + Zone Management + Preset + E6 Signal + Diagnostics Skeleton.
v3.17.0: Zone Intelligence — vacancy management, duty cycle, stale failsafe,
         person-to-zone pre-arrival, zone presence state machine.
"""

from __future__ import annotations

import asyncio
import time
import logging
from collections import deque
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from .base import BaseCoordinator, CoordinatorAction, Intent
from .hvac_const import (
    HVAC_DECISION_TICK,
    HVAC_EVIDENCE_RULE_STATES,
    HVAC_NIGHT_HOLD_STATES,
    HVAC_FAST_PATH_MIN_INTERVAL_S,
    HVAC_FAST_PATH_SLA_S,
    HVAC_FAST_PATH_EXIT_SLACK_S,
    HVAC_FAST_PATH_MAX_WRITES_PER_ZONE_PER_HOUR,
    HVAC_FAST_PATH_MAX_RUNS_PER_ZONE_PER_HOUR,
    HVAC_QUICK_RETURN_WINDOW_S,
    HVAC_QUICK_RETURN_NM_PER_DAY,
    HVAC_PENDING_HOLD_CAP_S,
    DEFAULT_HVAC_RETURN_WINDOW_MINUTES,
    # HVAC W1/W2 finish D5: knob 35 "Pre-Arrival Window (min)".
    DEFAULT_HVAC_PRE_ARRIVAL_WINDOW_MINUTES,
    S12_PRE_ARRIVAL_SITE,
    clamp_hvac_pre_arrival_window_minutes,
    pre_arrival_reference_preset,
    COMFORT_SOC_FLOOR_PCT,
    COMFORT_GRACE_MIN,
    # HVAC W1-B: P2 classifier thresholds + §5.P5 reclaim-rate trip-wire.
    OVERRIDE_NORMAL_DELTA,
    OVERRIDE_COAST_TOLERANCE_BONUS,
    S1_RECLAIM_RATE_LIMIT_N,
    S1_RECLAIM_RATE_WINDOW_S,
    CONF_HVAC_ARRESTER_ENABLED,
    DEFAULT_ARRESTER_ENABLED,
    DEFAULT_MAX_OCCUPANCY_HOURS,
    DEFAULT_VACANCY_GRACE_CONSTRAINED,
    DEFAULT_VACANCY_GRACE_MINUTES,
    DEFAULT_ZONE_ENTRY_DWELL_MINUTES,
    DUTY_CYCLE_COAST,
    DUTY_CYCLE_SHED,
    DUTY_CYCLE_WINDOW_SECONDS,
    FAN_TRUST_STATES,
    FREEZE_FLOOR,
    FREEZE_TRIGGER_HYSTERESIS,
    FREEZE_TRIGGER_TEMP,
    HVAC_ANOMALY_MIN_SAMPLES,
    HVAC_SHORT_CYCLE_MIN_SAMPLES,
    SHORT_CYCLE_THRESHOLD_S,
    HVAC_COORDINATOR_ID,
    HVAC_COORDINATOR_NAME,
    HVAC_COORDINATOR_PRIORITY,
    HVAC_METRICS,
    HVAC_SUPPRESSED_FROM_PERSISTENCE,
    PRE_ARRIVAL_TIMEOUT_MINUTES,
    SIGNAL_HVAC_ENTITIES_UPDATE,
)
from .hvac_covers import CoverController
from .hvac_egress import EgressManager
from .hvac_fans import FanController
from .hvac_override import OverrideArrester, SUPPRESS_TTL_SECONDS_PRESET
from .hvac_predict import HVACPredictor
from .hvac_preset import PresetManager
from .hvac_setpoint import (
    apply_setpoint_guards,
    emit_set_hvac_mode,
    emit_set_preset_mode,
    emit_set_temperature,
)
from .hvac_zones import ZoneManager
from .signals import (
    EnergyConstraint,
    SIGNAL_ENERGY_CONSTRAINT,
    SIGNAL_HOUSE_STATE_CHANGED,
    SIGNAL_PERSON_ARRIVING,
    SIGNAL_ROOM_ENTRY_LIFECYCLE,
    SIGNAL_SAFETY_HAZARD,
    SIGNAL_ZM_ZONES_UPDATED,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Zone-prune hotfix D1 — module-level helpers (extracted for real test
# authority per fix-up "Fix 2"). Lifting these out of the handler makes
# them import-testable WITHOUT the HA runtime, which is what caught the
# A-CRIT-1 dead-import in the prior build.
# ---------------------------------------------------------------------------
def _compute_surviving_thermostats(
    hass: Any, deleted_name: str,
) -> tuple[set[str], bool]:
    """Build the set of thermostat entity_ids still claimed by any surviving
    house zone — BOTH ZM-embedded zones (`ENTRY_TYPE_ZONE_MANAGER` options
    ``zones`` dict) AND legacy standalone ``ENTRY_TYPE_ZONE`` entries
    (fix-up A-HIGH-2 / plan Invariant I).

    Returns ``(set, ok)``. ``ok=False`` signals the caller to SPARE the
    prune (fix-up A-MED-1) rather than proceed with a partial set.
    """
    surviving: set[str] = set()
    try:
        # Import from const.py (NOT hvac_const — fix-up A-CRIT-1).
        from ..const import (
            CONF_ENTRY_TYPE,
            CONF_ZONE_NAME,
            CONF_ZONE_THERMOSTAT,
            DOMAIN as _DOMAIN,
            ENTRY_TYPE_ZONE,
            ENTRY_TYPE_ZONE_MANAGER,
        )
        for ce in hass.config_entries.async_entries(_DOMAIN):
            et = ce.data.get(CONF_ENTRY_TYPE)
            if et == ENTRY_TYPE_ZONE_MANAGER:
                merged = {**ce.data, **ce.options}
                zm_zones = merged.get("zones", {}) or {}
                for zname_key, zcfg in zm_zones.items():
                    if zname_key == deleted_name:
                        continue
                    therm = (zcfg or {}).get(CONF_ZONE_THERMOSTAT)
                    if therm:
                        surviving.add(therm)
            elif et == ENTRY_TYPE_ZONE:
                merged = {**ce.data, **ce.options}
                zname_key = (merged.get(CONF_ZONE_NAME) or "").strip()
                if zname_key == deleted_name:
                    continue
                therm = merged.get(CONF_ZONE_THERMOSTAT)
                if therm:
                    surviving.add(therm)
        return surviving, True
    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "HVAC prune guard: _compute_surviving_thermostats failed",
            exc_info=True,
        )
        return surviving, False


def _thermostat_still_claimed_helper(
    zs: Any, surviving_thermostats: set[str],
) -> bool:
    """True iff the zone-state's climate_entity is in the survivor set."""
    therm = getattr(zs, "climate_entity", "") or ""
    return bool(therm) and therm in surviving_thermostats


class HVACCoordinator(BaseCoordinator):
    """HVAC Coordinator — zone comfort and cost management.

    Listens for:
    - SIGNAL_HOUSE_STATE_CHANGED → adjust presets
    - SIGNAL_ENERGY_CONSTRAINT → apply energy offsets to setpoints
    - Zone climate entity state changes → detect manual overrides
    """

    COORDINATOR_ID = HVAC_COORDINATOR_ID

    def __init__(
        self,
        hass: HomeAssistant,
        max_sleep_offset: float = 1.5,
        # HVAC W1-B D4a (M11): default 30 -> 15 (HVAC_COMPROMISE_MINUTES_MAX).
        compromise_minutes: int = 15,
        ac_reset_timeout: int = 10,
        fan_activation_delta: float = 2.0,
        fan_hysteresis: float = 1.5,
        fan_min_runtime: int = 10,
        arrester_enabled: bool = DEFAULT_ARRESTER_ENABLED,
        ac_reset_enabled: bool = True,
        vacancy_grace: int = DEFAULT_VACANCY_GRACE_MINUTES,
        vacancy_grace_constrained: int = DEFAULT_VACANCY_GRACE_CONSTRAINED,
        max_occupancy_hours: int = DEFAULT_MAX_OCCUPANCY_HOURS,
        zone_entry_dwell: int = DEFAULT_ZONE_ENTRY_DWELL_MINUTES,
        return_window_minutes: int = DEFAULT_HVAC_RETURN_WINDOW_MINUTES,
        pre_arrival_window_minutes: int = DEFAULT_HVAC_PRE_ARRIVAL_WINDOW_MINUTES,
        person_zone_map: dict[str, list[str]] | None = None,  # Deprecated: map now built internally from zone_persons config
        net_power_entity: str | None = None,
        fan_control_enabled: bool = True,
        # v4.5.9.2: occupancy-aware solar-gain cover-close threshold (was hardcoded)
        occupied_cover_close_delta: float = 2.0,
        # v4.5.10: HVAC tunables — master + 5 cover thresholds + 4 predictor thresholds
        solar_gain_cover_enabled: bool = True,
        cover_close_temp: float = 85.0,
        cover_open_temp: float = 80.0,
        cover_override_hours: float = 2.0,
        solar_bank_floor: float = 72.0,
        cover_solar_start_hour: int = 13,
        cover_solar_end_hour: int = 18,
        solar_bank_soc_min: int = 95,
        precool_forecast_high: float = 90.0,
        preheat_forecast_low: float = 35.0,
        # v4.7.8 D2: Egress Window HVAC Pause master + 2 tunables
        egress_pause_enabled: bool = True,
        egress_threshold_min: int = 3,
        egress_resume_delay_min: int = 1,
        # HC Pre-Conditioning master enable (D1). Install-time seed; the
        # HVACPreConditioningSwitch is the runtime source of truth via
        # options-write-back.
        pre_conditioning_enabled: bool = True,
        # Arrester Operator-Immunity (2026-08-06). Empty default = feature
        # dormant (no user's holds immune). CM __init__.py resolves the
        # operator's actual list from options; passing here keeps the
        # HVAC coord unaware of options schema (mirror of other CONFs).
        arrester_immune_persons: list[str] | None = None,
        # AC-ramp master persistence (2026-08-06). Seeded from
        # entry.options[hvac_ac_ramp_master_enabled]; the switch write-
        # through keeps this in sync on toggle. Fixes the reload→OFF
        # regression where a config-entry reload silently reset the
        # arrester's ramp master to DEFAULT=False.
        ac_ramp_master_enabled: bool | None = None,
        # ARREST-COMFORT-1 D2-LOW-2 fix-up (2026-08-10): eager-seed the
        # comfort-delay rung-3 knobs at construction (BEFORE the Number
        # entities are added, so the arrester + D3 guard never read the
        # module defaults during the boot window). Values default to the
        # module constants when unset (fresh install / test bench).
        comfort_grace_min: int | None = None,
        comfort_soc_floor_pct: int | None = None,
        # HVAC-PRESET-FLAP-1 D4 (2026-08-11): eager-seed the duty off-phase
        # honesty knobs at HC construction so the D5 else-limb never reads
        # stale defaults during the boot window between HC init and the
        # Number/Switch entities' async_added_to_hass push. None => use
        # module defaults (fresh install / test bench).
        # HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1 (D-b3): Rung-3 knob seeds
        # for the D5 duty-cycle window / caps / master enable. None
        # falls back to the module DUTY_CYCLE_* defaults (fresh install
        # / test bench). Live values are read via
        # self.duty_cycle_window_seconds / duty_cycle_coast_pct /
        # duty_cycle_shed_pct / d5_enabled.
        duty_cycle_window_minutes: int | None = None,
        duty_cycle_coast_pct: int | None = None,
        duty_cycle_shed_pct: int | None = None,
        d5_enabled: bool | None = None,
    ) -> None:
        """Initialize HVAC Coordinator."""
        super().__init__(
            hass,
            coordinator_id=HVAC_COORDINATOR_ID,
            name=HVAC_COORDINATOR_NAME,
            priority=HVAC_COORDINATOR_PRIORITY,
        )
        self._zone_manager = ZoneManager(hass)
        # v4.6.5.1 P1: track previous-cycle total_overrides so we can emit a
        # per-cycle DELTA rather than the cumulative-daily count (which is a
        # sawtooth that resets at midnight — late-day values fire ADVISORY just
        # from natural accumulation per v4.6.5 review B-M2).
        self._last_total_overrides_observed: int | None = None
        self._preset_manager = PresetManager(hass, max_sleep_offset=max_sleep_offset)
        self._override_arrester = OverrideArrester(
            hass, self._zone_manager,
            compromise_minutes=compromise_minutes,
            ac_reset_timeout=ac_reset_timeout,
            enabled=arrester_enabled,
        )
        self._override_arrester.ac_reset_enabled = ac_reset_enabled
        # HVAC W1-B §5.P1 (Also-1): PresetManager is built before the
        # arrester, so the S1 manual-rule gates are injected here. Until
        # this line runs `should_change_preset` fails CLOSED on `manual`.
        self._preset_manager.set_arrester(self._override_arrester)
        # HVAC W1-B D4a / C-2: the constructor is the load-bearing clamp
        # site — EVERY caller (setup path, tests) gets [5, 15].
        from .hvac_const import clamp_hvac_compromise_minutes as _clamp_cm
        compromise_minutes = _clamp_cm(compromise_minutes)
        self._override_arrester._compromise_minutes = compromise_minutes
        # Arrester Operator-Immunity: seed immune-persons list. Options-flow
        # edits refresh via set_immune_persons() from the options update
        # handler (mirrors the CM options-write-back pattern).
        self._override_arrester.set_immune_persons(arrester_immune_persons)
        # F8 (2026-08-07 fix-up cycle-4): register a single sunset-notify
        # callback so the timer-precise discharge path fires the NM note
        # instead of relying on the periodic sweep observing the return
        # value (which is False by the time the sweep runs, because the
        # timer already flipped OFF). Sweep + state-change paths no
        # longer branch on the return value; the callback is the single
        # dispatch site, with engagement-id dedup inside the arrester.
        def _fire_sunset_note(reason: str) -> None:
            try:
                _t = self.hass.async_create_task(
                    self._notify_temp_arrester_override_ended(reason)
                )
                self._pending_tasks.add(_t)
                _t.add_done_callback(self._pending_tasks.discard)
            except Exception:  # noqa: BLE001
                pass
            # HVAC W1-B fix-up 2 (LOW-3): an automatic sunset ends the
            # engagement, so the restart marker must not claim "was ACTIVE".
            self._clear_tao_restart_marker()
        self._override_arrester.set_on_sunset_notify(_fire_sunset_note)

        # HVAC W1/W2 finish D2: the arrester's reference-preset resolver.
        # preset=None -> the house's CURRENT S1 target preset
        # (`get_preset_for_house_state`, the startup-audit arithmetic); the
        # per-zone vacancy retreat stays S1's job (ruling Q4). Returns
        # (preset, cool, heat) or None.
        def _arrester_reference(
            zone_id: str, preset: str | None = None, arrival: bool = False,
        ):
            pm = self._preset_manager
            if arrival:
                # Q7 (fix-up 1): the ARRIVAL target, never away / vacation.
                target = pre_arrival_reference_preset(self._house_state)
            else:
                target = preset or pm.get_preset_for_house_state(
                    self._house_state or "home_day",
                )
            if not target:
                return None
            season = pm.current_season or pm.determine_season()
            sp = pm.get_seasonal_setpoints(target, season)
            if sp is None:
                return None
            cool, heat = sp
            return (target, cool, heat)
        self._override_arrester.set_baseline_resolver(_arrester_reference)

        # OVERRIDE-NOTIFY-1 (2026-08-08, operator-approved): pre-warn +
        # defer NM notes so the operator can re-engage before the auto-
        # release. Wrap both as background tasks (arrester calls the cb
        # sync from its timer / state-transition path).
        def _fire_expiry_warn_note(remaining_minutes: int) -> None:
            try:
                _t = self.hass.async_create_task(
                    self._notify_temp_arrester_override_expiring(
                        remaining_minutes
                    )
                )
                self._pending_tasks.add(_t)
                _t.add_done_callback(self._pending_tasks.discard)
            except Exception:  # noqa: BLE001
                pass

        def _fire_defer_note(remaining_minutes: int) -> None:
            try:
                _t = self.hass.async_create_task(
                    self._notify_temp_arrester_override_deferred(
                        remaining_minutes
                    )
                )
                self._pending_tasks.add(_t)
                _t.add_done_callback(self._pending_tasks.discard)
            except Exception:  # noqa: BLE001
                pass

        self._override_arrester.set_on_expiry_warn_notify(_fire_expiry_warn_note)
        self._override_arrester.set_on_defer_notify(_fire_defer_note)
        # AC-ramp master seed from CM option (reload-safe path). If
        # None is passed, retain the arrester's DEFAULT (False) so
        # fresh installs with no persisted option behave as before.
        if ac_ramp_master_enabled is not None:
            self._override_arrester._ramp_master_enabled = bool(
                ac_ramp_master_enabled
            )
        # D2-LOW-2 fix-up: seed comfort-delay knobs BEFORE any decision
        # cycle can read them. Closes the boot window between arrester
        # construction and Number.async_added_to_hass push.
        if comfort_grace_min is not None:
            self._override_arrester.set_comfort_grace_min(int(comfort_grace_min))
        if comfort_soc_floor_pct is not None:
            self._override_arrester.set_comfort_soc_floor_pct(
                int(comfort_soc_floor_pct)
            )
        # HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1 (D-b3): eager-seed D5
        # duty-cycle Rung-3 knobs. None -> module defaults so fresh
        # installs and unit tests match pre-cycle behavior.
        from .hvac_const import (
            DEFAULT_HVAC_DUTY_CYCLE_WINDOW_MIN as _DFLT_D5_WIN_MIN,
            DEFAULT_HVAC_DUTY_CYCLE_COAST_PCT as _DFLT_D5_COAST_PCT,
            DEFAULT_HVAC_DUTY_CYCLE_SHED_PCT as _DFLT_D5_SHED_PCT,
            DEFAULT_HVAC_D5_ENABLED as _DFLT_D5_ENABLED,
        )
        self._duty_cycle_window_min: int = (
            int(duty_cycle_window_minutes)
            if duty_cycle_window_minutes is not None
            else int(_DFLT_D5_WIN_MIN)
        )
        self._duty_cycle_coast_pct: int = (
            int(duty_cycle_coast_pct)
            if duty_cycle_coast_pct is not None
            else int(_DFLT_D5_COAST_PCT)
        )
        self._duty_cycle_shed_pct: int = (
            int(duty_cycle_shed_pct)
            if duty_cycle_shed_pct is not None
            else int(_DFLT_D5_SHED_PCT)
        )
        self._d5_enabled: bool = (
            bool(d5_enabled)
            if d5_enabled is not None
            else bool(_DFLT_D5_ENABLED)
        )
        # HVAC-GOVERNED-EXCURSION-1 §4.7 kill switch RETIRED (W1-B decision
        # 51, 2026-09-27): borrow rows are always recorded.
        # Episode-gated ledger cache: (zone_id, house_state) -> True while a
        # single per-(zone, house_state) episode of the off-phase condition
        # has already emitted its `preset_change_suppressed` row (mirror of
        # `_night_trust_logged`). Discharged on house_state transition
        # (below in the helper); a new house_state is a new episode.
        # NB: episode granularity is per-(zone, house_state), NOT a rolling
        # window — one row per house_state occupancy of the condition.
        # B11 (fix-up): explicit init of the discharge sentinel — no
        # empty-string ambiguity.
        # B1 (fix-up): per-zone emit throttle mirroring S10's
        # `_last_emitted_range` (hvac.py:2219). Suppresses re-emitting the
        # SAME (low, high) tuple across consecutive ticks — the operator's
        # thermostat sees ONE write per (low, high) change, not one per
        # tick. Cleared per-zone when runtime_exceeded drops false OR
        # house_state changes (see D5 branch clear + helper discharge).
        # Per-zone D3-guard skip flag exposed cross-tick for the D3 sensor
        # attribute (§3.3). Updated inside the D5 branch each tick.
        self._d3_skipped_current_tick: dict[str, bool] = {}
        # HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1 (D-b2): mirror flag for
        # the new D5 occupancy gate. Set True on ticks where coast-mode
        # + fused-occupied causes the D5 force-away to defer (no
        # thermostat write). Exposed on the HVAC status sensor next to
        # the D3-skip attribute. Episode-gated activity-log emission uses
        # `_d5_occ_defer_logged_episode` below.
        self._d5_occupancy_deferred_current_tick: dict[str, bool] = {}
        # Episode gate for the deferred-occupied activity-log row. Value
        # is (constraint_mode, house_state) at the last emit. C-L1
        # (fix-up) — CORRECTED COMMENT: the map is cleared ONLY when
        # `_handle_energy_constraint_change` sees a normal↔constrained
        # transition (see hvac.py:_handle_energy_constraint_change).
        # There is NO per-zone clear on runtime_exceeded drop today; a
        # stale (constraint_mode, house_state) key persists until the
        # next mode transition. Prevents per-tick firehose
        # (~480/night/zone) — mirror of _night_trust_logged.
        self._d5_occ_defer_logged_episode: dict[str, tuple] = {}
        self._fan_controller = FanController(
            hass, self._zone_manager,
            activation_delta=fan_activation_delta,
            deactivation_delta=fan_hysteresis,
            min_runtime=fan_min_runtime,
        )
        self._cover_controller = CoverController(
            hass, self._zone_manager,
            occupied_close_delta=occupied_cover_close_delta,
            # v4.5.10: master + 5 tunables forwarded to CoverController
            solar_gain_enabled=solar_gain_cover_enabled,
            cover_close_temp=cover_close_temp,
            cover_open_temp=cover_open_temp,
            cover_override_hours=cover_override_hours,
            solar_start_hour=cover_solar_start_hour,
            solar_end_hour=cover_solar_end_hour,
        )
        self._predictor = HVACPredictor(
            hass, self._zone_manager, self._preset_manager, self._override_arrester,
            net_power_entity=net_power_entity,
            # v4.5.10: 4 predictor tunables (banking + pre-cool + pre-heat)
            solar_bank_floor=solar_bank_floor,
            solar_bank_soc_min=solar_bank_soc_min,
            precool_forecast_high=precool_forecast_high,
            preheat_forecast_low=preheat_forecast_low,
        )
        # Tier 1 review CRITICAL-1: wire backref so banking release path
        # sources the TRUE baseline from `_last_emitted_range`.
        self._predictor.set_hvac_coord(self)
        # feature/freeze-floor: arrester reads freeze_active off HC for the
        # setpoint chokepoint (mirror of the predictor backref above).
        self._override_arrester.set_hvac_coord(self)
        # v4.7.8 D3: Egress Window HVAC Pause manager (sibling of OverrideArrester).
        # DB ref is wired in async_setup (mirror OverrideArrester pattern).
        self._egress_manager = EgressManager(
            hass, self._zone_manager,
            db=None,
            threshold_min=egress_threshold_min,
            resume_delay_min=egress_resume_delay_min,
            enabled=egress_pause_enabled,
        )
        self._egress_manager.set_hvac_coord(self)

        # HVAC W1-B D2.1 (M7 / N9a): zones S1 wrote THIS decision cycle.
        # Reset at cycle ENTRY (`_run_decision_cycle`); consumed by the
        # arrester's soft-nudge dispatch so a nudge never starts on a zone
        # whose preset write is still settling.
        self._zones_written_this_cycle: set[str] = set()
        # HVAC W1-B §5.P5: per-zone monotonic timestamps of S1 manual
        # write-throughs inside S1_RECLAIM_RATE_WINDOW_S + per-zone NM latch
        # (fires once per episode; discharges when the rate drops below N).
        self._s1_reclaim_ts: dict[str, list[float]] = {}
        self._s1_reclaim_rate_latched: set[str] = set()

        # ------------------------------------------------------------------
        # HVAC fast occupancy response (v5.103.20) — D2 event-driven zone
        # runs. Plan: docs/planning/PLANNING_hvac_fast_occupancy_response.md
        # REV 3 §5. ALL of this is in memory and resets on restart (plan
        # §5.7 "Restart"): a restart ends any trip early, the first full
        # cycle after boot-settle reschedules the exit timers, and the
        # nudge-skip seed is empty for the first tick (same as today).
        # ------------------------------------------------------------------
        # Kill switch (`switch.ura_hvac_coordinator_31_fast_room_response`,
        # default ON). OFF = listeners ignore refreshes, exit timers are
        # cancelled, behaviour is today's tick timing; the D1 evidence clock
        # in hvac_zones.py stays active either way.
        self._fast_path_enabled: bool = True
        self._tearing_down: bool = False
        # True ONLY while a fast run holds `_decision_cycle_lock` (set and
        # cleared inside the lock) — a waiting periodic cycle reads it.
        self._fast_path_running: bool = False
        # Zones with a fast run queued or running (per-zone dedup).
        self._fast_path_queued: set[str] = set()
        # Room-coordinator listener unsubs keyed by ROOM entry_id + the one
        # lifecycle-signal unsub.
        self._fast_path_room_unsubs: dict[str, Any] = {}
        self._fast_path_lifecycle_unsub: Any = None
        # Exit timers: unsub + scheduled due per zone; one-shot key per
        # vacancy episode `(zone_id, zone_release_at)`.
        self._fast_path_exit_unsubs: dict[str, Any] = {}
        self._fast_path_exit_due: dict[str, datetime] = {}
        self._fp_exit_fired: dict[str, tuple[str, datetime]] = {}
        # Per-room last evidence seen by the listener (None-rule, §5.4 step 3).
        self._fp_last_ev: dict[str, datetime] = {}
        # Per-zone last fast ENTRY run start (60 s limiter).
        self._fp_last_entry_run: dict[str, datetime] = {}
        # Per-zone last S1 write: (effective_preset, utc ts, reason). Seeds
        # `_zones_written_this_cycle` at cycle entry (§5.5), is the FIRST
        # key of the limiter exemption (§5.4) and of the quick-return
        # trip-wire (§5.7).
        self._zone_last_s1_write: dict[str, tuple[str, str, datetime]] = {}
        # Rolling-hour buckets (UTC datetimes) for the write ceiling and the
        # runaway guard; per-zone tick-only fallback until local midnight.
        self._fp_writes_bucket: dict[str, deque] = {}
        self._fp_runs_bucket: dict[str, deque] = {}
        self._fp_tripped_until: dict[str, datetime] = {}
        # Quick-return trip-wire: per-zone count today + per-zone NM latch.
        self._fp_quick_returns_today: dict[str, int] = {}
        self._fp_quick_return_date: str | None = None
        self._fp_quick_return_latched: set[str] = set()
        # UTC start of the most recent FULL cycle (lock rule §5.5: a waiting
        # periodic skips if a full cycle started after it was scheduled).
        self._last_full_cycle_started_at: datetime | None = None
        self._last_fast_edge_to_write_s: float | None = None
        # D5 (plan §5b / §5.7): APPLIED `vacant_past_grace` away instant per
        # zone (the quick-return alarm anchor; one alarm event per away),
        # the reason of the zone's last APPLIED away (ledger
        # `last_away_reason`), per-zone alarm split, the per-spell latch of
        # the `pending_arm_hold` suppressed row, and the arm re-check
        # timers keyed by ROOM entry_id.
        self._zone_vacancy_away_at: dict[str, datetime] = {}
        self._zone_vacancy_away_counted: dict[str, datetime] = {}
        self._zone_last_away_reason: dict[str, str] = {}
        self._fp_same_room_returns_today: dict[str, int] = {}
        self._fp_other_room_returns_today: dict[str, int] = {}
        # fix-up 2 (D-L3): "Skip entry wait" re-arms get their own counter.
        self._fp_skip_entry_wait_returns_today: dict[str, int] = {}
        self._pending_hold_logged: set[str] = set()
        self._pending_hold_cap_logged: set[str] = set()
        self._fast_path_arm_unsubs: dict[str, Any] = {}
        self._fast_path_arm_due: dict[str, datetime] = {}
        # (The four `_fast_*_today` DailyCounters are created below, after
        # the function-local `_DailyCounter` import — Bug Class #34.)

        # v4.0.15: Fan control toggle
        self._fan_control_enabled: bool = fan_control_enabled

        # Energy constraint state
        self._energy_constraint: EnergyConstraint | None = None
        self._energy_constraint_mode: str = "normal"
        self._energy_offset: float = 0.0
        # HVAC-DEMAND-KNOBS-AND-OBS-GAPS-1 D7 (v5.103.8): timestamp of
        # the most recent transition INTO the current
        # `_energy_constraint_mode`. Updated in `_handle_energy_constraint`
        # whenever `mode` changes; the "10 · Mode" sensor exposes
        # `energy_constraint_since` (ISO) + `energy_constraint_duration_s`
        # from this. RestoreEntity on the sensor persists it across
        # restarts (resume-if-same, reset-if-different).
        self._energy_constraint_mode_since: datetime | None = None
        # HVAC-DEMAND-KNOBS-AND-OBS-GAPS-1 D6 (v5.103.8): per-zone
        # cache of the most recent `reason=` argument observed at the
        # `emit_set_preset_mode` chokepoint. Populated from the
        # chokepoint's `_capture_preset_reason` on every successful
        # write, and hydrated on setup from the durable
        # ura_activity_log rows written by the S1 path
        # (`action='preset_change'`). Values: (reason: str, ts:
        # datetime). Non-S1 sites show `unknown` after restart until
        # the next write repopulates — see planning doc P3 scope.
        self._last_reason_by_zone: dict[str, tuple[str, datetime]] = {}

        # House state
        self._house_state: str = ""
        # Fan-trust review A-L1 2026-06-11: per (zone_id, house_state)
        # one-shot INFO de-noise for night-trust suppression. Without
        # this the trust block fires ~12/hr/zone all night long. Cleared
        # whenever the house_state changes.
        self._night_trust_logged: set[tuple[str, str]] = set()
        self._night_trust_logged_state: str = ""
        # HVAC-DEGRADED-ROOM-TRIPWIRE-1 fix-up round 3 (item 8, 2026-09-26):
        # episode-gate for the row-1 transient-room hold's durable log row.
        # Keyed (zone_id, house_state, target_preset); reset implicitly on
        # ZoneManager rebuild (coordinator lifetime).
        self._row1_hold_logged_episode: dict[str, tuple[str, str]] = {}

        # Decision cycle tracking
        self._last_evaluate: str = ""
        self._last_daily_reset: str = ""
        self._decision_timer_unsub = None
        self._pending_preset_change: bool = False

        # Observation mode — sensors run but no actions taken
        self._observation_mode: bool = False

        # v4.7.15 D6: HVAC consensus defer gate.
        # Master toggle (default ON). Operator can disable via
        # switch.ura_hvac_coordinator_hvac_consensus_defer_gate ("Wait for
        # Presence") for rollback without restart.
        # When ON, _apply_house_state_presets skips writes if signal_consensus
        # < 0.5 AND last house-state transition < 30 s ago.
        # v4.7.15 fix-up A5-H1: also implement asymmetric hysteresis — once
        # the gate engages, it stays engaged until consensus recovers above 0.7
        # (the "upper threshold"). This matches the README + plan spec and
        # prevents 0.5-line flap from turning the gate on/off within a single
        # consensus oscillation.
        self._defer_gate_enabled: bool = True
        self._d6_gate_engaged: bool = False  # asymmetric-hysteresis latch
        # RESTART-SAFETY-DOCTRINE-1 F14: daily counter exposed on the HVAC
        # compliance sensor for operator visibility.
        # restart: RESET WITH REASON — display-only counter; the D6 defer
        # gate itself is derived from live consensus, not this count.
        from .coordinator_diagnostics import DailyCounter as _DailyCounter
        self._d6_deferrals_today = _DailyCounter(
            name="hvac.d6_deferrals_today",
            persist=False,
            reason=(
                "display-only diagnostic counter; the D6 defer gate is a "
                "live-consensus derivation and does not consume this value"
            ),
        )

        # v4.7.1 fix-up D2/D3: Guest Mode Actuation Phase 1
        # Master kill switch — seeded True; runtime-toggled via
        # HVACGuestModeActuationSwitch (D3 switch on HVAC Coordinator device).
        self._guest_mode_actuation_enabled: bool = True
        # Per-zone last-emitted (cool_low, cool_high) to avoid redundant
        # set_temperature service calls when resolved range is unchanged.
        self._last_emitted_range: dict[str, tuple[float, float]] = {}

        # feature/freeze-floor: freeze-protection heat_low FLOOR latch.
        # Freeze arms when the best-available outdoor temp ≤ FREEZE_TRIGGER_TEMP
        # and stays armed (hysteresis) until outdoor > FREEZE_TRIGGER_TEMP +
        # FREEZE_TRIGGER_HYSTERESIS. RAM-only by design: on restart it
        # re-derives from the live temp on the next decision cycle (no
        # RestoreEntity → no Bug Class #52 unavailable-coercion risk).
        self._freeze_active: bool = False

        # Diagnostics
        self._decision_logger = None
        self._compliance = None
        self._outcome = None

        # v3.17.0: Zone Intelligence
        self._vacancy_grace = vacancy_grace
        self._vacancy_grace_constrained = vacancy_grace_constrained
        self._max_occupancy_hours = max_occupancy_hours
        self._zone_entry_dwell = zone_entry_dwell
        # v5.103.20 fix-up 1 (ruling 2): "52 · Return Window (min)" — live
        # source for the D5 room-only return exemption (0 = off).
        self._return_window_minutes = return_window_minutes
        # HVAC W1/W2 finish D5: "35 · Pre-Arrival Window (min)" — live source
        # for the pre-arrival timeout AND the pre-arrival borrow's max age
        # (D3). Clamped to [5, 110] on every read path.
        self._pre_arrival_window_minutes = clamp_hvac_pre_arrival_window_minutes(
            pre_arrival_window_minutes,
        )
        self._person_zone_map: dict[str, list[str]] = person_zone_map or {}
        self._last_good_person_zone_map: dict[str, list[str]] = {}
        self._pre_arrival_zones: set[str] = set()
        self._pre_arrival_persons: dict[str, str] = {}  # zone_id -> person_entity
        self._pre_arrival_start: dict[str, Any] = {}  # zone_id -> datetime
        # HVAC W1/W2 finish fix-up 1 (D-L5): arrival episodes whose pre-cool
        # already ran its course (max age) or was ended as inactive (ZI /
        # coordinator off). zone_id -> last trigger time. While a zone is
        # here, a repeat trigger inside the window only refreshes this time
        # and does NOT re-add the zone (no second pre-cool). Discharge:
        # HVAC arrival in the zone, or a whole window with no trigger.
        self._pre_arrival_spent: dict[str, Any] = {}
        # RESTART-SAFETY-DOCTRINE-1 F14. restart: RESET WITH REASON —
        # display-only counter surfaced via property vacancy_sweeps_today
        # and the HVAC diagnostics sensor. Zone-vacancy behaviour is
        # re-derived per decision cycle from live occupancy, so a reset
        # count on restart does not affect actuation.
        self._vacancy_sweeps_today = _DailyCounter(
            name="hvac.vacancy_sweeps_today",
            persist=False,
            reason="display counter; vacancy actuation is live-derived per cycle",
        )
        # HVAC fast occupancy response (v5.103.20) display counters.
        # restart: RESET WITH REASON — re-derived within a day; the durable
        # record of every fast write is its `preset_change` ledger row.
        self._fast_entry_runs_today = _DailyCounter(
            name="hvac.fast_entry_runs_today", persist=False,
            reason="display counter; fast runs are live-derived from room refreshes",
        )
        self._fast_exit_runs_today = _DailyCounter(
            name="hvac.fast_exit_runs_today", persist=False,
            reason="display counter; exit timers are re-armed by the first full cycle",
        )
        self._fast_writes_today = _DailyCounter(
            name="hvac.fast_writes_today", persist=False,
            reason="display counter; the durable record is the preset_change row",
        )
        self._fast_limited_today = _DailyCounter(
            name="hvac.fast_limited_today", persist=False,
            reason="display counter; a limited edge is discharged by the next tick",
        )
        self._zone_intelligence_enabled: bool = True
        self._decision_cycle_lock = asyncio.Lock()
        self._pending_tasks: set[asyncio.Task] = set()
        self._last_runtime_accumulation: Any = None  # UTC datetime

        # Cold-boot away-actuation storm mitigation (Gate 2 — HVAC first
        # decision cycle gate). Sibling of the presence dispatch gate
        # (presence.py): the storm may originate downstream of the presence
        # dispatch — HVAC's own first cold-boot decision cycle can fan out
        # turn_off / preset-apply before any house-state signal fires
        # (scenario γ in the planning doc). When False, _async_decision_cycle
        # short-circuits with an INFO log so the periodic timer's first tick
        # at boot is held until Predicate B (EVENT_HOMEASSISTANT_STARTED or
        # BOOT_SETTLE_TIMEOUT_SECONDS) elapses. Scoped to cold boot only.
        self._boot_settle_done: bool = False
        self._boot_settle_release_reason: str = "pending"
        self._boot_settle_hvac_suppressed: int = 0

        # HC Pre-Conditioning master enable (operator-facing toggle on
        # HC device). Seeded from CM options on init; the
        # HVACPreConditioningSwitch is the runtime source of truth via
        # options-write-back. Mirrors the EC Solar HVAC Banking sibling
        # pattern but lives on HC since pre-conditioning is HC-owned.
        # See PLANNING_hc_precool_toggle_oc_observability.md (D1).
        self._pre_conditioning_enabled: bool = bool(pre_conditioning_enabled)

        # v3.18.6: Pre-arrival source filter and tracking
        self._pre_arrival_enabled: bool = True
        self._pre_arrival_sources: list[str] = ["geofence", "ble", "camera_face"]
        self._last_pre_arrival_time: Any = None
        self._last_pre_arrival_source: str = ""
        self._last_pre_arrival_person: str = ""
        # RESTART-SAFETY-DOCTRINE-1 F14. restart: RESET WITH REASON —
        # display-only counter surfaced on HVAC diagnostics + read via
        # getattr in sensor.py (line ~12673). Pre-arrival dispatch is
        # driven by person state on live signals, not by this count.
        # HVAC-PRESET-LOCKOUT-TELEMETRY-1 -> HVAC W1-B §5.P1 (Also-3): per-zone
        # DEFERRAL episode start and a daily count of episodes (renamed from
        # `preset_lockouts_today`). Under Alt A a refusal is a DEFERRAL with a
        # named gate — a legitimate holder (person-protected hold / arrester
        # window / arrester disabled / live borrow) — not a lockout. Per-gate
        # breakdown in `_preset_deferrals_by_gate`.
        self._preset_lockout_since: dict[str, Any] = {}
        self._preset_deferrals_today = _DailyCounter(
            name="hvac.preset_deferrals_today",
            persist=False,
            reason=(
                "display/diagnostic counter; a deferral episode is re-detected "
                "on the next decision tick after a restart, so resetting to 0 "
                "loses only the running day's tally, not the condition"
            ),
        )
        self._preset_deferrals_by_gate: dict[str, int] = {}
        self._pre_arrival_triggers_today = _DailyCounter(
            name="hvac.pre_arrival_triggers_today",
            persist=False,
            reason="display counter; pre-arrival dispatch is signal-driven",
        )

        # CARRIER-STALE-POLL-REFRESH-1 (2026-09-09). Bounded reload of the
        # ha_carrier config entry when it goes stale. See hvac_const.py for
        # the knob ladder + kill-switch (cooldown=0). Per-entry asyncio.Lock
        # prevents overlapping reload attempts; DailyCounter caps the per-day
        # count; RAM stamp tracks cooldown. Restart: RESET WITH REASON —
        # cooldown is a debounce not a safety; the day-cap is a safety cap
        # not a budget, and a boot immediately after >=4 reloads still
        # surfaces via NM on the next stale episode.
        self._carrier_reload_lock = asyncio.Lock()
        self._last_carrier_reload_at: Any = None  # UTC datetime or None
        self._carrier_reloads_today = _DailyCounter(
            name="hvac.carrier_reloads_today",
            persist=False,
            reason=(
                "reload count is a safety cap (max/day), not a budget; "
                "on restart the next stale episode re-triggers evaluation "
                "and D3 NM will fire if reload is ineffective"
            ),
        )
        # Once True for the current local day, no more Carrier reloads fire
        # (D3 trip-wire fired). Reset on daily rollover.
        self._carrier_reload_suppressed_today: bool = False
        self._carrier_reload_suppress_date: str = ""
        # Consecutive stale ticks observed AFTER the most recent reload.
        self._carrier_stale_ticks_since_reload: int = 0
        # Snapshot consumed by HVACCarrierFreshnessSensor (per-zone).
        self._carrier_freshness_snapshot: dict[str, dict[str, Any]] = {}
        self._carrier_worst_age_s: float | None = None
        self._carrier_stale_zone_count: int = 0
        # C-HIGH-4 fix-up (2026-09-09): age-only stranded-stale NM. Fires
        # once per local day when a Carrier zone is genuinely stale but
        # cannot be corroborated / reloaded (e.g. SPAN dead OR reload
        # in-flight-fenced OR trip-wire suppressed). Ensures a stale
        # Carrier is ALWAYS surfaced even outside the reload path.
        self._carrier_stale_nm_date: str = ""
        # Options-flow blind-corroboration toggle (True = require SPAN
        # blind-corroboration for age-stale reload; False = age-only).
        from .hvac_const import (
            DEFAULT_HVAC_CARRIER_STALE_REQUIRE_BLIND_CORROBORATION,
        )
        self._carrier_require_blind_corroboration_default = (
            DEFAULT_HVAC_CARRIER_STALE_REQUIRE_BLIND_CORROBORATION
        )

        # v3.19.0: Camera zone map (diagnostic)
        self._camera_zone_map: dict[str, str] = {}

        # v3.18.2: Zone state persistence
        self._zone_state_store = Store(hass, 1, f"{DOMAIN}.hvac_zone_state")
        self._zone_state_save_counter: int = 0

        # HVAC-ANOMALY-BLIND-1 D2: event-driven short-cycle tracker.
        # `_short_cycles_today`: per-zone integer count of sub-
        #   SHORT_CYCLE_THRESHOLD_S on-cycles observed today (LOCAL day per
        #   dt_util.now()). PERSISTED via hvac_zone_state so a mid-day
        #   restart preserves the day's accumulated count and does not
        #   emit a partial-day observation. See rollover guard below.
        # `_short_cycles_today_date`: LOCAL-day ISO string ("YYYY-MM-DD")
        #   the counter belongs to. Empty on first boot; on first
        #   post-boot decision cycle we seed it to today and emit NOTHING.
        #   On subsequent-day rollover (prev != today), emit exactly once
        #   per zone THEN reset. This guard is on the tracker's OWN
        #   persisted date — NOT on `_last_daily_reset` (RAM-only, would
        #   fire an empty observation on every boot).
        # `_short_cycle_on_since`: per-zone datetime of the most recent
        #   idle→active transition. RESET on restart (not persisted) so
        #   that an on-cycle whose start predates the current boot cannot
        #   be observed as short — its duration is unknowable.
        self._short_cycles_today: dict[str, int] = {}
        self._short_cycles_today_date: str = ""
        self._short_cycle_on_since: dict[str, Any] = {}
        # Restored from persisted snapshot in _setup_short_cycle_tracker (see
        # async_setup); listener unsubs held on the shared _unsub_listeners
        # (drained by _cancel_listeners in async_teardown).
        self._short_cycle_listener_installed: bool = False

    @property
    def zone_manager(self) -> ZoneManager:
        """Return zone manager for sensor access."""
        return self._zone_manager

    @property
    def preset_manager(self) -> PresetManager:
        """Return preset manager for sensor access."""
        return self._preset_manager

    @property
    def override_arrester(self) -> OverrideArrester:
        """Return override arrester for sensor access."""
        return self._override_arrester

    @property
    def fan_controller(self) -> FanController:
        """Return fan controller for sensor access."""
        return self._fan_controller

    @property
    def cover_controller(self) -> CoverController:
        """Return cover controller for sensor access."""
        return self._cover_controller

    @property
    def predictor(self) -> HVACPredictor:
        """Return predictor for sensor access."""
        return self._predictor

    @property
    def freeze_active(self) -> bool:
        """Whether freeze-protection is currently armed (HC-owned).

        feature/freeze-floor: shared accessor read by the predictor and the
        override arrester so every `set_temperature` chokepoint emission knows
        whether to apply the freeze floor. HC latches this each cycle via
        `_update_freeze_active`; RAM-only by design.
        """
        return self._freeze_active

    @property
    def egress_manager(self) -> EgressManager:
        """Return egress manager for sensor / switch / number access."""
        return self._egress_manager

    @property
    def energy_constraint_mode(self) -> str:
        """Return current energy constraint mode."""
        return self._energy_constraint_mode

    # ------------------------------------------------------------------
    # ARREST-COMFORT-1 Cycle A (2026-08-10) — SOC + shed accessors.
    # BOTH the D1 grant-time SOC gate (inside OverrideArrester) AND the
    # D3 coast-precedence guard (this file, forced-away emit at :1445)
    # MUST read from these SAME accessors — single-accessor discipline
    # (planning §8 Sharpest Risk mitigation). No direct-to-energy reads
    # from either site.
    # ------------------------------------------------------------------
    @property
    def battery_soc(self) -> float | None:
        """Battery SOC (%) from the last EnergyConstraint push. None until
        the first constraint arrives OR when the Envoy is blind (see
        `battery_blind`)."""
        c = self._energy_constraint
        if c is None:
            return None
        soc = getattr(c, "soc", None)
        try:
            return float(soc) if soc is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def battery_blind(self) -> bool:
        """True when the SOC read cannot be trusted (no constraint yet OR
        SOC field absent). Fail-closed direction: treat as below-floor for
        comfort-delay grant decisions.
        """
        return self.battery_soc is None

    @property
    def comfort_grace_min(self) -> int:
        """Fix-up A-HIGH-1: live rung-3 comfort-grace knob. Delegates to
        the arrester (single source of truth). Falls back to module
        constant when the Number entity hasn't seeded yet."""
        try:
            return int(self._override_arrester._get_grace_min())
        except Exception:  # noqa: BLE001
            return int(COMFORT_GRACE_MIN)

    @property
    def comfort_soc_floor_pct(self) -> int:
        """Fix-up A-HIGH-1: live rung-3 SOC-floor knob. D3 guard reads
        THIS (not the module constant) so operator changes take effect
        without restart."""
        try:
            return int(self._override_arrester._get_soc_floor())
        except Exception:  # noqa: BLE001
            return int(COMFORT_SOC_FLOOR_PCT)

    # ------------------------------------------------------------------
    # HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1 (D-b3) — Rung-3 D5 knobs.
    # Accessors + setters. Accumulator + enforcement read the LIVE
    # value from these properties (not the module constant), so
    # operator tuning takes effect without a restart.
    # ------------------------------------------------------------------
    @property
    def duty_cycle_window_seconds(self) -> int:
        try:
            return max(1, int(self._duty_cycle_window_min) * 60)
        except Exception:  # noqa: BLE001
            from .hvac_const import DUTY_CYCLE_WINDOW_SECONDS as _W
            return int(_W)

    def set_duty_cycle_window_minutes(self, value: int) -> None:
        try:
            v = int(value)
        except (TypeError, ValueError):
            return
        self._duty_cycle_window_min = max(1, v)
        _LOGGER.info(
            "HVAC D5: duty_cycle_window_minutes -> %d",
            self._duty_cycle_window_min,
        )

    @property
    def duty_cycle_coast_pct(self) -> int:
        return int(self._duty_cycle_coast_pct)

    def set_duty_cycle_coast_pct(self, value: int) -> None:
        try:
            v = int(value)
        except (TypeError, ValueError):
            return
        self._duty_cycle_coast_pct = max(0, min(100, v))
        _LOGGER.info(
            "HVAC D5: duty_cycle_coast_pct -> %d%s",
            self._duty_cycle_coast_pct,
            " (coast D5 disabled)" if self._duty_cycle_coast_pct == 0 else "",
        )

    @property
    def duty_cycle_shed_pct(self) -> int:
        return int(self._duty_cycle_shed_pct)

    def set_duty_cycle_shed_pct(self, value: int) -> None:
        try:
            v = int(value)
        except (TypeError, ValueError):
            return
        self._duty_cycle_shed_pct = max(0, min(100, v))
        _LOGGER.info(
            "HVAC D5: duty_cycle_shed_pct -> %d%s",
            self._duty_cycle_shed_pct,
            " (shed D5 disabled)" if self._duty_cycle_shed_pct == 0 else "",
        )

    @property
    def d5_enabled(self) -> bool:
        return bool(self._d5_enabled)

    def set_d5_enabled(self, value: bool) -> None:
        self._d5_enabled = bool(value)
        _LOGGER.info(
            "HVAC D5: d5_enabled -> %s%s",
            self._d5_enabled,
            "" if self._d5_enabled else " (D5 disabled entirely)",
        )

    @property
    def shed_active(self) -> bool:
        """True when the current energy constraint is `shed`. Consumed by
        the D3 coast-precedence guard AND pushed into the arrester's
        comfort-request gate (shed dominates comfort — rev-2 H3)."""
        return self._energy_constraint_mode == "shed"

    @property
    def observation_mode(self) -> bool:
        """Whether HVAC observation mode is active."""
        return self._observation_mode

    @observation_mode.setter
    def observation_mode(self, value: bool) -> None:
        """Set HVAC observation mode."""
        self._observation_mode = value
        _LOGGER.info("HVAC Coordinator observation mode: %s", value)

    @property
    def fan_control_enabled(self) -> bool:
        """Whether FanController temperature-based fan management is active."""
        return self._fan_control_enabled

    @fan_control_enabled.setter
    def fan_control_enabled(self, value: bool) -> None:
        """Set fan control enabled state."""
        self._fan_control_enabled = value
        _LOGGER.info("HVAC Fan Control: %s", "enabled" if value else "disabled")

    @property
    def zone_intelligence_enabled(self) -> bool:
        """Whether Zone Intelligence features are active."""
        return self._zone_intelligence_enabled

    @zone_intelligence_enabled.setter
    def zone_intelligence_enabled(self, value: bool) -> None:
        """Set Zone Intelligence enabled state."""
        self._zone_intelligence_enabled = value
        _LOGGER.info("HVAC Zone Intelligence: %s", "enabled" if value else "disabled")

    @property
    def pre_conditioning_enabled(self) -> bool:
        """Whether HVAC pre-conditioning master gate is ON.

        Read by HVACPredictor._is_pre_conditioning_enabled() to short-circuit
        the entire _check_pre_conditioning branch chain (weather pre-cool,
        solar banking, pre-arrival, pre-heat).
        """
        return self._pre_conditioning_enabled

    @pre_conditioning_enabled.setter
    def pre_conditioning_enabled(self, value: bool) -> None:
        """Set HC pre-conditioning master enable."""
        self._pre_conditioning_enabled = bool(value)
        _LOGGER.info(
            "HVAC Pre-Conditioning master: %s",
            "enabled" if value else "disabled",
        )

    @property
    def pre_arrival_enabled(self) -> bool:
        """Whether HVAC pre-arrival is active."""
        return self._pre_arrival_enabled

    @pre_arrival_enabled.setter
    def pre_arrival_enabled(self, value: bool) -> None:
        """Set HVAC pre-arrival enabled state.

        v3.18.6: Also syncs to person_coordinator so BLE detection
        respects the same toggle.
        """
        self._pre_arrival_enabled = value
        _LOGGER.info("HVAC pre-arrival: %s", "enabled" if value else "disabled")
        # Sync to person_coordinator
        pc = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if pc:
            pc._pre_arrival_enabled = value

    @property
    def vacancy_sweeps_today(self) -> int:
        """Return count of vacancy sweeps executed today."""
        return self._vacancy_sweeps_today.value

    @property
    def energy_offset(self) -> float:
        """Return current energy setpoint offset."""
        return self._energy_offset

    @property
    def house_state(self) -> str:
        """Return current house state."""
        return self._house_state

    async def async_setup(self) -> None:
        """Set up HVAC Coordinator."""
        _LOGGER.info("HVAC Coordinator: starting setup")

        # ARREST-COMFORT-1 Cycle A §4.6 + fix-up A-HIGH-1: WARN when the
        # LIVE SOC floor is set below 20% (deliberate blackout-risk
        # acceptance — operator override of the safety default). `0` is
        # the documented kill-switch value (SOC gate disabled entirely);
        # anything in (0, 20) is a near-blackout risk the operator should
        # see in the logs. The same evaluation runs on every setter change
        # (see OverrideArrester.set_comfort_soc_floor_pct).
        try:
            _live_floor = int(self.comfort_soc_floor_pct)
            if 0 < _live_floor < 20:
                _LOGGER.warning(
                    "ARREST-COMFORT-1: comfort_soc_floor_pct=%d — below "
                    "the 20%% safety threshold. Comfort-delay grants will "
                    "consume battery reserves that may be needed to weather "
                    "a grid outage. Confirm this is intentional.",
                    _live_floor,
                )
        except Exception:  # noqa: BLE001 — never let a log call block setup
            pass

        # Cold-boot away-actuation storm mitigation — Gate 2 init.
        # Scope to cold boot only: if HA core is already RUNNING (options-flow
        # reload), release the gate immediately so the reload's first decision
        # cycle actuates normally. Otherwise schedule both Predicate B release
        # paths (EVENT_HOMEASSISTANT_STARTED + failsafe timeout).
        try:
            _ha_running = bool(getattr(self.hass, "is_running", False))
        except Exception:  # noqa: BLE001
            _ha_running = False
        if _ha_running:
            self._boot_settle_done = True
            self._boot_settle_release_reason = "not_cold_boot"
            _LOGGER.info(
                "HVAC boot-settle: HA already RUNNING — gate released at "
                "setup (reload path, not cold boot)"
            )
        else:
            from ..const import BOOT_SETTLE_TIMEOUT_SECONDS  # noqa: PLC0415
            from homeassistant.helpers.event import async_call_later  # noqa: PLC0415
            try:
                from homeassistant.const import EVENT_HOMEASSISTANT_STARTED  # noqa: PLC0415
            except Exception:  # noqa: BLE001
                EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"
            try:
                _unsub_started = self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED,
                    self._on_ha_started_release_boot_settle,
                )
                self._unsub_listeners.append(_unsub_started)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "HVAC boot-settle: failed to register "
                    "EVENT_HOMEASSISTANT_STARTED listener",
                    exc_info=True,
                )
            try:
                _unsub_to = async_call_later(
                    self.hass,
                    BOOT_SETTLE_TIMEOUT_SECONDS,
                    self._timeout_release_boot_settle,
                )
                self._unsub_listeners.append(_unsub_to)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "HVAC boot-settle: failed to register failsafe timeout",
                    exc_info=True,
                )

        # Discover zones
        zone_count = await self._zone_manager.async_discover_zones()
        if zone_count == 0:
            _LOGGER.warning(
                "HVAC: No zones with thermostats found. "
                "Configure CONF_ZONE_THERMOSTAT on zone entries."
            )

        # v3.18.2: Restore zone state from persistent storage
        stored = None
        try:
            stored = await self._zone_state_store.async_load()
            if stored and isinstance(stored, dict):
                count = self._zone_manager.restore_state_snapshot(stored)
                _LOGGER.info("HVAC: Restored zone state for %d zones", count)
        except Exception as e:
            _LOGGER.warning("HVAC: Failed to restore zone state: %s", e)

        # HVAC-ANOMALY-BLIND-1 D2: restore persisted short-cycle counter
        # AND install the event-driven listener on each zone's climate
        # entity. Runs AFTER zone discovery so `self._zone_manager.zones`
        # is populated and AFTER restore_state_snapshot so the counter is
        # available if it survived a mid-day restart. The tracker's
        # `_short_cycle_on_since` map is intentionally NOT restored — an
        # on-cycle whose start predates the current boot cannot have its
        # duration measured, so we discard rather than fabricate.
        if stored and isinstance(stored, dict):
            try:
                sc_state = stored.get("__short_cycles_today", {}) or {}
                if isinstance(sc_state, dict):
                    counts = sc_state.get("counts", {})
                    date = sc_state.get("date", "")
                    if isinstance(counts, dict) and isinstance(date, str):
                        self._short_cycles_today = {
                            str(k): int(v) for k, v in counts.items()
                            if isinstance(v, (int, float))
                        }
                        self._short_cycles_today_date = date
                        _LOGGER.info(
                            "HVAC: Restored short-cycle counter (date=%s, "
                            "counts=%s)",
                            date, self._short_cycles_today,
                        )
            except Exception as e:
                _LOGGER.warning(
                    "HVAC: Failed to restore short-cycle counter: %s", e,
                )
        # HVAC W1-B D-P1 / D-P1a (N8): rehydrate the arrester's persisted
        # records HERE — in the `async_setup` load path, BEFORE the first
        # decision cycle below — so gate (a/b) is armed on S1's first tick.
        await self._rehydrate_arrester_state(stored)
        self._install_short_cycle_listeners()

        # v3.18.5: Build person-zone map from zone configs
        new_map = self._build_person_zone_map()
        if new_map:
            self._person_zone_map = new_map
            self._last_good_person_zone_map = dict(new_map)
            _LOGGER.info("HVAC: Person-zone map built: %s", new_map)
        else:
            # Fallback chain: cache -> DB
            if self._last_good_person_zone_map:
                self._person_zone_map = self._last_good_person_zone_map
                _LOGGER.warning("HVAC: Zone person config empty — using cached map")
            elif stored and isinstance(stored, dict):
                db_map = stored.get("__person_zone_map", {})
                if db_map and isinstance(db_map, dict):
                    self._person_zone_map = db_map
                    self._last_good_person_zone_map = dict(db_map)
                    _LOGGER.warning("HVAC: Using DB-persisted person-zone map")
                else:
                    self._person_zone_map = {}
                    _LOGGER.info("HVAC: No person-zone mapping configured")
            else:
                self._person_zone_map = {}

        # v3.18.6: Read pre-arrival source filter from CM config
        from .hvac_const import CONF_PRE_ARRIVAL_SOURCES, DEFAULT_PRE_ARRIVAL_SOURCES
        from ..const import CONF_ENTRY_TYPE, ENTRY_TYPE_COORDINATOR_MANAGER
        for ce in self.hass.config_entries.async_entries(DOMAIN):
            if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                cm_config = {**ce.data, **ce.options}
                self._pre_arrival_sources = cm_config.get(
                    CONF_PRE_ARRIVAL_SOURCES, DEFAULT_PRE_ARRIVAL_SOURCES
                )
                break
        _LOGGER.info("HVAC: Pre-arrival sources=%s", self._pre_arrival_sources)

        # v3.19.0: Build camera zone map
        self._camera_zone_map = self._build_camera_zone_map()
        if self._camera_zone_map:
            _LOGGER.info("HVAC: Camera-zone map built: %s", self._camera_zone_map)

        # Determine season and log
        season = self._preset_manager.determine_season()
        _LOGGER.info("HVAC: Season=%s, zones=%d", season, zone_count)

        # Subscribe to house state changes
        self._unsub_listeners.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_HOUSE_STATE_CHANGED,
                self._handle_house_state_changed,
            )
        )

        # Subscribe to energy constraints
        self._unsub_listeners.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_ENERGY_CONSTRAINT,
                self._handle_energy_constraint,
            )
        )

        # HVAC-PRECOOL-NO-CONSTRAINT-POST-BOOT-1: producer-owned pull.
        # EC is registered BEFORE HVAC (__init__.py:3759 vs ~4041) and
        # CoordinatorManager.async_start runs setups sequentially, so EC's
        # boot decision cycle fires SIGNAL_ENERGY_CONSTRAINT before this
        # subscribe is in place. async_dispatcher_send is fire-and-forget
        # (no replay) and the change-gate then suppresses re-emits until
        # the mode changes (evening coast) — leaving _energy_constraint
        # None all afternoon on restart-days and dead-arming Path A pre-cool.
        # Pull the current constraint from EC now that the subscribe is up.
        # Ordering-TOLERANT (a reorder yields a default-valued payload,
        # silently inert — not a loud failure) and idempotent with the
        # next real signal (_handle_energy_constraint is a setter).
        try:
            _cm = self.hass.data.get("universal_room_automation", {}).get(
                "coordinator_manager"
            )
            _energy = _cm.coordinators.get("energy") if _cm else None
            if _energy is not None and hasattr(_energy, "current_energy_constraint"):
                _seed = _energy.current_energy_constraint()
                if _seed is not None:
                    self._handle_energy_constraint(_seed)
                    _LOGGER.info(
                        "HVAC: Seeded energy constraint at setup mode=%s offset=%.1f reason=%s",
                        getattr(_seed, "mode", None),
                        getattr(_seed, "setpoint_offset", 0.0) or 0.0,
                        getattr(_seed, "reason", None),
                    )
                else:
                    _LOGGER.debug("HVAC: Energy pull returned None; keeping default constraint")
            else:
                _LOGGER.debug(
                    "HVAC: Energy coordinator unavailable at setup; skipping constraint pull"
                )
        except Exception as _e:
            _LOGGER.debug(
                "HVAC: Energy constraint pull at setup failed (non-fatal): %s", _e
            )

        # v3.17.0 D3: Subscribe to person arriving signals
        self._unsub_listeners.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_PERSON_ARRIVING,
                self._handle_person_arriving,
            )
        )

        # HVAC fast occupancy response (v5.103.20, plan §5.4): room-refresh
        # listeners — subscribe to the lifecycle signal FIRST, then
        # enumerate existing rooms (attach is idempotent).
        self._setup_fast_path_listeners()

        # v3.22.0 D2: Subscribe to safety hazard signals
        self._unsub_listeners.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_SAFETY_HAZARD,
                self._handle_safety_hazard,
            )
        )

        # Zone Delete Flow (fix-up R4 / B-HIGH-1): prune the deleted zone
        # from the in-memory ``ZoneManager.zones`` dict AND rewrite the
        # persisted ``_zone_state_store`` snapshot so a restart doesn't
        # RESURRECT the zone via ``restore_state_snapshot`` (hvac.py:503).
        # Unsub tracked via ``_unsub_listeners`` per Bug Class #50.
        self._unsub_listeners.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_ZM_ZONES_UPDATED,
                self._handle_zm_zones_updated,
            )
        )

        # Set up diagnostics
        try:
            await self._setup_diagnostics()
        except Exception as e:
            _LOGGER.warning("HVAC: Diagnostics setup failed (non-fatal): %s", e)

        # Read initial house state from presence coordinator
        # v3.21.0 D2: Wait for Presence ready event to avoid reading stale
        # default state during startup race.
        manager = self.hass.data.get("universal_room_automation", {}).get(
            "coordinator_manager"
        )
        if manager:
            presence = manager.coordinators.get("presence")
            if presence and hasattr(presence, "_ready_event"):
                try:
                    await asyncio.wait_for(presence._ready_event.wait(), timeout=10.0)
                except asyncio.TimeoutError:
                    _LOGGER.warning(
                        "HVAC: Timed out waiting for Presence — using default state"
                    )
            # v5.37.0 (House-State Rung 1): the prior boot-seed read
            # ``presence._house_state``, an attribute that never existed;
            # the branch was dead and HVAC's initial ``_house_state`` was
            # only ever updated via the live SIGNAL_HOUSE_STATE_CHANGED
            # subscription below. Seed from the canonical source instead
            # (CoordinatorManager.house_state — the HouseStateMachine's
            # StrEnum property). Live-signal behavior is unchanged.
            try:
                _seed = getattr(manager, "house_state", None)
                if _seed is not None:
                    self._house_state = str(_seed)
                    _LOGGER.info("HVAC: Initial house state = %s", self._house_state)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("HVAC: house_state boot-seed unavailable (non-fatal)", exc_info=True)

        # Initial zone update
        self._zone_manager.update_all_zones()
        self._zone_manager.update_room_conditions(house_state=self._house_state)
        # HVAC-DEGRADED-ROOM-TRIPWIRE-1 REV-2 D3/F9: drain async NM events
        # queued by the sync producer (per-boot debounced inside ZM).
        await self._drain_hvac_degraded_room_events()

        # Discover fans and covers
        fan_rooms = self._fan_controller.discover_fans()
        cover_count = self._cover_controller.discover_covers()
        _LOGGER.info("HVAC: %d fan rooms, %d managed covers", fan_rooms, cover_count)
        self._cover_controller.setup_listeners()

        # Share outdoor temp sensor with predictor
        if self._cover_controller._outdoor_temp_entity:
            self._predictor.set_outdoor_temp_entity(
                self._cover_controller._outdoor_temp_entity
            )

        # Start override arrester (event-driven)
        self._override_arrester.setup()
        self._startup_audit_done = False

        # v4.5.11: Wire database into OverrideArrester so persistent caps
        # + lockout flags + event log have a place to live. Without this,
        # the ramp-down feature is inert (caps not enforced, no events
        # logged) — graceful degrade, not a crash.
        # v4.5.11.2 fix: DOMAIN is already imported at module-level (line 27).
        # Re-importing it here would make DOMAIN a function-local variable
        # for the entire async_setup body, which would shadow the module
        # name and break the EARLIER line `async_entries(DOMAIN)` at the
        # top of this method with UnboundLocalError. Bug Class #34.
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if db is not None:
            self._override_arrester.set_database(db)
            _LOGGER.info(
                "HVAC: OverrideArrester wired to database for AC ramp-down state"
            )
        else:
            _LOGGER.warning(
                "HVAC: database not available — AC ramp-down feature inert"
            )

        # HVAC-GOVERNED-EXCURSION-1 D2 — bind primitive to hass+db and run
        # the startup audit (§4.4 restart interaction). Guarded because
        # a DB-less bench mode still runs the coordinator; the primitive
        # then works in-memory only (no restart-safety, but no crashes).
        try:
            from . import hvac_excursion as _ex_mod
            _ex_mod.bind(self.hass, db)
            if db is not None:
                await _ex_mod.async_startup_excursion_audit(self.hass, self)
            # HVAC W1/W2 finish D1: seed the RAM record of URA's setpoint
            # writes from every rehydrated borrow row, so the echo of a
            # pre-restart borrow write is not read as a person. (L2,
            # accepted: the arrester listener went live above; the first
            # post-restart event has old_state=None and is dropped.)
            self._seed_ura_setpoint_record_from_rows()
        except Exception as _ex_boot_exc:  # noqa: BLE001
            _LOGGER.warning(
                "HVAC: excursion primitive bind/audit failed (non-fatal): %s",
                _ex_boot_exc,
            )

        # D1 excursion auto-release sweep (HVAC-EXCURSION-D1-ONLY,
        # 2026-08-26). Wire-in extracted into a helper so the wire-in
        # anchor test (C-8) can neuter one call site and see RED.
        # ORDERING (MEDIUM fix in-cycle): scheduled AFTER
        # async_startup_excursion_audit above, so the interval sweep
        # cannot fire while the boot audit is still awaiting a blocking
        # stale-boot BANKING preset emit — which would otherwise let
        # the sweep re-collect the same row (the B3 _sweep_running guard
        # protects sweep vs sweep only, not sweep vs boot audit).
        self._schedule_excursion_autorelease_sweep()

        # v4.7.8 D6: Wire DB into EgressManager and rehydrate state BEFORE
        # the periodic decision-cycle timer is registered. Bug Class #14 —
        # first tick post-restart MUST see _rehydrate_done=True so it can
        # act on the restored counters / paused dict / cooldowns.
        if db is not None:
            self._egress_manager.set_database(db)
            try:
                await self._egress_manager.async_rehydrate_from_db()
            except Exception:
                _LOGGER.warning(
                    "HVAC: EgressManager rehydrate failed (non-fatal)",
                    exc_info=True,
                )
        else:
            _LOGGER.warning(
                "HVAC: database not available — EgressManager inert"
            )
        # HVAC-DEMAND-KNOBS-AND-OBS-GAPS-1 D6 hydration (v5.103.8):
        # populate `_last_reason_by_zone` from durable activity-log
        # rows written by the S1 path (`action='preset_change'`). This
        # is the ONLY path that logs preset writes durably today (see
        # planning §P3); non-S1 sites remain `unknown` post-restart
        # until the next write on that zone. Best-effort; failure is
        # non-fatal (sensor falls back to `unknown`).
        if db is not None:
            try:
                await self._hydrate_last_reason_by_zone(db)
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "HVAC: preset-reason hydration failed (non-fatal)",
                    exc_info=True,
                )
        # v4.7.8 D8: cross-rule precedence — let OverrideArrester +
        # HVACPredictor see paused zones so they skip cleanly.
        self._override_arrester.set_egress_manager(self._egress_manager)
        self._predictor.set_egress_manager(self._egress_manager)

        # Start periodic decision cycle (HVAC_DECISION_TICK; see hvac_const).
        self._decision_timer_unsub = async_track_time_interval(
            self.hass,
            self._async_decision_cycle,
            HVAC_DECISION_TICK,
        )

        # Run initial cycle
        await self._async_decision_cycle()

        _LOGGER.info("HVAC Coordinator: setup complete")

        # v4.7.3.1: signal HVAC-ready so bespoke HVAC switches can complete
        # deferred restores (Bug Class #5).  Mirrors SIGNAL_ENERGY_COORDINATOR_READY
        # in energy.py — one-shot fire-and-forget after setup completes.
        try:
            from .signals import SIGNAL_HVAC_COORDINATOR_READY
            async_dispatcher_send(self.hass, SIGNAL_HVAC_COORDINATOR_READY)
            _LOGGER.debug("SIGNAL_HVAC_COORDINATOR_READY dispatched")
        except Exception:
            _LOGGER.debug(
                "SIGNAL_HVAC_COORDINATOR_READY dispatch failed (non-fatal)",
                exc_info=True,
            )

        # v4.7.8 fix-up B-H2 / B-H3: force-release the EgressManager
        # initial-restore gate after a bounded delay so the next periodic
        # tick (+5 min) can fire even if the master switch / Numbers never
        # land their RestoreEntity callback (e.g., entity deleted, signal
        # subscription dropped). Without this, async_tick would stay gated
        # indefinitely after restart. 60s is well past normal RestoreEntity
        # completion (typically <1s after async_added_to_hass) but tight
        # enough that the second tick still acts on saved values.
        try:
            # (async_call_later is a module-level import — v5.103.20 removed
            # the function-local re-import here, Bug Class #34.)

            @callback
            def _release_egress_gate(_now=None):
                try:
                    self._egress_manager.force_release_initial_restore_gate()
                except Exception:
                    _LOGGER.debug(
                        "HVAC: egress force-release failed (non-fatal)",
                        exc_info=True,
                    )

            # UNLOAD-SYMMETRY-TASK-HYGIENE-1: retain the one-shot unsub on
            # ``self._unsub_listeners`` (drained by ``_cancel_listeners`` in
            # ``async_teardown``) so a reload inside the 60s window cancels
            # the pending callback instead of firing against a torn-down
            # ``_egress_manager``.
            self._unsub_listeners.append(
                async_call_later(self.hass, 60, _release_egress_gate)
            )
        except Exception:
            _LOGGER.debug(
                "HVAC: scheduling egress gate release failed (non-fatal)",
                exc_info=True,
            )

    def _schedule_excursion_autorelease_sweep(self) -> None:
        """D1 wire-in: schedule the periodic excursion auto-release sweep.

        Ticks every ``EXCURSION_AUTORELEASE_SWEEP_S``. Each tick closes
        borrows whose age exceeds ``duration_s + SLACK`` (bounded by
        ``EXCURSION_LEASE_MAX_S``) via ``_auto_return``, writing an
        ended-event row and restoring ``pre_preset`` (or skipping the
        preset write when ``pre_preset`` is ``manual``/``None``/``""``
        per HIGH-1).

        The unsub is appended to ``self._unsub_listeners`` per Bug Class
        #50 so ``async_unload`` cancels it. B3 re-entrancy and B6
        torn-down-coord guards live inside ``_auto_release_sweep``.
        """
        try:
            from . import hvac_excursion as _ex_mod_sweep  # noqa: PLC0415
            from datetime import timedelta as _td  # noqa: PLC0415

            async def _sweep_tick(_now) -> None:
                try:
                    await _ex_mod_sweep._auto_release_sweep(coord=self)
                except Exception as _exc:  # noqa: BLE001
                    _LOGGER.debug(
                        "excursion.sweep tick failed: %s", _exc,
                    )

            self._unsub_listeners.append(
                async_track_time_interval(
                    self.hass,
                    _sweep_tick,
                    _td(seconds=_ex_mod_sweep.EXCURSION_AUTORELEASE_SWEEP_S),
                )
            )
        except Exception as _sweep_exc:  # noqa: BLE001
            _LOGGER.warning(
                "excursion.sweep: failed to schedule periodic auto-release "
                "sweep: %s — D1 auto-release falls back to boot audit + "
                "stale-row NM notice only.",
                _sweep_exc,
            )

    async def _setup_diagnostics(self) -> None:
        """Initialize diagnostics components."""
        from .coordinator_diagnostics import (
            AnomalyDetector,
            ComplianceTracker,
            DecisionLogger,
        )
        from ..const import (  # noqa: PLC0415
            CONF_HVAC_ANOMALY_SENSITIVITY,
            DEFAULT_ANOMALY_SENSITIVITY,
            ANOMALY_SENSITIVITY_MULTIPLIERS,
            CONF_ENTRY_TYPE,
            ENTRY_TYPE_COORDINATOR_MANAGER,
        )

        self._decision_logger = DecisionLogger(self.hass)
        self._compliance = ComplianceTracker(self.hass)
        # v4.6.3 D10: Read sensitivity bucket from CM entry options.
        _hvac_sensitivity = DEFAULT_ANOMALY_SENSITIVITY
        try:
            for _ce in self.hass.config_entries.async_entries(DOMAIN):
                if _ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                    _hvac_sensitivity = {**_ce.data, **_ce.options}.get(
                        CONF_HVAC_ANOMALY_SENSITIVITY, DEFAULT_ANOMALY_SENSITIVITY
                    )
                    break
        except Exception:
            pass
        _hvac_sensitivity_mult = ANOMALY_SENSITIVITY_MULTIPLIERS.get(_hvac_sensitivity, 1.0)
        self.anomaly_detector = AnomalyDetector(
            hass=self.hass,
            coordinator_id=HVAC_COORDINATOR_ID,
            metric_names=HVAC_METRICS,
            minimum_samples=HVAC_ANOMALY_MIN_SAMPLES,
            sensitivity_multiplier=_hvac_sensitivity_mult,
            # v4.6.5.3 surface fix: persist-suppressed metrics don't count
            # toward get_worst_severity() so the per-coordinator anomaly
            # sensor reflects anomaly_log-eligible signal.
            suppressed_metric_names=HVAC_SUPPRESSED_FROM_PERSISTENCE,
            # HVAC-ANOMALY-BLIND-1 D1a: short_cycle_rate is 1 obs/day/zone;
            # 336-day maturation is infeasible. Override to 14 days —
            # matches the probe window that established the fixture.
            minimum_samples_by_metric={
                "short_cycle_rate": HVAC_SHORT_CYCLE_MIN_SAMPLES,
            },
        )
        try:
            await self.anomaly_detector.load_baselines()
        except Exception as e:
            _LOGGER.debug("HVAC: Could not load anomaly baselines: %s", e)

    # ------------------------------------------------------------------
    # Cold-boot away-actuation storm mitigation — Gate 2 release callbacks
    # ------------------------------------------------------------------
    def _release_boot_settle(self, reason: str) -> None:
        """Idempotent gate-flip used by both Predicate B release paths."""
        if self._boot_settle_done:
            return
        self._boot_settle_done = True
        self._boot_settle_release_reason = reason
        if reason == "timeout":
            from ..const import BOOT_SETTLE_TIMEOUT_SECONDS  # noqa: PLC0415
            _LOGGER.warning(
                "HVAC boot-settle: released via TIMEOUT after %ss — first "
                "decision cycle will now proceed",
                BOOT_SETTLE_TIMEOUT_SECONDS,
            )
        else:
            _LOGGER.info(
                "HVAC boot-settle: released via %s — first decision cycle "
                "will now proceed",
                reason,
            )
        # Reviewer A HIGH-A2 (2026-06-04): if we suppressed the boot kickoff,
        # re-run one decision cycle rather than waiting up to 5min for the next
        # periodic tick. Without this, Gate 2 trades the cold-boot storm for a
        # 0-5min actuation-lag hole after release.
        # Reviewer B HIGH-B1 (2026-06-04): defer via async_call_later and store
        # the unsub in _unsub_listeners — NOT a bare un-cancellable task — so a
        # parent-entry reload that calls async_teardown between release and the
        # kickoff cancels it in the SAME envelope as the gate's own timers,
        # closing the teardown-race window (cf. "parent reload watchdog" memo).
        # _async_decision_cycle already accepts the _now arg the scheduler passes.
        if self._boot_settle_hvac_suppressed > 0:
            from homeassistant.helpers.event import (  # noqa: PLC0415
                async_call_later,
            )
            try:
                _unsub_kick = async_call_later(
                    self.hass, 1, self._async_decision_cycle
                )
                self._unsub_listeners.append(_unsub_kick)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "HVAC boot-settle: failed to schedule post-release kickoff",
                    exc_info=True,
                )

    @callback
    def _on_ha_started_release_boot_settle(self, _event: Any) -> None:
        """EVENT_HOMEASSISTANT_STARTED listener — Predicate B path 1."""
        self._release_boot_settle("ha_started")

    @callback
    def _timeout_release_boot_settle(self, _now: Any = None) -> None:
        """Failsafe timeout — Predicate B path 2."""
        self._release_boot_settle("timeout")

    async def _async_decision_cycle(self, _now=None, *, trigger: str = "periodic") -> None:
        """Run the periodic HVAC decision cycle (every 5 minutes).

        Self-driven via async_track_time_interval — does NOT rely on the
        intent-based evaluate() path since no intents route to HVAC.

        v5.103.20 (plan §5.2, REV 7 L3): `trigger` is KEYWORD-ONLY (the
        timer passes HA's `now` positionally) and is forwarded through
        `_run_decision_cycle` to `_apply_house_state_presets` for the
        `preset_change` ledger row: `periodic` (timer / setup / boot kick),
        `house_state`, `pre_arrival`. Observability only — every non-fast
        trigger still runs the full site list.
        """
        if not self._enabled:
            # HVAC W1/W2 finish fix-up 1 (D-L4): a pre-arrival pre-cool
            # borrow live when the coordinator is switched off is ended as
            # `pre_arrival_inactive` here (never left to `lease_expiry`).
            if self._boot_settle_done:
                await self._async_end_pre_arrival_borrows({}, all_inactive=True)
            return

        # Cold-boot away-actuation storm mitigation — Gate 2. The first
        # decision cycle on a cold boot is held until Predicate B releases
        # the gate (EVENT_HOMEASSISTANT_STARTED or BOOT_SETTLE_TIMEOUT_SECONDS).
        # This is the scenario-γ guard: even if presence holds its dispatch,
        # the periodic 5-min timer's initial tick + the explicit kickoff at
        # the end of async_setup can still fan turn_off / preset re-apply
        # before sensor/zone data has settled.
        if not self._boot_settle_done:
            self._boot_settle_hvac_suppressed += 1
            _LOGGER.info(
                "Boot-settle: suppressed HVAC first decision cycle "
                "(suppressed_count=%d, release_reason=%s)",
                self._boot_settle_hvac_suppressed,
                self._boot_settle_release_reason,
            )
            return

        # Re-entrancy guard: skip if already running (e.g. signal + timer overlap,
        # or the post-boot-settle re-kick landing on top of a periodic tick).
        # HVAC fast occupancy response (v5.103.20, plan §5.5): if the lock is
        # held by a zone-scoped FAST run, WAIT for it instead of skipping
        # (a fast run is short and must not cost the house a whole tick);
        # if held by a full cycle, skip as before. After acquiring, skip if
        # a full cycle STARTED after this call was scheduled, so a waiting
        # periodic never runs a second back-to-back full cycle (that would
        # double-sample `check_ac_reset` and the anomaly counters).
        scheduled_at = dt_util.utcnow()
        if self._decision_cycle_lock.locked() and not self._fast_path_running:
            _LOGGER.debug(
                "HVAC decision cycle skipped — already running (re-entrancy guard)"
            )
            return
        async with self._decision_cycle_lock:
            if (
                self._last_full_cycle_started_at is not None
                and self._last_full_cycle_started_at >= scheduled_at
            ):
                _LOGGER.debug(
                    "HVAC decision cycle skipped — a full cycle ran while waiting"
                )
                return
            await self._run_decision_cycle(trigger=trigger)

    @staticmethod
    def _classify_manual_episode(last_det: dict | None) -> str:
        """HVAC W1-B P2 (N4, A-M1, D-LOW) — `manual_class` for an S1 manual
        write-through, from the arrester's in-memory detection for the
        CURRENT manual episode:
          * no detection in this episode (incl. after a restart) -> `unknown`
          * delta_f == 0                                          -> `zero_delta_ura`
          * 0 < |delta_f| < threshold (+1 F in coast)             -> `sub_delta_human`
          * |delta_f| >= threshold (gated or failed/expired arrest) -> `gated_human`
        Reason ladder untouched; no NM."""
        if not last_det or last_det.get("delta_f") is None:
            return "unknown"
        try:
            d = abs(float(last_det["delta_f"]))
        except (TypeError, ValueError):
            return "unknown"
        if d == 0.0:
            return "zero_delta_ura"
        thr = float(OVERRIDE_NORMAL_DELTA) + (
            float(OVERRIDE_COAST_TOLERANCE_BONUS) if last_det.get("coast") else 0.0
        )
        if d < thr:
            return "sub_delta_human"
        return "gated_human"

    def _track_task(self, task: Any) -> None:
        """B-L2: register a fire-and-forget task on the coordinator's
        existing `_pending_tasks` set (cancelled in `async_teardown`)."""
        try:
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
        except Exception:  # noqa: BLE001
            pass

    def _note_s1_reclaim(self, zone_id: str, zone_name: str, reason: str) -> None:
        """HVAC W1-B §5.P5 — S1 reclaim-rate anomaly trip-wire.

        More than `S1_RECLAIM_RATE_LIMIT_N` manual write-throughs on ONE
        zone inside `S1_RECLAIM_RATE_WINDOW_S` means something keeps
        re-creating a manual hold faster than S1 reclaims it (a fight) ->
        one MEDIUM NM `s1_reclaim_rate_high` per episode. Discharge: the
        rate drops back to <= N inside the window (latch clears; a later
        burst notifies again). N <= 0 disables. Never raises.
        """
        try:
            if S1_RECLAIM_RATE_LIMIT_N <= 0:
                return
            now_m = time.monotonic()
            hist = self._s1_reclaim_ts.setdefault(zone_id, [])
            hist.append(now_m)
            cutoff = now_m - float(S1_RECLAIM_RATE_WINDOW_S)
            hist[:] = [t for t in hist if t >= cutoff]
            count = len(hist)
            if count > S1_RECLAIM_RATE_LIMIT_N:
                if zone_id in self._s1_reclaim_rate_latched:
                    return
                self._s1_reclaim_rate_latched.add(zone_id)
                nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
                if nm is None:
                    return
                from .base import Severity  # noqa: PLC0415
                self._track_task(self.hass.async_create_task(nm.async_notify(
                    coordinator_id="hvac",
                    severity=Severity.MEDIUM,
                    title=f"HVAC S1 reclaim rate high: {zone_name}",
                    message=(
                        f"S1 took {zone_name} out of manual {count} times in the "
                        f"last {S1_RECLAIM_RATE_WINDOW_S // 60} min (limit "
                        f"{S1_RECLAIM_RATE_LIMIT_N}); something keeps re-creating "
                        f"a manual hold (last reason={reason})."
                    ),
                    hazard_type="s1_reclaim_rate_high",
                )))
            else:
                self._s1_reclaim_rate_latched.discard(zone_id)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("s1 reclaim-rate trip-wire failed", exc_info=True)

    def _clear_tao_restart_marker(self) -> None:
        """Drop `hvac_temp_arrester_override_was_active` from every entry's
        options (sunset path; the switch clears it itself on manual OFF)."""
        try:
            for e in self.hass.config_entries.async_entries(DOMAIN):
                opts = getattr(e, "options", None) or {}
                if opts.get("hvac_temp_arrester_override_was_active"):
                    new_opts = dict(opts)
                    new_opts.pop("hvac_temp_arrester_override_was_active", None)
                    self.hass.config_entries.async_update_entry(e, options=new_opts)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("TAO marker clear on sunset failed", exc_info=True)

    def _settle_tao_restart_marker(self, decision: str, expires_at: Any, now: Any) -> None:
        """A-H2 / B-M1: the `hvac_temp_arrester_override_was_active` options
        marker (written by the switch on every toggle) used to fire a
        "released across restart" NM from `__init__` BEFORE the coordinator
        existed — false whenever decision 46 restores the override. The
        wording is now decided HERE from the boot decision:
          restore_on          -> LOW "restored across restart (Xh left)"
          restore_off_expired -> LOW "expired across restart"
          anything else       -> LOW "released across restart" (legacy)
        and the marker is cleared in every branch. Never raises."""
        try:
            marked = [
                e for e in self.hass.config_entries.async_entries(DOMAIN)
                if (getattr(e, "options", None) or {}).get(
                    "hvac_temp_arrester_override_was_active"
                )
            ]
        except Exception:  # noqa: BLE001
            marked = []
        if not marked:
            return
        if decision == "restore_on":
            left_h = max(0.0, (expires_at - now).total_seconds() / 3600.0) if expires_at else 0.0
            title = "Temp Arrester Override restored across restart"
            message = (
                f"Temp Arrester Override was ACTIVE when HA restarted and its "
                f"6 h window has not expired; it was RESTORED ({left_h:.1f} h left). "
                f"Arrester corrective writes stay suppressed until it sunsets."
            )
        elif decision == "restore_off_expired":
            title = "Temp Arrester Override expired across restart"
            message = (
                "Temp Arrester Override was ACTIVE when HA restarted but its "
                "6 h window had already expired; it is OFF and arrester "
                "governance has resumed. Re-engage if still intended."
            )
        else:
            title = "Temp Arrester Override released across restart"
            message = (
                "Temp Arrester Override was ACTIVE when HA restarted/reloaded "
                "but no restorable window was persisted. It has been released "
                "to the default-OFF state; arrester governance has resumed. "
                "Re-engage if still intended."
            )

        async def _emit() -> None:
            nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
            if nm is not None:
                try:
                    from .base import Severity  # noqa: PLC0415
                    await nm.async_notify(
                        coordinator_id="hvac", severity=Severity.LOW,
                        title=title, message=message,
                        hazard_type="hvac_temp_arrester_override",
                    )
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("TAO restart NM note failed", exc_info=True)
            for e in marked:
                try:
                    new_opts = dict(e.options)
                    new_opts.pop("hvac_temp_arrester_override_was_active", None)
                    self.hass.config_entries.async_update_entry(e, options=new_opts)
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("TAO marker clear failed", exc_info=True)

        try:
            self._track_task(self.hass.async_create_task(_emit()))
        except Exception:  # noqa: BLE001
            _LOGGER.debug("TAO restart marker settle failed", exc_info=True)

    async def _rehydrate_arrester_state(self, stored: Any) -> None:
        """HVAC W1-B D-P1 + D-P1a boot restore from `_zone_state_store`.

        * `__immune_holds` -> `arrester.rehydrate_immune_holds` (ruling 17).
        * `__tao_state` -> restore Temp Arrester Override ON iff
          `now < expires_at` (decision 46, option (ii)); OFF otherwise.
          The coordinator sets the ARRESTER internals (the boolean gate
          (a/b) reads) and the switch UI follows the dispatcher signal —
          one atomic seam, never a switch-ON / arrester-False window.
        * Emits ONE `tao_restore_evaluated` ledger row with
          `decision in {restore_on, restore_off_expired, no_persisted_state}`
          (C-P1E). Never raises.
        """
        arr = self._override_arrester
        if arr is None:
            return
        data = stored if isinstance(stored, dict) else {}
        try:
            arr.rehydrate_immune_holds(data.get("__immune_holds") or {})
        except Exception:  # noqa: BLE001
            _LOGGER.warning("HVAC: immune-hold rehydration failed", exc_info=True)
        # HVAC W1/W2 finish fix-up 1 (D-M2): restore the interrupt latch
        # (kept only while the zone still reads manual).
        try:
            arr.rehydrate_interrupt_latch(data.get("__interrupt_latch") or [])
        except Exception:  # noqa: BLE001
            _LOGGER.warning("HVAC: interrupt-latch rehydration failed", exc_info=True)

        tao = data.get("__tao_state") or {}
        if not isinstance(tao, dict):
            tao = {}
        persisted_expires = tao.get("expires_at")
        persisted_started = tao.get("started_ts")
        expires_at = None
        started_at = None
        try:
            expires_at = (
                dt_util.parse_datetime(str(persisted_expires)) if persisted_expires else None
            )
            started_at = (
                dt_util.parse_datetime(str(persisted_started)) if persisted_started else None
            )
        except Exception:  # noqa: BLE001
            expires_at = None
        now = dt_util.now()
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = dt_util.as_local(expires_at.replace(tzinfo=dt_util.UTC))
        if started_at is not None and started_at.tzinfo is None:
            started_at = dt_util.as_local(started_at.replace(tzinfo=dt_util.UTC))
        if expires_at is not None and now < expires_at:
            try:
                # A-L3: a missing/unparseable started_ts derives the start
                # from the ceiling so age math still measures from the real
                # engagement, not from boot.
                if started_at is None:
                    from .hvac_const import COMFORT_OVERRIDE_MAX_S as _MAX_S
                    started_at = expires_at - timedelta(seconds=_MAX_S)
                arr.restore_temp_arrester_override(
                    started_at, pending_sunset=tao.get("pending_sunset"),
                )
                decision = "restore_on"
            except Exception:  # noqa: BLE001
                _LOGGER.warning("HVAC: TAO restore failed", exc_info=True)
                decision = "restore_failed"
        elif expires_at is not None:
            decision = "restore_off_expired"
        else:
            decision = "no_persisted_state"
        self._settle_tao_restart_marker(decision, expires_at, now)
        _LOGGER.info(
            "HVAC: Temp Arrester Override boot evaluation: %s (expires_at=%s)",
            decision, persisted_expires,
        )
        try:
            db = self.hass.data.get(DOMAIN, {}).get("database")
            if db is not None:
                import json as _json  # noqa: PLC0415
                _coro = db.log_activity(
                    timestamp=dt_util.utcnow().isoformat(),
                    coordinator="hvac",
                    action="tao_restore_evaluated",
                    room=None,
                    zone=None,
                    importance="notable",
                    description=f"tao_restore_evaluated decision={decision}",
                    details_json=_json.dumps({
                        "tao_persisted_started_ts": persisted_started,
                        "tao_persisted_expires_at": persisted_expires,
                        "decision": decision,
                        "now": now.isoformat(),
                    }, default=str),
                    entity_id=None,
                )
                import inspect as _inspect  # noqa: PLC0415
                if _inspect.iscoroutine(_coro):
                    self.hass.async_create_task(_coro)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("tao_restore_evaluated ledger row failed", exc_info=True)

    async def _run_decision_cycle(self, *, trigger: str = "periodic") -> None:
        """Inner decision cycle logic (called under lock). `trigger` is
        forwarded to `_apply_house_state_presets` (REV 7 L3)."""
        # HVAC W1-B D2.1 (N9a): same-tick set resets at cycle ENTRY, not at
        # cycle end — an exception anywhere below cannot leave a zone
        # marked "written" into the next tick.
        # HVAC fast occupancy response (v5.103.20, plan §5.5 / REV 2 #4):
        # the reset is now a SEED — zones whose last S1 write (fast OR
        # periodic) is younger than the arrester's preset suppression window
        # (SUPPRESS_TTL_SECONDS_PRESET, 120 s) start the tick already
        # "written", so a zone a fast run wrote seconds before this tick is
        # still skipped by the soft-nudge dispatch (hvac_override.py). A
        # zone written by the previous tick (300 s ago) is NOT seeded —
        # identical to the old empty set.
        _cycle_start_utc = dt_util.utcnow()
        self._last_full_cycle_started_at = _cycle_start_utc
        self._zones_written_this_cycle = {
            _z for _z, _rec in self._zone_last_s1_write.items()
            if (_cycle_start_utc - _rec[2]).total_seconds() < SUPPRESS_TTL_SECONDS_PRESET
        }
        # LOCAL-day clock for the daily reset (test_hvac_short_cycle_producer).
        now = dt_util.now()

        # Daily reset check
        today = now.date().isoformat()
        if today != self._last_daily_reset:
            self._last_daily_reset = today
            # Flush predictor outcome BEFORE resetting zone counters
            # so it captures yesterday's override/reset counts
            self._predictor.flush_daily_outcome()
            self._zone_manager.reset_daily_counters()
            self._preset_manager.determine_season()
            # RESTART-SAFETY-DOCTRINE-1 F14: DailyCounter primitives roll
            # over lazily; call rollover_if_needed (no arg) so the counter
            # uses its own UTC-based today string (Bug Class #11 guard) and
            # does not mix the outer local "today" clock with the counter's
            # internal UTC clock.
            self._vacancy_sweeps_today.rollover_if_needed()
            self._pre_arrival_triggers_today.rollover_if_needed()
            self._preset_deferrals_today.rollover_if_needed()
            self._preset_deferrals_by_gate = {}
            # CARRIER-STALE-POLL-REFRESH-1: roll day-scoped safety cap +
            # release the D3 suppress-for-day flag on the local-day hinge.
            self._carrier_reloads_today.rollover_if_needed()
            if self._carrier_reload_suppress_date != today:
                if self._carrier_reload_suppressed_today:
                    _LOGGER.info(
                        "Carrier reload suppression released at daily rollover "
                        "(previous day cap or reload-ineffective D3 cleared)"
                    )
                self._carrier_reload_suppressed_today = False
                self._carrier_reload_suppress_date = today
            # HVAC-ANOMALY-BLIND-1 D2: emit per-zone short_cycle_rate
            # observation for the completed LOCAL day, then reset the
            # counter. Placed BESIDE the vacancy/pre-arrival rollovers
            # (:1304-1305) so it participates in the same daily hinge.
            # NOTE — the CRITICAL guard against emitting a partial-day
            # value at boot lives in `_emit_and_reset_short_cycles` and
            # gates on the tracker's OWN persisted date
            # (`_short_cycles_today_date`), NOT `_last_daily_reset`
            # (RAM-only, resets on every boot). Passing `today` (already
            # computed above from dt_util.now(), LOCAL day) keeps clock
            # semantics consistent across the tracker.
            await self._emit_and_reset_short_cycles(today)

        # Update zone states
        self._zone_manager.update_all_zones()
        self._zone_manager.update_room_conditions(
            house_state=self._house_state,
            entry_dwell_s=self._entry_dwell_s(),
            away_edge_fn=self._zone_away_edge,
            return_window_s=self._return_window_s(),
        )
        # HVAC-DEGRADED-ROOM-TRIPWIRE-1 REV-2 D3/F9: async NM emission
        # from the coordinator (never from the sync gate — no
        # create_task from a sync tick path).
        await self._drain_hvac_degraded_room_events()

        # CARRIER-STALE-POLL-REFRESH-1 D1: per-tick Carrier freshness check.
        # Wire-in anchors (fix-up round 2026-09-09, C-HIGH-2):
        #   - test_wire_in_call_site_present_in_run_decision_cycle
        #     (AST assertion) fails if THIS call is deleted from
        #     `_run_decision_cycle`.
        #   - test_stale_and_corroborated_triggers_reload fails if
        #     `_reload_ha_carrier_entry` is neutered.
        try:
            await self._check_carrier_freshness()
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "Carrier freshness check failed (non-fatal)", exc_info=True,
            )

        # feature/freeze-floor (D-HIGH-1): re-derive the freeze-active latch
        # ONCE per decision cycle, UNCONDITIONALLY — before any setpoint
        # emitter runs. The predictor (banking/pre-heat) and the override
        # arrester (nudge) read `_freeze_active` lazily and fire on independent
        # triggers; the DPM apply path is double-gated (observation mode +
        # guest_mode_actuation). If the refresh lived only inside that gated
        # path, `_freeze_active` would stay at its False default during a real
        # freeze whenever actuation gates are off / on the first boot cycle,
        # and the floor would silently NO-OP at the predictor/arrester. Refresh
        # here so every emitter in this cycle reads a current value. Logic
        # (hysteresis, fail-open) is unchanged — only WHERE it's called.
        self._update_freeze_active()

        # v4.7.8 D3/D6: Egress Window HVAC Pause — runs AFTER room conditions
        # are fresh (so window_state is current) but BEFORE preset apply +
        # predictor update (so paused zones get skipped cleanly downstream).
        # async_tick early-returns if rehydrate hasn't completed yet (Bug
        # Class #14). Service calls are awaited under the held lock so they
        # complete before downstream rules read the new climate state.
        try:
            await self._egress_manager.async_tick(now)
        except Exception:
            _LOGGER.warning("HVAC: EgressManager tick failed", exc_info=True)

        # One-time startup audit: catch stale overrides that survived restart
        if not self._startup_audit_done:
            self._startup_audit_done = True
            await self._override_arrester.async_startup_audit(
                self._preset_manager, self._house_state or "home_day",
            )
            # v4.5.11: Restore in-flight nudges that survived an HA restart
            # (R1 mitigation). Runs after override audit so suppression flags
            # are settled.
            await self._override_arrester.async_startup_ramp_audit()
            # A3 fix-up (2026-08-22): bounded restart resumption of
            # in-flight durability windows. Sibling of the nudge
            # ramp audit; runs after it so any zone whose nudge got
            # restored can also have its durability window resumed.
            await self._override_arrester.async_startup_durable_audit()

        now_utc = dt_util.utcnow()

        # v3.17.0: Zone Intelligence features (guarded by toggle)
        _pa_reasons: dict[str, str] = {}
        if self._zone_intelligence_enabled:
            # D5: Accumulate zone runtime BEFORE presets (RC3 ordering)
            self._accumulate_zone_runtime(now_utc)
            # D3: Clear stale pre-arrival zones
            _pa_reasons = self._expire_pre_arrival_zones(now_utc)

        # HVAC W1/W2 finish fix-up 2 (N1): level check of the person-
        # interrupt latch every full pass — a thermostat now readable at a
        # named non-manual preset discharges it even if no event was seen.
        try:
            self._override_arrester.latch_level_check()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("HVAC: latch level check failed", exc_info=True)

        # HVAC W1/W2 finish D3 (INV-B.3): end pre-arrival pre-cool borrows
        # (arrival / timeout / interrupt / inactive / max age) BEFORE S1 in
        # this same pass, whatever the ZI toggle or observation mode.
        await self._async_end_pre_arrival_borrows(_pa_reasons)

        # Arrester Operator-Immunity: periodic sweep — max-age +
        # next_activity boundary sunsets that are not triggered by a
        # house-state signal. Comfort Override max-age auto-release
        # + LOW NM note run here as well. Called every decision cycle
        # (5 min) — safe cadence given the max-age is measured in hours.
        try:
            self._override_arrester.sunset_immune_holds(
                reason="max_age_or_boundary",
            )
            # F8: sunset-notify callback registered on the arrester fires
            # the NM note (dedup'd by engagement-id). Sweep just drives
            # the periodic evaluation; the note routes via the callback
            # so timer-precise discharges are covered too.
            self._override_arrester.sunset_temp_arrester_override(
                reason="max_age_or_boundary",
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "Arrester periodic sunset sweep failed: %s", e,
            )

        if not self._observation_mode:
            # Apply presets based on house state (includes D1 vacancy + D6 failsafe)
            await self._apply_house_state_presets(trigger=trigger)

            # Update override arrester energy state and check AC resets
            self._override_arrester.update_energy_state(
                self._energy_offset,
                self._energy_constraint_mode == "coast",
                # ARREST-COMFORT-1 Cycle A: push SOC + blind + shed so the
                # D1 grant-time gate reads from the SAME source as D3.
                battery_soc=self.battery_soc,
                battery_blind=self.battery_blind,
                shed_active=self.shed_active,
            )
            await self._override_arrester.check_ac_reset()

            # Fan and cover control
            if self._fan_control_enabled:
                await self._fan_controller.update(self._energy_constraint, self._house_state)
            else:
                await self._fan_controller.turn_off_all_managed()
            await self._cover_controller.update(self._energy_constraint)
        else:
            # fix-up 2 (D-L1): observation mode skips every S1 block.
            self._close_unseen_pending_spells(set(), None)
            # Still update arrester state for diagnostics (no actions)
            self._override_arrester.update_energy_state(
                self._energy_offset,
                self._energy_constraint_mode == "coast",
                # ARREST-COMFORT-1 Cycle A: push SOC + blind + shed so the
                # D1 grant-time gate reads from the SAME source as D3.
                battery_soc=self.battery_soc,
                battery_blind=self.battery_blind,
                shed_active=self.shed_active,
            )

        # Predictive sensors and pre-conditioning
        # NOTE: predictor.update() includes pre-arrival fan bridge (Path 2),
        # intentionally NOT gated by fan_control_enabled.
        zi = self._zone_intelligence_enabled
        await self._predictor.update(
            self._energy_constraint,
            self._house_state,
            pre_arrival_zones=self._pre_arrival_zones if zi else set(),
            zone_intelligence_enabled=zi,
        )

        # v3.17.0 D4: Compute zone presence states (after all other logic)
        if zi:
            self._compute_zone_presence_states(now_utc)

        # Record anomaly observations (async — persists anomalies to anomaly_log)
        await self._record_anomaly_observations()

        # HVAC fast occupancy response (v5.103.20, plan §5.6): (re)arm the
        # exit timer of every zone at the end of every full cycle.
        for _zid in list(self._zone_manager.zones.keys()):
            self._schedule_exit_timer(_zid)

        # Signal sensor updates
        async_dispatcher_send(self.hass, SIGNAL_HVAC_ENTITIES_UPDATE)

        self._last_evaluate = now.isoformat()

        # v3.18.2: Periodic zone state save (every 5 cycles = ~25 min)
        self._zone_state_save_counter += 1
        if self._zone_state_save_counter >= 5:
            self._zone_state_save_counter = 0
            await self.async_save_zone_state()

    # ------------------------------------------------------------------
    # HVAC W1-B D-P1 / D-P1a — ONE snapshot builder for every save site
    # ------------------------------------------------------------------
    def _build_zone_state_snapshot(self) -> dict:
        """Zone state + every side-key, so no save site can drop a key.

        Side-keys: `__person_zone_map` (v3.18.5), `__short_cycles_today`
        (HVAC-ANOMALY-BLIND-1 D2), `__immune_holds` (W1-B D-P1, ruling 17),
        `__tao_state` (W1-B D-P1a, decision 46).
        """
        snapshot = self._zone_manager.get_state_snapshot()
        snapshot["__person_zone_map"] = self._person_zone_map
        # HVAC-ANOMALY-BLIND-1 D2: persist short-cycle counter so a mid-day
        # restart preserves accumulated per-zone counts and the rollover
        # guard can distinguish "same day" from "new day" against the
        # tracker's OWN date (not the RAM-only _last_daily_reset).
        snapshot["__short_cycles_today"] = {
            "date": self._short_cycles_today_date,
            "counts": dict(self._short_cycles_today),
        }
        arr = self._override_arrester
        snapshot["__immune_holds"] = arr.export_immune_holds() if arr else {}
        snapshot["__tao_state"] = (
            arr.export_tao_state() if arr else {"started_ts": None, "expires_at": None}
        )
        # HVAC W1/W2 finish fix-up 1 (D-M2): the person-interrupt latch.
        snapshot["__interrupt_latch"] = arr.export_interrupt_latch() if arr else []
        return snapshot

    async def async_save_zone_state(self) -> None:
        """Persist the zone-state snapshot (periodic / shutdown / arrester)."""
        try:
            await self._zone_state_store.async_save(self._build_zone_state_snapshot())
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("HVAC: Failed to save zone state: %s", e)

    def schedule_zone_state_save(self, reason: str = "") -> None:
        """Non-blocking save request (arrester stamp/sunset/TAO paths)."""
        try:
            self._track_task(self.hass.async_create_task(self.async_save_zone_state()))
            _LOGGER.debug("HVAC: zone-state save scheduled (%s)", reason)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("HVAC: zone-state save schedule failed", exc_info=True)

    async def evaluate(
        self,
        intents: list[Intent],
        context: dict[str, Any],
    ) -> list[CoordinatorAction]:
        """Evaluate intents from CoordinatorManager.

        HVAC is primarily self-driven via _async_decision_cycle.
        This exists to satisfy the BaseCoordinator interface.
        """
        return []

    async def _apply_house_state_presets(
        self,
        *,
        zone_filter: set[str] | None = None,
        trigger: str = "periodic",
        edge_ts: datetime | None = None,
        exempt_reason: str | None = None,
    ) -> bool:
        """Apply preset changes based on current house state.

        Includes D1 vacancy override, D5 duty cycle enforcement, D6 stale failsafe.
        Directly calls HA services (self-driven, not via CoordinatorManager actions).

        HVAC fast occupancy response (v5.103.20, plan §5.2). Returns True iff
        S1 applied a write this call. `zone_filter is None` (periodic /
        house-state / pre-arrival) is byte-identical to before. With
        `zone_filter` set (a zone-scoped fast run): the heat_cool enforcer
        and the DPM preset overrides are SKIPPED, every other zone is
        skipped at the loop top, and the consensus gate, `arriving`, every
        per-zone rule and the vacancy sweep for the filtered zone run as
        today. `trigger` / `edge_ts` land on the `preset_change` ledger row.

        v4.7.15 D6: Asymmetric-hysteresis defer gate driven by signal_consensus.
        When the inputs disagree (consensus < 0.5) AND the last house-state
        transition was recent (< 30 s), skip this preset apply cycle entirely.
        Critical safety paths (CO2, fire, hazard) DO NOT go through this method,
        so they are inherently bypassed. Resume at consensus > 0.7 (the next
        cycle that crosses the upper hysteresis threshold writes presets normally).
        """
        if not self._house_state:
            return False

        # v4.7.15 D6: HVAC consensus defer gate.
        # v4.7.15 fix-up A5-H1: asymmetric hysteresis 0.5 / 0.7.
        # Engage when (consensus < 0.5 AND last transition < 30 s ago) — this
        # is the "transition-driven disagreement" shape D6 targets. Once
        # engaged, stay engaged (defer writes) until consensus recovers above
        # 0.7. Disengage at >= 0.7, regardless of time since transition.
        # Single-threshold flap (0.45 → 0.55 → 0.45 within the 30s window)
        # used to flip the gate on/off; the upper threshold prevents that.
        if self._defer_gate_enabled:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            presence = manager.coordinators.get("presence") if (
                manager is not None and hasattr(manager, "coordinators")
            ) else None
            if presence is not None:
                consensus = getattr(presence, "_signal_consensus", 1.0)
                last_transition = getattr(presence, "_last_transition_time", None)
                now_utc = dt_util.utcnow()
                if last_transition is not None:
                    secs_since_transition = (now_utc - last_transition).total_seconds()
                else:
                    secs_since_transition = 1e9
                # Asymmetric hysteresis: defer if < 0.5 + recent transition,
                # resume only at >= 0.7.
                if self._d6_gate_engaged:
                    if consensus >= 0.7:
                        _LOGGER.info(
                            "v4.7.15 D6: HVAC defer gate DISENGAGED — "
                            "consensus=%.2f recovered above 0.7",
                            consensus,
                        )
                        self._d6_gate_engaged = False
                    else:
                        # Still engaged — keep deferring.
                        _LOGGER.info(
                            "v4.7.15 D6: HVAC preset write deferred (hysteresis hold) — "
                            "consensus=%.2f < 0.7",
                            consensus,
                        )
                        self._d6_deferrals_today.increment()
                        return False
                else:
                    if consensus < 0.5 and secs_since_transition < 30:
                        _LOGGER.info(
                            "v4.7.15 D6: HVAC defer gate ENGAGED — "
                            "consensus=%.2f, secs_since_transition=%.0f",
                            consensus, secs_since_transition,
                        )
                        self._d6_gate_engaged = True
                        self._d6_deferrals_today.increment()
                        return False  # Skip this apply cycle — retry next tick.

        # --- Continuous heat_cool enforcer (always, even during arriving) ---
        # The operator runs zones in ranges/presets (heat_cool). A bare
        # hvac_mode drift to a single mode (e.g. cool, with preset/setpoints
        # unchanged) is NOT caught by the OverrideArrester (which only reverts
        # on a MANUAL-PRESET override). The old loop here only restored zones
        # stuck in "off", so a zone drifted to "cool"/"heat" sailed past with
        # no recovery path. This makes the 5-min decision cycle a continuous
        # heat_cool enforcer for ANY non-heat_cool drift on heat_cool-capable
        # zones, regardless of how the drift happened.
        #
        # Gating (only act on UNINTENTIONAL drift):
        #   - Skip zones paused by EgressManager (we set them "off"
        #     deliberately; restoring heat_cool would defeat the pause). v4.7.8 D8
        #   - Skip zones mid-AC-reset (intentionally "off" for a short cycle).
        #   - Only act on heat_cool-CAPABLE zones (a genuinely heat-only /
        #     cool-only unit is never forced into an unsupported mode).
        #   - Idempotent: the `!= "heat_cool"` guard means no write when already
        #     in heat_cool.
        # The suppress() handshake (TTL window, A-F5) wraps the write so it does
        # not register as a manual override → no feedback loop.
        #
        # NOTE (operator decision 2026-06-16): single-mode "heat" is
        # INTENTIONALLY NOT exempt. If the Safety Coordinator sets a zone to
        # "heat" as a freeze response, this enforcer WILL revert it to
        # heat_cool on the next decision cycle. This is by design — heat_cool
        # still heats via the low setpoint and the operator does not rely on
        # single-mode heat. Do NOT "re-fix" this by adding a heat exemption.
        # snapshot: zones dict may be pruned by _handle_zm_zones_updated mid-await
        # v5.103.20 (plan §5.2 / INV-4): the enforcer is a house-wide,
        # tick-cadence writer — a zone-scoped fast run SKIPS it.
        for zone_id, zone in (
            list(self._zone_manager.zones.items()) if zone_filter is None else []
        ):
            if self._egress_manager.is_paused(zone_id):
                continue
            if (
                zone.hvac_mode != "heat_cool"
                and self._override_arrester._supports_heat_cool(zone.climate_entity)
                and not self._override_arrester.has_active_ac_reset(zone_id)
            ):
                self._override_arrester.suppress(zone.climate_entity)
                try:
                    # HVAC-W1-A B1: heat_cool enforcer drift revert.
                    await emit_set_hvac_mode(
                        self.hass,
                        zone.climate_entity,
                        "heat_cool",
                        site="B1_heat_cool_enforcer",
                        zone_id=zone_id,
                        reason="heat_cool_enforcer_drift_revert",
                        blocking=True,
                    )
                    _LOGGER.info(
                        "HVAC: Enforced heat_cool on %s (was %s)",
                        zone.zone_name, zone.hvac_mode,
                    )
                except Exception as e:
                    self._override_arrester.unsuppress(zone.climate_entity)
                    _LOGGER.error(
                        "HVAC: Failed to restore mode on %s: %s",
                        zone.climate_entity, e,
                    )

        # Skip preset changes during "arriving" — transient state after
        # HA restart or geofence arrival.  Presence sensors haven't settled
        # yet, so acting now causes unnecessary preset churn.
        if self._house_state == "arriving":
            self._close_unseen_pending_spells(set(), zone_filter)
            return False

        target_preset = self._preset_manager.get_preset_for_house_state(
            self._house_state
        )
        if target_preset is None:
            self._close_unseen_pending_spells(set(), zone_filter)
            return False
        wrote_any = False
        # fix-up 2 (D-L1): zones whose S1 block ran `_note_pending_hold`
        # this tick; every other zone in scope has its spell closed below.
        _pending_seen: set[str] = set()

        now = dt_util.utcnow()
        energy_constrained = self._energy_constraint_mode in ("coast", "shed")
        grace_minutes = (
            self._vacancy_grace_constrained if energy_constrained
            else self._vacancy_grace
        )

        zi = self._zone_intelligence_enabled
        # B-L1 (2026-08-06): hoist activity_logger lookup once per tick rather
        # than re-fetching inside every zone iteration (two branches used it).
        activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
        # snapshot: zones dict may be pruned by _handle_zm_zones_updated mid-await
        for zone_id, zone in list(self._zone_manager.zones.items()):
            # v5.103.20 (plan §5.2 / INV-4): zone-scoped fast run — every
            # other zone is skipped at the loop top, before any read/write.
            if zone_filter is not None and zone_id not in zone_filter:
                continue
            # v4.7.8 D8: Skip preset apply for zones paused by EgressManager.
            # Preset restoration happens on resume; applying here would push
            # a preset to an off compressor and the restore would override it.
            if self._egress_manager.is_paused(zone_id):
                continue
            effective_preset = target_preset
            zone_vacant_past_grace = False
            # B-H1 (2026-08-06): local flag set inside the D6 stuck-sensor
            # branch below; consumed by the reason ladder so we emit
            # `stale_occupancy` instead of `house_state_transition` when the
            # coordinator forces "away" against a still-any_room_occupied zone.
            stale_occupancy = False
            # HVAC-DEGRADED-ROOM-TRIPWIRE-1 fix-up round 3 (2026-09-26,
            # item 1): hoist EVERY per-zone per-tick local that is read
            # OUTSIDE the `if zi:` block to the loop top. Previous shape
            # assigned these three only inside `if zi:` (~2225, ~2232,
            # ~2056 for `_row1_hold_write`) but read them at
            # loop-level (~2666, ~2686, ~2533) — with Zone Intelligence
            # OFF (switch.ura_hvac_zone_intelligence off, a legal operator
            # setting) every tick raised UnboundLocalError and aborted
            # `_async_decision_cycle` at hvac.py:1742 (no try) — skipping
            # energy / AC-reset / fans / covers / predictor / signals /
            # save. Pre-existing sibling bug on develop for the D3/D5
            # flags; the row-1 hold made a HIGH out of it.
            _d3_skipped_this_tick = False
            _d5_occupancy_deferred_this_tick = False
            _row1_hold_write = False
            # v5.103.20 D5 pending-arm hold (plan §5.2, REV 7 H1) — a TRUE
            # mirror of `_row1_hold_write`, riding the same branch, the same
            # shed clearing and the same `continue` + suppressed row.
            _pending_arm_hold_write = False
            # fix-up 1 (D-L2): set when the D5 energy-shed branch forced away
            # this tick, so the reason ladder never labels it vacant_past_grace.
            _shed_forced_away_this_tick = False

            # HVAC-ZONE-CONDITIONING-DEMAND-1 D6 (doc-only, 2026-09-16):
            # retreat semantics on the preset-flip path (row 1) + the D6
            # stale-occupancy branch (row 4) key on the HVAC-occupancy
            # denomination — `zone.any_room_hvac_occupied` — NOT the
            # lighting-fused `any_room_occupied`. Downstream basis writes
            # `last_occupied_time` (row 2a) and `continuous_occupied_since`
            # (row 2c) share the same denomination; `zone_presence_state`
            # (row 7) similarly swaps to match. Lighting / fan / cover
            # surfaces continue to read the lighting-fused sibling.
            # --- D1/D5/D6: Zone Intelligence overrides (gated by toggle) ---
            if zi:
                # D1: Per-zone vacancy override.
                # HVAC-ZONE-CONDITIONING-DEMAND-1 §2a row 1: SWAP the
                # preset-flip retreat gate from the lighting-fused
                # `any_room_occupied` to the HVAC-denomination sibling
                # `any_room_hvac_occupied`. This is the load-bearing
                # preset-decision site — hallway transits must not keep
                # a bedroom zone in `home` past a legitimate retreat.
                # Only override "home"/"sleep" presets — away/vacation are already correct.
                # HVAC-ZONE-CONDITIONING-DEMAND-1 row-1 (fix-up round 4,
                # 2026-09-17 — F3 unification + reset-only backstop).
                # Retreat authorized iff `conditioning_retreat_ok` (i.e.
                # ESTABLISHED AND fused-empty). Person-trust preserve
                # dropped from this path — occupancy alone decides once
                # established (operator: "kills the over-preservation
                # where any-resident-home held every empty zone all
                # night"). Unestablished zones fail-open (no retreat)
                # via the shared helper's reset-only backstop.
                if self._zone_conditioning_retreat_ok(zone):
                    zone_vacant_past_grace = (
                        zone.last_occupied_time is not None
                        and (now - zone.last_occupied_time).total_seconds()
                        > grace_minutes * 60
                    )
                else:
                    zone_vacant_past_grace = False

                # HVAC-DEGRADED-ROOM-TRIPWIRE-1 FIX-UP item 2 (2026-09-26,
                # RESTRUCTURED per orchestrator fix-up round 2):
                # `_row1_hold_write` is set when the zone is unestablished
                # ONLY because a sibling room is transient AND the fused
                # HVAC signal is empty. It SUPPRESSES the eventual preset
                # write, NOT the safety paths. D6 stale-sensor cannot fire
                # here (it requires fused-occupied). D5 shed/coast still
                # runs — if it force-aways for energy-shed, it CLEARS
                # `_row1_hold_write` so the safety-directed write proceeds.
                # If nothing else forces away, we HOLD (no write in either
                # direction), matching the operator rule "match occupancy
                # IN THE ZONE" during a sibling-room reload.
                try:
                    _fused_empty = not bool(
                        getattr(zone, "any_room_hvac_occupied", False)
                    )
                except Exception:  # noqa: BLE001
                    _fused_empty = False
                _is_tb_row1 = getattr(
                    self._zone_manager, "is_zone_transient_blocked", None,
                )
                try:
                    _transient_blocked_row1 = (
                        bool(_is_tb_row1(zone_id)) if callable(_is_tb_row1) else False
                    )
                except Exception:  # noqa: BLE001
                    _transient_blocked_row1 = False
                # FIX-UP round 3 item 3 (2026-09-26): scope the HOLD to the
                # OCCUPANCY layer. Arm ONLY when the write would be an
                # occupancy-driven un-retreat (target=home/sleep and the
                # zone is not being pre-arrival conditioned and the house
                # is not in a genuine away/vacation transition). This
                # lets house-state-driven away/vacation/sleep transitions
                # AND pre-arrival writes land on the same tick even while
                # a sibling room reloads.
                _row1_hold_eligible = (
                    target_preset in ("home", "sleep")
                    and zone_id not in self._pre_arrival_zones
                    and self._house_state not in ("away", "vacation")
                )
                _row1_hold_write = (
                    _transient_blocked_row1
                    and _fused_empty
                    and _row1_hold_eligible
                )
                # v5.103.20 D5 (plan §5.2, REV 7 H1): pending-arm hold =
                # `pending and fused_empty and eligible`. While a room of an
                # otherwise HVAC-empty zone is deciding whether it is a
                # stay, the zone's preset is HELD in BOTH directions: no
                # home (the transit filter) and no vacancy away (INV-2 —
                # the pending room may become an occupant). If another
                # room is armed, `_fused_empty` is False and Z gets its
                # normal outcome driven by that room.
                _pending_arm_hold_write = (
                    bool(getattr(zone, "hvac_pending_arm_rooms", ()) or ())
                    and _fused_empty
                    and _row1_hold_eligible
                )
                # fix-up 1 (ruling 1 — pending-hold CAP, and B-L3): the
                # spell clock runs while the hold CONDITION holds; the latch
                # closes whenever it does not, on every exit path below.
                self._note_pending_hold(zone, _pending_arm_hold_write)
                _pending_seen.add(zone_id)
                if _pending_arm_hold_write:
                    _since = getattr(zone, "pending_hold_since", None)
                    # fix-up 2 (D-L2): the cap is never shorter than one
                    # full episode (W + J) so it only bites on CHAINS of
                    # episodes that never persisted — even at knob 47 = 15.
                    _cap_s = self._pending_hold_cap_s(zone)
                    if (
                        _since is not None
                        and (now - _since).total_seconds() > _cap_s
                    ):
                        # Held ONLY by never-persisted episodes for longer
                        # than the cap: stop holding, let the away through.
                        _pending_arm_hold_write = False
                        self._log_pending_hold_capped(
                            zone, zone_id, activity_logger, now, _since, _cap_s,
                        )
                else:
                    self._pending_hold_logged.discard(zone_id)
                    self._pending_hold_cap_logged.discard(zone_id)
                if _row1_hold_write or _pending_arm_hold_write:
                    _LOGGER.debug(
                        "HVAC row-1 hold: zone %s %s + fused-empty "
                        "— will suppress preset write unless a safety path "
                        "(D5 shed / D6 stale) forces away",
                        zone_id,
                        "transient-blocked" if _row1_hold_write else "pending-arm",
                    )
                    # Suppress the row-1 vacancy-grace override: with the
                    # hold armed, we do NOT flip effective_preset to away
                    # for "past grace"; safety paths below decide.
                elif zone_vacant_past_grace and target_preset in ("home", "sleep"):
                    effective_preset = "away"

                    # HVAC-ZONE-CONDITIONING-DEMAND-1 fix-up round 2
                    # (2026-09-17, A-HIGH/B-CRIT-1): DECOUPLE the vacancy
                    # sweep call from the HVAC-denomination retreat. The
                    # sweep is a LIGHTING actuator — it must fire only
                    # when the room is empty in the LIGHTING denomination
                    # (`not zone.any_room_occupied`). A standing hallway
                    # occupant makes the zone HVAC-empty (CIRCULATION
                    # EXCLUSION) but the hallway lights must stay on
                    # while the person is IN the hallway. Same shape as
                    # row 2b's NO-SWAP write basis in hvac_zones.py.
                    _sweep_light_ok = not getattr(
                        zone, "any_room_occupied", False,
                    )
                    if (
                        _sweep_light_ok
                        and not zone.vacancy_sweep_done
                        and zone.vacancy_sweep_enabled
                    ):
                        await self._execute_vacancy_sweep(zone)
                        zone.vacancy_sweep_done = True
                        self._vacancy_sweeps_today.increment()

                # D6: Stale occupancy failsafe (skip during sleep — RH4)
                # v3.22.2: Multi-source confidence check before declaring stale.
                # If 2+ independent sources confirm presence, reset the timer
                # instead of forcing away. Only treat as stale if a single
                # stuck sensor is the sole evidence.
                # HVAC-ZONE-CONDITIONING-DEMAND-1 §2a row 4: SWAP D6
                # stale-occupancy branch to HVAC denomination. This is the
                # sibling of the row-1 preset-flip retreat and consumes the
                # HVAC-scoped `continuous_occupied_since` write (row 2c).
                _row4_fused = getattr(zone, "any_room_hvac_occupied", None)
                if _row4_fused is None:
                    _row4_fused = getattr(zone, "any_room_occupied", True)
                if (
                    _row4_fused
                    and self._house_state != "sleep"
                    and zone.continuous_occupied_since is not None
                    and (now - zone.continuous_occupied_since).total_seconds()
                    > self._max_occupancy_hours * 3600
                ):
                    # v4.7.15 D4: helper relocated to PresenceCoordinator.
                    # Boot-race safety: if presence not registered yet (very
                    # early in startup), behave as if no confirmation —
                    # caller falls through to "stale sensor" branch exactly
                    # as v3.22.2 intended.
                    manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
                    presence = manager.coordinators.get("presence") if (
                        manager is not None and hasattr(manager, "coordinators")
                    ) else None
                    if presence is not None and hasattr(
                        presence, "check_zone_occupancy_confidence",
                    ):
                        confirmed, possible = presence.check_zone_occupancy_confidence(zone)
                    else:
                        confirmed, possible = 0, 0
                    # Adaptive threshold: require 2 of N if N >= 2, else 1 of 1
                    threshold = min(2, possible) if possible > 0 else 1
                    if confirmed >= threshold:
                        # Sufficient confirmation — occupancy is real, reset timer
                        zone.continuous_occupied_since = now
                        _LOGGER.info(
                            "HVAC: Zone %s occupied >%dh but %d/%d sources confirm "
                            "presence (threshold %d) — resetting timer (not stale)",
                            zone.zone_name, self._max_occupancy_hours,
                            confirmed, possible, threshold,
                        )
                    else:
                        # Insufficient confirmation — likely stuck sensor.
                        # B-H1 (2026-08-06 fix-up): tag the D6 stuck-sensor branch
                        # so the reason ladder below can emit `stale_occupancy`
                        # instead of mislabeling as `house_state_transition`
                        # (this branch is triggered by any_room_occupied being
                        # True while we force effective_preset -> "away").
                        stale_occupancy = True
                        effective_preset = "away"
                        # HVAC-ZONE-CONDITIONING-DEMAND-1 fix-up round 2
                        # (2026-09-17, A-HIGH/B-CRIT-1): sibling of the
                        # row-1 sweep decouple. The D6 stale branch only
                        # sweeps lighting when the zone is empty in the
                        # LIGHTING denomination. In practice this branch
                        # is entered because the HVAC-fused signal shows
                        # continuous occupancy > max_hours (a stuck
                        # sensor); if lighting shows real occupancy we
                        # DO NOT sweep the lights dark.
                        _sweep_light_ok = not getattr(
                            zone, "any_room_occupied", False,
                        )
                        if (
                            _sweep_light_ok
                            and not zone.vacancy_sweep_done
                            and zone.vacancy_sweep_enabled
                        ):
                            await self._execute_vacancy_sweep(zone)
                            zone.vacancy_sweep_done = True
                            self._vacancy_sweeps_today.increment()
                        _LOGGER.warning(
                            "HVAC: Zone %s occupied >%dh with only %d/%d source(s) "
                            "(threshold %d) — treating as stale sensor",
                            zone.zone_name, self._max_occupancy_hours,
                            confirmed, possible, threshold,
                        )
                        # Stuck-Signal Watchdog D4-P18 (v5.35.0): notify-only
                        # NM emit alongside the existing force-away action.
                        # Per-day dedup latched by zone name to keep a
                        # standing-stale zone from firing every 30s. Behavior
                        # above is UNCHANGED — this is an observability add.
                        from ._stuck_signal_nm import fire_stuck_signal  # noqa: PLC0415
                        self.hass.async_create_task(fire_stuck_signal(
                            self.hass,
                            kind="zone_stale_occupancy",
                            key=(zone.zone_name,),
                            diagnosis=(
                                f"HVAC zone {zone.zone_name} occupied "
                                f">{self._max_occupancy_hours}h with only "
                                f"{confirmed}/{possible} source(s) (threshold "
                                f"{threshold}) — treating as stale sensor, "
                                "forcing away"
                            ),
                            remedy=(
                                "inspect the zone's motion/mmwave/camera "
                                "sensors; a stuck signal is the most likely "
                                "cause"
                            ),
                            # STUCK-SENSOR-1 D4 (P18 diagnosability): the
                            # persisted `_emit_audit_row` message field is
                            # the "[audit]" redaction sentinel, so a bare
                            # `f"Stuck signal: {kind}"` title leaves the
                            # row un-attributable to a zone. Mirror the
                            # P24 title_override pattern.
                            title_override=(
                                f"HVAC zone {zone.zone_name} stuck"
                            ),
                        ))

                # D5: Duty cycle enforcement (skip during sleep — RH4)
                # ARREST-COMFORT-1 Cycle A §3.4 (2026-08-10) — D3 coast-
                # precedence guard. Canonical ordered sequence:
                #   1. read runtime_exceeded and current preset  (already done)
                #   2. read self.battery_soc / self.battery_blind
                #   3. read arrester.comfort_delay_active(zone_id)
                #   4. if SOC >= floor AND not blind AND comfort_delay_active
                #      AND not shed_active: skip forced-away, log reason
                #      `comfort_delay_active`, and DO NOT set effective_preset
                #      to "away".
                #   5. else: proceed with the existing forced-away path.
                # Shed dominates comfort (rev-2 H3 falsification #6). BOTH
                # this site AND the D1 grant read via the SAME accessor —
                # the single-accessor invariant (planning §8).
                # Fix-up A-HIGH-2 + D-b2: per-tick flags hoisted to loop
                # top (fix-up round 3, item 1). Both `_d3_skipped_this_
                # tick` and `_d5_occupancy_deferred_this_tick` are read
                # unconditionally below (reason ladder ~2666/2686); an
                # `if zi:`-scoped reset would leave them unbound on the
                # zi-off path. See loop-top declaration.
                # B1 (fix-up): clear the throttle map for this zone when
                # runtime_exceeded is no longer set — the operator's
                # runtime accumulator dropped below the cap; the S14
                # episode has ended and a future off-phase should emit
                # anew (even if the resolved (low, high) tuple is
                # identical). Matches reviewer spec: throttle discharges
                # on runtime_exceeded clear OR house_state change.
                if (
                    zone.runtime_exceeded
                    and self._house_state != "sleep"
                    and self.d5_enabled  # D-b3 kill switch
                ):
                    _cd_soc = self.battery_soc
                    _cd_blind = self.battery_blind
                    _cd_shed = self.shed_active
                    _cd_active = False
                    if self._override_arrester is not None:
                        try:
                            _cd_active = self._override_arrester.comfort_delay_active(zone_id)
                        except Exception:  # noqa: BLE001 — never let this deny safety
                            _cd_active = False
                    # Fix-up A-HIGH-1: read the LIVE SOC-floor knob so an
                    # operator-tuned floor takes effect without a restart.
                    _cd_floor = self.comfort_soc_floor_pct
                    if (
                        _cd_active
                        and not _cd_shed
                        and not _cd_blind
                        and _cd_soc is not None
                        and float(_cd_soc) >= float(_cd_floor)
                    ):
                        _LOGGER.debug(
                            "HVAC: skipping forced-away on %s — "
                            "comfort_delay_active (soc=%.1f)",
                            zone.zone_name, float(_cd_soc),
                        )
                        # do NOT set effective_preset to "away"; fall
                        # through to the normal preset-decision path.
                        _d3_skipped_this_tick = True
                    else:
                        # S14 REMOVED 2026-09-16 (operator: "Remove s14").
                        #
                        # WHAT WAS HERE. HVAC-PRESET-FLAP-1 (2026-08-11) added
                        # "duty off-phase honesty": in an OCCUPIED zone, rather
                        # than writing preset=away (which relaxes toward ~80F),
                        # it held home_target_high + OFFSET with a RAW SETPOINT
                        # write. The intent was kind — save energy without
                        # abandoning a room someone is sitting in.
                        #
                        # WHY IT IS GONE. A raw setpoint write puts the Bryant
                        # into preset `manual`, and should_change_preset refuses
                        # to act on a manual zone — so S14 CREATED THE EXACT
                        # CONDITION THAT PREVENTED ITS OWN DOCUMENTED EXIT
                        # ("holds until the next preset transition"). No timer,
                        # no decay, no restore: a zone could sit off-preset
                        # indefinitely. The flap fix had introduced a
                        # permanent-manual writer.
                        #
                        # WHY REMOVE RATHER THAN REPAIR. The kill switch had
                        # been OFF for weeks (operator disabled it on instinct,
                        # then called the feature "marginal — possibly should
                        # not have built it at all"), so this limb was already
                        # dead in practice and the away path below was already
                        # what ran. Removal is therefore BEHAVIOUR-NEUTRAL,
                        # while repair would have re-enabled a disliked
                        # behaviour. Costed 2026-09-16; operator picked remove.
                        #
                        # HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1 (D-b2):
                        # OCCUPANCY GATE. D5 is EC coast/shed energy-
                        # shed policy, occupancy-blind. Under coast (NOT
                        # shed) with a fused-occupied zone, DEFER the
                        # force-away — EC's graceful degree-offset
                        # (energy.py:_hvac_constraint_offset) already
                        # sheds this zone; a second blunter force-away
                        # is what we're de-stacking. Under shed we
                        # still force-away (shed dominates — matches
                        # the D3 comfort-delay ordering). Empty zones
                        # under coast still force-away (additive lever
                        # preserved). NO-WRITE defer: leave the zone at
                        # its current preset; do NOT restore S14's
                        # setpoint hold (the 2026-09-16 removal fixed
                        # the manual-lockout bug that produced).
                        _row2054_fused = getattr(
                            zone, "any_room_hvac_occupied", None,
                        )
                        if _row2054_fused is None:
                            _row2054_fused = getattr(
                                zone, "any_room_occupied", True,
                            )
                        # B-M1 (fix-up) — D6×D5 co-occurrence: if D6
                        # stale_occupancy (or any upstream branch) has
                        # ALREADY set `effective_preset = "away"` this
                        # tick, D6 dominates and D5's "defer for
                        # occupancy" would be a false suppression row.
                        # Fall through to the away write and skip the
                        # D5 bookkeeping.
                        if (
                            self._energy_constraint_mode != "shed"
                            and _row2054_fused
                            and effective_preset != "away"
                        ):
                            _d5_occupancy_deferred_this_tick = True
                            _LOGGER.debug(
                                "HVAC: skipping D5 forced-away on %s "
                                "— occupancy gate (mode=%s)",
                                zone.zone_name,
                                self._energy_constraint_mode,
                            )
                            # Episode-gated activity-log row (once per
                            # (zone, constraint_mode, house_state)
                            # episode — mirrors the night_trust
                            # suppressed pattern; NOT per-tick).
                            _ep_key = (
                                self._energy_constraint_mode,
                                self._house_state,
                            )
                            _prev_ep = self._d5_occ_defer_logged_episode.get(zone_id)
                            if _prev_ep != _ep_key and activity_logger:
                                self._d5_occ_defer_logged_episode[zone_id] = _ep_key
                                self.hass.async_create_task(
                                    activity_logger.log(
                                        coordinator="hvac",
                                        action="preset_change_suppressed",
                                        description=(
                                            f"{zone.zone_name} D5 "
                                            f"forced-away suppressed "
                                            f"(coast + occupied)"
                                        ),
                                        zone=zone_id,
                                        importance="notable",
                                        entity_id=zone.climate_entity,
                                        details={
                                            "old_preset": zone.preset_mode,
                                            "new_preset": zone.preset_mode,
                                            "house_state": self._house_state,
                                            "reason": "energy_shed_cap_deferred_occupied",
                                            "energy_shed_cap_reached": bool(
                                                zone.runtime_exceeded,
                                            ),
                                            "constraint_mode": self._energy_constraint_mode,
                                            # F6: mirror the discriminating
                                            # fields onto the defer row so
                                            # INV-D5-GATE is evaluable on the
                                            # SAME shape whether the gate
                                            # fired or the zone was written.
                                            "any_room_hvac_occupied": bool(_row2054_fused),
                                        },
                                    )
                                )
                        else:
                            effective_preset = "away"
                            # HVAC-DEGRADED-ROOM-TRIPWIRE-1 FIX-UP item 2
                            # (2026-09-26): D5 shed/coast force-away is a
                            # SAFETY-adjacent energy-shed response. If we
                            # had armed the row-1 hold, clear it now so
                            # the shed-directed write proceeds; the hold
                            # only suppresses the row-1-vacancy write,
                            # not a safety-directed one.
                            _row1_hold_write = False
                            # v5.103.20 D5: the pending-arm hold clears on
                            # the same shed path (plan §5.2).
                            _pending_arm_hold_write = False
                            _shed_forced_away_this_tick = True
                # Expose per-zone D3-skip flag for the sensor attribute (D3).
                try:
                    self._d3_skipped_current_tick[zone_id] = bool(_d3_skipped_this_tick)
                except Exception:  # noqa: BLE001
                    pass
                # HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1 (D-b2): expose
                # the per-zone D5 occupancy-defer flag on the same
                # sensor surface.
                try:
                    self._d5_occupancy_deferred_current_tick[zone_id] = bool(
                        _d5_occupancy_deferred_this_tick,
                    )
                except Exception:  # noqa: BLE001
                    pass

                # v4.2.2 "zone entry dwell" (lighting-session skip) RETIRED
                # in v5.103.20 (plan §5b.5): it read the LIGHTING session
                # clock — the one HVAC occupancy was built to be independent
                # of (state of play §3.2). Knob 47 now drives the D5 entry
                # transit filter in the producer (hvac_zones `_d5_update`)
                # and the pending-arm hold above. Behaviour-neutral at the
                # live value 0.

            # v4.7.13 + fan-trust extension: Night-window zone presence
            # trust — suppress preset flip to "away" during the night-trust
            # window (home_night/sleep/waking) when any zone_persons member
            # is "home". Mirrors the D5 duty-cycle / D6 stale-failsafe
            # sleep-skip pattern but for OCCUPANCY (not runaway timers).
            # NB: D5 and D6 above remain sleep-only by design — they guard
            # against runaway timers / stuck sensors and the sleep-only
            # gate prevents lockout in daytime. THIS branch is the trust
            # branch and extends to flank states.
            # Rationale: room sensors degenerate during the night-trust
            # window (mmWave drops motionless bodies, PIR can't fire on
            # stationary, camera blind in dark room). The phone-based
            # person tracker is the stable signal.
            # Bidirectionality: this branch only suppresses while at least
            # one zone_persons member is "home". The v4.7.14 all-trackers-
            # away veto path (StateInferenceEngine → HouseState.AWAY) is
            # NOT affected — when all trackers are away `home_persons` is
            # empty and this branch falls through, allowing the normal
            # `away` preset path to run. Live finding 2026-06-05
            # (project_zone_away_when_occupied_home_night_gap.md): Zone 1
            # flipped to `away` 7+ times during home_night because this
            # gate was sleep-only.
            # HVAC-ZONE-CONDITIONING-DEMAND-1 D7 (fix-up round 4,
            # 2026-09-17). Uses the shared `_zone_conditioning_retreat_ok`
            # helper (F3). Preserve preset iff retreat is NOT authorized —
            # i.e. iff the zone is unestablished (reset-only backstop) OR
            # fused-occupied. When established+empty, we FALL THROUGH
            # (no suppression) and `away` stands. Person-trust preserve
            # dropped from the established path per operator round-4
            # decision.
            if (
                effective_preset == "away"
                and self._house_state in FAN_TRUST_STATES
                and not self._zone_conditioning_retreat_ok(zone)
            ):
                home_persons = []
                try:
                    for person_entity in (zone.zone_persons or []):
                        st = self.hass.states.get(person_entity)
                        if st is not None and st.state == "home":
                            home_persons.append(person_entity)
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.debug(
                        "HVAC: night-trust person check errored for zone %s: %s",
                        zone.zone_name, exc,
                    )
                    home_persons = []
                if home_persons:
                    # A-L1 de-noise: clear log-once cache when state changed.
                    if self._night_trust_logged_state != self._house_state:
                        self._night_trust_logged.clear()
                        self._night_trust_logged_state = self._house_state
                    log_key = (zone_id, self._house_state)
                    first_fire = log_key not in self._night_trust_logged
                    if first_fire:
                        self._night_trust_logged.add(log_key)
                        _LOGGER.info(
                            "HVAC: Suppressing %s preset flip -> away during %s "
                            "(zone_persons home: %s) [subsequent suppressed]",
                            zone.zone_name, self._house_state, home_persons,
                        )
                    else:
                        _LOGGER.debug(
                            "HVAC: Suppressing %s preset flip -> away during %s "
                            "(zone_persons home: %s)",
                            zone.zone_name, self._house_state, home_persons,
                        )
                    # Reason-ledger (Writer-B removal cycle 2026-08-06):
                    # log the suppression as a synthetic preset_change_suppressed
                    # row so the ledger shows WHY the coordinator didn't flip
                    # to away. Reason: night_trust_suppressed. Inputs echoed
                    # so mixed causes remain visible.
                    # B-M1 (2026-08-06 fix-up): episode-gated on the existing
                    # per-(zone,house_state) _night_trust_logged cache so a
                    # standing suppression emits ONE row per episode, not one
                    # per tick (~480/night/zone). Description omits the
                    # home_persons list (kept in details_json) so the row's
                    # dedup key is stable across membership churn.
                    if first_fire and activity_logger:
                        self.hass.async_create_task(
                            activity_logger.log(
                                coordinator="hvac",
                                action="preset_change_suppressed",
                                description=(
                                    f"{zone.zone_name} preset flip -> away suppressed "
                                    f"during {self._house_state}"
                                ),
                                zone=zone_id,
                                importance="notable",
                                entity_id=zone.climate_entity,
                                details={
                                    "old_preset": zone.preset_mode,
                                    "new_preset": zone.preset_mode,
                                    "house_state": self._house_state,
                                    "reason": "night_trust_suppressed",
                                    "zone_vacant_past_grace": zone_vacant_past_grace,
                                    # D-b1 rename (operator-facing).
                                    "energy_shed_cap_reached": bool(zone.runtime_exceeded),
                                    "home_persons": list(home_persons),
                                },
                            )
                        )
                    continue

            # HVAC-DEGRADED-ROOM-TRIPWIRE-1 FIX-UP item 2 (2026-09-26,
            # RESTRUCTURED): if row-1 hold is armed AND no safety path
            # (D5 shed / D6 stale) cleared it above, HOLD the preset —
            # no write in either direction. D6 cannot fire under
            # fused-empty; D5 clears the hold in its force-away branch;
            # night-trust (D7) above already `continue`s independently.
            if _row1_hold_write:
                # FIX-UP round 3 item 8 (2026-09-26): episode-gated
                # durable log so a held write is diagnosable (previously
                # only a DEBUG line). Mirror of the D5-defer / D7 night-
                # trust `preset_change_suppressed` pattern: one row per
                # (zone, house_state, target_preset) episode, not per
                # tick. Reason "transient_room_hold" so the ledger can
                # be filtered.
                _ep = (self._house_state, target_preset)
                if (
                    self._row1_hold_logged_episode.get(zone_id) != _ep
                    and activity_logger is not None
                ):
                    self._row1_hold_logged_episode[zone_id] = _ep
                    try:
                        self.hass.async_create_task(
                            activity_logger.log(
                                coordinator="hvac",
                                action="preset_change_suppressed",
                                description=(
                                    f"{zone.zone_name} preset write "
                                    f"held: sibling room reloading "
                                    f"(target={target_preset}, house="
                                    f"{self._house_state})"
                                ),
                                zone=zone_id,
                                importance="notable",
                                entity_id=zone.climate_entity,
                                details={
                                    "old_preset": zone.preset_mode,
                                    "new_preset": zone.preset_mode,
                                    "house_state": self._house_state,
                                    "reason": "transient_room_hold",
                                    "target_preset": target_preset,
                                    "energy_shed_cap_reached": bool(
                                        zone.runtime_exceeded,
                                    ),
                                    "any_room_hvac_occupied": bool(
                                        getattr(
                                            zone, "any_room_hvac_occupied",
                                            False,
                                        )
                                    ),
                                },
                            )
                        )
                    except Exception:  # noqa: BLE001
                        _LOGGER.debug(
                            "row-1 transient-room-hold ledger write failed",
                            exc_info=True,
                        )
                continue

            # v5.103.20 D5 pending-arm hold (plan §5.2, REV 7 H1/L1): same
            # `continue` before S1 as the row-1 hold; one
            # `preset_change_suppressed` row (reason `pending_arm_hold`) per
            # hold SPELL — the latch is cleared when the hold drops, so a
            # standing spell logs once and every new spell logs again.
            if _pending_arm_hold_write:
                if zone_id not in self._pending_hold_logged:
                    self._pending_hold_logged.add(zone_id)
                    if activity_logger is not None:
                        try:
                            _pending_rooms = list(
                                getattr(zone, "hvac_pending_arm_rooms", []) or []
                            )
                            _ep_starts = {}
                            try:
                                for _r in _pending_rooms:
                                    _d = self._zone_manager.hvac_occupied_diag(_r)
                                    _ep_starts[_r] = _d.get("episode_start")
                            except Exception:  # noqa: BLE001
                                _ep_starts = {}
                            self.hass.async_create_task(
                                activity_logger.log(
                                    coordinator="hvac",
                                    action="preset_change_suppressed",
                                    description=(
                                        f"{zone.zone_name} preset write held: "
                                        f"room deciding whether it is a stay "
                                        f"(target={target_preset}, house="
                                        f"{self._house_state})"
                                    ),
                                    zone=zone_id,
                                    importance="notable",
                                    entity_id=zone.climate_entity,
                                    details={
                                        "old_preset": zone.preset_mode,
                                        "new_preset": zone.preset_mode,
                                        "house_state": self._house_state,
                                        "reason": "pending_arm_hold",
                                        "target_preset": target_preset,
                                        "pending_rooms": _pending_rooms,
                                        "episode_starts": _ep_starts,
                                        "trigger": trigger,
                                        "any_room_hvac_occupied": bool(
                                            getattr(zone, "any_room_hvac_occupied", False)
                                        ),
                                    },
                                )
                            )
                        except Exception:  # noqa: BLE001
                            _LOGGER.debug(
                                "pending-arm-hold ledger write failed", exc_info=True,
                            )
                continue

            # --- Determine if preset change is needed ---
            # Bypass should_change_preset() manual guard for vacancy (RH3 fix)
            # Lockout episode discharges as soon as the zone is out of manual
            # (suppression-needs-a-discharge: an episode that never ends would
            # under-count every later lockout).
            if zone.preset_mode != "manual":
                self._preset_lockout_since.pop(zone_id, None)
            # HVAC W1-B §5.P1 — the S1 manual rule (Alt A, four gates).
            # `should_change_preset` now reads the gates for a `manual`
            # zone (person-protected hold / arrester window / arrester
            # disabled / live borrow) and refuses ONLY while one is armed;
            # otherwise S1 takes the zone out of `manual` on this tick
            # (C-P1A). A refusal is a DEFERRAL with a named gate, recorded
            # once per episode as `preset_change_deferred` (KEEP+WIRE of the
            # old `preset_change_locked_out` row).
            _deferred_reason: str | None = None
            _deferred_snapshot: dict = {}
            if zi and (zone_vacant_past_grace or zone.runtime_exceeded) and effective_preset == "away":
                if zone.preset_mode == "away":
                    continue  # Already away
                # M3 / N9b: the vacancy/runtime bypass skips the manual rule
                # for `away` — but it must still respect a person-protected
                # hold (a/b, incl. restart-restored TAO) and a live borrow
                # (e). Gates (c) and (d) do NOT block the bypass (an empty
                # zone going away is not fighting a grace, and a passive
                # arrester does not own an empty zone).
                if zone.preset_mode == "manual":
                    _vb = self._preset_manager.manual_guard_verdict(zone_id)
                    _vs = _vb.get("gate_snapshot", {})
                    if _vs.get("a_b"):
                        _deferred_reason = "vacancy_bypass_deferred:person_protected_hold"
                    elif _vs.get("e"):
                        _deferred_reason = "vacancy_bypass_deferred:active_borrow"
                    _deferred_snapshot = _vs
            elif not self._preset_manager.should_change_preset(
                zone.preset_mode, effective_preset, zone_id=zone_id,
            ):
                if zone.preset_mode == "manual":
                    _v = self._preset_manager.last_manual_verdict(zone_id) or {}
                    _deferred_reason = _v.get("reason") or "unknown"
                    _deferred_snapshot = _v.get("gate_snapshot", {}) or {}
                else:
                    continue  # already at target: benign no-op, never recorded
            if _deferred_reason is not None:
                # EDGE-TRIGGERED, not per-tick: one row when a deferral
                # EPISODE begins (per zone), carrying what URA wanted and
                # which gate refused; the episode ends when the zone leaves
                # manual (cleared above). Per-gate daily breakdown feeds
                # diagnostics.
                _lk = self._preset_lockout_since.get(zone_id)
                if _lk is None:
                    self._preset_lockout_since[zone_id] = dt_util.utcnow()
                    self._preset_deferrals_today.increment()
                    _gate_key = _deferred_reason.split(":")[-1]
                    self._preset_deferrals_by_gate[_gate_key] = (
                        self._preset_deferrals_by_gate.get(_gate_key, 0) + 1
                    )
                    if activity_logger is not None:
                        try:
                            self.hass.async_create_task(
                                activity_logger.log(
                                    coordinator="hvac",
                                    action="preset_change_deferred",
                                    description=(
                                        f"{zone.zone_name} wanted preset "
                                        f"{effective_preset}; zone is in manual "
                                        f"and deferred by {_deferred_reason}"
                                    ),
                                    importance="info",
                                    zone=zone_id,
                                    entity_id=zone.climate_entity,
                                    details={
                                        "wanted": effective_preset,
                                        "reason": _deferred_reason,
                                        "gate_snapshot": _deferred_snapshot,
                                    },
                                )
                            )
                        except Exception:  # noqa: BLE001
                            _LOGGER.debug(
                                "preset deferral ledger write failed",
                                exc_info=True,
                            )
                continue

            # Reason-ledger derivation (Writer-B removal cycle 2026-08-06):
            # tag each preset_change with WHY the coordinator wrote it. Derived
            # from the actual decision branch that produced effective_preset,
            # not post-hoc inference. Approved vocabulary (per audit §reason-
            # ledger): house_state_transition | vacant_past_grace |
            # runtime_exceeded | stale_occupancy | night_trust_suppressed |
            # pre_arrival.
            # (`manual_detected` is a CANDIDATE future reason once URA gains a
            # manual-detection code path that produces a write or suppression
            # event — no site emits it today; do not add to derivations without
            # a real branch.)
            # Precedence for concurrent inputs (top wins, exact order pinned
            # by TestReasonLadderPrecedence):
            #   stale_occupancy > vacant_past_grace > runtime_exceeded >
            #   pre_arrival > house_state_transition.
            # A-L2/B-L2 (2026-08-06 fix-up) — precedence notes:
            #   * vacant_past_grace / runtime_exceeded / stale_occupancy are
            #     AWAY-gated (`effective_preset == "away"` predicate) because
            #     each is a branch that FORCED away against target_preset;
            #     they only make sense as the reason for an away write.
            #   * pre_arrival is ORTHOGONAL to effective_preset — a zone in
            #     the pre-arrival set may be written to any preset, and the
            #     reason should reflect the pre-arrival lifecycle, not the
            #     target preset value.
            #   * B-H1 fix-up: stale_occupancy ranks FIRST because the D6
            #     stuck-sensor branch (which sets both `stale_occupancy` and
            #     `effective_preset = "away"` against any_room_occupied=True)
            #     ALSO satisfies neither `zone_vacant_past_grace` nor
            #     `runtime_exceeded` on its own — the ladder would otherwise
            #     fall through to `house_state_transition` and mislabel.
            # Both underlying booleans (vacant/runtime) are recorded in
            # details so mixed causes remain visible even though `reason` is
            # single-valued.
            if stale_occupancy:
                preset_change_reason = "stale_occupancy"
            elif effective_preset == "away" and _shed_forced_away_this_tick:
                # fix-up 1 (D-L2): a shed/coast force-away is never booked
                # as a vacancy retreat even when the zone is also past grace.
                preset_change_reason = "energy_shed_cap_reached"
            elif effective_preset == "away" and zone_vacant_past_grace:
                preset_change_reason = "vacant_past_grace"
            elif effective_preset == "away" and zone.runtime_exceeded:
                # HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1 (D-b1): renamed
                # from `runtime_exceeded` → `energy_shed_cap_reached`.
                # D5 is EC coast/shed energy-shed policy, not compressor
                # protection. See PLANNING_hvac_d5_reframe_occupancy_gate.md.
                preset_change_reason = "energy_shed_cap_reached"
            elif zone_id in self._pre_arrival_zones:
                preset_change_reason = "pre_arrival"
            else:
                preset_change_reason = "house_state_transition"

            # ARREST-COMFORT-1 Cycle A §3.4 (2026-08-10): reason-ladder
            # leaf `comfort_delay_active`. If the D3 guard above skipped
            # the runtime_exceeded forced-away because comfort-delay is
            # active, we detect that by (a) runtime_exceeded True AND
            # (b) effective_preset is NOT "away" AND (c) the arrester
            # confirms comfort_delay_active — and re-label the reason
            # for the ledger so the operator can see WHY we didn't force
            # away. Precedence: this label overrides house_state_transition
            # since the comfort-grace was the actual reason we're here.
            # Fix-up A-HIGH-2: relabel ONLY when the D3 guard actually
            # skipped a forced-away this tick. Without this the pre-fix
            # check hijacked ANY non-away preset write while
            # runtime_exceeded && comfort_delay_active — mislabeling
            # legitimate house-state / occupant-home writes.
            if (
                _d3_skipped_this_tick
                and zone.runtime_exceeded
                and effective_preset != "away"
                and self._override_arrester is not None
            ):
                try:
                    if self._override_arrester.comfort_delay_active(zone_id):
                        preset_change_reason = "comfort_delay_active"
                except Exception:  # noqa: BLE001
                    pass
            # HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1 (D-b2) fix-up F4:
            # when the D5 occupancy gate deferred this tick, but some
            # OTHER path is still driving a preset_change (i.e. we
            # reached the emit below), relabel the reason so the
            # ledger records WHY the D5 force-away didn't fire. This
            # does NOT feed `_s1_defer_reasons` — the label is purely
            # a ledger surface; deferral is a strictly non-emit path
            # elsewhere. Fires only when the D5 defer flag AND the
            # gate-satisfying preconditions held.
            if (
                _d5_occupancy_deferred_this_tick
                and zone.runtime_exceeded
                and preset_change_reason
                in ("house_state_transition", "pre_arrival")
            ):
                preset_change_reason = "energy_shed_cap_deferred_occupied"

            # Suppress arrester for URA-initiated changes.
            # HVAC W1-B §5.P3 (M4): kind="preset" (120 s window) — S1 is a
            # PRESET write; its Carrier echo (resume -> pin -> refresh)
            # lands well past the 15 s temp window and was booked as a
            # fresh override.
            if self._override_arrester:
                self._override_arrester.suppress(zone.climate_entity, kind="preset")

            # HVAC W1-B P2 (N4): classify a manual write-through BEFORE the
            # wire call from the arrester's in-memory last detection for
            # this manual episode. sub_delta_human := a booked detection
            # whose |delta_f| is under the revert threshold (+1 F in coast);
            # zero_delta_ura := no booked detection in this episode (the
            # URA-caused strand class). Reason ladder untouched; no NM.
            _manual_class = "not_manual"
            _last_det: dict | None = None
            if zone.preset_mode == "manual":
                try:
                    if self._override_arrester is not None:
                        _last_det = self._override_arrester.last_detection_for(
                            zone.climate_entity,
                        )
                except Exception:  # noqa: BLE001
                    _last_det = None
                _manual_class = self._classify_manual_episode(_last_det)

            # Execute the service call directly
            #
            # KNOWN BOUNDARY (freeze floor): the freeze-protection floor
            # (hvac_setpoint.emit_set_temperature) governs URA-emitted
            # set_temperature ranges only, NOT set_preset_mode. If
            # guest-mode-actuation is disabled (so URA emits no explicit range)
            # AND the thermostat's OWN device-side away/vacation preset is
            # configured below 50°F, that zone can sit below the freeze floor
            # during a freeze. Operator-accepted 2026-06-18 as a narrow
            # boundary (requires a thermostat away-preset literally set < 50°F).
            # Not fixed to avoid a double-writer self-fight.
            try:
                # ARREST-COMFORT-1 Cycle A §3.7 S1 (2026-08-10): route
                # through the new `emit_set_preset_mode` chokepoint. The
                # per-reason DEFER/ALLOW verdict from §3.7 fires here:
                #   DEFER while comfort_delay_active iff reason ∈
                #     {runtime_exceeded, house_state_transition,
                #      comfort_delay_active (self-referential no-op)}.
                #   ALLOW unconditionally for {freeze, vacant_past_grace,
                #     stale_occupancy, pre_arrival}.
                _s1_zone_id = zone_id
                _s1_reason = preset_change_reason
                # D5 ledger inputs captured BEFORE the write (plan §5.2).
                _last_away_reason_before = self._zone_last_away_reason.get(zone_id)
                try:
                    _established_at_write = bool(
                        self._zone_manager.is_zone_hvac_established(zone_id)
                    )
                except Exception:  # noqa: BLE001
                    _established_at_write = False
                _s1_defer_reasons = {
                    # D-b1 rename: was `runtime_exceeded`.
                    "energy_shed_cap_reached",
                    "house_state_transition",
                    "comfort_delay_active",
                }
                def _s1_gate() -> bool:
                    if _s1_reason not in _s1_defer_reasons:
                        return False
                    if self._override_arrester is None:
                        return False
                    try:
                        return bool(
                            self._override_arrester.comfort_delay_active(_s1_zone_id)
                        )
                    except Exception:  # noqa: BLE001
                        return False
                # HVAC W1-B D1 (C5): S1 writes through the per-brand
                # strategy. `hold_preset` routes into the SAME funnel
                # (resume-then-pin untouched) and adds the strategy-layer
                # no-op: SKIPPED_ALREADY_CORRECT = zero service calls.
                from .hvac_strategy import strategy_for, WriteStatus  # noqa: PLC0415
                _s1_result = await strategy_for(
                    self.hass, zone.climate_entity,
                ).hold_preset(
                    self.hass,
                    zone.climate_entity,
                    effective_preset,
                    blocking=False,
                    gate=_s1_gate,
                    site="S1_reason_ladder",
                    zone_id=zone_id,
                    reason=preset_change_reason,
                )
                if _s1_result.status is WriteStatus.SKIPPED_ALREADY_CORRECT:
                    _LOGGER.debug(
                        "HVAC: S1 no-op on %s (%s already sent and observed)",
                        zone.zone_name, effective_preset,
                    )
                    if self._override_arrester:
                        self._override_arrester.unsuppress(zone.climate_entity)
                    continue
                if _s1_result.status is WriteStatus.FAILED:
                    raise RuntimeError(
                        f"S1 strategy write failed: {_s1_result.reason} "
                        f"{_s1_result.exc or ''}".strip()
                    )
                if _s1_result.status is not WriteStatus.APPLIED:
                    # Deferred by comfort-grace — do NOT log the "Set
                    # preset" line nor emit the preset_change activity
                    # row; the deferred-write ledger row has already
                    # been logged by the chokepoint. B-L3: nothing went
                    # out, so roll back the pre-emit suppress stamp.
                    if self._override_arrester:
                        self._override_arrester.unsuppress(zone.climate_entity)
                    continue
                # HVAC W1-B D2.1: this zone was written this tick — the
                # arrester's soft-nudge dispatch skips it until next tick.
                self._zones_written_this_cycle.add(zone_id)
                # v5.103.20 (plan §5.2, REV 2 #4): per-zone S1 write stamp —
                # seeds the next tick's nudge skip, keys the limiter
                # exemption and the quick-return trip-wire.
                _s1_ts = dt_util.utcnow()
                _prev_applied = self._zone_last_s1_write.get(zone_id)
                # (preset, reason, ts) — APPLIED writes ONLY (plan §5.2).
                self._zone_last_s1_write[zone_id] = (
                    effective_preset, preset_change_reason, _s1_ts,
                )
                if effective_preset == "away":
                    self._zone_last_away_reason[zone_id] = preset_change_reason
                    # Only an APPLIED `vacant_past_grace` away that is a REAL
                    # transition (previous applied write not away — the §9.7
                    # re-issue loop must not re-anchor) anchors the
                    # quick-return alarm (plan §5.2 / §5.7; fix-up 1 D-M3).
                    if (
                        preset_change_reason == "vacant_past_grace"
                        and not (_prev_applied is not None and _prev_applied[0] == "away")
                    ):
                        self._zone_vacancy_away_at[zone_id] = _s1_ts
                wrote_any = True
                # fix-up 1 (A-MED1): only FAST runs count toward the write
                # ceiling — house_state / pre_arrival cycles are periodic-class.
                if trigger in ("fast_entry", "fast_exit"):
                    self._note_fast_write(zone_id, _s1_ts, edge_ts)
                # HVAC W1-B §5.P5: reclaim-rate trip-wire on manual
                # write-throughs only.
                if zone.preset_mode == "manual":
                    self._note_s1_reclaim(zone_id, zone.zone_name, preset_change_reason)
                _LOGGER.info(
                    "HVAC: Set %s preset %s -> %s (house_state=%s%s)",
                    zone.zone_name, zone.preset_mode, effective_preset,
                    self._house_state,
                    " [vacancy]" if zone_vacant_past_grace and effective_preset == "away" else "",
                )
                # Activity log: HVAC preset change.
                # DOMAIN is imported at module level (line 27). Re-importing
                # here would make DOMAIN function-local for the whole scope
                # and break the earlier reference at line ~806 (v4.7.15.1 D6
                # defer-gate path) with UnboundLocalError. Bug Class #34.
                # activity_logger hoisted above the zone loop (B-L1 fix-up).
                if activity_logger:
                    # B-L3 (2026-08-06 fix-up): capture which zone_persons are
                    # home at write time for episode correlation with the
                    # night-trust suppressed rows above. Guarded — a state
                    # read failure must not block the preset write's log.
                    main_row_home_persons: list[str] = []
                    try:
                        for _p in (zone.zone_persons or []):
                            _st = self.hass.states.get(_p)
                            if _st is not None and _st.state == "home":
                                main_row_home_persons.append(_p)
                    except Exception:  # noqa: BLE001
                        main_row_home_persons = []
                    self.hass.async_create_task(
                        activity_logger.log(
                            coordinator="hvac",
                            action="preset_change",
                            description=f"{zone.zone_name} preset {zone.preset_mode} -> {effective_preset} (house={self._house_state})",
                            zone=zone_id,
                            importance="notable",
                            entity_id=zone.climate_entity,
                            details={
                                "old_preset": zone.preset_mode,
                                "new_preset": effective_preset,
                                "house_state": self._house_state,
                                "reason": preset_change_reason,
                                "zone_vacant_past_grace": zone_vacant_past_grace,
                                # v5.103.20 (plan §5.2): which path wrote
                                # (`periodic` / `fast_entry` / `fast_exit`),
                                # the evidence edge that triggered a fast
                                # entry, and the zone's release anchor on
                                # an away row (L1-L4 live checks).
                                "trigger": trigger,
                                "edge_ts": (
                                    edge_ts.isoformat() if edge_ts is not None else None
                                ),
                                "zone_empty_since": (
                                    zone.last_occupied_time.isoformat()
                                    if (
                                        effective_preset == "away"
                                        and zone.last_occupied_time is not None
                                    )
                                    else None
                                ),
                                # D5 (plan §5.2, REV 7 M1): the L15 predicate
                                # fields — exempt re-arm, establishment at
                                # write time, and the reason of Z's last
                                # APPLIED away (before this write).
                                "exempt_reason": exempt_reason,
                                "established": _established_at_write,
                                "last_away_reason": _last_away_reason_before,
                                # D-b1 rename (operator-facing).
                                "energy_shed_cap_reached": bool(zone.runtime_exceeded),
                                # F6 (fix-up) — DISCRIMINATING fields so
                                # INV-D5-GATE can be evaluated against
                                # the ledger. constraint_mode + occupancy
                                # split the "did the gate actually apply"
                                # verdict from the "was the reason we
                                # got here" label.
                                "constraint_mode": self._energy_constraint_mode,
                                "any_room_hvac_occupied": bool(
                                    getattr(zone, "any_room_hvac_occupied", None)
                                    if getattr(zone, "any_room_hvac_occupied", None)
                                    is not None
                                    else getattr(zone, "any_room_occupied", False)
                                ),
                                "home_persons": main_row_home_persons,
                                # HVAC W1-B P2 (N4) + C-P1B/C-P1D: the
                                # manual-episode class and the gate
                                # snapshot at write time. Lives on S1's
                                # OWN row (the funnel's `climate_write`
                                # payload is untouched — operator
                                # constraint); the falsifiers join this
                                # row to the `climate_write` row by
                                # zone + timestamp.
                                "manual_class": _manual_class,
                                "gate_snapshot": (
                                    (self._preset_manager.last_manual_verdict(zone_id) or {})
                                    .get("gate_snapshot", {})
                                    if zone.preset_mode == "manual" else {}
                                ),
                                "last_detection": _last_det,
                            },
                        )
                    )
            except Exception as e:
                _LOGGER.error(
                    "HVAC: Failed to set preset on %s: %s",
                    zone.climate_entity, e,
                )
                continue

            # Log decision
            decision_id = None
            if self._decision_logger:
                from .coordinator_diagnostics import DecisionLog

                decision_id = await self._decision_logger.log_decision(
                    DecisionLog(
                        timestamp=dt_util.utcnow(),
                        coordinator_id=self.coordinator_id,
                        decision_type="preset_change",
                        scope=f"zone:{zone_id}",
                        situation_classified=f"house_state_{self._house_state}",
                        urgency=30,
                        confidence=1.0,
                        context={
                            "house_state": self._house_state,
                            "old_preset": zone.preset_mode,
                            "new_preset": effective_preset,
                            "vacancy_override": zone_vacant_past_grace,
                            # D-b1 rename (operator-facing).
                            "energy_shed_cap_reached": zone.runtime_exceeded,
                            "reason": preset_change_reason,
                        },
                        action={"preset_mode": effective_preset},
                        devices_commanded=[zone.climate_entity],
                    )
                )

            # Schedule compliance check
            if self._compliance:
                await self._compliance.schedule_check(
                    decision_id=decision_id or 0,
                    scope=f"zone:{zone_id}",
                    device_type="climate",
                    device_id=zone.climate_entity,
                    commanded_state={"preset_mode": effective_preset},
                )

        # v4.7.1 fix-up D2: After preset changes, apply OverrideEngine temperature
        # ranges if guest_mode_actuation is enabled (Bug #23 — skip in obs mode).
        # v5.103.20 (plan §5.2 / INV-4): DPM overrides are house-wide and
        # tick-cadence — a zone-scoped fast run SKIPS them.
        if not self._observation_mode and zone_filter is None:
            await self._async_apply_preset_overrides()
        # fix-up 2 (D-L1): a zone whose S1 block was skipped this tick
        # (zone intelligence off, egress pause, ...) is not held.
        self._close_unseen_pending_spells(_pending_seen, zone_filter)
        return wrote_any

    # ------------------------------------------------------------------
    # feature/freeze-floor: freeze-protection heat_low FLOOR
    # ------------------------------------------------------------------

    def _get_best_outdoor_temp(self) -> float | None:
        """Return the best-available outdoor temperature (°F), or None.

        Primary source is the predictor's configured outdoor-temp entity
        (shared from the cover controller in async_setup). Fail-open: if no
        usable reading is available we return None and the caller treats
        freeze as NOT active — we never fabricate a freeze.
        """
        try:
            predictor = getattr(self, "_predictor", None)
            if predictor is not None:
                temp = predictor._get_outdoor_temp()
                if temp is not None:
                    return temp
        except Exception:  # noqa: BLE001 — fail-open on any read error
            _LOGGER.debug("HVAC: freeze-floor outdoor temp read failed", exc_info=True)
        return None

    def _update_freeze_active(self) -> bool:
        """Re-derive and latch the freeze-active state with hysteresis.

        Freeze ARMS when outdoor ≤ FREEZE_TRIGGER_TEMP; once armed it stays
        armed until outdoor > FREEZE_TRIGGER_TEMP + FREEZE_TRIGGER_HYSTERESIS
        (38°F by default). Missing outdoor temp → fail-open (clear / never
        arm). State is RAM-only; on restart it re-derives from the live temp.
        """
        temp = self._get_best_outdoor_temp()
        was_active = self._freeze_active
        if temp is None:
            # Fail-open: no trusted source → do not hold a fabricated freeze.
            self._freeze_active = False
        elif not self._freeze_active:
            if temp <= FREEZE_TRIGGER_TEMP:
                self._freeze_active = True
        else:
            # Already armed — clear only above the hysteresis ceiling.
            if temp > FREEZE_TRIGGER_TEMP + FREEZE_TRIGGER_HYSTERESIS:
                self._freeze_active = False

        if self._freeze_active != was_active:
            _LOGGER.info(
                "HVAC: freeze-protection floor %s (outdoor=%s°F, floor=%s°F)",
                "ARMED" if self._freeze_active else "cleared",
                temp, FREEZE_FLOOR,
            )
        return self._freeze_active

    async def _async_apply_preset_overrides(self) -> None:
        """D2: Apply OverrideEngine temperature ranges to thermostats.

        v4.7.1 Phase 1 D2 (PLANNING_v4.7.x_guest_mode_actuation_phase1.md §5.D2).

        Reads override records from the EC's _dynamic_preset_overrides dict,
        resolves them via OverrideEngine against the seasonal baseline, and
        issues set_temperature when the resolved range differs from the
        last-emitted range (throttle guard).

        Always wrapped in OverrideArrester.suppress so URA's own
        set_temperature call is not read as a manual override.

        Bug #23: gate is on this method (actuation side), not the source.
        Bug #19: no async_create_task — awaited inline.
        Bug #42: no lambda in any callback.
        """
        if not self._guest_mode_actuation_enabled:
            _LOGGER.debug("HVAC: guest_mode_actuation disabled — skipping override apply")
            return

        try:
            from ..const import DOMAIN as _DOMAIN_KEY
            from .preset_overrides import OverrideEngine

            # Get EC's accumulated overrides from the last evaluate tick
            ec = None
            manager = self.hass.data.get(_DOMAIN_KEY, {}).get("coordinator_manager")
            if manager is not None:
                ec = manager.coordinators.get("energy")
            if ec is None:
                return

            all_overrides = getattr(ec, "_dynamic_preset_overrides", {})
            master_enabled = self._guest_mode_actuation_enabled
            engine = OverrideEngine()

            # feature/freeze-floor (D-HIGH-1): `_freeze_active` is refreshed
            # unconditionally at the top of `_run_decision_cycle`, BEFORE this
            # gated apply path runs, so it is already current here. The clamp
            # below (via the setpoint chokepoint) raises a dangerously-low
            # resolved heat_low up to FREEZE_FLOOR.

            target_preset = self._preset_manager.get_preset_for_house_state(
                self._house_state
            )
            if target_preset is None:
                return

            # snapshot: zones dict may be pruned by _handle_zm_zones_updated mid-await
            for zone_id, zone in list(self._zone_manager.zones.items()):
                # v4.7.8 fix-up C-H1 (plan §D8 spec gap): DPM apply must
                # skip egress-paused zones. Ecobee thermostats re-engage
                # mode on set_temperature after an explicit off, silently
                # defeating the pause. Mirrors the predictor pre-cool /
                # pre-heat guards.
                if (
                    self._egress_manager is not None
                    and self._egress_manager.is_paused(zone_id)
                ):
                    continue
                # MED-A1 (promoted): DPM preset-override apply is a
                # corrective set_temperature over a zone the operator
                # may currently be holding manually (immunity) or the
                # house-wide Temp Arrester Override may be engaged. In
                # either case the DPM write would overwrite an intent
                # the operator explicitly asked us to leave alone. Third
                # shaver: gate here through the same helper as every
                # other shave path so the "operator holds are
                # untouchable" claim is complete.
                _arr = self._override_arrester
                _gate = getattr(
                    _arr, "_corrective_writes_suppressed", None,
                )
                if _arr is not None and callable(_gate) and _gate(zone_id):
                    _log = getattr(_arr, "_log_shave_skipped", None)
                    if callable(_log):
                        _log(zone.zone_name, zone_id, "dpm_preset_override")
                    continue
                # HVAC-ZONE-CONDITIONING-DEMAND-1 D9 (2026-09-17 fix-up
                # round 2 — COMPOSE-AWAY, operator-endorsed). CALLER-SIDE
                # POINT-GATE on the FUSED HVAC-occupancy denomination. When
                # the zone is empty in `zone.any_room_hvac_occupied` (D1
                # fused signal), the DPM DOES NOT SKIP — it composes the
                # `away` preset baseline (instead of the house-state
                # target_preset baseline) for THIS zone and emits it
                # through the existing chokepoint.
                #
                # Why compose-away (not skip): the DPM is the *corrector*
                # for third-writer restores (nudge-restore, pre-heat
                # return, ramp-audit) that would otherwise strand an
                # empty zone at comfort setpoints all night (D-HIGH-2 —
                # sibling writer strands the zone). Emitting the `away`
                # baseline lets the throttle guard on `_last_emitted_range`
                # dedupe repeat writes cheaply, and any concurrent
                # third-writer restore is overwritten on the next tick.
                #
                # Fail-OPEN polarity (D-MED-2, unified with D7/row-1):
                # when the fused signal is UN-ESTABLISHED for this zone
                # (D1 producer has not observed >=1 arm/release cycle
                # for any of the zone's rooms since ZoneManager
                # construction — see `_is_zone_hvac_established`) OR the
                # zone has no room_conditions yet (early boot / test
                # fake), keep pre-cycle behaviour: use the caller-narrowed
                # `target_preset`, no retreat. Only ESTABLISHED empty
                # zones compose-away.
                #
                # Fix-up round 4 (2026-09-17, F3 unification): compose-away
                # only when the SHARED retreat-authorization helper says
                # retreat is OK. That helper wraps: ESTABLISHED AND
                # fused-empty (reset-only backstop — see F3 in
                # ZoneManager.conditioning_retreat_ok). Callers of D9,
                # row-1, D7, and F4 row-10 all now consult the same
                # oracle so the preset-layer preserve is never defeated
                # at the setpoint layer.
                _rc_ready = bool(getattr(zone, "room_conditions", None))
                # HVAC-DEGRADED-ROOM-TRIPWIRE-1 FIX-UP item 2 (2026-09-26,
                # comment corrected round 3 item 5): if the zone is
                # transient-blocked (a sibling room is loading/reloading)
                # AND fused-empty, HOLD the setpoint write for this tick
                # — a raw baseline/freeze-floor DPM write while a sibling
                # room is reloading would strand the zone at the
                # `target_preset` baseline the whole cycle. This is a
                # setpoint-layer hold; the `else` branch below (~compose-
                # away when established+empty) never runs on this tick.
                try:
                    _fused_empty_dpm = not bool(
                        getattr(zone, "any_room_hvac_occupied", False)
                    )
                except Exception:  # noqa: BLE001
                    _fused_empty_dpm = False
                _is_tb = getattr(
                    self._zone_manager, "is_zone_transient_blocked", None,
                )
                try:
                    _transient_blocked_dpm = bool(_is_tb(zone_id)) if callable(_is_tb) else False
                except Exception:  # noqa: BLE001
                    _transient_blocked_dpm = False
                if _transient_blocked_dpm and _fused_empty_dpm:
                    _LOGGER.debug(
                        "HVAC D9 hold: zone %s transient-blocked + fused-empty — "
                        "skipping compose-away tick",
                        zone_id,
                    )
                    continue
                _compose_away = _rc_ready and self._zone_conditioning_retreat_ok(zone)
                if _compose_away:
                    zone_target_preset = "away"
                    try:
                        self._dpm_composed_away_zones = (
                            getattr(self, "_dpm_composed_away_zones", 0) + 1
                        )
                    except Exception:  # noqa: BLE001
                        pass
                else:
                    zone_target_preset = target_preset

                zone_overrides = all_overrides.get(zone_id, [])

                # Get baseline from preset manager (compose-away swaps to
                # the `away` baseline for empty established zones).
                baseline = self._preset_manager.get_seasonal_setpoints(zone_target_preset)
                if baseline is None:
                    continue
                baseline_cool, _baseline_heat = baseline

                # Determine effective baseline (cool_low=baseline_cool - MIN_DEADBAND, cool_high=baseline_cool)
                # seasonal setpoints return (cool_setpoint, heat_setpoint) — cool is the high
                baseline_low = baseline_cool - 7.0  # standard 7°F spread from SEASONAL_DEFAULTS
                baseline_high = baseline_cool

                # Resolve override for this zone + preset. Under the D9
                # compose-away branch, resolve against the zone-scoped
                # target ("away") so operator overrides on `away` apply
                # if present.
                active = engine.get_active_overrides(
                    zone_id, zone_target_preset, self._house_state, master_enabled, zone_overrides
                )
                resolved = engine.resolve_range(baseline_low, baseline_high, active)

                # feature/freeze-floor: the setpoint chokepoint applies the
                # freeze floor + deadband invariant. We compute the
                # post-chokepoint pair here for the idempotent throttle so the
                # guard compares the actually-emitted values; the chokepoint
                # re-applies the same transform on the wire.
                emit_low, emit_high = apply_setpoint_guards(
                    resolved.cool_low, resolved.cool_high,
                    freeze_active=self._freeze_active,
                )

                # Throttle: skip if resolved range matches last emitted.
                # F2 fix-up round 4 (2026-09-17): BYPASS the throttle on
                # compose-away. Third-writer restores (S8 cancel-nudge,
                # S9 startup ramp-audit restore in hvac_override.py) emit
                # comfort setpoints without updating `_last_emitted_range`.
                # Without this bypass, the throttle sees a stale "away"
                # entry, skips the corrective emit, and the zone strands
                # at comfort setpoints for the rest of the night. Emitting
                # unconditionally on the compose-away branch is by-design:
                # the DPM is the CORRECTOR — its whole job on an
                # established empty zone is to overwrite any third-writer
                # restore back to `away` on the next tick.
                last = self._last_emitted_range.get(zone_id)
                resolved_pair = (emit_low, emit_high)
                if last == resolved_pair and not _compose_away:
                    continue

                # Suppress arrester so set_temperature isn't flagged as manual override
                if self._override_arrester:
                    self._override_arrester.suppress(zone.climate_entity, kind="temp")  # v5.36.2 H6: B1 completeness

                try:
                    # ARREST-COMFORT-1 D-CRIT-1 fix-up: gate this DPM apply
                    # emit on `comfort_delay_active` — S10_dpm_apply. The
                    # DPM apply loop was previously the UNGATED sibling of
                    # S3/S4/S5 and could stomp a comfort-qualified manual.
                    def _s10_gate(z=zone_id) -> bool:
                        if self._override_arrester is None:
                            return False
                        try:
                            return bool(
                                self._override_arrester.comfort_delay_active(z)
                            )
                        except Exception:  # noqa: BLE001
                            return False
                    _s10_written = await emit_set_temperature(
                        self.hass,
                        zone.climate_entity,
                        target_temp_low=resolved.cool_low,
                        target_temp_high=resolved.cool_high,
                        freeze_active=self._freeze_active,
                        blocking=False,
                        gate=_s10_gate,
                        site="S10_dpm_apply",
                        zone_id=zone_id,
                        reason="dpm_preset_apply",
                    )
                    if not _s10_written:
                        # Deferred by comfort-grace — do NOT record the
                        # resolved pair in the throttle map (next tick
                        # re-emits naturally when grace expires). Roll
                        # back the pre-emit suppress() stamp so a real
                        # manual within SUPPRESS_TTL_SECONDS isn't
                        # swallowed (mirrors A-MED-2 discipline).
                        if self._override_arrester:
                            self._override_arrester.unsuppress(zone.climate_entity)
                        continue
                    self._last_emitted_range[zone_id] = resolved_pair
                    _LOGGER.info(
                        "HVAC: set_temperature %s low=%.1f high=%.1f "
                        "(override_sources=%s, house=%s)",
                        zone.zone_name,
                        emit_low, emit_high,
                        list(resolved.sources.values()),
                        self._house_state,
                    )
                except Exception as exc:
                    _LOGGER.error(
                        "HVAC: failed set_temperature on %s: %s",
                        zone.climate_entity, exc,
                    )
                    if self._override_arrester:
                        self._override_arrester.unsuppress(zone.climate_entity)

        except Exception:
            _LOGGER.warning("HVAC: _async_apply_preset_overrides failed", exc_info=True)

    @callback
    def _handle_house_state_changed(self, payload: Any) -> None:
        """Handle house state change signal.

        Triggers an immediate decision cycle so presets change promptly.
        """
        if isinstance(payload, dict):
            new_state = payload.get("new_state", "")
        elif hasattr(payload, "new_state"):
            new_state = payload.new_state
        else:
            new_state = str(payload)

        old_state = self._house_state
        if new_state == old_state:
            return

        self._house_state = new_state

        _LOGGER.info(
            "HVAC: House state changed %s -> %s",
            old_state, new_state,
        )

        # Arrester Operator-Immunity: sunset immune holds + Comfort
        # Override on durable-state transitions. Runs BEFORE the decision
        # cycle so any resumed governance shows up in the same tick.
        try:
            self._override_arrester.sunset_immune_holds(
                reason="durable_state", house_state=new_state,
            )
            # F8: notify via the arrester's on_sunset_notify callback
            # (single dispatch site, engagement-id dedup).
            self._override_arrester.sunset_temp_arrester_override(
                reason="durable_state", house_state=new_state,
            )
        except Exception as e:  # noqa: BLE001 — never crash signal handler
            _LOGGER.warning(
                "Arrester sunset processing failed on house-state change: %s",
                e,
            )

        # Trigger immediate decision cycle
        task = self.hass.async_create_task(
            self._async_decision_cycle(trigger="house_state")
        )
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _drain_hvac_degraded_room_events(self) -> None:
        """Emit NM notes for rooms newly classified EXCLUDED this pass.

        HVAC-DEGRADED-ROOM-TRIPWIRE-1 REV-2 D3/F9 (2026-09-26). The sync
        `is_zone_hvac_established` gate MUST NEVER dispatch NM (no
        `create_task` from a sync tick path — untracked background task
        class). The ZoneManager queues (room_name, reason) events
        inside `_classify_all_rooms` and this async coordinator method
        drains them right after `update_room_conditions` returns.
        Per-boot debounce lives inside ZoneManager
        (`_excluded_ever_notified`); each room fires at most one NM per
        HVACCoordinator lifetime.
        """
        try:
            events = self._zone_manager.drain_degraded_events()
        except Exception:  # noqa: BLE001
            return
        if not events:
            return
        try:
            from ..const import DOMAIN
            nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
            if nm is None:
                return
            from .base import Severity
            for room_name, reason in events:
                # FIX-UP item 4: NM dedup key is
                # `coordinator_id:title:location` (notification_manager
                # .py:3792). Pass `location=room_name` so two rooms
                # excluded in the same pass emit two distinct notes;
                # include the zone name(s) in the message body so the
                # operator sees which zone(s) lost this room.
                zone_names: list[str] = []
                try:
                    for _z in self._zone_manager.zones.values():
                        if room_name in (getattr(_z, "rooms", []) or []):
                            zone_names.append(_z.zone_name)
                except Exception:  # noqa: BLE001
                    zone_names = []
                _zn = ", ".join(zone_names) if zone_names else "(no HVAC zone)"
                try:
                    await nm.async_notify(
                        coordinator_id="hvac",
                        severity=Severity.MEDIUM,
                        location=room_name,
                        title="HVAC room degraded",
                        message=(
                            f"HVAC live-room establishment: room "
                            f"'{room_name}' (zone {_zn}) classified "
                            f"EXCLUDED (reason={reason}). Its zone's "
                            f"establishment is now computed over the "
                            f"remaining live rooms; a zone consisting "
                            f"only of excluded rooms will never retreat."
                        ),
                        hazard_type="hvac_degraded_room",
                    )
                except Exception:  # noqa: BLE001
                    _LOGGER.debug(
                        "HVAC degraded-room NM emit failed for %s",
                        room_name, exc_info=True,
                    )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "HVAC degraded-room drain failed", exc_info=True,
            )

    async def _notify_temp_arrester_override_ended(self, reason: str) -> None:
        """LOW NM note when Temp Arrester Override auto-sunsets.

        ``reason`` is threaded through unmodified from the sunset caller
        (e.g. ``sleep_transition``, ``max_age``) — LOW-A4: no more
        hard-coded reason strings; the arrester tells us why.
        """
        try:
            from ..const import DOMAIN
            nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
            if nm is None:
                return
            from .base import Severity
            await nm.async_notify(
                coordinator_id="hvac",
                severity=Severity.LOW,
                title="Temp Arrester Override ended (auto)",
                message=(
                    f"Temp Arrester Override auto-released "
                    f"(reason={reason}); arrester governance resumed "
                    f"house-wide."
                ),
                hazard_type="hvac_temp_arrester_override",
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("Temp Arrester Override NM note failed: %s", e)

    async def _notify_temp_arrester_override_expiring(
        self, remaining_minutes: int,
    ) -> None:
        """LOW NM note: Temp Arrester Override auto-release approaching.

        OVERRIDE-NOTIFY-1 (2026-08-08): fires ~ARRESTER_OVERRIDE_EXPIRY_
        WARN_S seconds before COMFORT_OVERRIDE_MAX_S so the operator has
        time to re-engage.
        """
        try:
            from ..const import DOMAIN
            nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
            if nm is None:
                return
            from .base import Severity
            await nm.async_notify(
                coordinator_id="hvac",
                severity=Severity.LOW,
                title="Temp Arrester Override expiring soon",
                message=(
                    f"Temp Arrester Override will auto-release in "
                    f"~{remaining_minutes} minute(s); re-engage if still "
                    f"needed."
                ),
                hazard_type="hvac_temp_arrester_override",
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug(
                "Temp Arrester Override expiry-warn NM note failed: %s", e,
            )

    async def _notify_temp_arrester_override_deferred(
        self, remaining_minutes: int,
    ) -> None:
        """LOW NM note: an invalidating state transition deferred the sunset.

        OVERRIDE-NOTIFY-1 (2026-08-08): the MIN_LIFE grace held the
        sunset for the remaining grace window; the override will end at
        the end of that window (~N minutes from now).
        """
        try:
            from ..const import DOMAIN
            nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
            if nm is None:
                return
            from .base import Severity
            await nm.async_notify(
                coordinator_id="hvac",
                severity=Severity.LOW,
                title="Temp Arrester Override ending soon (context changed)",
                message=(
                    f"House state changed while Temp Arrester Override was "
                    f"active; override will end in ~{remaining_minutes} "
                    f"minute(s) once the MIN_LIFE grace elapses."
                ),
                hazard_type="hvac_temp_arrester_override",
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug(
                "Temp Arrester Override defer NM note failed: %s", e,
            )

    # ==================================================================
    # HVAC fast occupancy response (v5.103.20) — D2 event-driven zone runs
    # Plan: docs/planning/PLANNING_hvac_fast_occupancy_response.md REV 3 §5.
    # Invariants: INV-1 (re-arm = periodic outcome within SLA), INV-3 (exit =
    # periodic outcome at release + grace, once per episode), INV-4 (zone
    # scope: climate writes only for Z via S1; other actuation = Z's vacancy
    # sweep; accepted house-wide side effects = display refresh of
    # zone_presence_state + `_expire_pre_arrival_zones`).
    # ==================================================================
    @property
    def fast_room_response_enabled(self) -> bool:
        """Kill switch (`31 · Fast Room Response`). OFF = tick-only timing."""
        return self._fast_path_enabled

    @fast_room_response_enabled.setter
    def fast_room_response_enabled(self, value: bool) -> None:
        value = bool(value)
        if value == self._fast_path_enabled:
            return
        self._fast_path_enabled = value
        if not value:
            # OFF: cancel every exit timer; listeners stay attached but
            # `_on_room_refresh` short-circuits on the gate.
            for _zid in list(self._fast_path_exit_unsubs):
                self._cancel_exit_timer(_zid)
            _LOGGER.info("HVAC fast room response OFF — tick-only timing")
        else:
            _LOGGER.info("HVAC fast room response ON — exit timers re-armed")
            self.reschedule_exit_timers()

    # ---- listener lifecycle (§5.4) -------------------------------------
    def _setup_fast_path_listeners(self) -> None:
        """Subscribe to SIGNAL_ROOM_ENTRY_LIFECYCLE FIRST, then enumerate the
        rooms already loaded. Attach is idempotent (release-then-attach per
        entry_id), so a room that loads between the two steps is attached
        exactly once."""
        from ..const import CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM  # noqa: PLC0415
        if self._fast_path_lifecycle_unsub is None:
            self._fast_path_lifecycle_unsub = async_dispatcher_connect(
                self.hass, SIGNAL_ROOM_ENTRY_LIFECYCLE, self._on_room_lifecycle,
            )
        try:
            entries = list(self.hass.config_entries.async_entries(DOMAIN))
        except Exception:  # noqa: BLE001
            entries = []
        for entry in entries:
            try:
                if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                    continue
            except Exception:  # noqa: BLE001
                continue
            self._attach_room_listener(entry.entry_id)

    @callback
    def _on_room_lifecycle(self, entry_id: Any, room_name: Any = None, phase: Any = None) -> None:
        """`loaded` attaches, `unloaded` releases, `options_updated`
        re-attaches (payload: entry_id, room_name, phase — __init__.py)."""
        if self._tearing_down:
            return
        if phase == "unloaded":
            self._release_room_listener(entry_id)
        elif phase in ("loaded", "options_updated"):
            self._attach_room_listener(entry_id)

    def _attach_room_listener(self, entry_id: str) -> None:
        self._release_room_listener(entry_id)
        if self._tearing_down:
            return
        coordinator = self.hass.data.get(DOMAIN, {}).get(entry_id)
        add = getattr(coordinator, "async_add_listener", None)
        if not callable(add):
            return
        try:
            unsub = add(partial(self._on_room_refresh, entry_id))
        except Exception:  # noqa: BLE001
            _LOGGER.debug("fast path: listener attach failed for %s", entry_id, exc_info=True)
            return
        if callable(unsub):
            self._fast_path_room_unsubs[entry_id] = unsub

    def _release_room_listener(self, entry_id: str) -> None:
        unsub = self._fast_path_room_unsubs.pop(entry_id, None)
        if callable(unsub):
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        # D5: a room that unloads drops its arm re-check (plan §5b.4).
        self._cancel_arm_recheck(entry_id)

    def _teardown_fast_path(self) -> None:
        """Sync; called BEFORE the first await of `async_teardown`."""
        for _eid in list(self._fast_path_room_unsubs):
            self._release_room_listener(_eid)
        if self._fast_path_lifecycle_unsub is not None:
            try:
                self._fast_path_lifecycle_unsub()
            except Exception:  # noqa: BLE001
                pass
            self._fast_path_lifecycle_unsub = None
        for _zid in list(self._fast_path_exit_unsubs):
            self._cancel_exit_timer(_zid)
        for _eid in list(self._fast_path_arm_unsubs):
            self._cancel_arm_recheck(_eid)
        self._fast_path_queued.clear()

    # ---- D5: away edge, pending-hold exposure, arm re-check (§5b) --------
    def _zone_away_edge(self, zone_id: str) -> bool:
        """Plan §2 "Away edge": Z's last APPLIED S1 write was `away`
        (`_zone_last_s1_write`, else the strategy's `last_sent`) AND Z is
        not being pre-arrival conditioned. Unknown -> False (fail open: at
        most one unfiltered transit per zone per restart)."""
        zone = self._zone_manager.zones.get(zone_id)
        if zone is None:
            return False
        if zone_id in self._pre_arrival_zones:
            return False
        return self._zone_last_write_is_away(zone)

    def _pending_hold_cap_s(self, zone: Any) -> float:
        """fix-up 2 (D-L2): `max(HVAC_PENDING_HOLD_CAP_S, W + J)` with J the
        largest join window among the zone's pending rooms — one episode can
        always run its course; only chains are capped."""
        W = self._entry_dwell_s()
        J = 0.0
        for _r in (getattr(zone, "hvac_pending_arm_rooms", []) or []):
            try:
                J = max(J, float(self._zone_manager.d5_join_window_s(_r, W)))
            except Exception:  # noqa: BLE001
                continue
        return max(float(HVAC_PENDING_HOLD_CAP_S), W + J)

    def _close_unseen_pending_spells(self, seen: set[str], zone_filter: Any) -> None:
        """fix-up 2 (D-L1): close the pending spell of every in-scope zone
        whose S1 block did not run this tick (arriving, no target preset,
        zone intelligence off, observation mode, egress pause)."""
        # Bare fixtures (object.__new__ coordinators in older tests) may lack
        # the latch sets — treat them as empty rather than fault the tick.
        _logged = getattr(self, "_pending_hold_logged", None)
        _cap_logged = getattr(self, "_pending_hold_cap_logged", None)
        for _zid, _z in list(self._zone_manager.zones.items()):
            if zone_filter is not None and _zid not in zone_filter:
                continue
            if _zid in seen:
                continue
            if getattr(_z, "pending_hold_since", None) is not None:
                self._note_pending_hold(_z, False)
            if _logged is not None:
                _logged.discard(_zid)
            if _cap_logged is not None:
                _cap_logged.discard(_zid)

    def _log_pending_hold_capped(
        self, zone: Any, zone_id: str, activity_logger: Any, now_utc: datetime,
        since: datetime, cap_s: float = float(HVAC_PENDING_HOLD_CAP_S),
    ) -> None:
        """One `pending_hold_capped` ledger row per spell (ruling 1)."""
        if zone_id in self._pending_hold_cap_logged:
            return
        self._pending_hold_cap_logged.add(zone_id)
        held_s = int((now_utc - since).total_seconds())
        _LOGGER.info(
            "HVAC pending hold CAPPED on %s after %d s (cap %d s) — the "
            "vacancy away may proceed", getattr(zone, "zone_name", zone_id),
            held_s, int(cap_s),
        )
        if activity_logger is None:
            return
        try:
            self.hass.async_create_task(activity_logger.log(
                coordinator="hvac",
                action="pending_hold_capped",
                description=(
                    f"{getattr(zone, 'zone_name', zone_id)} stopped holding for a "
                    f"room that never settled ({held_s} s, cap {int(cap_s)} s)"
                ),
                zone=zone_id,
                importance="notable",
                entity_id=getattr(zone, "climate_entity", None),
                details={
                    "held_s": held_s,
                    "cap_s": int(cap_s),
                    "pending_rooms": list(getattr(zone, "hvac_pending_arm_rooms", []) or []),
                    "house_state": self._house_state,
                },
            ))
        except Exception:  # noqa: BLE001
            _LOGGER.debug("pending_hold_capped ledger row failed", exc_info=True)

    def _note_pending_hold(self, zone: Any, held: bool) -> None:
        """Accumulate `pending_hold_s_today` per hold spell (plan §4.2 6)."""
        try:
            now_utc = dt_util.utcnow()
            since = getattr(zone, "pending_hold_since", None)
            if held:
                if since is None:
                    zone.pending_hold_since = now_utc
            elif since is not None:
                zone.pending_hold_s_today = float(
                    getattr(zone, "pending_hold_s_today", 0.0) or 0.0
                ) + max(0.0, (now_utc - since).total_seconds())
                zone.pending_hold_since = None
        except Exception:  # noqa: BLE001
            pass

    def _return_window_s(self) -> float:
        """Knob 52 "Return Window" in seconds (0 = exemption off)."""
        try:
            return max(0.0, float(getattr(self, "_return_window_minutes", DEFAULT_HVAC_RETURN_WINDOW_MINUTES) or 0) * 60.0)
        except (TypeError, ValueError):
            return float(DEFAULT_HVAC_RETURN_WINDOW_MINUTES) * 60.0

    def _entry_dwell_s(self) -> float:
        """Knob 47 in seconds (W). Tolerates a partially-initialised
        coordinator (bare fixtures) — missing/None/malformed -> 0 (filter off)."""
        try:
            return float(getattr(self, "_zone_entry_dwell", 0) or 0) * 60.0
        except (TypeError, ValueError):
            return 0.0

    def _sync_arm_rechecks(self, zone: Any) -> None:
        """After a producer pass for `zone`: cancel the arm re-check of every
        room that is no longer pending (lapsed or armed) — plan §5b.4."""
        pending = set(getattr(zone, "hvac_pending_arm_rooms", []) or [])
        for room_name in (getattr(zone, "rooms", []) or []):
            if room_name in pending:
                continue
            eid = self._entry_id_for_room(room_name)
            if eid is not None:
                self._cancel_arm_recheck(eid)

    def _entry_id_for_room(self, room_name: str) -> str | None:
        meta = getattr(self._zone_manager, "_room_meta_last_pass", {}).get(room_name) or {}
        return meta.get("entry_id")

    def _schedule_arm_recheck(
        self, entry_id: str, room_name: str, episode_start: datetime,
    ) -> None:
        """Arm re-check at `episode_start + W + HVAC_ARM_RECHECK_SLACK_S`
        (plan §5b.4). Replaced only when the due time changes."""
        from .hvac_const import HVAC_ARM_RECHECK_SLACK_S  # noqa: PLC0415
        due = episode_start + timedelta(
            seconds=self._entry_dwell_s() + HVAC_ARM_RECHECK_SLACK_S,
        )
        if (
            entry_id in self._fast_path_arm_unsubs
            and self._fast_path_arm_due.get(entry_id) == due
        ):
            return
        self._cancel_arm_recheck(entry_id)
        delay = max(0.0, (due - dt_util.utcnow()).total_seconds())
        self._fast_path_arm_unsubs[entry_id] = async_call_later(
            self.hass, delay, partial(self._on_arm_recheck, entry_id, room_name),
        )
        self._fast_path_arm_due[entry_id] = due

    def _cancel_arm_recheck(self, entry_id: str) -> None:
        unsub = self._fast_path_arm_unsubs.pop(entry_id, None)
        self._fast_path_arm_due.pop(entry_id, None)
        if callable(unsub):
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass

    @callback
    def _on_arm_recheck(self, entry_id: str, room_name: str, _now: Any = None) -> None:
        """Arm re-check callback (plan §5b.4): persisted -> re-enter
        `_on_room_refresh` at step 5 (the gates + the zone-cold gate decide);
        lapsed -> drop; otherwise nothing. NEVER queues a run directly."""
        self._fast_path_arm_unsubs.pop(entry_id, None)
        self._fast_path_arm_due.pop(entry_id, None)
        try:
            if self._tearing_down:
                return
            zone_id, zone = self._zone_for_room(room_name)
            if zone_id is None:
                return
            d5 = self._zone_manager.d5_room_probe(
                room_name, dt_util.utcnow(), self._entry_dwell_s(),
                self._zone_away_edge(zone_id),
            )
            if d5 is None or not d5.get("cold"):
                # D5 no longer applies (house left the evidence states, the
                # edge cleared, the room is exempt or the filter is off):
                # re-enter at step 5 and let the gates decide.
                self._on_room_refresh(entry_id, from_step=5)
                return
            if d5.get("live") and d5.get("persisted"):
                self._on_room_refresh(entry_id, from_step=5)
            # lapsed (not live) -> dropped; pending -> nothing (the next
            # refresh reschedules).
        except Exception:  # noqa: BLE001
            _LOGGER.debug("fast path: arm re-check failed for %s", room_name, exc_info=True)

    # ---- gates + helpers ------------------------------------------------
    def _fast_path_gates_open(self, zone_id: str, trigger: str) -> bool:
        """Every gate a fast run must pass — checked before AND after the
        lock wait (a kill-switch flip, teardown, zone deletion or trip while
        waiting must abort the run)."""
        if self._tearing_down or not self._enabled or not self._boot_settle_done:
            return False
        if (
            not self._fast_path_enabled
            or self._observation_mode
            or not self._zone_intelligence_enabled
        ):
            return False
        if zone_id not in self._zone_manager.zones:
            return False
        if self._fast_path_zone_tripped(zone_id):
            return False
        return True

    def _fast_path_zone_tripped(self, zone_id: str) -> bool:
        until = self._fp_tripped_until.get(zone_id)
        if until is None:
            return False
        if dt_util.utcnow() >= until:
            # Trip ended (local midnight): fresh hour for the zone (A-MED2).
            self._fp_tripped_until.pop(zone_id, None)
            self._fp_writes_bucket.pop(zone_id, None)
            self._fp_runs_bucket.pop(zone_id, None)
            return False
        return True

    def _local_midnight_after(self, now_utc: datetime) -> datetime:
        """UTC instant of the next LOCAL midnight (trip fallback end)."""
        local = dt_util.as_local(now_utc)
        start = dt_util.start_of_local_day(local) + timedelta(days=1)
        return dt_util.as_utc(start)

    def _trip_fast_path_zone(self, zone_id: str, kind: str, count: int) -> None:
        """Tick-only fallback for `zone_id` until local midnight + ONE NM.
        `kind` ∈ {ceiling, runaway}."""
        now_utc = dt_util.utcnow()
        if self._fast_path_zone_tripped(zone_id):
            return
        self._fp_tripped_until[zone_id] = self._local_midnight_after(now_utc)
        # A-MED2: the breach that tripped is not carried into the next window.
        self._fp_writes_bucket.pop(zone_id, None)
        self._fp_runs_bucket.pop(zone_id, None)
        self._cancel_exit_timer(zone_id)
        zone = self._zone_manager.zones.get(zone_id)
        zone_name = getattr(zone, "zone_name", zone_id) if zone else zone_id
        _LOGGER.warning(
            "HVAC fast room response paused for %s (%s, %d in the last hour) "
            "until local midnight; the periodic tick still runs",
            zone_name, kind, count,
        )
        if kind == "ceiling":
            title = f"Fast room response paused for {zone_name}"
            message = (
                f"{zone_name} changed its heating and cooling setting {count} "
                "times in the last hour. Fast response is off for this zone "
                "until midnight. The regular 5-minute check still runs."
            )
            hazard = "hvac_fast_path_write_ceiling"
        else:
            title = f"Fast room response paused for {zone_name}"
            message = (
                f"{zone_name} ran more checks than expected in the last hour. "
                "Fast response is off for this zone until midnight. The "
                "regular 5-minute check still runs."
            )
            hazard = "hvac_fast_path_runaway"
        self._fast_path_nm(title, message, hazard, "MEDIUM")

    def _fast_path_nm(self, title: str, message: str, hazard_type: str, severity: str) -> None:
        """One NM via the notification manager (same path as
        `_note_s1_reclaim`). Never raises."""
        try:
            nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
            if nm is None:
                return
            from .base import Severity  # noqa: PLC0415
            sev = getattr(Severity, severity, Severity.LOW)
            self._track_task(self.hass.async_create_task(nm.async_notify(
                coordinator_id="hvac",
                severity=sev,
                title=title,
                message=message,
                hazard_type=hazard_type,
            )))
        except Exception:  # noqa: BLE001
            _LOGGER.debug("fast path NM failed", exc_info=True)

    @staticmethod
    def _bucket_add_and_count(bucket: deque, now_utc: datetime, window_s: int = 3600) -> int:
        bucket.append(now_utc)
        cutoff = now_utc - timedelta(seconds=window_s)
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        return len(bucket)

    def _zone_last_write_is_away(self, zone: Any) -> bool:
        """Limiter-exemption / exit-timer key (plan §5.4, REV 3): the S1 write
        stamp FIRST; on a miss, the strategy's `last_sent`; NEVER
        `zone.preset_mode` (the §9.7 status feed can misreport it)."""
        rec = self._zone_last_s1_write.get(getattr(zone, "zone_id", ""))
        if rec is not None:
            return rec[0] == "away"
        try:
            from .hvac_strategy import strategy_for  # noqa: PLC0415
            sent = strategy_for(self.hass, zone.climate_entity).last_sent(
                zone.climate_entity, "set_preset_mode",
            )
        except Exception:  # noqa: BLE001
            sent = None
        return sent == "away"

    def _room_name_and_type(self, coordinator: Any) -> tuple[str | None, str | None]:
        """Resolve (room_name, room_type) for a room coordinator, from the
        producer's last-pass meta first, else the entry config."""
        from ..const import CONF_ROOM_NAME, CONF_ROOM_TYPE, ROOM_TYPE_GENERIC  # noqa: PLC0415
        entry = getattr(coordinator, "entry", None)
        data = getattr(entry, "data", None) or {}
        room_name = data.get(CONF_ROOM_NAME) or data.get("room_name")
        if not room_name:
            return None, None
        meta = getattr(self._zone_manager, "_room_meta_last_pass", {}).get(room_name)
        if meta and meta.get("room_type"):
            return room_name, str(meta["room_type"])
        options = getattr(entry, "options", None) or {}
        merged = {**data, **options}
        return room_name, str(merged.get(CONF_ROOM_TYPE) or ROOM_TYPE_GENERIC)

    def _zone_for_room(self, room_name: str) -> tuple[str | None, Any]:
        for zone_id, zone in self._zone_manager.zones.items():
            if room_name in (getattr(zone, "rooms", []) or []):
                return zone_id, zone
        return None, None

    # ---- entry trigger (§5.4) -------------------------------------------
    @callback
    def _on_room_refresh(self, entry_id: str, *, from_step: int = 1) -> None:
        """Room-coordinator refresh listener (plan §5.4). Short-circuits in
        order: 1 gates -> 2 hallway skip / live zone lookup -> 3 evidence
        advance (None rule) -> 4 D5 episode update (cold + not persisted:
        schedule the arm re-check if the zone is cold, then return) ->
        5 zone-cold gate + tripped -> 6 60 s limiter (exempt iff the last
        write was away) -> 7 dedup -> 8 queue `fast_entry`.
        The arm re-check re-enters at `from_step=5` (steps 1-2 still run)."""
        try:
            if self._tearing_down or not self._enabled or not self._boot_settle_done:
                return
            if (
                not self._fast_path_enabled
                or self._observation_mode
                or not self._zone_intelligence_enabled
            ):
                return
            coordinator = self.hass.data.get(DOMAIN, {}).get(entry_id)
            if coordinator is None:
                return
            from ..const import ROOM_TYPE_HALLWAY  # noqa: PLC0415
            room_name, room_type = self._room_name_and_type(coordinator)
            if not room_name or room_type == ROOM_TYPE_HALLWAY:
                return
            zone_id, zone = self._zone_for_room(room_name)
            if zone_id is None:
                return
            now_utc = dt_util.utcnow()
            exempt_reason: str | None = None
            if from_step <= 3:
                # 3. Evidence advance — None never counts and never overwrites.
                _get = getattr(coordinator, "get_last_hvac_evidence_time", None)
                _raw = _get() if callable(_get) else None
                ev = _raw if isinstance(_raw, datetime) else None
                last = self._fp_last_ev.get(room_name)
                if ev is None or (last is not None and ev <= last):
                    # fix-up 2 (D-L4): no evidence advance — but a
                    # SUPPRESSED-source falling edge (fan-demoted, fan-recheck
                    # release) can still end the room's evidence without a
                    # stamp. In a warm zone (re)arm the exit timer from live
                    # evidence, exactly as the B-L1 edge does. No run.
                    if bool(getattr(zone, "any_room_hvac_occupied", False)):
                        self._schedule_exit_timer(zone_id)
                    return
                self._fp_last_ev[room_name] = ev
            if from_step <= 4:
                # 4. D5 episode update (evidence states, filter on).
                W = self._entry_dwell_s()
                if W > 0 and self._house_state in HVAC_EVIDENCE_RULE_STATES:
                    d5 = self._zone_manager.d5_room_probe(
                        room_name, now_utc, W, self._zone_away_edge(zone_id),
                    )
                    if d5 and d5.get("cold"):
                        if d5.get("live") and not d5.get("persisted"):
                            if not bool(getattr(zone, "any_room_hvac_occupied", False)):
                                self._schedule_arm_recheck(
                                    entry_id, room_name, d5["episode_start"],
                                )
                            return
                        if not d5.get("live"):
                            self._cancel_arm_recheck(entry_id)
                            return
                        # persisted -> proceed to step 5
                        self._cancel_arm_recheck(entry_id)
            try:
                exempt_reason = getattr(self._zone_manager, "_hvac_exempt_reason", {}).get(room_name)
            except Exception:  # noqa: BLE001
                exempt_reason = None
            # 5. Zone-cold gate (stored fused value from the last pass) + trip.
            if bool(getattr(zone, "any_room_hvac_occupied", False)):
                # fix-up 1 (B-L1): a WARM zone's evidence advance (typically
                # the falling edge that starts a room's release clock)
                # (re)arms the zone's exit timer from LIVE evidence — the
                # timer a `due is None` fire dropped, or one never armed
                # because every pass so far saw the room active. No run.
                self._schedule_exit_timer(zone_id)
                return
            if self._fast_path_zone_tripped(zone_id):
                self._fast_limited_today.increment()
                return
            # 6. Per-zone entry limiter, exempt when the last write was away.
            if not self._zone_last_write_is_away(zone):
                last_run = self._fp_last_entry_run.get(zone_id)
                if (
                    last_run is not None
                    and (now_utc - last_run).total_seconds() < HVAC_FAST_PATH_MIN_INTERVAL_S
                ):
                    self._fast_limited_today.increment()
                    return
            # 7. Dedup.
            if zone_id in self._fast_path_queued:
                return
            # 8. Queue.
            self._fast_path_queued.add(zone_id)
            self._track_task(self.hass.async_create_task(
                self._async_zone_fast_run(
                    zone_id, "fast_entry", edge_ts=now_utc, exempt_reason=exempt_reason,
                )
            ))
        except Exception:  # noqa: BLE001 — a listener must never raise into HA
            _LOGGER.debug("fast path: room refresh handler failed", exc_info=True)

    # ---- the fast run (§5.1) --------------------------------------------
    async def _async_zone_fast_run(
        self, zone_id: str, trigger: str, edge_ts: datetime | None = None,
        exempt_reason: str | None = None,
    ) -> None:
        wrote = False
        fused_changed = False
        try:
            if not self._fast_path_gates_open(zone_id, trigger):
                return
            async with self._decision_cycle_lock:
                if not self._fast_path_gates_open(zone_id, trigger):
                    return
                self._fast_path_running = True  # set only while holding the lock
                try:
                    now_utc = dt_util.utcnow()
                    # Runaway guard — counts RUNS (write or not).
                    runs = self._bucket_add_and_count(
                        self._fp_runs_bucket.setdefault(zone_id, deque()), now_utc,
                    )
                    if runs > HVAC_FAST_PATH_MAX_RUNS_PER_ZONE_PER_HOUR:
                        self._trip_fast_path_zone(zone_id, "runaway", runs)
                        return
                    zm = self._zone_manager
                    zone = zm.zones.get(zone_id)
                    if zone is None:
                        return
                    if trigger == "fast_entry":
                        self._fp_last_entry_run[zone_id] = now_utc
                        self._fast_entry_runs_today.increment()
                    else:
                        self._fast_exit_runs_today.increment()
                    fused_before = bool(getattr(zone, "any_room_hvac_occupied", False))
                    zm.update_zone_climate_state(zone_id)
                    zm.update_room_conditions(
                        house_state=self._house_state, zone_ids={zone_id},
                        entry_dwell_s=self._entry_dwell_s(),
                        away_edge_fn=self._zone_away_edge,
                        return_window_s=self._return_window_s(),
                    )
                    self._sync_arm_rechecks(zone)
                    _pa_reasons_fp: dict[str, str] = {}
                    if self._zone_intelligence_enabled:
                        # M10: a fast run expires ONLY its own zone.
                        _pa_reasons_fp = self._expire_pre_arrival_zones(
                            dt_util.utcnow(), zone_filter={zone_id},
                        )
                    # HVAC W1/W2 finish D3 (M10): end THIS zone's pre-arrival
                    # borrow before its S1; other zones wait for the next full
                    # pass, which ends them before its S1.
                    await self._async_end_pre_arrival_borrows(
                        _pa_reasons_fp, zone_filter={zone_id},
                    )
                    if not self._observation_mode:
                        wrote = await self._apply_house_state_presets(
                            zone_filter={zone_id}, trigger=trigger, edge_ts=edge_ts,
                            exempt_reason=exempt_reason,
                        )
                    if self._zone_intelligence_enabled:
                        self._compute_zone_presence_states(dt_util.utcnow())
                    _fused_after = bool(getattr(zone, "any_room_hvac_occupied", False))
                    fused_changed = fused_before != _fused_after
                    # fix-up 1 (B-L4): a quick return is counted only when
                    # the fast entry actually RE-ARMED the zone.
                    if trigger == "fast_entry" and _fused_after and not fused_before:
                        self._note_quick_return(
                            zone_id, zone, now_utc, exempt_reason=exempt_reason,
                        )
                    self._schedule_exit_timer(zone_id)
                    if wrote or fused_changed:
                        async_dispatcher_send(self.hass, SIGNAL_HVAC_ENTITIES_UPDATE)
                finally:
                    self._fast_path_running = False  # cleared inside the lock
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _LOGGER.warning("HVAC fast run (%s) failed for %s", trigger, zone_id, exc_info=True)
        finally:
            self._fast_path_queued.discard(zone_id)  # every exit path

    def _note_fast_write(self, zone_id: str, ts_utc: datetime, edge_ts: datetime | None) -> None:
        """Called from S1 when a non-periodic run applied a write: counters,
        SLA consumer, write ceiling."""
        self._fast_writes_today.increment()
        if edge_ts is not None:
            try:
                self._last_fast_edge_to_write_s = round(
                    (ts_utc - edge_ts).total_seconds(), 1,
                )
            except Exception:  # noqa: BLE001
                self._last_fast_edge_to_write_s = None
        writes = self._bucket_add_and_count(
            self._fp_writes_bucket.setdefault(zone_id, deque()), ts_utc,
        )
        if writes > HVAC_FAST_PATH_MAX_WRITES_PER_ZONE_PER_HOUR:
            self._trip_fast_path_zone(zone_id, "ceiling", writes)

    # ---- quick-return trip-wire (§5.7) ----------------------------------
    def _quick_returns_today_view(self) -> dict[str, int]:
        today = dt_util.now().date().isoformat()
        if self._fp_quick_return_date != today:
            self._fp_quick_return_date = today
            self._fp_quick_returns_today = {}
            self._fp_same_room_returns_today = {}
            self._fp_other_room_returns_today = {}
            self._fp_skip_entry_wait_returns_today = {}
            self._fp_quick_return_latched = set()
        return self._fp_quick_returns_today

    def _note_quick_return(
        self, zone_id: str, zone: Any, now_utc: datetime, *,
        exempt_reason: str | None = None,
    ) -> None:
        """Quick-return alarm (plan §5.7, O1). Event: the FIRST `fast_entry`
        re-arm in Z (exempt or not) after an APPLIED `vacant_past_grace` away
        (`_zone_vacancy_away_at`), within HVAC_QUICK_RETURN_WINDOW_S of it —
        at most one per away (deduped on the away instant). Per-zone
        counters: `quick_returns_today` (= same-room + skip-entry-wait +
        other-room; fix-up 2 D-L3 splits them by `exempt_reason`). At
        HVAC_QUICK_RETURN_NM_PER_DAY per zone per local day: one LOW NM whose
        text reads the window from the constant."""
        away_at = self._zone_vacancy_away_at.get(zone_id)
        if away_at is None:
            return
        if not (0 <= (now_utc - away_at).total_seconds() < HVAC_QUICK_RETURN_WINDOW_S):
            return
        if self._zone_vacancy_away_counted.get(zone_id) == away_at:
            return  # this away already produced its one event
        self._zone_vacancy_away_counted[zone_id] = away_at
        counts = self._quick_returns_today_view()
        counts[zone_id] = counts.get(zone_id, 0) + 1
        if exempt_reason == "same_room_return":
            split = self._fp_same_room_returns_today
        elif exempt_reason == "skip_entry_wait":
            split = self._fp_skip_entry_wait_returns_today
        else:
            split = self._fp_other_room_returns_today
        split[zone_id] = split.get(zone_id, 0) + 1
        n = counts[zone_id]
        if n >= HVAC_QUICK_RETURN_NM_PER_DAY and zone_id not in self._fp_quick_return_latched:
            self._fp_quick_return_latched.add(zone_id)
            zone_name = getattr(zone, "zone_name", zone_id)
            window_min = int(HVAC_QUICK_RETURN_WINDOW_S // 60)
            self._fast_path_nm(
                # User-facing name "Early return alert" (operator 2026-09-28:
                # distinct from the "Return window" mechanism — 15-min alarm
                # vs 10-min mechanism). Internal names / attr keys unchanged.
                f"Early return alert: {zone_name}",
                (
                    f"Early return alert: {zone_name} switched to Away and someone was back within "
                    f"{window_min} minutes {n} times today. The empty-room hold "
                    "for a room in this zone may be too short."
                ),
                "hvac_quick_return_rate",
                "LOW",
            )

    # ---- exit timer (§5.6) ----------------------------------------------
    def _exit_grace_seconds(self) -> float:
        """The grace S1 uses NOW (hvac.py `_apply_house_state_presets`):
        constrained under coast/shed, else normal — read at call time."""
        energy_constrained = self._energy_constraint_mode in ("coast", "shed")
        minutes = (
            self._vacancy_grace_constrained if energy_constrained
            else self._vacancy_grace
        )
        return float(minutes) * 60.0

    def _exit_timer_preconditions(self, zone_id: str) -> bool:
        if self._tearing_down or not self._enabled:
            return False
        if (
            not self._fast_path_enabled
            or self._observation_mode
            or not self._zone_intelligence_enabled
        ):
            return False
        zone = self._zone_manager.zones.get(zone_id)
        if zone is None:
            return False
        if self._fast_path_zone_tripped(zone_id):
            return False
        if not self._house_state or (
            self._house_state not in HVAC_EVIDENCE_RULE_STATES
            and self._house_state not in HVAC_NIGHT_HOLD_STATES
        ):
            return False
        target = self._preset_manager.get_preset_for_house_state(self._house_state)
        if target not in ("home", "sleep"):
            return False
        try:
            if self._egress_manager.is_paused(zone_id):
                return False
        except Exception:  # noqa: BLE001
            pass
        try:
            if not self._zone_manager.is_zone_hvac_established(zone_id):
                return False
        except Exception:  # noqa: BLE001
            return False
        if self._zone_last_write_is_away(zone):
            return False
        return True

    def _exit_due(self, zone_id: str) -> tuple[datetime | None, datetime | None]:
        """(due, release) from LIVE evidence and the LIVE grace."""
        release = self._zone_manager.zone_release_at(zone_id)
        if release is None:
            return None, None
        due = release + timedelta(
            seconds=self._exit_grace_seconds() + HVAC_FAST_PATH_EXIT_SLACK_S,
        )
        return due, release

    def _cancel_exit_timer(self, zone_id: str) -> None:
        unsub = self._fast_path_exit_unsubs.pop(zone_id, None)
        self._fast_path_exit_due.pop(zone_id, None)
        if callable(unsub):
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass

    def _schedule_exit_timer(self, zone_id: str) -> None:
        """(Re)arm the zone's exit timer; cancel it when no timer is due."""
        try:
            if not self._exit_timer_preconditions(zone_id):
                self._cancel_exit_timer(zone_id)
                return
            due, release = self._exit_due(zone_id)
            if due is None or release is None:
                self._cancel_exit_timer(zone_id)
                return
            if self._fp_exit_fired.get(zone_id) == (zone_id, release):
                # One-shot per vacancy episode: this key already fired.
                self._cancel_exit_timer(zone_id)
                return
            if (
                zone_id in self._fast_path_exit_unsubs
                and self._fast_path_exit_due.get(zone_id) == due
            ):
                return  # unchanged
            self._cancel_exit_timer(zone_id)
            delay = max(0.0, (due - dt_util.utcnow()).total_seconds())
            self._fast_path_exit_unsubs[zone_id] = async_call_later(
                self.hass, delay, partial(self._on_exit_timer, zone_id),
            )
            self._fast_path_exit_due[zone_id] = due
        except Exception:  # noqa: BLE001
            _LOGGER.debug("fast path: exit timer schedule failed for %s", zone_id, exc_info=True)

    @callback
    def _on_exit_timer(self, zone_id: str, _now: Any = None) -> None:
        """Recompute from LIVE evidence + LIVE grace; not due -> lazy
        reschedule (no run, no counters); due -> record the one-shot key and
        queue a `fast_exit` run (never limited)."""
        self._fast_path_exit_unsubs.pop(zone_id, None)
        self._fast_path_exit_due.pop(zone_id, None)
        try:
            # Teardown / kill switch / zone gone / tripped / state / target /
            # egress pause / establishment / last-write-away: ONE gate,
            # checked FIRST (fix-up 1 D-M1) — `_exit_timer_preconditions`
            # (its first conjunct is `_tearing_down`).
            if not self._exit_timer_preconditions(zone_id):
                return
            now_utc = dt_util.utcnow()
            # D5 (plan §5.6, REV 7 L2): a pending room in Z -> reschedule to
            # that room's `ev + J + HVAC_FAST_PATH_EXIT_SLACK_S`; the key is
            # NOT consumed and nothing runs before the lapse is observable.
            zone = self._zone_manager.zones.get(zone_id)
            pending = list(getattr(zone, "hvac_pending_arm_rooms", []) or []) if zone else []
            if pending:
                W = self._entry_dwell_s()
                lapse_due: datetime | None = None
                for _r in pending:
                    _ev = self._zone_manager.room_last_evidence_live(_r)
                    if _ev is None:
                        continue
                    _due = _ev + timedelta(
                        seconds=self._zone_manager.d5_join_window_s(_r, W)
                        + HVAC_FAST_PATH_EXIT_SLACK_S,
                    )
                    if lapse_due is None or _due > lapse_due:
                        lapse_due = _due
                if lapse_due is None:
                    lapse_due = now_utc + timedelta(seconds=W + HVAC_FAST_PATH_EXIT_SLACK_S)
                if lapse_due <= now_utc:
                    lapse_due = now_utc + timedelta(seconds=HVAC_FAST_PATH_EXIT_SLACK_S)
                self._cancel_exit_timer(zone_id)
                delay = max(0.0, (lapse_due - now_utc).total_seconds())
                self._fast_path_exit_unsubs[zone_id] = async_call_later(
                    self.hass, delay, partial(self._on_exit_timer, zone_id),
                )
                self._fast_path_exit_due[zone_id] = lapse_due
                return
            due, release = self._exit_due(zone_id)
            if due is None or release is None:
                return
            if due > now_utc + timedelta(seconds=1):
                self._schedule_exit_timer(zone_id)
                return
            key = (zone_id, release)
            if self._fp_exit_fired.get(zone_id) == key:
                return
            self._fp_exit_fired[zone_id] = key
            if zone_id in self._fast_path_queued:
                return
            self._fast_path_queued.add(zone_id)
            self._track_task(self.hass.async_create_task(
                self._async_zone_fast_run(zone_id, "fast_exit")
            ))
        except Exception:  # noqa: BLE001
            _LOGGER.debug("fast path: exit timer callback failed for %s", zone_id, exc_info=True)

    def reschedule_exit_timers(self) -> None:
        """Public hook (number.py grace setters, energy-constraint change,
        kill switch ON): recompute every zone's exit due time."""
        if self._tearing_down:
            return
        for _zid in list(self._zone_manager.zones.keys()):
            self._schedule_exit_timer(_zid)

    @callback
    def _handle_energy_constraint(self, constraint: EnergyConstraint) -> None:
        """Handle energy constraint signal from Energy Coordinator."""
        old_mode = self._energy_constraint_mode

        self._energy_constraint = constraint
        self._energy_constraint_mode = constraint.mode
        self._energy_offset = constraint.setpoint_offset
        # HVAC-DEMAND-KNOBS-AND-OBS-GAPS-1 D7 (v5.103.8): stamp the
        # transition-into-mode timestamp WHENEVER the mode changes
        # AND on first observation (from initial `None` -> anything).
        # Restart-safety lives on the mode sensor (RestoreEntity
        # resume-if-same / reset-if-different) — this coordinator
        # field is set for the live current-tick derivation.
        if (
            old_mode != constraint.mode
            or self._energy_constraint_mode_since is None
        ):
            self._energy_constraint_mode_since = dt_util.utcnow()

        if old_mode != constraint.mode:
            # v5.103.20 (plan §5.6): the grace S1 uses depends on coast/shed,
            # so a mode change moves every zone's exit due time.
            self.reschedule_exit_timers()
            _LOGGER.info(
                "HVAC: Energy constraint changed %s -> %s (offset=%.1f, fan_assist=%s)",
                old_mode,
                constraint.mode,
                constraint.setpoint_offset,
                constraint.fan_assist,
            )
            # v3.17.0 D5: Reset duty cycle counters only when entering constrained
            # mode from normal (not on coast↔shed bounces, which would defeat enforcement)
            _MODE_RANK = {"normal": 0, "coast": 1, "shed": 2}
            if _MODE_RANK.get(old_mode, 0) == 0 and _MODE_RANK.get(constraint.mode, 0) > 0:
                for zone in self._zone_manager.zones.values():
                    zone.runtime_seconds_this_window = 0.0
                    zone.window_start = None
                    zone.runtime_exceeded = False
                # HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1 (D-b2): the
                # deferred-occupied episode ends when the constraint
                # mode transitions in EITHER direction — clear so the
                # next episode re-emits an activity-log row.
                self._d5_occ_defer_logged_episode.clear()
            # v4.7.30 (Review B-MED-1): also clear counters when RELEASING to
            # normal from a constrained mode. Otherwise a zone that hit
            # runtime_exceeded during coast/shed stays flagged until its duty
            # window naturally expires (up to one DUTY_CYCLE_WINDOW), and the
            # actuation paths that read runtime_exceeded (e.g. the away-preset
            # force at the occupancy/preset stage) keep the zone restricted —
            # defeating the HVAC post-peak coast RELEASE this version adds.
            # Clearing on return to normal is always safe: normal applies no
            # duty limit (_accumulate_zone_runtime `continue`s in normal).
            elif _MODE_RANK.get(old_mode, 0) > 0 and _MODE_RANK.get(constraint.mode, 0) == 0:
                for zone in self._zone_manager.zones.values():
                    zone.runtime_seconds_this_window = 0.0
                    zone.window_start = None
                    zone.runtime_exceeded = False
                # HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1 (D-b2): the
                # deferred-occupied episode ends when the constraint
                # mode transitions in EITHER direction — clear so the
                # next episode re-emits an activity-log row.
                self._d5_occ_defer_logged_episode.clear()

    # ------------------------------------------------------------------
    # v3.22.0 D2: Safety hazard signal handler
    # ------------------------------------------------------------------

    @callback
    def _handle_zm_zones_updated(self, payload: Any) -> None:
        """Zone Delete Flow (fix-up R4 / B-HIGH-1 + B-HIGH-2): prune the
        deleted zone from ``ZoneManager.zones`` AND rewrite the persisted
        ``_zone_state_store`` snapshot without the deleted zone_id.

        Without the persisted-snapshot rewrite, the next boot's
        ``restore_state_snapshot`` (hvac.py:503) would RESURRECT the
        deleted zone into ``ZoneManager.zones``. This is the load-bearing
        part of the fix — pruning the in-memory dict alone would only
        survive until restart.
        """
        if payload is None:
            return
        try:
            deleted_name = (payload or {}).get("deleted_zone_name") or ""
            deleted_id = (payload or {}).get("deleted_zone_id")
        except Exception:  # noqa: BLE001
            _LOGGER.debug("ZM zones updated payload malformed", exc_info=True)
            return
        # 1) In-memory prune: if we know the zone_id, drop it; otherwise
        #    fall back to matching by zone_name.
        #
        # Concurrency note (P1): this mutates the live zones dict shared
        # with HVAC iteration loops. Callers that iterate `zones` with an
        # await in the loop body MUST snapshot via `list(...)` — see the
        # snapshotted sites at hvac.py:1108, 1158, 1525, 1825 (and mirror
        # sites in hvac_override.py, hvac_predict.py). The try/except here
        # is a defense-in-depth belt so a raced pop cannot crash the
        # dispatcher; the primary correctness contract is the caller-side
        # snapshot.
        # Zone-prune hotfix D1: build guard set of thermostat entities
        # still claimed by ANY surviving ENTRY_TYPE_ZONE_MANAGER-embedded
        # house-zone. A merged HVAC zone whose climate_entity is in this
        # set MUST NOT be pruned — deleting the husk house zone whose
        # display name collides with the merged compound name (e.g.
        # "Entertainment + Master Suite") would otherwise take the live
        # merged HVAC zone inert until the next restart re-derives it
        # via async_discover_zones (hvac.py:492, setup-only).
        # Fix-up A-CRIT-1: correct import path (const, NOT hvac_const);
        # A-HIGH-2: fold BOTH ZM-embedded AND legacy ENTRY_TYPE_ZONE surfaces
        # into the survivor set (plan Invariant I); A-MED-1: WARN + spare
        # (skip prune) on lookup failure instead of DEBUG + proceed.
        surviving_thermostats, _guard_set_ok = _compute_surviving_thermostats(
            self.hass, deleted_name,
        )
        if not _guard_set_ok:
            _LOGGER.warning(
                "HVAC prune guard: surviving-thermostat lookup failed for "
                "deleted_name=%r — sparing all merged zones from this prune "
                "(safe default; restart will re-derive via async_discover_zones)",
                deleted_name,
            )

        def _thermostat_still_claimed(zs: Any) -> bool:
            return _thermostat_still_claimed_helper(zs, surviving_thermostats)

        # Fix-up A-LOW-1: hoist pruned_ids + guard_spared_ids to the
        # handler top so the persisted-store rewrite path cannot
        # NameError if the in-memory try-block raises early. Also record
        # spares INLINE (single decision per zone_id) so the persisted
        # store mirror does not have to recompute _thermostat_still_claimed.
        pruned_ids: list[str] = []
        guard_spared_ids: set[str] = set()
        # v5.103.20 D5: snapshot room membership BEFORE the prune so the
        # pruned zone's arm re-checks can be cancelled afterwards.
        _pruned_zone_rooms: dict[str, list[str]] = {}
        try:
            for _zid0, _z0 in list(getattr(self._zone_manager, "zones", {}).items()):
                _pruned_zone_rooms[_zid0] = list(getattr(_z0, "rooms", []) or [])
        except Exception:  # noqa: BLE001
            _pruned_zone_rooms = {}
        try:
            zm = self._zone_manager
            zones = getattr(zm, "_zones", None) or getattr(zm, "zones", None) or {}
            try:
                if deleted_id and deleted_id in zones:
                    zs = zones.get(deleted_id)
                    if _thermostat_still_claimed(zs):
                        _LOGGER.warning(
                            "HVAC prune guard: skipping merged zone_id=%s "
                            "(name=%r) because thermostat=%s is still claimed "
                            "by surviving house zone(s); deleted_name=%r",
                            deleted_id, getattr(zs, "zone_name", ""),
                            getattr(zs, "climate_entity", ""), deleted_name,
                        )
                        guard_spared_ids.add(deleted_id)
                    else:
                        zones.pop(deleted_id, None)
                        pruned_ids.append(deleted_id)
                else:
                    # zone_id-unknown path: scan by zone_name.
                    for zid in list(zones.keys()):
                        zs = zones.get(zid)
                        zname = getattr(zs, "zone_name", "") or ""
                        if zname == deleted_name or (
                            " + " in zname
                            and deleted_name in [p.strip() for p in zname.split(" + ")]
                        ):
                            if _thermostat_still_claimed(zs):
                                _LOGGER.warning(
                                    "HVAC prune guard: skipping merged "
                                    "zone_id=%s (name=%r) because "
                                    "thermostat=%s is still claimed by "
                                    "surviving house zone(s); deleted_name=%r",
                                    zid, zname,
                                    getattr(zs, "climate_entity", ""),
                                    deleted_name,
                                )
                                guard_spared_ids.add(zid)
                                continue
                            zones.pop(zid, None)
                            pruned_ids.append(zid)
            except (KeyError, RuntimeError) as pop_err:  # noqa: BLE001
                # RuntimeError: dict mutated during another consumer's
                # iteration (defense-in-depth; snapshotting is the real fix).
                # KeyError: raced pop from a concurrent handler.
                _LOGGER.warning(
                    "HVAC: raced zone prune for %r (id=%r): %s",
                    deleted_name, deleted_id, pop_err,
                )
            if pruned_ids:
                _LOGGER.info(
                    "HVAC: pruned %d zone(s) from ZoneManager for deleted "
                    "zone=%r: %s", len(pruned_ids), deleted_name, pruned_ids,
                )
                # v5.103.20 (plan §5.6, REV 2 R1 LOW-9): a pruned zone's exit
                # timer and fast-path state must not fire against a zone
                # that no longer exists.
                for _pz in pruned_ids:
                    self._cancel_exit_timer(_pz)
                    self._fast_path_queued.discard(_pz)
                    self._fp_exit_fired.pop(_pz, None)
                    # D5: arm re-checks of the pruned zone's rooms.
                    for _pr in (getattr(_pruned_zone_rooms, "get", lambda *_: [])(_pz) or []):
                        _eid = self._entry_id_for_room(_pr)
                        if _eid is not None:
                            self._cancel_arm_recheck(_eid)
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "HVAC: in-memory zone prune failed for %r", deleted_name,
                exc_info=True,
            )
        # HVAC W1/W2 finish fix-up 2 (N5): drop person-interrupt latches for
        # thermostats no longer mapped to any zone (the arrester schedules
        # the snapshot save that persists the pruned `__interrupt_latch`;
        # the store rewrite below does not touch that key).
        self._prune_interrupt_latch()
        # 2) Persisted snapshot rewrite (LOAD-BEARING — else restart
        #    resurrects the zone via restore_state_snapshot at line 503).
        # D1 guard mirror: `guard_spared_ids` was recorded INLINE above
        # (fix-up A-LOW-1) — no need to recompute _thermostat_still_claimed.
        try:
            if guard_spared_ids:
                for _sid in guard_spared_ids:
                    _LOGGER.info(
                        "HVAC prune guard: sparing zone_state_store row for "
                        "zone_id=%s (thermostat still claimed)", _sid,
                    )
        except Exception:  # noqa: BLE001
            pass

        async def _rewrite_zone_state_store() -> None:
            try:
                stored = await self._zone_state_store.async_load()
                if not isinstance(stored, dict):
                    return
                changed = False
                # zone_id-only matching is sufficient here:
                #   - The persisted snapshot payload never carries
                #     `zone_name` (see hvac_zones.get_state_snapshot at
                #     hvac_zones.py:631-648 — keys are last_occupied_time,
                #     vacancy_sweep_done, zone_presence_state, ...).
                #   - When deleted_id is unknown, that path is the
                #     thermostat-configured coord_down/unknown case,
                #     which R7 (config_flow.py:7492-7502) aborts BEFORE
                #     dispatch. Husk zones (no thermostat) never enter
                #     this store, so name-based fallback is dead code.
                for zid in list(stored.keys()):
                    # Skip all meta keys (dunder-prefixed), not just the
                    # person-zone map — HVAC-ANOMALY-BLIND-1 D2 added
                    # `__short_cycles_today`, and future meta keys
                    # should not be treated as zone_ids either.
                    if isinstance(zid, str) and zid.startswith("__"):
                        continue
                    if deleted_id and zid == deleted_id and zid not in guard_spared_ids:
                        stored.pop(zid, None)
                        changed = True
                if changed:
                    await self._zone_state_store.async_save(stored)
                    _LOGGER.info(
                        "HVAC: rewrote zone_state_store without deleted "
                        "zone=%r (id=%r)", deleted_name, deleted_id,
                    )
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning(
                    "HVAC: zone_state_store rewrite failed for %r: %s",
                    deleted_name, e,
                )
        self.hass.async_create_task(_rewrite_zone_state_store())

    def _handle_safety_hazard(self, hazard: Any) -> None:
        """Handle safety hazard signal — stop fans on smoke/CO, emergency heat on freeze.

        v3.22.0 D2: Cross-coordinator response to SIGNAL_SAFETY_HAZARD.
        Gated by per-action config toggles via _get_signal_config().
        """
        if not self._enabled:
            return
        if self._observation_mode:
            _LOGGER.debug("HVAC: Safety hazard received — suppressed by observation mode")
            return

        # Extract hazard fields with safe defaults
        if hazard is None:
            return
        if isinstance(hazard, dict):
            hazard_type = hazard.get("hazard_type", "")
            severity = hazard.get("severity", "")
        elif hasattr(hazard, "hazard_type"):
            hazard_type = getattr(hazard, "hazard_type", "")
            severity = getattr(hazard, "severity", "")
        else:
            return

        from ..const import CONF_HVAC_ON_HAZARD_STOP_FANS

        # Action 1: Stop all managed fans on smoke/CO critical
        # Review fix F1: match HazardType enum values (carbon_monoxide, not co)
        if hazard_type in ("smoke", "carbon_monoxide") and severity == "critical":
            if self._get_signal_config(CONF_HVAC_ON_HAZARD_STOP_FANS):
                _LOGGER.warning(
                    "HVAC: Safety hazard %s/%s — stopping all managed fans",
                    hazard_type, severity,
                )
                task = self.hass.async_create_task(
                    self._stop_all_fans_safety()
                )
                self._pending_tasks.add(task)
                task.add_done_callback(self._pending_tasks.discard)
            else:
                _LOGGER.info(
                    "HVAC: Safety hazard %s/%s — would stop fans (disabled by config)",
                    hazard_type, severity,
                )

        # Action 2 (freeze response) intentionally REMOVED in feature/freeze-floor.
        # The old single-mode `_set_emergency_heat` was defeated by the v5.5.2
        # heat_cool enforcer (reverted to heat_cool next cycle). The freeze
        # response is now the HC-owned heat_low FLOOR enforced at the setpoint
        # chokepoint (`hvac_setpoint.emit_set_temperature`) on EVERY climate
        # write, gated by `_update_freeze_active` (live outdoor temp +
        # hysteresis) rather than the edge-emitted safety hazard signal.
        # CONF_HVAC_ON_HAZARD_EMERGENCY_HEAT is now vestigial (kept for
        # back-compat but no longer drives anything).

    async def _stop_all_fans_safety(self) -> None:
        """Stop all fans managed by the fan controller (safety response).

        Best-effort: failures logged but do not propagate.
        Session-3: per-fan emit wrapped in oracle.actuate(safety=True).
        See _safety_stop_one_fan for the wrap detail.
        """
        from ..const import CONF_FANS

        oracle = self.hass.data.get(DOMAIN, {}).get("fan_oracle")

        # snapshot: zones dict may be pruned by _handle_zm_zones_updated mid-await
        for zone_id, zone in list(self._zone_manager.zones.items()):
            for room_name in zone.rooms:
                # B-MED-2 fix-up (2026-08-11): per-room try/except so a
                # single misconfigured / mid-reload room does NOT abort
                # safety-stop for the REST of the zones. A safety hazard
                # is the last place we want a partial-execution failure.
                try:
                    coordinator = self._get_room_coordinator(room_name)
                    if coordinator is None:
                        continue
                    config = {**coordinator.config_entry.data, **coordinator.config_entry.options}
                    fans = config.get(CONF_FANS, [])
                    if not isinstance(fans, list):
                        fans = [fans]
                    for fan_entity in fans:
                        if not fan_entity:
                            continue
                        state = self.hass.states.get(fan_entity)
                        if state and state.state == "on":
                            await self._safety_stop_one_fan(
                                oracle, room_name, fan_entity,
                            )
                except Exception:  # noqa: BLE001
                    _LOGGER.warning(
                        "HVAC: safety-stop room=%s failed — continuing "
                        "with siblings (B-MED-2)", room_name, exc_info=True,
                    )
                    continue

    async def _safety_stop_one_fan(self, oracle, room_name, fan_entity):
        """Per-fan safety-stop emission (extracted so oracle.actuate can wrap).

        Kept as a helper so tests can drive ONE emission at a time and
        assert the ``safety=True`` semantics (ALLOW + pre-safety verdict
        logged). The emission lives INSIDE the ``async with oracle.actuate``
        body (no closure indirection) so C-MED-2's un-vacuoused adjacency
        walker can see the ``services.async_call`` directly under the lock.
        """
        from ..const import FAN_TRIGGER_SAFETY_STOP
        from .fan_policy_oracle import FanDecisionSnapshot

        domain = fan_entity.split(".")[0]

        if oracle is None:
            # No oracle wired — pre-Session-1 fallback path. Emit directly.
            try:
                await self.hass.services.async_call(
                    domain, "turn_off",
                    {"entity_id": fan_entity}, blocking=False,
                )
                _LOGGER.info("HVAC: Safety stop fan %s", fan_entity)
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "HVAC: Failed to stop fan %s (safety)", fan_entity,
                )
            return
        snap = FanDecisionSnapshot(
            now=dt_util.now(),
            sleep_state="unknown",
            sleep_axis=None,
            house_state=self._house_state or "unknown",
            is_hvac_managing=True,
            entities=(fan_entity,),
            observed_any_on=True,
        )
        try:
            async with oracle.actuate(
                room_name, FAN_TRIGGER_SAFETY_STOP, snap,
                direction="off", safety=True,
            ) as verdict:
                # safety=True guarantees ALLOW; guard nonetheless for
                # defense-in-depth against future oracle changes.
                if verdict.is_allow:
                    try:
                        await self.hass.services.async_call(
                            domain, "turn_off",
                            {"entity_id": fan_entity}, blocking=False,
                        )
                        _LOGGER.info("HVAC: Safety stop fan %s", fan_entity)
                    except Exception:  # noqa: BLE001
                        _LOGGER.warning(
                            "HVAC: Failed to stop fan %s (safety)", fan_entity,
                        )
        except Exception:  # noqa: BLE001 — oracle wrap must never suppress safety-stop
            _LOGGER.warning(
                "HVAC: safety-stop oracle wrap failed for %s — falling back "
                "to direct emit", fan_entity, exc_info=True,
            )
            try:
                await self.hass.services.async_call(
                    domain, "turn_off",
                    {"entity_id": fan_entity}, blocking=False,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "HVAC: Failed to stop fan %s (safety-fallback)", fan_entity,
                )

    # feature/freeze-floor: `_set_emergency_heat` removed. The freeze response
    # is now the heat_low FLOOR enforced at the setpoint chokepoint
    # (`hvac_setpoint.emit_set_temperature`). The smoke/CO fan-stop branch of
    # `_handle_safety_hazard` is unchanged.

    # ------------------------------------------------------------------
    # v3.17.0: Zone Intelligence methods
    # ------------------------------------------------------------------

    # v4.7.15 D4: _check_zone_occupancy_confidence relocated to
    # PresenceCoordinator.check_zone_occupancy_confidence(). The call site
    # in _apply_house_state_presets now reads it via the presence coordinator
    # from hass.data; identical (confirmed, possible) tuple shape preserved.

    # ------------------------------------------------------------------
    # HVAC-PRESET-FLAP-1 (2026-08-11): duty off-phase honesty (S14).
    # ------------------------------------------------------------------

    async def _execute_vacancy_sweep(self, zone) -> None:
        """Turn off URA-configured lights and fans in all rooms of a vacant zone.

        D1: Only touches entities explicitly configured in URA room entries.
        v4.2.7: Added observation mode guard + warning-level error logging.
        """
        # Defensive observation mode check (call site already gates, but
        # protect against future callers that might skip the gate)
        if self._observation_mode:
            _LOGGER.debug("HVAC: Vacancy sweep suppressed by observation mode for %s", zone.zone_name)
            return

        from ..const import CONF_LIGHTS, CONF_FANS, CONF_NIGHT_LIGHTS

        swept_count = 0
        for room_name in zone.rooms:
            coordinator = self._get_room_coordinator(room_name)
            if coordinator is None:
                continue
            config = {
                **coordinator.config_entry.data,
                **coordinator.config_entry.options,
            }

            # NIGHT-LIGHT-NO-OFF-PATH-1 (Rev 3, D5): unconditional union.
            # Zone-vacancy sweep turns off both regular and night-only
            # entities regardless of sleep — night lights behave like any
            # occupancy light on the OFF path (operator correction
            # 2026-09-01). A 02:00 sweep killing a hallway night-only
            # light when the hallway room is vacant is the DESIRED
            # behavior.
            regular = config.get(CONF_LIGHTS, []) or []
            night = config.get(CONF_NIGHT_LIGHTS, []) or []
            lights = list(regular) + [e for e in night if e not in regular]
            fans = config.get(CONF_FANS, [])

            for entity_id in lights:
                domain = entity_id.split(".")[0]
                state = self.hass.states.get(entity_id)
                if state and state.state == "on":
                    try:
                        await self.hass.services.async_call(
                            domain, "turn_off",
                            {"entity_id": entity_id}, blocking=False,
                        )
                        swept_count += 1
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.warning("HVAC: Vacancy sweep failed to turn off %s: %s", entity_id, exc)

            # FAN-MANUAL-1 (Review B-HIGH-1 fix-up, 2026-08-10): if the
            # operator has a live manual-ON hold on this room's fans
            # (either the room-tier hold, via the automation coordinator,
            # or the HVAC-tier hold, via the FanController), SKIP the
            # per-room fan sweep. INV-FMH — a fresh manual instruction
            # outranks the zone-level vacancy sweep for the duration of
            # the hold. Lights are UNAFFECTED (the hold is fan-scoped).
            fan_hold_active = False
            try:
                automation = getattr(coordinator, "automation", None)
                if automation is not None and hasattr(
                    automation, "is_fan_in_manual_on_hold",
                ):
                    fan_hold_active = bool(
                        automation.is_fan_in_manual_on_hold()
                    )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug(
                    "HVAC: sweep hold check (room-tier) failed for %s (%s)",
                    room_name, exc,
                )
            if not fan_hold_active:
                try:
                    fan_hold_active = bool(
                        self._fan_controller.is_room_in_manual_on_hold(
                            room_name,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.debug(
                        "HVAC: sweep hold check (HVAC-tier) failed for %s (%s)",
                        room_name, exc,
                    )

            if fan_hold_active:
                _LOGGER.info(
                    "HVAC: Vacancy sweep skipped fans for %s — "
                    "manual-ON hold active (FAN-MANUAL-1)",
                    room_name,
                )
            else:
                # FAN-LAYER-2 D2 W8 wrap: INDEPENDENT per-room oracle.actuate
                # (NOT routed through _set_fan_state — this loop iterates fans
                # of ONE room and issues raw services.async_call per entity;
                # see PLAN §2.2 W8 row + §5.3 nested-actuate note). The wrap
                # holds the per-room lock across the entire per-fan emit
                # sequence so an interleaving external-ON adopt cannot open a
                # manual-ON hold mid-sweep (INV-FLA-T repro from PLAN §1).
                # Fallback: oracle absent OR wrap raised → direct emit
                # (byte-identical to pre-D2 semantics).
                fan_entities_in_room = [e for e in fans if e]
                observed_any_on = any(
                    (st := self.hass.states.get(e)) is not None
                    and st.state == "on"
                    for e in fan_entities_in_room
                )
                oracle_w8 = self.hass.data.get(DOMAIN, {}).get("fan_oracle")
                fc_w8 = self._fan_controller
                snap_w8 = None
                if (
                    oracle_w8 is not None
                    and fc_w8 is not None
                    and hasattr(fc_w8, "_build_fan_snapshot_hvac")
                ):
                    try:
                        snap_w8 = fc_w8._build_fan_snapshot_hvac(
                            room_name, fan_entities_in_room, observed_any_on,
                        )
                    except Exception:  # noqa: BLE001
                        snap_w8 = None

                async def _emit_w8() -> int:
                    swept = 0
                    for entity_id in fans:
                        domain = entity_id.split(".")[0]
                        state = self.hass.states.get(entity_id)
                        if state and state.state == "on":
                            try:
                                await self.hass.services.async_call(
                                    domain, "turn_off",
                                    {"entity_id": entity_id}, blocking=False,
                                )
                                swept += 1
                            except Exception as exc:  # noqa: BLE001
                                _LOGGER.warning("HVAC: Vacancy sweep failed to turn off %s: %s", entity_id, exc)
                    return swept

                if oracle_w8 is not None and snap_w8 is not None:
                    from ..const import FAN_TRIGGER_HVAC_VACANCY  # noqa: PLC0415
                    from .fan_policy_oracle import (  # noqa: PLC0415
                        FanPolicyOracle as _Oracle,  # noqa: F401
                    )
                    # FAN-LAYER-2 D2 fix-up B-MED-1: _room_key no longer
                    # raises (sanitize-and-WARN), so the raw-string except
                    # fallback that produced misaligned keys is now dead.
                    from .hvac_fans import _room_key as _rk  # noqa: PLC0415
                    room_key_w8 = _rk(room_name)
                    try:
                        async with oracle_w8.actuate(
                            room_key_w8, FAN_TRIGGER_HVAC_VACANCY, snap_w8, "off",
                        ) as verdict:
                            if verdict.is_allow:
                                swept_count += await _emit_w8()
                            else:
                                _LOGGER.debug(
                                    "HVAC: Vacancy sweep W8 DEFER/VETO for %s "
                                    "(verdict=%s)", room_name, verdict.kind,
                                )
                    except Exception:  # noqa: BLE001
                        _LOGGER.warning(
                            "HVAC: W8 oracle wrap failed for %s — direct emit fallback",
                            room_name, exc_info=True,
                        )
                        swept_count += await _emit_w8()
                else:
                    swept_count += await _emit_w8()

        _LOGGER.info(
            "HVAC: Vacancy sweep for zone %s — swept %d entities",
            zone.zone_name, swept_count,
        )

    def _is_zone_hvac_established(self, zone) -> bool:
        """Delegate — never raises. See ZoneManager.is_zone_hvac_established."""
        try:
            zm = getattr(self, "_zone_manager", None)
            zone_id = getattr(zone, "zone_id", None)
            if zm is None or zone_id is None:
                return False
            return bool(zm.is_zone_hvac_established(zone_id))
        except Exception:  # noqa: BLE001
            return False

    def _zone_conditioning_retreat_ok(self, zone) -> bool:
        """F3 fix-up round 4 (2026-09-17): unified retreat authorization.

        Single call site for row-1 preset-flip retreat, D7 night-trust
        suppression, D9 DPM compose-away, and F4 arrester comfort-delay.
        Returns True IFF established AND fused-empty. Never raises;
        fail-CLOSED (returns False) on any accessor fault. See
        ZoneManager.conditioning_retreat_ok for the full semantics
        (reset-only backstop; person-trust dropped from the established
        path).
        """
        try:
            zm = getattr(self, "_zone_manager", None)
            if zm is None or not hasattr(zm, "conditioning_retreat_ok"):
                return False
            return bool(zm.conditioning_retreat_ok(zone))
        except Exception:  # noqa: BLE001
            return False

    def _get_room_coordinator(self, room_name: str):
        """Get room coordinator by room name."""
        from ..const import CONF_ENTRY_TYPE, CONF_ROOM_NAME, DOMAIN, ENTRY_TYPE_ROOM

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            if entry.data.get(CONF_ROOM_NAME) == room_name:
                return self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
        return None

    def _accumulate_zone_runtime(self, now: Any) -> None:
        """Track per-zone HVAC active runtime in rolling window (D5).

        Uses actual elapsed time since last call (not hardcoded 300s)
        to correctly handle ad-hoc cycles triggered by signals.
        """
        elapsed = 0.0
        if self._last_runtime_accumulation is not None:
            elapsed = min(
                (now - self._last_runtime_accumulation).total_seconds(), 300.0
            )
        self._last_runtime_accumulation = now

        # D-b3: LIVE window seconds from the Rung-3 knob. Accumulator
        # matches the enforcement site's window basis on every tick.
        window_seconds = self.duty_cycle_window_seconds
        for zone in self._zone_manager.zones.values():
            # Initialize window
            if zone.window_start is None:
                zone.window_start = now
                zone.runtime_seconds_this_window = 0.0
                zone.runtime_exceeded = False

            # Check window expiry → reset
            if (now - zone.window_start).total_seconds() >= window_seconds:
                zone.window_start = now
                zone.runtime_seconds_this_window = 0.0
                zone.runtime_exceeded = False

            # Accumulate if actively heating/cooling using actual elapsed time
            if zone.hvac_action in ("heating", "cooling") and elapsed > 0:
                zone.runtime_seconds_this_window += elapsed

            # D-b3: master enable kills enforcement entirely (accumulator
            # keeps running for diagnostics + future re-enable).
            if not self.d5_enabled:
                continue

            # Check duty cycle — LIVE percentage knobs. `0` on a cap =
            # documented kill for that mode (no cap can be reached).
            mode = self._energy_constraint_mode
            if mode == "shed":
                cap_pct = self.duty_cycle_shed_pct
            elif mode == "coast":
                cap_pct = self.duty_cycle_coast_pct
            else:
                continue  # No limit in normal mode
            if cap_pct <= 0:
                # Kill switch for this mode — never trip. F5 (fix-up):
                # clear any latched `runtime_exceeded` BEFORE returning
                # so an operator setting a mode cap to 0 mid-episode
                # doesn't leave the zone forced-away for up to a full
                # window. Same clear also releases a grow-window seed
                # that predated a live knob change.
                zone.runtime_exceeded = False
                continue
            max_seconds = window_seconds * (cap_pct / 100.0)

            # Skip enforcement during sleep (RH4 fix)
            if self._house_state == "sleep":
                continue

            if zone.runtime_seconds_this_window >= max_seconds:
                zone.runtime_exceeded = True

    def _build_person_zone_map(self) -> dict[str, list[str]]:
        """Build person->zones reverse map from zone configs.

        v3.18.5: Each zone has zone_persons: ["person.oji", "person.nkem"].
        Builds reverse: {"person.oji": ["zone_1", "zone_3"], ...}
        """
        pzm: dict[str, list[str]] = {}
        for zone_id, zone in self._zone_manager.zones.items():
            for person in zone.zone_persons:
                pzm.setdefault(person, []).append(zone_id)
        return pzm

    def _build_camera_zone_map(self) -> dict[str, str]:
        """Build camera->zone reverse map from zone configs (diagnostic).

        v3.19.0: Used for diagnostics — shows which cameras map to which zones.
        """
        czm: dict[str, str] = {}
        for zone_id, zone in self._zone_manager.zones.items():
            for cam in zone.zone_cameras:
                czm[cam] = zone_id
        return czm

    @callback
    def _handle_person_arriving(self, data: dict) -> None:
        """Route arriving person to preferred zones for pre-conditioning (D3)."""
        if not self._zone_intelligence_enabled:
            return

        # v3.18.6: Check pre-arrival enabled and source filter
        if not self._pre_arrival_enabled:
            return
        source = data.get("source", "")
        if source and source not in self._pre_arrival_sources:
            _LOGGER.debug("HVAC: Ignoring pre-arrival from source %s (not enabled)", source)
            return

        person_entity = data.get("person_entity", "")
        preferred_zones = self._person_zone_map.get(person_entity, [])

        if not preferred_zones:
            _LOGGER.debug("HVAC: No preferred zones for %s", person_entity)
            return

        now = dt_util.utcnow()
        _win = timedelta(seconds=self._pre_arrival_window_s())
        for zone_id in preferred_zones:
            if zone_id in self._zone_manager.zones:
                # D-L5: a repeat trigger inside a spent arrival episode only
                # extends that episode — no new pre-arrival, no new pre-cool.
                _spent_at = self._pre_arrival_spent.get(zone_id)
                if _spent_at is not None and (now - _spent_at) <= _win:
                    self._pre_arrival_spent[zone_id] = now
                    _LOGGER.info(
                        "HVAC: Pre-arrival for zone %s ignored — this arrival "
                        "episode's pre-cool already ended", zone_id,
                    )
                    continue
                self._pre_arrival_spent.pop(zone_id, None)
                self._pre_arrival_zones.add(zone_id)
                self._pre_arrival_persons[zone_id] = person_entity
                self._pre_arrival_start[zone_id] = now

        _LOGGER.info(
            "HVAC: Pre-arrival for %s → zones %s (source=%s)",
            person_entity, preferred_zones, source or "unknown",
        )

        # Activity log: HVAC pre-arrival
        from ..const import DOMAIN
        activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
        if activity_logger:
            self.hass.async_create_task(
                activity_logger.log(
                    coordinator="hvac",
                    action="pre_arrival",
                    description=f"Pre-arrival for {person_entity} → zones {preferred_zones} (source={source or 'unknown'})",
                    importance="notable",
                    details={"person": person_entity, "zones": preferred_zones, "source": source},
                )
            )

        # v3.18.6: Track last trigger for diagnostics
        self._last_pre_arrival_time = dt_util.utcnow()
        self._last_pre_arrival_source = data.get("source", "unknown")
        self._last_pre_arrival_person = person_entity
        self._pre_arrival_triggers_today.increment()

        # Trigger immediate decision cycle
        task = self.hass.async_create_task(
            self._async_decision_cycle(trigger="pre_arrival")
        )
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    def _seed_ura_setpoint_record_from_rows(self) -> None:
        """HVAC W1/W2 finish D1 boot seed: append each live (rehydrated)
        borrow row's excursion target to the funnel's URA-write record for
        its zone's entity. Never raises."""
        try:
            from . import hvac_excursion as _ex_seed  # noqa: PLC0415
            from .hvac_setpoint import record_ura_setpoint  # noqa: PLC0415
            for zone_id, tok in list(_ex_seed._rows.items()):
                lo = getattr(tok, "excursion_target_low", None)
                hi = getattr(tok, "excursion_target_high", None)
                if lo is None and hi is None:
                    continue
                zone = self._zone_manager.zones.get(zone_id)
                ent = getattr(zone, "climate_entity", None) if zone else None
                if ent:
                    record_ura_setpoint(ent, lo, hi)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("HVAC: URA setpoint record boot seed failed", exc_info=True)

    def _spend_pre_arrival_episode(self, zone_id: str, now: Any = None) -> None:
        """D-L5 / fix-up 2: the zone's current arrival EPISODE is spent (its
        pre-cool ended by max age, inactivity, master OFF or a person's
        interrupt). Records the last trigger time in `_pre_arrival_spent` and
        drops the zone from the pre-arrival set. Discharge: HVAC arrival in
        the zone, or a whole window with no trigger (see
        `_expire_pre_arrival_zones` / `_handle_person_arriving`)."""
        now = now or dt_util.utcnow()
        self._pre_arrival_spent[zone_id] = self._pre_arrival_start.get(zone_id) or now
        self._pre_arrival_zones.discard(zone_id)
        self._pre_arrival_start.pop(zone_id, None)
        self._pre_arrival_persons.pop(zone_id, None)

    def _prune_interrupt_latch(self) -> None:
        """Fix-up 2 (N5): hand the arrester the current zone map so latches
        for unmapped thermostats are dropped. Never raises."""
        try:
            self._override_arrester.prune_interrupt_latch()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("HVAC: interrupt-latch prune failed", exc_info=True)

    def _pre_arrival_window_s(self) -> float:
        """Knob 35 in seconds. Every writer (constructor, in-place options
        apply, Number entity) clamps to [5, 110] min."""
        return float(getattr(
            self, "_pre_arrival_window_minutes",
            DEFAULT_HVAC_PRE_ARRIVAL_WINDOW_MINUTES,
        )) * 60.0

    def _expire_pre_arrival_zones(
        self, now: Any, zone_filter: set[str] | None = None,
    ) -> dict[str, str]:
        """Clear stale pre-arrival zones (person didn't show up within timeout).

        When a pre-arrival zone is cleared due to timeout (not occupancy),
        turn off fans that were activated as comfort bridge.

        HVAC W1/W2 finish D3: arrival is HVAC occupancy
        (`any_room_hvac_occupied`, hallway-excluded — a hallway crossing
        must not end a pre-cool; P4), falling back to the lighting signal
        only when the attribute is missing. The timeout is knob 35. A zone
        whose pre-arrival borrow a person ended is cleared as `interrupted`
        (a pull; its fans are left on). ``zone_filter`` scopes a fast run to
        its own zone (M10). Returns {zone_id: arrived | timeout |
        interrupted} for the zones cleared on this call.
        """
        timeout = timedelta(seconds=self._pre_arrival_window_s())
        zones_to_defan: list = []
        cleared: dict[str, str] = {}
        # D-L5: end spent arrival episodes on HVAC arrival or after a whole
        # window with no trigger.
        for _sz in list(self._pre_arrival_spent):
            if zone_filter is not None and _sz not in zone_filter:
                continue
            _zs = self._zone_manager.zones.get(_sz)
            if _zs is None or bool(getattr(_zs, "any_room_hvac_occupied", False)):
                self._pre_arrival_spent.pop(_sz, None)
                continue
            if (now - self._pre_arrival_spent[_sz]) > timeout:
                self._pre_arrival_spent.pop(_sz, None)
        tokens = getattr(self._predictor, "_banking_excursion_tokens", None) or {}
        for zone_id in list(self._pre_arrival_zones):
            if zone_filter is not None and zone_id not in zone_filter:
                continue
            zone = self._zone_manager.zones.get(zone_id)
            # A person ended this zone's pre-arrival borrow (human_interrupt).
            _tok = tokens.get(zone_id)
            if (
                _tok is not None
                and getattr(_tok, "caller_site", None) == S12_PRE_ARRIVAL_SITE
                and _tok.returned
            ):
                # Fix-up 2 (N2): the person ended this arrival's pre-cool —
                # the arrival EPISODE is spent, so a repeat trigger inside
                # the window does not start a second pre-cool once the S4 /
                # S1 pin has discharged the latch.
                self._spend_pre_arrival_episode(zone_id, now)
                cleared[zone_id] = "interrupted"
                _LOGGER.info("HVAC: Pre-arrival cleared for zone %s (interrupted)", zone_id)
                continue
            # Clear if zone is now occupied (person arrived — fans managed by fan controller)
            _arr = getattr(zone, "any_room_hvac_occupied", None) if zone else None
            if _arr is None and zone is not None:
                _arr = getattr(zone, "any_room_occupied", False)
            if zone and _arr:
                self._pre_arrival_zones.discard(zone_id)
                self._pre_arrival_start.pop(zone_id, None)
                self._pre_arrival_persons.pop(zone_id, None)
                cleared[zone_id] = "arrived"
                _LOGGER.info("HVAC: Pre-arrival cleared for zone %s (occupied)", zone_id)
                continue

            # Clear if timeout exceeded — also turn off pre-arrival fans
            start = self._pre_arrival_start.get(zone_id)
            if start and (now - start) > timeout:
                self._pre_arrival_zones.discard(zone_id)
                self._pre_arrival_start.pop(zone_id, None)
                self._pre_arrival_persons.pop(zone_id, None)
                cleared[zone_id] = "timeout"
                if zone:
                    zones_to_defan.append(zone)
                _LOGGER.info("HVAC: Pre-arrival timeout for zone %s", zone_id)

        # Turn off fans for timed-out pre-arrival zones (best-effort)
        for zone in zones_to_defan:
            self.hass.async_create_task(self._deactivate_zone_fans(zone))
        return cleared

    async def _async_end_pre_arrival_borrows(
        self, reasons: dict[str, str] | None,
        zone_filter: set[str] | None = None,
        all_inactive: bool = False,
    ) -> None:
        """HVAC W1/W2 finish D3 call-site helper: run the predictor's
        reconciliation BEFORE S1 (INV-B.3), then drop max-aged zones from the
        pre-arrival set and refresh the touched zones' climate state so S1
        reads the post-release preset. Runs whatever the observation mode
        (S12 starts regardless — Bug Class #23 symmetry). With Zone
        Intelligence off, no pre-arrival is active, so every pre-arrival
        borrow ends."""
        try:
            active = (
                set(self._pre_arrival_zones)
                if self._zone_intelligence_enabled and not all_inactive
                else set()
            )
            _toks = getattr(self._predictor, "_banking_excursion_tokens", None) or {}
            _before = set(_toks.keys())
            max_aged = await self._predictor.async_end_pre_arrival_borrows(
                active, reasons or {}, self._pre_arrival_window_s(),
                zone_filter=zone_filter,
            )
            _now_sp = dt_util.utcnow()
            for _zid in max_aged:
                # D-L5: the arrival EPISODE is spent — no new pre-cool for
                # this zone until the episode ends (arrival, or no trigger
                # for a whole window). Keyed by the last trigger time.
                self._spend_pre_arrival_episode(_zid, _now_sp)
                # A-M1: the max-age end turns the zone's pre-arrival fans off
                # exactly like the timeout branch.
                _z_fan = self._zone_manager.zones.get(_zid)
                if _z_fan is not None:
                    self.hass.async_create_task(self._deactivate_zone_fans(_z_fan))
            if all_inactive or not self._zone_intelligence_enabled:
                # D-L5: ZI off (or the coordinator off) ended every live
                # pre-arrival borrow as inactive — mark those episodes spent
                # too, so ZI off->on within the window does not re-begin.
                for _zid in _before - set((getattr(self._predictor, "_banking_excursion_tokens", None) or {}).keys()):
                    if _zid in self._pre_arrival_zones:
                        self._spend_pre_arrival_episode(_zid, _now_sp)
            # Refresh ONLY the zones whose borrow was ended here (no-op pass
            # stays byte-identical).
            _after = set((getattr(self._predictor, "_banking_excursion_tokens", None) or {}).keys())
            _zm = self._zone_manager
            for _zid in _before - _after:
                if _zid in _zm.zones:
                    _zm.update_zone_climate_state(_zid)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("HVAC: pre-arrival borrow reconciliation failed", exc_info=True)

    async def _deactivate_zone_fans(self, zone) -> None:
        """Turn off fans that were activated for pre-arrival comfort bridge.

        Only deactivates fans in rooms that the predictor actually activated,
        to avoid turning off fans managed by FanController or the user.
        """
        from ..const import CONF_FANS, CONF_ENTRY_TYPE, CONF_ROOM_NAME, DOMAIN, ENTRY_TYPE_ROOM

        # Only touch rooms that the predictor explicitly activated
        activated_rooms = set(
            getattr(self._predictor, '_last_fan_activation_rooms', [])
        )
        deactivated: list[str] = []

        for room_name in zone.rooms:
            if room_name not in activated_rooms:
                continue
            coordinator = self._get_room_coordinator(room_name)
            if coordinator is None:
                continue
            config = {**coordinator.config_entry.data, **coordinator.config_entry.options}
            fans = config.get(CONF_FANS, [])
            # FAN-MANUAL-1 (MED-B1 fix-up, 2026-08-10): skip pre-arrival
            # deactivation while a manual-ON hold is live for this room.
            # Same INV-FMH gate as the zone-vacancy sweep (_execute_vacancy_sweep).
            fan_hold_active = False
            try:
                automation = getattr(coordinator, "automation", None)
                if automation is not None and hasattr(
                    automation, "is_fan_in_manual_on_hold",
                ):
                    fan_hold_active = bool(automation.is_fan_in_manual_on_hold())
            except Exception:  # noqa: BLE001
                pass
            if not fan_hold_active:
                try:
                    fan_hold_active = bool(
                        self._fan_controller.is_room_in_manual_on_hold(room_name)
                    )
                except Exception:  # noqa: BLE001
                    pass
            if fan_hold_active:
                _LOGGER.info(
                    "HVAC: Pre-arrival fan deactivation skipped for %s — "
                    "manual-ON hold active (FAN-MANUAL-1)", room_name,
                )
                continue
            # FAN-LAYER-2 D2 W9 wrap: INDEPENDENT per-room oracle.actuate
            # around the pre-arrival fan-deactivation emit loop (mirrors
            # W8 in _execute_vacancy_sweep — see PLAN §2.2 W9 row). Fallback:
            # oracle absent OR wrap raised → direct emit (byte-identical).
            fan_entities_in_room = [e for e in fans if e]
            observed_any_on = any(
                (st := self.hass.states.get(e)) is not None
                and st.state == "on"
                for e in fan_entities_in_room
            )
            oracle_w9 = self.hass.data.get(DOMAIN, {}).get("fan_oracle")
            fc_w9 = self._fan_controller
            snap_w9 = None
            if (
                oracle_w9 is not None
                and fc_w9 is not None
                and hasattr(fc_w9, "_build_fan_snapshot_hvac")
            ):
                try:
                    snap_w9 = fc_w9._build_fan_snapshot_hvac(
                        room_name, fan_entities_in_room, observed_any_on,
                    )
                except Exception:  # noqa: BLE001
                    snap_w9 = None

            async def _emit_w9() -> None:
                for fan_entity in fans:
                    domain = fan_entity.split(".")[0]
                    state = self.hass.states.get(fan_entity)
                    if state and state.state == "on":
                        try:
                            await self.hass.services.async_call(
                                domain, "turn_off",
                                {"entity_id": fan_entity}, blocking=False,
                            )
                        except Exception:  # noqa: BLE001
                            _LOGGER.warning(
                                "HVAC: Pre-arrival fan deactivation failed for %s",
                                fan_entity,
                            )

            if oracle_w9 is not None and snap_w9 is not None:
                from ..const import FAN_TRIGGER_HVAC_PREARRIVAL  # noqa: PLC0415
                # FAN-LAYER-2 D2 fix-up B-MED-1: _room_key no longer raises.
                from .hvac_fans import _room_key as _rk  # noqa: PLC0415
                room_key_w9 = _rk(room_name)
                try:
                    async with oracle_w9.actuate(
                        room_key_w9, FAN_TRIGGER_HVAC_PREARRIVAL, snap_w9, "off",
                    ) as verdict:
                        if verdict.is_allow:
                            await _emit_w9()
                        else:
                            _LOGGER.debug(
                                "HVAC: Pre-arrival W9 DEFER/VETO for %s (verdict=%s)",
                                room_name, verdict.kind,
                            )
                except Exception:  # noqa: BLE001
                    _LOGGER.warning(
                        "HVAC: W9 oracle wrap failed for %s — direct emit fallback",
                        room_name, exc_info=True,
                    )
                    await _emit_w9()
            else:
                await _emit_w9()
            deactivated.append(room_name)

        _LOGGER.info(
            "HVAC: Pre-arrival fans deactivated for zone %s (timeout): rooms=%s",
            zone.zone_name, deactivated,
        )

    def _compute_zone_presence_states(self, now: Any) -> None:
        """Compute the 7-state zone presence state machine (D4).

        Priority: sleep > runtime_limited > pre_arrival > pre_conditioning
                  > occupied > vacant > away.
        """
        energy_constrained = self._energy_constraint_mode in ("coast", "shed")
        grace_minutes = (
            self._vacancy_grace_constrained if energy_constrained
            else self._vacancy_grace
        )

        pre_conditioning_zones = getattr(
            self._predictor, "_pre_conditioning_zones", set()
        )

        for zone_id, zone in self._zone_manager.zones.items():
            if self._house_state == "sleep":
                zone.zone_presence_state = "sleep"
            elif zone.runtime_exceeded:
                # D-b1: operator-facing state label renamed. Internal
                # `runtime_exceeded` field kept for stability.
                zone.zone_presence_state = "energy_shed_cap_reached"
            elif zone_id in self._pre_arrival_zones:
                zone.zone_presence_state = "pre_arrival"
            elif zone_id in pre_conditioning_zones:
                zone.zone_presence_state = "pre_conditioning"
            # HVAC-ZONE-CONDITIONING-DEMAND-1 §2a row 7: SWAP zone_presence_state
            # to the HVAC denomination. Pairs with row 2a's HVAC-scoped
            # last_occupied_time so the "vacant" branch's grace math uses a
            # matching basis. Diagnostic entity now reports HVAC-side
            # occupancy (matches intent).
            elif (
                getattr(zone, "any_room_hvac_occupied", None)
                if getattr(zone, "any_room_hvac_occupied", None) is not None
                else getattr(zone, "any_room_occupied", True)
            ):
                zone.zone_presence_state = "occupied"
            elif (
                zone.last_occupied_time is not None
                and (now - zone.last_occupied_time).total_seconds()
                <= grace_minutes * 60
            ):
                zone.zone_presence_state = "vacant"
            else:
                zone.zone_presence_state = "away"

    # ------------------------------------------------------------------
    # HVAC-ANOMALY-BLIND-1 D2 — Short-cycle producer (event-driven)
    # ------------------------------------------------------------------
    def _install_short_cycle_listeners(self) -> None:
        """Register a state-change listener on each discovered zone's
        climate entity so `hvac_action` transitions drive the short-cycle
        tracker directly — no 5-min-tick polling loss.

        The unsub is appended to the shared `self._unsub_listeners`
        (drained by `self._cancel_listeners()` in `async_teardown`), so
        the listener follows the same lifecycle envelope as every other
        HVAC listener. Idempotent — a re-run (e.g. zone-config reload)
        will not double-register because `_short_cycle_listener_installed`
        latches.
        """
        if self._short_cycle_listener_installed:
            return
        entities = [
            z.climate_entity
            for z in self._zone_manager.zones.values()
            if z.climate_entity
        ]
        if not entities:
            _LOGGER.debug(
                "HVAC short-cycle: no climate entities to watch"
            )
            return
        try:
            unsub = async_track_state_change_event(
                self.hass, entities, self._on_zone_climate_state_change,
            )
            self._unsub_listeners.append(unsub)
            self._short_cycle_listener_installed = True
            _LOGGER.info(
                "HVAC short-cycle: watching %d climate entities (%s)",
                len(entities), entities,
            )
        except Exception as e:
            _LOGGER.warning(
                "HVAC short-cycle: failed to install state listener: %s", e,
            )

    @callback
    def _on_zone_climate_state_change(self, event: Any) -> None:
        """Handler for climate.hvac_action transitions.

        idle→active: stamp `_short_cycle_on_since[zone_id] = now()`.
        active→idle: if on_since is set AND its duration is under
          SHORT_CYCLE_THRESHOLD_S, increment
          `_short_cycles_today[zone_id]` (clamping the date first if the
          restored counter is from a previous day). Missing on_since ==
          the on-cycle started before this boot: DISCARD.
        """
        try:
            data = event.data
            entity_id = data.get("entity_id")
            new_state = data.get("new_state")
            old_state = data.get("old_state")
            if entity_id is None or new_state is None:
                return
            # A-H1 / B-HIGH-2 (review fix-up): drop unavailable/unknown
            # transitions before they fabricate a phantom short cycle from
            # a WiFi/cloud blip. Symmetric on both sides — if either endpoint
            # of the transition is UNAVAILABLE/UNKNOWN we can't trust the
            # duration, and we clear any dangling on_since so the next real
            # idle→active transition starts a fresh cycle.
            zone_id_for_drop: str | None = None
            for zid, zone in self._zone_manager.zones.items():
                if zone.climate_entity == entity_id:
                    zone_id_for_drop = zid
                    break
            if new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                if zone_id_for_drop is not None:
                    self._short_cycle_on_since.pop(zone_id_for_drop, None)
                return
            if old_state is not None and old_state.state in (
                STATE_UNAVAILABLE, STATE_UNKNOWN,
            ):
                if zone_id_for_drop is not None:
                    self._short_cycle_on_since.pop(zone_id_for_drop, None)
                return
            new_action = new_state.attributes.get("hvac_action") or ""
            old_action = (
                old_state.attributes.get("hvac_action") if old_state else ""
            ) or ""
            # If hvac_action attribute is missing/None on the new state,
            # treat it like unavailable (can't classify → drop).
            if new_state.attributes.get("hvac_action") is None:
                if zone_id_for_drop is not None:
                    self._short_cycle_on_since.pop(zone_id_for_drop, None)
                return
            if new_action == old_action:
                return
            zone_id: str | None = zone_id_for_drop
            if zone_id is None:
                return
            active_states = ("cooling", "heating")
            now_local = dt_util.now()
            if old_action not in active_states and new_action in active_states:
                # idle → active
                self._short_cycle_on_since[zone_id] = now_local
                _LOGGER.debug(
                    "HVAC short-cycle: zone=%s on_since=%s",
                    zone_id, now_local.isoformat(),
                )
            elif old_action in active_states and new_action not in active_states:
                # active → idle
                on_since = self._short_cycle_on_since.pop(zone_id, None)
                if on_since is None:
                    _LOGGER.debug(
                        "HVAC short-cycle: zone=%s cycle-end with no "
                        "on_since (predates boot?) — DISCARD",
                        zone_id,
                    )
                    return
                duration_s = (now_local - on_since).total_seconds()
                if duration_s < SHORT_CYCLE_THRESHOLD_S:
                    today = now_local.date().isoformat()
                    # A-C2 / B-MED-1 (review fix-up): the callback used to
                    # schedule `_emit_and_reset_short_cycles` via
                    # async_create_task on a stale-date increment. That path
                    # (a) double-emitted (not under the decision lock),
                    # (b) misattributed the day by incrementing BEFORE the
                    # scheduled task ran, and (c) was an untracked task.
                    # The ≤5-min decision-cycle rollover in hvac.py:1304-05
                    # is now the SOLE rollover path. If the date is stale
                    # here, skip the increment and let the next decision
                    # tick roll + attribute correctly. The cycle is
                    # discarded, not lost to yesterday.
                    if (
                        self._short_cycles_today_date
                        and self._short_cycles_today_date != today
                    ):
                        _LOGGER.debug(
                            "HVAC short-cycle: zone=%s cycle-end straddled "
                            "day rollover (stored=%s today=%s) — DISCARD, "
                            "decision tick will roll",
                            zone_id, self._short_cycles_today_date, today,
                        )
                        return
                    self._short_cycles_today[zone_id] = (
                        self._short_cycles_today.get(zone_id, 0) + 1
                    )
                    if not self._short_cycles_today_date:
                        self._short_cycles_today_date = today
                    _LOGGER.info(
                        "HVAC short-cycle: zone=%s duration=%.1fs "
                        "count_today=%d",
                        zone_id, duration_s,
                        self._short_cycles_today[zone_id],
                    )
                else:
                    _LOGGER.debug(
                        "HVAC short-cycle: zone=%s duration=%.1fs "
                        "(above threshold, not counted)",
                        zone_id, duration_s,
                    )
        except Exception:
            _LOGGER.debug(
                "HVAC short-cycle: state-change handler failed",
                exc_info=True,
            )

    async def _emit_and_reset_short_cycles(self, today: str) -> None:
        """Rollover emitter — records one observation per zone for the
        completed day, clears prior-day active anomalies for the metric
        (via the D1c filtered clear), then resets the counter and stamps
        the new date.

        CRITICAL GUARD (falsifiable invariant, planning doc §Invariant):
        gate on the tracker's OWN persisted date
        (`_short_cycles_today_date`), NEVER on `_last_daily_reset` (which
        is RAM-only and would fire an empty observation on every boot).
          - first boot (prev_date == ""): seed date, no emit
          - mid-day restart (prev_date == today): strict no-op
          - genuine day rollover (prev_date != "" and != today): emit
            each zone's count, clear latched anomalies, reset to zero
            keyed on today
        """
        prev_date = self._short_cycles_today_date
        if prev_date == "":
            self._short_cycles_today_date = today
            _LOGGER.debug(
                "HVAC short-cycle: first-boot seed date=%s (no emit)", today,
            )
            return
        if prev_date == today:
            return
        if self.anomaly_detector is None:
            # B-MED-3 / A-M3 (review fix-up): no detector to emit into.
            # Reset the counter so it doesn't grow unbounded across days,
            # but do NOT advance the date — leave the rollover pending so
            # the next tick with a live detector still evaluates.
            self._short_cycles_today = {
                zid: 0 for zid in self._zone_manager.zones
            }
            return
        # B-MED-2 (review fix-up): multi-day-down restart. Only emit when
        # prev_date is exactly (today - 1 local day). Any larger gap means
        # the counter represents an unknown-length partial history — emit
        # would be a stale partial-day sample; discard-and-reseed instead.
        try:
            prev_dt = dt_util.parse_datetime(prev_date + "T00:00:00")
            today_dt = dt_util.parse_datetime(today + "T00:00:00")
            if prev_dt is None or today_dt is None:
                gap_days = None
            else:
                gap_days = (today_dt.date() - prev_dt.date()).days
        except Exception:
            gap_days = None
        if gap_days is None or gap_days != 1:
            _LOGGER.info(
                "HVAC short-cycle: multi-day gap (prev=%s today=%s "
                "gap_days=%s) — DISCARD accumulated counts, reseed date",
                prev_date, today, gap_days,
            )
            self._short_cycles_today = {
                zid: 0 for zid in self._zone_manager.zones
            }
            self._short_cycles_today_date = today
            return
        for zone_id in list(self._zone_manager.zones.keys()):
            count = int(self._short_cycles_today.get(zone_id, 0))
            # A-C1 / B-HIGH-1 (review fix-up): clear the (metric, scope)
            # BEFORE recording the new observation, so the just-cleared
            # slot is empty when record_observation potentially appends a
            # fresh anomaly for today's value. Prior ordering deleted the
            # anomaly it had just created → sensor/get_worst_severity
            # never saw it.
            try:
                self.anomaly_detector.clear_active_anomalies_filtered(
                    metric_name="short_cycle_rate", scope=zone_id,
                )
            except Exception:
                _LOGGER.debug(
                    "HVAC short-cycle: filtered clear failed for zone=%s",
                    zone_id, exc_info=True,
                )
            try:
                anomaly = self.anomaly_detector.record_observation(
                    "short_cycle_rate", zone_id, float(count),
                )
            except Exception as e:
                _LOGGER.warning(
                    "HVAC short-cycle: record_observation failed for "
                    "zone=%s: %s", zone_id, e,
                )
                continue
            if anomaly is not None:
                _LOGGER.info(
                    "HVAC short-cycle anomaly: zone=%s count=%d "
                    "severity=%s z=%.2f",
                    zone_id, count, anomaly.severity.value, anomaly.z_score,
                )
                try:
                    from .anomaly_event import (  # noqa: PLC0415
                        AnomalyEvent,
                        AnomalyType,
                        build_context_json,
                        map_diag_severity,
                    )
                    ctx = build_context_json(
                        zone_id=zone_id,
                        source_signal="hvac_short_cycle_rollover",
                        extra={
                            "short_cycles_yesterday": count,
                            "threshold_s": SHORT_CYCLE_THRESHOLD_S,
                        },
                    )
                    event = AnomalyEvent(
                        coordinator="hvac",
                        type="hvac.short_cycle_rate",
                        severity=map_diag_severity(anomaly.severity),
                        anomaly_type=AnomalyType.POINT_IN_TIME,
                        detected_at=anomaly.timestamp.isoformat(),
                        payload=ctx,
                        observed_value=anomaly.observed_value,
                        expected_mean=anomaly.expected_mean,
                        expected_std=anomaly.expected_std,
                        z_score=round(anomaly.z_score, 3),
                        sample_size=anomaly.sample_size,
                    )
                    await self.anomaly_detector.store_event(event)
                except Exception:
                    _LOGGER.debug(
                        "HVAC short-cycle: anomaly persist failed",
                        exc_info=True,
                    )
        # B4 (2026-08-23 Tier-2-DB review residual): persist the baselines
        # NOW, on the genuine-rollover path only. record_observation is
        # pure in-memory (coordinator_diagnostics.py:988) and the
        # coordinator's only other save_baselines() call is in
        # async_teardown — so at ~2.9 restarts/day the once-per-local-day
        # short_cycle_rate observation was almost always discarded before
        # reaching metric_baselines, leaving sample_count stuck far below
        # HVAC_SHORT_CYCLE_MIN_SAMPLES.
        #
        # Same doctrine as the CM setup_duration_seconds precedent at
        # __init__.py:4058-4068: a metric that fires ONCE per day/boot
        # cannot use the teardown-only cadence its many-times-per-session
        # peers use. This save deliberately does NOT run on any of the
        # four early-return paths above (first-boot seed, mid-day restart,
        # detector-None, multi-day gap) — a save on the mid-day-restart
        # path would fire on every boot.
        #
        # Isolated so a DB failure can never prevent the load-bearing
        # counter reset / date stamp (same defensive style as store_event
        # and clear_active_anomalies_filtered above).
        #
        # ORDERING (fix-up round, Review B LOW-2): the counter reset and
        # the date stamp run BEFORE the await, not after. `CancelledError`
        # is a `BaseException`, so it escapes the `except Exception` below
        # — if a shutdown cancels this tick inside the awaited save, a
        # reset-after-save ordering would never reach the date stamp;
        # teardown would then persist {date: prev_date, counts: non-zero}
        # and the NEXT boot's rollover would re-record the same day, a
        # duplicate observation into a 14-sample gate. Reordering is free:
        # every observation is already recorded in memory above, so what
        # gets persisted is unchanged.
        # Reset counter keyed on the new day.
        self._short_cycles_today = {
            zid: 0 for zid in self._zone_manager.zones
        }
        self._short_cycles_today_date = today
        # DURABILITY NUDGE (fix-up round, Review A MEDIUM-1): the stamp
        # above is RAM-only. The durable copy lives in the zone-state
        # `.storage` snapshot, written at clean teardown or by the
        # periodic block below (gated on `_zone_state_save_counter >= 5`,
        # ~25 min). Setting the counter to 4 here makes the increment in
        # `_run_decision_cycle` reach 5 and write the durable snapshot
        # later in the SAME decision cycle (this method is awaited from
        # that function, and there is no `return` between the two sites).
        #
        # HONEST SCOPE: this SHRINKS the double-count window from up to
        # ~25 minutes to the remainder of one decision cycle. It does NOT
        # close it — an unclean kill between this baseline save and the
        # snapshot write later in the tick can still double-count the
        # day. Full closure needs the durable snapshot written BEFORE the
        # baseline save, i.e. a shared snapshot-construction helper used
        # by all three sites (rollover, periodic, teardown). Deliberately
        # out of scope for an unattended overnight change; carded.
        self._zone_state_save_counter = 4
        try:
            await self.anomaly_detector.save_baselines()
            _LOGGER.info(
                "HVAC short-cycle: baselines persisted after day rollover "
                "(prev=%s today=%s)", prev_date, today,
            )
        except Exception as e:
            # `save_baselines` already swallows DB errors one level down,
            # so anything reaching here is a programming error — error,
            # not warning (fix-up round, Review A LOW-2).
            _LOGGER.error(
                "HVAC short-cycle: save_baselines failed after rollover "
                "(prev=%s today=%s): %s — counter already reset",
                prev_date, today, e,
            )

    async def _record_anomaly_observations(self) -> None:
        """Record observations for anomaly detection and persist anomalies to anomaly_log.

        v4.6.5 D1: Added save_anomaly_event persistence for continuous HVAC metrics.

        METRIC AUDIT (v4.6.5 binary-metric check per v4.6.3.1 doctrine,
        revised pre-deploy after live cardinality audit):
        - zone_call_frequency: integer count of zones actively cooling/heating
          (0..N where N = HVAC zone count). LIVE BASELINE on a 3-zone install
          showed mean=0.378, std=0.678 over 899 samples — degenerate-shape per
          v4.6.3.1 doctrine. Z-score arithmetic: active_count=2 → z=2.39 →
          ADVISORY fires; active_count=3 → z=3.87 → near CRITICAL. Same family
          as the suppressed census_count (mean=0.64, std=1.39 → 1825 emits/24h).
          In normal use, 2+ zones calling simultaneously happens routinely
          during morning warm-up and evening cool-down → persistence would
          flood anomaly_log. SUPPRESSED_FROM_PERSISTENCE. Long-term fix:
          replace with a duty-cycle ratio (continuous 0..1) or per-zone Bayesian
          time-bin distribution.
        - override_frequency: integer count of overrides today across zones,
          grows throughout day. Live mean=3.234, std=3.436 — well-shaped
          continuous distribution. WIRE.
        - short_cycle_rate: HVAC-ANOMALY-BLIND-1 D2 — WIRED via a per-zone
          event-driven producer (`_on_zone_climate_state_change` +
          `_emit_and_reset_short_cycles`), one observation per zone per
          LOCAL-day rollover. PERSISTED (removed from
          HVAC_SUPPRESSED_FROM_PERSISTENCE). Not emitted from this
          function — the emit hinge is the daily-reset block in
          _run_decision_cycle.
        - comfort_deviation_hours: defined in HVAC_METRICS but never recorded via
          record_observation (no call site exists). SUPPRESSED_FROM_PERSISTENCE —
          metric is silent; z-score detection never fires for it.
        """
        # v4.6.5.1 P2: SUPPRESSED_FROM_PERSISTENCE was promoted to module-level
        # constant `HVAC_SUPPRESSED_FROM_PERSISTENCE` in hvac_const.py so the
        # parametric meta-test can introspect it. See that constant's docstring
        # for the per-metric suppression rationale.
        if self.anomaly_detector is None:
            return

        # Zone call frequency: count zones currently actively heating/cooling.
        # record_observation kept so in-memory anomaly tracking (the per-coordinator
        # anomaly sensor's active_anomalies / anomalies_today counters) continues
        # to work. store_event + activity_logger.log path SUPPRESSED per the
        # cardinality audit above — same pattern as v4.6.3.1 zone_occupied_count
        # and v4.6.3.3 census_count suppression.
        active_count = sum(
            1
            for z in self._zone_manager.zones.values()
            if z.hvac_action in ("cooling", "heating")
        )
        anomaly = self.anomaly_detector.record_observation(
            "zone_call_frequency", "house", float(active_count)
        )
        if anomaly:
            _LOGGER.debug(
                "HVAC zone_call_frequency in-memory anomaly only "
                "(persistence suppressed): active_zones=%d severity=%s z=%.2f",
                active_count, anomaly.severity.value, anomaly.z_score,
            )

        # Override frequency — per-cycle DELTA, not cumulative count.
        # v4.6.5.1 P1 (review B-M2 fix): pre-v4.6.5.1 this emitted the
        # cumulative total_overrides (resets at midnight, grows through day).
        # Late-day high values produced ADVISORY z-fires just from natural
        # accumulation. Emitting the per-cycle delta gives a stable-variance
        # signal: zero when no new overrides this cycle, positive int when
        # a zone got overridden. After midnight reset (total drops to 0)
        # we skip one cycle's observation to avoid recording a negative
        # delta artifact.
        total_overrides = sum(
            z.override_count_today for z in self._zone_manager.zones.values()
        )
        previous_total = self._last_total_overrides_observed
        # Always update the anchor before any return path so we re-seed on
        # restart, daily reset, or first cycle.
        self._last_total_overrides_observed = total_overrides

        if previous_total is None:
            # First observation post-init or post-reload — no delta possible.
            delta = 0
        else:
            delta = total_overrides - previous_total

        if delta < 0:
            # Daily reset just happened (total dropped from N to a smaller
            # value). Skip the observation to avoid polluting the baseline
            # with a negative artifact; resume next cycle.
            _LOGGER.debug(
                "HVAC override_frequency: midnight reset detected "
                "(total dropped from %d to %d) — skipping observation this cycle",
                previous_total, total_overrides,
            )
            return

        anomaly2 = self.anomaly_detector.record_observation(
            "override_frequency", "house", float(delta)
        )
        if anomaly2:
            try:
                from .anomaly_event import (  # noqa: PLC0415
                    AnomalyEvent,
                    AnomalySeverity as _NewSev,
                    AnomalyType,
                    build_context_json,
                    map_diag_severity,
                )
                _ctx2 = build_context_json(
                    source_signal="hvac_decision_cycle",
                    extra={
                        "delta_overrides": delta,
                        "total_overrides_today": total_overrides,
                    },
                )
                _event2 = AnomalyEvent(
                    coordinator="hvac",
                    type="hvac.override_frequency",
                    # v4.6.6 D1: 1:1 mapping via map_diag_severity preserves
                    # ADVISORY (z 2-3) and ALERT (z 3-4) as distinct DB values
                    # instead of collapsing both to WARNING.
                    severity=map_diag_severity(anomaly2.severity),
                    anomaly_type=AnomalyType.POINT_IN_TIME,
                    detected_at=anomaly2.timestamp.isoformat(),
                    payload=_ctx2,
                    observed_value=anomaly2.observed_value,
                    expected_mean=anomaly2.expected_mean,
                    expected_std=anomaly2.expected_std,
                    z_score=round(anomaly2.z_score, 3),
                    sample_size=anomaly2.sample_size,
                )
                await self.anomaly_detector.store_event(_event2)
                _LOGGER.info(
                    "HVAC override_frequency anomaly persisted: delta=%d total_today=%d z=%.2f",
                    delta, total_overrides, anomaly2.z_score,
                )
                _activity_logger2 = self.hass.data.get(DOMAIN, {}).get("activity_logger")
                if _activity_logger2:
                    await _activity_logger2.log(
                        coordinator="hvac",
                        action="anomaly",
                        description=(
                            f"HVAC override_frequency anomaly: delta={delta} "
                            f"total_today={total_overrides} z={anomaly2.z_score:.2f}"
                        ),
                        importance="notable",
                        details={
                            "type": "hvac.override_frequency",
                            "z_score": round(anomaly2.z_score, 3),
                            "delta_overrides": delta,
                            "total_overrides_today": total_overrides,
                        },
                    )
            except Exception:
                _LOGGER.debug("HVAC override_frequency anomaly persist failed", exc_info=True)

    def get_anomaly_status(self) -> str:
        """Return anomaly status string for sensor."""
        if self.anomaly_detector is None:
            return "not_configured"
        learning = self.anomaly_detector.get_learning_status()
        if hasattr(learning, "value") and learning.value in (
            "insufficient_data",
            "learning",
        ):
            return learning.value
        return self.anomaly_detector.get_worst_severity().value

    def get_compliance_summary(self) -> dict[str, Any]:
        """Return compliance summary for sensor."""
        zones = self._zone_manager.zones
        return {
            "zones_total": len(zones),
            "overrides_today": sum(
                z.override_count_today for z in zones.values()
            ),
        }

    async def _hydrate_last_reason_by_zone(self, db) -> None:
        """HVAC-DEMAND-KNOBS-AND-OBS-GAPS-1 D6-hydrate (v5.103.8).

        Populate `_last_reason_by_zone` from `ura_activity_log` rows
        with `action='preset_change'`, one row per zone (most recent).
        Only the S1 path writes this durable row today — non-S1 sites
        remain `unknown` after restart until the next write on their
        zone (planning §P3 scoped restart-safety).
        """
        import json  # noqa: PLC0415
        sql = (
            "SELECT zone, timestamp, details_json FROM ura_activity_log "
            "WHERE coordinator='hvac' AND action='preset_change' "
            "AND zone IS NOT NULL "
            "ORDER BY timestamp DESC"
        )
        seen: set[str] = set()
        try:
            async with db._db_read() as conn:
                async with conn.execute(sql) as cursor:
                    async for row in cursor:
                        zone_id = row[0]
                        if not zone_id or zone_id in seen:
                            continue
                        seen.add(zone_id)
                        ts_str = row[1]
                        details_raw = row[2] or "{}"
                        try:
                            details = json.loads(details_raw)
                        except Exception:  # noqa: BLE001
                            details = {}
                        reason = details.get("reason") or "unknown"
                        try:
                            ts = dt_util.parse_datetime(ts_str)
                        except Exception:  # noqa: BLE001
                            ts = None
                        if ts is None:
                            ts = dt_util.utcnow()
                        self._last_reason_by_zone[zone_id] = (reason, ts)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "hydrate_last_reason_by_zone: query failed",
                exc_info=True,
            )
            return
        if self._last_reason_by_zone:
            _LOGGER.info(
                "HVAC: hydrated preset-reason cache for %d zones (S1 path)",
                len(self._last_reason_by_zone),
            )

    def get_mode(self) -> str:
        """Return current HVAC operating mode for sensor."""
        return self._energy_constraint_mode

    def get_mode_attrs(self) -> dict[str, Any]:
        """Return mode sensor attributes."""
        attrs: dict[str, Any] = {
            "house_state": self._house_state,
            "energy_constraint_mode": self._energy_constraint_mode,
            "energy_offset": self._energy_offset,
            "season": self._preset_manager.current_season,
            "zone_count": self._zone_manager.zone_count,
            # v5.103.20 fast occupancy response counters (plan D2 sensor row).
            "fast_room_response_enabled": self._fast_path_enabled,
            "fast_entry_runs_today": self._fast_entry_runs_today.value,
            "fast_exit_runs_today": self._fast_exit_runs_today.value,
            "fast_writes_today": self._fast_writes_today.value,
            "fast_limited_today": self._fast_limited_today.value,
            "fast_tripped_zones": sorted(
                z for z in list(self._fp_tripped_until)
                if self._fast_path_zone_tripped(z)
            ),
            "quick_returns_today": dict(self._quick_returns_today_view()),
            "same_room_returns_today": dict(self._fp_same_room_returns_today),
            "skip_entry_wait_returns_today": dict(self._fp_skip_entry_wait_returns_today),
            "other_room_returns_today": dict(self._fp_other_room_returns_today),
            "transit_filtered_today": dict(
                getattr(self._zone_manager, "transit_filtered_today", {}) or {}
            ),
            "last_fast_edge_to_write_s": self._last_fast_edge_to_write_s,
            "last_evaluate": self._last_evaluate,
        }
        # HVAC-DEMAND-KNOBS-AND-OBS-GAPS-1 D7 (v5.103.8): energy-
        # constraint dwell observability. `since` is ISO UTC; the
        # sensor's RestoreEntity resume-if-same discipline persists
        # this across restarts.
        since = self._energy_constraint_mode_since
        if since is not None:
            attrs["energy_constraint_since"] = since.isoformat()
            try:
                delta = (dt_util.utcnow() - since).total_seconds()
                attrs["energy_constraint_duration_s"] = int(max(0, delta))
            except Exception:  # noqa: BLE001
                attrs["energy_constraint_duration_s"] = 0
        else:
            attrs["energy_constraint_since"] = None
            attrs["energy_constraint_duration_s"] = 0
        if self._energy_constraint:
            attrs["fan_assist"] = self._energy_constraint.fan_assist
            attrs["occupied_only"] = self._energy_constraint.occupied_only
        fan_status = self._fan_controller.get_fan_status()
        attrs["active_fans"] = fan_status.get("active_fan_rooms", 0)
        attrs["fan_assist_active"] = fan_status.get("fan_assist_active", False)
        cover_status = self._cover_controller.get_cover_status()
        attrs["covers_closed"] = cover_status.get("covers_closed", False)
        attrs["managed_covers"] = cover_status.get("managed_covers", 0)
        # v4.5.9.1: surface the new D6 diagnostic attributes from
        # CoverController.get_cover_status() — v4.5.9 added them to the
        # dict but this picker missed them, so the mode sensor only
        # carried the two pre-v4.5.9 keys. Now exposes the full
        # tilt/shade breakdown + the per-cover HVAC-closed set.
        attrs["managed_tilt_covers"] = cover_status.get("managed_tilt_covers", 0)
        attrs["managed_shade_covers"] = cover_status.get("managed_shade_covers", 0)
        attrs["hvac_closed_set"] = cover_status.get("hvac_closed_set", [])
        attrs["hvac_closed_count"] = cover_status.get("hvac_closed_count", 0)
        attrs["pre_cool_likelihood"] = self._predictor.pre_cool_likelihood
        attrs["comfort_risk"] = self._predictor.comfort_violation_risk
        attrs["pre_cool_active"] = self._predictor.pre_cool_active
        attrs["pre_cool_skip_reason"] = self._predictor.pre_cool_skip_reason
        attrs["pre_heat_active"] = self._predictor.pre_heat_active
        attrs["observation_mode"] = self._observation_mode
        attrs["arrester_state"] = self._override_arrester.get_arrester_state()
        attrs["arrester_enabled"] = self._override_arrester.enabled
        attrs["ac_reset_enabled"] = self._override_arrester.ac_reset_enabled
        attrs["fan_control_enabled"] = self._fan_control_enabled
        # v3.17.0: Zone Intelligence attributes
        attrs["pre_arrival_zones"] = list(self._pre_arrival_zones)
        # v5.7.1 — Energy Saver Pre-Cool attrs (replaces solar_banking
        # surface; no compat alias per planning §10 Q4 default). Surfaces
        # zones banked THIS cycle, the operator master-gate state, the
        # operator-configured offset + scope, and the effective scope
        # applied this cycle (for auto_pv_tiered visibility into whether
        # the unoccupied-zone expansion was active). See
        # PLANNING_v5.7.x_energy_pre_cool_unification.md (D1.4).
        energy_precool_zones = getattr(
            self._predictor, "_energy_precool_zones", set()
        )
        attrs["energy_precool_zones"] = list(energy_precool_zones)
        try:
            gate_fn = getattr(
                self._predictor, "_is_energy_precool_enabled", None,
            )
            attrs["energy_precool_enabled"] = (
                bool(gate_fn()) if callable(gate_fn) else True
            )
        except Exception:  # noqa: BLE001
            attrs["energy_precool_enabled"] = True
        try:
            off_fn = getattr(
                self._predictor, "_get_energy_precool_offset", None,
            )
            attrs["energy_precool_offset"] = (
                float(off_fn()) if callable(off_fn) else -2.0
            )
        except Exception:  # noqa: BLE001
            attrs["energy_precool_offset"] = -2.0
        try:
            scope_fn = getattr(
                self._predictor, "_get_energy_precool_scope", None,
            )
            attrs["energy_precool_scope"] = (
                str(scope_fn()) if callable(scope_fn) else "auto_pv_tiered"
            )
        except Exception:  # noqa: BLE001
            attrs["energy_precool_scope"] = "auto_pv_tiered"
        attrs["energy_precool_scope_effective"] = getattr(
            self._predictor, "_energy_precool_scope_effective", "n/a",
        )
        # HC pre-conditioning master gate (parent of weather pre-cool +
        # solar banking + pre-arrival + pre-heat). Mirrors the
        # banking_enabled attr so dashboards can distinguish "operator
        # OFF" (pre_conditioning_enabled=false) from "gate open but
        # conditions unmet" (pre_conditioning_enabled=true,
        # pre_conditioning_zones=[]). See
        # PLANNING_hc_precool_toggle_oc_observability.md (D1).
        try:
            pc_gate_fn = getattr(
                self._predictor, "_is_pre_conditioning_enabled", None,
            )
            attrs["pre_conditioning_enabled"] = (
                bool(pc_gate_fn()) if callable(pc_gate_fn) else True
            )
        except Exception:
            attrs["pre_conditioning_enabled"] = True
        vacancy_overrides = [
            z.zone_id for z in self._zone_manager.zones.values()
            if z.zone_presence_state == "away"
        ]
        attrs["vacancy_override_zones"] = vacancy_overrides
        attrs["person_zone_map"] = self._person_zone_map
        attrs["camera_zone_map"] = self._camera_zone_map
        attrs["vacancy_sweeps_today"] = self._vacancy_sweeps_today.value
        # v3.18.6: Pre-arrival diagnostics
        attrs["pre_arrival_enabled"] = self._pre_arrival_enabled
        attrs["pre_arrival_sources"] = self._pre_arrival_sources
        attrs["pre_arrival_active_zones"] = list(self._pre_arrival_zones)
        attrs["pre_arrival_triggers_today"] = self._pre_arrival_triggers_today.value
        attrs["last_pre_arrival_time"] = self._last_pre_arrival_time.isoformat() if self._last_pre_arrival_time else None
        attrs["last_pre_arrival_source"] = self._last_pre_arrival_source
        attrs["last_pre_arrival_person"] = self._last_pre_arrival_person
        # v4.6.11 D4.6: zone_limits — per-zone target temperature bounds.
        # get_zone_status_attrs() shape: see hvac_zones.py:502.
        zone_limits: dict[str, dict[str, float | None]] = {}
        try:
            for zone_id, zone in self._zone_manager.zones.items():
                zone_attrs = self._zone_manager.get_zone_status_attrs(zone_id, window_seconds=self.duty_cycle_window_seconds)
                friendly_name = zone_attrs.get("friendly_name", zone_id)
                zone_limits[friendly_name] = {
                    "cool_low": zone_attrs.get("target_temp_low"),
                    "heat_high": zone_attrs.get("target_temp_high"),
                }
        except Exception:
            pass
        attrs["zone_limits"] = zone_limits
        return attrs

    async def async_teardown(self) -> None:
        """Tear down HVAC Coordinator."""
        _LOGGER.info("HVAC Coordinator: tearing down")

        # v5.103.20 (plan §5.8): mark tearing down and release every fast-path
        # listener / exit timer / queue entry BEFORE the first `await` below
        # (the zone-state save), so no callback can fire mid-teardown.
        self._tearing_down = True
        self._teardown_fast_path()

        # Cancel periodic timer
        if self._decision_timer_unsub:
            self._decision_timer_unsub()
            self._decision_timer_unsub = None

        # Cancel any in-flight ad-hoc decision cycle tasks
        for task in list(self._pending_tasks):
            task.cancel()
        self._pending_tasks.clear()

        # HVAC W1-B B-H1 / D-M1: persist the zone-state snapshot (incl.
        # `__tao_state` / `__immune_holds`) BEFORE the arrester teardown
        # clears `_temp_arrester_override_active` — otherwise a reload
        # wiped the saved TAO and decision 46 could never restore it.
        try:
            if self._zone_manager:
                await self._zone_state_store.async_save(
                    self._build_zone_state_snapshot()
                )
                _LOGGER.info("HVAC: Zone state saved on shutdown")
        except Exception as e:
            _LOGGER.warning("HVAC: Failed to save zone state on shutdown: %s", e)

        # Tear down override arrester and cover controller
        self._override_arrester.teardown()
        self._cover_controller.teardown()

        self._cancel_listeners()

        # UNLOAD-SYMMETRY-TASK-HYGIENE-1: cancel any pending ComplianceTracker
        # ``schedule_check`` callbacks so they cannot fire against a
        # torn-down coordinator after unload/reload.
        try:
            _compliance = getattr(self, "_compliance", None)
            if _compliance is not None and hasattr(_compliance, "async_teardown"):
                _compliance.async_teardown()
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.debug(
                "HVAC: ComplianceTracker teardown raised (non-fatal)",
                exc_info=True,
            )

        # v3.18.2: zone state was saved ABOVE (before the arrester teardown).

        # Save anomaly baselines
        if self.anomaly_detector:
            try:
                await self.anomaly_detector.save_baselines()
            except Exception as e:
                _LOGGER.warning("HVAC: Could not save anomaly baselines: %s", e)

        _LOGGER.info("HVAC Coordinator: teardown complete")

    # ------------------------------------------------------------------
    # CARRIER-STALE-POLL-REFRESH-1 — D1 detection + D2 bounded reload + D3
    # trip-wire. Modeled shape-only after energy.py:_track_envoy_availability
    # and energy_write_verify.is_reserve_verifiable. NEVER reloads the URA
    # parent entry (feedback: parent_reload_watchdog).
    # ------------------------------------------------------------------
    def _carrier_require_blind_corroboration(self) -> bool:
        """Read the options-flow blind-corroboration toggle live."""
        from .hvac_const import (
            CONF_HVAC_CARRIER_STALE_REQUIRE_BLIND_CORROBORATION,
        )
        try:
            entries = self.hass.config_entries.async_entries(DOMAIN)
            for ce in entries:
                opts = getattr(ce, "options", None) or {}
                if CONF_HVAC_CARRIER_STALE_REQUIRE_BLIND_CORROBORATION in opts:
                    return bool(
                        opts[CONF_HVAC_CARRIER_STALE_REQUIRE_BLIND_CORROBORATION]
                    )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Carrier corroboration toggle read failed; using default",
                exc_info=True,
            )
        return self._carrier_require_blind_corroboration_default

    def _carrier_zone_span_kw(self, zone: Any) -> float | None:
        """Return the SPAN kW for this zone's mapped AC load sensor (or None).

        Fix-up round A2 (2026-09-09): REFUSE non-kW/W units. A cumulative
        `kWh` SPAN sensor reads as a huge number and produced permanent
        false corroboration -> healthy-entry reload every idle window
        (reload-storm class). Mirrors the unit-refusal prior art at
        hvac_override.py:1204-1207 (kwh/wh rejected as not-instant-kW)
        and sensor.py:12695-12702 (unknown unit refused). Blank unit is
        treated as unknown and refused too — the operator's real SPAN
        sensors carry `kW`.
        """
        entity_id = getattr(zone, "ac_load_sensor", "") or ""
        if not entity_id:
            return None
        try:
            st = self.hass.states.get(entity_id)
            if st is None or st.state in ("unknown", "unavailable", None, ""):
                return None
            val = float(st.state)
            unit_raw = st.attributes.get("unit_of_measurement") or ""
            unit = unit_raw.strip().lower()
            if unit in ("kwh", "wh", "watt hour", "watt-hour"):
                return None
            if unit in ("w", "watt", "watts"):
                return val / 1000.0
            if unit in ("kw", "kilowatt", "kilowatts"):
                return val
            return None
        except (ValueError, TypeError):
            return None
        except Exception:  # noqa: BLE001
            return None

    def _carrier_in_flight_ops_pending(self) -> str | None:
        """C-CRITICAL-1 fix-up (2026-09-09): return a reason string if any
        in-flight HVAC operation would be stranded by a reload, else None.

        A reload rebuilds the ha_carrier client — any setpoint/preset write
        already dispatched to the (now-absent) climate entity no-ops, AND
        the recovery record (in-flight nudge / ac_reset / excursion) is
        cleared — leaving the thermostat physically bumped while URA DB
        says "restored". A stale >=15 min zone can wait one 5-min tick.

        Predicates use the REAL prior art:
          - OverrideArrester._nudge_in_flight (hvac_override.py:323/3457)
          - OverrideArrester.has_active_ac_reset (hvac_override.py:1902)
          - hvac_excursion._rows (hvac_excursion.py:201) — active tokens
        """
        try:
            arr = getattr(self, "_override_arrester", None)
            if arr is not None:
                nif = getattr(arr, "_nudge_in_flight", None)
                if nif:
                    return f"nudge in flight ({len(nif)} zone(s))"
                try:
                    zones = list(self._zone_manager.zones.keys())
                except Exception:  # noqa: BLE001
                    zones = []
                for zid in zones:
                    try:
                        if arr.has_active_ac_reset(zid):
                            return f"ac_reset in flight (zone={zid})"
                    except Exception:  # noqa: BLE001
                        continue
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Carrier in-flight fence: arrester read failed", exc_info=True,
            )
        try:
            from . import hvac_excursion as _ex_mod  # noqa: PLC0415
            rows = getattr(_ex_mod, "_rows", None) or {}
            if rows:
                return f"excursion in flight ({len(rows)} row(s))"
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Carrier in-flight fence: excursion read failed", exc_info=True,
            )
        return None

    async def _check_carrier_freshness(self) -> None:
        """D1: detect stale Carrier climate entities; hand off to D2/D3 reload."""
        from .hvac_const import (
            CONF_HVAC_CARRIER_STALE_MAX_AGE_S,
            DEFAULT_HVAC_CARRIER_STALE_MAX_AGE_S,
            CARRIER_BLIND_CORROBORATION_KW_THRESHOLD,
        )
        max_age_s = float(DEFAULT_HVAC_CARRIER_STALE_MAX_AGE_S)
        try:
            entries = self.hass.config_entries.async_entries(DOMAIN)
            for ce in entries:
                opts = getattr(ce, "options", None) or {}
                if CONF_HVAC_CARRIER_STALE_MAX_AGE_S in opts:
                    max_age_s = float(opts[CONF_HVAC_CARRIER_STALE_MAX_AGE_S])
                    break
        except Exception:  # noqa: BLE001
            pass

        require_corroboration = self._carrier_require_blind_corroboration()
        now_utc = dt_util.utcnow()

        snapshot: dict[str, dict[str, Any]] = {}
        worst_age: float | None = None
        stale_count = 0
        any_reload_qualifier = False
        qualifiers_by_zone: list[str] = []

        try:
            zones = list(self._zone_manager.zones.items())
        except Exception:  # noqa: BLE001
            zones = []

        # A8 fix-up (2026-09-09): reuse _state_age_s semantics
        # (last_updated fallback, naive-tz refusal -> None).
        try:
            from .energy_battery import _state_age_s
        except Exception:  # noqa: BLE001
            _state_age_s = None

        for zone_id, zone in zones:
            climate = getattr(zone, "climate_entity", "") or ""
            row: dict[str, Any] = {
                "climate_entity": climate,
                "state": None,
                "age_s": None,
                "stale": False,
                "corroborated": False,
                "span_kw": None,
                "ac_load_sensor": getattr(zone, "ac_load_sensor", "") or "",
                "span_unreadable": False,  # A5 fix-up diagnostic
            }
            if not climate:
                snapshot[zone_id] = row
                continue
            try:
                st = self.hass.states.get(climate)
            except Exception:  # noqa: BLE001
                st = None
            # A4 fix-up (2026-09-09): surface unavailable zones in the
            # diagnostic snapshot rather than dropping them silently.
            if st is None:
                row["state"] = "missing"
                snapshot[zone_id] = row
                continue
            row["state"] = st.state
            if st.state in ("unavailable", "unknown"):
                snapshot[zone_id] = row
                continue
            age = None
            if _state_age_s is not None:
                try:
                    age = _state_age_s(st, stamp="last_reported")
                except Exception:  # noqa: BLE001
                    age = None
            if age is None:
                try:
                    last_reported = getattr(st, "last_reported", None)
                    if last_reported is None or getattr(
                        last_reported, "tzinfo", None,
                    ) is None:
                        snapshot[zone_id] = row
                        continue
                    age = (now_utc - last_reported).total_seconds()
                except Exception:  # noqa: BLE001
                    snapshot[zone_id] = row
                    continue
            row["age_s"] = age
            if worst_age is None or age > worst_age:
                worst_age = age
            if age <= max_age_s:
                snapshot[zone_id] = row
                continue
            row["stale"] = True
            stale_count += 1

            # Corroboration path
            span_kw = self._carrier_zone_span_kw(zone)
            row["span_kw"] = span_kw
            # A5 fix-up (2026-09-09): distinguishable diagnostic when a
            # configured SPAN sensor is unreadable (unknown unit / dead /
            # non-numeric). Previously degraded silently to age-only.
            if row["ac_load_sensor"] and span_kw is None:
                row["span_unreadable"] = True
            hvac_action = (st.attributes.get("hvac_action") or "").lower()
            blind_evidence = (
                hvac_action == "idle"
                and span_kw is not None
                and span_kw > CARRIER_BLIND_CORROBORATION_KW_THRESHOLD
            )
            row["corroborated"] = blind_evidence

            if require_corroboration:
                # Skip corroboration ONLY when zone has no SPAN sensor
                # (graceful degrade — age-only for that zone).
                if row["ac_load_sensor"] == "":
                    _LOGGER.debug(
                        "Carrier stale zone %s has no SPAN load sensor; "
                        "falling back to age-only qualifier",
                        zone_id,
                    )
                    any_reload_qualifier = True
                    qualifiers_by_zone.append(zone_id)
                elif blind_evidence:
                    any_reload_qualifier = True
                    qualifiers_by_zone.append(zone_id)
                # else: quiet-idle — do NOT reload
            else:
                any_reload_qualifier = True
                qualifiers_by_zone.append(zone_id)

            snapshot[zone_id] = row

        self._carrier_freshness_snapshot = snapshot
        self._carrier_worst_age_s = worst_age
        self._carrier_stale_zone_count = stale_count

        # D3 fix-up round (2026-09-09, B-HIGH-1/2/3, C-MED-1): TIME-based
        # settle window; counter scoped to QUALIFYING staleness inside the
        # window (never counts quiet-idle). Grace window >= cooldown so a
        # second reload is structurally reachable before the trip-wire.
        from .hvac_const import (
            CONF_HVAC_CARRIER_POST_RELOAD_SETTLE_S,
            DEFAULT_HVAC_CARRIER_POST_RELOAD_SETTLE_S,
        )
        settle_s = float(DEFAULT_HVAC_CARRIER_POST_RELOAD_SETTLE_S)
        try:
            for ce in self.hass.config_entries.async_entries(DOMAIN):
                opts = getattr(ce, "options", None) or {}
                if CONF_HVAC_CARRIER_POST_RELOAD_SETTLE_S in opts:
                    settle_s = float(
                        opts[CONF_HVAC_CARRIER_POST_RELOAD_SETTLE_S]
                    )
                    break
        except Exception:  # noqa: BLE001
            pass

        if self._last_carrier_reload_at is not None:
            since_reload = (
                now_utc - self._last_carrier_reload_at
            ).total_seconds()
            if since_reload > 2.0 * settle_s:
                # Window elapsed -> clear (was a permanent latch previously).
                self._carrier_stale_ticks_since_reload = 0
            elif qualifiers_by_zone:
                self._carrier_stale_ticks_since_reload += 1
            else:
                self._carrier_stale_ticks_since_reload = 0

        # C-CRITICAL-1 fix-up: in-flight fence BEFORE the reload call.
        in_flight_reason = self._carrier_in_flight_ops_pending()
        if any_reload_qualifier and in_flight_reason is not None:
            _LOGGER.info(
                "Carrier reload deferred: %s — waiting one tick",
                in_flight_reason,
            )
            if self._last_carrier_reload_at is not None:
                self._carrier_stale_ticks_since_reload = max(
                    0, self._carrier_stale_ticks_since_reload - 1,
                )
        elif any_reload_qualifier:
            await self._reload_ha_carrier_entry(qualifiers_by_zone)

        # D3 trip-wire (redesigned): TIME-based settle threshold.
        if (
            self._last_carrier_reload_at is not None
            and not self._carrier_reload_suppressed_today
            and qualifiers_by_zone
        ):
            since_reload = (
                now_utc - self._last_carrier_reload_at
            ).total_seconds()
            if since_reload >= settle_s:
                await self._trip_wire_carrier_reload_ineffective(
                    reason=(
                        f"still qualifying-stale {int(since_reload)}s after "
                        f"reload (settle={int(settle_s)}s, "
                        f"qualifying_zones={qualifiers_by_zone})"
                    ),
                )

        # C-HIGH-4 fix-up: stranded-stale age-only NM (once/day),
        # INDEPENDENT of the reload path. Surfaces genuinely stale
        # Carrier zones that can't be reloaded/corroborated.
        if stale_count > 0:
            try:
                today_iso = dt_util.now().date().isoformat()
            except Exception:  # noqa: BLE001
                today_iso = ""
            if today_iso and today_iso != self._carrier_stale_nm_date:
                self._carrier_stale_nm_date = today_iso
                stale_zones = [
                    zid for zid, r in snapshot.items() if r.get("stale")
                ]
                await self._nm_carrier_reload_note(
                    severity_low=True,
                    title="Carrier climate stale (age-only)",
                    message=(
                        f"{stale_count} zone(s) stale: {stale_zones}. "
                        f"worst_age_s={int(worst_age or 0)}. NM fires "
                        f"once per local day independent of reload path."
                    ),
                    hazard_type="carrier_stale_age_only",
                )

    async def _reload_ha_carrier_entry(self, qualifier_zones: list[str]) -> None:
        """D2: bounded reload of the single ha_carrier config entry.

        Guards (first-fail short-circuits):
          - kill-switch (cooldown_s == 0)
          - suppress-for-day (D3 already fired)
          - per-day cap
          - cooldown since last reload
          - per-entry asyncio.Lock (prevents overlap)
          - single-entry resolution (0 or 2+ -> NM + no reload)

        NEVER reloads the URA parent entry (safety-critical invariant).
        """
        from .hvac_const import (
            CONF_HVAC_CARRIER_RELOAD_COOLDOWN_S,
            DEFAULT_HVAC_CARRIER_RELOAD_COOLDOWN_S,
            CONF_HVAC_CARRIER_RELOAD_MAX_PER_DAY,
            DEFAULT_HVAC_CARRIER_RELOAD_MAX_PER_DAY,
            CARRIER_INTEGRATION_DOMAIN,
        )

        cooldown_s = DEFAULT_HVAC_CARRIER_RELOAD_COOLDOWN_S
        max_per_day = DEFAULT_HVAC_CARRIER_RELOAD_MAX_PER_DAY
        # B-LOW-3 fix-up (2026-09-09): consistent first-wins semantics
        # with sibling readers (break after we resolve options).
        try:
            for ce in self.hass.config_entries.async_entries(DOMAIN):
                opts = getattr(ce, "options", None) or {}
                found = False
                if CONF_HVAC_CARRIER_RELOAD_COOLDOWN_S in opts:
                    cooldown_s = int(
                        opts[CONF_HVAC_CARRIER_RELOAD_COOLDOWN_S]
                    )
                    found = True
                if CONF_HVAC_CARRIER_RELOAD_MAX_PER_DAY in opts:
                    max_per_day = int(
                        opts[CONF_HVAC_CARRIER_RELOAD_MAX_PER_DAY]
                    )
                    found = True
                if found:
                    break
        except Exception:  # noqa: BLE001
            pass

        # Kill-switch: cooldown 0 disables reload entirely
        if cooldown_s <= 0:
            _LOGGER.debug(
                "Carrier reload skipped: kill-switch active (cooldown_s=0)"
            )
            return
        # D3 suppress
        if self._carrier_reload_suppressed_today:
            _LOGGER.debug(
                "Carrier reload suppressed for the day (D3 trip-wire fired)"
            )
            return
        # Per-day cap
        if self._carrier_reloads_today.value >= max_per_day:
            _LOGGER.info(
                "Carrier reload cap hit (%d/day); suppressing for the day",
                max_per_day,
            )
            await self._trip_wire_carrier_reload_ineffective(
                reason=f"per-day cap reached ({max_per_day})",
            )
            return
        # Cooldown
        now_utc = dt_util.utcnow()
        if self._last_carrier_reload_at is not None:
            elapsed = (now_utc - self._last_carrier_reload_at).total_seconds()
            if elapsed < cooldown_s:
                _LOGGER.debug(
                    "Carrier reload skipped: cooldown %ds remaining "
                    "(cooldown=%ds, elapsed=%ds)",
                    int(cooldown_s - elapsed), cooldown_s, int(elapsed),
                )
                return
        if self._carrier_reload_lock.locked():
            _LOGGER.debug("Carrier reload skipped: another reload in flight")
            return

        async with self._carrier_reload_lock:
            # Resolve the single ha_carrier entry
            try:
                carrier_entries = self.hass.config_entries.async_entries(
                    CARRIER_INTEGRATION_DOMAIN
                )
            except Exception:  # noqa: BLE001
                carrier_entries = []
            if len(carrier_entries) != 1:
                _LOGGER.warning(
                    "Carrier reload skipped: found %d ha_carrier entries "
                    "(expected exactly 1); NM alerting operator",
                    len(carrier_entries),
                )
                await self._nm_carrier_reload_note(
                    severity_low=False,
                    title="Carrier reload skipped - ambiguous entry",
                    message=(
                        f"Found {len(carrier_entries)} ha_carrier config "
                        f"entries; refusing to reload. Expected exactly 1."
                    ),
                    hazard_type="carrier_reload_ambiguous",
                )
                return

            entry = carrier_entries[0]
            # SAFETY INVARIANT: never reload URA parent
            if getattr(entry, "domain", "") == DOMAIN:
                _LOGGER.error(
                    "Carrier reload aborted: resolved entry belongs to URA "
                    "domain (%s); refusing per parent_reload_watchdog rule",
                    DOMAIN,
                )
                return

            _LOGGER.info(
                "Carrier reload: qualifier_zones=%s cooldown=%ds count_today=%d",
                qualifier_zones,
                cooldown_s,
                self._carrier_reloads_today.value,
            )
            try:
                await self.hass.services.async_call(
                    "homeassistant",
                    "reload_config_entry",
                    {"entry_id": entry.entry_id},
                    blocking=False,
                )
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning(
                    "Carrier reload service call failed: %s", e, exc_info=True,
                )
                return

            self._last_carrier_reload_at = dt_util.utcnow()
            self._carrier_reloads_today.increment()
            self._carrier_stale_ticks_since_reload = 0

            # Diagnostic row into ura_activity_log (reuse existing DAO)
            try:
                activity_logger = self.hass.data.get(DOMAIN, {}).get(
                    "activity_logger"
                )
                if activity_logger:
                    self.hass.async_create_task(
                        activity_logger.log(
                            coordinator="hvac",
                            action="carrier_reload",
                            description=(
                                f"Reloaded ha_carrier entry "
                                f"(qualifier_zones={qualifier_zones}, "
                                f"count_today={self._carrier_reloads_today.value})"
                            ),
                            importance="notable",
                            details={
                                "entry_id": entry.entry_id,
                                "qualifier_zones": qualifier_zones,
                                "count_today": self._carrier_reloads_today.value,
                            },
                        )
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "Carrier reload activity_logger write failed", exc_info=True,
                )

            await self._nm_carrier_reload_note(
                severity_low=True,
                title="Carrier stale - reload issued",
                message=(
                    f"ha_carrier reloaded to clear stale climate state "
                    f"(zones={qualifier_zones}, count_today="
                    f"{self._carrier_reloads_today.value}/{max_per_day})."
                ),
                hazard_type="carrier_stale_reload",
            )

    async def _trip_wire_carrier_reload_ineffective(self, *, reason: str) -> None:
        """D3: reload was ineffective (or cap hit). Suppress + NM high."""
        if self._carrier_reload_suppressed_today:
            return
        self._carrier_reload_suppressed_today = True
        try:
            self._carrier_reload_suppress_date = (
                dt_util.now().date().isoformat()
            )
        except Exception:  # noqa: BLE001
            self._carrier_reload_suppress_date = ""
        _LOGGER.warning(
            "Carrier reload ineffective: %s; suppressing further reloads "
            "for the rest of the day",
            reason,
        )
        try:
            activity_logger = self.hass.data.get(DOMAIN, {}).get(
                "activity_logger"
            )
            if activity_logger:
                self.hass.async_create_task(
                    activity_logger.log(
                        coordinator="hvac",
                        action="carrier_reload_ineffective",
                        description=(
                            f"Carrier reload trip-wire fired: {reason}"
                        ),
                        importance="critical",
                        details={"reason": reason},
                    )
                )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Carrier trip-wire activity_logger write failed", exc_info=True,
            )
        await self._nm_carrier_reload_note(
            severity_low=False,
            title="Carrier reload ineffective",
            message=(
                f"Carrier reload trip-wire fired ({reason}). Further "
                f"reloads suppressed until the next local day. Manual "
                f"investigation recommended."
            ),
            hazard_type="carrier_reload_ineffective",
        )

    async def _nm_carrier_reload_note(
        self,
        *,
        severity_low: bool,
        title: str,
        message: str,
        hazard_type: str,
    ) -> None:
        """Fire an NM alert for carrier-reload lifecycle events."""
        try:
            nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
            if nm is None:
                return
            from .base import Severity
            sev = Severity.LOW if severity_low else Severity.HIGH
            await nm.async_notify(
                coordinator_id="hvac",
                severity=sev,
                title=title,
                message=message,
                hazard_type=hazard_type,
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("Carrier reload NM note failed: %s", e)
