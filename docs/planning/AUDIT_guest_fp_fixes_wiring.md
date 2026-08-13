# AUDIT — Guest false-positive fixes: live wiring + recurrence check

**Trigger:** premise correction on the planned GUEST-FP-1 cycle — both fixes
(Fix A LOST-away trusted admission, Fix B outdoor-zone census exclusion)
appear to have shipped in prior cycles. Verify wiring end-to-end against
the running house before closing the backlog card
`project_guest_mode_false_positive_backlog`.

**Auditor:** ura-planner (2026-08-12)
**Sources of truth used:**
- Current source: `custom_components/universal_room_automation/domain_coordinators/presence.py`, `camera_census.py`, `person_coordinator.py`, `domain_coordinators/safety.py`, `const.py`
- Live HA storage: `/Users/okosisi/ha-config/.storage/core.config_entries` (Samba-mounted, verified per CLAUDE.md data-source rule)
- Backlog memory: `project_guest_mode_false_positive_backlog` (51d stale — all file:line claims re-verified)
- Related shipped memory: `project_presence_guest_latch_and_veto_gap` (v5.16.0)

---

## 1. Fix wiring in current source

### Fix A — LOST-but-AWAY as trusted (v4.7.14.1 H3 lineage / v5.7.0 WS-A)

**Helper definition:** `_tracking_active_or_lost_away` at `presence.py:169-191`. Returns True iff `tracking_status == ACTIVE` OR (`tracking_status ∈ {LOST, STALE}` AND `location == "away"`). Correct semantics per Fix A spec.

**Wiring — split verdict:**

| Consumer | Site | Wired to Fix A helper? |
|---|---|---|
| Path-α trusted classifier (`excluded_persons` map, `_tracked_persons_count_trusted`) | `presence.py:5122-5137` (`track_ok = _tracking_active(info)`) | **NO** — still uses the strict `_tracking_active` (ACTIVE-only, defined `presence.py:5068-5079`). A LOST-away person is STILL emitted into `_excluded_persons` with reason `tracking_status=lost` and STILL reduces `_tracked_persons_count_trusted`. |
| Path-β denominator (WS-A AWAY veto) | `presence.py:5158-5182` | **YES** — uses `_tracking_active_or_lost_away_local`. LOST-away is admitted, veto fires for the empty-house case. Preserved by v5.16.0 sustained-external-empty discriminator. |

**Meaning:** the helper shipped, and the WS-A2 path-β load-bearing consumer is wired. But the path-α trusted-classifier — which is what the backlog memo's diagnosis specifically named (`excluded_persons: {"Ziri":"tracking_status=lost"}` on `sensor.ura_presence_coordinator_presence_house_state`) — is NOT rewired. The `excluded_persons` sensor attr and `tracked_persons_count_trusted` count STILL exhibit the 2026-06-22 shape for a LOST-away person.

**Does that gap actually feed the guest gate?** No — verified by trace. `_guest_gate_armed` (`presence.py:4743-4790`) takes `unidentified_count`, `census_confidence`, `now`. `unidentified_count` is set from the camera-census SIGNAL_CENSUS_UPDATED payload (`presence.py:4211` ← `camera_census.py:1136` ← `house_result.unidentified_count = camera_total - identified` in the FullCensusResult). It is NOT computed as `census_count - tracked_persons_count_trusted`. So even with a LOST-away person shown in `excluded_persons`, the guest gate itself is not directly gated on the path-α classifier. The path-α classifier is load-bearing for the WS-A path-α AWAY veto (which requires all tracked persons away with tracked_count>0), but the empty-house case is handled by path β.

**Residual (small) gap:** the `excluded_persons` sensor attribute and `tracked_persons_count_trusted` remain confusing to operator debugging — they still show a LOST-away person as excluded and reduce the trusted count. Cosmetic/diagnostic today, but the shape mismatch means an operator reading the sensor cannot verify "LOST-away is admitted" without knowing to look at the path-β numerator separately. Track as a diagnostic-clarity backlog item, NOT a live functional bug.

### Fix B — Outdoor zones never contribute census

**Wiring:**

