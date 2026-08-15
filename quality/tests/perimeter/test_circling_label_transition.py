"""CIRCLING-LABEL-1 D1 + D2 + D4 + D5 + D5b + D7 tests.

Covers:
  - D1: `ExteriorTrack` dataclass carries the two ledger fields with
    the annotated `set[str]` type.
  - D2: `_classification_transition_exemption_permitted` branch matrix
    (linker absent, tracking disabled, target-class already dispatched,
    safeword window active/inactive, strict `<=` boundary, import
    presence).
  - D4: safeword window outranks the exemption (I3); after expiry, the
    next escalating hop bypasses cooldown.
  - D5: coercion RAISE branch on the exemption dispatch (severity
    stays HIGH under home_day + circling — coerced MEDIUM cannot raise).
  - D5b: single-camera nighttime approach/circling exemption survives
    XCORR-1's burst-demote (HIGH-1 pin).
  - D7: exemption hop is NOT deduplicated against the baseline hop
    under today's contextual severity map (MED-2 pin).
"""
from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta, timezone
from typing import get_type_hints
from unittest.mock import AsyncMock, MagicMock

import pytest

# Reuse the founding-case bootstrap (stub HA modules + module loader).
from quality.tests.perimeter.test_circling_founding_case import (
    CAMS,
    SENSORS,
    PerimeterAlertManager,
    Severity,
    _const,
    _etl,
    _make_hass_with_linker,
    _observe,
    _perimeter,
    _run,
    _setup,
)


# --- D1: dataclass shape -----------------------------------------------------


def test_exterior_track_dataclass_has_transition_ledger():
    ExteriorTrack = _etl.ExteriorTrack
    field_names = {f.name for f in fields(ExteriorTrack)}
    assert "last_dispatched_classification" in field_names
    assert "_dispatched_classifications" in field_names
    # Default construction: str|None -> None; set[str] -> empty set.
    tr = ExteriorTrack(track_id="t1", label="person")
    assert tr.last_dispatched_classification is None
    assert tr._dispatched_classifications == set()
    assert isinstance(tr._dispatched_classifications, set)
    # Annotation is `set[str]` (not bool, not frozenset). PEP 604 /
    # future-annotations means we compare the string.
    ann = ExteriorTrack.__annotations__["_dispatched_classifications"]
    ann_str = ann if isinstance(ann, str) else getattr(ann, "__name__", str(ann))
    assert "set[str]" in ann_str, f"annotation was {ann!r} (expected set[str])"


# --- D2: helper branch matrix -----------------------------------------------


def _make_fixture(house_state: str = "home_day"):
    hass, nm, linker = _make_hass_with_linker(CAMS, house_state=house_state)
    nm._perimeter_silence_until = None
    return hass, nm, linker


def _fresh_mgr(house_state: str = "home_day"):
    hass, nm, linker = _make_fixture(house_state=house_state)
    mgr = _run(_setup(hass))
    return hass, nm, linker, mgr


def _replay_founding_sequence(mgr, linker):
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


def test_transition_exemption_bypasses_cooldown_on_escalation():
    """Founding shape: hop-3 dispatches even though its cooldown would
    block it. Without the exemption gate, dispatch count is 2."""
    hass, nm, linker, mgr = _fresh_mgr()
    _replay_founding_sequence(mgr, linker)
    assert nm.async_notify.await_count == 3


def test_no_exemption_on_de_escalation():
    """A track whose classify() returns pass_by (or the same class as
    last) does NOT earn an exemption."""
    hass, nm, linker, mgr = _fresh_mgr()
    # Two hops, same camera. Stub classify to return pass_by both times
    # — the "last" seed comes from hop 1 (pass_by), so hop 2's pass_by
    # is not an escalation.
    linker.classify = lambda _tr: "pass_by"
    t0 = datetime.now(timezone.utc)
    for dt in (0, 30):
        _observe(linker, "back_yard", t0 + timedelta(seconds=dt))
        _run(mgr._async_handle_perimeter_trigger(SENSORS["back_yard"]))
    # Hop 1 dispatches (baseline, no cooldown). Hop 2 blocked (same
    # class, no escalation → no exemption).
    assert nm.async_notify.await_count == 1


def test_no_exemption_when_target_class_already_dispatched():
    """I4: circling already in the ledger blocks a second exemption."""
    hass, nm, linker, mgr = _fresh_mgr()
    # Pre-seed the ledger by dispatching a circling classification once.
    from quality.tests.perimeter.test_circling_founding_case_transition import (
        _StepClassify,
        _drive_stepped_same_camera,
    )
    stub = _StepClassify(["pass_by", "circling", "circling"])
    linker.classify = stub
    _drive_stepped_same_camera(mgr, linker, "back_yard", stub)
    # Hop 1: baseline (pass_by). Hop 2: exemption (circling). Hop 3:
    # I4 blocks (circling in set). So exactly 2 dispatches, not 3.
    assert nm.async_notify.await_count == 2


