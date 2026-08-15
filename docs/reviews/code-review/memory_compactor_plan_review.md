# PLAN REVIEW — MEMORY-COMPACTOR-1 (Stage 2)

**Doc under review:** `docs/planning/PLANNING_memory_compactor.md` (commit f7ff9e947, branch develop)
**Review tier:** Tier 2-DB (plan-review-before-build), single adversarial pass.
**Method:** independently re-ran the plan's cited greps; read the referenced code end-to-end (`__init__.py:1975-2062`, `database.py:315-485, 1520-1600, 8380-8455, 8590-8660, 8060-8160`, `const.py:3600-3760`); adjudicated the plan against `AUDIT_memory_retro_value.md` (commit 6a99575fa).
**Verdict:** **FIX-PLAN-FIRST.** Two CRITs (one is a plan-internal contradiction that makes the load-bearing invariant unimplementable as specced; one is a missing vocabulary registration that will trip a boot-time assert or write a topic no consumer expects). Two HIGHs, three MEDs, two LOWs. All fixable in the plan without rescoping the cycle.

---

## CRIT-1 — "Same DB transaction" invariant is unimplementable given D3's DAO shapes

**Where:** §1 (Invariant) + §D2 step 2 + §D3.

**Claim under review:**
- §1: *"at least one `memory_facts` row … must be committed and readable in the same DB transaction as the redaction write."*
- §D2 step 2 (correct): *"insert the new row FIRST, then `supersede_memory_fact(old_id, new_id)` in the SAME `_db()` context"*
- §D3: `add_memory_fact_row` and `supersede_memory_fact` each *"INSERT OR IGNORE via `_db()`"* / *"UPDATE ... via `_db()`"*.

**Why it fails (verified against `database.py:322-421`):** `_db()` is the single-writer-worker producer contextmanager — every acquisition enqueues onto `self._write_queue` (line 421) and each queued item runs its own execute+commit in the worker. **Two DAO calls = two queue submissions = two distinct SQLite transactions**, in worker-serialized order but not atomic together. You cannot nest `_db()`; the caller cannot batch two DAO calls "in the SAME `_db()` context" while each DAO opens its own. The compactor engine as specced in D2 step 2 literally cannot honor the wording in D3.

Similarly for the redaction stub (§D2 step 3): "the fact write committed BEFORE emitting the UPDATE that rewrites `attrs_json`" — this can be strictly ORDERED (single-writer worker preserves enqueue order), but it is not "the same transaction," so a crash between the two commits is a real reachable state. The plan's restart-resilience argument in §4 ("either neither committed (raw survives) or both committed") is FALSE as written — the reachable interleave is "fact committed, redaction UPDATE not yet committed," which leaves a dangling fact whose `derived_from` points at an unredacted raw row. That's still a safe state (invariant §1 holds: fact exists, episode exists), but the plan's own wording says otherwise, and Review-A will chase this ghost.

**Fix (plan-side):** Rewrite the invariant to match the architecture the code actually supports:

> "Every `memory_facts` row emitted by the compactor is COMMITTED via the single-writer worker before any redaction UPDATE for the same episode is enqueued. Because the write queue is FIFO and every DAO acquires `_db()` exactly once, this ordering is guaranteed by enqueue order. A crash between the two commits leaves either (fact absent, episode raw — retried next run) or (fact committed, episode raw — invariant §1 still holds; next run's redaction UPDATE is idempotent)."

Then either:
- (Option A, minimum change) Delete the "same `_db()` context" phrase from D2 step 2. Corrections become: enqueue INSERT, then enqueue UPDATE; ordering guaranteed by the worker. Add an explicit note that the two operations are two transactions ordered by the worker, not one transaction; document the failure interleave as invariant-preserving.
- (Option B, if true atomicity is required — recommended NOT to pursue this cycle) add a `add_fact_and_supersede(old_id, node_id, topic, ...)` combined DAO that opens ONE `_db()` and issues INSERT + UPDATE + one `commit()`. Also lets the redaction stub use `add_fact_and_redact_episode(ep_id, ...)`. This is more code and a new surface, but is the only way the "same transaction" wording is literally true. Do NOT accept plan wording that implies atomicity while shipping Option A.

**Severity CRIT because:** the invariant is what the three Tier 2-DB reviewers are supposed to try to falsify. If the wording is unimplementable, every reviewer will either wave it through (misreading intent) or flag it as CRIT during build review — either way, budget lost. Fix in the plan.

---

## CRIT-2 — `topic="exterior_track_baseline"` is NOT in `MEMORY_FACT_TOPICS`; adding a topic is a reviewed change and the plan doesn't call it out

