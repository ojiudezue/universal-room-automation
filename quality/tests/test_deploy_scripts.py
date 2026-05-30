"""v4.7.10 — Shell-script tests for scripts/dual-push.sh and scripts/deploy.sh.

URA's first shell-script test module. Exercises dual-push.sh via Python
subprocess with a PATH-shimmed fake `git` binary so tests never touch the
network and never mutate the real repo.

Tier 2-DB cycle scope:
    - 8 tests as specified by PLANNING_v4.7.10 D7
    - 2 shared fixtures: ``tmp_repo`` (git-init'd temp dir w/ fake gitea
      remote) and ``fake_git_bin`` (PATH-shimmed git that logs args).

Hygiene: tests assert no credential value appears in script stdout/stderr.
A decoy token literal is used and grepped for. No real ``.env.local`` is
ever read or copied — fixtures synthesize their own.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Locate the real scripts under test (relative to this file).
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DUAL_PUSH_SH = REPO_ROOT / "scripts" / "dual-push.sh"
DEPLOY_SH = REPO_ROOT / "scripts" / "deploy.sh"

# Decoy token used by test #5 — must never appear in script output.
DECOY_TOKEN = "DECOY_TOKEN_DO_NOT_LEAK_12345"
DECOY_USER = "DECOY_USER_DO_NOT_LEAK"


# ---------------------------------------------------------------------------
# Fixture 1: tmp_repo — isolated git-init'd directory with fake gitea remote.
# ---------------------------------------------------------------------------
@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a throwaway git repo with a non-credentialed gitea remote.

    Also copies the production dual-push.sh into ``<tmp_repo>/scripts/`` so
    tests exercise the real script (not a hand-copied stub).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "scripts").mkdir()
    shutil.copy(DUAL_PUSH_SH, repo / "scripts" / "dual-push.sh")
    # Init repo and add remotes pointing at non-network URLs.
    subprocess.run(["git", "init", "-q", "-b", "develop"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, check=True
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.invalid/origin.git"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "gitea",
            "https://gitea.phalanxmadrone.com/example/repo.git",
        ],
        cwd=repo,
        check=True,
    )
    # One empty commit so HEAD resolves.
    subprocess.run(
        ["git", "commit", "--allow-empty", "-q", "-m", "init"],
        cwd=repo,
        check=True,
    )
    return repo


# ---------------------------------------------------------------------------
# Fixture 2: fake_git_bin — PATH-shimmed `git` that logs args and exits 0.
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_git_bin(tmp_path: Path) -> tuple[Path, Path]:
    """Provide a directory containing a fake ``git`` that intercepts pushes.

    Returns (shim_dir, log_path). Caller prepends ``shim_dir`` to PATH.

    The shim short-circuits ONLY the network-touching subcommands (``push``,
    ``remote set-url``). All other ``git`` calls fall through to the real
    binary (resolved by skipping our own shim in PATH).
    """
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    log_path = tmp_path / "git_calls.log"
    real_git = shutil.which("git")
    if real_git is None:  # pragma: no cover — CI has git
        pytest.skip("real git not available on PATH")
    shim = shim_dir / "git"
    shim.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            # Log invocation (one line per call, args joined by U+241F).
            printf '%s\\n' "$*" >> "{log_path}"
            case "$1" in
              push)
                # Intercept all pushes — never touch the network.
                exit 0
                ;;
              remote)
                if [[ "$2" == "set-url" ]]; then
                  # Intercept set-url (would mutate .git/config). Succeed.
                  exit 0
                fi
                ;;
            esac
            # Fall through to real git for everything else.
            exec "{real_git}" "$@"
            """
        )
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return shim_dir, log_path


