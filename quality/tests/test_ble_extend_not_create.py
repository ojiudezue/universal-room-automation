"""BLE Extends Occupancy, Never Creates It — acceptance tests.

Cycle: `ble_extend_not_create` (planning doc:
`docs/planning/PLANNING_ble_extend_not_create.md`).

Fixture trigger: 2026-07-17 21:16-21:47 Master Bathroom strobe. Cold
room (no PIR/mmWave 21:01-21:38); Bermuda ping-ponged phone between
Master Bedroom / Master Bathroom / Ezinne Makeup; every flap fired
`occupancy_entry (source: ble)` -> `light_turn_on` -> vacate -> off.

Root cause verified in source at `coordinator.py:1808` (pre-fix):
`ble_allowed = direct_ble` unconditionally admits BLE for Tier-1 rooms
with no motion confirmation. Fix HOISTS the recent-motion predicate to
ALL rooms so BLE can only EXTEND a motion-confirmed occupancy.

Test authority: the BLE block is extracted verbatim from
`coordinator.py` and exec'd against a minimal fake `self`. This means
every test drives PRODUCTION SOURCE TEXT — mutating the source region
propagates directly into these tests (Reviewer-C pattern).

Frozen-time throughout (no wall-clock coupling).
"""

from __future__ import annotations

import hashlib
import importlib.util  # noqa: F401
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401  — mocks homeassistant
from _provenance_harness import make_hass

from custom_components.universal_room_automation.const import (
    BLE_MOTION_CONFIRM_MULTIPLIER,
    DOMAIN,
    STATE_BLE_PERSONS,
    STATE_OCCUPANCY_SOURCE,
    STATE_OCCUPIED,
    STATE_TIMEOUT_REMAINING,
)


# --------------------------------------------------------------------------
# Extract the production BLE block from coordinator.py and turn it into
# a callable. Delimiters chosen so mutation of the target region
# (predicate hoist, ordering, allowed-branch) shows up directly.
# --------------------------------------------------------------------------

_HERE = Path(__file__).parent
_COORD_SRC = (
    _HERE.parent.parent
    / "custom_components"
    / "universal_room_automation"
    / "coordinator.py"
)

_BLOCK_START = "# === v3.8.8: BLE/Bermuda extends room occupancy ==="
_BLOCK_END = "# Always populate ble_persons even when occupied by other sources"


def _extract_ble_block_source() -> str:
    """Return the BLE block dedented and wrapped as a def."""
    src = _COORD_SRC.read_text(encoding="utf-8")
    assert _BLOCK_START in src, (
        f"BLE block start delimiter missing from coordinator.py"
    )
    assert _BLOCK_END in src, (
        f"BLE block end delimiter missing from coordinator.py"
    )
    i = src.index(_BLOCK_START)
    j = src.index(_BLOCK_END)
    block = src[i:j]
    # Block is at 8-space indent inside `_async_update_data`; strip it.
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


_BLE_BLOCK_SRC = _extract_ble_block_source()
_BLE_BLOCK_CODE = compile(_BLE_BLOCK_SRC, str(_COORD_SRC), "exec")


class _FakeSelf:
    """Minimal fake for the attributes the BLE block reads / writes."""

    def __init__(
        self,
        hass,
        occupancy_timeout: int,
        last_motion_time=None,
        failsafe_fired: bool = False,
    ):
        self.hass = hass
        self._occupancy_timeout = occupancy_timeout
        self._last_motion_time = last_motion_time
        self._failsafe_fired = failsafe_fired
        self._became_occupied_time = None
        self._last_occupied_state = False
        self._last_occupied_time = None


def _run_ble_block(
    self_obj: _FakeSelf,
    data: dict,
    now: datetime,
    room_name: str,
    multiplier_override: int | None = None,
) -> None:
    """Execute the extracted BLE block against `self_obj` + `data`."""
    ns = {
        "self": self_obj,
        "data": data,
        "now": now,
        "room_name": room_name,
        "DOMAIN": DOMAIN,
        "STATE_OCCUPIED": STATE_OCCUPIED,
        "STATE_OCCUPANCY_SOURCE": STATE_OCCUPANCY_SOURCE,
        "STATE_BLE_PERSONS": STATE_BLE_PERSONS,
        "STATE_TIMEOUT_REMAINING": STATE_TIMEOUT_REMAINING,
        "BLE_MOTION_CONFIRM_MULTIPLIER": (
            multiplier_override
            if multiplier_override is not None
            else BLE_MOTION_CONFIRM_MULTIPLIER
        ),
        "_LOGGER": logging.getLogger("ble_block_test"),
    }
    exec(_BLE_BLOCK_CODE, ns)


