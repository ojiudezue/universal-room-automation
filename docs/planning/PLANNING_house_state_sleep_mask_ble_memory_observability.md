# PLANNING — House state: SLEEP-mask fix, 5-min resident BLE memory, AWAY observability

**Card:** HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1 (the simple cycle; replaces Rev 4 as the build target).
**Status:** Rev 1, 2026-10-18. Plan only. Operator approved this "simple" Away cycle in place of Rev 4 on 2026-10-18.
**Author:** ura-planner. **Tier:** 3 (house-state shared primitive, §11).

**Operator constraints (2026-10-18):**
- "accuracy at the right amount of effort and simplicity."
- Residents matter more than guests, but guests still count.
- Build on existing infrastructure; nothing frivolous.
- "Make sure what we do benefits Wigton and the general case" (§9 is the per-shape evaluation and is part of acceptance).

**Parked by the operator:** Rev 4's camera-recency guard (A) and guest-room veto (B). See §12. Rev 4's plan file is marked PARKED in the same commit.

---

## 0. The plan in one paragraph

Three small changes to the existing house-state inference and the existing presence house-state sensor.
- **D1, SLEEP-mask fix.** The nobody-home branch stops reading a zone as empty just because house SLEEP put it in SLEEP mode. It reads the zone's real (raw) occupancy, which the WAKING gate already computes. Works with zero cameras and zero BLE.
- **D2, 5-min resident BLE memory.** A resident whom Bermuda placed in a room within the decay window (300 s, the existing STALE stamp) counts as home in the α/β denominator instead of being dropped from it. Inert in a house without Bermuda.
- **D3, observability.** On `sensor.ura_presence_coordinator_presence_house_state`: which branch made the last AWAY, AWAY entries today (local midnight, restored across restarts), and a `guest_reason`.

No new timer, entity, store, schema, signal or config-flow field. One rung-1 kill-switch constant per behavioural deliverable.

---

## 1. Institutional context verified (MANDATORY)

