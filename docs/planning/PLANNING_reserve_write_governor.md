# PLANNING — Reserve Write Governor (Rev 3.2: writer lint + truthful dispatch ledger)

**Card:** `EC-RESERVE-WRITE-GOVERNOR-1`
**Tier:** 3. This is the single battery-reserve write surface, used by arbitrage, attain, drain, inclement, the EVSE/DP overlay, blind de-escalation and the write-verify self-heal. It has cost and safety ripple.
**Status:** BUILD-READY (Rev 3.2). Builder: **ura-fable-builder**.
**Branch target:** `develop`.
**Operator (2026-10-15):** *"25 places is mad. Force them through a governed slice with history and restart resilience. This is not about alerts at all."* *"Tough build → tight plan. Don't scope creep."*

**What the governor is (Rev 3, in one line):** a production allowlist of every reserve writer, enforced by an AST lint, plus one durable `ura_activity_log` row for each reserve value actually dispatched. It is not a floor engine. The one cross-cutting floor (inclement `partial_hold`) stays enforced where it is today, by the 8 `_floor_reserve` wraps. The governor records whether each real write honoured that floor.

---

## Rev-3.2 changelog (ground-truth audit `audit_reserve_surface_ground_truth.md` + operator decision)

| ID | Sev | Change |
|---|---|---|
| G-1 | MED | C3 rows moved **outside** the `force_redispatch` service-call `try`: the success row goes after step 5's ledger stamp, and the failure row goes after `record_dispatch_failed`. Each is reached through `getattr(self, "_coord")` → `getattr(coord, "_record_reserve_dispatch")` inside its own `try/except: debug`. New mutation/test: `test_force_redispatch_row_call_cannot_fake_failure`. |
| G-2 | MED | Live AC rewritten. Entity is `sensor.ura_energy_coordinator_battery_strategy`. Compare against the **cloud write-leg** `number.iq_battery_hacs_battery_reserve` with about 90 s cloud lag. The local Envoy entity is a witness, not a write target. |
| G-3 | MED | `("radar_tuning.py", "async_send_radar_settings", "non_reserve", 1)` added. The "radar uses a variable domain" claim (Rev 3.1 / R3-02) was false and is removed. |
| G-4 | LOW | Write-queue text corrected: `log_activity` → `_db()` = the single-worker write queue, one item per row (fixes the R2-08 text). |
| G-5 | LOW | `pre_state = battery._get_state_float(target)`, compared as `int(round(pre_state)) == int(value)`. None means the row is written. |
| G-6 | LOW | C1 and C2 write a row only when the configured write-leg reserve entity is truthy and equals the target. The existing tap filter is untouched. |
| G-7 | LOW | `hold_owner` is documented as the highest-precedence active subsystem, not the value's source. `evse_hold_soc` is added to the row so provenance can be derived. |
| G-8 | LOW | Timer/CM interleaving is documented as a row-data-only limitation (§2 Known limitations); §Ordering is qualified. |
| G-9 | LOW | The `floor_ok` AC requires investigating any hit against the inclement-hardening site table before calling it a governor defect. |
| D-6 / audit | LOW | Inline off-peak partial_hold clamps `:6224` / `:6262` are added to the prior-art floor inventory and the non-goals. Edge case 9c covers the legitimate below-`reserve_soc` off-peak hold. Edge case 4 notes blind de-escalation is provable only in-suite until the June peak. |
| Earlier-review errors | — | R1-03's `sensor.ura_battery_strategy` was **wrong** (the entity does not exist); corrected throughout. R2-08's "no write queue" was **wrong**. R3-02's "radar variable domain" was **wrong**. |
| Operator | — | **Typed outcomes folded:** the row's `verb` is replaced by `status` (imported `hvac_strategy.WriteStatus`: `applied` / `failed` / `deferred`; `skipped_already_correct` is the meaning of a gated, unwritten no-op) plus `path` (`timer` / `evaluate` / `redispatch`). There is no `WriteResult` plumbing and no change to the dispatch return contract. Earlier changelog rows that mention `verb`, `dispatch_queued` or `redispatch_failed` map as follows: `dispatch` → `applied`/timer, `dispatch_failed` → `failed`/timer, `dispatch_queued` → `deferred`/evaluate, `redispatch` → `applied`/redispatch, `redispatch_failed` → `failed`/redispatch. |
| Builder | — | **ura-fable-builder.** |

