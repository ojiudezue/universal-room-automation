# AUDIT: arc-close sweep, identity / vision / census (2026-11-19)

Author ura-planner. Read-only on code and HA. Inputs: `ARC_identity_vision_census_map.md` §1, §4, §4a (refreshed
2026-11-19); the charter in `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`; every open card in batch
`person-sightings` plus the named arc siblings in `kanban.data.yaml`; `PLANNING_layer_leak_cleanup.md` (the 11-17
re-cut); live HA states; URA DB `memory_episodes` over ssh (read-only). Rules applied: "Only proven code should
supersede correct code" and "I don't want to worry and derail from low probability concerns". Board not edited.

Not a presence or HVAC design change; no claim here rests on the presence or HVAC state-of-play docs. The two cards
that touch HVAC/presence code (ROOM-OCCUPIED, BLE-ARRIVAL) are dispositioned from code reads only; their builder reads
those docs in full.

## 1. Evidence gathered this sweep

- **Door vision since v5.108.36 (pipeline_version 3, from 2026-11-17 13:17):** 55 `ok` + 1 `blank` crossing rows on the
  `recording_window` route (8 frames). Blank rate 1/56 (1.8 %) vs 4/66 (6 %) on the old evenly spaced route since 11-10.
  Where `camera_peak_count` is stamped (24 rows): peak 1 → vision 1 (20/20); peak 2 → vision 2 (2/4), vision 1 (2/4).
  **No crossing with a camera peak of 3 or more has occurred since 11-17**, so the card's headline case (groups of 3+)
  cannot be scored yet.
- **Registry guard:** `test/registry-not-names-guard` (ea777fa46, 2026-11-15) is not on develop; only the
  person-awareness layer guard is (`quality/tests/test_person_awareness_layer_guard.py`).
- **L4 build:** branch `feature/layer-l4-veto-miss-path` (locked worktree) holds no commits beyond develop merges; D1
  not started.
- **Room occupied slug builds still live:** `domain_coordinators/hvac_fans.py:1726` and `:2035` read
  `f"binary_sensor.{slug}_occupied"`.
- **BLE arrival producer still gated by HVAC:** `person_coordinator.py:1199` `if self._pre_arrival_enabled:`; live
  `switch.ura_hvac_coordinator_pre_arrival_conditioning` = `on`, so the defect is latent today.
- **Circling titles:** CIRCLING-LABEL-1 (ordering + exemption ledger) is merged; option A (own NM title for
  escalation-exemption dispatches) is not in `perimeter_alert.py`.
- **Interior path map:** `/config/universal_room_automation/interior_paths.json` installed; read by
  `transit_validator.py:2813-2826` and `interior_vision.py`.
- `update.universal_room_automation_update` installed = v5.108.37.

## 2. Verdict table

