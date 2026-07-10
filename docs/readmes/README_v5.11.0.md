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

## Live Validation — to populate post-restart (write-back rule)

Concrete criteria to verify against the running HA instance. Every row must record PASS/FAIL with the observed evidence (entity_id + attribute or DB row) before the cycle is closed.

- **L1 Deploy healthy:** `update.universal_room_automation_update` `installed_version == v5.11.0`; 40/40 entries loaded; zero URA ERROR mentioning `optimiz` in boot log.
- **L2 Promotion readiness visible within 1 cycle:** `sensor.ura_optimizer_reasoning` attr `promotion_readiness` present with `ready == false` and a `blockers` list containing at least the boot-transient blockers (minimum-cycle-count, minimum-shadow-samples, `window_incomplete`).
- **L3 Steady-state persistence gates:** `sensor.ura_optimizer_reasoning` attrs `persistence_suspended == false` and `write_volume_alarmed_at == null` in steady state (i.e. the tripwire is armed but not latched).
- **L4 Shadow-sample table writes real values within 1h:** `SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM optimizer_shadow_samples;` must show non-zero rows with non-NULL, **non-sentinel** payload columns within 60 minutes of restart. **Sentinels-only = payload shape broken** — this is the Tier 2-DB rule that would have caught v4.6.1.1 and v4.6.3-initial. Cite the concrete row.
- **L5 Activity-log rate bounded:** across 3 consecutive OC cycles (≈15 minutes) the OC contribution to `ura_activity_log` stays ≤2 rows/cycle. `SELECT COUNT(*) FROM ura_activity_log WHERE source='optimizer' AND created_at >= datetime('now','-3 minutes')` ≤ 6 at any sample.
- **L6 Zero URA ERROR logs mentioning optimizer:** `ha_search_logs "optimiz" ERROR` over 24h post-restart returns 0.
- **L7 Shadow-count survives restart:** note `shadow_accuracy_samples_count` on the reasoning sensor pre-restart-2, restart, verify the counter resumes at ≥ the pre-restart value within 1 cycle (RestoreEntity proof — anchors C-HIGH-2).
- **L8 Boot-storm cache observable:** `boot_storm_cache_expires_iso` attr present on the reasoning sensor within 1 cycle of restart and clears (goes null) after expiry. Boot-transient — dismiss once cleared.

### In-suite proven, not live-testable
- **Tripwire latch semantics** (restart-only recovery): proven in-suite via `test_log_activity_suppressed_after_latch` + F1 chokepoint mutation. Live-testing would require synthesizing a write-flood — deferred.
- **Notification dedup off-by-one:** proven in-suite via `test_notify_dedup_ttl_off_by_one`. Live re-fire is timing-sensitive and unreliable to trigger organically.

_(A `Validated <date>` table with observed evidence per criterion will replace this prospective list before the cycle is closed, per the README write-back rule.)_
