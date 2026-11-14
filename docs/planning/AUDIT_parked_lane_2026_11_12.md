# Parked lane audit, 2026-11-12

Read-only audit of the 118 `status: parked` cards in `docs/planning/kanban.data.yaml` (read at 2026-11-12 20:57 CST). Nothing edited. Verdicts are from the card text plus a few code/yaml greps noted inline; where a trigger was not checked against live data it says UNKNOWN or "not queried".

Why-parked codes: OD operator decision, EVT waiting on evidence trigger, LOW low value, PHYS blocked on physical work, BLK blocked on another card, SUP superseded/done, UNK no stated reason.

## Counts

- KEEP PARKED: 80
- TRIGGER FIRED: 8
- CLOSE: 10
- NEEDS OPERATOR: 20

## Adjacencies to today's work (FACE-ARRIVAL-REBUILD-1, HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1, LOCK-RELEASE-ON-ARRIVING-BODY-EVIDENCE-1)

Context read from the live cards: FACE-ARRIVAL-REBUILD-1 (pre_planning, 11-12 18:30) and FRIGATE-DOOR-FACE-TUNING-1 (investigating) cite 85% of named faces interior, doors weak, egress attach ~40%; LOCK-RELEASE-ON-ARRIVING-BODY-EVIDENCE-1 (investigating, 19:10) says a body alone moves away to ARRIVING and releases the garage lockout and disarms security; HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1 is in_progress.

**Face arrival / person sightings / vision census**
- GUEST-GATE-DOOR-IDENTITY-1: its revival is egress attach >=50% sustained 14 d; today ~44%, so face-rebuild output is exactly what would fire it.
- KP-ANNOTATION-1: parked on producer coverage (0.0% identity at t=0 in the D0 probe). FRIGATE-DOOR-FACE-TUNING-1 changes that probe input; re-run D0 after tuning.
- SECURITY-ENTRY-VERDICT-NAME-1, LAST-RESIDENT-EGRESS-ARM-1, EXTERIOR-GUEST-EGRESS-1, EGRESS-EXIT-JOINT-DEPART-ONE-ROW-1, EXTERIOR-DWELL-LOITER-1, SECURITY-CENSUS-UNKNOWN-WIRE-1: all identity consumers gated on face/egress yield.
- GUEST-IDENTITY-PHONE-LEFT-BEHIND-1: BLE-only exclusion; door identity would close it.
- IDENTITY-FLAPPING-FACE-VETO-1: becomes live if the rebuild routes face names into more consumers.
- INTEGRATION-CAMERA-DISCOVER-STALE-1: the same camera->area map (`_cameras_by_area`) as the zone-camera device-area discovery bug behind FACE-ARRIVAL-REBUILD-1; fix together or sequence.
- D1-PROTECT-FACE-BRIDGE-ADDON-1 (recommend CLOSE), CAMERA-STUCK-MASTER-HALLWAY-1, CHATTER-CAMERA-CONFIDENCE-FLAP-1, DISABLE-CAMERA-PRESENCE-SCOPE-GAP-1: camera-presence neighbours.

**Pre-cool / pre-heat / pre-arrival**
- PREARRIVAL-NEAR-HOME-ZONE-1: earlier arrival signal for pre-cool; its blocker PERSON-OJI-HOME-FLAP-1 is now done, only the "operator home after 11-16" gate remains.
- HVAC-PRECOOL-WINDOW-TOU-DERIVED-1 and EC-GRID-ANTICIPATORY-PRECOOL-GAP-1: pre-cool window/anticipation (Path A, energy-driven), a different trigger path than pre-arrival but the same `hvac_predict.py` file; check before editing.
- HVAC-FAST-PATH-FAN-WARM-EDGES-1: fan latency on occupancy edges, same pre-arrival fan surface.
- HVAC-S10-NOTIFY-UNDELIVERED-1: a stand-down that skips a preset write interacts with S10 range latch notifications.

**Lock release on arriving body evidence**
- LOCK-REGIME-BOOT-REALLY-AWAY-1: same release path, restart hole; revival is lockout switch ON. Do this plan with LOCK-RELEASE-ON-ARRIVING-BODY-EVIDENCE-1.
- SC-SWEEP-CLOSES-OPEN-GARAGE-1 and SC-ARMING-ALARM-ONLY-1: lockout Phase 2 / arming prerequisites; parent GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 is shipped_organic.
- LAST-RESIDENT-EGRESS-ARM-1: identity-accelerated arm, same "access actions need identity plus independent signal" principle.

## Hygiene findings

