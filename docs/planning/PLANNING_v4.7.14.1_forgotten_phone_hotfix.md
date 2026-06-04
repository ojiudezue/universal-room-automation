# PLANNING v4.7.14.1 — Hotfix: Close v4.7.14 Forgotten-Phone Gaps

**Tier:** 2-DB (operator-elevated — see Section 5)
**Sibling cycles in sprint:** v4.7.15 (sleep-state trust universalization), v4.7.16 (TBD — see master link doc)
**Master link doc:** `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md`
**Estimated size:** ~25-40 LoC + ~10 cycle tests, single file (`domain_coordinators/presence.py`) plus diagnostic surface in `sensor.py`.
**Predecessor:** v4.7.14 (LIVE 2026-05-30 22:00 UTC).

---

## 0. Institutional context verified

Before writing the deliverables I grep-verified the assertions below. Every constant, class, signal, and line cited here was read in this session.

### 0.1 CONF_* audit (REUSE vs NEW)

| Constant | Status | Citation |
|---|---|---|
| `CONF_TRACKED_PERSONS` | REUSED (no change) | `const.py:152` — `Final = "tracked_persons"` |
| `CONF_PERSON_DECAY_TIMEOUT` | REUSED (referenced for context only — controls when `tracking_status` decays to STALE/LOST) | `const.py:157`, `DEFAULT = 300` at `const.py:158` |
| `TRACKING_STATUS_ACTIVE` | REUSED in NEW filter logic (H3) | `const.py:161` — `Final = "active"` |
| `TRACKING_STATUS_STALE` | REUSED in NEW filter logic (H3) | `const.py:162` — `Final = "stale"` |
| `TRACKING_STATUS_LOST` | REUSED in NEW filter logic (H3) | `const.py:163` — `Final = "lost"` |
| `STALE_THRESHOLD_SECONDS` | REUSED (referenced for context only) | `const.py:166` |
| `TRANSIT_PHONE_LEFT_BEHIND_HOURS` | REUSED (referenced — separate from `PersonPhoneLeftBehindSensor.PHONE_LEFT_BEHIND_HOURS=1.0` class attribute; the const is for transit_validator at `const.py:829`) | `const.py:829` |
| `DOMAIN` | REUSED | already imported in `presence.py` |

**NO NEW CONF_\* proposed.** All three deliverables consume existing signals; no new operator-tunable knobs are introduced. Confidence thresholds are hardcoded sentinels — explicit non-goal of this hotfix to expose tuning.

### 0.2 `phone_left_behind` signal — REUSED, not rebuilt

