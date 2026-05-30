#!/usr/bin/env bash
# deploy.sh — One-command deploy pipeline for URA
# Usage: ./scripts/deploy.sh <version> <commit-summary> <release-notes>
# Example: ./scripts/deploy.sh "3.3.5.7" "Fix zone entity grouping" "- Fixed zone entities not grouping correctly"
#
# With --dry-run flag, prints each step without executing.

set -euo pipefail

VERSION="${1:?Usage: deploy.sh <version> <commit-summary> <release-notes>}"
# Strip leading 'v' if present — script adds 'v' prefix in commits/tags/releases
VERSION="${VERSION#v}"
SUMMARY="${2:?Usage: deploy.sh <version> <commit-summary> <release-notes>}"
NOTES="${3:?Usage: deploy.sh <version> <commit-summary> <release-notes>}"
DRY_RUN=false

# Check for --dry-run anywhere in args
for arg in "$@"; do
  if [[ "$arg" == "--dry-run" ]]; then
    DRY_RUN=true
  fi
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
COMPONENT_DIR="$REPO_DIR/custom_components/universal_room_automation"

step() {
  echo ""
  echo "==> $1"
}

run() {
  if $DRY_RUN; then
    echo "  [dry-run] $*"
  else
    "$@"
  fi
}

# Step 1: Stamp version
step "1/7 Stamping version $VERSION"
run python3 "$SCRIPT_DIR/stamp_version.py" "$VERSION"

# Step 2: Stage changed files
step "2/7 Staging changed files"
run git -C "$REPO_DIR" add \
  "$COMPONENT_DIR/const.py" \
  "$COMPONENT_DIR/manifest.json" \
  "$COMPONENT_DIR"/*.py \
  "$COMPONENT_DIR/domain_coordinators/"*.py \
  "$COMPONENT_DIR/strings.json" \
  "$COMPONENT_DIR/translations/" \
  "$COMPONENT_DIR/frontend/" \
  "$COMPONENT_DIR/brand/" \
  "$REPO_DIR/quality/tests/" \
  "$REPO_DIR/docs/readmes/" \
  "$REPO_DIR/docs/"*.md

# Step 3: Commit
step "3/7 Committing: $SUMMARY"
if $DRY_RUN; then
  echo "  [dry-run] git commit -m \"v$VERSION: $SUMMARY\""
else
  git -C "$REPO_DIR" commit -m "v$VERSION: $SUMMARY"
fi

# Step 4: Push to develop (GitHub origin + homelab Gitea mirror)
# v4.7.10 (fix-up A-H1): gitea is MIRROR-ONLY. Origin is already pushed
# above, so any gitea failure must not halt the pipeline mid-flight (no PR,
# no release). Only deliberate-propagation codes halt:
#   rc=2   bash script-level error (set -e tripped)         → halt
#   rc=130 SIGINT (user-initiated)                          → halt
#   rc=143 SIGTERM (operator/CI-initiated)                  → halt
# Everything else (rc=1 preflight/auth, rc=128 git network/auth/repo-path,
# any other unexpected nonzero) → `[warn]` and CONTINUE so PR + release still
# happen. The previous narrow-rc dispatch regressed UX vs pre-v4.7.10, which
# swallowed ALL nonzero with [warn]. We now retain the warn-continue contract
# AND keep the rc visible in the warning for diagnostics.
step "4/7 Pushing to develop (origin + gitea)"
run git -C "$REPO_DIR" push origin develop
# Gitea mirror — only if remote exists. dual-push.sh handles credentials
# from .env.local and restores clean URL via trap on any failure.
if git -C "$REPO_DIR" remote get-url gitea >/dev/null 2>&1; then
  if $DRY_RUN; then
    echo "  [dry-run] bash scripts/dual-push.sh --gitea-only develop"
  else
    # Capture dual-push exit code without leaking `set +e` into steps 5-7.
    set +e
    bash "$REPO_DIR/scripts/dual-push.sh" --gitea-only develop
    rc=$?
    set -e
    if [ "$rc" -eq 0 ]; then
      :  # success
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
      # rc=1 (preflight/auth), rc=128 (git auth/network/repo-path — most
      # common real-world failure mode), and any other unexpected nonzero
      # all fall here. WARN and CONTINUE — gitea is mirror-only.
      echo "  [warn] gitea mirror push failed (rc=$rc) — origin already pushed; gitea is mirror-only"
      echo "  [warn] catch up later with: bash scripts/dual-push.sh --gitea-only develop"
    fi
  fi
fi

# Step 5: Create PR
step "5/7 Creating PR: develop → master"
if $DRY_RUN; then
  echo "  [dry-run] gh pr create --base master --head develop --title \"v$VERSION: $SUMMARY\" --body \"$NOTES\""
else
  gh pr create --base master --head develop \
    --title "v$VERSION: $SUMMARY" \
    --body "$NOTES" \
    --repo "$(gh repo view --json nameWithOwner -q .nameWithOwner)"
fi

# Step 6: Merge PR
step "6/7 Merging PR"
if $DRY_RUN; then
  echo "  [dry-run] gh pr merge develop --merge"
else
  gh pr merge develop --merge --repo "$(gh repo view --json nameWithOwner -q .nameWithOwner)"
fi

# Step 7: Create release
step "7/7 Creating release v$VERSION"
if $DRY_RUN; then
  echo "  [dry-run] gh release create v$VERSION --target master --title \"v$VERSION\" --notes \"$NOTES\""
else
  gh release create "v$VERSION" --target master \
    --title "v$VERSION: $SUMMARY" \
    --notes "$NOTES" \
    --repo "$(gh repo view --json nameWithOwner -q .nameWithOwner)"
fi

echo ""
echo "Deploy complete: v$VERSION"
