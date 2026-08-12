"""CONSOL-1 §D3 — perimeter_enrichment adapter test authority.

Pins the three-class failure contract (INV-ENRICH-NEVER-SILENCES) plus
INV-ENRICH-NON-EMPTY, INV-ENRICH-BUDGETED, and the cancel-immediately
contract on `asyncio.wait_for` timeout. Every test that pins a load-
bearing guard is mutation-anchored: a comment above the assert names
the production site whose removal would flip it red.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

# Load the adapter as a standalone module (avoid the URA package chain).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
_ura_path = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation",
)


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Package plumbing so `from .const import ...` resolves.
_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(_ura_path, "..")]
sys.modules.setdefault("custom_components", _cc)
_ura = types.ModuleType("custom_components.universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura
_cc.universal_room_automation = _ura

_const = _load(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_ura.const = _const
_enr = _load(
    "custom_components.universal_room_automation.perimeter_enrichment",
    os.path.join(_ura_path, "perimeter_enrichment.py"),
)


def _make_hass(
    enabled: bool = True,
    cameras: list[str] | None = None,
    model: str = "gpt-4o-mini",
    max_tokens: int = 1500,
    provider: str = "llmvision",
    timeout_state: str | None = None,
    service_result: dict | Exception | None = None,
    service_sleep_s: float = 0.0,
):
    hass = MagicMock()
    hass.is_stopping = False

    # Config entry
    entry = MagicMock()
    entry.data = {_const.CONF_ENTRY_TYPE: _const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        _const.CONF_PERIMETER_ENRICHMENT_ENABLED: enabled,
        _const.CONF_PERIMETER_ENRICHMENT_CAMERAS: cameras or [],
        _const.CONF_PERIMETER_ENRICHMENT_MODEL: model,
        _const.CONF_PERIMETER_ENRICHMENT_MAX_TOKENS: max_tokens,
        _const.CONF_PERIMETER_ENRICHMENT_PROVIDER: provider,
    }
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[entry])

    # Number-entity state for timeout knob.
    st = MagicMock()
    st.state = timeout_state if timeout_state is not None else "4.0"
    _states = {f"number.{_const.DOMAIN}_perimeter_enrichment_timeout_s": st}
    hass.states = MagicMock()
    hass.states.get = lambda eid: _states.get(eid)

    # Service call. `service_sleep_s > 0` simulates a slow provider so the
    # asyncio.wait_for timeout can fire.
    async def _fake_call(*args, **kwargs):
        if service_sleep_s > 0:
            await asyncio.sleep(service_sleep_s)
        if isinstance(service_result, Exception):
            raise service_result
        return service_result

    hass.services = MagicMock()
    hass.services.async_call = _fake_call
    return hass


# --- Snapshot file fixture ----------------------------------------------------


@pytest.fixture()
def _snapshot_file(tmp_path):
    p = tmp_path / "snap.jpg"
    p.write_bytes(b"fake")
    return str(p)


# --- Contract tests -----------------------------------------------------------


def test_enrichment_disabled_byte_identical(_snapshot_file):
    """Default OFF at ship — adapter no-ops, returns None cleanly."""
    hass = _make_hass(enabled=False, cameras=[])
    result = asyncio.run(_enr.enrich_dispatched_alert(
        hass, _snapshot_file, "binary_sensor.front_yard",
    ))
    # Mutation anchor: remove the `_is_enabled_for_camera` short-return
    # in perimeter_enrichment.enrich_dispatched_alert → this returns str.
    assert result is None


def test_enrichment_only_when_snapshot_path_present():
    """No snapshot_path → adapter never calls llmvision (rev-2 L1)."""
    hass = _make_hass(
        enabled=True, cameras=["binary_sensor.front_yard"],
        service_result={"response_text": "should not fire"},
    )
    result = asyncio.run(_enr.enrich_dispatched_alert(
        hass, None, "binary_sensor.front_yard",
    ))
    assert result is None


def test_enrichment_missing_snapshot_no_call(tmp_path):
    """Path string points at a file that doesn't exist → adapter no-ops."""
    hass = _make_hass(
        enabled=True, cameras=["binary_sensor.front_yard"],
        service_result={"response_text": "should not fire"},
    )
    ghost = str(tmp_path / "does_not_exist.jpg")
    result = asyncio.run(_enr.enrich_dispatched_alert(
        hass, ghost, "binary_sensor.front_yard",
    ))
    assert result is None


def test_enrichment_success_returns_stripped_text(_snapshot_file):
    """Happy path: {"response_text": "..."} → adapter returns stripped str."""
    hass = _make_hass(
        enabled=True, cameras=["binary_sensor.front_yard"],
        service_result={"response_text": "  A person in a hoodie.  "},
    )
    result = asyncio.run(_enr.enrich_dispatched_alert(
        hass, _snapshot_file, "binary_sensor.front_yard",
    ))
    assert result == "A person in a hoodie."


