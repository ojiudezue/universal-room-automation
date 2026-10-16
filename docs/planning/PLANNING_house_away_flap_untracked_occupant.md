# PLANNING — House AWAY flap with an untracked occupant home

**Card:** HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1
**Status:** DRAFT for operator review, 2026-10-16 (overnight, read-only pass). No code changed. Needs two Tier-3 plan reviews (completeness + adversarial build-prediction) before any build.
**Author:** ura-planner.
**Operator instruction on the card:** "Tell me what the plan is. I want careful plans. But make sure it context and prior art aware."

---

## 0. The plan in one paragraph

When no tracked phone is home, URA declares AWAY the moment the interior camera stops seeing a body, even though the camera saw one seconds earlier. Two AWAY branches do this: path α and the plain "nobody home" branch. The 3-minute census hold that looks like it should prevent this has no effect on this edge, because a later clamp cuts the held count back to the live camera count (§3.2, new finding). Recommendation **(B)**: add one guard shared by all three AWAY branches in `StateInferenceEngine.infer()`. No AWAY until the house has gone `Count memory` seconds with no camera body. Discharge it with a timer so a genuinely empty house still goes AWAY on time. Use the knob name and default (1200 s) the census-estimator plan already chose, so its later D6 swaps in a different input and nothing is rebuilt. Measured effect: it would have absorbed about 114 of the 119 short AWAY episodes over the last 59 normal days, and about 28 of the 44 during the trip. Real departures get to AWAY up to 20 minutes later. Until it ships, the only lever is the house-state override (§6).

---

## 1. Institutional context verified (MANDATORY)

