# AUDIT: Envoy reserve oracle history - local sensor vs cloud number (2026-10-23)

Read-only probe. Run Fri 2026-10-23 19:27-19:35 CDT (`date`; = 2026-10-24 00:27-00:35 UTC). Times below are UTC unless marked CDT.
Prober: ura-prober. Trigger: operator challenge to the proposal "make the reserve release deadband and the 'Envoy write not applied' CRITICAL trust the LOCAL Envoy reserve sensor over the stale CLOUD number", based on one observation (`docs/planning/AUDIT_envoy_reserve_98_alert_2026_10_23.md`).
Not read: HVAC / presence state-of-play (not relevant). No state was changed.

Entities: LOCAL = `sensor.envoy_482543015950_reserve_battery_level` (official `enphase_envoy`, unique_id `482543015950_reserve_soc`; memory `project_battery_soc_envoy_not_span.md` correction 2026-10-18). CLOUD = `number.iq_battery_hacs_battery_reserve` (`enphase_ev`, the WRITE leg). FROZEN = `number.enpower_482348004678_reserve_battery_level` (a third entity, not the local sensor; do not conflate).

## 0. Answer first

1. The operator is right that one test proves little, but the evidence is not one test. This audit finds: 4 stale-cloud episodes in the last 5 days (recorder), 3 more earlier in October (prior audits), 2 in July (B0 probe, behavioural plan), and a behavioural scorecard in which the LOCAL sensor predicted what the battery did in 554 of 558 decisive minutes versus 2 for the cloud number.
2. "Trust local over cloud" for the release-deadband and the not-applied CRITICAL is SUPPORTED as a direction. It is NOT sufficient as stated, and a blanket swap has real failure modes (section 5). It needs a different design: local is the primary reading of what the gateway enforces; cloud is a corroborating reading of what Enphase's cloud believes; DISAGREEMENT with a healthy local is itself a classified signal (not a "write not applied" CRITICAL).
3. A new finding that changes the fix: even a deadband that trusts local will not release today's stuck reserve, because the write goes through `enphase_ev` `BatteryReserveNumber.async_set_native_value`, which returns early when the value equals the cloud-side selected value (section 4.3). Writing 10 while the cloud thinks 10 and the gateway holds 98 is a no-op at the integration.
4. Staleness of the cloud number is NOT rare in October: of 28 distinct reserve changes since 10-16 the gateway followed 25 and the cloud number followed 22 (section 3.2); after 10-19 18:26 the cloud missed 5 of 11. Cloud-stale time was about 23% of wall-clock since 10-16.

## 1. Why writes are cloud-first (provenance)

| What | Source |
|---|---|
| Decision commit | `114043a89` "Hotfix H1 (pre-review): cloud-first battery writes for all three surfaces", 2026-07-13 11:42 CDT (git log -S ENERGY_CLOUD_FIRST_WRITES on `domain_coordinators/energy_const.py`). |
| Stated reason | `energy_const.py:524-533`: "live evidence on firmware 8.3.5167 shows local Envoy writes are accepted-then-ignored - the hardware follows the Enphase cloud leg. The LOCAL entities remain configured for use as a SECONDARY WITNESS". Comment ends "operator directive: rip off the band aid". |
| Concrete evidence in the commit | Only a unit-test docstring, "~11:21 tripwire condition": local `switch.enpower_*_charge_from_grid` read ON (lying) while the cloud switch read OFF, so a local-read intent check suppressed re-dispatch (`quality/tests/test_energy_write_verification.py`, H1 addendum tests). The raw 07-13 live transcript is not in the repo. |
| Scope of that evidence | WRITE entities (Enpower number/switch/select), i.e. which leg to COMMAND. It says nothing about whether the local reserve SENSOR is an honest READ of what the gateway enforces. |
| Restated later | EC manual 2.6 ("on Envoy firmware 8.3.x, local writes are accepted-then-ignored", `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md:265-278`); `PLANNING_enphase_cloud_reliance.md` exec summary; kanban EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 ("local battery writes have gone via the cloud since firmware 8.2.4225"). Firmware date is inconsistent across docs (8.2.4225 vs 8.3.5167); I did not verify either. |
| Counter-note | EC manual 2.6a correction 2026-10-06: a local `switch.enpower_*_charge_from_grid` `turn_off` DID take effect (OFF ~2 min after the command), "contrary to the earlier assumption". So "local writes ignored" is not universal. Not re-tested for the reserve number. |
| Bearing on the proposal | None directly. The proposal changes how URA READS (deadband, alert), not where it WRITES. Cloud-first writes stay. |

