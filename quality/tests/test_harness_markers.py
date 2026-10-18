"""TEST-HARNESS Wave 1 D3 + D6: behavioural tests for quality/tests/_markers.py.

Each scenario runs a real pytest subprocess over a throwaway test dir whose
conftest loads the `_markers` plugin, and asserts on the outcome.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent

_SAMPLE = textwrap.dedent(
    """
    import pytest

    def test_plain():
        pass

    @pytest.mark.quarantine("ABC-DEF-1", reason="known flake")
    def test_quarantined_fails():
        assert False

    @pytest.mark.quarantine(card="XYZ-2", cls="fake-ha-drift")
    def test_quarantined_kw_passes():
        pass

    @pytest.mark.source_mutation
    def test_drill():
        pass
    """
)


def _run(tmp_path: Path, *args: str, env_extra: dict | None = None, body: str = _SAMPLE):
    (tmp_path / "conftest.py").write_text('pytest_plugins = ["_markers"]\n')
    (tmp_path / "test_sample.py").write_text(body)
    # Mirror the repo default (pytest.ini addopts) explicitly.
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\naddopts = -m \"not source_mutation\"\n"
        "markers =\n    quarantine: q\n    source_mutation: d\n"
    )
    env = dict(os.environ)
    env.pop("URA_RUN_QUARANTINED", None)
    env.pop("URA_SOURCE_MUTATION", None)
    env["PYTHONPATH"] = os.pathsep.join([str(_HERE), env.get("PYTHONPATH", "")])
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-rs", *args],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
    )


def test_default_run_skips_quarantine_and_deselects_drills(tmp_path):
    r = _run(tmp_path)
    out = r.stdout
    assert r.returncode == 0, out + r.stderr
    assert "1 passed, 2 skipped, 1 deselected" in out
    assert "quarantined [ABC-DEF-1] known flake" in out
    assert "quarantined: 2 test(s), 2 card(s) -- skipped" in out


def test_ledger_option_lists_every_entry(tmp_path):
    r = _run(tmp_path, "--quarantine-ledger")
    assert "ABC-DEF-1  test_sample.py::test_quarantined_fails  -- known flake" in r.stdout
    assert "XYZ-2 [fake-ha-drift]  test_sample.py::test_quarantined_kw_passes" in r.stdout


def test_run_quarantined_env_executes_them(tmp_path):
    r = _run(tmp_path, env_extra={"URA_RUN_QUARANTINED": "1"})
    assert "1 failed, 2 passed, 1 deselected" in r.stdout, r.stdout


def test_source_mutation_opt_in_by_marker_expression(tmp_path):
    r = _run(tmp_path, "-m", "source_mutation")
    assert "1 passed, 3 deselected" in r.stdout, r.stdout


def test_source_mutation_opt_in_by_env(tmp_path):
    r = _run(tmp_path, env_extra={"URA_SOURCE_MUTATION": "1"})
    assert "2 passed, 2 skipped" in r.stdout and "deselected" not in r.stdout, r.stdout


@pytest.mark.parametrize(
    "mark",
    [
        '@pytest.mark.quarantine(reason="no card")',
        '@pytest.mark.quarantine("not-a-card")',
        '@pytest.mark.quarantine("NOHYPHEN")',
        "@pytest.mark.quarantine(card=123)",
    ],
)
def test_missing_or_malformed_card_is_collection_error(tmp_path, mark):
    body = f"import pytest\n\n{mark}\ndef test_x():\n    pass\n"
    r = _run(tmp_path, body=body)
    assert r.returncode == 4, r.stdout + r.stderr  # pytest UsageError
    assert "invalid quarantine marker" in (r.stdout + r.stderr)
