# CRITIQUE: CENSUS-OCCUPANCY-ESTIMATOR-1 (hybrid head-count estimator + guests-present flag)

**Mode:** plan critique (Mode 2). No code, no new plan. Written 2026-10-18 by ura-planner.
**Card:** `docs/planning/kanban.data.yaml:31951`. **Plan under critique:** `PLANNING_census_occupancy_estimator.md` (round 6, 2026-10-04).
**Operator instruction (verbatim, 2026-10-18 03:50Z):** "Make sure a) Its needed b) It solves the problem c) We can think through all the unintended consequences. Also what does the held count solve?"

**Read completely first:** `IDENTITY_FUSION_CAMERAS_MANUAL.md`, `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`. Also read: the estimator plan (all 742 lines), `AUDIT_census_estimator_replay_2026_10_03_hybrid.md`, `PLANNING_census_inputs_first.md` (R2/R3/R4 sections and the D3 verdict), `AUDIT_away_flap_untracked_occupant_would_have.md`, `AUDIT_guest_mode_fp_2026_10_17.md`, `PLANNING_house_away_flap_untracked_occupant.md` (knob section), and the cards CENSUS-GUEST-FLOOR-1, CENSUS-ACCURACY-1, CENSUS-GROUND-TRUTH-CSV-FIX-1, CENSUS-INPUTS-FIRST-1, HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1, GUEST-FP-RESIDUALS-1. Presence-doc corrections ledger respected (no claim here relies on path alpha reading `census_count`; §10 #12).

## Verdict: PARK the estimator. SIMPLIFY into two things that already have homes.

The estimator would not do the jobs people expect of it today. The useful part of its design, a held count that blocks AWAY, is already being built more simply by the AWAY-flap card. The camera-less bedroom gap is filled better by a guest-room / still-radar AWAY veto than by a door tally. The parts that are genuinely new (door tally T, empty anchor, ESTIMATE band, FLOOR written into `total_persons`) are the parts that failed the replay. They would bring stuck-high and phantom-guest failure modes into AWAY, security and guest mode.

**Simpler version (recommended):**
1. **Held count:** the AWAY-flap guard (camera-body recency, W = 10 min, house-side consumers only, HVAC left on its fast path), as the 10-18 would-have audit recommends. That is the estimator's `M_cam` collapsed to one bit ("was a body seen in the last W min"). Card: HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1.
2. **Bedroom fill:** add one more AWAY-veto input: a guest room (`CONF_ROOM_IS_GUEST_ROOM`) that is occupied by its still-holding presence radar with no known person in it. This is the estimator's `U_gr` term without the rest of the estimator. Fold it into the AWAY-flap plan as a deliverable, or give it a sibling card. Do not use the door tally.
3. **Guests-present flag (D5) as a separate, later question.** Making guest status orthogonal to house state (so SLEEP + guest is legal) is real design value and does not need a head count. Path (b), the guest-room gate, is already the only thing that arms GUEST today. Re-card it only if the operator wants SLEEP-with-guest behaviour.

**Revival trigger for the full estimator (park, do not delete):** any one of these.
- (a) A consumer appears that needs a number above 1, not just "anyone home": party-size HVAC, occupancy-scaled ventilation, or a capacity alert.
- (b) Door `person_id` attach for residents stays at or above 70% for 14 days. That is the minimum where unattributed crossings stop being mostly residents (today: 29-31%).
- (c) A D0 re-replay with the fixed inputs passes gates 2, 3 and 5 against the corrected 10-03 fixture. This needs CENSUS-GROUND-TRUTH-CSV-FIX-1 answered and `M_cam` redefined as the per-area instantaneous max with a short hold.

## a) Is it needed?

**Who would read a head count, and what they do today without it** (code verified on develop):

| Consumer | Reads today | What a FLOOR would change | Need for a count > 1? |
|---|---|---|---|
| AWAY inference, path alpha | trackers away + `unidentified == 0` + `face == 0` + camera fleet not dark (`presence.py:1170-1181`). It does not read `census_count`. | Plan D6-1/D6-2/D6-6/D6-7 add `FLOOR > R` blocks AWAY | No. "Is anyone here" is a boolean. |
| GUEST arming | **Only** the guest-room gate (`presence.py:6067-6082`, `guest_armed = guest_room_gate_armed`). The census (Path A) has not armed GUEST since 2026-08-16. | Plan D5 (a) **adds** a census-driven arming path (`guest_estimate >= 1`) | No. And see (c): it adds false-positive risk. |
| HVAC | Zone vacancy per room. GUEST maps to the "home" preset (`hvac_const.py:1293`), rollout zones = [zone_3] | Indirect, through house state | No. HVAC already moves 69% of zone-episodes to Away on its own vacancy before the house edge (would-have audit §4.1). |
| Security | `_HOUSE_STATE_TO_ARMED` (`security.py:173`). Auto-follow is **OFF** live (`security.py:1094`) | D6 merges SECURITY-CENSUS-UNKNOWN-WIRE-1 (security reads FLOOR) | No, and it is inert today. |
| NM exterior-person severity | house state (`const.py:2295, 2389`) | Indirect | No. |
| `persons_in_house` sensor, dashboards, PWA | `total_persons` snapshot (`sensor.py:3636`) | Shows FLOOR | Display only. |

**Quantifying the problems the card names:**
- **"Mixes up residents and guests, pushes the house into guest mode by mistake":** largely solved upstream. The name-space dedup (v5.103.47) cleared the last census-driven GUEST flips. Since 10-04 there were 25 GUEST entries over 11 days (URA DB `house_state_log`, read-only, 2026-10-18). All of them come from the guest-room gate. A long-stay guest has been in residence, and `AUDIT_guest_mode_fp_2026_10_17.md` concluded the 10-17 GUEST was plausibly correct. No census-driven false-positive population is left for the estimator to fix.
- **AWAY flapping with an untracked occupant:** real. Trip: 65 AWAY entries in 78.8 h. Baseline: 3.2 per day. This is the problem the estimator's FLOOR was later borrowed for. It is a one-bit problem, and the AWAY-flap card owns it.
- **Party under-count (CENSUS-GUEST-FLOOR-1, "reads 4 with 10 in the house"):** real, but no trust consumer reads the count. It is a display error.

**Conclusion (a):** no current consumer needs a head count. Two consumers need a reliable "someone is here" bit (AWAY) and a reliable "a non-resident is here" bit (guest), and each has a simpler producer.

## b) Would it solve the problem?

**The estimator's own gate failed and was never re-run.** D0-REPLAY on 10-03 (`AUDIT_census_estimator_replay_2026_10_03_hybrid.md:55-65`):

| Gate | Needed | Got |
|---|---|---|
| G2 FLOOR ≤ truth | ≥ 95% | **64%** |
| G3 household-norm \|err\| ≤ 1 | ≥ 90% | **81%** |
| G5 residents only → guest_estimate 0 | ≥ 90% | **30%** |
| G4 party band | | passes only because phantom T (≈9-10) happened to equal the party size. With phantoms removed it drops to 8%. |
| 14:20 group of 8, front-door entries surviving | ≥ 6 | **0** |

Inputs-first then fixed door dedup and direction (31/31) and raised attach. It also showed that G5 was caused by the **held count itself**: the 1200 s windowed max promotes brief cross-camera double counts into a sustained 4-5 while the live census read 3 (`PLANNING_census_inputs_first.md:274, 343, 455`). The hybrid replay has not been re-run on the fixed inputs (no `*_rerun.md` exists). The card is still blocked on the CSV answer key.

**The current producers set its error floor** (measured 2026-10-18, URA DB `person_entry_exit_events`, 10-04 → now):
- Door `person_id`: entries 59/206 (29%), exits 45/143 (31%, including the late exit backfill). Guests are never named, and Jaya and Ezinne are not enrolled in Protect. About 70% of crossings therefore reach the tally unattributed. Most of them are residents, because residents make most crossings.
- The fallback attribution in the plan's pipeline is a tracker edge within ±120 s. It covered 19% of crossings in D0 §P3. A resident whose phone stays `home` (porch trips, garage runs) never produces an edge, which is the dominant 10-03 failure (T reached 8 by 13:00 on resident activity alone). Inputs-first named this residual "irreducible without a new input source" (`PLANNING_census_inputs_first.md:99`).
- Interior cameras cover common areas only: Living Room and Upstairs Hallway as room cameras, plus hallway and stair Frigate counts. There are none in bedrooms, bathrooms, Kitchen, Study or Garage (would-have audit §3).
- WiFi guest phones are excluded by design. The one persistent guest phone on 10-17 had an empty hostname, so `_get_wifi_guest_count` (`camera_census.py:5649`) skips it anyway (guest-FP audit re-probe §1).

**Does it fix the camera-less bedroom gap?** Only through `U_gr`, which the simple version keeps.
- **`M_cam`:** blind to bedrooms. It is the same input as the AWAY-flap guard, so it covers the same 23%.
- **Door tally T:** it says "someone is inside" only if an unattributed entry happened since the last empty anchor. During the trip, 51 of 65 AWAY entries had no crossing at either end, so T could have been non-zero by luck only (an earlier unnamed entry not offset by an unnamed exit). That is the same mechanism that makes T stuck-high on resident-only days. It cannot tell "the guest came in this morning" from "Jaya's unnamed garage entry at 07:00 and her named exit at 07:33". Its right answers would come from errors cancelling.
- **`U_gr`:** guest-room sustained unknown occupancy. This is the term that would actually have held the house home: Guest Bedroom 2 was occupied for 487 of the trip's all-phones-away AWAY minutes. It is also the simple fill.

**Expected error, plainly:** on a normal 1-3 person day, FLOOR within ±1 about 80% of the time, over-counting rather than under-counting (G2 64%), and phantom guests on most resident-only mornings. These are the latest measured numbers. A re-run on fixed inputs might improve G2 and G3, but G5's cause (the held max) and T's cause (unattributable resident crossings) are structural.

## c) Unintended consequences

1. **Guest-mode false positives come back (the 08-2026 failure class).** D5 path (a) re-opens census-driven GUEST arming, which was removed on 2026-08-16 after ~50 spurious entries. With G5 at 30%, a residents-only morning would light `guests_present` most days. HVAC zone_3 would go to the guest/home preset, Bayesian learning would be suppressed (`__init__.py:3325`), occupancy-anomaly alerts would be suppressed (`binary_sensor.py:3418`), and NM severity would change.
2. **Stuck-high FLOOR and lost AWAY on real departures.** Phantom T only clears through (i) the empty anchor (R = ∅, M_cam = 0, U_gr = 0 held for 900 s) or (ii) tally age-out, which runs only after 3600 s with **no camera body**. While anyone is home, residents keep cameras busy, so (ii) rarely runs. On 10-03 the anchor never fired. A day of phantom T then blocks AWAY (INV-AWAY-SAFE) when the family leaves, until the anchor settles (20 min held max + 15 min anchor + 10 min boot settle after a restart). It blocks forever if a long-stay guest's room keeps U_gr = 1. HVAC is mostly unaffected (zone vacancy), but the house-side consumers (lights sweep, NM CRITICAL exterior severity, a future auto-arm) lose AWAY.
3. **Residents double-counted.** R is subtracted only from the camera term. A resident's unattributed crossing becomes a guest in T while the same resident sits in R, which is the 10-03 midday case. The guest-side `max()` stops guest-on-guest double counting but not resident-as-guest.
4. **Still guest erased (accepted, ruling 14).** The anchor erases T when a phoneless guest is still and out of view. With a long-stay guest this is the common case overnight, not "rare": the 10-03 overnight FLOOR was 3 against a truth of 4.
5. **Restart behaviour.** The plan persists T, B, the `M_cam` peak and in-flight priors through RestoreEntity extra data. A restored phantom T carries across restarts. Door events during downtime are lost, so an exit while HA was down leaves T permanently high until the anchor. This repeats the RestoreEntity stale-state class (memory `project_envoy_boot_incident_2026_06_12`). The house-state store already has its own 1800 s staleness rule, so the system would have two restore clocks.
6. **Security.** Merging SECURITY-CENSUS-UNKNOWN-WIRE-1 makes security read FLOOR. A stuck-high FLOOR silently disables auto-arm on a real departure. Auto-follow is off today, so this is latent, but it is a trap for whoever turns it on.
7. **Blast radius for little gain.** The D6 table changes 21 read sites of `total_persons` / `census_count` (SLEEP→WAKING forcing at `presence.py:6530`, boot settle, anomaly z-score, interlocks, the DB writer). The DB writer change is a Tier 2-DB trigger. D5 changes 16 GUEST readers. That is a Tier-3 cross-coordinator ripple at a state-machine × time seam, the ingredient profile the marginal-benefit rule warns about.
8. **Config surface.** At least 8 new per-install fields or knobs: door groups, main entry door, interior neighbours, approach cameras, overlap groups, Revel deny/allow, two P-AMB windows. Several have no other consumer, against the parsimonious-config rule.
9. **Privacy.** Low incremental risk. T is an anonymous tally, and no new identity is produced. The WiFi leg (D4), if revived, would keep a per-device guest history, which matters with CENSUS-GUEST-FLOOR-1's "known guest device" lifetime. Keep that leg out unless separately approved.
10. **Decay mismatch with the AWAY-flap guard.** The AWAY-flap plan reuses the estimator's `FLOOR_WINDOW_S` name and 1200 s default. The would-have audit recommends 10 min. If the estimator later lands with 1200 s, it silently re-lengthens the departure delay. Decouple the knobs: the AWAY guard owns its own W.

## d) What does the "held count" solve?

**What it is.** In the plan, `M_cam(t)` is the **highest** de-duplicated interior-camera body count seen in the last `FLOOR_WINDOW_S` (20 min). It is not the current count (§7.2). FLOOR uses that remembered peak. So if a camera saw two people at 14:00 and nobody since, FLOOR still says two until about 14:20, or sooner if a door exit is observed (the shrink to 180 s).

**The failure it targets.** Cameras see people only while they walk through common areas. The instantaneous count therefore drops to 0 the moment someone goes into a bedroom, bathroom or the kitchen, and path alpha then declares AWAY. The held count is a short memory that bridges "out of view" gaps, so a person who was just seen is not declared gone. It also smooths bursty per-camera counts (L8 in the plan).

**What it does not solve, measured:**
- People who stay out of view longer than the window. Would-have audit: cameras saw a body inside only 1 of 65 trip AWAY episodes. The 3 long episodes (about 240 min each) are only shifted by about 20 min, and 344 of 347 camera-blind Guest Bedroom 2 minutes stay AWAY.
- It creates over-counts. Holding a max across cameras turns brief simultaneous sightings of one person on two cameras into a sustained extra body. This is the root of the G5 30% (inputs-first R2.4). A 20-min max is a lower bound on the people present only if each sighting is a distinct person, and it is not.

**Simpler alternatives, by marginal benefit:**

| Option | Captures | Marginal risk | Verdict |
|---|---|---|---|
| Camera-body recency bit, W = 10 (AWAY-flap guard) | 31/34 of the W = 20 absorptions (trip), 116/136 (baseline). Kills the short-flap churn. | One stamp. No count arithmetic. House-side only. | **Build (already carded).** |
| + guest-room radar AWAY veto (`U_gr` alone) | The bedroom gap. Guest Bedroom 2 occupied for 487 of the AWAY minutes. | MS600 radar holds a still person (SENSOR_FLEET_CLASSES). Fan phantoms on that room unmeasured; restricting to guest rooms avoids the Kitchen radars (17.6 h phantom on the trip). | **Simplify into the AWAY-flap plan.** Needs a fan check on GB1/GB2 first. |
| + door tally T | Adds information only when an unattributed entry is not later offset. About 70% of crossings are unattributed residents. | New persisted accumulator, stuck-high, restart drift, 8 config fields. | **Do not build.** Marginal benefit is about 0 or negative at 29-31% attach. |
| Full hybrid FLOOR into `total_persons` + D5 flag | Party-size number (display) | Tier-3, 37 read sites, re-opens census-driven GUEST | **Park** with the triggers above. |

A count-valued held max (rather than one bit) adds value only for a consumer that needs N > 1, and none exists.

## Card hygiene recommended (for the orchestrator, not applied here)
- CENSUS-OCCUPANCY-ESTIMATOR-1 → `parked`, revival trigger as above. Its current `next` (waiting on the CSV answer) should not be read as "will build once the CSV is fixed".
- HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1: (i) own its window knob (rename from the estimator's `FLOOR_WINDOW_S` / "Count memory", default 600 s per the audit); (ii) add the guest-room radar veto as a candidate deliverable, gated on a fan-phantom measurement for GB1/GB2 MS600 Matter occupancy.
- CENSUS-ACCURACY-1: its "fold decay into the estimator" note (10-16) no longer holds. Keep its 4 registry-bypass sites; drop the decay leg, which the AWAY-flap guard supersedes for the AWAY consumer.
- CENSUS-GUEST-FLOOR-1 (revived 10-17): keep it display-and-corroborator only. It must not feed AWAY or GUEST arming without its own measured false-positive rate.
- CENSUS-GROUND-TRUTH-CSV-FIX-1: no longer on a critical path. Leave it waiting_operator at low rank.

## Evidence index
- Code: `presence.py:1170-1181` (path alpha), `:6067-6086` (GUEST = guest-room gate only), `:5485` (`_guest_room_gate_armed`); `security.py:173, 1094`; `hvac_const.py:1293`; `camera_census.py:5649`. No `census_estimator` or `FLOOR_WINDOW` symbol in the tree (grep 2026-10-18).
- DB (read-only, `ssh ha`, `?mode=ro`, 2026-10-18): crossings since 10-04: entry 206 (59 named), exit 143 (45 named); GUEST entries 25 over 11 days.
- Audits: replay gates (`AUDIT_census_estimator_replay_2026_10_03_hybrid.md:55-75`); held-max artefact (`PLANNING_census_inputs_first.md:274, 343`); trip numbers (`AUDIT_away_flap_untracked_occupant_would_have.md` §0, §3, §6); GUEST 10-17 producer (`AUDIT_guest_mode_fp_2026_10_17.md` §1, §3).
