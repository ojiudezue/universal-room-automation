# URA v5.101.3 — Suppression observability, routine-shift discharge, camera stuck trip-wire

**Shipped:** 2026-09-14
**Tier:** 2 (three independent cards; one touches perimeter alerting, one the optimizer cycle,
one a diagnostic sensor query)
**Cards:** CIRCLING-SEVERITY-1 · ROUTINE-DETECTOR-NO-DISCHARGE-1 · CAMERA-STUCK-SENSOR-TRIPWIRE-1

All three are **additive**: no control-flow change to alerting, no change to any actuation path.

---

## D1 — Perimeter alerts now record WHY they were suppressed

A live circling track had `alert_count=0` (no dispatch), and a code trace isolated the cause to
**one of two gates that both returned silently** — egress suppression and the per-camera
cooldown. Code reading cannot tell them apart retrospectively, and the card's original plan
(raise log levels and wait for a recurrence) is soak-watching, which doctrine forbids.

Both gates now record a `reason` before returning, **reusing the burst path's existing
`decision["reason"]` idiom** in the same file rather than inventing a second vocabulary. Surfaced
as `attrs["suppressions_by_camera"]` on the exterior open-tracks diagnostic sensor, alongside the
existing `burst_demotions_by_camera`.

The cooldown record also carries `exemption_offered` / `exemption_granted`, because "the
classification-transition exemption was offered and declined" is a **different diagnosis** from
"the exemption was never reachable" — and that distinction is the discriminator the trace needed.

### Acceptance criteria
- **Verify:** no control-flow change — the recorder runs immediately before an existing `return`.
- **Test:** reasons are distinguishable; the cooldown record carries exemption state; the
  recorder never raises (it runs on a live suppression path).
- **Test:** WIRE-IN ANCHOR — a helper-only test stays green if the call sites are never added.
- **Live:** the next suppressed track reports `reason` = `egress_suppression` | `cooldown`.

---

## D2 — Routine-shift events now discharge on return-to-stable, and the sensor is recency-bounded

**The defect.** The detector's in-memory cell counter always reset correctly when a cell returned
to stable — but the `anomaly_log` rows it emitted had **no automatic clear path**, only a manual
button. Measured 2026-09-14: **462 rows, 462 unacknowledged since 2026-05-15, zero ever
acknowledged**, while **all 48 cells read `stable`**. The household routine sensor had therefore
been reporting `major_shift` for four months, driven by three severity-4 rows from May.

**Fix 1 — discharge at the seam.** A new DAO clears that cell's open rows, called from the same
place that already resets the counter. **Scoped to the one cell**, deliberately not a bulk ack — a
bulk clear would also discharge cells that are still genuinely drifting. The payload shape the
query depends on was verified against live rows before the query was written.

