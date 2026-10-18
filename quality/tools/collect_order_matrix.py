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

Collect mode is read-only: it only ever runs ``--collect-only``.

Run mode (TEST-HARNESS Wave 2 D7)
---------------------------------
Collection-time poisoning is only half the defect: a module can also leak a
stub/monkeypatch at EXECUTION time and turn a later file's tests red. ``--run``
executes the selected files in the default order, in each seeded FILE-level
shuffle and (``--reverse``) in reverse, and reports per-test outcome diffs
against the default order::

    ... collect_order_matrix.py --run --seeds 1 2 3 --reverse
    ... collect_order_matrix.py --run --files quality/tests/test_a.py quality/tests/test_b.py

``--find-donors`` then bisects, for every victim (a test that does not fail in
the default order but fails in a shuffled order), the files that preceded the
victim's file in the failing order down to the single file ("donor") whose
presence before the victim makes it fail. Output is a donor -> victim table.
A victim whose failure needs several files is reported as ``<multi:N>`` with
the reduced set. ``--victim NODEID --files A B ... V`` bisects one victim
against an explicit prefix (the order given).

Run mode executes tests but writes nothing to the repo (junit XML goes to a
temporary directory) and never mutates source.
"""

from __future__ import annotations

import argparse
import pathlib
import random
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

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


# --------------------------------------------------------------------------
# Run mode
# --------------------------------------------------------------------------

# Rung-1 knob (planning doc §7): default seeds for the order matrix.
ORDER_MATRIX_SEEDS = (1, 2, 3)
FAILED_OUTCOMES = ("failed", "error")


def run_order(
    files: list[str], python: str, cwd: pathlib.Path = REPO_ROOT, extra: tuple = ()
) -> dict[str, str]:
    """Execute ``files`` in the given order; return {nodeid: outcome}.

    outcome is passed / failed / error / skipped. A file that fails to collect
    is reported as ``<file>::<collection>`` -> error (its tests vanish).
    """
    with tempfile.TemporaryDirectory(prefix="order_matrix_") as tmp:
        xml_path = pathlib.Path(tmp) / "junit.xml"
        proc = subprocess.run(
            [python, "-m", "pytest", *files, "-q", "-p", "no:cacheprovider",
             "-p", "no:randomly", "-o", "junit_family=xunit1",
             # Without this one file's import error aborts the whole session
             # and every later file's tests vanish from the comparison.
             "--continue-on-collection-errors",
             f"--junitxml={xml_path}", *extra],
            cwd=cwd,
            capture_output=True,
            text=True,
            env={**_base_env(), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": "quality"},
        )
        if not xml_path.exists():
            return {"<session>::<no-junit>": "error"}
        res = _parse_junit(xml_path)
    # junit drops collection errors of individual files in some pytest
    # versions; recover them from the terminal "ERROR <file>" lines.
    for ln in (proc.stdout + proc.stderr).splitlines():
        m = re.match(r"ERROR (\S+\.py)(?:\s|$)", ln)
        if m and not any(file_of(n) == m.group(1) for n in res):
            res[f"{m.group(1)}::<collection>"] = "error"
    return res


def _parse_junit(xml_path: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for case in ET.parse(xml_path).getroot().iter("testcase"):
        classname = case.get("classname", "")
        name = case.get("name", "")
        nodeid = _nodeid(classname, name, case.get("file"))
        outcome = "passed"
        for child in case:
            if child.tag == "failure":
                outcome = "failed"
            elif child.tag == "error":
                outcome = "error"
                if child.get("message") == "collection failure" and case.get("file"):
                    nodeid = f"{case.get('file')}::<collection>"
            elif child.tag == "skipped":
                outcome = "skipped"
        out.setdefault(nodeid, outcome)
        # setup error + test fail on one node: keep the worse outcome.
        if outcome in FAILED_OUTCOMES:
            out[nodeid] = outcome
    return out


def _nodeid(classname: str, name: str, file_attr) -> str:
    # xunit1 carries file="quality/tests/test_x.py"; classname is
    # "quality.tests.test_x[.Class]".
    if file_attr and file_attr.endswith(".py"):
        mod = file_attr[:-3].replace("/", ".")
        rest = classname[len(mod):].lstrip(".") if classname.startswith(mod) else ""
        parts = [file_attr] + ([rest.replace(".", "::")] if rest else []) + [name]
        return "::".join(parts)
    return f"{classname}::{name}"


def file_of(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def victims_of(baseline: dict[str, str], other: dict[str, str]) -> list[str]:
    """Nodeids that do not fail in ``baseline`` but fail in ``other``."""
    return sorted(
        n for n, o in other.items()
        if o in FAILED_OUTCOMES and baseline.get(n) not in FAILED_OUTCOMES
    )


def _victim_fails(prefix: list[str], victim: str, python: str, cwd: pathlib.Path) -> bool:
    vfile = file_of(victim)
    res = run_order([f for f in prefix if f != vfile] + [vfile], python, cwd)
    if victim in res:
        return res[victim] in FAILED_OUTCOMES
    # Victim vanished (its file failed to collect / crashed the session).
    return any(file_of(n) in (vfile, "<session>") and o in FAILED_OUTCOMES for n, o in res.items())


def find_donor(
    prefix: list[str], victim: str, python: str, cwd: pathlib.Path = REPO_ROOT
) -> list[str]:
    """Reduce ``prefix`` (files run before the victim's file) to the donor(s).

    Returns [donor] for a single-file donor, the reduced list when the failure
    needs files from both halves (multi-donor), or [] when the victim does not
    fail after the full prefix (not reproduced). Halving bisection:
    ~log2(len(prefix)) pytest runs.
    """
    vfile = file_of(victim)
    cand = [f for f in prefix if f != vfile]
    if not cand or not _victim_fails(cand, victim, python, cwd):
        return []
    while len(cand) > 1:
        mid = len(cand) // 2
        left, right = cand[:mid], cand[mid:]
        if _victim_fails(left, victim, python, cwd):
            cand = left
        elif _victim_fails(right, victim, python, cwd):
            cand = right
        else:
            return cand
    return cand


def _orders(files: list[str], seeds, reverse: bool) -> list[tuple[str, list[str]]]:
    orders = []
    for seed in seeds:
        shuffled = list(files)
        random.Random(seed).shuffle(shuffled)
        orders.append((f"seed {seed}", shuffled))
    if reverse:
        orders.append(("reverse", list(reversed(files))))
    return orders


def _donor_label(donor: list[str]) -> str:
    if not donor:
        return "<not-reproduced>"
    if len(donor) == 1:
        return donor[0]
    return f"<multi:{len(donor)}> " + " ".join(donor)


def run_matrix(args, files: list[str], cwd: pathlib.Path = REPO_ROOT) -> tuple[int, list]:
    print(f"RUN mode · {len(files)} files · seeds {args.seeds} · reverse={args.reverse}\n")
    baseline = run_order(files, args.python, cwd)
    base_fail = sorted(n for n, o in baseline.items() if o in FAILED_OUTCOMES)
    print(f"  default order : {len(baseline)} results, {len(base_fail)} failing")
    for n in base_fail:
        print(f"      x {n}")

    order_dependent = False
    table: list[tuple[str, str, str]] = []
    for label, order in _orders(files, args.seeds, args.reverse):
        res = run_order(order, args.python, cwd)
        vics = victims_of(baseline, res)
        healed = victims_of(res, baseline)
        flag = "   <-- ORDER-DEPENDENT" if (vics or healed) else ""
        print(f"  {label:<14}: {len(res)} results, {len(vics)} new fails, {len(healed)} healed{flag}")
        for v in vics:
            print(f"      + {v}")
        for h in healed:
            print(f"      - {h}  (fails in DEFAULT order only)")
        order_dependent = order_dependent or bool(vics or healed)
        if args.find_donors:
            per_file: dict[str, list[str]] = {}
            for v in vics:
                vfile = file_of(v)
                if vfile not in order:
                    continue
                if vfile not in per_file:  # one bisection per victim FILE
                    per_file[vfile] = find_donor(order[: order.index(vfile)], v, args.python, cwd)
                table.append((label, _donor_label(per_file[vfile]), v))

    if args.find_donors:
        _print_table(table)
    print()
    if order_dependent:
        print("FAIL — per-test outcomes differ across file orders.")
        return 1, table
    print("PASS — per-test outcomes identical across every order tried.")
    return 0, table


def _print_table(table) -> None:
    print("\nDONOR -> VICTIM")
    print("order | donor | victim")
    for label, donor, victim in table:
        print(f"{label} | {donor} | {victim}")


def run_victim(args, files: list[str]) -> int:
    donor = find_donor(files, args.victim, args.python)
    _print_table([("given", _donor_label(donor), args.victim)])
    return 1 if donor else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(ORDER_MATRIX_SEEDS))
    parser.add_argument("--run", action="store_true", help="Execute (not just collect) per order.")
    parser.add_argument("--reverse", action="store_true", help="Also run the reversed file order.")
    parser.add_argument("--find-donors", action="store_true", help="Bisect each victim to its donor file.")
    parser.add_argument("--files", nargs="+", help="Restrict to these files (repo-relative, order kept).")
    parser.add_argument("--victim", help="Bisect this nodeid against --files (the prefix, in order).")
    parser.add_argument(
        "--python",
        default=str(REPO_ROOT / ".venv-ha" / "bin" / "python"),
        help="Interpreter to use. MUST be the real-HA venv — bare python3 is 3.9 "
        "here and fails loudly but misleadingly (missing phcc fixtures).",
    )
    args = parser.parse_args()

    if args.files:
        files = list(args.files)
    else:
        files = sorted(str(p.relative_to(REPO_ROOT)) for p in TESTS_DIR.glob("test_*.py"))
    if args.victim:
        return run_victim(args, files)
    if args.run or args.find_donors:
        return run_matrix(args, files)[0]
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
