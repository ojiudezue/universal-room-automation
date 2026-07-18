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

## Validated 2026-07-17 ~20:36 CDT (post-restart)

| Criterion | Result | Evidence |
|---|---|---|
| Options-flow round-trip + enable live-apply (B-HIGH-1) | **PASS both directions** | Drove the real CM options flow via API: save `baec.energy_dp_enable=true` → `switch...battery_aware_ev_charging` flipped `on` at 20:35:44 with NO reload (entry stayed `loaded`); save `false` → `off` at 20:35:53. `.storage` shows `energy_dp_enable: False`, `energy_dp_must_start_by_min: 180.0` persisted flat (no section residue). |
| Shadow eval live | PASS | `sensor.ura_energy_coordinator_ev_charging_plan` = `hold_only` with `shadow_decision: not_applicable`, `shadow_reason: outside_night_window`, `shadow_last_eval_at: 20:33:31` — correct for 20:33 (off_peak starts 21:00). Zero `drain-precedence:` actuation lines. First real shadow arithmetic visible after 21:00 tonight (organic). |
| Renames live | PASS | Registry `original_name` confirms: Decision delay · Charging time buffer · Typical charge needed — Garage A/B · Overnight house load estimate. Switch friendly name Battery-Aware EV Charging; sensor EV Charging Plan. |
| Device slim-down (one-shot registry disable) | PASS | 4 Numbers + Select set `disabled_by: user` (reversible in UI). Switch + `number...dp_must_start_by_min_past_midnight` (Latest charge start, 180) remain enabled. |
| D2 knobs | PASS-as-designed | Not yet in options (written only on first operator save; module constants serve as defaults — verified in .storage). Pre-existing `weather_divergence_threshold_f: 3.0` untouched (sibling-preservation held on a real save). |
| Regression | PASS | Zero URA ERROR entries post-restart; house_state live (`home_evening`); all 41 URA entries `loaded`. |
| Carried from v5.20.0 | **CLOSED 2026-07-17 ~21:20 (Envoy re-terminated by operator)** | Recorder exclusion PROVEN: entity live-updating since 20:36 while newest statistics row is 666 min old — states flow, statistics frozen. D2 happy path VALIDATED: `soc_resolution` tier `primary_envoy` (envoy 53 / cloud 56.2, divergence 3.2pp inactive) AND cloud-lag leg organically fired (`cloud_settings_lag_active: true` @ 2776s). |

**Addendum 2026-07-17 ~20:47: operator ACTIVATED BAEC** (switch ON).
First armed hold observed at 21:13 (`hold_only`, off_peak); first real
eval expected after the 10-min Decision delay. Shadow attrs frozen at
their last OFF-mode values, as designed.

Boot transients: none URA-attributable observed.

## Deferred / accounted
- L1 backlog: factory-switch toggles don't persist to options (pre-existing, all EC switches) — unify writeback or ratify boot authority.
- A3 accepted: config-flow writes display-lag on the 2 enabled knobs until restart (peak-buffer precedent).
- QUALITY_CONTEXT additions queued: asserted-but-untested invariant leg; prior candidates from v5.20.0 record.
