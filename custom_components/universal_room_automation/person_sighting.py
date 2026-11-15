"""Person sightings (FACE-ARRIVAL-REBUILD-1 D1 + D4; plan
``docs/planning/PLANNING_person_sighting_layer.md`` rev 11 §3.1-§3.2, §3.5).

A sighting is "person P was seen at place X at time T, by evidence of
provenance V, with confidence C". This module owns the ONE producer and its
ONE emit function. Three sources funnel into it:

  (a) the census Frigate MQTT face bridge (one callback per message, after the
      latch write; registered through ``signals.register_face_latch_callback``);
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
from . import interior_vision as _iv
from .camera_resolver import canonical_camera_key, resolve_area_id_for_entity
from .domain_coordinators._stuck_signal_nm import fire_stuck_signal
from .domain_coordinators.hvac_const import CONF_ZONE_CAMERAS
from .domain_coordinators.signals import (
    SIGNAL_PERSON_SIGHTING,
    register_face_latch_callback,
)

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


@dataclass(frozen=True)
class RoomSighting:
    """F4 UNNAMED room record (VISION-INTERIOR-SIGHTINGS-1 D1, plan §9.D1):
    bodies the NVRs see in one covered shared room, who is named there
    (BLE residents + named interior faces, one placement per slug), how
    many are unnamed. Display / suggestion class only; never a trust input
    (guard ``PINNED_READERS``). Constructed only by ``_emit_unnamed``."""

    room: str | None
    area_id: str | None
    group_key: str
    bodies: int | None
    bodies_nvr: int | None
    bodies_vision: int | None
    bodies_source: str | None
    named: tuple[str, ...]
    named_sources: tuple[tuple[str, str], ...]
    unnamed: int | None
    status: str
    provenance: str | None
    liveness: str
    entered_via: tuple[str, str] | None
    census_as_of: Any
    as_of: float


@dataclass(frozen=True)
class PathRecord:
    """F4 UNNAMED path record (D5 no-model leg, plan §9.D5): where an entry
    went inside. ``hops`` = ``(group_key, room, first_on_ts,
    bodies_nvr_at_first_on, bodies_vision)``, earliest first."""

    source_ref: str
    door: str
    ts: float
    n: int | None
    n_source: str | None
    hops: tuple[tuple[str, str | None, float, int | None, int | None], ...]


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
        self._bridge_unsub: Callable[[], None] | None = None
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
        # VISION-INTERIOR-SIGHTINGS-1 ship 1: the F4 UNNAMED stores (owner:
        # this producer; written only through `_emit_unnamed`).
        self._room_sightings: tuple[RoomSighting, ...] = ()
        self._path_records: deque = deque(maxlen=max(1, int(_c.INTERIOR_TIMELAPSE_RING)))
        self._vision_counts: dict[str, int] = {}   # filled by the vision ships
        self._interior_registries: Callable[[], tuple[Any, Any]] | None = None
        self._interior_groups: list[dict[str, Any]] = []
        self._interior_key_by_entity: dict[str, str] = {}
        self._interior_sig: Any = None
        self._interior_timer_unsub: Callable[[], None] | None = None
        self._interior_state_unsub: Callable[[], None] | None = None
        self._interior_tasks: set = set()
        self._interior_torn_down = False
        self._onedge_ring = _iv.OnEdgeRing(int(_c.INTERIOR_ONEDGE_RING_MAX))
        self._bodies_hist: dict[str, deque] = {}
        self._entered_via: dict[str, tuple[str, str, float]] = {}
        self._open_paths: dict[str, dict[str, Any]] = {}
        self._crossing_cursor: datetime | None = None
        self._crossing_seen_at_cursor: set[str] = set()
        self._iv_ticks_with_bodies: deque = deque()
        self._iv_records_written: deque = deque()
        self._iv_entries_mapped: deque = deque()
        self._iv_paths_written: deque = deque()
        self._iv_records_zero_latched = False
        self._iv_path_zero_latched = False
        self.interior_counters: Counter = Counter()
        self.interior_excluded: Counter = Counter()

    # ------------------------------------------------------------------ setup
    def async_setup(self) -> None:
        """Bind picks and register every listener. INV-NOOP: with
        FACE_SIGHTING_ENABLED False nothing is registered."""
        self._setup_ts = self._now()
        self._setup_interior()
        if not self.enabled:
            return
        self._bridge_cb = self._on_bridge
        # Ship 3a D1: the typed F4 camera ingest (same list, same order).
        self._bridge_unsub = register_face_latch_callback(self.hass, self._bridge_cb)
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
        self._teardown_interior()
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
        if self._bridge_unsub is not None:
            try:
                self._bridge_unsub()
            except Exception:  # noqa: BLE001
                pass
            self._bridge_unsub = None
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
            if census is not None and census.face_suppressed_now():
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
            mapped = slug if name_is_slug else census.canonical_person_slug(slug)
            tracked = set(census.tracked_person_slugs())
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
            tracker.note_face(sighting.slug, when)  # ship 3a D4

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
        _ring_fn = (
            getattr(census, "frigate_face_named_ring", None)
            if census is not None else None
        )
        ring = _ring_fn() if _ring_fn is not None else None
        if not ring:
            return 0
        try:
            tracked = set(census.tracked_person_slugs())
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
                slug = census.canonical_person_slug(name)
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

    # =================================================================
    # VISION-INTERIOR-SIGHTINGS-1 ship 1: F4 UNNAMED room records (D1) and
    # the no-model path time-lapse (D5). Own interval timer and own state
    # listener; nothing here runs on a presence inference / census path
    # (INV-IV-AWAY). Every camera read goes through ship 3b
    # (`interior_camera_entities`, `entity_stream_view`,
    # `physical_camera_dead`) and the registry; no name is parsed.
    # =================================================================
    def _emit_unnamed(self, kind: str, payload: Any) -> Any:
        """THE one F4 UNNAMED ingest (contract §2.4 / §7). ``kind``:
        ``room`` (payload = the field mappings of one build; replaces the
        room store) or ``path`` (payload = one path record's fields; appended
        to the ring). Sends no channel (SIGNAL_PERSON_SIGHTING listeners stay
        none, operator Q5). Unknown kind raises ``ValueError``."""
        if kind == "room":
            records = tuple(RoomSighting(**fields) for fields in payload)
            self._room_sightings = records
            self.interior_counters["record_builds"] += 1
            if records:
                self._iv_records_written.append(self._now())
                self._iv_records_zero_latched = False
            return records
        if kind == "path":
            record = PathRecord(**payload)
            self._path_records.append(record)
            self.interior_counters["path_records"] += 1
            self._iv_paths_written.append(self._now())
            self._iv_path_zero_latched = False
            return record
        raise ValueError(f"unknown unnamed kind {kind!r}")

    def get_room_sightings(self) -> tuple[RoomSighting, ...]:
        """The last build's room records (frozen tuple; display readers)."""
        return self._room_sightings

    def get_last_path_records(self) -> tuple[PathRecord, ...]:
        """Closed path records, oldest first (RAM ring)."""
        return tuple(self._path_records)

    # ------------------------------------------------------------- lifecycle
    def _setup_interior(self) -> None:
        """Register the record timer (``INTERIOR_ROOM_RECORD_INTERVAL_S``).
        Kill switch ``INTERIOR_ROOM_RECORDS_ENABLED`` False = nothing
        registered. The on-edge listener is (re)bound when the groups are
        built on the first tick."""
        self._interior_torn_down = False
        if not _c.INTERIOR_ROOM_RECORDS_ENABLED:
            return
        try:
            from datetime import timedelta  # noqa: PLC0415

            from homeassistant.helpers.event import (  # noqa: PLC0415
                async_track_time_interval,
            )
            self._interior_timer_unsub = async_track_time_interval(
                self.hass, self._on_interior_interval,
                timedelta(seconds=max(1, int(_c.INTERIOR_ROOM_RECORD_INTERVAL_S))),
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("interior vision: timer registration failed", exc_info=True)
        try:
            self._crossing_cursor = dt_util.utcnow()
        except Exception:  # noqa: BLE001
            self._crossing_cursor = None

    def _teardown_interior(self) -> None:
        self._interior_torn_down = True
        for name in ("_interior_timer_unsub", "_interior_state_unsub"):
            unsub = getattr(self, name)
            if unsub is not None:
                try:
                    unsub()
                except Exception:  # noqa: BLE001
                    pass
                setattr(self, name, None)
        for task in list(self._interior_tasks):
            try:
                task.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._interior_tasks.clear()
        self._open_paths.clear()

    @callback
    def _on_interior_interval(self, _now: Any = None) -> None:
        self.interior_tick()

    # ---------------------------------------------------------------- groups
    def _registries(self) -> tuple[Any, Any]:
        if self._interior_registries is not None:
            return self._interior_registries()
        from homeassistant.helpers import device_registry as _dr  # noqa: PLC0415
        from homeassistant.helpers import entity_registry as _er  # noqa: PLC0415

        return _er.async_get(self.hass), _dr.async_get(self.hass)

    def _room_entries(self) -> dict[str, dict[str, Any]]:
        """URA room entries by room name (merged data + options)."""
        out: dict[str, dict[str, Any]] = {}
        try:
            entries = self.hass.config_entries.async_entries(_c.DOMAIN)
        except Exception:  # noqa: BLE001
            return out
        for entry in entries:
            merged = {**(getattr(entry, "data", {}) or {}),
                      **(getattr(entry, "options", {}) or {})}
            if merged.get(_c.CONF_ENTRY_TYPE) != _c.ENTRY_TYPE_ROOM:
                continue
            name = merged.get(_c.CONF_ROOM_NAME)
            if name:
                out[str(name)] = merged
        return out

    def _ensure_interior_groups(self) -> None:
        """(Re)build the interior camera groups (plan §7) when the census
        interior list or the camera manager's resolver changed. Each interior
        entity -> its registry camera DEVICE -> the ship 3b twin group (pure
        pairing, computed once per rebuild); key = min device id of the group;
        area = entity area else device area; room by area; a group with no
        room or an excluded room type gets no record (counted)."""
        census = self._census()
        try:
            interior = list(census.interior_camera_entities()) if census is not None else []
        except Exception:  # noqa: BLE001
            interior = []
        resolver = self._resolver()
        sig = (tuple(interior), id(resolver))
        if sig == self._interior_sig:
            return
        try:
            er_, dr_ = self._registries()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("interior vision: registries unavailable", exc_info=True)
            return
        from .domain_coordinators import camera_stream_health as _csh  # noqa: PLC0415

        pure = _csh.pure_twin_groups(er_, dr_)
        by_key: dict[str, dict[str, Any]] = {}
        excluded: Counter = Counter()
        for eid in interior:
            dev = _csh.camera_device_for_entity(er_, eid)
            if dev is None:
                excluded["no_camera_device"] += 1
                continue
            group = _csh.twin_pair_for_device(er_, dr_, dev, groups=pure)
            key = min(group)
            g = by_key.setdefault(key, {"group_key": key, "devices": tuple(sorted(group)),
                                        "members": []})
            g["members"].append(eid)
        rooms = self._room_entries()
        groups: list[dict[str, Any]] = []
        key_by_entity: dict[str, str] = {}
        for key, g in sorted(by_key.items()):
            area = None
            for eid in g["members"]:
                try:
                    area = resolve_area_id_for_entity(er_, dr_, eid)
                except Exception:  # noqa: BLE001
                    area = None
                if area:
                    break
            room = self._room_for_area(area)
            if room is None:
                excluded["no_room"] += 1
                continue
            room_type = (rooms.get(room) or {}).get(_c.CONF_ROOM_TYPE)
            if room_type in _c.INTERIOR_VISION_EXCLUDED_ROOM_TYPES:
                excluded["excluded_room_type"] += 1
                continue
            frig = _csh.frigate_member(er_, g["devices"])
            still = _csh.own_camera_entity_for_device(er_, frig) if frig else None
            if still is None:
                excluded["no_still_source"] += 1  # counted, still recorded
            g.update(members=tuple(sorted(g["members"])), area_id=area, room=room,
                     room_type=room_type, still_source=still)
            groups.append(g)
            for eid in g["members"]:
                key_by_entity[eid] = key
        self._interior_groups = groups
        self._interior_key_by_entity = key_by_entity
        self.interior_excluded = excluded
        self._interior_sig = sig
        self._bind_onedge_listener()

    def _bind_onedge_listener(self) -> None:
        if self._interior_state_unsub is not None:
            try:
                self._interior_state_unsub()
            except Exception:  # noqa: BLE001
                pass
            self._interior_state_unsub = None
        entities = sorted(self._interior_key_by_entity)
        if not entities or self._interior_torn_down:
            return
        self._interior_state_unsub = async_track_state_change_event(
            self.hass, entities, self._on_interior_person_state,
        )

    @callback
    def _on_interior_person_state(self, event: Any) -> None:
        """D1 on-edge stamp (O(1), no await): a group's person sensor going
        to ``on`` from anything else."""
        data = getattr(event, "data", {}) or {}
        new_state = data.get("new_state")
        old_state = data.get("old_state")
        if new_state is None or getattr(new_state, "state", None) != "on":
            return
        if old_state is not None and getattr(old_state, "state", None) == "on":
            return
        key = self._interior_key_by_entity.get(data.get("entity_id") or "")
        if key is None:
            return
        lc = getattr(new_state, "last_changed", None)
        ts = lc.timestamp() if isinstance(lc, datetime) else self._now()
        self._onedge_ring.append(ts, key)

    # ------------------------------------------------------------------ tick
    def _named_by_room(self, now: float) -> dict[str, dict[str, str]]:
        """One placement per slug: BLE ACTIVE room (the one BLE-in-room read,
        phone-left-behind filtered) over every URA room, else the newest fresh
        named interior face sighting (``census_would_veto`` False)."""
        from .person_ids import slug_of  # noqa: PLC0415

        ble: dict[str, str] = {}
        pc = self.hass.data.get(_c.DOMAIN, {}).get("person_coordinator")
        reader = getattr(pc, "persons_in_room", None) if pc is not None else None
        if callable(reader):
            for room in sorted(self._room_entries()):
                try:
                    names = reader(room, active_only=True)
                except Exception:  # noqa: BLE001
                    continue
                for name in names or ():
                    slug = slug_of(name)
                    if slug:
                        ble.setdefault(slug, room)
        faces = [
            (s.slug, s.room, s.ts) for s in self._last_sightings.values()
            if s.sighting_source == SIGHTING_SOURCE_INTERIOR and s.room
            and not s.census_would_veto
        ]
        placed = _iv.place_named(ble, faces, now, float(_c.INTERIOR_ROOM_FACE_FRESH_S))
        out: dict[str, dict[str, str]] = {}
        for slug, (room, src) in placed.items():
            out.setdefault(room, {})[slug] = src
        return out

    def interior_tick(self, now: float | None = None) -> tuple[RoomSighting, ...]:
        """One record build (timer callback; sync, never raises out)."""
        if self._interior_torn_down or not _c.INTERIOR_ROOM_RECORDS_ENABLED:
            return self._room_sightings
        now = self._now() if now is None else float(now)
        try:
            return self._interior_tick(now)
        except Exception:  # noqa: BLE001
            self.interior_counters["tick_errors"] += 1
            _LOGGER.debug("interior vision: tick failed", exc_info=True)
            return self._room_sightings

    def _interior_tick(self, now: float) -> tuple[RoomSighting, ...]:
        from .domain_coordinators import camera_stream_health as _csh  # noqa: PLC0415
        from .domain_coordinators import camera_twin_health as _cth  # noqa: PLC0415

        self._ensure_interior_groups()
        census = self._census()
        try:
            evidence = census.area_evidence() if census is not None else {}
        except Exception:  # noqa: BLE001
            evidence = {}
        by_entity = (evidence or {}).get("by_entity") or {}
        liveness: dict[str, str] = {}
        groups: list[dict[str, Any]] = []
        for g in self._interior_groups:
            for eid in g["members"]:
                try:
                    view = _csh.entity_stream_view(self.hass, eid, census=True)
                except Exception:  # noqa: BLE001
                    view = None
                st = self.hass.states.get(eid)
                liveness[eid] = _iv.member_liveness(
                    view, getattr(st, "state", None) if st is not None else None)
            dead = None
            if not any(liveness.get(e) == _iv.LIVE for e in g["members"]):
                dead = _cth.physical_camera_dead(self.hass, g["group_key"])
            groups.append({**g, "physical_dead": dead})
        # Trip-wire numerator, independent of the group build: any census
        # interior entity reading live with a last reading > 0.
        try:
            interior = list(census.interior_camera_entities()) if census is not None else []
        except Exception:  # noqa: BLE001
            interior = []
        for eid in interior:
            st = self.hass.states.get(eid)
            if (int(by_entity.get(eid) or 0) > 0 and st is not None
                    and _iv.member_liveness(None, st.state) == _iv.LIVE):
                self._iv_ticks_with_bodies.append(now)
                break
        # D5 first, so a hop found this tick seeds `entered_via` on this build.
        self._path_tick(now)
        for room in [r for r, seed in self._entered_via.items() if seed[2] < now]:
            del self._entered_via[room]
        for g in groups:
            seed = self._entered_via.get(g["room"])
            g["entered_via"] = (seed[0], seed[1]) if seed else None
        fields = _iv.build_room_records(
            groups, evidence, liveness, self._named_by_room(now),
            dict(self._vision_counts), now,
        )
        records = self._emit_unnamed("room", fields)
        hist_len = int(
            (int(_c.INTERIOR_TIMELAPSE_MAX_HOPS) * float(_c.EGRESS_PATH_BUFFER_S)
             + float(_c.INTERIOR_TIMELAPSE_CLOSE_PAD_S))
            / max(1.0, float(_c.INTERIOR_ROOM_RECORD_INTERVAL_S))) + 2
        for r in records:
            dq = self._bodies_hist.get(r.group_key)
            if dq is None or dq.maxlen != hist_len:
                dq = self._bodies_hist[r.group_key] = deque(dq or (), maxlen=hist_len)
            dq.append((now, r.bodies_nvr))
        self._check_interior_tripwires(now)
        return records

    # ------------------------------------------------------------ D5 (paths)
    def _door_edges(self) -> dict[str, tuple[Any, ...]]:
        tracker = self.hass.data.get(_c.DOMAIN, {}).get("egress_tracker")
        if tracker is None:
            return {}
        try:
            doors = tracker.path_map_status().get("path_map_doors") or []
        except Exception:  # noqa: BLE001
            return {}
        out: dict[str, tuple[Any, ...]] = {}
        for door in doors:
            try:
                edges = tuple(tracker.inward_path_edges(door) or ())
            except Exception:  # noqa: BLE001
                edges = ()
            if edges:
                out[door] = edges
        return out

    def _new_entries(self) -> list[Any]:
        """Entry crossings since the last pull (F3 read, oldest first)."""
        cursor = self._crossing_cursor
        if cursor is None:
            return []
        try:
            recs = list(self._presence.get_crossings_since(cursor))
        except Exception:  # noqa: BLE001
            return []
        fresh = [r for r in recs if r.source_ref not in self._crossing_seen_at_cursor]
        if recs:
            top = max(r.ts for r in recs)
            if top > cursor:
                self._crossing_cursor = top
                self._crossing_seen_at_cursor = {r.source_ref for r in recs if r.ts == top}
            else:
                self._crossing_seen_at_cursor |= {r.source_ref for r in recs}
        return [r for r in fresh if getattr(r, "direction", None) == "entry"]

    def _path_tick(self, now: float) -> None:
        doors = self._door_edges()
        for rec in self._new_entries():
            root = self._egress_key(str(rec.camera))
            for door, edges in sorted(doors.items()):
                if not any(e.from_key == root for e in edges):
                    continue
                self._open_paths[rec.source_ref] = {
                    "source_ref": rec.source_ref, "door": door, "root": root,
                    "entry_ts": rec.ts.timestamp(), "edges": edges,
                }
                self._iv_entries_mapped.append(now)
                self.interior_counters["entries_mapped"] += 1
                break
            else:
                self.interior_counters["entries_unmapped"] += 1
        room_of = {g["group_key"]: g["room"] for g in self._interior_groups}
        max_hops = int(_c.INTERIOR_TIMELAPSE_MAX_HOPS)
        for ref, op in list(self._open_paths.items()):
            entry_ts = op["entry_ts"]
            windows = _iv.chain_windows(
                op["edges"], op["root"], entry_ts,
                self._onedge_ring.by_group_since(entry_ts), max_hops,
            )
            for key, w in windows.items():
                room = room_of.get(key)
                if w.get("first_on") is not None and room:
                    self._entered_via[room] = (
                        op["door"], dt_util.utc_from_timestamp(entry_ts).isoformat(),
                        float(w["first_on"]) + float(_c.INTERIOR_TIMELAPSE_SEED_TTL_S),
                    )
            close_at = max((w["close"] for w in windows.values()), default=entry_ts)
            if now < close_at + float(_c.INTERIOR_TIMELAPSE_CLOSE_PAD_S):
                continue
            del self._open_paths[ref]
            hops = sorted(
                (key, room_of.get(key), float(w["first_on"]),
                 self._bodies_at(key, float(w["first_on"])), None)
                for key, w in windows.items() if w.get("first_on") is not None
            )
            hops.sort(key=lambda h: h[2])
            n, n_source = self._path_n(ref, hops)
            record = self._emit_unnamed("path", {
                "source_ref": ref, "door": op["door"], "ts": entry_ts,
                "n": n, "n_source": n_source, "hops": tuple(hops),
            })
            self._log_path_row(record)

    def _bodies_at(self, key: str, ts: float) -> int | None:
        dq = self._bodies_hist.get(key) or ()
        last = None
        for t, b in dq:
            if t >= ts:
                return b
            last = b
        return last

    def _path_n(self, source_ref: str, hops: list) -> tuple[int | None, str | None]:
        """``n`` read order (plan §9.D5): the crossing's G3 ``people_count``
        attribute, else the crossing-vision arrival record with the same
        ``source_ref``, else the max ``bodies_nvr`` on the first hop."""
        try:
            rec = self._presence.get_crossing(source_ref)
        except Exception:  # noqa: BLE001
            rec = None
        val = getattr(rec, "people_count", None) if rec is not None else None
        if isinstance(val, int) and not isinstance(val, bool):
            return val, "crossing"
        try:
            arr = self._presence.get_last_arrival_record()
        except Exception:  # noqa: BLE001
            arr = None
        if arr is not None:
            get = arr.get if isinstance(arr, dict) else (lambda k, d=None: getattr(arr, k, d))
            val = get("people_count")
            if get("source_ref") == source_ref and isinstance(val, int) \
                    and not isinstance(val, bool):
                return val, "arrival_record"
        if hops and hops[0][3] is not None:
            return int(hops[0][3]), "first_hop"
        return None, None

    def _log_path_row(self, record: PathRecord) -> None:
        database = self.hass.data.get(_c.DOMAIN, {}).get("database")
        if database is None or self._interior_torn_down:
            return
        attrs = {
            "door": record.door, "ts": dt_util.utc_from_timestamp(record.ts).isoformat(),
            "n": record.n, "n_source": record.n_source,
            "hops": [{"group": h[0], "room": h[1], "first_on_s": round(h[2] - record.ts, 1),
                      "bodies_nvr": h[3], "bodies_vision": h[4]} for h in record.hops],
        }
        try:
            task = self.hass.async_create_task(database.log_memory_episode(
                node_id=f"ipath:{record.source_ref}", episode_type="interior_path",
                attrs=attrs, source_ref=record.source_ref,
                dedup_source_ref=True, window_dedup=False,
            ))
        except Exception:  # noqa: BLE001
            _LOGGER.debug("interior vision: path row failed", exc_info=True)
            return
        self._interior_tasks.add(task)
        try:
            task.add_done_callback(self._interior_tasks.discard)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ trip-wires
    def _check_interior_tripwires(self, now: float) -> None:
        window_s = float(_c.INTERIOR_ZERO_WINDOW_H) * 3600.0
        for dq in (self._iv_ticks_with_bodies, self._iv_records_written,
                   self._iv_entries_mapped, self._iv_paths_written):
            while dq and dq[0] < now - window_s:
                dq.popleft()
        min_ticks = int(_c.INTERIOR_ZERO_MIN_TICKS)
        if (min_ticks > 0 and not self._iv_records_zero_latched
                and len(self._iv_ticks_with_bodies) >= min_ticks
                and not self._iv_records_written):
            self._iv_records_zero_latched = True
            self._fire(
                "interior_room_records_zero",
                f"Interior cameras saw people on {len(self._iv_ticks_with_bodies)} record "
                f"ticks in {float(_c.INTERIOR_ZERO_WINDOW_H):g} h but no room record was built",
                "Check the interior camera groups (registry) and the census interior "
                "camera list.", "HIGH",
            )
        min_entries = int(_c.INTERIOR_TIMELAPSE_ZERO_MIN_ENTRIES)
        if (min_entries > 0 and not self._iv_path_zero_latched
                and len(self._iv_entries_mapped) >= min_entries
                and not self._iv_paths_written):
            self._iv_path_zero_latched = True
            self._fire(
                "interior_path_zero",
                f"{len(self._iv_entries_mapped)} entries on mapped doors in "
                f"{float(_c.INTERIOR_ZERO_WINDOW_H):g} h but no path record",
                "Check the interior path map and the door crossing reads.", "LOW",
            )

    def interior_diagnostics(self) -> dict[str, Any]:
        """Counters for ``get_layer_diagnostics()["interior_vision"]``."""
        by_liveness: Counter = Counter(r.liveness for r in self._room_sightings)
        return {
            "record_builds": int(self.interior_counters.get("record_builds", 0)),
            "records": len(self._room_sightings),
            "groups": len(self._interior_groups),
            "groups_by_liveness": dict(sorted(by_liveness.items())),
            "groups_excluded_by_reason": dict(sorted(self.interior_excluded.items())),
            "path_records": int(self.interior_counters.get("path_records", 0)),
            "open_paths": len(self._open_paths),
            "entries_mapped": int(self.interior_counters.get("entries_mapped", 0)),
            "entries_unmapped": int(self.interior_counters.get("entries_unmapped", 0)),
            "onedge_ring": len(self._onedge_ring),
            "tick_errors": int(self.interior_counters.get("tick_errors", 0)),
        }