- No stated reason or workable trigger: CAMERA-STUCK-MASTER-HALLWAY-1, GUEST-IDENTITY-PHONE-LEFT-BEHIND-1, WATERLEAK-TRIO-UNKNOWN-1 (safety input, last verified still unknown 09-12), HVAC-WRITE-CONFIRMATION-ORACLE-1, ENPHASE-REALTIME-TRIAL-1, EC-ATTAIN-HOLD-WHEN-ENVOY-BLIND-1, KITCHEN-OVERHEAD-EXTERNAL-TURNOFF-1, NIGHT-LIGHTS-HOUSE-SLEEP-ALL-ROOMS-1 (says "see revival trigger", none stated), CHATTER-CAMERA-CONFIDENCE-FLAP-1, SENSOR-MULTISTATE-FAULT-1, HVAC-ZONE3-NIGHT-SAWTOOTH-1 (vague), APPLIANCE-CENSUS-MULTI-ROOM-POWER-SENSOR-1 (soft).
- Parked cards that already carry a `shipped_version` (lane mismatch): ARREST-SUNSET-1, DRAIN-TARGET-DAY-STALENESS-1, EGRESS-IDENTITY-CONTROL-OBS-1, MENU-CONSISTENCY-1, XCORR-1, PATH-ALPHA-DENOM-1, STUCK-SENSOR-1, FAN-LAYER-2, FAN-RECHECK-D2-DEADLOCK-1.
- Overdue date triggers: COVERAGE-EVENING-ATTRIBUTION-DRIFT-1 (10-25), ENPHASE-REALTIME-TRIAL-1 (10-13), HVAC-BASELINE-MAXSAMPLES-1 (heating season now). Two-restart-check cards (FAN-ORACLE-BOOT-FALLBACK-NOISE-1, LOOP-STALL-WATCHDOG-STOP-UNSUB-ERROR-1) have been waiting since early October with five logged "log-read gaps"; a boot-log trip-wire or one-shot journald read would dispose both.
- Operator "do not raise again" items (JAYA-WINDOW-CONTACT-UNAVAILABLE-1, WIGTON-URA-REENABLE-1) are correctly parked; do not list them in status.
- Card-internal contradictions: KHOST-2 (parked "not shipped" but shipped_note says live 08-11), ZONE-ROOM-NAME-DRIFT-1 (operator approved Tier-3, parked only to keep lane clear).

## Table by thread

### analytics

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| REGIME-BASELINE-ROOM-RENAME-CONTAMINATION-1 | Room renames fake routine drift | OD 09-26 option B | Next room rename | KEEP PARKED |  |

### architecture

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| URA-CENTRAL-TICK-WHEEL-1 | One URA clock with divisors | OD/LOW marginal benefit | 3rd/4th fast sub-loop need, or timing re-architecture pass | KEEP PARKED |  |

### census

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| TRANSIT-PERSON-CHECKPOINT-1 | Key TRANSIT checkpoints to person_id | OD speculative | Agentic room-to-room layer scoped | KEEP PARKED |  |

### config-flow

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| CONFIG-FLOW-SLOW-ONBOARDING-1 | Add Entry slow (traced to device outage) | EVT (instrumented v5.103.105) | Next slow setup: read CFLOW-TIMING SLOW lines | KEEP PARKED |  |
| ONBOARDING-SIMPLIFY-1 | Simplify first-run onboarding | PHYS (needs second-home first run; Wigton off) | Wigton runbook Stage 1 | KEEP PARKED | Operator said not to start Wigton stage 1 |

### dashboarding

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| IOS-APP-PLAN-CARD-1 | iOS app blueprint | Gated on PWA M2 + >=100 installs | PWA M2 lands + install gate | KEEP PARKED |  |
| LOVELACE-DECLUTTER-MIGRATION-1 | Decluttering-card template for room cards | Gated on LOVELACE-AUTO-ROOM patch + archetype design | Those land | NEEDS OPERATOR | v6/v8 dashboards moved on; confirm still wanted |
| URA-ENTITY-COUNT-REDUCTION-1 | Cut URA enabled entity count | LOW (max 4.4% gain) | Panel test shows entity count drives CPU | KEEP PARKED |  |

### dashboards

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| URAV8-ZONE-AC-FORECAST-1 | Per-zone AC forecast on v8 | EVT (needs ~30 d forecast log) | ~30 d from 11-02 hvac_zone arm beats v1 on MAE | KEEP PARKED | Earliest date ~12-02 |

### devices

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| QREVO-OFFLINE-1 | Qrevo has no area; empty duplicate device | OD ("Drop 5. Not needed" 10-21) | Operator raises Qrevo again | CLOSE | Operator dropped it; premise partly wrong (robot not offline) |

### diagnostics

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| CHATTER-CAMERA-CONFIDENCE-FLAP-1 | Camera confidence-flap detector | Sibling of STEP primitive | After STEP D1/D2 ship (not dated) | NEEDS OPERATOR | Hygiene: STEP status not stated; camera/face adjacent |
| SENSOR-MULTISTATE-FAULT-1 | Bed/multi-state sensor fault detector | LOW (few sensors) | After STEP primitive ships (not dated) | KEEP PARKED | Hygiene: soft trigger |
| KITCHEN-OVERHEAD-EXTERNAL-TURNOFF-1 | Kitchen overhead turns itself off | OD ("Leave it alone") then reopened 09-27 with two callers found | None stated post-reopen | NEEDS OPERATOR | Hygiene: reopened with findings but still parked |

