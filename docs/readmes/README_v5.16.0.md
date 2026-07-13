# URA v5.16.0 — Overnight Wave: presence trust · zone-delete guard · Envoy write-verification · census BLE-cancel · energy pause hygiene

Five cycles + one rider, built and reviewed 2026-07-12/13 in one overnight
wave (16 framing-disjoint reviews + 2 focused re-passes across the wave;
6 CRITICALs and ~23 HIGHs found and fixed pre-deploy — none shipped).
Review records: `wave2026_07_13_presence_zone_writeverify.md`,
`wave2026_07_13_hygiene_blecancel.md`, pre-deploy snapshot
`v5_16_0_pre_deploy_snapshot.md`.

## What operators will notice

1. **The house can sleep past a false "guest".** A guest state whose
   trigger has cleared now exits during sleep hours (GUEST → HOME_NIGHT →
   SLEEP within ~2 ticks) instead of pinning the house awake until 06:00
   (the 2026-07-11 incident). Real guests still hold the house awake.
   A genuine late guest arriving 21:00-22:00 can now flip the house to
   GUEST (previously silently rejected).
2. **Far fewer false guests at all.** Camera census now lets phone (BLE)
   presence excuse an unrecognized camera detection in the same area —
   residents crossing the foyer without a face match stop counting as
   strangers. Real guests (no resident correlate) still arm the gate at
   the same latency; departed/stale phone fixes cannot excuse anyone.
   Rides with the census interior hold returning 15→3 min (applied at
   this deploy). Diagnostic: `ble_cancelled_count` on the house census
   sensor. (A config kill-switch for the BLE excusal is queued as a
   post-wave hotfix if wanted.)
3. **An empty house stops flapping.** When every tracker is LOST-away AND
   census, unidentified, and (debounced) zone signals all agree the house
   is empty for ~3 consecutive ticks, the away-veto engages immediately
   instead of waiting out a 60-minute grace. The grace still protects the
   BLE-dropout-while-home case in full.
4. **Zone deletes can't knock out live HVAC.** The v5.14.0 delete flow's
   prune can no longer kill a live merged HVAC zone that shares the
   deleted house zone's name (the 2026-07-12 5-hour zone_1 outage class);
   the boot migration can no longer mint phantom compound zones; deleting
   a thermostat-carrying zone now actually resolves its zone id (a dead
   lookup slot was repaired — id-keyed purge is genuinely active for the
   first time, protected by the new guard).
5. **URA now verifies its battery commands.** Every reserve /
   charge-from-grid / battery-mode write is checked ~15 min later against
   the Enphase CLOUD (catching Enphase's accept-then-revert behavior the
   operator observed), with a per-cycle reversion sweep, transition-latched
   anomalies, and a once-per-day NM alert per surface+type. Firmware
   8.2.4225+ killing local writes will be detected the morning it lands,
   not via a drained battery. SOC reads gain a cloud fallback
   (unit-guarded) for Envoy outages like 2026-07-12's subnet hop. The four
   cloud oracle entities are configurable (Coordinator Manager → energy →
   Cloud Verification section; blank disables a surface). Cloud WRITE
   failover ships dormant (scaffolding only).
6. **EV/plug pauses can't be orphaned, and L1 plugs finally start
   themselves.** Flipping off TOU management / excess-solar / grid-cap
   now releases that feature's pauses within a cycle (previously pinned
   forever, surviving restarts). L1 plugs get the same per-tick off-peak
   ensure-on as the L2 EVSEs — a car plugged in after midnight charges
   without a manual flip (the 2026-07-13 01:04 incident) — with identical
   owner precedence including the grid-charge breaker cede (L1 ≡ L2 by
   operator principle).
7. Riders: MF health sensor now exposes `current_house_state` (v5.10.0 H2
   oracle repaired); substrate rooms expose `last_edge_entity` (pins the
   next noisy sensor in minutes); v5.15.0's EVSE-hold ledger gap
   (E-MED-1) closed via the single-writer park ledger.

## Fixed defect classes (full detail in the wave review records)

- Tautological guard limb deleting grace + debounce (presence CRITICAL,
  triple-confirmed) → sustained-external-empty discriminator.
- Dead-import guard = incident fix that never ran (zone CRITICAL) →
  import fixed + pure-helper runnable behavioral tests.
