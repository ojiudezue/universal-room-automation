# PLANNING — 365-day retention for the room-history tables (DB-SIZE-GROWTH-1)

Status: plan, awaiting plan review (Tier 2-DB -> one adversarial plan review before build).
Card: `DB-SIZE-GROWTH-1` (`docs/planning/kanban.data.yaml`). Operator decision 2026-10-17: 365 days for
`environmental_data`, `energy_snapshots`, `occupancy_events`; `room_transitions` also 365 unless this plan
shows a reason not to (it does not, see Producer/Consumer). Offline DB copy before the first prune.

## Headline (measured 2026-10-18 ~02:10 CDT, read-only `sqlite3 -readonly` on the live DB)

| table | rows | oldest | rows older than 365 d today | table MB | index MB |
|---|---|---|---|---|---|
| environmental_data | 2,578,130 | 2025-11-19T12:04 | **0** | 220 | 162 (idx_env_room_time) |
| energy_snapshots | 2,581,327 | 2025-11-19T12:04 | **0** | 176 | 163 (idx_energy_room_time) |
| occupancy_events | 2,303,938 | 2025-11-20T17:15 | **0** | 172 | 139 (idx_occupancy_room_time) |
| room_transitions | 372,161 | 2026-01-04 19:31-06:00 | **0** | 36 | 55 (idx_transitions_rooms 32 + _person 23) |

File: 1,448,099,840 B (1.45 GB; 353,540 pages x 4096; freelist 38; `auto_vacuum=2` INCREMENTAL). The four
tables + indexes = ~1,123 MB (78%). Growth since the 09-30 measurement: env +218 k rows in 18 d (~12.1 k/day),
energy the same, occupancy ~460/day; file +99 MB in 18 d (~5.5 MB/day).

**Plainly: 365-day retention frees nothing now.** No row is older than 365 days. The first rows age out on
**2026-11-19** (env + energy), **2026-11-20** (occupancy), **2027-01-04** (room_transitions). After that the
nightly prune deletes ~one day of rows per night (~12 k env + ~12 k energy + ~0.5 k occupancy + ~1.3 k
transitions). The effect is a **cap, not a shrink**: the DB keeps growing until 2026-11-19, then plateaus at
roughly one year of these tables (estimate ~1.55-1.65 GB total, i.e. ~+0.1-0.2 GB from today). If the operator
wants the file to get *smaller*, that needs a shorter window, which is a separate decision (non-goal here).

There is also no "first run" backlog: on the first eligible night only the oldest day is past the cutoff, so a
first-run cap is satisfied trivially by the existing per-op batch cap. It is kept anyway (below) as a guard
against a future knob change to a short window.

## 1. Institutional context verified

Greps run (code at `custom_components/universal_room_automation/`):

