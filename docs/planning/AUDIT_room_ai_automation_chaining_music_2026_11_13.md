# AUDIT — Room AI automation, automation chaining, music following

**Card:** AUDIT-ROOM-AI-AUTOMATION-CHAINING-MUSIC-1 · **Author:** ura-prober (read-only) · **Written:** 2026-11-13 18:22 CDT
**Live system:** HA 2026.11.1 (`.HA_VERSION`), 47 room entries, 4 tracked persons, 352 `media_player` entities (188 `music_assistant`, 71 `wiim`, 23 `linkplay`, 2 `sonos`, 2 `denonavr`, 1 `esphome`).
**Read first:** CLAUDE.md, QUALITY_CONTEXT.md bug classes, DEVELOPMENT_CHECKLIST.md, URA_CODE_TRACING_METHODOLOGY.md, URA_ARCHITECTURE_MAP.md, MUSIC_FOLLOWING.md, PLANNING_v3.10.0_AI_AUTOMATION.md, PLANNING/CRITIQUE_audit_music_following, REVIEW_MUSIC_PEOPLE_FOLLOWING.md, DRAFT_README_music_following_name_match.md, v5.10.0 review record, cards MUSIC-FOLLOWING-NO-TRANSFERS-SINCE-MAY-1 and TEST-MUSIC-SYSMODULES-LEAK-1.
**Log-read gap:** HA core logs are not readable from this host (`home-assistant.log` absent, `.1` empty, `.old` dated 2025-11-10; `ssh ha` has no journald and `ha core logs`/`docker logs` returned 0 lines even for strings that demonstrably fire). Fire checks below rest on the URA DB (`immutable` read-only open), `.storage/core.config_entries`, and the HA REST `/api/states` snapshot taken 18:15 CDT. Nothing was changed.

## Verdicts

| Surface | Verdict | One line |
|---|---|---|
| Automation chaining (`coordinator.py:834-925, 957-1155, 1757-1828`) | **SOLID / UNUSED** | Correct, lifecycle-clean, HA-current; configured in 0 of 47 rooms, 0 `chain_trigger` rows in the 30-day activity window. |
| AI NL rules (`coordinator.py:1160-1452`, `config_flow.py:3053-3338, 15018-15330`) | **NEEDS WORK → recommend RETIRE** | Executor is well-guarded, but the person filter can never match, `needs_parsing` rules are stored and never parsed (the only live rule is one), tests are inline replicas. |
| Music following engine (`music_following.py`) | **NEEDS WORK** | v5.10.0 gates hold up; both native transfer calls are wrong against current HA/MA APIs (`join` leader inverted; `transfer_queue` payload invalid), so only the generic `play_media` path can work. |
| MF coordinator + observability (`domain_coordinators/music_following.py`, sensors, CM options) | **NEEDS WORK** | 5 of 7 CM timing knobs are dead form fields; diagnostic listeners leak across reload; "source not playing / no player" skips are uncounted so the health sensor cannot explain a quiet day. |

## Fire check (window 2026-10-14 17:55Z → 2026-11-14 00:19Z = activity-log retention, 20,736 rows)

