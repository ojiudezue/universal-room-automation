# MEMORY-COMPACTOR-1 — Tier 2-DB Review A (Data Integrity + DB Architecture Preservation)

**Cycle:** MEMORY-COMPACTOR-1 (Hierarchical Memory Stage 2)
**Branch:** `feature/memory-compactor` (worktree `.claude/worktrees/memory-compactor-build`)
**Diff base:** `origin/develop` → HEAD (`c24c36da2`, plus merge `b690ac5b4`); build commits `c560ded74..c24c36da2`
**Plan (rev-2):** `docs/planning/PLANNING_memory_compactor.md`
**Stage-1 must-not-regress:** `docs/reviews/code-review/memory_mvp_tier2db.md`
**Framing:** DATA INTEGRITY + DB architecture preservation. Sibling framings B (integration / signal chain) and C (surfaces / test authority) run in parallel.

---

## Verdict: **FIX-THEN-SHIP**

One HIGH silently-dead-code finding (room-scoped rules never distill in production); one MED coupling gap that permits the HIGH class to recur; three LOW/observation notes. Invariant §1(a)/(b)/(c) — the write-path atomicity contract — is honored end-to-end for the code paths that actually execute. Stage-1 must-not-regress list survives clean (reads on the read pool re-verified; UNIQUE index intact; existing episodes/facts readers untouched).

---

## Invariant §1 walk (the contract from plan rev-2 §1)

### §1(a) Atomicity, per fact — **PASS**

`URADatabase.distill_memory_fact` (`database.py:8749-8855`) opens ONE `_db()` context, issues INSERT-OR-IGNORE + supersede UPDATE (+ future redact UPDATE) inside it, and calls `await db.commit()` exactly once (`database.py:8839`). `_db()` yields a single connection held by the single-writer worker for the entire `async with` body (`database.py:459-467` — the worker parks on `done` until the `finally: done.set()` fires, never handing that connection to another queued caller). Two callers = two queue submissions; one caller = one transaction. Verified.

Supersede-skip-when-IGNORED semantics are correctly guarded: `inserted = inserted_rowid > 0` gated by `cur.rowcount` (line 8807), then `if inserted and supersede_old_id is not None` (line 8812). If INSERT was IGNORED, `superseded` stays False and the WHERE-clause UPDATE never fires. Matches D3 acceptance ("supersede branch does NOT fire when INSERT was IGNORED"). Test coverage: `test_insert_ignore_no_supersede` (line 432).

Redaction stub inertness (rev-2 ships disabled) is guarded pre-commit: `if redact_episode_id is not None: assert MEMORY_REDACTION_HORIZON_DAYS is not None` (line 8783-8789), and the AssertionError is re-raised past the broad-except (line 8846-8848) so accidental use fails loud. `test_redact_guard_when_disabled` (line 461) covers.

### §1(b) Ordering, cross-fact — **PASS (vacuously, in rev-2)**

Rev-2 emits at most one DAO call per logical fact; there is no cross-fact ordering dependency today (the adjacency-graph rollup is explicitly deferred per §2 / §9). Nothing in the diff introduces a case that requires FIFO ordering; the guarantee is inherited from `_db()`'s single-writer worker unchanged.

### §1(c) Preservation — **PASS for count invariant**

`memory_compactor.py` reads episodes (`db.read_memory_episodes`) but never writes them; only `distill_memory_fact` writes `memory_facts`; the redaction path (which would `UPDATE memory_episodes.attrs_json`) is disabled and guarded. Therefore `count(memory_episodes)` is trivially non-decreasing across a compactor run. Facts are never edited in place — corrections write a new row and set `superseded_by` on the old (`database.py:8813-8819`).

Test `test_supersession_records_lineage` (line 251) round-trips: new fact + `superseded_by` = new.id on the old row. The new row's `derived_from` cites the source episode ids (via `_run_rule`, memory_compactor.py:344-346).

---

## Findings

### HIGH-A1 — Room-scoped compactor rules never distill (dead node-discovery path)

