"""EVSE Drain-Precedence — Session B2c-3 fix-up acceptance tests.

Scope: framing-D re-pass HIGH findings.

  H-1 — `_paused_by_dp` is now persisted alongside its siblings (grid_cap
        / battery_drain / fill_priority / arbitrage) via KV
        `evse_dp_paused`, and restored + reclaimed on boot so a restart
        mid-TRANSITIONED does not strand the EVSE off with no owner
        (INV-DP2 breach).

  H-2 — `_apply_dp_reversion` + `_apply_dp_must_start_release` are STICKY
        on deferral: peer-owner OR non-off_peak TOU (reversion) / safety
        peer (must-start) KEEP the DP set membership + "dp" dispatch owner
        so a later tick can retry. The retry driver lives in
        `_dp_decision_tick` — kill-switch hoist for the switch-OFF path,
        HOLD_ONLY orphan-cleanup for the switch-ON restart / normal
        deferred-reversion path.

Test authority: EXECUTED source mutations against production `energy.py`
in a subprocess-isolated pytest run (Reviewer-C pattern). Re-uses the
b2c1 fix-up mutation harness.
"""

from __future__ import annotations

import importlib

_b2c1 = importlib.import_module("test_evse_drain_precedence_session_b2c1_fixup")

_mutate_and_expect_red = _b2c1._mutate_and_expect_red


# ==========================================================================
# H-2 mutation anchors
# ==========================================================================


def test_MUTATION_h2_sticky_reverted_to_eager_discard_makes_sticky_test_red():
    """Revert `_apply_dp_reversion` to eager-discard (drop the set +
    owner BEFORE the peer/TOU checks). The sticky test asserts the DP
    claim SURVIVES a TOU-defer; under the eager mutation, the set is
    emptied first → test goes RED."""
    _mutate_and_expect_red(
        # The anchor is the sticky TOU-defer log line. Replace with the
        # pre-fix eager discard sequence (discard + release BEFORE
        # continue). Uniquely targets the reversion sticky branch.
        swap_from=(
            'if tou_period is not None and tou_period != "off_peak":\n'
            '                _LOGGER.info(\n'
            '                    "drain-precedence release: %s — TOU=%s, keeping DP claim "\n'
            '                    "(sticky)",\n'
            '                    evse_id, tou_period,\n'
            '                )\n'
            '                continue'
        ),
        swap_to=(
            'if tou_period is not None and tou_period != "off_peak":\n'
            '                self._ev._paused_by_dp.discard(evse_id)  # noqa: SLF001\n'
            '                self._ev._release_pause_dispatch_owner(evse_id, "dp")  # noqa: SLF001\n'
            '                continue'
        ),
        test_name=(
            "test_evse_drain_precedence_session_b2b_ii.py::"
            "test_reversion_defers_ensure_on_when_tou_not_off_peak"
        ),
    )


def test_MUTATION_h2_retry_driver_removed_makes_orphan_test_red():
    """Delete the HOLD_ONLY orphan retry-driver block in
    `_dp_decision_tick`. The restart-orphan test (switch-ON path)
    depends on that block calling `_apply_dp_reversion` on a HOLD_ONLY
    carrier with non-empty `_paused_by_dp`; without it, the set never
    drains → RED."""
    _mutate_and_expect_red(
        swap_from=(
            "if (\n"
            "            _dp_on\n"
            "            and self._dp_carrier.state == _DPState.HOLD_ONLY\n"
            "            and self._ev._paused_by_dp  # noqa: SLF001\n"
            "        ):\n"
            "            self._apply_dp_reversion(tou_period=period)"
        ),
        swap_to=(
            "if False and (\n"
            "            _dp_on\n"
            "            and self._dp_carrier.state == _DPState.HOLD_ONLY\n"
            "            and self._ev._paused_by_dp  # noqa: SLF001\n"
            "        ):\n"
            "            self._apply_dp_reversion(tou_period=period)"
        ),
        test_name=(
            "test_evse_drain_precedence_session_b2c1_fixup.py::"
            "test_h2_sticky_orphan_hold_only_retry_dispatches_turn_on_switch_on_path"
        ),
    )


