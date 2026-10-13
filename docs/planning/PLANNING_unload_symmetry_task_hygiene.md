# PLANNING — UNLOAD-SYMMETRY-TASK-HYGIENE-1 (shutdown-teardown follow-ups)

Thread: platform / shutdown + DB hygiene
Tier: **2-DB** (shared DB primitive `database.py` + its `_db()` surface; builds immediately on top of v5.103.49)
Status: **PLAN ONLY — do not build, commit or deploy**
Author: ura-planner (overnight autonomous pass, 2026-10-13)

---

## Parsimony verdict

**BUILD (narrow).** Three small, additive items on the same `_db()` surface the v5.103.49 fix opened. The marginal benefit is modest-but-real:

- Item 1 (`DBShuttingDown` + DEBUG downgrade) — directly removes the residual ~95 ERROR/WARNING log lines per restart that v5.103.49 traded the 5-minute stall for. Pure signal-to-noise fix; no new behavior.
- Item 2 (CM baseline-save via `async_add_shutdown_job`) — closes a known race (stop-handler fires after the worker is already cancelled). The reward is bounded (baselines persisted every 30 min anyway) but the fix is 10 lines.
- Item 3 (diagnostics reads via `_db_read()`) — removes read traffic from the single-writer serial queue. Latency win small, but it also means these reads survive a stopped writer (currently they fail at shutdown exactly like item 1).

Not PARK: these three sit on the same surface, each < ~30 LoC, and the review ceremony has already been done once at the mother ship (v5.103.49). The build is cheaper than letting them drift and re-reading the surface a third time.

Item 4 (close-stage buffering) remains **accepted / non-goal**, as carded.

---

## Falsifiable invariant (stated up front)

> **Across HA shutdown, URA emits ZERO `_LOGGER.error(...)` or `_LOGGER.warning(...)` lines whose root cause is "the write worker is closed", AND the stop-time anomaly-baseline save completes before the worker is cancelled (visible as `metric_baselines.updated_at` within ±2 s of `EVENT_HOMEASSISTANT_FINAL_WRITE`).**

Discriminators (how a bad fix would look different from a good one):

- **Bad fix masks writes still failing.** If item 1 swallows errors but item 2 is not actually running before cancel, the stop-time baselines will NOT update — distinguishable from the pass case because `metric_baselines.updated_at` would stay at the last periodic tick, not stop time.
- **Bad fix moves logs from ERROR to DEBUG for all failures.** DBShuttingDown must be a *dedicated* subclass so that only the stopping case is quieted; connection-lost / corruption / migration failures must still log at ERROR/WARNING. Discriminator: an induced non-stop failure (e.g. unit-test raising generic RuntimeError in a DAO) must still land ERROR.

---

## Institutional context verified

### 1. Prior art — code (REUSED vs NEW per proposed symbol)

| Proposed symbol | Verdict | Evidence |
|---|---|---|
| `DBShuttingDown(RuntimeError)` subclass | **NEW** | `grep -rn 'DBShuttingDown' custom_components/universal_room_automation/` → 0 hits. v5.103.49 raises bare `RuntimeError("DB write skipped: Home Assistant is stopping and the write worker is closed")` at `database.py:499-502`. No existing shutdown-signalling exception class to reuse. |
| Shutdown-stage flag | **REUSED** | `getattr(self.hass, "is_stopping", False) is True` already used at `database.py:497`. Reuse the same gate for the DEBUG-vs-ERROR routing in caller except-arms (no new state on `URADatabase`). |
| `async_add_shutdown_job` | **REUSED** | HA core API `homeassistant/core.py:1019-1039` (the `@callback`-decorated one). Appends to `self._shutdown_jobs`; jobs run during `async_stop` BEFORE `async_block_till_done` + worker cancel. Verified by reading the installed `.venv-ha/.../homeassistant/core.py:1007-1039` and `:1041+` for `async_stop` ordering. |
| `_db_read()` context manager | **REUSED** | `database.py:644-654` — opens a transient `aiosqlite.connect` with `PRAGMA query_only=ON`; bypasses the write worker entirely. Already in use elsewhere in the DAO layer. |
| `HassJob` wrapper for the shutdown job | **REUSED** | HA core type (expected by `async_add_shutdown_job`); already imported in several URA modules — pick the one closest to `manager.py` at build time. |
| Any new module constant / Number entity / knob | **NEW** / none | No new numbers; see "Numbers get knobs" section. |

### 2. Prior art — plans

