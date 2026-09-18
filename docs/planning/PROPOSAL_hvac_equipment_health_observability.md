# PROPOSAL — HVAC Equipment-Health Observability + Closed-Loop Tuning

**Date:** 2026-09-17 · **Status:** possibilities capture (unshipped — no version) · **Card:** `HVAC-EQUIPMENT-HEALTH-OBSERVABILITY-1`
**Origin:** surfaced out of the Bryant duty-cycle audit (`AUDIT_bryant_duty_cycle_redundancy_2026_09_17.md`) + live reads 2026-09-17.
**Doctrine:** measure-first (every item below is gated on a read-only probe); do NOT build while the D5 reframe is in flight.

## What we found (live, enabled — measure-first already cleared existence)

`ha_carrier` publishes a rich per-thermostat telemetry stream URA does not consume today:

- **ODU Status** (`sensor.thermostat_bryant_wifi_<loc>_odu_status`, `sensor.office_b_odu_status`): state = `off / Stage 1..5` (the real compressor **duty**, staged not %), plus attributes `suction_pressure`, `suction_temperature`, `suction_superheat`, `discharge_temperature`, `outdoor_coil_temperature`, `line_voltage`, `static_pressure`, `blower_rpm`. Live example: `office_b` = **Stage 5**, superheat 16°, discharge 149°F, line 251 V.
- **IDU Status** (`..._idu_status`): `operational_status` (furnace stage), `airflow_cfm`, `static_pressure`, `blower_rpm`.
- **`..._filter_remaining`** (e.g. 60): filter life countdown.
- Per-zone **`*_cooling_energy_*`** (yesterday / last_month / yearly): actual HVAC energy.

**Home for consumers:** `SafetyCoordinator.SAFETY_METRICS` (safety.py:904 — already registers metrics, emits anomalies, tracks a `degraded` state) + the shared anomaly engine (`anomaly_event.py` / `coordinator_diagnostics.py`) → NM. Same path as the existing `short_cycle_rate`.

---

## Possibilities — priority order (value × certainty × leverage)

### P1 — Equipment-health anomaly detection → SC + anomaly → NM  *(highest value, lowest risk, additive)*
Alert the owner to equipment **degradation** the Infinity board silently rides over. "Impossible for most homeowners; trivial for an engine that baselines." Three sub-detectors:
- **Refrigerant/compressor:** `suction_superheat` (low → liquid floodback risk; high → low charge/airflow), `discharge_temperature` (high → overheat/low charge), suction pressure.
- **Airflow / dirty filter:** `static_pressure` UP **cross-corroborated** with `filter_remaining` DOWN (two signals agreeing = a confident dirty-filter call, few false alarms) + `airflow_cfm`.
- **Electrical:** `line_voltage` brownout / overvoltage.

**Measurements that gate it (P1-probe):** (a) the *theory of not-great-state* — see §Theory; (b) baseline this house's per-stage/per-outdoor-temp distributions from recorder history to set alert thresholds; (c) false-alarm rate on a replayed week.
**Risk:** low (observation only, no actuation). **Effort:** medium.

