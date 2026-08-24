# PLANNING — `short_cycle_rate` producer rebuild (HVAC-ANOMALY-BLIND-1)

**Tier:** 2-DB (elevated per standing regression-prone policy). Change extends a
shared primitive (`AnomalyDetector` gains per-metric `minimum_samples`) consumed
by 5 coordinators, decides persistence for a metric currently in
`HVAC_SUPPRESSED_FROM_PERSISTENCE`, and interacts with the latching /
`clear_active_anomalies` gap. Build v1 shipped, was killed by two disjoint
reviews — do not repeat that at Tier 2.

**Recommendation up front:** **Option (c) — per-zone daily count of sub-10-min
completed cycles, observed ONCE per calendar-day rollover, with per-metric
`minimum_samples=14` override.** Options (a) and (b) were both examined and
rejected on measured grounds; the arithmetic is in §Design Decision.

---

## Institutional context verified

Greps run (short — full art already inventoried on card `HVAC-ANOMALY-BLIND-1`):

- `HVAC_SUPPRESSED_FROM_PERSISTENCE` → `hvac_const.py:1004`, referenced from
  `hvac.py:52,1186`, primitive at `coordinator_diagnostics.py:929,942,1077`.
  **REUSED** — `short_cycle_rate` currently listed (`hvac_const.py:1006`); this
  cycle REMOVES it from the frozenset once the metric's shape is well-conditioned.
- `short_cycle_rate` producer site → **does not exist** (confirmed
  `hvac.py:3635` comment: "defined in HVAC_METRICS but never recorded"). **NEW**
  producer inside `_record_anomaly_observations()` at `hvac.py:3614`.
- Per-metric `minimum_samples` → **does not exist**; primitive has scalar
  `self.minimum_samples` at `coordinator_diagnostics.py:906`. **NEW** additive
  `minimum_samples_by_metric: Optional[Dict[str, int]] = None` kwarg with
  backward-compat default.
- `clear_active_anomalies` at `coordinator_diagnostics.py:1310` — **REUSED**,
  zero production callers; this cycle wires ONE caller (daily rollover, per-zone
  short-cycle metric only). Broad latching fix is out of scope.
- `SHORT_CYCLE_THRESHOLD_S` — **NEW** module constant in `hvac_const.py`. Knob
  ladder rung = module constant (see §Traps trap 5).
- `_MIN_VARIANCE=0.01` at `coordinator_diagnostics.py:151` — **REUSED**;
  relevant to the Option-(a) rejection arithmetic below.
- Cycle-start/end tracking → HVAC zone has `hvac_action` (`hvac.py:3658`);
  transition idle↔active is the observable. **NEW** per-zone cycle-tracker
  (start_time + `restart_epoch` stamp) lives beside existing zone state. No
  new persistence machinery — piggyback on `hvac_zone_state` (already persisted,
  see restart-safety audit F-classifications on card).

Prior planning consulted: `docs/planning/AUDIT_restart_safety_classification.md`
(the audit that re-scoped this card, denominator=2.9 restarts/day); build v1 on
branch `feature/hvac-anomaly-blind-1` (referenced, treated as superseded for D1).

Design doc: `docs/Coordinator/HVAC.md` — reviewed; no existing short-cycle spec
to reconcile with (this is greenfield producer for a declared-but-silent metric).

Probes (do not re-run): `scripts/probes/hvac_cycle_duration_probe.py`,
`hvac_shortcycle_distribution_probe.py`, `hvac_shortcycle_daily_probe.py`.

---

## Falsifiable invariant

> For every completed HVAC on-cycle whose `on_since` is later than the last
> `homeassistant_start` AND whose duration < `SHORT_CYCLE_THRESHOLD_S`,
> `_short_cycles_today[zone_id]` increments by exactly 1. For every calendar-day
> rollover, `record_observation("short_cycle_rate", zone_id, count)` fires
> exactly once per zone. No observation ever derives from a cycle whose
> `on_since` predates the last restart.

D-framing reviewer's job: find a reachable state where the counter increments
without a real short cycle, or where a real short cycle fails to increment, or
where a truncated (restart-interrupted) cycle is observed as short.

---

## Design decision — why Option (c), not (a) or (b)

Measured fixture (from probes, do NOT re-derive): per-zone daily counts of
sub-10-min cycles over 7-8 days: z1 mean 0.88 std 0.78; z2 mean 1.50 std 1.32;
z3 mean 1.75 std 1.71. A fault day of 8 short cycles → z=9.13/4.91/3.65. Worst
normal day (5, z3) → z=1.90, just under ADVISORY 2.0. Good separation.

