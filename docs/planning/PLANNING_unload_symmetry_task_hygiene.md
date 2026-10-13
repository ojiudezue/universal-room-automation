# PLANNING — UNLOAD-SYMMETRY-TASK-HYGIENE-1 (shutdown-teardown follow-ups)

Thread: platform / shutdown + DB hygiene
Tier: **2-DB** (shared DB primitive `database.py` + its `_db()` surface; builds immediately on top of v5.103.49)
Status: **PLAN ONLY — Rev 2 — do not build, commit or deploy**
Author: ura-planner (Rev 1 overnight autonomous pass 2026-10-13; Rev 2 same day applying plan review `docs/reviews/code-review/plan_review_unload_symmetry_task_hygiene.md`)

---

## Rev 2 reconciliation table (plan-review findings → Rev 2 changes)

| Finding | Sev | Change in Rev 2 | Where in this doc |
|---|---|---|---|
| **P1** | HIGH | D2 handler contract fixed: `_async_persist_coordinator_baselines_on_stop` is a zero-arg method invoked via `HassJob` with no args (not `(_event)`). Verified against HA `core.py:1077-1091` (`async_run_hass_job(job.job, *job.args)` with `job.args = ()`). D2 test now invokes the job the way core does. Verified real signature at `manager.py:647-649` takes `_event: Any` — Rev 2 drops the positional param. | D2 §What, D2 Acceptance |
| **P2** | HIGH | Invariant restated: column is `metric_baselines.last_updated` (verified at `database.py:1268-1278`), NOT `updated_at`. Timing restated: shutdown job runs in Stage 1 **before** STOP (verified `core.py:1077-1091`), bounded by `STOPPING_STAGE_SHUTDOWN_TIMEOUT=20s` (`core.py:112`). Discriminator becomes "later than last periodic tick AND no later than the `Stopping Home Assistant` log line", with `safety_rate`-scope rows as the stop-only discriminator (`manager.py:566-626` sets `include_safety_rate=True` **only** on the STOP path — periodic path leaves it False — so a `safety_rate` row written in the restart window is dispositive). | Invariant, D2 Live |
| **P3** | MED | §8 D3 enumeration corrected to the full 10-site inventory of `coordinator_diagnostics.py`: 6 reads (:320, :361, :752, :793, :825, **:1670 baseline load SELECT**) and **:1636** `get_anomaly_count` SELECT-COUNT (adds a 7th read), plus 3 writes (:274 log_decision INSERT, **:1776 save_baselines INSERT OR REPLACE**, **:1872 outcome_log INSERT**). D3 scope is the 7 reads; D1 scope includes the 3 write except-arms (notably :1801 — the exact save D2 protects). | §8, D3 §What, Verify count |
| **P4** | MED | D1 scope corrected. The 133 `except Exception` arms in `database.py` are not all migration — `database.py` itself holds many `async with self._db() as db` DAO methods (grep at build time), and those are the primary shutdown-noise sites. **Parsimony decision:** centralizing the handler in `database.py` is NOT viable — the neutral default (`0`, `None`, `[]`, `{}`, `1.0`) differs per DAO, so each caller still needs a site-local except arm; centralizing the *exception type* is exactly what D1 does. External caller files corrected to the ones that actually exist: `websocket_api.py`, `sensor.py`, `memory_facade.py`, `memory_compactor.py`, `optimization.py` / `optimization_llm.py`, `hvac.py`, `energy.py`, `notification_manager.py`, `button.py`, and `domain_coordinators/coordinator_diagnostics.py`. Removed the false references to `census.py` / `anomaly_log.py` / `safety.py` as top-level `_db()`-caller files (verified non-existent at those paths). | §8 Item 1, D1 §What |
| **P5** | MED | D1 extended: `_drain_pending_futures(reason)` at `database.py:429-444` must raise `DBShuttingDown("DB write failed: shutdown timeout")` **only when invoked on the shutdown path** (`_flush_pending_writes` call site at `:427` — reason == `"shutdown timeout"`). The lost-connection drain at `:377` (reason=`str(exc)`) keeps a plain `RuntimeError` so it still logs ERROR. Also: the `_LOGGER.warning("DB flush hit 5s budget …")` at `:400-402` and the drained-count WARNING at `:443-444` demote to DEBUG when `hass.is_stopping is True`. | §8 Item 1, D1 §What, D1 tests |
| **P6** | MED | D3 Live oracle replaced with an in-suite oracle (parsimony: no new exposed counter). The in-suite test asserts the 7 converted sites take the `_db_read()` path (via spy / isolation) and increment `_db_stats["reads"]` without touching `_db_stats["writes"]`. The post-restart "Live" bullet becomes a one-shot DB-level check: `_db_stats["reads"]` incremented over the dashboard-refresh window with `writes` unchanged on those specific calls — proved by targeted in-suite rather than live telemetry. Dropped the "sensor.ura_db_stats or equivalent" wording. | D3 Acceptance |
| **P7** | LOW | D2 teardown §: keep the existing `try: unsub(); except Exception: pass; self._...= None` shape at `manager.py:825-836` — `remove_job` raises `ValueError` on a second call and this shape already absorbs that. Also noted: Stage 1 runs **before** entry-unload, so `_running` is still True inside the STOP save path — a builder must NOT "fix" that guard. | D2 §What, Non-goals |
| **P8** | LOW | Confirmed `ANOMALY_BASELINE_STOP_SAVE_TIMEOUT_S = 30` at `manager.py:67` is **longer** than Stage 1's `STOPPING_STAGE_SHUTDOWN_TIMEOUT = 20` (HA `core.py:112`). D2 lowers it to **15s** so the save finishes inside Stage 1's budget with margin for the surrounding gather. This is the only new number touched; it stays a module constant (reviewed-change rung) — not a knob. | Numbers get knobs, D2 §What |

