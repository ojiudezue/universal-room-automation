# URA v4.7.10 — `deploy.sh` Gitea Retrofit

**Release date:** 2026-05-29
**Tier:** Tier 2-DB (three parallel staff-engineer reviews — different framings)
**Scope:** `scripts/deploy.sh` + `scripts/dual-push.sh` + `quality/tests/test_deploy_scripts.py` (new). Zero production code touched. First Phase A cycle to ship.

**Trigger:**
- v4.7.7 deploy logs printed `[warn] gitea push failed — origin already pushed; gitea is mirror-only`. Because the existing `|| echo` short-circuit at `scripts/deploy.sh:77-78` swallowed ALL nonzero exit codes (including bash syntax errors and SIGINT), the actual stderr from `dual-push.sh` was lost. The retrofit replaces the swallow-all with a narrow exit-code dispatch so future failures are observable AND actionable.
- `dual-push.sh` also re-pushed origin from inside `deploy.sh` step 4 — wasteful and a chance to mask real gitea-side failures behind origin-already-up-to-date noise. The new `--gitea-only` flag makes `deploy.sh` skip the redundant origin push.
- No pre-flight on credential state — a missing `.env.local` key fell through to a `git push gitea` that would prompt or hang. The new `_dualpush_preflight()` fails fast with actionable hints (and never echoes the user/token values).

---

## Headline Changes

