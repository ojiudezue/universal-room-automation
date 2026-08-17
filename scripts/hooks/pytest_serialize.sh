#!/bin/bash
# pytest_serialize.sh — PreToolUse(Bash) guard: refuse a second concurrent pytest.
#
# WHY THIS EXISTS (2026-08-16). The full URA suite runs in ~4 minutes alone.
# Under concurrent pytest this host thrashes and the same suite takes 30-45
# minutes; a 43-minute straggler was found still holding the machine while
# three agents queued behind it. Since the suite is the most-repeated
# operation in every build, review drill and validator run, that ~10x tax was
# the single largest source of cycle latency.
#
# A prompt instruction did not hold — agents run in parallel and each one
# individually believes it is the only one. So this is a MECHANISM, not a rule:
# the second concurrent invocation is denied before it starts.
#
# Emits a PreToolUse deny decision (exit 0 either way; the JSON carries the
# verdict). Fails OPEN on any internal error — a broken guard must never block
# legitimate work.

set -uo pipefail

input=$(cat)

cmd=$(printf '%s' "$input" | python3 -c \
  "import json,sys
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('command', ''))
except Exception:
    print('')" 2>/dev/null) || cmd=""

# Only guard actual pytest invocations against the project suite.
case "$cmd" in
  *pytest*) ;;
  *) printf '{}'; exit 0 ;;
esac

# ...but NEVER guard commands that merely TALK ABOUT pytest. The v1 guard
# matched any command containing the string, which blocked `ps`, `pgrep` and
# `kill` — i.e. exactly the commands its own deny message tells you to run to
# find and clear a straggler. That catch-22 blocked a real build agent.
# Diagnostic/cleanup verbs are always allowed through.
case "$cmd" in
  *pgrep*|*pkill*|*"ps -"*|*"ps a"*|*kill\ *|*htop*|*"grep -"*|*wc\ *|*tail\ *|*head\ *)
    printf '{}'; exit 0 ;;
esac

# `pgrep -f pytest` would match this very hook's own shell (the command string
# contains "pytest"), so match the python process form specifically.
# Pattern is overridable ONLY so the deny path can be exercised in a test
# without launching a real 4-minute suite (see quality/tests/test_pytest_serialize_hook.sh).
guard_pattern="${PYTEST_GUARD_PATTERN:-python[0-9.]* -m pytest}"
running=$(pgrep -f "$guard_pattern" 2>/dev/null | head -5) || running=""

if [ -z "$running" ]; then
  printf '{}'
  exit 0
fi

# A process that has burned no CPU is not running a suite — it is a zombie or a
# wedged shell whose python child already died. v1 blocked on exactly such a
# process (pid 1124: 0.01s CPU across 58 minutes, no live child), stalling a
# build agent that could not clear it. Only LIVE runs justify a deny; stale
# entries are reported and allowed through.
live=""
stale=""
for pid in $running; do
  cputime=$(ps -o time= -p "$pid" 2>/dev/null | tr -d ' ')
  [ -z "$cputime" ] && continue
  # ps TIME is [[dd-]hh:]mm:ss — anything at or below 00:05 of CPU is not a
  # real suite (a genuine run burns minutes of CPU within its first minute).
  case "$cputime" in
    0:00.[0-9]*|0:0[0-5].*|00:00*|00:0[0-5]) stale="${stale} ${pid}" ;;
    *) live="${live} ${pid}" ;;
  esac
done

if [ -z "$live" ]; then
  # Nothing genuinely running. Allow, but surface any stale pids so they get
  # cleaned up rather than silently accumulating.
  printf '{}'
  exit 0
fi
running="$live"

detail=""
for pid in $running; do
  elapsed=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
  [ -z "$elapsed" ] && continue
  detail="${detail} pid=${pid} elapsed=${elapsed};"
done

if [ -z "$detail" ]; then
  printf '{}'
  exit 0
fi

reason="BLOCKED: another pytest run is already in progress (${detail}). This host \
deadlocks and thrashes under concurrent pytest — the suite is ~4 min alone but \
30-45 min when overlapped, so starting a second run makes BOTH slower rather \
than finishing sooner. Wait for the current run to finish, then re-issue. If a \
listed run shows a large elapsed time (roughly 15m+) it is probably a straggler \
from an agent that already gave up: verify what it belongs to, then kill that \
PID and retry. Do NOT work around this by renaming the command."

printf '%s' "$reason" | python3 -c \
  "import json,sys
print(json.dumps({'hookSpecificOutput': {
    'hookEventName': 'PreToolUse',
    'permissionDecision': 'deny',
    'permissionDecisionReason': sys.stdin.read()}}))" 2>/dev/null \
  || printf '{}'

exit 0
