# Plan review: CENSUS-BLE-OVER-FACE-1 (rev 3, commit 6058a1884)

**Reviewer:** ura-reviewer, Tier-2 adversarial plan review (one pass, pre-build). No code edited.
**Read first, completely:** `IDENTITY_FUSION_CAMERAS_MANUAL.md`, `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger), `SENSOR_FLEET_CLASSES.md`, `AUDIT_presence_gps_assistive_consequence_replay.md`. No §10 claim re-asserted.
**Verdict: FIX-REQUIRED (plan edits only).** The mechanism is sound and the one-site change is correctly located. Fix findings 1-3 in the plan before build dispatch; 4-9 are small spec or doc items.

## Verified (holds)

- **Single enhanced-path admission site for identity.** `face_recognized` comes only from `_get_face_recognized_person_names` (`camera_census.py:5816-5906`), called once at `:5925`. It feeds `recognized_set` (`:5951-5958`), `face_recognized_persons=` (`:6044`) and, through it, `face_recognized_count` (`:1789`, `:1837`). With `enhanced_census: true` the raw `_get_face_recognized_persons` (`:2180`) result for the house is overwritten (`:5938-5946`). The property census sets `identified_persons=[]` and has no face input (`:2201+`). `face_persons` (`:1757`) is the union of house and property identified persons, so it is house-only in practice.
- **Helper semantics.** `person_state_for_trust` (`person_coordinator.py:124-145`) and `effective_person_state` (`:628-655`) return `not_home` only when the name is in `_gps_home_overruled`, the switch is on, and `get_person_location(name) == "away"`. Every other case, including any exception, returns raw. `_get_ble_persons` (`camera_census.py:2671-2685`) already drops a `location == away` person, so after the change an overruled person has no BLE or face route into `recognized_set`. The egress register is the only route left, and the plan names it.
- **Per-tick timing cannot cause flapping.** `_gps_home_overruled` is assigned at `person_coordinator.py:1227`, before `self.data` is published. `get_person_location` reads `self.data` (`:1811-1815`). If the two disagree for a tick, at either edge, the helper returns raw, so the error is always toward admitting the face (today's behaviour) and lasts at most one tick. Identity flips only when the overrule itself flips. When the overrule ends because BLE reads home, the person comes back through `ble_persons`, so `identified_count` stays the same at that edge. The 300 s GUEST persistence absorbs single-tick changes.
- **Switch off.** `effective_person_state` returns raw when `_ble_leads_enabled()` is False, and the overrule set empties on the next person tick. The admission decision is byte-identical.
- **Restart.** `_gps_home_overruled` starts as `frozenset()` (`:224`) and is not restored. The fleet-arm latch (≥ 360 s) then keeps it empty, so for ≥ 6 min after a restart the site behaves as it does today. This is safe because the error is toward admission.
- **Room-level claim.** `get_room_identified_persons` exists nowhere except the `getattr(..., lambda r: None)` at `coordinator.py:1299`, so it always falls back to BLE. KEEP + DOCUMENT is correct.
- **v5.103.90 is live.** Manifest `:18` reads `v5.103.90`, and `README_v5.103.90.md` exists. The helper has 6 production callers (aggregation ×2, hvac ×2, hvac_fans ×1, and the module wrapper).
- **D0 counterfactual maths.** It uses the recorded post-cancel `camera_unrecognized`, so the real BLE area-cancel is included. For the four runs (pre_cancel 3, unrecognized 3, id 3 → 2): ceiling 3, total `min(5, 3) = 3`, unidentified 0 → 1. The arithmetic matches `:5998-6003`.

## Findings

1. **MEDIUM (Bug Class #53, one-missed-site enumeration): unlisted face consumer.** `_get_face_recognized_persons_fresh` (`camera_census.py:2077-2079`, `:3586+`) feeds the cross-validation corroboration bundle. That bundle decides whether a divergent camera max is downgraded, and so sets census `confidence`, which is an input to the GUEST gate. It has no person veto. After the change, the mislabelled "Oji" face still corroborates and keeps confidence medium/high, while Oji's name leaves the identified set. That combination is exactly what makes the D0 runs GUEST-eligible. The probable right verdict is to keep it raw, because it corroborates that a body exists, not who it is. The plan must still list it in §5.3 and §9 and give that reason. Otherwise a builder or reviewer will either miss it or "fix" it inconsistently.
2. **MEDIUM (internal inconsistency in the cost statement): §3 still carries the falsified hypothesis.** §3's "Cost of (a)" paragraph still says the expected cost is "**near zero**, unproven until D0", and that a Jaya body in another area "usually fails (2)". §4.3 then says the data falsifies this: 4 GUEST-eligible runs, ~33 min, on 10-24. A builder or operator reading §3 gets the wrong cost. Rewrite §3 to point to §4.3's measured cost and drop "near zero".
3. **MEDIUM (honesty of D0 on the third body): one cheap discriminator was skipped.** The plan correctly says the third body is unknown. But D0 lists everything apart from Oji's confirmed travel as `unknown`. It never checks the cheapest discriminators at 13:40, 15:19, 15:43 and 19:04 on 10-24:
   - (a) Was **Ziri** home? He is a BLE-only resident with no GPS, and his face labels and BLE state are in the recorder. If Ziri was home and BLE-dark, these runs are the option-A false-GUEST class against a resident, which is the cost the operator accepted. That is a different statement from "maybe a guest".
   - (b) The per-camera person counts at those samples. These show whether the 3 came from one camera or was summed across `family_room` and `utilities_ptz`, which would be a likely double count of one body.

   Also, the bucket "other resident BLE-home, different area" mixes up "a different body" with "the same resident whose BLE room differs from the camera's area". The co-location test compared camera names with `ble_by_area` keys, and `utilities_ptz` is not an area. Either add the two checks to §4.3, or state plainly that the runs are unattributed and that the operator's Q1 acceptance covers a possible resident false-GUEST.
4. **LOW (gate design): the gate could not have failed.** The go/no-go test ("no run in the co-located-mislabel bucket") ran on 11 samples (2.5 min) and was nearly certain to pass. The actual decision is Q1's operator acceptance of a measured cost. Say that in §4.3, so the "GO" is not read as evidence that the cost is low.
5. **LOW (spec precision, byte-identity): the D1 counter.** `face_dropped_ble_overrule_count`:
   - Name the sensor that carries it (presumably `persons_in_house`).
   - Read raw state once. Call the helper only when the flag is True, which is what the flag-False test "helper not called" requires.
   - Count only drops where raw ≠ `not_home` and the trust value is `not_home`, so kids' existing raw drops do not inflate it.
   - Restate the switch-off and flag-False claims as "admission decision byte-identical". The new attribute is present either way.
   - Decide whether it belongs in `_unrecorded_attributes`. The census sensor is recorded every tick, so a new attribute adds recorder rows on every drop tick.
6. **LOW (§7 wording): name the direction of the one-tick lag.** It always errs toward admission (today's behaviour). Also add the restart case: ≥ 6 min of raw behaviour after boot, because the set starts empty and the arm latch holds.
7. **LOW (namespace, silent no-op risk).** The census builds `person.{slug.lower()}` (`camera_census.py:5891`) from entry data merged with options. The helper matches `person.{name.lower().replace(' ', '_')}` (`person_coordinator.py:648`) against `tracked_persons` read from `entry.data` only (`:160`). The two agree for the live underscore slugs. A spaced name, or a `tracked_persons` list set only in options, would quietly fall back to raw. Tests should use the live key shape. The Live criterion (counter > 0 while Oji is abroad) already detects this.
8. **LOW (doc drift for D2).**
   - The PRESENCE SoP §1 row and §3 still say "branch `fix/presence-gps-assistive`, NOT deployed". It is live as v5.103.90.
   - The IDENTITY manual §5.4 cites `~:3346-3366`; the code is now at `:5884-5904`.
   - The comment at `camera_census.py:1779-1786` cites `:3034-3055`.
   - The plan cites path α at `presence.py:1169-1180`; the gate comments now sit at ~`:1206-1230`.

   Fix all four in the D1/D2 commit.
9. **LOW (open egress fence).** A mislabelled *entry* crossing registers the wrong slug through `_get_egress_face_ids_fresh` for the union TTL. That route bypasses INV-FACE-CONFIRMS. It is correctly listed as a non-goal. Add one line to §9 saying the INV holds only for the interior latch, so the Live check is not read as covering egress.

## Invariant check (INV-FACE-CONFIRMS)

| Clause | Status |
|---|---|
| Overruled + away ⇒ not in `face_recognized` | PASS once D1 lands (single site, `:5925`) |
| ⇒ not in `face_recognized_count` | PASS (`:1789` reads the same list) |
| ⇒ not in `identified_persons` via face | PASS, but the egress register can still add the person (finding 9) |
| Non-overruled / switch off / flag False / no pc ⇒ byte-identical | PASS for the decision; the new attribute is not byte-identical (finding 5) |
| One-tick lag cannot flap | PASS (it errs toward admission) |

## Must-fix before build
Findings 1, 2 and 3: plan text, plus the optional Ziri and per-camera recorder check. Fold findings 4-9 into the same revision.
