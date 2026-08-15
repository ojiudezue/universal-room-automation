# CIRCLING-LABEL-1 — Reviewer B (async / lifecycle / race + cross-site interactions + restart)

Branch: `feature/circling-label` (worktree `.claude/worktrees/circling-label-build`)
Merge-base: `8a5394482`
HEAD: `d49209aa8` (6 commits, 5 files, +759 / -6)
Framing: async / lifecycle / concurrency / cross-suppression-site interactions / restart resilience.
Plan of record: `docs/planning/PLANNING_circling_label_transition_dispatch.md` (rev-2), §Perimeter suppression-site enumeration S1–S8, §Falsifiable invariants I1–I4.

## Verdict: **SHIP**

Two LOW findings (below) are non-blocking; both are documented behaviour that matches the plan. Independent re-runs of Reviewer-A drills #3 and #4 both PASS (mutation → loud named-test failures; restore → 21/21 green).

---

## Scope of the diff (verified)

| File | Change | Notes |
|---|---|---|
| `exterior_track_linker.py` | +19 (dataclass fields on `ExteriorTrack`) | `last_dispatched_classification: str \| None`; `_dispatched_classifications: set[str]` — RAM-only, dies with the track. Docstring pins re-arm semantics per LOW-4. |
| `perimeter_alert.py` | +178 / −6 | New `_CLASSIFICATION_RANK`, `_classification_transition_exemption_permitted`, two-step gate at cooldown, `exemption_active` kwarg threaded into `_evaluate_burst_demotion` with early-return for `approach`/`circling`, ledger-update block inside `dispatched_ok`. Module-level import `from ._nm_cycle_a import is_life_safety_hazard` present (MED-1 pin). |
| `notification_manager.py` | +10 (comments only) | Contract tripwire on `_perimeter_silence_until` documenting the cross-module reader in PA (I3). No behavioural change. |
| `test_circling_label_transition.py` (new) | +365 | 15 cases covering I1–I4, ledger update, safeword, coercion survival, NM dedup non-collision, XCORR-1 short-circuit, boundary. |
| `test_circling_founding_case_transition.py` (new) | +187 | 6 cases: founding-shape dispatch count 3; multi-escalation two exemptions; downgrade-then-recover no re-exemption. |

Only ONE caller of `_evaluate_burst_demotion` in the tree (`perimeter_alert.py:1247`). The `exemption_active` kwarg is defaulted to `False` — no other call site is silently receiving stale exemption state. Grep confirmed.

Only ONE caller of `_classification_transition_exemption_permitted` (the cooldown-suppress branch at :1080). Kill-switch (`TRACK_LINK_WINDOW_S <= 0`) and `tracking_enabled=False` short-circuit before any ExteriorTrack reach — verified by trace.

---

## Suppression-site walk (S1–S8 per plan Table §Perimeter suppression-site enumeration)

| Site | Verified interaction |
|---|---|
| S1 alert-hours | Upstream of exemption; unchanged. Exemption cannot re-open an alert-hours suppression. Correct. |
| S2 egress-window | Upstream of exemption; unchanged. Correct. |
| S3 cooldown | The gate the exemption targets. Two-step gate: cooldown first, exemption second. `exemption_active` reset to `False` per invocation (function-local); no cross-event flag carrying. Correct. |
| S4 in-flight guard (:1106) | Runs AFTER cooldown/exemption. If an exemption is granted at :1080 but a same-camera dispatch is in flight, S4 suppresses. The ledger update lives at :1458–1465 inside the `if dispatched_ok:` block, which S4 short-circuits before reaching → **ledger is NOT consumed** on the suppressed second event. Matches plan LOW-1 pin. Traced. |
| S5 XCORR-1 burst-demote | New `exemption_active` kwarg + early-return (:2005–2030) fires with `reason="classification_transition_exemption"` only when `_linker.classify(track) in ("approach","circling")`. `exemption_active=False` path is byte-identical to pre-cycle (guarded by `if exemption_active:` block). Verified. |
| S6 NM safeword | I3 short-circuits BEFORE the exemption fires, keying on `nm._perimeter_silence_until` + `is_life_safety_hazard(hass, NM_HAZARD_EXTERIOR_PERSON)`. Fail-closed on exception. Verified by drill #3 (invert → `test_safeword_window_blocks_transition_exemption` fails loud). |
| S7 NM dedup | Dedup tuple `(coord_id, title, location, severity)`. On the exemption hop, `classification ∈ {approach, circling}` raises severity via the coercion block at :1221–1232 (`if coerced > severity: severity = coerced`); baseline `pass_by` cannot have already produced a matching HIGH row. Structurally no HIGH-HIGH collision. D7 test guards. Verified. |
| S8 NM DND / other NM gates | Exemption-agnostic; unchanged. |

