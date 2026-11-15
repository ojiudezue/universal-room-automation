# Layer ship 3a, framing C (test authority via real per-site source mutation)

Branch `feature/layer-ship3a` @ 8c875182; diff base develop bc4f462b (merge-base verified, three-dot diff). Tier 2-DB (operator-elevated).
Read first: PRESENCE + HVAC state-of-play docs and SENSOR_FLEET_CLASSES (complete). No claim in their ledgers re-asserted.

Method: 245 single-site mutations of production source (one anchor replaced, exactly-once check), each run against the cycle test set
(ship3a + guard + the 8 touched test files, 419 tests), `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` purged before and after, file restored
in `finally`, `git status` clean after every batch (only the untracked drill dir, removed before commit). Plus 17 real reverts to the
pre-3a form against the real-tree guard test, plus 22 injected leaks.

Totals: 206 RED, 36 GREEN (of 248 runs incl. guard reverts; 1 anchor miss re-run RED). GREEN rows split into equivalent mutants and real test gaps below.

## RED (authority confirmed), by site
| site | mutations (each RED) | test that went RED (first) |
|---|---|---|
| 3 F5 producer calls (presence.py geofence / camera_face, person_coordinator.py BLE) | call removed; wrong source; payload key dropped; obs-mode gate removed; geofence direct inference trigger removed | `test_dispatch_person_arriving_payload_equal[geofence/camera_face/ble]`, `test_observation_mode_still_suppresses[*]`, `test_geofence_inference_trigger_order_unchanged` |
| `to_signal` key logic (signals.py) | sighting/zone/ts always or never; source / person_entity key dropped; deepcopy | `test_to_signal_omits_unset`, `test_to_signal_sighting_identity`, payload_equal |
| `from_signal` ts (dict branch) | dropped | `test_to_signal_omits_unset` |
| missing-source rejection | removed; None-only; empty-only | `test_dispatch_rejects_missing_source[None]` / `[]` |
| `dispatch_person_arriving` | raw payload; wrong signal; never sends; count removed | payload_equal, `test_layer_diagnostics_counts` |
| `subscribe_person_arriving` | coroutine reject removed; no `@callback`; raw passed; wrong signal; unsub no-op | `test_subscribe_person_arriving_payload` |
| face-latch register / read / unsub | insert-front; not appended; unsub no-op / clear-all; read empty / live list; census read removed; sighting register / unregister removed | `test_face_latch_register_order_and_unsub`, `test_sighting_producer_registers_and_unregisters_latch` |
| ring append / prune | append removed; shared deque; count bound removed / off-by-one / drops newest; age bound removed / doubled / `<=`; consts 1800->1000, 32->16 | `test_ring_prunes_by_count_and_age`, `test_crossing_ring_age_covers_step7_windows`, `test_resolve_direction_appends_ring` |
| `get_crossings_since` / `get_crossing` | exclusive; filter removed; sort removed; list return; camera filter removed; inverted; always None | `test_get_crossings_since_order`, `test_ring_amend_does_not_clobber_newer` |
| `door_camera_device_ids` | returns entity; name-guess | `test_door_camera_device_ids_registry_only` |
| `door_entry_entities` / `door_neighbours_for_stem` + both consumers (arrival_edges, perimeter `_near_areas`) | no neighbours; no egress; reordered; empty; consumer read removed | `test_door_entry_areas_unchanged` |
| G3 `attach_crossing_attribute` | unknown-key check off / not called; single send removed / doubled / only-when-found / only-with-source_ref; in-place->append; pointers not moved / moved for any record; provenance ignored; nameable not normalised; aged-out count removed; payload keys dropped; payload_extra precedence; sorted removed | `test_g3_forbidden_keys`, `test_g3_fires_once_found_or_not`, `test_ring_amend_does_not_clobber_newer`, `test_crossing_record_serialises_and_nameable_via_g3` |
| exit-backfill migration | call removed; role / row_id / person_id dropped; source_ref given; Persons reader role filter removed; either reader on wrong signal | `test_exit_backfill_display_equal`, `test_exit_backfill_reader_ignores_other_roles`, `test_exit_backfill_ring_untouched` |
| `subscribe_person_edges` | no `@callback`; coroutine / kind reject removed; kind / person filter removed; wrong signal; counters; cb not called | `test_person_edges_callback_counted_flags`, `test_subscribe_rejects_coroutine_and_unknown_kind`, `test_person_edges_delivered_synchronously` |
| `get_person_edges_since` + `person_edges_truncated_since` | exclusive; filters; order; list; full leg / creation leg removed; full off-by-one; created_ts zero; count removed | `test_person_edges_since_per_person_inclusive`, `test_person_edges_truncated_since` |
| crossing-vision G1 call | subscribe removed; departure-only; wrong cb | `test_crossing_vision_residency_delivery_equal` |
| `set_pre_arrival_enabled` + HVAC call | call removed; inverted; setter no-op / always True | `test_hvac_toggle_reaches_person_coordinator` |
| `note_face` | slug / time dropped; call removed; args swapped | `test_note_face_equal` |
| move log | call removed; append removed; unresolved not dropped / not counted; method; rooms swapped; entity vs name; count / age bound removed; drops newest | `test_location_moves_*`, `test_location_moves_mirror_bus_event` |
| `location_moves_since` / truncation | exclusive; list; full leg; age leg; count; off-by-one; age floor doubled; presence delegates (fallback, raises, no-pc) | `test_location_moves_truncated_since`, `test_location_moves_truncated_when_t_older_than_age_bound`, delegate tests |
| `min_confidence` | default 0.0 | `test_min_confidence_table` |
| `census_view.view_for_class` | switch check removed / off still awareness / missing awareness; house_census_view cls ignored / always awareness; presence delegates | `test_census_view_positional_and_cls_equal` |
| PLB sites (binary_sensor.py x2), `_CensusAwarenessSensor` | cls -> positional trust / display; sensor cls / view changed | `test_phone_left_behind_reads_house_state_class`, `test_census_awareness_sensor_reads_display_class_golden` |
| `get_layer_diagnostics` + diagnostics.py | each counter key removed; ring_sizes; config-entry data leaked (nested and top level); non-CM not `{}`; key renamed; wrong manager key | `test_layer_diagnostics_counts`, `test_diagnostics_download_*` |

