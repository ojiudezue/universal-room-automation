# PLANNING v4.7.10 — `deploy.sh` Gitea Retrofit (Phase A — parallel-merge, ships first)

**Status:** Plan ready for build
**Tier:** **Tier 2-DB** (THREE parallel staff-engineer reviews, different framings) — user-upgraded from Tier 1 due to **parallel + merge risk** in Phase A and credential-handling surface
**Predecessor:** v4.7.7 — AC Nudge / AC Reset Decouple + DPM Sensor Cleanup (LIVE 2026-05-29)
**Phase A peers (parallel cycles, separate worktrees):** v4.7.8 (Egress), v4.7.9 (Hygiene). Merge order: **Gitea (v4.7.10) → Hygiene (v4.7.9) → Egress (v4.7.8)** — Gitea ships first because it is the smallest, most isolated, and lowest-blast-radius change in Phase A.
**Filed:** 2026-05-29
**Recall:** "Plan v4.7.10 — deploy.sh gitea retrofit" / "Resume v4.7.10"

---

## 1. Tier Classification

**Tier 2-DB.** Not because this touches `database.py` (it does not) but because the user explicitly upgraded this cycle to a 3-reviewer cadence to address **two non-DB risk axes that map onto the same multi-framing discipline**:

1. **Secrets / credential hygiene** — a single mistake leaks a Gitea token into `.git/config` or stdout.
2. **Parallel-merge risk** — three Phase A cycles running in separate worktrees against `develop`. If Gitea silently touches files outside `scripts/`, the sequential merges into `develop` will conflict or, worse, reintroduce changes that the other cycles already replaced.

The user-coined rule applies: *"3x staff end reviews that are targeted at diff risks."* Two reviewers using overlapping framings converge on the same blind spots. The three framings below are deliberately disjoint (state-machine, lifecycle/resilience, secret-hygiene+parallel-merge).

Tier 2-DB trigger check (for completeness):

| Tier 2-DB Trigger (canonical) | Hit? | Notes |
|---|---|---|
| Touches `database.py` DAO definitions | No | n/a — this cycle is `scripts/` only. |
| Migrates ≥3 callers to a new DAO | No | n/a. |
| Changes payload shape of a dispatched event / persisted record | No | n/a. |
| Adds behavioral test infrastructure against real schemas | No | n/a. |
| Followed within 1-2 versions by a planned schema migration | No | n/a. |
| **User-upgrade override (this cycle)** | **YES** | Phase A parallel-merge risk + secret-handling surface. User explicitly raised tier 2026-05-29. |

**Dispatch:** THREE parallel reviewers per §10. Framings deliberately disjoint so blind spots do not overlap.

---

## 2. Goal + Why

### Goal

Make `scripts/deploy.sh` reliably push every release to **both** GitHub origin **and** the user's homelab Gitea (`gitea.phalanxmadrone.com`) via `scripts/dual-push.sh`. Today the dual-push step is invoked but **observably fails** during v4.7.7 deploy logs with `gitea push failed — origin already pushed; gitea is mirror-only`. Investigate why, fix it, and lock the contract so future deploys are dual-mirrored.

### Why (the user mandate)

From `feedback_dual_commit_gitea.md` (2026-05-21, captured during PWA cycle):

> *"peace of mind to save to data stack I control."*

GitHub is convenient but external. Gitea at the homelab (CT 105, `192.168.13.130:3000`, public `git.phalanxmadrone.com` through Caddy + TinyAuth) is the user-controlled redundancy. URA's deploy script was supposed to be retrofitted post-PWA cycle. PWA closed (v6.0.1 live 2026-05-24). This is that retrofit.

### Why now (Phase A, ships first)

Phase A has three parallel cycles. Gitea is the **cleanly isolated** one — touches ONLY `scripts/deploy.sh` and `scripts/dual-push.sh`. Zero overlap with Egress (v4.7.8) or Hygiene (v4.7.9). Merging Gitea first means Hygiene and Egress can rebase against a clean `develop` without worrying about script collisions. If Gitea were to merge LAST, any conflict-resolution mistake in `scripts/` would risk silently undoing the Egress or Hygiene changes that already touched (e.g.) `__init__.py` and `manifest.json`.

### Today's observed failure (the bug we're fixing)

`scripts/deploy.sh` lines 73-80 (current `develop` HEAD):

```bash
if git -C "$REPO_DIR" remote get-url gitea >/dev/null 2>&1; then
  if $DRY_RUN; then
    echo "  [dry-run] bash scripts/dual-push.sh develop  (gitea mirror only)"
  else
    bash "$REPO_DIR/scripts/dual-push.sh" develop || \
      echo "  [warn] gitea push failed — origin already pushed; gitea is mirror-only"
  fi
fi
```

The fact that v4.7.7 deploy logs printed `[warn] gitea push failed` means **the `gitea` remote already exists locally** (the `remote get-url gitea` returned 0) but the push itself errored. Likely causes (to be confirmed by build agent at investigation step §3.D1):

