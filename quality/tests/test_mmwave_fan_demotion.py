"""mmWave Fan-Corroboration Demotion (Tier-3 D2) — acceptance tests.

Cycle: `mmwave_corroboration_tier3` (planning doc:
`docs/planning/PLANNING_mmwave_corroboration_tier3.md`). D2 is the
passive backstop to the pause-based fan-recheck (v5.23.0): when a
room's occupancy is sustained by mmWave alone AND fans have been on
for >= grace AND no PIR motion in >= MULT * timeout AND no BLE-
trustworthy person is present AND recheck is not in-flight, the
demotion releases the room to vacant.

Test authority (Bug Class #62): the demotion block is extracted
verbatim from `coordinator.py` and exec'd against a minimal fake
`self`. Every test drives PRODUCTION SOURCE TEXT — mutating the target
region propagates directly into these tests (Reviewer-C mutation
anchor). The wrapper predicate in `presence.py` is exercised by
direct-import tests on the pure-python helper.
"""

from __future__ import annotations

import importlib.util  # noqa: F401
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401  — mocks homeassistant
from _provenance_harness import make_hass

from custom_components.universal_room_automation.const import (
    D2_PIR_STALENESS_MULTIPLIER,
    DOMAIN,
    MMWAVE_FAN_CORROBORATION_ENABLED,
    MMWAVE_FAN_CORROBORATION_GRACE_S,
    OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED,
    STATE_BLE_PERSONS,
    STATE_OCCUPANCY_SOURCE,
    STATE_OCCUPIED,
    STATE_TIMEOUT_REMAINING,
)
# NOTE: `signals` module is monkeypatched to a bare MagicMock by other
# test modules that run first in a full-suite invocation (see
# test_comfort_fan_away_veto_behavioral.py-style harnesses). Import
# lazily inside each test that needs the symbol so collection cannot
# fail on a mocked signals module. The string value must match the
# authoritative definition in signals.py.
_SIGNAL_MMWAVE_FAN_DEMOTED_STR = "ura_mmwave_fan_demoted"


# --------------------------------------------------------------------------
# T1 — constants + signal presence (D1 acceptance)
# --------------------------------------------------------------------------


def test_mmwave_fan_demotion_constants_present():
    # Kill switch defaults ON so feature is live post-deploy.
    assert MMWAVE_FAN_CORROBORATION_ENABLED is True
    # Grace default = 600s per plan §D1 table.
    assert int(MMWAVE_FAN_CORROBORATION_GRACE_S) == 600
    assert OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED == "mmwave_fan_demoted"
    # Cross-check the signals module string when it's still real (i.e.
    # not mocked out by a sibling test module's harness).
    try:
        from custom_components.universal_room_automation.domain_coordinators.signals import (  # noqa: PLC0415, E501
            SIGNAL_MMWAVE_FAN_DEMOTED as _sig,
        )
        assert _sig == _SIGNAL_MMWAVE_FAN_DEMOTED_STR
    except (ImportError, AttributeError):
        pass


# --------------------------------------------------------------------------
# Extract the D2 consumer block from coordinator.py.
# Mirrors test_ble_extend_not_create.py's extract-and-exec pattern.
# --------------------------------------------------------------------------

_HERE = Path(__file__).parent
_COORD_SRC = (
    _HERE.parent.parent
    / "custom_components"
    / "universal_room_automation"
    / "coordinator.py"
)

_BLOCK_START = "        # === mmWave fan-corroboration Tier-3 D2 — DEMOTION consumer ==="
_BLOCK_END = "        # Always populate ble_persons even when occupied by other sources"


def _extract_d2_block_source() -> str:
    src = _COORD_SRC.read_text(encoding="utf-8")
    assert _BLOCK_START in src, (
        "D2 block start delimiter missing from coordinator.py — "
        "the wrapper site was removed/renamed (mutation anchor)"
    )
    assert _BLOCK_END in src, "D2 block end delimiter missing"
    i = src.index(_BLOCK_START)
    j = src.index(_BLOCK_END, i)
    block = src[i:j]
    # Block sits at 8-space indent inside `_async_update_data`; dedent.
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


_D2_BLOCK_SRC = _extract_d2_block_source()
_D2_BLOCK_CODE = compile(_D2_BLOCK_SRC, str(_COORD_SRC), "exec")


# B-1 fix-up: sustained-production default for the positive test.
# _occupancy_first_detected is set on entry and retained for the WHOLE
# sustained hold — so the production shape D2 must fire against is a
# stamp hours in the past (debounce closed long ago), NOT None.
_SUSTAINED_STAMP = datetime(2000, 1, 1, tzinfo=timezone.utc)