### Disagreement / nuance vs. the review

- **P4 "handle DBShuttingDown centrally in the DAO layer":** I disagree with the stronger reading of the suggestion. Catching `DBShuttingDown` inside `_db()` itself is impossible without the context manager yielding a stub connection, which creates ambiguous shape (what does a stub `SELECT` return? empty rows? `None`? each caller already picks its own neutral default). Centralizing the **exception type** (D1's existing shape) is the right amount of centralization; forcing a central handler would require every DAO to grow a sentinel-aware return path and would hide shutdown no-ops behind "looks like a legitimate zero". Rev 2 therefore keeps per-site `except DBShuttingDown` arms. Noted explicitly in the reconciliation above so the reviewer can push back if they meant something narrower.
- **P7 "the ordering is correct; no CRITICAL race":** agreed — Rev 1's "can race" wording was weak. Rev 2 restates D2 as a *determinism* fix (today's STOP listener runs after background-task cancel in Stage 2; the stop-time save is lost **every time**, not sometimes) and lifts the HA ordering claim verbatim from `core.py:1077-1123`.

---

## Parsimony verdict

**BUILD (narrow).** Three small, additive items on the same `_db()` surface the v5.103.49 fix opened. The marginal benefit is modest-but-real:

- **Item 1** (`DBShuttingDown` + DEBUG downgrade across DAO except-arms + shutdown-path drain path) — directly removes the ~95 ERROR/WARNING log lines v5.103.49 traded the 5-min stall for. Pure signal-to-noise; no new behavior.
- **Item 2** (CM baseline-save via `async_add_shutdown_job`) — the stop-time save is **lost every time** today (STOP listener runs post-cancel in Stage 2). Fix is ~10 lines + a timeout tweak.
- **Item 3** (diagnostics reads via `_db_read()`) — removes 7 reads from the single-writer serial queue. Latency win small; survives a stopped writer at shutdown.

Not PARK: three items on the same surface, each < ~30 LoC, ceremony largely paid at v5.103.49. Item 4 (close-stage buffering) remains **accepted / non-goal**, as carded.

---

## Falsifiable invariant (restated, Rev 2)

> **Across HA shutdown, URA emits ZERO `_LOGGER.error(...)` or `_LOGGER.warning(...)` lines whose root cause is "the write worker is closed / shutdown timeout", AND the stop-time anomaly-baseline save completes before background-task cancellation (Stage 2) — visible as `max(metric_baselines.last_updated)` later than the last periodic tick AND no later than the `Stopping Home Assistant` log line, with at least one row at `scope='safety_rate'` written in that window.**

Discriminators (how a bad fix would look different from a good one):

- **Bad fix masks writes still failing.** If D1 swallows errors but D2 is not actually running inside Stage 1, `metric_baselines.last_updated` stays at the last periodic tick and NO `scope='safety_rate'` row is written in the restart window. (Only the STOP path sets `include_safety_rate=True` — periodic calls leave it False at `manager.py:566-626`.) That makes `safety_rate`-scope row presence a stop-only oracle.
- **Bad fix moves logs from ERROR to DEBUG for all failures.** `DBShuttingDown` must be a *dedicated* subclass so only the stopping case is quieted; connection-lost / corruption / migration failures must still log at ERROR/WARNING. Discriminator: an induced non-stop failure (unit-test raising generic `RuntimeError` in a DAO) must still land ERROR.