- `docs/planning/kanban.data.yaml` card `UNLOAD-SYMMETRY-TASK-HYGIENE-1` (lines 19362-19453): canonical scope.
- `docs/planning/kanban.data.yaml` card `SHUTDOWN-CENSUS-DB-WRITES-BLOCK-1` (line 31395-): shipped predecessor, same `_db()` surface, same reviewer axis.
- `docs/readmes/README_v5.103.49.md` §2 and §Validated-2026-10-11: proves §2 fix landed, left `~95 ERROR/WARNING` log residuals and a race around the stop-time save still open (explicit "Follow-ups carded under UNLOAD-SYMMETRY-TASK-HYGIENE-1").
- `docs/reviews/code-review/overnight_2026-10-06_shutdown_db_fastfail.md`: the four review MEDs that minted this card's INSTANCE block. Verified in card body.

No plan proposes a different design for any of these three items.

### 3. Prior art — memory / analysis

- Memory `project_optimizer_db_write_flood_incident_2026_06_09` — reminder that boot-unavailable + per-cycle persist can saturate the write queue; our fix does NOT increase write volume (items 1-3 do not add writes; item 3 REMOVES reads from the queue).
- Memory `feedback_pre_deploy_zero_bugs_gate` — applies at build time.
- No memory contradicts this scope.

### 4. Design doc

- `docs/architecture/*` — no coordinator-specific state-of-play doc governs the DB primitive; `docs/QUALITY_CONTEXT.md` bug classes (restart resilience, task leaks, log hygiene) apply.

### 5. Code locations surveyed end-to-end during scoping

- `custom_components/universal_room_automation/database.py:1-700` (worker loop, `_db()`, `_db_read()`, flush/drain, `async_close`) and spot-reads of DAO methods.
- `custom_components/universal_room_automation/domain_coordinators/manager.py:525-600` (`_wire_anomaly_baseline_persistence`, stop hook).
- `custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py:250-845` (`DecisionLogger`, `ComplianceTracker` — all `_db()` call sites).
- HA source `/.venv-ha/.../homeassistant/core.py:1000-1060` (`async_add_shutdown_job` + `async_stop` ordering).

### 6. Config-first check

**No knob fixes this.** The three items are all code-site corrections (an exception class / log level, a scheduler primitive swap, a context-manager swap). There is no live Number/Select/Switch entity, options-flow field, or room-config setting whose value would change what happens at shutdown. If one existed it would be a layering mistake. Config-first verdict: **not applicable, do code.**

### 7. Producer + consumer check (for item 2's value: anomaly-baseline rows)

- **Producer:** `CoordinatorManager._persist_coordinator_baselines(include_safety_rate=True)` at `manager.py:566+`, called by the EVENT_HOMEASSISTANT_STOP listener registered at `manager.py:554-559`.
- **Dependency health:** each coordinator's `_save_*_baselines` DAO write goes through `database._db()`. After v5.103.49 that write fast-fails if the worker is already cancelled when the STOP handler finally runs — which is the race item 2 fixes.
- **Consumer:** on next boot, coordinators call `_load_*_baselines` to restore anomaly thresholds. If the stop-time save was lost, the restored baselines are up to `ANOMALY_BASELINE_SAVE_INTERVAL_S` stale — bounded, but a measurable regression against the fix's goal.

### 8. Independent re-enumeration of DAO except-arms (item 1) and diagnostics reads (item 3)

The card lists specific line numbers; the plan treats those as a HYPOTHESIS and re-enumerates. Builder MUST re-grep at build time (line numbers drift). Snapshot taken 2026-10-13:

**Item 1 — DAO except-arms that log ERROR/WARNING on a `_db()` failure.** `grep -nP "except Exception as e:\s*$" custom_components/universal_room_automation/database.py` plus a scan of each DAO file. In `database.py` alone, `rg -c "except Exception"` returned **133 occurrences**. The vast majority are **migration/table-creation** arms (e.g. `database.py:1060, 1102, 1982, 2033, 2049, 2074, 2095, 2137, 2153, 2169, 2199, 2215, 2243, 2280, …`) — these run only during boot/migration and are NOT in the shutdown blast radius; they must keep ERROR/WARNING. The affected set is the **DAO caller** except-arms: methods that wrap `async with database._db() as db: … except Exception as e: _LOGGER.error(…)`. Representative in-scope sites (hypothesis — builder re-greps):