## 2. Known failure modes of each source (with dates)

### 2.1 CLOUD `number.iq_battery_hacs_battery_reserve` - wrong or stale

| Date | Failure | Evidence |
|---|---|---|
| 2026-07-15 | Cloud echoed commanded 80 while hardware had been knocked to 50; battery discharged 83 to 66, about 5 kWh. LOCAL sensor was right ("told the truth the whole time"). | `PLANNING_behavioral_write_verify.md` lines 17-22 and B0-D1 table row 5 (cmd 80, hw 50). |
| 2026-07-16 | Cloud app showed 15 while hardware enforced 61 (~70 min lag); cloud aggregate SOC 86.8 vs local 60-62. | `PLANNING_enphase_cloud_reliance.md` 40-48. |
| 2026-07-10 to 07-11 | A write took 20.7 h to apply (pending at Enphase); gateway held 10 while cloud ledger said 20. | B0-D2 apply-lag table (max 74,569 s). |
| 2026-10-11, 10-12 | `write_verification_failed` rows with cloud oracle 81 / 14 while the local sensor already equalled the commanded 15 / 20 / 90. | `AUDIT_envoy_reliability_recount_and_witness_reconcile.md` section 4 item 8. |
| 2026-10-14 | Cloud number held 6.0 with no state update for 6.5 h while the local sensor went 6, 8, 10; 49 resends of 10. | same audit item 6; kanban EC-SELFHEAL card `measured_2026_10_17_overnight` (3). |
| 2026-10-19 to 10-20 | Cloud 98 for ~8.5 h after release to 10 (section 3). | recorder, this audit. |
| 2026-10-22 to 10-23 | Cloud 10 while gateway held 15 then 13 for ~28 h (section 3); false CRITICAL 10-22 01:21 CDT "reserve_soc=15, cloud reports 10.0". | recorder; kanban EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 `INSTANCE_2026_10_22_stale_cloud_false_critical`. |
| 2026-10-23 | Cloud 10 while gateway held 98 for 4.8 h (the alert under challenge). | `AUDIT_envoy_reserve_98_alert_2026_10_23.md`; recorder. |

Why the cloud number goes stale: UNKNOWN. Facts: `enphase_ev` default scan 60 s, `battery_status` 300 s, repeated 429 backoffs (~1 h) in its health payload, observed entity writes 15-22 min apart (`PLANNING_envoy_local_witness_and_solar_follow.md` 0.1; measured cloud SOC value-change gaps p50 669-947 s, p95 1,725-3,225 s in `AUDIT_envoy_mqtt_trust_measurement.md` 3.4). The reserve entity's value is `current_control_value(coord, "battery_reserve", "reserve", battery_selected_backup_percentage)` (`/config/custom_components/enphase_ev/number.py:362-372`, `control_updates.py:268`), i.e. the cloud settings payload plus a runtime overlay. It is NOT unavailable when stale: cloud-number unavailable time was only 22 min in 181 h, so an availability gate cannot detect staleness (recount audit 4 item 6; kanban 10-13 retraction "last_reported shows the cloud polls normally").

### 2.2 LOCAL `sensor.envoy_482543015950_reserve_battery_level` - wrong, stale, or missing