class _FakeSelf:
    """Minimal fake for the attributes the D2 block reads / writes."""

    def __init__(
        self,
        hass,
        occupancy_timeout: int,
        last_pir_motion_time=None,
        boot_settle: bool = True,
        occupancy_first_detected=_SUSTAINED_STAMP,
        motion_sensors_present: bool = True,
        house_state_allows: bool = True,
        debounce_seconds: float = 5.0,
        fan_hold_active: bool = False,
    ):
        self.hass = hass
        self._occupancy_timeout = occupancy_timeout
        self._last_pir_motion_time = last_pir_motion_time
        self._last_motion_time = last_pir_motion_time  # not-None default
        self._became_occupied_time = None
        self._last_occupied_state = True
        self._last_occupied_since_for_handler = None
        self._mmwave_fan_demoted_last_tick = False
        self._mmwave_fan_demoted_since = None
        self._mmwave_fan_demotions_since_boot = 0
        self._mmwave_demoted_latch = False
        self._occupancy_first_detected = occupancy_first_detected
        self._occupancy_debounce_seconds = debounce_seconds
        self._boot_settle = boot_settle
        self._motion_sensors_present = motion_sensors_present
        self._house_state_allows = house_state_allows
        self._fan_hold_active = fan_hold_active
        # entry.data.get(...) parity for logging paths.

        class _E:
            data = {"room_name": "TestRoom"}
        self.entry = _E()

    def _d2_boot_settle_done(self) -> bool:
        return self._boot_settle

    def _d2_debounce_elapsed(self, now) -> bool:
        if self._occupancy_first_detected is None:
            return True
        try:
            return (
                now - self._occupancy_first_detected
            ).total_seconds() >= self._occupancy_debounce_seconds
        except Exception:  # noqa: BLE001
            return True

    def _d2_motion_sensors_present(self) -> bool:
        return self._motion_sensors_present

    def _d2_house_state_allows(self) -> bool:
        return self._house_state_allows


def _run_d2_block(
    self_obj: _FakeSelf,
    data: dict,
    now: datetime,
    room_name: str,
    *,
    enabled_override: bool | None = None,
    multiplier_override: int | None = None,
) -> None:
    ns = {
        "self": self_obj,
        "data": data,
        "now": now,
        "room_name": room_name,
        "DOMAIN": DOMAIN,
        "STATE_OCCUPIED": STATE_OCCUPIED,
        "STATE_OCCUPANCY_SOURCE": STATE_OCCUPANCY_SOURCE,
        "STATE_TIMEOUT_REMAINING": STATE_TIMEOUT_REMAINING,
        "OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED": OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED,
        "MMWAVE_FAN_CORROBORATION_ENABLED": (
            enabled_override if enabled_override is not None
            else MMWAVE_FAN_CORROBORATION_ENABLED
        ),
        "D2_PIR_STALENESS_MULTIPLIER": (
            multiplier_override if multiplier_override is not None
            else D2_PIR_STALENESS_MULTIPLIER
        ),
        "SIGNAL_MMWAVE_FAN_DEMOTED": _SIGNAL_MMWAVE_FAN_DEMOTED_STR,
        "async_dispatcher_send": lambda hass, sig, payload=None: (
            _dispatched.append((sig, payload))
        ),
        "_LOGGER": logging.getLogger("d2_block_test"),
    }
    exec(_D2_BLOCK_CODE, ns)


_dispatched: list[tuple[str, Any]] = []


def _reset_dispatched() -> None:
    _dispatched.clear()


def _seed_presence(
    hass,
    *,
    demoted_rooms: set[str],
    recheck_state: str = "idle",
    fan_on_since: datetime | None = None,
    fan_hold_until: datetime | None = None,
):
    presence = MagicMock()
    presence.is_room_mmwave_fan_demoted = MagicMock(
        side_effect=lambda r: r in demoted_rooms,
    )
    tracker = MagicMock()
    tracker._fan_on_since = {}
    tracker._fan_interference_hold_until = {}
    if fan_on_since is not None:
        for r in demoted_rooms:
            tracker._fan_on_since[r] = fan_on_since
    if fan_hold_until is not None:
        for r in demoted_rooms:
            tracker._fan_interference_hold_until[r] = fan_hold_until
    tracker._room_occupied = {r: True for r in demoted_rooms}
    presence.tracker_for_room = MagicMock(return_value=tracker)
    fr_mgr = MagicMock()
    fr_mgr.get_room_state = MagicMock(return_value=recheck_state)
    presence._fan_recheck_manager = fr_mgr
    manager = MagicMock()
    manager.coordinators = {"presence": presence}
    hass.data[DOMAIN] = {"coordinator_manager": manager}
    return presence


# --------------------------------------------------------------------------
# T2 — Study A repro: all four legs met -> demotes
# --------------------------------------------------------------------------


