# PLANNING — House state: SLEEP-mask fix, 5-min resident BLE memory, AWAY observability

**Card:** HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1 (the simple cycle; replaces Rev 4 as the build target).
**Status:** **Rev 2**, 2026-10-18. This revision folds both Tier-3 plan reviews of Rev 1 (`0eeacbb9e`):
- R1 (completeness) `docs/reviews/plan-review/PLAN_REVIEW_sleep_mask_ble_memory_R1_completeness.md` (`cf136afd9`): 6 MEDIUM, 7 LOW.
- R2 (build prediction) `docs/reviews/plan-review/PLAN_REVIEW_sleep_mask_ble_memory_R2_build_prediction.md` (`eff23bd1a`): 1 HIGH, 7 MEDIUM, 7 LOW.

Every finding is dispositioned in §14. The biggest change is the R2 H1 night fan loop: D1 now drops a room from its night input when that room is radar-sole and its fan is on.
**Next step:** orchestrator decides on a re-verify; operator answers the PICK (§13); then build.
**Author:** ura-planner. **Tier:** 3 (§11).

**Operator constraints (2026-10-18):**
- "accuracy at the right amount of effort and simplicity."
- Residents matter more than guests; guests still count.
- Build on existing infrastructure; nothing frivolous.
- "Make sure what we do benefits Wigton and the general case" (§9, part of acceptance).

**Parked by the operator:** Rev 4's camera-recency guard (A) and guest-room veto (B). See §12. Rev 4's file carries the PARKED banner (committed in `0eeacbb9e`).

---

## 0. The plan in one paragraph

Three small changes to the existing house-state inference and the existing presence house-state sensor.
- **D1, SLEEP-mask fix.** When a zone tracker is in SLEEP mode, the nobody-home branch reads that zone's real (raw) occupancy instead of treating it as empty. Two exclusions apply. A room whose occupancy is radar-sole with its fan on is not counted, which breaks the fan loop (R2 H1). A zone under a manual AWAY override stays "empty" (PICK 1). Works with zero cameras and zero BLE.
- **D2, 5-min resident BLE memory.** A resident whom Bermuda placed in a room within the decay window (300 s, the existing STALE stamp) counts as home in the α/β denominator instead of being dropped. Inert without Bermuda.
- **D3, observability.** Three fields on `sensor.ura_presence_coordinator_presence_house_state`: which branch made the last AWAY, AWAY entries today (local midnight, restored across restarts), and `guest_reason`.

No new timer, entity, store, schema, signal or config-flow field. One rung-1 kill-switch constant per behavioural deliverable.

---

## 1. Institutional context verified (MANDATORY)

