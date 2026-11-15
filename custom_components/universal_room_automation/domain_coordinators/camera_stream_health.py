"""Camera input stream health, S1 room tier.

Plan: ``docs/planning/PLANNING_camera_input_stream_health.md`` (cards
PANEL-KS-HEALTH-AS-INPUT-1, CAMERA-STREAM-DEAD-ZONE-AND-CENSUS-1 for S2).
Ship 3b (``docs/planning/PLANNING_person_awareness_layer_ship3.md`` §6): with
``CAMERA_STREAM_DEVICE_LEVEL_INPUTS`` an input's "own camera" is its registry
camera DEVICE (live if any enabled camera entity on it reads live), page
latches are set only after a confirmed send, the pure page key
``page_camera_key`` is shared by rooms and the twin owner
(``camera_twin_health.CameraTwinHealth``), and the house readers fall back
to the owner's house tracker for cameras no room watches.

When a camera's stream is dead, the inputs that camera produces (e.g. a
Frigate person-occupancy sensor filed in a room's presence list) can freeze
``on`` for hours. This tracker answers one question per room input: has the
input's OWN camera entity (same device, exactly one enabled camera entity)
read ``unavailable`` for at least ``CAMERA_INPUT_STREAM_DEAD_GRACE_S``? The
room coordinator then promotes the input into its ``SensorExclusionSet``
under client ``camera_stream_dead`` (STEP-EXCLUDE-1: vote contributes 0).

Agnostic by construction: keyed on the camera ENTITY's availability, never on
a camera name, a kiosk app, or an NVR brand.

INV-STREAM: while a resolved input's camera entity has read ``unavailable``
continuously since first observed for >= the grace, the input is in
``dead_now``; unresolved inputs and the kill switch False never are (room
fusion byte-identical to pre-S1).

State vocabulary for the camera entity:
  * ``unavailable``            -> stamp ``since`` on first observation.
    "Continuously": if no ``unavailable`` reading was seen for longer than
    the grace (a no-opinion stretch), the stamp restarts at this reading.
  * ``unavailable`` with attribute ``restored: True`` -> no opinion: HA's
    placeholder for a registry entity whose integration has not loaded it
    (e.g. Frigate in setup retry), not a dead stream.
  * ``unknown`` or no state    -> no opinion: ``since`` neither set nor
    cleared, and the input is not dead this tick (INV needs ``unavailable``).
  * anything else              -> live: ``since`` cleared.

Watched inputs: the room's configured motion / presence / occupancy lists
(paged, shown on the sensor) plus ``extra_inputs``, the person sensors the
room's camera override reads (coordinator v3.5.1 camera override); those
are excluded the same way but never paged or shown, because they are not
configured inputs.

One public reader for the room and its siblings:
``UniversalRoomCoordinator.camera_input_stream_dead(input_eid)`` and its
camera-keyed form ``camera_stream_dead(camera_eid)``. S2 readers outside the
room (zone substrate / zone tracker, presence fan-interference gate, comfort
fan veto, census, a future NVR-witness layer) go through the house-level
functions at the bottom of this module, which only fold those room answers:
``input_stream_dead``, ``camera_stream_dead`` and ``entity_stream_dead``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Iterable

from .. import const as _const
from ..camera_resolver import CameraResolver

_LOGGER = logging.getLogger(__name__)

# SensorExclusionSet client name and stuck-signal NM kind (one vocabulary).
EXCLUSION_CLIENT = "camera_stream_dead"
NM_KIND = "camera_stream_dead"
# S2: one HIGH page per outage once a hold cap is passed (the camera's
# inputs are released): a camera dead this long is a hardware or host
# failure, not a normal outage. Key = (camera,), so rooms sharing a camera
# share one latch.
NM_KIND_HOLD_RELEASED = "camera_stream_hold_released"

_UNAVAILABLE = "unavailable"
_UNKNOWN = "unknown"




class CameraInputStreamHealth:
    """Per-room dead-stream tracker (RAM only; rebuilt on restart).

    Person-awareness ship 3b (§6.1, §6.2): with
    ``CAMERA_STREAM_DEVICE_LEVEL_INPUTS`` each watched input resolves to its
    registry CAMERA DEVICE (the "key"): live if any enabled camera entity on
    it reads live. Stamps, prunes and liveness are keyed by the device id;
    only ``dead[eid]`` carries the device's own canonical camera (first
    sorted enabled member), never a twin's camera or the page key. With the
    knob False the key is the input's own camera entity (exactly one camera
    on the device), exactly as before 3b.

    Latch after send (§6.6): ``evaluate`` returns page candidates only; the
    caller marks a page with ``mark_paged`` once its send returned SENT or
    ALREADY_SENT (``mark_not_sent`` otherwise), so a deferred or failed page
    is offered again on the next tick.
    """

    def __init__(self, room_name: str) -> None:
        self._room_name = room_name
        # input_eid -> (key | None, reason, camera_derived). The key is the
        # device id (device level) or the own camera entity (entity level).
        self._resolution: dict[str, tuple[str | None, str, bool]] | None = None
        self._resolution_inputs: tuple[str, ...] = ()
        self._resolution_device_level: bool | None = None
        # key -> its enabled camera entities, sorted (members[0] = the
        # key's own canonical camera). Re-read on every resolution rebuild.
        self._key_members: dict[str, tuple[str, ...]] = {}
        # Set by invalidate(): rebuild on the next tick, but keep answering
        # from the old resolution until then (the exclusion set still holds
        # this tick's promotions, so the getter must not read None).
        self._resolution_dirty = False
        # Configured inputs of the last tick (paging + display scope).
        self._configured: frozenset[str] = frozenset()
        # key -> first observed `unavailable` (DEAD-READ) time.
        self._unavail_since: dict[str, datetime] = {}
        # key -> last tick that read `unavailable` (continuity).
        self._unavail_seen: dict[str, datetime] = {}
        # Keys that read no-opinion since their last `unavailable`.
        self._gap_seen: set[str] = set()
        # input_eid -> (own camera, since): dead THIS tick.
        self._dead_now: dict[str, tuple[str, datetime]] = {}
        # input_eid -> key, for the dead inputs of this tick.
        self._dead_key: dict[str, str] = {}
        # S2 hold: dead inputs whose key has read `unavailable` for at
        # least CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S (the hold is over: the
        # input counts as off outside the room). Subset of _dead_now.
        self._hold_expired_now: frozenset[str] = frozenset()
        # Same for the census hold (CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S).
        self._census_hold_expired_now: frozenset[str] = frozenset()
        # Review D-M1 (unavailable together with its camera, e.g. a Protect
        # device disconnect marks every entity unavailable at once): an
        # input reading `unavailable` is held from t0 until a room tick has
        # seen its camera LIVE during that same unavailable episode (then it
        # is an ordinary sensor outage and counts as off). Keyed input ->
        # the input state's `last_changed` of the confirmed episode.
        self._plain_unavailable: dict[str, Any] = {}
        self._state_getter: Callable[[str], Any] | None = None
        self._enabled = False
        # Hold-release page: keys paged this outage -> (own camera, the
        # page key the send used; frozen for the episode); this tick's
        # candidates (own camera, since, cap_s) and recoveries (page key).
        self._hold_paged: dict[str, tuple[str, str]] = {}
        self.hold_pages: list[tuple[str, datetime, float]] = []
        self.hold_recoveries: list[str] = []
        # NM bookkeeping: inputs whose current episode paged; per-day latch.
        self._paged_episode: set[str] = set()
        self._paged_day: dict[str, str] = {}
        # Sends scheduled and not yet answered: (kind, ident) (no second
        # send while one is in flight; cleared by mark_paged / mark_not_sent).
        self._inflight: set[tuple[str, str]] = set()
        # Review A-L3: the latch key of each scheduled send, frozen at
        # begin_send ((kind, ident) -> pid), so a resolution rebuild inside
        # the send window cannot move the latch off the device key.
        self._send_pid: dict[tuple[str, str], str] = {}
        # Review D-M1: keys whose S2 hold page is due this tick (hold over,
        # not yet latched; in flight or not). The S1 loop skips them.
        self._hold_due_keys: frozenset[str] = frozenset()
        # Review D-L2: input -> the owner's group S1 page key this input's
        # S1 episode adopted (caps 0); its LOW recovers that key too.
        self._adopted_group_s1: dict[str, str] = {}
        self._warned_unresolved = False

    # ------------------------------------------------------------------
    # Resolution cache
    # ------------------------------------------------------------------

    def invalidate(self) -> None:
        """Mark the resolution cache stale (entity registry changed). The
        next tick rebuilds it; until then readers keep the old answer."""
        self._resolution_dirty = True

    def _ensure_resolution(
        self, inputs: tuple[str, ...], registry_getter: Callable[[], Any],
        configured: frozenset[str] = frozenset(),
    ) -> dict[str, tuple[str | None, str, bool]]:
        device_level = _device_level_inputs()
        if (
            self._resolution is not None
            and not self._resolution_dirty
            and inputs == self._resolution_inputs
            and device_level == self._resolution_device_level
        ):
            return self._resolution
        try:
            registry = registry_getter()
        except Exception:  # noqa: BLE001
            registry = None
        resolution: dict[str, tuple[str | None, str, bool]] = {}
        members: dict[str, tuple[str, ...]] = {}
        for eid in inputs:
            if registry is None:
                resolution[eid] = (None, "registry_error", False)
                continue
            if device_level:
                key, reason, derived, cams = resolve_input_device(registry, eid)
                resolution[eid] = (key, reason, derived)
                if key:
                    members[key] = cams
                continue
            cam, reason, derived = CameraResolver.own_camera_entity_for_input(
                registry, eid,
            )
            resolution[eid] = (cam, reason, derived)
            if cam:
                members[cam] = (cam,)
        self._resolution = resolution
        self._key_members = members
        self._resolution_inputs = inputs
        self._resolution_device_level = device_level
        self._resolution_dirty = False
        self._maybe_warn_unresolved(
            {e: v for e, v in resolution.items() if e in configured},
        )
        return resolution

    def _maybe_warn_unresolved(
        self, resolution: dict[str, tuple[str | None, str, bool]],
    ) -> None:
        """Silence check: a room listing a camera-derived input whose camera
        never resolves gets ONE WARNING per coordinator lifetime (healthy =
        zero exclusions, so a zero-fire page would be wrong)."""
        if self._warned_unresolved:
            return
        derived = [e for e, (_c, _r, d) in resolution.items() if d]
        resolved = [e for e, (c, _r, _d) in resolution.items() if c]
        if derived and not resolved:
            self._warned_unresolved = True
            _LOGGER.warning(
                "Room %s: camera-derived input(s) %s have no single camera "
                "entity on their device (%s); camera stream health cannot "
                "watch them",
                self._room_name, sorted(derived),
                {e: resolution[e][1] for e in sorted(derived)},
            )

    def _own_camera(self, key: str) -> str:
        """The key's own canonical camera (first sorted enabled member)."""
        cams = self._key_members.get(key) or ()
        return cams[0] if cams else key

    def _key_for_camera(self, camera_eid: str) -> str | None:
        """The watched key whose member set holds ``camera_eid`` (its own
        device), or None: never a twin's key."""
        if not camera_eid:
            return None
        for key, cams in self._key_members.items():
            if camera_eid in cams:
                return key
        return None

    def _key_reading(self, key: str, state_getter: Callable[[str], Any]) -> str | None:
        """One reading per key this tick (§6.1): a live state value if any
        member reads LIVE; ``unavailable`` if no member is LIVE and at least
        one reads DEAD-READ (``unavailable`` not restored); else None (no
        opinion: every member unknown / restored / missing)."""
        live: str | None = None
        dead_read = False
        for cam in self._key_members.get(key) or (key,):
            try:
                st = state_getter(cam)
            except Exception:  # noqa: BLE001
                st = None
            cls = member_reading(st)
            if cls == READING_LIVE:
                live = getattr(st, "state", None)
                break
            if cls == READING_DEAD:
                dead_read = True
        if live is not None:
            return live
        return _UNAVAILABLE if dead_read else None

    # ------------------------------------------------------------------
    # Per-tick evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        now: datetime,
        inputs: Iterable[str],
        state_getter: Callable[[str], Any],
        registry_getter: Callable[[], Any],
        extra_inputs: Iterable[str] = (),
    ) -> tuple[
        dict[str, tuple[str, datetime]],
        list[tuple[str, str, datetime]],
        list[tuple[str, str]],
    ]:
        """One room tick. Returns ``(dead_now, to_page, to_recover)``.

        ``dead_now``: input -> (own camera, since) to exclude this tick.
        ``to_page``: S1 candidates (input, camera, since) whose exclusion
        passed ``CAMERA_INPUT_STREAM_DEAD_NM_AFTER_S`` (once per episode, once
        per input per local day, once a send is confirmed: ``mark_paged``).
        ``to_recover``: (input, camera) whose paged episode ended this tick.
        Pages and recoveries cover configured ``inputs`` only;
        ``extra_inputs`` (camera override person sensors) can be in
        ``dead_now`` but never page S1.
        """
        ordered: list[str] = []
        for eid in inputs:
            if eid and eid not in ordered:
                ordered.append(eid)
        configured = frozenset(ordered)
        watched = list(ordered)
        for eid in extra_inputs or ():
            if eid and eid not in watched:
                watched.append(eid)
        self._configured = configured
        resolution = self._ensure_resolution(
            tuple(watched), registry_getter, configured,
        )

        enabled = bool(getattr(_const, "CAMERA_INPUT_STREAM_HEALTH_ENABLED", False))
        grace_s = float(getattr(_const, "CAMERA_INPUT_STREAM_DEAD_GRACE_S", 120.0))
        nm_after_s = float(
            getattr(_const, "CAMERA_INPUT_STREAM_DEAD_NM_AFTER_S", 0.0),
        )

        keys = {key for key, _r, _d in resolution.values() if key}
        # Prune stamps of keys no longer watched (config / registry change).
        for key in list(self._unavail_since):
            if key not in keys:
                self._unavail_since.pop(key, None)
                self._unavail_seen.pop(key, None)
                self._gap_seen.discard(key)
        key_state: dict[str, str | None] = {}
        for key in keys:
            value = self._key_reading(key, state_getter)
            key_state[key] = value
            if value is None or value == _UNKNOWN:
                if key in self._unavail_since:
                    self._gap_seen.add(key)
                continue  # no opinion
            if value == _UNAVAILABLE:
                last = self._unavail_seen.get(key)
                if key not in self._unavail_since or (
                    key in self._gap_seen
                    and last is not None
                    and (now - last).total_seconds() > grace_s
                ):
                    # First reading, or a no-opinion stretch longer than the
                    # grace broke continuity since the last one: restart.
                    self._unavail_since[key] = now
                self._unavail_seen[key] = now
                self._gap_seen.discard(key)
            else:
                self._unavail_since.pop(key, None)
                self._unavail_seen.pop(key, None)
                self._gap_seen.discard(key)

        dead: dict[str, tuple[str, datetime]] = {}
        dead_key: dict[str, str] = {}
        if enabled:
            for eid in watched:
                key = resolution.get(eid, (None, "", False))[0]
                # Dead ON A TICK only when this tick reads DEAD-READ (an
                # `unknown` / restored tick keeps the stamp but is not dead).
                if not key or key_state.get(key) != _UNAVAILABLE:
                    continue
                since = self._unavail_since.get(key)
                if since is None:
                    continue
                if (now - since).total_seconds() >= grace_s:
                    dead[eid] = (self._own_camera(key), since)
                    dead_key[eid] = key

        hold_s = float(
            getattr(_const, "CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S", 0.0),
        )
        census_hold_s = float(
            getattr(_const, "CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S", 0.0),
        )
        # hold 0 (no hold): every dead input is released at once.
        self._hold_expired_now = frozenset(
            eid for eid, (_cam, since) in dead.items()
            if (now - since).total_seconds() >= hold_s
        )
        self._census_hold_expired_now = frozenset(
            eid for eid, (_cam, since) in dead.items()
            if (now - since).total_seconds() >= census_hold_s
        )
        self._dead_key = dead_key
        # Hold-release pages first, so the S1 per-input page below can see
        # which keys already paged this outage (one HIGH page per outage).
        self._evaluate_hold_pages(dead, hold_s, census_hold_s)

        to_page: list[tuple[str, str, datetime]] = []
        today = now.date().isoformat()
        if nm_after_s > 0:
            for eid, (cam, since) in dead.items():
                if eid not in configured:
                    continue  # override sensor: excluded, never paged
                if eid in self._paged_episode:
                    continue
                if dead_key.get(eid) in self._hold_paged:
                    # This camera already sent the S2 hold-release page in
                    # this outage: no second HIGH page for its inputs.
                    continue
                if dead_key.get(eid) in self._hold_due_keys:
                    # Review D-M1: its S2 page is due THIS tick (or in
                    # flight / not yet confirmed): that is the outage's one
                    # HIGH; the latch-after-send S2 latch is not set yet.
                    continue
                if self._paged_day.get(eid) == today:
                    continue
                if (NM_KIND, eid) in self._inflight:
                    continue
                if (now - since).total_seconds() >= nm_after_s:
                    to_page.append((eid, cam, since))

        to_recover: list[tuple[str, str]] = []
        for eid in sorted(self._paged_episode):
            if eid not in configured:
                # Input removed from the room mid-episode: drop silently
                # (no "counts again" for an input that no longer exists).
                self._paged_episode.discard(eid)
                self._adopted_group_s1.pop(eid, None)
                continue
            if eid not in dead:
                prev = self._dead_now.get(eid)
                to_recover.append((eid, prev[0] if prev else ""))
                self._paged_episode.discard(eid)

        self._dead_now = dead
        self._state_getter = state_getter
        self._enabled = enabled
        self._classify_unavailable_inputs(
            watched, resolution, key_state, state_getter, enabled,
        )
        return dict(dead), to_page, to_recover

    def _classify_unavailable_inputs(
        self, watched, resolution, key_state, state_getter, enabled,
    ) -> None:
        """Review D-M1: for each resolved input reading ``unavailable``, a
        tick that sees its camera LIVE confirms an ordinary sensor outage
        for that episode (the input then counts as off); otherwise (camera
        unavailable, or not seen yet) it stays held from t0. Under device
        level "its camera" is its DEVICE, looked up by the same key it was
        stamped with: held only while the device is DEAD-READ this tick (no
        member LIVE, at least one `unavailable` and not restored)."""
        newly_plain: set[str] = set()
        for eid in watched:
            key = resolution.get(eid, (None, "", False))[0]
            st = _safe_state(state_getter, eid)
            if (
                not enabled or not key or st is None
                or getattr(st, "state", None) != _UNAVAILABLE or _is_restored(st)
            ):
                self._plain_unavailable.pop(eid, None)
                continue
            episode = getattr(st, "last_changed", None)
            if key_state.get(key) != _UNAVAILABLE:
                # Camera live, or no opinion (unknown / restored / missing):
                # an ordinary sensor outage. Only a camera that reads
                # `unavailable` keeps it held, and that camera turns dead at
                # the grace, so the hold is bounded by the caps.
                if self._plain_unavailable.get(eid, _MISSING) != episode:
                    # Held at its event until now: the substrate must
                    # re-read it (no event will come).
                    newly_plain.add(eid)
                self._plain_unavailable[eid] = episode
                continue
            if self._plain_unavailable.get(eid, _MISSING) == episode:
                continue  # confirmed plain earlier this episode
            self._plain_unavailable.pop(eid, None)
        self._newly_plain_now = frozenset(newly_plain)

    @property
    def newly_plain_now(self) -> frozenset[str]:
        """Inputs confirmed an ordinary sensor outage at this tick (they were
        held from their unavailable event; flip set for the substrate)."""
        return getattr(self, "_newly_plain_now", frozenset())

    def _evaluate_hold_pages(
        self, dead: dict[str, tuple[str, datetime]], hold_s: float,
        census_hold_s: float,
    ) -> None:
        """One HIGH page per key per outage once the first positive hold
        cap is passed (its inputs are released somewhere); a LOW recovery
        when the key has no dead input any more. Caps 0 = no hold = no
        page (a 2-min blip must not page). Candidates only: the latch is
        set by ``mark_paged`` after a confirmed send."""
        self.hold_pages = []
        self.hold_recoveries = []
        caps = [c for c in (hold_s, census_hold_s) if c > 0]
        due: set[str] = set()
        dead_keys: dict[str, tuple[str, datetime]] = {}
        for eid, (cam, since) in dead.items():
            key = self._dead_key.get(eid, cam)
            if key not in dead_keys or since < dead_keys[key][1]:
                dead_keys[key] = (cam, since)
        if caps:
            cap = min(caps)
            for key, (cam, since) in sorted(dead_keys.items()):
                if key in self._hold_paged:
                    continue
                if not any(
                    eid in self._hold_expired_now
                    or eid in self._census_hold_expired_now
                    for eid, k in self._dead_key.items() if k == key
                ):
                    continue
                due.add(key)
                if (NM_KIND_HOLD_RELEASED, key) in self._inflight:
                    continue
                self.hold_pages.append((cam, since, cap))
        self._hold_due_keys = frozenset(due)
        for key in sorted(self._hold_paged):
            if key not in dead_keys:
                _cam, page_key = self._hold_paged.pop(key)
                self.hold_recoveries.append(page_key)

    # ------------------------------------------------------------------
    # Latch after send (§6.6)
    # ------------------------------------------------------------------

    def _page_ident(self, kind: str, ident: str) -> str:
        """S1 pages are keyed by input; S2 hold pages by key (an own camera
        given by the caller is mapped to its key)."""
        if kind == NM_KIND_HOLD_RELEASED:
            return self._key_for_camera(ident) or ident
        return ident

    def begin_send(self, kind: str, ident: str) -> None:
        """A send for this candidate is scheduled (no second one meanwhile).
        The latch key is frozen here (review A-L3)."""
        pid = self._page_ident(kind, ident)
        self._send_pid[(kind, ident)] = pid
        self._inflight.add((kind, pid))

    def _frozen_pid(self, kind: str, ident: str) -> str:
        pid = self._send_pid.pop((kind, ident), None)
        return pid if pid is not None else self._page_ident(kind, ident)

    def mark_paged(
        self, kind: str, ident: str, today: str, page_key: str | None = None,
    ) -> None:
        """The send returned SENT or ALREADY_SENT: set the latches. S1
        (``NM_KIND``): the input's episode + per-day latch. S2
        (``NM_KIND_HOLD_RELEASED``): the key's hold-page latch, remembering
        the page key the send used (its LOW uses the same key)."""
        pid = self._frozen_pid(kind, ident)
        self._inflight.discard((kind, pid))
        if kind == NM_KIND_HOLD_RELEASED:
            self._hold_paged[pid] = (ident, page_key or ident)
            return
        self._paged_episode.add(pid)
        self._paged_day[pid] = today

    def mark_not_sent(self, kind: str, ident: str) -> None:
        """The send returned NOT_SENT: no latch; the candidate comes back on
        the next tick."""
        self._inflight.discard((kind, self._frozen_pid(kind, ident)))

    def adopt_group_s1(self, input_eid: str, today: str, group_key: str) -> None:
        """Review D-L2 (caps 0): the owner already sent the group S1 page
        ``(GROUP_S1_KEY, group_key)`` for this input's device: latch the
        input's S1 episode (no second HIGH) and remember the key, so this
        room sends that LOW if it owns the outage at its end."""
        self._paged_episode.add(input_eid)
        self._paged_day[input_eid] = today
        self._adopted_group_s1[input_eid] = group_key

    def pop_adopted_group_s1(self, input_eid: str) -> str | None:
        """The group S1 key the input's ended episode adopted, if any."""
        return self._adopted_group_s1.pop(input_eid, None)

    @property
    def hold_expired_now(self) -> frozenset[str]:
        """Dead inputs whose S2 hold is over this tick (see evaluate)."""
        return self._hold_expired_now

    # ------------------------------------------------------------------
    # Readers
    # ------------------------------------------------------------------

    def is_dead(self, input_eid: str) -> bool | None:
        """None = unresolved / not one of this room's inputs; else whether
        the input is excluded as dead-stream this tick."""
        if self._resolution is None:
            return None
        res = self._resolution.get(input_eid)
        if res is None or not res[0]:
            return None
        return input_eid in self._dead_now

    def camera_is_dead(self, camera_eid: str) -> bool | None:
        """Camera-keyed form of the same evaluation (S2). None = this room
        does not watch that camera (no input of it resolves to a key whose
        members hold it); True iff an input of THAT key (its own device under
        device level, never a twin) is dead this tick; False otherwise
        (always False with the kill switch off)."""
        if self._resolution is None or not camera_eid:
            return None
        key = self._key_for_camera(camera_eid)
        if key is None:
            return None
        return any(k == key for k in self._dead_key.values())

    def is_hold_expired(
        self, input_eid: str, census: bool = False,
    ) -> bool | None:
        """S2 hold reader. None = unresolved / not this room's input; True
        iff the input is dead AND its hold (the zone cap, or the census cap
        with ``census``) is over this tick."""
        if self.is_dead(input_eid) is None:
            return None
        expired = (
            self._census_hold_expired_now if census else self._hold_expired_now
        )
        return input_eid in expired

    def camera_hold_expired(
        self, camera_eid: str, census: bool = False,
    ) -> bool | None:
        """Camera-keyed form of ``is_hold_expired``: None = not watched;
        True iff an input of that camera's key is dead with its hold over."""
        if self.camera_is_dead(camera_eid) is None:
            return None
        key = self._key_for_camera(camera_eid)
        expired = (
            self._census_hold_expired_now if census else self._hold_expired_now
        )
        return any(
            k == key and eid in expired for eid, k in self._dead_key.items()
        )

    def is_unavailable_held(self, input_eid: str) -> bool | None:
        """Review D-M1, read at call time (event time). None = unresolved /
        not this room's input. True iff the input reads ``unavailable``
        now (not a restored placeholder) and no room tick has seen its
        camera live during this unavailable episode: an input that went
        unavailable together with its camera is held from t0, never read
        as off during the grace. Always False with the kill switch off."""
        if self.is_dead(input_eid) is None:
            return None
        if not self._enabled or self._state_getter is None:
            return False
        st = _safe_state(self._state_getter, input_eid)
        if (
            st is None or getattr(st, "state", None) != _UNAVAILABLE
            or _is_restored(st)
        ):
            return False
        confirmed = self._plain_unavailable.get(input_eid, _MISSING)
        return confirmed != getattr(st, "last_changed", None)

    def clear_state_getter(self) -> None:
        """Teardown hygiene: drop the held ``hass.states.get`` reference."""
        self._state_getter = None

    def watched_inputs(self) -> tuple[str, ...]:
        """The inputs of the current resolution (diagnostics)."""
        return tuple(self._resolution_inputs)

    def dead_stamps(self) -> dict[str, str]:
        """key -> first `unavailable` stamp (ISO), for diagnostics."""
        return {k: v.isoformat() for k, v in sorted(self._unavail_since.items())}

    def snapshot(self) -> dict[str, Any]:
        """Display surface for ``sensor.<room>_unavailable_entities``."""
        resolution = self._resolution or {}
        configured = self._configured
        return {
            "camera_stream_dead_inputs": {
                eid: {"camera": cam, "since": since.isoformat()}
                for eid, (cam, since) in sorted(self._dead_now.items())
                if eid in configured
            },
            "camera_stream_inputs_resolved": sum(
                1 for eid, (cam, _r, _d) in resolution.items()
                if cam and eid in configured
            ),
        }


