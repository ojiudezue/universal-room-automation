"""Guard test for Bug Class #28: sync function passed to add_update_listener.

HA 2024+ awaits update listeners: it does
    self.hass.async_create_task(listener(self.hass, entry), ...)
A sync function returns None, which fails with
    TypeError: a coroutine was expected, got None

This test walks the URA codebase, finds every `entry.add_update_listener(name)`
call, locates the function definition by name in the same file, and asserts
the function is `async def`.

v4.5.2 D1: defer annotation eval for Python 3.9 dev-env compat (the test
itself uses `ast.AST | None` at module level for a helper signature).

Discovered v4.2.24: coordinator.py:837 had a sync `@callback` registered as
update listener — caused months of silent config-save failures. See
docs/QUALITY_CONTEXT.md Bug Class #28.
"""
from __future__ import annotations

import ast
import pathlib

import pytest


COMPONENT_ROOT = pathlib.Path(__file__).resolve().parents[2] / (
    "custom_components/universal_room_automation"
)


def _iter_py_files():
    return COMPONENT_ROOT.rglob("*.py")


def _find_function_def(tree: ast.AST, name: str) -> ast.AST | None:
    """Find a top-level or class-level FunctionDef by name anywhere in the tree."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _handler_name(handler_arg: ast.AST) -> str | None:
    """Extract a function name from common handler argument shapes.

    Handles:
      - bare names:        add_update_listener(_on_entry_update)
      - attribute access:  add_update_listener(self._on_entry_update)
                           add_update_listener(coordinator.handler)
    Returns None for lambdas, partials, and other non-name shapes.
    """
    if isinstance(handler_arg, ast.Name):
        return handler_arg.id
    if isinstance(handler_arg, ast.Attribute):
        return handler_arg.attr
    return None


def test_no_sync_update_listeners():
    """Every add_update_listener handler must be async def.

    v4.2.26 strengthened (review M5): also resolves attribute-access handlers
    like `add_update_listener(self.foo)` — finds method `foo` on any class
    and asserts async.
    """
    violations: list[str] = []
    skipped_unresolvable: list[str] = []

    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError as e:
            pytest.fail(f"{path} failed to parse: {e}")

        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_update_listener"
                and node.args
            ):
                continue

            handler_arg = node.args[0]
            handler_name = _handler_name(handler_arg)

            if handler_name is None:
                # Lambda, partial, or other dynamic — can't statically verify.
                skipped_unresolvable.append(
                    f"{path}:{node.lineno}: handler is not a name/attribute "
                    f"({type(handler_arg).__name__}); cannot statically verify"
                )
                continue

            fn_def = _find_function_def(tree, handler_name)
            if fn_def is None:
                # Defined in another module — can't verify here. Conservative:
                # don't fail the test, but record so a human can audit.
                skipped_unresolvable.append(
                    f"{path}:{node.lineno}: handler '{handler_name}' not "
                    "found in this file; cross-module verification skipped"
                )
                continue

            if not isinstance(fn_def, ast.AsyncFunctionDef):
                violations.append(
                    f"{path}:{fn_def.lineno}: handler '{handler_name}' "
                    f"passed to add_update_listener at line {node.lineno} "
                    f"is sync — must be `async def` (Bug Class #28)"
                )

    assert not violations, (
        "Sync handlers registered to add_update_listener (Bug Class #28):\n  - "
        + "\n  - ".join(violations)
        + (
            "\n\nNote: the following could not be statically verified "
            "(audit by hand):\n  - " + "\n  - ".join(skipped_unresolvable)
            if skipped_unresolvable else ""
        )
    )

