# URA v5.23.0 — Fan-Recheck Observability

Instrumentation-only release: makes the v4.7.22 Mode-2 fan-recheck mechanism
observable so the loosening decision (docs/planning/ANALYSIS_fan_recheck_loosening_options.md)
can be made from data. NO state-machine behavior change (review-verified
gate-by-gate: 19/19 veto substitutions one-for-one, 3/3 authorize points
untouched). Review record: `docs/reviews/code-review/fanrecheck_observability_tier1.md`.

## What ships
1. **Durable event rows** in `ura_activity_log` on ARM / OUTCOME / CANCEL
   transitions only (actions `fan_recheck_arm` / `fan_recheck_outcome` /
   `fan_recheck_cancel`; outcome rows carry `cancel_driven` so analytics
   never double-count terminal events). Write-flood-guarded: a vetoed
   eligibility tick writes NOTHING (50-tick spy regression test).
2. **17 named veto-reason counters** + per-room evaluation denominator,
   RAM-only, exposed as attributes on the existing
   `sensor.<room>_fan_recheck_state` — excluded from recorder history via
   `_unrecorded_attributes` (mechanism verified against installed HA source,
   entity.py:518) so enabling the sensor for the data harvest cannot become
   a state-write amplifier.
3. `get_aggregate_counters()` reserved for a future presence-level
   diagnostics surface (not wired; loosening memo §9 is its consumer).

## Rider at this restart
`custom_components/lovesac_stealthtech` **v0.2** (non-URA sibling project,
Tier 2-DB reviewed in its own repo) replaces the v0.1 copy — optimistic
writes + post-write refresh, input sensor/select, sound-mode select,
audio-capability + firmware + connection-health diagnostics, sync button,
Quiet Couch Mode polish. Public release imminent from
github.com/ojiudezue/ha-lovesac-stealthtech.

## The data clock
From this restart, veto counters and event rows accumulate:
- **~2 weeks:** `veto_house_sleep` split by room-type/zone decides promotion
  of loosening candidate (c) (SLEEP veto narrowed to sleep-relevant zones).
- **~4 weeks (ideally spanning a travel week):** `veto_high_still_risk_type`
  × whole-house-BLE-absence windows decides the Tier-3 (b)+(i) evaluation.

## Live Validation (prospective — write back post-restart)
- **Live:** `sensor.<room>_fan_recheck_state` attrs show `fan_recheck_eval_count`
  incrementing and `fan_recheck_veto_counts` populating for an eligible room
  (enable one room's sensor to check; it is disabled-by-default).
- **Live:** zero `fan_recheck_*` rows in ura_activity_log absent a real
  arm/outcome/cancel (write discipline holds in production).
- **Live (rider):** Lovesac v0.2 entities appear (input select + sensor,
  audio capability, firmware versions, control link, sync button); input
  sensor agrees with media_player source.
- **Regression:** zero URA ERROR lines; BAEC + BLE extend-not-create
  (v5.21.0/v5.22.0) undisturbed; fan-recheck state machine behavior
  unchanged (no new arms attributable to the instrumentation).
- **Suite:** recheck filter 86/1; full suite within pre-existing envelope.