### 1.1 Docs read completely before writing
- `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (555 lines), incl. §10 ledger 1–12. Relied on as corrected: #6 (denominator is the α/β ladder), #11 (SLEEP pins the zone mode; display vs HVAC), #12 (α has no census/zone term). No ledger claim re-asserted.
- `docs/architecture/SENSOR_FLEET_CLASSES.md` (ZV motion-class; ZK/ZX hold a still person; classify by capability). This plan classifies no sensor.
- `docs/planning/AUDIT_census_arc_and_away_holistic.md` incl. probes P0, P1, P2, P3 and **P4 (BLE and resident-only goal)**.
- `docs/planning/AUDIT_wigton_away_replay_2026_10_18.md`.
- `docs/planning/AUDIT_presence_visibility_gaps_2026_10_18.md`.
- `docs/planning/PLANNING_house_away_flap_untracked_occupant.md` Rev 4, and both Rev 3 plan reviews: `docs/reviews/plan-review/PLAN_REVIEW_house_away_flap_R1_completeness_rev3.md`, `..._R2_build_prediction_rev3.md`.
- HVAC state-of-play was not re-read for this plan: no HVAC code is touched, and the HVAC consumer rows are carried from Rev 4 §3.4, which was written after a complete read.

### 1.2 Findings reused from prior work
| Finding | Source | Used in |
|---|---|---|
| **R1 HIGH-1:** house SLEEP masks the zone flags (`set_sleep` override), so nobody-home fires AWAY with a sleeper home | R1 rev3 review | D1 (the whole deliverable) |
| **Wigton S0:** 216 of 251 false AWAYs are SLEEP→nobody-home loops; S1: 1 of 4 | Wigton replay §3 | D1 motivation, §9 |
| **R2 H3:** the 60 s periodic (the only discharge when no events arrive) is registered inside the discovery `try:` | R2 rev3 review | §6 INV-DISCHARGE precondition (D1 note) |
| **P4 G1:** STALE residents are dropped from the denominator; 4 of 102 real AWAYs had `excluded_persons = {Jaya: tracking_status=stale}`; L(5) costs no measured departure | P4 §1, §4 | D2 |
| **UTC/local counter bug:** hydration compares a local date to naive-UTC rows; counter resets only on a transition | R1 MED-2, R2 M1 | D3 counter |
| **Recorder attributes:** the house-state sensor has no `_unrecorded_attributes`, polls 30 s, retention 7 d | R1 LOW-3 / open (b), R2 M2 | D3 attribute placement |
| Consumer list incl. wall-panel automations and `const.py:2344` | R1 MED-4, Rev 4 §3.4 | §4 |

### 1.3 Prior-art scan: REUSE / EXTEND / BUILD (re-grepped on `develop` @ `b5962bf46`)
| # | Piece | Verdict | Evidence (file:line) |
|---|---|---|---|
| P1 | Nobody-home branch | **EXTEND** (one input) | `presence.py:1127-1131` `if census_count == 0 and not any_zone_occupied` |
| P2 | Zone SLEEP mask | **REUSE (unchanged)** | `ZonePresenceTracker.mode` returns `_override` first `presence.py:652-656`; `set_sleep` `:930-937`; called on SLEEP entry `:7026-7031`, boot restore `:2404`, override path `:8025` |
| P3 | Raw zone occupancy that ignores the override | **REUSE** | `ZonePresenceTracker.raw_occupied` `presence.py:748-754` (`_derived_mode == OCCUPIED`); already aggregated as `any_zone_raw_occupied` for the WAKING gate `presence.py:5996-6006`. No new producer needed. |
| P4 | Zone flags fed to `infer()` | **EXTEND** (one new local) | `any_zone_occupied` `presence.py:5975-5978`; `any_indoor_zone_occupied` `:5987-5991`; `infer()` call `:6487-6516` |
| P5 | STALE stamp (BLE seen within decay window, unresolved this tick) | **REUSE** | `person_coordinator.py:607-642`: Bermuda sensor present, no room, `time_since_update < self.decay_timeout` → `tracking_status = STALE`, `location = old_location`, `last_bermuda_update` kept |
| P6 | Decay window N | **REUSE** `CONF_PERSON_DECAY_TIMEOUT` / `DEFAULT_PERSON_DECAY_TIMEOUT = 300` | `const.py:163-164`; read `person_coordinator.py:126-129` from integration `entry.data`; no config-flow field (grep: only `person_coordinator.py`, `aggregation.py:5902`). |
| P7 | Trust denominator | **EXTEND** (`_tracking_active`) | `presence.py:5862-5873` (ACTIVE only), applied `:5906-5916`, `all_tracked_persons_away` `:5939-5945` |
| P8 | Forgotten-phone exclusion | **REUSE (unchanged, precedence kept)** | `_phone_trustworthy` `presence.py:5833-5860` |
| P9 | Branch label | **EXTEND** | `_veto_path` reset `presence.py:1124`, set `:1177/1180/1274/1277`, mirrored `:6518`, read `sensor.py` (`veto_path` attr) and D7 episode `:7926` |
| P10 | Sole `house_state_log` writer / AWAY edge | **EXTEND** | `_dispatch_house_state_change` `presence.py:7861` (inference and override adapter) |
| P11 | Daily counter + hydration | **EXTEND** | `_count_transition` `presence.py:7451-7466` (resets only when called); hydration `:2573-2591`; DAO `count_house_state_changes_since` `database.py:3031-3058` (local date vs UTC, docstring admits it) |
| P12 | Guest gate internals | **REUSE (read only)** | Path A `_guest_gate_armed` `presence.py:5537+` (`_unidentified_first_seen` `:1716`); Path B `_guest_room_gate_armed` `:5485-5535` |
| P13 | House-state sensor | **EXTEND (attributes only)** | `PresenceHouseStateSensor` `sensor.py:5557`; precedent for `_unrecorded_attributes` `sensor.py:6658`, `binary_sensor.py:271` |
| P14 | Kill switches | **BUILD: two rung-1 module constants** | grep `STALE_COUNTS\|stale_counts_home\|SLEEP_MASK` → 0 hits |
| P15 | Name collision check | `last_away_reason` already exists as an HVAC zone attribute (`hvac.py:653-658`, `:4023`). This plan uses **`last_away_branch`** to avoid a second meaning of the same name. `guest_reason`, `away_entries_today`: 0 hits. |

**New functionality, flagged:** one local boolean (D1), one changed predicate (D2), a handful of sensor attributes plus one optional DAO kwarg (D3), two module constants. **Not added:** a timer, a persisted store, an entity, a config-flow field, a DB column, a signal, a camera dependency.

### 1.4 Memory bodies relevant
`feedback_suppression_needs_discharge`, `feedback_no_restart_during_sleep`, `project_presence_guest_latch_and_veto_gap`, `project_guest_mode_false_positive_backlog`, `feedback_marginal_benefit_pushback`, `feedback_extend_existing_never_rebuild`, `project_house_zones_vs_hvac_zones`, `feedback_config_first_before_code`.

### 1.5 Config-first check
- D1: no knob changes it. `sleep_start/end` only move the window; turning SLEEP off is not a fix. **Code needed.**
- D2: `CONF_PERSON_DECAY_TIMEOUT` sets how long STALE lasts but not that STALE is *excluded*. **Code needed** (one predicate).
- D3: the dashboard-only items of the visibility audit (§4a) are config and are not in this plan. Branch-of-last-AWAY, an AWAY count and a guest reason do not exist as data (visibility audit §3 Q1/Q4/Q5). **Code needed.**

---

## 2. Falsifiable invariants

Definitions: `raw_zone(z)` = `tracker.raw_occupied`; `sleep_masked(z)` = `tracker.mode == SLEEP`; N = live `decay_timeout` (s).

> **INV-EMPTY-REACHES-AWAY (bound):** if from t0 the house is physically empty, census_count is 0, every zone's raw occupancy is clear by t0 + T_zone (the existing room/zone timeouts), and every tracked person is either `not_home`-ACTIVE or has had no Bermuda room update since t0, then AWAY is proposed by **t0 + max(T_zone, N) + 60 s** and accepted within the current state's dwell (`DEFAULT_HYSTERESIS`, `house_state.py:129-139`: SLEEP 600, GUEST 300, HOME_* 120, WAKING/ARRIVING 60 s). D1 and D2 add no other hold. *Break attempts that must fail:* SLEEP with raw zones clear; a STALE stamp that never ages; periodic tick not registered.

> **INV-SLEEP-NOT-EMPTY:** in house SLEEP, the nobody-home branch never returns AWAY while any zone has `raw_occupied = True`. (Today's behaviour violates this: Wigton S0, R1 HIGH-1 repro.)

> **INV-BLE-SEEN-NOT-AWAY:** a resident whose last Bermuda room update is younger than N seconds (STALE, or ACTIVE in a room) is never counted as away by α or β. Hence α/β never return AWAY while such a resident exists, unless `phone_left_behind` is `on` for them (precedence unchanged).

> **INV-NO-BLE-HOLD (bounded):** D2's hold ends no later than N seconds after the last Bermuda room update for that person, whatever the phone does afterwards. A phone that stays *visible* is ACTIVE (not STALE) and is already governed by `phone_left_behind`; D2 does not touch that path.

> **INV-BYTE-ID-OUTSIDE-SLEEP:** with house state ≠ SLEEP and no STALE person, every `infer()` return, transition and `house_state_log` row is identical to today. With both kill constants False, identical in all states. Permitted differences: new attribute values and the new `_veto_path` value `nobody_home` (persisted in the D7 episode payload `:7926`; grep shows no value consumers beyond `sensor.py` and `presence.py:6518/7926`).

> **INV-COUNTER-MATCHES-LOG:** at any time, `away_entries_today` = `COUNT(*) FROM house_state_log WHERE state='away' AND (previous_state IS NULL OR previous_state <> 'away') AND timestamp >= utc(local midnight)`, including after a restart and before the first transition of the day.

---

## 3. Producer and consumer checks

### 3.1 D1 value: nobody-home's zone input
- **Producer today:** `any_zone_occupied = any(t.mode == OCCUPIED)` (`:5975`). `mode` is the override when set; on SLEEP entry every tracker without a manual override is set to SLEEP (`:930-937`, `:7026-7031`). So in SLEEP the term is False regardless of rooms.
- **Arithmetic of the fix:** new local `any_zone_occupied_for_empty = any(t.mode == OCCUPIED or (t.mode == SLEEP and t.raw_occupied))`. Outside SLEEP the second limb is never true (a tracker is in SLEEP mode only via `set_sleep`, or a manual SLEEP override, which we also treat as "look at raw"). Manual AWAY/OCCUPIED zone overrides are untouched (an operator AWAY override still reads as not occupied, as today).
- **Dependency health:** `_derived_mode` comes from the room sensors via the zone tracker (same input the WAKING gate has relied on since v4.7.18.1). On Wigton it is 17 ZX radars plus 3 ecobee PIR; here, the normal fleet. Phantom radars hold `raw_occupied` exactly as they hold `mode` in the daytime, so D1 brings night behaviour to parity with day, no worse.
- **Consumer:** only the nobody-home conjunct (`:1127`) receives the new value, via a new `infer()` kwarg `any_zone_occupied_for_empty: bool | None = None` (None → fall back to `any_zone_occupied`, so the engine default is byte-identical). `has_people` (`:1291`), β's `indoor_blocked`, guest and time-of-day logic keep the masked value (β is sleep-exempt anyway; changing `has_people` would alter SLEEP→HOME semantics, out of scope).
- **Ground truth for acceptance:** `house_state_log` rows `previous_state='sleep' AND state='away'`, cross-checked against `occupancy_events` for rooms occupied at that instant.

### 3.2 D2 value: trusted denominator
- **Producer:** `tracking_status` from `person_coordinator.py`. STALE is set only in the "Bermuda sensor exists but resolved no room" branch and only while `now − last_bermuda_update < decay_timeout` (`:607-616`); then `location = old_location` (a room). After N it falls to the `person.*` home/away read (`:644+`). So STALE is a 300 s-bounded "BLE saw them in a room" stamp, which is L(5) from P4.
- **Fix:** `_tracking_active(info)` returns True for STALE as well as ACTIVE when `PRESENCE_STALE_RESIDENT_COUNTS_HOME` is True. A STALE person then enters `trustworthy_persons` with `location = <room>`, so `all_tracked_persons_away` is False. `excluded_persons` no longer lists them; the reason is visible instead via a new attribute `stale_counted_home` (list of names) so the change is observable.
- **Dependency health:** needs a live Bermuda fleet. Here: 55/55 proxies (visibility audit §2). P4 caveat: `pps` rows lag truth; L(5) precision is limited, and that is why N stays at 300 s and is not raised.
- **Consumers of `all_tracked_persons_away` / `_tracked_persons_count_trusted`:** α (`:1170`), β (`:1248` via `all_trusted_or_lost_away_persons_away`), the away-veto switch coercion (`:6476-6486`), `should_veto_due_to_reliable_signals` parallel lists (`person_tracking_active_signals`, `:5904-5909`, D1 of v4.7.15.1: the D2 change must keep the list aligned and feed the *same* boolean it uses for trust, so the reliable-signal helper sees STALE as reliable when the constant is on), the sensor attributes `all_tracked_persons_away`, `tracked_persons_count_trusted`, `excluded_persons`, the D5/D6 observational episodes (`away_transition_blocked`, `tracker_trust_excluded`, `:6520+`). The builder must grep `_tracking_active\|person_tracking_active_signals\|_excluded_persons` and confirm each site (wire-in anchor).
- **Nobody-home is not affected:** census counts a person whose location is not `away/unknown/""` (`camera_census._get_ble_persons`, cited by the Wigton replay at `camera_census.py:2671-2686`), and a STALE person's location is a room, so census is already ≥ 1. D2 only changes α/β.

### 3.3 D3 values
| Value | Producer | Consumers |
|---|---|---|
| `last_away_branch` (`nobody_home` / `active` / `lost_admitted` / `lost_admitted_immediate` / `override` / `restore`) + `last_away_at` | Set in `_dispatch_house_state_change` (`:7861`) on any edge into AWAY: inference copies `_veto_path` (which now reads `nobody_home` for P1); non-inference sources map from `source` | Display only (sensor attribute, D7 episode already carries `veto_path`). No actuation reader. |
| `away_entries_today` | Incremented at the same edge; reset on local-date change checked at increment **and** on every `_periodic_inference` tick; hydrated at setup with the new DAO kwarg | Display only. |
| `guest_reason` (`none` / `guest_room:<room>` / `unidentified_persistent` / `override`) | Computed in `_run_inference` from which of Path B (`_guest_room_gate_armed`, first qualifying room) or Path A (`_guest_gate_armed`) armed `guest_armed` that tick; `override` when the house-state override is GUEST | Display only. |
| `stale_counted_home` (D2) | `_run_inference` trust loop | Display only. |

Recorder placement (R1 LOW-3 / R2 M2): `last_away_branch`, `last_away_at`, `away_entries_today`, `guest_reason` change rarely and are **recorded** (the post-ship scorecard reads them within 7 days). `stale_counted_home` changes on every BLE dropout and goes in **`_unrecorded_attributes`**. The pre-existing churners on the same sensor (`dwell_seconds`, `veto_path`, `lost_away_grace_remaining_s`, `last_veto_decision`) are out of scope; a one-line note card is §12.

---

## 4. Consumer enumeration of house AWAY (who sees the changed edge)

D1 and D2 change *when* AWAY is proposed (fewer false AWAYs, departure bound unchanged by D1, up to +N s by D2). Rows carried from Rev 4 §3.4 and re-grepped 2026-10-18.

| Consumer | file:line | Kind | Effect of D1 (night) | Effect of D2 |
|---|---|---|---|---|
| HVAC presets | `hvac.py:1437`, `:5184`; AWAY→away `:2968`/`:3024` | signal, trust | Fewer false SLEEP→AWAY at night; HVAC zone vacancy (knob 48) unchanged | AWAY edge ≤ N s later after a BLE dropout departure |
| Room leave-on lights sweep | `coordinator.py:935` | signal edge | fewer spurious night sweeps | ≤ N |
| Per-room chains / AI rules on `house_state_away` | `coordinator.py:1739-1749`; labels `config_flow.py:3183`, `:14995` | signal | none configured live | ≤ N |
| **HA automation `wallpanel_fleet_force_off_secure`** | `automations.yaml:8335-8355` (`sensor.ura_coordinator_manager_house_state` → away for 3 min → 5 panels off) | HA actuation | no false panel-off from night flaps | short dropouts < 3 min never reached it anyway; ≤ N later on real departures |
| Wall-panel siblings `wallpanel_fleet_wake`, `_sleep_after_grace` | `automations.yaml:8255`, `:8270`, `:8320` | HA automation | fewer false wakes after a SLEEP→AWAY→ARRIVING loop | ≤ N |
| Exterior-person NM severity | **`const.py:2344`** (`hs in ("away","vacation","sleep","home_night") → CRITICAL`), caller `perimeter_alert.py:1660-1665` | trust (NM) | none: SLEEP and AWAY both map to CRITICAL | daytime: fewer false CRITICALs during BLE-dropout flaps |
| Perimeter vehicle night alert | `perimeter_alert.py:2769`, `const.py:2701` | poll | none (night already alerting) | ≤ N |
| Security auto-follow | `security.py:759`, `:1087-1094`; off live | signal | no false auto-arm at night if enabled | — |
| Comfort-fan AWAY veto | `fan_veto.py:60`, `:167` | trust | fans no longer vetoed on a sleeper | ≤ N |
| HVAC pre-conditioning / optimizer / energy offset | `hvac_predict.py:446`, `optimization.py:3661`, `energy.py:8144-8236` | poll/advisory | fewer false AWAY | ≤ N |
| ARRIVING path + re-arm cooldown | `presence.py:1297`, `:6992-7008` | internal | removes the SLEEP→AWAY→ARRIVING→HOME→SLEEP loop (Wigton S0) | — |
| Someone-home binary sensor | `binary_sensor.py:2315` | display; no automation reads it (R1 open c) | — | — |
| Bayesian / routine / music / arrester | `__init__.py:3313-3329`, `routine_forecaster.py:188`, `music_following.py:301`, `hvac_override.py:1010` | signal | negligible | negligible |
| EVSE, battery | none | — | — | — |

**Emission/decision sites for this cycle:** `grep -n "return HouseState.AWAY" presence.py` → exactly `:1131`, `:1181`, `:1288`. D1 touches only `:1131`'s condition; D2 changes the input of `:1181` and `:1288`. Other writers (`transition` `:6961`, overrides `select.py:278` / `__init__.py:6201` / `presence.py:8017`, `apply_restored` `manager.py:697`) are fenced and untouched; D3 counts their AWAY edges.

---

## 5. Measure before build (done)
No new probe is needed to start; the numbers are in hand:
- **D1:** Wigton S0 216/251 AWAY entries are SLEEP→nobody-home; S1 1/4. Main house: 54 of 102 real AWAYs (10-13→10-18) carry `veto_path = none` = nobody-home (P4 §1); how many of those were from SLEEP is **not measured**. The post-ship scorecard (§10 D0) splits them; the build does not depend on it, because INV-SLEEP-NOT-EMPTY is a correctness property, not a tuning trade.
- **D2:** P4 §4: L(5) catches 2–4 of 9 genuine ordinary resident misses, plausibly the 4 stale-Jaya entries of 10-17, and delays 0 of 10 genuine departures inside 15 min (median exit→AWAY 11.5 → 11.6 min).
- **D3:** visibility audit: AWAY entries 5/4/33/11/42/10 per CDT day 10-12..10-17, readable only from the DB today.

---

## 6. Marginal-benefit decomposition
- **D1** is the largest benefit per line: one boolean, already computed for WAKING. It fixes a correctness bug in both houses and dominates Wigton when census inputs are thin.
- **D2 at N = 300 s** reuses the stamp exactly; going beyond 300 s (L(10): +2–3 resident misses, −1 of 7 departures inside 15 min) needs a new last-seen stamp and a departure trade. **Parked** (§12) until a precise Bermuda-history probe exists (P4 §6).
- **D3** is three attributes and a counter; it turns every future AWAY question into a sensor read instead of a DB replay. A separate counter *entity* (visibility audit 4b) adds nothing an attribute does not: rejected.
- **Rev 4 A/B:** parked by the operator. Their margin (guest-room and short camera flaps) was measured mostly on guests and on the camera house; neither helps Wigton (A inert without interior cameras, B needs guest-room flags and a cap).

---

## 7. Deliverables

### D1: SLEEP-mask fix on the nobody-home branch
**Change.**
1. In `_run_inference`, next to `any_zone_raw_occupied` (`:5996`): `any_zone_occupied_for_empty = any(t.mode == ZonePresenceMode.OCCUPIED or (t.mode == ZonePresenceMode.SLEEP and t.raw_occupied) for t in self._zone_trackers.values())` when `PRESENCE_NOBODY_HOME_READS_RAW_IN_SLEEP` is True, else `any_zone_occupied`.
2. Pass it to `infer()` as `any_zone_occupied_for_empty=` (new kwarg, default `None` → use `any_zone_occupied`).
3. In `infer()` nobody-home: `if census_count == 0 and not (any_zone_occupied if any_zone_occupied_for_empty is None else any_zone_occupied_for_empty):`. The already-AWAY `return None` stays first inside the branch. Set `self._veto_path = "nobody_home"` on both the fire and the already-AWAY return (mirrors α).
4. Expose `any_zone_occupied_for_empty` as a sensor attribute `nobody_home_zone_input` (unrecorded, it is per tick).

**Discharge.** No new hold mechanism: when the raw zones clear, the next event or the 60 s periodic (`presence.py:2926-2930`) proposes AWAY. Precondition from R2 H3: **move the `async_track_time_interval(self._periodic_inference …)` registration out of the discovery `try:` block** so a discovery exception can never remove the only no-event discharge. This is a two-line move, inside D1 because INV-EMPTY-REACHES-AWAY depends on it.

**Kill switch.** `PRESENCE_NOBODY_HOME_READS_RAW_IN_SLEEP: Final = True` in `const.py`, rung 1 (a correctness fix; flipping it should need review). False = today's behaviour.

**Acceptance criteria.**
- **Verify (fix):** house SLEEP, census 0, a zone with `raw_occupied=True` → `infer()` returns not AWAY (SLEEP held). **Under the old bug** the same fixture returns AWAY. Discriminates.
- **Verify (discharge):** house SLEEP, census 0, all zones `raw_occupied=False` → AWAY proposed on the same tick (empty house still leaves). A broken fix that simply blocked nobody-home in SLEEP would fail this.
- **Verify:** non-SLEEP behaviour unchanged; manual zone AWAY override is still "not occupied".
- **Tests:** `test_nobody_home_blocked_in_sleep_when_zone_raw_occupied` (mutation: drop the raw limb → RED), `test_nobody_home_fires_in_sleep_when_all_raw_clear`, `test_nobody_home_non_sleep_byte_identical`, `test_manual_zone_away_override_still_empty`, `test_kill_constant_false_restores_masked_behaviour`, `test_nobody_home_sets_veto_path_label`, `test_periodic_registered_when_discovery_raises` (mutation: move registration back inside the try → RED), **`test_wigton_shape_sleep_loop_suppressed`** (fixture §9.2).
- **Live:** over 7 days post-restart, `house_state_log` rows `previous_state='sleep' AND state='away'` are each checked against `occupancy_events`: 0 rows with any room in an indoor zone occupied at the instant. A pre-ship baseline count of the same query over the previous 7 days is taken at deploy so the change is a comparison, not an impression.

### D2: 5-min resident BLE memory (STALE counts home)
**Change.** In `_tracking_active` (`presence.py:5862-5873`): `status in (ACTIVE, STALE)` when `PRESENCE_STALE_RESIDENT_COUNTS_HOME` is True; else ACTIVE only. `_phone_trustworthy` precedence unchanged (a `phone_left_behind=on` person stays excluded). Keep `person_tracking_active_signals` fed from the same boolean. Collect STALE names into `self._stale_counted_home` for the attribute.

**N and its knob.** N = `decay_timeout` = `CONF_PERSON_DECAY_TIMEOUT`, default `DEFAULT_PERSON_DECAY_TIMEOUT = 300` s (`const.py:163-164`), read from integration `entry.data` (rung 1.5: an existing key with no flow field). **REUSED, not a new knob**, because STALE *is* this window; a second number would let the two drift. Raising N past 300 s changes STALE for every person-coordinator consumer, so it stays review-only; L(10+) is parked with its own stamp (§12). Kill switch: `PRESENCE_STALE_RESIDENT_COUNTS_HOME: Final = True`, rung 1.

**INV-NO-BLE-HOLD check (operator ask).** Verified in code: STALE is only assigned while `time_since_update < self.decay_timeout` (`person_coordinator.py:611-616`); `last_bermuda_update` is carried, not refreshed, through STALE ticks (`:615`, `:625`). So the hold ends at most N after the last real Bermuda room fix, plus one person-coordinator update interval. Builder must confirm the update interval (attribute `update_interval_seconds` on `sensor.universal_room_automation_person_tracking_status`) and state the exact bound in the README.

**Acceptance criteria.**
- **Verify (fix):** resident STALE in `study_a`, others away → α returns not AWAY. **Under today's code** the same fixture returns AWAY with `excluded_persons={name: tracking_status=stale}`. Discriminates.
- **Verify (bound):** same resident at `last_bermuda_update = now − (N+1)` resolves to `person.*` state; if `not_home` → AWAY fires.
- **Verify:** `phone_left_behind=on` + STALE → still excluded (forgotten phone path untouched).
- **Tests:** `test_stale_resident_blocks_alpha` (mutation: revert predicate → RED), `test_stale_resident_blocks_beta`, `test_stale_hold_ends_after_decay_timeout`, `test_phone_left_behind_overrides_stale`, `test_reliable_signal_lists_aligned_with_stale`, `test_kill_constant_false_excludes_stale`, config extremes `decay_timeout ∈ {0, 60, 300, 900}` (0 → STALE never assigned → inert), **`test_wigton_shape_no_bermuda_inert`**.
- **Live:** scorecard D0 row: AWAY transitions whose D7 episode shows `excluded_persons` containing `tracking_status=stale` = **0** after deploy (baseline: 4 in 102, 10-13→10-18). `stale_counted_home` is non-empty at least once in 7 days (proves wiring).

### D3: Observability on the existing house-state sensor
**Branch label.** `nobody_home` value (D1 step 3). `last_away_branch` + `last_away_at` set in `_dispatch_house_state_change` on any edge into AWAY: inference → the mirrored `_veto_path`; `source="override_adapter"` → `override`; boot restore → `restore`.

**AWAY-entries-today counter.**
- Increment in `_dispatch_house_state_change` on `new_state == AWAY and old_state != AWAY` (the sole `house_state_log` writer, so counter and log agree by construction, incl. overrides).
- Day boundary on the **local** date (`dt_util.now().date()`), checked at increment and on every `_periodic_inference` tick, so the attribute resets at local midnight with no transition.
- Hydration: new DAO kwarg `count_house_state_changes_since(since_iso, *, state=None, since_utc=None)`. The new call passes `since_utc = dt_util.as_utc(start of local today)` as an ISO string comparable to the naive-UTC column, `state='away'`, and filters `previous_state IS NULL OR previous_state <> 'away'`. The existing `_transitions_today` call is untouched (default kwargs → byte-identical SQL).

**guest_reason.** Set each inference tick from whichever gate armed GUEST (§3.3). `none` when not armed.

**Attributes** on `sensor.ura_presence_coordinator_presence_house_state`: recorded `last_away_branch`, `last_away_at`, `away_entries_today`, `guest_reason`; `_unrecorded_attributes = frozenset({"stale_counted_home", "nobody_home_zone_input"})`. **No v8 card in this cycle's code**: the card is a dashboard config action after deploy (snapshot first, `people` view, the visibility audit 4a pattern), listed as an operator step, not a build item.

**Acceptance criteria.**
- **Verify:** a nobody-home AWAY sets `last_away_branch=nobody_home` (today the sensor shows `veto_path: none`, indistinguishable from "no veto").
- **Verify:** an override AWAY sets `override` and increments the counter.
- **Verify:** counter at 00:00:30 local with no transition reads 0 (today it would read yesterday's count).
- **Verify:** restart at 20:00 CDT: hydrated count excludes rows from before local midnight (today's local-date compare would include 19:00–24:00 UTC of the previous evening). Discriminates the UTC bug.
- **Tests:** `test_last_away_branch_nobody_home`, `test_last_away_branch_override_and_restore`, `test_away_entries_today_resets_on_periodic_at_local_midnight`, `test_away_count_hydration_uses_utc_instant_of_local_midnight`, `test_away_count_excludes_away_to_away_rows`, `test_count_since_default_sql_unchanged`, `test_guest_reason_guest_room`, `test_guest_reason_unidentified_persistent`, `test_unrecorded_attributes_set`, **`test_wigton_shape_observability_without_cameras_or_ble`**.
- **Live:** `away_entries_today` equals the INV-COUNTER-MATCHES-LOG query at two reads (one after a restart); `last_away_branch` never `none` after an AWAY; recorder `state_attributes` for the sensor carry no `stale_counted_home` key.

---

## 8. Numbers and their knobs
| Number | Value | Rung | Why | Kill |
|---|---|---|---|---|
| D1 enable | True | 1 (`const.py`) | correctness fix; flipping should need review | False |
| D2 enable | True | 1 (`const.py`) | trust-denominator change | False |
| N (BLE memory) | 300 s | existing `CONF_PERSON_DECAY_TIMEOUT` (entry.data, no flow field) | it *is* the STALE window; one number, not two | 0 → STALE never assigned → D2 inert |
| Discharge tick | 60 s | existing | reused | — |
| Dwell table | SLEEP 600 / GUEST 300 / HOME_* 120 / WAKING, ARRIVING 60 s | existing `DEFAULT_HYSTERESIS` | bounds INV-EMPTY-REACHES-AWAY | — |

No new Number entity: nothing here is a policy the operator tunes by observation.

---

## 9. Three house shapes (operator constraint 2026-10-18; part of acceptance)

### 9.1 Evaluation
| Deliverable | This house (cameras, Bermuda/IRK, 4 trackers) | Wigton (no interior cameras, no BLE room trackers, no doors, 1 enrolled phone, 17 ZX radars) | Generic minimal (room motion sensors, 1–2 `person.*` GPS phones, no cameras, no BLE) |
|---|---|---|---|
| **D1 SLEEP mask** | **Helps.** Night nobody-home AWAYs with a sleeper (R1 HIGH-1 repro; share of the 54 nobody-home entries unmeasured, scored by D0). Cameras do not see sleepers, so nothing else covers this. | **Helps, most.** Replay S0: 216 of 251 entries are SLEEP→nobody-home loops; S1: 1 of 4 (10-13 05:53). Depends only on room sensors. | **Helps.** Census is 0 whenever phones are away or not counted, so this house shape lives in S0 at night. Needs only zone room sensors. |
| **D2 BLE memory** | **Helps (small).** P4: 2–4 of 9 resident misses, the stale-Jaya class (4 of 102). 0 departures lost. | **Inert, explicitly.** No Bermuda room trackers (bermuda has 4 global sensors only), so STALE is never assigned (`person_coordinator.py:607` requires a resolved Bermuda area sensor). No effect, no harm. | **Inert** without Bermuda. With Bermuda but no IRK, same as this house. |
| **D3 observability** | **Helps.** Answers visibility-audit Q1/Q4/Q5. | **Helps.** Works with zero cameras/BLE: branch label, counter and guest reason come from the state machine and the DB. `guest_reason` reads `none` (no guest rooms flagged, no cameras). | **Helps.** Same. |
| *Hurts anywhere?* | D2 delays a genuine departure by ≤ N if the phone drops BLE at the door (P4: 0 of 10 measured). D1: none. | None found. D1 could hold SLEEP on a phantom ZX all night where today it would flap to AWAY; that is the daytime behaviour already and is the safer error for a house with residents asleep. | Same as Wigton for D1. |

**Rule check:** no deliverable depends on a capability Wigton lacks except D2, which degrades to inert by construction. D1 and D3 need zero cameras and zero BLE.

### 9.2 Wigton-shape test fixture (acceptance)
Build one fixture in `quality/tests/` from production classes (no hand-copied state machine), shaped from the Wigton replay §1:
- one tracked person `omonele`, GPS-only `person.*` (no `tracker_sources.ble`), no Bermuda sensor;
- zones: `Back hallway`, `Entertainment Zone`, `Master Suite`, `Upstairs Zone`, plus a room in no zone (Gym);
- no camera census input (`unidentified_count=0`, `face_recognized_count=0`, `camera_input_degraded=False`);
- `census_count` scenarios S0 (0) and S1 (1 while home).
Tests: `test_wigton_shape_sleep_loop_suppressed` (S0, SLEEP, Master Suite raw occupied → no AWAY over 30 simulated ticks; old code → AWAY), `test_wigton_shape_empty_still_reaches_away` (S0, all raw clear → AWAY), `test_wigton_shape_no_bermuda_inert` (D2 on/off give identical results), `test_wigton_shape_observability_without_cameras_or_ble` (AWAY via nobody-home sets `last_away_branch` and the counter; `guest_reason=none`).

**Wigton deployment note (not a deliverable):** URA is disabled there. Before enabling, confirm which census scenario applies (replay risk #1). D1 makes S0 safe at night; daytime S0 still means nobody-home fires whenever all zones clear, which is correct.

---

## 10. Post-ship scorecard (D0, read-only, cycle exit)
Run at day 7 after the restart (recorder retention is 7 days, R1 MED-3). Script committed by the build to `scripts/probes/house_state_simple_scorecard/`. Baseline = the same queries over the 7 days before deploy, captured at deploy.

| Observation | Fix working | D1 broken | D2 broken | D2 over-holding |
|---|---|---|---|---|
| SLEEP→AWAY rows with an indoor room occupied at the instant | 0 | > 0 | — | — |
| SLEEP→AWAY rows total vs baseline | lower | ≈ baseline | — | — |
| AWAY rows whose D7 episode excludes a person as `tracking_status=stale` | 0 | — | > 0 | — |
| Genuine departures (exit crossing, no sustained body) reaching AWAY within 15 min | ≥ baseline − 1 | — | — | < baseline − 1 |
| Max gap between a person's last Bermuda room update and an AWAY they blocked | ≤ N + update interval | — | — | > that |
| `away_entries_today` vs INV-COUNTER query (3 spot reads) | equal | — | — | — |
| Resident someone-home AWAY/day (P4 classifier, ordinary days) | ≤ 0.27 baseline, target ≈ 0.15–0.25 | — | — | — |

Exit: table written into the README validation section. Any failing row reopens the card. No soak.

---

## 11. Tier
**Tier 3** (house-state inference is a shared primitive consumed by HVAC, lighting, security, NM severity, wall panels). Required:
- two framing-disjoint plan reviews before build: (1) completeness re-enumeration (every `_tracking_active` / `person_tracking_active_signals` / `any_zone_occupied` reader, every AWAY consumer); (2) adversarial build-prediction;
- `ura-super-builder`;
- four build reviews: A local correctness; B state machine and lifecycle (SLEEP entry/exit, boot restore at `:2404`, periodic registration, hydration across restart, midnight reset); C per-site mutation over the D1/D2/D3 test anchors; D adversarial completeness against §2 with config extremes (`decay_timeout` 0/900; sleep hours 0-0 and 20-10; zone manual overrides; a room in no zone; all-zones-outdoor; kill constants False);
- orchestrator re-grep of `return HouseState.AWAY` and one source mutation before ship;
- operator checkpoint before deploy; restart only in an awake window (`feedback_no_restart_during_sleep`).

## 12. Non-goals, parked, and cards
**Non-goals:** Rev 4 camera guard and guest-room veto; any change to `has_people`, β, guest-gate behaviour, census, hysteresis values, HVAC code, the schema, or the v8 dashboard in code.

| Item | Status | Revival trigger |
|---|---|---|
| Rev 4 guard A + veto B (`PLANNING_house_away_flap_untracked_occupant.md`) | **PARKED by operator 2026-10-18** | Guest accuracy becomes a priority (a long stay or a party) |
| L(N > 300 s) with a new last-seen stamp | PARKED | A Bermuda-area-history probe (P4 §6) shows ≥ 3 resident misses/month with BLE last seen 5–15 min before AWAY and no departure cost |
| Trim pre-existing recorder churn on the house-state sensor (`dwell_seconds`, `veto_path`, etc.) | Card: HOUSE-STATE-SENSOR-ATTR-CHURN-1 (to mint) | — |
| v8 "Away decisions" card | Operator dashboard action after deploy | — |

**Separate finding to card (do not fold): PERSON-GPS-ANY-HOME-WINS-1.** `person_coordinator.py:207-229` iterates `device_trackers` and **overwrites** `sources["gps"]` per GPS tracker, so the last GPS tracker in the list wins. On 2026-10-18 the iPad was removed from `person.oji_udezue` to stop a stale iPad overriding the phone. The question: should the merge be "any GPS `home` wins" (fail-toward-home, matches resident-first) or "freshest `last_updated` wins"? "Any home wins" re-opens the forgotten-device hazard (an iPad left home holds the person home indefinitely, the INV-NO-BLE-HOLD class), so freshest-wins is likely the safer rule. Tier 1–2, needs its own decision; it also matters for Wigton, where `person.omonele` has 6 trackers but only the Android reports.

## 13. Docs (same commit as the build)
- PRESENCE state of play: §2 nobody-home reads raw zones in SLEEP; STALE counts home; §10 new ledger row "SLEEP stops nobody-home AWAY" was false before this cycle (R1 HIGH-1); gold pattern "raw zone occupancy for emptiness decisions".
- README with the §10 baseline and the day-7 table written back.
