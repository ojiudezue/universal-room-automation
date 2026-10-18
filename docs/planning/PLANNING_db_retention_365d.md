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
**Rule (revised in plan review, see PR-1):** compare against a **date-only** cutoff string `YYYY-MM-DD`
computed **in the clock the table's rows are written in**:
- env / energy / occupancy (naive UTC, producer `datetime.utcnow().isoformat()` `database.py:2770,2785,2808`):
  `cutoff = (dt_util.utcnow().date() - timedelta(days=N)).isoformat()`
- room_transitions (local wall time with offset, space separator): `cutoff = (dt_util.now().date() - timedelta(days=N)).isoformat()`
A date-only string sorts correctly against both formats (`T` and space both sort after the 10-char date prefix,
so every row on the cutoff date compares `>=`), and with the per-table clock the error is always on the keep side
by < 1 day in ANY HA timezone. Test both formats explicitly, and test the UTC tables with HA tz set east of UTC
(e.g. `Australia/Sydney`) at local just-after-midnight.

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
`retention_days <= 0` returns 0 with no query; per-table INFO log of rows deleted **including 0** (the deploy-night
live check depends on seeing the op ran; siblings only log when >0 — PR-5).
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
  `SELECT min(timestamp) FROM environmental_data` >= `2025-11-20` (the 11-20 UTC-date cutoff) and the day-over-day
  row-count delta is ~0 (inserts ~12 k/day are offset by ~12 k deleted) instead of the pre-prune ~+12 k; nightly
  log shows "room_history" deleted N>0. Discriminates "op wired but cutoff wrong / not running" (min stays
  2025-11-19T12:04, delta ~+12 k) from "op works". A count *drop* is NOT expected (PR-4).

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
- Steady state ~26 k rows/night across tables -> ~27 batches; worst case 4 x 100 k (cap) = 400 batches (>= 40 s of
  yields alone). NOTE (PR-3): the 5-min budget check (`__init__.py:2800`) runs only BETWEEN ops — it never
  preempts a running op. The bound on this op is `ROOM_HISTORY_PRUNE_MAX_BATCHES` alone; the budget guard only
  defers the ops after it. The cap carries the remainder to the next night.
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

## Plan review (2026-10-18 overnight)

Reviewer: ura-planner, adversarial plan review (Tier 2-DB, one pass). Method: greps re-run, not trusted; live DB
read-only (`sqlite3 -readonly`) for formats and a no-match scan timing. No HVAC/presence surface touched.

**Verified as claimed:**
- Both nightly lists exist: `_cleanup_ops` `__init__.py:2731` (vacuum at :2772, loop :2796-2810) and
  `_cleanup_ops_d` `__init__.py:2882` (vacuum at :2912, loop :2933). No third copy (`grep -n _cleanup_ops __init__.py`).
- No existing DELETE on the four tables; `RETENTION_*` constants `const.py:2010-2015` have no runtime readers.
- `cleanup_person_data` shape `database.py:3929-3965` matches the cited pattern (`< ?` on an isoformat cutoff,
  rowid-IN LIMIT, `_db()`, 0.1 s yield, 500-batch cap).
- Reader enumeration re-run independently: all SQL readers are in `database.py` (3392/3402/3412 recent_data,
  3434-3440 counts, 3471, 3520, 3566, 3605, 3680/3702, 4087, 4122, 7264/7273, 7926, 7952); outside it only the
  producer call `coordinator.py:5462`, the counts sensor `sensor.py:2392`, the export button `button.py:381,423-440`,
  a comment in `memory_facade.py:899` (adjacency cache, no DB read), and the offline probe. Caller windows:
  `bayesian_predictor.py:233,666` days=90; `coordinator.py:5502-5523` 7 d / month / 7 d; `pattern_learning.py:69`,
  `transitions.py:682`. Max look-back 90 d — **INV-2 holds**. No reader in `scripts/` other than the probe; no
  PWA/websocket reader in this repo.
- Live formats (2026-10-18 07:14 UTC): env/occ/energy `2026-10-18T07:14:46.451929` (naive UTC, producer
  `datetime.utcnow().isoformat()` `database.py:2770,2785,2808`); occupancy has 3 rows of length 19 (no micros) —
  harmless for a date-prefix compare; room_transitions 100% length 32, space separator, `-05:00/-06:00` offsets.