### 1.1 Mandatory docs read, completely, before writing
- `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (all sections, corrections ledger §10). **Contradiction found (§9 C1):** its §2 says path α requires `census_count == 0 AND all_zones_away`. The code says otherwise.
- `docs/architecture/SENSOR_FLEET_CLASSES.md`: not re-litigated. This plan does not touch sensor classes. Room sensors are an input only through `any_zone_occupied`.
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (all, incl. §10 C1–C38): HVAC consumes house state at `hvac.py:5177` `_handle_house_state_changed` (the doc's `:3260` is stale; the code wins). No §10 claim is re-asserted.
- `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`: census arithmetic (§4.2), the graceful-anonymous doctrine (§3.6), and the rule that `person_id` is advisory. This plan uses no identity input (INV-NO-NAME holds).
- `docs/QUALITY_CONTEXT.md`: the relevant classes are Bug Class #53 (computed-but-not-consumed / one missed site; here the three AWAY branches), stale-data-source #7, and "suppression needs a discharge" (memory `feedback_suppression_needs_discharge`).

### 1.2 Prior-art scan: REUSE or BUILD, per piece

| Piece | Verdict | Evidence |
|---|---|---|
| Interior body evidence per tick | **REUSE** | `PresenceCoordinator._handle_census_update` `presence.py:4739-4815` already reads `interior_count` → `_census_count` and `unidentified_count` → `_unidentified_count` on every `SIGNAL_CENSUS_UPDATED`. |
| "Last time a body was seen" timestamp | **BUILD (one field)** | No equivalent. Grep of `presence.py` / `camera_census.py` / `const.py` for `last_body`, `body_seen`, `last_nonzero`: nothing. `_peak_house_timestamp` (`camera_census.py`) is a peak-promotion stamp, not a last-seen stamp (it is deliberately not refreshed on equality, `camera_census.py` ~5375 INV-PEAK-NO-SELF-REFRESH). |
| Held camera max (the concept) | **REUSE the estimator's design** | `PLANNING_census_occupancy_estimator.md` §7.2 `M_cam` over `FLOOR_WINDOW_S`. "Body seen within W" ⇔ `M_cam > 0` when R = 0. The slice is the R = 0 projection of D6's INV-AWAY-SAFE. |
| Knob for the window | **REUSE the name and default** | Estimator §7.10: `FLOOR_WINDOW_S` → Number "Count memory", rung 3, default 1200 s. This plan creates exactly that entity early. D6 inherits it. |
| Existing census hold | **REJECT as the lever** | `_apply_hold_decay` `camera_census.py:5292`, `CONF_CENSUS_HOLD_INTERIOR` = 3.0 min live (`.storage/core.config_entries`, read 2026-10-16). Neutralised on this edge by the GUEST-CENSUS D1 clamp (§3.2). |
| Tick-count debounce | **REJECT** | `_external_empty_consecutive_ticks` / `sustained_external_empty` (`presence.py` ~6395-6410, N = `CONF_LOST_AWAY_INDOOR_CLEAR_TICKS` = 3). It counts inference calls, not seconds. Census updates arrive every ~60-90 s, so 3 ticks ≈ 1-3 min. Measured AWAY-entry gaps are 0-3 min in most cases (§4), so a tick count can't be tuned to this. |
| Arriving re-arm cooldown | **REJECT (does not apply)** | `ARRIVING_REARM_COOLDOWN_S = 900` `presence.py:221` (B-2026-08-03-2) suppresses re-arming after a FAILED arrival. Most trip arrivals succeeded (`arriving→home_day`, `house_state_log`). |
| State-machine hysteresis | **REJECT** | `DEFAULT_HYSTERESIS` `house_state.py:~130`: a minimum dwell IN a state, not an AWAY-entry confirmation. Module dict, no knob, constructed bare at `domain_coordinators/manager.py:225`. Raising HOME_DAY dwell would delay every state change. |
| Deferred retry (discharge timer) | **REUSE** | `_schedule_deferred_retry` `presence.py:5107-5122`, which already re-runs `_run_inference("deferred_retry")`. |
| Away veto kill switch | **REUSE as rollback only** | `switch.ura_presence_coordinator_away_confirmation_veto` (live **on**, read 2026-10-16). Backing `_away_veto_enabled`, `switch.py:3880`. Coerces α/β off (`presence.py` ~6470-6487). |
| House-state override | **REUSE (interim)** | `select.ura_presence_coordinator_house_state_override` (live **auto**, last changed 2026-10-15 12:46 CDT). |

Greps run (2026-10-16): `grep -n "census_count == 0\|unidentified_count == 0\|all_tracked_persons_away" presence.py`; `grep -n "HYSTERESIS\|hysteresis" const.py config_flow.py number.py` (no house-state hysteresis knob); `grep -n "CONF_LOST_AWAY\|AWAY_DWELL\|AWAY_SETTLE\|AWAY_CONFIRM\|CENSUS_HOLD_INTERIOR" const.py` (no AWAY-entry dwell knob exists); `grep -rn SIGNAL_HOUSE_STATE_CHANGED` (consumer list in §3.4).

### 1.3 Prior plans and cards consulted
- `PLANNING_census_occupancy_estimator.md` (round 6, read fully). D6 = FLOOR into the AWAY guards; INV-AWAY-SAFE; INV-NO-LATCH; anchor-erasure ruling 14. **Gap found (§9 C6):** D6's migration table has no row for path α.
- `DESIGN_census_simplification.md`, `PLANNING_census_inputs_first*.md`: skimmed headers only. The estimator is blocked on inputs-first and the ground-truth CSV.
- Cards PATH-ALPHA-DENOM-1, GUEST-FP-RESIDUALS-1, CENSUS-ATHOME-RESIDENT-CORROBORATOR-1, HVAC-PRESET-FLAP-1, CENSUS-INPUTS-FIRST-1: card text only (adjacency already swept on the card, verdict NEW; not re-run).
- BACKLOG B-2026-08-03-2 (arriving cooldown): see the table above.

### 1.4 Memory bodies
Memory index lines for `project_guest_mode_false_positive_backlog`, `project_presence_guest_latch_and_veto_gap`, `feedback_suppression_needs_discharge`, `feedback_marginal_benefit_pushback`, `feedback_measure_before_build`, `feedback_config_first_before_code`, `project_operator_travel_2026_10_15`. **Full bodies were not pulled this pass; reviewers should pull them.**

### 1.5 Code read end-to-end for this plan
`presence.py:1000-1300` (`infer`), `:4739-4815`, `:5107-5122`, `:6380-6510`; `house_state.py:60-175`; `camera_census.py:2440-2535`, `:5265-5470`, `:5464-5650`, `:5903-6045`.

---

## 2. Falsifiable invariant

> **INV-AWAY-QUIET:** In any reachable path, `infer()` never returns `HouseState.AWAY` (from the nobody-home branch, path α, or path β) at time t if a census update in `[t − W, t]` reported `interior_count > 0` or `unidentified_count > 0`, where W = live `Count memory` > 0. **And INV-AWAY-DISCHARGE:** if every AWAY conjunct holds continuously and no body is reported after `t_last_body`, AWAY is returned no later than `t_last_body + W + RETRY_SLACK_S` without needing any further external event.
> **W = 0 ⇒ byte-identical** to today on every path.

How D falsifies it: a branch that returns AWAY without the guard (one missed site, Bug Class #53); a restart that loses `t_last_body`; a census payload path that skips `_handle_census_update`; a guard satisfied but no timer armed (the house stuck HOME forever).

---

## 3. Producer and consumer checks

### 3.1 Which branch fires (code, `presence.py:1127-1270`)
1. **Nobody home** `:1127`: `census_count == 0 and not any_zone_occupied`. Confidence 0.9.
2. **Path α** `:1169-1180`: `not camera_input_degraded and all_tracked_persons_away and unidentified_count == 0 and face_recognized_count == 0`. **No census_count term and no zone term.** Confidence 0.95.
3. **Path β** `:1248-1270`: `all_trusted_or_lost_away_persons_away and unidentified_count == 0 and census_count == 0 and not indoor_blocked and grace… and not sleep_exempt_state`. Confidence 0.95.

Measured (`house_state_log`, confidence used to tell branch 1 apart from 2/3): trip 10-14 = 22 α/β + 11 nobody-home; 10-15 = 2 + 9. **A fix to path α alone would have left most of 10-15's flaps in place.** All 59 AWAY entries in the 7-day recorder window had every `person.*` not_home at entry (recorder join, §4).

### 3.2 PRODUCER of `interior_count` / `unidentified_count` — why the 3-min hold does nothing on this edge
`camera_census._apply_enhanced_house_census` (`:5903-6040`):
- `held_unidentified` = `_apply_hold_decay(camera_unrecognized, "house")`. The 3-min hold IS computed.
- Then the GUEST-CENSUS D1 clamp runs: `raw_total_ceiling = max(camera_total_pre_cancel, identified_count)`, `clamped_total = min(identified + held, ceiling)`, `unidentified = clamped_total − identified`.
- `camera_total_pre_cancel` is **instantaneous**: it is summed from the current `person_count` sensor states in `_get_unrecognized_camera_count` (`:5515-5578`, assigned `:5577`).
- With every resident away, `identified_count = 0`. When the camera reads 0, the ceiling is 0, so `unidentified_count = interior_count = 0` on the same tick, whatever the hold says.

Ground truth that fits this (`census_snapshots`, house zone, 10-14 UTC): `14:16:42 total=1` → `14:17:58 total=0` → `house_state_log 14:17:59 away 0.95 census_update`. That is 76 s after a body, inside the 3-min hold. Snapshots track the raw camera with no hold on every flap in 14:00-15:30.

Dependency health: Frigate interior `person_count` is healthy (it counts the guest). Face recognition is irrelevant here (`face_recognized_count` = 0 and stays 0). The clamp is correct for its purpose (stopping guest inflation) and is **not** changed by this plan.

### 3.3 PRODUCER of `any_zone_occupied`
Zone tracker rollup of room occupancy (`presence.py`, PoP §1). On 11+9 nobody-home AWAYs it was False, so no room sensor held the occupant. Who the occupant is and which rooms they used: **not verified.**

### 3.4 CONSUMERS of an AWAY edge (`SIGNAL_HOUSE_STATE_CHANGED`, grep 2026-10-16)

| Consumer | file:line | Trust or display | Harm per false AWAY edge |
|---|---|---|---|
| HVAC presets | `hvac.py:1437` subscribe → `:5177` `_handle_house_state_changed` | trust (writes thermostats) | Zones 2/3 home↔away preset flips (card: 54 / 38 changes on 10-14). The occupant sits at an away range. |
| Room automation (incl. the Away leave-on lights sweep) | `coordinator.py:1739` | trust (actuates lights) | Can sweep lights off on the occupant. Configured rooms: **not verified.** |
| Security auto-follow | `security.py:749` / `:1077`; debounce `SECURITY_AUTO_FOLLOW_ARM_DELAY_S = 30` `const.py:3151` | trust (arming) | A 30 s debounce does not absorb 4-15 min flaps. Whether auto-follow arming is enabled live: **not verified.** Highest-stakes consumer. |
| Bayesian guest listener | `__init__.py:3313-3329` | learning | Pollutes learning. |
| Music following | `domain_coordinators/music_following.py:301` | trust (media) | Minor. |
| Routine forecaster | `routine_forecaster.py:188` | learning | Pollutes the forecast. |
| Arrester durable-state | `hvac_override.py:1010` | trust | Ends immune holds on durable state change. |
| Energy | `energy.py:8050` (`_get_house_state`, polled, offset reset) | trust | **Not traced further.** |
| Sensors | `sensor.py:6573`, `:10326` | display | None. |
| EVSE / battery | no direct subscription found by grep | n/a | Card claim "EVSE, battery" is **not supported by the grep**. They may read state indirectly (not verified). |

---

## 4. Measure before build (read-only, run 2026-10-16)

Sources: URA DB `house_state_log` and `census_snapshots` (house zone, ~60-90 s cadence, retained from 07-17) via `ssh ha sqlite3 -readonly` / `python3 -` (scripts in `.claude/tmp/awayflap/`); HA recorder `person.*` (7-day retention).

| Measure | Baseline 08-16 → 10-13 (59 d) | Trip 10-14 12Z → 10-16 |
|---|---|---|
| AWAY entries | 162 (≈2.7/day; max 13 on 09-28; ≥8 on 4 days) | 44 (33 on UTC 10-14, 11 on 10-15) |
| AWAY episodes < 15 min | **119 (73 %)** | 27 |
| AWAY episodes < 5 min | 93 | 15 |
| Short (<15 min) by branch: α/β vs nobody-home | 94 / 25 | 15 / 12 |
| Camera body seen < 3 min before AWAY entry | 143 / 162 | 37 / 44 |
| Short episodes a W-min body guard would absorb: W = 5 / 10 / 15 / 20 | 60 / 102 / 111 / 113 | 9 / 19 / 25 / 25 |
| All AWAY episodes absorbed at W = 20 | 114 / 162 | 28 / 44 |
| AWAY entries with any `person.*` home (7-d recorder) | 0 of 16 | 0 of 44 |

Read-out:
1. **This is not trip-only.** Short AWAY flaps happen about twice a day in normal life: ~119 in 59 days, ~73 % of all AWAY entries. The trip made them about 10× more frequent. That answers the operator's "how often outside trips": every day.
2. A **15-20 min** window catches almost all baseline short flaps. **W = 5 min catches only half.**
3. During the trip, **~16 of 44 AWAYs survive even W = 20.** The occupant went more than 20 min with no camera and no room sensor seeing them. Camera memory alone cannot fix those. They are the estimator's door-tally (T) territory.
4. **Cost.** About 43 real (≥15 min) AWAY episodes in 59 days, nearly all preceded by a body on camera within 3 min. Each would reach AWAY up to W later: about 0.7 delayed departures a day × ≤20 min of extra conditioning and later arming.
5. The simulation approximates the episode duration as the re-arrival gap, and snapshot sampling (~75 s) under-samples body sightings. So these are estimates; "absorbed" may be slightly understated.

---

## 5. Marginal-benefit decomposition

| Option | Benefit | Ingredient risk | Verdict |
|---|---|---|---|
| **(A) Do nothing until estimator D6** | 0 now. D6 is blocked on inputs-first plus the CSV, then D3 shadow plus D5, so months away. **As written, D6 would not fix path α** (§9 C6). | None now. ~2 false AWAY/day persist for months, and ~20 preset flips per zone per trip weekday. | Reject. The problem is daily, not trip-only. |
| **(B) Narrow slice: body-recency guard on all 3 AWAY branches, knob = estimator's "Count memory"** | ~70 % of all false AWAYs (114/162 baseline). Biggest component, simplest form. | One new timestamp and one guard inside a state machine consumed by HVAC, security and lights (Tier 3). Time seam: needs a discharge timer. No new writer to a shared primitive. No change to the census payload or the clamp. | **RECOMMENDED.** |
| (B′) Fix the clamp to use a held ceiling | Same AWAY benefit, plus the census sensors stop flickering. | Changes `unidentified_count` / `interior_count` for EVERY consumer: the guest gate (GUEST false positives, the exact bug the clamp fixed), DB snapshots, NM, D6 table rows. Much wider blast radius for the same AWAY margin. | Park. Revival: estimator D3 decides the held ceiling anyway. |
| (B″) Full estimator FLOOR now | Adds T (door tally) for the >20-min out-of-view residue (~16 trip AWAYs). | Everything in the estimator plan (persisted tally, anchor, attribution). Blocked on inputs. | Not now. That is D6. |
| **(C) Config only** | Override `guest` (or `home_day`) holds the house. It fixes trip days entirely and does nothing for the daily baseline. | Blunt: stops evening/night/sleep progression and must be reset to auto by hand. `CONF_CENSUS_HOLD_INTERIOR`: **no effect** (§3.2 clamp). Away-veto switch OFF: kills α/β only. On 10-15, 9 of 11 AWAYs came from nobody-home, and it removes the phantom-camera defence α was built for. | Interim only, operator's call (§6). |

Margin: (B) captures most of what is achievable without door flow. (B″) adds the ~16-episode residue at the cost of the whole estimator. The parked alternatives in §10 record when to revisit.

---

## 6. Config-first check

- `select.ura_presence_coordinator_house_state_override`: live `auto`. Setting `guest` until 10-18 stops the trip flaps. Blunt, and needs a manual reset. **Operator decision; this pass did not change it.**
- `switch.ura_presence_coordinator_away_confirmation_veto`: live `on`. Turning it off does not fix it (nobody-home branch) and weakens the ghost defence. Not recommended.
- `census_hold_interior` = 3.0 min (`.storage`): raising it does nothing on this edge (§3.2).
- House-state hysteresis: no knob exists.
- `lost_away_*` knobs: unset (defaults 60 / 3 / True); path β only.
- **Conclusion: no setting fixes the daily baseline. Code is required.**

---

## 7. Deliverables

### D0 — Pre-build probe re-run (read-only, ~10 min)
Re-run `p7.py` with event-accurate body times from the recorder (Frigate `person_count` state changes, not 75 s snapshots) to pin the absorbed fraction and the departure-delay distribution for W ∈ {600, 900, 1200}. Pick the default from this table; 1200 stays unless D0 shows a materially smaller cost at 900 for the same absorption.
- **Verify:** an `AUDIT_house_away_flap_body_gap.md` table with absorbed/residual/delay per W.
- **Live:** n/a.

### D1 — Body-recency stamp (producer)
In `_handle_census_update` (`presence.py:4739`), after the counts parse: `if self._census_count > 0 or self._unidentified_count > 0: self._last_interior_body_ts = now` (monotonic and wall time, captured before any await). Persist the wall stamp on the house-state Store payload next to the existing restore (`house_state.py:26-54`, 1800 s staleness bound). On restore, stale → None (None = no recent body; with W > 0 the boot-settle gate still applies). **Entry-reset discipline:** the stamp is never cleared by a 0 count, only aged.
- **Test:** `test_body_stamp_set_on_interior_or_unidentified_positive`, `test_body_stamp_not_refreshed_by_zero`, `test_body_stamp_restored_within_staleness`.
- **Verify (discriminating):** a census update with `interior_count=0, unidentified_count=1` stamps. Under a bug that reads only `interior_count` it would not, so this test tells the two apart.

### D2 — Guard on ALL THREE AWAY branches + discharge (consumer, Tier 3 core)
Add kwarg `body_quiet_elapsed: bool = True` to `infer()`. Default True keeps every existing caller byte-identical (invariant I3 pattern). Each of the three AWAY returns (`:1127`, `:1169-1180`, `:1248-1270`) requires `body_quiet_elapsed`. The caller computes `W == 0 or last_body is None or now − last_body ≥ W`. When an AWAY branch is denied ONLY by this guard, record `self._veto_path = "body_quiet_hold"` and arm a one-shot `_schedule_deferred_retry(last_body + W − now + RETRY_SLACK_S)`. **Do not hand-roll a second timer.** Re-arm on each new body, which supersedes the pending retry.
- **Precedence / ordering:** the guard is evaluated inside the branches, so an AWAY-denied tick falls through to the existing has_people / ARRIVING logic unchanged. In the AWAY state the guard is not consulted (`return None` paths unchanged).
- **Test (per-site mutation anchors, framing C):** `test_nobody_home_branch_blocked_within_W`, `test_path_alpha_blocked_within_W`, `test_path_beta_blocked_within_W`. Each must go RED when its own branch's guard conjunct is deleted. Plus `test_away_fires_at_last_body_plus_W_without_new_event` (discharge, frozen clock), `test_W_zero_byte_identical` (golden over the existing presence AWAY suites), `test_guard_ignored_when_already_away`, `test_new_body_rearms_retry`.
- **Config-extreme:** W = 0; W = max; W < tick cadence; `camera_input_degraded=True` (α skipped, guard still on nobody-home and β); restart mid-window.
- **Verify (discriminating):** with α guarded but nobody-home unguarded (the one-missed-site bug), the 10-15 replay still shows nobody-home AWAYs. The replay assertion counts AWAYs by confidence 0.9 vs 0.95, so it tells a partial fix from a full one.
- **Live:** on the next all-trackers-away-with-occupant day, or the next baseline day, `house_state_log` AWAY entries with an episode < W drop to ≈0. Every AWAY row is ≥ W after the last `census_snapshots.total_persons > 0`. The veto_path sensor attribute shows `body_quiet_hold` during holds. Real departures: the AWAY row lands within W + 120 s of the last body snapshot (discharge proven, no stuck HOME).

### D3 — Knob: Number "Count memory" (`FLOOR_WINDOW_S`)
- **Rung 3** Number on the presence coordinator, persisted via the existing Number-persistence machinery, default **1200 s** (estimator §7.10), range 0-3600, step 60. **0 = kill switch (today's behaviour).** One line: "How long the house must see no one on camera before it can go Away."
- `RETRY_SLACK_S` = 5 s, **rung 1** module const (timer jitter; review-only).
- **Test:** `test_count_memory_round_trip_restore`; `test_count_memory_zero_disables`.
- **Live:** entity exists, value 1200, survives restart.

### D4 — Docs (same commit)
- PRESENCE state-of-play §2: correct path α (C1) and add the D1 clamp note (C4). §10 gets new ledger rows.
- Fix the `house_state.py` AWAY hysteresis comment (card follow-up).
- Estimator plan: add a D6 row for path α and record that D6 replaces D2's input `last_body_ts` with `FLOOR > R` while keeping the same knob (§8).
- README write-back table after live validation.

---

## 8. How the estimator absorbs this with no rework
- Same knob entity (`FLOOR_WINDOW_S` / "Count memory") with the same semantics: a camera-body memory window.
- D6 changes only the caller's computation of `body_quiet_elapsed` (from `now − last_body ≥ W` to `FLOOR ≤ R`). The three guarded sites and the discharge timer stay. D6's mutation anchors are the D2 tests with a new input.
- When D6 lands, `_last_interior_body_ts` is either kept as a FLOOR input or classified KEEP+DOCUMENT in the supersession audit.

---

## 9. Claims found WRONG (record in ledgers)
- **C1:** PRESENCE_STATE_OF_PLAY §2 (and the card's `measured_…` text): "path α = census_count == 0 AND all_zones_away AND …". **Code `presence.py:1169-1180`:** no census_count term and no zone term (GAP-A D8 swapped census_count for `face_recognized_count`).
- **C2:** card `update_2026_10_15`: "AWAY entry already requires census_count==0 AND no zone occupied". Wrong for α; the card's own investigation corrected it.
- **C3:** "path alpha declares AWAY" as the whole mechanism. **33 % of 10-14 and 82 % of 10-15 AWAYs came from the nobody-home branch** (confidence 0.9).
- **C4:** "camera_census `_apply_hold_decay` gives a 3-min interior hold" (task brief, estimator §2.1 row "Hold/decay"). The hold is computed but **the GUEST-CENSUS D1 clamp cancels it on the downward edge** whenever identified = 0 (`camera_census.py` ~5985-5995). Raising `census_hold_interior` would not help.
- **C5:** card "EVSE, battery" as AWAY consumers: no subscription found by grep. Unverified indirect reads only.
- **C6:** estimator plan §6.2.b: the D6 table covers `presence.py:1111` / `:1223` (now `:1127` / `:1251`) but **has no row for path α**. INV-AWAY-SAFE would not hold after D6 as written. Line numbers are also stale.
- **C7:** HVAC state-of-play §2: `_handle_house_state_changed` is at `hvac.py:5177`, not `:3260`.

---

## 10. Non-goals and parked alternatives
**Non-goals:** no change to the census payload, the clamp, the hold, `unidentified_count` semantics, the GUEST gate, path β grace, or hysteresis. No door tally. No identity input. No HVAC change (HVAC simply sees fewer edges). Not solving the >W out-of-view residue (~16 trip AWAYs). Not deciding the trip override.

**Parked:**
- **(B′) clamp on a held ceiling.** Revival trigger: estimator D3 shadow shows held-ceiling FLOOR passes gate 5 (no resident-only guest false positives).
- **Room-occupancy veto on α.** The card's investigation found every room/guest-Wi-Fi signal sparse or always on. Revival trigger: a capability-classed still-holder (ZK/ZX) exists in the rooms the occupant uses.
- **Security-specific longer arm debounce.** Revival trigger: verify auto-follow arming is live and armed during a flap (the next prober should check security events on 10-14).

---

## 11. Tier
**Tier 3.** The house-state machine is a shared primitive consumed by HVAC, lights, security, the arrester and learning, and the failure mode is one missed AWAY branch (Bug Class #53) at a state-machine × time seam that needs a discharge. Required: two plan reviews (completeness re-enumerating every `return HouseState.AWAY` in `infer()` and any AWAY setter outside it; adversarial build-prediction), four framing-disjoint build reviews (A/B/C-mutation/D), orchestrator re-grep plus a mutation check, an operator checkpoint before deploy, and the operator travel rule (risk HIGH → deploy after 10-18 or during an attended window; one restart).

**Open for reviewers:** confirm there is no other AWAY producer outside `infer()` (e.g. vacation/override paths, a `house_state_machine.transition(AWAY)` elsewhere). This was not exhaustively grepped this pass.
