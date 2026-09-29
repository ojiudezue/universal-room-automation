"""HVAC-ANOMALY-BLIND-1 residual A (D4) — behavioural ctor twin of
test_v465_observability_gap.py::test_all_coordinators_pass_suppression_set_to_anomaly_detector.

Runs each coordinator's REAL setup method (HVAC `_setup_diagnostics`, the
others' `async_setup`) until it constructs its AnomalyDetector, then asserts
the detector it built carries the module's `*_UNWIRED_METRICS` declaration
(and still the suppression set). The capture wraps the REAL AnomalyDetector
class, so the assertion reads `det._unwired_metric_names` off a real detector;
setup is stopped right after construction by a BaseException sentinel so no
listener/timer side effects run.

Drill: delete the `unwired_metric_names=` kwarg at any ONE ctor site → exactly
that parametrized case goes RED.
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    coordinator_diagnostics as diag,
    hvac as hvac_mod,
    hvac_const,
    music_following as mf_mod,
    presence as presence_mod,
    safety as safety_mod,
    security as security_mod,
)

_REAL_DETECTOR = diag.AnomalyDetector


class _Built(BaseException):
    """Stops setup right after the detector is constructed."""

    def __init__(self, det):
        super().__init__("detector built")
        self.det = det


def _capturing_detector(*args, **kwargs):
    raise _Built(_REAL_DETECTOR(*args, **kwargs))


def _hass():
    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    hass.config_entries.async_entries.return_value = []
    hass.is_running = True
    return hass


def _setup_call(site):
    hass = _hass()
    if site == "hvac":
        coord = hvac_mod.HVACCoordinator.__new__(hvac_mod.HVACCoordinator)
        coord.hass = hass
        return coord._setup_diagnostics()
    if site == "security":
        return security_mod.SecurityCoordinator(hass).async_setup()
    if site == "safety":
        return safety_mod.SafetyCoordinator(hass).async_setup()
    if site == "music_following":
        return mf_mod.MusicFollowingCoordinator(hass).async_setup()
    if site == "presence":
        return presence_mod.PresenceCoordinator(hass).async_setup()
    raise KeyError(site)


_EXPECTED = {
    "hvac": (hvac_const.HVAC_UNWIRED_METRICS, hvac_const.HVAC_SUPPRESSED_FROM_PERSISTENCE),
    "security": (security_mod.SECURITY_UNWIRED_METRICS,
                 security_mod.SECURITY_SUPPRESSED_FROM_PERSISTENCE),
    "safety": (safety_mod.SAFETY_UNWIRED_METRICS,
               safety_mod.SAFETY_SUPPRESSED_FROM_PERSISTENCE),
    "music_following": (mf_mod.MUSIC_FOLLOWING_UNWIRED_METRICS,
                        mf_mod.MUSIC_FOLLOWING_SUPPRESSED_FROM_PERSISTENCE),
    "presence": (presence_mod.PRESENCE_UNWIRED_METRICS,
                 presence_mod.PRESENCE_SUPPRESSED_FROM_PERSISTENCE),
}


@pytest.mark.parametrize("site", sorted(_EXPECTED))
def test_coordinator_builds_detector_with_unwired_declaration(site, monkeypatch):
    # Each setup imports `from .coordinator_diagnostics import AnomalyDetector`
    # at call time; patch the module object that import will resolve to.
    mod_name = diag.__name__
    targets = {id(diag): diag}
    live = sys.modules.get(mod_name)
    if live is not None:
        targets[id(live)] = live
    for m in targets.values():
        monkeypatch.setattr(m, "AnomalyDetector", _capturing_detector)
    # music_following binds the class at module import (top-level import).
    monkeypatch.setattr(mf_mod, "AnomalyDetector", _capturing_detector)

    with pytest.raises(_Built) as built:
        asyncio.run(_setup_call(site))
    det = built.value.det
    unwired, suppressed = _EXPECTED[site]
    assert det._unwired_metric_names == unwired
    assert det._suppressed_metric_names == suppressed


def test_expected_declarations():
    """The declarations themselves (plan D4)."""
    assert hvac_const.HVAC_UNWIRED_METRICS == frozenset(
        {"comfort_deviation_hours", "egress_pause_frequency"})
    assert security_mod.SECURITY_UNWIRED_METRICS == frozenset({"entry_anomaly_score"})
    assert presence_mod.PRESENCE_UNWIRED_METRICS == frozenset()
    assert safety_mod.SAFETY_UNWIRED_METRICS == frozenset()
    assert mf_mod.MUSIC_FOLLOWING_UNWIRED_METRICS == frozenset()