| Card | Verdict | Evidence / next |
|---|---|---|
| LOCK-UNCOUNTED-RETURN-ARM-REDUNDANT-1 | DONE | closed on board 2026-11-18 |
| CROSSING-GRADING-PAGE-1 | DONE | page live; 56 grades pulled and scored 11-18 (§4a row 6). Names-batch grading continues under row 6, not this card |
| VISION-AMBIGUOUS-CROSSINGS-1 | DONE (met with residual) | P3-D2/P3-D3 shipped v5.108.36, README live validation PASS (c72cb3e8e). Residual P3-D6 bar (unmet) and P3-D11 live on the umbrella VISION-CROSSING-ANALYSIS-1; P3-D10 NO-GO recorded |
| FACE-ARRIVAL-REBUILD-1 | DONE (umbrella) | Phase 1 D0-D7 shipped from v5.108.16; D8 shipped as step 7 S1 (v5.108.37). Remaining validation lives on EGRESS-DIRECTION-AWARE-IDENTITY-1 |
| INTERIOR-PATH-MAP-1 | DONE | file installed and consumed (above); soak-exit disposition overdue per arc map |
| PERSON-AWARENESS-READ-API-1 | DONE | ships 1/3a/3b live since v5.108.24/.25; every consumer since 11-14 builds on it (§4a row 8) |
| PHONE-LEFT-BEHIND-CAMERA-LEG-1 | DONE | deployed v5.108.21 |
| HOUSE-STATE-FIRST-PRINCIPLES-1 | DONE | 1a deployed v5.108.19; 1b has its own parked card |
| LOCK-RELEASE-ON-ARRIVING-BODY-EVIDENCE-1 | DONE | v5.108.18 README with validation |
| DEAD-CAMERA-DEVICE-RULE-1 | DONE | layer ship 3b, v5.108.25 README with validation |
| PERIMETER-GLOBAL-EGRESS-MUTE-1 | DONE | v5.108.22 README with validation (discriminator not re-queried here) |
| BLE-PERSON-SENSOR-REGISTRY-RESOLVE-1 | DONE | v5.108.22; branch merged to develop |
| PERSON-ID-INLINE-SWEEP-1 | SUPERSEDED | by LAYER-LEAK-CLEANUP-1 D1 (the five fail-open veto sites); the other four inline builds are parked there with trigger "person-id rule replaced by a registry resolver" |
| DEPARTURE-ACTIONS-1 | SUPERSEDED (in part) | step 8 departure pause shipped v5.108.33. Other departure actions: PARK until the operator names one |
| CENSUS-DECONFLICTION-LEDGER-1 | BLOCKED-ON-OPERATOR | pick A (anchor ignores held inputs) or B (held inputs block the anchor). Also §4a row 7 Q-F1..Q-F4 |
| EGRESS-OUTCOME-WEEKLY-LABEL-1 | BLOCKED-ON-OPERATOR | was Jaya's phone with her all day 11-11; do Ojini and Ziri carry phones with trackers |
| LLMVISION-CANCEL-CLEANUP-UPSTREAM-1 | BLOCKED-ON-OPERATOR | approve posting `DRAFT_llmvision_timeout_leak_upstream_issue.md` (you post, or I post) |
| PERSON-PROFILE-PREFERENCES-1 | BLOCKED-ON-OPERATOR | fill the People profile; run the live 5-min MA test that sets the ownership rule; then v6.0.0 (§4a row 3). Card `next` text is stale (says review C running) |
| DOOR-VISION-GROUP-UNDERCOUNT-1 | BLOCKED-ON-DATA | fix shipped (P3-D2 crossing-centred 8 frames); false blanks fell 6 % → 1.8 %. Cannot close: zero 3+ crossings since 11-17, and pairs still undercount 2 of 4. Close when ≥3 crossings with camera peak ≥ 3 are scored (or fold into the row 6 re-score due 11-20 18:00) |
| EGRESS-TRACKER-DIRECTION-1 | BLOCKED-ON-DATA | tracker 23/36 on the 56-grade re-score; plan waits on the names-batch score (§4a row 6, due 11-20) |
| VISION-CROSSING-ANALYSIS-1 | BLOCKED-ON-DATA | umbrella; next is the row 6 re-score, then the P3 list |
| EGRESS-DIRECTION-AWARE-IDENTITY-1 | BLOCKED-ON-DATA | v5.108.37 installed; post-restart live validation and the 5 S1 candidates to grade (§4a row 5); set the pairs option |
| VISION-INTERIOR-SIGHTINGS-1 | BLOCKED-ON-DATA | ships 1-2 live; criterion 1/7 PASS; criterion 2 needs a non-operator describe (§4a row 2) |
| LAYER-LEAK-CLEANUP-1 | READY | D1 L4-min (five veto sites + H1 guard case). Tier 2, ~1 builder-day. Already §4a row 8 |
| REGISTRY-NOT-NAMES-1 | READY | guard branch ea777fa46 has sat unmerged since 11-15: rebase, one review, merge. Tier 1 (test-only), ~0.5 day. Children stay in audit §8 order |
| ROOM-OCCUPIED-ENTITY-REGISTRY-RESOLVE-1 | READY | slug builds still at `hvac_fans.py:1726, 2035`; 11 of 47 rooms fail open on the fan-off-while-occupied guard. Tier 2-DB (HVAC reader), ~1-1.5 days; builder reads HVAC state of play |
| PERIMETER-CIRCLING-HOP-SEVERITY-COLLIDE-1 | READY | option A (own title for escalation-exemption dispatches) defaulted on no veto; not built. Tier 2, ~0.5-1 day, `perimeter_alert.py` only, test uses the real NM `_is_deduplicated` |
| G6-ONE-BLE-ROOM-READ-1 | PARK | = L1 behaviour, parked 11-17 (PLB `on` 10 min/7 d). Trigger: a PLB `on` > 2 h in a week, a room hold traced to a PLB-on person, or a second occupancy consumer of `persons_in_room` |
| PRESENCE-BOOT-SEED-FROM-VIEW-1 | PARK | = L3-H1, 0 false boot AWAYs in 27 restarts. Guard case rides D1. Trigger: identified-persons derivation changes, or a boot AWAY with a resident `home` |
| BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 | PARK | latent: pre-arrival switch is `on`. Trigger: the switch is turned off, or step 8 BLE arrival music needs it at v6.0.0 (operator approved option A earlier; revive then, Tier 2, ~0.5 day) |
| PHONE-LEFT-BEHIND-TRANSIENT-FLICKER-1 | PARK | 17 one-poll flickers in 8 days, none real, no action traced to one. Trigger: a flicker coincides with a house-state change or an AWAY decision |
| NVR-WITNESS-CONSOLIDATION-1 | PARK | §4a parked list: W2 only before the interior D4 census flip. Trigger: that flip is scheduled |
| CENSUS-DOOR-TALLY-ATTRIBUTION-PARKED-1 | PARK | unchanged; revisit at the bar disposition |

Already-parked lock / house cards (HOUSE-STATE-VACATION-OVERLAY-1B, LOCK-REGIME-BOOT-REALLY-AWAY-1,
LOCK-BOOT-LOCKOUT-UNAVAILABLE-AT-SETUP-1, LOCK-VACATION-PHANTOM-SLEEP-DAILY-UNLOCK-1, DUAL-LENS-PACKAGE-CHANNEL-MEMBERSHIP-1,
DEAD-CAMERA-TWIN-COVERAGE-1, HA-FOYER-CAMERA-AREA-ALIGN-1): keep parked, triggers unchanged.

**Counts:** DONE 12 · SUPERSEDED 2 · BLOCKED-ON-OPERATOR 4 · BLOCKED-ON-DATA 5 · READY 4 · PARK 6 (+7 kept parked).

## 3. Finish order for READY (does not displace §4a)

§4a rows 2-7 are operator/data-gated; row 8 is the only builder row. Order, one builder slot at a time:

1. **LAYER-LEAK-CLEANUP-1 D1** — §4a row 8 itself.
2. **REGISTRY-NOT-NAMES-1 guard merge** — test-only; land right after D1 so D1's allowlist change and the registry
   allowlist ratchet together once.
3. **ROOM-OCCUPIED-ENTITY-REGISTRY-RESOLVE-1** — the first registry child; a real fail-open on 11 rooms. Tier 2-DB.
4. **PERIMETER-CIRCLING-HOP-SEVERITY-COLLIDE-1 option A** — smallest, lowest value; any free slot.

Items 2-4 are side work under the §4a rule: they run only at a free builder slot while rows 2-7 wait on the operator
or data, and yield to any §4a row that unblocks.