- `coordinator_diagnostics.py:302-304` (`log_decision`), `:344-346` (`get_decisions`), `:371-374` (`get_decisions_count`), `:776-778` (`get_compliance_rate`), `:808-810` (`get_override_count`), `:842-844` (`get_override_sources`).
- `census.py`, `anomaly_log.py`, `energy.py` snapshot writers, `safety.py` rate-baseline save, HVAC baseline save, perimeter_alert.py — enumerate at build time (`rg -nB2 "except Exception as e:" --type py custom_components/ | rg -B2 "_LOGGER\.(error|warning)"`), then filter to those whose `try:` block contains `database._db(` or a known DAO call.

The card's claim of **~40 ERROR + ~55 WARNING** at shutdown is the empirical v5.103.49 restart log; it is the right order of magnitude but the SITE LIST is a build-time derivation, not a plan-time one.

**Item 3 — diagnostics reads currently routed through `_db()`:** `grep -n "database\._db()" domain_coordinators/coordinator_diagnostics.py` →

| Line | Method | Operation | Scope verdict |
|---|---|---|---|
| 274 | `DecisionLogger.log_decision` | **INSERT** (WRITE) | **OUT OF SCOPE** — stays on `_db()`. Card line number was wrong on this one. |
| 320 | `DecisionLogger.get_decisions` | SELECT | **IN SCOPE** → `_db_read()` |
| 361 | `DecisionLogger.get_decisions_count` | SELECT | **IN SCOPE** → `_db_read()` |
| 752 | `ComplianceTracker.get_compliance_rate` | SELECT | **IN SCOPE** → `_db_read()` |
| 793 | `ComplianceTracker.get_override_count` | SELECT | **IN SCOPE** → `_db_read()` (not in card — card missed it) |
| 825 | `ComplianceTracker.get_override_sources` | SELECT | **IN SCOPE** → `_db_read()` (not in card — card missed it) |

Net: card listed 3 reads; the real set is **5 reads** (and the fourth number in the card, `:274`, is a WRITE and must NOT be moved). Builder reconfirms at build time.

### 9. Verify-before-work — is each item still real against develop?

- **Item 1 (DBShuttingDown DEBUG class):** STILL-REAL. v5.103.49 raises a bare `RuntimeError` at `database.py:499-502`; every DAO caller catches it as `except Exception as e: _LOGGER.error(…)` → noisy restart log. The predecessor cycle did NOT add this subclass (`grep DBShuttingDown` → 0 hits).
- **Item 2 (`async_add_shutdown_job` for the baseline save):** STILL-REAL. `manager.py:554-559` is still an `async_listen_once(EVENT_HOMEASSISTANT_STOP)`. HA fires STOP listeners during the stopping stage, but `async_block_till_done` + any serial-worker-cancel ordering can leave the stop-handler running after the worker is cancelled. `async_add_shutdown_job` runs during `async_stop` **before** the final-write + cancel sweep — the correct primitive.
- **Item 3 (diagnostics reads via `_db_read`):** STILL-REAL for the 5 SELECT sites enumerated above. `_db_read` already exists at `database.py:644-654`; the swap is mechanical.
- **Item 4 (close-stage buffering):** accepted as non-goal, no change.

Nothing in develop supersedes any item; nothing is ALREADY-DONE.

---

## Numbers get knobs

**No new numbers introduced.** No thresholds, durations, windows, or gate values. The one existing constant touched by proximity (`ANOMALY_BASELINE_SAVE_INTERVAL_S`) is unchanged. Correct rung: all three items are code-shape fixes, so no knob is appropriate.

---

## Deliverables

### D1 — `DBShuttingDown(RuntimeError)` + DEBUG-level logging across DAO except-arms

**What.** Define a new exception subclass in `database.py` (top-level, exported):

```python
class DBShuttingDown(RuntimeError):
    """Raised when a DB write is submitted after the worker has stopped
    because Home Assistant is shutting down. Expected during HA stop;
    callers log at DEBUG, not ERROR."""
```

Change `_db()` (currently `database.py:499-502`) to raise `DBShuttingDown(...)` instead of bare `RuntimeError(...)`. Update every DAO caller's `except Exception as e:` arm to catch `DBShuttingDown` first and log at DEBUG, falling through to the existing ERROR/WARNING arm for everything else:

```python
except DBShuttingDown:
    _LOGGER.debug("DB write skipped: HA shutting down")
    return <neutral default>
except Exception as e:
    _LOGGER.error("Error ...: %s", e)
    return <neutral default>
```

Scope: the DAO caller sites surfaced by the Section-8 re-grep. Migration/table-creation except-arms are **not** touched. The two existing sites inside `database.py` itself that drain pending futures (`_flush_pending_writes` 5s-budget warning, `_drain_pending_futures` "DB write failed: shutdown timeout" warning) ALSO need routing — the "shutdown timeout" message is on the invariant's kill-list and must become DEBUG when `hass.is_stopping` is True.