### energy

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| COVERAGE-EVENING-ATTRIBUTION-DRIFT-1 | Room energy totals overshoot whole-house meter each evening | EVT (fix shipped v5.103.86; ec_total live since 10-24) | 10-25 evening query; reopen if whole_house walks negative | TRIGGER FIRED | Query date passed 17 days ago; one-shot dispose due |
| DRAIN-TARGET-DAY-STALENESS-1 | Off-peak drain target reads calendar-tomorrow after midnight | EVT organic cross-midnight night | Next class-disagreement night w/ arbitrage wait | CLOSE | Shipped v5.91.1, live-validated 2026-08-26 (card VALIDATED_2026_08_26); only a confirmatory observation left; lane-hygiene |
| ARBITRAGE-DRAIN-TODAY-UNKNOWN-DEGENERATE-PAIR-1 | Today-Solcast unknown at rollover makes broadening leg pair tomorrow with tomorrow | LOW value (1 tick/11d, boot only) | target_day_source==tomorrow_solcast_fallback on a command tick, or >3/wk | KEEP PARKED |  |
| BREAKER-GRIDCAP-STALE-TELEMETRY-1 | Breaker guard/grid cap behaviour under stale (not unavailable) Envoy data | LOW value vs HIGH risk; operator accepted | Real blind-telemetry breaker trip, or guard enabled | KEEP PARKED |  |
| EC-ATTAIN-HOLD-WHEN-ENVOY-BLIND-1 | Attain charges nothing when Envoy unavailable though cloud SOC fresh | Hold under EC-DEGRADED-DATA-POLICY-1 (operator 10-03) | None stated beyond that policy card (phase 1 shipped v5.103.39) | NEEDS OPERATOR | Hygiene: blocker shipped, no trigger; may be superseded by EC arc (v5.103.9x/v5.106.2) |
| EC-BLIND-DEESCALATE-TOP-RATE-1 | Envoy-blind de-escalation keys on literal "peak" not top rate | EVT rare-fire (shipped v5.106.2) | First Envoy-blind day at top-rate window start with charge_from_grid on | KEEP PARKED |  |
| EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 | Enphase cloud-only writes / yearly token / rate limits resilience | EVT (soak exit; shipped v5.103.95) | Any "Envoy write reverted/not applied" CRITICAL after 11-02 06:56 | KEEP PARKED | Card logs false CRITICALs 10-30,10-31 (pre-trigger). Post-11-02 count UNKNOWN (not queried) |
| EC-FORECAST-TRUTH-GAPS-1 | energy_daily missing days; forecasts cannot be scored | OD default-taken 10-26 | Forecast-scoring work needing rows before 10-22, or operator approves backfill | KEEP PARKED |  |
| EC-GRID-ANTICIPATORY-PRECOOL-GAP-1 | Path A pre-cools only on live PV surplus; low-SOC hot day gets none | LOW (design axis, measure first) | Summer billing / measured hot-low-SOC day | KEEP PARKED | ADJACENT to pre-cool work (see top) |
| EC-INCLEMENT-HARDENING-1 | Storm hold gaps (blind gate, wind advisory, onset) | EVT (shipped v5.103.69; rare event) | First hold-class NWS alert after v5.103.70 | KEEP PARKED |  |
| EC-SOC-LADDER-FULL-WIRING-1 | 3 SOC-ladder invariants unwired across ~25 sites | EVT (partly shipped v5.103.35) | threshold_ladder_violation row in anomaly_log | KEEP PARKED | Check anomaly_log at groom |
| EC-STORM-FULLHOLD-DEGRADED-ENVOY-AVAILABLE-1 | Storm full-hold degraded tick resets Envoy outage counter | EVT rare-fire (shipped v5.106.2) | Envoy-blind tick during inclement full hold | KEEP PARKED |  |
| EC-TOU-CFG-BEFORE-EV-PAUSE-MANAGER-PATH-1 | Grid charge may switch on up to 5 min before EV pause | LOW (operator call + measurement) | Site load >30 kW in EV+grid-charge overlap, trip sensor on, bigger EVSE | KEEP PARKED |  |
| ENERGY-CONSUMPTION-FORECAST-POISONED-1 | Consumption forecast poisoned by lifetime-counter days | EVT (default A taken 10-29) | energy_daily NULL / solar 0 sunny / consumption >240 | KEEP PARKED | Trigger checked NOT fired 11-01; call (1) done 10-26 |
| ENERGY-TODAY-STATS-STEPPED-RESET-1 | Staggered midnight resets overcount rooms-total LTS | LOW (consumerless) | Rooms total added to Energy dashboard/statistics card | KEEP PARKED |  |
| ENPHASE-REALTIME-TRIAL-1 | Trial ha-enphase-realtime as second Envoy witness | UNK (stale since 10-09) | "After 2026-10-13" compare; no live trigger | NEEDS OPERATOR | Hygiene: next-step date long passed; operator 10-09 narrowed to second-witness |
| ENVOY-DRAIN-ARM-STALE-CT-1 | Drain-pause does not arm under stale battery CT | LOW; operator accepted gap | Real blind-CT drain event or operator wants protection | KEEP PARKED |  |
| EVSE-SOLAR-STOP-CONDITIONS-1 | Solar session cannot tell car done from sun out | OD pending (waiting operator since 08-26) | Operator picks NARROW parked-reservation fix vs Tier-3 | NEEDS OPERATOR | Hygiene: 2.5 months with an open operator question |
| APPLIANCE-CENSUS-MULTI-ROOM-POWER-SENSOR-1 | Shared power sensor attributed to first-scanned room | BLK on v1b flow | Fold into appliance v1b | KEEP PARKED | Weak trigger |