---

## Rev-3.1 changelog (R3 finding → change; review 3 said READY once these text edits land)

| ID | Sev | Change |
|---|---|---|
| R3-01 | HIGH | **Gate rule changed.** A `dispatch`/`dispatch_queued` row is skipped only when **both** hold: its key matches the memo **and** the target's **pre-write hardware state** already equals `value`. Drift correction (cloud reverted 30→20, URA re-sends 30) is therefore always logged. Steady overlay re-sends (hardware already 60) stay gated. New test `test_reserve_row_records_drift_correction` + a mutant that drops hardware state from the rule (must go RED). |
| R3-02 | MED | The lint now scans the **whole package** and also matches the keyword form `async_call(domain="number", service="set_value")` and a positional `"set_value"` whose domain is the literal `"number"`. Evasions it cannot see are listed as known limits, and INV-G1 is reworded to match. |
| R3-03 | MED | `("energy.py", "_evaluate_battery", "reader", 1)` is added for C2's comparison. The counting rule is stated in §4. |
| R3-04 | MED | C1 and C2 pass `reason=decision.get("reason")`. The live check excludes blind rows by the `Blind de-escalation` reason prefix. |
| R3-05 | MED | The A/B golden fixture runs under a frozen `dt_util.utcnow`/`dt_util.now`, so the timestamp fields (`_last_reserve_level_at`, the `verifier.schedule` time arg) stay in the fixture. |
| R3-06 | LOW | Every written row updates the memo. `dispatch_failed` and `redispatch*` rows are ungated. |
| R3-07 | LOW | Known limitations: a `dispatch_queued` failure inside the CM is swallowed and leaves no failure row. Pre-existing gap: the evaluate path never stamps `_last_reserve_level` or calls the verifier. Carded as `EC-EVALUATE-PATH-LEDGER-GAP-1`; not fixed here. |
| R3-08 | LOW | Edge case 4: on blind rows `desire` is the **previous tick's** value, because blind bypasses `_result`. |
| R3-09 | LOW | Prior art gains `_log_charger_actuation` (`energy.py:7772`), with the reason the HVAC pattern was preferred. |

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
| R2-08 | MED | Rate bound in §3. *(Rev 3.2 correction: the Rev-3 text claimed `log_activity` bypasses the write queue. That was false: `_db()` is the queue submitter. See §3.)* |
| R2-09 | MED | The second lint assertion is deleted. |
| R2-10 | MED | The ordering test is made concrete (§Ordering). |
| R2-11 | LOW | Anchors fixed: `_resolve_hold_owner` `:1738`, `force_redispatch` `async_call` `:6816-6820`. Trailer fixed. |
| R2-12 | LOW | Moot. **No sensor attribute is added**, because the DB holds the history (operator: "cut the 20-row attribute unless needed"). `sensor.py` is not touched. |
| R1 carry-over | — | One floor only; wraps kept; DP floor stays in the overlay; no RestoreEntity; restart uses the existing `wv_commanded_ledger` (`energy.py:1940-1968, 2290-2330`); the strategy entity is `sensor.ura_energy_coordinator_battery_strategy` (corrected in Rev 3.2; `sensor.ura_battery_strategy` does not exist). All unchanged from Rev 2. |

---

## Institutional context verified (prior art, REUSE / BUILD per piece)