### 1.1 Docs read completely before writing (Rev 1 and Rev 2)
- `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, incl. the §10 ledger. No ledger claim is re-asserted. Relied on as corrected:
  - #6: the denominator is the α/β ladder.
  - #11: SLEEP pins the zone mode.
  - #12: α has no census or zone term.
  - #16 (added by R1): `veto_path` values are `none/active/lost_admitted/lost_admitted_immediate`; `alpha_*`/`beta_only` exist only in the D5 episode.
- `docs/architecture/SENSOR_FLEET_CLASSES.md`. This plan classifies no sensor; the D1 fan breaker reuses the capability classifier.
- `docs/planning/AUDIT_census_arc_and_away_holistic.md`, P0–P4.
- `AUDIT_wigton_away_replay_2026_10_18.md`.
- `AUDIT_presence_visibility_gaps_2026_10_18.md`.
- Rev 4 of `PLANNING_house_away_flap_untracked_occupant.md` and its two Rev 3 reviews.
- Both Rev 1 reviews (R1, R2), in full.
- The HVAC state-of-play doc was read by R1. This plan touches no HVAC code. Its one HVAC trust consumer (the Wait-for-Presence consensus, §3.2 row b) is listed.

### 1.2 Findings reused from prior work
| Finding | Source | Used in |
|---|---|---|
| R1 HIGH-1: SLEEP masks zone flags, so nobody-home fires with a sleeper home | Rev 3 R1 | D1 |
| Wigton S0: 216/251 false AWAYs are SLEEP→nobody-home loops | Wigton replay §3 | D1, §9 |
| R2 H2 (Rev 3): fan + veto loop; reuse radar-sole + fan-on as the breaker | Rev 3 R2 | D1 breaker (this rev) |
| R2 H3 (Rev 3): the 60 s periodic is registered inside the discovery `try:` | Rev 3 R2 | D1 discharge |
| P4 G1: STALE residents are dropped from the denominator; L(5) costs 0 measured departures | P4 §1, §4 | D2 |
| UTC/local counter bug | Rev 3 R1 MED-2, R2 M1 | D3 |
| Recorder attributes: recorded, 30 s poll, 7-day retention | Rev 3 R1/R2 | D3 |

### 1.3 Prior-art scan: REUSE / EXTEND / BUILD (re-grepped on `develop` @ `b5962bf46`)
| # | Piece | Verdict | Evidence (file:line) |
|---|---|---|---|
| P1 | Nobody-home branch | **EXTEND** (one input) | `presence.py:1127-1131` |
| P2 | Zone SLEEP mask | **REUSE (unchanged)** | `ZonePresenceTracker.mode` → `_override` first (`presence.py:652-656`). `set_sleep` (`:930-937`) skips zones with a manual override. Callers: SLEEP entry `:7026-7031`, boot restore `:2404`, house-override path `:8024-8025`. `"auto"` clears only SLEEP zone overrides (`:8008-8012`). |
| P3 | Raw zone occupancy | **REUSE, with a per-room filter** | `_derived_mode` (`presence.py:756-785`) = BLE tier `_ble_occupied` OR (has_sensors AND (`any(_room_occupied.values())` OR `_any_camera_occupied()`)). `raw_occupied` is at `:748-754`. It is live during SLEEP because tier-1 registration (`:3440-3507`) does not gate on SLEEP (R1 §3.3). |
| P3b | Fan-loop breaker primitives | **REUSE** | `PresenceCoordinator._room_radar_sole_capable(room)` (`presence.py:3907-3940`, fail-closed → False). Per-tracker `_fan_on_rooms` (`presence.py:580`, written by `_discover_room_fans` listener `:3600+`; last-known-good belief, gold pattern). |
| P4 | Zone flags fed to `infer()` | **EXTEND** (one new local) | `any_zone_occupied` `:5975-5978`; `infer()` call `:6487-6516` |
| P5 | STALE stamp | **REUSE** | `old_last_bermuda_update` is set only in the area-valid branch (`person_coordinator.py:470-519`). STALE is assigned when the area is unresolved and `time_since_update < decay_timeout` (`:610-616`). `last_bermuda_update` is carried, not refreshed (`:615`, `:625`). |
| P6 | Decay window N | **REUSE** `CONF_PERSON_DECAY_TIMEOUT`, default 300 | `const.py:163-164`. Read at `person_coordinator.py:126-129` from integration `entry.data`; no flow field. |
| P6b | Person-coordinator interval | existing `UPDATE_INTERVAL = 30` | `const.py:40` |
| P7 | Trust denominator | **EXTEND** `_tracking_active` | Def `presence.py:5862-5873`. Single call site `:5913`, applied `:5916`. Result `all_tracked_persons_away` `:5939-5945`. |
| P8 | Forgotten-phone exclusion | **REUSE (precedence kept)** | `_phone_trustworthy` `:5833-5860`; `phone_ok and track_ok` `:5916` |
| P9 | Branch label | **EXTEND** | `_veto_path` reset `:1124`, set `:1177/1180/1274/1277`, mirrored `:6518`, D7 episode `:7926`, sensor `sensor.py:5661` |
| P10 | Sole `house_state_log` writer | **EXTEND** | `_dispatch_house_state_change` `presence.py:7861`. Gates: boot-settle early return `:7879-7889`, observation mode `:7890-7896`. DB task `:7953-7962`. Sources: `inference` (`:7057`), `override_adapter` (`manager.py:758`), `boot_settle_override` (`presence.py:2440-2446`). Boot `apply_restored` (`manager.py:697`) does **not** dispatch (`presence.py:2412-2416`). |
| P11 | Counter + hydration | **EXTEND** | `_count_transition` `:7451-7466`; hydration `:2573-2591`; DAO `count_house_state_changes_since` `database.py:3031-3058`; the column is naive `datetime.utcnow().isoformat()` (`database.py:2967-2968`). |
| P12 | Guest gates | **REUSE (read only)** | Path B `_guest_room_gate_armed` `:5485-5535`; Path A `_guest_gate_armed` `:5537+` |
| P13 | House-state sensor | **EXTEND (attributes only)** | `PresenceHouseStateSensor` `sensor.py:5557`; `_unrecorded_attributes` precedent `sensor.py:6658` (R1 L6: the Rev 1 cite `binary_sensor.py:271` was wrong) |
| P14 | Kill switches | **BUILD: two rung-1 constants** | grep `STALE_COUNTS\|stale_counts_home\|SLEEP_MASK\|READS_RAW` → 0 hits |
| P15 | Names | `last_away_reason` exists on HVAC zones (`hvac.py:653-658`, `:4023`), so this plan uses `last_away_branch`. `guest_reason`, `away_entries_today`: 0 hits. |

**New functionality, flagged:** one local plus one small helper (D1), one changed predicate (D2), attributes plus one optional DAO kwarg (D3), and two module constants.

### 1.4 Memory bodies relevant
`feedback_suppression_needs_discharge`, `feedback_no_restart_during_sleep`, `project_presence_guest_latch_and_veto_gap`, `project_guest_mode_false_positive_backlog`, `feedback_marginal_benefit_pushback`, `feedback_extend_existing_never_rebuild`, `feedback_coincidental_equality_masks_concept_split` (D2 STALE split), `feedback_wire_in_anchor_mandatory` (R2 M6).

### 1.5 Config-first check
- **D1:** no knob fixes it. **Code needed.**
- **D2:** `CONF_PERSON_DECAY_TIMEOUT` sets how long STALE lasts, but not that STALE is excluded. **Code needed.**
- **D3:**
  - Branch, count and guest reason do not exist as data. **Code needed.**
  - The v8 dashboard fixes (incl. the pre-existing "Decided by" mislabel, R1 §5) are config. The coordinator is fixing them separately.

---

## 2. Falsifiable invariants (restated in zone-mode terms; R1 F2/F3, R2 M2)

**Definitions:**
- `sleep_zone(z)` ⇔ `z.mode == SLEEP`. That happens via `set_sleep`, via a house SLEEP override push, or via a manual zone SLEEP override.
- `away_pinned(z)` ⇔ `z._override == AWAY`.
- `fan_phantom(r)` ⇔ `_room_radar_sole_capable(r)` AND `r ∈ z._fan_on_rooms`.
- `night_raw(z)` = `z._ble_occupied` OR (`z._has_sensors` AND (any room r with `_room_occupied[r]` AND NOT `fan_phantom(r)`, OR `z._any_camera_occupied()`)).
- N = live `decay_timeout`. I = `UPDATE_INTERVAL` = 30 s. T = presence tick ≤ 60 s.

> **INV-SLEEP-NOT-EMPTY:** the nobody-home branch (and, after the review fix-up, path β's indoor guard) never returns AWAY while some zone has `sleep_zone(z) AND night_raw(z)`. **Carve-out (PICK 1 default):** a zone with `away_pinned(z)` counts as empty, as today.
> **Scope limits, named by review D (not guaranteed by this cycle):**
> - **S-1, path α (ledger #12):** suppose three trackers are ACTIVE-away and the sleeper's phone is dead (LOST, so it drops out of the denominator), with cameras healthy and no interior view of the sleeper. Then α returns AWAY over a raw-occupied pinned zone. That is Rev 4 guard A, which is parked.
> - **S-2, PICK 1:** a mistaken house AWAY override followed by `auto` leaves zones AWAY-pinned when the sleeper's radar makes no new edge. Those zones count as empty.

> **INV-EMPTY-REACHES-AWAY (precondition stated openly, R2 H1):** suppose that from t0:
> - the house is physically empty and census is 0;
> - every tracked person is `not_home`-ACTIVE, or has had no Bermuda room fix since t0;
> - every zone's `night_raw` (if `sleep_zone`) or `mode` (otherwise) is clear by t0 + T_zone.
>
> Then AWAY is proposed by t0 + max(T_zone, N + I) + T and accepted within the current state's dwell (`house_state.py:129-139`: AWAY 30, SLEEP 600, GUEST 300, HOME_* 120, WAKING/ARRIVING 60 s).
> - A room held by a fan-on radar phantom no longer violates the premise, because `fan_phantom` drops it.
> - A phantom with **no URA-known fan** (or a non-radar phantom) still violates the premise. This is the same exposure as daytime and is named in §9.

> **INV-BLE-SEEN-NOT-AWAY:** a resident whose last Bermuda room fix is younger than N is never counted as away by α or β, unless `phone_left_behind` is `on` for them.

> **INV-NO-BLE-HOLD (R2 M1):** D2 never extends a hold beyond **last Bermuda room fix + N + I + T (300 + 30 + 60 s)** for that person.
> - The forgotten **visible** phone (ACTIVE, not STALE) is a pre-existing hold that D2 does not touch (§12).

> **INV-BYTE-ID:** with no zone tracker in `mode == SLEEP` and no STALE person, every `infer()` return, transition and `house_state_log` row is identical to today. This is keyed on tracker mode, not house state: SLEEP-pinned zones under a later HOME override do get the raw limb, deliberately (R2 M2).
> - With both kill constants False, everything is identical in all states.
> - Permitted differences: new attributes. `_veto_path = nobody_home` appears only on the **firing** return (R2 M3), and it is persisted in the D7 payload. The listed D2 consumer shifts in §3.2 are also permitted.

> **INV-COUNTER-MATCHES-LOG:** within one write-queue flush, `away_entries_today` = `COUNT(*) FROM house_state_log WHERE state='away' AND (previous_state IS NULL OR previous_state <> 'away') AND timestamp >= B`. Here `B = dt_util.as_utc(dt_util.start_of_local_day()).replace(tzinfo=None).isoformat()`. This holds after a restart and before the first transition of the day.

---

## 3. Producer and consumer checks

### 3.1 D1: nobody-home's zone input
**Producer today.** `any_zone_occupied = any(t.mode == OCCUPIED)` (`:5975`). In SLEEP every non-overridden tracker reads SLEEP.

**New local** (in `_run_inference`, next to `any_zone_raw_occupied` `:5996`):
```
any_zone_occupied_for_empty = any(
    t.mode == OCCUPIED
    or (t.mode == SLEEP and self._zone_night_raw(t))
    for t in self._zone_trackers.values()
)
```
- `_zone_night_raw(t)` is the `night_raw` formula of §2.
- The helper is on `PresenceCoordinator`, because it needs `_room_radar_sole_capable`.
- Each room is wrapped in try/except. On error the room counts as occupied (fail toward holding SLEEP; the discharge is the next tick).
- Manual AWAY-pinned zones read `mode == AWAY`, so they stay empty (PICK 1).

**Why the breaker sits here.**
- The comfort-fan veto acts only in AWAY/VACATION (`fan_veto.py:60`, `:167`).
- In SLEEP the fan runs, and fan recheck refuses bedrooms in sleep (`FAN_TRUST_STATES`).
- So a fan-faked radar would hold SLEEP forever, and the WAKING gate would then promote it to the day (R2 H1).
- Dropping fan-on radar-sole rooms from the night input is the same breaker Rev 4 adopted for its veto (Rev 3 R2 H2, option iii).
- Cost: a real still sleeper whose room has only radars and a running fan does not hold the house. If the trackers are also away, nobody-home can fire. That is today's behaviour for that room, so it is no worse than today.

**Dependency health.**
- `_derived_mode` inputs are live during SLEEP.
- `_room_radar_sole_capable` is shipped (ledger #10).
- `_fan_on_rooms` holds last-known-good through unavailable flaps.
- Wigton has no URA fans, so the breaker is inert there (§9).

**Consumer.** Only nobody-home (`:1127`), via a new `infer()` kwarg `any_zone_occupied_for_empty: bool | None = None`. `None` falls back to `any_zone_occupied`.
- `has_people` (`:1291`), β, consensus (`:7270/:7284`) and the veto log gate (`:6611-6650`) keep the masked value (R1 §3.1).
- After D1, SLEEP + census 0 + night_raw falls past β (sleep-exempt) to `has_people=False` → `return None`, so SLEEP is held.

**Outdoor zones (R1 §3.3, R2 L3).** Outdoor zones are included, as in the daytime input. A porch camera hit holds SLEEP for its camera timeout. Bounded; stated in §9.

### 3.2 D2: trusted denominator, every reader (R1 F1, R2 M4)
`_tracking_active` has a single call site (`:5913`). It feeds `trustworthy_persons`, `person_tracking_active_signals`, `_tracked_persons_count_trusted`, `_all_tracked_persons_away` and `_excluded_persons`. For a STALE resident, each reader moves toward "home" for at most N + I + T.

| # | Reader | file:line | Kind | Effect for a STALE resident | Intended? |
|---|---|---|---|---|---|
| a | NM perimeter severity, `persons_home` | `perimeter_alert.py:1700-1705` reads `_tracked_persons_count_trusted`; table `:1660-1665` → `const.py:2338+` | trust (NM) | count +1, so a daytime exterior person is no longer "nobody home" → HIGH | **Yes.** A BLE-seen resident is home. |
| b | HVAC "Wait for Presence" consensus | `_signal_consensus` `presence.py:7270-7272` loses its −0.4 term when `all_tracked_persons_away` flips; read by `hvac.py:2717` | trust (HVAC defer) | consensus rises, so HVAC defers less on a resident who is home | **Yes.** Same direction as the house state. |
| c | Arriving re-arm bypass | `_arriving_rearm_bypass(tracked_count, all_tracked_persons_away)` `presence.py:5646-5669`; callers `:6915`, `:6982` | internal | bypass is MORE likely while a resident is STALE-home (`tracked_count > 0 and not all_tracked_persons_away` → True; corrected per review B-L5) | **Yes.** Safe direction: a real arrival is never delayed. |
| d | Zone `room_level_weighted` veto context | `presence.py:6235-6236` | internal | context sees the resident as home | **Yes** |
| e | D5 episode labels `alpha_starved`/`alpha_denies` | `presence.py:6538-6553` | display (memory) | fewer `alpha_starved` labels during dropouts | **Yes** (display) |
| f | `excluded_persons`: house-state sensor `sensor.py` and `PresenceDiagnosticSensor` `sensor.py:6295`; v8 Presence Diagnostics row | display | STALE persons stop appearing; they appear in `stale_counted_home` instead | **Yes** |
| g | `person_tracking_active_signals` → `should_veto_due_to_reliable_signals` | `:5915` → `:6844`; `_last_veto_decision` is display only (`sensor.py:5683/6217/6232`) | display | fed from the same boolean; lists stay aligned | **Yes** |
| h | α / β | `:1170`, `:1248` | trust | not AWAY while STALE | **Yes** (the point of D2) |
| i | Sensor attrs and the switch coercion | `sensor.py:5636/5642`; `switch.py:3873`; `presence.py:6481`, `:7911-7914` | display / coercion | follow the values | **Yes** |

**Builder wire-in grep:** `_tracking_active\|person_tracking_active_signals\|_tracked_persons_count_trusted\|_all_tracked_persons_away\|_excluded_persons\|_signal_consensus`. Each hit must be listed in the build PR with "unchanged / intended shift".

**Deliberate concept split (R1 L1; Bug Class #63).** These readers keep treating STALE as **not present**, on purpose:
- `fan_veto._ble_present_in_room` (`fan_veto.py:326-327`): a frozen tracker must not defeat the fan veto;
- the census guest cancel `_ble_home_by_area` (`camera_census.py:3080-3085`): a frozen tracker must not cancel a real guest;
- `aggregation.py:5919-5959`.

Recorded in the state-of-play gold patterns at build so nobody aligns them later.

**Nobody-home is unaffected.** Census already counts a STALE person, because their location is a room (`camera_census._get_ble_persons`, `camera_census.py:2671-2688`).

**Restart (R2 L4).** STALE is not restored. `old_data` is empty at boot (`person_coordinator.py:423`, `:610`), so a restart inside N drops the memory and fails toward pre-D2 behaviour. Intended; a test anchors it.

### 3.3 D3 values
| Value | Producer | Consumers |
|---|---|---|
| `last_away_branch`, `last_away_at` | `_dispatch_house_state_change`, **after** the boot-settle and observation-mode returns, next to the DB task. Mapping: `source="inference"` → the engine's `_veto_path` captured at this edge; `override_adapter` → `override`; `boot_settle_override` → `override` (R1 F6, R2 M5). There is no `restore` value: restore never dispatches and writes no row. | display only |
| `away_entries_today` | Same placement. Increment when `new_state == AWAY and old_state != AWAY`. Hydrated at setup with bound B. The getter returns 0 when the stored date ≠ local today (R2 L2), and the periodic also resets it. | display only |
| `guest_reason` | Each inference tick, precedence Path B then Path A (R2 L6): `guest_room:<room>`, then `unidentified_persistent`; `override` when the house override is GUEST; else `none` | display only |
| `stale_counted_home` | D2 trust loop | display only, **unrecorded** |
| `nobody_home_zone_input` | D1 local | display only, **unrecorded** |
| `veto_path = nobody_home` | `infer()` nobody-home **firing return only**; the already-AWAY return keeps `none` (R2 M3) | sensor attr, D7 payload; dashboards in §4 |

Recorded attributes: `last_away_branch`, `last_away_at`, `away_entries_today`, `guest_reason` (rare changes; the scorecard reads them).

---

## 4. Consumers of house AWAY and of changed attributes

Effects of D1 are at night only; effects of D2 are a delay of up to N + I + T after a BLE dropout. Rows were re-grepped (R1 §3.5).

| Consumer | file:line | Kind | D1 | D2 |
|---|---|---|---|---|
| HVAC presets | `hvac.py:1437`, `:5184`; away `:2968`/`:3024` | trust | fewer false SLEEP→AWAY; zone vacancy unchanged | ≤ N+I+T later |
| HVAC Wait-for-Presence consensus | `presence.py:7270-7272` → `hvac.py:2717` | trust | none (masked value kept) | row 3.2 b |
| Room leave-on lights sweep | `coordinator.py:935` | signal | fewer night sweeps | ≤ N+I+T |
| Per-room chains / AI rules on `house_state_away` | `coordinator.py:1739-1749`; `config_flow.py:3183`, `:14995` | signal | none configured live | ≤ N+I+T |
| HA automation `wallpanel_fleet_force_off_secure` | `automations.yaml:8335-8355` (`sensor.ura_coordinator_manager_house_state` away for 3 min) | HA actuation | no false night panel-off | ≤ N+I+T on real departures |
| `wallpanel_fleet_wake`, `_sleep_after_grace` | `automations.yaml:8255`, `:8270`, `:8320` | HA automation | fewer false wakes from the AWAY→ARRIVING loop | ≤ N+I+T |
| Exterior-person NM severity | **`const.py:2344`** (away/vacation/sleep/home_night → CRITICAL) via `perimeter_alert.py:1660-1665` | trust (NM) | none (SLEEP and AWAY both CRITICAL) | fewer false CRITICALs in the day |
| NM `persons_home` input | `perimeter_alert.py:1700-1705` | trust (NM) | — | 3.2 a |
| Perimeter vehicle night alert | `perimeter_alert.py:2769`, `const.py:2701` | poll | none | ≤ N+I+T |
| Security auto-follow | `security.py:759`, `:1087-1094` (off live) | signal | no false night auto-arm | — |
| Comfort-fan AWAY veto | `fan_veto.py:60`, `:167` | trust | sleeper's fan not vetoed; fan-phantom rooms do not hold (breaker) | ≤ N+I+T |
| HVAC pre-conditioning / optimizer / energy offset | `hvac_predict.py:446`, `optimization.py:3661`, `energy.py:8144-8236` | poll | fewer false AWAYs | ≤ N+I+T |
| ARRIVING + re-arm cooldown | `presence.py:1297`, `:6992-7008`; bypass `:5646-5669` | internal | removes the SLEEP→AWAY→ARRIVING loop | 3.2 c |
| Someone-home binary sensor | `binary_sensor.py:2315` | display | — | — |
| Bayesian / routine / music / arrester | `__init__.py:3313-3329`, `routine_forecaster.py:188`, `music_following.py:301`, `hvac_override.py:1010` | signal | negligible | negligible |
| `house_state_log` readers: routine forecaster, memory facade, probe | `const.py:4659-4684`, `memory_facade.py:676`, `scripts/probes/empty_house_experiment_probe.py` | analytics | fewer night AWAY rows | fewer dropout rows |
| **v8 house-state card** | `.storage/lovelace.ura_v8:10453,10458,10464` turns red and appends "veto: …" when `veto_path != 'none'` | display | with the firing-only label, red appears only on the AWAY-firing tick (≤ 60 s), as α does today. **No AWAY-long red.** | — |
| **v8 Presence Diagnostics "Decided by"** | `lovelace.ura_v8:10477` maps the D5 vocabulary (pre-existing mislabel, R1 §5) | display | being fixed separately by the coordinator; the fix must add `nobody_home` | — |
| v7 card | `lovelace.ura_v7:921,3698` prints `veto_path` raw | display | renders `nobody_home` | — |
| PWA Presence tab | `ura-dashboard-pwa/src/components/tabs/Presence.tsx` (state only) | display | — | — |
| EVSE, battery | none | — | — | — |

**Label coordination (R2 M3, R1 L4).** Rev 1 set `nobody_home` on the already-AWAY tick, which would have kept the v8 card red for the whole AWAY. Rev 2 sets it on the firing return only, so it shows for one tick, exactly like `active` today. The durable answer is `last_away_branch`, which no live dashboard reads yet. The dashboard fix adds `nobody_home` to the "Decided by" map; that is a dashboard step, not a build item.

**AWAY sites:** `return HouseState.AWAY` appears only at `:1131`, `:1181`, `:1288`. D1 changes the condition at `:1131`; D2 changes the inputs to `:1181`/`:1288`. Other writers are fenced: `transition` `:6961`, overrides (`select.py:278`, `__init__.py:6201`, `presence.py:8017`) and `apply_restored` (`manager.py:697`).

---

## 5. Measure before build (done)
- **D1:**
  - Wigton S0: 216/251; S1: 1/4.
  - Main house: 54 of 102 real AWAYs (10-13→10-18) were nobody-home (P4 §1). The SLEEP share is unmeasured; the scorecard measures it with the `veto_path='nobody_home'` filter.
  - The R2 H1 loop is a design property, not a rate. The breaker is included without a probe because it is fail-open and reuses shipped primitives.
- **D2:** P4 §4. L(5) catches 2–4 of 9 genuine resident misses, plausibly the 4 stale-Jaya entries of 10-17, and loses 0 of 10 departures.
- **D3:** visibility audit §3 Q4: 5/4/33/11/42/10 AWAY entries per CDT day 10-12..10-17.

---

## 6. Marginal-benefit decomposition
- **D1:** one local plus one helper over shipped primitives. It fixes a correctness bug in every house shape. The fan breaker adds one AND per room; the evidence for it is Rev 3's identical loop finding.
- **D2:** L(5) reuses the stamp. L(10+) needs a new stamp and costs departures, so it is parked.
- **D3:** attributes only. A separate counter entity is rejected (an attribute suffices).
- **Rev 4 A/B:** parked by the operator. A is inert without interior cameras; B needs guest-room flags and caps.

---

## 7. Deliverables

### D1: SLEEP-mask fix on the nobody-home branch
**Change.**
1. Add the helper `_zone_night_raw(tracker)` (§2 formula, per-room try/except, error → room counts occupied).
2. In `_run_inference` (next to `:5996`), compute `any_zone_occupied_for_empty` (§3.1) when `PRESENCE_NOBODY_HOME_READS_RAW_IN_SLEEP` is True; otherwise `None`.
3. Pass it at the `infer()` call (`:6487-6516`) as `any_zone_occupied_for_empty=`. **This call-site kwarg is the wire-in anchor** (R2 M6).
4. In `infer()` nobody-home: `occ = any_zone_occupied if any_zone_occupied_for_empty is None else any_zone_occupied_for_empty`; `if census_count == 0 and not occ:`. The already-AWAY `return None` stays first and **does not** set the label. The firing return sets `self._veto_path = "nobody_home"`.
5. Publish the attribute `nobody_home_zone_input` (unrecorded).
6. **Discharge isolation** (Rev 3 R2 H3; R1 L5; R2 L7):
   - Move `async_track_time_interval(self._periodic_inference, 60 s)` (`:2926-2930`) out of the discovery `try:`.
   - It stays in the once-per-setup path and stays appended to `_unsub_listeners`, so unload cancels it and a re-setup does not double-register (Bug Class #50).

**Kill switch.** `PRESENCE_NOBODY_HOME_READS_RAW_IN_SLEEP: Final = True` (`const.py`, rung 1). False restores today's behaviour.

**Acceptance criteria.**
- **Verify (fix vs bug):** zones pinned by `set_sleep(True)`, census 0, a real room-occupancy update on a non-radar-sole room. Expected: not AWAY, `_veto_path='none'`. Old code: AWAY via nobody-home.
- **Verify (discharge):** same setup with all rooms clear → AWAY on that tick, `_veto_path='nobody_home'`.
- **Verify (fan loop, R2 H1, Jaya repro):** SLEEP; Frigate dark (`camera_input_degraded=True`) so α is skipped; β sleep-exempt; census 0. Jaya Bedroom occupied by radar only (LD2410 + ZK), Jaya fan on. Expected: the room is dropped → AWAY via nobody-home. Without the breaker: SLEEP held.
- **Verify (fan off):** the same room with the fan off still holds SLEEP.
- **Verify (witness):** a room with a fan on but a motion witness on (not radar-sole) still holds.
- **Verify (zone-mode keying, R2 M2):** house SLEEP inferred, then a HOME_DAY override. Zones stay SLEEP-pinned and the raw limb applies.
- **Verify (PICK 1 default):** zone under a manual AWAY override with its radar on, house SLEEP, census 0 → AWAY (carve-out kept).
- **Tests.** All drive `PresenceCoordinator._run_inference` with real `ZonePresenceTracker`s, not `infer()` alone (R2 M6):
  - `test_nobody_home_blocked_in_sleep_when_zone_raw_occupied`. Mutations: delete the call-site kwarg → RED; drop the raw limb → RED.
  - `test_nobody_home_fires_in_sleep_when_all_raw_clear`
  - `test_sleep_fan_radar_phantom_does_not_hold_empty_house` (mutation: drop the `fan_phantom` exclusion → RED)
  - `test_sleep_radar_room_fan_off_still_holds`
  - `test_sleep_fan_on_with_motion_witness_still_holds`
  - `test_zone_sleep_pin_survives_home_override_raw_limb_applies`
  - `test_zone_away_override_carve_out` (or `..._widened` if PICK 1 = widen)
  - `test_nobody_home_non_sleep_byte_identical`
  - `test_already_away_tick_keeps_veto_path_none`
  - `test_kill_constant_false_restores_masked_behaviour`
  - `test_night_raw_helper_error_counts_room_occupied`
  - `test_periodic_registered_when_discovery_raises` (mutation: move it back into the try → RED)
  - `test_periodic_cancelled_on_unload_and_not_double_registered`
  - Wigton tests (§9.2)
- **Live:**
  - Over 7 days, the D7 `house_state_transition` episodes with `previous_state='sleep'`, `new_state='away'` **and `veto_path='nobody_home'`** are each checked against `occupancy_events`. Expected: 0 with an indoor non-AWAY-pinned room occupied, other than fan-phantom rooms (R1 F4: the filter separates D1 from α firing on an untracked sleeper).
  - The same query is run over the 7 days before deploy, at deploy, as the baseline.

### D2: 5-min resident BLE memory (STALE counts home)
**Change.**
- `_tracking_active` returns True for `status in (ACTIVE, STALE)` when `PRESENCE_STALE_RESIDENT_COUNTS_HOME` is True.
- `_phone_trustworthy` precedence is unchanged.
- STALE names go into `self._stale_counted_home` (unrecorded attribute).
- All §3.2 readers shift as listed.

**N and its knob.**
- N = `CONF_PERSON_DECAY_TIMEOUT` (300 s, existing key, no flow field). It is reused because STALE *is* that window.
- Raising N changes STALE for every person-coordinator consumer, so it stays review-only.
- Kill switch: `PRESENCE_STALE_RESIDENT_COUNTS_HOME: Final = True` (rung 1).
- N = 0 → STALE never assigned → D2 inert.

**Acceptance criteria.**
- **Verify (fix vs bug):** resident STALE in Study A, others away → α not AWAY, `stale_counted_home=[name]`. Old code: AWAY, with `excluded_persons={name: tracking_status=stale…}`.
- **Verify (bound):** last fix older than N → falls to `person.*`. If `not_home`, AWAY.
- **Tests:**
  - `test_stale_resident_blocks_alpha` (mutation: revert the predicate → RED)
  - `test_stale_resident_blocks_beta`
  - `test_stale_hold_ends_after_decay_timeout`
  - **`test_d2_preserves_phone_left_behind_precedence`**: STALE + `phone_left_behind=on` → excluded, reason `phone_left_behind=on` (R2 M1 anchor).
  - **`test_stale_flicker_hold_bounded_by_last_fix`**: alternate resolved/unresolved, stop resolving → AWAY proposed by last fix + N + I + T (R2 M1).
  - `test_reliable_signal_lists_aligned_with_stale`
  - `test_perimeter_persons_home_counts_stale` (row 3.2 a)
  - `test_signal_consensus_with_stale_resident` (row 3.2 b)
  - `test_stale_not_restored_across_restart` (R2 L4)
  - `test_kill_constant_false_excludes_stale`
  - Config extremes `decay_timeout ∈ {0, 60, 300, 900}`
  - `test_wigton_shape_no_bermuda_inert`
- **Live / scorecard (R2 L5):** in the D7 AWAY snapshots, the count of AWAYs where some person's `last_bermuda_update` was younger than N at the AWAY instant = **0**. This is the discriminator; the old "no stale in `excluded_persons`" check is true by construction. `stale_counted_home` is non-empty at least once in 7 days (wiring proven).

### D3: Observability on the existing house-state sensor
**Branch label and source map.** As §3.3: `inference` → `_veto_path`; `override_adapter` and `boot_settle_override` → `override`; no `restore`.

**Counter placement.**
- In `_dispatch_house_state_change`, **after** the boot-settle return (`:7879-7889`) and the observation-mode return (`:7890-7896`).
- Immediately adjacent to the `log_house_state_change` task (`:7953-7962`).
- A gated dispatch writes no row and is not counted (R1 F5, R2 M5).

**Day boundary.**
- Store `_away_count_date` (local ISO date).
- The getter returns 0 when it differs from `dt_util.now().date()` (R2 L2).
- The increment and the 60 s periodic reset it.

**Hydration (R1 L3, R2 L1).**
- DAO signature: `count_house_state_changes_since(since_iso, *, state: str | None = None, exclude_same_previous: bool = False)`.
- The new call passes `since_iso = dt_util.as_utc(dt_util.start_of_local_day()).replace(tzinfo=None).isoformat()` (naive, matching the column; `start_of_local_day` is DST-correct), `state='away'` and `exclude_same_previous=True` (adds `AND (previous_state IS NULL OR previous_state <> 'away')`).
- The existing `_transitions_today` call passes neither kwarg, so its SQL is byte-identical.

**guest_reason.** §3.3, precedence B then A.

**Attributes.**
- Recorded: `last_away_branch`, `last_away_at`, `away_entries_today`, `guest_reason`.
- `_unrecorded_attributes = frozenset({"stale_counted_home", "nobody_home_zone_input"})`.
- No v8 card in code.

**Acceptance criteria.**
- **Verify:** a nobody-home AWAY gives `last_away_branch=nobody_home`. Today it is indistinguishable from "no veto".
- **Verify:** `override_adapter` and `boot_settle_override` AWAYs give `override` and increment the counter.
- **Verify:** a boot-settle-gated or observation-mode dispatch increments nothing.
- **Verify:** at 00:00:05 local with no transition, the attribute reads 0.
- **Verify:** a 20:00 CDT restart hydrates only rows from local midnight. A row stamped exactly at B with zero microseconds is included.
- **Tests:**
  - `test_last_away_branch_nobody_home`
  - `test_last_away_branch_override_and_boot_settle_override`
  - `test_no_restore_branch_value_emitted`
  - `test_gated_dispatch_not_counted`
  - `test_away_entries_today_getter_zero_after_local_midnight`
  - `test_away_count_hydration_naive_utc_bound_includes_boundary_row`
  - `test_away_count_excludes_away_to_away_rows`
  - `test_count_since_default_sql_unchanged`
  - `test_guest_reason_room_precedes_unidentified`
  - `test_unrecorded_attributes_set`
  - `test_wigton_shape_observability_without_cameras_or_ble`
- **Live:**
  - `away_entries_today` matches the INV-COUNTER-MATCHES-LOG query at two reads, one after a restart.
  - `last_away_branch` is never empty after an AWAY.
  - The recorder `state_attributes` carry no `stale_counted_home` key.

---

## 8. Numbers and their knobs
| Number | Value | Rung | Why | Kill |
|---|---|---|---|---|
| D1 enable | True | 1 | correctness fix | False |
| D2 enable | True | 1 | trust-denominator change | False |
| N | 300 s | existing `CONF_PERSON_DECAY_TIMEOUT` | is the STALE window | 0 → D2 inert |
| I | 30 s | existing `UPDATE_INTERVAL` (`const.py:40`) | bounds INV-NO-BLE-HOLD | — |
| T (discharge tick) | 60 s | existing | reused | — |
| Dwell | AWAY 30 / SLEEP 600 / GUEST 300 / HOME_* 120 / WAKING, ARRIVING 60 s | existing `DEFAULT_HYSTERESIS` | bounds INV-EMPTY-REACHES-AWAY | — |

No new behavioural literal. The D1 breaker has no number (it is a boolean conjunction of shipped predicates).

---

## 9. Three house shapes (operator constraint; part of acceptance)

### 9.1 Evaluation (Rev 2 changes marked ▲)
| Deliverable | This house (cameras, Bermuda/IRK, 4 trackers) | Wigton (no interior cameras, no BLE room trackers, no doors, 1 enrolled phone, 17 ZX radars, no URA fans) | Generic minimal (room sensors, 1–2 GPS `person.*`, no cameras, no BLE) |
|---|---|---|---|
| **D1 SLEEP mask** | **Helps.** Night nobody-home AWAYs with a sleeper. ▲ The fan breaker drops LD2410/ZK-only rooms with the fan on (Jaya, Study A, Kitchen-class), so the night loop is closed. | **Helps, most.** S0: 216/251 loops. Needs only room sensors. ▲ The breaker is **inert** (no URA fans). A ZX phantom from an unconfigured fan would hold SLEEP: the daytime exposure (A3 in the replay), not a URA-driven loop, because URA cannot turn an unknown fan on or off. | **Helps** ▲ when an occupant is phoneless or untracked. With a GPS phone home, census ≥ 1 already (R1 L2), so the S0 night case is the untracked-occupant case, not every night. |
| **D2 BLE memory** | **Helps (small):** 2–4 of 9 resident misses, 0 departures lost. | **Inert, explicitly.** STALE needs `old_last_bermuda_update`, set only when a Bermuda area sensor resolves (`person_coordinator.py:470-519`, `:610`). Wigton has none. | **Inert** without Bermuda. |
| **D3 observability** | **Helps** (visibility audit Q1/Q4/Q5). | **Helps.** No camera or BLE input is needed. `guest_reason=none`. | **Helps.** |
| *Hurts?* | D2: departure ≤ N+I+T later if the phone drops BLE at the door (0/10 measured). D1: ▲ a porch camera hit holds SLEEP for its camera timeout (as by day). | ▲ D1: an unknown-fan ZX phantom holds SLEEP instead of flapping to AWAY. That is the safer error with residents asleep. | Same as Wigton for D1. |

**Rule check.** Only D2 depends on a capability Wigton lacks, and it degrades to inert by construction. D1's breaker depends on URA-known fans and degrades to inert without them. D1 and D3 need zero cameras and zero BLE.

### 9.2 Wigton-shape fixture (acceptance; R2 M7)
One fixture in `quality/tests/`, built from production classes (`PresenceCoordinator`, real `ZonePresenceTracker`s):
- one tracked person `omonele`;
- **S0: omonele's tracker pinned `unknown` → LOST**, so α is starved (`tracked_count == 0`) and β is sleep-exempt. Census 0.
- **S1:** `person.omonele` `home`, location `home` → census 1.
- No Bermuda sensor, no camera input, no URA fans.
- Zones: Back hallway, Entertainment Zone, Master Suite, Upstairs Zone, plus Gym in no zone.

Each test asserts the state **and** `_veto_path`:
- `test_wigton_shape_sleep_loop_suppressed`: S0, SLEEP, Master Suite ZX occupied → no AWAY over 30 ticks, `_veto_path='none'`. Old code: AWAY, `nobody_home`.
- `test_wigton_shape_empty_still_reaches_away`: S0, all clear → AWAY, `nobody_home`.
- `test_wigton_shape_lost_fan_loop_breaker_when_fan_configured` (R2 H1 Wigton repro): S0, a ZX-only room, a URA fan added and on → AWAY. Proves the breaker holds in the LOST shape too.
- `test_wigton_shape_no_bermuda_inert`: D2 on/off give identical results.
- `test_wigton_shape_observability_without_cameras_or_ble`.

**Deployment note:** URA is disabled at Wigton. Confirm S0 vs S1 before enabling it.

---

## 10. Post-ship scorecard (D0, day 7, read-only; cycle exit)
- Script: `scripts/probes/house_state_simple_scorecard/`.
- Baseline: the same queries over the 7 days before deploy.
- Rows are filtered on the D7 episode `veto_path` (R1 F4).

| Observation | Fix working | D1 broken | D1 over-holding | D2 broken | D2 over-holding |
|---|---|---|---|---|---|
| SLEEP→AWAY with `veto_path='nobody_home'` and an indoor, non-AWAY-pinned, non-fan-phantom room occupied | 0 | > 0 | — | — | — |
| SLEEP→AWAY `nobody_home` total vs baseline | lower | ≈ baseline | — | — | — |
| Empty-night check: verified-empty absences (P3 control method) overlapping SLEEP hours reaching AWAY within max(T_zone) + 60 s + 600 s | all | — | any missed | — | — |
| AWAYs with a person's `last_bermuda_update` younger than N | 0 | — | — | > 0 | — |
| Max (AWAY time − last Bermuda fix) for a person D2 held | ≤ N+I+T | — | — | — | > N+I+T |
| Genuine departures reaching AWAY within 15 min | ≥ baseline − 1 | — | < baseline − 1 | — | < baseline − 1 |
| `away_entries_today` vs the INV query (3 reads) | equal | — | — | — | — |
| Resident someone-home AWAY/day, ordinary days (P4 classifier) | ≤ 0.27, target ≈ 0.15–0.25 | — | — | — | — |

**Exit:** the table is written into the README. Any failing row reopens the card.

---

## 11. Tier
**Tier 3.** Required:
- the orchestrator's re-verify decision on Rev 2;
- `ura-super-builder`;
- four build reviews:
  - A, local correctness;
  - B, state machine and lifecycle: SLEEP entry/exit, override pins, boot restore `:2404`, periodic move and teardown, hydration across a restart, the midnight getter;
  - C, per-site mutation over the D1/D2/D3 anchors, incl. the call-site kwarg and the breaker;
  - D, adversarial completeness against §2. Config extremes: `decay_timeout` 0/900; sleep hours 0-0 and 20-10; zone manual SLEEP/AWAY overrides; HOME override after SLEEP; a room in no zone; all-outdoor zones; fan unavailable; kill constants False;
- the orchestrator re-greps `return HouseState.AWAY` and the §3.2 wire-in grep, and runs one mutation;
- an operator checkpoint before deploy;
- a restart only in an awake window.

## 12. Non-goals, parked, out-of-scope, cards
**Non-goals.** Rev 4's guard and veto. Any change to `has_people`, β, guest-gate behaviour, census, hysteresis, HVAC code, the schema, or dashboards in code.

**Pre-existing and out of scope: the forgotten-visible-phone hold (R2 M1).**
- A phone that Bermuda keeps resolving is ACTIVE and holds HOME today, without D2.
- Its only discharge is `PersonPhoneLeftBehindSensor.is_on` (`binary_sensor.py:2133-2194`). It requires all of:
  - outside 22:00–07:00 (`:2137-2139`);
  - BLE puts the person in a specific room;
  - that room is unoccupied (D9);
  - camera `total_persons == 0`;
  - no camera sighting for `PHONE_LEFT_BEHIND_HOURS` = 1 h.
- Limits: up to 1 h latency, never fires overnight, and it cannot be satisfied in the intended way without interior cameras (Wigton).
- D2 does not change this path. A flickering phone re-arms STALE, but the hold is sustained by its ACTIVE ticks, which hold today anyway, and D2's own extension stays ≤ N+I+T from the last fix (`test_stale_flicker_hold_bounded_by_last_fix`).

| Item | Status | Revival trigger |
| **ZONE-TRACKER-PER-SENSOR-WIPE-1** (review D-H1, pre-existing). `ZonePresenceTracker.update_room_occupancy(room, False, kind)` clears every kind for the room, and the substrate is last-writer per (room, kind), so a multi-sensor room's tracker view drops while a sensor is still on. The night input works around it by ORing in the live state of registered sensors (`_zone_night_rooms`). Daytime `any_zone_occupied` and everything downstream of WAKING still read the lossy view (anchored as a known gap in `test_wigton_shape_multi_sensor_master_ends_via_waking`). | Card (own cycle; it touches every zone consumer) | Any reviewed plan to make zone occupancy per-sensor |
| **B-L4** (review B): auto-follow precondition. D1b adds a census-0 SLEEP→WAKING path, and `security.py` maps `waking` to DISARMED. Before enabling `security_auto_follow`, check that an empty house held in SLEEP by a phantom is not disarmed at window end. | Card (inert today: auto-follow off) | Operator enables security auto-follow |
| **D-P1** (review D, pre-existing): the zone SLEEP pin survives a HOME_* override. The unpin is keyed on the effective `current_state == SLEEP`, so an override then an AWAY transition leaves zones pinned with the house AWAY and occupants home. | Card | Unpin on any transition whose underlying previous state was SLEEP, or whenever the new state is not SLEEP |
| **B-L3** (review B): trip-wire = one NM per episode, by design. An emit the NM path drops (NM missing at boot, kill switch, same-day latch) is not retried in that episode. | Documented, no change | — |
|---|---|---|
| Rev 4 guard A + veto B | **PARKED by operator 2026-10-18** | Guest accuracy becomes a priority (a long stay or a party) |
| L(N > 300 s) with a new last-seen stamp | PARKED | A Bermuda-history probe shows ≥ 3 resident misses/month with BLE last seen 5–15 min before AWAY and no departure cost |
| Forgotten-phone discharge at night / without cameras | Not carded | An observed overnight hold with a phone left behind |
| House-state sensor recorder churn (pre-existing) | Card HOUSE-STATE-SENSOR-ATTR-CHURN-1 (to mint) | — |
| v8 "Decided by" map + `nobody_home` | Coordinator fixing separately | — |

**Separate finding: PERSON-GPS-ANY-HOME-WINS-1 (to mint; do not fold).**
- `person_coordinator.py:207-229` overwrites `sources["gps"]` per GPS tracker, so the last tracker in the list wins.
- The iPad was removed from `person.oji_udezue` on 2026-10-18.
- "Any home wins" re-opens the forgotten-device hold, so "freshest `last_updated` wins" is likely safer. Needs its own decision.
- Also relevant to Wigton (6 trackers, 1 reporting).

## 13. Operator PICK
1. **Zone under a stale manual AWAY override while house is SLEEP (R1 F2).** Default **carve-out**: the zone counts as empty, as today, and INV-SLEEP-NOT-EMPTY names the exception. The alternative is **widen**: read `night_raw` for AWAY-pinned zones too.
   - **Why carve-out by default:**
     - A zone AWAY override is an explicit operator or house-AWAY-override statement.
     - It already self-clears on any room, camera or BLE rising edge (`presence.py:864-869`, `:908-914`, `:922-928`).
     - The repro needs a house AWAY override followed by `auto` with a sleeper's radar already on and no new edge all night. That is legal but rare, and no measured case exists.
     - Widening would make a zone AWAY override ineffective for house emptiness at night. That is a semantics change to the select, which this cycle should not make.
   - **Evidence that would flip it:** one observed night where `nobody_home` fired with an AWAY-pinned zone's raw occupancy on. The scorecard row 1 query, without the AWAY-pinned filter, reports this.

## 14. Review findings → resolution
| ID | Sev | Finding | Resolution | Where |
|---|---|---|---|---|
| R2 H1 | HIGH | D1 creates a fan→radar→never-AWAY loop in SLEEP (Jaya; Wigton LOST) | `fan_phantom` breaker in `night_raw` (REUSE `_room_radar_sole_capable` + `_fan_on_rooms`); invariant precondition stated; Jaya and Wigton-LOST tests | §2, §3.1, D1, §9 |
| R1 F2 | MED | INV-SLEEP-NOT-EMPTY false for a zone under a manual AWAY override | Restated in zone-mode terms with the carve-out; PICK 1 with evidence; test | §2, §13, D1 |
| R1 F3 / R2 M2 | MED | INV-BYTE-ID keyed on house state; zones can be SLEEP-pinned outside house SLEEP | Restated as "no zone tracker in SLEEP mode"; `test_zone_sleep_pin_survives_home_override_raw_limb_applies` | §2, D1 |
| R1 F1 / R2 M4 | MED | D2 readers unlisted (perimeter `persons_home`, HVAC consensus, re-arm bypass, zone veto context, episode labels, `excluded_persons`) | §3.2 reader table a–i with intended effect; wire-in grep; two reader tests | §3.2, §4, D2 |
| R1 F4 | MED | D1 live check cannot tell D1 from α | Filter on `veto_path='nobody_home'` | D1 Live, §10 |
| R1 F5 / R2 M5 | MED | Counter placement vs dispatch gates | After both early returns, adjacent to the DB task; gated-dispatch test | §3.3, D3 |
| R1 F6 / R2 M5 | MED | `restore` source does not exist; `boot_settle_override` unmapped | Map `boot_settle_override` → `override`; drop `restore`; test | §3.3, D3 |
| R2 M1 | MED | INV-NO-BLE-HOLD mis-scoped; forgotten-phone discharge | Restated as last fix + N + I + T; §12 out-of-scope paragraph; precedence and flicker tests | §2, §12, D2 |
| R2 M3 | MED | `nobody_home` on already-AWAY ticks turns v8 red for the whole AWAY | Label on the firing return only; dashboards listed; v8 map fix noted as the coordinator's | §3.3, §4, D1 |
| R2 M6 | MED | D1 tests on `infer()` alone leave the wire-in unanchored | Tests drive `_run_inference` with real trackers; call-site kwarg mutation | D1 |
| R2 M7 | MED | Wigton fixture incoherent about omonele | S0 pinned LOST; per-test branch assertion | §9.2 |
| R1 L1 | LOW | STALE concept split | Recorded as deliberate; gold-pattern note at build | §3.2 |
| R1 L2 | LOW | Generic shape S0 overstated | Corrected | §9.1 |
| R1 L3 / R2 L1 | LOW | DAO kwarg and naive bound | Signature with `exclude_same_previous`; `start_of_local_day` naive UTC | D3 |
| R1 L4 | LOW | Label red while AWAY | Same fix as R2 M3 | §4 |
| R1 L5 / R2 L7 | LOW | Periodic move teardown / double-register | Stays in `_unsub_listeners`, once per setup; test | D1 |
| R1 L6 | LOW | Wrong `binary_sensor.py:271` cite | Dropped; `sensor.py:6658` | P13 |
| R1 L7 | LOW | Wigton D2 cite | `person_coordinator.py:470-519`, `:610` | P5, §9 |
| R2 L2 | LOW | Midnight reset depends on tick phase | Date-checking getter | D3 |
| R2 L3 | LOW | Outdoor zones in the night input | Stated (bounded by camera timeout) | §3.1, §9 |
| R2 L4 | LOW | STALE not restored | Stated; test | §3.2, D2 |
| R2 L5 | LOW | D2 scorecard row true by construction | Replaced with the `last_bermuda_update < N` row | D2, §10 |
| R2 L6 | LOW | `guest_reason` precedence | Path B then A; test | §3.3, D3 |
| R1 §5 | — | State-of-play `veto_path` value set was wrong | Fixed by R1 (ledger #16); dashboard follow-up by the coordinator | §1.1, §4 |

Rejected: none. Adapted: R2 H1 offered "operator acceptance" as an alternative. The breaker was chosen instead, because it reuses shipped primitives and is fail-open.

## 15. Docs (same commit as the build)
- **PRESENCE state of play:**
  - §2: nobody-home reads `night_raw` for SLEEP-mode zones, with the fan breaker and the AWAY-pin carve-out; STALE counts home.
  - §10: ledger row "SLEEP stops nobody-home AWAY" was false before this cycle.
  - Gold patterns: "night_raw = raw zone occupancy minus fan-phantom rooms", and the STALE concept split.
- **README:** the §10 baseline and the day-7 table, written back.

---

## Rev 2.1 build delta (2026-10-18, decided by stress test P5)

Source: `docs/planning/AUDIT_census_arc_and_away_holistic.md` §P5 (commit `1c74b467b`). The build applies three changes to Rev 2:

1. **Fan-loop breaker DROPPED from D1 (parked, not built).** P5 measured that the breaker blanks real sleepers. Jaya's room is radar-sole with the fan on in 76 % of her occupied minutes (Master 30 %, Study A 69 %), and there were 0 genuine night departures in 220 days. `night_raw` is now the §2 formula without the `fan_phantom` term, and no constant was left behind.
   - **Revival trigger:** the D1 trip-wire (item 3) fires on a night that a prober proves was an empty house held in SLEEP by a fan-on radar-sole room.
2. **D1b, wake-time discharge (P5 item 4 gap).** With census 0 and zones pinned, `has_people` stayed False, so `infer()` returned None and never reached SLEEP→WAKING. The house could then sit in SLEEP all day.
   - **Change:** one disjunct in `infer()`. When `current_state == SLEEP`, the hour is no longer a sleep hour, and `any_zone_occupied_for_empty is True`, then `has_people = True`, so the existing WAKING branch runs; the 90 s raw WAKING gate still applies.
   - **Kill switch:** it is gated by the same D1 kill switch (the kwarg is None when off).
3. **Trip-wire, retargeted to the window end (coordinator, 2026-10-18).** It fires when SLEEP is still held only by raw occupancy with census 0 more than `SLEEP_RAW_HOLD_NM_BOUND_S = 5400` after the sleep window ENDS (07:30 with the 06:00 default). That case means the D1b wake discharge failed.
   - **Review fix-up:**
     - It never fires while the house state is overridden (A-M1 / B-L1 / D-M2: a 21:30 early-bedtime or 14:00 nap override is the operator's hold, not a failed discharge).
     - The clock is anchored at max(window end, SLEEP entry), using the tick's own `now` (A-L3).
     - The NM goes out at **HIGH** through a new optional `severity` kwarg on `fire_stuck_signal` (A-M2 / B-L2). It reuses the S10 latches' per-call severity pattern. Other callers stay MEDIUM.
   - An overnight raw-only hold inside the window is the normal state on a census-0 house such as Wigton, and it never fires. The first draft measured 90 min from the start of the hold and would have paged every night there.
   - It fires one `fire_stuck_signal(kind="sleep_raw_hold", key=("house",))` per hold episode, plus that path's per-day latch. Rung 1; `0` disables. The diagnosis names the holding rooms. There is no new notifier.

**New invariant: INV-SLEEP-HOLD-BOUNDED** (P5 wording, in the test header).
- Holds when census is 0, the house state is SLEEP, and `night_raw` is true only through sensor-occupied rooms. Then:
  - (a) nobody-home never returns AWAY while a pinned zone has an occupied room;
  - (b) the house is out of SLEEP by the first tick after the end of the sleep window plus the dwell.
- **Anchors:** `test_sleep_leaves_after_window_with_raw_occupancy` and `test_infer_wake_disjunct_engine_level`.
- **Drills:** `d1b_disjunct_removed`, `d1b_sleep_state_conjunct_dropped`, and the `tripwire_*` set (incl. `tripwire_window_gate_dropped` and `tripwire_clock_from_hold_not_window_end`). Wigton test: `test_wigton_shape_tripwire_full_night_silent_then_fires_past_window`.
- **Equivalent mutant (recorded):** dropping the sleep-hour conjunct of D1b changes nothing, because inside sleep hours a SLEEP house already returns None from the sleep-hours branch. The conjunct is kept as documentation.

Scope note: P5 also proposed a diagnostic attribute naming the holding room. The coordinator's directive was NM-only, so the room names go in the NM diagnosis and no attribute was added.


## Review fix-up (2026-10-18, four Tier-3 reviews A/B/C/D)

| Finding | Fix |
|---|---|
| D-H1 HIGH: multi-sensor room reads empty while a radar is on | `_zone_night_rooms` ORs the live `on` state of every Tier-1 sensor registered to the room (`tracker._entity_to_room`) into the room limb. The WAKING sustained gate is fed the same night signal, so INV-SLEEP-HOLD-BOUNDED (b) still holds. The tracker/substrate semantics are carded as ZONE-TRACKER-PER-SENSOR-WIPE-1. |
| D-M1 / B-M1: label read after an await | `tick_veto_path` is captured right after `infer()` and passed to `_dispatch_house_state_change(veto_path=)`. Both the counter's branch and the D7 payload use it. |
| A-M1 / B-L1 / D-M2: trip-wire false page under an override | `held` requires `not is_overridden`; the anchor is max(window end, SLEEP entry). |
| A-M2 / B-L2: MEDIUM reaches no channel | `fire_stuck_signal(severity="HIGH")`. |
| C M5b: window roll-back untested | Non-wrapping 01→07 test at 00:30. |
| D-M3: β reads the masked indoor input when the sleep exemption is off | The non-outdoor SLEEP-mode night signal is ORed into `any_indoor_zone_occupied` (β guard and FIX-2b debounce), only when a SLEEP-mode zone is night-occupied. |
| S-1 / S-2 | Named as scope limits under INV-SLEEP-NOT-EMPTY. |
| B-L5 | §3.2 row c wording corrected. |
| A-L1 | `guest_reason` value `unidentified_corroborator_only` (Path A arms nothing by itself since GUEST-CENSUS D2). |
| A-L2 | Stale "fan-phantom rooms dropped" docstring corrected. |
| A-L3 | The trip-wire uses the tick's `now`. |
| D-L1 | Unused `_sleep_raw_hold_since` removed. |
| D-L2 (DST) | Noted in the trip-wire docstring. |
| B-L3 / B-L4 / D-P1 | Carded or documented in §12. |
| B-L6, D-L3 | Accepted: an `<error>` room limb is covered by the trip-wire. INV-NO-BLE-HOLD is stated in URA's frame (last poll with a valid area). |
