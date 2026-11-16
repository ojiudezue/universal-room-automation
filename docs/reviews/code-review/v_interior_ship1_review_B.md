# Interior vision ship 1: Review B (integration, lifecycle, invariant integrity)

Branch `feature/interior-vision-d1` at 9931a001; diff `git diff 7b818ce1 9931a001` (7b818ce1 is an ancestor of develop).
Tier 3, framing B. Read-only.

I read `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `docs/architecture/SENSOR_FLEET_CLASSES.md` completely before
reviewing. I re-assert nothing from the corrections ledger. I also read the contract and the plan sections this review relies on.

Targeted run (cycle files + guard + golden + reload hazard): `227 passed, 1 skipped` (`PYTHONDONTWRITEBYTECODE=1`).

**Verdict: FIX-REQUIRED (two MEDIUMs, both cheap). INV-IV-AWAY holds.**

## INV-IV-AWAY: PASS

- **`_run_inference`, `_handle_census_update`, `_periodic_inference`.** The presence diff adds only `get_room_sightings`,
  `get_last_path_records` and one diagnostics key (`presence.py:6043-6060`, `:6242-6247`). Nothing new is called from the
  inference or census paths.
- **`PersonCensus.area_evidence()` is a pure copy.** It reads only through `getattr` and builds new dicts
  (`camera_census.py:2717-2740`). It writes nothing, and its only caller is the producer's own tick.
- **The interior work runs on its own timer.** `async_track_time_interval` is registered in `_setup_interior`, which
  `async_setup` calls (`person_sighting.py:~1218`). It never runs from a census tick or from inference. Every read on the
  tick is side-effect free: `entity_stream_view` (`camera_stream_health.py:1201`), `physical_camera_dead`,
  `interior_camera_entities`, `persons_in_room` → `get_room_occupants` / `phone_trustworthy`, and `get_crossings_since`
  (prunes only its own ring).
- **The golden variant is genuine.** The harness hook runs `after_census_tick` inside the `n_calls` window
  (`_census_vision_harness.py:224-233`), so any inference trigger it caused would be captured. Variant `interior_records_on`
  makes three checks: two real groups over the rig registry, a body count of 3 actually seen, and `record_builds` counting
  the real timer as well. Residual (LOW-4): no entry crossing is driven, so `_path_tick` and `_log_path_row` sit idle under
  the golden.
- **The switch, cap and admission values are inert.** `switch.ura_interior_vision` writes `hass.data[INTERIOR_VISION_SWITCH_HASS_KEY]`,
  and nothing in ship 1 reads it. `INTERIOR_ROOM_RECORDS_ENABLED` gates only the producer timer and the tick.

## Findings

### MEDIUM-1: interior groups are not rebuilt when a room's type or area changes, so a room changed to `bedroom` keeps getting records (INV-IV-SCOPE staleness; Bug Class: stale cache / #53 one-missed-site)
- `person_sighting.py:~1001-1004`: `sig = (tuple(interior), id(resolver))`. Groups are rebuilt only when the census interior
  list or the resolver object changes.
- The resolver is invalidated only by entity and device registry events (`camera_census.py:544-560`).
- The two room facts are read once per rebuild: room type from `_room_entries()` (`:1041`), and room by area from presence
  `_room_area_ids` (`:342`).
- `_on_room_entry_lifecycle` calls `rebind()` but never resets `_interior_sig`.
- **Repro:** the Playroom (camera group in area `playroom`, type `common_area`) has records. Change its room type to
  `bedroom` in the options flow. The room entry reloads; no registry event fires, and neither the interior list nor the
  resolver changes. Records keep publishing Playroom bodies on `sensor.ura_interior_awareness` until restart.
- **The same staleness affects:**
  - a new URA room created for an area that was `no_room`;
  - a room renamed or re-areaed.
- **Why it matters now:** ship 1 is counts only, but later ships attach model frames to these same groups. The privacy fence
  must not depend on a restart.
- **Fix:** add `tuple(sorted((r, m.get(CONF_AREA_ID), m.get(CONF_ROOM_TYPE)) for r, m in self._room_entries().items()))` and
  presence `_room_area_ids` to `sig`, or set `self._interior_sig = None` in the lifecycle rebind. Add a test that flips the
  type and asserts `excluded_room_type` on the next tick.

### MEDIUM-2: R15 catches only calls to the five named methods. A trust reader can get the same records with zero guard hits (contract §6 enforcement gap; Bug Class #62 hollow anchor)
I verified each case with `_snippet_hits` (script
`/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/ivb_probe_r15b.py`).

| Code placed in `domain_coordinators/security.py` | Guard hits |
|---|---|
| `m.coordinators['presence']._person_sightings.interior_tick()` | **none**. `interior_tick` is public, returns the `RoomSighting` tuple and is unpinned; `._person_sightings` trips no R1. |
| `p._person_sightings._room_sightings` | R2 (caught) |
| `p._person_sightings.get_room_sightings()` | R15 (caught) |
| `census.area_evidence()['by_entity']` (contract: "layer members only") | **none** |
| `g = p.get_room_sightings; g()` | none (static limit) |
| `hass.states.get('sensor.ura_interior_awareness').attributes['rooms']` | none (generic display-entity limit, pre-existing) |

- **Fix (cheap):**
  - pin `interior_tick` and `_emit_unnamed` in `PINNED_READERS`, to `PersonSightingProducer._on_interior_interval` and the
    owner class; or make `interior_tick` return None and have tests read `get_room_sightings()`;
  - pin `area_evidence` to `person_sighting.py` `PersonSightingProducer.*`;
  - add both as drills next to `iv_trust_reader`.
- **Known and accepted:** the alias form and the state-read form are generic static-analysis limits. The review record
  should name them rather than claim "no trust reader possible".
- No live trust reader exists today. `grep _person_sightings|interior_tick|area_evidence` outside presence and the producer
  returns nothing.

### LOW-1: the interior on-edge listener and the record timer run whatever the Face Recognition switch and `FACE_SIGHTING_ENABLED` say
`_setup_interior` runs before the `if not self.enabled: return` check (`person_sighting.py` `async_setup`). That is by
design: the records are body counts, and `named` faces come only from `_last_sightings`, which those switches already gate.
Note it in the doc: with Face Recognition OFF the records still publish NVR counts.

### LOW-2: path-row tasks are cancelled at teardown, not drained (Bug Class: untracked background tasks, handled but lossy)
- `_teardown_interior` cancels `_interior_tasks` (`person_sighting.py:~939`). A `log_memory_episode` cancelled mid-enqueue
  drops that row.
- Residency's precedent drains instead: it sets the flag first, then gathers at the end of teardown (presence `async_teardown`).
- Rate: about one row per mapped entry, so the loss is at most a row per reload.
- The two new `_fire` trip-wire NM tasks are untracked, the same as the producer's pre-existing `_fire` (`:865`). This is
  pre-existing in pattern.

### LOW-3: the crossing cursor assumes the ring is appended in `ts` order
- `_new_entries` advances `_crossing_cursor` to the max `ts` seen. `CrossingRecord.ts` is the trigger time (`dt_util.now()`
  at `transit_validator.py:1641/1689`), but the record is appended at resolution, 45 s later through `async_call_later`
  (`:1666/:1717`).
- That is safe today: both handlers use the same `ENTRY_WINDOW_SECONDS`, and `_resolve_direction` has no `await` before
  `_record_crossing` (`:2373-2515`). Append order is therefore `ts` order, and same-`ts` duplicates are deduped by
  `_crossing_seen_at_cursor`.
- If a future change gives a handler a different delay, or adds an await, a late record with an older `ts` is skipped
  silently.
- Suggest a comment, or deduping by `source_ref` over `now - EGRESS_CROSSING_RING_MAX_AGE_S`.
- No crossing listener was added (pull only, as the plan requires). `inward_path_edges` (`transit_validator.py:2846-2861`)
  is a pure read of `path_map`.

### LOW-4: the golden does not drive D5
See INV-IV-AWAY above. Add one entry crossing on a mapped door to the `interior_records_on` variant so `_path_tick` and
the DB-row path run inside the trigger window.

### LOW-5: the state-of-play marker correction is incomplete (docs)
- **The claim holds as far as it goes.** All nine branches it names are ancestors of 746e6751 (`git merge-base
  --is-ancestor`); the commit's subject is "v5.108.25: Layer ship 3b". The live manifest at
  `/Users/okosisi/ha-config/custom_components/universal_room_automation/manifest.json` reads `v5.108.25`. No local tag
  `v5.108.25` exists, so cite the commit, not a tag.
- **Stale markers left inside the commit's own scope:**
  - §4 zone-tier bullet: S2 "not deployed" (line 494);
  - §10 #41: ship 3b "NOT deployed" (line 1082).
- **Further branches that are also ancestors of 746e6751 but still read "NOT deployed":**

  | Branch | Line |
  |---|---|
  | `feature/forms-release-1` | 5 |
  | `fix/ble-person-registry-resolve` | 318 |
  | `feature/phone-left-behind-camera` | 399 |
  | `feature/lock-release-arriving` | 97, 733 |
  | `feature/house-state-step1a` | 97, 98, 113 |
  | `fix/fan-noise-running-rejection` | 589 |
  | `fix/occupancy-source-follows-capability` | 881 |

  Fix them in the same commit (presence doc owner rule).

## Lifecycle checklist

| Item | Verdict | Evidence |
|---|---|---|
| Timer registered and removed | PASS | `_setup_interior` / `_teardown_interior`; tick returns at once after teardown (`interior_tick` checks `_interior_torn_down`) |
| On-edge listener | PASS | bound only on a group rebuild; previous unsub released first; skipped after teardown (`_bind_onedge_listener`); O(1) append, no await |
| Ring and RAM bounds | PASS | `OnEdgeRing` maxlen 512; `_bodies_hist` maxlen derived; `_path_records` maxlen 20; `_iv_*` deques pruned to 24 h (at most 8,640 per deque); `_open_paths` closes after a finite window (max_hops × `window_s` + pad); `_entered_via` TTL-pruned |
| Teardown while a tick runs | PASS | tick is a sync `@callback` with no await, so it cannot interleave |
| Reload / restart | PASS (RAM by design) | a new producer per `_setup_person_sightings` (prior torn down, `presence.py:5915-5922`); cursor = setup time, so pre-setup crossings are ignored |
| DB writes | PASS | one `interior_path` row per closed path, `dedup_source_ref=True`, `window_dedup=False`, through `log_memory_episode` (the write-queue DAO); no per-tick write, so no flood shape |
| Sensor polling / recorder | PASS | `sensor.ura_interior_awareness` is polled; every attribute (`rooms`, `last_path`, `records_as_of`) is in `_unrecorded_attributes`; integer state with `MEASUREMENT` |
| `CONF_INTERIOR_VISION_ENABLED` in `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` | PASS | field on the integration `camera_census` options step (`config_flow.py:5036`; strings and en.json on `camera_census`); the switch reads it only while the hass.data key is unset (`switch.py` `_default` / `is_on`), so no cached consumer needs a discharge; a save that changes only this key suppresses reload correctly (`__init__.py:8925`); test-namespace alias and allowlist set updated (`test_reload_watchdog_hazard.py`) |
| `persons_in_room` lazy import | PASS | function-local import of `_ble_corroboration.phone_trustworthy` (no cycle); fail-open; no existing reader migrated |
| Presence delegates | PASS | never raise; `()` when there is no producer |

## Guard reconciliation at merge (deltas)

- **This branch:** `LAYER_ALLOWLIST_TOTAL` 259 → 259 (Δ0), `len(A.ROWS)` 231 → 231 (Δ0), `LISTED` 29 (Δ0). R15 hits on the
  real tree: 0 (outside the total). Develop at 340bfe7f is also 259 / 231 / 29.
- **The music repair:** Δ−3 on both counts (259 → 256, 231 → 228).
- **Merged expectation:** 256 / 228 / 29, R15 = 0. The branch adds no rows, so take develop's numbers verbatim.
- **After merge:** re-run `test_person_awareness_layer_guard.py`. The branch edits files the music rows may sit in
  (`sensor.py`, `presence.py`), so confirm that no row's `max` was consumed by a line the branch added. MEDIUM-2's fix adds
  pins, not rows: still Δ0 to the total.

## Must-fix
1. MEDIUM-1: rebuild the groups when room type, area or name changes, with a test.
2. MEDIUM-2: pin `interior_tick` / `_emit_unnamed` and `area_evidence`, with two drills; name the static limits.

Fold in, by the fix-LOWs rule: LOW-5 (doc markers), LOW-4 (golden D5 entry), and the LOW-3 comment.

| Severity | Found |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 2 |
| LOW | 5 |