**Where:** §D1 ("propose/refresh a fact under `topic=exterior_track_baseline`"), §D2 (`add_memory_fact_row` writes with a topic arg), §D4 live-check (`WHERE topic='exterior_track_baseline'`).

**Verified:** `const.py:3660-3666` — `MEMORY_FACT_TOPICS = frozenset({"occupancy_reliability", "sensor_trust", "occupancy_baseline", "notification_hygiene", "adjacency_graph"})`. `exterior_track_baseline` is not in it. The immediately-preceding comment (§3642): *"Adding a type is a reviewed change — this is the write-quality gate."*

The plan asserts registry KEYS must be a subset of `MEMORY_EPISODE_TYPES` (§D2, "boot-time assert"). It says nothing about the parallel constraint on `topic` values. Either:
- there's no enforcement on `topic` today (grep of `database.py` for `MEMORY_FACT_TOPICS` will confirm — reviewer must run this), in which case the compactor will silently write facts under a topic no reader is scoped to, and the retro-value doctrine ("write-quality gate on vocabulary") is violated in the first shipped compactor rule; OR
- there IS an enforcement point (facade or DAO) and D1's write will fail at runtime.

**Fix (plan-side):**
1. Add a deliverable step (D0 or fold into D3): amend `MEMORY_FACT_TOPICS` in `const.py` to include the new topic(s) the compactor's rule registry will emit. List EVERY topic the shipped registry uses.
2. Add a symmetric boot-time assert to §D2: every `topic` used by a registered rule MUST be in `MEMORY_FACT_TOPICS`. Mirror the episode-type assert.
3. Adjudicate the topic name against the retro-value taxonomy (see MED-1 below): the topic should encode both the axis (baseline/rate/outlier) AND the type. `exterior_track_baseline` is fine but should be committed to explicitly, not implicitly.
4. Grep and cite: has any reader or NM consumer written a switch on the current five topics? If yes, list impact of adding a new one (usually zero — additive).

---

## HIGH-1 — Retro-analysis says `occupancy_phantom` is the highest-signal, most-adjudicated bucket; the plan picks `exterior_track` for D1 with a "largest bucket" justification that the retro explicitly downgrades

**Where:** §D1, and the priority ordering hinted for §D2 registry.

**Adjudication vs `AUDIT_memory_retro_value.md`:**
- Retro §"Episode types that earn distillation priority" ranks: **(1) `occupancy_phantom` — highest signal density per row; already adjudicated (`d2_demotion`); clean per-room recurrence profile.** (4) `actuation_conflict` — lowest retro value per row (identical 5-min-tick repeats — the most compressible). (3) `exterior_track` — per-row value LOW but attrs rich; compact aggressively.
- The plan justifies `exterior_track` as "largest bucket" (1044 rows) and "per-track shape well-defined." Both true, but retro says the largest bucket is the LOWEST-per-row-value bucket, and the highest-value bucket (`occupancy_phantom`) is smaller (56 rows) but where the compactor earns its keep.

**Two defensible readings; the plan must pick one and state why:**
- (Reading A — engine-first) `exterior_track` is a good fixture-first choice for the ENGINE because the shape is regular (linker-produced), which stresses the distillation-rule mechanics without conflating with adjudication semantics. `occupancy_phantom` is where the compactor delivers diagnostic value, but that value is realized once the engine is proven. This is a defensible position IF the plan says so explicitly.
- (Reading B — value-first) D1 should be `occupancy_phantom` because that's what the retro says answers real questions, and the compactor's hand-built oracle should be the one that will feed MEMORY-FIRST-DIAGNOSTICS-1.

**Fix (plan-side):** pick one, write one paragraph in §D1 that names the retro finding and says which reading applies. If Reading A, add an explicit second deliverable D1b (or a §5 rule-registry seed row): `occupancy_phantom` rule ships in the same registry with a HIGHER priority than `exterior_track`. Otherwise Retro-Value-1's ordering is not reflected anywhere in the built artifact, which defeats the "priority ints let retro tune the compactor" claim in §"Sibling cycle input."

---

## HIGH-2 — Reads-on-write-queue guard (Stage-1 HIGH-B) has no callsite anchor in the plan

**Where:** §D2 "Write discipline" says *"Reads inside the compactor use `db.read_memory_episodes(...)` / `db.read_memory_facts(...)`"*. §6 mutation drill #3 says *"Swap compactor's `db.read_memory_episodes` → open a raw connection → 'reads-use-read-pool' test must fail."*