## GREEN rows
### Real test gaps (production code unchanged by the finding; tests needed)
| # | SEV | site (file:line) | mutation that left 419 tests green | needed test |
|---|---|---|---|---|
| C1 | MEDIUM | `census_view.py:72` (promoted-class check) | check removed: with the switch on, the legal-but-unpromoted class `notification` reads `awareness` (legal set is {display, notification}, promoted {display}, const.py:6638-6641) | `view_for_class(hass, "notification")` == trust with switch on |
| C2 | MEDIUM | `census_view.py:80` (fail-closed `except`) | returns `awareness` on any error | raise from `hass.states.get`, assert `trust` |
| C3 | MEDIUM | `sensor.py:5233` (LastPersonExit role filter) | filter removed; a non-`exit_backfilled` amend re-reads. The Persons-exited filter (`sensor.py` ~5092) IS RED; the named "both readers" requirement is half pinned | mirror `test_exit_backfill_reader_ignores_other_roles` for `LastPersonExitSensor` |
| C4 | MEDIUM | `diagnostics.py:44` | adding `hass.states.async_all()` states to the download stays green; test only checks config-entry data | assert no entity state / person `.data` in the payload |
| C5 | MEDIUM | `presence.py:6056` (`subscribe_person_edges` delegate) | `persons=` dropped, or `kinds=` forced to default | delegate filter test (the free function's filters are RED) |
| C6 | MEDIUM | `presence.py:6117` (`get_crossings_since` delegate) | `camera` argument dropped | per-camera delegate read |
| C7 | MEDIUM | `transit_validator.py:1056` (`amend_crossing` tracker route) | route disabled (always notice-only): a `source_ref` amend through `amend_crossing` never touches the ring. Only prod caller passes `source_ref=None`, so no live effect today | `amend_crossing(hass, ref, {...})` with a tracker in `hass.data` amends the ring |
| C8 | MEDIUM | `transit_validator.py:1273` (`provenance` override) | applied unconditionally: `provenance=None` clobbers an existing provenance | amend with `provenance=None` keeps provenance |
| C9 | LOW | `presence.py:6081, 6083` | no tracker -> truncated False; error -> False (both must be True, fail toward "incomplete") | `person_edges_truncated_since` with no tracker / raising tracker |
| C10 | LOW | `presence.py:6059-6068` (`get_person_edges_since` never-raise) | `except` narrowed, still green | raising tracker returns `()` |
| C11 | LOW | `person_coordinator.py:2327` | creation leg of `location_moves_truncated_since` removed (t between age floor and creation) | t in that window |
| C12 | LOW | `person_coordinator.py:2289/2310/2319` | prune on read removed in `location_moves_since` and the truncation read | aged move absent without append |
| C13 | LOW | `transit_validator.py:1169`, `:1227` | prune-on-append removed (read prunes anyway); `get_crossing` prune removed (returns an aged record) | aged `get_crossing` returns None |
| C14 | LOW | `residency.py:287` | `unsub` not idempotent (counter double-decrements) | double unsub keeps `g1_subscribers` correct |
| C15 | LOW | `signals.py:192` | `subscribe_person_arriving` calls `cb(None)` for a malformed payload | malformed raw payload not delivered |
| C16 | LOW | `signals.py:89` | `from_signal` object branch drops `ts` | object payload with `ts` |
| C17 | LOW | `transit_validator.py:1066` / `:1282` | no-tracker `amend_crossing` returns True; payload `person_id` not taken from the amended record | return value and `person_id` assertions |
| C18 | LOW | `presence.py:6193-6195`, `const.py:6676` | `move_log_size` forced 0; `PERSON_LOCATION_MOVES_MAX` 256->128 | size in diagnostics; constant pin (plan sized it pre-D0) |
| C19 | LOW | `presence.py:6158`, `census_view.py` non-string check | non-str class: equivalent in effect (`dict.get` / `in` on hashables); only unhashable differs, caught by the `except` | none (note only) |
| C20 | LOW | `diagnostics.py:36,38,46`, `signals.py:146` | never-raise `except` narrowed to `KeyError` | raising `hass.data` / presence in diagnostics; raising counter |

### Equivalent mutants (no action)
- `transit_validator.py:1005` forbidden-key set entries (5 mutations) and the forbidden check (`:1072`): every forbidden key is also absent from the amendable set, so the unknown-key check rejects it (`ValueError`, different message). Redundant defence in depth; behaviour identical. The unknown-key check itself is RED.
- `signals.py:103` `_FACE_LATCH_KEY` string renamed: only `signals.py` may hold the literal (guard R11 pins that), so renaming is unobservable.
- Guard: a mutation inside `PresenceCoordinator.view_for_class` adding a raw `house_census_view` is exempt by design (`R5_OWNER_DELEGATES`, `_layer_guard_engine.py:258-261`).

## Guard (`test_person_awareness_layer_guard.py`)
Real reverts to the pre-3a form, run against `test_guard_matches_provisional_allowlist`, all RED with the rule named:
raw `SIGNAL_PERSON_ARRIVING` send at geofence / camera_face / BLE -> `R6` (+ stale `R13` pin); raw residency connect in `crossing_vision.py` (literal and by name) -> `R10`; `pc._pre_arrival_enabled = value` in `hvac.py` -> `R1`; `arrival_edges.door_entry_areas` and perimeter `_near_areas` private reads -> `R1` x2 each; raw `SIGNAL_EGRESS_RECORD_AMENDED` send in the exit backfill -> `R6`; raw `"face_latch_callbacks"` register and read -> `R11`; private `_last_face_*` writes -> `R1` x2; `"person." + entity_id` -> `R12`; PLB non-literal view -> `R5`; geofence payload without `source` -> `R13` "missing source" (never allowlistable); person_sighting f-string removed without lowering the total -> stale `R12` row (ratchet).
Injected leaks (22) into an in-memory copy of a clean module, all CAUGHT with the rule named: R1 (call and getattr), R2, R3, R4, R5 (view and `min_confidence`), R6 (aliased signal and bus fire), R7 (setattr and `dataclasses.replace`/ctor), R8 (inline and const), R9, R10 (raw connect and `async_add_listener`), R11, R12 (`+` and `%`), R13 (missing source and feeder), R14.
Caveat (LOW): `census_view.py` and `arrival_edges.py` sit in the engine's exempt-module list (`_layer_guard_engine.py:55-56`), so R2/R3/R4 (and R7 for `census_view.py`) injected there are NOT caught; the same injections into 48 other clean modules are. By design, but it means a leak added to those two files is invisible.

## Verdict: FIX-REQUIRED (tests only)
No production defect found; every named site except the GREEN rows above is pinned by a specific RED test. Must-fix before ship (tests, ~10 lines each): C1, C2 (census class gate is the safety rule: notification must not read awareness), C3 (operator-named "both readers"), C4 (diagnostics "never entity states"), C5, C6, C7, C8. LOWs C9-C20 fix in-cycle per standing policy. New drill-style tests need no `source_mutation` marker (they are in-process).
Files: `/Users/okosisi/Code/universal-room-automation/.claude/worktrees/agent-aa1d30dcca08c1676/docs/reviews/code-review/v_layer_ship3a_C.md`.
