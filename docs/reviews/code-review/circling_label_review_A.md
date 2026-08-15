# CIRCLING-LABEL-1 — Reviewer A (correctness + edge cases + invariant integrity)

**Branch:** `feature/circling-label` (worktree `.claude/worktrees/circling-label-build`)
**Merge-base:** `8a5394482`
**Commits reviewed:** `801a8afe1 · fba479f7e · c56ed8317 · e5d24716a · d27297ea1 · d49209aa8`
**Plan:** `docs/planning/PLANNING_circling_label_transition_dispatch.md` (rev-2)
**Framing:** local correctness, edge cases, invariant integrity of I1–I4, and adjudication of builder deviations 2 & 3.

**Verdict: SHIP** (with two low-severity follow-ups noted for opportunistic fix).

---

## What I ran

Baseline test load + three independent per-site source mutations, `PYTHONDONTWRITEBYTECODE=1` and `__pycache__` cleared before each run, source restored + re-verified green after.

| Drill | Mutation | Expected | Observed |
|---|---|---|---|
| #1 (rank inversion) | `_CLASSIFICATION_RANK["circling"] = 2 → 0` | D3 hop-3 assertions fail | **5 failed / 1 passed** in `test_circling_founding_case_transition.py` (`test_founding_shape_dispatch_count_is_three`, `_produces_exactly_one_high_circling_page`, `_ledger_final_state`, `_multi_escalation_pass_by_approach_circling_gets_two_exemptions`, `_reescalation_after_downgrade_gets_no_new_exemption`); restored → green |
| #6 (delete D5b XCORR-1 short-circuit block) | Remove the `if exemption_active and classification in ("approach","circling"):` early-return from `_evaluate_burst_demotion` | D5b night-single-camera test fails | **1 failed** — severity of hops 2/3 drops to LOW; restored → green |
| #8 (bool-semantic ledger) | Replace I4 predicate `if current in track._dispatched_classifications` with `if bool(track._dispatched_classifications)` | D3b multi-escalation test fails (dispatch count 2 vs expected 3) | **1 failed** — `expected 3 dispatches, got 2`; restored → green |

Post-restore full perimeter suite: **61 passed** (`pytest quality/tests/perimeter/ -q`).

---

## Invariant walk (I1–I4)

Hostile lifecycles constructed on paper and cross-checked against the diff + tests.

### I1 — exactly-one dispatch per escalating transition

- Ledger is a `set[str]` (`exterior_track_linker.py:122` annotation, `default_factory=set`). D3b (`test_multi_escalation_pass_by_approach_circling_gets_two_exemptions`) is the anchor and it is real: drill #8 falsifies bool semantics. ✓
- Hostile: `pass_by → approach → approach` — hop 2 fires (escalation), hop 3 blocked by I4 (approach ∈ set). ✓ (implicit in `_reescalation_after_downgrade_gets_no_new_exemption`).

### I2 — strict `<=` blocks non-escalation

- Predicate at `perimeter_alert.py:1962` uses `current_rank <= last_rank → blocked`. Boundary test `test_predicate_boundary_is_strict_le` present.
- Unknown class → rank `-1`; `None` → rank `-1`; `-1 <= -1 → blocked` (fail-closed for unknowns). ✓
- Hostile: `circling → pass_by → circling` — hop 3 sees `last='pass_by'`, `current='circling'`, escalation True; then I4 blocks (circling ∈ set). Test `test_reescalation_after_downgrade_gets_no_new_exemption` covers. ✓

### I3 — safeword outranks and does not consume

- Gate probes `nm._perimeter_silence_until` via `getattr` before I2/I4 (`perimeter_alert.py:1907–1919`), returns False when active + hazard non-life-safety.
- Does NOT touch the ledger on this path (ledger update lives in `dispatched_ok` block only). So a full safeword window does not silently consume the exemption. ✓
- Post-expiry hop re-arms — `test_transition_exemption_fires_after_safeword_window_expires` confirms.
- Baseline dispatches during safeword still occur on different cameras (baseline path not gated by safeword — that's NM's own suppress) and DO update the ledger, so `last` may already equal `pass_by` when the window expires. That is the intended I3 subtlety (documented in plan §D4 adjudication) — not a defect.

### I4 — one exemption per (track × target_class)

- `if current in track._dispatched_classifications: return False` at `perimeter_alert.py:1954`.
- Builder deviation 2 (added `test_i4_blocks_when_i2_would_permit` as the I4 anchor) is legitimate: my read confirms the plan's original set of tests all keep `last` at the higher class, so I2 alone would have covered them and the previously-named drill target could not have uniquely failed for I4 alone. The added test constructs `last='pass_by', current='circling', {"pass_by","circling"} ⊂ set` where I2 permits but I4 must block — this is a real I4-only anchor and the builder's justification is sound.

### XCORR-1 exemption early-return — can a non-exemption dispatch ride it?

- Early-return runs only when the caller passed `exemption_active=True`. `exemption_active` is a **local** in `_async_handle_perimeter_trigger` (`:1071`), initialized False every call, set True only when `_classification_transition_exemption_permitted` returned True.
- First alert (no cooldown reservation) → outer `if last_alert is not None:` branch skipped → `exemption_active` stays False → XCORR-1 short-circuit unreachable.
- No cross-event contamination possible. ✓
- Extra guard `if _cls in ("approach","circling")` prevents any weird path where `exemption_active=True` but the re-looked-up classification is `pass_by`/None from over-suppressing (would just fall through to normal XCORR-1). ✓

---

## Builder deviations

