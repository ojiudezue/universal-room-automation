# PLANNING — Guest / Census correctness cycle

**Card:** `CENSUS-GHOST-DEDUP-1` (operator-approved 2026-08-16).
**Tier:** **2-DB** — census + house-state are shared primitives; trust-hierarchy
ripple (census → presence → security lockdown, HVAC hold preservation,
learning suppression, phone-left-behind, veto oracles). Three framing-disjoint
reviews required.
**Scope discipline:** hard no-cruft. **THREE deliverables**, ~25 LoC net, ZERO
new knobs. Anything not listed under D1-D3 is explicitly out of scope
(§ Non-goals).
**Spec source:** `docs/planning/RESEARCH_guest_actuation_and_census.md`
(commit `8f55b243d`), §1.6 (root cause), §6 (diff), §7 (G1/G4), §3.1 (D5 wiring).

---

## Falsifiable invariant

**INV-CENSUS-CLAMP.** For every census tick under the enhanced path
(`enhanced_census: True`, live), the published payload must satisfy

    identified_count + unidentified_count  <=  max(camera_unrecognized, identified_count)

which is exactly the raw path's subtractive derivation
(`camera_census.py:1780-1782`). Equivalently: **no person may contribute to
both `identified_count` and `unidentified_count` on the same tick.**

**INV-GUEST-LEAD.** For every inference tick with `current_state ∈
_home_like_states`, GUEST entry requires
`_guest_room_gate_armed() == True`. `_guest_gate_armed()` (census-unidentified)
alone MUST NOT be sufficient to enter GUEST. (Path C manual override
`house_state.py:213-221` is not covered by this invariant — by product design.)

D (adversarial-completeness) reviewer's sole job is to falsify these two.

---

## Institutional context verified

**Grepped surfaces** (each addition marked REUSED or NEW):

- `_apply_enhanced_house_census` `camera_census.py:3075-3137` — read end-to-end.
  Confirms additive: `total = identified_count + held_unidentified` (`:3109`).
  Overwrites `raw_result` except confidence/agreement/counts (`:3111-3121`).
- `_cross_correlate_persons` `camera_census.py:1746-1818` — subtractive:
  `unidentified = max(0, camera_total - identified)`, `total = max(camera_total, identified)`.
- `_get_unrecognized_camera_count` `camera_census.py:2670-2826` — fresh-face
  `−1/camera` (`:2740-2760`), per-area BLE-cancel (`:2798-2816`).
  Live `ble_cancelled_count = 0` and `camera_unrecognized == frigate_count`
  (§0.1) → both defenses returning zero.
- `sensor.py:3505-3529` — `area_contributions` reads `_last_area_contributions`
  written by the RAW producer (`camera_census.py:1358`) → wrong publisher for
  enhanced path (§1.9). Fold into D1 as instrument (G2 in RESEARCH).
- `presence.py` → **`domain_coordinators/presence.py`**. `_discover_guest_rooms`
  at `:4668-4730`, `_handle_guest_room_occupancy_change` at `:4732-4801`,
  composition OR at `:5391-5404`, confidence at `:5406-5414`.
- `entity.py:34` — `_attr_unique_id = f"{coordinator.entry.entry_id}_{entity_type}"`.
  For the room's occupied binary_sensor, `entity_type = "occupied"`
  (`binary_sensor.py:245` — `OccupiedBinarySensor.__init__` calls
  `super().__init__(coordinator, "occupied", "Occupied")`). Registry lookup
  key: `("binary_sensor", DOMAIN, f"{entry_id}_occupied")`. **REUSED** —
  this is how every URA room's occupied entity is registered. No new
  identifier scheme.
- No new CONF_*, no `const.py` numeric additions, no Number/Select/Switch
  entity, no options-flow field. Verified by exhaustive grep of the six
  prior-art surfaces in CLAUDE.md § Institutional Context First.
  **ZERO new knobs.**

**Prior planning docs consulted:**
- `RESEARCH_guest_actuation_and_census.md` (spec source; full read).
- `PLANNING_census_overcount_dedup_decay.md` (v5.9.0 D-A/D-B/D-C/D-E, shipped
  — this cycle does NOT re-tune hold/decay/sustain).
