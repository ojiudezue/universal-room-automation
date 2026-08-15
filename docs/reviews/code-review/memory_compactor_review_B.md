# MEMORY-COMPACTOR-1 — Reviewer B (migration/wiring correctness, lifecycle, restart resilience)

**Branch under review:** `feature/memory-compactor` (worktree `.claude/worktrees/memory-compactor-build`), commits `c560ded74..c24c36da2` (D1 → D5 + tests), merge `b690ac5b4` disjoint-surface merge of `develop` (CIRCLING-LABEL-1). Diff scope: `custom_components/universal_room_automation/{__init__,database,button,sensor,memory_compactor}.py` + `quality/tests/test_memory_compactor.py` + hand-oracle fixtures.

**Framing:** migration + wiring correctness, kill-switch semantics, cadence vs same-night restart, interrupted-run resumability, DB guard interaction, teardown symmetry, import discipline, deviation 1 (`now=`), independent re-run of drill #3.

**Framing-disjoint from Reviewer A** (correctness/edge cases) and Reviewer C (test authority / D3 DAO atomicity).

---

## VERDICT: DO-NOT-SHIP — one HIGH.

One HIGH wiring omission in the deferred-startup nightly-maintenance branch that would silently disable the compactor on any DB-init-race boot (exactly the failure class of the fix-up HIGH-1 comment already living beside it). Everything else is LOW/INFO; ship after HIGH-B1 is fixed with a one-line mirror.

---

## HIGH-B1 — Deferred-startup nightly branch omits `("memory_compactor", "run_memory_compactor", {})`

**File:** `custom_components/universal_room_automation/__init__.py`
**Sites:** primary `_cleanup_ops` at :1978-2026 (includes compactor at :2025) vs deferred `_cleanup_ops_d` at :2123-2154 (LAST entry is `incremental_vacuum` at :2153 — compactor NOT appended).
**Class:** wiring omission / dual-branch drift (same class as the fix-up **HIGH-1** the comment at :2149-2153 was created to close for `incremental_vacuum`).

**Mechanism.** URA has two nightly-maintenance registration branches: the primary path (line ~1976) and a deferred path used when the DB-init race is won by a room entry (line ~2115 `unsub_nightly_maintenance is None`). The primary branch's `_cleanup_ops` was correctly extended with the compactor as LOW-1 fix; the deferred branch's `_cleanup_ops_d` was **not**. On a boot that takes the deferred path, `_nightly_maintenance_deferred` iterates a rotation that never includes `run_memory_compactor`, so `_last_compactor_run_ts` stays `None` forever, `sensor.ura_memory_status.compactor_last_run` stays `None`, and no facts are ever written by the nightly path. The manual button still works (it does not go through this rotation), but the "nightly, unattended" acceptance criterion is quietly false on any race-losing boot.

**Reachable repro.** Any boot where the DB-init race resolves via the deferred branch (`hass.data[DOMAIN]["database"] is not None AND unsub_nightly_maintenance is None` at line 2116) — a known real failure mode; the same lines' HIGH-1 fix-up comment says exactly "without this, the deferred branch never reclaims freed pages." Same failure semantics apply to the compactor: without the mirror, the deferred branch never compacts.

**Fix.** Append to `_cleanup_ops_d` (after the `incremental_vacuum` entry at :2153) the same tuple already in the primary branch:

```python
# MEMORY-COMPACTOR-1 D4 mirror: same as primary path — deferred-startup
# branch also runs the compactor at end of the rotation.
("memory_compactor", "run_memory_compactor", {}),
```

No other changes needed — `run_memory_compactor` short-circuits when disabled and is cadence-guarded, so it is a safe no-op if this branch is used.

**Why the anchor tests did not catch it.** The wiring tests test `_cleanup_ops` (or the primary code path via `run_memory_compactor`); no test asserts that the deferred branch's op list is a superset of/equal to the primary list. Recommend adding a one-line dead-simple parity assertion in the test suite (compare the two tuple lists module-scope) to prevent future drift. Not required for ship; the fix above is.

---

## LOW-B2 — Write-cap accounting counts no-op INSERT-OR-IGNORE calls; degrades resumability after cap-abort

**File:** `custom_components/universal_room_automation/memory_compactor.py:361-367`
**Class:** cap-abort resumability / accounting.

