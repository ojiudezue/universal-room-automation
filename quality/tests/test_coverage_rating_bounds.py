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
# Repo root too, so `custom_components.universal_room_automation.aggregation`
# resolves as a real package (see _load_agg — relative imports need a parent).
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


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
    """Import aggregation.py AS A PACKAGE MEMBER.

    COVERAGE-RATING-FALSE-ANOMALOUS-1 fixed a hollow anchor here. The
    previous implementation used ``spec_from_file_location`` with a
    standalone module name, which gives the module no parent package, so
    aggregation.py's ``from .const import (...)`` raised
    ``ImportError: attempted relative import with no known parent
    package`` — every time, in every environment. ``_load_agg`` caught
    that and returned None, and the module-level ``pytest.skip`` then
    silently skipped the ENTIRE file. The D3 bounds tests and the B-H4
    post-restart test therefore never executed anywhere despite reading
    as present and passing.

    The real package import works because ``custom_components`` is on
    sys.path (set above). The file-location path is kept only as a
    fallback, and the skip below is now a genuine no-HA guard rather
    than an unconditional one.
    """
    try:
        import importlib

        return importlib.import_module(
            "custom_components.universal_room_automation.aggregation"
        )
    except Exception:
        pass
    path = os.path.join(
        _REPO, "custom_components", "universal_room_automation", "aggregation.py",
    )
    spec = importlib.util.spec_from_file_location("_ura_agg_bounds_test", path)
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
    -100.0, -1e10, -24558907924.0,
])
def test_negative_returns_anomalous(value):
    """Clearly out-of-bounds negatives → ANOMALOUS.

    Fix-up pass C-M2: small negatives in [-2, 0) are now treated as
    timing skew (EXCELLENT), see ``test_small_negative_epsilon_band``.
    """
    assert _rating(value) == _RATING_ANOMALOUS


@pytest.mark.parametrize("value", [
    -0.1, -1.0, -1.99,
])
def test_small_negative_epsilon_band(value):
    """C-M2: delta_percent in [-2, 0) is timing skew, treated as 0."""
    assert _rating(value) == _RATING_EXCELLENT


def test_negative_below_epsilon_band_is_anomalous():
    """Boundary: -2.01% is just below the epsilon band → ANOMALOUS."""
    assert _rating(-2.01) == _RATING_ANOMALOUS
    # The boundary -2.0 exactly is inside [-2, 0) so still EXCELLENT.
    assert _rating(-2.0) == _RATING_EXCELLENT


def test_post_restart_window_negative_is_incomplete():
    """B-H4: post_restart_window=True swaps negative-delta path to INCOMPLETE."""
    assert _rating(-50.0, post_restart_window=True) == _RATING_INCOMPLETE
    # Without the kwarg, still ANOMALOUS.
    assert _rating(-50.0) == _RATING_ANOMALOUS
    # Bounds-clearly-out path (>100) is ANOMALOUS regardless of window.
    assert _rating(1e6, post_restart_window=True) == _RATING_ANOMALOUS


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


# ---------------------------------------------------------------------------
# COVERAGE-RATING-FALSE-ANOMALOUS-1 — midnight re-anchor window
#
# Live evidence (recorder, 2026-09-19): delta_percent -635.30 at 22:56 rated
# INCOMPLETE (post-restart window open) and -643.90 at 00:11 rated ANOMALOUS.
# The value barely moved; only the window closed. These tests pin that the
# excuse now survives the midnight boundary, AND that it does not leak into
# the sustained evening-drift pattern that must keep its ANOMALOUS signal.
# ---------------------------------------------------------------------------


def test_midnight_reanchor_window_negative_is_incomplete():
    """The 00:11 case: negative delta just after midnight → INCOMPLETE."""
    assert _rating(-643.90, midnight_reanchor_window=True) == _RATING_INCOMPLETE


def test_midnight_window_and_post_restart_window_are_independent_excuses():
    """Either window alone is sufficient; neither is required."""
    assert _rating(-50.0, post_restart_window=True) == _RATING_INCOMPLETE
    assert _rating(-50.0, midnight_reanchor_window=True) == _RATING_INCOMPLETE
    assert (
        _rating(-50.0, post_restart_window=True, midnight_reanchor_window=True)
        == _RATING_INCOMPLETE
    )


def test_evening_drift_outside_window_stays_anomalous():
    """DISCRIMINATING case — the fix must NOT silence the real pattern.

    Measured 2026-09-21/22: a negative delta growing monotonically from
    ~14:00 to ~23:00 local (-10 → -58). That is outside both windows, so
    both flags are False and it must still rate ANOMALOUS. If this test
    passes only because the window flag happens to be False at test time,
    it is doing its job — the flag is an argument, not a clock read.
    """
    for observed in (-3.9, -10.0, -23.6, -37.0, -58.8):
        assert (
            _rating(
                observed,
                post_restart_window=False,
                midnight_reanchor_window=False,
            )
            == _RATING_ANOMALOUS
        ), f"evening-drift value {observed} must stay ANOMALOUS"


def test_midnight_window_does_not_excuse_above_100():
    """The window excuses NEGATIVE deltas only, never >100."""
    assert _rating(1e6, midnight_reanchor_window=True) == _RATING_ANOMALOUS
    assert _rating(150.0, midnight_reanchor_window=True) == _RATING_ANOMALOUS


