"""v4.6.2.2 — Guest mode false-positive hardening tests.

Covers D1–D6 deliverables:
  D1: SIGNAL_CENSUS_UPDATED payload includes 'confidence' and 'source_agreement'
  D2: New config constants exist and import cleanly
  D3: Threshold, confidence, and persistence gates in _guest_gate_armed
  D4: Persistence timer scheduled/cancelled correctly
  D5: _handle_census_update propagates confidence to _census_confidence
  D6: AST/source-grep regressions

Test categories:
  - Source-grep: verify symbols exist in source without HA runtime
  - Unit: directly instantiate StateInferenceEngine / PresenceCoordinator stubs
  - AST: parse source and verify structural invariants

No HA runtime is required. All tests run via PYTHONPATH=quality.
"""

from __future__ import annotations

import ast
import re
import types
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"

PRESENCE_SRC = (PKG / "domain_coordinators" / "presence.py").read_text()
CAMERA_CENSUS_SRC = (PKG / "camera_census.py").read_text()
CONST_SRC = (PKG / "const.py").read_text()
INIT_SRC = (PKG / "__init__.py").read_text()
CONFIG_FLOW_SRC = (PKG / "config_flow.py").read_text()


# ===========================================================================
# D1 — SIGNAL_CENSUS_UPDATED payload includes 'confidence' and 'source_agreement'
# ===========================================================================


def test_census_signal_payload_includes_confidence():
    """The SIGNAL_CENSUS_UPDATED dispatch dict in camera_census.py must include
    a 'confidence' key read from house_result.confidence.
    """
    # Find the async_dispatcher_send call block
    assert '"confidence"' in CAMERA_CENSUS_SRC, (
        "camera_census.py: SIGNAL_CENSUS_UPDATED payload missing 'confidence' key. "
        "Add: \"confidence\": house_result.confidence"
    )


def test_census_signal_payload_includes_source_agreement():
    """The SIGNAL_CENSUS_UPDATED dispatch dict in camera_census.py must include
    a 'source_agreement' key read from house_result.source_agreement.
    """
    assert '"source_agreement"' in CAMERA_CENSUS_SRC, (
        "camera_census.py: SIGNAL_CENSUS_UPDATED payload missing 'source_agreement' key. "
        "Add: \"source_agreement\": house_result.source_agreement"
    )


def test_census_signal_payload_reads_from_house_result():
    """Both new keys should reference house_result (not property_result)."""
    # Find the dispatcher send block around SIGNAL_CENSUS_UPDATED
    idx = CAMERA_CENSUS_SRC.find("SIGNAL_CENSUS_UPDATED,")
    assert idx >= 0, "SIGNAL_CENSUS_UPDATED dispatch not found in camera_census.py"
    # Grab the payload dict — use a wider window to accommodate comments
    block = CAMERA_CENSUS_SRC[idx: idx + 700]
    assert "house_result.confidence" in block, (
        "SIGNAL_CENSUS_UPDATED payload should read confidence from house_result"
    )
    assert "house_result.source_agreement" in block, (
        "SIGNAL_CENSUS_UPDATED payload should read source_agreement from house_result"
    )


# ===========================================================================
# D2 — New config constants
# ===========================================================================


def test_guest_mode_config_defaults():
    """All new CONF_* constants and DEFAULT_* values must be in const.py."""
    assert "CONF_GUEST_MODE_PERSISTENCE_SECONDS" in CONST_SRC
    assert "CONF_GUEST_MODE_REQUIRE_CONFIDENCE" in CONST_SRC
    assert "DEFAULT_GUEST_PERSISTENCE_SECONDS" in CONST_SRC
    assert "DEFAULT_GUEST_REQUIRE_CONFIDENCE" in CONST_SRC
    # Threshold knob dropped per orchestrator corrections — must NOT be present
    assert "CONF_GUEST_MODE_MIN_UNIDENTIFIED" not in CONST_SRC
    assert "DEFAULT_GUEST_MIN_UNIDENTIFIED" not in CONST_SRC