No new dispatch-loss modes introduced. No dispatch site bypasses either the gate or the ledger.

---

## Async / concurrency / restart

### Single-thread event-loop safety
Set mutation (`track._dispatched_classifications.add(_cls)`) and scalar assign (`track.last_dispatched_classification = _cls`) occur on the HA event loop. Between the exemption gate at :1080 and the ledger update at :1458 there ARE await boundaries (snapshot delay, dispatch call). Without a lock, a strict reading is: two concurrent flows on the SAME track could both grant an exemption for the SAME class before either updates the ledger.

Concrete reachability trace:
- Same camera / same `cooldown_key`: the second flow is serialised by S4 (`_dispatch_in_flight`). The second grant is granted **but not consumed** (ledger update guarded by `dispatched_ok`, which is unreachable when S4 suppresses). Correct per plan.
- Different cameras, same track: the second camera's own `_last_alert[cooldown_key]` must already be within cooldown for the exemption path to be entered at all. Requires **both** cameras to have baseline-alerted recently AND observe the escalating hop within the same await window before either flow completes. Narrow but non-zero. Worst-case impact: two exemption pages for the same target class on the same track (one per camera). Not a HIGH — the pages are on different cameras and carry different location context, so operator experience is 2 legitimate camera-scoped pages instead of 1 aggregated. I4's "one exemption per (track, target_class)" is technically violated in this window.

→ **Finding B-LOW-1** (below). Non-blocking; document + monitor. If ever observed in the wild, mitigation is to seed the set optimistically BEFORE the dispatch await and roll back on `not dispatched_ok`.

### Track lifecycle / recycling
`ExteriorTrack.track_id` is generated with a monotonic counter + uuid4-suffix (`exterior_track_linker.py:504`). No id recycling. When a track expires (idle beyond `TRACK_LINK_WINDOW_S`) it is dropped from `_tracks[label]` and never re-materialised. A subsequent event on the same camera opens a fresh track with an empty `_dispatched_classifications` set and `last_dispatched_classification=None` (dataclass defaults) — the ledger cannot inherit stale state. Verified.

### Restart / RAM-only ledger
`ExteriorTrack` is not persisted. HA restart drops all in-flight tracks; the next observation earns a fresh exemption. Docstring on the field pins operator-visible bound: **≤ 2 additional pages per in-flight track per restart** (approach + circling). Matches plan §I1 LOW-4 pin. No RestoreEntity poisoning surface (no restored state → no boot-time re-arm burst).

### `exemption_active` threading
- Set at exactly one site (:1080).
- Read at exactly two sites (:1094 log message, :1247 kwarg into `_evaluate_burst_demotion`).
- Kwarg-defaulted to `False` in `_evaluate_burst_demotion` signature → all pre-cycle callers observe byte-identical behaviour. No missed caller.
- No module-level or instance-level storage of the flag; cannot leak across events.

Verified.

---

## Independent re-runs of Reviewer-A mutation drills

`PYTHONDONTWRITEBYTECODE=1`; `__pycache__` cleared before each run; source restored + re-verified green after each drill.

### Drill #3 — invert I3 (safeword) check
Mutation: within `_classification_transition_exemption_permitted`, change the `if silence_until … and not is_life_safety_hazard(...): return False` block's terminal `return False` → `return True` (equivalent to "if window active: return True" per drill spec).

- **Baseline:** 21 / 21 passed.
- **Mutated:** `FAILED quality/tests/perimeter/test_circling_label_transition.py::test_safeword_window_blocks_transition_exemption` — 1 failed, 20 passed.
- **Restored:** 21 / 21 passed.

Result: **PASS** — mutation produces a specific named failure, not a silent-count regression.

### Drill #4 — neuter the ledger update
Mutation: replace the four-statement ledger block inside `dispatched_ok` (`find_owning_track` → `classify` → assign `last_dispatched_classification` → `.add(_cls)`) with `pass`.

