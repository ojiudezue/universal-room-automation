# STEP Chatter — D7 Review (A + D combined, Tier-3 adversarial)

**Reviewer:** ura-reviewer (combined A=correctness + D=adversarial-completeness pass, incident-informed)
**Cycle:** STEP chatter — D7 delta (shadow-first + house-level control entities + room telemetry + config-flow migration)
**Diff scope:** `git diff c2308dcba..7f145ee84` in `.claude/worktrees/step-chatter` (12 files, +858/-64)
**Baseline (pre-D7):** commit `c2308dcba` (STEP D1..D5 shipped state)
**Head:** commit `7f145ee84` (STEP D7)
**Plan:** `docs/planning/PLANNING_sensor_health_surfacing.md` (D7 sections + 2026-08-19 amendment)
**Incident context:** v5.84.0 presence-startup UnboundLocalError (function-local `from ..const import CONF_ENTRY_TYPE` shadowed module-level). This review actively hunts for the same class in the D7 delta.

---

## Verdicts

- **Boot-safety verdict (incident class):** **CLEAN.** No import-shadow / UnboundLocalError / entity-setup-crash class introduced by D7. Details in §Boot-Safety Sweep below.
- **Shadow-never-excludes verdict (D7 load-bearing invariant):** **VIOLATED** on a legitimate operator action — see **D-HIGH-1** (mode-transition act→shadow leaves stale `_exclusion_set` chatter promotions live for up to `CHATTER_RELEASE_QUIET_S` = 900 s).
- **Overall:** **SHIP-WITH-FIX.** Fix D-HIGH-1 (mandatory) and A-MED-1 (recommended, same mechanism on mode→off transition) before deploy. Housekeeping A-LOW-3 (unrestored mutation drills in the worktree) must be reverted before any test-based re-verification.

---

## Boot-Safety Sweep (v5.84.0 incident class)

**1. Function-local imports that could shadow a module-level name:**

`coordinator.py::_chatter_mode()` uses one function-local `from .const import (...)` block bringing in `CHATTER_QUARANTINE_ENABLED`, `CONF_CHATTER_MODE`, `CONF_CHATTER_QUARANTINE_ENABLED`, `CHATTER_MODES`, `DEFAULT_CHATTER_MODE`, `DEFAULT_CHATTER_QUARANTINE_ENABLED`, `CHATTER_MODE_OFF`. Grepped module-level imports (`coordinator.py:31` `from .const import (...)`): only `CHATTER_OBSERVATION_WINDOW_S` and `CHATTER_RELEASE_QUIET_S` land at module scope. **None of the seven function-local names collide with a module-level binding** — no shadow, no UnboundLocalError possible.

Both `try/except` branches inside `_chatter_mode()` fail-safe to a legal string literal (`"off"` or the local `DEFAULT_CHATTER_MODE` which is only referenced inside the branch where the outer import already succeeded). Safe.

**2. Config-flow migration integrity (removed CONF_CHATTER_* from `async_step_coordinator_notifications_volume`):**

- The tuple `from .const import (...)` at `config_flow.py:6570-` has the three CONF_* + three DEFAULT_* names REMOVED. Remaining grep hits are comment-only (`config_flow.py:6599, 6639, 6904, 6906`). No dangling references. Tuple parenthesization intact.
- `_DEFAULTS` dict has the three CHATTER keys removed cleanly.
- The `vol.Schema({...})` block has the three chatter `vol.Optional(...)` fields removed cleanly. Braces balanced. `async_show_form(step_id="coordinator_notifications_volume", ...)` still returns a valid schema. Opening the step will NOT crash.
- Migration semantics: any pre-existing value for these three keys in `entry.options` (from prior D2 fix-up ships) remains persisted and continues to be read by `nm_cycle_a_knob(...)` in the detector and by the new Numbers' constructors. **No data loss.** Correct.

**3. Entity setup can't crash at boot:**

