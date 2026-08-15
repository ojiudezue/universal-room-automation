# PLANNING — Hierarchical Memory COMPACTOR (Stage 2)

Card: **MEMORY-COMPACTOR-1**
Tier: **Tier 2-DB** (touches `database.py` + the shipped facade primitive;
downstream shape/lineage-critical). Plan-review: FIX-PLAN-FIRST verdict
(rev-1) — see `docs/reviews/code-review/memory_compactor_plan_review.md`
commit `9c19ac35f`. This is **rev-2**, absorbing all 2 CRIT + 2 HIGH +
3 MED + 2 LOW findings. Ready-to-build after operator confirms two
knobs (§10).
Sizing target: **small and finishable** — thinnest compactor that honors
`ARCHITECTURE_hierarchical_memory.md §5c`. Elaborations parked with
evidence triggers, not built.

Downstream of:
- `docs/planning/ARCHITECTURE_hierarchical_memory.md §5c` (distill /
  correct / redact — the design; this plan builds it, does not redesign).
- `docs/planning/AUDIT_memory_handbuild_study_a.md` (Stage-0 fixture
  precedent; this cycle produces a sibling hand-compaction fixture).
- `docs/planning/AUDIT_memory_retro_value.md` (MEMORY-RETRO-VALUE-1;
  input to per-type distillation priority — see §3 / §D1 adjudication).
