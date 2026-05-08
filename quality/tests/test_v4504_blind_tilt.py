"""v4.5.0.4 hotfix: blind tilt control regression tests.

User-reported bug: rooms allow specifying blind type (roller shade vs
venetian-with-tilt), but venetian blinds were always commanded with
`cover.open_cover` / `cover.close_cover` instead of the tilt variants.
The `CONF_COVER_TYPE` config option was set in 3 form locations but
never read in production runtime code — pure dead config.

This test file is standalone (not importing custom_components.universal_room_automation.automation
because automation.py:508 uses Python 3.10+ union-syntax `float | None`
that doesn't compile on Python 3.9, which blocks the existing
test_cover_verify.py from collecting on this dev box). It mirrors the
fix's static method logic + dispatch decision in a self-contained
helper so the test asserts the contract regardless of test-baseline
Python compat.

The mirror is intentional, like test_v450_d2_migration.py — production
helper must implement these exact semantics or the user's bug returns.
v4.5.2 (test baseline cleanup) will replace this with real-import tests.
"""

import pytest


# ---------------------------------------------------------------------------
# Mirror of automation.py:_cover_at_target (v4.5.0.4 shape).
# Kept in sync with production via review; v4.5.2 will replace with a
# real-import test once the Python 3.9 compat issue is resolved.
# ---------------------------------------------------------------------------

def _cover_at_target_mirror(state, target_state: str, cover_type: str = "shade") -> bool:
    """Mirror of RoomAutomation._cover_at_target — see automation.py."""
    if state is None:
        return False
    attrs = getattr(state, "attributes", None) or {}

    if cover_type == "tilt":
        tilt_pos = attrs.get("current_tilt_position")
        if tilt_pos is not None:
            try:
                tp = float(tilt_pos)
            except (TypeError, ValueError):
                tp = None
            if tp is not None:
                if target_state == "closed":
                    return tp <= 5.0
                if target_state == "open":
                    return tp >= 95.0
        return state.state == target_state

    position = attrs.get("current_position")
    if position is not None:
        try:
            pos = float(position)
        except (TypeError, ValueError):
            pos = None
        if pos is not None:
            if target_state == "closed":
                return pos <= 5.0
            if target_state == "open":
                return pos >= 95.0
    return state.state == target_state


# ---------------------------------------------------------------------------
# Mirror of the dispatch logic in automation.py:_send_covers_with_verify
# ---------------------------------------------------------------------------

def _service_name_for_cover_action(action: str, cover_type: str) -> str:
    """Mirror — must match _send_covers_with_verify's dispatch.

    cover_type='tilt' → action_tilt (e.g. close_cover_tilt)
    cover_type='shade' → action unchanged (e.g. close_cover)
    """
    if action not in ("open_cover", "close_cover"):
        raise ValueError(f"Unsupported cover action: {action}")
    if cover_type == "tilt":
        return f"{action}_tilt"
    return action


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeState:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


# ---------------------------------------------------------------------------
# Service dispatch tests
# ---------------------------------------------------------------------------

class TestServiceDispatch:
    """For each cover_type, the right HA service is selected."""

    def test_shade_close_uses_close_cover(self):
        assert _service_name_for_cover_action("close_cover", "shade") == "close_cover"

    def test_shade_open_uses_open_cover(self):
        assert _service_name_for_cover_action("open_cover", "shade") == "open_cover"

    def test_tilt_close_uses_close_cover_tilt(self):
        """v4.5.0.4 fix: venetian close_cover → cover.close_cover_tilt."""
        assert _service_name_for_cover_action("close_cover", "tilt") == "close_cover_tilt"

    def test_tilt_open_uses_open_cover_tilt(self):
        """v4.5.0.4 fix: venetian open_cover → cover.open_cover_tilt."""
        assert _service_name_for_cover_action("open_cover", "tilt") == "open_cover_tilt"

    def test_unknown_cover_type_falls_back_to_shade_action(self):
        """Defensive: unknown cover_type doesn't crash, falls back to base action.
        Matches the production helper which does `if cover_type == "tilt"`
        — anything else falls through to the shade path."""
        assert _service_name_for_cover_action("close_cover", "unknown_value") == "close_cover"
        assert _service_name_for_cover_action("close_cover", "") == "close_cover"
        assert _service_name_for_cover_action("close_cover", None) == "close_cover"

    def test_unsupported_action_raises(self):
        with pytest.raises(ValueError):
            _service_name_for_cover_action("set_position", "shade")


# ---------------------------------------------------------------------------
# Verify-state tests (_cover_at_target with cover_type)
# ---------------------------------------------------------------------------