**Gap:** the plan lists the DAOs to REUSE (correct — verified at `database.py:8597`/`:8645`, both use `_db_read()` at line 8621/8663). But it does NOT constrain the compactor to call ONLY these two read DAOs. The distillation rules run per-node + per-window, and a naive implementation of the `class` / `zone` distribution in the D1 exterior-track rule will want facts, seen episode ids, and cross-node counts. If the engine adds a new read (e.g., "have I already written a fact for this window?"), and the reviewer / builder doesn't notice, that new read is a fresh callsite that must ALSO route via `_db_read()`.

**Fix (plan-side):**
1. §D2 add an explicit rule: *"the compactor engine has exactly two read callsites: `read_memory_episodes` and `read_memory_facts`. Any new read is a new DAO added to `URADatabase` and covered by its own mutation drill. A raw `aiosqlite.connect` inside `memory_compactor.py` is a CRIT-blocking review finding."*
2. §D2 add an idempotency-check pattern: the plan currently relies on `INSERT OR IGNORE` for idempotency. That's fine — but it means the compactor does NOT need to pre-check "does this fact exist." So the read surface really is only the two DAOs. Make this explicit.
3. §6 add a fourth mutation drill: add an ad-hoc `aiosqlite.connect(...)` call inside the compactor module and confirm a specific test fails (e.g., a "compactor uses only sanctioned read DAOs" test — verifiable via import-time introspection or a linter rule).

---

## MED-1 — Rule-registry `statement_fn` shape is deferred but is the load-bearing shape the oracle diffs against

**Where:** §D2 registry `statement_fn` is undefined. §D1 hand-oracle statements are undefined (the audit will produce them).

**Risk:** the D1 hand-oracle IS the acceptance oracle for D2 (§D2 acceptance: *"diff resulting `memory_facts` rows against the D1 oracle (Q: exact statements + derived_from set equality)"*). If D1 produces statements that D2's `statement_fn` cannot produce deterministically from the source rows alone (e.g., D1 uses human-written phrasing; D2 uses a template), the diff will FAIL not because the compactor is wrong but because the oracle is over-specified.

**Fix (plan-side):** §D1 acceptance criteria — add a constraint: *"The hand-oracle statements MUST be generatable from a pure function `(rows_in_window, node_id, topic) -> str`. If the auditor finds herself writing phrasing that requires human judgment, freeze the template first and re-generate the oracle from it. The `statement_fn` for D2 IS this frozen template."* This flips the ordering — the template is designed in D1, not in D2 — and makes the fixture-diff test defensible.

---

## MED-2 — `MEMORY_COMPACTOR_MAX_WRITES_PER_RUN=500` default has no measurement backing and no anchor to the write-flood postmortem numbers

**Where:** §5 knob table.

**Missing:** the v5.2.1 write-flood postmortem was per-cycle-per-room. 500 writes in one nightly run, gated by cadence, is orders of magnitude below the flood pattern (which was continuous). Fine. But the plan should cite the number it's staying under. Also 500 in a single loop iteration inside the 5-min budget's 300s means ~1.6 writes/sec — trivially safe, so 500 is probably too CONSERVATIVE (a first run against 1799 rows may write ~10-50 facts, well under 500; but on a re-run against a full year's accumulation the cap may bite arbitrarily).

**Fix (plan-side):** two lines in §5:
- Cite the v5.2.1 flood rate the compactor stays under (e.g., "well below the ~N writes/min sustained rate that saturated the queue in v5.2.1").
- Add an observation-only counter to `sensor.ura_memory_status`: `compactor_writes_last_run`. When it starts trending toward `MAX_WRITES_PER_RUN`, that's the raise-the-cap trigger. Currently there's no way to know if the cap is biting or if it's dead code.

---

## MED-3 — The five flagged open decisions: three can be resolved now, two genuinely need the operator

The plan defers five decisions to D1/build. Adjudicating each:

1. **`statement_fn` shape** — resolve NOW (see MED-1): pure function, template frozen in D1.
2. **Correction trigger** — resolve NOW: "new fact's structured claim contradicts a current fact under the same `(node_id, topic)`" (from §D2 step 2) is well-defined IF the rules encode their claims as structured `attrs` (not free text). Add to §D2: rules produce `(statement, attrs)` where `attrs` is the canonical structured form used for contradiction detection; `statement` is the human-readable rendering.
3. **`require_adjudicated=True` default** — resolve NOW (already resolved in §9): default True per Arch §5c step 1. Move this from §9 "Explicit deferrals" up into §D2 registry description as the DEFAULT, and drop the "open decision" framing.
4. **Cadence** — DEFER to operator: default 24h is fine, but confirm the operator wants the 02:30 tick or would prefer 03:30 (after the main maintenance rotation completes to keep the window quiet).
5. **Redaction threshold (20,000 rows)** — DEFER to operator: the number is stated in §5 but the trigger belongs to the operator's parked-plan review discipline, not this cycle's build.

**Fix (plan-side):** promote 1/2/3 into resolved decisions in §D2; keep 4 and 5 as explicit "operator confirm before build dispatch" checklist items at the bottom of the plan.

---

## LOW-1 — Nightly `_cleanup_ops` line number in §0 is 1978; verified location is 1977 (the `_cleanup_ops = [` line) with the compactor tuple going after `("incremental_vacuum", ...)` at ~2019

Not a bug, but the plan's "REUSE this exact wiring surface (add one op tuple)" should specify the insertion order. Rotating index means order affects the "which nights this op skips" pattern. Put compactor AT THE END (after `incremental_vacuum`) so the rotation still hits it fairly and it runs LAST like vacuum does (so any facts it emits are potentially vacuumed the same night, though that's minor). Add one line to §D4.

