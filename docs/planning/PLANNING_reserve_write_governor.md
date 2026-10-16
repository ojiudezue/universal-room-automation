# PLANNING — Reserve Write Governor (Rev 2 — single floor, durable rows, chokepoint lint)

**Card:** `EC-RESERVE-WRITE-GOVERNOR-1`
**Tier:** 3 (shared primitive — the single battery reserve write path consumed across arbitrage, attain, drain, peak-buffer, inclement, EVSE overlay, DP ledger, WAIT narration, and `force_redispatch`; cost + safety ripple).
**Status:** `pre_planning` → BUILD-READY after Rev-2 plan review.
**Branch target:** `develop`.
**Scope posture:** EXTEND existing machinery (`_result`, `_floor_reserve`, `_apply_evse_battery_hold`, `wv_commanded_ledger`, `ura_activity_log` via `database.log_activity`) into ONE *governed slice* with (a) ONE registered floor, (b) a durable per-write ledger row, (c) a structural AST chokepoint lint. **Do not invent floors. Do not duplicate ledgers. Do not add RestoreEntity surfaces.**

**Operator posture (2026-10-15):** *"25 places is mad. Force them through a governed slice with history and restart resilience. This is not about alerts at all."* *"Tough build → tight plan. Don't scope creep."*

---

## Rev-2 changelog (R1 finding → change)

| ID | Sev | Change in Rev 2 |
|---|---|---|
| R1-01 | CRIT | Registry collapses to ONE floor: `inclement_partial_hold`. The old entries `inclement_full_hold / arbitrage_wait / attain_target / drain_park / evse_overlay` are documented as **branch proposals**, not floors; they are NOT registered. The 5-floor registry was scope creep + behaviour change. |
| R1-02 | CRIT | The one floor's value is **`max(self.reserve_soc, decision.reserve_floor)` when `decision.hold_depth == "partial_hold"`**, mirroring every current `_floor_reserve` call site + narration `:6687-6689` exactly. Named explicitly in the plan. |
| R1-03 | CRIT | RAM ring + RestoreEntity blob design **dropped.** History is one `ura_activity_log` row per governed emission via `database.log_activity(action="reserve_write")`, modelled on `_schedule_climate_write_row` (`hvac_setpoint.py:213-310`). Restart resilience is handled by the **existing** `wv_commanded_ledger` restore (`energy.py:1940-1968, 2290-2330`); governor adds **nothing** to restore. Entity id corrected: `sensor.ura_battery_strategy`. |
| R1-04 | HIGH | `BatteryStrategy.force_redispatch` (`energy_battery.py:6713-6852`) added to site table + INV-G corollary 3 allowlist. It re-dispatches the already-governed `_last_reserve_level_desired`, so its value is correct by construction; it writes a `reserve_write` row with `verb="redispatch"`. |
| R1-05 | HIGH | Site table rebuilt from **wrap lines** (not emit lines). 8 `_floor_reserve` wraps: `:3926, :3949, :3991, :4715, :4769, :5004, :5952, :6098`. Narration caller `:6687` added as 9th consumer (display-only, no `_result`). |
| R1-06 | HIGH | **The `_floor_reserve` wraps are KEPT.** The `" (partial_hold floor)"` reason suffix stays where it is today (`:4718-4719, :3929-3932`, …). Governor does NOT retire the wraps. Governor's role is the DB row + lint + a shared single-floor evaluator the wraps + narration both call (byte-identical to today's arithmetic). |
| R1-07 | HIGH | REUSE HVAC's AST completeness lint pattern (`test_hvac_climate_write_funnel_completeness.py`, HVAC doc §4.3). New `test_reserve_write_chokepoint_lint.py` AST-scans `energy*.py` for `number.set_value` targeting the reserve role with an explicit allowlist. This is the structural "no 7th site" guarantee that INV-G needs. |
| R1-08 | HIGH | No large recorder attr. Sensor exposes `last_reserve_write` (one row only) plus a 20-row rolling attr guarded by `_unrecorded_attributes = frozenset({"reserve_write_history"})` in `sensor.py`. Row rate: per `_result` call that writes reserve; change-gated (skip when `(proposed, final, winning_floor)` matches the previous row) + per-tick dedup for the twice-per-tick `determine_mode` reality (`energy.py:6390` + `_evaluate_battery :7155`). |
| R1-09 | HIGH | Existing tests `test_battery_inclement_arbitrage_floor.py:595, 720, 758, 785` monkeypatch `_floor_reserve`. Since wraps are KEPT (R1-06), these tests remain anchored and bite. New governor tests ADD to the suite; they do not retire the existing ones. |
| R1-10 | MED | DP floor stays inside `_apply_evse_battery_hold` (`energy.py:5401, :5497`). **Not registered.** Registry has only `inclement_partial_hold`. Fixed anchors. |
| R1-11 | MED | Reconciled with `command_trail` / `_resolve_hold_owner` (`energy_write_verify.py:2477-2530, :2525-2529`). `winning_floor` on the row uses the same vocabulary as `_resolve_hold_owner` ("inclement_partial_hold" when the inclement arm wins; "none" otherwise). Rev 2 REUSES `_resolve_hold_owner` as the authoritative labeller (import it; do not duplicate). |
| R1-12 | HIGH | Prior-art section REWRITTEN with correct REUSE/BUILD verdicts (below). Transfers: AST lint, durable per-write `ura_activity_log` row, `_resolve_hold_owner` as labeller. Does NOT transfer: `ExcursionToken`/lease ownership (floor has no owner/duration; recomputed every tick from cached inclement decision), `PresetManager.borrow_live`, presence fusion, `perimeter_alert.py` (fusion/alerting ≠ write governance). Typed `WriteResult` carded as a follow-up for the dispatch tap, NOT this cycle. |
| R1-13 | MED | Ordering invariant stated: `_cache_inclement` runs inside `_inclement_decision` which is reached before every emission in `determine_mode` (`:2700-2740`). The one path that returns BEFORE classify is the Envoy-blind early-return (`:5588`), and that path emits one direct reserve write at `:5664-5673` which is explicitly on the lint allowlist (unchanged this cycle). Test `test_governor_never_folds_stale_prior_tick_decision` asserts the invariant. |
| R1-14 | LOW | Site anchors standardised to `<function_name>:<wrap_line>` throughout. |
| R1-15 | LOW | 48h soak criterion dropped. Replaced with a **one-shot log query at validation** (R1-15 §Live). |