### fans

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| FAN-LAYER-2 | FanPolicyOracle completion: RoomFanState delegation, wrap remainder | BLK on FAN-LAYER-1 | FAN-LAYER-1 ships+validates | TRIGGER FIRED | FAN-LAYER-1 shipped (card shipped_version v5.73.2); Tier 2-DB refactor, benefit unmeasured, so operator call on priority |

### hvac

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| ARREST-SUNSET-1 | Temp Arrester override does not sunset on away/vacation | Deferred build folded into SECC-1 (closed) | TAO on during away >30 min | CLOSE | Fixed in code: hvac_override.py:1041,1671 use house_state_invalidates_arrester_hold; shipped v5.61.0 |
| ARRESTER-GATE4-LOW-STAGE-THRESHOLD-1 | 0.5 kW running check misreads low-stage ODUs | EVT measured by W3 M0 | Wrong nudge on zone 2/3 due to misread, or Var% signal | KEEP PARKED |  |
| GUEST-ROOM-FAN-HOLD-1 | Guest bedroom fan turns off after 5 min empty at night | EVT | Observed guest night, or operator asks | KEEP PARKED |  |
| HVAC-BASELINE-MAXSAMPLES-1 | HVAC anomaly baselines never forget season | EVT (b) first heating-season week | Operator pick on HVAC-ANOMALY-BLIND-1, OR first heating week | TRIGGER FIRED | (b) is now: mid-Nov. Card premise partly wrong (MetricStats already has max_samples; HVAC metrics do not set it; grep hvac.py max_samples = 0 hits). Tier 2-DB |
| HVAC-EQUIPMENT-HEALTH-OBSERVABILITY-1 | Use Bryant ODU/IDU telemetry for health + tuning | EVT (telemetry cadence gate failed) | Static-pressure p95 gap <30 min, or >=10 hard resets | KEEP PARKED |  |
| HVAC-FAST-PATH-FAN-WARM-EDGES-1 | Fans wait for 5-min tick on warm-zone edge | LOW (not worse than today) | Complaint/measure of late fan | KEEP PARKED |  |
| HVAC-OPTIMIZER-CLIMATE-FUNNEL-ROUTING-1 | Optimizer climate.* actions bypass W1-A funnels | BLK external gate (optimizer L1 shadow) | Any proposal to promote OC to L2+ | KEEP PARKED |  |
| HVAC-PRECOOL-WINDOW-TOU-DERIVED-1 | Pre-cool window summer-hardcoded [10,14) | EVT (measured: summer right by coincidence) | Tariff change, shoulder grid share >0.5, or Q3 value >=$25/yr | KEEP PARKED | ADJACENT to today pre-cool work |
| HVAC-ROLLOVER-DURABLE-DATE-ORDERING-1 | Short-cycle sample durable but date stamp not (double-count window) | LOW | short_cycle_rate sample_count +>1/zone/day, or snapshot refactor | KEEP PARKED |  |
| HVAC-S10-NOTIFY-UNDELIVERED-1 | S10 latch NMs sent at LOW/MED reach nobody | EVT (shipped v5.103.69, event-gated) | First CPR give-up; check HIGH delivered=1 | KEEP PARKED |  |
| HVAC-SHUTDOWN-SAVE-RACE-STATE-STORE-1 | Shutdown save can overwrite latch/holds with [] | LOW (ms window) | Observed lost hold/TAO/latch after restart | KEEP PARKED |  |
| HVAC-W1C-GENERIC-THERMOSTAT-1 | Non-Carrier thermostat support | PHYS (Wigton HVAC not enabled; no 2nd brand) | Second brand available, or Wigton persons enrolled | KEEP PARKED | Operator 10-20: do not start Wigton stage 1 |
| HVAC-WRITE-CONFIRMATION-ORACLE-1 | Which Carrier feed confirms a URA write took? | UNK (needs operator controlled test, stale 10-14) | Per-class >=3 cloud-sourced episodes over >=2 zones | NEEDS OPERATOR | Hygiene: measurement-only, no owner/date; 9/28 evidence says loop not recurring |
| HVAC-ZONE3-NIGHT-SAWTOOTH-1 | Zone 3 flips sleep<->away all night (robot vacuum) | OD (operator: leave vacuum alone) | Operator revives or measurable comfort/energy cost | KEEP PARKED | Vague trigger |
| PREARRIVAL-NEAR-HOME-ZONE-1 | Optional near-home zone as earlier pre-cool signal | EVT/PHYS (operator abroad; drive test) | Operator home after 11-16 AND PERSON-OJI-HOME-FLAP-1 verified | KEEP PARKED | FLAP card is now done (11-12 13:20); only the date gate remains. ADJACENT |

