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

## Validated 2026-07-18 ~04:30 CDT (post-restart)

| Criterion | Result | Evidence |
|---|---|---|
| Write discipline in production | PASS | `SELECT COUNT(*) FROM ura_activity_log WHERE action LIKE 'fan_recheck%'` = **0** with the house live and rooms ticking — vetoed evaluations write nothing, exactly as the 50-tick spy test promised. |
| Veto counters visible | **PASS (closed 2026-07-18 morning restart)** | `sensor.living_room_living_room_fan_recheck_state` materialized: `fan_recheck_eval_count: 1`, `fan_recheck_veto_counts: {not_occupied: 1}` — the instrumentation counted its first eligibility evaluation with a named veto reason on the first post-restart tick. Data harvest confirmed operational. |
| Rider: Lovesac v0.2 | **PASS, richly** | All new entities live under the media_room device: input sensor + select AGREE ("HDMI-ARC"), sound_mode "Movies", audio capability "Dolby Digital 5.1 / PLII (ARC only)", **real firmware over the wire: MCU 1.71 / DSP 1.68 / EQ 1.23**, control_link ON, last_contact 09:28Z, layout_raw=5 covering_raw=1 arm_type=4 (first enum-corpus data), sync button present. Operator's earlier EQ changes (treble 16, balance 59) survived the restart. |
| Regression | PASS | Zero URA ERROR entries; house `home_night`; BAEC switch ON; v5.21.0/v5.22.0 surfaces undisturbed; no fan-recheck arms attributable to instrumentation (0 rows). |
| Suite | PASS | Recheck filter 86/1 at merge; full suite 36F/14E pre-existing envelope at deploy. |
