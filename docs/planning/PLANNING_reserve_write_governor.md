# PLANNING — Reserve Write Governor (Rev 3: writer lint + truthful dispatch ledger)

**Card:** `EC-RESERVE-WRITE-GOVERNOR-1`
**Tier:** 3. This is the single battery-reserve write surface, used by arbitrage, attain, drain, inclement, the EVSE/DP overlay, blind de-escalation and the write-verify self-heal. It has cost and safety ripple.
**Status:** `pre_planning`. It becomes BUILD-READY once the Rev-3 plan review passes.
**Branch target:** `develop`.
**Operator (2026-10-15):** *"25 places is mad. Force them through a governed slice with history and restart resilience. This is not about alerts at all."* *"Tough build → tight plan. Don't scope creep."*

**What the governor is (Rev 3, in one line):** a production allowlist of every reserve writer, enforced by an AST lint, plus one durable `ura_activity_log` row for each reserve value actually dispatched. It is not a floor engine. The one cross-cutting floor (inclement `partial_hold`) stays enforced where it is today, by the 8 `_floor_reserve` wraps. The governor records whether each real write honoured that floor.

---

## Rev-3 changelog (R2 finding → change)

| ID | Sev | Change |
|---|---|---|
| R2-01 | CRIT | **The desire row in `_result` is DROPPED.** One row is written for each **real** reserve dispatch, at three points that together cover every write: (1) the reserve leg of `_tap_write_verifier` (`energy.py:9095`). The timer dispatch loop (`energy.py:7389-7398`) calls it for every action in `decision["actions"]`, so this covers the `_result` append, the EVSE/DP overlay append (`energy.py:5516`) and blind de-escalation (`energy_battery.py:5664`). (2) The TOU-transition path, `_evaluate_battery` (`energy.py:7150-7221`). **Verified: it does NOT go through the tap.** It converts actions to `ServiceCallAction` for `CoordinatorManager` (comment `:7184-7185`), so it gets its own call in the action loop, with `verb="dispatch_queued"`. (3) `force_redispatch` (`energy_battery.py:6816-6820`), a direct `async_call`, with `verb="redispatch"` on success. A failure is already recorded by `record_dispatch_failed` (`:6833`), and the row gets `verb="redispatch_failed"`. |
| R2-02 | HIGH | `_tick_id` is deleted, together with its test and mutation row. The dispatch change gate is the only dedup. |
| R2-03 | HIGH | `redispatch` / `redispatch_failed` rows **bypass the change gate**, because they are rare real writes. The "hourly" claim was unsourced and is deleted. The real caller is the WriteVerifier pending-watchdog retry, `_pending_fire_retry` (`energy_write_verify.py:2331-2360`, which calls `battery.force_redispatch` at `:2344`). |
| R2-04 | HIGH | No invented constant. The row's `hold_owner` field is the **return value of `WriteVerifier._resolve_hold_owner(battery)`** (`energy_write_verify.py:1738`). Its live vocabulary is `dp_transition / evse_battery_hold / inclement / arbitrage_<phase> / strategy`. The row stores that string verbatim. `energy_write_verify.py` is not edited. The separate field `inclement_floor` carries the floor value. |
| R2-05 | HIGH | Lint re-specified: every `ast.Constant == "number.set_value"` in `domain_coordinators/energy*.py`, plus every call whose first two positional args are `"number", "set_value"`, must sit lexically inside a `(module, function)` pair in the production tuple `RESERVE_SET_VALUE_WRITERS` (`energy_const.py`), with a **pinned occurrence count**. Pool and EVSE-amp writers are listed as `non_reserve`. Role resolution and sentinel comments are dropped. The second assertion is deleted (R2-09). |
| R2-06 | HIGH | The floor-fold AC is removed as governor coverage, because the governor does no fold. Floor-fold stays covered by the existing tests that monkeypatch `_floor_reserve` (`test_battery_inclement_arbitrage_floor.py:595, 720, 758, 785`), unchanged. Byte-identical is now an **A/B** with a committed golden capture made before any governor code exists (§Acceptance). |
| R2-07 | MED | `proposed`/`final`/`winning_floor` are gone. The row records `value` (dispatched), `desire` (pre-overlay `_last_reserve_level_desired`), `hold_owner`, `inclement_floor` and `floor_ok`, so the floor's effect is visible honestly (`desire` vs `value` vs `inclement_floor`). |
| R2-08 | MED | Mechanism stated: `database.log_activity` (`database.py:6233`) runs one direct `INSERT` per row. It does not use the write queue. The row is scheduled fire-and-forget through `hass.async_create_task`, the same pattern as `_schedule_climate_write_row` (`hvac_setpoint.py:213-312`). Rate bound in §Row. |
| R2-09 | MED | The second lint assertion is deleted. |
| R2-10 | MED | The ordering test is made concrete (§Ordering). |
| R2-11 | LOW | Anchors fixed: `_resolve_hold_owner` `:1738`, `force_redispatch` `async_call` `:6816-6820`. Trailer fixed. |
| R2-12 | LOW | Moot. **No sensor attribute is added**, because the DB holds the history (operator: "cut the 20-row attribute unless needed"). `sensor.py` is not touched. |
| R1 carry-over | — | One floor only; wraps kept; DP floor stays in the overlay; no RestoreEntity; restart uses the existing `wv_commanded_ledger` (`energy.py:1940-1968, 2290-2330`); the strategy entity is `sensor.ura_battery_strategy`. All unchanged from Rev 2. |

