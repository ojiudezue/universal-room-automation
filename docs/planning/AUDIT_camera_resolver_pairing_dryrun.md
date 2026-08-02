# AUDIT — CameraResolver D0 dry-run pairing probe

**Date:** 2026-08-01
**Cycle:** `docs/planning/PLANNING_room_camera_fusion.md` D0 (test battery item #5 — "Live dry-run probe as a D0 artifact").
**Mode:** READ-ONLY. Consumed the Samba-mounted registries under `~/ha-config/.storage/` — no HA import, no writes, no config change.
**Script:** `docs/planning/scripts/camera_resolver_dryrun_probe.py` (committed alongside).
**Raw JSON output:** regenerable via `python3 docs/planning/scripts/camera_resolver_dryrun_probe.py`.

This document is the **acceptance artifact** the Tier-3 build gets diffed against. Every derived pairing here has been hand-verified against the operator's CM config (fixture #2 in the plan's test battery).

---

## 1. Camera-device census on the live registry

Enumerated every device whose entities include a `camera.*` platform. Total **85 camera devices** across five platforms:

| Platform | Camera-owning devices | With MAC connection | Without MAC |
|---|---:|---:|---:|
| `unifiprotect` | 35 | 35 | 0 |
| `frigate` | 48 | 0 | 48 (Docker containers, no NIC) |
| `reolink` | 3 | 0 | 3 |
| `amcrest` | 1 | 1 | 0 |
| `dahua` | 1 | — | — |
| **Total unique** | **85** | **36 (42%)** | **49 (58%)** |

