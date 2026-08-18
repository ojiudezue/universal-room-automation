# URA Kanban - generated view

> **GENERATED - do not hand-edit.** Source of truth is `docs/planning/kanban.data.yaml`. Regenerate via `python3 scripts/kanban_render.py`.

_Generated: 2026-08-18T13:59:24-05:00_ - _Data commit: `8272f4b4e282`_ - _last_reconciled: 2026-08-18_

**Hosted:** https://urakanban.phalanxmadrone.com
**Artifact:** https://claude.ai/code/artifact/5748808f-5f16-41e8-a455-c3c59ed40149

## Columns

| Column | Count |
|---|---:|
| 📥 Inbox | 6 |
| 🧭 Pre-planning | 6 |
| 📝 Planned | 1 |
| 🔨 In progress | 1 |
| 🔍 Review | 0 |
| 🚀 Shipped (organic open) | 36 |
| ⏸️ Waiting on operator | 3 |
| ⏳ Waiting on me (Claude) | 1 |
| 🅿️ Parked | 8 |
| ✅ Done | 25 |
| ❓ Other | 20 |

## 📥 Inbox (6)
_raw capture_

### `ROADMAP-STALE-AGENTIC-LAYER-1` - Roadmap is stale (says v4.0.0 next; we are at v5.80.0) + the room-to-room agentic layer is unplanned
thread: **planning** - status: **inbox** - approval: **unreviewed**
_created 2026-08-18 02:45 · updated 2026-08-18 02:30 · initial_
- **Problem / Solution:**
  - Problem: ROADMAP_v11.md (written at v3.22.0) says "Next: Bayesian Predictive Intelligence v4.0.0" but we are at v5.80.0 — ~2 major versions and dozens of cycles (energy arbitrage, guest/census, presence fusion) shipped WITHOUT updating t...
