# URA v5.26.0 — NM Cycle B: Safety Rails

CRITICAL-notification safety machinery for the Notification Manager, per
`docs/planning/PLANNING_nm_overhaul_2026_07.md` Cycle B. NM remains in
observe mode live (blank per-person targets) — this machinery ships dark and
is proven at the action boundary in-suite. Review record:
`docs/reviews/code-review/v5.26.0_nm_cycle_b.md` (Tier 2-DB; 1 CRITICAL +
4 HIGH + 6 MED found, all fixed or ratified-open; dry-run gate completeness
PROVEN across all 8 outbound sites; 7/7 mutations killed incl. 2
orchestrator-run).

## What ships

1. **B0 dry-run gate** — `switch.ura_nm_dry_run` (RestoreEntity + CM-options
   writeback so NM reads it at construction; kill-switch: ON = zero outbound).
   Every gated send writes a `dry_run=1` row to `notification_log` (additive
   guarded column migration; existing readers name-keyed, unaffected).
2. **Life-safety cadence** — CRITICAL repeats at 30s for the life-safety
   vocabulary (smoke, fire, carbon_monoxide, water_leak, flooding, intruder,
   freeze_risk, gas — see const.py), 300s otherwise. Vocabulary is
   authority-tested: every member must be an actually-emitted token
   (countermeasure for the `"intrusion"`/`"intruder"` CRITICAL caught in
   review). Safe-word ack stops repeats; ack registry (20-episode cap)
   persists via the NM diagnostics sensor with a late-restore cancel path;
   DB `acknowledged=0` filter remains the primary restart protection.
3. **Per-channel token buckets** — capacity 10 / refill 6 per min defaults,
   live-tunable via two NM Numbers (reload-suppressed options writeback;
   refill=0 documented kill-switch: non-life-safety stops once drained).
   ONE token per channel per notification (post-pref-checks); life-safety
   CRITICAL bypasses entirely; dry-run evaluates but never burns.
   Overflow is an honest DROP COUNTER (`overflow_dropped_total` + recent
   ring) — real drain deferred to Cycle C's routing rework (plan amended).
4. **Boot settle** — 60s duplicate-collapse window per (coordinator, hazard);
   life-safety CRITICAL never collapses.
5. **NM sensor attrs**: `dry_run_active`, `overflow_dropped_total`,
   `bucket_capacity_remaining_per_channel`, `active_ack_registry_size`, etc.

## Open policy question (operator)

`overheat` / `high_co2` CRITICALs intentionally NOT life-safety-cadenced this
cycle (paging-fatigue tradeoff) — ratify or amend; recorded in the plan.

## Test evidence

7275 passed; failure set = pre-existing env-drift baseline (36+14), zero new.
Write-volume regression tests: sensor reads and idle ticks produce 0 DB rows.

## Live Validation (prospective — write back observed results post-restart)

| # | Criterion | How to check |
|---|---|---|
| L1 | Clean boot: CM + NM load, no URA ERROR logs, house state resolves | log scan + sensors |
| L2 | `switch.ura_nm_dry_run` + 2 bucket Numbers exist on NM device; defaults OFF / 10 / 6.0 | entity registry |
| L3 | NM sensor shows new attrs (dry_run_active false, buckets at capacity, ack registry 0) | live attributes |
| L4 | Bucket Number turn does NOT reload CM (sibling last_changed invariant) | operator-exercised |
| L5 | notification_log migration applied (dry_run column present; existing rows intact) | DB read via MCP |
| L6 | 24h: notification shape unchanged vs pre-deploy (machinery dark, observe mode) | recorder next evening |
