# PLANNING — Guest / Census correctness cycle (rev-2)

**Card:** `CENSUS-GHOST-DEDUP-1` (operator-approved 2026-08-16).
**Tier:** **2-DB** — census + house-state are shared primitives; trust-hierarchy
ripple (census → presence → security lockdown, HVAC hold preservation,
learning suppression, phone-left-behind, veto oracles). Three framing-disjoint
reviews required.
**Scope discipline:** hard no-cruft. **THREE deliverables**, ~30 LoC net,
ZERO new knobs. Anything not listed under D1-D3 is explicitly out of scope
(§ Non-goals).
**Spec source:** `docs/planning/RESEARCH_guest_actuation_and_census.md`
(commit `8f55b243d`), §1.6 (root cause), §6 (diff), §7 (G1/G4), §3.1 (D5 wiring).

**Rev-2 (2026-08-16):** rewritten after plan-review verdict DO NOT SHIP
(`docs/reviews/code-review/guest_census_plan_review.md` @ `b7d22574b`).
Changes vs rev-1:

- **P1 fix:** the D1 clamp ceiling is now the **PRE-BLE-cancel** per-area-max
  scalar produced at Step 2 of `_get_unrecognized_camera_count`
  (`camera_census.py:2779`), NOT the POST-cancel return value at `:3090`
  which subtracts identified persons' camera contributions and can drive
  the ceiling below `identified + 1` once cancellation defenses are
  repaired (reviewer's reachable counter-example: 4 residents cancelled,
  1 guest → old ceiling suppresses the guest to 0 unidentified). Invariant
  renamed **INV-CENSUS-ATTRIBUTION** and restated below.
- **P2 fix (folded into D1 as G2 refactor):** publish the pre-cancel
  scalar, the per-area raw-max dict, the `ble_by_area` snapshot, and the
  live kill-switch value — so a human can discriminate "BLE-cancel ran and
  cancelled zero" from "BLE-cancel never ran". The same scalar serves
  both P1 and P2.
- **M1:** D2 preservation section now names the behavioral trades honestly
  (guests in non-flagged rooms, guests under 30 min).
- **M2:** ground-truth acceptance for tonight given as exact expected
  numbers (5-person household, both defenses still broken) with a numeric
  FAIL threshold, not a loose range.
- D3 unchanged (reviewer confirmed sound).

---

## Falsifiable invariants

**INV-CENSUS-ATTRIBUTION (rev-2, replaces INV-CENSUS-CLAMP).** For every
enhanced-path tick, no person may contribute to both `identified_count`
and `unidentified_count`. Scalarly:

    identified_count + unidentified_count  <=  max(camera_total_pre_area_cancel, identified_count)

where **`camera_total_pre_area_cancel`** is the fresh-face-adjusted,
per-area-deduped, **PRE-BLE-cancel** scalar computed at Step 2 of
`_get_unrecognized_camera_count` (`camera_census.py:2779`):

    camera_total_pre_area_cancel  =  sum(area_raw_max.values()) + sum(unassigned_raw)

Rationale: BLE-cancel (`:2798-2816`) and fresh-face `−1` (`:2760`) are
**dedup optimizations INSIDE `camera_unrecognized`**; they must not
tighten the attribution ceiling, because doing so would subtract
identified persons twice — once via BLE-cancel of their camera
contribution, once via the ceiling. The raw path's `camera_total`
(`camera_census.py:1331` via `_dedup_by_area`) is also pre-cancel by
construction (the raw path never applies BLE-cancel), so this ceiling is
the correct structural analogue of the raw derivation.

**INV-GUEST-LEAD.** For every inference tick with `current_state ∈
_home_like_states`, GUEST entry requires
`_guest_room_gate_armed() == True`. `_guest_gate_armed()` (census-unidentified)
alone MUST NOT be sufficient to enter GUEST. (Path C manual override
`house_state.py:213-221` is not covered by this invariant — by product design.)

**INV-GUEST-NO-RESIDENT (added 2026-08-16, fix-up round 2).** In **any** reachable
path — including boot, config-entry reload, guest-room re-discovery, and kill-switch
toggle — a designated guest room occupied **solely by known tracked residents** MUST
NOT cause `_guest_room_gate_armed()` to return True.

*Why this invariant is separate from INV-GUEST-LEAD, and why it exists:* INV-GUEST-LEAD
is satisfied whenever the room gate arms, regardless of **who** is in the room. The
fix-up-round-1 boot-seed defect satisfied INV-GUEST-LEAD completely while being exactly
the failure the cycle exists to prevent. An invariant that a real defect can satisfy is
not doing any work.

*The falsifying repro (must be a permanently failing-then-passing regression test):*
resident in a designated guest room, occupancy `on` since hours ago → HA restarts →
`_discover_guest_rooms` runs before `person_coordinator` is populated, so
`_is_known_person_in_room()` returns its documented `False` fallback → `first_seen`
seeds to `last_changed` (hours ago) and `current_occupancy_known` initialises `False`
→ the gate's elapsed already exceeds `threshold_min` → **GUEST arms on the first
inference tick.**