| Producer / feature | Configured | Fired | Evidence |
|---|---|---|---|
| Chained automations (`_fire_chained_automations`) | 0 rooms have `automation_chains` (all 47 entries, data+options) | 0 | `ura_activity_log` `action LIKE '%chain%'` = 0 rows; room actions are only occupancy/light/fan kinds |
| AI rules (`_execute_ai_rules`) | 1 rule: Exercise Room `6a932dd2`, trigger `enter`, `needs_parsing: true`, `actions: []` | 0 | `sensor.exercise_room_ai_automation_status` = `active`, `last_trigger: null`; `switch.exercise_room_ai_automation` = **off**; no activity-log writer exists for AI rules at all |
| AI parse (`ai_task.generate_data`) | ai_task entities present: `ai_task.claude_ai_task`, `openai_ai_task` (others unknown/unavailable) | unknown | No DB/entity trace; the one stored rule carries the "ai_task unavailable" fallback shape (`config_flow.py:3120-3133`) |
| Signal triggers (house_state/energy/safety/security) | Subscribed only when a room has a matching chain/rule (`coordinator.py:1786-1823`) | 0 | No room qualifies (Exercise rule is `enter`); house-state sub exists only for Away leave-on rooms |
| Per-room AI toggle | 47 switches: **31 off, 16 on** (REST, restored 17:44 CDT) | — | Even a parsed Exercise Room rule would be skipped: switch off |
| Transition producer (`room_transitions`) | — | **healthy**: 8,126 rows / 14 d; 5,144 at conf ≥ 0.6; 1,700 between two rooms that both have a configured player, 1,039 of those ≥ 0.6 | DB `room_transitions`; last row 2026-11-13 18:19:37 CDT |
| MF engine outcomes | 10 rooms with `room_media_player`; 4 persons enabled; CM switch on | today: `transfers_today 0`, `low_confidence 21`, `ping_pong_suppressed 11`, last skip Jaya Garage A→Powder 18:14 CDT | `sensor.universal_room_automation_music_following_health`, `..._transfers_today`, `..._last_transfer` |
| MF last success | — | last anomaly row (observed 1.0) 2026-10-11 21:09Z; baseline `sample_count 2672` last updated 2026-11-08 14:22Z | `anomaly_log` (691 Oct rows), `metric_baselines` |
| Players at 18:15 CDT | 9 WiiM `idle`, Living Room denonavr `off`, Master Bedroom (MA/Sonos) `unavailable` | — | REST states + entity registry |

Reading: the producer side is alive; the engine evaluates transitions; nothing was playing in any configured room at probe time. Whether a transfer has succeeded since 2026-10-11 is **unknown** (success and skip both bump `sample_count`; logs unreadable).

## Findings (ranked)

### HIGH

