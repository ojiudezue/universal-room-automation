# PLANNING v4.6.5 — In-Memory Anomaly Persistence (Observability Cycle)

**Status:** Plan complete, ready to implement
**Tier:** Tier 1 (4 coordinators × narrow per-coordinator emit addition; no schema change, no signal chain change, no migration)
**Predecessor:** v4.6.3.1 (presence zone_occupancy persistence suppression — hotfix that surfaced this gap)
**Soak interaction:** Adds new emit sites in HVAC, security, music_following, safety-detector. Per-coordinator and disjoint. Safe alongside v4.6.2 routine awareness soak.

## Why

v4.6.3 successfully migrated 10 anomaly emit sites to the canonical `save_anomaly_event()` DAO. Post-deploy, `sensor.ura_recent_anomalies` surfaced a real **observability gap**: HVAC, security, music_following, and the safety-detector path (separate from safety hazards which DID migrate in v4.6.3 D2) all have functioning `AnomalyDetector` instances that produce in-memory `_active_anomalies` entries, but **none of those entries ever reach `anomaly_log`**.

**Evidence:** 3 hours post-v4.6.3-deploy, `sensor.ura_hvac_coordinator_hvac_anomaly` shows `state=advisory, anomalies_today=3` but `by_coordinator.hvac` in `sensor.ura_recent_anomalies` is 0. Same shape for security, MF, and safety-detector.

**Root cause:** these coordinators have always tracked anomalies in `AnomalyDetector._active_anomalies` (in-memory list, capped at 50) without writing to `anomaly_log`. v4.6.3's D7 deletion of the legacy `store_anomaly()` wrapper covered every call site that ALREADY emitted to the DB — but these coordinators never emitted in the first place, so there was nothing to migrate.

**Why this matters:** the v4.6.3 unified observability surface (`sensor.ura_recent_anomalies` + `by_coordinator` distribution + `top_10` event list + the Logbook integration via `ura_action` events) is supposed to be the one-stop view of anomaly activity across URA. With 4 coordinators silently absent, dashboards under-report, NM correlation chains break, and analytics queries miss large swaths of the system.

## Scope

Add a NEW `save_anomaly_event` emit at the appropriate gate inside each affected `AnomalyDetector` consumer. **NOT v4.6.3-shaped:** there's no existing call to migrate. The emit is added fresh at the point where `record_observation` returns a non-None anomaly.

Standard pattern per coordinator (from v4.6.3 D2/D3 conventions):

```python
anomaly = self.anomaly_detector.record_observation(metric, scope, value)
if anomaly:
    from .anomaly_event import AnomalyEvent, AnomalySeverity, EVENT_CLASS_POINT_IN_TIME, build_context_json
    ctx = build_context_json(
        zone_id=...,            # if zone-scoped
        room_id=...,            # if room-scoped
        source_signal=...,      # the originating signal if applicable
    )
    event = AnomalyEvent(
        coordinator="<coord_name>",
        type=f"<coord_name>.<metric_short_name>",
        severity=<mapped_severity>,
        event_class=EVENT_CLASS_POINT_IN_TIME,
        detected_at=anomaly.timestamp.isoformat(),
        payload=ctx,
        observed_value=anomaly.observed_value,
        expected_mean=anomaly.expected_mean,
        expected_std=anomaly.expected_std,
        z_score=round(anomaly.z_score, 3),
        sample_size=anomaly.sample_size,
    )
    await self.anomaly_detector.store_event(event)
    if activity_logger:
        await activity_logger.log(
            coordinator="<coord_name>",
            action="anomaly",
            description=f"<short summary> z={anomaly.z_score:.2f}",
            importance=<mapped_importance>,
            room=...,
            zone=...,
            details={...},
        )
```

**Lesson learned from v4.6.3.1:** before adding an emit, verify the metric is structurally appropriate for z-score detection. **Skip binary 0/1 metrics** — they produce z >= 4 for any "rare" observation and flood `anomaly_log`. Only emit for continuous-ish metrics (rates, counts, durations, deltas).

## Deliverables

### D1 — HVAC emit (`hvac.py`)