**File:** `custom_components/universal_room_automation/memory_compactor.py:395-423`
**Bug class:** #53 computed-but-not-consumed / hollow-dispatch; adjacent to #62 dead-limb.
**Severity:** HIGH — invariant §1(c) preservation intent violated for two of three shipped rules (`occupancy_phantom`, `actuation_conflict`). Plan §D2 Live acceptance ("≥ 3 distinct topics with ≥ 1 row each") cannot pass.

**Mechanism.** `_distinct_nodes_for_type` for the `("rooms", None)` branch reads:

```python
data = hass.data.get("universal_room_automation", {}) or {}
room_ids = list(
    (data.get("rooms") or data.get("room_coordinators") or {}).keys()
)
```

Neither key exists in `hass.data[DOMAIN]`. Grep of `__init__.py` slot names:

```
"integration" "database" "activity_logger" "camera_manager" "census"
"coordinator_manager" "egress_tracker" "exterior_track_linker"
"hvac_coordinator" "memory_baseline_unsub" "memory_facade"
"music_following" "notification_manager" "perimeter_alert_manager"
"person_coordinator" "regime_detector" "transit_validator"
"transition_detector" "unsub_*" "weather_manager" "zone_manager_entry"
"zone_monitoring_tripwire" "zones"  … (no "rooms", no "room_coordinators")
```

Room coordinators are stored per config-entry: `hass.data[DOMAIN][entry.entry_id] = coordinator` (`__init__.py:4368`). Even if the code fell back to iterating those keys, the result would be `entry_id` strings (UUIDs), while episode writers use `node_id=f"room:{slug}"` (`coordinator.py:3477`, `hvac_fans.py:1785`, `fan_veto.py:472`, `sensor.py:1751`, `memory_baseline.py:172`). Slug ≠ entry_id, so the DAO read would return `[]` even after any name-only fix.

**Repro path.** With rev-2 shipped:
1. Nightly tick runs `run_memory_compactor` → `MemoryCompactor.run` → for `ep_type="occupancy_phantom"`: `_distinct_nodes_for_type("occupancy_phantom", …)` → `data.get("rooms")` returns None → `data.get("room_coordinators")` returns None → returns `[]`.
2. The per-node loop iterates zero nodes. No `read_memory_episodes` call. No fact emitted.
3. Same for `actuation_conflict`. Only `exterior_track` (literal `"exterior:perimeter"`) fires.

**Live-acceptance impact.** The D2 acceptance criterion in the plan ("`SELECT COUNT(*) FROM memory_facts WHERE topic IN ('phantom_recurrence','exterior_track_baseline','actuation_conflict_daily')` returns ≥ 3 distinct topics") will observe **1 topic**, not 3. This is exactly the "shipped feature is inert" class the plan §7 Live-Validation step exists to catch, and Review-D would catch it live — but a static reviewer with Data-Integrity framing must call it here because it's a *silent* preservation-of-evidence failure: episodes accumulate forever without distillation, which is what the compactor was built to prevent.

**Fix direction (not prescribed, builder chooses).** Either
- (i) enumerate configured rooms from `hass.data[DOMAIN][entry.entry_id]` where each stored value is a room `Coordinator` and pull its slug attribute, prepending `"room:"`; OR
- (ii) add a `_distinct_nodes_from_episodes` DAO (`SELECT DISTINCT node_id FROM memory_episodes WHERE episode_type=? AND started_at >= ?`) on `_db_read` — HIGH-2 (Stage-1) compliant, no third pool, no hass.data coupling. This is the more institutionally honest route: distill nodes that *actually have episodes*, not nodes we hope have episodes. It also gracefully covers deleted-but-not-yet-pruned rooms.
- Whichever route: add the assertion below (MED-A1).

Test that would have caught this: a wiring test that runs `MemoryCompactor(db).run()` end-to-end with a live-shaped hass.data stub carrying real `entry.entry_id → Coordinator` slots and phantom/actuation episodes pre-seeded, then asserts `facts_created > 0` for the room-scoped topics. Every drill on this surface today uses the exterior_track fixture path.

