# PLANNING — Room-Camera Fusion (per-room camera surface + cross-integration discovery + fused CameraPersonDetectedSensor)

**Cycle date:** 2026-08-01
**Operator directive:** "Plan it." (2026-08-01) with 5 verbatim design amendments (see §Operator-specified design).
**Branch (proposed):** `feature/room-camera-fusion`
**Tier (proposed):** **Tier 3** — four framing-disjoint reviews + operator checkpoint (justification in §Tier classification).
**Harden bench:** Study A (the sole current member of `CAMERA_COVERED_ROOMS`, `const.py:666`).

---

## 1. Institutional context verified (MANDATORY — proof-of-work)

### 1.1 Files read end-to-end during scoping
- `custom_components/universal_room_automation/camera_census.py` (2723 lines; partial-read through line ~1341, plus targeted greps of the rest). Load-bearing surfaces: `CameraIntegrationManager` (l.182–709), `PersonCensus.__init__` (l.742–825), `_calculate_house_census` (l.981–1219), `_calculate_property_census`, dedup helpers, stuck-signal watchdog.
- `custom_components/universal_room_automation/__init__.py` l.271–347 — the v3.4.5 room→integration camera migration.
- `custom_components/universal_room_automation/binary_sensor.py` l.1084–1132 — `CameraPersonDetectedSensor` (v3.5.0 per-room sensor).
- `custom_components/universal_room_automation/fan_veto.py` l.245–290 — `_has_camera_person`, `_room_has_trusted_presence`, `CAMERA_COVERED_ROOMS` consumer.
- `custom_components/universal_room_automation/config_flow.py` l.1070–1150 (room sensors step), l.2846–2920 (integration `async_step_camera_census`).
- `custom_components/universal_room_automation/transit_validator.py` (grep-surveyed) — l.53, l.84, l.184–272 (camera_person_id / face freshness use).

### 1.2 Greps run

| Need | Grep | Result |
|---|---|---|
| Prior CONF for room cameras | `CONF_CAMERA_PERSON_ENTITIES` | `const.py:1025` = `"camera_person_entities"` (still legal identifier; today owned by INTEGRATION scope, v3.4.5 migration strips it from room scope). |
| Room-camera opt-out flag | `CONF_DISABLE_CAMERA_PRESENCE` | `const.py:354` — per-room boolean, strings at 110/125. REUSED by D3/D5 (respect existing opt-out). |
| Covered-rooms allowlist | `CAMERA_COVERED_ROOMS` | `const.py:666` = `frozenset({"Study A"})`. Consumed by `fan_veto._has_camera_person` (fan_veto.py:260). REPLACED by D5 (derive from config presence). |
| Entity→device resolution | `resolve_camera_entity` | `camera_census.py:221–351`. REUSED (same-device sensor discovery). |
| Cross-device / cross-integration | `resolve_cross_platform_sensors` | `camera_census.py:401–489`. REUSED — this IS the "same physical camera across integrations" mechanism the operator wants; already implemented via **name-stem sibling search** across the registry. Does NOT use device identifiers/connections today. |
| Frigate `person_count` sensor | `person_count_sensor` | `camera_census.py:322–328,616–617`. REUSED. |
| Face freshness / last_camera | `face_recognized` / `camera_person_id` | `transit_validator.py:53,184,247–272`; `_get_face_recognized_persons` in census. REUSED (D3 attribution). |
| Person-detect switch toggles | `switch.*_person_detect*` | Not yet enumerated in-repo; D4 acceptance requires live enumeration on Study-A hardware BEFORE build (Measure-Before-You-Build gate). |
| Fan-veto camera leg | `_has_camera_person` | `fan_veto.py:245–290`. REPLACED by D5 to key off the new fusion machinery. |
| Camera-covered census cross-check | `CameraPersonDetectedSensor` | `binary_sensor.py:1089–1132` — **v3.4.5 leftover: still reads `CONF_CAMERA_PERSON_ENTITIES` from ROOM config**, which the migration strips → today it's dormant on all rooms. D3 revives it under the new key. |
| Presence-coordinator camera signal | `camera_person_detected` | `domain_coordinators/presence.py:194` — signal kind exists. Verify wiring under D3 attrs. |

### 1.3 Prior planning docs / memory bodies consulted (headers skimmed)
- `docs/planning/PLANNING_zone_camera_person_only_guard*.md` — reference in `_humidity_gate.py:11` — recent Tier-3 closure on camera-person guarding; establishes the "camera-only trust needs review" precedent.
- Memory: `project_jaya_bedroom_occupancy_resolved.md`, `project_guest_mode_false_positive_backlog.md`, `feedback_incident_diagnosis_verify_before_mechanism.md` — camera trust-hierarchy sensitivity.
- CLAUDE.md rules invoked: **Institutional Context First**, **Measure Before You Build**, **Marginal-Benefit Decomposition**, **Numbers Get Knobs**, **Single User No Back-Compat**.

