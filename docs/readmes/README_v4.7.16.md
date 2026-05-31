# v4.7.16 — Room-level veto + Bermuda-scanner-aware density weighting

**Tier:** 2-DB (three parallel reviewers, framings A/B/C per CLAUDE.md)
**Predecessor sprint:** Bug Class #48 trust-hierarchy universalization
**Sibling cycles (in flight):** v4.7.14.1 (forgotten-phone hotfix), v4.7.15 (shared veto helper)
**Sprint link doc:** `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md`

> This README is the operator runbook for v4.7.16. Read alongside the
> planning doc (`docs/planning/PLANNING_v4.7.16_room_level_veto_density_weighting.md`)
> and the sprint link doc.

---

## 1. What v4.7.16 changes for the operator

Four deliverables landed:

| Deliverable | Operator-visible change | Surfaces |
|---|---|---|
| **D1** | `ble_tier` (1/2/0) classification now derivable per room | New method `PersonTrackingCoordinator.get_ble_tier(room_name)` |
| **D2** | New per-room diagnostic sensor `sensor.ura_<room>_signal_inventory` | One entity per room config entry, DIAGNOSTIC category |
| **D3** | Per-room weighted veto in `_run_inference` zone-iterates-rooms loop | Diagnostic dict `self._v4716_zone_verdicts` populated each cycle |
| **D4** | New per-room boolean field `disable_camera_presence` | Config flow (initial + options), strings, `_discover_zone_cameras` opt-out |

No DB migrations. No schema changes. No new tables. No anomaly_log row-rate
changes. v4.7.16 is purely additive on top of the v3.2.4 `CONF_SCANNER_AREAS`
infrastructure (reused, not modified).

---

## 2. Operator setup guide — `CONF_SCANNER_AREAS` (REUSED from v3.2.4)

`CONF_SCANNER_AREAS` is the v3.2.4-era field that lets a room "borrow" a BLE
scanner from a neighbor when it has no scanner of its own. v4.7.16 reuses this
field as the canonical input to the per-room `ble_tier` classification.

### Tier mapping (canonical)

| Room config | ble_tier | Meaning |
|---|---|---|
| `area_id` set, no `scanner_areas` | **1** | Direct / dense — room has its own scanner |
| `area_id` set, `scanner_areas` populated | **2** | Borrowing / sparse — relies on a neighbor's scanner |
| No `area_id` configured | **0** | Unmapped — falls back to multi-tier sensor agreement |

### Example: borrowing a scanner for `living_room`

The Living Room has no BLE scanner of its own, but the adjacent Family Room
has a Shelly Plus BLE proxy.

1. Settings → Devices & Services → URA → Living Room → **Configure**.
2. In the **Sensors** section, find **BLE Scanner Areas (Optional)** —
   select `Family Room` from the area dropdown.
3. Save. URA reloads the Living Room entry.
4. Probe (Developer Tools → Template):
   ```
   {{ state_attr('sensor.ura_room_living_room_signal_inventory', 'ble_tier') }}
   ```
   Expected: `2` within 30 s of reload.

The same room's signal_inventory sensor state should read
`sparse_with_fallback`.

---

## 3. Per-room diagnostic sensor probes (D2)

### Pre-deploy snapshot

Before deploy, the `signal_inventory` sensors don't exist:

```yaml
# Developer Tools → Template
{{ states.sensor | selectattr('entity_id', 'match', '^sensor\\.ura_room_.*_signal_inventory$') | list | length }}
# expected: 0
```

### Post-deploy validation

After HA restarts on v4.7.16:

```yaml
# Count of signal_inventory sensors should equal the number of URA room entries
{{ states.sensor | selectattr('entity_id', 'match', '^sensor\\.ura_room_.*_signal_inventory$') | list | length }}
# expected: one per room config entry
```

For each room, verify the rolled-up state label is non-`unknown`:

```yaml
{{ states('sensor.ura_room_master_bedroom_signal_inventory') }}
# expected: one of dense / sparse_with_fallback / sparse_no_fallback / pir_only / camera_only / none
```

Verify the numeric `ble_tier` attribute aligns with the room config:

```yaml
{{ state_attr('sensor.ura_room_master_bedroom_signal_inventory', 'ble_tier') }}
# Master bedroom with own scanner → expected: 1
```

```yaml
{{ state_attr('sensor.ura_room_living_room_signal_inventory', 'ble_tier') }}
# Living room with scanner_areas=[family_room] → expected: 2
```

```yaml
{{ state_attr('sensor.ura_room_closet_signal_inventory', 'ble_tier') }}
# Closet with no area_id → expected: 0
```

The full attribute set per sensor:
- `ble_tier`: int (1/2/0)
- `has_mmwave`: bool
- `has_pir`: bool
- `has_camera`: bool
- `has_ble_fallback_room`: bool (true iff ble_tier == 2)
- `scanner_areas`: list[str]
- `area_id`: str | None
- `disable_camera_presence`: bool (mirrors the D4 opt-out)

Per Bug Class #47 (lazy canonical UI surface): the numeric tier lives only in
attributes; state is the human-readable label. Do NOT write automations that
compare state to `"1"`/`"2"` — read the `ble_tier` attribute instead.

