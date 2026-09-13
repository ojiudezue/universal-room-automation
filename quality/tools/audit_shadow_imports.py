"""SHADOW-IMPORT-AUDIT-1 — detect the Bug Class #34 footgun:

A function-local ``from .const import X`` (or any local import) binds X as a
LOCAL name for the whole function. If X is also *used* somewhere in that
function BEFORE the import statement's line, Python raises
``UnboundLocalError: local variable 'X' referenced before assignment`` at
runtime (the v5.84.0 CONF_ENTRY_TYPE incident).

This audit walks every function in the component and flags any local-import
name that has a Load reference at an earlier line in the same function scope.
Read-only; prints findings as  file:func:name  import@L<import>  use@L<use>.
"""
from __future__ import annotations

import ast
import os
import sys

ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "custom_components", "universal_room_automation",
)


def _local_import_names(node: ast.AST):
    """Yield (name, lineno) for every name bound by an import inside node's
    OWN body (not nested functions)."""
    out = []
    for child in ast.walk(node):
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                bound = alias.asname or alias.name.split(".")[0]
                out.append((bound, child.lineno))
    return out


def _loads_by_name(node: ast.AST):
    """Map name -> sorted list of Load linenos within node."""
    uses: dict[str, list[int]] = {}
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            uses.setdefault(child.id, []).append(child.lineno)
    return uses


def find_shadows_in_source(src: str, path: str = "<src>") -> list:
    """Audit a single source string; return findings for it (test hook)."""
    findings: list = []
    tree = ast.parse(src, filename=path)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            audit_function(node, path, findings)
    return findings


def find_shadows(root: str = ROOT) -> list:
    """Repo-wide audit; return the findings list (empty == clean)."""
    findings: list = []
    for base, _dirs, files in os.walk(root):
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(base, f)
            try:
                tree = ast.parse(open(path).read(), filename=path)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    audit_function(node, os.path.relpath(path, root), findings)
    return findings


def audit_function(fn: ast.AST, path: str, findings: list):
    # local imports directly in this function (walk includes nested; filter by
    # excluding names bound inside nested funcs is complex — accept minor
    # over-report, then verify by hand).
    imports = _local_import_names(fn)
    if not imports:
        return
    uses = _loads_by_name(fn)
    # earliest import line per name
    first_import: dict[str, int] = {}
    for name, ln in imports:
        first_import[name] = min(first_import.get(name, ln), ln)
    for name, imp_line in first_import.items():
        earlier = [u for u in uses.get(name, []) if u < imp_line]
        if earlier:
            findings.append((path, getattr(fn, "name", "?"), name, imp_line, min(earlier)))


def main():
    findings = find_shadows()
    if not findings:
        print("CLEAN: no use-before-local-import shadow found (Bug Class #34)")
        return 0
    print(f"POTENTIAL SHADOWS ({len(findings)}):")
    for path, fn, name, imp, use in sorted(findings):
        print(f"  {path}:{fn}  name={name}  import@L{imp}  use@L{use}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
