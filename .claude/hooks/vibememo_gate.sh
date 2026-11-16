#!/bin/bash
# VibeMemo capture gate (replaces the user-facing systemMessage reminders, operator 2026-11-14).
# Modes:
#   commit  PreToolUse(Bash): silent note to the model (additionalContext) when decision-bearing
#           commits have piled up since the last vibememo entry; at most once per 30 min.
#   stop    Stop: block the stop with a capture task if decision-bearing commits landed since
#           the last entry; once per last-entry (re-arms after each new entry, so a multi-day
#           session is not covered by one marker); never loops (stop_hook_active guard).
# 2026-11-15 fixes: count board/audit/README commits (operator decisions land on cards and
# audits, not only code); add a time trigger (>=1 pending and last entry >2 h old); flag a
# user narrative lagging >=3 entries behind.
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
    'docs/planning/PLANNING_*' 'docs/planning/ARC_*' 'docs/planning/AUDIT_*' \
    docs/planning/kanban.data.yaml docs/readmes docs/Coordinator 2>/dev/null | wc -l | tr -d ' '
}

# Seconds since the last vibememo entry commit.
entry_age() {
  local t
  t=$(git log -1 --format=%ct -- .vibememo/users 2>/dev/null)
  [ -z "$t" ] && { echo 0; return; }
  echo $(( $(date +%s) - t ))
}

# Entries committed after the user narrative last changed.
narrative_lag() {
  local n
  n=$(git log -1 --format=%H -- .vibememo/users/*/vibememo.md 2>/dev/null)
  [ -z "$n" ] && { echo 0; return; }
  git log --format=%H "$n"..HEAD -- .vibememo/users/*/entries 2>/dev/null | wc -l | tr -d ' '
}

note_lag() {
  local l
  l=$(narrative_lag)
  [ "${l:-0}" -ge 3 ] && echo " The user narrative is ${l} entry commits behind; update it." || true
}

case "$mode" in
  commit)
    cmd=$(echo "$input" | jq -r '.tool_input.command // ""')
    echo "$cmd" | grep -q 'git commit' || exit 0
    n=$(pending)
    age=$(entry_age)
    lagnote=$(note_lag)
    if [ "${n:-0}" -lt 3 ] && ! { [ "${n:-0}" -ge 1 ] && [ "${age:-0}" -ge 7200 ]; } && [ -z "$lagnote" ]; then
      exit 0
    fi
    stamp="$state/vibememo_last_nudge"
    now=$(date +%s)
    last=$(cat "$stamp" 2>/dev/null || echo 0)
    [ $((now - last)) -ge 1800 ] || exit 0
    echo "$now" > "$stamp"
    jq -n --arg n "$n" --arg lag "$lagnote" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:("VibeMemo: " + $n + " decision-bearing commits since the last vibememo entry. After this commit, if any carried a load-bearing decision, pivot or counseling, write the entries per the vibememo skill (index + entries + user narrative). Skip silently if none did." + $lag)}}'
    ;;
  stop)
    [ "$(echo "$input" | jq -r '.stop_hook_active // false')" = "true" ] && exit 0
    sid=$(echo "$input" | jq -r '.session_id // "none"')
    lastentry=$(git log -1 --format=%h -- .vibememo/users 2>/dev/null)
    marker="$state/vibememo_stop_${sid}_${lastentry}"
    [ -f "$marker" ] && exit 0
    n=$(pending)
    [ "${n:-0}" -ge 1 ] || exit 0
    touch "$marker"
    jq -n --arg n "$n" '{decision:"block",reason:("VibeMemo capture before ending: " + $n + " decision-bearing commits since the last vibememo entry. Write entries for any load-bearing decisions, pivots or counseling (vibememo skill), update the user narrative and synthesize the project narrative, commit, then stop. If none qualify, say so in one line and stop.")}'
    ;;
esac
exit 0