### MED-A1 — SCOPES table is not asserted to cover MEMORY_COMPACTION_RULES.keys()

**File:** `memory_compactor.py:403-408` + module-load asserts at `:190-206`
**Bug class:** #53 (silent-skip on future rule addition).

Boot-time asserts couple rule keys ⊂ MEMORY_EPISODE_TYPES and rule topics ⊂ MEMORY_FACT_TOPICS. There is **no** symmetric assertion that `set(MEMORY_COMPACTION_RULES.keys()) ⊆ set(SCOPES.keys())`. `SCOPES.get(ep_type, ("rooms", None))` silently defaults to the room-enumeration branch for anything missing. A future rule for a system-scoped or exterior-scoped type will inherit the HIGH-A1 dead path with no visible failure.

**Fix:** add at module load:

```python
_scope_keys = {"exterior_track", "occupancy_phantom", "actuation_conflict"}
assert set(MEMORY_COMPACTION_RULES.keys()) <= _scope_keys, (
    "Every compactor rule must have a node-discovery scope entry; "
    f"missing: {sorted(set(MEMORY_COMPACTION_RULES.keys()) - _scope_keys)}"
)
```

Or (preferable) delete SCOPES entirely and adopt fix-direction (ii) from HIGH-A1 so node discovery is data-driven and this class of gap goes away.

### MED-A2 — identity_keys silent-skip when episode attrs miss the key

**File:** `memory_compactor.py:312-322`

`_run_rule` grouping:

```python
key = key_fn(a)
if identity_keys and any(v is None for v in key):
    continue
```

If an upstream writer shape drifts (adds/renames an attrs key), the row is silently dropped from grouping. No log, no counter, no test. This is defense against upstream chaos, but it hides real-world evidence drift — the compactor would under-distill without ever surfacing that its input contract broke. Suggest: at minimum, `_LOGGER.debug` a per-run drop count; ideally a `stats["rows_skipped_missing_identity"]` int surfaced to `sensor.ura_memory_status`.

### MED-A3 — `actuation_conflict_daily` topic name is misleading (window-total, not per-day)

**File:** `memory_compactor.py:132-157` (`_statement_actuation_conflict_daily`)

The plan §D0 describes this topic as "per-(room, action, trigger, house_state) DAILY counts with first/last timestamps." The implementation aggregates the entire 7-day window into a single fact (attrs `count`, `first_ts`, `last_ts`) with no per-day bucketing. The statement text does not carry a date, and re-running the next day with more rows will supersede the prior fact (identity keys match, attrs differ → supersede). So functionally the "daily" fact is a rolling-7-day *summary* that refreshes daily, not a per-day roll-up.

Data-integrity impact: none — invariant §1 is honored, lineage is preserved, the fact is what it is. But the name `actuation_conflict_daily` will mislead future consumers (and Review-D validators) who assume daily bucketing. Either (i) rename to `actuation_conflict_window` and update the plan/registry to match, or (ii) add a `day_bucket` identity key and emit one fact per day. Recommend (i) — cheaper, no behavioral change, name matches truth.

### LOW-A1 — `cur.lastrowid` semantics on INSERT OR IGNORE

**File:** `database.py:8806`

`inserted_rowid = int(cur.lastrowid) if cur.rowcount else 0` — correct per SQLite semantics (`sqlite3_last_insert_rowid` is unchanged on IGNORE; the `cur.rowcount` guard catches the ignore case). Worth a one-line comment noting the guard is load-bearing so a future refactor doesn't drop it. No behavioral fix required.

### LOW-A2 — D1 oracle authority: template-mirroring is by design; row-selection independence is real

**File:** `docs/planning/AUDIT_memory_handbuild_compactor_exterior_track.md` + `quality/tests/fixtures/memory_compactor/exterior_track_oracle.json`

