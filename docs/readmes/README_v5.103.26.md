# v5.103.26: room settings dialogs cleaned up, Fan Mode on the Controls card, and a watchdog that names what freezes HA at boot

**Status:** deployed 2026-09-29 (install only; HA restart held until the house is awake — guest in house, no night restart).
**Operator go:** "Ship the next version" (2026-09-29).

**Cards:** `ROOM-DIALOGS-USABILITY-SWEEP-1`, `BOOT-EVENT-LOOP-FREEZE-1`, `DB-WAIT-WARNING-REWORK-1`, plus the Fan Mode placement fix and two label fixes (tail of `HVAC-FANS-IGNORE-ROOM-COMFORT-FAN-SWITCH-1`).

## User-facing changes

- **Room settings dialogs (all room steps, config + options, incl. collapsible groups):** every field has a plain label (no raw key names, no repeated units) and a short helper (≤ 220 characters); the Empty-room hold day/night texts went from 770/433 characters to one or two sentences, with the per-room-type defaults moved to one note at the top of that group. Enforced by a meta-test (`quality/tests/test_room_dialog_strings.py`) that fails on any raw label, missing helper, or over-long helper.
- **Accuracy fixes found in review:** the room electricity-rate helper now says what the code does (room rate, else house rate, else default — no time-of-use); the day hold says "day and evening".
- **Labels:** `comfort_fan_away_veto_enabled` → "Comfort fan off when away"; `ble_hold_cap_enabled` → "Limit phone-only occupancy", both with helpers.
- **Fan Mode select** now sits in the room device page's **Controls** card (no entity category), where Climate Automation was. The 43 retired Climate Automation switch entities were removed from the registry on 2026-09-29 (operator request).

## Diagnostics (no automation behaviour change)

Two diagnostic-only cards: the watchdog only observes the loop, and the DB wait-warning rework is logging-only.

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
| L6 | Fan Mode in Controls | Room device page (e.g. Guest Bedroom 2) shows Fan Mode under Controls; registry entry `select.guest_bedroom_2_guest_bedroom_2_fan_mode` has `entity_category` null. |
| L7 | Dialog strings live | Room options > Climate & Fans shows plain labels and short helpers (no `comfort_fan_away_veto_enabled` / `ble_hold_cap_enabled` raw keys). |
| L8 | HVAC + Energy return to correct state after the restart (operator ask) | House state after boot settles matches pre-restart; zone presets match the house state (no zone written to Home/Away by the boot walk); Energy battery reserve / TOU mode / EVSE state match pre-restart snapshot. |
| L5 | No automation regression | No new WARNING/ERROR lines from `hvac`, `presence`, `energy`, `safety` domains attributable to this diff. |

## Not done / deferred

- README v5.103.24 line 309 corrected on develop (66950d1cf): it is the per-boot event-loop freeze, not a DB pool warm-up.
- The house-state restore/override cycle (v5.103.27) is NOT in this release; it is in three-framing review.

## Validated 2026-09-30 (restarts 07:46 and 08:00)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1/L2 | Watchdog installed; one stall WARNING with a main-thread stack | PASS | 07:48:23 `Event loop stalled >= 10.0s (phase=boot)` + stack ending `bayesian_predictor.py:743 scan_data_quality`; 07:50:44 `recovered after stall (total_stall=153.3s)`. Named the root cause (fixed v5.103.28). |
| L2 (post-fix) | No stall on the 08:00 restart | PASS | no `Event loop stalled` line; HVAC boot-settle released 08:02:41 (~2.3 min after restart vs 5-9 min before) |
| L6 | Fan Mode in Controls | not re-checked live | registry change applies on load; verify on device page |
| L8 | HVAC + Energy return to correct state | PASS | 07:46 snapshot vs post-boot: battery reserve 19, self_consumption, charge_from_grid on, TOU off_peak unchanged; strategy sensor `unknown` for ~2 min while the Envoy was unavailable, then `self_consumption`. Zones 1-2 unchanged; zone 3 Back Hallway home<->away = its known vacancy flap, not boot-caused. |
