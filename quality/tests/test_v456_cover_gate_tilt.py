"""v4.5.6 — Cover gate helpers + timed-path determinism (CONF_COVER_TYPE
sibling sites, Bug Class #33).

User report: 2 venetian blinds (Study A, Master Bedroom) stayed open
past their automation time tonight. History showed both with
`state="closed"` but `current_tilt_position=97` (Study A) and `=100`
(Master Bedroom) — i.e. position 0 (blind fully lowered) but slats
wide open. URA's `_are_covers_already_closed()` checked
`state.state != "closed"`, so the gate returned True and silently
skipped the timed-close runner.

Same root cause as v4.5.0.4's blind-tilt fix (CONF_COVER_TYPE was
collected but the runtime branch was missing) — but in a different
helper. v4.5.0.4 fixed `_send_covers_with_verify` (dispatch) and
`_cover_at_target` (verify). The gate helpers `_are_covers_already_open`
and `_are_covers_already_closed` were missed. Bug Class #33.

v4.5.6 fix has two parts:

  1. **Timed paths drop the gate entirely.** A scheduled action should
     fire deterministically; verify resolves a no-op in zero retries,
     so cost is one extra idempotent service call per day. Closes the
     specific reproducer.

  2. **Entry/exit gate helpers become cover_type-aware** with the same
     5/95 thresholds the verify path already uses. Tilt blinds with
     slats genuinely open (tilt > 5) no longer mis-detect as "already
     closed" because the entity's position-driven `state` happens to
     be "closed".

Mirror-style tests (factory's helpers aren't cleanly importable
without HA core; matches v4.5.0.4's pattern).
"""

import pytest


# ---------------------------------------------------------------------------
# Mirror of the v4.5.6 _are_covers_already_* helpers in automation.py
# ---------------------------------------------------------------------------

def _are_covers_already_open_mirror(states_by_id, available, cover_type):
    if not available:
        return True
    for cover_id in available:
        state = states_by_id.get(cover_id)
        if state is None:
            return False
        if cover_type == "tilt":
            tilt = state.attributes.get("current_tilt_position")
            if tilt is None:
                if state.state != "open":
                    return False
                continue
            try:
                if float(tilt) < 95.0:
                    return False
            except (TypeError, ValueError):
                if state.state != "open":
                    return False
        else:
            if state.state != "open":
                return False
    return True


def _are_covers_already_closed_mirror(states_by_id, available, cover_type):
    if not available:
        return True
    for cover_id in available:
        state = states_by_id.get(cover_id)
        if state is None:
            return False
        if cover_type == "tilt":
            tilt = state.attributes.get("current_tilt_position")
            if tilt is None:
                if state.state != "closed":
                    return False
                continue
            try:
                if float(tilt) > 5.0:
                    return False
            except (TypeError, ValueError):
                if state.state != "closed":
                    return False
        else:
            if state.state != "closed":
                return False
    return True


class _MockState:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


# ---------------------------------------------------------------------------
# Tests — gate helpers (entry/exit paths)
# ---------------------------------------------------------------------------

class TestGateClosedShadeUnchanged:
    """Shade path is byte-equivalent to pre-v4.5.6 behavior."""

    def test_shade_state_closed_returns_true(self):
        states = {"cover.x": _MockState("closed")}
        assert _are_covers_already_closed_mirror(states, ["cover.x"], "shade") is True

    def test_shade_state_open_returns_false(self):
        states = {"cover.x": _MockState("open")}
        assert _are_covers_already_closed_mirror(states, ["cover.x"], "shade") is False