def test_gate_returns_false_when_linker_absent():
    hass, nm, linker, mgr = _fresh_mgr()
    hass.data[_const.DOMAIN].pop("exterior_track_linker", None)
    assert mgr._classification_transition_exemption_permitted(
        cooldown_key="back_yard",
        entity_id=SENSORS["back_yard"],
        now=datetime.now(timezone.utc),
    ) is False


def test_gate_returns_false_when_tracking_disabled():
    hass, nm, linker, mgr = _fresh_mgr()
    # Seed a track first so find_owning_track would return non-None
    # were tracking enabled — proves the disabled-guard is what blocks.
    _observe(linker, "back_yard", datetime.now(timezone.utc))
    linker.tracking_enabled = False
    assert mgr._classification_transition_exemption_permitted(
        cooldown_key="back_yard",
        entity_id=SENSORS["back_yard"],
        now=datetime.now(timezone.utc),
    ) is False


def test_predicate_boundary_is_strict_le():
    """LOW-2 pin: the escalation predicate is STRICT `<=`. When
    `current_rank == last_rank`, no exemption. If the boundary were
    `<`, this returns True (wrongly permitting a re-dispatch)."""
    hass, nm, linker, mgr = _fresh_mgr()
    now = datetime.now(timezone.utc)
    _observe(linker, "back_yard", now)
    tr = linker._tracks["person"][0]
    # last == current == "approach" (rank 1)
    tr.last_dispatched_classification = "approach"
    linker.classify = lambda _t: "approach"
    assert mgr._classification_transition_exemption_permitted(
        cooldown_key="back_yard",
        entity_id=SENSORS["back_yard"],
        now=now,
    ) is False


def test_import_missing_fails_loud():
    """MED-1 pin: `is_life_safety_hazard` MUST be imported at module
    load. Removing the import produces a NameError inside the helper —
    the outer try swallows it and the helper fail-closes to False.
    Verify the symbol is bound at module scope."""
    assert hasattr(_perimeter, "is_life_safety_hazard"), (
        "is_life_safety_hazard MUST be imported by perimeter_alert (MED-1). "
        "Without this import the exemption gate raises NameError, the outer "
        "try masks it, and the helper masquerades as 'safeword window "
        "blocks' — D4 would then pass for the wrong reason."
    )


def test_ledger_updates_on_baseline_dispatch_too():
    """The ledger update runs on EVERY dispatched_ok, not only exemption
    ones. Otherwise the first exemption gate has no `last` to compare
    against and I2 would trivially permit any classification."""
    hass, nm, linker, mgr = _fresh_mgr()
    _observe(linker, "back_yard", datetime.now(timezone.utc))
    _run(mgr._async_handle_perimeter_trigger(SENSORS["back_yard"]))
    tr = linker._tracks["person"][0]
    assert tr.last_dispatched_classification is not None
    assert tr._dispatched_classifications, (
        "baseline dispatch must seed the ledger"
    )


# --- D4: safeword window outranks exemption (I3) ----------------------------


def test_safeword_window_blocks_transition_exemption():
    hass, nm, linker, mgr = _fresh_mgr()
    # Open a safeword window well into the future.
    nm._perimeter_silence_until = (
        datetime.now(timezone.utc) + timedelta(minutes=30)
    )
    _replay_founding_sequence(mgr, linker)
    # Without safeword the count would be 3; safeword blocks hop 3's
    # exemption (baseline hops 1+2 still fire because NM.async_notify
    # is a spy — the real NM's own suppress happens inside async_notify
    # which our spy doesn't emulate; what matters here is that
    # PerimeterAlertManager DID NOT bypass its own cooldown).
    assert nm.async_notify.await_count == 2, (
        f"expected exactly 2 dispatches (baseline hops 1 + 2, exemption "
        f"blocked by safeword); got {nm.async_notify.await_count}"
    )


def test_transition_exemption_fires_after_safeword_window_expires():
    hass, nm, linker, mgr = _fresh_mgr()
    # Window in the PAST — expired.
    nm._perimeter_silence_until = (
        datetime.now(timezone.utc) - timedelta(minutes=1)
    )
    _replay_founding_sequence(mgr, linker)
    assert nm.async_notify.await_count == 3, (
        "an expired safeword window must not block the exemption"
    )


# --- D5: RAISE branch on exemption dispatch ---------------------------------


