"""Person sightings (FACE-ARRIVAL-REBUILD-1 D1 + D4; plan
``docs/planning/PLANNING_person_sighting_layer.md`` rev 11 §3.1-§3.2, §3.5).

A sighting is "person P was seen at place X at time T, by evidence of
provenance V, with confidence C". This module owns the ONE producer and its
ONE emit function. Three sources funnel into it:

  (a) the census Frigate MQTT face bridge (one callback per message, after the
      latch write; registered in ``hass.data[DOMAIN]["face_latch_callbacks"]``);
  (b) face-NAME sensor state changes on the cameras the operator picked per
      house zone (``zone_cameras`` on the Zone Manager entry), resolved
      pick -> physical camera -> every integration's face sensor through
      ``CameraResolver.resolve_pick_to_fusions`` (never string-built);
  (c) ``ura_person_egress_event`` crossings whose identity has a FACE
      provenance (``identity_provenance`` in face / ble+face). A crossing is
      PROJECTED, never re-decided; exit backfills are not sightings.

Producer filters are about evidence quality only (INV-PRODUCER): face
suppression, sentinel names, the boot drop (``ts < presence setup +
PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S``, all three sources), an unmapped
name, a non-face egress provenance. Nothing here reads a consumer's identity
or action class. Sightings feed no census, no house-state inference, no NM;
access consumers must never act on one alone (INV-ACCESS).

Debounce: key ``(slug, physical_camera)`` across all sources, a FIXED window
of ``FACE_SIGHTING_DEBOUNCE_S`` from the first emit (duplicates never extend
it). A later copy inside the window never re-emits; it may only upgrade the
last-sighting store (non-synthetic replaces synthetic, ``ts`` kept).
"""

from __future__ import annotations

import logging
import time
from collections import Counter, deque
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Callable

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from . import const as _c
from .camera_resolver import canonical_camera_key
from .domain_coordinators._stuck_signal_nm import fire_stuck_signal
from .domain_coordinators.hvac_const import CONF_ZONE_CAMERAS
from .domain_coordinators.signals import SIGNAL_PERSON_SIGHTING

_LOGGER = logging.getLogger(__name__)

SIGHTING_SOURCE_INTERIOR = "interior_pick"
SIGHTING_SOURCE_EGRESS_ENTRY = "egress_entry"
SIGHTING_SOURCE_EGRESS_EXIT = "egress_exit"
EGRESS_EVENT = "ura_person_egress_event"
_SENTINELS = frozenset({"", "unknown", "none", "unavailable", "no_match"})
_UNREADY = frozenset({"unavailable", "unknown"})
# Interior recent-emit ring (trip-wire numerator); bounded by construction.
_EMIT_RING_MAX = 4096


@dataclass(frozen=True)
class PersonSighting:
    """Payload of ``SIGNAL_PERSON_SIGHTING`` (plan rev 11 §3.1)."""

    person_entity: str
    slug: str
    face_name: str | None
    camera: str
    physical_camera: str
    person_state_at_emit: str | None
    census_would_veto: bool
    area_id: str | None
    room: str | None
    house_zones: tuple[str, ...]
    ts: float
    confidence: float
    provenance: str
    sighting_source: str
    identity_role: str | None
    synthetic: bool
    person_edge_age_s: float | None


@dataclass
class _PhysicalView:
    """Everything one resolved physical camera contributes."""

    key: str
    picks: list[str] = field(default_factory=list)
    zones: set[str] = field(default_factory=set)
    room: str | None = None
    area_id: str | None = None
    face_entities: set[str] = field(default_factory=set)
    person_sensors: set[str] = field(default_factory=set)