**H1 — `media_player.join` leader/follower inverted.** `music_following.py:1505-1513` calls `join` with `entity_id=to_player` (idle target) and `group_members=[from_player]` (playing source). HA docs: "The target plays the audio, and the group members follow it" (https://www.home-assistant.io/actions/media_player.join/); core WiiM `async_join_players` joins `group_members` "to the group led by the current player" (https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/wiim/media_player.py). Effect on the WiiM→WiiM path (9 of 10 configured players): the playing source becomes a follower of a silent leader — the exact "music disappears from source without appearing at target" the design doc's silent-actuator invariant forbids (MUSIC_FOLLOWING.md §Cross-coordinator invariants). The `_verify_transfer` `media_play` nudge (`:981-998`) can start the target's own last queue and record `success`, masking it. Bug class: #37 API-contract / #4 domain-mismatch class. Fix: `entity_id=from_player, group_members=[to_player]`; then the 5 s `unjoin` of the source (`:1014-1025`) must become an unjoin of… nothing (the leader) — re-decide cleanup (H1b). **Unverified live** (log gap); falsifier: one walk WiiM→WiiM while playing, then read `group_members` on both entities.

**H2 — `music_assistant.transfer_queue` payload cannot validate.** `music_following.py:1553-1561` sends data `{"source": from, "target": to}` with no target. Current schema (platform entity service, target = `media_player` entity; data `source_player: cv.entity_id`, `auto_play: bool`): https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/music_assistant/services.py, https://www.home-assistant.io/actions/music_assistant.transfer_queue/. The call raises, is caught (`:1575-1577`), logs WARNING and falls through to generic `play_media`. Also `auto_play` defaults false, so even a schema-correct call would move the queue without starting it. Fix: `async_call("music_assistant","transfer_queue",{"source_player": from_player,"auto_play": True}, target={"entity_id": to_player}, blocking=True)`. Live impact today: only Master Bedroom is an MA entity, but 188/352 players are MA mirrors — this is the path to prefer (see Currency).

**H3 — AI-rule person filter can never match.** Options/init forms store `person` from an `EntitySelector(domain="person")` → `person.oji_udezue` (`config_flow.py:3167-3169`, `15xxx` mirror). Executor compares it to `_get_identified_persons_in_room()` (`coordinator.py:1183-1190`), which returns `person_coordinator.get_room_occupants` names keyed by display name ("Oji Udezue": `__init__.py:3149`, `person_coordinator.py:2131`). Same defect class as MUSIC-FOLLOWING-NO-TRANSFERS (entity_id vs display name). Every person-scoped rule is silently inert. Fix: REUSE `music_following._person_key` (`music_following.py:44-64`). No person-scoped rule exists live.

**H4 — `needs_parsing` rules are a dead-end state.** Writer `config_flow.py:3120-3133` (init flow, ai_task unavailable); readers: none (`grep needs_parsing` → only that block). The live Exercise Room rule is exactly this: `actions: []`, never re-parsed, no UI hint, yet `sensor.exercise_room_ai_automation_status` reports `active` / `ai_rules_count 1`. Bug class #53 (computed-but-not-consumed) + #32. Fix: either refuse to store unparsed rules (error back to the form) or add a retry on options-flow open and surface `needs_parsing_count` on the status sensor.

**H5 — Five CM timing knobs are form fields with no runtime reader (Bug Class #32).** `CONF_MF_COOLDOWN_SECONDS / PING_PONG_WINDOW / VERIFY_DELAY / UNJOIN_DELAY / POSITION_OFFSET` are read into the coordinator (`domain_coordinators/music_following.py:111-115`) and used only in a log line (`:213-217`); the engine uses constants `MUSIC_TRANSFER_COOLDOWN_SECONDS` (`music_following.py:800`), `TRANSFER_VERIFY_DELAY_SECONDS` (`:974`), `GROUP_UNJOIN_DELAY_SECONDS` (`:1015`), literal `+ 3` (`:1634`), `PING_PONG_WINDOW_SECONDS` (`transitions.py:652`). Live CM options carry all five (8/60/2/5/3) — any operator edit is a no-op. Already a "known residual" on the done card; still open. Conversely `DEFAULT_MF_STALE_TRANSITION_SECONDS` (`const.py:4123`) has **no** CONF field (`grep CONF_MF_STALE_TRANSITION_SECONDS config_flow.py` = 0) — rung 1 by accident. Fix: push the five via `update_gate_config`-style setters (REUSE `:311-323`) or delete the fields; MUSIC_FOLLOWING.md §Tunables is stale on this.

### MEDIUM

**M1 — Diagnostic-listener leak across reload.** `MusicFollowing.add_diagnostic_listener` (`:349-351`) has no removal API (`grep remove_diagnostic_listener` = 0). The coordinator registers `_on_transfer_outcome` on every `async_setup` (`:264-266`) and `async_teardown` (`:677-707`) never unregisters; `MusicFollowingHealthSensor.async_added_to_hass` registers too (`sensor.py:8157`) with no `async_on_remove`. Each CM reload adds a listener → duplicate `record_observation` per outcome (inflates `sample_count`, the HVAC-BASELINE-MAXSAMPLES instance) and calls into removed entities, swallowed by the bare `except` at `:404-408`. Bug class #38 analogue.

**M2 — Uncounted skips make the health sensor blind.** `_execute_transfer` returns without `_record_stat` on "no player for source/target" (`:814-826`), "source state missing" (`:861-866`) and "source not playing" (`:868-873`). Today's sensor shows 21 `low_confidence` and 0 transfers while 1,039 eligible transitions/14 d passed confidence — the dominant outcome ("nothing was playing") is invisible. Also BLE-distance rejections are booked as `low_confidence` (`:545`), conflating two gates. Add `no_player`, `source_not_playing`, `ble_too_far` stats (they flow to `last_skip_reason` for free via `_SKIP_OUTCOMES`).

**M3 — Group cleanup direction (H1b).** `_schedule_group_cleanup` unjoins the **source** 5 s after a verified join (`:1014-1025`). Once H1 is fixed the source is the leader; WiiM `async_unjoin_player` ungroups the entity's own device, which dissolves the group and may silence the target. Decide: unjoin the *target* after a generic re-play, or keep the group and let the operator's next transfer re-form it. Needs a live check.

**M4 — `_stop_all_playback` scope.** On a critical hazard/security signal it sends `media_stop` to every playing/paused `media_player` in HA (`domain_coordinators/music_following.py:662-668`; 352 entities here, incl. TVs, Alexa, casts). Gated OFF by default (`CONF_MUSIC_ON_HAZARD_STOP`/`_SECURITY_STOP` absent from live CM options → `_get_signal_config` default False, `base.py:270-285`). Scope to configured room players before anyone turns it on.

**M5 — `ai_task` structure shape unverified.** Both parsers send `structure={"actions": {"selector": {"object": {"multiple": True}}, "description": ...}}` (`config_flow.py:3224-3236`). The contributor docs define fields as `selector` + optional `description`/`required` and show `text`/`number` selectors only (https://contributors.home-assistant.io/core/entities/ai-task/); `object` + `multiple` appears only in the architecture proposal (https://github.com/home-assistant/architecture/discussions/1216). Whether HA 2026.11 accepts it is **unknown**; the response handling (`result["data"]["actions"]`) matches the documented return shape. One live parse would settle it (not done — would call an LLM).

**M6 — Duplicated parser.** Init-flow parser/validator (`config_flow.py:3184-3338`) is a copy of the options-flow one (`15246-…`), ~150 lines twice, already drifting (init swallows all exceptions and stores `needs_parsing`; options returns `ai_parse_failed`). Bug class #33 (sibling helpers).

### LOW

- **L1** `automation.trigger` is called without `skip_condition`, whose default is `true` — chained automations' own conditions are bypassed (`coordinator.py:897-902`). Document or pass `skip_condition: False`.
- **L2** `_last_conflicts` grows unbounded in memory (`append` at `:1408`, reset only when a rule matches `:1177-1178`); sensor slices `[-5:]`.
- **L3** `HOUSE_STATE_TRIGGER_VALUES` (`const.py:4463-4466`) is a hand-copied list of house states (Bug Class #22 exposure if `HouseState` changes) — not cross-checked against the enum here (unverified).
- **L4** `_get_player_platform` maps only sonos/linkplay/wiim/denonavr/music_assistant (`music_following.py:1054-1062`); `esphome`/Sendspin → generic; `heos` → generic although HEOS supports join.
- **L5** `_get_room_player` Strategy 3 (HA Area) will see MA mirrors next to native entities for every room; explicit `room_media_player` avoids it today in 10 rooms.
- **L6** `AIAutomationStatusSensor` = `active` whenever a rule exists, parsed or not; no fire counter; AI rules write no activity-log row (chains do, `:905-915`).

## HA / Music Assistant / Sendspin currency

| API used | Site | Current? | Note / source |
|---|---|---|---|
| `ai_task.generate_data` with `return_response=True` | `config_flow.py:3238-3247`, options twin | Yes (2025.7+), structure selector format partly unverified (M5) | https://www.home-assistant.io/actions/ai_task.generate_data/ ; contributors doc above |
| `automation.trigger` | `coordinator.py:897-902` | Yes; `skip_condition` default true (L1) | HA automation action docs |
| `entry.async_create_background_task(eager_start=False)`, async `add_update_listener`, `async_dispatcher_connect` + unsub lists | `coordinator.py:1001-1006, 1037-1041, 1750-1755, 1781-1823`; unload `__init__.py:6100-6130` | Yes; matches the hardened patterns (tracked tasks, listener cleanup, v4.2.24 async listener fix) | — |
| `media_player.join` / `unjoin` | `music_following.py:1505-1513, 1018-1023` | API current; **semantics inverted (H1)**; no `MediaPlayerEntityFeature.GROUPING` check before calling (grep = 0) | join action doc; core wiim source |
| `music_assistant.transfer_queue` | `:1553-1561` | API current; **payload invalid (H2)** | MA services.py; action doc |
| `media_player.play_media` + `media_seek` generic | `:1609-1648` | Yes | — |
| Sendspin | none | No core HA integration found (search, 2026-11); Sendspin is an MA player provider + experimental ESPHome "Sendspin Group Media Player" entity (https://esphome.io/components/media_player/sendspin/, https://beta.music-assistant.io/player-support/sendspin). MA groups Sendspin/AirPlay/Cast players itself. | The recommended way to "move music" in an MA house is `transfer_queue` between MA player entities — which URA cannot currently issue (H2). |

Recommended direction: resolve each room's player to its MA mirror when one exists (188 here) and use `transfer_queue(auto_play=True)` as the primary path; keep native `join` (fixed) for same-platform non-MA pairs; generic last.

## Test coverage (static; suite not run — slot owned by another agent)

| File | Lines | Drives production code? | Hollow / stale | Gaps |
|---|---|---|---|---|
| `test_ai_automation.py` | 775 | **No** — every class re-implements the logic inline (docstrings say so, e.g. `:132-137, 386-390`) | Replica of `_get_builtin_target_entities` (`:392-406`) lacks the `CONF_NIGHT_LIGHTS` union now in `coordinator.py:1431-1434` → Bug Class #60 stub-mirror drift; `_execute_rule_action` replica has no allowlist/climate/cover/hold gates | `_execute_ai_rules` matching, person filter (H3 would have been caught by a real-path test), conflict detection, `_parse_rule_with_ai`, `_validate_parsed_actions` (0 tests, grep) |
| `test_automation_chaining.py` | 804 | **No** — `MockLuxDetector` and inline `_fire_chained_automations` (`:42-72, 181-213`) | Inline copies | `_update_signal_subscriptions` is only exercised incidentally by `test_reconcile_on_return.py`, `test_room_substrate_integration.py`, `test_lighting_review_fixups.py` |
| Real-path AI-executor tests elsewhere | — | **Yes**: `test_room_covers_garage_guard.py:286` (real `_execute_rule_action`), `test_hvac_w1a_site_migration.py:1191` (climate block), `test_lighting_slice_c_manual_hold.py:295` (hold gate), `test_lighting_slice_d_house_state.py:227` (`_on_house_state_changed`), `test_builtin_target_entities_night_light_entry.py` | — | Good anchors; the only trustworthy coverage of this surface |
| `test_v458_signal_handler_gating.py` | 178 | Source-grep by design (Bug Class #62, acknowledged in its docstring) | — | Gating matrix is asserted on text, not behaviour |
| `test_music_following.py` | 348 | **No** — inline replicas; tautologies `assert ("playing" == "playing") is True` (`:290`), `assert 120 + 3 == 123` (`:309`) | Hollow | Nothing load-bearing |
| `test_music_following_coordinator.py` | 380 | Partly — real `MusicFollowingCoordinator` under `sys.modules` stubs | `setdefault` at `:91-95` and unconditional overwrites `:119, :128` never restored (TEST-MUSIC-SYSMODULES-LEAK-1, open); `:260-283` asserts the five dead knobs are "stored" — a test that enshrines H5 | — |
| `test_v5100_music_following.py` | 1362 | **Yes** — real `MusicFollowing._on_person_transition` on `FakeHass`; covers D1–D12 gates, SLEEP invariant, kill switch, name match | Six source-grep tests (`:312-324, 732-740, 884-892, 929-948, 1036-1127`); `FakeServices.async_call` (`:231-232`) accepts no `target=` kwarg, so a corrected `transfer_queue` call would `TypeError` in the fixture | `_transfer_media` / `_transfer_same_platform_join` / `_transfer_mass_queue` / `_transfer_generic` payloads never asserted — exactly where H1/H2 live; `_schedule_group_cleanup`, `_verify_transfer` nudge path untested |

## Observability and configuration

- **Chaining/AI:** per-room `switch.<room>_ai_automation` (RestoreEntity, #52-guarded, `switch.py:5723-5753`); `sensor.<room>_ai_automation_status` (+ `last_trigger`, `last_conflicts`); `binary_sensor.<room>_automation_conflict`. Chains log `chain_trigger` to the activity log; AI rules log nothing. Knobs: `LUX_DARK/BRIGHT_THRESHOLD` rung 1 (`const.py:4444-4445`); chains/rules are options-flow (rung 2) — correct rungs. Labels in `strings.json:249-343, 2538-2540` are plain; the Exercise Room's stored-but-unparsed rule has no label or error telling the operator it is inert.
- **MF:** master `switch.ura_music_following_enabled` (now a real kill switch, `music_following.py:449-489`), per-person `switch.ura_music_following_coordinator_person_*`, health/transfers-today/last-transfer/active-rooms/anomaly sensors with skip reasons — good surface, except M2 (uncounted skips) and the dead knobs (H5). `mf_sleep_suppress`, `mf_night_suppress_mode` are live via in-place apply (`__init__.py:8389-8440`). `music_on_arrival_start` is still offered in the CM form (`config_flow.py:10414-10415`, `strings.json:1889`) although D9 made the handler a DEBUG no-op (`domain_coordinators/music_following.py:573-583`) — the critique's "do not leave a toggle that does nothing" was not completed.
- **Baselines:** `transfer_success_rate` mean 0.29 / std 0.41 / n 2672; `cooldown_frequency` variance 0.0 (constant). The Oct anomaly burst (691 rows, z≈2 by 10-11) has tapered as the baseline absorbed successes; the "never forgets" instance stays on HVAC-BASELINE-MAXSAMPLES-1.

## Keep / fix / retire

| Surface | Recommendation | Marginal-benefit note |
|---|---|---|
| Automation chaining | **KEEP as-is** (+L1 doc line) | ~90 lines, zero runtime cost when unconfigured, correct and HA-current. Retiring saves nothing measurable; it is also the safe substitute for AI rules ("write an HA automation, chain it"). |
| AI NL rules | **RETIRE the executor + parsers** (tombstone `CONF_AI_RULES`, keep the status sensor reading `0`), or at minimum fix H3+H4+M5 and collapse M6 | Simplest version of the benefit (NL → service calls in a room) is captured by HA's own `ai_task`/assist tooling plus chaining, with none of these ingredients: LLM-authored service calls executing in URA, a domain allowlist that must track the HVAC chokepoints, two parsers, a dead `needs_parsing` state, a person filter that never worked, and tests that test themselves. Live usage: 1 inert rule, 31/47 rooms have the toggle off, operator "rarely use". Operator decision. |
| Music following engine | **FIX** H1, H2, M2, M3 (≈40 lines + fixture `target=` kwarg + payload tests), then one live walk to validate | Everything above the transfer call was hardened in v5.10.0 and holds; the transfer calls themselves were never exercised by a test or (verifiably) by the house. If the operator does not want following at all, the CM switch is the config-first answer (no code retire needed). |
| MF coordinator / knobs | **FIX** H5 (wire or delete five fields; add a field for stale seconds), M1 (listener removal on teardown/remove), M4 scope, remove `music_on_arrival_start` from the form | Small, self-contained; closes the residuals the done card left open. |

## Where the prior docs are now stale

- `docs/Coordinator/MUSIC_FOLLOWING.md` §Tunables lists the five knobs as live (they are not, H5); §14 "MASS transfer_queue → join → generic" describes a dispatch whose first two legs cannot work as written (H1/H2); the `_coordinator_enabled` kill switch (v5.103.34) and `_person_key` matching are missing from the gate list (new gate 0 before "same room").
- `PLANNING_audit_music_following.md` / `CRITIQUE…`: all C1–C11, L1–L8 shipped in v5.10.0; still open: C10 (restart cooldown, accepted), D10 TTS (dropped), L9 per-pair ping-pong, L7 per-person queues, C7's second half (retire the arrival toggle from the form).
- `DRAFT_README_music_following_name_match.md` residuals (BLE bleed, baseline distortion, dead knobs) remain open; "the target player starts within the verify delay" was never observable here (log gap).
- `PLANNING_v3.10.0_AI_AUTOMATION.md`: design still matches the code (parse-once, chain-after-builtin, AI-only conflicts, delete+recreate); its "verification" sections never contemplated a stored-unparsed rule.

## Unverified / gaps (explicit)

1. H1 live effect on WiiM (docs + core source say inverted; no log or state proves a silent source).
2. Whether any MF transfer succeeded after 2026-10-11 (DB cannot separate success from skip in `sample_count`; logs unreadable).
3. M5 `object`+`multiple` acceptance by `ai_task` in HA 2026.11.
4. L3 enum parity; `test_cycle_d_coordinator_hardening.py` switch-restore tests (not read in full).
5. No pytest run (slot discipline); coverage assessed statically.
