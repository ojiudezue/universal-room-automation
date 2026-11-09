# Plan review 1 of 2 (COMPLETENESS): guest mode split

**Plan:** `docs/planning/PLANNING_guest_mode_split_2026_11.md` @ `0dc36450` (rev 1). **Card:** `GUEST-MODE-SPLIT-VISITORS-1`.
**Reviewer:** ura-planner, Mode 2, framing = completeness (independent re-enumeration). Review 2 (adversarial
build-prediction) is separate and must not reuse this framing.
**Date:** 2026-11-09. **Code base read:** `develop` @ `b1d0a3d5` (plan base `6b97e434`; presence gate lines unchanged).

**Read completely before reviewing:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (860 lines, §10 ledger
1-29), `docs/architecture/SENSOR_FLEET_CLASSES.md`, `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`, and, because
the consumer enumeration covers HVAC preset / arrester / fan readers of GUEST, `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`
(726 lines, §10 C1-C38). No ledger claim is re-asserted below.

**Verdict: FIX-PLAN-FIRST.** Fixes applied in the same commit as plan rev 2. After rev 2 the plan is ready for review 2
(build-prediction). The build stays blocked on D0 (now an explicit dispatch gate).

---

## 0. Operator answers folded in (binding, `operator_answers_2026_11_09`)

| # | Answer | Effect on the plan (rev 2) |
|---|---|---|
| 1 | Room leg MANDATORY; entry = room + one other leg (cam or WiFi); cam + WiFi without room may NOT enter | Entry rule, INV-SPLIT-1, pair matrix, §2.2 table, confidence (S5/S8 now need no change), knobs (two confidence constants dropped). INV-GUEST-LEAD is KEPT and strengthened, not relaxed |
| 2 | Real guest stayed 3-4 weeks in October; D0 locates the dates; 10-17 likely inside | §0 framing of 10-17 as the FP shape withdrawn; D0 Q0 added (locate the stay); the replay is scored for RECALL on the stay, not only FP removal; new go/no-go clause |
| 3 | Operator adds a BLE scanner to Guest Bedroom 2 | Recorded in §1.3 as an operator-owned precondition/observation, not a deliverable; D0 notes whether it was in place for any measured window |

---

## 1. Findings

Severity is about what a builder or the live house would get wrong if the plan shipped as written.

