# Review B — safety clear-on-recovery (lifecycle / consumers / restart / no-flap)

Branch feature/safety-clear-on-recovery @ cca8826c7, base = merge-base 434d8f1f0 (verified). Targeted tests: 163 passed.

## Findings
- **LOW (latent, Bug Class: cross-coordinator consumer drift)** `notification_manager.py:3039` + `safety.py` `is_hazard_active` (~:3385). NM smoke/CO cooldown defaults to 2 min (`const.py:3357-3358`) < `HAZARD_MIN_HOLD_S`=300. Once SAFETY-NM-REFIRE-UNWIRED wires hazard_type/location, repro: smoke on -> page -> ack at t0 -> detector clears t0+30s -> cooldown expires t0+2m -> `is_hazard_active` True (hold until ~t0+5.5m) -> spurious CRITICAL re-page for a cleared detector. Inert today (safety's NotificationAction sets no hazard_type; verified, only `manager.py:1079` reads it). Must be handled on that card (hold-aware `is_hazard_active` or check `_hazard_clear_pending`). Not a ship blocker.

## Cleared
- Downstream actuators: `SIGNAL_SAFETY_HAZARD` emits only on is_new (raise); HVAC `_handle_safety_hazard` (hvac.py:6338) and coordinator automation chains are raise-edge only; no clear-driven actuation (no valve re-open). Longer active window affects display only (`sensor.py:6639/6757`, `binary_sensor.py:2494-2522`, active_hazard_count anomaly metric) — intended.
- Sweep: reuses existing 1-min `async_track_time_interval` tracked in `_unsub_listeners` (safety.py:1273); runs after the flooding guard (:2973); sync, no awaits, no new tasks. Clear lands at 300-360 s; entity update only on pop -> no boundary flap.
- Teardown / clear_all clear all three new dicts (:3044-3048, :3425-3429). Restart: ephemeral state lost; a still-wet/on sensor re-raises via normal evaluation; a hazard held at restart simply drops (same as pre-branch post-restart).
- I2 holds: life-safety raise during pending forces is_new (:2478); registration/pending-cancel precede the early return.
- Divergence (get_rate): raise path uses the same `get_rate` (:799), so ROC raises are equally rare; a raised ROC key clears ~5-6 min later via None->recovered. Absolute CO/temp keys are separate (non-:roc) and unaffected, so no real CO response lost. Re-fire spam needs get_rate non-None again (same rare condition) and is deduplicator-throttled.

## Verdict: SHIP
