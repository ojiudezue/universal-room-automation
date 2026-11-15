#!/usr/bin/env python3
"""Generate quality/tests/fixtures/away_latency_golden_develop.json.

INV-P2-AWAY-LATENCY golden provenance (PLANNING_census_deconfliction.md §4):
run this ONLY on a develop commit that carries no census-deconfliction or
crossing-ledger production change (the branch's first commit, whose parent
is the develop merge-base). A golden regenerated after the build is a hollow
oracle (Bug Class #62) and a review finding.

It runs the test-harness replay (``_census_vision_harness``, time frozen,
the inference spy counting ``_run_inference`` calls) through pytest with the
generator test enabled.

Usage (from the repo root):
    .venv-ha/bin/python scripts/probes/gen_census_trust_golden.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    base = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    env = dict(os.environ)
    env.update({
        "URA_REGEN_CENSUS_GOLDEN": "1",
        "URA_GOLDEN_BASE": base,
        "PYTHONPATH": "quality",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    return subprocess.call(
        [sys.executable, "-m", "pytest",
         "quality/tests/test_census_trust_golden.py::test_regenerate_golden",
         "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, env=env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