class TestGateClosedTiltAware:
    """The bug from the user report, plus the new tilt branch behaviors."""

    def test_user_reproducer_tilt_open_blind_lowered_returns_false(self):
        """Reproducer: state='closed' (position=0) but tilt=97 (slats open).
        Pre-v4.5.6 returned True → silent skip → user's nightly close
        never fired for Study A and Master Bedroom blinds."""
        states = {
            "cover.study_a_blinds": _MockState(
                "closed", {"current_position": 0, "current_tilt_position": 97}
            ),
        }
        assert _are_covers_already_closed_mirror(
            states, ["cover.study_a_blinds"], "tilt"
        ) is False, (
            "tilt blind with slats open at 97 must NOT be detected as "
            "already closed — this was the v4.5.6 reproducer."
        )

    def test_tilt_fully_closed_returns_true(self):
        states = {"cover.x": _MockState("closed", {"current_tilt_position": 0})}
        assert _are_covers_already_closed_mirror(states, ["cover.x"], "tilt") is True

    def test_tilt_at_5_returns_true(self):
        """Threshold matches verify path's `tp <= 5.0` for parity."""
        states = {"cover.x": _MockState("closed", {"current_tilt_position": 5})}
        assert _are_covers_already_closed_mirror(states, ["cover.x"], "tilt") is True

    def test_tilt_just_above_5_returns_false(self):
        states = {"cover.x": _MockState("closed", {"current_tilt_position": 6})}
        assert _are_covers_already_closed_mirror(states, ["cover.x"], "tilt") is False

    def test_tilt_partial_returns_false(self):
        states = {"cover.x": _MockState("open", {"current_tilt_position": 50})}
        assert _are_covers_already_closed_mirror(states, ["cover.x"], "tilt") is False

    def test_tilt_no_attr_falls_back_to_state(self):
        """Integration that doesn't expose tilt position — fall back."""
        states = {"cover.x": _MockState("closed")}
        assert _are_covers_already_closed_mirror(states, ["cover.x"], "tilt") is True

        states = {"cover.x": _MockState("open")}
        assert _are_covers_already_closed_mirror(states, ["cover.x"], "tilt") is False

    def test_tilt_invalid_attr_falls_back_to_state(self):
        states = {"cover.x": _MockState("closed", {"current_tilt_position": "n/a"})}
        assert _are_covers_already_closed_mirror(states, ["cover.x"], "tilt") is True


class TestGateOpenTiltAware:
    """Mirror of TestGateClosedTiltAware for the open helper."""

    def test_tilt_open_blind_raised_returns_true(self):
        states = {"cover.x": _MockState("open", {"current_position": 100, "current_tilt_position": 100})}
        assert _are_covers_already_open_mirror(states, ["cover.x"], "tilt") is True

    def test_tilt_at_95_returns_true(self):
        states = {"cover.x": _MockState("open", {"current_tilt_position": 95})}
        assert _are_covers_already_open_mirror(states, ["cover.x"], "tilt") is True

    def test_tilt_just_below_95_returns_false(self):
        states = {"cover.x": _MockState("open", {"current_tilt_position": 94})}
        assert _are_covers_already_open_mirror(states, ["cover.x"], "tilt") is False

    def test_tilt_at_zero_returns_false(self):
        states = {"cover.x": _MockState("closed", {"current_tilt_position": 0})}
        assert _are_covers_already_open_mirror(states, ["cover.x"], "tilt") is False

    def test_tilt_inverse_position_zero_slats_open(self):
        """Position 0 (blind down) but slats genuinely open at 100 —
        sibling case to the v4.5.6 closed-side reproducer. The user's
        Master Bedroom presented this exact shape."""
        states = {"cover.mb_shade": _MockState("closed", {"current_position": 0, "current_tilt_position": 100})}
        assert _are_covers_already_open_mirror(states, ["cover.mb_shade"], "tilt") is True


class TestGateMixedAndEdgeCases:
    def test_all_unavailable_returns_true(self):
        """Empty available list — no-op semantics, return True so dispatch
        doesn't try to act on nothing."""
        assert _are_covers_already_closed_mirror({}, [], "tilt") is True
        assert _are_covers_already_open_mirror({}, [], "tilt") is True

    def test_one_cover_missing_state_returns_false(self):
        """Defensive: if any cover's state is None, treat as not-in-target
        (matches pre-v4.5.6 behavior)."""
        states = {"cover.x": _MockState("closed", {"current_tilt_position": 0})}
        assert _are_covers_already_closed_mirror(
            states, ["cover.x", "cover.missing"], "tilt"
        ) is False

    def test_multiple_covers_all_must_be_closed(self):
        states = {
            "cover.a": _MockState("closed", {"current_tilt_position": 0}),
            "cover.b": _MockState("closed", {"current_tilt_position": 4}),
        }
        assert _are_covers_already_closed_mirror(
            states, ["cover.a", "cover.b"], "tilt"
        ) is True

    def test_multiple_covers_one_open_returns_false(self):
        states = {
            "cover.a": _MockState("closed", {"current_tilt_position": 0}),
            "cover.b": _MockState("closed", {"current_tilt_position": 50}),
        }
        assert _are_covers_already_closed_mirror(
            states, ["cover.a", "cover.b"], "tilt"
        ) is False


