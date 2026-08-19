# STEP chatter — Tier-3 Review C (RE-RUN, post-fix-up)

**Branch:** `feature/step-chatter` @ 569b7848a
**Framing:** C — test authority via REAL per-site source mutation
**Prior verdict (C round 1):** DO-NOT-SHIP — coordinator tick / fusion tests were hollow source-string anchors that would go green under a wholesale semantic gut of `_apply_chatter_tick`.
**This verdict:** **SHIP** — the de-hollow is real, not a new hollow.

Environment: worktree `/Users/okosisi/Code/universal-room-automation/.claude/worktrees/step-chatter`, `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` cleared before each drill, source restored + `git status`-clean between drills and at end.

---

## Ast-extraction verdict: **GENUINELY BEHAVIOURAL, NOT A NEW HOLLOW**

`quality/tests/test_chatter_tick_helper.py` reads `coordinator.py` from disk each test-module invocation, ast-parses it, plucks the `_fusion_filter_active`, `_apply_chatter_tick`, `_discharge_chatter_latches`, and `_chatter_quarantine_enabled` `FunctionDef` nodes, wraps them in a bare mixin class, and `exec`s that. The extracted mixin is then bound to a stand-in with the exact attribute set the helper reads/writes. So the SAME production bytes execute under test — a coordinator.py edit flows through.

Drill 1 confirms this. See the mutation table below.

---

## Mutation drill table

All drills: mutate real production source (in-worktree), `PYTHONDONTWRITEBYTECODE=1`, clear `__pycache__`, run pytest, restore, re-run pytest for green.

| # | Mutation | Named test that reds | Expected? | Verdict |
|---|---|---|---|---|
| 1 | `coordinator.py::_apply_chatter_tick` — comment out `self._exclusion_set.promote("chatter", _ceid, …)` | `test_chatter_tick_helper::test_apply_chatter_tick_promotes_current_chatterers` | RED | ✅ REAL |
| 2 | `coordinator.py::_fusion_filter_active` — replace body with `return list(sensors)` (no filter) | `test_chatter_tick_helper::test_fusion_filter_active_extracted_matches_coordinator` + `test_chatter_wire_in::test_drill_1_d1_fusion_filter_helper_wire` | RED | ✅ REAL |
| 3 | `coordinator.py::_apply_chatter_tick` — delete `if _nm_key in self._chatter_nm_fired: continue` (break M-A1 latch) | `test_chatter_tick_helper::test_apply_chatter_tick_ma1_per_day_latch_prevents_write_flood` — reds with exact message `M-A1 VIOLATED: per-tick NM scheduling not deduped by _chatter_nm_fired; got 11 scheduled tasks over 11 ticks` | RED | ✅ REAL |
| 4 | `const.py::DEFAULT_CHATTER_BURST_K` 10 → 20 (revert recalibration high) | `test_chatter_detector::test_recalibration_invisoutlet_shape_flagged_at_K10` (invisoutlet burst=13 no longer flags at K=20) + 12 others | RED | ✅ REAL |
| 5 | `const.py::DEFAULT_CHATTER_BURST_K` 10 → 5 (recalibration low) | `test_chatter_detector::test_recalibration_meross_healthy_night_not_flagged` reds with `Meross healthy burst=7 must stay below K=10; got 7 sub-floor events` | RED | ✅ REAL |
| 6 | `coordinator.py` line 3000 — bypass one of the 6 fusion callsites (`for s in self._fusion_filter_active(motion_sensors)` → `for s in motion_sensors`) | `test_sensor_exclusion::test_all_6_fusion_sites_route_through_fusion_filter_active` reds with `found 5` | RED (structural) | ✅ REAL but count-based |

Baseline pre-drill: 59/59 green (cycle files). Post-restore: 59/59 green.

---

## Item-by-item verification against the fix-up spec

### 1. Ast-extraction genuinely drives production source
**VERIFIED.** Drills 1, 2, 3 all show a production-source mutation directly reds an ast-extracted test. `test_chatter_tick_helper.py::_extract_and_compile_helpers` uses `ast.parse((_URA / "coordinator.py").read_text())` at fixture time — no snapshot, no copy. A drift assertion (`assert set(found.keys()) == wanted`) would surface if the coordinator's method signatures moved. The extraction is real.