#### Acceptance criteria
- **Verify:** `rg -n "DBShuttingDown" custom_components/universal_room_automation/` returns the class definition + every DAO except-arm (builder commits the final count in the review doc).
- **Verify:** `rg -nP '_LOGGER\.(error|warning).*(shutdown|is stopping|write worker is closed)' custom_components/universal_room_automation/` returns zero caller-side matches that are NOT inside an `if not hass.is_stopping:` guard.
- **Test:** `quality/tests/test_database_shutdown.py::test_db_shutting_down_logs_debug_not_error` — set `hass.is_stopping = True`, cancel the write task, call `log_decision` (or any sample DAO) and assert (a) return value is the neutral default, (b) a `caplog.at_level(logging.DEBUG)` captures the DEBUG line, (c) NO record with `levelname == "ERROR"` is emitted.
- **Test:** `test_db_other_errors_still_log_error` — inject a non-shutdown `RuntimeError` from a DAO and assert ERROR is still emitted (discriminator against over-swallowing).
- **Live:** after restart, `journalctl … | grep "DB write failed: shutdown timeout"` returns **zero** lines in the shutdown window, AND `grep "Error logging decision\|Error getting compliance\|Error counting overrides"` returns **zero** lines attributable to the shutdown window. Discriminator: a mid-day `_db()`-connection-lost (not shutdown) must still produce an ERROR line, confirmed by the next retry-after-reconnect log pair at `database.py:374-376`.

---

### D2 — CM stop-time baseline save via `async_add_shutdown_job`

**What.** In `CoordinatorManager._wire_anomaly_baseline_persistence` (`manager.py:540-564`) replace the `self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, …)` registration with `self.hass.async_add_shutdown_job(HassJob(self._async_persist_coordinator_baselines_on_stop))`. Keep the returned unsub stored in `self._anomaly_baseline_stop_unsub` and remove it in `async_stop` symmetrically with today. The periodic timer (`async_track_time_interval`) is unchanged.

Rationale (verified against installed HA `core.py:1019-1039 + 1041+`): shutdown jobs are drained inside `async_stop` BEFORE the stopping-stage cancels background tasks. The STOP-event listener today can race the worker cancel; the shutdown-job hook runs while the writer is still alive.