| Date | Failure | Evidence |
|---|---|---|
| 2026-06-16 | Memory called it a "FROZEN secondary readout" (1-3 states in 24 h) and attributed it to `enphase_ev`. SUPERSEDED: ownership and role were corrected 2026-10-18 (official `enphase_envoy`, tracks the real reserve). The June finding was probably the Enpower NUMBER or low change volume; not re-derived. | `project_battery_soc_envoy_not_span.md` CORRECTION 2026-10-18. |
| 2026-06-12 | Local Envoy availability coupled to URA boot (after_dependencies stranding, one-shot validation race, restore poisoning). Fixed v5.3.7. | `project_envoy_boot_incident_2026_06_12.md`. |
| 2026-07-12, 07-16, 07-21 | Local Envoy dropouts; 07-21 84-min blind window. Unavailability 7-29 events/day (production sensor), 17% >30 min. | `PROBE_envoy_outage_frequency.md`. |
| 2026-09-18 to 09-26 | Native integration flapping 109-163 down-events/day; upstream cause `EnvoyClientClosedError` not subclassing `EnvoyError`; "a core update will NOT fix it". | memory `project_session_pickup_2026_09_23.md` section 1; `AUDIT_envoy_mqtt_trust_measurement.md` 3.6. |
| 2026-10-15 to 10-17 | After Ethernet + GC freeze, blips fell but long outages 586 min and 714 min and one open from 10-17 23:08; `/info` answers while authenticated `/ivp/pdm/device_data` hangs, needs gateway reboot. | recount audit 3.1. |
| 2026-10-16 to 10-24 (this audit) | Unavailable 808 min of 181.6 h = 7.4%, 11 episodes, longest 461 min. | recorder, section 3.1. |
| 2026-09-25, 09-26 | Reboot partial-fleet junk: MQTT STREAM SOC 87 to 20, then SOC 0 and backup_reserve 0 then 30 for ~36 s. This is the stream add-on path, not the native sensor. Native reserve sensor hourly statistics (id 5663, 4,390 hours since 2026-04-11) never show a minimum below 5.0. | `AUDIT_envoy_mqtt_trust_measurement.md` 3.8; statistics query this audit. |
| 2026-10-17 00:00-04:00 UTC | Low-SOC wobble: with SOC 4-9, commanded 10, cloud 10, the local sensor read 10/11/13/16/20/26 and flipped every 1-5 min. It behaves like an EFFECTIVE (ratcheted) floor, not an echo of the setting. Discharge was ~0 throughout so it cannot be adjudicated behaviourally. | recorder, section 3.3. Mechanism UNKNOWN. |
| 2026-10-17 18:01 | Non-landing write (commanded 10, both local and cloud stayed 9). Local was honest here; masked by the frozen Enpower number then. | recount audit 5.1. |
| (not the sensor) 2026-08-05 to 10-18 | FROZEN Enpower NUMBER read 10.0 / unavailable only; ~3 months of false pending_write_stuck / stand-downs (311 certain + 300 probable artifacts of 622). Fixed by v5.103.74 which moved the verifier's WITNESS to the sensor. | `AUDIT_ec_selfheal_resends_root_cause_2026_10_18.md`; recount audit. |