---

## 4. Per-room camera-presence opt-out (D4)

### When to use the opt-out

URA's camera-based presence tier (Tier 2 in the `ZonePresenceTracker`
vocabulary) listens to camera person-detection binary sensors. Some rooms
generate persistent false positives:

- Rooms with a TV in view of the camera (reflections of news anchors,
  movie people).
- Hallways with sun-glare onto walls that the classifier reads as a person.
- Rooms where the camera's person-detection model is otherwise unreliable.

For these rooms, set `CONF_DISABLE_CAMERA_PRESENCE=True`. The room's
mmWave / PIR / BLE signals continue to contribute; only the camera tier is
muted at registration time.

### Opt-out setup

1. Settings → Devices & Services → URA → [Room] → **Configure**.
2. In the **Sensors** section, immediately after **BLE Scanner Areas
   (Optional)**, toggle **Disable Camera Presence (Opt-Out)** to ON.
3. Save. URA reloads the room entry; the zone owning that room's `area_id`
   stops receiving camera registrations from that area.
4. Verify the room's signal_inventory sensor reflects the opt-out:
   ```yaml
   {{ state_attr('sensor.ura_room_master_hallway_signal_inventory', 'has_camera') }}
   # expected: false (post-opt-out)
   ```

The log will show one INFO line per opted-out area at boot:

```
v4.7.16 D4: 3 room(s) opting out of camera-presence: ['family_room', 'master_hallway', 'upstairs_hall']
Camera-presence opt-out: skipping 2 cameras for zone Entertainment (area family_room) per CONF_DISABLE_CAMERA_PRESENCE
```

---

## 5. Rollback procedure

