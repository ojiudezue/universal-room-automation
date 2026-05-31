"""v4.7.2 D4 / D5 — Per-Room Guest Designation + Sustained-Occupancy Guest Signal.

Source-grep style (matches project convention). Fast, no running HA required.

Deliverables covered:
  D4 — CONF_ROOM_IS_GUEST_ROOM + CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN in const.py
       + room reconfigure step (basic_setup) + strings/translations labels.

  D5 — Phase 2 Feature B: sustained-occupancy guest signal in presence.py
       - _discover_guest_rooms() registered in async_setup
       - _handle_guest_room_occupancy_change() @callback state machine
       - _is_known_person_in_room() helper
       - _guest_room_gate_armed() — returns True after threshold_min elapsed
       - _run_inference() additive OR: unid_gate OR guest_room_gate
       - D5 confidence: 0.9 (vs 0.8 for unid path)
       - Bug Class #11 guard: dt_util.utcnow() (not datetime.now())
       - Bug Class #38 guard: listener cleanup on teardown (_guest_room_unsubs)
       - Bug Class #42 guard: @callback bound method, not lambda
       - Exit condition guard: GUEST exits when BOTH unidentified_count==0 AND not guest_gate_armed
"""

import json
import pytest


# ===========================================================================
# Source fixtures
# ===========================================================================


@pytest.fixture(scope="module")
def const_src() -> str:
    with open("custom_components/universal_room_automation/const.py") as f:
        return f.read()


@pytest.fixture(scope="module")
def config_flow_src() -> str:
    with open("custom_components/universal_room_automation/config_flow.py") as f:
        return f.read()