---

## Institutional context verified (prior art, REUSE / BUILD per piece)

| Piece | Prior art (file:line) | Verdict |
|---|---|---|
| Writer completeness guard | `quality/tests/test_hvac_climate_write_funnel_completeness.py` (AST walk; allowlist imported from production `hvac_const.DYNAMIC_DOMAIN_ALLOWLIST`, `:26-39`) | **REUSE pattern.** Extended to the action-dict shape, which the HVAC lint does not cover. |
| Durable per-write row | `hvac_setpoint.py:_schedule_climate_write_row :213-312` (direct `db.log_activity`, fire-and-forget, never raises) | **REUSE pattern.** New `_record_reserve_dispatch` in `energy.py`. |
| Real-dispatch chokepoint | `energy.py:_tap_write_verifier :9041`, reserve leg `:9095-9113` (already filters to the configured reserve entity and stamps `_last_reserve_level` with the actual value) | **REUSE + one call.** |
| TOU-transition dispatch | `energy.py:_evaluate_battery :7150-7221` (bypasses the tap; it already special-cases CFG writes at `:7184-7205`) | **EXTEND with one call** in the same loop, mirroring the CFG special-case. |
| Self-heal re-send | `energy_battery.py:force_redispatch :6713-6852`; caller `energy_write_verify.py:_pending_fire_retry :2331-2360` | **EXTEND with one call** after the success log (`:6822`). |
| Owner vocabulary | `energy_write_verify.py:_resolve_hold_owner :1738` | **REUSE verbatim** (call it; store its string). |
| Floor enforcement | `energy_battery.py:_floor_reserve :3855` + 8 wraps + narration `:6687` | **UNCHANGED.** Not part of this build. |
| Restart | `wv_commanded_ledger` restore/save `energy.py:1940-1968, 2290-2330`; rows are durable in the DB | **REUSE unchanged.** Nothing to add. |
| Activity log write | `database.py:log_activity :6233` | **REUSE.** No schema change, no new table. |
| Typed `WriteResult` | `hvac_strategy.py:236-256` | **CARD follow-up** `EC-RESERVE-WRITE-RESULT-TYPE-1` (dispatch tap + `force_redispatch`). Not this cycle. |
| Borrow lease `ExcursionToken`, `PresetManager.borrow_live`, arrester borrow gate | `hvac_excursion.py:131`, `hvac_preset.py:73/234/253`, `hvac_override.py:4266-4315` | **Does not transfer.** The reserve floor has no owner, duration or begin/return lifecycle; it is recomputed every tick from the cached inclement decision. A lease would add stale-row reap + NM machinery and protect nothing. |
| Presence fusion, `perimeter_alert.py` | — | **Does not transfer.** These are fusion and alerting, not write governance. |

