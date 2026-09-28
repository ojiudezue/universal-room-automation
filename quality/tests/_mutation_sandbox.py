"""SIGKILL-safe mutation-drill sandbox.

Shared helper for tests that used to write production source in place
inside a `try/finally`. If a hard SIGKILL (concurrency-guard kill, OOM,
^C bypass) or a concurrent `git stash`/`git pull` interrupts such a
drill, production code is left mutated on disk (observed live on
2026-09-26: ``return 0.0  # B2c-1 stubbed`` left in energy.py by
test_evse_drain_precedence_session_b2c1_fixup.py).

Pattern (mirrored from
quality/tests/test_owner_registry_mutation_matrix.py, v5.100.9): copy
the two mutable trees (`custom_components/`, `quality/`) to a tmp dir,
symlink everything else at the repo root, mutate exactly one file in
the tmp copy, then run the anchor test in a subprocess with
``cwd=tmp_root`` and ``PYTHONPATH`` prefixed by ``tmp_root`` so imports
and ``Path(__file__).resolve()``-based source reads all resolve
against the mutated tree. The real production file is NEVER opened for
write; an md5 invariant across every drill proves it.

`quality/` is copied (not symlinked) so anchor tests that resolve
``Path(__file__).resolve().parents[2]`` don't follow a symlink back to
the real repo and read the unmutated production source.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# _REPO = the worktree root (three parents up from this file:
# quality/tests/_mutation_sandbox.py -> quality/tests -> quality -> repo).
_REPO = Path(__file__).resolve().parent.parent.parent
_CC = _REPO / "custom_components"


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _clear_pycache_at(root: Path) -> None:
    for r, dirs, _ in os.walk(root):
        if "__pycache__" in dirs:
            shutil.rmtree(Path(r) / "__pycache__", ignore_errors=True)


def apply_mutation_in_sandbox(
    prod_path: Path,
    swap_from: str = None,
    swap_to: str = None,
    anchor_test_file: Path = None,
    anchor_test_name: str = None,
    expect: str = "KILLED",
    extra_pytest_args: tuple = (),
    mutator=None,
) -> subprocess.CompletedProcess:
    """Mutate ``prod_path`` in a tmp copy of the repo, then run
    ``anchor_test_file::anchor_test_name`` in a subprocess against the
    mutated tree.

    Args:
        prod_path: absolute path to the production file under
            ``custom_components/`` to mutate.
        swap_from / swap_to: single-shot string replacement performed
            against the tmp copy of ``prod_path``. Must be unique in
            the source; asserts if missing or a no-op.
        anchor_test_file: absolute path (under ``quality/``) of the
            test file containing the anchor test.
        anchor_test_name: pytest node name of the anchor to run
            (bare function or ``Class::method``).
        expect: ``"KILLED"`` (mutation flips the anchor RED) or
            ``"SURVIVES"`` (anchor stays GREEN under mutation).

    Invariants:
        * Real production source is NEVER opened for write. Asserts
          ``md5(prod_path)`` is unchanged after the drill.
        * ``PYTHONDONTWRITEBYTECODE=1`` and ``-p no:cacheprovider`` in
          the subprocess so stale ``.pyc`` cannot mask the mutation.
    """
    assert prod_path.is_absolute(), f"prod_path must be absolute: {prod_path}"
    assert anchor_test_file.is_absolute(), (
        f"anchor_test_file must be absolute: {anchor_test_file}"
    )

    original = prod_path.read_text(encoding="utf-8")
    if mutator is not None:
        mutated = mutator(original)
    else:
        assert swap_from is not None and swap_to is not None, (
            "either mutator=callable OR (swap_from, swap_to) is required"
        )
        assert swap_from in original, (
            f"swap_from anchor missing in {prod_path.name}: "
            f"{swap_from[:120]!r}"
        )
        mutated = original.replace(swap_from, swap_to, 1)
    assert mutated != original, "mutation was a no-op"
    md5_before = _md5(prod_path)

    with tempfile.TemporaryDirectory(prefix="ura_mut_") as td:
        tmp_root = Path(td)
        # Symlink every top-level entry EXCEPT custom_components and
        # quality (both must be real dirs so mutation writes / .resolve()
        # of test __file__ land on the mutated tree, not the real repo).
        for entry in _REPO.iterdir():
            if entry.name in ("custom_components", "quality"):
                continue
            (tmp_root / entry.name).symlink_to(entry)
        shutil.copytree(
            _CC, tmp_root / "custom_components", symlinks=False,
        )
        shutil.copytree(
            _REPO / "quality", tmp_root / "quality", symlinks=False,
        )

        rel_prod = prod_path.resolve().relative_to(_CC)
        tmp_target = tmp_root / "custom_components" / rel_prod
        tmp_target.write_text(mutated, encoding="utf-8")

        rel_test = anchor_test_file.resolve().relative_to(_REPO)
        tmp_test = tmp_root / rel_test

        _clear_pycache_at(tmp_root)

        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join([
            str(tmp_root),
            str(tmp_root / "quality"),
        ])
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [
                sys.executable, "-B", "-m", "pytest",
                f"{tmp_test}::{anchor_test_name}",
                "-x", "-p", "no:cacheprovider", "--tb=short", "-q",
                *extra_pytest_args,
            ],
            env=env, cwd=str(tmp_root),
            capture_output=True, text=True,
        )

    # SIGKILL-safe invariant: the real production file was NEVER touched.
    md5_after = _md5(prod_path)
    assert md5_after == md5_before, (
        f"SIGKILL-safe invariant violated: {prod_path} was modified by the "
        f"drill (md5 {md5_before} -> {md5_after})."
    )

    if expect == "KILLED":
        assert result.returncode != 0, (
            f"expected KILLED (anchor RED under mutation); got returncode="
            f"{result.returncode}\nSTDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-1000:]}"
        )
    elif expect == "SURVIVES":
        assert result.returncode == 0, (
            f"expected SURVIVES (anchor GREEN under mutation); got returncode="
            f"{result.returncode}\nSTDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-1000:]}"
        )
    else:
        raise ValueError(f"expect must be KILLED or SURVIVES, got {expect!r}")

    return result