- `PLANNING_census_ble_cancel_unrecognized.md` (v5.9.x per-area BLE-cancel,
  shipped, currently inert — D1 is the invariant-level fix that makes its
  inertness non-fatal).
- `PLANNING_gap_a_census_hole.md` (v5.78.0 D8 — payload-key precedent for
  additive/byte-identity plumbing; D1 does NOT add a new payload key).
- `PLANNING_v4.7.2_dpm_hvac_surface_plus_guest_signal.md` (D4/D5 shipped
  and LIVE — D2 modifies D5 predicates only; do NOT re-plumb).
- `PLANNING_presence_guest_latch_and_veto_gap.md` (v5.16.0 exit-ordering;
  the exit condition tests `guest_gate_armed` at `presence.py:1241` — D2's
  change to `guest_armed` composition is compatible because
  `guest_room_gate_armed → 0` still triggers exit).

**Memory bodies pulled:**
- `project_presence_guest_latch_and_veto_gap` (do NOT re-plan D1/D1b; exit
  branch ordering preserved).
- `project_guest_mode_false_positive_backlog` (Fix A LOST-away shipped;
  Fix B outdoor-census G9 explicitly out of scope here — noted in RESEARCH §7).

**Design docs read:** `docs/Coordinator/PRESENCE.md`, `docs/Coordinator/CENSUS.md`
if present — census logic lives in `custom_components/…/camera_census.py`
(no coordinator subclass; owned by presence init).

**Code locations surveyed end-to-end during scoping:**
`camera_census.py:1746-1818, 3060-3172, 3080-3137`;
`domain_coordinators/presence.py:4660-4801, 5380-5420`;
`binary_sensor.py:200-246`; `entity.py:1-99`.

---

## PRODUCER check — every derivation of the count

| # | Path | File:line | Formula | Wins? | Depends on | Health (2026-08-16) |
|---|---|---|---|---|---|---|
| P1 | Raw subtractive | `camera_census.py:1780-1782` | `unidentified = max(0, camera − identified)`; `total = max(camera, identified)` | **NO** — overwritten by P2 when `enhanced_census: True` (live) | `camera_total` (post-`_dedup_by_area`), `identified = |face_ids ∪ ble_ids|` | Healthy in isolation (structurally invariant-preserving) but never published on live |
| P2 | Enhanced additive | `camera_census.py:3109` | `total = identified_count + held_unidentified`; `unidentified = held_unidentified` | **YES (live)** | `camera_unrecognized` (P2a), `held_unidentified` (P2c via P2b), `identified = |ble ∪ face_recognized_names|` | **BROKEN** — over-counts by 5 tonight |
| P2a | Enhanced camera raw | `_get_unrecognized_camera_count` `:2670-2826` | per-Frigate: `max(0, count-1)` if fresh face else `count`; per-area MAX; + `unassigned_raw`; then per-area BLE-cancel `min(raw_max, ble_here)` | Feeds P2 | Fresh-face `−1` (needs `sensor.<base>_last_recognized_face` age ≤ 1800s); BLE-cancel needs `_ble_home_by_area` to return non-empty overlap | **BOTH DEFENSES RETURN ZERO NOW.** `camera_unrecognized == frigate_count == 6` (no fresh-face fired); `ble_cancelled_count = 0` (no area subtraction) |
| P2b | Face-recognized names | `_get_face_recognized_person_names` `:2828+` | 30-min freshness gate + `person.<slug> != not_home` cross-check | Feeds P2 identified | `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS = 1800` (rung 1) | Returns `[]` while `face_confirmed = [4 names]` — gate blocking all 4 |
| P2c | Hold/decay | `_apply_hold_decay` `:2500` | 3-min interior hold; then `−1 / 300s` decay; upward moves need 15s sustain | Feeds P2 unidentified | `CENSUS_PEAK_SUSTAIN_SECONDS=15`, `CENSUS_DECAY_STEP_SECONDS=300` | Working as designed — but makes P2's over-count *durable* (~25 min to decay 6→1) |
| P3 | WiFi guest count | `_get_wifi_guest_count` `:2828` | full filter | **NO** — attribute-only `wifi_guest_floor` | — | Diagnostics-only per docstring `:3081-3087` |