- Write-only config section (write-verify CRITICAL, Bug Class #55) →
  flattened per the inclement pattern.
- Missing-hunks-from-tree-contention census crash (BLE CRITICAL, v5.8.0
  class) → field restored + end-to-end construction test; parallel
  builders now isolate in worktrees.
- Verification blackout via two-writer ledger ping-pong (hygiene HIGH,
  convergent) → single-writer-per-tick.

## Acceptance

```yaml
version: 5.16.0
hypotheses:
  - id: H1
    name: ura_v5160_deployed
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: update.universal_room_automation_update, attribute: installed_version }
    expected: { condition: "==", value: "v5.16.0" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H2
    name: guest_arm_rate_drops
    description: Guest-gate arming events/day drop ≥60% vs the 2-4/day baseline (BLE-cancel L1 bar + census hold 3min).
    oracle: home_assistant
    query: { kind: home_assistant.history, entity: sensor.ura_presence_coordinator_presence_house_state, period: 72h }
    expected: { condition: "guest_entries_per_day <= 1" }
    window: { first_check_after: 1d, confirm_after: 3d, alert_if_violated_after: 7d }
  - id: H3
    name: write_verify_first_pass
    description: First URA reserve write post-deploy verifies against the cloud oracle within ~20 min (verified_write attrs populate; no unit-mismatch anomalies).
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: sensor.ura_energy_coordinator_battery_strategy, attribute: last_verified_write }
    expected: { condition: "populated_within", value: "2h" }
    window: { first_check_after: 30m, confirm_after: 4h, alert_if_violated_after: 24h }
  - id: H4
    name: no_anomaly_volume_regression
    description: anomaly_log + ura_activity_log 24h rates within ±25% of the pre-deploy snapshot (absent a real event); write_verification anomalies transition-latched (no per-window spam).
    oracle: ura_sqlite
    query: { kind: sqlite.row_rate_compare, baseline: docs/reviews/code-review/v5_16_0_pre_deploy_snapshot.md }
    expected: { condition: "within_25pct" }
    window: { first_check_after: 1d, confirm_after: 2d, alert_if_violated_after: 3d }
```

## Live Validation — Validated 2026-07-13 (deploy restart 10:53 CDT)

| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Deploy healthy; zero URA errors; census pipeline alive | **PASS (4 boot transients noted)** | `installed_version=v5.16.0`; census sensors updating post-boot (`persons_in_house=2` at 10:57); ZERO occurrences of the B-C1 crash signature ("Census periodic update failed"). Four boot-window "DB write worker not running" ERRORs at 10:53:26-35 (setup-ordering race, pre-existing class — 1 occurrence at the v5.15.0 boot, 4 here; boot-only, none post-setup; **filed as a small Tier-1 candidate: start_write_worker before first logging consumers**). |
| L2 | census_hold_interior=3 LIVE | **PASS** | Applied via the restart-window edit (core-down at +3s, written pre-boot-read); post-boot read-back = 3 (survived, vs the 2026-07-12 running-HA clobber). Guest-arming rate comparison runs over the next 48-72h (H2). |
| L3 | ble_cancelled_count present | **PASS (present, =0)** | Attr live on `sensor.universal_room_automation_persons_in_house`; 0 is correct at validation time (unidentified=0, nothing to cancel). Increment check rides the next resident common-area pass without a face hit. |
| L4 | Sleep transition works the next guest-straddles-22:00 evening: GUEST exits by gate-clear + ~12 min chain (300s exit persistence + hysteresis) | house-state history on the next false-arm evening (PENDING-ORGANIC) |
| L5 | Empty-house: next full-family departure engages AWAY within ~5 min with veto_path=lost_admitted_immediate, NO flap cycle | house-state sensor attrs + history (PENDING-ORGANIC) |
| L6 | Write-verify: first reserve write verifies (H3); flip charge_from_grid in the Enphase app once → NM alert within ~20 min (operator-staged reversion test) | battery-strategy attrs + NM |
| L7 | Zone delete guard: create + delete a disposable test zone sharing no thermostat → clean purge; the compound-name scenario is covered in-suite (live re-test optional) | operator-staged, optional |
| L8 | Plug ensure-on: tonight's off_peak turns designated L1 plugs ON within 2 cycles of 21:00 (no car needed — switch-on is the observable) | plug switch history |
| L9 | Toggle-release: flip excess-solar OFF while a fill-priority pause is active on a test device → released within 2 cycles, no turn_on if TOU-paused | operator-staged, optional |
| L10 | Reserve verification NOT blacked out during an EVSE hold (the hygiene HIGH): during tonight's charge session, last_verified_write for reserve still completes | battery-strategy attrs during charging |