#### Acceptance criteria
- **Verify:** `rg -n "async_add_shutdown_job\|EVENT_HOMEASSISTANT_STOP" custom_components/universal_room_automation/domain_coordinators/manager.py` shows `async_add_shutdown_job` present and the STOP-event listener for baselines removed. Any OTHER STOP listener (house-state hook) is untouched.
- **Verify:** unsub stored and called in `async_stop` (symmetric teardown — Bug Class #34 avoidance).
- **Test:** `test_coordinator_manager_baseline_save_runs_before_worker_cancel` — construct a fake hass with a `_shutdown_jobs` list and a cancellable write worker, trigger `async_stop`-equivalent, assert the baseline-save callable ran while the worker task was still not-done. Also assert idempotency across repeated stop-handler fire.
- **Test:** `test_coordinator_manager_baseline_save_unsub_called_on_entry_unload` (symmetry).
- **Live:** on the restart after ship, query `metric_baselines` for the most recent `updated_at`; it must fall within ±2 s of the `EVENT_HOMEASSISTANT_FINAL_WRITE` log line (or the `Stopping Home Assistant` line as a fallback oracle), **not** at the prior periodic tick ~30 min earlier. Discriminator: a bad fix where the shutdown job never runs would leave `updated_at` at the periodic tick, visibly older.

---

### D3 — Route diagnostics reads through `_db_read()`

**What.** In `domain_coordinators/coordinator_diagnostics.py`, replace `async with database._db() as db:` with `async with database._db_read() as db:` at the five SELECT sites enumerated in Section 8: `:320`, `:361`, `:752`, `:793`, `:825` (hypothesis — builder re-greps). Leave `:274` (`log_decision` INSERT) on `_db()`.

Rationale: reads do not need the write-queue serialization; routing through `_db_read()` (a) removes head-of-line blocking against pending writes, (b) survives a stopped writer at shutdown (shutdown-time dashboard refreshes stop failing silently), (c) uses `PRAGMA query_only=ON` which catches an accidental future write-regression in these methods.

#### Acceptance criteria
- **Verify:** `rg -n "database\._db\(\)\|database\._db_read\(\)" custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py` shows one `_db()` (the `log_decision` INSERT) and five `_db_read()`.
- **Verify:** no SELECT-only method still uses `_db()`.
- **Test:** `test_diagnostics_reads_do_not_block_on_full_write_queue` — fill the fake write queue to capacity, call `get_decisions`, assert it returns before the queue drains.
- **Test:** `test_diagnostics_reads_survive_worker_stopped` — set `hass.is_stopping=True` and cancel the write task; call each of the 5 methods and assert they return their neutral defaults (empty list / 0 / 1.0) WITHOUT raising and WITHOUT emitting ERROR.
- **Live:** at steady state, URA DB stats (`sensor.ura_db_stats` or equivalent attributes on the DB primitive) show `reads` incremented by at least one per dashboard refresh of a compliance/diagnostics card; `writes` NOT incremented on those refreshes. Discriminator: a bad swap that left the read on `_db()` would increment `writes`.

---

## Non-goals (explicit)

- **Item 4 of the card (close-stage buffering).** `CoreState.not_running` re-opens buffering for late timer writes bounded by HA's 30 s close stage. Carded as accepted; no change here.
- **Any migration except-arm.** Boot-time / migration except-arms stay ERROR/WARNING; they are not in the shutdown blast radius.
- **Other coordinators' STOP-event listeners** (e.g. house-state persistence hook). They have their own race budget and are a separate hardening scope.
- **Task-hygiene (178 `hass.async_create_task` sites)** that the card's `AUDIT_2026_09_15` scoped to this card. That half SHIPPED in v5.103.5 and is OUT of this cycle; this cycle is only the four shutdown residuals.
- **No new config knobs, Numbers, Selects or Switches.**
- **No schema change** — this is Tier 2-DB for the `_db()` primitive, not for schema.

---

## Tier 2-DB review framings (for the orchestrator)

Three framing-disjoint reviews, run in parallel after build:

- **A — Correctness + log hygiene.** `DBShuttingDown` subclass placement, every DAO except-arm catches it ahead of `Exception`, no over-swallowing of non-shutdown errors, `_db_read` swap safe for every converted site (reads only, no writes hiding behind `PRAGMA query_only=ON`).
- **B — Lifecycle + migration correctness.** `async_add_shutdown_job` registration happens exactly once per CM start; unsub stored and called on entry-unload (Bug Class #34); shutdown-job ordering verified against HA `core.py` (reviewer re-reads `async_stop` + `async_block_till_done`); no double-fire if both the stop-job AND a residual periodic tick land in the same window; symmetric teardown.
- **C — Test authority + surfaces.** Tests actually drive production code paths (not their own mocks of the DB), including the discriminator tests (`test_db_other_errors_still_log_error`, bad-swap-would-fail oracles); per-site mutation drill on each of the 5 `_db_read()` swaps (revert one at a time, confirm a specific test fails); no silent neutral-default masking of a real regression.

Pre-deploy snapshot: capture the shutdown-window log line count by `(levelname, substring)` from the current develop restart (last v5.103.49 restart will do), to compare post-deploy ±25% (expect ~95 → 0 for the shutdown-attributed lines, migration lines unchanged).

Live Validation (Review D) uses the Live acceptance criteria from D1-D3 above as a one-shot post-restart read; README gets the Validated-<date> table in the same commit as the ship.

---

## Open questions for the operator

1. **DBShuttingDown export surface.** Should `DBShuttingDown` be exported from `database.py` only, or also re-exported from `const.py` / `__init__.py` for callers in other coordinators that want to catch it explicitly? Current plan: define in `database.py`, import where needed. (Default assumed if no answer.)
2. **Scope of D1 beyond `coordinator_diagnostics.py`.** The card and the v5.103.49 review named ~95 noisy lines, which empirically span `coordinator_diagnostics` + `census` + anomaly/energy snapshot writers. Should D1 convert **every** DAO caller except-arm house-wide in this cycle, or only the ones observed on the v5.103.49 restart log (likely the same set, but the former is a bigger diff)? Current plan: all DAO caller except-arms whose `try:` wraps a `database._db(` call (surfaced by the build-time grep). If the operator wants a narrower first pass, say so.
3. **Operator checkpoint before deploy.** Standard Tier 2-DB ask: confirm you want the orchestrator to deploy on green reviews + Live-D1/D2/D3 pass, or hold for an explicit go.

No question blocks the plan — all three can take defaults; flagged so the orchestrator surfaces them with the build-dispatch brief if desired.