---

## Falsifiable invariant (INV-G, Rev 2)

> **INV-G (governed emission):** every URA-originated service call that writes the battery reserve role (`number.set_value` on the configured reserve entity) originates from exactly one of the **named allowlisted sites**, and emits exactly one `ura_activity_log` row with `action="reserve_write"` recording `(proposed, final, winning_floor, reason, site)` (modulo change-gate + per-tick dedup).
>
> **Floor fold (sub-invariant):** when `self._last_inclement_decision.hold_depth == "partial_hold"`, every emission's `final >= max(self.reserve_soc, decision.reserve_floor)`. When `hold_depth != "partial_hold"` **or** `_last_inclement_decision is None`, `final == proposed` (byte-identical to today).

### Allowlisted writers (INV-G corollary 3)
1. `_result` reserve action append (`energy_battery.py:_result`, inside the `if reserve_level is not None:` block near `:6353`).
2. EVSE overlay append (`energy.py:_apply_evse_battery_hold`, append path `:5516`) and the in-place update leg of the same overlay.
3. Blind de-escalation reserve write at `energy_battery.py:5664-5673` (unchanged this cycle; routed through `_result` only by a later `EC-INCLEMENT-HARDENING-1` D-blind cycle).
4. `BatteryStrategy.force_redispatch` direct `number.set_value` call at `energy_battery.py:6820-6825` (re-sends the already-governed `_last_reserve_level_desired`; records a row with `verb="redispatch"`).

Pool `number.set_value` sites (`energy.py:8710, 8734`, `energy_pool.py:411, 429`) target **pool speed**, NOT the reserve role — the lint discriminates by write-target entity role.

### Falsification observations
1. A reserve write originates from a site NOT in the allowlist → INV-G broken (lint fails).
2. Any emission under `partial_hold` with `final < max(reserve_soc, reserve_floor)` → fold broken.
3. Any emission under NOT-partial_hold where `final != proposed` → byte-identical broken.
4. v5.17.5 blind semantics changed (new commands fire while fully blind absent a floor transition) → broken.

---

## Design — the governor is `_result` + a shared evaluator + a durable row + an AST lint

### 1. Shared single-floor evaluator (REUSE `_floor_reserve`)

