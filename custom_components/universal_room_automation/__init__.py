"""Universal Room Automation integration."""
#
# Universal Room Automation vv5.94.3
# Build: 2026-01-05
# File: __init__.py
# FIX v3.3.2: Added ENTRY_TYPE_ZONE handling so zone OptionsFlow becomes accessible
# FIX v3.2.8: PersonLocationSensor architectural fix - active state listeners
# FIX v3.2.8: Presence decay system with tracking_status states
# FIX v3.2.8: Path tracking with recent_path attribute
# FIX v3.2.6: Previous location bug - was reading from current dict instead of self.data
# FIX v3.2.6: OccupantCountSensor now counts real people instead of rooms
# FIX v3.2.6: Added diagnostic logging and sensors for person tracking
# NEW v3.2.6: Sensor renaming for clarity (Presence → Sensor Presence, etc.)
#

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers.event import (
    async_track_time_interval,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util  # v4.6.10 review fix A-M1: module-top import

from .const import (
    DOMAIN,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ROOM,
    ENTRY_TYPE_ZONE,  # v3.3.2: Import zone entry type
    ENTRY_TYPE_ZONE_MANAGER,  # v3.6.0: Zone manager entry type
    ENTRY_TYPE_COORDINATOR_MANAGER,  # v3.6.0: Coordinator manager entry type
    CONF_ENTRY_TYPE,
    CONF_INTEGRATION_ENTRY_ID,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_OUTSIDE_HUMIDITY_SENSOR,
    CONF_WEATHER_ENTITY,
    CONF_SOLAR_PRODUCTION_SENSOR,
    CONF_ELECTRICITY_RATE,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TARGET,
    CONF_NOTIFY_LEVEL,
    CONF_TRACKED_PERSONS,  # v3.2.0: Person tracking
    CONF_ZONE_NAME,  # v3.3.2: For zone entry logging
    CONF_ZONE,  # v3.3.5.4: For zone migration
    CONF_ZONE_ROOMS,  # v3.3.5.4: For zone migration
    CONF_ZONE_DESCRIPTION,  # v3.3.5.4: For zone migration
    CONF_CAMERA_PERSON_ENTITIES,  # v3.4.5: Interior camera migration
    CONF_EGRESS_CAMERAS,  # v3.5.0: Egress cameras
    CONF_PERIMETER_CAMERAS,  # v3.5.0: Perimeter cameras
    CONF_DOMAIN_COORDINATORS_ENABLED,  # v3.6.0: Domain coordinators
    SCAN_INTERVAL_CENSUS,  # v3.5.0: Census update interval
    DEFAULT_ELECTRICITY_RATE,
    NOTIFY_LEVEL_ERRORS,
    CONF_ENHANCED_CENSUS,  # v3.10.1: Enhanced census toggle
    CENSUS_EVENT_DEBOUNCE_SECONDS,  # v3.10.1: Event debounce
    STATE_OCCUPIED,  # v4.0.0-B2: Used in accuracy eval
    # RELOAD-WATCHDOG-HAZARD fix-up (2026-08-15, B-MED-1):
    # imported so `_INTEGRATION_KEY_SIGNAL_TABLE` references the
    # authoritative constant instead of a raw duplicate string
    # (stringly-typed cross-module coupling — subscriber at
    # `transit_validator.py:41` imports the same const).
    SIGNAL_URA_TRANSIT_CONFIG_CHANGED,
    # CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1 (2026-08-18):
    CONF_FACE_RECOGNITION_ENABLED,
    CONF_EGRESS_IDENTITY_ENABLED,
    SIGNAL_URA_FACE_RECOGNITION_CHANGED,
)
from .const import VERSION
from .coordinator import UniversalRoomCoordinator
from .database import UniversalRoomDatabase
from .person_coordinator import PersonTrackingCoordinator  # v3.2.0
from .camera_census import CameraIntegrationManager, PersonCensus  # v3.5.0
from .perimeter_alert import PerimeterAlertManager  # v3.5.1
from .exterior_track_linker import ExteriorTrackLinker  # build/exterior-track
from .activity_logger import ActivityLogger  # Activity log

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Zone-prune hotfix D2 — module-level helpers (extracted for real test
# authority per fix-up "Fix 2"). Lifting `_is_phantom_compound` out of the
# migration body makes it callable from tests without invoking the whole
# HA startup path.
# ---------------------------------------------------------------------------
def _warn_immunity_dormant(hass: HomeAssistant) -> None:
    """Arrester Operator-Immunity DORMANT WARN (CRIT-A1 fix).

    The prior _default_immune_persons alphabetical seeding was DELETED
    per operator ruling 2026-08-06: silently designating whoever sorts
    first as immune is a safety hazard (a fresh person entity registered
    on a household member could shift immunity without the operator ever
    touching options). New semantics: absent OR empty option list =
    feature is DORMANT (no one is immune, arrester governance is
    byte-identical to pre-cycle). At every setup while the arrester is
    ENABLED but the immune list is empty, emit a WARNING telling the
    operator that their manual holds are UNPROTECTED. This is emitted
    every setup — the intent is that it stays visible in journald until
    the operator either enables the list OR disables the arrester.
    """
    _LOGGER.warning(
        "Arrester operator-immunity is DORMANT — set "
        "hvac_arrester_immune_persons in HVAC options to protect your "
        "manual holds. Without a list, the arrester will shave your own "
        "quick-cool manual overrides during peak just as it does for "
        "guests/kids. Set the list to the empty list explicitly to "
        "silence this warning if that is the intended posture."
    )


def _warn_immunity_voice_default_best_effort(hass: HomeAssistant) -> None:
    """One-time WARN when ARRESTER_IMMUNITY_VOICE_CONTEXTS is False.

    Operator ruling 2026-08-06 landed on False as the shipped default —
    voice/Assist pipeline calls MUST NOT inherit immunity. The
    discriminator (see hvac_const.ARRESTER_IMMUNITY_VOICE_CONTEXTS
    docstring) is best-effort (context.parent_id heuristic). Warn once
    at setup so the operator is aware of the residual: a voice agent
    authenticated as the operator's HA user could conceivably issue a
    parent_id-less direct service call and inherit immunity. The
    strict-enforcement mitigation is documented in HC manual §3.4b.4:
    give voice/Assist agents a DEDICATED HA user (not the operator).
    """
    try:
        from .domain_coordinators.hvac_const import (
            ARRESTER_IMMUNITY_VOICE_CONTEXTS,
        )
        if not ARRESTER_IMMUNITY_VOICE_CONTEXTS:
            _LOGGER.warning(
                "Arrester operator-immunity: ARRESTER_IMMUNITY_VOICE_"
                "CONTEXTS=False (shipped default). Voice pipelines "
                "sharing the operator's HA user cannot be reliably "
                "excluded from immunity by HA Context alone — the "
                "discriminator uses context.parent_id (excludes chained "
                "automation/script/assist calls but not hypothetical "
                "parent-less voice-agent calls). Keep voice agents on a "
                "DEDICATED HA user for strict enforcement (see HC manual "
                "§3.4b.4)."
            )
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("Voice-immunity warn failed: %s", e)


def _fire_temp_arrester_override_lost_note(hass: HomeAssistant) -> None:
    """B-M2 + LOW-A3: if a marker in entry.options indicates Temp
    Arrester Override was ACTIVE pre-restart, emit a LOW NM note and
    clear the marker.

    Called from async_setup_entry AFTER the notification_manager exists.
    Guarded — every branch tolerates missing keys / mid-teardown state.
    """
    try:
        from .const import DOMAIN
        entries = hass.config_entries.async_entries(DOMAIN)
        for e in entries:
            if not e.options.get("hvac_temp_arrester_override_was_active"):
                continue
            nm = hass.data.get(DOMAIN, {}).get("notification_manager")
            if nm is None:
                return
            from .domain_coordinators.base import Severity

            async def _emit(entry=e, notifier=nm):
                try:
                    await notifier.async_notify(
                        coordinator_id="hvac",
                        severity=Severity.LOW,
                        title="Temp Arrester Override released across restart",
                        message=(
                            "Temp Arrester Override was ACTIVE when HA "
                            "restarted/reloaded. It has been released to "
                            "the default-OFF state (safe default); "
                            "arrester governance has resumed. Re-engage "
                            "if still intended."
                        ),
                        hazard_type="hvac_temp_arrester_override",
                    )
                except Exception as ex:  # noqa: BLE001
                    _LOGGER.debug(
                        "Temp Arrester Override restart NM note failed: %s",
                        ex,
                    )
                try:
                    new_opts = dict(entry.options)
                    new_opts.pop("hvac_temp_arrester_override_was_active", None)
                    hass.config_entries.async_update_entry(
                        entry, options=new_opts,
                    )
                except Exception as ex:  # noqa: BLE001
                    _LOGGER.debug(
                        "Temp Arrester Override marker clear failed: %s",
                        ex,
                    )

            hass.async_create_task(_emit())  # noqa: untracked-ok — best-effort one-shot LOW NM note at setup + marker clear; fire-and-forget by design (setup should not block on an NM channel).
    except Exception as ex:  # noqa: BLE001
        _LOGGER.debug("Marker-scan on setup failed: %s", ex)


def _log_nm_suppression_daily_warning(hass: HomeAssistant) -> None:
    """B-2026-08-03-3(b): emit one WARNING/day while NM messaging is
    suppressed, so a long-forgotten kill switch is visible in journald
    (previously logged one WARN at flip time only).

    Duration is derived from ``nm._suppressed_since`` when available.

    LOW-A3 (Reviewer A) fix-up: correct the reachability wording. The
    happy path is:
      1. Steady-state — `_suppressed_since` was stamped on the OFF→ON
         flip and persisted via NMDiagnosticsSensor RestoreEntity.
      2. First boot AFTER this fix ships (switch ON from a prior
         restart, no persisted stamp) — the resync-on-startup path
         stamps the current restart time. This is a TRANSITIONAL
         UNDERREPORT that SELF-HEALS on the next flip cycle.

    The ``switch.ura_nm_messaging_suppressed.last_changed`` fallback
    below is therefore only reachable when BOTH NMDiagnosticsSensor
    restore AND the resync stamp are missing (rare cold-boot ordering
    race) — an honest approximation, not the primary source. If even
    the switch state is unavailable, we log the warning without a
    duration.
    """
    nm = hass.data.get(DOMAIN, {}).get("notification_manager")
    if nm is None or not getattr(nm, "messaging_suppressed", False):
        return
    from homeassistant.util import dt as _dtu
    now = _dtu.utcnow()
    since = getattr(nm, "_suppressed_since", None)
    duration_source = "nm_suppressed_since"
    if since is None:
        state = hass.states.get("switch.ura_nm_messaging_suppressed")
        if state is not None and getattr(state, "last_changed", None) is not None:
            since = state.last_changed
            duration_source = "switch_last_changed_approx"
    if since is not None:
        try:
            days = max(0, int((now - since).total_seconds() // 86400))
        except (TypeError, ValueError):
            days = 0
        _LOGGER.warning(
            "NM messaging suppressed for %d days — all outbound "
            "notifications are being dropped (source=%s)",
            days,
            duration_source,
        )
    else:
        _LOGGER.warning(
            "NM messaging suppressed — all outbound notifications are "
            "being dropped (duration unknown: no _suppressed_since, no "
            "switch.ura_nm_messaging_suppressed state)"
        )


def _is_phantom_compound(
    name: str, existing_zone_names_lower: set[str],
) -> tuple[bool, list[str]]:
    """True iff ``name`` is a compound "A + B [+ C ...]" where every part
    matches an already-existing house zone name (case-insensitive).

    Compound-name construction lives at
    ``domain_coordinators/hvac_zones.py:297-301``; this predicate is the
    D2 mirror that refuses to MINT such a name back into a fresh
    ENTRY_TYPE_ZONE entry (2026-07-12 husk-birth path).
    """
    if " + " not in name:
        return (False, [])
    parts = [p.strip() for p in name.split(" + ") if p.strip()]
    if len(parts) < 2:
        return (False, [])
    if all(p.lower() in existing_zone_names_lower for p in parts):
        return (True, parts)
    return (False, parts)


def _live_hvac_display_names(hass: Any) -> set[str]:
    """Return lowercased display names of live HVAC merged zones.

    Fix-up A-HIGH-1 / B-HIGH-1: production populates the canonical HVAC
    coordinator via ``CoordinatorManager.coordinators["hvac"]`` (see
    ``domain_coordinators/optimization.py:346-360`` "CM is authoritative"
    and ``switch.py:510`` for the fixed pattern). The legacy
    ``hass.data[DOMAIN]["hvac_coordinator"]`` slot is not populated in
    prod; keep it as a best-effort fallback only.

    HONEST: on cold-boot migration this lookup is typically EMPTY (the
    HVAC coordinator has not been created yet), so D2's LOAD-BEARING
    predicate is P2 (structural compound-of-existing-zones), not P1.
    P1 exists to catch the case where migration runs on a later reload
    after HVAC is already up.
    """
    names: set[str] = set()
    try:
        domain_data = hass.data.get(DOMAIN, {}) or {}
        hvac = None
        cm = domain_data.get("coordinator_manager")
        if cm is not None:
            coords = getattr(cm, "coordinators", None) or {}
            hvac = coords.get("hvac")
        if hvac is None:
            # Best-effort legacy fallback (empty in prod).
            hvac = domain_data.get("hvac_coordinator")
        if hvac is None:
            return names
        zm = getattr(hvac, "zone_manager", None) or getattr(
            hvac, "_zone_manager", None,
        )
        if zm is None:
            return names
        for _zs in getattr(zm, "zones", {}).values():
            _dn = getattr(_zs, "zone_name", "") or ""
            if _dn:
                names.add(_dn.lower())
    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "Zone migration: live-HVAC display-name lookup failed",
            exc_info=True,
        )
    return names


PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
]

# Platforms for integration entry (aggregation sensors + select for house state + switches)
INTEGRATION_PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SWITCH,  # v3.6.0-c2.5: DomainCoordinatorsSwitch, CoordinatorEnabledSwitch
    Platform.BUTTON,  # v4.0.0-B1: ClearBayesianBeliefsButton + NMAcknowledgeButton
    # evse-charge-onset Rev 6 (D1b, B-CRIT-1 fix) — the live-tunable
    # `EVChargeOnsetTimeEntity` is on the CM device. Must be here (not
    # in room PLATFORMS) so the CM-entry setup at :4160 forwards it
    # and the unload at :4818/:4835 tears it down cleanly.
    Platform.TIME,
]


async def _migrate_zone_names_to_entries(hass: HomeAssistant, integration_entry: ConfigEntry) -> int:
    """Migrate zone names from room entries to proper zone config entries (v3.3.5.4).
    
    Previously, zones could be created by typing a new zone name during room setup.
    This created a zone NAME (string) stored in the room entry, but not a zone ENTRY.
    
    Going forward, zones must be proper config entries created via "Add new Zone".
    This migration auto-creates zone entries for any orphaned zone names.
    
    Returns the number of zone entries created.
    """
    # Collect all unique zone names from room entries
    zone_names_from_rooms: dict[str, list[str]] = {}  # zone_name -> [room_entry_ids]
    
    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM:
            zone_name = config_entry.options.get(CONF_ZONE) or config_entry.data.get(CONF_ZONE)
            if zone_name:
                zone_name = zone_name.strip()
                if zone_name:
                    if zone_name not in zone_names_from_rooms:
                        zone_names_from_rooms[zone_name] = []
                    zone_names_from_rooms[zone_name].append(config_entry.entry_id)
    
    if not zone_names_from_rooms:
        _LOGGER.debug("No zone names found in room entries, skipping migration")
        return 0
    
    # Collect existing zone names — BOTH legacy ENTRY_TYPE_ZONE AND
    # ZM-embedded zones (fix-up A-HIGH-2 / plan Invariant I). The prior
    # build read ENTRY_TYPE_ZONE only, so a compound whose parts existed
    # ONLY inside a ZM options ``zones`` dict would fail the P2 predicate
    # and mint anyway.
    existing_zone_names: set[str] = set()
    for config_entry in hass.config_entries.async_entries(DOMAIN):
        et = config_entry.data.get(CONF_ENTRY_TYPE)
        if et == ENTRY_TYPE_ZONE:
            zone_name = config_entry.data.get(CONF_ZONE_NAME, "").strip()
            if zone_name:
                existing_zone_names.add(zone_name.lower())
        elif et == ENTRY_TYPE_ZONE_MANAGER:
            merged = {**config_entry.data, **config_entry.options}
            for zm_name in (merged.get("zones", {}) or {}).keys():
                if zm_name:
                    existing_zone_names.add(zm_name.strip().lower())

    # Zone-prune hotfix D2: mint-guard.
    #   P1 (live-HVAC): display names of already-derived HVAC merged
    #       zones, if the HVAC coordinator is up (CM-authoritative;
    #       fix-up A-HIGH-1 / B-HIGH-1). On cold-boot migration this is
    #       typically empty — P2 is the load-bearing predicate.
    #   P2 (structural): compound "A + B [+ C ...]" whose parts all match
    #       an existing house-zone name (case-insensitive).
    # Predicate is P1 OR P2 (union).
    live_hvac_display_names = _live_hvac_display_names(hass)

    # Create zone entries for any zone names without entries
    zones_created = 0
    for zone_name, room_entry_ids in zone_names_from_rooms.items():
        if zone_name.lower() not in existing_zone_names:
            # D2 mint-guard: skip phantom compound / live-HVAC-collision.
            _is_compound, _parts = _is_phantom_compound(
                zone_name, existing_zone_names,
            )
            _hits_live_hvac = zone_name.lower() in live_hvac_display_names
            if _is_compound or _hits_live_hvac:
                _LOGGER.warning(
                    "Zone migration: refusing to mint phantom zone %r "
                    "(hits_live_hvac=%s compound_of_existing=%s parts=%s) "
                    "— linked_rooms=%d. Leaving room CONF_ZONE untouched; "
                    "operator must clean up the room's zone assignment.",
                    zone_name, _hits_live_hvac, _is_compound, _parts,
                    len(room_entry_ids),
                )
                continue
            _LOGGER.info("Migrating zone '%s' to config entry (linked to %d rooms)", zone_name, len(room_entry_ids))
            
            # Create the zone entry via config flow
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "zone_migration"},
                data={
                    CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE,
                    CONF_ZONE_NAME: zone_name,
                    CONF_ZONE_DESCRIPTION: f"Auto-migrated from room zone assignment",
                    CONF_ZONE_ROOMS: room_entry_ids,
                    CONF_INTEGRATION_ENTRY_ID: integration_entry.entry_id,
                }
            )
            
            if result.get("type") == "create_entry":
                zones_created += 1
                _LOGGER.info("✓ Created zone entry for '%s'", zone_name)
            else:
                _LOGGER.warning("Failed to create zone entry for '%s': %s", zone_name, result)
    
    if zones_created > 0:
        _LOGGER.info("Zone migration complete: created %d zone entries", zones_created)

    return zones_created


async def _migrate_room_cameras_to_integration(hass: HomeAssistant, integration_entry: ConfigEntry) -> int:
    """Migrate CONF_CAMERA_PERSON_ENTITIES from room entries to integration entry (v3.4.5).

    In v3.4.0–3.4.4, interior cameras were configured per room in the sensors
    step. Starting in v3.4.5, they are configured at the integration level in
    the camera_census step, with room mapping handled automatically via each
    camera's area assignment.

    This one-time migration:
      1. Scans all room config entries for CONF_CAMERA_PERSON_ENTITIES values.
      2. Collects and deduplicates all camera entity IDs found.
      3. Merges them into the integration config entry's CONF_CAMERA_PERSON_ENTITIES.
      4. Removes CONF_CAMERA_PERSON_ENTITIES from each room entry's options.

    Returns the number of camera entity IDs migrated.
    """
    # Collect all camera entity IDs from room entries
    collected_cameras: list[str] = []
    seen_ids: set[str] = set()
    room_entries_with_cameras: list[ConfigEntry] = []

    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
            continue
        merged = {**config_entry.data, **config_entry.options}
        room_cameras = merged.get(CONF_CAMERA_PERSON_ENTITIES, [])
        if room_cameras:
            room_entries_with_cameras.append(config_entry)
            for cam in room_cameras:
                if cam not in seen_ids:
                    collected_cameras.append(cam)
                    seen_ids.add(cam)

    if not collected_cameras:
        _LOGGER.debug("Camera migration: no room-level camera_person_entities found, skipping")
        return 0

    _LOGGER.info(
        "Camera migration: found %d camera entity IDs across %d room entries — merging into integration entry",
        len(collected_cameras),
        len(room_entries_with_cameras),
    )

    # Merge with any already present at integration level
    integration_merged = {**integration_entry.data, **integration_entry.options}
    existing_integration_cameras = integration_merged.get(CONF_CAMERA_PERSON_ENTITIES, [])
    existing_set = set(existing_integration_cameras)
    merged_cameras = list(existing_integration_cameras)
    for cam in collected_cameras:
        if cam not in existing_set:
            merged_cameras.append(cam)
            existing_set.add(cam)

    # Update integration entry options with merged cameras
    hass.config_entries.async_update_entry(
        integration_entry,
        options={**integration_entry.options, CONF_CAMERA_PERSON_ENTITIES: merged_cameras},
    )
    _LOGGER.info(
        "Camera migration: integration entry updated with %d indoor cameras: %s",
        len(merged_cameras),
        merged_cameras,
    )

    # Remove camera_person_entities from each room entry's options
    for room_entry in room_entries_with_cameras:
        updated_options = {
            k: v for k, v in room_entry.options.items()
            if k != CONF_CAMERA_PERSON_ENTITIES
        }
        hass.config_entries.async_update_entry(room_entry, options=updated_options)
        _LOGGER.info(
            "Camera migration: removed camera_person_entities from room entry '%s'",
            room_entry.data.get("room_name", room_entry.entry_id),
        )

    return len(collected_cameras)


async def _camera_autoenable_dry_run_scan(
    hass: HomeAssistant, integration_entry: ConfigEntry
) -> None:
    """D4 dry-run: LOG the person-detect switches that would be auto-enabled.

    Iterates every ROOM entry, resolves its CONF_ROOM_CAMERAS via the shared
    CameraResolver, and emits an INFO log listing the union of person-detect
    switches currently OFF that would be turned on. Also emits a separate
    log line naming any face-detect switches found in the fusion inventory
    (INVENTORY ONLY — never auto-enabled; the log is there so the operator
    can prove face was seen and rejected).

    Behavior:
      * When ``CAMERA_AUTOENABLE_DRY_RUN=True`` (default) OR the operator
        knob ``CONF_AUTO_ENABLE_PERSON_DETECTION=False`` -> log only.
      * When both dry-run is False AND the knob is True -> currently STILL
        log only. The service-call plumbing is intentionally NOT wired this
        cycle per the plan (flip is a later reviewed change once the log
        inventory looks right on live).
    """
    from .camera_resolver import (  # noqa: PLC0415
        CameraResolver,
        collect_person_switches_to_enable,
        CAMERA_AUTOENABLE_DRY_RUN,
    )
    from .const import (  # noqa: PLC0415
        CONF_ROOM_CAMERAS,
        CONF_AUTO_ENABLE_PERSON_DETECTION,
        DEFAULT_AUTO_ENABLE_PERSON_DETECTION,
        CONF_ENTRY_TYPE,
        ENTRY_TYPE_ROOM,
    )
    from homeassistant.helpers import (  # noqa: PLC0415
        entity_registry as er, device_registry as dr,
    )

    knob_enabled = (
        (integration_entry.options.get(
            CONF_AUTO_ENABLE_PERSON_DETECTION,
            DEFAULT_AUTO_ENABLE_PERSON_DETECTION,
        ))
    )
    # B-MED-2: early-return when zero ROOM entries have room_cameras configured.
    rooms_with_cams = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM
        and ({**e.data, **e.options}.get(CONF_ROOM_CAMERAS) or [])
    ]
    if not rooms_with_cams:
        _LOGGER.debug(
            "Camera auto-enable dry-run: no rooms have CONF_ROOM_CAMERAS — skipping scan"
        )
        return
    resolver = CameraResolver(
        er.async_get(hass), dr.async_get(hass),
        state_getter=hass.states.get,
    )
    fusions = []  # flat list across rooms
    for room_entry in rooms_with_cams:
        merged = {**room_entry.data, **room_entry.options}
        room_cams = merged.get(CONF_ROOM_CAMERAS) or []
        try:
            room_fusions = resolver.resolve_operator_declaration(room_cams)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Camera auto-enable dry-run: resolve failed for room %s: %s",
                room_entry.title, exc,
            )
            continue
        fusions.extend(room_fusions)  # Fix #7: list, not single
        for f in room_fusions:
            face_sw = f.face_detect_switch_entity_ids()
            if face_sw:
                _LOGGER.info(
                    "Camera auto-enable dry-run: room=%s FACE switches (INVENTORY "
                    "ONLY, never auto-enabled): %s",
                    room_entry.title, face_sw,
                )
    would_enable = collect_person_switches_to_enable(
        fusions, lambda eid: hass.states.get(eid)
    )
    _LOGGER.info(
        "Camera auto-enable dry-run: dry_run=%s knob_enabled=%s fused_rooms=%d "
        "person_switches_that_would_be_enabled=%d entities=%s",
        CAMERA_AUTOENABLE_DRY_RUN, knob_enabled, len(fusions),
        len(would_enable), would_enable,
    )


async def _migrate_arbitrage_target_to_peak_buffer(
    hass: HomeAssistant, cm_entry: ConfigEntry
) -> bool:
    """v4.5.0 D2: rename arbitrage_target → peak_buffer_target and drop trigger.

    Idempotent — checks `arbitrage_target_rename_migration_done` flag and
    returns False (no-op) if already run. Mirrors the existing
    `zone_manager_migration_done` / `camera_migration_done` pattern.

    Operations on the CM entry's options dict:
      1. If CONF_ENERGY_ARBITRAGE_SOC_TARGET present → copy value to
         CONF_ENERGY_PEAK_BUFFER_TARGET (new key) and pop the old key.
      2. Pop CONF_ENERGY_ARBITRAGE_SOC_TRIGGER entirely (gate is now
         forecast-class only — see PLANNING_v4.5.0_battery_strategy_redesign.md).
      3. Set the migration_done flag so this only runs once.

    Returns True if migration actually ran (something changed), else False.
    """
    # v4.5.0.1 hotfix: import CONF_ENERGY_ARBITRAGE_SOC_TRIGGER_LEGACY (the
    # marker constant) — v4.5.0 D2 renamed CONF_ENERGY_ARBITRAGE_SOC_TRIGGER
    # to ..._LEGACY but missed updating this import, causing every restart
    # to log an ImportError and the migration to skip (silent no-op; entity
    # values still loaded correctly via PeakBufferTargetNumber's seed
    # fallback chain, but the migration_done flag was never set).
    from .domain_coordinators.energy_const import (
        CONF_ENERGY_ARBITRAGE_SOC_TARGET,
        CONF_ENERGY_ARBITRAGE_SOC_TRIGGER_LEGACY,
        CONF_ENERGY_PEAK_BUFFER_TARGET,
    )
    # v4.5.0.2: orphan registry cleanup is gated on its own flag so it
    # runs even on installs that already cleared the rename flag in v4.5.0.1.
    rename_done = cm_entry.options.get("arbitrage_target_rename_migration_done")
    orphan_cleanup_done = cm_entry.options.get(
        "arbitrage_soc_orphan_cleanup_done"
    )
    if rename_done and orphan_cleanup_done:
        return False

    new_options = dict(cm_entry.options)
    changed = False

    if not rename_done:
        # 1. Carry old value forward to new key (don't override an existing
        # peak_buffer_target — fresh installs may have only the new key).
        legacy_target = new_options.pop(CONF_ENERGY_ARBITRAGE_SOC_TARGET, None)
        if (
            legacy_target is not None
            and CONF_ENERGY_PEAK_BUFFER_TARGET not in new_options
        ):
            new_options[CONF_ENERGY_PEAK_BUFFER_TARGET] = legacy_target
            changed = True
        elif legacy_target is not None:
            # Both keys present — new key already wins. Just drop the old.
            changed = True

        # 2. Drop the deprecated trigger key (no longer used).
        if CONF_ENERGY_ARBITRAGE_SOC_TRIGGER_LEGACY in new_options:
            new_options.pop(CONF_ENERGY_ARBITRAGE_SOC_TRIGGER_LEGACY, None)
            changed = True

        new_options["arbitrage_target_rename_migration_done"] = True

    if not orphan_cleanup_done:
        # 3. v4.5.0.2: remove orphan ArbitrageSOCNumber entity registry entries
        # left over from v4.3.x. These show up as ghost sliders ("Arbitrage
        # SOC...") on the EC device card after the v4.5.0 D2 entity rename —
        # the production code no longer instantiates them, but HA's entity
        # registry still holds the old unique_ids. Idempotent: no-op if the
        # entities are already gone (e.g. fresh install).
        try:
            from homeassistant.helpers import entity_registry as er
            ent_reg = er.async_get(hass)
            orphan_unique_ids = (
                f"{DOMAIN}_energy_arbitrage_soc_trigger",
                f"{DOMAIN}_energy_arbitrage_soc_target",
            )
            for uid in orphan_unique_ids:
                entity_id = ent_reg.async_get_entity_id("number", DOMAIN, uid)
                if entity_id:
                    ent_reg.async_remove(entity_id)
                    _LOGGER.info(
                        "v4.5.0.2 migration: removed orphan entity %s (unique_id=%s)",
                        entity_id, uid,
                    )
                    changed = True
        except Exception as e:
            # Don't let registry cleanup block the rest of the migration.
            _LOGGER.warning(
                "v4.5.0.2 orphan entity cleanup failed (non-fatal): %s", e
            )

        new_options["arbitrage_soc_orphan_cleanup_done"] = True

    hass.config_entries.async_update_entry(cm_entry, options=new_options)
    if changed:
        _LOGGER.info(
            "v4.5.0 D2 migration: renamed arbitrage_target → peak_buffer_target "
            "and removed arbitrage_trigger from CM entry options"
        )
    return changed


async def _migrate_sensor_entity_ids(hass: HomeAssistant) -> int:
    """Migrate person-sensor unique_ids from old "occupant" names to "identified" names (v3.5.x).

    In v3.2.6 the friendly names of room and zone person sensors were updated
    (e.g. "Current Occupants" → "Identified People"), but the unique_ids were
    kept for backward compatibility.  This caused entity_ids that still said
    "current_occupants" / "occupant_count" to mismatch the visible friendly names.

    This one-time migration updates the unique_ids in the entity registry so that
    HA assigns new entity_ids consistent with the sensor names:

      Room sensors:
        {entry_id}_current_occupants   → {entry_id}_identified_people
        {entry_id}_occupant_count      → {entry_id}_identified_people_count
        {entry_id}_last_occupant       → {entry_id}_last_identified_person
        {entry_id}_last_occupant_time  → {entry_id}_last_identified_time

      Zone sensors:
        {DOMAIN}_zone_{zone}_current_occupants   → {DOMAIN}_zone_{zone}_identified_people
        {DOMAIN}_zone_{zone}_occupant_count      → {DOMAIN}_zone_{zone}_identified_people_count
        {DOMAIN}_zone_{zone}_last_occupant       → {DOMAIN}_zone_{zone}_last_identified_person
        {DOMAIN}_zone_{zone}_last_occupant_time  → {DOMAIN}_zone_{zone}_last_identified_time

    Returns the total number of entity unique_ids updated.
    """
    from homeassistant.helpers import entity_registry as er

    entity_registry = er.async_get(hass)
    renamed_count = 0

    # --- Room-level sensor migration ---
    # Room sensor unique_ids use the pattern: {entry_id}_{suffix}
    room_suffix_map = {
        "current_occupants": "identified_people",
        "occupant_count": "identified_people_count",
        "last_occupant": "last_identified_person",
        "last_occupant_time": "last_identified_time",
    }

    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
            continue
        entry_id = config_entry.entry_id
        room_name = config_entry.data.get("room_name", entry_id)

        for old_suffix, new_suffix in room_suffix_map.items():
            old_unique_id = f"{entry_id}_{old_suffix}"
            new_unique_id = f"{entry_id}_{new_suffix}"

            entity_id = entity_registry.async_get_entity_id("sensor", DOMAIN, old_unique_id)
            if entity_id is None:
                continue  # Already migrated or never existed

            # Check that the target unique_id doesn't already exist
            if entity_registry.async_get_entity_id("sensor", DOMAIN, new_unique_id) is not None:
                _LOGGER.debug(
                    "Sensor migration: target unique_id '%s' already exists, skipping '%s'",
                    new_unique_id,
                    old_unique_id,
                )
                continue

            entity_registry.async_update_entity(entity_id, new_unique_id=new_unique_id)
            renamed_count += 1
            _LOGGER.warning(
                "Sensor migration: renamed entity '%s' (room '%s') unique_id "
                "'%s' → '%s'. Update any external automations referencing the old entity_id.",
                entity_id,
                room_name,
                old_suffix,
                new_suffix,
            )

    # --- Zone-level sensor migration ---
    # Zone sensor unique_ids use the pattern: {DOMAIN}_zone_{zone_name}_{suffix}
    zone_suffix_map = {
        "current_occupants": "identified_people",
        "occupant_count": "identified_people_count",
        "last_occupant": "last_identified_person",
        "last_occupant_time": "last_identified_time",
    }

    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ZONE:
            continue
        zone_name = config_entry.data.get(CONF_ZONE_NAME, "")
        if not zone_name:
            continue

        for old_suffix, new_suffix in zone_suffix_map.items():
            old_unique_id = f"{DOMAIN}_zone_{zone_name}_{old_suffix}"
            new_unique_id = f"{DOMAIN}_zone_{zone_name}_{new_suffix}"

            entity_id = entity_registry.async_get_entity_id("sensor", DOMAIN, old_unique_id)
            if entity_id is None:
                continue  # Already migrated or never existed

            # Check that the target unique_id doesn't already exist
            if entity_registry.async_get_entity_id("sensor", DOMAIN, new_unique_id) is not None:
                _LOGGER.debug(
                    "Sensor migration: target unique_id '%s' already exists, skipping '%s'",
                    new_unique_id,
                    old_unique_id,
                )
                continue

            entity_registry.async_update_entity(entity_id, new_unique_id=new_unique_id)
            renamed_count += 1
            _LOGGER.warning(
                "Sensor migration: renamed entity '%s' (zone '%s') unique_id "
                "'%s' → '%s'. Update any external automations referencing the old entity_id.",
                entity_id,
                zone_name,
                old_suffix,
                new_suffix,
            )

    if renamed_count > 0:
        _LOGGER.info(
            "Sensor migration complete: updated %d entity unique_ids from 'occupant' to 'identified' naming",
            renamed_count,
        )

    return renamed_count


async def _migrate_zones_to_zone_manager(hass: HomeAssistant, integration_entry: ConfigEntry) -> None:
    """Migrate individual zone config entries to a single Zone Manager entry (v3.6.0).

    Creates a Zone Manager config entry containing all zone data, then removes
    the individual zone config entries to eliminate duplicate UI groups.
    """
    # Check if Zone Manager entry already exists
    for ce in hass.config_entries.async_entries(DOMAIN):
        if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
            _LOGGER.debug("Zone Manager entry already exists, skipping migration")
            return

    # Collect zone data from individual zone entries
    zones_data: dict[str, dict] = {}
    zone_entries_to_remove: list[ConfigEntry] = []

    for ce in hass.config_entries.async_entries(DOMAIN):
        if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
            zone_name = (ce.data.get(CONF_ZONE_NAME) or ce.options.get(CONF_ZONE_NAME, "")).strip()
            if not zone_name:
                continue
            merged = {**ce.data, **ce.options}
            zones_data[zone_name] = {
                CONF_ZONE_DESCRIPTION: merged.get(CONF_ZONE_DESCRIPTION, ""),
                CONF_ZONE_ROOMS: merged.get(CONF_ZONE_ROOMS, []),
            }
            # Copy any zone-specific options (media player, etc.)
            from .const import CONF_ZONE_PLAYER_ENTITY, CONF_ZONE_PLAYER_MODE
            if merged.get(CONF_ZONE_PLAYER_ENTITY):
                zones_data[zone_name][CONF_ZONE_PLAYER_ENTITY] = merged[CONF_ZONE_PLAYER_ENTITY]
            if merged.get(CONF_ZONE_PLAYER_MODE):
                zones_data[zone_name][CONF_ZONE_PLAYER_MODE] = merged[CONF_ZONE_PLAYER_MODE]

            zone_entries_to_remove.append(ce)

    # Create Zone Manager entry via config flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "zone_manager_migration"},
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE_MANAGER,
            CONF_INTEGRATION_ENTRY_ID: integration_entry.entry_id,
            "zones": zones_data,
        },
    )

    if result.get("type") == "create_entry":
        _LOGGER.info(
            "Zone Manager entry created with %d zones: %s",
            len(zones_data),
            list(zones_data.keys()),
        )

        # Remove old zone devices from the integration entry's device registry
        from homeassistant.helpers import device_registry as dr
        dev_reg = dr.async_get(hass)

        # Remove Zone Manager device from integration entry (will be recreated under ZM entry)
        zm_device = dev_reg.async_get_device(identifiers={(DOMAIN, "zone_manager")})
        if zm_device:
            dev_reg.async_remove_device(zm_device.id)

        # Remove zone devices (will be recreated under ZM entry)
        for zone_name in zones_data:
            zone_device = dev_reg.async_get_device(identifiers={(DOMAIN, f"zone_{zone_name}")})
            if zone_device:
                dev_reg.async_remove_device(zone_device.id)

        # Remove individual zone config entries
        for ce in zone_entries_to_remove:
            await hass.config_entries.async_remove(ce.entry_id)
            _LOGGER.info("Removed legacy zone entry: %s", ce.title)
    else:
        _LOGGER.error("Failed to create Zone Manager entry: %s", result)


async def _ensure_coordinator_manager_entry(hass: HomeAssistant, integration_entry: ConfigEntry) -> None:
    """Ensure a Coordinator Manager config entry exists (v3.6.0).

    Creates the entry if it doesn't exist. Coordinator sensors will be
    set up via this entry instead of the integration entry.
    Also migrates existing coordinator entities from the integration entry
    to the new Coordinator Manager entry to avoid unique_id conflicts.
    """
    for ce in hass.config_entries.async_entries(DOMAIN):
        if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
            _LOGGER.debug("Coordinator Manager entry already exists")
            return

    # Remove Coordinator Manager device from integration entry (will be recreated)
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er_mod
    dev_reg = dr.async_get(hass)
    ent_reg = er_mod.async_get(hass)

    cm_device = dev_reg.async_get_device(identifiers={(DOMAIN, "coordinator_manager")})
    if cm_device:
        dev_reg.async_remove_device(cm_device.id)

    # Remove old coordinator entity registrations so they can be recreated
    # under the new Coordinator Manager config entry
    coordinator_unique_ids = [
        f"{DOMAIN}_coordinator_manager",
        f"{DOMAIN}_house_state",
        f"{DOMAIN}_coordinator_summary",
    ]
    for uid in coordinator_unique_ids:
        entity = ent_reg.async_get_entity_id("sensor", DOMAIN, uid)
        if entity:
            ent_reg.async_remove(entity)
            _LOGGER.info("Removed old coordinator entity %s for re-creation under CM entry", entity)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "coordinator_manager_migration"},
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER,
            CONF_INTEGRATION_ENTRY_ID: integration_entry.entry_id,
        },
    )

    if result.get("type") == "create_entry":
        _LOGGER.info("Coordinator Manager entry created")
    else:
        _LOGGER.error("Failed to create Coordinator Manager entry: %s", result)


def _schedule_envoy_revalidation(
    hass: HomeAssistant,
    entry: ConfigEntry,
    energy_entity_config: dict,
) -> None:
    """Schedule deferred Envoy re-validation post-EVENT_HOMEASSISTANT_STARTED.

    EC Envoy boot-decoupling cycle (D3). Mirrors the HVAC boot-settle
    pattern at hvac.py:385-419 — register a one-shot listener for
    EVENT_HOMEASSISTANT_STARTED AND a failsafe `async_call_later` so a
    crashed start event doesn't strand the validator.

    Behavior:
      - If HA is already RUNNING (options-flow reload), run re-validation
        synchronously on the next loop tick (no boot race to wait for).
      - If still booting, listen for EVENT_HOMEASSISTANT_STARTED + arm a
        failsafe at BOOT_SETTLE_TIMEOUT_SECONDS.

    The callback (whichever path wins) re-runs `validate_envoy_config`:
      - Hard-fail (V0/V1/registry-absent) → raise/refresh the repair issue
        `energy_envoy_invalid_<entry_id>`.
      - Degraded → log INFO; clear any stale repair issue (the device is
        recovering, not misconfigured).
      - Live → clear stale repair issue.

    The first callback to fire wins; the other is unregistered via the
    `_fired` guard. Both unsubs are registered with `entry.async_on_unload`
    so reload/unload cleans them up (Bug Class #38 + #42).
    """
    from homeassistant.helpers.event import async_call_later
    try:
        from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
    except Exception:  # noqa: BLE001
        EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"
    from .const import BOOT_SETTLE_TIMEOUT_SECONDS
    from .domain_coordinators.energy_const import validate_envoy_config

    # Idempotency latch — captured by the inner callbacks so whichever
    # path fires first prevents the other from double-running. `unsubs`
    # carries (tag, handle) pairs so the winner can cross-cancel the
    # loser AND skip its own already-fired handle (A5 fix + Review D D4
    # cosmetic guard — async_listen_once self-cancel after fire would
    # log "Unable to remove unknown listener"; we filter by tag instead).
    state: dict = {"fired": False, "unsubs": []}

    entry_id = entry.entry_id
    issue_id = f"energy_envoy_invalid_{entry_id}"

    def _ec_registered() -> bool:
        """Return True iff EnergyCoordinator was actually registered.

        A2 fix: the D3 ok-path clear of the repair issue must NOT happen
        when validation now passes but EC is still absent (boot hard-fail
        case where __init__.py raised the issue + skipped EC). Deleting
        the issue there erases the operator's recovery affordance.
        """
        try:
            manager = (
                hass.data.get(DOMAIN, {}).get("coordinator_manager")
            )
            if manager is None:
                return False
            return manager.coordinators.get("energy") is not None
        except Exception:  # noqa: BLE001
            return False

    def _do_revalidate(_reason: str) -> None:
        if state["fired"]:
            return
        state["fired"] = True
        # Cross-cancel the loser path (A5). Review D D4: skip cancelling
        # the winner's own already-fired handle to avoid HA's "Unable to
        # remove unknown listener" warning (cosmetic).
        for _entry in state["unsubs"]:
            try:
                _tag, _unsub = _entry
            except Exception:  # noqa: BLE001
                _tag, _unsub = None, _entry
            if _tag is not None and _tag == _reason:
                # This is the firing path's own unsub — HA already
                # removed it as part of dispatching the once-listener /
                # timer fire. Skip to keep logs clean.
                continue
            try:
                _unsub()
            except Exception:  # noqa: BLE001
                pass
        state["unsubs"] = []
        try:
            result = validate_envoy_config(hass, energy_entity_config)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Envoy deferred re-validation failed (%s): %s",
                _reason, exc,
            )
            return

        try:
            from homeassistant.helpers import issue_registry as ir
        except Exception:  # noqa: BLE001
            return

        if not result["ok"]:
            # Genuine hard-fail post-settle → raise/refresh repair issue.
            _LOGGER.error(
                "Envoy deferred re-validation (%s) hard-failed: %s — "
                "raising repair issue.",
                _reason, result["errors"],
            )
            try:
                ir.async_create_issue(
                    hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=True,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key="energy_envoy_invalid",
                    translation_placeholders={
                        "errors": ", ".join(
                            f"{k}={v}" for k, v in result["errors"].items()
                        ) or "unknown",
                    },
                    data={"entry_id": entry_id},
                )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "Could not raise repair issue for envoy "
                    "deferred re-validation: %s", exc,
                )
            return

        # ok=True path. A2 fix: the clear is only safe when EC was
        # actually registered. If EC was skipped at boot due to an
        # earlier hard-fail (registry-absent), validation passing now
        # does NOT mean the runtime is healthy — EC is still absent.
        # Re-raise/keep the repair issue with a placeholder telling
        # the operator a reload/restart is needed to register EC.
        # (We deliberately do NOT auto-reload — operator decides.)
        if not _ec_registered():
            _LOGGER.warning(
                "Envoy deferred re-validation (%s): config now ok "
                "but EnergyCoordinator was not registered at boot — "
                "keeping repair issue. Reload/restart URA to register EC.",
                _reason,
            )
            try:
                ir.async_create_issue(
                    hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=True,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key="energy_envoy_invalid",
                    translation_placeholders={
                        "errors": (
                            "envoy_now_ok_but_ec_not_registered — "
                            "reload Universal Room Automation to "
                            "register EnergyCoordinator"
                        ),
                    },
                    data={"entry_id": entry_id},
                )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "Could not refresh repair issue for envoy "
                    "deferred re-validation (ec_not_registered): %s",
                    exc,
                )
            return

        # EC is registered — safe to clear any stale issue.
        try:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
        except Exception:  # noqa: BLE001
            pass

        if result.get("degraded"):
            # B4: log at WARNING — operator's file logger is at WARNING,
            # so INFO would render the deferred persistent-outage signal
            # invisible.
            _LOGGER.warning(
                "Envoy deferred re-validation (%s): still degraded "
                "(reason=%s) — runtime continues, no repair issue.",
                _reason, result.get("degraded_reason"),
            )
        else:
            _LOGGER.info(
                "Envoy deferred re-validation (%s): live and clear.",
                _reason,
            )

    # Bound callbacks (Bug Class #42 — no lambdas capturing loop vars).
    # A1/B1 fix: @callback so HassJob classifies these as
    # HassJobType.Callback (plain synchronous callbacks, not coroutines)
    # and runs them on the event loop (not the executor thread pool).
    # Without @callback, ir.async_create_issue / ir.async_delete_issue /
    # er.async_get would be called off-loop and either raise or silently
    # no-op. Review D D5 (2026-06-12): prior comment incorrectly
    # mentioned `HassJobType.Coroutinefunction` — these are plain
    # callbacks, classified as HassJobType.Callback only.
    @callback
    def _on_ha_started(_event) -> None:
        _do_revalidate("event_homeassistant_started")

    @callback
    def _on_failsafe_timeout(_now) -> None:
        _do_revalidate("failsafe_timeout")

    try:
        _ha_running = bool(getattr(hass, "is_running", False))
    except Exception:  # noqa: BLE001
        _ha_running = False

    if _ha_running:
        # Options-flow reload path — no boot race, run immediately.
        # Schedule for next tick so we don't re-enter setup synchronously.
        try:
            unsub_immediate = async_call_later(hass, 0, _on_failsafe_timeout)
            entry.async_on_unload(unsub_immediate)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Envoy deferred re-validation: failed to schedule "
                "immediate run on reload path",
                exc_info=True,
            )
        return

    # Cold-boot path — listen-once + failsafe timeout. The winner cancels
    # the loser via state["unsubs"] inside _do_revalidate (A5 cross-cancel).
    try:
        unsub_started = hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, _on_ha_started,
        )
        entry.async_on_unload(unsub_started)
        state["unsubs"].append(("event_homeassistant_started", unsub_started))
    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "Envoy deferred re-validation: failed to register "
            "EVENT_HOMEASSISTANT_STARTED listener",
            exc_info=True,
        )
    try:
        unsub_timeout = async_call_later(
            hass, BOOT_SETTLE_TIMEOUT_SECONDS, _on_failsafe_timeout,
        )
        entry.async_on_unload(unsub_timeout)
        state["unsubs"].append(("failsafe_timeout", unsub_timeout))
    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "Envoy deferred re-validation: failed to register failsafe "
            "timeout",
            exc_info=True,
        )


async def _migrate_solar_banking_to_energy_precool(
    hass: HomeAssistant, entry: ConfigEntry,
) -> bool:
    """v5.7.1: migrate CONF_HVAC_SOLAR_BANK_ENABLED → CONF_ENERGY_PRECOOL_ENABLED.

    The Solar HVAC Banking toggle was folded into the unified Energy
    Saver Pre-Cool feature. An operator who had banking OFF must NOT
    silently have pre-cool flipped ON by the default-seeded constructor;
    we copy their persisted choice into the new key BEFORE
    EnergyCoordinator.__init__ runs (it reads CONF_ENERGY_PRECOOL_ENABLED
    from CM entry options).

    v5.7.1 fix-up (B-1 CRITICAL): the OLD `ECSolarBankingSwitch` only
    `setattr`+`async_write_ha_state` on toggle — its durable OFF state was
    held in the entity's RestoreEntity record (unique_id
    `{DOMAIN}_energy_solar_banking`), NOT in `entry.options`. An operator
    who flipped banking OFF at runtime therefore has
    `options[hvac_solar_bank_enabled]=True` (the install seed) AND a
    RestoreEntity state of "off". The plain options copy would migrate
    True → energy_precool_enabled=True, re-enabling pre-cool. We MUST
    consult RestoreStateData and force OFF when the persisted entity
    state is "off".

    Behavior:
    - If options carry the legacy key AND not the new key:
        - Look up the orphan switch's last persisted state via the
          entity registry (unique_id slug) + RestoreStateData.
        - If RestoreEntity says "off", force NEW_KEY=False (regardless
          of the options seed). Otherwise honor the options value.
        - DROP the legacy key.
    - If both keys are present (e.g. cycle re-run), drop the legacy key
      and keep the operator's most recent value at the new key.
    - If only the new key is present, no-op (idempotent).
    - If neither is present, no-op (fresh install — constructor seeds
      from DEFAULT_ENERGY_PRECOOL_ENABLED).

    Idempotent via the `energy_precool_migration_done` flag on
    entry.options — mirrors `arbitrage_target_rename_migration_done`.

    Offset + Scope are NEW knobs with sensible defaults — no migration
    needed; first start hydrates them from defaults.
    See PLANNING_v5.7.x_energy_pre_cool_unification.md (D5).

    Returns True if something was changed in entry.options.
    """
    OLD_KEY = "hvac_solar_bank_enabled"
    NEW_KEY = "energy_precool_enabled"
    DONE_KEY = "energy_precool_migration_done"
    opts = entry.options or {}
    if opts.get(DONE_KEY):
        return False  # already migrated this entry once
    if OLD_KEY not in opts:
        # No legacy key to migrate. Still set the done-marker so we
        # don't re-scan RestoreEntity on every restart for fresh installs.
        return False
    try:
        new_options = dict(opts)
        legacy_options_value = bool(new_options.pop(OLD_KEY))

        # B-1: RestoreEntity-OFF override. Look up the orphan switch's
        # entity_id by its unique_id, then ask RestoreStateData for the
        # last persisted state. If "off", force NEW_KEY=False.
        restore_off = False
        legacy_entity_id = None
        legacy_unique_id = f"{DOMAIN}_energy_solar_banking"
        try:
            from homeassistant.helpers import entity_registry as er
            # B-RE-1 fix: RestoreStateData.async_get does NOT exist; the
            # real API is the module-level @callback `async_get`. It is
            # SYNCHRONOUS — never await it (an await on a non-coroutine
            # raises TypeError, which a bare-except would silently swallow
            # and re-enable the operator's OFF setting). Mirror the
            # `er.async_get(hass)` shape.
            from homeassistant.helpers.restore_state import (
                async_get as async_get_restore_data,
            )
            registry = er.async_get(hass)
            for ent in registry.entities.values():
                if (
                    ent.domain == "switch"
                    and ent.unique_id == legacy_unique_id
                ):
                    legacy_entity_id = ent.entity_id
                    break
            if legacy_entity_id is not None:
                restore_data = async_get_restore_data(hass)
                stored = restore_data.last_states.get(legacy_entity_id)
                state_str = None
                if stored is not None:
                    inner = getattr(stored, "state", None)
                    state_str = getattr(inner, "state", None)
                if isinstance(state_str, str) and state_str.lower() == "off":
                    restore_off = True
                    _LOGGER.info(
                        "v5.7.1 migration (B-1): RestoreEntity state for "
                        "legacy %s (%s) is 'off' — forcing %s=False over "
                        "options seed %s",
                        legacy_unique_id, legacy_entity_id, NEW_KEY,
                        legacy_options_value,
                    )
        except (ImportError, AttributeError, KeyError) as exc:
            # B-RE-1 fix: narrow the except so a future contract break
            # (e.g. RestoreState API rename, missing attribute) is LOUD
            # instead of silently swallowing a TypeError and re-enabling
            # the operator's OFF. Fail-safe to options seed below.
            _LOGGER.warning(
                "v5.7.1 RestoreEntity OFF probe failed (%s: %s) — falling "
                "back to options seed; verify RestoreState API contract",
                type(exc).__name__, exc,
            )

        # B-RE-2 fix: perform the orphan registry removal HERE, AFTER the
        # RestoreState read, so a sibling switch-platform setup cannot
        # race the migration's registry lookup. Idempotent: gated by the
        # `solar_banking_cleanup_done` marker in hass.data; switch.py's
        # `_cleanup_solar_banking_orphan` will no-op once we set it.
        if legacy_entity_id is not None:
            try:
                from homeassistant.helpers import entity_registry as er
                registry = er.async_get(hass)
                if registry.async_get(legacy_entity_id) is not None:
                    registry.async_remove(legacy_entity_id)
                    _LOGGER.info(
                        "v5.7.1 migration: removed orphan %s "
                        "(unique_id=%s) after RestoreState probe",
                        legacy_entity_id, legacy_unique_id,
                    )
            except (ImportError, AttributeError, KeyError) as exc:
                _LOGGER.warning(
                    "v5.7.1 orphan removal failed (%s: %s) — "
                    "switch-platform backstop will retry",
                    type(exc).__name__, exc,
                )
            hass.data.setdefault(DOMAIN, {})[
                "solar_banking_cleanup_done"
            ] = True

        if NEW_KEY not in new_options:
            new_options[NEW_KEY] = False if restore_off else legacy_options_value
        elif restore_off:
            # Operator-explicit OFF persisted on the retired switch
            # outranks even a same-cycle new-key default.
            new_options[NEW_KEY] = False
        new_options[DONE_KEY] = True
        hass.config_entries.async_update_entry(entry, options=new_options)
        _LOGGER.info(
            "v5.7.1 migration: %s=%s (restore_off=%s) -> %s=%s (entry %s)",
            OLD_KEY, legacy_options_value, restore_off,
            NEW_KEY, new_options[NEW_KEY], entry.entry_id,
        )
        return True
    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "v5.7.1 solar_banking → energy_precool migration failed (non-fatal)",
            exc_info=True,
        )
        return False


# =========================================================================
# ROOM-NAME-DESYNC-1 D2 — one-shot boot migration for options→data desyncs
# =========================================================================
#
# The options-flow rename handlers (config_flow.py D1 sites 1/2/3) now
# write the name/zone join-key fields through to `entry.data` in the same
# combined `async_update_entry` call. Pre-cycle entries whose last rename
# only wrote to `entry.options` are still desynced on-disk; this pass
# reconciles them at setup time.
#
# Ordering (plan §D2 checklist): this helper MUST run BEFORE
# `entry.add_update_listener(_async_update_listener)` at each of the four
# setup branches (init.py:3655, 3805, 4055, 4168). The listener is
# registered only after this returns, so the migration's
# `async_update_entry` cannot fire the listener → cannot cascade a reload
# during setup → cannot trip `feedback_parent_entry_reload_watchdog_hazard`.
#
# No VERSION bump (plan §7, Reviewer-A direction): the write-through does
# not change entry-shape; it makes two existing keys agree.
#
# String constants (NOT const-imported symbols) to keep the section
# extractor-friendly for test_v5_7_1_energy_precool.py::TestD5Migration —
# that test slices __init__.py source between two `async def` lines and
# execs the slice in an isolated namespace; any `CONF_*` reference in
# between would fail with NameError. See v5.x plan §Institutional context.
_ROOM_NAME_WRITETHROUGH_KEYS: tuple[str, ...] = (
    "room_name",   # == CONF_ROOM_NAME
    "zone_name",   # == CONF_ZONE_NAME
    "zone",        # == CONF_ZONE
)


def _migrate_room_zone_name_writethrough(
    hass: HomeAssistant, entry: ConfigEntry
) -> int:
    """Sync desynced ROOM/ZONE name+zone keys from options → data.

    Idempotent: entries already in agreement are a full no-op (zero
    async_update_entry calls, zero log lines).

    Returns the number of keys reconciled on this entry.
    """
    try:
        entry_type = entry.data.get(CONF_ENTRY_TYPE)
        if entry_type not in (ENTRY_TYPE_ROOM, ENTRY_TYPE_ZONE):
            return 0
        options = entry.options or {}
        data = entry.data or {}
        pending: dict[str, object] = {}
        for key in _ROOM_NAME_WRITETHROUGH_KEYS:
            if key not in options:
                continue
            if options.get(key) == data.get(key):
                continue
            pending[key] = options[key]
        if not pending:
            return 0
        new_data = {**data, **pending}
        hass.config_entries.async_update_entry(entry, data=new_data)
        for key, new_val in pending.items():
            _LOGGER.info(
                "ROOM-NAME-DESYNC-1 D2 migration: reconciled entry_id=%s "
                "key=%s data=%r → options=%r",
                entry.entry_id, key, data.get(key), new_val,
            )
        return len(pending)
    except Exception:  # noqa: BLE001 — never break setup
        _LOGGER.exception(
            "ROOM-NAME-DESYNC-1 D2 migration failed (non-fatal) for "
            "entry_id=%s",
            entry.entry_id,
        )
        return 0


async def _check_and_notify_room_name_desync(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """D3b runtime diagnostic — fire NM if any name key still desynced.

    Called AFTER D2 migration. If any of the three write-through keys
    still show `options[key] != data[key]`, someone edited `.storage`
    manually or a future write path escaped D1. Per-day-dedup via
    `_stuck_signal_nm.fire_stuck_signal` (kind=`room_name_desync`).

    B-MED-2 (fix-up): NM machinery may not be up yet when a room/zone
    entry sets up (entry order is nondeterministic). We schedule the
    notify as a background task + ONE deferred retry via
    `async_call_later(~60s)` if the first attempt raises. Both attempts
    ultimately swallow — the diagnostic must never break setup.
    """
    try:
        entry_type = entry.data.get(CONF_ENTRY_TYPE)
        if entry_type not in (ENTRY_TYPE_ROOM, ENTRY_TYPE_ZONE):
            return
        options = entry.options or {}
        data = entry.data or {}
        # Hoisted per A-L3 — one import per call, not per iteration.
        try:
            from .domain_coordinators._stuck_signal_nm import (  # noqa: PLC0415
                fire_stuck_signal,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "room_name_desync: stuck-signal NM module unavailable "
                "(swallowed)", exc_info=True,
            )
            return
        from homeassistant.helpers.event import async_call_later  # noqa: PLC0415

        pending: list[tuple[str, object, object]] = []
        for key in _ROOM_NAME_WRITETHROUGH_KEYS:
            if key not in options:
                continue
            if options.get(key) == data.get(key):
                continue
            pending.append((key, data.get(key), options.get(key)))
        if not pending:
            return

        async def _emit(_now=None) -> bool:
            """Try to fire NM for every pending desync. Return True if all OK."""
            all_ok = True
            for key, data_val, opt_val in pending:
                try:
                    await fire_stuck_signal(
                        hass,
                        kind="room_name_desync",
                        key=(entry.entry_id, key),
                        diagnosis=(
                            f"Config entry {entry.entry_id} ({entry.title}) "
                            f"has desynced {key}: data={data_val!r} "
                            f"options={opt_val!r}"
                        ),
                        remedy=(
                            "Re-open the room/zone options flow and save "
                            "to trigger the write-through, or restart HA "
                            "to run the boot migration."
                        ),
                    )
                except Exception:  # noqa: BLE001
                    all_ok = False
                    _LOGGER.debug(
                        "room_name_desync NM emit attempt failed "
                        "entry_id=%s key=%s", entry.entry_id, key,
                        exc_info=True,
                    )
            return all_ok

        async def _emit_with_retry() -> None:
            ok = await _emit()
            if ok:
                return
            # First attempt failed — NM machinery likely not up yet.
            # Schedule ONE deferred retry ~60s later, then swallow.
            async def _retry(_now):
                try:
                    await _emit()
                except Exception:  # noqa: BLE001
                    _LOGGER.debug(
                        "room_name_desync deferred retry failed (swallowed) "
                        "entry_id=%s", entry.entry_id, exc_info=True,
                    )

            try:
                async_call_later(hass, 60, _retry)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "room_name_desync retry schedule failed (swallowed) "
                    "entry_id=%s", entry.entry_id, exc_info=True,
                )

        # Fire-and-forget — don't block setup on the diagnostic. Tracked
        # via `entry.async_create_background_task` per the
        # setup/unload-symmetry invariant (test_setup_unload_symmetry.py::
        # TestNoUntrackedAsyncCreateTaskInScope). Task is bound to the
        # entry so it's cancelled on unload.
        entry.async_create_background_task(
            hass,
            _emit_with_retry(),
            name=f"room_name_desync_nm[{entry.entry_id}]",
        )
    except Exception:  # noqa: BLE001
        _LOGGER.debug(
            "room_name_desync diagnostic failed (swallowed) entry_id=%s",
            entry.entry_id, exc_info=True,
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Universal Room Automation from a config entry."""
    # ROOM-NAME-DESYNC-1 D2 — reconcile pre-cycle options/data desync on
    # ROOM and legacy-ZONE entries. Runs BEFORE any of the four
    # `add_update_listener` sites (planning §D2 checklist). Idempotent
    # + swallow-except; safe on all entry types (early-returns on non-
    # ROOM/ZONE). Then D3b diagnostic surfaces any residual desync via
    # NM (per-day-dedup) — catches future manual `.storage` edits.
    _migrate_room_zone_name_writethrough(hass, entry)
    await _check_and_notify_room_name_desync(hass, entry)

    # Initialize hass.data[DOMAIN] if needed
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    # MIGRATION: v2.x → v3.0.0
    if not entry.data.get(CONF_ENTRY_TYPE):
        _LOGGER.info("Detected v2.x entry '%s', migrating to v3.0.0", entry.title)
        await _migrate_to_v3(hass, entry)

    # v5.7.1 fix-up (B-2 CRITICAL): the solar-banking → energy-precool
    # migration MUST run on the CM entry's options BEFORE the integration
    # entry constructs EnergyCoordinator from cm_config. Calling it here
    # per-entry races: HA can set up the integration entry before the CM
    # entry, in which case EC reads un-migrated options and defaults
    # energy_precool ON. Mirror the arbitrage_target migration pattern —
    # invoke it inline in the integration block immediately BEFORE
    # cm_config is built (see ~line 1922). No call here.
    entry_type = entry.data.get(CONF_ENTRY_TYPE)
    
    if entry_type == ENTRY_TYPE_INTEGRATION:
        # Integration entry - store reference and set up aggregation sensors
        _LOGGER.info("Setting up Universal Room Automation integration entry")
        hass.data[DOMAIN]["integration"] = entry
        
        # Bug Class #46 note: the following async_update_entry calls are SAFE because
        # they execute BEFORE entry.add_update_listener(_async_update_listener) is
        # registered at line ~2526. No re-entrant reload can fire. If you add a new
        # async_update_entry call AFTER the update_listener registration site, defer
        # it via lazy derivation at read time (see v4.7.4.3 customize_buckets pattern).

        # v3.3.5.4: Migrate zone names to proper zone entries (run once)
        # v3.5.3: Check entry.data (durable) with fallback to entry.options (legacy)
        if not entry.data.get("zone_migration_done") and not entry.options.get("zone_migration_done"):
            try:
                zones_created = await _migrate_zone_names_to_entries(hass, entry)
                if zones_created >= 0:  # 0 = nothing to migrate, also counts as done
                    hass.config_entries.async_update_entry(
                        entry, data={**entry.data, "zone_migration_done": True}
                    )
                    if zones_created > 0:
                        _LOGGER.info("Zone migration created %d new zone entries", zones_created)
            except Exception as e:
                _LOGGER.error("Zone migration failed: %s", e)
                import traceback
                _LOGGER.error("Traceback: %s", traceback.format_exc())

        # v3.5.3: Clean up orphaned zone devices from pre-v3.3.5.6 or renamed zones
        try:
            from homeassistant.helpers import device_registry as dr
            dev_reg = dr.async_get(hass)
            active_zone_names = set()
            for ce in hass.config_entries.async_entries(DOMAIN):
                if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
                    zn = (ce.data.get(CONF_ZONE_NAME) or ce.options.get(CONF_ZONE_NAME, "")).strip()
                    if zn:
                        active_zone_names.add(zn.lower())

            for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
                for ident_domain, identifier in device.identifiers:
                    if ident_domain == DOMAIN and identifier.startswith("zone_"):
                        zone_name_from_id = identifier[5:]
                        if zone_name_from_id.lower() not in active_zone_names:
                            dev_reg.async_remove_device(device.id)
                            _LOGGER.info("Removed orphaned zone device: %s", identifier)
        except Exception as e:
            _LOGGER.warning("Zone orphan cleanup failed (non-fatal): %s", e)

        # v3.4.5: Migrate room-level camera_person_entities to integration level (run once)
        if not entry.options.get("camera_migration_done"):
            try:
                cameras_migrated = await _migrate_room_cameras_to_integration(hass, entry)
                # Re-read entry after potential update by migration
                entry = hass.config_entries.async_get_entry(entry.entry_id) or entry
                hass.config_entries.async_update_entry(
                    entry, options={**entry.options, "camera_migration_done": True}
                )
                if cameras_migrated > 0:
                    _LOGGER.info(
                        "Camera migration: moved %d camera entity IDs from room entries to integration entry",
                        cameras_migrated,
                    )
            except Exception as e:
                _LOGGER.error("Camera migration failed: %s", e)
                import traceback
                _LOGGER.error("Traceback: %s", traceback.format_exc())

        # 2026-08-01 room-camera fusion cycle D4: dry-run inventory of
        # per-integration person-detect switches that WOULD be auto-enabled.
        # Gated by camera_resolver.CAMERA_AUTOENABLE_DRY_RUN (default True)
        # AND per-integration knob CONF_AUTO_ENABLE_PERSON_DETECTION. Face
        # switches are NEVER included in this list (invariant). Flip
        # CAMERA_AUTOENABLE_DRY_RUN to False in a later reviewed change to
        # turn on live action.
        try:
            await _camera_autoenable_dry_run_scan(hass, entry)
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("Camera auto-enable dry-run scan failed: %s", e)

        # v3.6.0: Migrate zone entries to Zone Manager entry and create manager entries
        if not entry.options.get("zone_manager_migration_done"):
            try:
                await _migrate_zones_to_zone_manager(hass, entry)
                entry = hass.config_entries.async_get_entry(entry.entry_id) or entry
                hass.config_entries.async_update_entry(
                    entry, options={**entry.options, "zone_manager_migration_done": True}
                )
            except Exception as e:
                _LOGGER.error("Zone manager migration failed: %s", e)
                import traceback
                _LOGGER.error("Traceback: %s", traceback.format_exc())

        # v3.6.0: Ensure Coordinator Manager entry exists
        if not entry.options.get("coordinator_manager_entry_done"):
            try:
                await _ensure_coordinator_manager_entry(hass, entry)
                entry = hass.config_entries.async_get_entry(entry.entry_id) or entry
                hass.config_entries.async_update_entry(
                    entry, options={**entry.options, "coordinator_manager_entry_done": True}
                )
            except Exception as e:
                _LOGGER.error("Coordinator manager entry creation failed: %s", e)

        # v3.5.x: Migrate person-sensor unique_ids from "occupant" to "identified" naming (run once)
        if not entry.options.get("sensor_naming_migration_done"):
            try:
                sensors_renamed = await _migrate_sensor_entity_ids(hass)
                # Re-read entry after options may have been updated by prior migrations
                entry = hass.config_entries.async_get_entry(entry.entry_id) or entry
                hass.config_entries.async_update_entry(
                    entry, options={**entry.options, "sensor_naming_migration_done": True}
                )
                if sensors_renamed > 0:
                    _LOGGER.info(
                        "Sensor naming migration: updated %d entity unique_ids to use 'identified' naming",
                        sensors_renamed,
                    )
            except Exception as e:
                _LOGGER.error("Sensor naming migration failed: %s", e)
                import traceback
                _LOGGER.error("Traceback: %s", traceback.format_exc())

        # CONSOL-1 §D6 — one-shot options migration via the pure helper
        # `migrate_consol1_perimeter_keys` in perimeter_alert.py. Fix-up
        # A2/C-SN-MIG extracted the transform so tests drive the real
        # helper, not a simulated mirror.
        if not entry.options.get("consol1_perimeter_keys_migration_done"):
            try:
                from .perimeter_alert import migrate_consol1_perimeter_keys
                _before = dict(entry.options)
                opts, changed = migrate_consol1_perimeter_keys(_before)
                opts["consol1_perimeter_keys_migration_done"] = True
                if changed:
                    for _k in (
                        "perimeter_alert_hours_start",
                        "perimeter_alert_hours_end",
                    ):
                        _new = _k.replace("alert", "vehicle")
                        if _k in _before and opts.get(_new) == _before[_k]:
                            _LOGGER.info(
                                "CONSOL-1 §D6: migrated %s → %s (value=%s)",
                                _k, _new, _before[_k],
                            )
                    for _k in (
                        "perimeter_alert_notify_service",
                        "perimeter_alert_notify_target",
                        "perimeter_alert_hours_start",
                        "perimeter_alert_hours_end",
                    ):
                        if _k in _before and _k not in opts:
                            _LOGGER.info(
                                "CONSOL-1 §D1/§D6: stripped retired key %s", _k,
                            )
                entry = (
                    hass.config_entries.async_get_entry(entry.entry_id)
                    or entry
                )
                hass.config_entries.async_update_entry(entry, options=opts)
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("CONSOL-1 perimeter-keys migration failed: %s", e)

        # v3.6.0-c2.9.2: Remove stale coordinator-level safety_alert entity
        # that collides with the room-level one in aggregation.py.
        # The coordinator sensor was renamed to _safety_coordinator_safety_alert.
        if not entry.options.get("safety_alert_dedup_done"):
            try:
                from homeassistant.helpers import entity_registry as er_mod
                ent_reg = er_mod.async_get(hass)
                stale_uid = f"{DOMAIN}_safety_alert"
                # Check if the stale unique_id is registered under a coordinator device
                stale_eid = ent_reg.async_get_entity_id(
                    "binary_sensor", DOMAIN, stale_uid
                )
                if stale_eid:
                    stale_entry = ent_reg.async_get(stale_eid)
                    # Only remove if it belongs to the safety_coordinator device
                    if stale_entry and stale_entry.device_id:
                        from homeassistant.helpers import device_registry as dr
                        dev_reg = dr.async_get(hass)
                        device = dev_reg.async_get(stale_entry.device_id)
                        if device and (DOMAIN, "safety_coordinator") in device.identifiers:
                            ent_reg.async_remove(stale_eid)
                            _LOGGER.info(
                                "Removed stale coordinator safety_alert entity %s (unique_id collision fix)",
                                stale_eid,
                            )
                entry = hass.config_entries.async_get_entry(entry.entry_id) or entry
                hass.config_entries.async_update_entry(
                    entry, options={**entry.options, "safety_alert_dedup_done": True}
                )
            except Exception as e:
                _LOGGER.debug("Safety alert dedup migration: %s", e)

        # Fan-noise Mode-2: clean up orphaned FanRecheck*Number registry
        # entries from the v4.7.x Number-entity surface that was deleted
        # this cycle (timing knobs are now config_flow NumberSelector
        # form fields on the Coordinator Manager entry, not platform
        # Number entities). Pattern mirrors the safety_alert dedup
        # precedent above (entity_registry.async_remove by unique_id).
        if not entry.options.get("fan_recheck_number_cleanup_done"):
            try:
                from homeassistant.helpers import entity_registry as er_mod
                ent_reg = er_mod.async_get(hass)
                orphan_unique_ids = (
                    f"{DOMAIN}_fan_recheck_arm_delay_s",
                    f"{DOMAIN}_fan_recheck_spindown_s",
                    f"{DOMAIN}_fan_recheck_window_s",
                    f"{DOMAIN}_fan_recheck_cooldown_s",
                    f"{DOMAIN}_fan_recheck_max_per_hour",
                    f"{DOMAIN}_fan_recheck_hvac_suppress_s",
                    f"{DOMAIN}_fan_recheck_mmwave_history_ticks",
                )
                removed = 0
                for uid in orphan_unique_ids:
                    eid = ent_reg.async_get_entity_id("number", DOMAIN, uid)
                    if eid:
                        ent_reg.async_remove(eid)
                        removed += 1
                if removed:
                    _LOGGER.info(
                        "Fan-recheck Number cleanup: removed %d orphan registry entries",
                        removed,
                    )
                entry = hass.config_entries.async_get_entry(entry.entry_id) or entry
                hass.config_entries.async_update_entry(
                    entry,
                    options={
                        **entry.options,
                        "fan_recheck_number_cleanup_done": True,
                    },
                )
            except Exception as e:
                _LOGGER.debug("Fan-recheck Number cleanup migration: %s", e)

        # Prediction-sensor kill-list cycle (2026-06): clean up two
        # per-room sensor unique_ids removed this cycle.
        #
        # NextOccupancyInSensor (suffix `next_occupancy_in`)
        #   per-minute countdown → ~50k recorder writes/day across ~37
        #   rooms; superseded by client-side rendering of the
        #   device_class=timestamp NextOccupancyTimeSensor.
        # PeakOccupancyTimeSensor (suffix `peak_occupancy_time`)
        #   superseded 1:1 by `<room>_bayesian_occupancy_pattern`.
        #
        # Pattern mirrors the v4.7.22 fan-recheck precedent above
        # (entity_registry.async_remove by unique_id, run-once flag on the
        # integration entry options). Per-room unique_ids follow the
        # `{room_entry_id}_{entity_type}` convention from
        # ``UniversalRoomEntity.__init__`` (entity.py:30).
        if not entry.options.get("prediction_sensor_kill_list_cleanup_done"):
            try:
                from homeassistant.helpers import entity_registry as er_mod
                ent_reg = er_mod.async_get(hass)
                kill_list_suffixes = (
                    "next_occupancy_in",
                    "peak_occupancy_time",
                )
                removed = 0
                for room_entry in hass.config_entries.async_entries(DOMAIN):
                    if room_entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                        continue
                    for suffix in kill_list_suffixes:
                        uid = f"{room_entry.entry_id}_{suffix}"
                        eid = ent_reg.async_get_entity_id("sensor", DOMAIN, uid)
                        if eid:
                            ent_reg.async_remove(eid)
                            removed += 1
                if removed:
                    _LOGGER.info(
                        "Prediction-sensor kill-list cleanup: removed %d orphan "
                        "registry entries (next_occupancy_in + peak_occupancy_time)",
                        removed,
                    )
                entry = hass.config_entries.async_get_entry(entry.entry_id) or entry
                hass.config_entries.async_update_entry(
                    entry,
                    options={
                        **entry.options,
                        "prediction_sensor_kill_list_cleanup_done": True,
                    },
                )
            except Exception as e:
                _LOGGER.debug(
                    "Prediction-sensor kill-list cleanup migration: %s", e
                )

        # Initialize database (shared across all rooms — use existing if already created).
        # v4.0.17: Lock prevents race with concurrent room entry setup.
        # v5.47.1: memory wiring is idempotent and must also run when the
        # DB ALREADY exists (CM reload after owning the wiring: cleanup
        # popped the keys, this guard would skip site 1, and no other CM-
        # path call exists — memory would stay dead until restart).
        if hass.data[DOMAIN].get("database") is not None:
            await _async_wire_memory(hass, entry)
        if hass.data[DOMAIN].get("database") is None:
            db_lock = hass.data[DOMAIN].setdefault("_db_init_lock", asyncio.Lock())
            async with db_lock:
                if hass.data[DOMAIN].get("database") is None:
                    database = UniversalRoomDatabase(hass)
                    if await database.initialize():
                        await database.start_write_worker()
                        hass.data[DOMAIN]["database"] = database
                        _LOGGER.info("Database initialized successfully")

                        # v4.6.5.3 M2: dispatch SIGNAL_DATABASE_READY so any
                        # sensor that was set up before this point (e.g.
                        # URARecentAnomaliesSensor on the CM entry — concurrent
                        # setup race) can run its initial DB-dependent load
                        # without polling. Replaces v4.6.5.2's retry-with-sleep.
                        try:
                            from homeassistant.helpers.dispatcher import async_dispatcher_send
                            from .domain_coordinators.signals import SIGNAL_DATABASE_READY
                            async_dispatcher_send(hass, SIGNAL_DATABASE_READY)
                        except Exception:
                            _LOGGER.debug(
                                "SIGNAL_DATABASE_READY dispatch failed (non-fatal)",
                                exc_info=True,
                            )

                        # Activity logger — initialized immediately after DB
                        activity_logger = ActivityLogger(hass)
                        hass.data[DOMAIN]["activity_logger"] = activity_logger

                        # Hierarchical memory MVP (Stage 1) — v5.47.1:
                        # extracted to _async_wire_memory (idempotent,
                        # called from BOTH DB-init sites).
                        await _async_wire_memory(hass, entry)

                        # v5.17.0 — Observability WS surface. Registration
                        # is process-global and idempotent (guarded by
                        # ``_WS_REGISTERED`` inside the module). Safe to
                        # call from any entry setup; second call is a
                        # no-op. See planning doc §5.
                        try:
                            from .websocket_api import async_register_ws_commands
                            async_register_ws_commands(hass)
                        except Exception as ws_err:
                            _LOGGER.warning(
                                "URA observability WS commands registration failed: %s",
                                ws_err,
                            )

                        # Prune stale activity log entries on startup
                        try:
                            await database.prune_activity_log()
                        except Exception as prune_err:
                            _LOGGER.debug("Activity log startup prune failed: %s", prune_err)

                        # Register daily 2 AM prune for activity log + dedup cache clear
                        from homeassistant.helpers.event import async_call_later, async_track_time_change

                        async def _daily_activity_prune(_now):
                            """Prune activity log and clear dedup cache at 2 AM."""
                            try:
                                db = hass.data.get(DOMAIN, {}).get("database")
                                if db:
                                    await db.prune_activity_log()
                                al = hass.data.get(DOMAIN, {}).get("activity_logger")
                                if al:
                                    al.clear_dedup_cache()
                            except Exception as exc:
                                _LOGGER.debug("Daily activity prune failed: %s", exc)
                            # B-2026-08-03-3(b): daily WARNING while NM
                            # messaging is suppressed. Piggybacks this 2 AM
                            # hook — no new timers. Falls back to the
                            # switch's last_changed if NM has no
                            # suppressed_since timestamp yet.
                            try:
                                _log_nm_suppression_daily_warning(hass)
                            except Exception as exc:  # noqa: BLE001
                                _LOGGER.debug(
                                    "NM suppression daily-warning hook failed: %s",
                                    exc,
                                )

                        unsub_activity_prune = async_track_time_change(
                            hass, _daily_activity_prune, hour=2, minute=0, second=0
                        )
                        hass.data[DOMAIN]["unsub_activity_prune"] = unsub_activity_prune

                        # v4.2.8: Nightly DB maintenance at 2:30 AM — all cleanup
                        # operations batched to avoid blocking write queue.
                        _cleanup_ops = [
                            ("predictions", "prune_prediction_results", {"days": 30}),
                            ("census", "cleanup_census", {"retention_days": 90}),
                            ("energy_history", "cleanup_energy_history", {"retention_days": 180}),
                            ("external_conditions", "cleanup_external_conditions", {"retention_days": 90}),
                            ("notifications", "prune_notification_log", {"retention_days": 30}),
                            ("inbound", "prune_inbound_log", {"retention_days": 30}),
                            ("person_data", "cleanup_person_data", {"retention_days": 90}),
                            ("room_energy_baselines", "cleanup_room_energy_baselines", {"retention_days": 90}),
                            ("anomaly_log", "cleanup_anomaly_log", {"retention_days_point_in_time": 90, "retention_days_regime_shift": 365}),
                            # v4.7.8 fix-up B-H1 / C-H2 (Bug Class #27):
                            # paired cleanup for egress_state. Bounded by
                            # zone count but deleted rooms / orphaned
                            # transitions need a sweep to age out.
                            ("egress_state", "prune_stale_egress_state", {"cutoff_days": 7}),
                            # v4.7.36 fix-up B3: wire Phase 1 + Phase 3
                            # optimizer prunes into the nightly cadence so
                            # findings/digest rows don't grow unbounded.
                            ("optimization_findings", "prune_optimization_findings", {}),
                            ("optimization_daily_digest", "prune_optimization_daily_digest", {}),
                            # v5.11.0 F-MED (B-MED-2 fix-up): the D2
                            # shadow-samples table needs the same nightly
                            # prune wiring as findings/digest — else
                            # ``optimizer_shadow_samples`` grows unbounded.
                            ("optimizer_shadow_samples", "prune_optimizer_shadow_samples", {}),
                            # Fix-up A-HIGH-1 (Batch 4): retention prune for
                            # decision_log rows. `dp_eval` uses the module
                            # const `CONF_DP_EVAL_LOG_RETENTION_DAYS` (90d);
                            # the two blind-window row types share the same
                            # retention today. Each decision_type gets its
                            # own op so batching / logging is per-type.
                            ("decision_log_dp_eval", "cleanup_decision_log", {"decision_type": "dp_eval", "retention_days": 90}),
                            ("decision_log_blind_window_defer", "cleanup_decision_log", {"decision_type": "blind_window_defer", "retention_days": 90}),
                            ("decision_log_blind_window_liveness_release", "cleanup_decision_log", {"decision_type": "blind_window_liveness_release", "retention_days": 90}),
                            # DB space-reclamation: bounded incremental_vacuum
                            # runs LAST so the prunes above have already freed
                            # pages for it to reclaim. No-ops cleanly until the
                            # supervised activation VACUUM (the button-triggered
                            # full-vacuum method) converts the DB to INCREMENTAL
                            # auto_vacuum. Bounded (<=2000 pages, ~8 MB) so it
                            # completes far under the 5-min budget + 120s guard.
                            ("incremental_vacuum", "incremental_vacuum", {}),
                            # MEMORY-COMPACTOR-1 D4 (LOW-1 fix): append
                            # AFTER incremental_vacuum so the compactor
                            # rides free at the end of the rotation. The
                            # adapter is cadence-guarded and no-ops when
                            # MEMORY_COMPACTOR_ENABLED is False.
                            ("memory_compactor", "run_memory_compactor", {}),
                        ]

                        async def _nightly_db_maintenance(_now):
                            """Run all DB cleanup at 2:30 AM (batched, 5-min budget, rotating)."""
                            _db = hass.data.get(DOMAIN, {}).get("database")
                            if not _db:
                                return
                            from homeassistant.util import dt as _dtu
                            _start = _dtu.utcnow()
                            # Rotate start index so later tables get fair access
                            _idx = hass.data[DOMAIN].get("_nightly_start_idx", 0)
                            n = len(_cleanup_ops)
                            for i in range(n):
                                op = _cleanup_ops[(_idx + i) % n]
                                name, method_name, kwargs = op
                                if (_dtu.utcnow() - _start).total_seconds() > 300:
                                    _LOGGER.warning("Nightly maintenance hit 5-min budget — continuing tomorrow from %s", name)
                                    break
                                try:
                                    method = getattr(_db, method_name, None)
                                    if method:
                                        await method(**kwargs)
                                except Exception as exc:
                                    _LOGGER.warning("Nightly %s cleanup failed: %s", name, exc)
                                await asyncio.sleep(1.0)
                            hass.data[DOMAIN]["_nightly_start_idx"] = (_idx + 1) % n

                            # v4.6.2 D4: fire regime detector after cleanup ops.
                            # entry.async_create_background_task ensures the task is
                            # tracked and cancelled on entry unload (Bug Class #19).
                            _regime_det = hass.data.get(DOMAIN, {}).get("regime_detector")
                            _bayesian = hass.data.get(DOMAIN, {}).get("bayesian_predictor")
                            if _regime_det is not None and _bayesian is not None:
                                entry.async_create_background_task(
                                    hass,
                                    _regime_det.run_nightly(),
                                    "ura_regime_detector_nightly",
                                )

                        unsub_nightly = async_track_time_change(
                            hass, _nightly_db_maintenance, hour=2, minute=30, second=0
                        )
                        hass.data[DOMAIN]["unsub_nightly_maintenance"] = unsub_nightly

                        # v4.2.14: Startup catch-up prune REMOVED.
                        # v4.2.8 added it to clear a one-time backlog from orphaned
                        # cleanup methods. v4.2.13 delayed it to 30 min but it still
                        # saturated the write queue for 15-20 min, blocking all DB
                        # reads (accuracy sensor, zone sensors, external tools).
                        # Nightly 2:30 AM maintenance handles all cleanup safely.

                    else:
                        _LOGGER.warning("Database initialization failed")

        # v4.0.17: Activity logger may not have been created if a room entry won
        # the DB init race. Ensure it exists whenever DB exists.
        if (hass.data[DOMAIN].get("database") is not None
                and hass.data[DOMAIN].get("activity_logger") is None):
            activity_logger = ActivityLogger(hass)
            hass.data[DOMAIN]["activity_logger"] = activity_logger
            _LOGGER.info("Activity logger initialized (deferred from DB race)")

            try:
                await hass.data[DOMAIN]["database"].prune_activity_log()
            except Exception as prune_err:
                _LOGGER.debug("Activity log startup prune failed: %s", prune_err)

            from homeassistant.helpers.event import async_track_time_change as _attc

            async def _daily_prune_deferred(_now):
                try:
                    db = hass.data.get(DOMAIN, {}).get("database")
                    if db:
                        await db.prune_activity_log()
                    al = hass.data.get(DOMAIN, {}).get("activity_logger")
                    if al:
                        al.clear_dedup_cache()
                except Exception:
                    pass
                # B-2026-08-03-3(b): mirror the primary path — daily WARNING
                # while NM messaging is suppressed.
                try:
                    _log_nm_suppression_daily_warning(hass)
                except Exception:  # noqa: BLE001
                    pass

            unsub = _attc(hass, _daily_prune_deferred, hour=2, minute=0, second=0)
            hass.data[DOMAIN]["unsub_activity_prune"] = unsub

        # v4.2.8: Nightly maintenance deferred path (same race as activity logger)
        if (hass.data[DOMAIN].get("database") is not None
                and hass.data[DOMAIN].get("unsub_nightly_maintenance") is None):
            from homeassistant.helpers.event import (
                async_call_later as _acl_d,
                async_track_time_change as _attc_d,
            )

            _cleanup_ops_d = [
                ("predictions", "prune_prediction_results", {"days": 30}),
                ("census", "cleanup_census", {"retention_days": 90}),
                ("energy_history", "cleanup_energy_history", {"retention_days": 180}),
                ("external_conditions", "cleanup_external_conditions", {"retention_days": 90}),
                ("notifications", "prune_notification_log", {"retention_days": 30}),
                ("inbound", "prune_inbound_log", {"retention_days": 30}),
                ("person_data", "cleanup_person_data", {"retention_days": 90}),
                ("room_energy_baselines", "cleanup_room_energy_baselines", {"retention_days": 90}),
                ("anomaly_log", "cleanup_anomaly_log", {"retention_days_point_in_time": 90, "retention_days_regime_shift": 365}),
                # v4.7.8 fix-up B-H1 / C-H2 (Bug Class #27): mirror primary
                # path so the deferred-startup branch also schedules the
                # egress_state prune.
                ("egress_state", "prune_stale_egress_state", {"cutoff_days": 7}),
                # v4.7.36 fix-up B3: mirror primary path so deferred-startup
                # branch also schedules the optimizer prunes.
                ("optimization_findings", "prune_optimization_findings", {}),
                ("optimization_daily_digest", "prune_optimization_daily_digest", {}),
                # v5.11.0 F-MED (D-MED-2 fix-up): mirror primary path so
                # deferred-startup ALSO schedules the shadow-samples prune.
                ("optimizer_shadow_samples", "prune_optimizer_shadow_samples", {}),
                # Fix-up A-HIGH-1 (Batch 4) mirror: deferred-startup path
                # also schedules the decision_log prunes.
                ("decision_log_dp_eval", "cleanup_decision_log", {"decision_type": "dp_eval", "retention_days": 90}),
                ("decision_log_blind_window_defer", "cleanup_decision_log", {"decision_type": "blind_window_defer", "retention_days": 90}),
                ("decision_log_blind_window_liveness_release", "cleanup_decision_log", {"decision_type": "blind_window_liveness_release", "retention_days": 90}),
                # DB space-reclamation fix-up HIGH-1: mirror the primary path
                # so a deferred-startup (DB-init-race) boot ALSO schedules the
                # bounded incremental_vacuum. Without this, the deferred branch
                # never reclaims freed pages. Runs LAST, identical semantics.
                ("incremental_vacuum", "incremental_vacuum", {}),
                # MEMORY-COMPACTOR-1 fix-up C1 / B-HIGH-1 (Bug Class #27):
                # mirror the primary path so a deferred-startup boot ALSO
                # runs the nightly compactor. Without this, on any boot that
                # loses the DB-init race, `_last_compactor_run_ts` stays None
                # forever and no room-scoped facts are ever distilled by the
                # nightly path (button still works). Same short-circuit / cadence
                # guard semantics as primary.
                ("memory_compactor", "run_memory_compactor", {}),
            ]

            async def _nightly_maintenance_deferred(_now):
                _db = hass.data.get(DOMAIN, {}).get("database")
                if not _db:
                    return
                from homeassistant.util import dt as _dtu3
                _start = _dtu3.utcnow()
                _idx = hass.data.get(DOMAIN, {}).get("_nightly_start_idx", 0)
                n = len(_cleanup_ops_d)
                for i in range(n):
                    op = _cleanup_ops_d[(_idx + i) % n]
                    name, method_name, kwargs = op
                    if (_dtu3.utcnow() - _start).total_seconds() > 300:
                        _LOGGER.warning("Nightly maintenance hit 5-min budget — continuing tomorrow from %s", name)
                        break
                    try:
                        method = getattr(_db, method_name, None)
                        if method:
                            await method(**kwargs)
                    except Exception as exc:
                        _LOGGER.warning("Nightly %s cleanup failed: %s", name, exc)
                    await asyncio.sleep(1.0)
                hass.data.get(DOMAIN, {})["_nightly_start_idx"] = (_idx + 1) % n

                # v4.6.2 D4: fire regime detector (deferred path, same as primary)
                _regime_det = hass.data.get(DOMAIN, {}).get("regime_detector")
                _bayesian = hass.data.get(DOMAIN, {}).get("bayesian_predictor")
                if _regime_det is not None and _bayesian is not None:
                    entry.async_create_background_task(
                        hass,
                        _regime_det.run_nightly(),
                        "ura_regime_detector_nightly",
                    )

            unsub_n = _attc_d(hass, _nightly_maintenance_deferred, hour=2, minute=30, second=0)
            hass.data[DOMAIN]["unsub_nightly_maintenance"] = unsub_n

            # v4.2.14: Startup catch-up prune REMOVED (deferred path).
            # Nightly 2:30 AM maintenance handles all cleanup.

        # v3.2.0: Initialize person tracking coordinator if persons are configured
        # FIX v3.2.3.1: Read from options first (where UI saves), then fall back to data
        merged_config = {**entry.data, **entry.options}

        # v3.5.0: Initialize camera integration manager and person census
        # NOTE: Must init BEFORE transit validator (inside tracked_persons block)
        # which reads hass.data[DOMAIN]["camera_manager"] during async_init().
        # Kept outside tracked_persons block so cameras work without BLE persons.
        try:
            camera_manager = CameraIntegrationManager(hass)
            room_cameras = merged_config.get(CONF_CAMERA_PERSON_ENTITIES, [])
            egress_cameras = merged_config.get(CONF_EGRESS_CAMERAS, [])
            perimeter_cameras = merged_config.get(CONF_PERIMETER_CAMERAS, [])
            await camera_manager.async_discover(
                room_cameras=room_cameras,
                egress_cameras=egress_cameras,
                perimeter_cameras=perimeter_cameras,
            )
            hass.data[DOMAIN]["camera_manager"] = camera_manager

            census = PersonCensus(hass, camera_manager)
            hass.data[DOMAIN]["census"] = census

            # IDENTITY-FUSION-PRODUCER-1 (2026-09-04) D2: register the
            # per-slug person.<slug> state_changed listeners that feed
            # the BLE-transition leg cache. Idempotent — census tears
            # down any prior handles before re-registering. Teardown is
            # hooked from `async_unload_entry` alongside `unsub_census`.
            try:
                census._register_ble_transition_listeners()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "BLE-transition listener registration failed at setup",
                    exc_info=True,
                )

            # Periodic census updates
            async def _census_update_cb(_now):
                """Periodic callback for census updates."""
                try:
                    await census.async_update_census()
                except Exception as exc:
                    _LOGGER.error("Census periodic update failed: %s", exc)

            unsub_census = async_track_time_interval(
                hass, _census_update_cb, SCAN_INTERVAL_CENSUS
            )
            hass.data[DOMAIN]["unsub_census"] = unsub_census

            _LOGGER.info(
                "Camera census initialized with periodic updates (cameras discovered: %d, interval: %s)",
                len(camera_manager.get_all_frigate_cameras())
                + len(camera_manager.get_all_unifi_cameras()),
                SCAN_INTERVAL_CENSUS,
            )

            # v3.10.1: Event-driven census triggers (when enhanced census enabled)
            enhanced = merged_config.get(CONF_ENHANCED_CENSUS, True)
            if enhanced:
                import time as _time
                _last_event_census_time = 0.0

                async def _event_census_trigger(event):
                    """Trigger immediate census on detection event (debounced)."""
                    nonlocal _last_event_census_time
                    now = _time.monotonic()
                    if now - _last_event_census_time < CENSUS_EVENT_DEBOUNCE_SECONDS:
                        return
                    _last_event_census_time = now
                    try:
                        await census.async_update_census()
                    except Exception as exc:
                        _LOGGER.warning("Event-triggered census update failed: %s", exc)

                # Collect person detection entity IDs to watch
                _person_detection_entities = []
                for cam_info in camera_manager.get_all_frigate_cameras():
                    if cam_info.entity_id:
                        _person_detection_entities.append(cam_info.entity_id)
                for cam_info in camera_manager.get_all_unifi_cameras():
                    if cam_info.person_binary_sensor:
                        _person_detection_entities.append(cam_info.person_binary_sensor)

                unsub_event_listeners = []
                if _person_detection_entities:
                    unsub = async_track_state_change_event(
                        hass, _person_detection_entities, _event_census_trigger
                    )
                    unsub_event_listeners.append(unsub)

                # Watch Bermuda global device count for new BLE devices
                # Always register even if entity doesn't exist yet —
                # async_track_state_change_event will fire when it first appears
                unsub = async_track_state_change_event(
                    hass,
                    ["sensor.bermuda_global_total_device_count"],
                    _event_census_trigger,
                )
                unsub_event_listeners.append(unsub)

                hass.data[DOMAIN]["unsub_census_events"] = unsub_event_listeners
                _LOGGER.info(
                    "Enhanced census v2: watching %d detection entities + BLE count",
                    len(_person_detection_entities),
                )
        except Exception as e:
            _LOGGER.error("Failed to initialize camera census: %s", e)

        tracked_person_entities = merged_config.get(CONF_TRACKED_PERSONS, [])
        # v3.22.3 DIAGNOSTIC: Log the full config path for person coordinator init
        _LOGGER.warning(
            "PERSON INIT DIAGNOSTIC: entry.data keys=%s, entry.options keys=%s, "
            "CONF_TRACKED_PERSONS in data=%s, in options=%s, "
            "merged value=%s (type=%s, len=%d)",
            list(entry.data.keys()),
            list(entry.options.keys()),
            CONF_TRACKED_PERSONS in entry.data,
            CONF_TRACKED_PERSONS in entry.options,
            tracked_person_entities,
            type(tracked_person_entities).__name__,
            len(tracked_person_entities) if tracked_person_entities else 0,
        )
        if tracked_person_entities:
            try:
                # Convert entity IDs to person names
                # Config flow returns ["person.oji", "person.ezinne"]
                # Coordinator expects ["Oji", "Ezinne"]
                tracked_persons = []
                for entity_id in tracked_person_entities:
                    if entity_id.startswith("person."):
                        # Extract name from entity_id (person.oji -> Oji)
                        person_name = entity_id.replace("person.", "").replace("_", " ").title()
                        tracked_persons.append(person_name)
                    else:
                        # Already a name, just title case it
                        tracked_persons.append(entity_id.replace("_", " ").title())

                _LOGGER.warning(
                    "PERSON INIT DIAGNOSTIC: converted %s -> %s",
                    tracked_person_entities, tracked_persons,
                )

                # UPDATE the entry.data directly so aggregation.py also sees person names
                hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_TRACKED_PERSONS: tracked_persons}
                )

                # Now create coordinator with the updated entry
                _LOGGER.warning("PERSON INIT DIAGNOSTIC: creating PersonTrackingCoordinator...")
                person_coordinator = PersonTrackingCoordinator(hass, entry)
                await person_coordinator.async_config_entry_first_refresh()
                hass.data[DOMAIN]["person_coordinator"] = person_coordinator
                _LOGGER.info("Person tracking coordinator initialized for %d persons: %s", len(tracked_persons), tracked_persons)
                
                # v3.3.0: Initialize cross-room coordination components
                try:
                    from .transitions import TransitionDetector
                    from .pattern_learning import PatternLearner
                    from .music_following import MusicFollowing
                    
                    # Get database reference
                    database = hass.data[DOMAIN].get("database")
                    
                    # Initialize transition detector
                    _LOGGER.debug("Initializing TransitionDetector...")
                    transition_detector = TransitionDetector(
                        hass,
                        person_coordinator,
                        database
                    )
                    await transition_detector.async_init()
                    hass.data[DOMAIN]["transition_detector"] = transition_detector
                    _LOGGER.info("✓ TransitionDetector initialized successfully")
                    
                    # Initialize pattern learner
                    _LOGGER.debug("Initializing PatternLearner...")
                    pattern_learner = PatternLearner(hass, database)
                    hass.data[DOMAIN]["pattern_learner"] = pattern_learner
                    _LOGGER.info("✓ PatternLearner initialized successfully")

                    # v4.0.0-B1: Initialize Bayesian predictor
                    try:
                        from .bayesian_predictor import BayesianPredictor

                        _LOGGER.debug("Initializing BayesianPredictor...")
                        bayesian_predictor = BayesianPredictor(hass)
                        # v4.2.13: Register BEFORE initialize so button/sensors
                        # are available even if DB load fails (empty beliefs,
                        # learns from live transitions).
                        hass.data[DOMAIN]["bayesian_predictor"] = bayesian_predictor

                        # v4.6.9: notify buttons that bayesian_predictor is ready
                        try:
                            from homeassistant.helpers.dispatcher import async_dispatcher_send
                            from .domain_coordinators.signals import SIGNAL_BAYESIAN_READY
                            async_dispatcher_send(hass, SIGNAL_BAYESIAN_READY)
                        except Exception:
                            _LOGGER.debug(
                                "SIGNAL_BAYESIAN_READY dispatch failed (non-fatal)",
                                exc_info=True,
                            )

                        # v4.6.2 D4: instantiate RegimeDetector now that both
                        # database and bayesian_predictor are available.
                        try:
                            from .domain_coordinators.regime_detector import RegimeDetector
                            # v4.6.2 review fix B#2/A#1: pass `entry` so
                            # _window_days() actually reads the D6 Number
                            # tunables instead of falling through to the
                            # hardcoded 56/14 defaults.
                            regime_detector = RegimeDetector(
                                hass, database, bayesian_predictor, entry,
                            )
                            hass.data[DOMAIN]["regime_detector"] = regime_detector
                            _LOGGER.info("RegimeDetector instantiated")
                        except Exception as _rde:
                            _LOGGER.warning("RegimeDetector init failed: %s", _rde)

                        try:
                            await bayesian_predictor.initialize(database)
                        except Exception as init_exc:
                            _LOGGER.warning(
                                "BayesianPredictor DB load failed (will learn "
                                "from live transitions): %s", init_exc
                            )

                        # Wire into transition detector for live updates
                        @callback
                        def _bayesian_on_transition(transition):
                            """Update Bayesian beliefs on each room transition."""
                            bayesian_predictor.update(
                                person_id=transition.person_id,
                                to_room=transition.to_room,
                                timestamp=transition.timestamp,
                                confidence=transition.confidence,
                            )

                        transition_detector.async_add_listener(_bayesian_on_transition)
                        hass.data[DOMAIN]["bayesian_transition_listener"] = _bayesian_on_transition

                        # Periodic save every 30 minutes
                        async def _bayesian_periodic_save(now):
                            """Save Bayesian beliefs to DB."""
                            try:
                                await bayesian_predictor.save_beliefs()
                            except Exception as exc:
                                _LOGGER.error("Bayesian periodic save failed: %s", exc)

                        unsub_bayesian_save = async_track_time_interval(
                            hass, _bayesian_periodic_save, timedelta(minutes=30)
                        )
                        hass.data[DOMAIN]["unsub_bayesian_save"] = unsub_bayesian_save

                        # Save on shutdown (via unload)
                        hass.data[DOMAIN]["bayesian_predictor_shutdown"] = True

                        # Guest mode listener: suppress learning when GUEST state
                        from .domain_coordinators.signals import (
                            SIGNAL_HOUSE_STATE_CHANGED,
                            HouseStateChange,
                        )
                        from homeassistant.helpers.dispatcher import (
                            async_dispatcher_connect,
                        )

                        @callback
                        def _bayesian_guest_listener(payload):
                            """Suppress Bayesian learning during guest mode."""
                            if not isinstance(payload, HouseStateChange):
                                return  # Skip non-conforming payloads
                            is_guest = str(payload.new_state).lower() == "guest"
                            bayesian_predictor.suppress_learning(is_guest)

                        unsub_bayesian_guest = async_dispatcher_connect(
                            hass, SIGNAL_HOUSE_STATE_CHANGED, _bayesian_guest_listener
                        )
                        hass.data[DOMAIN]["unsub_bayesian_guest"] = unsub_bayesian_guest

                        # v4.0.0-B2: Accuracy evaluation at time-bin boundaries
                        # Record predictions vs actual occupancy at bin transitions
                        # Bins start at hours: 0, 6, 9, 12, 17, 21 — evaluate 5 min in
                        from homeassistant.helpers.event import async_track_time_change

                        async def _bayesian_accuracy_eval(_now):
                            """Record prediction accuracy at bin boundaries."""
                            try:
                                # v4.5.17: dt_util was never imported in this
                                # closure's scope, causing every Bayesian eval
                                # since the feature was added (v4.0.0-B2) to
                                # silently die with NameError. The bare
                                # `_LOGGER.debug` swallow at the bottom of this
                                # try block hid the failure for months until
                                # v4.5.16 escalated it to WARNING. Phase 1
                                # surfaced the bug; this is Phase 2's one-line
                                # fix. Same pattern as `__init__.py:2375`.
                                from homeassistant.util import dt as dt_util
                                bp = hass.data.get(DOMAIN, {}).get("bayesian_predictor")
                                if bp is None:
                                    return
                                from .bayesian_predictor import (
                                    _hour_to_time_bin,
                                    _day_type,
                                )

                                now = dt_util.now()
                                time_bin = _hour_to_time_bin(now.hour)
                                day_type_val = _day_type(now)
                                timestamp = dt_util.utcnow().isoformat()

                                # Collect all predictions into batch rows
                                batch_rows = []
                                for room_entry in hass.config_entries.async_entries(DOMAIN):
                                    room_name = room_entry.data.get("room_name")
                                    if not room_name:
                                        continue
                                    entry_type = room_entry.data.get("entry_type")
                                    if entry_type != "room":
                                        continue

                                    # Get actual occupancy from coordinator
                                    coord = hass.data.get(DOMAIN, {}).get(room_entry.entry_id)
                                    if coord is None or not hasattr(coord, "data") or not coord.data:
                                        continue
                                    actual_occupied = bool(coord.data.get(STATE_OCCUPIED))

                                    # Get predicted probability
                                    prob = bp.predict_room_occupancy(
                                        room_name, time_bin, day_type_val
                                    )
                                    if prob is not None:
                                        error = (prob - (1 if actual_occupied else 0)) ** 2
                                        context_code = float(time_bin * 10 + day_type_val)
                                        batch_rows.append((
                                            room_name,
                                            timestamp,
                                            "bayesian_occupancy",
                                            str(round(prob, 4)),
                                            context_code,
                                            str(1 if actual_occupied else 0),
                                            round(error, 6),
                                        ))

                                # Single batch DB write
                                if batch_rows:
                                    database = hass.data.get(DOMAIN, {}).get("database")
                                    if database is not None:
                                        await database.save_prediction_results_batch(batch_rows)
                                        _LOGGER.info(
                                            "Bayesian accuracy eval: wrote %d "
                                            "prediction rows to DB",
                                            len(batch_rows),
                                        )
                                    else:
                                        _LOGGER.warning(
                                            "Bayesian accuracy eval: %d rows "
                                            "ready but database handle is None — "
                                            "rows DROPPED (Phase 2 fix needed)",
                                            len(batch_rows),
                                        )
                                else:
                                    _LOGGER.warning(
                                        "Bayesian accuracy eval fired but "
                                        "produced 0 rows — likely room_id "
                                        "mismatch or no predictions resolved "
                                        "(v4.5.16 diagnostic; Phase 2 fix needed)"
                                    )
                            except Exception as exc:
                                # v4.5.16: was _LOGGER.debug — escalated to
                                # warning + exc_info so the silent-swallow
                                # that hid the "0 prediction rows in 7d" bug
                                # is no longer invisible. Traceback at WARNING
                                # level (not ERROR via .exception()) keeps the
                                # noise level proportional to the diagnostic
                                # phase. After one decision bin (~6h) of
                                # these logs, we know whether eval (a) never
                                # fires, (b) fires-but-empty, or (c) fires
                                # but writes fail. Phase 2 fix follows.
                                _LOGGER.warning(
                                    "Bayesian accuracy eval failed: %s "
                                    "(type=%s)",
                                    exc, type(exc).__name__,
                                    exc_info=True,
                                )

                        # Fire at minute=5 of each bin-boundary hour
                        unsub_bayesian_accuracy = async_track_time_change(
                            hass,
                            _bayesian_accuracy_eval,
                            hour=[0, 6, 9, 12, 17, 21],
                            minute=5,
                            second=0,
                        )
                        hass.data[DOMAIN]["unsub_bayesian_accuracy"] = unsub_bayesian_accuracy

                        # v4.0.0-B2: Add prediction results pruning to periodic save
                        # v4.2.8: Prediction prune moved to nightly maintenance (2:30 AM)
                        # and startup catch-up (5 min after boot). The unbounded DELETE
                        # was holding the write queue for >120s on large tables.

                        _LOGGER.info("✓ BayesianPredictor initialized successfully")
                    except Exception as e:
                        _LOGGER.error("BayesianPredictor init failed: %s", e)
                        import traceback
                        _LOGGER.error("BayesianPredictor traceback: %s", traceback.format_exc())

                    # Initialize music following
                    _LOGGER.debug("Initializing MusicFollowing...")
                    music_following = MusicFollowing(
                        hass,
                        merged_config,
                        transition_detector
                    )
                    await music_following.async_init()
                    hass.data[DOMAIN]["music_following"] = music_following
                    _LOGGER.info("✓ MusicFollowing initialized successfully")
                    
                    # Enable music following for all tracked persons by default
                    # v5.10.0 fix-up FIX-5 (B-HIGH-1): consult the
                    # singleton's per-person prefs so an explicit OFF
                    # pref (from a restored MFPersonFollowSwitch) is not
                    # clobbered by the auto-enable-all boot pass.
                    _prefs = getattr(music_following, "_person_follow_prefs", {}) or {}
                    for person_name in tracked_persons:
                        if _prefs.get(person_name) is False:
                            continue
                        music_following.enable_for_person(person_name)

                    # v3.5.2: Transit validation and egress direction tracking
                    # NOTE: camera_manager + census init moved before tracked_persons
                    # block (v3.6.33) so they're always available.
                    try:
                        from .transit_validator import TransitValidator, EgressDirectionTracker

                        transit_validator = TransitValidator(hass)
                        await transit_validator.async_init()
                        hass.data[DOMAIN]["transit_validator"] = transit_validator

                        # Wire validator into transition detector
                        transition_detector.set_transit_validator(transit_validator)

                        egress_tracker = EgressDirectionTracker(hass)
                        await egress_tracker.async_init()
                        hass.data[DOMAIN]["egress_tracker"] = egress_tracker

                        _LOGGER.info("Transit validation and egress direction tracking initialized")
                    except Exception as e:
                        _LOGGER.warning(
                            "Transit validation init failed — sensor predictions will work "
                            "without camera enrichment: %s",
                            e,
                        )

                except ImportError as e:
                    _LOGGER.warning("Cross-room coordination modules not available: %s", e)
                except Exception as e:
                    _LOGGER.error("Failed to initialize cross-room coordination: %s", e)
                    import traceback
                    _LOGGER.error("Traceback: %s", traceback.format_exc())

            except Exception as e:
                _LOGGER.error("PERSON INIT DIAGNOSTIC: FAILED to initialize person tracking: %s", e)
                import traceback
                _LOGGER.error("PERSON INIT DIAGNOSTIC: Traceback: %s", traceback.format_exc())
        else:
            _LOGGER.warning(
                "PERSON INIT DIAGNOSTIC: tracked_person_entities is EMPTY/FALSY — "
                "skipping person coordinator. Value was: %r",
                tracked_person_entities,
            )

        # v3.5.1: Initialize perimeter alert manager
        try:
            perimeter_alert_manager = PerimeterAlertManager(hass)
            await perimeter_alert_manager.async_setup()
            hass.data[DOMAIN]["perimeter_alert_manager"] = perimeter_alert_manager
            _LOGGER.info(
                "Perimeter alert manager initialized (active: %s)",
                perimeter_alert_manager.is_active,
            )
        except Exception as e:
            _LOGGER.error("Failed to initialize perimeter alert manager: %s", e)

        # CONSOL-1 §D8 — in-code tripwire on the HA zone_monitoring
        # pager stack. Subscribes to `last_updated` on the four counter
        # automations; fires ONE MEDIUM NM per fired counter per day
        # (per-day dedup). Auto-closes: if the tripwire produces zero
        # leak notifications between ship and the NEXT URA release, the
        # yaml notify actions get stripped in a follow-up.
        try:
            from .zone_monitoring_tripwire import ZoneMonitoringTripwire
            # B1 double-setup guard: tear down any prior instance from a
            # partial reload before installing the new one — mirrors the
            # exterior_track_linker guard at :2504.
            _existing_zmt = hass.data.get(DOMAIN, {}).pop(
                "zone_monitoring_tripwire", None,
            )
            if _existing_zmt is not None:
                try:
                    await _existing_zmt.async_teardown()
                except Exception:  # noqa: BLE001
                    pass
            _zmt = ZoneMonitoringTripwire(hass)
            await _zmt.async_setup()
            hass.data[DOMAIN]["zone_monitoring_tripwire"] = _zmt
            _LOGGER.info(
                "CONSOL-1 §D8: zone_monitoring tripwire subscribed"
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.error(
                "CONSOL-1 §D8: zone_monitoring tripwire failed: %s", e,
            )

        # build/exterior-track: Initialize exterior track linker.
        # Independent of PerimeterAlertManager — subscribes to `frigate_events`
        # itself. Kill switch: TRACK_LINK_WINDOW_S == 0 in const.py disables
        # linking (per-camera alert behavior is byte-identical to today).
        try:
            # B-M1: double-setup guard. If a prior linker instance is still
            # registered (e.g. a partially-failed reload), tear it down
            # before installing the new one so timers/subscriptions don't
            # leak.
            _existing_linker = hass.data.get(DOMAIN, {}).pop(
                "exterior_track_linker", None
            )
            if _existing_linker is not None:
                try:
                    await _existing_linker.async_teardown()
                except Exception:  # noqa: BLE001
                    _LOGGER.debug(
                        "prior ExteriorTrackLinker teardown raised",
                        exc_info=True,
                    )
            exterior_track_linker = ExteriorTrackLinker(hass)
            await exterior_track_linker.async_setup()
            # Control-surface restore fallback (focused-review LOW-1): the
            # switches live on the CM entry which may set up concurrently;
            # announce readiness so a deferred restore can apply.
            from homeassistant.helpers.dispatcher import async_dispatcher_send as _ads
            from .domain_coordinators.signals import SIGNAL_EXTERIOR_LINKER_READY
            # SECC-1 ORDERING FIX (2026-08-08, v5.62.1): REGISTER BEFORE DISPATCH.
            # `_ads(...)` used to fire on the line ABOVE this assignment, so every
            # SIGNAL_EXTERIOR_LINKER_READY subscriber that resolves the linker via
            # `hass.data[DOMAIN]["exterior_track_linker"]` found None and bailed —
            # silently. That defeated PerimeterAlertManager's deferred allowlist
            # install across v5.59-v5.62: the live diagnostic read
            # `allowlist_installed: false, allowlist_camera_count: 0` right after
            # the v5.62.0 deploy, which is what finally exposed it. The linker MUST
            # be resolvable from hass.data before readiness is announced.
            # Pinned by test_linker_registered_in_hass_data_BEFORE_ready_signal_dispatched.
            hass.data[DOMAIN]["exterior_track_linker"] = exterior_track_linker
            _ads(hass, SIGNAL_EXTERIOR_LINKER_READY)
            _LOGGER.info(
                "Exterior track linker initialized (active: %s)",
                exterior_track_linker.is_active,
            )
        except Exception as e:
            _LOGGER.error("Failed to initialize exterior track linker: %s", e)

        # v3.6.0: Initialize domain coordinator manager if enabled
        # NOTE: Zone Manager and Coordinator Manager devices are now registered
        # under their own config entries (not under the integration entry).
        # This prevents duplicate display on the integration page.
        # v4.6.10 D1: Capture setup start timestamp (Bug Class #21: dt_util, not datetime).
        # Review fix A-M1: use module-top dt_util import, no function-local re-import.
        _setup_started = None
        try:
            _setup_started = dt_util.utcnow()
        except Exception:
            _LOGGER.debug("v4.6.10: setup telemetry start capture failed (non-fatal)", exc_info=True)

        if merged_config.get(CONF_DOMAIN_COORDINATORS_ENABLED, False):
            try:
                from .domain_coordinators.manager import CoordinatorManager
                from .const import (
                    CONF_SLEEP_START_HOUR,
                    CONF_SLEEP_END_HOUR,
                    CONF_GEOFENCE_ENTITIES,
                    CONF_WATER_SHUTOFF_VALVE,
                    CONF_EMERGENCY_LIGHT_ENTITIES,
                    CONF_PRESENCE_ENABLED,
                    CONF_SAFETY_ENABLED,
                    CONF_SECURITY_ENABLED,
                    CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED,
                    DEFAULT_SLEEP_START_HOUR,
                    DEFAULT_SLEEP_END_HOUR,
                    # v4.6.2.2: Guest mode hardening knobs
                    CONF_GUEST_MODE_PERSISTENCE_SECONDS,
                    CONF_GUEST_MODE_REQUIRE_CONFIDENCE,
                    DEFAULT_GUEST_PERSISTENCE_SECONDS,
                    DEFAULT_GUEST_REQUIRE_CONFIDENCE,
                )

                # v3.6.0-c2.1: Read coordinator settings from CM entry options.
                # Settings are stored in the CM entry by the coordinator config steps.
                # Fall back to integration merged_config for backward compatibility.
                cm_config: dict = {}
                cm_entry: ConfigEntry | None = None
                for ce in hass.config_entries.async_entries(DOMAIN):
                    if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                        cm_entry = ce
                        break

                # v4.5.0 D2: Migrate arbitrage_target → peak_buffer_target and
                # drop the now-removed arbitrage_trigger key. Idempotent —
                # gated on options["arbitrage_target_rename_migration_done"].
                # Must run BEFORE cm_config dict is built so the renamed key
                # is in place when EnergyCoordinator constructs BatteryStrategy.
                if cm_entry is not None:
                    try:
                        await _migrate_arbitrage_target_to_peak_buffer(hass, cm_entry)
                        # Re-read after potential update
                        cm_entry = (
                            hass.config_entries.async_get_entry(cm_entry.entry_id)
                            or cm_entry
                        )
                    except Exception as e:
                        _LOGGER.error(
                            "v4.5.0 arbitrage_target rename migration failed: %s", e
                        )

                # v5.7.1 fix-up (B-2 CRITICAL): solar-banking → energy-precool
                # migration MUST run on the CM entry HERE, BEFORE cm_config is
                # built, so EnergyCoordinator.__init__ reads the migrated
                # value (and the RestoreEntity-OFF override) instead of the
                # un-migrated install seed. Idempotent via DONE_KEY.
                if cm_entry is not None:
                    try:
                        await _migrate_solar_banking_to_energy_precool(
                            hass, cm_entry,
                        )
                        cm_entry = (
                            hass.config_entries.async_get_entry(cm_entry.entry_id)
                            or cm_entry
                        )
                    except Exception as e:
                        _LOGGER.error(
                            "v5.7.1 solar_banking → energy_precool migration "
                            "failed: %s", e,
                        )

                if cm_entry is not None:
                    cm_config = {**cm_entry.data, **cm_entry.options}

                coordinator_manager = CoordinatorManager(hass)

                # v4.7.x Cycle A: Construct WeatherProviderManager singleton.
                # Stored at hass.data[DOMAIN]["weather_manager"] for Energy +
                # HVAC + sensors to consume. Sets up its own state listeners.
                try:
                    from .domain_coordinators.weather_manager import (
                        WeatherProviderManager,
                    )
                    weather_manager = WeatherProviderManager(hass, cm_config)
                    await weather_manager.async_setup()
                    hass.data[DOMAIN]["weather_manager"] = weather_manager
                except Exception as exc:  # pragma: no cover
                    _LOGGER.warning(
                        "WeatherProviderManager setup failed: %s", exc, exc_info=True
                    )

                # v3.6.0-c1: Register Presence Coordinator
                if cm_config.get(CONF_PRESENCE_ENABLED, True):
                    from .domain_coordinators.presence import PresenceCoordinator
                    presence = PresenceCoordinator(
                        hass,
                        sleep_start_hour=int(cm_config.get(
                            CONF_SLEEP_START_HOUR,
                            merged_config.get(
                                CONF_SLEEP_START_HOUR, DEFAULT_SLEEP_START_HOUR
                            ),
                        )),
                        sleep_end_hour=int(cm_config.get(
                            CONF_SLEEP_END_HOUR,
                            merged_config.get(
                                CONF_SLEEP_END_HOUR, DEFAULT_SLEEP_END_HOUR
                            ),
                        )),
                        # v4.6.2.2: Guest mode false-positive hardening
                        guest_persistence_seconds=int(cm_config.get(
                            CONF_GUEST_MODE_PERSISTENCE_SECONDS,
                            DEFAULT_GUEST_PERSISTENCE_SECONDS,
                        )),
                        guest_require_confidence=str(cm_config.get(
                            CONF_GUEST_MODE_REQUIRE_CONFIDENCE,
                            DEFAULT_GUEST_REQUIRE_CONFIDENCE,
                        )),
                    )
                    coordinator_manager.register_coordinator(presence)
                else:
                    _LOGGER.info("Presence Coordinator disabled via config")

                # v3.6.0-c2: Register Safety Coordinator
                if cm_config.get(CONF_SAFETY_ENABLED, True):
                    from .domain_coordinators.safety import SafetyCoordinator
                    safety = SafetyCoordinator(
                        hass,
                        water_shutoff_valve=cm_config.get(CONF_WATER_SHUTOFF_VALVE),
                        emergency_lights=cm_config.get(
                            CONF_EMERGENCY_LIGHT_ENTITIES, []
                        ),
                    )
                    coordinator_manager.register_coordinator(safety)
                else:
                    _LOGGER.info("Safety Coordinator disabled via config")

                # v3.6.0-c3: Register Security Coordinator
                if cm_config.get(CONF_SECURITY_ENABLED, True):
                    from .domain_coordinators.security import SecurityCoordinator
                    from .const import (
                        CONF_SECURITY_LOCK_ENTITIES,
                        CONF_SECURITY_GARAGE_ENTITIES,
                        CONF_SECURITY_ENTRY_SENSORS,
                        CONF_SECURITY_LIGHT_ENTITIES,
                        CONF_SECURITY_CAMERA_ENTITIES,
                        CONF_SECURITY_CAMERA_RECORDING,
                        CONF_SECURITY_CAMERA_RECORD_DURATION,
                        CONF_SECURITY_ALARM_PANEL,
                        CONF_SECURITY_AUTO_FOLLOW,
                        CONF_SECURITY_LOCK_CHECK_INTERVAL,
                        CONF_SECURITY_DELEGATE_LIGHTS_TO_NM,
                    )
                    security = SecurityCoordinator(
                        hass,
                        lock_entities=cm_config.get(CONF_SECURITY_LOCK_ENTITIES, []),
                        garage_entities=cm_config.get(CONF_SECURITY_GARAGE_ENTITIES, []),
                        entry_sensors=cm_config.get(CONF_SECURITY_ENTRY_SENSORS, []),
                        security_lights=cm_config.get(CONF_SECURITY_LIGHT_ENTITIES, []),
                        camera_entities=cm_config.get(CONF_SECURITY_CAMERA_ENTITIES, []),
                        camera_recording_enabled=cm_config.get(
                            CONF_SECURITY_CAMERA_RECORDING, False
                        ),
                        camera_record_duration=int(cm_config.get(
                            CONF_SECURITY_CAMERA_RECORD_DURATION, 30
                        )),
                        alarm_panel_entity=cm_config.get(CONF_SECURITY_ALARM_PANEL),
                        auto_follow_house_state=cm_config.get(
                            CONF_SECURITY_AUTO_FOLLOW, False
                        ),
                        lock_check_interval=int(cm_config.get(
                            CONF_SECURITY_LOCK_CHECK_INTERVAL, 30
                        )),
                        delegate_lights_to_nm=cm_config.get(
                            CONF_SECURITY_DELEGATE_LIGHTS_TO_NM, True
                        ),
                    )
                    coordinator_manager.register_coordinator(security)
                else:
                    _LOGGER.info("Security Coordinator disabled via config")

                # v3.6.24: Register Music Following Coordinator
                if cm_config.get(CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED, True):
                    from .domain_coordinators.music_following import (
                        MusicFollowingCoordinator,
                    )
                    from .const import (
                        CONF_MF_COOLDOWN_SECONDS,
                        CONF_MF_HIGH_CONFIDENCE_DISTANCE,
                        CONF_MF_PING_PONG_WINDOW,
                        CONF_MF_VERIFY_DELAY,
                        CONF_MF_UNJOIN_DELAY,
                        CONF_MF_POSITION_OFFSET,
                        CONF_MF_MIN_CONFIDENCE,
                        # v5.10.0 D2: sleep + night suppression seeds
                        CONF_MF_SLEEP_SUPPRESS,
                        CONF_MF_NIGHT_SUPPRESS_MODE,
                        DEFAULT_MF_COOLDOWN_SECONDS,
                        DEFAULT_MF_HIGH_CONFIDENCE_DISTANCE,
                        DEFAULT_MF_PING_PONG_WINDOW,
                        DEFAULT_MF_VERIFY_DELAY,
                        DEFAULT_MF_UNJOIN_DELAY,
                        DEFAULT_MF_POSITION_OFFSET,
                        DEFAULT_MF_MIN_CONFIDENCE,
                        DEFAULT_MF_SLEEP_SUPPRESS,
                        DEFAULT_MF_NIGHT_SUPPRESS_MODE,
                    )
                    mf_coordinator = MusicFollowingCoordinator(
                        hass,
                        cooldown_seconds=int(cm_config.get(
                            CONF_MF_COOLDOWN_SECONDS, DEFAULT_MF_COOLDOWN_SECONDS
                        )),
                        ping_pong_window=int(cm_config.get(
                            CONF_MF_PING_PONG_WINDOW, DEFAULT_MF_PING_PONG_WINDOW
                        )),
                        verify_delay=int(cm_config.get(
                            CONF_MF_VERIFY_DELAY, DEFAULT_MF_VERIFY_DELAY
                        )),
                        unjoin_delay=int(cm_config.get(
                            CONF_MF_UNJOIN_DELAY, DEFAULT_MF_UNJOIN_DELAY
                        )),
                        position_offset=int(cm_config.get(
                            CONF_MF_POSITION_OFFSET, DEFAULT_MF_POSITION_OFFSET
                        )),
                        min_confidence=float(cm_config.get(
                            CONF_MF_MIN_CONFIDENCE, DEFAULT_MF_MIN_CONFIDENCE
                        )),
                        high_confidence_distance=float(cm_config.get(
                            CONF_MF_HIGH_CONFIDENCE_DISTANCE, DEFAULT_MF_HIGH_CONFIDENCE_DISTANCE
                        )),
                        # v5.10.0 D2: seed sleep + night gate from CM options.
                        sleep_suppress=bool(cm_config.get(
                            CONF_MF_SLEEP_SUPPRESS, DEFAULT_MF_SLEEP_SUPPRESS,
                        )),
                        night_suppress_mode=str(cm_config.get(
                            CONF_MF_NIGHT_SUPPRESS_MODE, DEFAULT_MF_NIGHT_SUPPRESS_MODE,
                        )),
                    )
                    coordinator_manager.register_coordinator(mf_coordinator)
                else:
                    _LOGGER.info("Music Following Coordinator disabled via config")

                # v4.0.12: Build energy entity config + auto-derive Envoy entities.
                # This runs OUTSIDE the Energy-enabled guard so HVAC can also
                # access derived entities (e.g. net_power_entity).
                from .domain_coordinators.energy_const import (
                    CONF_ENERGY_NET_POWER_ENTITY,
                    CONF_ENERGY_ENVOY_ENTITY,
                    extract_envoy_serial,
                    derive_envoy_config,
                    validate_envoy_config,
                )
                energy_entity_config: dict[str, str] = {}
                for key in cm_config:
                    if key.startswith("energy_"):
                        energy_entity_config[key] = cm_config[key]

                envoy_eid = energy_entity_config.get(CONF_ENERGY_ENVOY_ENTITY)
                if envoy_eid:
                    serial = extract_envoy_serial(envoy_eid)
                    if serial:
                        for k, v in derive_envoy_config(serial).items():
                            energy_entity_config.setdefault(k, v)

                # EC Envoy boot-decoupling cycle: replace the boolean
                # `_envoy_validation_ok` gate with `_envoy_hard_fail` which
                # is True ONLY for genuine config errors (V0 no entity / V1
                # unparseable serial / registry-absent). Boot-race / device-
                # recovery cases (registry-known + state missing/unavailable)
                # are NOT hard-fails: EC registers and runtime handles
                # None gracefully (energy_battery.py:928/945).
                #
                # The deferred re-validation at EVENT_HOMEASSISTANT_STARTED
                # (see _schedule_envoy_revalidation below) re-checks the
                # repair-issue surface after the boot-race window settles.
                # NOTE (A3 reconciliation): V0/V1/registry-absent hard fails
                # raise the repair issue IMMEDIATELY below — these are
                # user-actionable config errors, not boot-race recoverable.
                # The post-settle pass at D3 refreshes/clears the same
                # entry-scoped issue id based on the live result, and the
                # ok-path clear is now conditional on EC having actually
                # been registered (A2 fix), so a transient false-positive
                # raised at startup cannot strand the operator without a
                # recovery affordance.
                from .const import CONF_ENERGY_ENABLED
                _energy_enabled = bool(cm_config.get(CONF_ENERGY_ENABLED, False))
                _envoy_hard_fail = False
                _validation = None

                if envoy_eid:
                    _validation = validate_envoy_config(hass, energy_entity_config)
                    # Hard-fail ONLY when validation reports !ok AND the
                    # underlying cause is V0/V1/registry-absent (not a
                    # boot-race degraded path — those return ok=True).
                    _envoy_hard_fail = not _validation["ok"]

                    if _envoy_hard_fail:
                        # V0/V1/registry-absent → user-actionable config
                        # error; raise repair issue immediately (NOT
                        # boot-race recoverable). Only when EC is enabled.
                        if _energy_enabled:
                            _LOGGER.error(
                                "Energy Coordinator NOT started — envoy validation "
                                "hard-failed. Errors: %s. Fix via Coordinator "
                                "Manager → Configure → Energy.",
                                _validation["errors"],
                            )
                            try:
                                from homeassistant.helpers import issue_registry as ir
                                _envoy_issue_id = (
                                    f"energy_envoy_invalid_{entry.entry_id}"
                                )
                                ir.async_create_issue(
                                    hass,
                                    DOMAIN,
                                    _envoy_issue_id,
                                    is_fixable=True,
                                    severity=ir.IssueSeverity.ERROR,
                                    translation_key="energy_envoy_invalid",
                                    translation_placeholders={
                                        "errors": ", ".join(
                                            f"{k}={v}"
                                            for k, v in _validation["errors"].items()
                                        ) or "unknown",
                                    },
                                    data={"entry_id": entry.entry_id},
                                )
                            except Exception as exc:
                                _LOGGER.warning(
                                    "Could not raise repair issue for envoy "
                                    "validation: %s", exc,
                                )
                        else:
                            _LOGGER.warning(
                                "Envoy entity set but validation hard-failed "
                                "(EC disabled, no repair issue): %s",
                                _validation["errors"],
                            )
                    else:
                        # ok=True path — may be live OR degraded. Either way
                        # we proceed with EC. Degraded means runtime will
                        # see None readings briefly until the Enphase
                        # integration's first refresh succeeds. We do NOT
                        # clear stale repair issues here — the deferred
                        # re-validation owns that, so the clear happens
                        # AFTER the boot-race window settles.
                        if _validation.get("degraded"):
                            _LOGGER.info(
                                "Envoy validation degraded at startup "
                                "(reason=%s); EC will register and degrade "
                                "gracefully. Deferred re-validation will "
                                "run at HA-started.",
                                _validation.get("degraded_reason"),
                            )
                        for w in _validation["warnings"]:
                            _LOGGER.warning("Envoy config warning: %s", w)

                # EC Envoy boot-decoupling: schedule deferred re-validation
                # (D3) iff envoy_eid is configured and EC is enabled.
                # Review D D1 fix (2026-06-12): the scheduling call was
                # previously here (pre-CM-registration), but on warm
                # options-flow reloads the HA-already-running branch fires
                # an immediate `async_call_later(0, ...)` which lands during
                # the awaited TOURateEngine.async_from_json_file() below.
                # At that moment CM has not yet been placed in
                # hass.data[DOMAIN]["coordinator_manager"] (assignment at
                # ~2489 inside the same block), so the EC-registration check
                # would fail and a spurious `envoy_now_ok_but_ec_not_registered`
                # persistent ERROR repair issue would be raised on every
                # healthy reload. Moved AFTER CM registration below so the
                # check sees a fully-installed CM. Cold-boot path is
                # unaffected — EVENT_HOMEASSISTANT_STARTED + failsafe both
                # fire well after setup completes.

                # v3.7.0-E1: Register Energy Coordinator
                # EC Envoy boot-decoupling: gate is now `not _envoy_hard_fail`
                # (V0/V1/registry-absent only). Boot-race degraded cases
                # proceed — EC's runtime handles None readings.
                if _energy_enabled and not _envoy_hard_fail:
                    from .domain_coordinators.energy import EnergyCoordinator
                    from .domain_coordinators.energy_const import (
                        CONF_ENERGY_RESERVE_SOC,
                        CONF_ENERGY_DECISION_INTERVAL,
                        CONF_ENERGY_EVSE_A_ENTITY,
                        CONF_ENERGY_EVSE_B_ENTITY,
                        CONF_ENERGY_EVSE_A_SPAN_BREAKER,
                        CONF_ENERGY_EVSE_B_SPAN_BREAKER,
                        CONF_ENERGY_L1_CHARGER_ENTITIES,
                        CONF_ENERGY_WEATHER_ENTITY,
                        CONF_ENERGY_SOLAR_CLASSIFICATION_MODE,
                        CONF_ENERGY_SOLAR_THRESHOLD_EXCELLENT,
                        CONF_ENERGY_SOLAR_THRESHOLD_GOOD,
                        CONF_ENERGY_SOLAR_THRESHOLD_MODERATE,
                        CONF_ENERGY_SOLAR_THRESHOLD_POOR,
                        DEFAULT_RESERVE_SOC,
                        DEFAULT_DECISION_INTERVAL_MINUTES,
                        DEFAULT_L1_CHARGER_ENTITIES,
                        SOLAR_CLASS_MODE_AUTOMATIC,
                    )

                    # Weather entity: use EC config, fall back to house entry
                    if CONF_ENERGY_WEATHER_ENTITY not in energy_entity_config:
                        integration = hass.data.get(DOMAIN, {}).get("integration")
                        if integration:
                            house_weather = (
                                integration.options.get(CONF_WEATHER_ENTITY)
                                or integration.data.get(CONF_WEATHER_ENTITY)
                            )
                            if house_weather:
                                energy_entity_config[CONF_ENERGY_WEATHER_ENTITY] = house_weather

                    # EVSE config — EVChargerController expects nested dicts
                    # with at minimum a "power" key per charger
                    from .domain_coordinators.energy_pool import DEFAULT_EVSE_ENTITIES
                    evse_config = {}
                    for evse_id, defaults in DEFAULT_EVSE_ENTITIES.items():
                        evse_config[evse_id] = dict(defaults)
                    # Override power entities from user config
                    evse_a_power = cm_config.get(CONF_ENERGY_EVSE_A_ENTITY)
                    if evse_a_power:
                        evse_config["garage_a"]["power"] = evse_a_power
                    evse_b_power = cm_config.get(CONF_ENERGY_EVSE_B_ENTITY)
                    if evse_b_power:
                        evse_config["garage_b"]["power"] = evse_b_power
                    # v5.12.0: SPAN breaker overrides (rename-recovery).
                    # Absent options keep the DEFAULT_EVSE_ENTITIES value —
                    # byte-identical behaviour on upgrade.
                    evse_a_breaker = cm_config.get(CONF_ENERGY_EVSE_A_SPAN_BREAKER)
                    if evse_a_breaker:
                        evse_config["garage_a"]["span_breaker"] = evse_a_breaker
                    evse_b_breaker = cm_config.get(CONF_ENERGY_EVSE_B_SPAN_BREAKER)
                    if evse_b_breaker:
                        evse_config["garage_b"]["span_breaker"] = evse_b_breaker
                    # v4.7.6 D3.4: per-EVSE self_modulates flag from config flow.
                    # Default False (Option B / smart manual-override detection).
                    if "garage_a_self_modulates" in cm_config:
                        evse_config["garage_a"]["self_modulates"] = bool(
                            cm_config.get("garage_a_self_modulates", False)
                        )
                    if "garage_b_self_modulates" in cm_config:
                        evse_config["garage_b"]["self_modulates"] = bool(
                            cm_config.get("garage_b_self_modulates", False)
                        )

                    # Smart plug entities
                    smart_plug_entities = cm_config.get(
                        CONF_ENERGY_L1_CHARGER_ENTITIES,
                        DEFAULT_L1_CHARGER_ENTITIES,
                    )
                    # v4.7.6 D6.4 / fix-up C-H2: per-plug self_modulates.
                    # Build {plug_id: {self_modulates: bool}} from per-plug
                    # config keys (`<plug_entity_id>_self_modulates`). When
                    # a plug's key is ABSENT we OMIT `self_modulates` so
                    # SmartPlugController.get_status() reports
                    # `source: "default"`. When the key is present, the
                    # bool is stored and `source: "explicit"`.
                    plug_config = {}
                    for plug_id in (smart_plug_entities or []):
                        per_plug_key = f"{plug_id}_self_modulates"
                        if per_plug_key in cm_config:
                            plug_config[plug_id] = {
                                "self_modulates": bool(
                                    cm_config.get(per_plug_key, False)
                                )
                            }
                        else:
                            # Absent — keep empty dict so source="default".
                            plug_config[plug_id] = {}

                    # Solar classification config
                    solar_mode = cm_config.get(
                        CONF_ENERGY_SOLAR_CLASSIFICATION_MODE,
                        SOLAR_CLASS_MODE_AUTOMATIC,
                    )
                    custom_solar_thresholds = None
                    if solar_mode == "custom":
                        custom_solar_thresholds = {
                            "excellent": float(cm_config.get(CONF_ENERGY_SOLAR_THRESHOLD_EXCELLENT, 100.0)),
                            "good": float(cm_config.get(CONF_ENERGY_SOLAR_THRESHOLD_GOOD, 80.0)),
                            "moderate": float(cm_config.get(CONF_ENERGY_SOLAR_THRESHOLD_MODERATE, 50.0)),
                            "poor": float(cm_config.get(CONF_ENERGY_SOLAR_THRESHOLD_POOR, 30.0)),
                        }

                    # v4.0.5: Pre-load TOU rates asynchronously to avoid
                    # blocking I/O on event loop (HA 2026.x enforcement)
                    from .domain_coordinators.energy_tou import TOURateEngine
                    from .domain_coordinators.energy_const import DEFAULT_TOU_RATE_FILE
                    tou_engine = await TOURateEngine.async_from_json_file(
                        hass, hass.config.path(""), DEFAULT_TOU_RATE_FILE,
                    )

                    energy = EnergyCoordinator(
                        hass,
                        reserve_soc=int(cm_config.get(
                            CONF_ENERGY_RESERVE_SOC, DEFAULT_RESERVE_SOC
                        )),
                        decision_interval=int(cm_config.get(
                            CONF_ENERGY_DECISION_INTERVAL,
                            DEFAULT_DECISION_INTERVAL_MINUTES,
                        )),
                        entity_config=energy_entity_config or None,
                        evse_config=evse_config,
                        smart_plug_entities=smart_plug_entities,
                        plug_config=plug_config,
                        solar_classification_mode=solar_mode,
                        custom_solar_thresholds=custom_solar_thresholds,
                        tou_engine=tou_engine,
                    )
                    coordinator_manager.register_coordinator(energy)
                elif not _energy_enabled:
                    _LOGGER.info("Energy Coordinator disabled via config")
                # else: enabled but validation failed — already logged above.

                # v3.8.0-H1: Register HVAC Coordinator
                from .const import CONF_HVAC_ENABLED
                if cm_config.get(CONF_HVAC_ENABLED, False):
                    # EC Envoy boot-decoupling: pass net_power_entity when
                    # the envoy is registry-known (validation didn't hard-fail).
                    # Boot-race degraded path still passes the entity ID —
                    # HVAC's _get_net_power() returns 0.0 for missing/None
                    # state so solar-banking conditions evaluate safely.
                    # Hard-fail (V0/V1/registry-absent) → pass None so HVAC
                    # doesn't waste a state lookup on a known-bad entity.
                    if not _envoy_hard_fail:
                        _hvac_net_power_entity = energy_entity_config.get(
                            CONF_ENERGY_NET_POWER_ENTITY
                        )
                    else:
                        _hvac_net_power_entity = None
                        _LOGGER.warning(
                            "HVAC solar banking degraded: envoy validation "
                            "hard-failed, net_power_entity unavailable. "
                            "Pre-cool decisions will skip live power input."
                        )

                    from .domain_coordinators.hvac import HVACCoordinator
                    from .domain_coordinators.hvac_const import (
                        CONF_HVAC_MAX_SLEEP_OFFSET,
                        CONF_HVAC_COMPROMISE_MINUTES,
                        CONF_HVAC_AC_RESET_TIMEOUT,
                        CONF_HVAC_FAN_ACTIVATION_DELTA,
                        CONF_HVAC_FAN_HYSTERESIS,
                        CONF_HVAC_FAN_MIN_RUNTIME,
                        CONF_HVAC_ARRESTER_ENABLED,
                        CONF_HVAC_ARRESTER_IMMUNE_PERSONS,
                        CONF_HVAC_AC_RESET_ENABLED,
                        CONF_HVAC_VACANCY_GRACE_MINUTES,
                        CONF_HVAC_VACANCY_GRACE_CONSTRAINED,
                        CONF_HVAC_MAX_OCCUPANCY_HOURS,
                        CONF_HVAC_ZONE_ENTRY_DWELL,
                        DEFAULT_MAX_SLEEP_OFFSET,
                        DEFAULT_COMPROMISE_MINUTES,
                        DEFAULT_AC_RESET_TIMEOUT,
                        DEFAULT_FAN_ACTIVATION_DELTA,
                        DEFAULT_FAN_HYSTERESIS,
                        DEFAULT_FAN_MIN_RUNTIME,
                        DEFAULT_ARRESTER_ENABLED,
                        DEFAULT_AC_RESET_ENABLED,
                        CONF_HVAC_FAN_CONTROL_ENABLED,
                        DEFAULT_FAN_CONTROL_ENABLED,
                        DEFAULT_VACANCY_GRACE_MINUTES,
                        DEFAULT_VACANCY_GRACE_CONSTRAINED,
                        DEFAULT_MAX_OCCUPANCY_HOURS,
                        DEFAULT_ZONE_ENTRY_DWELL_MINUTES,
                        # v4.5.9.2: per-house occupancy-aware cover-close delta
                        CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA,
                        DEFAULT_HVAC_OCCUPIED_COVER_CLOSE_DELTA,
                        # v4.5.10: HVAC tunables (master + 9 thresholds)
                        CONF_HVAC_SOLAR_GAIN_COVER_ENABLED,
                        DEFAULT_HVAC_SOLAR_GAIN_COVER_ENABLED,
                        CONF_HVAC_COVER_CLOSE_TEMP,
                        DEFAULT_HVAC_COVER_CLOSE_TEMP,
                        CONF_HVAC_COVER_OPEN_TEMP,
                        DEFAULT_HVAC_COVER_OPEN_TEMP,
                        CONF_HVAC_COVER_OVERRIDE_HOURS,
                        DEFAULT_HVAC_COVER_OVERRIDE_HOURS,
                        CONF_HVAC_SOLAR_BANK_FLOOR,
                        DEFAULT_HVAC_SOLAR_BANK_FLOOR,
                        CONF_HVAC_COVER_SOLAR_START_HOUR,
                        DEFAULT_HVAC_COVER_SOLAR_START_HOUR,
                        CONF_HVAC_COVER_SOLAR_END_HOUR,
                        DEFAULT_HVAC_COVER_SOLAR_END_HOUR,
                        CONF_HVAC_SOLAR_BANK_SOC_MIN,
                        DEFAULT_HVAC_SOLAR_BANK_SOC_MIN,
                        CONF_HVAC_PRECOOL_FORECAST_HIGH,
                        DEFAULT_HVAC_PRECOOL_FORECAST_HIGH,
                        CONF_HVAC_PREHEAT_FORECAST_LOW,
                        DEFAULT_HVAC_PREHEAT_FORECAST_LOW,
                    )

                    hvac = HVACCoordinator(
                        hass,
                        max_sleep_offset=float(cm_config.get(
                            CONF_HVAC_MAX_SLEEP_OFFSET, DEFAULT_MAX_SLEEP_OFFSET
                        )),
                        compromise_minutes=int(cm_config.get(
                            CONF_HVAC_COMPROMISE_MINUTES, DEFAULT_COMPROMISE_MINUTES
                        )),
                        ac_reset_timeout=int(cm_config.get(
                            CONF_HVAC_AC_RESET_TIMEOUT, DEFAULT_AC_RESET_TIMEOUT
                        )),
                        fan_activation_delta=float(cm_config.get(
                            CONF_HVAC_FAN_ACTIVATION_DELTA, DEFAULT_FAN_ACTIVATION_DELTA
                        )),
                        fan_hysteresis=float(cm_config.get(
                            CONF_HVAC_FAN_HYSTERESIS, DEFAULT_FAN_HYSTERESIS
                        )),
                        fan_min_runtime=int(cm_config.get(
                            CONF_HVAC_FAN_MIN_RUNTIME, DEFAULT_FAN_MIN_RUNTIME
                        )),
                        arrester_enabled=(arrester_enabled_flag := bool(
                            cm_config.get(
                                CONF_HVAC_ARRESTER_ENABLED,
                                DEFAULT_ARRESTER_ENABLED,
                            )
                        )),
                        ac_reset_enabled=bool(cm_config.get(
                            CONF_HVAC_AC_RESET_ENABLED, DEFAULT_AC_RESET_ENABLED
                        )),
                        vacancy_grace=int(cm_config.get(
                            CONF_HVAC_VACANCY_GRACE_MINUTES, DEFAULT_VACANCY_GRACE_MINUTES
                        )),
                        vacancy_grace_constrained=int(cm_config.get(
                            CONF_HVAC_VACANCY_GRACE_CONSTRAINED, DEFAULT_VACANCY_GRACE_CONSTRAINED
                        )),
                        max_occupancy_hours=int(cm_config.get(
                            CONF_HVAC_MAX_OCCUPANCY_HOURS, DEFAULT_MAX_OCCUPANCY_HOURS
                        )),
                        # ARREST-COMFORT-1 D2-LOW-2 fix-up (2026-08-10):
                        # eager-seed rung-3 comfort-delay knobs at HC
                        # construction so the arrester + D3 guard never
                        # read stale module defaults during the boot
                        # window between HC init and
                        # ComfortGraceMinutesNumber.async_added_to_hass.
                        # Local import: keeps top-of-file imports quiet.
                        **(lambda _cfg: {
                            "comfort_grace_min": int(_cfg.get(
                                "hvac_comfort_grace_min", 30,
                            )),
                            "comfort_soc_floor_pct": int(_cfg.get(
                                "hvac_comfort_soc_floor_pct", 80,
                            )),
                            # HVAC-PRESET-FLAP-1 D4 (2026-08-11): eager-seed
                            # the duty off-phase honesty knobs so the D5
                            # else-limb never reads defaults during the boot
                            # window between HC init and the Number/Switch
                            # entities' async_added_to_hass push.
                            "comfort_offphase_offset_f": float(_cfg.get(
                                "hvac_comfort_offphase_offset_f", 2.0,
                            )),
                            "hvac_offphase_honesty_enabled": bool(_cfg.get(
                                "hvac_offphase_honesty_enabled", True,
                            )),
                            # HVAC-GOVERNED-EXCURSION-1 D2 §4.7 kill
                            # switch. Default ON. BEGIN-ONLY.
                            "excursion_primitive_enabled": bool(_cfg.get(
                                "excursion_primitive_enabled", True,
                            )),
                        })(cm_config),
                        zone_entry_dwell=int(cm_config.get(
                            CONF_HVAC_ZONE_ENTRY_DWELL, DEFAULT_ZONE_ENTRY_DWELL_MINUTES
                        )),
                        person_zone_map=None,
                        # v4.2.29: only pass net_power_entity when envoy
                        # validation passed — otherwise HVAC predictor would
                        # read from a non-existent wrong-serial entity.
                        net_power_entity=_hvac_net_power_entity,
                        fan_control_enabled=bool(cm_config.get(
                            CONF_HVAC_FAN_CONTROL_ENABLED, DEFAULT_FAN_CONTROL_ENABLED
                        )),
                        # v4.5.9.2: occupancy-aware cover-close delta (was hardcoded 2.0°F)
                        occupied_cover_close_delta=float(cm_config.get(
                            CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA,
                            DEFAULT_HVAC_OCCUPIED_COVER_CLOSE_DELTA,
                        )),
                        # v4.5.10: solar-gain cover management master + tunables
                        solar_gain_cover_enabled=bool(cm_config.get(
                            CONF_HVAC_SOLAR_GAIN_COVER_ENABLED,
                            DEFAULT_HVAC_SOLAR_GAIN_COVER_ENABLED,
                        )),
                        cover_close_temp=float(cm_config.get(
                            CONF_HVAC_COVER_CLOSE_TEMP,
                            DEFAULT_HVAC_COVER_CLOSE_TEMP,
                        )),
                        cover_open_temp=float(cm_config.get(
                            CONF_HVAC_COVER_OPEN_TEMP,
                            DEFAULT_HVAC_COVER_OPEN_TEMP,
                        )),
                        cover_override_hours=float(cm_config.get(
                            CONF_HVAC_COVER_OVERRIDE_HOURS,
                            DEFAULT_HVAC_COVER_OVERRIDE_HOURS,
                        )),
                        solar_bank_floor=float(cm_config.get(
                            CONF_HVAC_SOLAR_BANK_FLOOR,
                            DEFAULT_HVAC_SOLAR_BANK_FLOOR,
                        )),
                        cover_solar_start_hour=int(cm_config.get(
                            CONF_HVAC_COVER_SOLAR_START_HOUR,
                            DEFAULT_HVAC_COVER_SOLAR_START_HOUR,
                        )),
                        cover_solar_end_hour=int(cm_config.get(
                            CONF_HVAC_COVER_SOLAR_END_HOUR,
                            DEFAULT_HVAC_COVER_SOLAR_END_HOUR,
                        )),
                        solar_bank_soc_min=int(cm_config.get(
                            CONF_HVAC_SOLAR_BANK_SOC_MIN,
                            DEFAULT_HVAC_SOLAR_BANK_SOC_MIN,
                        )),
                        precool_forecast_high=float(cm_config.get(
                            CONF_HVAC_PRECOOL_FORECAST_HIGH,
                            DEFAULT_HVAC_PRECOOL_FORECAST_HIGH,
                        )),
                        preheat_forecast_low=float(cm_config.get(
                            CONF_HVAC_PREHEAT_FORECAST_LOW,
                            DEFAULT_HVAC_PREHEAT_FORECAST_LOW,
                        )),
                        # v4.7.8 D2: Egress Window HVAC Pause seeds from CM
                        # config. RestoreEntity-backed switch + 2 Numbers are
                        # the runtime source of truth; these values seed
                        # install-time only.
                        egress_pause_enabled=bool(cm_config.get(
                            "hvac_egress_pause_enabled", True,
                        )),
                        egress_threshold_min=int(cm_config.get(
                            "hvac_egress_threshold_min", 3,
                        )),
                        egress_resume_delay_min=int(cm_config.get(
                            "hvac_egress_resume_delay_min", 1,
                        )),
                        # HC Pre-Conditioning master enable (D1). Install-
                        # time seed; the HVACPreConditioningSwitch is the
                        # runtime source of truth via options-write-back.
                        pre_conditioning_enabled=bool(cm_config.get(
                            "hvac_pre_conditioning_enabled", True,
                        )),
                        # Arrester Operator-Immunity (2026-08-06 —
                        # CRIT-A1 fix). Resolve to the operator's HA
                        # user id at RUNTIME via the arrester's
                        # context-user->person lookup. NO alphabetical
                        # seeding: absent OR empty option = DORMANT
                        # (feature disabled, byte-identical to pre-
                        # cycle governance) with a WARN at every setup
                        # so the operator can see their manual holds
                        # are unprotected. Explicit list = verbatim.
                        # We deliberately do NOT collapse an empty list
                        # via `or` — an empty list is a distinct
                        # operator posture ("dormant on purpose") and
                        # gets threaded verbatim; the WARN below fires
                        # regardless of absent-vs-empty because the
                        # observable behavior (no protection) is the
                        # same.
                        arrester_immune_persons=list(
                            cm_config.get(
                                CONF_HVAC_ARRESTER_IMMUNE_PERSONS, [],
                            ) or []
                        ),
                        # AC-ramp master persisted option (2026-08-06 fix).
                        # None passthrough retains the arrester's default
                        # for fresh installs; a stored True/False survives
                        # config-entry reload (which recreates the arrester).
                        ac_ramp_master_enabled=cm_config.get(
                            _CONF_HVAC_AC_RAMP_MASTER_ENABLED,
                        ),
                    )
                    coordinator_manager.register_coordinator(hvac)
                    # HVAC-TUNABLE-RUNTIME-NOT-SEEDED-1 (2026-08-21):
                    # Deterministically seed the 14 factory-tunable
                    # runtime fields from CM options at construction —
                    # closes the boot race where
                    # `Number.async_added_to_hass` may fire before the
                    # sub-controllers are visible via
                    # `hass.data[DOMAIN]["coordinator_manager"]`, leaving
                    # the coordinator running the module DEFAULT until
                    # some later write pushes the operator value across.
                    # Reuses `_HVAC_TUNABLE_DISPATCH` so a 15th tunable
                    # added there inherits this seeding for free (no
                    # hand-written per-knob call). Byte-identical when
                    # options match defaults.
                    _seed_hvac_runtime_tunables_from_options(hvac, cm_config)
                    # CRIT-A1 dormant WARN + voice-default WARN. Emit
                    # only when the arrester is ENABLED (dormant
                    # immunity is only a problem if the arrester itself
                    # is running).
                    if arrester_enabled_flag:
                        _immune_list = list(
                            cm_config.get(
                                CONF_HVAC_ARRESTER_IMMUNE_PERSONS, [],
                            ) or []
                        )
                        if not _immune_list:
                            _warn_immunity_dormant(hass)
                        else:
                            # B-M4: if the list references a person
                            # entity that doesn't exist, WARN (seeding
                            # was deleted so a stale reference is now
                            # visible). Fail-open: don't drop, just warn.
                            try:
                                known = {
                                    s.entity_id for s in
                                    hass.states.async_all("person")
                                }
                                missing = [
                                    p for p in _immune_list if p not in known
                                ]
                                if missing:
                                    _LOGGER.warning(
                                        "Arrester immunity: configured "
                                        "person(s) not registered: %s "
                                        "(no immunity will apply to "
                                        "them until their person entity "
                                        "exists)",
                                        missing,
                                    )
                            except Exception as e:  # noqa: BLE001
                                _LOGGER.debug(
                                    "Arrester immunity person-existence "
                                    "check failed: %s", e,
                                )
                        _warn_immunity_voice_default_best_effort(hass)
                else:
                    _LOGGER.info("HVAC Coordinator disabled via config")

                # v3.6.29: Register Notification Manager
                from .const import CONF_NM_ENABLED
                if cm_config.get(CONF_NM_ENABLED, False):
                    from .domain_coordinators.notification_manager import (
                        NotificationManager,
                    )
                    nm = NotificationManager(hass, cm_config)
                    coordinator_manager.set_notification_manager(nm)
                    # v4.6.9: register canonical slot (latent bug fix — was never
                    # set, so NMAcknowledgeButton.available and the three NM
                    # service handlers always read None from hass.data[DOMAIN]).
                    hass.data[DOMAIN]["notification_manager"] = nm
                    # B-M2 + LOW-A3: fire the "Temp Arrester Override was
                    # active pre-restart" LOW NM note now that NM exists.
                    _fire_temp_arrester_override_lost_note(hass)
                    # v4.6.9: notify NMAcknowledgeButton that NM is ready
                    try:
                        from homeassistant.helpers.dispatcher import async_dispatcher_send
                        from .domain_coordinators.signals import SIGNAL_NM_READY
                        async_dispatcher_send(hass, SIGNAL_NM_READY)
                    except Exception:
                        _LOGGER.debug(
                            "SIGNAL_NM_READY dispatch failed (non-fatal)",
                            exc_info=True,
                        )
                else:
                    _LOGGER.info("Notification Manager disabled via config")

                # v4.7.34 Phase 1 D1: register OptimizationCoordinator AFTER
                # HVAC + NM exist so the broker can locate the override
                # arrester and NM can route severity-high findings. The
                # optimizer is priority=5 (lowest, runs last in batches).
                try:
                    from .domain_coordinators.optimization import (
                        OptimizationCoordinator,
                    )
                    optimization = OptimizationCoordinator(hass)
                    coordinator_manager.register_coordinator(optimization)
                    _LOGGER.info(
                        "Optimization Coordinator registered (priority=%d)",
                        optimization.priority,
                    )
                except Exception:
                    _LOGGER.warning(
                        "Optimization Coordinator registration failed "
                        "(non-fatal — feature degrades to no-op)",
                        exc_info=True,
                    )

                # B1 fix: assign coordinator_manager to hass.data BEFORE
                # async_start() so that SIGNAL_ENERGY_COORDINATOR_READY
                # subscribers (e.g. EC sub-switches in _handle_ec_ready) can
                # look up the coordinator via hass.data[DOMAIN]["coordinator_manager"]
                # at signal-fire time.  Mirrors the SIGNAL_DATABASE_READY /
                # SIGNAL_NM_READY pattern: hass.data slot is set before the
                # signal is dispatched.  The coordinator_manager object is
                # fully constructed at this point; async_start() merely drives
                # async_setup() on each coordinator, so the earlier publish is safe.
                hass.data[DOMAIN]["coordinator_manager"] = coordinator_manager
                await coordinator_manager.async_start()
                _LOGGER.info("Domain Coordinator Manager initialized and started")

                # HVAC-TUNABLE-RUNTIME-NOT-SEEDED-1 zone-arm (2026-08-21):
                # The per-zone AC kWh Rate Threshold Number
                # (`_hvac_zone_kwh_threshold_factory`, number.py:2467)
                # persists via HA RestoreEntity — NOT entry.options — so
                # it can't ride the sub-controller seed above. It writes
                # `zone.kwh_rate_threshold` on a ZoneState that only
                # exists after `HVACCoordinator.async_setup()` has run
                # `async_discover_zones()` (hvac.py:815), which happens
                # inside `coordinator_manager.async_start()`. Hence a
                # SECOND call site here, deliberately after async_start:
                # ordering-required, not stylistic. Fails UNSAFE without
                # this seed — a boot race drops the runtime from the
                # operator's 1.30 to the dataclass default 0.8, doubling
                # detection sensitivity and nudge frequency.
                try:
                    hvac_coord = coordinator_manager.coordinators.get("hvac")
                    if hvac_coord is not None:
                        await _seed_hvac_zone_kwh_thresholds_from_restore(
                            hass, hvac_coord
                        )
                except Exception:  # noqa: BLE001
                    _LOGGER.debug(
                        "Per-zone AC kWh threshold seed failed (non-fatal)",
                        exc_info=True,
                    )

                # EC Envoy boot-decoupling: schedule deferred re-validation
                # AFTER CM registration (Review D D1 fix). On warm reloads
                # the scheduler short-circuits to async_call_later(0, ...),
                # which now lands with CM already in hass.data so
                # `_ec_registered()` does not race a half-built CM. Cold
                # boot fires at EVENT_HOMEASSISTANT_STARTED or the failsafe
                # timeout — both well after this point.
                if envoy_eid and _energy_enabled:
                    _schedule_envoy_revalidation(
                        hass, entry, energy_entity_config,
                    )

                # v4.6.10 D1: Stash setup telemetry — LAST thing in CM init block.
                # Failure here is non-fatal; integration is fully functional without it.
                # Review fix A-M1: use module-top dt_util import.
                try:
                    if _setup_started is not None:
                        _setup_completed = dt_util.utcnow()
                        _duration_s = (_setup_completed - _setup_started).total_seconds()
                        _room_count = sum(
                            1
                            for _ce in hass.config_entries.async_entries(DOMAIN)
                            if _ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM
                        )
                        hass.data[DOMAIN]["setup_telemetry"] = {
                            "started": _setup_started,
                            "completed": _setup_completed,
                            "duration_seconds": _duration_s,
                            "coordinator_count": len(coordinator_manager.coordinators),
                            "room_count": _room_count,
                        }
                        _LOGGER.debug(
                            "v4.6.10: setup telemetry captured: duration=%.3fs "
                            "coordinators=%d rooms=%d",
                            _duration_s,
                            len(coordinator_manager.coordinators),
                            _room_count,
                        )
                except Exception:
                    _LOGGER.debug("v4.6.10: setup telemetry stash failed (non-fatal)", exc_info=True)

                # v4.6.11 D1: Full pipeline — construct → load_baselines on async_start
                # (manager.py) → record_observation → save_baselines → store_event →
                # anomaly_log row visible via URARecentAnomaliesSensor.
                # NOTE (Review B L1): no NM cascade for this metric — setup_duration
                # is internal instrumentation, not an operator-facing alert. Analytics
                # consumers read anomaly_log directly; activity_log carries the audit
                # trail. If a future metric needs operator notification, wire NM at
                # the store_event call site, not here.
                #
                # Bug Class #19: use entry.async_create_background_task so the task is
                # tracked and cancelled on entry unload.
                # Review fix H1: wrap the scheduling call itself in try/except so a
                # scheduling failure doesn't mask as "CM init failed" at the outer except.
                try:
                    async def _push_setup_observation():
                        try:
                            _cm = hass.data.get(DOMAIN, {}).get("coordinator_manager")
                            if _cm is None:
                                return
                            _det = getattr(_cm, "_setup_anomaly_detector", None)
                            if _det is None:
                                return
                            _telem = hass.data.get(DOMAIN, {}).get("setup_telemetry")
                            if _telem is None:
                                return
                            _dur = _telem.get("duration_seconds")
                            if _dur is None:
                                return
                            _anomaly = _det.record_observation(
                                metric_name="setup_duration_seconds",
                                scope="house",
                                value=float(_dur),
                            )
                            # save_baselines ALWAYS — even when no anomaly returned.
                            # Without this, the baseline never persists and
                            # minimum_samples=10 is unreachable across restarts.
                            #
                            # Review B M1 — intentional cadence divergence from peers:
                            # HVAC/presence/security/music save baselines at teardown
                            # (their metrics fire many times per session). CM's
                            # setup_duration fires exactly once per boot; teardown-only
                            # save would lose the observation if HA crashes before
                            # clean shutdown. Do NOT "align" this to the peer pattern.
                            await _det.save_baselines()
                            if _anomaly is not None:
                                from .domain_coordinators.anomaly_event import (
                                    AnomalyEvent,
                                    AnomalyType,
                                    build_context_json,
                                    map_diag_severity,
                                )
                                # Review A M3: include house_state so anomaly_log
                                # rows for the CM are queryable alongside peer
                                # rows that all carry this column. save_anomaly_event
                                # reads payload_dict["house_state"] (database.py:4642).
                                _house_state: str | None = None
                                try:
                                    _hsm = getattr(_cm, "_house_state_machine", None)
                                    if _hsm is not None:
                                        _house_state = str(_hsm.state)
                                except Exception:
                                    _house_state = None
                                _ctx = build_context_json(
                                    source_signal="URA_SETUP_COMPLETE",
                                    extra={
                                        "duration_seconds": _dur,
                                        "coordinator_count": _telem.get("coordinator_count"),
                                        "room_count": _telem.get("room_count"),
                                    },
                                )
                                if _house_state is not None:
                                    _ctx["house_state"] = _house_state
                                _event = AnomalyEvent(
                                    coordinator="coordinator_manager",
                                    type="coordinator_manager.setup_duration_seconds",
                                    severity=map_diag_severity(_anomaly.severity),
                                    anomaly_type=AnomalyType.POINT_IN_TIME,
                                    detected_at=_anomaly.timestamp.isoformat(),
                                    payload=_ctx,
                                    observed_value=_anomaly.observed_value,
                                    expected_mean=_anomaly.expected_mean,
                                    expected_std=_anomaly.expected_std,
                                    z_score=round(_anomaly.z_score, 3),
                                    sample_size=_anomaly.sample_size,
                                )
                                await _det.store_event(_event)
                                _LOGGER.info(
                                    "v4.6.11 D1: setup_duration_seconds anomaly emitted: "
                                    "z=%.2f severity=%s dur=%.2fs",
                                    _anomaly.z_score, _anomaly.severity.value, _dur,
                                )
                                _activity_logger = hass.data.get(DOMAIN, {}).get("activity_logger")
                                if _activity_logger:
                                    await _activity_logger.log(
                                        coordinator="coordinator_manager",
                                        action="anomaly",
                                        description=(
                                            f"Setup duration anomaly: "
                                            f"{_dur:.2f}s "
                                            f"(z={_anomaly.z_score:.2f})"
                                        ),
                                        importance="notable",
                                        details={
                                            "type": "coordinator_manager.setup_duration_seconds",
                                            "z_score": round(_anomaly.z_score, 3),
                                            "duration_seconds": _dur,
                                        },
                                    )
                        except Exception:
                            _LOGGER.debug(
                                "v4.6.10: setup anomaly observation push failed (non-fatal)",
                                exc_info=True,
                            )

                    entry.async_create_background_task(
                        hass,
                        _push_setup_observation(),
                        "ura_setup_duration_observation",
                    )
                except Exception:
                    _LOGGER.debug(
                        "v4.6.10: setup anomaly observation scheduling failed (non-fatal)",
                        exc_info=True,
                    )
            except Exception as e:
                _LOGGER.error("Failed to initialize Coordinator Manager: %s", e)
                import traceback
                _LOGGER.error("Traceback: %s", traceback.format_exc())
        else:
            _LOGGER.warning(
                "Domain coordinators NOT enabled. "
                "Set domain_coordinators_enabled=True in integration options. "
                "merged_config keys: %s",
                list(merged_config.keys()),
            )

        # v3.6.0-c1: Register house state services
        await _async_register_presence_services(hass)

        # v3.6.0-c2: Register safety services
        await _async_register_safety_services(hass)

        # v3.6.0-c3: Register security services
        await _async_register_security_services(hass)

        # v3.6.29: Register notification manager services
        await _async_register_notification_services(hass)

        # setup/unload symmetry: every service registered above must be
        # released on integration-entry unload, otherwise reload
        # accumulates ghost copies and `hass.services.async_services()[DOMAIN]`
        # grows unbounded. The service handlers are integration-scoped
        # (singletons keyed on DOMAIN); their owning lifecycle is the
        # integration entry. REUSED `entry.async_on_unload` pattern at
        # :2399 (Zone Manager update-listener) and :2627
        # (Coordinator Manager update-listener).
        for _service_name in (
            # _async_register_presence_services
            "set_house_state",
            "clear_house_state_override",
            "fan_recheck_force_restore",
            # _async_register_safety_services
            "test_safety_hazard",
            # _async_register_security_services
            "security_arm",
            "security_disarm",
            "authorize_guest",
            "add_expected_arrival",
            # _async_register_notification_services
            "acknowledge_notification",
            "test_notification",
            "test_inbound",
            # NM Cycle C fix-up (2026-07-20, D5/B-MED-2): register
            # symmetric unload for `nm_mute_person_channel` so entry
            # unload cleans it up (matches its now-central registration
            # in `_async_register_notification_services`).
            "nm_mute_person_channel",
            # _async_register_memory_services (Memory MVP Stage 1)
            "memory_query",
        ):
            # default-arg binding pins _service_name into each lambda's
            # closure so the loop variable doesn't capture-by-reference
            # (every lambda would otherwise remove only the last name).
            # A-LOW-2 (Review A): guard with `has_service` so partial-
            # setup unload (where some _async_register_*_services
            # helpers raised mid-call) doesn't emit up to 10 spurious
            # "Unable to remove unknown service" warnings from HA core
            # (homeassistant/core.py:2680-2682).
            entry.async_on_unload(
                lambda _name=_service_name: (
                    hass.services.async_remove(DOMAIN, _name)
                    if hass.services.has_service(DOMAIN, _name)
                    else None
                )
            )

        # Set up aggregation sensors (sensor and binary_sensor platforms)
        # These will be registered via the platform files
        await hass.config_entries.async_forward_entry_setups(entry, INTEGRATION_PLATFORMS)

        # v5.94.0 (device/entity de-frag D-NEST): stamp via_device_id AFTER
        # forwarded setups so device rows exist. Idempotent + guarded so this
        # call from INTEGRATION is safe even before CM has registered its
        # coordinator devices (missing parent → skip; re-stamped on the CM
        # entry's own D-NEST call).
        try:
            from ._devices import (
                async_stamp_via_device_tree,
                async_schedule_device_tree_sweep,
            )
            await async_stamp_via_device_tree(hass)
            # FIX-2 (2026-09-03, Review D D-LEAK-2): also schedule the
            # at-start cover-all sweep from INTEGRATION so a boot where
            # the CM entry is late/absent still gets the sweep.
            # `async_schedule_device_tree_sweep` is idempotent.
            async_schedule_device_tree_sweep(hass)
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "D-NEST: via_device stamping from INTEGRATION setup raised (non-fatal)",
                exc_info=True,
            )

        # RELOAD-WATCHDOG-HAZARD fix-up (2026-08-15, H-1 / B-HIGH-1):
        # Seed the integration-entry snapshot BEFORE the update listener
        # is armed so the first post-restart options save has a real
        # baseline to diff against (else `old={}` → `changed_keys` =
        # `set(new.keys())` → subset-check false → cascade). Mirrors the
        # CM seed at :4265; same ordering rule as CM (seed then arm).
        _seed_integration_last_applied_options(hass, entry)

        # v3.2.5: Add update listener to reload entry when options change
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))

        # v3.9.4: Register URA Dashboard panel (panel_custom with auth passthrough)
        import os
        frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
        if os.path.isdir(frontend_path):
            try:
                from homeassistant.components.http import StaticPathConfig
                panel_url = f"/{DOMAIN}_panel"
                await hass.http.async_register_static_paths(
                    [StaticPathConfig(panel_url, frontend_path, False)]
                )
                # setup/unload symmetry: HA's `async_register_static_paths`
                # adds aiohttp routes directly to `app.router` (see
                # homeassistant/components/http/__init__.py:512-543) and
                # exposes NO public removal API in current HA versions.
                # Routes live for the process lifetime; on entry reload
                # the duplicate registration may raise depending on
                # aiohttp version (caught by the surrounding except —
                # B-LOW-3 (Review B, 2026-06-03): the raise behavior
                # was not verified against aiohttp source, so the
                # except is defensive rather than guaranteed).
                # Not a leak we can patch from URA's side. Documenting
                # the gap so reviewers don't expect a paired teardown.
                from homeassistant.components import panel_custom
                from homeassistant.components import frontend as _ha_frontend
                _panel_path = "ura-dashboard"
                await panel_custom.async_register_panel(
                    hass,
                    webcomponent_name="ura-dashboard-panel",
                    frontend_url_path=_panel_path,
                    sidebar_title="URA",
                    sidebar_icon="mdi:home-automation",
                    module_url=f"{panel_url}/ura-panel.js",
                    embed_iframe=False,
                    require_admin=False,
                    config={},
                )
                # setup/unload symmetry: pair the panel registration
                # with a teardown via `frontend.async_remove_panel`.
                # Verified at homeassistant/components/frontend/__init__.py:394
                # (signature: async_remove_panel(hass, frontend_url_path,
                # *, warn_if_unknown=True)). Without this, every reload
                # leaves a ghost sidebar entry that fails when clicked.
                entry.async_on_unload(
                    lambda _p=_panel_path: _ha_frontend.async_remove_panel(
                        hass, _p, warn_if_unknown=False,
                    )
                )
                _LOGGER.info("URA Dashboard panel registered at /ura-dashboard")
            except Exception as exc:
                _LOGGER.warning("Failed to register URA Dashboard panel: %s", exc)

        # v3.12.0: Register URA Dashboard v3 panel (separate sidebar entry)
        frontend_v3_path = os.path.join(os.path.dirname(__file__), "frontend-v3")
        if os.path.isdir(frontend_v3_path):
            try:
                from homeassistant.components.http import StaticPathConfig
                panel_v3_url = f"/{DOMAIN}_panel_v3"
                await hass.http.async_register_static_paths(
                    [StaticPathConfig(panel_v3_url, frontend_v3_path, False)]
                )
                # See note above re. static-path teardown gap (no HA API).
                from homeassistant.components import panel_custom
                from homeassistant.components import frontend as _ha_frontend
                _panel_v3_path = "ura-dashboard-v3"
                await panel_custom.async_register_panel(
                    hass,
                    webcomponent_name="ura-dashboard-panel-v3",
                    frontend_url_path=_panel_v3_path,
                    sidebar_title="URA Dashboard",
                    sidebar_icon="mdi:view-dashboard",
                    module_url=f"{panel_v3_url}/ura-panel-v3.js",
                    embed_iframe=False,
                    require_admin=False,
                    config={},
                )
                # setup/unload symmetry: paired teardown for the v3 panel.
                entry.async_on_unload(
                    lambda _p=_panel_v3_path: _ha_frontend.async_remove_panel(
                        hass, _p, warn_if_unknown=False,
                    )
                )
                _LOGGER.info("URA Dashboard v3 panel registered at /ura-dashboard-v3")
            except Exception as exc:
                _LOGGER.warning("Failed to register URA Dashboard v3 panel: %s", exc)

        _LOGGER.info("Integration entry setup complete with aggregation sensors")
        return True
    
    # =========================================================================
    # v3.6.0: Zone Manager entry handling
    # =========================================================================
    if entry_type == ENTRY_TYPE_ZONE_MANAGER:
        _LOGGER.info("Setting up Zone Manager entry")

        # Register Zone Manager device under THIS config entry (not integration)
        from homeassistant.helpers import device_registry as dr
        dev_reg = dr.async_get(hass)
        dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "zone_manager")},
            name="URA: Zone Manager",
            manufacturer="Universal Room Automation",
            model="Zone Manager",
            sw_version=VERSION,
        )

        # v3.6.0-c2.1: Clean up orphaned zone devices with slugified identifiers.
        # Prior to this fix, select.py used zone_slug (lowercased+underscored) for
        # device identifiers while aggregation.py used raw zone names, creating
        # duplicate "Unnamed device" entries. Remove any zone_<slug> devices that
        # don't match a zone_<RawName> pattern.
        try:
            merged_zm = {**entry.data, **entry.options}
            raw_zone_ids = {f"zone_{zn}" for zn in merged_zm.get("zones", {})}
            for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
                for ident_domain, identifier in device.identifiers:
                    if (
                        ident_domain == DOMAIN
                        and identifier.startswith("zone_")
                        and identifier != "zone_manager"
                        and identifier not in raw_zone_ids
                    ):
                        dev_reg.async_remove_device(device.id)
                        _LOGGER.info(
                            "Removed orphaned slugified zone device: %s", identifier
                        )
        except Exception as e:
            _LOGGER.warning("Zone slug cleanup failed (non-fatal): %s", e)

        # v4.7.4.3: customize_buckets eager migration REMOVED (Bug Class #46).
        # v4.7.4 and v4.7.4.1 both called async_update_entry from inside
        # async_setup_entry (directly or via a deferred task), triggering the
        # update_listener → async_create_task(reload) chain within the
        # bootstrap-2 budget window, causing double invocation of
        # async_setup_entry and a 120s cold-boot timeout.
        # The flag is now derived lazily at read time in
        # _build_dynamic_preset_schema (config_flow.py) — zero side effects,
        # no update_entry call, no reload. Value persists naturally on next
        # form save by the user.

        # Store zone data reference for music_following and other lookups
        if "zones" not in hass.data[DOMAIN]:
            hass.data[DOMAIN]["zones"] = {}
        hass.data[DOMAIN]["zone_manager_entry"] = entry

        # Forward sensor/binary_sensor platforms — zone sensors created here
        await hass.config_entries.async_forward_entry_setups(entry, INTEGRATION_PLATFORMS)

        # v5.94.0 (device/entity de-frag D-NEST): stamp zone devices under
        # zone_manager after forwarded setups.
        try:
            from ._devices import async_stamp_via_device_tree
            await async_stamp_via_device_tree(hass)
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "D-NEST: via_device stamping from Zone Manager setup raised (non-fatal)",
                exc_info=True,
            )

        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        _LOGGER.info("Zone Manager entry setup complete")
        return True

    # =========================================================================
    # v3.6.0: Coordinator Manager entry handling
    # =========================================================================
    if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:
        _LOGGER.info("Setting up Coordinator Manager entry")

        # STEP D7 fix-up B-MED-1/2 (2026-08-19): one-time reconcile of the
        # retired CONF_CHATTER_QUARANTINE_ENABLED bool into CONF_CHATTER_MODE.
        # The retirement removes the two-mechanism drift where a pre-D7
        # operator with the old bool = False had no UI to recover. Idempotent:
        # only runs when the old key is still present in options; deletes it
        # after the reconcile. Preserves disable-intent (bool False -> mode
        # off); a True or missing pre-D7 bool leaves mode at its current /
        # default value (shadow).
        try:
            from .const import (  # noqa: PLC0415
                CHATTER_MODE_OFF,
                CONF_CHATTER_MODE,
                CONF_CHATTER_QUARANTINE_ENABLED,
            )
            if CONF_CHATTER_QUARANTINE_ENABLED in entry.options:
                old_bool = bool(entry.options.get(CONF_CHATTER_QUARANTINE_ENABLED))
                _new_opts = dict(entry.options)
                _new_opts.pop(CONF_CHATTER_QUARANTINE_ENABLED, None)
                if not old_bool and CONF_CHATTER_MODE not in entry.options:
                    _new_opts[CONF_CHATTER_MODE] = CHATTER_MODE_OFF
                    _LOGGER.info(
                        "STEP D7 migrate: pre-D7 chatter disable-intent "
                        "preserved; CONF_CHATTER_MODE=off (entry=%s)",
                        entry.entry_id,
                    )
                else:
                    _LOGGER.info(
                        "STEP D7 migrate: retired CONF_CHATTER_QUARANTINE_"
                        "ENABLED dropped (was %s; mode select is now the "
                        "single UI, entry=%s)",
                        old_bool, entry.entry_id,
                    )
                hass.config_entries.async_update_entry(entry, options=_new_opts)
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.debug(
                "STEP D7 chatter-migrate raised (non-fatal)", exc_info=True,
            )

        # NM Cycle A-2 fix-up (B1, 2026-07-20): flush the process-wide
        # NM knob cache at CM setup. Restart / config-entry reload paths
        # rebuild `entry.options`; a stale cache from the previous
        # incarnation would otherwise silently shadow the new values
        # until the first options-update listener fire.
        try:
            from .domain_coordinators._nm_cycle_a import invalidate_knob_cache
            invalidate_knob_cache()
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.warning(
                "NM Cycle A-2: invalidate_knob_cache at CM setup raised (non-fatal)",
                exc_info=True,
            )

        # v5.94.1 A-MED (2026-09-03): shell cleanup runs BEFORE the CM
        # `async_get_or_create` below — with duplicate same-identifier
        # devices persisted from the prior boot, get_or_create resolves
        # via the last-writer-wins identifier index and CAN bind the
        # SHELL to the CM entry (shell.config_entries becomes
        # {parent, CM}, guard-1 sole-owner==\{parent\} then permanently
        # excludes it; CM entities re-home onto the shell). Running
        # cleanup first — against the persisted post-rehome state where
        # the shell is still 0-entity + sole-parent-owned — ensures
        # get_or_create resolves to a clean slot (or mints anew).
        # v5.94.1 FIX 1 (2026-09-03): remove empty coordinator-shell devices
        # left on the INTEGRATION/parent entry after v5.94.0 D-REHOME moved
        # coordinator entities to the CM entry. HA does NOT auto-remove a
        # device when its last entity migrates to a DIFFERENT config entry
        # (helpers/device_registry.py), so three empty shells lingered:
        # (DOMAIN, "coordinator_manager") / "security_coordinator" /
        # "music_following_coordinator") plus any other coord identifier
        # that meets the predicate. Removal is durable because the parent
        # entry no longer forwards any coordinator platform (see
        # INTEGRATION_PLATFORMS + sensor.py:161-185) — nothing will
        # recreate them. MUST run BEFORE the D-NEST stamp so the sweep's
        # same-identifier resolution (FIX 2) picks the surviving real
        # device on the CM entry.
        try:
            from ._devices import async_cleanup_parent_entry_shells
            parent_entry_id = entry.data.get(CONF_INTEGRATION_ENTRY_ID)
            if not parent_entry_id:
                # v5.94.2: pre-existing migrated CM entries predate the
                # CONF_INTEGRATION_ENTRY_ID stamping (written only at
                # migration-create time, see _ensure_coordinator_manager_entry
                # ~:968), so entry.data lacks it and the shell cleanup would
                # silently no-op. Resolve the single INTEGRATION entry directly.
                for _e in hass.config_entries.async_entries(DOMAIN):
                    if _e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                        parent_entry_id = _e.entry_id
                        break
            if parent_entry_id:
                # Pass CM entry_id as the not-CM-owned safety guard —
                # the REAL coord devices live on the CM entry, so any
                # candidate carrying it MUST be spared.
                await async_cleanup_parent_entry_shells(
                    hass, parent_entry_id, cm_entry_id=entry.entry_id,
                )
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.warning(
                "v5.94.1 FIX 1: shell-cleanup guard raised (non-fatal)",
                exc_info=True,
            )

        # Register Coordinator Manager device under THIS config entry
        from homeassistant.helpers import device_registry as dr
        dev_reg = dr.async_get(hass)
        dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )

        # Forward sensor/binary_sensor platforms — coordinator sensors created here
        # v4.2.3: CM also gets number platform for ZoneEntryDwellNumber
        cm_platforms = list(INTEGRATION_PLATFORMS) + [Platform.NUMBER]
        await hass.config_entries.async_forward_entry_setups(entry, cm_platforms)

        # v5.94.0 (device/entity de-frag D-NEST): stamp via_device_id across
        # URA-owned devices to restore the device-tree nesting HA 2026.9 broke
        # by removing DeviceInfo.via_device. Uses dr.async_update_device — no
        # entry reload (INV-6).
        # HIGH-B3 (2026-09-03): concurrent per-domain entry setup means an
        # inline stamp can\'t see devices created by later-completing entries.
        # Schedule a cover-all sweep via async_at_started AND run one inline
        # pass now to catch anything already registered.
        # v5.94.1 B1 (2026-09-03): schedule the at-started sweep OUTSIDE
        # the stamp try/except — a stamp raise must NOT skip sweep
        # scheduling (that's the only cover-all pass; without it any
        # devices created by later-completing entries stay unparented).
        try:
            from ._devices import async_stamp_via_device_tree
            await async_stamp_via_device_tree(hass)
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "D-NEST: via_device stamping from CM setup raised (non-fatal)",
                exc_info=True,
            )
        try:
            from ._devices import async_schedule_device_tree_sweep
            async_schedule_device_tree_sweep(hass)
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "D-NEST: at-started sweep scheduling from CM setup raised (non-fatal)",
                exc_info=True,
            )

        # v5.94.0 (device/entity de-frag D1): guarded removal of dead
        # `URA: Music Following` device records. FIX-4 (2026-09-03,
        # Review D live-registry): the dead identifier is
        # `(DOMAIN, "coordinator_music_following")` — NOT bare
        # `music_following` (the initial build targeted the wrong id and
        # was a silent no-op). Two records exist (one per config entry),
        # each with 0 entities and disabled_by=user. NOTE:
        # `music_following_coordinator` (different id!) is the LIVE
        # device that owns `music_following_health` — do NOT touch it.
        # `async_get_device()` returns only one record; iterate
        # `dev_reg.devices.values()` to catch both.
        # Safety: skip removal if ANY entity still points at the device.
        try:
            from homeassistant.helpers import entity_registry as er
            dev_reg2 = dr.async_get(hass)
            dead_ident = (DOMAIN, "coordinator_music_following")
            ent_reg2 = er.async_get(hass)
            removed = 0
            for _device in list(dev_reg2.devices.values()):
                if dead_ident not in _device.identifiers:
                    continue
                remaining = er.async_entries_for_device(
                    ent_reg2, _device.id, include_disabled_entities=True,
                )
                if not remaining:
                    dev_reg2.async_remove_device(_device.id)
                    removed += 1
                    _LOGGER.info(
                        "D1: removed dead device %s with identifier "
                        "(DOMAIN, 'coordinator_music_following') (0 entities)",
                        _device.id,
                    )
                else:
                    _LOGGER.info(
                        "D1: dead-device removal SKIPPED for %s — "
                        "(DOMAIN, 'coordinator_music_following') still has %d entities",
                        _device.id, len(remaining),
                    )
            if removed:
                _LOGGER.info(
                    "D1: removed %d dead 'coordinator_music_following' device record(s)",
                    removed,
                )
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "D1: dead-device cleanup guard raised (non-fatal)",
                exc_info=True,
            )

        # v4.7.2 D2 / v4.7.3 D4: defensive entity_registry device-reassignment.
        # Reassigns the switch (v4.7.2 D2) and two number entities (v4.7.3 D4)
        # from the Energy Coordinator device to the HVAC Coordinator device.
        # Idempotent — no-ops if HA already moved the entity.
        #
        # Look up each entity by unique_id (stable per plan spec) — entity_id is
        # generated by HA from friendly name and is NOT predictable from the
        # unique_id pattern.  Verified live 2026-05-28: actual entity_id is
        # `switch.ura_energy_coordinator_dynamic_preset_overrides` (slugified
        # from friendly_name), NOT the naïve f"switch.{DOMAIN}_..." pattern.
        #
        # List of (platform, unique_id) tuples to migrate → HVAC Coordinator.
        _HVAC_DEVICE_MIGRATIONS = [
            ("switch", f"{DOMAIN}_energy_dynamic_preset_enabled"),        # v4.7.2 D2
            ("number", f"{DOMAIN}_energy_dynamic_preset_dwell_minutes"),   # v4.7.3 D4
            ("number", f"{DOMAIN}_energy_dynamic_preset_hysteresis_f"),    # v4.7.3 D4
            # v4.7.7 B3: DPM observability sensors — global aggregate +
            # per-zone Active Bucket + Range sensors — joined the master
            # switch on the HVAC Coordinator device card. Per-zone unique_ids
            # are appended in the loop below since iter_canonical_hvac_zones
            # requires hass at runtime (not at module load).
            ("sensor", f"{DOMAIN}_dynamic_preset_overrides_applied"),
        ]
        try:
            # v4.7.7 B3: extend the static list with per-zone DPM sensor
            # unique_ids. Mirrors the v4.7.2/v4.7.3 device-reassignment
            # idempotency guard below (skip if device_id already correct).
            from .domain_coordinators.hvac_zones import iter_canonical_hvac_zones
            for _z in iter_canonical_hvac_zones(hass):
                _zone_id = _z["zone_id"]
                _HVAC_DEVICE_MIGRATIONS.append(
                    ("sensor", f"{DOMAIN}_dynamic_preset_active_bucket_{_zone_id}")
                )
                _HVAC_DEVICE_MIGRATIONS.append(
                    ("sensor", f"{DOMAIN}_dynamic_preset_range_{_zone_id}")
                )
        except Exception:
            _LOGGER.debug(
                "v4.7.7 B3: per-zone DPM sensor enumeration skipped",
                exc_info=True,
            )

        try:
            from homeassistant.helpers import entity_registry as er
            from homeassistant.helpers import device_registry as dr_mod
            _er = er.async_get(hass)
            _dr = dr_mod.async_get(hass)
            _target_device = _dr.async_get_device(
                identifiers={(DOMAIN, "hvac_coordinator")}
            )
            for _platform, _unique_id in _HVAC_DEVICE_MIGRATIONS:
                _entity_id = _er.async_get_entity_id(_platform, DOMAIN, _unique_id)
                if _entity_id is None:
                    continue
                _ent_entry = _er.async_get(_entity_id)
                if _ent_entry is None:
                    continue
                if (
                    _target_device is not None
                    and _ent_entry.device_id != _target_device.id
                ):
                    _er.async_update_entity(
                        _entity_id, device_id=_target_device.id
                    )
                    _LOGGER.info(
                        "v4.7.3 D4 / v4.7.7 B3 migration: reassigned %s to "
                        "HVAC Coordinator device",
                        _entity_id,
                    )
        except Exception:
            _LOGGER.debug(
                "v4.7.3 D4 / v4.7.7 B3: entity reassignment skipped "
                "(entity not registered yet or registry unavailable)",
                exc_info=True,
            )

        # =====================================================================
        # v4.7.7 B1: orphan registry sweep for legacy
        # `dynamic_preset_bucket_*` entities.
        #
        # The class was renamed to DynamicPresetActiveBucketSensor
        # (sensor.py:6536) with unique_id
        # f"{DOMAIN}_dynamic_preset_active_bucket_{zone_id}".
        # Pre-rename entries with unique_id
        # f"{DOMAIN}_dynamic_preset_bucket_{zone_id}" have no producing
        # class and sit in Unknown state forever.
        #
        # CRITICAL: legacy prefix `dynamic_preset_bucket_` is a STRICT
        # prefix of the current `dynamic_preset_active_bucket_`. The
        # exclusion clause on the current prefix is the only thing that
        # keeps the live entities from being swept too.
        # =====================================================================
        try:
            from homeassistant.helpers import entity_registry as er
            _er = er.async_get(hass)
            _legacy_prefix = f"{DOMAIN}_dynamic_preset_bucket_"
            _current_prefix = f"{DOMAIN}_dynamic_preset_active_bucket_"
            # Materialize the entity values up-front — async_remove mutates
            # the registry mid-iteration.
            _to_remove = []
            for _ent_entry in list(_er.entities.values()):
                if _ent_entry.platform != DOMAIN:
                    continue
                if not _ent_entry.unique_id.startswith(_legacy_prefix):
                    continue
                if _ent_entry.unique_id.startswith(_current_prefix):
                    # STRICT guard: active class — never sweep.
                    continue
                _to_remove.append(_ent_entry.entity_id)
            for _entity_id in _to_remove:
                _er.async_remove(_entity_id)
                _LOGGER.info(
                    "v4.7.7 B1: removed stale dynamic_preset_bucket entity %s "
                    "(legacy unique_id; current class uses active_bucket prefix)",
                    _entity_id,
                )
        except Exception:
            _LOGGER.debug("v4.7.7 B1: orphan sweep skipped", exc_info=True)

        # =====================================================================
        # v4.7.7 A4: AC ramp sensor entity_id ↔ friendly-name scrambling fix.
        #
        # Root cause: unique_id is built from canonical zone_id (stable
        # across boots) but _attr_name uses zone_name (merged display label,
        # ordering-dependent across boots). HA generates the entity_id
        # slug from the FIRST _attr_name it saw at unique_id registration —
        # so a different merge ordering on a later boot produces the
        # mismatch: `_back_hallway` displaying "Entertainment + Master
        # Suite", etc.
        #
        # Fix: rename entity_ids to canonical zone_id form. Migration is
        # ONLY applied to the two diagnostic ramp sensors (state +
        # last_action) — neither has SensorStateClass.MEASUREMENT, so no
        # LTS history is broken. The third ramp sensor (kwh_rate) HAS
        # SensorStateClass.MEASUREMENT (sensor.py:9006) and is left alone
        # to preserve Long-Term Statistics history — accepting the
        # scrambling on that one entity. See plan §A4 LTS trade-off.
        #
        # Bug Class #46-safe: this block ONLY mutates the entity registry
        # via async_update_entity(entity_id, new_entity_id=...). It does
        # NOT call async_update_entry on the config entry, and it runs
        # BEFORE entry.add_update_listener registration below.
        # =====================================================================
        try:
            from homeassistant.helpers import entity_registry as er
            from .domain_coordinators.hvac_zones import iter_canonical_hvac_zones
            _er = er.async_get(hass)
            # The two diagnostic ramp sensor classes (no LTS). kwh_rate is
            # intentionally omitted — see block-header comment.
            _RAMP_SENSORS_NO_LTS = (
                "hvac_ac_ramp_state",
                "hvac_ac_ramp_last_action",
            )
            for _z in iter_canonical_hvac_zones(hass):
                _zone_id = _z["zone_id"]
                for _slug_root in _RAMP_SENSORS_NO_LTS:
                    _uid = f"{DOMAIN}_{_slug_root}_{_zone_id}"
                    _current_entity_id = _er.async_get_entity_id(
                        "sensor", DOMAIN, _uid,
                    )
                    if _current_entity_id is None:
                        continue
                    _canonical_entity_id = (
                        f"sensor.ura_{_slug_root}_{_zone_id}"
                    )
                    if _current_entity_id == _canonical_entity_id:
                        # Idempotent: already canonical.
                        continue
                    # Confirm the target slug isn't already taken by
                    # something else — async_update_entity raises on
                    # collision.
                    _existing = _er.async_get(_canonical_entity_id)
                    if (
                        _existing is not None
                        and _existing.unique_id != _uid
                    ):
                        _LOGGER.warning(
                            "v4.7.7 A4: cannot rename %s to %s — slug "
                            "already taken by unique_id=%s",
                            _current_entity_id,
                            _canonical_entity_id,
                            _existing.unique_id,
                        )
                        continue
                    _er.async_update_entity(
                        _current_entity_id,
                        new_entity_id=_canonical_entity_id,
                    )
                    _LOGGER.info(
                        "v4.7.7 A4 migration: renamed %s -> %s "
                        "(canonical zone_id form; resolves entity_id ↔ "
                        "friendly-name scrambling)",
                        _current_entity_id, _canonical_entity_id,
                    )
        except Exception:
            _LOGGER.debug(
                "v4.7.7 A4: ramp sensor entity_id migration skipped "
                "(entity not registered yet or registry unavailable)",
                exc_info=True,
            )

        # Seed the last-applied-options snapshot BEFORE registering the update
        # listener so the listener always observes a populated snapshot. A race
        # between seeding and registration is impossible: both run synchronously
        # on the single-threaded asyncio loop with no await between them. If a
        # future path ever fires the listener with an empty snapshot, the diff
        # degrades to "all keys look new" -> suppress branch if all-new keys are
        # allowlisted, otherwise reload. Either outcome is safe.
        _seed_cm_last_applied_options(hass, entry)
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        _LOGGER.info("Coordinator Manager entry setup complete")
        return True

    # =========================================================================
    # v3.3.2: Legacy zone entry handling (deprecated — migrated to Zone Manager)
    # =========================================================================
    if entry_type == ENTRY_TYPE_ZONE:
        zone_name = entry.data.get(CONF_ZONE_NAME, "Unknown")
        _LOGGER.warning(
            "Legacy zone entry '%s' found — should have been migrated to Zone Manager. "
            "Skipping setup; zone sensors are now managed by the Zone Manager entry.",
            zone_name,
        )
        return True
    
    # Room entry - normal setup
    _LOGGER.info(
        "Setting up Universal Room Automation for room: %s",
        entry.data.get("room_name")
    )
    
    # Initialize database (shared across all rooms — use existing if already created).
    # v4.0.17: Use asyncio.Lock to prevent race where 31 room entries all see
    # database=None simultaneously during startup and each create a write worker.
    database = hass.data[DOMAIN].get("database")
    if database is None:
        db_lock = hass.data[DOMAIN].setdefault("_db_init_lock", asyncio.Lock())
        async with db_lock:
            # Re-check after acquiring lock — another entry may have created it
            database = hass.data[DOMAIN].get("database")
            if database is None:
                database = UniversalRoomDatabase(hass)
                if await database.initialize():
                    await database.start_write_worker()
                    hass.data[DOMAIN]["database"] = database
                    _LOGGER.info("Database initialized successfully")
                    # v4.6.5.3 M2: dispatch SIGNAL_DATABASE_READY so subscribed
                    # sensors can run their initial DB-dependent load without
                    # polling. (Second DB-init site — CM entry typically hits
                    # the first one above; this branch is for entry-type
                    # orderings where CM is not first.)
                    try:
                        from homeassistant.helpers.dispatcher import async_dispatcher_send
                        from .domain_coordinators.signals import SIGNAL_DATABASE_READY
                        async_dispatcher_send(hass, SIGNAL_DATABASE_READY)
                    except Exception:
                        _LOGGER.debug(
                            "SIGNAL_DATABASE_READY dispatch failed (non-fatal)",
                            exc_info=True,
                        )
                else:
                    _LOGGER.warning("Database initialization failed")
                    database = None  # Prevent use of uninitialized DB below

    # Re-read from shared state (another entry may have created it)
    database = hass.data[DOMAIN].get("database")

    # v5.47.1: memory wiring must run regardless of WHICH entry won the
    # DB-init race (both init sites + this common room path). Idempotent.
    if database is not None:
        await _async_wire_memory(hass, entry)

    # Create coordinator
    coordinator = UniversalRoomCoordinator(hass, entry)

    # v3.22.12: Pre-restore occupancy state from DB BEFORE first refresh.
    # Without this, the coordinator starts with _last_occupied_state=False.
    # The first refresh reads sensors, finds the room occupied, and
    # occupied != False triggers handle_occupancy_change → full entry
    # automation (lights on, fans on, covers open) on every reload/restart.
    # By restoring the prior state first, the "transition" is suppressed.
    if database:
        try:
            saved_state = await database.get_room_state(entry.entry_id)
            if saved_state:
                coordinator._last_occupied_state = bool(
                    saved_state.get("last_occupied_state", 0)
                )
                coordinator._failsafe_fired = bool(
                    saved_state.get("failsafe_fired", 0)
                )
                # Restore became_occupied_time (ISO string → datetime)
                # v4.2.9: Use dt_util.parse_datetime for tz-aware result
                bot_str = saved_state.get("became_occupied_time")
                if bot_str:
                    try:
                        from homeassistant.util import dt as _dt_util
                        coordinator._became_occupied_time = (
                            _dt_util.parse_datetime(bot_str) or _dt_util.now()
                        )
                    except (ValueError, TypeError):
                        pass
                _LOGGER.debug(
                    "Pre-restored room state for %s: occupied=%s, failsafe=%s",
                    entry.data.get("room_name"),
                    coordinator._last_occupied_state,
                    coordinator._failsafe_fired,
                )
        except Exception as err:
            _LOGGER.debug(
                "Could not pre-restore room state for %s (non-fatal): %s",
                entry.data.get("room_name"),
                err,
            )

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()
    
    # Store coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # v3.2.5: Add update listener to reload entry when options change
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # FIX-3 (2026-09-03, Review D D-LEAK-3): a room added at runtime (after
    # HA has started) has no chance to be stamped by the CM/INTEGRATION
    # inline pass or the once-per-boot async_at_started sweep (latch
    # already set). Run an inline stamp + re-schedule the at-start sweep
    # (allowed to re-arm; see async_schedule_device_tree_sweep).
    try:
        from ._devices import (
            async_stamp_via_device_tree,
            async_schedule_device_tree_sweep,
        )
        await async_stamp_via_device_tree(hass)
        async_schedule_device_tree_sweep(hass)
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "D-NEST: via_device stamping from ROOM setup raised (non-fatal)",
            exc_info=True,
        )

    # Substrate re-subscribe cycle (D1): fire SIGNAL_ROOM_ENTRY_LIFECYCLE so
    # PresenceCoordinator can call OccupancySubstrate.refresh_subscriptions()
    # and pick up this room's Tier-1 CONF sensors WITHOUT waiting for a
    # restart. Restores the pre-v4.7.24 (commit e165e1cb) per-room-onboarding
    # guarantee — see PLANNING_substrate_resubscribe_on_room_add.md and the
    # Master Bath Toilet 2026-07-09 regression evidence.
    # If presence has not yet installed its subscriber (cold-boot ordering:
    # ROOM entries can load before presence), the dispatch is a no-op and the
    # substrate picks this room up at its own async_setup() enumeration path.
    try:
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        from .domain_coordinators.signals import SIGNAL_ROOM_ENTRY_LIFECYCLE
        async_dispatcher_send(
            hass,
            SIGNAL_ROOM_ENTRY_LIFECYCLE,
            entry.entry_id,
            entry.data.get("room_name"),
            "loaded",
        )
    except Exception:  # noqa: BLE001 — defensive; must not block room setup
        _LOGGER.debug(
            "SIGNAL_ROOM_ENTRY_LIFECYCLE dispatch (loaded) failed (non-fatal)",
            exc_info=True,
        )

    _LOGGER.info(
        "Successfully set up Universal Room Automation for room: %s",
        entry.data.get("room_name")
    )

    return True


async def _migrate_to_v3(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Migrate a v2.x entry to v3.0.0 format.
    
    v2.x: Single entry with all room config
    v3.0.0: Integration entry + Room entries
    
    Migration:
    1. Create new integration entry with defaults
    2. Convert current entry to room entry
    """
    _LOGGER.info("Starting migration from v2.x to v3.0.0")
    
    # Check if integration entry already exists
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
            _LOGGER.info("Integration entry already exists, skipping creation")
            # Just update current entry to be a room
            new_data = dict(entry.data)
            new_data[CONF_ENTRY_TYPE] = ENTRY_TYPE_ROOM
            new_data[CONF_INTEGRATION_ENTRY_ID] = e.entry_id
            hass.config_entries.async_update_entry(entry, data=new_data)
            return
    
    # Create new integration entry with defaults
    _LOGGER.info("Creating new integration entry")
    integration_entry = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "migration"},
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION,
            CONF_OUTSIDE_TEMP_SENSOR: entry.data.get(CONF_OUTSIDE_TEMP_SENSOR),
            CONF_OUTSIDE_HUMIDITY_SENSOR: entry.data.get(CONF_OUTSIDE_HUMIDITY_SENSOR),
            CONF_WEATHER_ENTITY: entry.data.get(CONF_WEATHER_ENTITY),
            CONF_SOLAR_PRODUCTION_SENSOR: entry.data.get(CONF_SOLAR_PRODUCTION_SENSOR),
            CONF_ELECTRICITY_RATE: entry.data.get(CONF_ELECTRICITY_RATE, DEFAULT_ELECTRICITY_RATE),
            CONF_NOTIFY_SERVICE: entry.data.get(CONF_NOTIFY_SERVICE),
            CONF_NOTIFY_TARGET: entry.data.get(CONF_NOTIFY_TARGET),
            CONF_NOTIFY_LEVEL: entry.data.get(CONF_NOTIFY_LEVEL, NOTIFY_LEVEL_ERRORS),
        }
    )
    
    # Update current entry to be a room entry
    # Find integration entry ID
    integration_entry_id = None
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
            integration_entry_id = e.entry_id
            break
    
    new_data = dict(entry.data)
    new_data[CONF_ENTRY_TYPE] = ENTRY_TYPE_ROOM
    if integration_entry_id:
        new_data[CONF_INTEGRATION_ENTRY_ID] = integration_entry_id
    
    hass.config_entries.async_update_entry(entry, data=new_data)
    
    _LOGGER.info("Migration complete: entry '%s' converted to room entry", entry.title)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_type = entry.data.get(CONF_ENTRY_TYPE)
    
    if entry_type == ENTRY_TYPE_INTEGRATION:
        # v5.94.1 B3 (2026-09-03): tear down D-NEST sweep resources
        # (scheduled from INTEGRATION setup as well as CM). Idempotent —
        # whichever unload runs first drains the lists; the other no-ops.
        try:
            from ._devices import async_teardown_device_tree_sweep_handles
            async_teardown_device_tree_sweep_handles(hass)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "v5.94.1 B3: D-NEST sweep teardown at INTEGRATION unload raised (non-fatal)",
                exc_info=True,
            )
        # Unload aggregation platforms
        unload_ok = await hass.config_entries.async_unload_platforms(entry, INTEGRATION_PLATFORMS)

        # v4.2.29: Clear envoy-validation repair issue on unload so it doesn't
        # linger in Settings → Repairs after the user removes the integration
        # (Tier 2 Review CRITICAL fix). Issue id is entry-scoped to avoid
        # cross-entry collisions.
        try:
            from homeassistant.helpers import issue_registry as ir
            ir.async_delete_issue(
                hass, DOMAIN, f"energy_envoy_invalid_{entry.entry_id}"
            )
        except Exception:
            pass

        # Clean up person tracking
        # setup/unload symmetry: defensive `pop(key, None)` matches the
        # v4.6.10 review-fix B2 pattern at :2884 — never raise KeyError
        # on unload paths because a partial-setup failure may have left
        # the key absent.
        hass.data[DOMAIN].pop("person_coordinator", None)
        
        # v4.5.19: tear down TransitionDetector BEFORE removing from
        # hass.data so its event-bus listener + cleanup timer are
        # released. Without teardown, every reload leaks one listener
        # → N+1 duplicate INSERTs into room_transitions per event,
        # biasing Bayesian priors. See transitions.py:async_teardown.
        # Also fixes a latent ordering bug here: the old code at
        # lines 2270-2277 fetched transition_det AFTER deleting it
        # from hass.data, so the Bayesian-listener removal was dead
        # code that always saw None. Reorder: pop bayesian listener
        # → drop it from transition_det._listeners → teardown → delete.
        transition_det = hass.data[DOMAIN].get("transition_detector")
        bayesian_listener = hass.data[DOMAIN].pop("bayesian_transition_listener", None)
        if bayesian_listener and transition_det and hasattr(transition_det, "_listeners"):
            try:
                transition_det._listeners.remove(bayesian_listener)
            except ValueError:
                pass  # Already removed
        if transition_det is not None and hasattr(transition_det, "async_teardown"):
            try:
                await transition_det.async_teardown()
            except Exception:
                _LOGGER.warning(
                    "TransitionDetector teardown failed during unload",
                    exc_info=True,
                )

        # Clean up cross-room coordination
        # setup/unload symmetry: defensive `pop(key, None)`. Key list
        # kept as a `[...]` literal so the v4.5.19 ordering tests at
        # quality/tests/test_v4519_transition_detector_teardown.py:166,188
        # (which search for the literal `for key in ["transition_detector",
        # "pattern_learner"`) still pin the teardown→deletion ordering.
        for key in ["transition_detector", "pattern_learner", "music_following"]:
            hass.data[DOMAIN].pop(key, None)

        # v4.0.0-B1: Save and clean up Bayesian predictor
        bayesian_predictor = hass.data[DOMAIN].pop("bayesian_predictor", None)
        if bayesian_predictor:
            try:
                await bayesian_predictor.save_beliefs()
            except Exception as exc:
                _LOGGER.warning("Bayesian beliefs shutdown save failed: %s", exc)
        unsub_bayesian_save = hass.data[DOMAIN].pop("unsub_bayesian_save", None)
        if unsub_bayesian_save:
            unsub_bayesian_save()
        unsub_bayesian_guest = hass.data[DOMAIN].pop("unsub_bayesian_guest", None)
        if unsub_bayesian_guest:
            unsub_bayesian_guest()
        # v4.0.0-B2: Clean up accuracy evaluation timer
        unsub_bayesian_accuracy = hass.data[DOMAIN].pop("unsub_bayesian_accuracy", None)
        if unsub_bayesian_accuracy:
            unsub_bayesian_accuracy()
        hass.data[DOMAIN].pop("bayesian_predictor_shutdown", None)

        # v4.6.10 review fix B2: Clean up setup_telemetry so a reload doesn't leave
        # stale data that would mislead the sensor if the reload's CM init block
        # never re-runs. Bug Class #36 (lifecycle teardown).
        hass.data[DOMAIN].pop("setup_telemetry", None)

        # v3.5.0: Clean up camera census
        unsub_census = hass.data[DOMAIN].pop("unsub_census", None)
        if unsub_census:
            unsub_census()
        # v3.10.1: Clean up event-driven census listeners
        for unsub in hass.data[DOMAIN].pop("unsub_census_events", []):
            unsub()
        # IDENTITY-FUSION-PRODUCER-1 (2026-09-04) D2: tear down
        # BLE-transition state_changed listeners.
        _cens_for_teardown = hass.data[DOMAIN].get("census")
        if _cens_for_teardown is not None and hasattr(
            _cens_for_teardown, "async_teardown_ble_transition_listeners"
        ):
            try:
                _cens_for_teardown.async_teardown_ble_transition_listeners()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "BLE-transition listener teardown raised (non-fatal)",
                    exc_info=True,
                )
        # B-HIGH-1: tear down the CameraResolver cache-invalidation listeners
        # before dropping the manager reference (Bug Class #42: untracked
        # listeners → stale invalidations against a torn-down manager).
        _cm = hass.data[DOMAIN].get("camera_manager")
        if _cm is not None:
            try:
                await _cm.async_shutdown()
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("CameraIntegrationManager.async_shutdown failed: %s", exc)
        # setup/unload symmetry: defensive `pop(key, None)`.
        for key in ("camera_manager", "census"):
            hass.data[DOMAIN].pop(key, None)

        # v3.5.1: Tear down perimeter alert manager
        # setup/unload symmetry: `pop(..., None)` after teardown so a partial
        # setup that left the key absent never raises KeyError on unload.
        perimeter_alert_manager = hass.data[DOMAIN].get("perimeter_alert_manager")
        if perimeter_alert_manager:
            await perimeter_alert_manager.async_teardown()
            hass.data[DOMAIN].pop("perimeter_alert_manager", None)

        # build/exterior-track: tear down exterior track linker
        exterior_track_linker = hass.data[DOMAIN].get("exterior_track_linker")
        if exterior_track_linker:
            await exterior_track_linker.async_teardown()
            hass.data[DOMAIN].pop("exterior_track_linker", None)

        # CONSOL-1 §D8 fix-up B1: tear down zone_monitoring tripwire so
        # a reload does not double-subscribe (leaked listener would fire
        # NM twice per counter event).
        zmt = hass.data[DOMAIN].get("zone_monitoring_tripwire")
        if zmt:
            try:
                await zmt.async_teardown()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "zone_monitoring_tripwire teardown raised",
                    exc_info=True,
                )
            hass.data[DOMAIN].pop("zone_monitoring_tripwire", None)

        # v3.5.2: Tear down transit validator and egress tracker
        transit_validator = hass.data[DOMAIN].get("transit_validator")
        if transit_validator:
            await transit_validator.async_teardown()
            hass.data[DOMAIN].pop("transit_validator", None)

        egress_tracker = hass.data[DOMAIN].get("egress_tracker")
        if egress_tracker:
            await egress_tracker.async_teardown()
            hass.data[DOMAIN].pop("egress_tracker", None)

        # v3.6.0: Tear down domain coordinator manager
        coordinator_manager = hass.data[DOMAIN].get("coordinator_manager")
        if coordinator_manager:
            await coordinator_manager.async_stop()
            hass.data[DOMAIN].pop("coordinator_manager", None)

        # v4.7.x Cycle A: Tear down WeatherProviderManager state listeners
        weather_manager = hass.data[DOMAIN].pop("weather_manager", None)
        if weather_manager is not None:
            try:
                await weather_manager.async_teardown()
            except Exception:
                _LOGGER.warning(
                    "WeatherProviderManager teardown failed during unload",
                    exc_info=True,
                )

        # Activity log: clean up daily prune timer
        unsub_activity_prune = hass.data[DOMAIN].pop("unsub_activity_prune", None)
        if unsub_activity_prune:
            unsub_activity_prune()
        # v4.2.8: Clean up nightly maintenance + startup catch-up timers
        unsub_nightly = hass.data[DOMAIN].pop("unsub_nightly_maintenance", None)
        if unsub_nightly:
            unsub_nightly()
        unsub_catchup = hass.data[DOMAIN].pop("unsub_startup_catchup", None)
        if unsub_catchup:
            unsub_catchup()
        hass.data[DOMAIN].pop("activity_logger", None)

        # Hierarchical memory MVP (Stage 1) teardown — release the 5-min
        # baseline-writer listener + drop the facade instance (v-review
        # HIGH A1=B1). The unsub is also entry.async_on_unload-registered,
        # but pop-and-call here matches the pattern used by neighboring
        # timer cleanups above.
        _mem_unsub = hass.data[DOMAIN].pop("memory_baseline_unsub", None)
        if _mem_unsub is not None:
            try:
                _mem_unsub()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "memory_baseline_unsub call failed on unload",
                    exc_info=True,
                )
        hass.data[DOMAIN].pop("memory_facade", None)

        # v3.22.7: Close persistent DB connections on unload
        database = hass.data[DOMAIN].get("database")
        if database and hasattr(database, "async_close"):
            await database.async_close()
        hass.data[DOMAIN].pop("database", None)  # Remove stale reference for clean re-init
        hass.data[DOMAIN].pop("_db_init_lock", None)

        # setup/unload symmetry: defensive `pop(key, None)`.
        hass.data[DOMAIN].pop("integration", None)

        # v4.7.18.2 review B-MED-1: the zone-level "no coordinators" dedup set
        # is integration-scoped shared state. Clear it on integration-entry
        # teardown too (not only on Zone Manager unload) so it never outlives
        # the bag it lives in.
        hass.data[DOMAIN].pop("_no_coord_warned_zones", None)

        return unload_ok

    # v3.6.0: Handle Zone Manager entry unload
    if entry_type == ENTRY_TYPE_ZONE_MANAGER:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, INTEGRATION_PLATFORMS)
        if "zone_manager_entry" in hass.data.get(DOMAIN, {}):
            hass.data[DOMAIN]["zone_manager_entry"] = None
        # v4.7.18.2: clear the zone-level "no coordinators after 60s" dedup
        # set so a legitimate Zone Manager reload re-warns for zones whose
        # coordinators still haven't appeared. See aggregation.py
        # ZoneSensorBase._check_coordinators. B-LOW-1: only touch live state.
        domain_data = hass.data.get(DOMAIN)
        if domain_data is not None:
            domain_data.pop("_no_coord_warned_zones", None)
        return unload_ok

    # v3.6.0: Handle Coordinator Manager entry unload
    if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:
        # NM Cycle A-2 fix-up (B1, 2026-07-20): flush the process-wide
        # NM knob cache on CM unload so a subsequent reload can't read
        # stale values before the setup-path flush lands.
        try:
            from .domain_coordinators._nm_cycle_a import invalidate_knob_cache
            invalidate_knob_cache()
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.warning(
                "NM Cycle A-2: invalidate_knob_cache at CM unload raised (non-fatal)",
                exc_info=True,
            )
        cm_platforms = list(INTEGRATION_PLATFORMS) + [Platform.NUMBER]
        # B-MED-1 (Review B): clear the CM last-applied-options snapshot
        # BEFORE async_unload_platforms so a listener fire during platform
        # teardown can't diff against a half-torn-down state. The pop is
        # defensive (.get + is not None) — if the snapshot dict was never
        # created (degenerate setup), this is a no-op.
        snapshots = hass.data.get(DOMAIN, {}).get("cm_last_applied_options")
        if snapshots is not None:
            snapshots.pop(entry.entry_id, None)
        # v5.94.1 B3 (2026-09-03): tear down D-NEST sweep resources
        # BEFORE platform unload so the async_at_started unsub / any
        # pending async_call_later retry can't fire against a
        # half-torn-down entry.
        try:
            from ._devices import async_teardown_device_tree_sweep_handles
            async_teardown_device_tree_sweep_handles(hass)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "v5.94.1 B3: D-NEST sweep teardown at CM unload raised (non-fatal)",
                exc_info=True,
            )
        unload_ok = await hass.config_entries.async_unload_platforms(entry, cm_platforms)
        return unload_ok

    # v3.3.2: Handle legacy zone entry unload (deprecated)
    if entry_type == ENTRY_TYPE_ZONE:
        return True
    
    # Room entry - unload platforms and remove coordinator
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # v3.20.0: Save room state to DB on unload/shutdown so the
        # DB backup is fresh for crash recovery (not up to 5min stale)
        coordinator = hass.data[DOMAIN].get(entry.entry_id)
        if coordinator is not None:
            db = hass.data.get(DOMAIN, {}).get("database")
            if db:
                try:
                    from homeassistant.util import dt as dt_util
                    room_id = entry.entry_id
                    state = {
                        "became_occupied_time": (
                            coordinator._became_occupied_time.isoformat()
                            if getattr(coordinator, "_became_occupied_time", None)
                            else None
                        ),
                        "last_occupied_state": getattr(coordinator, "_last_occupied_state", False),
                        "occupancy_first_detected": (
                            coordinator._occupancy_first_detected.isoformat()
                            if getattr(coordinator, "_occupancy_first_detected", None)
                            else None
                        ),
                        "failsafe_fired": getattr(coordinator, "_failsafe_fired", False),
                        "last_trigger_source": getattr(coordinator, "_last_trigger_source", None),
                        "last_lux_zone": getattr(coordinator, "_last_lux_zone", None),
                        "last_timed_open_date": (
                            coordinator.automation._last_timed_open_date
                            if hasattr(coordinator, "automation") and coordinator.automation
                            else None
                        ),
                        "last_timed_close_date": (
                            coordinator.automation._last_timed_close_date
                            if hasattr(coordinator, "automation") and coordinator.automation
                            else None
                        ),
                    }
                    await db.save_room_state(room_id, state)
                except Exception as err:
                    _LOGGER.warning("Failed to save room state on unload for %s: %s", entry.entry_id, err)

        # v3.12.0: Explicitly clean up coordinator listeners.
        # async_will_remove_from_hass is an Entity lifecycle method — never
        # called on DataUpdateCoordinator. Without this, state and signal
        # listener unsub handles leak on every entry reload.
        if coordinator is not None:
            state_listeners = getattr(coordinator, "_unsub_state_listeners", [])
            for unsub in state_listeners:
                unsub()
            state_listeners.clear()
            signal_listeners = getattr(coordinator, "_unsub_signal_listeners", [])
            for unsub in signal_listeners:
                unsub()
            signal_listeners.clear()
            # B-C1 fix-up: substrate signal subscription lives on its own
            # list (NOT _unsub_signal_listeners) so _update_signal_subscriptions
            # cannot clobber it. Tear it down here symmetrically.
            substrate_listeners = getattr(coordinator, "_unsub_substrate_listeners", [])
            for unsub in substrate_listeners:
                unsub()
            substrate_listeners.clear()
            # Reconcile-on-Return (v5.8.0, D2.9): tear down the reconciler's OWN
            # listener + any pending coalesce/grace timers. Its unsub list is
            # separate from every coordinator list (Bug Class #38).
            reconciler = getattr(coordinator, "_actuator_reconciler", None)
            if reconciler is not None and hasattr(reconciler, "async_teardown"):
                await reconciler.async_teardown()
            # STEP D2 — chatter detector teardown (Bug Class #38). Owns its
            # own async_track_state_change_event unsub (self._chatter_unsub).
            chatter = getattr(coordinator, "_chatter_detector", None)
            if chatter is not None and hasattr(chatter, "async_teardown"):
                await chatter.async_teardown()
            debounce_unsub = getattr(coordinator, "_debounce_refresh_unsub", None)
            if debounce_unsub is not None:
                debounce_unsub()
                coordinator._debounce_refresh_unsub = None
            # v4.0.10: Clean up trailing-edge refresh timer from rate limiter
            trailing_unsub = getattr(coordinator, "_trailing_refresh_unsub", None)
            if trailing_unsub is not None:
                trailing_unsub()
                coordinator._trailing_refresh_unsub = None
            # setup/unload symmetry: defensive `pop(key, None)`.
            hass.data[DOMAIN].pop(entry.entry_id, None)

        # Substrate re-subscribe cycle (D1): fire SIGNAL_ROOM_ENTRY_LIFECYCLE
        # so PresenceCoordinator's OccupancySubstrate.refresh_subscriptions()
        # diffs the removed entities off the tracked set. Fires ONLY on
        # successful unload (unload_ok True) — mirrors the coordinator
        # teardown branch. Symmetric with the "loaded" dispatch above.
        #
        # F7 fix-up (A-MED-5): options-reload cycles unloaded->loaded
        # refreshes back-to-back. There is a ~one-tick window between the
        # unloaded refresh finishing and the loaded refresh starting where
        # the room's entities are unmapped. Any state-change event that
        # lands in that window is dropped by the substrate's
        # `mapping is None` guard. RECOVERY: the loaded refresh (F1/F2)
        # re-seeds from LIVE state — if the entity moved during the blind
        # window, that new state is captured by the re-seed and either
        # (a) matches the pre-refresh snapshot (no synthetic edge needed)
        # or (b) flips the bucket and emits a synthetic edge. So
        # transitions that occur during the blind window are NOT lost —
        # they're recovered by the live-state read at the tail of the
        # loaded refresh.
        try:
            from homeassistant.helpers.dispatcher import async_dispatcher_send
            from .domain_coordinators.signals import SIGNAL_ROOM_ENTRY_LIFECYCLE
            async_dispatcher_send(
                hass,
                SIGNAL_ROOM_ENTRY_LIFECYCLE,
                entry.entry_id,
                entry.data.get("room_name"),
                "unloaded",
            )
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.debug(
                "SIGNAL_ROOM_ENTRY_LIFECYCLE dispatch (unloaded) failed (non-fatal)",
                exc_info=True,
            )

    return unload_ok


async def _async_register_presence_services(hass: HomeAssistant) -> None:
    """Register house state services for HA automations.

    Services:
    - universal_room_automation.set_house_state: Set house state override
    - universal_room_automation.clear_house_state_override: Clear override
    """
    import voluptuous as vol

    async def handle_set_house_state(call):
        """Handle set_house_state service call."""
        state = call.data.get("state", "auto")
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        presence = manager.coordinators.get("presence")
        if presence is not None:
            presence.set_house_state_override(state)
        else:
            # Direct state machine control if Presence not registered
            from .domain_coordinators.house_state import HouseState
            if state == "auto":
                manager.house_state_machine.clear_override()
            else:
                try:
                    manager.house_state_machine.set_override(HouseState(state))
                except ValueError:
                    _LOGGER.warning("Invalid house state: %s", state)

    async def handle_clear_override(call):
        """Handle clear_house_state_override service call."""
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        presence = manager.coordinators.get("presence")
        if presence is not None:
            presence.set_house_state_override("auto")
        else:
            manager.house_state_machine.clear_override()

    async def handle_fan_recheck_force_restore(call):
        """Handle fan_recheck_force_restore service call.

        Routes to FanRecheckManager.force_restore for the named room.
        Defensive: silent no-op when presence/manager not registered yet.
        """
        room_name = call.data.get("room_name", "")
        if not room_name:
            return
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            _LOGGER.warning(
                "fan_recheck_force_restore: coordinator manager not ready",
            )
            return
        presence = manager.coordinators.get("presence")
        fr_mgr = (
            getattr(presence, "_fan_recheck_manager", None)
            if presence is not None else None
        )
        if fr_mgr is None:
            _LOGGER.warning(
                "fan_recheck_force_restore: FanRecheckManager not registered "
                "(room=%s)", room_name,
            )
            return
        await fr_mgr.force_restore(room_name)

    # Only register once
    if not hass.services.has_service(DOMAIN, "set_house_state"):
        hass.services.async_register(
            DOMAIN,
            "set_house_state",
            handle_set_house_state,
            schema=vol.Schema({
                vol.Required("state"): vol.In([
                    "auto", "away", "arriving", "home_day", "home_evening",
                    "home_night", "sleep", "waking", "guest", "vacation",
                ]),
            }),
        )
        hass.services.async_register(
            DOMAIN,
            "clear_house_state_override",
            handle_clear_override,
            schema=vol.Schema({}),
        )
        _LOGGER.info("Registered house state services")

    if not hass.services.has_service(DOMAIN, "fan_recheck_force_restore"):
        hass.services.async_register(
            DOMAIN,
            "fan_recheck_force_restore",
            handle_fan_recheck_force_restore,
            schema=vol.Schema({
                vol.Required("room_name"): str,
            }),
        )
        _LOGGER.info("Registered fan_recheck_force_restore service")


async def _async_wire_memory(
    hass: HomeAssistant, entry: ConfigEntry | None = None,
) -> None:
    """Idempotently wire the memory facade + service + baseline writer.

    v5.47.1 hotfix: async_setup_entry has TWO DB-init sites (CM-path
    ~1483 and room-path ~3693) and 40+ entries race for the init lock at
    boot — v5.47.0 wired memory only at the first site, so any boot
    where a room entry won the lock silently skipped the facade, the
    memory_query service, AND the baseline writer (observed live
    2026-08-02: seeds present, service absent, baseline_last_fold null).
    This helper is called from BOTH sites and guards on the facade key.
    """
    if hass.data.get(DOMAIN, {}).get("memory_facade") is not None:
        return
    try:
        from .memory_facade import MemoryFacade  # noqa: PLC0415
        hass.data[DOMAIN]["memory_facade"] = MemoryFacade(hass)
        await _async_register_memory_services(hass)
        await _async_start_memory_baseline_writer(hass, entry)
        _LOGGER.info("Memory MVP: facade + baseline writer wired (Stage 1)")
    except Exception as _mem_err:  # noqa: BLE001
        hass.data.get(DOMAIN, {}).pop("memory_facade", None)
        _LOGGER.warning(
            "Memory MVP wiring failed (non-fatal): %s", _mem_err,
        )


async def _async_register_memory_services(hass: HomeAssistant) -> None:
    """Register the memory_query service (SupportsResponse.ONLY).

    Fields: verb (str), node (str), plus optional signal/context/window/
    pattern/topic. Returns a MemoryAnswer serialized to dict.
    See docs/planning/MVP_hierarchical_memory.md deliverable 6.
    """
    import voluptuous as vol  # noqa: PLC0415
    from datetime import timedelta as _timedelta  # noqa: PLC0415
    try:
        from homeassistant.core import SupportsResponse  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — older HA fallback (harness)
        SupportsResponse = None  # type: ignore[assignment]

    async def _handle_memory_query(call):
        facade = hass.data.get(DOMAIN, {}).get("memory_facade")
        if facade is None:
            return {
                "verdict": "no_data", "value": None, "support": 0,
                "provenance": ["facade_not_initialized"],
                "as_of": None,
            }
        verb = str(call.data.get("verb") or "")
        node = str(call.data.get("node") or "")
        signal = call.data.get("signal")
        pattern = call.data.get("pattern")
        topic = call.data.get("topic")
        context = call.data.get("context") or {}
        window_s = call.data.get("window_s")
        window = _timedelta(seconds=int(window_s)) if window_s else None
        # MED C-M5: default to explicit "observer" for the service caller
        # so unknown-tier deny doesn't fire against dashboard/operator use.
        caller_id = call.data.get("caller_id") or "observer"
        try:
            if verb == "baseline":
                ans = await facade.baseline(
                    node, str(signal or ""), context=context,
                    caller_id=caller_id,
                )
            elif verb == "episodes":
                ans = await facade.episodes(
                    node, pattern=pattern, window=window,
                    caller_id=caller_id,
                )
            elif verb == "unusual":
                ans = await facade.unusual(
                    node, window=window, caller_id=caller_id,
                )
            elif verb == "outcome":
                ans = await facade.outcome(
                    node, decision_type=pattern, window=window,
                    caller_id=caller_id,
                )
            elif verb == "narrative":
                ans = await facade.narrative(
                    node, window=window, caller_id=caller_id,
                )
            elif verb == "profile":
                ans = await facade.profile(node, caller_id=caller_id)
            elif verb == "facts":
                ans = await facade.facts(
                    node, topic=topic, caller_id=caller_id,
                )
            else:
                return {
                    "verdict": "no_data", "value": None, "support": 0,
                    "provenance": [f"unknown_verb:{verb}"],
                    "as_of": None,
                }
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("memory_query verb=%s failed: %s", verb, e)
            return {
                "verdict": "no_data", "value": None, "support": 0,
                "provenance": [f"exception:{type(e).__name__}"],
                "as_of": None,
            }
        return {
            "verdict": ans.verdict,
            "value": ans.value,
            "support": ans.support,
            "provenance": list(ans.provenance),
            "as_of": ans.as_of.isoformat() if ans.as_of else None,
        }

    if hass.services.has_service(DOMAIN, "memory_query"):
        return
    kw: dict = {
        "schema": vol.Schema({
            vol.Required("verb"): vol.In([
                "baseline", "episodes", "unusual",
                "outcome", "narrative", "profile", "facts",
            ]),
            vol.Required("node"): str,
            vol.Optional("signal"): str,
            vol.Optional("pattern"): str,
            vol.Optional("topic"): str,
            vol.Optional("context"): dict,
            vol.Optional("window_s"): vol.Coerce(int),
            vol.Optional("caller_id"): str,
        }),
    }
    if SupportsResponse is not None:
        kw["supports_response"] = SupportsResponse.ONLY
    hass.services.async_register(
        DOMAIN, "memory_query", _handle_memory_query, **kw,
    )
    _LOGGER.info("Registered memory_query service (MVP Stage 1)")


async def _async_start_memory_baseline_writer(
    hass: HomeAssistant, entry: ConfigEntry | None = None,
) -> None:
    """Kick off the 5-min baseline-writer time interval, guarded by the
    kill switch. Handle stored in hass.data[DOMAIN]["memory_baseline_unsub"].

    When ``entry`` is provided, the unsub is also registered with
    ``entry.async_on_unload`` (v-review HIGH A1=B1) so a config-entry
    unload deterministically releases the listener.
    """
    from datetime import timedelta as _timedelta  # noqa: PLC0415
    from homeassistant.helpers.event import (  # noqa: PLC0415
        async_track_time_interval,
    )
    from .const import MEMORY_BASELINE_WRITER_ENABLED  # noqa: PLC0415
    from .memory_baseline import async_fold_samples  # noqa: PLC0415

    if not MEMORY_BASELINE_WRITER_ENABLED:
        _LOGGER.info(
            "memory_baseline_writer disabled by kill switch — skipping",
        )
        return
    if hass.data.get(DOMAIN, {}).get("memory_baseline_unsub") is not None:
        return  # already armed

    async def _tick(_now):
        try:
            await async_fold_samples(hass)
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug(
                "memory_baseline tick raised (non-fatal): %s", e,
            )

    unsub = async_track_time_interval(
        hass, _tick, _timedelta(minutes=5),
    )
    hass.data[DOMAIN]["memory_baseline_unsub"] = unsub
    if entry is not None:
        def _cleanup_memory_wiring() -> None:
            # v5.47.1: the owning entry's unload must ALSO drop the
            # hass.data keys, not just cancel the listener — otherwise a
            # reload of that one entry leaves the stale unsub + facade
            # guarding _async_wire_memory closed, and memory stays dead
            # until a full restart. Popping here lets the reloaded
            # entry's own setup rewire cleanly.
            _u = hass.data.get(DOMAIN, {}).pop(
                "memory_baseline_unsub", None,
            )
            if _u is not None:
                try:
                    _u()
                except Exception:  # noqa: BLE001
                    pass
            hass.data.get(DOMAIN, {}).pop("memory_facade", None)
        try:
            entry.async_on_unload(_cleanup_memory_wiring)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "memory_baseline_writer: async_on_unload registration "
                "failed (non-fatal)", exc_info=True,
            )


async def _async_register_safety_services(hass: HomeAssistant) -> None:
    """Register safety test service for HA automations.

    Services:
    - universal_room_automation.test_safety_hazard: Trigger test hazard
    """
    import voluptuous as vol

    async def handle_test_safety_hazard(call):
        """Handle test_safety_hazard service call."""
        hazard_type = call.data.get("hazard_type", "smoke")
        location = call.data.get("location", "test")
        severity = call.data.get("severity", "medium")
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        safety = manager.coordinators.get("safety")
        if safety is not None:
            await safety.handle_test_hazard(hazard_type, location, severity)
        else:
            _LOGGER.warning("Safety coordinator not available for test hazard")

    # Only register once
    if not hass.services.has_service(DOMAIN, "test_safety_hazard"):
        hass.services.async_register(
            DOMAIN,
            "test_safety_hazard",
            handle_test_safety_hazard,
            schema=vol.Schema({
                vol.Required("hazard_type"): vol.In([
                    "smoke", "fire", "water_leak", "flooding",
                    "carbon_monoxide", "high_co2", "high_tvoc",
                    "freeze_risk", "overheat", "hvac_failure",
                    "high_humidity", "low_humidity",
                ]),
                vol.Required("location"): str,
                vol.Optional("severity", default="medium"): vol.In([
                    "critical", "high", "medium", "low",
                ]),
            }),
        )
        _LOGGER.info("Registered safety test service")


async def _async_register_security_services(hass: HomeAssistant) -> None:
    """Register security services for HA automations.

    Services:
    - universal_room_automation.security_arm: Set armed state
    - universal_room_automation.security_disarm: Disarm
    - universal_room_automation.authorize_guest: Authorize a guest
    - universal_room_automation.add_expected_arrival: Add expected arrival
    """
    import voluptuous as vol

    async def handle_security_arm(call):
        """Handle security_arm service call."""
        armed_state = call.data.get("state", "armed_home")
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        security = manager.coordinators.get("security")
        if security is not None:
            await security.handle_arm(armed_state)
        else:
            _LOGGER.warning("Security coordinator not available for arm")

    async def handle_security_disarm(call):
        """Handle security_disarm service call."""
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        security = manager.coordinators.get("security")
        if security is not None:
            await security.handle_disarm()
        else:
            _LOGGER.warning("Security coordinator not available for disarm")

    async def handle_authorize_guest(call):
        """Handle authorize_guest service call."""
        person_name = call.data.get("person_name", "")
        expires_hours = call.data.get("expires_hours", 24)
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        security = manager.coordinators.get("security")
        if security is not None:
            security.handle_authorize_guest(person_name, expires_hours)
        else:
            _LOGGER.warning("Security coordinator not available for authorize_guest")

    async def handle_add_expected_arrival(call):
        """Handle add_expected_arrival service call."""
        person_id = call.data.get("person_id", "")
        window_minutes = call.data.get("window_minutes", 30)
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        security = manager.coordinators.get("security")
        if security is not None:
            security.handle_add_expected_arrival(person_id, window_minutes)
        else:
            _LOGGER.warning("Security coordinator not available for add_expected_arrival")

    if not hass.services.has_service(DOMAIN, "security_arm"):
        hass.services.async_register(
            DOMAIN,
            "security_arm",
            handle_security_arm,
            schema=vol.Schema({
                vol.Required("state"): vol.In([
                    "disarmed", "armed_home", "armed_away", "armed_vacation",
                ]),
            }),
        )

    if not hass.services.has_service(DOMAIN, "security_disarm"):
        hass.services.async_register(
            DOMAIN,
            "security_disarm",
            handle_security_disarm,
            schema=vol.Schema({}),
        )

    if not hass.services.has_service(DOMAIN, "authorize_guest"):
        hass.services.async_register(
            DOMAIN,
            "authorize_guest",
            handle_authorize_guest,
            schema=vol.Schema({
                vol.Required("person_name"): str,
                vol.Optional("expires_hours", default=24): vol.Coerce(float),
            }),
        )

    if not hass.services.has_service(DOMAIN, "add_expected_arrival"):
        hass.services.async_register(
            DOMAIN,
            "add_expected_arrival",
            handle_add_expected_arrival,
            schema=vol.Schema({
                vol.Required("person_id"): str,
                vol.Optional("window_minutes", default=30): vol.Coerce(int),
            }),
        )

    _LOGGER.info("Registered security services")


async def _async_register_notification_services(hass: HomeAssistant) -> None:
    """Register notification manager services.

    Services:
    - universal_room_automation.acknowledge_notification: Ack active alert
    - universal_room_automation.test_notification: Send test notification
    """
    import voluptuous as vol

    async def handle_acknowledge_notification(call):
        """Handle acknowledge_notification service call."""
        nm = hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm:
            # FIX 4: label service-triggered acks so the audit row can
            # distinguish them from inbound-channel + button acks.
            await nm.async_acknowledge(acked_by_channel="service")
        else:
            _LOGGER.warning("Notification Manager not available for acknowledge")

    async def handle_test_notification(call):
        """Handle test_notification service call."""
        severity = call.data.get("severity", "MEDIUM")
        channel = call.data.get("channel")
        nm = hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm:
            await nm.async_test_notification(severity=severity, channel=channel)
        else:
            _LOGGER.warning("Notification Manager not available for test")

    if not hass.services.has_service(DOMAIN, "acknowledge_notification"):
        hass.services.async_register(
            DOMAIN,
            "acknowledge_notification",
            handle_acknowledge_notification,
            schema=vol.Schema({}),
        )

    if not hass.services.has_service(DOMAIN, "test_notification"):
        hass.services.async_register(
            DOMAIN,
            "test_notification",
            handle_test_notification,
            schema=vol.Schema({
                vol.Optional("severity", default="MEDIUM"): vol.In([
                    "LOW", "MEDIUM", "HIGH", "CRITICAL",
                ]),
                vol.Optional("channel"): str,
            }),
        )

    # C4b: test_inbound service
    async def handle_test_inbound(call):
        """Handle test_inbound service call."""
        nm = hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm:
            text = call.data.get("text", "status")
            channel = call.data.get("channel", "companion")
            response = await nm._process_inbound_reply(None, channel, text)
            _LOGGER.info("Test inbound response: %s", response)

    if not hass.services.has_service(DOMAIN, "test_inbound"):
        hass.services.async_register(
            DOMAIN,
            "test_inbound",
            handle_test_inbound,
            schema=vol.Schema({
                vol.Required("text"): str,
                vol.Optional("channel", default="companion"): vol.In([
                    "companion", "whatsapp", "pushover", "imessage",
                ]),
            }),
        )

    # NM Cycle C fix-up (2026-07-20, D5): register `nm_mute_person_channel`
    # centrally so entry unload's `async_on_unload(async_remove...)` loop
    # covers it symmetrically. NM's own async_setup ALSO tries to
    # register; `has_service` guards make both paths idempotent.
    from .const import SERVICE_NM_MUTE_PERSON_CHANNEL as _SVC_NM_MUTE

    async def handle_mute_person_channel(call):
        """Handle nm_mute_person_channel service call."""
        nm = hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            _LOGGER.warning("NM not available for mute_person_channel")
            return
        await nm.async_mute_person_channel(
            person_id=call.data.get("person_id"),
            channel=call.data.get("channel"),
            duration_minutes=call.data.get("duration_minutes"),
        )

    if not hass.services.has_service(DOMAIN, _SVC_NM_MUTE):
        hass.services.async_register(
            DOMAIN,
            _SVC_NM_MUTE,
            handle_mute_person_channel,
            schema=vol.Schema({
                vol.Required("person_id"): str,
                vol.Required("channel"): str,
                vol.Optional("duration_minutes"): vol.Any(int, None),
            }),
        )

    _LOGGER.info("Registered notification manager services")


# v4.7.4.3: the v4.7.4.1 customize_buckets deferred-persist helper was
# deleted (do not reintroduce — test_v4743_no_eager_migration.py guards
# the name against ANY reappearance, including comments).
# Bug Class #46: even deferred, the helper's async_update_entry call still
# triggered the update_listener -> reload chain within bootstrap-2 budget.
# Replaced by lazy derivation in _build_dynamic_preset_schema (config_flow.py).


# =============================================================================
# CM Option-Writeback Reload Suppression
# =============================================================================
#
# Runtime-tunable CM-entry option keys: editing one of these from a Number
# entity OR from the OptionsFlow form should NOT trigger a full Coordinator
# Manager reload (which rebuilds presence/HVAC/energy/safety/diagnostics/
# house_state/signals coordinators). Instead the listener pokes the live
# coordinator attribute in place. Persistence still goes through
# `async_update_entry`; restart re-seeds the value from `entry.options`
# via the CM constructor (`cm_config = {**cm_entry.data, **cm_entry.options}`).
#
# Listener decision (CM entry only):
#   - changed_keys ⊆ OPTIONS_RELOAD_SUPPRESS_KEYS  → apply_in_place, no reload
#   - empty changed_keys                            → no-op
#   - mixed or non-allowlisted changed_keys         → full reload (legacy)
#
# ROOM and ZONE_MANAGER entries are UNCHANGED (full reload as today).
# =============================================================================

from .domain_coordinators.hvac_const import (
    CONF_HVAC_VACANCY_GRACE_MINUTES as _CONF_HVAC_VACANCY_GRACE_MINUTES,
    CONF_HVAC_VACANCY_GRACE_CONSTRAINED as _CONF_HVAC_VACANCY_GRACE_CONSTRAINED,
    CONF_HVAC_MAX_OCCUPANCY_HOURS as _CONF_HVAC_MAX_OCCUPANCY_HOURS,
    CONF_HVAC_ZONE_ENTRY_DWELL as _CONF_HVAC_ZONE_ENTRY_DWELL,
    # Part 2 — HVAC tunable factory (60-66 + 70-76 cluster, 14 keys)
    CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA as _CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA,
    CONF_HVAC_COVER_CLOSE_TEMP as _CONF_HVAC_COVER_CLOSE_TEMP,
    CONF_HVAC_COVER_OPEN_TEMP as _CONF_HVAC_COVER_OPEN_TEMP,
    CONF_HVAC_COVER_OVERRIDE_HOURS as _CONF_HVAC_COVER_OVERRIDE_HOURS,
    CONF_HVAC_SOLAR_BANK_FLOOR as _CONF_HVAC_SOLAR_BANK_FLOOR,
    CONF_HVAC_FAN_ACTIVATION_DELTA as _CONF_HVAC_FAN_ACTIVATION_DELTA,
    CONF_HVAC_FAN_HYSTERESIS as _CONF_HVAC_FAN_HYSTERESIS,
    CONF_HVAC_AC_NUDGE_SIZE as _CONF_HVAC_AC_NUDGE_SIZE,
    CONF_HVAC_AC_NUDGE_DURATION as _CONF_HVAC_AC_NUDGE_DURATION,
    CONF_HVAC_AC_NUDGE_EVAL_DELAY as _CONF_HVAC_AC_NUDGE_EVAL_DELAY,
    CONF_HVAC_AC_SUSTAINED_SAMPLES as _CONF_HVAC_AC_SUSTAINED_SAMPLES,
    CONF_HVAC_AC_DETECTION_TIME_GATE as _CONF_HVAC_AC_DETECTION_TIME_GATE,
    CONF_HVAC_AC_HARD_RESET_DAILY_LIMIT as _CONF_HVAC_AC_HARD_RESET_DAILY_LIMIT,
    CONF_HVAC_AC_HARD_RESET_MIN_INTERVAL as _CONF_HVAC_AC_HARD_RESET_MIN_INTERVAL,
    # Part 2 — DPM hysteresis (D5) and egress thresholds (D5)
    CONF_HVAC_EGRESS_THRESHOLD_MIN as _CONF_HVAC_EGRESS_THRESHOLD_MIN,
    CONF_HVAC_EGRESS_RESUME_DELAY_MIN as _CONF_HVAC_EGRESS_RESUME_DELAY_MIN,
    # Arrester operator-immunity cycle (2026-08-06): AC-ramp master
    # option-persistence key. Add to OPTIONS_RELOAD_SUPPRESS_KEYS so a
    # switch write-through does not trigger a CM reload (which would
    # RE-create the arrester and reset the field to its default False).
    CONF_HVAC_AC_RAMP_MASTER_ENABLED as _CONF_HVAC_AC_RAMP_MASTER_ENABLED,
    # Arrester operator-immunity cycle (2026-08-06): live-tunable
    # options key for immune-person list. Wired through _apply_in_place
    # via set_immune_persons() so options-flow edits take effect without
    # a reload (docstring vs wiring alignment — MED-A2/B-L1).
    CONF_HVAC_ARRESTER_IMMUNE_PERSONS as _CONF_HVAC_ARRESTER_IMMUNE_PERSONS,
)
from .domain_coordinators.energy_const import (
    CONF_DYNAMIC_PRESET_DWELL_MINUTES as _CONF_DYNAMIC_PRESET_DWELL_MINUTES,
    # Part 2 — DPM hysteresis (D5)
    CONF_DYNAMIC_PRESET_HYSTERESIS_F as _CONF_DYNAMIC_PRESET_HYSTERESIS_F,
    # Part 2 — EC Number family (D1)
    CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT as _CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT,
    CONF_ENERGY_OFFPEAK_DRAIN_GOOD as _CONF_ENERGY_OFFPEAK_DRAIN_GOOD,
    CONF_ENERGY_OFFPEAK_DRAIN_MODERATE as _CONF_ENERGY_OFFPEAK_DRAIN_MODERATE,
    CONF_ENERGY_OFFPEAK_DRAIN_POOR as _CONF_ENERGY_OFFPEAK_DRAIN_POOR,
    CONF_ENERGY_OFFPEAK_DRAIN_VERY_POOR as _CONF_ENERGY_OFFPEAK_DRAIN_VERY_POOR,
    CONF_ENERGY_PEAK_BUFFER_TARGET as _CONF_ENERGY_PEAK_BUFFER_TARGET,
    CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN as _CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
    CONF_ENERGY_EV_BATTERY_DRAIN_SOC as _CONF_ENERGY_EV_BATTERY_DRAIN_SOC,
    # evse-charge-onset cycle — overnight release-onset HH:MM knob.
    CONF_ENERGY_EVSE_CHARGE_ONSET_TIME as _CONF_ENERGY_EVSE_CHARGE_ONSET_TIME,
    # Rev 6 D-A — dedicated ENABLE toggle (config-flow boolean).
    CONF_ENERGY_EVSE_CHARGE_ONSET_ENABLED as _CONF_ENERGY_EVSE_CHARGE_ONSET_ENABLED,
    CONF_ENERGY_FILL_PRIORITY_SOC as _CONF_ENERGY_FILL_PRIORITY_SOC,
    CONF_ENERGY_EXCESS_SOLAR_SOC as _CONF_ENERGY_EXCESS_SOLAR_SOC,
    # Blind-window guard cycle — D4 Emporia-mains backup export sensor.
    CONF_ENERGY_MAINS_EXPORT_ENTITY as _CONF_ENERGY_MAINS_EXPORT_ENTITY,
    # LKG wave 1 D2 — solar production upper-envelope nameplate (config-flow
    # field, rung 2). Read fresh via `_entity_config` on every excess-solar
    # tick, so a change takes effect without a full CM reload. Kill-switch:
    # setting to 0 (or unset) triggers the DEFAULT_ENERGY_SOLAR_NAMEPLATE_W
    # fallback path in `BatteryStrategy.solar_production_w_envelope`.
    CONF_ENERGY_SOLAR_NAMEPLATE_W as _CONF_ENERGY_SOLAR_NAMEPLATE_W,
    # Session B1 — EVSE Drain-Precedence CM options keys.
    CONF_ENERGY_DP_ENABLE as _CONF_ENERGY_DP_ENABLE,
    # v5.21.0 fix-up (SECOND OPERATOR ADDITION 2026-07-17) — D2 detection
    # knobs promoted rung-1 → rung-2 (options-settable).
    CONF_ENERGY_SOC_DIVERGENCE_THRESHOLD_PP as _CONF_ENERGY_SOC_DIVERGENCE_THRESHOLD_PP,
    CONF_ENERGY_SOC_DIVERGENCE_DWELL_MIN as _CONF_ENERGY_SOC_DIVERGENCE_DWELL_MIN,
    CONF_ENERGY_CLOUD_LAG_ALERT_S as _CONF_ENERGY_CLOUD_LAG_ALERT_S,
    CONF_ENERGY_DP_EVAL_DELAY_MIN as _CONF_ENERGY_DP_EVAL_DELAY_MIN,
    CONF_ENERGY_DP_MARGIN_MIN as _CONF_ENERGY_DP_MARGIN_MIN,
    CONF_ENERGY_DP_MUST_START_BY_MIN as _CONF_ENERGY_DP_MUST_START_BY_MIN,
    CONF_ENERGY_DP_NEEDED_KWH_GARAGE_A as _CONF_ENERGY_DP_NEEDED_KWH_GARAGE_A,
    CONF_ENERGY_DP_NEEDED_KWH_GARAGE_B as _CONF_ENERGY_DP_NEEDED_KWH_GARAGE_B,
    CONF_ENERGY_DP_HOUSE_LOAD_SOURCE as _CONF_ENERGY_DP_HOUSE_LOAD_SOURCE,
)
from .const import (
    # Part 2 — Bayesian + fan-interference + routine family
    CONF_BAYESIAN_CELL_STALENESS_DAYS as _CONF_BAYESIAN_CELL_STALENESS_DAYS,
    CONF_FAN_INTERFERENCE_HOLD_S as _CONF_FAN_INTERFERENCE_HOLD_S,
    CONF_ROUTINE_EVENT_COOLDOWN_DAYS as _CONF_ROUTINE_EVENT_COOLDOWN_DAYS,
    CONF_ROUTINE_EVENT_MIN_SEVERITY as _CONF_ROUTINE_EVENT_MIN_SEVERITY,
    CONF_ROUTINE_REGIME_BASELINE_WINDOW_DAYS as _CONF_ROUTINE_REGIME_BASELINE_WINDOW_DAYS,
    CONF_ROUTINE_REGIME_RECENT_WINDOW_DAYS as _CONF_ROUTINE_REGIME_RECENT_WINDOW_DAYS,
    # v4.7.34 — Optimization Coordinator CM-level keys (C-CRIT-1 reload
    # suppression) and ROOM-level comfort sliders (C-HIGH-3).
    CONF_OPTIMIZER_AUTONOMY_LEVEL as _CONF_OPTIMIZER_AUTONOMY_LEVEL,
    CONF_OPTIMIZER_KILL_SWITCH as _CONF_OPTIMIZER_KILL_SWITCH,
    CONF_OPTIMIZER_DIMENSION_AUTONOMY as _CONF_OPTIMIZER_DIMENSION_AUTONOMY,
    CONF_OPTIMIZER_CONFIDENCE_GATE as _CONF_OPTIMIZER_CONFIDENCE_GATE,
    CONF_OPTIMIZER_RATE_CAP_PER_HOUR as _CONF_OPTIMIZER_RATE_CAP_PER_HOUR,
    CONF_OPTIMIZER_QUIET_HOURS_SOURCE as _CONF_OPTIMIZER_QUIET_HOURS_SOURCE,
    CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL as _CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL,
    # v4.7.35 Phase 2 — LLM Tier-2 CM-options keys (C-CRIT-1).
    CONF_OPTIMIZER_LLM_TASK_ENTITY as _CONF_OPTIMIZER_LLM_TASK_ENTITY,
    CONF_OPTIMIZER_LLM_TRIAGE_ENTITY as _CONF_OPTIMIZER_LLM_TRIAGE_ENTITY,
    CONF_OPTIMIZER_LLM_SYSTEM_PROMPT as _CONF_OPTIMIZER_LLM_SYSTEM_PROMPT,
    CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H as _CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H,
    # v4.7.35 fix-up (B-B2) — safety/security deny-list CM-options key.
    CONF_OPTIMIZER_SAFETY_DENY_ENTITIES as _CONF_OPTIMIZER_SAFETY_DENY_ENTITIES,
    CONF_COMFORT_TEMP_MIN as _CONF_COMFORT_TEMP_MIN,
    CONF_COMFORT_TEMP_MAX as _CONF_COMFORT_TEMP_MAX,
    CONF_COMFORT_HUMIDITY_MAX as _CONF_COMFORT_HUMIDITY_MAX,
    CONF_FAN_CONTROL_ENABLED as _CONF_FAN_CONTROL_ENABLED,
    CONF_HUMIDITY_FAN_CONTROL_ENABLED as _CONF_HUMIDITY_FAN_CONTROL_ENABLED,
    # v5.10.0 D2 — MF sleep + night suppression CM keys.
    CONF_MF_SLEEP_SUPPRESS as _CONF_MF_SLEEP_SUPPRESS,
    CONF_MF_NIGHT_SUPPRESS_MODE as _CONF_MF_NIGHT_SUPPRESS_MODE,
    # NM Cycle A-2 (2026-07-20) — rung-2 promotion of Cycle A knobs.
    # All 12 consumed via `nm_cycle_a_knob(...)` which reads
    # entry.options fresh on every call (cached, invalidated on
    # options-update). They belong in _NO_LIVE_ATTR_KEYS (no live-attr
    # push) and in OPTIONS_RELOAD_SUPPRESS_KEYS (no CM reload).
    CONF_TRIPPED_BREAKER_ZERO_WINDOW_S as _CONF_TRIPPED_BREAKER_ZERO_WINDOW_S,
    CONF_TRIPPED_BREAKER_ROUTE_NM as _CONF_TRIPPED_BREAKER_ROUTE_NM,
    CONF_LOCK_UNAVAILABLE_DEDUP_S as _CONF_LOCK_UNAVAILABLE_DEDUP_S,
    CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT as _CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT,
    CONF_HUMIDITY_NORMAL_MEDIUM_PCT as _CONF_HUMIDITY_NORMAL_MEDIUM_PCT,
    CONF_HUMIDITY_NORMAL_HIGH_PCT as _CONF_HUMIDITY_NORMAL_HIGH_PCT,
    CONF_HUMIDITY_SWING_DELTA_PCT as _CONF_HUMIDITY_SWING_DELTA_PCT,
    CONF_HUMIDITY_SWING_MIN_ABS_PCT as _CONF_HUMIDITY_SWING_MIN_ABS_PCT,
    CONF_CO2_LOG_ONLY_CEILING_PPM as _CONF_CO2_LOG_ONLY_CEILING_PPM,
    CONF_TVOC_ABSOLUTE_HIGH_PPB as _CONF_TVOC_ABSOLUTE_HIGH_PPB,
    CONF_TVOC_SUSTAINED_S as _CONF_TVOC_SUSTAINED_S,
    CONF_SAFETY_DISCOVERY_BLOCKLIST as _CONF_SAFETY_DISCOVERY_BLOCKLIST,
    CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS as _CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS,
    # STUCK-SENSOR-1 B-MED-2 fix-up (2026-08-13): both stuck-signal knobs
    # are consumed via `nm_cycle_a_knob` (cache flushed by CM options-
    # update listener) — no live-attr push, no CM reload needed.
    CONF_STUCK_SIGNAL_NM_ENABLED as _CONF_STUCK_SIGNAL_NM_ENABLED,
    CONF_STUCK_SENSOR_EXCLUSION_ENABLED as _CONF_STUCK_SENSOR_EXCLUSION_ENABLED,
    # D7 fix-up B-MED-1/2 (2026-08-19): CONF_CHATTER_QUARANTINE_ENABLED
    # is RETIRED — the CONF_CHATTER_MODE Select is the single kill-switch
    # UI now. The import is kept only for the migrate reconcile at CM
    # setup which drops the key + preserves disable-intent.
    CONF_CHATTER_QUARANTINE_ENABLED as _CONF_CHATTER_QUARANTINE_ENABLED,  # noqa: F401 — migrate-only
    # STEP D2 fix-up (2026-08-19, D-MED-2): operator-settable overrides
    # for the two safety knobs whose miscalibration would need a backout.
    CONF_CHATTER_BURST_K as _CONF_CHATTER_BURST_K,
    CONF_CHATTER_T_FLOOR_S as _CONF_CHATTER_T_FLOOR_S,
    # D7 (2026-08-19): chatter operational mode (off/shadow/act).
    CONF_CHATTER_MODE as _CONF_CHATTER_MODE,
    # NM Cycle B fix-up (2026-07-20, B-B1): dry-run + token-bucket
    # entity-owned CM options keys must reload-suppress + no-live-attr
    # (Number/Switch entities call setters directly; NM re-reads options
    # via _refresh_config on any options-update).
    CONF_NM_DRY_RUN as _CONF_NM_DRY_RUN,
    CONF_NM_BUCKET_CAPACITY as _CONF_NM_BUCKET_CAPACITY,
    CONF_NM_BUCKET_REFILL_PER_MIN as _CONF_NM_BUCKET_REFILL_PER_MIN,
    # NM Cycle C (2026-07-20) — matrix + DND-bypass + mute duration.
    # All 4 keys are re-read fresh by NM on every emit (`_refresh_config`
    # +  matrix helpers); no CM reload, no live-attr push required.
    CONF_NM_PERSON_ROUTING_MATRIX as _CONF_NM_PERSON_ROUTING_MATRIX,
    CONF_NM_PERSON_HAZARD_OVERRIDES as _CONF_NM_PERSON_HAZARD_OVERRIDES,
    CONF_NM_PERSON_DND_BYPASS_SEVERITIES as _CONF_NM_PERSON_DND_BYPASS_SEVERITIES,
    CONF_NM_MUTE_DEFAULT_DURATION_MINUTES as _CONF_NM_MUTE_DEFAULT_DURATION_MINUTES,
    # NM Cycle C-2 (2026-07-22, D2) — extras union knob. Consumed via
    # `is_life_safety_hazard(hass, ...)` which reads fresh via
    # `nm_cycle_a_knob` (cache flushed by CM options-update listener).
    CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS as _CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS,
)

# NM Cycle C — central set used to extend BOTH `_NO_LIVE_ATTR_KEYS` and
# `OPTIONS_RELOAD_SUPPRESS_KEYS`. Both prior NM cycles (A-2, B) tripped
# on missing membership here — see B-B1 v5.26.0, A-2 fix v5.25.0.
_NM_C_KEYS: frozenset[str] = frozenset({
    _CONF_NM_PERSON_ROUTING_MATRIX,
    _CONF_NM_PERSON_HAZARD_OVERRIDES,
    _CONF_NM_PERSON_DND_BYPASS_SEVERITIES,
    _CONF_NM_MUTE_DEFAULT_DURATION_MINUTES,
    # NM Cycle C-2 (2026-07-22, D2) — additive-only life-safety extras.
    _CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS,
})

# NM Cycle A-2 — the 13 CONF keys (12 Cycle-A + 1 optimizer allowlist)
# consumed via `nm_cycle_a_knob(...)`. Central set used to extend both
# `_NO_LIVE_ATTR_KEYS` and `OPTIONS_RELOAD_SUPPRESS_KEYS` below.
_NM_A2_KEYS: frozenset[str] = frozenset({
    _CONF_TRIPPED_BREAKER_ZERO_WINDOW_S,
    _CONF_TRIPPED_BREAKER_ROUTE_NM,
    _CONF_LOCK_UNAVAILABLE_DEDUP_S,
    _CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT,
    _CONF_HUMIDITY_NORMAL_MEDIUM_PCT,
    _CONF_HUMIDITY_NORMAL_HIGH_PCT,
    _CONF_HUMIDITY_SWING_DELTA_PCT,
    _CONF_HUMIDITY_SWING_MIN_ABS_PCT,
    _CONF_CO2_LOG_ONLY_CEILING_PPM,
    _CONF_TVOC_ABSOLUTE_HIGH_PPB,
    _CONF_TVOC_SUSTAINED_S,
    _CONF_SAFETY_DISCOVERY_BLOCKLIST,
    _CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS,
    # STUCK-SENSOR-1 B-MED-2 fix-up (2026-08-13): stuck-signal knobs.
    _CONF_STUCK_SIGNAL_NM_ENABLED,
    _CONF_STUCK_SENSOR_EXCLUSION_ENABLED,
    # STEP D2 (v5.85) chatter kill-switch bool — RETIRED by D7 fix-up
    # (2026-08-19, B-MED-1/2). The migrate reconcile at CM setup drops
    # any pre-D7 options entry. Not included in _NM_A2_KEYS anymore —
    # RoomCoordinator._chatter_mode() no longer reads it.
    # STEP D2 fix-up (D-MED-2): operator overrides for burst K + T_floor.
    _CONF_CHATTER_BURST_K,
    _CONF_CHATTER_T_FLOOR_S,
    # D7 (2026-08-19): chatter operational mode.
    _CONF_CHATTER_MODE,
})

# The 14 HVAC tunable factory CONFs share an identical dispatch pattern:
# look up `hvac.<sub_controller_attr>` then `setattr(sub, runtime_field, cast(value))`.
# This table is the single source of truth for both the allowlist membership
# and the `_apply_in_place` dispatch — keeping the two in lockstep.
#
# All 5 watch-list keys (ac_nudge_duration, ac_nudge_eval_delay,
# ac_detection_time_gate, ac_hard_reset_min_interval, cover_override_duration)
# were verified to consume their runtime_field INLINE at call sites
# (hvac_override.py:1061/1359/1495/1779-1784, hvac_covers.py:653), NOT via
# a stashed timedelta cache. A plain setattr is sufficient.
_HVAC_TUNABLE_DISPATCH: dict[str, tuple[str, str, type]] = {
    _CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA:  ("_cover_controller",   "_occupied_close_delta",      float),
    _CONF_HVAC_COVER_CLOSE_TEMP:            ("_cover_controller",   "_cover_close_temp",          float),
    _CONF_HVAC_COVER_OPEN_TEMP:             ("_cover_controller",   "_cover_open_temp",           float),
    _CONF_HVAC_COVER_OVERRIDE_HOURS:        ("_cover_controller",   "_cover_override_hours",      float),
    _CONF_HVAC_SOLAR_BANK_FLOOR:            ("_predictor",          "_solar_bank_floor",          float),
    _CONF_HVAC_FAN_ACTIVATION_DELTA:        ("_fan_controller",     "_activation_delta",          float),
    _CONF_HVAC_FAN_HYSTERESIS:              ("_fan_controller",     "_deactivation_delta",        float),
    _CONF_HVAC_AC_NUDGE_SIZE:               ("_override_arrester",  "_nudge_size_f",              float),
    _CONF_HVAC_AC_NUDGE_DURATION:           ("_override_arrester",  "_nudge_duration_min",        int),
    _CONF_HVAC_AC_NUDGE_EVAL_DELAY:         ("_override_arrester",  "_nudge_eval_delay_s",        int),
    _CONF_HVAC_AC_SUSTAINED_SAMPLES:        ("_override_arrester",  "_sustained_samples",         int),
    _CONF_HVAC_AC_DETECTION_TIME_GATE:      ("_override_arrester",  "_detection_time_gate_min",   int),
    _CONF_HVAC_AC_HARD_RESET_DAILY_LIMIT:   ("_override_arrester",  "_hard_reset_daily_limit",    int),
    _CONF_HVAC_AC_HARD_RESET_MIN_INTERVAL:  ("_override_arrester",  "_hard_reset_min_interval_min", int),
}

# F16 + A2 fix-up (2026-08-22): AC-RAMP-PIPELINE-HARDENING-1 knobs added
# to the dispatch. The dispatch drives BOTH the CM-options in-place
# apply AND the init-time seeding via
# `_seed_hvac_runtime_tunables_from_options`, so this single addition
# covers F16 (options-flow path bypassed setters) AND A2 (init-time
# seeding of the new knobs from CM options). Every push routes through
# the setter method named in `_HVAC_TUNABLE_SETTER_METHOD` below when
# present, so the setter's range/type/kill-switch guards are actually
# invoked.
from .domain_coordinators.hvac_const import (
    CONF_HVAC_AC_SOFT_NUDGE_DAILY_LIMIT as _CONF_HVAC_AC_SOFT_NUDGE_DAILY_LIMIT,
    CONF_HVAC_AC_RESET_DAY_BUDGET as _CONF_HVAC_AC_RESET_DAY_BUDGET,
    CONF_HVAC_AC_RESET_NIGHT_BUDGET as _CONF_HVAC_AC_RESET_NIGHT_BUDGET,
    CONF_HVAC_AC_RESET_OFF_DURATION as _CONF_HVAC_AC_RESET_OFF_DURATION,
    CONF_HVAC_AC_DURABILITY_WINDOW as _CONF_HVAC_AC_DURABILITY_WINDOW,
    CONF_HVAC_AC_NIGHT_START_HHMM as _CONF_HVAC_AC_NIGHT_START_HHMM,
    CONF_HVAC_AC_NIGHT_END_HHMM as _CONF_HVAC_AC_NIGHT_END_HHMM,
    CONF_HVAC_AC_GATE4_PREDICATE_MODE as _CONF_HVAC_AC_GATE4_PREDICATE_MODE,
)
_HVAC_TUNABLE_DISPATCH.update({
    _CONF_HVAC_AC_SOFT_NUDGE_DAILY_LIMIT: ("_override_arrester", "_soft_nudge_daily_limit", int),
    _CONF_HVAC_AC_RESET_DAY_BUDGET:       ("_override_arrester", "_reset_day_budget",       int),
    _CONF_HVAC_AC_RESET_NIGHT_BUDGET:     ("_override_arrester", "_reset_night_budget",     int),
    _CONF_HVAC_AC_RESET_OFF_DURATION:     ("_override_arrester", "_ac_reset_off_duration_s", int),
    _CONF_HVAC_AC_DURABILITY_WINDOW:      ("_override_arrester", "_durability_window_min",  int),
    _CONF_HVAC_AC_NIGHT_START_HHMM:       ("_override_arrester", "_night_start_hhmm",       str),
    _CONF_HVAC_AC_NIGHT_END_HHMM:         ("_override_arrester", "_night_end_hhmm",         str),
    _CONF_HVAC_AC_GATE4_PREDICATE_MODE:   ("_override_arrester", "_gate4_predicate_mode",   str),
})

# F16: side table of setter methods, keyed by CONF_. When present, the
# in-place apply + init-time seed call `getattr(sub, setter)(cast(value))`
# instead of bare setattr so range/kill-switch guards run. When absent
# (or the sub-controller doesn't declare the setter), fall back to
# setattr (defensive; matches pre-fix behaviour for keys that don't
# have a setter).
_HVAC_TUNABLE_SETTER_METHOD: dict[str, str] = {
    _CONF_HVAC_AC_HARD_RESET_DAILY_LIMIT:   "set_hard_reset_daily_limit",
    _CONF_HVAC_AC_SOFT_NUDGE_DAILY_LIMIT:   "set_soft_nudge_daily_limit",
    _CONF_HVAC_AC_RESET_DAY_BUDGET:         "set_reset_day_budget",
    _CONF_HVAC_AC_RESET_NIGHT_BUDGET:       "set_reset_night_budget",
    _CONF_HVAC_AC_RESET_OFF_DURATION:       "set_ac_reset_off_duration",
    _CONF_HVAC_AC_DURABILITY_WINDOW:        "set_durability_window",
    _CONF_HVAC_AC_NIGHT_START_HHMM:         "set_night_start_hhmm",
    _CONF_HVAC_AC_NIGHT_END_HHMM:           "set_night_end_hhmm",
    _CONF_HVAC_AC_GATE4_PREDICATE_MODE:     "set_gate4_predicate_mode",
}


def _hvac_tunable_apply(sub, conf_key: str, runtime_field: str,
                        value, cast_fn) -> None:
    """Route a single tunable push through its setter if declared,
    else bare setattr. Callers pass the raw (uncast) value; cast_fn
    is applied here so the setter sees the same type the entity would
    have sent."""
    _setter_name = _HVAC_TUNABLE_SETTER_METHOD.get(conf_key)
    _casted = cast_fn(value)
    if _setter_name is not None:
        _setter = getattr(sub, _setter_name, None)
        if _setter is not None:
            _setter(_casted)
            return
    setattr(sub, runtime_field, _casted)


def _seed_hvac_runtime_tunables_from_options(hvac, cm_config: dict) -> None:
    """Seed the 14 HVAC factory-tunable runtime fields from CM options.

    HVAC-TUNABLE-RUNTIME-NOT-SEEDED-1 fix (2026-08-21). Called ONCE from
    async_setup_entry immediately after the HVAC coordinator is
    constructed and registered — before any decision cycle can read
    the runtime field. Iterates `_HVAC_TUNABLE_DISPATCH` so the seed
    path stays in lockstep with the options-update dispatch: any 15th
    tunable added to the dispatch inherits this seeding for free.

    Silent no-op when the sub-controller attribute is missing (defensive
    for partial construction / tests). Missing option key falls back to
    the sub-controller's already-assigned module default — the seed
    call is byte-identical to the pre-fix behaviour in that case.
    """
    for conf_key, (sub_attr, runtime_field, cast_fn) in _HVAC_TUNABLE_DISPATCH.items():
        sub = getattr(hvac, sub_attr, None)
        if sub is None:
            continue
        if conf_key not in cm_config:
            continue
        try:
            # F16: route through the setter when the tunable declares
            # one so range/kill-switch guards are actually invoked at
            # seed time (not just entity time).
            _hvac_tunable_apply(sub, conf_key, runtime_field,
                                cm_config[conf_key], cast_fn)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "HVAC tunable seed failed for %s -> %s.%s",
                conf_key, sub_attr, runtime_field,
                exc_info=True,
            )
    _LOGGER.info(
        "HVAC runtime tunables seeded from CM options (14 factory keys)"
    )


async def _seed_hvac_zone_kwh_thresholds_from_restore(hass, hvac) -> None:
    """Seed per-zone `ZoneState.kwh_rate_threshold` from HA RestoreState.

    HVAC-TUNABLE-RUNTIME-NOT-SEEDED-1 zone-arm (2026-08-21).
    Companion to `_seed_hvac_runtime_tunables_from_options` for the ONE
    Number that writes into a ZoneState field instead of a
    sub-controller attr (sweep: number.py:2467
    `_hvac_zone_kwh_threshold_factory`, sole hit for
    `zone.<field> =` in number.py). That entity uses RestoreEntity as
    its source of truth (deliberately split out from Part 2 D3), so
    the CM-options path used by the 14 factory tunables does not apply.

    Ordering: MUST run after `coordinator_manager.async_start()` because
    `HVACCoordinator.async_setup` runs `async_discover_zones()`
    (hvac.py:815) which populates `zone_manager.zones`. Called before
    that point, the lookup finds nothing and the seed is a no-op.

    Failure visibility (2026-08-21 fix-up): this knob fails UNSAFE —
    the ZoneState dataclass default is 0.8 kW (hvac_zones.py:124) but
    production runs 1.30 kW. A silent seed failure LOWERS the
    detection threshold, making the nudge MORE sensitive and firing
    MORE nudges (each nudge = 2 raw setpoint writes = manual-preset
    risk). Every unresolvable per-zone lookup therefore logs at
    WARNING (not debug) with the zone_id + reason, so the operator
    can grep for it in a WARNING-and-above filtered log. The
    infrastructural failures (import, RestoreStateData instance) also
    log at WARNING because they take out the whole seed pass.
    """
    zm = getattr(hvac, "_zone_manager", None)
    if zm is None or not zm.zones:
        # Not a failure — this is the pre-async_start / no-AC-zones
        # posture. Legit no-op (debug only).
        _LOGGER.debug(
            "Zone-kWh seed: no zones registered (pre-async_start "
            "or no AC zones configured); nothing to seed"
        )
        return
    # RESTORE-STATE ACCESS SHAPE (2026-08-21 fix-up B-RE-1 sibling):
    # Use the module-level SYNC `async_get` helper (a HA @callback).
    # `RestoreStateData` has no async classmethod — the awaited-
    # classmethod form NEVER worked and raised TypeError on every boot,
    # which the defensive except swallowed => guaranteed silent no-op =>
    # guaranteed UNSAFE fallback to 0.8 kW. Matches the pre-existing correct
    # exemplar at `__init__.py:1301-1313` (v5.7.1 D5 migration, guarded
    # by test_v5_7_1_energy_precool.py::test_restore_state_helper_is_called_sync_not_awaited).
    try:
        from homeassistant.helpers.restore_state import (
            async_get as async_get_restore_data,
        )
        from homeassistant.helpers import entity_registry as er
        from .domain_coordinators.hvac_zones import iter_canonical_hvac_zones
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "Zone-kWh seed FAILED (import error): all AC zones will "
            "fall back to dataclass default 0.8 kW — UNSAFE direction "
            "(more nudges, more manual-preset risk). Configured "
            "values will NOT take effect until an operator write "
            "pushes each per-zone threshold across.",
            exc_info=True,
        )
        return
    # SYNC call. Do NOT await — `async_get` is @callback, not a coroutine.
    restore_data = async_get_restore_data(hass)
    if restore_data is None:
        _LOGGER.warning(
            "Zone-kWh seed FAILED (RestoreStateData unavailable): all "
            "AC zones will fall back to dataclass default 0.8 kW — "
            "UNSAFE direction (more nudges, more manual-preset risk)"
        )
        return
    last_states = getattr(restore_data, "last_states", {}) or {}
    ent_reg = er.async_get(hass)
    seeded = 0
    unresolved: list[tuple[str, str]] = []  # (zone_id, reason)
    for spec in iter_canonical_hvac_zones(hass):
        zone_id = spec.get("zone_id") or "<unknown>"
        climate_entity = spec.get("climate_entity")
        if not spec.get("zone_id") or not climate_entity:
            unresolved.append((zone_id, "spec missing zone_id or climate_entity"))
            continue
        unique_id = f"{DOMAIN}_hvac_ac_kwh_threshold_{zone_id}"
        entity_id = ent_reg.async_get_entity_id("number", DOMAIN, unique_id)
        if entity_id is None:
            unresolved.append((
                zone_id,
                f"no entity registered for unique_id={unique_id} "
                "(first boot after per-zone Number added? or unique_id drift)",
            ))
            continue
        stored = last_states.get(entity_id)
        if stored is None:
            unresolved.append((
                zone_id,
                f"no RestoreState entry for {entity_id} (fresh install / "
                "state store cleared / entity never wrote a state)",
            ))
            continue
        try:
            raw = stored.state.state  # StoredState.state is a State-like obj
            val = float(raw)
        except (AttributeError, ValueError, TypeError) as e:
            unresolved.append((
                zone_id,
                f"restored state for {entity_id} is not numeric: {e!r}",
            ))
            continue
        matched = False
        for zone in zm.zones.values():
            if getattr(zone, "climate_entity", None) == climate_entity:
                try:
                    zone.kwh_rate_threshold = val
                    seeded += 1
                    matched = True
                except Exception as e:  # noqa: BLE001
                    unresolved.append((
                        zone_id,
                        f"setattr on ZoneState failed: {e!r}",
                    ))
                break
        if not matched and not any(z == zone_id for z, _ in unresolved):
            unresolved.append((
                zone_id,
                f"no ZoneManager zone matched climate_entity={climate_entity}",
            ))
    for zone_id, reason in unresolved:
        _LOGGER.warning(
            "Zone-kWh seed UNRESOLVED for zone %s: %s. Zone will use "
            "ZoneState default 0.8 kW — UNSAFE direction (more nudges, "
            "more manual-preset risk). Configured value will NOT take "
            "effect until an operator write pushes the threshold across.",
            zone_id, reason,
        )
    if seeded:
        _LOGGER.info(
            "HVAC: seeded %d per-zone AC kWh threshold(s) from RestoreState",
            seeded,
        )


# Energy Coordinator setter-based dispatch (calls a coordinator method, NOT
# a direct attr write — the setters carry side-effects like
# _check_threshold_ladder() that a raw setattr would skip).
_EC_SETTER_DISPATCH: dict[str, tuple[str, type]] = {
    _CONF_ENERGY_PEAK_BUFFER_TARGET:               ("set_peak_buffer_target",         int),
    _CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN:   ("set_arbitrage_charge_lead_time", int),
    _CONF_ENERGY_EV_BATTERY_DRAIN_SOC:             ("set_ev_battery_drain_soc",       int),
    # evse-charge-onset cycle — HH:MM string; blank ⇒ gate disabled.
    _CONF_ENERGY_EVSE_CHARGE_ONSET_TIME:           ("set_ev_charge_onset_time",       str),
    # Rev 6 D-A — enable toggle dispatched live via set_ev_charge_onset_enabled.
    _CONF_ENERGY_EVSE_CHARGE_ONSET_ENABLED:        ("set_ev_charge_onset_enabled",    bool),
    _CONF_ENERGY_FILL_PRIORITY_SOC:                ("set_fill_priority_soc",          int),
    _CONF_ENERGY_EXCESS_SOLAR_SOC:                 ("set_excess_solar_soc",           int),
    # Session B1 — EVSE Drain-Precedence Number + Select entities.
    # v5.21.0 fix-up (B-HIGH-1): route DP-enable through the setter so the
    # options-flow toggle applies live (coord attr updated + switch entity
    # state refreshed via SIGNAL_ENERGY_ENTITIES_UPDATE dispatch below).
    _CONF_ENERGY_DP_ENABLE:                        ("set_dp_enabled",                 bool),
    _CONF_ENERGY_DP_EVAL_DELAY_MIN:                ("set_dp_eval_delay_min",          int),
    _CONF_ENERGY_DP_MARGIN_MIN:                    ("set_dp_margin_min",              int),
    _CONF_ENERGY_DP_MUST_START_BY_MIN:             ("set_dp_must_start_by_min",       int),
    _CONF_ENERGY_DP_NEEDED_KWH_GARAGE_A:           ("set_dp_needed_kwh_garage_a",     float),
    _CONF_ENERGY_DP_NEEDED_KWH_GARAGE_B:           ("set_dp_needed_kwh_garage_b",     float),
    _CONF_ENERGY_DP_HOUSE_LOAD_SOURCE:             ("set_dp_house_load_source",       str),
    # v5.21.0 fix-up (SECOND OPERATOR ADDITION 2026-07-17) — D2 detection
    # knobs. Kill-switch semantics preserved by the setters (threshold 0 =
    # detection off; lag 0 = alert off, attribute still populated).
    _CONF_ENERGY_SOC_DIVERGENCE_THRESHOLD_PP:      ("set_soc_divergence_threshold_pp", int),
    _CONF_ENERGY_SOC_DIVERGENCE_DWELL_MIN:         ("set_soc_divergence_dwell_min",    int),
    _CONF_ENERGY_CLOUD_LAG_ALERT_S:                ("set_cloud_lag_alert_s",           int),
}

# Off-peak drain takes (quality, value) — special-cased below.
_OFFPEAK_DRAIN_QUALITY: dict[str, str] = {
    _CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT: "excellent",
    _CONF_ENERGY_OFFPEAK_DRAIN_GOOD:      "good",
    _CONF_ENERGY_OFFPEAK_DRAIN_MODERATE:  "moderate",
    _CONF_ENERGY_OFFPEAK_DRAIN_POOR:      "poor",
    _CONF_ENERGY_OFFPEAK_DRAIN_VERY_POOR: "very_poor",
}

# Keys where no live-attr push is needed; the listener just advances the
# snapshot (mirrors the v4.7.26 DPM-dwell pattern). Per-sub-family:
#   - DPM dwell + DPM hysteresis: consumer re-reads `entry.options` each
#     evaluation tick via `_get_cm_options()`.
#   - Routine event family (event_cooldown_days, event_min_severity):
#     consumer (notification_manager.py:2358-2379) reads live entity-state,
#     falling back to `cm_opts.get(CONF_…)` from entry.options.
#   - Routine regime family (regime_baseline/recent_window_days):
#     consumer (regime_detector.py:104-133, `_window_days`) reads live
#     entity-state, falling back to HARDCODED 56/14 academic-default seeds
#     (NOT `cm_opts.get(...)`).
#   - Bayesian cell staleness: consumer reads live entity-state.
# In all cases the Number setter's `async_write_ha_state()` refreshes the
# entity state, and the Number setter is the sole write path (verified:
# no config/options-flow path writes these keys), so the entity-state
# read sees fresh values without a live-attr push.
_NO_LIVE_ATTR_KEYS: frozenset[str] = frozenset({
    _CONF_DYNAMIC_PRESET_DWELL_MINUTES,
    _CONF_DYNAMIC_PRESET_HYSTERESIS_F,
    _CONF_ROUTINE_EVENT_COOLDOWN_DAYS,
    _CONF_ROUTINE_EVENT_MIN_SEVERITY,
    _CONF_ROUTINE_REGIME_BASELINE_WINDOW_DAYS,
    _CONF_ROUTINE_REGIME_RECENT_WINDOW_DAYS,
    _CONF_BAYESIAN_CELL_STALENESS_DAYS,
    # Blind-window guard cycle — D4 Emporia-mains backup export sensor.
    # `EnergyCoordinator.mains_export_active` reads `_entity_config` fresh
    # every tick; no live-attr push needed.
    _CONF_ENERGY_MAINS_EXPORT_ENTITY,
    # LKG wave 1 D2 — solar nameplate is read fresh via `_entity_config` in
    # `EnergyCoordinator.solar_production_w_envelope()` on every consumer
    # call; no live-attr push needed.
    _CONF_ENERGY_SOLAR_NAMEPLATE_W,
    # v4.7.34 — Optimization Coordinator (C-CRIT-1): the coordinator
    # reads `entry.options` fresh on every cycle, so no live-attr push
    # is needed.  These keys flow through `_apply_in_place` purely as a
    # no-op so the snapshot advances normally.
    _CONF_OPTIMIZER_AUTONOMY_LEVEL,
    _CONF_OPTIMIZER_KILL_SWITCH,
    _CONF_OPTIMIZER_DIMENSION_AUTONOMY,
    _CONF_OPTIMIZER_CONFIDENCE_GATE,
    _CONF_OPTIMIZER_RATE_CAP_PER_HOUR,
    _CONF_OPTIMIZER_QUIET_HOURS_SOURCE,
    # Pillar B (Phase 5) — pending-autonomy confirm-guard key. Coordinator
    # NEVER reads this key; it lives purely on `entry.options` and flows
    # through `_apply_in_place` as a no-op so the snapshot advances.
    _CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL,
    # v4.7.35 Phase 2 — LLM tier keys. OptimizationLLMTier reads CM
    # options fresh on every cycle (`_read_cm_config`) — no live-attr
    # push needed; flow through `_apply_in_place` as a no-op.
    _CONF_OPTIMIZER_LLM_TASK_ENTITY,
    _CONF_OPTIMIZER_LLM_TRIAGE_ENTITY,
    _CONF_OPTIMIZER_LLM_SYSTEM_PROMPT,
    _CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H,
    # v4.7.35 fix-up (B-B2) — deny-list read fresh on every chokepoint
    # invocation; no live-attr push needed.
    _CONF_OPTIMIZER_SAFETY_DENY_ENTITIES,
    # Arrester operator-immunity cycle (2026-08-06): AC-ramp master
    # option-persistence. The HVACACRampMasterSwitch is the SOLE write
    # path (no config-flow field); on toggle it applies the value
    # DIRECTLY to arrester._ramp_master_enabled AND write-throughs to
    # entry.options. So a subsequent options-update listener firing for
    # this key has no live-attr work to do — the switch already applied
    # it. The option only matters at INIT (arrester construction) to
    # survive config-entry reload. NO_LIVE_ATTR = correct classification.
    _CONF_HVAC_AC_RAMP_MASTER_ENABLED,
    # Arrester operator-immunity (2026-08-06 — MED-A2/B-L1):
    # `hvac_arrester_immune_persons` is applied live via
    # `set_immune_persons()` on the HVAC arrester in _apply_in_place;
    # there is no plain-attribute push (the arrester keeps a list of
    # its own that only the setter should mutate). Membership here
    # documents "no direct live-attr push needed" AND keeps the
    # snapshot-advance path clean — the explicit set_immune_persons
    # branch below fires the actual side-effect, then falls through
    # to the _NO_LIVE_ATTR_KEYS `applied.add` so the snapshot advances.
    _CONF_HVAC_ARRESTER_IMMUNE_PERSONS,
    # B-M2 marker: written by the switch on every toggle; no live-attr
    # push consumer — the option only matters at NEXT setup (marker
    # sweep in _fire_temp_arrester_override_lost_note).
    "hvac_temp_arrester_override_was_active",
    # v5.21.0 fix-up (B-HIGH-1): `_CONF_ENERGY_DP_ENABLE` used to live
    # here on the (incorrect) rationale that the switch entity is the
    # sole write path. The BAEC config-flow step (v5.21.0 D1) is a
    # SECOND ratified write path — persisting via options without
    # applying to the coord left the switch stale. Moved into
    # `_EC_SETTER_DISPATCH` above; the setter updates `_dp_enabled`
    # and we dispatch SIGNAL_ENERGY_ENTITIES_UPDATE below so the
    # switch entity's `is_on` (a live property reading the coord attr)
    # re-renders.
    # NM Cycle A-2 — knob keys consumed via `nm_cycle_a_knob(...)`
    # which reads entry.options fresh on every call (module-level
    # cache flushed by the update-listener). No live-attr push needed.
    *_NM_A2_KEYS,
    # NM Cycle B fix-up (2026-07-20, B-B1): dry-run + token-bucket keys.
    # Numbers/Switch call NM setters directly; NM re-reads via
    # `_refresh_config` — no live-attr push needed here.
    _CONF_NM_DRY_RUN,
    _CONF_NM_BUCKET_CAPACITY,
    _CONF_NM_BUCKET_REFILL_PER_MIN,
    # NM Cycle C — matrix / DND-bypass / mute-duration keys.
    *_NM_C_KEYS,
})

OPTIONS_RELOAD_SUPPRESS_KEYS: frozenset[str] = frozenset({
    # v4.7.26 (Cycle 1) — HVAC presence timers + DPM dwell
    _CONF_HVAC_VACANCY_GRACE_MINUTES,
    _CONF_HVAC_VACANCY_GRACE_CONSTRAINED,
    _CONF_HVAC_MAX_OCCUPANCY_HOURS,
    _CONF_HVAC_ZONE_ENTRY_DWELL,
    _CONF_DYNAMIC_PRESET_DWELL_MINUTES,
    # Part 2 D1 — EC Number family + Bayesian
    _CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT,
    _CONF_ENERGY_OFFPEAK_DRAIN_GOOD,
    _CONF_ENERGY_OFFPEAK_DRAIN_MODERATE,
    _CONF_ENERGY_OFFPEAK_DRAIN_POOR,
    _CONF_ENERGY_OFFPEAK_DRAIN_VERY_POOR,
    _CONF_ENERGY_PEAK_BUFFER_TARGET,
    _CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
    _CONF_ENERGY_EV_BATTERY_DRAIN_SOC,
    _CONF_ENERGY_FILL_PRIORITY_SOC,
    _CONF_ENERGY_EXCESS_SOLAR_SOC,
    # evse-charge-onset Rev 6 B-CRIT-2 — both onset knobs are pushed
    # live to the coord via `_EC_SETTER_DISPATCH`; a full CM reload
    # for a knob-turn is the reload-watchdog hazard (see
    # `feedback_parent_reload_watchdog_hazard`). Suppress here.
    _CONF_ENERGY_EVSE_CHARGE_ONSET_TIME,
    _CONF_ENERGY_EVSE_CHARGE_ONSET_ENABLED,
    # Blind-window guard cycle — D4 Emporia-mains backup export sensor.
    # Read at every excess-solar tick via `EnergyCoordinator.mains_export_active`,
    # so a change takes effect without a full CM reload.
    _CONF_ENERGY_MAINS_EXPORT_ENTITY,
    # LKG wave 1 D2 — solar nameplate for the production upper envelope.
    # Read fresh on every solar_production_w_envelope() call; no CM reload.
    _CONF_ENERGY_SOLAR_NAMEPLATE_W,
    _CONF_BAYESIAN_CELL_STALENESS_DAYS,
    # Part 2 D2 — Routine family
    _CONF_ROUTINE_EVENT_COOLDOWN_DAYS,
    _CONF_ROUTINE_EVENT_MIN_SEVERITY,
    _CONF_ROUTINE_REGIME_BASELINE_WINDOW_DAYS,
    _CONF_ROUTINE_REGIME_RECENT_WINDOW_DAYS,
    # Part 2 D3 — HVAC tunable factory (14 keys)
    *_HVAC_TUNABLE_DISPATCH.keys(),
    # Part 2 D5 — DPM hysteresis + egress + fan-interference hold
    _CONF_DYNAMIC_PRESET_HYSTERESIS_F,
    _CONF_HVAC_EGRESS_THRESHOLD_MIN,
    _CONF_HVAC_EGRESS_RESUME_DELAY_MIN,
    # Arrester operator-immunity cycle (2026-08-06): AC-ramp master
    # persistence. The HVACACRampMasterSwitch write-through updates
    # entry.options[hvac_ac_ramp_master_enabled] on every toggle; the
    # arrester seeds `_ramp_master_enabled` from this option at init
    # (fixes the reload→OFF regression the operator hit 2026-08-06
    # 20:36/20:39 CDT during options-flow saves — RestoreEntity's
    # last_state was 'unavailable' during the reload so its restore
    # path skipped, and the arrester was re-created at DEFAULT=False).
    _CONF_HVAC_AC_RAMP_MASTER_ENABLED,
    # Arrester operator-immunity (2026-08-06 — MED-A2/B-L1): options-flow
    # writes must not trigger a CM reload (which recreates the arrester
    # and drops any in-flight immune-hold records). Live update flows
    # through `set_immune_persons()` in _apply_in_place.
    _CONF_HVAC_ARRESTER_IMMUNE_PERSONS,
    # Temp Arrester Override marker (B-M2): the switch write-through
    # updates entry.options[hvac_temp_arrester_override_was_active] on
    # every toggle. That write must NOT trigger a reload (which would
    # recreate the arrester and clobber operator state mid-session).
    # Suppress-only; no live-attr consumer.
    "hvac_temp_arrester_override_was_active",
    _CONF_FAN_INTERFERENCE_HOLD_S,
    # v4.7.34 — Optimization Coordinator CM-level keys (C-CRIT-1).
    # OptimizationCoordinator reads entry.options fresh every cycle via
    # `_read_cm_config()`, so no live-attr push is needed — these belong
    # in `_NO_LIVE_ATTR_KEYS` below.
    _CONF_OPTIMIZER_AUTONOMY_LEVEL,
    _CONF_OPTIMIZER_KILL_SWITCH,
    _CONF_OPTIMIZER_DIMENSION_AUTONOMY,
    _CONF_OPTIMIZER_CONFIDENCE_GATE,
    _CONF_OPTIMIZER_RATE_CAP_PER_HOUR,
    _CONF_OPTIMIZER_QUIET_HOURS_SOURCE,
    # Pillar B — pending-autonomy confirm-guard key. Pressing the
    # autonomy select to stage a pending escalation must NOT trigger a
    # CM reload (the broker reads the real key fresh on every cycle).
    _CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL,
    # v4.7.35 Phase 2 — LLM tier keys. Editing the LLM provider,
    # triage backend, prompt, or 24h cap must NOT trigger a full
    # CM reload — the OptimizationLLMTier re-reads entry.options on
    # every cycle. (See `_NO_LIVE_ATTR_KEYS` above.)
    _CONF_OPTIMIZER_LLM_TASK_ENTITY,
    _CONF_OPTIMIZER_LLM_TRIAGE_ENTITY,
    _CONF_OPTIMIZER_LLM_SYSTEM_PROMPT,
    _CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H,
    # v4.7.35 fix-up (B-B2) — deny-list edits are options-only; no full
    # reload (chokepoint reads CM options fresh on every action).
    _CONF_OPTIMIZER_SAFETY_DENY_ENTITIES,
    # v5.10.0 D2 — MF sleep + night suppression push through
    # MusicFollowing.update_gate_config() without a CM reload.
    _CONF_MF_SLEEP_SUPPRESS,
    _CONF_MF_NIGHT_SUPPRESS_MODE,
    # Session B1 — EVSE Drain-Precedence knob keys (Switch + 5 Numbers +
    # Select). Numbers + Select route through `_EC_SETTER_DISPATCH` above;
    # the Switch key is a NO_LIVE_ATTR no-op (entity is sole write path).
    _CONF_ENERGY_DP_ENABLE,
    _CONF_ENERGY_DP_EVAL_DELAY_MIN,
    _CONF_ENERGY_DP_MARGIN_MIN,
    _CONF_ENERGY_DP_MUST_START_BY_MIN,
    _CONF_ENERGY_DP_NEEDED_KWH_GARAGE_A,
    _CONF_ENERGY_DP_NEEDED_KWH_GARAGE_B,
    _CONF_ENERGY_DP_HOUSE_LOAD_SOURCE,
    # v5.21.0 fix-up (SECOND OPERATOR ADDITION 2026-07-17) — D2 detection
    # knobs. Live-apply via `_EC_SETTER_DISPATCH`; no CM reload.
    _CONF_ENERGY_SOC_DIVERGENCE_THRESHOLD_PP,
    _CONF_ENERGY_SOC_DIVERGENCE_DWELL_MIN,
    _CONF_ENERGY_CLOUD_LAG_ALERT_S,
    # NM Cycle A-2 (2026-07-20) — 12 Cycle-A knobs + optimizer allowlist.
    # Consumed via `nm_cycle_a_knob(...)`; cache invalidated by the
    # update listener; no live-attr push, no reload.
    *_NM_A2_KEYS,
    # NM Cycle B fix-up (2026-07-20, B-B1): dry-run + token-bucket keys.
    # Entity is the sole write path; must not trigger a CM reload on toggle.
    _CONF_NM_DRY_RUN,
    _CONF_NM_BUCKET_CAPACITY,
    _CONF_NM_BUCKET_REFILL_PER_MIN,
    # NM Cycle C — options-flow-authored keys; NM re-reads via
    # `_refresh_config`. No CM reload needed.
    *_NM_C_KEYS,
})


# =====================================================================
# RELOAD-WATCHDOG-HAZARD (2026-08-15) — integration-entry reload suppress
# =====================================================================
# Mirrors the CM `OPTIONS_RELOAD_SUPPRESS_KEYS` pattern, scoped to the
# INTEGRATION (parent) entry. The observed 2026-08-07 outage came from a
# Camera Census save on the integration entry cascading a synchronous
# reload to ~40 child entries (~5-minute event-loop stall → supervisor
# watchdog restart). This branch short-circuits that reload when the
# changed key-set is a subset of `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS`
# and every allowlisted key either is fresh-read on every tick or has a
# discharge signal wired in `_INTEGRATION_KEY_SIGNAL_TABLE`.
#
# v1 seed per D1 audit (docs/planning/AUDIT_integration_options_reload_classification.md):
#   {CONF_CAMERA_PERSON_ENTITIES} only.
# CONF_EGRESS_CAMERAS / CONF_PERIMETER_CAMERAS are DELIBERATELY NOT in
# the allowlist — PerimeterAlertManager caches them at setup with no
# refresh signal today (parked follow-up #1). They stay on the legacy
# reload path (unchanged behavior; zero regression).
#
# NON-GOAL (plan MED-2): `_apply_in_place` is byte-identical after this
# cycle. The integration branch uses the sibling helper
# `_dispatch_integration_key_signals` — NOT an `entry_type` branch inside
# `_apply_in_place`. Bug Class #27 (primary/deferred mirror drift): the
# CM helper and the integration helper stay independent.
INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS: frozenset[str] = frozenset({
    CONF_CAMERA_PERSON_ENTITIES,
    # CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1 (2026-08-18):
    # CONF_FACE_RECOGNITION_ENABLED — cached at
    # `transit_validator.py:259` (self._face_recognition_enabled) AND
    # `presence.py:2451` (self._face_recognition_enabled). Discharge
    # signal SIGNAL_URA_FACE_RECOGNITION_CHANGED wired in
    # `_INTEGRATION_KEY_SIGNAL_TABLE` below; both consumers subscribe
    # and re-read on receipt.
    CONF_FACE_RECOGNITION_ENABLED,
    # CONF_EGRESS_IDENTITY_ENABLED — fresh-read at every consumer:
    # `camera_census._is_egress_identity_enabled` (2858-2870) and the
    # indirect `transit_validator.py:1094` path via
    # `camera_census.register_egress_face` → the same reader. No
    # cached-consumer discharge signal needed (path (a) of the
    # suppression-needs-discharge rule).
    CONF_EGRESS_IDENTITY_ENABLED,
})

# Rung-1 kill switch (numbers-get-knobs). Flipping to False re-enables
# the pre-cycle reload behavior AND skips the discharge dispatch (see
# plan LOW-1) — the reload rebuilds subscriptions naturally, and a
# parallel dispatch on the fall-through path doubles work + confuses
# logs. This is a fire-axe; adding/removing it requires review.
INTEGRATION_RELOAD_SUPPRESS_ENABLED: bool = True

# Rung-1 wiring table (per-key discharge signals). v1: the transit
# validator's cached subscription set is the only cached consumer of
# CONF_CAMERA_PERSON_ENTITIES; SIGNAL_URA_TRANSIT_CONFIG_CHANGED is
# subscribed at transit_validator.py:328 and rebuilds subs on receipt.
# Camera Census itself is fresh-read (`camera_census.py:1803-1821`);
# `fan_veto.py:353` is fresh-read via caller `_config()`
# (`actuator_reconciler.py:212-214` — `{**data, **options}` per call).
_INTEGRATION_KEY_SIGNAL_TABLE: dict[str, tuple[str, ...]] = {
    CONF_CAMERA_PERSON_ENTITIES: (SIGNAL_URA_TRANSIT_CONFIG_CHANGED,),
    # CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1 (2026-08-18): face-recognition
    # cached at transit_validator.py:259 + presence.py:2451.
    CONF_FACE_RECOGNITION_ENABLED: (SIGNAL_URA_FACE_RECOGNITION_CHANGED,),
    # CONF_EGRESS_IDENTITY_ENABLED intentionally absent — fresh-read at
    # all consumers (camera_census._is_egress_identity_enabled +
    # indirect transit_validator.py:1094). No cached-consumer discharge
    # needed.
}


def _dispatch_integration_key_signals(
    hass: HomeAssistant,
    entry: ConfigEntry,
    changed_keys: set[str],
) -> None:
    """Fire discharge signals for each allowlisted integration-entry key.

    Sibling helper to `_apply_in_place` (NOT an extension of it — plan
    MED-2, Bug Class #27). Per-signal try/except mirrors the CM branch's
    defensive posture: persistence has already happened via
    `async_update_entry`, so a dispatch failure logs WARNING and does NOT
    re-raise — converting a persisted write into an outage-inducing
    reload is worse than a silent-until-next-tick cached-consumer stale.
    """
    from homeassistant.helpers.dispatcher import async_dispatcher_send
    for key in changed_keys:
        signals = _INTEGRATION_KEY_SIGNAL_TABLE.get(key, ())
        for sig in signals:
            try:
                async_dispatcher_send(hass, sig, entry.entry_id, key)
            except Exception:  # noqa: BLE001 — never re-raise; see docstring
                _LOGGER.warning(
                    "INTEGRATION options: dispatch of signal=%s for "
                    "key=%s failed (non-fatal)",
                    sig, key, exc_info=True,
                )


def _seed_cm_last_applied_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Seed/refresh the per-CM-entry last-applied-options snapshot.

    Called at the END of CM setup (so subsequent listener fires can diff)
    AND at the end of every in-place apply (so the next edit diffs against
    the post-apply state, not the pre-apply state).
    """
    snapshots = hass.data.setdefault(DOMAIN, {}).setdefault(
        "cm_last_applied_options", {},
    )
    snapshots[entry.entry_id] = dict(entry.options)


def _seed_integration_last_applied_options(
    hass: HomeAssistant, entry: ConfigEntry,
) -> None:
    """Seed the per-INTEGRATION-entry last-applied-options snapshot.

    RELOAD-WATCHDOG-HAZARD fix-up (2026-08-15, Review A H-1 / Review B B-HIGH-1):
    the integration-entry suppress branch in ``_async_update_listener``
    diffs `entry.options` against this dict. Without a boot-time seed the
    FIRST post-restart options save saw `old={}`, so `changed_keys`
    reduced to `set(new.keys())` — a superset of the single-key allowlist —
    and the subset check FAILED, cascading a full reload (i.e. the very
    2026-08-07 outage this cycle exists to prevent). Sibling helper to
    ``_seed_cm_last_applied_options``, deliberately NOT an extension of it
    (Bug Class #27 — primary/deferred mirror drift). Call once from the
    integration setup path BEFORE `entry.add_update_listener(...)` is
    registered.
    """
    snapshots = hass.data.setdefault(DOMAIN, {}).setdefault(
        "integration_last_applied_options", {},
    )
    snapshots[entry.entry_id] = dict(entry.options)


def _apply_in_place(
    hass: HomeAssistant,
    entry: ConfigEntry,
    changed_keys: set[str],
    new_options: dict,
) -> set[str]:
    """Push allowlisted option changes to live coordinator attrs in place.

    Idempotent and tolerant of missing coordinators (CM may be mid-teardown
    or HVAC/energy may have failed to construct). Each branch early-returns
    if the target coordinator is None.

    DPM dwell (CONF_DYNAMIC_PRESET_DWELL_MINUTES) does NOT need an explicit
    live-attr poke: the Energy coordinator's DPM evaluate-and-emit reads
    `entry.options` fresh on every tick via `_get_cm_options()` (verified at
    `domain_coordinators/energy.py:2850-2865`). By the time this function
    runs, `async_update_entry` has already updated `entry.options`, so the
    next evaluate_and_emit tick picks up the new dwell automatically. DPM
    dwell is reported as "applied" by this function so the listener's
    snapshot advances normally for it.

    Returns the set of `changed_keys` whose live-attr write (or no-op for
    DPM dwell) completed cleanly. The LISTENER owns the snapshot-merge
    decision based on this return value: keys NOT in the returned set keep
    their OLD snapshot value so the next diff retries them. Per-key
    try/except (HIGH-1 fix) guarantees that one malformed value cannot
    silently suppress its three siblings.

    Defensive clamp (B-HIGH-1): after the per-key writes, this function
    re-enforces the v4.7.25 A-HIGH-1 invariant
    `_vacancy_grace_constrained <= _vacancy_grace` in case an out-of-band
    write (external `async_update_entry`, future service/YAML path)
    bypassed the Number-setter clamp.
    """
    applied: set[str] = set()
    manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
    hvac = manager.coordinators.get("hvac") if manager is not None else None
    energy = manager.coordinators.get("energy") if manager is not None else None
    presence = manager.coordinators.get("presence") if manager is not None else None

    # A-MED-1: if HVAC coordinator is None but allowlisted HVAC-owned keys
    # are in changed_keys, emit ONE INFO. The DPM dwell key is NOT
    # HVAC-owned — it's handled by energy.py re-read each tick, so it
    # should NOT trigger this log. Part 2: the EC family + Routine family +
    # Bayesian + DPM hysteresis all also legitimately apply with hvac=None
    # (their consumers are EC / Routine / lookup-based).
    _hvac_owned_keys = {
        _CONF_HVAC_VACANCY_GRACE_MINUTES,
        _CONF_HVAC_VACANCY_GRACE_CONSTRAINED,
        _CONF_HVAC_MAX_OCCUPANCY_HOURS,
        _CONF_HVAC_ZONE_ENTRY_DWELL,
        # Part 2 D3 — HVAC tunable factory (14 keys)
        *_HVAC_TUNABLE_DISPATCH.keys(),
        # Part 2 D5 — egress thresholds (HVAC-owned via egress_manager)
        _CONF_HVAC_EGRESS_THRESHOLD_MIN,
        _CONF_HVAC_EGRESS_RESUME_DELAY_MIN,
        # Arrester operator-immunity (2026-08-06 MED-A2/B-L1)
        _CONF_HVAC_ARRESTER_IMMUNE_PERSONS,
    }
    _ec_owned_keys = {
        *_OFFPEAK_DRAIN_QUALITY.keys(),
        *_EC_SETTER_DISPATCH.keys(),
    }

    if hvac is None:
        if changed_keys & _hvac_owned_keys:
            _LOGGER.info(
                "CM in-place apply: HVAC coordinator not available "
                "(likely mid-reload); values for %s are persisted in "
                "entry.options and will be picked up on next HVAC setup",
                sorted(changed_keys & _hvac_owned_keys),
            )
        # Keys whose consumer re-reads entry.options each tick: mark as
        # applied so the listener snapshot advances (the option write
        # already persisted — no further action needed).
        for k in changed_keys & _NO_LIVE_ATTR_KEYS:
            applied.add(k)
        # EC-owned and fan-interference (presence-owned) keys are NOT
        # HVAC-owned: try to apply them below even if hvac is None.
        # Fall through to the EC + presence + no-live-attr branches.

    # Arrester operator-immunity (2026-08-06 — MED-A2/B-L1). Live-apply
    # the immune-person list by calling `set_immune_persons()` on the
    # arrester. `_NO_LIVE_ATTR_KEYS` membership above already marked
    # this key as "no plain-attr push"; here we do the actual method
    # invocation. Snapshot advancement happens via that fallback.
    if (
        _CONF_HVAC_ARRESTER_IMMUNE_PERSONS in changed_keys
        and hvac is not None
        and getattr(hvac, "_override_arrester", None) is not None
    ):
        try:
            new_list = list(
                new_options.get(
                    _CONF_HVAC_ARRESTER_IMMUNE_PERSONS, [],
                ) or []
            )
            hvac._override_arrester.set_immune_persons(new_list)
            applied.add(_CONF_HVAC_ARRESTER_IMMUNE_PERSONS)
        except (AttributeError, TypeError, ValueError) as err:
            _LOGGER.warning(
                "CM in-place apply: arrester set_immune_persons failed "
                "for value=%r: %s",
                new_options.get(_CONF_HVAC_ARRESTER_IMMUNE_PERSONS),
                err,
            )

    # HIGH-1: per-key try/except so one bad value cannot suppress its
    # siblings. B-MED-2: widened to AttributeError (coordinator may be
    # mid-teardown with attrs nulled).
    if _CONF_HVAC_VACANCY_GRACE_MINUTES in changed_keys:
        try:
            hvac._vacancy_grace = int(
                new_options[_CONF_HVAC_VACANCY_GRACE_MINUTES],
            )
            applied.add(_CONF_HVAC_VACANCY_GRACE_MINUTES)
        except (AttributeError, KeyError, ValueError, TypeError) as err:
            _LOGGER.warning(
                "CM in-place apply: HVAC live-attr push failed for "
                "key=%s value=%r: %s",
                _CONF_HVAC_VACANCY_GRACE_MINUTES,
                new_options.get(_CONF_HVAC_VACANCY_GRACE_MINUTES),
                err,
            )
    if _CONF_HVAC_VACANCY_GRACE_CONSTRAINED in changed_keys:
        try:
            hvac._vacancy_grace_constrained = int(
                new_options[_CONF_HVAC_VACANCY_GRACE_CONSTRAINED],
            )
            applied.add(_CONF_HVAC_VACANCY_GRACE_CONSTRAINED)
        except (AttributeError, KeyError, ValueError, TypeError) as err:
            _LOGGER.warning(
                "CM in-place apply: HVAC live-attr push failed for "
                "key=%s value=%r: %s",
                _CONF_HVAC_VACANCY_GRACE_CONSTRAINED,
                new_options.get(_CONF_HVAC_VACANCY_GRACE_CONSTRAINED),
                err,
            )
    if _CONF_HVAC_MAX_OCCUPANCY_HOURS in changed_keys:
        try:
            hvac._max_occupancy_hours = int(
                new_options[_CONF_HVAC_MAX_OCCUPANCY_HOURS],
            )
            applied.add(_CONF_HVAC_MAX_OCCUPANCY_HOURS)
        except (AttributeError, KeyError, ValueError, TypeError) as err:
            _LOGGER.warning(
                "CM in-place apply: HVAC live-attr push failed for "
                "key=%s value=%r: %s",
                _CONF_HVAC_MAX_OCCUPANCY_HOURS,
                new_options.get(_CONF_HVAC_MAX_OCCUPANCY_HOURS),
                err,
            )
    if _CONF_HVAC_ZONE_ENTRY_DWELL in changed_keys:
        try:
            hvac._zone_entry_dwell = int(
                new_options[_CONF_HVAC_ZONE_ENTRY_DWELL],
            )
            applied.add(_CONF_HVAC_ZONE_ENTRY_DWELL)
        except (AttributeError, KeyError, ValueError, TypeError) as err:
            _LOGGER.warning(
                "CM in-place apply: HVAC live-attr push failed for "
                "key=%s value=%r: %s",
                _CONF_HVAC_ZONE_ENTRY_DWELL,
                new_options.get(_CONF_HVAC_ZONE_ENTRY_DWELL),
                err,
            )

    # ----- Part 2 D3: HVAC tunable factory (14 keys) -----
    # Each key dispatches via setattr against a sub-controller attr; the
    # 5 watch-list keys consume their runtime_field inline at the call
    # site (no stashed timedelta cache), so a plain setattr is sufficient.
    # The cast (int vs float) comes from the dispatch table, which is the
    # single source of truth shared with `_HVACTunableNumber`.
    for key, (sub_attr, runtime_field, cast_fn) in _HVAC_TUNABLE_DISPATCH.items():
        if key not in changed_keys:
            continue
        if hvac is None:
            continue  # already logged above; key not added to applied
        try:
            sub = getattr(hvac, sub_attr, None)
            if sub is None:
                _LOGGER.info(
                    "CM in-place apply: HVAC sub-controller %s not available "
                    "for key=%s; value will be picked up on next setup",
                    sub_attr, key,
                )
                continue
            # F16: setter-aware push (see `_hvac_tunable_apply`).
            _hvac_tunable_apply(sub, key, runtime_field,
                                new_options[key], cast_fn)
            applied.add(key)
        except (AttributeError, KeyError, ValueError, TypeError) as err:
            _LOGGER.warning(
                "CM in-place apply: HVAC tunable push failed for "
                "key=%s value=%r: %s",
                key, new_options.get(key), err,
            )

    # ----- Part 2 D5: HVAC egress thresholds -----
    # `egress_manager` is a @property (hvac.py:295) backed by
    # `self._egress_manager`, which can be None mid-teardown. Mirror the
    # HVAC-tunable loop's `if sub is None: continue` guard so we don't
    # AttributeError on `None.set_threshold_min(...)` during teardown races.
    if _CONF_HVAC_EGRESS_THRESHOLD_MIN in changed_keys and hvac is not None:
        try:
            egress_mgr = hvac.egress_manager
            if egress_mgr is None:
                _LOGGER.info(
                    "CM in-place apply: egress_manager not available for "
                    "key=%s; value will be picked up on next setup",
                    _CONF_HVAC_EGRESS_THRESHOLD_MIN,
                )
            else:
                egress_mgr.set_threshold_min(
                    int(new_options[_CONF_HVAC_EGRESS_THRESHOLD_MIN]),
                )
                applied.add(_CONF_HVAC_EGRESS_THRESHOLD_MIN)
        except (AttributeError, KeyError, ValueError, TypeError) as err:
            _LOGGER.warning(
                "CM in-place apply: egress threshold push failed: %s", err,
            )
    if _CONF_HVAC_EGRESS_RESUME_DELAY_MIN in changed_keys and hvac is not None:
        try:
            egress_mgr = hvac.egress_manager
            if egress_mgr is None:
                _LOGGER.info(
                    "CM in-place apply: egress_manager not available for "
                    "key=%s; value will be picked up on next setup",
                    _CONF_HVAC_EGRESS_RESUME_DELAY_MIN,
                )
            else:
                egress_mgr.set_resume_delay_min(
                    int(new_options[_CONF_HVAC_EGRESS_RESUME_DELAY_MIN]),
                )
                applied.add(_CONF_HVAC_EGRESS_RESUME_DELAY_MIN)
        except (AttributeError, KeyError, ValueError, TypeError) as err:
            _LOGGER.warning(
                "CM in-place apply: egress resume-delay push failed: %s", err,
            )

    # ----- Part 2 D1: EC Number family -----
    # OffPeakDrain takes (quality, value) — must use the EC setter (NOT a
    # direct attr write — the setter calls _check_threshold_ladder()).
    for key, quality in _OFFPEAK_DRAIN_QUALITY.items():
        if key not in changed_keys:
            continue
        if energy is None:
            _LOGGER.info(
                "CM in-place apply: Energy coordinator not available for "
                "key=%s; persisted in entry.options for next EC setup", key,
            )
            continue
        try:
            energy.set_offpeak_drain(quality, int(new_options[key]))
            applied.add(key)
        except (AttributeError, KeyError, ValueError, TypeError) as err:
            _LOGGER.warning(
                "CM in-place apply: OffPeakDrain push failed key=%s "
                "value=%r: %s", key, new_options.get(key), err,
            )
    # Other EC keys dispatch via their setter method on the EC instance
    # (setters carry side-effects: clamps, threshold-ladder check, log).
    for key, (setter_name, cast_fn) in _EC_SETTER_DISPATCH.items():
        if key not in changed_keys:
            continue
        if energy is None:
            _LOGGER.info(
                "CM in-place apply: Energy coordinator not available for "
                "key=%s; persisted in entry.options for next EC setup", key,
            )
            continue
        try:
            setter = getattr(energy, setter_name, None)
            if setter is None:
                _LOGGER.warning(
                    "CM in-place apply: EC setter %s missing for key=%s",
                    setter_name, key,
                )
                continue
            setter(cast_fn(new_options[key]))
            applied.add(key)
            # v5.21.0 fix-up (B-HIGH-1): DP-enable is the only setter where
            # a switch entity mirrors the coord attr live. Ping the shared
            # EC entities signal so `_ec_switch_factory` subscribers call
            # `async_write_ha_state()` — HA re-reads `is_on` (live prop on
            # coord attr) and emits a state_changed event. Number/select
            # entities that also subscribe re-render harmlessly (their
            # `_value` is unchanged; display staleness precedent A3 stands).
            if key == _CONF_ENERGY_DP_ENABLE:
                try:
                    from homeassistant.helpers.dispatcher import (
                        async_dispatcher_send,
                    )
                    from .domain_coordinators.signals import (
                        SIGNAL_ENERGY_ENTITIES_UPDATE,
                    )
                    async_dispatcher_send(hass, SIGNAL_ENERGY_ENTITIES_UPDATE)
                except Exception:  # noqa: BLE001 — best-effort push
                    _LOGGER.debug(
                        "EC entity refresh dispatch failed", exc_info=True,
                    )
        except (AttributeError, KeyError, ValueError, TypeError) as err:
            _LOGGER.warning(
                "CM in-place apply: EC setter %s failed key=%s value=%r: %s",
                setter_name, key, new_options.get(key), err,
            )

    # ----- Part 2 D5: Fan-interference hold (presence coordinator) -----
    if _CONF_FAN_INTERFERENCE_HOLD_S in changed_keys:
        if presence is None:
            _LOGGER.info(
                "CM in-place apply: Presence coordinator not available for "
                "fan_interference_hold_s; persisted in entry.options",
            )
        else:
            try:
                presence.set_fan_interference_hold_s(
                    int(new_options[_CONF_FAN_INTERFERENCE_HOLD_S]),
                )
                applied.add(_CONF_FAN_INTERFERENCE_HOLD_S)
            except (AttributeError, KeyError, ValueError, TypeError) as err:
                _LOGGER.warning(
                    "CM in-place apply: fan_interference_hold_s push failed: %s",
                    err,
                )

    # ----- B-HIGH-1: defensive clamp for vacancy-grace pair -----
    # Re-enforce the v4.7.25 A-HIGH-1 invariant in case an out-of-band
    # write bypassed the Number-setter's clamp (external
    # `async_update_entry`, future service/YAML path).
    try:
        if hvac._vacancy_grace_constrained > hvac._vacancy_grace:
            _LOGGER.warning(
                "CM in-place apply: clamping _vacancy_grace_constrained=%s "
                "to _vacancy_grace=%s (out-of-band write bypassed setter "
                "clamp)",
                hvac._vacancy_grace_constrained, hvac._vacancy_grace,
            )
            hvac._vacancy_grace_constrained = hvac._vacancy_grace
    except AttributeError:
        pass

    # ----- v5.10.0 D2 — Music Following sleep + night suppression -----
    # Live-attr push into the standalone MusicFollowing singleton via
    # update_gate_config(). If the coordinator or singleton is missing
    # (mid-teardown), leave the key OUT of `applied` so the next diff
    # retries it — mirrors the HVAC pattern above.
    _mf_keys = {_CONF_MF_SLEEP_SUPPRESS, _CONF_MF_NIGHT_SUPPRESS_MODE}
    if changed_keys & _mf_keys:
        mf_coord = None
        try:
            if manager is not None:
                mf_coord = manager.coordinators.get("music_following")
        except Exception:
            mf_coord = None
        mf = hass.data.get(DOMAIN, {}).get("music_following")
        if mf is None:
            _LOGGER.info(
                "CM in-place apply: MusicFollowing singleton not available "
                "(likely mid-reload); values for %s are persisted in "
                "entry.options and will be picked up on next MF setup",
                sorted(changed_keys & _mf_keys),
            )
        else:
            if _CONF_MF_SLEEP_SUPPRESS in changed_keys:
                try:
                    mf.update_gate_config(
                        sleep_suppress=bool(
                            new_options[_CONF_MF_SLEEP_SUPPRESS],
                        ),
                    )
                    applied.add(_CONF_MF_SLEEP_SUPPRESS)
                    # v5.10.0 fix-up B-LOW-1: mirror-write into
                    # ``mf_coord._sleep_suppress`` deleted. It was never
                    # load-bearing — the coordinator re-reads from
                    # entry.options on its next async_setup (see
                    # domain_coordinators/music_following.py :__init__ +
                    # async_setup pushing via update_gate_config()).
                    # Options is the source of truth on the persisted
                    # side; the singleton is the source of truth on the
                    # live side. No third mirror is needed.
                except (AttributeError, KeyError, ValueError, TypeError) as err:
                    _LOGGER.warning(
                        "CM in-place apply: MF live-attr push failed for "
                        "key=%s value=%r: %s",
                        _CONF_MF_SLEEP_SUPPRESS,
                        new_options.get(_CONF_MF_SLEEP_SUPPRESS),
                        err,
                    )
            if _CONF_MF_NIGHT_SUPPRESS_MODE in changed_keys:
                try:
                    mf.update_gate_config(
                        night_suppress_mode=str(
                            new_options[_CONF_MF_NIGHT_SUPPRESS_MODE],
                        ),
                    )
                    applied.add(_CONF_MF_NIGHT_SUPPRESS_MODE)
                    # v5.10.0 fix-up B-LOW-1: mirror-write into
                    # ``mf_coord._night_suppress_mode`` deleted — same
                    # rationale as _sleep_suppress above.
                except (AttributeError, KeyError, ValueError, TypeError) as err:
                    _LOGGER.warning(
                        "CM in-place apply: MF live-attr push failed for "
                        "key=%s value=%r: %s",
                        _CONF_MF_NIGHT_SUPPRESS_MODE,
                        new_options.get(_CONF_MF_NIGHT_SUPPRESS_MODE),
                        err,
                    )

    # ----- Keys whose consumer re-reads entry.options each tick -----
    # No live-attr push needed (option write already persisted by the
    # caller before this function fires). DPM dwell + DPM hysteresis read
    # via energy.py `_get_cm_options()`; Routine family + Bayesian read
    # via entity-state lookup with `cm_opts.get(...)` fallback.
    for k in changed_keys & _NO_LIVE_ATTR_KEYS:
        applied.add(k)

    return applied


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — apply in place for allowlisted CM keys, else reload.

    v4.0.5: Fire reload as a background task instead of awaiting it.
    The old `await async_reload()` ran in the OptionsFlow HTTP request context.
    With 93+ entities per room, the unload/setup cycle exceeded the frontend's
    ~30s timeout — aiohttp cancelled the task mid-reload, leaving the entry
    half-unloaded and the coordinator unable to pick up new config.

    CM reload suppression (this cycle): when the CM entry's options write
    only changes keys in `OPTIONS_RELOAD_SUPPRESS_KEYS`, push to live
    coordinator attrs instead of reloading. Persistence is unchanged
    (already done by `async_update_entry`). ROOM and ZONE_MANAGER entries
    are unchanged from the legacy reload-everything behavior.
    """
    entry_type = entry.data.get(CONF_ENTRY_TYPE)

    # C-HIGH-3 fix-up (v4.7.34): ROOM-entry comfort-slider writes used to
    # trigger a full ROOM reload (~90 entities) on every slider drag.
    # The OptimizationCoordinator reads `comfort_temp_min/max` and
    # `comfort_humidity_max` fresh on every cycle via
    # ``_read_per_room_comfort()``; the Number entity's `_value` is the
    # only other consumer, and it lives in the same process and was
    # already mutated by the setter that triggered this listener. So a
    # ROOM-entry write that ONLY changed comfort-slider keys is a pure
    # persistence operation — no reload required.
    # Zone Delete Flow fix-up R2 (B-CRIT-2): CONF_ZONE writes during zone
    # reassignment (delete flow clears each affected ROOM's CONF_ZONE) must
    # NOT trigger per-room reloads — deleting a 6-room zone would otherwise
    # storm 6 ROOM reloads in parallel plus the ZM reload.
    #
    # Verified safe (fix-up R2 precondition): CONF_ZONE consumers all read
    # LIVE from the entry every tick — no in-memory cache to push to:
    #   - aggregation.py:508  data.entry.data.get(CONF_ZONE) or ...options.get
    #   - aggregation.py:892  coord.entry.options.get(CONF_ZONE) or ...data
    #   - aggregation.py:942  coord.entry.options.get(CONF_ZONE) or ...data
    #   - aggregation.py:3549 coord.entry.options.get(CONF_ZONE)
    #   - aggregation.py:5714 coord.entry.options.get(CONF_ZONE) or ...data
    #   - __init__.py:111     config_entry.options.get(CONF_ZONE) or ...data
    #   - safety.py:2335      merged.get(CONF_ZONE, "") after merge
    # None of these cache; nothing to push in-place. The suppress branch
    # is a documented no-op (persistence has already happened via
    # ``async_update_entry``); consumers pick up the new value on their
    # next natural tick.
    _ROOM_SUPPRESS_KEYS: frozenset[str] = frozenset({
        _CONF_COMFORT_TEMP_MIN,
        _CONF_COMFORT_TEMP_MAX,
        _CONF_COMFORT_HUMIDITY_MAX,
        CONF_ZONE,
        # Fan/humidity toggle-symmetry (2026-07-22, HIGH F1):
        # RoomComfortFanControlSwitch / RoomHumidityFanControlSwitch mirror
        # into entry.options on every physical toggle (switch.py:4576-4586).
        # Without these keys in the suppress set, every toggle → full ROOM
        # reload (~90-entity cycle) via the fall-through async_reload below.
        # Safe: consumers read live merged options every tick (see import
        # comment above and AUDIT §1).
        _CONF_FAN_CONTROL_ENABLED,
        _CONF_HUMIDITY_FAN_CONTROL_ENABLED,
    })

    if entry_type == ENTRY_TYPE_ROOM:
        snapshots = hass.data.setdefault(DOMAIN, {}).setdefault(
            "room_last_applied_options", {},
        )
        old = snapshots.get(entry.entry_id, {})
        new = dict(entry.options)
        changed_keys = {
            k for k in (old.keys() | new.keys())
            if old.get(k) != new.get(k)
        }
        if changed_keys and changed_keys.issubset(_ROOM_SUPPRESS_KEYS):
            _LOGGER.info(
                "ROOM options changed for '%s' (%s) — comfort slider "
                "write, suppressing reload (changed_keys=%s)",
                entry.title, entry.entry_id, sorted(changed_keys),
            )
            snapshots[entry.entry_id] = dict(new)
            # Substrate re-subscribe cycle (D1): fire lifecycle signal even
            # on suppressed writes. Substrate CONF sensor lists (motion /
            # mmwave / occupancy) are NOT in _ROOM_SUPPRESS_KEYS today, so
            # this dispatch is defensive against future expansion of the
            # suppress set silently reopening the v4.7.24 blind spot.
            # refresh_subscriptions() diffs to zero-change when nothing
            # sensor-list-relevant moved — cost = one enumeration walk.
            try:
                from homeassistant.helpers.dispatcher import async_dispatcher_send
                from .domain_coordinators.signals import SIGNAL_ROOM_ENTRY_LIFECYCLE
                async_dispatcher_send(
                    hass,
                    SIGNAL_ROOM_ENTRY_LIFECYCLE,
                    entry.entry_id,
                    entry.data.get("room_name"),
                    "options_updated",
                )
            except Exception:  # noqa: BLE001 — defensive
                _LOGGER.debug(
                    "SIGNAL_ROOM_ENTRY_LIFECYCLE dispatch (options_updated) failed (non-fatal)",
                    exc_info=True,
                )
            return
        # Mixed / unknown change → reseed snapshot so future slider-only
        # writes diff against current state, then fall through to reload.
        # NOTE: The fall-through path triggers a full ROOM reload via
        # hass.config_entries.async_reload(entry.entry_id) (see below),
        # which cycles unload → setup and thus fires "unloaded" and
        # "loaded" naturally — no explicit "options_updated" dispatch
        # needed on the fall-through branch.
        snapshots[entry.entry_id] = dict(new)

    if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:
        # NM Cycle A-2 B-LOW-1: total-flush the NM knob cache on EVERY
        # CM options-update, unconditionally and before any subset check.
        # Cheap (dict.clear), correctness-first — the next
        # `nm_cycle_a_knob(...)` call reads fresh from `entry.options`.
        try:
            from .domain_coordinators._nm_cycle_a import invalidate_knob_cache
            invalidate_knob_cache()
        except Exception:  # noqa: BLE001 — defensive; never block the listener
            # C-LOW-2 fix-up (2026-07-20): raise to WARNING so a repeatedly
            # failing cache flush is visible in the log (was DEBUG, silent
            # in default log config).
            _LOGGER.warning(
                "NM Cycle A-2: invalidate_knob_cache raised (non-fatal)",
                exc_info=True,
            )
        snapshots = hass.data.setdefault(DOMAIN, {}).setdefault(
            "cm_last_applied_options", {},
        )
        old = snapshots.get(entry.entry_id, {})
        new = dict(entry.options)
        changed_keys = {
            k for k in (old.keys() | new.keys())
            if old.get(k) != new.get(k)
        }
        if not changed_keys:
            # Defensive no-op (HA core already short-circuits identical writes
            # at the `async_update_entry` layer; this guard handles paths that
            # bypass that short-circuit, e.g. external snapshot drift).
            return
        if changed_keys.issubset(OPTIONS_RELOAD_SUPPRESS_KEYS):
            _LOGGER.info(
                "CM options changed for '%s' (%s) — in-place apply, "
                "suppressing reload (changed_keys=%s)",
                entry.title, entry.entry_id, sorted(changed_keys),
            )
            applied = _apply_in_place(hass, entry, changed_keys, new)
            # C3 (Review C) — snapshot ownership lives in the listener so
            # future callers of `_apply_in_place` can't forget it. Handle
            # partial-apply correctly: for any changed key that did NOT
            # apply cleanly, KEEP the OLD value in the snapshot so the
            # next listener fire re-diffs and re-attempts; if there was no
            # OLD value for it, drop it from the snapshot. Keys that
            # applied cleanly take their NEW value (persisted truth).
            snapshot = dict(new)
            for k in (changed_keys - applied):
                if k in old:
                    snapshot[k] = old[k]
                else:
                    snapshot.pop(k, None)
            snapshots[entry.entry_id] = snapshot
            return
        # Mixed or non-allowlisted change → fall through to reload.
        # B-LOW-3: enrich the CM fall-through log so a live tail can
        # distinguish it from the generic ROOM/ZONE_MANAGER reload log
        # below. The generic log line still fires below for parity with
        # the legacy ROOM/ZONE path.
        _LOGGER.info(
            "CM options changed for '%s' (%s) — mixed/non-allowlisted "
            "keys present, falling through to reload (changed_keys=%s)",
            entry.title, entry.entry_id, sorted(changed_keys),
        )
        # B-HIGH-2 (Review B): reseed the snapshot to the post-write
        # options BEFORE scheduling the reload so a second in-flight
        # write during the reload diffs against a clean baseline. Use
        # `setdefault` defensively in case `hass.data[DOMAIN]` was
        # cleared between the suppress-branch entry and here.
        hass.data.setdefault(DOMAIN, {}).setdefault(
            "cm_last_applied_options", {},
        )[entry.entry_id] = dict(entry.options)

    # RELOAD-WATCHDOG-HAZARD (2026-08-15): mirror the CM suppress pattern
    # on the INTEGRATION (parent) entry. Root cause of the 2026-08-07
    # ~5-minute outage: a Camera Census save on this entry cascaded a
    # synchronous reload to ~40 child entries.
    #
    # NOTE on snapshot cleanup (plan LOW-4): `integration_last_applied_options`
    # is intentionally NOT cleaned on entry unload — the leak is one
    # dict per integration entry (there is exactly one), cleared at
    # integration teardown when `hass.data[DOMAIN]` is torn down. This
    # matches the CM branch's convention (`cm_last_applied_options`
    # write-only, see :6447 above). If a future cycle changes CM
    # cleanup, mirror it here.
    if entry_type == ENTRY_TYPE_INTEGRATION:
        snapshots = hass.data.setdefault(DOMAIN, {}).setdefault(
            "integration_last_applied_options", {},
        )
        old = snapshots.get(entry.entry_id, {})
        new = dict(entry.options)
        changed_keys = {
            k for k in (old.keys() | new.keys())
            if old.get(k) != new.get(k)
        }
        if not changed_keys:
            # Defensive no-op (matches CM branch shape).
            return
        # Kill-switch gate (plan LOW-1): skips BOTH suppress AND dispatch.
        # The fall-through reload rebuilds subscriptions naturally; a
        # parallel dispatch would double the work and confuse logs.
        if (INTEGRATION_RELOAD_SUPPRESS_ENABLED
                and changed_keys.issubset(INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS)):
            _LOGGER.info(
                "INTEGRATION options changed for '%s' (%s) — in-place "
                "apply, suppressing reload (changed_keys=%s)",
                entry.title, entry.entry_id, sorted(changed_keys),
            )
            _dispatch_integration_key_signals(hass, entry, changed_keys)
            # Snapshot advance: for v1 the apply-set equals the changed
            # set (dispatch-only, no live-attr push). Keep the CM-branch
            # shape for future cached-consumer additions.
            snapshots[entry.entry_id] = dict(new)
            return
        # Mixed or non-allowlisted change → reseed snapshot to the
        # post-write options BEFORE falling through to reload so a
        # second in-flight write during the reload diffs against a
        # clean baseline (mirrors CM branch B-HIGH-2 pattern).
        hass.data.setdefault(DOMAIN, {}).setdefault(
            "integration_last_applied_options", {},
        )[entry.entry_id] = dict(entry.options)

    _LOGGER.info("Options changed for '%s' (%s), scheduling reload", entry.title, entry.entry_id)
    # B-CRIT-1 (Review B, 2026-06-03): MUST be an UNTRACKED task. A
    # tracked task registered via `entry.async_create_background_task`
    # gets cancelled by `_async_process_on_unload` during the reload's
    # own unload phase (config_entries.py:1233-1234 iterates
    # `entry._background_tasks` and cancels each), aborting the
    # reload before its setup phase completes and leaving the entry
    # in NOT_LOADED. The standard HA-core pattern for self-reload
    # from inside a config entry is the untracked form below —
    # exemplars: plex, flux_led, tile, epson.
    hass.async_create_task(  # noqa: untracked-ok — self-reload must outlive entry unload; standard HA core pattern (plex, flux_led, tile, epson)
        hass.config_entries.async_reload(entry.entry_id),
    )