**Why this check exists:** the fact that P1 and P2 have *different, incompatible*
invariants — one subtractive, one additive — was never asserted anywhere.
P2 shipped as a replacement for P1's aggregation but silently dropped P1's
double-count-impossibility guarantee. D1 restores it as a **clamp on P2's
output** rather than a third fail-open correction stacked inside P2a.

Dependency health rollup: **P2a's two defenses depend on live conditions that
regularly fail** (face-recognition freshness, BLE-area overlap). **P1's
derivation depends only on set arithmetic** and cannot fail open. D1 borrows
P1's arithmetic as a ceiling on P2's output. Independently repairing P2a's
defences (face freshness, BLE-area coverage) is a separate KP chain
(out of scope, see § Non-goals).

---

## CONSUMER + call-site check

Fan-out via `SIGNAL_CENSUS_UPDATED` — two subscribers; every other reader
consults `hass.data[DOMAIN]["census"].last_result` directly. Enumerated from
RESEARCH §2.1 + §2.2, re-greped for this plan:

**Trust decisions (actuation / state change):**

| Consumer | file:line | Reads | Effect | Sensitive to over-count? |
|---|---|---|---|---|
| Presence ingress | `presence.py:4301-4357` | full payload | schedules `_run_inference("census_update")` | Yes (fan-out) |
| Nobody-home → AWAY | `presence.py:1059-1063` | `census_count`, `any_zone_occupied` | AWAY @ 0.9 | Yes — over-count blocks AWAY |
| Path α away-veto | `presence.py:1091-1101` | `face_recognized_count == 0` (post v5.78.0 D8) | AWAY @ 0.95 | No — D8 severed |
| Path β | `presence.py:1163-1177` | `census_count == 0` | veto | Yes |
| `has_people` | `presence.py:1211-1214` | `census_count > 0` | blocks AWAY-family transitions | Yes |
| GUEST exit | `presence.py:1241-1243` | `unidentified_count == 0 and not guest_gate_armed` | exits GUEST | Yes — over-count prevents exit |
| GUEST entry | `presence.py:1262-1274` | `guest_gate_armed` | enters GUEST | **YES — root cause fan-out** |
| Guest gate (Path A) | `presence.py:4861-4938` | `unidentified_count`, `census_confidence` | arms Path A | Yes |
| Sustained external empty | `presence.py:5687-5695` | `_census_count == 0` | immediate-engage veto limb | Yes |
| Wake backstop | `presence.py:6004-6014` | `_census_count > 0` | SLEEP→WAKING | Yes |
| Veto oracle H1 | `presence.py:1877-1897` | both zero | veto | Yes |
| Boot settle | `presence.py:5080-5093` | `>= BOOT_SETTLE_MIN_INPUTS` | release | Yes |
| Boot seeding | `presence.py:2616-2647` | `last_result.house.total_persons` | first-inference seed | Yes |
| **Security lockdown** | `security.py:774-775, 969-1010` | `intent.source == "census_update"` | **locks all doors, HIGH NM, recording** | Yes — highest-consequence |
| Phone-left-behind suppress | `binary_sensor.py:1769-1773` | `total_persons > 0` | suppresses alarm | Yes |
| Per-room identified | `coordinator.py:1027-1033` | `census.get_room_identified_persons` | per-room presence feed | No (per-room, not house total) |

**Display-only** (RESEARCH §2.2): all census sensors, `sensor.py:4354-4416`
(parallel duplicate derivation — flagged for future collapse, NOT in this
cycle), `sensor.py:4947-4961` (D2c observability), `binary_sensor.py:1527-1585`
(UnexpectedPerson), `binary_sensor.py:1610-1660` (CensusMismatch),
`aggregation.py:5927-5995`, `presence.py:6429-6451`.