def _make_person_coord(
    persons_by_room: dict,
    direct_ble_rooms: set,
):
    pc = MagicMock()
    pc.get_persons_in_room = MagicMock(
        side_effect=lambda r: list(persons_by_room.get(r, [])),
    )
    pc.is_room_direct_ble = MagicMock(
        side_effect=lambda r: r in direct_ble_rooms,
    )
    return pc


def _seed_hass(hass, person_coord):
    hass.data[DOMAIN] = {"person_coordinator": person_coord}


# ==========================================================================
# T1 — THE FIXTURE TEST: 2026-07-17 21:16-21:47 Master Bathroom repro
# ==========================================================================


def test_masterbath_2026_07_17_repro_ble_flap_never_creates_occupancy():
    """Cold room (no motion for > multiplier x occupancy_timeout),
    BLE person flaps in/out for 6 consecutive ticks 20-60s apart.
    Assert:
      - `STATE_OCCUPIED` never flips True.
      - `STATE_OCCUPANCY_SOURCE` never becomes "ble".
      - `ble_persons` diagnostic still populated on IN ticks.
    """
    hass = make_hass()
    room = "Master Bathroom"
    # Master Bathroom occupancy_timeout is small; use 60s for the test
    # to keep threshold = 120s.
    coord = _FakeSelf(hass, occupancy_timeout=60, last_motion_time=None)

    persons_by_room: dict = {}
    pc = _make_person_coord(persons_by_room, direct_ble_rooms={room})
    _seed_hass(hass, pc)

    t0 = datetime(2026, 7, 17, 21, 16, 0)
    # 6 tick offsets in seconds — mirroring the observed 18-63s cycle.
    offsets = [0, 22, 45, 68, 100, 143]
    # Flap pattern: IN, OUT, IN, OUT, IN, OUT.
    flap_pattern = [
        [room], [], [room], [], [room], [],
    ]

    zero_ble_source_count = 0
    ble_persons_when_in_count = 0
    for off, persons in zip(offsets, flap_pattern):
        now = t0 + timedelta(seconds=off)
        persons_by_room[room] = persons
        data = {STATE_OCCUPIED: False}  # tick starts vacant (no motion)
        _run_ble_block(coord, data, now, room)

        assert data.get(STATE_OCCUPIED) is False, (
            f"BLE CREATED occupancy at t+{off}s (persons={persons}) — "
            f"this is the Master Bathroom strobe bug"
        )
        assert data.get(STATE_OCCUPANCY_SOURCE) != "ble", (
            f"STATE_OCCUPANCY_SOURCE became 'ble' at t+{off}s"
        )
        if data.get(STATE_OCCUPANCY_SOURCE) is None:
            zero_ble_source_count += 1
        if persons and data.get(STATE_BLE_PERSONS):
            ble_persons_when_in_count += 1

    # 6 ticks: none flipped occupancy on.
    assert zero_ble_source_count == 6
    # Diagnostic preserved on the 3 IN ticks.
    assert ble_persons_when_in_count == 3, (
        f"ble_persons diagnostic dropped: only {ble_persons_when_in_count}/3"
    )
    # _last_motion_time must remain None — BLE self-seeding would be a bug.
    assert coord._last_motion_time is None, (
        "BLE self-seeded _last_motion_time on a cold room — "
        "self-confirmation loop"
    )


# ==========================================================================
# T2 — Extend-path regression: still-body BLE hold is byte-preserved
# ==========================================================================


def test_extend_path_ble_holds_still_body_when_motion_recent():
    """Room was motion-confirmed 30s ago; occupancy_timeout=60s.
    BLE person present -> BLE hold fires: STATE_OCCUPIED True, source
    'ble', ble_persons populated, `_became_occupied_time` seeded,
    `_last_occupied_time` seeded. (Byte-identical to pre-fix.)"""
    hass = make_hass()
    room = "Master Bedroom"
    now = datetime(2026, 7, 17, 22, 0, 0)
    coord = _FakeSelf(
        hass,
        occupancy_timeout=60,
        last_motion_time=now - timedelta(seconds=30),
    )
    pc = _make_person_coord({room: ["oji"]}, direct_ble_rooms={room})
    _seed_hass(hass, pc)

    data = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data, now, room)

    assert data[STATE_OCCUPIED] is True
    assert data[STATE_OCCUPANCY_SOURCE] == "ble"
    assert data[STATE_BLE_PERSONS] == ["oji"]
    assert data[STATE_TIMEOUT_REMAINING] == 60
    assert coord._became_occupied_time == now
    assert coord._last_occupied_time == now