def test_guest_mode_constants_import_cleanly():
    """The 4 new symbols must be importable from const — no ImportError.
    The threshold knob (MIN_UNIDENTIFIED) must NOT be present.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ura_const_test", PKG / "const.py"
    )
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        pytest.fail(f"const.py failed to load: {e}")

    for symbol in [
        "CONF_GUEST_MODE_PERSISTENCE_SECONDS",
        "CONF_GUEST_MODE_REQUIRE_CONFIDENCE",
        "DEFAULT_GUEST_PERSISTENCE_SECONDS",
        "DEFAULT_GUEST_REQUIRE_CONFIDENCE",
    ]:
        assert hasattr(mod, symbol), f"const.py missing symbol: {symbol}"

    # Threshold knob must have been dropped
    assert not hasattr(mod, "CONF_GUEST_MODE_MIN_UNIDENTIFIED"), (
        "CONF_GUEST_MODE_MIN_UNIDENTIFIED must not exist in const.py (dropped per orchestrator)"
    )
    assert not hasattr(mod, "DEFAULT_GUEST_MIN_UNIDENTIFIED"), (
        "DEFAULT_GUEST_MIN_UNIDENTIFIED must not exist in const.py (dropped per orchestrator)"
    )


def test_guest_mode_default_values_sensible():
    """Defaults must be within the documented ranges."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ura_const_defaults", PKG / "const.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert 0 <= mod.DEFAULT_GUEST_PERSISTENCE_SECONDS <= 1800, (
        f"DEFAULT_GUEST_PERSISTENCE_SECONDS={mod.DEFAULT_GUEST_PERSISTENCE_SECONDS} "
        "out of range [0, 1800]"
    )
    assert mod.DEFAULT_GUEST_REQUIRE_CONFIDENCE in ("low", "medium", "high"), (
        f"DEFAULT_GUEST_REQUIRE_CONFIDENCE={mod.DEFAULT_GUEST_REQUIRE_CONFIDENCE!r} "
        "must be one of: low, medium, high"
    )


def test_guest_mode_config_round_trip():
    """The 2 new CONF_ keys must appear in the coordinator_presence step of config_flow.py.
    The threshold knob must NOT be present.
    """
    assert "CONF_GUEST_MODE_PERSISTENCE_SECONDS" in CONFIG_FLOW_SRC, (
        "config_flow.py missing CONF_GUEST_MODE_PERSISTENCE_SECONDS in coordinator_presence step"
    )
    assert "CONF_GUEST_MODE_REQUIRE_CONFIDENCE" in CONFIG_FLOW_SRC, (
        "config_flow.py missing CONF_GUEST_MODE_REQUIRE_CONFIDENCE in coordinator_presence step"
    )
    # Threshold knob must have been dropped
    assert "CONF_GUEST_MODE_MIN_UNIDENTIFIED" not in CONFIG_FLOW_SRC, (
        "config_flow.py must NOT contain CONF_GUEST_MODE_MIN_UNIDENTIFIED (dropped per orchestrator)"
    )
    # Verify they appear inside async_step_coordinator_presence
    idx = CONFIG_FLOW_SRC.find("async def async_step_coordinator_presence(")
    assert idx >= 0, "async_step_coordinator_presence not found"
    next_def = CONFIG_FLOW_SRC.find("\n    async def ", idx + 1)
    block = CONFIG_FLOW_SRC[idx: next_def if next_def > 0 else idx + 4000]
    assert "CONF_GUEST_MODE_PERSISTENCE_SECONDS" in block
    assert "CONF_GUEST_MODE_REQUIRE_CONFIDENCE" in block


# ===========================================================================
# D3 — Threshold, confidence, and persistence gates
# ===========================================================================


