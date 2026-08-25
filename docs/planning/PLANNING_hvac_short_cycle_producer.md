# PLANNING — `short_cycle_rate` producer rebuild (HVAC-ANOMALY-BLIND-1)

**Tier:** 2-DB (elevated per standing regression-prone policy). Change extends a
shared primitive (`AnomalyDetector` gains per-metric `minimum_samples` AND a
new filtered `clear_active_anomalies` variant) consumed by 6 coordinators,
decides persistence for a metric currently in
`HVAC_SUPPRESSED_FROM_PERSISTENCE`, introduces the first zone-scoped metric on
a detector whose status surfaces are house-scoped, and interacts with the
latching gap. Build v1 shipped, was killed by two disjoint reviews; the v2
plan was killed by a Tier-2-DB plan review; the v3 plan was killed by a
SECOND Tier-2-DB plan review (post-D0) — see fix-up logs at the bottom.

**Recommendation up front:** **Option (c) — per-zone daily count of
short-cycle completions, driven by an event listener on climate `hvac_action`,
observed ONCE per calendar-day rollover, with a per-metric
`minimum_samples=HVAC_SHORT_CYCLE_MIN_SAMPLES=14` override.** Options (a) and
(b) were rejected on measured grounds; arithmetic in §Design Decision.
Fixture numbers are **REVISED per D0** (2026-08-24 recorder-event probe;
see `docs/planning/AUDIT_hvac_shortcycle_recorder_fidelity.md`). The
±10% gate FAILED (means 21-30% low) BUT the shift is in the SAFE
direction (separation improves); Option (c) HOLDS with more margin.
Second Tier-2-DB plan review triggered per the §D0 gate. The F2
(Nyquist / fidelity) concern is RESOLVED — producer
(`async_track_state_change_event` on `hvac_action`) and probe (recorder
`states`-row transitions on `hvac_action`) share the same event surface
by construction, so the D0 rate difference is real week-to-week
variance, not a fidelity artefact.