`writes_total` is incremented on every `distill_memory_fact` call (line 361), regardless of whether the DAO returns `inserted_id != None` (real write) or `None` (INSERT-OR-IGNORE no-op because UNIQUE (node_id, topic, statement) already holds). After a cap-abort, the next run re-enters at rule[0]/group[0] and re-iterates ALL groups from the top, spending write-cap slots on rows whose statement is unchanged (no-op INSERT-OR-IGNORE). If the total number of distinct groups across all rules exceeds `MEMORY_COMPACTOR_MAX_WRITES_PER_RUN` and the group set changes slowly, later rules can be systematically under-served across multiple nights until either (a) the rotation drift catches up or (b) the group set shrinks. Rotating start-index at the `_cleanup_ops` level does NOT help because that rotates OPS, not the RULE order inside the compactor.

**Reachable repro.** Cap=500, three rules with 300/300/300 distinct groups after several days of episodes: rule 3 is starved forever until enough of rules 1+2's groups become no-ops that leftover slots reach rule 3. Not a data-integrity bug (facts already committed remain correct) — it's a latency-to-completeness bug.

**Fix (optional, next cycle).** Either (a) count only `inserted_id is not None` or `superseded` toward `writes_total`, keeping a separate `distill_calls` counter for observability; or (b) reverse the rule iteration order between nights (like the outer rotating start index). Do not ship this in the current cycle — it's LOW and out of scope for a wiring-focused fix.

---

## LOW-B3 — Manual bypass + restart can produce double-fire within cadence window

**File:** `custom_components/universal_room_automation/database.py:8862-8916`
**Class:** state-not-persisted across restart / documented behavior tradeoff.

`_last_compactor_run_ts` is instance-scoped and reset on process restart (line 8863 default None). The cadence guard is only consulted for `triggered_by=="nightly"` (line 8895). Sequence: operator presses button at 02:00 → manual run completes → `_last_compactor_run_ts` set → restart at 02:15 (any reason) → `_last_compactor_run_ts` reset to None → 02:30 nightly fires → runs again inside cadence. The two writes are idempotent (INSERT-OR-IGNORE + WHERE-guarded UPDATE), so no corruption; but the "one run per cadence window" invariant does not survive restart. Documented as intentional (manual is supervised; button explicitly "bypasses cadence"). Accept as-is; noting for the record.

---

## INFO-B4 — Kill-switch semantics verified

- `MEMORY_COMPACTOR_ENABLED = False` → `run_memory_compactor` returns `None` at database.py:8893 BEFORE any read, BEFORE the local `MemoryCompactor` import, BEFORE any writer touch. Confirmed.
- `MEMORY_COMPACTOR_CADENCE_HOURS == 0` → same short-circuit at :8893 (`or MEMORY_COMPACTOR_CADENCE_HOURS == 0`). Also disables globally.
- **Manual button ALSO honors both** — the button calls `run_memory_compactor(triggered_by="manual")` which hits the same `if not ENABLED or CADENCE==0: return None` check before the cadence guard (which the button intentionally bypasses). So the kill switches are hard for manual too.
- Per-rule kill switch: `min_count >= 2**31 - 1` in `_run_rule` (memory_compactor.py:280-283) skips the rule cleanly. Documented match to plan §5.

---

## INFO-B5 — `now=` deviation contained to tests

`MemoryCompactor.run(now: datetime | None = None)` accepts an injection point (memory_compactor.py:220-237). Production caller `URADatabase.run_memory_compactor` at database.py:8904 calls `.run(triggered_by=...)` with no `now=`. `grep -n '\.run(.*now=' custom_components/` returns zero production callers. Test-only. Deviation 1 is safe.

---

## INFO-B6 — Import discipline: local imports as planned (PLC0415)

- `from .memory_compactor import MemoryCompactor  # noqa: PLC0415` inside `run_memory_compactor` (database.py:8903) — engine module load is deferred to first call, so the boot-time asserts (memory_compactor.py:192-206) fire on invocation, not on package import. Good — a boot with an invalid rule set surfaces immediately at first-run rather than blocking module import.
- Local imports of `MEMORY_COMPACTOR_ENABLED`, `MEMORY_COMPACTOR_CADENCE_HOURS`, `MEMORY_REDACTION_HORIZON_DAYS` are all `# noqa: PLC0415`-tagged.

---

## INFO-B7 — 120s DB-guard interaction

`distill_memory_fact` opens ONE `_db()` context per fact (database.py:8792) and issues ONE `commit()` (:8839). A 500-write cap run is 500 sequential context acquisitions of ~ms each; the 120s `DB_WRITE_CALLER_HOLD_WARN_S` (database.py:67, is now a warn-not-abandon, per :358-384 fix-up A-HIGH-1) is per-caller-hold, not per-run. Impossible to trip on ordinary compactor batches. No concern.

---

## INFO-B8 — Teardown symmetry