Docs read: plan reviews `plan_inclement_hardening_review_{1,2,3}.md`, `plan_reserve_governor_review_{1,2}.md`; `PLANNING_inclement_hardening.md` (site table), `PLANNING_arbitrage_wait_inclement_floor.md` (v5.5.3 D-HIGH-1); CLAUDE.md Tier-3.

---

## Falsifiable invariants

> **INV-G1 (writer allowlist):** every `"number.set_value"` constant and every `async_call("number","set_value",…)` in `domain_coordinators/energy*.py` lies inside a `(module, function)` entry of `RESERVE_SET_VALUE_WRITERS`, with exactly the pinned count. A new reserve writer anywhere in energy fails the suite.

> **INV-G2 (truthful ledger):** every reserve-entity `number.set_value` that URA dispatches produces exactly one `ura_activity_log` row with `action="reserve_write"` whose `value` equals the dispatched value, subject only to the change gate (§Row). No row is written for a value that was not dispatched (deadband-suppressed desires produce no row).

> **INV-G3 (no behaviour change):** dispatched action lists, `_last_reserve_level(_at)`, `_last_reserve_level_desired`, CFG writes and `verifier.schedule` calls are byte-identical with the row writer live vs patched to a no-op, on every branch: allow_discharge, partial_hold, full_hold, EVSE overlay, DP fold, blind de-escalation, TOU-transition evaluate, force_redispatch.

**Falsifiers:** (1) a reserve write lands on the hardware with no row (the history is incomplete); (2) a row whose `value` was never dispatched (e.g. the Repro-1 deadband case: current 20, desire 21); (3) Repro-2 (EVSE overlay sends 60 while the desire is 20) where the row does not say `value=60, desire=20, hold_owner=evse_battery_hold`; (4) any A/B diff.

Floor sub-invariant (enforced by the existing wraps, **observed** by the governor): under `partial_hold`, `value >= max(reserve_soc, reserve_floor)`. The row's `floor_ok` makes a violation queryable. It is not a new enforcement path.

---

## Design

### 1. `_record_reserve_dispatch` (new, `energy.py`, next to `_tap_write_verifier`)

```python
def _record_reserve_dispatch(self, *, verb: str, path: str, target: str,
                             value: int, reason: str | None) -> None:
    """One `reserve_write` activity row per REAL reserve dispatch. Never raises."""
```
- It computes `desire = battery._last_reserve_level_desired` and `hold_owner = self._write_verifier._resolve_hold_owner(battery)` (`None` if the verifier is absent).
- `inclement_floor = max(int(battery.reserve_soc), int(dec.reserve_floor))` iff `dec = battery._last_inclement_decision` is not None and `dec.hold_depth == "partial_hold"`; otherwise `None`. This is the same expression as the wraps and the narration (`:6689`).
- `floor_ok = value >= inclement_floor` if `inclement_floor` is not None, else `None`.
- **Change gate:** for `verb in ("dispatch", "dispatch_queued")`, skip the row when `(verb, value, hold_owner) == self._last_reserve_row_key`. `redispatch*` rows always write. The memo is RAM-only (it resets on boot, so the first post-boot write is always recorded).
- The payload goes into `details_json`: `{verb, path, value, desire, hold_owner, inclement_floor, floor_ok, reason}`. Columns: `coordinator="energy"`, `action="reserve_write"`, `entity_id=target`, `importance=RESERVE_WRITE_LOG_IMPORTANCE`.
- `db = hass.data[DOMAIN]["database"]`; call `db.log_activity(...)`; `hass.async_create_task(coro)` only if `inspect.iscoroutine`. All of it sits inside `try/except Exception → _LOGGER.debug`, a byte-for-byte copy of the climate-row guard.

### 2. Call sites (exactly three; no other edits)

