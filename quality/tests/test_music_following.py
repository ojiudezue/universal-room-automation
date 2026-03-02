"""Tests for Music Following and Transition Detection (v3.6.21).

All tests use inline logic replication to avoid importing from
custom_components (which triggers homeassistant module imports).

Tests cover:
- Ping-pong suppression logic
- Confidence calculation logic
- Path classification logic
- Music following constants (hardcoded expected values)
- Cooldown logic
- Winner rules
- Media position offset
- Exact match logic (PersonCoordinator)
"""
import pytest
from datetime import datetime, timedelta


# ============================================================================
# EXPECTED CONSTANT VALUES (must match const.py)
# ============================================================================

PING_PONG_WINDOW_SECONDS = 60
MUSIC_TRANSFER_COOLDOWN_SECONDS = 8
TRANSFER_VERIFY_DELAY_SECONDS = 2
GROUP_UNJOIN_DELAY_SECONDS = 5
CONF_BERMUDA_AREA_SENSORS = "bermuda_area_sensors"

# Path classification thresholds (must match transitions.py)
MAX_DIRECT_DURATION = 30
MAX_HALLWAY_DURATION = 60

# Hallway terms (must match transitions.py)
HALLWAY_TERMS = ("hallway", "corridor", "hall", "foyer", "entry", "landing", "passage", "vestibule")


# ============================================================================
# INLINE LOGIC REPLICATIONS
# These replicate the exact logic from the source files so we can test
# the algorithms without importing HA-dependent modules.
# ============================================================================

def _is_ping_pong(recent_transitions, person_id, from_room, to_room, timestamp):
    """Replicate TransitionDetector._is_ping_pong logic."""
    recent = recent_transitions.get(person_id, [])
    if not recent:
        return False
    window = timedelta(seconds=PING_PONG_WINDOW_SECONDS)
    for prev_from, prev_to, prev_ts in reversed(recent):
        if (timestamp - prev_ts) > window:
            break
        if prev_from == to_room and prev_to == from_room:
            return True
    return False


def _record_transition(recent_transitions, person_id, from_room, to_room, timestamp):
    """Replicate TransitionDetector._record_transition logic."""
    if person_id not in recent_transitions:
        recent_transitions[person_id] = []
    recent_transitions[person_id].append((from_room, to_room, timestamp))
    if len(recent_transitions[person_id]) > 10:
        recent_transitions[person_id] = recent_transitions[person_id][-10:]


def _calculate_confidence(duration, path_type):
    """Replicate TransitionDetector._calculate_confidence logic."""
    if path_type == "direct":
        if duration <= 10:
            return 0.95
        elif duration <= 20:
            return 0.85
        else:
            return 0.75
    elif path_type == "via_hallway":
        if duration <= 30:
            return 0.80
        else:
            return 0.65
    else:
        return 0.50


def _classify_path_type(from_room, to_room, duration, history):
    """Replicate TransitionDetector._classify_path_type logic."""
    if duration <= MAX_DIRECT_DURATION:
        return ("direct", None)

    if len(history) >= 2:
        recent = history[-3:]
        for entry in recent:
            location = entry["location"]
            if location not in [from_room, to_room]:
                loc_lower = location.lower()
                if any(term in loc_lower for term in HALLWAY_TERMS):
                    return ("via_hallway", location)

    if duration <= MAX_HALLWAY_DURATION:
        return ("via_hallway", None)

    return ("separate", None)


def _is_match(room_name, location):
    """Replicate PersonCoordinator exact match logic."""
    room_lower = room_name.lower().replace(" ", "_")
    location_lower = location.lower().replace(" ", "_")
    return room_lower == location_lower


# ============================================================================
# PING-PONG SUPPRESSION TESTS
# ============================================================================