- (a) `.env.local` is present but missing `GITEA_USER` / `GITEA_TOKEN` (lines 30-33 of `dual-push.sh` would print to stderr and `return 1`).
- (b) `.env.local` is absent and the osxkeychain fallback at `dual-push.sh:40-43` does not have credentials cached.
- (c) `dual-push.sh` already pushed origin (lines 47-48), so when invoked from `deploy.sh` AFTER `deploy.sh` already did `git push origin develop` (line 70), the second `git push origin` returns 0 (already up-to-date) — that path is fine. The actual failure is on the gitea side.
- (d) `gitea` remote is set to a stale URL (e.g., from PWA-era template).

**Critical observation surfacing now:** `dual-push.sh` **also pushes origin** (lines 47-49) before pushing gitea (line 52). When invoked from `deploy.sh`, origin has ALREADY been pushed at step 4 (line 70). So `dual-push.sh` re-pushes origin (idempotent, returns 0) and then attempts gitea. **This is wasteful but not harmful.** The retrofit should make this explicit and consider adding a `--gitea-only` mode to `dual-push.sh` so `deploy.sh` does not double-push origin.

---

## 3. Discovery — Read Before Build (Mandatory)

Builder MUST read these before code changes and cite file:line in code comments where patterns are reused.

| File | Lines | Why |
|---|---|---|
| `scripts/deploy.sh` | 1-114 (whole file) | The pipeline. Step 4 (lines 68-80) is the only block touched. `set -euo pipefail` at line 8 governs failure propagation. The `\|\| echo "  [warn] ..."` short-circuit at line 78 is the existing failure-tolerance contract — preserve it. |
| `scripts/dual-push.sh` | 1-55 (whole file) | The mirror-push helper. Trap at line 24 restores clean URL. Credential injection at lines 26-44. **Key reads:** (a) line 11 `set -euo pipefail` interplay with the trap; (b) lines 47-49 origin push happens UNCONDITIONALLY (the double-push observation); (c) line 36 token interpolation into URL — must verify no `set -x` or `echo` of `$GITEA_TOKEN` anywhere in the script. |
| `.gitignore` | 56-57 (`.env` + `.env.local`) | Confirms `.env.local` is gitignored — Reviewer C will re-verify. |
| `docs/readmes/README_v4.7.7.md` | 200-207 (Pre-Deploy Zero-Bugs Gate section) | Reference gate-shape this cycle adopts + adds gate 6. |
| `WORKFLOW_GUIDE.md` | full | Cycle protocol. |
| `docs/QUALITY_CONTEXT.md` | bug class index | Cross-check for any class touching shell/credential handling (none expected — URA bug classes are HA-runtime focused — but verify). |
| `~/Code/ura-dashboard-pwa/scripts/dual-push.sh` (reference, read-only) | full | The PWA mirror this script was copied from (`dual-push.sh:3`). Confirms canonical pattern. **DO NOT modify** the PWA file. |
| `~/Code/homelab-automation/docs/plan-ziri-website-sync.md` | 153-168 (per `feedback_dual_commit_gitea.md`) | Canonical dual-push sequence reference. Read once for context, do not copy. |

**Build-time investigation (D1, before any code change):**

1. `cd /Users/okosisi/Code/universal-room-automation && git remote -v` — capture current `gitea` remote URL (if any). Note: do NOT paste this into the planning doc or commit — it may contain a token.
2. `ls -la .env.local 2>&1 \|\| echo absent` — does the file exist?
3. If `.env.local` exists, grep for required keys WITHOUT printing values: `grep -c '^GITEA_USER=' .env.local; grep -c '^GITEA_TOKEN=' .env.local; grep -c '^GITEA_REPO=' .env.local`. Counts only, never values.
4. Try a manual `bash scripts/dual-push.sh develop` and capture stderr (redact any URL containing `:` followed by non-`/` characters before pasting anywhere).
5. Confirm the network reachability of `gitea.phalanxmadrone.com` from the dev machine (`curl -sI https://gitea.phalanxmadrone.com/ \| head -1`).

Output of D1 goes into the implementation commit body, NOT into a separate doc, NOT into stdout that gets logged anywhere.

---

## 4. Deliverables

### D1 — Root-cause investigation of the v4.7.7 `gitea push failed` warning

Build agent runs the §3 investigation steps. Captures findings in commit body. **No code change at this step** — this is a precondition that informs D2-D5 scope.

Likely outcomes (one or more):
- (a) `.env.local` missing required keys → D2 hardens the error message and adds a pre-flight check in `deploy.sh`.
- (b) `gitea` remote URL stale or missing repo path → D3 documents the expected remote shape and adds a validation function.
- (c) `dual-push.sh` is double-pushing origin → D4 adds `--gitea-only` mode.
- (d) Network reachability problem → out of scope, document only.

**Acceptance Criteria:**
- **Verify:** D1 commit body contains a redacted summary of which of (a)–(d) was the root cause.
- **Verify:** No credentials, tokens, or full remote URLs containing user:token appear in the commit body, any log, or any file changed in this cycle.

### D2 — Pre-flight credential check in `dual-push.sh`