**Option (a) — rolling-24h count observed every 5-min tick — REJECTED.**
Arithmetic: normal shape is ~1.5 short cycles/day → the rolling-24h count
CHANGES only when a cycle enters or leaves the window, ≈3 change events/day. Over
336 ticks (~28h) the baseline sees ~3-5 unique values and ~330 duplicate samples.
Variance collapses to `_MIN_VARIANCE=0.01` → std floor 0.1. With mean ≈1.5, an
observation of 5 (a normal day) → z=35 → CRITICAL. Hair-trigger, and worse than
build v1 — every routine day fires. `_MIN_VARIANCE` does NOT save this; it IS
the reason the arithmetic goes pathological. Also re-introduces build-v1
failure B2 (baseline drift as fault progresses).

**Option (b) — one observation per completed cycle, log-duration, one-sided —
REJECTED.** Requires new one-sided z-score primitive (detector uses `abs()` at
`coordinator_diagnostics.py:995`). That is a wider primitive change than we are
willing to make here. Also relies on repeated ADVISORY firings as the signal,
which pins `_active_anomalies` and makes the latching gap materially worse
(currently zero-caller `clear_active_anomalies`).

**Option (c) — per-zone daily observation, per-metric minimum_samples override
— CHOSEN.** Sampling cadence and unit MATCH the measured fixture, so the
acceptance z-scores above are exactly what the live detector will compute.
Maturation at 1 obs/day/zone: `MINIMUM_SAMPLES=336` would take 336 days — that
is why per-metric override is IN SCOPE. Set `minimum_samples_by_metric =
{"short_cycle_rate": 14}` → 2 weeks to first firing, matching the probe window
that established the fixture. Firing rate ≤1/day/zone bounds the latching blast
radius; combined with a new `clear_active_anomalies(metric="short_cycle_rate",
scope=zone_id)` call at daily rollover, latching for THIS metric is fully
contained without touching the general gap.

**Falsifier for the choice:** if 30 days of live rollover observations show
std collapse below 0.3 (probably from a run of quiet days), the daily-sample
shape is unsafe and Option (b) with a proper one-sided primitive becomes the
next attempt. Live metric attribute `expected_std` on the anomaly record makes
this observable without new instrumentation.

**In scope for this cycle:** per-metric `minimum_samples` override (additive,
backward-compat). Wiring one call to `clear_active_anomalies` at daily rollover
for `short_cycle_rate` only.
**Out of scope, explicit:** one-sided z-scoring; the general
`clear_active_anomalies` gap for other metrics; migrating other
`HVAC_SUPPRESSED_FROM_PERSISTENCE` entries; any change to `_MIN_VARIANCE`. If
deferred, the metric ships PERSISTED (removed from the frozenset) because its
per-day shape is well-conditioned (std 0.78-1.71, none near zero) — the reason
it was suppressed originally (silent, never observed) is exactly what this
cycle fixes.

---

## Deliverables

### D1 — Per-metric `minimum_samples` override (shared primitive)

Add `minimum_samples_by_metric: Optional[Dict[str, int]] = None` to
`AnomalyDetector.__init__` (`coordinator_diagnostics.py:874`). `record_observation`
consults it as `self._min_samples_for(metric_name)` returning the override or
`self.minimum_samples`. Backward compat: if arg is None, no behaviour change.

**Acceptance:**
- **Verify:** existing 5 coordinators pass unchanged when arg is None.
- **Test:** `test_anomaly_detector_per_metric_minimum_samples` — detector with
  `{"m1": 5}` fires on m1 after 5 samples, still requires 24 for m2.
- **Live:** `sensor.ura_hvac_coordinator_status` attribute
  `metric_learning_status.short_cycle_rate` transitions to `ACTIVE` after 14
  observed days, not 336.

### D2 — `short_cycle_rate` producer

New per-zone cycle-tracker in `hvac.py`: on zone `hvac_action` transition
idle→active record `(on_since=utcnow, restart_epoch=<current boot id>)`
inside `hvac_zone_state` (piggyback on the existing persisted carrier); on
active→idle, if `restart_epoch` matches current boot AND duration <
`SHORT_CYCLE_THRESHOLD_S`, increment `_short_cycles_today[zone_id]`. At
UTC-day rollover (reuse `_maybe_reset_daily_counter` cadence in
`_record_anomaly_observations`), for each zone call
`record_observation("short_cycle_rate", zone_id, float(count))`, then reset
`_short_cycles_today[zone_id]=0` and call `clear_active_anomalies(metric=
"short_cycle_rate", scope=zone_id)`. Remove `short_cycle_rate` from
`HVAC_SUPPRESSED_FROM_PERSISTENCE` (`hvac_const.py:1006`).