| ID | Sev | Finding | Evidence | Fix in rev 2 |
|---|---|---|---|---|
| F1 | HIGH | Entry rule contradicts operator answer 1: rev 1 admits `cam+wifi` (living-room gathering) and says it relaxes INV-GUEST-LEAD | plan §2.2, §2.4 INV-SPLIT-1, §1.2 row 1; card `operator_answers_2026_11_09` (1) | Entry = `room AND (cam OR wifi)`. INV-SPLIT-1 restated; `cam+wifi` row now "visitors_present, no GUEST"; INV-GUEST-LEAD kept |
| F2 | HIGH | §0 and D3's discriminating criterion frame the 10-17 21:06Z entry as the FP shape. The 10-17 audit itself (§0 line 8, §5) says GUEST was "plausibly CORRECT" (a guest staying a month), and operator answer 2 puts 10-17 inside a real stay. The plan's FP motivation is therefore unmeasured: `house_state_log` shows GUEST entries every few days 09-17..10-17 and none since 10-17; GUEST-FP-RESIDUALS-1 measured the FP population collapsing to zero after v5.79.0 (09-10). The second-leg rule may mostly REMOVE real-guest GUEST episodes | `AUDIT_guest_mode_fp_2026_10_17.md:8`, `:60`, `:99-101`; URA DB `house_state_log` (read-only copy, 2026-11-09): last GUEST row 2026-10-17; GUEST-FP-RESIDUALS-1 `measured_2026_09_15` | §0 rewritten; D0 Q0 locates the stay; Q3 scores RECALL on the stay and FP outside it; new go/no-go: if room-alone entries outside known visits are ~0 since v5.79.0 AND the second leg loses a material share of the stay's entries, stop and page the operator before build (marginal-benefit pushback recorded in §2.3) |
| F3 | HIGH | D0 cannot measure the WiFi leg on the October stay: HA recorder `purge_keep_days: 7` (live `configuration.yaml:13`), `census_snapshots` has no WiFi column (`database.py:1064-1078`), `unknown_devices` has 0 rows. Rev 1's Q1 says "split by days with and without an operator-known visit" as if visit days were in the window | `/Users/okosisi/ha-config/configuration.yaml:12-16`; `database.py:1064`; DB copy `select count(*) from unknown_devices` = 0 | D0 states the limit: WiFi FP measurable only on the last ~7 days (no guest present per F-5 §9: zero GUEST ticks 11-01..11-08); WiFi RECALL unmeasurable for October except the one hand-recorded 10-17 edge in the 10-17 audit (MacBookAir, 20:12:54Z). Go/no-go therefore defaults the WiFi leg OFF unless the operator accepts FP-only evidence. Room + cam replay for October IS feasible (`occupancy_events` from 2025-11-20, `census_snapshots` from 2026-08-10, `house_state_log` from June) |
| F4 | HIGH | D0 does not actually gate the build: §0 table says D0 gates "D1 and the default of D3's WiFi leg", so D2/D3 could be dispatched before D0, and the "stop and page" clause is buried | plan table line 10, §5 D0 go/no-go | New §5.0 "Build dispatch gate": no builder dispatch for ANY deliverable until §D0-results is committed with a verdict line `D0 GATE: GO` (or `GO-WIFI-OFF`) and the operator has confirmed the stay dates and the real/FP labels |
| F5 | MED | GUEST consumer table (§3.3) misses the IMPLICIT consumers, i.e. readers keyed on state sets that exclude `guest`, and misstates one direction. (a) NM exterior-person severity: GUEST = MEDIUM always; `home_night`/`sleep` = CRITICAL; `home_day` = LOW/HIGH. Fewer GUEST episodes during a real stay = CRITICAL pages at night for the guest walking outside (rev 1 says only "fewer MEDIUM-instead-of-LOW"). (b) HVAC hold selection: `HVAC_EVIDENCE_RULE_STATES` = (home_day, home_evening), GUEST uses the legacy tail (`hvac_zones.py:1482-1486`). (c) Fan night trust: `FAN_TRUST_STATES` = (home_night, sleep, waking) excludes guest (`hvac_fans.py:596`, `:1213`, `:1442`) and the fan recheck sleep veto reads the same set. (d) GUEST blocks SLEEP all night (presence §10 #29), so every SLEEP-keyed consumer is a GUEST consumer by absence. (e) `aggregation.py:4871-4873` non-sleep person fallback; `security_lock_regime.py:764` `_HOME_STATES` release. (f) Override entry paths `select.py:280`, service `__init__.py:6200` / `presence.set_house_state_override` `:8663` | grep `'HouseState.GUEST\|"guest"'` over the package; `const.py:2667-2762`; `hvac_const.py:1067`, `:1082`, `:1097` | §3.3 split into explicit readers (rev 1 list + `aggregation.py:4873`, `const.py:2677`), implicit set-membership readers (b)-(e), and entry writers (f); NM direction corrected; D0 Q3 adds "real-guest nights that would lose GUEST" so the CRITICAL-page cost is counted |
| F6 | MED | Restart consequence understated. Legs are RAM-only; a restored GUEST (non-override, ≤ 1800 s stale, `manager.py:688-719`) is held by `room` only after boot (WiFi entries never re-form for a device that stayed connected across the restart; cam latch lost). If the room is empty at that moment the house exits after persistence, and RE-ENTRY then needs a fresh camera run: the WiFi leg cannot re-fire for that guest until their phone disconnects and reconnects. Also: boot-seed residual `GUEST_BOOT_SEED_MIN_RESIDUAL_S` = 300 equals the exit persistence default 300 (coincidental equality, race already present today) | `const.py:483`; `presence.py:5745-5768`, `:7328-7382`; `house_state.py:137` | Non-goal text extended; INV-SPLIT-1 scoped to infer() entries (restore and override exempt, restored GUEST discharged by the hold rule); test `test_restored_guest_held_by_room_only`; README must list the re-entry residual |
| F7 | MED | S3 ambiguity: "evaluate legs for `visitors_present` only" in every other state. `_guest_room_gate_armed` is not pure: it entry-resets `_guest_room_gate_fired_room`, clears `first_seen` on a known person and INFO-logs every tick while armed (`presence.py:5953-5996`). Calling it in SLEEP/AWAY adds a per-tick INFO line all night for a sleeping guest and can change `guest_reason`/confidence locals, which breaks INV-SPLIT-3 byte-identity unless the builder guesses right | `presence.py:5941-5996`, `:6610-6637` | S3: room leg NOT evaluated outside HOME_*/GUEST (today's behaviour); cam = latch read (pure), WiFi = pure census read; S3 must not touch the `guest_room_gate_armed` / `unid_gate_armed` locals |
| F8 | MED | Live oracles L4/L5 rely on unreadable sources. L4 reads the presence INFO line, but URA INFO is not kept (HVAC state of play §4.3 "INFO log only (not kept — log level WARNING)"; presence §1 / FRIGATE-FACE-BRIDGE card: boot INFO line could not be read). L5 reads `guest_reason` from `house_state_log`, which has no such column (`database.py:1494-1501`: timestamp, state, confidence, trigger, previous_state). L3 is tautological (both sides derive from the same legs) | cited | Oracle = the RECORDED `guest_reason` attribute on the house-state sensor (it is not in `_unrecorded_attributes`, `sensor.py:5714-5724`), read from the recorder at each GUEST transition timestamp in `house_state_log`. L3 replaced by a discriminating check; INFO line kept as a convenience only |
| F9 | MED | Kill switch semantics: rev 1 says the cam latch "is cleared by the guest-detection switch OFF". The switch only `setattr`s `_guest_detection_enabled` (`switch.py:3794-3805`); there is no hook | `switch.py:3785-3805` | Latch is cleared, and all legs forced False, by the compose step on the first tick that reads `_guest_detection_enabled` False (level-triggered, same as the room gate's own clear at `presence.py:5957-5959`) |
| F10 | MED | Parked-plan triggers not enumerated. `PLANNING_house_away_flap_untracked_occupant.md` Rev 4 (B) guest-room AWAY veto is parked with trigger "guest accuracy becomes a priority (a long stay or a party)", which both the October stay and this cycle fire. `GUEST-IDENTITY-PHONE-LEFT-BEHIND-1` (parked) is the exact residual class the mandatory second leg addresses (resident in guest room without BLE). Neither is in §8 | `PLANNING_house_away_flap_untracked_occupant.md:5`, `:25`; board card bodies | §8 gains both, with dispositions: Rev 4 (B) trigger FIRED, not folded (AWAY-side, different invariant), card it for the operator; PHONE-LEFT-BEHIND-1 stays parked, its residual is reduced by D3 + the GB2 scanner, re-measure after |
| F11 | LOW | D4 trip-wire condition "room false AND cam false for the whole span": cam cannot hold GUEST (INV-SPLIT-2) and Path A is not evaluated in GUEST (`presence.py:6601-6606`), so the cam term reads a stale latch | `presence.py:6601-6609` | D4 = GUEST for > bound with `room` false throughout (WiFi is then the only possible holder) |
| F12 | LOW | Confidence knobs `GUEST_TWO_LEG_CONFIDENCE` / `GUEST_CAM_WIFI_CONFIDENCE` become unnecessary once room is mandatory: the existing layering (room+unid 0.95, room 0.9, `presence.py:6645-6650`) and the S8 override guarded on `guest_room_gate_armed` (`:7236`) are already correct for every allowed pair | cited | Both constants dropped; S5 keeps its values (room+cam 0.95, room+WiFi 0.9); S8 unchanged; the debug canary condition is narrowed to HOME_* entry ticks |
| F13 | LOW | §0 line "GB2 has no scanner of its own" is now an operator action in flight (answer 3); and the config-first section offered "scanner_areas borrowing" as an equal option | card answer (3) | §1.3 records the scanner as an operator-owned precondition with its own observation (resident in GB2 reads `location == "Guest Bedroom 2"`) |

No CRITICAL. The rev 1 plan's core composition sites were found complete; the gaps are the operator-rule change, the
empirical premise (F2/F3), the build gate (F4), and the consumer/oracle enumeration.

---

## 2. Independent re-enumerations

### 2.1 Readers of the GUEST state (grep `HouseState.GUEST|"guest"|GUEST.value` over the package, plus state-set readers)

| Reader | file:line | Kind | In rev 1? |
|---|---|---|---|
| HVAC preset map guest → home | `hvac_const.py:1293` | trust | yes |
| HVAC arrester hold-preserving states | `hvac_const.py:229` (+ `hvac_override.py:1017`, `:1630` docstrings) | trust | yes |
| Custom Preset Ranges predicate | `preset_overrides.py:115-148` | trust | yes |
| Dynamic preset guest offset reset | `dynamic_preset.py:861` | trust | yes |
| Security armed-state map | `security.py:183` | trust | yes |
| SC lock regime | `security_lock_regime.py:776`, `:808`, `:1410`, `:1477`; `_HOME_STATES` `:764` | trust (lock) | partly (`:764` missing) |
| NM exterior-person severity | `const.py:2667`, `:2677`, `:2761-2762` | trust (severity) | yes, direction wrong (F5a) |
| Bayesian learning suppression | `__init__.py:3278` | trust (learning) | yes |
| Occupancy-anomaly suppression | `binary_sensor.py:3570` | display | yes |
| `binary_sensor.ura_guest_mode` | `binary_sensor.py:2450` | display | yes |
| Routine forecaster passthrough | `routine_forecaster.py:101-105` | display | yes |
| Memory facade | `memory_facade.py:279` | display | yes |
| Non-sleep person fallback (zone_persons_home) | `aggregation.py:4871-4873` | trust (zone occupancy) | **no** |
| HVAC hold-table selection (evidence vs legacy tail) | `hvac_zones.py:1482-1486`, `hvac_const.py:1097` | trust, implicit | **no** |
| HVAC night tail | `hvac_zones.py:1452`, `hvac_const.py:1082` | trust, implicit | **no** |
| Fan night trust / sleep-onset / hold | `hvac_fans.py:580`, `:596`, `:1213`, `:1442`; `presence_fan_recheck` sleep veto via `FAN_TRUST_STATES` | trust, implicit | **no** |
| Every SLEEP-keyed consumer (GUEST blocks SLEEP, §10 #29) | `house_state.py:116-121` | implicit | partly (non-goal mentions it) |
| Lighting in URA | none found (grep) | — | yes |
| HA YAML wall-panel automation | `automations.yaml:8270` per 10-17 audit | cosmetic | yes |

### 2.2 Readers of the gate and the census values

- `guest_armed` / `guest_room_gate_armed` / `unid_gate_armed` / `_guest_reason`: only `presence.py` (sites S1-S13 in the
  plan; re-grep matched rev 1's list exactly: `:6563-6613`, `:6615-6637`, `:6645-6670`, `:7046`, `:7236`, `:7328-7382`,
  `:7596-7603`, `:8227`, `:5605-5614`, `:5941`, `:5998-6070`) plus `sensor.py:5836` (publish) and `switch.py:3899` (kill).
- `identified_guests` / `_last_identified_guests_count`: produced `camera_census.py:6355-6363`, read only by
  `sensor.py:3765-3772` (display). No trust reader. Using it for `visitor_names` (display) does not fire
  EGRESS-EXIT-JOINT-DEPART-ONE-ROW-1's trigger ("a consumer ACTS on exit person_id").
- `wifi_guest_floor`: produced `camera_census.py:6319`, `:6435`; read only by `sensor.py:3792` (display).
- `unidentified_count`: readers in `presence.py` (path α `:1227-1232`, Path A), `aggregation.py`, `binary_sensor.py`
  (`URAUnexpectedPersonSensor` `:1889`), `sensor.py`, `database.py` (snapshots). The plan changes none of them (census
  arithmetic is a non-goal).

### 2.3 Transitions into and out of GUEST

| Path | Site | Gated by the new rule? |
|---|---|---|
| infer() entry from HOME_* | `presence.py:1425-1432`, input `guest_gate_armed` from `:6586-6601` | yes (S1) |
| infer() exit (above sleep branch, I-D1) | `presence.py:1399-1401` | via hold (S2) |
| Exit persistence veto | `presence.py:7328-7382` | unchanged |
| GUEST min dwell 300 s | `house_state.py:137` | unchanged |
| GUEST → AWAY | `house_state.py:116-121`; nobody-home / α / β | unchanged |
| No GUEST → SLEEP edge | `house_state.py:116-121`, `:219-221` (§10 #29) | unchanged |
| Manual override (select) | `select.py:280` → `house_state_machine.set_override` | exempt by design |
| Override (service `ura.set_house_state`) | `__init__.py:6200`; `presence.set_house_state_override` `:8663-8683` | exempt by design |
| Restart restore (≤ 1800 s stale) | `manager.py:688-719`, `house_state.apply_restored` | exempt from entry; discharged by the hold rule (F6) |
| Kill switch OFF | `switch.py:3794`; room gate early return `presence.py:5957`; Path A `:6019` | discharges via exit |
| Arm-state clear on edges | `presence.py:7596-7603`, teardown `:8227`, non-home `:6568-6575` | cam latch must survive these (S10) |

### 2.4 Parked-plan triggers this cycle would fire

| Parked item | Trigger | Fires? | Disposition |
|---|---|---|---|
| `PLANNING_house_away_flap_untracked_occupant.md` Rev 4 (A) camera guard + (B) guest-room AWAY veto | "guest accuracy becomes a priority (a long stay or a party)" | **YES** (October stay; this cycle) | Not folded (AWAY-side invariant, different cycle). Card a re-evaluation for the operator; this cycle's D0 Q2 output (guest-room runs during the stay) is its input |
| `GUEST-IDENTITY-PHONE-LEFT-BEHIND-1` | "resident-in-guest-room-without-phone false-GUEST recurs" | not measured as recurring; D3 reduces the class | stays parked; link; re-measure after the GB2 scanner |
| `GUEST-FP-RESIDUALS-1` | "guest entries resume above …" | the 09-17..10-17 entries are plausibly the real stay, not FP | stays parked; note added |
| `CENSUS-GUEST-FLOOR-1` | already revived 10-17 | — | stays pre_planning; owns device memory/decay |
| `GUEST-GATE-DOOR-IDENTITY-1` | egress attach ≥ 50 % sustained 14 d | no | parked |
| `EGRESS-EXIT-JOINT-DEPART-ONE-ROW-1` | a consumer ACTS on exit `person_id` | no (display only) | parked |
| `GUEST-ROOM-FAN-HOLD-1` | guest night fan off under a sleeping guest | no (no fan change) | parked; note that fewer GUEST nights put guest-room fans under `FAN_TRUST_STATES` rules more often |
| `EXTERIOR-GUEST-EGRESS-1` | identity at egress shown to miss real guests | no | parked |
| Known-guest-face-as-evidence (rev 1 §2.3) | `known_face_guests` non-empty AND ≥ 10 confirmed rows / 14 d | no | parked |

### 2.5 "No face path enters GUEST today": VERIFIED

- `guest_armed = guest_room_gate_armed` in HOME_* (`presence.py:6601`) and GUEST (`:6609`); False elsewhere (`:6613`).
  `unid_gate_armed` is read only by `guest_reason` (`:6632`) and confidence (`:6645`).
- `_guest_room_gate_armed` inputs: `_guest_room_state[*].first_seen` written by the guest-room occupancy listener and the
  boot seed (`presence.py:5700-5790`), and `_is_known_person_in_room` (person_coordinator `location`, BLE-sourced,
  `:5859-5920`). No face, camera or census read in the gate or its listener (grep of `face|camera|census` over
  `:5793-5860` = no hits; `person_coordinator.py` has no face input).
- Faces reach presence via `unidentified_count` (Path A, corroborator only) and `_handle_face_arrival`
  (`SIGNAL_PERSON_ARRIVING`, no house-state write). So the claim holds on entry AND hold.

### 2.6 Knob ladder

All rev 2 numbers are rung 1 with a why and kill semantics, except the reused rung-2/3 knobs. Dropped in rev 2:
`GUEST_TWO_LEG_CONFIDENCE`, `GUEST_CAM_WIFI_CONFIDENCE` (F12). `GUEST_WIFI_SUSTAIN_S` clamp-at-read is stated.
`GUEST_WIFI_BOOT_EXCLUDE_S` keeps its own constant (coincidental-equality rule). No new options-flow field or entity
knob: consistent with the parsimonious-config rule.

### 2.7 Acceptance criteria discrimination

- D1 restart criterion discriminates (`last_changed` reuse would read 3 after sustain). Kept.
- D2 face criterion discriminates. Kept.
- D3 10-17 replay: rev 1 asserted the outcome under an FP framing. Rev 2 keeps the reason-string discriminator but
  re-labels the outcome against the October ground truth (a real guest: losing GUEST there is a recall cost, not a fix).
- L3 was tautological; replaced (F8).

---

## 3. Summary statistics

| Severity | Found | Fixed in plan rev 2 | Deferred |
|---|---|---|---|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 4 | 4 | 0 |
| MEDIUM | 6 | 6 | 0 |
| LOW | 3 | 3 | 0 |

| Class | Count |
|---|---|
| Operator ruling not reflected in plan | 1 (F1) |
| Unmeasured premise / measure-before-build gap | 3 (F2, F3, F4) |
| Consumer enumeration incomplete (implicit state-set readers) | 1 (F5) |
| Restart/restore semantics (Bug Class: restart resilience) | 1 (F6) |
| Side-effecting predicate called as pure (ambiguity) | 1 (F7) |
| Unreadable live oracle | 1 (F8) |
| Kill-switch semantics assumed, not verified | 1 (F9) |
| Parked-trigger enumeration miss | 1 (F10) |
| Spec redundancy / dead knob | 2 (F11, F12) |
| Stale precondition | 1 (F13) |

**QUALITY_CONTEXT candidate:** "implicit consumers" — readers keyed on a state SET that excludes a state are consumers of
that state by absence (here `FAN_TRUST_STATES`, `HVAC_EVIDENCE_RULE_STATES`, every SLEEP reader while GUEST blocks
SLEEP). A literal grep for the state string misses them. Suggest adding to the consumer-check guidance.