def test_studya_repro_all_legs_met_demotes():
    """Study A shape: mmwave-sole hold, fan on > grace, PIR stale, no BLE,
    boot-settled, no recheck in-flight -> demotion fires with the right
    source string and dispatches _SIGNAL_MMWAVE_FAN_DEMOTED_STR."""
    _reset_dispatched()
    hass = make_hass()
    room = "Study A"
    now = datetime(2026, 7, 31, 19, 45, 0, tzinfo=timezone.utc)
    # PIR stale by construction: last PIR = 3 * timeout ago.
    pir_stale_time = now - timedelta(seconds=3 * 60)
    coord = _FakeSelf(
        hass, occupancy_timeout=60,
        last_pir_motion_time=pir_stale_time,
    )
    fan_on_since = now - timedelta(seconds=700)  # > 600s grace
    _seed_presence(hass, demoted_rooms={room}, fan_on_since=fan_on_since)

    data = {
        STATE_OCCUPIED: True,
        STATE_OCCUPANCY_SOURCE: "mmwave",
    }
    _run_d2_block(coord, data, now, room)

    assert data[STATE_OCCUPIED] is False, (
        "All four D2 legs met but the room did not demote — "
        "Invariant M leak"
    )
    assert data[STATE_OCCUPANCY_SOURCE] == OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED
    assert data[STATE_TIMEOUT_REMAINING] == 0
    assert coord._mmwave_fan_demoted_last_tick is True
    assert coord._mmwave_fan_demotions_since_boot == 1
    assert coord._last_motion_time is None
    # Signal dispatched with the payload contract from planning §D2.
    assert any(sig == _SIGNAL_MMWAVE_FAN_DEMOTED_STR for sig, _ in _dispatched)
    sig, payload = next(
        (s, p) for s, p in _dispatched if s == _SIGNAL_MMWAVE_FAN_DEMOTED_STR
    )
    assert payload["room_name"] == room
    assert payload["reason"] == "mmwave_sole_fan_on_no_corroboration"
    assert payload["fan_on_since"] is not None
    assert payload["last_pir_motion_time"] is not None


# --------------------------------------------------------------------------
# T3 — Each leg individually BLOCKS demotion (per-leg guards)
# --------------------------------------------------------------------------


def test_no_demote_when_source_is_ble():
    """OCCUPANCY_SOURCE=='ble' means BLE-corroborated — must not demote."""
    _reset_dispatched()
    hass = make_hass()
    room = "Study A"
    now = datetime(2026, 7, 31, 19, 45, 0, tzinfo=timezone.utc)
    coord = _FakeSelf(
        hass, occupancy_timeout=60,
        last_pir_motion_time=now - timedelta(seconds=3 * 60),
    )
    _seed_presence(
        hass, demoted_rooms={room},
        fan_on_since=now - timedelta(seconds=700),
    )
    data = {STATE_OCCUPIED: True, STATE_OCCUPANCY_SOURCE: "ble"}
    _run_d2_block(coord, data, now, room)
    assert data[STATE_OCCUPIED] is True
    assert data[STATE_OCCUPANCY_SOURCE] == "ble"
    assert coord._mmwave_fan_demoted_last_tick is False


def test_no_demote_when_pir_motion_recent():
    """PIR motion within MULT*timeout — leg (e) blocks demotion."""
    _reset_dispatched()
    hass = make_hass()
    room = "Study A"
    now = datetime(2026, 7, 31, 19, 45, 0, tzinfo=timezone.utc)
    # PIR just fired 30s ago, well under MULT (2) * timeout (60) = 120s.
    coord = _FakeSelf(
        hass, occupancy_timeout=60,
        last_pir_motion_time=now - timedelta(seconds=30),
    )
    _seed_presence(
        hass, demoted_rooms={room},
        fan_on_since=now - timedelta(seconds=700),
    )
    data = {STATE_OCCUPIED: True, STATE_OCCUPANCY_SOURCE: "mmwave"}
    _run_d2_block(coord, data, now, room)
    assert data[STATE_OCCUPIED] is True
    assert data[STATE_OCCUPANCY_SOURCE] == "mmwave"
    assert coord._mmwave_fan_demoted_last_tick is False


def test_no_demote_when_presence_says_not_demoted():
    """Presence's is_room_mmwave_fan_demoted returns False (e.g. BLE
    person present, or fan-on grace not yet elapsed) — no demotion."""
    _reset_dispatched()
    hass = make_hass()
    room = "Study A"
    now = datetime(2026, 7, 31, 19, 45, 0, tzinfo=timezone.utc)
    coord = _FakeSelf(
        hass, occupancy_timeout=60,
        last_pir_motion_time=now - timedelta(seconds=3 * 60),
    )
    _seed_presence(hass, demoted_rooms=set())  # presence says NO
    data = {STATE_OCCUPIED: True, STATE_OCCUPANCY_SOURCE: "mmwave"}
    _run_d2_block(coord, data, now, room)
    assert data[STATE_OCCUPIED] is True


def test_no_demote_when_recheck_in_flight():
    """Fan-recheck is armed/paused for the room — recheck gets first
    crack. D2 defers so the two mechanisms don't fight (per plan)."""
    _reset_dispatched()
    hass = make_hass()
    room = "Study A"
    now = datetime(2026, 7, 31, 19, 45, 0, tzinfo=timezone.utc)
    coord = _FakeSelf(
        hass, occupancy_timeout=60,
        last_pir_motion_time=now - timedelta(seconds=3 * 60),
    )
    _seed_presence(
        hass, demoted_rooms={room},
        fan_on_since=now - timedelta(seconds=700),
        recheck_state="armed",
    )
    data = {STATE_OCCUPIED: True, STATE_OCCUPANCY_SOURCE: "mmwave"}
    _run_d2_block(coord, data, now, room)
    assert data[STATE_OCCUPIED] is True
    assert coord._mmwave_fan_demoted_last_tick is False


