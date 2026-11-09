# Plan review 1: FACE-SOURCE-REGISTRY-DISCOVERY-1

Plan: `docs/planning/PLANNING_face_source_registry_discovery_2026_11.md` (reviewed at `7959d000`, rev 2 applied in the
same commit as this review). Inputs: `AUDIT_face_source_registry_discovery_2026_11.md`,
`IDENTITY_FUSION_CAMERAS_MANUAL.md`. Tier 2-DB plan review (one adversarial pass). Reviewer: ura-planner, 2026-11-08.
Read in full: the plan and the audit. Read the code at every cited site; greps re-run on `develop`.

**Verdict: FIX-PLAN-FIRST. The fixes are applied as rev 2, so the plan is now BUILD**, subject to the D0 gate and the
sequencing rule (perimeter v5.107.0 merged first).

## 1. Verified as claimed

| Claim | Check | Result |
|---|---|---|
| Consumers: 8 plus `_get_face_recognized_person_names` | grep `_resolve_face_entity_id\|_resolve_face_legs\|_get_face_recognized_persons\|_get_unrecognized_camera_count\|_get_face_for_camera\|_compute_face_latch_stems` | Call sites: `camera_census.py:2087` (S6), `:2189` (S5), `:3581`, `:3616`, `:5186` (latch), `:5544` (S7), `:5975-5977`; `transit_validator.py:1459`; `perimeter_alert.py:1401`; `presence.py:5326`, `:5391`. Nothing missing. The perimeter D10.5 caller is not on develop yet; §9 covers it. |
| Pattern-match sites S1-S12 | grep `endswith("_person_occupancy")\|last_recognized_face\|face_recognized\|sensor_recognized_face` | All present at the cited lines. Missing from the non-goals list: `camera_census.py:626` and `:1134` (both person-leg derivation, both already `_N`-stripped). Fixed in rev 2. |
| 17 of 29 skipped | Re-ran the registry join myself | 17 SKIP confirmed. Of the 17, only `playroom` and `upstairs_hall` are interior. The other 15 are exterior (doorbell, garages, yards, PTZs, hot tub, pool). |
| Knob ladder | §7 | Rungs are right: two module constants and one options field. No unknobbed numbers. Rev 2 changes one default (see §3). |
| INV-2 dedup claim | `camera_census.py:3325-3390` | Holds structurally. The synthetic leg copies the engine from any entity leg already in `results` (`:3331-3334`), so entity and synthetic legs agree whatever derivation is used. There is one gap; see F-2. |
| `contributor_engines` display only | grep | Built at `transit_validator.py:1709` and `:1889-1904` into the last-attach observability. It is not a DB column. Confirmed. |

## 2. Findings

| # | Sev | Finding | Bug class | Fix (rev 2) |
|---|---|---|---|---|
| F-1 | HIGH | D3 shadow plus a 14-day forward count is a soak. CLAUDE.md "No soak watching" and Measure-before-build both say to answer the question from existing data. The face sensors are not recorder-excluded, so the history already exists. | Process (soak as gate) | New D0: a one-shot recorder probe before build. D3 ships live, default True, if the gate passes. The FLIP card is folded into this cycle. |
| F-2 | HIGH | D4 does not specify a fallback. If the device-derived helper returns `"unknown"` or `""` (missing device, test stub, `_infer_integration` miss), the entity leg's engine falls outside `("frigate","frigate2")` (`:3332`). The synthetic leg then takes its own branch and is tagged `"frigate"`, so the dedup at `:3385` misses. That gives `n=2` and a spurious 0.75 boost, which is exactly the INV-2 break. Repro: a face entity whose `device_id` is absent from the device registry, with a fresh latch on the same stem. | Coincidental-equality / unpinned fallback | The helper returns the candidate's `integration_hint` on any miss, and the `:3332` membership set is updated in the same edit. Added a test and a Verify. |
| F-3 | MED | In the D2 live criterion, "dead face subsystem shows both 0" is wrong if the counters count lookups, and the plan never said what they count. The criterion was undiscriminating. | Undiscriminating acceptance | Pinned: the counters count lookups. Producer death shows in `face_lookup_missing_count`. |
| F-4 | MED | D3's live criterion (`skipped == 17`) only discriminated in shadow mode. | Undiscriminating acceptance | Replaced with a positive `face_source_device_derived_cameras` list plus an interior `count-1` observation, with distinct signatures for "not wired" and "join broken". |
| F-5 | MED (pre-existing) | S7 subtracts 1 for any fresh named face, including `guest:*` (known-face guests such as Ojini). A known guest alone in front of an interior camera is therefore not counted as unrecognized. This already happens on the 12 bare cameras. D3 widens it to playroom. | Semantics of a trust input | Not forked in this cycle (non-goal). Card it: subtract only for tracked-resident slugs. |
| F-6 | LOW (pre-existing) | The raw fuse site `_cross_correlate_persons` (`:2496-2505`) puts `guest:ojini` into `known_persons`, which inflates `identified_count`. Only the enhanced recompute (`:6013-6021`) separates guests. This is live only when enhanced census is off (live: on). | Namespace leak (v5.16 class) | Non-goal; card it. |
| F-7 | LOW | The `upstairs_hall` Frigate sensor may never be in S7's interior list: `camera_person_entities` holds `camera.upstairs_hall_high_resolution_channel`, not `camera.upstairs_hall_2`. The plan asserts upstairs_hall is affected without checking. | Unverified premise | D0.3 checks it at runtime. |

