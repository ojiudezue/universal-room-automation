# v4.2.22 — Cover Automation Independence + Living Room Straggler Fix

**Date:** 2026-05-03

## Summary

Two related fixes for the room cover automation pipeline:

1. **Cover automation now runs independently of the master room automation switch** (Option A). Previously, turning off `switch.<room>_automation` (lights/fans master) silently disabled `check_timed_cover_open/close` even when `switch.<room>_cover_automation` was ON.

2. **Living Room straggler bug** — Hunter Douglas (and other RF-bridged) hubs accept group `cover.close_cover` calls instantly while individual blinds miss the RF burst. Old code set the daily dedup date on hub-acceptance, locking out retries for the day. New `_send_covers_with_verify` helper sends per-cover with pacing, verifies physical state after settle, and retries only the stragglers.

## Problem

Living Room reported sunset cover close completing at 8:00 PM but 1-2 blinds remained open. Logs showed `cover.close_cover` returning success. Investigation: HA's cover service returns when the hub accepts the call, not when each blind reaches state. RF mesh dropouts on individual blinds were invisible to URA. Combined with `_last_timed_close_date = today` set on service-call success, no retries fired until the next day.

Separately, users with master automation OFF for one room (e.g. Living Room) never got sunset cover close at all — the cover periodic was nested inside `_is_automation_enabled()`.

## Changes

### automation.py
- New `_send_covers_with_verify(cover_ids, action)` helper: per-cover sequential commands with `COVER_PACE_SECONDS=0.3` pacing, `COVER_SETTLE_SECONDS=8.0` post-batch settle, `COVER_MAX_RETRIES=2` straggler-only retries with `COVER_RETRY_BACKOFF_BASE=2.0` backoff (2s, 4s).
- Position-aware verification (`_cover_at_target`): covers with `current_position` attribute use a 5%-tolerance window (`pos<=5` for closed, `pos>=95` for open) instead of state.state alone — fixes false stragglers on partially-open blinds reporting `state="open"`.
- Daily counter reset (`_maybe_reset_cover_counters`) now also clears `_last_cover_failure_time` and `_last_cover_failure_entities`.
- All four cover entry points (`_control_covers_entry`, `_control_covers_exit`, `check_timed_cover_open`, `check_timed_cover_close`) now schedule a verify-and-retry runner as a tracked background task via new `_schedule_cover_runner` helper. `_cover_op_in_flight` flag prevents double-scheduling and is reset on schedule failure.
- Runners use `entry.async_create_background_task` so HA cancels them on entry unload (no leaked self-references).
- Timed runners re-check `is_sleep_mode_active()` before issuing commands (the runner runs ~10s+ after the periodic check).
- Activity log descriptions now report actual outcome (`Closed 5/6 covers — 1 straggler: [cover.lr_3]`) instead of just commanded count.

### coordinator.py
- Cover automation runs in **both** the `elif self._is_automation_enabled():` branch (master ON) and the `else:` branch (master OFF). Master-off path also calls `automation._refresh_config()` and respects `_skip_first_automation`.

### sensor.py
- `AutomationHealthSensor` exposes new attributes: `cover_attempts_today`, `cover_failures_today`, `last_cover_failure`, `last_cover_failure_entities`. Surfaces hub/RF reliability that hub-acceptance service calls would otherwise hide.

## Tests

15 new tests in `quality/tests/test_cover_verify.py`:
- All-success first try (per-cover, not group)
- Straggler recovers on retry
- Persistent straggler increments failure counter, dedup not set
- Unavailable blind not counted as straggler
- Daily counter reset (incl. failure metadata)
- Unsupported action raises
- Open-action target state
- Position-based covers (closed/open/partial/no-position/none)
- Position-based straggler end-to-end
- M3: inner `_safe_service_call` receives `max_retries=0`

Full suite: 1724 passed (was 1709 baseline), 86 failed (same as baseline — pre-existing, unrelated). Zero regressions.

## Review: Tier 1 (1 review, 9 findings, 7 fixed)

| Severity | Found | Fixed | Notes |
|----------|-------|-------|-------|
| CRITICAL | 1 | 1 | C1: in-flight flag leak on schedule failure |
| HIGH | 3 | 3 | H1 untracked tasks → background_task; H2 first-refresh skip in else; H3 position-based covers |
| MEDIUM | 5 | 4 | M1 reset failure metadata; M3 drop inner retry; M4 sleep recheck; M5 activity log outcome. M2 (TZ) acknowledged |
| LOW | 3 | 0 | L1 test gaps partially covered; L2/L3 deferred |

Review doc: `docs/reviews/code-review/v4.2.22_cover_verify.md` (to be persisted post-deploy).

## Deployment Notes

- No config flow changes; no new switches/sensors. All new diagnostics are attributes on the existing `sensor.<room>_automation_health`.
- Affected rooms: any room using sunrise/sunset/timed cover open/close. Living Room (8 blinds), Breakfast Nook, Dining Room called out specifically.
- After deploy, verify on Living Room sunset (~8:00 PM CDT 2026-05-03):
  - All blinds reach `closed` state.
  - `sensor.living_room_automation_health` attribute `cover_failures_today == 0` once fully settled.
  - Log line: `Timed cover close [Living Room]: closing 8 cover(s)` followed (post-settle) by either silence (success) or `did not reach 'closed' after 3 attempt(s): [...]` (persistent failure).
- Verify Option A independence: turn `switch.living_room_automation` OFF, leave `switch.living_room_cover_automation` ON; sunset close should still fire.