| Piece | Prior art (file:line) | Verdict |
|---|---|---|
| Writer completeness guard | `quality/tests/test_hvac_climate_write_funnel_completeness.py` (AST walk; allowlist imported from production `hvac_const.DYNAMIC_DOMAIN_ALLOWLIST`, `:26-39`) | **REUSE pattern.** Extended to the action-dict shape, which the HVAC lint does not cover. |
| Durable per-write row | `hvac_setpoint.py:_schedule_climate_write_row :213-312` (direct `db.log_activity`, fire-and-forget, never raises) | **REUSE pattern.** New `_record_reserve_dispatch` in `energy.py`. |
| Same-file activity row | `energy.py:_log_charger_actuation :7772` (best-effort activity row for charger switch writes, filtered by target) | **Considered; HVAC pattern preferred.** Both are best-effort and never raise. `_schedule_climate_write_row` is the closer fit because it is the funnel-paired write ledger: one row per real write, `details_json` payload, an explicit fire-and-forget scheduling contract, and it sits next to an AST completeness lint. The builder should copy the local style of `_log_charger_actuation` (`self.hass`, same-file helper) and follow the climate-row contract. |
| Real-dispatch chokepoint | `energy.py:_tap_write_verifier :9041`, reserve leg `:9095-9113` (already filters to the configured reserve entity and stamps `_last_reserve_level` with the actual value) | **REUSE + one call.** |
| TOU-transition dispatch | `energy.py:_evaluate_battery :7150-7221` (bypasses the tap; it already special-cases CFG writes at `:7184-7205`) | **EXTEND with one call** in the same loop, mirroring the CFG special-case. |
| Self-heal re-send | `energy_battery.py:force_redispatch :6713-6852`; caller `energy_write_verify.py:_pending_fire_retry :2331-2360` | **EXTEND with one call** after the success log (`:6822`). |
| Owner vocabulary | `energy_write_verify.py:_resolve_hold_owner :1738` | **REUSE verbatim** (call it; store its string). |
| Floor enforcement | `energy_battery.py:_floor_reserve :3855` + 8 wraps + narration `:6687` + **inline off-peak partial_hold clamps `:6224` (drain) / `:6262` (hold)** | **UNCHANGED.** Not part of this build. |
| Restart | `wv_commanded_ledger` restore/save `energy.py:1940-1968, 2290-2330`; rows are durable in the DB | **REUSE unchanged.** Nothing to add. |
| Activity log write | `database.py:log_activity :6233` | **REUSE.** No schema change, no new table. |
| Typed outcome vocabulary | `hvac_strategy.py:WriteStatus :238-242` (stdlib-only module) | **FOLDED IN (operator, Rev 3.2).** Row `status` is an imported `WriteStatus` member. **No `WriteResult` plumbing**: the dispatch return contract (`ServiceDispatchResult`) is unchanged. `EC-RESERVE-WRITE-RESULT-TYPE-1` shrinks to "typed dispatch return contract", if ever. |
| Borrow lease `ExcursionToken`, `PresetManager.borrow_live`, arrester borrow gate | `hvac_excursion.py:131`, `hvac_preset.py:73/234/253`, `hvac_override.py:4266-4315` | **Does not transfer.** The reserve floor has no owner, duration or begin/return lifecycle; it is recomputed every tick from the cached inclement decision. A lease would add stale-row reap + NM machinery and protect nothing. |
| Presence fusion, `perimeter_alert.py` | — | **Does not transfer.** These are fusion and alerting, not write governance. |

Docs read: plan reviews `plan_inclement_hardening_review_{1,2,3}.md`, `plan_reserve_governor_review_{1,2}.md`; `PLANNING_inclement_hardening.md` (site table), `PLANNING_arbitrage_wait_inclement_floor.md` (v5.5.3 D-HIGH-1); CLAUDE.md Tier-3.

---

## Falsifiable invariants

> **INV-G1 (writer allowlist):** every **statically visible** `number`/`set_value` writer anywhere in `custom_components/universal_room_automation/` lies inside a `(module, function)` entry of `RESERVE_SET_VALUE_WRITERS`, with exactly the pinned count. That means a `"number.set_value"` constant, a positional `async_call("number","set_value",…)`, or the keyword form `async_call(domain="number", service="set_value",…)`. Known limits the AST cannot see: a domain or service passed in a variable, the HA constant `SERVICE_SET_VALUE`, strings built at runtime, and in-place mutation of an existing action dict (the EVSE overlay update leg). Review D covers those by grep. `radar_tuning.py:274-279` is a literal writer (not a variable-domain one, as Rev 3.1 wrongly said) and is listed `non_reserve`.

> **INV-G2 (truthful ledger):** every reserve-entity `number.set_value` that URA dispatches produces exactly one `ura_activity_log` row with `action="reserve_write"` whose `value` equals the dispatched value, subject only to the change gate (§Row). No row is written for a value that was not dispatched (deadband-suppressed desires produce no row).

> **INV-G3 (no behaviour change):** dispatched action lists, `_last_reserve_level(_at)`, `_last_reserve_level_desired`, CFG writes and `verifier.schedule` calls are byte-identical with the row writer live vs patched to a no-op, on every branch: allow_discharge, partial_hold, full_hold, EVSE overlay, DP fold, blind de-escalation, TOU-transition evaluate, force_redispatch.

