#!/usr/bin/env python3
"""Suite name-diff with a cached baseline — the validator's single entry point.

WHY (2026-09-26, operator: "make the changes now to make the test strategy and
fix ups faster"). On the v5.103.15 cycle every name-diff re-ran the develop
baseline (~8 min) even though develop's CODE never changed (docs-only commits),
so each comparison cost ~17 min instead of ~8. The baseline's failing-test set is
a pure function of the code + tests, so it is cached keyed by the git tree hashes
of the directories that determine it. A baseline is re-run only when that key
changes.

Usage:
  python3 scripts/suite_namediff.py --branch-dir <worktree> [--base-ref develop]
         [--files quality/tests/a.py quality/tests/b.py] [--dry-run]

  --files   targeted mode: run only these test files on both sides (cached by
            key + file list). Use for test-only fix rounds; the full run stays
            the pre-merge gate.
  --isolate with --files: run EACH file in its own pytest process (union of failures). Catches a
            test that passes in suite order only because an earlier file loaded the real module
            (W1-A 2026-09-26: test_heatcool_enforcer broke in isolation, invisible to the full run).
  --dry-run print the keys and whether each side is cached; run nothing.

Exit codes: 0 = no NEW failing names; 1 = NEW failing names; 2 = usage/infra error.

Serialisation: the PreToolUse guard (scripts/hooks/pytest_serialize.sh) only sees
command text, and this wrapper's command line does not contain "pytest", so the
script enforces serialisation itself — it WAITS (does not die) while another
`python -m pytest` process is running, then runs one suite at a time.

Both sides must be COMMITTED trees (the key is a git tree hash). A dirty branch
worktree is refused, because its cached result would be keyed to code it did not
run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO / ".claude" / "suite-cache"
PY = REPO / ".venv-ha" / "bin" / "python"
# Everything that can change which tests fail. Docs, board, vibememo are excluded
# on purpose — they never affect the suite.
KEY_PATHS = ["custom_components", "quality"]
KEY_FILES = ["pytest.ini", "setup.cfg", "pyproject.toml", "conftest.py"]
GUARD_PATTERN = r"python[0-9.]* -m pytest"
WAIT_MAX_S = 3 * 3600
NAME_RE = re.compile(r"^(FAILED|ERROR) (\S+?)(?: - .*)?$")


def sh(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def tree_key(ref: str, extra: list[str] | None = None) -> str:
    parts = []
    for p in KEY_PATHS:
        parts.append(f"{p}={sh(['git', 'rev-parse', f'{ref}:{p}'], cwd=REPO)}")
    for f in KEY_FILES:
        r = subprocess.run(["git", "rev-parse", f"{ref}:{f}"], cwd=REPO, capture_output=True, text=True)
        if r.returncode == 0:
            parts.append(f"{f}={r.stdout.strip()}")
    if extra:
        parts.append("files=" + ",".join(sorted(extra)))
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:20]


def wait_for_turn() -> None:
    waited = 0
    while True:
        r = subprocess.run(["pgrep", "-f", GUARD_PATTERN], capture_output=True, text=True)
        pids = [p for p in r.stdout.split() if p and int(p) != os.getpid()]
        if not pids:
            return
        if waited == 0:
            print(f"[suite_namediff] another pytest is running (pids {pids}); waiting for it to finish…", flush=True)
        if waited >= WAIT_MAX_S:
            raise RuntimeError(f"gave up waiting after {WAIT_MAX_S}s for pytest pids {pids}")
        time.sleep(20)
        waited += 20


def run_suite(cwd: Path, files: list[str] | None, isolate: bool = False) -> tuple[set[str], dict]:
    if isolate and files:
        allnames, secs = set(), 0.0
        for f in files:
            n, m = run_suite(cwd, [f])
            allnames |= n
            secs += m["seconds"]
        return allnames, {"seconds": round(secs, 1), "summary": f"isolated x{len(files)}", "returncode": 0}
    for d in cwd.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
    env = dict(os.environ, PYTHONPATH="quality", PYTHONDONTWRITEBYTECODE="1")
    targets = files or ["quality/tests/"]
    wait_for_turn()
    t0 = time.time()
    r = subprocess.run(
        [str(PY), "-m", "pytest", *targets, "-q", "-rfE", "-p", "no:cacheprovider"],
        cwd=cwd, env=env, capture_output=True, text=True,
    )
    dur = round(time.time() - t0, 1)
    names = set()
    for line in (r.stdout + "\n" + r.stderr).splitlines():
        m = NAME_RE.match(line.strip())
        if m:
            names.add(m.group(2))
    tail = [l for l in r.stdout.splitlines() if l.strip()][-1:] or [""]
    return names, {"seconds": dur, "summary": tail[0], "returncode": r.returncode}


def cached_or_run(key: str, cwd_factory, files, label: str, isolate: bool = False) -> tuple[set[str], dict, bool]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = CACHE_DIR / f"{key}.json"
    if f.exists():
        d = json.loads(f.read_text())
        return set(d["failing"]), d["meta"], True
    cwd, cleanup = cwd_factory()
    try:
        print(f"[suite_namediff] running {label} suite in {cwd} …", flush=True)
        names, meta = run_suite(cwd, files, isolate)
    finally:
        cleanup()
    f.write_text(json.dumps({"failing": sorted(names), "meta": meta}, indent=1))
    return names, meta, False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch-dir", required=True)
    ap.add_argument("--base-ref", default="develop")
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--isolate", action="store_true")
    a = ap.parse_args()

    bdir = Path(a.branch_dir).resolve()
    if sh(["git", "status", "--porcelain", "--", *KEY_PATHS], cwd=bdir):
        print("[suite_namediff] branch worktree has uncommitted changes under custom_components/ or quality/ — commit first.", file=sys.stderr)
        return 2
    branch_ref = sh(["git", "rev-parse", "HEAD"], cwd=bdir)
    base_ref = sh(["git", "rev-parse", a.base_ref], cwd=REPO)
    extra = (a.files or []) + (["--isolate"] if a.isolate else [])
    bkey = tree_key(base_ref, extra or None)
    rkey = tree_key(branch_ref, extra or None)

    if a.dry_run:
        for lbl, k in (("base", bkey), ("branch", rkey)):
            print(f"{lbl}: key={k} cached={(CACHE_DIR / f'{k}.json').exists()}")
        return 0

    def base_factory():
        wt = REPO / ".claude" / "worktrees" / f"suite-baseline-{bkey[:12]}"
        if wt.exists():
            sh(["git", "worktree", "remove", "--force", str(wt)], cwd=REPO, check=False)
        sh(["git", "worktree", "add", "--detach", str(wt), base_ref], cwd=REPO)
        return wt, lambda: sh(["git", "worktree", "remove", "--force", str(wt)], cwd=REPO, check=False)

    base_names, base_meta, base_hit = cached_or_run(bkey, base_factory, a.files, "baseline", a.isolate)
    br_names, br_meta, br_hit = cached_or_run(rkey, lambda: (bdir, lambda: None), a.files, "branch", a.isolate)

    new = sorted(br_names - base_names)
    gone = sorted(base_names - br_names)
    report = {
        "base": {"ref": base_ref[:10], "key": bkey, "cached": base_hit, **base_meta, "failing": len(base_names)},
        "branch": {"ref": branch_ref[:10], "key": rkey, "cached": br_hit, **br_meta, "failing": len(br_names)},
        "new": new, "gone": gone, "mode": ("isolated" if a.isolate else "targeted") if a.files else "full",
    }
    print(json.dumps(report, indent=1))
    print(f"[suite_namediff] {'CLEAN' if not new else 'REGRESSION'}: {len(new)} NEW, {len(gone)} GONE "
          f"(baseline {'cached' if base_hit else 'ran'}, branch {'cached' if br_hit else 'ran'})")
    return 1 if new else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        print(f"[suite_namediff] {e}", file=sys.stderr)
        sys.exit(2)