def test_no_demote_when_in_debounce():
    """Room is inside occupancy_debounce (occupancy_first_detected set)
    — demotion must not fire mid-debounce."""
    _reset_dispatched()
    hass = make_hass()
    room = "Study A"
    now = datetime(2026, 7, 31, 19, 45, 0, tzinfo=timezone.utc)
    coord = _FakeSelf(
        hass, occupancy_timeout=60,
        last_pir_motion_time=now - timedelta(seconds=3 * 60),
        occupancy_first_detected=now - timedelta(seconds=2),
    )
    _seed_presence(
        hass, demoted_rooms={room},
        fan_on_since=now - timedelta(seconds=700),
    )
    data = {STATE_OCCUPIED: True, STATE_OCCUPANCY_SOURCE: "mmwave"}
    _run_d2_block(coord, data, now, room)
    assert data[STATE_OCCUPIED] is True
    assert coord._mmwave_fan_demoted_last_tick is False


def test_no_demote_before_boot_settle():
    """Boot-settle not done — D2 fails safe (does not fire)."""
    _reset_dispatched()
    hass = make_hass()
    room = "Study A"
    now = datetime(2026, 7, 31, 19, 45, 0, tzinfo=timezone.utc)
    coord = _FakeSelf(
        hass, occupancy_timeout=60,
        last_pir_motion_time=now - timedelta(seconds=3 * 60),
        boot_settle=False,
    )
    _seed_presence(
        hass, demoted_rooms={room},
        fan_on_since=now - timedelta(seconds=700),
    )
    data = {STATE_OCCUPIED: True, STATE_OCCUPANCY_SOURCE: "mmwave"}
    _run_d2_block(coord, data, now, room)
    assert data[STATE_OCCUPIED] is True
    assert coord._mmwave_fan_demoted_last_tick is False


# --------------------------------------------------------------------------
# T4 — Kill switches
# --------------------------------------------------------------------------


def test_kill_switch_disabled_never_demotes():
    """MMWAVE_FAN_CORROBORATION_ENABLED=False -> byte-identical no-op."""
    _reset_dispatched()
    hass = make_hass()
    room = "Study A"
    now = datetime(2026, 7, 31, 19, 45, 0, tzinfo=timezone.utc)
    coord = _FakeSelf(
        hass, occupancy_timeout=60,
        last_pir_motion_time=now - timedelta(seconds=3 * 60),
    )
    _seed_presence(
        hass, demoted_rooms={room},
        fan_on_since=now - timedelta(seconds=700),
    )
    data = {STATE_OCCUPIED: True, STATE_OCCUPANCY_SOURCE: "mmwave"}
    _run_d2_block(coord, data, now, room, enabled_override=False)
    assert data[STATE_OCCUPIED] is True
    assert data[STATE_OCCUPANCY_SOURCE] == "mmwave"
    assert coord._mmwave_fan_demoted_last_tick is False
    assert coord._mmwave_fan_demotions_since_boot == 0


def test_mult_zero_disables_via_derived_kill_switch():
    """D2_PIR_STALENESS_MULTIPLIER=0 -> outer guard closes D2 (kill switch)."""
    _reset_dispatched()
    hass = make_hass()
    room = "Study A"
    now = datetime(2026, 7, 31, 19, 45, 0, tzinfo=timezone.utc)
    coord = _FakeSelf(
        hass, occupancy_timeout=60,
        last_pir_motion_time=now - timedelta(seconds=3 * 60),
    )
    _seed_presence(
        hass, demoted_rooms={room},
        fan_on_since=now - timedelta(seconds=700),
    )
    data = {STATE_OCCUPIED: True, STATE_OCCUPANCY_SOURCE: "mmwave"}
    _run_d2_block(coord, data, now, room, multiplier_override=0)
    assert data[STATE_OCCUPIED] is True
    assert coord._mmwave_fan_demoted_last_tick is False


# --------------------------------------------------------------------------
# T5 — Presence wrapper predicate: fan-on grace gate (Invariant M leg (b))
# --------------------------------------------------------------------------


