"""Regression guard: v4.7.20.1 — UnboundLocalError on async_dispatcher_send.

v4.7.20's B-H2 fix-up hoisted `async_dispatcher_send` to a module-top import in
presence.py, but left a function-local `from ...dispatcher import async_dispatcher_send`
inside `_run_inference`. A function-local import re-scopes that name as a local
for the ENTIRE method, so every later use on a tick that skips the importing
branch raised `UnboundLocalError: cannot access local variable
'async_dispatcher_send'`. Live it fired ~every tick on the SIGNAL_PRESENCE_ENTITIES_UPDATE
dispatch and on the new fan-interference gate dispatch.

The fix removed all bare function-local imports of `async_dispatcher_send`; the
module-top import is now the sole binding. This guard fails if any function-local
import re-binds the bare name again. Aliased imports (`... as _dispatcher_send`)
are allowed because they bind a different local name and cannot shadow the global.
"""

import ast
import os

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PRESENCE_PATH = os.path.join(
    _REPO_ROOT,
    "custom_components",
    "universal_room_automation",
    "domain_coordinators",
    "presence.py",
)


def _function_local_bare_imports(tree: ast.AST) -> list:
    """Return (func_name, lineno) for every function-local ImportFrom that binds
    the bare name `async_dispatcher_send` (no alias)."""
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.ImportFrom):
                continue
            for alias in inner.names:
                if alias.name == "async_dispatcher_send" and alias.asname is None:
                    offenders.append((node.name, inner.lineno))
    return offenders


def test_no_function_local_async_dispatcher_send_import():
    with open(_PRESENCE_PATH) as f:
        tree = ast.parse(f.read())

    offenders = _function_local_bare_imports(tree)
    assert offenders == [], (
        "Function-local `import async_dispatcher_send` re-scopes the name as a "
        "method-local, causing UnboundLocalError on branches that skip the import "
        f"(v4.7.20.1 regression). Use the module-top import instead. Found: {offenders}"
    )


def test_module_top_async_dispatcher_send_import_present():
    """The module-top import must exist — it is the sole binding the gate relies on."""
    with open(_PRESENCE_PATH) as f:
        tree = ast.parse(f.read())

    found = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "homeassistant.helpers.dispatcher"
        and any(a.name == "async_dispatcher_send" and a.asname is None for a in node.names)
        for node in tree.body  # module-level only
    )
    assert found, "Module-top `from homeassistant.helpers.dispatcher import async_dispatcher_send` is missing."
