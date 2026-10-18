"""TEST-HARNESS D1: no test may leave production source modified (G3).

Unit tests drive ``TreeIntegrityGuard`` against a scratch tree. The
end-to-end tests run a REAL pytest session in a tmp COPY of the repo with a
planted test module that writes a production file and does not restore it:
the session must FAIL, name the file and the culprit module, and restore the
bytes. The real repo is never written.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from _tree_integrity_guard import TreeIntegrityGuard

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Unit: the guard against a scratch tree
# ---------------------------------------------------------------------------
@pytest.fixture
def scratch(tmp_path):
    cc = tmp_path / "custom_components" / "pkg"
    cc.mkdir(parents=True)
    (cc / "a.py").write_text("A = 1\n")
    (cc / "b.json").write_text("{}\n")
    (cc / "__pycache__").mkdir()
    (cc / "__pycache__" / "a.cpython-313.pyc").write_bytes(b"\x00")
    g = TreeIntegrityGuard(repo_root=tmp_path)
    g.take_snapshot()
    return tmp_path, g


def test_clean_tree_has_no_violation(scratch):
    _root, g = scratch
    assert g.check_and_restore("mod_x") == []
    assert g.violations == []


def test_modified_file_is_restored_and_attributed(scratch):
    root, g = scratch
    f = root / "custom_components" / "pkg" / "a.py"
    f.write_text("A = 2  # MUTATION\n")
    found = g.check_and_restore("quality/tests/test_culprit.py")
    assert [(v["file"], v["kind"], v["culprit"]) for v in found] == [
        ("custom_components/pkg/a.py", "modified", "quality/tests/test_culprit.py"),
    ]
    assert f.read_text() == "A = 1\n"
    # Forensic copy keeps the mutant for diagnosis.
    assert Path(found[0]["saved"]).read_text() == "A = 2  # MUTATION\n"
    # Report names file and culprit.
    report = "\n".join(g.report_lines())
    assert "custom_components/pkg/a.py" in report
    assert "quality/tests/test_culprit.py" in report


def test_identical_rewrite_is_not_a_violation(scratch):
    root, g = scratch
    f = root / "custom_components" / "pkg" / "a.py"
    os.utime(f, ns=(1, 1))  # stat moves, bytes identical
    f.write_text("A = 1\n")
    assert g.check_and_restore("m") == []


def test_deleted_file_is_restored(scratch):
    root, g = scratch
    f = root / "custom_components" / "pkg" / "b.json"
    f.unlink()
    found = g.check_and_restore("m")
    assert [(v["file"], v["kind"]) for v in found] == [
        ("custom_components/pkg/b.json", "deleted"),
    ]
    assert f.read_text() == "{}\n"


def test_created_file_is_reported_not_deleted(scratch):
    root, g = scratch
    f = root / "custom_components" / "pkg" / "new.py"
    f.write_text("X = 1\n")
    found = g.check_and_restore("m")
    assert [(v["file"], v["kind"]) for v in found] == [
        ("custom_components/pkg/new.py", "created"),
    ]
    assert f.exists()
    # Reported once, not once per module.
    assert g.check_and_restore("m2") == []


def test_pycache_is_ignored(scratch):
    root, g = scratch
    (root / "custom_components" / "pkg" / "__pycache__" / "a.cpython-313.pyc").write_bytes(b"\x01")
    (root / "custom_components" / "pkg" / "__pycache__" / "z.pyc").write_bytes(b"\x02")
    assert g.check_and_restore("m") == []


# ---------------------------------------------------------------------------
# End-to-end: a real pytest session in a tmp copy of the repo
# ---------------------------------------------------------------------------
_TARGET_REL = "custom_components/universal_room_automation/manifest.json"

_PLANTED_DIRTY = '''
from pathlib import Path

def test_writes_production_without_restore():
    p = Path(__file__).resolve().parents[2] / "{target}"
    p.write_text(p.read_text() + "\\n# PLANTED-MUTATION\\n")
'''

_PLANTED_CLEAN = '''
def test_does_nothing():
    assert True
'''

_PLANTED_RESTORES = '''
from pathlib import Path

def test_writes_then_restores():
    p = Path(__file__).resolve().parents[2] / "{target}"
    orig = p.read_bytes()
    try:
        p.write_bytes(orig + b"\\n# TEMP\\n")
    finally:
        p.write_bytes(orig)
'''


def _run_in_copy(planted_src: str, name: str):
    td = Path(tempfile.mkdtemp(prefix="ura_tree_guard_e2e_"))
    try:
        for entry in REPO.iterdir():
            if entry.name in ("custom_components", "quality"):
                continue
            (td / entry.name).symlink_to(entry)
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        shutil.copytree(REPO / "custom_components", td / "custom_components", ignore=ignore)
        shutil.copytree(REPO / "quality", td / "quality", ignore=ignore)
        planted = td / "quality" / "tests" / name
        planted.write_text(planted_src.format(target=_TARGET_REL))
        target = td / _TARGET_REL
        before = target.read_bytes()
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join([str(td), str(td / "quality")])
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        p = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", str(planted),
             "-q", "-p", "no:cacheprovider"],
            cwd=str(td), env=env, capture_output=True, text=True, timeout=180,
        )
        after = target.read_bytes()
        return p.returncode, p.stdout + p.stderr, before, after
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_e2e_unrestored_write_fails_session_and_is_restored():
    rc, out, before, after = _run_in_copy(_PLANTED_DIRTY, "test_zz_planted_dirty.py")
    assert rc == 1, out[-3000:]
    assert "1 passed" in out, out[-3000:]  # the test itself passed...
    assert "TREE INTEGRITY VIOLATION" in out, out[-3000:]  # ...the session failed
    assert _TARGET_REL in out and "test_zz_planted_dirty.py" in out, out[-3000:]
    assert after == before, "guard did not restore the production file"


def test_e2e_clean_session_passes():
    rc, out, before, after = _run_in_copy(_PLANTED_CLEAN, "test_zz_planted_clean.py")
    assert rc == 0, out[-3000:]
    assert "TREE INTEGRITY VIOLATION" not in out
    assert after == before


def test_e2e_write_restored_by_the_test_itself_passes():
    rc, out, before, after = _run_in_copy(_PLANTED_RESTORES, "test_zz_planted_restores.py")
    assert rc == 0, out[-3000:]
    assert "TREE INTEGRITY VIOLATION" not in out
    assert after == before
