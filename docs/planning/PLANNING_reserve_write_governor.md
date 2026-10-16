# PLANNING — Reserve Write Governor (one chokepoint, floor registry, write history, restart-resilient)

**Card:** `EC-RESERVE-WRITE-GOVERNOR-1`
**Tier:** 3 (shared primitive — the single battery reserve write path consumed by ~20 emission sites across arbitrage, attain, drain, peak-buffer, inclement, EVSE overlay, and the WAIT narration; cost + safety ripple).
**Status:** `pre_planning` → BUILD-READY after plan review.
**Branch target:** `develop`.
**Scope posture:** EXTEND existing machinery (`_result`, `_floor_reserve`, `_apply_evse_battery_hold`, the drain-precedence ledger) into one *governed* reserve-write slice. Do not invent a sibling writer. Do not change inclement/EVSE/attain decision logic. Do not add new floors.

**Operator posture (2026-10-15):** *"25 places is mad. Force them through a governed slice with history and restart resilience. This is not about alerts at all."* And: *"I anticipate a tough build so it means a tight plan. Don't scope creep."* The governor is pure plumbing; it must be **byte-identical** on every tick where no registered floor binds. The inclement D-blind change (`EC-INCLEMENT-HARDENING-1`) rides on top of this governor in a **separate** revision.

---

## Institutional context verified

### Code read end-to-end during scoping
- `energy_battery.py` — `_floor_reserve` (`:3855-3870`, pure static helper), `_arbitrage_wait_floor` (`:3872-3890`), `_result` (`:6278-6610`), reserve-stamp block (`:6520-6560`), blind-gate (`:5578-5710`), reserve-emission band (`:5820-5994`, `:6098-6271`), ledger restore (`:1966-1968`, `:2318-2320`, `:2422-2446`, `:6850-6852`).
- `energy.py` — `_apply_evse_battery_hold` def (`:5239`), call sites (`:6459, :7174`), post-overlay commanded stamp band (`:5440-5480` region, verify at build).
- `energy_write_verify.py` — reserve-desired reader (`:1027, :1604-1720`), `_inclement_partial_hold_floor` (`:1647-1665`), reserve divergence (`:880-905`, `:1756`).
- `energy_drain_precedence.py` — `DrainPrecedenceState` (`:132`), transition machinery (`:304-394`), restore (`:394-454`).

### Greps run — REUSE / BUILD verdict per piece
| Proposed piece | Grep | Verdict |
|---|---|---|
| Chokepoint for reserve writes | `def _result\|reserve_level=` → single def at `energy_battery.py:6278`, all ~20 emits terminate here (A3/A2/A1 of arbitrage plan + :5820/41/57/67/83/90, :5959/79/94, :6114, :6251, :6271, blind pre-emit absent today) | **REUSED + EXTEND** `_result`. Already the CFG cloud-withhold chokepoint (`:6317-6324`) and the single `_last_reserve_level_desired` stamp (`:6532-6534`). |
| Per-branch floor helper | `def _floor_reserve` → `:3855` pure `max(existing, effective_reserve)` under `partial_hold` only | **REUSED + GENERALIZED**. Collapses into the governor's floor registry evaluator; call sites (6 incl. :3939/62, :4004/725/779, :5018, :6114) migrate 1:1 to `max(active floors)` with `partial_hold` as one registered floor source. |
| WAIT narration floor | `_arbitrage_wait_floor` `:3872` | **REUSED unchanged** as a *proposer* of the WAIT branch's `reserve_level`; the governor clamps its output, does not replace it. |
| EVSE post-overlay | `_apply_evse_battery_hold` `energy.py:5239`; called `:6459, :7174` | **REUSED unchanged.** Runs AFTER `_result`. Governor must preserve the overlay's current input shape (dict with `reserve_level` key) and its `max()`-safe semantics. |
| Drain-precedence ledger | `energy_drain_precedence.py:DrainPrecedenceState` | **REUSED unchanged** as a *floor source* (DP floor is `max()`-folded today at `energy.py` near `:5767`). Governor registers DP floor; consumer at `:5767` unchanged (idempotent). |
| Restore / commanded ledger | `_last_reserve_level` restore `energy_battery.py:1966-1968, 2318-2320`; stamp dispatch tap `energy.py` (per `:6522-6534` comments) | **REUSED + EXTEND**. Governor's write-history ring piggybacks on the same RestoreEntity blob the strategy sensor already restores — one extra key. No new RestoreEntity. |
| HVAC-side governed writer | `rg "def _write\|_governed\|_governor\|_arbiter\|command_trail" hvac*.py presence*.py` | **No match.** HVAC and presence do **not** today have a named "write governor" pattern. The closest analog in URA is `_result` itself (reserve) + the EVSE overlay (post-max). The operator's analogy is aspirational; the right structural reuse is to *harden `_result`'s already-chokepoint role into an explicit, inspectable governor*, not to port a nonexistent HVAC pattern. |
| New floors / knobs | — | **BUILD-NEW:** zero new floors, zero new behavioral knobs. The only new knob is the history-ring size (rung 1 const + optional rung-2 override). |