Add an early check at the top of `inject_gitea_creds` (currently `dual-push.sh:26`): before sourcing `.env.local`, check whether the gitea remote URL points at the expected host (`gitea.phalanxmadrone.com`). If not, log a clear actionable error and exit nonzero. If `.env.local` is missing AND the osxkeychain has no entry, fail FAST with an instruction string ("create `.env.local` with `GITEA_USER`, `GITEA_TOKEN`, `GITEA_REPO`"). Today's behavior at lines 40-44 silently falls through to `git push gitea` which will then prompt or hang.

Concretely:
- Add a function `_dualpush_preflight()` near the top of `dual-push.sh` that validates: (i) gitea remote exists, (ii) gitea remote URL host matches `gitea.phalanxmadrone.com`, (iii) either `.env.local` exists with required keys OR `git config --global credential.helper` is set to a non-empty value (osxkeychain fallback acceptable).
- Call `_dualpush_preflight` BEFORE the origin push at line 47. If it fails, exit nonzero with a clear message; do NOT touch origin.

**Acceptance Criteria:**
- **Verify:** With a clean repo and no `.env.local` and no osxkeychain credential, `bash scripts/dual-push.sh develop` exits nonzero within 1 second with a message starting `[dual-push] preflight failed:` and a one-line remediation hint.
- **Verify:** No `GITEA_TOKEN` or `GITEA_USER` value appears anywhere in stdout/stderr.
- **Verify:** `git remote get-url gitea` after a failed pre-flight returns the SAME clean URL it had before (no `https://user:token@` left in `.git/config`).
- **Test:** `quality/tests/test_deploy_scripts.py::test_dualpush_preflight_no_env_no_keychain_fails_fast` (mocks `.env.local` absent + asserts exit code + asserts stderr shape).

### D3 — `--gitea-only` mode in `dual-push.sh`

Add a `--gitea-only` flag to `dual-push.sh` that **skips the origin push** (lines 47-49). `deploy.sh` step 4 already pushes origin at line 70; the dual-push helper should not re-push it. Today's double-push is wasteful (a network roundtrip + a chance to fail in a way that masks the gitea-only failure with origin-already-up-to-date noise).

Mode matrix:
| Invocation | Origin push | Gitea push |
|---|---|---|
| `dual-push.sh develop` (today, unchanged) | yes | yes |
| `dual-push.sh --gitea-only develop` (new) | no | yes |
| `dual-push.sh --dry-run develop` (new, see D5) | no (printed) | no (printed) |

The `deploy.sh` step 4 should switch to `dual-push.sh --gitea-only develop`.

**Acceptance Criteria:**
- **Verify:** `bash scripts/dual-push.sh --gitea-only develop` (with valid `.env.local`) pushes ONLY to gitea, not to origin.
- **Verify:** Exit code 0 on success, nonzero on gitea push failure.
- **Verify:** Flag parsing tolerates either order: `--gitea-only develop` or `develop --gitea-only` both work.
- **Test:** `quality/tests/test_deploy_scripts.py::test_dualpush_gitea_only_skips_origin` (mocks `git push` and asserts only gitea is invoked).

### D4 — `deploy.sh` step 4 retrofit

Replace the existing block at `scripts/deploy.sh:68-80` with:

1. The unconditional `git push origin develop` at line 70 stays.
2. The conditional `dual-push.sh` invocation switches to `--gitea-only` mode.
3. The `\|\| echo "  [warn] ..."` short-circuit at line 78 is preserved (gitea is mirror-only — origin success is the success criterion of the cycle).
4. Add a clearer warning message that includes the next remediation step ("run `bash scripts/dual-push.sh --gitea-only develop` manually after fixing credentials").
5. Add `set -o pipefail`-safe handling: today the `\|\| echo` swallows ALL nonzero exits including unexpected ones (e.g., bash syntax error in dual-push.sh). Bound the swallowed exit code range: only treat exit codes 1-3 as "expected gitea push failure"; anything else (syntax error 2 from bash, signal 130 SIGINT) should NOT be swallowed and SHOULD halt the deploy.

Concretely:

```bash
# Step 4: Push to develop (GitHub origin, then Gitea mirror)
step "4/7 Pushing to develop (origin + gitea)"
run git -C "$REPO_DIR" push origin develop

# Gitea mirror push (only if remote exists). Failure is non-fatal — gitea is mirror-only.
# We catch only "expected" failure codes (1=push rejected/auth/preflight). Signals
# (SIGINT=130, SIGTERM=143) and bash errors (2) are NOT swallowed.
if git -C "$REPO_DIR" remote get-url gitea >/dev/null 2>&1; then
  if $DRY_RUN; then
    echo "  [dry-run] bash scripts/dual-push.sh --gitea-only develop"
  else
    set +e
    bash "$REPO_DIR/scripts/dual-push.sh" --gitea-only develop
    rc=$?
    set -e
    if [[ $rc -eq 0 ]]; then
      :  # success
    elif [[ $rc -eq 1 ]]; then
      echo "  [warn] gitea push failed (exit 1) — origin already pushed; gitea is mirror-only."
      echo "  [warn] To catch up gitea later: bash scripts/dual-push.sh --gitea-only develop"
    else
      echo "  [error] dual-push.sh exited unexpectedly (rc=$rc) — halting deploy."
      exit "$rc"
    fi
  fi
fi
```

