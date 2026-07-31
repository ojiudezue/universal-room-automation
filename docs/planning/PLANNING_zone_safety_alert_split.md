# PLANNING — Zone Safety Alert Split (backlog #12)

**Status:** Plan only, awaiting build authorization.
**Tier:** 2 (feature cycle, cross-coordinator ripple: `aggregation.py` zone chip consulting `safety.py` bands + per-room CONF).
**Framings for the two reviews:**
- **Review A** — correctness + room-type → band mapping + edge cases (missing room_type, missing sensors, sensor-sharing double-count, unit assumptions).
- **Review B** — config-drift / registration integrity + no-regression against the safety coordinator (zone chip MUST NOT alarm where the safety coordinator deliberately stays silent; outdoor/exempt honored; leak logic preserved).

---

## Institutional context verified

### Audit + prior art consulted
- `docs/planning/AUDIT_zone_safety_alert_2026_07_30.md` (source of truth for actively-wrong rooms, per-type recommendation table, and sensor-sharing double-counts). Operator-approved direction: split the zone chip to consume safety.py's already-tuned per-room-type bands rather than inline literals.
- `docs/QUALITY_CONTEXT.md` — Bug Class #22 (enum/string mismatch) and #7 (stale data source) are directly in scope: the current chip compares against string room_type via `coord.data.get(...)` freshness and could easily drift.
- `docs/Coordinator/SAFETY.md` — if present, read before build (safety authority reference).
- `MEMORY.md` entries scanned: no prior planning doc for the zone chip specifically; NM Cycle A (safety humidity 78/85/92 + outdoor exclusion via zone flag) is the immediate upstream that made the chip's 70% threshold visibly wrong.

### Greps run + verified anchors
- **Zone chip current logic:** `aggregation.py:4342-4375` — confirmed inline literals `temp > 85 or temp < 55`, `humidity > 70 or humidity < 25`, leak `state == "on"`. `room_name` fetched at :4358 then discarded (never surfaced on the entity). REUSED target for D2/D3.
- **safety.py per-type tables:**
  - `HUMIDITY_THRESHOLDS` at `safety.py:210-219` (normal 78/85/92 window 2h; bathroom 80/85/90 window 4h; basement 65/75/85; outdoor sentinel 200/200/200). REUSED.
  - `LOW_HUMIDITY_THRESHOLDS` at `safety.py:222-225` (MEDIUM 25, LOW 30). REUSED.
  - `OVERHEAT` at `safety.py:196-200` (HIGH 115 / MEDIUM 105 / LOW 100). REUSED.
  - `FREEZE_RISK` at `safety.py:191-195` (HIGH 35 / MEDIUM 40 / LOW 45). REUSED.
- **Outdoor authority:** `safety.py:1004-1026` derives outdoor via `CONF_ZONE_IS_OUTDOOR` zone flag (const.py:72) overriding `CONF_ROOM_TYPE`. REUSED — mirror the same precedence in the zone chip.
- **CONF constants:** `const.py:72` `CONF_ZONE_IS_OUTDOOR`, `const.py:96` `CONF_WATER_LEAK_SENSOR`, `const.py:312` `CONF_ROOM_TYPE`. REUSED.
- **room_type SelectSelector options** in `config_flow.py` — reviewer must re-verify current option list (audit noted "outdoor" is NOT among CONF_ROOM_TYPE options; zone flag is the outdoor authority). No new options proposed here.

### NEW additions justified
- **`resolve_safety_bands(room_type: str) -> SafetyBands`** in `safety.py` — NEW helper, but it is a *thin projection* over the four EXISTING tables (HUMIDITY_THRESHOLDS, LOW_HUMIDITY_THRESHOLDS, OVERHEAT, FREEZE_RISK). Does NOT duplicate a second table (Numbers-Get-Knobs rung-1: module constants — one source of truth).
- **Module constants for chip-specific rung selection** (which severity the chip alarms on): NEW, rung-1 in `safety.py` alongside the tables, e.g. `ZONE_CHIP_HUMIDITY_RUNG = "medium"`, `ZONE_CHIP_TEMP_HIGH_RUNG = Severity.MEDIUM`, `ZONE_CHIP_TEMP_LOW_RUNG = Severity.MEDIUM`. Chosen at rung-1 because turning them requires review (safety semantics), not operator-tunable.
- **`extra_state_attributes` on `ZoneSafetyAlertSensor`** — NEW; recovers the discarded `room_name` at aggregation.py:4358 plus a `reason` string. Feeds the Residence-tab chip UI.

---

## D1 — Shared band-resolution helper

Add to `safety.py` (module scope, alongside the existing tables):

```python
@dataclass(frozen=True)
class SafetyBands:
    temp_high_medium: float  # OVERHEAT MEDIUM (default 105)
    temp_high_low: float     # OVERHEAT LOW    (default 100)
    temp_low_medium: float   # FREEZE MEDIUM   (default 40)
    temp_low_low: float      # FREEZE LOW      (default 45)
    humidity_high_medium: float | None  # None => exempt
    humidity_high_high: float | None
    humidity_low_medium: float | None
    humidity_exempt: bool

def resolve_safety_bands(room_type: str) -> SafetyBands: ...
```

