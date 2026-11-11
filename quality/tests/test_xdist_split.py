"""TEST-SUITE-PARALLEL-1: the loadfile scheduler override in _xdist_split.py."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import _xdist_split as xs

SLEEP = "quality/tests/test_house_state_sleep_mask_mutation_drills.py"
D7 = "quality/tests/test_d7_donor_hygiene.py"


def test_listed_drill_is_its_own_unit():
    nid = f"{SLEEP}::test_mutation_drill_goes_red[tripwire_census_conjunct_dropped]"
    assert xs.split_scope(nid) == nid


def test_in_process_test_of_listed_file_stays_grouped_by_file():
    assert xs.split_scope(f"{D7}::test_import_scope_guard_flags_in_place_mutation") == D7
    assert xs.split_scope(f"{D7}::test_probe") == D7


def test_listed_d7_subprocess_tests_split():
    for name in ("test_drill_guard_neutered_goes_red",
                 "test_victim_green_after_donor[a.py-b.py::t]",
                 "test_donor_leaves_no_residue[a.py]"):
        nid = f"{D7}::{name}"
        assert xs.split_scope(nid) == nid


def test_unlisted_file_grouped_by_file_even_for_drill_names():
    f = "quality/tests/test_ble_extend_not_create.py"
    assert xs.split_scope(f"{f}::test_drill_x") == f
    assert xs.split_scope(f"{f}::TestA::test_b") == f


def _cfg(dist):
    return SimpleNamespace(getoption=lambda name, default=None: dist)


@pytest.mark.parametrize("dist", ["load", "loadscope", "loadgroup", "worksteal", "no", None])
def test_scheduler_override_only_for_loadfile(dist):
    assert xs.pytest_xdist_make_scheduler(_cfg(dist), None) is None


def test_loadfile_gets_the_splitting_scheduler():
    pytest.importorskip("xdist")
    from xdist.scheduler import LoadFileScheduling

    opts = {"dist": "loadfile", "tx": ["6*popen"]}
    cfg = SimpleNamespace(
        getoption=lambda name, default=None: opts.get(name, default),
        getvalue=lambda name: opts[name],
    )
    sched = xs.pytest_xdist_make_scheduler(cfg, None)
    assert isinstance(sched, LoadFileScheduling)
    nid = f"{SLEEP}::test_mutation_drill_goes_red[x]"
    assert sched._split_scope(nid) == nid
    assert sched._split_scope(f"{D7}::test_probe") == D7