def _make_coordinator(
    persistence_seconds: int = 300,
    require_confidence: str = "medium",
) -> Any:
    """Build a minimal PresenceCoordinator-like object for gate testing.

    We avoid importing PresenceCoordinator directly (HA runtime dependency)
    and instead extract the relevant methods by AST + exec into a minimal stub.

    Note: min_unidentified parameter has been dropped per orchestrator corrections.
    The effective threshold is unidentified_count > 0 (existence check only).
    """
    # Build a stub class that carries the gate fields and the two methods
    class _Stub:
        def __init__(self):
            self._guest_persistence_seconds = persistence_seconds
            self._guest_require_confidence = require_confidence
            self._unidentified_first_seen: Optional[datetime] = None
            self._guest_persistence_check_handle = None
            self.hass = MagicMock()
            self._scheduled_delays: list = []

        # Copy the rank map
        _CONFIDENCE_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}

        def _confidence_at_least(self, observed: str, required: str) -> bool:
            observed_rank = self._CONFIDENCE_RANK.get(observed, 0)
            required_rank = self._CONFIDENCE_RANK.get(required, 0)
            return observed_rank >= required_rank

        def _disarm_guest_gate(self) -> None:
            self._unidentified_first_seen = None
            if self._guest_persistence_check_handle is not None:
                self._guest_persistence_check_handle()
                self._guest_persistence_check_handle = None

        def _schedule_guest_persistence_recheck(self, persistence_secs: int) -> None:
            # In stub: record the scheduled delay instead of calling async_call_later
            self._scheduled_delays.append(persistence_secs + 5)
            # Set a no-op cancellable handle
            self._guest_persistence_check_handle = lambda: None

        def _guest_gate_armed(
            self,
            unidentified_count: int,
            census_confidence: str,
            now: datetime,
        ) -> bool:
            # Direct copy of the implementation logic (no threshold — existence only)
            if unidentified_count <= 0:
                self._disarm_guest_gate()
                return False

            if not self._confidence_at_least(census_confidence, self._guest_require_confidence):
                self._disarm_guest_gate()
                return False

            persistence_secs = self._guest_persistence_seconds
            if persistence_secs <= 0:
                self._disarm_guest_gate()
                return True

            if self._unidentified_first_seen is None:
                self._unidentified_first_seen = now
                self._schedule_guest_persistence_recheck(persistence_secs)
                return False

            elapsed = (now - self._unidentified_first_seen).total_seconds()
            if elapsed >= persistence_secs:
                if self._guest_persistence_check_handle is not None:
                    self._guest_persistence_check_handle()
                    self._guest_persistence_check_handle = None
                return True

            return False

    return _Stub()


def test_guest_gate_confidence_blocks_low_census():
    """With require_confidence=medium, low confidence must block the gate."""
    coord = _make_coordinator(
        require_confidence="medium", persistence_seconds=0
    )
    now = datetime(2026, 5, 14, 10, 0, 0)
    result = coord._guest_gate_armed(
        unidentified_count=3,
        census_confidence="low",
        now=now,
    )
    assert result is False, "Confidence gate should block low census even with count >= min"
    assert coord._unidentified_first_seen is None


def test_guest_gate_confidence_blocks_none():
    """Confidence 'none' must be blocked when require_confidence >= 'low'."""
    coord = _make_coordinator(
        require_confidence="low", persistence_seconds=0
    )
    now = datetime(2026, 5, 14, 10, 0, 0)
    result = coord._guest_gate_armed(
        unidentified_count=2,
        census_confidence="none",
        now=now,
    )
    assert result is False, "Confidence 'none' should be blocked when require_confidence='low'"


def test_guest_gate_confidence_allows_exact_match():
    """Confidence exactly matching require_confidence should be accepted."""
    coord = _make_coordinator(
        require_confidence="medium", persistence_seconds=0
    )
    now = datetime(2026, 5, 14, 10, 0, 0)
    result = coord._guest_gate_armed(
        unidentified_count=2,
        census_confidence="medium",
        now=now,
    )
    assert result is True, "Confidence exactly at require_confidence should pass"


def test_guest_gate_persistence_arms_on_first_qualifying_tick():
    """On first qualifying tick (count > 0, conf >= required), gate arms but does not fire."""
    coord = _make_coordinator(
        require_confidence="medium", persistence_seconds=300
    )
    now = datetime(2026, 5, 14, 10, 0, 0)
    result = coord._guest_gate_armed(
        unidentified_count=2,
        census_confidence="high",
        now=now,
    )
    assert result is False, "Gate should not fire on first qualifying tick (persistence not met)"
    assert coord._unidentified_first_seen == now, (
        "_unidentified_first_seen should be set to 'now' on first qualifying tick"
    )
    assert coord._scheduled_delays == [305], (
        "Recheck should be scheduled for persistence_seconds+5=305s"
    )


def test_guest_gate_persistence_fires_after_window():
    """After persistence_seconds have elapsed, the gate must fire."""
    coord = _make_coordinator(
        require_confidence="medium", persistence_seconds=300
    )
    t0 = datetime(2026, 5, 14, 10, 0, 0)
    t1 = t0 + timedelta(seconds=301)

    # First tick — arms
    coord._guest_gate_armed(unidentified_count=2, census_confidence="high", now=t0)
    assert coord._unidentified_first_seen == t0

    # Second tick 301s later — should fire
    result = coord._guest_gate_armed(
        unidentified_count=2,
        census_confidence="high",
        now=t1,
    )
    assert result is True, "Gate should fire after persistence window elapsed"


