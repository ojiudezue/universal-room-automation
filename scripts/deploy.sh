#!/usr/bin/env bash
# deploy.sh — One-command deploy pipeline for URA
# Usage: ./scripts/deploy.sh <version> <commit-summary> <release-notes> \
#            --cards ID[,ID...] --why "<reasoning trail: WHY, not WHAT>"
# Example: ./scripts/deploy.sh "3.3.5.7" "Fix zone entity grouping" "- Fixed grouping" \
#            --cards ZONE-GROUP-1 --why "Grouping broke because the area-registry \
#            lookup keyed on device_id not entity_id; chose the registry join over \
#            a name-map because renames would silently re-collide. Verified by ..."
#
# --cards / --why are FORCING GATES (BOARD-CURRENCY-1 + vibememo): a real release
#   reconciles the board AND writes a proper reasoning trail, or it does not ship.
#   --no-cards is the explicit escape for pure-docs releases (writes neither).
# With --dry-run flag, prints each step without executing.

set -euo pipefail

VERSION="${1:?Usage: deploy.sh <version> <commit-summary> <release-notes>}"
# Strip leading 'v' if present — script adds 'v' prefix in commits/tags/releases
VERSION="${VERSION#v}"
SUMMARY="${2:?Usage: deploy.sh <version> <commit-summary> <release-notes>}"
NOTES="${3:?Usage: deploy.sh <version> <commit-summary> <release-notes>}"
DRY_RUN=false
CARDS=""
NO_CARDS=false
WHY=""
REVISIT=""
# Forcing function (operator-coined 2026-08-19): a real ship MUST carry a proper
# vibememo reasoning trail (the WHY), not the thin auto-stub that just echoed the
# release notes. --why is required whenever --cards is (i.e. a real release);
# --no-cards (pure-docs) is exempt. vibememo_ship.py re-validates substance.
MIN_WHY_CHARS=200

# Check for --dry-run / --cards / --no-cards anywhere in args.
# (Positional args 1-3 are version/summary/notes; flags may appear in any order.)
# M1: --cards must be followed by a non-empty NON-FLAG value. Rejecting a
# leading '--' here catches `deploy.sh 1 2 3 --cards --dry-run` early,
# where the previous parser silently swallowed `--dry-run` as the ID list.
i=0
for arg in "$@"; do
  i=$((i+1))
  case "$arg" in
    --dry-run)  DRY_RUN=true ;;
    --no-cards) NO_CARDS=true ;;
    --cards)
      # Next arg is the ID list.
      next_idx=$((i+1))
      next_val="${!next_idx:-}"
      if [[ -z "$next_val" || "$next_val" == --* ]]; then
        echo "ERROR: --cards requires a non-empty ID list (got: '${next_val}')." >&2
        echo "       Example: --cards CARD-1,CARD-2   (do not pass another flag)." >&2
        exit 1
      fi
      CARDS="$next_val"
      ;;
    --cards=*)
      CARDS="${arg#--cards=}"
      if [[ -z "$CARDS" ]]; then
        echo "ERROR: --cards= requires a non-empty ID list." >&2
        exit 1
      fi
      ;;
    --why)
      next_idx=$((i+1))
      next_val="${!next_idx:-}"
      if [[ -z "$next_val" || "$next_val" == --* ]]; then
        echo "ERROR: --why requires a non-empty reasoning string (got: '${next_val}')." >&2
        echo "       The WHY of the ship: decision, alternatives, what review/verify caught." >&2
        exit 1
      fi
      WHY="$next_val"
      ;;
    --why=*)
      WHY="${arg#--why=}"
      ;;
    --revisit)
      next_idx=$((i+1))
      next_val="${!next_idx:-}"
      if [[ -z "$next_val" || "$next_val" == --* ]]; then
        echo "ERROR: --revisit requires the disposition discriminator (got: '${next_val}')." >&2
        echo "       The OBSERVABLE that closes this ship's shipped_organic card (Soak-Exit rule):" >&2
        echo "       an entity value / DB row / metric to QUERY, not a date to watch." >&2
        exit 1
      fi
      REVISIT="$next_val"
      ;;
    --revisit=*)
      REVISIT="${arg#--revisit=}"
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
COMPONENT_DIR="$REPO_DIR/custom_components/universal_room_automation"

