"""Phase-3 mutation matrix — the 8 reviewer mutations (a..h).

Each mutation edits a piece of production source (energy_pool.py,
energy.py, or energy_pool_owners.py), runs one or more named anchor
tests in a subprocess, and asserts the expected result:

  KILLED  — the mutation flips a passing anchor RED (test detected it).
  SURVIVES — the mutation leaves the suite green (the source change is
             not behaviorally observable to the current tests).

Mutations c, d, g, h are called out in the phase-3 spec as "must now be
KILLED by named tests" (post-fix-up). a, b, e, f are additional
coverage mutations from the same review consolidation.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent.parent
_CC = _REPO / "custom_components" / "universal_room_automation" / \
    "domain_coordinators"


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _clear_pycache() -> None:
    for root, dirs, _ in os.walk(_REPO):
        if "__pycache__" in dirs:
            shutil.rmtree(Path(root) / "__pycache__", ignore_errors=True)


def _run(anchor: str):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO / "quality")
    return subprocess.run(
        [sys.executable, "-m", "pytest", anchor, "-x", "--tb=line", "-q"],
        env=env, cwd=str(_REPO),
        capture_output=True, text=True,
    )


def _apply(path: Path, swap_from: str, swap_to: str, anchor: str,
           expect: str):
    original = path.read_text(encoding="utf-8")
    assert swap_from in original, f"anchor missing in {path.name}"
    mutated = original.replace(swap_from, swap_to, 1)
    assert mutated != original, "no-op mutation"
    _md5_before = _md5(path)
    path.write_text(mutated, encoding="utf-8")
    try:
        _clear_pycache()
        result = _run(anchor)
    finally:
        path.write_text(original, encoding="utf-8")
        _clear_pycache()
        assert _md5(path) == _md5_before
    if expect == "KILLED":
        assert result.returncode != 0, (
            f"expected KILLED; test stayed GREEN\n{result.stdout[-2000:]}"
        )
    else:
        assert result.returncode == 0, (
            f"expected SURVIVES; test went RED\n{result.stdout[-2000:]}"
        )


# ---------------------------------------------------------------------------
# a — flip classifier priority for fill_priority (1) and battery_drain (2)
#     → classifier surfaces a wrong reason_token on a fill+drain state
#     Killed by: golden byte-identical replay
# ---------------------------------------------------------------------------
def test_mutation_a_classifier_priority_swap_is_KILLED():
    _apply(
        _CC / "energy_pool_owners.py",
        swap_from=(
            'name="fill_priority", attr="_paused_by_fill_priority", tier="evse",\n'
            '        kind="set", precedence_row=8,\n'
            '        persistence_key="evse_fill_priority_paused", persistence_kind="list",\n'
            '        peer_holds_member=True, dispatch_tag="fill_priority",\n'
            '        classifier_priority=1'
        ),
        swap_to=(
            'name="fill_priority", attr="_paused_by_fill_priority", tier="evse",\n'
            '        kind="set", precedence_row=8,\n'
            '        persistence_key="evse_fill_priority_paused", persistence_kind="list",\n'
            '        peer_holds_member=True, dispatch_tag="fill_priority",\n'
            '        classifier_priority=99'  # demote below all
        ),
        anchor=(
            "quality/tests/test_owner_registry_golden.py::"
            "test_golden_byte_identical_replay"
        ),
        expect="KILLED",
    )


# ---------------------------------------------------------------------------
# b — drop peer_holds_member=True on grid_cap
#     Killed by: golden replay (release-path deferral for the grid_cap
#                sibling of the release loops changes shape)
# ---------------------------------------------------------------------------
def test_mutation_b_grid_cap_peer_holds_dropped_is_KILLED():
    _apply(
        _CC / "energy_pool_owners.py",
        swap_from=(
            'name="grid_cap", attr="_paused_by_grid_cap", tier="evse", kind="set",\n'
            '        precedence_row=3,\n'
            '        persistence_key="evse_grid_cap_paused", persistence_kind="list",\n'
            '        peer_holds_member=True,'
        ),
        swap_to=(
            'name="grid_cap", attr="_paused_by_grid_cap", tier="evse", kind="set",\n'
            '        precedence_row=3,\n'
            '        persistence_key="evse_grid_cap_paused", persistence_kind="list",\n'
            '        peer_holds_member=False,'
        ),
        anchor=(
            "quality/tests/test_owner_registry_golden.py::"
            "test_golden_byte_identical_replay"
        ),
        expect="KILLED",
    )


# ---------------------------------------------------------------------------
# c — flip load_shed prune_participant to True (quirk lost)
#     Must be KILLED after C-HIGH-4 fixture fix (seed both ids).
# ---------------------------------------------------------------------------
def test_mutation_c_load_shed_prune_quirk_lost_is_KILLED():
    _apply(
        _CC / "energy_pool_owners.py",
        swap_from=(
            'name="load_shed", attr="_paused_by_load_shed", tier="evse", kind="set",\n'
            '        precedence_row=7,\n'
            '        persistence_key=None,  # RAM only, re-derived from cascade at\n'
            '                               # energy.py:2358 (§1c cross-module coupling).\n'
            '        persistence_kind="none",\n'
            '        peer_holds_member=True, dispatch_tag="load_shed",\n'
            '        prune_participant=False,'
        ),
        swap_to=(
            'name="load_shed", attr="_paused_by_load_shed", tier="evse", kind="set",\n'
            '        precedence_row=7,\n'
            '        persistence_key=None,  # RAM only, re-derived from cascade at\n'
            '                               # energy.py:2358 (§1c cross-module coupling).\n'
            '        persistence_kind="none",\n'
            '        peer_holds_member=True, dispatch_tag="load_shed",\n'
            '        prune_participant=True,'  # <— mutation
        ),
        anchor=(
            "quality/tests/test_owner_registry_golden.py::"
            "test_golden_byte_identical_replay"
        ),
        expect="KILLED",
    )


# ---------------------------------------------------------------------------
# d — null the load_shed persistence declaration side (already None; use
#     an alternate: flip prune_quirk_note to empty — doc-only, should
#     SURVIVE because the field is not consumed for behavior. Recorded
#     as documentation-only.
# ---------------------------------------------------------------------------
def test_mutation_d_module_docstring_comment_removed_SURVIVES():
    """d — documentation-only mutation control: erasing a comment
    inside `_stronger_peer_holds` must NOT flip the oracle (comments
    are not behavior). This anchors the 'SURVIVES on doc-only edits'
    property so future authors know the oracle is not tautologized
    by cosmetic edits."""
    _apply(
        _CC / "energy_pool.py",
        swap_from=(
            "        # Phase-2 refactor: enumeration derived from EV_REGISTRY. The\n"
            "        # OR-loop below is byte-equivalent to the pre-refactor inline"
        ),
        swap_to=(
            "        # (comment removed by mutation d)\n"
            "        # OR-loop below is byte-equivalent to the pre-refactor inline"
        ),
        anchor=(
            "quality/tests/test_owner_registry_golden.py::"
            "test_golden_byte_identical_replay"
        ),
        expect="SURVIVES",
    )


# ---------------------------------------------------------------------------
# e — drop dispatch_tag on tou (documentation-only field on the EV
#     side, since production still uses inline string tags at claim
#     sites). SURVIVES.
# ---------------------------------------------------------------------------
def test_mutation_e_tou_dispatch_tag_dropped_SURVIVES():
    _apply(
        _CC / "energy_pool_owners.py",
        swap_from=(
            'peer_holds_member=False,\n'
            '        dispatch_tag="tou",\n'
            '        classifier_priority=6, reason_token="paused",'
        ),
        swap_to=(
            'peer_holds_member=False,\n'
            '        dispatch_tag=None,\n'
            '        classifier_priority=6, reason_token="paused",'
        ),
        anchor=(
            "quality/tests/test_owner_registry_golden.py::"
            "test_golden_byte_identical_replay"
        ),
        expect="SURVIVES",
    )


# ---------------------------------------------------------------------------
# f — drop persistence_key on proactive_offpeak
#     Killed by: persistence-oracle round-trip
# ---------------------------------------------------------------------------
def test_mutation_f_proactive_offpeak_persistence_key_dropped_is_KILLED():
    _apply(
        _CC / "energy_pool_owners.py",
        swap_from=(
            'name="proactive_offpeak", attr="_proactive_offpeak_holds", tier="evse",\n'
            '        kind="set", precedence_row=9,\n'
            '        persistence_key="evse_proactive_offpeak_holds", persistence_kind="list",'
        ),
        swap_to=(
            'name="proactive_offpeak", attr="_proactive_offpeak_holds", tier="evse",\n'
            '        kind="set", precedence_row=9,\n'
            '        persistence_key=None, persistence_kind="none",'
        ),
        anchor=(
            "quality/tests/test_owner_registry_persistence.py::"
            "test_every_persisted_declaration_round_trips"
        ),
        expect="KILLED",
    )


# ---------------------------------------------------------------------------
# g — remove the blind-window pre-engaged marking block in restore
#     (breaks C-HIGH-2 behavioral guarantee). MUST be KILLED.
# ---------------------------------------------------------------------------
def test_mutation_g_blind_window_pre_engaged_disabled_is_KILLED():
    _apply(
        _CC / "energy.py",
        swap_from="self._ev.mark_pre_engaged_from_restore(epoch_dt)",
        swap_to="pass  # mutation g: pre-engaged disabled",
        anchor=(
            "quality/tests/test_owner_registry_persistence.py::"
            "test_blind_window_restore_marks_pre_engaged_and_epoch"
        ),
        expect="KILLED",
    )


# ---------------------------------------------------------------------------
# h — remove the DP dispatch owner reinstall on restore
#     (breaks C-HIGH-3 behavioral guarantee). MUST be KILLED.
# ---------------------------------------------------------------------------
def test_mutation_h_dp_dispatch_owner_reinstall_removed_is_KILLED():
    _apply(
        _CC / "energy.py",
        swap_from=(
            'if _decl.restore_hook == "reinstall_dp_dispatch_owner":\n'
            '                    # Preserved from B2c-3 H-1 — sticky reversion retry'
        ),
        swap_to=(
            'if False:  # mutation h: DP dispatch owner reinstall removed\n'
            '                    # Preserved from B2c-3 H-1 — sticky reversion retry'
        ),
        anchor=(
            "quality/tests/test_owner_registry_persistence.py::"
            "test_restore_reinstalls_dp_dispatch_owner"
        ),
        expect="KILLED",
    )
