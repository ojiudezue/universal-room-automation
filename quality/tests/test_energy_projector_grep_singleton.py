"""R7 — AST-based singleton CI enforcement for the projection primitive.

Per PLANNING_net_energy_program_R1_R7_R2.md R7 §Acceptance:
    "post-migration, grep of `soc.*\\+.*rate.*\\*.*hours` (and variants)
    returns ZERO hits outside `energy_projector.py`."

**AST implementation (2026-07-16 fix-up per Tier-3 reviews A/C/D):**
The original grep-based scanner missed evasive spellings that reviewer C
proved could slip past (e.g. `soc_now + net_rate * remaining_hours +
solar_surplus`). It also structurally exempted any line merely
containing the string `not R7_USE_UNIFIED_PROJECTOR` (including in
comments), not actual `if` statements. This rewrite:

1. Parses each coordinator module with ``ast`` and walks BinOp shapes
   inside function bodies matching ``<name> + <name> * <name>`` (with an
   optional additive ``+ <name>`` surplus tail), where the identifiers
   contain any of the substrings ``soc``, ``rate``, ``hour``, or ``min``
   (case-insensitive). This catches:
     - `soc + rate * rate_hours + solar_surplus`   (pre-R7 shape)
     - `soc_now + net_rate * remaining_hours + solar_surplus`  (C-evasive)
     - `soc + effective_rate * rate_hours`         (A-evasive; no surplus)
     - `soc + (mins / 60) * rate + surplus`        (attain shape)
2. Scans ALL files under ``domain_coordinators/`` (D-MED-1 widening)
   with two exemptions: the primitive module itself, and any hit whose
   enclosing ``If`` node is a ``not R7_USE_UNIFIED_PROJECTOR`` guard.
3. Honors an ``R7-SINGLETON-EXEMPT`` line marker for defensive-rescue
   lines that can't be structurally exempted.
4. D-LOW-1: pins the marker line count in ``energy_battery.py`` at the
   known-good value (9). A change requires an intentional bump.

Bug Class: #53 (computed-but-not-consumed at projection scale).
"""
from __future__ import annotations

import ast
from pathlib import Path

_EXEMPT_MARKER = "R7-SINGLETON-EXEMPT"
_TRIGGER_SUBSTRINGS = ("soc", "rate", "hour", "min")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COORD_DIR = (
    _REPO_ROOT
    / "custom_components"
    / "universal_room_automation"
    / "domain_coordinators"
)
_PROJECTOR_FILE = _COORD_DIR / "energy_projector.py"
_ENERGY_BATTERY = _COORD_DIR / "energy_battery.py"

# Known-good exempt-marker count in energy_battery.py (D-LOW-1). Bump
# only with cycle-scoped justification.
_EXPECTED_EXEMPT_MARKER_COUNT = 9


def _name_matches(node: ast.AST) -> bool:
    """True iff the node is a Name/Attribute whose identifier trips a
    trigger substring, OR a parenthesized/wrapped sub-expression that
    contains such a name (e.g. ``(mins / 60.0)`` — the attain shape).
    """
    if isinstance(node, ast.Name):
        ident = node.id.lower()
        return any(sub in ident for sub in _TRIGGER_SUBSTRINGS)
    if isinstance(node, ast.Attribute):
        ident = node.attr.lower()
        return any(sub in ident for sub in _TRIGGER_SUBSTRINGS)
    if isinstance(node, ast.BinOp):
        # Sub-expression like (mins / 60.0) counts if it contains a
        # trigger-name anywhere in its subtree.
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                if any(s in sub.id.lower() for s in _TRIGGER_SUBSTRINGS):
                    return True
            elif isinstance(sub, ast.Attribute):
                if any(s in sub.attr.lower() for s in _TRIGGER_SUBSTRINGS):
                    return True
        return False
    return False


def _is_projection_shape(node: ast.AST) -> bool:
    """Match the additive-surplus projection shape at the AST level.

    Shapes accepted (all left-associative Python parses):
      A) name + name * name                    (soc + rate * hours)
      B) (name + name * name) + name           (with surplus tail)

    Each name must trip the identifier substring guard. Parenthesized
    sub-expressions are handled naturally because ast unwraps them.
    """
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Add):
        return False

    # Try shape B: outer Add whose left is a `name + name * name` Add
    # and whose right is a name-like token.
    if (
        isinstance(node.left, ast.BinOp)
        and isinstance(node.left.op, ast.Add)
        and _name_matches(node.right)
    ):
        inner = node.left
        # inner must be: name + (name * name)
        if (
            _name_matches(inner.left)
            and isinstance(inner.right, ast.BinOp)
            and isinstance(inner.right.op, ast.Mult)
            and _name_matches(inner.right.left)
            and _name_matches(inner.right.right)
        ):
            return True

    # Shape A: name + (name * name)  (no surplus tail)
    if (
        _name_matches(node.left)
        and isinstance(node.right, ast.BinOp)
        and isinstance(node.right.op, ast.Mult)
        and _name_matches(node.right.left)
        and _name_matches(node.right.right)
    ):
        return True

    return False


def _iter_enclosing_ifs(node: ast.AST, parents: dict[ast.AST, ast.AST]):
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, ast.If):
            yield cur
        cur = parents.get(cur)


