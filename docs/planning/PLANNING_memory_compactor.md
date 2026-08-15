# PLANNING — Hierarchical Memory COMPACTOR (Stage 2)

Card: **MEMORY-COMPACTOR-1**
Tier: **Tier 2-DB** (touches `database.py` + the shipped facade primitive;
downstream shape/lineage-critical). Plan-review: **one adversarial pass
before build dispatch** per CLAUDE.md Plan-Review policy.
Sizing target: **small and finishable** — thinnest compactor that honors
`ARCHITECTURE_hierarchical_memory.md §5c`. Elaborations parked with
evidence triggers, not built.

Downstream of:
- `docs/planning/ARCHITECTURE_hierarchical_memory.md §5c` (distill /
  correct / redact — the design; this plan builds it, does not redesign).
- `docs/planning/AUDIT_memory_handbuild_study_a.md` (Stage-0 fixture
  precedent; this cycle produces a sibling hand-compaction fixture).
- `docs/reviews/code-review/memory_mvp_tier2db.md` (Stage-1 review record;
  the compactor MUST NOT regress its five fixed HIGHs, in particular
  **reads-on-write-queue** (HIGH B) and **Welford M2 decay** (MED A)).

---

## 0. Institutional context verified

### Greps run + results (proof-of-work)

- **`log_memory_episode` writer path** — `database.py:8433` writes through
  `self._db()` (single-writer worker). Reads use `self._db_read()` —
  `database.py:470`. REUSE both; do not introduce a third path.
- **`read_memory_episodes` / `read_memory_facts`** — `database.py:8597`
  / `:8645`. Already return the shapes the compactor will diff /
  supersede. REUSE.
- **`memory_facts` schema** — `database.py:1551` — carries
  `UNIQUE(node_id, topic, statement)` and `superseded_by` column. The
  supersession primitive is in the schema but **has no DAO** (grep for
  `superseded_by` in DAOs → only column definition + read filter).
  **NEW DAO required**: `add_memory_fact_row` (INSERT OR IGNORE mirroring
  the seed pattern at `database.py:1579`) + `supersede_memory_fact(old_id,
  new_id)` (single UPDATE, write queue).
- **`MEMORY_EPISODE_TYPES` / `MEMORY_FACT_TOPICS`** — `const.py:3642` /
  `:3660`. REUSE — a per-type distillation-rule registry is NEW keyed off
  this vocabulary (registry keys MUST be a subset of the frozenset;
  boot-time assert).
- **Nightly maintenance loop** — `__init__.py:2022` `_nightly_db_maintenance`
  driven by `_cleanup_ops` list of `(name, method_name, kwargs)` at
  `__init__.py:1978`. **REUSE this exact wiring surface** (add one op
  tuple). Loop already has a 5-min budget guard and rotating start index;
  a compactor step that returns quickly (< 1s typical) rides free.
- **Adjacent primitive — `incremental_vacuum`** — `database.py:8094`.
  Read for doctrine: (a) bounded cap constant, (b) no-op cleanly when
  disabled/not-applicable, (c) writes through the single-writer worker
  under the 120s guard, (d) supervised manual button variant. The
  compactor follows every one of these — including a supervised
  `button.ura_memory_compact_now` per Arch §10 (design already ratified).
- **Retention machinery** — none of the existing `prune_*` ops touch
  `memory_episodes` or `memory_facts` (grep confirmed). Redaction here
  is NEW — but redaction ≠ pruning. Redaction rolls raw rows into a
  digest row whose payload survives in the fact's `derived_from`; it is
  not a `DELETE ... WHERE ts < cutoff` that would lose evidence.
- **`MEMORY_BASELINE_SAMPLE_CAP`, `MEMORY_FACADE_ENABLED`, etc.** —
  `const.py:3610-3626`. Existing rung-1 knob pattern; new compactor
  knobs follow this rung + naming (see §5).