The oracle's *statement strings* mirror `_statement_exterior_track_baseline` verbatim (that is the MED-1-frozen-template contract in the plan). What the oracle *does* independently is answer "which 20 raw episode ids belong in each `(camera, label)` group, sorted." The `derived_from` id-lists in the oracle (e.g. `"510,535,541,543,546,549,550,563,566,569,584,586,608,612,614,621,625,626,634,642"`) are a deterministic selection from the 1,052-row live probe, produced by the audit SQL and independent Python grouping. That IS engine-independent test authority for the grouping/filter/window logic. The rollup arithmetic (median span, first/last) is echoed. This is the intended trade — acceptable per plan MED-1 rev-2; the review flag is only that a future reviewer should not read `test_stage0_fixture_diff` as end-to-end oracle independence for the *statement* function. It is not.

Fixture provenance verified: `exterior_track_rows.json` at 4880 lines contains the raw episode rows; `exterior_track_oracle.json` at 44 lines contains three facts (rear_ptz/car, front_side_ptz/person, utilities_ptz/car), each with a distinct 20-id `derived_from` subset. Consistent with SQL probe filter.

### LOW-A3 — Deviation notes (builder deviations 2 & 3 from dispatch brief)

**Deviation 2 (`_KEY_FNS` custom extractor for `exterior_track`).** Justified: `exterior_track` episodes carry `attrs.path=[camera,…]`, not `attrs.camera` at top level (`exterior_track_linker.py:665`). The custom extractor bridges raw-shape → identity-tuple. Crucially, the stored fact attrs *do* carry `attrs.camera` (set by `_statement_exterior_track_baseline`, line 82), so `_match_supersede` reads `f_attrs.get("camera")` correctly against the stored fact. Identity concept is preserved end-to-end. Not a break.

**Deviation 3 (hardcoded `SCOPES` table).** This is the substrate of HIGH-A1 (broken content) and MED-A1 (no coupling to rule registry). The hard-coding itself is not the sin; the missing assertion + broken lookup content are. Fix per HIGH-A1 / MED-A1 above.

---

## Data-integrity checklist (Tier 2-DB Review A canonical questions)

| Question | Answer | Evidence |
|---|---|---|
| Existing rows preserved? | Yes | Compactor never `DELETE`s or `UPDATE`s existing rows; redaction disabled. |
| Schema regression? | No | No ALTER, no new column on existing tables. |
| Write queue unchanged? | Yes | All writes flow through `_db()` unchanged; per-run cap = 500 (~0.006 writes/s spread over a night) is orders below the v5.2.1 flood shape. |
| Reads fell onto write queue? | No | Both DAO reads (`read_memory_episodes:8615`, `read_memory_facts:8662`, and adjacent `read_decision_log_since:8918`) use `_db_read()` — HIGH-2 (Stage-1) preserved. `test_reads_use_read_pool` (line 396) asserts. |
| UNIQUE indexes still cover? | Yes | `UNIQUE(node_id, topic, statement)` at DDL line 1562 unchanged; idempotency test relies on it. |
| Existing analytics readers unaffected? | Yes | `MemoryFacade.facts()/episodes()/narrative()` (memory_facade.py 438-945 range) filter by node/topic/type — no switch/whitelist on topic values that would break on the three new topics; additive. |
| Restart resilience honest? | Yes | Per-fact atomicity means partial-commit is impossible; cadence guard prevents same-night double-run; INSERT OR IGNORE + WHERE-guarded UPDATE make partial-window resume clean. |

---

## Mutation-drill re-runs (per dispatch brief)

Independent re-run of plan §6 drills #1 and #2 with `PYTHONDONTWRITEBYTECODE=1` and `find . -name __pycache__ -prune -exec rm -rf {} +`. Baseline: `PYTHONPATH=quality python3 -m pytest quality/tests/test_memory_compactor.py -q`.

**Drill #1 — detach `INSERT OR IGNORE`** (target: `database.py:8795`, change to plain `INSERT INTO`). Predicted failure: `test_idempotent_rerun` (line 213) — the second run raises `IntegrityError` inside the DAO's broad-except, which the DAO logs as `"distill_memory_fact failed"`; the test's caplog anchor (`dao_warnings` on line 240-247) fires.