# ==========================================================================
# H-1 mutation anchors (persistence)
# ==========================================================================


def test_MUTATION_h1_save_evse_dp_paused_dropped_makes_ast_test_red():
    """Drop the `evse_dp_paused` KV save from `_save_evse_state`. The
    AST-anchored persistence test looks for the literal key + the save
    call site; without it the source-parse check goes RED.

    Anchors on the KV key STRING; a broader anchor risks catching the
    restore path too."""
    _mutate_and_expect_red(
        swap_from='await db.save_energy_state(\n                "evse_dp_paused",\n                _json.dumps(list(self._ev._paused_by_dp)),\n            )',
        swap_to='pass  # mutation: evse_dp_paused save removed',
        test_name=(
            "test_evse_drain_precedence_session_b2c3_fixup.py::"
            "test_h1_evse_dp_paused_is_saved_alongside_siblings"
        ),
    )


# ==========================================================================
# H-1 AST-anchored persistence tests
# ==========================================================================


def test_h1_evse_dp_paused_is_saved_alongside_siblings():
    """H-1 save side. `_save_evse_state` must emit an
    `evse_dp_paused` KV write with the DP set contents — mirroring the
    grid_cap / battery_drain / fill_priority / arbitrage sibling writes.
    AST-verify the KV key literal + the DP set arg."""
    import ast
    from pathlib import Path
    src = Path(
        "custom_components/universal_room_automation/domain_coordinators/energy.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    save_body = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_save_evse_state"
        ):
            save_body = ast.unparse(node)
            break
    assert save_body is not None, "_save_evse_state not found in energy.py"
    assert 'evse_dp_paused' in save_body, (
        "H-1: `_save_evse_state` must write KV key 'evse_dp_paused'"
    )
    assert "_paused_by_dp" in save_body, (
        "H-1: `_save_evse_state` must include the DP set contents"
    )


def test_h1_evse_dp_paused_is_restored_and_dp_owner_reclaimed():
    """H-1 restore side. `_restore_evse_state` must read
    `evse_dp_paused`, add ids into `_paused_by_dp`, AND reinstall the
    "dp" dispatch owner claim on each restored id."""
    import ast
    from pathlib import Path
    src = Path(
        "custom_components/universal_room_automation/domain_coordinators/energy.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    body = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_restore_evse_state"
        ):
            body = ast.unparse(node)
            break
    assert body is not None
    assert 'evse_dp_paused' in body, (
        "H-1: `_restore_evse_state` must read KV key 'evse_dp_paused'"
    )
    assert "_paused_by_dp.add" in body, (
        "H-1: restored ids must be added into `_paused_by_dp`"
    )
    assert '_claim_pause_dispatch_owner' in body and (
        '"dp"' in body or "'dp'" in body
    ), (
        "H-1: restored ids must reinstall the 'dp' dispatch owner claim "
        "(else sticky reversion has nothing to release)"
    )


# ==========================================================================
# M-1 disposition anchor (accepted-gap documented in source)
# ==========================================================================


def test_m1_accepted_gap_documented_in_needed_kwh_docstring():
    """M-1 disposition: the plugged-idle case is left as an accepted gap
    with must-start-by as the liveness backstop, per operator direction
    to not invent EVSE attributes not present in the real state shape.
    Anchor the disposition text in the docstring so future refactors
    don't silently drop the rationale."""
    from custom_components.universal_room_automation.domain_coordinators import (
        energy as _energy_mod,
    )
    import inspect
    src = inspect.getsource(_energy_mod)
    # Locate the target docstring by anchor phrase.
    assert "B2c-3 M-1 (accepted gap)" in src, (
        "M-1 disposition rationale must be documented in "
        "`_dp_needed_kwh_plugged` docstring"
    )
    assert "must_start_by" in src, (
        "M-1 rationale must cite must-start-by as the liveness backstop"
    )