| Consumer | Site | Wired? |
|---|---|---|
| Outdoor authority (single source) | `domain_coordinators/safety.py:510-552` `outdoor_zone_names_snapshot(hass)` — reads both `ENTRY_TYPE_ZONE` legacy entries and `ENTRY_TYPE_ZONE_MANAGER.zones[<name>][CONF_ZONE_IS_OUTDOOR]`. | **YES** — shipped v5.7.0 WS-A4. |
| Presence outdoor snapshot | `presence.py:1600-1649` (twin of the safety helper, per-cycle read) | **YES** |
| WS-A2 indoor-only zone-occupied gate for path β | `presence.py:5222-5226` `any_indoor_zone_occupied` | **YES** — outdoor motion cannot suppress the empty-house veto. |
| Camera-census `interior_count` payload | `camera_census.py:1086-1143` (SIGNAL_CENSUS_UPDATED producer) | **NO ROOM-→-ZONE FILTER FOUND** in `_run_census` / `_calculate_house_census`. `interior_count = house_result.total_persons` is emitted verbatim. However, see mitigation below. |

**Mitigation for the missing camera-census filter:** the "Outside" zone in live config (see §2) has ONE room (**Patio**, entry_id `01KDRKZ2V8EP2B7Q9FH3F087ES`) with:
- `zone_cameras`: **NONE** on the zone entry (unlike Back Hallway / Entertainment / Upstairs which each list `zone_cameras`).
- Room-level `motion_sensors`: `binary_sensor.occupancy_lux_temp_humidity_hobeian_patioleft_presence`, `binary_sensor.occupancy_lux_temp_humidity_hobeian_patioright_presence` (Zigbee mmWave/PIR, NOT camera person-detection sensors).
- Room-level `occupancy_sensors`: **empty**.
- Room-level `presence_sensors`: **empty**.

The house-side `_calculate_house_census` consumes camera person-detection entities and BLE, not raw motion PIRs. So today, **the Patio zone's motion cannot flow into `interior_count`** regardless of the missing camera-census outdoor filter — the input class doesn't reach that consumer.

**Consequence:** Fix B is *structurally* effective for the current house configuration. If the operator ever attaches a Frigate/camera person-detection sensor to a room whose `zone == "Outside"` (or any other outdoor-flagged zone), the camera-census producer would need the outdoor filter to prevent that person from being counted in `interior_count`. That is a latent gap, not a live one — flagged as **Residual-B1** (see §4).

---

## 2. Live config — "Outside" zone wiring

Verified from `/Users/okosisi/ha-config/.storage/core.config_entries` (modified 2026-07-31):

- **Zone-manager entry** `01KJEC3ARCN49EVC80VZZPHCZQ` (title "URA: Zone Manager") holds `options.zones.Outside`:
  - `"zone_is_outdoor": true` ✅
  - `"zone_rooms": ["01KDRKZ2V8EP2B7Q9FH3F087ES"]` (Patio only)
  - No `zone_cameras`, no `zone_thermostat`, no `zone_persons` — appropriately minimal for an outdoor zone.
- **Patio room entry** `01KDRKZ2V8EP2B7Q9FH3F087ES` has `"zone": "Outside"` in both data and options.
- **`outdoor_zone_names_snapshot(hass)` returns:** `{"Outside"}` — confirmed by tracing `safety.py:528-544`: the zone-manager branch (line 536) walks `merged["zones"]` and picks up `Outside` because its dict has `zone_is_outdoor: True`.

**Reconciliation of today's boot warning `zone fallback unavailable: zone=Outside scope=nonsleep (zone not registered in zone_manager.zones)`:**
- The warning does NOT indicate a config gap. `Outside` IS registered in the zone-manager storage (verified above). The warning originates from a runtime code path (v4.7.13/v4.7.15 zone fallback) that looks up `zone_manager.zones` — the RUNTIME dict on the ZoneManagerCoordinator — not the config-entry storage. Either (a) that runtime dict is populated lazily after the fallback fires, or (b) it deliberately excludes zones with no `zone_thermostat` / no controllable actuators (Outside qualifies), or (c) it's a benign check for a scope the Outside zone legitimately doesn't participate in.
- The outdoor authority for exclusion (`outdoor_zone_names_snapshot`) reads the config-entry storage directly, so it is unaffected by whatever the runtime `zone_manager.zones` dict contains at boot.
- **Actionable:** the boot warning is a separate low-severity diagnostic-clarity item (grep for the emitter, decide if it should suppress for `zone_is_outdoor=True` zones or zones with no thermostat). Not blocking. Flagged as **Residual-B2**.

**Verdict for the operator's specific question ("is Outside actually flagged?"):** ✅ YES. `zone_is_outdoor: True` present in the zone-manager sub-entry; WS-A4 exclusion covers it.

---

## 3. Recurrence check — guest false-positive episodes since fixes shipped

**Requested:** query URA DB and/or HA recorder for `house_state=guest` episodes since ~July (v5.16.0 shipped 2026-07-13).