Prior incident where "accept local confirmation" was judged WRONG: EC-RESERVE-CLOUD-DIVERGENCE-1 (10-12/13). The refuted idea was accepting the Enpower NUMBER (read 10 while the battery obeyed 14). The local SENSOR read 14 in that episode and matched the cloud (card measured_2026_10_17_overnight (4); recount audit item 15 calls the card's "never accept local confirmation" lesson "overstated"). The kanban line still stands in EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 `INSTANCE_2026_10_14` and is the source of the operator's recollection; it is about the wrong entity.

### 2.3 envoy_status "stale"

`sensor.ura_energy_coordinator_envoy_status` is not a reserve oracle. It flips to "stale" when a cross-check anomaly is recorded within the last hour (`energy.py:998-1003`, `sensor.py:14597`) or when a per-source age threshold trips (net/battery power, solar, primary SOC; `sensor.py:14500-14525`). Live at 00:31 UTC: `stale_sources: []`, all source ages 22-54 s, `data_anomaly_at` 2026-10-23T19:00:03-05:00. Recorder 7-day state counts: stale 17,909, online 3,976, offline 240 (~81% stale by rows). A signal that is "stale" most of the time cannot discriminate and says nothing about reserve freshness. Not investigated further (why the cross-check keeps firing: UNKNOWN).

## 3. Measurement (HA recorder, read-only; 2026-10-16 10:52 to 10-24 00:32 UTC, 181.6 h)

Limit: the recorder only retains from 2026-10-16 09:12 UTC (`min(last_updated_ts)`), so this is 7.6 days. Earlier history is taken from prior audits and flagged as such. Scripts: scratchpad `m1.py` to `m8.py` (`/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/`).

### 3.1 How often and how long they disagreed

Definition: both numeric, |local - cloud| >= 2 (the same threshold as the `_reserve_action` deadband, `energy_battery.py:7058-7060`).

| Metric | Value |
|---|---|
| Both-numeric time | 604,049 s = 167.8 h |
| Disagreement time | 157,797 s = 2,630 min = 26.1% of both-numeric time |
| Episodes | 35 |
| Episodes >= 60 min | 6 raw (4 distinct stale-cloud events after merging two splits caused by a local `unavailable` blip) = 2,491 min = 94.7% of all disagreement minutes |
| Episodes < 20 min | 29, total ~139 min (apply lag, low-SOC wobble) |
| Local unavailable | 808 min = 7.4% of window, 11 episodes, max 461 min |
| Cloud unavailable | 22 min = 0.2%, 39 episodes, max 1 min |

The four distinct stale-cloud events (all on or after 10-19):

| # | Window (UTC) | Duration | Cloud | Gateway (local) | Trigger |
|---|---|---|---|---|---|
| A | 10-19 18:26 to 19:33 | 66 min | 9 | 79 then 98 | EVSE hold write 79 at 18:27:04 never reflected; cloud jumped to 98 at 19:32:58 |
| B | 10-19 21:37 to 10-20 06:07 | ~8.5 h | 98 | 10 | release write 10 at 21:37:11; local 10 in 2.6 s; cloud stayed 98; ~100 resends of 10 every 5 min |
| C | 10-22 06:05 to 10-23 10:00 | ~27.9 h | 10 | 15 then 13 | EVSE hold writes 15 (06:06) and 13 (08:06) never reflected; hold never released until 10-23 10:00 |
| D | 10-23 19:35 to 10-24 00:23 | 4.8 h | 10 | 98 | the alert under challenge; ended when the operator wrote 12 |

Cloud-stale wall-clock share: (66 + ~510 + ~1,670 + ~290) min = about 2,540 min = about 23% of the 181.6 h window.

### 3.2 Did writes land? (28 distinct value-change writes from `ura_activity_log action=reserve_write status=applied`, 10-16 15:00 onward)

For each first write of a new value, did the source reach |value| within 2 before the next different-value write or 1 h:

| Source | Reached |
|---|---|
| LOCAL sensor | 25 of 28 (2 of the 3 misses are timestamp artifacts where the sensor moved 20-40 s before the log row; 1 real miss, 10-17 02:57 at low SOC) |
| CLOUD number | 22 of 28. Misses: 10-19 18:27 (79), 10-19 21:37 (10), 10-22 06:06 (15), 10-22 08:06 (13), 10-23 19:35 (98), 10-24 00:30 (10, still within normal lag when measured) |

Before 10-19 the cloud followed every change in ~61 s (consistent with a 60 s poll); after 10-19 18:26 it missed 5 of 11. All three cloud-missed holds and one release are in the `evse_battery_hold` / `dp_transition` family, but 3 other hold writes (10-20 06:06 value 30, 07:11 value 19, 10-23 09:50 value 12) DID reflect, so the hold path is not the sole trigger. The cause is UNKNOWN. Local apply lag when the gateway is healthy and SOC is not near the floor: 2-31 s (median ~20 s), consistent with B0-D2 p50 41 s and p90 461 s (July).

### 3.3 Which source matched the battery's actual behaviour

Method: per minute, "decisive" = sources disagree by >= 2 and exactly one of them sits at or above SOC + 1 (would hold the battery) while the other sits at or below SOC - 3 (would allow discharge). Battery observed from `sensor.envoy_482543015950_current_battery_discharge` (+ = discharging): held if |kW| < 0.3, discharging if > 0.5 kW. 558 decisive minutes:

| Outcome | Minutes |
|---|---|
| Local sensor predicted the battery | 554 |
| Cloud number predicted the battery | 2 |
| Neither (idle band) | 2 |

Narrated examples: 10-19 22:00 to 10-20 06:07 UTC: cloud 98 / local 10, SOC 99 falling to 23 at 1.2-3.6 kW (battery followed local). 10-22 20:00 to 10-23 06:00 UTC: cloud 10 / local 13, SOC fell 100 to 13 at ~5 kW then held flat at 13 (-0.05 kW) for 2 h (battery honoured 13; with cloud 10 it would have continued to 10). Today: local 98, cloud 10, discharge -0.03 to -0.06 kW at SOC 98 (`AUDIT_envoy_reserve_98_alert_2026_10_23.md` Q2) versus 5-9 kW the previous night.
Cost of 10-22/23 hold: SOC pinned at 13 instead of 10 for a full overnight discharge plus the next morning, about 3 percentage points (~1.2 kWh of 40). Small, silent (no alert fired, because the cloud still read the desired 10).

Falsifier that could have shown otherwise and did not: any minute with cloud above SOC, local below SOC - 3, and battery idle (cloud right), or the reverse with the battery discharging. Found 2 cloud-correct minutes out of 558, both on episode edges (10-19 and 10-20), not sustained.

Caveat: this is 3 days of decisive data (10-19, 10-20, 10-22) from a single battery in a single house; the low-SOC regime (local wobble) is excluded by construction (SOC < 10).

## 4. Write-verification design and the other knobs

### 4.1 `energy_write_verify.py` - which oracle and why

- Primary oracle for "write applied / reverted" is the CLOUD entity (`_oracle_entity_for`, `energy_write_verify.py:337-370`; defaults `DEFAULT_CLOUD_RESERVE_ORACLE_ENTITY`). Reason in the build (`PLANNING_envoy_write_verification_and_redundancy.md` W-1..W-3): the tripwire was designed in July when local writes were suspected dead and the cloud was the system of record; "cloud propagation lag observed 5-10 min, default 15 for margin" (verify window 900 s).
- Secondary witness is LOCAL (`_local_entity_for`, `:372-420`). Since v5.103.74 the reserve branch prefers the local Envoy sensor found by registry lookup. Its docstring states the intended semantics: "when local and cloud disagree beyond the verify window, that's the 'gateway didn't hear it' signal - distinct from a cloud-side reversion".
- The 15/30/60 min retry ladder and 3 h stand-down (`CONF_PENDING_*`, `energy_const.py:505-526`) were sized by B0-D2 p90 = 461 s.
- The "Envoy write not applied" CRITICAL (`write_verification_failed`, `energy_write_verify.py:782`) still fires from the cloud oracle alone; a card exists to gate it: EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 `INSTANCE_2026_10_22_stale_cloud_false_critical` ("when the cloud number is older than the command but the Envoy witness already matches, treat the write as converged"), blocked by the reserve write governor and parked at `pre_planning` (Tier 3, two plan reviews, operator checkpoint).
- Release-deadband site: `_reserve_action` (`energy_battery.py:7015-7061`) reads `current_reserve` from the write-role entity (the cloud number) and emits only if `current_reserve is None or abs(current_reserve - target) >= 2`. This is the site the proposal targets. Not covered by v5.103.74.

### 4.2 `CONF_RESERVE_VERIFIABLE_MAX_AGE_S` (600 s)

Rung-1 backout knob from v5.28.0 (memory `reference_ec_reserve_verifiable_backout_knob.md`; EC manual 2.5a). It gates the blind-window EVSE guard's "verifiable" test (status OK AND `verified_at` fresher than 600 s AND oracle readable now). It does not touch the release deadband or the CRITICAL. It reads the cloud oracle for readability. Setting it to 0 is an emergency backout only and leaves partial outages exposed by design. Not relevant to today's fault, and the docs say never to tune it.

### 4.3 The write itself can be a no-op (new)

`/config/custom_components/enphase_ev/number.py:384-388` (`BatteryReserveNumber.async_set_native_value`): `reserve = int(value)`, `if self._coord.battery_selected_backup_percentage == reserve: return`, else `await self._coord.async_set_battery_reserve(reserve)`. `battery_selected_backup_percentage` is `coordinator.py:6714`. So when the cloud's selected value already equals the requested one, URA's `number.set_value` returns without contacting Enphase.

Consequence: today the cloud holds 10, desire is 10, the gateway holds 98. A local-trusting deadband would emit `set_value 10`, and the integration would drop it. The release landed this evening only because the operator wrote 12 (cloud selected 10 to 12), after which URA's write of 10 differed from 12 and went through (local 12 at 00:23:45, local 10 at 00:30:13, no lag). I verified the code; I did not verify the live behaviour of a same-value write (would require a service call).

### 4.4 Disagreeing detail worth knowing

After the integration reload at 00:22:01 UTC the cloud number came back at 10.0 (00:23:12), not 98. So the cloud settings payload itself said 10 while the gateway enforced 98: the stale value is not just a display cache that a reload refreshes. Mechanism UNKNOWN.

## 5. Strongest counter-evidence and risks of "trust local over cloud"

1. Local unavailability: 7.4% of this window, outages of 461, 586, 714 min recorded this month, and 17% of July outages >30 min. In those periods local gives no reading. A design that REQUIRES local blocks the release for hours; AND-gating both sources would stall releases for ~30% of the time (23% cloud-stale union 7% local-down, partly overlapping).
2. Local is not an echo of the setting at low SOC: the 10-17 00:00-04:00 UTC wobble (local 10-26 versus commanded 10, SOC 4-9, cloud steady) is ~100 min of >= 2 disagreements with the cloud being the one that equals the command. A deadband keyed on local would treat that as "needs a write" and re-send. Existing churn trip-wire: 12 writes/h (`DEFAULT_BATTERY_WRITE_CHURN_MAX_PER_H`, `energy_const.py` ~540). Unmeasured whether the wobble would breach it; the 10-17 strategy writes at 02:23-03:37 were 6, 8, 5, 8, 5, 7, 5 (7 changes in 75 min), which is already near that rate without the change.
3. Local cannot see an Enphase pending change (accepted by the cloud, not yet delivered) - `EC-RESERVE-CLOUD-DIVERGENCE-1` 10-12/13 and the 07-16 pending-stuck 67 min incident. In those cases local equals the old gateway state, same as today's logic would see; no new harm, but "local matches" does not prove the cloud has stopped being pending.
4. The write no-op (4.3): trusting local fixes the READ but not the SEND.
5. Sample size and retention: the behavioural scorecard is 3 days and one battery. Recorder starts 10-16. No instance of "cloud right, local wrong" was found in anything I could read, including July and earlier October; absence is bounded by what survived retention.
6. The firmware-side reason local WRITES are ignored is unverified; the proposal does not rely on local writes, so this does not hurt it, but nobody should read "local is honest" as "local is writable".

## 6. Verdict

SUPPORTED as a direction, with the following design instead of a plain swap (decision for the operator; nothing built):

1. Treat the gateway reading as primary for "what is enforced now" and the cloud number as a corroborator. Release deadband: if local is available, fresh and numeric, compute |local - desire|; if >= 2, SEND, regardless of the cloud value (and bypass the integration same-value early-return, section 4.3, e.g. send via a different value first or via a path the card must choose). If local is unavailable, fall back to today's cloud-based behaviour (do not stall).
2. Verifier: when local (healthy) equals the commanded value but the cloud oracle differs, do NOT page CRITICAL "not applied". Classify it as "cloud oracle stale" (INFO or HIGH once per episode with the age of the cloud value). Keep CRITICAL for: local (healthy) differs from commanded beyond the ladder, or both unavailable.
3. Make the disagreement itself an observable: a dwell-gated `reserve_source_divergence` (local vs cloud >= 2 for > N min with local available) is already the pattern the cloud-reliance plan proposes for SOC (`PLANNING_enphase_cloud_reliance.md` D2). Four events in 5 days make it an expected, not exceptional, signal.
4. Guard the low-SOC regime (SOC <= reserve + small margin): do not trust the sensor's ratcheted values for the deadband there; keep the existing cloud/desire comparison.
5. Do NOT require both. Do NOT use `envoy_status` as a gate (stale ~81% of rows).

Tier: touches the reserve emission site and the write-verify primitive; per CLAUDE.md that is Tier 3, which matches the existing card's note. The immediate unstick (operator writes a value >= 2 away, then URA releases) is a Config-First action, not code, and is already in the 98-alert audit.

## 7. Limits and unknowns

- Why the cloud number goes stale (and why a reload returns it to the stale value): UNKNOWN. No enphase_ev log retained (journald not readable via SSH add-on, previously noted).
- Behavioural scorecard excludes SOC < 10 and is 3 days; the low-SOC semantics of the sensor are unexplained.
- Firmware version/date of the "local writes ignored" finding is inconsistent across docs; not verified.
- Whether the same-value `set_value` is really dropped live (4.3) is from code only.
- Pre-10-16 numbers come from prior audits, not re-derived. 300 of the 622 `pending_write_stuck` rows are "MIXED" (bound only).
- The cause of `envoy_status` staying "stale" (cross-check anomaly every hour?) is not investigated.
- Final cloud read at 00:32:53 UTC: 12.0 (local 10 since 00:30:13) - cloud lag 2m40s and counting when I stopped.

## 8. Sources

Memory: `reference_ec_reserve_verifiable_backout_knob.md`, `project_envoy_boot_incident_2026_06_12.md`, `project_session_pickup_2026_09_23.md` (grep), `project_enphase_coupling_tier.md`, `project_battery_soc_envoy_not_span.md`.
Docs: `AUDIT_envoy_reserve_98_alert_2026_10_23.md`, `AUDIT_envoy_reliability_recount_and_witness_reconcile.md`, `AUDIT_ec_selfheal_resends_root_cause_2026_10_18.md`, `PLANNING_ec_reserve_witness_fix.md`, `AUDIT_envoy_mqtt_trust_measurement.md`, `PLANNING_envoy_local_witness_and_solar_follow.md`, `PLANNING_envoy_write_verification_and_redundancy.md`, `PLANNING_behavioral_write_verify.md` (B0 reports), `PLANNING_enphase_cloud_reliance.md`, `PROBE_envoy_outage_frequency.md`, `docs/reviews/code-review/audit_reserve_surface_ground_truth.md`, EC manual 2.5a/2.6/2.6a, `docs/readmes/README_v5.16.0.md`.
Kanban: EC-RESERVE-CLOUD-DIVERGENCE-1 (`kanban.data.yaml:32647`), EC-SELFHEAL-UNEXPLAINED-RESENDS-1 (:894), EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 (:971).
Git: `114043a89` (H1), `git log -S` on `energy_const.py` / `energy_write_verify.py`.
Live: HA recorder `/config/home-assistant_v2.db` (metadata 18390, 19446, 941, 18389, 18388; statistics 5663), URA DB `ura_activity_log`, `/config/custom_components/enphase_ev/number.py`, `control_updates.py`.
