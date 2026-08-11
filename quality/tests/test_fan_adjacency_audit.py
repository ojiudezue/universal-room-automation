"""FAN-LAYER-1 D8 M1 — wire the fan-adjacency AST walker into pytest.

Session 1 (2026-08-10) has zero consult sites — the walker returns zero
findings trivially. Later sessions add real writers; this test guards
that every consult stays IMMEDIATELY adjacent to its
``services.async_call`` per PLAN §7.9 TOCTOU discipline.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from quality.tools.audit_fan_adjacency import run_audit  # noqa: E402


def test_fan_adjacency_audit_clean():
    findings = run_audit()
    assert findings == [], (
        "fan-adjacency violations detected:\n  "
        + "\n  ".join(str(f) for f in findings)
    )