---

## Institutional context verified

### 1. Prior art — code (REUSED vs NEW per proposed symbol)

| Proposed symbol | Verdict | Evidence |
|---|---|---|
| `DBShuttingDown(RuntimeError)` subclass | **NEW** | `grep -rn 'DBShuttingDown' custom_components/universal_room_automation/` → 0 hits. v5.103.49 raises bare `RuntimeError(...)` at `database.py:499-502`. No existing shutdown-signalling exception class to reuse. |
| Shutdown-stage flag | **REUSED** | `getattr(self.hass, "is_stopping", False) is True` already used at `database.py:497`. Reuse the same gate for routing drain-path warnings to DEBUG inside `_flush_pending_writes` / `_drain_pending_futures`. Note: `is_stopping` is **False** inside Stage 1 shutdown jobs (HA state is still `running` until `core.py:1101`); the gate therefore applies to the Stage-2 drain path, not to the Stage-1 D2 handler itself. |
| `async_add_shutdown_job` | **REUSED** | HA core API `homeassistant/core.py:1019-1039` (returns an unsub via `remove_job`, which raises `ValueError` on double-call — the existing try/except shape at `manager.py:825-836` absorbs that). Jobs run in Stage 1 under `STOPPING_STAGE_SHUTDOWN_TIMEOUT=20s` (`core.py:1077-1091`), **before** Stage 2 cancels background tasks (`core.py:1101`) and **before** `EVENT_HOMEASSISTANT_STOP` fires. |
| `_db_read()` context manager | **REUSED** | `database.py:644-654` — transient `aiosqlite.connect` + `PRAGMA query_only=ON`; bypasses the write worker; already increments `_db_stats["reads"]`. |
| `HassJob` wrapper | **REUSED** | HA core type expected by `async_add_shutdown_job`. |
| Timeout constant `ANOMALY_BASELINE_STOP_SAVE_TIMEOUT_S` | **REUSED, retuned** | `manager.py:67` currently `30`; Rev 2 lowers to `15` so the save finishes inside Stage 1's 20s budget. Module constant, not a knob. |
| Any new config knob / Number / Select / Switch | **NEW** / none | None introduced. |

### 2. Prior art — plans

- `docs/planning/kanban.data.yaml` card `UNLOAD-SYMMETRY-TASK-HYGIENE-1`: canonical scope.
- `docs/planning/kanban.data.yaml` card `SHUTDOWN-CENSUS-DB-WRITES-BLOCK-1`: shipped predecessor (v5.103.49), same `_db()` surface.
- `docs/readmes/README_v5.103.49.md` §2 and §Validated-2026-10-11: proves §2 fix landed, left `~95 ERROR/WARNING` log residuals + a race around the stop-time save.
- `docs/reviews/code-review/overnight_2026-10-06_shutdown_db_fastfail.md`: four MEDs that minted the INSTANCE block.
- `docs/reviews/code-review/plan_review_unload_symmetry_task_hygiene.md`: **Rev 1 plan review**, FIX-PLAN-REQUIRED (this doc is the response).

### 3. Prior art — memory / analysis

- `project_optimizer_db_write_flood_incident_2026_06_09` — items 1-3 do not add writes; item 3 REMOVES reads from the queue.
- `feedback_pre_deploy_zero_bugs_gate` — applies at build time.

### 4. Design doc

