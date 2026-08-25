# AUDIT — HVAC short-cycle recorder-event fidelity (D0 gate)

**Cycle:** HVAC-ANOMALY-BLIND-1 (`docs/planning/PLANNING_hvac_short_cycle_producer.md`)
**Date:** 2026-08-24
**Gate:** D0 — probe re-run at recorder event fidelity, ±10% verdict on the
Option-(c) fixture that anchors §Design Decision and
`HVAC_SHORT_CYCLE_MIN_SAMPLES`.
**Decision:** **REVISED** — probe means diverge by 21-30% from the prior
fixture. Divergence is in the SAFE direction (means smaller → z-scores
LARGER → separation better). Thresholds re-frozen from these numbers;
**second Tier-2-DB plan review triggered** per the D0 gate rule.

---

## Probe

Script: `scripts/probes/hvac_shortcycle_daily_probe.py` (ssh-executed
against the live HAOS recorder, read-only via
`file:/config/home-assistant_v2.db?mode=ro`).

Method (verified against script source, lines cited relative to the
committed file):
- Enumerates each zone's climate `entity_id` via
  `states_meta.metadata_id` (line 8).
- Streams every recorder `states` row for that entity in `last_updated_ts`
  order, joined to `state_attributes.shared_attrs` for the JSON
  `hvac_action` value (lines 11-14).
- Treats `hvac_action in {"cooling","heating"}` as ACTIVE (line 5). A
  transition `not active → active` opens a cycle at `start=ts`; the
  matching `active → not active` closes it and computes
  `duration_min = (ts - start)/60.0` (lines 18-24).
- Bins completed cycles by calendar day of `start` (`%m-%d`); a cycle
  with `duration_min < THRESH` (10.0 min) increments that day's short-
  cycle counter (lines 20-23).
- Reports the per-day count vector, `mean`, `pstdev` (floored at 0.1),
  and the fault-day z-scores at 8 and 12 (lines 29-32).

**Fidelity equivalence to the D2 producer:** the probe iterates every
`states`-row transition of `hvac_action` in recorder order. The D2
producer subscribes via `async_track_state_change_event` to the same
three climate entities and drives its cycle-tracker off every `old→new`
`hvac_action` transition on the live bus. Recorder rows for that
attribute ARE the persisted trace of those same bus events, so the two
observation surfaces are equivalent by construction — a rate difference
between this probe and the previous fixture is a REAL RATE DIFFERENCE
(week-to-week variance / seasonal load), not a fidelity difference. This
resolves the F2 "5-min-poll aliased sub-5-min transitions" concern that
killed the v2 plan.

Window: 8 days ending 2026-08-24.

---

## Per-zone results (this probe vs. prior fixture)

| Zone | Daily counts (sub-10-min completions) | Mean | Std | Prior fixture (mean/std) | Δ mean | Δ std |
|---|---|---|---|---|---|---|
| z1 (`climate.thermostat_bryant_wifi_studyb_zone_1`) | `[0,0,2,0,1,2,0,0]` | 0.62 | 0.86 | 0.88 / 0.78 | −29.5% | +10.3% |
| z2 (`climate.up_hallway_zone_2`) | `[0,0,2,0,3,3,1,0]` | 1.12 | 1.27 | 1.50 / 1.32 | −25.3% | −3.8% |
| z3 (`climate.back_hallway_zone_3`) | `[2,0,1,3,0,0,3,2]` | 1.38 | 1.22 | 1.75 / 1.71 | −21.1% | −28.7% |

**±10% gate verdict: FAIL** — every zone's mean is 21-30% below the prior
fixture; z1 std is +10.3%, z3 std is −28.7%. The gate REQUIRES a
threshold re-derivation and a second plan review per §D0 of the plan.

**Direction of miss: SAFE.** Lower means (and, for z3, lower std) push
fault-day z-scores UP, not down — the separation Option (c) relies on
gets WIDER, not narrower. The re-derivation therefore CONFIRMS Option
(c) with more margin rather than displacing it.

Distribution shape unchanged: near-Poisson 0-3/day across all three
zones (same shape as the prior fixture); no new tail, no zero-inflation
regime that would argue for a different sampling primitive.

---

## Recomputed z-scores (frozen from D0)

