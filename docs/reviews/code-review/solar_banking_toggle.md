# Code Review — Solar HVAC Banking Toggle

**Branch:** `feature/solar-banking-toggle` (4ff0377 build → 682b269 fix-up)
**Plan:** `docs/planning/PLANNING_solar_banking_toggle.md` · **Protocol:** Tier 1 (single adversarial review) · **Date:** 2026-06-11

**Operator trigger:** banking fires every good-solar day, pins HVAC, drives energy use; needs an easy off from the EC device.

## Build notes
EC-device "Solar HVAC Banking" switch (default ON) via `_ec_switch_factory`, `CONF_HVAC_SOLAR_BANK_ENABLED`, gate in `HVACPredictor._check_pre_conditioning`, `banking_enabled` attr beside `solar_banking_zones`. The opus builder **falsified the plan's "mid-bank release is free" claim** during implementation (the `_last_emitted_range` throttle blocks preset re-emits) and built an explicit release path — which the review then found wrong in a deeper way.

## Findings ledger
| ID | Sev | Finding | Bug class | Status |
|---|---|---|---|---|
| C1 | CRITICAL | Release wrote `zone.target_temp_*` — refreshed each cycle from LIVE thermostat state, so post-banking "baseline" IS the banked value → release was a no-op re-write; house stays over-cooled | #7 wrong data source | FIXED (682b269) — release sources `HVACCoordinator._last_emitted_range` (true URA-emitted baseline) via a predictor backref, preset-resolved fallback, throttle map synced post-release |
| H1 | HIGH | Restart mid-bank with gate restored OFF → in-memory `_last_banked_zones` lost → thermostats stuck banked (DPM throttle sees "no change") | #32-adjacent unpersisted actuation state | FIXED — one-shot startup reconciliation: gate OFF + live setpoint >0.5°F below baseline → release, INFO log |
| M1 | MEDIUM | Per-cycle re-snapshot emptied the tracked set when the banking window closed (hour≥14) — operator's most likely flip moment released nothing | Tracking lifecycle | FIXED — zones tracked from bank until explicit release or live-setpoint-vs-baseline prune (live comparison, since banking bypasses the throttle map) |
| M2 | MEDIUM | Helper text implied the options field is authoritative; RestoreEntity actually wins post-install (sibling-EC semantics) | Doc honesty | FIXED — helper text states switch is authoritative at runtime |
| L1/L2 | LOW | `blocking=False` try/except can't catch service failures (mirrors existing pattern); style nit on an unconditional local import | — | ACCEPTED |
| — | NOTE | Banking ratchets toward the floor across cycles because it reads live (already-banked) setpoints — pre-existing, flagged in code comment | #7 | BACKLOG |

**Verified clean:** flip state machine; live-read `banking_enabled` (#14); translations; tests drive the real `_check_pre_conditioning` with setdefault-only mocks.

## Statistics
CRITICAL 1/1 · HIGH 1/1 · MEDIUM 2/2 fixed · LOW 2 accepted · 1 backlog note. Suite: 5596 passed / 44 failed / 14 errors — empty failure-diff vs fresh develop baseline (main-session verified); 18 cycle tests.

## QUALITY_CONTEXT note
Reinforces #7 with a precise trap: **"baseline" read from live device state after you've written to the device is your own write echoed back.** Any release/undo path must source from a URA-side record of what it emitted (here: `_last_emitted_range`), never from the entity it just mutated.