- `docs/QUALITY_CONTEXT.md` bug classes (restart resilience, task leaks, log hygiene, #34 symmetric teardown, #53 computed-but-not-consumed) apply.

### 5. Code locations surveyed end-to-end during Rev 2

- `custom_components/universal_room_automation/database.py:1-700` + spot-reads of DAO methods under `_db()`; `:1268-1278` (`metric_baselines` schema); `:1636-1646` and `:1670-1734` and `:1776-1802` and `:1872+` (diagnostics `_db()` sites verified by grep).
- `custom_components/universal_room_automation/domain_coordinators/manager.py:540-668` (wire + handler), `:825-836` (teardown shape).
- `.venv-ha/.../homeassistant/core.py:112-113` (stage-timeout constants), `:1019-1039` (`async_add_shutdown_job`), `:1077-1091` (Stage 1 gather), `:1093-1123` (Stage 2 cancel + STOP fire + final write).

### 6. Config-first check

**No knob fixes this.** All three items are code-site corrections. Config-first verdict: **not applicable, do code.**

### 7. Producer + consumer check (for D2's value: anomaly-baseline rows)

- **Producer:** `CoordinatorManager._persist_coordinator_baselines(include_safety_rate=True)` at `manager.py:566-640`, called by the shutdown-job registered in Rev 2's D2 (replacing today's STOP listener at `manager.py:554-559`).
- **Dependency health:** each coordinator's `_save_baselines` + `safety._save_rate_baselines` writes go through `database._db()`. Pre-fix, the write queue is already cancelled when the STOP listener fires in Stage 2 — the write fast-fails at `database.py:495-502`. Rev 2's D2 moves the save to Stage 1, where the worker is still alive.
- **Consumer:** on next boot, coordinators call `load_baselines` (`coordinator_diagnostics.py:1648`) to restore thresholds. If stop-time save is lost, restored baselines are up to `ANOMALY_BASELINE_SAVE_INTERVAL_S` stale (bounded, but measurable).

### 8. Independent re-enumeration (Rev 2 corrections)

The card lists specific line numbers; the plan treats those as a HYPOTHESIS and re-enumerates. Builder MUST re-grep at build time.

**Item 1 — DAO except-arms that log ERROR/WARNING on a `_db()` failure.**
- Inside `database.py` itself: many `async with self._db() as db` DAO methods (grep `rg -n "async with self\._db\(\) as db" database.py`) with sibling `except Exception as e: _LOGGER.error(...)` arms. Build-time grep required — the plan-time list is a hypothesis.
- External caller files (verified to exist via `ls custom_components/universal_room_automation/`): `websocket_api.py`, `sensor.py`, `memory_facade.py`, `memory_compactor.py`, `optimization.py`, `optimization_llm.py`, `hvac.py`, `energy.py`, `notification_manager.py`, `button.py`, `domain_coordinators/coordinator_diagnostics.py`. (Rev 1 named `census.py`, `anomaly_log.py`, `safety.py` as `_db()`-caller files — those paths do not exist at the top level; removed from the scope list.)
- The ~40 ERROR + ~55 WARNING count is the empirical v5.103.49 restart log; the site list is a **build-time derivation** (`rg -nB4 "except Exception as e:" --type py custom_components/ | rg -B4 "_LOGGER\.(error|warning)"`, filter to those whose `try:` contains `database._db(` or `self._db(`).
- **Item 1 ALSO covers the drain-path shutdown emissions inside `database.py`:**
  - `:400-402` — `_LOGGER.warning("DB flush hit 5s budget after %d writes", flushed)` → DEBUG when `hass.is_stopping is True`.
  - `:443-444` — `_LOGGER.warning("DB write worker drained %d pending writes", drained)` → DEBUG when `hass.is_stopping is True`.
  - `:427` — `_drain_pending_futures("shutdown timeout")` must raise `DBShuttingDown(...)` into the drained futures (so awaiting DAOs land in the DBShuttingDown DEBUG arm).
  - `:377` — `_drain_pending_futures(str(exc))` **stays** `RuntimeError` (connection-lost is a real failure).
  Implementation note: either pass an `is_shutdown: bool = False` flag to `_drain_pending_futures` (preferred — one site), or branch on `reason == "shutdown timeout"` inside the drain function.

**Item 3 — diagnostics `_db()` sites — corrected 10-site inventory of `coordinator_diagnostics.py`:**