def test_exemption_dispatch_severity_survives_coercion():
    hass, nm, linker, mgr = _fresh_mgr()
    _replay_founding_sequence(mgr, linker)
    # Hop-3 dispatch severity must be HIGH (contextual home_day +
    # circling). The 4b coercion for home_day/circling is MEDIUM; since
    # the rule for approach/circling is "only RAISE", MEDIUM < HIGH
    # cannot raise → severity stays HIGH.
    sev_names = [
        getattr(c.kwargs["severity"], "name", None)
        for c in nm.async_notify.await_args_list
    ]
    assert sev_names.count("HIGH") == 1
    assert sev_names[-1] == "HIGH", (
        f"final (hop-3) dispatch severity should be HIGH; sev sequence was "
        f"{sev_names}"
    )


# --- D5b: single-camera nighttime exemption survives XCORR-1 ----------------


def test_exemption_dispatch_severity_survives_xcorr1_single_camera_night():
    """HIGH-1 pin: `home_night` at 02:00 CDT, three same-camera hops
    all within cooldown. Without the XCORR-1 short-circuit, guards 2/3/
    4/5 all pass and XCORR-1 DEMOTES hop-2 and hop-3 to LOW. With the
    short-circuit, both exemption dispatches keep their contextual
    severity (approach → home_night is CRITICAL under the plan; at
    minimum the severity must NOT be LOW)."""
    hass, nm, linker, mgr = _fresh_mgr(house_state="home_night")

    # Force XCORR-1's night-window guard to accept "now" so the demote
    # path reaches guard 5. `_evaluate_burst_demotion` reads
    # `PERIMETER_BURST_NIGHT_WINDOW` from module const; monkeypatching
    # `PERIMETER_BURST_NIGHT_ONLY` to False lets the helper skip the
    # window check entirely (equivalent to being inside the window).
    orig_night_only = _perimeter.PERIMETER_BURST_NIGHT_ONLY
    _perimeter.PERIMETER_BURST_NIGHT_ONLY = False
    try:
        from quality.tests.perimeter.test_circling_founding_case_transition import (  # noqa: E501
            _StepClassify,
            _drive_stepped_same_camera,
        )
        stub = _StepClassify(["pass_by", "approach", "circling"])
        linker.classify = stub
        _drive_stepped_same_camera(mgr, linker, "back_yard", stub)
    finally:
        _perimeter.PERIMETER_BURST_NIGHT_ONLY = orig_night_only

    assert nm.async_notify.await_count == 3, (
        f"expected 3 dispatches (baseline + 2 exemptions); got "
        f"{nm.async_notify.await_count}"
    )
    sev_names = [
        getattr(c.kwargs["severity"], "name", None)
        for c in nm.async_notify.await_args_list
    ]
    # Hop-2 and hop-3 are exemption dispatches — MUST NOT be LOW
    # (that would prove XCORR-1 demoted them).
    assert sev_names[1] != "LOW" and sev_names[2] != "LOW", (
        f"exemption dispatches must not be XCORR-1 demoted to LOW; got "
        f"severities {sev_names}"
    )
    # And the last_burst_decision on this camera records the short-
    # circuit reason for the LAST evaluated dispatch.
    dec = mgr._last_burst_decision.get("back_yard")
    assert dec is not None, "burst decision must be recorded"
    assert dec["reason"] == "classification_transition_exemption", (
        f"last burst decision reason must be the transition-exemption "
        f"short-circuit; got {dec['reason']!r}"
    )


# --- D7: NM dedup non-collision on exemption path ---------------------------


def test_exemption_hop_not_deduplicated_against_baseline_hop():
    """MED-2 pin. Under today's contextual severity map, (person,
    pass_by) resolves to LOW/MEDIUM/DIGEST in every house state — never
    HIGH — so the hop-3 exemption dispatch (HIGH circling) has a
    distinct severity from the hop-1 baseline (LOW/DIGEST pass_by). The
    NM dedup key `(coordinator_id, title, location, severity)`
    therefore cannot collide, and hop 3 does NOT dedup with hop 1.

    Verified structurally by asserting the dispatched severities of
    hop-1 and hop-3 differ; this is the observable proxy for
    non-collision without spinning up a real NM instance."""
    hass, nm, linker, mgr = _fresh_mgr()
    _replay_founding_sequence(mgr, linker)
    sev_names = [
        getattr(c.kwargs["severity"], "name", None)
        for c in nm.async_notify.await_args_list
    ]
    assert len(sev_names) == 3
    hop1_sev = sev_names[0]
    hop3_sev = sev_names[2]
    assert hop1_sev != hop3_sev, (
        f"hop-1 and hop-3 must differ in severity for dedup non-collision; "
        f"got hop1={hop1_sev}, hop3={hop3_sev}. If this test ever fails, "
        f"extend NM._is_deduplicated key to include classification (one-line "
        f"change per plan D7)."
    )
