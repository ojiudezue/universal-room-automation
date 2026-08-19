# STEP Chatter D7 — Tier-3 Review B+C (Integration/Lifecycle + Test-Authority via Mutation)

**Reviewer:** ura-reviewer (framings B + C, adversarial, framing-disjoint from A+D)
**Diff:** `git diff c2308dcba..7f145ee84` on `develop` (worktree `.claude/worktrees/step-chatter`)
**Scope:** D7 additions only — CHATTER-OBSERVE-CONTROL-D7-1 (shadow-first mode + house-level control + room telemetry)
**Method:** Read the diff end-to-end; ran the D7 test file + `test_chatter_wire_in.py` + `test_chatter_tick_helper.py` + `test_unavailable_entities_chatter.py` (37 passed); performed 4 independent per-site source mutations with `PYTHONDONTWRITEBYTECODE=1` + cache clears, restoring after each; verified `git status --porcelain` shows zero tracked-file drift.

---

## Verdict

**Overall:** DO NOT SHIP as-is. Two real findings (one HIGH, one MEDIUM) tied to the load-bearing D7 promise — plus a documentation/reality drift MEDIUM. All findings live at the **runtime mode-flip boundary** and the **legacy kill-switch fallback path** — the two ingredients A+D's diff-scoped framings are least likely to catch.

**Shadow-seam-is-mutation-anchored:** CONFIRMED. Independent per-site mutations of `coordinator.py::_apply_chatter_tick` prove the seam is the load-bearing wire and the D7 test is not hollow:

| Mutation | Anchor | Expected red | Observed |
|---|---|---|---|
| M1 | `if is_act:` → `if True:` | `test_d7_shadow_mode_does_not_promote_into_exclusion_set` reds | REDS (`D7 SHADOW SEAM VIOLATED: fusion excluded a chatterer in shadow mode`) |
| M2 | `if is_act:` → `if False:` | `test_d7_act_mode_DOES_promote_into_exclusion_set` reds | REDS (`D7 ACT SEAM VIOLATED: chatterer NOT excluded in act mode`) |
| M3 | `DEFAULT_CHATTER_MODE = CHATTER_MODE_SHADOW` → `CHATTER_MODE_ACT` | `test_d7_default_mode_is_shadow` + drill 21 red | BOTH RED |
| M4 | `ChatterDetector.telemetry()` first line → `return []` | telemetry test + drill 22 red | BOTH RED |

