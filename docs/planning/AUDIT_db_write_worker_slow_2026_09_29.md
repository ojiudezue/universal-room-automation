# AUDIT — "DB write worker slow: no connection after 35.0s" (2026-09-29)

Read-only. Trigger: v5.103.25 restart ~19:17 CDT, ~24 identical WARNINGs from `database.py:434-438`.
Operator question: are we hitting DB contention again after the DB surgery?

## Verdict (one line)
**Not a DB regression. The DB write path is healthy; the warning is a *symptom* of a ~140 s whole-event-loop
freeze that happens on EVERY HA boot (12 of 12 measured restarts, 09-25 → 09-29).** The log wording
("no connection") misdirects to the DB. The loop freeze is the real problem, and its cause is still unknown (see §3).
The README_v5.103.24 description ("boot-time DB pool warm-up", line 309) is **wrong**: URA has no pool, and nothing warms up.

## 1. Prior art: what the DB surgery was meant to guarantee
| Cycle | Invariant |
|---|---|
| v3.22.8 | Single-writer: every write goes through one `asyncio.Queue` and one persistent connection (`database.py:134-138, 185-227`). Reads use short-lived WAL connections (`:470-480`). |
| v4.2.8 / Bug Class #25 | No unbounded DELETE inside the write queue (batched LIMIT and yield). |
| v5.2.2 (optimizer write-flood incident) | Per-cycle producer write volume is O(1). Batch DAOs; no per-room burst. |
| v5.5.7 | `auto_vacuum=INCREMENTAL` plus a nightly `incremental_vacuum` through the worker. The "bloat" premise was refuted: the DB is live data. |
| v5.16.2 | Lossless across worker gaps: writes buffer on the queue before and between worker runs (`:342-346`). |
| backlog #13 (`docs/reviews/code-review/db_write_lossless_timeout_tier2db.md`) | Soft-warn at 35 s, hard cap at 300 s (`:65-67`). Late rows land instead of being dropped. The worker never abandons a connection that a caller still holds (the done-invariant, `:358-384`). |

**Every one of these held on 09-29.** There were 0 `row dropped`, 0 `caller holding connection`, 0 `connection lost` and 0 `drained` lines.
The queue peaked at 24 and drained as soon as the loop resumed.

## 2. Producer: what the warning actually measures
- The worker opens **one** connection when it starts and keeps it (`:194-208`). The caller in `_db()` enqueues `_execute` and
  waits on `ready`. `ready` is set only when the worker **reaches that caller's item** (`:355-357, 421-431`).
- So "no connection after 35 s" really means "my item has not been served yet". That can be head-of-line blocking
  behind slow items, **or** the timer firing late because the event loop was frozen. The message cannot tell these apart.
- **Discriminator already in the line:** `elapsed=150.9–157.7s` against `soft=35.0s`. A 35 s `asyncio.wait` timeout
  that returns after about 155 s means the loop did not run for about 120 s. DB slowness cannot produce that.
- Boot DB work: `initialize()` (`:550+`) only runs `CREATE ... IF NOT EXISTS` plus PRAGMAs through aiosqlite, which runs in its
  own thread. There is no synchronous `sqlite3` anywhere in URA (grep clean). `integrity_check` runs only in the supervised
  VACUUM button (`:9238`). Nothing in the boot DB path can freeze the loop.

## 3. Measurement
**Log (supervisor ring buffer, 14:17 → 19:52 on 09-29; only the 19:17 restart is in range):**
- 19:17:23–25: `DB write queue peak` 14 → 20 → 24 (`:225`).
- **19:17:26.847 → 19:19:55.494: zero log lines from any logger or thread for 148.6 s.** When logging resumes,
  every loop-dependent integration complains at once: Meross "154 seconds behind HA", ElkM1 heartbeat timeout,
  MQTT "No ACK in 10 s", the Protect websocket drops, and alexa_media/esphome "setup taking over 10 s".
- 19:19:57.698–.700: 23 URA WARNINGs within 2 ms, each with `queue_depth=23`. That is one line per parked caller.
- After that, no slow-worker line for the rest of the window, and none between 14:17 and 19:16 (steady state is clean).
- Bootstrap stage-2 timeout at 19:21:51; "Something is blocking HA from wrapping up" at 19:27:07.
- The last line before the freeze and the first line after it are both URA Living Room `FanPolicyOracle fallback read_on`
  (`automation.py:337`). This is **suggestive only, not proof**. It is pure-Python dict and state code with no obvious blocking call.

**Recorder probe across all restarts (`states.last_updated_ts`, largest gap in the 20–1500 s window after each
`homeassistant_stop`; recorder retention reaches back to 09-25):**

| stop (CDT) | largest gap | at stop+ | 2nd gap | `homeassistant_start` at |
|---|---|---|---|---|
| 09-25 18:05 | 156 s | 61 s | – | +355 s |
| 09-26 12:49 | 139 s | 78 s | – | +342 s |
| 09-26 15:15 | 141 s | 245 s | 118 s @100 | +819 s |
| 09-27 10:33 | 133 s | 84 s | – | +321 s |
| 09-27 20:33 | 148 s | 106 s | 140 s @1129 | +388 s |
| 09-27 20:50 | 140 s | 75 s | – | +346 s |
| 09-27 22:15 | 144 s | 75 s | – | +351 s |
| 09-28 18:45 | 141 s | 258 s | 119 s @100 | +530 s |
| 09-28 19:16 | 142 s | 65 s | – | +352 s |
| 09-28 23:36 | 152 s | 55 s | – | +329 s |
| 09-29 03:01 | 142 s | 113 s | – | +381 s |
| 09-29 19:15 | 148 s | 93 s | – | +658 s |

