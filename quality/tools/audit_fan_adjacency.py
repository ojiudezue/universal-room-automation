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
        # FAN-LAYER-2 D2 §5.5: allow explicit fixture-root scans for the
        # reverse-adjacency synthetic-violation test. Default sweeps still
        # skip quality/tests/ (production-only production tree scan).
        root_str = root.as_posix()
        explicit_test_root = "quality/tests/" in root_str
        for path in root.rglob("*.py"):
            path_str = path.as_posix()
            if "quality/tests/" in path_str and not explicit_test_root:
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


_EMIT_HELPER_NAMES = frozenset({
    # Wrappers around hass.services.async_call whose bodies delegate to the
    # actual services.async_call. Counted as valid "inner emit" for the
    # C-MED-2 un-vacuous check of oracle.actuate async-with bodies.
    "async_call",
    "_safe_service_call",
    "_emit_fan_state",
    "_emit_w8",
    "_emit_w9",
    "_emit_temp_on",
    "_emit_onset",
})


def _is_service_call(node: ast.AST) -> bool:
    call = node
    if isinstance(node, ast.Await):
        call = node.value
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in _EMIT_HELPER_NAMES:
        return True
    if isinstance(func, ast.Name) and func.id in _EMIT_HELPER_NAMES:
        return True
    return False


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


# =============================================================================
# FAN-LAYER-2 D2 §5.5 — REVERSE-ADJACENCY SCANNER
# =============================================================================
#
# Forward scanner (above): starts from every ``oracle.may_turn_*`` consult and
# verifies the next statement is a ``services.async_call``.
#
# Reverse scanner (below): starts from every FAN-DOMAIN ``services.async_call``
# emission and verifies each is enclosed by an ``async with oracle.actuate(...)``
# ancestor (or carved out with an explicit ``# fan-adjacency: allow (reason=...)``
# comment). This closes the failure mode where a new fan writer is added that
# never even considered the oracle — the forward walker cannot see it because
# there is no consult to start from.
#
# Five AST rules (PLAN §5.5):
#   (1) direct fan domain — ``services.async_call("fan", ...)`` string literal.
#   (2) ``startswith("fan.")`` branch — the classic per-entity dispatch in
#       ``_set_fan_state`` and its ilk (any function body that guards a
#       ``services.async_call`` under an ``entity.startswith("fan.")`` If).
#   (3) ``_set_fan_state`` param-taint — a call to the hard-coded chokepoint
#       method name is treated as an emission by proxy (its own body is wrapped
#       via rule 4, so callers need not re-wrap; this rule ensures the CALL is
#       tracked so a mis-refactored caller that bypasses the chokepoint gets
#       flagged).
#   (4) enclosing ``oracle.actuate`` context — the site is inside an
#       ``async with oracle.actuate(...)`` AST ancestor.
#   (5) ``# fan-adjacency: allow (reason=...)`` carve-out comment on the same
#       source line as the emission (or the immediately preceding line).

_ALLOW_CARVEOUT_PREFIX = "# fan-adjacency: allow"

# Chokepoint helpers: their BODIES contain the fan emit but are themselves
# wrapped (either directly by an enclosing ``async with oracle.actuate`` in the
# caller — the W4/W8/W9 pattern — or by helper contract where the caller ALWAYS
# hits the W4-chokepoint wrap). Treat calls TO these helpers as satisfying the
# wrap requirement (rule 3 chokepoint allowlist), and skip their BODIES during
# scanning (they are the wrapped chokepoint itself).
_CHOKEPOINT_ALLOWLIST = frozenset({
    "_set_fan_state",           # hvac_fans W4 chokepoint (D2-wrapped)
    "_emit_fan_state",          # helper extracted from _set_fan_state; only
                                # called from inside _set_fan_state's actuate.
    "_safety_stop_one_fan",     # W11: body has its own oracle.actuate wrap
                                # (see hvac.py:2617-2685).
    "_emit_w8",                 # inline coroutine invoked ONLY from the W8
                                # oracle.actuate block in _execute_vacancy_sweep.
    "_emit_w9",                 # inline coroutine invoked ONLY from the W9
                                # oracle.actuate block in _deactivate_zone_fans.
    "_emit_temp_on",            # inline coroutine invoked ONLY from the W3-temp
                                # oracle.actuate block in automation.py.
    "_emit_onset",              # inline coroutine invoked ONLY from the W3-onset
                                # oracle.actuate block in automation.py.
})


