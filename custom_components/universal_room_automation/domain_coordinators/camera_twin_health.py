"""Person-awareness layer ship 3b: the device-level dead-camera rule owner.

Plan: ``docs/planning/PLANNING_person_awareness_layer_ship3.md`` §6 (D6,
option A, decided Q11; device level, decided Q12). Contract evidence service
§2.6 (camera input stream health).

``CameraTwinHealth`` is ONE instance per install, created on the coordinator
manager entry at ``hass.data[DOMAIN]["camera_twin_health"]``. It owns:

* the device TWIN MAP (W1 pairing ``CameraResolver.frigate_object_name_pairs``
  plus the NVR-platform check; one fresh resolver per build, debounced
  rebuilds on device / entity registry events);
* the HOUSE TRACKER for cameras no room watches: the census interior and
  zone camera entities outside every room's watch (the unwatched set U),
  stamped and held exactly like a room input (the same
  ``CameraInputStreamHealth`` code), answering the house readers only for
  entities in U ∪ sticky and only when no room has an opinion;
* the GROUP PAGES (operator rule 2: a camera is dead only when every paired
  NVR device has lost it): HIGH ``camera_stream_hold_released`` (or S1 with
  both caps 0) per group episode, the MEDIUM "one NVR down, the other
  covering" notice per member episode, the LOW at the episode end, for
  groups some URA reader uses (Wr ∪ U).

No reader takes a twin's reading (option A); ``physical_camera_dead`` is read
by the pages and the diagnostics only. Every behavioural number is a rung-1
const in ``const.py`` (§8).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from .. import const as _const
from . import camera_stream_health as _csh

_LOGGER = logging.getLogger(__name__)

# NM kinds (one vocabulary with the room tracker).
NM_KIND_S1 = _csh.NM_KIND
NM_KIND_S2 = _csh.NM_KIND_HOLD_RELEASED
NM_KIND_TWIN_COVERING = "camera_stream_nvr_down_twin_covering"
# The owner's S1 key prefix: ("<group>", page_camera_key).
GROUP_S1_KEY = "<group>"

_NVR_NAMES = {
    "frigate": "Frigate",
    "unifiprotect": "UniFi Protect",
    "reolink": "Reolink",
    "amcrest": "Amcrest",
    "dahua": "Dahua",
}


def _knob(name: str, default: Any) -> Any:
    return getattr(_const, name, default)


def _twin_rule() -> bool:
    return bool(_knob("CAMERA_STREAM_DEAD_TWIN_RULE", False))


def _positive_caps() -> list[float]:
    return [
        c for c in (
            float(_knob("CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S", 0.0)),
            float(_knob("CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S", 0.0)),
        ) if c > 0
    ]


class CameraTwinHealth:
    """The twin map, the house tracker and the group pages (one per install).

    Its house tracker is a private attribute whose name no ``hass.data``
    scan matches (``camera_stream_health._room_coordinators`` looks for
    ``_camera_stream_health``), so the owner never joins the room fold.
    """

    def __init__(
        self,
        hass: Any,
        *,
        clock: Callable[[], datetime] | None = None,
        entity_registry_getter: Callable[[], Any] | None = None,
        device_registry_getter: Callable[[], Any] | None = None,
    ) -> None:
        self.hass = hass
        self._clock = clock or dt_util.now
        self._er_getter = entity_registry_getter or self._default_er
        self._dr_getter = device_registry_getter or self._default_dr
        self.torn_down = False
        self.map_ready = False
        self._setup_at: datetime = self._clock()
        # Twin map (device -> its admitted pair, both directions).
        self._groups: dict[str, frozenset[str]] = {}
        self._admitted: list[tuple[str, str]] = []
        self._rejected: list[tuple[str, str]] = []
        self._candidates: frozenset[str] = frozenset()
        self._known_camera_devices: frozenset[str] = frozenset()
        self._map_stale_since: datetime | None = None
        self._build_count = 0
        self._build_failures = 0
        # Registry listeners + debounce.
        self._unsubs: list[Callable[[], None]] = []
        self._debounce_unsub: Callable[[], None] | None = None
        self._pending_events: list[tuple[str, dict]] = []
        # Watched / unwatched sets (§6.3).
        self._sets_ready = False
        self._wr_devices: frozenset[str] = frozenset()
        self._room_inputs: list[tuple[str, str, str]] = []  # (room, input, device)
        self._unwatched: frozenset[str] = frozenset()
        self._unwatched_devices: frozenset[str] = frozenset()
        self._sticky_until: dict[str, datetime] = {}
        self._active_device_of: dict[str, str] = {}
        # The house tracker (RAM; rebuilt on restart).
        self._unwatched_tracker = _csh.CameraInputStreamHealth("<house>")
        # Loss rule per member device (§6.1).
        self._notlive_since: dict[str, datetime] = {}
        self._live_since: dict[str, datetime] = {}
        self._seen_real: set[str] = set()
        # Group episodes (§6.6). frozenset(members) -> episode dict.
        self._episodes: dict[frozenset[str], dict[str, Any]] = {}
        # HIGH sent in the group's current (or adopted) episode; cleared at
        # the episode end only.
        self._group_high_sent: dict[frozenset[str], bool] = {}
        self._s1_day: dict[frozenset[str], str] = {}
        # MEDIUM per member device episode.
        self._member_medium: dict[str, dict[str, Any]] = {}
        self._adoption_sweep_due = True
        # Sends in flight (ident) and tracked tasks.
        self._inflight: set[str] = set()
        self._tasks: set[Any] = set()
        # Diagnostics.
        self.page_counts: dict[str, int] = {}
        self.last_results: dict[str, str] = {}

    # ------------------------------------------------------------------
    # HA seams
    # ------------------------------------------------------------------

    def _default_er(self) -> Any:
        from homeassistant.helpers import entity_registry as er  # noqa: PLC0415
        return er.async_get(self.hass)

    def _default_dr(self) -> Any:
        from homeassistant.helpers import device_registry as dr  # noqa: PLC0415
        return dr.async_get(self.hass)

    def _registries(self) -> tuple[Any, Any]:
        try:
            er = self._er_getter()
        except Exception:  # noqa: BLE001
            er = None
        try:
            dr = self._dr_getter()
        except Exception:  # noqa: BLE001
            dr = None
        return er, dr

    def _domain_data(self) -> dict:
        try:
            return self.hass.data.get(_const.DOMAIN) or {}
        except Exception:  # noqa: BLE001
            return {}

    # ------------------------------------------------------------------
    # Lifecycle (§6.4)
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """First (attempted) build, registry listeners and the tick."""
        self._setup_at = self._clock()
        self._rebuild()
        try:
            from homeassistant.helpers.device_registry import (  # noqa: PLC0415
                EVENT_DEVICE_REGISTRY_UPDATED,
            )
            from homeassistant.helpers.entity_registry import (  # noqa: PLC0415
                EVENT_ENTITY_REGISTRY_UPDATED,
            )
            self._unsubs.append(self.hass.bus.async_listen(
                EVENT_DEVICE_REGISTRY_UPDATED, self._on_device_registry_event,
            ))
            self._unsubs.append(self.hass.bus.async_listen(
                EVENT_ENTITY_REGISTRY_UPDATED, self._on_entity_registry_event,
            ))
        except Exception:  # noqa: BLE001 — test stubs without the constants
            _LOGGER.debug("camera twin health: registry listeners not set", exc_info=True)
        try:
            from homeassistant.helpers.event import (  # noqa: PLC0415
                async_track_time_interval,
            )
            self._unsubs.append(async_track_time_interval(
                self.hass, self._on_interval,
                timedelta(seconds=float(_knob("CAMERA_TWIN_HEALTH_TICK_S", 30.0))),
            ))
        except Exception:  # noqa: BLE001
            _LOGGER.debug("camera twin health: tick not scheduled", exc_info=True)

    def async_teardown(self) -> None:
        """Pop the data key, mark torn down (checked first by the debounce
        and the tick), unsubscribe the listeners and the interval, cancel
        the pending debounce and in-flight sends, clear the house tracker's
        state getter."""
        self.torn_down = True
        data = self._domain_data()
        if data.get(_csh.TWIN_HEALTH_DATA_KEY) is self:
            data.pop(_csh.TWIN_HEALTH_DATA_KEY, None)
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._unsubs.clear()
        if self._debounce_unsub is not None:
            try:
                self._debounce_unsub()
            except Exception:  # noqa: BLE001
                pass
            self._debounce_unsub = None
        for task in list(self._tasks):
            try:
                task.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._tasks.clear()
        self._unwatched_tracker.clear_state_getter()

    @callback
    def _on_interval(self, _now: Any = None) -> None:
        if self.torn_down:
            return
        try:
            self.tick()
        except Exception:  # noqa: BLE001 — never break the loop
            _LOGGER.debug("camera twin health tick raised", exc_info=True)

    # ------------------------------------------------------------------
    # Twin map (§6.4)
    # ------------------------------------------------------------------

    @callback
    def _on_device_registry_event(self, event: Any) -> None:
        self._queue_event("device", event)

    @callback
    def _on_entity_registry_event(self, event: Any) -> None:
        self._queue_event("entity", event)

    def _queue_event(self, source: str, event: Any) -> None:
        if self.torn_down:
            return
        try:
            data = dict(getattr(event, "data", {}) or {})
        except Exception:  # noqa: BLE001
            data = {}
        self._pending_events.append((source, data))
        if self._debounce_unsub is not None:
            return
        try:
            from homeassistant.helpers.event import (  # noqa: PLC0415
                async_call_later,
            )
            self._debounce_unsub = async_call_later(
                self.hass,
                float(_knob("CAMERA_TWIN_MAP_REBUILD_DEBOUNCE_S", 10.0)),
                self._on_debounce,
            )
        except Exception:  # noqa: BLE001
            self._debounce_unsub = None

    @callback
    def _on_debounce(self, _now: Any = None) -> None:
        """Debounced rebuild: filters evaluated NOW (rebuild time), so an
        event whose device gained its camera after the event still counts."""
        self._debounce_unsub = None
        if self.torn_down:
            return
        events, self._pending_events = self._pending_events, []
        if self._events_relevant(events):
            self._rebuild()

    def _events_relevant(self, events: Iterable[tuple[str, dict]]) -> bool:
        er, _dr = self._registries()
        watched = set(self._groups) | set(self._candidates) | set(
            self._known_camera_devices,
        )
        for source, data in events:
            if source == "device":
                action = data.get("action")
                if action in ("create", "remove"):
                    return True
                dev = data.get("device_id")
                if dev in watched or (
                    er is not None and _csh.device_camera_members(er, dev)
                ):
                    return True
                continue
            for key in ("entity_id", "old_entity_id"):
                eid = str(data.get(key) or "")
                if eid.startswith("camera."):
                    return True
            eid = data.get("entity_id")
            if er is not None and eid:
                try:
                    ent = er.async_get(eid)
                except Exception:  # noqa: BLE001
                    ent = None
                dev = getattr(ent, "device_id", None) if ent is not None else None
                if dev and dev in watched:
                    return True
        return False

    def _rebuild(self) -> None:
        """One build from a FRESH resolver. A build that raises keeps the
        previous map (the first one leaves an empty map, logged) and sets
        ``map_stale_since``; ``map_ready`` is set after the first attempt."""
        er, dr = self._registries()
        now = self._clock()
        self._build_count += 1
        try:
            if er is None or dr is None:
                raise RuntimeError("registry unavailable")
            groups, admitted, rejected = _csh.build_twin_map(er, dr)
            known = _camera_devices(er)
        except Exception:  # noqa: BLE001
            self._build_failures += 1
            if self._map_stale_since is None:
                self._map_stale_since = now
            if not self.map_ready:
                _LOGGER.warning(
                    "camera twin health: first twin-map build failed; rooms "
                    "page every device until a build succeeds",
                    exc_info=True,
                )
            else:
                _LOGGER.info(
                    "camera twin health: twin-map rebuild failed; keeping the "
                    "previous map", exc_info=True,
                )
            self.map_ready = True
            return
        self._groups = groups
        self._admitted = admitted
        self._rejected = rejected
        self._candidates = frozenset(
            d for pair in admitted + rejected for d in pair
        )
        self._known_camera_devices = known
        self._map_stale_since = None
        self.map_ready = True
        self._adoption_sweep_due = True

    def in_map(self, device_id: str | None) -> bool:
        """The device is in the OWNER'S map (an admitted pair member). Always
        False with CAMERA_STREAM_DEAD_TWIN_RULE off (a runtime flip leaves
        the last map in RAM; it is not used)."""
        return (
            bool(device_id) and _twin_rule() and device_id in self._groups
        )

    def is_map_candidate(self, device_id: str | None) -> bool:
        """The device has a W1 sibling in the last build (admitted or not)."""
        return bool(device_id) and device_id in self._candidates

    def deferral_active(self, now: datetime) -> bool:
        """Rooms defer pages while the owner is present and not map-ready,
        bounded by CAMERA_TWIN_BOOT_SETTLE_S from the owner's setup."""
        if self.map_ready:
            return False
        try:
            elapsed = (now - self._setup_at).total_seconds()
        except Exception:  # noqa: BLE001
            return False
        return elapsed < float(_knob("CAMERA_TWIN_BOOT_SETTLE_S", 600.0))

    def group_for(self, device_id: str) -> frozenset[str]:
        """The device's group in the owner's map, or the device alone (also
        with the twin rule off)."""
        if not _twin_rule():
            return frozenset({device_id})
        return self._groups.get(device_id, frozenset({device_id}))

    # ------------------------------------------------------------------
    # The tick: sets, house tracker, pages
    # ------------------------------------------------------------------

    def tick(self, now: datetime | None = None) -> None:
        if self.torn_down:
            return
        now = now or self._clock()
        if not bool(_knob("CAMERA_INPUT_STREAM_HEALTH_ENABLED", False)):
            # Kill switch: no exclusion, no hold, no page (house fallback
            # None, as before 3b).
            self._sets_ready = False
            return
        er, dr = self._registries()
        if er is None:
            return
        self._compute_sets(now, er)
        if self._sets_ready:
            inputs = sorted(self._active_entities(now))
            # The house tracker reuses the room code; its page candidates
            # are DISCARDED (the owner pages only through its groups). It
            # answers readers only through ``house_tracker_for`` (the one
            # gate of CAMERA_STREAM_UNWATCHED_STAMPS_ENABLED for answers).
            self._unwatched_tracker.evaluate(
                now, inputs, self._state_get, lambda: er,
            )
        if self._sets_ready:
            self._evaluate_groups(now, er, dr)

    def _state_get(self, entity_id: str) -> Any:
        return self.hass.states.get(entity_id)

    def _compute_sets(self, now: datetime, er: Any) -> None:
        """Wr (devices rooms watch) and U (census / zone camera entities on
        no watched device), only once the camera manager is present."""
        data = self._domain_data()
        if data.get("camera_manager") is None:
            self._sets_ready = False
            return
        room_inputs: list[tuple[str, str, str]] = []
        wr: set[str] = set()
        try:
            entries = list(self.hass.config_entries.async_entries(_const.DOMAIN))
        except Exception:  # noqa: BLE001
            entries = []
        for entry in entries:
            if not _csh.is_room_entry(entry):
                continue
            room, configured, extras = _csh.room_stream_input_entities(
                self.hass, entry,
            )
            for eid in configured + extras:
                dev = _csh.camera_device_for_entity(er, eid)
                if dev:
                    wr.add(dev)
                    room_inputs.append((room, eid, dev))
        candidates = set(self._census_entities()) | set(self._zone_entities())
        unwatched: set[str] = set()
        device_of: dict[str, str] = {}
        for eid in candidates:
            dev = _csh.camera_device_for_entity(er, eid)
            if dev and dev not in wr:
                unwatched.add(eid)
                device_of[eid] = dev
        grace = float(_knob("CAMERA_INPUT_STREAM_DEAD_GRACE_S", 120.0))
        new_u = frozenset(unwatched)
        for eid in self._unwatched - new_u:
            self._sticky_until[eid] = now + timedelta(seconds=grace)
        for eid in new_u:
            self._sticky_until.pop(eid, None)
        for eid, until in list(self._sticky_until.items()):
            if until <= now:
                self._sticky_until.pop(eid, None)
                self._active_device_of.pop(eid, None)
        for eid, dev in device_of.items():
            self._active_device_of[eid] = dev
        self._unwatched = new_u
        self._unwatched_devices = frozenset(device_of.values())
        self._wr_devices = frozenset(wr)
        self._room_inputs = room_inputs
        self._sets_ready = True

    def _census_entities(self) -> list[str]:
        census = self._domain_data().get("census")
        fn = getattr(census, "interior_camera_entities", None)
        if not callable(fn):
            return []
        try:
            return [e for e in (fn() or []) if isinstance(e, str) and e]
        except Exception:  # noqa: BLE001
            return []

    def _zone_entities(self) -> list[str]:
        manager = self._domain_data().get("coordinator_manager")
        try:
            presence = manager.coordinators.get("presence") if manager else None
        except Exception:  # noqa: BLE001
            presence = None
        fn = getattr(presence, "zone_camera_entities", None)
        if not callable(fn):
            return []
        try:
            return [e for e in (fn() or []) if isinstance(e, str) and e]
        except Exception:  # noqa: BLE001
            return []

    def _active_entities(self, now: datetime) -> set[str]:
        """U ∪ sticky (an entity that left U within one grace)."""
        out = set(self._unwatched)
        for eid, until in self._sticky_until.items():
            if until > now:
                out.add(eid)
        return out

    def house_tracker_for(self, key: str) -> Any:
        """The house tracker, only for an entity (or a camera whose device)
        is in U ∪ sticky NOW; else None (outside it the house getters answer
        exactly as the rooms do). None until the camera manager is present
        and with the unwatched-stamps or master kill switch off."""
        if (
            self.torn_down or not self._sets_ready
            or not bool(_knob("CAMERA_STREAM_UNWATCHED_STAMPS_ENABLED", False))
            or not bool(_knob("CAMERA_INPUT_STREAM_HEALTH_ENABLED", False))
            or not key
        ):
            return None
        now = self._clock()
        active = self._active_entities(now)
        if key in active:
            return self._unwatched_tracker
        if str(key).startswith("camera."):
            er, _dr = self._registries()
            dev = _csh.camera_device_for_entity(er, key) if er is not None else None
            if dev and any(self._active_device_of.get(e) == dev for e in active):
                return self._unwatched_tracker
        return None

    # ------------------------------------------------------------------
    # Loss rule and the group gate (§6.1, §6.5)
    # ------------------------------------------------------------------

    def _update_loss(self, dev: str, now: datetime, er: Any) -> None:
        live = dead_read = False
        for cam in _csh.device_camera_members(er, dev):
            cls = _csh.member_reading(self._state_get(cam))
            if cls == _csh.READING_LIVE:
                live = True
                break
            if cls == _csh.READING_DEAD:
                dead_read = True
        if live:
            self._notlive_since.pop(dev, None)
            self._live_since.setdefault(dev, now)
            self._seen_real.add(dev)
            return
        self._live_since.pop(dev, None)
        self._notlive_since.setdefault(dev, now)
        if dead_read:
            self._seen_real.add(dev)

    def _lost(self, dev: str, now: datetime) -> bool:
        """LOST: not live for the grace; a member no-opinion since setup
        counts only after CAMERA_TWIN_BOOT_SETTLE_S from setup."""
        since = self._notlive_since.get(dev)
        if since is None:
            return False
        grace = float(_knob("CAMERA_INPUT_STREAM_DEAD_GRACE_S", 120.0))
        if (now - since).total_seconds() < grace:
            return False
        if dev in self._seen_real:
            return True
        settle = float(_knob("CAMERA_TWIN_BOOT_SETTLE_S", 600.0))
        return (now - self._setup_at).total_seconds() >= settle

    def _group_alive(self, group: frozenset[str]) -> bool:
        """Some member device reads LIVE (its live stretch is running)."""
        return any(d in self._live_since for d in group)

    def _group_dead(self, group: frozenset[str], now: datetime) -> bool:
        return bool(group) and all(self._lost(d, now) for d in group)

    def physical_camera_dead(self, entity_or_device: str) -> bool | None:
        """True iff EVERY member device of the camera's group is LOST."""
        er, _dr = self._registries()
        dev = None
        if er is not None and entity_or_device:
            dev = _csh.camera_device_for_entity(er, entity_or_device)
        dev = dev or entity_or_device
        if not dev:
            return None
        return self._group_dead(self.group_for(dev), self._clock())

    # ------------------------------------------------------------------
    # Pages (§6.6)
    # ------------------------------------------------------------------

    def _scope_groups(self) -> set[frozenset[str]]:
        """Groups with a member some URA reader uses (Wr ∪ U devices). The
        reader-less admitted pairs never page from 3b."""
        readers = set(self._wr_devices) | set(self._unwatched_devices)
        scope: set[frozenset[str]] = set()
        if bool(_knob("CAMERA_STREAM_DEAD_TWIN_RULE", False)):
            for group in set(self._groups.values()):
                if group & readers:
                    scope.add(group)
        if bool(_knob("CAMERA_STREAM_UNWATCHED_STAMPS_ENABLED", False)):
            for dev in self._unwatched_devices:
                if len(self.group_for(dev)) == 1:
                    scope.add(frozenset({dev}))
        return scope

    def _member_room_keys(self, group: frozenset[str]) -> list[tuple[str, str]]:
        return sorted({
            (room, eid) for room, eid, dev in self._room_inputs if dev in group
        })

    def _group_page_key(self, group: frozenset[str], er: Any, dr: Any) -> str | None:
        """The PURE page key of the group (never the map): the Frigate
        member's page_camera_key, else the device's own."""
        frig = _csh.frigate_member(er, group)
        dev = frig or (sorted(group)[0] if group else None)
        return _csh.page_camera_key(er, dr, dev)

    def _room_s1_latched(self, group: frozenset[str]) -> bool:
        """A member device's room S1 page ``(room, input)`` is sent and not
        recovered (any date)."""
        from ._stuck_signal_nm import stuck_signal_notified  # noqa: PLC0415
        return any(
            stuck_signal_notified(NM_KIND_S1, (room, eid))
            for room, eid in self._member_room_keys(group)
        )

    def _any_latched(self, key: str | None, group: frozenset[str]) -> bool:
        """Any page of the group still unrecovered: its S2 / owner S1 key or
        a member room S1 key (the LOW duty of a takeover)."""
        from ._stuck_signal_nm import stuck_signal_notified  # noqa: PLC0415
        if key and (
            stuck_signal_notified(NM_KIND_S2, (key,))
            or stuck_signal_notified(NM_KIND_S1, (GROUP_S1_KEY, key))
        ):
            return True
        return self._room_s1_latched(group)

    def _start_episode(
        self, group: frozenset[str], now: datetime, er: Any, dr: Any,
        *, adopted: bool = False,
    ) -> dict[str, Any]:
        key = self._group_page_key(group, er, dr)
        ep = {
            "members": group, "page_key": key, "started": now,
            "false_since": None, "adopted": adopted,
        }
        # Owner start / takeover (§6.6 Keys): a member room's S1 page
        # (room, input) still unrecovered is THIS episode's HIGH (no second
        # HIGH under the different owner S1 key); its LOW is sent at the
        # episode end. A room-sent S2 under the same pure key needs no
        # adoption: the owner's send reads ALREADY_SENT.
        if self._room_s1_latched(group):
            self._group_high_sent[group] = True
        self._episodes[group] = ep
        return ep

    def _evaluate_groups(self, now: datetime, er: Any, dr: Any) -> None:
        caps = _positive_caps()
        cap = min(caps) if caps else None
        nm_after = float(_knob("CAMERA_INPUT_STREAM_DEAD_NM_AFTER_S", 0.0))
        grace = float(_knob("CAMERA_INPUT_STREAM_DEAD_GRACE_S", 120.0))
        scope = self._scope_groups()
        # Dissolve: an episode whose group is no longer a current group.
        for group, ep in list(self._episodes.items()):
            current = self.group_for(sorted(group)[0])
            if current != group:
                self._end_episode(group, ep, now, er, dissolve=True)
        groups = scope | set(self._episodes)
        for group in groups:
            for dev in group:
                self._update_loss(dev, now, er)
        if self._adoption_sweep_due:
            self._adoption_sweep_due = False
            for group in scope:
                if group not in self._episodes and self._any_latched(
                    self._group_page_key(group, er, dr), group,
                ):
                    ep = self._start_episode(group, now, er, dr, adopted=True)
                    if self._group_alive(group):
                        ep["false_since"] = now
        today = now.date().isoformat()
        for group in sorted(groups, key=lambda g: sorted(g)):
            dead = self._group_dead(group, now)
            ep = self._episodes.get(group)
            if dead:
                if ep is None:
                    ep = self._start_episode(group, now, er, dr)
                ep["false_since"] = None
            elif ep is not None and self._group_alive(group):
                # The gate is False because a member is LIVE (not merely not
                # yet lost: a fresh owner's stamps need one grace to mature,
                # and that unknown stretch must not end a takeover episode).
                if ep["false_since"] is None:
                    ep["false_since"] = now
                if (now - ep["false_since"]).total_seconds() >= grace:
                    self._end_episode(group, ep, now, er)
            if group not in scope:
                continue  # no reader: never pages
            if cap is not None:
                self._maybe_send_s2(group, now, cap, er, dr)
            else:
                self._maybe_send_s1(group, now, nm_after, today, er, dr)
            if len(group) > 1:
                self._member_notices(group, dead, now, cap, grace, er, today)

    def _ensure_episode(
        self, group: frozenset[str], now: datetime, er: Any, dr: Any,
    ) -> dict[str, Any]:
        ep = self._episodes.get(group)
        if ep is None:
            ep = self._start_episode(group, now, er, dr)
        return ep

    def _maybe_send_s2(
        self, group: frozenset[str], now: datetime, cap: float, er: Any,
        dr: Any,
    ) -> None:
        """HIGH S2 once per group episode: only while EVERY member device is
        lost (the group gate) and the LATEST member's loss stamp + the cap
        has passed (a short blip of the live twin never pages)."""
        if self._group_high_sent.get(group):
            return
        if not self._group_dead(group, now):
            return
        latest = max(self._notlive_since.get(d, now) for d in group)
        if (now - latest).total_seconds() < cap:
            return
        ep = self._ensure_episode(group, now, er, dr)
        key = ep["page_key"]
        ident = f"high:{key}"
        if not key or ident in self._inflight:
            return
        mins = int((now - latest).total_seconds() // 60)
        self._send(
            ident, lambda: self._group_high_sent.__setitem__(group, True),
            kind=NM_KIND_S2, key=(key,),
            diagnosis=(
                f"Every NVR has lost {key} for {mins} min; its URA inputs "
                f"are released."
            ),
            remedy="check the camera's power / network and its NVRs",
            title_override=f"Camera dead {mins} min: {key}",
            exclusion_engaged=True, severity="HIGH",
        )

    def _maybe_send_s1(
        self, group: frozenset[str], now: datetime, nm_after: float,
        today: str, er: Any, dr: Any,
    ) -> None:
        """Both caps 0: HIGH S1 at the latest loss stamp + NM_AFTER, once per
        group per local day, only while EVERY member device is lost. With
        any positive cap the owner never sends S1."""
        if nm_after <= 0 or self._group_high_sent.get(group):
            return
        if self._s1_day.get(group) == today:
            return
        if not self._group_dead(group, now):
            return
        latest = max(self._notlive_since.get(d, now) for d in group)
        if (now - latest).total_seconds() < nm_after:
            return
        ep = self._ensure_episode(group, now, er, dr)
        key = ep["page_key"]
        ident = f"high:{key}"
        if not key or ident in self._inflight:
            return

        def _done() -> None:
            self._group_high_sent[group] = True
            self._s1_day[group] = today

        self._send(
            ident, _done, kind=NM_KIND_S1, key=(GROUP_S1_KEY, key),
            diagnosis=(
                f"Every NVR has lost {key} since {latest.isoformat()}; its URA "
                f"inputs no longer count."
            ),
            remedy="restart the camera or its NVRs",
            title_override=f"Camera stream dead: {key}",
            exclusion_engaged=True, severity="HIGH",
        )

    def _member_notices(
        self, group: frozenset[str], dead: bool, now: datetime,
        cap: float | None, grace: float, er: Any, today: str,
    ) -> None:
        """MEDIUM once per member device episode: the member's LOSS stamp +
        min(positive caps) passed while the group is not physically dead
        (one NVR down, the other covering). The member episode ends when the
        member is live for one grace (then its LOW)."""
        ep = self._episodes.get(group)
        key = (ep or {}).get("page_key")
        for dev in sorted(group):
            st = self._member_medium.get(dev)
            live_since = self._live_since.get(dev)
            if live_since is not None:
                if st is not None and (now - live_since).total_seconds() >= grace:
                    self._member_medium.pop(dev, None)
                    if st.get("sent"):
                        self._recover(
                            NM_KIND_TWIN_COVERING, (st["key"],),
                            f"{st['camera']} is visible again on "
                            f"{_nvr_name(er, dev)}",
                        )
                continue
            if st is None:
                st = {"sent": False}
                self._member_medium[dev] = st
            if (
                dead or cap is None or st.get("sent")
                or not bool(_knob("CAMERA_STREAM_TWIN_COVERING_NOTICE_ENABLED", False))
                or not self._lost(dev, now)
            ):
                continue
            since = self._notlive_since.get(dev, now)
            if (now - since).total_seconds() < cap:
                continue
            own = _csh.own_camera_entity_for_device(er, dev) or dev
            camera = key or self._group_page_key(group, er, self._registries()[1]) or own
            others = [d for d in sorted(group) if d != dev]
            ident = f"medium:{own}"
            if ident in self._inflight:
                continue
            st["key"] = own
            st["camera"] = camera

            def _done(_st=st) -> None:
                _st["sent"] = True

            self._send(
                ident, _done, kind=NM_KIND_TWIN_COVERING, key=(own,),
                diagnosis=(
                    f"{_nvr_name(er, dev)} has lost {camera}; "
                    f"{', '.join(_nvr_name(er, o) for o in others)} still "
                    f"sees it."
                ),
                remedy="check that NVR's connection to the camera",
                title_override=f"NVR down, twin covering: {camera}",
                severity="MEDIUM",
            )

    def _end_episode(
        self, group: frozenset[str], ep: dict[str, Any], now: datetime,
        er: Any, *, dissolve: bool = False,
    ) -> None:
        """Whoever owns the outage at its end sends its LOW, whoever sent
        the HIGH: the group's S2 key, the owner S1 key and every member
        room S1 key (each a no-op when nothing was latched)."""
        self._episodes.pop(group, None)
        self._group_high_sent.pop(group, None)
        key = ep.get("page_key")
        if dissolve:
            message = f"{key} is now watched per NVR; pages follow per device"
        else:
            live = [d for d in sorted(group) if not self._lost(d, now)]
            down = [d for d in sorted(group) if self._lost(d, now)]
            message = f"{key} is visible again on " + ", ".join(
                _nvr_name(er, d) for d in live
            )
            if down:
                message += "; " + ", ".join(
                    _nvr_name(er, d) for d in down
                ) + " still down"
        if key:
            self._recover(NM_KIND_S2, (key,), message)
            self._recover(NM_KIND_S1, (GROUP_S1_KEY, key), message)
        for room, eid in self._member_room_keys(group):
            self._recover(NM_KIND_S1, (room, eid), message)

    # ------------------------------------------------------------------
    # Send plumbing (latch after send)
    # ------------------------------------------------------------------

    def _send(self, ident: str, on_sent: Callable[[], None], **kwargs: Any) -> None:
        if self.torn_down or ident in self._inflight:
            return
        self._inflight.add(ident)
        self._track(self._send_task(ident, on_sent, kwargs))

    async def _send_task(
        self, ident: str, on_sent: Callable[[], None], kwargs: dict,
    ) -> None:
        from ._stuck_signal_nm import (  # noqa: PLC0415
            ALREADY_SENT,
            NOT_SENT,
            SENT,
            fire_stuck_signal_ex,
        )
        try:
            result = await fire_stuck_signal_ex(self.hass, **kwargs)
        except Exception:  # noqa: BLE001
            result = NOT_SENT
        self._inflight.discard(ident)
        self.last_results[ident] = result
        if result in (SENT, ALREADY_SENT):
            if result == SENT:
                kind = str(kwargs.get("kind"))
                self.page_counts[kind] = self.page_counts.get(kind, 0) + 1
            if not self.torn_down:
                on_sent()

    def _recover(self, kind: str, key: tuple, message: str) -> None:
        if self.torn_down:
            return

        async def _go() -> None:
            from ._stuck_signal_nm import (  # noqa: PLC0415
                fire_stuck_signal_recovered,
            )
            try:
                await fire_stuck_signal_recovered(
                    self.hass, kind=kind, key=key, message=message,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug("camera twin health recovery raised", exc_info=True)

        self._track(_go())

    def _track(self, coro: Any) -> None:
        try:
            task = self.hass.async_create_task(coro)
        except Exception:  # noqa: BLE001
            try:
                coro.close()
            except Exception:  # noqa: BLE001
                pass
            return
        try:
            self._tasks.add(task)
            done = getattr(task, "add_done_callback", None)
            if callable(done):
                done(self._tasks.discard)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Diagnostics (§6.9; the D5 download carries this under
    # ``camera_twin_health``). No entity attribute.
    # ------------------------------------------------------------------

    def get_diagnostics(self) -> dict[str, Any]:
        now = self._clock()
        return {
            "map_ready": self.map_ready,
            "map_stale_since": (
                self._map_stale_since.isoformat() if self._map_stale_since else None
            ),
            "builds": self._build_count,
            "build_failures": self._build_failures,
            "pairs_admitted": [list(p) for p in self._admitted],
            "pairs_rejected": [list(p) for p in self._rejected],
            "watched_devices": len(self._wr_devices),
            "unwatched": sorted(self._unwatched),
            "sticky": {
                e: u.isoformat() for e, u in sorted(self._sticky_until.items())
                if u > now
            },
            "house_tracker_stamps": self._unwatched_tracker.dead_stamps(),
            "loss_stamps": {
                d: s.isoformat() for d, s in sorted(self._notlive_since.items())
            },
            "group_episodes": [
                {
                    "members": sorted(g), "page_key": ep.get("page_key"),
                    "started": ep["started"].isoformat(),
                    "high_sent": bool(self._group_high_sent.get(g)),
                    "adopted": bool(ep.get("adopted")),
                }
                for g, ep in sorted(self._episodes.items(), key=lambda kv: sorted(kv[0]))
            ],
            "member_notices": {
                d: bool(st.get("sent")) for d, st in sorted(self._member_medium.items())
            },
            "page_counts": dict(self.page_counts),
            "last_send_results": dict(self.last_results),
        }


def _camera_devices(er: Any) -> frozenset[str]:
    """Every device that owns a camera entity (``had a camera``, rebuild
    filters)."""
    out: set[str] = set()
    try:
        entities = list(getattr(er, "entities", {}).values())
    except Exception:  # noqa: BLE001
        return frozenset()
    for ent in entities:
        eid = str(getattr(ent, "entity_id", "") or "")
        dev = getattr(ent, "device_id", None)
        if dev and eid.startswith("camera."):
            out.add(dev)
    return frozenset(out)


def _nvr_name(er: Any, device_id: str) -> str:
    plat = _csh.device_platform(er, device_id) if er is not None else None
    return _NVR_NAMES.get(plat or "", plat or "NVR")


def physical_camera_dead(hass: Any, entity_or_device: str) -> bool | None:
    """True iff EVERY paired NVR device has LOST the camera (§6.5). None =
    no owner. Read by the pages and the diagnostics only (no hold, view or
    anchor reads it)."""
    owner = _csh.twin_owner(hass)
    if owner is None:
        return None
    try:
        return owner.physical_camera_dead(entity_or_device)
    except Exception:  # noqa: BLE001
        return None


async def async_setup_camera_twin_health(hass: Any) -> CameraTwinHealth | None:
    """Create and start the one owner (coordinator-manager entry setup)."""
    data = hass.data.setdefault(_const.DOMAIN, {})
    old = data.get(_csh.TWIN_HEALTH_DATA_KEY)
    if old is not None:
        try:
            old.async_teardown()
        except Exception:  # noqa: BLE001
            pass
    owner = CameraTwinHealth(hass)
    data[_csh.TWIN_HEALTH_DATA_KEY] = owner
    await owner.async_setup()
    return owner


def async_teardown_camera_twin_health(hass: Any) -> None:
    """Coordinator-manager entry unload."""
    try:
        owner = (hass.data.get(_const.DOMAIN) or {}).get(_csh.TWIN_HEALTH_DATA_KEY)
    except Exception:  # noqa: BLE001
        owner = None
    if owner is not None:
        owner.async_teardown()