## 3. The specific question: shadow plus 14 days, or live this cycle?

**Recommendation: live this cycle, default True, gated by a pre-build one-shot recorder probe (D0). Keep the
constant as the kill switch.** Here is what actually changes on this house, consumer by consumer, read from code:

1. **S5 census face union (`_get_face_recognized_persons`, `:2189`).** On this install it has no effect on house
   counts. `enhanced_census` is True (live options), and `_apply_enhanced_house_census` rebuilds `identified_*` from
   BLE, `_get_face_recognized_person_names` (the `last_camera` map, not per-camera sensors) and egress
   (`:5977-6021`). The only raw fields it keeps are confidence, agreement and platform counts (it reads `raw_result.`
   only at `:6120-6131` relative). The visible effect is that the `face_confirmed` attribute (`sensor.py:4093` ←
   `:1764`) can now list exterior faces. That is display only.
2. **S7 guest count (`_get_unrecognized_camera_count`, `:5531-5574`).** Interior cameras only (`configured_interior`).
   Today a `_2` interior camera takes the "can't derive face sensor — count as unrecognized" branch (`:5533-5536`)
   every tick. After the flip, a fresh face makes the contribution `count-1`, and a stale or absent face leaves it at
   `count` (fail-closed, unchanged). **The count can only go down, so the flip cannot produce a GUEST flip-on.** The
   change lowers the playroom phantom-guest pressure that the 2026-08-01 corroboration work was fighting. The
   downside is a missed guest when a guest's face is fresh. That covers a misrecognition and also a correctly
   recognized known guest (F-5). Both already happen on the 12 bare cameras, and per-area BLE-cancel already absorbs
   most of this.
3. **S6 corroboration (`:2087`).** More fresh faces mean more corroboration, which can block a divergence downgrade.
   This only matters when `ble_persons` is empty and no tier-1 zone is occupied (it is OR'd at `:2107-2111`).
   Exterior faces already corroborate today through the bare `reolinkpatio` / `madroneptultra` cameras, so the flip
   adds no new class.
4. **S8 presence pre-arrival (`presence.py:5326`).** It fires only when the camera's person sensor is in a zone
   tracker. The face must also map through `_find_person_entity_from_face` (`:5480-5496`), which is an exact
   `person.<name>` match, plus a 30 s freshness check and a 60 s debounce. Checked against live `tracked_persons`:
   "Jaya", "Ziri" and "Ezinne" map; "Oji" does not map (no `person.oji`), and neither does "Ojini". **So "Ojini" cannot
   produce a wrong-identity pre-arrival for Oji.** A Frigate misrecognition can produce one, and it can do that today
   on 12 cameras. This consumer is also where the fix is most valuable: the doorbell, entry and garage cameras where
   arrivals happen are all among the 17 skipped today.

Weighing the two options: the shadow version buys a count we can already get from the recorder, and it adds 14 days
of drift plus a second Tier-2 cycle. The live version introduces no new kind of logic. Every affected consumer
already runs these exact semantics on 12 cameras. The one trust path with real stakes (S7) is one-directional, and
INV-4 pins that direction with a mutation-anchored test. The marginal risk is small and bounded. The marginal benefit
is face pre-arrival at the house's real arrival cameras plus less phantom-guest pressure in playroom. Live wins.

**Acceptance criteria and trip-wire** (now in plan D3): INV-4 test parametrised over fresh/stale/absent/exception;
bare cameras identical under the flip; the enhanced overwrite proven; live `face_source_device_derived_cameras` plus
a playroom `count-1` observation. No new NM anomaly: the failure direction is a missed guest, not a false GUEST, and
the kill switch plus counters are enough. If D0 finds a passthrough or guest name on an interior camera at a
material rate, ship with the constant False and record why in the README. Do not soak.

## 4. Summary

| Severity | Found | Fixed in plan | Carded / non-goal |
|---|---|---|---|
| HIGH | 2 | 2 | 0 |
| MED | 3 | 2 | 1 (F-5) |
| LOW | 2 | 1 | 1 (F-6) |

Bug classes: unpinned fallback / coincidental equality (F-2), undiscriminating acceptance (F-3, F-4), soak as gate
(F-1), namespace leak (F-6), unverified premise (F-7). QUALITY_CONTEXT candidate: none new. F-2 is an instance of
the existing coincidental-equality memo.

Board: FACE-SOURCE-SKIP-FIX-FLIP-1 → done (folded). F-5 and F-6 still need cards; the orchestrator mints them after
an adjacency sweep.
