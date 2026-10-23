# OC-REEMIT-DEDUP — Review A (local correctness + edge cases)

Branch `fix/oc-reemit-dedup` @ 2b4a058a8; base = merge-base e00454adc (develop). Static review; no tests run.

## Findings

| # | SEV | Site | Class | Finding |
|---|---|---|---|---|
| A1 | MEDIUM | optimization.py `_filter_unchanged_repeats` (~5155-5190) + database.py:6571 prune | Suppression needs a discharge / #53 | No re-persist interval. META (`cycle_ok`) and prediction_accuracy are both `severity="low"` (optimization.py:1143, ~4021) → pruned after 7 days (database.py:6583). With no restart for >7d, the table holds ZERO META rows and zero rows for a still-degraded prediction fact, while RAM says "already persisted". Breaks the D5 "sentinels-vs-real-rows" DB liveness check (comment at :1135) and empties the boot seed corpus (`get_recent_optimization_findings`, :789). Fix: reuse the sensor_health shape — store `(desc, ts)` and re-persist when unchanged for >= `OPTIMIZER_SENSOR_HEALTH_REPERSIST_INTERVAL_S` (24h), well under 7d. |
| A2 | MEDIUM | same, `last[key]` never cleared | Concept split (clear vs unchanged) | When the prediction issue CLEARS (evaluator returns no finding), the `_persist_on_change_last` entry survives. A later recurrence with identical text (e.g. `data_quality_pct 42.0% < floor` — fixed at init time, so identical recurrence is likely) is suppressed: the new episode leaves no row. Fix: per cycle, drop keys of on-change dims that were absent from this batch (or fold into A1's interval). |
| A3 | LOW | :5212 filters applied before tripwire/DB-None/exception at :5217-5235 | Stamp-before-commit | Stamp is taken before the write. If the tripwire suppresses the batch, DB is None, or `log_findings_batch` raises, the row is marked persisted but never written → suppressed until description change (indefinitely for META). Pre-existing for sensor_health (24h-bounded there); unbounded here. A1's interval bounds it; otherwise stamp after a successful write. |
| A4 | LOW | :1185-1194 skip-persist path comment | Stale doc | "META sentinel will still persist" / "liveness signal lands in the table" is now false after the first cycle of a boot. Update comment. |
| A5 | INFO | prediction description floats (`:.1f`, `:.3f`) | Float noise | Comparison is exact string; formatted rates drifting by 0.1 re-persist. Not incorrect, just less savings than the 37% measurement implies. Acceptable. |

## Cleared

- never_fires key parity: `_never_fires_persisted_key` (:2214) = `(str(dedup_key), stuck_state)` matches `_filter_repeat_sensor_health` keying (:5124) given emitter `dedup_key=("sensor_never_fires", eid)` (:2822) and payload `entity_id`/`stuck_state` (:2839/:2849). Holds.
- Old store shape: `rec.get("last_persisted")` → None → `_never_fires_seed_persisted_key` returns early (fail-open, re-persist once). Non-str / unparseable → no seed. Holds.
- Recovery clear (:2346) nulls the Store copy alongside RAM pop. Holds.
- Mirror sets `_never_fires_dirty`; teardown flush is unconditional (:990). Holds.
- dict ordering: description is a pre-joined string; dedup_key stringified tuple — deterministic. Holds.
- Kill switch: empty tuple returns input unchanged. Holds.
- Consumers: `_last_findings`, scoreboard, notify, LLM signature (excludes META, optimization_llm.py:443) run on the unfiltered list; only DB rows change. LLM premium seed reads only `tier2_llm` rows (unaffected). Rate-cap seed reads applied rows (META/prediction never applied). No scripts/dashboards count META rows per hour (grep of scripts/).

## NM `_notify_dedup_state` (:5554) memory-only
Out of scope for this card: it governs notification repeats, not row volume; restart re-notify is bounded by `OPTIMIZER_NOTIFY_DEDUP_CYCLES`. Card separately if restart re-pages are observed.

## Verdict
FIX-REQUIRED (MEDIUM): A1, A2. A3/A4 are cheap and should go in the same fix-up (A1's 24h interval fixes A3 too).

## Fix-up (2026-10-23)

| Finding | Fix | Test | Drill (neuter site -> named test) |
|---|---|---|---|
| A1/B2 no re-persist interval | `_persist_on_change_last` now stores `(description, ts)`; unchanged row re-persists once older than the REUSED `OPTIMIZER_SENSOR_HEALTH_REPERSIST_INTERVAL_S` (24h, same semantics; no new constant) | `test_ocr_fixup_unchanged_meta_repersists_after_interval` (86399 s / 86401 s literals) | interval condition -> `True`: RED |
| A2 clear-then-recur suppressed | new `_prune_persist_on_change(findings)` called in `_run_cycle_body` right after `_cap_findings` on the FULL evaluated list (not inside `_persist_findings_batch`: the skip-path META-only batch and the LLM batch are partial and would spuriously clear) | `test_ocr_fixup_cleared_then_recur_same_text_repersists`; wire-in anchor `test_ocr_fixup_cycle_body_prunes_cleared_on_change_entry` (drives `_run_cycle_body`) | prune `pop` -> `pass`: RED; prune CALL removed: RED |
| A3/B1 stamp-before-commit | both filters collect stamps into a list; new `_commit_persist_stamps` applies them only after `log_findings_batch` returns a truthy count (the DAO swallows insert errors and returns 0, so an exception is not the only failure). Tripwire drop / no DB / raise / 0 leave no stamp. The never_fires Store `last_persisted` mirror moved into the commit. Direct filter calls (stamps=None) stamp immediately (pre-existing unit tests). | `test_ocr_fixup_failed_write_leaves_no_stamp`, `test_ocr_fixup_tripwire_drop_leaves_no_stamp`, `test_ocr_fixup_never_fires_stamp_not_set_on_failed_write` | `if written` -> `if True`: RED; on_change deferral -> immediate commit: RED; sensor_health deferral -> immediate commit: RED; never_fires mirror neutered: RED; commit call removed: RED (`test_ocr_cycle_ok_persists_once_not_every_cycle`) |
| A4/B3 stale comment | skip-path comment/log now says the META sentinel is offered for persist and lands on the first successful write of a boot then at most once per interval | n/a (comment) | n/a |
| A5 float noise | not changed (INFO, accepted) | - | - |

Drills: one-step mutate/run/restore script, `__pycache__` cleared, `PYTHONDONTWRITEBYTECODE=1`; `git status` clean of source mutations after. Ran only test_optimization_coordinator.py + test_v5110_optimizer_hardening.py + test_optimizer_reserve_hard_deny.py: the only failures are the same 10 env-shaped failures (MockHassForOpt lacks loop/config) that fail identically at 2b4a058a8.
