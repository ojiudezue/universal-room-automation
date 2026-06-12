"""Cover Controller for HVAC Coordinator.

Manages common area blinds for solar gain reduction.
Closes south/west facing covers during peak solar hours in warm months
when outdoor temperature is high.

v3.8.4-H3: Initial implementation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_COVERS,
    CONF_COVER_HVAC_MANAGED,
    CONF_COVER_TYPE,
    CONF_ENTRY_TYPE,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_ROOM_NAME,
    COVER_TYPE_SHADE,
    COVER_TYPE_TILT,
    DOMAIN,
    ENTRY_TYPE_ROOM,
    STATE_OCCUPIED,
    STATE_TEMPERATURE,
)

# Cover supported_features bitmask values (per HA cover entity spec).
# Used in the v4.5.9 three-tier cover_type resolution when a cover lacks
# explicit per-room CONF_COVER_TYPE — auto-detect tilt support from the
# entity's supported_features bitmask.
_COVER_FEATURE_OPEN_TILT = 128
_COVER_FEATURE_CLOSE_TILT = 256
_COVER_FEATURE_SET_TILT_POSITION = 64
_COVER_FEATURE_TILT_BITS = (
    _COVER_FEATURE_OPEN_TILT
    | _COVER_FEATURE_CLOSE_TILT
    | _COVER_FEATURE_SET_TILT_POSITION
)

# v4.5.9: occupancy-aware close threshold. If a room is occupied, only close
# its covers when the room temp is at least this many degrees above the
# zone's cooling setpoint. Avoids ruining a sunny afternoon read in a room
# that's still comfortable.
OCCUPIED_CLOSE_TEMP_DELTA: float = 2.0  # °F
from .hvac_const import (
    CONF_HVAC_COVER_ENTITIES,
    COVER_CLOSE_TEMP,
    COVER_COMMAND_WINDOW_SECONDS,
    COVER_MANUAL_OVERRIDE_HOURS,
    COVER_OPEN_TEMP,
    COVER_SOLAR_HOUR_END,
    COVER_SOLAR_HOUR_START,
    COVER_SOLAR_MONTHS,
)
from .hvac_zones import ZoneManager
from .signals import EnergyConstraint

_LOGGER = logging.getLogger(__name__)


@dataclass
class ManagedCover:
    """Tracks state for a single managed cover.

    v4.5.9: cover_type added (shade vs tilt) for tilt-aware dispatch in
    `_command_close_one`/`_command_open_one`. owning_room_name added so
    the controller can consult per-room intent before deciding to act.
    """

    entity_id: str
    cover_type: str = COVER_TYPE_SHADE   # "shade" | "tilt"
    owning_room_name: str = ""           # Room that owns this cover (empty for CM-level explicit covers)
    last_command_time: str = ""          # ISO timestamp of last command we sent
    manual_override_until: str = ""      # ISO timestamp when override expires


class CoverController:
    """Manages common area covers for solar gain reduction.

    v3.8.4: Closes covers during peak solar hours (13-18) in Apr-Oct when hot.
    Respects manual overrides with 2-hour backoff.

    v4.5.9 changes:
      - Tilt-aware dispatch (closes Bug Class #33 third hit). Venetian
        blinds get cover.{open,close}_cover_tilt instead of position
        commands; the "already in target" check reads tilt_position
        with the same 5/95 thresholds the verify path uses.
      - Per-cover closed-set (`_hvac_closed: set[str]`) replaces the
        single `_covers_closed: bool`. Only covers HVAC explicitly
        closed get reopened at end-of-window — no more bulk open of
        every discovered cover.
      - Per-room intent gate: a cover whose owning room's
        CONF_COVER_OPEN_MODE says "not currently intended open"
        (e.g. mode=none, or mode=at_time outside window) is skipped.
        HVAC doesn't override the room's own cover policy.
      - Per-room HVAC opt-out (`CONF_COVER_HVAC_MANAGED=False`)
        excludes a room's covers from discovery entirely.
      - Occupancy-aware skip: occupied rooms only get covers closed
        when temp is meaningfully above setpoint.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        zone_manager: ZoneManager,
        occupied_close_delta: float = OCCUPIED_CLOSE_TEMP_DELTA,
        # v4.5.10: 5 new tunables + master enable
        solar_gain_enabled: bool = True,
        cover_close_temp: float = COVER_CLOSE_TEMP,
        cover_open_temp: float = COVER_OPEN_TEMP,
        cover_override_hours: float = COVER_MANUAL_OVERRIDE_HOURS,
        solar_start_hour: int = COVER_SOLAR_HOUR_START,
        solar_end_hour: int = COVER_SOLAR_HOUR_END,
    ) -> None:
        """Initialize cover controller.

        v4.5.9.2: occupied_close_delta accepted as constructor arg
        (was hardcoded module constant). Wired through from
        HVACCoordinator → CM-level CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA.

        v4.5.10: master toggle (solar_gain_enabled) + 5 additional
        tunables now configurable. Module constants stay as constructor
        defaults so existing test fixtures work unchanged. URA mirror
        pattern: kwargs are install-time seeds; the eventual Number /
        Switch entities are the runtime source of truth (they write to
        these instance attrs directly).
        """
        self.hass = hass
        self._zone_manager = zone_manager
        self._covers: dict[str, ManagedCover] = {}
        # v4.5.9: per-cover tracking. Set of entity IDs HVAC explicitly
        # closed in the current solar window. Used by the open-after-solar
        # branch to scope reopens to ONLY what HVAC closed (not every cover
        # the controller manages).
        self._hvac_closed: set[str] = set()
        # Cycle EC/HC reboot pickup — D2 #15. See update() for rationale.
        # v4.5.9.2: per-house occupancy-aware close threshold (configurable)
        self._occupied_close_delta: float = float(occupied_close_delta)
        # v4.5.10: master toggle + 5 tunables
        self._solar_gain_enabled: bool = bool(solar_gain_enabled)
        self._cover_close_temp: float = float(cover_close_temp)
        self._cover_open_temp: float = float(cover_open_temp)
        self._cover_override_hours: float = float(cover_override_hours)
        self._solar_start_hour: int = int(solar_start_hour)
        self._solar_end_hour: int = int(solar_end_hour)
        self._state_listener_unsub: CALLBACK_TYPE | None = None
        self._outdoor_temp_entity: str = ""
        # Fix-up pass (B-LOW-2): declare reboot-pickup one-shot flag here
        # rather than relying on getattr default. hvac_predict's lazy
        # pattern was justified by a test-window __init__ constraint;
        # this controller has no such constraint, so declare explicitly.
        self._reboot_pickup_done: bool = False

    def discover_covers(self) -> int:
        """Discover cover entities for solar gain management.

        Sources (in this order — room-derived takes precedence on cover_type):
        1. Room covers from HVAC zone rooms (so cover_type can be read from
           the room's CONF_COVER_TYPE) — also respects per-room
           CONF_COVER_HVAC_MANAGED opt-out (default True).
        2. Coordinator Manager explicit covers from CONF_HVAC_COVER_ENTITIES
           (covers not already discovered via a room).

        Excludes covers with device_class 'garage'.

        v4.5.9: cover_type three-tier resolution:
            - Room-derived (preferred): read from owning room's CONF_COVER_TYPE
            - Auto-detect: read entity's supported_features bitmask for tilt
            - Default: "shade"

        Returns count of managed covers.
        """
        self._covers.clear()
        # v4.5.9: clear closed-set on rediscovery — stale entries can't survive
        # a config change. Open-after-solar will gracefully no-op if it had
        # been holding entries.
        self._hvac_closed.clear()

        # Find outdoor temp sensor from room entries (house-level config)
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            entry_type = entry.data.get(CONF_ENTRY_TYPE, "")
            if entry_type == ENTRY_TYPE_ROOM:
                continue  # Skip room entries
            merged = {**entry.data, **entry.options}
            sensor = merged.get(CONF_OUTSIDE_TEMP_SENSOR, "")
            if sensor:
                self._outdoor_temp_entity = sensor
                break

        # Map of room name → entry's zone_id, for HVAC-zone membership check
        room_to_zone: dict[str, str] = {}
        for zone_id, zone in self._zone_manager.zones.items():
            for room_name in zone.rooms:
                room_to_zone[room_name] = zone_id

        # === Phase 1: Room-derived covers (preferred — cover_type known) ===
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            room_name = entry.data.get(CONF_ROOM_NAME, "")
            if not room_name or room_name not in room_to_zone:
                continue

            merged = {**entry.data, **entry.options}

            # v4.5.9: per-room HVAC opt-out. Default True preserves prior
            # behavior. Setting to False excludes the room's covers from
            # HVAC management entirely (per-room automation still runs).
            if not merged.get(CONF_COVER_HVAC_MANAGED, True):
                _LOGGER.debug(
                    "HVAC Covers: skipping room %s (cover_hvac_managed=False)",
                    room_name,
                )
                continue

            room_cover_type = merged.get(CONF_COVER_TYPE, COVER_TYPE_SHADE)
            covers = merged.get(CONF_COVERS, [])
            if isinstance(covers, str):
                covers = [covers]
            for entity_id in covers:
                if not entity_id or entity_id in self._covers:
                    continue
                if self._is_garage_cover(entity_id):
                    continue
                # Resolved cover_type via room. If the room's cover_type
                # is somehow unset/invalid, fall through to auto-detect
                # in the resolver.
                resolved = self._resolve_cover_type(entity_id, room_cover_type)
                self._covers[entity_id] = ManagedCover(
                    entity_id=entity_id,
                    cover_type=resolved,
                    owning_room_name=room_name,
                )

        # === Phase 2: CM-level explicit covers (no room → auto-detect type) ===
        from ..const import ENTRY_TYPE_COORDINATOR_MANAGER
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COORDINATOR_MANAGER:
                continue
            merged = {**entry.data, **entry.options}
            cover_list = merged.get(CONF_HVAC_COVER_ENTITIES, [])
            if isinstance(cover_list, str):
                cover_list = [cover_list]
            for entity_id in cover_list:
                if not entity_id or entity_id in self._covers:
                    continue
                if self._is_garage_cover(entity_id):
                    continue
                # No owning room → use feature-bitmask auto-detect; default shade
                resolved = self._resolve_cover_type(entity_id, room_cover_type=None)
                self._covers[entity_id] = ManagedCover(
                    entity_id=entity_id,
                    cover_type=resolved,
                    owning_room_name="",
                )

        n_tilt = sum(1 for c in self._covers.values() if c.cover_type == COVER_TYPE_TILT)
        _LOGGER.info(
            "HVAC Covers: managing %d covers (%d tilt, %d shade)",
            len(self._covers), n_tilt, len(self._covers) - n_tilt,
        )
        return len(self._covers)

    def _resolve_cover_type(
        self, entity_id: str, room_cover_type: str | None,
    ) -> str:
        """v4.5.9: Three-tier cover_type resolution.

        1. If room declares cover_type explicitly (shade or tilt), trust it.
        2. Otherwise auto-detect via entity's supported_features bitmask.
        3. Default to shade (safe — preserves pre-v4.5.9 dispatch).
        """
        if room_cover_type in (COVER_TYPE_SHADE, COVER_TYPE_TILT):
            return room_cover_type
        # Auto-detect from entity attributes
        state = self.hass.states.get(entity_id)
        if state is not None:
            try:
                features = int(state.attributes.get("supported_features", 0))
            except (TypeError, ValueError):
                features = 0
            has_tilt_bits = bool(features & _COVER_FEATURE_TILT_BITS)
            # Also require current_tilt_position to be exposed — some
            # integrations advertise tilt support but don't actually
            # report tilt position, in which case the verify path can't
            # confirm tilt actions.
            tilt_pos_present = "current_tilt_position" in state.attributes
            if has_tilt_bits and tilt_pos_present:
                return COVER_TYPE_TILT
        return COVER_TYPE_SHADE

    def setup_listeners(self) -> None:
        """Subscribe to cover state changes for manual override detection."""
        if not self._covers:
            return

        entity_ids = list(self._covers.keys())
        self._state_listener_unsub = async_track_state_change_event(
            self.hass, entity_ids, self._handle_cover_state_change
        )
        _LOGGER.info(
            "HVAC Covers: watching %d covers for manual overrides",
            len(entity_ids),
        )

    def teardown(self) -> None:
        """Cancel state listeners."""
        if self._state_listener_unsub:
            self._state_listener_unsub()
            self._state_listener_unsub = None

    def _reboot_pickup_seed_closed_set(
        self, month: int, hour: int, outdoor_temp: float,
    ) -> None:
        """Cycle EC/HC reboot pickup — D2 #15 (fix-up pass: B-MED-2/3 fixes).

        On the FIRST eval after process startup: if we are INSIDE the solar
        window AND the close-hold hysteresis condition holds (mirrors the
        hold branch's `outdoor_temp > _cover_open_temp` band), seed
        ``_hvac_closed`` with any cover whose current position is below 30
        (closed-ish). This re-establishes the membership claim that the
        RAM-only set lost across the restart, so the post-window open phase
        will reopen covers HVAC closed pre-reboot. Bounded — runs exactly
        once per process lifetime via ``_reboot_pickup_done``.

        B-MED-3: previously gated on ``>= _cover_close_temp``; live covers
        legitimately stay HVAC-closed through the hysteresis band
        (`open_temp < temp <= close_temp`), so the strict gate missed the
        original #15 failure shape. Now mirrors the hold gate.

        B-MED-2: previously adopted ANY cover at position <= 30, including
        ones the operator manually closed pre-reboot — which would then be
        auto-reopened at window end. The RAM-only ``manual_override_until``
        ledger is empty post-boot, so we cannot tell adopted-by-URA from
        operator-closed at seed time. Defensive fix: stamp every adopted
        cover with an ``_cover_override_hours``-equivalent grace so the
        first open-phase tick that would have reopened it instead drops
        it from the set (matching the operator-closed-mid-window path).
        Operator can still let URA reopen them by waiting out the grace
        or toggling the master switch.
        """
        in_solar_window = (
            month in COVER_SOLAR_MONTHS
            and self._solar_start_hour <= hour < self._solar_end_hour
        )
        # B-MED-3: align with hold gate. Hold condition keeps closed when
        # `outdoor_temp > _cover_open_temp` after the initial close at
        # `>= _cover_close_temp`. Seed mirrors that band so the
        # hysteresis-band reboot case isn't stranded.
        if not (in_solar_window and outdoor_temp > self._cover_open_temp):
            return
        seeded = 0
        # B-MED-2 grace stamp — far enough in the future that the first
        # open-phase tick treats the cover as "operator override active"
        # and drops it from the set without commanding it open. Uses the
        # configured cover override hours so this respects the same
        # operator-tunable window the live override path uses.
        from homeassistant.util import dt as dt_util
        grace_end = (
            dt_util.now() + timedelta(hours=self._cover_override_hours)
        ).isoformat()
        for entity_id, cover in self._covers.items():
            try:
                st = self.hass.states.get(entity_id)
                if st is None:
                    continue
                pos = st.attributes.get("current_position")
                if pos is None:
                    continue
                if int(pos) <= 30:
                    self._hvac_closed.add(entity_id)
                    # Conservative B-MED-2 stamp — only the seed path
                    # leaves this so live close paths still emit overrides
                    # via _handle_cover_state_change as before.
                    if not cover.manual_override_until:
                        cover.manual_override_until = grace_end
                    seeded += 1
            except (TypeError, ValueError):
                continue
        if seeded:
            _LOGGER.info(
                "HVAC Covers reboot-pickup: re-seeded %d covers as "
                "HVAC-closed (in solar window, hysteresis band; "
                "stamped operator-override grace to avoid clobbering "
                "any operator-closed covers)",
                seeded,
            )

    async def update(self, energy_constraint: EnergyConstraint | None) -> None:
        """Run cover control logic.

        Called from the HVAC decision cycle every 5 minutes.

        v4.5.9: per-cover decisions (was bulk close-all / open-all).
        Each close decision passes through intent + occupancy gates;
        open is scoped to ONLY covers HVAC explicitly closed (the
        `_hvac_closed` set).

        v4.5.10: master enable check (early-return). Tunable thresholds
        and hours read from instance attrs (live — Number/Switch entity
        edits take effect on next tick without reload).
        """
        # v4.5.10: master switch — early return if disabled
        if not self._solar_gain_enabled:
            return

        if not self._covers:
            return

        now = dt_util.now()
        month = now.month
        hour = now.hour

        # Get outdoor temperature
        outdoor_temp = self._get_outdoor_temp()
        if outdoor_temp is None and energy_constraint:
            outdoor_temp = energy_constraint.forecast_high_temp

        if outdoor_temp is None:
            return  # Can't make cover decisions without temperature

        # Cycle EC/HC reboot pickup — D2 #15. See _reboot_pickup_seed_closed_set().
        if not self._reboot_pickup_done:
            self._reboot_pickup_done = True
            self._reboot_pickup_seed_closed_set(month, hour, outdoor_temp)

        # Determine if covers should be closed for solar gain.
        # v4.5.10: hours are now configurable instance attrs.
        in_solar_window = (
            month in COVER_SOLAR_MONTHS
            and self._solar_start_hour <= hour < self._solar_end_hour
        )

        # Hysteresis: close at self._cover_close_temp, open at self._cover_open_temp
        # (v4.5.10: was hardcoded COVER_CLOSE_TEMP / COVER_OPEN_TEMP module constants)
        should_close = False
        if in_solar_window:
            if outdoor_temp >= self._cover_close_temp:
                should_close = True
            elif self._hvac_closed and outdoor_temp > self._cover_open_temp:
                should_close = True  # Stay closed until below open threshold

        # === Close phase: per-cover, gated ===
        if should_close:
            closed_count = 0
            for entity_id, cover in self._covers.items():
                if entity_id in self._hvac_closed:
                    continue  # Already HVAC-closed in this window
                if not self._should_hvac_close(entity_id, cover, now):
                    continue
                if await self._command_close_one(entity_id, cover, now):
                    self._hvac_closed.add(entity_id)
                    closed_count += 1
            if closed_count:
                _LOGGER.info(
                    "HVAC Covers: closed %d cover(s) for solar gain "
                    "(now tracking %d total HVAC-closed)",
                    closed_count, len(self._hvac_closed),
                )
            return

        # === Open phase: ONLY reopen covers HVAC closed earlier ===
        if not should_close and self._hvac_closed:
            opened_count = 0
            for entity_id in list(self._hvac_closed):
                cover = self._covers.get(entity_id)
                if cover is None:
                    # Cover was removed from discovery (config change) —
                    # silently drop from the set so we don't keep retrying.
                    self._hvac_closed.discard(entity_id)
                    continue
                # If user manually re-opened during the closed window, the
                # state-change handler stamped manual_override_until. Drop
                # the cover from the set — HVAC's "I closed this, now I'll
                # reopen it" claim is invalid because the user already did.
                if cover.manual_override_until:
                    try:
                        override_end = datetime.fromisoformat(cover.manual_override_until)
                    except ValueError:
                        override_end = None
                    if override_end and now < override_end:
                        _LOGGER.debug(
                            "HVAC Covers: dropping %s from closed-set — "
                            "user manually overrode during closed window",
                            entity_id,
                        )
                        self._hvac_closed.discard(entity_id)
                        continue
                if await self._command_open_one(entity_id, cover, now):
                    opened_count += 1
            self._hvac_closed.clear()
            if opened_count:
                _LOGGER.info(
                    "HVAC Covers: reopened %d cover(s) post-solar window",
                    opened_count,
                )

    def _should_hvac_close(
        self, entity_id: str, cover: ManagedCover, now: datetime,
    ) -> bool:
        """v4.5.9: per-cover gate before issuing a solar-gain close.

        Skip when:
          - Manual override is currently active (existing 2hr backoff)
          - Owning room intends covers closed at this time (intent gate)
          - Owning room is currently occupied AND temp not meaningfully
            above cooling setpoint (occupancy-aware comfort skip)
        """
        # Manual override skip (existing pattern, hoisted from old _command_covers)
        if cover.manual_override_until:
            try:
                override_end = datetime.fromisoformat(cover.manual_override_until)
            except ValueError:
                override_end = None
            if override_end and now < override_end:
                _LOGGER.debug(
                    "HVAC Covers: skipping %s — manual override until %s",
                    entity_id, cover.manual_override_until,
                )
                return False
            else:
                cover.manual_override_until = ""

        # Per-room intent gate. CM-level explicit covers (no owning room)
        # bypass this — user added them explicitly to the HVAC list with
        # the intent that HVAC manages them.
        if cover.owning_room_name:
            room_coord = self._get_room_coordinator(cover.owning_room_name)
            if room_coord is not None:
                automation = getattr(room_coord, "automation", None)
                if automation is not None and hasattr(automation, "is_cover_currently_intended_open"):
                    try:
                        intended_open = automation.is_cover_currently_intended_open(now)
                    except Exception:
                        # v4.5.20: was debug. If is_cover_currently_intended_open
                        # raises (e.g., method renamed during refactor, room
                        # automation schema change), every owned cover gets
                        # silently skipped permanently. HVAC cover automation
                        # dies invisibly; user assumes feature is off.
                        _LOGGER.warning(
                            "HVAC Covers: intent check failed for %s — "
                            "defaulting to skip (cover will not move)",
                            entity_id,
                            exc_info=True,
                        )
                        return False
                    if not intended_open:
                        _LOGGER.debug(
                            "HVAC Covers: skipping %s — room %s does not "
                            "currently intend covers open",
                            entity_id, cover.owning_room_name,
                        )
                        return False

                # Occupancy-aware comfort skip
                if not self._should_close_for_occupied_room(room_coord, cover.owning_room_name):
                    _LOGGER.debug(
                        "HVAC Covers: skipping %s — room %s occupied and "
                        "comfortable; not closing",
                        entity_id, cover.owning_room_name,
                    )
                    return False

        return True

    def _should_close_for_occupied_room(
        self, room_coord: Any, room_name: str,
    ) -> bool:
        """v4.5.9: return False if the room is occupied and not meaningfully
        warmer than the zone's cooling setpoint.

        Returns True (allow close) when:
          - Room is vacant, OR
          - Room temp >= zone.target_temp_high + self._occupied_close_delta
          - Or insufficient data to make a decision (default-allow; the close
            is still gated by everything else above)

        v4.5.9.2: threshold is now `self._occupied_close_delta`, configurable
        per-house via CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA. Was hardcoded to
        OCCUPIED_CLOSE_TEMP_DELTA = 2.0°F in v4.5.9.
        """
        data = getattr(room_coord, "data", None) or {}
        is_occupied = bool(data.get(STATE_OCCUPIED, False))
        if not is_occupied:
            return True

        room_temp = data.get(STATE_TEMPERATURE)
        if room_temp is None:
            return True  # No data → defer to other gates

        # Find the zone this room belongs to and read its cooling setpoint
        for zone in self._zone_manager.zones.values():
            if room_name in zone.rooms:
                if zone.target_temp_high is None:
                    return True  # No setpoint data → allow
                try:
                    delta = float(room_temp) - float(zone.target_temp_high)
                except (TypeError, ValueError):
                    return True
                # Allow close only when meaningfully above setpoint
                return delta >= self._occupied_close_delta
        # No zone match (shouldn't happen for room-discovered covers) — allow
        return True

    def _get_room_coordinator(self, room_name: str):
        """v4.5.9: lookup room coordinator by name (mirror of the same
        helper in hvac_predict.py — kept local to avoid coupling)."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            if entry.data.get(CONF_ROOM_NAME) == room_name:
                return self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
        return None

    async def _command_close_one(
        self, entity_id: str, cover: ManagedCover, now: datetime,
    ) -> bool:
        """v4.5.9: single-cover close with tilt-aware dispatch + already-
        in-target check. Returns True if a service call was issued."""
        # Already-in-target check (tilt-aware)
        if self._is_cover_already_in_target_state(entity_id, cover, "close"):
            return False

        if cover.cover_type == COVER_TYPE_TILT:
            service = "close_cover_tilt"
        else:
            service = "close_cover"

        try:
            cover.last_command_time = now.isoformat()
            await self.hass.services.async_call(
                "cover", service,
                {"entity_id": entity_id},
                blocking=False,
            )
            return True
        except Exception as e:
            _LOGGER.error(
                "HVAC Covers: failed to close %s via %s: %s",
                entity_id, service, e,
            )
            return False

    async def _command_open_one(
        self, entity_id: str, cover: ManagedCover, now: datetime,
    ) -> bool:
        """v4.5.9: single-cover open with tilt-aware dispatch + already-
        in-target check. Returns True if a service call was issued."""
        if self._is_cover_already_in_target_state(entity_id, cover, "open"):
            return False

        if cover.cover_type == COVER_TYPE_TILT:
            service = "open_cover_tilt"
        else:
            service = "open_cover"

        try:
            cover.last_command_time = now.isoformat()
            await self.hass.services.async_call(
                "cover", service,
                {"entity_id": entity_id},
                blocking=False,
            )
            return True
        except Exception as e:
            _LOGGER.error(
                "HVAC Covers: failed to open %s via %s: %s",
                entity_id, service, e,
            )
            return False

    def _is_cover_already_in_target_state(
        self, entity_id: str, cover: ManagedCover, action: str,
    ) -> bool:
        """v4.5.9: tilt-aware "already at target" check.

        Mirrors the verify-path semantics established in v4.5.0.4 +
        v4.5.6: tilt covers are evaluated on current_tilt_position
        with the same 5/95 thresholds; shade covers fall back to
        state.state.
        """
        state = self.hass.states.get(entity_id)
        if state is None:
            return False  # Can't verify → don't skip; let the service call go

        if cover.cover_type == COVER_TYPE_TILT:
            tilt = state.attributes.get("current_tilt_position")
            if tilt is None:
                # Tilt-typed but integration didn't expose current_tilt_position
                # → fall back to state.state for the check.
                if action == "close":
                    return state.state == "closed"
                if action == "open":
                    return state.state == "open"
                return False
            try:
                tp = float(tilt)
            except (TypeError, ValueError):
                return False
            if action == "close":
                return tp <= 5.0
            if action == "open":
                return tp >= 95.0
            return False

        # Shade path (unchanged from pre-v4.5.9 behavior)
        if action == "close" and state.state == "closed":
            return True
        if action == "open" and state.state == "open":
            return True
        return False

    @callback
    def _handle_cover_state_change(self, event: Event) -> None:
        """Detect manual cover position changes."""
        entity_id = event.data.get("entity_id", "")
        cover = self._covers.get(entity_id)
        if cover is None:
            return

        # If we recently commanded this cover, ignore the state change
        if cover.last_command_time:
            last_cmd = datetime.fromisoformat(cover.last_command_time)
            now = dt_util.now()
            if (now - last_cmd).total_seconds() < COVER_COMMAND_WINDOW_SECONDS:
                return

        # Manual change detected — set override backoff.
        # v4.5.10: duration is now configurable per house (was hardcoded
        # COVER_MANUAL_OVERRIDE_HOURS = 2).
        now = dt_util.now()
        override_end = now + timedelta(hours=self._cover_override_hours)
        cover.manual_override_until = override_end.isoformat()

        _LOGGER.info(
            "HVAC Covers: manual override on %s, backoff until %s",
            entity_id, cover.manual_override_until,
        )

    def _get_outdoor_temp(self) -> float | None:
        """Read outdoor temperature from configured sensor."""
        if not self._outdoor_temp_entity:
            return None
        state = self.hass.states.get(self._outdoor_temp_entity)
        if state is None or state.state in ("unavailable", "unknown"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _is_garage_cover(self, entity_id: str) -> bool:
        """Check if a cover is a garage door (should be excluded)."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        return state.attributes.get("device_class") == "garage"

    def get_cover_status(self) -> dict[str, Any]:
        """Return cover status for sensor attributes.

        v4.5.9: replaced single-bool `covers_closed` with per-cover
        `hvac_closed_set` (sorted list of entity IDs) and
        `hvac_closed_count`. `covers_closed` retained as bool form
        of "any HVAC-closed covers right now" for back-compat with
        any existing dashboard tile reading the old key.
        """
        now = dt_util.now()
        manual_overrides = 0
        for c in self._covers.values():
            if not c.manual_override_until:
                continue
            try:
                override_end = datetime.fromisoformat(c.manual_override_until)
            except ValueError:
                continue
            if override_end > now:
                manual_overrides += 1

        n_tilt = sum(1 for c in self._covers.values() if c.cover_type == COVER_TYPE_TILT)
        return {
            "managed_covers": len(self._covers),
            "managed_tilt_covers": n_tilt,
            "managed_shade_covers": len(self._covers) - n_tilt,
            "hvac_closed_set": sorted(self._hvac_closed),
            "hvac_closed_count": len(self._hvac_closed),
            "covers_closed": bool(self._hvac_closed),  # v4.5.9: back-compat
            "manual_overrides": manual_overrides,
        }