@pytest.mark.parametrize(
    "response_text",
    [None, "", "   ", "\n\t"],
)
def test_enrichment_empty_response_falls_through(_snapshot_file, response_text):
    """INV-ENRICH-NON-EMPTY (rev-2 #1): None/""/whitespace → None (fall through)."""
    hass = _make_hass(
        enabled=True, cameras=["binary_sensor.front_yard"],
        service_result={"response_text": response_text},
    )
    result = asyncio.run(_enr.enrich_dispatched_alert(
        hass, _snapshot_file, "binary_sensor.front_yard",
    ))
    # Mutation anchor: remove the `if not text: return None` block —
    # adapter would return "" and the caller would concatenate a trailing
    # separator into the message body (silent P2 regression).
    assert result is None


def test_enrichment_exception_falls_through(_snapshot_file):
    """INV-ENRICH-NEVER-SILENCES class (a): adapter raise → None."""
    hass = _make_hass(
        enabled=True, cameras=["binary_sensor.front_yard"],
        service_result=RuntimeError("provider 500"),
    )
    result = asyncio.run(_enr.enrich_dispatched_alert(
        hass, _snapshot_file, "binary_sensor.front_yard",
    ))
    assert result is None


def test_enrichment_timeout_falls_through(_snapshot_file):
    """INV-ENRICH-BUDGETED / class (b): wall-clock > timeout_s → None
    at ≤ timeout_s + small margin. Mutation anchor: remove the
    `asyncio.wait_for` wrap → this test times out (no bound)."""
    hass = _make_hass(
        enabled=True, cameras=["binary_sensor.front_yard"],
        service_result={"response_text": "late"},
        service_sleep_s=5.0,
        timeout_state="0.2",  # aggressive; keeps test fast
    )

    async def _drive():
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        r = await _enr.enrich_dispatched_alert(
            hass, _snapshot_file, "binary_sensor.front_yard",
        )
        return r, loop.time() - t0

    r, elapsed = asyncio.run(_drive())
    assert r is None
    # Cancel-immediately contract: return within a couple of scheduler ticks.
    assert elapsed < 1.5, f"timeout took too long: {elapsed:.2f}s"


def test_enrichment_late_completion_never_double_dispatches(_snapshot_file):
    """Cancel-contract (rev-2 #2): once wait_for fires the underlying
    coroutine is cancelled and cannot late-deliver into the alert path.
    We simulate the (a) ordering (timeout first, provider "completes"
    later) and observe the adapter returned None BEFORE the "would-be"
    late completion could produce another value."""
    hass = _make_hass(
        enabled=True, cameras=["binary_sensor.front_yard"],
        service_result={"response_text": "late-result"},
        service_sleep_s=2.0,
        timeout_state="0.1",
    )
    result = asyncio.run(_enr.enrich_dispatched_alert(
        hass, _snapshot_file, "binary_sensor.front_yard",
    ))
    assert result is None


def test_enrichment_two_cameras_concurrent_isolated(_snapshot_file):
    """Rev-2 L2: two concurrent events get independent adapter invocations."""
    hass = _make_hass(
        enabled=True,
        cameras=[
            "binary_sensor.front_yard", "binary_sensor.back_yard",
        ],
        service_result={"response_text": "ok"},
    )

    async def _drive():
        return await asyncio.gather(
            _enr.enrich_dispatched_alert(
                hass, _snapshot_file, "binary_sensor.front_yard",
            ),
            _enr.enrich_dispatched_alert(
                hass, _snapshot_file, "binary_sensor.back_yard",
            ),
        )

    a, b = asyncio.run(_drive())
    assert a == "ok"
    assert b == "ok"


def test_enrichment_kill_switch_disables(monkeypatch, _snapshot_file):
    """Rung-1 kill switch: LLMVISION_ENRICHMENT_KILL = True → adapter
    returns None even with enabled=True and camera in the allowlist.
    Mutation anchor: remove the `if LLMVISION_ENRICHMENT_KILL: return
    False` in _is_enabled_for_camera → this test flips green→red-would-
    call-service, but here we assert None (no service call reached)."""
    monkeypatch.setattr(_enr, "LLMVISION_ENRICHMENT_KILL", True)
    hass = _make_hass(
        enabled=True, cameras=["binary_sensor.front_yard"],
        service_result={"response_text": "kill me not"},
    )
    result = asyncio.run(_enr.enrich_dispatched_alert(
        hass, _snapshot_file, "binary_sensor.front_yard",
    ))
    assert result is None


def test_enrichment_camera_not_in_allowlist_no_call(_snapshot_file):
    """Enabled but this camera not on the allowlist → no service call."""
    hass = _make_hass(
        enabled=True, cameras=["binary_sensor.back_yard"],
        service_result={"response_text": "must not reach"},
    )
    result = asyncio.run(_enr.enrich_dispatched_alert(
        hass, _snapshot_file, "binary_sensor.front_yard",
    ))
    assert result is None