v4.7.16 has zero migration risk: both new config fields use lazy default at
read time (Bug Class #46 doctrine). Rolling back any subset of D1–D4 is safe
and idempotent.

### Clear the camera-presence opt-out for a room

1. Settings → Devices & Services → URA → [Room] → Configure.
2. Toggle **Disable Camera Presence (Opt-Out)** to OFF (or clear it).
3. Save. URA reloads; cameras for the room's area re-register on next
   discovery cycle. The room's `has_camera` attribute on its
   signal_inventory sensor returns to its pre-opt-out value within 30 s.

### Clear `scanner_areas` for a room (revert to tier 1 / tier 0)

1. Settings → Devices & Services → URA → [Room] → Configure.
2. In the **Sensors** section, find **BLE Scanner Areas (Optional)** and
   remove all selections.
3. Save. URA reloads:
   - If `area_id` is still set: `ble_tier` reverts to **1**.
   - If `area_id` is also cleared: `ble_tier` reverts to **0**.

### Full cycle rollback (revert v4.7.16 → previous version)

Standard `./scripts/deploy.sh` rollback to the previous version pointer. No
DB migration needed. Existing config entries continue to read the same
fields (the new keys simply become inert).

---

## 6. Live validation checklist (Review D — post-deploy)

After HA restarts on v4.7.16, verify each item:

- [ ] **D1:** For each room, `state_attr('sensor.ura_room_<slug>_signal_inventory', 'ble_tier')` returns an int (`0`, `1`, or `2`).
- [ ] **D2:** Every URA room config entry has exactly one
  `sensor.ura_room_<slug>_signal_inventory` entity registered. Count
  equals the number of room entries.
- [ ] **D2:** At least one room shows `ble_tier=1` (operator's house has
  bedrooms with their own scanners — confirmed in 2026-05-30 audit).
- [ ] **D2:** At least one room shows `ble_tier=2` IF the operator has
  configured `scanner_areas` on any room.
- [ ] **D3:** `_run_inference` does not raise. Confirm no
  `v4.7.16 D3: per-room weighting block failed` WARNINGs in the log.
- [ ] **D3:** Since v4.7.15 is shipping in parallel, expect either:
  - "helper available" — `_v4716_zone_verdicts[zone]["veto_reason"]` is a
    real reason string, OR
  - "helper unavailable" — `veto_reason == "helper_unavailable"` and
    behavior is preserved pre-v4.7.16. **Either outcome is acceptable
    during the v4.7.15 integration window.**
- [ ] **D4:** For each room with `CONF_DISABLE_CAMERA_PRESENCE=True`,
  `state_attr('sensor.ura_room_<slug>_signal_inventory', 'has_camera')`
  returns `false`.
- [ ] **D4:** The "v4.7.16 D4" INFO log line lists the expected opted-out
  rooms at boot.

### Pass criteria summary

- No WARNINGs from `v4.7.16 D3` or `v4.7.16 D4` source-tagged lines.
- Every room config entry has its `signal_inventory` sensor visible.
- Numeric `ble_tier` matches operator's house topology expectation.
- Opt-out rooms show `has_camera=false`.

---

## 7. Known limitations + deferrals

Per Plan Completion Tracking (CLAUDE.md):

| Deferral | Reason | Where it lands |
|---|---|---|
| Per-camera opt-out (vs per-room) | Investigation §9 Q1: per-room is sufficient | Backlog |
| Camera-shadow mode (log-only, no signal contribution) | Investigation §9 Q4 open | Backlog |
| Per-room `BLE_TIER_2_WEIGHT` override (vs global) | Global knob covers operator's needs | Conditional v4.7.16.x |
| Bermuda-scanner enumeration sensor | Useful but standalone | v4.7.16.x or v4.7.17 |
| Part B durability audit (Frigate vs Protect 7-day) | Needs its own cycle | v4.7.17 candidate |
| Deprecating `sensor.ura_house_state_confidence` | Audit zero readers first | v5.0 cleanup |
| Sum-vs-max aggregation decision | Flagged for Reviewer A | First review pass |
| Helper signature verification | Forward reference to v4.7.15 | Post-v4.7.15-merge integration pass |

### D3 status: complete-pending-helper-verification

The D3 call site invokes `should_veto_due_to_reliable_signals` against the
documented contract:

```python
helper(
    reliable_signals=reliable_signals,
    transient_signals=transient_signals,
    state_context=state_context,
) -> VetoDecision(fired, confidence, reason)
```

Each call site is marked with `# v4.7.16 D3: verify helper signature post
v4.7.15 lands` so the post-v4.7.15-merge integration pass can mechanically
locate them. The call is guarded by `getattr(self,
"should_veto_due_to_reliable_signals", None)` and a `try`/`except` block so
that v4.7.16 ships safely BEFORE v4.7.15 lands — in that window
`veto_reason="helper_unavailable"` and behavior is preserved.

---

## 8. Cross-cycle references

- **v4.7.14** — Away-state person-tracker trust veto (Bug Class #48 origin
  pattern). v4.7.16 D3 generalizes the per-zone weight idea introduced here.
  See `docs/readmes/README_v4.7.14.md` and
  `docs/planning/PLANNING_v4.7.14_away_state_person_tracker_trust.md`.
- **v4.7.14.1** (sibling) — Forgotten-phone hotfix. Closes the carve-out
  gap v4.7.14 opened. Independent of v4.7.16.
- **v4.7.15** (sibling) — Shared veto helper extraction
  (`should_veto_due_to_reliable_signals` on `PresenceCoordinator`).
  v4.7.16 D3 is the first consumer of this helper at the room level.
- **`docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md`** — Sprint-level
  link doc connecting v4.7.14.1, v4.7.15, v4.7.16 into the trust-hierarchy
  universalization arc.

---

## 9. Bug class watchlist

Per planning doc §5:

| Bug Class | Risk in v4.7.16 | Mitigation |
|---|---|---|
| **#20** — Concurrent Config Entry Reload Race | D4 toggles a config field that triggers reload; D2 sensor reads from a coordinator whose data may be mid-rebuild | D4 reads opt-out at discovery time (one-shot per discovery cycle); D2 sensor lookups are guarded with try/except fail-safe |
| **#44** — Test Fixture Authority | New tests touch const, presence, sensor, config_flow | Tests use `importlib.util` to load `const.py` directly (avoids the HA import chain); behavioral assertions read constants from production source, not hand-copied |
| **#46** — Lazy Derivation, No Migration | D1 `get_ble_tier`, D2 sensor, D4 opt-out all derive at read time | NO migration helper added. AST test enforces absence of `_migrate_*` for v4.7.16 fields |
| **#47** — Lazy Canonical Resolution UI Surface | D2 sensor exposes `ble_tier` to operators | State is human-readable label; numeric tier lives in attributes only. AST test enforces |

(Bug Class #48 is the subject of v4.7.15 — v4.7.16 is the consumer of its
veto-helper output, not the introducer.)

---

## 10. Files changed in v4.7.16

| File | What changed |
|---|---|
| `const.py` | NEW `CONF_DISABLE_CAMERA_PRESENCE` + `DEFAULT_DISABLE_CAMERA_PRESENCE` + `BLE_TIER_2_WEIGHT` constants |
| `config_flow.py` | NEW `CONF_DISABLE_CAMERA_PRESENCE` selector in initial + options flow per-room Sensors section |
| `strings.json` | NEW label + description for `disable_camera_presence` in both flow surfaces |
| `person_coordinator.py` | NEW public method `get_ble_tier(room_name)` |
| `domain_coordinators/presence.py` | NEW `_rooms_opting_out_of_camera_presence` helper, NEW D4 opt-out branch in `_discover_zone_cameras`, NEW D3 zone-iterates-rooms weighted veto block in `_run_inference`, NEW init field `_v4716_zone_verdicts` |
| `sensor.py` | NEW `RoomSignalInventorySensor` class + registration in room async_setup_entry |
| `quality/tests/test_v4716_room_veto_density.py` | NEW 33-test cycle harness (source-grep + lightweight behavioral) |
| `docs/readmes/README_v4.7.16.md` | This document |

**LoC delta** (against `3231346` baseline): ~600 LoC source + ~600 LoC tests
+ ~360 LoC README. No code removed.

---

## 11. Recall hooks

- "Resume v4.7.16 room-level veto"
- "Plan BLE tier exposure"
- "Per-room camera opt-out"
- "v4.7.16 live validation"