def test_midnight_window_does_not_excuse_none_or_nan():
    assert _rating(None, midnight_reanchor_window=True) == _RATING_ANOMALOUS
    assert (
        _rating(float("nan"), midnight_reanchor_window=True)
        == _RATING_ANOMALOUS
    )


def test_midnight_window_constant_separates_the_two_patterns():
    """The constant must sit above the measured artifact tail (01:20 = 80
    minutes) and well below the earliest measured evening-drift onset
    (14:00 = 840 minutes). This is the sizing argument, pinned."""
    from custom_components.universal_room_automation.const import (
        COVERAGE_MIDNIGHT_REANCHOR_WINDOW_MIN,
    )

    assert COVERAGE_MIDNIGHT_REANCHOR_WINDOW_MIN > 80
    assert COVERAGE_MIDNIGHT_REANCHOR_WINDOW_MIN < 840


# ---------------------------------------------------------------------------
# WIRE-IN ANCHOR — the call site, not just the helper.
#
# Required by the wire-in-anchor rule: a mutation drill that DELETED the
# `midnight_reanchor_window=self._in_midnight_reanchor_window()` argument at
# the extra_state_attributes() call site left every helper-level test above
# green. These tests drive the enclosing method so that deletion goes red.
# ---------------------------------------------------------------------------


def _coverage_sensor_at(local_dt, *, whole_house, attributed,
                        post_restart_window=False):
    """Build an EnergyCoverageDeltaSensor with its inputs pinned.

    __init__ needs a real hass/ConfigEntry, so the instance is created
    without it and only the attributes extra_state_attributes() reads are
    supplied. ``dt_util.now`` is patched IN THE AGGREGATION MODULE so the
    production window helper reads the simulated local time.
    """
    sensor = object.__new__(_agg.EnergyCoverageDeltaSensor)
    sensor._post_restart_window = post_restart_window
    sensor._whole_house_scope = "today"
    sensor._scope_mismatch_warning = None
    sensor._get_whole_house_energy = lambda: whole_house
    sensor._get_rooms_total_energy = lambda: attributed
    sensor._get_zones_total_energy = lambda: 0.0
    sensor._get_house_devices_total_energy = lambda: 0.0
    return sensor


class _FrozenNow:
    def __init__(self, dt):
        self._dt = dt

    def now(self):
        return self._dt


def _attrs_at(monkeypatch, local_dt, **kwargs):
    import datetime as _datetime

    real_dt_util = _agg.dt_util
    frozen = _FrozenNow(local_dt)

    class _Shim:
        def __getattr__(self, name):
            if name == "now":
                return frozen.now
            return getattr(real_dt_util, name)

    monkeypatch.setattr(_agg, "dt_util", _Shim())
    sensor = _coverage_sensor_at(local_dt, **kwargs)
    assert isinstance(local_dt, _datetime.datetime)
    # extra_state_attributes is a @property, not a method.
    return sensor.extra_state_attributes


def test_call_site_midnight_window_yields_incomplete(monkeypatch):
    """00:11 local, attribution exceeds whole-house → INCOMPLETE."""
    import datetime

    attrs = _attrs_at(
        monkeypatch,
        datetime.datetime(2026, 9, 19, 0, 11),
        whole_house=10.0,
        attributed=74.4,  # delta_percent = -644%
    )
    assert attrs["coverage_rating"] == _RATING_INCOMPLETE
    assert attrs["midnight_reanchor_window"] is True


def test_call_site_same_value_at_1500_is_anomalous(monkeypatch):
    """DISCRIMINATOR — identical inputs, only the clock differs.

    This is the pair the live evidence describes in reverse: the value
    must not decide the rating on its own. Outside the window the same
    -644% still rates ANOMALOUS, so the fix cannot be silencing the
    signal generally.
    """
    import datetime

    attrs = _attrs_at(
        monkeypatch,
        datetime.datetime(2026, 9, 19, 15, 0),
        whole_house=10.0,
        attributed=74.4,
    )
    assert attrs["coverage_rating"] == _RATING_ANOMALOUS
    assert attrs["midnight_reanchor_window"] is False


def test_call_site_window_closes_at_the_constant(monkeypatch):
    """Just inside vs just outside COVERAGE_MIDNIGHT_REANCHOR_WINDOW_MIN."""
    import datetime

    from custom_components.universal_room_automation.const import (
        COVERAGE_MIDNIGHT_REANCHOR_WINDOW_MIN as _W,
    )

    inside = datetime.datetime(2026, 9, 19) + datetime.timedelta(minutes=_W - 1)
    outside = datetime.datetime(2026, 9, 19) + datetime.timedelta(minutes=_W)

    assert (
        _attrs_at(monkeypatch, inside, whole_house=10.0, attributed=74.4)[
            "coverage_rating"
        ]
        == _RATING_INCOMPLETE
    )
    assert (
        _attrs_at(monkeypatch, outside, whole_house=10.0, attributed=74.4)[
            "coverage_rating"
        ]
        == _RATING_ANOMALOUS
    )


def test_call_site_healthy_positive_delta_unaffected_inside_window(monkeypatch):
    """No-op path: a normal positive delta rates the same inside the window."""
    import datetime

    attrs = _attrs_at(
        monkeypatch,
        datetime.datetime(2026, 9, 19, 0, 30),
        whole_house=10.0,
        attributed=8.0,  # delta_percent = 20% -> Fair boundary
    )
    assert attrs["coverage_rating"] == _RATING_FAIR