### hygiene

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| FAN-ORACLE-BOOT-FALLBACK-NOISE-1 | 86 boot WARNINGs from fan oracle fallback | EVT next restart (fix a841fbc8c v5.103.37) | Read first 10 min boot log for fallback WARN | TRIGGER FIRED | Log-read gap 5x; any restart since is evaluable; close if absent |
| LOOP-STALL-WATCHDOG-STOP-UNSUB-ERROR-1 | Watchdog logs ERROR at every shutdown | EVT next restart (fix v5.103.39) | Shutdown-window log: absence of unknown job listener ERROR | TRIGGER FIRED | Restarts since 10-06 make this one-shot checkable; close if absent |

### identity

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| D1-PROTECT-FACE-BRIDGE-ADDON-1 | Add-on to bridge Protect face names to HA | OD marginal-benefit park 08-29; BLK operator credentials | None (Frigate covers all residents) | CLOSE | Superseded by Frigate face path (FRIGATE-SUBLABEL-FACE-BRIDGE-1 done, per CLAUDE.md). Adjacent to face work, but 85% of names are interior Frigate |
| EGRESS-EXIT-JOINT-DEPART-ONE-ROW-1 | Joint departure names whoever edge arrives first | LOW (~1.5 rows) | A consumer acts on exit person_id, or wrong-name ground-truth | KEEP PARKED | ADJACENT (identity actuation) |
| IDENTITY-FLAPPING-FACE-VETO-1 | Flapping-frozen face sensor evades staleness gate | OD ("do not solve phantom problems") | Observed flapping-frozen misattribution | KEEP PARKED |  |

### lighting

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| LIGHT-FADE-OVER-5S-MANUAL-MISREAD-1 | Fade >5 s misread as manual | LOW (defaults 1s/3s) | Any room fade >5 s | KEEP PARKED |  |
| NIGHT-LIGHTS-HOUSE-SLEEP-ALL-ROOMS-1 | House-sleep motion should use night lights only without per-room protection | OD (plan review FIX-PLAN-FIRST; config workarounds applied) | "see revival trigger" but none found in the card | NEEDS OPERATOR | Hygiene: references a trigger that is not stated; operator said "I like the fix. Do it" |
| NIGHTLIGHT-RED-RECONCILE-PARITY-1 | Reconnecting night light returns warm white not red | EVT not evaluable (shipped v5.103.52) | Colour night light seen warm white after reconnect in Sleep | KEEP PARKED |  |

### maintenance

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| DELETE-REACT-DASHBOARDS-CODE-2 | Delete dead React dashboard code | EVT phase-1 unregister lived | Phase-1 unregister shipped (v5.100.5) and lived | TRIGGER FIRED | Parent DELETE-REACT-DASHBOARDS-1 is done (09-12); dashboard/, dashboard-v3/ still present; deploy.sh:246 still ships frontend/ |

### memory

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| MEMORY-ZONE-PHANTOM-WRITER-1 | Zone-phantom memory writer | LOW marginal | F2 zone-occupied-while-away divergence recurs | KEEP PARKED |  |

### notifications

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| NM-TTS-ENGINE-TARGET-1 | tts.speak names no engine | LOW latent (TTS off) | Operator enables spoken alerts | KEEP PARKED |  |
| OPTIMIZER-RUN-NOW-BUTTON-READY-1 | Run-now button may stay unavailable | LOW measured never fired | Button unavailable >180 s after a boot | KEEP PARKED |  |

### ops

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| SWEEP | Morning sweep placeholder | SUP process placeholder (no work) | None | CLOSE | Not a work card; lane-hygiene |