`BatteryStrategy._floor_reserve(existing, effective_reserve, hold_depth)` (`:3855`) remains the one evaluator. **No signature change, no behaviour change.** All current 8 wrap sites + the narration keep calling it. The governor exposes a thin accessor so `_result` and the narration read the SAME value:

```python
def _active_inclement_floor(self) -> tuple[str | None, int | None]:
    """Return (name, value) of the active registered floor, else (None, None)."""
    dec = self._last_inclement_decision
    if dec is None or dec.hold_depth != "partial_hold":
        return (None, None)
    return ("inclement_partial_hold",
            max(int(self.reserve_soc), int(dec.reserve_floor)))
```

This is the *only* new helper on the hot path. Byte-identical when inactive. The 8 wrap sites + narration continue to call `_floor_reserve(existing, effective_reserve, hold_depth)` directly — the governor does not touch them — so the `" (partial_hold floor)"` reason suffix stays exactly where it is today (R1-06).

### 2. `_result` additions (surgical: one DB-row scheduler)

Inside `_result`, immediately AFTER the reserve-stamp block (`:6520-6560`), schedule one `ura_activity_log` row. **Byte-identical to today's return value.** No fold inside `_result` — the proposals handed to `_result` are already-floored (the wraps did the fold). `_result` only *records* what passed through:

```python
# Reserve Write Governor — durable per-write row (R1-07/R1-08/R1-12).
# Byte-identical to today's return. Writes zero actions. Fire-and-forget.
if reserve_level is not None:
    _schedule_reserve_write_row(
        hass=self.hass,
        verb="emit",
        site=reason,                      # e.g. "arbitrage WAIT ...", "off_peak hold ..."
        proposed=reserve_level,           # already-floored by caller (today's behaviour)
        active_floor=self._active_inclement_floor(),   # (name, value) or (None, None)
        final=_new_res,                   # the stamped desire from the block above
        reason=reason,
        change_gate=self._last_reserve_write_row,       # (proposed, final, winning_floor)
        tick_id=self._tick_id,            # per-determine_mode uuid (NEW, cheap)
    )
    # update last-row memo + sensor attr memo (bounded N=20)
```

- `_schedule_reserve_write_row` lives next to `_result` in `energy_battery.py` (NOT a new module), direct-calls `database.log_activity(action="reserve_write", ...)` the same way `_schedule_climate_write_row` does. Never raises. Never awaited (write queue absorbs it).
- **Change gate:** skip the row when `(proposed, final, winning_floor) == self._last_reserve_write_row` (dedup identical consecutive emissions).
- **Per-tick dedup:** `tick_id` is set once at the top of `determine_mode` to a uuid; rows carry it; second emission in the same tick with same payload is suppressed (addresses the twice-per-tick reality at `energy.py:6390` + `_evaluate_battery :7155`).
- **`winning_floor` label** = `self._active_inclement_floor()[0]` which is `"inclement_partial_hold"` or `None`. Agrees with `_resolve_hold_owner` (`energy_write_verify.py:2525-2529`) vocabulary (R1-11). **Import** `_resolve_hold_owner`'s label constants rather than redefining strings — single source of truth.
- `force_redispatch` adds a sibling scheduler call with `verb="redispatch"` (`energy_battery.py:6820-6825` region).

### 3. Durable row schema (`ura_activity_log`)

Row shape — JSON payload inside the existing `details_json` column (no schema migration, no new table — avoids Tier 2-DB schema trigger per R1-12):

```json
{
  "verb": "emit" | "redispatch",
  "site": "<_result reason prefix>",
  "proposed": <int>,
  "active_floor": {"name": "inclement_partial_hold", "value": <int>} | null,
  "winning_floor": "inclement_partial_hold" | null,
  "final": <int>,
  "reason": "<_result reason, verbatim>",
  "tick_id": "<uuid>"
}
```

Columns outside details_json: `coordinator="energy"`, `action="reserve_write"`, `entity_id=<configured reserve number entity>`, `importance=` existing `CLIMATE_WRITE_LOG_IMPORTANCE` sibling (new `RESERVE_WRITE_LOG_IMPORTANCE = CLIMATE_WRITE_LOG_IMPORTANCE`, rung-1 const).

### 4. Sensor attribute surface (`sensor.ura_battery_strategy`)