# ----------------------------------------------------------------------
# Person-awareness ship 3b: device liveness, twin pairing, page keys
# (PLANNING_person_awareness_layer_ship3.md §6.1). Pure registry functions:
# never inferred from an entity-id string.
# ----------------------------------------------------------------------

# Per member reading (§6.1).
READING_LIVE = "live"
READING_DEAD = "dead_read"
READING_NO_OPINION = "no_opinion"

# The owner (CameraTwinHealth) key in hass.data[DOMAIN]. Kept as a constant
# so readers and the owner agree; the owner object carries no attribute a
# room-coordinator scan matches (see _room_coordinators).
TWIN_HEALTH_DATA_KEY = "camera_twin_health"

# NVR platforms a Frigate camera may be twinned with (§6.4).
NVR_TWIN_PLATFORMS: frozenset[str] = frozenset(
    {"unifiprotect", "reolink", "amcrest", "dahua"},
)
_FRIGATE_PLATFORM = "frigate"


def _device_level_inputs() -> bool:
    return bool(getattr(_const, "CAMERA_STREAM_DEVICE_LEVEL_INPUTS", False))


def member_reading(state: Any) -> str:
    """LIVE = a real state other than ``unavailable`` / ``unknown``;
    DEAD-READ = ``unavailable`` without ``restored: True``; NO-OPINION =
    ``unknown``, a restored placeholder, or no state."""
    value = getattr(state, "state", None) if state is not None else None
    if value is None or value == _UNKNOWN:
        return READING_NO_OPINION
    if value == _UNAVAILABLE:
        return READING_NO_OPINION if _is_restored(state) else READING_DEAD
    return READING_LIVE