**Metrics already tracked by HVAC's AnomalyDetector** (`HVAC_METRICS` in `hvac_const.py`):
- `zone_call_frequency` — continuous, suitable
- `short_cycle_rate` — continuous, suitable
- `override_frequency` — continuous, suitable
- `comfort_deviation_hours` — continuous, suitable

All four are good z-score candidates. Add emit at the gate inside `hvac.py` where `anomaly_detector.record_observation` is called for these metrics.

**Gate location:** existing `_record_anomaly_observations()` or equivalent method in `hvac.py` (verify at build time — file is ~3000 LoC). The `record_observation` calls are likely in the periodic HVAC evaluation cycle.

**Acceptance Criteria**
- **Verify:** when HVAC anomaly_detector fires for any of the 4 metrics, an `anomaly_log` row appears with `coordinator_id="hvac"`, `type="hvac.<metric_short_name>"`, real metric values.
- **Verify:** `sensor.ura_recent_anomalies` `by_coordinator.hvac` count matches HVAC's `anomalies_today` minus pre-deploy carryover.
- **Test (behavioral, real_schema_db):** stub HVAC's AnomalyDetector to return an anomaly; assert row inserted via the new emit path.
- **Live:** 24h post-deploy, `by_coordinator.hvac` is non-zero on the live system (if HVAC AnomalyDetector legitimately fires during that window — currently `advisory` with 3 anomalies/day baseline).

**Cost:** ~50 LoC + ~30 test LoC.

### D2 — Security emit (`security.py`)

**Metrics tracked by security's AnomalyDetector** (verify at build time):
- Likely: `arming_event_rate`, `door_unlock_frequency`, `unfamiliar_activity_count`
- Audit which are continuous vs binary before wiring.

**Same emit shape as D1.** Coordinator name = `security`. Event types prefixed `security.<metric>`.

**Acceptance Criteria**
- **Verify:** security anomalies write to `anomaly_log` with `coordinator_id="security"`.
- **Test (behavioral):** stub → emit → row.
- **Live:** if security AnomalyDetector legitimately fires post-deploy, `by_coordinator.security` > 0.

**Cost:** ~50 LoC + ~30 test LoC.

### D3 — Music Following emit (`music_following.py`)

**Metrics tracked by MF's AnomalyDetector** (verify at build time):
- Likely: `transfer_failure_rate`, `transfer_latency_ms`, `target_unavailable_count`
- Continuous metrics expected.

**Same shape.** Coordinator name = `music_following`. Event types prefixed `music_following.<metric>`.

**Acceptance Criteria**
- **Verify:** MF anomalies write to `anomaly_log` with `coordinator_id="music_following"`.
- **Test (behavioral):** stub → emit → row.
- **Live:** if MF AnomalyDetector legitimately fires post-deploy, `by_coordinator.music_following` > 0.

**Cost:** ~50 LoC + ~30 test LoC.

### D4 — Safety-detector emit (`safety.py`, distinct from D2 safety-hazards)

**Distinction from v4.6.3 D2:** v4.6.3 migrated safety **hazard** emits (smoke, CO, leak triggers). This deliverable covers safety **detector** anomalies — the `AnomalyDetector` instance inside the safety coordinator that tracks statistical patterns like `hazard_trigger_frequency` and `active_hazard_count` (the metric_names visible on `sensor.ura_safety_coordinator_safety_anomaly`).

These metrics are statistical aggregates; safety hazards are individual events. Different gates, different rows.

**Note:** `active_hazard_count` is integer-valued and effectively binary in most homes (0 or 1). Audit for the same degenerate-z-score shape as zone_occupancy before wiring. Likely outcome: emit `hazard_trigger_frequency` but skip `active_hazard_count` per the v4.6.3.1 lesson.

**Acceptance Criteria**
- **Verify:** safety-detector anomalies write to `anomaly_log` with `coordinator_id="safety"` and `type="safety.<metric_short_name>"` (distinct from `type="safety.hazard.*"` rows from D2 hazards).
- **Test (behavioral):** stub → emit → row.
- **Test (degenerate-metric audit):** confirm `active_hazard_count` is NOT wired (or has explicit gate skipping low-cardinality observations).
- **Live:** post-deploy, `by_coordinator.safety` distinguishes hazard rows (from v4.6.3 D2) from detector rows (new in this cycle) via the `type` field.