Every mutation restored cleanly; post-restore re-runs all green; tree-clean confirmed. The `test_chatter_wire_in.py::_TOUCHED_FILES` snapshot fixture correctly covers `select.py` + `number.py` (belt-and-braces per D2-MED-1). Drills 20/21/22 are real (they subprocess-invoke the mutated production tree with a fresh cache, not the parent process's already-imported modules).

**Mode-flip-releases-stale:** **DENIED** — see B-HIGH-1 below.

---

## Findings

### B-HIGH-1 — act→shadow flip does NOT release prior act-mode exclusions ("suppression needs discharge" violation)

**File:** `custom_components/universal_room_automation/coordinator.py:2197-2219` (`_apply_chatter_tick` mode-transition path)
**Class:** *Suppression-Needs-Discharge* (per `feedback_suppression_needs_discharge`) + Bug Class #53 (computed-but-not-consumed at a state-machine seam).

**Repro (legal config, one operator gesture):**
1. Mode = `act`. A qualifying chatterer fires → `_exclusion_set.promote("chatter", eid, reason=...)` at line 2264. The vote is now excluded from fusion.
2. Operator opens the dashboard and flips `select.ura_chatter_mode` → `shadow`.
3. Next `_apply_chatter_tick`: `mode="shadow"`, `enabled = mode != "off"` → `True`. `self._chatter_kill_switch_last` is also `True`. The `if self._chatter_kill_switch_last and not enabled` guard at line 2205 does NOT fire → `_discharge_chatter_latches` is never called → `_exclusion_set` still contains the chatter promotion.
4. `check_release()` only releases when the DETECTOR sees `CHATTER_RELEASE_QUIET_S` of quiet. A still-chattering sensor stays quarantined indefinitely.

**Why this is HIGH, not MEDIUM:** the D7 comment at line 2268-2269 promises "*SHADOW: DO NOT promote; DO NOT add to stuck_sensors — occupancy fusion is byte-identical to no-chatter.*" That promise is FALSE across a live act→shadow flip. During the 2-day evaluation window, if the operator sees an unexpected quarantine and flips to shadow to unblock fusion (the exact use case the control was added for), fusion stays broken. Silent operator-intent violation on the primary D7 knob.

**Fix (in-cycle):** either (a) discharge exclusions on any mode→non-act transition (mirror the B-LOW-4 `_chatter_kill_switch_last`→discharge idiom with a `_chatter_act_last` tracker that discharges when act→{shadow,off}), or (b) in shadow mode, actively `_exclusion_set.release("chatter", eid)` for every currently-known chatter promotion at the top of the tick. (a) is cleaner because it fires only on transition.

**Test to add:** live mode-flip test — construct with mode=act, tick, assert exclusion, flip `_mode` to shadow, tick again, assert exclusion released.

---

### B-MED-1 — Orphaned `CONF_CHATTER_QUARANTINE_ENABLED` with no operator-facing reset surface

**Files:**
- `custom_components/universal_room_automation/config_flow.py:6599-6605, 6636-6644, 6906-6913` (form field REMOVED)
- `custom_components/universal_room_automation/coordinator.py:2374-2383` (`_chatter_mode()` still honors the flag)

**Class:** Migration correctness / options-flow round-trip gap.

**Repro:** an operator on a pre-D7 build sets `CONF_CHATTER_QUARANTINE_ENABLED=False` via the form (legal, was the documented kill switch). Upgrade to D7. `nm_cycle_a_knob(hass, CONF_CHATTER_QUARANTINE_ENABLED, DEFAULT=True)` returns the stored `False` → `_chatter_mode()` short-circuits to `off` regardless of what the Select shows. The Select becomes decorative; there is NO UI to clear the stored `False` because D7 deleted the form field (see the D-MED-2-style tunable Numbers, which also lose their form path — same shape but the Numbers at least have live entities). Recovery requires editing `.storage/core.config_entries` by hand.

**Fix (in-cycle):** one of —
1. Ship the `switch.ura_chatter_enabled` entity that the config_flow comment at line 6909 already **claims exists** (see B-MED-2 — this fixes both findings), OR
2. Add a one-shot migration in `async_migrate_entry` that pops `CONF_CHATTER_QUARANTINE_ENABLED` from options and, if it was `False`, writes `CONF_CHATTER_MODE=off` in its place, OR
3. Change `_chatter_mode()` to ignore `CONF_CHATTER_QUARANTINE_ENABLED` (rely on mode="off" as the sole disable), which retires the flag cleanly.

Option 2 preserves operator intent across the upgrade; option 3 is the smallest diff.

---

### B-MED-2 — Documentation/reality drift: config_flow claims a Switch that was never added

**File:** `custom_components/universal_room_automation/config_flow.py:6907-6912`

The comment enumerates the four ship-first surfaces:
```
#   * switch.ura_chatter_enabled    (integration device)
#   * select.ura_chatter_mode       (integration device)
#   * number.ura_chatter_burst_k    (CM device)
#   * number.ura_chatter_t_floor    (CM device)
```

`grep -rn ura_chatter_enabled custom_components/ quality/tests/` returns ONLY this comment line. No `switch.py` entity, no test. A future maintainer reading this comment will look for a Switch that does not exist; an operator reading the release notes verbatim will not find the toggle. Direct fix: either (a) ship the Switch (recommended — resolves B-MED-1 too) or (b) delete the `switch.ura_chatter_enabled` line and add "the Select's `off` option is the enabled/disabled control."

---

### B-LOW-1 — `_chattering_entities` retained on off→shadow with previously-off surface state (minor operator-facing surface inconsistency)

**File:** `coordinator.py:2213-2219` vs `2258-2259`

Not a correctness bug — surface parity is preserved on the next tick — but worth noting: the off-mode branch (line 2214) writes `self._chattering_entities = set(self._chatter_detector.chattering_entities())` AND returns; the shadow/act branch (line 2259) does the same write. So after off→shadow the set is refreshed cleanly. No fix needed; called out because I inspected the seam for this exact class.

---

## C-Framing (Test Authority via Mutation) — Confirmed Real

Every D7 acceptance-test claim was independently mutation-verified this session (see M1-M4 table above). Findings:

- **All 5 D7 tests + 3 D7 drills (drills 20/21/22) are real.** Post-mutation the specific named test reds; post-restore the test greens.
- **Drill 22 restore covers select.py + number.py** — `_TOUCHED_FILES` extension per D2-MED-1 works: I ran the drill (which internally mutates `chatter_detector.py`), then verified `git status --porcelain` returns no tracked drift.
- **AST-extraction correctness** — the `_extract()` helper in `test_chatter_d7_shadow_act.py` pulls the *actual* `_apply_chatter_tick` + `_chatter_mode` + `_discharge_chatter_latches` + `_chatter_quarantine_enabled` + `_fusion_filter_active` bodies from `coordinator.py`; mutation M1 (`if is_act:` → `if True:`) reds the shadow test, proving the extracted AST tracks the real source.
- **No hollow anchors** in the D7 additions.

Gap: **no test covers the live mode-flip transition** (B-HIGH-1). The 5 D7 tests all set `_mode` at fixture construction; none flip mid-run to observe stale-exclusion release. Add such a test alongside the B-HIGH-1 fix.

---

## Integration / Lifecycle checks — clean unless noted

- **§D1.1 tick ordering / D2-raise Reading-A byte-identity:** preserved. The mode gate is inside the promote block only; check_release, chatter_current read, `_chattering_entities` write, `_stuck_sensor_kinds` write, and NM scheduling all remain in the same order as pre-D7. Reading-A path (fusion) sees `_exclusion_set` unchanged under shadow.
- **D5 surface (`_chattering_entities`, `_stuck_sensor_kinds`):** correctly populated in shadow (verified by `test_d7_shadow_mode_does_not_promote_into_exclusion_set`).
- **Number/Select entity lifecycle:** `async_setup_entry` registers once per matching entry_type; DeviceInfo identifiers are stable (`(DOMAIN, "coordinator_manager")` for the Numbers, `(DOMAIN, "integration")` for the Select); unique_ids are `DOMAIN`-prefixed and unique; `EntityCategory.CONFIG` set. No leak.
- **Options-write → live-value round-trip:** Number `async_set_native_value` calls `hass.config_entries.async_update_entry(entry, options={...})`; the `_NM_A2_KEYS` extension in `__init__.py` includes `CONF_CHATTER_MODE` (and pre-existing `CONF_CHATTER_BURST_K` / `CONF_CHATTER_T_FLOOR_S`), so the CM options listener invalidates the `nm_cycle_a_knob` cache without a reload. `_chatter_mode()` re-reads via `nm_cycle_a_knob` on every tick — no stale cache. Select's `current_option` reads `entry.options` directly on every state render — same story. Restart-safe (entity.options persists in `.storage`).
- **`ChatterDetector.telemetry()` perf/exceptions:** iterates `self._entity_to_meta.items()` (bounded by monitored-sensor count per room, ~O(10)); `k = self._effective_burst_k()` called ONCE outside the loop; `len(deque)` is O(1). Consumer at `sensor.py:1922-1932` is `try/except`-guarded → any raise degrades to no-op attribute. `getattr` + `hasattr` guards keep it None-safe on rooms without a detector.
- **Mode-flip act→act (same value):** no-op (Select early-returns on invalid, always writes on valid — a same-value write triggers one options-updated event but no state change; harmless).
- **Off→shadow / off→act transitions:** clean (nothing was promoted while off, so no stale exclusion).
- **Shadow→act transitions:** clean (act promotes the current chatterers on the next tick).
- **Any→off transition:** the B-LOW-4 discharge fires as designed.
- **act→shadow transition:** BROKEN (B-HIGH-1).

---

## Recommendation

**Fix-up before ship:** B-HIGH-1 + B-MED-2 (5-line comment edit) at minimum. B-MED-1 is best resolved by the same Switch-entity fix that resolves B-MED-2; if not shipping the Switch, adopt option 3 of B-MED-1 (retire `CONF_CHATTER_QUARANTINE_ENABLED` from `_chatter_mode()`). Then re-run the D7 suite + add the mode-flip test + re-verify tree-clean.

Absent a live mode-flip discharge, D7's SHADOW-FIRST doctrine has a runtime foot-cannon at the operator's exact escape hatch. Fix is small; the test-authority framework already in place (drill 20 mutation-verified) makes the addition straightforward.
