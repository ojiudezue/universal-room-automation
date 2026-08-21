"""AC14 + AC14b — the lease gate is at the emit MERGE POINT.

The operator's explicit "single most important thing" for this build is
placement of the ``lease_active`` check in ``_apply_house_state_presets``:

- It MUST be AFTER both preset-decision arms converge (the vacancy-bypass
  arm at ``hvac.py:1892-1894`` and the general ``should_change_preset``
  arm at ``hvac.py:1902-1906``).
- It MUST be BEFORE the ``emit_set_preset_mode`` call at ``hvac.py:~1981``.
- Placing it BEFORE ``should_change_preset`` (rev-4's original wrong
  placement) leaves the vacancy arm unreachable to the gate — a vacancy
  sweep would write ``away`` through a live excursion while
  ``lease_active`` reported clean. AC14b would fail behaviorally.

These tests structurally assert that ordering. They are the adherence
guarantee for the rev-5 placement: a future refactor that moves the
gate upstream of ``should_change_preset`` — even one that keeps AC14
green via a global monkeypatch — will red AC14b_vacancy_arm here.

A full behavioural drive of ``_apply_house_state_presets`` (constructing
a live HVACCoordinator + zone + presence + preset-manager fixture rich
enough to route through the vacancy arm end-to-end) is a substantial
harness — deferred to the follow-up build that lands the D3 site
migrations. This structural test discriminates the rev-4 vs rev-5
placement, which is the specific defect the operator called out.

NEUTER DRILL (performed manually by the builder before shipping):
  1. Comment out the `if _excursion_lease_active(zone_id): continue`
     block in ``hvac.py`` at the merge point.
  2. Run this test file: ``AC14_lease_gate_precedes_emit`` MUST fail.
  3. Restore. Re-run. MUST pass. Confirm ``git status`` clean.

  Additionally: move the gate BEFORE ``should_change_preset`` (i.e.
  before ``hvac.py:~1889``). ``AC14b_lease_gate_dominates_vacancy_arm``
  MUST fail (the gate now sits upstream of the vacancy bypass — the
  vacancy arm reaches emit without consulting the gate).
"""

from __future__ import annotations

import os
import re


HVAC_PY = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation",
    "domain_coordinators", "hvac.py",
)


def _load_source() -> str:
    with open(HVAC_PY, "r", encoding="utf-8") as f:
        return f.read()


def _slice_apply_house_state_presets(src: str) -> tuple[str, int]:
    """Return (body_text, start_line_offset) of _apply_house_state_presets."""
    m = re.search(
        r"^    async def _apply_house_state_presets\b",
        src, flags=re.MULTILINE,
    )
    assert m, "_apply_house_state_presets not found in hvac.py"
    start = m.start()
    # Find the next top-level (4-space indent) `def`/`async def` after start.
    tail = src[m.end():]
    n = re.search(
        r"^    (?:async def|def) ",
        tail, flags=re.MULTILINE,
    )
    end = m.end() + (n.start() if n else len(tail))
    body = src[start:end]
    line_offset = src[:start].count("\n") + 1
    return body, line_offset


def _line_of(body: str, needle: str) -> int:
    """Return 1-indexed line within body where needle first appears.
    Raises AssertionError if absent."""
    idx = body.find(needle)
    assert idx >= 0, f"expected substring not found in slice: {needle!r}"
    return body.count("\n", 0, idx) + 1


def test_apply_house_state_presets_slice_exists():
    body, _ = _slice_apply_house_state_presets(_load_source())
    # Both arms must still exist — if either is renamed/removed this
    # whole placement analysis needs re-verification.
    assert "Bypass should_change_preset() manual guard for vacancy" in body
    assert "should_change_preset(" in body
    assert "emit_set_preset_mode(" in body
    assert "lease_active" in body