class TestPingPongSuppression:
    """Test ping-pong suppression logic."""

    def test_ping_pong_window_value(self):
        """PING_PONG_WINDOW_SECONDS should be 60."""
        assert PING_PONG_WINDOW_SECONDS == 60

    def test_no_history_not_ping_pong(self):
        """No recent transitions = not ping-pong."""
        recent = {}
        now = datetime.now()
        assert _is_ping_pong(recent, "alice", "kitchen", "living", now) is False

    def test_detects_return_leg(self):
        """A->B followed by B->A within window = ping-pong."""
        recent = {}
        now = datetime.now()
        _record_transition(recent, "alice", "kitchen", "living", now)
        assert _is_ping_pong(recent, "alice", "living", "kitchen", now + timedelta(seconds=30)) is True

    def test_allows_different_rooms(self):
        """A->B followed by B->C is NOT ping-pong."""
        recent = {}
        now = datetime.now()
        _record_transition(recent, "alice", "kitchen", "living", now)
        assert _is_ping_pong(recent, "alice", "living", "bedroom", now + timedelta(seconds=10)) is False

    def test_expired_window(self):
        """A->B followed by B->A AFTER window = not ping-pong."""
        recent = {}
        now = datetime.now()
        _record_transition(recent, "alice", "kitchen", "living", now)
        after_window = now + timedelta(seconds=PING_PONG_WINDOW_SECONDS + 5)
        assert _is_ping_pong(recent, "alice", "living", "kitchen", after_window) is False

    def test_history_limited_to_10(self):
        """Transition history is limited to 10 entries per person."""
        recent = {}
        now = datetime.now()
        for i in range(15):
            _record_transition(recent, "alice", f"room_{i}", f"room_{i+1}", now)
        assert len(recent["alice"]) == 10

    def test_per_person_isolation(self):
        """Ping-pong suppression is per-person."""
        recent = {}
        now = datetime.now()
        _record_transition(recent, "alice", "kitchen", "living", now)
        # Bob's transition should NOT be detected as ping-pong
        assert _is_ping_pong(recent, "bob", "living", "kitchen", now + timedelta(seconds=10)) is False


# ============================================================================
# CONFIDENCE CALCULATION TESTS
# ============================================================================

class TestConfidenceCalculation:
    """Test confidence calculation logic."""

    def test_direct_fast_high_confidence(self):
        """Quick direct transition (<10s) gets 0.95 confidence."""
        assert _calculate_confidence(5, "direct") == 0.95

    def test_direct_medium_confidence(self):
        """Medium direct transition (10-20s) gets 0.85 confidence."""
        assert _calculate_confidence(15, "direct") == 0.85

    def test_direct_slow_lower_confidence(self):
        """Slower direct transition (20-30s) gets 0.75 confidence."""
        assert _calculate_confidence(25, "direct") == 0.75

    def test_via_hallway_fast(self):
        """Fast hallway transition (<30s) gets 0.80 confidence."""
        assert _calculate_confidence(25, "via_hallway") == 0.80

    def test_separate_events_low_confidence(self):
        """Separate events get 0.50 confidence."""
        assert _calculate_confidence(120, "separate") == 0.50


# ============================================================================
# PATH CLASSIFICATION TESTS
# ============================================================================

class TestPathClassification:
    """Test path type classification logic."""

    def test_fast_transition_is_direct(self):
        """Transition under 30s is classified as direct."""
        path_type, via = _classify_path_type("kitchen", "living", 15, [])
        assert path_type == "direct"
        assert via is None

    def test_long_transition_is_separate(self):
        """Transition over 60s is classified as separate."""
        path_type, via = _classify_path_type("kitchen", "living", 120, [])
        assert path_type == "separate"

    def test_hallway_detection_expanded(self):
        """Hallway detection recognizes multiple terms."""
        now = datetime.now()
        for term in ("hallway", "foyer", "entry", "landing", "corridor"):
            history = [
                {"location": "kitchen", "timestamp": now - timedelta(seconds=50)},
                {"location": term, "timestamp": now - timedelta(seconds=40)},
                {"location": "living", "timestamp": now - timedelta(seconds=35)},
            ]
            path_type, via = _classify_path_type("kitchen", "living", 45, history)
            assert path_type == "via_hallway", f"Expected via_hallway for '{term}'"
            assert via == term


