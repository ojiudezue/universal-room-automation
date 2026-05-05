"""Guard test for Bug Class #28: sync function passed to add_update_listener.

HA 2024+ awaits update listeners: it does
    self.hass.async_create_task(listener(self.hass, entry), ...)
A sync function returns None, which fails with
    TypeError: a coroutine was expected, got None

This test walks the URA codebase, finds every `entry.add_update_listener(name)`
call, locates the function definition by name in the same file, and asserts
the function is `async def`.

Discovered v4.2.24: coordinator.py:837 had a sync `@callback` registered as
update listener — caused months of silent config-save failures. See
docs/QUALITY_CONTEXT.md Bug Class #28.
"""
import ast
import pathlib

import pytest


COMPONENT_ROOT = pathlib.Path(__file__).resolve().parents[2] / (
    "custom_components/universal_room_automation"
)


def _iter_py_files():
    return COMPONENT_ROOT.rglob("*.py")


def _find_function_def(tree: ast.AST, name: str) -> ast.AST | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def test_no_sync_update_listeners():
    """Every add_update_listener handler must be async def."""
    violations: list[str] = []

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

            handler = node.args[0]
            if not isinstance(handler, ast.Name):
                # Non-name args (lambda, attribute access) — skip; covered by
                # other checks if needed.
                continue

            fn_def = _find_function_def(tree, handler.id)
            if fn_def is None:
                # Defined in another module — can't statically verify here.
                continue

            if not isinstance(fn_def, ast.AsyncFunctionDef):
                violations.append(
                    f"{path}:{fn_def.lineno}: handler '{handler.id}' "
                    f"passed to add_update_listener at line {node.lineno} "
                    f"is sync — must be `async def` (Bug Class #28)"
                )

    assert not violations, (
        "Sync handlers registered to add_update_listener (Bug Class #28):\n  - "
        + "\n  - ".join(violations)
    )