- `last_reserve_write`: dict of the last row (small, under 1 KB).
- `reserve_write_history`: list of last 20 rows (ONLY exposed for operator diagnostics).
- **Both are recorder-excluded** via `_unrecorded_attributes = frozenset({"reserve_write_history", "last_reserve_write"})` on `EnergyBatteryStrategySensor` (`sensor.py:9052`). This touches `sensor.py` — the Rev-1 "not touched" list is corrected.
- The HA recorder `MAX_STATE_ATTRS_BYTES = 16384` is now a non-issue (both attrs are unrecorded).

### 5. Restart resilience (REUSE `wv_commanded_ledger`, add NOTHING)

- `_last_reserve_level_desired` / `_last_reserve_level` continue to restore from the DB key `wv_commanded_ledger` via `db.restore_energy_state_with_age` (`energy.py:1940-1968`), 15-min save cadence (`:2290-2330`). **Unchanged.**
- History ledger is **durable in `ura_activity_log` by construction** — rows are written at emit time, read via DB query. Restart cost = zero reload work on the governor side.
- First post-boot emission writes a fresh row that includes the (restored) `_last_inclement_decision` floor if active — the restore of that decision is v5.5.0 behaviour, unchanged.

### 6. Structural chokepoint lint (NEW test, modelled on HVAC §4.3)

`quality/tests/test_reserve_write_chokepoint_lint.py` — AST walker over every `.py` under `custom_components/universal_room_automation/`:

- Flags any `hass.services.async_call("number", "set_value", ...)` and any `.async_call("number", "set_value"...)` where the target entity-id (static str OR a traceable attribute read) resolves to the **reserve role**. Role detection: match the write target to `_get_entity("reserve_soc_number", DEFAULT_RESERVE_SOC_ENTITY, role="write")` (one call-site symbol + one default const).
- Pool-speed writes (`energy.py:8710, 8734`, `energy_pool.py:411, 429`) are distinguished by their target symbol (`"storage_mode"` / pool speed role); the lint discriminates by role, not domain.
- **Allowlist** (production-sourced constant, imported — not hand-copied, per HVAC lint pattern):
  - `energy_battery.py:_result` reserve action append (within `_result` body)
  - `energy.py:_apply_evse_battery_hold` append path + in-place update leg
  - `energy_battery.py:5664-5673` blind de-escalation (ships with a `# RESERVE_WRITE_ALLOWED: blind_deescalation` sentinel comment)
  - `energy_battery.py:6820-6825` `force_redispatch` (sentinel `# RESERVE_WRITE_ALLOWED: force_redispatch`)
- Second lint assertion: every emission branch in `energy_battery.py` that proposes a reserve floor must either (a) call `_floor_reserve(...)` directly (the 8 wraps + narration) **or** (b) be inside `_result` after the single-floor evaluator ran. **Inline `max(..., effective_reserve)` outside `_floor_reserve` is allowed** (the branch-local `max(int(soc)-5, effective_reserve)` at `:5890, :5994` is defensive, not a floor — flagged in the allowlist by comment sentinel).

**This is the structural "no 7th site" guarantee**: adding a new reserve writer requires either an allowlist entry (reviewed) or the lint fails. INV-G now has teeth beyond "trust the review."

---

## Reserve emission site table (Rev 2, symbol + wrap-line anchored)

