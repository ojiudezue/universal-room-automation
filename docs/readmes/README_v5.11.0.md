# URA v5.11.0 — Optimization Coordinator Hardening (Tier 3)

Hardens the Optimization Coordinator (OC) against the failure shape that produced the v5.0.0-v5.2.1 rollback: a write-flood across multiple channels (findings table, activity log, notifications, digests) that saturated the DB write-queue and starved core writes into a supervisor watchdog restart. This cycle ships **five-channel write-volume tripwire + boot-storm short-circuit + notification dedup TTL fix + shadow-sample persistence with pruner + promotion-readiness readout**, plus per-room observability that stays None until first cycle.

## Root causes addressed (verified in source)

1. **Write-flood** — v5.0.0-v5.2.1 flooded `ura_activity_log` (per-boot Sensor-Health fires × per-cycle emit) and `optimizer_findings` (per-finding persist). The v5.11.0 tripwire counts **all five** write channels — findings, activity_log, notifications, shadow_samples, digests — and latches on a per-hour ceiling of 150 counted units (5 units/cycle × 12 cycles/hr × 2.5 safety margin). Once latched, **recovery is restart-only** (deliberate: a latch means we don't trust the state).
2. **Boot-storm false positives** — early boot cycles run with partial per-room fan-in; a naive short-circuit that compared the *running* count against a threshold fired prematurely. v5.11.0 gates the short-circuit on the fleet total and exposes a cache expiry timestamp so the operator can see when the boot-storm window closes.
3. **Notification re-fires** — the dedup TTL evaluated the firing cycle inclusively (off-by-one), letting the same key re-fire once. Fixed.
4. **Silent shadow-sample writes** — the shadow-accuracy sampler persisted without honoring the tripwire and the pruner was written but never wired to the lifecycle. Fixed; pruner is now registered on `async_setup_entry`.
5. **Promotion visibility** — no operator-facing readout for "why isn't the optimizer promoted to L2 yet?" Added `promotion_readiness` with a 7-blocker set including `window_incomplete`.

## What ships

- **D1 — Per-room sensor None-until-first-cycle:** the per-room reasoning sensor now returns `None` (not stale zero) until it has completed a first cycle; adds a `worst_open` attribute for the worst-scoring open finding.
- **D2 — Stub verdicts:** deterministic stub oracle for coordinators that have no live oracle yet; verdict is stamped on the reasoning sensor.
- **D3 — Five-channel write-volume tripwire:** counts + gates findings, activity_log, notifications, shadow_samples, and digests. Latch is restart-only recovery — this is deliberate.
- **D4 — Shadow-sample persistence + pruner:** new `optimizer_shadow_samples` table; pruner registered on lifecycle to bound growth; `shadow_accuracy_samples_count` restored across restart.
- **D5 — Notification dedup TTL fix + observability:** off-by-one fixed; `notify_dedup_active_keys` exposes live keys on the reasoning sensor.
- **D6 — Boot-storm short-circuit revert + cache:** short-circuit now gated on fleet total, not partial running count; `boot_storm_cache_expires_iso` attr shows when the boot-storm window closes.
- **D7 — Promotion readiness:** `promotion_readiness` object on `sensor.ura_optimizer_reasoning` with `ready: bool` and `blockers: list`. Seven blockers: minimum-cycle-count, minimum-shadow-samples, shadow-accuracy-floor, no-open-CRITICAL, no-recent-tripwire, no-active-boot-storm, **`window_incomplete`** (added per B-review-of-critique).
- **D8 — Reasoning logging:** structured per-cycle log line; asserted via `caplog` in tests (was source-grep, brittle).
- **D9 — Threshold + ceiling arithmetic:** ceiling 150/hr, arithmetic captured inline in `const.py` (5/cycle × 12/hr × 2.5).

### New attributes on `sensor.ura_optimizer_reasoning`
- `write_volume_alarmed_at` — ISO timestamp of tripwire latch (or `null` in steady state)
- `persistence_suspended` — bool; `true` after latch until restart
- `notify_dedup_active_keys` — list of active dedup keys with their TTL expiries
- `boot_storm_cache_expires_iso` — ISO timestamp when the boot-storm short-circuit window closes
- `shadow_accuracy_samples_count` — cumulative count of shadow-accuracy samples persisted (survives restart via RestoreEntity)
- `promotion_readiness` — `{ ready: bool, blockers: [ ... ] }` with the 7-blocker set

### New DB surface
- `optimizer_shadow_samples` table for shadow-accuracy samples used by the future L2 auto-apply promotion. Pruner registered on lifecycle (Tier-3 B-MED-2 finding).

## Falsifiable invariant (Tier-3 discipline)

**No more than 2 counted "finds-table batches" (tier-1 emit + LLM emit) shall land in the combined 5-channel write surface (findings + activity_log + notifications + shadow_samples + digests) within a single OC cycle. On tripwire latch all 5 channels are suppressed until restart.**

Two caveats recorded on the invariant:
1. Invariant is **per-cycle, not per-finding**. Future L2 auto-apply promotion will emit per-finding activity rows, legitimately exceeding 2/cycle at high finding counts — re-tune threshold and unit at promotion time (cross-ref: optimizer-autonomy campaign backlog).
2. **Ceiling arithmetic:** 5 counted units/cycle × 12 cycles/hr × 2.5 safety margin = **150/hr**. Re-tuned from the plan's initial 60 during Tier-3 D-LOW-1.

## Review / gate (Tier 3)

**4 framing-disjoint reviews + validator + orchestrator independent verification + D re-enumeration.** Findings: 8 HIGH / 5 MEDIUM / 7 LOW — all HIGH and MEDIUM fixed in commit `2a755e0d` (1 LOW pre-existing NM signature-drift deferred to its own hotfix). Review C mutation table covers **12 sites** — 9 caught first pass; 3 GREEN sites (activity_log, digest, shadow-sample persist gates) were unanchored gaps corresponding to B-HIGH-1 / D-HIGH-1 / D-HIGH-2 and are now anchored by named tests. **Orchestrator independently re-mutated the F1 chokepoint** (`_log_activity` gate bypass): 1 failed (`test_log_activity_suppressed_after_latch`), byte-identical restore → green. **D re-enumeration: SHIP, all 4 clauses HELD, no N+1th site.** Review doc: `docs/reviews/code-review/v5.11.0_oc_hardening.md`.

**Bug Class #53 (computed-but-not-consumed) appeared 4 times this cycle** (channel-blind tripwire × 3 + pruner not on lifecycle × 1). Two new candidate bug classes recommended for `docs/QUALITY_CONTEXT.md`: **"tripwire/telemetry blind to the channel it was built for"** and **"partial state consumed as final."**

## Pre-deploy row-rate snapshot — MANDATORY (Tier 2-DB / Tier 3)

Run these on the live DB **before** deploying so the ±25% comparison is possible post-restart:

```sql
-- 1. Findings write rate by (coordinator, severity) — last 7 days
SELECT coordinator, severity, DATE(created_at) AS d, COUNT(*)
FROM optimizer_findings
WHERE created_at >= datetime('now', '-7 days')
GROUP BY coordinator, severity, d ORDER BY d, coordinator, severity;

-- 2. Activity log write rate for optimizer events — last 7 days
SELECT DATE(created_at) AS d, COUNT(*)
FROM ura_activity_log
WHERE source = 'optimizer' AND created_at >= datetime('now', '-7 days')
GROUP BY d ORDER BY d;

-- 3. Shadow samples baseline (should be 0 pre-deploy)
SELECT COUNT(*) FROM optimizer_shadow_samples;  -- expected: 0 (or table missing pre-migration)
```

Save output to `docs/reviews/code-review/v5.11.0_row_rate_snapshot.md` before running `./scripts/deploy.sh`.

---

## Acceptance

```yaml
version: 5.11.0
hypotheses:
  - id: H1
    name: ura_v5110_deployed
    description: URA v5.11.0 is the running HACS-installed version and all entries load.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: update.universal_room_automation_update, attribute: installed_version }
    expected: { condition: "==", value: "v5.11.0" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H2
    name: promotion_readiness_visible
    description: Reasoning sensor exposes promotion_readiness with the 7-blocker set within 1 cycle.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: sensor.ura_optimizer_reasoning, attribute: promotion_readiness }
    expected: { condition: "!=", value: "unknown" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 24h }
  - id: H3
    name: no_error_storm
    description: No recurring URA error mentioning optimizer.
    oracle: home_assistant
    query: { kind: home_assistant.log_count, search: "universal_room_automation.*optimiz", period: 24h }
    expected: { condition: "<", value: 5 }
    window: { first_check_after: 1h, confirm_after: 24h, alert_if_violated_after: 72h }
  - id: H4
    name: activity_log_bounded
    description: OC rows in ura_activity_log stay ≤2/cycle over 3 consecutive cycles.
    oracle: ura_sqlite
    query: { kind: sql, statement: "SELECT COUNT(*) FROM ura_activity_log WHERE source='optimizer' AND created_at >= datetime('now','-3 minutes')" }
    expected: { condition: "<=", value: 6 }
    window: { first_check_after: 30m, confirm_after: 2h, alert_if_violated_after: 24h }
```

## Live Validation — Validated 2026-07-10

Combined release v5.11.0 shipped this cycle alongside v5.10.0 Music Following. HA restarted 2026-07-10 17:32 CDT; validation window 17:40-18:05 CDT.

| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | **Deploy healthy.** `installed_version == v5.11.0`; all entries loaded; zero URA ERROR mentioning `optimiz` in boot log. | PASS | 41/41 entries loaded; 0 optimizer ERRORs; no recursion / setup_error / watchdog. |
| L2 | **Promotion readiness visible within 1 cycle.** `sensor.ura_optimization_coordinator_optimizer_reasoning` attr `promotion_readiness` present with the 7-blocker set. | PASS (spec-nuanced) | Attr present after cycle 1 with per-DIMENSION structure (`comfort`, `occupancy_accuracy`) each `ready=false`, `blocked_by=[samples_below_min, shadow_accuracy_not_ready]`. **Spec correction:** the README prospective wording said a flat blocker list; the implementation is **per-dimension with only currently-FIRING blockers listed** (confirmed by-design against `optimization.py :: _compute_promotion_readiness`). Wording corrected here; behavior correct. |
| L3 | **Steady-state persistence gates.** `persistence_suspended == false` and `write_volume_alarmed_at == null`. | PASS | Both confirmed on the reasoning sensor after cycle 4. Tripwire armed, not latched. |
| L4 | **Shadow-sample table writes real values within 1h.** Non-zero rows with non-NULL, non-sentinel payload columns within 60 min. | PASS (table) / PENDING (rows) | Table exists with correct schema + indexes; 0 rows at +28 min = **warming-up** (samples require shadow findings to mature past observe-delay), NOT the sentinels-only failure shape that broke v4.6.1.1 / v4.6.3-initial. First full-persist cycle at 22:52 UTC seeded `comfort` + `occupancy_accuracy` shadow findings. |
| L5 | **Activity-log rate bounded ≤2 rows/cycle.** OC contribution to `ura_activity_log` ≤ 6 across 3 consecutive cycles. | PASS | Cycle 4: exactly 2 rows (`shadow_cycle_summary` + `clamped_cycle_summary`). Settle cycles 1-3: 0 rows — **F2 skip-path write-quiet fix observed live**. |
| L6 | **Zero URA ERROR logs mentioning optimizer.** | PASS | 0 entries in the post-restart window. |
| L7 | **Shadow-count survives restart** (RestoreEntity, anchors C-HIGH-2). | PENDING-ORGANIC | Requires `shadow_accuracy_samples_count > 0` before a subsequent restart; today's warm-up floor is 0. |
| L8 | **Boot-storm cache attr observable.** `boot_storm_cache_expires_iso` present within 1 cycle. | PASS | `boot_storm_cache_expires_iso = 2026-07-10T23:22:29Z` visible on the reasoning sensor after cycle 4. |
| L9 | **`dimension_verdicts` stub tokens** stamped by D2. | PASS | On `sensor.ura_optimization_coordinator_optimizer_status` (NOT the reasoning sensor — validator initially looked at the wrong entity; correcting the reference here): `automation_responsiveness` / `energy_efficiency` / `setpoint_compliance` all = `"stub"`. |
| L10 | **Row-rate ±25% vs pre-deploy snapshot.** | PASS | Pre-restart cycle 16 findings vs post-restart cycle 4 15 findings; `ura_activity_log` optimizer rows 2/cycle vs pre-deploy ~1.6/cycle avg — within band, no flood. |
| L11 | **META excluded from findings-sensor state.** | PASS | Findings sensor state = a real `prediction_accuracy` finding text, not `"meta"`. META row `90640` present in DB but correctly not surfaced as sensor state. |

### In-suite proven, not live-testable
- **Tripwire latch semantics** (restart-only recovery): proven in-suite via `test_log_activity_suppressed_after_latch` + F1 chokepoint mutation. Live-testing would require synthesizing a write-flood — deferred.
- **Notification dedup off-by-one:** proven in-suite via `test_notify_dedup_ttl_off_by_one`. Live re-fire is timing-sensitive and unreliable to trigger organically.

**Validation notes.** Optimizer status reads `degraded` due to 8 HIGH `sensor_health` findings from boot-unavailable rooms — the optimizer is **correctly reporting a real pre-existing condition**, not a deploy regression. Boot-only transients dismissed: settle cycles 1-3 emit META-only rows by design; the F2 skip-path write-quiet gate was observed to hold (0 activity-log rows on those cycles). Shadow-sample row seeding (L4 rows-level) and shadow-count restart survival (L7) both depend on shadow findings maturing past the observe-delay — expected within the first 24-48h of normal operation.
