"""ExteriorTrackLinker — perimeter person/car/animal track linking.

Sits ABOVE PerimeterAlertManager: consumes the same Frigate detection stream
(via the `frigate_events` bus) plus the resolved person-binary-sensor state
changes as a fallback, and links space-time-plausible events into one open
track per Frigate label. Never re-identifies — pure adjacency + Δt.

INVARIANT (INV-XT, this cycle):
    A single person crossing N adjacent perimeter cameras within link
    windows yields exactly ONE track and at most ONE alert thread.

INV-XP (from PLANNING_exterior_person_escalation): NOT weakened here.
Per-camera cooldown in PerimeterAlertManager remains the outer rate limit.
Same-track suppression is only ever a REFINEMENT of alert cadence — it
narrows the alert stream, it never bypasses a cooldown or creates a new
dispatch path.

Kill switch: TRACK_LINK_WINDOW_S == 0 → no linking (every event opens a
new single-hop track), no cross-camera suppression → per-camera behavior
is byte-identical to today.
"""

from __future__ import annotations

import itertools
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from datetime import timedelta

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    TRACK_LINK_WINDOW_S,
    TRACK_CLOSE_IDLE_S,
    EXTERIOR_ADJACENCY_GRAPH,
    EXTERIOR_TRACK_LABELS,
    EXTERIOR_TRACK_CLASSIFY_APPROACH_CAMERAS,
    EXTERIOR_TRACK_CLASSIFY_CIRCLING_CAMERAS,
    EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS,
    NM_HAZARD_EXTERIOR_TRACK_SEVERITY_MAP,
)

_LOGGER = logging.getLogger(__name__)

# Frigate HA-bus event name (same as perimeter_alert.py — subscribe defensively).
FRIGATE_EVENTS_BUS_EVENT = "frigate_events"

# Bucketing for Frigate labels into track families. Extended per review
# A-MED-4 (dog, cat, bird, squirrel, rabbit, fox, coyote, deer, raccoon,
# possum, bear). "vehicle" retained under the car bucket in _bucket_label.
_ANIMAL_LABELS = {
    "dog", "cat", "animal", "bird", "squirrel", "rabbit",
    "fox", "coyote", "deer", "raccoon", "possum", "bear",
}

# Dedup window for observe() dispatch across the two ingress paths (frigate
# events bus vs perimeter binary_sensor fallback). Two calls for the same
# (camera,label) within this window fold to one hop. Keep small so a real
# fresh detection is never dropped.
_OBSERVE_DEDUP_S: float = 2.5


def _bucket_label(raw: str) -> str | None:
    """Normalize a Frigate label into person/car/animal, or None to ignore."""
    if not raw:
        return None
    lw = raw.lower()
    if lw == "person":
        return "person"
    if lw in ("car", "truck", "bus", "motorcycle", "vehicle"):
        return "car"
    if lw in _ANIMAL_LABELS:
        return "animal"
    return None


@dataclass
class TrackHop:
    """One camera visit inside a track."""

    camera: str
    t_first: datetime
    t_last: datetime
    best_score: float = 0.0
    best_event_id: str | None = None


@dataclass
class ExteriorTrack:
    """One open (or just-closed) exterior track."""

    track_id: str
    label: str
    hops: list[TrackHop] = field(default_factory=list)
    sub_label: str | None = None  # Frigate sub_label promotes to identified
    alert_count: int = 0
    first_alert_at: datetime | None = None
    started_at: datetime = field(default_factory=dt_util.now)

    @property
    def last_hop(self) -> TrackHop:
        return self.hops[-1]

    @property
    def cameras(self) -> list[str]:
        return [h.camera for h in self.hops]

    @property
    def camera_count(self) -> int:
        return len({h.camera for h in self.hops})

    @property
    def revisit_count(self) -> int:
        seen: dict[str, int] = {}
        for h in self.hops:
            seen[h.camera] = seen.get(h.camera, 0) + 1
        return sum(1 for c in seen.values() if c > 1)

    @property
    def duration_s(self) -> float:
        if not self.hops:
            return 0.0
        return (self.hops[-1].t_last - self.hops[0].t_first).total_seconds()

    @property
    def identified(self) -> bool:
        return bool(self.sub_label)


