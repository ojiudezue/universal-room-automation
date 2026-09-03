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
    BLE_CHAIN_HOLD_ENABLED,
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
        # ble-bleed-extend-corroboration A1 anchor (default: no prior
        # BLE-only-hold observed — cap fails OPEN so existing chain
        # tests keep their current admit behaviour).
        self._ble_only_hold_since = None
        # ble-bleed-extend-corroboration cap harness stubs. Default:
        # room_type unknown → cap default False → gate never fires.
        # Callers that want to exercise the cap set _room_type on the
        # instance BEFORE running the block AND populate
        # _became_occupied_time in the past.
        self._room_type = "generic"

    def _get_config(self, key, default=None):
        # Match production _get_config: options-then-data-then-default.
        # Tests do not populate an entry; every read falls through to
        # the default — this preserves the extend-never-create behavior
        # of existing tests (cap default is room_type-keyed, generic=False).
        return default

    def _get_ble_hold_cap_seconds(self):
        from custom_components.universal_room_automation.const import (
            BLE_HOLD_CAP_DURATIONS,
            DEFAULT_BLE_HOLD_CAP_SECONDS,
        )
        return BLE_HOLD_CAP_DURATIONS.get(
            self._room_type, DEFAULT_BLE_HOLD_CAP_SECONDS,
        )


def _run_ble_block(
    self_obj: _FakeSelf,
    data: dict,
    now: datetime,
    room_name: str,
    multiplier_override: int | None = None,
) -> None:
    """Execute the extracted BLE block against `self_obj` + `data`.

    MULT split 2026-08-10: the BLE block's kill switch is now the bool
    `BLE_CHAIN_HOLD_ENABLED`. `multiplier_override` is honoured for
    backward-compat with test call sites — `0` maps to disabled, any
    positive value (or None) maps to enabled.
    """
    if multiplier_override is None:
        _enabled = BLE_CHAIN_HOLD_ENABLED
    else:
        _enabled = bool(multiplier_override > 0)
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
        "BLE_CHAIN_HOLD_ENABLED": _enabled,
        "_LOGGER": logging.getLogger("ble_block_test"),
        # ble-bleed-extend-corroboration: the extracted block does a
        # local `from .const import (...)` for the cap symbols. Seed
        # __name__/__package__ so the relative import can resolve.
        "__name__": "custom_components.universal_room_automation.coordinator",
        "__package__": "custom_components.universal_room_automation",
    }
    # The BLE block calls the module-level NM fire helper on cap eviction.
    from custom_components.universal_room_automation import coordinator as _cm  # noqa: PLC0415
    ns["_fire_ble_hold_cap_nm"] = _cm._fire_ble_hold_cap_nm
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


def test_extend_path_ble_holds_still_body_when_chain_unbroken():
    """Room was motion-confirmed on the prior tick (chain unbroken);
    BLE person present -> BLE hold fires: STATE_OCCUPIED True, source
    'ble', ble_persons populated, `_became_occupied_time` seeded,
    `_last_occupied_time` seeded. Post BLE-WARM-CREATE-1 the motion-
    age is irrelevant; only the chain matters."""
    hass = make_hass()
    room = "Master Bedroom"
    now = datetime(2026, 7, 17, 22, 0, 0)
    coord = _FakeSelf(
        hass,
        occupancy_timeout=60,
        last_motion_time=now - timedelta(seconds=30),
    )
    coord._last_occupied_state = True  # chain unbroken from prev tick
    pc = _make_person_coord({room: ["oji"]}, direct_ble_rooms={room})
    _seed_hass(hass, pc)

    data = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data, now, room)

    assert data[STATE_OCCUPIED] is True
    assert data[STATE_OCCUPANCY_SOURCE] == "ble"
    assert data[STATE_BLE_PERSONS] == ["oji"]
    assert data[STATE_TIMEOUT_REMAINING] == 60
    assert coord._became_occupied_time == now
    # `_last_occupied_time` only re-seeds when chain was previously broken;
    # here chain was unbroken so it stays at its pre-tick value (None).
    assert coord._last_occupied_time is None


# ==========================================================================
# T3 — Falsifiable-invariant regression anchors (BLE-WARM-CREATE-1,
#      2026-08-10): with chain BROKEN (`_last_occupied_state=False`),
#      BLE presence must NEVER create occupancy regardless of the
#      recency of prior motion. These parameterize over the motion
#      ages leg (b) used to admit — they go RED if any future refactor
#      re-introduces a window-scoped create path.
# ==========================================================================


import pytest