- **D1** — Root-cause investigation of the v4.7.7 `[warn]`. Captured in the commit body (redacted). All three required keys (`GITEA_USER`, `GITEA_TOKEN`, `GITEA_REPO`) are present in `.env.local`; gitea remote URL is clean; network reachable. Hypothesis (a) `.env.local` missing keys: **REJECTED**. Most likely root cause is hypothesis (d) variant — `GITEA_REPO` path or gitea-side branch state mismatch — surfaced by D2's preflight + D4's narrow rc dispatch regardless of the exact transient.
- **D2** — `_dualpush_preflight()` in `dual-push.sh`. Validates (i) gitea remote exists, (ii) gitea remote URL host matches `gitea.phalanxmadrone.com`, (iii) either `.env.local` exists with `GITEA_USER` + `GITEA_TOKEN` keys OR `git config --global credential.helper` is non-empty. Errors to stderr with `[dual-push] preflight failed:` prefix and a one-line remediation hint. Never echoes key VALUES.
- **D3** — `--gitea-only` flag on `dual-push.sh`. Skips the unconditional origin push at lines 47-49 when called from `deploy.sh` (which already pushed origin at step 4). Default behavior unchanged when invoked manually without the flag.
- **D4** — `deploy.sh` step 4 retrofit. Replaces `bash dual-push.sh develop || echo [warn]...` with a `set +e; rc=$?; set -e` window and narrow exit-code dispatch: rc=0 success, rc=1 warn+continue, rc=2 halt with error, rc=130 (SIGINT) halt with error, anything else halt with error. The `set +e` / `set -e` window does NOT leak into steps 5-7 (verified by test #6 + #7).
- **D5** — `--dry-run` flag on `dual-push.sh`. Runs preflight + prints would-be commands; no real `git push`, no `.git/config` mutation, no credentialed URL ever written to stdout (the URL-rewrite line at `dual-push.sh:36` is now gated behind `! $DRY_RUN`).
- **D6** — This README.
- **D7** — 8 new tests in `quality/tests/test_deploy_scripts.py` (URA's first shell-script test module) covering: dry-run preflight (passes / missing env / missing remote), credential-leak grep, `--gitea-only` skips origin, `deploy.sh` rc=2 and rc=130 propagation, trap-restores-clean-URL on SIGINT mid-push.

---

## Per-Deliverable Detail

### D1 — Root-Cause Investigation of v4.7.7 `[warn] gitea push failed`

Captured in commit body. Investigation outputs (all redacted of token + user values per safety contract):

- `git remote -v` → `gitea` and `origin` both present.
- `.env.local` → exists; `grep -c '^GITEA_USER='`, `grep -c '^GITEA_TOKEN='`, `grep -c '^GITEA_REPO='` all returned `1` (all three required keys present).
- `git config --get remote.gitea.url` → URL contains NO embedded `user:token@` pattern (trap from previous runs successfully restored clean URL).
- `curl -sI https://gitea.phalanxmadrone.com/` → `HTTP/2 200` (network reachable).

**Conclusion:** Hypothesis (a) `.env.local` missing keys is REJECTED. The most likely root cause was a transient hypothesis-(d) variant (GITEA_REPO path mismatch or gitea-side branch divergence). The retrofit closes the observability gap so the next failure surfaces actionable stderr instead of a swallowed exit code, and the preflight now provides a 1-second fail-fast with remediation hints instead of falling through to a hang.

### D2 — `_dualpush_preflight()`

New function in `dual-push.sh` invoked BEFORE any push and BEFORE any URL rewrite. Three checks:

1. `git remote get-url gitea` returns 0.
2. The gitea remote URL contains the expected host string `gitea.phalanxmadrone.com`.
3. Credentials available: either `.env.local` defines both `GITEA_USER=` and `GITEA_TOKEN=` (validated via `grep -c` so values are never sourced before they are known to be present), OR a non-empty `git config --global credential.helper` is configured.

On miss, prints `[dual-push] preflight failed: <reason>` and a `[dual-push] hint: <remediation>` line to stderr, then returns 1. The `dual-push.sh` main flow `exit 1`s when preflight returns nonzero.

### D3 — `--gitea-only` Flag

Flag parsing is tolerant of argument order: `dual-push.sh --gitea-only develop`, `dual-push.sh develop --gitea-only`, and `dual-push.sh --gitea-only --dry-run develop` all parse identically. Unknown flags exit 1 with a clear error (no silent swallow).

When `--gitea-only` is set, the unconditional origin push at the top of the script is skipped. The gitea push proceeds as normal. `deploy.sh` step 4 has been switched to invoke `--gitea-only` since it has already pushed origin at line 70 of `deploy.sh`.

### D4 — `deploy.sh` Step 4 Retrofit

New exit-code dispatch table (verbatim from `deploy.sh:73-101`):

| Exit code from `dual-push.sh` | `deploy.sh` behavior |
|---|---|
| `0` | success, proceed to step 5 |
| `1` | `[warn]` (preflight or auth failure) + remediation hint, proceed to step 5 |
| `2` | `[error]` script-level error, halt with `exit 2` |
| `130` | `[error]` SIGINT, halt with `exit 130` |
| any other | `[error]` unexpected, halt with `exit $rc` |

The `set +e; rc=$?; set -e` window is bounded to the single `bash dual-push.sh` invocation — `set -e` is restored before any exit-code branch runs, so steps 5-7 retain strict error-on-failure semantics.

### D5 — `--dry-run` Mode

Runs preflight (the whole point — preflight is the value of dry-run) and then prints what `git remote set-url`, `git push gitea <branch>`, and `git push gitea --tags` WOULD execute, without actually invoking them. The URL-rewrite-with-creds line at `dual-push.sh:36` is guarded behind `! $DRY_RUN` so dry-run never mutates `.git/config` and never echoes the credentialed URL.

A sample successful dry-run on a clean local repo:

```
→ Pushing to Gitea gitea/develop
  [dry-run] git remote set-url gitea <credentialed-url-redacted>
  [dry-run] git push gitea develop
  [dry-run] git push gitea --tags
  [dry-run] git remote set-url gitea https://gitea.phalanxmadrone.com/<repo>.git
✓ Dry-run complete (no remotes modified).
```

### D7 — Tests (8 total + 2 fixtures)

`quality/tests/test_deploy_scripts.py`. Fixtures:

- `tmp_repo`: ephemeral git-init'd directory with `origin` and `gitea` remotes pointing at non-network URLs; production `dual-push.sh` copied in.
- `fake_git_bin`: PATH-shim `git` binary that intercepts `push` and `remote set-url` (logs to file, exits 0) and forwards everything else to the real `git`.

Tests:

1. `test_v4710_dualpush_dry_run_exits_0_when_preflight_passes`
2. `test_v4710_dualpush_dry_run_fails_when_env_local_missing` (preflight rc=1)
3. `test_v4710_dualpush_dry_run_fails_when_gitea_remote_absent` (preflight rc=1)
4. `test_v4710_dualpush_dry_run_stdout_contains_no_credentials` — generic secret-leak grep for `https?://[^/]+:[^/@]+@` pattern + decoy literal grep
5. `test_v4710_gitea_only_flag_skips_origin_push` — asserts shim's log shows zero `push origin` calls
6. `test_v4710_deploy_sh_propagates_rc_2_not_silences`
7. `test_v4710_deploy_sh_propagates_rc_130_sigint_not_silences`
8. `test_v4710_trap_restores_clean_url_on_sigint` — sends SIGINT to the process group while a shim-`git push gitea` sleeps; asserts post-trap `.git/config` does NOT contain `://X:Y@` pattern and does NOT contain the decoy literals

All 8 pass in <1 second on macOS dev machine.

---

## Operator Notes

### `.env.local` location and required keys

Path: `<repo-root>/.env.local` (gitignored at `.gitignore:57`).

Required keys (no example values — provide your own):

```
GITEA_USER=
GITEA_TOKEN=
GITEA_REPO=    # optional; defaults to Okosisi/universal-room-automation
```

### Manual gitea catch-up if the mirror falls behind

If `deploy.sh` prints `[warn] gitea mirror push failed`:

```bash
# 1. Fix the cause (rotate token / fix .env.local / verify gitea remote URL):
bash scripts/dual-push.sh --dry-run develop  # validate preflight, no push

# 2. Catch up gitea once preflight is clean:
bash scripts/dual-push.sh --gitea-only develop
git push gitea <tag>   # if a release tag was created during the failed deploy
```

### Verifying gitea is current

```bash
gh_sha=$(git ls-remote origin develop | awk '{print $1}')
gt_sha=$(git ls-remote gitea  develop | awk '{print $1}')
[[ "$gh_sha" == "$gt_sha" ]] && echo "in sync" || echo "MISMATCH — gitea behind"
```

### Exit-code semantics (lock-in)

`dual-push.sh` exit codes:

- `0` — success
- `1` — preflight failure OR `git push` rejected (expected; mirror-side miss; `deploy.sh` continues)
- `2` — bash script-level error (`set -e` tripped; `deploy.sh` halts)
- `130` — SIGINT (`deploy.sh` halts)
- `143` — SIGTERM (`deploy.sh` halts)

`deploy.sh` step 4 propagates `2`, `130`, and any other unexpected nonzero code. Only `0` and `1` allow the deploy to proceed to step 5.

### Pre-deploy Zero-Bugs Gate 6 (cycle-specific)

The dual-push dry-run smoke check added to the pre-deploy gate sequence:

```bash
bash scripts/dual-push.sh --dry-run develop 2>&1 \
  | grep -qE ':[^@]*@' \
  && echo TOKEN-LEAK-DETECTED && exit 1
echo "gate 6 clean"
```

---

## Live Validation Expectations

After this release ships:

1. `gh release view v4.7.10` returns the GitHub release with this README body.
2. `git ls-remote gitea refs/tags/v4.7.10` returns the SHA (gitea push succeeded).
3. Both remotes converged on the same `develop` SHA (see verification snippet above).
4. `git config --get remote.gitea.url` returns a URL with NO `://X:Y@` pattern (trap fired correctly).
5. `bash scripts/dual-push.sh --gitea-only --dry-run develop` exits 0; `.git/config` unchanged before/after.
6. No HA restart required — this cycle does NOT touch `custom_components/`.

---

## Known Limitations / Carried Forward

- `kill -9` (SIGKILL) is not trappable. If `dual-push.sh` is hard-killed mid-push between the URL-rewrite and the URL-restore lines, `.git/config` may briefly contain a credentialed URL. Operator remediation: `git remote set-url gitea https://gitea.phalanxmadrone.com/<repo>.git`. Documented residual risk; not fixable in shell.
- No Slack/email notification on gitea failure. The `[warn]` stdout line is sufficient for a single-operator project (per planning §12).
- Gitea is mirror-only. Releases (`gh release create`) are only created on GitHub origin. Tags + branches mirror to gitea; no gitea-side Releases API integration.

---

## Review Trail

Tier 2-DB — three parallel staff-engineer reviewers with disjoint framings (per CLAUDE.md Tier 2-DB protocol):

- **Reviewer A** — Correctness + state-machine invariants (push-success/fail combinatorics, exit-code dispatch, flag parsing).
- **Reviewer B** — Async + lifecycle + restart resilience (trap firing under `set -e` / EXIT / INT / TERM; `set +e` window isolation).
- **Reviewer C** — Secret hygiene + parallel-merge risk (no `set -x`; no `echo $TOKEN`; pre-review-tag diff confirms files-touched-list is exactly the 4-file scope).

Findings burn-down captured in `docs/reviews/code-review/v4.7.10_*.md` (filed at cycle end).

---

## Files Touched

- `scripts/deploy.sh`
- `scripts/dual-push.sh`
- `quality/tests/test_deploy_scripts.py` (new)
- `docs/readmes/README_v4.7.10.md` (new)

No production code in `custom_components/universal_room_automation/` touched. Version bump (`const.py`, `manifest.json`) happens at deploy time via `stamp_version.py`, NOT pre-stamped in this branch.
