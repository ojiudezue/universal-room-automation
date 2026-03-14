# v3.16.0: Circuit Alert De-spam + Kill Switch Persistence + BLE Re-entry

**Date:** 2026-03-14
**Branch:** develop -> main
**Tests:** 1110 passed (16 pre-existing aiosqlite failures, no regressions)

## Problems

Three issues discovered during production use:

1. **Breaker alert spam bypassing kill switch**: Circuit tripped-breaker alerts were hardcoded as CRITICAL severity, which bypasses ALL NM filters including the kill switch, quiet hours, and severity thresholds. Unknown/unfilled SPAN breaker slots also fired spurious alerts.
2. **Kill switch not surviving restarts**: RestoreEntity read NM state during `async_added_to_hass`, but NM may not be initialized yet (config entry setup ordering). The switch silently fell back to "off".
3. **BLE ghost occupancy blocking lights**: When BLE (Bluetooth) places a person in a room before they physically enter (signal bleed through walls), the room is already "occupied". Physical entry (motion sensor) doesn't trigger a state change, so `handle_occupancy_change` never fires and lights stay off. User waits up to 30s for the polling interval.

## Solutions

### 1. Circuit Alert De-spam (`energy_circuits.py` + `energy.py`)

- **Severity downgraded**: Tripped breaker → HIGH (was CRITICAL). Consumption anomaly → MEDIUM. Only generator alerts remain CRITICAL.
- **Unknown circuit filter**: Discovery skips circuits with "unknown", "unfilled", "unused", "spare", "empty" in friendly name.
- **Energy delivery guard**: Circuits must accumulate 50 Wh of real energy delivery before tripped-breaker alerts can fire. Prevents false alerts from circuits that briefly spike above 5W during panel resets.
- **Threshold increased**: Zero-power duration threshold raised from 120s to 300s.
- **Per-type alert messages**: Tripped breaker and consumption anomaly alerts now have distinct message text (was using tripped breaker message for both).
- **Trapezoidal integration fix**: `0.0 or power` Python falsy bug fixed — was inflating energy estimates when last_power was exactly 0.

### 2. Kill Switch Restart Persistence (`switch.py`)

- **Self-contained state**: Switch stores `_is_on` locally instead of reading from NM. `is_on` property returns the local flag.
- **Deferred NM sync**: On restore, sets local flag immediately, then syncs to NM via `_sync_to_nm()`. If NM isn't ready, retries every 10s up to 18 times (3 minutes), then gives up gracefully.
- **Cleanup on teardown**: Stores `async_call_later` unsub handle, cancels in `async_will_remove_from_hass`.
- **Always available**: Switch is always available (not gated on NM existence) since state is self-contained.
- **Turn on/off before NM**: If user toggles switch before NM is ready, local state updates and deferred sync is scheduled.

### 3. BLE→Motion Source Transition Re-entry (`coordinator.py`)

- **Source tracking**: New `_last_occupancy_source` field tracks whether occupancy is driven by "ble", "motion", "mmwave", etc.
- **Re-entry trigger**: When room is already occupied AND source transitions from "ble" to a real sensor, re-triggers `handle_occupancy_change(True, data)` to ensure lights turn on.
- **60s cooldown**: Prevents rapid re-entry thrashing from flaky motion sensors or pets.
- **Normal path untouched**: The fast vacant→occupied event-driven path is an `if` branch; the re-entry is an `elif` — they cannot both fire.

### Files Changed

| File | Changes |
|------|---------|
| `energy_circuits.py` | Threshold 120→300s, energy delivery guard (50 Wh), unknown circuit filter, trapezoidal fix, cumulative energy tracking |
| `energy.py` | Per-type severity (HIGH/MEDIUM) and distinct alert messages for tripped vs consumption anomalies |
| `switch.py` | Self-contained `_is_on`, bounded deferred sync (18 retries), teardown cleanup, always-available |
| `coordinator.py` | `_last_occupancy_source` tracking, BLE→motion re-entry with 60s cooldown |

### Review Findings Fixed

Both staff-engineer adversarial reviews identified and all HIGH/MEDIUM findings were resolved:
- **S1 (HIGH)**: Unbounded retry loop → capped at 18 retries
- **S2 (MEDIUM)**: Timer handle not stored → stored + cancelled on teardown
- **2.1 (HIGH)**: Wrong message for consumption anomalies → per-type messages
- **2.2 (LOW)**: `0.0 or power` falsy bug → explicit None check
- **3.1 (MEDIUM)**: Rapid re-entry thrashing → 60s cooldown
- **C1 (LOW)**: Defensive getattr → direct attribute access