**Acceptance Criteria:**
- **Verify:** `bash scripts/deploy.sh 9.9.9.9 "test" "test" --dry-run` prints `[dry-run] bash scripts/dual-push.sh --gitea-only develop` (NOT the old form without the flag).
- **Verify:** When the gitea remote is absent, the step is silently skipped (current behavior preserved).
- **Verify:** When `dual-push.sh` exits with code 1 (expected gitea-side failure), `deploy.sh` continues to step 5 (PR creation).
- **Verify:** When `dual-push.sh` exits with code 2 (bash syntax error) or 130 (SIGINT), `deploy.sh` halts and propagates the exit code.
- **Test:** `quality/tests/test_deploy_scripts.py::test_deploy_step4_swallows_rc1_propagates_rc2` (mocks `dual-push.sh` to return chosen exit codes).

### D5 — `--dry-run` mode in `dual-push.sh`

Add a `--dry-run` flag to `dual-push.sh` so the new Pre-Deploy Gate 6 (§8) can exercise the script end-to-end without actually pushing. In dry-run mode:
- Pre-flight checks still run (this is the value of the dry-run).
- `git push` invocations are PRINTED, not executed.
- No URL is ever rewritten to embed credentials (the line at `dual-push.sh:36` is the dangerous one — guard it under `! $DRY_RUN`).
- Exit 0 if pre-flight passes, nonzero if pre-flight fails (same semantics as live).

**Acceptance Criteria:**
- **Verify:** `bash scripts/dual-push.sh --dry-run develop` exits 0 on a properly-configured host without contacting gitea over the network.
- **Verify:** During dry-run, `.git/config` is never mutated (verified by hashing `.git/config` before and after).
- **Verify:** During dry-run, no `GITEA_TOKEN` value appears in stdout/stderr.
- **Test:** `quality/tests/test_deploy_scripts.py::test_dualpush_dry_run_does_not_mutate_git_config`.

### D6 — `README_v4.7.10.md`

Standard release README at `docs/readmes/README_v4.7.10.md`. Sections:
- Headline (deploy.sh now reliably dual-pushes to GitHub + Gitea)
- Per-deliverable detail (D1-D5)
- Operator notes (where `.env.local` lives, what keys it needs, how to manually catch up gitea if it falls behind, how to verify gitea is current)
- Live Validation Expectations (see §11)
- Known Limitations / Carried Forward
- Review Trail (Tier 2-DB, three reviewers — filled at cycle end)

**Acceptance Criteria:**
- **Verify:** `docs/readmes/README_v4.7.10.md` exists and is referenced from the `gh release create` step in `deploy.sh`.
- **Verify:** Operator notes section names the file path `.env.local` and the three required keys (`GITEA_USER`, `GITEA_TOKEN`, `GITEA_REPO`) but does NOT include any example value.
- **Verify:** No credentials of any form appear in the README.

### D7 — Test scaffolding (`quality/tests/test_deploy_scripts.py`)

URA does not currently have any tests against shell scripts (verified via glob: `quality/tests/test_deploy*.py` and `quality/tests/test_*script*.py` both empty). This cycle introduces ONE new test module that exercises `dual-push.sh` via Python subprocess with mocked `PATH` shims for `git`.

Pattern:
- `tests/test_deploy_scripts.py` uses `subprocess.run(["bash", "scripts/dual-push.sh", ...], env=..., cwd=tmp_repo)`.
- `tmp_repo` fixture: a `git init`'d temp directory with a fake `gitea` remote pointing at `https://gitea.phalanxmadrone.com/example/repo.git` (no credentials).
- `fake_git_bin` fixture: prepends a temp directory to `PATH` containing a `git` shim that records arguments to a log file and exits 0 (or a chosen rc).
- Tests assert against the shim's log file and the script's exit code.

Tests in scope for this cycle:
1. `test_dualpush_preflight_no_env_no_keychain_fails_fast` (D2)
2. `test_dualpush_gitea_only_skips_origin` (D3)
3. `test_deploy_step4_swallows_rc1_propagates_rc2` (D4)
4. `test_dualpush_dry_run_does_not_mutate_git_config` (D5)
5. `test_dualpush_no_credentials_in_stdout_stderr` — generic secret-leak guard. Runs `--dry-run` with a synthetic fake `GITEA_TOKEN=DECOY_TOKEN_DO_NOT_LEAK_12345` env var, asserts the literal string does NOT appear in either stream.
6. `test_dualpush_trap_restores_clean_url_on_signal` — sends SIGINT mid-push (via the git shim that sleeps then exits 130), asserts post-trap `.git/config` does NOT contain `@gitea.phalanxmadrone.com` (i.e., no embedded creds).
7. `test_dotenv_local_is_gitignored` — source-grep test asserting `.env.local` appears in `.gitignore`.
8. `test_dualpush_no_set_x` — source-grep test asserting `dual-push.sh` does NOT contain `set -x` or `set -o xtrace` (would leak credentials to stdout).