### 2. Six fusion callsites — helper is behaviour-tested; per-callsite routing is structurally checked
**VERIFIED with the labelled caveat.** The extracted helper is directly behaviour-tested (drill 2 reds a real test). Per-callsite routing is enforced by `test_all_6_fusion_sites_route_through_fusion_filter_active` — drill 6 shows the count-based marker DOES bite when one callsite is bypassed (count drops 6 → 5). The test's docstring explicitly labels itself `STRUCTURAL marker (NOT behavioural)` and defers coordinator-integration behavioural coverage to live-validation citing the v5.8.0 seam — **honest disposition**. Residual risk: a mutation that swaps one callsite for another `_fusion_filter_active(...)` call elsewhere would preserve the count. Acceptable per the labelled caveat + live-validation gate.

### 3. Recalibration acceptance fixtures — real, not invented
**VERIFIED.** Drill 4 (K→20) reds `test_recalibration_invisoutlet_shape_flagged_at_K10` — the invisoutlet-shape positive is genuinely gated on K=10 (its burst=13 stops flagging at K=20). Drill 5 (K→5) reds `test_recalibration_meross_healthy_night_not_flagged` with the assertion "Meross healthy burst=7 must stay below K=10; got 7 sub-floor events" — the negative sentinel bites a floor. Both fixtures trace to `PROBE_mmwave_healthy_cadence.md` / `PROBE_sensor_chatter_definition_handcheck.md` in the docstrings. Real.

### 4. De-hollow disposition — honestly labelled per site
**VERIFIED.** `test_all_6_fusion_sites_route_through_fusion_filter_active` opens with `STRUCTURAL marker (NOT behavioural)`. The 19 `test_drill_*` names in `test_chatter_wire_in.py` are honestly wired — each drill mutates a specific production anchor and asserts a NAMED behavioural test reds via a subprocess pytest invocation (feedback_hollow_test_anchors compliant). No test in the fix-up masquerades as behavioural while being a source-string check.

### 5. Chatter core + primitive drills didn't regress
**VERIFIED.** 59/59 green in cycle files at baseline, and 59/59 green after every restore. `test_chatter_wire_in.py::test_drill_*` (19 drills) all pass — the pre-existing mutation-authority machinery is intact.

---

## Findings

### LOW-1 (non-blocking, order-fragility): Cycle-file HA-stub install collides when tests run non-alphabetically

`test_chatter_tick_helper.py::_install_ha_stubs()` guards with `if "homeassistant" in sys.modules: return` but installs a stub that does NOT include a full `homeassistant.util` shim (only `homeassistant.util.dt`). Under normal alphabetical collection (`test_chatter_detector.py` runs first and installs the complete stub) everything passes. Running with `test_chatter_tick_helper.py` FIRST causes 17 collection errors in `test_chatter_detector.py`:

```
ModuleNotFoundError: No module named 'homeassistant.util'
```

Repro: `pytest quality/tests/test_chatter_tick_helper.py quality/tests/test_chatter_detector.py`.

Not blocking — default pytest collection is alphabetical and CI presumably preserves it. Recommend the tick-helper's `_install_ha_stubs` also `_mod("homeassistant.util")` to make it order-independent. Trivial one-liner.

### MED-1 (advisory, deferred to live-validation, already documented): 6-callsite routing check is count-based

`test_all_6_fusion_sites_route_through_fusion_filter_active` counts `self._fusion_filter_active(` occurrences and asserts `>= 6`. Drill 6 confirms a straight-bypass mutation reds it (6 → 5). A pathological mutation that swaps one legitimate callsite for a no-op call to `_fusion_filter_active` elsewhere would preserve the count without preserving routing. This is called out in the test's own docstring and the docstring points to live-validation. Acceptable at Tier-3 with the labelled caveat.

### No CRITICAL / HIGH findings

The prior C-CRIT-1/2/3 findings from Review C round 1 are resolved:
- **C-CRIT-1** (fusion helper hollow): fixed — `_fusion_filter_active` now behaviour-tested via ast extraction AND structural count-marker (drills 2 + 6).
- **C-CRIT-2** (tick-site promote hollow): fixed — drill 1 + drill 3 (wire-in) both red on promote mutation.
- **C-CRIT-3** (parity/M-A1 hollow): fixed — drill 3 reds the M-A1 latch mutation with the exact write-flood violation message.

---

## Verdict

**SHIP.** The de-hollow fix-up is genuine — every load-bearing site the previous C round called out as source-string-only now has a REAL per-site mutation anchor. Ast-extracted tests execute production bytes directly and red on production mutations. Recalibration acceptance fixtures are gated on K in both directions. Structural-only tests are honestly labelled and paired with behavioural drives.

Recommend LOW-1 (2-line stub fix) be picked up on next incidental touch to `test_chatter_tick_helper.py`; not a ship blocker.

Worktree left clean — `git status` shows only this untracked review file plus the prior round's `step_chatter_review_C.md`.
