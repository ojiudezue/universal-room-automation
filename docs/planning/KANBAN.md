# URA Kanban - generated view

> **GENERATED - do not hand-edit.** Source of truth is `docs/planning/kanban.data.yaml`. Regenerate via `python3 scripts/kanban_render.py`.

_Generated: 2026-08-14T02:28:04-05:00_ - _Data commit: `35de5621ae32`_ - _last_reconciled: 2026-08-14_

**Hosted:** https://urakanban.phalanxmadrone.com
**Artifact:** https://claude.ai/code/artifact/5748808f-5f16-41e8-a455-c3c59ed40149

## Columns

| Column | Count |
|---|---:|
| 📥 Inbox | 2 |
| 🧭 Pre-planning | 10 |
| 📝 Planned | 1 |
| 🔨 In progress | 2 |
| 🔍 Review | 0 |
| 🚀 Shipped (organic open) | 29 |
| ⏸️ Waiting on operator | 2 |
| ⏳ Waiting on me (Claude) | 1 |
| 🅿️ Parked | 1 |
| ✅ Done | 0 |
| ❓ Other | 1 |

## 📥 Inbox (2)
_raw capture_

### `EVCARD-1` - EV charging detail card for the URA v8 Energy tab
thread: **dashboarding** - status: **inbox** - approval: **explicit**
- **Origin:** 2026-08-09 - "add an EV charging detail card to the Ura v8 energy tab. Style well. Detail cards are a bit sensor words vomit. Best judgement because of space though."
- **Why:** EV charging is a first-class energy behaviour (drain precedence, must-start-by, TOU exposure) with no dedicated surface on the v8 energy tab.
- **Next:** APPLIED LIVE 2026-08-09 to ura-v8 Energy & EV tab (views[2].sections[8], right after Battery Strategy Detail). write_committed + post_write_verified; template render verified separately. AWAITING OPERATOR REVIEW for refinement — operator...
- **Forensic keys (9):**
  - `applied_render_2026_08_09`: ## ⏸ Paused / TOU peak/mid-peak pause / [Garage A yes|Paused|0.0 kW] [Garage B —|Off|0.0 kW] [Outlets (2) —|TOU peak/mid-peak pause|—] / **Plan:** Hold Only · held 53h — 7 lines, zero None/unavailable/unknown, all four conditional lines ...
  - `fix_2026_08_09_held_label`: Operator: "What does held 53h mean?" — it was WRONG. Verified in source: since is stamped on every DP state transition (energy_drain_precedence.py:265) and HOLD_ONLY CLEARS hold_started_at as a "clean reversion" (:269-274); DPState docst...
  - `ARRESTER_TILE_2026_08_10`: Operator aside: temp override arrester onto the ura-v8 HVAC (Climate) tab for quick access. DONE — new section at climate view position 1 (right under the hero, above the thermostats): heading w/ live state badge + full-width toggle tile...
  - `MULT_SPLIT_APPROVED_2026_08_10`: Operator: "Clean break. Timing is fine." — BLE_CHAIN_HOLD_ENABLED (bool kill switch) + separately named D2 staleness multiplier; NO deprecated alias (single-user no-backcompat). Rides the P24/D3/dropdown batch.
  - `refinement_candidates`: REDUNDANCY: the headline reason and the Outlets row currently show the same string twice ("TOU peak/mid-peak pause") because the outlets are the only endpoints holding a reason. Options: drop the reason from the endpoint row, or drop it ...
  - `bug_caught_pre_ship`: The markdown card auto-detects entities from LITERAL entity IDs in the template. This template reaches them through Jinja VARIABLES (states(s)), so auto-detection would have missed them and the card would never re-render on state change ...
  - `design_notes`: Anti-word-vomit rules applied: (1) narrative first — pause_reason_human leads, and nothing on the dashboard consumed that attribute before; (2) CONDITIONAL rendering — must_start_by, force_charge_until, excess-solar and fill-target only ...
  - `followup_candidate`: retrofit conditional rendering to the Battery Strategy Detail card (same section group, same defect, ~30 min) — only if the operator endorses this card's style
  - `DEDUPE_2026_08_09`: Sweep: dashboarding thread has the PWA + KHOST-1 (kanban board, different surface); EV drain-precedence card is queued BACKLOG work about behaviour not display. No existing card covers a v8 energy-tab EV surface. NEW.