- `docs/reviews/code-review/memory_mvp_tier2db.md` (Stage-1 review
  record; the compactor MUST NOT regress its five fixed HIGHs — in
  particular **reads-on-write-queue** (HIGH B; see HIGH-2 fix, §D2 +
  §6 drill #4) and **Welford M2 decay** (MED A; untouched here)).

---

## 0. Institutional context verified

### Greps run + results (proof-of-work)

- **`log_memory_episode` writer path** — `database.py:8433` writes through
  `self._db()` (single-writer worker). Reads use `self._db_read()` —
  `database.py:470`. REUSE both; do not introduce a third path.
- **`_db()` semantics (CRIT-1 grounding)** — verified at
  `database.py:322-421`: every acquisition enqueues on
  `self._write_queue` and each queued item runs its own execute + commit
  in the FIFO worker. Two DAO calls = two queue submissions = two
  distinct SQLite transactions (worker-serialized, but NOT atomic
  together). `_db()` cannot be nested by callers. This forces the
  combined-DAO shape in §D3 (CRIT-1 fix Option B).
- **`read_memory_episodes` / `read_memory_facts`** — `database.py:8597`
  / `:8645`, both on `_db_read()`. REUSE — these are the ONLY two
  reads the compactor is allowed to make (§D2, HIGH-2 fix).
- **`memory_facts` schema** — `database.py:1551` — carries
  `UNIQUE(node_id, topic, statement)` and `superseded_by`. NEW COMBINED
  DAO required: `distill_memory_fact(...)` — one `_db()` acquisition,
  INSERT OR IGNORE + optional supersede UPDATE + (future) redaction-mark
  UPDATE, single `commit()`. See §D3.
- **`MEMORY_EPISODE_TYPES`** — `const.py:3642`, 10 entries (not 5 — the
  retro cites the 5 with live rows). Registry keys asserted subset at
  boot.
- **`MEMORY_FACT_TOPICS`** — `const.py:3660`, frozenset of 5 topics
  today: `occupancy_reliability`, `sensor_trust`, `occupancy_baseline`,
  `notification_hygiene`, `adjacency_graph`. The compactor emits topics
  not in this set → CRIT-2 requires amending it (§D0) + symmetric
  boot-time assert.
- **Nightly maintenance loop** — `__init__.py:1977` `_cleanup_ops` list
  literal; first tuple at `:1978`. Insertion position for the compactor
  op tuple: **AFTER `("incremental_vacuum", ...)`**, i.e. at the end of
  the list (LOW-1). Rotating start index (`__init__.py:2030`) means
  every op runs every night unless the 5-min budget bites; end-of-list
  placement rides free.
- **Adjacent primitive — `incremental_vacuum`** — `database.py:8094`.
  Doctrine borrowed: bounded cap constant, no-op cleanly when
  disabled/not-applicable, writes through single-writer worker under
  the 120s guard, supervised manual button variant. Compactor mirrors
  every one.
- **`sensor.ura_memory_status`** — verified at `sensor.py:4466`;
  attribute additions per D5 attach here (no new entity).
- **v5.2.1 write-flood postmortem** — the flood shape was
  per-cycle-per-room continuous writes (bursty at every state change).
  A nightly compactor bounded to ≤ `MEMORY_COMPACTOR_MAX_WRITES_PER_RUN`
  (default 500, §5) run once per 24h is orders of magnitude below that
  sustained rate. Observability: MED-2 fix adds
  `compactor_writes_last_run` to §D5 so cap-biting is visible.
- **No prior compaction/distill code** — grep for `distill`, `compact`,
  `roll.?up` across `custom_components/universal_room_automation/`
  returns only `incremental_vacuum`, `_cleanup_ops` prunes, and the
  MVP's "compactor DEFERRED" comment at `database.py:1530`. Confirmed:
  no prior art.

### Prior planning docs consulted

- `ARCHITECTURE_hierarchical_memory.md` — full read, §5c is normative.
- `AUDIT_memory_handbuild_study_a.md` — full read; fixture precedent
  for Stage 0.
- `AUDIT_memory_retro_value.md` — full read; drives §D1 adjudication
  (HIGH-1 fix) and §5 rule-registry priority seeding.
- `MVP_hierarchical_memory.md` — headers skimmed for the "compactor
  DEFERRED per MVP parsimony pass" language.

### Memory bodies pulled

- `feedback_measure_before_build.md` — Stage 0 hand-compact D1 satisfies.
- `feedback_marginal_benefit_pushback.md` — applied in §7 (redaction
  stub) and §D1 (why engine-first not value-first).
- `feedback_suppression_needs_discharge.md` — cadence knob has a
  discharge (next nightly tick); no one-shot suppression.
- `feedback_hollow_test_anchors.md` — fixtures hand-built, independently
  authored; four mutation drills, each must fail a named test.

### Design docs / code locations read end-to-end during scoping

- `database.py` §§ around `memory_episodes` DDL (1527–1600),
  `log_memory_episode` (8380–8455), `read_memory_episodes` (8597),
  `read_memory_facts` (8645), `incremental_vacuum` (8071–8154),
  `_db`/`_db_read` (322–485).
- `memory_facade.py` around `episodes()` (438–476) and `facts()`
  (920–945) — the read-consumer surface the compactor must not break.
- `const.py` 3600–3745 (memory constants + episode-type registry +
  fact-topic registry + seed facts).
- `__init__.py` 1975–2062 (nightly-maintenance wiring surface).
- `sensor.py:4466` (`sensor.ura_memory_status` — attribute host).

---

## 1. Falsifiable invariant (rev-2, honest to the write-queue architecture)

**INVARIANT (Compactor Preservation of Evidence, via combined-DAO
atomicity + FIFO worker ordering):**

> **(a) Atomicity, per fact.** Every `memory_facts` INSERT and its
> paired `superseded_by` UPDATE (when a correction is emitted) are
> issued inside ONE `_db()` acquisition — one queue submission, one
> `commit()`. A reader between commits therefore never sees a
> new-without-old or old-without-new inconsistent state for that fact.
> When the redaction path lands in a future cycle, the redaction-mark
> UPDATE against `memory_episodes.attrs_json` is issued inside the
> SAME `_db()` acquisition as the fact write it depends on — one
> commit — so the raw-episode rollup is atomic with the fact that
> cites it.
>
> **(b) Ordering, cross-fact.** Where two logically-related writes
> cannot be combined into a single DAO call (rare — reserved for the
> future adjacency-graph rollup where a house-fact depends on multiple
> per-room facts), ordering is guaranteed by the single-writer worker's
> FIFO queue: the earlier `_db()` acquisition is enqueued first,
> committed first, and visible to any subsequent read.
>
> **(c) Preservation.** `count(memory_episodes)` never decreases across
> a compactor run. Redaction (when enabled) is a shape transform on
> `attrs_json`, not a DROP. Facts are never edited in place;
> corrections write a new row and set `superseded_by` on the old.
> For any episode whose `attrs_json` was rolled up, at least one
> `memory_facts` row with a `derived_from` string containing that
> episode's id is committed and reachable (non-superseded) at the
> moment the rollup UPDATE commits — guaranteed by (a) placing both
> in the same transaction.

Operationally verifiable:
- `count(memory_episodes)` non-decreasing across a run.
- No fact row is ever the target of an in-place `UPDATE` of
  `statement`, `attrs_json`, `derived_from`, or `confidence`.
- `SELECT id, superseded_by FROM memory_facts WHERE superseded_by IS
  NOT NULL` — every such row has a target whose `derived_from` cites
  the superseded row's id.
- For any episode rolled up (future), `SELECT 1 FROM memory_facts
  WHERE derived_from LIKE '%<ep.id>%' AND superseded_by IS NULL`
  returns ≥ 1 row.

Tier 2-DB Review-A/B/C each try to break this invariant; §6 tests
exercise each half.

## 2. Non-goals (explicit)

- **No new query verbs.** `facts()` / `episodes()` / `narrative()` are
  the read surface.
- **No schema redesign.** `memory_episodes` + `memory_facts` shipped in
  v5.47.0 are load-bearing as-is. No ALTER, no new column, no new table.
- **No cross-node fact synthesis.** House-level roll-ups
  (adjacency graph — Arch §5b) are OUT OF SCOPE and PARKED.
- **Redaction of `attrs_json` is a STUB.** Framework path exists;
  `MEMORY_REDACTION_HORIZON_DAYS = None` = disabled (see §5 for the
  operator-confirm trigger). Rationale: marginal benefit of full
  redaction is small when total episode volume is ~1,805 rows
  (retro-audit 2026-08-14 counts: exterior_track 1050 +
  actuation_conflict 639 + occupancy_phantom 56 + fan_transition_suppressed 41 +
  comfort_fan_vetoed 19 = 1,805); the largest ingredient risk is
  losing evidence, which is exactly what the framework-only stub
  avoids.
- **No LLM in the loop.** Distillation rules are registered per-type
  transparent statistics.
- **No new sensor entities.** Compactor stats attach to existing
  `sensor.ura_memory_status` as observation-only attributes (LOW-2).

## 3. Deliverables

### D0: `MEMORY_FACT_TOPICS` vocabulary amendment (CRIT-2 fix)

Amend `const.py:3660` `MEMORY_FACT_TOPICS` to include every topic the
shipped rule registry emits. Rev-2 shipping set:

- `exterior_track_baseline` — per-camera/label daily baselines (rule
  seeded from D1 hand-compact).
- `phantom_recurrence` — per-room phantom-rate + typical fan-on
  duration (from `occupancy_phantom`; retro highest-priority).
- `actuation_conflict_daily` — per-(room, action, trigger, house_state)
  daily counts with first/last timestamps (from `actuation_conflict`;
  retro's aggressive-compaction target).

Add symmetric boot-time assert (mirroring the episode-type assert
proposed in §D2): every `topic` referenced by a registered rule MUST
be in `MEMORY_FACT_TOPICS`. Placed in `memory_compactor.py` module-load
guard; import-time failure surfaces before any write.

Impact grep: no NM/dashboard consumer switches on the current five
topic values (confirmed — facade `facts()` filters by topic string
but has no switch/whitelist). Additive change; no reader impact.

Acceptance Criteria:
- **Verify:** `MEMORY_FACT_TOPICS` frozenset contains the three new
  topics; `python -c "from custom_components.universal_room_automation
  import memory_compactor"` succeeds.
- **Verify:** removing any one topic from `MEMORY_FACT_TOPICS` makes
  compactor import fail with the assert message (mutation drill).
- **Test:** `tests/test_memory_compactor.py::test_topic_vocabulary_gate`.

### D1: Stage-0 hand-compact of `exterior_track` — engine-proving fixture

**Adjudication vs `AUDIT_memory_retro_value.md` (HIGH-1 fix):** the
retro ranks `occupancy_phantom` as highest-signal per row and
`exterior_track` as lowest per row but rich in attrs. This plan picks
Reading A (engine-first): **`exterior_track` is the D1 fixture because
its shape is regular (linker-produced, uniform attrs across all 1,050
rows) and volume is highest, which stresses the distillation-rule
mechanics without conflating with adjudication semantics.** The
`occupancy_phantom` value case is not deferred — it lands in D2's
registry as the HIGHEST-priority rule (see below), with its own
smaller hand-checked spot-fixture built inline in the test file.

Produce `docs/planning/AUDIT_memory_handbuild_compactor_exterior_track.md`:
- Read all 1,050 `exterior_track` rows from the live DB (RO probe).
- Hand-apply a distillation rule (proposed: **N ≥ 20 tracks of same
  `label` within a rolling 7-day window on the same `camera` or
  `zone` → propose/refresh a fact under
  `topic=exterior_track_baseline`** with statement citing count +
  label distribution + typical span; `derived_from` = comma-joined
  episode ids).
- **Freeze the `statement_fn` template in D1 (MED-1 fix).** The
  hand-oracle statements MUST be generatable from a pure function
  `(rows_in_window, node_id, topic) -> (statement: str, attrs: dict)`.
  If the auditor finds herself writing phrasing that requires human
  judgment, freeze the template first and re-generate the oracle from
  it. That frozen template IS the `statement_fn` D2 implements.
- Commit the resulting hand-written facts table + the raw-rows-→-facts
  mapping as the acceptance oracle.
- Note any type-shape surprises the automated compactor must handle.

Acceptance Criteria:
- **Verify:** file exists at planned path with the mapping table and
  the frozen `statement_fn` pseudocode block.
- **Verify:** every raw episode id appears in exactly one fact's
  `derived_from` (invariant §1(c) in the hand version).
- **Verify:** the `statement_fn` template is deterministic — the same
  input rows produce the same output tuple (no timestamps in
  statement text, no set-ordering ambiguity).
- **Live:** D1 is a pre-build deliverable; no HA involvement.

### D2: `MemoryCompactor` engine + distillation-rule registry

New module `custom_components/universal_room_automation/memory_compactor.py`
(one class, ≤ ~300 LoC target). Interface:

```python
async def run(self, *, now: datetime | None = None) -> dict:
    """One compactor pass. Returns stats dict (facts_created,
    facts_superseded, episodes_redacted, writes_total, aborted_reason)."""
```

**Read discipline (HIGH-2 fix — CRIT-blocking on review if violated):**
> The compactor engine has EXACTLY TWO read callsites:
> `db.read_memory_episodes` and `db.read_memory_facts`. Any new read is
> a new DAO added to `URADatabase` (routed via `_db_read()`) and
> covered by its own mutation drill. A raw `aiosqlite.connect(...)`
> anywhere inside `memory_compactor.py` is a CRIT-blocking review
> finding.

Idempotency-check rationale: `INSERT OR IGNORE` on the
`UNIQUE(node_id, topic, statement)` index makes "does this fact
already exist" moot; the compactor does not need to pre-check.

**Write discipline (CRIT-1 fix — combined DAO):** the engine emits
each logical (fact-insert [+ optional supersede]) pair via ONE call to
`db.distill_memory_fact(...)` (see §D3), which opens ONE `_db()`
context and issues INSERT OR IGNORE + supersede UPDATE + one
`commit()`. The engine never opens `_db()` itself; it never issues
two writes for one logical fact.

Registry: `MEMORY_COMPACTION_RULES` in `const.py`, a mapping
`episode_type -> {min_count, window_days, topic, statement_fn,
require_adjudicated, priority}`. Keys asserted subset of
`MEMORY_EPISODE_TYPES`; every `topic` value asserted member of
`MEMORY_FACT_TOPICS` (both asserts at compactor import time — CRIT-2).

**Rev-2 seeded rules (HIGH-1 fix — retro-informed priority):**

| Priority | episode_type | topic | min_count | window_days | require_adjudicated | Rationale |
|---|---|---|---|---|---|---|
| 1 | `occupancy_phantom` | `phantom_recurrence` | 3 | 30 | True | Retro's highest per-row value; all 56 rows self-adjudicated `d2_demotion` in the D2 path; distills to per-room phantom rate + typical fan-on duration. Small hand-checked spot-fixture inline in test file. |
| 2 | `actuation_conflict` | `actuation_conflict_daily` | 20 | 7 | False | Retro's aggressive-compaction target (639 rows dominated by identical 5-min-tick repeats). Compact to (room, action, trigger, house_state) daily counts with first/last timestamps. Small hand-checked spot-fixture inline in test file. |
| 3 | `exterior_track` | `exterior_track_baseline` | 20 | 7 | False | D1 hand-compact fixture-first. Largest bucket, most regular shape — best engine stressor. |

Engine loop (per rule, priority order):
1. **Distill** — for each node, `read_memory_episodes(node, type,
   since)`; if `require_adjudicated`, filter `adjudication !=
   'unadjudicated'`; if count ≥ `min_count`, build `(statement, attrs)`
   via `statement_fn` (pure, no I/O); call
   `db.distill_memory_fact(node_id, topic, statement, attrs,
   confidence, derived_from, supersede_old_id=None)`. Idempotent
   re-runs are no-ops on the UNIQUE index.
2. **Correct** — a NEW fact's structured `attrs` (canonical
   contradiction-detection form, per MED-3 resolution — see below)
   contradicts a CURRENT fact under the same `(node_id, topic)`. The
   engine passes `supersede_old_id=<old.id>` to the same
   `distill_memory_fact` call; the DAO issues INSERT + UPDATE in ONE
   commit (invariant §1(a)).
3. **Redact** — STUB. If `MEMORY_REDACTION_HORIZON_DAYS` is not None
   AND an episode of a type whose fact exists is older than the
   horizon, transform `attrs_json` to a rollup shape via the same
   combined DAO extended with a `redact_episode_id` arg (framework
   only; default None → this branch never executes).

Batch cap: at most `MEMORY_COMPACTOR_MAX_WRITES_PER_RUN` combined
writes per run. On hit → log info, set `aborted_reason='cap'`, return.
Next nightly run resumes deterministically (rules are ordered;
`INSERT OR IGNORE` makes redoing already-emitted facts a no-op; §4).

**Resolved open decisions (MED-3):**
1. **`statement_fn` shape** — RESOLVED: pure function, template
   frozen in D1 (see §D1 MED-1 fix).
2. **Correction trigger** — RESOLVED: rules produce `(statement: str,
   attrs: dict)`. `attrs` is the canonical structured form used for
   contradiction detection. `statement` is the human-readable
   rendering. Contradiction = new `attrs` differs from current fact's
   `attrs` under matching `(node_id, topic)` — deterministic dict
   equality per registered comparator (default: exact dict equality
   after key sort).
3. **`require_adjudicated` default** — RESOLVED: per-rule, per Arch
   §5c step 1 ("N+ same-type ADJUDICATED episodes"). See registry
   table above (default True for `occupancy_phantom`; False for
   volume-only rules like `actuation_conflict`/`exterior_track` where
   unadjudicated observation is the useful signal).

Boot-time asserts (in `memory_compactor.py` module load):
- `set(MEMORY_COMPACTION_RULES.keys()) <= MEMORY_EPISODE_TYPES`.
- `{r['topic'] for r in MEMORY_COMPACTION_RULES.values()} <=
  MEMORY_FACT_TOPICS`.

Acceptance Criteria:
- **Verify:** unit tests drive the engine against a fixture DB seeded
  with the D1 hand-built shape and diff resulting `memory_facts` rows
  against the D1 oracle (exact statement + derived_from set equality).
  Fixture-diff test is the load-bearing acceptance.
- **Verify:** inline spot-fixtures for `occupancy_phantom` (~3 rows,
  hand-adjudicated) and `actuation_conflict` (~20 rows of identical
  5-min-tick shape) each produce their expected single fact.
- **Verify:** mutation drill (see §6) — delete `INSERT OR IGNORE` →
  idempotent-rerun test MUST fail (UNIQUE violation).
- **Test:** `tests/test_memory_compactor.py::test_stage0_fixture_diff`,
  `::test_phantom_rule_spot`, `::test_actuation_conflict_rule_spot`,
  `::test_idempotent_rerun`, `::test_supersession_records_lineage`,
  `::test_supersession_atomic_single_commit`,
  `::test_write_cap_aborts_gracefully`,
  `::test_reads_use_read_pool`,
  `::test_no_raw_aiosqlite_in_compactor`.
- **Live:** after first nightly run post-deploy, `SELECT COUNT(*) FROM
  memory_facts WHERE topic IN ('phantom_recurrence',
  'exterior_track_baseline', 'actuation_conflict_daily')` returns ≥ 3
  distinct topics with ≥ 1 row each.

### D3: Combined DAO + supersession primitive (CRIT-1 fix)

One combined DAO on `URADatabase`:

```python
async def distill_memory_fact(
    self,
    *,
    node_id: str,
    topic: str,
    statement: str,
    attrs: dict,
    confidence: float,
    derived_from: str,
    supersede_old_id: int | None = None,
    redact_episode_id: int | None = None,  # framework-only; default off
) -> dict:
    """Atomic compactor write: INSERT OR IGNORE the fact; if
    supersede_old_id is set, UPDATE that row's superseded_by to point
    at the new row; if redact_episode_id is set (future),
    UPDATE memory_episodes.attrs_json to the rollup shape. All inside
    ONE _db() acquisition -> ONE commit(). Returns
    {inserted_id: int|None, superseded: bool, redacted: bool}."""
```

Implementation (single `_db()` context):
1. INSERT OR IGNORE the fact row; capture `cursor.lastrowid`.
2. If `supersede_old_id is not None` AND a new row was inserted:
   `UPDATE memory_facts SET superseded_by=? WHERE id=? AND
   superseded_by IS NULL` (idempotent — WHERE clause).
3. If `redact_episode_id is not None` (future path; asserts
   `MEMORY_REDACTION_HORIZON_DAYS is not None` — else raise): UPDATE
   the episode's `attrs_json` to rollup shape.
4. Single `commit()`.

Error-handling mirrors `log_memory_episode` (broad except →
`_LOGGER.warning` → return `{"inserted_id": None, "superseded":
False, "redacted": False}`; never raise into the engine).

Acceptance Criteria:
- **Verify:** insert-then-supersede via one call issues exactly ONE
  `commit()` (test hooks `aiosqlite.Connection.commit` and asserts
  call count == 1).
- **Verify:** double call with same `(node_id, topic, statement)`
  returns `inserted_id=None` on second call; row count unchanged;
  supersede branch does NOT fire when INSERT was IGNORED.
- **Verify:** `supersede_old_id` for an already-superseded row is a
  no-op (WHERE-guarded).
- **Verify:** `redact_episode_id` passed with
  `MEMORY_REDACTION_HORIZON_DAYS=None` raises `AssertionError` (guards
  the framework-only path from accidental use).
- **Test:** `tests/test_memory_dao_compactor.py::test_atomic_single_commit`,
  `::test_insert_ignore_no_supersede`,
  `::test_double_supersede_noop`,
  `::test_redact_guard_when_disabled`.

### D4: Nightly wiring + supervised manual button

Wire into `__init__.py:1977` `_cleanup_ops`, **appended AFTER
`("incremental_vacuum", ...)`** (LOW-1):
```python
("memory_compact", "run_memory_compactor", {}),
```
Add thin adapter on `URADatabase`:
```python
async def run_memory_compactor(self) -> None:
    if not MEMORY_COMPACTOR_ENABLED or MEMORY_COMPACTOR_CADENCE_HOURS == 0:
        return
    # Cadence guard: skip if last run was less than cadence ago.
    if self._compactor_within_cadence():
        return
    from .memory_compactor import MemoryCompactor  # PLC0415
    stats = await MemoryCompactor(self).run()
    self._last_compactor_stats = stats  # for status sensor attribute
```
Cadence guard defends against the maintenance loop re-firing after a
restart the same night.

Add `button.ura_memory_compact_now` mirroring the v5.5.7
`button.ura_memory_vacuum_now` precedent. Button bypasses the cadence
guard (supervised manual override) and tags stats with
`triggered_by='manual'`.

Acceptance Criteria:
- **Verify:** entity `button.ura_memory_compact_now` present after
  reload; press invokes `run_memory_compactor` with manual override.
- **Verify:** disabling via `MEMORY_COMPACTOR_ENABLED=False` (mutation
  drill: source-flip in test) makes both nightly and button return
  with no writes.
- **Verify:** cadence guard — two nightly calls 5 minutes apart
  produce one run + one skip.
- **Live:** after first 02:30 tick post-deploy, `sensor.ura_memory_status`
  attribute `compactor_last_run` populated and `facts_created` ≥ 0.

### D5: `sensor.ura_memory_status` attribute additions (observation-only)

Add to the existing sensor's `extra_state_attributes` (no new entity,
observation-only per LOW-2 — NOT knobs, NOT persisted, in-process
only):
- `compactor_last_run` — ISO ts of most recent run
- `compactor_facts_created_last_run` — int
- `compactor_facts_superseded_last_run` — int
- `compactor_writes_last_run` — int (MED-2: cap-biting visibility)
- `compactor_aborted_reason` — str or None
- `compactor_triggered_by` — `"nightly"` | `"manual"` | None

Read via `db._last_compactor_stats` (in-process). Missing stats (boot
window, before first run) render as None cleanly.

Grep confirmed: no dashboard/NM/template consumer switches on
`sensor.ura_memory_status` attributes today; additive change is safe.

Acceptance Criteria:
- **Verify:** attributes appear in state; missing stats render as None
  without exception.
- **Verify:** attribute values are read-only from HA's perspective —
  no service call mutates them (they are pure observation).
- **Live:** attributes visible in Developer Tools → States after first
  compactor run; `compactor_writes_last_run` populated with a small
  integer.

## 4. Restart resilience (rev-2 honest write-up)

- **Per-fact atomicity (invariant §1(a)).** A crash inside
  `distill_memory_fact` before its single `commit()` leaves ZERO of
  its writes applied (the aiosqlite transaction rolls back on
  connection close without commit). Re-run recomputes and commits
  cleanly. A crash AFTER commit is a no-op state (fact present, next
  run's INSERT OR IGNORE returns no-row).
- **Cross-fact ordering (invariant §1(b)).** The single-writer worker
  processes the queue FIFO; a crash between two enqueued DAO calls
  simply drops the un-processed tail. Next nightly run re-enqueues
  from a deterministic rule-ordered scan; INSERT OR IGNORE makes
  already-processed facts no-ops.
- **Redaction stub does not run** in rev-2 (`MEMORY_REDACTION_HORIZON_DAYS
  = None`). When it lands: the combined DAO places the
  redaction UPDATE inside the SAME commit as the fact write, so
  "fact committed, episode not redacted" is not a reachable state
  for a rule that redacts. For rules that distill without redacting,
  no episode is ever modified, so the question does not arise.
- **Cadence guard** prevents double-runs the same night after a
  02:29:59 → 02:30:01 restart window.
- **Write cap** enforces a hard ceiling on write-queue exposure per
  run. Hit → abort with `aborted_reason='cap'`; the next tick picks
  up idempotently (all writes are INSERT OR IGNORE or WHERE-guarded
  UPDATEs).

## 5. Numbers on the knob ladder

Every behavioral number named + placed. All rung 1 (module constant,
per CLAUDE.md "Numbers Get Knobs" — these should require review to
change; retro-analysis output feeds a code change to the priority ints
in `MEMORY_COMPACTION_RULES`, not a live tune).

| Knob | Rung | Default | Kill-switch semantics | Operator confirm before build? |
|---|---|---|---|---|
| `MEMORY_COMPACTOR_ENABLED` | 1 (const.py) | `True` | `False` → nightly + button both no-op | No |
| `MEMORY_COMPACTOR_CADENCE_HOURS` | 1 | `24` | `0` → disabled (redundant kill switch); values >24 skip nights | **YES (§10)** — 02:30 tick placement vs 03:30 alternative |
| `MEMORY_COMPACTOR_MAX_WRITES_PER_RUN` | 1 | `500` | Hit → abort, resume next tick. Cited-anchor: well below the v5.2.1 sustained per-cycle-per-room flood rate (nightly cap ÷ ~86,400s ≈ 0.006 writes/s spread; the flood was bursty at every state-change event). `compactor_writes_last_run` (§D5) tracks approach to cap. | No |
| `MEMORY_REDACTION_HORIZON_DAYS` | 1 | `None` | `None` → redaction stub inert; integer enables framework path | **YES (§10)** — parked-plan review discipline; the 20,000-row revisit trigger below is a suggestion, not a decision |
| `MEMORY_COMPACTION_RULES` | 1 (dict) | See §D2 rev-2 seeded table | Empty dict → engine runs, does nothing | No |
| Per-rule `min_count` | 1 (nested) | Per-type (registry defaults) | `sys.maxsize` disables the rule without deleting it | No |
| Per-rule `window_days` | 1 (nested) | Per-type (registry defaults) | — | No |
| Per-rule `priority` | 1 (nested) | Per-type int (retro-informed: phantom < actuation_conflict < exterior_track) | Lower priority rules skip earlier if cap hit | No |
| Per-rule `require_adjudicated` | 1 (nested) | Per-rule (True for `occupancy_phantom`, False for volume rules) | — | No |

Redaction-enable revisit trigger (parked): if `SELECT COUNT(*) FROM
memory_episodes` grows > 20,000, revisit `MEMORY_REDACTION_HORIZON_DAYS`.
At retro-audit 1,805 rows and the current ~30 rows/day accrual rate,
this leaves ~1.6 years of margin. That's the parking record.

## 6. Testing plan (independently-authored oracle + four mutation drills)

- Fixture DB built by test setup INSERTs raw `memory_episodes` matching
  D1's exterior-track shape + inline `occupancy_phantom` (~3 rows) +
  `actuation_conflict` (~20 rows) spot-fixtures. Real row shapes,
  hand-selected subsets — NOT machine-generated from the engine itself
  (hollow-anchor discipline per `feedback_hollow_test_anchors.md`).
- Oracle facts hand-written in the test file from D1's audit table and
  the two inline spots; compactor is diffed against this oracle.

**Mutation drills (Tier 2-DB §C "test authority via REAL per-site
source mutation"):**
1. **Detach `INSERT OR IGNORE`** in `distill_memory_fact` → the
   idempotent-rerun test MUST fail (UNIQUE violation).
2. **Detach `AND superseded_by IS NULL`** from the supersede UPDATE →
   the double-supersede-noop test MUST fail.
3. **Swap** the compactor's `db.read_memory_episodes` for an open
   raw connection → the `test_reads_use_read_pool` test MUST fail.
4. **HIGH-2 mutation drill #4.** Insert an `aiosqlite.connect(...)`
   call anywhere in `memory_compactor.py` →
   `test_no_raw_aiosqlite_in_compactor` MUST fail. Test implementation:
   AST-scan the compactor module (or import-time introspection) for
   any reference to `aiosqlite.connect`; presence = fail. Enforces the
   HIGH-2 hard rule from §D2 that reads on that module are limited to
   the two sanctioned DAOs.

Full memory suite (32/32 baseline per Stage-1 record) must remain
green; suite baseline diff before deploy.

## 7. Review posture

- **Plan review:** rev-1 → FIX-PLAN-FIRST verdict (2 CRIT / 2 HIGH /
  3 MED / 2 LOW), all addressed in this rev-2. Reviewer should re-verify
  CRIT-1 wording + D3 combined-DAO shape + CRIT-2 vocabulary
  amendment + §D1 HIGH-1 adjudication paragraph + §D2 HIGH-2 hard
  rule + drill #4 in §6 as the primary re-check surface.
- **Build reviews:** Tier 2-DB three framing-disjoint reviews:
  - **A — data integrity:** invariant §1 holds under all rule paths;
    supersession never loses lineage; INSERT OR IGNORE behavior;
    single-commit atomicity of D3.
  - **B — migration/signal integrity:** the combined DAO uses `_db()`
    exactly once per logical fact; reads via DAOs never re-fall onto
    the write queue; nightly wiring appended AFTER
    `incremental_vacuum` (LOW-1); cadence guard defends
    same-night restart.
  - **C — new surface / test authority:** button round-trips through
    HA restart; fixture is independently authored (not engine-echoed);
    the four mutation drills each fail a specific test on detach and
    restore green; boot-time asserts (episode-type ⊂,
    topic ⊂) trip on hostile registry.
- **Live validation (Review D):** post-restart, sensor attribute
  populates after first 02:30 tick; DB reads confirm ≥ 1 row under
  each of the three shipped topics; `compactor_writes_last_run` is a
  small integer well below cap.
- **README write-back mandatory** after live validation.

## 8. Build size estimate

- D0 (topic vocabulary + assert): ~10 LoC production + ~20 LoC tests.
- D1 (hand-compact audit + frozen `statement_fn` template): ~4h
  (SQL probes + write-up + template design).
- D2 (engine + registry): ~280 LoC + ~250 LoC tests.
- D3 (combined DAO): ~60 LoC + ~80 LoC tests.
- D4 (wiring + button + cadence guard): ~40 LoC + ~50 LoC tests.
- D5 (sensor attrs): ~20 LoC + ~25 LoC tests.
- Total: ~410 LoC production + ~425 LoC tests. Fits one Tier 2-DB
  build session.

## 9. Explicit deferrals (accountable, per CLAUDE.md)

- **Full `attrs_json` redaction** — framework in D3 + boot-time
  guard; enable trigger in §5 (operator confirms threshold — §10).
- **Cross-node fact synthesis (adjacency graph, house-level rollups)**
  — separate cycle; NOT gated on this one. The combined DAO deliberately
  does not extend to "insert house-fact + N per-room fact refs" —
  that's the future invariant §1(b) cross-fact ordering case, and its
  atomicity story (if needed) is a Tier-3 problem for that cycle.
- **Operator adjudication service** (per Arch §10) — separate cycle;
  compactor's `require_adjudicated=True` rules skip unadjudicated rows
  until the service lands.
- **`comfort_fan_vetoed` and `fan_transition_suppressed` rules** —
  registered types with live rows but not seeded in rev-2's registry;
  the retro ranks them below the top three by value/compressibility.
  Additive future work; the engine mechanically supports any new rule
  the moment its topic is added to `MEMORY_FACT_TOPICS`.
- **Missing episode-type writers listed in retro §"Missing episode
  types"** — writer additions are OUT OF SCOPE for the compactor
  cycle; each is its own future ticket.

## 10. Operator-confirm checklist (blocking build dispatch)

Two knobs default-set in the plan but flagged for operator confirmation
before build (MED-3, items 4 and 5):

- [ ] **Cadence tick placement.** Default: piggyback on the existing
      02:30 nightly maintenance loop (compactor op appended after
      `incremental_vacuum`). Alternative: 03:30 tick separate from
      main maintenance rotation. Operator confirms 02:30 stays.
- [ ] **Redaction threshold parked-plan.** Rev-2 ships redaction
      disabled (`MEMORY_REDACTION_HORIZON_DAYS = None`). Parked
      revisit trigger is `> 20,000 rows in memory_episodes`. Operator
      confirms this threshold (or replaces it) as the standing
      condition for the next planning pass on redaction.