Per-room-type projection (from audit table):
- `bedroom`, `common_area`, `generic` → normal humidity (85/92), overheat 105/115, freeze 40/35, low-hum 25.
- `bathroom` → bathroom humidity (85/90 window 4h — window not consumed by the chip, medium rung is the trip).
- `laundry`, `utility` → normal humidity but temp_high raised to 95/... (per audit); if not currently a distinct room_type, fold under `generic` with a note and DO NOT invent new room_types in this cycle.
- `closet` → normal 85/92.
- `garage` → overheat MEDIUM 105 (keep default), FREEZE MEDIUM raised or kept — reviewer to confirm; **humidity exempt**.
- `basement` → basement table (75/85).
- `outdoor` (via zone flag) → fully exempt (both temp AND humidity).
- `infrastructure` / mech-closet — if not a distinct room_type today, plan to route via `generic` bands and leave the tighter 82-85 recommendation from the audit as a **follow-up** (do not silently expand room_type enum in this cycle).

### Acceptance Criteria
- **Test:** `test_resolve_safety_bands_matches_tables()` — for every currently-defined room_type, the helper returns values byte-identical to the underlying tables (proves no second copy).
- **Test:** `test_resolve_safety_bands_outdoor_exempt()` — outdoor room_type returns both temp AND humidity exempt (`humidity_exempt=True`; temp bands set to sentinels the chip treats as never-trip).
- **Verify:** grep post-build shows the helper is the SOLE consumer of chip-band selection; the four upstream tables retain their existing safety-coordinator consumers unchanged.

---

## D2 — `ZoneSafetyAlertSensor.is_on` rewrite