### P2 — Reset-vs-nudge measurement → possibly KILL resets  *(strongest decision-driver; re-litigates S14 + informs the D5 reframe on evidence)*
Test the hypothesis: a **reset** (force-away) slams the compressor **off**, which then **restarts at Stage 5** — the short-cycle we don't want — whereas a **nudge** (small setpoint bump) lets it **modulate down a stage** (5→3) gracefully. If true, that's the empirical case to stop using force-away resets (D5's force-away *is* a reset; S14 was a nudge-style hold that got torn out).

**Measurements that gate it (P2-probe):**
- Correlate URA's action log (reset/force-away vs nudge events) against **ODU Stage transitions** in the following minutes: does reset → `off` then `Stage 5` restart (short-cycle) vs nudge → `Stage 5→3` glide?
- **DATA GAP found 2026-09-17:** zone_1 shows 86 preset_change (resets/flaps) in 3d but the action inventory shows **NO nudge/ramp/setpoint-named rows** — so either nudges aren't firing on zone_1 lately or they're logged under a different action name / elsewhere. **First sub-probe: locate where nudges are logged.**
- Passive-first; **live A/B available** — operator cleared a controlled Zone-1 reset (2026-09-17) if the passive signal is ambiguous: one force-away, watch ODU stage ~15–20 min, restore.
**Risk:** passive = none; live A/B = one controlled comfort blip on Zone 1 (authorized). **Effort:** low (probe) / policy change medium.

### P3 — Closed-loop energy attribution + knob tuning
Combine ODU **stage** (instantaneous duty) + `*_cooling_energy_*` + URA action log → **measure** whether vacancy-retreat / coast / pre-cool / D5 actually save kWh, turning open-loop "we think this saves" into "this saved X," and **tune the knobs to measured energy** instead of assumption.
**Measurements that gate it (P3-probe):** per-behavior kWh delta (behavior-on vs comparable behavior-off windows), controlling for outdoor temp; a signed, defensible savings figure per lever.
**Risk:** low (measurement → informs tuning). **Effort:** medium-high (attribution is fiddly).

### P4 — Re-ground D5 duty estimate on ODU Stage  *(lowest — folds `HVAC-D5-REGROUND-ON-ODU-VAR-1`)*
Replace D5's coarse 20-min `hvac_action` on/off integral with the real ODU **Stage** (a unit modulating at Stage 2 ≠ one cycling on/off). Modest, because the reframed D5 already won't fire on occupied zones; do it only if P1/P2 data shows the coarse integral visibly mis-estimates on a staged unit.
**Measurement that gates it:** compare the 20-min integral vs the stage-integral over history; is the divergence large enough to change a shed decision?
**Risk:** low. **Effort:** low.

---

## Theory of "not-great-state" (honest — the research did NOT establish this)

The Bryant research confirmed the *signals exist*; it did **not** establish normal/abnormal ranges. The theory is two-tier:

1. **Hard physical limits** (equipment/refrigerant-specific — VERIFY, do not assert):
   - `line_voltage`: US split-phase ~240 V nominal; ~216–252 normal, brownout well below (<~210), overvoltage above ~264.
   - `static_pressure`: residential total external ~0.5" WC target; >~0.8 signals restricted airflow. *(office_b IDU already read 0.86 — worth a look.)*
   - `discharge_temperature`: a real overheat ceiling exists (low charge / failing) — equipment-specific.
   - `suction_superheat`: a **floor** matters (too low → floodback, compressor killer); high → low charge/airflow.
2. **Self-baselined anomaly** (the powerful part): superheat / suction / static are all conditional on stage + outdoor temp + load. No single "good" number — learn **this unit's** distribution (superheat @ Stage 5 @ 82°F ODT) and alert on drift. Requires the recorder-history baseline probe.

---

## Measurements catalog (read-only probes; each feeds a decision)

| Probe | Feeds | Question it answers | Status |
|---|---|---|---|
| Hard-limit research (equipment/refrigerant) | P1, Theory | What are the absolute danger thresholds? | not run |
| Recorder baseline (per-stage/per-ODT distributions) | P1, P4 | What is normal for THIS house, so what is drift? | not run |
| Reset-vs-nudge ↔ ODU-stage correlation | P2, D5 reframe, S14 | Do resets short-cycle worse than nudges? | started — action-name gap found |
| Nudge-logging locator | P2 | Where are nudges recorded? | **first sub-probe** |
| Per-behavior kWh attribution | P3 | Does each URA lever actually save energy? | not run |
| Stage-integral vs hvac_action-integral divergence | P4 | Is re-grounding D5 worth it? | not run |

## Sequencing / non-goals
- **Measure-first:** no wiring/build until the gating probe for that item returns. This doc + card hold the plan.
- **Not now:** do NOT build while the D5 reframe (`feature/hvac-d5-reframe`) is in review. This is the follow-up workstream.
- **One workstream, not a card flurry** (operator directive 2026-09-17): the P1–P4 items live as a checklist inside `HVAC-EQUIPMENT-HEALTH-OBSERVABILITY-1`, not as separate cards. `HVAC-D5-REGROUND-ON-ODU-VAR-1` (parked) folds into P4.

## Open questions
- Where are nudge/ramp writes logged (action-name gap)?
- One outdoor unit per zone, or shared? (3 zones; tonnage 4/3/3 → likely ≥2 ODUs — confirm for per-unit baselining.)
- Does a live A/B reset add enough over the passive natural experiment to be worth the comfort blip? (Decide after the passive correlation.)