def device_camera_members(entity_registry: Any, device_id: str | None) -> tuple[str, ...]:
    """The device's enabled ``camera.*`` entities, sorted. () on any miss."""
    if not device_id:
        return ()
    try:
        return CameraResolver.enabled_camera_entities_for_device(
            entity_registry, device_id,
        )
    except Exception:  # noqa: BLE001
        return ()


def camera_device_for_entity(entity_registry: Any, entity_id: str) -> str | None:
    """The entity's registry ``device_id`` when that device has at least one
    ENABLED ``camera.*`` entity, else None (never from the entity id)."""
    try:
        entry = entity_registry.async_get(entity_id)
    except Exception:  # noqa: BLE001
        return None
    device_id = getattr(entry, "device_id", None) if entry is not None else None
    if not device_id:
        return None
    return device_id if device_camera_members(entity_registry, device_id) else None


def own_camera_entity_for_device(entity_registry: Any, device_id: str | None) -> str | None:
    """The device's own canonical camera: its first sorted enabled camera
    entity. The READER key (dead maps, camera getters, exclusion reasons)."""
    cams = device_camera_members(entity_registry, device_id)
    return cams[0] if cams else None


def resolve_input_device(
    entity_registry: Any, entity_id: str,
) -> tuple[str | None, str, bool, tuple[str, ...]]:
    """Device-level resolution of one watched input: ``(device_id | None,
    reason, camera_derived, members)``; reasons as
    ``CameraResolver.own_camera_entity_for_input`` minus ``multi_camera``
    (a multi-camera device resolves)."""
    try:
        entry = entity_registry.async_get(entity_id)
    except Exception:  # noqa: BLE001
        return None, "registry_error", False, ()
    if entry is None:
        return None, "no_registry_entry", False, ()
    platform = getattr(entry, "platform", None)
    camera_platform = platform in ({_FRIGATE_PLATFORM} | NVR_TWIN_PLATFORMS)
    device_id = getattr(entry, "device_id", None)
    if not device_id:
        return None, "no_device", camera_platform, ()
    try:
        cams = CameraResolver.enabled_camera_entities_for_device(
            entity_registry, device_id,
        )
    except Exception:  # noqa: BLE001
        return None, "registry_error", camera_platform, ()
    if not cams:
        return None, "no_camera", camera_platform, ()
    return device_id, "resolved", True, tuple(cams)


