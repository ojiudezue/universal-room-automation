# OC-REEMIT-DEDUP — Review B (async / lifecycle / restart / DB write path)

Branch `fix/oc-reemit-dedup` @ 2b4a058a8; base = merge-base(develop) e00454adc. Static review, no tests run.

## Findings

| # | SEV | file:line | Class | Finding |
|---|---|---|---|---|
| B1 | MEDIUM | optimization.py `_filter_unchanged_repeats` (~5185) + `_filter_repeat_sensor_health` mirror (~5138-5144) vs `_persist_findings_batch` 5216-5236 | Stamp-before-commit | Both filters stamp "persisted" BEFORE the tripwire check, the `database is None` return, and the `log_findings_batch` try/except. A dropped or failed write is recorded as persisted. For `cycle_ok` (description is always the literal `"cycle_ok"`, 1148) this means if the first post-restart cycle's write is dropped (DB not ready, tripwire suspended, exception), NO META row lands for the whole uptime. For never_fires the false stamp is now written to the Store, so a restart no longer heals it (before this change, restart re-persisted). Fix: stamp only after a successful write (collect keys, commit after `log_findings_batch` returns), or roll back on drop/failure. |
| B2 | MEDIUM | optimization.py `_filter_unchanged_repeats`; database.py 6571-6590 (prune: low/medium 7d) | Retention × dedup | No periodic re-assert. `sensor_health` has the 24h `OPTIMIZER_SENSOR_HEALTH_REPERSIST_INTERVAL_S`; the new filter has none. META is severity low, so with uptime over 7 days the pruner deletes the only `cycle_ok` row and the table carries no liveness at all. An unchanged prediction_accuracy finding (low/medium) also disappears after 7d while still active. Fix: re-persist when the last write is older than the existing 24h interval constant (keep `(fp, ts)` instead of `fp`). |
| B3 | LOW | optimization.py 1186-1194 | Stale comment | The skip-path comment says "META sentinel will still persist ... liveness signal lands in the table". After this change that holds only on the first cycle per boot. Update the comment. |

## Cleared

- **Writes only go down.** Both filters only remove rows from the batch; there is still one `log_findings_batch` call per cycle and no new DB call sites. The never_fires `last_persisted` field rides the existing whole-blob Store save (120s debounce at the evaluator cadence, 2745-2747), so nothing new goes to the SQLite write queue. The 2026-06-09 flood shape (per-row/per-cycle writes) does not reappear.
- **Store save timing.** The filter sets `_never_fires_dirty` (5144). The next evaluator pass schedules the debounced save, and teardown always flushes (980-996), so a graceful stop or reload persists the stamp. A crash inside the debounce window loses it, and the row then re-persists once. That is the old behaviour, so it fails open.
- **Clearing on fire.** On a fire, `last_persisted=None` (2347) and the dirty flag (2353) keep the RAM and Store copies consistent.
- **Load order.** `_sensor_health_last_persisted` is set up in `__init__` (650) before the Store load re-seeds it (2147). A bad or missing ISO stamp means no seed, so it fails open.
- **Reload/unload.** `_persist_on_change_last` is RAM state built in `__init__`, so each reload costs one duplicate META row plus at most one prediction row. That is acceptable and in fact wanted, because it gives a boot-liveness row.
- **First post-restart cycle is written.** The cache is empty, so the rows persist. The exception is the drop case in B1.
- **Consumers of the table.** The only DB readers are `get_recent_optimization_findings` at optimization.py:790 (rate-cap plus LLM boot seed, limit 200) and optimization_llm.py:519 (premium-call seed that filters on `created_by=tier2_llm`). Neither needs a row every cycle. With fewer rows, the boot seed's 200-row window just reaches further back in time, which is harmless. I found no staleness or max(timestamp) health check on these rows in custom_components, scripts or quality.
- **Notify, scoreboard, `_last_findings`.** The filter sits only at the persistence layer, so these still see every cycle.

## Verdict: FIX-REQUIRED (MEDIUM). Must-fix: B1, B2. Fix B3 in the same pass.

## Fix-up (2026-10-23)

| Finding | Fix | Test | Drill (neuter site -> named test) |
|---|---|---|---|
| A1/B2 no re-persist interval | `_persist_on_change_last` now stores `(description, ts)`; unchanged row re-persists once older than the REUSED `OPTIMIZER_SENSOR_HEALTH_REPERSIST_INTERVAL_S` (24h, same semantics; no new constant) | `test_ocr_fixup_unchanged_meta_repersists_after_interval` (86399 s / 86401 s literals) | interval condition -> `True`: RED |
| A2 clear-then-recur suppressed | new `_prune_persist_on_change(findings)` called in `_run_cycle_body` right after `_cap_findings` on the FULL evaluated list (not inside `_persist_findings_batch`: the skip-path META-only batch and the LLM batch are partial and would spuriously clear) | `test_ocr_fixup_cleared_then_recur_same_text_repersists`; wire-in anchor `test_ocr_fixup_cycle_body_prunes_cleared_on_change_entry` (drives `_run_cycle_body`) | prune `pop` -> `pass`: RED; prune CALL removed: RED |
| A3/B1 stamp-before-commit | both filters collect stamps into a list; new `_commit_persist_stamps` applies them only after `log_findings_batch` returns a truthy count (the DAO swallows insert errors and returns 0, so an exception is not the only failure). Tripwire drop / no DB / raise / 0 leave no stamp. The never_fires Store `last_persisted` mirror moved into the commit. Direct filter calls (stamps=None) stamp immediately (pre-existing unit tests). | `test_ocr_fixup_failed_write_leaves_no_stamp`, `test_ocr_fixup_tripwire_drop_leaves_no_stamp`, `test_ocr_fixup_never_fires_stamp_not_set_on_failed_write` | `if written` -> `if True`: RED; on_change deferral -> immediate commit: RED; sensor_health deferral -> immediate commit: RED; never_fires mirror neutered: RED; commit call removed: RED (`test_ocr_cycle_ok_persists_once_not_every_cycle`) |
| A4/B3 stale comment | skip-path comment/log now says the META sentinel is offered for persist and lands on the first successful write of a boot then at most once per interval | n/a (comment) | n/a |
| A5 float noise | not changed (INFO, accepted) | - | - |

Drills: one-step mutate/run/restore script, `__pycache__` cleared, `PYTHONDONTWRITEBYTECODE=1`; `git status` clean of source mutations after. Ran only test_optimization_coordinator.py + test_v5110_optimizer_hardening.py + test_optimizer_reserve_hard_deny.py: the only failures are the same 10 env-shaped failures (MockHassForOpt lacks loop/config) that fail identically at 2b4a058a8.