**Falsifiers:** (1) a reserve write lands on the hardware with no row (the history is incomplete); (2) a row whose `value` was never dispatched (e.g. the Repro-1 deadband case: current 20, desire 21); (3) Repro-2 (EVSE overlay sends 60 while the desire is 20) where the row does not say `value=60, desire=20, hold_owner=evse_battery_hold`; (4) any A/B diff.

Floor sub-invariant (enforced by the existing wraps, **observed** by the governor): under `partial_hold`, `value >= max(reserve_soc, reserve_floor)`. The row's `floor_ok` makes a violation queryable. It is not a new enforcement path.

---

## Design

### 1. `_record_reserve_dispatch` (new, `energy.py`, next to `_tap_write_verifier`)

```python
from .hvac_strategy import WriteStatus   # stdlib-only module; no cycle. Imported, never re-typed.

def _record_reserve_dispatch(self, *, status: WriteStatus, path: str, target: str,
                             value: int, reason: str | None,
                             pre_state: float | None = None) -> None:
    """One `reserve_write` activity row per REAL reserve dispatch. Never raises."""
```
- **Status vocabulary (Rev 3.2, operator decision):** `status` is a `hvac_strategy.WriteStatus` member (`hvac_strategy.py:238-242`), stored as `status.value`:
  - `APPLIED`: timer dispatch or redispatch, `dispatch_result` ok.
  - `FAILED`: dispatch or redispatch raised or was reported failed.
  - `DEFERRED`: the evaluate path handed the action to `CoordinatorManager` (it is executed later, outcome unseen).
  - `SKIPPED_ALREADY_CORRECT`: the meaning of a gated no-op re-send. It is **not written** (the gate suppresses the row), but tests reference the member by name.
  `path ∈ {"timer", "evaluate", "redispatch"}` says where the write came from. There is **no `WriteResult` plumbing**: `_execute_service_action` / `ServiceDispatchResult` and the tap's return contract are unchanged. Only the row's vocabulary is typed.
- It computes `desire = battery._last_reserve_level_desired` and `hold_owner = self._write_verifier._resolve_hold_owner(battery)` (`None` if the verifier is absent). **`hold_owner` means the highest-precedence active subsystem, not the value's source** (G-7). Example: arbitrage HOLD 80 plus EVSE hold 45 gives value 80 labelled `evse_battery_hold`. To derive provenance, the row also carries `evse_hold_soc` (`self._evse_hold_soc`); compare `desire`, `value` and `evse_hold_soc`. `_resolve_hold_owner` is not changed.
- `inclement_floor = max(int(battery.reserve_soc), int(dec.reserve_floor))` iff `dec = battery._last_inclement_decision` is not None and `dec.hold_depth == "partial_hold"`; otherwise `None`. This is the same expression as the wraps and the narration (`:6689`).
- `floor_ok = value >= inclement_floor` if `inclement_floor` is not None, else `None`.
- **Change gate:** `pre_state` is the target's numeric value before the write, read as `battery._get_state_float(target)` (`energy_battery.py:881`). HA state is the string `"10.0"`, so a raw compare would never match (G-5). For `status in (APPLIED, DEFERRED)` and `path != "redispatch"`, the row is skipped only when `(path, value, hold_owner) == self._last_reserve_row_key` **and** `pre_state is not None and int(round(pre_state)) == int(value)`. `FAILED` and every `redispatch` row are never gated. Every written row updates the memo. The memo is RAM-only, so the first write after boot always gets a row.
- **Where `pre_state` comes from:** C1 reads it in the timer dispatch loop (`energy.py:~7389`) **before** `_execute_service_action`, only for reserve-target `number.set_value` actions, and passes it to `_tap_write_verifier` as a new keyword-only `pre_state=None` (the default leaves other callers unchanged). C2 reads it in place, because the CM has not executed yet. C3 does not gate.
- The payload goes into `details_json`: `{status, path, value, desire, evse_hold_soc, hold_owner, inclement_floor, floor_ok, pre_state, reason}`. Columns: `coordinator="energy"`, `action="reserve_write"`, `entity_id=target` (the **write-leg** entity, e.g. `number.iq_battery_hacs_battery_reserve` under cloud-first), `importance=RESERVE_WRITE_LOG_IMPORTANCE`.
- `db = hass.data[DOMAIN]["database"]`; call `db.log_activity(...)`; `hass.async_create_task(coro)` only if `inspect.iscoroutine`. Everything sits inside `try/except Exception → _LOGGER.debug`, the same guard as the climate row.