Class **`PersonPhoneLeftBehindSensor`** (NOT `PersonPhoneLeftBehindBinarySensor` — the user's prompt naming was slightly off; the build agent should reference the correct symbol).

- Defined: `custom_components/universal_room_automation/binary_sensor.py:973` (class body extends to ~`:1084`).
- Constructed once per tracked person: `binary_sensor.py:102` — `census_binary.append(PersonPhoneLeftBehindSensor(hass, entry, person_name))`.
- Entity ID pattern: `binary_sensor.<person_id_lowercased>_phone_left_behind` (unique_id at `binary_sensor.py:1000`; `_attr_has_entity_name=True` at `:989` plus `_attr_name=f"{person_id} Phone Left Behind"` at `:1001` produces the device-namespaced entity).
- `_attr_entity_registry_enabled_default = False` (`:988`) — **the sensor exists but is disabled by default.** The hotfix MUST handle the case where the entity is disabled / not in `hass.states` (read returns `None` → treat as "not flagged" → person counts toward veto normally).
- Trigger logic (`binary_sensor.py:1010-1044`): True when BLE places person in a room AND no camera has seen them in `PHONE_LEFT_BEHIND_HOURS=1.0` (`:991`) AND census sees zero unidentified persons AND outside sleep hours (22-07 local).
- Attributes exposed (`binary_sensor.py:1078-1084`): `person_id`, `ble_location`, `hours_since_camera_sighting`, `phone_left_behind_hours`, `census_persons_in_house`.

**Design intent (verified from class docstring at `:974-983`):** "BLE says person is home but camera hasn't seen them recently" — the canonical "phone is sitting on the kitchen counter while the person is at work" signal. This is exactly the inverse trust signal H2 needs.

**REUSE statement:** H2 REUSES `binary_sensor.<person>_phone_left_behind` from `binary_sensor.py:973-1084`. The hotfix does NOT rebuild this detection. It reads the existing entity state via `hass.states.get(...)` at veto-compute time inside `presence.py`.

### 0.3 `tracking_status` signal — REUSED, not rebuilt

- Constants: `const.py:161-163` (cited above).
- Field set in `person_coordinator.py`:
  - To `ACTIVE` when Bermuda area resolves: `:213` (`tracking_status = TRACKING_STATUS_ACTIVE`), persisted into `person_data[person_name]["tracking_status"]` at `:222`.
  - To `STALE` when Bermuda stops updating but we're inside `decay_timeout`: `:288`, persisted at `:299` (method `"bermuda_decay"`).
  - To `LOST` when no Bermuda data at all OR person tracker says `home`/`away` only: `:153`, `:333`, `:345`, `:377` — note four set-sites because of the cross-product of (no Bermuda sensor, Bermuda but no area, decay expired) x (person_state home, person_state away).
- Transitions: ACTIVE → STALE happens at `STALE_THRESHOLD_SECONDS=60` (`const.py:166`). STALE → LOST happens at `decay_timeout=300` (`const.py:158`). LOST → ACTIVE only on next Bermuda area resolution.

**REUSE statement:** H3 REUSES `info["tracking_status"]` from `person_coordinator.data` (the same dict already read by v4.7.14 D1 at `presence.py:1908`). No new tracking calculations.

### 0.4 v4.7.14 veto line being modified

The v4.7.14 veto is at `presence.py:410`:

```python
# Body (presence.py:403-414)
# v4.7.14: Person-tracker veto — if all configured phone trackers say
# away AND no unidentified person is in the house, return AWAY
# regardless of camera Tier 2 motion. Defends against camera
# ghost-presence (Frigate motion-without-person-ID on empty rooms).
# Note: unidentified_count > 0 preserves guest detection — a guest at
# the door triggering camera motion legitimately means someone IS here
# even if all tracked persons are away.
if all_tracked_persons_away and unidentified_count == 0:
    if current_state == HouseState.AWAY:
        return None  # Already away
    self._confidence = 0.95  # higher than camera-driven 0.85
    return HouseState.AWAY
```

**What v4.7.14.1 changes at this site:** Tightens the condition from `unidentified_count == 0` to `unidentified_count == 0 AND census_count == 0` (H1). The census surface is already available at the call site (`presence.py:1996` passes `census_count=self._census_count`) — `infer()` already receives it on `:369`. We add it to the veto predicate. No signature change, no new kwargs.

**What v4.7.14.1 changes at the call site (`presence.py:1896-1923`):** The `all_tracked_persons_away` computation gets two new filters (H2 phone-left-behind exclusion, H3 tracking_status exclusion) BEFORE the `all(...)` reduction.

### 0.5 v4.7.14 D1 computation block being modified

Currently at `presence.py:1896-1926`:

```python
person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
all_tracked_persons_away = False
tracked_count = 0
away_person_ids: list[str] = []
try:
    if person_coordinator and getattr(person_coordinator, "data", None):
        person_data = person_coordinator.data or {}
        tracked_count = len(person_data)
        if tracked_count > 0:
            all_tracked_persons_away = all(
                (info.get("location") or "") in ("away", "")
                for info in person_data.values()
            )
            if all_tracked_persons_away:
                away_person_ids = sorted(person_data.keys())
except Exception as exc:  # noqa: BLE001 — defensive: stale coord data
    ...
```

H2 + H3 transform `person_data.values()` (and `.keys()` for the log enumeration) through two filter predicates before reduction. The `tracked_count > 0` fail-safe guard MUST be preserved.

### 0.6 Prior planning docs consulted

- `docs/planning/PLANNING_v4.7.14_away_state_person_tracker_trust.md` — primary predecessor; defines D1/D2/D3 and the veto architecture. Lines 60-185 describe the design; lines 32-58 enumerate the architectural file:line index that v4.7.14.1 inherits.
- `docs/planning/PLANNING_v4.7.13_sleep_state_zone_presence_trust.md` — sibling pattern (same "Bug Class #48" lesson, different gate).
- `docs/planning/INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md` — upstream rationale for why camera Tier 2 noise floor varies (Frigate/Protect sensitivity drift).
- (v3.x) `phone_left_behind` was introduced in v3.6.x era; the `PersonPhoneLeftBehindSensor` class lives in `binary_sensor.py` and predates the present cycle — its planning doc was not located in `docs/planning/` (likely shipped before the planning-doc cadence was enforced). The class docstring at `binary_sensor.py:974-983` is the authoritative spec.
- (v3.2.8) `tracking_status` was introduced in v3.2.8.1 — comment at `person_coordinator.py:8` confirms the lineage. Constants block introduced same era (`const.py:160-163` comment "v3.2.8: Tracking status states").

### 0.7 What `project_v4714_live.md` confirmed live (2026-05-30 22:00 UTC)

From the memory body — all gates passed:

- HACS install: `update.universal_room_automation_update.installed_version = "v4.7.14"`.
- Zero bounces post-restart: 33-minute (1983 s) uninterrupted dwell in `away`, no `arriving` transitions.
- Veto signature confirmed: `sensor.ura_presence_coordinator_house_state_confidence = 0.95` (vs 0.9 for the pre-existing AND-gate AWAY).
- D3 attribute `tracked_persons_count = 4` on `sensor.ura_presence_coordinator_presence_house_state`.
- D3 attribute `all_tracked_persons_away = true` on the same sensor.
- Three mirror sensors agree: `presence_coordinator_presence_house_state` + `coordinator_manager_house_state` + `universal_room_automation_house_state` all `away`.
- `census_count = 0` at the time (Frigate gave zero) — the veto short-circuited regardless.
- `binary_sensor.ura_presence_coordinator_house_occupied = off` (was `on` pre-fix).

**Crucial gap exposed by the 22:00 UTC validation window:** the validation confirmed the veto fires correctly when census ALSO reports zero. It did NOT exercise the forgotten-phone scenarios. The three failure modes v4.7.14.1 closes are:

- **Gap A (H1):** Phone left at home, person actually home and walking past a camera. Frigate face-recognizes them, `census_count >= 1`, `unidentified_count == 0`. v4.7.14 veto fires (incorrect — person IS home). H1 adds `census_count == 0` to the predicate.
- **Gap B (H2):** Phone left at home (sitting on the counter, BLE stays put). `person.X = home` (because phone is home). Person actually AT WORK. URA-side `person_coordinator.data["X"]["location"] != "away"` so v4.7.14 thinks X is home and refuses to veto despite the other 3 phones being away. H2 excludes anyone whose `phone_left_behind` is on from the "tracked persons" denominator.
- **Gap C (H3):** Phone in a STALE/LOST tracking state — Bermuda has decayed, `tracking_status != ACTIVE`. The person tracker fallback at `person_coordinator.py:326-349` sets `location` to `"home"` or `"away"` based on stale `person.X` state. v4.7.14 reads these as authoritative. H3 demands ACTIVE tracking for a phone to count toward the veto denominator.

---

## 1. Problem statement

v4.7.14 shipped a coarse "all phones say away" veto. Three forgotten-phone scenarios slip past it (Gaps A/B/C above). Each scenario produces a different wrong answer:

- **Gap A:** False-positive veto (says away when home).
- **Gap B:** False-negative veto (refuses to say away when home).
- **Gap C:** Stale-positive veto (says away based on hour-old data when reality has moved on).

Single rule: the veto must trust phones ONLY when each phone is independently trustworthy.

## 2. Live evidence motivating the hotfix

- No specific incident yet — this is a pre-emptive close-out filed against the v4.7.14 design discussion's deferred items.
- Risk window is high because the v4.7.14 veto bumps confidence to 0.95, OVERRIDING the 0.85 camera-Tier-2 ARRIVING signal that would otherwise correctly catch Gap A. The veto is doing what we asked it to — defending against camera noise — but with insufficient trust-checks on the phones it's listening to.

## 3. Cycle scope — three surgical fixes

All three modify `presence.py`. H1 is in `StateInferenceEngine.infer()`. H2 and H3 are in `_run_inference` at the all-persons-away computation block (lines 1896-1926). No new files, no signature changes (H1 reuses the already-passed `census_count`; H2 and H3 are entirely local to `_run_inference`).

---

### H1 — Add `census_count == 0` to the veto predicate

**File:** `domain_coordinators/presence.py`
**Site:** `StateInferenceEngine.infer()` body, the v4.7.14 veto block (currently `:410`).

**Change:**

```python
# BEFORE (presence.py:410)
if all_tracked_persons_away and unidentified_count == 0:

# AFTER
if all_tracked_persons_away and unidentified_count == 0 and census_count == 0:
```

**Rationale:** `census_count` is the count of identified people Frigate is currently seeing (including face-recognized residents). When census sees one or more identified persons, SOMEONE is provably in front of a camera. Whether their phone is tracking correctly or not is irrelevant — the building has a verified occupant. The veto must not fire.

**Why this can't fabricate the trust:** The existing AND-gate at `:397` (`census_count == 0 and not any_zone_occupied`) already trusts `census_count == 0` as a fail-closed signal. We're using the same trust direction (`== 0`) in the veto. No new fragility introduced.

**Verify in build:** Confirm that the `infer()` signature already accepts `census_count` (it does — `:369`). The change is one additional `and` clause at `:410`.

#### Acceptance Criteria — H1

- **Verify:** Veto condition at `presence.py:410` reads `if all_tracked_persons_away and unidentified_count == 0 and census_count == 0:`. No other code paths altered.
- **Verify:** Comment above the veto updated to reflect the tightened condition.
- **Sensor:** `sensor.ura_presence_coordinator_house_state_confidence` shows `0.95` ONLY when census_count is also zero (along with the existing conditions).
- **Test:** `test_h1_veto_does_not_fire_when_census_count_positive` — all 4 persons away, no unidentified, `census_count=1` → veto skipped, falls through to normal `has_people` logic, returns `HouseState.ARRIVING`.
- **Test:** `test_h1_veto_still_fires_when_census_count_zero` — same as v4.7.14 baseline: all 4 away, no unidentified, `census_count=0` → veto fires, returns `HouseState.AWAY` at confidence 0.95. Regression guard against this hotfix accidentally killing the v4.7.14 behavior.
- **Test:** `test_h1_default_kwarg_preserves_existing_behavior` — call `infer()` without `all_tracked_persons_away` and verify identical output to pre-v4.7.14 behavior on the same inputs (carry-over from v4.7.14's same test).
- **Live:** Forgotten-phone-at-home scenario — walk past kitchen camera with phone left in bedroom. `sensor.ura_presence_coordinator_presence_house_state` should NOT transition to `away`. `census_count` attribute > 0 at the time of evaluation.

---

### H2 — Exclude phone-left-behind persons from the veto denominator

**File:** `domain_coordinators/presence.py`
**Site:** `_run_inference` at lines 1907-1916 (the H1 computation block from v4.7.14).

**Change:** Before reducing with `all(...)`, filter out persons whose `phone_left_behind` binary sensor is `on`. Their phone is sitting somewhere; their location signal is meaningless.

**Pseudocode:**

```python
if person_coordinator and getattr(person_coordinator, "data", None):
    person_data = person_coordinator.data or {}

    # H2: Build per-person trust map by reading the existing
    # binary_sensor.<person>_phone_left_behind entity.
    # REUSING PersonPhoneLeftBehindSensor signal from binary_sensor.py:973-1084,
    # NOT rebuilding the detection logic.
    def _phone_trustworthy(person_name: str) -> bool:
        # Sensor is disabled by default (binary_sensor.py:988). If it doesn't
        # exist or state is unavailable/unknown, default to TRUSTING the phone
        # (preserves v4.7.14 behavior for operators who haven't enabled it).
        person_slug = person_name.lower().replace(" ", "_")
        entity_id = f"binary_sensor.{person_slug}_phone_left_behind"
        state = self.hass.states.get(entity_id)
        if state is None:
            return True
        return state.state not in ("on", STATE_ON)  # type: ignore[name-defined]
        # NOTE: verify in build whether STATE_ON is already imported; otherwise
        # compare against the string "on" only.

    trustworthy_persons = {
        name: info for name, info in person_data.items()
        if _phone_trustworthy(name)
    }

    tracked_count = len(trustworthy_persons)
    if tracked_count > 0:
        all_tracked_persons_away = all(
            (info.get("location") or "") in ("away", "")
            for info in trustworthy_persons.values()
        )
        if all_tracked_persons_away:
            away_person_ids = sorted(trustworthy_persons.keys())
```

**Critical edge case:** If ALL persons have `phone_left_behind=on`, `tracked_count` drops to 0, and the `tracked_count > 0` fail-safe guard at the next line keeps `all_tracked_persons_away = False`. The veto does NOT fire — correct fail-safe direction.

**Why this is non-fragile:** The default-disabled state of `PersonPhoneLeftBehindSensor` (`binary_sensor.py:988`) means most operators will see NO behavioral difference. Only operators who have explicitly enabled the diagnostic — i.e., operators who have decided the signal is reliable in their home — get the H2 carve-out. Conservative and operator-opt-in by design.

**Builder NOTE — entity-ID slug:** the slug formula `person_id.lower().replace(' ', '_')` mirrors `binary_sensor.py:1000`. Use the SAME formula; do not invent a parallel slug rule.

**Builder NOTE — `STATE_ON` import:** `[verify in build]` whether `homeassistant.const.STATE_ON` is already imported in `presence.py`. If not, comparing against the literal `"on"` string is acceptable per the existing project conventions (`presence.py:1502` uses literal-string comparison for the same kind of state check).

#### Acceptance Criteria — H2

- **Verify:** H2 filter sits BEFORE the `all(...)` reduction so phone-left-behind persons never enter the away-check.
- **Verify:** `tracked_count` reflects the filtered denominator (not the raw `person_coordinator.data` length).
- **Verify:** `tracked_count > 0` fail-safe guard preserved — all-persons-flagged scenario does NOT veto.
- **Verify:** Sensor disabled / not in `hass.states` → person counted (trust phone), preserving v4.7.14 baseline behavior.
- **Sensor:** `sensor.ura_presence_coordinator_presence_house_state` `tracked_persons_count` attribute reflects post-filter count.
- **Sensor:** `away_person_ids` log enumeration excludes persons filtered out by H2.
- **Test:** `test_h2_excludes_phone_left_behind_person` — 4 persons configured, 1 has `phone_left_behind=on`, other 3 have `location=away`. Veto fires (denominator dropped from 4 to 3; remaining 3 all away → all-away).
- **Test:** `test_h2_phone_left_behind_holdout_blocks_veto` — 4 persons configured, 1 has `phone_left_behind=on` AND `location != "away"` (phone is home → "location" likely `"home"` or a room), other 3 are away. Filter removes the flagged person, denominator=3, remaining 3 are away → veto fires. (Same outcome as previous test but different setup — checks filter applies to home-flagged persons specifically.)
- **Test:** `test_h2_all_persons_flagged_does_not_veto` — 4 persons configured, all 4 have `phone_left_behind=on`. `tracked_count == 0`, fail-safe holds, veto does NOT fire.
- **Test:** `test_h2_sensor_unavailable_treats_as_trustworthy` — sensor disabled / `hass.states.get(...)` returns None → person counted in denominator (preserves v4.7.14 baseline).
- **Test:** `test_h2_sensor_state_unknown_treats_as_trustworthy` — `state.state == "unknown"` → person counted (only literal `"on"` excludes).
- **Live:** Enable `binary_sensor.oji_phone_left_behind` for one person. Confirm `sensor.ura_presence_coordinator_presence_house_state` attributes update: `tracked_persons_count` decrements by 1 when the binary sensor is on; `all_tracked_persons_away` recomputes accordingly.

---

### H3 — Exclude STALE/LOST persons from the veto denominator

**File:** `domain_coordinators/presence.py`
**Site:** Same block as H2 (lines 1907-1916).

**Change:** After the H2 phone-trust filter, also exclude any person whose `tracking_status != TRACKING_STATUS_ACTIVE`.

**Pseudocode (composing with H2):**

```python
from ..const import TRACKING_STATUS_ACTIVE  # [verify in build — likely
# needs to be from .const inside _run_inference's module; the actual
# import path depends on presence.py's existing relative-import style]

def _tracking_active(info: dict) -> bool:
    # REUSING tracking_status field from person_coordinator.py (set at
    # :213 ACTIVE, :288 STALE, :153/:333/:345/:377 LOST). NOT rebuilding.
    # Default to ACTIVE if the field is absent — defensive against
    # older-shape entries.
    return info.get("tracking_status", TRACKING_STATUS_ACTIVE) == TRACKING_STATUS_ACTIVE

trustworthy_persons = {
    name: info for name, info in person_data.items()
    if _phone_trustworthy(name) and _tracking_active(info)
}
```

**Rationale:**

- `ACTIVE` (set at `person_coordinator.py:213`) means Bermuda resolved within the last `STALE_THRESHOLD_SECONDS=60`. The phone is actively reporting. Trust it.
- `STALE` (set at `:288`) means we have Bermuda data but it's stale (within decay window 60-300 s). The location field is preserved but decaying. Excluding it from the veto denominator prevents the veto from firing on stale data — conservative.
- `LOST` (set at `:153/:333/:345/:377`) means we have NO Bermuda data (or only `person.X` state). The fallback uses `person.X` state, which itself can lag by minutes. Don't let stale fallback data fire the high-confidence veto.

**Crucial edge case A:** If ALL persons are STALE/LOST, `tracked_count` drops to 0, the `tracked_count > 0` guard prevents the veto. The system falls through to `census_count == 0 and not any_zone_occupied` AND-gate at `:397` (the pre-v4.7.14 baseline), or to the camera-driven path. CORRECT fail-safe.

**Crucial edge case B:** Default `ACTIVE` if the `tracking_status` field is absent. This handles any legacy-shape entries that may exist post-deploy from previous versions. Defensive against the `KeyError` regression class.

#### Acceptance Criteria — H3

- **Verify:** Filter applied AFTER H2 (or AND'd in the same comprehension). Order does not matter functionally but must be deterministic.
- **Verify:** Constant `TRACKING_STATUS_ACTIVE` imported from `const.py:161`. Spell-checked.
- **Verify:** Missing `tracking_status` field defaults to ACTIVE (defensive — fail-open toward v4.7.14 baseline behavior).
- **Verify:** `tracked_count > 0` fail-safe guard preserved.
- **Sensor:** `sensor.ura_presence_coordinator_presence_house_state` `tracked_persons_count` attribute reflects post-filter count (consistent with H2 above).
- **Test:** `test_h3_excludes_stale_person` — 4 persons, 1 with `tracking_status=stale` and `location=away`, other 3 ACTIVE and away. Stale person excluded from denominator. Remaining 3 ACTIVE all away → veto fires.
- **Test:** `test_h3_excludes_lost_person` — same shape but `tracking_status=lost`.
- **Test:** `test_h3_only_stale_persons_does_not_veto` — 4 persons, all STALE. Denominator drops to 0, fail-safe holds, veto does NOT fire.
- **Test:** `test_h3_missing_tracking_status_treated_as_active` — person entry has no `tracking_status` key. Defaults to ACTIVE → counted in denominator.
- **Test:** `test_h3_active_person_at_home_blocks_veto` — 4 persons all ACTIVE, 1 at `home`/some-room, other 3 away. Veto correctly does NOT fire.
- **Live:** Read `sensor.ura_presence_coordinator_presence_house_state` attributes during a known STALE window (e.g., immediately after Bermuda glitch). Verify `tracked_persons_count` decrements appropriately. Veto should NOT fire on STALE-only data.

---

## 4. Bug class watchlist

| Class | Risk | Mitigation |
|---|---|---|
| #11 (UTC vs local TZ) | None | No new timestamp logic. |
| #14 (config snapshot staleness) | Minimal | Person list read fresh per inference cycle, no snapshotting. |
| #20 (concurrent reload race) | None | No new listeners, no entity registry mutation. |
| #22 (enum mismatch) | Low | H3 compares to `TRACKING_STATUS_ACTIVE` constant (not string literal). String literal `"on"` used in H2 only because `binary_sensor` states are universal strings (`"on"`/`"off"`/`"unknown"`/`"unavailable"`). |
| #23 (observation mode gating) | None | The veto is inference logic, not actuation. Observation mode does not apply at this layer. |
| #26 (in-memory reads only) | Watch | H2 reads `hass.states.get(...)` not `coordinator.data`. This is the correct surface for a binary_sensor entity. |
| #33 (sibling helper skipped) | **Watch** | Are there OTHER places in `presence.py` (or elsewhere) that compute "all phones away" or read `person_coordinator.data` for location? Builder MUST grep `person_coordinator.data` and `location.*away` to ensure H2+H3 carve-outs don't need to be replicated elsewhere. Likely-clean per the v4.7.14 design (only one veto site), but verify. |
| #38 (untracked unsub) | None | No new listeners. |
| #42 (lambda + async_create_task) | None | No new scheduling. |
| #43 (silent room drop) | None | House-level, not room-level. |
| #44 (test fixture authority) | **Watch** | Cycle tests MUST drive the real `StateInferenceEngine.infer()` and the real `_run_inference` filter logic — NOT stub the filter and assert on the stub. Tests MUST construct realistic `person_coordinator.data` dicts using the same field shape produced at `person_coordinator.py:215-226` (`location`, `tracking_status`, `confidence`, `method`, etc.) and the same `tracking_status` constants from `const.py`. |
| #45 (lambda closure stale) | Low | `_phone_trustworthy` defined inside `_run_inference` captures `self.hass`. Re-defined each call → no stale closure risk. |
| #46 (async_update_entry re-entrancy) | None | No config-entry mutations. |
| #47 (lazy canonical UI surface violation) | None | No new entities. |
| **#48 (transient-sensor over-trust)** | **Direct exemplar — being closed** | This entire cycle is a Bug Class #48 cleanup of v4.7.14's veto. After ship, `QUALITY_CONTEXT.md` entry for #48 should be updated to cite v4.7.14.1 as the "follow-up tightening" reference. |

## 5. Tier classification — Tier 2-DB (operator-elevated)

### Why elevated

Per CLAUDE.md, the Tier 2-DB triggers (touches `database.py` DAOs, migrates ≥3 callers, changes payload shape, adds behavioral test infra against real schemas, predecessor to imminent schema migration) do NOT formally fire for this cycle — it's a ~25-40 LoC three-clause filter tweak that doesn't touch `database.py`.

**However, the user has explicitly elevated all cycles in the Bug Class #48 sprint to Tier 2-DB** because the trust hierarchy is load-bearing: a regression to the v4.7.14 veto behavior reintroduces the empty-house oscillation (live-evidenced 2026-05-30 ~19:13 UTC pre-fix). The three changes touch the conditions under which the high-confidence (0.95) veto fires; getting them subtly wrong silently reverts v4.7.14's gain.

### Three parallel reviewer framings

Per Tier 2-DB protocol, run THREE reviews in parallel, each framed by a different risk axis. **Different framings cannot share blind spots.**

#### Reviewer A — Correctness of veto condition + edge cases

Focus:
- The exact veto predicate at `presence.py:410` — does `census_count == 0` AND-clause stack with the existing two clauses correctly?
- None-handling in H2/H3: what if `hass.states.get(...)` returns None? What if `info.get("tracking_status")` returns None? What if `info` itself is None?
- Empty data: what if `person_coordinator.data == {}`? What if every person is filtered out by H2 OR H3?
- Missing entities: what if the operator has 4 persons configured but only 2 corresponding `phone_left_behind` binary sensors exist (because the integration was reloaded mid-cycle and entity registry hasn't caught up)?
- Default kwarg compatibility: does the v4.7.14 `default=False` for `all_tracked_persons_away` still preserve back-compat for any callsite (test or production) that doesn't pass it?
- Confidence value math: `0.95` still > `0.85` ARRIVING and > `0.9` AND-gate AWAY? Any code that ranks states by confidence and might now prefer one path over another?

#### Reviewer B — Signal-chain integrity + interaction with v4.7.14's existing veto + interaction with phone_left_behind original design intent

Focus:
- End-to-end trace: phone goes onto kitchen counter → `binary_sensor.X_phone_left_behind` turns on → `_run_inference` reads sensor state → person filtered → `all_tracked_persons_away` recomputed → `infer()` called → veto decision. Every link must be verified.
- Does v4.7.14's veto INFO log at `presence.py:2011-2014` still enumerate the CORRECT `away_person_ids`? After H2+H3 filtering, the log MUST list the filtered subset (the persons actually driving the veto), not the raw person_coordinator keys. Builder must confirm `away_person_ids = sorted(trustworthy_persons.keys())` post-filter.
- Does H2 conflict with `PersonPhoneLeftBehindSensor`'s original design intent? The class docstring (`binary_sensor.py:974-983`) says the sensor fires when "BLE places person in a room AND no camera has seen them recently AND census sees zero unidentified persons AND outside sleep hours." Reviewer B must verify that REUSING this signal in the veto denominator does not create a feedback loop (e.g., the sensor's "no camera saw them" condition shouldn't depend on a sensor that's downstream of the veto we're tightening).
- Sleep-hour suppression: `PersonPhoneLeftBehindSensor` is force-False during 22-07 local. During sleep hours, H2 has no effect (all persons trustworthy). Reviewer B must confirm this is acceptable — likely yes, because the veto is for AWAY, not SLEEP, but call it out explicitly.
- Census-count interaction: H1 requires `census_count == 0` for the veto. If `census_count > 0` AND `unidentified_count == 0` (i.e., Frigate sees a face-recognized resident), we fall through to the `has_people` branch. Reviewer B confirms this is the desired routing.
- Interaction with v4.7.14 D3 attributes on `PresenceHouseStateSensor` (`sensor.py:3629-3634`): the attributes read `presence._tracked_persons_count` and `presence._all_tracked_persons_away`. After H2+H3, these now reflect the FILTERED denominator. Reviewer B must confirm this is the desired diagnostic — likely YES because the operator wants to see "what the veto actually thinks," but the doc should explicitly call this out so the live-validation interpretation is unambiguous.

#### Reviewer C — Test fixture authority (Bug Class #44) + cross-coordinator dependencies + parallel-merge risk with v4.7.15

Focus:
- Bug Class #44: do the new tests for H1/H2/H3 drive the REAL `StateInferenceEngine.infer()` and the REAL `_run_inference` filter block? Or do they stub the filter? Reviewer C MUST verify test code paths.
- Test fixture: do `person_coordinator.data` dicts in tests use the field shape from `person_coordinator.py:215-226` (with `location`, `tracking_status`, `last_changed`, `confidence`, `method`, `recent_path`, `last_bermuda_update`, `previous_location`, `previous_location_time`) — not a hand-rolled subset? If a subset is used, document WHY it's safe.
- Cross-coordinator deps: H2 reads `hass.states.get("binary_sensor.X_phone_left_behind")`. Does the test framework have a `hass.states.async_set(...)` for the test fixture binary sensor states? Or does it use a different fixture path? Confirm.
- Cross-coordinator deps: H3 reads `person_coordinator.data[...]["tracking_status"]`. Does `person_coordinator` exist in `hass.data[DOMAIN]` during tests? Tests already exist for v4.7.14 D1 so this is presumably already wired, but confirm.
- **Parallel-merge risk with v4.7.15** (sleep-state trust universalization): does v4.7.15 plan to ALSO modify `_run_inference` near the same line range? If yes, the merge order matters. Reviewer C MUST cross-check the v4.7.15 planning doc (or its TBD scope memo) and flag any line-range collisions. If v4.7.15 lands first, v4.7.14.1 builder needs to rebase. If v4.7.14.1 lands first, v4.7.15 builder needs to rebase. Document the agreed ordering in the master link doc `PLANNING_BUG_CLASS_48_SPRINT_LINK.md`.

### Pre-deploy zero-bugs gate (mandatory)

Per CLAUDE.md "Pre-Deploy Zero-Bugs Gate" rule, BEFORE invoking `scripts/deploy.sh`:

| Gate | Pass criterion |
|---|---|
| **G1 — Grep conflict markers** | `grep -rn '<<<<<<<\|=======\|>>>>>>>' custom_components/universal_room_automation/` returns ZERO matches. No files in the cycle commit show diff markers. |
| **G2 — py_compile changed files** | `python3 -m py_compile custom_components/universal_room_automation/domain_coordinators/presence.py` and any other file touched returns exit 0. (Source-grep AST tests do not catch SyntaxError — py_compile does.) |
| **G3 — Cycle tests pass** | The H1/H2/H3 test functions enumerated in Section 3 ALL pass: `PYTHONPATH=quality python3 -m pytest quality/tests/<test_file> -v` returns 0 failures. |
| **G4 — Suite baseline diff** | Full `PYTHONPATH=quality python3 -m pytest quality/tests/ -v` compared against `pre-review-v4.7.14.1` tag shows ≥0 net new passes and ZERO new failures. |
| **G5 — Tag pre-review baseline** | `git tag pre-review-v4.7.14.1 -m "Pre-review baseline for v4.7.14.1"` MUST exist before any review-fix commits. |
| **G6 — README staged** | `docs/readmes/README_v4.7.14.1.md` exists, fully populated per Section 6, and `git add`-ed before `deploy.sh` invocation. |

If ANY gate fails, deploy is BLOCKED. Investigate, fix, re-run all six. No "we'll fix it in 4.7.14.2" — that's exactly the v4.7.4.3 / v4.7.4.4 pattern the gate exists to prevent.

---

## 6. README content requirements

**File:** `docs/readmes/README_v4.7.14.1.md` (MUST exist pre-deploy per G6).

### Required sections

1. **Summary** — one sentence: "Hotfix closing three forgotten-phone gaps in v4.7.14's person-tracker veto."
2. **Why this ships** — pre-existing risk window: v4.7.14's veto fires at confidence 0.95 (overriding camera ARRIVING) without checking whether the phone signal is independently trustworthy. Three scenarios where it gets the wrong answer (Gaps A/B/C from Section 0.7).
3. **Changes** — H1/H2/H3 enumerated with one-line file:line citations each.
4. **What's NOT changing** — explicit list of v4.7.14 D1/D2/D3 surfaces preserved (the `infer()` signature, the `_run_inference` computation block structure, the `PresenceHouseStateSensor` attribute surface). Refer to Section 8 of this plan.
5. **Operator runbook** — what to verify within 10 minutes of restart (see Section 7 below). Specific entity attributes and expected values. If any check fails, the operator should follow the rollback procedure in section 6.
6. **Rollback procedure** — step-by-step:
   - In HACS, downgrade `universal_room_automation` to `v4.7.14`.
   - Restart Home Assistant.
   - Confirm `update.universal_room_automation_update.installed_version == "v4.7.14"`.
   - Confirm `sensor.ura_presence_coordinator_house_state_confidence` returns to 0.95 during all-away windows (v4.7.14 baseline behavior).
   - File issue with the symptom + the four-row attribute table from the operator runbook so the next cycle can diagnose.
7. **Live-validation checklist** — full Section 7 table from this plan, copy-pasted.
8. **Pre/post observation table** — operator-fillable table to be completed at deploy time:

| Window | Time (UTC) | All persons `not_home`? | `census_count` | `unidentified_count` | `phone_left_behind` (any on?) | `tracking_status` (any STALE/LOST?) | `house_state` | `confidence` | `tracked_persons_count` attr | `all_tracked_persons_away` attr | Veto fired? |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Pre-deploy | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ |
| T+10min | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ |
| T+1h | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ |
| Morning workday | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ | _____ |

9. **Bug Class watchlist** — copy Section 4 of this plan.
10. **Master sprint link** — link to `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md`.

---

## 7. Live-validation acceptance criteria

The live entity is `sensor.ura_presence_coordinator_presence_house_state` (verified in `project_v4714_live.md` row 5; the build agent's earlier guess `sensor.ura_presence_house_state` was wrong; do NOT regress to that name).

### 7.1 Veto-still-fires regression check (carries v4.7.14 baseline forward)

When all 4 persons reach `not_home` AND `census_count == 0` AND `unidentified_count == 0`:

| Attribute / sensor | Expected value |
|---|---|
| `sensor.ura_presence_coordinator_presence_house_state` state | `away` |
| `sensor.ura_presence_coordinator_presence_house_state` attribute `tracked_persons_count` | `4` (assuming 4 configured persons, no H2/H3 filters tripped) |
| `sensor.ura_presence_coordinator_presence_house_state` attribute `all_tracked_persons_away` | `true` |
| `sensor.ura_presence_coordinator_house_state_confidence` | `0.95` |
| `binary_sensor.ura_presence_coordinator_house_occupied` | `off` |
| Logs (last 1h) | At least one `"v4.7.14: Person-tracker veto fired"` line enumerating all 4 persons |

### 7.2 H1 forgotten-phone-at-home check

When phone is left at home AND person walks past a camera that face-recognizes them (`census_count >= 1`, `unidentified_count == 0`):

| Attribute / sensor | Expected value |
|---|---|
| `sensor.ura_presence_coordinator_presence_house_state` attribute `census_count` (already exposed pre-cycle at `sensor.py:3623`) | `>= 1` |
| `sensor.ura_presence_coordinator_presence_house_state` state | NOT `away` — should be `arriving` or `home_*` per existing inference logic |
| `sensor.ura_presence_coordinator_house_state_confidence` | NOT `0.95` (the veto is the only path that sets 0.95; if state is not away, confidence should not be the veto's signature value) |
| Logs (last 10 min) | ZERO `"Person-tracker veto fired"` lines during the window the person is in front of the camera |

### 7.3 H2 phone-left-behind exclusion check

When `binary_sensor.<person>_phone_left_behind` for one person is `on` AND the other 3 persons are away:

| Attribute / sensor | Expected value |
|---|---|
| `binary_sensor.<flagged_person>_phone_left_behind` state | `on` |
| `sensor.ura_presence_coordinator_presence_house_state` attribute `tracked_persons_count` | `3` (post-filter) |
| `sensor.ura_presence_coordinator_presence_house_state` attribute `all_tracked_persons_away` | `true` (because remaining 3 are all away) |
| `sensor.ura_presence_coordinator_presence_house_state` state | `away` (assuming `census_count == 0`) |
| Logs (last 10 min) | `"v4.7.14: Person-tracker veto fired"` listing the 3 non-flagged persons |

### 7.4 H3 STALE/LOST exclusion check

When `person_coordinator.data["<person>"]["tracking_status"] == "stale"` for one person AND the other 3 are ACTIVE+away:

| Attribute / sensor | Expected value |
|---|---|
| `sensor.ura_presence_coordinator_presence_house_state` attribute `tracked_persons_count` | `3` (post-filter — the STALE person excluded) |
| `sensor.ura_presence_coordinator_presence_house_state` attribute `all_tracked_persons_away` | `true` |
| Veto-fired log | Lists the 3 ACTIVE persons, not the STALE one |

### 7.5 All-filtered fail-safe check

When ALL 4 persons are either `phone_left_behind=on` or `tracking_status != ACTIVE`:

| Attribute / sensor | Expected value |
|---|---|
| `sensor.ura_presence_coordinator_presence_house_state` attribute `tracked_persons_count` | `0` |
| `sensor.ura_presence_coordinator_presence_house_state` attribute `all_tracked_persons_away` | `false` (fail-safe — empty denominator does NOT veto) |
| House state falls through to existing AND-gate (`census_count == 0 AND not any_zone_occupied → AWAY` at confidence 0.9) or camera-driven path | No veto-fired log; state determined by other paths |

---

## 8. What's intentionally OUT of scope

Be explicit about each:

- **H4 — WAKING-state gate.** Some operators may want a veto that fires during the WAKING transition window (07:00-08:00 local) when phones haven't yet moved but the household is rousing. **Out of scope.** This is a SLEEP/WAKING surface, not an AWAY surface. v4.7.15 (sleep-state trust universalization) may address it; this hotfix MUST NOT.
- **H5 — SLEEP transition NIT.** During SLEEP-state, phones may BLE-decay to STALE simply because the person is motionless. Applying H3 to a hypothetical sleep-state veto would incorrectly exclude all sleeping persons. **Out of scope.** v4.7.15's domain.
- **Any v4.7.15+ scope.** No sleep-state changes, no other coordinator changes, no schema migration.
- **New CONF_\* for veto tuning.** Confidence value 0.95 stays hardcoded. Census/unidentified thresholds stay hardcoded. The hotfix tightens predicates; it does not expose them.
- **New entities.** No new sensors, no new binary_sensors, no new buttons. The diagnostic surface (`tracked_persons_count`, `all_tracked_persons_away`) already exists on `PresenceHouseStateSensor` from v4.7.14 D3 and is REUSED.
- **Modifying `PersonPhoneLeftBehindSensor`'s detection logic.** REUSED as-is. If the signal is too noisy in practice, that's a future tuning question; this cycle just consumes the existing signal.
- **Modifying `person_coordinator.py` tracking_status transitions.** REUSED as-is. If STALE/LOST thresholds need re-tuning, that's a future cycle.
- **`_update_ble_zone_presence` at `presence.py:1500-1506` "away" filter.** Per v4.7.14 §5 — that filter is correct as-is. Not in scope.
- **Camera Tier 2 timeout (`_CAMERA_OCCUPANCY_TIMEOUT_SECONDS = 300`).** Not in scope.
- **Frigate sensitivity / Frigate config.** Upstream tuning. Not in scope.
- **No soak watching.** Per CLAUDE.md: cycles close at live-validation. No "monitor for 24h" — the operator runbook completes within 10 minutes of restart; subsequent observation is opportunistic, not gated.

---

## 9. Master link doc reference

This cycle is **one of three** in the "Bug Class #48 trust-hierarchy universalization" sprint. The master link doc at `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md` (filed alongside this doc) coordinates:

- **v4.7.14.1 (this doc):** Tightens the AWAY veto with three forgotten-phone carve-outs.
- **v4.7.15:** Sleep-state trust universalization. Will modify `_run_inference` and likely the aggregation layer. Builder MUST cross-check line-range overlap with this cycle before starting.
- **v4.7.16:** TBD scope per the master link doc — likely Bug Class #48 cleanup at one more surface.

Merge ordering: Reviewer C (Section 5) must approve the deploy order to avoid trivial merge conflicts. **Default ordering (until master link doc supersedes):** v4.7.14.1 → v4.7.15 → v4.7.16.

---

## 10. Plan completion tracking

After implementation, document:

- H1 / H2 / H3 status (shipped, partial, deferred).
- Any deviations from planned line numbers or signatures.
- Confirmation that the `tracked_count > 0` fail-safe guard remained intact.
- Confirmation that v4.7.14 baseline behavior is preserved when no H2/H3 conditions trip (regression-guard test passes).
- Live evidence: the pre/post observation table from the README, filled in.
- Confirmation that QUALITY_CONTEXT.md Bug Class #48 entry was updated with v4.7.14.1 as the "follow-up tightening" reference.

If any of H1/H2/H3 is deferred, state WHY and where it lives in the backlog. Do NOT silently drop.

---

## 11. References

- v4.7.14 planning: `docs/planning/PLANNING_v4.7.14_away_state_person_tracker_trust.md`
- v4.7.13 planning (sibling): `docs/planning/PLANNING_v4.7.13_sleep_state_zone_presence_trust.md`
- v4.7.14 live evidence: `~/.claude/projects/-Users-okosisi-Code-universal-room-automation/memory/project_v4714_live.md`
- `PersonPhoneLeftBehindSensor` class: `custom_components/universal_room_automation/binary_sensor.py:973-1084`
- `tracking_status` constants: `custom_components/universal_room_automation/const.py:161-163`
- `tracking_status` set-sites: `custom_components/universal_room_automation/person_coordinator.py:153, 213, 222, 288, 299, 333, 345, 377`
- v4.7.14 veto line: `custom_components/universal_room_automation/domain_coordinators/presence.py:410`
- v4.7.14 D1 computation block: `custom_components/universal_room_automation/domain_coordinators/presence.py:1896-1926`
- v4.7.14 D3 diagnostic surface: `custom_components/universal_room_automation/sensor.py:3624-3634`
- v4.7.14 INFO log surface: `custom_components/universal_room_automation/domain_coordinators/presence.py:2004-2019`
- QUALITY_CONTEXT Bug Class #48: `docs/QUALITY_CONTEXT.md:1855`
- Camera signal sensitivity investigation: `docs/planning/INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md`
- Master sprint link: `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md`