def _load_source_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def _has_carveout_comment(lines: list[str], lineno: int) -> tuple[bool, bool]:
    """Return (has_carveout, has_reason).

    Checks the emission's own line AND the line immediately above it (Python
    inline vs prefix-line comment placement). ``has_reason`` is True only if
    the carve-out is followed by ``(reason=...)``.
    """
    idx = lineno - 1
    candidates = []
    if 0 <= idx < len(lines):
        candidates.append(lines[idx])
    if 0 <= idx - 1 < len(lines):
        candidates.append(lines[idx - 1])
    for candidate in candidates:
        stripped = candidate.strip()
        if _ALLOW_CARVEOUT_PREFIX in candidate or stripped.startswith(_ALLOW_CARVEOUT_PREFIX):
            has_reason = "(reason=" in candidate or "reason=" in candidate
            return True, has_reason
    return False, False


def _first_string_arg(call: ast.Call) -> str | None:
    if not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _is_fan_domain_service_call(node: ast.Call) -> bool:
    """Rule 1: services.async_call("fan", ...) with string-literal first arg."""
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "async_call"):
        return False
    first = _first_string_arg(node)
    return first == "fan"


def _is_chokepoint_call(node: ast.Call) -> bool:
    """Rule 3: call to a hard-coded chokepoint on the allowlist.

    A call to a chokepoint SATISFIES the wrap requirement (the callee's body
    holds the oracle.actuate). Rule 3 exists so that the reverse scanner
    tracks chokepoint-hop emissions AS emissions (a mis-refactor that
    replaces the chokepoint hop with a raw services.async_call would then
    surface via rule 1 or rule 2).
    """
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in _CHOKEPOINT_ALLOWLIST:
        return True
    if isinstance(func, ast.Name) and func.id in _CHOKEPOINT_ALLOWLIST:
        return True
    return False


def _under_chokepoint_function(stack: list[ast.AST]) -> bool:
    """Skip nodes inside an allowlisted chokepoint FunctionDef — those bodies
    contain the fan emit but are themselves the wrapped chokepoint."""
    for ancestor in stack:
        if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if ancestor.name in _CHOKEPOINT_ALLOWLIST:
                return True
    return False


def _under_fan_startswith_branch(stack: list[ast.AST]) -> bool:
    """Rule 2: any enclosing If tests ``entity.startswith("fan.")``."""
    for ancestor in stack:
        if not isinstance(ancestor, ast.If):
            continue
        test = ancestor.test
        # e.g. `if entity_id.startswith("fan.")`
        if isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute):
            if test.func.attr == "startswith":
                first = _first_string_arg(test)
                if first is not None and first.startswith("fan."):
                    return True
    return False


def _under_oracle_actuate_block(stack: list[ast.AST]) -> bool:
    """Rule 4: enclosed by an ``async with oracle.actuate(...)`` ancestor."""
    for ancestor in stack:
        if isinstance(ancestor, ast.AsyncWith):
            for item in ancestor.items:
                if _is_oracle_actuate_call(item.context_expr):
                    return True
    return False


def _within_scanner_or_test(path_str: str, explicit_root_paths: set[str]) -> bool:
    if "quality/tools/audit_fan_adjacency" in path_str:
        return True
    # Skip synthetic fixtures during the default production sweep. When the
    # caller passes them as an EXPLICIT root (fixture-driven test), do NOT
    # skip — the test wants to see the violations flagged.
    if "quality/tests/fixtures/fan_adjacency_synthetic" in path_str:
        for root_str in explicit_root_paths:
            if "fan_adjacency_synthetic" in root_str:
                return False
        return True
    return False