*The two structural facts that made it reachable, both of which any future change must
preserve the fix for:*
1. **`current_occupancy_known` is an event-driven producer.** Every writer of it
   (`presence.py` Transitions 1/2/3) lives inside `_handle_guest_room_occupancy`, the
   occupancy **state-change listener**. It is therefore never refreshed for a room whose
   occupancy does not toggle. Any consumer treating it as live truth is wrong.
2. **`_is_known_person_in_room()` fails open to `False`** ("unknown = safer for guest
   detection"). That fallback is only safe while `first_seen` starts at `now`, which
   guarantees a full `threshold_min` of settling time. Pre-ageing `first_seen` removes
   that margin and converts the fail-open into a false-arm.

*Consequence for reviewers:* a fix that relies on the occupancy state-change path to
correct the state does **not** satisfy this invariant, because the repro's defining
feature is that no state change occurs.

D (adversarial-completeness) reviewer's sole job is to falsify these two.

---

## Institutional context verified

**Grepped surfaces** (each addition marked REUSED or NEW):

- `_apply_enhanced_house_census` `camera_census.py:3075-3137` — read end-to-end.
  Additive: `total = identified_count + held_unidentified` (`:3109`).
  Overwrites `raw_result` except confidence/agreement/counts (`:3111-3121`).
- `_cross_correlate_persons` `camera_census.py:1746-1818` — subtractive:
  `unidentified = max(0, camera_total - identified)`, `total = max(camera_total, identified)`.
  Feeder `_calculate_house_census:1331` produces `camera_total` via
  `_dedup_by_area` (per-area MAX summed, **no BLE cancel**).
- `_get_unrecognized_camera_count` `camera_census.py:2670-2826` — Step 1
  fresh-face `−1/camera` (`:2740-2766`), Step 2 per-area MAX + `unassigned_raw`
  (`:2768-2779`), Step 3 BLE-cancel (`:2798-2816`), Step 4 return
  (`:2826`). The returned value is **POST-cancel**. Live
  `ble_cancelled_count = 0` and `camera_unrecognized == frigate_count`
  (RESEARCH §0.1) → both defenses returning zero — which is why POST- and
  PRE-cancel scalars numerically coincide today. **They will diverge
  the moment the defenses work.**
- `sensor.py:3505-3529` — `area_contributions` reads `_last_area_contributions`
  written by the RAW producer (`:1358`) → wrong publisher for enhanced path.
  Refactored under D1's G2 folding.
- `presence.py` → **`domain_coordinators/presence.py`**. `_discover_guest_rooms`
  at `:4668-4730`, `_handle_guest_room_occupancy_change` at `:4732-4801`,
  composition OR at `:5391-5404`, confidence at `:5406-5414`.
- `entity.py:34` — `_attr_unique_id = f"{coordinator.entry.entry_id}_{entity_type}"`.
  Room's occupied binary_sensor: `entity_type = "occupied"`
  (`binary_sensor.py:245`). Registry lookup key:
  `("binary_sensor", DOMAIN, f"{entry_id}_occupied")`. **REUSED** — this
  is how every URA room's occupied entity is registered.
- No new CONF_*, no `const.py` numeric additions, no Number/Select/Switch
  entity, no options-flow field. **ZERO new knobs** — verified by
  exhaustive grep of the six prior-art surfaces in CLAUDE.md
  § Institutional Context First.

**Prior planning docs consulted:** RESEARCH_guest_actuation_and_census.md
(spec, full read); PLANNING_census_overcount_dedup_decay.md (v5.9.0 — do
not re-tune hold/decay); PLANNING_census_ble_cancel_unrecognized.md
(v5.9.x, currently inert — D1 makes its inertness non-fatal);
PLANNING_gap_a_census_hole.md (v5.78.0 D8 additive-payload pattern — not
reused here, we add no new payload key);
PLANNING_v4.7.2_dpm_hvac_surface_plus_guest_signal.md (D4/D5 shipped, LIVE);
PLANNING_presence_guest_latch_and_veto_gap.md (v5.16.0 exit ordering
preserved).

**Memory bodies pulled:** `project_presence_guest_latch_and_veto_gap`;
`project_guest_mode_false_positive_backlog`.

**Design docs read:** `docs/Coordinator/PRESENCE.md`; census logic lives
in `camera_census.py` (no coordinator subclass).

**Code locations surveyed end-to-end during scoping:**
`camera_census.py:1746-1818, 2670-2826, 3060-3172`;
`domain_coordinators/presence.py:4660-4801, 5380-5420`;
`binary_sensor.py:200-246`; `entity.py:1-99`.

---

## PRODUCER check — every derivation of the count

| # | Path | File:line | Formula | Wins? | Health (2026-08-16) |
|---|---|---|---|---|---|
| P1 | Raw subtractive | `camera_census.py:1780-1782` | `unidentified = max(0, camera_total − identified)`; `total = max(camera_total, identified)` where `camera_total` is per-area MAX summed, **pre-cancel** | **NO** — overwritten by P2 when `enhanced_census: True` (live) | Structurally invariant-preserving but never published on live |
| P2 | Enhanced additive | `camera_census.py:3109` | `total = identified_count + held_unidentified`; `unidentified = held_unidentified` | **YES (live)** | **BROKEN** — over-counts by 5 tonight |
| P2a | Enhanced camera raw (POST-cancel) | `_get_unrecognized_camera_count` `:2670-2826` | Step 1 fresh-face `-1` → Step 2 per-area MAX + unassigned → Step 3 BLE-cancel → Step 4 sum. Return = POST-cancel scalar | Feeds P2 `camera_unrecognized` and unidentified_raw | Both defenses (fresh-face, BLE-cancel) return zero → post==pre numerically, coincidentally |
| P2a-pre | Step 2 scalar (NEW publication) | `camera_census.py:2779` | `sum(area_raw_max.values()) + sum(unassigned_raw)` | Feeds D1 clamp ceiling ONLY | New attribute `_last_camera_total_pre_cancel` |
| P2b | Face-recognized names | `_get_face_recognized_person_names` `:2828+` | 30-min freshness + `person.<slug> != not_home` cross-check | Feeds P2 identified | Returns `[]` while `face_confirmed=[4 names]` — gate blocking all 4 |
| P2c | Hold/decay | `_apply_hold_decay` `:2500` | 3-min hold + −1/300s decay + 15s upward sustain | Feeds P2 unidentified | Working as designed but makes P2's over-count durable ~25 min |
| P3 | WiFi guest count | `_get_wifi_guest_count` `:2828` | full filter | **NO** — diagnostics `wifi_guest_floor` only | — |

**Why this check exists / dependency health rollup:** P1's raw derivation
depends only on set arithmetic (cannot fail open). P2's additive
derivation depends on P2a's defenses AND P2b's face freshness. **BOTH P2a
defenses depend on live conditions that regularly fail.** D1 borrows P1's
structural invariant as a ceiling on P2's output, using P2a-pre (Step 2
scalar) — NOT P2a return value — so the ceiling remains sound when P2a's
defenses are repaired.

