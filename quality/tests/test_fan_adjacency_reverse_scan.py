"""FAN-LAYER-2 D2 §5.5 — reverse-adjacency scanner test.

Drives ``run_reverse_scan`` against the 5 synthetic fixtures under
``quality/tests/fixtures/fan_adjacency_synthetic/`` and asserts each of the
four violation shapes is flagged AND the valid carve-out is not. Also asserts
that a full production scan (default roots) returns ZERO findings — the D2
wraps + `# fan-adjacency: allow (reason=...)` carve-outs must cover every
existing fan emission site.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quality.tools.audit_fan_adjacency import (  # noqa: E402
    run_audit,
    run_reverse_scan,
)

FIXTURE_DIR = REPO_ROOT / "quality" / "tests" / "fixtures" / "fan_adjacency_synthetic"


def _findings_for(filename: str, findings) -> list:
    return [f for f in findings if f.file.endswith(filename)]


def test_fan_adjacency_reverse_scan_flags_synthetic_violations() -> None:
    findings = run_reverse_scan(roots=[FIXTURE_DIR])

    # Rule 1: direct fan-domain call, no wrap.
    v1 = _findings_for("violation_direct_fan_domain.py", findings)
    assert v1, "reverse scanner MUST flag direct fan-domain services.async_call"

    # Rule 2: generic services.async_call under startswith("fan.") branch.
    v2 = _findings_for("violation_startswith_fan_branch.py", findings)
    assert v2, "reverse scanner MUST flag services.async_call under fan.* branch"

    # Rule 3: bare _set_fan_state call without oracle.actuate ancestor.
    v3 = _findings_for("violation_set_fan_state_taint.py", findings)
    assert v3, "reverse scanner MUST flag _set_fan_state chokepoint call outside actuate"

    # Rule 5 partial: carve-out with no reason.
    v4 = _findings_for("violation_carveout_missing_reason.py", findings)
    assert v4, "reverse scanner MUST flag carve-out missing (reason=...)"
    assert any("(reason=" in f.reason for f in v4), (
        "the flagged carve-out finding should call out the missing reason clause"
    )

    # Rule 5 valid: proper carve-out with reason — MUST NOT be flagged.
    v_ok = _findings_for("allow_carveout_valid.py", findings)
    assert not v_ok, (
        f"valid carve-out should not be flagged; got {v_ok!r}"
    )


def test_forward_adjacency_audit_still_clean_post_d2() -> None:
    """FAN-LAYER-1 forward walker: post-D2 the 7 new actuate wraps all contain
    inner services.async_call bodies. Forward scan MUST remain clean.
    """
    findings = run_audit()
    assert findings == [], f"forward-adjacency audit regressed: {findings!r}"


def test_reverse_scan_clean_over_production_tree() -> None:
    """After D2 all in-tree fan emission sites are either enclosed in
    oracle.actuate contexts or carve out with `# fan-adjacency: allow
    (reason=...)`. Default-root reverse scan MUST return zero findings.
    """
    findings = run_reverse_scan()
    if findings:
        formatted = "\n  ".join(str(f) for f in findings)
        raise AssertionError(
            f"reverse-adjacency scan found {len(findings)} unwrapped fan "
            f"emission site(s):\n  {formatted}"
        )