# ---------------------------------------------------------------------------
# Source-contract tests — production must match the mirror
# ---------------------------------------------------------------------------

class TestSourceContract:
    @pytest.fixture
    def src(self):
        with open("custom_components/universal_room_automation/automation.py") as f:
            return f.read()

    def test_gate_helpers_are_cover_type_aware(self, src):
        for fn_name in ("_are_covers_already_open", "_are_covers_already_closed"):
            idx = src.find(f"def {fn_name}(self)")
            assert idx > 0, f"{fn_name} must exist"
            body_end = src.find("\n    def ", idx + 1)
            body = src[idx:body_end if body_end > 0 else idx + 4000]
            assert "CONF_COVER_TYPE" in body, (
                f"{fn_name} must read CONF_COVER_TYPE — Bug Class #33 "
                f"prevention. The gate's behavior must depend on the "
                f"same config field the dispatcher and verify path use."
            )
            assert "current_tilt_position" in body, (
                f"{fn_name} must inspect current_tilt_position for the "
                f"tilt branch (matches verify path semantics)."
            )

    def test_timed_close_does_not_call_already_closed_gate(self, src):
        """Timed close fires deterministically — no 'already closed' gate."""
        idx = src.find("async def check_timed_cover_close(self)")
        assert idx > 0
        body_end = src.find("\n    async def ", idx + 1)
        if body_end == -1:
            body_end = src.find("\n    def ", idx + 1)
        body = src[idx:body_end] if body_end > 0 else src[idx:idx + 4000]
        # Match the actual call (not narrative comments mentioning the name).
        assert "self._are_covers_already_closed()" not in body, (
            "check_timed_cover_close must not call _are_covers_already_closed() "
            "— v4.5.6 removed it so the schedule fires deterministically; this "
            "is the user's reproducer fix and a Bug Class #33 closure."
        )

    def test_timed_open_does_not_call_already_open_gate(self, src):
        """Mirror: timed open also fires deterministically."""
        idx = src.find("async def check_timed_cover_open(self)")
        assert idx > 0
        body_end = src.find("\n    async def ", idx + 1)
        if body_end == -1:
            body_end = src.find("\n    def ", idx + 1)
        body = src[idx:body_end] if body_end > 0 else src[idx:idx + 4000]
        assert "self._are_covers_already_open()" not in body, (
            "check_timed_cover_open must not call _are_covers_already_open() "
            "— same v4.5.6 deterministic-schedule contract as the close side."
        )

    def test_entry_path_still_uses_gate(self, src):
        """The entry/exit paths SHOULD keep the gate (high call frequency
        per occupancy event makes the dedup valuable). Ensure we didn't
        over-delete."""
        # Just count remaining call sites — should be exactly 2:
        # _control_covers_entry uses _are_covers_already_open;
        # _control_covers_exit (or wherever exit-close lives) uses
        # _are_covers_already_closed.
        open_calls = src.count("self._are_covers_already_open()")
        closed_calls = src.count("self._are_covers_already_closed()")
        # Each helper retains exactly one call site after v4.5.6 removed
        # the timed paths' calls.
        assert open_calls == 1, (
            f"Expected 1 call to _are_covers_already_open() (entry path); "
            f"found {open_calls}. v4.5.6 removed only the timed-open call."
        )
        assert closed_calls == 1, (
            f"Expected 1 call to _are_covers_already_closed() (exit path); "
            f"found {closed_calls}. v4.5.6 removed only the timed-close call."
        )
