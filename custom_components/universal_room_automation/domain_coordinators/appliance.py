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
- **NO device_id auto-collapse.** ``device_id`` is not a reliable
  appliance boundary — a single LG ThinQ washer registers as one device
  with many entities (control + energy + state), a 2-channel Shelly
  registers as one device with two independent appliances. Grouping
  across entity_ids is an operator decision (source-1 declared records
  in v1b), NEVER a heuristic. Source-3 emits **one record per unique
  unclaimed entity_id** (dedup by entity_id ONLY, no-drop invariant).
- Unmapped entity = visible, ``other`` / uncategorized, never dropped.
- Same-entity-in-two-records is a legal-config hole; v1a treats a duplicate
  as last-wins-with-removal (actually removes the entity_id from the
  earlier record — the v1b flow validator will reject-at-save).

v1a does NOT construct an ``AnomalyDetector`` (that lands in v1d, along
with the observability meta-test wiring). No gating on the Energy
integration's health.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import (
    CONF_APPLIANCE_RECORDS,
    CONF_ENTRY_TYPE,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_ROOM,
)
from ._units import power_state_to_w
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


# Boot-settle horizon: for the first N seconds after construct, refs with
# no last_updated / stale states are reported "unknown" rather than
# "stale" — a device off-WiFi since before restart shouldn't be labeled
# "stale" on the first census tick (consistent with other coordinators'
# boot-settle gates, e.g. hvac.py:515).
_APPLIANCE_BOOT_SETTLE_S: int = 60