def _camera_platforms(entity_registry: Any, cams: Iterable[str]) -> list[str | None]:
    out: list[str | None] = []
    for cam in cams:
        try:
            ent = entity_registry.async_get(cam)
        except Exception:  # noqa: BLE001
            ent = None
        out.append(getattr(ent, "platform", None) if ent is not None else None)
    return out


def device_platform(entity_registry: Any, device_id: str | None) -> str | None:
    """The registry platform of the device's camera entities (all equal for
    an NVR device), or None (display: the NVR name in a page)."""
    plats = {p for p in _camera_platforms(
        entity_registry, device_camera_members(entity_registry, device_id),
    ) if p}
    return next(iter(plats)) if len(plats) == 1 else None


def twin_pair_admissible(
    entity_registry: Any, frigate_device: str, sibling_device: str,
) -> bool:
    """§6.4 NVR-platform check: every enabled camera entity on the Frigate
    device has registry platform ``frigate``, every enabled camera entity on
    the sibling has a platform in NVR_TWIN_PLATFORMS, and each side has at
    least one enabled camera entity (so "every" is never vacuous)."""
    f_cams = device_camera_members(entity_registry, frigate_device)
    s_cams = device_camera_members(entity_registry, sibling_device)
    if not f_cams or not s_cams:
        return False
    if any(p != _FRIGATE_PLATFORM for p in _camera_platforms(entity_registry, f_cams)):
        return False
    return all(
        p in NVR_TWIN_PLATFORMS for p in _camera_platforms(entity_registry, s_cams)
    )