### Dev 1 — dedicated I4 anchor test (`test_i4_blocks_when_i2_would_permit`) instead of the plan-named `test_reescalation_after_downgrade_gets_no_new_exemption` as the I4 anchor

Accepted. See I4 discussion above; the builder correctly identified that the plan's chosen scenario was actually an I2-covered case, not an I4-unique case. The additional test constructs the only reachable state where I2 permits but I4 must block. This is a strengthening, not a deviation from intent.

### Dev 2 — fail-closed outer `try` in `_classification_transition_exemption_permitted`

Two `try/except Exception: return False` blocks (one wrapping the safeword probe, one wrapping the linker probe). The concern is that a real invariant bug in production (e.g. an accidental refactor removes `find_owning_track`) would fail-closed silently — no exemption dispatches, no loud signal.

- **In tests** — the specific NameError case is guarded by `test_import_missing_fails_loud`, which asserts the symbol is bound at module load, not by asserting an error propagates through the helper. That is sufficient: the surface tested is the observable one (import present at load time).
- **In production** — the log lives at `_LOGGER.debug`, invisible at default level. A silent regression where the exemption stops firing entirely would be observable only via the D3 tripwire `sensor.perimeter_circling_zero_dispatch_24h > 0`, which the operator already has.
- **Recommendation (LOW L1, follow-up):** promote the two `_LOGGER.debug` inside the outer `try`s to `_LOGGER.warning` — the intent of these branches is unreachable-in-practice, so a hit is a signal worth surfacing. Not a blocker.

---

## Findings

### MEDIUM — none

### LOW L1 — outer fail-closed `try` logs at DEBUG

**File:** `perimeter_alert.py:1911-1917, 1934-1940` (safeword probe + linker probe fail-closed catches).

The two outer try/except blocks in `_classification_transition_exemption_permitted` swallow any exception and return False with a debug-level log. Intent is fail-closed against transient state (nm/hass.data missing during shutdown, etc.), which is correct. But if the branches ever fire in steady-state production, the exemption silently stops working across the whole install and the only observable is the pre-existing D3 tripwire. Suggest promoting the two log lines to WARNING to raise ambient visibility. Not a shipping blocker.

**Bug class:** none new (relates to Bug Class #22 "silent swallow"). No QUALITY_CONTEXT.md update needed.

### LOW L2 — ledger-update `_cam_key` has no `or entity_id` fallback

**File:** `perimeter_alert.py:1456-1487` (existing `dispatched_ok` block + new ledger update inside it).

The exemption gate resolves cooldown key as `cooldown_key = self._camera_key_for_sensor(entity_id) or entity_id` (pre-existing fallback at `:1068`). The `dispatched_ok` block uses `_cam_key = self._camera_key_for_sensor(entity_id)` without the fallback (also pre-existing) and guards subsequent work with `if _linker is not None and _cam_key:`. Both `note_alert_dispatched` AND the new ledger update sit inside that guard.

If `_camera_key_for_sensor` ever returns None/empty for an entity_id that DID pass the exemption gate (via the entity_id fallback), the ledger update is skipped → `last_dispatched_classification` stays None → subsequent hops may re-fire the exemption unboundedly on that (narrow) path. The condition is bounded: `note_alert_dispatched` has the same skip, and the cooldown reservation `self._last_alert[cooldown_key] = now` uses the fallback key so a same-camera cooldown DOES still latch. So the worst case is: repeated exemption bypasses on the same camera whose sensor lookup returns None, once per hop.

This is a pre-existing asymmetry the new cycle inherits, not introduced. **Recommendation (opportunistic):** add `_cam_key = self._camera_key_for_sensor(entity_id) or entity_id` at `:1456` to make the two paths symmetric — one line, zero risk, and it fixes the note_alert_dispatched path too. Not blocking.

**Bug class:** none new.

---

## Trace check — no double-emit on the exemption hop

- Gate returns True → `exemption_active=True` set locally.
- `_evaluate_burst_demotion` early-returns `(False, ...)` on the exemption+approach/circling path → severity unchanged.
- Dispatch fires once via `nm.async_notify`; `dispatched_ok=True` on success.
- `self._last_alert[cooldown_key] = now` reserves cooldown; `_record_burst_alert` records; `note_alert_dispatched` increments `alert_count`; new ledger update writes `last_dispatched_classification` + adds to set.
- S4 in-flight guard (`self._dispatch_in_flight`) is intact and runs AFTER the cooldown/exemption gate at `:1103-1116` (my read of the surrounding source) — an exemption-permitted dispatch still respects one-in-flight-per-camera. If S4 short-circuits, the ledger update does not run (lives inside `_do_dispatch` → `dispatched_ok`), so the exemption is not consumed by an in-flight collision. Correct behavior per plan §S4 note.

---

## Suite baseline

`quality/tests/perimeter/` — 61 passed after all drills restored. No unrelated regressions surfaced.

---

## Verdict

**SHIP.** All four falsifiable invariants I1–I4 hold under real per-site source mutation. XCORR-1 exemption threading is airtight and cannot over-exempt. Builder deviations 1 & 2 are net-positive (stronger I4 anchor; fail-closed defenses that match the plan's semantics). L1 (WARNING promotion) and L2 (symmetric `_cam_key` fallback) are opportunistic follow-ups, both one-line, neither shipping-blocker.

If Reviewer B surfaces a lifecycle/restart issue I've missed, defer to combined judgment; from the correctness/edge-case framing this is ready.

— Reviewer A (Oji Udezue), 2026-08-14