### perimeter

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| CAMERA-SEAM-CLOSE-PAIR-SEMANTICS-1 | [C] camera pairs count as one for circling? | OD merged into PERIMETER-TOLERANCE replay | Gate not cheaply met | KEEP PARKED |  |
| KP-ANNOTATION-1 | Known-person annotation on exterior alerts | Evidence: D0 PARK v1 (0.0% identity at t=0) | Producer fixes: Frigate-2 face on 6 dead cams, enrol, re-run probe | NEEDS OPERATOR | ADJACENT: FRIGATE-DOOR-FACE-TUNING-1 changes the probe input; operator decides re-run now or later |
| PERIMETER-TOLERANCE-AND-SECTIONS-1 | Measure link tolerance; priority perimeter sections | BLK CAMERA-SEAM-VALIDATION-1 | Seam accuracy landing | KEEP PARKED |  |
| XCORR-1 | Burst-demotion for single-camera night alerts | Deferred build; revival CONSOL-1 or burst | CONSOL-1 or a burst | NEEDS OPERATOR | Hygiene: shipped_version v5.64.0 but parked; reconcile whether burst-demotion shipped |

### planning

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| ROADMAP-STALE-AGENTIC-LAYER-1 | Agentic layer unplanned (roadmap half done v12) | OD 11-03 park until OC loop proven | OC live eval passes + first production slice | KEEP PARKED |  |

### platform

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| CM-SHUTDOWN-JOB-SETUP-FAIL-LEAK-1 | CM setup failure leaves shutdown job | LOW pre-existing | CM setup failure log, or two stop-save jobs | KEEP PARKED |  |
| CONFIG-SUBENTRIES-MIGRATION-1 | Flat 34 entries to subentries | LOW/MED value, high risk | Per-item reload wanted, or HA deprecates flat | KEEP PARKED |  |
| DB-SIZE-GROWTH-1 | DB grew 52% (retention shipped v5.103.76) | EVT dated | On/after 2026-11-21: oldest rows >= 2025-11-20 + row delta | KEEP PARKED | Due in 9 days; not yet |
| DEVICE-INFO-HELPER-CONSOLIDATION-1 | ~100 inline DeviceInfo literals | LOW opportunistic | Next cycle touching those files | KEEP PARKED | Read DEVICE_TREE.md first |
| ENTITYDESC-RUNTIMEDATA-HYGIENE-1 | EntityDescription/runtime_data hygiene | LOW opportunistic | Next coordinator touch | KEEP PARKED |  |
| MENU-CONSISTENCY-1 | Flow menus inconsistent | SUP/done (reorg shipped v5.94.0) | Reorg shipping | CLOSE | shipped_version v5.94.0; zone-picker split to MENU-ZONE-PICKER-1 |
| INTEGRATION-CAMERA-DISCOVER-STALE-1 | Camera->area map stale after suppressed reload | OD 09-26 option B workaround: restart HA | Interior camera added/removed, or subentries land | KEEP PARKED | ADJACENT: same camera->area map as ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1 behind FACE-ARRIVAL-REBUILD-1 |