| # | Function / branch | Wrap line | Emit line | What it computes today | Rev-2 change |
|---|---|---|---|---|---|
| 1 | `_get_attainability_decision` (attain CHARGE) | `:3926` | `:3939` | `_floor_reserve(peak_buffer_target, eff, depth)` | **unchanged** (wrap kept; reason suffix kept) |
| 2 | `_get_attainability_hold_decision` (attain HOLD) | `:3949` | `:3962` | same shape | unchanged |
| 3 | `_run_attain_branch` `wait_base` leg | `:3991` | `:4004` | `_floor_reserve(wait_base, eff, depth)` | unchanged |
| 4 | peak-buffer / drain release helper | `:4715` | `:4725` | `_floor_reserve(…)` | unchanged |
| 5 | drain-park helper | `:4769` | `:4779` | `_floor_reserve(…)` | unchanged |
| 6 | off-peak hold ladder | `:5004` | `:5018` | `_floor_reserve(…)` | unchanged |
| 7 | mid-peak summer hold | `:5952` | `:5959` | `_floor_reserve(hold_reserve, eff, depth)` | unchanged |
| 8 | `_get_arbitrage_decision` emit | `:6098` | `:6114` | `_floor_reserve(phase_proposal, eff, depth)` | unchanged |
| 9 | `_next_action_estimate` WAIT narration | — | `:6687` | `_floor_reserve(_wait_base, max(reserve_soc, reserve_floor), hold_depth)` | **unchanged** — same evaluator as the emitter (operator invariant kept) |
| F7-F10 | inclement full_hold emits | — | `:5820, :5841, :5857, :5867` | `decision.reserve_floor` directly | unchanged (full_hold proposal is its own floor by construction) |
| F11-F14 | inclement/mid-peak branch literals | — | `:5883, :5890, :5959, :5979, :5994` | branch-local `effective_reserve` / `max(soc-5, eff)` | unchanged |
| D17-D18 | off-peak drain / hold | — | `:6251, :6271` | already max-folded at `:6263-6264` / `:~6223` | unchanged |
| B21 | blind de-escalation | — | `:5664-5673` | `int(self.reserve_soc)` unfloored | **unchanged this cycle** (lint allowlist entry; EC-INCLEMENT-HARDENING-1 routes it through `_result` next rev) |
| E22-E23 | EVSE overlay append + in-place update | — | `energy.py:5401, :5497, :5516` | DP floor fold + `max()` of hold | unchanged (lint allowlist) |
| R24 | `force_redispatch` direct call | — | `energy_battery.py:6820-6825` | re-sends `_last_reserve_level_desired` | records `reserve_write` row with `verb="redispatch"` |

**Zero line edits to the emission arithmetic.** The only code additions are: `_active_inclement_floor` helper, `_schedule_reserve_write_row` scheduler + call in `_result`, sibling call in `force_redispatch`, `_tick_id` field, `_last_reserve_write_row` memo field, two `_unrecorded_attributes` entries in `sensor.py`, the lint test file.

---

## Prior art — REUSE / BUILD per piece (Rev 2, corrected per R1-12)

| Piece | Location | Verdict |
|---|---|---|
| AST chokepoint lint | `quality/tests/test_hvac_climate_write_funnel_completeness.py:1-60, :251`; HVAC doc §4.3 | **REUSE pattern.** New `test_reserve_write_chokepoint_lint.py` adapts the walker to the reserve role with a production-sourced allowlist. Strongest fit for INV-G corollary 3. |
| Durable per-write row | `hvac_setpoint.py:_schedule_climate_write_row :213-310` | **REUSE pattern.** New `_schedule_reserve_write_row` is a near-byte copy adapted to `action="reserve_write"`. Fire-and-forget, DB `_write_queue`-batched, defensive. |
| Reserve single-floor evaluator | `energy_battery.py:_floor_reserve :3855-3870` | **REUSE as-is.** Governor's `_active_inclement_floor` is a thin accessor on top; wraps + narration keep calling `_floor_reserve` directly. |
| Chokepoint for reserve writes | `energy_battery.py:_result :6278` | **REUSE + minimal extend.** Already hosts CFG cloud-withhold chokepoint + `_last_reserve_level_desired` stamp. One scheduler call added. |
| EVSE post-overlay | `energy.py:_apply_evse_battery_hold :5239, :5401, :5497, :5516` | **REUSE unchanged.** Allowlist entry only. |
| DP floor | `energy_drain_precedence.py` → folded in overlay at `energy.py:5401, :5497` | **REUSE unchanged.** NOT registered in the governor registry (R1-10). |
| Commanded ledger / restart | `energy.py:1940-1968, 2290-2330` (DB `wv_commanded_ledger` key) | **REUSE unchanged.** Governor adds nothing. |
| Row-labelling vocabulary | `energy_write_verify.py:_resolve_hold_owner :2525-2529, command_trail :2477-2530` | **REUSE.** `winning_floor` label imports the same constant. No duplicate surface. |
| Typed `WriteResult` | `hvac_strategy.py:236-256` | **CARD AS FOLLOW-UP, NOT THIS CYCLE.** Fits the dispatch tap (`energy.py` `_tap_write_verifier`) + `force_redispatch`, not `_result`. Separate card `EC-RESERVE-WRITE-RESULT-TYPE-1`. |
| `ExcursionToken` / `borrow_live` / `PresetManager` | `hvac_excursion.py:131, :307, :597, :635`; `hvac_preset.py:73, :234, :253`; `hvac_override.py:4266-4315` | **DOES NOT TRANSFER.** The one reserve floor (`inclement_partial_hold`) has no owner, no duration, no begin/return lifecycle — it is recomputed every tick from the cached inclement decision. A lease would add stale-row reap + NM machinery with nothing to protect; restore of the floor is already covered by inclement decision restore. |
| Presence fusion / `perimeter_alert.py` | — | **DOES NOT TRANSFER.** Fusion + alerting are not write governance. No shape fit. |

