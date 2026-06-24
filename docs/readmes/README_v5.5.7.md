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

## Live Validation — Validated 2026-06-19 (post-restart; reclaim pending operator button press)
| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Deploy healthy / inert | **PASS** | `update.universal_room_automation_update` installed_version `v5.5.7`; button entity present (actual id `button.ura_coordinator_manager_vacuum_database_one_time_supervised`, state `unknown`); `sensor.ura_coordinator_manager_db_size` = **900.65 MB (unchanged)** — confirms inert deploy; zero URA ERROR entries in system log at boot |
| L2 | Nightly op wired (H2) | **code-proven; inert confirmed** | both schedules carry `incremental_vacuum`; no-op on the current `auto_vacuum=NONE` DB (the unchanged 900.65 MB size is the live evidence of inertness). Runs for real at the next nightly maintenance once incremental mode is active. |
| L3 | Supervised VACUUM ran (H4) | **PASS (mechanism) — premise corrected** | operator pressed the button 2026-06-19 20:30 CDT. Log sequence: backup → `.prevacuum.bak` written → VACUUM → **`integrity_check: ok`**, **`auto_vacuum_after: 2` (INCREMENTAL activated)**, re-entrant presses correctly ignored. Result dict `{'status':'ok','size_mb_before':899.9,'size_mb_after':884.1,'integrity_check':'ok','auto_vacuum_after':2}`. |

### Important finding — the bloat hypothesis was wrong
The supervised VACUUM reclaimed only **~15.8 MB** (899.9 → 884.1 MB), not the hundreds implied by "~900 MB high-water mark of reclaimable empty pages." **The DB is genuinely ~884 MB of *live* data, not bloat** — there were very few free pages to return (the nightly prune had kept it tight). So there is **no large one-time reclaim to be had.**

The durable value is the **`auto_vacuum=INCREMENTAL` activation**, not the one-time shrink: from now on, pages the nightly prune frees are returned to the OS incrementally instead of accumulating into a growing high-water mark. The cycle's mechanism is sound and the activation is the lasting win; the original "~900 MB reclaimable" motivation was a mis-diagnosis. If the file ever does grow with genuine free pages, the nightly `incremental_vacuum` will now trim it without another full VACUUM.

**Note:** the button's live entity_id carries the full friendly suffix `_one_time_supervised` (the README body's shorthand `button.ura_coordinator_manager_vacuum_database` is the unique-id stem, not the resolved entity_id).