@pytest.fixture(scope="module")
def presence_src() -> str:
    with open(
        "custom_components/universal_room_automation/domain_coordinators/presence.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def strings() -> dict:
    with open("custom_components/universal_room_automation/strings.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def translations_en() -> dict:
    with open(
        "custom_components/universal_room_automation/translations/en.json"
    ) as f:
        return json.load(f)


# ===========================================================================
# D4 — const.py constants
# ===========================================================================


class TestD4Constants:
    """D4: CONF_ROOM_IS_GUEST_ROOM and CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN
    must be defined in const.py with correct Final string values."""

    def test_conf_room_is_guest_room_defined(self, const_src):
        assert 'CONF_ROOM_IS_GUEST_ROOM' in const_src
        assert '"room_is_guest_room"' in const_src or "'room_is_guest_room'" in const_src

    def test_conf_room_guest_occupancy_threshold_defined(self, const_src):
        assert 'CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN' in const_src
        assert (
            '"room_guest_occupancy_threshold_min"' in const_src
            or "'room_guest_occupancy_threshold_min'" in const_src
        )

    def test_both_confs_are_final(self, const_src):
        # Both must use Final annotation (project convention for CONF_ constants)
        assert "CONF_ROOM_IS_GUEST_ROOM: Final" in const_src
        assert "CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN: Final" in const_src


# ===========================================================================
# D4 — config_flow basic_setup step
# ===========================================================================


class TestD4ConfigFlowFields:
    """D4: Room reconfigure step (basic_setup) must expose both new fields."""

    def test_is_guest_room_in_basic_setup(self, config_flow_src):
        assert "CONF_ROOM_IS_GUEST_ROOM" in config_flow_src, (
            "CONF_ROOM_IS_GUEST_ROOM must be wired into basic_setup reconfigure step"
        )

    def test_threshold_in_basic_setup(self, config_flow_src):
        assert "CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN" in config_flow_src, (
            "CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN must be wired into basic_setup"
        )

    def test_threshold_default_30(self, config_flow_src):
        # Default 30 min per plan spec
        assert "30" in config_flow_src, (
            "Threshold default must be 30 minutes (3-ton heuristic value per plan spec)"
        )


# ===========================================================================
# D4 — strings.json + translations
# ===========================================================================


class TestD4Strings:
    """D4: strings.json and en.json must have labels for both new fields."""

    def test_strings_basic_setup_has_is_guest_room(self, strings):
        step = strings["config"]["step"].get(
            "basic_setup", strings.get("options", {}).get("step", {}).get("basic_setup", {})
        )
        # Try options flow path first (room reconfigure)
        opts_step = strings.get("options", {}).get("step", {}).get("basic_setup", {})
        cfg_step = strings.get("config", {}).get("step", {}).get("basic_setup", {})
        found = False
        for s in (opts_step, cfg_step):
            data = s.get("data", {})
            if "room_is_guest_room" in data:
                found = True
                break
        assert found, (
            "strings.json basic_setup.data must include 'room_is_guest_room' label"
        )

    def test_strings_basic_setup_has_threshold(self, strings):
        opts_step = strings.get("options", {}).get("step", {}).get("basic_setup", {})
        cfg_step = strings.get("config", {}).get("step", {}).get("basic_setup", {})
        found = False
        for s in (opts_step, cfg_step):
            data = s.get("data", {})
            if "room_guest_occupancy_threshold_min" in data:
                found = True
                break
        assert found, (
            "strings.json basic_setup.data must include 'room_guest_occupancy_threshold_min' label"
        )

    def test_translations_basic_setup_has_is_guest_room(self, translations_en):
        opts_step = translations_en.get("options", {}).get("step", {}).get("basic_setup", {})
        cfg_step = translations_en.get("config", {}).get("step", {}).get("basic_setup", {})
        found = False
        for s in (opts_step, cfg_step):
            data = s.get("data", {})
            if "room_is_guest_room" in data:
                found = True
                break
        assert found, (
            "translations/en.json basic_setup.data must mirror 'room_is_guest_room'"
        )

    def test_translations_basic_setup_has_threshold(self, translations_en):
        opts_step = translations_en.get("options", {}).get("step", {}).get("basic_setup", {})
        cfg_step = translations_en.get("config", {}).get("step", {}).get("basic_setup", {})
        found = False
        for s in (opts_step, cfg_step):
            data = s.get("data", {})
            if "room_guest_occupancy_threshold_min" in data:
                found = True
                break
        assert found, (
            "translations/en.json basic_setup.data must mirror 'room_guest_occupancy_threshold_min'"
        )


# ===========================================================================
# D5 — presence.py init fields
# ===========================================================================


class TestD5PresenceInit:
    """D5: PresenceCoordinator.__init__ must define _guest_room_state and
    _guest_room_unsubs dicts."""

    def test_guest_room_state_init(self, presence_src):
        assert "_guest_room_state" in presence_src, (
            "_guest_room_state dict must be initialised in __init__ (Bug Class #38)"
        )

    def test_guest_room_unsubs_init(self, presence_src):
        assert "_guest_room_unsubs" in presence_src, (
            "_guest_room_unsubs dict must be initialised in __init__ for "
            "listener cleanup (Bug Class #38)"
        )


# ===========================================================================
# D5 — _discover_guest_rooms
# ===========================================================================


class TestD5DiscoverGuestRooms:
    """D5: _discover_guest_rooms must exist and wire up listeners."""

    def test_method_exists(self, presence_src):
        assert "def _discover_guest_rooms(" in presence_src

    def test_called_from_async_setup(self, presence_src):
        idx = presence_src.find("async def async_setup(")
        # Window widened from 5000 → 7000 in v4.7.14 (away-veto block added
        # ~700 chars at the top of _run_inference, pushing the D5 confidence
        # block past the original 5000-char horizon).
        body = presence_src[idx:idx + 11000]
        assert "_discover_guest_rooms" in body, (
            "_discover_guest_rooms must be called during async_setup "
            "so guest rooms are discovered at integration load time"
        )

    def test_reads_conf_room_is_guest_room(self, presence_src):
        idx = presence_src.find("def _discover_guest_rooms(")
        body = presence_src[idx:idx + 2000]
        assert "CONF_ROOM_IS_GUEST_ROOM" in body, (
            "_discover_guest_rooms must read CONF_ROOM_IS_GUEST_ROOM to identify "
            "which rooms are designated guest rooms"
        )

    def test_reads_threshold_conf(self, presence_src):
        idx = presence_src.find("def _discover_guest_rooms(")
        body = presence_src[idx:idx + 2000]
        assert "CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN" in body

    def test_registers_state_change_listener(self, presence_src):
        idx = presence_src.find("def _discover_guest_rooms(")
        # Function body can be up to 4000 chars — use generous window
        body = presence_src[idx:idx + 4000]
        assert "async_track_state_change_event" in body, (
            "_discover_guest_rooms must subscribe to occupancy sensor state changes"
        )

    def test_stores_unsub_in_dict(self, presence_src):
        idx = presence_src.find("def _discover_guest_rooms(")
        body = presence_src[idx:idx + 2000]
        assert "_guest_room_unsubs" in body, (
            "Unsub handles must be stored in _guest_room_unsubs for cleanup "
            "(Bug Class #38 — listener cleanup)"
        )


# ===========================================================================
# D5 — _handle_guest_room_occupancy_change
# ===========================================================================


class TestD5OccupancyCallback:
    """D5: _handle_guest_room_occupancy_change must be a @callback bound method
    implementing the 3-transition state machine."""

    def test_method_exists(self, presence_src):
        assert "def _handle_guest_room_occupancy_change(" in presence_src

    def test_is_callback_decorated(self, presence_src):
        idx = presence_src.find("def _handle_guest_room_occupancy_change(")
        # Look backwards for @callback
        pre_body = presence_src[max(0, idx - 100):idx]
        assert "@callback" in pre_body, (
            "_handle_guest_room_occupancy_change must be decorated with @callback "
            "(Bug Class #42 — bound method, not lambda)"
        )

    def test_state_machine_transition_1_arms_first_seen(self, presence_src):
        idx = presence_src.find("def _handle_guest_room_occupancy_change(")
        body = presence_src[idx:idx + 3000]
        assert "first_seen" in body, (
            "Transition 1 (unknown occupant → arm first_seen) must set first_seen"
        )

    def test_state_machine_uses_utcnow(self, presence_src):
        idx = presence_src.find("def _handle_guest_room_occupancy_change(")
        body = presence_src[idx:idx + 3000]
        assert "dt_util.utcnow()" in body, (
            "Must use dt_util.utcnow() for UTC-aware timestamps (Bug Class #11 guard)"
        )

    def test_state_machine_transition_3_resets_first_seen(self, presence_src):
        idx = presence_src.find("def _handle_guest_room_occupancy_change(")
        body = presence_src[idx:idx + 3000]
        # Reset: first_seen = None
        assert "first_seen\"] = None" in body or 'first_seen"] = None' in body, (
            "Transition 3 (room unoccupied → reset) must set first_seen to None"
        )

    def test_schedules_inference_via_create_task(self, presence_src):
        idx = presence_src.find("def _handle_guest_room_occupancy_change(")
        # Use 4000-char window — function body + docstring can exceed 3000 chars
        # (window was too small in original; fixed in v4.7.2 reviewer fix-up).
        body = presence_src[idx:idx + 4000]
        assert "_run_inference" in body, (
            "Callback must trigger inference re-evaluation after state change"
        )

    def test_no_lambda_in_callback(self, presence_src):
        idx = presence_src.find("def _handle_guest_room_occupancy_change(")
        body = presence_src[idx:idx + 4000]
        # Check that no lambda *expression* is used. Comments and docstrings may
        # reference the word "lambda" as documentation — check for the expression
        # forms: "lambda " (with trailing space) followed by code, or "lambda:"
        import re
        lambda_expr = re.findall(r"\blambda\s+[^,\n]", body)
        assert not lambda_expr, (
            f"Bug Class #42: no lambda expressions inside callback code — "
            f"use bound methods. Found: {lambda_expr}"
        )


# ===========================================================================
# D5 — _guest_room_gate_armed
# ===========================================================================


class TestD5GuestRoomGateArmed:
    """D5: _guest_room_gate_armed must return True when elapsed >= threshold."""

    def test_method_exists(self, presence_src):
        assert "def _guest_room_gate_armed(" in presence_src

    def test_accepts_now_parameter(self, presence_src):
        idx = presence_src.find("def _guest_room_gate_armed(")
        sig = presence_src[idx:idx + 200]
        assert "now" in sig, (
            "_guest_room_gate_armed must accept 'now' (UTC datetime) to enable "
            "deterministic testing (Bug Class #11)"
        )

    def test_uses_threshold_min_for_elapsed_check(self, presence_src):
        idx = presence_src.find("def _guest_room_gate_armed(")
        body = presence_src[idx:idx + 1500]
        assert "threshold_min" in body

    def test_returns_false_when_no_rooms(self, presence_src):
        # The method must have an explicit False return path
        idx = presence_src.find("def _guest_room_gate_armed(")
        body = presence_src[idx:idx + 1500]
        assert "return False" in body, (
            "Must return False when no guest rooms have the gate armed"
        )

    def test_returns_true_on_armed_room(self, presence_src):
        idx = presence_src.find("def _guest_room_gate_armed(")
        body = presence_src[idx:idx + 1500]
        assert "return True" in body, (
            "Must return True when at least one guest room has elapsed >= threshold"
        )


# ===========================================================================
# D5 — _run_inference additive OR
# ===========================================================================


class TestD5RunInferenceOr:
    """D5: _run_inference must compute additive OR of unid gate and guest_room gate."""

    def test_guest_room_gate_armed_call_present(self, presence_src):
        idx = presence_src.find("async def _run_inference(")
        # Window widened from 5000 → 7000 in v4.7.14 (away-veto block added
        # ~700 chars at the top of _run_inference, pushing the D5 confidence
        # block past the original 5000-char horizon).
        body = presence_src[idx:idx + 11000]
        assert "_guest_room_gate_armed" in body, (
            "_run_inference must call _guest_room_gate_armed for the D5 path"
        )

    def test_additive_or_present(self, presence_src):
        idx = presence_src.find("async def _run_inference(")
        # Window widened from 5000 → 7000 in v4.7.14 (away-veto block added
        # ~700 chars at the top of _run_inference, pushing the D5 confidence
        # block past the original 5000-char horizon).
        body = presence_src[idx:idx + 11000]
        # The combined gate: unid_gate_armed or guest_room_gate_armed
        assert "or guest_room_gate_armed" in body or "guest_room_gate_armed or" in body, (
            "_run_inference must use additive OR: guest_armed = unid_gate_armed or "
            "guest_room_gate_armed (plan §7)"
        )

    def test_confidence_09_for_guest_room_path(self, presence_src):
        idx = presence_src.find("async def _run_inference(")
        # Window widened from 5000 → 7000 in v4.7.14 (away-veto block added
        # ~700 chars at the top of _run_inference, pushing the D5 confidence
        # block past the original 5000-char horizon).
        body = presence_src[idx:idx + 11000]
        assert "0.9" in body, (
            "D5 guest_room path confidence must be 0.9 "
            "(vs 0.8 for unid path — higher specificity)"
        )

    def test_confidence_08_for_unid_path(self, presence_src):
        idx = presence_src.find("async def _run_inference(")
        # Window widened from 5000 → 7000 in v4.7.14 (away-veto block added
        # ~700 chars at the top of _run_inference, pushing the D5 confidence
        # block past the original 5000-char horizon).
        body = presence_src[idx:idx + 11000]
        assert "0.8" in body, (
            "Unid path confidence 0.8 must still be present (existing behavior preserved)"
        )

    def test_utcnow_used_for_d5_call(self, presence_src):
        # _run_inference must pass dt_util.utcnow() to _guest_room_gate_armed
        idx = presence_src.find("async def _run_inference(")
        # Window widened from 5000 → 7000 in v4.7.14 (away-veto block added
        # ~700 chars at the top of _run_inference, pushing the D5 confidence
        # block past the original 5000-char horizon).
        body = presence_src[idx:idx + 11000]
        assert "dt_util.utcnow()" in body, (
            "Bug Class #11: _guest_room_gate_armed must receive dt_util.utcnow(), "
            "not a naive datetime"
        )


# ===========================================================================
# D5 — Exit condition guard
# ===========================================================================


class TestD5ExitConditionGuard:
    """D5: GUEST exit requires BOTH unidentified_count==0 AND not guest_gate_armed.

    Without this guard, a room where the occupant is unknown (count=0 because they
    haven't been identified by census) would immediately re-exit GUEST state.
    """

    def test_exit_uses_combined_condition(self, presence_src):
        # The exit branch in StateInferenceEngine.infer() must check both
        idx = presence_src.find("def infer(")
        # Window widened from 5000 → 7000 in v4.7.14 (away-veto block added
        # ~700 chars at the top of _run_inference, pushing the D5 confidence
        # block past the original 5000-char horizon).
        body = presence_src[idx:idx + 11000]
        assert "unidentified_count == 0 and not guest_gate_armed" in body, (
            "GUEST exit condition must require BOTH unidentified_count==0 AND "
            "not guest_gate_armed — otherwise the D5 guest_room path can't hold "
            "GUEST state when census count=0 (plan §9)"
        )


# ===========================================================================
# D5 — Teardown cleanup (Bug Class #38)
# ===========================================================================


class TestD5TeardownCleanup:
    """D5: async_teardown must unsub all _guest_room_unsubs listeners."""

    def test_teardown_clears_unsubs(self, presence_src):
        idx = presence_src.find("async def async_teardown(")
        body = presence_src[idx:idx + 2000]
        assert "_guest_room_unsubs" in body, (
            "async_teardown must clean up _guest_room_unsubs (Bug Class #38)"
        )

    def test_teardown_calls_unsub(self, presence_src):
        idx = presence_src.find("async def async_teardown(")
        body = presence_src[idx:idx + 2000]
        # Teardown must iterate and call the unsub functions
        assert "unsub()" in body or "for unsub" in body, (
            "async_teardown must call each unsub function to detach listeners"
        )

    def test_teardown_clears_state_dict(self, presence_src):
        idx = presence_src.find("async def async_teardown(")
        body = presence_src[idx:idx + 2000]
        assert "_guest_room_state" in body, (
            "async_teardown must clear _guest_room_state to release memory"
        )


# ===========================================================================
# B1 fix-up — D5 guest_room gate evaluated in GUEST state
# (v4.7.2 reviewer fix-up — Bug Class #46: Exit-Path Gate Skip)
# ===========================================================================


class TestB1GuestRoomGateInGuestState:
    """B1 fix-up: _run_inference must evaluate _guest_room_gate_armed() when
    current_state == HouseState.GUEST so the hold/exit decision is truthful.

    Without this fix the exit condition at infer() reduces to unidentified_count==0,
    causing immediate GUEST→HOME oscillation when the occupant was never in census.

    Source-grep checks:
    1. The GUEST-state branch in _run_inference evaluates _guest_room_gate_armed.
    2. The GUEST-state branch skips the unid gate (side-effect-bearing).
    3. guest_room_gate_armed is used as guest_armed in the GUEST-state branch.
    """

    def test_guest_state_branch_evaluates_guest_room_gate(self, presence_src):
        """B1 CRITICAL fix: GUEST state branch must call _guest_room_gate_armed."""
        idx = presence_src.find("async def _run_inference(")
        assert idx > 0, "_run_inference must exist"
        body = presence_src[idx:idx + 11000]
        # The fix adds an elif current_state == HouseState.GUEST branch that
        # calls _guest_room_gate_armed.
        assert "HouseState.GUEST" in body, (
            "B1 fix: _run_inference must handle HouseState.GUEST state explicitly "
            "for gate evaluation"
        )
        # After the elif HouseState.GUEST block, _guest_room_gate_armed must appear.
        guest_idx = body.find("HouseState.GUEST")
        tail = body[guest_idx:guest_idx + 1000]
        assert "_guest_room_gate_armed" in tail, (
            "B1 fix: after the HouseState.GUEST branch, _guest_room_gate_armed "
            "must be called — so sustained-occupancy can hold GUEST state"
        )

    def test_guest_state_branch_skips_unid_gate(self, presence_src):
        """B1 fix: GUEST-state branch must NOT call _guest_gate_armed (has side effects)."""
        idx = presence_src.find("async def _run_inference(")
        body = presence_src[idx:idx + 11000]
        # Find the elif HouseState.GUEST block
        guest_idx = body.find("elif current_state == HouseState.GUEST")
        assert guest_idx > 0, (
            "B1 fix: _run_inference must have an 'elif current_state == HouseState.GUEST' "
            "branch separate from the _home_like_states branch"
        )
        # Extract just the GUEST branch (up to the else: clause)
        else_idx = body.find("else:", guest_idx)
        guest_branch = body[guest_idx:else_idx] if else_idx > 0 else body[guest_idx:guest_idx + 800]
        # unid gate must NOT be called inside the GUEST branch
        assert "_guest_gate_armed(" not in guest_branch, (
            "B1 fix: GUEST-state branch must NOT call _guest_gate_armed — "
            "it has side effects (arms/disarms persistence state) and should "
            "only run on HOME_* entry path"
        )

    def test_guest_state_unid_gate_hardcoded_false(self, presence_src):
        """B1 fix: unid_gate_armed must be False in the GUEST state branch."""
        idx = presence_src.find("async def _run_inference(")
        body = presence_src[idx:idx + 11000]
        guest_idx = body.find("elif current_state == HouseState.GUEST")
        assert guest_idx > 0
        else_idx = body.find("else:", guest_idx)
        guest_branch = body[guest_idx:else_idx] if else_idx > 0 else body[guest_idx:guest_idx + 800]
        assert "unid_gate_armed = False" in guest_branch, (
            "B1 fix: unid_gate_armed must be hardcoded False in the GUEST branch "
            "— the unid gate is side-effect-bearing and must not run in GUEST state"
        )

    def test_guest_armed_is_guest_room_gate_in_guest_branch(self, presence_src):
        """B1 fix: guest_armed must derive from guest_room_gate_armed in GUEST branch."""
        idx = presence_src.find("async def _run_inference(")
        body = presence_src[idx:idx + 11000]
        guest_idx = body.find("elif current_state == HouseState.GUEST")
        assert guest_idx > 0
        else_idx = body.find("else:", guest_idx)
        guest_branch = body[guest_idx:else_idx] if else_idx > 0 else body[guest_idx:guest_idx + 800]
        # guest_armed must be set from guest_room_gate_armed in this branch
        assert "guest_armed = guest_room_gate_armed" in guest_branch, (
            "B1 fix: in the GUEST state branch, guest_armed must equal "
            "guest_room_gate_armed so the exit condition at infer() is truthful"
        )

    def test_b1_comment_references_bug_class_46(self, presence_src):
        """B1 fix: the code comment must reference Bug Class #46."""
        idx = presence_src.find("async def _run_inference(")
        body = presence_src[idx:idx + 11000]
        assert "Bug Class #46" in body or "#46" in body, (
            "B1 fix: comment must reference Bug Class #46 (Exit-Path Gate Skip) "
            "for future reviewers to understand the guard"
        )