def _if_is_kill_switch_fallback(if_node: ast.If) -> bool:
    """True iff the ``If`` test is ``not R7_USE_UNIFIED_PROJECTOR``."""
    test = if_node.test
    if not isinstance(test, ast.UnaryOp) or not isinstance(test.op, ast.Not):
        return False
    operand = test.operand
    return (
        isinstance(operand, ast.Name)
        and operand.id == "R7_USE_UNIFIED_PROJECTOR"
    )


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return [(lineno, source_line), ...] for banned projection shapes.

    Skips: primitive file, kill-switch structural exemptions, and lines
    tagged with the R7-SINGLETON-EXEMPT marker.
    """
    src = path.read_text()
    src_lines = src.splitlines()
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []

    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not _is_projection_shape(node):
            continue
        lineno = getattr(node, "lineno", None)
        if lineno is None:
            continue
        line_src = src_lines[lineno - 1] if lineno - 1 < len(src_lines) else ""
        if _EXEMPT_MARKER in line_src:
            continue
        # Structural kill-switch exemption.
        if any(
            _if_is_kill_switch_fallback(if_node)
            for if_node in _iter_enclosing_ifs(node, parents)
        ):
            continue
        hits.append((lineno, line_src.rstrip()))
    return hits


def test_all_coordinators_have_no_inline_projection():
    """No banned inline projection shape in ANY coordinator (D-MED-1)."""
    offenders: list[tuple[str, int, str]] = []
    for py in sorted(_COORD_DIR.glob("*.py")):
        if py == _PROJECTOR_FILE:
            continue
        for ln, src in _scan_file(py):
            offenders.append((py.name, ln, src))
    assert offenders == [], (
        "R7 singleton violation: inline SOC-at-boundary projection "
        "shape found outside the unified primitive.\n"
        + "\n".join(f"  {name}:{ln}: {src}" for name, ln, src in offenders)
        + "\n\nRoute this projection through "
        "EnergyProjector.project_soc_at_boundary "
        "(see energy_projector.py)."
    )


def test_projector_module_owns_the_expression():
    """Sanity: primitive module retains the additive-surplus expression."""
    text = _PROJECTOR_FILE.read_text()
    assert "effective_rate" in text and "solar_surplus_pct" in text, (
        "energy_projector.py no longer contains the additive-surplus "
        "primitive — R7 singleton owner is missing."
    )


def test_energy_battery_exempt_marker_count_pinned():
    """D-LOW-1: pin the exempt-marker line count in energy_battery.py.

    Fails if someone pastes the marker on a new line without an
    accompanying cycle bump of _EXPECTED_EXEMPT_MARKER_COUNT.
    """
    count = sum(
        1 for line in _ENERGY_BATTERY.read_text().splitlines()
        if _EXEMPT_MARKER in line
    )
    assert count == _EXPECTED_EXEMPT_MARKER_COUNT, (
        f"R7-SINGLETON-EXEMPT marker count in energy_battery.py = {count}, "
        f"expected {_EXPECTED_EXEMPT_MARKER_COUNT}. If this is an "
        "intentional new exempt line, bump _EXPECTED_EXEMPT_MARKER_COUNT "
        "in this test with justification."
    )


# --------------------------------------------------------------------------
# Positive self-tests — the scanner MUST catch the evasive spellings
# that reviewers A and C proved could slip past the pre-fixup regex.
# --------------------------------------------------------------------------


def _scan_snippet(src: str, tmp_path: Path) -> list[tuple[int, str]]:
    p = tmp_path / "fixture.py"
    p.write_text(src)
    return _scan_file(p)


def test_positive_catches_c_evasive_spelling(tmp_path):
    """C's exact evasive spelling MUST be caught."""
    src = (
        "def f(soc_now, net_rate, remaining_hours, solar_surplus):\n"
        "    return soc_now + net_rate * remaining_hours + solar_surplus\n"
    )
    hits = _scan_snippet(src, tmp_path)
    assert len(hits) == 1, f"expected 1 hit, got {hits}"


def test_positive_catches_a_evasive_spelling(tmp_path):
    """A's evasive spelling (no surplus tail) MUST be caught."""
    src = (
        "def f(soc, effective_rate, rate_hours):\n"
        "    return soc + effective_rate * rate_hours\n"
    )
    hits = _scan_snippet(src, tmp_path)
    assert len(hits) == 1, f"expected 1 hit, got {hits}"


def test_positive_catches_pre_r7_canonical_shape(tmp_path):
    """The canonical pre-R7 shape (soc + rate * hours + surplus) is caught."""
    src = (
        "def f(soc, rate, hours, surplus):\n"
        "    return soc + rate * hours + surplus\n"
    )
    hits = _scan_snippet(src, tmp_path)
    assert len(hits) == 1


def test_negative_ignores_unrelated_addmul_shape(tmp_path):
    """Shape with no trigger-substring identifiers must NOT fire."""
    src = (
        "def f(a, b, c, d):\n"
        "    return a + b * c + d\n"
    )
    hits = _scan_snippet(src, tmp_path)
    assert hits == [], f"false-positive: {hits}"


def test_negative_marker_line_is_exempt(tmp_path):
    """Lines carrying the R7-SINGLETON-EXEMPT marker are ignored."""
    src = (
        "def f(soc, rate, hours, surplus):\n"
        "    return soc + rate * hours + surplus  # R7-SINGLETON-EXEMPT\n"
    )
    hits = _scan_snippet(src, tmp_path)
    assert hits == []


def test_negative_kill_switch_branch_is_exempt(tmp_path):
    """Hits inside `if not R7_USE_UNIFIED_PROJECTOR:` are structurally exempt."""
    src = (
        "R7_USE_UNIFIED_PROJECTOR = True\n"
        "def f(soc, rate, hours, surplus):\n"
        "    if not R7_USE_UNIFIED_PROJECTOR:\n"
        "        return soc + rate * hours + surplus\n"
        "    return 0\n"
    )
    hits = _scan_snippet(src, tmp_path)
    assert hits == [], f"kill-switch fallback should be exempt: {hits}"