| Line | Method | Op | Rev 2 scope |
|---|---|---|---|
| 274 | `DecisionLogger.log_decision` | INSERT | **OUT** of D3 (stays `_db()`); its except-arm **IN** D1 |
| 320 | `DecisionLogger.get_decisions` | SELECT | **IN** D3 → `_db_read()` |
| 361 | `DecisionLogger.get_decisions_count` | SELECT COUNT | **IN** D3 → `_db_read()` |
| 752 | `ComplianceTracker.get_compliance_rate` | SELECT | **IN** D3 → `_db_read()` |
| 793 | `ComplianceTracker.get_override_count` | SELECT | **IN** D3 → `_db_read()` |
| 825 | `ComplianceTracker.get_override_sources` | SELECT | **IN** D3 → `_db_read()` |
| **1636** | `AnomalyDetector.get_anomaly_count` | SELECT COUNT | **IN** D3 → `_db_read()` (missed by Rev 1) |
| **1670** | `AnomalyDetector.load_baselines` | SELECT (+ opportunistic DELETE prune on orphans) | **IN** D3 → `_db_read()` with caveat: the orphan-prune `DELETE` at `:1715-1720` is a write — must stay on `_db()`. Builder splits the method: SELECT via `_db_read()`, prune via a separate `_db()` block OR leaves `:1670` on `_db()` with a comment. Prefer the split (reads survive stopped worker). |
| **1776** | `AnomalyDetector.save_baselines` | INSERT OR REPLACE | **OUT** of D3 (write); its except-arm `:1801` **IN** D1 — this is the exact save D2 protects |
| **1872** | `OutcomeMeasurer.store_outcome` | INSERT | **OUT** of D3 (write); its except-arm **IN** D1 |

Net: 7 reads to convert, 3 writes left on `_db()`, 3 write except-arms also captured by D1. Rev 1 said "1 `_db()` + 5 `_db_read()`"; correct target is **3 `_db()` writes + 7 `_db_read()` reads** (counting the baseline-load split as one `_db_read()` site).

### 9. Verify-before-work

- D1: STILL-REAL — bare `RuntimeError` at `database.py:499-502` + bare `RuntimeError("DB write failed: ...")` at `:437`; `DBShuttingDown` grep → 0.
- D2: STILL-REAL — `manager.py:554-559` registers an `async_listen_once(EVENT_HOMEASSISTANT_STOP)` which fires in Stage 2 after background-task cancel; D2 moves it to Stage 1 via `async_add_shutdown_job`.
- D3: STILL-REAL for the 7 SELECT sites enumerated above.
- D4 (close-stage buffering): non-goal, no change.

---

## Numbers get knobs

**One tuning change:** `ANOMALY_BASELINE_STOP_SAVE_TIMEOUT_S` at `manager.py:67` drops `30 → 15`. Rationale: the save now runs inside Stage 1's 20s `STOPPING_STAGE_SHUTDOWN_TIMEOUT` (HA `core.py:112`); a 30s timeout would be truncated by Stage 1 anyway, and 15s leaves 5s of margin for the surrounding `asyncio.gather`. Stays a module constant — safety-adjacent, needs code review to retune — correct rung.

No other new numbers. No new Numbers / Selects / Switches / config-flow fields.

---

## Deliverables

### D1 — `DBShuttingDown(RuntimeError)` + DEBUG-level logging across DAO except-arms AND shutdown drain path

**What.**

1. Define a new exception subclass in `database.py` (module-level, exported):

```python
class DBShuttingDown(RuntimeError):
    """Raised when a DB write is submitted or drained after the worker has
    stopped because Home Assistant is shutting down. Expected during HA
    stop; callers log at DEBUG, not ERROR."""
```

2. Change `_db()` fast-fail at `database.py:499-502` to raise `DBShuttingDown(...)` instead of bare `RuntimeError(...)`.

3. Change `_drain_pending_futures` at `database.py:429-444` to accept the shutdown case (either a new `is_shutdown: bool = False` kwarg, or by branching on `reason == "shutdown timeout"`) and raise `DBShuttingDown("DB write failed: shutdown timeout")` into drained futures. The `_flush_pending_writes` call site at `:427` passes the shutdown signal. The `:377` lost-connection call site stays bare `RuntimeError` (real failure, keeps ERROR).

4. Demote the two drain-path WARNINGs at `database.py:400-402` and `:443-444` to DEBUG **only** when `getattr(self.hass, "is_stopping", False) is True`.

5. Update every DAO caller's `except Exception as e:` arm to catch `DBShuttingDown` first and log at DEBUG, falling through to the existing ERROR arm for everything else:

```python
except DBShuttingDown:
    _LOGGER.debug("DB op skipped: HA shutting down")
    return <neutral default>  # same default as the existing except arm
except Exception as e:
    _LOGGER.error("Error ...: %s", e)
    return <neutral default>
```

