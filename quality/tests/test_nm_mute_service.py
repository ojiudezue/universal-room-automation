"""v5.62.2 — the NM mute service handler must be a COROUTINE function.

Regression pin for a real production defect found 2026-08-08 while trying to
mute an alert loop in real time: `_mute_service_handler` was registered as a
plain `def`, so Home Assistant ran it in an executor thread, where
`hass.async_create_task()` is not thread-safe. The coroutine was created and
immediately dropped — HA logged
`coroutine 'NotificationManager.async_mute_person_channel' was never awaited`
and the service call returned HTTP 500. The operator's documented mute escape
hatch had therefore never worked.

This is an AST assertion, not a source grep: it parses the module and checks
the handler is an `AsyncFunctionDef`. A sync-def regression fails it.
"""
from __future__ import annotations

import ast
from pathlib import Path


def _handler_node():
    src = (
        Path(__file__).resolve().parents[2]
        / "custom_components/universal_room_automation/domain_coordinators"
        / "notification_manager.py"
    ).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "_mute_service_handler":
                return node
    return None


def test_mute_service_handler_is_async():
    node = _handler_node()
    assert node is not None, "_mute_service_handler not found"
    assert isinstance(node, ast.AsyncFunctionDef), (
        "REGRESSION: _mute_service_handler is a sync def. HA will run it in an "
        "executor thread where hass.async_create_task() is not thread-safe; the "
        "coroutine is dropped and the service call 500s. Make it `async def` and "
        "await async_mute_person_channel directly."
    )


def test_mute_handler_awaits_rather_than_fire_and_forget():
    """The handler must AWAIT the coroutine, not schedule it from a thread."""
    node = _handler_node()
    assert node is not None
    has_await = any(isinstance(n, ast.Await) for n in ast.walk(node))
    schedules = [
        n for n in ast.walk(node)
        if isinstance(n, ast.Attribute) and n.attr == "async_create_task"
    ]
    assert has_await, "handler must await async_mute_person_channel"
    assert not schedules, (
        "handler must not use hass.async_create_task — that was the original "
        "thread-safety defect"
    )
