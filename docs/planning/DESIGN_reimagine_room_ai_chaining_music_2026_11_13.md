# DESIGN: reimagine room AI rules, automation chaining and music following

> SUPERSEDED for delivery by the two PLANNING docs (operator 2026-11-13: no shadow mode); kept as design history,
> NOT A BUILD SPEC. See `PLANNING_music_following_repair.md` and `PLANNING_unified_room_rules.md`.

Design exploration, not a build plan. Cards: AI-ROOM-RULES-TRUST-REPAIR-1, MUSIC-FOLLOWING-TRANSFER-REPAIR-1,
PERSON-PROFILE-PREFERENCES-1, parent AUDIT-ROOM-AI-AUTOMATION-CHAINING-MUSIC-1. Written 2026-11-13 by ura-planner.
Source of facts: `AUDIT_room_ai_automation_chaining_music_2026_11_13.md` (the audit). Findings H1-H5, M1-M6, L1-L6
below are the audit's ids. Claims marked **(unverified)** were not checked in code, docs or live state this session.

Read for this doc: the audit (full), the four board cards, CLAUDE.md (Institutional Context First, Marginal-Benefit,
Numbers Get Knobs, Producer AND Consumer, F1-F5), `ARC_identity_vision_census_map.md` (rows for the read API and
PERSON-PROFILE-PREFERENCES-1), `PLANNING_person_awareness_read_api.md` §1-§5, `PLANNING_crossing_vision.md` P2-D10
(grading), `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §1 table, §3 headings and §10 ledger in full (not every line of
§2-§9; nothing here relies on a §2-§9 claim beyond what the audit and the §1 table state). No HVAC code is touched,
so the HVAC state-of-play doc was not required.

## 0. Charter (operator, verbatim)

- "We will fix the AI automation and the AI [chaining] and music following. We will not retire them. The reason
  they're not exercised is because I don't trust them yet, and the entire point is to build it so I can trust it.
  Also, music following is key to personalization."
- "Part of what we have to do is to figure if we can improve and simplify those three features. Not just audit them,
  but look for actual opportunities to improve them, build them in a way that is, find opportunities for reimagining
  what's possible with the goal in mind."
- Audit goals: correctness; current with HA, with what we have learned and with hardened patterns; good test
  coverage; observability and configuration.

This overrides the audit's "RETIRE AI rules" recommendation. Retirement is off the table.

## 1. Goal per feature

| Feature | What it is FOR | What makes the operator trust it enough to turn it on |
|---|---|---|
| Room AI rules | Describe room behaviour in plain language ("when I enter after dark, lamp to 30%") and have the room do it | He can see what the rule compiled to before it runs, see what it WOULD have done for a week, see every real fire with a reason, and undo or disable it in one tap. A rule that cannot run never reports `active`. |
| Automation chaining | Compose: let a room event start an HA automation or script the operator already owns | Same evidence trail as AI rules (fires logged, conditions honoured deliberately), and one place to see what a room will do on enter/exit. |
| Music following | Personalization: a person's audio follows that person through the house | It moves the right person's music to the right player, never silences the source without starting the target, and asks or offers undo until it has earned silence. |

## 2. What exists and works (extend, do not rebuild)

From the audit, verified there with file:line: the chain executor is correct, lifecycle-clean and HA-current
(`coordinator.py:834-925, 957-1155, 1757-1828`); the AI executor's guards (domain allowlist `coordinator.py:1208`,
climate/cover/hold gates) have real-path tests; MF gates D1-D12, SLEEP invariant, kill switch and name match hold
(`test_v5100_music_following.py`); the transition producer is healthy (8,126 rows / 14 d, 1,039 eligible
player-to-player transitions at confidence ≥ 0.6). The broken parts are narrow: the two transfer calls (H1, H2), the
person filter (H3), the unparsed-rule dead end (H4), five dead knobs (H5), a listener leak (M1), uncounted skips (M2),
replica tests. Every option below is a delta on that base.

## 3. Prior-art scan: REUSE or BUILD per proposed piece

| Piece | Verdict | Existing symbol |
|---|---|---|
| Person id matching for rules | REUSE | `music_following._person_key` `music_following.py:44`; long term the one id rule of `PLANNING_person_awareness_read_api.md` INV-ID-ONE-RULE |
| Person location input for MF | REUSE | `transition_detector.async_add_listener(self._on_person_transition)` `music_following.py:211`, `RoomTransition` `transitions.py:28` |
| Who is in a room (rule person filter) | REUSE | `person_coordinator.get_room_occupants` `person_coordinator.py:2131` (keyed by display name, hence H3) |
| F4 sightings | REUSE (not needed for v1) | `PresenceCoordinator.get_last_person_sighting(s)` `presence.py:5907-5917` |
| F1/F2 read surface | REUSE when shipped | read API ship 1, `get_house_census`, `view_for_class` (planned, not in code yet) |
| Approve / undo actionable notification | REUSE | `NotificationManager._handle_companion_action` (listener `notification_manager.py:1330`); add one `startswith` branch per action family, the pattern crossing-vision grading uses (`PLANNING_crossing_vision.md` P2-D10). No second listener |
| Decision rows / episodes | REUSE | `memory_episodes` via `memory_facade.py` (reader `:462`); chains already write `chain_trigger` activity rows `coordinator.py:905-915` |
| Skip/outcome counters and health sensor | REUSE + EXTEND | `_record_stat`, `_SKIP_OUTCOMES`, `MusicFollowingHealthSensor` (`sensor.py:8157`) |
| Live gate setters for knobs | REUSE | `MusicFollowing.update_gate_config` `music_following.py:311` |
| NL to structured actions | REUSE | `ai_task.generate_data` with `structure` (already called, `config_flow.py:3224-3247`) |
| Rule store | REUSE | `CONF_AI_RULES` / `automation_chains` in room options (rung 2) |
| Per-person preferences store | BUILD (owned by PERSON-PROFILE-PREFERENCES-1, not here) | none found (card adjacency 2026-11-08: no owner/pref CONF keys) |
| Preference suggestions from history | REUSE later | `RoutineForecaster` `domain_coordinators/routine_forecaster.py:117`, `person_visits` |
| Shadow / would-have-done machinery | BUILD small | no generic shadow helper found for room rules (grep `shadow`, `would_have` in package: only domain-specific uses, e.g. HVAC evidence/shadow machine per presence §10 #11). Pattern exists, helper does not |
| Rule compiler module | BUILD by moving, not writing | the two parsers `config_flow.py:3184-3338` and `:15246-` collapse into one module (M6) |

## 4. Room AI rules and chaining

### 4.1 Are they one concept? (seam check)

Today: chains are `trigger -> automation.trigger(entity)`; AI rules are `trigger + optional person + conditions ->
service calls`. Both hang off the same room triggers (enter, exit, lux, house_state, signals) and the same signal
subscription code (`coordinator.py:1786-1823`). A chain is an AI rule whose action is "run this automation".

**For merging:** one rule shape (trigger, conditions, actions), one executor, one decision log, one status sensor,
one test surface; chaining stops being an unlogged sibling. The operator favours consolidation, and the two share every
trigger and lifecycle path already.
**Against:** chaining works and is simple; folding it into a store with LLM-authored rules could make a correct path
inherit the new path's risk. Mitigation: merging the *shape and log* does not require merging *authorship*; a chain
entry stays operator-authored and needs no parse.

Verdict: merge at the contract (one `RoomRule` record, one executor entry point, one log row type), keep two authoring
paths ("describe it" and "pick an automation"). Data migration is a read-time adapter over the two existing option
keys, not a rewrite of stored config.

### 4.2 Simplest version that delivers trust (S-RULES)

1. Correctness: H3 (person match via `_person_key`), H4 (never store an unparsed rule; the form errors and keeps the
   text; plus a "retry parse" step for the one live Exercise Room rule), M6 (one compiler module), L1 (pass
   `skip_condition: False` by default, knob per chain), L2 (bound `_last_conflicts`).
2. Honest status: `sensor.<room>_ai_automation_status` states `active` / `needs_parse` / `disabled` / `none`;
   attributes `rules_ok`, `rules_unparsed`, `fires_7d`, `last_fire`, `last_fire_reason`.
3. Decision rows: one row per rule evaluation that matched its trigger, with outcome `fired` / `would_fire` /
   `skipped:<reason>` (switch off, person absent, condition false, gate refused). Chains get the same row type.
4. Shadow mode per rule: `mode: shadow | live` (default shadow for every new rule). In shadow the executor runs the
   full match and gate path and writes `would_fire` with the exact service calls it would issue, then stops. Promotion
   to live is a one-tap action.
5. Preview at creation: the options flow shows the compiled actions in plain words before save ("Turn on Lamp to 30%
   when you enter and it is dark").
6. Real-path tests replacing the inline replicas in `test_ai_automation.py` / `test_automation_chaining.py`.

Captures: nearly all the trust value. The operator sees the compiled rule, a week of "would have" rows, and every fire.

### 4.3 Reimagined versions

**R1. Compile to HA-native artefacts.** The parser asks `ai_task.generate_data` for a structure whose actions are HA
service-call objects (domain, service, target, data), validated against the room's own entities and the existing
allowlist, then stored as today. Variant R1b goes further and writes a real HA automation (labelled `ura_room_<room>`)
that the operator can open in the HA editor, with URA's chain path firing it. Benefit: inspectability for free, HA
traces, HA's own editor. Ingredient risk for R1b: a new writer to HA's automation config (a shared surface outside
URA), lifecycle of generated automations across room reloads and deletes, and the URA gates (HVAC chokepoints,
covers, manual hold) no longer apply to actions HA runs directly. That last one is decisive: R1b bypasses governed
writes. **Recommend R1 (structured, URA-executed, rendered readably), park R1b** (revival trigger: HA exposes a way
to route automation actions through an integration's gate, or the operator wants rules editable in the HA UI more than
gated).

**R2. NM approve / undo.** On the first N live fires of a rule (knob), NM sends an actionable notification: "Exercise
Room: turned lamp on (rule 'enter after dark'). Keep / Undo / Back to shadow." Undo restores prior states captured
before the action (scene-style snapshot of the touched entities only). Benefit: closes the loop from would-have to
trusted with a grade, the same pattern as crossing-vision grading. Risk: a new NM action family (one `startswith`
branch, low), a state snapshot (small, but undo on climate must go through the HVAC governed path or be excluded;
**exclude climate from undo**). Worth it once S-RULES ships.

**R3. Weekly digest.** One NM message per week per house: per rule, would-fire count, fire count, undo count, skips by
reason, plus "promote these 2 shadow rules?". Cheap (read rows, one message). Good second step.

**R4. Rule suggestions from behaviour.** Use repeated manual actions (activity log + routine forecaster) to propose
rules in plain language, created in shadow. High value later, but new inference and noisy ground truth. Park; revival
trigger: S-RULES shadow rows show the operator promotes rules readily.

### 4.4 Marginal-benefit decomposition (rules + chaining)

| Step | Captures | Adds over previous | Ingredient risk |
|---|---|---|---|
| S-RULES | Correct execution, honest status, shadow, decision rows, preview | (base) | Low: one new row type through the existing write queue (batch), one mode field, no new shared primitive |
| + R1 structured compile | Fewer parse failures, readable preview | Moderate: parse quality, one compiler | Low; M5 `object`+`multiple` acceptance **(unverified)** must be probed first by one live parse |
| + R2 approve/undo | The operator's grade, one-tap rollback | High for trust | Low-medium: new NM action family, snapshot/restore; exclude climate |
| + R3 digest | Habitual review | Moderate | Low |
| R1b HA automations | HA-editor inspectability | Small over R1 + preview | High: bypasses URA gates, new external writer. Park |
| R4 suggestions | New rules without typing | Unknown | Medium-high: new inference. Park |

## 5. Music following

### 5.1 Identity framing (F1-F5, consumer class)

MF consumes **person location**: today `RoomTransition` from the transition detector (BLE/Bermuda room changes plus
room occupancy), keyed by person. In the F model that is closest to F4 (P seen at X at T) from BLE, not from
cameras. It also reads F1 implicitly (only tracked persons). Consumer class: **comfort**: a wrong move is an
annoyance, never a safety or access event. Policy for that class lives in MF (confidence 0.6, stale 15 s, ping-pong,
BLE distance), not in the producer.

Should MF read through the person-awareness read API? Not in v1. The API's ship 1 covers house-level census and
arrival records; room-level per-person location is not in it (`PLANNING_person_awareness_read_api.md` §2 table).
The transition stream is the right input today, already healthy. When the read API grows a per-person room view,
MF and the profile should move to it together. Camera F4 sightings could add "seen in Kitchen" for a person whose
phone is elsewhere; **not for v1**: interior face arrival failed its D0 gate (presence §1 table, D0-P3), so camera
room sightings are not reliable enough to move music.

### 5.2 Simplest version that delivers trust (S-MF)

1. Correctness: H1 (join with `entity_id=source`, `group_members=[target]`), M3 (decide cleanup after one live
   check), H2 (`transfer_queue` with `target={"entity_id": to}`, `source_player`, `auto_play: True`), L4 add `heos`
   and `esphome` to platform mapping only after checking `MediaPlayerEntityFeature.GROUPING` on the entity.
2. MA first: resolve each room player to its Music Assistant mirror when one exists (188 MA mirrors of 352 players)
   and use `transfer_queue` as the primary path; native `join` for same-platform non-MA pairs; generic
   `play_media` last. Mapping is explicit per room (a second optional `room_ma_player` field, or derive via the device
   registry: the MA entity sits on its own MA device, so "same device" may not hold) **(unverified: how MA mirrors
   relate to the native device in the registry; probe first)**.
3. Observability: count `no_player`, `source_not_playing`, `ble_too_far` (M2); fix the listener leak (M1); wire the
   five knobs through `update_gate_config` or delete them (H5), add the stale-seconds field; remove the no-op
   `music_on_arrival_start` toggle from the form; scope `_stop_all_playback` to configured room players (M4).
4. Verify on ground truth: after a transfer, read the target's state and `media_title` / queue, and the source's state;
   record `success` only if target is playing and source is not silenced without the target playing. The current
   `media_play` nudge that can mask H1 is removed or recorded as `nudged`.
5. Shadow mode per person (default for re-enable): MF evaluates and writes `would_transfer from X to Y via path P`
   without acting. Promotion per person.
6. Tests: fix `FakeServices.async_call` to accept `target=`, assert the exact payload of each transfer path, test
   `_schedule_group_cleanup` and the verify path; close TEST-MUSIC-SYSMODULES-LEAK-1; delete the tautologies in
   `test_music_following.py`.

### 5.3 Reimagined: "audio follows the person" (personalization)

**R5. Offer, then move.** Instead of moving silently, the first M transfers per person (knob) send an NM actionable:
"Your music is in Kitchen. Move it to Study A? Move / Not now / Stop following today". Then flip to move with a 30 s
"Undo" action (undo = transfer back). This is the trust ladder: shadow, offer, act with undo, act silently. Risk:
latency (a phone tap after you have walked in), so this is a trust stage, not the end state.

**R6. Per-person preferences.** Volume per person per room type, quiet hours (no follow into a sleeping zone, already
partly the SLEEP invariant), "follow me" on/off per person (exists as per-person switches), preferred source/playlist
for arrival music. These live in PERSON-PROFILE-PREFERENCES-1, not in MF; MF reads them. Arrival music (card
scope add 2026-11-12) is the same "audio for this person" contract and belongs to the same consumer, keyed on F5 plus
F1 and the profile, subject to the arrival opt-in.

**R7. Group instead of move.** When a second person is still in the source room, extend the group (MA player group or
native join) rather than move the queue; when the source room empties, drop it. Captures the "two people, one
stream" case. Risk: group lifecycle is the M3 problem multiplied; needs per-pair ping-pong (open L9). Park until S-MF
plus R5 have run and the logs show the two-person case is common.

**R8. Sendspin.** Sendspin is an MA player provider plus an experimental ESPHome group player
(https://beta.music-assistant.io/player-support/sendspin , https://esphome.io/components/media_player/sendspin/)
**(unverified: current stability)**. Going MA-first makes Sendspin players reachable with no MF code of their own.
Do not build a Sendspin-specific path.

### 5.4 Marginal-benefit decomposition (MF)

| Step | Captures | Adds | Ingredient risk |
|---|---|---|---|
| S-MF | Transfers that actually work, honest counters, shadow | (base) | Low-medium: the M3 cleanup choice needs a live walk |
| + R5 offer/undo | Trust ladder, operator grade | High for trust | Low: one NM action family (shared with R2) |
| + R6 profile reads | Personalization: volume, quiet hours, arrival music | High for the stated goal | Medium: depends on PERSON-PROFILE-PREFERENCES-1 store; MF only reads |
| R7 group-not-move | Multi-person case | Unknown share of walks | Medium-high: group lifecycle. Park |
| Camera F4 as location | Phone-less person | Small today | High: interior sightings failed D0. Park |

## 6. Consolidation and seams

1. **Rules and chaining:** merge the contract (§4.1). Strong case, weak counter-case.
2. **Trust layer shared by all three:** shadow mode, decision rows, NM approve/undo, weekly digest. One small module
   (`trust_ladder` or similar: modes `shadow / offer / live_undo / live`, a row writer, the NM action branch). Building
   it twice (once for rules, once for MF) would be the artificial seam. Counter-argument: rules act once per trigger,
   MF moves a stream; their undo semantics differ. Resolution: share modes, rows and NM plumbing; each feature owns its
   own undo function. Recommend shared.
3. **MF and the person profile:** one contract, "what audio does this person want, where and when". MF is the
   actuator; the profile is the store; arrival music is a second trigger into the same actuator. Do not let arrival
   music build its own player resolution or transfer code.
4. **MF and the identity arc:** MF must use the one person-id rule (INV-ID-ONE-RULE) rather than its private
   `_person_key` once the read API ships; until then `_person_key` is that rule for this surface and AI rules should
   reuse it (H3), not grow a third.
5. **Should MF become a room rule** ("on person enters room, move their music")? Against: MF is a per-person
   continuous policy with ping-pong, stale, BLE distance and cleanup state; expressing it as a rule would either
   lose that or turn the rule engine into a state machine. Keep MF separate, sharing only the trust layer. A later
   rule action `music.follow_here(person)` could call MF, which would let a room rule trigger it.

## 7. Numbers get knobs

| Knob | Rung | Default | Why / kill semantics |
|---|---|---|---|
| `rule.mode` per rule | 2 (options) | `shadow` for new rules | promotion is deliberate; `live` is today's behaviour |
| `AI_RULE_UNDO_OFFER_FIRES` | 3 (Number) | 5 | first N live fires get an undo notification; 0 = never ask |
| `chain.skip_condition` per chain | 2 | False | L1; True restores today's bypass |
| `RULE_DECISION_ROW_RETENTION_DAYS` | 1 | reuse activity-log retention **(unverified value)** | storage bound, change needs review |
| `mf_person_mode` per person | 3 (Select) | `shadow` on re-enable | trust ladder stage |
| `MF_OFFER_TRANSFERS` | 3 | 10 | offers before acting; 0 = skip offer stage |
| `MF_UNDO_WINDOW_S` | 1 | 30 | undo action TTL |
| five CM timing knobs | 2 (existing) | live values 8/60/2/5/3 | wire via `update_gate_config` or delete; no new field |
| `CONF_MF_STALE_TRANSITION_SECONDS` | 2 | 15 | currently rung 1 by accident |
| `RULES_WEEKLY_DIGEST_ENABLED` | 3 (Switch) | on | off = no digest |

## 8. Recommendation and sequence

Build trust fastest by fixing what silently lies first, then making every action visible, then asking the operator.

| # | Step | Tier | Why first |
|---|---|---|---|
| 0 | Probes (read-only, ~1 h): one live `ai_task` parse with the current structure (M5); one WiiM to WiiM walk while playing, read `group_members` (H1/M3); map MA mirror entities to room players via registry (§5.2.2) | probe | Measure before build; each answer changes the design |
| 1 | **MF repair (S-MF items 1, 3, 4, 6)**: transfer calls, MA-first, counters, knobs, leak, tests | 2 | Music is the operator's personalization priority and the defects are concrete and small. Live criterion: one walk produces target playing and source handled per the chosen cleanup, recorded `success` with the new verify |
| 2 | **Trust layer + rules repair (S-RULES)**: shared shadow mode and decision rows, honest status, H3/H4/M6/L1, one compiler, real-path tests; merge chain+rule contract (adapter only); MF shadow per person rides on the same layer | 2 (operator may elevate to 2-DB: new row type) | Gives the "would have done" week the operator needs before turning anything on |
| 3 | **NM approve/undo** (R2 + R5) and weekly digest (R3) | 2 | The operator grades; the system earns silence |
| 4 | **Structured compile** (R1) if probe 0 shows parse quality is the limit | 2 | Only if measured |
| 5 | **Profile reads in MF** (R6, arrival music) | 2, after PERSON-PROFILE-PREFERENCES-1 plans the store | Personalization once the actuator is trusted |
| parked | R1b HA-native automations, R4 suggestions, R7 groups, camera F4 location | | revival triggers in §4.3 and §5.4 |

What the two build cards become:
- **MUSIC-FOLLOWING-TRANSFER-REPAIR-1**: keep as step 1, add MA mirror resolution and ground-truth verify to its
  scope, add probe 0 (walk + registry) as its first deliverable. Shadow per person moves to step 2.
- **AI-ROOM-RULES-TRUST-REPAIR-1**: becomes step 2, retitled toward "room rules (AI + chains) on one contract with a
  shared trust layer (shadow, decision rows, honest status)". Its plan must also declare the shared trust module that
  MF will use. A new card for step 3 (NM approve/undo + digest, shared by rules and MF) is needed; card R1 only if
  probe 0 says so.
- **PERSON-PROFILE-PREFERENCES-1**: unchanged owner of the store; its pre-plan should name MF as its first consumer.

Tier note: each step is Tier 2 (no reserve, HVAC control or shared state machine; climate actions remain behind the
existing executor gates and are excluded from undo). If step 2 changes the executor's gate order, elevate it.

## 9. Unverified claims (explicit)

1. `ai_task` acceptance of `object` + `multiple` in HA 2026.11 (audit M5).
2. Live effect of H1 on WiiM, and what unjoin of the leader does to the target (M3).
3. How MA mirror entities relate to native player devices in the device registry.
4. Sendspin stability and whether every Sendspin player appears as an MA `media_player`.
5. Activity-log retention value for decision rows.
6. Whether HA offers a supported way to route a native automation's actions through an integration's gates (R1b
   revival trigger); not researched.

References: https://www.home-assistant.io/actions/media_player.join/ ,
https://www.home-assistant.io/actions/music_assistant.transfer_queue/ ,
https://www.home-assistant.io/actions/ai_task.generate_data/ ,
https://contributors.home-assistant.io/core/entities/ai-task/ ,
https://beta.music-assistant.io/player-support/sendspin , https://esphome.io/components/media_player/sendspin/ .
