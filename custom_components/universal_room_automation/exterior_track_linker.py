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

from homeassistant.core import HomeAssistant, callback, Event
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

# Bucketing for Frigate labels into track families.
_ANIMAL_LABELS = {"dog", "cat", "animal", "bird", "raccoon", "deer"}


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
        self._unsub_frigate: Any = None
        self._active = False
        # Adjacency table — module constant by default, mutable per install
        # via set_adjacency (tests + operator).
        self._adjacency: dict[str, set[str]] = {
            k: set(v) for k, v in EXTERIOR_ADJACENCY_GRAPH.items()
        }
        self._id_gen = itertools.count(1)

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
        # Flush every open track as a close (so no data is lost across restart
        # for in-flight walks — episode dedup gate will drop repeats).
        for label in list(self._tracks.keys()):
            for t in list(self._tracks[label]):
                self._close_track(t, reason="teardown")
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
    ) -> ExteriorTrack:
        """Link event to an open track (or open a new one). Returns the track."""
        if label not in self._tracks:
            self._tracks[label] = []
        # First, close anything idle past the window (this may include the
        # candidate track before we look for a match — correct: past-idle
        # tracks should not swallow a fresh event).
        self._sweep_closed(now)

        track = self._find_link_target(label, camera, now)
        if track is None:
            track = ExteriorTrack(
                track_id=f"xt-{next(self._id_gen):06d}-{uuid.uuid4().hex[:6]}",
                label=label,
                started_at=now,
            )
            self._tracks[label].append(track)
            _LOGGER.info(
                "ExteriorTrackLinker: new %s track %s opened at camera=%s",
                label, track.track_id, camera,
            )

        self._append_hop(track, camera, event_id, score, now)
        if sub_label and not track.sub_label:
            track.sub_label = str(sub_label)
            _LOGGER.info(
                "ExteriorTrackLinker: track %s promoted to identified via "
                "sub_label=%s", track.track_id, sub_label,
            )
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
        # Persist as memory_episode (best-effort).
        self.hass.async_create_task(self._write_episode(track))

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
            await db.log_memory_episode(
                node_id="exterior:perimeter",
                episode_type="exterior_track",
                adjudication="observed",
                adjudicated_by="exterior_track_linker",
                attrs=attrs,
                source_ref=f"exterior_track:{track.track_id}",
                started_at=track.started_at.isoformat(),
                ended_at=ended_dt.isoformat(),
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "ExteriorTrackLinker: episode write failed for %s: %s",
                track.track_id, exc,
            )

    # ---------------- classification / rendering ----------------
    def classify(self, track: ExteriorTrack) -> str:
        """pass_by / approach / circling — space-time only, no ML."""
        cams = track.cameras
        if not cams:
            return "pass_by"
        # Circling: revisits OR ≥N distinct cameras.
        if track.revisit_count > 0 or (
            track.camera_count >= EXTERIOR_TRACK_CLASSIFY_CIRCLING_CAMERAS
        ):
            return "circling"
        # Approach: touches an operator-declared egress-adjacent camera.
        # (Camera-count-only heuristic left as an OPT-IN backstop via
        # EXTERIOR_TRACK_CLASSIFY_APPROACH_CAMERAS; default 0 disables it so
        # pass_by remains the default until either an egress-adjacent camera
        # is declared OR the backstop is explicitly raised.)
        egress_adj = set(EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS)
        if egress_adj and any(c in egress_adj for c in cams):
            return "approach"
        if (
            EXTERIOR_TRACK_CLASSIFY_APPROACH_CAMERAS > 0
            and track.camera_count >= EXTERIOR_TRACK_CLASSIFY_APPROACH_CAMERAS
        ):
            return "approach"
        return "pass_by"

    def path_string(self, track: ExteriorTrack) -> str:
        cams = track.cameras
        # Compact: dedupe consecutive repeats for display.
        compact: list[str] = []
        for c in cams:
            if not compact or compact[-1] != c:
                compact.append(c)
        minutes = int(track.duration_s // 60)
        return f"{' → '.join(compact)} · {minutes} min · {track.label}"

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

    # ---------------- alert-cadence refinement (INV-XP-preserving) ----------------
    def note_alert_dispatched(
        self, camera: str, label: str, now: datetime
    ) -> None:
        """Record that PerimeterAlertManager successfully dispatched an alert.

        Attributes the alert to the OPEN track that owns the last hop on this
        camera (best-effort — first match wins). Used by the same-track
        suppression check.
        """
        for t in self._tracks.get(label, []):
            if t.hops and t.hops[-1].camera == camera:
                t.alert_count += 1
                if t.first_alert_at is None:
                    t.first_alert_at = now
                return

    def same_track_should_suppress(
        self, camera: str, label: str, now: datetime
    ) -> bool:
        """REFINEMENT-only cadence check.

        Returns True iff there is an OPEN track T (adjacent-or-same to
        `camera`, within link window) that has already dispatched >= 1 alert
        AND is classified pass_by. In every other case returns False — the
        default is "let the alert through" so INV-XP is not weakened by a
        classification error or a stale track.

        Kill switch: TRACK_LINK_WINDOW_S == 0 → always False.
        """
        if TRACK_LINK_WINDOW_S <= 0:
            return False
        t = self._find_link_target(label, camera, now)
        if t is None or t.alert_count < 1:
            return False
        cls = self.classify(t)
        # Only pass_by demotes. Approach/circling MUST re-alert (escalate).
        return cls == "pass_by"

    # NM message enrichment
    def latest_track_for_camera(
        self, camera: str, label: str = "person"
    ) -> ExteriorTrack | None:
        """Return the most-recent OPEN track whose last hop matches this camera."""
        best: ExteriorTrack | None = None
        best_t: datetime | None = None
        for t in self._tracks.get(label, []):
            if not t.hops or t.hops[-1].camera != camera:
                continue
            if best_t is None or t.hops[-1].t_last > best_t:
                best_t = t.hops[-1].t_last
                best = t
        return best