- **v5.5.7 DB incremental-vacuum cycle** — adjacent but orthogonal. Its
  contribution is doctrine (bounded, guarded, supervised-manual variant).
  It does NOT free pages the compactor generates — freelist growth from
  redaction is chipped away by the nightly `incremental_vacuum` that
  already exists. No new vacuum call from this cycle.
- **v5.2.1 write-flood postmortem** — ghost of the write path. Compactor
  MUST batch: one `db.execute` per fact-INSERT + one UPDATE per
  supersession + one UPDATE per redacted-row rollup is bounded by
  `MEMORY_COMPACTOR_MAX_WRITES_PER_RUN` (see §5); if the cap is hit the
  run exits early and resumes next night (idempotent — see §4).

### Prior planning docs consulted

- `ARCHITECTURE_hierarchical_memory.md` — full read, §5c is normative.
- `AUDIT_memory_handbuild_study_a.md` — full read; the fixture precedent
  for Stage 0. This cycle mirrors it for one episode type.
- `MVP_hierarchical_memory.md` — headers skimmed for the deferral
  language ("compactor DEFERRED per MVP parsimony pass").
- `PLANNING_paper_and_oss_fusion_library.md` — noted as spine consumer;
  no plan interaction this cycle.

### Memory bodies pulled

- `feedback_measure_before_build.md` — Stage 0 hand-compact D1 satisfies
  this discipline.
- `feedback_marginal_benefit_pushback.md` — applied in §7 non-goals
  (why redaction is a stub for now).
- `feedback_suppression_needs_discharge.md` — the "60s dedup" in
  `log_memory_episode` is a suppression with a discharge (next-tick);
  the compactor's per-type dedup at fact-emission time is likewise
  bounded (see §5).
- `feedback_hollow_test_anchors.md` — fixture is hand-built and
  independently authored (see §6).

### Design docs / code locations read end-to-end during scoping

- `custom_components/universal_room_automation/database.py` §§ around
  `memory_episodes` DDL (1527–1600), `log_memory_episode` (8380–8455),
  `read_memory_episodes` (8597), `read_memory_facts` (8645),
  `incremental_vacuum` (8071–8154).
- `custom_components/universal_room_automation/memory_facade.py`
  around `episodes()` (438–476) and `facts()` (920–945) — the
  read-consumer surface the compactor must not break.
- `custom_components/universal_room_automation/const.py` 3600–3745
  (memory constants + episode-type registry + seed facts).
- `custom_components/universal_room_automation/__init__.py` 1975–2062
  (nightly-maintenance wiring surface).

### Sibling cycle input (do not block on it)

- **MEMORY-RETRO-VALUE-1** will identify which episode types answer real
  diagnostic questions. This plan's per-type distillation-rule registry
  (§3) is deliberately **priority-adjustable per type** (registry entries
  carry a `priority` int; missing type → skipped). Retro-analysis output
  can update priorities without a code change to the compactor engine.

---

## 1. Falsifiable invariant (the property the cycle must guarantee)

**INVARIANT (Compactor Preservation of Evidence):**
> For every raw `memory_episodes` row that the compactor rolls up
> (redacts) into a digest row, at least one `memory_facts` row with a
> `derived_from` string containing that episode's id **must be committed
> and readable in the same DB transaction as the redaction write**. No
> episode row is ever deleted; redaction is a shape transform, not a
> DROP. No fact is edited in place; corrections write a new row and set
> `superseded_by` on the old one.

Operationally verifiable:
- `count(memory_episodes)` never decreases across a compactor run
  (redaction converts raw attrs to rollup attrs; row id preserved).
- For any episode whose `attrs_json` was rolled up by the compactor,
  `SELECT 1 FROM memory_facts WHERE derived_from LIKE '%<ep.id>%' AND
  id NOT IN (superseded set)` returns ≥ 1 row.
- Corrections: `SELECT id, superseded_by FROM memory_facts WHERE
  superseded_by IS NOT NULL` — every such row has a target row whose
  `derived_from` cites the superseded row's id.