### `PATH-ALPHA-DENOM-1` - Path-alpha away inference structurally dead when all trackers LOST/STALE — trusted denominator empties; NO existing card fixes it
thread: **presence** - status: **inbox** - approval: **approved_after_investigation**
- **Origin:** 2026-08-13 - Carded-coverage grading: the LOST-denominator gap (all 4 trackers LOST -> all_tracked_persons_away false-by-vacuity for hours) is owned by no card; v5.16.0 fixed the veto denominator, not this.
- **Why:** Path-alpha ignores zones entirely — with ACTIVE trackers it would have fired regardless of the fan latch. Fixing the vacuous-denominator case (all-LOST + all-entity-away => away-eligible) is an independent mitigation with its own balance...
- **Next:** GATED on ZONE-TIER-DIVERGE-1 trace completing (same code region). Then: consumer enumeration of tracking_status (greps, all tiers) -> plan for decomposition path (1) with (2) as fallback if ripple too wide; Tier 2-DB minimum (trust-hiera...
- **Forensic keys (2):**
  - `operator_direction_2026_08_13`: Operator: "we should find a way to say AWAY not LOST. Do we need a lost state at all? That way we can actually use this signal the way it is supposed to be used. And not overload it." I.e. the fix may not be patching the denominator arit...
  - `alternate_paths`: (1) Dissolve LOST: away-with-no-fix => AWAY (trusted, counts in denominator); home-but-silent => new BLE_SILENT_HOME or stays ambiguous-excluded; keep LOST only for truly-unknown. Ripple: every consumer of tracking_status (H3 reliable-si...

## 🧭 Pre-planning (10)
_idea being decomposed_

### `ROOM-NAME-UNIQUE-1` - Room rename has no name-uniqueness guard — collision collapses name-keyed maps (two rooms fold into one occupancy bucket)
thread: **presence** - status: **pre_planning** - approval: **unreviewed**
- **Origin:** 2026-08-14 - ROOM-NAME-DESYNC-1 Review C adversarial find (D-MED-1): rename Room A to an existing Room B name — zero validation; _room_to_zone dict + ZonePresenceTracker.room_names + substrate bucket keys all name-keyed -> silent overwri...
- **Why:** Join-key uniqueness is an unenforced invariant every name-keyed tier map depends on.
- **Next:** Small cycle after v5.75.0; consider folding into the next config-flow-touching batch.
- **Forensic keys (1):**
  - `fix_sketch`: _check_room_name_unique in async_step_basic_setup -> async_show_form error on collision (~15 LoC, Tier 1-2). Live-validation D-block for the rename cycle includes a do-not-rename-to-existing sanity note meanwhile.

### `SENSOR-FANINDEP-1` - Role matrix needs a fan-independence axis — 10GHz motion-mmWave fleet is corroborator-grade for stuck but NOT for fan-demotion
thread: **presence** - status: **pre_planning** - approval: **unreviewed**
- **Origin:** 2026-08-14 - operator: the Hobeian "Millimeter wave motion detection" units (~20, transit areas) are 10GHz functional-PIRs (still-blind, long range). Registry confirms 3 Hobeian classes. But the Upstairs Guestroom unit of this EXACT mode...
- **Why:** STUCK-SENSOR-1 (v5.75.0) role layer accepts list-derived motion kind as corroborator — correct for non-fan stuck pathology, fails-agree (=status quo, no regression) under fan latch. The deferred D5 role-migration should add fan-independe...
- **Next:** Fold into the STUCK-D2-DEMOTION-ROLE-MIGRATE-1 follow-up (D5); probe result first.
- **Forensic keys (1):**
  - `measurement_first`: Passive recorder probe queued: does the NEW Living Room 10GHz unit latch the tower fan on its next run? (Placement/sensitivity may differ from Guestroom.) Result gates how urgent the axis is.

### `TABLET-FLEET-1` - Wall tablet fleet: URA integration (sensors, wake-on-occupancy, room quick-actions)
thread: **tablets** - status: **pre_planning** - approval: **unreviewed**
- **Origin:** 2026-08-08 - operator: master tablet upgrades tested and working (sensors, lights, all over MQTT); thinking house-device tablet control, wake on URA room occupancy, conditional room quick-actions. NO ACTION YET - thoughts requested.
- **Next:** operator thoughts/ruling; then likely sequence = (1) consume tablet lux/temp/humidity in URA, (2) wake-on-occupancy with night dimming + per-room opt-in, (3) room-scoped dashboard quick-actions as bounded overrides
- **Tags:** institutional-context, measure-before-build, marginal-benefit
- **Forensic keys (3):**
  - `repo`: ~/Code/wall-tablet (HALedController, v1.3 versionCode 5, 2026-08-01)
  - `verified_capabilities`: Per-room MQTT identity already fleet-safe: clientId wall-tablet-<room>, topics home/wallpanel/<room>/{led,sensors,status}; LWT availability; self-registers via MQTT Discovery (no YAML).
  - `orchestrator_assessment`: HIGHEST VALUE IS THE SENSORS, NOT THE CONTROL SURFACE. Per-room lux is a first-class input URA's lighting logic already consumes; a tablet in every room is a lux+temp+humidity fleet arriving for free. That likely beats the quick-action U...

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
> **⚡ OPERATOR: declined — pending apply** (at 2026-08-13T03:20:00.530Z)
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

## 📝 Planned (1)
_has plan / acceptance_

### `GUEST-FP-RESIDUALS-1` - Guest-FP audit residuals — path-alpha diagnostic classifier (A1, ~5 LoC) + camera-census outdoor filter (B1, latent)
thread: **presence** - status: **planned** - approval: **unreviewed**
- **Origin:** 2026-08-13 - AUDIT_guest_fp_fixes_wiring.md: core fixes SHIPPED + Outside zone correctly flagged outdoor; two residuals worth small fixes.
- **Why:** A1: path-alpha excluded_persons/tracked_persons_count_trusted still exclude LOST-away persons (diagnostic clarity only — guest gate does not read them). B1: camera-census has no room->outdoor filter; safe today (Patio has no camera perso...
- **Next:** Fold A1+B1 into the next presence hotfix batch; await operator answer on the 50-episode pattern.
- **Forensic keys (1):**
  - `operator_question`: 50 guest ENTRY episodes since 07-13 (1-7/day, daytime, flappy) — real summer guests or a daytime FP flavor? If the latter, escalate per audit §3.

## 🔨 In progress (2)
_being built_

### `FRIGATE-RETIRE-1` - Retire Frigate-1 — promote Frigate-2 (yolov9t/OpenVINO, zero night ghosts) to primary incl. snapshot engine
thread: **security** - status: **in_progress** - approval: **approved**
- **Origin:** 2026-08-12 - operator: "We should just retire frigate 1 instead of writing more code" + "Frigate 2 is our identical backup. We should move snapshots to it" + "Go".
- **Why:** Probe: 100% of night person alerts = frigate-1 single-witness sub-2s IR ghosts; frigate-1 thresholds already raised once (07-30 snapshot) and ghosting persists. Frigate-2 runs a DIFFERENT detector (custom yolov9t.onnx OpenVINO) with ZERO...
- **Next:** Operator word on final deletion (entry + registry sweep) -> then card closes. Recording tripwire stays permanently (F2 is sole recorder).
- **Forensic keys (10):**
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

### `AWAY-BLOCK-1` - House held home_day 2h with everyone away — fan->mmWave->occupancy->fan self-sustaining loop; both away paths structurally blocked
thread: **presence** - status: **in_progress** - approval: **unreviewed**
- **Origin:** 2026-08-13 - operator: "why not trust that signal and send the house to away mode? What are we getting wrong about this inability to transition?"
- **Why:** Traced (AUDIT_away_transition_2026_08_13.md): path-alpha dead (all 4 trackers LOST/STALE -> trusted denominator 0); path-beta vetoed by ONE zone occupied solely by the Living Room Screek mmWave, latched by the room's own tower fan (fan O...
- **Next:** Operator picks; orchestrator recommends 1+2 together (config turn + small loop-breaker), 3 only if evidence recurs after 1+2.
- **Forensic keys (2):**
  - `operator_decision`: Ranked recs — pick any: (1) CONFIG-ONLY: add a PIR/corroborator to Living Room + the 5 other no-PIR rooms (re-enables shipped D2 demotion; highest marginal benefit, near-zero risk). (2) TIER-1: cap comfort-fan sustain on mmwave-sole prov...
  - `operator_dispositions_2026_08_13`: Rec 1: OPERATOR-OWNED — the existing Zigbee sensor is hallway-placed; operator adds a physical sensor himself. DO NOT RAISE AGAIN (explicit instruction); when new sensors appear in room configs, silently verify D2 arms. Rec 2: PARKED (ad...

## 🔍 Review (0)
_under review_

_(none)_

## 🚀 Shipped (organic open) (29)
_live, awaiting proof_

### `STUCK-SENSOR-1` - Flapping mmWave evades stuck-exclusion; fix via corroboration-gated exclusion at the ROOM tier
thread: **presence** - status: **shipped_organic** - approval: **explicit**
- **Origin:** 2026-08-09 - operator diagnosed a stuck Zigbee mmWave holding master occupancy; asked why I did not see it
- **Why:** URA's duty-cycle detector DOES catch stuck sensors and logs: 'Sensor <x> duty-cycle stuck (on-ratio exceeded over rolling window) — NOTIFY-ONLY, not excluded from occupancy'. It then KEEPS USING the stuck sensor for occupancy. Detection ...
- **Next:** BLOCKED on SENSOR-CAPABILITY-1 — do not scope exclusion until capability/role are separated, else the corroborator must be hardcoded as PIR (the defect). Then: per-room corroborator capability map from AUDIT_mmwave_only_rooms_2026-07-31....
- **Tags:** tier-2db, no-fabrication-verify, context-wide-scoping
- **Depends on:** SENSOR-CAPABILITY-1
- **Parsimony:** [BUILD] a stuck sensor silently fabricates occupancy and drives fans/HVAC/lighting in empty rooms
- **Forensic keys (20):**
  - `shipped_version`: v5.75.0
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
- **Origin:** 2026-08-09 - operator ruling on whether bed presence moves bucket or code changes: "My instinct is code change so we don't have fixed config buckets. Sensor reality should not pin use and analysis reality in software. It should just tell...
- **Why:** VERIFIED: occupancy_substrate.py:81 _KIND_TO_CONF maps kind 1:1 onto the three CONF lists, and const.py:342 TIER1_KINDS = ("motion","mmwave","occupancy"). URA has exactly three sensor kinds and they ARE the three config buckets, so the h...
- **Next:** PLAN WRITTEN 2026-08-09 (docs/planning/PLANNING_sensor_capability_vs_role.md, 477 lines). Tier 3, four framing-disjoint reviews, operator checkpoint before deploy. AWAITING OPERATOR GO — Tier 3 shared primitive, not implied-approval elig...
- **Tags:** tier-3, institutional-context, no-fabrication-verify, context-wide-scoping, numbers-get-knobs
- **Blocks:** STUCK-SENSOR-1
- **Sibling of:** SIGNAL-TRUST-LEDGER (build-gated)
- **Parsimony:** [BUILD] hardware wiring pins analytic role, so the best available corroborator in a room cannot be used as one
- **Refs:** docs/planning/AUDIT_mmwave_only_rooms_2026-07-31.md (Finding 6 — root cause); docs/planning/PLANNING_mmwave_corroboration_tier3.md (Amendment 4); docs/planning/PLANNING_signal_trust_ledger_abstraction.md (Addendum 2026-08-09 — ledger assumed this layer); custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py:81; custom_components/universal_room_automation/const.py:335,342
- **Forensic keys (17):**
  - `shipped_version`: v5.65.0
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

### `BOARD-CURRENCY-1` - Forcing-function ladder so the board (and vibememo) cannot lag shipped work
thread: **process** - status: **shipped_organic** - approval: **explicit**
- **Origin:** 2026-08-09 - operator on the stale board: "A banner is not a forcing function. Is there a harder one? A kanban that does not keep current is fairly useless" -> then "yes deploy gate with softer backups as well (the other 2 or 3). We shou...
- **Why:** Board reconciliation is the ONLY step in the deploy ritual with no forcing function. deploy.sh refuses without tests and without a README; NOTHING refuses without a board update, so it is the only step running on willpower — and it rotte...
- **Next:** MERGED to develop 2026-08-09 (0b4a22592). Rungs 1+2 live in scripts/deploy.sh. ORGANIC PROOF OPEN: the post-push write path has never executed for real — the next release is its first true run. Failure there is contained (warn + exit 0, ...
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

### `WATCHDOG-INERT-1` - Three of four v5.35.0 stuck-signal detectors are effectively inert (D3 structurally unreachable)
thread: **presence** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-09 - fell out of the ledger golden-fixture yield probe — the short buckets were short because the events never happen, which is a statement about the detectors, not about instrumentation
- **Why:** MEASURED over 7.46 d recorder + 14 d URA notification_log. D3 frozen-tracker is STRUCTURALLY UNREACHABLE: threshold FROZEN_TRACKER_DAYS=2.0 (const.py:3121) but longest HA uptime in-window is 1.02 d across 30 restarts (2.5 h median gap); ...
- **Next:** OPERATOR DECISION 2026-08-09: DROP D1/D3/P24 from the ledger migration set ("1 want to drop. Some are rare. Not a bad thing."). Ledger migration set reduces to M1 (P22), M3 (P18), M5 (D2) + M7 (P14, hand-built). Open sub-question the ope...
- **Tags:** no-fabrication-verify, measure-before-build, context-wide-scoping
- **Blocks:** SIGNAL-TRUST-LEDGER M4/M6 scoping
- **Parsimony:** [BUILD] three shipped detectors do not detect; one cannot detect by construction
- **Refs:** docs/planning/AUDIT_ledger_golden_fixture_yield.md (the probe + orchestrator escalation); custom_components/universal_room_automation/const.py:3099,3121
- **Forensic keys (17):**
  - `shipped_version`: v5.67.0
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

### `HVAC-PRESET-FLAP-1` - HVAC zone preset flaps home<->away every 5-15 min during occupied evenings (survives Writer-B removal)
thread: **hvac** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-09 - operator: "The hvac zone is being set to away and there are/were people upstairs" — then "I've been seeing this issue from the moment we walked in", which falsified the first three mechanisms I proposed
- **Why:** MEASURED: nine home<->away preset cycles on zone_2 in two hours of confirmed occupancy, all inside coast mode. Presence was correct throughout. Writer B removal (v5.56.0) did NOT stop it — see P1P3 for the falsification. Real comfort cos...
- **Next:** Mechanism proven; this is now a DESIGN question, not a diagnosis. Decide the arbitration rule between the coast duty-limiter and occupied-zone comfort. Candidates: (a) exempt the limiter when the zone is occupied AND recovering from a la...
- **Tags:** no-fabrication-verify, measure-before-build, context-wide-scoping
- **Refs:** docs/planning/kanban.data.yaml card P1P3 (the falsification); custom_components/universal_room_automation/domain_coordinators/hvac.py:1569-1610 (reason ladder), :1660-1675 (ledger row), :2470-2492 (coast duty limiter)
- **Forensic keys (11):**
  - `shipped_version`: v5.73.0
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
- **Forensic keys (12):**
  - `shipped_version`: v5.69.0
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
- **Forensic keys (14):**
  - `shipped_version`: v5.66.0
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
- **Forensic keys (8):**
  - `shipped_version`: v5.68.0
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
- **Forensic keys (2):**
  - `shipped_version`: v5.73.1
  - `scope`: ~5 LoC in NM re-page path: reuse the stored snapshot path from the original dispatch (both WhatsApp + iMessage attachment keys, BB v0.6). Tier 1. Anchor: wire-in rule applies (call-site neuter must red a test).

### `ROOM-NAME-DESYNC-1` - Options-flow room rename without data write-back — house tier permanently blind to 3 renamed rooms (substrate edges name-dropped)
thread: **presence** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-13 - ZONE-TIER-DIVERGE-1 thorough trace: presence house tier keys rooms by entry.data room_name (presence.py:2868); substrate dispatches under options-first merged name (occupancy_substrate.py:197-202). 3 rooms renamed via option...
- **Why:** BUG, live now (smoking gun: jaya_3_presence=on w/ substrate_kinds all-false). The 08-13 20:51 away transition fired THROUGH occupied Upstairs precisely because the house tier could not see the two renamed rooms. Blast radius: away/veto/c...
- **Next:** Operator picks (a) now vs (b) after-sensors; then Tier 2-DB cycle (plan review first).
- **Forensic keys (3):**
  - `shipped_version`: v5.75.0
  - `operator_decision`: SEQUENCING TRADE: (a) config-mitigate NOW (re-align 3 entries names) = house tier regains sight, but away gets HARDER (3 more phantom-holdable mmWave zones until corroborators arrive — rec 1 hardware is operator-owned); (b) sequence the ...
  - `build_dispatched_2026_08_13`: Plan rev-2 (plan review: 4 HIGH fixed incl. double-reload + setup-reload-watchdog ordering + 3rd write site + CONF_ZONE fold-in). Build in flight (worktree). Hand-sync mitigation VERIFIED live same evening (Upstairs zone occupied w/ real...

### `DP-REASON-NULL-1` - DP durable ledger logs reason:null on all 4,181 rows — carrier has no .reason field
thread: **energy** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-13 - Found by AUDIT_dp_live_behavior.md: _log_dp_eval_decision (energy.py:4002) reads getattr(carrier,"reason",None); field does not exist; real reasons live only in ~10-day recorder attrs.
- **Why:** Durable decision ledger is the long-horizon audit trail; null reasons make future DP forensics depend on recorder retention.
- **Next:** One-line fix (log the eval snapshot decision.reason) + anchor test; fold into next URA deploy batch (Tier 1).
- **Forensic keys (1):**
  - `shipped_version`: v5.73.2

### `NM-BB-IMAGE-1` - iMessage photo delivery unblocked — BlueBubbles v0.5/0.6 added attachment + media_url
thread: **notifications** - status: **shipped_organic** - approval: **approved**
- **Origin:** 2026-08-11 - operator upgraded BlueBubbles to v0.6.0; release notes show send_message now takes attachment/media_url. Verified in installed source (__init__.py:100-165: attachment=local path w/ is_allowed_path gate, media_url=URL).
- **Why:** Closes SNAP-1-followup-bluebubbles-attachment: NM _send_imessage passes speculative keys (attachment_path / attachment-as-URL) the old integration dropped; new integration reads attachment/media_url. ~10 LoC key rename + delete the one-s...
- **Next:** Tier-1 build dispatched: rename keys, drop WARN, mutation-anchored tests; ride next deploy.
- **Forensic keys (1):**
  - `shipped_version`: v5.73.0

### `SUITE-HYGIENE-1` - Kill the order-dependent flake families (sys.modules pollution) — every cycle pays a classification tax
thread: **quality** - status: **shipped_organic** - approval: **approved**
- **Origin:** 2026-08-11 - Three consecutive cycles (ARREST-COMFORT, FAN-LAYER-1, FAN-LAYER-2 D1) each spent builder+reviewer effort re-classifying the same order-flakes; FAN-LAYER-2 D1 even had its own NEW test polluted on day one.
- **Why:** Diagnosed root cause (v5.70.0 Review B / B-MED-2, deferred): test_freeze_floor.py + test_v4_6_9_hvac_intent_attrs.py install synthesized modules into sys.modules without snapshot/restore; collection-order shifts expose different victims ...
- **Next:** Small Tier-1/2 cycle: snapshot/restore fixtures around every sys.modules-stubbing test file (grep for the stub pattern, fix all instances, not just the two known); add a suite-level canary test that asserts sys.modules is unchanged acros...
- **Forensic keys (1):**
  - `shipped_version`: v5.72.0

### `NM-IMAGE-1` - NM image attachments not landing (WhatsApp + iMessage) — operator automation images DO land
thread: **notifications** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-11 - operator: "The images are not landing in the NM messages even in whatsapp; the image-bearing ones are from my automation."
- **Why:** DIAGNOSED 2026-08-11: capture works (fresh files in /media/ura/snapshots), channel works (live media_path test delivered WITH image), perimeter dispatch threads snapshot_path. The drop is NM digest routing: operator delivery_pref=digest;...
- **Next:** Operator approves cycle -> plan (Tier 2, one adversarial plan review) -> build. Prerequisite for CONSOL-1 universal-llmvision (approved 2026-08-07).
- **Forensic keys (2):**
  - `shipped_version`: v5.71.0
  - `design_pick_for_operator`: Fix shape A: persist snapshot_path into digest rows + deliver images at flush. Fix shape B (recommended for security class): image-bearing perimeter alerts bypass digest as effectively-immediate. Pick rides the plan review.

### `DP-OBSERVABILITY-1` - DP plan sensor presents stale eval snapshot as current (misled 2 diagnoses in one day)
thread: **energy** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-11 - Found during EV-GARAGE-A-NOCHARGE-1: last_eval_at 4 days old + expired must_start_by rendered without staleness cues; pause_reason_human shows day-scoped reason strings that read as current at any hour.
- **Why:** The sensor is honest data, dishonest presentation: hold_only (resting state) + stale snapshot reads as "frozen/blocked". Cost: orchestrator misdiagnosed a stall; operator asked "how is that a sensor".
- **Next:** Small cycle: age-stamp the snapshot in attrs (eval_age_min), render must_start_by only when future, clarify hold_only naming/attr (state=resting vs active-pause), and consider a stale-eval WARN when off_peak+charging ticks pass without e...
- **Forensic keys (1):**
  - `shipped_version`: v5.71.0

### `FAN-LAYER-2` - FanPolicyOracle completion — RoomFanState delegation + actuate-wrap remainder (W1-W3, W8-W10) + INV-FLA-T lock
thread: **fans** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-11 - Session 3 scoped-partial: builder deferred RoomFanState dataclass→property (34 sites), W1-W3/W8-W10 actuate wraps, adjacency reverse-scan. Honest deferral, own blast radius.
- **Why:** State-in-one-place holds for RoomAutomation tier but HVAC-tier RoomFanState still carries its own hold fields; TOCTOU lock (INV-FLA-T) only covers W11/W12. Full oracle authority needs the remainder.
- **Next:** After FAN-LAYER-1 increment ships + validates: plan review (Tier 2-DB), then RoomFanState conversion as its own cycle.
- **Forensic keys (1):**
  - `shipped_version`: v5.73.2

### `FAN-LAYER-1` - DOC-2 fan-actuation shared layer: REVIVED — FAN-MANUAL-1 fired 3 of its 4 park triggers
thread: **hvac** - status: **shipped_organic** - approval: **explicit**
- **Origin:** 2026-08-11 - operator, on the fan cycle's 1-CRIT/6-HIGH review round: "Do we have a fan abstraction in our roadmap or kanban? This is why. I know we have a fusion camera abstraction and I think a presence sensor abstraction with intent a...
- **Why:** PLANNING_fan_actuation_shared_layer.md (DOC-2, 2026-08-01) parked the extraction behind a foundation gate + 4 evidence triggers. FAN-MANUAL-1 fired: (1) new-mechanic double-port — the manual-ON hold was ported room-tier + HVAC-tier and d...
- **Next:** BUILD DISPATCHED (Tier 3). Hard dep satisfied: FAN-MANUAL-1 merged at 1f5839c3a.
- **Tags:** tier-3, institutional-context, context-wide-scoping
- **Forensic keys (9):**
  - `shipped_version`: v5.70.0
  - `priority`: high
  - `seed_already_built`: mark_fan_on_issued() (FAN-MANUAL-1 fix-up) is the first shared primitive — an authored-by channel across all URA ON sites. The extraction grows from it.
  - `gate_check_pending`: DOC-2 foundation gate also requires H8 organic validation of the v5.31.0 manual-off cooldown (a real manual OFF observed not re-arming on the live house). Verify from ledger before build — if unproven, that is the one remaining gate.
  - `PLAN_2026_08_11`: PLANNING_fan_actuation_shared_layer_v2.md (756 lines). Writer set is TEN sites across 5 files, not five — W8 zone-vacancy sweep + W9 pre-arrival bypass ALL machinery (trigger #3 fired at TWO sites). RECOMMENDED SHAPE (b): FanPolicyOracle...
  - `PLAN_REVIEW_1_2026_08_11`: NEEDS-REVISION — TWO MORE MISSED WRITERS: C1 _stop_all_fans_safety (hvac.py:2330-2362, smoke/CO all-zones fan stop — legitimate but must consult w/ safety=True) and C2 hvac_predict._activate_zone_fans (:1038-1102, pre-arrival ON — would ...
  - `PLAN_READY_2026_08_11`: Rev-2 committed: 12 writers (W11 safety-stop w/ safety=True always-ALLOW- but-logged; W12 pre-arrival ON defers under cooldown); FanDecisionSnapshot required-arg contract; INV-FLA-T temporal + per-room lock via oracle.actuate() context m...
  - `DEDUPE_2026_08_11`: Sweep: DOC-2 planning doc is the PARENT (parked, triggers now fired -> READY per the skill rule). FAN-MANUAL-1 is the trigger-firing cycle, linked. ARREST-COMFORT-1 sibling class. THIRD instance of a parked plan's fired trigger surfacing...
  - `organic_evidence`: shipwatch 2026-08-11: v5.70.0 L2 no-fan-flap CONFIRMED (13.3h post-boot, all managed fans steady; Jaya 12.5h continuous). L3 holds + L4 safety still organic-open.

### `PLAN-TIER-1` - Tiered PLAN reviews: quality up front — plans reviewed before builds, like builds
thread: **process** - status: **shipped_organic** - approval: **explicit**
- **Origin:** 2026-08-11 - coined during the FAN-MANUAL-1 post-mortem — the plan missed 2 emission sites a one-line grep would have found, costing build + 3 reviews + CRIT fix-up
- **Why:** A plan review is ~20 min; a build round is hours. Protocol now in CLAUDE.md: Tier 1 = none; Tier 2/2-DB = one adversarial plan review (independent re-enumeration, greps not trust); Tier 3 = two framing-disjoint (completeness incl. parked...
- **Next:** apply to the two in-flight plans on arrival; organic proof = a plan-review finding that demonstrably prevents a build round
- **Forensic keys (1):**
  - `first_subjects`: FAN-LAYER-1 plan (Tier 3 -> 2 plan reviews) and ARREST-COMFORT-1 plan (likely Tier 3 -> 2) — both in flight as this lands; they get the treatment on delivery.

### `CIRCLING-SEVERITY-1` - A "circling" exterior person produced alert_count=0
thread: **perimeter** - status: **shipped_organic** - approval: **unreviewed**
- **Origin:** 2026-08-08 - observed during v5.62.1 live validation
- **Why:** Live track xt-000001-695c9e: back_yard -> front_side_ptz -> back_yard -> front_side_ptz -> back_yard, classification=circling, 133s, alert_count=0 at 09:22 CDT. Track linking worked correctly (one track, not five alerts). But CIRCLING is...
- **Next:** trace why alert_count=0 for a circling classification; decide whether circling should escape pure clock-time gating
- **Tags:** no-fabrication-verify
- **Parsimony:** [BUILD] the most suspicious exterior behaviour may be silently unalerted outside night hours
- **Refs:** exterior_track_linker.py classification; perimeter_alert.py alert-hours gating; CONSOL-1 contextual-severity ruling
- **Forensic keys (1):**
  - `shipped_version`: v5.74.0

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

### `CONSOL-1` - Perimeter consolidation cycle
thread: **perimeter** - status: **shipped_organic** - approval: **explicit**
- **Origin:** 2026-08-07 - retire redundant manager surface; I need to weigh in — usability
- **Why:** three parallel alerting stacks (URA NM, HA doorbell automation, zone_monitoring pagers) duplicate delivery
- **Next:** fold SNAP-1 + TEST-1/2 in; Tier 2-DB
- **Tags:** tier-2db, institutional-context, audit-first
- **Parsimony:** [BUILD] 3 stacks page the same event with no shared cooldown/routing
- **Refs:** PLANNING_perimeter_consolidation.md; AUDIT_ha_side_alerting_reconciliation.md
- **Forensic keys (3):**
  - `shipped_version`: v5.73.0
  - `rulings`: Option C surfacing (= A enhanced)
  - `plan_state`: rev-2 PLAN-READY (1 adversarial review: 3 CRIT + 4 HIGH fixed in-plan incl. No-Soak violation + G4/G6 misname + vehicle-window orphan). D0 probe: doorbell llmvision SILENTLY BROKEN since 02-13 (gpt-5-mini reasoning eats 300 tokens); buil...

### `SNAP-1` - Snapshot mirror-and-improve
thread: **perimeter** - status: **shipped_organic** - approval: **explicit**
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

### `CAM-AREA-PENDING` - Camera area corrections — RESOLVED
thread: **camera** - status: **shipped_organic** - approval: **explicit**
- **Origin:** 2026-08-07 - found during the exterior+interior camera area-id correction sweep
- **Refs:** https://claude.ai/code/artifact/ef6dc227-8488-4b59-b745-f71e946da6a8
- **Forensic keys (1):**
  - `resolved`: Madrone G6 Entry -> front_porch (operator: front porch/entry; sits with front_door_aerial door overhead). DONE.

### `D3-AREA-INHERIT` - URA D3 fused sensor should inherit room area on creation
thread: **camera** - status: **shipped_organic** - approval: **implied**
- **Origin:** 2026-08-07 - 5 rooms had roomless CameraPersonDetectedSensor - manual entity-area set was a band-aid
- **Why:** CameraPersonDetectedSensor (D3) does not set area_id from its room on creation, so new rooms silently ship roomless -> breaks resolver/transit room mapping. Durable fix so we do not hand-patch each new room.
- **Next:** set _attr area / registry area from room area on D3 sensor creation
- **Tags:** numbers-get-knobs
- **Parsimony:** [BUILD] per-room fused camera sensors ship with no area
- **Refs:** binary_sensor.py CameraPersonDetectedSensor
- **Forensic keys (1):**
  - `shipped_version`: v5.74.0

### `v5.59.0` - resolver-legs
thread: **perimeter** - status: **shipped_organic**
- **Origin:** 2026-08-07 - shipped + live-validated
- **Refs:** README_v5.59.0.md
- **Forensic keys (2):**
  - `note`: live PASS (zero multi-key WARN / _2 storm / URA ERROR; telemetry attr present)
  - `organic_open`: CLOSED 2026-08-07: leg_firing_by_camera POPULATED from real events (rear_ptz shows frigate+frigate2+protect on one camera; back_yard frigate+frigate2); today's exterior person-detects each = one alert per track, pass_by tracks alert_coun...

## ⏸️ Waiting on operator (2)
_needs a human call_

### `EV-GARAGE-A-NOCHARGE-1` - BMW on Garage A refuses charge overnight — vehicle-side or pilot fault; URA exonerated
thread: **energy** - status: **waiting_operator** - approval: **unreviewed**
- **Origin:** 2026-08-11 - operator: "BMW on Garage A has not charged overnight." Investigated; initial DP-stall framing CORRECTED.
- **Why:** Recorder: URA lifted TOU pause at 21:00 off_peak, switch.garage_a ON 23:53-06:09, 41A limit — EVSE Connected all night, NEVER Charging, 0 kWh. L1 sockets charged fine 01:30-07:04. DP hold_only = resting state (paused_by_battery_drain emp...
- **Next:** OPERATOR: check BMW app (schedule/target/errors) + reseat cable. URA-side follow-ups split out: DP observability (stale last_eval snapshot presented as current, expired must_start_by shown) + garage-A network fix (homelab).
- **Forensic keys (1):**
  - `sharp_problem`: Suspects: (1) BMW in-car charge schedule/target-SOC met; (2) pilot/cable fault — six 10s Connected->Disconnected blips overnight; (3) Garage A network degradation (Emporia unavailable-flap every 2-5min + Shelly overhead + Zigbee door als...

### `F1-SUNSET` - Frigate-1 go/no-go
thread: **camera** - status: **waiting_operator** - approval: **blocked**
- **Origin:** 2026-08-07 - Remind me when we can go on f1 sunset tmr
- **Why:** steps 1-6 remote (mine), step 7 = operator unplugs NUC; readiness = organic one-alert-per-multi-engine-traversal
- **Next:** operator go/no-go (reminder Aug 8)
- **Tags:** audit-first
- **Refs:** AUDIT_frigate1_sunset.md

## ⏳ Waiting on me (Claude) (1)
_I owe something_

### `SWEEP` - Morning sweep
thread: **ops** - status: **waiting_me** - approval: **implied**
- **Why:** reason-ledger first night, Frigate car/dog/cat first events, snapshot-fix organic proof, v5.57/58 organic criteria
- **Next:** check + report each

## 🅿️ Parked (1)
_revisit-trigger set_

### `ARRESTER-BOOT-BLIND-1` - Arrester boot-window manual blindness — manual holds predating the listener are unclassifiable
thread: **hvac** - status: **parked** - approval: **unreviewed**
- **Origin:** 2026-08-11 - operator: "The battery is not 97%. The arrester should be seeing this as a bad action" — up-hallway manual 75->71 cool during a 26->11 SOC collapse, arrester idle w/ overrides_today=0.
- **Why:** LIVE INCIDENT ~22:36-23:10: zone_2 flipped sleep->manual at 22:36:06 during the post-HA-upgrade boot window BEFORE the arrester listener attached (22:37:53); subsequent setpoint walks (75->71 at 22:56) were within-manual = no classifiabl...
- **Next:** Incident investigation: verify both gaps from source; probe-first (recorder: boot-coincident manual holds frequency); fix cycle Tier 2-DB.
- **Forensic keys (3):**
  - `parked_2026_08_12`: OPERATOR: "Park #2 until another incident." Revisit trigger: next boot-coincident manual hold the arrester misses (same signature: zone flips to manual during boot window, setpoint walks within-manual, arrester overrides_today stays flat...
  - `sharp_problem`: Gaps: (1) boot reconciliation — on listener attach, classify any zone ALREADY in manual as inherited-manual and start standard arrest evaluation; (2) verify _handle_climate_change classifies within-manual setpoint deltas (manual->manual ...
  - `related`: Envoy reserve wedge (device=10 vs cloud=26/27) is the energy half — the write-verify self-heal alert was RIGHT to fire. RESOLVED 2026-08-12: operator power-cycled Enpower; all 3 reserve legs coherent at 10 (local number + envoy sensor + ...

## ✅ Done (0)
_closed, evidence in refs_

_(none)_

## ❓ Other (1)
_unknown status bucket_

### `CIRCLING-LABEL-1` - Circling loops page but are never LABELLED/escalated as circling (2-camera shape) — cooldown blocks the hop where classification forms
thread: **perimeter** - status: **waiting_on_operator** - approval: **unreviewed**
- **Origin:** 2026-08-13 - CIRCLING-SEVERITY-1 Review A MEDIUM-A1: founding shape pages at hops 1-2 as pass_by (LOW/MED); classification becomes circling at hop 3; per-camera 300s cooldown returns before severity re-resolves; continuation-coercion blo...
- **Why:** INV-M holds (pages happen, tripwire honest) but the operator's 08-08 complaint was about CIRCLING specifically. The dominant 2-camera alternating shape can never emit a HIGH circling-labelled page under current mechanics.
- **Next:** Operator picks A/B/C. If A: own small Tier-2 cycle (new cooldown exemption on the perimeter dispatch path = regression-prone, plan review required).
- **Forensic keys (1):**
  - `operator_decision`: (A) surgical — allow ONE dispatch through the cooldown when a track's classification TRANSITIONS (one extra HIGH page at the hop circling forms; ~persist last_dispatched_classification on ExteriorTrack). (B) tighten invariant + add circl...

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