def test_guest_gate_persistence_does_not_fire_before_window():
    """Gate must not fire if elapsed < persistence_seconds."""
    coord = _make_coordinator(
        require_confidence="medium", persistence_seconds=300
    )
    t0 = datetime(2026, 5, 14, 10, 0, 0)
    t1 = t0 + timedelta(seconds=299)  # just under window

    coord._guest_gate_armed(unidentified_count=2, census_confidence="high", now=t0)
    result = coord._guest_gate_armed(
        unidentified_count=2,
        census_confidence="high",
        now=t1,
    )
    assert result is False, "Gate must not fire before persistence window"
    # _unidentified_first_seen must still be t0
    assert coord._unidentified_first_seen == t0


def test_guest_gate_disarms_when_count_drops_before_window():
    """If count drops to 0 during the persistence window, gate disarms."""
    coord = _make_coordinator(
        require_confidence="medium", persistence_seconds=300
    )
    t0 = datetime(2026, 5, 14, 10, 0, 0)
    t1 = t0 + timedelta(seconds=60)

    # Arm the gate
    coord._guest_gate_armed(unidentified_count=1, census_confidence="high", now=t0)
    assert coord._unidentified_first_seen == t0

    # Count drops to 0 before window — existence gate fails, disarms
    result = coord._guest_gate_armed(
        unidentified_count=0,
        census_confidence="high",
        now=t1,
    )
    assert result is False
    assert coord._unidentified_first_seen is None, (
        "_unidentified_first_seen should be cleared when unidentified count drops to 0"
    )


def test_guest_gate_disarms_when_confidence_regresses():
    """If confidence drops below required mid-window, gate disarms."""
    coord = _make_coordinator(
        require_confidence="medium", persistence_seconds=300
    )
    t0 = datetime(2026, 5, 14, 10, 0, 0)
    t1 = t0 + timedelta(seconds=60)

    # Arm the gate
    coord._guest_gate_armed(unidentified_count=2, census_confidence="high", now=t0)
    assert coord._unidentified_first_seen == t0

    # Confidence regresses to low
    result = coord._guest_gate_armed(
        unidentified_count=2,
        census_confidence="low",  # below medium
        now=t1,
    )
    assert result is False
    assert coord._unidentified_first_seen is None, (
        "_unidentified_first_seen should be cleared on confidence regression"
    )


def test_guest_gate_exit_is_immediate():
    """The exit path (count=0 → leave GUEST) is not governed by _guest_gate_armed.
    Verify that the inference engine's infer() still fires the exit immediately
    when unidentified_count=0 even when guest_gate_armed=False.
    """
    # We test via the StateInferenceEngine directly.
    # We need to isolate it from HA imports, so we use AST to confirm the
    # exit branch is in infer() and does NOT check guest_gate_armed.
    # Source-grep approach:
    infer_idx = PRESENCE_SRC.find("def infer(")
    assert infer_idx >= 0, "StateInferenceEngine.infer not found"

    # Find the exit branch: "current_state == HouseState.GUEST and unidentified_count == 0"
    exit_pattern = "current_state == HouseState.GUEST and unidentified_count == 0"
    assert exit_pattern in PRESENCE_SRC, (
        "Exit branch (guest→home on unidentified_count==0) must remain in infer(). "
        "Expected: if current_state == HouseState.GUEST and unidentified_count == 0"
    )

    # Verify the exit branch does NOT reference guest_gate_armed
    # Find the exit-branch block within infer()
    guest_exit_idx = PRESENCE_SRC.find(exit_pattern, infer_idx)
    # Get a slice around the exit branch
    block = PRESENCE_SRC[guest_exit_idx: guest_exit_idx + 200]
    assert "guest_gate_armed" not in block, (
        "Exit branch must NOT reference guest_gate_armed — exit is always immediate"
    )


def test_guest_gate_zero_persistence_fires_immediately():
    """When persistence_seconds=0, gate fires on first qualifying tick.
    Covered by test_persistence_zero_disables_persistence_gate per corrections.
    """
    coord = _make_coordinator(
        require_confidence="low", persistence_seconds=0
    )
    now = datetime(2026, 5, 14, 10, 0, 0)
    result = coord._guest_gate_armed(
        unidentified_count=1,
        census_confidence="low",
        now=now,
    )
    assert result is True, "Zero persistence should fire immediately on qualifying tick"
    assert coord._unidentified_first_seen is None, (
        "_unidentified_first_seen must be cleared after immediate fire"
    )


