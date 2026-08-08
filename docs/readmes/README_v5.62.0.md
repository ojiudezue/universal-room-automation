# URA v5.62.0 — Verifiable allowlist install + override expiry warning

Two backlog-depleting fixes found during v5.61.0's live validation. **Tier 2** (two disjoint reviews
+ orchestrator drills). Reviews: A = correctness/timer lifecycle (SHIP, 2 LOW), B = test authority
via mutation drills (1 HIGH + 3 MEDIUM, all fixed).

## BOOTSANITY-1 — the allowlist guard can now actually fire, and the install is observable

**Problem:** v5.61.0 added a boot-sanity WARNING to detect a failed linker-allowlist install — but it
ran at the end of `PerimeterAlertManager.async_setup()`, gated on the linker being present, at the
exact moment the linker isn't registered yet (that ordering *is* the bug it guards). So it could
never fire on a cold boot, and its silence was meaningless. Live validation nearly recorded that
silence as proof of success.

**Fix:** the sanity check now also runs inside the `SIGNAL_EXTERIOR_LINKER_READY` handler, *after*
the install attempt, so a failed install warns on the path that matters. The end-of-setup check is
retained for the warm-reload case (distinct paths; cannot double-warn spuriously).

**New live instrument:** `allowlist_installed` (bool) and `allowlist_camera_count` (int) on
`ExteriorOpenTracksDiagnosticSensor` — the install is now verifiable from a sensor rather than
requiring log-level surgery.

## OVERRIDE-NOTIFY-1 — tell the operator before the override lapses

**Problem:** v5.61.0 gave the Temp Arrester Override a correct release contract but never told the
operator it was about to release — the override silently vanished and the setpoint drifted back.
Operator: *"The only real optimization is getting a text that says your override is about to expire
5 mins before a boundary."*

**Fix (three parts — a 5-minute pre-warning is only possible for *predictable* expiries, since house
state transitions are not scheduled):**
1. **Pre-warn the 6h decay** — one-shot timer at `COMFORT_OVERRIDE_MAX_S − ARRESTER_OVERRIDE_EXPIRY_WARN_S`
   (new rung-1 constant, 300s; `0` disables; guarded against `WARN_S ≥ MAX_S`).
2. **Warn on deferral** — when the MIN_LIFE grace defers a sunset, notify immediately with the real
   remaining minutes ("context changed; ends in ~N min"). This gives *more* notice than 5 minutes and
   covers the unschedulable state-transition case.
3. **Notify on release** — verified to fire exactly once per engagement across all four release paths
   (timer discharge, sweep, state-transition, max-age), deduped by engagement id.

Timer cancelled on manual OFF, every release path, re-engage, and `teardown()`.

## Review findings

| ID | Sev | Finding | Fixed |
|---|---|---|---|
| B-HIGH | HIGH | **Hollow anchor, 3rd recurrence.** The diagnostic-attr test grepped `sensor.py` for the key names and separately drove a real linker — the halves never connected. Keeping the keys but detaching their values from the linker left the suite **GREEN**, so the "verifiable install" instrument wasn't pinned to what it reports. | ✅ behavioral test asserts both attrs TRACK linker state (False/0 → True/3) |
| B-MED | MED | Collection-order `ImportError`: this file's `homeassistant.core` stub lacked `CALLBACK_TYPE`, and `setdefault` doesn't merge, so a sibling's stub was discarded. Full-suite alphabetical order masked it. | ✅ stub completed; both orders proven green |
| B-MED | MED | Re-engagement pre-warn dedup not independently pinned (`_last_expiry_warned_engagement_id` is a separate variable from the sunset dedup) | ✅ `test_prewarn_refires_on_reengagement` |
| B-MED | MED | Deferral-cancels-pre-warn not pinned | ✅ extended defer test asserts the unsub fired |
| A-LOW-1 | LOW | Dedup stamped *before* the callback-exists check → an unregistered callback would mark the engagement "warned" with nothing sent and no retry | ✅ reordered: warned iff notified |
| A-LOW-2 | LOW | WARN_S=0 kill-switch path unpinned | ✅ test added |

## Orchestrator-verified drills

| Site | Mutation | Result |
|---|---|---|
| `sensor.py` attrs | **keys kept, values detached from linker** (compiles clean — the shape that slipped through 3×) | **RED** |
| pre-warn dedup | engagement-id → boolean "already warned" latch | RED |
| defer branch | remove `_cancel_expiry_warn_timer()` | RED |
| WARN_S guard | `if True:` (ignore the 0/misconfig guard) | RED |

A first attempt at the detach drill went red on an `IndentationError` from a sloppy edit — that
proved nothing and was redone cleanly (compiles, keys present, only values constant) before being
accepted. Mis-aimed drills are not evidence.

## Gate

Full suite **21 failed / 8390 passed / 45 skipped**; time-matched failing-name diff vs develop
**empty** (the 2 extra baseline failures earlier tonight were `TestBillingRestoreDaily`, which is
wall-clock-coupled via `datetime.now().date()` — verified by reproducing them on unmodified code).
Both test-file collection orders green. py_compile + conflict grep clean.

## Acceptance criteria

- **Live (the point of BOOTSANITY-1):** post-restart, `sensor.ura_security_coordinator_outside_open_tracks_diagnostic`
  shows `allowlist_installed: true` and `allowlist_camera_count` matching the configured perimeter +
  egress camera count. This is the check v5.61.0 could not make.
- **Live:** no `SECC-1 class regression suspected` WARNING in the log after boot.
- **Live (organic):** engage the override → a "~5 minutes remaining" note arrives before the 6h decay;
  a context change inside the grace produces an immediate "ends in ~N min" note.

## Live Validation

(prospective — replaced with the Validated table post-restart)