Replace `aggregation.py:4354-4375`. For each zone room coordinator:
1. Read `merged = {**entry.data, **entry.options}` (mirror safety.py:1017 pattern).
2. Resolve `room_type = merged.get(CONF_ROOM_TYPE, "generic")`.
3. Outdoor override: if the room's `CONF_ZONE` is in the outdoor-zone snapshot **or** `entry.data.get(CONF_ZONE_IS_OUTDOOR)` on the zone entry — treat as outdoor. Reuse the same precedence as `safety.py:1022-1026`; do NOT duplicate the snapshot logic — call a small helper (either import safety's or add a symmetric one on the zone side that reads config entries directly — reviewer picks).
4. `bands = resolve_safety_bands(room_type)`.
5. Temperature trip: `temp > bands.temp_high_medium` OR `temp < bands.temp_low_medium` (MEDIUM rung; keep chip aligned with the safety coordinator's "worth alerting a human" threshold, above the LOG-ONLY LOW rung).
6. Humidity trip: skip entirely if `bands.humidity_exempt`; else `humidity > bands.humidity_high_medium` OR (`bands.humidity_low_medium is not None` AND `humidity < bands.humidity_low_medium`).
7. **Leak**: preserved as always-safety, but only for entities whose entity_id starts with `binary_sensor.` AND whose device_class is `moisture` (or the CONF is populated — reviewer to pick the tighter of the two). Prevents dimmer-internal-temp-style config bugs from wearing a leak hat.
8. Track the first tripping `(room_name, reason)` for D3.

### Acceptance Criteria
- **Test:** Master Suite fixture (bedroom, 76°F, 42% humidity on an away-setback afternoon) → `is_on == False` (currently would fire on humidity>70 audit case pattern).
- **Test:** Patio fixture (outdoor via zone flag, 98°F, 88% humidity) → `is_on == False` (exempt).
- **Test:** Garage A fixture in Back Hallway zone (garage room_type, 102°F, 90% humidity) → `is_on == False` for humidity, `is_on == False` for temp (under 105 MEDIUM). Adjudication: garage bands render membership harmless — see §Garage A below.
- **Test:** Genuine leak (`binary_sensor.master_bath_leak` state=on) → `is_on == True`, reason includes room name.
- **Test:** Bathroom at 88% humidity within transient window → chip trips (MEDIUM=85 rung; the transient WINDOW is a safety-coordinator concern, not the chip's). Documented deliberate choice — chip is a snapshot, not a windowed evaluator.
- **Live:** After deploy, on a normal afternoon with Master Suite in away-setback, the Residence-tab red chip is OFF. Verified via `binary_sensor.ura_zone_<zone>_safety_alert` state and `extra_state_attributes.tripping_rooms == []`.
- **Live:** Trigger a leak (or use a known-live moisture sensor recent state) → chip trips within the polling interval and attributes name the room.

---

## D3 — `extra_state_attributes`

Add to `ZoneSafetyAlertSensor`:
```python
@property
def extra_state_attributes(self) -> dict[str, Any]:
    return {
        "tripping_rooms": [...],   # list[str] room names currently tripping
        "reasons": [...],          # parallel list, e.g. "humidity 89% > 85"
        "bands_source": "safety.resolve_safety_bands",
    }
```
Populated during `is_on` evaluation (cached on `self` for the attributes read, or re-derived — reviewer picks; keep it simple/synchronous, no I/O).

### Acceptance Criteria
- **Sensor:** `binary_sensor.ura_zone_master_suite_safety_alert.attributes.tripping_rooms` renders as a list on the Residence tab (chip label shows the room name).
- **Test:** Two rooms tripping same zone → both appear in the list in stable order (sorted by room name).
- **Live:** During any live trip, HA Developer Tools shows both `tripping_rooms` and `reasons`.

---

## D4 (optional) — `comfort_drift` sibling attribute

**Marginal-benefit decomposition (Marginal-Benefit rule):** the OLD chip's 70%/85°F thresholds carried a comfort-grade signal (housekeeping-worthy humidity, not-yet-safety-worthy heat). The safety-grade rewrite drops that signal.

- **Simplest version:** an `extra_state_attributes["comfort_drift_rooms"]` list on the same sensor, populated by the OLD-style thresholds (85/55, 70/25), no new entity, no new signal.
- **Full version:** a sibling `binary_sensor.ura_zone_<zone>_comfort_drift`.
- **Marginal cost of full version:** new entity registration, new unique_id, new options-flow surface (eventually), new dashboard chip. Categorically-risky ingredient: none, but it's config surface expansion.
- **Recommendation:** ship the ATTRIBUTE-ONLY version (D4a) in this cycle. Park the sibling-sensor design as backlog with the trigger "if operators actually consult `comfort_drift_rooms` and want per-room dashboarding, promote to entity." No lost information; deferred entity surface.

### Acceptance Criteria (D4a)
- **Sensor:** `attributes.comfort_drift_rooms` populated on the SAME `ZoneSafetyAlertSensor` when a room crosses the old comfort-grade lines but not the new safety-grade lines.
- **Test:** Master at 72°F/72% humidity → `is_on == False`, `comfort_drift_rooms == ["Master Bedroom"]`.

---

## Garage A / Back Hallway adjudication

Garage A (room_type=`garage`) currently lives inside the Back Hallway zone. Under the new bands, garage is humidity-EXEMPT and its temp-high MEDIUM stays at 105 (the audit recommendation), so the Back Hallway zone chip will NOT falsely trip on garage humidity spikes or ordinary garage summer heat. **Recommendation: leave zone membership as-is; the room-type bands make it harmless.** Operator may still choose to move Garage A into a dedicated Garage/Outbuilding zone for dashboard clarity — flagged as an operator decision, NOT a code change in this cycle.

---

## Files touched
- `custom_components/universal_room_automation/domain_coordinators/safety.py` — add `SafetyBands` dataclass + `resolve_safety_bands` + `ZONE_CHIP_*_RUNG` constants. NO change to existing table values or safety-coordinator logic.
- `custom_components/universal_room_automation/aggregation.py` — rewrite `ZoneSafetyAlertSensor.is_on` (4354-4375), add `extra_state_attributes`, add outdoor-zone snapshot access (import from safety or symmetric read).
- `quality/tests/test_zone_safety_alert.py` — NEW test file per D1/D2/D3/D4a acceptance.
- `docs/QUALITY_CONTEXT.md` — reviewer to consider whether "chip-vs-coordinator threshold drift" merits a new bug class after fix-up.
- `docs/readmes/README_v<next>.md` — write pre-deploy with prospective Live criteria (Master red chip OFF; genuine leak trips; attrs render).

## Files NOT touched
- `config_flow.py` / `options_flow.py` — no new operator-facing knobs (rung-1 constants only).
- `safety.py` existing hazard-evaluation code — bands helper is read-only projection.
- Any other zone sensor.

---

## Verification steps
1. `PYTHONPATH=quality python3 -m pytest quality/tests/test_zone_safety_alert.py -v` — all D1/D2/D3/D4a tests pass.
2. Full suite green: `PYTHONPATH=quality python3 -m pytest quality/tests/ -v`.
3. Grep confirms `HUMIDITY_THRESHOLDS`, `LOW_HUMIDITY_THRESHOLDS`, `OVERHEAT`, `FREEZE_RISK` are unchanged and still consumed by `_handle_humidity` / freeze / overheat paths in safety.py.
4. Grep confirms no inline literal `85`, `55`, `70`, `25` remains inside `ZoneSafetyAlertSensor`.
5. Tier-2 review (A + B framings), fix CRITICAL/HIGH.
6. `git tag pre-review-v<version>` before applying review fixes.
7. Deploy via `./scripts/deploy.sh`.
8. Live validation, write results back into `README_v<version>.md` per CLAUDE.md.

---

## Deferred / parked
- Sibling `comfort_drift` **sensor entity** (D4-full). Trigger to revisit: operator consumes the attribute and wants per-room chips.
- Tighter infrastructure bands (82-85 / 60% humidity) — requires new room_type or CONF flag; own cycle.
- Kitchen Pantry dimmer-internal-temp config repair — operator-side, not code.
- Sensor-sharing double-count remediation (Media/Media Closet etc.) — config hygiene, out of scope.