- No-match scan cost: `SELECT rowid FROM environmental_data WHERE timestamp < '2025-11-18' LIMIT 1000` = 0.19 s
  (warm), plan `SCAN ... USING COVERING INDEX idx_env_room_time`. Acceptable; see PR-6.

**Findings:**

| ID | Sev | Finding | Disposition |
|---|---|---|---|
| PR-1 | HIGH | INV-1 says "under any configuration", but the original rule used the **local** date for all tables. Three tables store naive **UTC**. With HA tz east of UTC (URA is rolling to other homes), e.g. UTC+10 at local 00:30 on D: cutoff C=D-N; rows with UTC date < C are deleted; local D 00:30 = UTC D-1 14:30, so a row at UTC (C-1) 23:59 is only ~364 d 14.5 h old -> INV-1 falsified. West-of-UTC (Texas) is safe, which is why it hid. | **FIXED in plan** (section 2): per-table clock — UTC date for UTC tables, local date for room_transitions; added east-of-UTC test. |
| PR-2 | MEDIUM | D2's test "reads both lists": the lists are local variables inside setup closures, so the only way to test is a source grep — a hollow anchor (memory `feedback_hollow_test_anchors`). The mirror-miss is this file's recurring bug (#27). | **DECISION:** recommend hoisting the op list to one module-level builder (e.g. `_nightly_cleanup_ops()`) consumed by both `_cleanup_ops` and `_cleanup_ops_d`, so the mirror cannot drift and the test can call it. Small, removes a bug class; but it touches 2 lists other cycles edit. If declined, the test must at least parse `__init__.py` with `ast` and assert the tuple in both list literals, and the mutation drill removes each entry separately. |
| PR-3 | MEDIUM | Section 7 claimed the 5-min budget guard "carries the remainder"; the guard (`__init__.py:2800`, :2933 loop) only checks between ops — it does not preempt a running op. | **FIXED in plan** (section 7 text). The cap is the only bound; 100 batches/table is fine. |
| PR-4 | MEDIUM | Nov-20 live criterion said "row count dropped by ~12 k vs the prior day" and "min >= 2025-11-19". With ~12 k/day inserts the count stays ~flat; and on 11-20 the UTC-date cutoff is 2025-11-20. As written the criterion would read FAIL on a working prune. | **FIXED in plan** (D2 Live): min >= 2025-11-20 and day-over-day delta ~0 vs ~+12 k. |
| PR-5 | LOW | Deploy-night live check ("op ran with 0 rows deleted") is unobservable if the DAO follows siblings and logs only when >0. | **FIXED in plan** (D1: log including 0). |
| PR-6 | LOW | Every night's final (non-full) batch scans the whole covering index (~140-160 MB per table) under the single writer. Measured 0.19 s warm; cold cache on the HA box may be seconds. | Accept. Optional cheaper variant for the builder: early-exit per table via an O(1) `SELECT timestamp FROM t ORDER BY rowid LIMIT 1` >= cutoff check (rows insert in time order) before the DELETE loop — skips all four scans every night until 2026-11-19 and on no-op nights. Builder's call; not required. |
| PR-7 | LOW (pre-existing, out of scope) | `get_room_transition_counts` (`database.py:7255-7268`) compares a UTC `T`-separated isoformat cutoff to local space-separated rows: ` ` < `T`, so cutoff-day rows are excluded, and the 5-6 h offset is ignored. Sub-day error on a 90-day prior; harmless. | Not this cycle; worth a one-line card if anyone touches the predictor. |
| PR-8 | INFO | "Placed before `incremental_vacuum`" is cosmetic: the start index rotates nightly, so order only holds on some nights. Plan already says so in section 7. | None. |

Checked and fine: institutional-context section is complete and the greps reproduce; knobs are on the module-const
rung with 0 = kill switch stated; non-goals explicit; tier (2-DB) correct, irreversible delete justifies 3 build
reviews; D0 backup uses the online `.backup` API. Invariants INV-1/2/3 are falsifiable (PR-1 is exactly a
falsification of the original INV-1 rule).

**Verdict: READY-TO-BUILD** after the in-plan fixes above, with one operator/orchestrator decision pending (PR-2:
hoist the shared op-list builder, or accept an `ast`-based dual-list test). Either choice is buildable; the
recommendation is hoist.
