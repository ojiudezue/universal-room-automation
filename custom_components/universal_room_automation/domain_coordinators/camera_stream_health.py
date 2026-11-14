"""Camera input stream health, S1 room tier.

Plan: ``docs/planning/PLANNING_camera_input_stream_health.md`` (cards
PANEL-KS-HEALTH-AS-INPUT-1, CAMERA-STREAM-DEAD-ZONE-AND-CENSUS-1 for S2).

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
  * ``unknown`` or no state    -> no opinion: ``since`` neither set nor
    cleared, and the input is not dead this tick (INV needs ``unavailable``).
  * anything else              -> live: ``since`` cleared.

One public reader for the room and its siblings:
``UniversalRoomCoordinator.camera_input_stream_dead(input_eid)`` (S2 zone /
fan recheck / census and a future NVR-witness layer read only that).
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

_UNAVAILABLE = "unavailable"
_UNKNOWN = "unknown"


class CameraInputStreamHealth:
    """Per-room dead-stream tracker (RAM only; rebuilt on restart)."""

    def __init__(self, room_name: str) -> None:
        self._room_name = room_name
        # input_eid -> (camera_eid | None, reason, camera_derived)
        self._resolution: dict[str, tuple[str | None, str, bool]] | None = None
        self._resolution_inputs: tuple[str, ...] = ()
        # camera_eid -> first observed `unavailable` time.
        self._unavail_since: dict[str, datetime] = {}
        # input_eid -> (camera_eid, since): dead THIS tick.
        self._dead_now: dict[str, tuple[str, datetime]] = {}
        # NM bookkeeping: inputs whose current episode paged; per-day latch.
        self._paged_episode: set[str] = set()
        self._paged_day: dict[str, str] = {}
        self._warned_unresolved = False

    # ------------------------------------------------------------------
    # Resolution cache
    # ------------------------------------------------------------------

    def invalidate(self) -> None:
        """Drop the resolution cache (entity registry changed)."""
        self._resolution = None

    def _ensure_resolution(
        self, inputs: tuple[str, ...], registry_getter: Callable[[], Any],
    ) -> dict[str, tuple[str | None, str, bool]]:
        if self._resolution is not None and inputs == self._resolution_inputs:
            return self._resolution
        try:
            registry = registry_getter()
        except Exception:  # noqa: BLE001
            registry = None
        resolution: dict[str, tuple[str | None, str, bool]] = {}
        for eid in inputs:
            if registry is None:
                resolution[eid] = (None, "registry_error", False)
                continue
            resolution[eid] = CameraResolver.own_camera_entity_for_input(
                registry, eid,
            )
        self._resolution = resolution
        self._resolution_inputs = inputs
        self._maybe_warn_unresolved(resolution)
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

    # ------------------------------------------------------------------
    # Per-tick evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        now: datetime,
        inputs: Iterable[str],
        state_getter: Callable[[str], Any],
        registry_getter: Callable[[], Any],
    ) -> tuple[
        dict[str, tuple[str, datetime]],
        list[tuple[str, str, datetime]],
        list[tuple[str, str]],
    ]:
        """One room tick. Returns ``(dead_now, to_page, to_recover)``.

        ``dead_now``: input -> (camera, since) to exclude this tick.
        ``to_page``: (input, camera, since) whose exclusion just passed
        ``CAMERA_INPUT_STREAM_DEAD_NM_AFTER_S`` (once per episode, once per
        input per local day). ``to_recover``: (input, camera) whose paged
        episode ended this tick.
        """
        ordered: list[str] = []
        for eid in inputs:
            if eid and eid not in ordered:
                ordered.append(eid)
        resolution = self._ensure_resolution(tuple(ordered), registry_getter)

        enabled = bool(getattr(_const, "CAMERA_INPUT_STREAM_HEALTH_ENABLED", False))
        grace_s = float(getattr(_const, "CAMERA_INPUT_STREAM_DEAD_GRACE_S", 120.0))
        nm_after_s = float(
            getattr(_const, "CAMERA_INPUT_STREAM_DEAD_NM_AFTER_S", 0.0),
        )

        cameras = {cam for cam, _r, _d in resolution.values() if cam}
        # Prune stamps of cameras no longer watched (config / registry change).
        for cam in list(self._unavail_since):
            if cam not in cameras:
                self._unavail_since.pop(cam, None)
        camera_state: dict[str, str | None] = {}
        for cam in cameras:
            try:
                st = state_getter(cam)
            except Exception:  # noqa: BLE001
                st = None
            value = getattr(st, "state", None) if st is not None else None
            camera_state[cam] = value
            if value is None or value == _UNKNOWN:
                continue  # no opinion
            if value == _UNAVAILABLE:
                self._unavail_since.setdefault(cam, now)
            else:
                self._unavail_since.pop(cam, None)

        dead: dict[str, tuple[str, datetime]] = {}
        if enabled:
            for eid in ordered:
                cam = resolution.get(eid, (None, "", False))[0]
                if not cam or camera_state.get(cam) != _UNAVAILABLE:
                    continue
                since = self._unavail_since.get(cam)
                if since is None:
                    continue
                if (now - since).total_seconds() >= grace_s:
                    dead[eid] = (cam, since)

        to_page: list[tuple[str, str, datetime]] = []
        today = now.date().isoformat()
        if nm_after_s > 0:
            for eid, (cam, since) in dead.items():
                if eid in self._paged_episode:
                    continue
                if self._paged_day.get(eid) == today:
                    continue
                if (now - since).total_seconds() >= nm_after_s:
                    self._paged_episode.add(eid)
                    self._paged_day[eid] = today
                    to_page.append((eid, cam, since))

        to_recover: list[tuple[str, str]] = []
        for eid in sorted(self._paged_episode):
            if eid not in dead:
                prev = self._dead_now.get(eid)
                to_recover.append((eid, prev[0] if prev else ""))
                self._paged_episode.discard(eid)

        self._dead_now = dead
        return dict(dead), to_page, to_recover

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

    def snapshot(self) -> dict[str, Any]:
        """Display surface for ``sensor.<room>_unavailable_entities``."""
        resolution = self._resolution or {}
        return {
            "camera_stream_dead_inputs": {
                eid: {"camera": cam, "since": since.isoformat()}
                for eid, (cam, since) in sorted(self._dead_now.items())
            },
            "camera_stream_inputs_resolved": sum(
                1 for cam, _r, _d in resolution.values() if cam
            ),
        }