Under `_MIN_VARIANCE`-floored `pstdev` (script uses `or 0.1`):

| Zone | z(day=8) | z(day=12) | Worst observed normal day | z(worst-normal) |
|---|---|---|---|---|
| z1 | (8 − 0.62)/0.86 = **8.58** | (12 − 0.62)/0.86 = **13.23** | 2 | (2 − 0.62)/0.86 = **1.60** |
| z2 | (8 − 1.12)/1.27 = **5.42** | (12 − 1.12)/1.27 = **8.57** | 3 | (3 − 1.12)/1.27 = **1.48** |
| z3 | (8 − 1.38)/1.22 = **5.43** | (12 − 1.38)/1.22 = **8.70** | 3 | (3 − 1.38)/1.22 = **1.33** |

Fault-day z ranges: **5.42-8.58** at 8 short cycles, **8.57-13.23** at 12.
Worst-normal-day z: **1.33-1.60** — all under the ADVISORY 2.0 gate on
every zone. Prior fixture's worst-normal z was 1.90 (z3), so the safety
margin under the D0 numbers is LARGER, not smaller.

Compared to the prior fixture's fault-day z-scores (z1 9.13 / z2 4.91 /
z3 3.65), z1 lands slightly lower (8.58 vs 9.13) but z2 and z3 both
improve materially (5.42 vs 4.91; 5.43 vs 3.65). No zone regresses toward
the ADVISORY floor.

---

## Option-(c) argument re-derived on the D0 numbers

Option (c) — per-zone daily observation with per-metric
`minimum_samples=HVAC_SHORT_CYCLE_MIN_SAMPLES` override — was chosen on
two grounds: (i) sampling cadence/unit match the fixture, and (ii) the
fault/normal separation is comfortable under the fixture's std. Both
grounds hold on the D0 numbers:

- Cadence/unit: producer is event-driven off `hvac_action` transitions;
  probe is event-driven off recorder `hvac_action` transitions. Same
  surface, same unit, same 1-obs-per-UTC-day-per-zone cadence.
- Separation: fault-day z ≥ 5.42 on every zone (well above CRITICAL);
  worst-normal-day z ≤ 1.60 on every zone (below ADVISORY 2.0). No zone
  is at risk of firing on the worst normal day observed in the window.

Options (a) and (b) rejection arguments are unchanged — (a)'s
variance-collapse pathology is a property of the rolling-24h sampling
shape, not the underlying rate; (b) still requires a one-sided primitive
this cycle is not building.

---

## `HVAC_SHORT_CYCLE_MIN_SAMPLES` — confirm at 14

The prior value 14 was chosen to match the ~2-week probe window that
established the baseline. Re-checked against the D0 distribution:

- Shape: unchanged (near-Poisson 0-3/day). No zero-inflated or heavy-
  tailed regime that would demand more samples for a stable mean/std.
- Fault separation at maturity: fault z-scores 5.4-13.3 across zones —
  the maturation floor does not need to be raised to guarantee a
  clean fire, and raising it defers the feature's first useful day
  without buying separation.
- Time-to-first-firing: 14 obs/zone × 1 obs/day = 14 days to activation.
  Consistent with the operator's expectation set on the card.

**Decision:** hold `HVAC_SHORT_CYCLE_MIN_SAMPLES = 14`. No shape-driven
reason to move it; confirming per the "confirm, don't assume" rule.

---

## D0 decision

- Fixture in the plan's §Design Decision is **REVISED** to the D0
  numbers above.
- `HVAC_SHORT_CYCLE_MIN_SAMPLES = 14` is **CONFIRMED** (unchanged).
- Option (c) is **CONFIRMED** with wider margin than the prior fixture
  predicted.
- **Second Tier-2-DB plan review is TRIGGERED** per §D0 ("second plan
  review required if D0 revises any threshold"). Reviewer scope:
  re-verify the §Design Decision numbers, the recomputed z-scores, and
  that D1/D2 acceptance criteria still discriminate under the new
  numbers.

Falsifier held open for post-ship monitoring (unchanged from plan): if
30 days of live rollover observations show per-zone std collapse below
0.3, the daily-sample shape is unsafe and Option (b) becomes the next
attempt. Under the D0 numbers, the minimum observed std is 0.86 (z1),
so this trip-wire is not close to firing today.
