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
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD)}"
GITEA_CLEAN_URL=""

restore_gitea_url() {
  if [[ -n "$GITEA_CLEAN_URL" ]]; then
    git remote set-url gitea "$GITEA_CLEAN_URL" 2>/dev/null || true
  fi
}
trap restore_gitea_url EXIT

inject_gitea_creds() {
  if [[ -f .env.local ]]; then
    # shellcheck disable=SC1091
    set -a; source .env.local; set +a
    if [[ -z "${GITEA_USER:-}" || -z "${GITEA_TOKEN:-}" ]]; then
      echo "[dual-push] .env.local missing GITEA_USER or GITEA_TOKEN" >&2
      return 1
    fi
    local repo="${GITEA_REPO:-Okosisi/universal-room-automation}"
    GITEA_CLEAN_URL="https://gitea.phalanxmadrone.com/${repo}.git"
    git remote set-url gitea "https://${GITEA_USER}:${GITEA_TOKEN}@gitea.phalanxmadrone.com/${repo}.git"
    git push gitea "$BRANCH"
    git push gitea --tags
    git remote set-url gitea "$GITEA_CLEAN_URL"
  else
    echo "[dual-push] no .env.local; relying on osxkeychain" >&2
    git push gitea "$BRANCH"
    git push gitea --tags
  fi
}

echo "→ Pushing to GitHub origin/$BRANCH"
git push origin "$BRANCH"
git push origin --tags

echo "→ Pushing to Gitea gitea/$BRANCH"
inject_gitea_creds

echo "✓ Both remotes updated."