Outside these windows the gaps are ≤ 7 s. The 133–156 s freeze is **deterministic, on every boot, and roughly constant in length**.
It adds about 2.5 min of dead house to every restart (about 3/day lately) and is the likely driver of the stage-2 timeouts.
A near-constant duration points to one fixed synchronous job rather than contention. Host: 11.7 GB RAM with 684 MB swap in use, which is not ruled out.
- DB on the mount: `universal_room_automation.db` is **1.35 GB** (884 MB after the VACUUM on 06-19, so +52% in about 3 months). WAL is 4.1 MB and SHM 32 KB, both healthy.
  This is not causal here, but the growth trend is unmeasured.

## 4. Consumers: who fills the queue at boot
There is no per-item tagging, so this is **inferred** from timing. The 23 parked callers enqueued between 19:17:20 and 19:17:27
(elapsed spread 150.9–157.7 s), which matches the per-room first-refresh log burst. The ~40 room coordinators each write
`log_environmental_data` (`coordinator.py:5100`) and `save_room_state` (`coordinator.py:5244`). A depth of 24 is small, and the worker
cleared it within seconds of the loop resuming. Nothing points to a flood producer like v5.2.2.

## 5. Logging critique
1. **Per-caller, not per-episode.** Every parked caller logs its own line (`:434`), so one freeze produces 23+ identical WARNINGs.
2. **Misleading text.** "no connection" suggests the connection is failing. The real state is "not yet served (queue position)".
3. **No stall/backlog classification**, even though `elapsed − soft` gives it away for free.
4. **No recovery line.** Nothing reports total wait, peak depth, callers affected or rows dropped (0) when the episode ends.
5. `DB write queue peak` (`:224-227`) WARNs on every new lifetime peak above 10, which is boot noise.
   The `DB stats` and `worker connection established` lines are INFO, so they are invisible: there is no `logger:` block (see reload-storm memory).
6. There is no boot-vs-steady-state distinction and no trip-wire. A steady-state stall would look exactly like this boot noise.

## 6. Ranked improvements
| # | Change | Rung / size / risk | Falsifiable acceptance |
|---|---|---|---|
| 0 (config) | Operator adds a `logger:` block (`custom_components.universal_room_automation.database: info`). This makes the worker-connect time and `DB stats` durable across restarts. No code. | config, trivial, none | The next restart shows `DB write worker connection established` within 5 s of `Database file:`. |
| 1 | **Find the ~140 s boot freeze.** Add a loop-stall sampler: a daemon thread with a 1 s `call_soon_threadsafe` heartbeat. When the heartbeat is more than 10 s stale, log `sys._current_frames()[main]` once per episode (WARNING). This one change turns "unknown" into a stack trace and also serves as the steady-state trip-wire (feed NM/anomaly when `CoreState.running`). Verify the NM/anomaly API in the plan; it is not verified here. | code, ~70 LoC, **Tier 2** (new thread in the runtime) | The next restart logs one stack captured during the stall. If the frame is outside URA, URA is exonerated and the card moves to the HA/host side. If it is inside URA, that names the site to fix. With no freeze, the sampler logs nothing. |
| 2 | **Reshape the DB wait logging** (`database.py:427-447`). One WARNING per episode (latch plus counter). Report `loop_lag = elapsed − soft` and classify it as `event-loop stall` when lag > 10 s, otherwise `worker backlog`. Replace "no connection" with "not yet served". Emit one summary line when the queue drains: max wait, peak depth, callers, dropped. During boot (`hass.state != running`) use INFO; in steady state use WARNING plus the trip-wire. Raise the `queue peak` WARN floor, or log it once per episode. | code, ~40 LoC, Tier 1 (log-only; the done-invariant is untouched) | Replaying the 09-29 shape in a test (freeze the loop for 150 s with 23 callers) gives exactly 1 WARNING classified as `event-loop stall` and 1 recovery line with `dropped=0`. A backlog-only test (slow factory, live loop) is classified as `worker backlog`. |
| 3 | Tag queue items with the enqueue site (`co_name` captured only when the soft threshold trips), so "top enqueuers" becomes measured instead of inferred. | code, ~10 LoC, Tier 1 | The episode summary lists the top 3 callers with counts. |
| 4 | Correct `docs/readmes/README_v5.103.24.md:309` ("DB pool warm-up") to "boot event-loop freeze, see this audit". | docs, trivial | – |
| 5 | Separate card: measure per-table row growth (884 MB → 1.35 GB since 06-19) against the prune retention windows. | probe, read-only | A per-table MB/week table exists. |

Do **not** raise `DB_WRITE_READY_SOFT_WARN_S`. Its timer fires late during a freeze whatever its value, and the warning is what exposed the freeze.

Limitations: the supervisor log ring buffer holds only about 5.5 h, so the log evidence covers one restart. The recorder gap probe covers 12 restarts.
The freeze's cause is **not established**; the Living Room adjacency is a lead, not a finding.