Scope of the DAO rewrite: all `_db()` caller except-arms whose `try:` block contains `database._db(` or `self._db(`. Build-time grep (§8). Specific files to sweep (verified-to-exist): `database.py` itself (its many `async with self._db() as db` DAO methods), `coordinator_diagnostics.py` (the 10 sites in §8 — 3 writes + 7 reads; D3 converts the 7 reads to `_db_read()` which does NOT raise `DBShuttingDown`, so only the 3 write except-arms need the DBShuttingDown arm; the 7 reads keep their existing except-arm but may add the DBShuttingDown arm defensively), `websocket_api.py`, `sensor.py`, `memory_facade.py`, `memory_compactor.py`, `optimization.py`, `optimization_llm.py`, `hvac.py`, `energy.py`, `notification_manager.py`, `button.py`. **Migration / table-creation except-arms in `database.py` (the 133-count majority) are NOT touched** — they run only at boot/migration and are outside the shutdown blast radius.

**Why not centralize in `_db()`:** the neutral-default return value differs per DAO (`0`, `None`, `[]`, `{}`, `1.0`). Centralizing the handler inside the context manager would require yielding a stub connection and inventing a per-call sentinel return — ambiguous and hides real failures behind "legitimate zero". Centralizing the **exception type** (this plan) + per-site DEBUG arm is the right split.

#### Acceptance criteria
- **Verify:** `rg -n "DBShuttingDown" custom_components/universal_room_automation/` returns the class definition + every DAO except-arm (builder commits the final count in the review doc).
- **Verify:** `rg -nP '_LOGGER\.(error|warning).*(shutdown|is stopping|write worker is closed|shutdown timeout)' custom_components/universal_room_automation/` returns zero caller-side matches not inside an `if not hass.is_stopping:` guard.
- **Test:** `test_db_shutting_down_logs_debug_not_error` — set `hass.is_stopping = True`, cancel the write task, call a sample DAO; assert (a) return value is the neutral default, (b) a `caplog.at_level(logging.DEBUG)` captures the DEBUG line, (c) no `levelname == "ERROR"` record is emitted.
- **Test:** `test_db_other_errors_still_log_error` — inject a generic `RuntimeError` (NOT `DBShuttingDown`) from a DAO and assert ERROR is still emitted (over-swallow discriminator).
- **Test:** `test_drain_pending_futures_shutdown_raises_dbshuttingdown` — drive `_flush_pending_writes` with items past the budget; assert drained futures raise `DBShuttingDown`.
- **Test:** `test_drain_pending_futures_connection_lost_raises_runtime_error` — simulate the `:377` path; assert drained futures raise plain `RuntimeError` (so it still logs ERROR). (P5 split discriminator.)
- **Live:** post-restart, `journalctl … -u home-assistant` across the shutdown window returns **zero** lines matching `grep -E "DB write failed: shutdown timeout|Error logging decision|Error getting compliance|Error counting overrides|Error saving baselines|DB flush hit 5s budget|DB write worker drained"`. Discriminator: a mid-day connection-lost (not shutdown) must still produce an ERROR line via the retry at `database.py:374-376`.

---

### D2 — CM stop-time baseline save via `async_add_shutdown_job`

**What.**

1. In `CoordinatorManager._wire_anomaly_baseline_persistence` (`manager.py:540-564`), replace the `self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, …)` registration with `self.hass.async_add_shutdown_job(HassJob(self._async_persist_coordinator_baselines_on_stop))`. Keep the unsub stored in `self._anomaly_baseline_stop_unsub`; the existing `try: unsub(); except Exception: pass; = None` teardown shape at `manager.py:825-836` already absorbs `remove_job`'s `ValueError`-on-double-call. **Do not "fix" the `_running` guard inside `_persist_coordinator_baselines`** — Stage 1 fires before entry-unload, so `_running` is still True (correct). The periodic timer registration is unchanged.

2. **Change the handler signature.** Today's `async def _async_persist_coordinator_baselines_on_stop(self, _event: Any)` at `manager.py:647-649` takes a positional event because `async_listen_once` delivers the event object. `async_add_shutdown_job` calls jobs via `async_run_hass_job(job.job, *job.args)` with `job.args = ()` (HA `core.py:1079-1084`) — zero positional args. Rev 2 drops the `_event` parameter:

```python
async def _async_persist_coordinator_baselines_on_stop(self) -> None:
    ...
```

3. Retune `ANOMALY_BASELINE_STOP_SAVE_TIMEOUT_S` from `30` to `15` at `manager.py:67` so the save finishes inside Stage 1's 20s `STOPPING_STAGE_SHUTDOWN_TIMEOUT`.