def build_twin_map(
    entity_registry: Any, device_registry: Any,
) -> tuple[dict[str, frozenset[str]], list[tuple[str, str]], list[tuple[str, str]]]:
    """The device twin map from ONE fresh ``CameraResolver`` (W1 pairing,
    ``frigate_object_name_pairs``) plus the NVR-platform check. Returns
    ``(groups, admitted, rejected)``: ``groups`` maps every member device of
    an admitted pair (both directions) to the pair. Honours
    ``CAMERA_STREAM_DEAD_TWIN_RULE`` (False = no pairs). Raises on a
    registry error (the owner keeps its previous map)."""
    if not bool(getattr(_const, "CAMERA_STREAM_DEAD_TWIN_RULE", False)):
        return {}, [], []
    # CameraResolver swallows a failed registry walk (WARN + empty index),
    # which would silently empty the map; read both registries first so a
    # registry error RAISES here and the owner keeps its previous map.
    list(getattr(device_registry, "devices").values())
    list(getattr(entity_registry, "entities").values())
    resolver = CameraResolver(entity_registry, device_registry)
    groups: dict[str, frozenset[str]] = {}
    admitted: list[tuple[str, str]] = []
    rejected: list[tuple[str, str]] = []
    for frig, sib in sorted(resolver.frigate_object_name_pairs().items()):
        if twin_pair_admissible(entity_registry, frig, sib):
            pair = frozenset({frig, sib})
            groups[frig] = pair
            groups[sib] = pair
            admitted.append((frig, sib))
        else:
            rejected.append((frig, sib))
    return groups, admitted, rejected