**Acceptance Criteria:**
- **Verify:** `PYTHONPATH=quality python3 -m pytest quality/tests/test_deploy_scripts.py -v` returns 8/8 passing.
- **Verify:** All 8 tests run in <10 seconds total (no real network access, no real `git push`).
- **Verify:** No test writes outside the `tmp_repo` fixture's directory.

---

## 5. Size Estimate

| Surface | LoC | Notes |
|---|---|---|
| `scripts/deploy.sh` | +15 / −5 | Step 4 block rewrite + clearer warning. |
| `scripts/dual-push.sh` | +35 / −5 | `_dualpush_preflight()` function + `--gitea-only` + `--dry-run` flag parsing + dry-run guard at URL-mutation line. |
| `docs/readmes/README_v4.7.10.md` | +90 | New file. |
| `quality/tests/test_deploy_scripts.py` | +220 | 8 tests + 2 fixtures (`tmp_repo`, `fake_git_bin`). |
| **Total prod-script LoC** | **~40 net** | Within the stated 20-50 LoC envelope. |
| **Total cycle LoC (incl. test + README)** | **~350** | Most is test scaffolding (one-time investment). |

---

## 6. Failure-State Matrix (Reviewer A will trace this exhaustively)

| Origin push result | Gitea push result | Expected deploy.sh outcome | Expected operator action |
|---|---|---|---|
| OK | OK | step 4 passes, proceeds to step 5 | none |
| OK | rc=1 (auth fail / push rejected) | step 4 prints `[warn]` with remediation, proceeds to step 5 | run `bash scripts/dual-push.sh --gitea-only develop` after fixing creds |
| OK | rc=2 (bash error in dual-push.sh) | step 4 HALTS, propagates rc=2 | fix the script; re-run deploy.sh |
| OK | rc=130 (SIGINT) | step 4 HALTS, propagates rc=130 | manual investigation |
| OK | pre-flight failed (rc=1) before any push | step 4 prints `[warn]`, proceeds to step 5 | fix `.env.local` or remote URL |
| FAIL (origin) | n/a (never reached — `dual-push.sh --gitea-only` is invoked AFTER origin) | step 4 HALTS at `git push origin develop` (line 70), rc=1 from set -e | fix origin auth |
| OK | OK BUT `.git/config` still has token URL | regression — Reviewer C blocks | trap broken — investigate trap firing |

The last row is the **secret-leak failure mode**. The trap at `dual-push.sh:24` is supposed to restore the clean URL on every exit. Reviewer C verifies the trap fires under (a) normal exit, (b) `set -e` exit on push failure, (c) SIGINT, (d) SIGTERM, (e) `kill -9` (cannot be trapped — accepted residual, documented).

---

## 7. Bug Class Compliance Matrix