**Acceptance:**
- **Verify (discriminating):** synthetic day with 8 short cycles on z1 →
  ADVISORY/ALERT anomaly with `metric=short_cycle_rate scope=zone_1` (NOT
  house-wide, NOT any other zone). Distinct from build-v1 failure: 2 zones
  starting warmup simultaneously produces ZERO short-cycle observations (they
  are long cycles). This observation would look different under the wrong fix.
- **Verify (restart discard):** cycle started 10 min before HA restart, ended
  2 min after → `restart_epoch` mismatch → NOT incremented.
- **Sensor:** `sensor.ura_hvac_coordinator_anomaly` reflects the zone-scoped
  fire; `attributes.z_score` matches probe arithmetic within 5%.
- **Test:** `test_short_cycle_producer_counts_only_within_boot` (restart
  discard), `test_short_cycle_daily_rollover_emits_once_per_zone`,
  `test_short_cycle_zone_scoped_not_house_scoped`.
- **Live:** after next UTC rollover, `anomaly_log` table has ≤3 rows for
  metric=`short_cycle_rate` (one per zone, mostly NOMINAL — no anomaly rows
  until fixture matures 14 days).

---

## Traps addressed

1. **Restart mid-cycle.** Handled by `restart_epoch` stamp on cycle-tracker.
   Cycles whose start predates current boot are discarded on completion, not
   observed. At 2.9 restarts/day this is the difference between fabricating
   ~3 phantom short-cycles/day and zero.
2. **`record_observation` evaluates z BEFORE `baseline.update`.** Cited, not
   worked around: at 1 obs/day/zone a fault-day value of 8 shifts the mean by
   ~8/14 ≈ 0.57 on first fire — still fires again next day if the fault
   persists (mean would need many fault-day observations before absorption
   matters, unlike the tick-cadence catastrophe of Option a).
3. **Latching.** Firing rate ≤1/day/zone = 3/day worst case. NEW call to
   `clear_active_anomalies(metric="short_cycle_rate", scope=zone_id)` at
   daily rollover clears prior day's fire before observing the new day.
   Sufficient for THIS metric; the general gap remains carded elsewhere.
4. **Persistence gating.** Ship PERSISTED (remove from
   `HVAC_SUPPRESSED_FROM_PERSISTENCE`). Justification: measured per-day std
   0.78-1.71 is well-conditioned, unlike `zone_call_frequency`'s degenerate
   shape that motivated suppression in the first place. Max 3 anomaly_log
   rows/day worst case; typical zero.
5. **`SHORT_CYCLE_THRESHOLD_S = 600` is NEW.** Rung on the knob ladder:
   MODULE CONSTANT in `hvac_const.py`. Rationale: safety-adjacent (compressor
   short-cycling protection semantics), tuning should require code review;
   picked at 10 min against measured medians ~20-22m and sub-5min share
   2.7-4.8% → 10-min threshold captures ~3.7-9.7% of cycles as "short",
   including the 5-min band that a 5-min knob would miss. Not exposed to
   options flow — an operator who legitimately needs to tune this is doing a
   review-worthy change (the metric's whole calibration depends on it).

---

## Non-goals (explicit)

- General `clear_active_anomalies` wiring for other metrics.
- One-sided z-score primitive.
- Migrating `zone_call_frequency` or `comfort_deviation_hours` off suppression.
- Exposing `SHORT_CYCLE_THRESHOLD_S` as a Number entity.
- Any change to `_MIN_VARIANCE`.
- The declaration-tag doctrine work (F1/F2/F5/F6/F8/DailyCounter) from the
  restart-safety audit — separate cycle.

---

## Plan Completion Tracking (to fill at cycle close)

- [ ] D1 shipped as specified? If not, what changed and why?
- [ ] D2 shipped as specified? Zone-scoped fire confirmed live?
- [ ] `short_cycle_rate` removed from `HVAC_SUPPRESSED_FROM_PERSISTENCE`?
- [ ] Rollover `clear_active_anomalies` call wired?
- [ ] Any deferrals beyond the stated Non-goals — list here.
- [ ] README `Validated <date>` table filled with observed z-scores from first
      real firing (may be up to 14 days post-deploy; note if pending).
