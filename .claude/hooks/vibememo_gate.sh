#!/bin/bash
# VibeMemo capture gate (replaces the user-facing systemMessage reminders, operator 2026-11-14).
# Modes:
#   commit  PreToolUse(Bash): silent note to the model (additionalContext) when decision-bearing
#           commits have piled up since the last vibememo entry; at most once per 30 min.
#   stop    Stop: once per session, block the stop with a capture task if decision-bearing
#           commits landed since the last entry; never loops (stop_hook_active guard).
# Prints nothing (no user noise) when there is nothing to capture.
mode="$1"
input=$(cat)
root="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$root" 2>/dev/null || exit 0
state="$root/.claude/tmp"; mkdir -p "$state" 2>/dev/null

# Commits since the last vibememo entry that touched decision-bearing paths.
pending() {
  local last
  last=$(git log -1 --format=%H -- .vibememo/users 2>/dev/null)
  [ -z "$last" ] && { echo 0; return; }
  git log --format=%H "$last"..HEAD -- custom_components CLAUDE.md .claude/skills .claude/agents \
    'docs/planning/PLANNING_*' 'docs/planning/ARC_*' 'docs/Coordinator' 2>/dev/null | wc -l | tr -d ' '
}

case "$mode" in
  commit)
    cmd=$(echo "$input" | jq -r '.tool_input.command // ""')
    echo "$cmd" | grep -q 'git commit' || exit 0
    n=$(pending)
    [ "${n:-0}" -ge 3 ] || exit 0
    stamp="$state/vibememo_last_nudge"
    now=$(date +%s)
    last=$(cat "$stamp" 2>/dev/null || echo 0)
    [ $((now - last)) -ge 1800 ] || exit 0
    echo "$now" > "$stamp"
    jq -n --arg n "$n" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:("VibeMemo: " + $n + " decision-bearing commits since the last vibememo entry. After this commit, if any carried a load-bearing decision, pivot or counseling, write the entries per the vibememo skill (index + entries + user narrative). Skip silently if none did.")}}'
    ;;
  stop)
    [ "$(echo "$input" | jq -r '.stop_hook_active // false')" = "true" ] && exit 0
    sid=$(echo "$input" | jq -r '.session_id // "none"')
    marker="$state/vibememo_stop_$sid"
    [ -f "$marker" ] && exit 0
    n=$(pending)
    [ "${n:-0}" -ge 1 ] || exit 0
    touch "$marker"
    jq -n --arg n "$n" '{decision:"block",reason:("VibeMemo capture before ending: " + $n + " decision-bearing commits since the last vibememo entry. Write entries for any load-bearing decisions, pivots or counseling (vibememo skill), update the user narrative and synthesize the project narrative, commit, then stop. If none qualify, say so in one line and stop.")}'
    ;;
esac
exit 0