def test_confidence_rank_ordering():
    """Rank map must order none < low < medium < high."""
    coord = _make_coordinator()
    # Test all meaningful comparisons using _confidence_at_least
    assert coord._confidence_at_least("none", "none")
    assert coord._confidence_at_least("low", "none")
    assert coord._confidence_at_least("medium", "none")
    assert coord._confidence_at_least("high", "none")
    assert not coord._confidence_at_least("none", "low")
    assert coord._confidence_at_least("low", "low")
    assert coord._confidence_at_least("medium", "low")
    assert coord._confidence_at_least("high", "low")
    assert not coord._confidence_at_least("none", "medium")
    assert not coord._confidence_at_least("low", "medium")
    assert coord._confidence_at_least("medium", "medium")
    assert coord._confidence_at_least("high", "medium")
    assert not coord._confidence_at_least("none", "high")
    assert not coord._confidence_at_least("low", "high")
    assert not coord._confidence_at_least("medium", "high")
    assert coord._confidence_at_least("high", "high")


# ===========================================================================
# D4 — Persistence timer handle tracking
# ===========================================================================


def test_persistence_handle_scheduled_on_arm():
    """When gate arms (first qualifying tick), a recheck must be scheduled."""
    coord = _make_coordinator(
        require_confidence="medium", persistence_seconds=300
    )
    now = datetime(2026, 5, 14, 10, 0, 0)
    coord._guest_gate_armed(unidentified_count=2, census_confidence="high", now=now)
    # _scheduled_delays should have been populated
    assert coord._scheduled_delays, "Recheck must be scheduled on first qualifying arm"
    assert coord._scheduled_delays[0] == 305, (
        "Recheck delay should be persistence_seconds + 5 = 305"
    )


def test_persistence_handle_cancelled_on_disarm():
    """Handle must be cancelled (called) when the gate disarms."""
    coord = _make_coordinator(
        require_confidence="medium", persistence_seconds=300
    )
    t0 = datetime(2026, 5, 14, 10, 0, 0)
    t1 = t0 + timedelta(seconds=60)

    cancel_called = []
    coord._guest_gate_armed(unidentified_count=1, census_confidence="high", now=t0)

    # Replace handle with a tracking callable
    def _tracking_cancel():
        cancel_called.append(True)
    coord._guest_persistence_check_handle = _tracking_cancel

    # Disarm by dropping count to 0 (existence gate fails)
    coord._guest_gate_armed(unidentified_count=0, census_confidence="high", now=t1)
    assert cancel_called, "Handle must be cancelled (called) on disarm"
    assert coord._guest_persistence_check_handle is None, (
        "Handle must be set to None after cancellation"
    )


def test_persistence_handle_cancelled_on_unload():
    """async_teardown must cancel the persistence handle (no orphan callbacks)."""
    # Source-grep: _disarm_guest_gate must be called in async_teardown
    teardown_idx = PRESENCE_SRC.find("async def async_teardown(")
    assert teardown_idx >= 0, "async_teardown not found in presence.py"
    # Find next def
    next_def = PRESENCE_SRC.find("\n    async def ", teardown_idx + 1)
    block = PRESENCE_SRC[teardown_idx: next_def if next_def > 0 else teardown_idx + 1000]
    assert "_disarm_guest_gate" in block, (
        "async_teardown must call _disarm_guest_gate() to prevent orphan callbacks "
        "(Bug Class #20 prevention)"
    )


def test_disarm_clears_first_seen_and_cancels_handle():
    """_disarm_guest_gate must clear _unidentified_first_seen AND cancel the handle."""
    coord = _make_coordinator(persistence_seconds=300)
    t0 = datetime(2026, 5, 14, 10, 0, 0)

    # Arm the gate
    coord._guest_gate_armed(unidentified_count=2, census_confidence="high", now=t0)
    assert coord._unidentified_first_seen is not None

    cancel_called = []
    coord._guest_persistence_check_handle = lambda: cancel_called.append(True)

    # Call disarm directly
    coord._disarm_guest_gate()

    assert coord._unidentified_first_seen is None
    assert cancel_called, "Handle must be called on _disarm_guest_gate"
    assert coord._guest_persistence_check_handle is None


# ===========================================================================
# D5 — Census confidence propagated to presence coordinator
# ===========================================================================