---

## Ordering invariant (R1-13)

`_last_inclement_decision` is set by `_cache_inclement` inside `_inclement_decision` (`energy_battery.py:2734`). Every `determine_mode` emission that reaches `_result` has first called `_inclement_decision` (precedence chain `:2740-2766`). The one path that returns BEFORE classify is the Envoy-blind early-return (`:5588`), and its emit (`:5664-5673`) is the lint-allowlisted direct write that this cycle does NOT touch. The `_tick_id` field is set at the top of `determine_mode` BEFORE `_inclement_decision`; rows carrying a `tick_id` are guaranteed to see the fresh (current-tick) decision.

**Test:** `test_governor_never_folds_stale_prior_tick_decision` — monkeypatch `_inclement_decision` to a sentinel that raises if called out-of-order; drive two consecutive `determine_mode` ticks with different `hold_depth` values; assert the second emission's row carries the second tick's floor, not the first.

---

## Config-extreme + edge cases

1. **No floor active (not partial_hold OR `_last_inclement_decision is None`):** `_active_inclement_floor()` returns `(None, None)`; emission `final == proposed`; row written with `active_floor=null, winning_floor=null`.
2. **Partial_hold active, proposed ≥ floor:** `final == proposed`; `active_floor=<name,value>`, `winning_floor=null` (floor present but did not win).
3. **Partial_hold active, proposed < floor:** cannot happen for the 8 wrap sites (wrap already folded); CAN happen for site F11 (`:5890 max(soc-5, eff)` is already max-folded), site F12 (`:5979 effective_reserve`) etc. For completeness, when `proposed < floor` is observed, `winning_floor="inclement_partial_hold"` is recorded and INV-G sub-invariant triggers investigation (lint should have caught it, test confirms).
4. **`reserve_level=None` in `_result`:** scheduler short-circuits; no row.
5. **Scheduler raises (DB missing):** swallowed per `_schedule_climate_write_row` pattern; row dropped; `_result` returns normally.
6. **Twice-per-tick `determine_mode`:** second row with same `tick_id` + same payload is dedup'd by the change gate.
7. **`force_redispatch` loop (hourly):** row every re-dispatch unless change-gate matches → steady state: zero rows per hour on an unchanging desire; one row on each legitimate change.
8. **Boot with no prior row memo:** `_last_reserve_write_row = None`; first emission is NOT dedup'd (correct — operator wants the first boot emission recorded).
9. **Recorder bytes:** both new attrs recorder-excluded; `MAX_STATE_ATTRS_BYTES` not approached.

---

## Per-site mutation plan (Review C)

Mutations target the governor + lint, not the wraps (wraps are unchanged and already covered by existing `test_battery_inclement_arbitrage_floor.py` monkeypatch tests at `:595, 720, 758, 785`).

| Mutation | Must-fail test |
|---|---|
| Comment out `_schedule_reserve_write_row` call in `_result` | `test_governor_emits_one_row_per_result_call` |
| Comment out the change-gate | `test_governor_change_gated_steady_state_no_rows` |
| Comment out per-tick dedup | `test_governor_tick_dedup_second_emit_suppressed` |
| Replace `_active_inclement_floor` return with `(None, None)` under partial_hold | `test_governor_row_labels_inclement_partial_hold_when_active` |
| Add a new raw `number.set_value` call to `energy_battery.py` outside allowlist | `test_reserve_write_chokepoint_lint::test_no_unallowlisted_writers` |
| Remove the `# RESERVE_WRITE_ALLOWED` sentinel from `:5664` | lint fails on blind de-escalation |
| Replace `_resolve_hold_owner`-sourced label with a hand string | `test_winning_floor_label_matches_hold_owner_vocabulary` |

**`PYTHONDONTWRITEBYTECODE=1`** on every mutation drill (pyc staleness guard).

---

## Acceptance criteria

