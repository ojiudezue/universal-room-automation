"""TEST-HARNESS D1: production-tree integrity guard (pytest plugin).

Registered from quality/tests/conftest.py via ``pytest_plugins``.

Invariant (G3): after any suite run, the production tree
(``custom_components/``) is byte-identical to what it was at session start.

Incident 2026-10-17: a plain full-suite run on develop left
``domain_coordinators/_loop_stall_watchdog.py`` mutated on disk
(``self._episode_active = False  # MUTATION``) by an in-place mutation drill.
Every result after that test was evidence about a mutant.

Mechanism:
  * ``pytest_sessionstart`` snapshots the bytes of every file under the
    protected roots (``__pycache__`` / ``*.pyc`` excluded).
  * An autouse MODULE-scoped fixture re-checks the tree after each test
    module (cheap: ``stat`` first, bytes only when size/mtime moved). Any
    changed or deleted file is RESTORED immediately (so later modules are not
    run against a mutant) and the violation is attributed to that module.
    The mutant bytes are saved to a temp dir for forensics.
  * ``pytest_sessionfinish`` does a final sweep (unattributed), prints a
    loud report and forces the session exit status to TESTS_FAILED.

New files created under a protected root are reported (fail) but NOT
deleted — deleting is irreversible and the file may be a developer's.

Caveat: the guard restores to the session-START bytes, so editing a
production file in the SAME checkout while its suite is running will be
reverted (the edit is saved in the forensics dir and named in the report).
Use a separate worktree for concurrent edits.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# Safety invariant, not a tunable: the roots no test may leave modified.
PROTECTED_ROOTS = ("custom_components",)
_SKIP_DIR_NAMES = frozenset({"__pycache__"})
_SKIP_SUFFIXES = (".pyc", ".pyo")


def _iter_files(repo_root: Path):
    for root_name in PROTECTED_ROOTS:
        base = repo_root / root_name
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
            for fn in filenames:
                if fn.endswith(_SKIP_SUFFIXES):
                    continue
                p = Path(dirpath) / fn
                yield p.relative_to(repo_root).as_posix(), p


def _stat_key(p: Path):
    st = p.stat()
    return (st.st_mtime_ns, st.st_size)


class TreeIntegrityGuard:
    """Snapshot / verify / restore the protected production tree."""

    def __init__(self, repo_root: Path = REPO_ROOT):
        self.repo_root = repo_root
        self.snapshot: dict[str, bytes] = {}
        self.stats: dict[str, tuple] = {}
        self.violations: list[dict] = []
        self._forensics_dir: Path | None = None

    # -- snapshot ---------------------------------------------------------
    def take_snapshot(self) -> None:
        self.snapshot.clear()
        self.stats.clear()
        for rel, p in _iter_files(self.repo_root):
            self.snapshot[rel] = p.read_bytes()
            self.stats[rel] = _stat_key(p)

    # -- verify + restore -------------------------------------------------
    def _save_forensics(self, rel: str, data: bytes) -> Path:
        if self._forensics_dir is None:
            self._forensics_dir = Path(
                tempfile.mkdtemp(prefix="ura_tree_guard_")
            )
        dest = self._forensics_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest

    def check_and_restore(self, culprit: str) -> list[dict]:
        """Compare the tree with the snapshot; restore every drift.

        Returns the violations found in THIS call (also appended to
        ``self.violations``).
        """
        found: list[dict] = []
        seen: set[str] = set()
        for rel, p in _iter_files(self.repo_root):
            seen.add(rel)
            if rel not in self.snapshot:
                if not any(v["file"] == rel and v["kind"] == "created"
                           for v in self.violations):
                    found.append({"file": rel, "kind": "created",
                                  "culprit": culprit, "saved": None})
                continue
            try:
                key = _stat_key(p)
            except FileNotFoundError:
                continue
            if key == self.stats.get(rel):
                continue
            current = p.read_bytes()
            if current == self.snapshot[rel]:
                self.stats[rel] = key  # rewritten with identical bytes
                continue
            saved = self._save_forensics(rel, current)
            p.write_bytes(self.snapshot[rel])
            self.stats[rel] = _stat_key(p)
            found.append({"file": rel, "kind": "modified",
                          "culprit": culprit, "saved": str(saved)})
        for rel in self.snapshot:
            if rel not in seen:
                p = self.repo_root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(self.snapshot[rel])
                self.stats[rel] = _stat_key(p)
                found.append({"file": rel, "kind": "deleted",
                              "culprit": culprit, "saved": None})
        self.violations.extend(found)
        return found

    def report_lines(self) -> list[str]:
        lines = [
            "PRODUCTION TREE MODIFIED BY THE TEST RUN — session FAILED "
            "(TEST-HARNESS D1 / G3).",
            "Every listed file was RESTORED to its session-start bytes; "
            "fix the named test module to mutate a COPY "
            "(quality/tests/_mutation_sandbox.py).",
        ]
        for v in self.violations:
            extra = f"  (mutant saved: {v['saved']})" if v["saved"] else ""
            if v["kind"] == "created":
                extra = "  (NOT deleted — remove it by hand if it is junk)"
            lines.append(
                f"  {v['kind'].upper():9s} {v['file']}  <- {v['culprit']}{extra}"
            )
        return lines


_GUARD: TreeIntegrityGuard | None = None


def pytest_sessionstart(session):
    global _GUARD
    _GUARD = TreeIntegrityGuard()
    _GUARD.take_snapshot()


@pytest.fixture(scope="module", autouse=True)
def _ura_tree_integrity_module_check(request):
    yield
    if _GUARD is not None:
        _GUARD.check_and_restore(culprit=request.node.nodeid)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    if _GUARD is None:
        return
    _GUARD.check_and_restore(culprit="<session: unattributed>")
    if not _GUARD.violations:
        return
    lines = _GUARD.report_lines()
    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    if tr is not None:
        tr.write_line("")
        tr.write_sep("!", "TREE INTEGRITY VIOLATION", red=True, bold=True)
        for ln in lines:
            tr.write_line(ln, red=True)
    else:  # pragma: no cover — terminal reporter disabled
        import sys
        sys.stderr.write("\n".join(lines) + "\n")
    if session.exitstatus in (pytest.ExitCode.OK, 0,
                              pytest.ExitCode.NO_TESTS_COLLECTED):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