**Frigate hosts distinct:** `01JV6G4E57HT3WH86WSQ4RJT11` (Frigate 1) and `01KM239Z8ZQWQTN1D9CV5JRA7V` (Frigate 2) — confirms the 2026-08-01 upstream finding of a dual-Frigate topology (both hosts publish under the same MQTT topic prefix `frigate` per the plan's amendment).

**Cross-platform MAC overlap:** **ZERO** — no MAC is shared across two camera-owning devices of different platforms. See §4 for what this means for the correlation ladder.

---

## 2. Correlation-ladder outcome per configured camera

Applied the plan's ladder (same-device → MAC → identifiers → name-stem) offline to every camera in the operator's live CM config (`camera_person_entities` interior list + `egress_cameras` + `perimeter_cameras`, 21 cameras total).

### 2.1 Per-rung distribution — the load-bearing rungs on THIS registry

| Rung | Interior (fixture) | Egress | Perimeter | **All** |
|---|---:|---:|---:|---:|
| `same_device` | **9** | 3 | 9 | **21** |
| `mac` | 0 | 0 | 0 | **0** |
| `identifiers` | 0 | 0 | 0 | **0** |
| `name_stem` (as primary) | 0 | 0 | 0 | **0** |
| `unmatchable` | 0 | 0 | 0 | **0** |

**Load-bearing verdict:** ONLY the same-device rung fires on this registry. **MAC and identifiers rungs discover NOTHING today.** Name-stem fires as an AUGMENTATION (adds more sensors) on some cameras — most notably the two Frigate hosts' duplicate `staircase` device — but never as the primary rung.

### 2.2 Confidence tags — interior fixture only

| Confidence | Count | Notes |
|---|---:|---|
| `certain` | 9 | All 9 fixture interior cameras: same-device match; Frigate `_person_occupancy` and UniFi Protect `_person_detected` co-resident on the SAME HA device (see §3). |
| `likely` | 0 | — |
| `ambiguous` | 0 (interior) / 1 (egress: `madrone_g6_entry` — package-person separate detector) | |
| `unmatchable` | 0 | |

---

## 3. Fixture diff — every fixture-vs-derived comparison (interior, 9 cameras)

Hand-built fixture: the operator's CM `camera_person_entities` list. Expected per-camera person sensor is `binary_sensor.<stem>_person_occupancy` (Frigate) and/or `binary_sensor.<stem>_person_detected` (UniFi Protect); expected count sensor `sensor.<stem>_person_count`.

| # | Fixture camera | Rung | Conf | Person BSes discovered | person_count | Face sensor(s) | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | `camera.playroom_high_resolution_channel` | same_device | certain | `playroom_person_detected`, `playroom_person_occupancy` | `playroom_person_count` | `playroom_last_recognized_face`, `_2` | **AGREE** |
| 2 | `camera.master_hallway` | same_device | certain | `master_hallway_person_occupancy`, `_person_detected` | `master_hallway_person_count` | `master_hallway_last_recognized_face_2` | **AGREE** |
| 3 | `camera.staircase_high_resolution_channel` | same_device | certain | `staircase_person_occupancy` + **`camera_protect_garagehallway_person_detected` (WRONG CAMERA)** | `staircase_person_count` | 2× `last_recognized_face*` | **AGREE + FINDING F1** |
| 4 | `camera.playroom` | same_device | certain | `playroom_person_occupancy`, `_person_detected` | `playroom_person_count` | 1× face | **AGREE** |
| 5 | `camera.foyer_fisheye` | same_device | certain | `foyer_fisheye_person_occupancy`, `_person_detected` | `foyer_fisheye_person_count` | 1× face | **AGREE** |
| 6 | `camera.family_room` | same_device | certain | `family_room_person_occupancy`, `_person_detected` | `family_room_person_count` | 1× face | **AGREE** |
| 7 | `camera.family_room_high_resolution_channel` | same_device | certain | `family_room_person_detected`, `_person_occupancy` | `family_room_person_count` | 2× face | **AGREE** (dedup with #6 required) |
| 8 | `camera.foyer_fisheye_high_resolution_channel` | same_device | certain | `foyer_fisheye_person_detected`, `_person_occupancy` | `foyer_fisheye_person_count` | 2× face | **AGREE** (dedup with #5 required) |
| 9 | `camera.master_hallway_high_resolution_channel` | same_device | certain | `master_hallway_person_detected`, `_person_occupancy` | `master_hallway_person_count` | 2× face | **AGREE** (dedup with #2 required) |

**Fixture-vs-derived summary:** 9/9 agree on presence of at least one correct person sensor; 4 of the 9 exhibit dedup pressure (high-res and default channels resolve to the same or overlapping device sets — the existing `resolve_configured_cameras` dedup path will collapse these correctly, but D3 must dedup post-fusion too).

### 3.1 Egress + perimeter (12 cameras)

All 12 resolved via `same_device` with `certain` (except `madrone_g6_entry`, `certain-ambiguous`: also has a `_package_person_occupancy` / `_package_person_count` — Frigate "package" object detector, not a person). Perimeter `camera.armcrest` picks up `armcrestash41b_*` sibling entities on the same device (legacy naming residue — verify these are the same physical camera).

---

## 4. Ambiguous / unmatchable rows — what and why

### F1 — CRITICAL: UniFi Protect NVR-style device conflates two physical cameras

- **Symptom:** `camera.staircase_high_resolution_channel` resolves to Protect device `e13c85d37316f21d1fcf4ae07537e717` (MAC `28:70:4e:17:ee:02`). Same-device sensor scan pulls in `binary_sensor.camera_protect_garagehallway_person_detected` and `binary_sensor.camera_protect_garagehallway_motion` — sensors belonging to a **different physical camera** (Garage Hallway) that shares the same HA device record.
- **Verification:** confirmed by re-reading the entity_registry for `device_id=e13c...`: 46 unifiprotect entities span BOTH the Staircase camera object (`staircase_*`) AND the GarageHallway camera object (`camera_protect_garagehallway_*`).
- **Why this matters:** the plan's D2 says "resolve to `device_id` and collect all person sensors on that device." On this registry that would fuse two physically distinct cameras. Silent-false-positive: garage hallway person triggers Staircase's fused sensor → wrong room presence.
- **Operator declaration that resolves it:** within a Protect device, sensor-to-physical-camera grouping must be done by ENTITY NAME STEM (the shared prefix like `staircase_` vs `camera_protect_garagehallway_`), NOT by `device_id`. Alternatively, treat the Protect device as authoritative only for entities whose stem matches the input `camera.<stem>` entity_id.

### F2 — HIGH: Frigate dual-host produces two devices for the same physical camera (name-stem only)

- **Symptom:** the two Frigate hosts each own a device named `Staircase` (identifiers `("frigate", "01JV...:staircase")` and `("frigate", "01KM...:staircase")`). Name-stem correlation returns both as siblings of the Protect `Staircase`; their `_person_occupancy` sensors will both fire in fusion.
- **Registered upstream:** MQTT `topic_prefix` for both hosts is `frigate` (plan §Amendment 2026-08-01 upstream finding). The two Frigate entries subscribe to the merged stream — they are NOT independent corroborators. Fusion agreement between Frigate-1 and Frigate-2 is currently meaningless.
- **Operator declaration that resolves it:** either (a) the homelab-side prefix split lands and the two hosts become distinct MQTT sources, or (b) CameraResolver treats all Frigate devices sharing the same object name as ONE logical source (collapse before agreement calculation).

### F3 — MEDIUM: `camera.madrone_g6_entry` has package-object person detector alongside person detector

- **Symptom:** same-device scan yields `binary_sensor.madrone_g6_entry_person_occupancy` (person) AND `binary_sensor.madrone_g6_entry_package_person_occupancy` (package + person) AND `sensor.madrone_g6_entry_package_person_count`.
- **Operator declaration that resolves it:** filter out Frigate "package" object variants (any `_package_` in the name). Package-person is a legitimate but distinct Frigate object class; conflating with person raises FP rate on egress.

### F4 — LOW: `camera.armcrest` picks up `armcrestash41b_*` legacy naming twin

- **Symptom:** same-device scan yields both `armcrest_person_occupancy` AND `armcrestash41b_person_occupancy`. Likely same physical camera, entity_id churn from earlier setup. Not harmful (both stems on same device) but the fusion dashboard will show a duplicate source.
- **Operator declaration that resolves it:** operator confirms same-camera (dedup by device_id already handles this; D3 attribution merely surfaces both entity_ids).

### F5 — INFO: MAC / identifiers rungs are 0-consumer on this registry

- **Symptom:** zero cross-platform MAC overlap; zero cross-platform identifier-value overlap.
- **Root cause:** Frigate (48 of 85 devices) never populates `connections.mac`; UniFi Protect uses `unifiprotect`-scoped identifier tuples (integration-scoped); Reolink uses `reolink`-scoped. The only integration that pairs by MAC across integrations would be a hypothetical `unifi` + `reolink` overlap — but Reolink devices here have no MAC either (0 of 3).
- **Implication for D2:** the MAC and identifiers rungs described in the plan §1.5 are **infrastructure with no live consumers today**. Building them is defensible (they cost ~40 LoC and cover future homes) but they cannot be validated on this registry — a fixture with a synthetic MAC-shared Protect/Reolink pair is the only way to prove them. Name-stem remains the workhorse.

---

## 5. D4 auto-enable probe — person-detect switch inventory

Enumerated every non-disabled `switch.*` entity matching the person-detect or face-detect patterns per integration.

| Platform / kind | Count | Sample entities | Auto-enable candidate? |
|---|---:|---|---|
| `unifiprotect` / person | **19** | `switch.staircase_detections_person`, `switch.playroom_detections_person`, `switch.g5_bullet_detections_person`, `switch.pool_equipment_detections_person`, `switch.garage_a_detections_person`, … | **YES** (D4 target) |
| `unifiprotect` / face | 0 | — (Protect exposes face via distinct `_smart_detect_face`? not present here) | — |
| `reolink` / person | 0 | none found matching `_person_detection` / `_smart_detect_person` | **NEEDS live check** — Reolink integration may expose these under a different naming (e.g. `switch.<name>_ai_person`); the probe's pattern set may be incomplete for Reolink |
| `amcrest` / person | 0 | none found | **NEEDS live check** — same caveat |
| `frigate` / person | 0 | Frigate is config-driven, no runtime switch | N/A per plan |

**Current on/off states:** the probe attempted to read `core.restore_state` — none of the 19 Protect person-detect switches had a row (they may be always-live entities, not RestoreEntity-backed). The plan's D4 acceptance says "current state; noted as needs-live-read" — this is that note. Live-read via `ha_get_states` (MCP) or `hass.states.get()` post-restart is required before the auto-enable action fires.

**Face-switch protection scope:** ZERO face-detect switches were found under the current pattern set — the "never auto-enable face" invariant is trivially satisfied for the platforms surveyed, but the pattern set should be widened (`_smart_detect_face`, `_detections_smart_face`, `_ai_face`) before Review C signs off.

---

## 6. GO / NO-GO per deliverable

| Deliverable | Verdict | Rationale |
|---|---|---|
| **D1** — per-room `room_cameras` field + any-domain entity → device resolution | **GO** | The device-resolution primitive works on 21/21 configured cameras. The v3.4.5 migration collision is well-understood; new key `CONF_ROOM_CAMERAS` is the correct sidestep. |
| **D2** — cross-integration sensor discovery (correlation ladder) | **GO — WITH SCOPE REVISION** | (a) Same-device rung is the workhorse (100% of live cameras). (b) **F1 forces a fix**: same-device grouping MUST filter Protect entities by name-stem within a device, not blanket-collect. (c) MAC / identifiers rungs are infrastructure without a live consumer — build them, but validate them ONLY via synthetic fixtures (§4 F5); do NOT gate the cycle on real-registry MAC-cross-platform matches — there are none. (d) Name-stem must add the **F2 same-Frigate-object collapse** (do not count Frigate-1 + Frigate-2 as independent) and **F3 package-object exclusion**. |
| **D3** — fused `CameraPersonDetectedSensor` v2 | **GO** | With D2's F1/F2/F3 fixes in place, event-driven OR-fusion + attribution attrs are well-scoped. Golden-master fixture (this document + §7 JSON snapshot) is available. |
| **D4** — auto-enable person detection | **GO — CONDITIONAL** | 19 Protect switches are live and enumerable. Face-switch pattern-set widening required before build. Reolink/Amcrest patterns need one live-read verification pass (may reveal `_ai_person` naming) before the resolver's switch-detection is declared complete. Kill switch `CONF_AUTO_ENABLE_PERSON_DETECTION` is the escape hatch. |
| **D5** — fan_veto camera leg keyed to D3 | **GO** | Config-presence derivation is trivially correct; the F1 grouping fix in D2 is a hard prerequisite (else fan_veto would activate for the wrong room). |

### Surprises that should reshape the build

1. **F1 (Protect NVR device conflation)** — the biggest miss in the pre-cycle mental model. The plan's D2 §1.5 algorithm ("resolve to device_id and grab person sensors") is a silent-fusion bug on this registry. D2 needs a per-camera-object filter within Protect.
2. **F2 (dual-Frigate corroboration is currently phantom)** — the amendment already flagged this at the fusion policy layer; D2 must implement the collapse so Frigate-Frigate agreement is not counted as cross-integration corroboration.
3. **F5 (MAC / identifier rungs are dead)** — build them if you want future-home coverage, but Review D should NOT be asked to falsify their live behavior on Study A. Use synthetic fixtures per plan test-battery item #4.
4. **19 Protect person switches** is the whole D4 addressable surface today; a single grep during build will re-enumerate. The `unifi_count` / Protect-side auto-enable is well within scope.
5. **Face-switch pattern set is under-specified** — widen before D4 build so the "never auto-enable face" invariant is truly falsifiable.

---

## 7. Artifact provenance

- Probe script: `docs/planning/scripts/camera_resolver_dryrun_probe.py` (committed with this doc).
- Registry snapshots (mtime at probe run):
  - `core.entity_registry` ~29.7 MB, 2026-08-01 17:54
  - `core.device_registry` ~1.95 MB, 2026-08-01 17:52
  - `core.config_entries` ~584 KB, 2026-08-01 17:51
- Fixture ground-truth source: `configuration.entries[Universal Room Automation].options.camera_person_entities` (9 interior), `egress_cameras` (3), `perimeter_cameras` (9). Read live from `core.config_entries` at probe time.
- No mutations, no HA restart, no service calls.

To reproduce:
```
python3 docs/planning/scripts/camera_resolver_dryrun_probe.py > /tmp/probe.json
```

The JSON dump contains every camera device, every per-camera resolution result with sibling-device basis, and the full switch inventory. Use `jq` to slice by rung, confidence, or category.
