"""HVAC Coordinator for Universal Room Automation.

Manages HVAC zones, presets, fans, covers, and energy constraint response.
Priority 30 (below Energy at 40).

v3.8.0-H1: Core + Zone Management + Preset + E6 Signal + Diagnostics Skeleton.
v3.17.0: Zone Intelligence — vacancy management, duty cycle, stale failsafe,
         person-to-zone pre-arrival, zone presence state machine.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from .base import BaseCoordinator, CoordinatorAction, Intent
from .hvac_const import (
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
from .hvac_override import OverrideArrester
from .hvac_predict import HVACPredictor
from .hvac_preset import PresetManager
from .hvac_setpoint import apply_setpoint_guards, emit_set_temperature
from .hvac_zones import ZoneManager
from .signals import (
    EnergyConstraint,
    SIGNAL_ENERGY_CONSTRAINT,
    SIGNAL_HOUSE_STATE_CHANGED,
    SIGNAL_PERSON_ARRIVING,
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
        compromise_minutes: int = 30,
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

        # v4.0.15: Fan control toggle
        self._fan_control_enabled: bool = fan_control_enabled

        # Energy constraint state
        self._energy_constraint: EnergyConstraint | None = None
        self._energy_constraint_mode: str = "normal"
        self._energy_offset: float = 0.0

        # House state
        self._house_state: str = ""
        # Fan-trust review A-L1 2026-06-11: per (zone_id, house_state)
        # one-shot INFO de-noise for night-trust suppression. Without
        # this the trust block fires ~12/hr/zone all night long. Cleared
        # whenever the house_state changes.
        self._night_trust_logged: set[tuple[str, str]] = set()
        self._night_trust_logged_state: str = ""

        # Decision cycle tracking
        self._last_evaluate: str = ""
        self._last_daily_reset: str = ""
        self._decision_timer_unsub = None
        self._pending_preset_change: bool = False

        # Observation mode — sensors run but no actions taken
        self._observation_mode: bool = False

        # v4.7.15 D6: HVAC consensus defer gate.
        # Master toggle (default ON). Operator can disable via
        # switch.ura_hvac_consensus_defer_gate for rollback without restart.
        # When ON, _apply_house_state_presets skips writes if signal_consensus
        # < 0.5 AND last house-state transition < 30 s ago.
        # v4.7.15 fix-up A5-H1: also implement asymmetric hysteresis — once
        # the gate engages, it stays engaged until consensus recovers above 0.7
        # (the "upper threshold"). This matches the README + plan spec and
        # prevents 0.5-line flap from turning the gate on/off within a single
        # consensus oscillation.
        self._defer_gate_enabled: bool = True
        self._d6_gate_engaged: bool = False  # asymmetric-hysteresis latch
        # Daily counter (reset by existing midnight-reset hook) — exposed on
        # the HVAC compliance sensor for operator visibility.
        self._d6_deferrals_today: int = 0

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
        self._person_zone_map: dict[str, list[str]] = person_zone_map or {}
        self._last_good_person_zone_map: dict[str, list[str]] = {}
        self._pre_arrival_zones: set[str] = set()
        self._pre_arrival_persons: dict[str, str] = {}  # zone_id -> person_entity
        self._pre_arrival_start: dict[str, Any] = {}  # zone_id -> datetime
        self._vacancy_sweeps_today: int = 0
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
        self._pre_arrival_sources: list[str] = ["geofence", "ble"]
        self._last_pre_arrival_time: Any = None
        self._last_pre_arrival_source: str = ""
        self._last_pre_arrival_person: str = ""
        self._pre_arrival_triggers_today: int = 0

        # v3.19.0: Camera zone map (diagnostic)
        self._camera_zone_map: dict[str, str] = {}

        # v3.18.2: Zone state persistence
        self._zone_state_store = Store(hass, 1, f"{DOMAIN}.hvac_zone_state")
        self._zone_state_save_counter: int = 0

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
        return self._vacancy_sweeps_today

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

        # v3.17.0 D3: Subscribe to person arriving signals
        self._unsub_listeners.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_PERSON_ARRIVING,
                self._handle_person_arriving,
            )
        )

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
        self._zone_manager.update_room_conditions()

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
        # v4.7.8 D8: cross-rule precedence — let OverrideArrester +
        # HVACPredictor see paused zones so they skip cleanly.
        self._override_arrester.set_egress_manager(self._egress_manager)
        self._predictor.set_egress_manager(self._egress_manager)

        # Start periodic decision cycle (every 5 minutes)
        self._decision_timer_unsub = async_track_time_interval(
            self.hass,
            self._async_decision_cycle,
            timedelta(minutes=5),
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
            from homeassistant.helpers.event import async_call_later

            @callback
            def _release_egress_gate(_now=None):
                try:
                    self._egress_manager.force_release_initial_restore_gate()
                except Exception:
                    _LOGGER.debug(
                        "HVAC: egress force-release failed (non-fatal)",
                        exc_info=True,
                    )

            async_call_later(self.hass, 60, _release_egress_gate)
        except Exception:
            _LOGGER.debug(
                "HVAC: scheduling egress gate release failed (non-fatal)",
                exc_info=True,
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

    async def _async_decision_cycle(self, _now=None) -> None:
        """Run the periodic HVAC decision cycle (every 5 minutes).

        Self-driven via async_track_time_interval — does NOT rely on the
        intent-based evaluate() path since no intents route to HVAC.
        """
        if not self._enabled:
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
        if self._decision_cycle_lock.locked():
            _LOGGER.debug(
                "HVAC decision cycle skipped — already running (re-entrancy guard)"
            )
            return
        async with self._decision_cycle_lock:
            await self._run_decision_cycle()

    async def _run_decision_cycle(self) -> None:
        """Inner decision cycle logic (called under lock)."""
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
            self._vacancy_sweeps_today = 0
            self._pre_arrival_triggers_today = 0

        # Update zone states
        self._zone_manager.update_all_zones()
        self._zone_manager.update_room_conditions()

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

        now_utc = dt_util.utcnow()

        # v3.17.0: Zone Intelligence features (guarded by toggle)
        if self._zone_intelligence_enabled:
            # D5: Accumulate zone runtime BEFORE presets (RC3 ordering)
            self._accumulate_zone_runtime(now_utc)
            # D3: Clear stale pre-arrival zones
            self._expire_pre_arrival_zones(now_utc)

        if not self._observation_mode:
            # Apply presets based on house state (includes D1 vacancy + D6 failsafe)
            await self._apply_house_state_presets()

            # Update override arrester energy state and check AC resets
            self._override_arrester.update_energy_state(
                self._energy_offset,
                self._energy_constraint_mode == "coast",
            )
            await self._override_arrester.check_ac_reset()

            # Fan and cover control
            if self._fan_control_enabled:
                await self._fan_controller.update(self._energy_constraint, self._house_state)
            else:
                await self._fan_controller.turn_off_all_managed()
            await self._cover_controller.update(self._energy_constraint)
        else:
            # Still update arrester state for diagnostics (no actions)
            self._override_arrester.update_energy_state(
                self._energy_offset,
                self._energy_constraint_mode == "coast",
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

        # Signal sensor updates
        async_dispatcher_send(self.hass, SIGNAL_HVAC_ENTITIES_UPDATE)

        self._last_evaluate = now.isoformat()

        # v3.18.2: Periodic zone state save (every 5 cycles = ~25 min)
        self._zone_state_save_counter += 1
        if self._zone_state_save_counter >= 5:
            self._zone_state_save_counter = 0
            try:
                snapshot = self._zone_manager.get_state_snapshot()
                snapshot["__person_zone_map"] = self._person_zone_map
                await self._zone_state_store.async_save(snapshot)
            except Exception as e:
                _LOGGER.warning("HVAC: Failed to save zone state: %s", e)

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

    async def _apply_house_state_presets(self) -> None:
        """Apply preset changes based on current house state.

        Includes D1 vacancy override, D5 duty cycle enforcement, D6 stale failsafe.
        Directly calls HA services (self-driven, not via CoordinatorManager actions).

        v4.7.15 D6: Asymmetric-hysteresis defer gate driven by signal_consensus.
        When the inputs disagree (consensus < 0.5) AND the last house-state
        transition was recent (< 30 s), skip this preset apply cycle entirely.
        Critical safety paths (CO2, fire, hazard) DO NOT go through this method,
        so they are inherently bypassed. Resume at consensus > 0.7 (the next
        cycle that crosses the upper hysteresis threshold writes presets normally).
        """
        if not self._house_state:
            return

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
                        self._d6_deferrals_today += 1
                        return
                else:
                    if consensus < 0.5 and secs_since_transition < 30:
                        _LOGGER.info(
                            "v4.7.15 D6: HVAC defer gate ENGAGED — "
                            "consensus=%.2f, secs_since_transition=%.0f",
                            consensus, secs_since_transition,
                        )
                        self._d6_gate_engaged = True
                        self._d6_deferrals_today += 1
                        return  # Skip this apply cycle — retry next tick.

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
        for zone_id, zone in list(self._zone_manager.zones.items()):
            if self._egress_manager.is_paused(zone_id):
                continue
            if (
                zone.hvac_mode != "heat_cool"
                and self._override_arrester._supports_heat_cool(zone.climate_entity)
                and not self._override_arrester.has_active_ac_reset(zone_id)
            ):
                self._override_arrester.suppress(zone.climate_entity)
                try:
                    await self.hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {
                            "entity_id": zone.climate_entity,
                            "hvac_mode": "heat_cool",
                        },
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
            return

        target_preset = self._preset_manager.get_preset_for_house_state(
            self._house_state
        )
        if target_preset is None:
            return

        now = dt_util.utcnow()
        energy_constrained = self._energy_constraint_mode in ("coast", "shed")
        grace_minutes = (
            self._vacancy_grace_constrained if energy_constrained
            else self._vacancy_grace
        )

        zi = self._zone_intelligence_enabled
        # snapshot: zones dict may be pruned by _handle_zm_zones_updated mid-await
        for zone_id, zone in list(self._zone_manager.zones.items()):
            # v4.7.8 D8: Skip preset apply for zones paused by EgressManager.
            # Preset restoration happens on resume; applying here would push
            # a preset to an off compressor and the restore would override it.
            if self._egress_manager.is_paused(zone_id):
                continue
            effective_preset = target_preset
            zone_vacant_past_grace = False

            # --- D1/D5/D6: Zone Intelligence overrides (gated by toggle) ---
            if zi:
                # D1: Per-zone vacancy override
                # Only override "home" preset — sleep/away/vacation are already correct
                zone_vacant_past_grace = (
                    not zone.any_room_occupied
                    and zone.last_occupied_time is not None
                    and (now - zone.last_occupied_time).total_seconds()
                    > grace_minutes * 60
                )

                if zone_vacant_past_grace and target_preset in ("home", "sleep"):
                    effective_preset = "away"

                    # Zone sweep: turn off lights + fans (once per vacancy cycle)
                    if not zone.vacancy_sweep_done and zone.vacancy_sweep_enabled:
                        await self._execute_vacancy_sweep(zone)
                        zone.vacancy_sweep_done = True
                        self._vacancy_sweeps_today += 1

                # D6: Stale occupancy failsafe (skip during sleep — RH4)
                # v3.22.2: Multi-source confidence check before declaring stale.
                # If 2+ independent sources confirm presence, reset the timer
                # instead of forcing away. Only treat as stale if a single
                # stuck sensor is the sole evidence.
                if (
                    zone.any_room_occupied
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
                        # Insufficient confirmation — likely stuck sensor
                        effective_preset = "away"
                        if not zone.vacancy_sweep_done and zone.vacancy_sweep_enabled:
                            await self._execute_vacancy_sweep(zone)
                            zone.vacancy_sweep_done = True
                            self._vacancy_sweeps_today += 1
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
                        ))

                # D5: Duty cycle enforcement (skip during sleep — RH4)
                if zone.runtime_exceeded and self._house_state != "sleep":
                    effective_preset = "away"

                # v4.2.2: Zone entry dwell — prevent preset flapping on brief transits
                # Only when house is already occupied and zone just became occupied.
                # Skip dwell for pre-arrival zones (pre-arrival already conditioned them).
                dwell_minutes = self._zone_entry_dwell
                if (
                    dwell_minutes > 0
                    and self._house_state in ("home_day", "home_evening", "home_night", "guest", "waking")
                    and zone.any_room_occupied
                    and zone.current_session_start is not None
                    and (now - zone.current_session_start).total_seconds() < dwell_minutes * 60
                    and zone_id not in self._pre_arrival_zones
                    and effective_preset != "away"  # Don't block vacancy overrides
                ):
                    continue  # Skip — dwell not met, keep current preset

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
            if effective_preset == "away" and self._house_state in FAN_TRUST_STATES:
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
                    if log_key in self._night_trust_logged:
                        _LOGGER.debug(
                            "HVAC: Suppressing %s preset flip -> away during %s "
                            "(zone_persons home: %s)",
                            zone.zone_name, self._house_state, home_persons,
                        )
                    else:
                        self._night_trust_logged.add(log_key)
                        _LOGGER.info(
                            "HVAC: Suppressing %s preset flip -> away during %s "
                            "(zone_persons home: %s) [subsequent suppressed]",
                            zone.zone_name, self._house_state, home_persons,
                        )
                    # Reason-ledger (Writer-B removal cycle 2026-08-06):
                    # log the suppression as a synthetic preset_change_suppressed
                    # row so the ledger shows WHY the coordinator didn't flip
                    # to away. Reason: night_trust_suppressed. Inputs echoed
                    # so mixed causes remain visible.
                    activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
                    if activity_logger:
                        self.hass.async_create_task(
                            activity_logger.log(
                                coordinator="hvac",
                                action="preset_change_suppressed",
                                description=(
                                    f"{zone.zone_name} preset flip -> away suppressed "
                                    f"during {self._house_state} (zone_persons home: {home_persons})"
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
                                    "runtime_exceeded": bool(zone.runtime_exceeded),
                                    "home_persons": list(home_persons),
                                },
                            )
                        )
                    continue

            # --- Determine if preset change is needed ---
            # Bypass should_change_preset() manual guard for vacancy (RH3 fix)
            if zi and (zone_vacant_past_grace or zone.runtime_exceeded) and effective_preset == "away":
                if zone.preset_mode == "away":
                    continue  # Already away
            elif not self._preset_manager.should_change_preset(
                zone.preset_mode, effective_preset
            ):
                continue

            # Reason-ledger derivation (Writer-B removal cycle 2026-08-06):
            # tag each preset_change with WHY the coordinator wrote it. Derived
            # from the actual decision branch that produced effective_preset,
            # not post-hoc inference. Approved vocabulary (per audit §reason-
            # ledger): house_state_transition | vacant_past_grace |
            # runtime_exceeded | night_trust_suppressed | manual_detected |
            # pre_arrival. Precedence for concurrent inputs:
            #   vacant_past_grace > runtime_exceeded > pre_arrival >
            #   house_state_transition.
            # Both underlying booleans are recorded in details so mixed causes
            # remain visible even though `reason` is single-valued.
            if effective_preset == "away" and zone_vacant_past_grace:
                preset_change_reason = "vacant_past_grace"
            elif effective_preset == "away" and zone.runtime_exceeded:
                preset_change_reason = "runtime_exceeded"
            elif zone_id in self._pre_arrival_zones:
                preset_change_reason = "pre_arrival"
            else:
                preset_change_reason = "house_state_transition"

            # Suppress arrester for URA-initiated changes
            if self._override_arrester:
                self._override_arrester.suppress(zone.climate_entity)

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
                await self.hass.services.async_call(
                    "climate",
                    "set_preset_mode",
                    {
                        "entity_id": zone.climate_entity,
                        "preset_mode": effective_preset,
                    },
                    blocking=False,
                )
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
                activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
                if activity_logger:
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
                                "runtime_exceeded": bool(zone.runtime_exceeded),
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
                            "runtime_exceeded": zone.runtime_exceeded,
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
        if not self._observation_mode:
            await self._async_apply_preset_overrides()

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
                zone_overrides = all_overrides.get(zone_id, [])

                # Get baseline from preset manager
                baseline = self._preset_manager.get_seasonal_setpoints(target_preset)
                if baseline is None:
                    continue
                baseline_cool, _baseline_heat = baseline

                # Determine effective baseline (cool_low=baseline_cool - MIN_DEADBAND, cool_high=baseline_cool)
                # seasonal setpoints return (cool_setpoint, heat_setpoint) — cool is the high
                baseline_low = baseline_cool - 7.0  # standard 7°F spread from SEASONAL_DEFAULTS
                baseline_high = baseline_cool

                # Resolve override for this zone + preset
                active = engine.get_active_overrides(
                    zone_id, target_preset, self._house_state, master_enabled, zone_overrides
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

                # Throttle: skip if resolved range matches last emitted
                last = self._last_emitted_range.get(zone_id)
                resolved_pair = (emit_low, emit_high)
                if last == resolved_pair:
                    continue

                # Suppress arrester so set_temperature isn't flagged as manual override
                if self._override_arrester:
                    self._override_arrester.suppress(zone.climate_entity, kind="temp")  # v5.36.2 H6: B1 completeness

                try:
                    await emit_set_temperature(
                        self.hass,
                        zone.climate_entity,
                        target_temp_low=resolved.cool_low,
                        target_temp_high=resolved.cool_high,
                        freeze_active=self._freeze_active,
                        blocking=False,
                    )
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

        # Trigger immediate decision cycle
        task = self.hass.async_create_task(self._async_decision_cycle())
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    @callback
    def _handle_energy_constraint(self, constraint: EnergyConstraint) -> None:
        """Handle energy constraint signal from Energy Coordinator."""
        old_mode = self._energy_constraint_mode

        self._energy_constraint = constraint
        self._energy_constraint_mode = constraint.mode
        self._energy_offset = constraint.setpoint_offset

        if old_mode != constraint.mode:
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
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "HVAC: in-memory zone prune failed for %r", deleted_name,
                exc_info=True,
            )
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
                    if zid == "__person_zone_map":
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
        """
        from ..const import CONF_FANS

        # snapshot: zones dict may be pruned by _handle_zm_zones_updated mid-await
        for zone_id, zone in list(self._zone_manager.zones.items()):
            for room_name in zone.rooms:
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
                        try:
                            domain = fan_entity.split(".")[0]
                            await self.hass.services.async_call(
                                domain, "turn_off",
                                {"entity_id": fan_entity}, blocking=False,
                            )
                            _LOGGER.info("HVAC: Safety stop fan %s", fan_entity)
                        except Exception:  # noqa: BLE001
                            _LOGGER.warning(
                                "HVAC: Failed to stop fan %s (safety)", fan_entity
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

        from ..const import CONF_LIGHTS, CONF_FANS

        swept_count = 0
        for room_name in zone.rooms:
            coordinator = self._get_room_coordinator(room_name)
            if coordinator is None:
                continue
            config = {
                **coordinator.config_entry.data,
                **coordinator.config_entry.options,
            }

            lights = config.get(CONF_LIGHTS, [])
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

            for entity_id in fans:
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

        _LOGGER.info(
            "HVAC: Vacancy sweep for zone %s — swept %d entities",
            zone.zone_name, swept_count,
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

        for zone in self._zone_manager.zones.values():
            # Initialize window
            if zone.window_start is None:
                zone.window_start = now
                zone.runtime_seconds_this_window = 0.0
                zone.runtime_exceeded = False

            # Check window expiry → reset
            if (now - zone.window_start).total_seconds() >= DUTY_CYCLE_WINDOW_SECONDS:
                zone.window_start = now
                zone.runtime_seconds_this_window = 0.0
                zone.runtime_exceeded = False

            # Accumulate if actively heating/cooling using actual elapsed time
            if zone.hvac_action in ("heating", "cooling") and elapsed > 0:
                zone.runtime_seconds_this_window += elapsed

            # Check duty cycle
            mode = self._energy_constraint_mode
            if mode == "shed":
                max_seconds = DUTY_CYCLE_WINDOW_SECONDS * DUTY_CYCLE_SHED
            elif mode == "coast":
                max_seconds = DUTY_CYCLE_WINDOW_SECONDS * DUTY_CYCLE_COAST
            else:
                continue  # No limit in normal mode

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
        for zone_id in preferred_zones:
            if zone_id in self._zone_manager.zones:
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
        self._pre_arrival_triggers_today += 1

        # Trigger immediate decision cycle
        task = self.hass.async_create_task(self._async_decision_cycle())
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    def _expire_pre_arrival_zones(self, now: Any) -> None:
        """Clear stale pre-arrival zones (person didn't show up within timeout).

        When a pre-arrival zone is cleared due to timeout (not occupancy),
        turn off fans that were activated as comfort bridge.
        """
        timeout = timedelta(minutes=PRE_ARRIVAL_TIMEOUT_MINUTES)
        zones_to_defan: list = []
        for zone_id in list(self._pre_arrival_zones):
            # Clear if zone is now occupied (person arrived — fans managed by fan controller)
            zone = self._zone_manager.zones.get(zone_id)
            if zone and zone.any_room_occupied:
                self._pre_arrival_zones.discard(zone_id)
                self._pre_arrival_start.pop(zone_id, None)
                self._pre_arrival_persons.pop(zone_id, None)
                _LOGGER.info("HVAC: Pre-arrival cleared for zone %s (occupied)", zone_id)
                continue

            # Clear if timeout exceeded — also turn off pre-arrival fans
            start = self._pre_arrival_start.get(zone_id)
            if start and (now - start) > timeout:
                self._pre_arrival_zones.discard(zone_id)
                self._pre_arrival_start.pop(zone_id, None)
                self._pre_arrival_persons.pop(zone_id, None)
                if zone:
                    zones_to_defan.append(zone)
                _LOGGER.info("HVAC: Pre-arrival timeout for zone %s", zone_id)

        # Turn off fans for timed-out pre-arrival zones (best-effort)
        for zone in zones_to_defan:
            self.hass.async_create_task(self._deactivate_zone_fans(zone))

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
                zone.zone_presence_state = "runtime_limited"
            elif zone_id in self._pre_arrival_zones:
                zone.zone_presence_state = "pre_arrival"
            elif zone_id in pre_conditioning_zones:
                zone.zone_presence_state = "pre_conditioning"
            elif zone.any_room_occupied:
                zone.zone_presence_state = "occupied"
            elif (
                zone.last_occupied_time is not None
                and (now - zone.last_occupied_time).total_seconds()
                <= grace_minutes * 60
            ):
                zone.zone_presence_state = "vacant"
            else:
                zone.zone_presence_state = "away"

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
        - short_cycle_rate: defined in HVAC_METRICS but never recorded via
          record_observation (no call site exists). SUPPRESSED_FROM_PERSISTENCE —
          metric is silent; z-score detection never fires for it.
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
            "last_evaluate": self._last_evaluate,
        }
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
        attrs["vacancy_sweeps_today"] = self._vacancy_sweeps_today
        # v3.18.6: Pre-arrival diagnostics
        attrs["pre_arrival_enabled"] = self._pre_arrival_enabled
        attrs["pre_arrival_sources"] = self._pre_arrival_sources
        attrs["pre_arrival_active_zones"] = list(self._pre_arrival_zones)
        attrs["pre_arrival_triggers_today"] = self._pre_arrival_triggers_today
        attrs["last_pre_arrival_time"] = self._last_pre_arrival_time.isoformat() if self._last_pre_arrival_time else None
        attrs["last_pre_arrival_source"] = self._last_pre_arrival_source
        attrs["last_pre_arrival_person"] = self._last_pre_arrival_person
        # v4.6.11 D4.6: zone_limits — per-zone target temperature bounds.
        # get_zone_status_attrs() shape: see hvac_zones.py:502.
        zone_limits: dict[str, dict[str, float | None]] = {}
        try:
            for zone_id, zone in self._zone_manager.zones.items():
                zone_attrs = self._zone_manager.get_zone_status_attrs(zone_id)
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

        # Cancel periodic timer
        if self._decision_timer_unsub:
            self._decision_timer_unsub()
            self._decision_timer_unsub = None

        # Cancel any in-flight ad-hoc decision cycle tasks
        for task in list(self._pending_tasks):
            task.cancel()
        self._pending_tasks.clear()

        # Tear down override arrester and cover controller
        self._override_arrester.teardown()
        self._cover_controller.teardown()

        self._cancel_listeners()

        # v3.18.2: Save zone state on shutdown
        try:
            if self._zone_manager:
                snapshot = self._zone_manager.get_state_snapshot()
                snapshot["__person_zone_map"] = self._person_zone_map
                await self._zone_state_store.async_save(snapshot)
                _LOGGER.info("HVAC: Zone state saved on shutdown")
        except Exception as e:
            _LOGGER.warning("HVAC: Failed to save zone state on shutdown: %s", e)

        # Save anomaly baselines
        if self.anomaly_detector:
            try:
                await self.anomaly_detector.save_baselines()
            except Exception as e:
                _LOGGER.warning("HVAC: Could not save anomaly baselines: %s", e)

        _LOGGER.info("HVAC Coordinator: teardown complete")