### 2. Call sites (exactly three; no other edits)

| # | Where | status / path | Value source |
|---|---|---|---|
| C1 | `_tap_write_verifier` reserve leg, after the existing target filter (`energy.py:~9097`), before `_note_battery_dispatch_outcome`. **Row only when the resolved `reserve_eid` is truthy and `target == reserve_eid`** (G-6). The tap's own filter behaviour is left untouched. `FAILED` if `dispatch_result` reports failure, else `APPLIED`. Pass `reason=decision.get("reason")` and `pre_state`. | `path="timer"` | `data["value"]` (post-overlay, actual) |
| C2 | `_evaluate_battery` action loop (`energy.py:~7190-7219`), when `service == "number.set_value"` and a truthy configured write-leg reserve entity equals `target` (resolved like `_cfg_eid` at `:7186-7191`). Pass `reason=decision.get("reason")` and the in-place `pre_state`. | `DEFERRED`, `path="evaluate"` | `data["value"]` |
| C3 | `force_redispatch` (G-1). **Success row goes AFTER the try/except AND after step 5's ledger stamp** (`energy_battery.py:~6845-6852`). **Failure row goes AFTER `record_dispatch_failed`** in the except branch (`:6826-6839`), before its `return`. Both use `coord = getattr(self, "_coord", None); fn = getattr(coord, "_record_reserve_dispatch", None)` inside their **own** `try/except Exception: _LOGGER.debug`. The row call can never land in the service-call `except`, so it can never cause a false `dispatch_failed` or skip the ledger stamp. | `APPLIED` / `FAILED`, `path="redispatch"` | `live_desire` |

**Known limitations (documented, not fixed):**
- **`DEFERRED` outcome:** the C2 row is written before the CM executes (`manager.py:1035-1070`). An execution failure there is swallowed by the CM's try/except and leaves no `FAILED` row.
- **Evaluate-path ledger gap (pre-existing):** the evaluate path never stamps `_last_reserve_level` and never calls the verifier. Carded `EC-EVALUATE-PATH-LEDGER-GAP-1`; not fixed here.
- **No verifier:** the tap returns at its top when `_write_verifier is None`, which happens only when `WriteVerifier` init raised (`energy.py:321-327`), a separate fault. In that state C1 writes no row.
- **Timer/CM interleaving (G-8, row data only):** `_evaluate_battery` is not guarded by `_cycle_in_flight` (`energy.py:6326-6336`). If a CM evaluate re-runs `determine_mode` while a timer tick is suspended between `determine_mode` (`:6390`) and dispatch, the timer's C1 row can read the evaluate run's `desire` / `_last_inclement_decision`. The **dispatch is unaffected**; only the row's `desire` / `inclement_floor` / `hold_owner` can be off. This is rare (it needs a CM evaluate inside the seconds a boundary tick is in flight). Accepted rather than threading captured values through the awaits (scope).

### 3. Row rate bound

