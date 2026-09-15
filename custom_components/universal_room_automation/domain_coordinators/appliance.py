"""Appliance Coordinator — v1a APPLIANCE-MGMT-REFINE-1 (passive census).

FIRST-CLASS, PASSIVE coordinator (peer of presence / safety / energy /
music-following, not a hidden helper). It observes; it commands NOTHING.

- ``evaluate()`` returns ``[]``. Appliance state changes never produce
  ``CoordinatorAction``.
- No ``hass.services.async_call`` from any code path — asserted by an
  invariant test (patch-and-assert-zero).
- No ``hass.states.async_set`` — invariant #ii.

v1a scope (this file):
- Passive lifecycle modeled on ``music_following.py`` (async_setup +
  evaluate→[] + async_teardown; tracked async_create_task set cancelled in
  teardown BEFORE any teardown persist).
- READ-ONLY appliance census unioned from three sources:
  1. SPAN circuits — read the *existing* ``SPANCircuitMonitor`` set on
     the Energy coordinator (registration order guarantees Energy is up
     first — see __init__.py registration site after :3567).
  2. Declared ``CONF_APPLIANCE_RECORDS`` on the CM entry options
     (default ``[]``; the writer flow lands in v1b).
  3. URA-owned entities discovered by a house-level iterator over every
     ROOM config entry, using the appliance-relevant room keys
     (``URA_ROOM_APPLIANCE_KEYS`` in ``appliance_const.py``). Modeled on
     ``presence.py:7567`` ``_collect_presence_input_entities``.
- Intra-integration shadow de-dup by ``device_id`` — reuses the pattern
  established by ``camera_census.py:589-628``. Cross-integration bridging
  is operator-declared only (fragile-pattern #2 in the plan).
- Unmapped entity = visible, ``other`` / uncategorized, never dropped.
- Same-entity-in-two-records is a legal-config hole; v1a treats a duplicate
  as last-wins-with-warning (v1b's flow validator will reject-at-save).

v1a does NOT construct an ``AnomalyDetector`` (that lands in v1d, along
with the observability meta-test wiring). No gating on the Energy
integration's health.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import (
    CONF_ENTRY_TYPE,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_ROOM,
)
from .base import BaseCoordinator, CoordinatorAction, Intent
from .appliance_const import (
    APPLIANCE_STALE_MAX_AGE_S,
    DOMAIN_OTHER,
    KEY_ENTITY_REFS,
    KEY_FUNCTIONAL_DOMAIN,
    KEY_NAME,
    KEY_ROOM,
    KEY_SOURCE_TAGS,
    ROLE_CONTROL,
    ROLE_ENERGY,
    ROLE_POWER,
    ROLE_STATE,
    ROLES,
    TAG_SPAN,
    TAG_URA_CONFIG,
    URA_ROOM_APPLIANCE_KEYS,
    URA_ROOM_KEY_TO_DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


# CM options key for operator-declared appliance record list. Read here in
# v1a; the writer (options-flow step + reload-suppression key) lands in
# v1b (per the plan's staging). Declared as a module constant on the
# coordinator so v1a owns its own surface without polluting const.py yet.
CONF_APPLIANCE_RECORDS = "appliance_records"


class ApplianceCoordinator(BaseCoordinator):
    """Passive appliance census. Peer coordinator; observes only."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            coordinator_id="appliance",
            name="Appliance",
            priority=25,
        )
        # Tracked task set — cancelled in async_teardown BEFORE anything else
        # (Fragile pattern #6: untracked async_create_task, v4.6.3 A5).
        self._pending_tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Passive setup — no listeners, no service calls, no state writes.

        v1a is intentionally quiet at setup: the census is resolved lazily
        on each read (see :meth:`resolve_census`). No gating on the
        Energy coordinator's health (fragile pattern #7) — a missing
        ``SPANCircuitMonitor`` collapses source (1) silently and the
        census still returns records from sources (2) and (3).
        """
        _LOGGER.info(
            "ApplianceCoordinator setup: passive census, priority=%d, "
            "stale_max_age_s=%d",
            self.priority,
            APPLIANCE_STALE_MAX_AGE_S,
        )

    async def evaluate(
        self,
        intents: list[Intent],
        context: dict[str, Any],
    ) -> list[CoordinatorAction]:
        """Passive — always empty. Invariant (ii): commands nothing.

        This must NEVER return a non-empty list. The census is a
        read-only surface for other consumers (dashboards, future v1d
        anomaly detection); it does not drive actions through the
        intent pipeline.
        """
        return []

    async def async_teardown(self) -> None:
        """Tear down — cancel tracked tasks first, then unhook listeners."""
        # Cancel-without-await (music_following.py:668-671 pattern).
        for task in list(self._pending_tasks):
            task.cancel()
        self._pending_tasks.clear()
        self._cancel_listeners()
        _LOGGER.info("ApplianceCoordinator torn down")

    # ------------------------------------------------------------------
    # Census resolver (v1a — read-only)
    # ------------------------------------------------------------------

    def resolve_census(self) -> list[dict[str, Any]]:
        """Return the current appliance census as a list of records.

        Union of three sources, in order:

        1. Declared ``CONF_APPLIANCE_RECORDS`` records (operator-authored
           on the CM entry).
        2. SPAN circuits — read the existing ``SPANCircuitMonitor``
           circuits on the Energy coordinator. NOT constructed here.
        3. URA-owned entities via the house iterator
           (:meth:`_iter_ura_owned_appliance_entities`).

        De-dup:
        - Every ``entity_id`` in a declared record is CLAIMED — sources
          (2) and (3) are suppressed for that entity (invariant #i:
          entity-exclusivity + group-completeness).
        - Intra-integration shadows collapse by ``device_id`` (pattern:
          ``camera_census.py:589-628``). Only within a single source.
        - Unclaimed entities from source (3) each become exactly one
          ``other``/uncategorized record (invariant #i: no-drop).
        """
        records: list[dict[str, Any]] = []
        claimed_entity_ids: set[str] = set()

        # Source (1): declared records — highest precedence.
        declared = self._read_declared_records()
        for rec in declared:
            entity_refs = rec.get(KEY_ENTITY_REFS) or {}
            for role in ROLES:
                for eid in entity_refs.get(role) or []:
                    if not eid:
                        continue
                    if eid in claimed_entity_ids:
                        # Last-wins-with-warning backstop (v1b flow will
                        # reject-at-save).
                        _LOGGER.warning(
                            "Appliance record %r references entity_id %s "
                            "already claimed by an earlier record; "
                            "last-wins backstop applied (v1b flow will "
                            "reject-at-save)",
                            rec.get(KEY_NAME, "?"),
                            eid,
                        )
                    claimed_entity_ids.add(eid)
            records.append(self._augment_declared_record(rec))

        # Source (2): SPAN circuits.
        for span_rec in self._read_span_circuits(claimed_entity_ids):
            records.append(span_rec)

        # Source (3): URA-owned entities.
        # Intra-integration shadow de-dup: within the URA source we
        # collapse entities on the same device_id (mirrors
        # camera_census.py:589-628 — a device with two representative
        # entities gets one record).
        seen_ura_device_ids: set[str] = set()
        for entry in self._iter_ura_owned_appliance_entities(claimed_entity_ids):
            entity_id = entry["entity_id"]
            device_id = entry.get("device_id")
            if device_id and device_id in seen_ura_device_ids:
                _LOGGER.debug(
                    "Appliance census: intra-integration shadow collapse — "
                    "%s shares device_id=%s with a previously seen URA-owned "
                    "entity; skipping",
                    entity_id, device_id,
                )
                continue
            if device_id:
                seen_ura_device_ids.add(device_id)
            records.append(self._build_ura_owned_record(entry))
            claimed_entity_ids.add(entity_id)

        return records

    # ------------------------------------------------------------------
    # Source (1) — declared records
    # ------------------------------------------------------------------

    def _read_declared_records(self) -> list[dict[str, Any]]:
        """Read the operator-declared record list from the CM entry."""
        try:
            for ce in self.hass.config_entries.async_entries(DOMAIN):
                if ce.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COORDINATOR_MANAGER:
                    continue
                merged = {**(ce.data or {}), **(ce.options or {})}
                declared = merged.get(CONF_APPLIANCE_RECORDS) or []
                if isinstance(declared, list):
                    return [d for d in declared if isinstance(d, dict)]
                return []
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Appliance census: reading declared records failed",
                exc_info=True,
            )
        return []

    def _augment_declared_record(self, rec: dict[str, Any]) -> dict[str, Any]:
        """Attach current power/state/freshness to a declared record."""
        entity_refs = rec.get(KEY_ENTITY_REFS) or {}
        power_w = self._read_first_float_state(entity_refs.get(ROLE_POWER) or [])
        state_val = self._read_first_state(entity_refs.get(ROLE_STATE) or [])
        # Freshness — most recent last_updated across ALL referenced
        # entity_ids; STALE if older than APPLIANCE_STALE_MAX_AGE_S.
        freshness = self._freshness_for_entity_refs(entity_refs)
        return {
            KEY_NAME: rec.get(KEY_NAME, "?"),
            KEY_FUNCTIONAL_DOMAIN: rec.get(KEY_FUNCTIONAL_DOMAIN, DOMAIN_OTHER),
            KEY_ROOM: rec.get(KEY_ROOM),
            KEY_ENTITY_REFS: {r: list(entity_refs.get(r) or []) for r in ROLES},
            KEY_SOURCE_TAGS: list(rec.get(KEY_SOURCE_TAGS) or []),
            "current_power_w": power_w,
            "current_state": state_val,
            "freshness": freshness,
        }

    # ------------------------------------------------------------------
    # Source (2) — SPAN circuits (read the existing monitor)
    # ------------------------------------------------------------------

    def _read_span_circuits(
        self, claimed_entity_ids: set[str],
    ) -> list[dict[str, Any]]:
        """Read circuits from the Energy coordinator's SPANCircuitMonitor.

        Registration order (see __init__.py, after :3567) guarantees
        Energy is registered BEFORE Appliance. If Energy is disabled or
        the monitor is missing (e.g. no SPAN panel), this source is
        silently empty — the coordinator does NOT gate on Energy health
        (fragile-pattern #7).
        """
        out: list[dict[str, Any]] = []
        monitor = self._get_span_monitor()
        if monitor is None:
            return out
        try:
            circuits = getattr(monitor, "_circuits", None) or {}
        except Exception:  # noqa: BLE001
            return out

        for entity_id, info in circuits.items():
            if entity_id in claimed_entity_ids:
                continue
            power_w = self._read_first_float_state([entity_id])
            friendly = getattr(info, "friendly_name", entity_id)
            record = {
                KEY_NAME: friendly,
                KEY_FUNCTIONAL_DOMAIN: DOMAIN_OTHER,
                KEY_ROOM: None,
                KEY_ENTITY_REFS: {
                    ROLE_POWER: [entity_id],
                    ROLE_ENERGY: [],
                    ROLE_CONTROL: [],
                    ROLE_STATE: [],
                },
                KEY_SOURCE_TAGS: [TAG_SPAN],
                "current_power_w": power_w,
                "current_state": None,
                "freshness": self._freshness_for_entity_refs(
                    {ROLE_POWER: [entity_id]}
                ),
            }
            out.append(record)
            claimed_entity_ids.add(entity_id)
        return out

    def _get_span_monitor(self) -> Any | None:
        """Return the Energy coordinator's SPANCircuitMonitor, or None."""
        try:
            cm = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if cm is None:
                return None
            energy = cm.coordinators.get("energy")
            if energy is None:
                return None
            return getattr(energy, "_circuits", None)
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # Source (3) — URA-owned entities across all ROOM entries
    # ------------------------------------------------------------------

    def _iter_ura_owned_appliance_entities(
        self, claimed_entity_ids: set[str],
    ) -> list[dict[str, Any]]:
        """Iterate every ROOM entry and yield URA-owned appliance entities.

        Modeled on ``presence.py:7567 _collect_presence_input_entities`` —
        a house-level iterator over ROOM config entries, unioning the
        appliance-relevant room-config keys.

        Skips any entity_id already claimed by source (1). Returns a list
        of dicts with ``entity_id``, ``room``, ``room_key``, ``device_id``.
        """
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        try:
            ent_reg = self._safe_entity_registry()
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                merged = {**(entry.data or {}), **(entry.options or {})}
                if merged.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                    continue
                room_name = merged.get("room_name") or entry.title or ""
                for key in URA_ROOM_APPLIANCE_KEYS:
                    val = merged.get(key)
                    if not val:
                        continue
                    entity_ids: list[str] = []
                    if isinstance(val, str):
                        entity_ids = [val]
                    elif isinstance(val, (list, tuple, set)):
                        entity_ids = [str(v) for v in val if v]
                    for eid in entity_ids:
                        if not eid or eid in seen or eid in claimed_entity_ids:
                            continue
                        seen.add(eid)
                        device_id = self._lookup_device_id(ent_reg, eid)
                        out.append({
                            "entity_id": eid,
                            "room": room_name,
                            "room_key": key,
                            "device_id": device_id,
                        })
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Appliance census: URA-owned entity iteration failed",
                exc_info=True,
            )
        return out

    def _build_ura_owned_record(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Build a census record for a URA-owned entity."""
        eid = entry["entity_id"]
        room_key = entry.get("room_key", "")
        functional_domain = URA_ROOM_KEY_TO_DOMAIN.get(room_key, DOMAIN_OTHER)
        # Role assignment by room-key: power_sensors -> power role;
        # everything else (fans/lights/covers/climate_entity/room_media_player)
        # -> state role (URA reads their live state; it does not command
        # them from here — v1a is passive).
        if room_key == "power_sensors":
            refs = {
                ROLE_POWER: [eid], ROLE_ENERGY: [],
                ROLE_CONTROL: [], ROLE_STATE: [],
            }
            power_w = self._read_first_float_state([eid])
            state_val = None
        else:
            refs = {
                ROLE_POWER: [], ROLE_ENERGY: [],
                ROLE_CONTROL: [], ROLE_STATE: [eid],
            }
            power_w = None
            state_val = self._read_first_state([eid])
        return {
            KEY_NAME: eid,
            KEY_FUNCTIONAL_DOMAIN: functional_domain,
            KEY_ROOM: entry.get("room"),
            KEY_ENTITY_REFS: refs,
            KEY_SOURCE_TAGS: [TAG_URA_CONFIG],
            "current_power_w": power_w,
            "current_state": state_val,
            "freshness": self._freshness_for_entity_refs(refs),
        }

    # ------------------------------------------------------------------
    # Small read helpers — all guarded per CLAUDE.md rule 4.
    # ------------------------------------------------------------------

    def _safe_entity_registry(self):
        try:
            from homeassistant.helpers import entity_registry as er
            return er.async_get(self.hass)
        except Exception:  # noqa: BLE001
            return None

    def _lookup_device_id(self, ent_reg, entity_id: str) -> str | None:
        if ent_reg is None:
            return None
        try:
            entry = ent_reg.async_get(entity_id)
            if entry is None:
                return None
            return getattr(entry, "device_id", None)
        except Exception:  # noqa: BLE001
            return None

    def _read_first_float_state(self, entity_ids: list[str]) -> float | None:
        for eid in entity_ids:
            try:
                st = self.hass.states.get(eid)
                if st is None:
                    continue
                return float(st.state)
            except Exception:  # noqa: BLE001
                continue
        return None

    def _read_first_state(self, entity_ids: list[str]) -> str | None:
        for eid in entity_ids:
            try:
                st = self.hass.states.get(eid)
                if st is None:
                    continue
                return str(st.state)
            except Exception:  # noqa: BLE001
                continue
        return None

    def _freshness_for_entity_refs(
        self, entity_refs: dict[str, list[str]],
    ) -> str:
        """Return 'fresh' | 'stale' | 'unknown' per APPLIANCE_STALE_MAX_AGE_S."""
        try:
            from homeassistant.util import dt as dt_util
            now = dt_util.utcnow()
        except Exception:  # noqa: BLE001
            return "unknown"
        seen_any = False
        oldest_age_s: float | None = None
        try:
            for role in ROLES:
                for eid in entity_refs.get(role) or []:
                    if not eid:
                        continue
                    try:
                        st = self.hass.states.get(eid)
                        if st is None:
                            continue
                        seen_any = True
                        lu = getattr(st, "last_updated", None)
                        if lu is None:
                            continue
                        age = (now - lu).total_seconds()
                        if oldest_age_s is None or age < oldest_age_s:
                            oldest_age_s = age
                    except Exception:  # noqa: BLE001
                        continue
        except Exception:  # noqa: BLE001
            return "unknown"
        if not seen_any:
            return "unknown"
        if APPLIANCE_STALE_MAX_AGE_S <= 0:
            return "fresh"  # kill-value
        if oldest_age_s is None:
            return "unknown"
        return "fresh" if oldest_age_s <= APPLIANCE_STALE_MAX_AGE_S else "stale"

    # ------------------------------------------------------------------
    # BaseCoordinator hook
    # ------------------------------------------------------------------

    def _cancel_listeners(self) -> None:
        """No listeners in v1a — override the base helper if it exists."""
        for unsub in list(getattr(self, "_unsub_listeners", []) or []):
            try:
                unsub()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "ApplianceCoordinator: listener unsub failed (non-fatal)",
                    exc_info=True,
                )
        if hasattr(self, "_unsub_listeners"):
            self._unsub_listeners = []