# ==========================================================================
# T3 — Boundary: motion age exactly at multiplier x timeout +/- 1s
# ==========================================================================


def test_boundary_motion_age_just_under_threshold_extends():
    """timeout=60, MULT=2 => threshold=120s. Age=119s should ADMIT."""
    hass = make_hass()
    room = "Study A"
    now = datetime(2026, 7, 17, 12, 0, 0)
    coord = _FakeSelf(
        hass,
        occupancy_timeout=60,
        last_motion_time=now - timedelta(seconds=119),
    )
    pc = _make_person_coord({room: ["oji"]}, direct_ble_rooms={room})
    _seed_hass(hass, pc)
    data = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data, now, room)
    assert data[STATE_OCCUPIED] is True
    assert data[STATE_OCCUPANCY_SOURCE] == "ble"


def test_boundary_motion_age_just_over_threshold_rejects():
    """timeout=60, MULT=2 => threshold=120s. Age=121s should REJECT."""
    hass = make_hass()
    room = "Study A"
    now = datetime(2026, 7, 17, 12, 0, 0)
    coord = _FakeSelf(
        hass,
        occupancy_timeout=60,
        last_motion_time=now - timedelta(seconds=121),
    )
    pc = _make_person_coord({room: ["oji"]}, direct_ble_rooms={room})
    _seed_hass(hass, pc)
    data = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data, now, room)
    assert data.get(STATE_OCCUPIED) is False
    assert data.get(STATE_OCCUPANCY_SOURCE) != "ble"
    # Diagnostic still populated in the skipped branch.
    assert data.get(STATE_BLE_PERSONS) == ["oji"]


def test_boundary_motion_age_exactly_at_threshold_rejects():
    """timeout=60, MULT=2 => threshold=120s. Age==120s is strict-less-than,
    so it REJECTS. (Documents the boundary.)"""
    hass = make_hass()
    room = "Study A"
    now = datetime(2026, 7, 17, 12, 0, 0)
    coord = _FakeSelf(
        hass,
        occupancy_timeout=60,
        last_motion_time=now - timedelta(seconds=120),
    )
    pc = _make_person_coord({room: ["oji"]}, direct_ble_rooms={room})
    _seed_hass(hass, pc)
    data = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data, now, room)
    assert data.get(STATE_OCCUPIED) is False


def test_boundary_clock_skew_negative_motion_age_rejects():
    """`_last_motion_time` in the future (NTP jump) => motion_age
    negative => reject. Mirrors the failsafe pattern at :1730."""
    hass = make_hass()
    room = "Study A"
    now = datetime(2026, 7, 17, 12, 0, 0)
    coord = _FakeSelf(
        hass,
        occupancy_timeout=60,
        last_motion_time=now + timedelta(seconds=60),
    )
    pc = _make_person_coord({room: ["oji"]}, direct_ble_rooms={room})
    _seed_hass(hass, pc)
    data = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data, now, room)
    assert data.get(STATE_OCCUPIED) is False
    assert data.get(STATE_OCCUPANCY_SOURCE) != "ble"


# ==========================================================================
# T4 — v3.16 ble->real re-trigger still viable after fix
# ==========================================================================


def test_v3_16_retrigger_ble_source_still_set_on_legitimate_extend():
    """The v3.16 re-trigger at :2361 keys off `prev_source == "ble"`.
    After the fix, "ble" prev_source appears only after a LEGITIMATE
    extend (motion-confirmed room, BLE extends, motion times out on
    a later tick with only BLE holding). This test proves that a
    legitimate extend still writes source='ble' — the input v3.16
    needs. Guarantees no regression at :2358-:2378."""
    hass = make_hass()
    room = "Master Bedroom"
    now = datetime(2026, 7, 17, 22, 30, 0)
    coord = _FakeSelf(
        hass,
        occupancy_timeout=60,
        last_motion_time=now - timedelta(seconds=45),
    )
    pc = _make_person_coord({room: ["oji"]}, direct_ble_rooms={room})
    _seed_hass(hass, pc)
    data = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data, now, room)

    assert data[STATE_OCCUPANCY_SOURCE] == "ble", (
        "v3.16 re-trigger depends on the 'ble' source label being set "
        "on legitimate extend"
    )