---

## LOW-2 — Non-goal "No new query verbs" implicitly commits the `sensor.ura_memory_status` attribute additions in §D5 to be internal-only; make explicit

The five new sensor attributes (`compactor_last_run`, etc.) are user-facing. Fine, and no new entity. But §5 knob-ladder tacitly places them as observation-only (rung 0 essentially). Add one line to §D5: these are OBSERVATION attributes; they are not knobs, they are not persisted (in-process only, per plan), and their absence at boot (before first run) MUST render cleanly (already stated) but should also NOT trip any downstream consumer. Grep sensor consumers of `ura_memory_status` attributes: are any templates in the dashboard reading them? (If none, safe.)

---

## Verified claims (no finding)

- §0 `_cleanup_ops` at `__init__.py:1978` — **CONFIRMED** (line 1977 for the list literal; §0's line number is off by one but the wiring surface described is exactly right — line 1978 is the first op tuple).
- §0 `_db`/`_db_read` at `database.py:322`/`:470` — **CONFIRMED** (single-writer worker + WAL read-pool).
- §0 v5.5.7 vacuum-button precedent — **CONFIRMED** (`button.py:1584` calls `vacuum_full_supervised()`; `database.py:8071` `incremental_vacuum` implements the doctrine — bounded cap, guarded no-op, single-writer worker).
- §0 `read_memory_episodes` uses `_db_read()` — **CONFIRMED** (`database.py:8621`).
- §0 `memory_facts` schema `UNIQUE(node_id, topic, statement) + superseded_by` — **CONFIRMED** (`database.py:1551-1568`).
- §0 seed pattern `INSERT OR IGNORE` — **CONFIRMED** (`database.py:1579`).
- §0 five `MEMORY_EPISODE_TYPES` covering 1799 rows — arithmetic checks out; but the frozenset ACTUALLY has 10 entries (const.py:3642-3657), not the 5 rendered in the retro. The plan's registry can safely register any subset; not a finding.
- §D5 `sensor.ura_memory_status` exists — **CONFIRMED** (`sensor.py:4466`).
- §D2 "no `aiosqlite.connect` in new module" — the constraint is stateable and enforceable (see HIGH-2).

---

## Verdict

**FIX-PLAN-FIRST.**

Blocking (must land in the plan before build dispatch):
- CRIT-1: rewrite the invariant to match the write-queue architecture; delete the "same `_db()` context" claim in D2 step 2 or add a combined DAO.
- CRIT-2: add `exterior_track_baseline` (and any other new topics) to `MEMORY_FACT_TOPICS` as an explicit deliverable; add the symmetric boot-time assert.
- HIGH-1: adjudicate the D1 type choice against the retro-value ranking in one paragraph; if `exterior_track` stays, seed `occupancy_phantom` in the registry with higher priority.
- HIGH-2: constrain the compactor read surface to exactly two DAOs; add mutation drill #4.

Should land (small edits):
- MED-1: freeze the `statement_fn` template in D1, not D2.
- MED-2: cite the flood-rate number; add `compactor_writes_last_run` counter.
- MED-3: resolve 3 of 5 open decisions in the plan; keep 2 as operator-confirm checklist.

Nice-to-have:
- LOW-1: specify insertion position in `_cleanup_ops`.
- LOW-2: mark §D5 attributes as observation-only.

Once CRIT-1/2 and HIGH-1/2 land in the plan, the cycle is READY-TO-BUILD as Tier 2-DB. Total plan edit is ~1-2 pages; no rescoping.