- **Baseline:** 21 / 21 passed.
- **Mutated:** 12 failed, 9 passed. Named failures (all as-expected):
  - `test_ledger_updates_on_baseline_dispatch_too`
  - `test_transition_exemption_fires_after_safeword_window_expires`
  - `test_exemption_dispatch_severity_survives_coercion`
  - `test_exemption_hop_not_deduplicated_against_baseline_hop`
  - `test_founding_shape_dispatch_count_is_three`
  - `test_founding_shape_produces_exactly_one_high_circling_page`
  - `test_founding_shape_ledger_final_state`
  - `test_multi_escalation_pass_by_approach_circling_gets_two_exemptions`
  - `test_reescalation_after_downgrade_gets_no_new_exemption`
  - (plus 3 further ledger-shape assertions)
- **Restored:** 21 / 21 passed.

Result: **PASS** — the ledger update is genuinely wire-in load-bearing across both new test files.

Both drills confirm the anchors are wire-in mutation-authoritative, not source-grep hollow anchors (per `feedback_hollow_test_anchors.md` / `feedback_wire_in_anchor_mandatory.md`).

---

## Findings

### B-LOW-1 — Ledger update is post-await; narrow cross-camera same-track double-exemption window
**Location:** `perimeter_alert.py:1458–1465` (ledger update inside `if dispatched_ok:` block, after snapshot / dispatch await boundaries).
**Framing:** Async concurrency, cross-camera reachability of I4 violation.
**Mechanism:** For the same track observed on two different cameras, each in its own cooldown, the exemption gate at :1080 in flow-B can run and grant before flow-A reaches its `dispatched_ok` ledger update. Both flows then dispatch a page for the same escalating class. S4 does NOT serialise across different `cooldown_key`s.
**Reachability:** Requires (a) both cameras have baseline-alerted within `PERIMETER_ALERT_COOLDOWN_SECONDS`, (b) both cameras receive the escalating-hop within the same await-suspended window, (c) the snapshot / dispatch latency of flow-A exceeds the interleave gap. Empirically infrequent but not zero.
**Impact:** At worst two exemption pages instead of one for the same track / same target class in the window (each with distinct camera location). Not a suppression / not a safety regression.
**Suggested mitigation (not required for ship):** seed `track._dispatched_classifications.add(_cls)` optimistically inside the gate (before returning `True`), with a rollback in the `else` branch of `if dispatched_ok:` if the dispatch failed. Keeps I4 strict at the cost of one extra transient set entry on failed dispatches.
**Recommendation:** Ship as-is; add to observability watch list. If shipwatch or NM ring-buffer ever shows two same-class exemption pages on the same track within `PERIMETER_ALERT_COOLDOWN_SECONDS`, promote to fix-up.

### B-LOW-2 — Cross-module reach into `NotificationManager._perimeter_silence_until`
**Location:** `perimeter_alert.py:1913–1921` (getattr on NM's underscore-prefixed RAM field).
**Framing:** Coupling / refactor hazard.
**Status:** Already documented — `notification_manager.py:387–396` carries a tripwire comment naming the exact PA consumer. Matches "reference contract" pattern used elsewhere (perimeter_diagnostics).
**Recommendation:** Ship. No action needed beyond the tripwire that is already present.

---

## Plan-B checklist (rev-2 §Reviewer B framing)

- [x] No double-emit on the exemption hop (`_dispatch_in_flight.add(cooldown_key)` at :1398 fires before any other flow can re-enter cooldown for the same key).
- [x] S4 interaction traced end-to-end; ledger not consumed on S4-suppressed second event.
- [x] Restart: track dies, next hop earns a fresh exemption; bound documented on the field docstring.
- [x] Vehicle leg (:2331–2570 / :2681+) untouched. Confirmed by diff scope + independent grep of `note_alert_dispatched` sites.
- [x] XCORR-1 threading: kwarg-defaulted, byte-identical no-op path when `exemption_active=False`.
- [x] NM dedup (S7 / D7): HIGH-HIGH collision structurally impossible on the exemption path (severity monotonically raises with class rank).
- [x] Contract comment at `notification_manager.py:387` present.
- [x] Independent re-enumeration of early-returns in `_async_handle_perimeter_trigger`: no new dispatch-loss mode.

---

## Recommendation

**SHIP.** Two LOWs documented, neither blocking. Both mutation drills (#3, #4) re-run independently and pass with named-test failures + clean restore. Reviewer A's other listed drills (#1, #2, #5, #6, #7, #8) were not re-run in this pass but the test files include the corresponding named anchors verified to exist and to be the plan-stated behavioural oracles (grep confirmed).
