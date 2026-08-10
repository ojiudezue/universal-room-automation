# CATALOG: Cross-Correlation / Corroboration Primitives in URA

**Date:** 2026-07-28 · **Method:** 3 parallel exhaustive sweeps (presence tier / census+person tier / cross-cutting), every entry verified at file:line against HEAD (v5.34.1).
**Why:** operator directive before designing any stuck-signal watchdog — *"I don't want to roll another one without cataloguing and examining them."* This doc is the adjudicator for **extend-vs-new**.

**Count: ~70 primitives.** Taxonomy of actions: `veto` (override a signal) · `discount/hold` (extend or suppress transitions) · `exclude` (drop a signal from computation) · `envelope` (physics-bound a stale value) · `echo-verify` (commanded vs oracle) · `behavioral-verify` (commanded vs conduct) · `reconcile` (desired vs actual, re-assert) · `consensus` (scored cross-signal agreement) · `dedup/fusion` (multi-source combine) · `staleness` (age-based trust decay) · `z-score` (statistical baseline anomaly).

---

## TIER 1 — Presence (31 primitives)

### House-state vetoes & gates
| # | Primitive | file:line | Correlates | Rule → Action |
|---|---|---|---|---|
| P1 | AWAY-veto α (v4.7.14) | presence.py:994-1004, 4491-4693 | ACTIVE phone trackers vs camera census/zones | all-away AND unid==0 AND census==0 → veto AWAY @0.95 (inline) |
| P2 | AWAY-veto β (v5.7.0 WS-A) | presence.py:1067-1111, 4570-4693 | LOST-admitted trackers vs indoor zones vs LOST-stamp grace vs sleep | relaxed denominator + youngest-stamp grace + indoor-clear debounce + immediate-engage-empty-house bypass → veto AWAY @0.95. Knobs: CONF_LOST_AWAY_GRACE_MIN, _SLEEP_EXEMPT, _INDOOR_CLEAR_TICKS, CONF_ZONE_IS_OUTDOOR |
| P3 | Sleep-hours guest suppression | presence.py:1144-1158 | unid/guest gate vs clock vs state | no GUEST entry during sleep hours; GUEST-exit evaluated before sleep branch |
| P4-P8 | Shared veto helper Patterns A-E (#48) | presence.py:1633-1828 | A: house AWAY (helper form, length-parity fail-safe). B: zone persons-home during sleep → veto @0.90. C: persons-home + sensors quiet ≥300s (inline) → veto @0.85. D: WAKING needs 90s sustained (inline) + 3h backstop (inline). E: GUEST-exit needs quiet ≥ persistence | veto/hold. Pattern F (room_level_weighted) INTENTIONALLY unhandled — vestigial |
| P9 | Guest gate arming | presence.py:4351-4410 | unid count vs census confidence vs persistence | existence+confidence+persistence all required → arm GUEST (single-tick FP can't arm) |

### Provenance / fan-interference / consensus
| # | Primitive | file:line | Correlates | Rule → Action |
|---|---|---|---|---|
| P10 | Fan-interference observation | presence.py:3208-3367 | fan-on vs mmwave-SOLE provenance vs BLE-L1 vs zone camera | flag rooms — OBSERVATION-ONLY (must snapshot reads before ever promoting to gate) |
| P11 | Fan-interference silent gate + BLE ladder | presence.py:3369-3601 | suspect rooms vs BLE L1/L2/L3 | L1 → trust mmwave; else HOLD occupancy (extend-only, truth-preserving). Knob: hold_s clamp 60-1800 |
| P12 | signal_consensus arithmetic (D5) | presence.py:5786-5839 | 4 deltas: phones-away∧zones-occupied −0.4; stale/lost tracker −0.2; camera-w/o-tier1 −0.15; low engine confidence −0.1 (all inline) | consensus = max(0, 1−Σ); <0.6 sustained tracked. Consumers: HVAC + compliance defer gates |
| P13 | Camera/Tier-1/mmwave tally | presence.py:5650-5687 | per-zone camera vs tier1 occupied counts | feeds consensus delta 3; diagnostic |
| P14 | Per-zone BLE-tier weighted veto (v4.7.16) | presence.py:4815-4970 | BLE tier weights (T2=0.6) vs veto helper | VESTIGIAL — Pattern F unhandled, verdicts diagnostic-only |
| P15 | Substrate kind-precedence arbitration | occupancy_substrate.py:169-286 | entity's CONF-list memberships; cross-room claims | first-match precedence, duplicate → drop+WARN; reset+reseed kills stuck-True — role questions above the substrate resolve via `domain_coordinators.sensor_role.resolve_role` (SENSOR-CAPABILITY-1, 2026-08-09) so a per-entity capability override can retag WITHOUT extending TIER1_KINDS |
| P16 | Boot-settle gate (Predicates A/B) | presence.py:4463-4491, 1994-2118 | real-input presence vs boot transient | hold cross-coordinator fan-out until real input / HA started / timeout |

### HVAC consumers of presence trust
| # | Primitive | file:line | Rule → Action |
|---|---|---|---|
| P17 | HVAC consensus defer gate (D6) | hvac.py:1084-1143 | consensus<0.5 ∧ transition<30s → defer; release @≥0.7 (asymmetric, inline) |
| P18 | **Zone stale-occupancy multi-source confidence failsafe** | hvac.py:1253-1303 + presence.py:1838-1940 | occupied > max_occupancy_hours → demand ≥min(2,possible) of {recent motion<1800s, BLE, camera, ≥2 rooms} → confirm-and-reset OR force away + sweep. Sleep-skipped |
| P19 | HVAC D1 vacancy override | hvac.py:1235-1251 | vacant past grace → force away + sweep |
| P20 | Night-window zone-persons trust veto (v4.7.13+) | hvac.py:1324-1378 | zone person "home" during night states → suppress flip-to-away (sensors degenerate at night; phone wins) |
| P21 | HVAC D5 duty-cycle guard | hvac.py:1305-1307 | runtime exceeded (not sleep) → force away |

### Room tier (coordinator.py)
| # | Primitive | file:line | Rule → Action |
|---|---|---|---|
| P22 | **Fix #9 stuck-sensor exclusion** | coordinator.py:1502-1543 | binary sensor continuously-ON ≥ _stuck_sensor_hours (4h) → EXCLUDE from occupancy + WARN (log-only; no notify; flap-evadable; RAM-only) |
| P23 | Fix #10 all-unavailable grace hold | coordinator.py:1482-1500 | all sensors unavailable within grace → hold previous occupancy |
| P24 | **RESILIENCE-001 max-active failsafe + Tier-1 freshness** | coordinator.py:1690-1754 | occupied > failsafe (60min closet/bath, 4h else) → if Tier-1 fresh (<2× timeout) skip (sleeping body); else force vacant |
| P25 | Fix #8 camera-override vs failsafe | coordinator.py:1756-1785 | camera person on → override vacancy UNLESS failsafe just fired (stuck camera can't defeat failsafe) |
| P26 | BLE extend-not-create (v3.8.9) | coordinator.py:1787-1878 | BLE may EXTEND motion-confirmed occupancy, never CREATE; chain-or-motion admission; kill switch MULTIPLIER=0 |
| P27 | Fix #6 entry debounce | coordinator.py:1586-1618 | sensors active ≥ debounce before confirming entry |

### Fan-recheck (presence_fan_recheck.py)
| # | Primitive | file:line | Rule → Action |
|---|---|---|---|
| P28 | Arm-eligibility veto ladder (D1/D1.5) | :380-504 | mmwave-sole ticks → fan on → boot-settle → manual-cooldown → rate cap → BLE L1/L2/L3 × tier × high-still-risk × trust-sensors → authorize/veto pause-recheck (per-reason counters) |
| P29 | Mid-tick BLE cancel | :767-835 | L1 phone re-appears during ARMED/PAUSED → cancel + restore |
| P30 | High-still-risk room-type dial | :473-493 | bedroom/media rooms reject weak (L2/sensors-only) drop-authorization |
| P31 | Presence→Optimizer intent veto | presence.py:6280-6337 | observation_mode / presence-input-sensor → veto optimizer actuation |

---

## TIER 2 — Census / Person (16 primitives)

| # | Primitive | file:line | Rule → Action |
|---|---|---|---|
| C1 | Frigate-vs-binary cross-validation | camera_census.py:1198-1231 | Frigate wins numeric; agreement label both_agree/close/single_source (never emits `disagree`); binary is floor-only — binary>frigate never raises count |
| C2 | Same-area spatial dedup + raw_pre_dedup_sum | :1385-1412 | per-area max, cross-area sum; **deliberate lockstep FORK with C5** (Bug Class #53 risk documented) |
| C3 | Face ∪ BLE person cross-correlation (raw path) | :1237-1309 | union of face+BLE identified; guests = camera surplus. GAP: raw path lacks freshness + not_home veto (enhanced-only) |
| C4 | Confidence banding | :1279-1294 | agreement × counts → none/low/medium/high; feeds guest-gate hardening |
| C5 | Enhanced unrecognized count + BLE-cancel-by-area | :1818-1974 | face-fresh −1/camera; area max; subtract min(area_max, ble_here); invariants I1-I3; fails toward over-arming |
| C6 | Face freshness + person not_home veto (v5.31.0) | :2143-2221 | face counted iff real camera + age≤1800s + person≠not_home (fail-OPEN) |
| C7 | **Peak-hold / pending / decay state machine** | :1648-1798 | up needs 15s sustain; hold **3 min** (15→3 SHIPPED v5.9.0); decay −1/300s as `max(fresh, peak−steps)` → **CANNOT pull below fresh: a stuck camera count is the floor, held INDEFINITELY** |
| C8 | Degraded mode | :1014-1041 | platform-down fallbacks, single_source labeling |
| C9 | WiFi guest floor (excluded from count) | :1976-2141 | 5-filter guest-VLAN count; 3-layer person exclusion + MAC; recency 4h (**docstring stale: says 24h**); attribute-only |
| C10 | Property (exterior) census | :1114-1192 | binary OR, instant-rise peak semantics |
| C11 | tracking_status derivation + Bermuda decay | person_coordinator.py:123-435 | ACTIVE → STALE (decay 300s, conf×0.5) → LOST (fallback to person entity) |
| C12 | BLE pre-arrival divergence | :248-306 | LOST≥15min then BLE room hit → pre-arrival event |
| C13 | Scanner-triangulation confidence | :815-936 | very-close/close counts → 0.9/0.7/0.5/0.3 |
| C14 | 3-tier room resolution + occupancy disambiguation | :499-714 | area→scanner-area→occupied-room tie-break |
| C15 | is_room_direct_ble / BLE tiers | :1200-1274 | Tier1 BLE standalone; Tier2 needs motion confirm |
| C16 | PersonPhoneLeftBehindSensor | binary_sensor.py:1295-1406 | BLE-home ∧ census==0 ∧ no camera 1h ∧ not sleep-hours → phone-left-behind flag (inline literals 1.0h/22/7) |

Zone-level: ZonePersonTrackingStatus (aggregation.py:5084), ZoneIdentifiedPersons (:5717), ZoneGuestCount (:5807 — **uses HOUSE census for every zone**, duplicated across zones; stale residents inflate guests).

---

## TIER 3 — Cross-cutting (23 primitives)

### Physics envelopes (LKG)
| # | Primitive | file:line | Rule |
|---|---|---|---|
| X1 | LkgValue.envelope() | lkg.py:47-79 | freshness-as-byproduct (no forgettable is_stale()); tiers fresh/bounded/stale/expired; bounds_fn code-owned, never persisted |
| X2 | soc_bounds | energy_const.py:1511-1583 | charge/discharge-rate cone; tiers 60s/600s/6h (inline) |
| X3 | solar_upper_bounds + stamped gate | energy_const.py:1609-1660 | hi widens to nameplate, lo=0; **ADMIT must gate on `stamped`, not hi** (A-HIGH-1); 15-min max age |

### Write verification (energy)
| # | Primitive | file:line | Rule |
|---|---|---|---|
| X4 | WriteVerifier echo-verify | energy_write_verify.py | commanded vs cloud oracle after window; 8 statuses; ±2 reserve tolerance; factor-1000 → UNIT_MISMATCH (wiring, never "reverted"); NM latch/day; NEVER actuates (W-6) |
| X5 | Behavioral conduct check (v5.19.0 D1) | :1758-1886 | SOC < floor−deadband ∧ discharging, N ticks → hardware_noncompliance ALERT; legal-exception resets; grid-witness-blind ABSTAINS |
| X6 | Pending-write watchdog ladder (D2) | :1913+ | divergence age 15/30/60min escalation, max attempts, cooloff |

### Reconciliation
| # | Primitive | file:line | Rule |
|---|---|---|---|
| X7 | ActuatorReconciler | actuator_reconciler.py | desired-vs-actual re-assert; guard chain (boot/manual/intent/debounce 15s/rate 6/h/auto-recovery); fan defers on humidity-fan/HVAC-managed/manual-cooldown/sleep/vacancy; **flap quarantine** (≥4 in 120s → quarantine until 600s stable → surfaced as "flapping" in unavailable_entities) |
| X8 | ComplianceTracker | coordinator_diagnostics.py:333-471 | commanded vs actual @120s; climate ±1.0°, cover ±5; violation-only anomalies; **consensus defer gate** (<0.6 ≥60s suppresses, switch default ON) |

### Statistical / anomaly
| # | Primitive | file:line | Rule |
|---|---|---|---|
| X9 | AnomalyDetector z-score | coordinator_diagnostics.py:742-1014 | Welford baselines; z 2/3/4 advisory/alert/critical × sensitivity; majority learning gate; suppressed-metric surface |
| X10 | RegimeDetector | regime_detector.py | Jensen-Shannon 14d-vs-baseline + persistence guard |
| X11 | Rate-of-change hazards | safety.py:245-471 | humidity_rise→WATER_LEAK (bathroom-excluded), temp rates→HVAC_FAILURE/OVERHEAT; z 3/4/5; 30-min window, no extrapolation |
| X12 | Flooding multi-sensor escalation | safety.py:1483-1527 | ≥2 leak sensors OR 1 sustained 15min → FLOODING + valve close. **NO smoke+CO AND-gate exists** |

### Energy correlation
| # | Primitive | file:line | Rule |
|---|---|---|---|
| X13 | ATTAIN solar-vs-grid attribution guard | energy.py:3237-3254 | battery_w ≤ solar_w on rise tick → skip arbitrage row (binary; partial attribution unhandled) |
| X14 | SOC 3-tier resolver + divergence | energy_battery.py:912-1000, 1243+ | wiring guards (unit, factor-1000) → point 3pp WARNING/hr → sustained 10pp/5min dwell+hysteresis NM |
| X15 | Cloud settings-lag detector (D2) | energy_battery.py:1390-1475 | oracle last_reported age >30min sustained 5min → NM daily latch; last_reported-not-last_changed (A6) |
| X16 | Drain-precedence KV expiry validation | energy_drain_precedence.py | restored state past expiry → reject |

### Weather / NM fusion
| # | Primitive | file:line | Rule |
|---|---|---|---|
| X17 | InclementFusion.decide | inclement.py:545-704 | NWS tier × condition corroboration × TOU × solar recoverability → allow/partial/full hold matrix |
| X18 | ConditionElector | weather_manager.py:785-825 | cross-provider stormy corroboration (healthy/stale only) |
| X19 | Provider divergence + health | weather_manager.py:337-364, 589-601 | high-delta divergence flag; UNAVAILABLE/STALE/HEALTHY ranking |
| X20 | DPM self-tuning baselines | weather_manager.py | 14d median + 90d p25 rings, sample floors, fixed fallback |
| X21 | NM dedup latches | _nm_cycle_a.py + sites | per-(surface,type)/day latches; knob cache flush on options-update |

### Health / sanity
| # | Primitive | file:line | Rule |
|---|---|---|---|
| X22 | unavailable_entities tracker | sensor.py:1654-1786 | per-entity reason (missing/offline_since_restart/unreachable/unknown/**flapping**); sensors vs actuators split. Tracks DEAD, not LYING |
| X23 | Energy baseline-drift sanity cap | coordinator.py:2093, 2176-2204 | implausible per-update kWh delta → baseline reset (counter rollover guard) |

Also: transit_validator.py (camera checkpoint transitions), bayesian/pattern/routine forecasters (produce "expected" baselines — potential comparison sources, not gates).

---

## THE FOUR STUCK-SIGNAL INCIDENTS vs THE INVENTORY

| Incident | Closest existing primitive(s) | Why none caught it |
|---|---|---|
| Foyer fisheye static person tracks (11h GUEST, 2026-07-28) | C7 (peak decay), P22 (Fix #9), P12 delta-3 (camera-w/o-tier1 −0.15) | C7's decay law is `max(fresh, peak−steps)` — a stuck count IS fresh, so it's the floor; **nothing ages a static camera count**. Fix #9 is room-binary-only. Consensus DID discount (−0.15) but nothing consumes consensus at the census/guest layer, and nothing notifies |
| Ezinne stuck GPS tracker (3+ days "home") | C11 (tracking decay), P1/P2 denominators | C11 decays *Bermuda*, not the HA person tier; upstream "any tracker home ⇒ home" kept person=home; no frozen-tracker (last_updated age) check, no notify |
| Jaya face latch | C6 | **CLOSED** by v5.31.0 (not_home veto). Deeper root (backlog #3) remains |
| Master mmWave phantom (empty-suite cooling) | P22, P24, P18, P11 | P22 evaded by FLAPPING (off-ticks reset the clock); P24/P18 exist for *occupancy duration* and did/could fire only after hours; P11 requires fan ON (was off). No duty-cycle variant anywhere; no notify |

**Pattern:** URA already implements the exact watchdog SHAPE — *"asserted too long ⇒ demand independent corroboration ⇒ act"* — **three times** (P22 room-binary, P24 room-occupancy, P18 zone-occupancy). What's missing is not a new concept but:
1. **The shape at the census/camera layer** (per-camera stuck non-zero count with zero interior corroboration — the exact inputs already tallied in P12/P13).
2. **A duty-cycle variant** (flap-stuck evades continuous-on).
3. **A frozen-tracker check** (person-tier last_updated age).
4. **Notification** — every existing detector acts silently (log/exclude); none tells the operator. Today's GUEST ran 11h unannounced.

---

## VERDICT: EXTEND, do not roll a new primitive

The stuck-signal watchdog should be built as **tier-extensions of the thrice-proven corroborate-or-kill shape + NM wiring**, not a new correlation framework:

- **D1 — Census layer:** per-camera stuck-count check (person_count>0, unchanged/duty-cycled ≥N h, zero interior corroboration from the P12/P13 inputs) → discount from census (age the C7 floor) + NM notify with remedy ("reload Frigate"). This is P18's logic applied one layer down.
- **D2 — Fix #9 duty-cycle variant** (P22): >X% asserted over window, PIR-uncorroborated → same exclusion path + notify. Catches the Master-mmWave class.
- **D3 — Frozen-tracker check** (extends C11): device_tracker last_updated age ≥N days while person state disagrees with all other evidence → notify (no auto-prune).
- **D4 — NM surface for the existing silent detectors** (P22, P24, P18, X7-quarantine): they already compute the stuck sets; wire them to NM with per-day dedup latches (X21 pattern).
- **Explicitly NOT:** a new consensus framework (P12 exists — consume it), auto-remediation (stage 2), new thresholds without knobs (fix the flagged inline literals where touched).

---

## ADDENDUM 2026-08-09 — D1–D4 all SHIPPED (v5.35.0, 2026-07-28). Third class found: CHATTER.

Verified in code, not from the plan: every deliverable above landed in **v5.35.0** (commit `0192ac2c3`,
tag 2026-07-28 23:18 CDT) plus hotfix v5.35.1 and observability v5.35.2 the same night.
D1 = `camera_census.py` (`_camera_stuck_state`, `_fire_camera_stuck_nm`, `stuck_cameras`);
D2 = `coordinator.py::_detect_duty_cycle_stuck`; D3 = `person_coordinator.py` frozen tracker;
D4 = `domain_coordinators/_stuck_signal_nm.py`.

**What the shared abstraction actually is.** D4 centralised the **notification**, not the detection.
`_stuck_signal_nm`'s own docstring scopes it: *"Detection + discount + notify ONLY. This module never
actuates, never mutates detector state"* — it is a fan-out for verdicts, latched per-`(kind, key)`/day,
consumed at `coordinator.py:181,192,205,206`, `person_coordinator.py:1534,1546`,
`actuator_reconciler.py:892,934`, `camera_census.py:94`. **Detection remains four bespoke
implementations** sharing only a `kind=` string. The plan said so deliberately: *"No abstraction/
unification of P22/P24/P18 in this cycle. A separate abstraction decision is pending"*, parked with the
trigger *"after D1..D4 ship and the shape is proven at four sites; separate design cycle."*
**That trigger has now fired.**

**Class 3 — CHATTER (transition-rate), invisible to both existing rules.** The taxonomy so far has two
classes: *continuous-on* (P22, `_sensor_on_since` ≥ 4h → **excludes**) and *high-duty-cycle* (D2, ≥85%
over 60 min, ≥20 ticks, PIR-uncorroborated → **notify only**). A sensor oscillating at roughly 50% duty
is caught by neither: every off-tick resets P22's clock, and the on-ratio never reaches D2's 85%.

Evidence (2026-08-09, Garage B ratgdo, 24h recorder): **3,769 off / 3,765 on / 6 unavailable** — real
oscillation, not a transport artefact. Two structural gaps compound it:

1. **Motion is unscored by design.** D2's candidate set is `mmwave_sensors + occupancy_sensors` only —
   PIR is excluded because *"PIR is our corroboration source."* So a chattering PIR is never itself
   diagnosed, and worse, it can **shield** a stuck mmWave: D2's corroboration test is satisfied by
   ≥2 PIR transitions in-window, which a chattering PIR trivially supplies. **The anchor can be the
   thing that's broken.** Operator note: ratgdo has no PIR of its own — it supervises the MyQ garage
   motion sensor, and the Zigbee/Z2M layer can make that flicker or go unavailable.
2. **Some rooms can never be scored at all.** Garage B has `mmwave_sensors: None` and
   `occupancy_sensors: []`, so D2's candidate set is empty there — the room where the incident happened
   is outside the detector's reach regardless of thresholds.

**Direction (adjacency, not a fifth detector).** Per this doc's standing verdict, chatter is a third
*verdict kind* on a generalised per-sensor reliability scorer — `_detect_duty_cycle_stuck` widened to
score all binary sensor kinds on **on-ratio + transition-rate + unavailable-rate** and to emit
`kind=` per class through the existing D4 notifier — not a new module. Unification is warranted only
where the shapes genuinely match: the census (person *count*) and frozen-tracker (*timestamp* age)
detectors are different shapes and should keep their own detection while continuing to share D4.
Consequence/exclusion policy is tracked on **STUCK-SENSOR-1** (`kanban.data.yaml`), whose verified
discriminator is **corroboration, not house state** — chatter folds into that card rather than opening
a new one.

---

**Flagged hygiene while in there:** C9 stale docstring (24h vs 4h); P14 vestigial weighted-veto (delete or promote); inline-literal knob list (presence sweeps); no smoke+CO AND-gate (X12 note, separate safety item); LKG outdoor-temp factory unwired (D3 energy cycle, known).
</content>