class PersonSightingProducer:
    """The one person-sighting producer (presence owns the instance)."""

    def __init__(
        self,
        hass: Any,
        presence: Any,
        *,
        now_fn: Callable[[], float] = time.time,
        arrival_rule: Callable[[PersonSighting], None] | None = None,
    ) -> None:
        self.hass = hass
        self._presence = presence
        self._now = now_fn
        self._arrival_rule = arrival_rule
        self._setup_ts: float | None = None
        self._unsubs: list[Callable[[], None]] = []
        self._face_unsub: Callable[[], None] | None = None
        self._started_unsub: Callable[[], None] | None = None
        self._bridge_cb: Callable | None = None
        self._bound_resolver: Any = None
        self._bound_picks: dict[str, tuple[str, ...]] = {}
        self._views: dict[str, _PhysicalView] = {}
        self._face_to_physical: dict[str, str] = {}
        self._resolved: dict[str, str] = {}     # pick -> physical key(s) joined
        self._unresolved: dict[str, str] = {}   # pick -> reason
        self._egress_keys: dict[str, str] = {}
        self._last_retry_ts = 0.0
        self._last_sightings: dict[str, PersonSighting] = {}
        self._last_sighting: PersonSighting | None = None
        self._interior_emits: deque = deque(maxlen=_EMIT_RING_MAX)
        self.counters: Counter = Counter()
        self.by_source: Counter = Counter()
        self.skips_by_reason: Counter = Counter()
        self.arrivals_derived_today = 0
        self._zero_latched = False
        self._arrival_zero_latched = False
        self._last_arrival_ts: float | None = None
        self.enabled = bool(_c.FACE_SIGHTING_ENABLED)

    # ------------------------------------------------------------------ setup
    def async_setup(self) -> None:
        """Bind picks and register every listener. INV-NOOP: with
        FACE_SIGHTING_ENABLED False nothing is registered."""
        self._setup_ts = self._now()
        if not self.enabled:
            return
        dom = self.hass.data.setdefault(_c.DOMAIN, {})
        self._bridge_cb = self._on_bridge
        dom.setdefault("face_latch_callbacks", []).append(self._bridge_cb)
        try:
            self._unsubs.append(
                self.hass.bus.async_listen(EGRESS_EVENT, self._on_egress_event)
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("person sightings: egress listener failed", exc_info=True)
        if not bool(getattr(self.hass, "is_running", False)):
            try:
                from homeassistant.const import EVENT_HOMEASSISTANT_STARTED  # noqa: PLC0415
            except Exception:  # noqa: BLE001
                EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"
            try:
                self._started_unsub = self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED, self._on_ha_started,
                )
            except Exception:  # noqa: BLE001
                self._started_unsub = None
        self.rebind()
        _LOGGER.info(
            "Face sighting: %d/%d picks resolved, %d egress cameras",
            len(self._resolved), len(self._resolved) + len(self._unresolved),
            len(self._egress_camera_ids()),
        )

    @callback
    def _on_ha_started(self, _event: Any = None) -> None:
        self._started_unsub = None
        self.rebind()

    def async_teardown(self) -> None:
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._unsubs.clear()
        if self._face_unsub is not None:
            try:
                self._face_unsub()
            except Exception:  # noqa: BLE001
                pass
            self._face_unsub = None
        if self._started_unsub is not None:
            try:
                self._started_unsub()
            except Exception:  # noqa: BLE001
                pass
            self._started_unsub = None
        try:
            lst = self.hass.data.get(_c.DOMAIN, {}).get("face_latch_callbacks")
            if lst is not None and self._bridge_cb in lst:
                lst.remove(self._bridge_cb)
        except Exception:  # noqa: BLE001
            pass
        self._bridge_cb = None
        self._views.clear()
        self._face_to_physical.clear()
        self._last_sightings.clear()
        self._last_sighting = None
        self.enabled = False

    # --------------------------------------------------------------- binding
    def _census(self) -> Any:
        return self.hass.data.get(_c.DOMAIN, {}).get("census")

    def _resolver(self) -> Any:
        cm = self.hass.data.get(_c.DOMAIN, {}).get("camera_manager")
        getter = getattr(cm, "_get_resolver", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("person sightings: resolver unavailable", exc_info=True)
            return None

    def _read_picks(self) -> dict[str, tuple[str, ...]]:
        """pick -> sorted house zones whose ``zone_cameras`` include it."""
        out: dict[str, set[str]] = {}
        try:
            entries = self.hass.config_entries.async_entries(_c.DOMAIN)
        except Exception:  # noqa: BLE001
            return {}
        for entry in entries:
            data = getattr(entry, "data", {}) or {}
            if data.get(_c.CONF_ENTRY_TYPE) != _c.ENTRY_TYPE_ZONE_MANAGER:
                continue
            opts = getattr(entry, "options", {}) or {}
            zones = opts.get("zones") or data.get("zones") or {}
            for zname, zcfg in zones.items():
                for pick in (zcfg or {}).get(CONF_ZONE_CAMERAS) or []:
                    if isinstance(pick, str) and pick:
                        out.setdefault(pick, set()).add(str(zname))
        return {p: tuple(sorted(z)) for p, z in out.items()}

    def _room_cameras_lookup(self, entry_id: str) -> list[str] | None:
        try:
            entry = self.hass.config_entries.async_get_entry(entry_id)
        except Exception:  # noqa: BLE001
            entry = None
        if entry is None:
            return None
        merged = {**(getattr(entry, "data", {}) or {}), **(getattr(entry, "options", {}) or {})}
        if merged.get(_c.CONF_ENTRY_TYPE) != _c.ENTRY_TYPE_ROOM:
            return None
        cams = merged.get(_c.CONF_ROOM_CAMERAS) or []
        return [c for c in cams if isinstance(c, str)]

    def _room_name_of_entry(self, entry_id: str | None) -> str | None:
        if not entry_id:
            return None
        try:
            entry = self.hass.config_entries.async_get_entry(entry_id)
        except Exception:  # noqa: BLE001
            return None
        if entry is None:
            return None
        return (getattr(entry, "data", {}) or {}).get(_c.CONF_ROOM_NAME) or None

    def _room_for_area(self, area_id: str | None) -> str | None:
        if not area_id:
            return None
        rooms = sorted(
            r for r, a in (getattr(self._presence, "_room_area_ids", {}) or {}).items()
            if a == area_id
        )
        return rooms[0] if rooms else None

    def rebind(self, *, only: list[str] | None = None) -> None:
        """(Re)build the pick bindings. ``only`` = add-only retry of those
        picks; None = full rebuild (registry change, HA started, picks
        changed). Re-subscribes source (b) to the bound face entities."""
        if not self.enabled:
            return
        resolver = self._resolver()
        picks = self._read_picks()
        if only is None:
            self._views = {}
            self._face_to_physical = {}
            self._resolved = {}
            self._unresolved = {}
            self._egress_keys = {}
            targets = list(picks)
        else:
            targets = [p for p in only if p in picks]
        self._bound_resolver = resolver
        self._bound_picks = picks
        for pick in targets:
            self._bind_pick(resolver, pick, picks.get(pick, ()))
        self._resubscribe_faces()

    def _bind_pick(self, resolver: Any, pick: str, zones: tuple[str, ...]) -> None:
        if resolver is None or not callable(getattr(resolver, "resolve_pick_to_fusions", None)):
            self._unresolved[pick] = "no_fusion"
            return
        try:
            fusions, reason, owner = resolver.resolve_pick_to_fusions(
                pick, self._room_cameras_lookup,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("person sightings: resolve %s failed", pick, exc_info=True)
            fusions, reason, owner = [], "no_fusion", None
        if not fusions:
            self._unresolved[pick] = reason or "no_fusion"
            self._resolved.pop(pick, None)
            return
        if owner is not None:
            room = self._room_name_of_entry(owner)
            area = None
            try:
                room_entry = self.hass.config_entries.async_get_entry(owner)
                merged = {**(room_entry.data or {}), **(room_entry.options or {})}
                area = merged.get(_c.CONF_AREA_ID) or None
            except Exception:  # noqa: BLE001
                area = None
        else:
            area = None
            try:
                area = resolver.area_id_for_entity(pick)
            except Exception:  # noqa: BLE001
                area = None
            room = self._room_for_area(area)
        any_face = False
        keys: list[str] = []
        for fusion in fusions:
            key = canonical_camera_key(fusion)
            view = self._views.setdefault(key, _PhysicalView(key=key))
            if pick not in view.picks:
                view.picks.append(pick)
                view.picks.sort()
            view.zones.update(zones)
            if view.room is None:
                view.room, view.area_id = room, area
            for src in fusion.sources:
                if src.person_binary_sensor:
                    view.person_sensors.add(src.person_binary_sensor)
                for face in resolver.face_name_entities_for_device(src.device_id) or ():
                    view.face_entities.add(face)
                    self._face_to_physical[face] = key
                    any_face = True
            keys.append(key)
        if not any_face:
            self._unresolved[pick] = "no_face_name_source"
            self._resolved.pop(pick, None)
            return
        self._unresolved.pop(pick, None)
        self._resolved[pick] = ",".join(sorted(keys))

    def _resubscribe_faces(self) -> None:
        if self._face_unsub is not None:
            try:
                self._face_unsub()
            except Exception:  # noqa: BLE001
                pass
            self._face_unsub = None
        entities = sorted(self._face_to_physical)
        if not entities:
            return
        self._face_unsub = async_track_state_change_event(
            self.hass, entities, self._on_face_state,
        )

    def _maybe_rebind(self) -> None:
        """Re-resolution triggers 1 and 3: a rebuilt resolver (registry
        update) or a changed pick set -> full rebuild."""
        resolver = self._resolver()
        if resolver is not self._bound_resolver or self._read_picks() != self._bound_picks:
            self.rebind()

    def on_tick(self, now: float | None = None) -> None:
        """Presence's periodic tick: re-resolution triggers 1/3/4 and the D4
        trip-wires."""
        if not self.enabled:
            return
        now = self._now() if now is None else now
        try:
            self._maybe_rebind()
            period = float(_c.FACE_SIGHTING_PICK_RERESOLVE_S)
            if self._unresolved and period > 0 and now - self._last_retry_ts >= period:
                self._last_retry_ts = now
                self.rebind(only=sorted(self._unresolved))
        except Exception:  # noqa: BLE001
            _LOGGER.debug("person sightings: rebind tick failed", exc_info=True)
        self.check_tripwires(now)

    # --------------------------------------------------------------- sources
    @callback
    def _on_bridge(self, camname: str, stems: frozenset, name: str, now: datetime) -> None:
        """Source (a): one census MQTT face message."""
        if not self.enabled:
            return
        self._maybe_rebind()
        resolver = self._bound_resolver
        keys: set[str] = set()
        for stem in stems or ():
            try:
                faces = resolver.face_name_entities_for_stem(stem) if resolver else []
            except Exception:  # noqa: BLE001
                faces = []
            for face in faces or ():
                key = self._face_to_physical.get(face)
                if key is not None:
                    keys.add(key)
        if not keys:
            return
        if len(keys) > 1:
            self.counters["multi_pick_messages"] += 1
        ts = now.timestamp() if isinstance(now, datetime) else float(now)
        for key in sorted(keys):
            self._emit_interior(key, name, ts, synthetic=True)

    @callback
    def _on_face_state(self, event: Any) -> None:
        """Source (b): a face-name sensor changed to a real name."""
        if not self.enabled:
            return
        data = getattr(event, "data", {}) or {}
        new_state = data.get("new_state")
        old_state = data.get("old_state")
        if new_state is None:
            return
        # H2: a restore / unavailable -> name edge is not a recognition. HA's
        # own `unknown` / `unavailable` (case-sensitive: Frigate's "no match"
        # name is `Unknown`, and `Unknown` -> name IS a recognition).
        if old_state is None or getattr(old_state, "state", None) in _UNREADY:
            self.counters["restore_dropped"] += 1
            return
        # A3: an attribute-only update (same state) is not a new recognition;
        # its last_changed is the ORIGINAL recognition time.
        if getattr(old_state, "state", None) == getattr(new_state, "state", None):
            return
        entity_id = data.get("entity_id") or getattr(new_state, "entity_id", "")
        key = self._face_to_physical.get(entity_id)
        if key is None:
            return
        lc = getattr(new_state, "last_changed", None)
        ts = lc.timestamp() if isinstance(lc, datetime) else self._now()
        self._emit_interior(key, str(new_state.state), ts, synthetic=False)

    @callback
    def _on_egress_event(self, event: Any) -> None:
        """Source (c): a named face-provenance egress crossing."""
        if not self.enabled:
            return
        data = getattr(event, "data", {}) or {}
        person_id = data.get("person_id")
        direction = data.get("direction")
        if not person_id or direction not in ("entry", "exit"):
            return
        provenance = data.get("identity_provenance")
        if provenance not in (_c.IDENTITY_PROVENANCE_FACE, _c.IDENTITY_PROVENANCE_BLE_FACE):
            self.counters["egress_non_face_skipped"] += 1
            return
        cam = str(data.get("egress_camera") or "")
        ts_raw = data.get("timestamp")
        parsed = dt_util.parse_datetime(ts_raw) if isinstance(ts_raw, str) else None
        ts = parsed.timestamp() if parsed is not None else self._now()
        key = self._egress_key(cam)
        area = None
        resolver = self._bound_resolver or self._resolver()
        try:
            area = resolver.area_id_for_entity(cam) if resolver else None
        except Exception:  # noqa: BLE001
            area = None
        room = self._room_for_area(area)
        zone = None
        try:
            zone = self._presence.get_room_zone(room) if room else None
        except Exception:  # noqa: BLE001
            zone = None
        self._emit(
            slug=str(person_id), face_name=None, camera=cam, physical_camera=key,
            area_id=area, room=room, house_zones=(zone,) if zone else (), ts=ts,
            confidence=float(
                _c.CONFIDENCE_MEDIUM if data.get("identity_confidence") is None
                else data.get("identity_confidence")
            ),
            provenance=str(provenance),
            sighting_source=(
                SIGHTING_SOURCE_EGRESS_ENTRY if direction == "entry"
                else SIGHTING_SOURCE_EGRESS_EXIT
            ),
            identity_role="attached",
            synthetic=bool(data.get("identity_synthetic_corroborated", False)),
            person_edge_age_s=None,
            name_is_slug=True,
        )

    def _egress_key(self, cam: str) -> str:
        if cam in self._egress_keys:
            return self._egress_keys[cam]
        key = cam
        resolver = self._bound_resolver or self._resolver()
        try:
            fusions = resolver.resolve_operator_declaration([cam]) if resolver else []
            if fusions:
                key = canonical_camera_key(fusions[0])
        except Exception:  # noqa: BLE001
            key = cam
        self._egress_keys[cam] = key
        return key

    def _egress_camera_ids(self) -> list[str]:
        try:
            for entry in self.hass.config_entries.async_entries(_c.DOMAIN):
                data = getattr(entry, "data", {}) or {}
                if data.get(_c.CONF_ENTRY_TYPE) == _c.ENTRY_TYPE_INTEGRATION:
                    merged = {**data, **(getattr(entry, "options", {}) or {})}
                    return list(merged.get(_c.CONF_EGRESS_CAMERAS) or [])
        except Exception:  # noqa: BLE001
            pass
        return []

    def _face_recognition_on(self) -> bool:
        """The operator's Face Recognition switch (presence
        ``_face_recognition_enabled``, kept current by its
        SIGNAL_URA_FACE_RECOGNITION_CHANGED handler). OFF = no interior face
        sighting (so no camera_face arrival) and no zone last-face display,
        as develop's v3.19 path was gated."""
        return bool(getattr(self._presence, "_face_recognition_enabled", False))

    def _emit_interior(self, key: str, name: str, ts: float, *, synthetic: bool) -> None:
        view = self._views.get(key)
        if view is None:
            return
        if not self._face_recognition_on():
            self.counters["face_recognition_off"] += 1
            return
        self._emit(
            slug=name, face_name=name, camera=view.picks[0] if view.picks else key,
            physical_camera=key, area_id=view.area_id, room=view.room,
            house_zones=tuple(sorted(view.zones)), ts=ts,
            confidence=float(_c.CONFIDENCE_MEDIUM),
            provenance=_c.IDENTITY_PROVENANCE_FACE,
            sighting_source=SIGHTING_SOURCE_INTERIOR, identity_role=None,
            synthetic=synthetic, person_edge_age_s=self._edge_age(view, ts),
            name_is_slug=False,
        )

    def _edge_age(self, view: _PhysicalView, ts: float) -> float | None:
        latest_off: float | None = None
        for eid in view.person_sensors:
            st = self.hass.states.get(eid)
            if st is None:
                continue
            if st.state == "on":
                return 0.0
            lc = getattr(st, "last_changed", None)
            if isinstance(lc, datetime):
                t = lc.timestamp()
                latest_off = t if latest_off is None else max(latest_off, t)
        if latest_off is None:
            return None
        return max(0.0, round(ts - latest_off, 1))

    # ------------------------------------------------------------------ emit
    def _emit(
        self, *, slug: str, face_name: str | None, camera: str, physical_camera: str,
        area_id: str | None, room: str | None, house_zones: tuple[str, ...], ts: float,
        confidence: float, provenance: str, sighting_source: str,
        identity_role: str | None, synthetic: bool, person_edge_age_s: float | None,
        name_is_slug: bool,
    ) -> PersonSighting | None:
        """THE one emit function (all three sources)."""
        census = self._census()
        # Face suppression (central checkpoint, camera_census
        # `_face_suppressed_now`: every face-emission site gates on it).
        try:
            if census is not None and census._face_suppressed_now():
                self.counters["suppressed"] += 1
                return None
        except Exception:  # noqa: BLE001
            pass
        if not name_is_slug and str(slug).strip().lower() in _SENTINELS:
            self.counters["sentinel_dropped"] += 1
            return None
        boot_end = (self._setup_ts or 0.0) + float(_c.PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S)
        if ts < boot_end:
            self.counters["boot_dropped"] += 1
            return None
        # ONE mapper: the census `_canonical_person_slug`; mapped = member of
        # the tracked slugs (the mapper passes unknown names through).
        if census is None:
            self.counters["unmapped_names"] += 1
            return None
        try:
            mapped = slug if name_is_slug else census._canonical_person_slug(slug)
            tracked = set(census._get_tracked_person_slugs())
        except Exception:  # noqa: BLE001
            mapped, tracked = "", set()
        if isinstance(mapped, str) and mapped.startswith("guest:"):
            self.counters["guest_names"] += 1
            return None
        if not mapped or mapped not in tracked:
            self.counters["unmapped_names"] += 1
            return None
        person_entity = f"person.{mapped}"
        # Fixed-window dedup per (slug, physical camera), across sources.
        debounce = float(_c.FACE_SIGHTING_DEBOUNCE_S)
        store = getattr(self._presence, "_face_arrival_cooldown", None)
        if store is None:
            store = {}
        dkey = ("sighting", mapped, physical_camera)
        start = store.get(dkey)
        if debounce > 0 and isinstance(start, (int, float)) and ts < start + debounce:
            self.counters["debounced"] += 1
            last = self._last_sightings.get(person_entity)
            if (last is not None and last.physical_camera == physical_camera
                    and last.synthetic and not synthetic):
                upgraded = replace(last, synthetic=False)
                self._last_sightings[person_entity] = upgraded
                if self._last_sighting is last:
                    self._last_sighting = upgraded
            return None
        store[dkey] = ts
        try:
            pstate = self.hass.states.get(person_entity)
            person_state = getattr(pstate, "state", None) if pstate is not None else None
        except Exception:  # noqa: BLE001
            person_state = None
        try:
            would_veto = bool(census.face_person_would_be_vetoed(mapped))
        except Exception:  # noqa: BLE001
            would_veto = False
        sighting = PersonSighting(
            person_entity=person_entity, slug=mapped, face_name=face_name,
            camera=camera, physical_camera=physical_camera,
            person_state_at_emit=person_state, census_would_veto=would_veto,
            area_id=area_id, room=room, house_zones=tuple(house_zones), ts=float(ts),
            confidence=float(confidence), provenance=provenance,
            sighting_source=sighting_source, identity_role=identity_role,
            synthetic=bool(synthetic), person_edge_age_s=person_edge_age_s,
        )
        self._last_sightings[person_entity] = sighting
        self._last_sighting = sighting
        self.counters["sightings_today"] += 1
        self.by_source[sighting_source] += 1
        if sighting_source == SIGHTING_SOURCE_INTERIOR:
            self._interior_emits.append(ts)
        self._update_tracker_fields(sighting)
        async_dispatcher_send(self.hass, SIGNAL_PERSON_SIGHTING, sighting)
        if self._arrival_rule is not None:
            try:
                self._arrival_rule(sighting)
            except Exception:  # noqa: BLE001
                _LOGGER.warning("person sightings: arrival rule raised", exc_info=True)
        return sighting

    def _update_tracker_fields(self, sighting: PersonSighting) -> None:
        if not self._face_recognition_on():
            return
        trackers = getattr(self._presence, "_zone_trackers", {}) or {}
        when = dt_util.utc_from_timestamp(sighting.ts)
        for zone in sighting.house_zones:
            tracker = trackers.get(zone)
            if tracker is None:
                continue
            tracker._last_face_recognized = sighting.slug
            tracker._last_face_time = when

    # --------------------------------------------------------------- readers
    def get_last(self, person_entity: str) -> PersonSighting | None:
        return self._last_sightings.get(person_entity)

    def get_all_last(self) -> dict[str, PersonSighting]:
        return dict(self._last_sightings)

    def note_arrival(self, ts: float) -> None:
        """Called by the D2 rule after a dispatch (trip-wire re-arm)."""
        self.arrivals_derived_today += 1
        self._last_arrival_ts = ts
        self._arrival_zero_latched = False

    def reset_daily(self) -> None:
        self.counters["sightings_today"] = 0
        self.by_source.clear()
        self.arrivals_derived_today = 0

    def diagnostics(self) -> dict[str, Any]:
        last = self._last_sighting
        return {
            "face_sightings_today": int(self.counters.get("sightings_today", 0)),
            "face_sightings_by_source": dict(self.by_source),
            "face_arrivals_derived_today": int(self.arrivals_derived_today),
            "face_arrival_skips_by_reason": dict(self.skips_by_reason),
            "face_sighting_last": (
                {"slug": last.slug, "camera": last.camera, "room": last.room,
                 "ts": dt_util.utc_from_timestamp(last.ts).isoformat()}
                if last is not None else None
            ),
            "face_sighting_unmapped_names": int(self.counters.get("unmapped_names", 0)),
            "egress_non_face_skipped": int(self.counters.get("egress_non_face_skipped", 0)),
            "multi_pick_messages": int(self.counters.get("multi_pick_messages", 0)),
            "face_sighting_picks_resolved": sorted(self._resolved),
            "face_sighting_picks_unresolved": dict(sorted(self._unresolved.items())),
        }

    # ------------------------------------------------------------ trip-wires
    def _denominator(self, now: float, window_s: float) -> int:
        census = self._census()
        ring = getattr(census, "_frigate_face_named_ring", None) if census is not None else None
        if not ring:
            return 0
        try:
            tracked = set(census._get_tracked_person_slugs())
        except Exception:  # noqa: BLE001
            return 0
        resolver = self._bound_resolver
        # A1: count only faces the producer could have turned into a
        # sighting: inside the window AND after this producer's boot drop
        # (a restart or a presence re-setup; the census ring survives both).
        cutoff = max(
            now - window_s,
            (self._setup_ts or 0.0) + float(_c.PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S),
        )
        n = 0
        for entry in list(ring):
            t, _cam, stems, name, suppressed = entry
            if t < cutoff or suppressed:
                continue
            try:
                slug = census._canonical_person_slug(name)
            except Exception:  # noqa: BLE001
                continue
            if slug not in tracked:
                continue
            joined = False
            for stem in stems or ():
                try:
                    faces = resolver.face_name_entities_for_stem(stem) if resolver else []
                except Exception:  # noqa: BLE001
                    faces = []
                if any(f in self._face_to_physical for f in faces or ()):
                    joined = True
                    break
            if joined:
                n += 1
        return n

    def check_tripwires(self, now: float | None = None) -> None:
        """D4 (plan §3.5). `face_sighting_zero` (HIGH): mapped resident faces
        on picked cameras >= FACE_SIGHTING_ZERO_MIN_FACES in the trailing
        window and zero interior sightings -> one page (RAM latch, re-armed
        when sightings resume). `face_arrival_zero` (LOW): armed only while
        FACE_ARRIVAL_INTERIOR_ENABLED."""
        if not self.enabled:
            return
        now = self._now() if now is None else now
        window_h = float(_c.FACE_SIGHTING_ZERO_WINDOW_H)
        # A2: switch OFF = no sightings expected; nothing to page.
        if window_h > 0 and self._face_recognition_on():
            window_s = window_h * 3600.0
            numerator = sum(1 for t in self._interior_emits if t >= now - window_s)
            if numerator > 0:
                self._zero_latched = False
            elif not self._zero_latched:
                denom = self._denominator(now, window_s)
                if denom >= int(_c.FACE_SIGHTING_ZERO_MIN_FACES):
                    self._zero_latched = True
                    self._fire(
                        "face_sighting_zero",
                        f"{denom} recognised resident faces on picked cameras in "
                        f"{window_h:g} h but 0 person sightings",
                        "Check the person-sighting producer (presence) and the "
                        "zone camera picks; sightings should follow faces.",
                        "HIGH",
                    )
        days = float(_c.FACE_ARRIVAL_ZERO_DAYS)
        if _c.FACE_ARRIVAL_INTERIOR_ENABLED and days > 0 and not self._arrival_zero_latched:
            since = self._last_arrival_ts or self._setup_ts or now
            if now - since >= days * 86400 and any(t >= since for t in self._interior_emits):
                self._arrival_zero_latched = True
                self._fire(
                    "face_arrival_zero",
                    f"Sightings but no face-before-phone arrival for {days:g} days",
                    "Expected if residents' phones always arrive first.",
                    "LOW",
                )

    def _fire(self, kind: str, diagnosis: str, remedy: str, severity: str) -> None:
        try:
            self.hass.async_create_task(
                fire_stuck_signal(
                    self.hass, kind=kind, key=("house",), diagnosis=diagnosis,
                    remedy=remedy, severity=severity,
                )
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("person sightings: trip-wire NM failed", exc_info=True)
