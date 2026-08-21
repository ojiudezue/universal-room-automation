# AUDIT — recorder-bloat log-flood sources (RECORDER-BLOAT-LOGFLOOD-1)

Date: 2026-08-21
Scope: URA-side emitters feeding the 31 GB / 7-day recorder + 51 %
flash-life symptom. HA `recorder:` include/exclude retention config is
OUT OF SCOPE and lives in operator `configuration.yaml`; recommendations
for that config are captured in the last section.

## Verified findings (from measured 5-h scan 2026-08-21 13:28→18:45)

### D1 — D2 canary (`presence.py:5766`), 2525 hits / 5h

**Card D2-CANARY-GUEST-PREDICATE-1 assertion VERIFIED against source:**
The `else` branch at `presence.py:5765` sits after a plain if/elif that
runs UNCONDITIONALLY (there is no outer `if guest_armed:` block despite
the comment claiming so — I read lines 5700-5775 in full). Therefore
`else` fires on every normal no-guest cycle, WARN at each tick. The
consumer at `presence.py:6302` gates on `guest_room_gate_armed`, so the
0.8 value is behaviourally inert (card correct).

**Fix (D1 in this card):** demoted the log to `debug` AND re-guarded to
`if guest_armed and not guest_room_gate_armed:` — the check the author
intended: it fires only if the arming predicate is ever re-composed to
depend on something other than the room gate. Fixed the misleading
"outer if guest_armed block" comment. `presence.py:5763-5782`.

Expected post-deploy rate: 0/day under normal operation (fires only on
a genuine invariant regression, at DEBUG level).

### D2 — duty-cycle stuck NOTIFY-ONLY (`coordinator.py:2977`), 3565 hits / 5h

Fired per-tick per-sensor while a sensor stayed stuck. Detection loop
is `_detect_duty_cycle_stuck` at `coordinator.py:1628`; the emit was
inline in the tick body with no dedup. Persistent state re-announced as
event = defect.

**Fix (D2):** extracted to
`domain_coordinators/_dutycycle_notify.py` with two helpers:
`notify_warn_on_enter` (WARN once on entry, silent thereafter) and
`notify_release` (INFO on release edge, discharges the latch so a
re-engage warns again — suppression-needs-discharge). Coordinator now
tracks `self._dutycycle_notify_active: set[str]` and delegates.
`_current_notify` is built during the D2 loop; release scan runs at
the end of the try (only when the detector completes cleanly, so a
mid-detector exception can NOT mass-release).

Detection is unchanged. `_dutycycle_excluded_now` /
`_dutycycle_excluded_last_tick` / the paired STUCK-NM emits are all
byte-identical. The stuck NM per-day latch (`_stuck_sensor_fired`) is
unchanged.

**Diagnostic surface:** exposed as attribute
`dutycycle_stuck_notify` on `sensor.<room>_unavailable_entities`
(`sensor.py:1932-1948`) — sibling of the existing `chatter_telemetry`
+ `flapping_entities` attributes. Operators can still see the current
stuck notify-only set without grepping historical logs.

Expected post-deploy rate: 1 WARN per (room, sensor) on entry into the
stuck state + 1 INFO on release. For the 2 stuck sensors in the scan
window (studya mmWave, jaya_3), that is 2 WARNs / day (or per stuck
episode) instead of ~17,000.

### D3 — camera_census not-found (`camera_census.py:337`), 2030 hits / 5h

`EGRESS-CAMERA-DEAD-CONFIG-1` fixed the sibling method
`resolve_configured_cameras` (line 512-522 — warn-once with
`_unresolved_warned`), but the UN-GUARDED sister
`resolve_camera_entity` (called every ~1 s from
`perimeter_alert.py:3805` for every configured camera, and
`camera_census.py:1018` `get_person_sensor`) was NOT covered. That is
the actual source of the garage_a / garage_b flood.

**Fix (D3):** added the same `_unresolved_warned` warn-once guard to
`resolve_camera_entity`'s missing-entity branch, with discharge when
the entity is later resolved. `camera_census.py:337-373`.

Expected post-deploy rate: 1 WARN per configured-but-missing camera,
re-armed only when the entity registry changes (device deleted, entity
renamed, integration reload).

### D4 — sibling per-tick warning sweep

Grep across `custom_components/universal_room_automation/coordinator.py`
+ `domain_coordinators/*.py`. Every `_LOGGER.warning` inside a per-tick
path was inspected. Findings:

| location | classification | note |
|---|---|---|
| `coordinator.py:4187` failsafe "Forcing vacancy" | one-shot | Guarded by `self._failsafe_fired` — fires once per room per failsafe episode. OK. |
| `security.py:260` "Census data stale" | per-entry-event | Called from `_evaluate_entry_event` per doorbell/entry — not per-tick. Bounded by entry cadence. LOW. |
| `security.py:379` "Failed to detect camera platforms" | one-shot | Camera-platform detection is idempotent + memoised in `_camera_platforms`. OK. |
| `energy.py:6740` "DynamicPreset zone=... evaluation failed" | per-tick if failing | If a zone eval permanently raises, this floods per-zone per-tick. Not observed in the scan window. **Recommended follow-up:** convert to edge-triggered (warn once per (zone, error-key), re-arm on recovery). Not fixed in-cycle — needs a look at whether an existing per-zone health record already carries the state. Captured here for the audit backlog; not spawning a card per operator directive. |
| `hvac.py:3082, 3168` "Vacancy sweep failed to turn off" | per-tick per-entity while device is dead | If a fan/light is `unavailable`, the vacancy sweep re-tries every eval and warns each time. This is a live flood hazard when the actuator is offline (the very "device offline ≠ integration failed" scenario in the URA CLAUDE.md). **NOT fixed here — `hvac.py` is under active edit by another agent.** Flagging for post-merge follow-up: same edge-trigger pattern (warn once per (entity, error-mode), re-arm on availability change). |
| `hvac.py:1256, 2314` "EgressManager tick / preset overrides failed" | per-tick on persistent raise | Guarded by broad `try/except`. If the raise is chronic these flood. Not observed but same class as the DynamicPreset item. **Same hvac.py contention — see above.** |
| `presence.py:2771` "Failed to seed census count" | per-tick on persistent raise | Same class. Not observed. |
| `energy_battery.py`, `energy_tou.py`, `notification_manager.py`, `optimization.py` warnings | bounded | All either one-shot (boot, restore, register-webhook) or per-user-action. OK. |

**No new cards spawned** per operator directive ("fix LOW/MEDIUM
in-cycle, do not spawn cards"). The hvac.py + energy.py per-tick items
above are the residual sibling candidates — the fix pattern is
identical (per-key latch + release-edge discharge) but I did not touch
`hvac.py`, `energy.py`, or `perimeter_alert.py` in this cycle:

- `hvac.py` is under active edit by another agent (per orchestrator
  brief) — flagged so the merge sequencer picks up the follow-up.
- `energy.py` is not in the current-edit list but a DynamicPreset
  eval-failed edge-trigger is a design decision (per-error-key vs
  per-zone) I did not want to make solo in a hotfix.

## Files touched

- `custom_components/universal_room_automation/domain_coordinators/presence.py` (D1)
- `custom_components/universal_room_automation/coordinator.py` (D2 helpers + call sites + latch state)
- `custom_components/universal_room_automation/domain_coordinators/_dutycycle_notify.py` (D2 — NEW small module)
- `custom_components/universal_room_automation/sensor.py` (D2 diagnostic surface)
- `custom_components/universal_room_automation/camera_census.py` (D3)
- `quality/tests/test_recorder_bloat_logflood.py` (NEW — 8 tests)

Files intentionally NOT touched (concurrent-edit contention flagged in
the brief): `__init__.py`, `coordinator_diagnostics.py`, `hvac.py`,
`safety.py`, `manager.py`, `security.py`, `hvac_egress.py`.

## Recommendation to operator — `recorder:` retention (OUT of URA scope)

The URA-side fixes above eliminate the emitter volume. For the
mirror-side (recorder growth per event, independent of log volume), the
following are candidates for `configuration.yaml`:

```yaml
recorder:
  exclude:
    entity_globs:
      # URA per-tick diagnostic sensors that get re-written every eval
      # even when nothing changes (each write = one recorder row):
      - sensor.*_last_automation_trigger
      - sensor.*_time_since_motion
      - sensor.*_timeout_remaining
      # State-history value: LOW; frequency: HIGH; state churn: HIGH.
    event_types:
      - call_service   # very high volume; keep only if needed for audit
```

Operator-applied; DO NOT edit these here. Re-measure DB growth 24 h
after the URA emitter fixes ship — if the recorder file is still
growing >2 GB/day, retention config is the next lever.

## Mutation drill (D2 helpers)

Two-direction proof of behavioural coverage:

- Neutered `notify_warn_on_enter`'s `if sensor in active:` guard
  (replaced with `if False:`): `test_dutycycle_notify_silent_while_stuck`
  FAILED with a per-tick flood, other 7 passed. Restored → 8/8 green.
- Neutered `notify_release`'s `active.discard(s)` (replaced with
  `pass`): `test_dutycycle_notify_release_emits_info_and_rearms` FAILED
  (re-engage stayed silent because latch never cleared). Restored →
  8/8 green.

## Test result

`PYTHONPATH=quality python3 -m pytest quality/tests/test_recorder_bloat_logflood.py -v` → 8 passed.

The full-suite run is intentionally NOT executed here (orchestrator
runs the serial name-diff centrally per brief).