### 1.4 Prior-art audit VERDICT vs operator recollection

| Operator memory | Prior-art reality | Match? |
|---|---|---|
| "Native config is zone-level cameras (census)" | Correct — `async_step_camera_census` at integration scope; indoor/egress/perimeter (`config_flow.py:2846`). Room mapping via HA `area_id`. | **MATCH** |
| "Room-level camera field once existed and was migrated away" | Correct — v3.4.5 migration at `__init__.py:271–347` STRIPS `CONF_CAMERA_PERSON_ENTITIES` from room options after merging up. Any NEW room-level use of that exact key will be eaten on the next reload. | **MATCH — and confirms hazard** |
| "Config accepts any camera-related entity; URA resolves to the physical camera device" | **PARTIAL** — `resolve_camera_entity` (l.221) accepts a `camera.*` entity via `ent_reg.async_get(...).device_id`. It does **not** currently accept an arbitrary binary_sensor / person-detect entity as INPUT (though the device-based resolution would work identically if pointed at one — the method just needs to accept any domain and hop through the shared `device_id`). | **PARTIAL — needs D1** |
| "Discover ALL integrations exposing that same physical camera (Frigate + UniFi + Reolink)" | **PARTIAL** — `resolve_cross_platform_sensors` (l.401) already searches for sibling `_person_detected`/`_person_occupancy`/`_person_count`/`_person` entities on OTHER platforms — but by **name-stem heuristic** (`madrone_g6_entry` → strip suffix, search registry). It does NOT walk `device_registry.connections` (MAC) or `identifiers` (unique_id) to correlate the SAME physical camera across separate HA devices per integration. Cross-integration works TODAY only when the integrations happen to name entities with the same stem. | **PARTIAL — see §Device-correlation honesty below** |
| "Cross-correlation confidence signal (agreement raises confidence)" | Exists at census level — `_cross_validate_platforms` (l.1309) yields `CENSUS_AGREEMENT_BOTH/CLOSE/DISAGREE/SINGLE` with `CENSUS_CONFIDENCE_*` — but it's INTEGRATION-scoped across ALL cameras, not per-camera. No per-camera agreement attribute today. | **PARTIAL — D3 adds per-camera** |
| "Auto-enable person detection where disabled" | **NEW** — no such logic exists. Enumeration of which integrations expose a person-detect switch (Frigate no, UniFi Protect yes per-camera, Reolink yes per-channel, Dahua varies) is NOT in the repo. Requires live probe before build (D4 gate). | **DIVERGE — new work** |
| "CameraPersonDetectedSensor per room" | Exists (`binary_sensor.py:1089`) but is DORMANT because it reads a room-level key the v3.4.5 migration removed. Operator memory of "we have it" is right about the class; wrong about its liveness. | **PARTIAL — dormant** |
| "fan_veto camera leg activates when CAMERA_COVERED_ROOMS matches" | Correct — `fan_veto.py:260`; only `Study A` today. Uses the same dormant room-level `CONF_CAMERA_PERSON_ENTITIES` read → effectively the veto camera leg NEVER fires today unless the operator has manually re-added the room key post-migration. | **MATCH — silent gap confirmed** |
| Per-room camera field is "for other homes"; native URA is zone-level | Correct positioning. This cycle SHIPS the per-room surface but hardens the fusion machinery that the zone-level census can also consume (`resolve_cross_platform_sensors` already used by transit + census). | **MATCH** |

### 1.5 Device-correlation honesty (must be specified, not glossed)

The operator asserts: "same physical camera can appear via multiple integrations (Frigate ingests UniFi/Reolink streams; Protect ingests Reolink via ONVIF; Reolink has its own NVR); each integration is a separate HA device." This is true. The correlation problem is:

**Q: Given a Reolink `camera.*` entity, how do we discover the Frigate device that ingests its RTSP stream and the UniFi Protect device that adopted it via ONVIF, so we can fuse all three integrations' person sensors?**

Available correlation signals (HA device registry):
- `device.identifiers` — integration-scoped tuples, e.g. `("frigate", "front_door")`, `("unifiprotect", "<mac>")`, `("reolink", "<uid>")`. Cross-integration overlap is unreliable — Frigate uses config-file names, not MACs.
- `device.connections` — set of `(type, value)` including `("mac", "aa:bb:cc:...")` and sometimes `("ip", "...")`. UniFi Protect and Reolink typically populate MAC; Frigate does NOT (Frigate is a Docker container, not a NIC-owning device).
- Entity name stems — the heuristic `resolve_cross_platform_sensors` uses today. Works when integrations agree on naming; fails otherwise.