---

## CONSUMER + call-site check

Fan-out via `SIGNAL_CENSUS_UPDATED` — two subscribers; every other reader
consults `hass.data[DOMAIN]["census"].last_result` directly.

**Trust decisions (actuation / state change):**

| Consumer | file:line | Reads | Effect | Sensitive to over-count? |
|---|---|---|---|---|
| Presence ingress | `presence.py:4301-4357` | full payload | `_run_inference("census_update")` | Yes (fan-out) |
| Nobody-home → AWAY | `presence.py:1059-1063` | `census_count` | AWAY @ 0.9 | Yes |
| Path α away-veto | `presence.py:1091-1101` | `face_recognized_count == 0` (v5.78.0 D8) | AWAY @ 0.95 | No — D8 severed |
| Path β | `presence.py:1163-1177` | `census_count == 0` | veto | Yes |
| `has_people` | `presence.py:1211-1214` | `census_count > 0` | blocks AWAY-family | Yes |
| GUEST exit | `presence.py:1241-1243` | `unidentified_count == 0 and not guest_gate_armed` | exits GUEST | Yes |
| GUEST entry | `presence.py:1262-1274` | `guest_gate_armed` | enters GUEST | **YES — root cause fan-out** |
| Path A gate | `presence.py:4861-4938` | `unidentified_count`, `census_confidence` | arms Path A | Yes |
| Sustained external empty | `presence.py:5687-5695` | `_census_count == 0` | veto immediate-engage | Yes |
| Wake backstop | `presence.py:6004-6014` | `_census_count > 0` | SLEEP→WAKING | Yes |
| Veto oracle H1 | `presence.py:1877-1897` | both zero | veto | Yes |
| Boot settle | `presence.py:5080-5093` | `>= BOOT_SETTLE_MIN_INPUTS` | release | Yes |
| Boot seeding | `presence.py:2616-2647` | `last_result.house.total_persons` | first-inference seed | Yes |
| **Security lockdown** | `security.py:774-775, 969-1010` | `intent.source == "census_update"` | **locks doors, HIGH NM, recording** | Yes — highest-consequence |
| Phone-left-behind | `binary_sensor.py:1769-1773` | `total_persons > 0` | suppresses alarm | Yes |
| Per-room identified | `coordinator.py:1027-1033` | `census.get_room_identified_persons` | per-room presence feed | No |

**Display-only:** all census sensors; `sensor.py:4354-4416` (parallel
duplicate derivation — flagged for future collapse); `sensor.py:4947-4961`
(D2c observability); `binary_sensor.py:1527-1585` (UnexpectedPerson);
`binary_sensor.py:1610-1660` (CensusMismatch); `aggregation.py:5927-5995`;
`presence.py:6429-6451`.

**Payload shape is unchanged.** D1 alters the values seen by every consumer
above on ticks where the clamp fires; byte-identity on other ticks. D2
changes only the composition of `guest_armed` — no payload keys added.

---

## Deliverables

### D1 — Attribution clamp on the enhanced path (+ discriminating observability)

**Files:** `custom_components/universal_room_automation/camera_census.py`,
`custom_components/universal_room_automation/sensor.py`.

**Sites:** `_get_unrecognized_camera_count` Step 2/3 (`:2768-2816`);
`_apply_enhanced_house_census` `:3109`; `sensor.py:3511`.

**Change #1 — publish the discriminating diagnostics (~5 LoC).** After
Step 2 (`:2779`), before Step 3, add:

```python
# G2 (D1): publish the PRE-BLE-cancel per-area-max scalar and dict so
# INV-CENSUS-ATTRIBUTION has a stable ceiling that does NOT drop when
# BLE-cancel repairs, and so observability can discriminate "cancel ran
# and cancelled zero" from "cancel never ran".
self._last_camera_total_pre_cancel = (
    sum(area_raw_max.values()) + sum(unassigned_raw)
)
self._last_area_raw_max_pre_cancel = dict(area_raw_max)
self._last_ble_by_area = dict(ble_by_area)
self._last_ble_cancel_enabled = bool(self._get_ble_cancel_enabled())
```

At the end of Step 3 (after `:2816`), add:

```python
# G2 (D1): enhanced-path per-area contributions POST-cancel — what
# actually feeds camera_unrecognized. Distinct from the raw producer's
# _last_area_contributions (:1358) which sensor.py:3511 currently reads
# and which cannot report the enhanced path's dedup.
self._last_enhanced_area_contributions = dict(area_contributions)
```

`sensor.py:3511` — prefer the enhanced dict when the enhanced path is
active; fall through to raw on the disabled path:

```python
if getattr(census, "_last_enhanced_area_contributions", None) is not None \
        and result.house.enhanced_census:
    attrs["area_contributions"] = dict(census._last_enhanced_area_contributions)
else:
    attrs["area_contributions"] = dict(
        getattr(census, "_last_area_contributions", {}) or {}
    )
# G2 diagnostics — always publish so cancel-ran-vs-never can be told apart.
attrs["area_raw_max_pre_cancel"] = dict(
    getattr(census, "_last_area_raw_max_pre_cancel", {}) or {}
)
attrs["ble_by_area"] = dict(getattr(census, "_last_ble_by_area", {}) or {})
attrs["ble_cancel_enabled"] = bool(
    getattr(census, "_last_ble_cancel_enabled", False)
)
attrs["camera_total_pre_cancel"] = int(
    getattr(census, "_last_camera_total_pre_cancel", 0) or 0
)
```

**Change #2 — the clamp (~10 LoC).** At `_apply_enhanced_house_census:3109`,
replace the single line `total = identified_count + held_unidentified`:

```python
# INV-CENSUS-ATTRIBUTION: attribution ceiling = the raw derivation's
# semantic max. MUST use the PRE-cancel scalar published above; using the
# POST-cancel return would subtract identified residents twice (once via
# BLE-cancel, once via the ceiling), suppressing a real guest when
# cancellation is repaired (reviewer counter-example, plan-review P1).
# Safe to read _last_camera_total_pre_cancel here: we called
# _get_unrecognized_camera_count() at :3090 above, on this tick.
camera_total_pre_cancel = int(
    getattr(self, "_last_camera_total_pre_cancel", 0) or 0
)
raw_total_ceiling    = max(camera_total_pre_cancel, identified_count)
additive_total       = identified_count + held_unidentified
clamped_total        = min(additive_total, raw_total_ceiling)
clamped_unidentified = max(0, clamped_total - identified_count)

total = clamped_total
```

In the returned `CensusZoneResult(...)` at `:3111-3137`, replace
`unidentified_count=held_unidentified` with
`unidentified_count=clamped_unidentified`.

**Re-derivation, tonight's live numbers (5-person household):**

Both P2a defenses are broken → POST-cancel `camera_unrecognized == 6 ==` PRE-cancel.

- `identified_count = 4`; `camera_total_pre_cancel = 6`; `held_unidentified = 6`.
- `raw_total_ceiling = max(6, 4) = 6`. `additive_total = 4 + 6 = 10`.
- `clamped_total = min(10, 6) = 6`. `clamped_unidentified = max(0, 6-4) = 2`.
- **Live sensor drops 10 → 6 within one `SCAN_INTERVAL_CENSUS` (30 s).**

**Re-derivation, reviewer's counter-example (repaired defenses, 5-person household including 1 real guest):**

- 4 residents each in own area (A1..A4) + 1 guest in area A5; per-area pc=1 each.
- Step 2 `area_raw_max = {A1:1, A2:1, A3:1, A4:1, A5:1}`; `unassigned_raw = []`.
- **`camera_total_pre_cancel = 5`** (published NEW, unaffected by cancel).
- Step 3 BLE-cancel on residents' areas: A1..A4 cancelled → `area_contributions = {A5:1}` → **`camera_unrecognized (return) = 1`**.
- `identified_count = 4` (BLE ∪ face); `held_unidentified = 1` (assume stable).
- **Old (WRONG) ceiling** `max(camera_unrecognized, identified) = max(1, 4) = 4`; additive `= 5`; clamped `= min(5, 4) = 4`; unidentified `= 0` → **guest suppressed, reads 4 for 5 people.**
- **New (rev-2) ceiling** `max(camera_total_pre_cancel, identified) = max(5, 4) = 5`; additive `= 5`; clamped `= min(5, 5) = 5`; unidentified `= max(0, 5-4) = 1` → **guest preserved, reads 5 for 5 people.** ✓

**Re-derivation, reviewer's tighter counter-example (2 residents in one area, ble_here=1):**