# Guard: deploys MUST run from develop. deploy.sh commits to current HEAD but
# pushes/PRs/releases develop — running from a feature branch cuts a CODELESS
# release (v5.8.0 2026-07-05, v5.25.0 2026-07-20). Merge to develop first.
CURRENT_BRANCH="$(git -C "$REPO_DIR" branch --show-current)"
if [[ "$CURRENT_BRANCH" != "develop" ]]; then
  echo "ERROR: deploy.sh must run from 'develop' (current: '$CURRENT_BRANCH')." >&2
  echo "The version-stamp commit would land on '$CURRENT_BRANCH' while the PR/release" >&2
  echo "ships develop — a codeless release. Merge your branch into develop, then re-run." >&2
  exit 1
fi

# BOARD-CURRENCY-1 rungs 1+2: board reconciliation is the ONLY step in the
# deploy ritual with no forcing function. This mirrors the develop-branch
# hard-gate pattern above and REFUSES to deploy when --cards is absent, so the
# board update becomes an OUTPUT of shipping instead of a task beside it.
# --no-cards is the explicit escape for pure-docs releases (must be logged,
# never silent). All validation happens BEFORE any push; all writes happen
# AFTER the push succeeds (see step 4b). A failed post-push write warns
# loudly but must NEVER exit non-zero — a stale board is strictly better than
# a half-released version.
KANBAN_YAML="$REPO_DIR/docs/planning/kanban.data.yaml"
if [[ -z "$CARDS" && "$NO_CARDS" == "false" ]]; then
  echo "ERROR: deploy.sh requires --cards ID[,ID...] (BOARD-CURRENCY-1 gate)." >&2
  echo "  Use --no-cards for pure-docs releases (explicit, will be logged)." >&2
  echo "" >&2
  echo "  Current in_progress / review cards on the board:" >&2
  python3 "$SCRIPT_DIR/kanban_ship.py" list-candidates --file "$KANBAN_YAML" >&2 || true
  exit 1
fi
if [[ -n "$CARDS" && "$NO_CARDS" == "true" ]]; then
  echo "ERROR: --cards and --no-cards are mutually exclusive." >&2
  exit 1
fi
# --why forcing gate: required for any real (carded) release, validated BEFORE
# any push so a thin/absent reasoning fails the deploy early — same posture as
# the --cards gate. Pure-docs (--no-cards) releases write no vibememo, so they
# are exempt. The char floor here mirrors vibememo_ship.MIN_REASONING_CHARS;
# the writer re-checks word count + notes-echo so this is fail-fast, not sole.
if [[ "$NO_CARDS" == "false" ]]; then
  why_trimmed="$(printf '%s' "$WHY" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  if [[ -z "$why_trimmed" ]]; then
    echo "ERROR: deploy.sh requires --why \"<reasoning>\" (vibememo forcing gate)." >&2
    echo "  vibememo = WHY, not WHAT. Capture the decision, the alternatives weighed," >&2
    echo "  and what the review/verify actually caught. It doesn't take that long." >&2
    echo "  (Pure-docs releases: use --no-cards, which writes no vibememo.)" >&2
    exit 1
  fi
  if [[ "${#why_trimmed}" -lt "$MIN_WHY_CHARS" ]]; then
    echo "ERROR: --why is too thin (${#why_trimmed} chars < $MIN_WHY_CHARS)." >&2
    echo "  A ship reasoning trail is a few real sentences, not a headline." >&2
    exit 1
  fi
  # --revisit forcing gate (Soak-Exit synergy): a carded ship MUST state the
  # observable that will DISPOSE its shipped_organic card, so the soak-sweep has
  # something to query rather than a card that rides forever. vibememo_ship.py
  # re-validates the 60-char floor; this is fail-fast.
  revisit_trimmed="$(printf '%s' "$REVISIT" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  if [[ -z "$revisit_trimmed" ]]; then
    echo "ERROR: deploy.sh requires --revisit \"<disposition discriminator>\" (Soak-Exit gate)." >&2
    echo "  Name the OBSERVABLE that closes this ship's shipped_organic card — an entity value," >&2
    echo "  a DB row, a metric to QUERY. Not a date. e.g.:" >&2
    echo "  --revisit \"sensor.X attr drain_floor==15 on a class-disagreement night at ~02:00\"" >&2
    exit 1
  fi
