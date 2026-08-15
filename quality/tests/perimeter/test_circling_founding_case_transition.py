"""CIRCLING-LABEL-1 D3 / D3b — founding-shape + multi-escalation tests.

Extends the CIRCLING-SEVERITY-1 founding-case fixture with the
transition-exemption's expected effect: the hop where the linker
classifies the track as `circling` MUST produce ONE dispatched HIGH
page (contextual `home_day + circling`), even though the per-camera
cooldown would otherwise have blocked it.

D3b (MED-3 pin) additionally proves the ledger's `set[str]` semantics
by driving pass_by → approach → circling on the SAME camera; a
bool-implementation collapses the second exemption dispatch and fails
loud here.

See docs/planning/PLANNING_circling_label_transition_dispatch.md D3/D3b.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

# Reuse the founding-case bootstrap: it wires stub `homeassistant.*`
# modules and loads perimeter_alert / exterior_track_linker / const
# via importlib. All names below are safe to import — the module-level
# setup runs exactly once per test session.
from quality.tests.perimeter.test_circling_founding_case import (
    CAMS,
    SENSORS,
    PerimeterAlertManager,
    Severity,
    _const,
    _make_hass_with_linker,
    _observe,
    _run,
    _setup,
)


def _make_hass_no_safeword(*args, **kwargs):
    """Founding fixture + explicit `_perimeter_silence_until = None`.

    A bare MagicMock returns a MagicMock for any getattr, so the I3
    safeword probe (`dt_util.utcnow() < silence_until`) would raise
    TypeError and the exemption gate would fail-closed regardless of
    escalation. Explicit None here ensures the gate reaches the I2/I4
    predicates under test.
    """
    hass, nm, linker = _make_hass_with_linker(*args, **kwargs)
    nm._perimeter_silence_until = None
    return hass, nm, linker


def _dispatched_severities(nm) -> list:
    return [c.kwargs["severity"] for c in nm.async_notify.await_args_list]


# --- D3 ----------------------------------------------------------------------

def _replay_founding(mgr, linker):
    t0 = datetime.now(timezone.utc)
    seq = [
        ("back_yard",      t0),
        ("front_side_ptz", t0 + timedelta(seconds=25)),
        ("back_yard",      t0 + timedelta(seconds=60)),
        ("front_side_ptz", t0 + timedelta(seconds=95)),
        ("back_yard",      t0 + timedelta(seconds=130)),
    ]
    for cam_key, ts in seq:
        _observe(linker, cam_key, ts)
        _run(mgr._async_handle_perimeter_trigger(SENSORS[cam_key]))
    return seq


def test_founding_shape_topology_precondition():
    hass, _nm, linker = _make_hass_no_safeword(CAMS)
    mgr = _run(_setup(hass))
    _replay_founding(mgr, linker)
    assert len(linker._tracks.get("person", [])) == 1


def test_founding_shape_dispatch_count_is_three():
    """Hops 1, 2, AND 3 dispatch. Without the exemption the count is 2."""
    hass, nm, linker = _make_hass_no_safeword(CAMS)
    mgr = _run(_setup(hass))
    _replay_founding(mgr, linker)
    assert nm.async_notify.await_count == 3, (
        f"expected 3 dispatches (2 baseline + 1 transition-exemption), "
        f"got {nm.async_notify.await_count}"
    )


def test_founding_shape_produces_exactly_one_high_circling_page():
    """The hop-3 exemption dispatch resolves to HIGH via the
    home_day + circling contextual severity — hops 1 and 2 are LOW/
    DIGEST/MEDIUM. Exactly ONE HIGH page over the founding sequence."""
    hass, nm, linker = _make_hass_no_safeword(CAMS)
    mgr = _run(_setup(hass))
    _replay_founding(mgr, linker)
    sev_names = [getattr(s, "name", None) for s in _dispatched_severities(nm)]
    high_count = sum(1 for s in sev_names if s == "HIGH")
    assert high_count == 1, (
        f"expected exactly ONE HIGH page (hop-3 circling exemption), "
        f"got severities={sev_names}"
    )


def test_founding_shape_ledger_final_state():
    hass, _nm, linker = _make_hass_no_safeword(CAMS)
    mgr = _run(_setup(hass))
    _replay_founding(mgr, linker)
    tr = linker._tracks["person"][0]
    assert tr.alert_count == 3
    assert tr.last_dispatched_classification == "circling"
    assert "circling" in tr._dispatched_classifications
    # At minimum {pass_by, approach, circling} were dispatched across the
    # 3 hops. approach comes from hop 2 (front_side_ptz is egress-adjacent).
    assert {"pass_by", "approach", "circling"} <= tr._dispatched_classifications


# --- D3b (MED-3 pin: set semantics load-bearing) -----------------------------

class _StepClassify:
    """Externally-stepped classify stub — the test bumps ``step`` between
    hops so each perimeter-handler invocation sees a fresh
    classification, regardless of how many times the handler calls
    classify() internally per hop. Necessary because same-camera
    consecutive observes collapse into a single track HOP (they only
    extend t_last), so a hop-index-based stub would return "pass_by"
    for all three same-camera events."""

    def __init__(self, sequence: list):
        self.sequence = sequence
        self.step = 0

    def __call__(self, _track):
        i = min(self.step, len(self.sequence) - 1)
        return self.sequence[i]


def _drive_stepped_same_camera(mgr, linker, cam_key: str, stub: "_StepClassify"):
    t0 = datetime.now(timezone.utc)
    for i, dt in enumerate([0, 30, 60, 90][: len(stub.sequence)]):
        stub.step = i
        _observe(linker, cam_key, t0 + timedelta(seconds=dt))
        _run(mgr._async_handle_perimeter_trigger(SENSORS[cam_key]))


def test_multi_escalation_pass_by_approach_circling_gets_two_exemptions():
    """Same-camera pass_by -> approach -> circling: exactly 3 dispatches
    (1 baseline + 2 transition exemptions). A bool-based ledger would
    collapse the second exemption and produce 2 dispatches, failing here."""
    hass, nm, linker = _make_hass_no_safeword(CAMS)
    mgr = _run(_setup(hass))
    stub = _StepClassify(["pass_by", "approach", "circling"])
    linker.classify = stub
    _drive_stepped_same_camera(mgr, linker, "back_yard", stub)

    assert nm.async_notify.await_count == 3, (
        f"expected 3 dispatches (1 baseline + 2 transition exemptions); "
        f"a bool ledger would produce 2. got {nm.async_notify.await_count}"
    )
    tr = linker._tracks["person"][0]
    assert tr._dispatched_classifications == {"pass_by", "approach", "circling"}


def test_reescalation_after_downgrade_gets_no_new_exemption():
    """LOW-3 / I4 bound: pass_by -> circling -> approach -> circling
    fires the exemption only on the first `-> circling` transition; the
    second `-> circling` is blocked by I4 (circling in set)."""
    hass, nm, linker = _make_hass_no_safeword(CAMS)
    mgr = _run(_setup(hass))
    stub = _StepClassify(["pass_by", "circling", "approach", "circling"])
    linker.classify = stub
    _drive_stepped_same_camera(mgr, linker, "back_yard", stub)

    # Hop 1: baseline dispatch (pass_by).
    # Hop 2: exemption fires (pass_by -> circling escalation).
    # Hop 3: I2 blocks (approach rank 1 <= last circling rank 2).
    # Hop 4: I4 blocks (circling already in set) — even though I2 alone
    #        would permit (circling vs approach — but approach was
    #        blocked at hop 3 so last stays at "circling", and I4 kicks
    #        in first).
    assert nm.async_notify.await_count == 2, (
        f"expected 2 dispatches (baseline + one -> circling exemption); "
        f"got {nm.async_notify.await_count}"
    )
    tr = linker._tracks["person"][0]
    assert tr._dispatched_classifications == {"pass_by", "circling"}
