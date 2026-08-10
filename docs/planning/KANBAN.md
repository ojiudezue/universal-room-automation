# URA Kanban - generated view

> **GENERATED - do not hand-edit.** Source of truth is `docs/planning/kanban.data.yaml`. Regenerate via `python3 scripts/kanban_render.py`.

_Generated: 2026-08-08T14:16:28-05:00_ - _Data commit: `ec743438a770`_ - _last_reconciled: 2026-08-07_

**Hosted:** https://urakanban.phalanxmadrone.com
**Artifact:** https://claude.ai/code/artifact/5748808f-5f16-41e8-a455-c3c59ed40149

> ## ⚠️ STALE - board has not been reconciled against newer work
>
> - newest git tag v5.64.0 (2026-08-08) is newer than last_reconciled (2026-08-07)
> - newest README README_v5.64.0.md (2026-08-08) is newer than last_reconciled (2026-08-07)
>
> Reconcile the board (update `meta.last_reconciled` + move shipped cards) before using it to pick next work.

## Columns

| Column | Count |
|---|---:|
| 📥 Inbox | 0 |
| 🧭 Pre-planning | 14 |
| 📝 Planned | 1 |
| 🔨 In progress | 1 |
| 🔍 Review | 1 |
| 🚀 Shipped (organic open) | 5 |
| ⏸️ Waiting on operator | 2 |
| ⏳ Waiting on me (Claude) | 2 |
| 🅿️ Parked | 0 |
| ✅ Done | 0 |

## 📥 Inbox (0)
_raw capture_

_(none)_

## 🧭 Pre-planning (14)
_idea being decomposed_

### `TABLET-FLEET-1` - Wall tablet fleet: URA integration (sensors, wake-on-occupancy, room quick-actions)
thread: **tablets** - status: **pre_planning** - approval: **unreviewed**
- **Origin:** 2026-08-08 - operator: master tablet upgrades tested and working (sensors, lights, all over MQTT); thinking house-device tablet control, wake on URA room occupancy, conditional room quick-actions. NO ACTION YET - thoughts requested.
- **Next:** operator thoughts/ruling; then likely sequence = (1) consume tablet lux/temp/humidity in URA, (2) wake-on-occupancy with night dimming + per-room opt-in, (3) room-scoped dashboard quick-actions as bounded overrides
- **Tags:** institutional-context, measure-before-build, marginal-benefit
- **Forensic keys (3):**
  - `repo`: ~/Code/wall-tablet (HALedController, v1.3 versionCode 5, 2026-08-01)
  - `verified_capabilities`: Per-room MQTT identity already fleet-safe: clientId wall-tablet-<room>, topics home/wallpanel/<room>/{led,sensors,status}; LWT availability; self-registers via MQTT Discovery (no YAML).
  - `orchestrator_assessment`: HIGHEST VALUE IS THE SENSORS, NOT THE CONTROL SURFACE. Per-room lux is a first-class input URA's lighting logic already consumes; a tablet in every room is a lux+temp+humidity fleet arriving for free. That likely beats the quick-action U...

### `CIRCLING-SEVERITY-1` - A "circling" exterior person produced alert_count=0
thread: **perimeter** - status: **pre_planning** - approval: **unreviewed**
- **Origin:** 2026-08-08 - observed during v5.62.1 live validation
- **Why:** Live track xt-000001-695c9e: back_yard -> front_side_ptz -> back_yard -> front_side_ptz -> back_yard, classification=circling, 133s, alert_count=0 at 09:22 CDT. Track linking worked correctly (one track, not five alerts). But CIRCLING is...
- **Next:** trace why alert_count=0 for a circling classification; decide whether circling should escape pure clock-time gating
- **Tags:** no-fabrication-verify
- **Parsimony:** [BUILD] the most suspicious exterior behaviour may be silently unalerted outside night hours
- **Refs:** exterior_track_linker.py classification; perimeter_alert.py alert-hours gating; CONSOL-1 contextual-severity ruling