This is the property the Tier 2-DB Review-A/B/C passes will each try
to break; write tests that make each half of the invariant fail.

## 2. Non-goals (explicit)

- **No new query verbs.** `facts()` / `episodes()` / `narrative()` are
  the read surface; the compactor writes into their tables.
- **No schema redesign.** `memory_episodes` + `memory_facts` shipped in
  v5.47.0 are load-bearing as-is. No ALTER, no new column, no new table.
- **No cross-node fact synthesis.** A fact's `node_id` is exactly the
  node whose episodes derived it; house-level roll-ups (e.g. adjacency
  graph — Arch §5b) are OUT OF SCOPE and PARKED (trigger: adjacency
  build lands separately).
- **Redaction of `attrs_json` is a STUB in this cycle.** Arch §5c allows
  a compactor with distill+correct only; redaction of raw attrs is
  built as a NO-OP path (framework exists, redaction cutoff defaults to
  `MEMORY_REDACTION_HORIZON_DAYS = None` = disabled). Trigger to
  enable: measured DB growth on `memory_episodes` past a threshold
  (§5). Rationale: MARGIN of full redaction over distill-only is small
  when episode volume is 1799 rows total (the current live count) —
  the largest ingredient risk is losing evidence, which is exactly what
  the framework-only stub avoids. Marginal-benefit pushback applied.
- **No LLM in the loop.** Distillation rules are registered per-type
  transparent statistics.
- **No new sensor entities.** Compactor stats attach to the EXISTING
  `sensor.ura_memory_status` per Arch §10.

## 3. Deliverables

### D1: Stage-0 hand-compact of `exterior_track` (fixture-first)

Mirror `AUDIT_memory_handbuild_study_a.md`'s role for the compactor.
Recommended type: **`exterior_track`** — 1044 live rows (2026-08-14),
the largest bucket, and per-track shape is well-defined by
`exterior_track_linker.py`.

Produce `docs/planning/AUDIT_memory_handbuild_compactor_exterior_track.md`:
- Read all 1044 `exterior_track` rows from the live DB (RO probe).
- Hand-apply a distillation rule (proposed: **N ≥ 20 tracks of same
  `class` within a rolling 7-day window on the same `zone` → propose/
  refresh a fact under `topic=exterior_track_baseline`** with statement
  citing count + class distribution + typical span; `derived_from` =
  comma-joined episode ids).
- Commit the resulting hand-written facts table + the raw-rows-→-facts
  mapping as the acceptance oracle.
- Note any type-shape surprises the automated compactor must handle.

Acceptance Criteria:
- **Verify:** file exists at planned path with the mapping table.
- **Verify:** every raw episode id appears in exactly one fact's
  `derived_from` (invariant §1 in the hand version).
- **Live:** D1 is a pre-build deliverable; no HA involvement.

### D2: `MemoryCompactor` engine + distillation-rule registry

New module `custom_components/universal_room_automation/memory_compactor.py`
(one class, ≤ ~300 LoC target). Interface:

```python
async def run(self, *, now: datetime | None = None) -> dict:
    """One compactor pass. Returns stats dict (facts_created,
    facts_superseded, episodes_redacted, aborted_reason)."""
```

Registry: `MEMORY_COMPACTION_RULES` in `const.py`, a mapping
`episode_type -> {min_count, window_days, topic, statement_fn,
priority}`. Keys asserted subset of `MEMORY_EPISODE_TYPES` at import.

For each rule (priority order):
1. **Distill.** For each node, count adjudicated episodes of the type
   in the window. If ≥ `min_count`, build the fact via `statement_fn`
   (registered, deterministic — no I/O, no live-time reads inside it).
   Emit via `add_memory_fact_row` (INSERT OR IGNORE on the UNIQUE index
   → idempotent re-runs are no-ops).