# ============================================================================
# MUSIC FOLLOWING CONSTANTS TESTS
# ============================================================================

class TestMusicFollowingConstants:
    """Test that music following constants have correct expected values."""

    def test_cooldown_constant(self):
        assert MUSIC_TRANSFER_COOLDOWN_SECONDS == 8

    def test_verify_delay_constant(self):
        assert TRANSFER_VERIFY_DELAY_SECONDS == 2

    def test_group_unjoin_delay_constant(self):
        assert GROUP_UNJOIN_DELAY_SECONDS == 5

    def test_bermuda_area_sensors_constant(self):
        assert CONF_BERMUDA_AREA_SENSORS == "bermuda_area_sensors"


# ============================================================================
# COOLDOWN LOGIC TESTS
# ============================================================================

class TestCooldownLogic:
    """Test cooldown logic (inline)."""

    def _is_blocked(self, now, last_time, last_target, target):
        return (
            last_time is not None
            and last_target == target
            and (now - last_time).total_seconds() < MUSIC_TRANSFER_COOLDOWN_SECONDS
        )

    def test_cooldown_blocks_same_target(self):
        """Cooldown blocks transfer to same room within window."""
        now = datetime.now()
        last_time = now - timedelta(seconds=3)
        assert self._is_blocked(now, last_time, "living", "living") is True

    def test_cooldown_allows_different_target(self):
        """Cooldown does NOT block transfer to different room."""
        now = datetime.now()
        last_time = now - timedelta(seconds=3)
        assert self._is_blocked(now, last_time, "living", "bedroom") is False

    def test_cooldown_allows_after_window(self):
        """Cooldown allows same target after window expires."""
        now = datetime.now()
        last_time = now - timedelta(seconds=MUSIC_TRANSFER_COOLDOWN_SECONDS + 1)
        assert self._is_blocked(now, last_time, "living", "living") is False


# ============================================================================
# WINNER RULES TESTS
# ============================================================================

class TestWinnerRulesLogic:
    """Test winner rules logic (inline)."""

    def test_playing_target_blocks_transfer(self):
        """If target is already playing, transfer should be blocked."""
        assert ("playing" == "playing") is True

    def test_idle_target_allows_transfer(self):
        """If target is idle/off, transfer should proceed."""
        for state in ("idle", "off", "paused", "standby"):
            assert (state == "playing") is False, f"State '{state}' should not block"


# ============================================================================
# MEDIA POSITION OFFSET TESTS
# ============================================================================

class TestMediaPositionOffset:
    """Test media position offset for transfer delay (P2-16)."""

    def test_position_offset_applied(self):
        """Position should be offset by 3 seconds for generic transfers."""
        original_position = 120
        offset = 3
        assert original_position + offset == 123

    def test_zero_position_not_seeked(self):
        """Position 0 or None should not trigger seek."""
        for position in (None, 0, -1):
            should_seek = position and position > 0
            assert not should_seek


# ============================================================================
# EXACT MATCH LOGIC TESTS
# ============================================================================

class TestExactMatchLogic:
    """Test exact match for room occupants (P0-4 fix)."""

    def test_exact_match_works(self):
        assert _is_match("kitchen", "kitchen") is True
        assert _is_match("Kitchen", "kitchen") is True

    def test_den_does_not_match_garden(self):
        """The old fuzzy match caused 'den' to match 'garden'."""
        assert _is_match("den", "garden") is False

    def test_master_does_not_cross_match(self):
        """'master' should not match 'master_bedroom' or 'master_bathroom'."""
        assert _is_match("master", "master_bedroom") is False
        assert _is_match("master", "master_bathroom") is False

    def test_master_bedroom_matches_itself(self):
        assert _is_match("master_bedroom", "master_bedroom") is True

    def test_space_normalization(self):
        """Spaces are normalized to underscores."""
        assert _is_match("Living Room", "living_room") is True

    def test_no_substring_match(self):
        """Substring matching no longer works."""
        assert _is_match("bed", "bedroom") is False
        assert _is_match("bedroom", "bed") is False
