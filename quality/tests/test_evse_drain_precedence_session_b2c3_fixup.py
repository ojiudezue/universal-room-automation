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
    """Phase-2 owner-registry refactor: the `evse_dp_paused` KV literal
    now lives on the `dp` OwnerDeclaration in `energy_pool_owners.py`.
    `_save_evse_state` iterates `EV_REGISTRY.iter_persisted_lists()`.
    Mutation-anchor: null out the DP declaration's persistence_key. The
    registry no longer emits a `dp` write, and the AST-registry check
    below goes RED (evse_dp_paused literal disappears from the
    declaration file).
    """
    from pathlib import Path
    import subprocess, sys, os
    owners_src = Path(
        "custom_components/universal_room_automation/domain_coordinators/"
        "energy_pool_owners.py",
    )
    original = owners_src.read_text(encoding="utf-8")
    swap_from = 'persistence_key="evse_dp_paused", persistence_kind="list",'
    swap_to = 'persistence_key=None, persistence_kind="none",'
    assert swap_from in original, f"anchor missing: {swap_from!r}"
    try:
        owners_src.write_text(original.replace(swap_from, swap_to, 1),
                              encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = os.path.abspath(
            os.path.join(os.path.dirname(__file__), ".."),
        )
        # Clear caches so the mutated module is re-imported.
        for root, _dirs, _files in os.walk(
            os.path.join(os.path.dirname(__file__), "..", ".."),
        ):
            if root.endswith("__pycache__"):
                for f in os.listdir(root):
                    try:
                        os.unlink(os.path.join(root, f))
                    except OSError:
                        pass
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                f"{os.path.abspath(__file__)}::"
                "test_h1_evse_dp_paused_is_saved_alongside_siblings",
                "-x", "--tb=short", "-q",
            ],
            env=env, capture_output=True, text=True,
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__),
                                             "..", "..")),
        )
        assert result.returncode != 0, (
            f"expected RED under mutation; got 0\n{result.stdout}"
        )
    finally:
        owners_src.write_text(original, encoding="utf-8")


# ==========================================================================
# H-1 AST-anchored persistence tests
# ==========================================================================


def test_h1_evse_dp_paused_is_saved_alongside_siblings():
    """H-1 save side (phase-3 C-HIGH-1 — BEHAVIORAL).

    Drive the production `_save_registry_owner_lists` helper against a
    KV-capture fake DB and assert:
      (a) the `evse_dp_paused` KV write occurred,
      (b) the payload is a JSON list of the exact DP set contents.
    Also asserts the sibling declarations still emit — this is the
    "bundled alongside grid_cap/battery_drain/fill_priority/arbitrage"
    invariant expressed behaviorally instead of by source substring.
    """
    import asyncio, json
    from tests_owner_registry_helpers import (  # type: ignore
        make_fake_energy_coord, FakeKVDB,
    )

    coord = make_fake_energy_coord()
    coord._ev._paused_by_dp.add("garage_a")
    coord._ev._paused_by_grid_cap.add("garage_b")
    coord._ev._paused_by_battery_drain.add("garage_a")
    coord._ev._paused_by_fill_priority.add("garage_a")
    coord._ev._paused_by_arbitrage.add("garage_b")

    db = FakeKVDB()
    asyncio.get_event_loop().run_until_complete(
        coord._save_registry_owner_lists(db),
    )

    assert "evse_dp_paused" in db.energy_state, (
        "H-1: DP KV key missing from writer output"
    )
    assert sorted(json.loads(db.energy_state["evse_dp_paused"])) == ["garage_a"]
    # Siblings emitted too — the "bundled alongside" contract.
    for _k in ("evse_grid_cap_paused", "evse_battery_drain_paused",
               "evse_fill_priority_paused", "evse_arbitrage_paused"):
        assert _k in db.energy_state, f"H-1: sibling {_k} missing"


def test_h1_evse_dp_paused_is_restored_and_dp_owner_reclaimed():
    """H-1 restore side (phase-3 C-HIGH-3 — BEHAVIORAL).

    Drive the production `_restore_registry_owner_lists` helper against
    a KV-preloaded fake DB, then assert:
      (a) `_paused_by_dp` contains the restored id,
      (b) `_dispatch_owners['<eid>']` contains "dp" — the load-bearing
          reinstall of the dispatch-owner claim (INV-DP2). This is the
          real behavioral surface; a source-substring guard cannot
          detect a broken hook that still name-checks correctly.
    """
    import asyncio, json
    from tests_owner_registry_helpers import (  # type: ignore
        make_fake_energy_coord, FakeKVDB,
    )

    coord = make_fake_energy_coord()
    db = FakeKVDB()
    db.energy_state["evse_dp_paused"] = json.dumps(["garage_a"])
    asyncio.get_event_loop().run_until_complete(
        coord._restore_registry_owner_lists(
            db, 10.0, {"garage_a", "garage_b"},
        ),
    )
    assert "garage_a" in coord._ev._paused_by_dp
    owners = coord._ev._dispatch_owners.get("garage_a", set())
    assert "dp" in owners, (
        "H-1: restored DP id must have `dp` in `_dispatch_owners` "
        f"(got {owners!r}) — else sticky reversion has nothing to release"
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