### `XCORR-1` - Burst-demotion for isolated single-camera night alerts (was: cross-engine corroboration gate)
thread: **perimeter** - status: **pre_planning** - approval: **explicit**
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
thread: **devices** - status: **pre_planning** - approval: **implied**
- **Origin:** 2026-08-08 - operator: why is the master bedroom dimmer coming on in the morning?
- **Why:** light.shellydimmer2_24d7ebe93470 (area master_bedroom) reboots repeatedly: 89 `unavailable` events since Aug 1, accelerating 6/day -> 23/day, each ~33s (consistent = full device reboot, not a variable WiFi blip). 32 of those reboots came...
- **Next:** set power-on-default OFF; then chase the reboot cause
- **Tags:** no-fabrication-verify
- **Forensic keys (3):**
  - `likely_causes`: Shelly power-on-default set to ON (or restore-last with stale value) -> every reboot turns the light on
  - `CORRECTION`: 2026-08-08: I FIRST REPORTED THIS AS A 117-130C FIRE RISK. THAT WAS WRONG — the sensor's unit_of_measurement is degF, not degC. 116.7F = 47C; peak 129.6F = 54C. That is NORMAL for a wall dimmer and inside the Shelly Dimmer 2 range. NO fi...
  - `fix`: PRIMARY: set the Shelly power-on default to OFF so a reboot cannot turn the light on (device setting, operator or API)

### `BOOTSANITY-1` - Boot-sanity allowlist guard cannot fire on a cold boot
thread: **camera** - status: **pre_planning** - approval: **implied**
- **Origin:** 2026-08-07 - found during v5.61.0 live validation — I nearly read its silence as proof of success
- **Why:** The F1(e) guard runs at the END of PerimeterAlertManager.async_setup() and is gated on `_linker_now` being present — but the linker registers AFTER that setup returns, which IS the bug. So on every cold boot it short-circuits and never w...
- **Next:** move the check into the READY handler; pin with a test that asserts the WARNING fires when install fails
- **Tags:** no-fabrication-verify, mutation-drill
- **Parsimony:** [BUILD] the tripwire for a CRITICAL class of bug is unreachable on the path that matters
- **Forensic keys (1):**
  - `fix`: re-run the sanity check from the READY handler AFTER the install attempt (and/or on a delayed post-boot check). Mutation drill: neuter the install -> the sanity WARNING must fire.

