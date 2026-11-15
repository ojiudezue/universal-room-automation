# Layer ship 3b review, framing A (local correctness)

Branch `feature/layer-ship3b` (cc74f59c, 6bac1624, dacab04c). Base develop `d0a38ad9`, which is the merge-base of HEAD (checked with `git merge-base`). Spec: `PLANNING_person_awareness_layer_ship3.md` rev 3.8 §6, §12 and §17 @ c86b6c74.

Read completely before review: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (with the §10 ledger, #41 included), `docs/architecture/SENSOR_FLEET_CLASSES.md`, and the bug-class index of `docs/QUALITY_CONTEXT.md`. No ledger claim is re-asserted here. pytest was not run (another agent owns the suite).

## Findings

| # | Sev | Site | Finding / repro | Class |
|---|---|---|---|---|
| A-M1 | MEDIUM | `domain_coordinators/camera_stream_health.py:943` (`room_page_policy`) with `camera_twin_health.py:403-416,424-427` | Rooms get SUPPRESS whenever `owner.map_ready and owner.in_map(dev)`. They never check whether the owner can actually page that group. The map is built in `async_setup` whether or not the camera manager exists, but `_compute_sets` keeps `_sets_ready=False` (and so never runs `_evaluate_groups`) until `hass.data[DOMAIN]["camera_manager"]` exists. **Repro:** `CameraIntegrationManager.async_discover` raises at `__init__.py:2938-2948`, so the key is never set (it is never popped either, so this is permanent until a restart). All 17 admitted pairs are in the map. A room whose presence list holds the Frigate `*_person_occupancy_2` of a paired camera (e.g. Playroom) suppresses its S1 and S2. Both NVRs lose the camera for hours and nothing pages. Spec §6.6 says "an empty or failed map makes rooms page (no silent outage)", and this is the same failure from a different cause. The same silence follows if the owner's tick returns early on `er is None` (`:403-404`). Fix: return SUPPRESS only when the owner is in a state where it pages, i.e. `_sets_ready` and the device's group is in `_scope_groups()`. Otherwise return PAGE. | #53 (one-missed-site: suppression without a discharge) |
| A-L1 | LOW | `camera_twin_health.py:412-414` | The house tracker's resolution is never invalidated on entity-registry events. `invalidate()` is called on room trackers only. So `_key_members` for a U device stays stale until the U input set changes. **Repro:** the foyer Protect device's only live channel is disabled and another channel is enabled. The house tracker keeps the old member set, the device reads no-opinion or dead, and the foyer census entry gets held although a channel is live. Spec §6.1 says to re-read members "on every entity-registry invalidation". Fix: call `self._unwatched_tracker.invalidate()` from `_on_entity_registry_event` (or in `_rebuild`). | #53 |
| A-L2 | LOW | `camera_twin_health.py:809-840` | The MEDIUM fires when `not dead`, not when another member is LIVE. **Repro:** NVR A loses the camera at t=0 and NVR B loses it at t=850 s. At t=900 s A has passed the cap and B is not lost (lost at 970 s), so the MEDIUM goes out saying "B still sees it" while B is down. The HIGH follows correctly at 1750 s. Text only. Fix: also require `self._group_alive(group)`. | text accuracy |
| A-L3 | LOW | `camera_stream_health.py:500-505, 518-521` | `mark_paged` maps the S2 own-camera to its key through the CURRENT `_key_members`. If a resolution rebuild lands between `begin_send` and the async send result, and it changes the device's member set (a channel enabled or disabled mid-send), then `_key_for_camera` returns None and the latch lands under the camera id, not the device id. Next tick: `key not in dead_keys` produces a spurious LOW (`hold_recoveries`), and then a fresh HIGH candidate. This needs a registry edit inside the send window. Fix: freeze the key at `begin_send` (store pid by (kind, ident)). | #57 |
| A-L4 | LOW | `coordinator.py:2803-2820`, `camera_stream_health.py:817-823` | If the device-registry getter fails, the room's `page_camera_key` falls back to the device's own camera (`twin_pair_for_device` returns {dev} when `device_registry is None`), while the owner uses the Frigate member's camera. The two S2 keys differ, so two HIGHs can go out for one outage (owner-absent window only, because rooms are suppressed for in-map devices). Fault path only. | #63 |
| A-I1 | INFO | `camera_stream_health.py:837-851`, `camera_twin_health.py:611-616, 672-677` | `page_camera_key` rebuilds the whole twin map (a fresh `CameraResolver` over the full registry) on every call. The adoption sweep calls it once per scope group (~17) after every rebuild, synchronously on the loop. This is correct; it is noted for framing B. |
| A-I2 | INFO | invariant wording | INV-DEAD-CAMERA as briefed says group death "only" drives the camera-down page, the hold-released alarm and the empty-house anchor block. The code (and spec §6.0, §6.8, the "charter drift #15 stays open for holds and the anchor" line) blocks the anchor on the per-DEVICE hold view (`entity_stream_view`), not on `physical_camera_dead`. For pages the invariant holds. For the anchor it holds only in the spec's sense (anchor code unchanged; no Tier-1 input on a multi-camera device or in U). The orchestrator should restate the invariant as "pages only", or confirm with the operator. |

## Checks that pass

- **Arithmetic and clocks.**
  - Grace. The reader rule (`camera_stream_health.py:319-357`) is dead only on a DEAD-READ tick with the stamp at or past the grace. A no-opinion gap restarts the stamp only if it lasted longer than the grace. This is the old continuity rule, keyed by device.
  - Loss rule (`camera_twin_health.py:530-561`). No-opinion counts toward loss. A device seen real is lost after the grace. A device that has been no-opinion since setup is lost only at or after setup + 600 s. The split from the reader rule is deliberate (#63, as specified).
  - Group clock (`:563-567, 725-726`) runs from the latest member's not-live stamp plus min(positive caps). Owner S1 runs only when no cap is positive (`:699-702`). Both caps are 900 s (`const.py:6071, 6080`).
  - The local-day `today` comes from `dt_util.now()`.
- **None and missing values.** Every registry and state read is guarded. An unresolved input, no device or no camera all mean no opinion. `physical_camera_dead` with no owner returns None. A device whose cameras are all disabled has no members: it stamps not-live, but the next rebuild dissolves its pair (`twin_pair_admissible` needs a camera on each side).
- **Page key.**
  - It is pure: `page_camera_key` goes through `twin_pair_for_device` and `build_twin_map`, never the owner's map.
  - The room S2 key and the owner key match (Frigate member camera). The episode key is frozen at `_start_episode`. Room S1 stays `(room, input)`. Owner S1 is `("<group>", key)`.
- **Latching.**
  - `mark_paged` runs only after SENT or ALREADY_SENT (`send_page_and_mark`, `camera_stream_health.py:948-973`). `evaluate` no longer writes any latch.
  - A DEFER or SUPPRESS result skips `begin_send`, so the candidate comes back next tick.
  - Owner latches go through `on_sent` (`camera_twin_health.py:895-900`).
  - `fire_stuck_signal_ex` returns ALREADY_SENT exactly when `(kind, key)` is in `_STUCK_SIGNAL_NOTIFIED`, on any date. The `_LATCHES == today` and not-notified case cannot occur, because `fire_stuck_signal_recovered` pops both together (`_stuck_signal_nm.py:347-353`). NOT_SENT (NM missing, kill switch, exception) retries.
- **Kill-switch matrix (§6.7).**
  - Master off: no dead input; the owner tick returns and `_sets_ready` goes False, so the house fallback answers None.
  - Twin rule off: `build_twin_map` returns {}, `in_map` is False, rooms page.
  - Stamps knob: gates house answers (`house_tracker_for`) and U one-member pages.
  - Device level off: per entity in rooms, the house tracker and `_own_camera_route`; the owner keeps device liveness.
  - Notice knob: gates the MEDIUM. Caps 0: no S2, no MEDIUM (`cap is None`), owner S1 only.
  - Every row and bullet matches.
- **Registry only.**
  - Devices come from `entity_registry.async_get(...).device_id`, members from `enabled_camera_entities_for_device`, and the NVR check from the registry `platform`. Page texts use `device_platform`.
  - The only string tests are the `camera.` domain prefix and HA's `restored` attribute.
  - W1 pairing (pre-existing, chosen by the plan) compares the Frigate identifier's object name with the sibling's registry device name, with uniqueness and platform guards. That is registry data, not an entity-id guess.
- **One-camera golden (INV-DEAD-INPUT).** For one enabled camera, `resolve_input_device` returns the device and its single member. `dead[eid]` names that camera, and `_key_reading` gives the same live, unavailable or no-opinion value as the old per-camera read. `derived` and the reasons match `own_camera_entity_for_input` except for `multi_camera`. PASS.
- **Mixed members (§6.2).** {restored, unavailable} and {unknown, unavailable} read DEAD-READ; {live, unavailable} reads live (`member_reading`, `_key_reading`). The classifier reads liveness by the same key the stamp used. PASS.
- **Owner never in the room fold.** `_room_coordinators` scans `_camera_stream_health`; the owner's tracker is `_unwatched_tracker`. PASS.

## Builder deviations

| Deviation | Verdict |
|---|---|
| M25 anchor: the deferral is bounded by the settle | OK. In practice it never engages, because `map_ready` is set synchronously by the first `_rebuild()` before any await (`camera_twin_health.py:1023-1024, 177-178`). |
| M15 split (`fire_stuck_signal_ex` beside the bool API) | OK. Existing callers are unchanged. |
| Registry errors keep the old map | OK. `build_twin_map` reads both registries first so an error raises (`camera_stream_health.py:792-793`). The failure sets `map_stale_since` and `map_ready`. |
| The takeover episode ends only after a member has been LIVE for one grace | OK, and better than the spec's literal "gate False": immature owner stamps after a reload cannot end an adopted episode early. Bounded. |
| Adoption sweep only after a rebuild | OK. Rooms can latch an in-map device only while the owner is absent or the device is out of the map, and both cases end with a rebuild. |
| U one-member groups gated on the stamps knob | OK. With stamps off no hold exists, so "inputs released" would be false text. Row 3 is still honoured. |
| Runtime knob check (`_knob` / `getattr(const, ...)`) | OK. |

## Invariant checklist

- INV-DEAD-INPUT: PASS (golden equivalence, see above).
- INV-DEAD-CAMERA: PASS for pages and the hold-released alarm, apart from A-M1, where pages are silenced rather than wrongly sent. For the anchor see A-I2.
- INV-ANCHOR: PASS. `crossing_vision.py` is untouched by the diff, and no Tier-1 input sits on a multi-camera device or in U.

## Verdict

**FIX-REQUIRED.** One must-fix: **A-M1**. `room_page_policy` must not return SUPPRESS unless the owner will page the group (`_sets_ready` and the group in scope). Fix the LOWs in the same pass if cheap: A-L1 (invalidate the house tracker on entity-registry events), A-L2 (MEDIUM needs a live member), A-L3 (freeze the latch key at `begin_send`).
