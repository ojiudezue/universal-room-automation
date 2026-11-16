# Step 8 §10.1 Review C: test authority by real per-site source mutation

Branch `feature/step8-identity-actions`, diff base `486b2783...HEAD` (custom_components only).
Method: one production-source edit per drill, `__pycache__` purged, `python -B`, `PYTHONDONTWRITEBYTECODE=1`,
then restored and `git status` confirmed clean after every batch. Test set per drill (one pytest process):
test_person_profile, test_arrival_scene_entry_hook, test_occupied_since, the 8 lighting slice/fixup files,
test_room_options_reload_suppression, test_cm_reload_suppression, test_reload_watchdog_hazard,
test_person_awareness_layer_guard, test_music_following{,_coordinator,_repair}, test_v5100_music_following.
Drivers: `.claude/tmp/mutbatch_c8.py` with `muts_c8_{a,b,c}.json` (untracked scratch).
Baseline before drills: cycle files 47 passed, 2 skipped (D1 B0 live fixture pending; HA<2026.11 visible marker).

## Result: 130 mutants, 83 RED, 47 GREEN

Verdict: **SHIP with fix-up of the MEDIUM test gaps** (no production bug found; every priority site except the
items below is RED on a specific named test). 0 CRITICAL, 0 HIGH, 7 MEDIUM, ~20 LOW test gaps; rest equivalent.

## Priority sites

| Site | Result |
|---|---|
| Store key rule (profiles_from_options, get_person_profile, people_save key) | RED: test_profile_keyed_by_one_id_rule, test_hidden_fields_dropped_keep_stored_values |
| Owner derivation (own_rooms both halves, room_owners) | RED: test_owners_derived_shared_master, test_profile_sensor_state_and_attributes |
| Room name -> entry_id | `.get(key)` lookup RED (test_room_name_maps_to_entry_id); sentinel guard and strip GREEN (below) |
| Master default True (const, reader, form default, stored False honored) | RED x4: test_master_defaults_on_when_unset, test_master_false_respected |
| Suggestions never stored | store path RED; window/rounding/top_n/error paths GREEN (below) |
| Save-time validation (both rules, both error keys, flow wiring) | RED: test_music_on_without_pick_rejected, test_scene_on_without_scene_rejected; media_valid RED. Merge-normalization GREEN (below) |
| Media strip at playback (play_pick, normalize keeps entity_id) | RED: test_pick_media_drops_browse_entity_id, test_stored_pick_keeps_browse_player_for_redisplay |
| Volume clamp (max, min, save clamp, default const) | RED: test_volume_bounded_on_save; bad-value fallback GREEN (LOW) |
| Hook day/evening-only (sleep caller, day caller, gate, preference order) | RED x6: test_sleep_caller_never_reads_override, test_entry_override_replaces_slot_scene |
| Four result reasons | applied/hold/unavailable RED (test_hold_and_unavailable_reasons_differ_same_room etc.); **error GREEN** |
| Reload suppression of person_profiles (both sets) | RED: test_people_save_in_reload_suppress_allowlist, test_people_save_no_reload_real_options_update |
| display_of label | sensor shared-owner labels RED; **sensor name and People picker label GREEN** |

Also RED: occupied_since (test_occupied_since x2), stubs (test_real_engine_stub_returns_none_until_d3),
episode types (test_episode_types_registered), sensor registration/entity_id/count/attrs, menu entry, abort,
bathroom filter, room step gating, hold check, engine-failure fallback.

## GREEN sites

### MEDIUM test gaps (need a test)