### `OVERRIDE-NOTIFY-1` - Warn before the Temp Arrester Override expires
thread: **hvac** - status: **pre_planning** - approval: **explicit**
- **Origin:** 2026-08-07 - "The only real optimization is getting a text that says your override is about to expire 5 mins before a boundary"
- **Why:** We built the release logic but never tell the operator it is coming — the override silently vanishes and the setpoint drifts back. A heads-up makes it usable: re-engage in one tap instead of noticing an hour later that the master went cold.
- **Next:** confirm the 3-part shape with operator, then build with the SNAP-1 batch or standalone
- **Tags:** numbers-get-knobs
- **Parsimony:** [BUILD] override releases silently; operator discovers it by feeling cold
- **Forensic keys (1):**
  - `design_note`: 5-min-ahead warning is only possible for PREDICTABLE expiries. House-state transitions are NOT scheduled - we cannot know home_evening is coming. So: (a) pre-warn the 6h decay at T-5min; (b) on a grace DEFERRAL, warn immediately ('contex...

### `TRANSIT-DIAG-1` - Expose checkpoint_cameras_by_area on a diagnostic sensor
thread: **presence** - status: **pre_planning** - approval: **implied**
- **Origin:** 2026-08-07 - operator: "Will you fix what the validation exposed?" - v5.60.0 live validation needed log-level surgery + a registry touch just to read the checkpoint inventory
- **Why:** checkpoint_cameras_by_area is a Python attribute only and URA logs at WARNING, so the feature is unobservable without raising log level and forcing a rebuild. Validation should not require surgery.
- **Next:** fold into the SECC-1 build batch
- **Tags:** numbers-get-knobs
- **Parsimony:** [BUILD] shipped feature is not observable live
- **Refs:** docs/readmes/README_v5.60.0.md live-validation method note
- **Forensic keys (1):**
  - `fix`: additive diagnostic sensor (or attrs on an existing presence diagnostic) exposing checkpoint_cameras_by_area + protect_sourced count. Read-only.

### `TEST-1` - Boot-time shadow diff (legacy vs resolver leg set)
thread: **resolver** - status: **pre_planning** - approval: **implied**
- **Origin:** 2026-08-07 - we took hardened surface and gave it new methods; something is bound to fail
- **Why:** live tripwire for silent coverage shrinkage that unit tests miss
- **Next:** WARN if a camera's new leg set doesn't superset legacy base+_2
- **Tags:** mutation-drill
- **Parsimony:** [BUILD] a camera's leg set silently shrank vs the retired helpers

### `TEST-2` - "Send Test Perimeter Alert" button
thread: **perimeter** - status: **pre_planning** - approval: **implied**
- **Origin:** 2026-08-07 - same push as TEST-1
- **Why:** delivery crosses into 3rd-party services; only a live end-to-end send proves it
- **Next:** button entity -> canned snapshot through all 4 channels
- **Tags:** numbers-get-knobs
- **Parsimony:** [BUILD] no way to prove channel delivery without waiting for a real intrusion

### `FRIG2SNAP-1` - frigate2 instance-id snapshot URL
thread: **camera** - status: **pre_planning** - approval: **implied**
- **Origin:** 2026-08-07 - found mid-investigation
- **Why:** endpoint is instance-scoped; URA builds only default shape -> frigate2-hosted cameras can't resolve a snapshot at all (latent since prefix-split)
- **Next:** fold into SNAP-1
- **Tags:** no-fabrication-verify
- **Parsimony:** [BUILD] any camera on the 2nd Frigate host has never had a snapshot

### `KP-ESCALATE-1` - Known-person / face-alert path (no URA successor)
thread: **security** - status: **pre_planning** - approval: **blocked**
- **Origin:** 2026-08-07 - discovered via purged Frigate_KnownPerson_* files + AUDIT rec 5
- **Why:** face-recognition paging has no URA successor; lost when the doorbell automation retires unless built into perimeter NM
- **Tags:** institutional-context, audit-first
- **Parsimony:** [BUILD] retiring the doorbell automation silently drops face-alert paging
- **Refs:** PLANNING_exterior_person_escalation.md

### `RELOAD-WATCHDOG-HAZARD` - URA parent-entry reload cascades → event-loop stall → watchdog (~5min outage)
thread: **lifecycle** - status: **pre_planning** - approval: **explicit**
- **Origin:** 2026-08-07 - options-flow submit (camera_person_entities) reloaded the URA parent entry and blipped HA -> diagnose and fix this autonomously tonight
- **Why:** routine options saves (Camera Census etc.) reload the integration/parent entry, which cascades to all ~40 room + coordinator entries synchronously, stalling the event loop until the supervisor watchdog restarts core (~5min outage). A con...
- **Next:** (tonight) build - INTEGRATION suppress set + SIGNAL_CAMERA_LIST_CHANGED re-subscribe path; Tier 2-DB (lifecycle + presence)
- **Tags:** tier-2db, no-fabrication-verify
- **Parsimony:** [BUILD] a routine config save causes a ~5min house outage
- **Refs:** __init__.py:5984 _async_update_listener; OPTIONS_RELOAD_SUPPRESS_KEYS; transit_validator.py async_init; feedback_parent_entry_reload_watchdog_hazard memory
- **Forensic keys (2):**
  - `diagnosis`: CONFIRMED (2026-08-07): _async_update_listener (__init__.py:5984) - for the INTEGRATION entry, if changed_keys NOT subset of OPTIONS_RELOAD_SUPPRESS_KEYS -> hass.config_entries.async_reload(entry.entry_id). Reloading the INTEGRATION (par...
  - `fix`: Add Camera Census keys to an INTEGRATION-entry suppress set (mirror the CM/ROOM reload-suppression). Persistence already done by async_update_entry.

### `KHOST-1` - Homelab-hosted board, generated from data
thread: **dashboarding** - status: **pre_planning** - approval: **explicit**
- **Origin:** 2026-08-07 - make url live on webhost (homelab)... design it better... give yourself eyes like playwright... build it tonight while I'm sleeping
- **Why:** the Artifact is hand-maintained HTML that can drift; a GENERATED board (pure function of this data) can't; homelab-hosted = durable, infra-native
- **Next:** (overnight) design data->view generator; screenshot-iterate; wire homelab serve + post-commit rebuild hook
- **Tags:** hand-build-fixture
- **Parsimony:** [BUILD] the reflected board is hand-maintained and can silently drift from the source
- **Forensic keys (2):**
  - `design`: source = this data file; generator -> {KANBAN.md view, html board, history}; page is a pure function of the data
  - `decisions`: host: urakanban.phalanxmadrone.com

### `D3-AREA-INHERIT` - URA D3 fused sensor should inherit room area on creation
thread: **camera** - status: **pre_planning** - approval: **implied**
- **Origin:** 2026-08-07 - 5 rooms had roomless CameraPersonDetectedSensor - manual entity-area set was a band-aid
- **Why:** CameraPersonDetectedSensor (D3) does not set area_id from its room on creation, so new rooms silently ship roomless -> breaks resolver/transit room mapping. Durable fix so we do not hand-patch each new room.
- **Next:** set _attr area / registry area from room area on D3 sensor creation
- **Tags:** numbers-get-knobs
- **Parsimony:** [BUILD] per-room fused camera sensors ship with no area
- **Refs:** binary_sensor.py CameraPersonDetectedSensor

## 📝 Planned (1)
_has plan / acceptance_

### `CONSOL-1` - Perimeter consolidation cycle
thread: **perimeter** - status: **planned** - approval: **explicit**
- **Origin:** 2026-08-07 - retire redundant manager surface; I need to weigh in — usability
- **Why:** three parallel alerting stacks (URA NM, HA doorbell automation, zone_monitoring pagers) duplicate delivery
- **Next:** fold SNAP-1 + TEST-1/2 in; Tier 2-DB
- **Tags:** tier-2db, institutional-context, audit-first
- **Parsimony:** [BUILD] 3 stacks page the same event with no shared cooldown/routing
- **Refs:** PLANNING_perimeter_consolidation.md; AUDIT_ha_side_alerting_reconciliation.md
- **Forensic keys (1):**
  - `rulings`: Option C surfacing (= A enhanced)

## 🔨 In progress (1)
_being built_

### `RESACC-1` - Resolver accuracy test suite
thread: **resolver** - status: **in_progress** - approval: **implied**
- **Origin:** 2026-08-07 - much more interested in accuracy of the task of the resolver; accuracy means alerting will be better
- **Why:** the resolver feeds census + transit + perimeter; one accuracy suite validates all three
- **Next:** hand-build ground-truth from live registry, commit as fixture, then build the diff
- **Tags:** hand-build-fixture, measure-before-build, no-fabrication-verify
- **Parsimony:** [BUILD] resolver mis-maps a camera silently -> wrong alerts/room across 3 consumers
- **Forensic keys (3):**
  - `progress`: 2026-08-07: hand-built ground-truth fixture from live registry (86 detection sensors, 20 multi-engine cameras) -> AUDIT_resolver_ground_truth_manual.md
  - `findings`: A-1 (CORRECTED per operator): armcrest (pool overhead: F2 frigate + dahua) and armcrestash41b (interior Study-A, F1) are DIFFERENT cameras. Precision hazard, NOT a recall gap - the accuracy test must assert they do NOT fuse. armcrestash4...
  - `design`: hand-built ground-truth table (camera -> {sensor x engine x family, room}); precision/recall per camera

## 🔍 Review (1)
_under review_

### `SNAP-1` - Snapshot mirror-and-improve
thread: **perimeter** - status: **review** - approval: **explicit**
- **Origin:** 2026-08-07 - still no images -> Mirror and improve -> does it cleanup? -> I approve the purge
- **Why:** URA sends media_url (URL fetch) so images drop; any live grab is stale
- **Next:** decisions RESOLVED - ready to build standalone (Tier 2-DB) after TRANSIT-1 fix-up + SECC-1
- **Tags:** tier-2db, numbers-get-knobs, no-fabrication-verify
- **Parsimony:** [BUILD] perimeter alerts arrive with no photo / a stale photo
- **Refs:** perimeter_alert.py; domain_coordinators/notification_manager.py
- **Forensic keys (5):**
  - `design`: mirror = snapshot to local file, attach as file to every channel (media_path / attachment / image)
  - `decisions`: snapshot_dir: /media/ura/snapshots — operator: 'whatever is best practice'. VERIFIED convention: llmvision already uses /media/llmvision/snapshots. /media is HA's auth-gated media dir (media browser), NOT the anonymous web-served /local//config/www — ...
  - `build`: build/snap-at-detection @ 7e28a2ea4 — 15 new tests, 6 detach-the-value drills all RED, gate 21/8405 name-diff 0
  - `verification_results`: VERIFIED: frigate2 instance-scoped snapshot URL — instance id = MQTT client_id from hass.data['frigate'][entry_id]['config']['mqtt']['client_id']; discovery tries each instance. Live: Frigate 1 (192.168.13.16:8971) + Frigate 2 (192.168.1...
  - `followups`: SNAP-1-followup-protect-thumb — REOPENED: Protect IS installed (core integration); verify the smart-detect thumbnail API against HA core unifiprotect and implement the middle precedence tier

## 🚀 Shipped (organic open) (5)
_live, awaiting proof_

### `ARREST-SUNSET-1` - Temp Arrester Override does not sunset on away/vacation (only sleep)
thread: **hvac** - status: **shipped_organic** - approval: **implied**
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

### `TRANSIT-1` - Interior traversal — Protect-sourced checkpoints via resolver
thread: **presence** - status: **shipped_organic** - approval: **explicit**
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

### `SECC-1` - Interior cams in the exterior open-tracks diagnostic
thread: **security** - status: **shipped_organic** - approval: **explicit**
- **Origin:** 2026-08-07 - Saw the outside open tracks diagnostic in SecC has interior cameras in it. Mistake? - dropped for hours, recovered via the board
- **Why:** the exterior diagnostic should reflect perimeter/egress cams only; interior cams there = display leak or observe-scope leak past the allowlist
- **Next:** build the allowlist fix (small); Tier 1/2
- **Tags:** no-fabrication-verify
- **Parsimony:** [BUILD] interior cameras surface in the exterior open-tracks diagnostic
- **Refs:** exterior_track_linker.py; sensor.py
- **Forensic keys (6):**
  - `finding`: CONFIRMED live 2026-08-07: exterior open-tracks diagnostic has OPEN TRACKS for interior cams (armcrestash41b=Study-A, playroom=game room) + unlinked_events for master_hallway/upstairs_hall/playroom. ignored_offlist_events EMPTY -> allowl...
  - `fix`: restrict linker allowed_cameras (set_allowed_cameras) to perimeter/egress only; observe() must drop off-list cams into ignored_offlist_events. Verify why interior cams are on the allowlist.
  - `finding_ROOT_CAUSE_CORRECTED`: VERIFIED 2026-08-07 (Review A CRIT-A1, orchestrator-confirmed): the allowlist has NEVER been installed on any boot. set_allowed_cameras has exactly ONE caller (perimeter_alert.py:385) inside PerimeterAlertManager.async_setup(), guarded b...
  - `fix_REVISED`: MUST make the install actually happen: either subscribe PerimeterAlertManager to SIGNAL_EXTERIOR_LINKER_READY and install there, or reorder __init__ (linker before perimeter_alert), or re-run the install after linker registration.
  - `bug_class`: #33 coordinator-setup ORDERING - hass.data sibling lookup inside async_setup with no READY-signal fallback; the guard silently no-ops
  - `organic_open`: CLOSED 2026-08-08 09:22 via v5.62.1: allowlist_installed=true, allowlist_camera_count=12 (matches the 12 staged+discarded cameras), and ignored_offlist_events={'garage_b':2} proves the gate is ENFORCING (was an empty dict for the entire ...

### `CAM-AREA-PENDING` - Camera area corrections — RESOLVED
thread: **camera** - status: **shipped_organic** - approval: **explicit**
- **Origin:** 2026-08-07 - found during the exterior+interior camera area-id correction sweep
- **Refs:** https://claude.ai/code/artifact/ef6dc227-8488-4b59-b745-f71e946da6a8
- **Forensic keys (1):**
  - `resolved`: Madrone G6 Entry -> front_porch (operator: front porch/entry; sits with front_door_aerial door overhead). DONE.

### `v5.59.0` - resolver-legs
thread: **perimeter** - status: **shipped_organic**
- **Origin:** 2026-08-07 - shipped + live-validated
- **Refs:** README_v5.59.0.md
- **Forensic keys (2):**
  - `note`: live PASS (zero multi-key WARN / _2 storm / URA ERROR; telemetry attr present)
  - `organic_open`: CLOSED 2026-08-07: leg_firing_by_camera POPULATED from real events (rear_ptz shows frigate+frigate2+protect on one camera; back_yard frigate+frigate2); today's exterior person-detects each = one alert per track, pass_by tracks alert_coun...

## ⏸️ Waiting on operator (2)
_needs a human call_

### `F1-SUNSET` - Frigate-1 go/no-go
thread: **camera** - status: **waiting_operator** - approval: **blocked**
- **Origin:** 2026-08-07 - Remind me when we can go on f1 sunset tmr
- **Why:** steps 1-6 remote (mine), step 7 = operator unplugs NUC; readiness = organic one-alert-per-multi-engine-traversal
- **Next:** operator go/no-go (reminder Aug 8)
- **Tags:** audit-first
- **Refs:** AUDIT_frigate1_sunset.md

### `PHYS` - Physical operator actions
thread: **ops** - status: **waiting_operator** - approval: **blocked**
- **Why:** hardware only the operator can touch
- **Forensic keys (1):**
  - `items`: Envoy power-cycle (daily reserve wedge, self-heals but recurs)

## ⏳ Waiting on me (Claude) (2)
_I owe something_

### `P1P3` - Preset verdict (flap re-measurement)
thread: **hvac** - status: **waiting_me** - approval: **explicit**
- **Origin:** 2026-08-07 - Yes re evaluate and come back
- **Why:** I owe the post-Writer-B flap re-measurement across occupied evenings, then the re-eval
- **Next:** pull flap numbers across occupied evenings, then re-eval P1/P3
- **Parsimony:** [BUILD] did removing Writer-B actually stop the preset flap - and do P1/P3 now earn their keep
- **Forensic keys (1):**
  - `note`: was mis-filed under the operator's lane - it is MY debt

### `SWEEP` - Morning sweep
thread: **ops** - status: **waiting_me** - approval: **implied**
- **Why:** reason-ledger first night, Frigate car/dog/cat first events, snapshot-fix organic proof, v5.57/58 organic criteria
- **Next:** check + report each

## 🅿️ Parked (0)
_revisit-trigger set_

_(none)_

## ✅ Done (0)
_closed, evidence in refs_

_(none)_

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
