"""v4.6.2 D4 — Jensen-Shannon divergence pure-Python math tests.

Tests the _js_divergence() function in regime_detector.py directly.
No HA runtime dependency. Verifies:
- Symmetry: JS(P,Q) == JS(Q,P)
- Range: 0 ≤ JS ≤ 1 (log base 2)
- Identical distributions: JS = 0
- Disjoint distributions: JS = 1
- Bucket boundary mapping (0.3 / 0.5 / 0.7)
- Known reference value from academic sources
"""

import sys
from pathlib import Path

# Allow direct import from custom_components without HA runtime
sys.path.insert(
    0,
    str(Path("custom_components/universal_room_automation/domain_coordinators").resolve()),
)

from regime_detector import _js_divergence, _magnitude_bucket


# ---------------------------------------------------------------------------
# Core JS divergence properties
# ---------------------------------------------------------------------------


def test_js_divergence_identical_distributions_is_zero():
    p = {"bedroom": 5, "kitchen": 3, "living_room": 2}
    q = {"bedroom": 10, "kitchen": 6, "living_room": 4}
    js = _js_divergence(p, q)
    assert js < 1e-9, f"Identical proportions must give JS=0, got {js}"


def test_js_divergence_disjoint_distributions_is_one():
    """Fully disjoint distributions give JS(P,Q) = 1 (in log base 2)."""
    p = {"bedroom": 5}
    q = {"kitchen": 5}
    js = _js_divergence(p, q)
    assert abs(js - 1.0) < 1e-9, f"Disjoint distributions must give JS=1, got {js}"


def test_js_divergence_symmetry():
    """JS(P,Q) == JS(Q,P)."""
    p = {"bedroom": 7, "kitchen": 2, "living_room": 1}
    q = {"bedroom": 1, "kitchen": 5, "living_room": 4}
    js_pq = _js_divergence(p, q)
    js_qp = _js_divergence(q, p)
    assert abs(js_pq - js_qp) < 1e-12, (
        f"JS divergence must be symmetric; JS(P,Q)={js_pq}, JS(Q,P)={js_qp}"
    )


def test_js_divergence_range_zero_to_one():
    """JS divergence must lie in [0, 1] for all valid distributions."""
    import random
    rng = random.Random(42)
    rooms = ["bedroom", "kitchen", "living_room", "office", "bathroom"]
    for _ in range(200):
        p = {r: rng.randint(0, 20) for r in rooms}
        q = {r: rng.randint(0, 20) for r in rooms}
        # Skip if both are all-zero for a room (degenerate)
        if sum(p.values()) == 0 or sum(q.values()) == 0:
            continue
        js = _js_divergence(p, q)
        assert 0.0 <= js <= 1.0 + 1e-9, (
            f"JS divergence out of range [0,1]: {js} for p={p}, q={q}"
        )


def test_js_divergence_known_reference_value():
    """Verify against a hand-computed reference case.

    P = uniform over 2 rooms = [0.5, 0.5]
    Q = deterministic first room = [1.0, 0.0]
    M = [0.75, 0.25]
    KL(P||M) = 0.5*log2(0.5/0.75) + 0.5*log2(0.5/0.25)
             = 0.5*(-0.585) + 0.5*(1.0) = 0.2075
    KL(Q||M) = 1.0*log2(1.0/0.75) + 0 = 0.415
    JS = 0.5*(0.2075 + 0.415) = 0.3113
    """
    import math
    p = {"a": 1, "b": 1}   # uniform
    q = {"a": 1, "b": 0}   # deterministic

    # Hand computation (log base 2)
    p_norm = {"a": 0.5, "b": 0.5}
    q_norm = {"a": 1.0, "b": 0.0}
    m = {"a": 0.75, "b": 0.25}
    kl_pm = 0.5 * math.log2(0.5 / 0.75) + 0.5 * math.log2(0.5 / 0.25)
    kl_qm = 1.0 * math.log2(1.0 / 0.75)   # b term: 0*log(anything) = 0
    expected = 0.5 * (kl_pm + kl_qm)

    js = _js_divergence(p, q)
    assert abs(js - expected) < 1e-9, (
        f"Known reference: expected {expected:.6f}, got {js:.6f}"
    )


def test_js_divergence_empty_distribution_returns_zero():
    """Empty distribution must return 0.0 without raising."""
    js = _js_divergence({}, {"bedroom": 5})
    assert js == 0.0
    js2 = _js_divergence({"bedroom": 5}, {})
    assert js2 == 0.0


# ---------------------------------------------------------------------------
# Bucket boundary mapping
# ---------------------------------------------------------------------------


def test_magnitude_bucket_stable_below_0_3():
    """JS < 0.3 must return None (stable, no event)."""
    assert _magnitude_bucket(0.0) is None
    assert _magnitude_bucket(0.29) is None


def test_magnitude_bucket_info_at_0_3():
    """JS in [0.3, 0.5) must return 'INFO'."""
    assert _magnitude_bucket(0.3) == "INFO"
    assert _magnitude_bucket(0.49) == "INFO"


def test_magnitude_bucket_warning_at_0_5():
    """JS in [0.5, 0.7) must return 'WARNING'."""
    assert _magnitude_bucket(0.5) == "WARNING"
    assert _magnitude_bucket(0.69) == "WARNING"


def test_magnitude_bucket_critical_at_0_7():
    """JS >= 0.7 must return 'CRITICAL'."""
    assert _magnitude_bucket(0.7) == "CRITICAL"
    assert _magnitude_bucket(1.0) == "CRITICAL"
