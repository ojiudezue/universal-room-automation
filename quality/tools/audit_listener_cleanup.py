"""UNLOAD-SYMMETRY-TASK-HYGIENE-1 — find subscriptions that are never torn down.

THE BUG CLASS. Every dispatcher subscription and every recurring timer that
URA registers returns an *unsubscribe callable*. If that callable is thrown
away, the subscription outlives the thing that made it. On a config-entry
reload the old handler is still attached AND a new one is added, so the
handler runs twice, then three times, then N times — the classic
double-dispatch / reload-leak shape.

There are two legitimate ways to keep it:
  * ``self.async_on_remove(async_dispatcher_connect(...))``  — Entity scope
  * ``entry.async_on_unload(async_dispatcher_connect(...))`` — ConfigEntry scope
  * assigning it (``self._unsub = ...``) and calling it later
Anything else is a candidate leak.

WHY AST AND NOT GREP. A grep of this codebase reports 294 dispatcher connects
against 163 cleanup idioms and implies ~131 leaks. That number is wrong: the
cleanup wrapper is frequently on a DIFFERENT LINE from the call it wraps
(black splits long calls), so line-based matching misses it. This walks the
syntax tree and asks the only question that matters: is this call's RESULT
retained by anything? Read-only; prints findings and exits 0 (report, not gate).

Usage:  python3 quality/tools/audit_listener_cleanup.py [--verbose]
"""
from __future__ import annotations

import ast
import os
import sys

ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "custom_components", "universal_room_automation",
)

# Calls that return an unsubscribe/cancel callable the caller MUST retain.
SUBSCRIBE_CALLS = {
    "async_dispatcher_connect",
    "async_track_time_interval",
    "async_track_state_change_event",
    "async_track_point_in_time",
    "async_track_point_in_utc_time",
    "async_track_time_change",
    "async_track_template_result",
    "async_call_later",
}

# Wrappers that take ownership of the returned callable.
RETAINING_WRAPPERS = {"async_on_remove", "async_on_unload"}


def _call_name(node: ast.Call) -> str:
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


class Auditor(ast.NodeVisitor):
    """Flag subscribe-calls whose return value is discarded.

    A call is CONSIDERED SAFE when its nearest enclosing expression either
    (a) hands it to a retaining wrapper, or (b) binds it to a name/attribute
    (assumed to be unsubscribed elsewhere — reported only with --verbose,
    since we cannot prove the later call without whole-program analysis).
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.leaks: list[tuple[int, str, str]] = []
        self.retained: list[tuple[int, str]] = []
        # Stack of (node) parents so we can inspect how a Call is used.
        self._parents: dict[int, ast.AST] = {}

    def build_parents(self, tree: ast.AST) -> None:
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                self._parents[id(child)] = parent

    def audit(self, tree: ast.AST) -> None:
        self.build_parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if name not in SUBSCRIBE_CALLS:
                continue
            verdict = self._classify(node)
            if verdict == "leak":
                self.leaks.append((node.lineno, name, self._context(node)))
            else:
                self.retained.append((node.lineno, name))

    def _classify(self, node: ast.Call) -> str:
        parent = self._parents.get(id(node))
        # Walk up through await / parenthesised wrappers.
        while isinstance(parent, ast.Await):
            node, parent = parent, self._parents.get(id(parent))
        if isinstance(parent, ast.Call):
            if _call_name(parent) in RETAINING_WRAPPERS:
                return "retained"
            # Passed as an argument to something else that may store it.
            return "retained"
        if isinstance(parent, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            return "retained"
        if isinstance(parent, (ast.Return, ast.Await)):
            return "retained"
        # Bare expression statement -> return value dropped on the floor.
        if isinstance(parent, ast.Expr):
            return "leak"
        if isinstance(parent, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
            return "retained"
        return "retained"

    def _context(self, node: ast.Call) -> str:
        cur: ast.AST | None = node
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return cur.name
            cur = self._parents.get(id(cur))
        return "<module>"


def main() -> int:
    verbose = "--verbose" in sys.argv
    total_leaks = 0
    total_retained = 0
    by_file: dict[str, list[tuple[int, str, str]]] = {}

    for dirpath, _dirs, files in os.walk(ROOT):
        for fname in sorted(files):
            if not fname.endswith(".py"):
                continue
            path = os.path.join(dirpath, fname)
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except SyntaxError as exc:  # pragma: no cover - defensive
                print(f"SKIP {path}: {exc}")
                continue
            aud = Auditor(path)
            aud.audit(tree)
            total_retained += len(aud.retained)
            if aud.leaks:
                rel = os.path.relpath(path, ROOT)
                by_file[rel] = aud.leaks
                total_leaks += len(aud.leaks)

    print("UNLOAD-SYMMETRY listener-cleanup audit")
    print("=" * 62)
    for rel in sorted(by_file, key=lambda k: -len(by_file[k])):
        print(f"\n{rel}  ({len(by_file[rel])} discarded)")
        for lineno, name, func in by_file[rel]:
            print(f"    L{lineno:<6} {name:<32} in {func}()")
    print("\n" + "=" * 62)
    print(f"DISCARDED (return value dropped): {total_leaks}")
    print(f"RETAINED  (wrapped/assigned/passed): {total_retained}")
    print(
        "\nNOTE: 'retained' is deliberately generous — it counts anything whose\n"
        "result is bound or handed onward. It does NOT prove the unsubscribe is\n"
        "ever CALLED. Only the DISCARDED list is a definite finding."
    )
    if verbose:
        print("\n(--verbose: per-call retained detail omitted; see source)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