def test_presence_wrapper_fan_on_since_below_grace_not_demoted():
    """The presence-side wrapper is a pure predicate: if fan_on_since
    < grace, room is NOT in the demoted set even though the primitive
    flagged it."""
    # Direct-import test on the wrapper — bypasses the full presence
    # coordinator setup by driving the method on a lightweight fake.
    from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E501, PLC0415
        presence as presence_mod,
    )
    # Wrapper uses the ``dt_util`` reference bound at presence.py
    # module-import time. Sibling test bootstraps sometimes replace
    # ``sys.modules["homeassistant.util.dt"]`` mid-run, so re-importing
    # here can yield a DIFFERENT utcnow (naive vs tz-aware) than
    # presence.py's cached reference. Source ``now`` from the SAME
    # object presence.py holds — the only mismatch-proof anchor.
    from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E501, PLC0415
        presence as _pmod,
    )
    now = _pmod.dt_util.utcnow()
    room = "Study A"

    # Fake tracker with the room and a young fan-on stamp (100s < 600s).
    class _FakeTracker:
        def __init__(self):
            self.room_names = {room}
            self._fan_on_since = {room: now - timedelta(seconds=100)}

    class _FakePresence:
        _zone_trackers = {"zone_1": _FakeTracker()}

        def _compute_fan_interference_rooms(self):
            return [room]

    fake = _FakePresence()
    # Bind the real method to the fake — mutation-anchored.
    demoted = presence_mod.PresenceCoordinator._compute_mmwave_fan_demoted_rooms(
        fake,
    )
    assert room not in demoted, (
        "fan_on_since below grace must NOT admit to demoted set"
    )
    # And past grace — same fake, older stamp — admits.
    fake._zone_trackers["zone_1"]._fan_on_since[room] = (
        now - timedelta(seconds=int(MMWAVE_FAN_CORROBORATION_GRACE_S) + 5)
    )
    demoted2 = presence_mod.PresenceCoordinator._compute_mmwave_fan_demoted_rooms(
        fake,
    )
    assert room in demoted2


def test_presence_wrapper_kill_switch_returns_empty(monkeypatch):
    from custom_components.universal_room_automation.domain_coordinators import (  # noqa: PLC0415
        presence as presence_mod,
    )
    from custom_components.universal_room_automation import const as const_mod

    monkeypatch.setattr(
        const_mod, "MMWAVE_FAN_CORROBORATION_ENABLED", False, raising=True,
    )

    class _FakePresence:
        _zone_trackers = {}

        def _compute_fan_interference_rooms(self):
            raise AssertionError("kill switch must short-circuit")

    fake = _FakePresence()
    demoted = presence_mod.PresenceCoordinator._compute_mmwave_fan_demoted_rooms(
        fake,
    )
    assert demoted == set()


# --------------------------------------------------------------------------
# T6 — Mutation anchor: source delimiters exist (Reviewer-C protection)
# --------------------------------------------------------------------------


def test_mutation_anchor_delimiters_present_in_coordinator():
    """If the D2 consumer block is deleted or renamed, extraction fails
    — this is the mutation-anchor test that turns red when a reviewer
    neuters the site."""
    src = _COORD_SRC.read_text(encoding="utf-8")
    assert _BLOCK_START in src
    assert _BLOCK_END in src
    # And the block must contain the load-bearing writes — a neutered
    # block that just `pass`es would still keep the delimiters, but
    # would remove these authoritative assignments.
    body = src[src.index(_BLOCK_START):src.index(_BLOCK_END, src.index(_BLOCK_START))]
    assert "OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED" in body, (
        "D2 block no longer writes the demotion source string — "
        "neutered site detected"
    )
    assert "is_room_mmwave_fan_demoted" in body, (
        "D2 block no longer consults the presence-side wrapper"
    )
    assert "get_room_state" in body, (
        "D2 block no longer honours the recheck-in-flight guard"
    )
    # A-CRIT-1 / B-1 mutation anchor: the debounce-elapsed helper MUST
    # gate the block. If a reviewer regresses to `is None` on
    # occupancy_first_detected, this assert catches it.
    assert "_d2_debounce_elapsed" in body, (
        "D2 gate reverted to occupancy_first_detected is None — "
        "sustained-hold scenario would never demote"
    )
    # D-HIGH-1: motion_sensors-present guard mutation anchor.
    assert "_d2_motion_sensors_present" in body, (
        "D2 no longer fails-closed when the room has no PIR sensors"
    )
    # D-CRIT-1: sleep-family guard mutation anchor.
    assert "_d2_house_state_allows" in body, (
        "D2 no longer skips demotion during SLEEP / WAKING / HOME_NIGHT"
    )
    # B-2 / D-HIGH-2: interference-hold precedence mutation anchor.
    assert "_fan_interference_hold_until" in body, (
        "D2 no longer defers to the fan-interference HOLD"
    )
    # B + C: flap-protection latch set-site anchor.
    assert "_mmwave_demoted_latch" in body, (
        "D2 no longer sets the flap-protection latch"
    )


# --------------------------------------------------------------------------
# NEW — Fix #1 mutation drill: the debounce guard is load-bearing
# --------------------------------------------------------------------------


