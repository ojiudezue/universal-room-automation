# PLANNING — Census: at-home-resident corroborator for unnamed garage crossings

**Card:** `CENSUS-ATHOME-RESIDENT-CORROBORATOR-1`
**Branch base:** `develop @ 8ecc754e2+`
**Tier:** 2 **elevated to 3 framing-disjoint reviews** (regression-prone — the vouch feeds `person_id` / `identified_count`, which the guest gate and HVAC / Bayesian consumers depend on; standing policy per CLAUDE.md "Tier 2-DB for ALL regression-prone work").
**Scope:** **GARAGE ONLY** (SIMPLIFY verdict). Side/front doors are explicitly non-goals (front-door lift is <2x, measured).
**Status:** awaiting plan review (per CLAUDE.md Plan-Review rule — ONE adversarial plan review before build dispatch for Tier 2+).

---

## 0. Institutional context verified

### 0.1 Prior-art scan — REUSE verdicts (code+plans+analysis)

Every proposed addition is cited REUSED or NEW with file:line on current develop. Re-grepped
tonight; the card's citations are a hypothesis — corrections to its line numbers below.

| Proposed piece | Verdict | Where |
|---|---|---|
| Per-person room location + freshness | REUSE | `PersonCoordinator.data[person]["location"]` + `tracking_status` (ACTIVE/STALE/LOST). STALE handling `person_coordinator.py:608-616`; `STALE_THRESHOLD_SECONDS=60` `const.py:240`. |
| Room-to-room transition stream | REUSE | `TransitionDetector` (`transitions.py:38`), bus listener `_on_location_change` (`:154`), listener API `async_add_listener` (`:150`), DB read `get_recent_transitions(person_id, hours)` (`:675`). Table `room_transitions` with index `idx_transitions_rooms (from_room, to_room, timestamp DESC)` (`database.py:913-928`). |
| Fresh BLE-at-home per area | REUSE | `camera_census._ble_home_by_area` (`camera_census.py:3014`) — **card said `:2809`, drifted; code is at `:3014`**. Already excludes STALE/LOST and non-room sentinels. |
| Door-group ↔ interior-camera map | REUSE but **do not extend** | `CONF_DOOR_GROUPS` (`const.py:2805`), `CONF_DOOR_INTERIOR_NEIGHBOURS` (`const.py:2809`), loaded `transit_validator.py:1113-1128`, consumed `_get_interior_cameras_near` (`:2187`). Camera-side map, not room-side. Per card: "no new door-to-room config map is needed." The door-side **rooms** are a 2-element knob with default (see §4). |
| Egress crossing resolve site (plug-in point) | REUSE | `transit_validator._on_camera_state_change` → `_resolve_direction` → `_resolve_egress_face_identity` (`transit_validator.py:1357`). We vouch **after** `_resolve_egress_face_identity` returns `(None, None, _)` and only when `direction in {entry, exit}`. |
| Bus event + DB column we write to | REUSE | `ura_person_egress_event` + `person_entry_exit_events.person_id` + `confidence REAL` (schema `database.py:793-808` per IDENTITY_FUSION_CAMERAS_MANUAL §4.6). No migration. |
| `person_id` canonicalisation | REUSE | `camera_census._canonical_person_slug` (fire-axe URA-slug namespace). |
| Confidence model | REUSE constants | `CONFIDENCE_MEDIUM = 0.6` (`const.py`, see IDENTITY_FUSION_CAMERAS_MANUAL §5.3). Vouch is a single-leg corroboration → **0.6**. We do NOT invent a new tier. |
| Camera-area lookup | REUSE | `camera_census` `CameraInfo.area_id` + `_build_room_to_area_id_map` (per `_ble_home_by_area` docstring). |

**NEW pieces (minimal):**