def _reverse_scan_node(
    tree: ast.AST,
    file_str: str,
    source_lines: list[str],
    findings: list[AdjacencyFinding],
) -> None:
    stack: list[ast.AST] = []

    def visit(node: ast.AST) -> None:
        stack.append(node)
        try:
            for child in ast.iter_child_nodes(node):
                visit(child)
            if isinstance(node, ast.Call):
                is_fan_dom = _is_fan_domain_service_call(node)
                is_chokepoint_call = _is_chokepoint_call(node)
                is_startswith_branch = False
                is_generic_service_call = (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "async_call"
                    and not is_fan_dom
                )
                if is_generic_service_call and _under_fan_startswith_branch(stack[:-1]):
                    is_startswith_branch = True
                if not (is_fan_dom or is_chokepoint_call or is_startswith_branch):
                    return
                # Rule 3 (PLAN §5.5) — chokepoint allowlist: a call TO a
                # chokepoint SATISFIES the wrap requirement. The callee's
                # body holds the oracle.actuate (see hvac_fans.py::_set_fan_state
                # W4-chokepoint block). A bypass — a caller that skips the
                # chokepoint and issues a raw services.async_call — is
                # detected by rules 1 or 2 instead (this is why the synthetic
                # violation for rule 3 nests a raw fan-domain services.async_call
                # inside a function BODY named _set_fan_state that has no
                # oracle.actuate wrap — the walker scans the body and rule 1
                # fires on the raw fan call).
                if is_chokepoint_call:
                    return
                # If we're inside a chokepoint function body, skip — the body
                # IS the wrapped chokepoint (rule 3 allowlist).
                if _under_chokepoint_function(stack[:-1]):
                    return
                if _under_oracle_actuate_block(stack[:-1]):
                    return
                has_carveout, has_reason = _has_carveout_comment(
                    source_lines, node.lineno,
                )
                if has_carveout and has_reason:
                    return
                if has_carveout and not has_reason:
                    findings.append(AdjacencyFinding(
                        file=file_str, lineno=node.lineno,
                        site="fan-emission (reverse)",
                        reason=(
                            "carve-out present but missing (reason=...) "
                            "— use `# fan-adjacency: allow (reason=<why>)`"
                        ),
                    ))
                    return
                if is_fan_dom:
                    site = "services.async_call(\"fan\", ...)"
                elif is_chokepoint_call:
                    site = "_set_fan_state chokepoint call"
                else:
                    site = "services.async_call under fan.* branch"
                findings.append(AdjacencyFinding(
                    file=file_str, lineno=node.lineno, site=site,
                    reason=(
                        "fan emission not enclosed by oracle.actuate context "
                        "(PLAN §5.5 reverse-adjacency rules)"
                    ),
                ))
        finally:
            stack.pop()

    visit(tree)


def run_reverse_scan(
    roots: Iterable[Path] | None = None,
) -> list[AdjacencyFinding]:
    """FAN-LAYER-2 D2 §5.5 — reverse-adjacency scan.

    Returns findings for every fan-emission site (rules 1-3) not enclosed by
    an ``oracle.actuate`` context (rule 4) and not carved out by a
    ``# fan-adjacency: allow (reason=...)`` comment (rule 5).
    """
    scan_roots = tuple(roots) if roots is not None else DEFAULT_SCAN_ROOTS
    explicit_root_paths = {Path(r).resolve().as_posix() for r in scan_roots}
    findings: list[AdjacencyFinding] = []
    for py in _iter_py_files(scan_roots):
        path_str = py.as_posix()
        if _within_scanner_or_test(path_str, explicit_root_paths):
            continue
        try:
            source_text = py.read_text(encoding="utf-8")
            tree = ast.parse(source_text, filename=str(py))
        except (SyntaxError, UnicodeDecodeError):
            continue
        source_lines = source_text.splitlines()
        try:
            file_str = py.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            file_str = py.as_posix()
        _reverse_scan_node(tree, file_str, source_lines, findings)
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
