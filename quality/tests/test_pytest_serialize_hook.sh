#!/bin/bash
# Behavioural tests for scripts/hooks/pytest_serialize.sh.
#
# Not a pytest file on purpose — it tests a shell hook, and running it under
# pytest would be self-referential (the hook guards pytest).
# Run directly:  bash quality/tests/test_pytest_serialize_hook.sh

set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
HOOK=./scripts/hooks/pytest_serialize.sh

pass=0; fail=0
check() { # check <name> <expected-substring> <actual>
  if printf '%s' "$3" | grep -q "$2"; then
    echo "  PASS  $1"; pass=$((pass+1))
  else
    echo "  FAIL  $1"; echo "        expected to contain: $2"; echo "        got: $3"; fail=$((fail+1))
  fi
}

echo "test_pytest_serialize_hook"

# 1. Non-pytest commands are never touched.
out=$(echo '{"tool_input":{"command":"git status"}}' | $HOOK)
check "non-pytest command passes through" '^{}$' "$out"

# 2. Malformed input fails OPEN (a broken guard must not block real work).
out=$(echo 'not json at all' | $HOOK)
check "malformed input fails open" '^{}$' "$out"

# 3. pytest with nothing running is allowed.
out=$(echo '{"tool_input":{"command":"python3 -m pytest quality/tests/"}}' | $HOOK)
check "pytest allowed when nothing running" '^{}$' "$out"

# 4. THE LOAD-BEARING CASE: pytest is DENIED while another run is in flight.
#    A sleep stands in for the running suite via the test-only pattern override.
sleep 30 &
victim=$!
sleep 0.3
out=$(PYTEST_GUARD_PATTERN="sleep 30" \
      sh -c 'echo "{\"tool_input\":{\"command\":\"python3 -m pytest quality/tests/\"}}" | '"$HOOK")
check "concurrent pytest is DENIED"          '"permissionDecision": "deny"' "$out"
check "deny names the blocking pid"          "pid=${victim}"                "$out"
check "deny reports elapsed time"            'elapsed='                     "$out"
check "deny forbids renaming the command"    'Do NOT work around'           "$out"

# 5. Non-pytest commands stay allowed EVEN WHILE a run is in flight —
#    the guard must not become a global lock on all shell work.
out=$(PYTEST_GUARD_PATTERN="sleep 30" \
      sh -c 'echo "{\"tool_input\":{\"command\":\"git log\"}}" | '"$HOOK")
check "non-pytest still allowed during a run" '^{}$' "$out"

kill $victim 2>/dev/null; wait $victim 2>/dev/null

echo
echo "  ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ] || exit 1
