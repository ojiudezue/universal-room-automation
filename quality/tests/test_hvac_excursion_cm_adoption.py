"""HVAC-GOVERNED-EXCURSION-1 fix-up round 2 - CM adoption anchor tests.

Item-2 (operator ruling 2026-08-21): every ``begin_excursion`` caller
MUST wrap the wire-write attempt in ``auto_release_on_incomplete``.
"A mechanism that exists but is not adopted does not deliver the
property we wanted."

These source-anchored tests assert the presence of the CM at each of
the 5 begin sites. They are STRUCTURAL adherence tests (not behavioural
drives) — the behavioural drives live in the per-cluster test files
(nudge/compromise/banking/preheat/egress migration).

Their job here is a single, cheap invariant:
    each `begin_excursion(...)` call is followed within the same method
    by an `async with ...auto_release_on_incomplete(...)` block AND a
    `mark_committed()` call inside it.

Neuter anchor: if a future refactor removes the `async with` around
any begin site, this file goes red before behavioural regressions can
hide behind the site-local logic.
"""

from __future__ import annotations

import os
import re


_URA = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation",
    "domain_coordinators",
)


def _slice_method(src: str, method_signature: str) -> str:
    """Return the body of the first method whose signature contains
    ``method_signature``, up to the next top-level def/async def at the
    same 4-space indent level."""
    idx = src.find(method_signature)
    assert idx > 0, f"method not found: {method_signature}"
    tail = src[idx + len(method_signature):]
    n = re.search(r"^    (?:async def|def) ", tail, flags=re.MULTILINE)
    end = idx + len(method_signature) + (n.start() if n else len(tail))
    return src[idx:end]


def _read(name: str) -> str:
    with open(os.path.join(_URA, name), "r", encoding="utf-8") as f:
        return f.read()


def _assert_cm_pattern(body: str, site_name: str):
    """Verify begin_excursion → auto_release_on_incomplete → mark_committed
    ordering within the method body."""
    begin_pos = body.find("begin_excursion(")
    cm_pos = body.find("auto_release_on_incomplete(")
    commit_pos = body.find("mark_committed()")
    assert begin_pos > 0, f"{site_name}: begin_excursion not found"
    assert cm_pos > 0, (
        f"{site_name}: auto_release_on_incomplete CM MUST wrap the wire "
        "write. Item-2 rule: every begin_excursion caller goes through "
        "the CM — a mechanism that exists but is not adopted does not "
        "deliver the property."
    )
    assert commit_pos > 0, (
        f"{site_name}: mark_committed() MUST be called on the success "
        "branch inside the CM block. Without it the CM auto-releases "
        "the excursion after every wire write, even on success."
    )
    assert begin_pos < cm_pos < commit_pos, (
        f"{site_name}: ordering wrong. begin_excursion "
        f"(pos={begin_pos}) must precede auto_release_on_incomplete "
        f"(pos={cm_pos}) which must precede mark_committed "
        f"(pos={commit_pos})."
    )


def test_nudge_site_uses_cm():
    body = _slice_method(
        _read("hvac_override.py"),
        "async def _perform_soft_nudge(",
    )
    _assert_cm_pattern(body, "S5_nudge_start (_perform_soft_nudge)")


def test_compromise_site_uses_cm():
    body = _slice_method(
        _read("hvac_override.py"),
        "async def _apply_compromise(",
    )
    _assert_cm_pattern(body, "S3_compromise (_apply_compromise)")


def test_banking_site_uses_cm():
    body = _slice_method(
        _read("hvac_predict.py"),
        "async def _execute_zone_pre_cool(",
    )
    _assert_cm_pattern(body, "S12_pre_cool (_execute_zone_pre_cool)")


def test_preheat_site_uses_cm():
    body = _slice_method(
        _read("hvac_predict.py"),
        "async def _execute_pre_heat(",
    )
    _assert_cm_pattern(body, "S13_pre_heat (_execute_pre_heat)")


def test_egress_site_uses_cm():
    body = _slice_method(
        _read("hvac_egress.py"),
        "async def _engage_pause(",
    )
    _assert_cm_pattern(body, "S15_egress_pause (_engage_pause)")


def test_no_site_local_release_helper_remains():
    """The pre-fix-up site-local _release_banking_on_incomplete_write
    helper was the second release path; the operator ruled it must be
    removed (only the CM as the single mechanism). Guard against a
    future author re-adding it (or a similar site-local twin)."""
    src = _read("hvac_predict.py")
    # Only comment references allowed. Look for the DEFINITION:
    assert "async def _release_banking_on_incomplete_write(" not in src, (
        "Item-2: site-local incomplete-write release helper was removed "
        "in favour of auto_release_on_incomplete. Do not re-add — the "
        "operator ruled 'no second path'."
    )
