# Code Review — CENSUS-FACE-RESOLVER-MIGRATE-1 (face resolver in presence)

**Tier:** 1 (hotfix — one file production change, additive path, ~14 LoC).
**Branch:** `feature/face-resolver-migrate` @ `0c6c8bd37`.
**Diff base:** `develop`.
**Verdict:** **SHIP-WITH-FIX** (LOW/MED only; no CRIT/HIGH).

## Summary

`PresenceCoordinator._get_face_for_camera` (presence.py:4536) previously
hard-built `sensor.{base}_last_recognized_face`, silently missing the
`_2`-suffix-only face sensors that exist post-Frigate-1 retirement
(memory: "frigate 1 retired 2 suffix"). The fix routes lookup through
the shared `camera_census._resolve_face_entity_id` (camera_census.py:2509),
with a fallback to the bare canonical id when `hass.data[DOMAIN]["census"]`
is not yet wired. Behavior change: v3.19.0 face-confirmed arrival now
fires on `_2`-only cameras.

## Verification checklist

### 1. Fallback fail-mode — census reliably present?

`hass.data[DOMAIN]["census"]` is set unconditionally in
`__init__.py:2234`, inside the main `async_setup_entry` flow OUTSIDE the
`tracked_persons` block. It is torn down in `__init__.py:4597`.
Camera-driven `_handle_camera_state_change` callbacks that reach
`_get_face_for_camera` cannot be registered before the platform setup
completes, and the camera_manager+census block runs before the presence
coordinator finishes wiring listeners. **Under normal operation census
will be present.** A narrow early-boot race window (unavailable→on
transition arriving between `hass.data[DOMAIN]` seeding and the census
init line) is theoretically possible but is degenerate to pre-fix
behavior — **no regression**. LOW at worst.

### 2. `_resolve_face_entity_id` contract

Confirmed at camera_census.py:2509-2542: returns `str` (canonical or
`_2` variant) or `None`, prefers canonical, skips any variant in
unavailable/unknown/empty/none. Fail-closed on missing state. On a full
miss, increments `self._face_lookup_missing_count`.

Frigate-1-retired concern (canonical would be dead, `_2` alive): resolver
skips canonical when its state is unavailable/unknown → returns `_2`.
Correct for the failure mode the memory documents.

### 3. Blast-radius

Only one caller of `_get_face_for_camera` in the repo
(presence.py:4525). It feeds `_handle_face_arrival`, a strictly
additive v3.19.0 path (extra fire only, no suppression). Broadening the
set of resolvable cameras is the intent. No trust-decision demotion
depends on this returning None.

### 4. `except Exception` swallow

Fail-closed to `None`, then falls through to the bare-string branch.
Face rec is documented as accelerator-only. Acceptable **except** for
the interaction with finding M1 below (masks a rename regression
silently).

### 5. Test authority

Tests drive the production `_get_face_for_camera` via `MethodType`
binding — correct. Mutation anchor (revert to bare-string build) would
fail `test_face_resolver_finds_suffix_only_camera` because the state map
has no canonical entry. Coupling holds.

**However**, tests inject a hand-rolled `_Census` stub that
re-implements the resolver contract rather than importing the real
`PersonCensus._resolve_face_entity_id`. See M1.

## Findings

### M1 — Test uses a hand-rolled resolver stub instead of the real `PersonCensus` (MEDIUM)
- **Bug class:** Hollow test anchors / test-authority gap (memory:
  "hollow anchors").
- **File:** quality/tests/test_face_resolver_migrate.py:44-70
  (`_make_census` — reimplements resolver semantics).
- **Failing scenario:** if `_resolve_face_entity_id` is ever renamed,
  refactored to a different signature, or moved off `PersonCensus`,
  presence.py:4573 raises `AttributeError`, is swallowed by the broad
  `except Exception` at :4574, and the fallback bare-string branch
  silently restores pre-fix behavior (`_2`-only cams miss again). No
  test in this cycle catches that — the stub always answers correctly.
- **Fix:** (a) add a lightweight smoke assertion that the real
  `PersonCensus` exposes `_resolve_face_entity_id` (attribute presence +
  signature), OR (b) instantiate real `PersonCensus` with a stub
  `camera_manager` and drive `_get_face_for_camera` through it.

### L1 — Broad `except Exception` masks AttributeError specifically (LOW)
- **Bug class:** Overbroad exception swallow (adjacent to M1).
- **File:** custom_components/universal_room_automation/domain_coordinators/presence.py:4574.
- **Failing scenario:** compounds M1 — any rename/removal of the
  resolver becomes silent. A narrow `except (LookupError, ValueError,
  TypeError)` (or explicit `AttributeError` allowlist that logs at
  DEBUG) would surface the regression class.
- **Fix:** either narrow the exception, or leave broad but log at DEBUG
  with `exc_info=True` on the first miss per boot so a live grep can
  detect it.

### L2 — Diagnostics-metric shape change: `_face_lookup_missing_count` now includes presence-driven lookups (LOW)
- **Bug class:** Metric-semantics drift (not a correctness bug).
- **File:** custom_components/universal_room_automation/camera_census.py:2541 (increment site) — now hit from presence.py:4573 too.
- **Impact:** `face_lookup_missing_count` (exposed via camera_census.py:1288)
  previously tracked census's own per-tick sweep only; it now
  additionally increments on every presence camera-state-change that
  fails to resolve a face sensor. Rate change, not shape change. If
  operators alert on this metric, expected level shifts up. Doc-only.
- **Fix:** either accept the change (recommended — the metric arguably
  becomes more useful) and note in the README, or introduce a caller
  tag if fine-grained attribution is wanted later. No code fix needed
  for correctness.

## Recommendation

SHIP-WITH-FIX on M1 (small; ~10 LoC of test): add a real-`PersonCensus`
attribute smoke check to the cycle test file so the resolver-migration
cannot silently regress via rename. L1 optional but cheap. L2
documentation-only.

The core production change is correct, narrowly scoped, and correctly
fail-closed. No CRIT/HIGH findings. No new bug classes for
QUALITY_CONTEXT.md.

## Summary table

| Severity | Count | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 0 | – | – |
| HIGH | 0 | – | – |
| MEDIUM | 1 | pending (M1) | – |
| LOW | 2 | optional (L1), doc-only (L2) | – |

| Bug class | Count |
|---|---|
| Hollow test anchors / test-authority gap | 1 |
| Overbroad exception swallow | 1 |
| Metric-semantics drift | 1 |
