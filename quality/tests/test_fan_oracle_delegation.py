"""FAN-LAYER-1 Session 2 — RoomAutomation field-delegation tests.

The two RoomAutomation manual-hold fields (`_fan_manual_off_until`,
`_fan_manual_on_until`) are class-level ``@property`` descriptors
backed by ``FanPolicyOracle`` (PLAN §7.10 adopted as delegation per
Session-2 coordinator direction — state lives in ONE place).

These tests lock the contract:
  * setting either field via any call site (including the pre-existing
    27 assignment sites in automation.py) writes to the oracle ledger;
  * reading either field returns the oracle ledger value;
  * when the oracle is missing (hass.data has no "fan_oracle"), reads
    and writes fall back to a local ``__dict__`` slot so pre-oracle
    contexts keep working byte-identically;
  * ``mark_fan_on_issued`` additionally records an oracle actuation
    edge with source="ura" (feeds edges-only ledger per PLAN §7.14).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401

from custom_components.universal_room_automation.const import (
    DOMAIN,
    FAN_TRIGGER_TEMP_ROOM_ON,
)
from custom_components.universal_room_automation.domain_coordinators.fan_policy_oracle import (  # noqa: E501
    FanPolicyOracle,
)


ROOM = "TestRoom"


def _make_room(with_oracle: bool = True):
    """Fabricate a RoomAutomation-shaped stub bypassing heavy __init__.

    We use RoomAutomation's class object but don't call its __init__ —
    we only need the class-level @property descriptors + a couple of
    instance attributes (``hass``, ``config``). Same shape used in
    test_reconciler_fan_manual_on_guards for the same reason: __init__
    pulls in every URA subsystem, which we don't need for property
    contract tests.
    """
    from custom_components.universal_room_automation.automation import (  # noqa: E501
        RoomAutomation,
    )
    room = RoomAutomation.__new__(RoomAutomation)
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    if with_oracle:
        hass.data[DOMAIN]["fan_oracle"] = FanPolicyOracle(hass)
    room.hass = hass
    room.config = {"room_name": ROOM}
    return room, hass


def test_set_fan_manual_off_until_writes_to_oracle():
    room, hass = _make_room()
    oracle = hass.data[DOMAIN]["fan_oracle"]
    t = datetime(2026, 8, 10, 12, 0, 0)
    room._fan_manual_off_until = t + timedelta(minutes=30)
    assert oracle.get_state(ROOM).manual_off_cooldown_until == t + timedelta(minutes=30)


def test_get_fan_manual_off_until_reads_from_oracle():
    room, hass = _make_room()
    oracle = hass.data[DOMAIN]["fan_oracle"]
    t = datetime(2026, 8, 10, 12, 0, 0)
    # Prime the oracle directly, then read via the RoomAutomation property.
    oracle._get_record(ROOM).manual_off_cooldown_until = t
    assert room._fan_manual_off_until == t


def test_set_fan_manual_on_until_writes_to_oracle():
    room, hass = _make_room()
    oracle = hass.data[DOMAIN]["fan_oracle"]
    t = datetime(2026, 8, 10, 12, 0, 0) + timedelta(hours=1)
    room._fan_manual_on_until = t
    assert oracle.get_state(ROOM).manual_on_hold_until == t


def test_get_fan_manual_on_until_reads_from_oracle():
    room, hass = _make_room()
    oracle = hass.data[DOMAIN]["fan_oracle"]
    t = datetime(2026, 8, 10, 12, 0, 0) + timedelta(hours=1)
    oracle._get_record(ROOM).manual_on_hold_until = t
    assert room._fan_manual_on_until == t


def test_clear_field_by_setting_none_clears_oracle():
    room, hass = _make_room()
    oracle = hass.data[DOMAIN]["fan_oracle"]
    oracle._get_record(ROOM).manual_off_cooldown_until = datetime.now()
    room._fan_manual_off_until = None
    assert oracle.get_state(ROOM).manual_off_cooldown_until is None


def test_fallback_when_oracle_missing_uses_local_dict():
    """Without an oracle in hass.data, the property spills to __dict__."""
    room, _hass = _make_room(with_oracle=False)
    t = datetime(2026, 8, 10, 12, 0, 0)
    room._fan_manual_off_until = t
    # Round-trips via the __dict__ fallback.
    assert room._fan_manual_off_until == t
    assert room.__dict__["_fan_manual_off_until_local"] == t


def test_fallback_survives_oracle_disappearing_after_set():
    """Set with oracle live, then wipe hass.data — reads use fallback."""
    room, hass = _make_room()
    t = datetime(2026, 8, 10, 12, 0, 0)
    room._fan_manual_on_until = t
    # Simulate oracle going away (mid-lifecycle reload).
    hass.data[DOMAIN].pop("fan_oracle")
    # Setter cached to __dict__; reader falls back to it.
    assert room._fan_manual_on_until == t


def test_reads_are_none_safe_when_room_never_seen():
    room, _hass = _make_room()
    # A fresh oracle has never seen ROOM — returns empty ledger (None fields).
    assert room._fan_manual_off_until is None
    assert room._fan_manual_on_until is None


def test_mark_fan_on_issued_records_oracle_edge():
    room, hass = _make_room()
    oracle = hass.data[DOMAIN]["fan_oracle"]
    # Provide the fan-issued attribute mark_fan_on_issued expects to set.
    room._fan_on_issued_this_tick = False
    room._last_seen_any_fan_on = False
    from custom_components.universal_room_automation.automation import (  # noqa: E501,PLC0415
        RoomAutomation,
    )
    RoomAutomation.mark_fan_on_issued(room)
    assert room._fan_on_issued_this_tick is True
    assert room._last_seen_any_fan_on is True
    events = [e for e in oracle.actuation_events
              if e["room"] == ROOM and e["direction"] == "on"]
    assert len(events) == 1, events
    assert events[0]["trigger_path"] == FAN_TRIGGER_TEMP_ROOM_ON
    assert events[0]["source"] == "ura"


def test_mark_fan_on_issued_edges_only_second_call_within_hold_no_new_edge():
    """PLAN §7.14: repeat notes within same hold generation collapse."""
    room, hass = _make_room()
    oracle = hass.data[DOMAIN]["fan_oracle"]
    room._fan_on_issued_this_tick = False
    room._last_seen_any_fan_on = False
    from custom_components.universal_room_automation.automation import (  # noqa: E501,PLC0415
        RoomAutomation,
    )
    RoomAutomation.mark_fan_on_issued(room)
    n1 = len(oracle.actuation_events)
    RoomAutomation.mark_fan_on_issued(room)
    RoomAutomation.mark_fan_on_issued(room)
    # Same (room, trigger, hold_id=0) triple → still ONE edge.
    assert len(oracle.actuation_events) == n1


def test_mark_fan_on_issued_no_oracle_does_not_raise():
    room, _hass = _make_room(with_oracle=False)
    room._fan_on_issued_this_tick = False
    room._last_seen_any_fan_on = False
    from custom_components.universal_room_automation.automation import (  # noqa: E501,PLC0415
        RoomAutomation,
    )
    # Must not raise; fields still advance.
    RoomAutomation.mark_fan_on_issued(room)
    assert room._fan_on_issued_this_tick is True


def test_property_writes_are_visible_through_accessor_is_fan_in_manual_on_hold(monkeypatch):
    """The pre-existing accessor reads via the same delegated property.

    Setting `_fan_manual_on_until` via the setter must make
    `is_fan_in_manual_on_hold()` return True — proving the accessor
    now transparently reads oracle-backed state.

    We pin ``dt_util.now`` on the automation module so this test is
    resilient to pollution from tests that install MagicMock as the
    dt_util shim earlier in a full-suite run (accessor uses
    ``dt_util.now() < until`` for the window check).
    """
    from custom_components.universal_room_automation import automation as _auto  # noqa: PLC0415
    fixed_now = datetime(2026, 8, 10, 12, 0, 0)
    fake_dt = MagicMock()
    fake_dt.now = MagicMock(return_value=fixed_now)
    monkeypatch.setattr(_auto, "dt_util", fake_dt)
    room, _hass = _make_room()
    future = fixed_now + timedelta(minutes=10)
    room._fan_manual_on_until = future
    assert _auto.RoomAutomation.is_fan_in_manual_on_hold(room) is True