class ExteriorTrackLinker:
    """Space-time linker for perimeter Frigate detections.

    Owned by the integration entry (sibling to PerimeterAlertManager). Feed
    it every raw perimeter detection via observe(); on a cadence it closes
    idle tracks and writes them to memory_episodes.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._tracks: dict[str, list[ExteriorTrack]] = {
            label: [] for label in EXTERIOR_TRACK_LABELS
        }
        self._closed_recent: list[ExteriorTrack] = []
        # Operator control surface (2026-08-06): two live switches.
        #   tracking_enabled — the fire axe. OFF = observe() creates no
        #     tracks; find_owning_track/note_alert_dispatched inert;
        #     per-camera alerting byte-identical to no-linker baseline
        #     (same contract as TRACK_LINK_WINDOW_S == 0).
        #   smart_alerts_enabled — governs ONLY the severity judgment
        #     layer in perimeter_alert (demotion/escalation). OFF = every
        #     camera alerts at classic severity while tracking/census/
        #     narrative continue. OFF makes alerting LOUDER, never silent.
        # suppressed_since timestamps carry operator-off provenance
        # (notification-hygiene precedent).
        self.tracking_enabled: bool = True
        self.smart_alerts_enabled: bool = True
        self.tracking_suppressed_since: str | None = None
        self.smart_alerts_suppressed_since: str | None = None
        self._unsub_frigate: Any = None
        self._unsub_sweep: Any = None
        self._active = False
        # Adjacency table — module constant by default, mutable per install
        # via set_adjacency (tests + operator). Symmetrized in constructor
        # (review B-L1 / D-MED-2) so declaring A→B in the module dict is
        # enough — B→A is auto-added.
        self._adjacency: dict[str, set[str]] = {}
        for a, neigh in EXTERIOR_ADJACENCY_GRAPH.items():
            self._adjacency.setdefault(a, set()).update(neigh)
            for b in neigh:
                self._adjacency.setdefault(b, set()).add(a)
        self._id_gen = itertools.count(1)
        # In-flight episode-write tasks (B-H2). done_callback discards on
        # completion; teardown gathers with bounded wait.
        self._episode_tasks: set[Any] = set()
        # (camera,label) → last-observed timestamp for cross-source dedup.
        self._last_observed: dict[tuple[str, str], datetime] = {}
        # Per-camera events that failed to link into any existing track
        # (B-M3 diagnostic). "Failed to link" here means opened a NEW
        # single-hop track rather than extending one — surfaced via the
        # diagnostic sensor's attrs.
        self._unlinked_events: dict[str, int] = {}
        # Exterior cycle 2 (seam-split telemetry rider, 2026-08-06). When a
        # NEW same-label track opens on camera B while an existing open track's
        # last hop A is EXACTLY 2 graph-hops from B (and within
        # TRACK_LINK_WINDOW_S), count (A,B) as a candidate missed-intermediate
        # observation. Observability only — never mutates edges or dispatch.
        self._seam_split_counts: dict[tuple[str, str], int] = {}

    # ---------------- setup / teardown ----------------
    async def async_setup(self) -> None:
        """Subscribe to `frigate_events`. Best-effort; no-op if never fired."""
        if self._active:
            return

        @callback
        def _on_frigate(event: Event) -> None:
            try:
                after = event.data.get("after") or {}
                raw_label = str(after.get("label") or "")
                label = _bucket_label(raw_label)
                if label is None:
                    return
                camera = str(after.get("camera") or "").strip()
                if not camera:
                    return
                event_id = after.get("id")
                score = float(after.get("score") or 0.0)
                sub_label = after.get("sub_label") or None
                msg_type = str(event.data.get("type") or "").lower()
                if msg_type == "end":
                    return
                self.observe(
                    camera=camera,
                    label=label,
                    event_id=str(event_id) if event_id else None,
                    score=score,
                    sub_label=sub_label,
                    now=dt_util.now(),
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug("ExteriorTrackLinker: frigate parse failed", exc_info=True)

        self._unsub_frigate = self.hass.bus.async_listen(
            FRIGATE_EVENTS_BUS_EVENT, _on_frigate
        )
        # B-H1: periodic idle sweep so tracks close even in the absence of
        # further events (frigate quiet after a walker leaves). Cadence =
        # TRACK_CLOSE_IDLE_S / 2 to guarantee close within one extra window.
        try:
            interval = timedelta(
                seconds=max(1, TRACK_CLOSE_IDLE_S // 2)
            )

            @callback
            def _sweep_tick(_now: Any) -> None:
                try:
                    self._sweep_closed(dt_util.now())
                except Exception:  # noqa: BLE001
                    _LOGGER.debug(
                        "ExteriorTrackLinker: sweep tick raised",
                        exc_info=True,
                    )

            self._unsub_sweep = async_track_time_interval(
                self.hass, _sweep_tick, interval
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "ExteriorTrackLinker: sweep timer registration failed",
                exc_info=True,
            )
            self._unsub_sweep = None
        self._active = True
        _LOGGER.info(
            "ExteriorTrackLinker: active (link_window=%ds, close_idle=%ds, "
            "adjacency_nodes=%d)",
            TRACK_LINK_WINDOW_S, TRACK_CLOSE_IDLE_S, len(self._adjacency),
        )

    async def async_teardown(self) -> None:
        if self._unsub_frigate is not None:
            try:
                self._unsub_frigate()
            except Exception:  # noqa: BLE001
                pass
            self._unsub_frigate = None
        if self._unsub_sweep is not None:
            try:
                self._unsub_sweep()
            except Exception:  # noqa: BLE001
                pass
            self._unsub_sweep = None
        # Flush every open track as a close (so no data is lost across restart
        # for in-flight walks — episode source_ref dedup drops repeats).
        for label in list(self._tracks.keys()):
            for t in list(self._tracks[label]):
                self._close_track(t, reason="teardown")
            self._tracks[label] = []
        # B-H2: wait for outstanding episode-write tasks with a bounded
        # timeout so shutdown never hangs on a stuck DB.
        pending = [t for t in self._episode_tasks if not t.done()]
        if pending:
            import asyncio as _asyncio  # noqa: PLC0415
            try:
                await _asyncio.wait_for(
                    _asyncio.gather(*pending, return_exceptions=True),
                    timeout=2.0,
                )
            except _asyncio.TimeoutError:
                _LOGGER.debug(
                    "ExteriorTrackLinker: %d episode task(s) still pending "
                    "after 2s wait — abandoning at teardown.",
                    len(pending),
                )
            except Exception:  # noqa: BLE001
                pass
        self._episode_tasks.clear()
        self._active = False
        _LOGGER.debug("ExteriorTrackLinker: torn down")

    # ---------------- operator / test knobs ----------------
    def set_adjacency(self, graph: dict[str, list[str]] | dict[str, set[str]]) -> None:
        """Replace the adjacency table (operator-declared) at runtime.

        Symmetrizes the graph so declaring A→B is enough (B→A implied).
        """
        adj: dict[str, set[str]] = {}
        for a, neigh in graph.items():
            adj.setdefault(a, set()).update(neigh)
            for b in neigh:
                adj.setdefault(b, set()).add(a)
        self._adjacency = adj

    @property
    def is_active(self) -> bool:
        return self._active

    # ---------------- core: link ----------------
    def observe(
        self,
        camera: str,
        label: str,
        event_id: str | None,
        score: float,
        sub_label: str | None,
        now: datetime,
    ) -> ExteriorTrack | None:
        """Link event to an open track (or open a new one). Returns the track.

        Kill switch: TRACK_LINK_WINDOW_S == 0 → NO tracks are created, no
        state is mutated (byte-identical to no-linker baseline). Returns None.

        Cross-source dedup (_OBSERVE_DEDUP_S): a second observation for the
        same (camera,label) within a couple seconds of the first is folded
        into the existing hop (idempotent), never opens a new track.
        """
        if TRACK_LINK_WINDOW_S <= 0 or not self.tracking_enabled:
            return None
        if label not in self._tracks:
            self._tracks[label] = []
        key = (camera, label)
        last_obs = self._last_observed.get(key)
        if last_obs is not None:
            dt = (now - last_obs).total_seconds()
            if 0 <= dt < _OBSERVE_DEDUP_S:
                # Fold into the current owning track's last hop if it is on
                # this camera; otherwise drop silently (the other-source
                # already recorded it).
                owning = self.find_owning_track(camera, label, now)
                if owning is not None and owning.hops and owning.hops[-1].camera == camera:
                    hop = owning.hops[-1]
                    hop.t_last = now
                    if score > hop.best_score:
                        hop.best_score = score
                        if event_id:
                            hop.best_event_id = event_id
                    if sub_label and not owning.sub_label:
                        # Sub-label promotion still needs ≥2 confirmations
                        # (see below), so record on the track but do not
                        # short-circuit it here.
                        pass
                return owning
        self._last_observed[key] = now

        # First, close anything idle past the window (this may include the
        # candidate track before we look for a match — correct: past-idle
        # tracks should not swallow a fresh event).
        self._sweep_closed(now)

        track = self._find_link_target(label, camera, now)
        if track is None:
            # Seam-split telemetry (cycle 2): before opening a new track,
            # check whether an open same-label track's last hop is exactly
            # 2 graph-hops from this camera (plausible missed intermediate).
            # Purely observational — no behavior change.
            try:
                self._record_seam_split_if_any(label, camera, now)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "ExteriorTrackLinker: seam-split telemetry raised",
                    exc_info=True,
                )
            track = ExteriorTrack(
                track_id=f"xt-{next(self._id_gen):06d}-{uuid.uuid4().hex[:6]}",
                label=label,
                started_at=now,
            )
            self._tracks[label].append(track)
            # B-M3: bump per-camera unlinked-events counter — a fresh
            # single-hop track opened when we could not link to any existing
            # open track.
            self._unlinked_events[camera] = (
                self._unlinked_events.get(camera, 0) + 1
            )
            _LOGGER.info(
                "ExteriorTrackLinker: new %s track %s opened at camera=%s",
                label, track.track_id, camera,
            )

        self._append_hop(track, camera, event_id, score, now)
        # D-MED-1: sub_label promotes identity only when observed on ≥2 hops
        # OR the same sub_label seen twice. First sub_label sighting is
        # provisional (stored on the track as _pending_sub_label) — the
        # second matching sighting confirms.
        if sub_label:
            sl = str(sub_label)
            pending = getattr(track, "_pending_sub_label", None)
            if track.sub_label is None:
                if pending is None:
                    track._pending_sub_label = sl
                    track._pending_sub_label_hops = {len(track.hops) - 1}
                elif pending == sl:
                    # Confirmed either by a different hop OR a second sighting.
                    seen_hops = getattr(
                        track, "_pending_sub_label_hops", set()
                    )
                    seen_hops.add(len(track.hops) - 1)
                    if len(seen_hops) >= 2 or track.camera_count >= 2:
                        track.sub_label = sl
                        _LOGGER.info(
                            "ExteriorTrackLinker: track %s promoted to "
                            "identified via sub_label=%s (≥2 hops)",
                            track.track_id, sl,
                        )
                    else:
                        track._pending_sub_label_hops = seen_hops
                else:
                    # Disagreement — reset provisional sub_label.
                    track._pending_sub_label = sl
                    track._pending_sub_label_hops = {len(track.hops) - 1}
        return track

    def _append_hop(
        self,
        track: ExteriorTrack,
        camera: str,
        event_id: str | None,
        score: float,
        now: datetime,
    ) -> None:
        if track.hops and track.hops[-1].camera == camera:
            hop = track.hops[-1]
            hop.t_last = now
            if score > hop.best_score:
                hop.best_score = score
                if event_id:
                    hop.best_event_id = event_id
            return
        track.hops.append(
            TrackHop(
                camera=camera,
                t_first=now,
                t_last=now,
                best_score=score,
                best_event_id=event_id,
            )
        )

    def _find_link_target(
        self, label: str, camera: str, now: datetime
    ) -> ExteriorTrack | None:
        """Return an open track this event can attach to, or None.

        Kill switch: TRACK_LINK_WINDOW_S == 0 → always None (no linking).
        """
        if TRACK_LINK_WINDOW_S <= 0:
            return None
        best: ExteriorTrack | None = None
        best_dt: float = float("inf")
        for t in self._tracks.get(label, []):
            last = t.last_hop
            dt = (now - last.t_last).total_seconds()
            if dt < 0 or dt > TRACK_LINK_WINDOW_S:
                continue
            same = last.camera == camera
            adj = camera in self._adjacency.get(last.camera, set())
            if not (same or adj):
                continue
            if dt < best_dt:
                best_dt = dt
                best = t
        return best

    # ---------------- close / episode ----------------
    def _sweep_closed(self, now: datetime) -> None:
        """Close any track idle past TRACK_CLOSE_IDLE_S."""
        for label, tracks in self._tracks.items():
            still_open: list[ExteriorTrack] = []
            for t in tracks:
                idle = (now - t.last_hop.t_last).total_seconds()
                if idle > TRACK_CLOSE_IDLE_S:
                    self._close_track(t, reason="idle_timeout")
                else:
                    still_open.append(t)
            self._tracks[label] = still_open

    def drain_open_tracks(self, reason: str = "operator_off") -> None:
        """Close ALL open tracks immediately (focused-review MEDIUM-1).

        Called by the Exterior Path Tracking switch on turn_off so the
        fire-axe framing is instantaneous: census zeroes NOW, episodes
        for in-flight tracks are written with the operator-off reason.
        """
        for label in list(self._tracks):
            for track in list(self._tracks[label]):
                self._close_track(track, reason)
            self._tracks[label] = []

    def sweep_closed(self, now: datetime | None = None) -> None:
        """Public wrapper — callable from a periodic tick."""
        self._sweep_closed(now or dt_util.now())

    def _close_track(self, track: ExteriorTrack, reason: str) -> None:
        _LOGGER.info(
            "ExteriorTrackLinker: closing %s track %s "
            "(%d hops, %d cameras, %.0fs, reason=%s)",
            track.label, track.track_id, len(track.hops),
            track.camera_count, track.duration_s, reason,
        )
        self._closed_recent.append(track)
        # Trim closed_recent buffer.
        if len(self._closed_recent) > 50:
            self._closed_recent = self._closed_recent[-50:]
        # Persist as memory_episode (best-effort). B-H2: keep a handle so
        # teardown can await outstanding writes.
        task = self.hass.async_create_task(self._write_episode(track))
        try:
            self._episode_tasks.add(task)
            task.add_done_callback(self._episode_tasks.discard)
        except Exception:  # noqa: BLE001
            # A MagicMock hass in tests may return non-Future; ignore.
            pass

    async def _write_episode(self, track: ExteriorTrack) -> None:
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if db is None or not hasattr(db, "log_memory_episode"):
            return
        try:
            classification = self.classify(track)
            attrs = {
                "track_id": track.track_id,
                "label": track.label,
                "sub_label": track.sub_label,
                "classification": classification,
                "path": [h.camera for h in track.hops],
                "hops": [
                    {
                        "camera": h.camera,
                        "t_first": h.t_first.isoformat(),
                        "t_last": h.t_last.isoformat(),
                        "best_score": round(h.best_score, 3),
                        "best_event_id": h.best_event_id,
                    }
                    for h in track.hops
                ],
                "duration_s": round(track.duration_s, 1),
                "camera_count": track.camera_count,
                "revisit_count": track.revisit_count,
                "identified": track.identified,
                "path_string": self.path_string(track),
            }
            ended_dt = track.hops[-1].t_last if track.hops else track.started_at
            # B-H3: real dedup via `dedup_source_ref=True` — database.py
            # performs a SELECT-by-source_ref existence check under this
            # flag and skips the INSERT on match. Backwards-compat: callers
            # not passing the flag get the pre-existing dedup semantics.
            await db.log_memory_episode(
                node_id="exterior:perimeter",
                episode_type="exterior_track",
                adjudication="observed",
                adjudicated_by="exterior_track_linker",
                attrs=attrs,
                source_ref=f"exterior_track:{track.track_id}",
                started_at=track.started_at.isoformat(),
                ended_at=ended_dt.isoformat(),
                dedup_source_ref=True,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "ExteriorTrackLinker: episode write failed for %s: %s",
                track.track_id, exc,
            )

    # ---------------- classification / rendering ----------------
    def classify(self, track: ExteriorTrack) -> str:
        """pass_by / approach / circling — space-time only, no ML.

        Review A-MED-2: circling requires EITHER a revisit
        (revisit_count >= 1, i.e. a camera appears as a non-consecutive
        hop twice) OR camera_count >= EXTERIOR_TRACK_CLASSIFY_CIRCLING_CAMERAS
        with a non-monotonic sequence (i.e. the traversal loops rather
        than proceeds in a single arc). Purely-monotonic wide traversals
        (e.g. a delivery driver walking across N adjacent cameras once)
        classify as `approach` when egress-adjacent, `pass_by` otherwise
        — reduces the false-circling rate.
        """
        cams = track.cameras
        if not cams:
            return "pass_by"
        non_monotonic = self._is_non_monotonic(cams)
        if track.revisit_count >= 1 or (
            track.camera_count >= EXTERIOR_TRACK_CLASSIFY_CIRCLING_CAMERAS
            and non_monotonic
        ):
            return "circling"
        # Approach: touches an operator-declared egress-adjacent camera.
        egress_adj = set(EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS)
        if egress_adj and any(c in egress_adj for c in cams):
            return "approach"
        if (
            EXTERIOR_TRACK_CLASSIFY_APPROACH_CAMERAS > 0
            and track.camera_count >= EXTERIOR_TRACK_CLASSIFY_APPROACH_CAMERAS
        ):
            return "approach"
        return "pass_by"

    def _is_non_monotonic(self, cams: list[str]) -> bool:
        """A track is non-monotonic if a camera appears again after a
        different camera intervened (i.e. the walker looped back)."""
        seen: set[str] = set()
        prev: str | None = None
        for c in cams:
            if c == prev:
                continue
            if c in seen:
                return True
            seen.add(c)
            prev = c
        return False

    def path_string(self, track: ExteriorTrack) -> str:
        cams = track.cameras
        # Compact: dedupe consecutive repeats for display.
        compact: list[str] = []
        for c in cams:
            if not compact or compact[-1] != c:
                compact.append(c)
        # A-MED-6: sub-minute → "just now" (reads more naturally than "0 min").
        if track.duration_s < 60:
            when = "just now"
        else:
            minutes = int(track.duration_s // 60)
            when = f"{minutes} min"
        return f"{' → '.join(compact)} · {when} · {track.label}"

    # ---------------- surfaces ----------------
    def census_counts(self) -> dict[str, int]:
        """Open-track counts for census sensors."""
        person = self._tracks.get("person", [])
        return {
            "exterior_person_tracks_active": len(person),
            "exterior_vehicle_tracks_active": len(self._tracks.get("car", [])),
            "exterior_animal_tracks_active": len(self._tracks.get("animal", [])),
            "exterior_unidentified_persons": sum(
                1 for t in person if not t.identified
            ),
        }

    def open_tracks_snapshot(self) -> list[dict]:
        out: list[dict] = []
        for label in EXTERIOR_TRACK_LABELS:
            for t in self._tracks.get(label, []):
                out.append(
                    {
                        "track_id": t.track_id,
                        "label": t.label,
                        "sub_label": t.sub_label,
                        "classification": self.classify(t),
                        "path": self.path_string(t),
                        "cameras": t.cameras,
                        "duration_s": round(t.duration_s, 1),
                        "identified": t.identified,
                        "last_camera": t.last_hop.camera,
                        "last_seen": t.last_hop.t_last.isoformat(),
                        "alert_count": t.alert_count,
                    }
                )
        return out

    # ---------------- alert bookkeeping (redesign: demote, never silence) ---
    def note_alert_dispatched(
        self, camera: str, label: str, now: datetime
    ) -> None:
        """Record that PerimeterAlertManager dispatched an alert.

        Attributes the dispatch to the OWNING open track (last hop on this
        camera). "Real dispatches" only — the redesign kills the silent
        suppress-and-return path, so alert_count now measures real NM
        deliveries (A-MED-1 dissolved: no more "attributed-but-not-dispatched"
        confounding).

        Kill switch: TRACK_LINK_WINDOW_S == 0 → no tracks exist → no-op.
        """
        if TRACK_LINK_WINDOW_S <= 0:
            return
        t = self.find_owning_track(camera, label, now)
        if t is None:
            return
        t.alert_count += 1
        if t.first_alert_at is None:
            t.first_alert_at = now

    def find_owning_track(
        self, camera: str, label: str, now: datetime
    ) -> ExteriorTrack | None:
        """Return the OPEN track that owns the last hop on `camera` for `label`.

        Unified lookup used by BOTH the demotion decision AND the narrative
        enrichment path in perimeter_alert.py (A-HIGH-2 — kills the
        _find_link_target vs latest_track_for_camera divergence). "Owning"
        means the track whose most-recent hop is this camera; if multiple
        such tracks exist, the one with the newest hop wins.

        Kill switch: TRACK_LINK_WINDOW_S == 0 or Exterior Path Tracking
        switch OFF → always None.
        """
        if TRACK_LINK_WINDOW_S <= 0 or not self.tracking_enabled:
            return None
        best: ExteriorTrack | None = None
        best_t: datetime | None = None
        for t in self._tracks.get(label, []):
            if not t.hops or t.hops[-1].camera != camera:
                continue
            if best_t is None or t.hops[-1].t_last > best_t:
                best_t = t.hops[-1].t_last
                best = t
        return best

    # Back-compat alias. Old name preserved for any external consumer; the
    # implementation now routes through find_owning_track (one lookup path).
    def latest_track_for_camera(
        self, camera: str, label: str = "person"
    ) -> ExteriorTrack | None:
        return self.find_owning_track(camera, label, dt_util.now())

    # ---------------- surface: seam-split telemetry (cycle 2 rider) ----------
    def _record_seam_split_if_any(
        self, label: str, camera: str, now: datetime
    ) -> None:
        """Count a (A,B) seam when a NEW track opens on B while an open
        same-label track has its last hop A exactly 2 graph-hops from B.

        "2 graph-hops" means A and B are NOT directly adjacent, but there
        exists some intermediate camera M adjacent to both. We record the
        endpoint seam (A,B) because M is not always unambiguous.
        """
        neigh_b = self._adjacency.get(camera, set())
        if not neigh_b:
            return
        for t in self._tracks.get(label, []):
            if not t.hops:
                continue
            last = t.hops[-1]
            a = last.camera
            if a == camera:
                continue
            dt = (now - last.t_last).total_seconds()
            if dt < 0 or dt > TRACK_LINK_WINDOW_S:
                continue
            neigh_a = self._adjacency.get(a, set())
            if camera in neigh_a:
                # Directly adjacent — would have linked; defensive skip.
                continue
            if neigh_a & neigh_b:
                key = (a, camera)
                self._seam_split_counts[key] = (
                    self._seam_split_counts.get(key, 0) + 1
                )
                _LOGGER.info(
                    "ExteriorTrackLinker: seam-split candidate on "
                    "(%s→%s) label=%s (2-hop, Δt=%.0fs) — count now %d",
                    a, camera, label, dt, self._seam_split_counts[key],
                )
                return

    def seam_split_snapshot(self) -> dict[str, int]:
        """Return {"A→B": count} for the diagnostic sensor attrs."""
        return {
            f"{a}→{b}": n
            for (a, b), n in self._seam_split_counts.items()
        }

    # ---------------- surface: unlinked-events counter (B-M3) ----------------
    def unlinked_events_snapshot(self) -> dict[str, int]:
        """Return {camera: count} of events that opened a NEW single-hop
        track rather than extending an existing one — a diagnostic proxy
        for cross-camera link failures (missing adjacency edge, walker gap
        exceeded TRACK_LINK_WINDOW_S, or non-perimeter noise)."""
        return dict(self._unlinked_events)
