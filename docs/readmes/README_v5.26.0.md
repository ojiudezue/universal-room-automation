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

## Live Validation — Validated 2026-07-20 (restart, boot 21:36 CDT)

| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Clean boot, no URA ERROR logs | PASS | Zero URA ERROR lines after 21:36 boot; house state `home_night` by 21:38:19. |
| L2 | Dry-run switch + bucket Numbers exist w/ defaults | PASS | `switch.ura_notification_manager_dry_run` = off; `number.ura_notification_manager_rate_limit_bucket_capacity` = 10; `number.ura_notification_manager_rate_limit_refill_rate` = 6.0. |
| L3 | New NM diagnostics attrs | PASS | `sensor.ura_notification_manager_notification_diagnostics`: dry_run_active false, all 6 channel buckets at 10, overflow_dropped_total 0, active_ack_registry_size 0. |
| L4 | Bucket Number turn does not reload CM | PENDING-OPERATOR | Exercise via UI; sibling last_changed invariant. |
| L5 | notification_log migration | PASS | `dry_run` column present (INTEGER DEFAULT 0, col 14) via live DB read; table intact (0 rows — consistent with observe mode + Cycle A quieting). |
| L6 | 24h notification shape unchanged | PENDING-24H | Due 2026-07-21 evening with the v5.24/v5.25 checks. |

Non-this-deploy observation logged during validation: single pre-restart
ERROR at 21:02 — `Energy: failed to execute switch.turn_on on
switch.garage_a` (v5.25.0 era, right after off-peak start; likely a
momentary EVSE switch unavailability). One occurrence, no recurrence
post-boot; watch organically — if it recurs at off-peak boundaries,
investigate the EV ensure-on retry path.
