#!/usr/bin/env python3
"""Shuffle-seed collection matrix — the acceptance gate for suite order-independence.

Why this exists
---------------
`pytest --collect-only` on the DEFAULT file ordering has been reported clean
(10787 tests, 0 errors, measured 2026-09-22) while the suite is in fact NOT
order-independent. Re-ordering the test files surfaces import-time
``sys.modules`` poisoning: a test module installs a PARTIAL stub for a
production package, and any module collected afterwards that needs a real
symbol from it fails at import. Measured the same night, three seeds gave
7 / 2 / 1 collection errors with a DIFFERENT set of files failing each time.

That asymmetry is the trap this tool closes. A single default-order run is
not evidence of order-independence, and reporting it as "collection is clean"
is a false all-clear — it removes the defect from every later check while
leaving it in the tree.

Two symptom shapes seen so far, both import-time:
  * ``ImportError: cannot import name X from '...signals' (unknown location)``
    — a stub shadowed a real module, so the symbol is absent.
  * ``IndexError: list index out of range`` on ``_cc.__path__[0]``
    — ``custom_components`` was stubbed with an empty ``__path__``.

Errored files silently drop their tests, so the collected COUNT moves too
(10647 / 10598 / 10690 vs 10787). Count drift is therefore itself a signal,
not just the error lines.

Usage
-----
    PYTHONPATH=quality .venv-ha/bin/python quality/tools/collect_order_matrix.py
    PYTHONPATH=quality .venv-ha/bin/python quality/tools/collect_order_matrix.py --seeds 1 2 3 7

Exit codes: 0 = every seed collected cleanly at a stable count; 1 = at least
one seed produced collection errors or a divergent count.

Read-only: this only ever runs ``--collect-only``. It never executes a test
and never writes to the repo.
"""

from __future__ import annotations

import argparse
import pathlib
import random
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "quality" / "tests"

# "10598 tests collected, 2 errors in 20.40s" / "10787 tests collected in 12.65s"
_SUMMARY = re.compile(r"(\d+) tests? collected(?:, (\d+) errors?)?")


def _collect(files: list[str], python: str) -> tuple[int, int, list[str]]:
    """Run --collect-only over `files` in the given order.

    Returns (collected, errors, error_lines). Bytecode writing is disabled so a
    stale .pyc can never mask or fabricate an import failure.
    """
    proc = subprocess.run(
        [python, "-m", "pytest", *files, "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={**_base_env(), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": "quality"},
    )
    out = proc.stdout + proc.stderr
    collected = errors = 0
    for match in _SUMMARY.finditer(out):
        collected = int(match.group(1))
        errors = int(match.group(2) or 0)
    error_lines = [ln.strip() for ln in out.splitlines() if ln.startswith("ERROR ")]
    return collected, errors, error_lines


def _base_env() -> dict[str, str]:
    import os

    return dict(os.environ)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument(
        "--python",
        default=str(REPO_ROOT / ".venv-ha" / "bin" / "python"),
        help="Interpreter to use. MUST be the real-HA venv — bare python3 is 3.9 "
        "here and fails loudly but misleadingly (missing phcc fixtures).",
    )
    args = parser.parse_args()

    files = sorted(str(p.relative_to(REPO_ROOT)) for p in TESTS_DIR.glob("test_*.py"))
    if not files:
        print(f"no test files found under {TESTS_DIR}", file=sys.stderr)
        return 1

    print(f"{len(files)} test files · seeds {args.seeds}\n")

    baseline, base_errors, base_lines = _collect(files, args.python)
    print(f"  default order : {baseline:>6} collected, {base_errors} errors")
    for line in base_lines:
        print(f"      {line}")

    failures: list[str] = []
    if base_errors:
        failures.append("default order")

    for seed in args.seeds:
        shuffled = list(files)
        random.Random(seed).shuffle(shuffled)
        collected, errors, lines = _collect(shuffled, args.python)
        drift = collected - baseline
        flag = "" if (errors == 0 and drift == 0) else "   <-- ORDER-DEPENDENT"
        print(f"  seed {seed:<9}: {collected:>6} collected, {errors} errors, drift {drift:+d}{flag}")
        for line in lines:
            print(f"      {line}")
        if errors or drift:
            failures.append(f"seed {seed}")

    print()
    if failures:
        print(f"FAIL — suite is NOT order-independent ({', '.join(failures)}).")
        print("A clean default-order run does NOT clear this; see module docstring.")
        return 1
    print("PASS — collection is stable across every seed tried.")
    print("Note: passing N seeds is evidence, not proof. Widen --seeds to strengthen it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