**Fix 2 — recency bound (the operator's requirement).** The sensor query had **no time filter at
all**: `recovery_at IS NULL` and nothing else, with the only pruning at 365 days. So one
unacknowledged row pinned the sensor for up to a year. The query is now bounded to
`ROUTINE_STATUS_RECENCY_DAYS = 56` — tied to the detector's own 56-day baseline, because a shift
older than one baseline window was computed against data that has itself aged out and cannot
describe current routine.

**Effect: acknowledging becomes OPTIONAL rather than mandatory.** Forgetting the button is no
longer a year-long stuck state. The button still works for clearing early.

### Acceptance criteria
- **Verify:** a cell returning to stable clears only its own rows.
- **Verify:** a still-drifting cell is NOT discharged.
- **Test:** 9 behavioural tests (the pre-existing regime tests in this repo are source greps).
- **Test:** no pointless DB write when a cell is already stable — guards against re-creating the
  row flood v5.101.1 B2 removed.
- **Live:** person/household routine sensors stop reporting `major_shift` on May-dated rows.

---

## D3 — Exterior camera stuck-ON trip-wire

A camera's person sensor sat pinned ON for **29.5 hours** and nothing noticed. `sensor_health`
**structurally cannot** catch this: it is ROOM-keyed — all 7,970 of its findings in a month
targeted rooms — so a camera `binary_sensor` is outside its target universe and no threshold
change there would ever help.

New `camera_stuck` evaluator in the optimizer cycle:

- **Threshold derived from measurement**, not invented: over 2026-09-06..09-14 every
  non-pathological exterior detector's p99 ON-duration was ≤ **355 s** and the fleet max was
  1562 s. `CAMERA_STUCK_ON_THRESHOLD_S = 1800` sits ~5× above the worst non-pathological p99.
  Backtested over that window it fires **exactly twice** — the two real incident sensors — and
  zero times spuriously on the other twelve.
- **Per-camera overrides** so one pathological camera cannot set the fleet bound: `garage_a`
  7200 s (interior-facing egress with a real 3.9 h dwell), `pool_equipment` 28800 s (quarantined;
  it was firing 25 periods over 1 h in 7.9 days). *The operator rebooted `pool_equipment` on
  2026-09-14 — if it self-corrects, REMOVE that override rather than leaving a blind spot. That
  instruction is in the constant's comment.*
- **Volume-safe:** a latch emits at most one finding per camera per stuck episode, so it cannot
  re-create the flood B2 removed. The latch clears on recovery so a genuine re-stick alerts again.
- **Config-following:** cameras are resolved from the live perimeter + egress config lists, not a
  hardcoded list that would silently rot when a camera is added — exactly what happened to the
  egress list.

### Acceptance criteria
- **Verify:** fires only past threshold; once per episode; re-arms on recovery.
- **Verify:** per-camera override prevents a false fire on a long legitimate dwell.
- **Test:** WIRE-IN ANCHOR — the evaluator must be registered in the cycle's evaluator table; an
  unregistered evaluator never runs no matter how correct it is.
- **Live:** a stuck exterior sensor produces one `sensor_health` finding naming the camera.

---

## Verification performed pre-deploy

| Check | Result |
|---|---|
| Conflict markers | none |
| `compileall` | rc=0 |
| perimeter + optimizer + linker | **230 passed** |
| regime discharge + energy TOU (`.venv-ha`) | **51 passed** (later 9 + 203) |
| D1 mutation — change the egress reason string | anchor RED → restored, residue 0 |
| D2 mutation — neuter the discharge call | 2 tests RED → restored, residue 0 |
| D2 mutation — drop the recency predicate | **initially GREEN (hollow anchor)** → anchor hardened → RED |
| D3 mutation — unregister the evaluator | anchor RED → restored, residue 0 |
| D3 mutation — remove the once-per-episode latch | test RED → restored, residue 0 |

**A hollow anchor was found and fixed during this cycle.** The first recency wire-in test asserted
a bare substring (`"AND timestamp >= ?"`) over the whole module — but `sensor.py` contains **three**
queries with that string, so deleting the routine-status predicate left the test green. It was
rewritten to isolate the `routine_shift` SELECT and assert the predicate inside *that* statement,
then re-drilled to RED. Recorded because it is the exact defect class this repo's rules warn
about, written by the author of those warnings.

---

## Not in this release / withdrawn

- **A recommendation to sweep seven cameras from threshold 0.7 → 0.6 is WITHDRAWN.** It rested on
  an agent-reported figure ("98–99% of genuine detections score below 0.70") that the operator
  disputes from direct knowledge of their infrastructure, and that I could not reproduce — the
  Frigate events DB is not reachable from the deploy host and HA stores only the resulting
  binary_sensor state, never per-event scores. Tracked as FRIGATE-THRESHOLD-CLAIM-DISPUTED-1 with
  the single query that would settle it.
- **The 462-row backlog is not cleared by this release.** The discharge only fires on a *future*
  return-to-stable. The recency bound will stop those May rows driving the sensor once they age
  past 56 days, and the acknowledge button clears them immediately if wanted.
- **Producer-level Frigate staleness check** — the real 29.5 h incident was a fleet-wide producer
  freeze (two cameras 11 minutes apart, both ending the same second), which one producer-level
  detector would catch faster than fourteen per-sensor ones. Left as a follow-up; the per-sensor
  wire also catches the chronic single-camera case a producer check would miss.

---

## Live Validation — to be completed post-restart

- [ ] D1 — `suppressions_by_camera` attribute present on the exterior open-tracks sensor
- [ ] D2 — routine sensors no longer pinned by May-dated rows
- [ ] D3 — `camera_stuck` evaluator runs without error; no spurious findings on healthy cameras
