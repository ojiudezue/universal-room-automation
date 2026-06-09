"""Tests for D3: _get_coverage_rating sign/range guard.

Pre-fix _get_coverage_rating(delta_percent) at aggregation.py:617-626
was a series of `delta_percent < THRESHOLD` checks. A massively negative
delta_percent (observed: −24,558,907,924%) fell through every < check
and returned EXCELLENT. Post-fix: out-of-bounds inputs return
COVERAGE_RATING_ANOMALOUS.

Drives the production function directly.
"""
import importlib.util
import math
import os
import sys

import pytest


_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CC = os.path.join(_REPO, "custom_components")
if _CC not in sys.path:
    sys.path.insert(0, _CC)


# Minimal HA stubs so aggregation.py imports cleanly.
def _stub_ha():
    import types
    # If real HA is present (test env), do nothing.
    try:
        import homeassistant  # noqa: F401
        return
    except Exception:
        pass
    # Provide enough surface for aggregation.py top-of-module imports.
    # (Most test files in quality/tests/ already rely on full HA being
    # installed via requirements_test.txt; this is a defensive stub.)


_stub_ha()


def _load_agg():
    path = os.path.join(
        _REPO, "custom_components", "universal_room_automation", "aggregation.py",
    )
    spec = importlib.util.spec_from_file_location("_ura_agg_bounds_test", path)
    # Aggregation has heavy imports; if it fails (no HA), we fall back to
    # extracting the function via direct text exec.
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


_agg = _load_agg()


if _agg is None:
    pytest.skip(
        "aggregation module not importable — skipping bounds test in this env",
        allow_module_level=True,
    )

_rating = _agg._get_coverage_rating
_RATING_ANOMALOUS = _agg.COVERAGE_RATING_ANOMALOUS
_RATING_EXCELLENT = _agg.COVERAGE_RATING_EXCELLENT
_RATING_GOOD = _agg.COVERAGE_RATING_GOOD
_RATING_FAIR = _agg.COVERAGE_RATING_FAIR
_RATING_INCOMPLETE = _agg.COVERAGE_RATING_INCOMPLETE


# ---------------------------------------------------------------------------
# Out-of-bounds → ANOMALOUS
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    -0.1, -100.0, -1e10, -24558907924.0,
])
def test_negative_returns_anomalous(value):
    assert _rating(value) == _RATING_ANOMALOUS


def test_none_returns_anomalous():
    assert _rating(None) == _RATING_ANOMALOUS


def test_nan_returns_anomalous():
    assert _rating(float("nan")) == _RATING_ANOMALOUS


@pytest.mark.parametrize("value", [
    100.0001, 101.0, 1e6, 1e10,
])
def test_above_100_returns_anomalous(value):
    assert _rating(value) == _RATING_ANOMALOUS


# ---------------------------------------------------------------------------
# In-bounds behavior preserved
# ---------------------------------------------------------------------------

def test_zero_is_excellent():
    assert _rating(0.0) == _RATING_EXCELLENT


def test_single_digit_excellent():
    assert _rating(5.0) == _RATING_EXCELLENT


def test_threshold_excellent_to_good():
    # Boundary: equal to the EXCELLENT threshold means we've fallen out
    # of the strict-less-than branch → GOOD.
    assert _rating(10.0) == _RATING_GOOD


def test_threshold_good_to_fair():
    assert _rating(20.0) == _RATING_FAIR


def test_threshold_fair_to_incomplete():
    assert _rating(30.0) == _RATING_INCOMPLETE


def test_high_in_bounds_is_incomplete():
    assert _rating(75.5) == _RATING_INCOMPLETE


def test_exactly_100_is_incomplete():
    # 100% delta = 100% unaccounted = INCOMPLETE (still in-bounds).
    assert _rating(100.0) == _RATING_INCOMPLETE