**Cost:** ~50 LoC + ~30 test LoC.

### D5 — Audit lesson encoded as a meta-test

Add a test in `quality/tests/test_v465_observability_gap.py` (new file) that walks every coordinator's `AnomalyDetector` consumer file and asserts: for every metric in `<COORD>_METRICS`, either (a) there is a `store_event` call site that emits when `record_observation` returns truthy for that metric, OR (b) the metric is explicitly listed in a `SUPPRESSED_FROM_PERSISTENCE` set (with a code comment explaining why — e.g., binary occupancy from v4.6.3.1).

This codifies the v4.6.3.1 lesson and prevents future "in-memory only" metric tracking from slipping in unnoticed.

**Cost:** ~80 LoC.

## Out of scope (deferred)

- **Bayesian time-bin distribution surface for `zone_occupied_count` and other binary-occupancy metrics.** v4.6.2 routine awareness already does this for per-person routines; extending to per-zone is its own design exercise. Defer.
- **Per-zone anomaly sensors.** Currently anomalies are house-scoped or zone-scoped within a coordinator's status dict; first-class per-zone sensors are out of scope here.
- **Anomaly correlation across coordinators.** D5's NM correlation in v4.6.3 was the first step; deeper correlation graphs (e.g., HVAC anomaly + presence anomaly within 5 min → "unusual occupancy + HVAC override" composite event) is a future design cycle.
- **Anomaly retention policy.** `anomaly_log` has no scheduled cleanup. Will become load-bearing once v4.6.5's new emits significantly increase row volume. File as a separate small cycle.

## Cost summary

| Component | Production | Test |
|---|---|---|
| D1 (HVAC) | ~50 | ~30 |
| D2 (Security) | ~50 | ~30 |
| D3 (Music Following) | ~50 | ~30 |
| D4 (Safety detector) | ~50 | ~30 |
| D5 (meta-test) | — | ~80 |
| **Total** | **~200** | **~200** |

Tier 1 cycle. Single staff-engineer review.

## Risks

1. **Degenerate-metric trap (v4.6.3.1 shape).** Each coordinator's metric list MUST be audited for binary/low-cardinality metrics before wiring. The build agent should produce an audit table per coordinator with "metric / type (continuous/binary) / wire-to-persistence (yes/no/justify)" rows.
2. **Row volume increase.** Adding 4 new emit sites will increase `anomaly_log` write rate. Capture pre-deploy baseline; verify post-deploy increase is within reason (estimated <20 emits/hour total across all 4 coordinators on a stable household, but verify).
3. **Activity logger dedup mask (Bug Class #41).** Descriptions for the new emits MUST include z_score or another distinguisher.
4. **Event type collision with v4.6.3 D2 safety hazards.** Safety detector emits are `type="safety.<metric>"`. Safety hazards are `type="hazard.<smoke|co|leak>"` (or similar). Confirm naming distinct so analytics queries don't conflate them.

## Live validation plan

1. **Per coordinator, synthetic anomaly trigger** (or wait for natural trigger in the soak window): verify a row appears in `anomaly_log` with `coordinator_id` matching, `type` matching the v4.6.5 emit type, and non-zero metric values (B1 fix from v4.6.3 still working).
2. **`sensor.ura_recent_anomalies` `by_coordinator` distribution** post-24h-soak: HVAC, security, music_following, safety should all appear with non-zero counts IF they have legitimately fired AnomalyDetector during the window. If they remain at 0 despite the per-coordinator sensors showing anomalies, the emit isn't wired correctly.
3. **Activity Logbook integration:** confirm `ura_action` events with `action="anomaly"` appear for each new emit type. Logbook should show entries categorized by the new event types.
4. **Pre/post-deploy row rate:** total `anomaly_log` row rate within ±50% of pre-deploy baseline (this cycle is expected to materially increase the rate, but a 5x+ spike would indicate over-emit per the v4.6.3.1 shape).

## Recall hint

`"Resume URA roadmap — in-memory anomaly persistence v4.6.5"` will load this plan.
