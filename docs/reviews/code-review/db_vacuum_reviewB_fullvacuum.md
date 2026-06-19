# Review B — Supervised full-VACUUM SAFETY (watchdog / corruption / not-unattended)

Branch `feature/db-incremental-vacuum` (c733adb). Framing: can the
supervised `vacuum_full_supervised()` stall the system unattended, or
corrupt the DB? File:line cites against `git show feature/db-incremental-vacuum:<path>`.

## VERDICT (lead)

**Unattended-stall risk: LOW / acceptable.** `vacuum_full_supervised` is
button-only — it is NOT in `_cleanup_ops` nor any `async_track_time_change`
(`__init__.py:1186` schedules only `incremental_vacuum`; the full method is
referenced ONLY from `button.py:1399`). A test asserts the method name is
absent from `__init__.py` source (`test_db_incremental_vacuum.py:393`). It
cannot fire on its own.

**Corruption risk: LOW.** Backup-first-then-abort (`database.py:6933-6951`),
dedicated short-lived connection with 600 000 ms `busy_timeout`
(`database.py:6957-6960`) NOT bounded by the 120 s `_db()` guard, and a
post-VACUUM `integrity_check(1)` (`database.py:6967-6970`). The exclusive
lock is not interruptible by the 120 s guard, so the multi-minute VACUUM
won't be torn mid-write.

**One real gap (HIGH):** the write worker is NOT paused/stopped for the
VACUUM. `_flush_pending_writes()` (`database.py:6925`) only *drains the
queue on a fresh connection* (`database.py:141`) — it neither cancels nor
suspends the persistent worker (`database.py:81-118`; no pause hook exists,
grep §). New writes enqueued during the VACUUM are serviced by the
still-running worker, which will block on the exclusive lock and (worker
conn `busy_timeout=30000`, `database.py:93`) time out after 30 s →
`set_exception` on those futures → callers see `DB write failed`. At
operator-supervised low activity this is tolerable, but it is undocumented
and untested, and on a multi-minute SMB VACUUM a write burst could fail
several callers. See M-FINDINGS.

## MUST-FIX (CRITICAL/HIGH)

- **H1 — worker not quiesced during VACUUM.** `database.py:6952-6963`. The
  drain (`_flush_pending_writes`) empties the queue but the worker keeps
  consuming new items against its open WAL connection. Two issues: (a) any
  write arriving during the VACUUM races the exclusive lock and fails after
  30 s; (b) the worker's *idle-but-open* WAL connection can itself delay the
  VACUUM acquiring the exclusive lock (VACUUM under WAL needs no other
  reader/writer holding a lock). Recommend: pause the worker for the VACUUM
  (a `_vacuum_in_progress`-gated `await`/event in the worker loop, or cancel
  + restart around the VACUUM), so no second connection contends and no
  caller futures fail. At minimum, the planning doc/README must state that
  the operator stops automations / presses at idle, and a test should prove
  worker-concurrent behaviour is bounded (current `_with_worker` test runs
  the worker but only with an EMPTY queue — `test_db_incremental_vacuum.py:125`,
  so the contention path is unexercised).

## SHOULD-FIX (MEDIUM)

- **M1 — flush failure is swallowed, VACUUM proceeds.** `database.py:6925-6930`:
  a flush exception is logged and execution continues. If the flush failed
  because writes are still in-flight, the VACUUM proceeds with a contended
  DB. Low likelihood (button is supervised) but worth narrowing the except.
- **M2 — backup is a live-file `shutil.copy2` of a WAL DB.**
  `database.py:6935-6938`: copying the main DB file while a `-wal` sidecar
  has uncommitted frames yields a backup missing those frames. Acceptable as
  a rollback "floor" (the VACUUM rewrites the file anyway), but the backup is
  not guaranteed crash-consistent; `VACUUM INTO <bak>` or a checkpoint-then-copy
  would be safer. Not blocking.
- **M3 — `.prevacuum.bak` left on disk, never reclaimed.** `database.py:6933`.
  On a 900 MB DB this doubles disk for the file's lifetime. Note in docs that
  the operator deletes it post-verify.

## NICE-TO-HAVE (LOW)

- **L1 — `integrity_check(1)` caps at 1 error.** `database.py:6967`. Fine for a
  pass/fail gate; "ok" is authoritative, a non-ok is a flag to investigate.
- **L2 — double re-entrancy guard** (`_running` on button `button.py:1389`,
  `_vacuum_in_progress` on DAO `database.py:6897`) is belt-and-suspenders, good.
  Note `_vacuum_in_progress` is a CLASS attribute (`database.py:6873`) — fine
  for a singleton DB, but two instances would share it. Not a real config.

## CHECKLIST RESULT

1. NOT in unattended schedule — **PASS** (`__init__.py:1186` only
   `incremental_vacuum`; assert at `test_..:393`).
2. Dedicated conn + high timeout, worker conn not the path — **PASS for the
   conn** (`database.py:6957`, `busy_timeout=600000` `:6960`); **PARTIAL** —
   worker conn stays OPEN/active (H1).
3. Drain-first — **PARTIAL.** Drains queue (`database.py:6925`) but worker
   not stopped → new writes can arrive mid-VACUUM (H1).
4. Backup-first + abort on failure — **PASS** (`database.py:6933-6951`,
   returns `backup_failed` before the VACUUM); see M2.
5. integrity_check + concurrent guard — **PASS** (`database.py:6967`,
   `:6897`; tests `:271`, `:282`).
6. auto_vacuum BEFORE VACUUM (and before WAL on fresh) — **PASS**
   (`database.py:6962` then `:6963`; fresh path `:92` before `:94`).
7. Button: registered (`button.py:53`), CONFIG category (`button.py:1344`),
   re-entrancy guarded (`button.py:1389`), loud WARNING logs + persistent
   notification (`button.py:1404`, `:1410`) — **PASS**.

## SUMMARY (<300 words)

The supervised full VACUUM is fundamentally safe against the two headline
risks. It cannot run unattended — it is button-only, deliberately excluded
from the nightly `_cleanup_ops`/`async_track_time_change` schedule, and a
source-level test enforces that exclusion. It cannot be torn mid-write by the
120 s `_db()` guard because it runs on its own short-lived connection with a
600 000 ms busy_timeout; it backs the DB up to `<db>.prevacuum.bak` first and
aborts if that copy fails; and it integrity-checks afterward. PRAGMA ordering
(auto_vacuum then VACUUM; auto_vacuum before WAL on a fresh file) is correct.

The one substantive gap is H1: the persistent write worker is NOT paused for
the duration of the VACUUM. `_flush_pending_writes` empties the queue but the
worker keeps running on its open WAL connection, so (a) writes enqueued during
the multi-minute VACUUM block on the exclusive lock and fail their callers
after the worker's 30 s busy_timeout, and (b) the open worker connection can
delay the VACUUM acquiring the exclusive lock. At operator-supervised low
activity this is tolerable, but it is untested — the `_with_worker` test runs
the worker only with an empty queue, so the contention path is unexercised.
Recommend gating the worker on `_vacuum_in_progress` (pause-and-resume) and
adding a worker-concurrent test, OR explicitly documenting "press at idle /
stop automations" in the README and accepting bounded write failures.

Must-fix: H1. Should-fix: M1 (swallowed flush error), M2 (WAL-inconsistent
backup), M3 (orphan backup file). No corruption or unattended-stall blocker.
