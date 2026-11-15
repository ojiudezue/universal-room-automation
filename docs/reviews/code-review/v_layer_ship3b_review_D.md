# Layer ship 3b, review D: adversarial completeness, diff-blind

Branch `feature/layer-ship3b` (worktree `.claude/worktrees/builder-ship3b`), base develop `d0a38ad9`, three-dot diff.
Spec: `c86b6c74:docs/planning/PLANNING_person_awareness_layer_ship3.md` §4 (INV-DEAD-INPUT, INV-DEAD-CAMERA), §6.
Read first, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger through #41) and
`docs/architecture/SENSOR_FLEET_CLASSES.md`. No ledger claim is re-asserted here. No pytest run (instructed).

## Reader re-enumeration (whole integration, not the diff)

Grep `stream_view|stream_dead|_stream_released|camera_stream_health.|own_camera_entity_for_input|camera_hold_expired|unavailable_held`:

| Reader | Site | Routes through device rule? |
|---|---|---|
| Room S1 exclusion + override drop | `coordinator.py:2621-2629`, `:2772-2781` | yes (tracker `evaluate`, device key) |
| Substrate `_kind_on_now` / `_is_live_end` / recheck | `occupancy_substrate.py:316-386, 890, 942` | yes (`input_stream_view`) |
| Night limb / fan gate / D4d label | `presence.py:4373, 4326, 4546` | yes (`input_stream_view` / `input_stream_dead`) |
| Zone camera tier | `presence.py:828, 981` | yes (`entity_stream_view`) |
| HVAC D6 Source 3 | `presence.py:2468` | yes (`entity_stream_dead`; picks in U via `zone_camera_entities`, same `{**data, **options}` zones source as `hvac_zones.py:515-540`) |
| Census S5/S6/S7 | `camera_census.py:2068, 2254, 6277` → `_stream_view_set` `:2796-2806` | yes (`entity_stream_view(census=True)`) |
| Census stuck-camera watchdog | `camera_census.py:2989-3020` | no; need not: it can only discount a camera, never count a frozen one live (carded residual) |
| Ledger anchor | `crossing_vision.py:1168`, `crossing_ledger.py:132` | yes (`entity_stream_view`) |
| Fan veto | `fan_veto.py:263, 462-476` | yes (`entity_stream_dead`) |

House readers fold rooms first, house tracker only on a None fold and only for U ∪ sticky
(`camera_stream_health.py:1008-1037`, `camera_twin_health.py:503-524`). No reader re-derives camera availability.
Name inference: none new. Only `startswith("camera.")` (domain test) in `camera_resolver.py:890`,
`camera_twin_health.py:306, 519, 990`. W1 pairing compares the Frigate identifier to the candidate's registry
DEVICE-name slug (`camera_resolver.py:1709-1744`, pre-existing, plan-sanctioned, guarded by the registry-platform
check `camera_stream_health.py:760-775`); not refiled.

## Findings

### D-M1 (MEDIUM) Same-tick S1 + S2 double HIGH after latch-after-send. Bug class: computed-but-not-consumed (#53) / handoff race.
`camera_stream_health.py:377-396`. `evaluate` computes the S2 candidates (`_evaluate_hold_pages`) and then the S1
candidates in the same call. The S1 skip reads `self._hold_paged` (`:387`), which 3b now fills only in `mark_paged`,
after the async send returns. Nothing blocks S1 on an S2 candidate of the same key emitted this tick, or on an
in-flight S2 (`_inflight` is checked per kind, `:393` checks `(NM_KIND, eid)` only). Pre-3b the S2 latch was set
inside `_evaluate_hold_pages`, so the S1 loop saw it.
Repro (in-map group, owner-absent window, which the spec says must not give a second HIGH):
Frigate `camera.playroom_2` device + Protect playroom device (admitted W1 pair), room Playroom presence list holds
`binary_sensor.playroom_person_occupancy_2`. Both NVRs lose the camera at t0. Owner sends S2 `(page_key,)` at
t0+900 s. At t0+1900 s the CM entry reloads (owner torn down, `twin_owner` None → `POLICY_PAGE`). The room's
`_hold_paged` is empty (it was suppressed), its stamp is 1900 s old, so its first tick returns an S2 candidate AND an
S1 candidate (1900 ≥ `NM_AFTER` 1800). S2 → ALREADY_SENT (same pure key, fine); S1 key `(Playroom, input)` → SENT:
a second HIGH in one episode. Same shape with no owner involved: a singleton device whose S2 send returns NOT_SENT
(NM not yet up / exception) across the 900 s→1800 s window, and a pair dissolve after 1800 s.
Fix: in the S1 loop also skip a key that has an S2 candidate this tick or `(NM_KIND_HOLD_RELEASED, key)` in
`_inflight`.

