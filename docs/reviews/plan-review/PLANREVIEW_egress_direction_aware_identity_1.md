# Plan review 1 (Tier 3): completeness + framing G — EGRESS-DIRECTION-AWARE-IDENTITY-1

Plan: `docs/planning/PLANNING_egress_direction_aware_identity.md` (develop 9834ace1). Reviewer: ura-reviewer, 2026-11-14.
Framings: (1) completeness, meaning an independent re-enumeration of every site that attaches, vetoes, names or
consumes a crossing identity; (G) goal fidelity against the charter `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`
and the `ura-arc` skill.

I read these in full before reviewing: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`,
`IDENTITY_FUSION_CAMERAS_MANUAL.md` and `HVAC_ARCHITECTURE_STATE_OF_PLAY.md`. This review re-asserts no claim from
any corrections ledger.

Identity model: the plan produces F3 (identity role, later confirmed name) and F5 `camera_egress`, and consumes F1
and F3. The consumer classes it touches are notification, display, comfort, and security/access (D3 gate).

## Verdict: FIX-PLAN

There are four HIGH findings. The most important is goal fidelity (H1). Measured on live data and on the plan's own
labelled fixture, the guards and the abstain rule together name roughly zero to one of the arrivals the plan says it
recovers. The go/no-go gate measures misrecognition only and has no yield floor.

## Findings (severity-ranked)

### HIGH

**H1 (G, goal fidelity): the designed product names almost no arrivals, and the gate cannot see it.**
- *G1 tier.* The plan requires a URA identity tier of at least 0.75. The live D8a outcome log over 31 h
  (`memory_episodes` `egress_identity_outcome`, 79 rows since 2026-11-13 08:25, `ssh ha sqlite3`) has 4 `vetoed`
  rows, and **all 4 are tier 0.6** (single Frigate leg). Of 6 face attaches, 5 are 0.6 and 1 is 0.9. BOOST (0.75)
  needs two engines on one camera, but Protect names have no HA path (manual §2.3), so in practice G1 means two
  cameras at 0.9. Every vetoed crossing in the window fails G1. The "10 measured true cases" are Frigate face scores
  (0.92-1.0, audit `AUDIT_egress_history_labels_2026_11_13.md` :51-71), not URA tiers.
- *Abstain rule.* §5.3 abstains on "any other egress crossing resolved in (crossing_ts, edge]". In the labelled
  fixture:
  - Two of the 10 TRUE cases have no URA row, so no candidate can form (audit :52, :62).
  - Two were already attached (`entry/ezinne`, `entry/oji_udezue`, :53, :55).
  - Of the remaining 6, five have another crossing in the confirm interval: 10-30 19:45 (:51), 11-03 08:36 (:56),
    11-03 22:37 and 22:38 (:57-58, two residents arriving together abstain each other), and 11-08 17:34 (:71).
  - Only 11-07 10:35 (:66) survives, and it still needs tier ≥ 0.75.
- *Gate.* D0 (a)-(e) and the go/no-go (§4, §11 Q1) cover misrecognition and wrong-person confirmations. None of them
  measures projected named-arrival yield.
- *Charter.* "assist arrivals accuracy and personalization" and "It should do both". The risk reductions (G1 at
  0.75, abstain on any crossing) change WHAT is delivered, from named arrivals to nearly none. Under `ura-arc`
  rule 3 that tradeoff goes to the operator. The plan's §1 claim of "zero drift" does not hold.
- **Fix:**
  - Add D0 (f): projected confirmed-name yield per week under G1-G5 plus the abstain rule, broken down by which
    guard or abstain clause removed each true case.
  - Give the go/no-go a yield floor next to the misrecognition ceiling.
  - Narrow the abstain rule. For example, abstain only on another resident's candidate or confirmation at the same
    door group, or only when the confirming edge's person also has a crossing in the interval. Otherwise put
    "group arrivals stay anonymous" to the operator as a named tradeoff.
  - Present the G1 tier distribution and decide with the operator whether a single-leg 0.6 face plus a confirming
    edge is enough to name.

**H2 (completeness): the count follow-up can name a candidate before confirmation; INV-PROVISIONAL misses it.**
- P2-D9's `named` set includes "fresh resident names on the door group's face-name entities" read directly
  (`PLANNING_crossing_vision.md` :376-378), not from the F3 attach. Step 8 then calls
  `notify_arrival_followup(crossing_ref, kind="count", names=..., ...)` (`PLANNING_identity_actions_v6.md` :160).
- A not-home Jaya face on the door camera therefore renders "That was Jaya, and 1 more" with no confirmation. That
  breaks INV-PROVISIONAL and arc map M3(a) ("counts a Phase 2 provisional candidate only after confirmation").
- §5.4's signature `names=()` carries no per-name confidence or basis, so "only at ≥ the notification class
  threshold" cannot be enforced inside the amend function.
- **Fix:**
  - The amend function validates each name against this crossing's record: attached, or confirmed with confidence
    ≥ 0.75. Alternatively, the signature carries `(slug, confidence, basis)` and the function refuses an unconfirmed
    candidate slug.
  - Add "count follow-up names" to INV-PROVISIONAL, with a drill (mutation: skip the check, so
    `::test_count_followup_refuses_candidate` goes RED).

**H3 (completeness): perimeter D10.5 is not "bus `person_id` only"; it has its own pre-existing naming path.**
- `_known_identity_for` reads face legs directly through `census._resolve_face_legs(cam_key)`
  (`perimeter_alert.py:5237-5261`), with no `not_home` veto. A scored leg ≥ 0.9 returns `face_leg`. A below-floor
  face plus a non-face edge returns `face+<src>`.
- `_followup_check` / `_async_send_identity_followup` (`:5519-5589`) then sends a quiet "<camera>: that was <name>"
  for the same door crossing on a dual-role camera.
- §7 says "perimeter D10.5 reads bus `person_id` only (no change, pinned)", which is false. INV-PROVISIONAL lists
  "perimeter D10.5", yet a ≥ 0.9 scored face of a not-home resident names them there before confirmation. A second
  "that was" path also exists beside the "one amend function" (INV-AMEND-ONE is scoped to arrival titles, so the
  operator can get two "that was X" messages for one arrival).
- **Fix:**
  - Correct §7.
  - Decide explicitly whether the D10.5 face-leg branch gets the direction-aware rule, or record it as a named
    residual with the operator's yes.
  - Make the D3 AST test (`::test_no_second_arrival_notify_site`) and the step-8 test
    (`test_r7_and_perimeter_followup_same_crossing`) agree on how the perimeter follow-up is counted.

**H4 (completeness): G5 is labelled REUSED, but its inputs do not exist on the tracker, and the forward half of the
window cannot be observed.**
- `arrival_edges.nonface_arrival_source` needs `tracker_arrivals` (a live `person.*` not_home→home ledger) and
  optionally a Bermuda stamp ring (`arrival_edges.py:269-302`).
- Those live in the perimeter (`perimeter_alert.py:487`, listener `:1030-1035`) and the lock regime, not on
  `EgressDirectionTracker`.
- PersonCoordinator overwrites `previous_location` every tick (presence state of play §1, review A MED-1), so the
  live-data Bermuda leg is visible for about 30 s only.
- G5 runs at t_E + 45 s, so a partner edge in (t_E + 45, t_E + 120] is unseen. For candidates, the §5.3 confirm-time
  abstain partly covers this. For an **attached** entry (`identity_pair_conflict`) there is no re-check, so
  INV-PAIR's ±120 s cannot hold.
- **Fix:**
  - List as NEW: a `person.*` state listener plus ledger and a PersonCoordinator listener plus stamp ring on the
    tracker, each with teardown, or reuse the lock regime's stamps through a public accessor.
  - Specify how the forward window is covered: delay the attached notify to t_E + 120, or re-check and amend.

### MEDIUM

**M1: security-class consumers ignore `identity_pair_conflict`.** On an attached entry the bus `person_id` and
`identity_confidence` (possibly 0.9) are unchanged. The new scoped egress mute
(`PLANNING_perimeter_egress_mute_scoped.md` :49-50, qualifies at ≥ 0.9) and D10.5 (`_note_egress_identity` →
`_known_identity_for` `egress_event`, `perimeter_alert.py:5213-5230`) would still mute or demote on a pair-conflicted
name. "Policy in the consumer" applies, but the plan wires only the notify consumer. **Fix:** state the
security-class rule for a conflicted identity (recommended: not qualifying) and add it to INV-PAIR.

**M2: INV-AWAY-UNTOUCHED contradicts the deltas declared in §5.1.**
- With exit + named zone → `vetoed`, no evict, the slug lingers in the union for up to `EGRESS_FACE_UNION_TTL_S`
  (300 s, `const.py:3388`). `census_count ≥ 1` blocks nobody-home AWAY (presence state of play §2 step 0).
- Legal repro: a named HA zone smaller than and inside `zone.home` (HA picks the smallest containing zone), so the
  resident reads that zone. They enter at t (attached, registered) and leave at t + 120 s; AWAY is held until
  t + 300 s, where the switch-off path evicted at t + 120 s.
- Entry + zone also stops a registration it made before. Either way a census input changes, so the INV as written
  ("no input ... changes") is falsified by the plan's own table.
- **Fix:** restate the invariant as "the switch can never delay AWAY". Keep the evict on a vetoed exit (evicting can
  only speed AWAY), or justify the hold and get the operator's yes against the hard constraint.

**M3: the D4 `camera_egress` dispatch is close to dead and arrives after the arrival.**
- D2 skips raw `home` (`presence.py:5856-5858`) and `phone_already_home` (`:5862-5866`). A GPS fix inside `zone.home`
  normally makes `person.*` read `home` at the same instant. Jaya has no companion GPS tracker (audit :124).
- Any dispatch lands 260-810 s after the person came through the door, so HVAC pre-arrival (`hvac.py:7222-7259`)
  would start conditioning for someone already indoors, where the v5.103.20 fast path has already reacted.
- The cost is a Tier-3 options migration and selector change. The sighting `ts` for source (c'), crossing time or
  confirm time, is unspecified, and it decides both the D2 gap test and the lock regime's `face_input_corroborated`
  `at_ts`.
- **Fix:** add a D0 fire check: count GPS-led confirmations whose raw `person.*` was not `home` at confirm time. If
  it is 0, park D4 with a revival trigger (operator yes), per the marginal-benefit rule. Specify (c') `ts`.

**M4: the 600 s confirm window drops 4 of 10 measured true cases** (641, 781, 791 and 810 s; audit :56-58, :62; the
snapshot rows are upper bounds). The §9 default should be 900, or D0 (b) must settle it before ship, not "may set".

**M5 (G): the delivery channel is not stated.** The arrival notify is `Severity.LOW` (`transit_validator.py:2697-2702`)
and the follow-up is LOW and quiet. Live NM config (`.storage/core.config_entries`): companion HIGH, iMessage /
WhatsApp / Pushover / TTS CRITICAL, and the only recipient has `nm_person_delivery_pref: digest` (08:00 / 18:00). A
named arrival reaches the operator at best in the next digest. Whether the digest carries LOW is UNVERIFIED. L-c
("arrives quiet") cannot be evaluated. **Fix:** name the channel and the expected latency in the acceptance criteria,
and ask the operator whether that is the product.

**M6: §7 omits the sighting-producer change.** §5.3 needs a new source (c') on `SIGNAL_EGRESS_ENTRY_CONFIRMED` and
an `identity_role` of `arrival_confirmed`. `person_sighting.py:491` hardcodes `identity_role="attached"` and §7 says
"no change". Add the site, its subscription and teardown, and its debounce interaction (60 s `(slug, camera)` key).

**M7: the Ojini misname is live and the plan leaves it.** §5.1 keeps "missing person → `attached` (fail-open)". A
non-tracked face slug such as `ojini` has no `person.ojini`, so it attaches today: DB row `entry/ojini@-19s`
(audit :59), Ojini false in 10 of 10, "Ojini arrived" naming at ≥ 0.75 and a census union register. "Needs no pair"
is true but misses this. **Fix:** a tracked-slug membership test for the face single-slug path, which the sighting
producer already applies, or a card with the operator's yes.

**M8 (seam): the scoped egress mute expects step 7 to cut resident walk-out alerts**
(`PLANNING_perimeter_egress_mute_scoped.md` :62-65). Step 7 adds no new exit naming (exit + home was already
`attached`) and keeps candidates anonymous at t_E + 45 s, so the mute gains nothing. Reconcile this in the arc map
(`ura-arc` rule 6).

### LOW

- **L1:** HVAC has a second default site, the literal at `hvac.py:881`. The migration precedent
  `_migrate_hvac_zone_entry_dwell_to_zero` (`__init__.py:749`, called at `:3716-3724`) is not cited. "EC-pin write"
  is undefined. Live `pre_arrival_sources` is stored explicitly (`['geofence','ble','camera_face']`), so the
  migration runs. State whether the options write reloads the CM (`OPTIONS_RELOAD_SUPPRESS_KEYS`, `__init__.py:7553`).
- **L2:** `display_of("oji_udezue")` gives "Oji Udezue" (`person_ids.py:56-63`), not "Oji". Fix the §5.4 example
  text.
- **L3:** `departure_candidate` is named and evicted at once, so it is not provisional. Rename it or state that
  INV-PROVISIONAL covers arrivals only.
- **L4:** `candidate_person_id` on the public HA bus (`ura_person_egress_event`) goes into the recorder events table
  and any user automation. The operator's 11-12 rule says "withheld from every consumer". Keep the slug internal (the
  waiter does not need the bus), or declare the exception.
- **L5 (G, rule 4):** deferrals have no recorded operator yes: Protect face names (the charter: "especially when
  combined with facial recognition from the nvr systems"; manual §2.3 says the Protect API is reachable) and
  automatic pair learning. Each needs an operator yes and a card with a revival trigger.
- **L6:** the §3 consumer map omits music following (`music_following.py:549-583`, a no-op today that step 8 turns
  on) and the security expected-arrival add (`security.py:2424-2429`).
- **L7:** the arc map row 45 cites the veto at `:1840-1854`, but it is at `transit_validator.py:2036-2050`.

## Sites re-enumerated and verified (REUSE / NEW)

| Site | file:line | Plan claim | Verified |
|---|---|---|---|
| Face-only veto | `transit_validator.py:2036-2050` | REUSED | Yes. Raw `not_home` only; a named zone attaches today (the §5.1 delta is correctly declared) |
| Resolver + `_ret` | `:1497-2103`; caller `:2192` | REUSED, extend | Yes. BLE branches return the slug with no person-state test |
| Tier helper | `:121-161` | REUSED | Yes. BOOST needs ≥ 2 legs on one camera |
| Bus fire | `:2215-2240` | additive keys | Yes |
| Crossing record `source_ref` | `:2247-2260` | `egress:<cam>:<iso>` | Matches §5.4 |
| Notify | `:2647-2709`; call `:2278` | REUSED | Yes. `.title()` at `:2672`; LOW; untracked task (pre-existing) |
| Census register / evict | `:2305-2332` | unchanged | Yes. Provenance read from the stash, which is not written on veto |
| INSERT | `database.py:4600-4652` | return the row id | Returns None today; queued `_db()` |
| Backfill DAO | `database.py:4723-4770` | REUSED | Idempotent, confidence untouched. The exit finder `:4685-4721` is `direction='exit'`, so NULL candidate entry rows are safe from exit backfill |
| Four displays | `sensor.py:4828`, `:4973`, `:5059`, `:5172` | readers | Yes |
| Attach counter | `sensor.py:3993` | relabel | Yes. The only `"attached"` reader besides the sighting role (`person_sighting.py:491`) |
| D2 site | `presence.py:5825-5894` | add egress branch | Yes. See M3 |
| HVAC filter | `hvac.py:1431-1440`, `:7231` | REUSED | Yes, plus the literal at `:881` (L1) |
| Camera-derived set | `const.py:3486` | REUSED | Holds `camera_egress` |
| Access gates | `security.py:2424-2429`; lock regime `face_input_corroborated` | unchanged | INV-ACCESS holds. Any corroborating edge releases on its own |
| Perimeter D10.5 | `perimeter_alert.py:1018-1035`, `:5178-5262`, `:5519-5589` | "bus only" | **No (H3)** |
| Scoped egress mute | plan `:49-54` | not listed | Consumes bus `person_id` at ≥ 0.9. Candidates count as unknown (safe); pair conflict is not handled (M1) |
| Sighting source (c)/(c') | `person_sighting.py:449-491` | "no change" | **No (M6)** |
| Residency / inference | `presence._handle_geofence_change` raw person only | untouched | Yes, except M2 (union TTL) |
| Music | `music_following.py:549-583` | not listed | No-op today (L6) |
| `get_last_crossing` | `transit_validator.py:1044`, `presence.py:6009` | REUSED | Yes |
| NEW names | grep `SIGNAL_EGRESS_ENTRY_CONFIRMED`, `EGRESS_OUTCOMES_ATTACHED`, `confusable`, `gps_fix`, `SIGNAL_PERSON_DEPARTING` | 0 hits | Confirmed 0 |

## Parked-plan triggers this cycle fires

- §2B.3 pair guard (G5): fired and included.
- F-NOTIFY identity half (census plan §3.2 rung 2): satisfied on ship, so it unblocks P2-D9. Fix H2 first.
- EXTERIOR-GUEST-EGRESS-1 (manual §6) is "gated on the identity path proving insufficient". If D0 (f) (H1) shows
  near-zero yield, that trigger arguably fires. Surface it to the operator rather than re-recommending it silently.
- GUEST-GATE-DOOR-IDENTITY-1: not fired (no GUEST input change).

## Framing G checklist

| Charter item | Result |
|---|---|
| Named arrivals ("assist arrivals accuracy"; "It should do both") | **FAIL as specified** (H1, M5). The mechanism is right; the measured yield is about 0-1 of 10 and the delivery is a LOW digest |
| AWAY fast (hard constraint) | **LEAK, bounded** (M2: up to 300 s on exit + named zone). Otherwise inference is untouched |
| Face alone never acts on access | PASS. `camera_egress` is camera-derived and both access gates need an independent edge (INV-ACCESS holds) |
| Security last / faster toward security | PASS for direction; M1 open (pair conflict still trusted by the security class) |
| Short-clip path not precluded | PASS. The plan touches no vision frame source |
| No deferral without operator yes | **FAIL** (L5; M3 if D4 is parked; group arrivals anonymous under H1) |

## Must-fix before build dispatch

H1, H2, H3, H4, M1, M2, M3, M6. Fix M4, M5, M7 and M8 in the same plan pass; the LOWs are cheap.