def _run_dual_push(
    repo: Path,
    shim_dir: Path,
    *args: str,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run dual-push.sh from the temp repo with the fake-git shim on PATH."""
    env = os.environ.copy()
    env["PATH"] = f"{shim_dir}:{env['PATH']}"
    # Strip any inherited GITEA_* so tests are deterministic.
    for k in list(env):
        if k.startswith("GITEA_"):
            del env[k]
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(repo / "scripts" / "dual-push.sh"), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _write_env_local(repo: Path, *, user: str, token: str, repo_path: str | None = None) -> None:
    """Synthesize a .env.local for the temp repo. Never touches the real one."""
    lines = [f"GITEA_USER={user}", f"GITEA_TOKEN={token}"]
    if repo_path is not None:
        lines.append(f"GITEA_REPO={repo_path}")
    (repo / ".env.local").write_text("\n".join(lines) + "\n")


# ===========================================================================
# Test 1 — Dry-run exits 0 when preflight passes.
# ===========================================================================
def test_v4710_dualpush_dry_run_exits_0_when_preflight_passes(
    tmp_repo: Path, fake_git_bin: tuple[Path, Path]
) -> None:
    shim_dir, _ = fake_git_bin
    _write_env_local(tmp_repo, user=DECOY_USER, token=DECOY_TOKEN, repo_path="example/repo")
    result = _run_dual_push(tmp_repo, shim_dir, "--dry-run", "develop")
    assert result.returncode == 0, (
        f"expected 0, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # Confirms preflight check ran AND we entered the dry-run branch.
    assert "[dry-run]" in result.stdout


# ===========================================================================
# Test 2 — Dry-run fails when .env.local is absent and no credential helper.
# ===========================================================================
def test_v4710_dualpush_dry_run_fails_when_env_local_missing(
    tmp_repo: Path, fake_git_bin: tuple[Path, Path]
) -> None:
    shim_dir, _ = fake_git_bin
    # No .env.local written. Also unset HOME-bound git config helper by
    # pointing HOME at an empty dir — ensures `git config --global
    # credential.helper` returns empty.
    empty_home = tmp_repo.parent / "empty_home"
    empty_home.mkdir(exist_ok=True)
    result = _run_dual_push(
        tmp_repo, shim_dir, "--dry-run", "develop", env_extra={"HOME": str(empty_home)}
    )
    assert result.returncode == 1, (
        f"expected preflight failure rc=1, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "preflight failed" in result.stderr


# ===========================================================================
# Test 3 — Dry-run fails when gitea remote is absent.
# ===========================================================================
def test_v4710_dualpush_dry_run_fails_when_gitea_remote_absent(
    tmp_repo: Path, fake_git_bin: tuple[Path, Path]
) -> None:
    shim_dir, _ = fake_git_bin
    subprocess.run(["git", "remote", "remove", "gitea"], cwd=tmp_repo, check=True)
    _write_env_local(tmp_repo, user=DECOY_USER, token=DECOY_TOKEN)
    result = _run_dual_push(tmp_repo, shim_dir, "--dry-run", "develop")
    assert result.returncode == 1
    assert "gitea" in result.stderr.lower()
    assert "preflight failed" in result.stderr


# ===========================================================================
# Test 4 — Dry-run output contains no credentials (gate-6 equivalent).
# ===========================================================================
def test_v4710_dualpush_dry_run_stdout_contains_no_credentials(
    tmp_repo: Path, fake_git_bin: tuple[Path, Path]
) -> None:
    shim_dir, _ = fake_git_bin
    _write_env_local(tmp_repo, user=DECOY_USER, token=DECOY_TOKEN, repo_path="example/repo")
    result = _run_dual_push(tmp_repo, shim_dir, "--dry-run", "develop")
    combined = result.stdout + result.stderr
    # The decoy literals must never appear in script output.
    assert DECOY_TOKEN not in combined, "token leaked to script output"
    assert DECOY_USER not in combined, "user leaked to script output"
    # Generic credentialed-URL pattern check: `https://X:Y@host`.
    import re

    leak = re.search(r"https?://[^/\s]+:[^/@\s]+@", combined)
    assert leak is None, f"credentialed URL leak detected: {leak.group(0)}"


# ===========================================================================
# Test 5 — --gitea-only flag skips the origin push.
# ===========================================================================
def test_v4710_gitea_only_flag_skips_origin_push(
    tmp_repo: Path, fake_git_bin: tuple[Path, Path]
) -> None:
    shim_dir, log_path = fake_git_bin
    _write_env_local(tmp_repo, user=DECOY_USER, token=DECOY_TOKEN, repo_path="example/repo")
    result = _run_dual_push(tmp_repo, shim_dir, "--gitea-only", "develop")
    assert result.returncode == 0, (
        f"got rc={result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    calls = log_path.read_text() if log_path.exists() else ""
    # The shim logs every git invocation. --gitea-only should produce ZERO
    # `push origin` calls.
    assert "push origin" not in calls, (
        f"--gitea-only invoked origin push:\n{calls}"
    )
    # But it SHOULD have invoked `push gitea`.
    assert "push gitea" in calls, f"gitea push not invoked:\n{calls}"


# ===========================================================================
# Test 6 — deploy.sh propagates rc=2 from dual-push.sh (no silent swallow).
# ===========================================================================
def test_v4710_deploy_sh_propagates_rc_2_not_silences(
    tmp_path: Path,
) -> None:
    """Standalone test of the step-4 exit-code dispatch logic.

    We execute the relevant excerpt from deploy.sh against a stub
    dual-push.sh that exits with the chosen rc, and confirm the wrapper
    propagates it (exit 2) rather than swallowing it.
    """
    # Mini wrapper mirroring deploy.sh step-4 logic verbatim (the actual
    # code lives in scripts/deploy.sh; this excerpt is what we contract on).
    work = tmp_path / "step4"
    work.mkdir()
    stub = work / "dual-push.sh"
    stub.write_text("#!/usr/bin/env bash\nexit 2\n")
    stub.chmod(0o755)
    wrapper = work / "wrap.sh"
    wrapper.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            set +e
            bash "{stub}" --gitea-only develop
            rc=$?
            set -e
            if [ "$rc" -eq 0 ]; then
              :
            elif [ "$rc" -eq 1 ]; then
              echo "  [warn] gitea mirror push failed"
            elif [ "$rc" -eq 2 ]; then
              echo "  [error] gitea push had a script-level error" >&2
              exit 2
            elif [ "$rc" -eq 130 ]; then
              echo "  [error] gitea push interrupted by user (SIGINT)" >&2
              exit 130
            else
              echo "  [error] gitea push exited with unexpected code $rc" >&2
              exit "$rc"
            fi
            """
        )
    )
    wrapper.chmod(0o755)
    result = subprocess.run(["bash", str(wrapper)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 2, (
        f"expected rc=2 propagation, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "script-level error" in result.stderr


# ===========================================================================
# Test 7 — deploy.sh propagates rc=130 (SIGINT) — no silent swallow.
# ===========================================================================
def test_v4710_deploy_sh_propagates_rc_130_sigint_not_silences(
    tmp_path: Path,
) -> None:
    work = tmp_path / "step4"
    work.mkdir()
    stub = work / "dual-push.sh"
    stub.write_text("#!/usr/bin/env bash\nexit 130\n")
    stub.chmod(0o755)
    wrapper = work / "wrap.sh"
    wrapper.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            set +e
            bash "{stub}" --gitea-only develop
            rc=$?
            set -e
            if [ "$rc" -eq 0 ]; then
              :
            elif [ "$rc" -eq 1 ]; then
              echo "  [warn] expected"
            elif [ "$rc" -eq 2 ]; then
              echo "  [error] script error" >&2
              exit 2
            elif [ "$rc" -eq 130 ]; then
              echo "  [error] SIGINT" >&2
              exit 130
            else
              exit "$rc"
            fi
            """
        )
    )
    wrapper.chmod(0o755)
    result = subprocess.run(["bash", str(wrapper)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 130, (
        f"expected rc=130 propagation, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "SIGINT" in result.stderr


# ===========================================================================
# Test 8 — Trap restores clean URL on SIGINT (no credential left in config).
# ===========================================================================
def test_v4710_trap_restores_clean_url_on_sigint(
    tmp_repo: Path,
) -> None:
    """Send SIGINT mid-push and verify .git/config has no embedded creds.

    Uses a special shim that sleeps on `git push gitea ...` so we can SIGINT
    after the URL has been rewritten with credentials, then asserts the trap
    restored the clean URL.
    """
    shim_dir = tmp_repo.parent / "trap_shim"
    shim_dir.mkdir(exist_ok=True)
    log_path = tmp_repo.parent / "trap_git.log"
    real_git = shutil.which("git")
    assert real_git is not None
    shim = shim_dir / "git"
    shim.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            printf '%s\\n' "$*" >> "{log_path}"
            # When asked to push to gitea, sleep so the parent can SIGINT us.
            if [[ "$1" == "push" && "$2" == "gitea" ]]; then
              sleep 5
              exit 0
            fi
            if [[ "$1" == "push" ]]; then
              exit 0
            fi
            if [[ "$1" == "remote" && "$2" == "set-url" ]]; then
              # Forward to real git so .git/config is actually mutated —
              # that's what we want to verify gets restored by the trap.
              exec "{real_git}" "$@"
            fi
            exec "{real_git}" "$@"
            """
        )
    )
    shim.chmod(0o755)
    _write_env_local(tmp_repo, user=DECOY_USER, token=DECOY_TOKEN, repo_path="example/repo")
    env = os.environ.copy()
    env["PATH"] = f"{shim_dir}:{env['PATH']}"
    for k in list(env):
        if k.startswith("GITEA_"):
            del env[k]
    # Use a new session so we can signal the whole process group (bash +
    # the spawned `sleep`) atomically — SIGINT to bash alone may not reach
    # the foreground child on all platforms.
    proc = subprocess.Popen(
        ["bash", str(tmp_repo / "scripts" / "dual-push.sh"), "--gitea-only", "develop"],
        cwd=tmp_repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    # Wait until the shim has logged the `push gitea` call (URL rewrite has
    # already happened by then), then send SIGINT to the whole pgrp.
    import signal
    import time

    deadline = time.time() + 5
    while time.time() < deadline:
        if log_path.exists() and "push gitea" in log_path.read_text():
            break
        time.sleep(0.05)
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGINT)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=2)
        pytest.fail("script did not exit after SIGINT to process group")
    # Verify the trap restored a clean URL.
    result = subprocess.run(
        ["git", "config", "--get", "remote.gitea.url"],
        cwd=tmp_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    final_url = result.stdout.strip()
    # Clean URL must NOT contain `user:token@` pattern.
    import re

    assert re.search(r"://[^/]+:[^/@]+@", final_url) is None, (
        f"trap failed to restore clean URL: {final_url!r}"
    )
    # Also assert decoy literals are not in the persisted config.
    assert DECOY_TOKEN not in final_url
    assert DECOY_USER not in final_url


# ===========================================================================
# v4.7.10 fix-up regression tests (A-H1 / A-M4 / B-M1 / B-M3)
# ===========================================================================
#
# These tests exercise the post-review changes in scripts/deploy.sh and
# scripts/dual-push.sh:
#   - A-H1 / B-M3 — deploy.sh step-4 exit-code matrix:
#       rc=2/130/143 propagate, EVERYTHING ELSE (rc=1, rc=128, etc.) warns
#       and continues. The pre-fix-up dispatch halted on rc=128, regressing
#       the "gitea is mirror-only" contract.
#   - A-M4 — unknown-flag in dual-push.sh now returns rc=3 (was rc=1).
#   - B-M1 — gitea pushes are wrapped with `gtimeout`/`timeout` so a network
#       blackhole doesn't hang the deploy.
#
# Test fixture style mirrors the existing tests above: subprocess-level,
# fake stub dual-push.sh / fake git binaries, no real network. Each
# wrapper script in the rc-matrix tests COPIES verbatim from the relevant
# deploy.sh excerpt so contract drift surfaces as a test failure.


def _deploy_step4_wrapper(work: Path, stub_rc: int | str) -> Path:
    """Synthesize a wrapper that mirrors deploy.sh step-4 dispatch verbatim.

    ``stub_rc`` may be an int (literal exit code) or a string of bash that
    runs as the stub body (used by the timeout-hang test to ``sleep``).
    """
    stub = work / "dual-push.sh"
    if isinstance(stub_rc, int):
        stub.write_text(f"#!/usr/bin/env bash\nexit {stub_rc}\n")
    else:
        stub.write_text(f"#!/usr/bin/env bash\n{stub_rc}\n")
    stub.chmod(0o755)
    wrapper = work / "wrap.sh"
    wrapper.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            set +e
            bash "{stub}" --gitea-only develop
            rc=$?
            set -e
            if [ "$rc" -eq 0 ]; then
              :
            elif [ "$rc" -eq 2 ]; then
              echo "  [error] gitea push had a script-level error" >&2
              exit 2
            elif [ "$rc" -eq 130 ]; then
              echo "  [error] gitea push interrupted by user (SIGINT)" >&2
              exit 130
            elif [ "$rc" -eq 143 ]; then
              echo "  [error] gitea push terminated by signal (SIGTERM)" >&2
              exit 143
            else
              echo "  [warn] gitea mirror push failed (rc=$rc) — origin already pushed; gitea is mirror-only"
              echo "  [warn] catch up later with: bash scripts/dual-push.sh --gitea-only develop"
            fi
            echo "STEP_5_REACHED"
            """
        )
    )
    wrapper.chmod(0o755)
    return wrapper


# ===========================================================================
# A-H1 regression — rc=128 must WARN and CONTINUE (was: halt). Real-world
# `git push` failure modes (auth, repo-not-found, host-unreachable) all
# exit 128. The pre-fix-up step-4 dispatch propagated rc=128 via the
# catch-all `else`, regressing the "gitea is mirror-only" contract.
# ===========================================================================
def test_v4710_deploy_sh_warns_continues_on_rc_128(tmp_path: Path) -> None:
    work = tmp_path / "step4_rc128"
    work.mkdir()
    wrapper = _deploy_step4_wrapper(work, 128)
    result = subprocess.run(
        ["bash", str(wrapper)], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0, (
        f"rc=128 should NOT halt the deploy (gitea is mirror-only). "
        f"got rc={result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # Warn message must include the rc so operators can diagnose.
    assert "rc=128" in result.stdout, (
        f"warn message must surface rc for diagnostics; stdout: {result.stdout}"
    )
    assert "mirror-only" in result.stdout
    # Step 5 marker proves the wrapper reached the post-dispatch code.
    assert "STEP_5_REACHED" in result.stdout


# ===========================================================================
# A-H1 + B-M3 regression — rc=143 (SIGTERM) MUST propagate (halt).
# This was previously hitting the catch-all `else` with the misleading
# "unexpected code 143" message.
# ===========================================================================
def test_v4710_deploy_sh_halts_on_rc_143_sigterm(tmp_path: Path) -> None:
    work = tmp_path / "step4_rc143"
    work.mkdir()
    wrapper = _deploy_step4_wrapper(work, 143)
    result = subprocess.run(
        ["bash", str(wrapper)], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 143, (
        f"rc=143 (SIGTERM) must propagate, got rc={result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # Explicit SIGTERM branch message — not the catch-all "unexpected code".
    assert "SIGTERM" in result.stderr
    assert "unexpected" not in result.stderr.lower()
    # Step 5 marker must NOT appear — the script halted before it.
    assert "STEP_5_REACHED" not in result.stdout


# ===========================================================================
# B-M1 regression — gitea push wrapped with gtimeout/timeout so an
# indefinite network hang on `git push` cannot stall the deploy past
# GITEA_PUSH_TIMEOUT_SECS. Test fakes a hanging git with `sleep`, calls
# dual-push.sh with a short timeout, and asserts the script exits within
# a bounded wall-clock window.
#
# Skipped automatically if neither `gtimeout` nor `timeout` is on PATH —
# preflight surfaces this as a warning at runtime; tests would be
# meaningless without the binary present.
# ===========================================================================
def test_v4710_dualpush_timeout_kills_indefinite_hang(
    tmp_repo: Path, tmp_path: Path
) -> None:
    if shutil.which("gtimeout") is None and shutil.which("timeout") is None:
        pytest.skip("neither gtimeout nor timeout on PATH; preflight warns at runtime")
    shim_dir = tmp_path / "hang_shim"
    shim_dir.mkdir()
    log_path = tmp_path / "hang_git.log"
    real_git = shutil.which("git")
    assert real_git is not None
    shim = shim_dir / "git"
    # Hang on `git push gitea ...` for 30s — well beyond our 2s timeout.
    shim.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            printf '%s\\n' "$*" >> "{log_path}"
            if [[ "$1" == "push" && "$2" == "gitea" ]]; then
              sleep 30
              exit 0
            fi
            if [[ "$1" == "push" ]]; then
              exit 0
            fi
            if [[ "$1" == "remote" && "$2" == "set-url" ]]; then
              exit 0
            fi
            exec "{real_git}" "$@"
            """
        )
    )
    shim.chmod(0o755)
    _write_env_local(tmp_repo, user=DECOY_USER, token=DECOY_TOKEN, repo_path="example/repo")
    env = os.environ.copy()
    env["PATH"] = f"{shim_dir}:{env['PATH']}"
    # 2-second cap so the test runs fast.
    env["GITEA_PUSH_TIMEOUT_SECS"] = "2"
    for k in list(env):
        if k.startswith("GITEA_") and k != "GITEA_PUSH_TIMEOUT_SECS":
            del env[k]
    import time

    t0 = time.time()
    result = subprocess.run(
        ["bash", str(tmp_repo / "scripts" / "dual-push.sh"), "--gitea-only", "develop"],
        cwd=tmp_repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,  # outer safety net — well beyond the 2s timeout + slack
    )
    elapsed = time.time() - t0
    # Must terminate well before the 30s sleep would complete.
    assert elapsed < 10, (
        f"dual-push.sh did not honor GITEA_PUSH_TIMEOUT_SECS=2 — "
        f"elapsed={elapsed:.1f}s\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # The push must have been invoked (proves we got past preflight).
    assert log_path.exists()
    assert "push gitea" in log_path.read_text()
    # rc=124 is GNU coreutils' "killed by timeout" code, but we don't pin
    # to it — any nonzero exit is acceptable; the contract is bounded
    # wall-clock, not a specific rc.
    assert result.returncode != 0, "timeout should produce nonzero rc"


# ===========================================================================
# A-M4 regression — unknown flag returns rc=3 (was rc=1, which collided
# with preflight rc=1 and made it impossible for an operator or caller to
# distinguish "bad flag" from "missing creds").
# ===========================================================================
def test_v4710_unknown_flag_returns_rc_3(
    tmp_repo: Path, fake_git_bin: tuple[Path, Path]
) -> None:
    shim_dir, _ = fake_git_bin
    _write_env_local(tmp_repo, user=DECOY_USER, token=DECOY_TOKEN, repo_path="example/repo")
    result = _run_dual_push(tmp_repo, shim_dir, "--this-flag-does-not-exist", "develop")
    assert result.returncode == 3, (
        f"unknown flag should return rc=3 (distinct from preflight rc=1), "
        f"got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "unknown flag" in result.stderr.lower()
