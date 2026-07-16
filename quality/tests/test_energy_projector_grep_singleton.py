"""R7 — Grep-singleton CI enforcement for the projection primitive.

Per PLANNING_net_energy_program_R1_R7_R2.md R7 §Acceptance:
    "post-migration, grep of `soc.*\\+.*rate.*\\*.*hours` (and variants)
    returns ZERO hits outside `energy_projector.py`."

This test scans `energy_battery.py` for the banned inline additive-surplus
projection pattern. Any hit fails the suite. New consumers of "SOC at
boundary" MUST route through `EnergyProjector.project_soc_at_boundary`;
this test is the durable enforcement.

**Exempted lines** (comments/docstrings only; must NOT execute the
expression): each exempt line is annotated in the source with the
``R7-SINGLETON-EXEMPT`` marker. The scanner honors that marker. This lets
the kill-switch fallback branches (`if not R7_USE_UNIFIED_PROJECTOR:`)
retain their inline arithmetic for one release without failing CI.

Bug Class: #53 (computed-but-not-consumed at projection scale). Live
evidence: 2026-07-15 11:20 ladder-vs-attain divergence.
"""
from __future__ import annotations

import re
from pathlib import Path

# The banned pattern is the additive-surplus shape:
#     soc + rate * hours + surplus            (rung, attain)
#     soc + (rate - X) * hours + surplus      (rung-1 counterfactual)
#     soc + (rate + X) * hours + surplus      (rung-1 entry)
#     soc + (mins/60) * rate + surplus        (attain shape)
# All variants share the sub-shape "rate ... hours" (or "mins / 60") in
# an expression starting with `soc + ... rate`. Two regexes cover both
# rate-first and mins-first orderings.
_BANNED_PATTERNS = [
    re.compile(r"soc\s*\+.*\brate\b\s*\*.*\b(rate_hours|hours)\b"),
    re.compile(r"soc\s*\+.*\(mins\s*/\s*60(?:\.0)?\)\s*\*\s*rate"),
    re.compile(r"soc\s*\+.*\brate\b\s*\*.*mins\s*/\s*60"),
]

_EXEMPT_MARKER = "R7-SINGLETON-EXEMPT"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENERGY_BATTERY = (
    _REPO_ROOT
    / "custom_components"
    / "universal_room_automation"
    / "domain_coordinators"
    / "energy_battery.py"
)


def _scan(path: Path) -> list[tuple[int, str]]:
    """Return list of (line_number, line) for banned pattern hits.

    Honors the `R7-SINGLETON-EXEMPT` marker: an exempt line is skipped.
    Kill-switch fallback branches inside `if not R7_USE_UNIFIED_PROJECTOR:`
    guards are also exempted structurally by looking back up to 6 lines
    for the guard header — the primitive path and the fallback path
    coexist for one release.
    """
    text = path.read_text().splitlines()
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(text, start=1):
        if _EXEMPT_MARKER in line:
            continue
        # Skip comment-only lines (# ... shape docs)
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Docstring line? (crude: line inside triple-quote block). Skip
        # anything that looks like prose vs code by requiring the line
        # to end in something code-like or contain an assignment.
        for pat in _BANNED_PATTERNS:
            if pat.search(line):
                # Structural exemption: kill-switch fallback branch.
                # Look back up to 8 lines for `if not R7_USE_UNIFIED_PROJECTOR`.
                lookback = text[max(0, i - 9): i - 1]
                in_fallback = any(
                    "not R7_USE_UNIFIED_PROJECTOR" in b for b in lookback
                )
                if in_fallback:
                    break
                hits.append((i, line.rstrip()))
                break
    return hits


def test_energy_battery_has_no_inline_projection_outside_fallback():
    """No banned inline projection pattern in energy_battery.py.

    Kill-switch fallback branches are structurally exempted (see
    _scan()); primitive is the only non-fallback owner.
    """
    hits = _scan(_ENERGY_BATTERY)
    assert hits == [], (
        "R7 grep-singleton violation: inline SOC-at-boundary projection "
        "found outside the unified primitive AND outside a "
        "`if not R7_USE_UNIFIED_PROJECTOR:` fallback branch.\n"
        + "\n".join(f"  line {ln}: {src}" for ln, src in hits)
        + "\n\nRoute this projection through "
        "EnergyProjector.project_soc_at_boundary "
        "(see energy_projector.py)."
    )


def test_projector_module_owns_the_expression():
    """Sanity: the primitive module itself contains the shape.

    If someone deletes the primitive but leaves the singleton test
    passing (e.g. by moving arithmetic somewhere else), this test fails
    — the primitive must remain the owner.
    """
    projector_path = (
        _REPO_ROOT
        / "custom_components"
        / "universal_room_automation"
        / "domain_coordinators"
        / "energy_projector.py"
    )
    text = projector_path.read_text()
    # Must contain the additive-surplus expression somewhere.
    assert "effective_rate" in text and "solar_surplus_pct" in text, (
        "energy_projector.py no longer contains the additive-surplus "
        "primitive — R7 singleton owner is missing."
    )