**Not executed in this audit.** MCP `ura-sqlite` and `ha-mcp` tools were not invoked in this subagent's tool budget (Read/Grep/Web-only). The audit is otherwise complete against source + storage; the DB query is a separable step. Recommended query for the operator or a follow-up validator:

```sql
-- URA DB (~/ha-config/universal_room_automation/data/universal_room_automation.db)
SELECT ts, house_state, prev_state, transition_reason
FROM house_state_transitions
WHERE house_state = 'guest' AND ts >= '2026-07-13'
ORDER BY ts;
```

And, for each row, cross-reference the surrounding presence-house-state attrs
(HA recorder `states` / `state_attributes` for
`sensor.ura_presence_coordinator_presence_house_state`) within ±10 min of the
transition to recover `census_count`, `unidentified_count`, `excluded_persons`,
`outdoor_zones`. Presence of a resident-only shape (unidentified>0 with
`excluded_persons == {}` and `census_count > tracked_count`) is the
2026-06-22 signature.

**Operator disposition:** approve/decline the DB probe; if approved, dispatch
`ura-validator` with the two queries above and paste results into a follow-up
addendum to this audit.

---

## 4. Verdict

**Overall:** ✅ **Fixes are wired and effective for the current live house configuration.** The specific 2026-06-22 causal chain cannot fire today:

- Path-β empty-house AWAY veto admits LOST-away persons (Fix A helper wired at `presence.py:5162`), so the empty-house case is handled correctly.
- The single "Outside"-zone room (Patio) has no camera-person or occupancy-sensor inputs into `_calculate_house_census`, so it cannot inflate `interior_count`/`_census_count` regardless of camera-census outdoor filtering.
- `outdoor_zone_names_snapshot()` correctly returns `{"Outside"}` from the live config; `any_indoor_zone_occupied` (`presence.py:5222-5226`) excludes the Patio's motion from the WS-A path-β zone-occupied gate.

**Backlog card `project_guest_mode_false_positive_backlog` — recommended action:** CLOSE with pointer to this audit. Update the memory body to (a) mark the two proposed fix candidates as SHIPPED, (b) name the two small residual items below.

**Residual items (small, not blockers):**

- **Residual-A1 (diagnostic-clarity):** Path-α trusted classifier at `presence.py:5122-5137` still uses strict `_tracking_active`; the `excluded_persons` sensor attribute and `tracked_persons_count_trusted` continue to show a LOST-away person as excluded. Not a live functional bug (guest gate does not read this), but confuses operator debugging. Fix is a one-line predicate swap + a threshold constant; can be batched with any future presence hotfix.
- **Residual-B1 (latent):** `camera_census._calculate_house_census` does NOT filter person counts by room→outdoor-zone. Live-safe today because no outdoor-flagged zone has camera person-detection inputs configured. Latent if the operator ever attaches a camera person-detection sensor to a room in an outdoor zone (e.g. porch Frigate, doorbell person-count on Patio). File a small planning card.
- **Residual-B2 (diagnostic noise):** Boot warning `zone fallback unavailable: zone=Outside scope=nonsleep (zone not registered in zone_manager.zones)` is a benign runtime-dict miss that does not affect the outdoor exclusion. Consider suppressing for zones with `zone_is_outdoor=True` or no `zone_thermostat`. One-line grep to find the emitter.
- **Recurrence check:** not executed here — run the two queries in §3 and append results before final closure.

---

## Non-goals

- No code changes proposed. Residuals A1/B1/B2 are captured for backlog scoping, not built here.
- No changes to Bermuda LOST semantics or `tracking_status` field.
- No changes to the v5.16.0 GUEST latch, path-β discriminator, or WS-A4 outdoor authority.

---

## §3 Recurrence results (executed 2026-08-13, orchestrator, read-only)

`house_state_log` since 2026-07-13: **50 guest ENTRY episodes** across 22 of 31 days
(1–7/day; heaviest 07-13→07-17 and 08-01). Only **2 night-hour (00–06) entries**
(07-17 00:19, 07-19 00:44) — the 2026-06-22 signature (night guest with nobody) is
essentially absent. Pattern includes rapid guest↔home_day flapping within the hour
(e.g. 07-14: guest 13:48 → home_day 14:25 → guest 15:37).

**Interpretation requires operator ground truth:** if mid-July/early-August actually
had frequent daytime guests, this is healthy behavior and the card closes cleanly.
If not, there is a *different* FP flavor (daytime, census-driven, flappy) distinct
from the June lost-away/outdoor mechanism — which the wiring audit shows is fixed.
Escalation path if operator says "no guests those days": pull presence attrs around
2–3 sample episodes for the census/unidentified shape.
