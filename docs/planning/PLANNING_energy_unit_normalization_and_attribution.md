# Planning — Zone/Room Energy Unit Normalization + 4-Tier Attribution Semantics Fix

**Status:** Draft (planning only — version assigned at deploy time per URA versioning convention)
**Tier:** Operator-elevated **Tier 2-DB** (3 framing-disjoint reviews + live validation + README write-back)
**Scope owner:** Energy Coordinator + room/zone aggregation surfaces
**Trigger:** 2026-06-09 live audit on v5.3.0 — energy/cost/coverage poisoning across the
attribution stack: `zone master_suite energy_today = 1,671 kWh` (~1000× plausible),
`coverage_delta state = −839,746,910 kWh`, `coverage_rating = "Excellent"`,
`cost_per_occupied_hour = $48.03/h`. Sibling zones silently 0 kWh despite live power.

This is a context-wide cycle. We distinguish **intent errors** (the original B4
plan said all four attribution tiers are TODAY-scoped; three of four tiers were
shipped as raw-state reads instead) from **code errors** (no `unit_of_measurement`
normalization where the bug class is otherwise fixed in 5+ sibling files). The
fix must address both, with sibling-path coverage, without narrowly patching one
arithmetic site.

---

## Tier Classification

**Operator-elevated Tier 2-DB.** Justification: this changes a **shared primitive**
(`STATE_ENERGY_TODAY`) that feeds at least seven downstream consumers across
`sensor.py` (room) and `aggregation.py` (rooms-total, coverage-delta, cost-per-occupied-hour,
zone energy, zone cost). It is a **trust-hierarchy ripple change** in the cost /
coverage / B4-Layer-2 axis. A surgical fix in one site could silently leave a
sibling poisoned (the v5.3.0 audit IS the proof — five sites were sibling-poisoned
by the same bug class). The 3 framing-disjoint reviews are mandatory.

**Three review framings (assigned to reviewers A / B / C):**

- **Reviewer A — Unit/numeric correctness + DB migration.** Wh↔kWh normalization
  applied at every read of an `energy` device-class entity. `room_energy_baselines`
  row migration is correct, idempotent, and version-gated. Sanity guards
  (`SANE_MAX_DELTA_KWH`) still hold in both directions (positive runaway AND
  negative drift on normalize-vs-raw-baseline mismatch — Wh-stored-baseline minus
  kWh-normalized-current would go hugely negative and silently be `max(0,·)`-clipped
  to 0 forever).
- **Reviewer B — Cross-tier attribution semantics vs PLANNING_v4.x_B4 D1c intent +
  no-double-count.** Every tier (rooms / zones / house-devices / whole-house) MUST
  be TODAY-scoped, not raw lifetime counters. No tier may double-count a circuit
  that is also referenced in another tier (room sensor on a circuit also in the
  zone meter). Coverage-rating boundary cases (negative delta, >100% over-attribution,
  null whole-house). Cite `aggregation.py:2469` (rating call) and B4 D1c divergence
  rule at planning doc lines 167–189.
