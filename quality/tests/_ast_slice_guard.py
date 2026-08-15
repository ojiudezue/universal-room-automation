"""Shared post-compile AST guard for the three `__init__.py` slice loaders
(`test_reload_watchdog_hazard.py`, `test_cm_reload_suppression.py`,
`test_part2_ec_hc_writeback.py`).

Review-C M-1 (RELOAD-WATCHDOG-HAZARD, 2026-08-15). The AST-slice loader
pre-seeds a large namespace with `_CONF_*` names + stand-ins so the
sliced production code can `exec` cleanly. If a builder adds a NEW
top-level symbol reference to `_async_update_listener` (or any sliced
function) without updating the loader stubs, the slice `exec`s
successfully (Python only resolves free names at execution) and only
blows up when a test happens to hit the branch that loads the missing
name. That is a hollow anchor — the D2 build demonstrated it: an
`ENTRY_TYPE_INTEGRATION` reference silently loaded in this loader
because the D2 tests seeded it, but blew up in the two SIBLING loaders
that had not been updated.

This guard walks the sliced AST post-compile and raises `RuntimeError`
on any `Name` load whose id is neither pre-seeded in `ns`, nor a
Python builtin, nor a local assignment/def/import inside the slice —
converting the silent stub-miss into a hard test failure at load time.
"""
from __future__ import annotations

import ast
import builtins


def assert_ast_slice_names_covered(mod: ast.Module, ns: dict) -> None:
    """Raise `RuntimeError` on any free `Name` load in `mod` that is
    neither present in `ns`, a Python builtin, nor bound locally inside
    the sliced code."""
    defined: set[str] = set()
    for node in ast.walk(mod):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
            for a in getattr(node.args, "args", []) or []:
                defined.add(a.arg)
            for a in getattr(node.args, "kwonlyargs", []) or []:
                defined.add(a.arg)
            for a in getattr(node.args, "posonlyargs", []) or []:
                defined.add(a.arg)
            if node.args.vararg:
                defined.add(node.args.vararg.arg)
            if node.args.kwarg:
                defined.add(node.args.kwarg.arg)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Name):
                        defined.add(sub.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                defined.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                defined.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            for sub in ast.walk(node.target):
                if isinstance(sub, ast.Name):
                    defined.add(sub.id)
        elif isinstance(node, ast.comprehension):
            for sub in ast.walk(node.target):
                if isinstance(sub, ast.Name):
                    defined.add(sub.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            for sub in ast.walk(node.optional_vars):
                if isinstance(sub, ast.Name):
                    defined.add(sub.id)
    builtin_names = set(dir(builtins))
    missing: set[str] = set()
    for node in ast.walk(mod):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            n = node.id
            if n in ns or n in defined or n in builtin_names:
                continue
            missing.add(n)
    if missing:
        raise RuntimeError(
            "AST-slice namespace missing symbols the sliced code loads "
            f"— add stubs to the loader (or extend the keep-set): "
            f"{sorted(missing)}"
        )
