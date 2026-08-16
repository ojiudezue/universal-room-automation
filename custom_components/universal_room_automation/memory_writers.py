"""PATH-ALPHA Scope B — memory-episode writers D4/D5/D6/D7.

Four episodic-tier writers added by the path-α LOST-dissolution cycle:

  * D4 ``phantom_retro`` (room node) — detector-INDEPENDENT retro-phantom.
    When a room's mmWave releases within ``PHANTOM_RETRO_RELEASE_WINDOW_S``
    of a fan-off transition AND the preceding fan-on hold was
    ``≥ PHANTOM_RETRO_MIN_HOLD_S``, we adjudicate the prior occupancy as
    likely fan-driven phantom. Would have captured the 5 latches the
    retro audit identified (2026-08-13 Living Room + Upstairs
    Guestroom ×2 + Jaya Bedroom ×2, plus the Guestroom re-latch).

  * D5 ``away_transition_blocked`` (house node) — coalesced episode
    covering a HELD path-α + path-β block. One row per block-episode,
    NOT per tick. Restart discharge is done on-boot from the DB (any
    prior OPEN row whose ended_at is NULL is force-closed by
    ``reconcile_open_away_block_on_boot``).

  * D6 ``tracker_trust_excluded`` (house node) — edge-writer on the
    excluded-persons set diff. Debounced by ``TRACKER_TRUST_MIN_HOLD_S``
    (default 60s) so BLE/trust flap cannot flood.

  * D7 ``house_state_transition`` (house node) — richer sibling of the
    existing ``house_state_log`` edge. First-tick-post-boot is
    suppressed via the ``trigger="boot"`` classification (per plan H4);
    that transition is stamped in the DB row with ``trigger="boot"``
    and NO memory episode is emitted for it (the test pins the choice).

**Architecture boundary (memory-ineligible, arch §8).** Every writer
here is fire-and-forget through the DB write queue. NOTHING in the
integration reads any of the four new episode types on an actuation
path. Enforced by a consumer-graph test in ``quality/tests/``.

**Rate-bounding is BY CONSTRUCTION.** Each writer has:
  - A named kill switch constant.
  - At least one shape-of-writer bound (window / hold / debounce /
    edge-only) that caps rows per unit time even under a hostile input
    stream (see per-writer docstrings + tests in
    ``test_memory_writers.py``).

All entry points swallow their own exceptions — an episode-write
failure is never allowed to bubble into an actuation path.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from .const import (
    AWAY_BLOCK_EPISODE_ENABLED,
    AWAY_BLOCK_EPISODE_MAX_OPEN_S,
    AWAY_BLOCK_EPISODE_MIN_HOLD_S,
    DOMAIN,
    HOUSE_STATE_TRANSITION_WRITER_ENABLED,
    PHANTOM_RETRO_ENABLED,
    PHANTOM_RETRO_MIN_HOLD_S,
    PHANTOM_RETRO_RELEASE_WINDOW_S,
    TRACKER_TRUST_MIN_HOLD_S,
    TRACKER_TRUST_WRITER_ENABLED,
)

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _slug(room_name: Optional[str]) -> str:
    return (room_name or "").lower().replace(" ", "_").replace("-", "_")


def _db(hass: Any):
    """Return the URA database or None (defensive lookup)."""
    try:
        return hass.data.get(DOMAIN, {}).get("database")
    except Exception:  # noqa: BLE001 — defensive
        return None


def _schedule(hass: Any, coro) -> None:
    """Fire-and-forget: prefer async_create_background_task, else task."""
    try:
        sched = getattr(
            hass, "async_create_background_task", None,
        ) or hass.async_create_task
        sched(coro)
    except Exception:  # noqa: BLE001 — defensive
        try:
            coro.close()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# D4 — phantom_retro
# ---------------------------------------------------------------------------


def write_phantom_retro(
    hass: Any,
    *,
    room_name: str,
    fan_off_ts: datetime,
    mmwave_off_ts: datetime,
    fan_on_since: Optional[datetime],
    room_capabilities: Optional[Mapping[str, bool]] = None,
    fan_entity: Optional[str] = None,
) -> None:
    """Emit a retro-phantom episode when the release/hold predicates hold.

    Rate-bounded BY CONSTRUCTION:
      * Kill switch ``PHANTOM_RETRO_ENABLED`` short-circuits the writer.
      * ``PHANTOM_RETRO_RELEASE_WINDOW_S`` bounds the release window
        (fan-off → mmwave-off delay).
      * ``PHANTOM_RETRO_MIN_HOLD_S`` bounds the minimum fan-on hold —
        brief fan taps do not qualify.
      * ``source_ref = "phantom_retro:<slug>:<fan_off_iso>"`` +
        ``dedup_source_ref=True`` at the DAO prevents a boot-time replay
        of the same edge from double-writing.
    """
    try:
        if not PHANTOM_RETRO_ENABLED:
            return
        if PHANTOM_RETRO_RELEASE_WINDOW_S <= 0:
            return  # kill via window=0
        if fan_off_ts is None or mmwave_off_ts is None:
            return
        release_delay = (mmwave_off_ts - fan_off_ts).total_seconds()
        if release_delay < 0 or release_delay > PHANTOM_RETRO_RELEASE_WINDOW_S:
            return
        hold_s: Optional[float] = None
        if fan_on_since is not None:
            hold_s = (fan_off_ts - fan_on_since).total_seconds()
            if hold_s < PHANTOM_RETRO_MIN_HOLD_S:
                return
        else:
            # No fan_on_since captured (e.g. we came up mid-fan-on) —
            # cannot prove the hold; refuse to emit rather than lie in
            # attrs. Latent detector: appears in tests as "no hold => no
            # emit" invariant.
            return
        db = _db(hass)
        if db is None or not hasattr(db, "log_memory_episode"):
            return
        room_slug = _slug(room_name)
        attrs: dict[str, Any] = {
            "coverage": "fan_release_correlated",
            "fan_off_ts": fan_off_ts.isoformat(),
            "mmwave_off_ts": mmwave_off_ts.isoformat(),
            "release_delay_s": round(release_delay, 3),
            "hold_s": round(hold_s, 3),
        }
        if fan_entity:
            attrs["fan_entity"] = fan_entity
        if room_capabilities is not None:
            attrs["room_capabilities"] = dict(room_capabilities)
        source_ref = f"phantom_retro:{room_slug}:{fan_off_ts.isoformat()}"
        _LOGGER.info(
            "phantom_retro: room=%s release_delay=%.1fs hold=%.1fs "
            "(writer=fan_release_correlation)",
            room_slug, release_delay, hold_s,
        )
        _schedule(
            hass,
            db.log_memory_episode(
                node_id=f"room:{room_slug}",
                episode_type="phantom_retro",
                adjudication="phantom",
                adjudicated_by="fan_release_correlation",
                attrs=attrs,
                source_ref=source_ref,
                dedup_source_ref=True,
            ),
        )
    except Exception:  # noqa: BLE001 — defensive; observational-only
        _LOGGER.debug("phantom_retro writer failed (non-fatal)", exc_info=True)


# ---------------------------------------------------------------------------
# D5 — away_transition_blocked
# ---------------------------------------------------------------------------


class AwayBlockEpisodeTracker:
    """Open/close coalescer for path-α+β blocked episodes.

    * ``note_tick(blocked, snapshot, now)`` is called on every house
      inference tick.
    * The FIRST tick where ``blocked=True`` starts a pending window
      but does NOT open the episode.
    * The episode OPENS when the block has been HELD for
      ``AWAY_BLOCK_EPISODE_MIN_HOLD_S`` seconds continuously.
    * Once opened, further blocked ticks refresh the ``ended_at``
      candidate + rotate open-episode row every
      ``AWAY_BLOCK_EPISODE_MAX_OPEN_S`` (I-M bound).
    * On the first ``blocked=False`` tick the OPEN episode is closed.

    Restart discharge: the OPEN-row identifier is persisted in the DB
    (ended_at IS NULL); on boot the coordinator calls
    ``reconcile_open_away_block_on_boot`` which force-closes any such
    row with ``closed_by="restart"``.
    """

    def __init__(self, hass: Any) -> None:
        self._hass = hass
        self._pending_since: Optional[datetime] = None
        self._pending_snapshot: Optional[Mapping[str, Any]] = None
        self._open_row_id: Optional[int] = None
        self._open_started_at: Optional[datetime] = None
        self._open_source_ref: Optional[str] = None

    # --- introspection helpers for tests ---
    @property
    def open_row_id(self) -> Optional[int]:
        return self._open_row_id

    @property
    def pending_since(self) -> Optional[datetime]:
        return self._pending_since

    async def note_tick(
        self,
        *,
        blocked: bool,
        snapshot: Optional[Mapping[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> None:
        try:
            if not AWAY_BLOCK_EPISODE_ENABLED:
                # Kill switch: also drain any prior OPEN episode so
                # flipping the switch off doesn't leave a stale open row.
                if self._open_row_id is not None:
                    await self._close_open(
                        now=now or datetime.now(timezone.utc),
                        closed_by="disabled",
                    )
                self._pending_since = None
                self._pending_snapshot = None
                return
            _now = now or datetime.now(timezone.utc)
            db = _db(self._hass)
            if db is None or not hasattr(db, "log_memory_episode"):
                return
            if not blocked:
                # First unblocked tick after an OPEN closes the episode.
                if self._open_row_id is not None:
                    await self._close_open(now=_now, closed_by="unblocked")
                self._pending_since = None
                self._pending_snapshot = None
                return
            # blocked path
            if self._pending_since is None and self._open_row_id is None:
                self._pending_since = _now
                self._pending_snapshot = dict(snapshot or {})
                return
            if (
                self._open_row_id is None
                and self._pending_since is not None
                and (_now - self._pending_since).total_seconds()
                >= AWAY_BLOCK_EPISODE_MIN_HOLD_S
            ):
                # Promote pending → OPEN.
                await self._open(
                    started_at=self._pending_since,
                    snapshot=self._pending_snapshot or {},
                    now=_now,
                )
                return
            if (
                self._open_row_id is not None
                and self._open_started_at is not None
                and (_now - self._open_started_at).total_seconds()
                >= AWAY_BLOCK_EPISODE_MAX_OPEN_S
            ):
                # I-M rotation: force-close current + immediately open
                # a fresh episode.
                await self._close_open(
                    now=_now, closed_by="max_open_rotation",
                )
                await self._open(
                    started_at=_now,
                    snapshot=dict(snapshot or {}),
                    now=_now,
                )
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.debug(
                "AwayBlockEpisodeTracker.note_tick failed (non-fatal)",
                exc_info=True,
            )

    async def _open(
        self,
        *,
        started_at: datetime,
        snapshot: Mapping[str, Any],
        now: datetime,
    ) -> None:
        db = _db(self._hass)
        if db is None:
            return
        source_ref = f"away_block:{started_at.isoformat()}"
        attrs = {
            "coverage": "path_alpha_and_beta_blocked",
            "snapshot": dict(snapshot),
        }
        row_id = await db.log_memory_episode(
            node_id="house",
            episode_type="away_transition_blocked",
            adjudication="observed",
            adjudicated_by="away_block_coalescer",
            attrs=attrs,
            source_ref=source_ref,
            started_at=started_at.isoformat(),
            dedup_source_ref=True,
        )
        if row_id:
            self._open_row_id = int(row_id)
            self._open_started_at = started_at
            self._open_source_ref = source_ref
            self._pending_since = None
            self._pending_snapshot = None
            _LOGGER.info(
                "away_transition_blocked: OPEN row=%d started_at=%s "
                "(min_hold=%ds satisfied)",
                self._open_row_id, started_at.isoformat(),
                AWAY_BLOCK_EPISODE_MIN_HOLD_S,
            )

    async def _close_open(
        self, *, now: datetime, closed_by: str,
    ) -> None:
        db = _db(self._hass)
        if db is None or self._open_row_id is None:
            self._open_row_id = None
            self._open_started_at = None
            self._open_source_ref = None
            return
        duration_s = 0.0
        if self._open_started_at is not None:
            duration_s = (now - self._open_started_at).total_seconds()
        try:
            if hasattr(db, "close_memory_episode"):
                await db.close_memory_episode(
                    row_id=self._open_row_id,
                    ended_at=now.isoformat(),
                    close_attrs={
                        "closed_by": closed_by,
                        "duration_s": round(duration_s, 3),
                    },
                )
            else:
                _LOGGER.debug(
                    "away_transition_blocked: close_memory_episode "
                    "helper missing; leaving row=%d open (row is "
                    "restart-reconcilable via ended_at IS NULL).",
                    self._open_row_id,
                )
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.debug(
                "away_transition_blocked close failed (row=%s)",
                self._open_row_id, exc_info=True,
            )
        _LOGGER.info(
            "away_transition_blocked: CLOSE row=%s closed_by=%s "
            "duration_s=%.1f",
            self._open_row_id, closed_by, duration_s,
        )
        self._open_row_id = None
        self._open_started_at = None
        self._open_source_ref = None


async def reconcile_open_away_block_on_boot(hass: Any) -> int:
    """Force-close any OPEN away_transition_blocked row left over across
    a restart. Returns the number of rows reconciled.

    Restart discharge (plan §D5): a pre-restart episode had no chance
    to observe its "unblocked" tick. Rather than leak forever, we close
    on boot with ``closed_by="restart"``; the fresh post-boot
    coalescer state starts empty and will open a NEW episode if the
    block is still real.
    """
    reconciled = 0
    try:
        db = _db(hass)
        if db is None or not hasattr(
            db, "fetch_open_memory_episodes_of_type",
        ):
            return 0
        rows = await db.fetch_open_memory_episodes_of_type(
            "away_transition_blocked",
        )
        if not rows:
            return 0
        now_iso = datetime.now(timezone.utc).isoformat()
        for row in rows:
            try:
                await db.close_memory_episode(
                    row_id=int(row["id"]),
                    ended_at=now_iso,
                    close_attrs={"closed_by": "restart"},
                )
                reconciled += 1
            except Exception:  # noqa: BLE001 — defensive
                _LOGGER.debug(
                    "reconcile_open_away_block_on_boot: close row=%s failed",
                    row.get("id"), exc_info=True,
                )
        if reconciled:
            _LOGGER.info(
                "away_transition_blocked: reconciled %d open episode(s) "
                "on boot (closed_by=restart).",
                reconciled,
            )
    except Exception:  # noqa: BLE001 — defensive
        _LOGGER.debug(
            "reconcile_open_away_block_on_boot failed (non-fatal)",
            exc_info=True,
        )
    return reconciled


# ---------------------------------------------------------------------------
# D6 — tracker_trust_excluded (60s debounce)
# ---------------------------------------------------------------------------


class TrackerTrustExcludedWriter:
    """Edge-writer over the trust-excluded set.

    ``observe(now, excluded_persons)`` is called with the CURRENT set of
    excluded persons + their reason strings. A person's transition
    (excluded ↔ not-excluded) is NOT emitted immediately; it must be
    HELD for ``TRACKER_TRUST_MIN_HOLD_S`` continuously to fire an
    episode. Rate-bound: a person cannot generate more than one row
    per ``TRACKER_TRUST_MIN_HOLD_S`` window even under a 60-flip-per-
    minute hostile input stream — verified by
    ``test_tracker_trust_excluded_60_flip_debounce``.
    """

    def __init__(self, hass: Any) -> None:
        self._hass = hass
        # Per-person committed state (True = excluded, False = trusted).
        self._committed: dict[str, tuple[bool, str]] = {}
        # Pending flip metadata: person -> (target_state, reason, since).
        self._pending: dict[str, tuple[bool, str, datetime]] = {}

    async def observe(
        self,
        *,
        excluded_persons: Mapping[str, str],
        known_persons: Optional[Any] = None,
        now: Optional[datetime] = None,
    ) -> None:
        try:
            if not TRACKER_TRUST_WRITER_ENABLED:
                return
            _now = now or datetime.now(timezone.utc)
            excluded_map = dict(excluded_persons or {})
            # Universe = union of known + committed + currently excluded.
            universe = set(excluded_map.keys()) | set(self._committed.keys())
            if known_persons is not None:
                try:
                    universe |= set(known_persons)
                except Exception:  # noqa: BLE001 — defensive
                    pass
            for person in universe:
                is_excluded_now = person in excluded_map
                reason_now = excluded_map.get(person, "trusted")
                committed = self._committed.get(person)
                if committed is None:
                    # First observation of this person — commit silently
                    # (no episode; this is the "baseline" state).
                    self._committed[person] = (is_excluded_now, reason_now)
                    self._pending.pop(person, None)
                    continue
                committed_state, committed_reason = committed
                if is_excluded_now == committed_state and (
                    reason_now == committed_reason
                    or not is_excluded_now
                ):
                    # No pending flip and state stable → nothing to do.
                    self._pending.pop(person, None)
                    continue
                pending = self._pending.get(person)
                if pending is None or (
                    pending[0] != is_excluded_now
                    or pending[1] != reason_now
                ):
                    # New candidate flip; restart the debounce clock.
                    self._pending[person] = (
                        is_excluded_now, reason_now, _now,
                    )
                    continue
                target_state, target_reason, since = pending
                if (
                    _now - since
                ).total_seconds() >= TRACKER_TRUST_MIN_HOLD_S:
                    # HELD long enough → commit + emit episode.
                    self._committed[person] = (target_state, target_reason)
                    self._pending.pop(person, None)
                    await self._emit(
                        person=person,
                        entered_exclusion=target_state,
                        reason=target_reason,
                        prior_reason=committed_reason,
                        at=_now,
                    )
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.debug(
                "TrackerTrustExcludedWriter.observe failed (non-fatal)",
                exc_info=True,
            )

    async def _emit(
        self,
        *,
        person: str,
        entered_exclusion: bool,
        reason: str,
        prior_reason: str,
        at: datetime,
    ) -> None:
        db = _db(self._hass)
        if db is None or not hasattr(db, "log_memory_episode"):
            return
        attrs = {
            "person": person,
            "entered_exclusion": bool(entered_exclusion),
            "reason": reason,
            "prior_reason": prior_reason,
            "debounce_hold_s": TRACKER_TRUST_MIN_HOLD_S,
        }
        source_ref = (
            f"tracker_trust:{person}:"
            f"{'in' if entered_exclusion else 'out'}:{at.isoformat()}"
        )
        _LOGGER.info(
            "tracker_trust_excluded: person=%s entered=%s reason=%s "
            "(prior=%s, held ≥ %ds)",
            person, entered_exclusion, reason, prior_reason,
            TRACKER_TRUST_MIN_HOLD_S,
        )
        _schedule(
            self._hass,
            db.log_memory_episode(
                node_id="house",
                episode_type="tracker_trust_excluded",
                adjudication="observed",
                adjudicated_by="trust_debounce",
                attrs=attrs,
                source_ref=source_ref,
                dedup_source_ref=True,
            ),
        )


# ---------------------------------------------------------------------------
# D7 — house_state_transition (with first-tick-post-boot suppression)
# ---------------------------------------------------------------------------


def write_house_state_transition(
    hass: Any,
    *,
    old_state: str,
    new_state: str,
    trigger: str,
    confidence: Optional[float],
    snapshot: Optional[Mapping[str, Any]] = None,
) -> None:
    """Emit a ``house_state_transition`` episode mirror.

    First-tick-post-boot suppression (plan H4): a restored→computed
    first tick is NOT a semantic transition. We detect it via the
    ``trigger`` string — the presence coordinator marks its first
    post-restart inference with a distinct trigger (``"boot"`` or
    ``"restore"`` / ``"initial"``). Any such trigger causes the
    episode to be SUPPRESSED (no row) with a debug log; the choice is
    pinned by ``test_house_state_transition_boot_suppression``.
    """
    try:
        if not HOUSE_STATE_TRANSITION_WRITER_ENABLED:
            return
        # Boot-suppression: match a small vocabulary of trigger strings
        # that presence.py uses on the initial post-restart tick. The
        # test pins the vocabulary via a parametrized fixture; any new
        # boot-trigger string added by presence.py should be added here.
        _boot_triggers = (
            "boot",
            "restore",
            "initial",
            "startup",
            "restored",
        )
        trig_norm = (trigger or "").strip().lower()
        if any(tok in trig_norm for tok in _boot_triggers):
            _LOGGER.debug(
                "house_state_transition: suppressed first-tick-post-boot "
                "(old=%s new=%s trigger=%s)",
                old_state, new_state, trigger,
            )
            return
        db = _db(hass)
        if db is None or not hasattr(db, "log_memory_episode"):
            return
        attrs: dict[str, Any] = {
            "old_state": old_state,
            "new_state": new_state,
            "trigger": trigger,
        }
        if confidence is not None:
            try:
                attrs["confidence"] = float(confidence)
            except Exception:  # noqa: BLE001
                pass
        if snapshot:
            attrs["snapshot"] = dict(snapshot)
        now_iso = datetime.now(timezone.utc).isoformat()
        source_ref = f"house_state_transition:{now_iso}:{old_state}->{new_state}"
        _LOGGER.info(
            "house_state_transition: %s -> %s (trigger=%s)",
            old_state, new_state, trigger,
        )
        _schedule(
            hass,
            db.log_memory_episode(
                node_id="house",
                episode_type="house_state_transition",
                adjudication="observed",
                adjudicated_by="house_state_edge",
                attrs=attrs,
                source_ref=source_ref,
                dedup_source_ref=True,
            ),
        )
    except Exception:  # noqa: BLE001 — defensive
        _LOGGER.debug(
            "house_state_transition writer failed (non-fatal)",
            exc_info=True,
        )
