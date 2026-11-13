"""HOUSE-STATE step 1a D1 (PLANNING_house_state_axes_step1.md rev 3, INV-RULE).

One counted-return rule and one ``_last_real`` ledger rule, shared by the SC
lock regime and the residency producer through ``arrival_edges``. The oracle
below is written by hand from the rule's statement (plan §A3.1), with literal
times (15 min = 900 s); it is never computed by the code under test.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from custom_components.universal_room_automation import arrival_edges as AE
from test_sc_garage_lockout import make_rig

_URA = pathlib.Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"

T = 1_000_000.0
MIN_AWAY = 900.0  # 15 min, literal

# (label, prev_real) -> elapsed is fixed by the entry's own since.
PREVS = {
    "none": None,
    "home_real": ("home", T - 10_000.0, False),
    "away_899": ("not_home", T - 899.0, False),
    "away_900": ("not_home", T - 900.0, False),
    "away_901": ("not_home", T - 901.0, False),
    "zone_2000": ("work", T - 2000.0, False),
    "away_restored_10": ("not_home", T - 10.0, True),
    "home_restored": ("home", T - 10.0, True),
}

# Hand-written oracle: counted for an unknown / unavailable old value
# (boot window False). A real old value (not_home / zone) always counts.
UNREAL_ORACLE = {
    "none": True,             # no real transition seen since setup
    "home_real": False,       # blip while home
    "away_899": False,        # 899 s < 15 min
    "away_900": True,         # exactly 15 min counts (>=)
    "away_901": True,
    "zone_2000": True,
    "away_restored_10": True,  # restored entry: not a real transition
    "home_restored": True,
}


@pytest.mark.parametrize("old", ["not_home", "work", "unknown", "unavailable"])
@pytest.mark.parametrize("prev", sorted(PREVS))
@pytest.mark.parametrize("boot", [False, True])
def test_matrix_matches_lock_semantics(old, prev, boot):
    if old in ("not_home", "work") or boot:
        expected = True
    else:
        expected = UNREAL_ORACLE[prev]
    got = AE.counted_return(old, PREVS[prev], T, in_boot_window=boot, min_away_s=MIN_AWAY)
    assert got is expected
    if old in ("unknown", "unavailable"):
        assert AE.really_away(PREVS[prev], T, in_boot_window=boot,
                              min_away_s=MIN_AWAY) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("prev", sorted(PREVS))
async def test_lock_rule_matches_oracle(prev):
    """The lock's own `_arrival_counts` (outside its boot window) gives the
    oracle's answer for the same ledger entry: one rule, no second copy."""
    rig = await make_rig()  # past the 600 s boot window
    assert rig.regime._in_boot_arrival_window() is False
    now = rig.regime._ts()
    entry = PREVS[prev]
    if entry is None:
        rig.regime._last_real.pop("person.ezinne", None)
    else:
        rig.regime._last_real["person.ezinne"] = (entry[0], now - (T - entry[1]), entry[2])
    assert rig.regime._arrival_counts("person.ezinne", "unavailable", now) is UNREAL_ORACLE[prev]
    assert rig.regime._arrival_counts("person.ezinne", "not_home", now) is True


def test_update_last_real_same_state_keeps_since():
    ledger: dict = {}
    AE.update_last_real(ledger, "p", "not_home", 100.0)
    assert ledger["p"] == ("not_home", 100.0, False)
    AE.update_last_real(ledger, "p", "not_home", 1180.0)  # attribute refresh
    assert ledger["p"] == ("not_home", 100.0, False)
    AE.update_last_real(ledger, "p", "unavailable", 1190.0)  # unreal: no stamp
    assert ledger["p"] == ("not_home", 100.0, False)
    AE.update_last_real(ledger, "p", "home", 1200.0)
    assert ledger["p"] == ("home", 1200.0, False)
    # A restored entry is replaced by the first live reading, same state too.
    ledger["q"] = ("home", 50.0, True)
    AE.update_last_real(ledger, "q", "home", 60.0)
    assert ledger["q"] == ("home", 60.0, False)


def test_stamp_restored_real_only():
    ledger: dict = {}
    AE.stamp_restored(ledger, "p", "unknown", 10.0)
    AE.stamp_restored(ledger, "p", "unavailable", 11.0)
    assert ledger == {}
    AE.stamp_restored(ledger, "p", "home", 12.0)
    assert ledger["p"] == ("home", 12.0, True)
    AE.stamp_restored(ledger, "p", "not_home", 13.0)
    assert ledger["p"] == ("not_home", 13.0, True)


def _fn(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


_CONSTS = {"GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN", "RESIDENT_RETURN_MIN_AWAY_MIN"}


def _no_second_copy(fn: ast.AST) -> None:
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare):
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            assert not (names & _CONSTS), ast.unparse(node)
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Subscript):
                    assert "_last_real" not in ast.unparse(t.value), ast.unparse(node)
                    assert "ledger" not in ast.unparse(t.value), ast.unparse(node)


def _calls(fn: ast.AST) -> set[str]:
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            out.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", ""))
    return out


def test_lock_delegates_structurally():
    """INV-RULE (structural, plan D1 acceptance): the lock's rule sites and
    the residency tracker contain no comparison against the min-away
    constants and no ``_last_real[...] =`` / ``ledger[...] =`` write; they
    call the shared ``arrival_edges`` functions."""
    lock = ast.parse((_URA / "domain_coordinators" / "security_lock_regime.py").read_text())
    names = ("_arrival_counts", "_really_away", "_process_person_edge", "_on_person_event")
    called: set[str] = set()
    for name in names:
        fn = _fn(lock, name)
        _no_second_copy(fn)
        called |= _calls(fn)
    assert {"counted_return", "really_away", "update_last_real", "stamp_restored"} <= called
    res = ast.parse((_URA / "domain_coordinators" / "residency.py").read_text())
    _no_second_copy(res)
    assert {"counted_return", "update_last_real", "stamp_restored"} <= _calls(res)