### presence

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| BLE-BLEED-EXTEND-SLEEP-1 | Master Bath held occupied all night by BLE bleed | OD ("PArk"); cap shipped v5.93.0 | Room BLE-held occupied run >= cap in sleep hours | KEEP PARKED |  |
| CAMERA-STUCK-MASTER-HALLWAY-1 | master_hallway camera sticks person_count=1 | UNK (cleared after reboot 09-12) | None | NEEDS OPERATOR | Hygiene: no trigger since 09-12; close or add a trigger. Adjacent to camera/face work (stuck camera occupancy) |
| CENSUS-G6-RAW-PERSISTENCE | Guest persistence gate on raw unidentified | EVT (G1+G4 shipped) | Phantom/transient still sustains guest mode | KEEP PARKED |  |
| CHATTER-RATE-VS-BURST-GAP-1 | Chatter detector cannot see sustained-rate chatter | LOW (harm unmeasured, 10-06 PARK) | Measured false occupancy from sustained-rate sensor, or rate view needed | KEEP PARKED |  |
| D2-PIR-STAMP-FOLLOWS-FAN-IMMUNE-WITNESS-1 | PIR stamp refreshed by radar motion bit | EVT not evaluable (v5.103.54) | GB1/GB2/Media fan >=30 min while radar-only occupied | KEEP PARKED | Fan-season dependent |
| DISABLE-CAMERA-PRESENCE-SCOPE-GAP-1 | disable_camera_presence mutes only fan-veto | LOW (no observed harm) | Operator sets flag and sees camera occupancy anyway | NEEDS OPERATOR | Card says "REVIEW (operator): gate-vs-document". ADJACENT to camera presence |
| EGRESS-IDENTITY-CONTROL-OBS-1 | Egress identity enable switch + observability | Folded into D1 (SUP) | Verify at egress-identity-arc close | CLOSE | Shipped v5.81.0 (card l1_validated); lane-hygiene |
| EXTERIOR-GUEST-EGRESS-1 | Exterior->interior guest admission via egress identity | OD parked, deferred | Identity-at-egress shipped and shown to miss real guests | KEEP PARKED | Adjacent to identity; egress attach ~44% (CLAUDE.md) |
| FAN-RECHECK-D2-DEADLOCK-1 | Fan-recheck never arms (D2 starves it) | EVT organic fan-ghost (shipped v5.84.0) | Fan-ghost episode shows O1/O3/O4 | TRIGGER FIRED | Sibling cards cite memory_episodes fan_recheck_outcome rows 10-12..10-20 (Living Room 56, Study A 58); O1 evidently met. Dispose via that query |
| FAN-RECHECK-SLEEP-VETO-SCOPE-1 | Scope fan-recheck sleep veto to bedrooms | BLK on FAN-RECHECK-OBSERVABILITY-1 | That card shipping | NEEDS OPERATOR | Hygiene: blocker card status not checked; may be stale (recheck ran 56+ times) |
| FAN-TRANSITION-GATE-FOLLOWS-CAPABILITY-1 | Dormant fan-transition gate keys on presence list | LOW (dormant, window 0.0) | Un-retire FAN_TRANSITION_SUSPECT_WINDOW_S | KEEP PARKED |  |
| GUEST-FP-RESIDUALS-1 | Path-alpha diag classifier + camera-census outdoor filter | LOW (A1 shipped v5.78.0; B1 latent) | Camera person entity attached to an outdoor-zone room | KEEP PARKED |  |
| GUEST-GATE-DOOR-IDENTITY-1 | Guest gate should consume door identity | BLK on producer yield | Egress attach >=50% sustained 14 d AND a non-resident named | KEEP PARKED | CLAUDE.md: attach 90/203=44% over 14 d to 11-08; not yet. ADJACENT (face/egress) |
| GUEST-IDENTITY-PHONE-LEFT-BEHIND-1 | Guest-room exclusion BLE-only | UNK (measure-first, no trigger) | None stated | NEEDS OPERATOR | Hygiene: parked since 09-11 with no trigger. ADJACENT (door identity would close it) |
| GUEST-SELF-AUTHENTICATION-1 | Guests opt in to self-identify | OD ("not now") | Operator asks | KEEP PARKED |  |
| HOUSE-STATE-UTILIZATION-EPIC | Give meaning to under-used house states | OD roadmap marker | Operator picks a rung | KEEP PARKED |  |
| JAYA-FAN-STILL-PHANTOM-1 | Jaya fan induces false still target | EVT not evaluable (v5.103.73) | Upstairs zone held by Jaya fan-on radar-only with no recheck row | KEEP PARKED |  |
| JAYA-WINDOW-CONTACT-UNAVAILABLE-1 | Jaya window contact unavailable | PHYS (battery/re-pair); operator knows | Contact reports again | KEEP PARKED | Operator: do not raise again |
| KITCHEN-NIGHTLIGHT-RANGE-MISCONFIG-1 | Kitchen night light is range-hood switch | OD ("Leave alone" 09-13) | None | KEEP PARKED | Operator-owned config; no trigger (hygiene minor) |
| OCCUPANCY-SOURCE-FOLLOWS-CAPABILITY-1 | Fan-noise rejection for combined radar sensors | EVT not evaluable (v5.103.53) | GB1/GB2/Media fan >=30 min radar-only hold | KEEP PARKED |  |
| PATH-ALPHA-DENOM-1 | Path-alpha dead when all trackers LOST | BLK ZONE-TIER-DIVERGE-1 trace | That trace completing | NEEDS OPERATOR | Hygiene: card says shipped v5.78.0 yet parked; blocker status unchecked. Needs reconcile |
| PREDICT-PATTERN-DETECTED-ORPHANS-1 | ~25 orphan occupancy_pattern_detected entities | OD (operator: not a reason to delete) | Real pattern-detection sensor built | KEEP PARKED |  |
| STUCK-SENSOR-1 | Flapping mmWave evades stuck exclusion | BLK SENSOR-CAPABILITY-1 | That card | NEEDS OPERATOR | Hygiene: shipped v5.75.0 and fleet classes now SETTLED; blocker likely done; reconcile |
| STUDY-A-CSI-SENSOR-1 | Study A Wi-Fi CSI is motion-class | EVT (firmware) | Firmware with stillness detection | KEEP PARKED |  |
| STUDYA-ZK-EMPTY-HOLD-1 | Study A radar holds room occupied when empty | OD default (stays out of Away veto) | Second sensor back online or ZK retuned | KEEP PARKED | Athom deleted 10-18 |
| SUBSTRATE-PER-ROOM-REFRESH-1 | Per-room substrate refresh scope | LOW (perf) | Residual house-wide substrate work after D1 | KEEP PARKED |  |
| URA-SENSOR-TUNING-PHASE-B-1 | Turn radar down while fan runs | EVT measure (10-18 fan re-measure) | Fan-faked radar hold still seen in fan-running room | KEEP PARKED | Siblings (OCC-SOURCE, D2-PIR) were not evaluable, so no evidence either way |
| WATERLEAK-TRIO-UNKNOWN-1 | Three leak sensors unknown since 08-30 | UNK (verified still unknown 09-12; safety) | None | NEEDS OPERATOR | Hygiene + SAFETY: ziri bath leak sensor still "unknown" on 09-12; no owner/trigger; needs re-read now |
| WIGTON-STUCK-ZX-NO-PAGE-1 | Camera-less stuck ZX holds house HOME with no page | PHYS (Wigton) | WIGTON-URA-REENABLE-1 or another camera-less install | KEEP PARKED |  |
| ZONE-ROOM-NAME-DRIFT-1 | Renamed room drops out of zone tier | OD (approved A Tier-3, park to keep lane clear 10-20) | Lane clears, or a room rename planned | NEEDS OPERATOR | Operator already approved A; lane state now UNKNOWN to me; ask whether to start. Live exposure 0 |