- `select.py::async_setup_entry` gates `ChatterModeSelect` on `entry_type == ENTRY_TYPE_INTEGRATION` — the integration singleton entry always exists post-config. Constructor performs local imports (`DeviceInfo` already at module scope — safe re-bind; `EntityCategory`, `CHATTER_MODES`, `CONF_CHATTER_MODE`, `DEFAULT_CHATTER_MODE`, `VERSION` — none collide with module scope). No coordinator access in `__init__`. Cannot raise at boot.
- `number.py::async_setup_entry` for the two Chatter Numbers is co-located with the existing CM-device Numbers list — added at the end, unconditional inside the same entry-type branch that already ships live. Constructor is pure attribute assignment + one `entry.options` read (fail-safe via TypeError/ValueError guard). Cannot raise at boot.
- Detector `telemetry()` addition is a pure method; no import-time or setup-time side-effect.
- `sensor.py` attribute augmentation is wrapped in a broad `try/except` — diagnostics degrade if the detector isn't wired.

**No v5.84.0-class boot hazard in the D7 delta.**

---

## Findings

### D-HIGH-1 — Mode-transition act→shadow leaves stale exclusion-set chatter promotions (invariant violation)

- **Severity:** HIGH
- **Framing:** D (adversarial completeness) — falsifies the D7 load-bearing invariant "in shadow mode, no chatter vote is ever excluded from the occupancy fusion; only in act"
- **Site:** `custom_components/universal_room_automation/coordinator.py:2201-2274` (`_apply_chatter_tick`), interacting with `_exclusion_set` populated on a prior act-mode tick
- **Boot-reachable:** No (requires a runtime operator flip after a real chatter promotion) — but reachable on any legitimate operator action ("let me flip act→shadow to observe the surface without quarantining")
- **Repro (legal-config, no code change needed):**
  1. Operator sets `select.ura_chatter_mode = act` (a supported option)
  2. Sensor X qualifies as chattering (K bursts in T_floor window) → `_exclusion_set.promote("chatter", X, reason="physics_violation")` fires on that tick
  3. Operator flips `select.ura_chatter_mode = shadow`
  4. Next tick within X's chatter observation window: `mode = "shadow"`; `enabled = True` (mode != off); the `_chatter_kill_switch_last and not enabled` discharge guard does NOT fire (True→True); `check_release()` returns `[]` because X is still bursting; the "current chatterers" loop runs with `is_act = False` and correctly skips re-promote — **but the prior promotion is still in `_exclusion_set`.** `_fusion_filter_active` (coordinator.py:2159) excludes X because `_exclusion_set.is_excluded(X)` remains True.
  5. State persists until `CHATTER_RELEASE_QUIET_S` (const.py:3832 = **900 s / 15 min**) of continuous quiet on X — a full observation window in which the docstring's invariant is falsified.
- **Why it slipped past D2/D3 tests and A/B/C reviewers:** All D7 tests start in a single mode and don't flip. The `is_act` gate is arithmetically correct for the *tick-local* promote; the leak is *cross-tick, cross-mode* state carried by `_exclusion_set` — a different surface from the one the gate protects.
- **Fix:** Track `self._chatter_mode_last: str | None`. At the top of `_apply_chatter_tick`, on any transition where `_chatter_mode_last == "act"` and current `mode == "shadow"`, iterate the currently-promoted chatter clients and `self._exclusion_set.release("chatter", eid)` for each; also `pop` the `"chatter"` kind label if no other client holds the entity (mirroring the check_release path at 2226-2233). Update `self._chatter_mode_last = mode` at the end of the tick. Add a test that promotes in act, flips mode to shadow, and asserts `_fusion_filter_active([X])` returns `[X]` on the next tick (byte-identical to no-chatter).
- **Blocker for ship.**

### A-MED-1 — Same class on mode→off transition; discharge is NM-only, does not release exclusion_set

- **Severity:** MEDIUM
- **Framing:** A (correctness) + adjacent to D-HIGH-1
- **Site:** `custom_components/universal_room_automation/coordinator.py:2205-2219` (kill-switch discharge branch) and `coordinator.py:2314-2345` (`_discharge_chatter_latches`)
- **Mechanism:** `_discharge_chatter_latches` drains ONLY the `_chatter_nm_fired` per-day dedup set — it does not release `_exclusion_set` clients. When mode flips to off, the early-return at line 2210 (`return` after setting `_chattering_entities`) prevents `check_release()` from ever firing while off. Any chatter promoted just before the flip stays excluded indefinitely (until the operator re-enables and the entity later goes quiet).
- **Repro:** as D-HIGH-1 steps 1-3 but flip to off instead of shadow; X remains excluded even after CHATTER_RELEASE_QUIET_S because `check_release` never runs.
- **Historical note:** Pre-D7 kill-switch had the same shape, but D7 elevates the reachability by making the mode-flip a first-class operator surface (a Select dropdown, not a hidden dev toggle).
- **Fix:** In the same transition-detection block added for D-HIGH-1, on mode→off release ALL prior chatter promotions and clear `_chattering_entities`. Cheap: one iteration over the previously-promoted set.
- **Recommended for ship** (same commit as D-HIGH-1 — same detection point).