| # | Where | verb / path | Value source |
|---|---|---|---|
| C1 | `_tap_write_verifier` reserve leg, after the target filter (`energy.py:~9097`), before `_note_battery_dispatch_outcome`. Pass `verb="dispatch_failed"` when `dispatch_result` reports failure, else `"dispatch"` | `path="timer"` | `data["value"]` (post-overlay, actual) |
| C2 | `_evaluate_battery` action loop (`energy.py:~7190-7219`), when `service == "number.set_value"` and the target equals the configured reserve entity (resolved like `_cfg_eid` at `:7186-7191`) | `verb="dispatch_queued"`, `path="evaluate"` | `data["value"]` |
| C3 | `force_redispatch` after the successful `async_call` (`energy_battery.py:~6822`) via `self._coord._record_reserve_dispatch(...)`; in the `except` branch (`:6826-6839`) with `verb="redispatch_failed"` | `path="redispatch"` | `live_desire` |

**Known limitation (documented, not fixed):** the tap returns at its top when `_write_verifier is None`. That happens only when `WriteVerifier` init raised (`energy.py:321-327`), which is a separate fault. In that state C1 writes no row. The A/B test pins that this config is otherwise unchanged.

### 3. Row rate bound

- Timer path: at most 1 reserve action per 5-min tick, so ≤288 rows/day worst case (desire or owner changing every tick). The `_result` deadband (`energy_battery.py:6390-6398`) plus the gate make the typical count tens per day.
- Evaluate path: TOU transitions only (a few per day).
- Redispatch: bounded by the WriteVerifier pending-watchdog (one retry per pending record, `energy_write_verify.py:2331-2360`).
- The 2026-06-09 write-flood lesson is answered by the gate and this bound, not by a queue.

### 4. Lint `quality/tests/test_reserve_write_chokepoint_lint.py`

- Production tuple in `energy_const.py`:
```python
RESERVE_SET_VALUE_WRITERS: tuple[tuple[str, str, str, int], ...] = (
    # (module, function, kind, pinned_count)
    ("energy_battery.py", "_result",                  "reserve",     1),  # :6395
    ("energy_battery.py", "determine_mode",           "reserve",     1),  # blind de-escalation :5664
    ("energy_battery.py", "force_redispatch",         "reserve",     2),  # async_call :6816 + failure record :6836
    ("energy.py",         "_apply_evse_battery_hold", "reserve",     1),  # :5516
    ("energy.py",         "_tap_write_verifier",      "reader",      1),  # svc compare :9095
    ("energy.py",         "_execute_shed_action",     "non_reserve", 2),  # :8710, :8734
    ("energy_pool.py",    "determine_actions",        "non_reserve", 2),  # :411, :429 pool speed
    ("energy_pool.py",    "_write_amps",              "non_reserve", 1),  # :4964 EVSE amps
)
```
  The builder **re-greps and corrects counts at build time**. The test imports this tuple; it is never hand-copied.
- The walker attributes each match to its innermost enclosing `FunctionDef/AsyncFunctionDef`. It fails on any match outside the tuple and on any count mismatch. A docstring containing the substring does not match, because equality is exact.
- Count-pinning is what makes allowlisting the huge `determine_mode` safe: a second writer in it changes the count.

---

## Ordering (R2-10)

`_last_inclement_decision` is set by `_cache_inclement` inside `_inclement_decision` (`energy_battery.py:2734`), during `determine_mode`. C1 and C2 run after `determine_mode` returns in the same coroutine, so they read the current call's decision. C3 reads the cache at redispatch time, which is the documented intent.
**Test `test_reserve_row_reads_current_tick_decision`:** tick 1 with partial_hold floor 30 dispatches 30 and the row has `inclement_floor=30`. Tick 2 with the decision at allow_discharge, desire 20, current 30 dispatches 20 and the row has `inclement_floor=None, floor_ok=None`. **Mutant:** `_record_reserve_dispatch` reads a decision frozen on first call. Tick 2 then has `inclement_floor=30` and the test goes RED.

---

## Config-extreme / edge cases

