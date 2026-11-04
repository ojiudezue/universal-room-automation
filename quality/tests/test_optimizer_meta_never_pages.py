"""OPTIMIZER-META-NEVER-PAGES-1 (2026-11-04): META findings never page NM.

Drives the real ``OptimizationCoordinator._notify_if_severe`` with a
signature-binding fake NM (same harness as test_nm_notify_signature_sites).
Mutation anchor: delete the META guard in ``_notify_if_severe`` →
test_meta_critical_does_not_page goes RED.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

import test_notification_manager  # noqa: F401  (order-hardening, see sibling)
from test_nm_notify_signature_sites import _BindingNM, DOMAIN

from custom_components.universal_room_automation.domain_coordinators.optimization import (
    OptimizationCoordinator, OptimizationFinding, OptimizationDimension,
)


def _coord(nm):
    coord = OptimizationCoordinator.__new__(OptimizationCoordinator)
    coord.hass = SimpleNamespace(data={DOMAIN: {"notification_manager": nm}})
    coord._notify_dedup_state = {}
    coord._notify_dedup_just_set = set()
    return coord


def _finding(dimension, severity, key):
    return OptimizationFinding(
        timestamp=datetime.utcnow().isoformat(),
        level="house", target_id="house",
        dimension=dimension, severity=severity,
        confidence=0.95, score=0.0,
        description=(
            "findings_recent is truncated (0 of 20 shown)... running blind"
        ),
        payload={"source": "llm"},
        dedup_key=(key, "house"),
    )


@pytest.mark.asyncio
async def test_meta_critical_does_not_page():
    nm = _BindingNM()
    await _coord(nm)._notify_if_severe(
        _finding(OptimizationDimension.META, "critical", "llm_meta_c"))
    assert nm.bound == []


@pytest.mark.asyncio
async def test_meta_high_does_not_page():
    nm = _BindingNM()
    await _coord(nm)._notify_if_severe(
        _finding(OptimizationDimension.META, "high", "llm_meta_h"))
    assert nm.bound == []


@pytest.mark.asyncio
@pytest.mark.parametrize("dim", ["meta", "META"])
async def test_meta_string_dimension_does_not_page(dim):
    nm = _BindingNM()
    await _coord(nm)._notify_if_severe(_finding(dim, "critical", "llm_meta_s"))
    assert nm.bound == []


@pytest.mark.asyncio
async def test_non_meta_critical_still_pages():
    nm = _BindingNM()
    await _coord(nm)._notify_if_severe(
        _finding(OptimizationDimension.SENSOR_HEALTH, "critical", "sh_c"))
    assert len(nm.bound) == 1


# Behavioural replacement for the former source-grep
# test_nm_cycle_a2_knob_surface.py::test_optimizer_consumer_wired_to_should_defer_helper
# (its fixed 3000-char window broke when the META guard landed above the gate).
@pytest.mark.asyncio
@pytest.mark.parametrize("defer,expected_pages", [(True, 0), (False, 1)])
async def test_high_finding_honours_should_defer_helper(
    monkeypatch, defer, expected_pages,
):
    from custom_components.universal_room_automation.domain_coordinators import (
        _nm_cycle_a,
    )
    calls = []

    def _fake(hass, finding):
        calls.append(finding)
        return defer

    monkeypatch.setattr(_nm_cycle_a, "should_defer_high_to_digest", _fake)
    nm = _BindingNM()
    f = _finding(OptimizationDimension.SENSOR_HEALTH, "high", "sh_h")
    await _coord(nm)._notify_if_severe(f)
    assert calls == [f]
    assert len(nm.bound) == expected_pages
