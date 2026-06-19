# Review A — `incremental_vacuum` correctness + nightly wiring + auto_vacuum pragma

**Cycle:** DB space-reclamation (Part 1) · **Branch:** `feature/db-incremental-vacuum` (c733acdb, off develop)
**Framing:** `incremental_vacuum` CORRECTNESS + nightly-schedule wiring + `auto_vacuum` pragma ordering
**Reviewer A** of a Tier-2-DB (3 framing-disjoint) review. No code edits, no checkout.

---

## Findings

### ✅ 1. `incremental_vacuum` is bounded — cannot block core writes
- `_INCREMENTAL_VACUUM_MAX_PAGES = 2000` (`database.py:6804`).
- Clamp: `max_pages = max(1, min(int(max_pages), self._INCREMENTAL_VACUUM_MAX_PAGES))` (`database.py:6824`). A caller-supplied `max_pages` (or `None`) can never exceed 2000. Test `test_bounded_page_count` (`test_db_incremental_vacuum.py:215`) proves a 10M request is clamped.
- `PRAGMA incremental_vacuum(N)` reclaims at most N pages from the freelist; SQLite further caps N at freelist size.
- **Worst-case duration estimate:** 2000 pages × 4096 B = ~8 MB moved/truncated. Even on the Samba-mounted DB this is sub-second to low-single-digit seconds — trivially under the 120s `_db()` guard (`database.py:234`) and the 5-min nightly budget. This is the explicit fix for the v5.0.0 unbounded-write failure mode. **PASS.**

### ✅ 2. No-op guard is correct and can't error
- Reads `PRAGMA auto_vacuum`, `mode = row[0] if row else 0`, returns 0 if `mode != 2` (`database.py:6832-6842`). Null-safe (`if row else`). Wrapped in `try/except Exception` (`database.py:6860`) → returns 0 on any error. Inert on the existing NONE-mode (0) DB until Part 2. Test `test_noop_when_auto_vacuum_not_incremental` (`:181`) covers it. Secondary guard `if free_before <= 0: return 0` (`:6850`). **PASS.**

### ✅ 3. Runs through the single write worker (no rogue connection)
- `async with self._db() as db:` (`database.py:6829`). `_db()` (`:208`) enqueues onto `_write_queue` processed by the one persistent-connection worker (`:72`, `:81`) — serialized with all other writes. `vacuum_full_supervised()` correctly uses a *separate dedicated* connection (`:6920`), which is appropriate since VACUUM needs exclusive access — but that method is button-only, out of this framing's scheduled-path concern. Test `test_runs_through_worker_path` (`:228`). **PASS.**

### ❌ 4. Nightly wiring — MISSING from the deferred path (`_cleanup_ops_d`)
- Present in primary `_cleanup_ops`: `("incremental_vacuum", "incremental_vacuum", {})` at `__init__.py:1189`. ✅
- **ABSENT from `_cleanup_ops_d`** (`__init__.py:1278-1295`) — the deferred-startup maintenance list. The last entries there are `optimization_findings` / `optimization_daily_digest` (`:1293-1294`); no `incremental_vacuum` tuple.
- **Impact:** the deferred path (`_nightly_maintenance_deferred`, `:1297`) registers the *same* 2:30 AM `async_track_time_change` and is the ONLY nightly maintenance that runs when a room config-entry wins the DB-init race and the primary block's `unsub_nightly_maintenance` is never set (guard at `:1262`). On those boots, **`incremental_vacuum` never runs** post-Part-2-activation, and freed pages are never returned to the OS — silently defeating the cycle's purpose on an unknown fraction of restarts.
- **Test gap:** `test_incremental_vacuum_in_nightly_ops` (`test_db_incremental_vacuum.py:388`) only asserts the string is in `_init_src()` — it matches the primary-list occurrence and gives false confidence; it does NOT assert presence in `_cleanup_ops_d`.
- **SEVERITY: HIGH.** **Fix:** add the same tuple to `_cleanup_ops_d` after `:1294`, and extend the test to assert TWO occurrences (or assert per-list).

### ⚠️ 5. auto_vacuum-before-WAL ordering — correct, with one residual note
- Worker init: `PRAGMA auto_vacuum=INCREMENTAL` (`database.py:92`) precedes `PRAGMA journal_mode=WAL` (`:94`). ✅
- `initialize()`: `PRAGMA auto_vacuum=INCREMENTAL` (`:363`) precedes `PRAGMA journal_mode=WAL` (`:365`). ✅
- Correctly placed before any table creation in `initialize()`. On an existing NONE-mode DB the pragma is silently inert (no error), so it doesn't break existing connection setup — confirmed by `test_converts_and_shrinks_and_backs_up` round-trip (`:250`).
- **Residual note (LOW):** the worker auto-reconnects on failure (`:79` loop), re-issuing `auto_vacuum=INCREMENTAL` each reconnect against an already-WAL existing DB. This is a harmless no-op (auto_vacuum can't change on a non-empty DB without VACUUM), but worth a one-line comment that the reconnect re-issue is intentional/inert. **No functional defect.**
- `_flush_pending_writes()` (`:131`) opens its own connection and does NOT set `auto_vacuum` before WAL (`:142-143`); harmless because it only flushes to an existing DB (never the fresh-file case), but inconsistent. **LOW.**

### ✅ 6. 5-min budget + ordering respected
- The op is the LAST entry in `_cleanup_ops` (`__init__.py:1189`), so prunes run first and free pages before reclamation — correct ordering. The budgeted loop checks `> 300s` break (`:1206`) and `await asyncio.sleep(1.0)` between ops (`:1217`) applies uniformly. Rotating `_nightly_start_idx` (`:1199`) means on a budget-truncated night the vacuum still gets fair rotation. **PASS** for the primary path (subject to finding #4 for the deferred path).

---

## Summary

`incremental_vacuum` itself is correct, bounded, null-safe, serialized through the single writer, and inert until Part-2 activation — it cannot reproduce the v5.0.0 watchdog failure. The auto_vacuum-before-WAL ordering is right at both init sites. **One real defect:** the op is wired into the primary nightly list but **MISSING from `_cleanup_ops_d`** (`__init__.py:1278-1295`), the deferred-startup path that is the sole nightly maintenance on DB-init-race boots — and the membership test (`:388`) is too loose to catch it. This means on some restarts reclamation never runs after activation. Two LOW consistency notes (`_flush_pending_writes` pragma ordering; reconnect re-issue comment).

**VERDICT: REQUEST CHANGES.** Fix HIGH #4 (add tuple to `_cleanup_ops_d` + tighten test to assert both lists) before deploy. LOW items may be folded into the same fix-up pass per the fix-LOWs-in-cycle policy.
