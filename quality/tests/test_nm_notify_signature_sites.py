"""NM-SIGNATURE (2026-10-20): per-site behavioural anchors that each fixed
``nm.async_notify`` call site binds to the REAL
``NotificationManager.async_notify`` signature.

The fake NM binds every call with ``inspect.signature`` of the production
method — an unknown kwarg, a missing ``coordinator_id``, or a missing
``severity`` raises TypeError exactly as production did, and the test
asserts the notification actually arrived (bind succeeded) with an enum
severity.

Sites (each mutation-drilled — revert the fix → the named test goes RED):
  - presence.py  _emit_wake_backstop_anomaly
        → test_wake_backstop_notify_binds_real_signature
  - (binary_sensor.py OccupancyAnomalyBinarySensor NM site DELETED by
    BAYES-OCCUPANCY-ANOMALY-NEVER-EVALUATES-1, operator ruling "no alert";
    its no-notify invariant is pinned by
    test_occupancy_anomaly_dwell.py::test_no_notification_on_rising_edge)
  - optimization.py _notify_if_severe (event_class/dedup_key kwargs)
        → test_optimizer_notify_binds_on_first_call
  - button.py SendTestPerimeterAlertButton (route_reason kwarg; fixed by
    adding ``route_reason`` to NM.async_notify)
        → test_perimeter_test_button_notify_binds_real_signature
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Order-hardening: let the NM harness module install its HA bindings
# BEFORE notification_manager is first imported (same pattern as
# test_nm_image_delivery.py). Importing NM first otherwise binds the real
# dt_util and breaks two time-sensitive tests in test_notification_manager.
import test_notification_manager  # noqa: F401,E402

from custom_components.universal_room_automation.domain_coordinators.base import (
    Severity,
)
from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
    NotificationManager,
)

DOMAIN = "universal_room_automation"


class _BindingNM:
    """Fake NM whose async_notify enforces the production signature."""

    def __init__(self) -> None:
        self.enabled = True
        self.bound: list[inspect.BoundArguments] = []
        self._sig = inspect.signature(NotificationManager.async_notify)

    async def async_notify(self, *args, **kwargs):
        ba = self._sig.bind(self, *args, **kwargs)  # TypeError on mismatch
        ba.apply_defaults()
        self.bound.append(ba)


def _assert_single_enum_call(nm: _BindingNM, coordinator_id: str, sev: Severity):
    assert len(nm.bound) == 1, f"expected one bound notify, got {len(nm.bound)}"
    a = nm.bound[0].arguments
    assert a["coordinator_id"] == coordinator_id
    # Compare by enum name + int value: sibling test files purge/reimport
    # the package, so class identity is not stable across orderings.
    got = a["severity"]
    assert not isinstance(got, str), f"str severity {got!r} (enum expected)"
    assert type(got).__name__ == "Severity", type(got)
    assert (got.name, int(got)) == (sev.name, int(sev))


# ---------------------------------------------------------------------------
# presence.py — wake-backstop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wake_backstop_notify_binds_real_signature():
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )

    nm = _BindingNM()
    loop = asyncio.get_running_loop()
    tasks: list[asyncio.Task] = []

    def _create_task(coro):
        t = loop.create_task(coro)
        tasks.append(t)
        return t

    pc = PresenceCoordinator.__new__(PresenceCoordinator)
    pc.hass = SimpleNamespace(
        data={DOMAIN: {"notification_manager": nm}},
        async_create_task=_create_task,
    )
    pc.coordinator_id = "presence"
    pc._wake_backstop_notified_on = None
    pc._census_count = 2

    pc._emit_wake_backstop_anomaly(10, "backstop")
    assert len(tasks) == 1
    await tasks[0]  # raises TypeError if the call doesn't bind

    _assert_single_enum_call(nm, "presence", Severity.MEDIUM)
    assert "wake-backstop" in nm.bound[0].arguments["title"]


# ---------------------------------------------------------------------------
# optimization.py — _notify_if_severe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optimizer_notify_binds_on_first_call():
    from custom_components.universal_room_automation.domain_coordinators.optimization import (
        OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
    )

    nm = _BindingNM()
    attempts = 0
    _real = nm.async_notify

    async def _counting(*a, **kw):
        nonlocal attempts
        attempts += 1
        await _real(*a, **kw)

    nm.async_notify = _counting
    coord = OptimizationCoordinator.__new__(OptimizationCoordinator)
    coord.hass = SimpleNamespace(data={DOMAIN: {"notification_manager": nm}})
    coord._notify_dedup_state = {}
    coord._notify_dedup_just_set = set()
    f = OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=OptimizationDimension.SENSOR_HEALTH,
        severity="critical", confidence=0.95, score=0.0,
        description="x",
        payload={},
        dedup_key=("sig_test", "house"),
    )
    await coord._notify_if_severe(f)
    assert attempts == 1, (
        f"first async_notify call must bind (no TypeError fallback); "
        f"attempts={attempts}"
    )
    _assert_single_enum_call(nm, "optimization", Severity.CRITICAL)


# ---------------------------------------------------------------------------
# button.py — SendTestPerimeterAlertButton (route_reason)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_perimeter_test_button_notify_binds_real_signature():
    from custom_components.universal_room_automation import button as btn_mod
    from custom_components.universal_room_automation import const as _const

    nm = _BindingNM()

    async def _exec(fn, *a):
        return None  # no bundled snapshot

    b = btn_mod.SendTestPerimeterAlertButton.__new__(
        btn_mod.SendTestPerimeterAlertButton
    )
    b.hass = SimpleNamespace(
        data={DOMAIN: {"notification_manager": nm}},
        async_add_executor_job=_exec,
    )
    with patch(
        "custom_components.universal_room_automation.perimeter_enrichment."
        "enrich_dispatched_alert",
        AsyncMock(return_value="A person in a hoodie."),
    ):
        await b.async_press()
    _assert_single_enum_call(nm, "perimeter_alert_test", Severity.MEDIUM)
    assert nm.bound[0].arguments["route_reason"] == _const.NM_ROUTE_REASON_ENRICHED