| New piece | Rung (Numbers-Get-Knobs ladder) | Why NEW is justified |
|---|---|---|
| `CENSUS_RESIDENT_VOUCH_WINDOW_S` | **Module constant** (`const.py`) | Behavioural number for a tight-coupled correlation window; operator does not need runtime tuning. Default **60 s** (card's measured 60% at ±60 s, 72% at ±120 s — the lift saturates and false-vouch risk grows with the window; keep tight). |
| `CONF_GARAGE_VOUCH_ENABLED` | **Config/options flow** | Operator kill switch, infrequent. Default **ON** (gated by card verdict). Mirrors `egress_identity_enabled` posture (manual §5.4). |
| `CONF_GARAGE_VOUCH_DOOR_SIDE_ROOMS` | **Config/options flow**, string list | Infrequent per-deployment knob. Default (`["garage_a", "kitchen_hallway_garage"]`) — the two rooms the card measured, scoped to door-group `garage_a`. NOT a Number entity; this is a set-once structural knob. |
| `_vouch_resident_at_home` helper on `TransitValidator` | NEW function, ~40 LoC | No existing helper reads TransitionDetector + per-person location simultaneously; this is the plug-in. |

**NOT ADDED (explicit non-goals, pushback-complete):**

- No new DAO. The vouch uses an in-memory ring buffer fed by `TransitionDetector.async_add_listener` (bounded, keyed by door-side rooms). This avoids a per-crossing SQL hit at the egress-resolve seam and matches the card's "REUSE room-to-room infrastructure" instruction. Startup seed uses the existing `get_recent_transitions(person_id, hours=1)` per tracked resident (one-shot).
- No new DB column. `confidence REAL` already carries the advisory score.
- No front-door variant. Measured <2x lift — card parsimony verdict SIMPLIFY applies.
- No learned-door-side-rooms algorithm. Marginal-benefit decomposition (CLAUDE.md): simplest version (2-element knob, default from measurement) captures the entire 60% lift; a learning layer adds state and review surface for no measured gain. **Parked** with the trigger: *if a 2nd install (coming 2026-10 weekend) measures a different door-adjacency pattern, revisit as a learned list.*

### 0.2 Prior planning / audit / memory consulted

- `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` (full read tonight; §4.3 TransitValidator seam, §4.6 schema, §5.2–§5.5 producer / confidence / consumer doctrine).
- `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (sibling; STALE/LOST semantics + BLE fleet-liveness gate).
- `docs/planning/AUDIT_census_subsystem_2026_10_04.md` (R1.3: 143 egress rows / day with ~2× camera-leg inflation; R2.1 producer check; R2.2 consumer check — the real guest-arm path is `_guest_room_gate_armed`, not `_guest_gate_armed` which has been COMPUTED-BUT-NOT-CONSUMED since 2026-08-16).
- `docs/planning/PLANNING_census_inputs_first.md` R2.3 item 4 (Path α/β residual budget: ~3–4 episodes/day).
- `docs/QUALITY_CONTEXT.md` — bug classes relevant to this change: #7 stale data source (STALE/LOST exclusion), #22 enum mismatch (direction values), #23 observation-mode gating, #34 untracked background tasks (listener leak — mirror TransitionDetector's `async_teardown` pattern), #53 computed-but-not-consumed (do NOT add a vouch write that no consumer reads — verify the identified_count path consumes it).
- `docs/reviews/URA_CODE_TRACING_METHODOLOGY.md`, `URA_ARCHITECTURE_MAP.md` (value SCOPE: `person_id` on egress event is HOUSE-scope; crossing is site-local).
- Memory bodies pulled: `reference_egress_face_coverage_7pct_not_a_ceiling` (do NOT re-litigate door-cam face coverage), `feedback_coincidental_equality_masks_concept_split` (vouch confidence 0.6 shares value with Frigate single-leg face — concept split, keep them nominally distinct via `agreement_class`), `feedback_wire_in_anchor_mandatory`, `feedback_hollow_test_anchors`, `project_v5_5_0_inclement_weather_shipped` (listener-leak pattern on teardown), `project_v5_8_0_incident_v5_8_0_setup_recursion` (do not reconcile from the new helper's wire-in path).

### 0.3 Code locations read end-to-end during scoping

- `custom_components/universal_room_automation/transitions.py` — full (:38–:689).
- `custom_components/universal_room_automation/transit_validator.py` :900–:2200 (door-group loader, dedup, direction, egress-resolve seam).
- `custom_components/universal_room_automation/camera_census.py` :3000–:3380 (`_ble_home_by_area`, canonical slug flow, union writer referenced from `_apply_enhanced_house_census`).
- `custom_components/universal_room_automation/database.py` :793–:808 (`person_entry_exit_events`), :913–:928 (`room_transitions`).

### 0.4 Card citations found WRONG on current code

| Card said | Code says | Impact |
|---|---|---|
| `camera_census.py:2809 _ble_home_by_area (+ room->area map :2480)` | `camera_census.py:3014` for `_ble_home_by_area`. Didn't verify `:2480` for the room→area map — the resolver docstring now references `_build_room_to_area_id_map` without a stable line. | Minor drift; use `_ble_home_by_area` by symbol, not line. |
| `camera_census.py:158 CameraInfo.area_id` | Not re-verified; symbol exists. | Low. |
| "transit_validator.py:1113-1128 / _get_interior_cameras_near :2187" | Correct on current develop. | — |

No other citation falsified. The 60%/10%/±60s measurement is accepted as the empirical gate.

---

## 1. Falsifiable invariant (the single property the cycle must guarantee)

**I1 (vouch soundness, falsifiable):**
A `ura_person_egress_event` on a `garage_a`-group egress camera is stamped with `person_id = R`
via the at-home-vouch path **only if** ALL of the following hold at the moment the crossing is
resolved:

1. Face-identity path returned `None` (we never override a real face match).
2. `direction ∈ {entry, exit}` (never on `ambiguous`).
3. `R ∈ PersonCoordinator.data` with `tracking_status ∈ {ACTIVE}` (NOT `STALE`, NOT `LOST`;
   mirrors `_ble_home_by_area` Fix 5a).
4. There exists a `room_transitions` row for `R` with `timestamp` within
   `[egress_timestamp − W, egress_timestamp + W]` where `W = CENSUS_RESIDENT_VOUCH_WINDOW_S` (60 s
   default) **AND** (`from_room ∈ door_side_rooms` OR `to_room ∈ door_side_rooms`).
5. `R`'s current `location` resolves to a room whose `area_id` matches the garage area OR
   neighbouring area (reuses `_ble_home_by_area`'s room→area map — a resident whose phone places
   them in an unrelated room MUST NOT vouch for a garage crossing).
6. `CONF_GARAGE_VOUCH_ENABLED == True` **AND** the existing kill switch
   `switch.ura_name_people_at_doors` is ON (fresh-read, matching egress-identity doctrine
   manual §3 invariant 7).

**I1 breaks ⇒ no stamp.** The stamp is `person_id = canonical_slug(R)`, `confidence = 0.6`,
`agreement_class = "resident_vouch_single_leg"` (new class literal; see §3).

**D (adversarial completeness):** D re-enumerates every path in `TransitValidator` that can
set `person_id` and verifies that only `_resolve_egress_face_identity` and the new
`_vouch_resident_at_home` are producers. D must concretely repro that a crossing on a
non-garage door CANNOT trigger the vouch even if a resident just moved into Garage A
(door-group discriminator is enforced upstream of the vouch call).

### 1.1 Mis-vouch exposure (what the invariant does NOT prevent, and why that is acceptable)

A visitor walking out of Garage A while resident R is also present in Garage A → the crossing
will be stamped `R`. Impact bounds:

- `identified_count` is a SET cardinality (manual §3 invariant 4); double-counting R has no
  effect on `|BLE ∪ face ∪ egress-face|` because R is already in the BLE set.
- `persons_entered_today` / `LastPersonExit` display sensors will carry a wrong name for that
  one row. **Display tier only** (manual §5.5 (b) — no trust decision).
- Guest-mode arming (`_guest_room_gate_armed`, presence.py) is UNCHANGED: it keys off
  guest-room occupancy + no-known-person, which the vouch does not affect.
- Bayesian learning (`__init__.py:2893`) is gated by GUEST state, not by raw `person_id`.

The audit's R1.3 measured ~1 unaccounted garage episode / day; the mis-vouch rate is strictly
smaller (requires simultaneous resident + visitor in the garage, uncommon on this house per
operator). Accepted residual.

### 1.2 Why confidence stays at 0.6 (concept-split protection)

A vouch is a single, non-face corroboration leg. It is INFERIOR evidence to a Frigate named
face (also 0.6 today). We keep the numeric value but distinguish via `agreement_class` so a
future consumer can discriminate — this is deliberate per
`feedback_coincidental_equality_masks_concept_split`: equal numbers hide a concept split, so
the test suite exercises a config in which the vouch class is excluded from a consumer that
accepts face-single-leg.

---

## 2. Producer / Consumer map (CLAUDE.md Producer-AND-Consumer rule)

### 2.1 PRODUCER check (the vouched identity)

Arithmetic — vouched `person_id` is produced iff I1 holds. Dependencies and their health:

| Dependency | Reader | Current health |
|---|---|---|
| `PersonCoordinator.data` populated + fresh | `_vouch_resident_at_home` | HEALTHY (per AUDIT_census_subsystem_2026_10_04 R2.1 — BLE residents 1–3 all day, STALE handling live). |
| `TransitionDetector` producing rows into `room_transitions` | listener subscribed via `async_add_listener` | HEALTHY (362,664 rows since 2026-01-04 per card). |
| Door-group resolver `_resolve_direction` setting `direction = entry/exit` | upstream of vouch | HEALTHY — same path face-identity uses. |
| `switch.ura_name_people_at_doors` state | fresh-read | HEALTHY (manual §3). |

External ground truth: the measurement itself (card: 66/110 vouched at 60% with 6× lift) is
the oracle. Re-measure under the new producer post-deploy (§6 live table).

### 2.2 CONSUMER + call-site check (every reader of `person_id` on an egress event)

| Consumer | file:line | Trust vs Display | Behaviour on vouched row |
|---|---|---|---|
| `PersonsEnteredTodaySensor` | `sensor.py:4268` | Display | Resident name joins today's entries list. ✓ Correct for sound vouch; wrong-name on mis-vouch (bounded, §1.1). |
| `PersonsExitedTodaySensor` | `sensor.py:4386` | Display | Same. |
| `LastPersonEntrySensor` | `sensor.py:4464` | Display | Same. |
| `LastPersonExitSensor` | `sensor.py:4512` | Display | Same. |
| Union writer `_apply_enhanced_house_census` (identified set via egress-face registration) | `camera_census.py` (per audit §2 flowchart `EID → ENH`) | **Trust (count-affecting)** | Vouched `person_id` of a resident ALREADY in the BLE set is a no-op on `identified_count` (set union). Vouched `person_id` of a resident whose BLE went LOST but is actually home → **adds them back** to identified set at confidence 0.6 — DESIRED behaviour per card. |
| Guest-mode arm | `_guest_room_gate_armed` (`presence.py`) | Trust (indirectly) | Does NOT read `person_id`; reads guest-room occupancy + no-known-person. Vouch cannot flip arm/disarm. |
| HVAC guest actuation | `hvac.py:3931-3962` | Trust (gated on GUEST state) | Downstream of guest-mode; vouch cannot escalate HVAC. |

**Safety doctrine check (manual §5.5 (a)):** vouch confidence is 0.6, below the ≥0.9
security-de-escalation floor. The vouch cannot suppress or escalate a security action. ✓
Compliant.

**Bug Class #53 check (computed-but-not-consumed):** `agreement_class = "resident_vouch_single_leg"` IS consumed by the `identified_count` union path (via the existing `EID → ENH` wiring) and by the four display sensors. Not a dangling value.

---

## 3. Deliverables

### D1: Door-group discriminator at the vouch call-site

**What:** In `transit_validator._on_camera_state_change` (or the egress-resolve seam exercised
at :2000), after `_resolve_egress_face_identity` returns `person_id = None`, call
`_vouch_resident_at_home(egress_camera_id, egress_timestamp, direction)` only when the camera
resolves to `door_group == "garage_a"` (reuse `_door_groups` loaded at `:1113-1128`).

**Acceptance Criteria:**
- **Verify:** A crossing on `front_door_aerial` (`door_group ≠ garage_a`) with a fresh resident
  Garage-A transition does NOT get vouched. (Unit test; mutation drill — comment out the
  door-group gate and a specific test MUST fail.)
- **Test:** `test_vouch_only_garage_door_group`.
- **Live:** Post-deploy, inspect `person_entry_exit_events` rows with
  `agreement_class = "resident_vouch_single_leg"` on an egress day: ALL rows have
  `egress_camera` resolving to `garage_a` group.

### D2: `_vouch_resident_at_home` helper

**What:** New TransitValidator method implementing I1 (steps 3–5). Reads:
- `TransitionDetector` recent-transition cache (D3 below) for door-side-room touches in
  `[t−W, t+W]`.
- `PersonCoordinator.data` for `tracking_status == ACTIVE` and `location` → area_id check via
  the existing room→area map.

Returns `(person_id_slug | None, confidence, agreement_class)`. Single-match only — if ≥2
distinct residents satisfy I1 in-window, ABSTAIN (returns `(None, None, "resident_vouch_abstain_multi")`;
mirrors egress-face abstain-on-ambiguity, manual §5.2).

**Acceptance Criteria:**
- **Verify:** Two residents each with a fresh door-side transition → ABSTAIN; no vouch
  stamped.
- **Verify:** One resident fresh, phone STALE/LOST → no vouch (I1 step 3).
- **Verify:** One resident fresh, phone in `master_bedroom` (unrelated area) → no vouch (I1
  step 5).
- **Test:** `test_vouch_abstain_multi_resident`, `test_vouch_rejects_stale_tracking`,
  `test_vouch_rejects_wrong_area`.
- **Live:** Within 48h of deploy, the vouch rate on the garage leg sits in the 50–70% band
  of unnamed garage crossings (sanity vs card's 60%); abstain-multi rate < 5%.

### D3: Transition tail cache (REUSE listener API)

**What:** Register a `TransitionDetector.async_add_listener` callback inside `TransitValidator`
that maintains an in-memory ring buffer:
`dict[room_slug, deque[(person_id, direction, timestamp)]]` keyed by `door_side_rooms`, with a
hard cap on size and a time-based prune (W + 60 s margin). Seed on startup from
`get_recent_transitions(person_id, hours=1)` for every tracked resident (bounded one-shot).

**Acceptance Criteria:**
- **Verify:** No DB read in the egress-resolve hot path (grep: `database.get_transitions` not
  called inside `_vouch_resident_at_home`).
- **Verify:** Listener teardown releases the registration (mirror
  `TransitionDetector.async_teardown` pattern at `transitions.py:107`; Bug Class #34 — add
  explicit `self._unsub_transition_listener = ...` and tear it down in TransitValidator's own
  teardown).
- **Test:** `test_vouch_cache_prunes_outside_window`,
  `test_vouch_listener_torn_down_on_reload` (reload 3x, assert no listener leak via
  `_listeners` count).
- **Live:** `_vouch_cache_size` observability counter stays < 200 entries at steady state.

### D4: Config/options-flow surface

**What:** Two options-flow fields on the integration entry (NOT on each room):
- `CONF_GARAGE_VOUCH_ENABLED` (bool, default `True`).
- `CONF_GARAGE_VOUCH_DOOR_SIDE_ROOMS` (list of room slugs, default
  `["garage_a", "kitchen_hallway_garage"]`).

Plus `CENSUS_RESIDENT_VOUCH_WINDOW_S = 60` as a module constant in `const.py` (safety-ish —
widening the window inflates the mis-vouch rate; keep behind code review).

**Acceptance Criteria:**
- **Verify:** Options flow round-trips both fields; empty list disables vouch
  (equivalent to `CONF_GARAGE_VOUCH_ENABLED == False`).
- **Verify:** Toggling `CONF_GARAGE_VOUCH_ENABLED` to False takes effect on the next crossing
  without reload (fresh-read posture, mirrors manual §3 invariant 7).
- **Test:** `test_options_flow_vouch_round_trip`, `test_vouch_disabled_short_circuits`.
- **Live:** Flip the entity to OFF via the UI; next garage crossing produces no vouched row
  (`agreement_class != "resident_vouch_single_leg"`); flip back ON; next crossing resumes
  vouching.

### D5: Observability sensors

**What:**
- `sensor.ura_vouched_crossings_today` — count of rows with
  `agreement_class = "resident_vouch_single_leg"` in `person_entry_exit_events` today.
- `sensor.ura_vouch_abstain_multi_today` — abstain count (safety signal — too many abstains
  means we need `person_id`-margin logic).

**Acceptance Criteria:**
- **Verify:** Sensors read from the existing DB table (no new table).
- **Test:** `test_vouched_crossings_sensor_counts`.
- **Live:** On a day with a measured ground-truth vouch count (operator-observed garage trip),
  the sensor's value matches ±1.

---

## 4. Knobs — placement ladder

| Knob | Rung | Default | Why that rung |
|---|---|---|---|
| `CENSUS_RESIDENT_VOUCH_WINDOW_S` | Module constant (`const.py`) | 60 s | Widening it is a safety call (mis-vouch rate rises); operator should NOT tune at runtime. |
| `CONF_GARAGE_VOUCH_ENABLED` | Options flow | True | Set-once kill switch per deployment; infrequent, not dashboard-tunable. |
| `CONF_GARAGE_VOUCH_DOOR_SIDE_ROOMS` | Options flow | `[garage_a, kitchen_hallway_garage]` | Per-deployment structural; the "2nd house this weekend" instance will have different slugs. Dropdown-of-known-rooms, not free text. |

No Number entity: none of these are operator-observationally-tunable policy numbers.

---

## 5. Three-reviewer plan (framing-disjoint)

Standing policy — this change is regression-prone (feeds `identified_count` which guest mode
and HVAC reach). Three framings:

- **Reviewer A — correctness + edge cases.** I1 steps 1–6 exhaustively; mis-vouch bound; set
  cardinality invariant; abstain-multi semantics; the four display consumers' NULL handling.
- **Reviewer B — async + lifecycle + race conditions.** Listener teardown (Bug Class #34);
  startup seed race (what if a crossing fires before `TransitionDetector.async_init` returns);
  reload resilience (TransitValidator reload re-registering the listener without leaking);
  cross-coordinator (vouch does not fire during `homeassistant_stop` — reuse the shutdown
  fence check already protecting the census).
- **Reviewer C — test authority + data integrity.** Per-site source mutation (comment out door
  group gate / ABSTAIN clause / STALE exclusion — each MUST produce a specific test failure,
  not a generic suite red). `person_entry_exit_events` shape unchanged (no migration). The
  new `agreement_class` literal is additive on the bus event (consumers that never read it are
  unaffected). D4 options flow round-trip + `restore_entity` posture.

ONE adversarial plan review precedes build dispatch (CLAUDE.md Plan-Review Tier 2+).

---

## 6. Live validation (written back into README after deploy)

Prospective table — overwritten with `Validated <date>` + observed values post-restart.

| Criterion | How observed | Pass if |
|---|---|---|
| Vouch producer live | `SELECT COUNT(*) FROM person_entry_exit_events WHERE agreement_class='resident_vouch_single_leg' AND timestamp >= today;` | ≥1 within 48h on a day with a known resident garage trip. |
| Discriminator holds | Query above with `egress_camera NOT LIKE '%garage_a%'` → 0 rows. | 0 rows. |
| Mis-vouch bound | Operator-observed garage trips vs vouched rows; sampled over 7 days. | Vouched count / (vouched + unnamed) in the 50–70% band; abstain-multi < 5%. |
| Guest-mode unchanged on garage-only trip | `binary_sensor.ura_presence_coordinator_guest_mode` does NOT flip on a solo-resident garage round-trip. | No state change. |
| No listener leak | After 3× `homeassistant.reload_config_entry` on the URA parent, `TransitionDetector._listeners` has the expected steady-state count. | Count stable. |
| Kill switch | Toggle `CONF_GARAGE_VOUCH_ENABLED` OFF; next garage crossing produces no vouched row. | Confirmed. |

---

## 7. Open questions for the operator

1. **Door-side room default.** `["garage_a", "kitchen_hallway_garage"]` is the measurement set.
   Confirm these are the exact URA room slugs on this house (I did NOT re-verify against
   `.storage/core.config_entries` tonight — the card asserts them, and the AUDIT confirms
   garage_a cluster; a 2-minute live-mount read would close this).
2. **2nd-house compatibility (weekend 2026-10-03/04 install, per memory
   `project_single_user_no_backcompat` update).** Should `CONF_GARAGE_VOUCH_ENABLED` default
   to `False` on fresh config entries and require explicit opt-in? Argument for: the 2nd house
   has not been measured, and the vouch is only correct where the door-side rooms are quiet
   (card's "visitor walking through while resident present" caveat). Argument against:
   consistent behaviour across installs.
3. **Mis-vouch rate carrier.** If the operator wants a visible metric before trust grows,
   emit `sensor.ura_vouch_mis_vouch_estimate_today` (count of vouched rows where a different
   resident was ALSO in Garage A within W — proxy for the risky overlap). Low cost, moderate
   information. Build it, or wait?

---

## 8. Non-goals (parsimony)

- Front-door variant (measured <2× lift — card REFUTED-AS-USEFUL).
- Learned door-side-room algorithm (parked with revival trigger: 2nd install's measurement).
- New Number entity on the dashboard for W (code-review-only tuning per rung).
- Any change to `_resolve_egress_face_identity` or to the face producer (manual §5.2 is
  canonical and recently BUILT; do not touch).
- Any change to the guest-mode gate wiring (`_guest_gate_armed` remains dormant — out of
  scope).

## 8. Orchestrator addendum (overnight 2026-10-12) — Q1 answered, and a plan defect

- **Q1 ANSWERED from the live mount** (`.storage/core.config_entries`): the URA room entries are titled `Garage A` and
  `Kitchen Hallway Garage` (also present: `Garage Hallway`, `Garage B`).
- **PLAN DEFECT (fix before build):** `room_transitions.to_room` stores the **display names**
  (`SELECT DISTINCT to_room ... LIKE '%arage%'` since 10-01 → `Garage A`, `Kitchen Hallway Garage`, `Garage B`), NOT the
  slugs `garage_a` / `kitchen_hallway_garage` that §7 Q1 proposes as the default. A slug default compared against
  `room_transitions` / TransitionDetector rows would never match, and the vouch would silently never fire (a hollow
  feature that still passes slug-keyed unit tests). The plan must pick ONE key space: either store room-entry
  identifiers (entry_id or a canonical slug) and normalise both sides through one helper, or compare display names.
  Add a test fixture built from real `room_transitions` values, not hand-typed slugs.
- Not yet plan-reviewed (Tier 2 requires one adversarial plan review before build). Also flag for the review: §3 lists
  "a live kill switch", but the knob section says "no Number entity". Reconcile these.