**Every consumer above sees the P2 output.** D1's clamp changes the value they
see; the shape of the payload does NOT change (no new keys). Byte-identity is
NOT expected on ticks where the clamp fires; identity IS expected on ticks
where the enhanced path was already producing raw-compatible values (i.e.
when both defenses were working). D2 changes only `guest_armed`; the
`_d5_guest_confidence` value goes 0.8→0.95 when both operands fire, else
0.9 (unchanged) or the gate is disarmed (0.8 branch becomes unreachable).

---

## Deliverables

### D1 — Subtractive clamp on the enhanced path (+ enhanced observability)

**File:** `custom_components/universal_room_automation/camera_census.py`
**Site:** `_apply_enhanced_house_census` at `:3109` (the `total = identified_count + held_unidentified` line).
**Companion (G2 — observability, ships as D1's acceptance instrument):**
`camera_census._get_unrecognized_camera_count` writes
`self._last_enhanced_area_contributions = dict(area_contributions)` after
Step 3 (`:2816`). `sensor.py:3511` reads
`_last_enhanced_area_contributions` in preference to
`_last_area_contributions` when `enhanced_census` is True (fall through to
raw on the disabled path).

**Change (~10 LoC of arithmetic + ~5 LoC observability):**

```python
# camera_census.py, replace the single line at :3109
# Raw-derivation ceiling: the subtractive path cannot exceed
# max(camera_unrecognized, identified). Clamp the additive form to it.
# camera_unrecognized is already per-area-deduped by _get_unrecognized_camera_count.
raw_total_ceiling = max(camera_unrecognized, identified_count)
additive_total    = identified_count + held_unidentified
clamped_total     = min(additive_total, raw_total_ceiling)
clamped_unidentified = max(0, clamped_total - identified_count)

total = clamped_total
# use clamped_unidentified in the CensusZoneResult below
```

Then in the returned `CensusZoneResult(...)` at `:3111-3137`, replace
`unidentified_count=held_unidentified` with `unidentified_count=clamped_unidentified`.

**Arithmetic proof (tonight):**
- Inputs: `identified_count = 4` (BLE union face-names=[]), `camera_unrecognized = 6`, `held_unidentified = 6`.
- `raw_total_ceiling = max(6, 4) = 6`.
- `additive_total = 4 + 6 = 10`.
- `clamped_total = min(10, 6) = 6`. `clamped_unidentified = max(0, 6-4) = 2`.
- **Matches the raw path's derivation on the same inputs exactly.**

**Proof it cannot suppress a real guest:** a genuine stranger's camera
detection contributes to `camera_unrecognized` (they are not in any BLE-here
area with a resident to cancel them; they have no fresh face). So
`camera_unrecognized ≥ identified + 1` whenever a stranger is on camera →
`raw_total_ceiling ≥ identified + 1` → `clamped_total ≥ identified + 1` →
`clamped_unidentified ≥ 1`. The stranger cannot be clamped away.

**Proof it does not silently break the working case:** on a tick where both
P2a defenses fire correctly, `camera_unrecognized = strangers` exactly. If
`strangers > identified` the min picks the additive form (`identified +
strangers`) — same as before. If `strangers ≤ identified` (residents home,
few or zero strangers), the additive form is bounded by the ceiling —
same as before. The clamp fires **only** when the additive form exceeds
what the raw derivation would have produced — which is precisely the
double-count case.

**Non-change:** `_apply_enhanced_property_census` (`:3139`) is unchanged.
Exterior is additive-of-zero-or-one per camera and doesn't have the
resident-double-count failure mode. Confirmed by re-reading `:3139-3171`.

### D2 — Invert the guest composition (guest rooms lead, census corroborates)

**File:** `custom_components/universal_room_automation/domain_coordinators/presence.py`
**Sites:** composition at `:5384-5404`, confidence at `:5406-5414`.

**Change (~5 LoC):**

```python
# presence.py :5383-5404 — home-like branch:
if current_state in _home_like_states:
    unid_gate_armed = self._guest_gate_armed(
        unidentified_count=self._unidentified_count,
        census_confidence=self._census_confidence,
        now=now,
    )
    guest_room_gate_armed = self._guest_room_gate_armed(now=dt_util.utcnow())
    # GUEST-CENSUS: guest rooms LEAD. Path A (census-unidentified) is a
    # corroborator only, used to raise confidence when both fire.
    guest_armed = guest_room_gate_armed
# elif HouseState.GUEST branch unchanged (was already guest_room only).
# else branch unchanged.
```

Confidence block (`:5407-5414`):

```python
if guest_room_gate_armed and unid_gate_armed:
    _d5_guest_confidence = 0.95   # room + census corroboration
elif guest_room_gate_armed:
    _d5_guest_confidence = 0.9
else:
    _d5_guest_confidence = 0.8    # unreachable under the new predicate; kept for shape
```

**Predicate summary:** GUEST arms iff `_guest_room_gate_armed()` is True
(kill switch OFF, ≥1 designated guest room occupied by an unknown occupant
for `threshold_min`). `_guest_gate_armed()` (Path A) contributes only to
confidence.

**Preservation checks:**
- Real guest sleeping in a flagged guest room: `guest_room_gate_armed=True`
  after 30 min → GUEST @ 0.9 (or 0.95 with census). Unchanged.
- Manual override (`services.set_house_state`, select entity) bypasses
  the entire inference path via `HouseStateMachine.set_override()`
  (`house_state.py:213-221`). Untouched.
- GUEST exit at `:1241` tests `guest_gate_armed` (the OR result) — the
  new `guest_armed = guest_room_gate_armed` still cleanly evaluates to
  False when the room clears, so the exit condition is compatible. v5.16.0
  D1 ordering (`presence.py:1228-1243`) is preserved (we did not touch it).
- Inside-GUEST re-evaluation branch (`:5393-5400`) was already
  `guest_armed = guest_room_gate_armed` — unchanged.
- Kill switch `switch.ura_presence_guest_detection_enabled` still gates
  Path A inside `_guest_gate_armed` `:4882-4884`; Path B's kill lives
  inside `_guest_room_gate_armed`. Unchanged.

### D3 — Guest-room entity resolution via registry (not string-build)

**File:** `custom_components/universal_room_automation/domain_coordinators/presence.py`
**Sites:** `_discover_guest_rooms` at `:4704-4724`; `_handle_guest_room_occupancy_change`
entity→room-name lookup at `:4757-4762`.

**Root cause:** `f"binary_sensor.{room_slug}_occupied"` where
`room_slug = room_name.lower().replace(" ", "_")` is a *guess* at the
current entity_id. "Upstairs Guestroom" was renamed → its real entity is
`binary_sensor.upstairs_guest_bedroom_occupied` → the listener subscribes to
nothing → the room can NEVER signal. 1 of 2 remaining live-guest-flagged
non-bathroom rooms is inert, and D2 makes rooms load-bearing.

**Fix (~15 LoC):** resolve via entity registry using the well-known
unique_id `f"{entry.entry_id}_occupied"` (verified: `entity.py:34` +
`binary_sensor.py:245`).

```python
# _discover_guest_rooms — inside the per-entry loop, replace the
# f"binary_sensor.{room_slug}_occupied" construction with:
from homeassistant.helpers import entity_registry as er
ent_reg = er.async_get(self.hass)
unique_id = f"{entry.entry_id}_occupied"
occupancy_entity_id = ent_reg.async_get_entity_id(
    "binary_sensor", DOMAIN, unique_id
)
if not occupancy_entity_id:
    _LOGGER.warning(
        "D5 guest room '%s' (entry=%s): no binary_sensor occupied entity "
        "registered (unique_id=%s); skipping registration.",
        room_name, entry.entry_id, unique_id,
    )
    continue

# Store entity_id <-> room_name mapping so the handler doesn't have to
# reverse-slugify.
self._guest_room_entity_to_name[occupancy_entity_id] = room_name
```

Add `self._guest_room_entity_to_name: dict[str, str] = {}` to
`__init__`/`async_setup` init (same site as `_guest_room_state` /
`_guest_room_unsubs`; clear alongside them in the reconfigure branch at
`:4691-4692`).

In `_handle_guest_room_occupancy_change` (`:4757-4762`), replace the
slug-reverse loop with:

```python
room_name = self._guest_room_entity_to_name.get(entity_id)
if room_name is None:
    return
```

**Same bug class** as the PWA slugify-guessing fix — entity_id ≠ derived
identifier; always resolve through the registry using unique_id.

---

## Non-goals (do NOT ship in this cycle)

Every item below is called out because it appeared adjacent to the diff
during scoping. Each has its own home:

- **Bathroom guard (was D4).** DROPPED per operator ruling 2026-08-16 (scope
  trim, "just config is fine"). Bathrooms-are-not-guest-rooms is an
  operator config convention, deliberately NOT enforced in code (no-cruft).
  Down Guest Bathroom is being unflagged via a config rider on next
  restart. Residual risk accepted: a future re-flag of a bathroom-typed
  room would make a long shower a guest signal under D2. Revisit only if
  that happens.
- **G6 — persistence gate on raw unidentified.** Card
  `CENSUS-G6-RAW-PERSISTENCE` (parked). Revisit trigger: after D1+D2 live
  + one real gathering, if guest still false-fires on multi-person
  transient over-counts.
- **G7 — `guest_mode_require_confidence` medium→high.** REJECTED (RESEARCH
  §7): confidence measures platform agreement, not correctness; already
  reads `high` while the count is wrong. D2 makes the census confidence a
  corroborator only, so raising it would only shrink the 0.95 case.
- **G8 — `CONF_GUEST_MODE_MIN_UNIDENTIFIED`.** Dropped in v4.6.2.2; D2
  makes it redundant. No new knob.
- **G9 — outdoor-zone camera-census filter** (v5.7.0 WS-A Residual-B1).
  Latent-safe today (Patio has no camera person inputs). Separate cycle.
- **Face-recognition freshness repair.** `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS`
  and the `person.<slug> != not_home` cross-check gate — separate KP chain
  (F2 tuning + person-tracker freshness). Explicitly out of scope; D1's
  clamp neuters its criticality by capping the total.
- **Parallel duplicate unidentified derivation** at `sensor.py:4354-4416`.
  Collapse candidate for a follow-on cleanup, not this cycle.
- **Guest actuation surface** (§4 in RESEARCH — the OVERRIDE_SOURCE_GUEST_MODE
  producer that was deleted for zero callers). Do NOT build actuation on top
  of a count that reads 10 for 5 (operator ruling, RESEARCH §7 closing note).
- **Path β symmetric clause** at `presence.py:1163-1177` still gates on
  `census_count == 0` (v5.78.0 D8 explicitly kept it asymmetric). Untouched.

---

## Knob-ladder statement

**Zero new knobs.** No CONF_*, no `const.py` numeric additions, no Number
/ Select / Switch entity, no options-flow field. Verified by exhaustive
grep of `const.py`, `config_flow.py`, `options_flow.py`, `sensor.py`,
`binary_sensor.py`, `number.py`, `switch.py`, `select.py`, `button.py`,
and the six coordinator files under `domain_coordinators/`. D1 uses
existing arithmetic; D2 changes a single boolean expression; D3 uses
existing registry helpers and the existing unique_id scheme.

Internal implementation details introduced (not knobs, not persisted):
`PersonCensus._last_enhanced_area_contributions` (dict, transient),
`PresenceCoordinator._guest_room_entity_to_name` (dict, transient).

---

## Discriminating acceptance criteria

**Ground-truth rule:** the census total is validated against the operator's
**known headcount at the moment of check**, not against
`identified_count`. Using `identified_count` as the oracle is exactly what
hid this bug for weeks (D8 residual). All criteria below name the
independent oracle explicitly.

### D1 — clamp

- **In-suite:** unit test in `quality/tests/` — construct
  `_apply_enhanced_house_census` inputs with `identified_count=4`,
  `camera_unrecognized=6`, `held_unidentified=6`; assert
  `result.total_persons == 6` and `result.unidentified_count == 2` (matches
  raw derivation on same inputs).
- **Under fix:** `sensor.universal_room_automation_persons_in_house` state
  transitions from 10 → 6 within one `SCAN_INTERVAL_CENSUS` (30s) after
  restart, with `identified_count=4`, `unidentified_count=2`,
  `camera_unrecognized=6`.
- **Under a plausible different failure (clamp too aggressive):** if the
  clamp used `min(camera_unrecognized, identified)` instead of `max`, the
  live state would drop to 4 with `unidentified_count=0` — visibly wrong
  because `camera_unrecognized=6 > identified=4` proves at least 2
  unrecognized detections exist. Reviewer D drills this by
  source-mutating the ceiling to `min(...)` and confirming a specific test
  fails.
- **Real-guest preservation:** integration test — arrange
  `identified_count=4, camera_unrecognized=5, held_unidentified=5`
  (residents + one stranger). Assert `total_persons == 5`,
  `unidentified_count == 1`. The stranger is not clamped away.
- **Live (with ground truth):** at next real gathering of N known people,
  the operator reports headcount = N. Assert
  `total_persons ∈ [N, N + camera_unrecognized_beyond_residents]` and NEVER
  `identified + camera_unrecognized` when identified overlaps camera.
- **G2 instrument (live):** `state_attr('sensor.universal_room_automation_persons_in_house','area_contributions')`
  is non-empty on the enhanced path within one tick after any camera
  produces a person detection (was live-`{}` pre-fix because it read the
  raw producer).

### D2 — composition

- **In-suite:** parameterized test over the four combinations of
  `(guest_room_gate_armed, unid_gate_armed)` in `_home_like_states`:
  `(F,F)→False, (F,T)→False, (T,F)→True, (T,T)→True`. Under the OLD code
  `(F,T)` was `True`; under the fix it is `False`. This is the single
  discriminating test.
- **Under fix:** with today's exact live payload
  (`unidentified_count=6, guest_confidence=high`, no guest room occupied
  by an unknown for 30 min), `_guest_gate_armed=True` but `guest_armed=False`.
  The 50-episode daytime-flap FP pattern (RESEARCH §5 GUEST-FP-RESIDUALS-1)
  does not fire.
- **Under plausible different failure (predicate wrong direction):** if the
  fix were written incorrectly as
  `guest_armed = unid_gate_armed and not guest_room_gate_armed`, the
  `(T,F)` case would fail — a real guest sleeping in a designated guest
  room with no unidentified census would NOT arm GUEST. Reviewer drills
  this via truth-table test.
- **Live:** on next real guest arriving to Guest Bedroom 1 or Upstairs
  Guestroom, `sensor.universal_room_automation_house_state` transitions to
  `guest` after `threshold_min` (30 min) and stays until the room clears +
  exit debounce. Attributes: confidence 0.9 (room only) or 0.95 (room +
  census corroboration).

### D3 — entity resolution

- **In-suite:** test with a mock entity registry — register a fake room
  entry with `unique_id=f"{entry_id}_occupied"` under a WRONG-guessed
  slug (e.g. entity_id `binary_sensor.upstairs_guest_bedroom_occupied`
  for a room named "Upstairs Guestroom" which would slug to
  `upstairs_guestroom`). Assert `_discover_guest_rooms` resolves to the
  correct entity_id via the registry and subscribes to the correct one.
  Under the OLD code the subscription target would be the wrong string.
- **Under fix (live):** `_guest_room_entity_to_name` on
  `PresenceCoordinator` includes the *actual*
  `binary_sensor.upstairs_guest_bedroom_occupied` (not the string-built
  `binary_sensor.upstairs_guestroom_occupied`, which does not exist in the
  registry). Verifiable via a debug service or a DEBUG log line at
  registration.
- **Under a plausible different failure (registry miss silently ignored):**
  if the warning + `continue` were replaced with a silent `continue`, the
  test that asserts a WARNING log for a missing entity would fail.

**Before-picture (currently-wrong live state, to be captured in the README
pre-deploy):**
- `sensor.universal_room_automation_persons_in_house = 10`
  (`identified_count=4`, `unidentified_count=6`) for ~5 real people.
- `sensor.universal_room_automation_house_state = guest`, since 13:38 CT,
  `is_overridden=false`, on Path A alone (no guest room has sustained
  unknown occupancy).
- `state_attr('...persons_in_house','area_contributions') = {}`
  (observability blind on the enhanced path).
- `_discover_guest_rooms` subscribes to nonexistent
  `binary_sensor.upstairs_guestroom_occupied` — Upstairs Guestroom cannot
  signal.

**After-picture (post-deploy expected):**
- `persons_in_house` in `[N, N+strangers_on_camera]` — never
  `identified + camera_unrecognized` when they overlap.
- `house_state = guest` only when a designated non-bathroom guest room has
  sustained unknown occupancy for 30 min. The 50 daytime FP episodes since
  07-13 stop.
- `area_contributions` non-empty when any camera contributes.
- Registration log shows Upstairs Guestroom subscribed to
  `binary_sensor.upstairs_guest_bedroom_occupied`.

---

## Tier 2-DB review framings

Three parallel, framing-disjoint reviews (CLAUDE.md § Tier 2-DB):

- **Review A — arithmetic correctness + clamp cannot suppress real guests.**
  Focus on D1: byte-identity on non-clamp ticks; ceiling math with every
  boundary (`camera_unrecognized=0`, `identified=0`, `held_unidentified=0`,
  each in isolation and combinations); interaction with `_apply_hold_decay`
  during decay (does clamping the *total* trigger unwanted decay behaviour?
  Check `_apply_hold_decay` is called BEFORE the clamp, on `unidentified_raw`,
  so decay state is unaffected).
- **Review B — cross-coordinator ripple.** Focus on D2: enumerate every
  consumer of `guest_gate_armed` / `_guest_gate_armed` / `_guest_room_gate_armed`
  independently of this plan's table. Confirm exit ordering (v5.16.0 D1)
  preserved. Confirm HouseState transition validity (GUEST from HOME_NIGHT
  post v5.16.0 D1b) unaffected. Confirm security lockdown (`security.py:774`)
  behaviour when GUEST no longer arms on census-alone. Confirm HVAC
  arrester-hold-preserving states (`hvac_const.py:224`) still trigger only on
  legitimate GUEST entries. Verify D3 registry lookup handles the
  reconfigure-without-restart path (`:4685-4692` iteration clears
  `_guest_room_entity_to_name` too).
- **Review C — test authority via per-site source mutation.** For each of
  D1's clamp line, D2's `guest_armed = guest_room_gate_armed` line, and
  D3's registry-lookup call, mutate the production source to
  bypass/neuter that ONE site and confirm a SPECIFIC test fails (name it).
  Global monkeypatch does NOT count. Confirm test fixtures use real
  config-entry construction, not hand-built stubs (v5.8.0 incident
  lineage).

**Pre-deploy snapshot:** capture the current live values in the
before-picture above into `README_v<version>.md` — they are the load-bearing
diff for post-deploy Review D. Also capture `_guest_room_state` keys via
debug snapshot pre-fix.

**Live Validation (Review D):** post-restart, verify the four
after-picture bullets. Write the observed values back into the README
as the `Validated <date>` table per CLAUDE.md § Record Live Validation
Back Into the README.

---

## Files touched (net)

- `custom_components/universal_room_automation/camera_census.py` — D1 (clamp + `_last_enhanced_area_contributions` write).
- `custom_components/universal_room_automation/sensor.py` — G2 (read `_last_enhanced_area_contributions` when enhanced).
- `custom_components/universal_room_automation/domain_coordinators/presence.py` — D2, D3.
- `quality/tests/…` — new tests per acceptance criteria (D1 clamp arithmetic,
  D1 real-guest preservation, D2 composition truth table, D3 registry-based
  resolution).

Estimated net LoC: ~25 production + tests.