def test_AC14_lease_gate_precedes_emit():
    """AC14 — with an active lease on zone Z, the tick MUST NOT reach
    the ``emit_set_preset_mode`` call. Structurally: the lease gate
    must appear in the slice BEFORE the emit call, and must contain
    a ``continue`` on the lease-active branch."""
    body, _ = _slice_apply_house_state_presets(_load_source())

    lease_line = _line_of(body, "_excursion_lease_active(zone_id)")
    emit_line = _line_of(body, "_s1_written = await emit_set_preset_mode(")

    assert lease_line < emit_line, (
        "AC14: lease gate must PRECEDE the emit_set_preset_mode call. "
        f"lease_line={lease_line} emit_line={emit_line}. "
        "Gate must guard the WRITE."
    )

    # And the gate MUST use `continue` on lease-active (DROP, not queue,
    # per §4.4 — matches the comfort-gate DROP policy at
    # hvac_setpoint.py:12-16).
    #
    # Extract the ~10 lines around the lease-active branch and require
    # a `continue` appears inside the gate's if-body.
    gate_idx = body.find("if _excursion_lease_active(zone_id)")
    assert gate_idx >= 0, "expected `if _excursion_lease_active(zone_id)` gate"
    window = body[gate_idx: gate_idx + 800]
    assert re.search(
        r"if _excursion_lease_active\(zone_id\):[\s\S]{0,400}?\n\s+continue",
        window,
    ), (
        "AC14: lease-active branch must DROP the decision this tick "
        "(a bare `continue`), not queue it. §4.4."
    )


def test_AC14b_lease_gate_dominates_vacancy_arm():
    """AC14b (MANDATORY, rev-5) — the vacancy bypass arm at
    ``hvac.py:1892-1894`` explicitly skips ``should_change_preset``. If
    the lease gate is placed BEFORE ``should_change_preset``, the vacancy
    arm reaches the emit WITHOUT consulting the gate — a vacancy sweep
    writes ``away`` through a live excursion and ``lease_active`` reports
    clean.

    Adherence check: the lease gate must appear AFTER the vacancy-bypass
    arm's ``continue`` (i.e. after both arms have re-converged). A build
    that puts the gate upstream of the vacancy bypass fails here.
    """
    body, _ = _slice_apply_house_state_presets(_load_source())

    # The vacancy-bypass arm sentinel — a comment line the vacancy arm
    # carries verbatim (see hvac.py:1889).
    vacancy_bypass_line = _line_of(
        body, "Bypass should_change_preset() manual guard for vacancy",
    )
    should_change_preset_call_line = _line_of(
        body, "not self._preset_manager.should_change_preset(",
    )
    lease_line = _line_of(body, "_excursion_lease_active(zone_id)")

    # Both arms converge AFTER should_change_preset (whose `continue`
    # ends the general arm). The lease gate must sit AFTER both.
    assert lease_line > vacancy_bypass_line, (
        "AC14b: lease gate must come AFTER the vacancy-bypass arm "
        f"(vacancy_bypass_line={vacancy_bypass_line}, "
        f"lease_line={lease_line}). Placing it upstream leaves the "
        "vacancy arm unreachable to the gate — a vacancy sweep would "
        "write `away` through a live excursion. Rev-4's original "
        "placement had this defect; rev-5 corrects it."
    )
    assert lease_line > should_change_preset_call_line, (
        "AC14b: lease gate must come AFTER the should_change_preset "
        "consult. Both arms converge past that consult; gating the "
        "MERGE POINT is the structural guarantee that survives future "
        f"arms being added. (should_change_preset_call_line="
        f"{should_change_preset_call_line}, lease_line={lease_line})"
    )


def test_AC14_gate_precedes_arrester_suppress():
    """Correctness detail (from §4.2 discipline): the lease gate must
    also precede the arrester ``suppress`` call, or a deferred tick
    leaves a stray suppression that has to be rolled back. Placing the
    gate before ``suppress`` sidesteps the roll-back entirely."""
    body, _ = _slice_apply_house_state_presets(_load_source())
    lease_line = _line_of(body, "_excursion_lease_active(zone_id)")
    # The S1-site suppress carries this unique comment header —
    # discriminates it from the earlier suppress at hvac.py:1482.
    suppress_line = _line_of(body, "# Suppress arrester for URA-initiated changes")
    assert lease_line < suppress_line, (
        "Lease gate must precede arrester.suppress — otherwise a "
        "deferred tick strands a suppression that needs unwinding. "
        f"lease_line={lease_line} suppress_line={suppress_line}"
    )