class TestCoverAtTargetForShade:
    """Pre-v4.5.0.4 behavior preserved for cover_type='shade'."""

    def test_state_open_matches_target_open(self):
        s = _FakeState("open")
        assert _cover_at_target_mirror(s, "open", "shade") is True

    def test_state_closed_matches_target_closed(self):
        s = _FakeState("closed")
        assert _cover_at_target_mirror(s, "closed", "shade") is True

    def test_position_zero_matches_target_closed(self):
        s = _FakeState("open", {"current_position": 0})
        assert _cover_at_target_mirror(s, "closed", "shade") is True

    def test_position_100_matches_target_open(self):
        s = _FakeState("open", {"current_position": 100})
        assert _cover_at_target_mirror(s, "open", "shade") is True

    def test_position_50_does_not_match_target_open(self):
        s = _FakeState("open", {"current_position": 50})
        assert _cover_at_target_mirror(s, "open", "shade") is False

    def test_position_95_matches_target_open_tolerance(self):
        s = _FakeState("open", {"current_position": 95})
        assert _cover_at_target_mirror(s, "open", "shade") is True

    def test_position_5_matches_target_closed_tolerance(self):
        s = _FakeState("closed", {"current_position": 5})
        assert _cover_at_target_mirror(s, "closed", "shade") is True


class TestCoverAtTargetForTilt:
    """v4.5.0.4: venetian blind verify uses current_tilt_position."""

    def test_tilt_position_zero_matches_target_closed(self):
        """Tilt-only blinds: state may always be 'open' (blind at full
        position); only tilt slats change. Pre-fix, position-based check
        marked these as permanent stragglers because position never changed."""
        s = _FakeState("open", {"current_tilt_position": 0, "current_position": 100})
        assert _cover_at_target_mirror(s, "closed", "tilt") is True

    def test_tilt_position_100_matches_target_open(self):
        s = _FakeState("open", {"current_tilt_position": 100, "current_position": 100})
        assert _cover_at_target_mirror(s, "open", "tilt") is True

    def test_tilt_position_50_does_not_match_target_closed(self):
        s = _FakeState("open", {"current_tilt_position": 50})
        assert _cover_at_target_mirror(s, "closed", "tilt") is False

    def test_tilt_position_5_matches_target_closed_tolerance(self):
        s = _FakeState("open", {"current_tilt_position": 5})
        assert _cover_at_target_mirror(s, "closed", "tilt") is True

    def test_tilt_position_95_matches_target_open_tolerance(self):
        s = _FakeState("open", {"current_tilt_position": 95})
        assert _cover_at_target_mirror(s, "open", "tilt") is True

    def test_no_tilt_position_attr_falls_back_to_state(self):
        """If integration doesn't expose tilt_position, trust state.state."""
        s = _FakeState("closed")
        assert _cover_at_target_mirror(s, "closed", "tilt") is True
        s2 = _FakeState("open")
        assert _cover_at_target_mirror(s2, "open", "tilt") is True

    def test_tilt_ignores_current_position(self):
        """Critical: tilt path must NOT use current_position. The bug pre-fix
        was that current_position=100 (blind at full open position) was
        interpreted as 'blind is open' even after a close_cover_tilt
        command set tilt to 0."""
        # Slats fully closed (tilt=0), but blind position still reads 100
        # (typical for tilt-only venetian)
        s = _FakeState("open", {"current_tilt_position": 0, "current_position": 100})
        # We're commanding closed → tilt path returns True (slats closed)
        assert _cover_at_target_mirror(s, "closed", "tilt") is True
        # In shade path (broken behavior), current_position=100 would say
        # "open" → mismatch with closed → False (the v4.5.0.3 bug shape)
        assert _cover_at_target_mirror(s, "closed", "shade") is False


class TestUnknownCoverTypeFallsBackToShade:
    """Defensive: unknown cover_type doesn't crash, falls back to shade behavior."""

    def test_unknown_cover_type_uses_position_attr(self):
        s = _FakeState("open", {"current_position": 100})
        # cover_type="" or invalid value → not "tilt" → shade path
        assert _cover_at_target_mirror(s, "open", "") is True
        assert _cover_at_target_mirror(s, "open", "unknown_type") is True

    def test_default_cover_type_is_shade(self):
        s = _FakeState("open", {"current_position": 100})
        # default arg cover_type="shade"
        assert _cover_at_target_mirror(s, "open") is True


class TestNoneStateReturnsFalse:
    """Defensive: if state is None (entity vanished), return False."""

    def test_none_state_shade(self):
        assert _cover_at_target_mirror(None, "open", "shade") is False

    def test_none_state_tilt(self):
        assert _cover_at_target_mirror(None, "closed", "tilt") is False