1. Deadband (current 20, desire 21): no action and **no row** (INV-G2 falsifier 2).
2. EVSE overlay (desire 20, hold 60): row `value=60, desire=20, hold_owner="evse_battery_hold"`.
3. DP fold raises the overlay value: row `hold_owner="dp_transition"`, value is the folded max.
4. Blind de-escalation: row via C1, `value=reserve_soc`, `inclement_floor` per cached decision. `floor_ok` may be False under partial_hold. That is correct and expected: it is the known unfloored site that `EC-INCLEMENT-HARDENING-1` D-blind will fix, and the row makes it visible.
5. Floor > target (`reserve_floor=80, peak_buffer_target=40`, partial_hold): wraps raise to 80; row `value=80, floor_ok=True`.
6. `reserve_soc=20, reserve_floor=10`, partial_hold: `inclement_floor=20` (R1-02 expression).
7. No decision yet (boot): `inclement_floor=None`.
8. DB missing: the row is skipped with a debug log; the dispatch proceeds.
9. Same value re-sent by the overlay every tick: the first row is written, the rest are gated until value or owner changes.
10. Redispatch of an unchanged desire: always a row.

---

## Mutation plan (Review C, real source edits, `PYTHONDONTWRITEBYTECODE=1`)

| Mutation | Must go RED |
|---|---|
| Delete C1 call | `test_reserve_row_on_timer_dispatch` |
| Delete C2 call | `test_reserve_row_on_evaluate_path` |
| Delete C3 success call | `test_reserve_row_on_force_redispatch` |
| C1 passes the pre-overlay desire instead of `data["value"]` | `test_reserve_row_records_overlay_value_not_desire` (Repro-2) |
| Remove the change gate | `test_reserve_row_gate_suppresses_identical_dispatch` |
| Apply the gate to redispatch | `test_reserve_row_redispatch_bypasses_gate` |
| `inclement_floor` uses `dec.reserve_floor` without the `max(reserve_soc, …)` | `test_reserve_row_inclement_floor_expression` |
| Freeze the decision read | `test_reserve_row_reads_current_tick_decision` |
| Inject a **dict-shape** `{"service": "number.set_value", …}` into a non-allowlisted energy function | `test_reserve_write_chokepoint_lint::test_no_unlisted_writers` |
| Inject a second dict-shape writer inside `determine_mode` | lint count mismatch |
| Inject `async_call("number","set_value",…)` into a non-allowlisted function | lint |

---

## Acceptance criteria

- **A/B (INV-G3), capture procedure:** **Commit 1** (before any governor code) adds `test_reserve_governor_ab.py`. It drives the timer dispatch, `_evaluate_battery` and `force_redispatch` through fakes, parametrized over allow_discharge, partial_hold, full_hold, EVSE overlay, DP fold and blind de-escalation, and writes the observed dispatched-action lists plus `_last_reserve_level(_at)`, `_last_reserve_level_desired` and `verifier.schedule` args to `quality/tests/fixtures/reserve_governor_golden.json`, which is committed. **Commit 2+** adds the governor; the same test asserts equality against the committed golden and also runs with `_record_reserve_dispatch` patched to a no-op. The reviewer verifies that the fixture's commit predates the governor commit (`git log --follow`).
- **Lint:** `test_reserve_write_chokepoint_lint.py` is green on HEAD. Every mutation row marked "lint" goes RED.
- **Rows:** the tests named in the mutation table pass. Repro-1 produces no row; Repro-2 produces the row values above.
- **Existing floor coverage:** `test_battery_inclement_arbitrage_floor.py` passes unchanged. It is a regression guard, not governor coverage.
- **Suite:** the full-suite name-diff vs `pre-review-v<version>` shows zero new failures.
- **Live (one-shot, at validation, no soak):** after restart, once at least one reserve write has occurred, run
  `SELECT timestamp, entity_id, json_extract(details_json,'$.verb'), json_extract(details_json,'$.value'), json_extract(details_json,'$.hold_owner'), json_extract(details_json,'$.floor_ok') FROM ura_activity_log WHERE action='reserve_write' ORDER BY timestamp DESC LIMIT 10;`
  **PASS** when the newest row's `value` equals the live state of the configured reserve number entity, or its `commanded` value in write-verify's `command_trail` on `sensor.ura_battery_strategy`. Also confirm no row has `floor_ok=0` outside a blind episode. **Discriminator:** a desire-only recorder (the Rev-2 bug) would show rows with no matching hardware change, and an overlay-blind recorder would show `value != commanded` during EVSE charging.
