# v5.103.26 — boot event-loop-freeze diagnosis (DRAFT)

**Status:** NOT DEPLOYED — held for operator go.
**Branch:** `feature/boot-freeze-watchdog`.

Two diagnostic-only cards. No automation behavior changes: the watchdog
only observes the loop, and the DB wait-warning rework is logging-only.

## Cards

### BOOT-EVENT-LOOP-FREEZE-1 — loop-stall watchdog

- New module `custom_components/universal_room_automation/domain_coordinators/_loop_stall_watchdog.py`.
- Installed once per HA process from `async_setup_entry` (guarded via
  `hass.data[DOMAIN]["_loop_stall_watchdog"]`), so all ~43 room entries
  share one daemon thread.
- Daemon pings `hass.loop.call_soon_threadsafe(_beat)` every
  `PING_INTERVAL_S=2.0s`. If no heartbeat for `STALL_THRESHOLD_S=10.0s`:
  logs ONE WARNING with a formatted main-thread stack (from
  `sys._current_frames()`, trimmed to the last `STACK_TRIM_FRAMES=40`
  frames). When the beat resumes, logs ONE recovery line with the
  total stall duration.
- Boot vs steady state: within `BOOT_WINDOW_S=300.0s` of install the
  warning still logs, but no NM alert fires. In steady state the
  watchdog additionally schedules one `fire_stuck_signal(kind=
  "event_loop_stall", key=("main",))` NM emit per episode (REUSED
  path — `_stuck_signal_nm.py:165`).
- Teardown: stopped on `EVENT_HOMEASSISTANT_STOP` and on the last URA
  entry unload (idempotent `uninstall`). No lingering threads in
  tests.
- Knobs: all four are module constants (rung 1 — diagnostic protocol
  windows, not operator policy). Kill-switch: `BOOT_WINDOW_S=0`
  removes the NM suppression during boot.

### DB-WAIT-WARNING-REWORK-1 — episode-based wait logging in `database.py`

- Replaces the per-waiter `_LOGGER.warning("DB write worker slow: ...")`
  at former line 434 with an **episode-latched** emit:
  - ONE WARNING at the moment the FIRST waiter crosses
    `DB_WRITE_READY_SOFT_WARN_S`, worded
    `DB write not yet served after X.Xs (classification=<stall|backlog>,
     queue_depth=N, phase=<boot|steady>)`.
  - Classification: `"event-loop stall"` when `elapsed >= 2 * soft`,
    else `"worker backlog"`.
  - Phase: `boot` (first 300s from DB construction) logs INFO; steady
    state logs WARNING.
  - ONE summary INFO line when the last waiter clears:
    `DB write wait episode cleared (max_wait=X.Xs, peak_queue=N,
     callers=N, dropped=N)`.
- No change to queue depth, soft/hard timeouts, drop semantics, or
  connection lifecycle — behavior on the connection contract is
  byte-identical.

## Test summary (all green on branch, local run)

12/12 new tests pass:

- `quality/tests/test_loop_stall_watchdog.py` — 7 tests:
  - `test_stall_episode_emits_one_warning_then_recovery`
  - `test_boot_window_suppresses_nm`
  - `test_install_is_single_instance_across_many_entries` (single
    thread across 43 installs)
  - `test_uninstall_stops_thread`
  - 3 mutation drills (per-episode latch, single-instance guard, stop):
    each turns a named test red; restore reproduces byte-identical
    source.
- `quality/tests/test_db_wait_episode_logging.py` — 5 tests:
  - `test_many_waiters_produce_one_warning_and_one_summary` (23
    waiters -> 1 WARNING + 1 summary)
  - `test_stall_vs_backlog_classification`
  - `test_boot_window_downgrades_warning_to_info`
  - `test_summary_carries_dropped_count`
  - 1 mutation drill on the episode-latch site.

Wider `-k "database or setup or unload"` run: 239 passed, 7 failed —
all 7 pre-existing on `origin/develop` (verified by re-running with our
changes stashed; same 7). None touch database.py or the watchdog.

## Live acceptance criteria (post-restart, populated by validator)

| # | Criterion | Expected observed evidence |
|---|-----------|---------------------------|
| L1 | Watchdog installed exactly once | System log contains exactly ONE `Loop-stall watchdog started` line for the restart. |
| L2 | One stall WARNING with a main-thread stack | If the boot freeze recurs: exactly ONE `Event loop stalled >= 10.0s` WARNING per stall episode, followed by a `Main-thread stack:` block whose innermost frame names a URA file:line. Followed by exactly ONE `Event loop recovered after stall (total_stall=X.Xs)` line. Boot episode logs but does NOT fire NM. |
| L3 | DB wait episode logging is one-per-episode | For each boot event-loop freeze: exactly ONE `DB write not yet served after X.Xs (classification=..., queue_depth=..., phase=...)` line + ONE `DB write wait episode cleared (max_wait=..., peak_queue=..., callers=..., dropped=...)` line. In particular the ~23 per-waiter `DB write worker slow: ...` lines from v5.103.24-era boots are GONE. |
| L4 | No lingering thread on unload/removal | If URA is removed or reloaded such that no entries remain: `Loop-stall watchdog stopped` appears; `threading.enumerate()` (via py_profile) shows no thread named `ura_loop_stall_watchdog`. |
| L5 | No automation regression | No new WARNING/ERROR lines from `hvac`, `presence`, `energy`, `safety` domains attributable to this diff. |

## Not done / deferred

- README v5.103.24 line 309 "boot-time DB pool warm-up" text: the
  operator task references this string, but `docs/readmes/README_v5.103.24.md`
  on `origin/develop` does not contain it. Nothing to correct in-place;
  future READMEs should describe the boot freeze as an event-loop stall,
  not a "DB pool warm-up" (there is no DB pool — there is a single
  serial write worker whose queue drains once the loop recovers).
