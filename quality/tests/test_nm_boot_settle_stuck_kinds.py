"""STUCK-SENSOR-S3B-S1-1 residual (2026-11-16): NM boot-settle vs stuck kinds.

Live defect: a chatter stuck-signal NM 9 s after a dutycycle NM was collapsed
by the NM boot-settle window (key = (coord, hazard); every stuck kind shares
one hazard_type), AND ``fire_stuck_signal`` still set the day latch, so the
chatter page stayed silent until the next day.

These tests drive the real ``NotificationManager.async_notify`` and the real
``fire_stuck_signal`` with the boot window open.
"""

from unittest.mock import AsyncMock

import pytest

# Bootstrap HA stubs by importing the sibling NM test module first.
from test_notification_manager import _make_hass, _make_config  # noqa: F401

from custom_components.universal_room_automation.const import DOMAIN
from custom_components.universal_room_automation.domain_coordinators import (
    _stuck_signal_nm as ssn,
)
from custom_components.universal_room_automation.domain_coordinators.base import (
    Severity,
)
from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
    NotificationManager,
)

# Literals on purpose (not the imported constants): a mutation of the
# constant must not move the oracle with it.
STUCK_COORD = "stuck_signal"
STUCK_HAZARD = "stuck_signal"


def _armed_nm():
    hass = _make_hass()
    nm = NotificationManager(hass, _make_config())
    nm._send_pushover = AsyncMock()
    # Boot-settle window unambiguously OPEN.
    nm._boot_settle_until = 10**15
    nm._boot_settle_seen.clear()
    hass.data[DOMAIN]["notification_manager"] = nm
    return hass, nm


@pytest.fixture(autouse=True)
def _clean_latches():
    ssn.reset_latches_for_tests()
    yield
    ssn.reset_latches_for_tests()


class TestBootSettleStuckKinds:
    @pytest.mark.asyncio
    async def test_dutycycle_then_chatter_in_boot_window_both_send(self):
        _hass, nm = _armed_nm()
        first = await nm.async_notify(
            STUCK_COORD, Severity.MEDIUM, "Stuck: dutycycle", "d",
            hazard_type=STUCK_HAZARD, location="dutycycle",
        )
        second = await nm.async_notify(
            STUCK_COORD, Severity.MEDIUM, "Stuck: chatter", "c",
            hazard_type=STUCK_HAZARD, location="chatter",
        )
        assert first is True
        assert second is True
        assert nm._send_pushover.await_count == 2

    @pytest.mark.asyncio
    async def test_same_stuck_kind_twice_in_boot_window_collapses(self):
        _hass, nm = _armed_nm()
        first = await nm.async_notify(
            STUCK_COORD, Severity.MEDIUM, "Stuck: chatter room A", "a",
            hazard_type=STUCK_HAZARD, location="chatter",
        )
        second = await nm.async_notify(
            STUCK_COORD, Severity.MEDIUM, "Stuck: chatter room B", "b",
            hazard_type=STUCK_HAZARD, location="chatter",
        )
        assert first is True
        assert second is False
        assert nm._send_pushover.await_count == 1

    @pytest.mark.asyncio
    async def test_other_hazard_varying_location_still_collapses(self):
        """Scope guard: location keys the window ONLY for stuck_signal.
        A per-room hazard from another coordinator still collapses."""
        _hass, nm = _armed_nm()
        first = await nm.async_notify(
            "hvac", Severity.MEDIUM, "Degraded: Kitchen", "k",
            hazard_type="hvac_degraded_room", location="Kitchen",
        )
        second = await nm.async_notify(
            "hvac", Severity.MEDIUM, "Degraded: Office", "o",
            hazard_type="hvac_degraded_room", location="Office",
        )
        assert first is True
        assert second is False
        assert nm._send_pushover.await_count == 1


class TestStuckLatchOnlyOnDelivery:
    @pytest.mark.asyncio
    async def test_dutycycle_then_chatter_fire_stuck_signal_both_latch(self):
        hass, nm = _armed_nm()
        ok1 = await ssn.fire_stuck_signal(
            hass, kind="dutycycle", key=("room_a",), diagnosis="d",
        )
        ok2 = await ssn.fire_stuck_signal(
            hass, kind="chatter", key=("room_a",), diagnosis="c",
        )
        assert ok1 is True and ok2 is True
        latches = ssn.latch_snapshot_for_tests()
        assert ("dutycycle", ("room_a",)) in latches
        assert ("chatter", ("room_a",)) in latches
        assert nm._send_pushover.await_count == 2

    @pytest.mark.asyncio
    async def test_boot_settle_dropped_stuck_nm_leaves_no_latch_then_sends(self):
        hass, nm = _armed_nm()
        ok1 = await ssn.fire_stuck_signal(
            hass, kind="chatter", key=("room_a",), diagnosis="a",
            title_override="Stuck signal: chatter (room_a)",
        )
        # Same kind, other room, inside the window -> collapsed by NM.
        ok2 = await ssn.fire_stuck_signal(
            hass, kind="chatter", key=("room_b",), diagnosis="b",
            title_override="Stuck signal: chatter (room_b)",
        )
        assert ok1 is True
        assert ok2 is False
        latches = ssn.latch_snapshot_for_tests()
        assert ("chatter", ("room_b",)) not in latches
        assert nm._send_pushover.await_count == 1

        # Window closes; the next tick re-offers room_b and it sends.
        nm._boot_settle_until = 0.0
        ok3 = await ssn.fire_stuck_signal(
            hass, kind="chatter", key=("room_b",), diagnosis="b",
            title_override="Stuck signal: chatter (room_b)",
        )
        assert ok3 is True
        assert ("chatter", ("room_b",)) in ssn.latch_snapshot_for_tests()
        assert nm._send_pushover.await_count == 2

    @pytest.mark.asyncio
    async def test_fire_stuck_signal_ex_reports_not_sent_on_boot_drop(self):
        hass, _nm = _armed_nm()
        assert await ssn.fire_stuck_signal_ex(
            hass, kind="chatter", key=("room_a",), diagnosis="a",
            title_override="Stuck signal: chatter (room_a)",
        ) == ssn.SENT
        assert await ssn.fire_stuck_signal_ex(
            hass, kind="chatter", key=("room_b",), diagnosis="b",
            title_override="Stuck signal: chatter (room_b)",
        ) == ssn.NOT_SENT
        assert not ssn.stuck_signal_notified("chatter", ("room_b",))