- Timer path: at most 1 reserve action per 5-min tick, so ≤288 rows/day worst case (desire or owner changing every tick). The `_result` deadband (`energy_battery.py:6390-6398`) plus the gate make the typical count tens per day.
- Evaluate path: TOU transitions only (a few per day).
- Redispatch: bounded by the WriteVerifier pending-watchdog (one retry per pending record, `energy_write_verify.py:2331-2360`).
- **Mechanism (corrected, G-4/D-2):** `log_activity` (`database.py:6233`) uses `async with self._db()`, and `_db()` **is** the single-worker write-queue submitter (`database.py:523-541`). Each row is one queue item. During a VACUUM or worker restart, rows buffer (`:530-541`). At shutdown they fast-fail (`:543-548`). Neither path back-pressures dispatch, because the helper is fire-and-forget. The audit measured about 67 dispatch rows/day (430 dispatches + 40 redispatches in 7 days). The 2026-06-09 write-flood lesson is answered by the gate plus this bound.

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
    ("energy.py",         "_evaluate_battery",        "reader",      1),  # C2 compare (new)
    ("energy.py",         "_execute_shed_action",     "non_reserve", 2),  # :8710, :8734
    ("energy_pool.py",    "determine_actions",        "non_reserve", 2),  # :411, :429 pool speed
    ("energy_pool.py",    "_write_amps",              "non_reserve", 1),  # :4964 EVSE amps
    ("radar_tuning.py",   "async_send_radar_settings","non_reserve", 1),  # :274-279 radar device numbers (G-3)
)
```
  The builder **re-greps and corrects counts at build time**. The test imports this tuple; it is never hand-copied.
- **Scope:** every `.py` under `custom_components/universal_room_automation/`, not just `energy*.py`. Writers outside energy get their own row. The audit's package-wide AST walk found 12 matches: the 11 above plus `radar_tuning.async_send_radar_settings` (a literal `async_call("number","set_value")`, now listed as `non_reserve`). Known limits, which no example in the repo shows today: a domain or service passed in a variable, the HA constant `SERVICE_SET_VALUE`, runtime-built strings, and the EVSE overlay's **update-in-place** leg, which rewrites an existing action dict with no new literal. C1 still sees that leg's value at dispatch.
- **Counting rule:** +1 per qualifying `Call` node. A Call qualifies when its positional args are `("number", "set_value", …)` or its keywords are `domain="number", service="set_value"`. +1 per `ast.Constant == "number.set_value"`. Constant args of a Call that already qualified are **not** counted again. A bare `"set_value"` counts only through its qualifying Call. This gives `force_redispatch = 2` (Call `:6817` + const `:6836`).
- The walker attributes each match to its innermost enclosing `FunctionDef/AsyncFunctionDef`. It fails on any match outside the tuple and on any count mismatch. A docstring containing the substring does not match, because equality is exact.
- Count-pinning is what makes allowlisting the huge `determine_mode` safe: a second writer in it changes the count.

---

## Ordering (R2-10)

`_last_inclement_decision` is set by `_cache_inclement` inside `_inclement_decision` (`energy_battery.py:2734`), during `determine_mode`. C1 and C2 run after `determine_mode` returns in the same coroutine, so they normally read the current call's decision. The exception is the timer/CM interleaving limitation in §2 (G-8), which affects row fields only. C3 reads the cache at redispatch time, which is the documented intent.
**Test `test_reserve_row_reads_current_tick_decision`:** tick 1 with partial_hold floor 30 dispatches 30 and the row has `inclement_floor=30`. Tick 2 with the decision at allow_discharge, desire 20, current 30 dispatches 20 and the row has `inclement_floor=None, floor_ok=None`. **Mutant:** `_record_reserve_dispatch` reads a decision frozen on first call. Tick 2 then has `inclement_floor=30` and the test goes RED.

---

## Config-extreme / edge cases

1. Deadband (current 20, desire 21): no action and **no row** (INV-G2 falsifier 2).
2. EVSE overlay (desire 20, hold 60): row `value=60, desire=20, hold_owner="evse_battery_hold"`.
3. DP fold raises the overlay value: row `hold_owner="dp_transition"`, value is the folded max.
4. Blind de-escalation: row via C1 with `reason` starting "Blind de-escalation", `value=reserve_soc`, `inclement_floor` per the cached decision. `desire` is the **previous tick's** value, because blind bypasses `_result`. `floor_ok` may be False under partial_hold. That is correct and expected: it is the known unfloored site that `EC-INCLEMENT-HARDENING-1` D-blind will fix, and the row makes it visible. **This case can only be proven in-suite until the June peak season**: blind de-escalation needs peak-or-into-peak, and shoulder/winter TOU has no `peak`. The audit confirmed it is unreachable live now.
5. Floor > target (`reserve_floor=80, peak_buffer_target=40`, partial_hold): wraps raise to 80; row `value=80, floor_ok=True`.
6. `reserve_soc=20, reserve_floor=10`, partial_hold: `inclement_floor=20` (R1-02 expression).
7. No decision yet (boot): `inclement_floor=None`.
8. DB missing: the row is skipped with a debug log; the dispatch proceeds.
9. Same value re-sent by the overlay every tick while hardware already holds it: the first row is written, the rest are gated.
9c. Off-peak hold writing below `reserve_soc` (e.g. "Off-peak hold — SOC 9.0% <= target 10%" → dispatched 8, audit 10-15 04:27) is **legitimate**: `hold_reserve = int(SOC)` with no partial_hold. The row shows `value=8, inclement_floor=None, floor_ok=None`. It is not a defect.
9d. Cloud lag: a re-send of the same value while the cloud still reads the old one (`pre_state` ≠ value) gives two rows. This is correct (audit: 17:00:05 and 17:01:07, cloud reflected at 17:01:33).
9b. Drift correction (row at 30; cloud reverts to 20; URA re-sends 30 with the same owner): `pre_state=20 != 30`, so a **row is written**.
10. Redispatch of an unchanged desire: always a row.

---

## Mutation plan (Review C, real source edits, `PYTHONDONTWRITEBYTECODE=1`)

| Mutation | Must go RED |
|---|---|
| Delete C1 call | `test_reserve_row_on_timer_dispatch` |
| Delete C2 call | `test_reserve_row_on_evaluate_path` |
| Delete C3 success call | `test_reserve_row_on_force_redispatch` |
| Move C3 back inside the service-call `try`, with `_coord` absent (standard test wiring) | `test_force_redispatch_row_call_cannot_fake_failure` (asserts the ledger is stamped and `record_dispatch_failed` is NOT called) |
| Compare raw `pre_state` string to int (drop `_get_state_float`/round) | `test_reserve_row_gate_suppresses_identical_dispatch` (steady overlay at `"60.0"` must gate) |
| C1 drops the truthy-`reserve_eid` guard | `test_reserve_row_requires_configured_reserve_entity` |
| Status re-typed as a local string or enum instead of the imported `WriteStatus` | `test_reserve_row_status_uses_hvac_writestatus` (identity check `status_enum is hvac_strategy.WriteStatus`) |
| C1 passes the pre-overlay desire instead of `data["value"]` | `test_reserve_row_records_overlay_value_not_desire` (Repro-2) |
| Remove the change gate | `test_reserve_row_gate_suppresses_identical_dispatch` |
| Apply the gate to redispatch | `test_reserve_row_redispatch_bypasses_gate` |
| Drop `pre_state` from the gate rule (gate on key only) | `test_reserve_row_records_drift_correction` |
| Inject keyword-form `async_call(domain="number", service="set_value")` into a non-allowlisted function | lint |
| `inclement_floor` uses `dec.reserve_floor` without the `max(reserve_soc, …)` | `test_reserve_row_inclement_floor_expression` |
| Freeze the decision read | `test_reserve_row_reads_current_tick_decision` |
| Inject a **dict-shape** `{"service": "number.set_value", …}` into a non-allowlisted energy function | `test_reserve_write_chokepoint_lint::test_no_unlisted_writers` |
| Inject a second dict-shape writer inside `determine_mode` | lint count mismatch |
| Inject `async_call("number","set_value",…)` into a non-allowlisted function | lint |

---

## Acceptance criteria

- **A/B (INV-G3), capture procedure:** **Commit 1** (before any governor code) adds `test_reserve_governor_ab.py`. It drives the timer dispatch, `_evaluate_battery` and `force_redispatch` through fakes, parametrized over allow_discharge, partial_hold, full_hold, EVSE overlay, DP fold and blind de-escalation, **under a frozen `dt_util.utcnow`/`dt_util.now`** (timestamp fields are kept, not dropped), and writes the observed dispatched-action lists plus `_last_reserve_level(_at)`, `_last_reserve_level_desired` and `verifier.schedule` args to `quality/tests/fixtures/reserve_governor_golden.json`, which is committed. **Commit 2+** adds the governor; the same test asserts equality against the committed golden and also runs with `_record_reserve_dispatch` patched to a no-op. The reviewer verifies that the fixture's commit predates the governor commit (`git log --follow`).
- **Lint:** `test_reserve_write_chokepoint_lint.py` is green on HEAD. Every mutation row marked "lint" goes RED.
- **Rows:** the tests named in the mutation table pass. Repro-1 produces no row; Repro-2 produces the row values above.
- **Existing floor coverage:** `test_battery_inclement_arbitrage_floor.py` passes unchanged. It is a regression guard, not governor coverage.
- **Suite:** the full-suite name-diff vs `pre-review-v<version>` shows zero new failures.
- **Live (one-shot, at validation, no soak; G-2):** the write target is the **cloud write-leg** entity `number.iq_battery_hacs_battery_reserve` (`_get_entity("reserve_soc_number", role="write")`, cloud-first `energy_const.py:518`). The local Envoy entity `number.enpower_482348004678_reserve_battery_level` is a witness only, often `unavailable`, and never a URA write target. After restart, once at least one reserve write has occurred, run
  `SELECT timestamp, entity_id, json_extract(details_json,'$.status'), json_extract(details_json,'$.path'), json_extract(details_json,'$.value'), json_extract(details_json,'$.pre_state'), json_extract(details_json,'$.hold_owner'), json_extract(details_json,'$.floor_ok') FROM ura_activity_log WHERE action='reserve_write' ORDER BY timestamp DESC LIMIT 10;`
  **PASS** when (a) the newest row's `entity_id` is `number.iq_battery_hacs_battery_reserve`; (b) its `value` equals `command_trail.reserve_soc.commanded.value` on `sensor.ura_energy_coordinator_battery_strategy`; and (c) the cloud entity reads that `value` **within about 90 s** of the row timestamp. Ground truth: the 10-15 17:00:05 send was reflected at 17:01:33. A second row at the same value with `pre_state` still at the old value inside that lag window is **correct**, not a dup. Status values are only `applied` / `failed` / `deferred`.
  **floor_ok:** `SELECT COUNT(*) FROM ura_activity_log WHERE action='reserve_write' AND json_extract(details_json,'$.floor_ok')=0 AND json_extract(details_json,'$.reason') NOT LIKE 'Blind de-escalation%';` should return 0. **Any hit is investigated against the `EC-INCLEMENT-HARDENING-1` site table before it is called a governor defect** (G-9; the governor only observes the floor). No partial_hold occurred in the audit's 7-day window, so this is expected to be vacuous at validation, and the in-suite tests are the proof.
  **Discriminator:** a desire-only recorder (the Rev-2 bug) shows rows with no matching cloud change; an overlay-blind recorder shows `value != commanded` during EVSE charging.
- **Live log check (one-shot):** grep the journald window since restart for `reserve_write` debug failures and tracebacks mentioning `_record_reserve_dispatch`. Zero expected.

---

## Non-goals

1. No floor registry, no fold in `_result`, no edit to the 8 wraps, the inline off-peak clamps (`:6224`, `:6262`) or the narration.
2. No inclement logic change. The blind write stays unfloored until `EC-INCLEMENT-HARDENING-1`, and the row makes it visible.
3. No edit to the EVSE overlay internals, DP placement, write-verify contract or `_resolve_hold_owner`.
4. No sensor attribute, no RestoreEntity, no schema/table, no new signal, no config field.
5. No `WriteResult` / dispatch-return-contract change (only the `WriteStatus` names are reused for row status), no leases, no presence/perimeter pattern.

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

- **A (local correctness):** row payload, gate rule (numeric `pre_state`), the `inclement_floor` expression, `WriteStatus` selection.
- **B (integration/lifecycle):** C1/C2/C3 placement; no change to tap ledger stamping or CFG handling; fire-and-forget safety; evaluate-path target resolution.
- **C (test authority):** the mutation table above, with real edits.
- **D (adversarial completeness):** independently enumerate every reserve write reachable in HA (including through `CoordinatorManager`) and every `number.set_value` in the package. Confirm each has a row path and an allowlist entry, and try to produce a reserve write with no row.

The orchestrator re-runs the lint and one mutation before ship. **Operator checkpoint before deploy.**

## Sequencing

Ship this first. `EC-INCLEMENT-HARDENING-1` D-blind then routes blind through `_result`: it changes the `determine_mode` count in `RESERVE_SET_VALUE_WRITERS`, and its rows show `floor_ok` flipping to True.

## Files touched

- `domain_coordinators/energy.py`: `_record_reserve_dispatch`, `_last_reserve_row_key`, calls C1 and C2, the `pre_state` read in the timer dispatch loop, and a keyword-only `pre_state=None` on `_tap_write_verifier`. About +85 LoC.
- `domain_coordinators/energy_battery.py`: C3, two guarded calls in `force_redispatch`, both outside the service-call `try` (G-1).
- `domain_coordinators/energy_const.py`: `RESERVE_SET_VALUE_WRITERS`, `RESERVE_WRITE_LOG_IMPORTANCE`.
- `quality/tests/test_reserve_write_chokepoint_lint.py`, `test_reserve_write_rows.py`, `test_reserve_governor_ab.py`, `fixtures/reserve_governor_golden.json`: NEW.
- `docs/readmes/README_v<version>.md`: written before deploy; post-restart validation written back.

Not touched: `sensor.py`, `energy_write_verify.py`, `energy_drain_precedence.py`, `database.py`, config/options flows.

---

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018uEjYPUcWq73wfBS3t1NEa