def pure_twin_groups(
    entity_registry: Any, device_registry: Any,
) -> dict[str, frozenset[str]]:
    """The PURE pairing (``build_twin_map`` groups) for this registry
    state; {} with no device registry or on any error. Callers that need
    many page keys in one pass compute it once and pass it as ``groups``
    (review B-L5); it is never the owner's map."""
    if device_registry is None:
        return {}
    try:
        groups, _a, _r = build_twin_map(entity_registry, device_registry)
    except Exception:  # noqa: BLE001
        return {}
    return groups


def twin_pair_for_device(
    entity_registry: Any, device_registry: Any, device_id: str,
    *, groups: dict[str, frozenset[str]] | None = None,
) -> frozenset[str]:
    """The device's group by the PURE pairing rule (the same function the
    map build calls): the device plus its admitted W1 twin, or the device
    alone. Computable with the owner absent. {device} on any error.
    ``groups``: a ``pure_twin_groups`` result for the same registry state."""
    if not device_id:
        return frozenset()
    if groups is None:
        groups = pure_twin_groups(entity_registry, device_registry)
    return groups.get(device_id, frozenset({device_id}))


def frigate_member(entity_registry: Any, group: Iterable[str]) -> str | None:
    """The member device whose camera entities are on the Frigate platform."""
    for dev in sorted(group):
        plats = _camera_platforms(
            entity_registry, device_camera_members(entity_registry, dev),
        )
        if plats and all(p == _FRIGATE_PLATFORM for p in plats):
            return dev
    return None


def page_camera_key(
    entity_registry: Any, device_registry: Any, device_id: str | None,
    *, groups: dict[str, frozenset[str]] | None = None,
) -> str | None:
    """THE stuck-signal PAGE key (§6.1), used only where a page is sent or
    recovered: the Frigate device's camera for a device that
    ``twin_pair_for_device`` pairs, else ``own_camera_entity_for_device``.
    Pure, so rooms and the owner agree, owner present or not."""
    if not device_id:
        return None
    group = twin_pair_for_device(
        entity_registry, device_registry, device_id, groups=groups,
    )
    if len(group) > 1:
        frig = frigate_member(entity_registry, group)
        if frig:
            return own_camera_entity_for_device(entity_registry, frig)
    return own_camera_entity_for_device(entity_registry, device_id)


def camera_override_person_sensors(hass: Any, area_id: str | None) -> list[str]:
    """The person sensors the v3.5.1 room camera override reads for an area
    (the camera manager's area lookup). [] on any miss."""
    if not area_id:
        return []
    try:
        from ..const import DOMAIN  # noqa: PLC0415
        camera_manager = (hass.data.get(DOMAIN) or {}).get("camera_manager")
        if not camera_manager:
            return []
        return list(camera_manager.get_person_sensor_for_area(area_id) or [])
    except Exception:  # noqa: BLE001
        return []


def is_room_entry(entry: Any) -> bool:
    data = getattr(entry, "data", {}) or {}
    etype = data.get(_const.CONF_ENTRY_TYPE)
    if etype == _const.ENTRY_TYPE_ROOM:
        return True
    return etype is None and bool(data.get(_const.CONF_ROOM_NAME))