- **Verify (lint):** `test_reserve_write_chokepoint_lint.py` passes on `develop @ HEAD`; any new `number.set_value` on the reserve role outside the allowlist fails.
- **Verify (byte-identical):** `test_governor_byte_identical_result_dict_under_allow_discharge` — snapshot of `_result` return across every emission branch under `allow_discharge` + arbitrage closed + no attain is unchanged vs a `pre-governor` fixture captured from `develop @ HEAD`.
- **Verify (floor fold):** `test_governor_partial_hold_floor_folds_to_max_reserve_soc_or_reserve_floor` — with `reserve_soc=20`, `reserve_floor=10`, proposed 15 → `final=20` (today's behaviour via `max(reserve_soc, reserve_floor)`); R1-02 anchor.
- **Verify (row):** every `_result` reserve emission writes exactly one `reserve_write` row to `ura_activity_log` (modulo change-gate + per-tick dedup); SQL query returns the row with the expected shape.
- **Verify (change gate):** steady partial_hold ticks produce zero new rows after the first.
- **Verify (force_redispatch):** `force_redispatch` writes a row with `verb="redispatch"`.
- **Verify (sensor attrs recorder-excluded):** `EnergyBatteryStrategySensor._unrecorded_attributes` contains `reserve_write_history` and `last_reserve_write`; a recorder-attr-bytes probe confirms the sensor's recorded-attr JSON stays well under `MAX_STATE_ATTRS_BYTES`.
- **Verify (CFG + stamp preserved):** existing `test_cfg_withhold_*` and write-verify stamp tests pass unchanged.
- **Verify (ordering):** `test_governor_never_folds_stale_prior_tick_decision`.
- **Verify (label vocabulary):** `winning_floor` string equals the constant that `_resolve_hold_owner` returns for the inclement-active case.
- **Live (one-shot, R1-15):** after restart, within 60 min, run ONE SQL query against `ura_activity_log` filtered to `action="reserve_write"` + the last hour; assert ≥1 row exists when any emission has occurred, OR `last_reserve_write` sensor attr is populated. **No 48h soak.** The one-shot query is the acceptance signal; residual anomalies become code trip-wires in a follow-up card, not calendar reminders.

---

## Non-goals (hold the line, Rev 2)

1. No new floor sources. Only `inclement_partial_hold` registered.
2. No change to inclement decision logic — this cycle is NOT `EC-INCLEMENT-HARDENING-1`.
3. No change to `_apply_evse_battery_hold` or DP floor placement.
4. No change to the write-verify freshness contract or stamp timing.
5. No change to v5.17.5 blind-tick semantics; blind write at `:5664-5673` stays as-is + allowlisted.
6. No new RestoreEntity. No new DB schema. No new table.
7. No `_floor_reserve` retirement. The 8 wraps + narration call it unchanged (R1-06).
8. No typed `WriteResult` in this cycle — carded as `EC-RESERVE-WRITE-RESULT-TYPE-1` follow-up for the dispatch tap + `force_redispatch`.
9. No leases / `ExcursionToken` for floors (R1-12: nothing to protect; adds reap + NM machinery for zero gain).
10. No presence-fusion or perimeter-manager pattern transfer (R1-12: fusion/alerting ≠ write governance).

---

## Knob ladder

| Name | Rung | Default | Why |
|---|---|---|---|
| `RESERVE_WRITE_HISTORY_MAX` | 1 (const in `energy_const.py`) | 20 | Bounded in-memory list for the recorder-excluded `reserve_write_history` attr; durability lives in DB rows, not RAM. |
| `RESERVE_WRITE_LOG_IMPORTANCE` | 1 (const) | = `CLIMATE_WRITE_LOG_IMPORTANCE` | Mirrors HVAC `climate_write` row importance. |
| `_FLOOR_REGISTRY` concept | — | **removed** vs Rev 1 | Rev 2 registers exactly one floor; no table needed. |

No rung-2 options, no rung-3 Number entities.

---

## Build-risk prediction (what a builder will likely get wrong)

1. **Deleting `_floor_reserve` wraps** — tempting given the Rev-1 design. Rev 2 KEEPS them. Reason suffix + narration parity depend on them.
2. **Awaiting the DB scheduler** — fire-and-forget per `_schedule_climate_write_row`; awaiting back-pressures the dispatch path.
3. **Omitting the `_unrecorded_attributes` set on `sensor.py`** — exposes the attr to the recorder; attr-bytes blow past 16 KB; recorder drops ALL attrs (R1-08).
4. **Change gate on the wrong tuple** — must be `(proposed, final, winning_floor)`; using `final` alone misses legit floor-value changes.
5. **Setting `_tick_id` inside `_evaluate_battery` instead of `determine_mode`** — breaks per-tick dedup for the twice-per-tick case.
6. **Writing a row inside `_apply_evse_battery_hold`** — the overlay runs AFTER `_result` returns; row is written by `_result`'s scheduler; adding one inside the overlay double-counts.
7. **Hand-copying `_resolve_hold_owner` strings** — must import the constant (same single-source-of-truth rule as HVAC's `DYNAMIC_DOMAIN_ALLOWLIST`).
8. **Allowlist drift in the lint** — allowlist must be production-sourced (sentinels or an imported constant), not hand-copied into the test.
9. **Breaking blind semantics** — do not touch `:5664-5673`; this cycle only adds a sentinel comment there for lint discovery.
10. **Adding a RestoreEntity** — Rev 2 adds none. Use the existing `wv_commanded_ledger` DB restore path.

---

## Tier-3 review framings (four, parallel, disjoint)

- **A — local correctness:** scheduler payload shape, change-gate tuple, per-tick dedup, `_active_inclement_floor` arithmetic (`max(reserve_soc, reserve_floor)`), byte-identical no-op.
- **B — integration / state-machine:** `_result` responsibilities preserved (CFG withhold, stamp block, arbitrage_phase sync, cloud mapping); EVSE overlay input/output unchanged; `wv_commanded_ledger` restore unchanged; write-verify `command_trail` / `_resolve_hold_owner` vocabulary agrees.
- **C — test authority (real source mutation):** per-mutation table above; `PYTHONDONTWRITEBYTECODE=1`.
- **D — adversarial completeness / diff-blind:** independently enumerate reserve-write paths across `energy_battery.py`, `energy.py`, `energy_pool.py`, `energy_drain_precedence.py`, `energy_write_verify.py` dispatch tap. Confirm the lint fires on any site added outside the allowlist AND agrees with D's enumeration (lint is D's permanent delegate).

Orchestrator pre-ship: run the lint, independently grep `number.set_value` across `custom_components/universal_room_automation/**/*.py`, confirm every match is in the allowlist. **Operator checkpoint BEFORE deploy.**

---

## Sequencing

1. Ship this governor **first**. It establishes the chokepoint lint + durable row that `EC-INCLEMENT-HARDENING-1` D-blind will register against on its next revision.
2. Then `EC-INCLEMENT-HARDENING-1` D-blind lands as a one-line routing change through `_result` — automatically governed, automatically a row, automatically within the lint's allowlist (the lint catches it IF it bypasses `_result`).
3. `EC-RESERVE-WRITE-RESULT-TYPE-1` (follow-up, carded) hardens the dispatch tap + `force_redispatch` with a typed `WriteResult`, modelled on `hvac_strategy.py:236-256`.

---

## Files touched (Rev 2)

- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` — `_active_inclement_floor` helper, `_schedule_reserve_write_row` scheduler, scheduler call in `_result` + `force_redispatch`, `_tick_id` + `_last_reserve_write_row` fields, `_reserve_write_history` bounded list init, lint sentinels at `:5664` + `:6820`. Est. +90 / -0 LoC. **No change** to the 8 wrap sites, the narration, or any emission arithmetic.
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py` — `RESERVE_WRITE_HISTORY_MAX = 20`, `RESERVE_WRITE_LOG_IMPORTANCE`. +2 LoC.
- `custom_components/universal_room_automation/sensor.py` — `_unrecorded_attributes` set on `EnergyBatteryStrategySensor` (`:9052`); `last_reserve_write` + `reserve_write_history` attr wiring. Est. +15 LoC.
- `quality/tests/test_reserve_write_chokepoint_lint.py` — NEW. ~250 LoC.
- `quality/tests/test_reserve_write_governor.py` — NEW. ~400 LoC (byte-identical snapshot, row-shape, change-gate, dedup, label vocabulary, ordering, force_redispatch).
- `docs/readmes/README_v<version>.md` — NEW pre-deploy, rewritten post-restart with one-shot DB query evidence.

**Not touched:** `const.py`, `config_flow.py`, `options_flow.py`, `binary_sensor.py`, `number.py`, `switch.py`, `select.py`, `button.py`, other coordinators, `energy.py` (overlay unchanged), `energy_write_verify.py` (contract unchanged; label vocabulary imported from it), `energy_drain_precedence.py` (unchanged), `database.py` (uses existing `log_activity`).

---

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018uEjYPUcWq73wfBS3t1NEa
