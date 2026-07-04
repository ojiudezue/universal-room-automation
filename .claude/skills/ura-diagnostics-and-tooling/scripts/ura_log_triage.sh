#!/usr/bin/env bash
# ura_log_triage.sh — split URA-relevant log lines into signal vs noise.
# Verified 2026-07-02 against URA v5.7.2 log patterns.
#
# Usage:
#   ura_log_triage.sh <path/to/home-assistant.log>
#
# Prints two sections: SIGNAL (investigate) and NOISE (dismiss).
# Read-only; makes no writes anywhere.

set -euo pipefail

LOG="${1:-}"
if [[ -z "${LOG}" || ! -f "${LOG}" ]]; then
  echo "usage: $0 <path/to/home-assistant.log>" >&2
  exit 2
fi

echo "=== SIGNAL (investigate every line) ==="

echo "-- URA ERRORs --"
grep -E "ERROR .*universal_room_automation" "${LOG}" || echo "  (none)"

echo "-- Untracked task exceptions (Bug Class #34 family) --"
grep -E "UnboundLocalError|Task exception was never retrieved|coroutine .* was never awaited" "${LOG}" || echo "  (none)"

echo "-- Coordinator setup failures --"
grep -E "Setup (of|timed out).*universal_room_automation" "${LOG}" || echo "  (none)"

echo "-- URA parent-entry reload cascades (watchdog hazard) --"
grep -E "Reloading config entry.*universal_room_automation" "${LOG}" || echo "  (none)"

echo
echo "=== NOISE (dismiss unless it persists past boot) ==="

echo "-- Shelly Not connected (cloud reconnect at boot) --"
grep -Ec "shelly.*Not connected|shellyies.*Not connected" "${LOG}" || echo "  0"

echo "-- Template from_json errors (upstream not-yet-ready) --"
grep -Ec "from_json.*Error|TemplateError.*from_json" "${LOG}" || echo "  0"

echo "-- appletv errors (non-URA) --"
grep -Ec "appletv" "${LOG}" || echo "  0"

echo "-- 'connection lost set_value' (ws backpressure, NOT a crash) --"
grep -Ec "connection lost set_value" "${LOG}" || echo "  0"

echo "-- 'No room coordinators found after 60s' (should be 0-1 post-v4.7.18.2) --"
grep -Ec "No room coordinators found after 60s" "${LOG}" || echo "  0"

echo
echo "Done. If SIGNAL section is non-empty, cite exact lines + timestamps in review."