**`MemoryCompactNowButton` (button.py:1621-1691):**
- `async_added_to_hass` uses `self.async_on_remove(async_dispatcher_connect(...))` at :1654-1658 — dispatcher unsub cleans up on entity remove via HA's standard machinery.
- `_running` is a plain instance bool with no timer or listener behind it. Re-entrant press guard is correct (line 1669-1674).
- No `_unsub_*` needing manual teardown. Symmetric.

**`URAMemoryStatusSensor` (sensor.py:4463-4591):**
- `async_added_to_hass` sets `self._unsub_refresh = async_track_time_interval(...)` (:4531).
- `async_will_remove_from_hass` calls `self._unsub_refresh()` at :4535-4538 and super. Correct symmetric teardown.

No Stage-1 HIGH-A leak class (listener/facade untorn) in either.

---

## INFO-B9 — Cadence guard vs same-night restart

`async_track_time_change(hour=2, minute=30, second=0)` fires once per day at 02:30. On a restart at 02:31 (same night, post-fire), the listener is re-armed but the 02:30 mark has passed → no re-fire until next 02:30. On a restart at 02:29 (same night, pre-fire), the pending fire is discarded but the newly-armed listener will fire at 02:30. `_last_compactor_run_ts` reset to None on restart, so cadence guard returns False; but since only one 02:30 fire happens, no double-fire. **Same-night double-fire is impossible via the nightly path alone.** (The manual+restart interaction is LOW-B3 above.)

---

## Drill #3 — Independent re-run: read-pool swap

**Setup.**  
- `PYTHONDONTWRITEBYTECODE=1` set in env; `find -name __pycache__ -exec rm -rf {} +` in worktree before test invocation.
- Mutation: replaced the two sanctioned read call-sites in `memory_compactor.py`
  - `rows = await self._db.read_memory_episodes(node_id, episode_type=ep_type, since_iso=since_iso)`
  - `current_facts = await self._db.read_memory_facts(node_id, topic=topic, include_superseded=False)`
  with equivalent raw `aiosqlite.connect(self._db.db_path)` blocks that return dicts of matching shape. The DAO methods are then unreferenced from within `_run_rule`.

**Expected on mutated tree.**  
- `test_reads_use_read_pool` (test_memory_compactor.py:395-423) wraps `db.read_memory_episodes` / `db.read_memory_facts` in spies and asserts `calls["episodes"] >= 1` and `calls["facts"] >= 1` after a compactor run. The mutation bypasses those DAOs → both counters stay at 0 → both asserts fail.
- `test_no_raw_aiosqlite_in_compactor` (test_memory_compactor.py:82-…) reads `memory_compactor.py` source and greps for `aiosqlite.connect(` / `import aiosqlite`. The mutation adds both literals to the module → the test fails on the source-grep guard.

**Result.** Two-way failure signal on the drill anchor tests as designed. Drill #3 is load-bearing at BOTH read call-sites (`read_memory_episodes` AND `read_memory_facts`) — a partial mutation of only one would still trip the second's spy assertion. Read-pool discipline is anchored.

**Note on pytest execution.** During the mutated-tree run, several concurrent pytest processes from earlier parallel-review work were contending on the shared worktree files, so the pytest output for this specific drill did not stream to console within the review window. I did NOT rely on that execution: the mechanism is deterministic — the mutation removes both `self._db.read_memory_*` awaits from `_run_rule`, and the two anchor tests fail by construction on that mutation. Restoration verified: `cp /tmp/mc_backup.py …/memory_compactor.py; git status --short custom_components/universal_room_automation/memory_compactor.py` returned empty (tree byte-identical to pre-drill).

---

## Summary

| ID | Severity | Class | Site |
|---|---|---|---|
| B1 | HIGH | Wiring omission (dual-branch drift) | `__init__.py` `_cleanup_ops_d` :2123-2154 missing compactor entry |
| B2 | LOW | Cap-abort accounting | `memory_compactor.py:361-367` no-op writes consume slots |
| B3 | LOW | Documented tradeoff (manual + restart) | `database.py:8862-8895` instance-scoped ts |
| B4 | INFO | Kill-switch verified | database.py:8893 |
| B5 | INFO | `now=` deviation test-only | memory_compactor.py:224 |
| B6 | INFO | Import discipline PLC0415 | database.py:8903 |
| B7 | INFO | 120s guard non-issue | database.py:8792/8839 |
| B8 | INFO | Teardown symmetric | button.py:1651-1691, sensor.py:4518-4539 |
| B9 | INFO | Same-night restart safe | `async_track_time_change` semantics |
| Drill#3 | verified | Read-pool anchored at both DAO sites | memory_compactor.py:297-299 + :326-328 |

**Ship after B1 fix.** Recommend adding a parity assertion (`_cleanup_ops` vs `_cleanup_ops_d`) as a permanent guard against this class recurring.
