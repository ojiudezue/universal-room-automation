# URA v5.86.0 — Measure before you fix: nudge-restore telemetry + stale-camera visibility

Two cards, one deploy. Both are **observability**: they instrument known defects so the fixes that
follow have a real before/after instead of a claim. Neither changes control behaviour.

## HVAC-GOVERNED-EXCURSION-1 · D1 — paired immediate/settled restore verdict

**The defect being instrumented** (not fixed here): a soft-nudge cycle makes two raw setpoint
writes, and on a Carrier/Bryant a raw setpoint write flips `preset_mode` to `manual`. The
preset-preserving restore has an ordering race — the setpoint restore is `blocking=False` and the
preset write follows immediately, so a cloud-polled thermostat can land them out of order (observed:
a 509 ms clobber that took zone 1 to `manual` for 14 h 35 m). It also self-disarms: the snapshot is
skipped when the zone is *already* `manual`, so once the race is lost the restore can never recover.
This runs **31–43 times/day/zone**.

**What shipped:**
- `ac_ramp_events` gains `preset_before` / `preset_after` / `mode_before` / `mode_after` /
  `restore_ok` / `restore_ok_immediate`, via guarded per-column `ALTER TABLE ADD COLUMN`
  (metadata-only; instant on the 1.18 GB production DB; `effective` semantics untouched).
- **Paired sampling.** An immediate post-restore read, plus a passive re-read
  `AC_NUDGE_RESTORE_SETTLE_DELAY_S` (12 s, module constant) later that updates the settled verdict.
  This is the load-bearing design decision: an *instantaneous* read sees the preset correctly
  restored and misses the 509 ms clobber — it would have reported success in exactly the failure
  case we are counting. **`immediate=1` + `settled=0` is the clobber signature.**
- The settled callback issues zero service calls, adds no `await` to the restore path, cancels on
  teardown and on re-nudge, and scopes its UPDATE with `AND restore_ok IS NULL` so it can never
  overwrite a later nudge's verdict. Unreadable state writes `NULL`, never a guess.
- `mode_before` / `mode_after` are a deliberate **tripwire on the axis we chose not to migrate**.
  The mode axis was hardened in v4.7.32 and has 11 `hard_reset_started` rows with 11 matching
  `hard_reset_completed`, zero orphans — so it is excluded from the excursion migration on evidence.
  Instrumenting it makes that exclusion checkable rather than assumed.

## EGRESS-CAMERA-DEAD-CONFIG-1 — stale configured cameras become visible

**Two of five egress cameras resolved to nothing** — `camera.garage_a` / `camera.garage_b` are dead
Frigate-1 names (retired 2026-08-13; the live entities carry the permanent `_2` suffix). They
contributed **zero** person-detection to egress, on the house's primary entry route, while emitting
2,030 identical warnings per five hours.

- **Warn-once per entity**, re-armed on entity-registry change — the flood stops without the fact
  being hidden.
- **Diagnostic surface**: `unresolved_configured_cameras` + `_count` on `sensor.persons_in_house`
  (chosen because it already hosts the peer `stuck_cameras` attribute and the camera manager sees
  all three configured lists).
- **No automatic `_N` suffix substitution** — an explicit non-goal, asserted by test. Silently
  trusting a camera the operator did not configure is the failure mode; prior art already flags
  suffix guessing in the other direction as a latent hazard.
- **Sweep** (`docs/planning/AUDIT_stale_entity_references.md`): 42 config entries, 19 entity-shaped
  keys, 28,524 registry entities. **Exactly 2 stale references system-wide**, both known. The
  Frigate-retirement damage is contained.

## Verification

- **Name-diff vs v5.85.1 baseline, full suite, run serially: empty in both directions.**
  141 failed / 9234 passed / 17 errors vs baseline 141 / 9215 / 17. The 141 pre-existing failures
  are the known order-pollution issue and reproduce identically without these changes.
- Mutation drills on every wire-in, both directions, each failing a *named* test: nudge-started
  telemetry, nudge-restored telemetry, settled-timer scheduling, settled-timer teardown, the
  `IS NULL` UPDATE guard, warn-once dedup, the diagnostic call site, scope-slice pruning, and
  cross-scope non-clobbering.

### Two integration-only findings worth recording

**A regression that neither agent could see.** `test_v4512_observability` asserted against a
**fixed-size source slice** of `__init__`; D1's new timer dict pushed the target past the window.
It surfaced *only* in the central integrated run — each branch was clean alone. Rather than widen
the window a third time (its own comment records a prior 6000→8000 widening), the slice is now
**bounded by structure**: from `def __init__(` to the next method at class-body indent. Mutation-
verified afterwards — renaming the init assignment still fails 8 tests, so the repair is structural
without being hollow. Dozens of these fixed-window slices remain suite-wide (one file has 8);
recorded as evidence on `TEST-STRATEGY-REARCH-1`.

**A rejected suggestion.** The coordinator proposed threading a `scope=` kwarg through
`resolve_configured_cameras`; the builder tried it, found it regressed **33 census tests** because
shared stub fixtures mimic the old signature, and chose a sibling `record_unresolved_for_scope`
method with a `hasattr`-guarded call site instead — smaller surface, and correct-by-construction for
stubs. The evidence-backed rejection was the right call.

## Acceptance criteria

- **Verify:** integration loads, zero URA ERROR lines, all coordinators up.
- **Live (egress, discriminating):** after the config repoint to `_2`, `sensor.persons_in_house`
  attribute `unresolved_configured_cameras_count` reads **0** and the list is empty. Checking that
  the warning stopped is necessary but NOT sufficient — the count returning to zero is what proves
  coverage came back rather than the message being silenced.
- **Live (D1, organic):** within a few hours, `ac_ramp_events` rows carry non-NULL `preset_before` /
  `preset_after` / `restore_ok_immediate` / `restore_ok`. **All-NULL means the telemetry is not
  wired** — that is the shape this deliverable exists to disprove.
- **Live (D1, the real prize):** at least one row showing `restore_ok_immediate=1` with
  `restore_ok=0` — the first direct measurement of the clobber, and the before-number for D2.