def room_stream_input_entities(
    hass: Any, entry: Any,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """THE one room-input list (§6.3, contract §2.6): ``(room_name,
    configured, extras)`` from the room config entry (motion / presence /
    occupancy lists, options over data) plus the camera manager's area
    lookup for the entry's area (the camera-override person sensors). A
    reloading room keeps its config entry, so this never shrinks on a room
    reload; the room tracker watches exactly these."""
    data = getattr(entry, "data", {}) or {}
    merged = {**data, **(getattr(entry, "options", {}) or {})}
    configured: list[str] = []
    for conf_key in (
        _const.CONF_MOTION_SENSORS, _const.CONF_MMWAVE_SENSORS,
        _const.CONF_OCCUPANCY_SENSORS,
    ):
        for eid in merged.get(conf_key) or []:
            if eid and eid not in configured:
                configured.append(eid)
    extras = [
        e for e in camera_override_person_sensors(
            hass, merged.get(_const.CONF_AREA_ID),
        ) if e and e not in configured
    ]
    return (
        str(data.get(_const.CONF_ROOM_NAME) or merged.get(_const.CONF_ROOM_NAME) or ""),
        tuple(configured), tuple(extras),
    )


# Room-side page policy (§6.4, §6.6).
POLICY_PAGE = "page"
POLICY_DEFER = "defer"
POLICY_SUPPRESS = "suppress"
# The owner's group S1 page key prefix: (GROUP_S1_KEY, page_camera_key).
GROUP_S1_KEY = "<group>"


def twin_owner(hass: Any) -> Any:
    try:
        from ..const import DOMAIN  # noqa: PLC0415
        owner = (hass.data.get(DOMAIN) or {}).get(TWIN_HEALTH_DATA_KEY)
    except Exception:  # noqa: BLE001
        return None
    if owner is None or getattr(owner, "torn_down", True):
        return None
    return owner


def room_page_policy(hass: Any, device_id: str | None, now: datetime) -> str:
    """May a ROOM tracker send (or recover) a page for this camera device?

    PAGE: no owner, the twin rule off, a device not in the owner's map, the
    owner not map-ready past ``CAMERA_TWIN_BOOT_SETTLE_S``, an in-map
    device whose group is outside the owner's scope, or an owner whose sets
    stayed not ready (no camera manager / no entity registry) past that
    bound (review A-M1: no silent outage). DEFER: the owner is present and
    not map-ready, or cannot page yet (sets not ready), inside that bound
    (no latch is set, the candidate comes back). SUPPRESS: only when the
    owner pages the device's group (``pages_device``); never the pure
    function, so an empty or failed map makes rooms page."""
    if not device_id:
        return POLICY_PAGE
    if not bool(getattr(_const, "CAMERA_STREAM_DEAD_TWIN_RULE", False)):
        return POLICY_PAGE
    owner = twin_owner(hass)
    if owner is None:
        return POLICY_PAGE
    try:
        if not owner.map_ready:
            return POLICY_DEFER if owner.deferral_active(now) else POLICY_PAGE
        if not owner.in_map(device_id):
            return POLICY_PAGE
        if owner.pages_device(device_id):
            return POLICY_SUPPRESS
        return POLICY_DEFER if owner.not_ready_defer(now) else POLICY_PAGE
    except Exception:  # noqa: BLE001
        return POLICY_PAGE


async def send_page_and_mark(
    hass: Any, tracker: Any, ident: str, today: str, *,
    page_key: str | None = None, **send_kwargs: Any,
) -> str:
    """Send one room page through ``fire_stuck_signal_ex`` and set the
    tracker's latch only on SENT / ALREADY_SENT (§6.6 latch after send).
    The latch kind is the page's own ``kind``."""
    kind = send_kwargs.get("kind", "")
    from ._stuck_signal_nm import (  # noqa: PLC0415
        ALREADY_SENT,
        NOT_SENT,
        SENT,
        fire_stuck_signal_ex,
    )
    try:
        result = await fire_stuck_signal_ex(hass, **send_kwargs)
    except Exception:  # noqa: BLE001
        result = NOT_SENT
    try:
        if result in (SENT, ALREADY_SENT):
            tracker.mark_paged(kind, ident, today, page_key=page_key)
        else:
            tracker.mark_not_sent(kind, ident)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("camera stream page latch failed", exc_info=True)
    return result


# ----------------------------------------------------------------------
# House-level readers (S2). They aggregate the room coordinators' ONE getter
# (``camera_input_stream_dead`` / ``camera_stream_dead``); they never look at
# a camera's state themselves (INV-STREAM-ONE-GETTER). Zone tier, fan veto,
# presence fan-interference gate, census and any later NVR-witness layer read
# only these. Ship 3b: only when the room fold has no opinion, and only for
# an entity (or its camera device) in the owner's unwatched set U ∪ sticky,
# they ask the owner's house tracker (§6.3).
# ----------------------------------------------------------------------


def _room_coordinators(hass: Any) -> list[Any]:
    try:
        from ..const import DOMAIN  # noqa: PLC0415
        values = list((hass.data.get(DOMAIN) or {}).values())
    except Exception:  # noqa: BLE001
        return []
    return [v for v in values if getattr(v, "_camera_stream_health", None) is not None]


def _fold(answers: Iterable[Any]) -> bool | None:
    """True if any room says True; False if any says False; else None.
    Only real bools count (a stub's non-bool answer is no opinion)."""
    seen_false = False
    for a in answers:
        if a is True:
            return True
        if a is False:
            seen_false = True
    return False if seen_false else None


def _house_answer(hass: Any, key: str, method: str, *args: Any) -> bool | None:
    """The owner's house tracker answer for an entity in U ∪ sticky, else
    None (outside U ∪ sticky the house getters answer exactly as the rooms
    do)."""
    owner = twin_owner(hass)
    if owner is None:
        return None
    try:
        tracker = owner.house_tracker_for(key)
        if tracker is None:
            return None
        answer = getattr(tracker, method)(key, *args)
    except Exception:  # noqa: BLE001 — no opinion
        return None
    return answer if isinstance(answer, bool) else None


def _ask(
    hass: Any, method: str, key: str, *args: Any, house: str | None = None,
) -> bool | None:
    answers = []
    for coord in _room_coordinators(hass):
        try:
            answers.append(getattr(coord, method)(key, *args))
        except Exception:  # noqa: BLE001 — no opinion
            continue
    folded = _fold(answers)
    if folded is None and house is not None:
        return _house_answer(hass, key, house, *args)
    return folded


def input_stream_dead(hass: Any, input_eid: str) -> bool | None:
    """Is this room input dead because its own camera's stream is? Asks
    every room coordinator's ``camera_input_stream_dead``. None = no room
    resolves it (no opinion: callers count the input as before)."""
    if not input_eid:
        return None
    return _ask(hass, "camera_input_stream_dead", input_eid, house="is_dead")


def camera_stream_dead(hass: Any, camera_entity: str) -> bool | None:
    """THE camera-keyed dead-stream getter (S2; NVR witness W2 / W6b).

    ``camera_entity`` is a ``camera.*`` entity id. True = confirmed dead (the
    room tier excludes an input of that camera's own device this tick:
    unavailable past ``CAMERA_INPUT_STREAM_DEAD_GRACE_S``, never ``unknown``
    and never a restored placeholder); False = watched and live (or the kill
    switch is off); None = no room watches that camera (and it is not in
    the unwatched set U), i.e. unknown. A camera key other than an entity id
    is not supported (None).
    """
    if not camera_entity or not str(camera_entity).startswith("camera."):
        return None
    return _ask(hass, "camera_stream_dead", camera_entity, house="camera_is_dead")


def _own_camera_route(hass: Any, entity_id: str) -> str | None:
    """The camera the house camera route asks about for a non-input entity:
    under device level its camera DEVICE's own canonical camera (so a room
    watching that device answers, and never a twin); else the S1
    exactly-one-camera rule."""
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415
    registry = er.async_get(hass)
    if _device_level_inputs():
        return own_camera_entity_for_device(
            registry, camera_device_for_entity(registry, entity_id),
        )
    return CameraResolver.own_camera_entity_for_input(registry, entity_id)[0]


def entity_stream_dead(hass: Any, entity_id: str) -> bool | None:
    """Census / zone camera reader: a camera-derived entity counts as dead
    when a room reports it dead as an input, or else when its own camera
    (its device under device level; the S1 one-camera rule otherwise) is
    reported dead by ``camera_stream_dead``. None = no opinion."""
    if not entity_id:
        return None
    if str(entity_id).startswith("camera."):
        return camera_stream_dead(hass, entity_id)
    direct = input_stream_dead(hass, entity_id)
    if direct is not None:
        return direct
    try:
        cam = _own_camera_route(hass, entity_id)
    except Exception:  # noqa: BLE001
        return None
    if not cam:
        return None
    return camera_stream_dead(hass, cam)


# S2 "a dead input holds" (operator ruling 2026-11-14). The VIEW of an input
# outside the room: None = live or unknown to every room (count its state as
# before); HELD = dead, hold not over (UNKNOWN: it neither creates nor ends
# occupancy, the reader keeps its prior level); RELEASED = dead and the hold
# is over (CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S): count it as off.
VIEW_HELD = "held"
VIEW_RELEASED = "released"


def input_stream_view(
    hass: Any, input_eid: str, census: bool = False,
) -> str | None:
    """View of a room input outside the room: the zone tier (substrate,
    switch-off night limb, zone camera tier) or, with ``census``, the census
    (its own, shorter cap CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S).

    HELD also covers review D-M1: an input reading ``unavailable`` that no
    room tick has yet seen with a LIVE camera (it went unavailable together
    with its camera, e.g. a Protect device disconnect) is held from t0
    instead of counting as off during the grace."""
    dead = input_stream_dead(hass, input_eid)
    if dead is not True:
        if dead is False and _ask(
            hass, "camera_input_stream_unavailable_held", input_eid,
            house="is_unavailable_held",
        ) is True:
            return VIEW_HELD
        return None
    expired = _ask(
        hass, "camera_input_stream_hold_expired", input_eid,
        *((True,) if census else ()), house="is_hold_expired",
    )
    return VIEW_RELEASED if expired is True else VIEW_HELD


def entity_stream_view(
    hass: Any, entity_id: str, census: bool = False,
) -> str | None:
    """Same view for any camera-derived entity (zone camera tier, census):
    the input route first, else its own camera (as ``entity_stream_dead``)."""
    if not entity_id:
        return None
    if str(entity_id).startswith("camera."):
        if camera_stream_dead(hass, entity_id) is not True:
            return None
        expired = _ask(
            hass, "camera_stream_hold_expired", entity_id,
            *((True,) if census else ()), house="camera_hold_expired",
        )
        return VIEW_RELEASED if expired is True else VIEW_HELD
    if input_stream_dead(hass, entity_id) is not None:
        return input_stream_view(hass, entity_id, census)
    # Review D-L1 / D2 (latent, documented, not fixed): a NON-input entity
    # (census / zone) on a device a room watches through ANOTHER entity is
    # routed by its device's camera, which is HELD only once that camera is
    # dead past the grace. The t0 unavailable-held classifier is per room
    # INPUT, and U excludes every entity on a watched device, so such an
    # entity reads plain `unavailable` (missing) for 0-120 s after a device
    # disconnect. No live shape found (needs e.g. a Protect `_motion` filed
    # in a room of another area). PRESENCE state of play, ship 3b entry.
    try:
        cam = _own_camera_route(hass, entity_id)
    except Exception:  # noqa: BLE001
        return None
    if not cam:
        return None
    return entity_stream_view(hass, cam, census)


def input_room_quarantined(hass: Any, input_eid: str) -> bool:
    """Review D-L2: True iff a room currently quarantines this input
    (chatter / stuck / duty-cycle / P22, any client of its
    ``SensorExclusionSet``). Such a sensor is not working equipment, so its
    ``on -> off`` cannot end a dead-camera hold. Error = False (develop)."""
    if not input_eid:
        return False
    return _ask(hass, "camera_input_room_quarantined", input_eid) is True


_MISSING = object()


def _safe_state(state_getter: Callable[[str], Any], entity_id: str) -> Any:
    try:
        return state_getter(entity_id)
    except Exception:  # noqa: BLE001 — no opinion
        return None


def _is_restored(state: Any) -> bool:
    """HA marks a registry entity that no integration has loaded yet as
    ``unavailable`` with attribute ``restored: True``."""
    attrs = getattr(state, "attributes", None)
    try:
        return bool(attrs) and attrs.get("restored") is True
    except Exception:  # noqa: BLE001
        return False