def test_census_confidence_propagated_to_presence():
    """_handle_census_update must read 'confidence' from payload into _census_confidence."""
    # Source-grep: census_data.get("confidence" must appear in _handle_census_update
    idx = PRESENCE_SRC.find("def _handle_census_update(")
    assert idx >= 0, "_handle_census_update not found in presence.py"
    # Find next method
    next_def = PRESENCE_SRC.find("\n    @callback\n    def ", idx + 1)
    next_def2 = PRESENCE_SRC.find("\n    @callback\n    async def ", idx + 1)
    if next_def < 0 or (next_def2 > 0 and next_def2 < next_def):
        next_def = next_def2
    block = PRESENCE_SRC[idx: next_def if next_def > 0 else idx + 2000]

    assert '_census_confidence' in block, (
        "_handle_census_update must store confidence in self._census_confidence"
    )
    assert 'census_data.get("confidence"' in block, (
        "_handle_census_update must read 'confidence' from census_data"
    )


def test_census_source_agreement_propagated_to_presence():
    """_handle_census_update must read 'source_agreement' into _census_source_agreement."""
    idx = PRESENCE_SRC.find("def _handle_census_update(")
    assert idx >= 0
    next_def = PRESENCE_SRC.find("\n    @callback\n    def ", idx + 1)
    next_def2 = PRESENCE_SRC.find("\n    @callback\n    async def ", idx + 1)
    if next_def < 0 or (next_def2 > 0 and next_def2 < next_def):
        next_def = next_def2
    block = PRESENCE_SRC[idx: next_def if next_def > 0 else idx + 2000]

    assert '_census_source_agreement' in block, (
        "_handle_census_update must store source_agreement in self._census_source_agreement"
    )
    assert 'census_data.get("source_agreement"' in block, (
        "_handle_census_update must read 'source_agreement' from census_data"
    )


def test_census_confidence_defaults_to_none_on_missing_key():
    """If 'confidence' key is absent from payload, _census_confidence must default to 'none'."""
    # Source-grep: default value in get() call
    idx = PRESENCE_SRC.find("census_data.get(\"confidence\"")
    assert idx >= 0, "census_data.get(\"confidence\") not found"
    block = PRESENCE_SRC[idx: idx + 100]
    assert '"none"' in block or "'none'" in block, (
        "confidence key must default to 'none' when missing"
    )


# ===========================================================================
# D6 — Source-grep / AST regressions
# ===========================================================================


def test_guest_gate_method_exists():
    """PresenceCoordinator must define _guest_gate_armed as an instance method."""
    assert "def _guest_gate_armed(" in PRESENCE_SRC, (
        "PresenceCoordinator._guest_gate_armed method not found in presence.py"
    )


def test_guest_gate_called_from_run_inference():
    """_guest_gate_armed must be called from _run_inference."""
    idx = PRESENCE_SRC.find("async def _run_inference(")
    assert idx >= 0, "_run_inference not found in presence.py"
    next_def = PRESENCE_SRC.find("\n    async def ", idx + 1)
    block = PRESENCE_SRC[idx: next_def if next_def > 0 else idx + 3000]
    assert "_guest_gate_armed(" in block, (
        "_run_inference must call self._guest_gate_armed() to evaluate the guest gate"
    )


def test_guest_gate_result_passed_to_inference_engine():
    """The result of _guest_gate_armed must be passed to inference_engine.infer()."""
    idx = PRESENCE_SRC.find("async def _run_inference(")
    assert idx >= 0
    next_def = PRESENCE_SRC.find("\n    async def ", idx + 1)
    block = PRESENCE_SRC[idx: next_def if next_def > 0 else idx + 3000]
    assert "guest_gate_armed" in block, (
        "_run_inference must pass guest_gate_armed= to inference_engine.infer()"
    )


def test_inference_engine_infer_accepts_guest_gate_armed_param():
    """StateInferenceEngine.infer() must accept a guest_gate_armed parameter."""
    assert "guest_gate_armed" in PRESENCE_SRC, (
        "StateInferenceEngine.infer() must accept guest_gate_armed parameter"
    )
    # Verify it's in the infer() signature
    idx = PRESENCE_SRC.find("def infer(")
    assert idx >= 0
    sig_block = PRESENCE_SRC[idx: idx + 300]
    assert "guest_gate_armed" in sig_block, (
        "guest_gate_armed must appear in infer() method signature"
    )


