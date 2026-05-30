#!/usr/bin/env bash
# Push current branch (+ tags) to BOTH GitHub origin and homelab Gitea.
# Mirror of ~/Code/ura-dashboard-pwa/scripts/dual-push.sh.
#
# Token-leak safety: `trap` restores clean URL on ANY exit. `set -euo pipefail`
# would otherwise leave the token embedded in `.git/config` after a network
# blip. (PWA D8 review B.CRITICAL-1.)
#
# Credentials come from ./.env.local (gitignored). First call uses the env;
# osxkeychain caches for subsequent calls.
#
# v4.7.10 (Phase A, Tier 2-DB) additions:
#   --gitea-only   Skip the origin push (deploy.sh already pushed origin).
#   --dry-run      Run preflight + print would-be commands; no real push.
#   _dualpush_preflight() fail-fast checks BEFORE any push and BEFORE any
#     URL rewrite that could embed a token in .git/config.
#
# Exit-code contract (v4.7.10 lock-in, fix-up clarification):
#   0   success
#   1   preflight failure OR push rejected (expected, gitea-side mirror miss)
#   2   bash script-level error (set -e tripped)
#   3   CLI usage error: unknown flag OR duplicate flag (A-M4 / A-L3 fix-up)
#   128 propagated from `git push` (auth/network/repo-path — caller WARNs)
#   130 SIGINT  (caller halts deploy)
#   143 SIGTERM (caller halts deploy)
set -euo pipefail

# Push timeout (seconds). Set to 0 to disable. macOS users get `gtimeout`
# from coreutils (`brew install coreutils`); Linux users get `timeout` from
# coreutils-by-default. Preflight warns if neither is on PATH (B-M1 fix-up).
GITEA_PUSH_TIMEOUT_SECS="${GITEA_PUSH_TIMEOUT_SECS:-60}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# ---- Flag parsing (tolerant of order) --------------------------------------
# Fix-up A-M4: unknown flag now returns rc=3 (was rc=1, which collided with
# preflight rc=1). Fix-up A-L3: duplicate flag also returns rc=3 (was silent
# accept, which masked operator typos).
GITEA_ONLY=false
DRY_RUN=false
_seen_gitea_only=false
_seen_dry_run=false
POSITIONAL=()
for arg in "$@"; do
  case "$arg" in
    --gitea-only)
      if $_seen_gitea_only; then
        echo "[dual-push] duplicate flag: $arg" >&2
        exit 3
      fi
      GITEA_ONLY=true
      _seen_gitea_only=true
      ;;
    --dry-run)
      if $_seen_dry_run; then
        echo "[dual-push] duplicate flag: $arg" >&2
        exit 3
      fi
      DRY_RUN=true
      _seen_dry_run=true
      ;;
    --*)
      echo "[dual-push] unknown flag: $arg" >&2
      exit 3
      ;;
    *) POSITIONAL+=("$arg") ;;
  esac
done

BRANCH="${POSITIONAL[0]:-$(git rev-parse --abbrev-ref HEAD)}"
GITEA_CLEAN_URL=""
EXPECTED_GITEA_HOST="gitea.phalanxmadrone.com"

restore_gitea_url() {
  if [[ -n "$GITEA_CLEAN_URL" ]]; then
    git remote set-url gitea "$GITEA_CLEAN_URL" 2>/dev/null || true
  fi
}
# Trap fires on both INT and EXIT (and TERM). On SIGINT the handler runs
# twice (once for INT, once for the implicit EXIT). restore_gitea_url is
# idempotent — repeated `set-url` to the same clean URL is a no-op. A-L1.
trap restore_gitea_url EXIT INT TERM

# ---- Timeout wrapper resolver ----------------------------------------------
# B-M1 fix-up: a network blackhole on `git push gitea ...` can hang forever,
# during which the EXIT/INT trap cannot fire (the script is blocked on a
# child syscall). Wrap pushes with `gtimeout` (macOS, coreutils) or `timeout`
# (Linux). If neither is on PATH, log once at preflight time and continue
# without a timeout — operator can ^C.
_TIMEOUT_BIN=""
_resolve_timeout_bin() {
  if command -v gtimeout >/dev/null 2>&1; then
    _TIMEOUT_BIN="gtimeout"
  elif command -v timeout >/dev/null 2>&1; then
    _TIMEOUT_BIN="timeout"
  else
    _TIMEOUT_BIN=""
  fi
}
# Run `git push ...` (or any command) with the resolved timeout wrapper, if
# available and GITEA_PUSH_TIMEOUT_SECS > 0. Exit code 124 from coreutils
# `timeout` signals "killed by timeout" — we surface that through unchanged
# so deploy.sh's catch-all branch warns + continues (gitea is mirror-only).
_push_with_timeout() {
  if [[ -n "$_TIMEOUT_BIN" && "$GITEA_PUSH_TIMEOUT_SECS" -gt 0 ]]; then
    "$_TIMEOUT_BIN" "$GITEA_PUSH_TIMEOUT_SECS" "$@"
  else
    "$@"
  fi
}

