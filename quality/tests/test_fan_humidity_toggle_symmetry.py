"""Fan/humidity toggle-symmetry cycle tests (2026-07-22).

Anchors the two load-bearing changes from
``docs/planning/AUDIT_fan_humidity_toggle_symmetry.md``:

D1 — HIGH F1 fix: ``CONF_FAN_CONTROL_ENABLED`` and
``CONF_HUMIDITY_FAN_CONTROL_ENABLED`` are in the ROOM-entry
``_ROOM_SUPPRESS_KEYS`` allowlist in ``__init__.py``. Without this,
every physical toggle of the room's Comfort/Humidity fan-control switch
mirrors the value into ``entry.options`` (switch.py ``_mirror_options``)
and the update-listener falls through to a full ~90-entity ROOM reload.

D2 — MEDIUM F2 fix: dual-source restore precedence in
``_RoomBooleanOptionSwitch.async_added_to_hass`` — options-flow value
wins over RestoreEntity when the key is present in entry.options.
Bug-Class-#52 guard (last_state.state must be "on"/"off") preserved.

Both tests are **mutation-anchored**: removing the fix from the
production source causes a SPECIFIC assertion here to fail.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

_ROOT = Path(__file__).parent.parent.parent
_INIT_PY = _ROOT / "custom_components" / "universal_room_automation" / "__init__.py"
_SWITCH_PY = _ROOT / "custom_components" / "universal_room_automation" / "switch.py"


# ---------------------------------------------------------------------------
# D1 — _ROOM_SUPPRESS_KEYS membership (static, mutation-anchored)
#
# Removing either key from the frozenset body must fail one of these
# assertions.  Mirrors the shape of test_zone_delete_flow.py::
# test_room_suppress_keys_includes_conf_zone.
# ---------------------------------------------------------------------------


def _extract_room_suppress_keys_body() -> str:
    text = _INIT_PY.read_text()
    m = re.search(
        r"_ROOM_SUPPRESS_KEYS:\s*frozenset\[str\]\s*=\s*frozenset\(\{(.*?)\}\)",
        text, re.DOTALL,
    )
    assert m is not None, "_ROOM_SUPPRESS_KEYS block not found in __init__.py"
    return m.group(1)


def test_room_suppress_keys_includes_fan_control_enabled():
    """D1 anchor: removing _CONF_FAN_CONTROL_ENABLED from the frozenset
    body must fail this test.  Guarantees a room-fan-control toggle does
    not full-reload the ROOM entry.
    """
    body = _extract_room_suppress_keys_body()
    assert "_CONF_FAN_CONTROL_ENABLED" in body, (
        "F1 fix reverted: _CONF_FAN_CONTROL_ENABLED missing from "
        f"_ROOM_SUPPRESS_KEYS body: {body!r}"
    )


def test_room_suppress_keys_includes_humidity_fan_control_enabled():
    """D1 anchor: removing _CONF_HUMIDITY_FAN_CONTROL_ENABLED from the
    frozenset body must fail this test.
    """
    body = _extract_room_suppress_keys_body()
    assert "_CONF_HUMIDITY_FAN_CONTROL_ENABLED" in body, (
        "F1 fix reverted: _CONF_HUMIDITY_FAN_CONTROL_ENABLED missing from "
        f"_ROOM_SUPPRESS_KEYS body: {body!r}"
    )


def test_room_suppress_keys_import_aliases_present():
    """The suppress-set entries reference module-local aliases; the
    ``_CONF_..._as`` import lines must exist so the frozenset resolves at
    module load time.
    """
    text = _INIT_PY.read_text()
    assert (
        "CONF_FAN_CONTROL_ENABLED as _CONF_FAN_CONTROL_ENABLED"
        in text
    ), "Fan-control alias import missing"
    assert (
        "CONF_HUMIDITY_FAN_CONTROL_ENABLED as _CONF_HUMIDITY_FAN_CONTROL_ENABLED"
        in text
    ), "Humidity-fan-control alias import missing"


# ---------------------------------------------------------------------------
# D2 — _RoomBooleanOptionSwitch.async_added_to_hass precedence
#
# Behavioral test: options-flow value in entry.options wins over
# RestoreEntity last_state at boot.  Reverting the change (last_state
# wins again) must fail the two "options wins" tests below.
# ---------------------------------------------------------------------------


class _StubSwitch:
    """Minimal harness that runs the exact production
    ``async_added_to_hass`` body against a fake entry+last_state.

    We intentionally do NOT subclass the real switch (its bases pull in
    HA core CoordinatorEntity machinery). Instead we monkey-copy the
    method under test — the assertion is on the *decision logic*, which
    is self-contained in this method.  If the method's logic changes,
    this test will detect it because we load the source function object
    from the live class.
    """

    def __init__(self, options: dict, last_state):
        self._conf_key = "fan_control_enabled"
        self._attr_is_on = None
        # coordinator.entry.options / .data — mimic ConfigEntry shape
        self.coordinator = SimpleNamespace(
            entry=SimpleNamespace(options=options, data={}),
        )
        self._last_state = last_state

    def _read_default(self) -> bool:  # matches production shape
        merged = {
            **self.coordinator.entry.data,
            **self.coordinator.entry.options,
        }
        return bool(merged.get(self._conf_key, False))

    async def async_get_last_state(self):
        return self._last_state


async def _run_added_to_hass(stub) -> None:
    """Execute the REAL _RoomBooleanOptionSwitch.async_added_to_hass body
    against the stub. We import the class from production and grab its
    unbound coroutine function, then call it with the stub as self.

    IMPORTANT: this makes the test mutation-anchored on the actual
    production source — swapping the branch order (RestoreEntity wins)
    in switch.py will change stub._attr_is_on and fail assertions below.
    """
    # Avoid pulling in HA core: import lazily and monkey-neuter the
    # super().async_added_to_hass() call by binding a no-op MRO shim.
    import importlib.util
    import sys
    import types

    # Prefer the already-loaded module if the suite imported it; else
    # do a light AST-free source-carve of just the method body.  We
    # implement the safe path: source-carve.
    src = _SWITCH_PY.read_text()
    m = re.search(
        r"class _RoomBooleanOptionSwitch\b[^\n]*\n(?:.*?\n)*?"
        r"(    async def async_added_to_hass\(self\) -> None:\n"
        r"(?:        .*\n)+?)"
        r"(?=\n    def |\n    async def |\nclass )",
        src,
    )
    assert m is not None, "async_added_to_hass body not found in switch.py"
    body = m.group(1)
    # Rewrite `await super().async_added_to_hass()` -> pass, so we don't
    # need the HA base class.  We keep every other line verbatim so the
    # test binds to production behavior.
    body = body.replace(
        "await super().async_added_to_hass()",
        "pass  # test harness: super() skipped",
    )
    ns: dict = {}
    exec(  # noqa: S102 — controlled source, extracted from production
        "async def async_added_to_hass(self) -> None:\n" + body.split(":\n", 1)[1],
        ns,
    )
    await ns["async_added_to_hass"](stub)


@pytest.mark.asyncio
async def test_options_wins_when_key_present_and_disagrees_with_last_state():
    """D2 anchor: options value = False, last_state = 'on' → attr_is_on False.

    If precedence is reverted (last_state wins), attr_is_on would be True
    and this assertion fails.
    """
    stub = _StubSwitch(
        options={"fan_control_enabled": False},
        last_state=SimpleNamespace(state="on"),
    )
    await _run_added_to_hass(stub)
    assert stub._attr_is_on is False, (
        "D2 fix reverted: options-flow value should win over RestoreEntity "
        "when the key is present in entry.options"
    )


@pytest.mark.asyncio
async def test_options_wins_when_key_present_true_last_state_off():
    """Symmetric: options True, last_state 'off' → attr_is_on True."""
    stub = _StubSwitch(
        options={"fan_control_enabled": True},
        last_state=SimpleNamespace(state="off"),
    )
    await _run_added_to_hass(stub)
    assert stub._attr_is_on is True, (
        "D2 fix reverted: options True should override restored 'off'"
    )


@pytest.mark.asyncio
async def test_last_state_wins_when_key_absent_from_options():
    """Key-absent first-boot case: RestoreEntity still governs."""
    stub = _StubSwitch(
        options={},  # nothing persisted via options flow
        last_state=SimpleNamespace(state="on"),
    )
    await _run_added_to_hass(stub)
    assert stub._attr_is_on is True, (
        "RestoreEntity fallback broken: last_state should govern when "
        "options key is absent"
    )


@pytest.mark.asyncio
async def test_bug_class_52_guard_preserved_unavailable_last_state():
    """Bug Class #52: last_state = 'unavailable' must NOT coerce to False.
    With key absent AND last_state unusable, fall back to _read_default.
    """
    stub = _StubSwitch(
        options={},
        last_state=SimpleNamespace(state="unavailable"),
    )
    await _run_added_to_hass(stub)
    # _read_default with empty options returns False (default) — the
    # important invariant is we did NOT set is_on based on "unavailable".
    assert stub._attr_is_on is False
    # And with a truthy default via options-data merge:
    stub2 = _StubSwitch(
        options={},
        last_state=SimpleNamespace(state="unknown"),
    )
    stub2.coordinator.entry.data = {"fan_control_enabled": True}
    await _run_added_to_hass(stub2)
    assert stub2._attr_is_on is True, (
        "Bug Class #52 guard broken: 'unknown' last_state should not "
        "block fallback to _read_default"
    )