2. **Correct.** If a NEW fact's structured claim contradicts a CURRENT
   fact under the same `(node_id, topic)`, insert the new row FIRST,
   then `supersede_memory_fact(old_id, new_id)` in the SAME `_db()`
   context (single-writer worker guarantees ordering; no reader ever
   sees new-without-old or old-without-new inconsistent).
3. **Redact.** STUB. Framework-only: if `MEMORY_REDACTION_HORIZON_DAYS`
   is not None AND an episode of a type whose fact exists is older than
   the horizon, transform `attrs_json` to a rollup shape. Default None
   → this branch never executes. When enabled (future cycle),
   invariant §1 is enforced by asserting the fact write committed
   BEFORE emitting the UPDATE that rewrites `attrs_json`.

Write discipline (regression-critical — Stage-1 HIGH B):
- Reads inside the compactor use `db.read_memory_episodes(...)` /
  `db.read_memory_facts(...)` DAOs (already on `_db_read()`).
- Writes call the new DAOs `add_memory_fact_row` /
  `supersede_memory_fact` (on `_db()`, single-writer worker).
- **Never open a raw connection.** No `aiosqlite.connect` in the new
  module.

Batch cap: at most `MEMORY_COMPACTOR_MAX_WRITES_PER_RUN` combined
INSERT+UPDATE per run. On hit → log info, set `aborted_reason='cap'`,
return. Next nightly run resumes deterministically (rules are ordered;
INSERT OR IGNORE makes redoing already-emitted facts a no-op; §4).

Acceptance Criteria:
- **Verify:** unit tests drive the engine against a fixture DB seeded
  with the D1 hand-built shape and diff resulting `memory_facts` rows
  against the D1 oracle (Q: exact statements + derived_from set
  equality). Fixture-diff test is the load-bearing acceptance.
- **Verify:** mutation drill — delete the `INSERT OR IGNORE` clause
  from `add_memory_fact_row` and re-run the "idempotent second run"
  test; it MUST fail (UNIQUE violation) → proves the idempotency
  path is under test.
- **Test:** `tests/test_memory_compactor.py::test_stage0_fixture_diff`,
  `::test_idempotent_rerun`, `::test_supersession_records_lineage`,
  `::test_write_cap_aborts_gracefully`, `::test_reads_use_read_pool`.
- **Live:** after first nightly run post-deploy, `SELECT COUNT(*) FROM
  memory_facts WHERE topic='exterior_track_baseline'` is ≥ the count in
  the D1 oracle.

### D3: DAO additions

Two methods on `URADatabase`:

```python
async def add_memory_fact_row(self, *, node_id, topic, statement,
    attrs, confidence, derived_from) -> int | None:
    """INSERT OR IGNORE via _db() (write queue). Returns row id or
    None on duplicate."""

async def supersede_memory_fact(self, old_id: int, new_id: int) -> bool:
    """UPDATE memory_facts SET superseded_by=? WHERE id=? AND
    superseded_by IS NULL. Idempotent. Via _db(). Returns True iff
    a row was updated."""
```

Both mirror `log_memory_episode`'s error-handling shape (broad except
→ `_LOGGER.warning` → return None/False, never raise into caller).

Acceptance Criteria:
- **Verify:** double-supersede test — calling `supersede_memory_fact`
  twice on the same old_id returns True then False; the second call
  is a no-op (WHERE clause enforces idempotency).
- **Verify:** duplicate insert returns None; row count unchanged.
- **Test:** `tests/test_memory_dao_compactor.py`.

### D4: Nightly wiring + supervised manual button

