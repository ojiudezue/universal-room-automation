# Plan review R1 (completeness): SLEEP-mask fix, 5-min resident BLE memory, AWAY observability

**Plan:** `docs/planning/PLANNING_house_state_sleep_mask_ble_memory_observability.md` Rev 1 (commit `0eeacbb9e`, develop).
**Tier:** 3, review 1 of 2 (completeness re-enumeration). R2 (build prediction) is separate.
**Reviewer:** ura-reviewer, 2026-10-18. Read first, completely: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. the bb71d7690 nobody-home / SLEEP-mask material and §10 ledger 1-15), `SENSOR_FLEET_CLASSES.md`, and `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (an HVAC trust consumer of D2 was found; no ledger claim re-asserted).
**Method:** every surface re-grepped on `develop`; the plan's site lists were treated as hypotheses. Live HA config read from the Samba mount (`automations.yaml`, `.storage/lovelace.ura_v8`) and the PWA repo.

**Verdict: FIX-PLAN.** The core design (D1 one local + one kwarg, D2 one predicate, D3 attributes) is sound and its REUSE claims hold. The plan needs edits before build: two invariants are false as written, D2 widens five consumers the plan does not list (two of them trust consumers, one in HVAC), the D3 counter and branch label have unplaced or non-existent producers, and the D1 live criterion cannot tell D1 failing from path α firing.

---

## 1. Must-fix findings

| # | Sev | Finding | Evidence | Fix in plan |
|---|---|---|---|---|
| F1 | MEDIUM | **D2 widens consumers the plan does not list.** `_tracking_active` feeds `trustworthy_persons`, so `tracked_count`, `all_tracked_persons_away` and `_excluded_persons` all change for a STALE resident. Unlisted readers: (a) **NM severity input** `perimeter_alert._get_persons_home` reads `_tracked_persons_count_trusted` as `persons_home` (`perimeter_alert.py:1700-1704`) and feeds the severity table (`perimeter_alert.py:1660-1665` → `const.py:2338+`); (b) **HVAC "Wait for Presence" defer gate**: `_signal_consensus` loses its −0.4 term when `all_tracked_persons_away` flips (`presence.py:7270-7272`), read by `hvac.py:2717`; (c) `_arriving_rearm_bypass(tracked_count, all_tracked_persons_away)` (`presence.py:5646-5669`, callers `:6915`, `:6982`); (d) the zone-level `room_level_weighted` veto context (`presence.py:6235-6236`); (e) the D5 episode labels `alpha_starved` / `alpha_denies` (`presence.py:6538-6553`) and `PresenceDiagnosticSensor.excluded_persons` (`sensor.py:6295`). All move toward "home" for ≤ N s, so none looks harmful, but the plan's §3.2 consumer list and §4 table must name each with its intended effect, and the builder's wire-in grep must include `_tracked_persons_count_trusted` and `_signal_consensus`. | greps listed | Add rows (a)–(e) to §3.2/§4 with "intended: yes/no". |
| F2 | MEDIUM | **INV-SLEEP-NOT-EMPTY is false as written.** A zone holding a manual AWAY override reads `mode == AWAY`, D1's limb only rescues `mode == SLEEP`, and `set_sleep` skips overridden zones (`presence.py:933`). A house AWAY override pushes AWAY onto every zone (`presence.py:8019-8022`) and selecting `auto` clears only SLEEP zone overrides (`:8009-8013`). The AWAY override clears only on a room **rising** edge, camera or BLE (`:864-869`, `:908-914`, `:922-928`). **Repro (legal):** operator sets house AWAY, then `auto`, while a sleeper's radar is already on (no new rising edge; Wigton has no camera or BLE fallback). House goes SLEEP, census 0 → nobody-home returns AWAY with `raw_occupied = True`. §3.1 says manual AWAY overrides stay "not occupied" on purpose. The invariant must carry that carve-out, or D1 must also read raw for zones under an AWAY override. That is a decision for the operator or planner; a reviewer should not pick it. | code cited | Restate the invariant with the carve-out, or widen D1, and add a test for whichever is chosen. |
| F3 | MEDIUM | **INV-BYTE-ID-OUTSIDE-SLEEP is false as written.** The zone select offers `sleep` (`const.py:3168`, `select.py:363`). A zone the operator pins to `sleep` while the house is HOME_* now reads raw in nobody-home. §3.1 calls that intended ("manual SLEEP override, which we also treat as raw"), but the invariant says "house state ≠ SLEEP → identical". | `const.py:3168` | Change the invariant to "no zone in SLEEP mode". |
| F4 | MEDIUM | **The D1 live criterion and scorecard row 1 don't discriminate.** Path α has no sleep exemption and ignores zones (`presence.py:1170-1181`). With residents' trackers away and an untracked sleeper (a guest), α returns SLEEP→AWAY with a room occupied. That is the same observation the plan reads as "D1 broken". | `presence.py:1170-1181` | Filter both on the D7 episode's `veto_path = 'nobody_home'`, which the plan itself adds. |
| F5 | MEDIUM | **The D3 counter is not placed relative to the dispatch gates.** `_dispatch_house_state_change` returns early under boot-settle (`presence.py:7880-7889`) and observation mode (`:7890-7896`), before the DB write (`:7953-7962`). An increment "in `_dispatch_house_state_change`" placed above those returns breaks INV-COUNTER-MATCHES-LOG. The "agree by construction" claim holds only if the increment sits next to the `log_house_state_change` scheduling. That write is a fire-and-forget task that only logs on failure, so the invariant also needs a "within one write-queue flush" clause. | code cited | Pin the increment to the line after the gates, adjacent to the DB task. |
| F6 | MEDIUM | **The D3 `last_away_branch` source map is wrong.** No dispatch source `restore` exists: boot restore bypasses `transition()`, and the boot-settle path says "no dispatch" when the restore is confirmed (`presence.py:2412-2416`). So no `restore` producer exists and no log row is written, which is fine for the counter. The source that does exist, `boot_settle_override` (`presence.py:2440-2446`), is unmapped. `_veto_path` is also stale for both override sources, since it was mirrored at `:6518` on the last inference tick. | code cited | Map `inference` / `override_adapter` / `boot_settle_override`. Drop `restore`, or say where it would be produced. |

## 2. Lower findings (fix in plan, not blocking alone)

| # | Sev | Finding |
|---|---|---|
| L1 | LOW | **Concept split, Bug Class #63.** After D2, α/β treat STALE as home, while `fan_veto._ble_present_in_room` (`fan_veto.py:326-327`) and the census guest cancel `_ble_home_by_area` (`camera_census.py:3080-3085`) still treat STALE as not present, both on purpose: a frozen tracker must not defeat the fan veto or cancel a real guest. Record the split in §3.2 and in the state-of-play gold patterns so nobody "aligns" them later. |
| L2 | LOW | **§9 generic-minimal row overstates S0.** With 1–2 GPS `person.*` phones home, `person_coordinator` stamps location `home` and `_get_ble_persons` (`camera_census.py:2671-2688`) counts it, so census ≥ 1 (the Wigton audit's own S1 basis, `AUDIT_wigton_away_replay_2026_10_18.md:61`). The generic shape lives in S0 at night only with phoneless or untracked occupants. D1 still helps; the stated reason is wrong. |
| L3 | LOW | **DAO kwarg under-specified.** The `previous_state` filter has no parameter in the proposed signature, and `since_iso` versus `since_utc` is ambiguous. The column is a naive `datetime.utcnow().isoformat()` (`database.py:2967`), so the bound must be naive too (`.replace(tzinfo=None).isoformat()`). A `+00:00` suffix sorts after a zero-microsecond row stamped exactly at the boundary and drops it. |
| L4 | LOW | **D1 sets `veto_path = nobody_home` on every already-AWAY tick.** The v8 "Why this state" hero turns red while the house sits AWAY (predicate `a.veto_path!=='none'`). That is display only. Keep the already-AWAY label, but note the dashboard follow-up. |
| L5 | LOW | **Moving the periodic registration.** It must stay appended to `_unsub_listeners` and must not double-register on re-setup (Bug Class #50). Add this to the D1 test list. |
| L6 | LOW | **REUSE P13 cite is wrong.** `binary_sensor.py:271` is an attribute-churn comment, and there is no `_unrecorded_attributes` in `binary_sensor.py` (grep). The `sensor.py:6658` precedent is enough. |
| L7 | LOW | **Wigton D2-inert cite.** STALE needs `old_last_bermuda_update`, which is set only in the area-sensor-valid branch (`person_coordinator.py:470-519`). STALE is then assigned when the area state is unknown/unavailable (`:607-616`). The claim holds; cite `:470` and `:610`, not `:607` alone. |

## 3. Re-enumerations

### 3.1 `any_zone_occupied` consumers (D1 must widen only nobody-home)
Producer `presence.py:5975-5978`. Readers: `infer()` nobody-home `:1127`, β `indoor_blocked` fallback `:1218` (caller always passes `any_indoor_zone_occupied`, so it is dead in practice), `has_people` `:1291`, the veto INFO-log gate `:6611-6650`, signal consensus `:7270`/`:7284`. `camera_census._any_zone_occupied_snapshot` (`camera_census.py:2091`, `:2371`) is a separate producer. **PASS:** D1 routes a new kwarg to `:1127` only. After D1, SLEEP + census 0 + raw occupied falls past β (sleep-exempt) to `has_people = False` → `return None`, so SLEEP is held as intended.

### 3.2 `_tracking_active` / STALE consumers
`_tracking_active` has one call site, `presence.py:5913`. It feeds `person_tracking_active_signals` (`:5915` → `should_veto_due_to_reliable_signals` `:6844`, whose `_last_veto_decision` output is display only: `sensor.py:5683`, `:6217`, `:6232`) and `trustworthy_persons` → F1 list. Other STALE readers that D2 does NOT touch: `fan_veto.py:326`, `camera_census.py:3081`, `aggregation.py:5919-5959` (its own per-zone status), and dashboard `tracking_status` rows. `phone_left_behind` precedence holds: `phone_ok and track_ok` (`:5916`) still excludes on `phone_ok = False`, and `PersonPhoneLeftBehindSensor.is_on` keys on location, not status (`binary_sensor.py` ~2133-2150), so STALE does not change it. **PASS with F1.**

### 3.3 `raw_occupied` / `any_zone_raw_occupied` producers and liveness in a Wigton shape
`raw_occupied` = `_derived_mode == OCCUPIED` (`presence.py:748-754`). `_derived_mode` = BLE tier 3 OR (has_sensors AND (tier-1 room provenance OR camera within timeout)) (`:757-785`). Tier 1 is fed by the occupancy substrate per kind (`_on_substrate_kind_changed` `:3485-3507`, seeded `:3440-3473`) and registers `CONF_MOTION_SENSORS`, `CONF_MMWAVE_SENSORS` and `CONF_OCCUPANCY_SENSORS` (`:3443-3447`). Nothing gates on house or zone SLEEP, so it is live during SLEEP. The fan-interference hold extends `_room_occupied` (`:4113+`). Wigton files all 17 ZX under `occupancy_sensors` (replay audit :35), and that list is registered, so **raw is live at Wigton**. Rooms in no zone (Gym) do not count, as the plan states. **PASS.** Note: outdoor zones are included, the same as the daytime `any_zone_occupied`. An exterior camera hit at night now also holds SLEEP; that matches daytime behaviour, but §9 should say it.

### 3.4 `house_state_log` writers and counter restore
Sole INSERT: `database.py:2964`, called only from `_dispatch_house_state_change` (`presence.py:7957`). Sources: `inference` (`:7057`), `override_adapter` (`manager.py:758`), `boot_settle_override` (`presence.py:2440`). Readers: routine forecaster (`const.py:4659-4684`), `memory_facade.py:676`, and `scripts/probes/empty_house_experiment_probe.py`. Restore: hydration at setup `presence.py:2573-2591` with a local-date string against naive UTC (the bug the plan names), plus the reset in `_count_transition` `:7451-7466`. **PASS with F5 and F6.**

### 3.5 Consumers of house AWAY
The plan's §4 rows were verified: wall-panel automations (`automations.yaml:8255`, `:8270`, `:8320`, `:8335-8355` on `sensor.ura_coordinator_manager_house_state`) and `const.py:2344` (CRITICAL for away/vacation/sleep/home_night). The table should add the `persons_home` input from F1(a). `return HouseState.AWAY` appears only at `:1131`, `:1181` and `:1288`. **PASS with F1.**

### 3.6 Attributes the plan changes vs dashboards and automations
No attribute is renamed or removed. Additions: `last_away_branch`, `last_away_at`, `away_entries_today`, `guest_reason`, `stale_counted_home`, `nobody_home_zone_input`. Value or meaning changes: `veto_path` gains `nobody_home`; `excluded_persons` stops listing STALE persons. Readers:
- v8 People "Presence Diagnostics" (`.storage/lovelace.ura_v8`) reads `previous_state`, `dwell_seconds`, `confidence`, `lost_away_grace_remaining_s`, `excluded_persons`, `veto_path`, `is_overridden`, `last_veto_decision`, `signal_consensus_inputs`, `signal_consensus_band`, `all_tracked_persons_away`, `tracked_persons_count(_trusted)`, `census_count`, `face_recognized_count`, `path_alpha_gate_source`, `boot_settle_done` and `wake_blocked_ticks`. None is removed. Unknown `veto_path` values fall through to the raw label, so `nobody_home` renders.
- v7 also reads `veto_path`.
- No automation reads these attributes.
- The PWA (`ura-dashboard-pwa/src/components/tabs/Presence.tsx`) reads the state only.

**PASS.** See L4, and §5 for a pre-existing dashboard mislabel.

## 4. Verification checklist

| Item | Result |
|---|---|
| REUSE table P1–P15 at file:line | PASS except P10 (missing `boot_settle_override`, F6) and P13 (L6). P2, P3, P5, P6, P7, P9, P11 verified line for line. |
| INV-EMPTY-REACHES-AWAY falsifiable | PASS. Dwell values match `house_state.py:129-139`; add AWAY 30 s for completeness. |
| INV-SLEEP-NOT-EMPTY | **LEAK as written** (F2). |
| INV-BLE-SEEN-NOT-AWAY | PASS. A STALE location is a resolved room or Bermuda's own area string (`person_coordinator.py:1080-1082`), never `away`/`""`. |
| INV-NO-BLE-HOLD | PASS (`person_coordinator.py:610-616`; `last_bermuda_update` carried, not refreshed). |
| INV-BYTE-ID-OUTSIDE-SLEEP | **LEAK as written** (F3); F1 consumers are permitted differences that must be listed. |
| INV-COUNTER-MATCHES-LOG | Holds only with F5 placement and L3's naive bound. |
| Three-house-shape table | This house: PASS. Wigton D1 helps and D2 is inert: PASS (L7 cite). Generic: claim overstated (L2). "D1 hurts nowhere": add the outdoor-zone note (§3.3). |
| Every number on the knob ladder | PASS. Two rung-1 kill constants; N reuses `CONF_PERSON_DECAY_TIMEOUT` (`const.py:163-164`, read `person_coordinator.py:126-129`); 60 s periodic and dwell table existing; no new inline literal. |

## 5. Doc contradiction found (code wins; state-of-play fixed in this commit)
`PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §2 said the sensor's veto-path verdict takes the values `alpha_starved / alpha_denies / beta_only / none`. In code, the sensor attribute `veto_path` (`sensor.py:5661`) mirrors the engine's `_veto_path`: `none` / `active` / `lost_admitted` / `lost_admitted_immediate` (`presence.py:1124`, `:1177-1180`, `:1270s`, mirrored `:6518`). The `alpha_*` / `beta_only` labels belong only to the D5 `away_transition_blocked` episode payload (`presence.py:6548-6561`). The v8 "Decided by" row maps the D5 vocabulary and so never matches a live value (a pre-existing display bug for the dashboard card). §2 is corrected and ledger item 16 added.

## 6. Summary

| Severity | Count | Items |
|---|---|---|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 6 | F1–F6 |
| LOW | 7 | L1–L7 |

Must-fix before build dispatch: F1–F6. Bug classes: #53 one-missed-consumer (F1, F6), #63 concept split (L1), untested/undischarged edge (F5), invariant not falsifiable as written (F2, F3), non-discriminating acceptance (F4).