| ID | Site | Mutation survived | Test needed |
|---|---|---|---|
| M1 | automation.py `_activate_scene_checked` outer except returns `ARRIVAL_SCENE_RESULT_ERROR` (R4); const ERROR value (R6); `_maybe_activate_slot_scene` except returns False (R9) | error -> "applied", or ERROR value = "hold"; error path returns True | Make scene.turn_on (or the hold check) raise with a welcome scene set; assert engine note == "error" AND return False (per-light path runs). Fourth of the four reasons has no test. |
| M2 | person_profiles.merge_profile_save blank media clears (G1) | blank pick keeps the old pick | Submit empty media for a stored music_default; assert key removed. |
| M3 | merge welcome_scene non-`scene.` / blank (G5, G5b) | `light.x` or blank saved as the welcome scene; blank does not clear | Submit "light.kitchen" and "": assert dropped/cleared. |
| M4 | merge bool coercion (G6) | truthy non-bool stored raw | Submit "yes"/1 for auto_music: assert `is True`. |
| M5 | merge by_room normalize + filter + non-mapping (G3, G3b, G4) | invalid per-room picks stored; non-mapping not reset | Submit by_room with one valid, one blank, one extra-keyed pick; assert only valid, normalized. |
| M6 | merge rooms sorted-set (G2) | duplicates/order stored | Submit duplicate rooms; assert sorted unique. |
| M7 | PersonProfileSensor unique_id (D5) | all persons share one unique_id (second sensor would fail to register) | Two persons: assert distinct unique_ids and entity_ids on the real constructor. |

M2-M6 are save-time normalization (§5.1 "suggestions never stored / save-time validation" neighbourhood): only
volume is pinned today; validate_profile is RED because it runs on merge output, but nothing pins merge itself.

### LOW test gaps

| ID | Site | Note |
|---|---|---|
| L1 | sensor name `display_of(slug)` (D1) and People picker label `display_of` (D3) | operator-visible labels; assert `friendly name == "Person Profile Ezinne"` and picker option label. (The display_of label is RED only for the shared-owner attribute.) |
| L2 | sensor shared-owner filter `len(owners) > 1` (D7) | self-only room would list as "shared"; add a one-owner case. |
| L3 | `_person_profile_sensors` dedupe (D9) | name + entity-id forms of the same person yield two sensors; add both forms to tracked_persons. |
| L4 | room-name sentinel guard x4 + strip (S5, S5b, S5d-g) | only matters if a room is literally named away/home/unknown; add a map with a room named "Home". |
| L5 | normalize_media strip (S9c) and `.` check on entity_id (S9d) | whitespace id; entity_id without domain. |
| L6 | volume bad-value fallback (S10c); form volume default (G23) | non-numeric stored volume; form default value. |
| L7 | flow error keeps submitted values (S8f) | UX only: error re-show should show merged input. |
| L8 | PROFILE_KEYS filter (S7) | unknown submitted keys stored; form cannot send them, so defensive. |
| L9 | suggestions: window lookback/until (X6, X7), percent rounding (X4), top_n slice and `top_n<=0` (X3b, X5), `b<=a` (X2), tz strip (X11), db raising (X9), empty-text (X12) | display only; test uses exact 80/20 and two rooms, so rounding/top_n/window are unpinned. Add 3-room 33/33/33 case and a window assertion. |
| L10 | `_get_person_profile` blank guard (S2b), `_str_list` scalar (S4d) | scalar-string rooms; blank person. |
| L11 | rooms_music: room without player counted (G10), requires auto_music (G11b), rooms_note (G12), room name title fallback (G21) | UX/gating; pick_media is gated on auto_music, so G11b is harmless. |
| L12 | pick_media by_room non-Mapping (K9) | unreachable after merge normalization. |

### Equivalent mutants

| ID | Reason |
|---|---|
| H10 (no engine -> no early return) | `None.arrival_scene_for` raises AttributeError, caught by the inner `except Exception`, returns None: same observable result. |
| S2b (blank person) | `tracked_person_entity_id("")` is `"person."`, never a stored key: lookup returns None either way. |
| X8 (db missing guard) | the `await db.get_closed_person_visits` sits inside the try; the AttributeError is swallowed to "". |
| G24 (URI fallback ungated) | with `PEOPLE_MUSIC_URI_FALLBACK_ENABLED=False` the schema has no `_uri` field, so nothing reaches the branch. |
| L5/L12 | defensive normalization behind validated input. |

## Skips

`test_people_form_matches_live_fixture` (D1 B0 live spike pending) and `test_people_form_visible_conditions`
(HA < 2026.11 in test venv) skip: the `visible` marker path is covered only by stub-marker tests, not the real
2026.11 marker. Not mutated; record as a known in-suite limit.

## Plan completion
Nothing deferred by this review. Fix-up tests M1-M7 should be added before ship (LOWs optional, fix in-cycle if
cheap). Tree restored: `git status --short` empty after every batch.