- **Reviewer C — Consumer surfaces + monotonic guards + test authority.** All
  downstream consumers of `STATE_ENERGY_TODAY` updated/audited (the 7 sites named
  in §Institutional Context). EnergyTodaySensor (`sensor.py:675 _last_valid_value`)
  and ZoneEnergyTodaySensor (`aggregation.py:3742 _last_valid_value`) monotonic
  guards behave correctly post-fix (HA restart clears in-memory state, so the
  1000×-smaller corrected value is NOT rejected — but document this so future
  reviewers don't re-flag it). Tests drive the production read path, not their
  own ad-hoc unit math.

---

## Institutional Context Verified

### Greps run + results

| Proposed addition | Status | Evidence |
|---|---|---|
| Wh→kWh normalization helper | **NEW** (shared util). Hand-rolled at 5+ existing sites (domain_coordinators/energy_battery.py:275–298 `battery_power_w`, `_read_power_w` at 300–324; energy_pool.py:282–288 `uom in ("kW","kw")`). No shared helper exists today (`grep "def.*normalize\|to_kwh"` returns only `safety.py:1506 _normalize_temperature` and `optimization_llm.py:1115 _normalize_proposed_action` — unrelated). **Justification: one shared helper avoids a 7th hand-rolled copy and gives reviewer A a single audit point.** Place in `domain_coordinators/_units.py` (new tiny module) or top of `aggregation.py` if util module proves contentious. **Do NOT refactor the 5 existing call sites in this cycle** — note as optional follow-up to keep blast radius down. |
| `CONF_ZONE_ENERGY_SENSORS`, `CONF_HOUSE_DEVICE_ENERGY_SENSORS`, `CONF_WHOLE_HOUSE_ENERGY_SENSORS` | **REUSED** at `const.py:241,243,237`. Shipped in B4 Layer 1. |
| Tier-2-DB review protocol | **REUSED** per `CLAUDE.md` standing policy. |
| `room_energy_baselines` table (3-column: room_id, sensor_id, baseline_value, baseline_set_at, needs_reset) | **REUSED** at `database.py:1033`. **Schema does NOT carry unit metadata** — the migration hazard the operator flagged is real. |
| Bug class for unit-of-measurement mismatch | **REUSED** — `QUALITY_CONTEXT.md` Bug Class #30 "Unit-of-Measurement Drift Across Firmware" (verified `QUALITY_CONTEXT.md:1031–1090`). This cycle is a Bug Class #30 recurrence on a non-power surface (energy device class, Wh vs kWh). Cite it in commit + README. Sibling of Bug Class #31 (per-unit vs aggregate). |
| Sane-delta runaway guard `SANE_MAX_DELTA_KWH=500.0` | **REUSED** at `coordinator.py:1844`. Catches positive runaway only — does NOT catch the negative-drift hazard the fix introduces (see D1 Migration Hazard). |
| Bug Class #7 (stale data source) relevance for D4 observability | **REUSED** — `QUALITY_CONTEXT.md:297`. Dead-sensor silent-0 is structurally the same class of failure (downstream consumer trusts an empty read as truth). |

### Prior planning docs consulted

- `docs/planning/PLANNING_v4.x_B4_ENERGY_INTEGRATION.md` (full read of D1, D1b, D1c).
  D1c intent verified: lines 144–189 explicitly specify all four tiers as TODAY
  energy with cross-check `attributed_total + unattributed ≈ whole_house`, AND
  divergence handling. The shipped `aggregation.py:2384–2513` honors the SHAPE
  (4-tier attrs) but silently violates the TODAY-scope contract for 3 of 4 tiers.
- `docs/planning/PLANNING_OPTIMIZATION_COORDINATOR_v2_agentic.md` (skim) — Optimizer
  cost/comfort tiers consume room energy_today; poisoning there cascades. Not in
  scope to change, but Reviewer C should verify no double-fix needed.

### Memory bodies pulled

- `project_optimizer_db_write_flood_incident_2026_06_09.md` — fresh memory of the
  rollback context. This cycle is NOT optimizer-related, but ships on top of v5.3.0
  live, so any DB write volume increase MUST be benchmarked pre-deploy.
- `feedback_no_fabrication_dhcp_incident.md` — discipline reminder, no fabricated
  HA-API claims in this plan; all line numbers cited from this session's reads.
- `feedback_tier2db_for_regression_prone.md` — standing policy invoked.

### Design docs read

- `docs/Coordinator/ENERGY_COORDINATOR_DESIGN_v2.3.md` (skim) — confirms energy
  coordinator does NOT own the room/zone aggregation surfaces being fixed here.
  This cycle lives in `coordinator.py` (room) + `aggregation.py` (rooms/zones/devices),
  not under `domain_coordinators/energy.py`.

### Code locations surveyed (read end-to-end during scoping)

- `custom_components/universal_room_automation/coordinator.py:1840–1957` (room
  energy tracking, the singular site missing unit normalization at line 1876).
- `custom_components/universal_room_automation/aggregation.py:2384–2513`
  (`EnergyCoverageDeltaSensor` + `_sum_sensors` + three tier getters).
- `custom_components/universal_room_automation/aggregation.py:617–626`
  (`_get_coverage_rating` — no sign/range guard).
- `custom_components/universal_room_automation/aggregation.py:2585–2665`
  (`EnergyCostPerOccupiedHourSensor`, the user-visible $48.03/h symptom).
- `custom_components/universal_room_automation/aggregation.py:3729–3815` (zone
  energy + cost sensors).
- `custom_components/universal_room_automation/sensor.py:664–728` (room
  EnergyTodaySensor + EnergyCostTodaySensor, monotonic guard at line 675).
- `custom_components/universal_room_automation/database.py:1033–1043, 4247–4341`
  (`room_energy_baselines` schema + DAO).
- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py:275–324`
  (precedent normalization, hand-rolled).
- `custom_components/universal_room_automation/domain_coordinators/energy_pool.py:282–290`
  (precedent normalization, hand-rolled; comment self-identifies as Bug Class #30).

---

## Scope

**IN scope (this cycle):**
- D1: Room energy unit normalization (Wh→kWh) + `room_energy_baselines` migration.
- D2: 4-tier attribution TODAY-scope semantics (zones / house-devices via shared
  today-delta baseline tracker; whole-house tier semantics defined explicitly).
- D3: Coverage-rating sign/range guard.
- D4: Dead-energy-sensor observability (WARNING + attribute when ALL of a room's
  configured energy sensors are unavailable).
- D5: Pre-deploy snapshot + Live Validation criteria.

**OUT of scope (separate tasks; explicitly not in this cycle):**
- Occupancy-weighted switch restart persistence.
- `energy_grid_demand` dead sensor remediation.
- Negative `predicted_energy_today` investigation.
- Routine-awareness forecaster.
- Optimization Coordinator Phase 5.
- Refactoring the 5 existing hand-rolled unit-normalization sites
  (optional follow-up, do not bundle).
- SPAN circuit entity_id remap (configuration work — `upstairs` zone went to 0;
  list as operator/live-validation step, not code; see hygiene-bucket memo).

---

## D1: Room Energy Unit Normalization + Baseline Migration

### Code error (verified)
`coordinator.py:1876` reads `current_value = float(state.state)` with no
`unit_of_measurement` check. A sensor that reports in Wh (device_class=energy,
uom="Wh") inflates 1000×. The integration-fallback branch at line 1943 looks
unit-correct for Watts (divides by 1000 to convert Wh→kWh) and is not in scope
to change.

### Design
1. Add a small shared helper:
   ```python
   # custom_components/universal_room_automation/domain_coordinators/_units.py (NEW)
   def energy_state_to_kwh(state) -> float | None:
       """Read an energy device-class HA state and return value in kWh.

       Bug Class #30 fix on the energy device class. Handles uom ∈
       {kWh, kwh, Wh, wh, MWh, mwh}; returns None on unparseable.
       """
   ```
   Use it at `coordinator.py:1876` and at every `_sum_sensors` site touching
   energy entities (D2). **Do NOT refactor the 5 existing power sites** — those
   are on the power device class and out of scope.

2. **Migration hazard (operator flagged, confirmed).** The existing
   `room_energy_baselines` table at `database.py:1033` stores
   `baseline_value REAL NOT NULL` with NO unit column. If we normalize
   `current_value` to kWh at line 1876 but the persisted baseline is a raw Wh
   number from a prior boot, `raw_delta = kwh_current − wh_baseline` goes hugely
   negative. The existing `SANE_MAX_DELTA_KWH = 500.0` guard at line 1844 only
   triggers on `raw_delta > 500.0` (positive runaway). The `max(0, raw_delta)`
   clamp at line 1936 then silently zeros the room forever (until midnight, when
   the baseline is reset to a normalized value).

   **Decision: version-gated full baseline reset on first boot of the new code.**
   Justification: (a) zero new schema (no unit column to back-fill / interpret),
   (b) cost is at most one day of part-of-day room energy on the upgrade boot —
   acceptable for a single-user install (memo `project_single_user_no_backcompat`),
   (c) simpler than the alternative (add `unit TEXT` column, back-fill
   "unknown", branch the read path). Mechanism: a new constant
   `ENERGY_BASELINE_SCHEMA_VERSION = 2` recorded as a singleton row (or a
   `hass.data`-tracked flag persisted via the existing baseline DAO with a
   sentinel `sensor_id`), and a one-shot reset on first observation that the
   stored version is < 2. Sane-delta guard MUST be extended to also catch
   `raw_delta < −SANE_MAX_DELTA_KWH` and trigger the same reset (defense-in-depth
   against future drift).

### Acceptance Criteria — D1
- **Verify:** `energy_state_to_kwh` returns same float for `(1.0, "kWh")` and
  `(1000.0, "Wh")`; returns `None` for unavailable / unparseable.
- **Verify:** Existing `room_energy_baselines` rows are reset exactly once on
  first boot of the new code (no repeated reset on subsequent boots).
- **Verify:** Sane-delta guard fires on negative delta below
  `−SANE_MAX_DELTA_KWH` (regression test).
- **Test:** `quality/tests/` — `test_energy_unit_normalization.py` covering
  Wh / kWh / MWh / Wh-as-string / missing-uom / unavailable paths through
  `coordinator.py` `_update_energy_tracking`.
- **Test:** `test_room_energy_baseline_migration.py` — old-row → reset → first
  read becomes new baseline; second boot does NOT re-reset.
- **Live:** `sensor.master_suite_energy_today` drops from ~1,671 kWh to a plausible
  single-digit-to-low-double-digit kWh within one update cycle after restart.
  `sensor.entertainment_energy_today` drops from 960.8 kWh to similar.

---

## D2: 4-Tier Attribution TODAY-Scope Semantics

### Intent error vs code error (split per operator)
**Intent error against B4 D1c:** `PLANNING_v4.x_B4_ENERGY_INTEGRATION.md:144–189`
spells out the four-tier model as TODAY energy. Three of four tiers were shipped
as raw current state reads:
- `_get_zones_total_energy` (`aggregation.py:2490–2505`) — sums RAW state of
  zone energy entities → 839.7M kWh (cumulative lifetime counters).
- `_get_house_devices_total_energy` (`aggregation.py:2507–2513`) — same shape.
- `_get_whole_house_energy` (`aggregation.py:2472–2478`) — same shape; the
  semantic intent here MUST be defined explicitly (live audit: verify what entity
  is actually configured before assuming counter-vs-today).

**Code error (orthogonal):** `_sum_sensors` (`aggregation.py:2409–2421`) does no
unit normalization. Even if a today-delta tracker is added, it must normalize.

### Design
1. **Today-delta tracker for zones + house-devices.** Reuse the room baseline
   pattern: persist `(scope, sensor_id) → (baseline_value_kwh, set_at, needs_reset)`
   in a new DB table OR generalize the existing `room_energy_baselines` table
   (extend PK to `(scope, scope_id, sensor_id)`; back-fill existing rows as
   `scope='room'`). **Decision pending Reviewer A** — choose ONE in the builder
   phase; both are tractable. Whichever is chosen: the today-delta read goes
   through the SAME `energy_state_to_kwh` helper as D1.
2. **Whole-house tier semantics.** Live-verify what `CONF_WHOLE_HOUSE_ENERGY_SENSORS`
   resolves to (likely a `_today` device on SPAN or Envoy). Two cases:
   - If it's already a TODAY-scoped sensor (resets daily): pass through after
     unit normalization. Document this in the sensor attributes
     (`whole_house_scope: "today_native"`).
   - If it's a cumulative counter: apply the same today-delta tracker.
     (`whole_house_scope: "today_derived"`).
3. **Refuse to compute when scope mixed.** If zone/house-device entities resolve
   to a mix of today-native and cumulative-counter shapes, the delta is
   meaningless. Add a `scope_mismatch_warning` attribute and skip that tier's
   contribution for the cycle.
4. **No-double-count discipline.** Out of scope to detect entity-overlap across
   tiers in code (operator config-time concern); explicitly document this in
   the planning doc as an operator hygiene step and as a Reviewer B check.

### Acceptance Criteria — D2
- **Verify:** `_get_zones_total_energy`, `_get_house_devices_total_energy`, and
  `_get_whole_house_energy` all return TODAY-scoped values, all in kWh, all
  resilient to Wh-reporting sources.
- **Verify:** `coverage_delta state` becomes a plausible small kWh number
  (post-fix expectation: ≤ ~30% of whole_house, positive in typical operation).
- **Verify:** `delta_percent` falls into the 0–100% range under normal conditions.
- **Verify:** Out-of-band attribution is signalled by the
  ``delta_percent`` bounds rating (D3 Anomalous / Incomplete) and by the
  per-tier ``scope_mismatch_warning``. **B-H2 amendment (fix-up pass):
  the original B4 D1c divergence cross-check
  ``abs(attributed + unattributed − whole_house) / whole_house`` is
  degenerate (identically zero) when ``unattributed`` is defined as
  ``whole_house − attributed`` — it can never trigger and was never
  built. The signal it was meant to surface (cross-tier disagreement)
  is now carried by the bounds rating + scope warning.**
- **Test:** `test_coverage_delta_tier_semantics.py` covering all-cumulative,
  all-today, mixed (with `scope_mismatch_warning`), and degenerate
  (whole_house=None or 0) inputs.
- **Live:** `sensor.universal_room_automation_energy_coverage_delta` state moves
  from −839,746,910 kWh to a sane single/double-digit kWh; `zones_total` and
  `house_devices_total` attrs are plausible TODAY values.
- **Live:** `sensor.universal_room_automation_energy_cost_per_occupied_hour`
  drops from $48.03/h to a plausible single-digit $/h (driven by D1 + D2
  feeding `STATE_ENERGY_TODAY` correctly).

---

## D3: Coverage-Rating Sign/Range Guard

### Code error
`_get_coverage_rating(delta_percent)` at `aggregation.py:617–626` uses a series
of `delta_percent < THRESHOLD` checks. A massively negative `delta_percent`
(observed: 24,558,907,924%, but also any negative number) falls through every
threshold and returns `COVERAGE_RATING_EXCELLENT`. This is sign-blind, not just
range-blind.

### Design
Insert a guard at function top:
```python
if delta_percent is None or delta_percent < 0 or delta_percent > 100:
    return COVERAGE_RATING_INCOMPLETE  # or a new "Anomalous" constant
```
**Decision: add a new constant** `COVERAGE_RATING_ANOMALOUS = "Anomalous"`
(rather than overload `INCOMPLETE`) so post-deploy auditors can grep for it as
a distinct telemetry signal. Add to `const.py` near the other coverage-rating
constants. Surface it in the sensor attributes and log a single WARNING per
detection (rate-limited) so the cause can be investigated.

### Acceptance Criteria — D3
- **Verify:** `_get_coverage_rating(-100.0)`, `_get_coverage_rating(1e10)`, and
  `_get_coverage_rating(None)` all return `COVERAGE_RATING_ANOMALOUS`.
- **Test:** `test_coverage_rating_bounds.py` parametrized over negative, zero,
  small-positive, threshold-boundary, large-positive, None, NaN.
- **Live:** Pre-fix `coverage_rating` reads "Excellent" while delta is −839M;
  post-fix on the same poisoned input, reads "Anomalous". (Validation can be
  done in the in-suite test even if D1+D2 fix the poisoning before live.)

---

## D4: Dead-Energy-Sensor Observability

### Code error
`coordinator.py:1853` `continue`s silently when a configured energy sensor is
`unknown`/`unavailable`. If ALL configured sensors for a room are dead (matches
the v5.3.0 `upstairs` zone failure mode, likely tied to the renamed-SPAN-circuit
backlog item), `STATE_ENERGY_TODAY` falls through as 0.0 with no warning.
Downstream consumers (cost, coverage) take the 0.0 as truth.

### Design
1. Track per-room "all configured energy sensors unavailable" state across the
   energy-tracking call. If TRUE:
   - Log a WARNING (rate-limited; e.g. once per hour per room using
     `monotonic()` timer on the coordinator instance — Bug Class #26 spirit).
   - Surface a `energy_sensors_dead: True` attribute on
     `EnergyTodaySensor` (room) so dashboards can show it without log mining.
   - Do NOT advance `STATE_ENERGY_TODAY` to 0; leave the prior value in place
     (the monotonic guard at `sensor.py:697` already enforces this in-memory,
     but coordinator-side data should be `None` in this case so the downstream
     sums skip the room cleanly).
2. **Explicitly OUT of scope:** Actually remapping the SPAN circuit entity_ids.
   That is operator config work tracked in the hygiene-bucket memo
   (`project_hygiene_bucket_yaml_span.md`). Listed here as a live-validation
   follow-up so the operator can verify `upstairs` zone recovers after remap.

### Acceptance Criteria — D4
- **Verify:** When all configured `CONF_ENERGY_SENSORS` for a room are
  unavailable, a WARNING is logged at most once per hour per room.
- **Verify:** `sensor.<room>_energy_today.attributes.energy_sensors_dead == True`
  in that case.
- **Verify:** Rooms-total tier in coverage-delta skips dead rooms cleanly
  (does not contribute 0 noise; uses the prior good value or None).
- **Test:** `test_dead_energy_sensor_observability.py` with all-dead, partial-dead,
  and recovery paths.
- **Live:** Trigger by examining the `upstairs` zone in live; after restart,
  expect `energy_sensors_dead: True` attribute on at least one upstairs-zone
  room sensor. (Recovery via SPAN remap is operator follow-up, separate cycle.)

---

## D5: Pre-Deploy Snapshot + Live Validation

### Pre-Deploy Snapshot (Tier 2-DB requirement)
Record current live values BEFORE restart so post-deploy ±25% comparison is
possible. Capture into the README at deploy time:

| Sensor | Current (poisoned) | Expected post-fix |
|---|---|---|
| `sensor.master_suite_energy_today` | ~1,671 kWh | < 50 kWh |
| `sensor.entertainment_energy_today` | 960.8 kWh | < 10 kWh |
| `sensor.universal_room_automation_energy_coverage_delta` | −839,746,910 kWh | within ±30% of whole_house, sign positive in typical operation |
| `coverage_delta.attributes.attribution_coverage_pct` | 24,558,907,924% | 0–100% |
| `coverage_delta.attributes.coverage_rating` | "Excellent" | "Excellent" / "Good" / "Fair" / "Incomplete" / "Anomalous" — any one of the bounded set, NOT a false-positive on poisoned data |
| `coverage_delta.attributes.rooms_total` | 2,249.78 kWh | sane TODAY kWh sum |
| `coverage_delta.attributes.zones_total` | 839.7M kWh | sane TODAY kWh sum |
| `sensor.universal_room_automation_energy_cost_per_occupied_hour` | $48.03/h | < $5/h typical |
| `sensor.upstairs_zone_energy_today` (or equivalent) | 0.0 stuck | either non-zero (post-remap) OR `energy_sensors_dead: True` attribute |

### Live Validation (Review D)
- **Run:** `@ura-validator` live mode after HA restart.
- **Confirm:** Every row in the snapshot table moves from "Current (poisoned)"
  to "Expected post-fix".
- **Confirm:** Zero new ERRORs in HA log scoped to URA between restart and
  validation cutoff.
- **Confirm:** `energy_state_to_kwh` shared helper hit at least once with a
  Wh-reporting source (verify via debug logging or an attribute counter on the
  coverage-delta sensor; remove the counter pre-Phase-2 if added).
- **Confirm:** No regression in room cost_today values (sane low-single-digit
  dollars per room, not the $45.99 Study A poisoning).
- **HA Recorder LTS damage:** Single-user install decision — **accept cosmetic
  history damage** rather than run HA `recorder.statistics_clear_collected`.
  Document this in the README "Known cosmetic regressions" subsection. The
  inflated 1000× datapoints in LTS will age out per recorder retention.
- **README write-back (mandatory):** Replace prospective bullets with the
  observed-results table per `CLAUDE.md` "Record Live Validation Back Into the
  README".

---

## Files Changed (estimated)

| File | Change |
|---|---|
| `custom_components/universal_room_automation/coordinator.py` | D1 normalize at `_update_energy_tracking` line 1876; D1 migration version check; D1 extend `SANE_MAX_DELTA_KWH` guard to negative; D4 dead-sensors WARNING + state |
| `custom_components/universal_room_automation/aggregation.py` | D2 today-delta semantics for `_get_zones_total_energy`, `_get_house_devices_total_energy`, `_get_whole_house_energy`; D2 normalize in `_sum_sensors`; D3 coverage-rating bounds guard at `_get_coverage_rating` |
| `custom_components/universal_room_automation/sensor.py` | D4 `energy_sensors_dead` attribute on `EnergyTodaySensor` |
| `custom_components/universal_room_automation/const.py` | `COVERAGE_RATING_ANOMALOUS`, `ENERGY_BASELINE_SCHEMA_VERSION` |
| `custom_components/universal_room_automation/database.py` | D1 migration: schema-version marker for `room_energy_baselines`; D2 optional generalization to `(scope, scope_id, sensor_id)` if chosen by Reviewer A |
| `custom_components/universal_room_automation/domain_coordinators/_units.py` | NEW — `energy_state_to_kwh` shared helper |
| `quality/tests/test_energy_unit_normalization.py` | NEW |
| `quality/tests/test_room_energy_baseline_migration.py` | NEW |
| `quality/tests/test_coverage_delta_tier_semantics.py` | NEW |
| `quality/tests/test_coverage_rating_bounds.py` | NEW |
| `quality/tests/test_dead_energy_sensor_observability.py` | NEW |

---

## Risks + Mitigations

| Risk | Mitigation |
|---|---|
| Baseline-migration negative-delta silent-zero (D1 hazard) | Extend `SANE_MAX_DELTA_KWH` guard to both signs + version-gated reset |
| Monotonic guard rejects corrected 1000×-smaller value | HA restart on deploy clears `_last_valid_value` in-memory; documented for Reviewer C so it isn't re-flagged |
| Today-delta tracker increases DB write volume (post-write-flood incident) | Reuse room baseline write cadence (per-cycle, throttled by sanity guard); benchmark write rate pre-deploy per Tier 2-DB requirement; abort deploy if baseline writes exceed 2× current per-room rate |
| Whole-house tier mis-assumed cumulative-vs-today | Live-verify configured entity before deploy; D2 emits `whole_house_scope` attribute so reviewers can audit post-deploy |
| HA LTS cosmetic damage (1000× inflated history) | Accept (single-user install); document in README |
| SPAN remap blocks observability proof for `upstairs` | D4 ships independently; remap is separate operator follow-up, not blocking |

---

## Bug Classes Cited

- `#7` Stale Data Source (D4 dead-sensor silent-0).
- `#26` High-Frequency DB Read (rate-limit pattern for D4 logging).
- `#30` Unit-of-Measurement Drift (D1 + D2; this cycle is a recurrence on the
  energy device class).
- `#31` Per-Unit vs Aggregate Sensor Reads (sibling — D2 zone meter vs room
  circuit overlap is the same family; flagged as Reviewer B audit, not in-scope
  to fix).
