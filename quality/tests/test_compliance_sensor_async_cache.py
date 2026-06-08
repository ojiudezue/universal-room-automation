"""Regression guard for the compliance-sensor async-cache fix (#2, v4.7.30).

PresenceComplianceSensor / SafetyComplianceSensor used to call the async
``get_compliance_rate`` DAO from a SYNC ``native_value`` property without
awaiting it — so it returned an un-awaited coroutine, ``rate * 100`` raised
TypeError, the ``except`` swallowed it, and the sensor silently reported a
hardcoded 100.0 (plus a RuntimeWarning every poll). The fix moves the await
into ``async_update`` and has ``native_value`` return a cached value.

This test extracts the REAL ``native_value`` + ``async_update`` bodies from
sensor.py source and drives them (Bug Class #44 fixture authority), so a future
refactor that reverts ``native_value`` to compute synchronously — or drops the
await — fails loudly.
"""

from __future__ import annotations

import os
import re
import asyncio
import logging
import types
from unittest.mock import MagicMock, AsyncMock

import pytest

_SENSOR_PY = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation", "sensor.py",
)
_DOMAIN = "universal_room_automation"


def _extract_methods(class_name: str):
    """Extract native_value + async_update from a sensor class as callables."""
    with open(_SENSOR_PY, "r") as fh:
        src = fh.read()
    cls_at = src.index(f"class {class_name}(")
    # native_value property: strip the @property decorator, exec the def.
    nv_def = src.index("    def native_value(", cls_at)
    nv_end = src.index("\n    async def async_update(", nv_def)
    nv_src = src[nv_def:nv_end]
    au_def = src.index("    async def async_update(", cls_at)
    # async_update runs until the next top-level construct (blank line + class/comment).
    au_end = src.index("\n\n\n", au_def)
    au_src = src[au_def:au_end]

    def _dedent(s: str) -> str:
        return "\n".join(l[4:] if len(l) >= 4 else l for l in s.splitlines()) + "\n"

    g: dict = {"DOMAIN": _DOMAIN, "_LOGGER": logging.getLogger("test.compliance")}
    exec(compile(_dedent(nv_src), "<native_value>", "exec"), g)
    exec(compile(_dedent(au_src), "<async_update>", "exec"), g)
    return g["native_value"], g["async_update"]


def _fake_self(rate, coordinator_key: str):
    obj = MagicMock()
    tracker = MagicMock()
    tracker.get_compliance_rate = AsyncMock(return_value=rate)
    coord = MagicMock()
    coord.compliance_tracker = tracker
    manager = MagicMock()
    manager.coordinators = {coordinator_key: coord}
    obj.hass.data = {_DOMAIN: {"coordinator_manager": manager}}
    return obj, tracker


@pytest.mark.parametrize(
    "class_name,key",
    [("PresenceComplianceSensor", "presence"), ("SafetyComplianceSensor", "safety")],
)
class TestComplianceSensorAsyncCache:
    def test_native_value_defaults_before_first_update(self, class_name, key):
        native_value, _ = _extract_methods(class_name)
        obj = MagicMock(spec=[])  # no _compliance_value attr
        assert native_value(obj) == 100.0

    def test_async_update_awaits_and_caches(self, class_name, key):
        native_value, async_update = _extract_methods(class_name)
        obj, tracker = _fake_self(0.873, key)
        asyncio.run(async_update(obj))
        tracker.get_compliance_rate.assert_awaited_once_with(key)
        assert obj._compliance_value == 87.3
        assert native_value(obj) == 87.3

    def test_native_value_returns_cache_not_live(self, class_name, key):
        # After caching, native_value must NOT re-query (proves it's a cache read).
        native_value, async_update = _extract_methods(class_name)
        obj, tracker = _fake_self(0.50, key)
        asyncio.run(async_update(obj))
        assert native_value(obj) == 50.0
        # Mutate the tracker; native_value must still return the cached value.
        tracker.get_compliance_rate = AsyncMock(return_value=0.99)
        assert native_value(obj) == 50.0

    def test_async_update_noop_when_manager_missing(self, class_name, key):
        native_value, async_update = _extract_methods(class_name)
        obj = MagicMock(spec=["hass"])
        obj.hass.data = {}
        asyncio.run(async_update(obj))  # must not raise
        assert native_value(MagicMock(spec=[])) == 100.0