### A-LOW-1 — Redundant `self.hass = hass` assignment in D7 entity constructors

- **Severity:** LOW
- **Sites:** `select.py::ChatterModeSelect.__init__` and `number.py::_ChatterCMNumberBase.__init__`
- HA populates `self.hass` after `async_add_entities`. Explicit early assignment is redundant and has, in some HA versions, caused subtle ordering issues with async listener registration. Not a boot crash today; matches a pattern already present elsewhere in this file. Optional cleanup, not a blocker.

### A-LOW-2 — Detector `telemetry()` reads a private attribute (`_entity_to_meta`) without a guard

- **Severity:** LOW
- **Site:** `domain_coordinators/chatter_detector.py:582` inside `telemetry()`
- If `_entity_to_meta` were ever unset (e.g. detector partially initialised on an in-progress reload path), `telemetry()` would raise `AttributeError`. The consumer in `sensor.py:1919` wraps the call in `try/except`, so diagnostics degrade gracefully — but the try/except swallows the exception without a `_LOGGER.debug(..., exc_info=True)`, so a real bug would go unlogged. Consider adding `exc_info=True` to the swallow at `sensor.py:1928`. Not a blocker.

### A-LOW-3 — Unrestored mutation drills in the worktree (evidence-hygiene)

- **Severity:** LOW (process, not code)
- **Sites observed in `.claude/worktrees/step-chatter` at review time:**
  - `custom_components/universal_room_automation/coordinator.py:2261` — `if is_act:` replaced with `if False:  # MUTATION D7-M2`
  - `custom_components/universal_room_automation/const.py:3886` — `DEFAULT_CHATTER_MODE = CHATTER_MODE_ACT  # MUTATION D7-M3`
- These are from concurrent reviewer drills (Review C / Review D2 docs present). They **do not affect the D7 code correctness** but WILL poison any pytest run that inherits the tree (invariant of the "unrestored drill poisons evidence" rule). Must be `git checkout --` reverted before any test-based re-verification.
- I did **not** modify the worktree — the concurrent reviewer's drill is theirs to restore.

---

## Correctness (A) — What Works

- **Shadow seam (coordinator.py:2264):** `is_act = mode == "act"`; only `is_act` gates the promote + `stuck_sensors.add`. In shadow, the *tick-local* fusion contribution is byte-identical to no-chatter. Correct — the only gap is the *cross-tick* leak (D-HIGH-1).
- **`_chatter_mode()` precedence (coordinator.py:2346-2395):** module-const `CHATTER_QUARANTINE_ENABLED` kill switch → options `CONF_CHATTER_QUARANTINE_ENABLED` mirror → `CONF_CHATTER_MODE` (default `SHADOW`). Off wins over shadow/act as documented. Unknown mode string falls through to `DEFAULT_CHATTER_MODE`. Fail-safe returns are legal strings.
- **NM title differentiation (coordinator.py:2299-2305):** shadow NM prefixed `"WOULD quarantine sensor (shadow):"` vs act's `"Chattering sensor:"` — operator can see which mode fired the surface.
- **Number/Select round-trip:** both write `entry.options[CONF_*]`; the CONF keys are in `_NM_A2_KEYS` (`__init__.py:5642-5646`) so the options-update listener invalidates `nm_cycle_a_knob` cache without a CM reload; the detector re-reads via `_effective_burst_k()` / `_effective_t_floor_default()` on the next scoring call. Single source of truth is `entry.options`. Correct.
- **Detector `telemetry()` (chatter_detector.py:565-596):** reads real `_sub_floor_events` / `_edge_windows` / `_entity_to_meta`; `would_quarantine` mirrors the real scoring predicate (`t_floor > 0.0 and sub >= k`). Matches the detector's own promotion criterion by inspection. Correct.
- **Sensor attribute augmentation (sensor.py:1919-1930):** wrapped in broad try/except; adds `chatter_telemetry` list + `chatter_would_quarantine_count` scalar. Degrades on any coordinator variant that lacks the detector.