| Proposed piece | Verdict | Evidence |
|---|---|---|
| Batched DELETE pattern | **REUSED** shape of `cleanup_person_data` `database.py:3930-3965` (rowid-IN-subselect LIMIT batch, `_db()` write-queue, 500-batch cap, 0.1 s yield, 0 = disabled) and `cleanup_energy_history` `database.py:5159` | grep `def cleanup_` |
| Nightly scheduler | **REUSED** `_cleanup_ops` in `_nightly_db_maintenance` `__init__.py:~2730-2790` (02:30, 5-min budget, rotating start, 1 s gap) **and** the deferred-startup mirror `_cleanup_ops_d` `__init__.py:~2885-2925` | grep `_cleanup_ops` — TWO lists; both must get the op (Bug Class #27 history: egress_state, incremental_vacuum, memory_compactor all needed mirror fix-ups) |
| Space reclaim | **REUSED** `incremental_vacuum` `database.py:9524` (cap `_INCREMENTAL_VACUUM_MAX_PAGES=2000` ~8 MB/night, `database.py:9522`); DB is already INCREMENTAL (live `PRAGMA auto_vacuum` = 2) | memory `project_db_incremental_vacuum_backlog` |
| Retention constant | **NEW** `RETENTION_ROOM_HISTORY_DAYS: Final = 365` in `const.py` next to `const.py:2010-2015` | Existing: `RETENTION_DETAILED=7`, `RETENTION_AGGREGATED=30`, `RETENTION_ARCHIVE=365` ("daily summaries"), `RETENTION_PREDICTIONS=365`, `RETENTION_ENERGY_HISTORY=90` — all with **no runtime users** (grep `RETENTION_` outside const.py: only perimeter + log constants). Reusing `RETENTION_ARCHIVE` would be a coincidental-equality reuse (it names "daily summaries", a different concept); reusing `RETENTION_ENERGY_HISTORY` is the wrong value. New name, one constant for all four tables. |
| DAO method | **NEW** `cleanup_room_history(retention_days, batch_size=1000, max_batches=...)` in `database.py` | No existing DELETE on any of the four tables (grep `DELETE FROM environmental_data|energy_snapshots|occupancy_events|room_transitions` -> none) |
| Config / options field | **none** (see knobs). `CONF_PERSON_DATA_RETENTION` `const.py:159` is a different table set and documented "no runtime reader" | grep config_flow/options_flow `retention` |

Config-First check: no live knob, options field, or HA setting prunes these tables (HA recorder `purge_keep_days`
governs the HA recorder DB, not URA's DB). The vacuum button (`button.ura_coordinator_manager_vacuum_database`)
only reclaims free pages; the DB has 38 free pages. Code is required.

Prior art consulted: memory `project_db_incremental_vacuum_backlog` (body: the June "bloat" was live data; INCREMENTAL
is active; don't re-chase VACUUM), memory `project_optimizer_db_write_flood_incident_2026_06_09` (index line:
batch, never per-row; write-queue saturation), `docs/planning/AUDIT_db_write_worker_slow_2026_09_29.md` (filename/
header: same boot audit that found this card), card fields `MEASURED_2026_09_30_overnight` + `gate_2026_09_30`.
Design docs: none per-coordinator (DB is cross-cutting); `URA_ARCHITECTURE_MAP.md` rule: DB writes go through
the single serialized `_write_queue`.

## 2. Falsifiable invariant

**INV-1:** Under any configuration, the nightly maintenance never deletes a row from the four tables whose
timestamp is less than `RETENTION_ROOM_HISTORY_DAYS` days old (local date), and with the constant at 0 it deletes
nothing.
**INV-2:** No in-repo reader of the four tables has a look-back window longer than `RETENTION_ROOM_HISTORY_DAYS`.
**INV-3:** The prune never runs on the event loop as one long statement: every DELETE is `<= batch_size` rows,
goes through `_db()` (single writer), and one night deletes at most `max_batches x batch_size` rows per table.

Timestamp-format trap (D must try to break INV-1 here): the tables store **different formats**.
env/energy/occupancy are naive ISO with `T` and appear to be UTC (max 07:11 at 02:11 CDT); room_transitions is
local with offset and a space separator (`2026-10-18 00:15:51-05:00`). A cutoff built with `.isoformat()` and
compared as a string would be off by the UTC offset on one table and sensitive to `T` vs space on the same date.
**Rule:** compare against a **date-only** cutoff string `YYYY-MM-DD` = `(dt_util.now().date() - timedelta(days=N))`.
A date-only string sorts correctly against both formats (every row on the cutoff date compares `>=`), so the
error is always on the keep side by < 1 day. Test both formats explicitly.

## 3. Producer and consumer checks

**Producers** (writers): `database.py:2768` occupancy_events, `:2781` environmental_data (via
`coordinator.py:5462`), `:2802` energy_snapshots, `:4028` room_transitions. The prune does not change them.

**Consumers** (every reader, look-back; all in `database.py` unless noted):

| Reader | Table | Window | Trust/display |
|---|---|---|---|
| `get_recent_data` ~3375-3415 | occ/env/energy | `LIMIT` newest N (export button `button.py`, limit 500) | display/export |
| `get_table_counts` ~3430-3440 | occ/env/energy | all-time `COUNT(*)` per room | display (`sensor.py:2392-2432`); counts will plateau instead of grow — expected |
| `get_energy_for_period` ~3471 | energy | 7 d and month-to-date (`coordinator.py:5502-5506`) — max 31 d | display |
| `get_occupancy_percentage` ~3520 | occ | `days=7` default | display/prediction |
| `get_peak_occupancy_hour` ~3566 | occ | 7 d | prediction |
| `get_next_occupancy_prediction` ~3605 | occ | 7 d | prediction |
| `get_avg_time_to_comfort` ~3680-3702 | occ + env | 14 d | display |
| `get_transitions` ~4087 | room_transitions | `hours=24` (`transitions.py:682`) or `days=30` (`pattern_learning.py:39,69`) | prediction |
| `get_common_paths` ~4122 | room_transitions | 30 d default | prediction |
| `get_room_transition_counts` 7243 | room_transitions | `days=90` at both callers (`bayesian_predictor.py:233,666`); the `days=None` all-time branch has **no caller** | Bayesian prior |
| `get_occupancy_time_today` ~7926 / `get_uncomfortable_minutes_today` ~7952 | occ / env | today | display |
| `scripts/probes/empty_house_experiment_probe.py:98` | occ | explicit S..E window (offline probe) | offline |

Longest in-code window: **90 days** (Bayesian prior on room_transitions). INV-2 holds with 275 days of margin.
**room_transitions verdict: same 365, no reason to differ.** The only all-time read path is uncalled; if a future
caller uses `days=None` it will silently see at most a year — note this in the docstring.
Off-repo consumers: none found (offline learning / forecaster reads the HA recorder, not these tables — grep of
`scripts/` found only the probe above). If the operator wants a permanent archive for offline learning, the
offline copy (D0) is it.

## 4. Emission / decision-site enumeration

Sites that must change: (a) `database.py` new DAO; (b) `_cleanup_ops` `__init__.py` primary list; (c)
`_cleanup_ops_d` deferred list; (d) `const.py` constant. Reviewer: `git grep -n "_cleanup_ops" __init__.py` and
confirm both lists carry the op (the missed-mirror is this file's recurring bug).

## 5. Deliverables

### D0 — Offline DB copy (operator step, before deploy)
`ssh ha "sqlite3 /config/universal_room_automation/data/universal_room_automation.db \".backup '/config/universal_room_automation/data/universal_room_automation.db.pre-retention-365-<date>.bak'\""`
(online backup API, safe while HA runs; ~1.45 GB; disk has 331 GB free). Taking it at deploy is sufficient: the
first prune is 2026-11-19 and every row it can delete already exists in the copy. Then
`sqlite3 -readonly <bak> "PRAGMA integrity_check; SELECT count(*) FROM environmental_data;"`.
- **Verify:** bak exists, `integrity_check` = ok, env row count >= the pre-deploy count.
- **Live:** `ls -l` shows the bak with size within 5% of the live file.

### D1 — `cleanup_room_history` DAO
Loops the four `(table, "timestamp")` pairs; date-only cutoff (section 2); `DELETE ... WHERE rowid IN (SELECT rowid
FROM t WHERE timestamp < ? LIMIT ?)` via `_db()`; per-table cap `ROOM_HISTORY_PRUNE_MAX_BATCHES` (module const,
default 100 -> 100 k rows/table/night; steady state needs ~13); `asyncio.sleep(0.1)` between batches; returns total;
`retention_days <= 0` returns 0 with no query; per-table INFO log of rows deleted.
- **Verify:** rows dated cutoff-1 d deleted; rows dated cutoff and cutoff+1 d kept, for BOTH timestamp formats (a
  fix that compared full ISO strings would fail the room_transitions same-day-offset case — discriminating).
- **Verify:** 0 disables (no DELETE issued); cap stops at `max_batches` and resumes next call.
- **Test:** `test_room_history_prune_keeps_rows_younger_than_cutoff_both_formats`,
  `test_room_history_prune_zero_disables`, `test_room_history_prune_batch_cap`, against the real schema extracted
  from `database.py` DDL (no hand-copied DDL).

### D2 — Wire into both nightly lists
Add `("room_history", "cleanup_room_history", {"retention_days": RETENTION_ROOM_HISTORY_DAYS})` to `_cleanup_ops`
and `_cleanup_ops_d`, placed before `incremental_vacuum`.
- **Verify:** both lists contain the op (test reads both, or a mutation removing either goes red).
- **Test:** `test_nightly_ops_include_room_history_primary_and_deferred`.
- **Live (deploy night):** HA log at 02:30 shows the op ran with 0 rows deleted (no rows old enough) and no
  "5-min budget" warning. **Live (2026-11-20 morning, one-shot query, not a soak):**
  `SELECT min(timestamp) FROM environmental_data` >= 2025-11-19 date-cutoff and row count dropped by ~12 k vs the
  prior day; nightly log shows "room_history" deleted N>0. Discriminates "op wired but cutoff wrong" (min
  unchanged) from "op works".

### D3 — Constant + docstring
`RETENTION_ROOM_HISTORY_DAYS: Final = 365` in `const.py` with comment "0 = keep forever (kill switch)";
docstring on `get_room_transition_counts` noting `days=None` is bounded by retention.

## 6. Knobs

| Knob | Rung | Why |
|---|---|---|
| `RETENTION_ROOM_HISTORY_DAYS = 365` | module const (`const.py`) | Deleting history is irreversible; changing it should require review, matching every other `RETENTION_*`. 0 = disabled. |
| `ROOM_HISTORY_PRUNE_MAX_BATCHES = 100` | module const | Protocol bound on write-queue occupancy; not an operator policy. |
| `batch_size = 1000` | DAO default | Same as all sibling cleanups. |

No options-flow field and no Number entity: the operator turns this once a year at most, and a live slider on an
irreversible delete is a footgun.

## 7. Write-queue / transaction safety
- Every batch is one short transaction on the single writer; other writes interleave between batches (0.1 s yield).
- Steady state ~26 k rows/night across tables -> ~27 batches; worst case 4 x 100 k (cap) — still inside the shared
  5-min nightly budget at observed delete rates (`cleanup_*` siblings do similar volumes); the budget guard
  carries the remainder to the next night.
- 02:30 is after the 02:00 activity prune; ops rotate start index, so `incremental_vacuum` may run before the new op
  on some nights — freed pages are then reclaimed the following night. Freed volume (~3-5 MB/day) is below the
  vacuum cap (~8 MB/night), so the freelist cannot accumulate.
- No schema change, no migration, no index change.

## 8. Non-goals
Shrinking the DB now; a shorter window; downsampling/aggregating old rows into summaries (the unused
`RETENTION_AGGREGATED/ARCHIVE` design — parked, revive only if the operator wants >1 year at lower resolution);
deleting the two old `.bak` files in the data dir (~1.9 GB; operator housekeeping); pruning `prediction_results` /
`decision_log`; an options-flow or entity knob; the boot-freeze (card says DB size is not its cause).

## 9. Tier
**Tier 2-DB** (new DELETE DAO on four history tables; irreversible). Three framing-disjoint build reviews:
A data integrity (cutoff format, keep side, indexes used), B lifecycle (both nightly lists, write-queue occupancy,
budget, restart mid-prune), C test authority by per-site mutation (cutoff arithmetic, each list entry, zero
kill-switch). One adversarial plan review before build.

## 10. Plan-completion tracking (fill at cycle close)
| Item | Done? | If not, why / where tracked |
|---|---|---|
| D0 offline copy | | |
| D1 DAO + tests | | |
| D2 both lists + test | | |
| D3 constant + docstring | | |
| Live 2026-11-20 first-prune check | | carry as a dated check on the card, not a soak |