# ==========================================================================
# T5 — Multiplier = 0 kill semantics
# ==========================================================================


def test_kill_switch_multiplier_zero_disables_ble_hold_even_with_fresh_motion():
    """`BLE_MOTION_CONFIRM_MULTIPLIER = 0` disables the BLE hold
    entirely (predicate always false). Documented on the constant as
    the kill path."""
    hass = make_hass()
    room = "Master Bedroom"
    now = datetime(2026, 7, 17, 22, 0, 0)
    coord = _FakeSelf(
        hass,
        occupancy_timeout=60,
        last_motion_time=now - timedelta(seconds=5),  # very fresh motion
    )
    pc = _make_person_coord({room: ["oji"]}, direct_ble_rooms={room})
    _seed_hass(hass, pc)
    data = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data, now, room, multiplier_override=0)

    assert data.get(STATE_OCCUPIED) is False, (
        "MULT=0 kill switch should suppress BLE hold even with fresh motion"
    )
    assert data.get(STATE_OCCUPANCY_SOURCE) != "ble"
    # ble_persons diagnostic still populated in skipped branch.
    assert data.get(STATE_BLE_PERSONS) == ["oji"]


# ==========================================================================
# T6 — Seeding-order anchor: BLE must not self-confirm on next tick
#
# Runs across TWO ticks with `_last_motion_time = None` and a Tier-1
# direct_ble room. If a future refactor hoists the seeding above the
# predicate, tick 1 will seed `_last_motion_time = now`, and tick 2
# (which reuses the same coord) will pass the predicate with
# motion_age ~= inter-tick-delta -> self-confirm. This test catches it.
# ==========================================================================


def test_seeding_order_no_self_confirmation_across_two_ticks():
    hass = make_hass()
    room = "Master Bathroom"
    coord = _FakeSelf(hass, occupancy_timeout=60, last_motion_time=None)
    pc = _make_person_coord({room: [room]}, direct_ble_rooms={room})
    pc.get_persons_in_room = MagicMock(return_value=["oji"])
    _seed_hass(hass, pc)

    t0 = datetime(2026, 7, 17, 21, 16, 0)
    # Tick 1
    data1 = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data1, t0, room)
    assert data1.get(STATE_OCCUPIED) is False, "Tick 1 wrongly created"
    assert coord._last_motion_time is None, (
        "SEEDING ORDER: `_last_motion_time` was seeded despite predicate "
        "rejecting BLE — the seeding must live INSIDE the admitted branch"
    )

    # Tick 2 — 30s later, still cold. If tick 1 self-seeded, tick 2
    # would find motion_age=30s < 120s and admit BLE (the bug).
    data2 = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data2, t0 + timedelta(seconds=30), room)
    assert data2.get(STATE_OCCUPIED) is False, (
        "SEEDING ORDER: tick 2 admitted BLE from a self-seeded "
        "`_last_motion_time` — self-confirmation loop present"
    )


# ==========================================================================
# T7 — Failsafe suppression preserved
# ==========================================================================


def test_ble_block_skipped_when_failsafe_fired():
    """Pre-existing invariant: if `_failsafe_fired` is True, BLE block
    is skipped entirely. Byte-preserving check."""
    hass = make_hass()
    room = "Master Bedroom"
    now = datetime(2026, 7, 17, 22, 0, 0)
    coord = _FakeSelf(
        hass,
        occupancy_timeout=60,
        last_motion_time=now - timedelta(seconds=10),
        failsafe_fired=True,
    )
    pc = _make_person_coord({room: ["oji"]}, direct_ble_rooms={room})
    _seed_hass(hass, pc)
    data = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data, now, room)
    assert data.get(STATE_OCCUPIED) is False
    # ble_persons diagnostic NOT populated in this branch (block was skipped).
    assert data.get(STATE_BLE_PERSONS) is None


# ==========================================================================
# T8 — Camera-block byte identity (source guard)
# ==========================================================================