**Rationale (verified against installed HA `core.py`):** Stage 1 (`:1077-1091`) runs shutdown jobs under `STOPPING_STAGE_SHUTDOWN_TIMEOUT=20s` with HA state still `running` (so `is_stopping` is still False inside the job). Stage 2 (`:1093-1123`) then sets state to `stopping`, cancels **every background task** (including the URA write worker), fires `EVENT_HOMEASSISTANT_STOP`, and finally runs FINAL_WRITE. Today's STOP listener runs in Stage 2 **after** worker cancel; it hits either the v5.103.49 fast-fail at `database.py:495-502` or a dead worker. The stop-time save is lost **every time**. D2 moves it to Stage 1 while the worker is alive.

#### Acceptance criteria
- **Verify:** `rg -n "async_add_shutdown_job|EVENT_HOMEASSISTANT_STOP" domain_coordinators/manager.py` shows `async_add_shutdown_job` present for the baselines hook and the STOP-event listener for baselines removed. Other STOP listeners (e.g. house-state) are untouched.
- **Verify:** handler signature is zero-arg (`async def _async_persist_coordinator_baselines_on_stop(self) -> None:`). `grep "_async_persist_coordinator_baselines_on_stop" domain_coordinators/manager.py` shows no positional non-self argument.
- **Verify:** `ANOMALY_BASELINE_STOP_SAVE_TIMEOUT_S = 15` at `manager.py:67`.
- **Verify:** unsub stored and called in `async_stop` (Bug Class #34 symmetric teardown).
- **Test:** `test_coordinator_manager_baseline_shutdown_job_invoked_zero_arg` — construct a `HassJob` wrapping the handler and invoke it via `hass.async_run_hass_job(job, *())` exactly as `core.py:1083-1084` does; assert the save path ran. (P1 discriminator — a stale `(self, _event)` signature raises `TypeError` here, which `return_exceptions=True` would swallow in prod, so this test is the only place that catches it.)
- **Test:** `test_coordinator_manager_baseline_save_runs_before_worker_cancel` — fake hass with `_shutdown_jobs` + cancellable worker; trigger stage-1 gather; assert the handler ran while the worker task was not-done.
- **Test:** `test_coordinator_manager_baseline_save_unsub_called_on_entry_unload` (symmetry).
- **Live:** post-restart, query `metric_baselines` for `max(last_updated)` and the presence of at least one row with `scope='safety_rate'` written in the restart window. The invariant holds when `max(last_updated)` is **later than** the last periodic tick (visible via the preceding `ANOMALY_BASELINE_SAVE_INTERVAL_S` cadence) AND **no later than** the `Stopping Home Assistant` log line (the Stage-1→Stage-2 boundary). Discriminator: a bad fix where the shutdown job never runs leaves `max(last_updated)` at the periodic tick AND no `scope='safety_rate'` row in the window (only the STOP path sets `include_safety_rate=True`).

---

### D3 — Route diagnostics reads through `_db_read()`

**What.** In `domain_coordinators/coordinator_diagnostics.py`, convert the **7** read sites enumerated in §8 to `async with database._db_read() as db:`:
- `:320` `get_decisions`
- `:361` `get_decisions_count`
- `:752` `get_compliance_rate`
- `:793` `get_override_count`
- `:825` `get_override_sources`
- `:1636` `get_anomaly_count`
- `:1670` `load_baselines` (SELECT portion only — the orphan-prune `DELETE` at `:1715-1720` MUST stay on `_db()`; builder splits the SELECT and the prune into separate `async with` blocks: SELECT via `_db_read()`, prune via `_db()`)

The 3 write sites stay on `_db()`: `:274` `log_decision`, `:1776` `save_baselines`, `:1872` `store_outcome`. (Builder re-greps at build time — line numbers drift.)

**Rationale:** reads do not need write-queue serialization. Routing through `_db_read()` removes head-of-line blocking against pending writes, lets reads survive a stopped writer at shutdown, and uses `PRAGMA query_only=ON` to catch an accidental future write-regression.

#### Acceptance criteria
- **Verify:** `rg -c "database\._db\(\)" domain_coordinators/coordinator_diagnostics.py` returns **3** (log_decision + save_baselines prune/INSERT + store_outcome); `rg -c "database\._db_read\(\)"` returns **7** (one per converted site; `load_baselines`'s SELECT counts as one site).
- **Verify:** no SELECT-only method still uses `_db()`.
- **Test:** `test_diagnostics_reads_do_not_block_on_full_write_queue` — fill the fake write queue to capacity, call `get_decisions`, assert it returns before the queue drains.
- **Test:** `test_diagnostics_reads_survive_worker_stopped` — set `hass.is_stopping=True` and cancel the write task; call each of the 7 methods and assert they return their neutral defaults (empty list / 0 / 1.0) without raising and without emitting ERROR.
- **Test:** `test_diagnostics_reads_increment_reads_not_writes` (**in-suite oracle, P6**) — spy on `_db_stats` before/after; assert `_db_stats["reads"]` is incremented by exactly 7 across the 7 methods and `_db_stats["writes"]` is unchanged by them. Also assert at the method level that each converted site routes through `_db_read()` (via patching / spy) rather than `_db()`. Discriminator: a bad swap that left the read on `_db()` would increment `writes` here, which the assertion catches.
- **Test:** `test_load_baselines_split_prune_still_writes` — orphan-prune `DELETE` must still succeed after the SELECT→read split; assert the delete runs via `_db()` and `_db_stats["writes"]` increments.
- **Live:** none required; D3's correctness is fully captured by the in-suite oracle above (no new runtime counter to expose; parsimony).

---

## Non-goals (explicit)

- **Item 4 of the card (close-stage buffering).** Accepted / non-goal.
- **Any migration except-arm.** Boot-time / migration except-arms stay ERROR/WARNING.
- **Other coordinators' STOP-event listeners** (house-state persistence hook etc.) — separate hardening scope.
- **"Fixing" the `_running` guard** inside `_persist_coordinator_baselines` (`manager.py:593-597`). Stage 1 runs before entry-unload, `_running` is True there, no fix needed.
- **Task-hygiene (178 `hass.async_create_task` sites)** — shipped in v5.103.5 and OUT of this cycle.
- **No new config knobs, Numbers, Selects or Switches.**
- **No schema change.**
- **Centralizing the DBShuttingDown handler inside `_db()`** — rejected on grounds that the neutral default is per-DAO (see D1 §Why not centralize).

---

## Tier 2-DB review framings (for the orchestrator)

Three framing-disjoint reviews, run in parallel after build:

- **A — Correctness + log hygiene.** `DBShuttingDown` subclass placement; every DAO except-arm catches it ahead of `Exception`; no over-swallowing (test `test_db_other_errors_still_log_error`); P5 split correct — drain-shutdown raises DBShuttingDown, drain-connection-lost stays RuntimeError; `_db_read` swap safe at every converted site (reads only — the `load_baselines` split keeps the prune on `_db()`); orphan-prune still writes.
- **B — Lifecycle + migration correctness.** `async_add_shutdown_job` registered exactly once per CM start; unsub stored and called on entry-unload (Bug Class #34); shutdown-job ordering re-verified against HA `core.py:1019-1091`; handler is zero-arg (P1); timeout 15s < Stage 1's 20s (P8); no double-fire if a residual periodic tick lands in the same window; `_running` guard still True in Stage 1 (per P7).
- **C — Test authority + surfaces.** Tests drive production code paths; discriminator tests present (`test_db_other_errors_still_log_error`, `test_drain_pending_futures_connection_lost_raises_runtime_error`, `test_diagnostics_reads_increment_reads_not_writes`); per-site mutation drill on each of the 7 `_db_read()` swaps (revert one at a time; confirm a specific test fails); job-invocation test uses `async_run_hass_job(job, *())` NOT a direct method call (P1).

Pre-deploy snapshot: capture the shutdown-window log line count by `(levelname, substring)` from the current develop restart to compare post-deploy (expect ~95 → 0 for the shutdown-attributed lines; migration lines unchanged).

Live Validation (Review D) uses the Live acceptance criteria from D1 and D2 above as a one-shot post-restart check (D3 is in-suite only — P6). README gets the Validated-<date> table in the same commit as the ship.

---

## Open questions for the operator

1. **DBShuttingDown export surface.** Define in `database.py` and import where needed, or also re-export from `const.py` / `__init__.py`? Default: `database.py` only.
2. **Scope of D1 beyond `coordinator_diagnostics.py`.** Convert **every** DAO caller except-arm that wraps `database._db(` house-wide (bigger diff, cleanest invariant), or restrict first pass to the files observed on the v5.103.49 restart log? Default: house-wide — otherwise the invariant is probabilistic.
3. **Operator checkpoint before deploy.** Standard Tier 2-DB ask: deploy on green reviews + Live-D1/D2 pass, or hold for explicit go?

None of these blocks the plan — all take defaults.
