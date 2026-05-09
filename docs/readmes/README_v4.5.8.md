# v4.5.8 — Lock down signal-handler gating model (docs + regression tests)

**Date:** 2026-05-09
**Type:** Tier 1 (~30 LoC docstrings + 8 regression tests; zero behavior change)
**Predecessor:** v4.5.7

## Summary

The v4.5.7 AI / chaining audit flagged an asymmetric gating model in `coordinator.py`'s 4 signal handlers as a possible bug. User confirmed the asymmetry is **intentional design** — pausing per-room automation should not silence system-level reactions to house state or energy events, and **safety / security must NEVER be gated** by either toggle (Review fix F11).

This release captures that intent in source — explanatory comment block above the handlers, gating-aware docstrings on each handler, and 8 regression tests that pin the matrix so a future "consistency fix" can't silently regress safety.

**Zero runtime behavior change.**

## The matrix (now documented in source)

| Trigger source | Master `automation` toggle | AI automation toggle |
|---|---|---|
| Per-room occupancy / lux | gates ✓ | gates ✓ |
| `_on_house_state_changed` | does NOT gate | gates ✓ |
| `_on_energy_constraint` | does NOT gate | gates ✓ |
| `_on_safety_hazard` | does NOT gate (F11) | does NOT gate (F11) |
| `_on_security_event` | does NOT gate (F11) | does NOT gate (F11) |

Rationale, in source as a comment block:

- **Occupancy / lux** are per-room, frequent, user-driven → pausing automation should silence them.
- **House-state / energy-constraint** are system-level, rare, reactive → pausing per-room automation shouldn't silence them. The AI toggle is the right kill switch if needed.
- **Safety / security** are critical-protection signals → no toggle should silence them. A user who paused automation for the night still expects the smoke detector's notify-and-light-the-path automation to run.

## What changed

- New `GATING MODEL FOR SIGNAL HANDLERS` comment block above `_on_house_state_changed` in `coordinator.py` explaining the matrix in one place.
- Each of the 4 signal-handler docstrings now opens with `Gating: …` declaring which toggle (if any) gates it and why.

## Regression tests

8 tests in `quality/tests/test_v458_signal_handler_gating.py`:

- **Gating model (4):** house_state and energy_constraint check AI toggle but NOT master; safety and security check **neither** (the F11 invariant is the most safety-critical assertion).
- **Per-room path stays double-gated (2):** master + AI gates remain on the occupancy/lux trigger detection.
- **Documentation present (2):** the comment block exists and each handler docstring contains a `Gating:` line.

The test design is source-grep based (mirror style — same as v4.5.0.4 / v4.5.3 / v4.5.6 / v4.5.7) because the signal handlers are deeply coupled to the coordinator and pull HA imports that don't load cleanly in the test env.

**Test count progression:**
- v4.5.7: 1994 tests, 0 isolated failures across 55 files
- **v4.5.8: 2002** (+8), 0 isolated failures across 56 files

## Why this matters

The v4.5.7 audit's first reading was "safety chaining unconditionally fires — that's a bug." The reading was wrong (the comment was design intent, not a TODO), but the failure mode is real: a future contributor doing a "consistency cleanup" PR could easily add `and self._is_ai_automation_enabled()` to the safety/security handlers and silently break the F11 invariant. The 8 tests + comment block + docstrings make that regression hard to merge by accident.

This is the same defensive pattern as the v4.5.6 source-contract tests for the EC switch lifecycle and v4.5.7's solar-banking source contract: **lock down design intent in tests so future cleanups don't accidentally undo it.**

## Deploy notes

- No DB schema changes
- No migration needed
- HACS download required after deploy.sh
- HA restart not strictly required (this is docs + tests; existing runtime code unchanged) — picks up at next restart for any other reason

## Next

Returning to investigate why `cover.living_blinds` closed at 13:00 CDT today after the 6:40 AM open. User confirmed `CONF_EXIT_COVER_ACTION = "none"` for Living Room, so my exit-cover hypothesis is wrong. Needs another look.