- `area_raw_max = {A1:2, A2:1, A3:1, A4:1(guest)}` (A1 has 2 residents visible, but only 1 BLE-here).
- `camera_total_pre_cancel = 5`.
- Step 3: A1 correction `min(2,1)=1`, final `1`; A2/A3 cancelled to 0; A4 uncancelled → `camera_unrecognized_return = 2`.
- `identified = 4`, `held = 2`.
- Old ceiling `max(2,4)=4`, additive `6`, clamped `4`, unidentified `0` → **guest suppressed**.
- New ceiling `max(5,4)=5`, additive `6`, clamped `5`, unidentified `1` → **guest preserved**. ✓

**Proof the clamp cannot suppress a real guest under ANY reachable state:**
a stranger contributes to Step 1's `raw_contribution` (they have no face
match anywhere → count is `pc`, not `pc-1`). Their contribution reaches
Step 2 as its own per-area entry (guest is in a different area from any
resident) or as an unassigned entry. Either way,
`camera_total_pre_cancel ≥ (unique identified-people-visible-on-camera) + 1`.
Because identified persons cannot exceed their own on-camera contributions
(the fresh-face `−1` at most zeros them, never negative),
`camera_total_pre_cancel ≥ identified_count + 1` whenever a stranger is
on camera in any area with no resident. Ceiling
`max(camera_total_pre_cancel, identified) ≥ identified + 1` →
`clamped_unidentified ≥ 1`. The stranger cannot be clamped away.

**Proof it does not break the working case:** on a tick where P2a and P2b
work correctly and no double-count exists, `additive_total = identified +
strangers ≤ camera_total_pre_cancel + identified` and the ceiling is
`max(camera_total_pre_cancel, identified)`. The clamp fires only when
`additive_total > raw_total_ceiling`, which by algebra requires
`held_unidentified > camera_total_pre_cancel - identified` — i.e. more
unidentifieds than the pre-cancel camera evidence can support given the
identified. That is precisely the double-count case.

**Non-change:** `_apply_enhanced_property_census` (`:3139`) unchanged.

**Concurrency / lifecycle notes:**
- `_get_unrecognized_camera_count` is called under `_async_update_census_locked`'s
  asyncio lock (`:1097`); publication of `_last_camera_total_pre_cancel` is
  therefore consistent with the tick that reads it in `_apply_enhanced_house_census`.
- Initialize `_last_camera_total_pre_cancel = 0`,
  `_last_area_raw_max_pre_cancel = {}`, `_last_ble_by_area = {}`,
  `_last_ble_cancel_enabled = False`,
  `_last_enhanced_area_contributions = {}` in `PersonCensus.__init__`
  (same site as `_last_area_contributions` / `_last_ble_cancelled_count`).

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
    # GUEST-CENSUS D2: guest rooms LEAD. Path A is a corroborator only,
    # raising confidence when both fire. See M1 trade-off list in plan.
    guest_armed = guest_room_gate_armed
# elif HouseState.GUEST branch unchanged.
# else branch unchanged.
```

Confidence block (`:5407-5414`):

```python
if guest_room_gate_armed and unid_gate_armed:
    _d5_guest_confidence = 0.95   # room + census corroboration
elif guest_room_gate_armed:
    _d5_guest_confidence = 0.9
else:
    _d5_guest_confidence = 0.8    # unreachable under new predicate; kept for shape