def test_positive_demote_uses_sustained_production_state():
    """B-1: the fixture default MUST be the sustained-production shape
    (occupancy_first_detected set to a stamp hours ago), not None.
    Neutering the debounce guard (making it always False) blocks the
    demotion — proves the guard is load-bearing on the production shape."""
    _reset_dispatched()
    hass = make_hass()
    room = "TestRoom"
    now = datetime(2026, 7, 31, 19, 45, 0, tzinfo=timezone.utc)
    coord = _FakeSelf(
        hass, occupancy_timeout=60,
        last_pir_motion_time=now - timedelta(seconds=3 * 60),
    )
    # Confirm the fixture is on the production sustained shape.
    assert coord._occupancy_first_detected is _SUSTAINED_STAMP
    _seed_presence(
        hass, demoted_rooms={room},
        fan_on_since=now - timedelta(seconds=700),
    )
    data = {STATE_OCCUPIED: True, STATE_OCCUPANCY_SOURCE: "mmwave"}
    _run_d2_block(coord, data, now, room)
    assert data[STATE_OCCUPIED] is False

    # Now neuter the debounce guard — mimics a reviewer regressing the
    # gate. Demotion MUST NOT fire.
    _reset_dispatched()
    coord2 = _FakeSelf(
        hass, occupancy_timeout=60,
        last_pir_motion_time=now - timedelta(seconds=3 * 60),
    )
    coord2._d2_debounce_elapsed = lambda _now: False
    data2 = {STATE_OCCUPIED: True, STATE_OCCUPANCY_SOURCE: "mmwave"}
    _run_d2_block(coord2, data2, now, room)
    assert data2[STATE_OCCUPIED] is True, (
        "Neutering _d2_debounce_elapsed should block demotion — guard "
        "is not load-bearing"
    )


# --------------------------------------------------------------------------
# NEW — Fix #3: house-state sleep-family gate
# --------------------------------------------------------------------------


def test_no_demote_when_house_state_sleep_family():
    """D-CRIT-1: SLEEP / WAKING / HOME_NIGHT must block D2 at the
    consumer AND the primitive. Test the consumer gate here."""
    _reset_dispatched()
    hass = make_hass()
    room = "TestRoom"
    now = datetime(2026, 7, 31, 19, 45, 0, tzinfo=timezone.utc)
    coord = _FakeSelf(
        hass, occupancy_timeout=60,
        last_pir_motion_time=now - timedelta(seconds=3 * 60),
        house_state_allows=False,  # e.g. house is SLEEP
    )
    _seed_presence(
        hass, demoted_rooms={room},
        fan_on_since=now - timedelta(seconds=700),
    )
    data = {STATE_OCCUPIED: True, STATE_OCCUPANCY_SOURCE: "mmwave"}
    _run_d2_block(coord, data, now, room)
    assert data[STATE_OCCUPIED] is True
    assert coord._mmwave_fan_demoted_last_tick is False


def test_demote_when_house_state_home_day():
    """Complement: HOME_DAY (house_state_allows True) still demotes."""
    _reset_dispatched()
    hass = make_hass()
    room = "TestRoom"
    now = datetime(2026, 7, 31, 19, 45, 0, tzinfo=timezone.utc)
    coord = _FakeSelf(
        hass, occupancy_timeout=60,
        last_pir_motion_time=now - timedelta(seconds=3 * 60),
        house_state_allows=True,
    )
    _seed_presence(
        hass, demoted_rooms={room},
        fan_on_since=now - timedelta(seconds=700),
    )
    data = {STATE_OCCUPIED: True, STATE_OCCUPANCY_SOURCE: "mmwave"}
    _run_d2_block(coord, data, now, room)
    assert data[STATE_OCCUPIED] is False


# --------------------------------------------------------------------------
# NEW — Fix #4: no PIR motion sensors fails closed
# --------------------------------------------------------------------------


def test_no_demote_when_no_pir_motion_sensors():
    """D-HIGH-1: motion_sensors=[] (after MMWAVE_NAME_PATTERN filter)
    -> leg (e) unsatisfiable -> skip demotion (fail-closed)."""
    _reset_dispatched()
    hass = make_hass()
    room = "TestRoom"
    now = datetime(2026, 7, 31, 19, 45, 0, tzinfo=timezone.utc)
    coord = _FakeSelf(
        hass, occupancy_timeout=60,
        last_pir_motion_time=now - timedelta(seconds=3 * 60),
        motion_sensors_present=False,
    )
    _seed_presence(
        hass, demoted_rooms={room},
        fan_on_since=now - timedelta(seconds=700),
    )
    data = {STATE_OCCUPIED: True, STATE_OCCUPANCY_SOURCE: "mmwave"}
    _run_d2_block(coord, data, now, room)
    assert data[STATE_OCCUPIED] is True
    assert coord._mmwave_fan_demoted_last_tick is False


# --------------------------------------------------------------------------
# NEW — Fix #5: fan-interference HOLD arbitrates before D2 (precedence)
# --------------------------------------------------------------------------


