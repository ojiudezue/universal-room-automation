# URA v5.5.7 — DB space reclamation: nightly incremental vacuum + supervised activation VACUUM

URA's SQLite DB file plateaued at ~900 MB: the nightly prune keeps the *logical* size stable, but there was **no VACUUM anywhere**, so SQLite never returns freed pages to the OS — the file is a high-water mark of reclaimable empty pages, making Samba I/O and boot catch-up heavier. This cycle adds page reclamation in two safe parts.

## What ships (Tier 2-DB)
- **Part 1 — nightly `incremental_vacuum` (inert until activated).** A bounded `incremental_vacuum(max_pages)` step (cap `_INCREMENTAL_VACUUM_MAX_PAGES = 2000`) is folded into BOTH existing nightly maintenance schedules (`__init__.py` `_nightly_db_maintenance` + `_nightly_maintenance_deferred`), running through the single-writer worker. It **no-ops (returns 0) until `PRAGMA auto_vacuum = INCREMENTAL`** is active — so on the current `auto_vacuum=NONE` DB it does nothing harmful. `auto_vacuum=INCREMENTAL` is now set BEFORE the WAL pragma at the connection-init sites (ordering matters — set after WAL it silently locks to 0).
- **Part 2 — supervised one-shot activation VACUUM (operator-triggered).** `auto_vacuum=INCREMENTAL` only takes effect on an existing DB after one full `VACUUM`. The new **`button.ura_coordinator_manager_vacuum_database`** runs `vacuum_full_supervised()`: flush pending writes → **stop the write worker** (so nothing contends the file) → `wal_checkpoint(TRUNCATE)` → back up to `.prevacuum.bak` → VACUUM on a dedicated `aiosqlite` connection (timeout 600 s, busy_timeout 600 000) → integrity check → **restart the worker in a `finally`** (always, even on error). Re-entrancy guarded by `_vacuum_in_progress`.
- **Why deploying this is low-risk:** Part 1 is inert until Part 2 runs, and the `auto_vacuum` init pragma is harmless on the existing NONE-mode DB. **Nothing changes on deploy** — the ~900 MB reclaim happens only when you press the button, once, at a moment you're watching.

## Review — Tier 2-DB (3 framing-disjoint)
A (data integrity / incremental path) + B (full-VACUUM supervision / worker pause / WAL ordering) + C (test authority). Three HIGHs from the first pass — missing op in the deferred schedule, worker not paused during VACUUM, WAL-ordering untested — all fixed and re-verified (worker stop/restart-in-`finally`, both schedules carry the op, WAL/auto_vacuum ordering test added). Ledgers: `docs/reviews/code-review/db_vacuum_review{A,B,C}_*.md`. Cycle tests 21/21; full suite zero new regressions.

---

## Shipwatch acceptance hypotheses (state oracle: HA recorder + `sensor.ura_coordinator_manager_db_size` + button entity)

**Immediate (post-restart — deploy is inert):**
- **H1 — button entity exists.** `button.ura_coordinator_manager_vacuum_database` is present (CONFIG category). Window: post-restart.
- **H2 — nightly incremental is wired but inert.** Both nightly maintenance schedules carry the `incremental_vacuum` op; on the current `auto_vacuum=NONE` DB it returns 0 (no page reclaim, no error). DB file size unchanged by deploy. Window: post-restart + first nightly maintenance.
- **H3 — no new URA errors / no write-worker disruption** at boot from the `auto_vacuum` init pragma. Window: post-restart.

**Delayed (operator presses the VACUUM button — the headline):**
- **H4 — supervised VACUUM activates incremental mode and reclaims space.** After one button press: `PRAGMA auto_vacuum` becomes `INCREMENTAL (2)`, the DB file shrinks materially from ~900 MB, `integrity_check` returns `ok`, a `.prevacuum.bak` is written, and the write worker resumes (writes flow again, no `>120s` guard trip). Signal: `sensor.ura_coordinator_manager_db_size` drops; button completes without error. Window: when the operator triggers it. Thereafter the nightly incremental keeps the file lean.

## Live Validation — PROSPECTIVE (write back after restart, then after the button press)
| # | Criterion | How |
|---|---|---|
| L1 | Deploy healthy / inert | v5.5.7 installed; button entity present; DB size unchanged; zero new errors |
| L2 | Nightly op wired (H2) | both schedules include `incremental_vacuum`; returns 0 on NONE-mode DB |
| L3 | Supervised reclaim (H4) | after button press: auto_vacuum=INCREMENTAL, db_size drops, integrity ok, `.prevacuum.bak` exists, worker resumes |