Wire into `__init__.py:1978` `_cleanup_ops`:
```python
("memory_compact", "run_memory_compactor", {}),
```
Add thin adapter on `URADatabase`:
```python
async def run_memory_compactor(self) -> None:
    if not MEMORY_COMPACTOR_ENABLED or MEMORY_COMPACTOR_CADENCE_HOURS == 0:
        return
    from .memory_compactor import MemoryCompactor  # PLC0415
    stats = await MemoryCompactor(self).run()
    self._last_compactor_stats = stats  # for status sensor attribute
```
The cadence knob (§5) is enforced by comparing `now - last_run` to
`MEMORY_COMPACTOR_CADENCE_HOURS`; a nightly tick that fires more often
than the cadence is a no-op (defense against the maintenance loop
re-firing after a restart same night).

Add `button.ura_memory_compact_now` mirroring
`button.ura_memory_vacuum_now` (v5.5.7 precedent). Calls the same
adapter with a "manual" tag in stats.

Acceptance Criteria:
- **Verify:** entity `button.ura_memory_compact_now` present after
  reload.
- **Verify:** disabling via `MEMORY_COMPACTOR_ENABLED=False` (mutation
  drill: source-flip in test) makes both the nightly and the button
  return with no writes.
- **Live:** after first 02:30 tick post-deploy, `sensor.ura_memory_status`
  attribute `compactor_last_run` is populated and `facts_created` ≥ 0.

### D5: `sensor.ura_memory_status` attribute additions

Add to the existing sensor's `extra_state_attributes` (no new entity):
- `compactor_last_run` — ISO ts of most recent run
- `compactor_facts_created_last_run` — int
- `compactor_facts_superseded_last_run` — int
- `compactor_aborted_reason` — str or None

Read via `db._last_compactor_stats` (in-process, no DB round-trip).

Acceptance Criteria:
- **Verify:** attributes appear in state; missing stats render as None
  cleanly (boot-window resilience).
- **Live:** attributes visible in Developer Tools → States after first
  compactor run.

## 4. Restart resilience

- **A batch interrupted mid-run is safe.** Every fact write is
  `INSERT OR IGNORE` under UNIQUE(node_id, topic, statement); a
  re-run recomputes the same set and no-ops on already-committed rows.
- **Supersessions are idempotent** (WHERE `superseded_by IS NULL`
  clause).
- **The redaction stub does not run**, so the "raw-rows partially
  rolled up" edge case does not exist in this cycle. When redaction
  ships, the invariant §1 rule (fact commit before attrs UPDATE, in
  the same `_db()` context) makes the crash window safe: either
  neither committed (raw survives, will be re-attempted) or both
  committed (redacted, fact cites it).
- **Cadence guard** prevents double-runs same night after a restart at
  02:29:59 → 02:30:01.

## 5. Numbers on the knob ladder

Every behavioral number named + placed. All rung 1 (module constant,
per CLAUDE.md "Numbers Get Knobs" — these should require review to
change, not operator tuning; retro-analysis output feeds a code
change to the priority ints, not a live tune).

| Knob | Rung | Default | Kill-switch semantics |
|---|---|---|---|
| `MEMORY_COMPACTOR_ENABLED` | 1 (const.py) | `True` | `False` → nightly + button both no-op |
| `MEMORY_COMPACTOR_CADENCE_HOURS` | 1 | `24` | `0` → disabled (redundant kill switch); values >24 skip nights |
| `MEMORY_COMPACTOR_MAX_WRITES_PER_RUN` | 1 | `500` | Bounds write-queue exposure per run; hit → abort, resume next tick |
| `MEMORY_REDACTION_HORIZON_DAYS` | 1 | `None` | `None` → redaction stub is inert; integer enables the framework path |
| `MEMORY_COMPACTION_RULES` | 1 (dict) | See D2 registry | Empty dict → engine runs, does nothing |
| Per-rule `min_count` | 1 (nested) | Per-type (start with `exterior_track: 20`) | Setting to `sys.maxsize` disables the rule without deleting it |
| Per-rule `window_days` | 1 (nested) | Per-type (start with `exterior_track: 7`) | — |
| Per-rule `priority` | 1 (nested) | Per-type int | Lower priority rules skip earlier if cap hit |