# ---- D2: fail-fast preflight ------------------------------------------------
# Validate the environment BEFORE any push and BEFORE any URL rewrite that
# could embed a credential in .git/config. Never echoes GITEA_USER or
# GITEA_TOKEN values — only presence/absence.
_dualpush_preflight() {
  # (i) gitea remote exists
  if ! git remote get-url gitea >/dev/null 2>&1; then
    echo "[dual-push] preflight failed: 'gitea' remote not configured" >&2
    echo "[dual-push] hint: git remote add gitea https://${EXPECTED_GITEA_HOST}/<owner>/<repo>.git" >&2
    return 1
  fi

  # (ii) gitea remote URL points at expected host
  local current_url
  current_url="$(git remote get-url gitea 2>/dev/null || true)"
  if [[ "$current_url" != *"${EXPECTED_GITEA_HOST}"* ]]; then
    echo "[dual-push] preflight failed: 'gitea' remote host does not match ${EXPECTED_GITEA_HOST}" >&2
    return 1
  fi

  # (iv) timeout binary resolution (warning only — never fatal).
  _resolve_timeout_bin
  if [[ -z "$_TIMEOUT_BIN" && "$GITEA_PUSH_TIMEOUT_SECS" -gt 0 ]]; then
    echo "[dual-push] warn: neither 'gtimeout' nor 'timeout' on PATH — gitea push will run without a timeout wrapper. hint: brew install coreutils" >&2
  fi

  # (iii) credentials available — either .env.local with required keys OR
  #        a configured credential helper (osxkeychain fallback acceptable).
  if [[ -f .env.local ]]; then
    # Source in a subshell first to validate keys WITHOUT leaking values to
    # this shell's exported env until we know they're present.
    local user_count token_count
    user_count="$(grep -c '^GITEA_USER=' .env.local || true)"
    token_count="$(grep -c '^GITEA_TOKEN=' .env.local || true)"
    if [[ "$user_count" -lt 1 || "$token_count" -lt 1 ]]; then
      echo "[dual-push] preflight failed: .env.local missing GITEA_USER or GITEA_TOKEN" >&2
      echo "[dual-push] hint: ensure .env.local defines GITEA_USER, GITEA_TOKEN, and (optional) GITEA_REPO" >&2
      return 1
    fi
  else
    # No .env.local — must have a credential helper configured.
    local helper
    helper="$(git config --global credential.helper 2>/dev/null || true)"
    if [[ -z "$helper" ]]; then
      echo "[dual-push] preflight failed: no .env.local and no git credential.helper configured" >&2
      echo "[dual-push] hint: create .env.local with GITEA_USER and GITEA_TOKEN, OR run: git config --global credential.helper osxkeychain" >&2
      return 1
    fi
  fi

  return 0
}

# ---- Credential injection (only after preflight passes) --------------------
inject_gitea_creds() {
  if [[ -f .env.local ]]; then
    # shellcheck disable=SC1091
    set -a; source .env.local; set +a
    if [[ -z "${GITEA_USER:-}" || -z "${GITEA_TOKEN:-}" ]]; then
      echo "[dual-push] .env.local missing GITEA_USER or GITEA_TOKEN" >&2
      return 1
    fi
    local repo="${GITEA_REPO:-Okosisi/universal-room-automation}"
    GITEA_CLEAN_URL="https://${EXPECTED_GITEA_HOST}/${repo}.git"
    if $DRY_RUN; then
      # Print the would-be commands but NEVER echo the credentialed URL.
      echo "  [dry-run] git remote set-url gitea <credentialed-url-redacted>"
      echo "  [dry-run] git push gitea $BRANCH"
      echo "  [dry-run] git push gitea --tags"
      echo "  [dry-run] git remote set-url gitea $GITEA_CLEAN_URL"
      return 0
    fi
    git remote set-url gitea "https://${GITEA_USER}:${GITEA_TOKEN}@${EXPECTED_GITEA_HOST}/${repo}.git"
    _push_with_timeout git push gitea "$BRANCH"
    _push_with_timeout git push gitea --tags
    git remote set-url gitea "$GITEA_CLEAN_URL"
  else
    echo "[dual-push] no .env.local; relying on osxkeychain" >&2
    if $DRY_RUN; then
      echo "  [dry-run] git push gitea $BRANCH"
      echo "  [dry-run] git push gitea --tags"
      return 0
    fi
    _push_with_timeout git push gitea "$BRANCH"
    _push_with_timeout git push gitea --tags
  fi
}

# ---- Main -------------------------------------------------------------------
if ! _dualpush_preflight; then
  exit 1
fi

if ! $GITEA_ONLY; then
  echo "→ Pushing to GitHub origin/$BRANCH"
  if $DRY_RUN; then
    echo "  [dry-run] git push origin $BRANCH"
    echo "  [dry-run] git push origin --tags"
  else
    git push origin "$BRANCH"
    git push origin --tags
  fi
fi

echo "→ Pushing to Gitea gitea/$BRANCH"
inject_gitea_creds

if $DRY_RUN; then
  echo "✓ Dry-run complete (no remotes modified)."
else
  echo "✓ Both remotes updated."
fi