def test_demotes_despite_active_interference_hold_and_clears_it():
    """D-PRIME-CRIT-1: the D1 hold is re-stamped EVERY tick a room
    stays fan-suspect, so a defer-to-hold gate can never win in the
    sustained case (arbitration-level unreachability, same class as
    A-CRIT-1). Once D2's strictly-higher bar is met, D2 OUTRANKS the
    hold: it demotes AND atomically clears the room's hold entry.
    The zone-side _room_occupied view must STILL be unchanged
    (room-tier-only blast radius — sustained mmwave provenance keeps
    the zone view up regardless of the hold)."""
    _reset_dispatched()
    hass = make_hass()
    room = "TestRoom"
    now = datetime(2026, 7, 31, 19, 45, 0, tzinfo=timezone.utc)
    coord = _FakeSelf(
        hass, occupancy_timeout=60,
        last_pir_motion_time=now - timedelta(seconds=3 * 60),
    )
    presence = _seed_presence(
        hass, demoted_rooms={room},
        fan_on_since=now - timedelta(seconds=700),
        # Sustained-suspect shape: hold freshly re-stamped, well in
        # the future — exactly the state that permanently deferred
        # the pre-fix arbitration.
        fan_hold_until=now + timedelta(seconds=300),
    )
    tracker = presence.tracker_for_room(room)
    room_occupied_before = dict(tracker._room_occupied)
    data = {STATE_OCCUPIED: True, STATE_OCCUPANCY_SOURCE: "mmwave"}
    _run_d2_block(coord, data, now, room)
    # D2 wins: demoted despite the active hold.
    assert data[STATE_OCCUPIED] is False
    assert coord._mmwave_fan_demoted_last_tick is True
    # Hold entry atomically cleared for this room.
    assert room not in tracker._fan_interference_hold_until
    # Room-tier-only blast radius — zone-side view unchanged.
    assert dict(tracker._room_occupied) == room_occupied_before


# --------------------------------------------------------------------------
# NEW — Fix #6: multi-fan stamp survives one fan going off (Master
# Bedroom is a real 2-fan room, historical incident room)
# --------------------------------------------------------------------------


def test_handle_fan_change_multi_fan_stamp_survives():
    """A-MED-1 / B-3: _handle_fan_change on one fan going OFF must NOT
    clear _fan_on_since when another fan for the same room is still
    on. Both off -> stamp clears."""
    from custom_components.universal_room_automation.domain_coordinators import (  # noqa: PLC0415, E501
        presence as presence_mod,
    )
    room = "Master Bedroom"
    fan_a = "fan.mbr_a"
    fan_b = "fan.mbr_b"
    hass = make_hass()

    # Seed hass states: fan_a going off, fan_b still on.
    class _S:
        def __init__(self, state):
            self.state = state

    hass_state_map = {fan_b: _S("on")}

    def _get(entity_id):
        return hass_state_map.get(entity_id)
    hass.states.get = _get  # type: ignore[assignment]

    class _Tracker:
        def __init__(self):
            self.room_names = {room}
            self._fan_on_rooms = {room}
            self._fan_on_since = {room: datetime(
                2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc,
            )}
            self._fan_entity_to_room = {fan_a: room, fan_b: room}

    tracker = _Tracker()

    class _P:
        _zone_trackers = {"z": tracker}
        hass = None
    p = _P()
    p.hass = hass

    class _Ev:
        data = {
            "entity_id": fan_a,
            "new_state": _S("off"),
        }

    presence_mod.PresenceCoordinator._handle_fan_change(p, _Ev())
    assert room in tracker._fan_on_since, (
        "Stamp cleared while other fan still on — multi-fan regression"
    )
    assert room in tracker._fan_on_rooms

    # Now turn fan_b off too.
    hass_state_map[fan_b] = _S("off")

    class _Ev2:
        data = {
            "entity_id": fan_b,
            "new_state": _S("off"),
        }
    presence_mod.PresenceCoordinator._handle_fan_change(p, _Ev2())
    assert room not in tracker._fan_on_since
    assert room not in tracker._fan_on_rooms


# --------------------------------------------------------------------------
# NEW — Fix #7: snapshot contract — is_room_mmwave_fan_demoted reads
# the frozen per-tick snapshot, never calls the primitive live.
# --------------------------------------------------------------------------


def test_is_room_mmwave_fan_demoted_reads_snapshot_not_live():
    """D-HIGH-3: the accessor MUST read _mmwave_fan_demoted_snapshot
    and NEVER invoke _compute_mmwave_fan_demoted_rooms /
    _compute_fan_interference_rooms live."""
    from custom_components.universal_room_automation.domain_coordinators import (  # noqa: PLC0415, E501
        presence as presence_mod,
    )
    call_counter = {"n": 0}

    class _P:
        _mmwave_fan_demoted_snapshot = frozenset({"Study A"})

        def _compute_mmwave_fan_demoted_rooms(self):
            call_counter["n"] += 1
            return set()

        def _compute_fan_interference_rooms(self):  # pragma: no cover
            call_counter["n"] += 1
            return []

    p = _P()
    for _ in range(10):
        assert presence_mod.PresenceCoordinator.is_room_mmwave_fan_demoted(
            p, "Study A",
        )
        assert not presence_mod.PresenceCoordinator.is_room_mmwave_fan_demoted(
            p, "Nowhere",
        )
    assert call_counter["n"] == 0, (
        "Accessor invoked the primitive live — snapshot contract violated"
    )


# --------------------------------------------------------------------------
# NEW — Fix #2 latch semantics and mutation drill
# --------------------------------------------------------------------------


