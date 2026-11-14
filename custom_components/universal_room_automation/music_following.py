"""Music following for Universal Room Automation.

When a person walks from a room with music to a room with a speaker, the
music moves with them. MUSIC-FOLLOWING-TRANSFER-REPAIR-1
(docs/planning/PLANNING_music_following_repair.md) rebuilt the pipeline:

* Gates in a fixed order (coordinator, person, same room, BLE certainty,
  stale, house state, cooldown, source, target player, target unavailable,
  source has others, source playing, target already playing). Time spent in
  the first room is never a skip reason (INV-MF-3); the old dwell-arithmetic
  "confidence" gate is gone.
* The source is the room the person left, or, when that room has no playing
  speaker, the last room they left with one within the lookback (hallway
  walk-through).
* Three paths, in order: Music Assistant ``transfer_queue`` (target = the
  destination MA player, ``source_player`` = the playing MA player), native
  ``media_player.join`` (``entity_id`` = the group leader = the source side),
  ``play_media`` + seek. One resolver returns the path and its reason.
* Success only when the room's configured speaker (the primary) reads
  ``playing`` after MF's own call (INV-MF-1, INV-MF-6). In ``move`` mode the
  old room fades to 10 percent, is removed after the release delay and gets
  its volume back; a fade is undone at once when the new room does not play.
* One transfer in flight per person; a newer room change supersedes it and
  its cleanup restores every volume it took (INV-MF-5).
* Every room change ends in exactly one outcome from ``MF_OUTCOMES``, counted,
  logged as one ``MF decision`` line and, when two speakers are involved,
  written to room memory (INV-MF-2).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from homeassistant.core import HomeAssistant
from homeassistant.components.media_player import (
    ATTR_MEDIA_POSITION,
    ATTR_MEDIA_VOLUME_LEVEL,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    SERVICE_MEDIA_PLAY,
    SERVICE_VOLUME_SET,
)
from homeassistant.const import STATE_PLAYING
from homeassistant.util import dt as dt_util

from . import const as _c
from .transitions import RoomTransition
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# HA MediaPlayerEntityFeature bits (homeassistant/components/media_player/
# const.py: PLAY_MEDIA = 512, GROUPING = 524288). Numeric so legacy test
# stubs of the media_player module keep importing this file.
_FEATURE_PLAY_MEDIA = 512
_FEATURE_GROUPING = 524288

_UNAVAILABLE_STATES = ("unavailable", "unknown")
_STOPPED_STATES = ("paused", "idle", "off", "standby", "on")


def _person_key(value: str) -> str:
    """Canonicalize a person identifier for cross-form comparison.

    The enabled-set is keyed by person entity_id (``person.oji_udezue``)
    while the transition event carries the display name (``"Oji Udezue"``).
    Both map to the casefolded ``"oji udezue"``.
    """
    if not value:
        return ""
    s = str(value)
    if s.startswith("person."):
        s = s[len("person."):]
    return s.replace("_", " ").strip().casefold()


def _slug(room: str) -> str:
    return str(room or "").lower().replace(" ", "_")


# Platform identifiers
PLATFORM_SONOS = "sonos"
PLATFORM_LINKPLAY = "linkplay"
PLATFORM_WIIM = "wiim"
PLATFORM_DENON = "denonavr"
PLATFORM_HEOS = "heos"
PLATFORM_MASS = "music_assistant"
PLATFORM_GENERIC = "generic"
# Kept for the area-player picker (prefer a multiroom speaker over a TV).
MULTIROOM_PLATFORMS = {
    PLATFORM_SONOS, PLATFORM_LINKPLAY, PLATFORM_WIIM, PLATFORM_DENON,
    PLATFORM_HEOS, PLATFORM_MASS,
}

# Paths
PATH_MA = "ma"
PATH_JOIN = "join"
PATH_GENERIC = "generic"

# ---------------------------------------------------------------------------
# Outcome registry (D4): the ONE source for stats init, the skip set, the
# transfer-attempt keys and outcomes_today.
# ---------------------------------------------------------------------------
MF_SUCCESS_OUTCOMES = ("success", "success_nudged")
MF_OUTCOMES = (
    "success",
    "success_nudged",
    "verify_failed",
    "failed",
    "coordinator_disabled",
    "person_not_enabled",
    "same_room",
    "ble_low_confidence",
    "stale_transition",
    "cooldown_blocked",
    "ping_pong_suppressed",
    "no_source_player",
    "no_target_player",
    "target_unavailable",
    "source_has_others",
    "source_not_playing",
    "active_playback_blocked",
    "sleep_suppressed",
    "night_suppressed",
    "hazard_blocked",
    "superseded",
    "returned_in_flight",
    "exception",
)
# Counters that are not move outcomes.
MF_COUNTERS = ("bonus_join_failed", "ble_input_missing", "unknown_outcome")
# Outcomes that are music-involved transfer attempts (success-rate denominator).
MF_TRANSFER_KEYS = (
    "success", "success_nudged", "verify_failed", "failed",
    "active_playback_blocked",
)
_NOT_SKIPS = frozenset(MF_SUCCESS_OUTCOMES)
MF_SKIP_OUTCOMES = frozenset(o for o in MF_OUTCOMES if o not in _NOT_SKIPS)

# Fields of the one-line decision log (D5.1), in order.
MF_DECISION_FIELDS = (
    "person", "from", "to", "source_room", "source_player", "target_player",
    "path", "outcome", "reason", "ble_confidence", "dwell_s",
    "path_type", "follow_mode", "call_ms", "verify_ms", "target_state",
    "knob",
)


@dataclass
class _Transfer:
    """One room change and, when it gets that far, its transfer."""

    person_id: str
    person_key: str
    from_room: str
    to_room: str
    transition: Optional[RoomTransition] = None
    transition_ts: Optional[datetime] = None
    decision: dict = field(default_factory=dict)
    source_room: str = ""
    source_player: str = ""
    target_player: str = ""
    source_eff: str = ""   # entity the path addresses on the source side
    target_eff: str = ""   # entity the path addresses on the target side
    path: str = ""
    leader: str = ""
    phase: str = "pending"  # pending/evaluating/calling/verifying/releasing/done
    target_started: bool = False
    saved: dict = field(default_factory=dict)  # player -> volume THIS move took
    outcome: str = ""
    superseded_to: Optional[str] = None
    follow_mode: str = _c.DEFAULT_MF_FOLLOW_MODE
    sent_content_id: Optional[str] = None
    decided: Optional[asyncio.Event] = None
    task: Optional[asyncio.Task] = None
    # The house-wide transfer lock is held only for the gates and the start
    # call, never through the verify / release waits (review B1).
    lock_held: bool = False
    # Set before the source stop is issued (review B5): a bounce back to the
    # source after this point must not also stop the target.
    source_released: bool = False
    # The outcome a cancellation books ("superseded"; "hazard_blocked" when a
    # safety / security stop cancelled the move, review B2).
    cancel_outcome: str = "superseded"
    # Join issued between Music Assistant players (extend mode, review A-H2).
    via_ma: bool = False


class MusicFollowing:
    """Seamless music following between rooms (see module docstring)."""

    # Kept as class attributes for back-compat readers.
    FADE_OUT_VOLUME = _c.MF_FADE_TARGET_VOLUME
    _SKIP_OUTCOMES = MF_SKIP_OUTCOMES
    _TRANSFER_KEYS = MF_TRANSFER_KEYS

    def __init__(self, hass: HomeAssistant, config: dict, transition_detector) -> None:
        self.hass = hass
        self.config = config
        self.transition_detector = transition_detector

        self._enabled_persons: set[str] = set()
        self._person_follow_prefs: dict[str, bool] = {}

        # House-wide lock over the gates + the start call only (two people
        # moving between the same rooms are serialised there); released
        # before the verify / release waits (review B1). One in flight per
        # person (INV-MF-5).
        self._transfer_lock = asyncio.Lock()
        self._inflight: dict[str, _Transfer] = {}
        self._transfer_tasks: set[asyncio.Task] = set()
        self._last_superseded: dict[str, dict] = {}

        # Saved pre-fade volumes; every restore pops (no leak). Persisted to
        # an HA Store on every change and put back at the next start (B3).
        self._saved_volumes: dict[str, float] = {}
        self._volume_store = None
        # Every speaker music following itself started (primaries found by
        # area, MA twins, bonus players): the hazard stop covers them (A-M1).
        self._started_players: set[str] = set()
        # Monotonic deadline until which new moves are refused after a
        # critical safety / security stop (B2); 0 = no block.
        self._hazard_until: float = 0.0

        self._last_transfer_time: dict[str, datetime] = {}
        self._last_transfer_target: dict[str, str] = {}
        # person_key -> (room, player, monotonic ts) of the last room left
        # with a playing speaker (D2 lookback).
        self._recent_source: dict[str, tuple[str, str, float]] = {}

        # leader -> followers MF formed (native join path).
        self._active_groups: dict[str, set[str]] = {}
        # room slug -> [(leader, bonus player)] joined after a success.
        self._bonus_joined: dict[str, list[tuple[str, str]]] = {}
        self._cleanup_tasks: set[asyncio.Task] = set()
        self._episode_tasks: set[asyncio.Task] = set()
        self._reversal_watch: dict[str, Callable] = {}

        # House-state gate.
        self._current_house_state: str = ""
        self._sleep_suppress: bool = _c.DEFAULT_MF_SLEEP_SUPPRESS
        self._night_suppress_mode: str = _c.DEFAULT_MF_NIGHT_SUPPRESS_MODE
        self._warned_dwell_only_no_surface: bool = False

        # Live knobs (D7): one place, set by apply_config().
        self._cooldown_s: float = float(_c.DEFAULT_MF_COOLDOWN_SECONDS)
        self._verify_delay_s: float = float(_c.DEFAULT_MF_VERIFY_DELAY)
        self._release_delay_s: float = float(_c.DEFAULT_MF_UNJOIN_DELAY)
        self._position_offset_s: float = float(_c.DEFAULT_MF_POSITION_OFFSET)
        self._stale_transition_seconds: float = float(_c.DEFAULT_MF_STALE_TRANSITION_SECONDS)
        self._follow_mode: str = _c.DEFAULT_MF_FOLLOW_MODE
        self._bonus_joins: bool = _c.DEFAULT_MF_BONUS_JOINS
        self._ble_certainty: str = _c.DEFAULT_MF_MIN_BLE_CONFIDENCE
        self._lookback_s: float = float(_c.DEFAULT_MF_SOURCE_LOOKBACK_SECONDS)
        self._ping_pong_s: float = float(_c.DEFAULT_MF_PING_PONG_WINDOW)
        self._knobs_applied_at: str = ""

        # Injectable clock / sleep (tests drive a fake clock).
        self._sleep = asyncio.sleep
        self._monotonic = time.monotonic

        # D7.5: per-person preference hook (None = current behaviour).
        self._preference_provider: Optional[Callable] = None

        # Stats + observability.
        self._state: str = "idle"
        self._transfer_stats: dict[str, int] = {
            k: 0 for k in (*MF_OUTCOMES, *MF_COUNTERS)
        }
        self._stats_date: str = ""
        self._last_transfer_from = ""
        self._last_transfer_to = ""
        self._last_transfer_person = ""
        self._last_transfer_time_iso = ""
        self._last_transfer_result = ""
        self._last_skip_reason = ""
        self._last_skip_from_room = ""
        self._last_skip_to_room = ""
        self._last_skip_time_iso = ""
        self._target_unavailable_skips = 0
        self._last_decision: dict = {}
        self._recent_decisions: list[tuple[float, str, bool]] = []
        self._accuracy_live = {"successes": 0, "reversals": 0,
                               "by_kind": {}, "by_pair": {}}
        self._accuracy_7d: Optional[dict] = None
        self._diagnostic_listeners: list = []

        _LOGGER.info("MusicFollowing initialized")

    async def async_init(self) -> None:
        """Subscribe to transitions; put back volumes a restart left faded."""
        self.transition_detector.async_add_listener(self._on_person_transition)
        await self.async_replay_saved_volumes()
        _LOGGER.info(
            "MusicFollowing ready: follow_mode=%s, fade_volume=%.2f",
            self._follow_mode, _c.MF_FADE_TARGET_VOLUME,
        )

    # ------------------------------------------------------------------
    # Restart-safe saved volumes (review B3)
    # ------------------------------------------------------------------

    def _volumes_store(self):
        if self._volume_store is None:
            from homeassistant.helpers.storage import Store  # noqa: PLC0415
            self._volume_store = Store(self.hass, 1, f"{DOMAIN}.mf_saved_volumes")
        return self._volume_store

    def _persist_volumes(self) -> None:
        """Schedule a write of the CURRENT saved volumes (latest wins)."""
        try:
            self._volumes_store().async_delay_save(
                lambda: {"volumes": dict(self._saved_volumes)}, 0)
        except Exception:  # noqa: BLE001 - persistence never blocks a move
            _LOGGER.debug("MusicFollowing: saved-volume persist failed", exc_info=True)

    def _remember_volume(self, rec: _Transfer, player: str, volume: float) -> None:
        if player not in self._saved_volumes:
            self._saved_volumes[player] = volume
        rec.saved[player] = self._saved_volumes[player]
        self._persist_volumes()

    async def async_replay_saved_volumes(self) -> int:
        """Put back pre-fade volumes persisted before a restart / crash.

        A speaker still reading the fade level (within
        MF_RESTORE_FADE_TOLERANCE) gets its volume back; one turned up by
        hand is left alone; one not loaded yet stays pending and is retried
        at the next room change. Returns the number restored.
        """
        try:
            data = await self._volumes_store().async_load()
        except Exception:  # noqa: BLE001
            _LOGGER.warning("MusicFollowing: could not read saved volumes", exc_info=True)
            return 0
        stored = (data or {}).get("volumes") if isinstance(data, dict) else None
        if isinstance(stored, dict):
            for eid, vol in stored.items():
                try:
                    self._saved_volumes.setdefault(str(eid), float(vol))
                except (TypeError, ValueError):
                    continue
        return await self._replay_pending_volumes()

    async def _replay_pending_volumes(self) -> int:
        if not self._saved_volumes or any(
                r.task is not None and not r.task.done() for r in self._inflight.values()):
            return 0
        restored = 0
        changed = False
        for eid in list(self._saved_volumes):
            st = self.hass.states.get(eid)
            if st is None or st.state in _UNAVAILABLE_STATES:
                continue                       # not loaded yet: keep pending
            try:
                now_vol = float((st.attributes or {}).get(ATTR_MEDIA_VOLUME_LEVEL))
            except (TypeError, ValueError):
                now_vol = None
            if now_vol is not None and abs(now_vol - _c.MF_FADE_TARGET_VOLUME) <= _c.MF_RESTORE_FADE_TOLERANCE:
                await self._restore_volume(eid)
                restored += 1
            else:
                self._saved_volumes.pop(eid, None)   # changed by hand: keep it
                changed = True
        if changed:
            self._persist_volumes()
        return restored

    # ==================================================================
    # Persons
    # ==================================================================

    def enable_for_person(self, person_id: str) -> None:
        key = _person_key(person_id)
        self._enabled_persons = {p for p in self._enabled_persons if _person_key(p) != key}
        self._enabled_persons.add(person_id)
        _LOGGER.info("Music following enabled for: %s", person_id)

    def disable_for_person(self, person_id: str) -> None:
        key = _person_key(person_id)
        self._enabled_persons = {p for p in self._enabled_persons if _person_key(p) != key}
        _LOGGER.info("Music following disabled for: %s", person_id)

    def sync_enabled_persons(self, tracked_persons: list[str]) -> None:
        """Reconcile the enabled set against tracked persons, keeping OFF prefs."""
        wanted = set(tracked_persons or [])
        wanted_keys = {_person_key(p) for p in wanted}
        prefs = self._person_follow_prefs
        off_keys = {_person_key(k) for k, v in prefs.items() if v is False}
        target = {p for p in wanted if _person_key(p) not in off_keys}
        added = {
            p for p in target
            if not any(_person_key(x) == _person_key(p) for x in self._enabled_persons)
        }
        removed = {p for p in self._enabled_persons if _person_key(p) not in wanted_keys}
        self._enabled_persons = (self._enabled_persons - removed) | added
        for p in list(prefs.keys()):
            if _person_key(p) not in wanted_keys:
                prefs.pop(p, None)
        if added or removed:
            _LOGGER.info(
                "MusicFollowing: re-synced enabled_persons (added=%s, removed=%s, total=%d)",
                sorted(added), sorted(removed), len(self._enabled_persons),
            )

    def _person_enabled(self, person_id: str) -> bool:
        if person_id in self._enabled_persons:
            return True
        key = _person_key(person_id)
        return any(_person_key(p) == key for p in self._enabled_persons)

    # ==================================================================
    # Live config (D7)
    # ==================================================================

    def update_house_state(self, new_state: str) -> None:
        prev = self._current_house_state
        self._current_house_state = new_state or ""
        if prev != self._current_house_state:
            _LOGGER.debug("MusicFollowing: house_state %s → %s",
                          prev or "?", self._current_house_state)

    def update_gate_config(
        self,
        sleep_suppress: Optional[bool] = None,
        night_suppress_mode: Optional[str] = None,
        stale_transition_seconds: Optional[float] = None,
    ) -> None:
        """Back-compat wrapper over apply_config for the three gate keys."""
        opts: dict = {}
        if sleep_suppress is not None:
            opts[_c.CONF_MF_SLEEP_SUPPRESS] = sleep_suppress
        if night_suppress_mode is not None:
            opts[_c.CONF_MF_NIGHT_SUPPRESS_MODE] = night_suppress_mode
        if stale_transition_seconds is not None:
            opts[_c.CONF_MF_STALE_TRANSITION_SECONDS] = stale_transition_seconds
        self.apply_config(opts)

    def apply_config(self, opts) -> set[str]:
        """Apply Music Following knobs from a (CM options) mapping, in place.

        Only keys present in ``opts`` change. Returns the keys applied. The
        ping-pong window is pushed to the TransitionDetector, where the
        suppression runs. Invalid values are ignored (logged), never raised.
        """
        applied: set[str] = set()
        opts = dict(opts or {})

        def _num(key, attr, lo=0.0):
            if key not in opts:
                return
            try:
                setattr(self, attr, max(lo, float(opts[key])))
                applied.add(key)
            except (TypeError, ValueError):
                _LOGGER.warning("MusicFollowing: ignoring invalid %s=%r", key, opts[key])

        _num(_c.CONF_MF_COOLDOWN_SECONDS, "_cooldown_s")
        _num(_c.CONF_MF_VERIFY_DELAY, "_verify_delay_s")
        _num(_c.CONF_MF_RELEASE_DELAY, "_release_delay_s")
        _num(_c.CONF_MF_POSITION_OFFSET, "_position_offset_s")
        _num(_c.CONF_MF_STALE_TRANSITION_SECONDS, "_stale_transition_seconds")
        _num(_c.CONF_MF_SOURCE_LOOKBACK_SECONDS, "_lookback_s")
        if _c.CONF_MF_SLEEP_SUPPRESS in opts:
            self._sleep_suppress = bool(opts[_c.CONF_MF_SLEEP_SUPPRESS])
            applied.add(_c.CONF_MF_SLEEP_SUPPRESS)
        if _c.CONF_MF_NIGHT_SUPPRESS_MODE in opts:
            self._night_suppress_mode = str(opts[_c.CONF_MF_NIGHT_SUPPRESS_MODE])
            applied.add(_c.CONF_MF_NIGHT_SUPPRESS_MODE)
        if _c.CONF_MF_FOLLOW_MODE in opts:
            mode = str(opts[_c.CONF_MF_FOLLOW_MODE])
            if mode in _c.MF_FOLLOW_MODES:
                self._follow_mode = mode
                applied.add(_c.CONF_MF_FOLLOW_MODE)
            else:
                _LOGGER.warning("MusicFollowing: ignoring invalid follow mode %r", mode)
        if _c.CONF_MF_BONUS_JOINS in opts:
            self._bonus_joins = bool(opts[_c.CONF_MF_BONUS_JOINS])
            applied.add(_c.CONF_MF_BONUS_JOINS)
        if _c.CONF_MF_MIN_BLE_CONFIDENCE in opts:
            val = str(opts[_c.CONF_MF_MIN_BLE_CONFIDENCE])
            if val == _c.MF_BLE_CERTAINTY_STRICT_RETIRED:
                # Distance gate dropped 2026-11-14: a saved "strict" is normal.
                val = _c.MF_BLE_CERTAINTY_NORMAL
            if val in _c.MF_BLE_CERTAINTIES:
                self._ble_certainty = val
                applied.add(_c.CONF_MF_MIN_BLE_CONFIDENCE)
            else:
                _LOGGER.warning("MusicFollowing: ignoring invalid certainty %r", val)
        if _c.CONF_MF_PING_PONG_WINDOW in opts:
            try:
                self._ping_pong_s = max(0.0, float(opts[_c.CONF_MF_PING_PONG_WINDOW]))
                setter = getattr(self.transition_detector, "set_ping_pong_window", None)
                if callable(setter):
                    setter(self._ping_pong_s)
                applied.add(_c.CONF_MF_PING_PONG_WINDOW)
            except (TypeError, ValueError):
                _LOGGER.warning("MusicFollowing: ignoring invalid ping-pong window")
        if applied:
            self._knobs_applied_at = dt_util.now().isoformat()
            _LOGGER.info("MusicFollowing knobs applied: %s", self.knobs())
        return applied

    def knobs(self) -> dict:
        return {
            "follow_mode": self._follow_mode,
            "release_delay_s": self._release_delay_s,
            "bonus_joins": self._bonus_joins,
            "location_certainty": self._ble_certainty,
            "lookback_s": self._lookback_s,
            "cooldown_s": self._cooldown_s,
            "ping_pong_s": self._ping_pong_s,
            "verify_delay_s": self._verify_delay_s,
            "position_offset_s": self._position_offset_s,
            "stale_transition_s": self._stale_transition_seconds,
            "sleep_suppress": self._sleep_suppress,
            "night_suppress_mode": self._night_suppress_mode,
        }

    def set_preference_provider(self, provider: Optional[Callable]) -> None:
        """D7.5: register ``provider(person_key, context) -> dict | None``.

        Returned keys used today: ``follow_mode`` (one of MF_FOLLOW_MODES)
        and ``target_volume`` (0..1). ``None`` (default) = current behaviour.
        Arrival music (arc step 8) and PERSON-PROFILE-PREFERENCES-1 build on it.
        """
        self._preference_provider = provider

    # ------------------------------------------------------------------
    # Arc step 8 welcome scene seam (PLANNING_identity_actions_v6.md §5.5,
    # §10.1). The room entry path (automation._maybe_activate_slot_scene,
    # day / evening caller only) asks this DECISION call for a per-person
    # scene before the room's slot scene. Until D3's decision logic lands
    # it always returns None, so the entry path stays byte-identical.
    # ------------------------------------------------------------------
    def arrival_scene_for(self, room_entry_id: str) -> Optional[str]:
        """Welcome scene to use for this room's entry, or None (D3 stub)."""
        return None

    def note_arrival_scene_result(self, room_entry_id: str, applied: bool) -> None:
        """Entry path reports whether the returned scene ran (D3 stub)."""
        return None

    def _preferences_for(self, rec: _Transfer) -> dict:
        provider = self._preference_provider
        if provider is None:
            return {}
        try:
            prefs = provider(rec.person_key, {
                "from_room": rec.from_room, "to_room": rec.to_room,
                "source_room": rec.source_room,
            })
            return dict(prefs) if isinstance(prefs, dict) else {}
        except Exception:  # noqa: BLE001 - a broken provider never blocks a move
            _LOGGER.warning("MusicFollowing: preference provider failed", exc_info=True)
            return {}

    async def async_teardown(self) -> None:
        """Cancel in-flight work, restore volumes, flush episode writes."""
        tasks = [t for t in list(self._transfer_tasks) if not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            try:
                await asyncio.wait(tasks, timeout=5)
            except Exception:  # noqa: BLE001
                pass
        self._transfer_tasks.clear()
        self._inflight.clear()
        for task in list(self._cleanup_tasks):
            try:
                task.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._cleanup_tasks.clear()
        for unsub in list(self._reversal_watch.values()):
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._reversal_watch.clear()
        if self._episode_tasks:
            pending = [t for t in self._episode_tasks if not t.done()]
            if pending:
                try:
                    await asyncio.wait(pending, timeout=5)
                except Exception:  # noqa: BLE001
                    pass
            self._episode_tasks.clear()
        # Review B4: a second cancel (this teardown) can land while a
        # superseded move's cleanup awaits a service call, so its restore
        # never runs. Put back every volume still saved before clearing.
        for eid in list(self._saved_volumes):
            await self._restore_volume(eid)
        self._saved_volumes.clear()
        self._active_groups.clear()
        self._bonus_joined.clear()
        self._last_transfer_time.clear()
        self._last_transfer_target.clear()
        self._recent_source.clear()
        self._last_superseded.clear()
        _LOGGER.info("MusicFollowing.async_teardown: state cleared")

    # ==================================================================
    # Stats, decisions, observability (D4/D5)
    # ==================================================================

    def add_diagnostic_listener(self, listener) -> Callable[[], None]:
        """Register a listener; returns its unsubscribe (D7.2)."""
        self._diagnostic_listeners.append(listener)

        def _unsub() -> None:
            try:
                self._diagnostic_listeners.remove(listener)
            except ValueError:
                pass

        return _unsub

    def _notify_listeners(self) -> None:
        for listener in list(self._diagnostic_listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001
                pass

    def _record_stat(self, outcome: str, person_id: str = "", from_room: str = "",
                     to_room: str = "") -> None:
        """Count one outcome (or counter) and notify listeners."""
        self._roll_day()
        if outcome in self._transfer_stats:
            self._transfer_stats[outcome] += 1
        else:
            _LOGGER.warning("MusicFollowing: unknown outcome %r counted as unknown_outcome", outcome)
            self._transfer_stats["unknown_outcome"] += 1
        if outcome in MF_OUTCOMES:
            if person_id:
                self._last_transfer_person = person_id
            if from_room:
                self._last_transfer_from = from_room
            if to_room:
                self._last_transfer_to = to_room
            self._last_transfer_result = outcome
            self._last_transfer_time_iso = dt_util.now().isoformat()
            if outcome in MF_SKIP_OUTCOMES:
                self._last_skip_reason = outcome
                self._last_skip_from_room = from_room
                self._last_skip_to_room = to_room
                self._last_skip_time_iso = dt_util.now().isoformat()
            if outcome == "target_unavailable":
                self._target_unavailable_skips += 1
        self._notify_listeners()

    def _roll_day(self) -> None:
        """Daily reset of the counters (local day)."""
        today = dt_util.now().strftime("%Y-%m-%d")
        if today != self._stats_date:
            for key in self._transfer_stats:
                self._transfer_stats[key] = 0
            self._stats_date = today
            self._target_unavailable_skips = 0

    def _count(self, counter: str) -> None:
        self._roll_day()
        self._transfer_stats[counter] = self._transfer_stats.get(counter, 0) + 1

    def success_count(self) -> int:
        return sum(self._transfer_stats.get(k, 0) for k in MF_SUCCESS_OUTCOMES)

    def transfer_attempts(self) -> int:
        return sum(self._transfer_stats.get(k, 0) for k in MF_TRANSFER_KEYS)

    def record_ping_pong_suppressed(self, person_id: str, from_room: str, to_room: str) -> None:
        """Called by TransitionDetector for a suppressed return leg."""
        rec = _Transfer(person_id=person_id, person_key=_person_key(person_id),
                        from_room=from_room, to_room=to_room)
        rec.decision["knob"] = f"ping_pong={self._ping_pong_s:g}"
        self._finish(rec, "ping_pong_suppressed")

    def _new_record(self, transition: RoomTransition) -> _Transfer:
        rec = _Transfer(
            person_id=transition.person_id,
            person_key=_person_key(transition.person_id),
            from_room=transition.from_room,
            to_room=transition.to_room,
            transition=transition,
            transition_ts=getattr(transition, "timestamp", None),
            follow_mode=self._follow_mode,
        )
        rec.decided = asyncio.Event()
        rec.decision.update({
            "person": transition.person_id,
            "from": transition.from_room,
            "to": transition.to_room,
            "dwell_s": getattr(transition, "duration_seconds", None),
            "path_type": getattr(transition, "path_type", None),
            "transition_confidence": getattr(transition, "confidence", None),
            "follow_mode": self._follow_mode,
        })
        return rec

    def _finish(self, rec: _Transfer, outcome: str, reason: str = "") -> None:
        """Book THE one outcome of a room change (INV-MF-2)."""
        if rec.outcome:
            return
        rec.outcome = outcome
        d = rec.decision
        d.setdefault("person", rec.person_id)
        d.setdefault("from", rec.from_room)
        d.setdefault("to", rec.to_room)
        d["outcome"] = outcome
        if reason:
            d["reason"] = reason
        d["source_room"] = rec.source_room or d.get("source_room", "")
        d["source_player"] = rec.source_player or d.get("source_player", "")
        d["target_player"] = rec.target_player or d.get("target_player", "")
        d["path"] = rec.path or d.get("path", "")
        d["follow_mode"] = rec.follow_mode
        d["ts"] = dt_util.now().isoformat()
        self._last_decision = dict(d)
        _LOGGER.info(
            "MF decision %s",
            " ".join(f"{k}={d.get(k, '')}" for k in MF_DECISION_FIELDS),
        )
        self._record_stat(outcome, rec.person_id, rec.from_room, rec.to_room)
        candidate = bool(d.get("source_player")) and bool(d.get("target_player"))
        now_m = self._monotonic()
        self._recent_decisions.append((now_m, outcome, bool(d.get("source_playing")) and candidate))
        cutoff = now_m - _c.MF_TRIPWIRE_WINDOW_S
        while self._recent_decisions and self._recent_decisions[0][0] < cutoff:
            self._recent_decisions.pop(0)
        if outcome in MF_SUCCESS_OUTCOMES:
            self._accuracy_live["successes"] += 1
        if candidate:
            self._write_decision_episode(rec)
        if rec.decided is not None:
            rec.decided.set()

    def get_diagnostic_data(self) -> dict:
        transfers = self.transfer_attempts()
        successes = self.success_count()
        acc = self.accuracy()
        return {
            "state": self._state,
            "current_house_state": self._current_house_state or "unknown",
            "active_followers": sorted(self._enabled_persons),
            "last_transfer_from": self._last_transfer_from,
            "last_transfer_to": self._last_transfer_to,
            "last_transfer_person": self._last_transfer_person,
            "last_transfer_time": self._last_transfer_time_iso,
            "last_transfer_result": self._last_transfer_result,
            "transfers_today": transfers,
            "transfer_failures_today": transfers - successes,
            "transfer_success_rate": round(successes / transfers * 100, 1) if transfers > 0 else 0.0,
            "active_groups": {k: sorted(v) for k, v in self._active_groups.items()},
            "last_skip_reason": self._last_skip_reason,
            "last_skip_from_room": self._last_skip_from_room,
            "last_skip_to_room": self._last_skip_to_room,
            "last_skip_time": self._last_skip_time_iso,
            "target_unavailable_today": self._transfer_stats.get("target_unavailable", 0),
            "sleep_suppressed_today": self._transfer_stats.get("sleep_suppressed", 0),
            "night_suppressed_today": self._transfer_stats.get("night_suppressed", 0),
            "source_has_others_today": self._transfer_stats.get("source_has_others", 0),
            "stale_transition_today": self._transfer_stats.get("stale_transition", 0),
            "outcomes_today": {k: self._transfer_stats.get(k, 0) for k in MF_OUTCOMES},
            "counters_today": {k: self._transfer_stats.get(k, 0) for k in MF_COUNTERS},
            "last_decision": dict(self._last_decision),
            "knobs": self.knobs(),
            "knobs_applied_at": self._knobs_applied_at,
            "accuracy_pct": acc.get("pct"),
        }

    def accuracy(self) -> dict:
        """Share of successes not reversed: 7-day roll-up when present, else live."""
        if self._accuracy_7d and self._accuracy_7d.get("successes"):
            src = dict(self._accuracy_7d)
            src["window"] = "7d"
        else:
            src = dict(self._accuracy_live)
            src["window"] = "since_start"
        s = int(src.get("successes") or 0)
        r = int(src.get("reversals") or 0)
        src["pct"] = round(100.0 * max(0, s - r) / s, 1) if s > 0 else None
        return src

    # ==================================================================
    # Kill switch
    # ==================================================================

    def _coordinator_enabled(self) -> bool:
        """True iff the Music Following coordinator switch is ON (fail-safe False)."""
        try:
            for ce in self.hass.config_entries.async_entries(DOMAIN):
                if ce.data.get(_c.CONF_ENTRY_TYPE) == _c.ENTRY_TYPE_COORDINATOR_MANAGER:
                    from .coordinator_gate import coordinator_should_run  # noqa: PLC0415
                    merged = {**ce.data, **ce.options}
                    return coordinator_should_run(merged, "music_following")
        except Exception:  # noqa: BLE001
            return False
        return False

    # ==================================================================
    # Entry: one room change
    # ==================================================================

    async def _on_person_transition(self, transition: RoomTransition) -> None:
        """Handle one room change. Returns once its outcome is booked.

        The release step of a ``move`` keeps running in the background task
        so the transition detector is not held for the release delay.
        """
        rec = self._new_record(transition)
        if not self._coordinator_enabled():
            self._finish(rec, "coordinator_disabled")
            return
        if not self._person_enabled(rec.person_id):
            self._finish(rec, "person_not_enabled")
            return
        if rec.from_room == rec.to_room:
            self._finish(rec, "same_room")
            return
        if self.hazard_active():
            rec.decision["knob"] = f"hazard_block={_c.MF_HAZARD_BLOCK_S:g}"
            self._finish(rec, "hazard_blocked")
            return
        if self._saved_volumes:
            # B3: a volume a restart left faded on a speaker that was not
            # loaded at start.
            await self._replay_pending_volumes()
        # D2: remember the room left if its speaker plays (before any gate).
        await self._stamp_recent_source(rec)

        old = self._inflight.get(rec.person_key)
        old_task = None
        if old is not None and old.task is not None and not old.task.done():
            old.superseded_to = rec.to_room
            old_task = old.task
            old_task.cancel()
        self._inflight[rec.person_key] = rec
        task = self._spawn(self._run(rec, old_task), f"ura_mf_transfer_{rec.person_key}")
        rec.task = task

        def _on_done(_t, rec=rec) -> None:
            # A task cancelled before its first step never runs its own
            # finally: book it here so every room change has one outcome.
            if not rec.outcome:
                self._finish(rec, rec.cancel_outcome, self._cancel_reason(rec))
            if self._inflight.get(rec.person_key) is rec:
                self._inflight.pop(rec.person_key, None)
            rec.decided.set()

        task.add_done_callback(_on_done)
        await rec.decided.wait()

    def _spawn(self, coro, name: str) -> asyncio.Task:
        try:
            task = self.hass.async_create_task(coro, name=name, eager_start=False)
        except TypeError:
            task = self.hass.async_create_task(coro, name=name)
        if not isinstance(task, asyncio.Future):
            # A test double that does not schedule: run it on the loop.
            task = asyncio.ensure_future(coro)
        self._transfer_tasks.add(task)
        task.add_done_callback(self._transfer_tasks.discard)
        return task

    async def async_wait_idle(self) -> None:
        """Wait for every in-flight transfer task (tests, teardown)."""
        while True:
            pending = [t for t in self._transfer_tasks if not t.done()]
            if not pending:
                return
            await asyncio.wait(pending)

    async def _lock(self, rec: _Transfer) -> None:
        await self._transfer_lock.acquire()
        rec.lock_held = True

    def _unlock(self, rec: _Transfer) -> None:
        """Release the house-wide lock if ``rec`` holds it (idempotent)."""
        if rec.lock_held:
            rec.lock_held = False
            self._transfer_lock.release()

    def _cancel_reason(self, rec: _Transfer) -> str:
        if rec.cancel_outcome == "hazard_blocked":
            return "hazard_stop"
        return f"by_room={rec.superseded_to}"

    async def _run(self, rec: _Transfer, old_task: Optional[asyncio.Task]) -> None:
        try:
            if old_task is not None:
                await asyncio.wait({old_task})
            await self._lock(rec)
            rec.phase = "evaluating"
            try:
                outcome, reason = await self._pipeline(rec)
                if outcome:
                    self._finish(rec, outcome, reason)
            except asyncio.CancelledError:
                await self._cleanup_superseded(rec)
                self._finish(rec, rec.cancel_outcome, self._cancel_reason(rec))
                raise
            except Exception:  # noqa: BLE001
                _LOGGER.exception("MusicFollowing: transfer raised")
                await self._restore_saved(rec)
                self._finish(rec, "exception")
        except asyncio.CancelledError:
            self._finish(rec, rec.cancel_outcome, self._cancel_reason(rec))
            raise
        finally:
            self._unlock(rec)
            rec.phase = "done"
            if self._state not in ("following", "idle"):
                self._state = "idle"
            if self._inflight.get(rec.person_key) is rec:
                self._inflight.pop(rec.person_key, None)
            if rec.decided is not None:
                rec.decided.set()

    # ==================================================================
    # The pipeline (gate order is fixed and documented)
    # ==================================================================

    async def _pipeline(self, rec: _Transfer) -> tuple[str, str]:
        """Gates, source, path, verify, release. Returns (outcome, reason).

        Returns ``("", "")`` when the outcome was already booked (success
        books before the release step runs).
        """
        d = rec.decision
        # BLE certainty (live inputs; fails open).
        ble = self._ble_gate(rec)
        if ble is not None:
            return ble
        # Stale (age measured at lock acquire).
        age = self._transition_age(rec.transition_ts)
        if age > self._stale_transition_seconds:
            d["knob"] = f"stale={self._stale_transition_seconds:g} age={age:.1f}"
            return "stale_transition", ""
        gate = self._check_house_state_gate(rec.person_id, rec.from_room, rec.to_room)
        if gate:
            d["knob"] = f"house_state={self._current_house_state}"
            return gate, ""
        # Cooldown.
        now = dt_util.now()
        last_time = self._last_transfer_time.get(rec.person_key)
        last_target = self._last_transfer_target.get(rec.person_key)
        if (self._cooldown_s > 0 and last_time and last_target == rec.to_room):
            try:
                since = (now - last_time).total_seconds()
            except Exception:  # noqa: BLE001
                since = self._cooldown_s
            if since < self._cooldown_s:
                d["knob"] = f"cooldown={self._cooldown_s:g} left={self._cooldown_s - since:.0f}"
                return "cooldown_blocked", ""
        # Bounce back into the room a superseded move came from (INV-MF-5):
        # its cleanup already left the music there at its own volume.
        sup = self._last_superseded.get(rec.person_key)
        if sup and sup.get("source_room") == rec.to_room:
            fresh = self._monotonic() - sup.get("ts", 0) <= _c.MF_RETURN_MATCH_WINDOW_S
            back = await self._get_room_player(rec.to_room)
            bst = self.hass.states.get(back) if back else None
            self._last_superseded.pop(rec.person_key, None)
            if fresh and bst is not None and bst.state == STATE_PLAYING:
                rec.target_player = back
                return "returned_in_flight", f"superseded_target={sup.get('target_room')}"
        # Source.
        outcome = await self._resolve_source(rec)
        if outcome:
            return outcome
        # Per-room opt-out covers BOTH sides (review A-L2): music is never
        # moved into, nor out of, a room whose Music Following is off.
        src_cfg = self._room_cfg(rec.source_room) if rec.source_room else None
        if src_cfg is not None and src_cfg.get(_c.CONF_MUSIC_FOLLOWING_ENABLED, True) is False:
            return "no_source_player", "source_room_opted_out"
        # Target player (the room's primary).
        to_cfg = self._room_cfg(rec.to_room)
        if to_cfg is not None and to_cfg.get(_c.CONF_MUSIC_FOLLOWING_ENABLED, True) is False:
            return "no_target_player", "room_opted_out"
        to_player = await self._get_room_player(rec.to_room)
        if not to_player:
            return "no_target_player", ""
        rec.target_player = to_player
        to_state = self.hass.states.get(to_player)
        if to_state is None or to_state.state in _UNAVAILABLE_STATES:
            d["target_state"] = to_state.state if to_state else "missing"
            return "target_unavailable", ""
        # Others still in the source room.
        if rec.source_room and self._source_has_other_occupants(rec.person_id, rec.source_room):
            return "source_has_others", ""
        from_state = self.hass.states.get(rec.source_player)
        if from_state is None or from_state.state != STATE_PLAYING:
            return "source_not_playing", ""
        d["source_playing"] = True
        if to_player == rec.source_player:
            return "active_playback_blocked", "same_speaker"
        if to_state.state == STATE_PLAYING:
            return "active_playback_blocked", ""

        # The move.
        self._cancel_reversal_watch(rec.person_key)
        prefs = self._preferences_for(rec)
        if prefs.get("follow_mode") in _c.MF_FOLLOW_MODES:
            rec.follow_mode = prefs["follow_mode"]
            d["follow_mode_source"] = "preference"
        return await self._transfer_then_release(rec, from_state, to_state, prefs)

    def _transition_age(self, ts: Optional[datetime]) -> float:
        if ts is None:
            return 0.0
        try:
            now = dt_util.now()
            if now.tzinfo is None and ts.tzinfo is not None:
                from datetime import timezone as _tz  # noqa: PLC0415
                now = now.replace(tzinfo=_tz.utc)
            elif now.tzinfo is not None and ts.tzinfo is None:
                ts = ts.replace(tzinfo=now.tzinfo)
            return float((now - ts).total_seconds())
        except Exception:  # noqa: BLE001
            return 0.0

    # ------------------------------------------------------------------
    # BLE certainty through the person-awareness layer (D1; review A-H1)
    # ------------------------------------------------------------------

    def _person_layer(self):
        """The F4-BLE owner (PersonTrackingCoordinator), or None.

        Music following (class comfort) reads only its public §4.1 methods
        (``get_person_location``, ``tracked_persons``); never its ``data``
        store or a Bermuda / person entity (INV-LAYER-READ).
        """
        try:
            return self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        except Exception:  # noqa: BLE001
            return None

    def _layer_location(self, person_id: str) -> Optional[str]:
        pc = self._person_layer()
        getter = getattr(pc, "get_person_location", None) if pc is not None else None
        if not callable(getter):
            return None
        try:
            loc = getter(person_id)
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(loc, str) or not loc or loc in ("unknown", "unavailable"):
            return None
        return loc

    def _ble_gate(self, rec: _Transfer) -> Optional[tuple[str, str]]:
        """Is the person still where the change said, per the layer?

        "normal": the layer's resolved room for the person is still
        ``to_room``. (The "strict" distance gate was dropped 2026-11-14.)
        A missing input fails open and is counted ONCE per room change
        (``ble_input_missing``, review A-L1).
        """
        d = rec.decision
        t = rec.transition
        mode = self._ble_certainty
        d["ble_confidence"] = mode
        if mode == _c.MF_BLE_CERTAINTY_ANY:
            return None
        missing: list[str] = []
        if t is None or getattr(t, "ble_method", None) is None:
            missing.append("no_event_ble")
        loc = self._layer_location(rec.person_id)
        d["ble_location"] = loc or ""
        try:
            if loc is None:
                missing.append("no_location")
            elif _slug(loc) != _slug(rec.to_room):
                d["knob"] = f"certainty={mode}"
                return "ble_low_confidence", f"location_moved to={rec.to_room} now={loc}"
            return None
        finally:
            if missing:
                d["ble_input"] = ",".join(missing)
                self._count("ble_input_missing")

    # ------------------------------------------------------------------
    # Source (D2)
    # ------------------------------------------------------------------

    async def _stamp_recent_source(self, rec: _Transfer) -> None:
        try:
            player = await self._get_room_player(rec.from_room)
        except Exception:  # noqa: BLE001
            player = None
        if not player:
            return
        st = self.hass.states.get(player)
        if st is not None and st.state == STATE_PLAYING:
            self._recent_source[rec.person_key] = (rec.from_room, player, self._monotonic())

    async def _resolve_source(self, rec: _Transfer) -> Optional[tuple[str, str]]:
        d = rec.decision
        from_player = await self._get_room_player(rec.from_room)
        if from_player:
            st = self.hass.states.get(from_player)
            if st is not None and st.state == STATE_PLAYING:
                rec.source_room, rec.source_player = rec.from_room, from_player
                d["source_how"] = "direct"
                return None
        stamp = self._recent_source.get(rec.person_key)
        if stamp and self._lookback_s > 0:
            room, player, ts = stamp
            age = self._monotonic() - ts
            if room != rec.to_room and age <= self._lookback_s:
                st = self.hass.states.get(player)
                if st is not None and st.state == STATE_PLAYING:
                    rec.source_room, rec.source_player = room, player
                    d["source_how"] = f"lookback age={age:.0f}"
                    return None
            elif room != rec.to_room:
                d["knob"] = f"lookback={self._lookback_s:g} age={age:.0f}"
        if from_player:
            rec.source_room, rec.source_player = rec.from_room, from_player
            return "source_not_playing", ""
        return "no_source_player", ""

    # ------------------------------------------------------------------
    # Path resolution (D3)
    # ------------------------------------------------------------------

    def _features(self, entity_id: str) -> int:
        st = self.hass.states.get(entity_id) if entity_id else None
        try:
            return int((st.attributes or {}).get("supported_features") or 0) if st else 0
        except (TypeError, ValueError):
            return 0

    def _ma_candidates(self, entity_id: str) -> list[tuple[str, str]]:
        """Music Assistant media_players for the same physical speaker.

        Matches (D0, live registry 2026-11-14): the entity itself is MA
        (``is_ma``); an MA entity on the same device (``same_device``); an
        MA device whose ``music_assistant`` identifier names an HA entity on
        this device (``ha_provider_wrap``); an MA device whose identifier
        carries this device's MAC (``mac_in_ma_id``, e.g. ``upc0f5352fc122``).
        """
        try:
            from homeassistant.helpers import device_registry as dr  # noqa: PLC0415
            from homeassistant.helpers import entity_registry as er  # noqa: PLC0415
            ent_reg = er.async_get(self.hass)
            e = ent_reg.async_get(entity_id)
            if e is None:
                return []
            if e.platform == PLATFORM_MASS:
                return [(entity_id, "is_ma")]
            dev_reg = dr.async_get(self.hass)
            dev = dev_reg.async_get(e.device_id) if e.device_id else None
            macs = set()
            if dev is not None:
                for kind, val in dev.connections or ():
                    if kind == "mac":
                        macs.add("".join(ch for ch in str(val).lower() if ch in "0123456789abcdef"))
            out: list[tuple[str, str]] = []
            for x in list(ent_reg.entities.values()):
                if x.platform != PLATFORM_MASS or x.domain != "media_player" or x.disabled_by:
                    continue
                if e.device_id and x.device_id == e.device_id:
                    out.append((x.entity_id, "same_device"))
                    continue
                mdev = dev_reg.async_get(x.device_id) if x.device_id else None
                if mdev is None:
                    continue
                for kind, val in mdev.identifiers or ():
                    if kind != PLATFORM_MASS:
                        continue
                    sval = str(val)
                    wrapped = ent_reg.async_get(sval) if sval.startswith("media_player.") else None
                    if wrapped is not None and e.device_id and wrapped.device_id == e.device_id:
                        out.append((x.entity_id, "ha_provider_wrap"))
                        break
                    hexval = "".join(ch for ch in sval.lower() if ch in "0123456789abcdef")
                    if macs and any(m and m in hexval for m in macs):
                        out.append((x.entity_id, "mac_in_ma_id"))
                        break
            seen: set[str] = set()
            uniq = []
            for eid, kind in out:
                if eid not in seen:
                    seen.add(eid)
                    uniq.append((eid, kind))
            return uniq
        except Exception:  # noqa: BLE001
            return []

    def _resolve_path(self, rec: _Transfer) -> tuple[str, str]:
        """Pick MA, then native join, then generic. Returns (path, reason)."""
        src, dst = rec.source_player, rec.target_player
        reasons = []
        if _c.MF_MA_FIRST_ENABLED:
            s_cands = self._ma_candidates(src)
            t_cands = self._ma_candidates(dst)
            playing = [c for c in s_cands
                       if (self.hass.states.get(c[0]) is not None
                           and self.hass.states.get(c[0]).state == STATE_PLAYING)]
            if s_cands and t_cands and playing:
                s_eid, s_kind = playing[0]
                same_kind = [c for c in t_cands if c[1] == s_kind]
                t_eid, t_kind = (same_kind or t_cands)[0]
                rec.source_eff, rec.target_eff = s_eid, t_eid
                if rec.follow_mode == _c.MF_FOLLOW_MODE_EXTEND:
                    # Review A-H2: transfer_queue MOVES the queue and stops
                    # the source. "Play in both rooms" joins the MA target to
                    # the playing MA source (leader) instead; the source
                    # keeps playing.
                    rec.leader = s_eid
                    rec.via_ma = True
                    return PATH_JOIN, (f"ma_join leader={s_eid}({s_kind}) "
                                       f"dst={t_eid}({t_kind}) extend")
                return PATH_MA, f"ma src={s_eid}({s_kind}) dst={t_eid}({t_kind})"
            if not s_cands or not t_cands:
                reasons.append("ma_not_covered")
            else:
                reasons.append("ma_source_not_playing")
        else:
            reasons.append("ma_disabled")
        src_pf = self._get_player_platform(src)
        dst_pf = self._get_player_platform(dst)
        if (src_pf == dst_pf and src_pf != PLATFORM_GENERIC
                and self._features(src) & _FEATURE_GROUPING
                and self._features(dst) & _FEATURE_GROUPING):
            leader, how = self._group_leader(src)
            safe = (rec.follow_mode == _c.MF_FOLLOW_MODE_EXTEND
                    or leader != src
                    or src_pf in _c.MF_JOIN_LEADER_RELEASE_SAFE_PLATFORMS)
            if safe:
                rec.leader = leader
                rec.source_eff, rec.target_eff = leader, dst
                return PATH_JOIN, f"join leader={leader}({how}) platform={src_pf}"
            reasons.append(f"join_leader_release_unsafe:{src_pf}")
        else:
            reasons.append("no_common_grouping")
        rec.source_eff, rec.target_eff = src, dst
        return PATH_GENERIC, "generic " + ",".join(reasons)

    def _group_leader(self, player: str) -> tuple[str, str]:
        for leader, members in self._active_groups.items():
            if player in members:
                return leader, "mf_group"
        st = self.hass.states.get(player)
        gm = list((st.attributes or {}).get("group_members") or []) if st else []
        if gm and player in gm and gm[0] != player:
            return gm[0], "leader_from_attr"
        return player, "source"

    # ------------------------------------------------------------------
    # Service calls (all MF calls carry the URA write context)
    # ------------------------------------------------------------------

    async def _call(self, domain: str, service: str, data: Optional[dict] = None, *,
                    target: Optional[dict] = None, blocking: bool = True) -> float:
        from .ura_context import ura_write_context  # noqa: PLC0415
        kwargs: dict = {"blocking": blocking, "context": ura_write_context()}
        if target is not None:
            kwargs["target"] = target
        t0 = self._monotonic()
        await self.hass.services.async_call(domain, service, dict(data or {}), **kwargs)
        return (self._monotonic() - t0) * 1000.0

    async def _set_volume(self, entity_id: str, volume: float) -> None:
        await self._call(MEDIA_PLAYER_DOMAIN, SERVICE_VOLUME_SET,
                         {"entity_id": entity_id, "volume_level": round(float(volume), 4)},
                         blocking=False)

    async def _restore_volume(self, entity_id: str) -> None:
        volume = self._saved_volumes.pop(entity_id, None)
        if volume is None:
            return
        self._persist_volumes()
        try:
            await self._set_volume(entity_id, volume)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("MusicFollowing: restore volume failed for %s: %s", entity_id, err)

    async def _restore_saved(self, rec: _Transfer) -> None:
        for player in list(rec.saved):
            rec.saved.pop(player, None)
            await self._restore_volume(player)

    # ------------------------------------------------------------------
    # Transfer, verify, release
    # ------------------------------------------------------------------

    async def _transfer_then_release(self, rec: _Transfer, from_state, to_state,
                                     prefs: Optional[dict] = None) -> tuple[str, str]:
        """Shared by automatic and manual moves."""
        prefs = prefs or {}
        d = rec.decision
        path, why = self._resolve_path(rec)
        rec.path = path
        d["path_reason"] = why
        attrs = from_state.attributes or {}
        try:
            src_volume = float(attrs.get(ATTR_MEDIA_VOLUME_LEVEL, 0.5))
        except (TypeError, ValueError):
            src_volume = 0.5
        if isinstance(prefs.get("target_volume"), (int, float)):
            tgt_volume = max(0.0, min(1.0, float(prefs["target_volume"])))
        elif path == PATH_JOIN:
            tgt_volume = src_volume
        else:
            tgt_volume = self._scaled_target_volume(rec.to_room, src_volume)
        self._state = "transferring"
        rec.phase = "calling"
        try:
            call_ms = await self._start_target(rec, attrs, tgt_volume)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("MusicFollowing: %s path failed: %s", path, err)
            self._state = "idle"
            return "failed", f"{path}:{type(err).__name__}"
        if call_ms is None:
            self._state = "idle"
            return "failed", f"{path}:no_content"
        d["call_ms"] = round(call_ms)
        # Move mode: fade the old room only after MF's call went through.
        if rec.follow_mode == _c.MF_FOLLOW_MODE_MOVE and path != PATH_MA:
            fade_eff = rec.source_player
            self._remember_volume(rec, fade_eff, src_volume)
            await self._set_volume(fade_eff, _c.MF_FADE_TARGET_VOLUME)
        elif rec.follow_mode == _c.MF_FOLLOW_MODE_MOVE and path == PATH_MA:
            # MA stops the source queue itself; keep its volume to put back.
            self._remember_volume(rec, rec.source_player, src_volume)
        # Review B1: the start call is issued and booked against the target;
        # drop the house-wide lock before the verify / release waits so a
        # second person's move is not aged into stale_transition behind it.
        self._unlock(rec)
        # Verify on ground truth: the primary only (INV-MF-6).
        rec.phase = "verifying"
        t0 = self._monotonic()
        if self._verify_delay_s > 0:
            await self._sleep(self._verify_delay_s)
        tstate = self.hass.states.get(rec.target_player)
        outcome = ""
        if tstate is not None and tstate.state == STATE_PLAYING:
            outcome = "success"
        elif (path == PATH_GENERIC and tstate is not None and rec.sent_content_id
              and (tstate.attributes or {}).get("media_content_id") == rec.sent_content_id):
            await self._call(MEDIA_PLAYER_DOMAIN, SERVICE_MEDIA_PLAY,
                             {"entity_id": rec.target_player})
            await self._sleep(_c.MF_NUDGE_SETTLE_S)
            tstate = self.hass.states.get(rec.target_player)
            if tstate is not None and tstate.state == STATE_PLAYING:
                outcome = "success_nudged"
        d["verify_ms"] = round((self._monotonic() - t0) * 1000.0)
        d["target_state"] = tstate.state if tstate is not None else "missing"
        if not outcome:
            # INV-MF-1: the source is never quieted when the target does not
            # play; undo the fade at once.
            await self._restore_saved(rec)
            self._state = "idle"
            return "verify_failed", ""

        # Success: book it now, then the background-safe extras.
        self._state = "following"
        self._last_transfer_time[rec.person_key] = dt_util.now()
        self._last_transfer_target[rec.person_key] = rec.to_room
        if path == PATH_JOIN:
            self._active_groups.setdefault(rec.leader or rec.source_player, set()).add(rec.target_player)
        self._finish(rec, outcome, why)
        await self._bonus_joins_after_success(rec)
        self._start_reversal_watch(rec)
        if rec.follow_mode == _c.MF_FOLLOW_MODE_MOVE:
            rec.phase = "releasing"
            if self._release_delay_s > 0:
                await self._sleep(self._release_delay_s)
            await self._release_source(rec)
        rec.phase = "done"
        return "", ""

    async def _start_target(self, rec: _Transfer, attrs: dict, volume: float) -> Optional[float]:
        """Issue the path's call; returns call ms, or None (no content).

        ``target_started`` is set BEFORE the awaited call (review B6): a
        cancel delivered while the call is in flight may still see it take
        effect, so cleanup must assume it did. The started players are
        recorded for the hazard stop (review A-M1).
        """
        if rec.path == PATH_MA:
            self._mark_started(rec)
            ms = await self._call(
                "music_assistant", "transfer_queue",
                {"source_player": rec.source_eff, "auto_play": True},
                target={"entity_id": rec.target_eff},
            )
            await self._set_volume(rec.target_eff, volume)
            return ms
        if rec.path == PATH_JOIN:
            self._mark_started(rec)
            ms = await self._call(
                MEDIA_PLAYER_DOMAIN, "join",
                {"entity_id": rec.source_eff, "group_members": [rec.target_eff]},
            )
            await self._set_volume(rec.target_eff, volume)
            return ms
        content_id = attrs.get("media_content_id")
        content_type = attrs.get("media_content_type")
        if not content_id or not content_type:
            return None
        self._mark_started(rec)
        rec.sent_content_id = content_id
        ms = await self._call(
            MEDIA_PLAYER_DOMAIN, "play_media",
            {"entity_id": rec.target_eff, "media_content_id": content_id,
             "media_content_type": content_type},
        )
        await self._set_volume(rec.target_eff, volume)
        position = attrs.get(ATTR_MEDIA_POSITION)
        try:
            position = float(position) if position is not None else 0.0
        except (TypeError, ValueError):
            position = 0.0
        if position > 0:
            try:
                await self._call(
                    MEDIA_PLAYER_DOMAIN, "media_seek",
                    {"entity_id": rec.target_eff,
                     "seek_position": position + self._position_offset_s},
                    blocking=False,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("MusicFollowing: seek failed: %s", err)
        return ms

    def _mark_started(self, rec: _Transfer) -> None:
        rec.target_started = True
        for eid in (rec.target_player, rec.target_eff):
            if eid:
                self._started_players.add(eid)

    async def _release_source(self, rec: _Transfer) -> None:
        """Remove the old room after a confirmed move; put its volume back."""
        # Review B5: from here on the source is (being) stopped; a bounce
        # back to it must not also take the target back.
        rec.source_released = True
        try:
            if rec.path == PATH_JOIN and rec.source_player != rec.target_player:
                await self._call(MEDIA_PLAYER_DOMAIN, "unjoin", {"entity_id": rec.source_player})
                for members in self._active_groups.values():
                    members.discard(rec.source_player)
            elif rec.path == PATH_GENERIC:
                await self._call(MEDIA_PLAYER_DOMAIN, "media_stop", {"entity_id": rec.source_player})
            # PATH_MA: MA already stopped the source queue when it moved it.
            for leader, bonus in self._bonus_joined.pop(_slug(rec.source_room), []):
                try:
                    await self._call(MEDIA_PLAYER_DOMAIN, "unjoin", {"entity_id": bonus})
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("MusicFollowing: bonus unjoin failed for %s", bonus)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("MusicFollowing: release of %s failed: %s", rec.source_player, err)
        finally:
            await self._restore_saved(rec)

    async def _undo_target(self, rec: _Transfer) -> None:
        """Take back MF's start of the target (bounce cleanup)."""
        if not rec.target_started:
            return
        try:
            if rec.path == PATH_JOIN:
                joined = rec.target_eff or rec.target_player
                await self._call(MEDIA_PLAYER_DOMAIN, "unjoin", {"entity_id": joined})
                for members in self._active_groups.values():
                    members.discard(rec.target_player)
            elif rec.path == PATH_GENERIC:
                await self._call(MEDIA_PLAYER_DOMAIN, "media_stop", {"entity_id": rec.target_player})
            # PATH_MA: the queue already moved; the next room change moves it on.
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("MusicFollowing: undo of %s failed: %s", rec.target_player, err)

    async def _cleanup_superseded(self, rec: _Transfer) -> None:
        """A newer room change superseded ``rec`` (INV-MF-5)."""
        new_to = rec.superseded_to
        try:
            if rec.phase == "releasing":
                if new_to == rec.source_room and rec.source_released:
                    # B5: the source stop is already out; taking the target
                    # back too would silence both rooms. Keep the target.
                    await self._restore_saved(rec)
                elif new_to == rec.source_room:
                    await self._undo_target(rec)
                    await self._restore_saved(rec)
                else:
                    await self._release_source(rec)
            else:
                await self._undo_target(rec)
                await self._restore_saved(rec)
        finally:
            if rec.source_room:
                self._last_superseded[rec.person_key] = {
                    "source_room": rec.source_room,
                    "target_room": rec.to_room,
                    "phase": rec.phase,
                    "ts": self._monotonic(),
                }

    async def _bonus_joins_after_success(self, rec: _Transfer) -> None:
        """Join the target room's other speakers, best effort (INV-MF-6)."""
        if not self._bonus_joins:
            return
        try:
            bonuses = self._bonus_candidates(rec)
        except Exception:  # noqa: BLE001
            bonuses = []
        if not bonuses:
            return
        leader = rec.target_eff if rec.path == PATH_MA else (rec.leader or rec.target_player)
        if rec.path == PATH_GENERIC:
            leader = rec.target_player
        joined = []
        for bonus in bonuses:
            self._started_players.add(bonus)
            try:
                await self._call(MEDIA_PLAYER_DOMAIN, "join",
                                 {"entity_id": leader, "group_members": [bonus]})
                joined.append((leader, bonus))
            except Exception as err:  # noqa: BLE001
                self._count("bonus_join_failed")
                _LOGGER.info("MusicFollowing: bonus join %s failed (%s); move unaffected", bonus, err)
        if joined:
            self._bonus_joined.setdefault(_slug(rec.to_room), []).extend(joined)
            rec.decision["bonus"] = ",".join(b for _, b in joined)

    def _bonus_candidates(self, rec: _Transfer) -> list[str]:
        """Other grouping speakers in the target room's HA area."""
        cfg = self._room_cfg(rec.to_room) or {}
        area_id = cfg.get(_c.CONF_AREA_ID)
        if not area_id:
            return []
        from homeassistant.helpers import device_registry as dr  # noqa: PLC0415
        from homeassistant.helpers import entity_registry as er  # noqa: PLC0415
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        prim = ent_reg.async_get(rec.target_player)
        prim_dev = prim.device_id if prim is not None else None
        exclude = {rec.target_player, rec.target_eff, rec.source_player}
        exclude |= {c for c, _ in self._ma_candidates(rec.target_player)}
        if rec.path == PATH_MA or rec.via_ma:
            want_pf = PLATFORM_MASS
        else:
            want_pf = self._get_player_platform(rec.target_player)
        out = []
        for e in list(ent_reg.entities.values()):
            if e.domain != "media_player" or e.disabled_by or e.entity_id in exclude:
                continue
            if prim_dev and e.device_id == prim_dev:
                continue
            e_area = e.area_id
            if not e_area and e.device_id:
                dev = dev_reg.async_get(e.device_id)
                e_area = dev.area_id if dev is not None else None
            if e_area != area_id:
                continue
            cand = e.entity_id
            if want_pf == PLATFORM_MASS and e.platform != PLATFORM_MASS:
                mas = self._ma_candidates(cand)
                if not mas:
                    continue
                cand = mas[0][0]
            elif want_pf != PLATFORM_MASS and self._get_player_platform(cand) != want_pf:
                continue
            st = self.hass.states.get(cand)
            if st is None or st.state in _UNAVAILABLE_STATES:
                continue
            if not self._features(cand) & _FEATURE_GROUPING:
                continue
            if cand not in exclude and cand not in out:
                out.append(cand)
        return out

    # ------------------------------------------------------------------
    # Reversal (D5.3)
    # ------------------------------------------------------------------

    def _cancel_reversal_watch(self, person_key: str) -> None:
        unsub = self._reversal_watch.pop(person_key, None)
        if unsub is not None:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass

    def _start_reversal_watch(self, rec: _Transfer) -> None:
        if _c.MF_REVERSAL_WINDOW_S <= 0:
            return
        self._cancel_reversal_watch(rec.person_key)
        try:
            from homeassistant.core import callback  # noqa: PLC0415
            from homeassistant.helpers.event import (  # noqa: PLC0415
                async_call_later,
                async_track_state_change_event,
            )
            from .ura_context import is_ura_context  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            return
        target, source = rec.target_player, rec.source_player
        started = self._monotonic()
        unsubs: list = []

        def _stop() -> None:
            for u in unsubs:
                try:
                    u()
                except Exception:  # noqa: BLE001
                    pass
            unsubs.clear()
            if self._reversal_watch.get(rec.person_key) is _stop:
                self._reversal_watch.pop(rec.person_key, None)

        @callback
        def _on_change(event) -> None:
            data = getattr(event, "data", {}) or {}
            ent = data.get("entity_id")
            old, new = data.get("old_state"), data.get("new_state")
            if old is None or new is None or old.state == new.state:
                return
            if is_ura_context(getattr(new, "context", None)):
                return
            kind = None
            if ent == target and old.state == STATE_PLAYING and new.state in _STOPPED_STATES:
                kind = "target_stopped_by_hand"
            elif ent == source and old.state != STATE_PLAYING and new.state == STATE_PLAYING:
                kind = "source_resumed_by_hand"
            if kind is None:
                return
            _stop()
            self._record_reversal(rec, kind, self._monotonic() - started)

        @callback
        def _expire(_now) -> None:
            _stop()

        try:
            unsubs.append(async_track_state_change_event(self.hass, [target, source], _on_change))
            unsubs.append(async_call_later(self.hass, _c.MF_REVERSAL_WINDOW_S, _expire))
        except Exception:  # noqa: BLE001
            _stop()
            return
        self._reversal_watch[rec.person_key] = _stop

    def _record_reversal(self, rec: _Transfer, kind: str, seconds_after: float) -> None:
        acc = self._accuracy_live
        acc["reversals"] += 1
        acc["by_kind"][kind] = acc["by_kind"].get(kind, 0) + 1
        pair = f"{rec.source_room}->{rec.to_room}"
        acc["by_pair"][pair] = acc["by_pair"].get(pair, 0) + 1
        _LOGGER.info("MF reversal person=%s pair=%s kind=%s seconds_after=%.0f",
                     rec.person_id, pair, kind, seconds_after)
        self._write_episode(
            _c.MF_REVERSAL_EPISODE_TYPE, f"room:{_slug(rec.to_room)}",
            {"person_key": rec.person_key, "kind": kind,
             "seconds_after": round(seconds_after, 1),
             "decision_ref": rec.decision.get("source_ref", ""),
             "source_room": rec.source_room, "to_room": rec.to_room},
            source_ref=f"mfrev:{rec.person_key}:{rec.decision.get('ts', '')}",
        )
        self._notify_listeners()

    # ------------------------------------------------------------------
    # Room memory (D6)
    # ------------------------------------------------------------------

    def _write_decision_episode(self, rec: _Transfer) -> None:
        d = rec.decision
        ref = f"mf:{rec.person_key}:{d.get('ts', '')}"
        d["source_ref"] = ref
        attrs = {k: d.get(k, "") for k in MF_DECISION_FIELDS}
        attrs["source_playing"] = bool(d.get("source_playing"))
        attrs["path_reason"] = d.get("path_reason", "")
        self._write_episode(_c.MF_DECISION_EPISODE_TYPE,
                            f"room:{_slug(rec.to_room)}", attrs, source_ref=ref)

    def _write_episode(self, episode_type: str, node: str, attrs: dict, *, source_ref: str) -> None:
        if not _c.MF_EPISODE_LOG_PERSIST:
            return
        database = self.hass.data.get(DOMAIN, {}).get("database") if isinstance(
            getattr(self.hass, "data", None), dict) else None
        if database is None or not hasattr(database, "log_memory_episode"):
            return

        async def _write() -> None:
            try:
                await database.log_memory_episode(
                    node_id=node, episode_type=episode_type, attrs=attrs,
                    source_ref=source_ref, window_dedup=False, dedup_source_ref=True,
                )
            except Exception:  # noqa: BLE001 - observational only
                _LOGGER.debug("MusicFollowing: memory row failed", exc_info=True)

        try:
            task = self.hass.async_create_task(_write(), name="ura_mf_episode")
        except Exception:  # noqa: BLE001
            return
        if isinstance(task, asyncio.Future):
            self._episode_tasks.add(task)
            task.add_done_callback(self._episode_tasks.discard)

    # ------------------------------------------------------------------
    # Nightly (D5.3 accuracy roll-up + D5.5 zero-fire trip-wire)
    # ------------------------------------------------------------------

    async def async_nightly_health_check(self, database: Any = None) -> dict:
        """Trailing-24 h trip-wire + 7-day accuracy roll-up. Never raises."""
        result: dict = {"fired": False}
        try:
            window = await self._tripwire_window(database)
            result["window_source"] = window[0]
            window = window[1]
            candidates = sum(1 for r in window if r[2])
            successes = sum(1 for r in window if r[1] in MF_SUCCESS_OUTCOMES)
            result.update({"candidates": candidates, "successes": successes})
            floor = _c.MF_ZERO_TRANSFER_MIN_CANDIDATES
            if floor > 0 and candidates >= floor and successes == 0:
                skips: dict[str, int] = {}
                for r in window:
                    if r[1] in MF_SKIP_OUTCOMES:
                        skips[r[1]] = skips.get(r[1], 0) + 1
                top = sorted(skips.items(), key=lambda kv: -kv[1])[:3]
                from .domain_coordinators._stuck_signal_nm import fire_stuck_signal  # noqa: PLC0415
                result["fired"] = await fire_stuck_signal(
                    self.hass, "music_follow_silent", ("house",),
                    diagnosis=(
                        f"Music following made no successful move in 24 h although "
                        f"{candidates} room changes had music playing and a speaker "
                        f"ahead. Top skips: "
                        + (", ".join(f"{k} ({v})" for k, v in top) or "none")
                    ),
                    remedy="Read the 'MF decision' log lines and sensor.ura_music_following_health.",
                    severity="HIGH",
                )
            if database is not None and hasattr(database, "read_memory_episodes_by_type"):
                since = (dt_util.utcnow() - timedelta(days=7)).isoformat()
                rows = await database.read_memory_episodes_by_type(
                    _c.MF_DECISION_EPISODE_TYPE, since)
                revs = await database.read_memory_episodes_by_type(
                    _c.MF_REVERSAL_EPISODE_TYPE, since)
                succ = sum(1 for r in rows
                           if (r.get("attrs") or {}).get("outcome") in MF_SUCCESS_OUTCOMES)
                by_kind: dict[str, int] = {}
                for r in revs:
                    k = (r.get("attrs") or {}).get("kind", "?")
                    by_kind[k] = by_kind.get(k, 0) + 1
                self._accuracy_7d = {"successes": succ, "reversals": len(revs),
                                     "by_kind": by_kind,
                                     "computed_at": dt_util.now().isoformat()}
                result["accuracy_7d"] = dict(self._accuracy_7d)
                self._notify_listeners()
        except Exception:  # noqa: BLE001
            _LOGGER.warning("MusicFollowing nightly health check failed", exc_info=True)
        return result

    async def _tripwire_window(self, database: Any) -> tuple[str, list]:
        """The last MF_TRIPWIRE_WINDOW_S of decisions as (ts, outcome, candidate).

        Review B7: from the persisted decision rows when the database can be
        read (a restart inside the window no longer under-counts); the
        in-memory list only when it cannot. Decision rows are written for
        candidates only (both players resolved), so every row is one. The DAO
        returns [] on a read error, so when memory holds MORE candidates
        than the rows (a failing writer), memory is used.
        """
        cutoff = self._monotonic() - _c.MF_TRIPWIRE_WINDOW_S
        mem = [r for r in self._recent_decisions if r[0] >= cutoff]
        if database is not None and hasattr(database, "read_memory_episodes_by_type"):
            try:
                since = (dt_util.utcnow()
                         - timedelta(seconds=_c.MF_TRIPWIRE_WINDOW_S)).isoformat()
                rows = await database.read_memory_episodes_by_type(
                    _c.MF_DECISION_EPISODE_TYPE, since)
                out = []
                for r in rows or []:
                    a = r.get("attrs") or {}
                    out.append((0.0, str(a.get("outcome", "")), bool(a.get("source_playing"))))
                if sum(1 for r in out if r[2]) >= sum(1 for r in mem if r[2]):
                    return "db", out
            except Exception:  # noqa: BLE001 - fall back to memory
                _LOGGER.debug("MusicFollowing: trip-wire DB read failed", exc_info=True)
        return "memory", mem

    def digest_section(self) -> str:
        """One digest line for the last 24 h; empty with no candidates."""
        cutoff = self._monotonic() - _c.MF_TRIPWIRE_WINDOW_S
        window = [r for r in self._recent_decisions if r[0] >= cutoff]
        cand = [r for r in window if r[2]]
        if not cand:
            return ""
        played = sum(1 for r in window if r[1] in MF_SUCCESS_OUTCOMES)
        failed = sum(1 for r in window if r[1] in ("verify_failed", "failed", "exception"))
        moves = played + failed
        skips: dict[str, int] = {}
        for r in window:
            if r[1] in MF_SKIP_OUTCOMES and r[1] not in ("verify_failed", "failed", "exception"):
                skips[r[1]] = skips.get(r[1], 0) + 1
        rev = int(self._accuracy_live.get("reversals") or 0)
        parts = [f"Music following, last 24 h: {moves} moves, {played} played"]
        if failed:
            parts.append(f"{failed} failed")
        if rev:
            parts.append(f"{rev} moved back by hand (since start)")
        line = ", ".join(parts) + "."
        if skips:
            k, v = max(skips.items(), key=lambda kv: kv[1])
            line += f" Most common skip: {k} ({v})."
        return line

    # ==================================================================
    # Gates kept from v5.10.0
    # ==================================================================

    def _source_has_other_occupants(self, person_id: str, from_room: str) -> bool:
        """True iff the source room still has someone besides ``person_id``.

        PRIMARY: another tracked person's resolved room is that room, read
        through the layer's public F4-BLE read (``tracked_persons`` +
        ``get_person_location``, contract §4.1), never ``data`` (review
        A-H1 / INV-LAYER-READ). G6 ``persons_in_room`` replaces this loop
        when it ships (PERSON-AWARENESS-READ-API-1 ship 3).
        SECONDARY: the substrate's ``occupancy`` kind is active there (motion
        excluded: it decays after the leaver walks out). Fail-open.
        """
        me = _person_key(person_id)
        try:
            pc = self._person_layer()
            for other_id in list(getattr(pc, "tracked_persons", None) or []):
                if other_id == person_id or _person_key(other_id) == me:
                    continue
                loc = self._layer_location(other_id)
                if loc and _slug(loc) == _slug(from_room):
                    return True
        except Exception:  # noqa: BLE001
            pass
        try:
            substrate = self.hass.data.get(DOMAIN, {}).get("occupancy_substrate")
            if substrate is None:
                return False
            try:
                return bool(substrate.is_kind_active(from_room, "occupancy"))
            except Exception:  # noqa: BLE001
                return False
        except Exception:  # noqa: BLE001
            return False

    def _dwell_room_for_person(self, person_id: str) -> Optional[str]:
        """The person's bedroom, from the preference provider (D7.5).

        Review A-H1: this used to read ``person_coordinator.data[p]
        ["dwell_room" / "bedroom"]``, keys the producer never writes (so it
        always returned None and ``dwell_only`` behaved as ``block_all``).
        A bedroom is a profile fact (PERSON-PROFILE-PREFERENCES-1), so it
        comes from the provider's ``bedroom`` key; no provider = None, the
        same live behaviour as before.
        """
        provider = self._preference_provider
        if provider is None:
            return None
        try:
            prefs = provider(_person_key(person_id), {"purpose": "bedroom"})
        except Exception:  # noqa: BLE001
            return None
        dwell = prefs.get("bedroom") if isinstance(prefs, dict) else None
        return dwell if isinstance(dwell, str) and dwell else None

    def _check_house_state_gate(self, person_id: str, from_room: str, to_room: str) -> Optional[str]:
        """SLEEP (with sleep_suppress) blocks; HOME_NIGHT per night mode."""
        state = self._current_house_state
        if not state:
            return None
        if state == "sleep" and self._sleep_suppress:
            return "sleep_suppressed"
        if state == "home_night":
            mode = self._night_suppress_mode
            if mode == "block_all":
                return "night_suppressed"
            if mode == "dwell_only":
                dwell = self._dwell_room_for_person(person_id)
                if dwell is None:
                    if not self._warned_dwell_only_no_surface:
                        _LOGGER.warning(
                            "MusicFollowing: night_suppress_mode='dwell_only' is set, but "
                            "no per-person bedroom mapping exists. Behaving as 'block_all'."
                        )
                        self._warned_dwell_only_no_surface = True
                    return "night_suppressed"
                if _slug(dwell) != _slug(to_room):
                    return "night_suppressed"
        return None

    # ==================================================================
    # Players and rooms
    # ==================================================================

    def _get_player_platform(self, entity_id: str) -> str:
        """Platform of a media player, from the entity registry."""
        try:
            from homeassistant.helpers import entity_registry  # noqa: PLC0415
            ent_reg = entity_registry.async_get(self.hass)
            entry = ent_reg.async_get(entity_id)
            platform = getattr(entry, "platform", None) if entry is not None else None
            if isinstance(platform, str) and platform:
                p = platform.lower()
                return {
                    "sonos": PLATFORM_SONOS, "linkplay": PLATFORM_LINKPLAY,
                    "wiim": PLATFORM_WIIM, "denonavr": PLATFORM_DENON,
                    "heos": PLATFORM_HEOS, "music_assistant": PLATFORM_MASS,
                }.get(p, PLATFORM_GENERIC)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Entity registry lookup failed for %s: %s", entity_id, err)
        return PLATFORM_GENERIC

    def _room_cfg(self, room_name: str) -> Optional[dict]:
        target = _slug(room_name)
        for entry_data in self._get_room_entries().values():
            if _slug(entry_data.get("room_name", "")) == target:
                return entry_data
        return None

    def configured_players(self) -> set[str]:
        """Every configured room and zone player (hazard-stop scope)."""
        out: set[str] = set()
        for cfg in self._get_room_entries().values():
            p = cfg.get("room_media_player")
            if p:
                out.add(p)
            zone = cfg.get("zone")
            if zone:
                zp, _mode = self._get_zone_player_config(zone)
                if zp:
                    out.add(zp)
        return out

    def hazard_stop_scope(self) -> set[str]:
        """Every speaker a hazard stop must reach (review A-M1).

        Configured room / zone players, every speaker music following
        itself started (area-found primaries, MA twins, bonus players),
        MF's native group leaders and members, and the MA twin of each.
        """
        scope = set(self.configured_players()) | set(self._started_players)
        for leader, members in self._active_groups.items():
            scope.add(leader)
            scope |= set(members)
        for joined in self._bonus_joined.values():
            for leader, bonus in joined:
                scope.update((leader, bonus))
        for eid in list(scope):
            scope.update(c for c, _ in self._ma_candidates(eid))
        return {e for e in scope if e}

    def hazard_active(self) -> bool:
        return self._hazard_until > 0 and self._monotonic() < self._hazard_until

    async def async_hazard_stop(self, reason: str = "hazard") -> int:
        """Critical safety / security stop (reviews B2, A-M1).

        Blocks new moves for MF_HAZARD_BLOCK_S, cancels every in-flight move
        (its cleanup takes the target back and restores volumes; booked
        ``hazard_blocked``), then stops every playing speaker in
        ``hazard_stop_scope`` with the URA context, so the reversal watch
        does not count the stop as a person's undo. Returns the number
        stopped. Never raises.
        """
        if _c.MF_HAZARD_BLOCK_S > 0:
            self._hazard_until = self._monotonic() + float(_c.MF_HAZARD_BLOCK_S)
        for person_key in list(self._reversal_watch):
            self._cancel_reversal_watch(person_key)
        tasks = []
        for rec in list(self._inflight.values()):
            if rec.task is not None and not rec.task.done():
                rec.cancel_outcome = "hazard_blocked"
                rec.task.cancel()
                tasks.append(rec.task)
        if tasks:
            try:
                await asyncio.wait(tasks, timeout=5)
            except Exception:  # noqa: BLE001
                pass
        stopped = 0
        for eid in sorted(self.hazard_stop_scope()):
            st = self.hass.states.get(eid)
            if st is None or st.state not in ("playing", "paused"):
                continue
            try:
                await self._call(MEDIA_PLAYER_DOMAIN, "media_stop",
                                 {"entity_id": eid}, blocking=False)
                stopped += 1
            except Exception:  # noqa: BLE001
                _LOGGER.warning("MusicFollowing: hazard stop of %s failed", eid)
        _LOGGER.warning("MusicFollowing: %s stop, %d speaker(s) stopped, moves blocked %ss",
                        reason, stopped, _c.MF_HAZARD_BLOCK_S)
        return stopped

    async def _get_room_player(self, room_name: str) -> Optional[str]:
        """The room's primary speaker: config, zone, then the room's HA area.

        Review A-M2 (Registry, not names): the area is the room entry's
        ``area_id`` (no area-name match), a speaker belongs to it by its
        entity area or else its device area, and there is no
        ``media_player.<room>`` guess.
        """
        room_zone = None
        cfg = self._room_cfg(room_name)
        if cfg is not None:
            media_player = cfg.get("room_media_player")
            if media_player:
                if self.hass.states.get(media_player):
                    return media_player
                _LOGGER.warning("Room '%s': configured room_media_player '%s' not found in HA",
                                room_name, media_player)
            room_zone = cfg.get("zone")
        if room_zone:
            zone_player, _zone_mode = self._get_zone_player_config(room_zone)
            if zone_player and self.hass.states.get(zone_player):
                return zone_player
        area_id = cfg.get(_c.CONF_AREA_ID) if cfg is not None else None
        try:
            from homeassistant.helpers import device_registry, entity_registry  # noqa: PLC0415
            entity_reg = entity_registry.async_get(self.hass)
            dev_reg = device_registry.async_get(self.hass)
            if area_id:
                area_players = []
                for e in entity_reg.entities.values():
                    if e.domain != "media_player" or e.disabled:
                        continue
                    e_area = e.area_id
                    if not e_area and e.device_id:
                        dev = dev_reg.async_get(e.device_id)
                        e_area = dev.area_id if dev is not None else None
                    if e_area == area_id:
                        area_players.append(e.entity_id)
                if area_players:
                    def _rank(eid: str) -> tuple[int, str]:
                        try:
                            pf = self._get_player_platform(eid)
                        except Exception:  # noqa: BLE001
                            pf = PLATFORM_GENERIC
                        return (0 if pf in MULTIROOM_PLATFORMS else 1, eid)

                    area_players.sort(key=_rank)
                    if len(area_players) > 1:
                        _LOGGER.warning(
                            "Room '%s' has %d media players in area; picked '%s'. "
                            "Configure room_media_player for explicit control.",
                            room_name, len(area_players), area_players[0])
                    return area_players[0]
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Room '%s': HA Area lookup failed: %s", room_name, err)
        return None

    def _scaled_target_volume(self, to_room: str, source_volume: float) -> float:
        """Per-room speaker loudness calibration (clamped)."""
        try:
            source_volume = float(source_volume)
        except (TypeError, ValueError):
            source_volume = 0.5
        if not to_room:
            return source_volume
        scale = _c.DEFAULT_ROOM_MEDIA_VOLUME_SCALE
        try:
            cfg = self._room_cfg(to_room)
            if cfg is not None and cfg.get(_c.CONF_ROOM_MEDIA_VOLUME_SCALE) is not None:
                scale = float(cfg.get(_c.CONF_ROOM_MEDIA_VOLUME_SCALE))
        except Exception:  # noqa: BLE001
            return source_volume
        scale = min(max(scale, _c.MIN_ROOM_MEDIA_VOLUME_SCALE), _c.MAX_ROOM_MEDIA_VOLUME_SCALE)
        return max(0.0, min(1.0, source_volume * scale))

    def _get_room_entries(self) -> dict:
        try:
            out = {}
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(_c.CONF_ENTRY_TYPE) == _c.ENTRY_TYPE_ROOM:
                    out[entry.entry_id] = {**entry.data, **entry.options}
            return out
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Failed to get room entries: %s", err)
            return {}

    def _get_zone_player_config(self, zone_name: str) -> tuple[Optional[str], str]:
        try:
            zone_name_lower = zone_name.lower()
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(_c.CONF_ENTRY_TYPE) == _c.ENTRY_TYPE_ZONE_MANAGER:
                    merged = {**entry.data, **entry.options}
                    for zn, zone_config in (merged.get("zones", {}) or {}).items():
                        if zn.lower() == zone_name_lower:
                            return (zone_config.get(_c.CONF_ZONE_PLAYER_ENTITY),
                                    zone_config.get(_c.CONF_ZONE_PLAYER_MODE,
                                                    _c.ZONE_PLAYER_MODE_FALLBACK))
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(_c.CONF_ENTRY_TYPE) == _c.ENTRY_TYPE_ZONE:
                    if entry.data.get(_c.CONF_ZONE_NAME, "").lower() == zone_name_lower:
                        merged = {**entry.data, **entry.options}
                        return (merged.get(_c.CONF_ZONE_PLAYER_ENTITY),
                                merged.get(_c.CONF_ZONE_PLAYER_MODE, _c.ZONE_PLAYER_MODE_FALLBACK))
            return None, "fallback"
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Failed to get zone player config for '%s': %s", zone_name, err)
            return None, "fallback"

    # ==================================================================
    # Manual transfer (same helper as automatic moves)
    # ==================================================================

    async def manual_transfer(self, person_id: str, from_room: str, to_room: str) -> bool:
        """Move music now; True iff the target was verified playing."""
        rec = _Transfer(person_id=person_id, person_key=_person_key(person_id),
                        from_room=from_room, to_room=to_room,
                        follow_mode=self._follow_mode)
        rec.decided = asyncio.Event()
        rec.decision.update({"person": person_id, "from": from_room, "to": to_room,
                             "reason": "manual"})
        from_player = await self._get_room_player(from_room)
        to_player = await self._get_room_player(to_room)
        if not from_player or not to_player:
            return False
        from_state = self.hass.states.get(from_player)
        to_state = self.hass.states.get(to_player)
        if from_state is None or from_state.state != STATE_PLAYING or to_state is None:
            return False
        rec.source_room, rec.source_player, rec.target_player = from_room, from_player, to_player
        rec.decision["source_playing"] = True
        if self.hazard_active():
            self._finish(rec, "hazard_blocked")
            return False
        await self._lock(rec)
        try:
            outcome, reason = await self._transfer_then_release(rec, from_state, to_state)
            if outcome:
                self._finish(rec, outcome, reason)
        finally:
            self._unlock(rec)
        return rec.outcome in MF_SUCCESS_OUTCOMES

    # Back-compat name used by older callers/tests.
    async def _execute_transfer(self, person_id: str, from_room: str, to_room: str, *,
                                transition_ts: Optional[datetime] = None) -> None:
        t = RoomTransition(person_id=person_id, from_room=from_room, to_room=to_room,
                           timestamp=transition_ts or dt_util.now(),
                           duration_seconds=0, path_type="direct", confidence=1.0)
        rec = self._new_record(t)
        rec.transition_ts = transition_ts
        await self._lock(rec)
        try:
            outcome, reason = await self._pipeline(rec)
            if outcome:
                self._finish(rec, outcome, reason)
        finally:
            self._unlock(rec)