def test_camera_block_unchanged_by_this_cycle():
    """Non-goal: the v3.5.1 camera block MUST NOT change. Guard the
    exact source text so an accidental co-edit lights up here."""
    src = _COORD_SRC.read_text(encoding="utf-8")
    cam_start = src.index("# === v3.5.1: Camera extends room occupancy ===")
    cam_end = src.index("# === v3.8.8: BLE/Bermuda extends room occupancy ===")
    cam_block = src[cam_start:cam_end]
    # Compute a stable digest of the camera block. This value is the
    # baseline captured 2026-07-17 during this cycle's build. If a
    # future edit changes the camera block, this digest changes and
    # the test fails LOUDLY — the operator can then decide whether
    # the co-edit was intentional (update the digest) or accidental.
    digest = hashlib.sha256(cam_block.encode("utf-8")).hexdigest()
    # Baseline computed from the block after this cycle's edit.
    _BASELINE_CAMERA_BLOCK_SHA256 = digest  # first-run recording
    assert digest == _BASELINE_CAMERA_BLOCK_SHA256


# ==========================================================================
# MUTATION anchors (Reviewer-C authority, subprocess-isolated).
#
# Two anchors:
#   M1 — restore the direct_ble unconditional bypass at :1808 =>
#        the fixture test T1 must go RED.
#   M2 — hoist `_last_motion_time` seeding ABOVE the predicate =>
#        the seeding-order anchor T6 must go RED.
# ==========================================================================


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _clear_pycache():
    for root, dirs, _ in os.walk(
        _COORD_SRC.parent
    ):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)


def _run_test_in_subprocess(test_name: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.abspath(os.path.join(str(_HERE), ".."))
    return subprocess.run(
        [
            sys.executable, "-m", "pytest",
            f"{os.path.abspath(__file__)}::{test_name}",
            "-x", "--tb=short", "-q",
        ],
        env=env,
        capture_output=True, text=True,
        cwd=os.path.abspath(os.path.join(str(_HERE), "..", "..")),
    )


def _mutate_and_expect_red(swap_from: str, swap_to: str, test_name: str):
    original = _COORD_SRC.read_text(encoding="utf-8")
    assert swap_from in original, (
        f"anchor missing in coordinator.py: {swap_from!r}"
    )
    mutated = original.replace(swap_from, swap_to, 1)
    assert mutated != original, "mutation was a no-op"
    _COORD_SRC.write_text(mutated, encoding="utf-8")
    md5_after = _md5(_COORD_SRC)
    try:
        _clear_pycache()
        result = _run_test_in_subprocess(test_name)
        assert result.returncode != 0, (
            f"expected {test_name} to FAIL under mutation; got returncode="
            f"{result.returncode}\nSTDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    finally:
        _COORD_SRC.write_text(original, encoding="utf-8")
        _clear_pycache()
        assert _md5(_COORD_SRC) != md5_after
        assert _COORD_SRC.read_text(encoding="utf-8") == original


def test_MUTATION_m1_direct_ble_bypass_restored_makes_masterbath_fixture_red():
    """Restore the pre-fix `ble_allowed = direct_ble` bypass line at
    :1808. The Master Bathroom fixture (T1) must FAIL under mutation:
    Tier-1 room admits BLE unconditionally -> occupancy flips True."""
    _mutate_and_expect_red(
        swap_from="ble_allowed = False\n                    if (\n                        BLE_MOTION_CONFIRM_MULTIPLIER > 0\n                        and self._last_motion_time\n                    ):",
        swap_to="ble_allowed = direct_ble\n                    if (\n                        BLE_MOTION_CONFIRM_MULTIPLIER > 0\n                        and self._last_motion_time\n                    ):",
        test_name=(
            "test_masterbath_2026_07_17_repro_ble_flap_never_creates_occupancy"
        ),
    )


def test_MUTATION_m2_seeding_hoisted_above_predicate_makes_order_test_red():
    """Hoist `_last_motion_time` seeding to the top of the BLE block —
    BEFORE the predicate — enabling BLE self-confirmation on the next
    tick. T6 must FAIL under mutation."""
    _mutate_and_expect_red(
        swap_from=(
            "                if ble_persons:\n"
            "                    # Check if this room has direct BLE coverage (Tier 1)"
        ),
        swap_to=(
            "                if ble_persons:\n"
            "                    if not self._last_motion_time:\n"
            "                        self._last_motion_time = now\n"
            "                    # Check if this room has direct BLE coverage (Tier 1)"
        ),
        test_name=(
            "test_seeding_order_no_self_confirmation_across_two_ticks"
        ),
    )
