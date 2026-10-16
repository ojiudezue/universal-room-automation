# PLANNING — House AWAY flap with an untracked occupant home

**Card:** HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1
**Status:** **Rev 2**, 2026-10-16 (overnight, read-only). Folds both Tier-3 plan reviews (`docs/reviews/plan-review/PLAN_REVIEW_house_away_flap_R1_completeness.md`, `…_R2_build_prediction.md`, both FIX-PLAN). The disposition is in §12. No code changed. Next step: a re-verify pass on Rev 2, then operator approval before build.
**Author:** ura-planner.
**Operator instruction on the card:** "Tell me what the plan is. I want careful plans. But make sure it context and prior art aware."

---

## 0. The plan in one paragraph

When no tracked phone is home, URA declares the house AWAY the moment the interior cameras stop seeing anyone, even if they saw someone a few seconds earlier. Three branches of the house-state logic do this (path α, path β and "nobody home"). The existing 3-minute camera hold does not prevent it, because a later clamp cuts the held count back to the live reading. The fix is one shared rule: the house may not go AWAY until the cameras have seen no unidentified person and no recognised face for "Count memory" minutes (default 20, 0 = off). Phones and BLE never count as "seen", so a forgotten phone can't hold the house home. The existing 60-second re-check releases a genuinely empty house within about W + 1 minute, and no new timer is added. After a restart the rule acts as if someone was seen at boot. Measured over 59 normal days, this would have stopped about 70% of AWAY entries, nearly all of them short false flips. It also stops about 28 of 44 during the current trip. Real departures reach AWAY up to 20 minutes later. The later census estimator (D6) keeps the same knob and swaps in its own count.

---

## 1. Institutional context verified (MANDATORY)