fi
if [[ -n "$CARDS" ]]; then
  # Validate every ID exists BEFORE any push happens.
  if ! python3 "$SCRIPT_DIR/kanban_ship.py" validate "$CARDS" --file "$KANBAN_YAML"; then
    echo "ERROR: refusing to deploy — unknown card ID(s) above." >&2
    exit 1
  fi
  echo "==> BOARD-CURRENCY-1: cards to reconcile after push: $CARDS"
else
  echo "==> BOARD-CURRENCY-1: --no-cards (pure-docs release) — no board write will occur"
fi

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

# Step 4b: BOARD-CURRENCY-1 rungs 1+2 — post-push board + vibememo writes.
# THE PUSH HAS ALREADY SUCCEEDED. From here on, any failure prints a loud,
# greppable [BOARD-CURRENCY-1] warning and CONTINUES; we never exit non-zero
# after a successful push. A stale board is strictly better than aborting a
# half-released version. `set +e` is scoped locally so steps 5-7 remain
# fail-fast.
step "4b/7 BOARD-CURRENCY-1: reconciling kanban + vibememo (post-push)"
if [[ -n "$CARDS" ]]; then
  if $DRY_RUN; then
    # H2: --dry-run is a REAL rehearsal — copy the live board + vibememo dir
    # to a tempdir, invoke the actual writers against those copies, and diff
    # so the operator sees exactly what a live run would produce. This
    # exercises the real code path (formerly untested until a live ship).
    rehearsal_dir="$(mktemp -d -t ura-deploy-dry.XXXXXX)"
    trap 'rm -rf "$rehearsal_dir"' EXIT
    cp "$KANBAN_YAML" "$rehearsal_dir/kanban.data.yaml"
    echo "  [dry-run] rehearsing kanban_ship.py mark-shipped $CARDS --version $VERSION"
    if python3 "$SCRIPT_DIR/kanban_ship.py" mark-shipped "$CARDS" \
         --version "$VERSION" --file "$rehearsal_dir/kanban.data.yaml"; then
      echo "  [dry-run] kanban diff (would-be write against real board):"
      diff -u "$KANBAN_YAML" "$rehearsal_dir/kanban.data.yaml" | sed 's/^/    /' || true
    else
      echo "  [dry-run] [warn] rehearsal FAILED — kanban writer errored on the real board" >&2
    fi

    mkdir -p "$rehearsal_dir/.vibememo/users"
    # Mirror the target author directory (if any) so entry-id numbering is
    # realistic. resolve_author() walks users/; a single-dir setup preserves
    # the operator's canonical namespace.
    if [ -d "$REPO_DIR/.vibememo/users" ]; then
      cp -R "$REPO_DIR/.vibememo/users/." "$rehearsal_dir/.vibememo/users/"
    fi
    echo "  [dry-run] rehearsing vibememo_ship.py --version $VERSION --repo-root $rehearsal_dir"
    # Marker file lets `find -newer` return ONLY the entry the rehearsal
    # created, not the pre-existing entries copied from the real repo.
    marker="$rehearsal_dir/.marker"; touch "$marker"; sleep 1
    if python3 "$SCRIPT_DIR/vibememo_ship.py" \
         --version "$VERSION" \
         --summary "$SUMMARY" \
         --notes "$NOTES" \
         --reasoning "$WHY" \
         --revisit-trigger "$REVISIT" \
         --cards "$CARDS" \
         --repo-root "$rehearsal_dir"; then
      echo "  [dry-run] vibememo entry (would-be write):"
      find "$rehearsal_dir/.vibememo/users" -name "*.json" -newer "$marker" -print 2>/dev/null | while read -r f; do
        echo "    ----- ${f#$rehearsal_dir/} -----"
        sed 's/^/    /' "$f"
      done
    else
      echo "  [dry-run] [warn] rehearsal FAILED — vibememo writer errored" >&2
    fi
    echo "  [dry-run] git add + commit + push (kanban reconcile) — NOT executed"
    rm -rf "$rehearsal_dir"; trap - EXIT
  else
    set +e
    python3 "$SCRIPT_DIR/kanban_ship.py" mark-shipped "$CARDS" \
      --version "$VERSION" --file "$KANBAN_YAML"
    kanban_rc=$?
    python3 "$SCRIPT_DIR/vibememo_ship.py" \
      --version "$VERSION" \
      --summary "$SUMMARY" \
      --notes "$NOTES" \
      --reasoning "$WHY" \
         --revisit-trigger "$REVISIT" \
      --cards "$CARDS"
    vibememo_rc=$?
    if [ "$kanban_rc" -ne 0 ]; then
      echo "  [warn] [BOARD-CURRENCY-1] kanban write FAILED (rc=$kanban_rc) — board is now stale for $CARDS; catch up manually" >&2
    fi
    if [ "$vibememo_rc" -ne 0 ]; then
      echo "  [warn] [BOARD-CURRENCY-1] vibememo write FAILED (rc=$vibememo_rc) — decision trail missing for v$VERSION" >&2
    fi
    if [ "$kanban_rc" -eq 0 ] || [ "$vibememo_rc" -eq 0 ]; then
      # Follow-up commit + push so the board/vibememo changes reach master.
      # L1: drop the 2>/dev/null blanket — status check names what was staged.
      git -C "$REPO_DIR" add \
        "$KANBAN_YAML" \
        "$REPO_DIR/.vibememo/users/"
      staged="$(git -C "$REPO_DIR" diff --cached --name-only)"
      if [ -z "$staged" ]; then
        echo "  [warn] [BOARD-CURRENCY-1] git add produced no staged files — nothing to reconcile?" >&2
      fi
      # M3: this is release plumbing; --no-verify sidesteps hook flakes that
      # would leave the board locally modified and block the next deploy on a
      # dirty tree. Authored-code hooks belong on step 3, not here.
      git -C "$REPO_DIR" commit --no-verify -m "kanban+vibememo: BOARD-CURRENCY-1 reconcile v$VERSION ($CARDS)"
      commit_rc=$?
      if [ "$commit_rc" -eq 0 ]; then
        git -C "$REPO_DIR" push origin develop
        push_rc=$?
        if [ "$push_rc" -ne 0 ]; then
          echo "  [warn] [BOARD-CURRENCY-1] follow-up push failed (rc=$push_rc) — commit is local; retry manually" >&2
        fi
        # M2: mirror the reconcile commit to Gitea best-effort so
        # gitea/develop does not trail origin/develop by exactly this commit
        # after every release. Warn-only — gitea is mirror-only (see step 4).
        if git -C "$REPO_DIR" remote get-url gitea >/dev/null 2>&1; then
          bash "$REPO_DIR/scripts/dual-push.sh" --gitea-only develop
          gitea_rc=$?
          if [ "$gitea_rc" -ne 0 ]; then
            echo "  [warn] [BOARD-CURRENCY-1] gitea mirror of reconcile commit failed (rc=$gitea_rc) — origin has it" >&2
          fi
        fi
      else
        echo "  [warn] [BOARD-CURRENCY-1] follow-up commit failed (rc=$commit_rc) — nothing to reconcile? board file untouched?" >&2
      fi
    fi
    set -e
  fi
elif $NO_CARDS; then
  echo "  --no-cards: pure-docs release, no board or vibememo write (LOGGED)"
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