This cycle is bash-only — none of the URA Python-runtime bug classes (Bug Class #1 through #47) apply. Instead, the relevant classes are **shell/credential-handling** anti-patterns. Document a small dedicated checklist:

| Anti-pattern | Surface | Result |
|---|---|---|
| Credential leak via `set -x` | `dual-push.sh` | CLEAN — D7 test #8 asserts `set -x` is not present. |
| Credential leak via `echo $TOKEN` | `dual-push.sh` | CLEAN — manual code review + D7 test #5 (decoy-token grep). |
| Credential persisted in `.git/config` after exit | `dual-push.sh:36` rewrite + `:24` trap | CLEAN — D7 test #6 (SIGINT mid-push) verifies trap restores clean URL. |
| Silently swallow ALL exit codes | `deploy.sh:77-78` (today) | FIXED by D4 — only rc=1 swallowed; rc=2+, rc=130+ propagate. |
| Double-push origin (waste + masks real failure) | `dual-push.sh:47-48` invoked from `deploy.sh` | FIXED by D3 `--gitea-only` mode. |
| Pre-flight UX absent (silent osxkeychain hang) | `dual-push.sh:40-44` (today) | FIXED by D2 — pre-flight check before any push. |
| Token printed in warning message | new `[warn]` text in D4 | CLEAN — warning text refers to script path only, never to creds. |

---

## 8. Pre-Deploy Zero-Bugs Gate (5 standard + 1 cycle-specific = 6 gates)

Per the user-coined gate (post-v4.7.4.3 broken-release incident):

1. **Conflict markers clean:** `grep -rln "^<<<<<<<\|^>>>>>>>" scripts/ docs/ quality/` → zero matches.
2. **`bash -n` parse clean:** `bash -n scripts/deploy.sh` and `bash -n scripts/dual-push.sh` both exit 0 (bash dry-syntax-check; equivalent of `py_compile` for shell).
3. **JSON validity:** n/a this cycle (no JSON files touched). Skip but record as N/A.
4. **v4.7.10 cycle tests pass:** `PYTHONPATH=quality python3 -m pytest quality/tests/test_deploy_scripts.py -v` → 8/8.
5. **Full URA suite — no new failures vs `pre-review-v4.7.10` baseline.** Same shape as v4.7.7: ~4315 / 55 / 14 expected (this cycle does not touch any Python production code, so the suite should be IDENTICAL to baseline).
6. **NEW — Cycle-specific Gate 6 — dual-push dry-run:** `bash scripts/dual-push.sh --dry-run develop` exits 0 AND `git config --get remote.gitea.url` returns the same value before and after (no `.git/config` mutation). This is the live-script equivalent of test #4 from D7 but run on the actual repo (not a tmp fixture) so we know production state is intact.

**Gate 6 sub-checks (mandatory, run from a clean shell):**
- `pre_url=$(git config --get remote.gitea.url 2>/dev/null \|\| echo absent)`
- `bash scripts/dual-push.sh --dry-run develop > /tmp/ura_v4710_dryrun.log 2>&1`
- `rc=$?; [[ $rc -eq 0 ]] \|\| { echo "Gate 6 FAIL: dry-run rc=$rc"; exit 1; }`
- `post_url=$(git config --get remote.gitea.url 2>/dev/null \|\| echo absent)`
- `[[ "$pre_url" == "$post_url" ]] \|\| { echo "Gate 6 FAIL: .git/config mutated"; exit 1; }`
- `grep -E "GITEA_TOKEN=\|:[^/]+@" /tmp/ura_v4710_dryrun.log && { echo "Gate 6 FAIL: token leaked to log"; exit 1; }`
- `rm /tmp/ura_v4710_dryrun.log`

---

## 9. Pre-Review Baseline Tag

Before applying any review fix-ups:

```bash
git tag pre-review-v4.7.10 -m "Pre-review baseline for v4.7.10 (deploy.sh gitea retrofit)"
```

Diff after fix-up:

```bash
git diff pre-review-v4.7.10..HEAD -- scripts/ quality/tests/test_deploy_scripts.py docs/readmes/README_v4.7.10.md
```

**Reviewer C will run this diff and CONFIRM no files outside `scripts/`, `quality/tests/test_deploy_scripts.py`, and `docs/readmes/README_v4.7.10.md` were touched** — this is the parallel-merge-risk gate.

---

## 10. Reviewer Framings (Tier 2-DB — locked at planning)

Three parallel reviewers. Framings deliberately disjoint so blind spots do not overlap.

### Reviewer A — Correctness + state-machine invariants

Focus:
- Push-success/push-fail combinatorics — trace ALL 7 rows of the §6 failure-state matrix.
- Idempotency under retry: re-running `deploy.sh` on an already-pushed `develop` must be a no-op for both remotes.
- Trap behavior on SIGINT mid-push: verify the trap at `dual-push.sh:24` fires under `set -euo pipefail` exit, normal exit, SIGINT, SIGTERM.
- Verify the existing v4.7.7 "gitea push failed" warning is correctly preserved (D4 only NARROWS the swallowed exit-code range; the original warning intent is intact).
- `--gitea-only` flag parsing tolerant of arg order.
- `--dry-run` flag never executes a real push (grep the script for unguarded `git push`).
- Pre-flight checks ordered correctly (gitea-remote-host check BEFORE `.env.local` source — otherwise a missing `.env.local` produces a misleading error when the real problem is a stale remote).

Out of scope for Reviewer A: lifecycle, restart resilience, secret hygiene.

### Reviewer B — Async + lifecycle + restart resilience

Focus:
- Bash script lifecycle: interaction of `set -euo pipefail` (line 11) and the `trap restore_gitea_url EXIT` (line 24). Under `set -e`, the trap fires before exit on a failed command — verify this is the intended behavior on push failure.
- What happens if `dual-push.sh` is killed mid-execution (SIGINT, SIGTERM, parent shell exit) and re-run from scratch? Is there any persistent state outside `.git/config` that needs cleanup? (Expected: no — but verify.)
- Lock files: none today; consider whether `--gitea-only` invocations from `deploy.sh` and concurrent manual invocations could race. **Acceptable risk** (single-user, single-machine) — document explicitly.
- Stale `.git/config` URLs after partial-network failures: trap MUST fire even when the network drops mid-`git push`.
- Process resilience: what if `bash` itself crashes (OOM, signal 9)? trap does NOT fire on signal 9 — accept as residual, document.
- D4 step-4 retrofit: verify the `set +e` / `rc=$?` / `set -e` pattern correctly captures the dual-push exit code without leaking the temporarily-disabled error mode into subsequent steps 5/6/7.

Out of scope for Reviewer B: secret hygiene, parallel-merge risk.

### Reviewer C — New surfaces + operational safety + secret hygiene + parallel-merge risk

Focus:
- **Secret hygiene (PRIMARY):**
  - Verify `.env.local` remains in `.gitignore` (D7 test #7).
  - Verify no credentials in log output: grep `dual-push.sh` and `deploy.sh` for any `set -x`, `set -o xtrace`, or `echo` of `$GITEA_TOKEN` / `$GITEA_USER` (D7 test #8 covers `set -x`; verify the echo-grep manually).
  - Verify no credentials in `git config` after trap fires under all exit paths (D7 test #6 covers SIGINT; manually trace the other paths).
  - Verify the gitea remote URL pattern in `dual-push.sh:36` is only written when `! $DRY_RUN` (D5 acceptance).
  - Verify the warning text in `deploy.sh` (D4) does not contain any user-injected value that could be a credential (e.g., do not echo `$SUMMARY` if it could ever contain a token).
  - Verify the README does not contain any example credential.
- **Parallel-merge risk (PRIMARY):**
  - Run `git diff pre-review-v4.7.10..HEAD --stat` and confirm changed files are EXACTLY `scripts/deploy.sh`, `scripts/dual-push.sh`, `quality/tests/test_deploy_scripts.py`, `docs/readmes/README_v4.7.10.md`. Anything else is a planning bug — block merge.
  - Confirm `README_v4.7.10.md` does NOT claim to ship any change to `custom_components/universal_room_automation/`.
  - Confirm no edits to `custom_components/universal_room_automation/manifest.json` (version bump comes from `stamp_version.py` invoked by `deploy.sh` at step 1; this cycle does NOT pre-stamp).
  - Confirm no edits to `__init__.py`, `const.py`, or any HVAC/DPM file (the territories of v4.7.8 Egress and v4.7.9 Hygiene).
- **Operational safety:**
  - Verify the operator notes section of the README correctly names the file path (`.env.local` at repo root) and the three required keys.
  - Verify the `[warn]` remediation message in `deploy.sh` actually works when copy-pasted by a tired operator at 11pm.

Out of scope for Reviewer C: state-machine correctness, lifecycle.

**Disjoint-framing claim:** A traces the state machine, B traces the lifecycle/resilience, C traces secrets + merge isolation. No two reviewers look at the same surface from the same angle. Per the user-coined Tier 2-DB rule, this is the discipline that catches what two converged reviewers would miss.

---

## 11. Live Validation Plan (post-deploy)

After `./scripts/deploy.sh 4.7.10 ...` completes, verify ON THE DEV MACHINE (not on HA — this cycle does not touch HA):

1. **GitHub release exists:** `gh release view v4.7.10` returns the new release with the README body.
2. **Gitea has the tag:** `git ls-remote gitea refs/tags/v4.7.10` returns the SHA (proves gitea push succeeded). If this fails, the warning path was hit — execute the documented manual catch-up: `bash scripts/dual-push.sh --gitea-only develop && git push gitea v4.7.10`.
3. **Both remotes converged on the same SHA:**
   - `gh_sha=$(git ls-remote origin develop \| awk '{print $1}')`
   - `gt_sha=$(git ls-remote gitea develop \| awk '{print $1}')`
   - `[[ "$gh_sha" == "$gt_sha" ]] \|\| echo "MISMATCH — gitea behind"`
4. **`.git/config` clean:** `git config --get remote.gitea.url` returns a URL with NO `@` (i.e., no embedded creds). If `:` appears in the URL before the host (e.g., `https://user:token@...`), the trap failed to fire — BUG.
5. **Re-run idempotency:** `bash scripts/dual-push.sh --gitea-only --dry-run develop` exits 0; no `.git/config` mutation.
6. **No regression in HA:** because this cycle does NOT touch `custom_components/`, no HA restart is needed and no HA-side validation is required. **This is the strongest signal that the cycle is correctly scoped** — Reviewer C verifies via the pre-review-tag diff.

**Phase-A-specific live check (after Hygiene and Egress also merge):**
7. **Three-way merge clean:** after `develop` has absorbed all three Phase A cycles (Gitea → Hygiene → Egress), `git log --oneline develop ^pre-phase-a` shows three distinct merge points with no conflict-resolution commits. If a `Merge conflict resolved` commit appears, parallel-merge isolation failed — root-cause before deploying any Phase A release.

---

## 12. Explicit Non-Goals

- Do NOT touch any production code in `custom_components/universal_room_automation/`.
- Do NOT change the GitHub origin URL or its auth method (`gh auth` / HTTPS+PAT remains the source of truth for origin).
- Do NOT add Gitea as a third release-creation target — releases (`gh release create`) only go to GitHub. Gitea is mirror-only (tags + branches, no Releases API).
- Do NOT add Gitea-side PR creation. Mirror push only.
- Do NOT add new dependencies. Bash + standard `git` only. No `python` calls from the shell scripts. No `curl`, no `jq`. (Test scaffolding uses Python because URA's tests are Python — the production scripts stay bash-only.)
- Do NOT broaden the `.env.local` schema beyond the existing three keys (`GITEA_USER`, `GITEA_TOKEN`, `GITEA_REPO`). Any future expansion is a separate cycle.
- Do NOT change `scripts/stamp_version.py` or any other deploy step (steps 1-3 and 5-7).
- Do NOT attempt to remove the `--warn-on-gitea-fail` semantic. Origin success remains the deploy success criterion. Gitea is a redundancy, not a hard requirement.
- Do NOT add a Slack/email notification on gitea failure. The `[warn]` text in stdout is sufficient for a single-operator project.

---

## 13. Parallel-Merge Risk Discipline (cycle-specific)

This cycle runs in PARALLEL with v4.7.8 (Egress) and v4.7.9 (Hygiene) in separate worktrees. To prevent merge conflicts and silent regressions:

1. **Worktree path:** this cycle's branch is `feature/v4.7.10-gitea-retrofit`, working in `.claude/worktrees/agent-<hash>/` per existing URA worktree convention.
2. **No `develop` rebase mid-cycle.** Build agent does NOT rebase against `develop` while the other two Phase A cycles are in flight. The merge order (Gitea → Hygiene → Egress) means Gitea merges FIRST against the Phase A baseline, then Hygiene rebases onto Gitea-merged-develop, then Egress rebases onto Hygiene-merged-develop.
3. **File-touch contract:** this cycle modifies EXACTLY these files:
   - `scripts/deploy.sh`
   - `scripts/dual-push.sh`
   - `quality/tests/test_deploy_scripts.py` (new)
   - `docs/readmes/README_v4.7.10.md` (new)
   - `custom_components/universal_room_automation/const.py` (version bump only, via `stamp_version.py` at deploy time — NOT pre-stamped)
   - `custom_components/universal_room_automation/manifest.json` (version bump only, via `stamp_version.py` — NOT pre-stamped)
4. **Reviewer C gate:** §10 Reviewer C runs `git diff pre-review-v4.7.10..HEAD --stat` and CONFIRMS the changed-file list. Anything outside this contract BLOCKS merge.
5. **Phase A merge captain (operator):** after Gitea merges to `develop`, the operator (user) signals the Hygiene and Egress agents to rebase. This is NOT automated; it is a manual sequencing point.

---

## 14. Plan-Completion Tracking (filled at cycle end)

After implementation completes, fill the table below explicitly. Per the user-mandated "no silent drops" rule:

| Planned deliverable | Status | If deferred — why + where tracked |
|---|---|---|
| D1 root-cause investigation | TBD | |
| D2 pre-flight credential check | TBD | |
| D3 `--gitea-only` mode | TBD | |
| D4 `deploy.sh` step 4 retrofit | TBD | |
| D5 `--dry-run` mode | TBD | |
| D6 README_v4.7.10.md | TBD | |
| D7 test scaffolding (8 tests) | TBD | |
| Gate 6 (dual-push dry-run) added | TBD | |
| Pre-review baseline tag | TBD | |
| Three Tier-2-DB review passes | TBD | A: ___ / B: ___ / C: ___ |
| Live validation steps 1-7 | TBD | |

---

## 15. Reference Files Cited

- `scripts/deploy.sh` (current `develop` HEAD) — lines 1-114, step 4 at 68-80
- `scripts/dual-push.sh` (current `develop` HEAD) — lines 1-55, trap at 24, URL-rewrite at 36, origin push at 47-49
- `.gitignore` lines 56-57 (`.env` + `.env.local`)
- `docs/readmes/README_v4.7.7.md` — Pre-Deploy Zero-Bugs Gate section, reviewer-framing template
- `~/Code/ura-dashboard-pwa/scripts/dual-push.sh` (referenced from `dual-push.sh:3` as the source mirror — read-only reference)
- `feedback_dual_commit_gitea.md` (memory, 2026-05-21) — user mandate
- `WORKFLOW_GUIDE.md` — cycle protocol
- `CLAUDE.md` § Review Protocol — Tier 2-DB definition

---

## 16. Verified Pre-Read Notes (from planning agent, 2026-05-29)

Read in full at planning time:

- **`scripts/deploy.sh` exists** (lines 1-114). Step 4 (`68-80`) already invokes `dual-push.sh` conditionally on `gitea` remote presence with a `\|\| echo [warn]` short-circuit. Confirmed the v4.7.7 deploy-log message text comes from line 78.
- **`scripts/dual-push.sh` exists today** (lines 1-55). It is described in its header as a *"Mirror of `~/Code/ura-dashboard-pwa/scripts/dual-push.sh`"* (line 3). Current state summary:
  - `set -euo pipefail` at line 11.
  - Single-arg branch input at line 16 (default = current branch).
  - `restore_gitea_url` trap registered at line 24 (fires on `EXIT`).
  - `inject_gitea_creds` (lines 26-45) sources `.env.local` via `set -a; source .env.local; set +a`, checks `GITEA_USER` + `GITEA_TOKEN` presence (errors to stderr + `return 1` at line 33), writes a credentialed URL to the gitea remote at line 36, pushes branch + tags (lines 37-38), then immediately rewrites the remote back to the clean URL at line 39. If `.env.local` is absent, falls through to a plain `git push gitea` (lines 42-43) which relies on osxkeychain.
  - **Pushes origin UNCONDITIONALLY at lines 47-49** — this is the double-push observation that D3's `--gitea-only` flag addresses.
- **`.env.local` is gitignored** (`.gitignore:57`) — confirmed without reading the file itself.
- **No existing tests for shell scripts** — `quality/tests/test_deploy*.py` and `quality/tests/test_*script*.py` both return empty globs. D7 introduces the first shell-script test module in the repo.
- **README_v4.7.7.md exists** and was used as a structural template for the README_v4.7.10.md that D6 will create.

These notes anchor the plan in observed repo state, not assumption.