---

## Adversarial Completeness (D) — Falsifiability Analysis

**Invariant under test (verbatim from D7 amendment):** *"In `off` or `shadow` mode, no chatter vote is ever excluded from the occupancy fusion; only in `act`."*

**Enumeration of every code path that could add a chatter client to `_exclusion_set` OR otherwise remove a sensor from `_fusion_filter_active`:**

- `_apply_chatter_tick` current-chatter loop (coordinator.py:2261-2266) — gated by `is_act`. ✅ correct tick-local.
- `check_release` path (coordinator.py:2223-2226) — only *releases*, never promotes. ✅ safe.
- No other grep hit for `promote("chatter"` in `custom_components/`. ✅ single production site.
- `_chattering_entities` member set is populated in all modes (coordinator.py:2214, 2259) but is *only* consumed by `sensor.py::1841` for the diagnostic surface — NOT by `_fusion_filter_active`. ✅ diagnostic-only.
- Local `stuck_sensors` parameter is passed into `_apply_chatter_tick` but `_fusion_filter_active` uses `_exclusion_set.is_excluded` only (coordinator.py:2168-2170); the local set does not gate fusion. ✅ decoupled.

**Falsifying case found:** cross-tick residual promotion after act→shadow transition (D-HIGH-1). The tick-local enumeration is correct; the *state-machine* enumeration is not.

**STEP D1..D5 byte-unchanged by the D7 diff:** confirmed via file-scoped diff — no changes to `_fusion_filter_active`, `_exclusion_set` primitive, chatter_detector scoring logic (only additive `telemetry()`), or per-room chatter sensor from D5.

---

## Fix-Up Guidance (for the builder)

One commit fixes both D-HIGH-1 and A-MED-1 in `_apply_chatter_tick`:

```python
# In __init__ or class body:
self._chatter_mode_last: str | None = None

# Near the top of _apply_chatter_tick, after `mode = self._chatter_mode()`:
prior_mode = self._chatter_mode_last
if prior_mode == "act" and mode != "act":
    # act -> shadow OR act -> off: release stale chatter promotions so
    # the shadow-never-excludes / off-never-excludes invariant holds
    # tick-1 after the operator flip.
    for _eid in list(self._chattering_entities):
        self._exclusion_set.release("chatter", _eid)
        if not self._exclusion_set.clients_for(_eid):
            self._stuck_sensor_kinds.pop(_eid, None)
    self._chattering_entities.clear()
self._chatter_mode_last = mode
```

**Verification (add to `quality/tests/test_chatter_d7_shadow_act.py`):**

1. `test_act_to_shadow_transition_releases_prior_promotions` — promote X in act, flip to shadow, assert next-tick `_fusion_filter_active([X]) == [X]` and `_exclusion_set.is_excluded(X) is False`.
2. `test_act_to_off_transition_releases_prior_promotions` — same, flip to off, assert same.
3. `test_shadow_to_act_transition_does_not_double_release` — shadow (no promotion), flip to act, assert normal promote path still works and no spurious release NM fires.

**Re-verify after fix:** re-run D's enumeration; confirm the mode-state-machine × exclusion-set surface is covered by an explicit test at every transition edge (off→shadow, off→act, shadow→off, shadow→act, act→shadow, act→off).

---

## Ship Decision

- **SHIP-WITH-FIX.**
- **Blocking:** D-HIGH-1 (mandatory fix + test).
- **Recommended in same commit:** A-MED-1 (same detection point, same code delta).
- **Housekeeping (blocking for test-based re-verification):** A-LOW-3 (restore mutations in the shared worktree).
- **Optional cleanup, not blocking:** A-LOW-1, A-LOW-2.
- **Then:** re-run the D7 suite + the three new transition tests + a spot mutation drill on the new transition block to confirm each transition test would fail if the release loop were neutered.