**Clock convention (post-second-review):** the entire cycle — invariant,
tracker state, rollover, acceptance — is stated in **LOCAL time** (the
system's TZ, via `dt_util.now()`). Rationale: the enclosing rollover
branch at `hvac.py:1290-1292` uses `dt_util.now()` (local), and the D0
fixture is local-day binned (`hvac_shortcycle_daily_probe.py:20` uses
`datetime.fromtimestamp`, which returns local naive). Any UTC framing in
earlier drafts is superseded; there is no "same UTC clock as
`rollover_if_needed()`" — those sibling counters use their OWN internal
UTC keys, which is a distinct clock the short-cycle rollover deliberately
does NOT share (see §D2 pseudocode guard).

---

## Institutional context verified

Greps run (short — full art already inventoried on card
`HVAC-ANOMALY-BLIND-1`; every citation below re-verified this pass):

- `HVAC_SUPPRESSED_FROM_PERSISTENCE` at `hvac_const.py:1004`, imported at
  `hvac.py:52`, passed at `hvac.py:1186`; filter machinery at
  `coordinator_diagnostics.py:929,942,1080,1128`. **REUSED** — this cycle
  REMOVES `short_cycle_rate` from the frozenset once the metric's shape is
  well-conditioned and its daily rollover clears prior fires. **De-suppression
  consumer enumeration (Producer/Consumer rule):** removing the metric from
  the frozenset changes what `_persisted_active_anomalies()`
  (`coordinator_diagnostics.py:934-947`) returns — which in turn feeds
  (a) `get_worst_severity()`'s worst-of scan, (b) the `active_anomalies`
  scalar in `get_status_summary()` (`:1138`), (c) the per-coordinator
  HVAC anomaly sensor whose `state` derives from `get_worst_severity()`
  and whose attributes reflect the persisted-active count, and (d) the
  notification path that consumes that sensor's severity transitions.
  Acceptance criterion added in §D2 that reads back-to-back the sensor's
  severity + `active_anomalies` under a synthetic short-cycle fire.
- `short_cycle_rate` producer site → **does not exist**
  (`hvac_const.py:994-995`, `hvac.py:3635-3637`). **NEW** producer.
- Per-metric `minimum_samples` → **does not exist**; primitive has scalar
  `self.minimum_samples` at `coordinator_diagnostics.py:906`, read at
  `:994`, `:1057`, `:1118`, `:1135`, `:1149` (five sites — F5). Four
  are behavioral reads that must be re-routed through
  `self._min_samples_for(metric_name)`; the fifth (`:1135`) is a
  scalar-shape-preserving display field that MUST keep
  `self.minimum_samples` (§D1a table). **NEW** additive
  `minimum_samples_by_metric: Optional[Dict[str, int]] = None` kwarg
  with backward-compat default.
- `clear_active_anomalies` at `coordinator_diagnostics.py:1310` —
  **REUSED-UNCHANGED**: existing zero-arg method preserved
  (clears ALL active anomalies for the detector) so no caller is silently
  re-scoped. **NEW** sibling method
  `clear_active_anomalies_filtered(metric_name: Optional[str] = None,
  scope: Optional[str] = None)` — filters by either/both; kwargs-only so
  callers can't be confused with the unfiltered variant. Wired at exactly
  one production caller (daily rollover, per-zone short-cycle metric).
  Broad latching fix out of scope.
- `SHORT_CYCLE_THRESHOLD_S` — **NEW** module constant in `hvac_const.py`.
  Knob-ladder rung = module constant (§Traps §5).
- `HVAC_SHORT_CYCLE_MIN_SAMPLES` — **NEW** module constant in `hvac_const.py`
  beside `HVAC_ANOMALY_MIN_SAMPLES` (`hvac_const.py:1012`). Knob-ladder rung
  = module constant (per-metric maturation floor; changing it changes the
  arithmetic underpinning firing separation — code-review-worthy).
- `_MIN_VARIANCE=0.01` at `coordinator_diagnostics.py:151` — **REUSED**;
  relevant to Option-(a) rejection.
- Cycle-start/end tracking → today HVAC reads `hvac_action` on the 5-min
  decision tick (`hvac_zones.py:444`, called from `hvac.py:1308` inside
  `_run_decision_cycle`). That fidelity ALIASES sub-5-min transitions
  (F2). **NEW** producer uses `async_track_state_change_event` on the
  three zone climate entities to capture every idle↔active transition;
  listener unsubs appended to the existing
  `self._unsub_listeners` list (`hvac.py:851`, populated across
  `hvac.py:934-980`) which is drained by `self._cancel_listeners()`
  (`base.py:282-289`) called from `async_teardown` at
  `hvac.py:3936`. **REUSED** — no new teardown primitive.
- Status surface callers of the HVAC detector: `base.py:252` and
  `manager.py:899` both call `get_status_summary()` with no scope arg,
  defaulting to `"house"` (`coordinator_diagnostics.py:1103`). No caller
  passes a zone-scoped scope. **F6 fix:** make `get_status_summary` build a
  per-metric-scoped view for metrics whose scope-vocabulary is zonal
  (§D1b).
- Coordinator count using `AnomalyDetector`: 6 — HVAC, presence, safety,
  security, notification_manager, and CM's `setup_anomaly_detector`
  (`manager.py:232`). Corrects the v2 plan's "5". Backward-compat
  contract must hold for all six.
- `DailyCounter(persist=True)` at `coordinator_diagnostics.py:794-804`
  **raises NotImplementedError**. F4 note: persisted `_short_cycles_today`
  CANNOT use the DailyCounter primitive today; it uses a per-zone dict
  piggybacked on `hvac_zone_state` (already persisted via
  `HVACZones.snapshot`, called out in `DailyCounter`'s own deferral docstring
  at `coordinator_diagnostics.py:803`).
- `restart_epoch` / `boot_id` → does not exist in the repo. F4 fix: DROP
  entirely; the redesign persists the COUNTER and keeps `on_since` in
  memory (§D2 and §Traps §1).
- `_last_daily_reset` init: `""` at `hvac.py:421`; assigned to
  `today` inside the daily-reset branch at `hvac.py:1292-1293`; the field
  is **NEVER persisted** — no `_zone_state_store` payload key, no
  `RestoreEntity` scope, no attribute save. Consequence: on every restart
  the first `_run_decision_cycle` sees `_last_daily_reset == ""` and
  enters the daily-reset branch UNCONDITIONALLY (~2.9 times/day at the
  measured restart rate). This is load-bearing for the §D2 pseudocode's
  guard: the short-cycle rollover MUST NOT be gated on
  `_last_daily_reset`; it MUST use the tracker's OWN persisted
  `_short_cycles_today_date` as the rollover key (mirroring how
  `_vacancy_sweeps_today.rollover_if_needed()` no-ops via its OWN
  internal date). See §D2 pseudocode.
- Snapshot cadence + staleness: zone-state snapshot writes every 5
  decision cycles (~25 min) at `hvac.py:1437-1445`, plus one on
  `async_teardown` at `hvac.py:3941-3943`. On load,
  `restore_state_snapshot` SKIPS any snapshot whose `saved_at` is >4h
  old (`hvac_zones.py:663-672`). Two bounded loss windows for the
  persisted counter therefore exist: (a) up to ~25 min of counter
  increments between save cycles are lost on an unclean crash;
  (b) outages >4h drop the whole pre-outage counter as stale. The
  invariant (§Falsifiable invariant) is scoped to name these windows
  explicitly rather than promising loss-free restart survival — a
  dedicated per-metric store is deferred to a carded follow-up (see
  §Non-goals and §Plan Completion Tracking).

Prior planning consulted: `docs/planning/AUDIT_restart_safety_classification.md`
(the audit that re-scoped this card) and
`docs/planning/AUDIT_hvac_shortcycle_recorder_fidelity.md` (the D0
recorder-event fidelity probe that revised §Design Decision numbers,
2026-08-24). Denominator "2.9 restarts/day" is carried on card
`HVAC-ANOMALY-BLIND-1` itself as a measured value (see card's
`CYCLE_DURATION_PROBE_2026_08_23_DECIDES_THE_REDESIGN` +
`DURATION_ZSCORE_IS_ALSO_BLIND_2026_08_24` entries) — cite the card, not
the audit (F3 provenance).

Design doc: `docs/Coordinator/HVAC.md` — reviewed; no existing short-cycle
spec to reconcile with (greenfield producer for a declared-but-silent metric).

Probes (existing): `scripts/probes/hvac_cycle_duration_probe.py`,
`hvac_shortcycle_distribution_probe.py`, `hvac_shortcycle_daily_probe.py` —
all read the recorder at full fidelity. **§D0 was run 2026-08-24** at
recorder-event fidelity; results and decision recorded in
`docs/planning/AUDIT_hvac_shortcycle_recorder_fidelity.md`.

---

## Falsifiable invariant (rewritten per second plan-review, F-invariant)

> For each zone `z` and each **LOCAL calendar day** `d`, `record_observation(
> "short_cycle_rate", zone_id=z, value=count_z_d)` is invoked **exactly
> once** on the FIRST decision cycle whose local date differs from
> `_short_cycles_today_date`, where `count_z_d` equals the number of
> climate-`hvac_action` completed on-cycles for `z` whose start-to-end
> duration was strictly less than `SHORT_CYCLE_THRESHOLD_S`. Every real
> short cycle observed by the `async_track_state_change_event` listener
> AND whose completion was captured in a snapshot that survived restart
> loads (see below) contributes to exactly one `count_z_d` (the local
> day of the completion). No truncated (restart-interrupted) cycle
> contributes to any `count_z_d`; and no observation is emitted for a
> `(z, d)` pair more than once (even across ~2.9/day restarts).

**Bounded loss windows explicitly permitted (not a violation):**
1. **Save-cadence window** — counter increments that occurred within the
   last ~25 min before an unclean crash MAY be lost, because the
   persisted snapshot is refreshed every 5 decision cycles at
   `hvac.py:1437-1445` (plus one on clean `async_teardown`). Clean
   shutdown always saves.
2. **Stale-snapshot window** — outages >4h drop the entire pre-outage
   counter for `d` because `restore_state_snapshot` refuses snapshots
   with `saved_at` >4h ago at `hvac_zones.py:663-672`. The emitted
   `count_z_d` on the post-outage day equals only the post-load
   increments.

Any subsequent cycle that widens either window (dedicated per-metric
store, or lowering the 4h threshold) is a follow-up card, not this cycle.

Reviewer-D framing job (Tier-2-DB plan review): find a reachable state
where (a) `count_z_d` differs from the ground-truth number of real
short-cycle completions on `z` during `d` OUTSIDE the two named loss
windows; (b) the daily observation for `(z, d)` is skipped or
double-emitted (e.g. by any restart-only rollover path — F-restart,
F7); or (c) a truncated cycle is counted.

This quantifies over the EMITTED DAILY OBSERVATION, not just the
counter increment, so restart-loss of the counter (v2 plan's hole) and
restart-double-emit of a partial-day observation (v3 plan's hole) are
first-class failures of the invariant.

---

## Design decision — why Option (c), not (a) or (b)

**FIXTURE FROZEN FROM D0 (2026-08-24).** Numbers below are the recorder-
event fidelity probe results from
`docs/planning/AUDIT_hvac_shortcycle_recorder_fidelity.md` (8-day window
ending 2026-08-24). The producer in D2 is event-driven
(`async_track_state_change_event`) and shares the same event surface as
the probe by construction — F2 (Nyquist / sampling-fidelity) is
resolved. The ±10% gate FAILED (means 21-30% low relative to the prior
fixture; z3 std −28.7%) BUT the miss is in the SAFE direction:
smaller means → LARGER fault-day z-scores → wider separation. The
Option-(c) argument is re-derived below on the D0 numbers and STILL
HOLDS with more margin. Second Tier-2-DB plan review triggered per the
§D0 gate rule.

Measured fixture (D0 recorder-event probe, 2026-08-24, 8-day window):
per-zone daily counts of sub-10-min completed cycles:

| Zone | Daily counts | mean | std | Worst normal day | z(worst-normal) | z(fault=8) | z(fault=12) |
|---|---|---|---|---|---|---|---|
| z1 | `[0,0,2,0,1,2,0,0]` | 0.62 | 0.86 | 2 | 1.60 | **8.58** | **13.23** |
| z2 | `[0,0,2,0,3,3,1,0]` | 1.12 | 1.27 | 3 | 1.48 | **5.42** | **8.57** |
| z3 | `[2,0,1,3,0,0,3,2]` | 1.38 | 1.22 | 3 | 1.33 | **5.43** | **8.70** |

Fault-day separation: z ≥ **5.42** on every zone at 8 short cycles,
z ≥ **8.57** at 12. Worst-normal-day z ≤ **1.60** on every zone — all
under the ADVISORY 2.0 gate. Distribution shape unchanged from the
prior fixture (near-Poisson 0-3/day); no new tail or zero-inflation
regime. **Rounding note (LOW):** z-scores above are recomputed from the
table's already-rounded mean/std, not from the raw D0 series; the sign
of every separation conclusion is robust to that rounding but exact
z-scores may differ by ~0.05 vs a from-raw recompute.

**Option (a) — rolling-24h count observed every 5-min tick — REJECTED.**
Arithmetic: normal shape is ~1 short cycle/day → the rolling-24h count
CHANGES only when a cycle enters or leaves the window, ≈2 change events/
day. Over 336 ticks (~28h) the baseline sees ~3-5 unique values and
~330 duplicate samples. Variance collapses to `_MIN_VARIANCE=0.01` → std
floor 0.1. With mean ≈1, an observation of 5 (a normal day) → z=40 →
CRITICAL. Hair-trigger. `_MIN_VARIANCE` does NOT save this; it IS the
reason the arithmetic goes pathological. Also re-introduces build-v1
failure B2 (baseline drift as fault progresses). Rejection is a property
of the sampling shape, not the underlying rate, so the D0 numbers do
not change this conclusion.

**Option (b) — one observation per completed cycle, log-duration,
one-sided — REJECTED.** Requires new one-sided z-score primitive
(detector uses `abs()` at `coordinator_diagnostics.py:995`). Wider
primitive change than we are willing to make here. Also relies on
repeated ADVISORY firings as the signal, which pins `_active_anomalies`
and worsens the latching gap.

**Option (c) — per-zone daily observation with per-metric
`minimum_samples=14` override — CHOSEN.** Sampling cadence and unit
MATCH the (event-driven) D0 fixture. Maturation at 1 obs/day/zone:
`HVAC_ANOMALY_MIN_SAMPLES=336` would take 336 days — that is why
per-metric override is IN SCOPE. Set `minimum_samples_by_metric =
{"short_cycle_rate": HVAC_SHORT_CYCLE_MIN_SAMPLES}` (=14) → 2 weeks to
first firing. Firing rate ≤1/day/zone bounds the latching blast
radius; combined with a new
`clear_active_anomalies_filtered(metric_name="short_cycle_rate",
scope=zone_id)` call at daily rollover, latching for THIS metric is fully
contained without touching the general gap.

**`HVAC_SHORT_CYCLE_MIN_SAMPLES = 14` — CONFIRMED on time-to-usefulness
grounds.** The D0 window is 8 days (AUDIT:50) — SHORTER than 14 — so
"14 matches the fixture window" is false and has been removed. The
value is chosen on time-to-usefulness alone: 2 weeks to first
firing balances (a) enough samples for a stable per-zone mean/std to
form under the near-Poisson 0-3/day shape, against (b) the cost of
deferring the feature's first useful day. Raising it defers first-fire
without buying separation (fault z at maturity is already ≥ 5.42);
lowering it risks a premature fire on a small sample of quiet days.
Confirming per the "confirm, don't assume" rule.

**Epistemics disclosure (n=8):** the D0 probe is an 8-sample window per
zone. An 8-sample window cannot statistically support both "the mean
shift is a REAL rate difference" AND "the std shift is shape-unchanged"
as strong claims — both shifts are within sampling error. The
substantive claim is weaker and sufficient: **at n=8 either reading
(D0 fixture or prior fixture) is safe for the Option-(c) decision** —
fault separation remains z ≥ 5.42 on every zone under D0 and z ≥ 3.65
under the prior fixture, both well above CRITICAL, and worst-normal-day
z remains under ADVISORY under both. The decision is robust either way.

**Falsifier for the choice:** if 30 days of live rollover observations
show std collapse below 0.3 on any zone (probably from a run of quiet
days), the daily-sample shape is unsafe and Option (b) with a proper
one-sided primitive becomes the next attempt. `expected_std` on the
anomaly record + the `metrics.short_cycle_rate.std` field in the
detector's `get_status_summary()` make this observable without new
instrumentation. Under the D0 numbers the minimum observed std is
0.86 (z1), so this trip-wire is not close to firing today.

**In scope:** per-metric `minimum_samples` override (additive,
backward-compat); new filtered `clear_active_anomalies_filtered` variant
(additive, backward-compat); zone-scope exposure of the detector's status
surfaces for metrics whose scope vocabulary is zonal; event-driven cycle
listener; module constants `SHORT_CYCLE_THRESHOLD_S` and
`HVAC_SHORT_CYCLE_MIN_SAMPLES`.
**Out of scope, explicit:** one-sided z-scoring; the general
`clear_active_anomalies` gap for other metrics; migrating other
`HVAC_SUPPRESSED_FROM_PERSISTENCE` entries; any change to `_MIN_VARIANCE`;
any change to the zero-arg `clear_active_anomalies` semantics; a
dedicated per-metric persistence store (loss-window bounds accepted).

---

## Deliverables

### D0 — Probe re-run (blocks D1/D2 threshold freeze) — **DONE 2026-08-24**

Ran `scripts/probes/hvac_shortcycle_daily_probe.py` against the live
HAOS recorder at native `hvac_action` state-change fidelity for an
8-day window ending 2026-08-24, per zone.

**Result:** ±10% gate **FAILED** on means (z1 −29.5%, z2 −25.3%,
z3 −21.1%) but the miss is in the SAFE direction (separation improves).
Distribution shape unchanged. Option (c) confirmed with wider margin.
`HVAC_SHORT_CYCLE_MIN_SAMPLES = 14` **CONFIRMED** (time-to-usefulness
grounds, not window-matching). §Design Decision numbers **REVISED** to
the D0 fixture and recomputed z-scores. Second Tier-2-DB plan review
**TRIGGERED** per the D0 gate rule.

**Artifact:** `docs/planning/AUDIT_hvac_shortcycle_recorder_fidelity.md`
(per-zone table, recomputed z-scores, verdict, decision).

**Fidelity note (F2 closure):** producer and probe share the same event
surface — the producer subscribes to `hvac_action` via
`async_track_state_change_event`, the probe iterates every recorder
`states` row for `hvac_action`. Recorder rows persist the same bus
events the producer listens to, so a rate divergence between probe and
prior fixture is a REAL rate difference (week-to-week variance), not a
fidelity artefact.

### D1a — Per-metric `minimum_samples` override (shared primitive)

Add `minimum_samples_by_metric: Optional[Dict[str, int]] = None` to
`AnomalyDetector.__init__` (signature line at
`coordinator_diagnostics.py:876`; the `def __init__` header spans
:874-:882). Add helper `def _min_samples_for(self, metric_name: str)
-> int` that returns
`self._min_samples_by_metric.get(metric_name, self.minimum_samples)`.

**Route FOUR of the five existing reads of `self.minimum_samples`
through the helper. The fifth (`:1135`) is a scalar-shape-preserving
display field and MUST stay `self.minimum_samples` (backward-compat for
existing consumers of the summary dict):**

| # | file:line | Site | Intent under override | In drill? |
|---|-----------|------|-----------------------|-----------|
| 1 | `coordinator_diagnostics.py:994` | `record_observation` gate | Use per-metric threshold — the write-side gate that decides whether to evaluate anomaly for THIS metric. | YES |
| 2 | `coordinator_diagnostics.py:1057` | `get_learning_status` per-metric loop | Use per-metric threshold when counting `active_metrics` — otherwise a metric with a lower override that has matured would be counted as still learning, keeping the detector stuck. | YES |
| 3 | `coordinator_diagnostics.py:1118` | `get_status_summary` `active_count` | Use per-metric threshold — display consistency with (2). **Zone-scoped-metric semantics:** for a scoped metric (`short_cycle_rate`), a metric is COUNTED-ACTIVE in `active_count` when EVERY listed zone-scope has met the per-metric threshold. Once-per-metric (not once-per-zone) so the "N/M metrics active" ratio remains keyed on `metric_names`, matching today's shape. Enforced via D1b's `metric_scopes` vocabulary; see the "all-scopes gate" test in D1b. | YES |
| 4 | `coordinator_diagnostics.py:1135` | `get_status_summary` top-level `minimum_samples` field | **KEEP self.minimum_samples verbatim.** Existing consumers read this as the scalar house default; changing it to a per-metric value would break every consumer of the summary dict. The per-metric information surfaces via a NEW sibling field `minimum_samples_by_metric` (dict, empty when override unused) so dashboards/tests can read the overrides without breaking existing shape. | **NO — dedicated shape-preservation test instead** |
| 5 | `coordinator_diagnostics.py:1149` | Per-metric `active` bool in `metrics` sub-dict | Use per-metric threshold — the per-metric `active` flag must reflect the metric's OWN maturation, not the house default (otherwise short_cycle_rate would show `active: false` for 336 days despite having matured at 14). | YES |

Backward-compat contract for all 6 coordinators that instantiate the
detector (HVAC `hvac.py:1177`, presence, safety, security, NM, CM's
`setup_anomaly_detector` at `manager.py:232`): if
`minimum_samples_by_metric` is None (default), `_min_samples_for` returns
`self.minimum_samples` and every read site behaves exactly as today.

**Acceptance:**
- **Verify (mutation drill — FOUR sites):** replace
  `self._min_samples_for(name)` with `self.minimum_samples` at each of
  sites #1, #2, #3, #5 in turn; the corresponding named test must FAIL
  on each mutation. Site #4 is EXCLUDED from the drill because the
  correct behavior at :1135 KEEPS `self.minimum_samples`, so a mutation
  to `self.minimum_samples` is a no-op that no test can be expected to
  fail on. Any drill-included site whose mutation leaves the test green
  is not covered → add a dedicated per-site assertion.
- **Verify (site #4 shape-preservation, separate from mutation drill):**
  `test_status_summary_scalar_field_unchanged` (see below) asserts the
  invariant for site #4 directly by shape (top-level `minimum_samples`
  is scalar and equal to `self.minimum_samples`, and the new
  `minimum_samples_by_metric` field is present).
- **Test:** `test_anomaly_detector_per_metric_minimum_samples` — detector
  with `metric_names=["m1","m2"]`, `minimum_samples=24`,
  `minimum_samples_by_metric={"m1": 5}`: after 5 observations of m1 the
  detector's `get_status_summary()` reports `metrics.m1.active == True`
  and `get_learning_status()` counts m1 as active; m2 requires the full 24.
- **Test:** `test_anomaly_detector_backward_compat_none` — with
  `minimum_samples_by_metric=None`, existing 6-coordinator
  instantiations behave byte-identically (assert `_min_samples_for("x")
  == self.minimum_samples` for arbitrary `x`).
- **Test:** `test_status_summary_scalar_field_unchanged` — top-level
  `minimum_samples` field is the scalar house default AND equals
  `self.minimum_samples`; new `minimum_samples_by_metric` field is
  present (may be empty dict). This is site #4's dedicated coverage.
- **Live:** `sensor.ura_hvac_coordinator_status` attribute
  `metrics.short_cycle_rate.active` transitions to `True` after 14
  observed days per zone (see D1b for the zone-scoped exposure — this
  bullet is discriminating because the current value is `False` and no
  other change would flip it).

### D1b — Zone-scope exposure of status surfaces (F6)

Today `get_status_summary(scope="house")` and `get_learning_status(
scope="house")` iterate `metric_names` at a single scope. `short_cycle_rate`
is zone-scoped, so a house-scoped call materialises a phantom
`("short_cycle_rate", "house")` baseline via `_get_baseline` (`:954-963`,
creates-on-read) and never sees the real per-zone data.

Extend `AnomalyDetector.get_status_summary(scope="house")` so that any
metric with a non-empty per-metric scope vocabulary is expanded per-scope
in the `metrics` sub-dict:

- Add optional kwarg `metric_scopes: Optional[Dict[str, list[str]]] =
  None` to `AnomalyDetector.__init__` (additive, backward-compat).
- When populating `summary["metrics"][metric_name]`, if `metric_scopes`
  contains `metric_name`, produce a per-scope breakdown: either replace
  the scalar entry with a `{"per_scope": {zone_id: {mean/std/…}, …}}`
  dict, OR flatten with keys like `short_cycle_rate.zone_1`. **Chosen:
  per-scope nested dict** — it keeps existing scalar entries unchanged
  for non-scoped metrics, so no existing consumer breaks.
- `get_learning_status` counts scoped metrics as ACTIVE if EVERY listed
  scope has met its per-metric `_min_samples_for(name)` (all zones must
  have matured; otherwise the aggregate label lies). This is the
  once-per-metric semantics referenced in D1a site #3.
- `_get_baseline` MUST NOT be called for `("short_cycle_rate", "house")`
  anywhere in the summary/learning path — the creates-on-read behaviour
  would still materialise a phantom baseline. Iterate the explicit
  `metric_scopes["short_cycle_rate"]` list instead.

HVAC wires it: at `hvac.py:1177-1187` (inside `_setup_diagnostics`,
called at `hvac.py:984`), pass
`metric_scopes={"short_cycle_rate": [z.zone_id for z in
self._zone_manager.zones.values()]}`. **Zone availability is
guaranteed** at this call site: `async_discover_zones()` runs at
`hvac.py:872` (populating `_zone_manager.zones`) BEFORE
`_setup_diagnostics()` is awaited at `hvac.py:984`. No deferral or
first-cycle rebind needed; state that fact in code comments and move on.

**Acceptance:**
- **Verify (discriminating):** with three zones present, `sensor.
  ura_hvac_coordinator_status.attributes.metrics.short_cycle_rate` is a
  dict `{"per_scope": {"zone_1": {…}, "zone_2": {…}, "zone_3": {…}}}`,
  NOT a scalar `{mean, std, sample_count, active}` at scope `house`.
  Under the wrong fix (leaving surfaces house-scoped), the field would
  be `{"mean": 0.0, "std": 0.0, "sample_count": 0, "active": false}` —
  the phantom-house-baseline signature. These two observations differ.
- **Verify:** `_baselines` dict on the HVAC detector never contains the
  key `("short_cycle_rate", "house")` after any number of decision
  cycles (grep-inspection in a test with a spy on `_get_baseline`).
- **Test:** `test_status_summary_per_scope_expansion` — detector with
  `metric_scopes={"m1": ["z1","z2"]}` and per-zone observations, summary
  contains `metrics.m1.per_scope.z1` and `.z2`; house `_baselines` has
  no `("m1", "house")` entry.
- **Test:** `test_learning_status_all_scopes_gate` — learning ACTIVE
  only when every listed scope has met the per-metric threshold.
- **Live:** after next decision cycle, `manager.py:899`'s aggregated
  status contains the per-zone breakdown; the D1a `active` transition
  is observed per-zone (not house).

### D1c — Filtered `clear_active_anomalies` variant (F1)

Add to `AnomalyDetector` in `coordinator_diagnostics.py` beside line 1310:

```python
def clear_active_anomalies(self) -> None:
    """Clear ALL active anomalies (e.g., after resolution)."""
    # Existing zero-arg semantics preserved verbatim for callers that
    # rely on wipe-all behaviour. Do NOT re-scope this method.
    self._active_anomalies.clear()

def clear_active_anomalies_filtered(
    self,
    *,
    metric_name: Optional[str] = None,
    scope: Optional[str] = None,
) -> int:
    """Clear active anomalies matching the given metric and/or scope.

    Returns the number cleared. Kwargs-only to prevent accidental
    positional confusion with the zero-arg wipe-all variant.
    If both filters are None this is a NO-OP (returns 0) — the caller
    must be explicit about wanting wipe-all by using the zero-arg
    method.
    """
    if metric_name is None and scope is None:
        return 0
    keep, cleared = [], 0
    for a in self._active_anomalies:
        if metric_name is not None and a.metric_name != metric_name:
            keep.append(a); continue
        if scope is not None and a.scope != scope:
            keep.append(a); continue
        cleared += 1
    self._active_anomalies = keep
    return cleared
```

**Acceptance:**
- **Test:** `test_clear_active_anomalies_zero_arg_wipes_all` — legacy
  behaviour untouched.
- **Test:** `test_clear_active_anomalies_filtered_metric_and_scope` — a
  detector with anomalies across
  `[(short_cycle_rate,z1), (short_cycle_rate,z2), (override_frequency,house)]`
  and a call with `metric_name="short_cycle_rate", scope="z1"` clears
  exactly one; verify remaining IDs.
- **Test:** `test_clear_active_anomalies_filtered_noop_when_both_none` —
  returns 0, list unchanged.
- **Verify (mutation):** replace the daily-rollover call
  (§D2) with the zero-arg `clear_active_anomalies()`; the test
  `test_short_cycle_daily_rollover_only_clears_its_own_metric` (§D2)
  must fail because unrelated (e.g. `override_frequency`) anomalies get
  wiped.

### D2 — `short_cycle_rate` producer

**Producer surface (event-driven, F2):** in `hvac.py`, on
post-discovery boot, register one `async_track_state_change_event`
listener per zone climate entity (`zone.climate_entity` iterated across
`self._zone_manager.zones.values()`). Handler signature per HA convention:
`@callback def _on_zone_climate_state_change(event)`; extract old/new
state's `attributes.get("hvac_action")` and drive the per-zone
cycle-tracker.

**Teardown (REUSE the existing primitive):** append each listener's
unsub token to the existing `self._unsub_listeners` list
(`hvac.py:851`, populated across `hvac.py:934-980`), which is drained
by `self._cancel_listeners()` (`base.py:282-289`) called from
`async_teardown` at `hvac.py:3936`. Do NOT introduce a new
`_short_cycle_unsubs` list; the existing primitive already handles
per-listener isolation of raise-on-cancel failures (see Reviewer B
MED-B2 note at `base.py:285-287`). No implementation hedge — the seam
is `self._unsub_listeners.append(unsub)` at the registration site.

**State model (F4) — LOCAL time throughout:**

| Attribute | Restart tag | Justification |
|---|---|---|
| `self._short_cycle_on_since: Dict[zone_id, datetime]` | `# restart: RESET` | In-memory only. Lost `on_since` simply yields no completion for the interrupted cycle (the invariant explicitly permits this — truncated cycles must NOT be counted). No `restart_epoch` needed. |
| `self._short_cycles_today: Dict[zone_id, int]` | `# restart: PERSIST` | Daily count MUST survive restart (within the bounded save-cadence + 4h-stale windows named in the invariant) or the emitted daily observation for `d` under-counts on any restart-crossing day. Persisted via the existing `hvac_zone_state` carrier (see below). |
| `self._short_cycles_today_date: str` (LOCAL ISO date, `dt_util.now().date().isoformat()`) | `# restart: PERSIST` | Paired with the count so a post-restart delivery on the same LOCAL day resumes correctly, and a post-restart delivery on a NEW LOCAL day fires the rollover for the pre-restart day using the persisted count before resetting. **This field, NOT `_last_daily_reset`, is the rollover gate** — `_last_daily_reset` is not persisted (`hvac.py:421`) and would fire the rollover block on every restart. |

**Persistence carrier (F4 concrete):** piggyback on the existing
per-zone snapshot `HVACZones.snapshot` (the same carrier flagged
"live persisted" in `DailyCounter`'s deferral docstring at
`coordinator_diagnostics.py:800-803`). Add two keys per zone to the
snapshot payload: `short_cycles_today: int` and
`short_cycles_today_date: str`. On load, rehydrate the per-zone dicts on
the producer; on save, write the current values. **Do NOT use
`DailyCounter(persist=True)` — it raises `NotImplementedError` at
`coordinator_diagnostics.py:800`.** If the builder finds
`HVACZones.snapshot` cannot round-trip additional keys, escalate to
a small carded follow-up and use a dedicated per-domain table (per
`DailyCounter`'s deferral note); do NOT invent a new persistence
primitive in this cycle.

**Cycle-tracker logic:**

- On `hvac_action` transition to `("heating", "cooling")` from anything
  else: `self._short_cycle_on_since[zone_id] = dt_util.now()`.
- On `hvac_action` transition to a non-active value (`"idle"`, `"off"`,
  `"fan"`) with `zone_id in self._short_cycle_on_since`: compute
  `duration = dt_util.now() - on_since`; if `duration.total_seconds() <
  SHORT_CYCLE_THRESHOLD_S`, `self._short_cycles_today[zone_id] += 1`;
  in either case `del self._short_cycle_on_since[zone_id]`. Cycles
  interrupted by restart have no `on_since` and are silently discarded
  — invariant-compliant.
- On any transition, if `unavailable`/`None` is seen for `hvac_action`,
  drop `on_since` for that zone (a stale-sticky mid-cycle read cannot
  be trusted; `hvac_zones.py:440` early-returns on `unavailable`
  WITHOUT clearing `hvac_action`, so the listener's own event is the
  authoritative signal).

**Daily rollover + emit block (F7 placement + F-restart guard):** place
the short-cycle rollover block at the **daily-reset branch of
`_run_decision_cycle` (`hvac.py:1290-1305`, alongside the existing
`rollover_if_needed` calls at `hvac.py:1304-1305`)** — NOT inside
`_record_anomaly_observations`. Placing it here runs it before any
early-return paths in the anomaly emitter. **BUT the rollover MUST NOT
inherit the enclosing branch's `_last_daily_reset` gate**, because
`_last_daily_reset` is non-persistent (`hvac.py:421`) and is `""` on
every boot, so the enclosing branch fires ~2.9 times/day at the
measured restart rate. Gating short-cycle emission on that field would
emit partial-day observations after every restart AND zero the persisted
counter, nullifying F4 and poisoning the D0 calibration.

The rollover block MUST use its OWN persisted date
(`_short_cycles_today_date`) as the gate — mirroring how
`_vacancy_sweeps_today.rollover_if_needed()` no-ops when its internal
date matches (that no-op is what makes the sibling calls at
`hvac.py:1304-1305` safe under the same restart pattern). The gate
guard is written explicitly, not delegated:

Rollover pseudocode (add beside `hvac.py:1305`, inside the daily-reset
branch, before it ends):

```python
# HVAC-ANOMALY-BLIND-1 D2: emit short_cycle_rate observations for the
# just-closed LOCAL day, then reset per-zone counters.
#
# CRITICAL GUARD (F-restart, post-second-plan-review):
# We are INSIDE the `if today != self._last_daily_reset:` block, which
# on every boot fires unconditionally because `_last_daily_reset` is
# non-persistent (`hvac.py:421`, init ""). We MUST re-guard the emission
# on the tracker's OWN persisted `_short_cycles_today_date` field so a
# mid-day restart does NOT emit a partial-day observation for `today`
# and zero the persisted counter. This mirrors the internal-date no-op
# used by `_vacancy_sweeps_today.rollover_if_needed()`.
#
# `today` here is the LOCAL date derived from `dt_util.now().date()`
# a few lines above at hvac.py:1288-1291.
prev_date = self._short_cycles_today_date  # "" on very-first-ever boot
if self.anomaly_detector is not None and prev_date not in ("", today):
    # A real local-day rollover occurred while we were alive OR across
    # a clean restart; emit yesterday's per-zone counts, then reset.
    for zone_id, count in list(self._short_cycles_today.items()):
        # Clear yesterday's per-zone fire before observing today,
        # bounding latching for this metric without disturbing others.
        self.anomaly_detector.clear_active_anomalies_filtered(
            metric_name="short_cycle_rate", scope=zone_id,
        )
        anomaly = self.anomaly_detector.record_observation(
            "short_cycle_rate", zone_id, float(count),
        )
        if anomaly:
            # persist via AnomalyEvent + store_event, mirroring the
            # override_frequency block at hvac.py:3707-3762 (payload
            # shape identical to override_frequency for consistency
            # with the v4.6.3 D0 canonical shape).
            ...
        self._short_cycles_today[zone_id] = 0
    self._short_cycles_today_date = today
elif prev_date == "":
    # First-ever boot (no persisted date yet). Do NOT emit; just seed
    # the date so subsequent cycles have a real prior day to compare
    # against.
    self._short_cycles_today_date = today
# else: prev_date == today → mid-day restart into the enclosing branch;
# do NOTHING. The counter and date are preserved as loaded from the
# snapshot; a genuine local-day rollover will trigger emission the first
# time _run_decision_cycle fires on a new local date.
```

**Remove** `short_cycle_rate` from `HVAC_SUPPRESSED_FROM_PERSISTENCE`
at `hvac_const.py:1006` (retain `zone_call_frequency`,
`comfort_deviation_hours`, `egress_pause_frequency`). This changes what
`_persisted_active_anomalies()` returns for HVAC and therefore
propagates through `get_worst_severity()` + `get_status_summary()`
`active_anomalies` + the HVAC anomaly sensor state + the sensor's
notification path — enumerated in §Institutional context under
`HVAC_SUPPRESSED_FROM_PERSISTENCE`. Acceptance criterion below covers
the propagation end-to-end.

**Acceptance:**
- **Verify (F-restart, restart double-emit — NEW CRITICAL):** simulate a
  mid-day restart. Set `self._short_cycles_today = {"zone_1": 4}` and
  `self._short_cycles_today_date = today_local_iso` (i.e. the counter
  survived a save just before restart); force `self._last_daily_reset =
  ""` (its post-boot state) and run the FIRST `_run_decision_cycle`
  after boot. Assert: ZERO `record_observation("short_cycle_rate", …)`
  calls, `self._short_cycles_today["zone_1"]` STILL equals 4,
  `self._short_cycles_today_date` unchanged. Under the wrong fix
  (inheriting the `_last_daily_reset` gate), the observation would fire
  with value 4.0 and the counter would zero — different observation.
- **Verify (discriminating, F-observation):** synthetic day with 8
  short-cycle completions on z1, 1 on z2, 1 on z3 → next LOCAL-day
  rollover emits EXACTLY three `record_observation` calls, one per
  zone, with values 8.0/1.0/1.0; z1 fires an ADVISORY/ALERT anomaly
  with `metric_name="short_cycle_rate" scope="zone_1"` (expected z at
  D0-frozen maturity: 8.58, well above ADVISORY 2.0 and CRITICAL 3.0).
  Under the wrong fix (still using house scope), the observation would
  be at `scope="house"` with value 10.0 — different observation.
- **Verify (restart-crossing count, F4-discriminating):** synthetic
  timeline: 5 short-cycle completions on z1 before an HA restart at
  local 22:00 on day D; 3 more short-cycle completions on z1 after
  restart before local midnight. Emitted `count_z1_D` MUST equal 8, NOT
  3 (which is what the v2 plan would have emitted). Under the wrong
  fix (in-memory-only counter), the observed value is 3 — different
  observation. (The two bounded loss windows named in the invariant
  are NOT exercised by this timeline: the save cadence is respected and
  the outage is <4h.)
- **Verify (restart mid-cycle, invariant clause 3):** cycle
  `hvac_action` idle→active at local 21:55, HA restart at 22:00, cycle
  reads idle at 22:02 post-restart. `on_since` was in-memory only, is
  now gone; no `_short_cycles_today` increment; the truncated cycle
  contributes to no `count_z_d`.
- **Verify (F1 blast-radius):** synthetic pre-existing
  `override_frequency` anomaly present in `_active_anomalies` at the
  moment of daily rollover. The rollover's
  `clear_active_anomalies_filtered(metric_name="short_cycle_rate",
  scope="zone_1")` MUST NOT clear the `override_frequency` anomaly.
- **Verify (F7 boundary, delta<0 midnight branch of
  `_record_anomaly_observations`):** even when the
  `_record_anomaly_observations` early-return at `hvac.py:3702` fires
  (override_frequency delta<0), the short-cycle rollover has already
  run (it lives in `_run_decision_cycle`, not
  `_record_anomaly_observations`). Test asserts
  `record_observation("short_cycle_rate", …)` fired for each zone
  and the emit's `sample_count` in the persisted baseline incremented
  by 1 for the day.
- **Verify (de-suppression consumer propagation — Producer/Consumer):**
  with `short_cycle_rate` removed from `HVAC_SUPPRESSED_FROM_PERSISTENCE`,
  force an ALERT-severity `short_cycle_rate` anomaly into
  `_active_anomalies` for `scope="zone_1"`. Assert:
  (a) `get_worst_severity()` returns `("short_cycle_rate", z_score)`
  (was previously filtered out by `_persisted_active_anomalies()`);
  (b) `get_status_summary()["active_anomalies"] >= 1` includes this
  anomaly (was previously in `suppressed_active_anomalies`);
  (c) the HVAC anomaly sensor's `state` reflects the severity
  transition; (d) the notification path consuming that sensor sees
  the transition (spy on the notification emit site).
- **Sensor (F6 discriminating):** `sensor.
  ura_hvac_coordinator_status.attributes.metrics.short_cycle_rate.
  per_scope.zone_1.sample_count` increments by exactly 1 per LOCAL day
  the coordinator was alive at midnight. Under the wrong fix
  (house-scoped), no `per_scope` field exists.
- **Test:** `test_short_cycle_producer_counts_only_completed_cycles`.
- **Test:** `test_short_cycle_producer_persists_count_across_restart`
  — save snapshot, tear down producer, re-instantiate, load snapshot,
  assert `_short_cycles_today[z1] == 5`.
- **Test:**
  `test_short_cycle_producer_rollover_new_local_day_after_restart_emits_pre_restart_count`.
- **Test:**
  `test_short_cycle_producer_midday_restart_does_not_emit_partial_day`
  — first `_run_decision_cycle` after boot with `_last_daily_reset==""`
  and `_short_cycles_today_date == today` emits ZERO observations,
  counter unchanged. (F-restart, the new CRITICAL guard.)
- **Test:**
  `test_short_cycle_daily_rollover_emits_once_per_zone_and_only_at_rollover`.
- **Test:**
  `test_short_cycle_daily_rollover_only_clears_its_own_metric` (F1).
- **Test:**
  `test_short_cycle_listener_unregistered_on_teardown` — the listener
  unsubs registered in `self._unsub_listeners` are drained by
  `_cancel_listeners()` on `async_teardown`; a subsequent state-change
  event does NOT increment the counter.
- **Test:** `test_short_cycle_unavailable_hvac_action_drops_on_since`.
- **Test:** `test_short_cycle_desuppression_propagates_to_worst_severity`
  — the de-suppression consumer propagation criterion above, as a unit
  test on the detector + a spy on the sensor's severity source.
- **Live (discriminating, replaces v2's "≤3 rows" non-discriminator):**
  after next LOCAL rollover, for each of the 3 zones, the persisted
  baseline row `metric_baselines WHERE coordinator_id='hvac' AND
  metric_name='short_cycle_rate' AND scope=<zone_id>` shows
  `sample_count` incremented by exactly 1 vs. the pre-rollover
  snapshot. Under the wrong producer (zero fires) `sample_count` would
  not change; under the wrong scope (house) the per-zone rows would
  not exist at all — this observation is discriminating in both
  directions. `anomaly_log` row count is EXPECTED to be zero until
  baseline maturity (14 days), so is NOT the live criterion.

---

## Traps addressed

1. **Restart mid-cycle.** Handled by RESETTING `on_since` in memory —
   restart-truncated cycles simply have no `on_since` on completion and
   are discarded. No `restart_epoch`/`boot_id` needed (neither exists in
   the repo). Restart-crossing DAILY COUNTS are preserved via the
   persisted `_short_cycles_today` per-zone dict (§D2 state table),
   subject to the two bounded loss windows named in the invariant.
2. **`record_observation` evaluates z BEFORE `baseline.update`.** Cited,
   not worked around: at 1 obs/day/zone a fault-day value of 8 shifts
   the mean by ~8/14 ≈ 0.57 on first fire — still fires again next day
   if the fault persists.
3. **Latching.** Firing rate ≤1/day/zone = 3/day worst case. NEW call to
   `clear_active_anomalies_filtered(metric_name="short_cycle_rate",
   scope=zone_id)` (see D1c) at daily rollover clears prior day's fire
   before observing the new day. Sufficient for THIS metric; the
   general gap remains carded elsewhere.
4. **Persistence gating.** Ship PERSISTED (remove from
   `HVAC_SUPPRESSED_FROM_PERSISTENCE`). Measured per-day std 0.86-1.27
   (D0) is well-conditioned, unlike `zone_call_frequency`'s degenerate
   shape. Max 3 anomaly_log rows/day worst case; typical zero.
5. **`SHORT_CYCLE_THRESHOLD_S = 600` is NEW.** Rung: MODULE CONSTANT in
   `hvac_const.py`. Safety-adjacent (compressor short-cycling
   protection); tuning should require code review.
6. **`HVAC_SHORT_CYCLE_MIN_SAMPLES = 14` is NEW.** Rung: MODULE CONSTANT
   in `hvac_const.py`, beside `HVAC_ANOMALY_MIN_SAMPLES=336`. The
   arithmetic underpinning firing separation (§Design Decision) is
   directly a function of this value; changing it changes the false-fire
   floor. Value CONFIRMED on time-to-usefulness grounds (not
   window-matching).
7. **`_get_baseline` creates-on-read.** Any code path that iterates
   metrics at a scope MUST use the explicit `metric_scopes` vocabulary
   from D1b, not `for m in metric_names: self._get_baseline(m,
   "house")` — the latter fabricates phantom `(zone-scoped-metric,
   "house")` baselines every decision cycle. Enforced by the "no
   `('short_cycle_rate', 'house')` in `_baselines`" test in D1b.
8. **`_last_daily_reset` is not a rollover gate for this cycle.** It is
   non-persistent (`hvac.py:421`, init `""`), so the enclosing daily-
   reset branch at `hvac.py:1290-1305` fires on the FIRST cycle after
   every restart (~2.9/day). The short-cycle rollover uses the
   persisted `_short_cycles_today_date` as its OWN gate (§D2
   pseudocode). Sibling counters at `hvac.py:1304-1305` are safe under
   the same restart pattern because their internal `rollover_if_needed`
   no-ops when their own date matches.

---

## Non-goals (explicit)

- General `clear_active_anomalies` wiring for other metrics (only THIS
  metric gets the filtered daily-rollover call).
- Any change to the zero-arg `clear_active_anomalies()` semantics
  (backward-compat preserved for all callers).
- One-sided z-score primitive.
- Migrating `zone_call_frequency`, `comfort_deviation_hours`, or
  `egress_pause_frequency` off suppression.
- Exposing `SHORT_CYCLE_THRESHOLD_S` or `HVAC_SHORT_CYCLE_MIN_SAMPLES`
  as options-flow / Number entities.
- Any change to `_MIN_VARIANCE`.
- Implementing `DailyCounter(persist=True)` — separate cycle when the
  shared backing store lands.
- **A dedicated per-metric persistence store** — the two bounded loss
  windows (save-cadence ~25 min, stale-snapshot >4h) are accepted as
  named exceptions in the invariant. A follow-up card may narrow either
  window if operational evidence warrants.
- The declaration-tag doctrine work (F1/F2/F5/F6/F8/DailyCounter) from
  the restart-safety audit — separate cycle.

---

## Plan-review fix-up log (2026-08-24, first pass)

v2 plan (git history of this file) was reviewed DO-NOT-BUILD by the
Tier-2-DB plan-review pass on 2026-08-24; findings captured on card
`HVAC-ANOMALY-BLIND-1` under `PLAN_REVIEW_2026_08_24_DO_NOT_BUILD`.

- **F1 (CRIT, `clear_active_anomalies` signature)** — v2 called
  `clear_active_anomalies(metric=, scope=)` which does not exist at
  `coordinator_diagnostics.py:1310`; the real method is zero-arg and
  wipes all. **Fix:** added D1c specifying a NEW sibling method
  `clear_active_anomalies_filtered(metric_name=, scope=)` (kwargs-only,
  additive, backward-compat); preserved zero-arg semantics verbatim;
  D2 rollover now calls the new method; added mutation-anchored test.
- **F2 (CRIT, Nyquist failure) — RESOLVED via D0.** v2 read
  `zone.hvac_action` from the 5-min polled snapshot but derived the
  entire fixture (z=9.13/4.91/3.65 and `minimum_samples=14`) from
  full-fidelity recorder rows. **Fix in v3:** producer redesigned as
  event-driven (`async_track_state_change_event` on 3 climate
  entities). **D0 gate ran 2026-08-24** at recorder-event fidelity and
  confirmed producer and probe share the same event surface by
  construction. D0 revised the fixture (means 21-30% low relative to
  prior — safe direction; std shape unchanged); §Design Decision
  numbers and z-scores updated; `HVAC_SHORT_CYCLE_MIN_SAMPLES = 14`
  confirmed. Audit at
  `docs/planning/AUDIT_hvac_shortcycle_recorder_fidelity.md`. Second
  Tier-2-DB plan review triggered per the §D0 gate rule.
- **F4 (CRIT, persist/reset inverted)** — v2 persisted `on_since`
  (with a nonexistent `restart_epoch`) and left `_short_cycles_today`
  in-memory. **Fix:** inverted — `on_since` is RESET, counter +
  counter-date are PERSISTED via `hvac_zone_state` snapshot (per
  `DailyCounter`'s own deferral note about that carrier);
  `restart_epoch`/`boot_id` removed entirely; every attribute in the
  §D2 state table now carries a `# restart:` tag with justification;
  `DailyCounter(persist=True) NotImplementedError` at
  `coordinator_diagnostics.py:800` explicitly acknowledged.
- **F5 (HIGH, per-metric override at 5 sites)** — v2 only mentioned
  `record_observation`. **Fix:** D1a now enumerates all 5 read sites
  (`:994`, `:1057`, `:1118`, `:1135`, `:1149`) in a table with intent
  per site; `:1135` scalar-vs-dict decision stated (keep top-level
  scalar, add new dict field); mutation drill scoped to the 4
  behaviorally-routed sites (see second-pass fix-up).
- **F6 (HIGH, house-scoped surfaces)** — v2 named a Live sensor
  attribute that doesn't exist. **Fix:** D1b added — surfaces made
  scope-aware via `metric_scopes` kwarg; explicit ban on `_get_baseline
  (scoped_metric, "house")`; per-scope nested-dict layout; discrimin-
  ating live criterion in D2 reads
  `metrics.short_cycle_rate.per_scope.zone_1.sample_count`, which
  differs under the wrong fix.
- **F7 (HIGH, insertion point)** — v2 would have placed rollover
  inside `_record_anomaly_observations`, after the delta<0 midnight
  early-return at `hvac.py:3702`. **Fix:** rollover moved to
  `_run_decision_cycle`'s daily-reset branch beside the existing
  `rollover_if_needed` calls at `hvac.py:1304-1305`, pseudocode
  provided; F7-boundary acceptance test asserts rollover fires even
  when the `_record_anomaly_observations` early-return trips.
- **F3 (provenance nit)** — 2.9 restarts/day is measured; cite the
  card (`HVAC-ANOMALY-BLIND-1`) not the audit. **Fix:** citation
  corrected in §Institutional context.
- **Coordinator count** — corrected 5 → 6 (added `manager.py:232`
  `setup_anomaly_detector`).
- **`minimum_samples=14` rung** — now `HVAC_SHORT_CYCLE_MIN_SAMPLES`,
  module constant, added to §Institutional context and Traps §6.
- **Invariant** — rewritten to quantify over the EMITTED DAILY
  OBSERVATION (not just the increment), covering the counter/restart
  case in the invariant itself.
- **D1/D2 acceptance criteria** — rewritten as testable AND
  discriminating; the v2 "Live: ≤3 anomaly_log rows" (which passes
  vacuously for a producer that never fires) replaced with the
  per-zone baseline `sample_count` increment (which discriminates
  both wrong-scope and wrong-producer failure modes).

D0 outcome (2026-08-24): ±10% gate FAILED (means 21-30% low, safe
direction); Option (c) confirmed with wider margin; thresholds re-frozen
from D0 numbers; `HVAC_SHORT_CYCLE_MIN_SAMPLES = 14` confirmed. **Second
Tier-2-DB plan review triggered** per §D0.

---

## Plan-review fix-up log (2026-08-24, SECOND pass, post-D0)

v3 plan (immediately preceding this revision) was reviewed
DO-NOT-BUILD by the second Tier-2-DB plan-review pass on 2026-08-24,
triggered by the §D0 revision. All findings addressed in-place; changes
grouped BLOCKING then MEDIUM/LOW.

- **F-restart (CRIT, restart double-emit)** — the v3 rollover
  pseudocode was placed inside the daily-reset branch
  (`hvac.py:1290-1305`) gated on `self._last_daily_reset`, which is
  init `""` at `hvac.py:421` and NEVER persisted → the block fires on
  the first `_run_decision_cycle` after EVERY restart (~2.9/day)
  emitting partial-day observations for `today` and zeroing the
  persisted counter, nullifying F4 and poisoning the D0 calibration.
  **Fix:** rewrote the pseudocode to gate on the tracker's OWN
  persisted `_short_cycles_today_date` field (`prev_date not in ("",
  today)`), mirroring how `_vacancy_sweeps_today.rollover_if_needed()`
  no-ops via its internal date. Added explicit branches for first-ever
  boot (seed the date, no emission) and mid-day restart (no-op). Added
  Trap §8 naming the pitfall. Added dedicated acceptance test
  `test_short_cycle_producer_midday_restart_does_not_emit_partial_day`
  and CRITICAL "restart double-emit" verify criterion.
- **F-clock (HIGH, UTC/LOCAL mixing)** — v3 stated invariant, state
  table, and acceptance in UTC but the enclosing branch uses
  `dt_util.now()` (local) at `hvac.py:1288-1292` and the D0 fixture is
  local-day binned (`hvac_shortcycle_daily_probe.py:20` uses
  `datetime.fromtimestamp` which returns local naive). **Fix:** picked
  LOCAL (coherent with the branch and the fixture). Rewrote the
  invariant, state table (`_short_cycles_today_date` is LOCAL ISO
  date), tracker logic (`dt_util.now()` throughout), acceptance
  (LOCAL day), and test names. Dropped the "same UTC clock as
  `rollover_if_needed`" claim (sibling counters have their OWN
  internal UTC keys — a distinct clock the short-cycle rollover
  deliberately does not share). Clock convention stated up front in
  the recommendation.
- **F-drill-site4 (HIGH, D1a mutation drill unsatisfiable)** — v3's
  5-site drill included site #4 (`:1135`), which correctly KEEPS
  `self.minimum_samples`; mutating it is a no-op and no test could
  fail. **Fix:** rescoped drill to FOUR sites (#1, #2, #3, #5) and
  gave site #4 its own shape-preservation acceptance
  (`test_status_summary_scalar_field_unchanged`, already existed as a
  test; now explicitly named as site #4's dedicated coverage). Updated
  the D1a table with an "In drill?" column.
- **F-loss-windows (HIGH, restart persistence loss windows)** — v3's
  invariant promised "no completed pre-restart cycle lost" but
  `restore_state_snapshot` skips snapshots >4h old
  (`hvac_zones.py:663-672`) and the snapshot writes only every 5
  cycles ~25 min (`hvac.py:1437-1445`), so unclean crashes and
  outages >4h silently violate that clause. **Fix:** weakened the
  invariant to explicitly name two bounded loss windows
  (save-cadence ≤25 min, stale-snapshot >4h) as permitted exceptions;
  added §Institutional context bullet documenting the mechanics;
  dedicated per-metric store deferred as an explicit Non-goal. The
  restart-crossing-count acceptance timeline notes that neither window
  is exercised.
- **F-teardown-primitive (MEDIUM, REUSE `_unsub_listeners`)** — v3
  invented `self._short_cycle_unsubs` and hedged that the builder
  would "identify the seam during implementation." Verified the
  existing primitive: `self._unsub_listeners` at `hvac.py:851`
  (populated across `hvac.py:934-980`) is drained by
  `self._cancel_listeners()` (`base.py:282-289`) called from
  `async_teardown` at `hvac.py:3936`. **Fix:** deleted the invented
  list and the hedge; §D2 producer surface and state table now
  specify `self._unsub_listeners.append(unsub)` at the registration
  site; teardown test updated to name the existing primitive.
- **F-construction-order (MEDIUM, D1b hedge)** — v3 hedged that zones
  might not be available when the detector is constructed. Verified:
  `async_discover_zones()` runs at `hvac.py:872` BEFORE
  `_setup_diagnostics()` is awaited at `hvac.py:984` (which
  constructs the detector at `hvac.py:1177`). **Fix:** deleted the
  deferral hedge from D1b; stated the ordering as a fact.
- **F-site3-semantics (MEDIUM, zone-scoped `active_count`)** — v3 did
  not specify whether a zone-scoped metric counts once or per-zone in
  the `active_count` at `:1118`. **Fix:** annotated the D1a table
  row for site #3 with the chosen semantics: once-per-metric (all
  zones must be mature for the metric to count as active in the
  aggregate), matching D1b's all-scopes-gate rule.
- **F-consumer-enum (MEDIUM, de-suppression consumers)** — v3 did not
  enumerate what changes when `short_cycle_rate` leaves
  `HVAC_SUPPRESSED_FROM_PERSISTENCE`. **Fix:** added enumeration in
  §Institutional context (feeds `_persisted_active_anomalies` →
  `get_worst_severity()` + `get_status_summary()` `active_anomalies`
  scalar + HVAC anomaly sensor state + notification path). Added
  §D2 acceptance criterion "de-suppression consumer propagation" and
  test `test_short_cycle_desuppression_propagates_to_worst_severity`.
- **F-min-samples-just (MEDIUM, MIN_SAMPLES=14 justification)** — v3
  said "matching the probe window that established the fixture" but
  the D0 window is 8 days, not 14 (AUDIT:50). **Fix:** rewrote the
  justification on time-to-usefulness grounds alone; removed the
  window-matching claim; Trap §6 updated to match.
- **F-epistemics (MEDIUM, n=8 mean-vs-std claims)** — v3 (via the D0
  audit) called the mean shift a "REAL rate difference" and the std
  shift "shape unchanged"; n=8 cannot support both as strong claims.
  **Fix:** reworded to acknowledge both shifts are within sampling
  error, and stated the substantive weaker claim: at n=8, either
  reading is safe for the Option-(c) decision (fault z ≥ 5.42 D0 /
  ≥ 3.65 prior, worst-normal under ADVISORY under both).
- **LOW — z-scores rounded from table values** — noted in §Design
  Decision that the z-scores in the table are recomputed from
  already-rounded mean/std; sign of the conclusion is robust.
- **LOW — `__init__` line number** — v3 cited
  `coordinator_diagnostics.py:874`; the `def __init__` header starts
  at :874 but the signature line the fix references (where the new
  kwarg is added) is :876. **Fix:** citation corrected in D1a and
  §Institutional context.

---

## Plan Completion Tracking (to fill at cycle close)

- [x] D0 probe re-run committed and fixture confirmed / revised?
      **REVISED** — audit at
      `docs/planning/AUDIT_hvac_shortcycle_recorder_fidelity.md`;
      §Design Decision + Traps §4 updated;
      `HVAC_SHORT_CYCLE_MIN_SAMPLES = 14` confirmed; second Tier-2-DB
      plan review triggered and its findings addressed in this doc.
- [ ] Second Tier-2-DB plan review re-verification of the F-restart
      guard passes?
- [ ] D1a shipped, 4-site mutation drill green + site-#4 shape test green?
- [ ] D1b shipped, no phantom `("short_cycle_rate", "house")` baseline?
- [ ] D1c shipped, zero-arg `clear_active_anomalies` semantics unchanged
      for all callers?
- [ ] D2 shipped, listener unsubs verified drained via
      `self._unsub_listeners` on teardown?
- [ ] F-restart mid-day-restart test green (no partial-day emission,
      counter preserved)?
- [ ] De-suppression consumer propagation test green (severity + sensor
      + notification path all reflect the fire)?
- [ ] `short_cycle_rate` removed from `HVAC_SUPPRESSED_FROM_PERSISTENCE`?
- [ ] `hvac_zone_state` snapshot round-trips `short_cycles_today`
      and `short_cycles_today_date`?
- [ ] Any deferrals beyond the stated Non-goals — list here.
- [ ] README `Validated <date>` table filled with observed per-zone
      `sample_count` deltas and (if reached) first-fire z-scores; note
      that first fire may be up to 14 days post-deploy.
