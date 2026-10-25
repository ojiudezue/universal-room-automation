# PLANNING — Census: BLE decides, face confirms (CENSUS-BLE-OVER-FACE-1)

**Operator (verbatim, 2026-10-24):** "Ble is going to be better than face almost anytime. Same logic as gps. It can confirm. Plan it maybe add another toggle." Addendum: "Narrow fixes."
**Status:** plan rev 1, not reviewed. No code edited. **Tier 2, three framing-disjoint reviews** (§8).
**Read first, completely:** `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`, `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger), `docs/architecture/SENSOR_FLEET_CLASSES.md`, `docs/planning/AUDIT_presence_gps_assistive_consequence_replay.md`, `docs/planning/PLANNING_presence_gps_assistive.md`. Not HVAC work.

---

## 0. The change in one paragraph

One line of policy at one site. The census face-latch guard in
`camera_census._get_face_recognized_person_names` (`camera_census.py:5884-5904`) drops a
face-recognised person when `person.<slug>` reads `not_home`. It reads RAW HA state, which for
GPS+BLE adults (Oji, Ezinne) is GPS-led. Route that one read through the existing
`person_coordinator.person_state_for_trust(hass, "person.<slug>")` (`person_coordinator.py:124`).
That helper already returns `not_home` only for a person the v5.103.90 rule overruled on the last
tick (GPS `home`, every own `bluetooth_le` tracker `not_home`, Bermuda fleet armed, URA location
`away`) and only while **BLE Leads Home/Away** is on (`effective_person_state`,
`person_coordinator.py:628-655`). Everything else returns raw state verbatim. No new switch, no new
state, no new math.

## 1. Institutional context verified

### 1.1 Prior art, REUSE or BUILD per piece

| Piece | Verdict | Where |
|---|---|---|
| "Is this person away by BLE?" | **REUSED** `_gps_home_overruled` frozenset + `effective_person_state` | `person_coordinator.py:224`, `:628-655`, assigned once per tick `:1222-1227` |
| Trust-reader wrapper (fail-open to raw) | **REUSED** `person_state_for_trust` | `person_coordinator.py:124-145` |
| Toggle | **REUSED** `switch.ura_presence_ble_leads_enabled` (`PresenceBleLeadsEnabledSwitch`, `switch.py:3892`, `_unique_slug = "presence_ble_leads_enabled"` `:3904`, backing `_ble_leads_enabled` `:3906`). Already consulted inside `effective_person_state`, so the gate is free | — |
| Face admission site | **REUSED** (modified) stale-face latch guard | `camera_census.py:5884-5904` |
| Body accounting when a name is dropped | **REUSED** existing enhanced-census math (BLE area-cancel `_get_unrecognized_camera_count` ~`:5492-5503`; ceiling clamp `:5998-6003`) | no change |
| Review-only revert | **NEW** rung-1 bool `CENSUS_FACE_LATCH_FOLLOWS_BLE_LEADS` (const.py). `grep -rn "FACE_LATCH\|FACE_CONFIRMS\|face_confirms" custom_components/` → 0 hits | justification §6 |
| New "Face Confirms Only" switch | **NOT BUILT** (§6) | — |

Greps run (2026-10-24, develop @ 07a60d99a): `def _get_face_recognized_person_names`, `is_face_leg_person_vetoed`,
`_get_ble_persons`, `face_recognized_count`, `identified_persons`, `face_persons`,
`face_recognized_persons` across the integration; `person_state_for_trust` / `_gps_home_overruled`
in `person_coordinator.py`; `class Presence.*Switch` / `ble_leads` in `switch.py`; knob names in
`const.py`.

### 1.2 Docs / plans / memory consulted
- IDENTITY manual §2.1 (BLE blind to phoneless), §3 rule 6 (graceful-anonymous), §4.3 egress veto, §5.4 (veto mirrored in census).
- PRESENCE SoP §1 table row `person_state_for_trust` — it records the face latch was **deliberately left raw** after the replay. This plan reverses that decision on the operator's later ruling (option A) and must update that row and add a §10 entry in the same commit.
- `AUDIT_presence_gps_assistive_consequence_replay.md` §3.6, §5 — source of the cost numbers below.
- `PLANNING_presence_gps_assistive.md` (INV-1, §6b ADOPT list, §9 residuals).
- Card FRIGATE-FACE-MISLABEL-OJI-1 instance 2026-10-24 21:42 (tonight's trigger).
- Memories: `reference_presence_state_of_play`, `feedback_read_consumers_before_asserting_function`, `project_guest_mode_false_positive_backlog`, `reference_egress_face_coverage_7pct_not_a_ceiling`.

### 1.3 Config-first
No setting does this. BLE Leads OFF reverts the whole v5.103.90 rule (wrong direction). Turning
`switch.ura_name_people_at_doors` off only affects egress. Disabling face via the D4 suppression
path drops face for everyone, including the no-BLE case face is meant to cover. Code is needed.

## 2. Why the kids already behave this way (the key finding)

Jaya and Ziri have only BLE trackers on their `person.*` entity (replay §1). HA derives their
`person.state` from those trackers, so when their BLE reads `not_home`, `person.state` is
`not_home` and the guard at `:5897-5904` **already drops their face today**. Adults differ only
because a GPS tracker holds `person.state` at `home`. The change makes adults match the kids, which
is exactly operator option A ("a resident home without phone is treated away like the BLE-only
kids"). (Verify in D0: read `person.jaya.attributes.device_trackers` live.)

## 3. Decision: what the dropped body counts as

Options for a body whose face says Oji while Oji is away by BLE:

| Option | Effect | Verdict |
|---|---|---|
| (a) **unidentified** (falls out of existing math) | Body stays in `camera_total`; BLE area-cancel removes it only if some BLE-located resident is in that camera's area; otherwise it can raise `unidentified_count`, subject to the ceiling clamp `max(camera_total_pre_cancel, identified_count)` | **Chosen.** Zero new math, same treatment the kids get today, and it never hides a real body from path α / nobody-home |
| (b) ignored (removed from camera total) | Needs a new subtract path; a real guest mislabelled as a resident disappears from the census and from AWAY blocking | Rejected: hides bodies, new writer to the census math |
| (c) "unnamed resident" bucket (explains body, not guest, not named) | New count, new consumer semantics for GUEST and α; a guest mislabelled as a resident is masked exactly as today | Rejected: greenfield, and the only win is avoiding a GUEST cost the operator accepted under option A |

**Cost of (a), measured (replay §3.6, proxy, 7.6 days to 10-24 19:25):** on Oji's at-home-without-BLE
intervals the unidentified run at medium/high confidence grows from 1,080 / 1,411 / 0 s to
1,080 / 2,641 / 2,595 s (IV10 / IV11 / IV12). GUEST persistence is 300 s
(`DEFAULT_GUEST_PERSISTENCE_SECONDS`, `const.py:3973`), so one additional GUEST-eligible run (IV12,
~43 min) and one longer run (IV11, +20 min) in 7.6 days, all on one day (10-24) when Oji's phone
BLE was dark at home. Option-A acceptance covers this; §9 Q1 asks the operator to confirm it
explicitly, because the replay audit (§5) noted that his earlier acceptance did not name GUEST.

**Benefit of (a):** `identified_persons` / `face_confirmed` stop naming an absent adult; and path α's
`face_recognized_count` stops being held > 0 by an absent adult's stale or mislabelled face (the
flapping `last_camera` re-stamp that the guard exists for, `:5876-5882`). Today that matters only
when every other resident is also away; tonight others were home, so the visible effect is display.

## 4. D0 — measure before build

### 4.1 What existing data already says (replay, Oji, 7.6 d; Ezinne 0 qualifying moments)

| Bucket | Count | Ground truth |
|---|---|---|
| Overrule minutes (Oji BLE-away by rule) | 1,124 | — |
| Interior face events for Oji inside those minutes | ~91 (IV1 1, IV6 6, IV7 2, IV10 4, IV11 24, IV12 54) | **right**: all in camera-confirmed at-home intervals (home without phone) |
| Face events inside true-away intervals (IV3, IV4, IV9) | 0 fresh; latch tail only, ≤ ~80 s before expiry | stale latch, harmless |
| Wrong face-only identity for a BLE-away person | **1 known**: 10-24 21:42 (Oji abroad, Frigate labels Jaya as Oji; FRIGATE-FACE-MISLABEL-OJI-1), after the replay window | **wrong** |

So in the measured week, face-only-while-BLE-away was right far more often than wrong. The operator's
premise ("BLE better than face almost anytime") holds for *who is home* only under option A: the
"right" faces were a resident at home without a phone, which option A chooses to treat as away. This
is a policy choice, not a data-quality win. Stated plainly so the operator rules on it knowingly (§9 Q1).

### 4.2 D0 probe (read-only, before build; go/no-go)
Script over HA recorder + URA DB, last 7 days, for each tracked person:
1. Minutes where URA location sensor = `Away` with reason `away_ble_silent_only` AND `person.<x>` = `home` (i.e. in `_gps_home_overruled`); and, separately for kids, minutes BLE `not_home`.
2. In those minutes, `sensor.frigate_<first>_last_camera[_2]` changes (the guard's actual input, not `last_recognized_face`) and interior `*_last_recognized_face_2` = that person.
3. Classify each face event right/wrong using the replay oracle (interior face clusters on ≥2 cameras within 30 min, egress rows, later BLE re-fix in-house) plus, for 10-24 21:42 onward, the operator's travel (Oji abroad).
4. Replay the census unidentified proxy (replay caveat c) with the guard swapped: total GUEST-eligible seconds added.
5. Confirm `person.jaya` / `person.ziri` device_trackers are BLE-only (§2).

**Gate:** proceed if (4) adds no GUEST-eligible run outside periods where the person was home
without BLE (i.e. no new cost beyond the option-A class). Stop and re-plan if a run appears while the
person was verifiably away (would mean the body math, not the name, is the problem).

## 5. Producer and consumer checks

### 5.1 Producer — `face_recognized` (enhanced path)
`_get_face_recognized_person_names(now)` (`camera_census.py:5816-5906`): per tracked person, resolve
`sensor.frigate_<first>_last_camera[_2]` via registry (`_resolve_last_camera_entity_id`), require a
real camera name, age ≤ `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` (1800 s) from `last_changed`, then the
guard. **Dependency health:** `last_changed` re-stamps on unavailable⇄camera flaps (`:5876-5882`), so
age alone never expires; Frigate mislabels Jaya↔Oji (card above). The guard is the only discharge.
After the change the guard's input is `person_state_for_trust` (raw unless overruled + switch on).
Dependency health of that: `_gps_home_overruled` is assigned once per completed tick and kept on
UpdateFailed (SoP §3); no person coordinator / exception → raw (fail-open preserved).

### 5.2 Producer — raw path face ids
`_get_face_recognized_persons()` (`camera_census.py:3545-3584`) has **no person veto and no
freshness gate**; feeds `_cross_correlate_persons` (`:2181-2185`). When `CONF_ENHANCED_CENSUS` is on,
`_apply_enhanced_house_census` (`:5908+`) recomputes `identified_persons` / `identified_count` /
`unidentified_count` and overwrites the raw house values (comment `:5938-5946`). **Open Q2:** confirm
enhanced census is on live; if it is, the raw path is not a consumer-visible admission site and is a
non-goal. If it is off, the raw path needs the same rule and the plan grows by one site.

### 5.3 Consumers of the face-admitted identity (file:line, trust vs display)

| Consumer | Reads | Trust/display | Changes? |
|---|---|---|---|
| `recognized_set` → `identified_count`, `identified_persons` (`camera_census.py:5947-5970`, `:6026-6029`) | face names ∪ BLE ∪ egress | trust input to unidentified math | yes (intended) |
| Unidentified math (`:5972-6003`) | `identified_count` via ceiling | **trust** (GUEST) | yes, §3 cost |
| `SIGNAL_CENSUS_UPDATED` `face_recognized_count` (`:1837`) → path α (`presence.py:1169-1180`), sensor attr (`sensor.py:5724-5737`) | len(face_recognized) | **trust** (AWAY) | yes (intended: absent adult's face stops blocking α) |
| `face_persons` / `face_confirmed` attr (`camera_census.py:1757`, `sensor.py:4091`) | identified_persons | display | yes |
| `face_recognized_persons` attr (`sensor.py:3787`) | face list | display | yes |
| GUEST gate (`presence.py` `_guest_gate_armed`, ~:5965) | unidentified_count + confidence + persistence | **trust** | indirect via unidentified |
| Room identified persons (`coordinator.py:1109`, `:1292-1299` via `get_room_identified_persons`) | census room view | display / room context | verify in build (Q3); not changed by this plan |
| Egress face-leg veto `is_face_leg_person_vetoed` (`camera_census.py:4178-4200`) and `transit_validator` egress veto | raw `person.state` | trust (egress identity, advisory) | **non-goal** (§7) |
| Music following, NM targeting, `persons_home` | person_coordinator location, not census face | display/routing | no (already follow BLE since v5.103.90) |
| Perimeter alerts | DetectionLeg, no census identity | — | no |

## 6. Toggle and knobs

- **Operator toggle: reuse BLE Leads Home/Away.** It already gates `effective_person_state`; OFF
  restores raw for this site with no extra code. A separate "Face Confirms Only" switch is justified
  only if the operator wants BLE to lead home/away while faces keep admitting absent adults. That
  combination is incoherent with option A, so no new switch (operator addendum: prefer reuse).
- **Rung 1:** `CENSUS_FACE_LATCH_FOLLOWS_BLE_LEADS: Final = True` in `const.py`. Why rung 1: lets a
  reviewer revert this one site to raw (the SoP's prior deliberate choice) without turning off the
  whole BLE-leads rule. Kill semantics: `False` = read raw `person.state` exactly as today
  (byte-identical). Read as a module attribute at call time.
- No new numbers.

## 7. Falsifiable invariant

**INV-FACE-CONFIRMS:** with BLE Leads on and the rung-1 flag True, for every census tick, if
`p ∈ person_coordinator._gps_home_overruled` and `get_person_location(p) == "away"` at the read,
then `p ∉ face_recognized` in `_apply_enhanced_house_census`, hence `p` contributes neither to
`face_recognized_count` nor, via face, to `identified_persons`. Conversely, for every person NOT
overruled (including any person with no person coordinator, switch off, or flag False), the face
admission decision is byte-identical to `develop` @ 07a60d99a.

Falsifiers a reviewer should try: a face name that canonicalises to `p` through a different path
(egress register `_get_egress_face_ids_fresh` — a *fresh entry* crossing with face, which is a
different evidence class and stays; see non-goals); the raw path (Q2); a tick where the overrule set
changed between person tick and census tick (accepted: one-tick lag, same as every other trust reader).

## 8. Deliverables

### D0 — probe (§4.2)
- **Verify:** report table of right/wrong face-only events and added GUEST-eligible seconds per person.
- **Live:** none (read-only).

### D1 — route the guard through the trust helper
At `camera_census.py:5884-5904`, when `const.CENSUS_FACE_LATCH_FOLLOWS_BLE_LEADS` is True, obtain the
state with `person_state_for_trust(self.hass, person_entity_id)` instead of
`self.hass.states.get(...).state`; keep the existing `== "not_home"` test, the DEBUG line (add the
source: `raw` / `ble_overrule`), and fail-open shape. Replace the "deliberately left on RAW" comment.
Add a per-tick counter `face_dropped_ble_overrule_count` on the census sensor attributes (display;
reset at tick start beside `_face_lookup_missing_count`, `:1708`).

**Acceptance criteria**
- **Test:** `test_census_face_dropped_when_ble_overruled` — p overruled + location away, face fresh → p absent from `identified_persons`, `face_recognized_count` excludes p, counter = 1.
- **Test:** `test_census_face_kept_when_ble_leads_off` — same, switch off → p present (raw `home`).
- **Test:** `test_census_face_kept_when_flag_false` — flag False → p present; asserts helper not called.
- **Test:** `test_census_face_kept_when_not_overruled` — person.state home, not in set → present (BLE agrees or no opinion).
- **Test:** `test_census_face_dropped_raw_not_home_unchanged` — kid with raw `not_home` dropped as today.
- **Test:** `test_census_face_fail_open_no_person_coordinator` — no pc → raw path.
- **Test (discriminating body math):** overruled p's body in an area with a BLE-located resident → unidentified 0; same body in an area with no BLE resident and identified < camera total → unidentified 1. Distinguishes "name dropped, body kept" (fix) from "body hidden" (option b leak).
- **Mutation (framing C):** revert the one read to raw → the first test fails.
- **Live:** with Oji abroad, `sensor.universal_room_automation_identified_persons_in_house` `person_list` excludes `oji_udezue` while `sensor.oji_udezue_location` (URA) reads Away with reason `away_ble_silent_only`; `face_dropped_ble_overrule_count` > 0 on a tick where `sensor.frigate_oji_last_camera_2` is fresh. Discriminator: if instead the count stays 3 and the counter stays 0, the helper is not wired or the overrule set is empty (check `person_coordinator` attr / `tracker_sources.gps == "home"`).
- **Live (no-regression):** while Oji is home with BLE (`home` trackers), `person_list` includes him and the counter is 0.

### D2 — docs in the same commit
PRESENCE SoP §1 row (face latch now follows BLE Leads; cite this plan) and §10 entry ("face latch left raw" superseded by operator option A, 2026-10-24); IDENTITY manual §5.4 veto bullet.

## 9. Non-goals
- Egress face-leg veto (`is_face_leg_person_vetoed`, `transit_validator`) stays raw: advisory, separate evidence (a face AT a crossing), and an entry crossing is precisely how a returning resident should become identified before BLE re-acquires. Not required for correctness of INV-FACE-CONFIRMS.
- Raw-path `_get_face_recognized_persons` (pending Q2).
- No change to unidentified/ceiling math, GUEST gate, path α, nobody-home.
- No fix for the Frigate Jaya↔Oji mislabel (card FRIGATE-FACE-MISLABEL-OJI-1) or the `last_camera` flap restamp.
- No "unnamed resident" bucket (§3 c, parked; revive if GUEST false positives from option A are carded twice in a month).
- No new switch.

## 10. Tier
**Tier 2, elevated to three framing-disjoint reviews** (standing policy: trust-hierarchy ripple presence ↔ census ↔ GUEST/AWAY). One-site change, no DB, no shared-primitive writer, so not Tier 3. Framings: A local correctness (guard, fail-open, flag/switch matrix); B cross-coordinator (GUEST and α consequences, tick ordering between person and census coordinators); C test authority by per-site mutation. One adversarial plan review before build.

## 11. Open questions for the operator
1. **GUEST cost under option A.** When you are home with your phone's BLE dark and no co-resident covers the camera area, your face will no longer explain your body, so the house can go GUEST (measured: one extra ~43-min eligible run and one +20-min run in 7.6 days, all 10-24). Accept? (The kids already work this way.)
2. Is `CONF_ENHANCED_CENSUS` on live? (If off, the raw path joins scope.)
3. Should room-level identified persons (`coordinator.py:1109`) follow too? Plan says no change; confirm it is display-only.
4. Separate toggle: confirm reuse of BLE Leads is fine (a separate switch only makes sense if you want BLE leading home/away but faces still naming absent adults).