- **Why:** A stale roadmap means new work is scoped without a current north star, and the operator vision (agentic rooms) has no plan to execute against — it will stay a passing mention until it is a document.
- **Next:** Operator: is the room-to-room agentic layer a near-term priority? If yes, scope a VISION/epic doc on top of the hierarchical-memory foundation. Separately: refresh ROADMAP_v11 -> v12 to reflect v4-v5 reality.
- **Refs:** docs/ROADMAP_v11.md; docs/VISION_v7.md; docs/planning/ARCHITECTURE_hierarchical_memory.md; MEMORY-PROGRAM-EPIC
- **Forensic keys (1):**
  - `audit_ledger_2026_08_18`: AUDIT_roadmap_undone_worthwhile.md now provides the "already shipped" ledger for the roadmap rewrite: mark ROADMAP v9/v10/v11 + VISION_v7 + ROADMAP_REMAINING as HISTORICAL; most v3.22 "future" shipped under other names (arbitrage hardeni...

### `CENSUS-FACE-MISS-WATCH-1` - Census face-lookup misses ~12/tick on an empty house — investigate on occupancy
thread: **presence** - status: **inbox** - approval: **unreviewed**
_created 2026-08-18 00:34 · updated 2026-08-18 01:10 · initial_
- **Problem / Solution:**
  - Problem: after the v5.80.0 D2 fresh-face fix, the census reports face_lookup_missing_count = 12 per tick even with the house EMPTY (no faces to look up). It fails CLOSED so the count stays correct (no wrong -1 credit), but 12 cameras' fa...
  - Solution: on occupancy (Wed), check WHICH cameras miss and why — is the face path probing cameras that have no face sensor (benign, make it not count them) or failing to resolve a face sensor that exists (a real resolution gap to fix)? D...
- **Why:** The v5.80.0 fresh-face fix is supposed to REVIVE face dedup; a high miss rate could mean it only partially works. Not a correctness risk (fail-closed) but the fix's value depends on faces resolving.
- **Next:** On occupancy: confirm the count DROPS when residents are recognized. If it stays high with recognized residents present, investigate resolution. Optional: split the counter (absent vs no-face-now).
- **Refs:** docs/readmes/README_v5.80.0.md; reference_frigate1_retired_2suffix_permanent.md
- **Forensic keys (1):**
  - `interpretation_2026_08_18`: EXPLAINED: face_lookup_missing_count increments when a camera's face sensor reads unavailable/unknown/empty/none = "NO recognized face right now" (camera_census.py:2502), NOT only when the entity is absent. On an EMPTY house no camera ha...

### `FRIGATE-LEG-NAMING-1` - Frigate live/dead leg naming is INCONSISTENT across cameras — bare _person_occupancy is live F2 on interior, dead F1 on perimeter
thread: **security** - status: **inbox** - approval: **unreviewed**
_created 2026-08-18 02:05 · updated 2026-08-18 02:25 · initial_
- **Problem / Solution:**
  - Problem: after Frigate 1 was retired, the INTERIOR cameras were renamed (dead F1 -> _person_occupancy_f1retired, live F2 -> bare _person_occupancy) but the PERIMETER cameras were NOT (live F2 stayed _person_occupancy_2, dead F1 kept the ...
  - Solution: standardise the naming (rename perimeter to match interior, or vice versa) OR make URA resolve the live leg by recency/registry never by name. Verify URA's resolver + the census/perimeter paths pick the LIVE leg for BOTH groups...
- **Why:** A name that means opposite things on different cameras is a latent silent-failure generator — it already caused me to misread interior cams as "Protect-only" and underlies the census/perimeter corroboration work.
- **Next:** LATENT LOW (no live bug). Future: make _prefer_canonical tiebreak by recency not name. No action now.
- **Refs:** reference_frigate1_retired_2suffix_permanent.md (corrected); camera_resolver.py:214; PERIMETER-PHANTOM-XCORR-1
- **Forensic keys (1):**
  - `audit_verdict_2026_08_18`: AUDIT (AUDIT_frigate_dead_leg_correctness.md): NO dead-leg reads. The dead F1 legs are FULLY REMOVED from the registry (404), not frozen-present — so the naming inconsistency causes NO live correctness bug. Every read site is registry/st...

### `PERIMETER-PHANTOM-XCORR-1` - Perimeter person alerts fire with no person in the snapshot, sent twice, and not cross-checked across NVRs
thread: **security** - status: **inbox** - approval: **unreviewed**
_created 2026-08-17 23:58 · updated 2026-08-18 02:40 · refined_
- **Problem / Solution:**
  - Problem: a single perimeter camera crying "person" pages at FULL severity (CRITICAL when the house is away) even when no other camera watching the area agreed — because the alert records which cameras fired but throws that agreement away...
  - Solution (Tier 3, NARROW remit per operator): make the already-recorded cross-camera/NVR agreement MATTER to the notification severity — a single-source detection DEMOTES (floor LOW, never silenced, so a lone-camera real threat still pag...
- **Why:** Perimeter alerts are a security surface — false alarms train the operator to ignore them (alert fatigue), and a double-send doubles the noise. Cross-NVR correlation is the same principle the operator just mandated for cycle-3 face ID: ne...
- **Next:** Plan the Tier-3 narrow cycle: wire _sensor_engine agreement -> severity (single-source demote floor LOW, corroborated keep/raise; single-NVR cameras fall back to track-linker confidence) + dashboard surfacing. Separately: BB dummy-Apple-...
- **Tags:** tier-3
- **Refs:** custom_components/universal_room_automation/perimeter_alert.py; EXTERIOR-GUEST-EGRESS-1 (cross-NVR theme)
- **Forensic keys (14):**
  - `operator_note`: Operator 2026-08-17: "either phantom detections or the snapshot was delayed. Are they properly cross correlated? I believe Camera <silver?> does this for free." (term "Camera silver" unclear — operator believes an NVR/product already doe...
  - `evidence`: 4 iMessage screenshots (IMG_6989-6992, 2026-08-16 alerts). Sensors: binary_sensor.hot_tub_person_occupancy_2 + binary_sensor.front_side_ptz_person_occupancy_2 — note the _2 Frigate-2 migration suffix, same class as the census fix.
  - `code_verified_2026_08_17`: CODE CHECKED (perimeter_alert.py). FINDINGS: (1) Multi-leg logic (:449-558) is COVERAGE + DEDUP, not corroboration — it subscribes to every integration on a camera (Frigate base + _2 + Protect) and dedups them; legs are OR'd, so ANY sing...
  - `tier`: Tier 3 — narrow remit
  - `db_verified_2026_08_17`: BY-HAND DB VERIFY (recorder, 2026-08-16 windows): BOTH alerts were DEFINITIVELY SINGLE-SOURCE. At 15:15:56 UTC ONLY binary_sensor.hot_tub_person_occupancy_2 fired — no other NVR. At 15:21:16 UTC ONLY front_side_ptz_person_occupancy_2 fir...
  - `double_send_corrected_2026_08_17`: CORRECTION (operator): the "double-send" is NOT a URA dedup bug. BlueBubbles texts the operator through his OWN number, so each message shows once as SENT and once as RECEIVED on the same thread = own-number loopback. URA sends ONCE. Fix...
  - `remit_2026_08_17`: OPERATOR SCOPE 2026-08-17: "Tier 3 work with a very narrow remit to make thrown away corroboration matter to notifications. And any dashboard work." So: (1) wire the existing _sensor_engine agreement telemetry (:537-538) into the severit...
  - `corroboration_definition_correction_2026_08_17`: CORRECTION (operator caught orchestrator over-claim). The 08-17 "multi-camera corroboration" claim was WRONG: front_side_ptz (exterior) co-fired with master_hallway/upstairs_hall/staircase/garagehallway (INTERIOR) — but those interior ca...
  - `dual_nvr_disagreement_proof_2026_08_17`: CORRECTION + STRONG PROOF (operator: "Nah Unifi and frigate 2"). hot_tub + front_side_ptz are DUAL-NVR, both legs LIVE: Protect (_person_detected, ~120-150 changes, last 02:50) + Frigate-2 (_person_occupancy_2, last 02:50). (Third leg _p...
  - `agreement_rate_measured_2026_08_17`: QUANTIFIED (front_side_ptz, 5 days): Frigate-2 (_person_occupancy_2) = 479 on-events; Protect (_person_detected) = 51 on-events. Agreement: 35 of 51 Protect events (69%) have a Frigate-2 within 60s. But from Frigate-2's side, only ~35 of...
  - `fleet_pattern_2026_08_18`: FLEET SAMPLE (13 dual-leg cameras, 5d, Frigate-2/Protect on-event ratio): front_side_ptz is an ISOLATED OUTLIER at 11.4x (455 vs 40). Every other dual-leg camera is 0.56x-3.4x, and MOST have Protect firing MORE than Frigate (garage_a 0.5...
  - `fleet_correction_2026_08_18`: OPERATOR CORRECTIONS 2026-08-18: (1) "All unmasked at the moment" — the front-PTZ mask/zone hypothesis is WRONG; no camera is masked. front_side_ptz 11.4x over-trigger cause is UNKNOWN (candidate: PTZ MOVEMENT — a panning/zooming PTZ cre...
  - `dead_leg_claim_retracted_2026_08_18`: RETRACTION: earlier notes said the dead Frigate-1 bare leg is a "stale corpse leg counted as coverage" that skews leg-agreement telemetry. WRONG — the audit found the dead F1 legs are REMOVED from the registry, so resolve_detection_legs ...
  - `ptz_rebooted_2026_08_18`: Operator REBOOTED the front PTZ 2026-08-18 (~02:40). Re-check the front_side_ptz Frigate-2/Protect ratio (was 11.4x, sole fleet outlier) after the reboot — if it drops toward the fleet norm (~0.5-1x), the over-trigger was a PTZ state/mot...

### `GUEST-ROOM-LOCATION-MATCH-1` - Precondition for designating a guest room: person location must match CONF_ROOM_NAME (D2-INFO-2)
thread: **presence** - status: **inbox** - approval: **unreviewed**
_updated 2026-08-17 23:25_
- **Problem / Solution:**
  - P1 `_is_known_person_in_room` excludes a resident by comparing person_coord.data[name]["location"] against CONF_ROOM_NAME. `_resolve_person_room` no-mapping fallback returns the raw bermuda_area string. If a room is flagged is_guest_room...
- **Origin:** 2026-08-17 - Review D2 (guest_census_review_D2_completeness.md) INFO-2, surfaced re-reviewing the repaired oracle.
- **Why:** Under D2 the room set is load-bearing; a designation whose location vocabulary does not match makes the sole safety check inert for that room.
- **Next:** VERIFIED PASSING (pre-deploy check 2026-08-17): live person locations are CONF_ROOM_NAME verbatim ("Garage A", "Breakfast Nook"); both designated rooms map correctly (guest_bedroom_2->"Guest Bedroom 2", bedroom->"Guest Bedroom 1"). The e...
- **Refs:** docs/reviews/code-review/guest_census_review_D2_completeness.md; custom_components/universal_room_automation/domain_coordinators/presence.py

### `GUEST-IDENTITY-PHONE-LEFT-BEHIND-1` - Guest-room identity exclusion is BLE-only, so a resident without their phone arms GUEST after 30 min
thread: **presence** - status: **inbox** - approval: **unreviewed**
- **Problem / Solution:**
  - P1 `_is_known_person_in_room` reads person_coord.data[name]["location"], which is Bermuda BLE-sourced (person_coordinator.py:471-541, 1036-1096). A resident physically IN the guest room whose phone is elsewhere — or who carries no BLE be...
- **Origin:** 2026-08-17 - Confirmed by the oracle-fix builder on orchestrator instruction to report-not-fix; surfaced when the operator noted "The guest room presence known person exclusion via BLE is crucial and good finding".
- **Why:** Under D2 this exclusion is the SOLE safety check between guest-room occupancy and GUEST mode, so its blind spots are guest-mode false positives. The GUEST_KNOWN_STICKY_S=120 latch shipped in the oracle fix absorbs BLE FLAP but does nothi...
- **Next:** After the guest-census cycle ships and the repaired oracle has organic evidence: quantify first — how often does a resident occupy a designated guest room while BLE places them elsewhere? Measure before designing.
- **Refs:** custom_components/universal_room_automation/domain_coordinators/presence.py; docs/readmes/README_v5.78.0.md

## 🧭 Pre-planning (6)
_idea being decomposed_

### `ROOM-NAME-UNIQUE-1` - Room rename has no name-uniqueness guard — collision collapses name-keyed maps (two rooms fold into one occupancy bucket)
thread: **presence** - status: **pre_planning** - approval: **unreviewed**
- **Origin:** 2026-08-14 - ROOM-NAME-DESYNC-1 Review C adversarial find (D-MED-1): rename Room A to an existing Room B name — zero validation; _room_to_zone dict + ZonePresenceTracker.room_names + substrate bucket keys all name-keyed -> silent overwri...
- **Why:** Join-key uniqueness is an unenforced invariant every name-keyed tier map depends on.
- **Next:** Small cycle after v5.75.0; consider folding into the next config-flow-touching batch.
- **Forensic keys (1):**
  - `fix_sketch`: _check_room_name_unique in async_step_basic_setup -> async_show_form error on collision (~15 LoC, Tier 1-2). Live-validation D-block for the rename cycle includes a do-not-rename-to-existing sanity note meanwhile.

### `SENSOR-FANINDEP-1` - Role matrix needs a fan-independence axis — 10GHz motion-mmWave fleet is corroborator-grade for stuck but NOT for fan-demotion
> **⚡ OPERATOR: approve — pending apply** (at 2026-08-18T03:19:40.142Z)
thread: **presence** - status: **pre_planning** - approval: **unreviewed**
- **Origin:** 2026-08-14 - operator: the Hobeian "Millimeter wave motion detection" units (~20, transit areas) are 10GHz functional-PIRs (still-blind, long range). Registry confirms 3 Hobeian classes. But the Upstairs Guestroom unit of this EXACT mode...
- **Why:** STUCK-SENSOR-1 (v5.75.0) role layer accepts list-derived motion kind as corroborator — correct for non-fan stuck pathology, fails-agree (=status quo, no regression) under fan latch. The deferred D5 role-migration should add fan-independe...
- **Next:** Fold into the STUCK-D2-DEMOTION-ROLE-MIGRATE-1 follow-up (D5); probe result first.
- **Forensic keys (1):**
  - `measurement_first`: Passive recorder probe queued: does the NEW Living Room 10GHz unit latch the tower fan on its next run? (Placement/sensitivity may differ from Guestroom.) Result gates how urgent the axis is.

### `PATHBETA-VESTIGIAL-1` - Path-beta infrastructure is now dead-code-like after D2b — scoped cleanup (reviewer B: do NOT bundle into PATH-ALPHA)
thread: **presence** - status: **pre_planning** - approval: **unreviewed**
- **Origin:** 2026-08-16 - PATH-ALPHA review B finding F2 (62820d23c): after the relaxed-predicate retirement, path-beta infra at presence.py:1146-1215 + call site :5787-5799 is vestigial — lost_away_persons_present=False from the sole caller, immedia...
- **Why:** Correctness is preserved (beta can only echo alpha or suppress; cannot fire spuriously), so this is hygiene not a defect. Reviewer B explicitly recommended a separate scoped cycle rather than bundling — bundling would have grown a Tier-2...
- **Next:** Scope after PATH-ALPHA ships and its organic proofs land: delete or collapse the vestigial beta limbs with test migration, or document why they stay.
- **Refs:** docs/reviews/code-review/path_alpha_review_B.md

### `TABLET-FLEET-1` - Wall tablet fleet: URA integration (sensors, wake-on-occupancy, room quick-actions)
thread: **tablets** - status: **pre_planning** - approval: **unreviewed**
- **Origin:** 2026-08-08 - operator: master tablet upgrades tested and working (sensors, lights, all over MQTT); thinking house-device tablet control, wake on URA room occupancy, conditional room quick-actions. NO ACTION YET - thoughts requested.
- **Next:** operator thoughts/ruling; then likely sequence = (1) consume tablet lux/temp/humidity in URA, (2) wake-on-occupancy with night dimming + per-room opt-in, (3) room-scoped dashboard quick-actions as bounded overrides
- **Tags:** institutional-context, measure-before-build, marginal-benefit
- **Forensic keys (3):**
  - `repo`: ~/Code/wall-tablet (HALedController, v1.3 versionCode 5, 2026-08-01)
  - `verified_capabilities`: Per-room MQTT identity already fleet-safe: clientId wall-tablet-<room>, topics home/wallpanel/<room>/{led,sensors,status}; LWT availability; self-registers via MQTT Discovery (no YAML).
  - `orchestrator_assessment`: HIGHEST VALUE IS THE SENSORS, NOT THE CONTROL SURFACE. Per-room lux is a first-class input URA's lighting logic already consumes; a tablet in every room is a lux+temp+humidity fleet arriving for free. That likely beats the quick-action U...

### `BOOTSANITY-1` - Boot-sanity allowlist guard cannot fire on a cold boot
thread: **camera** - status: **pre_planning** - approval: **implied**
- **Origin:** 2026-08-07 - found during v5.61.0 live validation — I nearly read its silence as proof of success
- **Why:** The F1(e) guard runs at the END of PerimeterAlertManager.async_setup() and is gated on `_linker_now` being present — but the linker registers AFTER that setup returns, which IS the bug. So on every cold boot it short-circuits and never w...
- **Next:** move the check into the READY handler; pin with a test that asserts the WARNING fires when install fails
- **Tags:** no-fabrication-verify, mutation-drill
- **Parsimony:** [BUILD] the tripwire for a CRITICAL class of bug is unreachable on the path that matters
- **Forensic keys (1):**
  - `fix`: re-run the sanity check from the READY handler AFTER the install attempt (and/or on a delayed post-boot check). Mutation drill: neuter the install -> the sanity WARNING must fire.

### `TEST-1` - Boot-time shadow diff (legacy vs resolver leg set)
thread: **resolver** - status: **pre_planning** - approval: **implied**
- **Origin:** 2026-08-07 - we took hardened surface and gave it new methods; something is bound to fail
- **Why:** live tripwire for silent coverage shrinkage that unit tests miss
- **Next:** WARN if a camera's new leg set doesn't superset legacy base+_2
- **Tags:** mutation-drill
- **Parsimony:** [BUILD] a camera's leg set silently shrank vs the retired helpers

## 📝 Planned (1)
_has plan / acceptance_

### `EGRESS-INTERIOR-COUNT-REINFORCE-1` - Use exterior->interior egress transitions to STRENGTHEN interior count accuracy (scope 2 of egress)
thread: **presence** - status: **planned** - approval: **pre_approved_gated**
_updated 2026-08-18 10:05_
- **Problem / Solution:**
  - P1 the interior census derives from cameras+BLE+face and does not currently consume the fact that a specific person was OBSERVED crossing an egress from outside to inside. That crossing is strong, causal evidence a body entered the inter...
- **Origin:** 2026-08-17 - Split from the egress design discussion: identity-on-egress (scope 1) is a prerequisite; using the resulting exterior->interior transitions to reinforce the interior headcount is scope 2.
- **Why:** The gate is deliberate: reinforcing interior count with egress data is only sound if the egress identity signal is itself accurate. Building it on an inaccurate scope-1 would inject a new error source into the interior count — the exact ...
- **Next:** BLOCKED on EXTERIOR-GUEST-EGRESS-1 D1 ship + accuracy proof. Then: measure how often egress crossings are NOT already reflected in the interior count (the gap this would fill) before designing.
- **Refs:** docs/planning/PLANNING_exterior_guest_egress.md; depends-on: EXTERIOR-GUEST-EGRESS-1
- **Forensic keys (2):**
  - `d0_impact_2026_08_17`: D0 probe impact: the gate ("D1 identity accurate") CANNOT be met via faces — face coverage at egress is ~7% even post-suffix-fix. So the identity-based interior-count reinforcement is not viable on current sensing. IF cycle 3 rescopes to...
  - `coverage_ceiling_2026_08_18`: CORRECTION 2026-08-18 (operator): the ~7% figure is NOT a coverage ceiling and must not be cited as one. It came from PROBE_protect_face_egress.md which measured the WRONG camera (front door madrone_g6_entry). Most family entries are via...

## 🔨 In progress (1)
_being built_

### `MEMORY-PROGRAM-EPIC` - EPIC — Hierarchical Entity Memory: every node (room/zone/house/coordinator) owns consultable, compressed history behind one queryable interface
thread: **memory** - status: **in_progress** - approval: **explicit**
_created 2026-08-05 00:00 · updated 2026-08-18 02:20 · refined_
- **Problem / Solution:**
  - Problem: we wanted every part of the house (each room, zone, the whole house) to keep a usable memory of what happened to it, instead of events scattered and never summarised. Solution: build it in stages — the raw event writers, then th...
- **Origin:** 2026-08-02 - Operator concept -> VISION + ARCHITECTURE + MVP doc set (all finalized 2026-08-02, self-critiqued DRAFT v2).
- **Why:** Program-level card so the memory work has a home; children carry the stages. URA composition (devices->rooms->zones->house) applied to TIME.
- **Next:** Epic foundation DELIVERED (writers + compactor live). Remaining is optional/parked (zone_phantom). Consider closing the epic to done and opening a new epic for the room-to-room agentic layer when that becomes a priority.
- **Refs:** docs/planning/VISION_hierarchical_memory.md; docs/planning/ARCHITECTURE_hierarchical_memory.md; docs/planning/MVP_hierarchical_memory.md; docs/planning/AUDIT_memory_handbuild_study_a.md; docs/reviews/code-review/memory_mvp_tier2db.md; docs/planning/AUDIT_memory_retro_value.md
- **Forensic keys (2):**
  - `stages`: Stage 0 hand-build: DONE 2026-08-02 — AUDIT_memory_handbuild_study_a.md (Study A hand-ledger; kill gate PASSED, operator: "every")
  - `completion_2026_08_18`: EPIC ESSENTIALLY COMPLETE: Stage-1 writers (D4-D7) shipped v5.78.0; Stage-2 compactor shipped + running nightly (14 memory_facts 02:30 CT 08-17); MEMORY-WRITERS-1 substantially shipped (top-2 already live). Only optional remainder: zone_...

## 🔍 Review (0)
_under review_

_(none)_

## 🚀 Shipped (organic open) (36)
_live, awaiting proof_

### `EXTERIOR-GUEST-FACE-FASTFOLLOW-1` - Face-identity arm for exterior->interior arrival — Protect Alarm Manager webhook -> HA -> family-room/garage named recognition
thread: **presence** - status: **shipped_organic** - approval: **explicit**
_created 2026-08-18 00:55 · updated 2026-08-18 02:25 · initial_
- **Problem / Solution:**
  - Problem: to know an UNKNOWN vs KNOWN person entered, we need face IDENTITY on the arrival path. The front-door cam sees no named faces, but people enter via the GARAGE into the FAMILY ROOM, where Protect DOES recognize residents by name ...
- **Why:** Completes the "build both" intent: the face-independent arm (cycle 3) says SOMEONE arrived; this says WHO (known resident vs unknown), which is the actual guest/security discriminator.
- **Next:** HOLD: consultation (duplicate-vs-complementary) running -> report to operator -> operator go -> then build.
- **Refs:** docs/planning/RESEARCH_protect_face_to_ha.md; EXTERIOR-GUEST-EGRESS-1
- **Forensic keys (8):**
  - `webhook_live_2026_08_18`: OPERATOR 2026-08-18: the Protect Alarm Manager face webhook is LIVE. So the recommended path (4b) precondition is MET. Next probe-first step: capture ONE real face POST (HA webhook trace / the ura_face_identified event) to confirm the na...
  - `webhook_verified_2026_08_18`: WEBHOOK RECEIVING SIDE VERIFIED: automation.ura_kp_face_webhook_probe (webhook_id ura_kp_face_probe, local-only POST) captures payloads verbatim -> ura_kp_face_probe_received event + system_log. Test POST returned 200 and logged the payl...
  - `promoted_2026_08_18`: PROMOTED to the PRIMARY cycle-3 build (operator: "let's build it first and see"). Reframe: we ALREADY have single-source identity via Frigate-2 face (sensor.<cam>_last_recognized_face_2, resolvable after v5.80.0 D2). Protect face (via th...
  - `prebuild_consultation_2026_08_18`: CONSULTATION DONE (AUDIT_egress_face_identity_prior_art.md, 1ff87322b) — VERDICT: COMPLEMENTARY, not duplicate. (1) EgressDirectionTracker resolves DIRECTION only; person_id hard-coded None at both emit sites (transit_validator.py:1106,:...
  - `plan_2026_08_18`: PLAN PLANNING_egress_face_identity.md — Tier 2-DB. SPLIT: D1 (ship now) Frigate person_id stamp (transit_validator.py:1106/:1121) + census union fuse (camera_census.py:1855) reusing existing face readers; D2 (gated on Wed payload) Protec...
  - `d2_gate_2026_08_18`: D2 (Protect corroboration) gate: NO cron (operator: "don't cron, just fire it yourself best you can"). The probe automation fires ura_kp_face_probe_received + logs the payload verbatim; the HA RECORDER durably retains that event+payload ...
  - `column`: shipped_organic
  - `l1_validated_2026_08_18`: SHIPPED v5.81.0 + LIVE. L1 PASS (boot clean, zero URA ERROR; switch OFF/dormant byte-identical — egress_identities_stamped=0, census as v5.80.0; observability attrs egress_face_ids_active + egress_identities_stamped live on persons_enter...

### `STUCK-SENSOR-1` - Flapping mmWave evades stuck-exclusion; fix via corroboration-gated exclusion at the ROOM tier
thread: **presence** - status: **shipped_organic** - approval: **explicit**
- **Origin:** 2026-08-09 - operator diagnosed a stuck Zigbee mmWave holding master occupancy; asked why I did not see it
- **Why:** URA's duty-cycle detector DOES catch stuck sensors and logs: 'Sensor <x> duty-cycle stuck (on-ratio exceeded over rolling window) — NOTIFY-ONLY, not excluded from occupancy'. It then KEEPS USING the stuck sensor for occupancy. Detection ...
- **Next:** BLOCKED on SENSOR-CAPABILITY-1 — do not scope exclusion until capability/role are separated, else the corroborator must be hardcoded as PIR (the defect). Then: per-room corroborator capability map from AUDIT_mmwave_only_rooms_2026-07-31....
- **Tags:** tier-2db, no-fabrication-verify, context-wide-scoping
- **Depends on:** SENSOR-CAPABILITY-1
- **Parsimony:** [BUILD] a stuck sensor silently fabricates occupancy and drives fans/HVAC/lighting in empty rooms
- **Forensic keys (19):**
  - `my_miss`: I READ these exact warnings hours earlier and dismissed them as 'routine, not a crash' — I was scanning for crashes, so a WARNING that was not a crash read as noise. The message named its own defect and I skimmed it. Rule: a warning that...
  - `gaps`: 1. NO CONSEQUENCE: stuck sensors are not excluded from the occupancy substrate.
  - `fix`: 1. Graduate D2 to exclusion behind the house-state gate the code always planned ('exclusion graduates in a later cycle behind a house-state gate'). The sleeping-person objection holds for bedrooms in sleep/home_night; it does NOT hold wh...
  - `CORRECTION`: 2026-08-09: my first version of this card was WRONG on three counts — I asserted mechanism from a LOG STRING instead of reading the code (operator: 'a log line does not reality make'). Corrected by verification: (1) it is NOT 'detection ...
  - `verified_findings`: ROOM TIER: continuous rule excludes but keys off _sensor_on_since, which a FLAPPING sensor resets each off-tick -> flapping never accumulates -> never excluded (coordinator.py:1960-1967).
  - `RETRACTION_2`: 2026-08-09 (second correction, operator challenge 'the stuck sensors are not correlated afaik'): I claimed the stuck sensors were a CORRELATED failure (same vendor/firmware/night) and built a 'falsified independence assumption' + 'closed...
  - `solution`: DISCRIMINATOR IS CORROBORATION, NOT HOUSE STATE. House state fails exactly in the hard case (asleep during home_night). A sleeping person pins the mmWave AND a corroborator; a stuck mmWave pins only itself.
  - `DEDUPE_2026_08_09`: Chatter/motion-chatter arrived as a candidate NEW card and was folded in here instead (adjacency check per kanban dedupe rule): same detector, same exclusion decision, same corroboration discriminator. No CHATTER-1 card exists or should.
  - `third_class_chatter`: CLASS 3 = CHATTER (transition-rate). A sensor oscillating at ~50% duty is invisible to BOTH shipped rules: every off-tick resets P22 continuous-on, and the on-ratio never reaches D2 85%. Evidence: Garage B ratgdo 24h = 3,769 off / 3,765 ...
  - `shipped_context`: D1-D4 ALL SHIPPED v5.35.0 (commit 0192ac2c3, 2026-07-28 23:18 CDT) + v5.35.1 hotfix + v5.35.2 observability. Do not re-scope them.
  - `approach`: PATCH A CENTRAL METHOD, NOT A FIFTH DETECTOR (operator 2026-08-09: "should not do this in isolation or it should be a patch of a central class/method" + "do the right thing unified or not"). Generalise _detect_duty_cycle_stuck into a per...
  - `FLEET_ROT_RETRACTION`: 2026-08-09 (third correction, operator challenge "I don't think a third of the fleet is bad"): I claimed a third of the corroborator fleet was dead, generalising B-2026-08-04-2' "5 of 13" — which is 5 of a 13-entry HAND-PICKED ADJACENCY ...
  - `D0_AUDIT_DONE`: 2026-08-09: docs/planning/AUDIT_mmwave_only_rooms_2026-07-31.md written (was owed since 07-31 as D0 of the mmwave Tier-3 cycle and never done; cycle shipped without it). Key results: 5 MMWAVE_ONLY rooms + Master Bedroom MMWAVE_NO_PIR = S...
  - `OPERATOR_DISPOSITIONS_2026_08_09`: ATHOM (Study A): CLOSED as a no-op. Operator: "Ignore athom now. It's a no op." URA already does not read it (options override every bucket); the ESPHome device entry stays. Do NOT re-raise, do NOT propose deleting the entry or cleaning ...
  - `rejected`: PROPAGATE STUCK STATE TO ZONE/HOUSE — I recommended this and then withdrew it under challenge ('is this flow upwards useful?'). If the room tier excludes correctly the corrected occupancy propagates naturally and upper tiers are right fo...
  - `amendment_approved_2026_08_13`: Operator approved the criterion-4 amendment (offline replay harness + hand-built supplement; runtime tap DROPPED — recorded in PLANNING_signal_trust_ledger_abstraction.md). Unblock path ACTIVE: build/ledger-golden-replay harness in fligh...
  - `harness_landed_2026_08_13`: Replay harness MERGED (fe9bfc845): P22 (13/5) + D2 (56/3, boot-settle unmodelled -> discount vs audit 13) FILLED from replay. Remaining criterion-4 work before this cycle builds: hand-built supplements for P24/P18/D1/CHATTER (operator si...
  - `approved_2026_08_13`: OPERATOR APPROVED (during AWAY-BLOCK-1 incident review: "Stuck sensor is approved"). Spec confirmed to operator: it ACTUATES (corroboration-gated exclusion at room tier), not notify-only. Taxonomy caution from the incident: fan-latch is ...
  - `build_dispatched_2026_08_13`: Plan rev-2 (plan review: HIGH corroborator-window-subsumed -> 900s + still-person test; P22 restore-poisoning boot guard; fixture emit-only-when-True + replay pre-deploy gate; merged-accessor pin). Build in flight (worktree). Criterion-4...

### `SENSOR-CAPABILITY-1` - Separate sensor CAPABILITY (hardware kind) from analytic ROLE — kind is currently the config bucket
thread: **presence** - status: **shipped_organic** - approval: **explicit**
_refined ×3_
- **Origin:** 2026-08-09 - operator ruling on whether bed presence moves bucket or code changes: "My instinct is code change so we don't have fixed config buckets. Sensor reality should not pin use and analysis reality in software. It should just tell...
- **Why:** VERIFIED: occupancy_substrate.py:81 _KIND_TO_CONF maps kind 1:1 onto the three CONF lists, and const.py:342 TIER1_KINDS = ("motion","mmwave","occupancy"). URA has exactly three sensor kinds and they ARE the three config buckets, so the h...
- **Next:** PLAN WRITTEN 2026-08-09 (docs/planning/PLANNING_sensor_capability_vs_role.md, 477 lines). Tier 3, four framing-disjoint reviews, operator checkpoint before deploy. AWAITING OPERATOR GO — Tier 3 shared primitive, not implied-approval elig...
- **Tags:** tier-3, institutional-context, no-fabrication-verify, context-wide-scoping, numbers-get-knobs
- **Blocks:** STUCK-SENSOR-1
- **Sibling of:** SIGNAL-TRUST-LEDGER (build-gated)
- **Parsimony:** [BUILD] hardware wiring pins analytic role, so the best available corroborator in a room cannot be used as one
- **Refs:** docs/planning/AUDIT_mmwave_only_rooms_2026-07-31.md (Finding 6 — root cause); docs/planning/PLANNING_mmwave_corroboration_tier3.md (Amendment 4); docs/planning/PLANNING_signal_trust_ledger_abstraction.md (Addendum 2026-08-09 — ledger assumed this layer); custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py:81; custom_components/universal_room_automation/const.py:335,342
- **Forensic keys (16):**
  - `root_cause_of`: Master Bedroom: the ideal discriminator (bed presence) is JUDGED instead of CONSULTED.
  - `unlocks_without_new_hardware`: Master Bedroom already HAS an ideal corroborator: the bed — independent failure mode, physically unspoofable — the moment role stops being pinned to the motion bucket.
  - `design`: KEEP the three CONF lists as the WIRING layer — no config migration, additive only.
  - `build_2026_08_09`: BUILT (worktree commit 141e60939) then REBASED onto current develop as c82290f68 on branch sensor-cap-rebase. STALE-BASE INCIDENT: the builder worktree was based on 57ba22942 (v5.50.2), 214 commits behind develop, so its green suite (19f...
  - `I1_DEVIATION_for_reviewers`: The builder KNOWINGLY deviated from byte-identity in one place and flagged it: for an entity in BOTH mmwave_sensors and occupancy_sensors (the P15 defensive case), pre-migration list-concat DOUBLE-SCORES it (same ring appended twice per ...
  - `build_notes`: A mutation drill initially PASSED, exposing dead code: the strong_evidence gate was unreachable for kind=bed (bed is not in _STUCK_CANDIDATE_KINDS, so it exits earlier). The builder added a test for the reachable path (operator declares ...
  - `TIER3_REVIEW_ROUND_2026_08_09`: A: SHIP w/ fix-ups — HIGH-A1 (validator accepted a capability with no kind, silently no-opping the cycle headline use case), MED-A2 (failure_mode unvalidated). Verified by reading: _CONF_PRECEDENCE matches occupancy_substrate._KIND_PRECEDEN...
  - `ORCHESTRATOR_ADJUDICATION`: B/C/D disagreed on ONE line. Resolved by reading source: _STUCK_CANDIDATE_KINDS = {mmwave, occupancy} excludes motion (sensor_role.py:73) and _CONF_PRECEDENCE resolves a motion+mmwave entity to MOTION, so CANDIDATE_FOR_STUCK returns Fals...
  - `FIXUP_2026_08_09`: bed359d5d, ff-merged onto sensor-cap-rebase. Fixed HIGH-A1, MED-A2, D-MEDIUM-1 (validator now rejects an override that would leave a motion-wired entity in neither loop), C-MED-1 (byte-identity anchor + a behavioural test driving product...
  - `ORCHESTRATOR_VERIFIED_2026_08_09`: Did NOT trust the reports (Tier-3 mandate). Personally: ff-merged; confirmed the dead branch and false comment are gone (0 occurrences); ran my OWN mutation on the load-bearing site (_CONF_PRECEDENCE inverted, py_compile clean) -> 7 NAME...
  - `AWAITING`: TIER-3 OPERATOR CHECKPOINT BEFORE DEPLOY (mandatory per CLAUDE.md). Not merged to develop.
  - `known_gap`: The misfiled-hybrid collision WARN has no dedicated test asserting the emit path (it fired incidentally in a drill). Would need _LOGGER mocking or caplog scaffolding on the coordinator logger. Say the word and it gets one.
  - `status_note`: plan complete; build gated on operator go
  - `invariant`: I1 — with no CONF_SENSOR_CAPABILITIES declared anywhere, get_all_room_kinds, every SIGNAL_SUBSTRATE_KIND_CHANGED dispatch, _room_provenance, _detect_duty_cycle_stuck's return set and every exposed entity attribute are BYTE-IDENTICAL to t...
  - `riskiest`: _detect_duty_cycle_stuck migration. Its positional signature (motion, mmwave, occupancy) is itself a legacy reification of _KIND_TO_CONF. An entity present in BOTH mmwave_sensors AND occupancy_sensors (the P15 defensive case, occupancy_s...
  - `DEDUPE_2026_08_09`: Four-surface adjacency sweep run before creating this card. Board: adjacent to STUCK-SENSOR-1 (which it now BLOCKS) — kept separate because the shared surface is OccupancySubstrate/TIER1_KINDS, not the stuck detector, and STUCK-SENSOR-1 ...

### `WATCHDOG-INERT-1` - Three of four v5.35.0 stuck-signal detectors are effectively inert (D3 structurally unreachable)
thread: **presence** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-09 - fell out of the ledger golden-fixture yield probe — the short buckets were short because the events never happen, which is a statement about the detectors, not about instrumentation
- **Why:** MEASURED over 7.46 d recorder + 14 d URA notification_log. D3 frozen-tracker is STRUCTURALLY UNREACHABLE: threshold FROZEN_TRACKER_DAYS=2.0 (const.py:3121) but longest HA uptime in-window is 1.02 d across 30 restarts (2.5 h median gap); ...
- **Next:** OPERATOR DECISION 2026-08-09: DROP D1/D3/P24 from the ledger migration set ("1 want to drop. Some are rare. Not a bad thing."). Ledger migration set reduces to M1 (P22), M3 (P18), M5 (D2) + M7 (P14, hand-built). Open sub-question the ope...
- **Tags:** no-fabrication-verify, measure-before-build, context-wide-scoping
- **Blocks:** SIGNAL-TRUST-LEDGER M4/M6 scoping
- **Parsimony:** [BUILD] three shipped detectors do not detect; one cannot detect by construction
- **Refs:** docs/planning/AUDIT_ledger_golden_fixture_yield.md (the probe + orchestrator escalation); custom_components/universal_room_automation/const.py:3099,3121
- **Forensic keys (16):**
  - `sharp_problem`: D3 cannot catch the incident it was built for. It exists because of the Ezinne 3-day frozen tracker; with HA restarting every ~2.5 h a 3-day freeze is invisible to a detector measuring uninterrupted in-memory last_updated age.
  - `root_cause_link`: Same defect STUCK-SENSOR-1 flagged and nobody pursued — "NO PERSISTENCE: any stuck-state tally resets on restart, and we restarted 7+ times today." The probe proves it is fatal for D3 rather than merely degrading.
  - `options`: FIX: measure staleness from a PERSISTED timestamp rather than in-memory last_updated, so restarts do not reset the counter. Restores D3 to its intended purpose.
  - `RESTART_VERDICT_2026_08_09`: RESOLVED — NOT a red flag. Authoritative events-table count is 26 (not 30; my earlier figure was a heuristic overcount that also caught config-entry reloads). ALL 26 were clean stops preceded within 300s by an explicit homeassistant.rest...
  - `D3_STILL_UNREACHABLE`: Corrected uptime stats CONFIRM it: median 3.43 h, mean 6.63 h, max 24.32 h (1.01 d) vs a 2.0 d threshold. Note the causality — D3 is unreachable BECAUSE we ship this often, so it will stay unreachable at this cadence. The fix is detector...
  - `D1_VERDICT_2026_08_09`: (i) CORRECTLY RARE — leave the thresholds alone. Interior hold distribution over 7.30 d: p50 0.004 h, p90 0.013 h, p99 0.044 h, max 0.27 h against a 3.0 h threshold (11x above max, ~68x above p99). All 7 interior candidates are live and ...
  - `GARAGE_CAMERA_RULING_2026_08_10`: OPERATOR: "No — garage cameras should feed only egresses and exterior. I fear it will be too noisy for interior listings." DECIDED: add camera.garage_a/garage_b to CONF_EGRESS_CAMERAS (perimeter_alert), NOT camera_person_entities. ACCEPT...
  - `D1_REAL_FINDING_coverage_not_calibration`: sensor.garage_b_person_count held >0 for 6.52 h and WOULD have crossed both rules — but camera.garage_b and camera.garage_a are in NO URA camera list (not interior, not perimeter, not egress), while "Garage B" IS a configured URA room. W...
  - `P24_VERDICT_2026_08_09`: (iii) STRUCTURALLY BLIND on its main leg — not a threshold problem. Duration precondition met 27 times across 7 rooms in 7.3 d (~3.7/day); the Tier-1 freshness skip suppressed 27 of 27 (100%). That 100% is a THEOREM not a statistic: any ...
  - `P24_DIAGNOSABILITY_DEFECT`: The NM row persists message="[audit]" with NO room name — identifying the firing room required a recorder attribute join. Cheap fix, real cost the next time one fires.
  - `BATCH_REVIEW_ROUND_2026_08_10`: b9975cf30 (P24 fix + D3 kill + dropdowns + constant split): A DO-NOT-SHIP — CRIT-A1: rebasing freshness on _last_pir_motion_time force-vacates the SIX no-PIR rooms at every 4h+ session (sleeping child in Jaya's room, nightly); the "27/27...
  - `FIXUP_IN_FLIGHT_2026_08_10`: Single consolidated pass: CRIT-A1 no-PIR guard (mirror _d2_motion_sensors_present; failsafe simply does not apply to no-PIR rooms); HIGH-A2 invariant "fires only when no live override AND PIR stale" + latch fix; C1/H1/H2/H3 REAL behavior...
  - `OPERATOR_DECISIONS_2026_08_09_round2`: GARAGE CAMERAS: "Yes pls. Or maybe to the egress list?" — ANSWERED: the two lists do different things and only ONE gives D1 coverage. CONF_CAMERA_PERSON_ENTITIES (interior) is what D1 scores (camera_census.py:1787,1803) and is ALSO consu...
  - `SEQUENCING_NOTE`: P24-fix and D3-kill both touch coordinator.py / person_coordinator.py. The SENSOR-CAPABILITY-1 fix-up is concurrently editing coordinator.py on sensor-cap-rebase. Queue these two BEHIND that merge rather than running them in parallel — w...
  - `operator_decision_2026_08_09`: DROP from migration. Rarity is not itself a defect — a detector guarding a condition that genuinely does not occur is working. This does NOT close the question of whether the thresholds are right; it only removes them from the ledger cyc...
  - `DEDUPE_2026_08_09`: Four-surface sweep: STUCK-SENSOR-1 is adjacent (shares the no-persistence root cause) but is about EXCLUSION POLICY for live detectors; this is about detectors that never fire at all — different problem, linked not merged. BACKLOG B-2026...

### `EV-SENSOR-CLEANUP-1` - EV sensor surface cleanup: remove dupe charge_rate sensors + wire per-plug real power (Emporia recovered) — next-deploy items, committed not parked
thread: **energy** - status: **shipped_organic** - approval: **implied**
- **Origin:** 2026-08-16 - Operator: "repair if not functional dupes; if so remove" + "dead emporia — which ones?" -> AUDIT_ev_sensor_surface.md (60105933a).
- **Why:** charge_rate_garage_a/b are strict-subset dupes of ev_charging_status power attrs (zero consumers verified) -> REMOVE (sensor.py:315-316 + classes + orphaned properties). Emporia outage ROOT-FIXED 2026-08-16: v0.12.2 boto3 pin conflict; v...
- **Next:** Ride the PATH-ALPHA cycle deploy: Tier-1 removal + per-plug wiring, per audit specs.
- **Refs:** docs/planning/AUDIT_ev_sensor_surface.md
- **Forensic keys (1):**
  - `live_validation_2026_08_16`: v5.78.0 LIVE 2026-08-16. L1 PASS (0 errors), L4 PASS (face_recognized_count + path_alpha_gate_source live on house-state sensor). L2 PASS-on-state / attribution organic: house is away with all 4 persons not_home and census 0 — but the tr...

### `HVAC-PRESET-FLAP-1` - HVAC zone preset flaps home<->away every 5-15 min during occupied evenings (survives Writer-B removal)
thread: **hvac** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-09 - operator: "The hvac zone is being set to away and there are/were people upstairs" — then "I've been seeing this issue from the moment we walked in", which falsified the first three mechanisms I proposed
- **Why:** MEASURED: nine home<->away preset cycles on zone_2 in two hours of confirmed occupancy, all inside coast mode. Presence was correct throughout. Writer B removal (v5.56.0) did NOT stop it — see P1P3 for the falsification. Real comfort cos...
- **Next:** Mechanism proven; this is now a DESIGN question, not a diagnosis. Decide the arbitration rule between the coast duty-limiter and occupied-zone comfort. Candidates: (a) exempt the limiter when the zone is occupied AND recovering from a la...
- **Tags:** no-fabrication-verify, measure-before-build, context-wide-scoping
- **Refs:** docs/planning/kanban.data.yaml card P1P3 (the falsification); custom_components/universal_room_automation/domain_coordinators/hvac.py:1569-1610 (reason ladder), :1660-1675 (ledger row), :2470-2492 (coast duty limiter)
- **Forensic keys (10):**
  - `DUTY_CYCLE_DEFINITION_2026_08_09`: PRECISE, read from source (hvac_const.py:392-394): DUTY_CYCLE_WINDOW_SECONDS = 20*60 (20-min ROLLING window); DUTY_CYCLE_SHED = 0.50; DUTY_CYCLE_COAST = 0.75. So coast permits 15 MINUTES OF COMPRESSOR RUNTIME PER 20-MINUTE WINDOW. Accumu...
  - `RETRACTION_2_max_runtime_minutes`: I earlier reported "max_runtime_minutes: 120 is the coast cap" and then "you hit the cap almost exactly when you noticed". BOTH WRONG. max_runtime_minutes is computed in energy.py:6907 from TIME REMAINING IN THE CURRENT TOU PERIOD — an u...
  - `RETRACTION_3_two_writers`: I framed this as "two URA writers disagreeing with no arbitration". WRONG. There is ONE mechanism. The home write is not another actor pushing back — it is the same effective_preset computation returning the house-state value once runtim...
  - `REFRAMED_PROBLEM`: If there is a defect it is NOT the cycling. Three narrower candidates, none Tier 3: (1) MECHANISM — duty cycling by toggling a user-visible comfort preset makes an energy action look like a presence failure; that misreading cost three ho...
  - `MEASURE_FIRST_GATE`: Operator: "Measure first for sure." AUDIT_hvac_duty_cycle_frequency.md in flight: how often runtime_exceeded fires per day/zone, how much of it is while OCCUPIED, EPISODE structure (10 flips in one evening != 10 flips over two weeks), an...
  - `LEDGER_RETRACTION_2026_08_09`: I carded a "reason ledger reads empty / diagnosability regression" finding. IT WAS FALSE and is fully RETRACTED. The v5.56.0 reason ledger works exactly as designed — my extraction script read a column named `details` when the actual col...
  - `MECHANISM_PROVEN_2026_08_09`: Two URA writers alternating with NO arbitration between them. From the ledger, zone_2, every row carrying persons=[ziri, jaya]: 23:34 home->away reason=runtime_exceeded       runtime=True 23:24 away->home reason=house_state_transition ru...
  - `my_process_failure`: I proposed three mechanisms in sequence from snapshots — "URA says home, device says away", then "the 120-min cap fired", then "it is coast" — and each fit the instant I was looking at and died on the next fact. The history query I ran F...
  - `DEDUPE_2026_08_09`: Four-surface sweep: P1P3 is the PARENT (closed, spawned this). STUCK-SENSOR-1 is a different flap (mmWave sensor stuck, not HVAC preset) — no merge. ARREST-SUNSET-1 shipped and is about override sunset, not oscillation. OVERRIDE-NOTIFY-1...
  - `toggle_retirement_2026_08_14`: Operator renamed the kill-switch -> "Coast Preset Preservation" (rides v5.75.0) and adjudicated it TEMPORARY CONTAINMENT, not a policy knob (nobody legitimately prefers the lying preset; the 2F offset Number is the real knob). RETIRE the...

### `ARREST-COMFORT-1` - Override arrester reverts occupant manual cooling requests with no comfort exemption
thread: **hvac** - status: **shipped_organic** - approval: **approved**
- **Origin:** 2026-08-09 - operator: "I think manual were kids trying to cool their space and the arrester stops them"
- **Why:** Observed tonight: zone_2 preset went to `manual` at 16:49 and again at 17:14 — the kids walking to the thermostat in an 80F room and asking for cooling. The override arrester reverted both within 10 and 5 minutes respectively. After 17:1...
- **Next:** Cycle A build after FAN-LAYER build slots clear (both touch hvac.py — SERIALIZE the builds; plan work done in parallel per operator mandate).
- **Forensic keys (11):**
  - `review_state`: Cycle A built (18b491e01, 28 tests, kids-replay authentic). Tier-3 4x reviews: B SHIP; A/C/D DO-NOT-SHIP with DISJOINT blockers — A-CRIT-1 occupancy gate read static zone_persons config list not live occupancy; D-CRIT-1 DPM apply ungated...
  - `sharp_problem`: A manual cool request, from an occupied zone, at 80F, during recovery from a 24h absence, is the single highest-quality signal in the building — a human walked to a wall and said they are uncomfortable. The arrester treats it as noise to...
  - `fix_direction`: Exempt (or substantially delay) arrest when the zone is occupied AND the manual change moves toward comfort AND the temp delta is large. Arresting inside 5-10 minutes is worse than not arresting at all — the occupant never feels an effec...
  - `operator_action_taken_2026_08_09`: temp_arrester_override switched ON and all three zones set to home at operator instruction. Verified: ceilings dropped 80 -> 76/77, all three cooling, runtime_exceeded cleared. Note the override has a 6h max life and sunsets on some hous...
  - `OPERATOR_DESIGN_2026_08_10`: DELAY chosen over exempt. Plus three design inputs verbatim-captured: (1) IDENTIFICATION QUESTION (operator): "how will this situation be identified specifically to widen the delay/grace?" — the predicate for "occupant comfort request" n...
  - `PLAN_2026_08_11`: PLANNING_arrester_comfort_delay.md. STAGED: Cycle A = predicate + SOC-gated flat grace + coast-precedence guard (~95% of the kids-incident benefit); Cycle B (graduated concession + approach-speed observer) PARKED with evidence trigger — ...
  - `PLAN_REVIEWS_2026_08_11`: Both NEEDS-REVISION (the protocol's first subject, and it paid): R1-H1 preset-writes clobber a granted setpoint on Bryant preset thermostats — INV-violating by construction, 9 emit sites unguarded; R2-H1 dual-setpoint predicate undefined...
  - `PROBE_2026_08_11`: D1/D2/D3 all GO. Qualifying events 44.4/wk (NOT rare — zone_2 = 43/49); SOC>=80 at ~50% of events so the gate is genuinely load-bearing; coast co-fire 13.6/wk -> D3 required; multi-thermostat zones = ZERO -> grant key simplifies to zone_...
  - `CYCLE_B_ESCALATION_DECISION`: Probe found Cycle-B's evidence trigger ALREADY MET (08-08 zone_2: 4 qualifying flips in 61 min). OPERATOR CALL: pull D4 graduated concession in-cycle, or keep staged? ORCHESTRATOR RECOMMENDATION: KEEP STAGED — the trigger being met justi...
  - `DEDUPE_2026_08_09`: Sweep: ARREST-SUNSET-1 (shipped) is about WHEN the override sunsets; OVERRIDE-NOTIFY-1 is about warning before expiry. Neither touches whether the arrester should fire against an occupant comfort request in the first place. HVAC-PRESET-F...
  - `organic_evidence`: shipwatch 2026-08-11: L3 pending — zero comfort_delay ledger entries in 14h (no qualifying manual yet); founding-case proof awaits next kid-thermostat event. Cycle B stays staged on it.

### `BLE-WARM-CREATE-1` - BLE re-creates bathroom occupancy inside the 10-min warm window on every toilet visit (v5.22.0 left this open by design)
thread: **presence** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-10 - operator in the master toilet; bathroom light came on briefly, reproducibly ("when I enter it"), during daytime despite only-when-dark
- **Why:** MEASURED from recorder attrs, two events this morning: 09:53:32 and 10:19:35, both occupancy_source=ble, ble_persons=[Oji], tier1_provenance all-False, fresh became_occupied_time (CREATE not extend), off again 41s/37s later. NOT a v5.22....
- **Next:** AWAITING TIER-3 OPERATOR CHECKPOINT: (a) go/no-go to merge+deploy; (b) the D-MEDIUM-1 option 1 vs 2 pick. Branch worktree-agent-afcf959feefd95587 @ c37d155c3, not merged.
- **Tags:** no-fabrication-verify, measure-before-build
- **Refs:** docs/readmes/README_v5.22.0.md (the reference cycle, same room, 2026-07-18); custom_components/universal_room_automation/coordinator.py:2646-2700 (two-leg admission); const.py:447 (BLE_MOTION_CONFIRM_MULTIPLIER=2)
- **Forensic keys (13):**
  - `mechanism`: Every toilet visit passes through the bathroom -> legitimate motion -> bathroom occupancy -> times out while operator sits in the toilet -> his BLE still resolves to the master_bathroom area (the toilet is inside the bathroom scanner foo...
  - `daytime_light_finding`: NOT a lux bug. sensor...masterbath_illuminance reads 8.5 lx live (cover 1 closed, interior room) -> lux_zone=dark is CORRECT. "Only when dark" is lux-based, not sun-based; the room genuinely is dark at 10am. Every occupancy row today car...
  - `third_writer_ruled_out`: 40 HA automations enabled; none targets master bathroom lights (closet + ziri/jaya/guest bathrooms have their own; master bath does not). URA sole writer.
  - `fix_directions_not_built`: (a) NARROW the motion leg to an actual handoff: admit BLE create only within ~1 tick (30-60s) of the occupancy-off transition, not 2x timeout from last motion. Smallest change; kills the reproducible case; still covers the documented pur...
  - `OPERATOR_CHALLENGE_2026_08_10`: "Why break the extend but not create rule at all? It seems like it created it, no?" — CORRECT. Leg (b) mechanically IS a create (occupancy off -> on via BLE alone, fresh became_occupied_time). Adjudication: (1) its DOCUMENTED purpose (ha...
  - `REVISED_RECOMMENDATION`: DELETE leg (b) rather than narrow it — restore the invariant to what its name claims. Review must: (i) mutation-verify the tick-ordering claim that chain covers the handoff (comment-trusted today); (ii) enumerate rooms WITHOUT mmWave (D0...
  - `LUX_RESOLVED_2026_08_10`: Operator: "bathroom is genuinely bright... I moved the hamper." MEASURED: lux flat ~12 lx ALL morning, then 11.7 -> 147.8 -> 201.4 -> 241+ in NINE SECONDS at 12:18:44-53, stable ~246 since. The HAMPER occluded the sensor. Every light act...
  - `OPERATOR_GO_2026_08_10`: DELETE approved: "Unless you see a livable scenario we missed, delete it... It is occupancy so go big on reviews and quality." Missed-scenario check done: even PIR-only rooms hold a still occupant via the chain leg while BLE is present a...
  - `REVIEWS_2026_08_10`: A SHIP (1 LOW: const doc described the D2 kill by the WRONG MECHANISM — outer guard, not threshold-collapse; the 4th false-mechanism comment this week, caught in the commit that retired three others). B SHIP (boot regression RULED OUT: _...
  - `FIXUP_2026_08_10`: c37d155c3 on the build branch: A-LOW-1 doc line + B-M-B1 fossil deleted with tombstone. Orchestrator drill: reintroduced a 600s window myself -> 10 red; restored -> 21 green. Full suite 22 failed / 8544 passed / 2 xfailed — failing names...
  - `D_MEDIUM_1_OPERATOR_DECISION_NEEDED`: The invariant is AMBIGUOUS at the restart boundary. _last_occupied_state restores True across a reboot with NO requirement of any in-process tier-1 evidence before the chain leg re-admits. Legal repro: occupant walks out during the 30-90...
  - `DEDUPE_2026_08_10`: Sweep: v5.22.0 cycle is the PARENT fix (cold strobe) — this is its documented residual, not a duplicate. STUCK-SENSOR-1/chatter unrelated (different detector). Fusion-library section 7 intent/evidence is the (b)/(c) design home, linked n...
  - `organic_evidence`: shipwatch 2026-08-11: L2 strongly positive — 22h/~28 Master Bathroom cycles, ZERO ble-source occupancy post-deploy; last strobe was 3min PRE-deploy. Confirm at 48h.

### `FAN-MANUAL-1` - Fans have no manual-ON override: room temp logic reverts a hand-switched fan ("below threshold")
thread: **hvac** - status: **shipped_organic** - approval: **explicit**
- **Origin:** 2026-08-10 - "I cant seem to turn on the living room fan manually without it turning off by itself."
- **Why:** EVIDENCE (ura_activity_log): Living Room fan turn-offs are [room/fan_off] "Fans off (below threshold, 77F)" — the room-tier temperature comfort controller reconciles fan state to its own verdict and does not recognise a manual ON. v5.31....
- **Next:** CONSOLIDATED FIX-UP IN FLIGHT: chokepoint behavioral test (no fixture zeroing) + zone-sweep/ pre-arrival guards + reconciler defer+marker (mark_fan_on_issued helper for ALL URA ON sites) + ONE coherent boot-seed policy (tick-1 ON → hold ...
- **Tags:** context-wide-scoping, institutional-context, numbers-get-knobs
- **Forensic keys (7):**
  - `scope_note`: Operator mandate: context-wide. Fan touchpoints to inventory before design: room comfort fan control (handle_temperature_based_fan_control + the below-threshold revert), v5.31.0 manual-off cooldown (the precedent + its knob), fan_recheck...
  - `PLAN_2026_08_10`: docs/planning/PLANNING_fan_manual_on_override.md. Shape: plain timed manual-ON hold symmetric to the v5.31.0 manual-OFF cooldown — graduated-concession REJECTED for fans (binary comfort, no setpoint to negotiate; margin ~0). Detection RE...
  - `OPERATOR_RULINGS_2026_08_10`: Both as recommended: (1) FRESHEST WINS — a manual-ON newer than the sleep transition survives it; (2) fan-recheck OFF is ALLOWLISTED via trigger_path, hold remaining-time preserved across the pause. Build fully approved (build-implies-sh...
  - `REVIEW_ROUND_2026_08_11`: ALL THREE DO-NOT-SHIP — 1 CRIT + 6 HIGH, disjoint framings, zero overlap. C-CRIT-1: the HVAC chokepoint gate (the plan's headline enforcement) had ZERO coverage — deleting it left 8,564 tests green, because every _set_fan_state-reaching ...
  - `DEDUPE_2026_08_10`: Sweep: ARREST-COMFORT-1 is the SIBLING (thermostat side of the same class) — linked not merged; fan-recheck cards/plans are about mmWave truth not manual intent; humidity-fan backlog (PowerView memo) is spike detection; B-2026-08-03-8 fl...
  - `organic_evidence`: shipwatch 2026-08-11: L2 PENDING ON OPERATOR — manual Living Room fan-ON test still owed; no organic 1h+ manual hold observed yet (both v5.68.0 hold + v5.70.0 delegation ride this one test).
  - `organic_evidence_2`: OPERATOR CONFIRMED 2026-08-11: "Living room fan is working afaik" — manual fan use no longer self-cancels. Closes v5.68.0 L2 + v5.70.0 L3 + v5.72.0 L4 (the one shared operator test).

### `KHOST-2` - Operator disposition buttons + drag-between-states on the hosted board
thread: **tooling** - status: **shipped_organic** - approval: **approved**
- **Origin:** 2026-08-11 - operator: "We have to add operator disposition buttons so the operator can communicate through the board. drag btw states | done | deferred | declined"
- **Why:** Board is currently read-only reflection; operator decisions still have to travel through chat. Dispositions through the board close the loop: tap/drag → queued → agent applies to kanban.data.yaml at session start (agent-in-loop, no unatt...
- **Next:** Build: webhost micro-API + board JS (buttons done/deferred/declined + column drag) + cron pull of disposition queue + pending-chip render + session-start apply protocol in ura-kanban skill.
- **Forensic keys (1):**
  - `shipped_note`: Live 2026-08-11: buttons (done/deferred/declined) + column drag on urakanban LAN site; queue → pending jsonl → agent session-start apply (operator authority). Orchestrator-verified API round-trip. Organic proof: first real operator dispo...

### `NM-REPAGE-IMG-1` - Re-attach stored snapshot on CRITICAL re-pages — text-only repeats are a correctness bug, not a design choice
thread: **notifications** - status: **shipped_organic** - approval: **approved**
- **Origin:** 2026-08-12 - operator: "Dont forget the missing images in follow on detections as designed. Intermittency on correctness is a bug." — promotes the LOW folded into PERIM-FP-1.
- **Why:** Unack-CRITICAL 5-min re-page loop resends text only; the original snapshot file persists at re-page time, so the omission is arbitrary. Operator ruling: if the alert deserves an image, every page of it does.
- **Next:** Fold into next NM-touching build or ship as standalone Tier-1 hotfix.
- **Forensic keys (1):**
  - `scope`: ~5 LoC in NM re-page path: reuse the stored snapshot path from the original dispatch (both WhatsApp + iMessage attachment keys, BB v0.6). Tier 1. Anchor: wire-in rule applies (call-site neuter must red a test).

### `NM-RECOVERY-AGEBOUND-1` - Boot recovery resurrects unacked CRITICALs of ANY age — 326 historical twin-eaten rows are a resurrection minefield
thread: **notifications** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-14 - Found while closing IMSG-IMAGE-FAIL-1: get_active_critical has no freshness bound; the twin-eating ack bug left 326 unacked REAL criticals over months. Todays 4 sibling rows acked in-band via the (fixed) service; the rest ar...
- **Why:** A re-page of a weeks-old alert is noise at best, alarm-fatigue at worst. The DB rows themselves should stay (analytics).
- **Next:** Fold into next NM-touching deploy.
- **Forensic keys (1):**
  - `fix_sketch`: Age-bound in get_active_critical (or the recovery caller): ignore unacked CRITICALs older than NM_RECOVERY_MAX_AGE_H (rung 1, default ~24h, 0=unbounded). Tier 1 + one twin-scenario test. Makes bulk historical ack unnecessary.

### `SAFEWORD-WINDOW-1` - Safe-word ack window — one "duke" covers perimeter alerts for a bounded period (operator-proposed)
thread: **notifications** - status: **shipped_organic** - approval: **operator_proposed**
- **Origin:** 2026-08-14 - operator: "safe word covers all alerts within 1-3 hours so no need for safe words for a while no matter the notification? The underlying goal is still to tune the classification of events and make sure they are good."
- **Why:** Operator ergonomics during the FP-tuning era: busy afternoons / alert clusters currently need per-alert acks.
- **Next:** Operator confirms the scoped shape (perimeter-only, duke Nh syntax, 3h cap) -> Tier 2 (NM routing = regression-prone).
- **Forensic keys (3):**
  - `institutional_reuse`: The silence primitive EXISTS: _silence_until (notification_manager.py:346, gate :1351-1352) — the reply-3 30-min silence. Proposal = parametrize duration + scope. NOT a new mechanism.
  - `marginal_shape`: Simplest honest version: "duke" keeps acking the current alert; "duke 2h" (parsed duration, cap 3h) sets _silence_until for PERIMETER-CLASS hazards only. Life-safety (smoke/CO/water/intrusion-interior) NEVER blanketed — a real intruder a...
  - `safety_note`: Blanket-mute is a stopgap while classification precision improves (the operator-stated underlying goal); scope-limiting to perimeter class keeps the failure mode bounded.

### `OPT-META-BOOT-TRANSIENT-1` - Optimizer meta-monitor false "cannot see problems" alert — findings_recent reads RAM cache emptied by restart while open-count reads durable state
thread: **optimizer** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-15 - Operator forwarded the meta alert 20min after the v5.76.0 restart; diagnosis: boot transient, not real blindness (3,725 findings/24h in DB, newest minutes old).
- **Why:** optimization_llm.py:666 builds findings_recent from coordinator._last_findings (in-memory, cleared at restart); the meta pass compares it against the durable open-findings count and the LLM narrates the mismatch as system blindness -> fa...
- **Next:** Tier 1 hotfix; batch with next deploy.
- **Refs:** custom_components/universal_room_automation/domain_coordinators/optimization_llm.py
- **Forensic keys (2):**
  - `fix_options`: Either (a) corpus falls back to get_recent_optimization_findings DB read when the RAM cache is empty, or (b) meta emission suppressed inside a post-boot grace window (suppression-needs-discharge: re-fires next cycle after grace). Prefer ...
  - `live_validation_2026_08_15`: v5.77.0 LIVE: L3 PASS — first post-boot meta cycle = cycle_ok only; false-blindness HIGH structurally closed. Card can move to done on one more clean restart.

### `CENSUS-ACCURACY-1` - Interior census accuracy: separate census decay from guest hysteresis + fix the _2-suffix fresh-face resolution (exterior dashboard wiring is a minor bonus)
thread: **presence** - status: **shipped_organic** - approval: **implied**
_updated 2026-08-18 03:15_
- **Problem / Solution:**
  - P5 one timer, two opposite needs — census wants freshness, guest wants hysteresis; shared hold+decay turns a 15s phantom into 480s of evidence and clears the 300s guest gate (the mechanism behind ~50 spurious guest entries since 07-13). ...
  - P6 decay never fires for systematic errors — the peak self-refreshes when fresh == peak, so a permanently-wrong value renews forever while only transients decay (wrong sign on both axes). S6 remove the self-renewing slope; make heldness ...
  - P7 consumers cannot distinguish a fresh count from a 20-minute-old latched one. S7 publish peak_held / peak_age / count_as_of — all already computed internally and discarded.
  - P8 the exterior census is naive (per-camera-bit sum, one walker past 3 cams reads 3) while the track-deduped count already exists live. ADJUDICATED 2026-08-17 (AUDIT_exterior_census_supersession.md, eb2caa3c8): the swap I originally scop...
  - P9 outdoor presence may pollute the interior headcount (outdoor-zone filter designed, unbuilt). S9 apply the filter using the existing CONF_ZONE_IS_OUTDOOR flag.
  - ABSORBED FROM CENSUS-DEDUP-REPAIR-1 (merged 2026-08-16): P10 the per-area BLE-cancel subtraction reports ble_cancelled_count 0 every tick while residents ARE being double-counted — cause UNKNOWN. Ruled out: missing areas on the counting ...
  - ABSORBED FROM CENSUS-DEDUP-REPAIR-1 (merged 2026-08-16): P11 the fresh-face -1 per-camera defense is inert because face recognition produces ~0 identities (face_recognized_persons empty with 4 known residents home). S11 gated on the EXTE...
  - P12 (folded in per operator 2026-08-17) the two exterior counts serve DIFFERENT consumers and neither is wired to the dashboard correctly. S12 small deliverable: dashboard shows the DEDUPED count (exterior_person_tracks_active) as the he...
- **Origin:** 2026-08-16 - Operator ruling after the guest-phantom incident; full context in RESEARCH_census_vs_guest_separation.md (aa3e39aa8).
- **Why:** Operator separation-of-concerns ruling: census = measurement (accuracy + freshness); guest = policy state (explicit entry/exit + hysteresis). Today guest is a function of a decaying measurement, which is the root architectural error. NOT...
- **Next:** RESCOPED by operator 2026-08-17 to DECAY + SUFFIX FIX (dedup repair dropped — probe measured it buys ~0). Plan: (1) decay/self-refresh separation, targeting the measured 74.5% of elevated time that had camera_unrecognized==0; (2) registr...
- **Refs:** docs/planning/RESEARCH_census_vs_guest_separation.md; docs/planning/PLANNING_v4.7.18_census_service_shared_refactor.md; CARD: EXTERIOR-GUEST-EGRESS-1 (exterior->guest, split out of P8); CARD: EXTERIOR-DWELL-LOITER-1 (circling dwell gap, security); docs/planning/AUDIT_census_accuracy_probe.md (probe gate); docs/planning/AUDIT_exterior_census_supersession.md (eb2caa3c8) — KEEP BOTH ruling
- **Forensic keys (8):**
  - `operator_exterior_direction_2026_08_16`: Operator ruling on the exterior work, THREE distinctions: (1) EXTERIOR -> HEADCOUNT is easy, do it (straight composition; sensor.universal_room_automation_persons_on_property_exterior is live, and a dashboard for it already exists at doc...
  - `regression_context_2026_08_16`: Operator: "I believe we regressed census with our prior work" — CONFIRMED with recorder data. Daily census max: Aug 9-12 = 6-7 (4 residents, chronic over-count of 2-3); Aug 13-14 = 4 (LOOKED perfect, but only because the _2-suffix break ...
  - `measured_incident_2026_08_16_guest_7h`: MEASURED end-to-end retrace of a live false-guest episode (operator flagged "5 seen, guest mode, 4 known"). Recorder: house `guest` 13:38:33 -> `home_evening` 20:40:59 = 7h02m of false guest with 4 known residents and zero guests. Entry ...
  - `exterior_intersection_findings_2026_08_16`: Context-wide read-only investigation answering "how does the circling/exterior-track work intersect the exterior census". ANSWER: IT DOES NOT — zero shared code, two independent readers of the same cameras. (1) Exterior census `_calculat...
  - `merged_from_2026_08_16`: Absorbed CENSUS-DEDUP-REPAIR-1 wholesale. That card covered P10/P11: repair the BLE-cancel and fresh-face dedup defences at source (both currently return zero, which is WHY the additive derivation double-counts). Kept as one cycle becaus...
  - `suffix_migration_finding_2026_08_17`: OPERATOR CONFIRMED: the Frigate1->Frigate2 migration WAS done; this aspect was missed. VERIFIED against the live registry (/Users/okosisi/ha-config/.storage/core.entity_registry — note CLAUDE.md documents a STALE path /Users/ojiudezue/.....
  - `scope_clarification_2026_08_17`: Operator scope check 2026-08-17: "Isn't cycle 2 about interior accuracy? The exterior was a bonus? Or does cycle 1 fix that?" — CONFIRMED. Cycle 1 (CENSUS-GHOST-DEDUP-1) fixes GUEST MODE, not the interior count (its D1 clamp is a no-op w...
  - `d3_dashboards_done_2026_08_18`: D3 (P12) exterior dashboards DONE (display-only, no producer change): composed card (deduped headline + G1 naive-floor fallback [never 0 when floor>0] + divergence badge) added to HA ura-v6 (Presence/Census Cross-Confirmation), ura-v8 (S...

### `CENSUS-GHOST-DEDUP-1` - Census double-counts residents as unidentified (4 known + 2 ghost bodies = 6) — BLE-cancel exists, is enabled, cancels nothing
thread: **presence** - status: **shipped_organic** - approval: **implied**
- **Origin:** 2026-08-16 - Operator home with family of 4; census read 6 (identified 4 + unidentified 2). Operator: "only 4 of us — 2 are ghosts or unrecognized versions of us and should decay right?"
- **Why:** Cameras detect person-bodies but recognize NO faces (face_recognized_persons: [] with 4 known people home), so residents own bodies land in the unidentified bucket alongside their own BLE-identified selves = systematic double-count, and ...
- **Next:** Suite run + NAME-diff at tip 7e3fa18d0 (never completed — blocked all night by concurrent-pytest deadlock, now cleared and guarded by the new hook), THEN re-run the framings against the REPAIRED oracle (operator: "Fix, then re-run all fr...
- **Refs:** docs/planning/PLANNING_census_overcount_dedup_decay.md
- **Forensic keys (8):**
  - `investigation_state_2026_08_16`: RULED OUT: missing areas on the counting sensors (16 of 17 Frigate person-count/occupancy _2 sensors have effective areas; only the screened ASH41B lacks one, and it never detects). NOT YET EXPLAINED: why area_contributions is empty and ...
  - `research_2026_08_16`: RESEARCH_guest_actuation_and_census.md (8f55b243d) — root cause found: the ENHANCED census path (default ON) is ADDITIVE (total = identified + camera_unrecognized) and OVERWRITES the RAW subtractive path (total = max(camera, identified))...
  - `minimal_set_2026_08_16`: OPERATOR-SCOPED MINIMAL SET = G1 + G4 only. G1 subtractive clamp (~10 LoC, no knob) because the count feeds away-inference/sleep-wake/NM/dashboards, not just guest. G4 invert composition so GUEST ROOMS LEAD and census corroborates (~5 Lo...
  - `guest_room_config_2026_08_16`: Guest-room set audited when G4 (guest-rooms-lead) was proposed — only ONE of three can currently signal. (a) Guest Bedroom 1: WORKS. (b) Upstairs Guestroom: BROKEN — the listener slugifies the room name to binary_sensor.upstairs_guestroo...
  - `build_state_2026_08_16`: Branch feature/guest-census. Build c7c308a53 (D1 pre-cancel clamp, D2 guest-rooms-lead composition, D2b exit decoupling, D3 registry resolution, G2 diagnostics). THREE framing-disjoint reviews: A SHIP (6c89dc017), B SHIP-with-notes (f425...
  - `fuller_pass_outcome_2026_08_17`: FULLER ADVERSARIAL PASS (operator ruling "Fuller pass") — THREE MORE framing-disjoint reviews, ALL THREE DO-NOT-SHIP. This pass is the only reason the cycle did not ship broken. D (adversarial completeness, 13ba10861) + E (lifecycle, dcf...
  - `guest_room_designation_correction_2026_08_17`: ORCHESTRATOR ERROR, CORRECTED BY OPERATOR. I reported "zero rooms designated is_guest_room=True" and concluded D2 would silently DISABLE guest mode. WRONG — I queried a plausible key name instead of the one the code reads. The real key i...
  - `empty_house_validation_window_2026_08_17`: OPERATOR 2026-08-17 21:53 CT: house EMPTY until Tue afternoon/evening; operator back Wed afternoon. ABSENCE OVER THIS WINDOW IS EXPECTED — do NOT flag away/empty/census-0 as anomaly. CONSEQUENCE for v5.79.0 live validation: L3 (resident ...

### `ROOM-NAME-DESYNC-1` - Options-flow room rename without data write-back — house tier permanently blind to 3 renamed rooms (substrate edges name-dropped)
thread: **presence** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-13 - ZONE-TIER-DIVERGE-1 thorough trace: presence house tier keys rooms by entry.data room_name (presence.py:2868); substrate dispatches under options-first merged name (occupancy_substrate.py:197-202). 3 rooms renamed via option...
- **Why:** BUG, live now (smoking gun: jaya_3_presence=on w/ substrate_kinds all-false). The 08-13 20:51 away transition fired THROUGH occupied Upstairs precisely because the house tier could not see the two renamed rooms. Blast radius: away/veto/c...
- **Next:** Operator picks (a) now vs (b) after-sensors; then Tier 2-DB cycle (plan review first).
- **Forensic keys (2):**
  - `operator_decision`: SEQUENCING TRADE: (a) config-mitigate NOW (re-align 3 entries names) = house tier regains sight, but away gets HARDER (3 more phantom-holdable mmWave zones until corroborators arrive — rec 1 hardware is operator-owned); (b) sequence the ...
  - `build_dispatched_2026_08_13`: Plan rev-2 (plan review: 4 HIGH fixed incl. double-reload + setup-reload-watchdog ordering + 3rd write site + CONF_ZONE fold-in). Build in flight (worktree). Hand-sync mitigation VERIFIED live same evening (Upstairs zone occupied w/ real...

### `PATH-ALPHA-DENOM-1` - Path-alpha away inference structurally dead when all trackers LOST/STALE — trusted denominator empties; NO existing card fixes it
thread: **presence** - status: **shipped_organic** - approval: **approved_after_investigation**
- **Origin:** 2026-08-13 - Carded-coverage grading: the LOST-denominator gap (all 4 trackers LOST -> all_tracked_persons_away false-by-vacuity for hours) is owned by no card; v5.16.0 fixed the veto denominator, not this.
- **Why:** Path-alpha ignores zones entirely — with ACTIVE trackers it would have fired regardless of the fan latch. Fixing the vacuous-denominator case (all-LOST + all-entity-away => away-eligible) is an independent mitigation with its own balance...
- **Next:** GATED on ZONE-TIER-DIVERGE-1 trace completing (same code region). Then: consumer enumeration of tracking_status (greps, all tiers) -> plan for decomposition path (1) with (2) as fallback if ripple too wide; Tier 2-DB minimum (trust-hiera...
- **Forensic keys (4):**
  - `operator_direction_2026_08_13`: Operator: "we should find a way to say AWAY not LOST. Do we need a lost state at all? That way we can actually use this signal the way it is supposed to be used. And not overload it." I.e. the fix may not be patching the denominator arit...
  - `alternate_paths`: (1) Dissolve LOST: away-with-no-fix => AWAY (trusted, counts in denominator); home-but-silent => new BLE_SILENT_HOME or stays ambiguous-excluded; keep LOST only for truly-unknown. Ripple: every consumer of tracking_status (H3 reliable-si...
  - `reconcile_2026_08_16`: STALE STATUS FIXED (was inbox). Plan rev-3.5.1 committed fa31c6d45 after operator checkpoint + adversarial plan review; BUILDING NOW on feature/path-alpha (D1-D7 + Gap-B guard + EV riders).
  - `live_validation_2026_08_16`: v5.78.0 LIVE 2026-08-16. L1 PASS (0 errors), L4 PASS (face_recognized_count + path_alpha_gate_source live on house-state sensor). L2 PASS-on-state / attribution organic: house is away with all 4 persons not_home and census 0 — but the tr...

### `AWAY-BLOCK-1` - House held home_day 2h with everyone away — fan->mmWave->occupancy->fan self-sustaining loop; both away paths structurally blocked
thread: **presence** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-13 - operator: "why not trust that signal and send the house to away mode? What are we getting wrong about this inability to transition?"
- **Why:** Traced (AUDIT_away_transition_2026_08_13.md): path-alpha dead (all 4 trackers LOST/STALE -> trusted denominator 0); path-beta vetoed by ONE zone occupied solely by the Living Room Screek mmWave, latched by the room's own tower fan (fan O...
- **Next:** Operator picks; orchestrator recommends 1+2 together (config turn + small loop-breaker), 3 only if evidence recurs after 1+2.
- **Forensic keys (3):**
  - `operator_decision`: Ranked recs — pick any: (1) CONFIG-ONLY: add a PIR/corroborator to Living Room + the 5 other no-PIR rooms (re-enables shipped D2 demotion; highest marginal benefit, near-zero risk). (2) TIER-1: cap comfort-fan sustain on mmwave-sole prov...
  - `operator_dispositions_2026_08_13`: Rec 1: OPERATOR-OWNED — the existing Zigbee sensor is hallway-placed; operator adds a physical sensor himself. DO NOT RAISE AGAIN (explicit instruction); when new sensors appear in room configs, silently verify D2 arms. Rec 2: PARKED (ad...
  - `reconcile_2026_08_16`: Root fixes SHIPPED v5.75.0 (fan duty-flag exclusion + room-name write-through). Deeper structural causes are in flight as PATH-ALPHA-DENOM-1 (H3 over-reach) + GAP-A-CENSUS-HOLE-1 (census half) + Gap-B guard. This card holds the incident ...

### `CIRCLING-LABEL-1` - Circling loops page but are never LABELLED/escalated as circling (2-camera shape) — cooldown blocks the hop where classification forms
thread: **perimeter** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-13 - CIRCLING-SEVERITY-1 Review A MEDIUM-A1: founding shape pages at hops 1-2 as pass_by (LOW/MED); classification becomes circling at hop 3; per-camera 300s cooldown returns before severity re-resolves; continuation-coercion blo...
- **Why:** INV-M holds (pages happen, tripwire honest) but the operator's 08-08 complaint was about CIRCLING specifically. The dominant 2-camera alternating shape can never emit a HIGH circling-labelled page under current mechanics.
- **Next:** ura-planner -> plan review -> build.
- **Forensic keys (6):**
  - `operator_decision`: (A) surgical — allow ONE dispatch through the cooldown when a track's classification TRANSITIONS (one extra HIGH page at the hop circling forms; ~persist last_dispatched_classification on ExteriorTrack). (B) tighten invariant + add circl...
  - `decision_2026_08_14`: OPERATOR: Option A approved per recommendation — one dispatch allowed through the per-camera cooldown when a track's classification TRANSITIONS (the hop circling forms => one HIGH circling-labelled page). Own Tier-2 cycle, plan review fi...
  - `plan_review_2026_08_14`: FIX-PLAN-FIRST (0d30ee8bc): HIGH — plan's XCORR-1 mechanism was WRONG; single-camera nighttime circling would demote the exemption dispatch to LOW (founding ask unmet in a reachable shape). Reviewer adjudicated fix: exemption_active earl...
  - `build_2026_08_15`: feature/circling-label (6 commits, worktree): 21 new tests, 8/8 drills red-restored, 0 HEAD-only suite failures (9026 pass). Notable builder find: plan's I4 anchor was masked by I2 — added unique-anchor test. 2 framing-disjoint reviews d...
  - `reviews_2026_08_15`: A SHIP (3f102e803) + B SHIP (ce9913b38), zero overlapping findings. Fix-up 4c1667f93 (3 LOWs incl. B-LOW-1 cross-camera double-grant race -> optimistic seed + 4-path rollback, +3 load-bearing tests). Orchestrator re-drill: XCORR-1 short-...
  - `live_validation_2026_08_14`: Shipped v5.76.0. Organic open: L6 next real escalating track -> one HIGH page at transition.

### `GAP-A-CENSUS-HOLE-1` - Path-alpha veto blocked by forgotten-phone BLE via census_count clause — replace with camera-provable-only evidence (face_recognized_count)
thread: **presence** - status: **shipped_organic** - approval: **implied**
- **Origin:** 2026-08-16 - AUDIT_away_transition_2026_08_13.md flagged the H1 census clause as latent; operator asked for the specific fix and required it ship in the same deploy as PATH-ALPHA.
- **Why:** presence.py:1047-1057 gates path alpha on census_count == 0, whose intent-of-record (comment :1039-1042) is "Frigate face-IDs a resident -> phone trustworthiness irrelevant". But census_count = |ble_home union face_recognized| + held_uni...
- **Next:** Plan review (running) -> build on feature/path-alpha AFTER its D1-D9 land (do NOT interleave presence.py edits) -> both covered by the same 3 framing-disjoint reviews -> ONE deploy.
- **Tags:** tier-2db, no-fabrication-verify, context-wide-scoping
- **Refs:** docs/planning/PLANNING_gap_a_census_hole.md; docs/planning/AUDIT_away_transition_2026_08_13.md; docs/planning/PLANNING_path_alpha_lost_dissolution.md
- **Forensic keys (3):**
  - `fix_sketch`: Encoding A (~15-30 LoC, ONE deliverable): extend SIGNAL_CENSUS_UPDATED with face_recognized_count (existing CensusZoneResult.face_recognized_persons, camera_census.py:158/:3116); store on PresenceCoordinator via _handle_census_update (:4...
  - `plan_review_2026_08_16`: SHIP (efec78928) — trace + consumer enumeration independently confirmed; circularity CLEAN (URA writes no person.* entity, so the matrix cannot feed back into the face cross-check — FENCE: re-audit if that ever changes); 3 text-only edit...
  - `live_validation_2026_08_16`: v5.78.0 LIVE 2026-08-16. L1 PASS (0 errors), L4 PASS (face_recognized_count + path_alpha_gate_source live on house-state sensor). L2 PASS-on-state / attribution organic: house is away with all 4 persons not_home and census 0 — but the tr...

### `GUEST-FP-RESIDUALS-1` - Guest-FP audit residuals — path-alpha diagnostic classifier (A1, ~5 LoC) + camera-census outdoor filter (B1, latent)
thread: **presence** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-13 - AUDIT_guest_fp_fixes_wiring.md: core fixes SHIPPED + Outside zone correctly flagged outdoor; two residuals worth small fixes.
- **Why:** A1: path-alpha excluded_persons/tracked_persons_count_trusted still exclude LOST-away persons (diagnostic clarity only — guest gate does not read them). B1: camera-census has no room->outdoor filter; safe today (Patio has no camera perso...
- **Next:** Fold A1+B1 into the next presence hotfix batch; await operator answer on the 50-episode pattern.
- **Forensic keys (3):**
  - `operator_question`: 50 guest ENTRY episodes since 07-13 (1-7/day, daytime, flappy) — real summer guests or a daytime FP flavor? If the latter, escalate per audit §3.
  - `folded_2026_08_16`: A1 path-alpha diagnostic classifier folded into the PATH-ALPHA cycle as D3 (rider). Building now.
  - `live_validation_2026_08_16`: v5.78.0 LIVE 2026-08-16. L1 PASS (0 errors), L4 PASS (face_recognized_count + path_alpha_gate_source live on house-state sensor). L2 PASS-on-state / attribution organic: house is away with all 4 persons not_home and census 0 — but the tr...

### `DP-REASON-NULL-1` - DP durable ledger logs reason:null on all 4,181 rows — carrier has no .reason field
thread: **energy** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-13 - Found by AUDIT_dp_live_behavior.md: _log_dp_eval_decision (energy.py:4002) reads getattr(carrier,"reason",None); field does not exist; real reasons live only in ~10-day recorder attrs.
- **Why:** Durable decision ledger is the long-horizon audit trail; null reasons make future DP forensics depend on recorder retention.
- **Next:** One-line fix (log the eval snapshot decision.reason) + anchor test; fold into next URA deploy batch (Tier 1).

### `SUITE-HYGIENE-1` - Kill the order-dependent flake families (sys.modules pollution) — every cycle pays a classification tax
thread: **quality** - status: **shipped_organic** - approval: **approved**
- **Origin:** 2026-08-11 - Three consecutive cycles (ARREST-COMFORT, FAN-LAYER-1, FAN-LAYER-2 D1) each spent builder+reviewer effort re-classifying the same order-flakes; FAN-LAYER-2 D1 even had its own NEW test polluted on day one.
- **Why:** Diagnosed root cause (v5.70.0 Review B / B-MED-2, deferred): test_freeze_floor.py + test_v4_6_9_hvac_intent_attrs.py install synthesized modules into sys.modules without snapshot/restore; collection-order shifts expose different victims ...
- **Next:** Small Tier-1/2 cycle: snapshot/restore fixtures around every sys.modules-stubbing test file (grep for the stub pattern, fix all instances, not just the two known); add a suite-level canary test that asserts sys.modules is unchanged acros...

### `NM-IMAGE-1` - NM image attachments not landing (WhatsApp + iMessage) — operator automation images DO land
thread: **notifications** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-11 - operator: "The images are not landing in the NM messages even in whatsapp; the image-bearing ones are from my automation."
- **Why:** DIAGNOSED 2026-08-11: capture works (fresh files in /media/ura/snapshots), channel works (live media_path test delivered WITH image), perimeter dispatch threads snapshot_path. The drop is NM digest routing: operator delivery_pref=digest;...
- **Next:** Operator approves cycle -> plan (Tier 2, one adversarial plan review) -> build. Prerequisite for CONSOL-1 universal-llmvision (approved 2026-08-07).
- **Forensic keys (1):**
  - `design_pick_for_operator`: Fix shape A: persist snapshot_path into digest rows + deliver images at flush. Fix shape B (recommended for security class): image-bearing perimeter alerts bypass digest as effectively-immediate. Pick rides the plan review.

### `DP-OBSERVABILITY-1` - DP plan sensor presents stale eval snapshot as current (misled 2 diagnoses in one day)
thread: **energy** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-11 - Found during EV-GARAGE-A-NOCHARGE-1: last_eval_at 4 days old + expired must_start_by rendered without staleness cues; pause_reason_human shows day-scoped reason strings that read as current at any hour.
- **Why:** The sensor is honest data, dishonest presentation: hold_only (resting state) + stale snapshot reads as "frozen/blocked". Cost: orchestrator misdiagnosed a stall; operator asked "how is that a sensor".
- **Next:** Small cycle: age-stamp the snapshot in attrs (eval_age_min), render must_start_by only when future, clarify hold_only naming/attr (state=resting vs active-pause), and consider a stale-eval WARN when off_peak+charging ticks pass without e...

### `FAN-LAYER-2` - FanPolicyOracle completion — RoomFanState delegation + actuate-wrap remainder (W1-W3, W8-W10) + INV-FLA-T lock
thread: **fans** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-11 - Session 3 scoped-partial: builder deferred RoomFanState dataclass→property (34 sites), W1-W3/W8-W10 actuate wraps, adjacency reverse-scan. Honest deferral, own blast radius.
- **Why:** State-in-one-place holds for RoomAutomation tier but HVAC-tier RoomFanState still carries its own hold fields; TOCTOU lock (INV-FLA-T) only covers W11/W12. Full oracle authority needs the remainder.
- **Next:** After FAN-LAYER-1 increment ships + validates: plan review (Tier 2-DB), then RoomFanState conversion as its own cycle.

### `CIRCLING-SEVERITY-1` - A "circling" exterior person produced alert_count=0
thread: **perimeter** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-08 - observed during v5.62.1 live validation
- **Why:** Live track xt-000001-695c9e: back_yard -> front_side_ptz -> back_yard -> front_side_ptz -> back_yard, classification=circling, 133s, alert_count=0 at 09:22 CDT. Track linking worked correctly (one track, not five alerts). But CIRCLING is...
- **Next:** trace why alert_count=0 for a circling classification; decide whether circling should escape pure clock-time gating
- **Tags:** no-fabrication-verify
- **Parsimony:** [BUILD] the most suspicious exterior behaviour may be silently unalerted outside night hours
- **Refs:** exterior_track_linker.py classification; perimeter_alert.py alert-hours gating; CONSOL-1 contextual-severity ruling

### `XCORR-1` - Burst-demotion for isolated single-camera night alerts (was: cross-engine corroboration gate)
thread: **perimeter** - status: **shipped_organic** - approval: **explicit**
- **Origin:** 2026-08-08 - operator got 12 notifications 01:01-01:25 CDT from hot_tub; "this is what x-correlation looks like if we have multiple engines"
- **Why:** A single engine asserting person while a CO-LOCATED engine on the same physical camera stays silent is strong false-positive evidence. Labelled example 2026-08-08: hot_tub frigate fired 5x in 18min; protect leg NEVER fired; zero adjacent...
- **Next:** build burst-demotion (first alert full severity, repeats demoted when isolated+uncorroborated+night); fold channel reduction into CONSOL-1
- **Tags:** tier-2db, measure-before-build, numbers-get-knobs, no-fabrication-verify
- **Parsimony:** [SIMPLIFY] one mis-tuned camera paged the operator 12x at 1am
- **Refs:** perimeter_alert.py leg_firing_by_camera / _record_leg_fire; v5.59.0 disagreement telemetry
- **Forensic keys (4):**
  - `evidence`: hot_tub frigate _person_occupancy: 06:01:27, 06:06:10, 06:08:36, 06:10:29, 06:19:00 UTC
  - `design_TRAP`: DO NOT gate on corroboration generally - that would SUPPRESS REAL INTRUSIONS on single-engine cameras (many cameras have only ONE engine; and a real prowler may only be seen by one). The gate must be NARROW: only for cameras that HAVE >=...
  - `design`: REVISED: first alert ALWAYS fires at full severity (preserves intrusion guarantee).
  - `probe_result`: PROBE RUN 2026-08-08 (8d, 30s window) -> AUDIT_xcorr_engine_corroboration_probe.md. The naive corroboration gate is REJECTED: solo firing is the NORM on the exterior cameras that drive alerts (front_side_ptz 92% solo, back_yard 91%, pool...

### `DIMMER-REBOOT-1` - Master bedroom Shelly Dimmer 2 reboots 89x since Aug 1 and returns ON (NOT thermal)
thread: **devices** - status: **shipped_organic** - approval: **implied**
- **Origin:** 2026-08-08 - operator: why is the master bedroom dimmer coming on in the morning?
- **Why:** light.shellydimmer2_24d7ebe93470 (area master_bedroom) reboots repeatedly: 89 `unavailable` events since Aug 1, accelerating 6/day -> 23/day, each ~33s (consistent = full device reboot, not a variable WiFi blip). 32 of those reboots came...
- **Next:** set power-on-default OFF; then chase the reboot cause
- **Tags:** no-fabrication-verify
- **Forensic keys (5):**
  - `likely_causes`: Shelly power-on-default set to ON (or restore-last with stale value) -> every reboot turns the light on
  - `CORRECTION`: 2026-08-08: I FIRST REPORTED THIS AS A 117-130C FIRE RISK. THAT WAS WRONG — the sensor's unit_of_measurement is degF, not degC. 116.7F = 47C; peak 129.6F = 54C. That is NORMAL for a wall dimmer and inside the Shelly Dimmer 2 range. NO fi...
  - `fix`: PRIMARY: set the Shelly power-on default to OFF so a reboot cannot turn the light on (device setting, operator or API)
  - `rediagnosis_2026_08_15`: REBOOT THEORY OVERTURNED for recent nights: device uptime 6.66 days (no reboot since ~Aug 8) yet uncommanded off->on 3s apart tonight 23:07 CDT (no HA context either row). Mechanism = PHANTOM WALL-SWITCH EDGES: btn_type=edge + 80ms debou...
  - `operator_fix_2026_08_15`: Operator: "Dimmer sorted." Device readback: btn_debounce 80->150ms; default_state STILL last, btn_type STILL edge — so the fix was partial via settings OR done elsewhere (app/physical). ORGANIC PROOF: two consecutive ghost-free nights (p...

### `ARREST-SUNSET-1` - Temp Arrester Override does not sunset on away/vacation (only sleep)
thread: **hvac** - status: **shipped_organic** - approval: **implied**
_refined ×8_
- **Origin:** 2026-08-07 - operator turned Temp Arrester Override ON (master cold at home) 15:04 CDT; asked to watch the next boundary -> found the gap while verifying
- **Why:** sunset_temp_arrester_override (hvac_override.py:606) hardcodes house_state == 'sleep'. Its SIBLING sunset_immune_holds (line ~487) correctly uses `house_state in DURABLE_HOUSE_STATES` = {sleep, away, vacation}. Both are invoked from the ...
- **Next:** fold into the SECC-1 build batch; Tier 2-DB (HVAC governance)
- **Tags:** tier-2db, no-fabrication-verify
- **Parsimony:** [BUILD] override survives away/vacation -> arrester suppressed in an empty house
- **Refs:** domain_coordinators/hvac_override.py:584-624; domain_coordinators/hvac_const.py:206; domain_coordinators/hvac.py:1908
- **Forensic keys (7):**
  - `operator_requirement`: 'the toggle has to flip itself off when a house state invalidates it. So the toggle always matches reality.' - away/vacation invalidate a comfort override; current code honors only sleep.
  - `fix`: replace the hardcoded 'sleep' check with `house_state in DURABLE_HOUSE_STATES` (matching the sibling). Keep the 6h COMFORT_OVERRIDE_MAX_S decay as the other first-of. Anchor with a test per durable state + a mutation drill.
  - `bug_precise`: hvac_override.py:603 `if reason == 'durable_state' and house_state == 'sleep'` (INLINE LITERAL) vs its sibling hvac_override.py:487 `house_state in DURABLE_HOUSE_STATES` (SHARED CONSTANT). Both invoked from the SAME call site hvac.py:190...
  - `bug_class`: DIVERGENT DUPLICATE PREDICATE (policy fork) - one policy expressed in two places, one drifts. THIRD instance in 2 days: v5.59.0 CRITICAL (resolver learned _smart_motion_human, dedup stripper kept its own narrower tuple) and SNAP-1 (media...
  - `guard`: 1. Policy exists ONCE: house_state_invalidates_arrester_hold() called by both sites.
  - `known_limitations`: restart mid-grace may lose the in-memory pending-sunset obligation unless persisted - builder instructed to persist or explicitly document + report
  - `organic_open`: engage the override, then confirm it releases on the next real context change (or 6h decay) and the switch flips OFF to match

### `CONSOL-1` - Perimeter consolidation cycle
thread: **perimeter** - status: **shipped_organic** - approval: **explicit**
- **Origin:** 2026-08-07 - retire redundant manager surface; I need to weigh in — usability
- **Why:** three parallel alerting stacks (URA NM, HA doorbell automation, zone_monitoring pagers) duplicate delivery
- **Next:** fold SNAP-1 + TEST-1/2 in; Tier 2-DB
- **Tags:** tier-2db, institutional-context, audit-first
- **Parsimony:** [BUILD] 3 stacks page the same event with no shared cooldown/routing
- **Refs:** PLANNING_perimeter_consolidation.md; AUDIT_ha_side_alerting_reconciliation.md
- **Forensic keys (2):**
  - `rulings`: Option C surfacing (= A enhanced)
  - `plan_state`: rev-2 PLAN-READY (1 adversarial review: 3 CRIT + 4 HIGH fixed in-plan incl. No-Soak violation + G4/G6 misname + vehicle-window orphan). D0 probe: doorbell llmvision SILENTLY BROKEN since 02-13 (gpt-5-mini reasoning eats 300 tokens); buil...

### `SNAP-1` - Snapshot mirror-and-improve
thread: **perimeter** - status: **shipped_organic** - approval: **explicit**
_refined ×5_
- **Origin:** 2026-08-07 - still no images -> Mirror and improve -> does it cleanup? -> I approve the purge
- **Why:** URA sends media_url (URL fetch) so images drop; any live grab is stale
- **Next:** SHIPPED v5.63.0 2026-08-09 — 73 snapshots live in /media/ura/snapshots, none in /config/www. Follow-ups open: bluebubbles attachment, protect-thumb source, capture-latency sensor, FRIG2SNAP-1.
- **Tags:** tier-2db, numbers-get-knobs, no-fabrication-verify
- **Parsimony:** [BUILD] perimeter alerts arrive with no photo / a stale photo
- **Refs:** perimeter_alert.py; domain_coordinators/notification_manager.py
- **Forensic keys (6):**
  - `design`: mirror = snapshot to local file, attach as file to every channel (media_path / attachment / image)
  - `RECONCILED_2026_08_09`: status review -> shipped_organic; board had said "ready to build" for shipped work
  - `decisions`: snapshot_dir: /media/ura/snapshots — operator: 'whatever is best practice'. VERIFIED convention: llmvision already uses /media/llmvision/snapshots. /media is HA's auth-gated media dir (media browser), NOT the anonymous web-served /local//config/www — ...
  - `build`: build/snap-at-detection @ 7e28a2ea4 — 15 new tests, 6 detach-the-value drills all RED, gate 21/8405 name-diff 0
  - `verification_results`: VERIFIED: frigate2 instance-scoped snapshot URL — instance id = MQTT client_id from hass.data['frigate'][entry_id]['config']['mqtt']['client_id']; discovery tries each instance. Live: Frigate 1 (192.168.13.16:8971) + Frigate 2 (192.168.1...
  - `followups`: SNAP-1-followup-protect-thumb — REOPENED: Protect IS installed (core integration); verify the smart-detect thumbnail API against HA core unifiprotect and implement the middle precedence tier

### `TRANSIT-1` - Interior traversal — Protect-sourced checkpoints via resolver
thread: **presence** - status: **shipped_organic** - approval: **explicit**
_refined ×2_
- **Origin:** 2026-08-07 - we built exterior tracking inspired by interior census/known-persons traversal - find it; can resolver improve it
- **Why:** transit_validator checkpoints fire from ~one integration; multi-engine legs = denser/earlier checkpoints = more path_confirmed
- **Next:** build - resolver enumerates checkpoint cameras from Protect, attributes each by area, transit consumes that instead of camera_person_entities
- **Tags:** institutional-context, tier-2db, hand-build-fixture, numbers-get-knobs
- **Parsimony:** [BUILD] 4 of 5 traversal checkpoints produce no usable room signal; hand-list drifts
- **Refs:** transit_validator.py; config_flow.py async_step_camera_census
- **Forensic keys (6):**
  - `plan`: docs/planning/PLANNING_transit_protect_sourced_checkpoints.md
  - `progress`: 2026-08-07: INTERIM - all 5 checkpoints now wired in camera_person_entities (operator added upstairs_hall + stairs_top via Camera Census UI; count 9->11; both area-map correctly). NOTE stairs uses Frigate F2 entity (stairs_top_2) not Pro...
  - `review_findings`: A-CRIT-1 (Review A): Protect-sourced entities are subscribed + sightings recorded, but validate_transition filters via _get_shared_space_cameras() = hand-list ONLY -> the superset coverage is recorded then DISCARDED at the decision point...
  - `findings`: OPERATOR: it's 5 cameras. By the real bar (produces a room-attributed signal transit can use) only garage_hallway works. master_hallway + entry(foyer) are in camera_person_entities but have NO fused sensor; upstairs_hallway + stairs aren...
  - `organic_open`: one logical sighting per real crossing (F2 dedup, despite Protect+Frigate legs) + no path_validated inflation vs prior day
  - `followups`: expose checkpoint_cameras_by_area on a diagnostic sensor (validation needed log-level surgery - build scoped it out)

### `RELOAD-WATCHDOG-HAZARD` - URA parent-entry reload cascades → event-loop stall → watchdog (~5min outage)
thread: **lifecycle** - status: **shipped_organic** - approval: **explicit**
- **Origin:** 2026-08-07 - options-flow submit (camera_person_entities) reloaded the URA parent entry and blipped HA -> diagnose and fix this autonomously tonight
- **Why:** routine options saves (Camera Census etc.) reload the integration/parent entry, which cascades to all ~40 room + coordinator entries synchronously, stalling the event loop until the supervisor watchdog restarts core (~5min outage). A con...
- **Next:** (tonight) build - INTEGRATION suppress set + SIGNAL_CAMERA_LIST_CHANGED re-subscribe path; Tier 2-DB (lifecycle + presence)
- **Tags:** tier-2db, no-fabrication-verify
- **Parsimony:** [BUILD] a routine config save causes a ~5min house outage
- **Refs:** __init__.py:5984 _async_update_listener; OPTIONS_RELOAD_SUPPRESS_KEYS; transit_validator.py async_init; feedback_parent_entry_reload_watchdog_hazard memory
- **Forensic keys (4):**
  - `diagnosis`: CONFIRMED (2026-08-07): _async_update_listener (__init__.py:5984) - for the INTEGRATION entry, if changed_keys NOT subset of OPTIONS_RELOAD_SUPPRESS_KEYS -> hass.config_entries.async_reload(entry.entry_id). Reloading the INTEGRATION (par...
  - `fix`: Add Camera Census keys to an INTEGRATION-entry suppress set (mirror the CM/ROOM reload-suppression). Persistence already done by async_update_entry.
  - `planned_2026_08_15`: Overnight pass: PLANNING_reload_watchdog_hazard.md written+committed. Central finding: v4.7.26 suppress branch is gated entry_type==COORDINATOR_MANAGER (__init__.py:6431); camera keys migrated to the INTEGRATION entry in v3.4.5 have NO b...
  - `live_validation_2026_08_15`: v5.77.0 LIVE: L1 PASS; L4 organic (next integration-entry save proves zero-reload + dispatch).

### `KHOST-1` - Homelab-hosted board, generated from data
thread: **dashboarding** - status: **shipped_organic** - approval: **explicit**
- **Origin:** 2026-08-07 - make url live on webhost (homelab)... design it better... give yourself eyes like playwright... build it tonight while I'm sleeping
- **Why:** the Artifact is hand-maintained HTML that can drift; a GENERATED board (pure function of this data) can't; homelab-hosted = durable, infra-native
- **Next:** BUILT + MERGED 2026-08-10 overnight pass (cc9c0e3f8 + 3031487c0). Generator live: scripts/kanban_render.py -> KANBAN.md + kanban_board.html (self-contained, light/dark, mobile), rung-3 STALE banner with exit codes 0/2/1, byte-stable, 13 ...
- **Tags:** hand-build-fixture
- **Parsimony:** [BUILD] the reflected board is hand-maintained and can silently drift from the source
- **Forensic keys (5):**
  - `design`: source = this data file; generator -> {KANBAN.md view, html board, history}; page is a pure function of the data
  - `decisions`: host: urakanban.phalanxmadrone.com
  - `SHIPPED_2026_08_10`: LIVE at https://urakanban.phalanxmadrone.com (verified HTTP 200 serving URA://KANBAN; Mac DNS cache may lag the new UDM record a few minutes). 5-min refresh cron installed on the dev-host crontab. Homelab commit eddf8e4. REDESIGNED same ...
  - `overnight_notes_2026_08_10`: STALE-BASE CLASS, SECOND INSTANCE, new variant: builder verified base against origin/develop but LOCAL develop was ahead (unpushed evening work), so its generated views rendered from an old board file. Caught at merge; views regenerated ...
  - `ADDED_2026_08_09_staleness_forcing_function`: The generator MUST compare meta.last_reconciled against the newest git tag AND the newest docs/readmes/README_v*.md, and (a) render a loud STALE banner on the board, (b) warn on the build. WHY: 2026-08-09 the board said "build" for XCORR...

## ⏸️ Waiting on operator (3)
_needs a human call_

### `EVCARD-1` - EV charging detail card for the URA v8 Energy tab
thread: **dashboarding** - status: **waiting_operator** - approval: **explicit**
- **Origin:** 2026-08-09 - "add an EV charging detail card to the Ura v8 energy tab. Style well. Detail cards are a bit sensor words vomit. Best judgement because of space though."
- **Why:** EV charging is a first-class energy behaviour (drain precedence, must-start-by, TOU exposure) with no dedicated surface on the v8 energy tab.
- **Next:** REDESIGNED 2026-08-16 after operator verdict "design is poor — review the main sensors." Full sensor discovery this time: ev_charging_status per-EVSE attrs (is_on/power/charging/ pause_reason_human — power WORKS while the standalone ev_c...
- **Forensic keys (10):**
  - `applied_render_2026_08_09`: ## ⏸ Paused / TOU peak/mid-peak pause / [Garage A yes|Paused|0.0 kW] [Garage B —|Off|0.0 kW] [Outlets (2) —|TOU peak/mid-peak pause|—] / **Plan:** Hold Only · held 53h — 7 lines, zero None/unavailable/unknown, all four conditional lines ...
  - `fix_2026_08_09_held_label`: Operator: "What does held 53h mean?" — it was WRONG. Verified in source: since is stamped on every DP state transition (energy_drain_precedence.py:265) and HOLD_ONLY CLEARS hold_started_at as a "clean reversion" (:269-274); DPState docst...
  - `ARRESTER_TILE_2026_08_10`: Operator aside: temp override arrester onto the ura-v8 HVAC (Climate) tab for quick access. DONE — new section at climate view position 1 (right under the hero, above the thermostats): heading w/ live state badge + full-width toggle tile...
  - `MULT_SPLIT_APPROVED_2026_08_10`: Operator: "Clean break. Timing is fine." — BLE_CHAIN_HOLD_ENABLED (bool kill switch) + separately named D2 staleness multiplier; NO deprecated alias (single-user no-backcompat). Rides the P24/D3/dropdown batch.
  - `refinement_candidates`: REDUNDANCY: the headline reason and the Outlets row currently show the same string twice ("TOU peak/mid-peak pause") because the outlets are the only endpoints holding a reason. Options: drop the reason from the endpoint row, or drop it ...
  - `bug_caught_pre_ship`: The markdown card auto-detects entities from LITERAL entity IDs in the template. This template reaches them through Jinja VARIABLES (states(s)), so auto-detection would have missed them and the card would never re-render on state change ...
  - `design_notes`: Anti-word-vomit rules applied: (1) narrative first — pause_reason_human leads, and nothing on the dashboard consumed that attribute before; (2) CONDITIONAL rendering — must_start_by, force_charge_until, excess-solar and fill-target only ...
  - `followup_candidate`: retrofit conditional rendering to the Battery Strategy Detail card (same section group, same defect, ~30 min) — only if the operator endorses this card's style
  - `DEDUPE_2026_08_09`: Sweep: dashboarding thread has the PWA + KHOST-1 (kanban board, different surface); EV drain-precedence card is queued BACKLOG work about behaviour not display. No existing card covers a v8 energy-tab EV surface. NEW.
  - `status_correction_2026_08_16`: Was stale in INBOX — the card was BUILT and applied live to ura-v8 Energy tab 2026-08-09; correct state = waiting_operator (refinement review, operator: "I'll review and we can refine").

### `ZIRI3-UNCONFIG-1` - RECOVER (not unconfigure) Ziri 3 device from Ziri Bedroom entry (presence + moving_target + VEML7700 lux) — rides next deploy restart
thread: **presence** - status: **waiting_operator** - approval: **explicit**
- **Origin:** 2026-08-15 - ziri_3_presence stuck-unavailable finding in optimizer score-55 round; device physically dead (established 2026-08-05).
- **Why:** Dead device dings sensor_health every cycle. Room keeps mmwave_zigbee_ziribedroom_presence for presence. Three refs removed: presence_sensors[ziri_3_presence], motion_sensors[ziri_3_moving_target], illuminance_sensor=ziri_3_veml7700 (set...
- **Next:** OPERATOR: power-cycle the Ziri 3 node (unplug/replug). Then I verify: entities leave unavailable, presence/lux flow, optimizer sensor_health finding clears next cycle.
- **Refs:** scratchpad ziri3_unconfig_after_flush.py
- **Forensic keys (1):**
  - `reversal_2026_08_15`: Operator: device is still physically in the room — DO NOT unconfigure. Staged flush-watcher rider DELETED. History: zero real readings in entire recorder retention (8+ days); node does not resolve on network (ESP fully off-WiFi, not flap...

### `EV-GARAGE-A-NOCHARGE-1` - BMW on Garage A refuses charge overnight — vehicle-side or pilot fault; URA exonerated
thread: **energy** - status: **waiting_operator** - approval: **unreviewed**
- **Origin:** 2026-08-11 - operator: "BMW on Garage A has not charged overnight." Investigated; initial DP-stall framing CORRECTED.
- **Why:** Recorder: URA lifted TOU pause at 21:00 off_peak, switch.garage_a ON 23:53-06:09, 41A limit — EVSE Connected all night, NEVER Charging, 0 kWh. L1 sockets charged fine 01:30-07:04. DP hold_only = resting state (paused_by_battery_drain emp...
- **Next:** OPERATOR: check BMW app (schedule/target/errors) + reseat cable. URA-side follow-ups split out: DP observability (stale last_eval snapshot presented as current, expired must_start_by shown) + garage-A network fix (homelab).
- **Forensic keys (1):**
  - `sharp_problem`: Suspects: (1) BMW in-car charge schedule/target-SOC met; (2) pilot/cable fault — six 10s Connected->Disconnected blips overnight; (3) Garage A network degradation (Emporia unavailable-flap every 2-5min + Shelly overhead + Zigbee door als...

## ⏳ Waiting on me (Claude) (1)
_I owe something_

### `SWEEP` - Morning sweep
thread: **ops** - status: **waiting_me** - approval: **implied**
_updated 2026-08-17 23:12_
- **Why:** reason-ledger first night, Frigate car/dog/cat first events, snapshot-fix organic proof, v5.57/58 organic criteria
- **Next:** Recurring morning-sweep placeholder; re-fires each session start. No standing action.

## 🅿️ Parked (8)
_revisit-trigger set_

### `MEMORY-ZONE-PHANTOM-WRITER-1` - Optional memory writer: zone_phantom (F2 zone-vs-house divergence has zero witnesses)
thread: **memory** - status: **parked** - approval: **unreviewed**
_created 2026-08-18 02:20 · initial_
- **Problem / Solution:**
  - Problem: nothing records when an HVAC zone reads occupied while the house is away (the F2 zone-vs-house divergence) — that tier has no memory witnesses at all. Solution: ONE additive writer zone_phantom, copy-adapt of AwayBlockEpisodeTra...
- **Why:** Fills the only actionable memory-coverage gap. But there is NO active problem needing it today, so its marginal benefit is low until an F2-shape divergence recurs.
- **Next:** REVISIT TRIGGER: a real F2 zone-occupied-while-house-away divergence is observed. Then build the writer (plan is PLANNING_memory_writers.md).
- **Refs:** docs/planning/PLANNING_memory_writers.md; custom_components/universal_room_automation/memory_writers.py:186

### `KP-ANNOTATION-1` - Known-person annotation + stranger-alert leg — exterior alerts annotate identity ("likely Oji"), unknown-face escalates (doorbell-automation successor)
thread: **perimeter** - status: **parked** - approval: **explicit**
_refined ×3_
- **Origin:** 2026-08-14 - Successor card for the work absorbed from declined KP-ESCALATE-1 + the annotate-not-suppress direction. This card was MISSING for a day (capture miss, created 2026-08-15).
- **Why:** Exterior alerts have zero member recognition; annotation kills operator triage cost without suppressing; stranger leg replaces the retiring doorbell automation. INV-KP: identity never delays/blocks/mutates the base alert; absent identity...
- **Next:** Tier 2-DB. Plan rev-3 committed (a28e4568f) — reviewed twice (4e468d37f). Next: D0 read-only probe (identity producers per camera, latency histogram, confidence distribution, enrollment coverage, doorbell cadence) -> gates build.
- **Refs:** docs/planning/PLANNING_known_person_annotation.md; docs/reviews/code-review/known_person_annotation_plan_review.md
- **Forensic keys (5):**
  - `d0_verdict_2026_08_15`: PARK v1 ENTIRELY (probe 2bcffbe0a, AUDIT_kp_annotation_d0_probe.md) — producer coverage insufficient, plan's own park branch. 0.0% of 1,532 perimeter person events had identity at t=0 (ship gate >=50%); 6 of 9 camera face pipelines emit ...
  - `revival_preconditions`: OPERATOR/HOMELAB actions, then RE-RUN the probe: (1) fix Frigate-2 face pipeline on the 6 dead cameras; (2) enroll Ziri + verify Oji enrollment (1 sighting as first-name token); (3) expose a Frigate confidence score OR drop the floor des...
  - `crosscheck_2026_08_15`: Operator tagged faces in BOTH engines this morning. Protect registry (via Protect API/MCP — HA exposes NO identity attrs on this install, so URA consumption = Protect API, plan note): Oji 21 dets avg-conf 82, Ziri 46 dets (Frigate's blin...
  - `webhook_probe_2026_08_15`: Operator approved the probe. HA listener LIVE: automation.ura_kp_face_webhook_probe (webhook id ura_kp_face_probe, local-only, payload -> event ura_kp_face_probe_received + system_log). Protect-side rule could NOT be created via API (v2 ...
  - `probe_result_2026_08_15`: PROBE FIRED (operator created "Madrone Face Alarm": Face ID known+unknown, Family Room + G6 Entry — the ONLY two Face-ID-capable Protect cams, fisheye silence explained definitively). Test payload captured: trigger key (face_known/face_u...

### `EXTERIOR-DWELL-LOITER-1` - Circling classification has no dwell/loiter predicate — a 20-minute stationary watcher reads as pass_by
thread: **security** - status: **parked** - approval: **explicit**
- **Problem / Solution:**
  - P1 `ExteriorTrackLinker.classify()` (exterior_track_linker.py:705-750) is PURELY TOPOLOGICAL. `circling` iff revisit_count >= 1 OR (camera_count >= EXTERIOR_TRACK_CLASSIFY_CIRCLING_CAMERAS AND non-monotonic path); `approach` iff egress-a...
  - P2 severity is keyed on (label, house_state, classification) via NM_HAZARD_EXTERIOR_TRACK_SEVERITY_MAP (const.py:1842-1875), so ANY new class is a severity-table change with NM blast radius — a new row set, not a one-line predicate. S2 s...
- **Origin:** 2026-08-16 - Surfaced by the exterior track-vs-census investigation while answering the operator's question on how the circling work intersects exterior census accuracy. Operator had just made exterior count accuracy a first-class SECURI...
- **Why:** Loitering is the canonical security signal the current classifier is structurally blind to, and the blindness is not an oversight in the data (duration_s is right there) but in the predicate. Directly connected to the shipped linker work...
- **Next:** PARKED pending prerequisites (camera-role gating + revived face-ID + track stitching). Face-ID revival is shared with CENSUS-ACCURACY-1 _2-suffix fix — revisit this card once that ships and face-ID is live.
- **Tags:** security, measure-before-build, no-fabrication-verify
- **Refs:** custom_components/universal_room_automation/exterior_track_linker.py:705-750; custom_components/universal_room_automation/const.py:1842-1875; docs/planning/AUDIT_memory_handbuild_compactor_exterior_track.md; docs/planning/PLANNING_circling_severity.md; docs/planning/PLANNING_circling_label_transition_dispatch.md; docs/planning/PROBE_exterior_dwell_loiter.md (491195ed9)
- **Forensic keys (1):**
  - `probe_outcome_2026_08_17`: PROBE DONE (PROBE_exterior_dwell_loiter.md, 491195ed9). RECOMMENDATION: DON'T build a raw duration predicate now. 623 person tracks / 11 days. Hypothesis PARTLY confirmed: dwell DOES leak into pass_by (41 tracks >5min, 4 >20min, max 70mi...

### `EXTERIOR-GUEST-EGRESS-1` - Exterior->interior guest admission: plumb identity through the egress event so an UNKNOWN person crossing inside can corroborate guest
thread: **presence** - status: **parked** - approval: **explicit**
_updated 2026-08-18 01:45 · refined_
- **Problem / Solution:**
  - P1 the egress detector cannot say WHO. `EgressDirectionTracker` (transit_validator.py:829-1140) ALREADY resolves direction correctly — egress cam then interior cam within EGRESS_ENTRY_WINDOW_SECONDS => `entry`; reverse => `exit`; else `a...
  - P2 interior adjacency is unmodelled — `_get_interior_cameras_near()` (transit_validator.py:1130-1140) returns ALL interior cameras with an explicit "without explicit adjacency mapping from the user" comment, so an `entry` can be confirme...
  - P3 the exterior track and the egress crossing are never joined — the linker has NO reference to `ura_person_egress_event` and the egress tracker never reads tracks; a track that approaches an egress camera and vanishes just closes on `id...
  - P4 guest must not be thresholded off exterior presence. S4 exterior arrival is a CORROBORATOR only — it may raise confidence in, or shorten the dwell for, a guest-room-gated entry; it may NEVER solo-arm guest. Operator: "Never 'someone i...
- **Origin:** 2026-08-16 - Split out of CENSUS-DECAY-SEPARATION-1 P8 after the exterior investigation showed exterior->headcount and exterior->guest are different-risk problems. Operator's own framing: "We would need to know the transition from outsid...
- **Why:** Completes the operator's (b) concern — the transition INTO guest — with a causal mechanism rather than a count threshold. Deliberately split from the cycle-2 headcount swap because the risk profiles differ sharply: the headcount swap is ...
- **Next:** PARKED (deferred): the face-independent nudge revisits only if the identity path proves insufficient. Trigger: identity-at-egress shipped + shown to miss real guests.
- **Tags:** tier-3, context-wide-scoping, producer-and-consumer, marginal-benefit-pushback
- **Refs:** custom_components/universal_room_automation/transit_validator.py:829-1140; custom_components/universal_room_automation/exterior_track_linker.py:766-777; docs/planning/RESEARCH_census_vs_guest_separation.md; docs/PLANNING_v3.5.2_CYCLE_6.md:428-551; docs/planning/PLANNING_exterior_guest_egress.md (486627875)
- **Forensic keys (6):**
  - `d0_probe_outcome_2026_08_17`: D0 PROBE DONE (PROBE_exterior_guest_egress.md, 1970f6360) — REJECTS the identity path, FINDS a face-independent alternative. Numbers: egress events fire ~50/day (186 entry/wk, 6651 rows over 166d in person_entry_exit_events; ambiguous fi...
  - `operator_ruling_2026_08_17_build_both`: OPERATOR RULING 2026-08-17 (overrides the D0 NO-GO on identity): "Build both face and face-independent solution and use face as a confidence boost." Plus critical context that INVALIDATES the D0 face measurement: (1) the D0 probe measure...
  - `protect_reprobe_2026_08_18`: PROTECT FACE RE-PROBE (PROBE_protect_face_egress.md) — the "build both" face premise does NOT hold on current sensing. Findings: (1) UniFi Protect exposes face to HA ONLY as event.<cam>_smart_detection {event_type:face} = face DETECTION,...
  - `operator_corrections_2026_08_18`: OPERATOR 2026-08-18 (build face-independent + corrections): (1) SPIKE EXISTS — RESEARCH_protect_face_to_ha.md (2026-08-15) already evaluated getting Protect face NAME into HA. Protect API capability CONFIRMED (name+id+confidence verified...
  - `cycle3_scope_final_2026_08_18`: CYCLE 3 SCOPE (operator): BUILD the face-INDEPENDENT arm NOW (approach-track->egress corroboration, 94% GO from PROBE_exterior_guest_egress.md) as a census_confidence contribution to the unidentified gate (INV-4 path b, never a third arm...
  - `direction_2026_08_18`: OPERATOR CHOSE IDENTITY PATH FIRST (over the planner's BUILD-the-nudge). The face-independent Tier-3 approach->census_confidence nudge (PLANNING_exterior_guest_egress.md rev-2, orchestrator dissented on marginal-benefit) is DEFERRED — re...

### `CENSUS-G6-RAW-PERSISTENCE` - G6 (PARKED, build only if needed): gate guest persistence on RAW unidentified, not the held/decayed value
thread: **presence** - status: **parked** - approval: **implied**
- **Origin:** 2026-08-16 - Operator: "Do both [G1+G4]. Card G6 and only use it if needed."
- **Why:** Census hold(3min)+decay(-1/300s) makes a phantom structurally durable ~25 min, outlasting the 300s guest persistence gate — so "sustained" cannot distinguish sustained-because-real from sustained-because-held. ~15 LoC, D8 threading pattern.
- **Refs:** docs/planning/RESEARCH_guest_actuation_and_census.md
- **Forensic keys (1):**
  - `revisit_trigger`: Build ONLY if, after G1+G4 ship, a phantom or a genuinely transient presence (delivery, brief visitor) still sustains guest mode. Under G4 this should be structurally blocked — no guest room sustaining 30min means no guest activation — s...

### `CENSUS-GUEST-FLOOR-1` - Census blind to guests (read 4 with 10 in house) — re-admit the WiFi guest-VLAN count as a bounded FLOOR, gated to contain the FP problem that unplugged it
thread: **presence** - status: **parked** - approval: **unreviewed**
- **Origin:** 2026-08-15 - operator: "census says 4 but there are 4 of us and 6 guests — how is it missing this many people"
- **Why:** Census total = identified(BLE+face, structurally household-only) + camera_unrecognized(3-min hold). Guests only count while standing in view of transit-tier census cameras; the guest phones on the Revel VLAN ARE counted by _get_wifi_gues...
- **Next:** ura-planner scope after current deploy queue clears; Tier 2 (presence/census shared primitive -> possibly 2-DB per standing policy).
- **Parsimony:** [SIMPLIFY] the census cannot count unidentified people outside census-camera view even when their devices announce them
- **Refs:** custom_components/universal_room_automation/camera_census.py
- **Forensic keys (2):**
  - `proposed_shape`: total = max(total, identified + wifi_guest_floor), the floor admitted ONLY under guards: guest-mode active OR count stable >N min; existing family-exclusion layers retained; kill switch = existing exclusion default. Numbers get knobs.
  - `parked_2026_08_15`: SHRUNK by the regression root-cause (CENSUS-SUFFIX-FIX-1): the census was count-accurate until 08-13; the suffix fix restores that. Revisit trigger: AFTER the fix ships + one real gathering, if guest counts still under-read materially, r...

### `HOUSE-STATE-UTILIZATION-EPIC` - ROADMAP EPIC — give operational meaning to under-consumed house states (HOME_DAY dead, AWAY thin); rungs 2-4 unbuilt
thread: **presence** - status: **parked** - approval: **explicit**
- **Origin:** 2026-07-30 - Plan inventory audit 2026-08-14: PLANNING_house_state_utilization.md is an operator-ratified multi-cycle roadmap; rung 1 shipped in a parallel cycle, rungs 2-4 unbuilt.
- **Why:** Roadmap marker, not one build — several house states carry little operational weight. Carded as an epic so the rungs are not lost; each rung becomes its own Tier-2 cycle when pulled.
- **Next:** Operator picks a rung to activate; until then held as roadmap.
- **Refs:** docs/planning/PLANNING_house_state_utilization.md
- **Forensic keys (1):**
  - `revisit_trigger`: Pull a rung when a concrete house-state-driven behavior is wanted; decompose per-rung then.

### `ARRESTER-BOOT-BLIND-1` - Arrester boot-window manual blindness — manual holds predating the listener are unclassifiable
thread: **hvac** - status: **parked** - approval: **unreviewed**
- **Origin:** 2026-08-11 - operator: "The battery is not 97%. The arrester should be seeing this as a bad action" — up-hallway manual 75->71 cool during a 26->11 SOC collapse, arrester idle w/ overrides_today=0.
- **Why:** LIVE INCIDENT ~22:36-23:10: zone_2 flipped sleep->manual at 22:36:06 during the post-HA-upgrade boot window BEFORE the arrester listener attached (22:37:53); subsequent setpoint walks (75->71 at 22:56) were within-manual = no classifiabl...
- **Next:** Incident investigation: verify both gaps from source; probe-first (recorder: boot-coincident manual holds frequency); fix cycle Tier 2-DB.
- **Forensic keys (3):**
  - `parked_2026_08_12`: OPERATOR: "Park #2 until another incident." Revisit trigger: next boot-coincident manual hold the arrester misses (same signature: zone flips to manual during boot window, setpoint walks within-manual, arrester overrides_today stays flat...
  - `sharp_problem`: Gaps: (1) boot reconciliation — on listener attach, classify any zone ALREADY in manual as inherited-manual and start standard arrest evaluation; (2) verify _handle_climate_change classifies within-manual setpoint deltas (manual->manual ...
  - `related`: Envoy reserve wedge (device=10 vs cloud=26/27) is the energy half — the write-verify self-heal alert was RIGHT to fire. RESOLVED 2026-08-12: operator power-cycled Enpower; all 3 reserve legs coherent at 10 (local number + envoy sensor + ...

## ✅ Done (25)
_closed, evidence in refs_

### `DOC-DRIFT-ZONE-AWAY-1` - Coordinator manuals stale vs code on zone-away / away-veto (PRESENCE_COORDINATOR.md badly stale)
thread: **docs** - status: **done** - approval: **unreviewed**
_updated 2026-08-17 23:40_
- **Problem / Solution:**
  - P1 PRESENCE_COORDINATOR.md away-veto section (:1233) documents ONLY the v4.7.14 predicate — missing D8 (face_recognized_count/census_count clauses), the ENTIRE Path β LOST-admitted veto, and the LOST six-state matrix; infer() pseudocode ...
  - P2 HVAC_MANAGEMENT_EXPLAINER.md:34 preset-map ref stale (:303 -> :780) + stale "guest planned v4.7.x" note. S2 fix refs.
  - P3 HVAC_COORDINATOR_MANUAL.md §3.1 omits the per-zone vacancy override (hvac.py:1544-1554) forcing away preset while house home. S3 add it.
  - P4 ABSENCE: no manual documents (a) the ZonePresenceTracker three-tier OR (BLE->sensor->camera) as the house-zone away mechanism, nor (b) that HVAC-zone occupancy = OR of room-level occupied bools (hvac_zones.py:146/546), NOT the zone tr...
- **Origin:** 2026-08-17 - Operator asked to check manuals against code for house-zone vs HVAC-zone away; AUDIT_zone_away_house_vs_hvac.md (7f54068fb) found 4 drifts.
- **Why:** These manuals are the institutional-context surface reviewers and planners consult. Stale away-veto docs directly caused wasted cycles this session (assumptions about away logic had to be re-derived from code). Keeping them current is ch...
- **Next:** DONE (673e91b07). PRESENCE_COORDINATOR.md away-veto + LOST-matrix + house-zone OR rewritten; HVAC explainer preset-map ref + HVAC manual §3.1 vacancy override + HVAC-zone-occupancy-source gaps fixed. Orchestrator spot-check confirmed pat...
- **Refs:** docs/planning/AUDIT_zone_away_house_vs_hvac.md (7f54068fb); docs/Coordinator/PRESENCE_COORDINATOR.md; docs/Coordinator/HVAC_COORDINATOR_MANUAL.md

### `GUEST-ROOM-CONFIG-1` - Guest-room designation was wrong: a BATHROOM was flagged is_guest_room (unflagged 2026-08-17)
thread: **presence** - status: **done** - approval: **explicit**
_created 2026-08-17 21:20 · updated 2026-08-17 23:30 · initial_
- **Problem / Solution:**
  - Problem: a downstairs guest BATHROOM was marked as a "guest room". Because the check that excludes known residents was broken, ANY 30-minute stay in that bathroom would have flipped the whole house into guest mode — and a bathroom gets u...
  - Solution: unmark the bathroom. The only rooms that can trigger guest mode are now the two actual guest bedrooms. (Details and the flow-API gotcha are in the card notes and refs.)
- **Origin:** 2026-08-17 - Operator flagged the Down Guest Bathroom designation as a misconfiguration while reviewing which rooms should carry the guest role.
- **Why:** Config correctness, and a prerequisite for D2 being safe: D2 makes the guest-room gate the SOLE arm for GUEST, so the designated set becomes load-bearing.
- **Next:** None — done. Verified live: designated set = Guest Bedroom 1, Upstairs Guestroom.
- **Refs:** custom_components/universal_room_automation/config_flow.py:9193; custom_components/universal_room_automation/const.py:386

### `BOARD-CURRENCY-1` - Forcing-function ladder so the board (and vibememo) cannot lag shipped work
thread: **process** - status: **done** - approval: **explicit**
_created 2026-08-09 00:00 · updated 2026-08-17 23:12 · refined_
- **Origin:** 2026-08-09 - operator on the stale board: "A banner is not a forcing function. Is there a harder one? A kanban that does not keep current is fairly useless" -> then "yes deploy gate with softer backups as well (the other 2 or 3). We shou...
- **Why:** Board reconciliation is the ONLY step in the deploy ritual with no forcing function. deploy.sh refuses without tests and without a README; NOTHING refuses without a board update, so it is the only step running on willpower — and it rotte...
- **Next:** DONE. Organic proof LANDED 2026-08-17: the post-push write path executed for real for the first time on the v5.79.0 deploy — kanban_ship marked 2 cards shipped + vibememo_ship wrote entry 055 automatically. The forcing function is proven...
- **Tags:** numbers-get-knobs, institutional-context
- **Sibling of:** KHOST-1
- **Parsimony:** [BUILD] the board silently lags shipped work, so picking "next" off it can rebuild already-shipped features
- **Refs:** docs/planning/PLANNING_v4.7.10_deploy_sh_gitea_retrofit.md (precedent for modifying deploy.sh); scripts/deploy.sh:32-36 (existing hard-gate pattern to mirror); .claude/skills/ura-kanban/SKILL.md (Forcing functions section)
- **Forensic keys (7):**
  - `ladder`: RUNG 1 (HARD — the forcing function): deploy.sh gains --cards ID[,ID...]. REFUSES to deploy when absent, printing current in_progress/review cards as candidates. --no-cards escape for pure-docs releases. On success it WRITES status: ship...
  - `RUNG5_DURABILITY_GAP`: The 01:23 job is SESSION-ONLY — in-memory, dies when the Claude session exits, and auto-expires after 7 days. So it does NOT yet fully solve the KHOST-1 miss: if the session ends before 01:23, the overnight pass silently does not happen ...
  - `scope_note`: Rung 1 hardens only the SHIPPED transition. pre_planning->planned->in_progress stays soft (turn-end hook). Deliberate: every card found stale on 2026-08-09 was shipped work the board still called "build" — the rot is concentrated exactly...
  - `review_record_2026_08_09`: Reviewed DO-NOT-SHIP -> fixed -> re-verified. H1 YAML reflow: safe_dump round-trip rewrote the real board 1296->1455 lines, re-wrapping every card's prose at 80 cols. Replaced with a textual line-anchored writer (parse to VALIDATE, edit ...
  - `residual_fragility`: A card whose status: line is quoted (status: "planned") would not match the writer regex — the card is skipped with a WARN rather than silently mis-written. No such card exists today; worth a lint if quoting ever starts.
  - `meta_note`: The first card this gate marks shipped will most likely be itself.
  - `DEDUPE_2026_08_09`: Four-surface sweep run. Board: KHOST-1 adjacent (owns rung 3, the generator) — linked, not merged, because rung 1 lives in release machinery not the generator. TRANSIT-DIAG-1 matched on "diagnostic" only, unrelated. BACKLOG.md: no match....

### `FRIGATE-RETIRE-1` - Retire Frigate-1 — promote Frigate-2 (yolov9t/OpenVINO, zero night ghosts) to primary incl. snapshot engine
thread: **security** - status: **done** - approval: **approved**
- **Origin:** 2026-08-12 - operator: "We should just retire frigate 1 instead of writing more code" + "Frigate 2 is our identical backup. We should move snapshots to it" + "Go".
- **Why:** Probe: 100% of night person alerts = frigate-1 single-witness sub-2s IR ghosts; frigate-1 thresholds already raised once (07-30 snapshot) and ghosting persists. Frigate-2 runs a DIFFERENT detector (custom yolov9t.onnx OpenVINO) with ZERO...
- **Next:** Operator word on final deletion (entry + registry sweep) -> then card closes. Recording tripwire stays permanently (F2 is sole recorder).
- **Forensic keys (11):**
  - `procedure`: CONSOL-1 §7 retirement doctrine: (1) capability inventory audit; (2) parity swap — URA perimeter sensors + snapshot instance -> frigate-2 with BOTH running; (3) Gate-1 N=5 organic events clean by ledger -> disable frigate-1; (4) Gate-2 N...
  - `audit_2026_08_12`: GO. 24/24 cameras identical both hosts (sole gap: ArmCrestASH41B enabled F1/disabled F2 — deliberate one-NVR-at-a-time; flip at window open). URA needs ZERO code changes (fused legs subscribe both instances; snapshot discovery automatic,...
  - `window_open_2026_08_12`: EXECUTED (operator "Go"): (1) F2 recording tripwire automation live (automation.frigate2_recording_tripwire_frigate_retire_1 — 30min-poll frozen-share check >6h + unavailable-30min leg -> WhatsApp; template-trigger pitfall caught: a froz...
  - `operator_refinements_2026_08_12`: (1) FP-gate preference RULED: cross-corroboration (Protect agreement) preferred over duration/latency gates — "I don't like the latency idea. Much prefer x-corroboration." Applies if frigate-2 ghosts post-promotion. (2) Evidence chain: h...
  - `ura_ref_swap`: FOUND during window-open verify (audit's "zero URA changes" was wrong at the entity layer): 26 F1-owned entity refs across 4 URA config entries (main entry 14 perimeter cameras, Zone Manager 6 occupancy sensors, Garage Hallway 3, Garage ...
  - `entity_migration_2026_08_12`: DONE (operator approved). Mechanism pivot: ha CLI unauthorized for ssh user -> did 50 entity-registry renames via API instead of .storage surgery: every dead F1 entity -> *_f1retired (reversible), F2 twin -> the id URA references. Bonus:...
  - `gate1_recheck_2026_08_13`: GATE-1 MET. Night window 08-12 23:00 -> 08-13 05:00 CT: ZERO person alerts (vs multiple F1 ghosts every prior night) — the ghost pattern died with F1. Only 2 legit-category vehicle deep-night alerts (rear_ptz, Protect-sourced). Clean cou...
  - `gate2_started_2026_08_13`: OPERATOR APPROVED. F1 HA integration entry 01JV6G4E57HT3WH86WSQ4RJT11 DISABLED + unloaded (11:4x CT). Container stop handed to operator (host is password-SSH only): ssh okosisi@192.168.13.16 sudo docker stop frigate double-take. Gate-2 c...
  - `reaudit_2026_08_13`: Operator-requested post-disable re-audit: PASS — 443 URA entity refs, 0 F1-owned; snapshot engine self-heals to F2-only; MQTT dual-prefix clean; census/resolver skip disabled entities. Findings ALL FIXED live same hour: MED automation.g6...
  - `gate2_met_2026_08_14`: GATE-2 MET + BOX PHYSICALLY POWERED OFF (operator, ahead of formal completion — with all software layers already dark, physical-off IS the authentic Gate-2 test and it passed). Since F1 disable: 10 dispatches, all healthy — incl. a SAME-...
  - `decommissioned_2026_08_15`: Operator go ("Frigate 1 hardware full decomm"; homelab agent repurposing the box). URA side EXECUTED: config entry 01JV6G4E57HT3WH86WSQ4RJT11 deleted in-band (ha_remove_helpers_integrations) — all 965 F1 entities + 25 *_f1retired renames...

### `IMSG-IMAGE-FAIL-1` - iMessage security images NOT arriving (organic FAIL of NM-BB-IMAGE-1 L5) + [audit] sentinel leaking into operator-visible message bodies
thread: **notifications** - status: **done** - approval: **unreviewed**
_updated 2026-08-17 23:55_
- **Origin:** 2026-08-14 - Operator screenshots: WhatsApp carries photos (incl. re-pages — v5.73.1 L3 CONFIRMED organically on WA); iMessage shows text-only bubbles reading "Perimeter Alert — Person Detected [audit]" — no image AND the [audit] ledger ...
- **Why:** Two distinct defects: (1) BB v0.6 attachment keys (v5.73.0 NM-BB-IMAGE-1) not delivering images — key contract vs BB server config vs is_allowed_path (probe BB server logs + a manual bluebubbles.send_message with attachment to isolate); ...
- **Next:** Tier-1 investigation: trace _send_imessage payload for a security alert (body composition + attachment fields); one manual BB send with a known-good local path; check whether audit-tagged duplicates are entering the send path. Fix both i...
- **Forensic keys (1):**
  - `resolution_2026_08_17`: Operator confirmed 2026-08-17: security images ARE arriving. The prune-audit "active fail" read was wrong — feature works. Closed.

### `PWA-CONTROL-LIST-1` - Per-room controllable-entities attr so the PWA stops slugify-guessing actuators (AV-Closet-Shelly problem)
thread: **dashboarding** - status: **done** - approval: **operator-approved**
- **Origin:** 2026-07-13 - Plan inventory audit 2026-08-14 found PLANNING_g1_room_control_list_attrs.md unbuilt + uncarded — PWA M2 gap G1.
- **Why:** PWA guesses a room's actuators by slugifying the room name; wrong for rooms whose real device is a differently-named Shelly relay (AV Closet). A per-room control_list attribute (additive, no behavior change, no new entities) gives the PW...
- **Next:** Operator: deploy the PWA branch when ready (npm run deploy after merge).
- **Tags:** audit-first
- **Parsimony:** [BUILD] PWA cannot reliably map a room to its controllable entities
- **Refs:** docs/planning/PLANNING_g1_room_control_list_attrs.md
- **Forensic keys (2):**
  - `note`: Re-scoped + BUILT 2026-08-16 PWA-side (no URA changes needed): useRoomDevices(slug) in ura-dashboard-pwa prefers sensor.<slug>_devices attrs (real configured entity_ids) with observable console.debug fallback to the existing G1 control_*...
  - `duplicate_verdict_2026_08_16`: Operator: "we have a device list sensor — does that duplicate?" -> YES, substantially. Per-room DevicesSensor (sensor.<room>_devices, sensor.py:2035) already exposes categorized attrs: lights, fans, humidity_fans, covers, auto/manual dev...

### `ZONE-CAM-PERSON-GUARD-1` - Durable device_class guard so a Frigate MOTION sensor cannot be trusted as camera person-confirmation in zone occupancy-confidence
thread: **presence** - status: **done** - approval: **unreviewed**
_refined ×1_
- **Origin:** 2026-07-13 - Plan inventory audit 2026-08-14: PLANNING_zone_camera_person_only_guard.md unbuilt + uncarded; the 2026-06-08 live finding was only fixed by config removal, not code.
- **Why:** CONF_ZONE_CAMERAS entries are trusted as person-confirmation by the presence Source-3 occupancy-confidence scorer (-> hvac.py stale-sensor guard). A motion-only Frigate sensor mis-filed there is trusted as a person confirm. No device_cla...
- **Next:** ura-planner; Tier 2 (touches occupancy-confidence scorer).
- **Parsimony:** [BUILD] a non-person camera sensor in CONF_ZONE_CAMERAS is trusted as person-confirmation
- **Refs:** docs/planning/PLANNING_zone_camera_person_only_guard.md
- **Forensic keys (3):**
  - `closed_2026_08_15`: CARD DEAD AS WRITTEN per context-wide audit (AUDIT_zone_cam_guard_necessity.md, 1e8b27e96). Operator was right: the person-only suffix guard EXISTS (camera_census.py:362-386 + camera_resolver.py:215-236) and covers room override + zone t...
  - `rider_update_2026_08_15`: Rider FAILED at v5.77.0 restart (script flat-scan hit nested zones dicts). Rewritten with recursive walk, dry-run verified (exactly the 2 zone edits), re-staged for NEXT restart. Rider bug class noted: .storage editors must handle nested...
  - `rider_applied_2026_08_15`: APPLIED + VERIFIED at operator-requested restart (~17:25 CDT): flush caught, both zone edits landed (Back Hallway + Upstairs -> person-only sensors), post-boot residue 0, swaps present TRUE. Card fully closed — nothing outstanding.

### `CENSUS-SUFFIX-FIX-1` - Census regression ROOT-CAUSED: strict-suffix matchers miss all _2 F2 sensors since F1 death (08-13) -> count sensors unmapped -> census pinned at identified count. Fix: disambiguation-tolerant matching.
thread: **presence** - status: **done** - approval: **implied**
- **Origin:** 2026-08-15 - operator: "census used to be more or less accurate — what changed?" Recorder: daily max 6-7 through 08-12, 4 from 08-13 (F1 entity death). AUDIT_census_accuracy_regression.md (a54379830), H1 confirmed, H2/H3/H4 refuted.
- **Why:** All F2 count sensors are _2-suffixed; _PERSON_COUNT_SUFFIX endswith matching (camera_resolver.py:272/1288 + camera_census.py:400/793) matches none -> binary fallback max-1-per-camera -> unrecognized=max(0,~4-4)=0 -> total=identified fore...
- **Next:** Builder in flight (strip-before-match at all strict sites + ambiguity guard + drills); 2 reviews; batches into the pending reload/opt-meta deploy. Post-deploy Live: census exceeds 4 during next multi-person traversal.
- **Refs:** docs/planning/AUDIT_census_accuracy_regression.md
- **Forensic keys (4):**
  - `operator_ruling_ash41b_2026_08_15`: ASH41B (Study A): stays OUT of camera_person_entities (census) by operator ruling — camera is physically blocked by a screen unless operator is away, so zero-detection history is EXPECTED (not a Frigate pipeline fault; struck from the F2...
  - `live_validation_2026_08_15`: v5.77.0 LIVE: L1 PASS; L2 organic — census at 4 post-boot pending first camera traversal; PASS = first recorder reading >4 (guests in house tonight = likely within hours).
  - `l2_watch_redefined_2026_08_15`: Guests departed before a >4 traversal registered (census max stayed 4 post-boot). L2 proof redefined: INTERIM = any unidentified contribution (census reads identified+1 on any visitor/delivery in census-camera view — was structurally imp...
  - `l2_INTERIM_PASS_2026_08_16`: ORGANIC PROOF (operator home, ~evening): census reads 6 = identified 4 + unidentified 2, camera_unrecognized 2, source_agreement close, confidence medium, wifi_guest_floor 6 (independent corroboration). Pre-fix this was STRUCTURALLY IMPO...

### `D3-BEHAVIOURAL-COVERAGE-1` - D3 guest-room registry resolution has ZERO behavioural coverage — all six tests are source-shape
thread: **presence** - status: **done** - approval: **unreviewed**
_updated 2026-08-18 02:30_
- **Problem / Solution:**
  - P1 all six D3 tests assert on SOURCE SHAPE (the registry call appears in the file), not on BEHAVIOUR (a guest room actually resolves to its occupancy entity). Review C proved this class is evadable: the sibling anchor test_unresolvable_r...
  - P2 D3 is now load-bearing: under cycle-1 D2, guest entry depends ENTIRELY on guest-room occupancy, so a silent D3 resolution failure means guest mode never arms at all. Source-shape tests cannot catch a registry lookup that returns the w...
- **Origin:** 2026-08-16 - Review C (guest-census cycle, d9a74e86e) observation while auditing test authority. Logged as follow-up; C was explicitly told NOT to expand the fix-up scope to cover it.
- **Why:** The cycle-1 fix-up repairs the ONE anchor Review C proved hollow (C-MED-1, via caplog) but deliberately does not build out the rest. Without this card that gap disappears, and it sits under the newly load-bearing guest entry path.
- **Next:** DONE (merged 7a2e73aa2, tests-only): 5 behavioural tests driving production _discover_guest_rooms + _handle_guest_room_occupancy_change vs a fake registry; 4 mutation drills (plain+variant-7) red-then-green; zero production change. D3 re...
- **Tags:** test-authority, hollow-anchors
- **Refs:** docs/reviews/code-review/guest_census_review_C.md; custom_components/universal_room_automation/domain_coordinators/presence.py

### `MDNS-SERIAL-HOSTS-1` - mDNS-serial hostnames breaking cross-VLAN camera consumers — amcrest FIXED; audit F2 RTSP paths + any other serial-host configs
thread: **devices** - status: **done** - approval: **implied**
- **Origin:** 2026-08-15 - Operator: "some kind of mDNS error" on amcrest entry 01KFAEN928S190YEJ2V4SWY6S6 + "multiple integrations point at that camera — did the IP change?"
- **Why:** IP did NOT change (camera at 192.168.15.96 for 8.4d; sibling dahua entry pinned .96 all along). Cross-VLAN mDNS reflection broke, killing serial-hostname consumers. FIXED: amcrest host serial->IP (flush-watcher) + DHCP reservation pinnin...
- **Next:** HOMELAB AGENT: check live F2 config for serial-hostname RTSP paths (pooloverhead at minimum; grep AMC serials); replace with pinned IPs. Also consider reservations for any other cameras without fixed IPs.
- **Forensic keys (3):**
  - `closed_2026_08_16`: DEAD on verification (operator push: "why card it vs fix it"). The suspected second victim does not exist: zero frigate-platform entities for pooloverhead in the live registry — the camera is NOT in the current F2 config; the serial-host...
  - `final_resolution_2026_08_16`: REAL root cause (operator kept pushing past my two wrong layers): the CUSTOM amcrest component performs a LIVE mDNS lookup at every setup whenever entry.data.mdns exists — it IGNORES host entirely (async_setup_entry: mdns key -> zeroconf...
  - `operator_context_2026_08_16`: Pool-overhead camera is watched by FOUR integrations — Protect, Frigate 2, Dahua, Amcrest — a random artifact of broad integration coverage, NOT intentional per-integration roles. Do not be confused by multiple entity families for this o...

### `MEMORY-COMPACTOR-1` - Hierarchical memory — build the deferred daily compaction batch when memory_episodes has volume (trigger: any episode type >50 rows)
thread: **memory** - status: **done** - approval: **explicit**
_created 2026-08-11 00:00 · updated 2026-08-17 23:30 · refined_
- **Problem / Solution:**
  - Problem: the house records thousands of raw memory events but never boils them down, so a reader (or the rooms themselves) can't consult a compact history — the volume just grows. Solution: a nightly job that reads the raw events and wri...
- **Origin:** 2026-08-02 - operator: "What if each room had memory?" Hierarchical Entity Memory MVP Stage 1 SHIPPED v5.47.0; the daily compactor was deferred until episode volume exists.
- **Why:** Stage 1 facade + memory_episodes + memory_query service are LIVE (v5.47.0, Tier 2-DB). The distill/correct/redact compaction batch needs rows to compact; the architecture keeps it in full, the MVP deferred only its construction. Untracke...
- **Next:** ORGANIC CONFIRMED 2026-08-17: compactor runs nightly (wired __init__.py:2031, after incremental_vacuum), wrote 14 memory_facts at 02:30 CT today; memory_facts totals 53 rows across 08-15/16/17. Trigger long met (exterior_track 1327, actu...
- **Refs:** docs/planning/MVP_hierarchical_memory.md; docs/planning/ARCHITECTURE_hierarchical_memory.md; docs/reviews/code-review/memory_mvp_tier2db.md
- **Forensic keys (7):**
  - `parent`: MEMORY-PROGRAM-EPIC
  - `revisit_trigger`: ANY memory_episodes episode_type exceeds 50 rows (per MVP_hierarchical_memory.md Stage 1 trim #1) OR facts() seeded set proves inadequate. Check episode row counts before dismissing.
  - `organic_open`: Stage-1 acceptance still open: the next organic D2 demotion must retro-adjudicate its creation episode within one cycle (live DB check) — verify + write back to this card.
  - `trigger_FIRED_2026_08_14`: Live memory_episodes count (mode=ro): 1799 rows; exterior_track=1044, actuation_conflict=639, occupancy_phantom=56 ALL exceed the 50-row build trigger (fan_transition_suppressed=41, comfort_fan_vetoed=19 below). READY, not parked — the d...
  - `go_2026_08_14`: operator: "Do the compaction... Review that plan and see how quickly we can get started on the rest and finish. Do hand checked proofs if need be." -> plan (ura-planner from ARCHITECTURE compactor section) -> Tier 2-DB plan review -> bui...
  - `plan_review_2026_08_14`: Plan review FIX-PLAN-FIRST (2 CRIT: same-transaction invariant unimplementable on per-acquisition write queue -> combined distill_memory_fact DAO; topic vocab gate bypass -> D0 MEMORY_FACT_TOPICS registration + boot assert. 2 HIGH: retro...
  - `live_validation_2026_08_14`: L1/L2/L3/L5 PASS at boot (20 facts, 3 topics, coverage stamp verified, episodes preserved). Organic open: L4 first nightly 02:30 tick. Entity-id correction: device-prefixed ura_coordinator_manager_*.

### `MEMORY-FIRST-DIAGNOSTICS-1` - Memory-first diagnostics doctrine — memory_query is the FIRST surface checked in any investigation/trace, encoded in memory + skills
thread: **memory** - status: **done** - approval: **explicit**
- **Origin:** 2026-08-14 - Compactor go turn: operator noticed investigations (AWAY-BLOCK-1 etc.) hand-mined recorder/DB while 1799 adjudicated memory_episodes sat unconsulted.
- **Why:** The facade exists precisely to answer "what happened in this room/zone/house" — but no diagnostic workflow invokes it. Doctrine: episodes/narrative/unusual via memory_query BEFORE raw recorder mining; raw mining remains the verify step, ...
- **Next:** Amend memory (feedback file) + CLAUDE-adjacent investigation surfaces; retro-analysis quantifies the win.
- **Refs:** custom_components/universal_room_automation/memory_facade.py
- **Forensic keys (2):**
  - `parent`: MEMORY-PROGRAM-EPIC
  - `closed_2026_08_16`: Doctrine shipped: all four investigation skills carry the mandatory memory-first section; feedback memory + MEMORY.md pointer written; retro (AUDIT_memory_retro_value.md) supplied the evidence. Nothing outstanding.

### `MEMORY-RETRO-VALUE-1` - Retro-check — which answers in the last few investigations were already derivable from memory_episodes?
thread: **memory** - status: **done** - approval: **explicit**
- **Origin:** 2026-08-14 - Same push as compactor go.
- **Why:** Evidence for the memory-first doctrine + input to the compactor plan (which episode types earn distillation priority).
- **Next:** Agent replays AWAY-BLOCK-1, guest-FP, Frigate-ghost, fan-latch questions against live memory_episodes; report what memory would have answered vs what we hand-mined.
- **Refs:** docs/planning/AUDIT_away_transition_2026_08_13.md
- **Forensic keys (1):**
  - `result_2026_08_14`: AUDIT_memory_retro_value.md (commit 6a99575fa). Verdicts: AWAY-BLOCK-1 PARTIAL (all 56 occupancy_phantom rows share mmwave_sole_fan_on_no_corroboration -> profile()/unusual() primes the fan-sustain hypothesis in minutes vs 4h recorder tr...

### `MEMORY-WRITERS-1` - Memory episode-writer coverage gaps — writers ride the detectors, so memory is blind where detectors fail (retro: 0 FULL / 2 PARTIAL / 2 NONE)
thread: **memory** - status: **done** - approval: **unreviewed**
_created 2026-08-11 00:00 · updated 2026-08-18 02:20 · initial_
- **Problem / Solution:**
  - Problem: the house only remembers an event if the detector that watches for it fires — so wherever a detector is missing or blind, that history is simply never recorded (a gap you can't see). Solution: add a few targeted event-writers fo...
- **Origin:** 2026-08-14 - MEMORY-RETRO-VALUE-1 finding: occupancy_phantom writer inherits D2 fail-closed no-PIR gate; both recent incidents lived in rooms memory never heard about.
- **Why:** Memory-first diagnostics only pays if memory covers the question. Candidate writers from the retro (ranked by incident coverage): (1) D2-independent retro phantom writer keyed on fan-release correlation — would have captured ALL FIVE lat...
- **Next:** DONE — top-2 writers shipped v5.78.0. Optional zone_phantom parked (MEMORY-ZONE-PHANTOM-WRITER-1).
- **Parsimony:** [SIMPLIFY] memory cannot answer diagnostic questions about the rooms/mechanisms where incidents actually occur
- **Refs:** docs/planning/AUDIT_memory_retro_value.md
- **Forensic keys (4):**
  - `parent`: MEMORY-PROGRAM-EPIC
  - `folded_2026_08_16`: FOLDED into the PATH-ALPHA cycle as D4-D7: phantom_retro, away_transition_blocked, tracker_trust_excluded (operator add), house_state_transition. Two candidates DROPPED with justification, zero parked (operator no-debt rule). Building now.
  - `live_validation_2026_08_16`: v5.78.0 LIVE 2026-08-16. L1 PASS (0 errors), L4 PASS (face_recognized_count + path_alpha_gate_source live on house-state sensor). L2 PASS-on-state / attribution organic: house is away with all 4 persons not_home and census 0 — but the tr...
  - `scope_reset_2026_08_18`: PLAN (PLANNING_memory_writers.md) found the card premise STALE: the named "top 1-2 writers" phantom_retro + away_transition_blocked are BOTH ALREADY SHIPPED in v5.78.0 (D4 memory_writers.py:101, D5 AwayBlockEpisodeTracker :186). The "4 r...

### `GARAGE-EGRESS-APPLY-1` - APPLY the 2026-08-10 garage-camera ruling — garage_a/garage_b into CONF_EGRESS_CAMERAS at the NEXT deploy restart (operator said do not forget)
thread: **security** - status: **done** - approval: **approved**
- **Origin:** 2026-08-14 - Operator re-raised; ruling of 08-10 (garages -> egress list, NOT interior — noise) was left "config apply pending" for 4 days. Operator: "update config in house device config. And any other place its needed. Batch with next ...
- **Why:** Egress list feeds perimeter_alert egress alerting; garages currently in NO camera list. Accepted consequence stands: D1 stuck-camera never covers garages.
- **Next:** BLOCKS-CLOSE-OF next deploy — do not close the next deploy cycle without this applied + verified.
- **Forensic keys (2):**
  - `apply_procedure`: At next deploy restart: flush-watcher pattern edit of the parent URA entry options.egress_cameras += [camera.garage_a, camera.garage_b] (F2-owned base ids, verified live), applied in the stop->boot gap; post-boot verify list + perimeter_...
  - `closed_2026_08_14`: Applied at v5.76.0 restart via flush-watcher (stop->boot gap); post-boot verified: egress_cameras contains garage_a+garage_b (README v5.76.0 L5 PASS).

### `NM-BB-IMAGE-1` - iMessage photo delivery unblocked — BlueBubbles v0.5/0.6 added attachment + media_url
thread: **notifications** - status: **done** - approval: **approved**
_updated 2026-08-17 23:55_
- **Origin:** 2026-08-11 - operator upgraded BlueBubbles to v0.6.0; release notes show send_message now takes attachment/media_url. Verified in installed source (__init__.py:100-165: attachment=local path w/ is_allowed_path gate, media_url=URL).
- **Why:** Closes SNAP-1-followup-bluebubbles-attachment: NM _send_imessage passes speculative keys (attachment_path / attachment-as-URL) the old integration dropped; new integration reads attachment/media_url. ~10 LoC key rename + delete the one-s...
- **Next:** Tier-1 build dispatched: rename keys, drop WARN, mutation-anchored tests; ride next deploy.
- **Forensic keys (1):**
  - `resolution_2026_08_17`: Operator confirmed 2026-08-17: security images ARE arriving. The prune-audit "active fail" read was wrong — feature works. Closed.

### `FAN-LAYER-1` - DOC-2 fan-actuation shared layer: REVIVED — FAN-MANUAL-1 fired 3 of its 4 park triggers
thread: **hvac** - status: **done** - approval: **explicit**
_updated 2026-08-17 23:30_
- **Origin:** 2026-08-11 - operator, on the fan cycle's 1-CRIT/6-HIGH review round: "Do we have a fan abstraction in our roadmap or kanban? This is why. I know we have a fusion camera abstraction and I think a presence sensor abstraction with intent a...
- **Why:** PLANNING_fan_actuation_shared_layer.md (DOC-2, 2026-08-01) parked the extraction behind a foundation gate + 4 evidence triggers. FAN-MANUAL-1 fired: (1) new-mechanic double-port — the manual-ON hold was ported room-tier + HVAC-tier and d...
- **Next:** BUILD DISPATCHED (Tier 3). Hard dep satisfied: FAN-MANUAL-1 merged at 1f5839c3a.
- **Tags:** tier-3, institutional-context, context-wide-scoping
- **Forensic keys (8):**
  - `priority`: high
  - `seed_already_built`: mark_fan_on_issued() (FAN-MANUAL-1 fix-up) is the first shared primitive — an authored-by channel across all URA ON sites. The extraction grows from it.
  - `gate_check_pending`: DOC-2 foundation gate also requires H8 organic validation of the v5.31.0 manual-off cooldown (a real manual OFF observed not re-arming on the live house). Verify from ledger before build — if unproven, that is the one remaining gate.
  - `PLAN_2026_08_11`: PLANNING_fan_actuation_shared_layer_v2.md (756 lines). Writer set is TEN sites across 5 files, not five — W8 zone-vacancy sweep + W9 pre-arrival bypass ALL machinery (trigger #3 fired at TWO sites). RECOMMENDED SHAPE (b): FanPolicyOracle...
  - `PLAN_REVIEW_1_2026_08_11`: NEEDS-REVISION — TWO MORE MISSED WRITERS: C1 _stop_all_fans_safety (hvac.py:2330-2362, smoke/CO all-zones fan stop — legitimate but must consult w/ safety=True) and C2 hvac_predict._activate_zone_fans (:1038-1102, pre-arrival ON — would ...
  - `PLAN_READY_2026_08_11`: Rev-2 committed: 12 writers (W11 safety-stop w/ safety=True always-ALLOW- but-logged; W12 pre-arrival ON defers under cooldown); FanDecisionSnapshot required-arg contract; INV-FLA-T temporal + per-room lock via oracle.actuate() context m...
  - `DEDUPE_2026_08_11`: Sweep: DOC-2 planning doc is the PARENT (parked, triggers now fired -> READY per the skill rule). FAN-MANUAL-1 is the trigger-firing cycle, linked. ARREST-COMFORT-1 sibling class. THIRD instance of a parked plan's fired trigger surfacing...
  - `organic_evidence`: shipwatch 2026-08-11: v5.70.0 L2 no-fan-flap CONFIRMED (13.3h post-boot, all managed fans steady; Jaya 12.5h continuous). L3 holds + L4 safety still organic-open.

### `PLAN-TIER-1` - Tiered PLAN reviews: quality up front — plans reviewed before builds, like builds
thread: **process** - status: **done** - approval: **explicit**
_updated 2026-08-17 23:55_
- **Origin:** 2026-08-11 - coined during the FAN-MANUAL-1 post-mortem — the plan missed 2 emission sites a one-line grep would have found, costing build + 3 reviews + CRIT fix-up
- **Why:** A plan review is ~20 min; a build round is hours. Protocol now in CLAUDE.md: Tier 1 = none; Tier 2/2-DB = one adversarial plan review (independent re-enumeration, greps not trust); Tier 3 = two framing-disjoint (completeness incl. parked...
- **Next:** apply to the two in-flight plans on arrival; organic proof = a plan-review finding that demonstrably prevents a build round
- **Forensic keys (2):**
  - `first_subjects`: FAN-LAYER-1 plan (Tier 3 -> 2 plan reviews) and ARREST-COMFORT-1 plan (likely Tier 3 -> 2) — both in flight as this lands; they get the treatment on delivery.
  - `resolution_2026_08_17`: Operator ruling 2026-08-17: "The cards that are judgement calls, resolve as done." Proof was a process/latent-event judgment not observable in live state; operator closed.

### `TEST-2` - "Send Test Perimeter Alert" button
thread: **perimeter** - status: **done** - approval: **implied**
- **Origin:** 2026-08-07 - same push as TEST-1
- **Why:** delivery crosses into 3rd-party services; only a live end-to-end send proves it
- **Next:** button entity -> canned snapshot through all 4 channels
- **Tags:** numbers-get-knobs
- **Parsimony:** [BUILD] no way to prove channel delivery without waiting for a real intrusion
- **Forensic keys (1):**
  - `verified_shipped_2026_08_16`: VERIFIED SHIPPED: SendTestPerimeterAlertButton present in button.py (2 refs) and exercised live this week. Card was stale.

### `FRIG2SNAP-1` - frigate2 instance-id snapshot URL
thread: **camera** - status: **done** - approval: **implied**
- **Origin:** 2026-08-07 - found mid-investigation
- **Why:** endpoint is instance-scoped; URA builds only default shape -> frigate2-hosted cameras can't resolve a snapshot at all (latent since prefix-split)
- **Next:** fold into SNAP-1
- **Tags:** no-fabrication-verify
- **Parsimony:** [BUILD] any camera on the 2nd Frigate host has never had a snapshot
- **Forensic keys (1):**
  - `verified_shipped_2026_08_16`: VERIFIED SHIPPED: instance-scoped snapshot machinery live in perimeter_alert.py (_discover_frigate_instance_ids / frigate-f2 refs) and validated during the F1 retirement. Card was stale.

### `KP-ESCALATE-1` - Known-person / face-alert path (no URA successor)
thread: **security** - status: **done** - approval: **blocked**
- **Origin:** 2026-08-07 - discovered via purged Frigate_KnownPerson_* files + AUDIT rec 5
- **Why:** face-recognition paging has no URA successor; lost when the doorbell automation retires unless built into perimeter NM
- **Tags:** institutional-context, audit-first
- **Parsimony:** [BUILD] retiring the doorbell automation silently drops face-alert paging
- **Refs:** PLANNING_exterior_person_escalation.md
- **Forensic keys (3):**
  - `direction_2026_08_14`: Operator agreed: exterior alerts today have ZERO member recognition (verified — perimeter_alert consults no face data). v1 direction = ANNOTATE not suppress ("Person detected — likely Oji") — preserves alert, kills operator cost; per-per...
  - `operator_answers_2026_08_14`: P1 privacy: LOCAL SOURCES ONLY (Frigate-2 + UniFi Protect face; llmvision EXCLUDED from identity — no household reference photos leave LAN). D3: FOLD IN NOW (stranger-alert / unknown-face leg builds in the same cycle as member-annotation...
  - `disposition_applied_2026_08_14`: OPERATOR DECLINED via board button 2026-08-13T03:20 (queue apply was MISSED for ~1 day — session-start disposition check skipped across overnight passes; corrected now). Reconciled NOT relitigated: declined AS A STANDALONE card; its scop...

### `CAM-AREA-PENDING` - Camera area corrections — RESOLVED
thread: **camera** - status: **done** - approval: **explicit**
_updated 2026-08-17 23:30_
- **Origin:** 2026-08-07 - found during the exterior+interior camera area-id correction sweep
- **Refs:** https://claude.ai/code/artifact/ef6dc227-8488-4b59-b745-f71e946da6a8
- **Forensic keys (1):**
  - `resolved`: Madrone G6 Entry -> front_porch (operator: front porch/entry; sits with front_door_aerial door overhead). DONE.

### `D3-AREA-INHERIT` - URA D3 fused sensor should inherit room area on creation
thread: **camera** - status: **done** - approval: **implied**
_updated 2026-08-17 23:55_
- **Origin:** 2026-08-07 - 5 rooms had roomless CameraPersonDetectedSensor - manual entity-area set was a band-aid
- **Why:** CameraPersonDetectedSensor (D3) does not set area_id from its room on creation, so new rooms silently ship roomless -> breaks resolver/transit room mapping. Durable fix so we do not hand-patch each new room.
- **Next:** set _attr area / registry area from room area on D3 sensor creation
- **Tags:** numbers-get-knobs
- **Parsimony:** [BUILD] per-room fused camera sensors ship with no area
- **Refs:** binary_sensor.py CameraPersonDetectedSensor
- **Forensic keys (1):**
  - `resolution_2026_08_17`: Operator ruling 2026-08-17: "The cards that are judgement calls, resolve as done." Proof was a process/latent-event judgment not observable in live state; operator closed.

### `F1-SUNSET` - Frigate-1 go/no-go
thread: **camera** - status: **done** - approval: **blocked**
- **Origin:** 2026-08-07 - Remind me when we can go on f1 sunset tmr
- **Why:** steps 1-6 remote (mine), step 7 = operator unplugs NUC; readiness = organic one-alert-per-multi-engine-traversal
- **Next:** operator go/no-go (reminder Aug 8)
- **Tags:** audit-first
- **Refs:** AUDIT_frigate1_sunset.md
- **Forensic keys (1):**
  - `closed_2026_08_16`: STALE (was blocked). Frigate-1 fully decommissioned 2026-08-15: entry deleted, 965 entities + 25 f1retired removed, F2 sole NVR, hardware repurposed by homelab agent. Go/no-go resolved months of soak ago.

### `v5.59.0` - resolver-legs
thread: **perimeter** - status: **done**
_updated 2026-08-17 23:30_
- **Origin:** 2026-08-07 - shipped + live-validated
- **Refs:** README_v5.59.0.md
- **Forensic keys (2):**
  - `note`: live PASS (zero multi-key WARN / _2 storm / URA ERROR; telemetry attr present)
  - `organic_open`: CLOSED 2026-08-07: leg_firing_by_camera POPULATED from real events (rear_ptz shows frigate+frigate2+protect on one camera; back_yard frigate+frigate2); today's exterior person-detects each = one alert per track, pass_by tracks alert_coun...

## ❓ Other (20)
_unknown status bucket_

### `MEMORY-ROADMAP-1` - Memory epic — forward roadmap + critique + what-survives
thread: **memory**
_created 2026-08-18 02:00 · updated 2026-08-18 02:35 · refined_
- **Next:** Delivered — operator to review the doc; drives roadmap rewrite / memory epic close-out.
- **Forensic keys (2):**
  - `column`: planned
  - `problem`: Memory epic shipped its first tranche (episodic writers D4-D7 v5.78.0 + nightly compactor). Operator wants a possible FORWARD roadmap for memory, a CRITIQUE of it, and a clear layout of which memory layers/artifacts SURVIVE (durability/r...

### `ROADMAP-UNDONE-REVIEW-1` - Review ROADMAP/VISION — surface undone-but-worthwhile
thread: **planning**
_created 2026-08-18 02:00 · updated 2026-08-18 02:35 · refined_
- **Next:** Delivered — operator to review the doc; drives roadmap rewrite / memory epic close-out.
- **Forensic keys (2):**
  - `column`: planned
  - `problem`: Roadmap is stale (ROADMAP-STALE-AGENTIC-LAYER-1: doc at v3.22.0 says Next=Bayesian v4.0.0 while live is v5.80.0). Operator wants a review of the roadmap surfacing what has NOT been done that is still worthwhile — separating genuinely val...

### `IOS-APP-PLAN-CARD-1` - iOS app for HAOS+URA — gated design blueprint (tracked)
thread: **dashboarding**
_created 2026-08-18 02:00 · updated 2026-08-18 02:25 · refined_
- **Next:** No action now (gated). When PWA M2 lands + install-gate met, promote M3 to planning.
- **Forensic keys (3):**
  - `column`: parked
  - `problem`: A real, detailed iOS app design EXISTS but was untracked. It is a BLUEPRINT, not a build: native iOS (SwiftUI + HAKit + TestFlight) is gated behind (a) PWA milestones M1/M2 and (b) the commercialization >=100-active-installs gate. Now ca...
  - `parked_reason`: GATED. Path: M1 PWA read-only -> M2 PWA writes+NM -> M3 SwiftUI native shell+HAKit+TestFlight -> M4 native writes+push. Native (M3/M4) blocked behind PWA M1/M2 + HACS distribution + >=100 installs. Revisit trigger: PWA M2 complete AND co...

### `EGRESS-IDENTITY-CONTROL-OBS-1` - Egress person-detection — enable/disable + observability (parsimony)
thread: **presence**
_created 2026-08-18 02:20 · updated 2026-08-18 02:25 · initial_
- **Next:** Folded into the in-flight D1 fix-up (builder a4d0f6ccc0e0eeb9d): add enable gate + observability attrs + kill-switch-inert test. Lands in the same Tier-2-DB re-review as the review fix-ups.
- **Forensic keys (3):**
  - `column`: shipped_organic
  - `problem`: The new egress person-identity detection (D1) must be operator-enableable/disableable, and its behavior must be observable — but with PARSIMONY (one control, minimal observability, no knob sprawl). It just surfaced a phantom-guest CRIT i...
  - `l1_validated_2026_08_18`: SHIPPED v5.81.0 + LIVE. L1 PASS (boot clean, zero URA ERROR; switch OFF/dormant byte-identical — egress_identities_stamped=0, census as v5.80.0; observability attrs egress_face_ids_active + egress_identities_stamped live on persons_enter...

### `SENSOR-HEALTH-SURFACING-1` - Sensor health surfacing — chatter detector + unhealthy-sensors + NM replace hook
thread: **diagnostics**
_created 2026-08-18 02:30 · initial_
- **Next:** Plan: chatter detector + ura_unhealthy_sensors sensor + sensor_health table + NM "replace this sensor" hook. Tier 2. Institutional-context grep first (chatter->0 files today).
- **Forensic keys (2):**
  - `column`: inbox
  - `problem`: URA detects stuck-ON sensors via a watchdog but has NO chatter/flapping detector and no surfaced "which sensor is unhealthy" signal. A live incident (INCIDENT_chatter_class_missed_by_watchdog_2026-08-09) already proved the gap. Cheapest ...

### `APPLIANCE-COST-DEFERRAL-1` - Appliance cost-deferral — LG ThinQ + Rainbird start-deferral/skip
thread: **energy**
_created 2026-08-18 02:30 · initial_
- **Next:** MARGINAL-BENEFIT DECOMPOSITION before speccing the full framework — how much does the simplest single-appliance deferral capture vs the whole v3 framework? Then Tier 2-DB if it clears.
- **Forensic keys (2):**
  - `column`: inbox
  - `problem`: No appliance_coordinator exists (thinq/rainbird->0 files). Deferring washer/dishwasher starts and skipping sprinkler runs to off-peak/solar windows is recurring-$ value but ~30-40h of work.

### `UNLOAD-SYMMETRY-TASK-HYGIENE-1` - Setup/unload symmetry + tracked background tasks (tech-debt hardening)
thread: **platform**
_created 2026-08-18 02:30 · initial_
- **Next:** Plan a Tier 2 hardening cycle: audit setup/unload symmetry across platforms + wrap background tasks in tracked/cancellable handles. Cross-ref parent-reload-watchdog hazard.
- **Forensic keys (2):**
  - `column`: inbox
  - `problem`: async_on_unload used in only 2 sites; untracked background tasks — both match known URA bug classes (reload-safety, task leak). One hardening cycle.

### `CONFIG-SUBENTRIES-MIGRATION-1` - Config subentries migration (flat 34-entry -> subentries)
thread: **platform**
_created 2026-08-18 02:30 · initial_
- **Next:** No action now (parked-with-trigger).
- **Forensic keys (3):**
  - `column`: parked
  - `problem`: Still flat 34 config entries; 189 hass.data[DOMAIN] sites. HA subentries would clean topology but the migration carries real risk for MEDIUM value.
  - `parked_reason`: MEDIUM value, real migration risk. Revisit trigger: when a config-topology change is needed anyway, or HA deprecates the flat pattern.

### `ENTITYDESC-RUNTIMEDATA-HYGIENE-1` - EntityDescription + runtime_data hygiene (opportunistic)
thread: **platform**
_created 2026-08-18 02:30 · initial_
- **Next:** Fold into the next platform/coordinator cycle that already edits the target files.
- **Forensic keys (3):**
  - `column`: parked
  - `problem`: EntityDescription + runtime_data patterns not adopted; low-value on its own.
  - `parked_reason`: Opportunistic — attach to the next coordinator touch rather than a dedicated cycle.

### `SUITE-ORDER-POLLUTION-1` - Presence tests fail order-dependently in large batches (suite hygiene)
thread: **platform**
_created 2026-08-18 03:00 · initial_
- **Next:** Bisect the batch to find the polluting file; add autouse snapshot/restore or fix the leak. Folds under UNLOAD-SYMMETRY-TASK-HYGIENE-1 suite-hygiene thread.
- **Forensic keys (2):**
  - `column`: inbox
  - `problem`: test_presence_coordinator + test_presence_guest_latch_and_veto_gap (D3 edge/zone-log tests) PASS in isolation but FAIL when run inside a large multi-file batch — order-dependent pollution from some other test file leaking module state. P...

### `CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1` - Promote 3 Camera-Census feature toggles to device switches
thread: **presence**
_created 2026-08-18 03:10 · updated 2026-08-18 09:40 · refined_
- **Next:** ura-planner: Tier 2 plan (3 SwitchEntity + persistence + options reconciliation + consumed by presence/transit/census). Then ONE plan review, then build.
- **Forensic keys (4):**
  - `column`: shipped_organic
  - `problem`: Three feature toggles are buried in the Camera Census options dialog (options-flow rung 2). Operator wants them as one-tap DEVICE SWITCHES on the URA device (rung 3) for live control + dashboard access. Names must be simple, benefit-firs...
  - `revised_2026_08_18`: PLAN-REVIEW (PLAN-NEEDS-FIXES, 1 CRIT) reshaped this. REVISED SCOPE: TWO switches only — Presence Face Matching + Name People at Doors. Smart People Counting (enhanced_census) STAYS in options (heaviest/structural at __init__.py:2253, no...
  - `shipped_2026_08_18`: SHIPPED v5.82.0 + LIVE. L1/L2/L4 PASS: both switches present+ON (defaults flipped), smart_people_counting correctly NOT a switch (404); L2 no-reload PROVEN live (untoggled sibling last_changed stable at boot across two toggles) + zero ER...

### `CENSUS-IDENTITY-GROUP-README-1` - Cycle-group README: census/guest/presence-identity program
thread: **planning**
_created 2026-08-18 03:20 · updated 2026-08-18 14:15 · initial_
- **Next:** general-purpose writing docs/readmes/README_GROUP_census_guest_presence_identity.md with verified entity inventory.
- **Forensic keys (3):**
  - `column`: done
  - `problem`: The census/guest/presence-identity arc (v5.79.0 guest correctness -> v5.80.0 census accuracy + dashboards -> v5.81.0 egress identity -> planned device switches -> gated D2) is coherent only in the operators head + scattered per-version R...
  - `done_note`: Delivered + reconciled to v5.82.0 (switches shipped). Sent to operator.

### `CENSUS-IDENTITY-SUPERSESSION-DELETE-1` - Delete superseded census/identity code (gated on L3 validation)
thread: **planning**
_created 2026-08-18 09:45 · updated 2026-08-18 10:35 · initial_
- **Next:** Tier-1 cleanup: grep-verify S1 zero readers -> delete CENSUS_DECAY_STEP_SECONDS; grep-sweep S7 legacy Frigate paths -> delete confirmed-dead sites. Both decidable now.
- **Forensic keys (4):**
  - `column`: done
  - `problem`: The census/identity arc superseded some code. Each delete-candidate has its OWN concrete, checkable gate (NOT a blanket "when validated fully"):
  - `parked_reason`: NOT gated on identity L3 (that was a spurious coupling). Each item gates on its OWN grep-check against ALREADY-shipped-and-validated cycles (v5.79.0/v5.80.0). Do the two greps (S1 zero-readers, S7 sweep) to DECIDE and delete — no Wed dep...
  - `closed_noop_2026_08_18`: CLOSED as NO-OP (correct outcome). Three-bucket triage: DELETE bucket EMPTY — no true dead-and-useless code in this cycle group. CENSUS_DECAY_STEP_SECONDS = bucket 3 (already documented retired-available in its tombstone comment, no edit...

### `PERIMETER-ALERT-NAME-PERSON-1` - Perimeter alerts should NAME the person (consume egress/face identity)
thread: **security**
_created 2026-08-18 09:45 · updated 2026-08-18 10:05 · initial_
- **Next:** Measure-before-build: probe the REAL egress identity rate against the GARAGE + family-room entry path (NOT the front door) and include Protect named face via the webhook, before scoping.
- **Forensic keys (3):**
  - `column`: inbox
  - `problem`: perimeter_alert.py:1316 still emits anonymous "Person Detected" even when identity is known — the exact known-vs-unknown discriminator this arc built. Highest signal-to-noise payoff of the gaps. Consume identity gracefully (name when kno...
  - `coverage_note_2026_08_18`: CORRECTION 2026-08-18 (operator): the ~7% figure is NOT a coverage ceiling and must not be cited as one. It came from PROBE_protect_face_egress.md which measured the WRONG camera (front door madrone_g6_entry). Most family entries are via...

### `GUEST-GATE-DOOR-IDENTITY-1` - Guest gate should consume door-identity (not just BLE room-location)
thread: **presence**
_created 2026-08-18 09:45 · updated 2026-08-18 10:05 · initial_
- **Next:** Measure-before-build: probe the REAL egress identity rate against the GARAGE + family-room entry path (NOT the front door) and include Protect named face via the webhook, before scoping.
- **Forensic keys (3):**
  - `column`: inbox
  - `problem`: _is_known_person_in_room relies solely on BLE room-location; a resident identified at the DOOR does not suppress a guest false-positive. Closest to the original census-double-count wound. Adjacent card EGRESS-INTERIOR-COUNT-REINFORCE-1 i...
  - `coverage_note_2026_08_18`: CORRECTION 2026-08-18 (operator): the ~7% figure is NOT a coverage ceiling and must not be cited as one. It came from PROBE_protect_face_egress.md which measured the WRONG camera (front door madrone_g6_entry). Most family entries are via...

### `ARRIVAL-DEPARTURE-NOTIFY-1` - "Oji arrived/left" notifications from egress person_id
thread: **notifications**
_created 2026-08-18 09:45 · updated 2026-08-18 10:05 · initial_
- **Next:** Measure-before-build: probe the REAL egress identity rate against the GARAGE + family-room entry path (NOT the front door) and include Protect named face via the webhook, before scoping.
- **Forensic keys (3):**
  - `column`: inbox
  - `problem`: person_id is on the bus + DB row but nothing turns it into a presence notification. Lowest-risk build of the gaps. Fires when identity is present (Frigate face + Protect named face via webhook).
  - `coverage_note_2026_08_18`: CORRECTION 2026-08-18 (operator): the ~7% figure is NOT a coverage ceiling and must not be cited as one. It came from PROBE_protect_face_egress.md which measured the WRONG camera (front door madrone_g6_entry). Most family entries are via...

### `PWA-CENSUS-P12-RELEASE-1` - PWA main is ~12 commits behind — D3 exterior card (+ design/control work) unshipped
thread: **dashboarding**
_created 2026-08-18 10:20 · initial_
- **Next:** OPERATOR: decide the PWA release — is census-p12 THE working branch to promote to main + deploy (ura.phalanxmadrone.com)? If yes, run the PWA release properly (its own review). The HA dashboard D3 cards (v6/v8) ARE live; only the PWA leg...
- **Forensic keys (2):**
  - `column`: waiting_operator
  - `problem`: The census D3 exterior KEEP-BOTH dashboard card lives on PWA branch census-p12-exterior-dashboard, which is ~12 commits AHEAD of main (main is stale). So the D3 card is NOT live on the PWA, and the branch also carries unrelated PWA work ...

### `CENSUS-FACE-RESOLVER-MIGRATE-1` - Route presence face-confirmed-arrival through the _2-suffix resolver (bucket-2 wire)
thread: **presence**
_created 2026-08-18 10:35 · initial_
- **Next:** Small Tier-1 hotfix: refactor presence.py:4557 to call camera_census._resolve_face_entity_id(base_name). Test the _2-only-cam case.
- **Forensic keys (2):**
  - `column`: inbox
  - `problem`: presence.py:4557 (_get_face_for_camera, live caller at :4525, v3.19.0 face-confirmed arrival) builds f"sensor.{base}_last_recognized_face" WITHOUT _2-suffix tolerance, so it silently misses cameras whose Frigate face sensor exists only a...

### `GUEST-COUNT-DEDUP-MIGRATE-1` - ZoneGuestCountSensor uses naive subtractive guest count — migrate to deduped union
thread: **presence**
_created 2026-08-18 11:00 · initial_
- **Next:** Verify ZoneGuestCountSensor live-status; then migrate _get_guest_count (+ binary_sensor.py:1584 sibling) to consume the deduped unidentified_count instead of the naive subtraction. Producer/consumer check both.
- **Forensic keys (2):**
  - `column`: inbox
  - `problem`: aggregation.py:5983 ZoneGuestCountSensor._get_guest_count derives guest count the NAIVE SUBTRACTIVE way (max(0, camera_total - ble_total)) — the SAME additive/subtractive formula behind the historical GUEST double-count. It is superseded...

### `SECURITY-CENSUS-UNKNOWN-WIRE-1` - Security unknown-person auto-lock is designed but UNWIRED to the census
thread: **security**
_created 2026-08-18 11:20 · initial_
- **Next:** Investigate-first: confirm the SanctionChecker intent contract + what a safe producer looks like (confidence-gated, kill-switched). Do NOT build a raw count->lock. Then Tier 2-DB plan.
- **Forensic keys (2):**
  - `column`: inbox
  - `problem`: security.py SanctionChecker has an unknown-person path (has_unknown_persons / _handle_census_intent -> locks ALL doors) that is a DESIGNED-BUT-INERT consumer: unknown_present has ZERO producers repo-wide, no source="census_update" intent...

## 🅿️ Parked ideas (top-level list)

- **Pre-roll frame buffer** - rising-edge frames look late for fast walkers
- **Anticipatory TOU tick** - boundary-lag data shows real cost
- **Adjacency config-flow (adjacency-as-data / TOU pattern)** - approved-queued (exterior-stragglers batch, seq 3)
- **Security config home** - a 2nd security-config surface would join the top menu

## Broader backlog references

- EV drain-precedence (queued)
- Load-shedding foundations (vision doc first)
- Fusion paper (gated)
- Shipwatch v1.2.0 deploy.sh hook
- Forecaster wire-up (LightGBM + BatteryStrategy)
- Dashboarding workstream (ura-v6 rebuild + PWA)
- Memory week-one gate + first coordinator-consumer proposal
