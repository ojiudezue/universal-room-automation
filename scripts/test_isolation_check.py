#!/usr/bin/env python3
"""Per-file pytest isolation check (URA test baseline guard).

Runs every `quality/tests/test_*.py` in its own pytest invocation and
reports ONLY files that fail when run in isolation. Exit code is the
number of files with real, isolated failures — so wiring this into CI
as `python3 scripts/test_isolation_check.py || exit 1` enforces a
"zero isolated failures" baseline.

Why per-file: the URA suite has cross-test pollution (shared
`sys.modules` mocks, MagicMocks left attached to homeassistant.*).
A single bulk run shows ~50 noisy failures even when nothing is
actually broken; the same files pass cleanly when invoked alone. The
isolation runner is the truth.

v4.5.2 D6: introduced after the test baseline cleanup
(quality/requirements_test.txt, conftest.py, future-annotations sweep)
that drove isolated failures from 70+ to 0.

Usage:
    python3 scripts/test_isolation_check.py [--baseline N]

Options:
    --baseline N    Allow up to N files to fail (default: 0). Use to
                    ratchet toward zero without blocking unrelated work.
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        type=int,
        default=0,
        help="Allow up to N files to fail (default: 0)",
    )
    parser.add_argument(
        "--tests-dir",
        default="quality/tests",
        help="Test directory (default: quality/tests)",
    )
    args = parser.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(repo_root)

    pattern = os.path.join(args.tests_dir, "test_*.py")
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"No tests found at {pattern}", file=sys.stderr)
        return 2

    env = {**os.environ, "PYTHONPATH": "quality"}
    real_fails: list[tuple[str, str]] = []

    print(f"Running {len(files)} test files in isolation...")
    t0 = time.monotonic()
    for path in files:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", path, "--tb=no", "-q"],
            capture_output=True,
            text=True,
            env=env,
        )
        last_line = (result.stdout + result.stderr).strip().split("\n")[-1]
        if "failed" in last_line or " error" in last_line.lower():
            real_fails.append((path, last_line))
            print(f"  FAIL  {path}: {last_line}")
    elapsed = time.monotonic() - t0

    print()
    print(f"Files: {len(files)}   real isolated fails: {len(real_fails)}   "
          f"elapsed: {elapsed:.1f}s")

    if len(real_fails) > args.baseline:
        print(
            f"\nFAIL: {len(real_fails)} isolated failures > baseline "
            f"{args.baseline}.",
            file=sys.stderr,
        )
        return 1
    if real_fails:
        print(
            f"WARN: {len(real_fails)} isolated failures within baseline "
            f"{args.baseline}; tighten the budget after fixing."
        )
    else:
        print("OK: zero isolated failures.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
