# URA v5.21.0 — Battery-Aware EV Charging Control Surface + D2 Knob Promotion

Follow-on to v5.20.0 (same day). All settings reachable from the Coordinator
Manager's ⚡ Energy options step; shadow-eval observability while the feature is
OFF; operator-facing names throughout. Review record:
`docs/reviews/code-review/v5_21_0_baec_control_surface.md` (2 HIGH found/fixed, SHIP).

## What ships
1. **Energy options step gains a "Battery-Aware EV Charging" section** (toggle +
   Latest charge start) with a collapsed **Advanced (rarely change)** apron
   (Decision delay · Charging time buffer · Typical charge needed — Garage A/B ·
   Overnight house load estimate). Flatten-on-save; sibling sections
   (inclement, cloud verification) preserved.
2. **Enable toggle applies live** in both directions (options save → coordinator
   + switch entity push via SIGNAL_ENERGY_ENTITIES_UPDATE; switch flip unchanged).
3. **Cloud-verification section gains the D2 detection knobs** (rung-1 → rung-2):
   Battery level disagreement alert (pp, 0 = off) · Disagreement confirmation
   time (min) · Cloud update delay alert (s, 0 = off). Constants remain the
   defaults; kill semantics unchanged.
4. **Shadow eval:** with the switch OFF, `sensor.ura_energy_coordinator_ev_charging_plan`
   now carries `shadow_decision` / `shadow_reason` / `shadow_last_eval_at` /
   `shadow_last_eval_snapshot` — what BAEC *would* have decided, zero actuation
   (INV-BAEC-SHADOW, mutation-enforced incl. zero-DB-write leg). Rate-limited
   INFO log (300s).
5. **Device slim-down:** 4 advanced Numbers + Select → diagnostic category,
   disabled-by-default for new installs; live house slimmed via one-shot
   registry disable at deploy (reversible in the UI).

## Live Validation (prospective — write back post-restart)
- **Live:** ⚡ Energy options step opens; BAEC section + Advanced apron render; save round-trips (spot: set Decision delay 11 → coordinator attr `dp_eval_delay_min` 11 without reload; revert to 10).
- **Live:** toggling enable in the options flow flips `switch...battery_aware_ev_charging` state without restart (then revert OFF).
- **Live:** `ev_charging_plan` sensor shows `shadow_*` attrs populated within one decision cycle during off_peak (or `not_applicable/outside_night_window` during day); switch stays OFF; zero `drain-precedence:` actuation lines.
- **Live:** cloud_verification section shows the 3 new knobs at defaults 10/5/(lag default); `soc_resolution` attr unaffected.
- **Live:** one-shot registry disable executed for the 4 Numbers + Select; device page shows only the switch + Latest charge start (+ diagnostic entities hidden).
- **Live (carried from v5.20.0):** recorder-exclusion definitive proof + D2 happy-path tier once Envoy recovers.
- **Regression:** zero URA ERROR post-restart; inclement + cloud oracle options unchanged in `.storage` before/after a BAEC-section save.

## Deferred / accounted
- L1 backlog: factory-switch toggles don't persist to options (pre-existing, all EC switches) — unify writeback or ratify boot authority.
- A3 accepted: config-flow writes display-lag on the 2 enabled knobs until restart (peak-buffer precedent).
- QUALITY_CONTEXT additions queued: asserted-but-untested invariant leg; prior candidates from v5.20.0 record.