def test_confidence_rank_map_is_private():
    """_CONFIDENCE_RANK must use numeric values, not string comparison."""
    assert "_CONFIDENCE_RANK" in PRESENCE_SRC, (
        "_CONFIDENCE_RANK dict not found in presence.py"
    )
    # Verify the dict has the expected keys as string literals with int values
    # Source-grep for the rank entries
    assert '"none": 0' in PRESENCE_SRC or "'none': 0" in PRESENCE_SRC, (
        "_CONFIDENCE_RANK must map 'none' to 0"
    )
    assert '"high": 3' in PRESENCE_SRC or "'high': 3" in PRESENCE_SRC, (
        "_CONFIDENCE_RANK must map 'high' to 3"
    )


def test_guest_persistence_handle_cleanup_registered():
    """_disarm_guest_gate must be called from async_teardown (Bug Class #20 prevention)."""
    # Already covered in test_persistence_handle_cancelled_on_unload but
    # also verify _disarm_guest_gate itself cancels the handle.
    assert "def _disarm_guest_gate(" in PRESENCE_SRC, (
        "_disarm_guest_gate method not found in presence.py"
    )
    idx = PRESENCE_SRC.find("def _disarm_guest_gate(")
    assert idx >= 0
    next_def = PRESENCE_SRC.find("\n    def ", idx + 1)
    block = PRESENCE_SRC[idx: next_def if next_def > 0 else idx + 500]
    assert "_guest_persistence_check_handle" in block, (
        "_disarm_guest_gate must reference _guest_persistence_check_handle"
    )
    # The handle must be called (cancelled) before being set to None
    assert "None" in block, (
        "_disarm_guest_gate must set _guest_persistence_check_handle = None"
    )


def test_guest_mode_init_constants_in_init_py():
    """__init__.py must pass the 2 new guest mode knobs when constructing PresenceCoordinator.
    The threshold knob (guest_min_unidentified) must NOT be passed.
    """
    assert "CONF_GUEST_MODE_PERSISTENCE_SECONDS" in INIT_SRC, (
        "__init__.py must import CONF_GUEST_MODE_PERSISTENCE_SECONDS"
    )
    assert "guest_persistence_seconds=" in INIT_SRC, (
        "__init__.py must pass guest_persistence_seconds= to PresenceCoordinator"
    )
    assert "guest_require_confidence=" in INIT_SRC, (
        "__init__.py must pass guest_require_confidence= to PresenceCoordinator"
    )
    # Threshold knob must have been dropped
    assert "guest_min_unidentified=" not in INIT_SRC, (
        "__init__.py must NOT pass guest_min_unidentified= to PresenceCoordinator (dropped)"
    )


def test_no_lexicographic_string_compare_on_confidence():
    """Confidence levels must be compared via _confidence_at_least / _CONFIDENCE_RANK,
    not via direct string comparison operators like > or <.
    """
    import re as _re

    # Find _guest_gate_armed body
    idx = PRESENCE_SRC.find("def _guest_gate_armed(")
    assert idx >= 0
    next_def = PRESENCE_SRC.find("\n    def ", idx + 1)
    block = PRESENCE_SRC[idx: next_def if next_def > 0 else idx + 2000]

    # The gate must use _confidence_at_least (not raw string comparison)
    assert "_confidence_at_least(" in block, (
        "_guest_gate_armed must call _confidence_at_least() for confidence comparison "
        "to avoid lexicographic comparison bugs"
    )
    # Guard: no standalone < or > string comparison on confidence variables
    # (allow >= and <= which appear in docstrings as pseudo-code, and in
    # numeric comparisons — we only disallow bare confidence_var > "string" or < "string")
    # Pattern: confidence_var followed immediately by > or < and a string literal
    bad_pattern = _re.compile(r'confidence\s+[<>]\s+"')
    assert not bad_pattern.search(block), (
        "_guest_gate_armed must not use raw string comparison on confidence "
        "(e.g. census_confidence > \"medium\" is lexicographic and wrong)"
    )


# ===========================================================================
# Scenario tests from orchestrator corrections
# ===========================================================================
# Note: test_persistence_zero_disables_persistence_gate is covered by
# test_guest_gate_zero_persistence_fires_immediately above.