### 1.1 Mandatory docs read completely before writing
- `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. ledger §10). Contradiction recorded in §9 C1.
- `docs/architecture/SENSOR_FLEET_CLASSES.md`. Not re-litigated; room sensors enter only through `any_zone_occupied`.
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 C1–C38). No ledger claim re-asserted.
- `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`. No identity input is used; `face_recognized_count` is used only as "a camera saw a body".
- `docs/QUALITY_CONTEXT.md`. Relevant classes: #53 one missed site, #7 stale data source, the concept-split smell (#63, `feedback_coincidental_equality_masks_concept_split`), suppression-needs-discharge.

### 1.2 Prior-art scan — REUSE or BUILD

| Piece | Verdict | Evidence |
|---|---|---|
| Camera body evidence per tick | **REUSE** | `_handle_census_update` `presence.py:4739-4815` already parses `unidentified_count` (`:4758`) and `face_recognized_count` (`:4765`) from the census payload. **Not** `interior_count`: it is `total_persons` = identified (face ∪ **BLE**) + held unidentified (`camera_census.py:1828`, `_apply_enhanced_house_census` `:5903+`). A BLE term would re-open GAP-A D8 (`presence.py:1155-1162`). R2-01. |
| Last-camera-body timestamp | **BUILD (one RAM field)** | Grep of presence / camera_census / const for `last_body`, `body_seen`, `last_nonzero`: no hits. `_peak_house_timestamp` is a promotion stamp (no self-refresh by design). |
| Discharge | **REUSE the 60 s periodic inference** | `async_track_time_interval(self._periodic_inference, 60 s)` `presence.py:2924-2930`; `_periodic_inference` → `_run_inference("periodic")` (`:5076-5082`). **NOT** `_schedule_deferred_retry` (`:5107-5129`): its single `_retry_unsub` slot is shared with the hysteresis retry and cancelled by accepted transitions (`:6966-6968`), and it refuses to re-arm from a `deferred_retry` trigger (`:7099-7101`). R1-01, R2-02. |
| Held camera max (concept) | **REUSE the estimator's design** | `PLANNING_census_occupancy_estimator.md` §7.2 `M_cam` over `FLOOR_WINDOW_S`; M_cam is camera-only (`S`). This slice matches that: camera-only. |
| Window knob | **REUSE name and default** | Estimator §7.10 `FLOOR_WINDOW_S` → Number "Count memory", default 1200 s, "0 = instantaneous". Persistence pattern: `number.py:684-690`, "entry.options is the SOLE source of truth (no RestoreEntity)". |
| Census hold | **REJECT as the lever** | `_apply_hold_decay` `camera_census.py:5292`; live `census_hold_interior` = 3.0 min. Cancelled by the clamp `camera_census.py:6006-6009` (§3.2). |
| Tick-count debounce `sustained_external_empty` | **REJECT** | It counts inference calls (`presence.py` ~6395-6410), not seconds. |
| Arriving re-arm cooldown `ARRIVING_REARM_COOLDOWN_S` | **REJECT (n/a)** | `presence.py:221`; covers failed arrivals only. |
| State-machine hysteresis | **REJECT** | Minimum dwell in a state, `house_state.py:~130`. No knob (`manager.py:225`). |
| House-state override (interim) | **REUSE** | Three selects exist, all `auto` live (R1 verified): **canonical** `select.ura_presence_coordinator_house_state_override` (Presence device, `select.py:332-339`); siblings `select.ura_coordinator_manager_house_state_override` and `select.universal_room_automation_house_state_override` write the same machine override (`select.py:255-278`). |
| Away veto switch (rollback) | **REUSE** | `switch.ura_presence_coordinator_away_confirmation_veto` live **on** (`switch.py:3880`). |

### 1.3 Prior plans and cards
Estimator plan read fully (C6). `DESIGN_census_simplification.md` and `PLANNING_census_inputs_first*.md`: headers only. Related cards: card text only (the card's adjacency sweep stands).

### 1.4 Memory
Index lines only for the bodies listed in Rev 1. **Full bodies not pulled** — the re-verify reviewer should pull `feedback_suppression_needs_discharge` and `project_guest_mode_false_positive_backlog`.

### 1.5 Code read
`presence.py:1000-1300, 2924-2960, 4739-4815, 5076-5129, 6380-6560, 6961-6968, 7099-7101`; `house_state.py:60-175`; `camera_census.py:2440-2535, 5265-5650, 5903-6045`; `number.py:684-690`; the polling consumer lines in §3.4.

---

## 2. Falsifiable invariants

Let `W` = the live Count memory in seconds and `B(t)` = the most recent census update time at or before t with `unidentified_count > 0 OR face_recognized_count > 0`. After a restart, `B` = boot time until a newer camera body is seen.

> **INV-AWAY-QUIET:** for W > 0, `infer()` never returns `HouseState.AWAY` from the nobody-home, α or β branch at time t if `t − B(t) < W`. All three branches compare against one `now`.
> **INV-AWAY-DISCHARGE:** if every other AWAY conjunct of some branch holds continuously from `B + W` on, AWAY is returned by `B + W + 60 s` (one periodic tick), plus any state-machine hysteresis remaining at that tick (bounded by `DEFAULT_HYSTERESIS`, max 120 s for HOME_*; `house_state.py:~130`). The periodic tick re-evaluates every 60 s regardless of retries.
> **INV-NO-BLE-HOLD:** a census update with `unidentified_count = 0 AND face_recognized_count = 0` never moves `B`, whatever `interior_count` says (forgotten phone / stale BLE).
> **INV-BYTE-ID:** W = 0 ⇒ every path is byte-identical to today, with no new state written and no veto-path label change.

---

## 3. Producer and consumer checks

### 3.1 The three AWAY branches (code)
1. Nobody home, `presence.py:1127-1131`: `census_count == 0 and not any_zone_occupied`. Confidence 0.9.
2. Path α, `:1169-1181`: `not camera_input_degraded and all_tracked_persons_away and unidentified_count == 0 and face_recognized_count == 0`. Confidence 0.95.
3. Path β, `:1262-1288`: trackers away, `unidentified_count == 0`, `census_count == 0`, not indoor-blocked, grace, not sleep-exempt. Confidence 0.95.

R1 verified there is no other automatic AWAY producer: `HouseStateMachine.transition` is called only at `presence.py:6961`; `force_state` has no callers.

### 3.2 PRODUCER — why the 3-min hold doesn't help
In `_apply_enhanced_house_census`, the held unidentified count is clamped by `raw_total_ceiling = max(camera_total_pre_cancel, identified_count)` (`camera_census.py:6006-6009`). `camera_total_pre_cancel` is the instantaneous per-camera `person_count` sum (`:5577`). With every resident away, identified = 0, so the published `unidentified_count` / `interior_count` drop to 0 on the same tick as the camera. Ground truth: snapshot `14:16:42 total=1` → `14:17:58 total=0` → AWAY `14:17:59` (10-14 UTC). The clamp is correct for its purpose and **is not changed**.

**Stamp producer (R2-01).** `B` moves on `unidentified_count > 0` (an unrecognised body on an interior camera, post-BLE-cancel) or `face_recognized_count > 0` (a recognised face on camera, already not_home-vetoed at `camera_census.py:~5890`). Both are camera-provenance. `interior_count` is excluded: it carries BLE identities. The nobody-home and β branches already require `census_count == 0`, so excluding it loses nothing.

### 3.3 `any_zone_occupied`
False on every nobody-home AWAY. The occupant's rooms: **not verified.**

### 3.4 CONSUMERS of AWAY, and what an up-to-W departure delay costs each (R1-02)

| Consumer | file:line | Kind | Cost of a false AWAY (prevented) | Cost of a real AWAY arriving ≤ W late |
|---|---|---|---|---|
| HVAC presets | `hvac.py:1437` → `:5177` | signal, trust | Preset churn and an away range on the occupant | ≤ 20 min more home-range conditioning per departure (~0.7/day). HVAC's own zone vacancy (5 min grace, HVAC doc §3.2) still retreats empty zones independently, so the real cost is smaller. |
| Room automation / AWAY leave-on lights sweep | `coordinator.py:1739` | signal, trust | Lights swept off on the occupant | Lights left on ≤ W after the family leaves. Room vacancy timeouts still turn them off. |
| Security auto-follow | `security.py:749/1077`; `SECURITY_AUTO_FOLLOW_ARM_DELAY_S = 30` `const.py:3151` | signal, trust | Arming with a person inside | **Auto-arm on departure is delayed ≤ W. This is the most serious cost.** Whether auto-follow is enabled live: **not verified.** If it is, the operator must accept this explicitly (§11 checkpoint). Mitigation already exists: the manual arm. |
| Perimeter vehicle night alert | `perimeter_alert.py:2769`, `EXTERIOR_VEHICLE_ALERT_STATES` `const.py:2701` (away/sleep/vacation; 22:00-06:00 only) | poll, trust (NM) | Spurious "away" vehicle alerts | Night-only. A night departure delays the vehicle alert ≤ W. Small. |
| Comfort-fan AWAY veto | `fan_veto.py:60` | poll, trust | Fans vetoed on the occupant | Fans may run ≤ W after departure. Energy only. |
| Security posture optimizer | `optimization.py:3661` | poll (findings) | Spurious posture findings | Findings ≤ W later. Advisory. |
| HVAC pre-conditioning `is_unoccupied` | `hvac_predict.py:446` | poll, trust | Pre-arrival logic on an occupied house | Pre-conditioning eligibility ≤ W later. Small. |
| Someone-home binary sensor | `binary_sensor.py:2315` | display / downstream automations | Flicker | ≤ W late. Its HA-side automations: **not enumerated.** |
| Energy offset reset | `energy.py:8050/8257` | poll, trust | Not traced | ≤ W late. **Not traced further.** |
| Bayesian guest / routine forecaster / music / arrester durable state | `__init__.py:3313`, `routine_forecaster.py:188`, `music_following.py:301`, `hvac_override.py:1010` | signal | Learning pollution / media / immune-hold end | Negligible. |
| EVSE, battery | no subscription found (R1 confirmed) | — | — | — |

Net: the delay is energy and comfort for every consumer except security auto-arm. That one needs an explicit operator acceptance or a lower W.

---

## 4. Measure before build (read-only, run 2026-10-16)
The Rev 1 numbers are unchanged; scripts are in `.claude/tmp/awayflap/`.

| Measure | Baseline 08-16→10-13 (59 d) | Trip 10-14 12Z→10-16 |
|---|---|---|
| AWAY entries | 162 (max 13/day) | 44 |
| < 15 min / < 5 min | 119 / 93 | 27 / 15 |
| Short episodes, α/β vs nobody-home | 94 / 25 | 15 / 12 |
| Short episodes absorbed at W = 5/10/15/20 min | 60 / 102 / 111 / 113 | 9 / 19 / 25 / 25 |
| All AWAY absorbed at W = 20 | 114 | 28 |
| AWAY with a `person.*` home (7-d recorder) | 0 / 16 | 0 / 44 |

Caveat: the simulation used `total_persons > 0` as the body signal. With every tracker away, total_persons equals unidentified (identified = 0, confirmed in the snapshots), so the R2-01 camera-only stamp gives the same numbers in these windows. D0 re-measures with the exact stamp predicate.

---

## 5. Marginal-benefit decomposition
As Rev 1: **(B) recommended**. (A) waiting for D6 fixes nothing for months, and D6 as written misses α (C6). (B′) changing the clamp has a wider blast radius than the problem. (B″) the full estimator is blocked on inputs. (C) config only helps the trip alone. Dropping the timer (R2-02) makes (B) smaller: one RAM field, one guard, one knob.

## 6. Config-first
Unchanged. No setting fixes the daily baseline. Interim for the trip: set the canonical override `select.ura_presence_coordinator_house_state_override` to `guest` until 10-18 (operator's call). Changing `census_hold_interior` has no effect. Turning off the away veto switch does not fix the nobody-home branch.

---

## 7. Deliverables

### D0 — Pre-build probe (read-only)
Re-run with the exact stamp predicate (`unidentified_count > 0 or face_recognized_count > 0`, from `census_snapshots` plus the recorder `person_count` edges) for W ∈ {600, 900, 1200}: absorbed, residual, and departure-delay distribution. The default stays 1200 unless 900 matches absorption within 3 episodes (the security cost favours the smaller W).
- **Verify:** `AUDIT_house_away_flap_body_gap.md` table. **Live:** n/a.

### D1 — Camera-body stamp (producer)
- In `_handle_census_update` (`presence.py:4739`), after `_face_recognized_count` is parsed (`:4765-4769`): `if self._unidentified_count > 0 or self._face_recognized_count > 0: self._last_camera_body_ts = dt_util.utcnow()`. **One clock** (R2-04): `dt_util.utcnow()` everywhere; no monotonic clock.
- Gate the write itself on W > 0, so W = 0 writes no new state (INV-BYTE-ID).
- **Restart (R1-03 / R2-03, choice (a)):** the stamp is RAM only and **not persisted**. In `__init__` / setup it is seeded to the boot time (`dt_util.utcnow()` at coordinator setup), so after any restart AWAY needs W of camera quiet. Accepted cost: up to W of delay to an AWAY after a restart into an empty house (the boot-settle gate `presence.py:5620-5645` already delays it). There is no early-AWAY case. Not persisting avoids the Store-heartbeat staleness R1-03 found (`manager.py:688-747` saves only on machine change).
- **Boot census seed (R1-04):** `presence.py:2946/2958` seeds `_census_count` only, which the stamp does not read. The boot-time seed of `B` covers this. No stamp at the seed.
- **Tests:**
  - `test_body_stamp_set_on_unidentified_positive`
  - `test_body_stamp_set_on_face_positive`
  - `test_body_stamp_not_refreshed_by_ble_only_identity` (census=1, unid=0, face=0 → no move)
  - `test_body_stamp_not_refreshed_by_zero`
  - `test_body_stamp_seeded_at_boot`
  - `test_no_state_written_when_W_zero`
- **Verify (discriminating):** a forgotten-phone replay (BLE keeps `interior_count = 1`, cameras empty) still reaches AWAY via α at B + W + ≤60 s. Under the Rev 1 `census_count` stamp it never would.

### D2 — Guard on all three AWAY branches (consumer)
- New `infer()` kwargs: `body_quiet_elapsed: bool = True` (the default keeps all existing callers byte-identical).
- The caller, `_run_inference`, captures `now = dt_util.utcnow()` once and passes it to both the elapsed computation (`W == 0 or now − self._last_camera_body_ts >= W`) and `infer(now=now)` (R2-04). This needs a check that `infer`'s `now` is used tz-consistently; `infer` reads `now.hour` for local time windows, so pass a local-aware `dt_util.as_local(now)`. **The builder must verify the existing caller's `now` convention at `presence.py:~6487` and keep it identical**; the elapsed arithmetic uses UTC.
- Each of the three AWAY returns gets the `and body_quiet_elapsed` conjunct. **Placement:** inside each branch's existing condition, after `current_state == AWAY → return None` is no longer reached. The guard does not apply in the already-AWAY case: `if current_state == AWAY: return None` stays first and unguarded.
- **Veto label (R2-05):** inside `infer()`, when a branch's other conjuncts all hold and only `body_quiet_elapsed` is False, set `self._veto_path = "body_quiet_hold"` (after the `:1124` reset) and fall through. The caller copies it at `:6518` unchanged. The D5 memory-writer classification at `:6520-6560`: `body_quiet_hold` counts as a **block** with `veto_path` `body_quiet_hold` and is not attributed to α-starved/denies. The builder adds that branch and a test. When several branches are guard-denied in one call, the first denial (nobody-home, then α, then β) sets the label.
- **No new timer** (R1-01 / R2-02). Discharge is the 60 s periodic (`presence.py:2924-2930`). `RETRY_SLACK_S` is deleted.
- **Tests (framing-C anchors, R2-06):**
  - Per branch: `test_nobody_home_blocked_within_W`, `test_path_alpha_blocked_within_W`, `test_path_beta_blocked_within_W`. Each goes RED when its own conjunct is deleted.
  - Producer: deleting the D1 stamp write → `test_body_stamp_set_on_unidentified_positive` RED. Re-adding a `census_count` term → `test_body_stamp_not_refreshed_by_ble_only_identity` RED.
  - Computation: flipping `>=` to `>` → `test_away_at_exact_W_boundary` RED. Dropping the `W == 0` short-circuit → `test_W_zero_byte_identical` RED (golden over the existing presence AWAY suites).
  - Discharge: `test_periodic_discharges_at_B_plus_W` (inject `now`, call `_periodic_inference`, no sleeps). `test_discharge_while_hysteresis_blocks` (AWAY proposed during HOME_DAY 120 s dwell → lands on a later periodic tick).
  - Other: `test_veto_label_body_quiet_hold_inside_infer`, `test_memory_writer_classifies_body_quiet_hold`, `test_guard_ignored_when_already_away`.
- **Config extremes:** W = 0, W = 3600, W < 60, `camera_input_degraded=True` (α skipped; the guard still applies to nobody-home/β), restart mid-window.
- **Live:**
  - AWAY entries in `house_state_log` each come ≥ W after the last camera-body snapshot.
  - Short (< W) AWAY episodes ≈ 0 on the next baseline day.
  - The veto-path attribute shows `body_quiet_hold` during holds.
  - A real departure's AWAY row lands within W + 180 s of the last camera body. That margin (60 s periodic + 120 s maximum hysteresis) distinguishes a working discharge from a stuck HOME.

### D3 — Knob "Count memory" (R2-07)
- **CONF key** `CONF_PRESENCE_COUNT_MEMORY_S = "presence_count_memory_s"`, NEW. Grep of `const.py` shows no `count_memory`/`FLOOR_WINDOW`; the estimator's `FLOOR_WINDOW_S` is unbuilt. The const value doubles as the estimator's knob.
- **Owning entry:** the Coordinator Manager entry (where presence knobs live). The builder confirms this against the presence Number pattern in `number.py`.
- **Entity:** `number.ura_presence_coordinator_count_memory`; unique_id `f"{DOMAIN}_presence_count_memory"`.
- **Rung 3.** Persistence = options write-back (`number.py:684-690`, "entry.options is the SOLE source of truth"); no RestoreEntity. Default 1200 s, range 0-3600, step 60. **0 = off (today's behaviour).**
- Read live per tick (fresh read, no reload).
- Description: "How long the cameras must see no one before the house can go Away. 0 = off."
- **Test:** `test_count_memory_options_round_trip`, `test_count_memory_zero_disables`. **Live:** the entity exists at 1200 and survives a restart.

### D4 — Docs (same commit)
- PRESENCE state of play: §2 path α correction (C1), the clamp note (C4), §10 rows.
- `house_state.py` AWAY hysteresis comment.
- Estimator plan: a D6 row for α; the note that D6 replaces `body_quiet_elapsed` with `FLOOR ≤ R`, keeps the key, and adds the post-exit shrink (§8).
- README validation write-back.

---

## 8. Estimator absorption (R1-06 / R2-08)
- Same CONF key and Number. D6 changes only the caller's computation of `body_quiet_elapsed` (to `FLOOR ≤ R`). The three guarded sites, the label and the tests stay.
- **The slice uses the plain window with no observed-exit shrink.** The estimator's `FLOOR_SHRINK_HOLD_S` (collapse to 180 s after an unattributed outbound crossing, estimator §7.4) is a D6 addition on the same knob. So after D6, the effective delay on observed exits drops from ≤ W to ~3 min under an unchanged setting. That is intended and should be noted in the D6 README.
- `_last_camera_body_ts` goes into D6's supersession audit (keep as a FLOOR input or KEEP+DOCUMENT).

---

## 9. Claims found WRONG
- **C1:** presence state of play §2 says path α needs census_count = 0 and all zones away. The code at `:1169-1181` has neither.
- **C2:** the card's `update_2026_10_15` claim does not hold for α.
- **C3:** "path α causes it". In fact 11/33 (10-14) and 9/11 (10-15) came from the nobody-home branch.
- **C4:** "the 3-min hold". The clamp at `camera_census.py:6006-6009` cancels it.
- **C5:** the card's EVSE/battery consumers. There is no subscription (R1 confirmed).
- **C6:** the estimator D6 table lacks a path α row, so INV-AWAY-SAFE would not hold. Lines are stale too (`:1111`→`:1127`, `:1223`→`:1262`).
- **C7:** HVAC doc: the handler is at `hvac.py:5177`.
- **C8 (Rev 1 self-correction, R2-01):** Rev 1's D1 stamped on `census_count`. That would have blocked α forever on a forgotten phone.
- **C9 (Rev 1 self-correction, R1-01/R2-02):** Rev 1 said "REUSE `_schedule_deferred_retry`". Its shared slot loses transitions.

---

## 10. Non-goals, fences, parked items

**Non-goals:** no change to the census payload, clamp, hold, guest gate, β grace, hysteresis, HVAC, door tally or identity. Not solving the out-of-view residue (~16 trip AWAYs).

**Fenced: out of the guard's scope (R1-07), each unchanged and each with a test asserting so:**
- operator override to AWAY via any of the three selects (`select.py:278`, `__init__.py:6195`, `presence.py:8013-8021`), which is immediate;
- boot restore `apply_restored` (`house_state.py:368-431`);
- the cold-boot default `initial_state=AWAY` (`house_state.py:153`, `manager.py:225`). That default is a display/boot artefact tracked by **HOUSE-STATE-SENSOR-BOOT-AWAY-DISPLAY-1**. This plan neither fixes nor worsens it. The boot-seeded `B` means inference cannot *re-enter* AWAY for W after boot.

Test: `test_override_away_not_guarded`.

**Parked:**
- (B′) a held clamp ceiling. Revive if estimator D3 shadow passes gate 5.
- A room-occupancy veto on α. Revive when a still-holding radar (ZK/ZX) covers the occupant's rooms.
- A separate `_body_quiet_unsub` timer. Revive if D0 or live data show the 60 s periodic missing discharges (e.g. periodic inference skipped under load).
- A security-specific arm policy. Revive if auto-follow turns out to be live and the operator rejects a ≤ W arming delay.

---

## 11. Tier
**Tier 3** (shared state machine; failure = one missed branch at a time seam). Required:
- a re-verify plan review of Rev 2;
- four framing-disjoint build reviews (A/B/C-mutation/D);
- the orchestrator re-greps every `return HouseState.AWAY` and re-runs one mutation;
- an **operator checkpoint before deploy**, including explicit acceptance of the security auto-arm delay (§3.4);
- the travel rule: risk HIGH, so deploy after 10-18 or in an attended window, with one restart.

---

## 12. Rev 2 — review findings disposition

| Finding | Sev | Change | Where |
|---|---|---|---|
| R2-01 stamp on census_count re-opens GAP-A | HIGH | Stamp on `unidentified_count>0 or face_recognized_count>0` only; INV-NO-BLE-HOLD; BLE-only test + forgotten-phone replay | §1.2, §2, §3.2, D1, C8 |
| R1-01 / R2-02 shared retry slot loses discharge | HIGH | Timer dropped; discharge = 60 s periodic; INV-AWAY-DISCHARGE = B+W+60 s (+ hysteresis ≤120 s); `RETRY_SLACK_S` deleted; hysteresis-blocked discharge test | §1.2, §2, D2, C9, §10 parked timer |
| R1-02 polling consumers + delay price | MED | Six polling consumers added with a per-consumer W-delay cost; security singled out for operator acceptance | §3.4, §11 |
| R1-03 / R2-03 restart under-specified | MED | Option (a): RAM-only, seeded to boot time (conservative, never early AWAY); cold-boot default fenced | D1, §10 |
| R2-04 two clocks | MED | One clock, `dt_util.utcnow()`, captured once per `_run_inference`; `infer(now=)` convention preserved | D1, D2 |
| R2-05 veto label lost/masking | MED | Set inside `infer()` after the reset; memory writer classifies `body_quiet_hold`; first-denial precedence | D2 |
| R2-06 producer/computation unanchored | MED | Mutation anchors for the stamp write, BLE exclusion, `>=` boundary, W==0 | D2 tests |
| R1-04 boot seed bypass | LOW | Resolved by camera-only stamp + boot-time seed; no stamp at the seed (documented) | D1 |
| R1-05 three override selects | LOW | Canonical named, siblings listed | §1.2, §6, §10 |
| R1-06 / R2-08 estimator exit shrink | LOW | Slice = plain window; D6 adds shrink on the same knob; effect noted | §8 |
| R1-07 fence AWAY setters outside infer() | LOW | Explicit fence list + test | §10 |
| R2-07 knob ownership | LOW | CONF key, owning entry, entity_id, unique_id, options-write-back persistence named | D3 |

**Rejected:** none. **Partially adapted:** R1-03 offered "persist on each stamp change" as an alternative. Rejected in favour of no persistence, because a Store save on every camera update is a write-amplification risk (the DB/Store write-flood history) for no safety gain over the conservative boot seed.