### D-M2 (MEDIUM) Disabled room entry removes a camera from U with no watcher. Bug class: one-missed-site (#53), scope.
`camera_twin_health.py:431-444` iterates `hass.config_entries.async_entries(DOMAIN)`, which includes disabled entries
(HA `config_entries.py:2073-2093`, `include_disabled=True` default). A disabled room has no coordinator, so
`_room_coordinators` never sees it, yet its inputs' devices enter Wr and are subtracted from U (`:448-452`).
Repro: room entry "Playroom" disabled in the HA UI; its presence list holds `binary_sensor.playroom_person_occupancy_2`;
the census interior list resolves the same sensor. The playroom Frigate stream dies with a body in view: no room
answers, the house tracker never watches it (not in U), `entity_stream_view` → None, so the census counts the frozen
reading indefinitely (INV-DEAD-INPUT broken: never held, never released). If the device has no W1 twin nobody pages
either (room absent, owner pages only U singletons: INV-DEAD-CAMERA broken). Identical to develop in effect, but U
exists precisely to cover "cameras no room watches".
Fix: skip entries with `disabled_by` (a reload keeps `disabled_by` None, so the anti-flap property holds); consider
`ConfigEntryState.SETUP_ERROR` too.

### D-M3 (MEDIUM) No camera manager: rooms suppress, owner never pages. Bug class: suppression without discharge.
`camera_twin_health.py:405-416` runs `_evaluate_groups` only when `_sets_ready`, which needs
`hass.data[DOMAIN]["camera_manager"]` (`:425-427`). `room_page_policy` (`camera_stream_health.py:924-945`) returns
SUPPRESS for any in-map device once `map_ready`, independent of `_sets_ready`. The camera manager is absent for the
life of the CM entry when `CameraIntegrationManager.async_discover` raises (`__init__.py:2937-2948`, caught at
`:3124`), while the owner is still created at `__init__.py:5450-5462` and the map built from the registry.
Repro: a discovery exception at CM setup; Frigate `binary_sensor.playroom_person_occupancy_2` (configured room input,
in-map pair) loses both NVRs: the room holds and releases correctly, but no S2/S1 page from anyone, ever, until a CM
reload. Fix: `room_page_policy` returns PAGE (or DEFER bounded by the settle) when the owner is not `_sets_ready`, or
the owner evaluates map groups with Wr from room configs without the camera-manager gate.

### D-L1 (LOW, latent) Held-from-t0 lost for a non-input entity on a watched device.
`entity_stream_view` camera route (`camera_stream_health.py:1152-1158`) gives HELD only once the device is dead past
the grace; the D-M1 (S2) unavailable-held classifier is per INPUT (`:418-453`). U excludes every entity whose device is
in Wr (`camera_twin_health.py:448-452`), so a census / zone entity on a watched device that is not itself a room input
or override extra reads `unavailable` = missing for 0-120 s after a device disconnect. Reachable only if a room watches
a different entity of that device (e.g. a Protect `_motion` filed in a room of another area). No live shape found.

### D-L2 (LOW) Caps 0 + owner-absent window: owner S1 then room S1, two HIGHs.
Owner S1 key `("<group>", k)` (`camera_twin_health.py:773`); room S1 key `(room, input)`. The owner adopts room keys
(`:652`), rooms never check the owner's key. Both caps 0 (rung-1 kill semantics), outage > `NM_AFTER`, CM reload →
second HIGH. Also a device moving from U into Wr mid-outage under caps 0.

### D-L3 (LOW, pre-existing) Room S1 before S2 when `NM_AFTER` < min cap gives two HIGHs for room-paged devices.
Spec keeps room order unchanged; noted only.

## Cleared

- Never a twin's answer: `_key_for_camera` (`camera_stream_health.py:232-240`) and `_own_camera_route` (`:1065-1076`) are
  per own device; holds because a twin's camera is on another device and matches no member set.
- Multi-channel Protect (2/3/4 channels): `_key_reading` (`:242-262`) any-member-live; disabled channels excluded by
  `enabled_camera_entities_for_device` (`camera_resolver.py:867-893`); re-read on registry invalidation.
- Twin member disabled / never set up: a side with no enabled camera fails `twin_pair_admissible` (`:767-770`), so the
  Frigate device pages as a singleton; a member never loaded (restored placeholders) counts lost after
  `CAMERA_TWIN_BOOT_SETTLE_S` (`camera_twin_health.py:549-561`), so an all-lost group still pages.
- Group gate and clock: `_maybe_send_s2` requires `_group_dead` and latest loss + cap (`:714-744`); one HIGH per episode
  via `_group_high_sent`, cleared only at episode end (`:842-868`).
- Knob extremes: grace > cap releases at grace (expired check `>=` on dead inputs only, `:366-373`); hold 0 with census
  900 pages at 900; settle 0 / large only shifts never-live loss (named in spec).

## Invariant checklist

| Invariant | Verdict |
|---|---|
| INV-DEAD-INPUT | LEAK (D-M2; D-L1 latent) |
| INV-DEAD-CAMERA, fires only when all lost | PASS |
| INV-DEAD-CAMERA, always fires when all lost | LEAK (D-M2, D-M3) |
| INV-DEAD-CAMERA, at most one HIGH per episode | LEAK (D-M1; D-L2 at caps 0) |

## Verdict

**FIX-REQUIRED**: D-M1, D-M2, D-M3 (each small). LOWs per fix-LOWs-in-cycle.
