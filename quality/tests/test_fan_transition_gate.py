"""Fan-transition coincidence gate (AUDIT probe 2026-08-01) — acceptance tests.

Basis: `docs/planning/AUDIT_fan_signature_separability_probe.md` — the
GO/NO-GO §d verdict. mmWave phantom-occupancy onsets align to the exact
second of a fan power/speed transition; steady-state fan runtime never
triggers a phantom. This gate suppresses mmwave-sole occupancy CREATION
within ``FAN_TRANSITION_SUSPECT_WINDOW_S`` of a fan transition on the
room's configured CONF_FANS entity.

Test authority (Bug Class #62): the gate block is extracted verbatim
from ``coordinator.py`` between the two mutation-anchor delimiters and
exec'd against a minimal fake ``self``. Every test drives PRODUCTION
SOURCE TEXT — mutating the gate region or the window comparison
propagates directly into these tests. The stamping side is exercised
by direct-import tests against ``PresenceCoordinator._handle_fan_change``.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401 — mocks homeassistant
from _provenance_harness import make_hass

from custom_components.universal_room_automation.const import (
    DOMAIN,
    FAN_TRANSITION_SUSPECT_WINDOW_S,
    STATE_OCCUPIED,
)


_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parent.parent.parent
_COORD_SRC = (
    _REPO_ROOT
    / "custom_components"
    / "universal_room_automation"
    / "coordinator.py"
)

_BLOCK_START = "        # === Fan-transition coincidence gate — CREATION suppressor ==="
_BLOCK_END = "        # === Fan-transition coincidence gate — END ==="


def _extract_gate_block_source() -> str:
    src = _COORD_SRC.read_text(encoding="utf-8")
    assert _BLOCK_START in src, (
        "Fan-transition gate START delimiter missing from coordinator.py — "
        "the gate site was removed/renamed (mutation anchor)"
    )
    assert _BLOCK_END in src, (
        "Fan-transition gate END delimiter missing from coordinator.py"
    )
    i = src.index(_BLOCK_START)
    j = src.index(_BLOCK_END, i)
    block = src[i:j]
    lines = block.splitlines()
    dedented = []
    for ln in lines:
        if ln.startswith("        "):
            dedented.append(ln[8:])
        elif ln.strip() == "":
            dedented.append("")
        else:
            dedented.append(ln)
    return "\n".join(dedented)


_GATE_SRC = _extract_gate_block_source()
_GATE_CODE = compile(_GATE_SRC, str(_COORD_SRC), "exec")


class _FakeSelf:
    """Minimal fake for the attributes the gate block reads / writes."""

    def __init__(self, hass, last_occupied_state: bool = False):
        self.hass = hass
        self._last_occupied_state = last_occupied_state
        self._fan_transition_suppressed_count = 0


def _seed_presence(hass, *, last_transition: datetime | None):
    """Seed a presence coordinator that returns last_transition for any room."""
    presence = MagicMock()
    presence.get_fan_last_transition = MagicMock(return_value=last_transition)
    manager = MagicMock()
    manager.coordinators = {"presence": presence}
    hass.data[DOMAIN] = {"coordinator_manager": manager}
    return presence


def _run_gate(
    self_obj: _FakeSelf,
    now: datetime,
    room_name: str,
    *,
    any_sensor_active: bool,
    motion_detected: bool,
    presence_detected: bool,
    occupancy_detected: bool,
    window_override: float | None = None,
) -> dict:
    ns = {
        "self": self_obj,
        "now": now,
        "room_name": room_name,
        "any_sensor_active": any_sensor_active,
        "motion_detected": motion_detected,
        "presence_detected": presence_detected,
        "occupancy_detected": occupancy_detected,
        "DOMAIN": DOMAIN,
        "FAN_TRANSITION_SUSPECT_WINDOW_S": (
            window_override if window_override is not None
            else FAN_TRANSITION_SUSPECT_WINDOW_S
        ),
        "_LOGGER": logging.getLogger("fan_transition_gate_test"),
    }
    exec(_GATE_CODE, ns)
    return ns


# --------------------------------------------------------------------------
# T1 — constant is present + kill-switch semantics documented
# --------------------------------------------------------------------------


def test_fan_transition_window_constant_present():
    # Default > 0 — feature live at boot.
    assert float(FAN_TRANSITION_SUSPECT_WINDOW_S) > 0
    # Sanity: default is the ~5s AUDIT §d window.
    assert 1.0 <= float(FAN_TRANSITION_SUSPECT_WINDOW_S) <= 30.0


# --------------------------------------------------------------------------
# T2 — Study A incident replay: fan transition at T, mmwave rising edge
# at T+2s -> occupancy NOT created, counter increments.
# --------------------------------------------------------------------------


def test_incident_replay_mmwave_sole_within_window_suppressed():
    hass = make_hass()
    room = "Study A"
    fan_t = datetime(2026, 7, 31, 20, 41, 16, tzinfo=timezone.utc)
    now = fan_t + timedelta(seconds=2)
    coord = _FakeSelf(hass, last_occupied_state=False)
    _seed_presence(hass, last_transition=fan_t)

    ns = _run_gate(
        coord, now, room,
        any_sensor_active=True,
        motion_detected=False,
        presence_detected=True,
        occupancy_detected=False,
    )
    assert ns["any_sensor_active"] is False, (
        "mmwave-sole creation within window was NOT suppressed — "
        "gate leak (AUDIT §d)"
    )
    assert coord._fan_transition_suppressed_count == 1


# --------------------------------------------------------------------------
# T3 — Outside window (T+8s > 5s) -> occupancy created normally.
# --------------------------------------------------------------------------


def test_outside_window_admits_normally():
    hass = make_hass()
    room = "Study A"
    fan_t = datetime(2026, 7, 31, 20, 41, 16, tzinfo=timezone.utc)
    now = fan_t + timedelta(seconds=8)
    coord = _FakeSelf(hass, last_occupied_state=False)
    _seed_presence(hass, last_transition=fan_t)

    ns = _run_gate(
        coord, now, room,
        any_sensor_active=True,
        motion_detected=False,
        presence_detected=True,
        occupancy_detected=False,
    )
    assert ns["any_sensor_active"] is True, (
        "Creation outside window was suppressed — false positive"
    )
    assert coord._fan_transition_suppressed_count == 0


# --------------------------------------------------------------------------
# T4 — PIR corroboration within window -> creation admits (only
# mmwave-sole path is gated).
# --------------------------------------------------------------------------


def test_pir_within_window_admits_only_mmwave_sole_gated():
    hass = make_hass()
    room = "Study A"
    fan_t = datetime(2026, 7, 31, 20, 41, 16, tzinfo=timezone.utc)
    now = fan_t + timedelta(seconds=2)
    coord = _FakeSelf(hass, last_occupied_state=False)
    _seed_presence(hass, last_transition=fan_t)

    ns = _run_gate(
        coord, now, room,
        any_sensor_active=True,
        motion_detected=True,      # PIR co-fire
        presence_detected=True,
        occupancy_detected=False,
    )
    assert ns["any_sensor_active"] is True, (
        "PIR + mmwave co-fire was gated — over-suppression"
    )
    assert coord._fan_transition_suppressed_count == 0


# --------------------------------------------------------------------------
# T5 — Kill switch (window = 0) -> pre-change behavior (never suppress).
# --------------------------------------------------------------------------


def test_kill_switch_zero_window_never_suppresses():
    hass = make_hass()
    room = "Study A"
    fan_t = datetime(2026, 7, 31, 20, 41, 16, tzinfo=timezone.utc)
    now = fan_t + timedelta(seconds=1)
    coord = _FakeSelf(hass, last_occupied_state=False)
    _seed_presence(hass, last_transition=fan_t)

    ns = _run_gate(
        coord, now, room,
        any_sensor_active=True,
        motion_detected=False,
        presence_detected=True,
        occupancy_detected=False,
        window_override=0.0,
    )
    assert ns["any_sensor_active"] is True
    assert coord._fan_transition_suppressed_count == 0


# --------------------------------------------------------------------------
# T6 — Existing occupancy + fan transition -> NOT released (creation-only).
# --------------------------------------------------------------------------


def test_existing_occupancy_not_released_by_gate():
    hass = make_hass()
    room = "Study A"
    fan_t = datetime(2026, 7, 31, 20, 41, 16, tzinfo=timezone.utc)
    now = fan_t + timedelta(seconds=1)
    coord = _FakeSelf(hass, last_occupied_state=True)  # already occupied
    _seed_presence(hass, last_transition=fan_t)

    ns = _run_gate(
        coord, now, room,
        any_sensor_active=True,
        motion_detected=False,
        presence_detected=True,
        occupancy_detected=False,
    )
    assert ns["any_sensor_active"] is True, (
        "Gate released an existing occupancy hold — sustain violation"
    )
    assert coord._fan_transition_suppressed_count == 0


# --------------------------------------------------------------------------
# T7 — No fan transition observed for the room -> admits normally.
# --------------------------------------------------------------------------


def test_no_fan_transition_admits_normally():
    hass = make_hass()
    room = "Study A"
    now = datetime(2026, 7, 31, 20, 41, 16, tzinfo=timezone.utc)
    coord = _FakeSelf(hass, last_occupied_state=False)
    _seed_presence(hass, last_transition=None)

    ns = _run_gate(
        coord, now, room,
        any_sensor_active=True,
        motion_detected=False,
        presence_detected=True,
        occupancy_detected=False,
    )
    assert ns["any_sensor_active"] is True
    assert coord._fan_transition_suppressed_count == 0


# --------------------------------------------------------------------------
# T8 — Stamping side: _handle_fan_change on state EDGE stamps
# _fan_last_transition (on/off).
# --------------------------------------------------------------------------


def test_handle_fan_change_state_edge_stamps_transition():
    from custom_components.universal_room_automation.domain_coordinators import (  # noqa: PLC0415, E501
        presence as presence_mod,
    )
    room = "Study A"
    fan_a = "fan.studya"
    hass = make_hass()

    class _S:
        def __init__(self, state, attrs=None):
            self.state = state
            self.attributes = attrs or {}

    hass.states.get = lambda eid: None  # type: ignore[assignment]

    class _Tracker:
        def __init__(self):
            self.room_names = {room}
            self._fan_on_rooms = set()
            self._fan_on_since = {}
            self._fan_last_transition = {}
            self._fan_entity_to_room = {fan_a: room}

    tracker = _Tracker()

    class _P:
        _zone_trackers = {"z": tracker}
        hass = None
    p = _P()
    p.hass = hass

    class _Ev:
        data = {
            "entity_id": fan_a,
            "old_state": _S("off"),
            "new_state": _S("on", {"percentage": 33}),
        }
    presence_mod.PresenceCoordinator._handle_fan_change(p, _Ev())

    assert room in tracker._fan_last_transition, (
        "State edge did NOT stamp _fan_last_transition"
    )


# --------------------------------------------------------------------------
# T9 — Stamping side: percentage-only attribute change (state unchanged)
# also stamps the transition. This is the Study A incident: fan already
# ON at 33%, speed-step to 55% at 20:41:17 triggers the phantom.
# --------------------------------------------------------------------------


def test_handle_fan_change_percentage_only_change_stamps_transition():
    from custom_components.universal_room_automation.domain_coordinators import (  # noqa: PLC0415, E501
        presence as presence_mod,
    )
    room = "Study A"
    fan_a = "fan.studya"
    hass = make_hass()

    class _S:
        def __init__(self, state, attrs=None):
            self.state = state
            self.attributes = attrs or {}

    hass.states.get = lambda eid: _S("on", {"percentage": 55})  # type: ignore[assignment]

    class _Tracker:
        def __init__(self):
            self.room_names = {room}
            # Already on with a prior stamp — this must be OVERWRITTEN.
            self._fan_on_rooms = {room}
            self._fan_on_since = {
                room: datetime(2026, 7, 31, 0, 31, 0, tzinfo=timezone.utc),
            }
            self._fan_last_transition = {
                room: datetime(2026, 7, 31, 0, 31, 0, tzinfo=timezone.utc),
            }
            self._fan_entity_to_room = {fan_a: room}

    tracker = _Tracker()

    class _P:
        _zone_trackers = {"z": tracker}
        hass = None
    p = _P()
    p.hass = hass

    old_stamp = tracker._fan_last_transition[room]

    class _Ev:
        data = {
            "entity_id": fan_a,
            "old_state": _S("on", {"percentage": 33}),
            "new_state": _S("on", {"percentage": 55}),
        }
    presence_mod.PresenceCoordinator._handle_fan_change(p, _Ev())

    new_stamp = tracker._fan_last_transition[room]
    assert new_stamp is not old_stamp and new_stamp != old_stamp, (
        "Percentage-only change did NOT stamp _fan_last_transition — "
        "Study A incident cannot be detected"
    )


# --------------------------------------------------------------------------
# T10 — get_fan_last_transition returns None for unknown room.
# --------------------------------------------------------------------------


def test_get_fan_last_transition_unknown_room_returns_none():
    from custom_components.universal_room_automation.domain_coordinators import (  # noqa: PLC0415, E501
        presence as presence_mod,
    )

    class _Tracker:
        _fan_last_transition: dict = {}
    tracker = _Tracker()

    class _P:
        _zone_trackers = {"z": tracker}
    p = _P()

    got = presence_mod.PresenceCoordinator.get_fan_last_transition(
        p, "Nowhere",
    )
    assert got is None


# --------------------------------------------------------------------------
# T11 — Mutation drill on the gate predicate: neuter the suppression
# assignment (`any_sensor_active = False`) in production source, confirm
# the incident-replay test FAILS, then restore.
#
# Per mutation-verify pyc-staleness feedback: PYTHONDONTWRITEBYTECODE=1
# + explicit __pycache__ purge to avoid false-PASS from stale bytecode.
# --------------------------------------------------------------------------


def _run_pytest_in_subprocess(test_id: str, expect_fail: bool) -> str:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = "quality"
    repo_root = _REPO_ROOT
    # Purge any stale bytecode for the coordinator module.
    for cache in repo_root.rglob("__pycache__"):
        try:
            shutil.rmtree(cache)
        except Exception:
            pass
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_id, "-x", "-q"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if expect_fail:
        assert result.returncode != 0, (
            f"Expected FAIL but pytest returned 0.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    else:
        assert result.returncode == 0, (
            f"Expected PASS but pytest returned {result.returncode}.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout + result.stderr


def test_mutation_neuter_suppression_causes_incident_test_to_fail(tmp_path):
    original = _COORD_SRC.read_text(encoding="utf-8")
    target = "any_sensor_active = False"
    assert original.count(target) >= 1, (
        "Suppression assignment absent from coordinator.py — "
        "gate wiring missing (mutation anchor)"
    )
    # Neuter ONLY the gate's assignment: it appears inside the block
    # between the two delimiters. Slice the source, mutate the first
    # occurrence inside the block, splice back.
    i = original.index(_BLOCK_START)
    j = original.index(_BLOCK_END, i)
    head = original[:i]
    body = original[i:j]
    tail = original[j:]
    mutated_body = body.replace(target, "pass  # MUTATED", 1)
    assert mutated_body != body, "Mutation did not apply inside gate block"
    mutated = head + mutated_body + tail
    try:
        _COORD_SRC.write_text(mutated, encoding="utf-8")
        _run_pytest_in_subprocess(
            "quality/tests/test_fan_transition_gate.py::"
            "test_incident_replay_mmwave_sole_within_window_suppressed",
            expect_fail=True,
        )
    finally:
        _COORD_SRC.write_text(original, encoding="utf-8")
    # Sanity: restored source passes the same test.
    _run_pytest_in_subprocess(
        "quality/tests/test_fan_transition_gate.py::"
        "test_incident_replay_mmwave_sole_within_window_suppressed",
        expect_fail=False,
    )


# --------------------------------------------------------------------------
# T12 — In-process boundary assertion (NOT a mutation drill; C5 fix-up):
# at Δt = window (equal boundary), the gate MUST suppress — under `<=`
# the boundary is inclusive, which is what the docs promise. This test
# runs entirely in-process against the extracted gate block; no source
# mutation, no subprocess.
# --------------------------------------------------------------------------


def test_boundary_inclusive_at_window_edge():
    hass = make_hass()
    room = "Study A"
    fan_t = datetime(2026, 7, 31, 20, 41, 16, tzinfo=timezone.utc)
    # Exactly at the window boundary.
    now = fan_t + timedelta(seconds=float(FAN_TRANSITION_SUSPECT_WINDOW_S))
    coord = _FakeSelf(hass, last_occupied_state=False)
    _seed_presence(hass, last_transition=fan_t)

    ns = _run_gate(
        coord, now, room,
        any_sensor_active=True,
        motion_detected=False,
        presence_detected=True,
        occupancy_detected=False,
    )
    assert ns["any_sensor_active"] is False, (
        "Boundary tick (Δt = window) was NOT suppressed — the gate's "
        "window comparison is stricter than documented (should be <=)"
    )
    assert coord._fan_transition_suppressed_count == 1


# --------------------------------------------------------------------------
# T13 — HIGH-B1: when the gate fires, the local `_fan_gate_suppressed`
# flag is set True. The debounce fall-through relies on this flag to
# skip resetting `_occupancy_first_detected` and cancelling the
# debounce refresh — see T14 for the source-level guard assertion.
# --------------------------------------------------------------------------


def test_high_b1_gate_sets_fan_gate_suppressed_flag_when_firing():
    hass = make_hass()
    room = "Study A"
    fan_t = datetime(2026, 7, 31, 20, 41, 16, tzinfo=timezone.utc)
    now = fan_t + timedelta(seconds=2)
    coord = _FakeSelf(hass, last_occupied_state=False)
    _seed_presence(hass, last_transition=fan_t)

    ns = _run_gate(
        coord, now, room,
        any_sensor_active=True,
        motion_detected=False,
        presence_detected=True,
        occupancy_detected=False,
    )
    assert ns["any_sensor_active"] is False
    assert ns["_fan_gate_suppressed"] is True, (
        "Gate fired but did NOT set _fan_gate_suppressed — HIGH-B1: "
        "the debounce fall-through will reset _occupancy_first_detected "
        "on the next tick, silently restarting the debounce clock."
    )


def test_high_b1_gate_no_fire_leaves_fan_gate_suppressed_false():
    """When the gate is out-of-window, the flag stays False so the
    normal debounce reset path runs (no regression to prior semantics).
    """
    hass = make_hass()
    room = "Study A"
    fan_t = datetime(2026, 7, 31, 20, 41, 16, tzinfo=timezone.utc)
    now = fan_t + timedelta(seconds=99)  # far outside window
    coord = _FakeSelf(hass, last_occupied_state=False)
    _seed_presence(hass, last_transition=fan_t)

    ns = _run_gate(
        coord, now, room,
        any_sensor_active=True,
        motion_detected=False,
        presence_detected=True,
        occupancy_detected=False,
    )
    assert ns["_fan_gate_suppressed"] is False


# --------------------------------------------------------------------------
# T14 — HIGH-B1 (source-level guard): the debounce else-branch that
# resets `_occupancy_first_detected` and cancels the debounce refresh
# MUST be guarded by `if not _fan_gate_suppressed:`. Without this,
# even if the gate flag is set (T13), the fall-through will silently
# reset the debounce clock.
# --------------------------------------------------------------------------


def test_high_b1_debounce_fallthrough_guarded_by_fan_gate_suppressed():
    src = _COORD_SRC.read_text(encoding="utf-8")
    # Locate the debounce else-branch just past the gate END marker.
    i = src.index(_BLOCK_END)
    tail = src[i:i + 4000]
    assert "self._occupancy_first_detected = None" in tail, (
        "Debounce fall-through reset absent from expected region — "
        "the source layout changed, mutation anchor invalid."
    )
    # The guard MUST appear before the reset in that region.
    guard_at = tail.find("if not _fan_gate_suppressed:")
    reset_at = tail.find("self._occupancy_first_detected = None")
    assert guard_at != -1, (
        "HIGH-B1 regression: debounce fall-through is NOT guarded by "
        "`if not _fan_gate_suppressed:` — an in-progress debounce clock "
        "will be reset when the gate suppresses."
    )
    assert guard_at < reset_at, (
        "HIGH-B1 regression: `if not _fan_gate_suppressed:` guard is "
        "positioned AFTER the reset — it does not protect it."
    )


# --------------------------------------------------------------------------
# T15 — C1 reachability guard: no unconditional `return` between the
# substrate-gap canary comment and the gate's _BLOCK_START. A future
# early-return in that region would silently disable the gate.
# --------------------------------------------------------------------------


def test_c1_no_unconditional_return_before_gate():
    import re
    src = _COORD_SRC.read_text(encoding="utf-8")
    canary = "# ---- Substrate-gap canary"
    assert canary in src, (
        "Substrate-gap canary marker missing — mutation anchor invalid."
    )
    i = src.index(canary)
    j = src.index(_BLOCK_START, i)
    region = src[i:j]
    # An unconditional return is a bare `return` (or `return <expr>`) at
    # column 8 (function-body indent), NOT nested inside an if/for/try.
    # We flag any `        return` at exactly 8-space indent.
    pattern = re.compile(r"^        return(\s|$)", re.MULTILINE)
    matches = pattern.findall(region)
    assert not matches, (
        "C1 regression: an unconditional `return` at function-body indent "
        "appears between the substrate-gap canary and the fan-transition "
        "gate — the gate is unreachable from that codepath."
    )


# --------------------------------------------------------------------------
# T16 — C4 boundary: Δt = window + 0.1s → NOT suppressed (pins the
# `<= window` upper-bound rounding — one tenth past the boundary must
# admit).
# --------------------------------------------------------------------------


def test_c4_boundary_just_past_window_admits():
    hass = make_hass()
    room = "Study A"
    fan_t = datetime(2026, 7, 31, 20, 41, 16, tzinfo=timezone.utc)
    now = fan_t + timedelta(
        seconds=float(FAN_TRANSITION_SUSPECT_WINDOW_S) + 0.1,
    )
    coord = _FakeSelf(hass, last_occupied_state=False)
    _seed_presence(hass, last_transition=fan_t)

    ns = _run_gate(
        coord, now, room,
        any_sensor_active=True,
        motion_detected=False,
        presence_detected=True,
        occupancy_detected=False,
    )
    assert ns["any_sensor_active"] is True, (
        "Δt = window + 0.1s was suppressed — upper-bound rounding leak"
    )
    assert coord._fan_transition_suppressed_count == 0


# --------------------------------------------------------------------------
# T17 — C4 negative delta: stamp 2s in the FUTURE → NOT suppressed
# (pins the `0 <= delta` lower-bound guard against clock skew / bad
# stamps).
# --------------------------------------------------------------------------


def test_c4_negative_delta_future_stamp_admits():
    hass = make_hass()
    room = "Study A"
    now = datetime(2026, 7, 31, 20, 41, 16, tzinfo=timezone.utc)
    # Stamp 2s AFTER now — delta would be -2s, which must not suppress.
    fan_t = now + timedelta(seconds=2)
    coord = _FakeSelf(hass, last_occupied_state=False)
    _seed_presence(hass, last_transition=fan_t)

    ns = _run_gate(
        coord, now, room,
        any_sensor_active=True,
        motion_detected=False,
        presence_detected=True,
        occupancy_detected=False,
    )
    assert ns["any_sensor_active"] is True, (
        "Negative delta (future stamp) was suppressed — the `0 <= delta` "
        "lower-bound guard is missing or inverted"
    )
    assert coord._fan_transition_suppressed_count == 0


# --------------------------------------------------------------------------
# T18 — C2: OccupiedBinarySensor.extra_state_attributes surfaces
# `fan_transition_suppressed_count` from the coordinator via getattr.
# Tests only the wiring — the property is patched onto a minimal fake
# so we don't need to construct a full RoomCoordinator.
# --------------------------------------------------------------------------


def test_c2_occupied_binary_sensor_exposes_fan_transition_suppressed_count():
    """C2 (source-level wiring): the OccupiedBinarySensor
    `extra_state_attributes` property must expose the coordinator's
    `_fan_transition_suppressed_count` under the attribute key
    `fan_transition_suppressed_count`, via getattr (so it degrades to
    0 on older-state coordinators). We assert on the source text
    because the harness `homeassistant` mock can't import the binary
    sensor module in-process; the pattern is validated verbatim.
    """
    bs_src = (
        _REPO_ROOT
        / "custom_components"
        / "universal_room_automation"
        / "binary_sensor.py"
    ).read_text(encoding="utf-8")
    # Locate the OccupiedBinarySensor class body.
    assert "class OccupiedBinarySensor" in bs_src, (
        "OccupiedBinarySensor class missing — mutation anchor invalid"
    )
    i = bs_src.index("class OccupiedBinarySensor")
    # Trim to a bounded region so we don't match other classes' attrs.
    region = bs_src[i:i + 20000]
    assert '"fan_transition_suppressed_count"' in region, (
        "C2: `fan_transition_suppressed_count` attribute key missing "
        "from OccupiedBinarySensor.extra_state_attributes"
    )
    # The getattr wiring must reference the coordinator attr with a
    # 0 fallback (mirrors mmwave_fan_demotions_since_boot sibling).
    assert 'getattr(' in region and '"_fan_transition_suppressed_count"' in region, (
        "C2: getattr wiring for `_fan_transition_suppressed_count` "
        "missing from OccupiedBinarySensor.extra_state_attributes"
    )