Redaction-enable trigger (parked): if `SELECT COUNT(*) FROM
memory_episodes` grows > 20,000, revisit `MEMORY_REDACTION_HORIZON_DAYS`.
At current 1,799 rows the row-per-day accrual (~30/day) leaves margin
of ~1.5 years; that's the elaboration parking record.

## 6. Testing plan (independently-authored oracle)

- Fixture DB built by test setup INSERTs raw `memory_episodes` matching
  D1's exterior-track shape (real row shape, hand-selected subset —
  not machine-generated from the engine itself; hollow-anchor
  discipline).
- Oracle facts hand-written in the test file from D1's audit table;
  the compactor is diffed against this oracle.
- Mutation drills (per Tier 2-DB §C "test authority via REAL per-site
  source mutation"):
  1. Detach `INSERT OR IGNORE` → idempotent-rerun test must fail.
  2. Detach `supersede_memory_fact`'s `AND superseded_by IS NULL`
     clause → double-supersede test must fail (would flip back).
  3. Swap compactor's `db.read_memory_episodes` → open a raw
     connection → "reads-use-read-pool" test must fail (proves the
     Stage-1 HIGH-B guard is under test in the compactor too).
- Full memory suite (32/32 baseline per Stage-1 record) must remain
  green; suite baseline diff before deploy.

## 7. Review posture

- **Plan review (this doc):** ONE adversarial pass before build
  dispatch. Reviewer's mandatory checks:
  (a) re-grep for prior compaction/distill code (should find zero); confirm the "no prior art" claim;
  (b) independently re-enumerate distillation-rule surfaces from
      `MEMORY_EPISODE_TYPES` and confirm the registry structure covers
      all live counts (1044+639+56+41+19 = 1799 rows are addressable);
  (c) verify falsifiable invariant is falsifiable;
  (d) verify every number in §5 sits on the correct rung.
- **Build reviews:** Tier 2-DB three framing-disjoint reviews:
  - **A — data integrity:** invariant §1 holds under all rule paths;
    supersession never loses lineage; `INSERT OR IGNORE` behavior.
  - **B — migration/signal integrity:** the two new DAOs use `_db()`;
    reads via DAOs never re-fall onto the write queue; the nightly
    wiring is placed in the rotation without displacing existing ops.
  - **C — new surface / test authority:** button round-trips through
    HA restart; fixture is independently authored (not engine-echoed);
    the three mutation drills each fail a specific test on detach and
    restore green.
- **Live validation (Review D):** post-restart, sensor attribute
  populates after first 02:30 tick; DB reads confirm ≥ 1
  `topic='exterior_track_baseline'` row per active zone with matching
  D1 statement text.
- **README write-back mandatory** after live validation.

## 8. Build size estimate

- D1 (hand-compact audit): ~4h (SQL probes + write-up).
- D2 (engine): ~250–300 LoC + ~200 LoC tests.
- D3 (DAOs): ~40 LoC + ~60 LoC tests.
- D4 (wiring + button): ~30 LoC + ~40 LoC tests.
- D5 (sensor attrs): ~15 LoC + ~20 LoC tests.
- Total: ~600 LoC + ~350 LoC tests. Fits inside a single Tier 2-DB
  build session.

## 9. Explicit deferrals (accountable, per CLAUDE.md)

- **Full attrs_json redaction** — framework only; enable trigger in §5.
- **Cross-node fact synthesis (adjacency graph, house-level rollups)**
  — separate cycle, not gated on this one.
- **Per-consumer priority tuning from MEMORY-RETRO-VALUE-1** — plug in
  via registry priority ints when that card lands; no code change to
  the engine needed.
- **Operator adjudication service** (per Arch §10) — separate cycle;
  compactor treats `adjudication='unadjudicated'` rows conservatively
  (rules can require confirmed-only via a per-rule
  `require_adjudicated=True`; default True — unadjudicated rows do
  NOT feed distillation, matching Arch §5c step 1).
