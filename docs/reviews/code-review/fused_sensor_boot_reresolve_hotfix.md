# Fused-Sensor Boot Re-Resolve — Hotfix Review Record (shipped v5.46.1)

Bug found during v5.46.0 live validation: `CameraPersonDetectedSensor` cached
an empty camera resolution computed before Frigate/Protect finished booting;
no retry path existed — sensor + fan-veto camera leg inert every restart.

Two framing-disjoint reviews (autonomous-mandate protocol):
- **A (correctness)** — SHIP-WITH-FOLLOWUP. MED: guard only fired on totally
  empty resolves; a PARTIAL resolve (one platform up) never re-joined → fixed:
  re-resolve unconditionally at STARTED. LOW: `is_running` is True during
  CoreState.starting → fixed: `hass.state is CoreState.running`. LOW: nil the
  unsub first in the callback (error-path double-unsub spam) → fixed. LOW:
  callback churn if lifecycle beat it → superseded by the MED fix (partial
  resolves make unconditional re-resolve the point); documented.
- **B (lifecycle + test authority)** — SHIP. Two independent source mutations
  red (guard inversion 3-fail, cache-clear removal 1-fail), byte-identical
  restore. Accepted residuals: platform still not ready at STARTED = one-shot
  spent (recovery: reload the room entry; bounded-retry rejected as overbuild);
  one-tick removal race leaks at most one listener (commented in code).

Orchestrator drill: re-adding the emptiness gate → 2 tests failed; restored.
Tests: 7 source anchors (instantiation infeasible under the harness — Bug
Class #62 disclosure in the module docstring). Suite: 7926/34 baseline, zero
drift. Live validation: autonomous re-resolve confirmed on first boot (see
README_v5.46.1.md).