@pytest.mark.parametrize(
    "motion_age_s",
    [None, 1, 60, 119, 120, 121, 540],
)
def test_invariant_cold_room_ble_never_creates_regardless_of_motion_age(
    motion_age_s,
):
    """Falsifiable invariant: chain broken + BLE present => REJECT.

    Parameterized over the motion ages that leg (b) would have admitted
    (1s, 60s, 119s — inside the old 2xtimeout window) and ages already
    outside it (120s, 121s, 540s), plus the no-motion case (None).
    Under the CHAIN-ONLY admission all cases must REJECT. The diagnostic
    `ble_persons` list must still be populated on every rejected tick.
    """
    hass = make_hass()
    room = "Study A"
    now = datetime(2026, 7, 17, 12, 0, 0)
    last_motion = (
        None
        if motion_age_s is None
        else now - timedelta(seconds=motion_age_s)
    )
    coord = _FakeSelf(
        hass,
        occupancy_timeout=60,
        last_motion_time=last_motion,
    )
    # chain broken (default): coord._last_occupied_state=False
    pc = _make_person_coord({room: ["oji"]}, direct_ble_rooms={room})
    _seed_hass(hass, pc)

    data = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data, now, room)

    assert data.get(STATE_OCCUPIED) is False, (
        f"BLE-WARM-CREATE-1: BLE CREATED occupancy at motion_age="
        f"{motion_age_s}s with chain broken — leg (b) reintroduced?"
    )
    assert data.get(STATE_OCCUPANCY_SOURCE) != "ble"
    # Diagnostic preserved.
    assert data.get(STATE_BLE_PERSONS) == ["oji"]


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
    After BLE-WARM-CREATE-1 (chain-only admission), "ble" prev_source
    appears only after a LEGITIMATE extend — a chain-unbroken room with
    a BLE person present. This test proves that a legitimate extend
    still writes source='ble'. Guarantees no regression at :2358-:2378."""
    hass = make_hass()
    room = "Master Bedroom"
    now = datetime(2026, 7, 17, 22, 30, 0)
    coord = _FakeSelf(
        hass,
        occupancy_timeout=60,
        last_motion_time=now - timedelta(seconds=45),
    )
    coord._last_occupied_state = True  # chain unbroken from prev tick
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


def test_kill_switch_multiplier_zero_disables_ble_chain_hold_even_when_chain_unbroken():
    """`BLE_CHAIN_HOLD_ENABLED = False` (== the old MULT=0 kill)
    disables the BLE hold entirely (chain predicate always false).
    Post BLE-WARM-CREATE-1 (chain-only admission) the meaningful kill
    check is that even a LEGITIMATE extend (chain unbroken) is
    suppressed by the kill switch."""
    hass = make_hass()
    room = "Master Bedroom"
    now = datetime(2026, 7, 17, 22, 0, 0)
    coord = _FakeSelf(
        hass,
        occupancy_timeout=60,
        last_motion_time=now - timedelta(seconds=5),  # very fresh motion
    )
    coord._last_occupied_state = True  # chain unbroken — would admit sans kill
    pc = _make_person_coord({room: ["oji"]}, direct_ble_rooms={room})
    _seed_hass(hass, pc)
    data = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data, now, room, multiplier_override=0)

    assert data.get(STATE_OCCUPIED) is False, (
        "MULT=0 kill switch should suppress BLE hold even when chain unbroken"
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
    # Baseline FROZEN 2026-07-17; re-frozen 2026-09-03 for the
    # ble-bleed-extend-corroboration HIGH-1 co-edit that added the
    # `self._ble_only_hold_since = None` reset after the camera
    # branch's `_became_occupied_time` seed. If this cycle again
    # intentionally edits the v3.5.1 camera block, RE-FREEZE this hex
    # deliberately after inspecting the diff; a silent co-edit will
    # fail loudly here.
    _BASELINE_CAMERA_BLOCK_SHA256 = (
        "4ff04f7fce26587a0145e7a789e829840daeaa3b7d61a89aae433366dc63bd4c"
    )
    assert digest == _BASELINE_CAMERA_BLOCK_SHA256, (
        f"Camera block SHA changed: expected "
        f"{_BASELINE_CAMERA_BLOCK_SHA256}, got {digest}. If the co-edit "
        f"was intentional, update the frozen hex above; otherwise revert."
    )


# ==========================================================================
# B-MED-1 — Sleep-hold pin: chain-unbroken room extends indefinitely
#          past the motion-leg window
# ==========================================================================


def test_sleep_hold_pin_chain_extends_past_motion_window():
    """Direct-BLE room, motion_age = 2 x occupancy_timeout + 1s (past
    the motion-leg window), but `_last_occupied_state=True` (chain
    unbroken from prior tick). The chain leg must ADMIT — this is the
    sleep-hold invariant (b): a legitimately-held room is BLE-held
    indefinitely, bounded only by the 4-hour failsafe."""
    hass = make_hass()
    room = "Master Bedroom"
    now = datetime(2026, 7, 17, 22, 30, 0)
    timeout = 60
    coord = _FakeSelf(
        hass,
        occupancy_timeout=timeout,
        # motion_age = 2*timeout + 1 = 121s -> motion leg REJECTS
        last_motion_time=now - timedelta(seconds=timeout * 2 + 1),
    )
    coord._last_occupied_state = True  # chain unbroken (prev tick)
    pc = _make_person_coord({room: ["oji"]}, direct_ble_rooms={room})
    _seed_hass(hass, pc)

    data = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data, now, room)

    assert data.get(STATE_OCCUPIED) is True, (
        "chain leg must admit BLE hold indefinitely when prev-tick "
        "occupied — sleep-hold invariant (b) violated"
    )
    assert data.get(STATE_OCCUPANCY_SOURCE) == "ble"


def test_sleep_hold_chain_broken_rejects_with_stale_motion():
    """Companion to the sleep-hold pin: chain BROKEN
    (`_last_occupied_state=False`) with the SAME stale motion age must
    REJECT. Guarantees a cold room (Bermuda flap) still fails after the
    chain leg is added."""
    hass = make_hass()
    room = "Master Bedroom"
    now = datetime(2026, 7, 17, 22, 30, 0)
    timeout = 60
    coord = _FakeSelf(
        hass,
        occupancy_timeout=timeout,
        last_motion_time=now - timedelta(seconds=timeout * 2 + 1),
    )
    # coord._last_occupied_state defaults False -> chain broken
    pc = _make_person_coord({room: ["oji"]}, direct_ble_rooms={room})
    _seed_hass(hass, pc)

    data = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data, now, room)

    assert data.get(STATE_OCCUPIED) is False, (
        "cold room (chain broken + stale motion) must REJECT even with "
        "BLE person present — invariant (a) 'never CREATE' violated"
    )
    assert data.get(STATE_OCCUPANCY_SOURCE) != "ble"


# ==========================================================================
# B-MED-2 — 5-tick chain scenario: motion-confirm -> chain-extend x3
#          -> BLE departs -> exit
#
# Harness gap note: the extracted-block harness only runs the BLE block
# region, not the full `_async_update_data` cycle that mutates
# `_last_occupied_state` (line ~2274). A true two-tick integration test
# would need to construct a full `UniversalRoomCoordinator` with
# platform + registry + entry plumbing, which the current fixtures
# (make_hass, MagicMock person_coord) do not provide. Rather than
# fabricate that plumbing, we simulate the state-carrying edge
# explicitly here: after each tick, mirror the prod update at :2274 /
# :2280 by copying `data[STATE_OCCUPIED]` into
# `coord._last_occupied_state`. This preserves the invariant we care
# about (chain propagation across ticks) while keeping the test on the
# same authority surface as T1-T7.
# ==========================================================================


def test_five_tick_chain_motion_confirm_then_chain_extend_then_exit():
    hass = make_hass()
    room = "Master Bedroom"
    timeout = 60
    t0 = datetime(2026, 7, 17, 22, 0, 0)
    coord = _FakeSelf(
        hass,
        occupancy_timeout=timeout,
        # Motion inside the window (kept as documentation; chain-only
        # admission ignores motion_age).
        last_motion_time=t0 - timedelta(seconds=30),
    )
    # Model production handoff: prior tick was motion-occupied so chain
    # is unbroken entering tick 1. Post BLE-WARM-CREATE-1 this is the
    # sole admission path.
    coord._last_occupied_state = True
    persons = {room: ["oji"]}
    pc = _make_person_coord(persons, direct_ble_rooms={room})
    _seed_hass(hass, pc)

    # Tick 1: chain unbroken + BLE -> chain leg admits.
    data1 = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data1, t0, room)
    assert data1[STATE_OCCUPIED] is True
    assert data1[STATE_OCCUPANCY_SOURCE] == "ble"
    # Mirror prod _last_occupied_state update (:2274).
    coord._last_occupied_state = data1[STATE_OCCUPIED]

    # Ticks 2, 3, 4: motion is now well past the 120s window, but chain
    # is unbroken from tick 1 -> chain-leg admits indefinitely.
    for i, secs_from_t0 in enumerate(
        [timeout * 3, timeout * 5, timeout * 10], start=2
    ):
        now = t0 + timedelta(seconds=secs_from_t0)
        data = {STATE_OCCUPIED: False}
        _run_ble_block(coord, data, now, room)
        assert data[STATE_OCCUPIED] is True, (
            f"tick {i}: chain leg failed to extend BLE hold at "
            f"motion_age={secs_from_t0 + 30}s"
        )
        assert data[STATE_OCCUPANCY_SOURCE] == "ble"
        coord._last_occupied_state = data[STATE_OCCUPIED]

    # Tick 5: BLE person departs. Block sees ble_persons=[] -> the
    # `if ble_persons:` branch is skipped, occupancy stays False, and
    # the outer cycle would fire exit. Mirror the prod update.
    persons[room] = []
    now = t0 + timedelta(seconds=timeout * 12)
    data5 = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data5, now, room)
    assert data5.get(STATE_OCCUPIED) is False, (
        "tick 5 (BLE departs): block must not re-admit; occupancy "
        "should exit once ble_persons is empty"
    )
    assert data5.get(STATE_OCCUPANCY_SOURCE) != "ble"
    coord._last_occupied_state = bool(data5.get(STATE_OCCUPIED))

    # Tick 6: chain is now broken, motion is ancient. Even if BLE
    # returns, the block must REJECT (would be a fresh create).
    persons[room] = ["oji"]
    now = t0 + timedelta(seconds=timeout * 13)
    data6 = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data6, now, room)
    assert data6.get(STATE_OCCUPIED) is False, (
        "post-exit BLE flap must not CREATE occupancy — chain broken, "
        "motion stale"
    )


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
    """Restore the pre-v5.22.0 Tier-1 bypass by ORing `direct_ble` into
    the chain-only admission. This reproduces the pre-fix behavior where
    a direct-BLE room admits BLE unconditionally. The Master Bathroom
    fixture (T1) must FAIL under mutation.

    Post BLE-WARM-CREATE-1 the production line is
    ``ble_allowed = chain_unbroken`` (single-leg); the mutation ORs
    ``direct_ble`` back in to model any future re-introduction of a
    create path."""
    _mutate_and_expect_red(
        swap_from="                        ble_allowed = chain_unbroken\n",
        swap_to=(
            "                        ble_allowed = chain_unbroken or direct_ble\n"
        ),
        test_name=(
            "test_masterbath_2026_07_17_repro_ble_flap_never_creates_occupancy"
        ),
    )


def test_MUTATION_m3_chain_leg_removed_makes_sleep_hold_test_red():
    """Remove the CHAIN leg by forcing chain_unbroken=False. The
    still-body sleep-hold test (motion_age past window + prev-tick
    occupied) must FAIL — without the chain leg, the motion leg alone
    would bound BLE holds to 2 x occupancy_timeout, contradicting
    invariant (b) that a legitimately-held room extends indefinitely
    (bounded only by the 4-hour failsafe)."""
    _mutate_and_expect_red(
        swap_from="chain_unbroken = self._last_occupied_state",
        swap_to="chain_unbroken = False",
        test_name="test_sleep_hold_pin_chain_extends_past_motion_window",
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


def test_pin_restart_midhold_chain_readmits_without_inprocess_tier1():
    """D-MEDIUM-1 PIN (operator decision 2026-08-10, option 1: ACCEPT).

    Extend-across-restart is INTENDED behavior, deliberately carved out
    of the never-create invariant. Scenario: HA restarts mid-hold;
    RestoreEntity/DB rehydrates ``_last_occupied_state=True`` before the
    first refresh, ``_last_motion_time`` is NOT restored (boots None),
    no in-process Tier-1 evidence has fired since start, BLE person
    present -> the chain leg MUST ADMIT (re-establish the hold).

    This is a PINNING test, not a blocking one: if a future cycle wants
    the tighter in-process invariant (option 2: a post-restart Tier-1
    gate), this test is the one it must consciously flip — do not
    weaken it silently. Repro/adjudication: kanban BLE-WARM-CREATE-1,
    D_MEDIUM_1_OPERATOR_DECISION_NEEDED.
    """
    hass = make_hass()
    room = "Master Bathroom"
    now = datetime(2026, 8, 10, 12, 0, 0)
    coord = _FakeSelf(
        hass,
        occupancy_timeout=300,
        last_motion_time=None,  # not restored across restart
    )
    coord._last_occupied_state = True  # rehydrated by RestoreEntity/DB
    pc = _make_person_coord({room: ["oji"]}, direct_ble_rooms={room})
    _seed_hass(hass, pc)

    data = {STATE_OCCUPIED: False}
    _run_ble_block(coord, data, now, room)
    assert data[STATE_OCCUPIED] is True, (
        "restart-mid-hold chain re-admission is PINNED intended "
        "behavior (D-MEDIUM-1 option 1); a silent change here is a "
        "regression in EITHER direction"
    )
    assert data.get(STATE_OCCUPANCY_SOURCE) == "ble"
