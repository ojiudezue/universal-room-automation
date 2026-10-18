"""TEST-HARNESS Wave 2 D7: self-test of collect_order_matrix.py --run / donor finder.

Plants an order-dependent pair in a temp dir (a donor that leaks a module
attribute at import time, and a victim that reads it) plus inert filler
files, then drives the real tool functions. The planted ground truth is the
oracle: the donor finder must name exactly the planted donor, and the run
matrix must report the victim only in orders where the donor precedes it.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_TOOL = pathlib.Path(__file__).resolve().parents[1] / "tools" / "collect_order_matrix.py"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("_com_under_test", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DONOR = """
import os
os.environ["D7_PLANTED_LEAK"] = "1"   # import-time leak, never restored

def test_donor_ok():
    assert True
"""

VICTIM = """
import os

# Read at IMPORT time, like a module binding a symbol from a stubbed package:
# pytest collects (imports) every file before running any test, so only an
# import-time read is sensitive to which file was COLLECTED first.
_SEEN_AT_IMPORT = os.environ.get("D7_PLANTED_LEAK")

def test_victim_needs_clean_env():
    assert _SEEN_AT_IMPORT is None

def test_victim_unaffected():
    assert True
"""

FILLER = """
def test_filler_{i}():
    assert True
"""


@pytest.fixture
def planted(tmp_path, monkeypatch):
    monkeypatch.delenv("D7_PLANTED_LEAK", raising=False)
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "test_d7_donor.py").write_text(DONOR)
    (tmp_path / "test_d7_victim.py").write_text(VICTIM)
    for i in range(5):
        (tmp_path / f"test_d7_filler{i}.py").write_text(FILLER.format(i=i))
    return tmp_path


def test_run_order_reports_victim_only_when_donor_precedes(tool, planted):
    py = sys.executable
    after = tool.run_order(["test_d7_donor.py", "test_d7_victim.py"], py, planted)
    before = tool.run_order(["test_d7_victim.py", "test_d7_donor.py"], py, planted)
    vic = "test_d7_victim.py::test_victim_needs_clean_env"
    assert after[vic] == "failed"
    assert before[vic] == "passed"
    assert after["test_d7_victim.py::test_victim_unaffected"] == "passed"
    assert tool.victims_of(before, after) == [vic]


def test_find_donor_names_exactly_the_planted_donor(tool, planted):
    prefix = [
        "test_d7_filler0.py", "test_d7_filler1.py", "test_d7_filler2.py",
        "test_d7_donor.py", "test_d7_filler3.py", "test_d7_filler4.py",
    ]
    donor = tool.find_donor(
        prefix, "test_d7_victim.py::test_victim_needs_clean_env", sys.executable, planted
    )
    assert donor == ["test_d7_donor.py"]


RUNTIME_DONOR = """
import os

def test_runtime_donor_leaks():
    os.environ["D7_RUNTIME_LEAK"] = "1"   # leaked by a test BODY, not import
"""

RUNTIME_VICTIM = """
import os

def test_runtime_victim():
    assert os.environ.get("D7_RUNTIME_LEAK") is None
"""


def test_find_donor_falls_back_to_execution_for_runtime_leak(tool, planted, monkeypatch):
    monkeypatch.delenv("D7_RUNTIME_LEAK", raising=False)
    (planted / "test_d7_rdonor.py").write_text(RUNTIME_DONOR)
    (planted / "test_d7_rvictim.py").write_text(RUNTIME_VICTIM)
    prefix = ["test_d7_filler0.py", "test_d7_rdonor.py", "test_d7_filler1.py"]
    vic = "test_d7_rvictim.py::test_runtime_victim"
    # import-only cannot see a test-body leak ...
    assert tool.find_donor(prefix, vic, sys.executable, planted, import_only=True) == []
    # ... the default (import-only, then execution) finds it.
    assert tool.find_donor(prefix, vic, sys.executable, planted) == ["test_d7_rdonor.py"]


def test_find_donor_not_reproduced_without_donor(tool, planted):
    prefix = ["test_d7_filler0.py", "test_d7_filler1.py"]
    assert tool.find_donor(
        prefix, "test_d7_victim.py::test_victim_needs_clean_env", sys.executable, planted
    ) == []


def test_collection_error_is_reported_as_failure(tool, planted):
    (planted / "test_d7_broken.py").write_text("import d7_module_that_does_not_exist\n")
    res = tool.run_order(["test_d7_broken.py", "test_d7_filler0.py"], sys.executable, planted)
    assert res.get("test_d7_broken.py::<collection>") == "error"
    assert res["test_d7_filler0.py::test_filler_0"] == "passed"


def test_run_matrix_finds_donor_in_reversed_order(tool, planted):
    class A:
        seeds: list = []
        reverse = True
        find_donors = True
        python = sys.executable

    # Default order: victim before donor (passes); reverse: donor first.
    files = ["test_d7_filler0.py", "test_d7_victim.py", "test_d7_filler1.py", "test_d7_donor.py"]
    rc, table = tool.run_matrix(A, files, planted)
    assert rc == 1
    assert table == [
        ("reverse", "test_d7_donor.py", "test_d7_victim.py::test_victim_needs_clean_env")
    ]