```

**M1 — Behavioral trades this cycle DELIBERATELY MAKES (operator-accepted, must be surfaced):**

1. **Non-flagged rooms no longer trigger GUEST.** Under the old OR, an
   unidentified camera detection anywhere in the house could arm GUEST
   via Path A. Under D2, only the operator-flagged guest rooms (currently
   `Guest Bedroom 1`, `Upstairs Guestroom` — plus `Down Guest Bathroom`
   pending its unflag config rider) can arm GUEST. **A guest on the
   couch, in the kitchen, in a bedroom not flagged as a guest room, or
   anywhere else without a designated guest-room flag will NOT activate
   GUEST.** Operator's ruling explicitly accepts this: guest rooms are
   the correct spatial primitive.
2. **Guests present under 30 minutes no longer trigger GUEST.** Path A's
   `guest_mode_persistence_seconds` (300 s = 5 min, live default) is
   replaced as the arming timer by Path B's per-room
   `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN` (currently 30 min on all
   three flagged rooms). Short visits (a plumber accepting a package
   inside, a friend dropping off keys, a courier waiting in the foyer
   for 10 min) will not arm GUEST. If the operator wants a faster arm,
   the existing knob `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN` can be
   lowered per-room via the options flow — this cycle does NOT change
   its default.
3. **Guests in an incorrectly-configured room won't activate GUEST.**
   D2 makes room configuration load-bearing: if a room that should be a
   guest room isn't flagged, or is flagged but doesn't resolve through
   the entity registry (which D3 fixes for the known case), no arming
   occurs. D3 addresses the Upstairs Guestroom rename gap; other future
   renames will need the D3 registry-based resolver to keep working
   (which it does, by design).
4. **Restart mid-visit — RESOLVED in fix-up (Review B-MEDIUM-1, 2026-08-16).**
   ADDED post-review (was missing from the original M1 list). Because
   `_guest_room_state` is RAM-only, an HA restart during a genuine
   in-progress guest visit would previously reset the 30-min sustained
   clock from scratch — Path A's ~5-min re-arm was gone under D2, so the
   effective penalty was 30 min per restart, not 5. **Resolved:** the
   fix-up added an identity-aware boot-seed in `_discover_guest_rooms`
   that seeds `first_seen = occupancy.last_changed` when the entity is
   currently ON and no known person is detected in the room. Restart
   mid-visit now preserves the pre-restart arming clock. Residual: if
   `person_coordinator` tracking hasn't populated at discover time,
   `_is_known_person_in_room` falls back to False (safe default) and
   may seed a resident-occupied room; the runtime gate re-checks
   `current_occupancy_known` on the next occupancy state-change, and
   the seeded `first_seen` is discharged via Transition 2. Accepted.

**FP-suppression claim, honestly qualified:** the 50 daytime guest ENTRY
episodes since 07-13 (RESEARCH §5 GUEST-FP-RESIDUALS-1) are Path-A-shaped.
Under D2 the ones caused by wrong census counts (the vast majority per
tonight's mechanism) will not fire. **However, an unknown fraction of
those episodes may have been legitimate short-duration guests
(deliveries, brief visitors) or guests in non-flagged rooms (couch,
kitchen) — those were guest-mode-worthy under the old predicate and
will NOT fire under the new one.** The reduction in false positives is
real; the reduction in this class of true positives is also real and
accepted.

**Preservation checks (things that DO still work):**
- Real guest sleeping in a flagged guest room: `guest_room_gate_armed=True`
  after 30 min → GUEST @ 0.9 (or 0.95 with census). Unchanged.
- Manual override (`services.set_house_state`, select entity) bypasses
  the entire inference path via `HouseStateMachine.set_override()`
  (`house_state.py:213-221`). Untouched.
- GUEST exit at `:1241` tests `guest_gate_armed` (the OR result) — the
  new `guest_armed = guest_room_gate_armed` still cleanly evaluates to
  False when the room clears, so the exit condition is compatible.
  v5.16.0 D1 ordering (`presence.py:1228-1243`) preserved.
- Inside-GUEST re-evaluation branch (`:5393-5400`) was already
  `guest_armed = guest_room_gate_armed` — unchanged.
- Kill switch `switch.ura_presence_guest_detection_enabled` still gates
  Path A inside `_guest_gate_armed:4882-4884`; Path B's kill lives
  inside `_guest_room_gate_armed`. Unchanged.

### D3 — Guest-room entity resolution via registry (not string-build)

**Unchanged from rev-1.** Reviewer confirmed sound.

**File:** `custom_components/universal_room_automation/domain_coordinators/presence.py`.
**Sites:** `_discover_guest_rooms` at `:4704-4724`; `_handle_guest_room_occupancy_change`
entity→room-name lookup at `:4757-4762`.

**Root cause:** `f"binary_sensor.{room_slug}_occupied"` is a *guess* at
the current entity_id. "Upstairs Guestroom" was renamed → the real entity
is `binary_sensor.upstairs_guest_bedroom_occupied` → subscription silently
fails.

**Fix (~15 LoC):** resolve via entity registry using the well-known
unique_id `f"{entry.entry_id}_occupied"` (`entity.py:34` +
`binary_sensor.py:245`).

```python
# _discover_guest_rooms — per-entry loop, replace the string-build:
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

self._guest_room_entity_to_name[occupancy_entity_id] = room_name
```

Add `self._guest_room_entity_to_name: dict[str, str] = {}` at the same
init site as `_guest_room_state` / `_guest_room_unsubs`; clear in the
reconfigure branch (`:4691-4692`).

In `_handle_guest_room_occupancy_change` (`:4757-4762`) replace the
slug-reverse loop with:

```python
room_name = self._guest_room_entity_to_name.get(entity_id)
if room_name is None:
    return