**Honest algorithm for D2 (specify, don't overclaim):**
1. Resolve the input entity to its HA `device_id` (D1).
2. Extend the current name-stem heuristic (`resolve_cross_platform_sensors`, l.401) to ALSO index the registry by `device.connections` MAC where available, producing a `mac → [device_id]` map at discovery time.
3. If the input device has a MAC connection, prefer MAC-linked sibling devices over name-stem matches.
4. Fall back to name-stem for Frigate (no MAC) and for integrations that don't populate connections.
5. **Always** surface the correlation basis in the fused sensor's `sources[i].correlation_basis` attribute ∈ `{"device_match", "mac", "name_stem", "operator_confirmed"}` so the operator can audit and, if wrong, add a per-room manual override (parked — see §Parked).

**Where operator confirmation is needed** (call out, don't hide): a Frigate camera ingesting a Reolink RTSP stream will have NEITHER MAC parity NOR guaranteed name-stem parity. Fusion of that pair requires either (a) accepting the operator's multi-select of both `camera.*` entities as an implicit "these are the same physical camera" declaration (D1's multi-select semantics — this is the operator amendment #1), or (b) a future operator-confirmation UI (parked). D1 as specified makes the operator's multi-select the source of truth for "same physical camera" and the algorithm above is only used to DISCOVER additional per-integration sensors from the entities the operator listed.

---

## 2. Operator-specified design (verbatim intent — honor exactly)

1. **Config accepts ANY camera-related entity but resolves to the physical CAMERA internally.** Operator picks a `camera.*`, a person-detect `binary_sensor.*`, or any entity of/near a camera. URA resolves to the camera DEVICE. Multi-select adds ANOTHER physical camera (any of its entities — same resolution).
2. **URA discovers capabilities itself:** for each resolved camera device, walk ALL camera-integration devices exposing the same physical camera (Frigate, UniFi Protect, Reolink). Iterate sensors across those devices and pick FACE and/or PERSON detection sensors per integration.
3. **Cross-correlation confidence:** agreement across integrations raises per-camera confidence.
4. **Auto-enable person detection** where an integration exposes it and it's currently OFF. **Person yes, face no** (face stays opt-in per existing `CONF_FACE_RECOGNITION_ENABLED`).
5. **Placement:** room config SENSORS step. Native URA remains zone-level (census). Per-room surface is for other homes; harden with Study A.

---

## 3. Tier classification — **Tier 3** (four framing-disjoint reviews + operator checkpoint)

Triggers fired:
- **Trust-hierarchy ripple:** camera → presence → fan_veto → census. Same coupling family as v5.16.0 guest-latch and Bug Class #53 (computed-but-not-consumed) — a wrong fusion result mis-classifies presence which mis-decides veto which mis-decides comfort.
- **Shared-primitive change:** `resolve_cross_platform_sensors` is consumed by census AND transit_validator AND (post-D5) fan_veto. Editing it is one-primitive-many-consumers.
- **Silent-loss failure mode:** a mis-fused sensor stuck ON silently vetoes fans (comfort loss) or holds presence (safety-relevant HVAC hold); silent DOWN misses guest detection. Both are single-path bugs.
- **Config combinatorics:** operator can pick 1..N entities per camera × 1..N cameras per room × 3+ integrations × person-detect switch on/off. Legal but never-happy-path combinations exist (e.g. one Reolink entity picked, its Frigate sibling exists but is disabled — should D4 enable? Only Frigate side).

**Falsifiable invariant this cycle must guarantee (stated up front for Review D):**

> Under any legal room config where at least one selected entity resolves to a camera device with at least one per-integration person-detect sensor whose HA state ∈ {`on`, `off`}, the room's fused `binary_sensor.<room>_camera_person_detected` MUST be `on` iff any resolved per-integration person-detect sensor is `on`, and it MUST reflect state changes within one HA state-change event tick (no polling gap ≥5s). It MUST never be `on` when every resolved sensor is `off`/`unavailable`/`unknown`. It MUST never be `unavailable` when at least one resolved sensor is available.

Review D's job: falsify this invariant across the ENTIRE surface, including pre-existing sensors (`CameraPersonDetectedSensor`, `_has_camera_person`), not just the diff.

---

## 4. Deliverables

### D1 — Per-room `room_cameras` field (NEW key) + device resolution

**Placement:** room `async_step_sensors` (config_flow.py:1070), NEW `async_step_room_cameras` sub-step OR inline field (choose inline for parsimony — one fewer step, matches operator "under SENSORS step").

**NEW constant:** `CONF_ROOM_CAMERAS = "room_cameras"` (`const.py`). **MUST NOT reuse `CONF_CAMERA_PERSON_ENTITIES`** — the v3.4.5 migration at `__init__.py:305` strips that exact key from room entries on every setup. New key sidesteps the migration.

**Selector:** `EntitySelector(multiple=True)` with NO `domain` filter — accepts `camera.*`, `binary_sensor.*`, `sensor.*`, `switch.*` (per operator amendment #1). Include a description string clarifying "pick any entity of/near each physical camera; add another entry per physical camera."

**Resolution:** at coordinator setup (and on options-flow save), for each entity ID in `room_cameras`:
1. `ent_reg.async_get(eid)` → `device_id`. If None, WARN + skip.
2. Store `resolved_camera_devices: list[str]` (device_ids, deduped) on the coordinator.
3. Feed `resolved_camera_devices` to D2 discovery.

**Knob (Numbers-Get-Knobs):** `CONF_ROOM_CAMERAS` — **Config/options flow** rung (per-deployment structure).

**Marginal-benefit decomposition:**
- **Simple version:** the operator picks only `camera.*` entities (current selector semantics for the integration-level `camera_person_entities`). Captures ~90% of the value.
- **Full version (amendment #1):** any domain accepted. Marginal benefit: operator doesn't have to know which entity is the "camera" (Reolink exposes device without a `camera.*` if only ONVIF is in use). Marginal cost: null. Both go through the same `device_id` hop. **Ship full.**

**Acceptance criteria:**
- Verify: adding a `binary_sensor.*_person_detected` to `room_cameras` resolves to the same device as adding the sibling `camera.*` (unit test on entity registry fixture).
- Verify: unresolvable entity (deleted device) logs WARN, does not crash setup.
- Verify: v3.4.5 migration on `__init__.py:271` does NOT touch `CONF_ROOM_CAMERAS` (grep-assertion in test).
- Sensor: `binary_sensor.<room>_camera_person_detected.extra_state_attributes.resolved_camera_devices` lists the resolved device_ids.
- Test: `tests/test_room_cameras_resolution.py::{test_camera_entity, test_binary_sensor_entity, test_switch_entity, test_multi_entity_same_device_dedups, test_missing_device_id_warns}`.
- Live: Study A config includes 2+ room_cameras entries → sensor attrs show correct device_ids post-restart.

### D2 — Cross-integration face/person sensor discovery per resolved camera

**Machinery:** extend `CameraIntegrationManager.resolve_cross_platform_sensors` (camera_census.py:401) with the device-correlation algorithm in §1.5. Add:
- `_index_devices_by_mac()` — one-shot at `async_discover`, builds `mac → set[device_id]`.
- `resolve_camera_capabilities(device_ids: list[str]) -> RoomCameraFusion` — for each input `device_id`, collect:
  - Same-device person + face binary_sensors and Frigate `person_count` sensor (existing path).
  - Sibling devices via MAC connection match.
  - Sibling entities via name-stem heuristic (existing).
  - Person-detect switch entities on any matched device (D4 input).
- Return a NEW dataclass `RoomCameraFusion` with fields:
  - `physical_camera_id: str` (deterministic ID — first device_id sorted)
  - `sources: list[FusionSource]` where `FusionSource = {integration, device_id, person_binary_sensor, face_binary_sensor, person_count_sensor, person_detect_switch, correlation_basis}`
  - `discovered_at: datetime`

**Marginal-benefit decomposition:**
- **Simple version:** name-stem only (today's `resolve_cross_platform_sensors`). Captures the current 1 hardware camera on Study A because Frigate/UniFi happen to agree on stems. Marginal benefit of MAC-augmented: correctness on ONVIF-adopted Reolink where Protect names differ from Reolink native names.
- **Full version:** MAC + name-stem + operator multi-select as ground truth. Cost: ~40 LoC + 1 new dataclass. **Ship full** — the simple version silently mis-fuses on any home not organized like Study A, defeating the "for other homes" placement rationale.

**Acceptance criteria:**
- Verify: fixture with 3 devices (Frigate no-MAC, UniFi with MAC X, Reolink with MAC X) — resolving the Reolink device yields a `RoomCameraFusion` with 3 sources, correlation_basis ∈ {`device_match`, `mac`, `name_stem`}.
- Verify: fixture with unrelated devices sharing a name-stem coincidence but no MAC — name_stem match is included but flagged in `correlation_basis`.
- Verify: no regression — call chain `PersonCensus.get_transit_interior_entities` returns byte-identical results on the Study-A fixture (integration-level path must not change).
- Test: `tests/test_camera_fusion_discovery.py::{test_mac_correlation, test_name_stem_fallback, test_no_regression_study_a}`.
- Live: NEW diagnostic sensor `sensor.<room>_camera_fusion_sources` (state = count of resolved sources; attrs = full `RoomCameraFusion` dict). On Study A, expect ≥1 source per configured camera.

### D3 — Fused `CameraPersonDetectedSensor` v2 (per-source attribution + x-correlation confidence)

**Rewrite:** `binary_sensor.py:1089–1132`. Replace room-level `CONF_CAMERA_PERSON_ENTITIES` read with the D1/D2 machinery.

**Semantics:**
- `is_on = any(source.person_binary_sensor state == "on" for source in fusion.sources if state available)`.
- Respect `CONF_DISABLE_CAMERA_PRESENCE` (`const.py:354`) — sensor is present but always `off` when set.
- Use `async_track_state_change_event` on the union of all `person_binary_sensor` entity_ids for tick-accurate updates (invariant: ≤1 tick propagation).

**Attributes:**
```
sources: [{integration, entity_id, state, correlation_basis, last_changed}, ...]
agreement: "unanimous_on" | "unanimous_off" | "split" | "single_source"
confidence: "high" (≥2 sources agree ON) | "medium" (single source ON or split) | "low" (all unavailable) | "none" (no sources)
face_recognized_persons: list[str]  # from face binary_sensors when available
resolved_camera_devices: [...]      # for D1 acceptance
disabled_by_config: bool            # respects CONF_DISABLE_CAMERA_PRESENCE
```

**Marginal-benefit decomposition:**
- **Simple version:** `is_on = any(...)` with no attribution. Ship the OR fusion; drop attribution. Captures the fan_veto D5 need directly (D5 only cares about the boolean). Cost: ~10 LoC.
- **Full version:** attribution + agreement + confidence for cross-integration observability. Marginal cost: ~30 LoC, adds new state to hold. Marginal benefit: operator can DIAGNOSE which integration triggered a false positive (materially useful during Study-A hardening — Bug Class #7 stale-data + Class #22 enum mismatch have both bitten camera work). **Ship full** — Study A is the harden bench and attribution is what hardening needs.

**Acceptance criteria:**
- Verify: state changes on any source propagate to `is_on` within 1 tick (event-driven, no polling).
- Verify: `CONF_DISABLE_CAMERA_PRESENCE=True` forces `is_on=False` and sets `disabled_by_config: true`.
- Verify: no sources available → `is_on=False`, `confidence="low"` or `"none"`, sensor NOT unavailable.
- Verify: agreement classification correct across the four combinations (fixture matrix).
- Test: `tests/test_camera_person_fused_sensor.py` (matrix on agreement/confidence, disabled_by_config, event propagation).
- Live: on Study A, entity `binary_sensor.study_a_camera_person_detected` shows `agreement` in {`unanimous_off`, `unanimous_on`, `split`} across a walk-through; `sources` lists ≥2 entries.

### D4 — Auto-enable person detection where disabled (person yes, face no)

**Gate — Measure-Before-You-Build (MANDATORY):** before build, run a read-only probe on the live HA instance to enumerate switch entities matching person-detect patterns per integration. Deliverable: `docs/planning/AUDIT_camera_person_detect_switches.md` with per-integration table (integration, entity_id pattern, current state, whether it's a "detect person" toggle vs a global "detections" toggle). Known/expected surfaces to check:
- UniFi Protect: `switch.<camera>_detections_person` (per-camera person detection toggle).
- Reolink: `switch.<camera>_person_detection` (per-channel).
- Frigate: N/A (config-file driven, no runtime switch).
- Dahua: varies.

**Behavior (post-probe):**
- At coordinator setup (post-D2 discovery), for each `FusionSource.person_detect_switch` where present and state == `"off"`: call `switch.turn_on` via `hass.services.async_call`.
- **Face switches (`*_detections_face`, `*_face_detection`) NEVER auto-enabled** — per operator amendment #4 and existing `CONF_FACE_RECOGNITION_ENABLED` respect.
- Kill switch: `CONF_AUTO_ENABLE_PERSON_DETECTION` (default `True`). Setting to `False` disables the auto-enable step (does not disable per-integration switches that were previously enabled).

**Knob (Numbers-Get-Knobs):**
- `CONF_AUTO_ENABLE_PERSON_DETECTION` — **Config/options flow** rung (safety-adjacent default-on, but the operator should be able to disable without a code change if a particular integration behaves badly).

**Marginal-benefit decomposition:**
- **Simple version:** don't auto-enable; document that operator must turn switches on manually. Marginal benefit of auto-enable: eliminates a silent-DOWN failure mode (operator adds a Reolink camera, its `person_detection` switch is off by default, fusion looks working but never fires ON). Marginal cost: writes to third-party integrations at setup time (one-shot per switch, idempotent).
- **Full version:** as specified above with kill switch. Cost: ~20 LoC + probe artifact. **Ship full** — this is the "usually safe vs face" amendment the operator explicitly asked for.

**Acceptance criteria (post-probe fills specifics):**
- Verify: probe artifact `docs/planning/AUDIT_camera_person_detect_switches.md` committed BEFORE build, lists actual per-integration switches on live HA.
- Verify: at coordinator setup, any known person-detect switch found in `off` is turned on; state transition logged INFO.
- Verify: no face-detect switch is touched (test fixture with both).
- Verify: `CONF_AUTO_ENABLE_PERSON_DETECTION=False` skips the entire auto-enable pass.
- Test: `tests/test_camera_person_detect_auto_enable.py`.
- Live: 24h after deploy, `switch.*_person_detection` entities remain ON for all discovered fusion sources; NO face switch changed state (`ha_get_logs` scan).

### D5 — fan_veto camera leg keyed to D3 (replaces dormant CAMERA_COVERED_ROOMS derivation)

**Change:** `fan_veto.py:245–290` `_has_camera_person`:
- Drop the `CAMERA_COVERED_ROOMS` allowlist (fan_veto.py:260) and the direct `CONF_CAMERA_PERSON_ENTITIES` read.
- Read the D3 fused sensor via `hass.states.get(f"binary_sensor.{room_slug}_camera_person_detected")`.
- Room is "camera-covered" iff `CONF_ROOM_CAMERAS` is non-empty AND `CONF_DISABLE_CAMERA_PRESENCE` is False.
- Coverage derivation moves from the const-file allowlist to config-presence.
- **Const to DEPRECATE (not delete this cycle):** `CAMERA_COVERED_ROOMS` in `const.py:666` — mark as UNUSED after D5, delete in a follow-up cycle after live-validation confirms nothing else reads it (grep found only the fan_veto consumer today, but grep the whole tree post-build).

**Falsifiable sub-invariant (Review D):** for any room where `CONF_ROOM_CAMERAS` is empty OR the fused sensor is `off`, `_has_camera_person` returns False. For any room where the fused sensor is `on` AND `CONF_DISABLE_CAMERA_PRESENCE` is False, `_has_camera_person` returns True.

**Marginal-benefit decomposition:**
- **Simple version:** keep `CAMERA_COVERED_ROOMS`, just make it read the fused sensor for listed rooms. Marginal cost: allowlist stays as a duplicate source of truth for "is this room camera-covered."
- **Full version:** delete the allowlist; derive from config presence. Cost: 1 const marked deprecated. Benefit: one source of truth; new homes don't need to edit `const.py` to activate the veto leg (the whole point of the room-level surface). **Ship full.**

**Acceptance criteria:**
- Verify: `_has_camera_person` returns True for Study A when fused sensor is ON (unit test).
- Verify: `_has_camera_person` returns False for any room with empty `CONF_ROOM_CAMERAS` regardless of `CAMERA_COVERED_ROOMS` membership.
- Verify: `_has_camera_person` respects `CONF_DISABLE_CAMERA_PRESENCE` (existing D-LOW-3 casefold parity preserved).
- Test: `tests/test_fan_veto_camera_leg_fusion.py` (matrix on coverage × fused state × disable flag).
- Live: on Study A, `binary_sensor.study_a_comfort_fan_veto_active` (or equivalent) tracks room camera-person during a walk-through; fan turn-on requests during camera-ON are vetoed (log scan).

### Parked (record with evidence triggers, not built)

- **Vision-LLM snapshot understanding** (AI Task per-cycle "describe this snapshot" for adjudication of ambiguous camera-ON): revisit when Study-A hardening surfaces a persistent split-agreement case that binary fusion cannot disambiguate. Evidence trigger: >5 `split` agreements/day sustained over 3 days on Study A.
- **NM snapshot attachments** (attach the triggering camera snapshot to security/anomaly NM notifications): revisit after PWA v6.2 gains attachment rendering. Evidence trigger: operator NM-follow-up latency measurably reduced by having the snapshot.
- **Recheck adjudication (LLM-assisted re-vote on unstable fusion):** revisit if D3 `confidence="medium"` (split) sustains >10% duty cycle on any camera. Evidence trigger: split-duty > 10% for 7 consecutive days.
- **Operator-confirmation UI for correlation basis** ("these two devices ARE the same physical camera" affirmation): revisit if D2's MAC-or-stem heuristic mis-correlates on any post-Study-A deployment. Evidence trigger: any false correlation reported.

---

## 5. Files touched (proposed)

| File | Change |
|---|---|
| `const.py` | ADD `CONF_ROOM_CAMERAS`, `CONF_AUTO_ENABLE_PERSON_DETECTION`, `DEFAULT_AUTO_ENABLE_PERSON_DETECTION=True`. Mark `CAMERA_COVERED_ROOMS` as `# DEPRECATED v<X> — replaced by CONF_ROOM_CAMERAS config-presence derivation; delete after N releases.` |
| `config_flow.py` | Inline `CONF_ROOM_CAMERAS` into `async_step_sensors` (~l.1106); mirror in options-flow `async_step_sensors` (l.9061). |
| `strings.json` + `translations/en.json` | Labels + descriptions for `room_cameras` and `auto_enable_person_detection`. |
| `camera_census.py` | Extend `CameraIntegrationManager` with `_index_devices_by_mac`, `resolve_camera_capabilities`, `RoomCameraFusion` dataclass. NO change to existing `resolve_cross_platform_sensors` signature (add path, don't replace). |
| `binary_sensor.py` | Rewrite `CameraPersonDetectedSensor` (l.1089) — event-driven, D2-backed, D3 attributes. |
| `__init__.py` | Coordinator setup: call D1 resolution + D2 discovery + D4 auto-enable. NO change to `_migrate_room_cameras_to_integration` (it must remain, and it must NOT touch the new key). |
| `fan_veto.py` | D5 rewrite of `_has_camera_person`; drop `CAMERA_COVERED_ROOMS` import. |
| `sensor.py` | ADD `RoomCameraFusionSourcesSensor` (D2 diagnostic; state = source count). |
| `tests/` | 5 new test files (see per-D acceptance sections). |
| `docs/planning/AUDIT_camera_person_detect_switches.md` | Probe artifact for D4 (BEFORE build). |
| `docs/readmes/README_v<version>.md` | Pre-deploy prospective + post-deploy Validated table. |

---

## 6. Review protocol (Tier 3)

Four framing-disjoint reviewers in parallel:

- **A — Local correctness:** per-site logic in D1 (resolution), D2 (correlation), D3 (agreement/confidence), D4 (switch domain/action), D5 (predicate). None-handling, unavailable state, disable-flag respect.
- **B — Integration / state-machine integrity:** event-track cleanup on entity_id set change (D3); coordinator reload safety; interaction with existing census `resolve_cross_platform_sensors` (byte-identical on the integration-level path); presence coordinator signal (`camera_person_detected` at `presence.py:194`); transit_validator's `camera_person_id` freshness unaffected; no double-writes to third-party switches (D4 idempotency).
- **C — Test authority via per-site source mutation:** neuter each of {D1 device_id hop, D2 MAC index, D2 name-stem, D3 agreement branch, D4 skip-when-face, D5 disable-flag branch} ONE at a time; verify a SPECIFIC test fails per site; restore. Any site whose neutering leaves suite green = untested site = block ship. Guard: `PYTHONDONTWRITEBYTECODE=1` + clear `__pycache__` before every mutation run (mutation-pyc-staleness rule).
- **D — Adversarial completeness / diff-blind:** falsify the §3 invariant across the ENTIRE camera trust surface (pre-existing sensors, transit, census, presence). Concrete legal-config repros required for every claimed leak. Re-enumerate all readers of camera-person state after D5 removes the allowlist — is there any pre-existing consumer that assumed only Study A was covered?

**Orchestrator independent verification before ship:** personally re-grep every `CONF_CAMERA_PERSON_ENTITIES`, `CAMERA_COVERED_ROOMS`, `_has_camera_person`, `CameraPersonDetectedSensor` reference and confirm each is either (a) intentionally preserved (integration-level), (b) rewritten (D5), or (c) marked deprecated. Personally run per-site mutation on at least D3.is_on and D5._has_camera_person.

**Operator checkpoint BEFORE deploy** — surface the four review outcomes + the invariant proof + the D4 probe artifact.

**Live Validation (Review D live):** post-restart, verify on Study A:
- `binary_sensor.study_a_camera_person_detected.attributes.sources` lists ≥2 sources.
- Walk-through toggles `is_on` correctly and `agreement` transitions through expected values.
- `switch.study_a_*_person_detection` all ON (D4).
- No face switch touched (log scan).
- Fan turn-on request during camera-ON is vetoed (log or DB scan).

Write results back into `README_v<version>.md` as `Validated <date>` table (per CLAUDE.md).

---

## 7. Risks

- **v3.4.5 migration collision** — mitigated by using NEW key `CONF_ROOM_CAMERAS`. Test-asserted.
- **`CameraPersonDetectedSensor` behavior change** — was dormant (post-migration), so rewriting to fusion is not a behavioral regression FOR ROOMS that had no room-level cameras. It IS a change for any manually-preserved legacy config; single-user-no-back-compat applies (MEMORY: `project_single_user_no_backcompat.md`) — no migration needed, but README must call this out.
- **D4 writes to third-party switches** — probe artifact enumerates exactly which switches; kill switch provided; face switches explicitly excluded.
- **D5 allowlist removal** — grep-verified single consumer today; deprecation-not-deletion this cycle, delete in a follow-up.
- **Bug Class #53 (computed-but-not-consumed):** D3 attributes must be consumed by at least the diagnostic sensor (D2) and the operator dashboard; Review D checks no orphan computation.

---

## 8. Plan-completion tracking (for post-implementation write-back)

Any of D1–D5 deferred: log here with reason. Parked items already recorded in §4.

---

## Amendment 2026-08-01 (operator): D2 becomes EXTRACT-AND-ABSTRACT of `resolve_cross_platform_sensors` — Tier 3, no regression

Operator directive: improve/abstract `resolve_cross_platform_sensors` (camera_census.py:401) so the
room-level re-add with a different purpose REUSES it — do not grow a parallel resolver. Tier 3; the
census must not regress.

**Revised D2 shape — a shared `CameraResolver` primitive:**
- One module (e.g. `camera_resolver.py`) owning the full chain: any-entity → device → physical-camera
  correlation (device `connections` MAC index → `identifiers` → entity-name-stem fallback → operator
  multi-select as ground-truth declaration) → per-integration capability map (person/face/count
  sensors, detection-enable switches).
- **Consumers:** camera_census (existing name-stem behavior), room-camera fusion (D3), fan_veto camera
  leg (D5), transit_validator (audit its usage during build). One resolver, N purposes — the same
  corroborate-at-one-chokepoint discipline as fan_veto.

**Non-regression invariant (this cycle's Review B/D anchor, falsifiable):** for every camera in the
live census config, the abstracted resolver's census-facing output is IDENTICAL to the pre-cycle
name-stem output — MAC/identifier correlation may only ADD matches for the NEW consumers, never
change what the census sees, until a separately-flagged census cutover (own knob, default legacy).
Golden-master test: capture pre-cycle `resolve_cross_platform_sensors` output for the live camera
list as a committed fixture; the abstracted path must reproduce it byte-identically.

**Tier 3 confirmation:** shared-primitive extraction consumed by 3+ coordinators = the definition of
the Tier-3 trigger. Four framing-disjoint reviews; Review C mutates the resolver per consumer;
Review D re-enumerates every resolution call site (census, transit, fusion, veto) for a missed one.

## Amendment 2026-08-01 (operator dispositions — scope guard)
- Room-camera config was dead **by design** (v3.4.5 centralization was correct for its purpose). This cycle is a **new use case (fusion)**, not a resurrection/correction. Frame accordingly.
- **Zone/census design is RIGHT — preserve its GOAL, and DO cut it over** (operator correction, same day): the census keeps its architecture and zone-level semantics (shared-space cameras, area-mapped, identity counting) and ADOPTS the shared resolver so its x-correlation gets better too. The invariant is design-preservation, not output-freezing.
- **Do not mistake the room use case for the zone use case.** Two consumers, two semantics, one resolver: zone census = shared-space identity/counting via area mapping; room fusion = per-room presence corroboration via operator-declared cameras. The resolver serves both; neither consumer's semantics leak into the other.
- Golden-master revised accordingly: capture the pre-cycle census resolution as a fixture, and the cutover review examines the DIFF — every changed resolution must be an explicable correlation improvement (a sensor the name-stem heuristic missed for a camera the census already owns), never a semantic change. Unexplained diffs block the cutover. Cutover ships flagged (rung-1 constant, default new-resolver after the diff review passes; flag exists purely as the fire-axe).
- Standing directive: no overbuilding, guard scope creep. Trust-ledger note: if/when that cycle runs (gate ~Aug 11), THIS cycle is its template for fusion+trust shape.

## Amendment 2026-08-01 (operator): census dual-source machinery IS the x-correlation reference; generalize the schema

Operator confirmed: the census's frigate/unifi dual-source implementation (camera_census.py platform classification + per-source counts + `source_agreement`) is the REFERENCE shape for CameraResolver x-correlation — reuse its semantics, don't reinvent. Its scaling flaw (operator-spotted): `census_snapshots` hardcodes one column per vendor (`frigate_count`, `unifi_count`). Fusion-cycle deliverable addition: **generalize to a `source_counts` JSON column** (per-source-key counts; new integrations = new keys, no migration), keep the two legacy columns written in parallel during transition (existing analytics unaffected), compute `source_agreement` over N sources. Tier 2-DB triggers apply (schema addition + payload shape).

Immediate config action (operator-approved, this session): interior UniFi Protect `*_person_detected` sensors added to the CM census camera list — activates the existing unifi_count leg today; today's playroom phantom would have been confidence-suppressed by source divergence.

**Correction (same day, deeper read):** the Protect leg is MORE alive than first assessed. Two Protect cameras are already in the census list (`playroom_high_resolution_channel`, `staircase_high_resolution_channel`); resolution is device-based first (person sensors live on the Protect camera's own HA device), and today's snapshots show BOTH sources reporting: `frigate_count=1` (phantom) vs `unifi_count=0` (truth), `source_agreement='close'`. **The gap is the FUSION POLICY, not the wiring**: a 1-vs-0 divergence is scored "close" and the census sides with the max — Protect's correct zero never suppressed the phantom. Fusion-cycle deliverable sharpened: (a) divergence-aware confidence (source disagreement during away/low-corroboration ⇒ suppress or downgrade, not max-wins), (b) widen Protect coverage to the remaining interior cameras (family_room, master_hallway, foyer — via their Protect camera entities), (c) the `source_counts` JSON generalization per the prior amendment. The options-flow selector is camera-domain-only — person binary_sensors are resolved, never hand-listed (correct design; keep).
