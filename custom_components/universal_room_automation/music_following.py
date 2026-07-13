"""Music following for Universal Room Automation v3.6.27.

Seamlessly transfer music playback when person moves between rooms.

v3.6.20: Music Following Hardening — Sub-Cycle B (Behavior Hardening)
         - Transfer cooldown: 8s per person to same target room
         - Post-transfer verification: check target playing, nudge if needed
         - Music Assistant queue transfer (MASS transfer_queue)
         - Winner rules: block transfer if target already playing
         - Speaker group cleanup: unjoin source after verified transfer
v3.6.19: Sub-Cycle A (Foundation Fixes)
         - asyncio.Lock, volume save/restore, fade gated behind success
v3.3.5.2–v3.3.1: Platform-agnostic transfers, zone config, etc.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.components.media_player import (
    ATTR_MEDIA_POSITION,
    ATTR_MEDIA_VOLUME_LEVEL,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    SERVICE_MEDIA_PAUSE,
    SERVICE_MEDIA_PLAY,
    SERVICE_VOLUME_SET,
)
from homeassistant.const import STATE_PLAYING
from homeassistant.util import dt as dt_util

from .transitions import RoomTransition
from .const import (
    DOMAIN,
    MUSIC_TRANSFER_COOLDOWN_SECONDS,
    TRANSFER_VERIFY_DELAY_SECONDS,
    GROUP_UNJOIN_DELAY_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

# Platform identifiers
PLATFORM_SONOS = "sonos"
PLATFORM_LINKPLAY = "linkplay"  # Linkplay integration entities
PLATFORM_WIIM = "wiim"  # WiiM custom integration entities
PLATFORM_DENON = "denonavr"  # Denon/Marantz AVR integration
PLATFORM_MASS = "music_assistant"  # Music Assistant players
PLATFORM_GENERIC = "generic"

# Platforms that support native multiroom sync via media_player.join
# v3.3.5.2: Added PLATFORM_WIIM - WiiM integration DOES support join
# v3.3.5.2: Added PLATFORM_DENON - HEOS integration supports join for Denon/Marantz
MULTIROOM_PLATFORMS = {PLATFORM_SONOS, PLATFORM_LINKPLAY, PLATFORM_WIIM, PLATFORM_DENON}


class MusicFollowing:
    """Seamless music following between rooms.
    
    Features:
    - Transfer playback on room transition
    - Maintain playback position
    - Preserve volume settings
    - Fade out source room
    - Platform-aware transfer (Sonos, Linkplay, WiiM, Denon, generic)
    - Graceful fallback handling
    - Zone-level media player configuration (v3.3.2)
    
    v3.3.5.2: Updated Platform Transfer Matrix
    
    Same-platform transfers use media_player.join for synchronized multiroom:
    ┌─────────────┬─────────────┬─────────────┬─────────────┬─────────────┐
    │ Source →    │ Sonos       │ Linkplay    │ WiiM        │ HEOS/Denon  │
    │ Target ↓    │             │             │             │             │
    ├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
    │ Sonos       │ join(SYNC)  │ play_media  │ play_media  │ play_media  │
    │ Linkplay    │ play_media  │ join(SYNC)  │ play_media  │ play_media  │
    │ WiiM        │ play_media  │ play_media  │ join(SYNC)  │ play_media  │
    │ HEOS/Denon  │ play_media  │ play_media  │ play_media  │ join(SYNC)  │
    └─────────────┴─────────────┴─────────────┴─────────────┴─────────────┘
    
    Cross-platform transfers use play_media (independent playback) because
    each platform uses incompatible hardware-level multiroom protocols:
    - Sonos: SonosNet / WiFi Direct
    - WiiM/Linkplay: LinkPlay multiroom protocol
    - Denon/Marantz: HEOS protocol
    """
    
    # Configuration
    FADE_OUT_VOLUME = 0.1  # Fade source to 10%
    TRANSFER_DELAY_MS = 500  # Wait before starting target
    MIN_CONFIDENCE = 0.6  # Minimum transition confidence to trigger
    
    def __init__(
        self,
        hass: HomeAssistant,
        config: dict,
        transition_detector
    ) -> None:
        """Initialize music following."""
        self.hass = hass
        self.config = config
        self.transition_detector = transition_detector

        # Track which person we're following music for
        self._enabled_persons: set[str] = set()

        # v3.6.19: Concurrency lock — prevent overlapping transfers
        self._transfer_lock = asyncio.Lock()

        # v3.6.19: Volume save/restore — pre-fade volume per player
        self._saved_volumes: dict[str, float] = {}

        # v3.6.20: Transfer cooldown — per-person last transfer time and target
        self._last_transfer_time: dict[str, datetime] = {}
        self._last_transfer_target: dict[str, str] = {}

        # v3.6.20: Active speaker groups for cleanup
        self._active_groups: dict[str, set[str]] = {}
        # v5.10.0 D6 (addresses C9): standardize on `set` for O(1) discard
        # (matches the coordinator's `_pending_tasks` type).
        self._cleanup_tasks: set[asyncio.Task] = set()

        # v5.10.0 D2: sleep/night gating state. Coordinator pushes the
        # current HouseState value via update_house_state() whenever
        # SIGNAL_HOUSE_STATE_CHANGED fires, plus the current CONF flags.
        # Default: no gate (UNKNOWN → allow) until coordinator boots.
        self._current_house_state: str = ""
        self._sleep_suppress: bool = True
        self._night_suppress_mode: str = "dwell_only"

        # v5.10.0 D6: stale-transition threshold in seconds.
        self._stale_transition_seconds: float = 15.0

        # v5.10.0 fix-up FIX-3 + FIX-5: one-shot flags / prefs.
        self._warned_dwell_only_no_surface: bool = False
        # FIX-5 (B-HIGH-1): per-person follow-preference authority. The
        # MFPersonFollowSwitch writes here on restore + on toggle; sync,
        # reload, and auto-enable-all consult it. False = DND (user has
        # turned this person's music-following OFF).
        self._person_follow_prefs: dict[str, bool] = {}

        # v3.6.21 C1: Transfer tracking for diagnostic sensor
        self._state: str = "idle"  # idle / following / transferring / cooldown / error
        self._transfer_stats: dict[str, int] = {
            "success": 0,
            "failed": 0,
            "unverified": 0,
            "cooldown_blocked": 0,
            "active_playback_blocked": 0,
            "low_confidence": 0,
            "ping_pong_suppressed": 0,
            # v5.10.0 D1/D2/D3/D4/D6: new skip stats
            "target_unavailable": 0,
            "sleep_suppressed": 0,
            "night_suppressed": 0,
            "source_has_others": 0,
            "same_room": 0,
            "stale_transition": 0,
        }
        self._stats_date: str = ""  # YYYY-MM-DD for daily reset
        self._last_transfer_from: str = ""
        self._last_transfer_to: str = ""
        self._last_transfer_person: str = ""
        self._last_transfer_time_iso: str = ""
        self._last_transfer_result: str = ""
        # v5.10.0 D1+D8: skip-reason surface for MusicFollowingLastTransferSensor
        self._last_skip_reason: str = ""
        self._last_skip_from_room: str = ""
        self._last_skip_to_room: str = ""
        self._last_skip_time_iso: str = ""
        # v5.10.0 D1: silent-actuator counter — how many times we no-op'd
        # because the target speaker was offline.
        self._target_unavailable_skips: int = 0
        # v5.10.0 fix-up B-MED-2: initialize the per-transfer join flag
        # so an early read on the first transition doesn't AttributeError.
        # Also reset at the top of _transfer_media (defensive; the flag
        # is authoritative there).
        self._last_transfer_used_join: bool = False
        # Listeners for sensor push updates
        self._diagnostic_listeners: list = []

        _LOGGER.info("MusicFollowing v3.6.21 initialized")
    
    async def async_init(self) -> None:
        """Initialize music following and subscribe to transitions."""
        # Subscribe to transition events
        self.transition_detector.async_add_listener(self._on_person_transition)
        
        _LOGGER.info(
            "MusicFollowing ready: confidence_threshold=%.2f, fade_volume=%.2f",
            self.MIN_CONFIDENCE, self.FADE_OUT_VOLUME
        )
    
    def enable_for_person(self, person_id: str) -> None:
        """Enable music following for specific person."""
        self._enabled_persons.add(person_id)
        _LOGGER.info("Music following enabled for: %s", person_id)
    
    def disable_for_person(self, person_id: str) -> None:
        """Disable music following for specific person."""
        self._enabled_persons.discard(person_id)
        _LOGGER.info("Music following disabled for: %s", person_id)

    def sync_enabled_persons(self, tracked_persons: list[str]) -> None:
        """v5.10.0 D6 (addresses C5) + v5.10.0 fix-up FIX-5 (B-HIGH-1):
        reconcile membership of _enabled_persons against tracked-persons,
        WITHOUT clobbering per-person DND prefs.

        Options-flow reload can add/remove a tracked person. The
        standalone MusicFollowing singleton survives the coordinator
        reload, so _enabled_persons drifts out of sync. Called from the
        coordinator's async_setup (see
        domain_coordinators/music_following.py:async_setup) after the
        singleton is bound.

        Rule: newly-tracked persons default ON UNLESS a stored pref
        already says OFF (the MFPersonFollowSwitch wrote its restore
        pref on async_added_to_hass). Removed persons are dropped.
        Prefs for a person who has just been dropped are pruned too,
        so a later re-add starts fresh.
        """
        wanted = set(tracked_persons or [])
        prefs = self._person_follow_prefs
        target = set()
        for p in wanted:
            if prefs.get(p) is False:
                # Explicit OFF pref — do NOT enable.
                continue
            target.add(p)
        added = target - self._enabled_persons
        removed = self._enabled_persons - wanted  # dropped ONLY if untracked
        self._enabled_persons = (self._enabled_persons - removed) | added
        # Prune prefs for untracked persons.
        for p in list(prefs.keys()):
            if p not in wanted:
                prefs.pop(p, None)
        if added or removed:
            _LOGGER.info(
                "MusicFollowing: re-synced enabled_persons "
                "(added=%s, removed=%s, total=%d)",
                sorted(added), sorted(removed), len(self._enabled_persons),
            )

    def update_house_state(self, new_state: str) -> None:
        """v5.10.0 D2: coordinator pushes the current HouseState value.

        Called from MusicFollowingCoordinator._handle_house_state_changed
        on every SIGNAL_HOUSE_STATE_CHANGED dispatch. Held as a plain
        string on the singleton so _execute_transfer can gate without
        a coordinator round-trip.
        """
        prev = self._current_house_state
        self._current_house_state = new_state or ""
        if prev != self._current_house_state:
            _LOGGER.debug(
                "MusicFollowing: house_state %s → %s",
                prev or "?", self._current_house_state,
            )

    def update_gate_config(
        self,
        sleep_suppress: Optional[bool] = None,
        night_suppress_mode: Optional[str] = None,
        stale_transition_seconds: Optional[float] = None,
    ) -> None:
        """v5.10.0 D2/D6: push CONF values from the coordinator."""
        if sleep_suppress is not None:
            self._sleep_suppress = bool(sleep_suppress)
        if night_suppress_mode is not None:
            self._night_suppress_mode = str(night_suppress_mode)
        if stale_transition_seconds is not None:
            self._stale_transition_seconds = float(stale_transition_seconds)

    async def async_teardown(self) -> None:
        """v5.10.0 D6 (addresses C4): cancel in-flight cleanup tasks and
        clear volatile state so a fresh coordinator wrap sees a clean
        MusicFollowing singleton.

        Safe to call multiple times. Does NOT drop diagnostic listeners —
        those are re-registered by the coordinator on setup.
        """
        for task in list(self._cleanup_tasks):
            try:
                task.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._cleanup_tasks.clear()
        self._saved_volumes.clear()
        self._active_groups.clear()
        self._last_transfer_time.clear()
        self._last_transfer_target.clear()
        _LOGGER.info("MusicFollowing.async_teardown: state cleared")

    # ==========================================================================
    # v3.6.21 C1: TRANSFER STATS & DIAGNOSTICS
    # ==========================================================================

    def add_diagnostic_listener(self, listener) -> None:
        """Register a listener for diagnostic state changes."""
        self._diagnostic_listeners.append(listener)

    # v5.10.0 D8: outcomes that are NOT success/unverified are "skips" for
    # last-skip-reason surface. Kept as a set on the class so tests and
    # sensor code can share the same definition.
    _SKIP_OUTCOMES = frozenset({
        "failed",
        "cooldown_blocked",
        "active_playback_blocked",
        "low_confidence",
        "ping_pong_suppressed",
        "target_unavailable",
        "sleep_suppressed",
        "night_suppressed",
        "source_has_others",
        "same_room",
        "stale_transition",
    })

    def _record_stat(self, outcome: str, person_id: str = "", from_room: str = "", to_room: str = "") -> None:
        """Record a transfer outcome and notify listeners."""
        today = dt_util.now().strftime("%Y-%m-%d")
        if today != self._stats_date:
            # Daily reset
            for key in self._transfer_stats:
                self._transfer_stats[key] = 0
            self._stats_date = today
            # v5.10.0 D1: reset silent-actuator counter on day boundary too
            self._target_unavailable_skips = 0

        if outcome in self._transfer_stats:
            self._transfer_stats[outcome] += 1

        if person_id:
            self._last_transfer_person = person_id
        if from_room:
            self._last_transfer_from = from_room
        if to_room:
            self._last_transfer_to = to_room
        if outcome:
            self._last_transfer_result = outcome
            self._last_transfer_time_iso = dt_util.now().isoformat()

            # v5.10.0 D1+D8: skip-reason surface
            if outcome in self._SKIP_OUTCOMES:
                self._last_skip_reason = outcome
                self._last_skip_from_room = from_room
                self._last_skip_to_room = to_room
                self._last_skip_time_iso = dt_util.now().isoformat()
            if outcome == "target_unavailable":
                self._target_unavailable_skips += 1

        # Notify diagnostic listeners
        for listener in self._diagnostic_listeners:
            try:
                listener()
            except Exception:
                pass

    # Stats that indicate actual music-involved transfer attempts
    _TRANSFER_KEYS = ("success", "failed", "unverified", "active_playback_blocked")

    def get_diagnostic_data(self) -> dict:
        """Return current diagnostic data for sensor consumption."""
        # v3.6.28: Only count music-involved attempts, not pre-music-check rejections
        transfers = sum(self._transfer_stats.get(k, 0) for k in self._TRANSFER_KEYS)
        successes = self._transfer_stats.get("success", 0)
        failures = transfers - successes
        return {
            "state": self._state,
            # v5.10.0 H2 repair (2026-07-13): MF's view of the house state was
            # previously DEBUG-log-only, making the sleep/night gates
            # unverifiable live (the v5.10.0 acceptance oracle pointed at an
            # attribute that never existed). Surfaced for Shipwatch/live use.
            "current_house_state": self._current_house_state or "unknown",
            "active_followers": sorted(self._enabled_persons),
            "last_transfer_from": self._last_transfer_from,
            "last_transfer_to": self._last_transfer_to,
            "last_transfer_person": self._last_transfer_person,
            "last_transfer_time": self._last_transfer_time_iso,
            "last_transfer_result": self._last_transfer_result,
            "transfers_today": transfers,
            "transfer_failures_today": failures,
            "transfer_success_rate": round(successes / transfers * 100, 1) if transfers > 0 else 0.0,
            "active_groups": {k: sorted(v) for k, v in self._active_groups.items()},
            # v5.10.0 D1+D8: skip-reason surface
            "last_skip_reason": self._last_skip_reason,
            "last_skip_from_room": self._last_skip_from_room,
            "last_skip_to_room": self._last_skip_to_room,
            "last_skip_time": self._last_skip_time_iso,
            # v5.10.0 D1: silent-actuator counter for MusicFollowingHealthSensor attrs
            "target_unavailable_today": self._transfer_stats.get("target_unavailable", 0),
            "sleep_suppressed_today": self._transfer_stats.get("sleep_suppressed", 0),
            "night_suppressed_today": self._transfer_stats.get("night_suppressed", 0),
            "source_has_others_today": self._transfer_stats.get("source_has_others", 0),
            "stale_transition_today": self._transfer_stats.get("stale_transition", 0),
        }
    
    async def _on_person_transition(self, transition: RoomTransition) -> None:
        """Handle person transition - transfer music if appropriate."""
        person_id = transition.person_id
        from_room = transition.from_room
        to_room = transition.to_room
        confidence = transition.confidence

        if from_room == to_room:
            _LOGGER.debug("🎵 Ignoring same-room transition: %s in %s", person_id, from_room)
            # v5.10.0 D4: record so operators can see the skip cadence
            self._record_stat("same_room", person_id, from_room, to_room)
            return

        _LOGGER.info(
            "🎵 Transition detected: %s moving %s → %s (confidence=%.2f)",
            person_id, from_room, to_room, confidence
        )

        # Skip if not enabled for this person
        if person_id not in self._enabled_persons:
            _LOGGER.info(
                "🎵 Music transfer skipped: %s not in enabled_persons=%s",
                person_id, list(self._enabled_persons)
            )
            return

        # Skip low-confidence transitions
        if confidence < self.MIN_CONFIDENCE:
            _LOGGER.info(
                "🎵 Music transfer skipped: low confidence %.2f < %.2f threshold",
                confidence, self.MIN_CONFIDENCE
            )
            self._record_stat("low_confidence", person_id, from_room, to_room)
            return

        # v3.6.24: BLE high-confidence distance gate — verify the person's
        # closest scanner distance is within the music-specific threshold.
        # Tighter than person tracking default (8ft vs 10ft) to avoid
        # transferring music on BLE bleed-through from adjacent rooms.
        mf_dist = getattr(self, "_mf_high_confidence_distance", None)
        if mf_dist is not None:
            person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
            if person_coord is not None:
                try:
                    person_data = person_coord.data.get(person_id, {})
                    closest_distance = person_data.get("closest_distance")
                    if closest_distance is not None and closest_distance > mf_dist:
                        _LOGGER.info(
                            "🎵 Music transfer skipped: BLE distance %.1fft > music threshold %.1fft for %s",
                            closest_distance, mf_dist, person_id
                        )
                        self._record_stat("low_confidence", person_id, from_room, to_room)
                        return
                except Exception:
                    pass  # If distance check fails, fall through to confidence-only

        # v5.10.0 D6: fix TOCTOU. Drop the `.locked()` pre-check + separate
        # `async with` acquire in favor of a single `async with` — the
        # previous pattern let two concurrent transitions both pass the
        # check and then serialize, with the second acting on stale
        # context. Now: everyone queues fairly; the stale-transition
        # guard inside _execute_transfer decides whether to skip when
        # unblocked. Transition timestamp is passed through so the
        # guard has a monotonic reference.
        transition_ts = getattr(transition, "timestamp", None)
        async with self._transfer_lock:
            try:
                await self._execute_transfer(
                    person_id, from_room, to_room,
                    transition_ts=transition_ts,
                )
            finally:
                # v3.6.27: Reset state unless transfer succeeded (state="following")
                if self._state not in ("following", "idle"):
                    self._state = "idle"

    def _source_has_other_occupants(self, person_id: str, from_room: str) -> bool:
        """v5.10.0 D3: True iff the source room still has an occupant
        besides ``person_id`` (the person that just transitioned OUT).

        v5.10.0 fix-up FIX-4 (A-HIGH-1): redesigned to avoid false
        positives on the leaver's OWN residual motion/mmwave signal.

        PRIMARY (exact, immune to residual): another TRACKED person's
        current ``location`` equals ``from_room``. Reads the person
        coordinator (writer: person_coordinator.py location-updater
        block around :161-233 which populates the ``location`` key
        for tracked persons).

        SECONDARY (guest coverage — untracked occupants): substrate
        ``occupancy`` kind active on ``from_room``. ``motion`` is
        DELIBERATELY EXCLUDED here because motion-only signals decay
        slowly after the leaver walks out and would false-positive on
        the leaver themselves. ``occupancy`` kinds (contact / seat /
        binary occupancy sensors) latch on real presence, not on
        decaying PIR trails.

        Non-blocking (dict lookups, no await). If the substrate is
        unavailable or the person coord read errors, returns False —
        fail-open (do NOT block transfers on a broken predicate).
        """
        # --- PRIMARY: another tracked person's location matches from_room
        try:
            person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
            if person_coord is not None and hasattr(person_coord, "data"):
                data = person_coord.data or {}
                for other_id, pdata in data.items():
                    if other_id == person_id:
                        continue
                    if not isinstance(pdata, dict):
                        continue
                    loc = pdata.get("location")
                    if not isinstance(loc, str) or not loc:
                        continue
                    # Slug-compare — person coord may store spaces / case.
                    if loc.lower().replace(" ", "_") == (
                        from_room or ""
                    ).lower().replace(" ", "_"):
                        return True
        except Exception:  # noqa: BLE001 — fail-open on predicate error
            pass

        # --- SECONDARY: untracked-occupant coverage via substrate
        # v5.10.0 fix-up FIX-2 (A-CRIT-1): reader — the writer for this
        # key lives in the Presence Coordinator's async_setup at
        # domain_coordinators/presence.py (setdefault call directly
        # after ``OccupancySubstrate(self.hass)`` construction) and is
        # cleaned up in async_teardown symmetrically.
        try:
            substrate = self.hass.data.get(DOMAIN, {}).get("occupancy_substrate")
            if substrate is None:
                # v5.10.0 fix-up A-LOW-4: format-drift canary — the writer
                # lives in Presence Coordinator async_setup. If it's
                # missing here, either presence hasn't set up yet OR the
                # key was renamed. Fail-open (return False) but log DEBUG
                # so the miss is visible in tail-follow.
                _LOGGER.debug(
                    "MusicFollowing D3: occupancy_substrate absent from "
                    "hass.data[%r] — falling through to fail-open "
                    "(person=%r, from_room=%r)",
                    DOMAIN, person_id, from_room,
                )
                return False
            # ONLY the ``occupancy`` kind — see docstring above for why
            # ``motion`` (and ``mmwave``, most residual-prone) are excluded.
            try:
                if substrate.is_kind_active(from_room, "occupancy"):
                    return True
            except Exception:  # noqa: BLE001
                return False
        except Exception:  # noqa: BLE001
            return False
        return False

    def _dwell_room_for_person(self, person_id: str) -> Optional[str]:
        """v5.10.0 D2: return the person's assigned dwell/bedroom, if any.

        Best-effort: reads person_coordinator.data first (which carries a
        "dwell_room" field for tracked persons); falls back to None. Used
        by the HOME_NIGHT dwell-only gate.
        """
        try:
            person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
            if person_coord is None:
                return None
            data = person_coord.data.get(person_id, {}) if hasattr(person_coord, "data") else {}
            dwell = data.get("dwell_room") or data.get("bedroom")
            if isinstance(dwell, str) and dwell:
                return dwell
            # v5.10.0 fix-up A-LOW-4: format-drift canary — log DEBUG when
            # the lookup misses so a future person_coordinator schema
            # change (e.g. renaming ``dwell_room`` → ``bedroom_slug``) is
            # discoverable in the logs before it silently degrades D2.
            _LOGGER.debug(
                "MusicFollowing: no dwell_room/bedroom for person %r "
                "(person_coord.data keys=%s) — HOME_NIGHT dwell_only will "
                "fall through to WARN+block_all fallback",
                person_id,
                sorted(data.keys()) if isinstance(data, dict) else "?",
            )
        except Exception:
            return None
        return None

    def _check_house_state_gate(
        self, person_id: str, from_room: str, to_room: str
    ) -> Optional[str]:
        """v5.10.0 D2 sleep/night gate.

        Returns a stat outcome string ("sleep_suppressed" / "night_suppressed")
        when the transfer should be blocked; None otherwise.

        Falsifiable invariant: During HouseState.SLEEP (with sleep_suppress
        on) MF SHALL NOT call any media_player service. During HOME_NIGHT
        the mode dictates whether transfers proceed.
        """
        state = self._current_house_state
        if not state:
            return None  # coordinator hasn't pushed a state yet — allow
        if state == "sleep" and self._sleep_suppress:
            return "sleep_suppressed"
        if state == "home_night":
            mode = self._night_suppress_mode
            if mode == "block_all":
                return "night_suppressed"
            if mode == "dwell_only":
                dwell = self._dwell_room_for_person(person_id)
                if dwell is None:
                    # v5.10.0 fix-up FIX-3 (A-CRIT-2): no per-person
                    # bedroom surface exists today (person_coordinator
                    # does not populate ``dwell_room`` / ``bedroom`` keys;
                    # see person_coordinator.py location-updater block).
                    # Behave as BLOCK_ALL and log a one-shot WARNING so
                    # the semantics are discoverable — the config-flow
                    # label was updated to name this behavior explicitly.
                    if not self._warned_dwell_only_no_surface:
                        _LOGGER.warning(
                            "MusicFollowing: night_suppress_mode='dwell_only' "
                            "is set, but no per-person bedroom mapping "
                            "surface exists (person_coordinator does not "
                            "expose 'dwell_room'/'bedroom' fields). "
                            "Behaving as 'block_all' — every HOME_NIGHT "
                            "transition will be suppressed. Pick 'off' or "
                            "'block_all' explicitly to silence this warning."
                        )
                        self._warned_dwell_only_no_surface = True
                    return "night_suppressed"
                if dwell.lower().replace(" ", "_") != to_room.lower().replace(" ", "_"):
                    return "night_suppressed"
            # mode == "off" or dwell match — allow
        return None

    async def _execute_transfer(
        self, person_id: str, from_room: str, to_room: str,
        *, transition_ts: Optional[datetime] = None,
    ) -> None:
        """Execute the actual music transfer (called under lock)."""
        now = dt_util.now()

        # v5.10.0 D6: stale-transition guard. If the transition timestamp
        # is significantly older than the moment we acquired the lock,
        # the underlying occupancy context may have changed. Skip.
        if transition_ts is not None:
            try:
                # v5.10.0 fix-up B-MED-1: normalize tz-awareness before
                # subtracting. dt_util.now() is tz-aware (local); the
                # transition timestamp may arrive naive (datetime.now())
                # depending on caller. Coerce both to the same awareness
                # to avoid TypeError on naive-vs-aware subtraction.
                from datetime import timezone as _tz  # noqa: PLC0415
                _now = now
                _ts = transition_ts
                _norm_ok = True
                try:
                    if _now.tzinfo is None and _ts.tzinfo is not None:
                        _now = _now.replace(tzinfo=_tz.utc)
                    elif _now.tzinfo is not None and _ts.tzinfo is None:
                        _ts = _ts.replace(tzinfo=_now.tzinfo)
                except Exception:
                    _LOGGER.debug(
                        "Music transfer: tz normalization failed for "
                        "now=%r transition_ts=%r; treating age as 0",
                        now, transition_ts, exc_info=True,
                    )
                    _norm_ok = False
                if _norm_ok:
                    try:
                        age = (_now - _ts).total_seconds()
                    except Exception:
                        _LOGGER.debug(
                            "Music transfer: tz-normalized subtract failed "
                            "for now=%r transition_ts=%r; age=0",
                            now, transition_ts, exc_info=True,
                        )
                        age = 0.0
                else:
                    age = 0.0
            except Exception:
                age = 0.0
            if age > self._stale_transition_seconds:
                _LOGGER.info(
                    "🎵 Music transfer skipped: transition is %.1fs old "
                    "(threshold %.1fs); context likely changed",
                    age, self._stale_transition_seconds,
                )
                self._record_stat("stale_transition", person_id, from_room, to_room)
                return

        # v5.10.0 D2: sleep/night gate. Runs BEFORE any lookup/service call
        # so the invariant "no media_player action during SLEEP" holds
        # without depending on downstream short-circuits.
        gate_outcome = self._check_house_state_gate(person_id, from_room, to_room)
        if gate_outcome:
            _LOGGER.info(
                "🎵 Music transfer suppressed by house-state gate "
                "(state=%s, outcome=%s, %s: %s → %s)",
                self._current_house_state, gate_outcome, person_id,
                from_room, to_room,
            )
            self._record_stat(gate_outcome, person_id, from_room, to_room)
            return

        # v3.6.20 B2: Transfer cooldown — block repeated transfers to same target
        last_time = self._last_transfer_time.get(person_id)
        last_target = self._last_transfer_target.get(person_id)
        if (last_time and last_target == to_room
                and (now - last_time).total_seconds() < MUSIC_TRANSFER_COOLDOWN_SECONDS):
            _LOGGER.info(
                "🎵 Transfer cooldown: %s → %s blocked (%.0fs since last, cooldown=%ds)",
                person_id, to_room,
                (now - last_time).total_seconds(),
                MUSIC_TRANSFER_COOLDOWN_SECONDS,
            )
            self._record_stat("cooldown_blocked", person_id, from_room, to_room)
            return

        # Get media player entities for rooms
        from_player = await self._get_room_player(from_room)
        to_player = await self._get_room_player(to_room)

        if not from_player:
            _LOGGER.info(
                "🎵 Music transfer skipped: no player found for source room '%s'",
                from_room
            )
            return

        if not to_player:
            _LOGGER.info(
                "🎵 Music transfer skipped: no player found for target room '%s'",
                to_room
            )
            return

        _LOGGER.info("🎵 Players found: %s → %s", from_player, to_player)

        # v5.10.0 D1: Silent-actuator pre-flight. If the target speaker is
        # offline (unavailable/unknown/no state), calling play_media/join
        # would silently no-op and the user would see "music disappeared".
        # Short-circuit BEFORE fading source. Log + counter for observability.
        to_state_preflight = self.hass.states.get(to_player)
        if to_state_preflight is None or to_state_preflight.state in ("unavailable", "unknown"):
            _LOGGER.info(
                "🎵 Music transfer skipped: target '%s' unavailable "
                "(state=%s). Source NOT faded; skip counter incremented.",
                to_player,
                to_state_preflight.state if to_state_preflight else "missing",
            )
            self._record_stat("target_unavailable", person_id, from_room, to_room)
            return

        # v5.10.0 D3: Guest-in-source-room guard. If the source room still
        # has another occupant (motion/mmwave/occupancy any-kind active),
        # transferring OUT would drag their music with us. Non-blocking
        # read of OccupancySubstrate — MUST NOT await into presence coord
        # data while holding the transfer lock.
        if self._source_has_other_occupants(person_id, from_room):
            _LOGGER.info(
                "🎵 Music transfer skipped: source room '%s' still has "
                "other occupants (%s leaves; music stays)",
                from_room, person_id,
            )
            self._record_stat("source_has_others", person_id, from_room, to_room)
            return

        # Check if source is playing
        from_state = self.hass.states.get(from_player)
        if not from_state:
            _LOGGER.info(
                "🎵 Music transfer skipped: source player '%s' state unavailable",
                from_player
            )
            return

        if from_state.state != STATE_PLAYING:
            _LOGGER.info(
                "🎵 Music transfer skipped: source '%s' not playing (state=%s)",
                from_player, from_state.state
            )
            return

        # v3.6.20 B5: Winner rules — don't transfer into a room already playing
        to_state = self.hass.states.get(to_player)
        if to_state and to_state.state == STATE_PLAYING:
            _LOGGER.info(
                "🎵 Active playback blocked: target '%s' already playing, skipping transfer",
                to_player,
            )
            self._record_stat("active_playback_blocked", person_id, from_room, to_room)
            return

        # Get platform info for logging
        source_platform = self._get_player_platform(from_player)
        target_platform = self._get_player_platform(to_player)

        _LOGGER.info(
            "🎵 Starting transfer: %s (%s) → %s (%s) for %s",
            from_player, source_platform, to_player, target_platform, person_id
        )

        # Transfer playback
        self._state = "transferring"
        # v5.10.0 D11+D12: reset per-transfer join flag before dispatch;
        # _transfer_media sets it True on the same-platform join path.
        self._last_transfer_used_join = False
        success = await self._transfer_media(
            from_player, to_player, from_state, to_room=to_room,
        )

        if success:
            # v3.6.20 B3: Post-transfer verification (D12: skip sleep on join)
            verified = await self._verify_transfer(
                to_player, skip_wait=bool(self._last_transfer_used_join),
            )
            if verified:
                _LOGGER.info(
                    "🎵 ✓ Music transfer verified: %s %s → %s",
                    person_id, from_room, to_room
                )
                self._state = "following"
                self._record_stat("success", person_id, from_room, to_room)
                # Record cooldown state
                self._last_transfer_time[person_id] = dt_util.now()
                self._last_transfer_target[person_id] = to_room
                # v3.6.20 B6: Schedule source unjoin for group cleanup
                await self._schedule_group_cleanup(from_player, to_player)
            else:
                # Verification failed — restore source volume
                _LOGGER.warning(
                    "🎵 Transfer unverified: target '%s' not playing after transfer, restoring source",
                    to_player,
                )
                self._state = "idle"
                self._record_stat("unverified", person_id, from_room, to_room)
                await self._restore_volume(from_player)
        else:
            # v3.6.19: Restore source volume on failure
            self._state = "idle"
            self._record_stat("failed", person_id, from_room, to_room)
            await self._restore_volume(from_player)
            _LOGGER.warning(
                "🎵 ✗ Music transfer failed: %s %s → %s (source volume restored)",
                person_id, from_room, to_room
            )

    async def _restore_volume(self, entity_id: str) -> None:
        """Restore a player's volume from saved state."""
        volume = self._saved_volumes.pop(entity_id, None)
        if volume is not None:
            _LOGGER.info("🎵 Restoring %s volume to %.0f%%", entity_id, volume * 100)
            try:
                await self.hass.services.async_call(
                    MEDIA_PLAYER_DOMAIN,
                    SERVICE_VOLUME_SET,
                    {"entity_id": entity_id, "volume_level": volume},
                    blocking=False,
                )
            except Exception as e:
                _LOGGER.warning("🎵 Failed to restore volume for %s: %s", entity_id, e)

    # ==========================================================================
    # v3.6.20 B3: POST-TRANSFER VERIFICATION
    # ==========================================================================

    async def _verify_transfer(
        self, target_entity: str, *, skip_wait: bool = False
    ) -> bool:
        """Verify target is playing after transfer, nudge if needed.

        v5.10.0 D12: ``skip_wait`` skips the initial 2s sleep when the
        transfer used same-platform ``join`` (which is synchronous and
        the target should already be playing). Same-perceived-latency
        drops from ~2.5s to <500ms on the join path.

        1. Wait TRANSFER_VERIFY_DELAY_SECONDS (unless skip_wait), check target state
        2. If not playing, send media_player.media_play nudge
        3. Wait 1s, recheck
        4. Return True if playing, False otherwise
        """
        if not skip_wait:
            await asyncio.sleep(TRANSFER_VERIFY_DELAY_SECONDS)

        state = self.hass.states.get(target_entity)
        if state and state.state == STATE_PLAYING:
            _LOGGER.debug("🎵 Verify: %s is playing (pass)", target_entity)
            return True

        # Nudge — send media_play to resume
        _LOGGER.info("🎵 Verify: %s not playing, sending media_play nudge", target_entity)
        try:
            await self.hass.services.async_call(
                MEDIA_PLAYER_DOMAIN,
                SERVICE_MEDIA_PLAY,
                {"entity_id": target_entity},
                blocking=True,
            )
        except Exception as e:
            _LOGGER.warning("🎵 Verify: media_play nudge failed for %s: %s", target_entity, e)
            return False

        await asyncio.sleep(1)
        state = self.hass.states.get(target_entity)
        if state and state.state == STATE_PLAYING:
            _LOGGER.info("🎵 Verify: %s playing after nudge (pass)", target_entity)
            return True

        _LOGGER.warning("🎵 Verify: %s still not playing after nudge (fail)", target_entity)
        return False

    # ==========================================================================
    # v3.6.20 B6: SPEAKER GROUP CLEANUP
    # ==========================================================================

    async def _schedule_group_cleanup(self, source: str, target: str) -> None:
        """Track group membership and schedule unjoin after delay."""
        # Record group
        if target not in self._active_groups:
            self._active_groups[target] = set()
        self._active_groups[target].add(source)

        async def _delayed_unjoin():
            await asyncio.sleep(GROUP_UNJOIN_DELAY_SECONDS)
            try:
                _LOGGER.info("🎵 Group cleanup: unjoining %s", source)
                await self.hass.services.async_call(
                    MEDIA_PLAYER_DOMAIN,
                    "unjoin",
                    {"entity_id": source},
                    blocking=True,
                )
                # Restore source volume after unjoin
                await self._restore_volume(source)
            except Exception as e:
                _LOGGER.debug("🎵 Group cleanup: unjoin failed for %s: %s", source, e)
            finally:
                # Clean up tracking
                if target in self._active_groups:
                    self._active_groups[target].discard(source)
                    if not self._active_groups[target]:
                        del self._active_groups[target]

        task = self.hass.async_create_task(_delayed_unjoin())
        # v5.10.0 D6 (C9): set discard is O(1) and safe if already removed.
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    def _get_player_platform(self, entity_id: str) -> str:
        """Detect the platform/integration for a media player.
        
        Returns: 'sonos', 'linkplay', 'wiim', 'denonavr', 'music_assistant', or 'generic'
        """
        # Strategy 1: Entity registry lookup (most accurate)
        try:
            from homeassistant.helpers import entity_registry
            ent_reg = entity_registry.async_get(self.hass)
            entry = ent_reg.async_get(entity_id)
            
            if entry and entry.platform:
                platform = entry.platform.lower()
                
                platform_map = {
                    "sonos": PLATFORM_SONOS,
                    "linkplay": PLATFORM_LINKPLAY,
                    "wiim": PLATFORM_WIIM,
                    "denonavr": PLATFORM_DENON,
                    "music_assistant": PLATFORM_MASS,
                    "denon": PLATFORM_DENON,
                    "marantz": PLATFORM_DENON,
                }
                
                if platform in platform_map:
                    detected = platform_map[platform]
                    _LOGGER.debug(
                        "Platform detection: %s is %s (entity registry: %s)", 
                        entity_id, detected, platform
                    )
                    return detected
                
                _LOGGER.debug(
                    "Platform detection: %s has platform '%s' in registry (treating as generic)", 
                    entity_id, platform
                )
                return PLATFORM_GENERIC
                
        except Exception as e:
            _LOGGER.debug("Entity registry lookup failed for %s: %s", entity_id, e)
        
        # Strategy 2: Entity ID pattern matching (fallback)
        entity_id_lower = entity_id.lower()
        
        if "sonos" in entity_id_lower:
            _LOGGER.debug("Platform detection: %s is Sonos (entity_id match)", entity_id)
            return PLATFORM_SONOS
        
        if "denon" in entity_id_lower or "marantz" in entity_id_lower:
            _LOGGER.debug("Platform detection: %s is Denon/Marantz (entity_id match)", entity_id)
            return PLATFORM_DENON
        
        # Strategy 3: Attribute-based detection (last resort)
        state = self.hass.states.get(entity_id)
        if not state:
            _LOGGER.debug("Platform detection: %s has no state, returning generic", entity_id)
            return PLATFORM_GENERIC
        
        attrs = state.attributes
        firmware = attrs.get("firmware_version", "")
        if firmware and "linkplay" in firmware.lower():
            _LOGGER.debug(
                "Platform detection: %s likely Linkplay (firmware=%s) - use entity registry for certainty", 
                entity_id, firmware
            )
            return PLATFORM_GENERIC
        
        _LOGGER.debug("Platform detection: %s is generic (no match found)", entity_id)
        return PLATFORM_GENERIC
    
    async def _get_room_player(self, room_name: str) -> Optional[str]:
        """Get media player entity for room."""
        _LOGGER.debug("Looking for media player in room '%s'", room_name)
        
        room_name_lower = room_name.lower().replace(' ', '_')
        
        # Strategy 1: Check room config for explicit room_media_player
        room_entries = self._get_room_entries()
        room_zone = None
        
        for entry_id, entry_data in room_entries.items():
            entry_room = entry_data.get("room_name", "").lower().replace(' ', '_')
            if entry_room == room_name_lower:
                media_player = entry_data.get("room_media_player")
                if media_player:
                    state = self.hass.states.get(media_player)
                    if state:
                        _LOGGER.info(
                            "Room '%s': Found player via room_media_player config: %s",
                            room_name, media_player
                        )
                        return media_player
                    else:
                        _LOGGER.warning(
                            "Room '%s': Configured room_media_player '%s' not found in HA",
                            room_name, media_player
                        )
                room_zone = entry_data.get("zone")
                break
        
        # Strategy 2: Check zone config for zone_player_entity
        if room_zone:
            zone_player, zone_mode = self._get_zone_player_config(room_zone)
            if zone_player:
                state = self.hass.states.get(zone_player)
                if state:
                    _LOGGER.info(
                        "Room '%s': Found player via zone '%s' config: %s (mode=%s)",
                        room_name, room_zone, zone_player, zone_mode
                    )
                    return zone_player
                else:
                    _LOGGER.warning(
                        "Room '%s': Zone '%s' player '%s' not found in HA",
                        room_name, room_zone, zone_player
                    )
        
        # Strategy 3: HA Area lookup
        try:
            from homeassistant.helpers import area_registry, entity_registry
            
            area_reg = area_registry.async_get(self.hass)
            entity_reg = entity_registry.async_get(self.hass)
            
            matching_area = None
            for area in area_reg.async_list_areas():
                if area.name.lower().replace(' ', '_') == room_name_lower:
                    matching_area = area
                    break
            
            if matching_area:
                area_players = []
                for entity in entity_reg.entities.values():
                    if (entity.area_id == matching_area.id and 
                        entity.domain == "media_player" and
                        not entity.disabled):
                        area_players.append(entity.entity_id)
                
                if area_players:
                    # v5.10.0 D7: prefer multiroom-platform entities over
                    # generic ones (a bedroom_sonos should win over a
                    # bedroom_tv). Sort primarily by multiroom-preference
                    # (True first), then alphabetical for stability.
                    def _prefers_multiroom(eid: str) -> tuple[int, str]:
                        try:
                            pf = self._get_player_platform(eid)
                        except Exception:
                            pf = PLATFORM_GENERIC
                        # Sort key: 0 = multiroom platform (wins), 1 = generic
                        rank = 0 if pf in MULTIROOM_PLATFORMS else 1
                        return (rank, eid)

                    area_players.sort(key=_prefers_multiroom)
                    player = area_players[0]
                    _LOGGER.info(
                        "Room '%s': Found player via HA Area '%s': %s (of %d players)",
                        room_name, matching_area.name, player, len(area_players)
                    )
                    if len(area_players) > 1:
                        # v5.10.0 D7: escalate to WARNING when the picker is
                        # ambiguous. Operators need to see this in logs so
                        # they know to set room_media_player explicitly.
                        _LOGGER.warning(
                            "Room '%s' has %d media players in area. Picked '%s' "
                            "(multiroom-platform preference). Configure "
                            "room_media_player for explicit control. Others: %s",
                            room_name, len(area_players), player, area_players[1:]
                        )
                    return player
                else:
                    _LOGGER.debug(
                        "Room '%s': HA Area '%s' found but has no media_player entities",
                        room_name, matching_area.name
                    )
            else:
                _LOGGER.debug("Room '%s': No matching HA Area found", room_name)
        except Exception as e:
            _LOGGER.debug("Room '%s': HA Area lookup failed: %s", room_name, e)
        
        # Strategy 4: Naming convention fallback
        room_entity = f"media_player.{room_name_lower}"
        state = self.hass.states.get(room_entity)
        if state:
            _LOGGER.info(
                "Room '%s': Found player via naming convention: %s",
                room_name, room_entity
            )
            return room_entity
        
        _LOGGER.debug(
            "Room '%s': No media player found. Tried: config, zone, HA Area, naming (%s)",
            room_name, room_entity
        )
        return None
    
    def _scaled_target_volume(self, to_room: str, source_volume: float) -> float:
        """v5.10.0 D11: apply per-room speaker loudness calibration.

        Reads ``room_media_volume_scale`` from the target room's config
        (default 1.0). Clamped to [MIN, MAX] defined in const.py. Applied
        ONLY on cross-platform generic transfers where absolute volume
        levels aren't directly comparable across platforms.
        """
        # v5.10.0 fix-up A-LOW-3: coerce non-numeric source volume to 0.5
        # (matches the ATTR_MEDIA_VOLUME_LEVEL default in _transfer_media).
        # Player integrations occasionally return None / "None" / an int
        # rather than a float; the scale + clamp math below assumes float.
        try:
            source_volume = float(source_volume)
        except (TypeError, ValueError):
            source_volume = 0.5
        try:
            from .const import (  # noqa: PLC0415
                CONF_ROOM_MEDIA_VOLUME_SCALE,
                DEFAULT_ROOM_MEDIA_VOLUME_SCALE,
                MIN_ROOM_MEDIA_VOLUME_SCALE,
                MAX_ROOM_MEDIA_VOLUME_SCALE,
            )
        except Exception:
            return source_volume
        if not to_room:
            return source_volume
        scale = DEFAULT_ROOM_MEDIA_VOLUME_SCALE
        try:
            room_entries = self._get_room_entries()
            room_name_lower = to_room.lower().replace(" ", "_")
            for entry_data in room_entries.values():
                entry_room = str(
                    entry_data.get("room_name", "")
                ).lower().replace(" ", "_")
                if entry_room == room_name_lower:
                    raw = entry_data.get(CONF_ROOM_MEDIA_VOLUME_SCALE)
                    if raw is not None:
                        scale = float(raw)
                    break
        except Exception:
            return source_volume
        # Clamp.
        if scale < MIN_ROOM_MEDIA_VOLUME_SCALE:
            scale = MIN_ROOM_MEDIA_VOLUME_SCALE
        elif scale > MAX_ROOM_MEDIA_VOLUME_SCALE:
            scale = MAX_ROOM_MEDIA_VOLUME_SCALE
        scaled = max(0.0, min(1.0, source_volume * scale))
        if scale != 1.0:
            _LOGGER.info(
                "🎵 D11: applied volume scale %.2f to room '%s' "
                "(source=%.2f → target=%.2f)",
                scale, to_room, source_volume, scaled,
            )
        return scaled

    def _get_room_entries(self) -> dict:
        """Get all room entry configurations from config entries."""
        try:
            from .const import DOMAIN, CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM
            
            room_entries = {}
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM:
                    merged_config = {**entry.data, **entry.options}
                    room_entries[entry.entry_id] = merged_config
            
            return room_entries
        except Exception as e:
            _LOGGER.debug("Failed to get room entries: %s", e)
            return {}
    
    def _get_zone_player_config(self, zone_name: str) -> tuple[Optional[str], str]:
        """Get zone media player config from Zone Manager or legacy zone entries."""
        try:
            from .const import (
                DOMAIN,
                CONF_ENTRY_TYPE,
                ENTRY_TYPE_ZONE,
                ENTRY_TYPE_ZONE_MANAGER,
                CONF_ZONE_NAME,
                CONF_ZONE_PLAYER_ENTITY,
                CONF_ZONE_PLAYER_MODE,
                ZONE_PLAYER_MODE_FALLBACK,
            )

            zone_name_lower = zone_name.lower()

            # v3.6.0: Check Zone Manager entry first
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
                    merged = {**entry.data, **entry.options}
                    zones_data = merged.get("zones", {})
                    for zn, zone_config in zones_data.items():
                        if zn.lower() == zone_name_lower:
                            player = zone_config.get(CONF_ZONE_PLAYER_ENTITY)
                            mode = zone_config.get(CONF_ZONE_PLAYER_MODE, ZONE_PLAYER_MODE_FALLBACK)
                            _LOGGER.debug(
                                "Zone '%s': Found config in Zone Manager - player=%s, mode=%s",
                                zone_name, player, mode,
                            )
                            return player, mode

            # Fallback: legacy zone entries
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
                    entry_zone = entry.data.get(CONF_ZONE_NAME, "").lower()
                    if entry_zone == zone_name_lower:
                        merged_config = {**entry.data, **entry.options}
                        player = merged_config.get(CONF_ZONE_PLAYER_ENTITY)
                        mode = merged_config.get(CONF_ZONE_PLAYER_MODE, ZONE_PLAYER_MODE_FALLBACK)
                        _LOGGER.debug(
                            "Zone '%s': Found config in legacy entry - player=%s, mode=%s",
                            zone_name, player, mode,
                        )
                        return player, mode

            _LOGGER.debug("Zone '%s': No config found", zone_name)
            return None, "fallback"
            
        except Exception as e:
            _LOGGER.debug("Failed to get zone player config for '%s': %s", zone_name, e)
            return None, "fallback"
    
    async def _transfer_media(
        self,
        from_player: str,
        to_player: str,
        from_state,
        *,
        to_room: str = "",
    ) -> bool:
        """Transfer media playback from one player to another.
        
        v3.3.5.2: Fixed WiiM-to-WiiM to use media_player.join for synchronized playback
        
        Transfer methods:
        - Same platform with multiroom support: media_player.join (SYNCHRONIZED)
        - Cross-platform/Generic: play_media (INDEPENDENT)
        """
        # v5.10.0 fix-up B-MED-2: defensive reset — the caller
        # (_execute_transfer) already resets, but making this authoritative
        # here means any FUTURE caller of _transfer_media can't leak the
        # previous transfer's flag into _verify_transfer.
        self._last_transfer_used_join = False
        try:
            source_platform = self._get_player_platform(from_player)
            target_platform = self._get_player_platform(to_player)

            _LOGGER.info(
                "🎵 Transfer method: %s (%s) → %s (%s)",
                from_player, source_platform, to_player, target_platform
            )

            # v3.6.19: Save source volume before any transfer attempt
            volume = from_state.attributes.get(ATTR_MEDIA_VOLUME_LEVEL, 0.5)
            self._saved_volumes[from_player] = volume

            # Get current playback info
            position = from_state.attributes.get(ATTR_MEDIA_POSITION)
            media_content_id = from_state.attributes.get("media_content_id")
            media_content_type = from_state.attributes.get("media_content_type")
            
            _LOGGER.info(
                "🎵 Source state: volume=%.2f, position=%s, content_id=%s, content_type=%s",
                volume, position, 
                media_content_id[:50] + "..." if media_content_id and len(media_content_id) > 50 else media_content_id,
                media_content_type
            )
            
            transfer_success = False

            _LOGGER.info(
                "🎵 Platform transfer: %s → %s (source: %s, target: %s)",
                source_platform, target_platform, from_player, to_player
            )

            # v3.6.20 B4: MASS queue transfer — best option when both are MASS
            if source_platform == PLATFORM_MASS and target_platform == PLATFORM_MASS:
                _LOGGER.info(
                    "🎵 Using Music Assistant transfer_queue (%s → %s)",
                    from_player, to_player,
                )
                transfer_success = await self._transfer_mass_queue(
                    from_player, to_player, volume
                )
                # Fall through to generic on failure
                if not transfer_success:
                    _LOGGER.info("🎵 MASS transfer_queue failed, falling through to generic")

            # CASE 1: Same platform with multiroom support - Use native grouping
            if not transfer_success and source_platform == target_platform and source_platform in MULTIROOM_PLATFORMS:
                # v5.10.0 D12: mark this path so _verify_transfer can skip
                # the 2s post-transfer sleep (join is synchronous).
                self._last_transfer_used_join = True
                _LOGGER.info(
                    "🎵 Using %s-to-%s native multiroom (media_player.join, SYNCHRONIZED)",
                    source_platform.upper(), target_platform.upper()
                )
                transfer_success = await self._transfer_same_platform_join(
                    from_player, to_player, volume, source_platform
                )

            # CASE 2: Generic fallback - cross-platform or no prior success
            if not transfer_success:
                # v5.10.0 D11: apply per-room volume scale for cross-platform
                # transfers only. Same-platform join preserves the source
                # volume as-is (already handled above); this branch is the
                # place where Sonos-vs-WiiM absolute-volume mismatch bites.
                scaled_volume = self._scaled_target_volume(to_room, volume)
                if source_platform != target_platform:
                    _LOGGER.info(
                        "🎵 Cross-platform transfer (%s → %s): using generic play_media (INDEPENDENT). "
                        "Different platforms use incompatible multiroom protocols.",
                        source_platform, target_platform
                    )
                else:
                    _LOGGER.info(
                        "🎵 Same platform (%s) generic fallback: using play_media (INDEPENDENT)",
                        source_platform
                    )
                transfer_success = await self._transfer_generic(
                    from_player, to_player, scaled_volume, position,
                    media_content_id, media_content_type
                )
            
            if not transfer_success:
                _LOGGER.warning("🎵 Primary transfer failed, playback may not have started on target")
                return False

            # v3.6.19: Only fade source if transfer succeeded
            _LOGGER.info("🎵 Fading source %s to %.0f%%", from_player, self.FADE_OUT_VOLUME * 100)
            await self.hass.services.async_call(
                MEDIA_PLAYER_DOMAIN,
                SERVICE_VOLUME_SET,
                {
                    "entity_id": from_player,
                    "volume_level": self.FADE_OUT_VOLUME
                },
                blocking=False
            )

            return True
            
        except Exception as e:
            _LOGGER.error("🎵 Music transfer failed with exception: %s", e)
            import traceback
            _LOGGER.debug("🎵 Traceback: %s", traceback.format_exc())
            return False
    
    async def _transfer_same_platform_join(
        self,
        from_player: str,
        to_player: str,
        volume: float,
        platform: str
    ) -> bool:
        """Transfer between two players of the same platform using native grouping.
        
        v3.3.5.2: Unified method for Sonos, Linkplay, and WiiM
        
        All these platforms support media_player.join for synchronized multiroom.
        """
        try:
            _LOGGER.info(
                "🎵 %s: Joining %s to group with %s (synchronized multiroom)",
                platform.upper(), to_player, from_player
            )
            
            # Join target to source's group
            await self.hass.services.async_call(
                MEDIA_PLAYER_DOMAIN,
                "join",
                {
                    "entity_id": to_player,
                    "group_members": [from_player]
                },
                blocking=True
            )
            
            # Set volume on target
            _LOGGER.info("🎵 %s: Setting target volume to %.0f%%", platform.upper(), volume * 100)
            await self.hass.services.async_call(
                MEDIA_PLAYER_DOMAIN,
                SERVICE_VOLUME_SET,
                {
                    "entity_id": to_player,
                    "volume_level": volume
                },
                blocking=False
            )
            
            _LOGGER.info("🎵 %s: Synchronized transfer successful", platform.upper())
            return True

        except Exception as e:
            _LOGGER.warning(
                "🎵 %s: media_player.join failed (%s), trying fallback",
                platform.upper(), e
            )
            return False

    async def _transfer_mass_queue(
        self,
        from_player: str,
        to_player: str,
        volume: float,
    ) -> bool:
        """Transfer via Music Assistant transfer_queue service.

        v3.6.20 B4: Best option when both source and target are MASS players.
        Transfers full queue + position, MASS handles source pause internally.
        """
        try:
            _LOGGER.info(
                "🎵 MASS: transfer_queue %s → %s",
                from_player, to_player,
            )
            await self.hass.services.async_call(
                "music_assistant",
                "transfer_queue",
                {
                    "source": from_player,
                    "target": to_player,
                },
                blocking=True,
            )

            # Set volume on target
            _LOGGER.info("🎵 MASS: Setting target volume to %.0f%%", volume * 100)
            await self.hass.services.async_call(
                MEDIA_PLAYER_DOMAIN,
                SERVICE_VOLUME_SET,
                {"entity_id": to_player, "volume_level": volume},
                blocking=False,
            )

            _LOGGER.info("🎵 MASS: Queue transfer successful")
            return True

        except Exception as e:
            _LOGGER.warning("🎵 MASS: transfer_queue failed (%s)", e)
            return False

    async def _transfer_generic(
        self,
        from_player: str,
        to_player: str,
        volume: float,
        position: Optional[int],
        media_content_id: Optional[str],
        media_content_type: Optional[str]
    ) -> bool:
        """Generic transfer using play_media service.
        
        Used for cross-platform transfers. Starts INDEPENDENT playback.
        """
        try:
            if not media_content_id or not media_content_type:
                _LOGGER.warning(
                    "🎵 Generic transfer failed: No media_content_id/type available "
                    "for %s → %s. Source may be playing from Line In, AirPlay, "
                    "Bluetooth, or another source that doesn't expose content_id. "
                    "Configure room_media_player and use same-platform speakers "
                    "to enable native multiroom (join) instead.",
                    from_player, to_player,
                )
                return False
            
            _LOGGER.info(
                "🎵 Generic: Playing media on %s (content_type=%s, INDEPENDENT playback)",
                to_player, media_content_type
            )
            
            await self.hass.services.async_call(
                MEDIA_PLAYER_DOMAIN,
                "play_media",
                {
                    "entity_id": to_player,
                    "media_content_id": media_content_id,
                    "media_content_type": media_content_type
                },
                blocking=True
            )
            
            _LOGGER.info("🎵 Generic: Setting volume to %.0f%%", volume * 100)
            await self.hass.services.async_call(
                MEDIA_PLAYER_DOMAIN,
                SERVICE_VOLUME_SET,
                {
                    "entity_id": to_player,
                    "volume_level": volume
                },
                blocking=False
            )
            
            if position and position > 0:
                # v3.6.21: Offset position by ~3s to account for transfer latency
                # (service call round-trip + buffering + startup)
                offset_position = position + 3
                _LOGGER.info(
                    "🎵 Generic: Seeking to position %d seconds (original %d + 3s offset)",
                    offset_position, position,
                )
                try:
                    await self.hass.services.async_call(
                        MEDIA_PLAYER_DOMAIN,
                        "media_seek",
                        {
                            "entity_id": to_player,
                            "seek_position": offset_position,
                        },
                        blocking=False
                    )
                except Exception as seek_error:
                    _LOGGER.debug("🎵 Generic: Seek failed (not supported): %s", seek_error)
            
            _LOGGER.info("🎵 Generic: Transfer successful (independent playback)")
            return True
            
        except Exception as e:
            _LOGGER.error("🎵 Generic transfer failed: %s", e)
            return False
    
    async def manual_transfer(self, person_id: str, from_room: str, to_room: str) -> bool:
        """Manually trigger music transfer (for testing/automation)."""
        _LOGGER.info(
            "🎵 Manual transfer requested: %s from '%s' to '%s'",
            person_id, from_room, to_room
        )
        
        from_player = await self._get_room_player(from_room)
        to_player = await self._get_room_player(to_room)
        
        if not from_player:
            _LOGGER.warning("🎵 Manual transfer failed: no player in source room '%s'", from_room)
            return False
        
        if not to_player:
            _LOGGER.warning("🎵 Manual transfer failed: no player in target room '%s'", to_room)
            return False
        
        from_state = self.hass.states.get(from_player)
        if not from_state:
            _LOGGER.warning("🎵 Manual transfer failed: source player '%s' unavailable", from_player)
            return False
        
        if from_state.state != STATE_PLAYING:
            _LOGGER.warning(
                "🎵 Manual transfer failed: source '%s' not playing (state=%s)",
                from_player, from_state.state
            )
            return False
        
        return await self._transfer_media(
            from_player, to_player, from_state, to_room=to_room,
        )