### safety

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| HUMIDITY-LOW-RUNG-PAGING-KNOB-1 | LOW humidity-band NM page un-knobbed | OD 09-26 option A DROP | A LOW humidity page fires and is unwanted | CLOSE | 0 pages in 30 d; operator call was DROP |
| SAFETY-PRE-NM-SETUP-NOTIFY-RACE-1 | Safety event can reach NM before restore | EVT (measured zero races in 19 boots) | SAFETY-NO-INITIAL-SENSOR-PASS-1 approved, or sensor on within 120 s of start | KEEP PARKED |  |
| SAFETY-RECONNECT-ZERO-SIBLINGS-1 | Junk 0 can fake freeze alarm / fan baseline | EVT (freeze 0 occurrences) | Humidity <5% on fan room, or freeze alert near 0 | KEEP PARKED |  |

### security

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| EXTERIOR-DWELL-LOITER-1 | Loiterer reads pass_by (no dwell predicate) | BLK prerequisites (probe: do not build raw duration) | Camera-role gating + face-ID + track stitching | KEEP PARKED | Face-dependent: ADJACENT |
| FRIGATE-LEG-NAMING-1 | Frigate leg naming inconsistent | LOW (latent, no live bug) | None; tiebreak by recency in _prefer_canonical | KEEP PARKED |  |
| LAST-RESIDENT-EGRESS-ARM-1 | Last resident departing as earlier arm trigger | OD parsimony ("house already knows") | Producer proves yield | KEEP PARKED | ADJACENT (identity->security) |
| LOCK-REGIME-BOOT-REALLY-AWAY-1 | Post-restart every resident "really away" so face can release lockout | BLK lockout switch OFF | switch.ura_security_coordinator_garage_lockout ON | KEEP PARKED | ADJACENT: lockout schedule shipped_organic 11-12; ON is imminent. Check before enabling |
| SC-ARMING-ALARM-ONLY-1 | SC arming auto-follow weak; make alarm-only | BLK lockout Phase 1 | GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 Phase 1 ships | TRIGGER FIRED | Parent is shipped_organic (11-12 15:30). ADJACENT |
| SC-SWEEP-CLOSES-OPEN-GARAGE-1 | Hourly sweep closes any open garage regardless of occupancy | OD pick A/B pending | Prerequisite to lockout Phase 2; after RETRY-CAP-1 | NEEDS OPERATOR | ADJACENT; also needs operator pick A vs B |
| SECURITY-CENSUS-UNKNOWN-WIRE-1 | Auto-lock-all on unknown person is unwired | OD defer+measure (footgun) | Unknown-count FP/FN rate measured; refire-loop must-fix first | KEEP PARKED |  |
| SECURITY-ENTRY-VERDICT-NAME-1 | Entry verdict names the door not the person | LOW misframed + sparse (10-14) | Naming rate >40% AND a correlation primitive | KEEP PARKED | Face/egress ADJACENT |

### tooling

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| KHOST-2 | Disposition buttons on hosted board | SUP (card says shipped_note live 08-11) | Board JS deployed | CLOSE | Disposition queue is in use (CLAUDE.md kanban.dispositions.pending.jsonl); card self-contradicts |

### ux

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| HOUSE-DIALOGS-CLEANUP-1 | House settings dialogs cleanup | OD (shipped v5.103.36; needs operator read) | Operator says "house menus OK" or finds issue | NEEDS OPERATOR | Soak-exit: operator read only; ask once |
| ZONE-DIALOGS-CLEANUP-1 | Zone dialogs cleanup | Shipped; operator "OK for now" 10-15 | Operator finds issue | CLOSE | Operator answered OK; close |

### wigton

| Card | Problem | Why parked | Revival trigger | Verdict | Note |
|---|---|---|---|---|---|
| WIGTON-URA-REENABLE-1 | Bring URA back at Wigton | PHYS/OD (operator 10-20: do not start stage 1) | Operator raises it | KEEP PARKED | Operator: do not raise again |