```

---

## Non-goals (do NOT ship in this cycle)

- **Bathroom guard (was D4 in rev-1).** DROPPED per operator ruling
  2026-08-16 (scope trim, "just config is fine"). Down Guest Bathroom is
  being unflagged via a config rider on next restart. Residual risk
  accepted: a future re-flag of a bathroom-typed room would make a long
  shower a guest signal under D2.
- **G6 — persistence gate on raw unidentified.** Card
  `CENSUS-G6-RAW-PERSISTENCE` (parked).
- **G7 — `guest_mode_require_confidence` medium→high.** REJECTED (RESEARCH
  §7): confidence measures platform agreement, not correctness.
- **G8 — `CONF_GUEST_MODE_MIN_UNIDENTIFIED`.** Dropped in v4.6.2.2; D2
  makes it redundant.
- **G9 — outdoor-zone camera-census filter.** Latent-safe today. Separate
  cycle.
- **Face-recognition freshness / person cross-check repair.** Separate KP
  chain; D1's clamp caps the total damage while the repair chain runs.
- **Parallel duplicate unidentified derivation** at `sensor.py:4354-4416`.
  Follow-on cleanup.
- **Guest actuation surface** (RESEARCH §4). Do NOT build actuation on top
  of a count that reads 10 for 5.
- **Path β symmetric clause** at `presence.py:1163-1177`. Untouched
  (v5.78.0 D8 explicitly asymmetric).

---

## Knob-ladder statement

**Zero new knobs.** No CONF_*, no `const.py` numeric additions, no Number
/ Select / Switch entity, no options-flow field. Verified by exhaustive
grep of `const.py`, `config_flow.py`, `options_flow.py`, `sensor.py`,
`binary_sensor.py`, `number.py`, `switch.py`, `select.py`, `button.py`,
and the six coordinator files under `domain_coordinators/`.

Internal transient attributes introduced (not knobs, not persisted):
`PersonCensus._last_camera_total_pre_cancel` (int),
`PersonCensus._last_area_raw_max_pre_cancel` (dict),
`PersonCensus._last_ble_by_area` (dict),
`PersonCensus._last_ble_cancel_enabled` (bool),
`PersonCensus._last_enhanced_area_contributions` (dict),
`PresenceCoordinator._guest_room_entity_to_name` (dict).

---

## Discriminating acceptance criteria

**Ground-truth rule:** the census total is validated against the operator's
**known headcount at the moment of check**, not against `identified_count`.

### D1 — clamp

- **In-suite (arithmetic ceiling correctness — tonight):** unit test —
  inputs `identified_count=4`, `camera_total_pre_cancel=6`,
  `camera_unrecognized=6`, `held_unidentified=6`; assert
  `result.total_persons == 6`, `result.unidentified_count == 2`.
- **In-suite (repaired-defenses guest preservation — reviewer counter-example):**
  inputs `identified_count=4`, `camera_total_pre_cancel=5`,
  `camera_unrecognized=1`, `held_unidentified=1`; assert
  `result.total_persons == 5`, `result.unidentified_count == 1`. Under
  the OLD (POST-cancel) ceiling this test asserts `4` / `0` and **must
  fail** — it is the load-bearing discriminator between rev-1 and rev-2.
- **In-suite (partial-cancel guest preservation):** inputs
  `identified_count=4`, `camera_total_pre_cancel=5`,
  `camera_unrecognized=2`, `held_unidentified=2`; assert
  `result.total_persons == 5`, `result.unidentified_count == 1`.
- **Under plausible different failure (clamp too aggressive — reviewer D
  drill):** source-mutate the ceiling to
  `max(camera_unrecognized_post_cancel, identified)`; the
  repaired-defenses test above must fail with observed
  `total_persons=4`. Restore, confirm suite green.
- **G2 discriminating observability (in-suite + live):** on any tick with
  `_get_ble_cancel_enabled()` returning True and cancellation summing to
  0, `state_attr('...persons_in_house', 'ble_cancel_enabled') == True`
  AND `ble_cancelled_count == 0` AND
  `sum(state_attr('...persons_in_house', 'ble_by_area').values()) == 0`
  proves the cancel ran and cancelled nothing (the "areas didn't
  overlap" case, per RESEARCH §1.7). If `ble_by_area` is non-empty and
  `ble_cancelled_count == 0`, the areas overlap-mismatch case is proven
  distinct — the diagnostic P2 asked for.
- **Live PRECISE expected (tonight, 5-person household, both defenses
  still broken):**
  - Household ground truth = **5** (4 residents Ezinne / Jaya / Oji / Ziri
    + 1 guest).
  - Pre-fix: `persons_in_house = 10` (`identified=4`, `unidentified=6`).
  - Post-fix expected: **`persons_in_house = 6`**
    (`identified_count = 4`, `unidentified_count = 2`,
    `camera_unrecognized = 6`, `camera_total_pre_cancel = 6`). The `+1`
    residual over ground truth is the underlying unrepaired cancellation
    gap — the clamp caps the total damage to `pre_cancel` but cannot
    itself repair the cancellation. Documented as expected in the README.
  - **Numeric FAIL threshold (any of):**
    - `persons_in_house >= 8` on any single tick post-restart, OR
    - `persons_in_house >= 7` sustained across ≥3 consecutive ticks
      (`SCAN_INTERVAL_CENSUS = 30 s` → 90 s window), OR
    - `unidentified_count >= 4` post-restart, OR
    - `identified_count + unidentified_count > camera_total_pre_cancel`
      on any tick (invariant violation, direct).
  - **PASS band:** `persons_in_house ∈ {5, 6}` with
    `identified_count = 4` and `unidentified_count ∈ {1, 2}`, sustained
    for ≥5 ticks (150 s) post-restart. `5` requires at least partial
    cancellation to have started firing (not expected tonight);
    `6` is the expected steady-state given the current broken defenses.
- **Live (next real gathering with N known people):** operator reports
  headcount N; assert `persons_in_house ∈ [N, N + max(0,
  camera_total_pre_cancel − N)]` and NEVER `identified_count +
  camera_unrecognized_post_cancel` when they overlap. Any reading
  exceeding `camera_total_pre_cancel` is a direct invariant violation
  and FAIL.

### D2 — composition

- **In-suite (truth-table discriminator):** parameterized test over
  `(guest_room_gate_armed, unid_gate_armed)` in `_home_like_states`:
  `(F,F)→False, (F,T)→False, (T,F)→True, (T,T)→True`. Under OLD code
  `(F,T)` was `True`; under fix it is `False`.
- **Under fix (live, tonight):** with live payload
  `unidentified_count=6, guest_confidence=high`, no guest room occupied
  by unknown for 30 min → `_guest_gate_armed=True` but
  `guest_armed=False`; `house_state` transitions out of `guest` within
  its exit debounce window.
- **Under plausible different failure (wrong direction):**
  source-mutate to `guest_armed = unid_gate_armed and not
  guest_room_gate_armed`; the `(T,F)` truth-table test must fail.
- **Live (next real long-visit guest to a flagged room):** transitions
  to `guest` after 30 min sustained occupancy; confidence 0.9 (room
  only) or 0.95 (room + census).
- **M1 trade acceptance (organic):** track any operator-flagged
  "should-have-been-guest" episode where a guest was in a non-flagged
  room or present under 30 min — recorded, NOT considered a regression
  per operator ruling.

### D3 — entity resolution

- **In-suite:** with mock entity registry, register unique_id
  `f"{entry_id}_occupied"` under a WRONG-guessed entity_id
  (`binary_sensor.upstairs_guest_bedroom_occupied` for room "Upstairs
  Guestroom" which slugs to `upstairs_guestroom`); assert
  `_discover_guest_rooms` resolves via registry to the correct
  entity_id.
- **Under plausible different failure:** silent `continue` on registry
  miss must fail a WARNING-log assertion test.
- **Live:** `_guest_room_entity_to_name` on `PresenceCoordinator`
  includes the actual `binary_sensor.upstairs_guest_bedroom_occupied`;
  registration log confirms.

**Before-picture (currently-wrong live state, captured in README pre-deploy):**
- `sensor.universal_room_automation_persons_in_house = 10`
  (`identified_count=4`, `unidentified_count=6`) for **5 real people**.
- `sensor.universal_room_automation_house_state = guest`, since 13:38 CT,
  `is_overridden=false`, on Path A alone.
- `state_attr('...persons_in_house','area_contributions') = {}`.
- `_discover_guest_rooms` subscribes to nonexistent
  `binary_sensor.upstairs_guestroom_occupied`.

**After-picture (post-deploy expected):**
- `persons_in_house = 6` for 5 real people (D1 clamp active; underlying
  cancellation still broken → the +1 residual). Never `≥ 7` in steady state.
- `house_state = guest` only when a designated non-bathroom guest room
  has sustained unknown occupancy for 30 min. The daytime FP class
  characterised in RESEARCH §5 stops.
- `area_contributions` non-empty when any camera contributes on the
  enhanced path; `area_raw_max_pre_cancel`, `ble_by_area`,
  `ble_cancel_enabled`, `camera_total_pre_cancel` all published and
  usable to discriminate cancel-ran-vs-never.
- Registration log shows Upstairs Guestroom subscribed to
  `binary_sensor.upstairs_guest_bedroom_occupied`.

---

## Tier 2-DB review framings

- **Review A — arithmetic + attribution ceiling soundness.** Focus on D1:
  ceiling comes from Step 2 (PRE-cancel), not Step 4 (POST-cancel).
  Enumerate every boundary (`camera_total_pre_cancel=0`,
  `identified=0`, `held_unidentified=0`, each in isolation and
  combinations). Confirm `_apply_hold_decay` runs on `unidentified_raw`
  BEFORE the clamp (unaffected decay state). Re-run reviewer's
  counter-example and the tighter partial-cancel case: rev-2 must PASS
  both.
- **Review B — cross-coordinator ripple.** Focus on D2: enumerate every
  consumer of `guest_gate_armed` / `_guest_gate_armed` /
  `_guest_room_gate_armed` independently. Confirm exit ordering (v5.16.0
  D1) preserved. Confirm HouseState transition validity (GUEST from
  HOME_NIGHT via v5.16.0 D1b) unaffected. Confirm security lockdown
  behaviour under the new arming rule. Verify D3 registry lookup handles
  the reconfigure-without-restart path (`:4685-4692` clears
  `_guest_room_entity_to_name` too).
- **Review C — test authority via per-site source mutation.** For each
  of: D1's clamp line, D1's ceiling operand (must specifically drill
  `camera_unrecognized` substituted for `camera_total_pre_cancel` — the
  rev-1 bug), D2's `guest_armed = guest_room_gate_armed` line, and D3's
  registry-lookup call — mutate the production source to bypass/neuter
  that ONE site and confirm a SPECIFIC named test fails. Global
  monkeypatch does NOT count.

**Pre-deploy snapshot:** capture the before-picture into the
`README_v<version>.md`. Also capture `_guest_room_state` keys pre-fix.

**Live Validation (Review D):** post-restart, verify the after-picture
bullets AND the numeric FAIL threshold above. Write the observed values
back into the README as the `Validated <date>` table.

---

## Files touched (net)

- `custom_components/universal_room_automation/camera_census.py` — D1
  clamp + Step-2 pre-cancel publication + Step-3 enhanced-area
  contributions publication + `__init__` seeding.
- `custom_components/universal_room_automation/sensor.py` — G2 read
  enhanced dict when active; publish the four G2 diagnostics.
- `custom_components/universal_room_automation/domain_coordinators/presence.py`
  — D2, D3.
- `quality/tests/…` — new tests per acceptance criteria (D1 tonight
  arithmetic, D1 repaired-defenses guest preservation, D1 partial-cancel
  guest preservation, D2 composition truth table, D3 registry-based
  resolution).

Estimated net LoC: ~30 production + tests.