def test_positive_demote_sets_flap_latch():
    """After demotion, _mmwave_demoted_latch is True (blocks mmwave-sole
    from re-creating occupancy in the next tick)."""
    _reset_dispatched()
    hass = make_hass()
    room = "TestRoom"
    now = datetime(2026, 7, 31, 19, 45, 0, tzinfo=timezone.utc)
    coord = _FakeSelf(
        hass, occupancy_timeout=60,
        last_pir_motion_time=now - timedelta(seconds=3 * 60),
    )
    _seed_presence(
        hass, demoted_rooms={room},
        fan_on_since=now - timedelta(seconds=700),
    )
    data = {STATE_OCCUPIED: True, STATE_OCCUPANCY_SOURCE: "mmwave"}
    _run_d2_block(coord, data, now, room)
    assert coord._mmwave_demoted_latch is True


def test_flap_latch_clears_on_recovery_signals():
    """The _evaluate_mmwave_demoted_latch helper clears the latch on
    each recovery signal (mmwave off, PIR fire, BLE person, fan off)."""
    from custom_components.universal_room_automation.coordinator import (  # noqa: PLC0415
        UniversalRoomCoordinator,
    )

    class _Mini:
        class _E:
            data = {"room_name": "TestRoom"}
        entry = _E()

    def _mk(hass, latch=True):
        m = _Mini()
        m.hass = hass
        m._mmwave_demoted_latch = latch
        return m

    # (1) mmwave off: presence_detected=False -> clears.
    hass = make_hass()
    hass.data[DOMAIN] = {}
    m = _mk(hass)
    UniversalRoomCoordinator._evaluate_mmwave_demoted_latch(
        m, "TestRoom", motion_detected=False, presence_detected=False,
    )
    assert m._mmwave_demoted_latch is False

    # (2) PIR fire: motion_detected=True -> clears.
    m = _mk(hass)
    UniversalRoomCoordinator._evaluate_mmwave_demoted_latch(
        m, "TestRoom", motion_detected=True, presence_detected=True,
    )
    assert m._mmwave_demoted_latch is False

    # (3) BLE person arrives.
    person_coord = MagicMock()
    person_coord.get_persons_in_room = MagicMock(return_value=["Oji"])
    hass.data[DOMAIN] = {"person_coordinator": person_coord}
    m = _mk(hass)
    UniversalRoomCoordinator._evaluate_mmwave_demoted_latch(
        m, "TestRoom", motion_detected=False, presence_detected=True,
    )
    assert m._mmwave_demoted_latch is False

    # (4) Fan off (tracker._fan_on_since drops the room).
    person_coord2 = MagicMock()
    person_coord2.get_persons_in_room = MagicMock(return_value=[])
    tracker = MagicMock()
    tracker._fan_on_since = {}  # room absent -> fan off
    presence = MagicMock()
    presence.tracker_for_room = MagicMock(return_value=tracker)
    manager = MagicMock()
    manager.coordinators = {"presence": presence}
    hass.data[DOMAIN] = {
        "person_coordinator": person_coord2,
        "coordinator_manager": manager,
    }
    m = _mk(hass)
    UniversalRoomCoordinator._evaluate_mmwave_demoted_latch(
        m, "TestRoom", motion_detected=False, presence_detected=True,
    )
    assert m._mmwave_demoted_latch is False

    # (5) No recovery signal -> latch stays.
    tracker2 = MagicMock()
    tracker2._fan_on_since = {"TestRoom": datetime(
        2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc,
    )}
    presence2 = MagicMock()
    presence2.tracker_for_room = MagicMock(return_value=tracker2)
    manager2 = MagicMock()
    manager2.coordinators = {"presence": presence2}
    hass.data[DOMAIN] = {
        "person_coordinator": person_coord2,
        "coordinator_manager": manager2,
    }
    m = _mk(hass)
    UniversalRoomCoordinator._evaluate_mmwave_demoted_latch(
        m, "TestRoom", motion_detected=False, presence_detected=True,
    )
    assert m._mmwave_demoted_latch is True, (
        "No recovery signal but latch cleared — flap protection broken"
    )


# --------------------------------------------------------------------------
# NEW — Fix #7 companion + Fix #8: grace floor
# --------------------------------------------------------------------------


def test_wrapper_grace_floor_clamps_low_values(monkeypatch):
    """D-MED-2: values below 300s clamp to 300s in the wrapper."""
    from custom_components.universal_room_automation.domain_coordinators import (  # noqa: PLC0415, E501
        presence as presence_mod,
    )
    from custom_components.universal_room_automation import const as const_mod

    monkeypatch.setattr(
        const_mod, "MMWAVE_FAN_CORROBORATION_GRACE_S", 30, raising=True,
    )

    class _T:
        def __init__(self, room, stamp):
            self.room_names = {room}
            self._fan_on_since = {room: stamp}

    class _P:
        # 200s old — above the low 30 but BELOW the 300s floor.
        def __init__(self):
            from datetime import datetime as _dt, timezone as _tz  # noqa: PLC0415
            now = _dt.now(tz=_tz.utc)
            self.now = now
            self._zone_trackers = {"z": _T(
                "X", now - timedelta(seconds=200),
            )}

        def _compute_fan_interference_rooms(self):
            return ["X"]

    p = _P()
    demoted = presence_mod.PresenceCoordinator._compute_mmwave_fan_demoted_rooms(p)
    assert "X" not in demoted, "Sub-floor grace failed to clamp — leaked"