# HA "not a live signal" state strings — excluded from counting toward
# ``seen_any`` in freshness (a stuck `unavailable` state is not proof of
# a fresh signal).
_NON_LIVE_STATES: frozenset[str] = frozenset({"unavailable", "unknown", "none", ""})


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
        # Boot-settle anchor. Monotonic so the gate is immune to wall-clock
        # jumps during startup.
        self._boot_monotonic = time.monotonic()

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
        # Base class handles listener cleanup (base.py:284).
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
        - Duplicate declared claims: last-wins with actual removal from
          the earlier record (v1b flow will reject-at-save).
        - Source (3): one record per unique unclaimed ``entity_id``.
          NO device_id auto-collapse — device_id is not a reliable
          appliance boundary (ThinQ washer = 1 device / many entities;
          2-channel Shelly = 1 device / 2 appliances).
        - Unclaimed entities from source (3) each become exactly one
          ``other``/uncategorized record (invariant #i: no-drop).
        """
        records: list[dict[str, Any]] = []
        # Map claimed entity_id -> the record dict it belongs to. Lets us
        # actually remove a duplicate from the earlier record when a
        # later declared record re-claims it (real "last-wins").
        claim_owner: dict[str, dict[str, Any]] = {}

        # Source (1): declared records — highest precedence.
        for rec in self._read_declared_records():
            try:
                augmented = self._augment_declared_record(rec)
            except Exception:  # noqa: BLE001 — one malformed record must
                # not blank the whole census. Skip it, log, keep going.
                _LOGGER.warning(
                    "Appliance census: skipping malformed declared record %r",
                    rec.get(KEY_NAME, "?") if isinstance(rec, dict) else "?",
                    exc_info=True,
                )
                continue
            # Record-local set — an entity legitimately appearing as
            # BOTH control and state of the SAME record must not warn.
            local_ids: set[str] = set()
            entity_refs = augmented.get(KEY_ENTITY_REFS) or {}
            for role in ROLES:
                for eid in entity_refs.get(role) or []:
                    if not eid:
                        continue
                    if eid in local_ids:
                        continue  # same record, different role — legal
                    local_ids.add(eid)
                    prior = claim_owner.get(eid)
                    if prior is not None and prior is not augmented:
                        # Real removal: strip the entity_id from the
                        # earlier record's every role list.
                        _LOGGER.warning(
                            "Appliance record %r claims entity_id %s already "
                            "claimed by earlier record %r; removing from "
                            "earlier record (v1b flow will reject-at-save)",
                            augmented.get(KEY_NAME, "?"), eid,
                            prior.get(KEY_NAME, "?"),
                        )
                        prior_refs = prior.get(KEY_ENTITY_REFS) or {}
                        for r_role in ROLES:
                            lst = prior_refs.get(r_role) or []
                            if eid in lst:
                                prior_refs[r_role] = [x for x in lst if x != eid]
                    claim_owner[eid] = augmented
            records.append(augmented)

        claimed_entity_ids: set[str] = set(claim_owner.keys())

        # Source (2): SPAN circuits.
        for span_rec in self._read_span_circuits(claimed_entity_ids):
            records.append(span_rec)

        # Source (3): URA-owned entities.
        # Dedup ONLY on entity_id. NO device_id auto-collapse — see
        # docstring.
        for entry in self._iter_ura_owned_appliance_entities(claimed_entity_ids):
            entity_id = entry["entity_id"]
            if entity_id in claimed_entity_ids:
                continue
            records.append(self._build_ura_owned_record(entry))
            claimed_entity_ids.add(entity_id)

        return records

    # ------------------------------------------------------------------
    # Source (1) — declared records
    # ------------------------------------------------------------------

    def _read_declared_records(self) -> list[dict[str, Any]]:
        """Read the operator-declared record list from the CM entry.

        Routes through the base class's cached CM-entry lookup
        (``base.py:267``) so we don't rescan config entries every tick.
        """
        try:
            # Poke the base cache — populates ``self._cm_entry_cache``.
            self._get_signal_config("__appliance_prime__", default=False)
            entry = self._cm_entry_cache
            if entry is None:
                return []
            merged = {**(entry.data or {}), **(entry.options or {})}
            declared = merged.get(CONF_APPLIANCE_RECORDS) or []
            if isinstance(declared, list):
                return [d for d in declared if isinstance(d, dict)]
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Appliance census: reading declared records failed",
                exc_info=True,
            )
        return []

    def _augment_declared_record(self, rec: dict[str, Any]) -> dict[str, Any]:
        """Attach current power/state/freshness to a declared record.

        May raise on badly-shaped input — the caller catches and skips.
        """
        entity_refs = rec.get(KEY_ENTITY_REFS) or {}
        power_w = self._sum_power_w(entity_refs.get(ROLE_POWER) or [])
        state_val = self._read_first_state(entity_refs.get(ROLE_STATE) or [])
        # Freshness — WORST (oldest) last_updated across ALL referenced
        # entity_ids; STALE if ANY is older than APPLIANCE_STALE_MAX_AGE_S.
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

        # Build a reverse-index from configured power_sensors → room name
        # (from ROOM entries) so a SPAN circuit that an operator has ALSO
        # configured as a room's power sensor picks up the room attribution.
        room_for_power_sensor = self._build_room_index_for_power_sensors()

        for entity_id, info in circuits.items():
            if entity_id in claimed_entity_ids:
                continue
            power_w = self._sum_power_w([entity_id])
            friendly = getattr(info, "friendly_name", entity_id)
            # TODO card: multi-room same power_sensor — current behavior
            # picks the FIRST room that references it. If the operator
            # legitimately shares a SPAN circuit across two rooms, that's
            # ambiguous and needs a design call (v1b territory).
            record = {
                KEY_NAME: friendly,
                KEY_FUNCTIONAL_DOMAIN: DOMAIN_OTHER,
                KEY_ROOM: room_for_power_sensor.get(entity_id),
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

    def _build_room_index_for_power_sensors(self) -> dict[str, str]:
        """Return {power_sensor_entity_id: first_room_name_that_references_it}."""
        idx: dict[str, str] = {}
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                merged = {**(entry.data or {}), **(entry.options or {})}
                if merged.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                    continue
                room_name = merged.get("room_name") or entry.title or ""
                val = merged.get("power_sensors")
                if not val:
                    continue
                ids: list[str] = []
                if isinstance(val, str):
                    ids = [val]
                elif isinstance(val, (list, tuple, set)):
                    ids = [str(v) for v in val if v]
                for eid in ids:
                    if eid and eid not in idx:
                        idx[eid] = room_name
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Appliance census: room-index for power_sensors build failed",
                exc_info=True,
            )
        return idx

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
        of dicts with ``entity_id``, ``room``, ``room_key``. No device_id
        dedup — each unclaimed entity_id yields at most one entry here.
        """
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        try:
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
                        out.append({
                            "entity_id": eid,
                            "room": room_name,
                            "room_key": key,
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
            power_w = self._sum_power_w([eid])
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

    def _sum_power_w(self, entity_ids: list[str]) -> float | None:
        """Return SUM of power readings across entity_ids in Watts, or None.

        Routes each read through ``power_state_to_w`` so a source
        reporting in kW / mW / MW normalizes to Watts (Bug Class #30).
        Sums across all refs so a 240V appliance with two SPAN legs
        reports the combined draw. Returns None if no ref parses.
        """
        total: float | None = None
        for eid in entity_ids:
            try:
                st = self.hass.states.get(eid)
                if st is None:
                    continue
                watts = power_state_to_w(st)
                if watts is None:
                    continue
                total = (total or 0.0) + watts
            except Exception:  # noqa: BLE001
                continue
        return total

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
        """Return 'fresh' | 'stale' | 'unknown' per APPLIANCE_STALE_MAX_AGE_S.

        - Uses the WORST (oldest) age across ALL refs — a record is
          stale if ANY ref is stale.
        - ``unavailable`` / ``unknown`` states do NOT count as a live
          signal (they don't set ``seen_any``).
        - During boot-settle (first ``_APPLIANCE_BOOT_SETTLE_S`` seconds
          after construct), a record with no live ref reports 'unknown'
          rather than 'stale' — a device off-WiFi since before restart
          shouldn't be flagged stale on the first tick.
        - Kill value: ``APPLIANCE_STALE_MAX_AGE_S <= 0`` disables
          freshness reporting entirely (every record with a live ref
          reports 'fresh').
        """
        try:
            from homeassistant.util import dt as dt_util
            now = dt_util.utcnow()
        except Exception:  # noqa: BLE001
            return "unknown"
        seen_live_signal = False
        worst_age_s: float | None = None
        try:
            for role in ROLES:
                for eid in entity_refs.get(role) or []:
                    if not eid:
                        continue
                    try:
                        st = self.hass.states.get(eid)
                        if st is None:
                            continue
                        raw = getattr(st, "state", None)
                        if isinstance(raw, str) and raw.strip().lower() in _NON_LIVE_STATES:
                            # Not a live signal — don't count for seen_any.
                            continue
                        seen_live_signal = True
                        lu = getattr(st, "last_updated", None)
                        if lu is None:
                            continue
                        age = (now - lu).total_seconds()
                        # WORST-age: track the maximum.
                        if worst_age_s is None or age > worst_age_s:
                            worst_age_s = age
                    except Exception:  # noqa: BLE001
                        continue
        except Exception:  # noqa: BLE001
            return "unknown"
        # Boot-settle: suppress stale during startup grace.
        if not seen_live_signal:
            if time.monotonic() - self._boot_monotonic < _APPLIANCE_BOOT_SETTLE_S:
                return "unknown"
            return "unknown"
        if APPLIANCE_STALE_MAX_AGE_S <= 0:
            return "fresh"  # kill-value
        if worst_age_s is None:
            return "unknown"
        return "fresh" if worst_age_s <= APPLIANCE_STALE_MAX_AGE_S else "stale"