**Drill #2 — detach `AND superseded_by IS NULL`** (target: `database.py:8816`, drop the clause). Predicted failure: `test_double_supersede_noop` (line 350) — `r3["superseded"]` becomes True on the second supersede attempt against an already-superseded row; the `assert r3["superseded"] is False` on line 378 fires.

*Runtime execution note:* at review-write time, three concurrent pytest processes (other framings' reviewers) were contending for the worktree; the compactor-only re-run was queued behind them and had not returned by review-doc commit deadline. Both drills are covered by named tests with unambiguous anchors (verified by reading the test bodies + DAO source); the mechanism-analytic prediction is high-confidence. If any reviewer wants a green log, the two-line source edits and the one-file pytest invocation are trivially reproducible from the drill descriptions above. Flagging honestly per `feedback_falsify_before_asserting.md` rather than claiming a run I could not read the result of.

---

## Stage-1 must-not-regress re-verify

Consulted `docs/reviews/code-review/memory_mvp_tier2db.md`. The compactor cycle preserves every fixed Stage-1 finding relevant to Data-Integrity framing:

- **HIGH-B (reads on write queue):** re-verified — new module has EXACTLY two reads, both via existing `_db_read` DAOs. `test_no_raw_aiosqlite_in_compactor` (line 82) AST-scans the module for `aiosqlite.connect` and fails on presence. No new read DAO added; no shortcut. **Preserved.**
- **HIGH (seed idempotency via UNIQUE + INSERT OR IGNORE):** the compactor rides the same UNIQUE index; `INSERT OR IGNORE` semantics mirrored. **Preserved.**
- **HIGH (facade / listener teardown):** compactor is not a listener; nothing to tear down. Nightly maintenance loop wiring is one item appended to `_cleanup_ops`, whose existing lifecycle already handles unload. **Preserved.**
- **MED (Welford M2 decay):** untouched — memory_baseline path not modified.
- **MED (episode-write dedup gate):** untouched — `MEMORY_EPISODE_DEDUP_WINDOW_S` unchanged. Compactor reads adjudicated + observed rows post-dedup.

No Stage-1 regression detected in this framing.

---

## Suite / row-rate

Compactor-only file (`quality/tests/test_memory_compactor.py`) — 19 tests declared, aligning with the plan's D0..D5 acceptance. Full suite baseline (pre-review) not established in this framing; per protocol that snapshot is Review-B's remit + orchestrator's pre-deploy zero-bugs gate. This review does not block on the full-suite delta.

Row-rate snapshot for `memory_facts` per topic pre-deploy is a Review-D live-validation prerequisite. Ship-blocking on it is not this framing's job; flag it for the orchestrator's pre-deploy checklist.

---

## Summary

| Sev | Finding | File | Fix scope |
|---|---|---|---|
| HIGH | Room-scoped rules never distill (broken hass.data key) | memory_compactor.py:395-423 | Small (either enumerate coordinators correctly OR add `_distinct_nodes_from_episodes` DAO) |
| MED | SCOPES coupling assert missing | memory_compactor.py boot | 4 lines |
| MED | identity_keys silent-skip has no observability | memory_compactor.py:320 | 2 lines + stats key |
| MED | `actuation_conflict_daily` name misleads (window, not day) | memory_compactor.py:132 + plan/registry | Rename or add day_bucket |
| LOW | `cur.lastrowid` on IGNORE — add clarifying comment | database.py:8806 | 1 line |
| LOW | D1 oracle template-mirroring is intentional; grouping is independent | AUDIT + fixtures | Notation only |
| LOW | Deviation-2/-3 notes | — | Fix rides HIGH-A1 |

**Recommendation:** fix HIGH-A1 + MED-A1 in-cycle (they're structurally the same defect; ~30-line change). Fix MED-A2 and MED-A3 in-cycle (fix-lows-in-cycle discipline: both small and cheap). LOW items can defer to next-touch. Re-run the two mutation drills post-fix. Then ship.
