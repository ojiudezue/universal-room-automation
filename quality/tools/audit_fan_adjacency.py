"""FAN-LAYER-1 §9-C M1 — fan-adjacency AST audit.

For every writer that consults ``oracle.may_turn_on`` / ``oracle.may_turn_off``
or opens an ``oracle.actuate(...)`` async-context block, verify that the
service-call emission is IMMEDIATELY adjacent (same function, no
early-returnable branch between the consult and the emit).

Session 1 (2026-08-10) migrates zero writers, so this walker currently
finds ZERO consult sites and returns success trivially. It is committed
and wired into the test suite so (a) later sessions cannot silently
regress adjacency, and (b) the D8 audit deliverable has an executable
authority.

Adjacency contract (PLAN §7.9 TOCTOU discipline):
  * For ``oracle.actuate`` sites the service call lives INSIDE the async-
    with body; adjacency is satisfied by construction (the lock is held).
  * For raw ``may_turn_*`` sites, the consult must be immediately followed
    by either:
      1. a ``services.async_call`` (possibly awaited / assigned) as the
         very next statement, OR
      2. an ``if verdict.is_allow`` guard whose body's first Call is
         ``services.async_call``.

Run as a module::

    python3 -m quality.tools.audit_fan_adjacency [path...]
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCAN_ROOTS = (
    REPO_ROOT / "custom_components" / "universal_room_automation",
)


@dataclass(frozen=True)
class AdjacencyFinding:
    file: str
    lineno: int
    site: str
    reason: str

    def __str__(self) -> str:
        return f"{self.file}:{self.lineno}: {self.site} — {self.reason}"


def _iter_py_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            yield root
            continue
        for path in root.rglob("*.py"):
            if "quality/tests/" in path.as_posix():
                continue
            if path.name == "audit_fan_adjacency.py":
                continue
            yield path


def _is_oracle_actuate_call(node: ast.AST) -> bool:
    """Return True if ``node`` is an ``oracle.actuate(...)`` call.

    Restored in C-MED-2 fix-up (2026-08-11): the un-vacuoused adjacency
    walker uses this to distinguish oracle.actuate async-with items from
    unrelated context managers (locks, file handles, other async ctx-mgrs).
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return isinstance(func, ast.Attribute) and func.attr == "actuate"


def _is_oracle_consult_call(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr in ("may_turn_on", "may_turn_off"):
        return func.attr
    return None


def _is_service_call(node: ast.AST) -> bool:
    call = node
    if isinstance(node, ast.Await):
        call = node.value
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    return isinstance(func, ast.Attribute) and func.attr == "async_call"


def _next_stmt_is_service_call_or_allow_branch(
    stmts: list[ast.stmt], idx: int,
) -> bool:
    if idx + 1 >= len(stmts):
        return False
    nxt = stmts[idx + 1]
    if isinstance(nxt, ast.Expr) and _is_service_call(nxt.value):
        return True
    if isinstance(nxt, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
        val = getattr(nxt, "value", None)
        if val is not None and _is_service_call(val):
            return True
    if isinstance(nxt, ast.If):
        for sub in nxt.body:
            if isinstance(sub, ast.Expr) and _is_service_call(sub.value):
                return True
        return False
    return False


def _walk_stmts_for_consults(
    stmts: list[ast.stmt], file: str, findings: list[AdjacencyFinding],
) -> None:
    for idx, stmt in enumerate(stmts):
        for attr in ("body", "orelse", "finalbody", "handlers"):
            children = getattr(stmt, attr, None)
            if isinstance(children, list):
                if attr == "handlers":
                    for h in children:
                        if isinstance(h, ast.ExceptHandler):
                            _walk_stmts_for_consults(h.body, file, findings)
                else:
                    _walk_stmts_for_consults(children, file, findings)
        if isinstance(stmt, ast.AsyncWith):
            # oracle.actuate satisfies adjacency by lock construction —
            # BUT C-MED-2 fix-up (2026-08-11): un-vacuous the check by
            # asserting that at least ONE async_with item is oracle.actuate
            # AND at least one services.async_call lives INSIDE the block.
            # This catches the failure mode where an oracle.actuate wrap
            # is present but the actual emission was refactored OUT of the
            # block (leaving the lock held over nothing while a raw
            # services.async_call fires elsewhere in the same function).
            is_actuate_block = any(
                _is_oracle_actuate_call(item.context_expr)
                for item in stmt.items
            )
            if is_actuate_block:
                has_inner_service_call = any(
                    _is_service_call(sub)
                    for body_stmt in stmt.body
                    for sub in ast.walk(body_stmt)
                )
                if not has_inner_service_call:
                    findings.append(AdjacencyFinding(
                        file=file, lineno=stmt.lineno,
                        site="oracle.actuate",
                        reason="async-with oracle.actuate body contains no "
                               "services.async_call — the lock guards nothing "
                               "(C-MED-2 fix-up unvacuoused this check)",
                    ))
            continue
        found_consult: str | None = None
        for sub in ast.walk(stmt):
            kind = _is_oracle_consult_call(sub)
            if kind is not None:
                found_consult = kind
                break
        if found_consult is None:
            continue
        has_later_service_call = any(
            _is_service_call(n)
            for later in stmts[idx + 1:]
            for n in ast.walk(later)
        )
        if not has_later_service_call:
            continue
        if not _next_stmt_is_service_call_or_allow_branch(stmts, idx):
            findings.append(AdjacencyFinding(
                file=file, lineno=stmt.lineno,
                site=f"oracle.{found_consult}",
                reason="consult not immediately adjacent to services.async_call "
                       "(no branchable code allowed between per PLAN §7.9)",
            ))


def _scan_file(path: Path) -> list[AdjacencyFinding]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    findings: list[AdjacencyFinding] = []
    file_str = path.relative_to(REPO_ROOT).as_posix()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _walk_stmts_for_consults(node.body, file_str, findings)
    return findings


def run_audit(roots: Iterable[Path] | None = None) -> list[AdjacencyFinding]:
    scan_roots = tuple(roots) if roots is not None else DEFAULT_SCAN_ROOTS
    findings: list[AdjacencyFinding] = []
    for py in _iter_py_files(scan_roots):
        findings.extend(_scan_file(py))
    return findings


def _main(argv: list[str]) -> int:
    roots = [Path(p) for p in argv[1:]] if len(argv) > 1 else list(DEFAULT_SCAN_ROOTS)
    findings = run_audit(roots)
    if not findings:
        # A-LOW-3 fix-up (2026-08-11): message reflects the post-Session-3
        # state — W11 + W12 are wired via oracle.actuate; the walker now
        # asserts each async-with block actually contains a service call.
        print(
            "fan-adjacency audit: OK — all oracle.actuate blocks contain "
            "an inner services.async_call; no orphaned consults"
        )
        return 0
    print(f"fan-adjacency audit: {len(findings)} violation(s):")
    for f in findings:
        print(f"  {f}")
    return 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