### Prior planning + review docs consulted
- `docs/planning/PLANNING_arbitrage_wait_inclement_floor.md` — v5.5.3 clamp cycle; the §A/§B/§C emission table (Bug Class #53) is the ancestor of this plan's site table. D-HIGH-1 history (7th unclamped reserve-emission site missed by three reviewers) is the invariant that justifies Tier 3 here.
- `docs/planning/PLANNING_inclement_hardening.md` (Rev 3) — the §"Reserve emission site inventory" table and INV-H are the input to the governor's floor registry.
- `docs/reviews/code-review/plan_inclement_hardening_review_{1,2,3}.md` — P2-05 (blind must emit via `_result`), P2-11 (symbol-anchored sites; drift), P2-12 (write-verify under blind; `_last_reserve_level_desired` stamping is load-bearing), P3-01..04 (adversarial-completeness traps).
- `docs/planning/PLANNING_inclement_weather_reserve.md` (v5.5.0) — `allow_discharge` byte-identical invariant.
- `CLAUDE.md` Tier-3 rules: falsifiable invariant up front, mutation-anchored per-site tests (Review C), adversarial completeness (Review D), orchestrator independent verify, operator checkpoint pre-ship.

---

## Falsifiable invariant (INV-G)

> **INV-G (governed emission):** for every reachable call to `_result(..., reserve_level=X, ...)` and every reachable post-overlay stamp of commanded reserve, the *dispatched* reserve value `F` satisfies
> `F == max(X, {floor.value for floor in Governor.active_floors()})`.
> **Corollaries:**
> - `F == X` when no registered floor is active in this tick (byte-identical no-op invariant).
> - A failure to register a known floor source is itself a violation (D-pass enumerates floors).

**Falsification observations (what to go look for):**
1. Any tick where `F < X` → INV-G broken (floor silently dropped).
2. Any tick where `F > X` and `Governor.last_write.winning_floor is None` → INV-G broken (unaccounted raise).
3. Any tick where a reserve write bypasses `_result` (direct `number.set_value` call outside the dispatch tap) → INV-G broken (writer outside the slice).
4. v5.17.5 blind-tick semantics changed (a new reserve command fires while fully blind + no floor transition) → INV-G broken (blind semantics regression).

---

## Design — the governor is `_result`, hardened

Three co-located pieces inside `energy_battery.py` (one new module file is OPTIONAL and discouraged — keep the slice next to `_result` so the chokepoint stays one grep away):

### 1. `_FLOOR_REGISTRY` (module-level, declared once)
Each entry: `(name, source_fn, is_active_fn)` where
- `source_fn(self) -> int | None` returns the proposed floor value (None = inactive).
- `is_active_fn(self) -> bool` short-circuits before `source_fn` for speed and clarity.

**Floors registered (existing ONLY, migrated from today's call sites — no new floors):**

| Name | Current source today | Registry source_fn | Active when |
|---|---|---|---|
| `inclement_partial_hold` | `decision.reserve_floor` when `decision.hold_depth == "partial_hold"` (via `_floor_reserve` call sites) | reads cached `self._last_inclement_decision` | `hold_depth == "partial_hold"` |
| `inclement_full_hold` | `decision.reserve_floor` under `full_hold` (sites `:5820/41/57/67`) | same cache | `hold_depth == "full_hold"` |
| `arbitrage_wait` | `_arbitrage_wait_floor(soc, now)` (`:3872`) — the drain-floor shelf | same helper | arbitrage gate open AND `_arbitrage_phase == WAIT` |
| `attain_target` | `_peak_buffer_target` consumed inside attain (`:1997, :2043`) | reads `self._peak_buffer_target` | attain active (`self._attain_active`) |
| `drain_park` | `_drain_target_for(now)` (per `_arbitrage_wait_floor` body) | same helper | off-peak drain park branch |
| `evse_overlay` | `_apply_evse_battery_hold` folds AFTER `_result` returns (`energy.py:5239`) | **registered but inert** — the overlay is a POST hook already max()-safe; registry entry is **documentation + an assertion target in INV-G corollary (3)** that no sibling writer exists. Governor does not clamp it inline. | always registered; evaluation deferred to overlay |

**No new floors.** The registry is just a *reification* of what every call site already does by inline literal. The move is from "N inline helpers each pulling the right floor" to "every site hands `_result` its proposed value; `_result` folds the registry once; one history row per tick."

### 2. `_result` additions (surgical)
Insert ONE block near the top of `_result` (just AFTER the CFG-withhold chokepoint at `:6317-6324`, BEFORE the storage-mode action at `:6334`):

```python
# Reserve Write Governor — INV-G.
# Fold the active-floor registry once per emission. Byte-identical to
# `reserve_level` when no floor is active (every is_active_fn returns False).
proposed_reserve = reserve_level
winning_floor = None
active_floors: list[tuple[str, int]] = []
if reserve_level is not None:
    for name, src_fn, active_fn in _FLOOR_REGISTRY:
        if not active_fn(self):
            continue
        v = src_fn(self)
        if v is None:
            continue
        active_floors.append((name, int(v)))
    if active_floors:
        floor_max = max(v for _, v in active_floors)
        if floor_max > reserve_level:
            reserve_level = floor_max
            winning_floor = next(n for n, v in active_floors if v == floor_max)
    self._reserve_write_history.append(
        _ReserveWriteRow(
            ts=dt_util.utcnow(),
            proposed=proposed_reserve,
            active_floors=tuple(active_floors),
            final=reserve_level,
            winning_floor=winning_floor,
            reason=reason,
        )
    )
# END governor
```

**Byte-identical guarantee:** when no `is_active_fn` returns True, `active_floors == []`, `reserve_level` is unchanged, and the only side-effect is one history row. The row is per-emission (one `_result` call = one row), *not* per 5-min tick.

### 3. `_reserve_write_history` — bounded ring, restart-resilient
- Type: `collections.deque[_ReserveWriteRow]`, `maxlen=RESERVE_WRITE_HISTORY_MAX`.
- Row: frozen `(ts, proposed, active_floors, final, winning_floor, reason)` — tuple-of-tuples for pickle safety.
- Persist: piggyback on the existing strategy-sensor RestoreEntity blob (same blob that already restores `_last_reserve_level`, `_last_reserve_level_desired`, drain-precedence state — reuses the extend-blob pattern at `energy_battery.py:1966-1968` / `:2318-2320`). ADD one key `reserve_write_history` on save; restore on boot populates the deque (truncated to maxlen). Boot restore is best-effort — a corrupt/absent key yields an empty deque, no raise.
- Diagnostic surface: `self._reserve_write_history_attrs()` returns the last N rows as a list of dicts, exposed via the existing strategy sensor's `extra_state_attributes` under key `reserve_write_history`. REUSE the attr builder next to the inclement attrs (`:2764-2805` neighbourhood).

### Non-invasive site migration

Every current `reserve_level=` call site keeps its existing *proposal* arithmetic. We retire ONLY the per-branch `_floor_reserve(...)` wrapping — proposals are passed raw to `_result`; `_result` folds the registry. This means:

- Sites `:3939, :3962, :4004, :4725, :4779, :5018, :6114, :6271` currently pass `floored = _floor_reserve(existing, effective_reserve, hold_depth)`. Migrate to pass `existing` (the pre-floor expression) directly. The governor re-derives the floor from the registry. If any site today has an **additional** inline `max()` beyond `_floor_reserve` (e.g. `:5890/5994 max(int(soc or 0) - 5, effective_reserve)`), that inline `max` stays — the governor runs on top of whatever the branch already proposes.
- Full-hold emits (`:5820, :5841, :5857, :5867`) today pass `reserve_level=decision.reserve_floor`. Migrate to pass the branch's *intent* (e.g. for full_hold the intent IS `decision.reserve_floor`, so these sites are unchanged — the floor registry re-derives the same number; byte-identical).
- Drain emit (`:6251`) passes `drain_target`. Unchanged (`drain_park` floor source yields the same `_drain_target_for(now)`; `max(existing, floor) == existing` → byte-identical).
- EVSE overlay (`energy.py:6459, :7174`) unchanged.
- Blind branch (`:5578-5710`) today has an **unfloored** reserve write at `:5667-5673` and no pre-emit. **Out of scope for this cycle** — stays exactly as today, including v5.17.5 blind semantics (no new commands while blind; `_last_reserve_level_desired` deliberately not stamped on blind ticks). The governor is BUILT so that `EC-INCLEMENT-HARDENING-1`'s D-blind can land on top in its own revision by routing the blind pre-emit through `_result` (and thus through the governor). Confirmed by this plan: nothing here changes the blind code path.

### What is deliberately **not** done
- No new RestoreEntity, no new sensor, no new signal, no new coordinator primitive, no new config field.
- No change to `_floor_reserve`'s signature *callers*; the helper itself is retired after the migration (dead code → DELETE candidate at ship+1 per supersession rule).
- No change to `_apply_evse_battery_hold` or its call sites.
- No change to the drain-precedence ledger's writer; the governor only *reads* its state via a registered `source_fn`.
- No change to `_last_reserve_level_desired` stamping semantics or the write-verify freshness contract (`energy_write_verify.py:1647-1665, 880-905`).
- No change to the CFG cloud-withhold chokepoint (`:6317-6324`).
- No change to blind-gate return semantics.

---

## Reserve emission site table (symbol-anchored; drift-safe)

| # | Branch | Symbol | Today's proposal | Today's floor mechanism | Governor migration |
|---|---|---|---|---|---|
| 1-6 | attain / peak-buffer / drain-park | `_floor_reserve` wrap at `:3939, :3962, :4004, :4725, :4779, :5018` | `floored = _floor_reserve(existing, effective_reserve, hold_depth)` | per-branch helper | pass `existing` to `_result`; registry refolds |
| 7-10 | inclement full_hold emits | `:5820, :5841, :5857, :5867` | `decision.reserve_floor` | branch literal | **unchanged** (byte-identical) |
| 11-12 | inclement partial-hold / discharge-with-floor | `:5883, :5890` | `effective_reserve` / `max(int(soc)-5, effective_reserve)` | branch literal | unchanged (registry re-derives same number) |
| 13-14 | mid_peak hold / discharge-with-floor | `:5959, :5979, :5994` | `hold_reserve` / `effective_reserve` / `max(soc-5, eff)` | branch literal | unchanged |
| 15 | arbitrage CHARGE/HOLD/WAIT emit (`_floor_reserve` wrap) | `:6114` | `floored` | per-branch helper | retire the wrap |
| 16 | WAIT narration floor | `_arbitrage_wait_floor` consumer within `_get_arbitrage_decision` | branch literal | unchanged |
| 17 | off-peak drain | `:6251` | `drain_target` (already max-folded under partial_hold at `:~6223`) | branch max | unchanged |
| 18 | off-peak hold | `:6271` | `hold_reserve` (already max-folded at `:6263-6264`) | branch max | unchanged |
| 19 | EVSE overlay (POST `_result`) | `energy.py:_apply_evse_battery_hold` | input dict's `reserve_level` key | overlay max | **unchanged**; registered as documentation |
| 20 | DP ledger consumer | `energy_drain_precedence.py:68, 98` + `energy.py` near `:5767` | reads `effective_reserve` passed in | caller max | unchanged |
| 21 | **blind reserve write at `:5667-5673` (unfloored)** | blind-gate | `int(self.reserve_soc)` | NONE | **OUT OF SCOPE** this cycle (inclement D-blind next rev) |

**Only sites 1-6 and 15 see a line edit.** All other sites are byte-identical. The governor fold happens inside `_result`; its correctness is driven by the registry, not by the call sites.

---

## Config-extreme + edge cases (Review A/C must cover)

1. **No floor binds (allow_discharge, no attain, arbitrage gate closed):** `active_floors == []`, `final == proposed`. Byte-identical.
2. **One floor binds, proposed > floor:** `final == proposed` (no raise). `winning_floor is None` (we only name a floor when it actually wins).
3. **One floor binds, proposed < floor:** `final == floor`, `winning_floor == name`. One row.
4. **Multiple floors active (inclement partial_hold + attain target):** `final == max(all)`; `winning_floor` is the single max. If tie, the first registry entry at that value wins (deterministic by registry order; document in INV-G note).
5. **Floor > target (`floor=80, peak_buffer_target=40`):** governor raises `final` to 80. `charge_from_grid` untouched — CHARGE still proceeds. Covered by v5.5.3's charge-intent guarantee; test re-run.
6. **SOC None (fully blind):** governor runs normally on whatever proposal the sighted branches emit. Blind-branch at `:5667-5673` is out of scope; governor sees no call from the blind branch today (unchanged). Verified by test: `test_governor_no_fold_on_blind_tick`.
7. **`reserve_level=None`:** governor short-circuits (no fold, no row). Preserves `_result`'s existing semantics (no reserve action appended).
8. **Floor source raises:** governor catches `Exception` per source_fn, logs at DEBUG, excludes from `active_floors`. Never raises from `_result`. Test: `test_governor_source_raise_is_swallowed`.
9. **History ring overflow:** deque at `maxlen` drops oldest; attribute reports current depth + maxlen. Test: `test_history_ring_bounded`.
10. **Restart with corrupt history blob:** restore yields empty deque; no raise. Test: `test_history_restore_corrupt_blob`.
11. **Restart mid-hold:** on boot, `_last_inclement_decision` is restored (v5.5.0 behaviour, unchanged); governor sees the restored floor on the first tick post-boot; first emission records a history row with `winning_floor` set correctly. Test: `test_governor_restart_recognises_restored_floor`.

---

## Per-site mutation plan (Review C — "real source mutation", not aggregate monkeypatch)

For each of the 7 line-edited sites (1-6 + 15), the C-reviewer edits production source to bypass the governor at that site exactly once (e.g. by hardcoding the branch's old `_floor_reserve` wrap to return `existing` unconditionally, OR by direct-writing `number.set_value` outside `_result` for that site's branch), runs the suite, and confirms a SPECIFIC test fails:

| Site # | Mutation | Must-fail test |
|---|---|---|
| 1 (`:3939` attain CHARGE) | re-insert pre-governor `_floor_reserve` returning raw `existing` | `test_attain_charge_floors_at_partial_hold_via_governor` |
| 2 (`:3962` attain HOLD) | same | `test_attain_hold_floors_via_governor` |
| 3 (`:4004` peak-buffer) | same | `test_peak_buffer_floors_via_governor` |
| 4 (`:4725`) | same | `test_drain_release_floors_via_governor` |
| 5 (`:4779`) | same | `test_drain_park_floors_via_governor` |
| 6 (`:5018`) | same | `test_offpeak_hold_floors_via_governor` |
| 15 (`:6114` arbitrage emit) | same | `test_arbitrage_wait_floors_via_governor` + `test_arbitrage_charge_intent_preserved` |

**Plus registry completeness mutations (D-pass):**
- Comment out each `_FLOOR_REGISTRY` entry one at a time → the corresponding `test_floor_<name>_registered_and_wins` fails.
- Comment out the governor fold block in `_result` → `test_governor_byte_identical_fallback_only_when_no_floor` passes, but `test_governor_folds_registered_floors` fails.

**Pyc staleness guard** (per `feedback_mutation_verification_pycache_staleness`): all mutation drills run with `PYTHONDONTWRITEBYTECODE=1`.

---

## Restart test (Tier-3 requirement)

`test_governor_restart_full_cycle` (in-suite):
1. Boot URA with a restored strategy-sensor blob containing `_last_inclement_decision = {hold_depth: partial_hold, reserve_floor: 55}` and `reserve_write_history = [<2 rows>]`.
2. First post-boot `determine_mode` on an off_peak + partial_hold-active tick emits a reserve.
3. Assert: `reserve_write_history[-1].winning_floor == "inclement_partial_hold"`, `final == 55`, and history deque length == 3.
4. Secondary assert: `_last_reserve_level_desired == 55` (write-verify stamp intact).

---

## Acceptance criteria

- **Verify:** every `reserve_level=` call site in `energy_battery.py` passes its **pre-floor** proposal to `_result`; `grep -n 'reserve_level=' energy_battery.py` returns exactly the counted set; no site invokes `_floor_reserve` after migration.
- **Verify:** `_floor_reserve` is deleted (DELETE candidate at ship+1; or inlined into the registry's `inclement_partial_hold` source_fn and removed as a public static method). Operator decision: delete in-cycle vs ship+1 — plan recommends **ship+1** to preserve a one-cycle rollback.
- **Verify (INV-G):** `test_governor_byte_identical_fallback_only_when_no_floor` — parameterized across every emission site with `allow_discharge` + arbitrage closed + no attain → snapshot of result dict is byte-identical to a saved pre-governor fixture.
- **Verify:** `sensor.ura_energy_battery_strategy` exposes `reserve_write_history` attribute (list of dicts, each with `ts, proposed, active_floors, final, winning_floor, reason`), bounded to `RESERVE_WRITE_HISTORY_MAX`.
- **Verify:** restart with corrupt / absent `reserve_write_history` key yields empty deque; no boot errors.
- **Verify (write-verify silence):** `test_write_verify_unchanged_under_governor` — `_last_reserve_level_desired` stamp semantics identical; `_inclement_partial_hold_floor` reader at `energy_write_verify.py:1647` still works.
- **Verify (CFG chokepoint):** `test_cfg_withhold_still_fires_after_governor` — cloud-fallback tick still forces `charge_from_grid=False`.
- **Verify (EVSE overlay):** `test_evse_overlay_folds_on_governor_final` — overlay runs on the governor's `final`, not on `proposed`; both call sites (`energy.py:6459, :7174`) verified.
- **Verify (blind semantics unchanged):** `test_blind_tick_no_new_reserve_write_v5175` — a fully-blind tick emits zero new reserve commands AND `_last_reserve_level_desired` is unchanged.
- **Test suite:** `quality/tests/test_reserve_write_governor.py` — ~15 tests covering the edge cases + the per-site mutation parameterization + restart test.
- **Live:** on first post-ship real-world partial_hold or attain-active tick, `sensor.ura_energy_battery_strategy` attribute `reserve_write_history` grows by exactly one row per `_result` emission with `winning_floor` set correctly; cite the entity snapshot in the README write-back.
- **Live:** `grep` the HA log for any `_result`-adjacent exception during the first 48h → zero.

---

## Non-goals (hold the line)

1. No new floor sources. (Inclement forecast, EV smart-charge, grid-import guard — all PARKED or already registered.)
2. No change to inclement decision logic — this plan is NOT `EC-INCLEMENT-HARDENING-1`.
3. No change to the EVSE overlay internals.
4. No change to the drain-precedence state machine.
5. No change to the write-verify freshness contract or stamp timing.
6. No change to v5.17.5 blind-tick semantics (blind reserve write at `:5667-5673` is OUT; the inclement D-blind cycle will route it through `_result` on top of this governor).
7. No new RestoreEntity, no new sensor, no new signal, no new config-flow field.
8. No port of a nonexistent HVAC "write governor" pattern — grep confirmed none exists; this cycle hardens `_result` and is self-contained in `energy_battery.py`.

---

## Knob ladder

| Name | Rung | Default | Why |
|---|---|---|---|
| `RESERVE_WRITE_HISTORY_MAX` | 1 (const in `energy_const.py`) | 100 | Bounded ring; sized for ~8h of 5-min emissions. Rung-1 because changes alter diagnostic-attr memory footprint; operator doesn't legitimately tune by observation. |
| `_FLOOR_REGISTRY` | 1 (const, declared once at module load in `energy_battery.py`) | per table above | Rung-1 because adding a floor is a topology change (new INV-G floor source → new review). |

**No rung-2 options, no rung-3 Number entities.** The governor is pure plumbing.

---

## Build-risk prediction (what a builder will likely get wrong)

1. **Dropping the pre-floor proposal in the migration** — a builder may "clean up" sites 1-6 by *also* removing the branch's defensive `max(int(soc)-5, effective_reserve)` at `:5890/5994`. **Do not.** The governor runs ON TOP of whatever the branch proposes; branch-local defensive maxes stay.
2. **Collapsing `_floor_reserve` inline too eagerly** — tempting to delete the helper in the same commit as the migration. **Don't** — ship+1 DELETE preserves one-cycle rollback. Mark the helper `# RETIRED — DELETE candidate ship+1` and leave the body intact (unreferenced).
3. **Writing the history row before the fold** — the row must capture BOTH `proposed` and `final`; writing after the fold is correct. Builders often write it before.
4. **Over-wiring the EVSE overlay** — `evse_overlay` is a *documented* registry entry, not a clamped one. The overlay still runs post-`_result` as today. Do not add a pre-fold EVSE clamp.
5. **Breaking `_last_reserve_level_desired` on blind ticks** — the governor must not touch the stamp semantics; the stamp block at `:6520-6560` is unchanged. v5.17.5 blind-tick staleness is load-bearing for write-verify.
6. **Catching too broadly in source_fn evaluation** — swallow `Exception` only around each `source_fn(self)` call, not around the whole fold. A registry iteration bug must fail loudly in tests.
7. **Making the registry global-mutable** — `_FLOOR_REGISTRY` is a tuple of tuples at module scope; do not expose a public `register_floor()` API. Future floors are code changes (rung-1 topology), not runtime registrations.
8. **Restart blob extension getting its own RestoreEntity** — do not add a new RestoreEntity; piggyback on the existing strategy-sensor blob. A new RestoreEntity would double the restore surface and race boot.
9. **Serializing deque directly** — pickle via tuple-of-tuples; deque pickling across HA versions is fragile.
10. **Changing arbitrage CHARGE→HOLD transitions** — v5.5.3 proved the transition reads `_peak_buffer_target`, not the clamped reserve. Governor does not touch phase transitions. Builder must not "simplify" the transition to read the governor's `final`.

---

## Tier-3 review framings (four, parallel, disjoint)

- **A — local correctness:** fold arithmetic, registry source_fn correctness, history-row shape, byte-identical no-op.
- **B — integration / state-machine:** `_result`'s existing responsibilities (CFG withhold, stamp block, arbitrage_phase sync, cloud mapping) preserved; EVSE overlay sees the right input; write-verify stamp semantics unchanged; restart contract.
- **C — test authority (per-site source mutation):** real production-source mutation per migrated site (table above); each mutation trips a specific named test; `PYTHONDONTWRITEBYTECODE=1`.
- **D — adversarial completeness / diff-blind:** independently re-enumerate every reserve-write path in `energy_battery.py` AND `energy.py` AND `energy_drain_precedence.py` AND `energy_write_verify.py` dispatch tap. Confirm (a) every path either passes through `_result` or is EVSE-overlay / DP-ledger (documented); (b) no sibling writer exists; (c) INV-G corollary (3) holds. D-reviewer owns the "7th site" prevention — this is the same framing that caught v5.5.3's D-HIGH-1.

Pre-ship: orchestrator independently re-greps `number.set_value` + `reserve_soc` references across `custom_components/universal_room_automation/**/*.py` and confirms every write terminates in `_result` or the overlay/DP ledger. **Operator checkpoint BEFORE deploy.**

---

## Sequencing

1. Ship this governor **first**. It is the structural chokepoint `EC-INCLEMENT-HARDENING-1` D-blind will route through.
2. Then `EC-INCLEMENT-HARDENING-1` lands D-blind as a one-line routing change through `_result` (and therefore the governor).

---

## Files touched

- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` — governor block in `_result`, `_FLOOR_REGISTRY` tuple at module scope, history deque init + restore extension, attr builder. Est. +120 / -40 LoC.
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py` — `RESERVE_WRITE_HISTORY_MAX = 100`. +1 LoC.
- `quality/tests/test_reserve_write_governor.py` — NEW, ~15 tests. ~400 LoC.
- `docs/readmes/README_v<version>.md` — NEW pre-deploy, rewritten post-restart with the validation table.

**Not touched:** `const.py`, `config_flow.py`, `options_flow.py`, `sensor.py` (attr builder reuses the existing strategy sensor's `extra_state_attributes` path), `binary_sensor.py`, `number.py`, `switch.py`, `select.py`, `button.py`, any other coordinator, `energy.py` (overlay unchanged), `energy_write_verify.py` (contract unchanged), `energy_drain_precedence.py` (unchanged).

---

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018uEjYPUcWq73wfBS3t1NEa