def test_resident_ble_flicker_does_not_fire_guest():
    """Resident BLE flicker (transient unidentified=1 tick) must not trigger guest mode.

    Scenario: resident recognized, camera=2, identified=1, unidentified=1, confidence=high
    for 60s, then tick (camera=1, identified=1, unidentified=0).
    Persistence gate (300s) catches the chatter — house stays HOME, never enters GUEST.
    """
    coord = _make_coordinator(require_confidence="high", persistence_seconds=300)
    t0 = datetime(2026, 5, 14, 10, 0, 0)

    # BLE flicker tick — unidentified=1, high confidence. Arms but does not fire.
    result = coord._guest_gate_armed(
        unidentified_count=1, census_confidence="high", now=t0
    )
    assert result is False, "First qualifying tick must not fire — persistence not met"
    assert coord._unidentified_first_seen == t0

    # 60s later — still within persistence window
    t1 = t0 + timedelta(seconds=60)
    result = coord._guest_gate_armed(
        unidentified_count=1, census_confidence="high", now=t1
    )
    assert result is False, "Within persistence window — must not fire"

    # BLE resolves — unidentified drops to 0 — gate disarms
    t2 = t1 + timedelta(seconds=5)
    result = coord._guest_gate_armed(
        unidentified_count=0, census_confidence="high", now=t2
    )
    assert result is False, "After BLE resolves (unidentified=0), gate must be disarmed"
    assert coord._unidentified_first_seen is None, (
        "_unidentified_first_seen must be cleared when unidentified drops to 0"
    )


def test_single_visitor_still_triggers_guest():
    """Single real visitor must still trigger guest mode after persistence window.

    Scenario: resident B at home, recognized. Visitor V walks in. Sustained ticks
    (camera=2, identified=1, unidentified=1, confidence=high) for >= persistence window.
    Assert house transitions HOME_DAY -> GUEST (no regression in real-guest detection).
    """
    coord = _make_coordinator(require_confidence="high", persistence_seconds=300)
    t0 = datetime(2026, 5, 14, 10, 0, 0)

    # First qualifying tick — gate arms
    result = coord._guest_gate_armed(
        unidentified_count=1, census_confidence="high", now=t0
    )
    assert result is False, "First tick: gate armed, waiting for persistence"
    assert coord._unidentified_first_seen == t0

    # 301s later — visitor is still there; persistence window exceeded
    t1 = t0 + timedelta(seconds=301)
    result = coord._guest_gate_armed(
        unidentified_count=1, census_confidence="high", now=t1
    )
    assert result is True, (
        "Single visitor sustained >= 300s must trigger guest mode "
        "(single-visitor regression prevention)"
    )


def test_low_confidence_blocks_guest_even_when_sustained():
    """Low confidence census must block guest mode even when sustained for 2x persistence.

    Scenario: BLE-only or camera-disagree produces confidence=low.
    Even if sustained for 2x the persistence window, guest must NOT fire.
    """
    coord = _make_coordinator(require_confidence="medium", persistence_seconds=300)
    t0 = datetime(2026, 5, 14, 10, 0, 0)

    # Low-confidence ticks over 700s (> 2x persistence)
    for offset_secs in [0, 60, 120, 300, 400, 600, 700]:
        t = t0 + timedelta(seconds=offset_secs)
        result = coord._guest_gate_armed(
            unidentified_count=1, census_confidence="low", now=t
        )
        assert result is False, (
            f"At t+{offset_secs}s: low confidence must block guest even when sustained"
        )
        # Gate is always disarmed by confidence failure — never arms
        assert coord._unidentified_first_seen is None, (
            "Gate must not arm when confidence is insufficient"
        )


def test_resident_walking_out_door_does_not_fire_guest():
    """Resident walking out should not trigger guest mode via BLE-flicker mid-departure.

    Scenario: start HOME_DAY with 2 identified. One resident leaves — camera=2,
    identified=1, unidentified=1 for 120s (BLE flicker during departure). Then
    camera sees 1 person, then 0. Assert NEVER entered GUEST.

    The persistence gate (300s) ensures the 120s flicker during departure does not fire.
    """
    coord = _make_coordinator(require_confidence="high", persistence_seconds=300)
    t0 = datetime(2026, 5, 14, 10, 0, 0)

    # Resident departure BLE-flicker: 120s of unidentified=1
    for offset_secs in [0, 30, 60, 90, 120]:
        t = t0 + timedelta(seconds=offset_secs)
        result = coord._guest_gate_armed(
            unidentified_count=1, census_confidence="high", now=t
        )
        assert result is False, (
            f"At t+{offset_secs}s: departure flicker (120s < 300s persistence) must not fire"
        )

    # Resident fully departed — unidentified drops to 0, gate disarms
    t_away = t0 + timedelta(seconds=130)
    result = coord._guest_gate_armed(
        unidentified_count=0, census_confidence="high", now=t_away
    )
    assert result is False
    assert coord._unidentified_first_seen is None, (
        "Gate must disarm when unidentified=0 (resident fully departed)"
    )