- **Live log check (one-shot):** grep the journald window since restart for `reserve_write` debug failures and tracebacks mentioning `_record_reserve_dispatch`. Zero expected.

---

## Non-goals

1. No floor registry, no fold in `_result`, no edit to the 8 wraps or the narration.
2. No inclement logic change. The blind write stays unfloored until `EC-INCLEMENT-HARDENING-1`, and the row makes it visible.
3. No edit to the EVSE overlay internals, DP placement, write-verify contract or `_resolve_hold_owner`.
4. No sensor attribute, no RestoreEntity, no schema/table, no new signal, no config field.
5. No `WriteResult` (carded), no leases, no presence/perimeter pattern.

## Knobs

| Name | Rung | Default | Why |
|---|---|---|---|
| `RESERVE_SET_VALUE_WRITERS` | 1 (`energy_const.py`) | table above | A topology change; adding a writer must be reviewed. |
| `RESERVE_WRITE_LOG_IMPORTANCE` | 1 | same value as `CLIMATE_WRITE_LOG_IMPORTANCE` | Parity with the HVAC write row. |

There are no rung-2 or rung-3 knobs.

---

## Build-risk prediction

1. Re-adding a row in `_result` ("for desire history"). **Don't**: the row lives at dispatch only.
2. Placing C1 before the reserve-target filter, which logs pool or unrelated `number.set_value` dispatches.
3. Reading `desire` for `value` at C1, which reproduces Repro-2.
4. Forgetting C2 because "the tap covers everything". It doesn't (`:7184-7185`).
5. Gating redispatch rows.
6. Awaiting `log_activity`, which back-pressures dispatch.
7. Hand-copying the allowlist into the test, or matching only `async_call` and missing the dict shape.
8. Leaving allowlist counts stale after the build. Re-grep and correct them in the same commit.
9. Writing the golden fixture in the same commit as the governor, which makes the check a tautology.
10. Touching `_floor_reserve` or the wraps. They are out of scope; the existing tests patch them.

## Tier-3 reviews (parallel, disjoint)

- **A (local correctness):** row payload, gate key, the `inclement_floor` expression, verb selection.
- **B (integration/lifecycle):** C1/C2/C3 placement; no change to tap ledger stamping or CFG handling; fire-and-forget safety; evaluate-path target resolution.
- **C (test authority):** the mutation table above, with real edits.
- **D (adversarial completeness):** independently enumerate every reserve write reachable in HA (including through `CoordinatorManager`) and every `number.set_value` in the package. Confirm each has a row path and an allowlist entry, and try to produce a reserve write with no row.

The orchestrator re-runs the lint and one mutation before ship. **Operator checkpoint before deploy.**

## Sequencing

Ship this first. `EC-INCLEMENT-HARDENING-1` D-blind then routes blind through `_result`: it changes the `determine_mode` count in `RESERVE_SET_VALUE_WRITERS`, and its rows show `floor_ok` flipping to True.

## Files touched

- `domain_coordinators/energy.py`: `_record_reserve_dispatch`, `_last_reserve_row_key`, calls C1 and C2. About +70 LoC.
- `domain_coordinators/energy_battery.py`: call C3 (two lines inside `force_redispatch`).
- `domain_coordinators/energy_const.py`: `RESERVE_SET_VALUE_WRITERS`, `RESERVE_WRITE_LOG_IMPORTANCE`.
- `quality/tests/test_reserve_write_chokepoint_lint.py`, `test_reserve_write_rows.py`, `test_reserve_governor_ab.py`, `fixtures/reserve_governor_golden.json`: NEW.
- `docs/readmes/README_v<version>.md`: written before deploy; post-restart validation written back.

Not touched: `sensor.py`, `energy_write_verify.py`, `energy_drain_precedence.py`, `database.py`, config/options flows.

---

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018uEjYPUcWq73wfBS3t1NEa
