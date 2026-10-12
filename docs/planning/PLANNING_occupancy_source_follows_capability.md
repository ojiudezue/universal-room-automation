# PLANNING — Fan-noise rejection follows SENSOR CAPABILITY, not the CONF list that produced the source tag

**Card:** OCCUPANCY-SOURCE-FOLLOWS-CAPABILITY-1 (`kanban.data.yaml:30888`). Tier 2. **Plan review required before build.**
**Status:** Rev 2 (2026-10-12). Docs only, no code.
**MANDATORY READS (completed by this planner, Rev 2 pass):** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` end-to-end (incl. §10 corrections ledger items 1–9, Addendum 2026-10-11 on D2 reachability + ZV fan susceptibility + Study A ZK, §Gold patterns index); `docs/architecture/SENSOR_FLEET_CLASSES.md` end-to-end (Rules 1–4, ZV susceptibility table, Meross MS600 dual-homed note, ESPHome LD2410 note, UNVERIFIED `meross_lan` value==2 semantics); `docs/planning/PLANNING_fan_noise_running_rejection.md` v5.103.51. All read completely before this revision. Nothing in the PRESENCE §10 ledger is re-asserted.

---

## 1. Problem (restated after Rev-1 plan review)

Multiple fan-noise and provenance mechanisms are **list-keyed** today — they treat "entity is filed under `CONF_MMWAVE_SENSORS` / `presence_sensors`" as a proxy for "entity is radar-bearing". These are **separate consumer sites**, and Rev 1 found only four of them; the Rev 1 plan review surfaced **two more** (presence-side provenance + D2 flap latch) and corrected the per-tick identity used by the recheck ring. The complete list, verified on `develop`:

**String-keyed consumers of `occupancy_source == "mmwave"` (trust decisions):**

- **D2 sustain demotion** — `coordinator.py:4179` requires `str(data.get(STATE_OCCUPANCY_SOURCE, "")) == "mmwave"`.
- **Fan-recheck eligibility N-tick history** — `presence_fan_recheck.py:520` requires every entry in the `recent_occupancy_sources` ring to be `"mmwave"`.
- **`_still_armed_eligible` live-tick** — `presence_fan_recheck.py:1005` requires the live tick's `occupancy_source == "mmwave"`.
- **Recheck VACATED defensive gate** — `presence_fan_recheck.py:800-802`: `not presence_now and current_source != "mmwave"` ⇒ VACATED. Both clauses are **list-keyed** (`presence_now` from `data["presence_detected"]`, which is produced by `mmwave_sensors` only at `coordinator.py:3479-3482`; `current_source` is a producer label).

**List-keyed consumers via presence provenance (new in Rev 2 — Finding 1):**

- **Presence-side fan-interference provenance gate** — `presence.py:3997-4001` requires `mmwave_on and not motion_on and not occupancy_on` on `_room_provenance[room]`, where the provenance kind comes from `_classify_entity_kind` (`presence.py:352-391`) — a **pure CONF-list lookup**. An entity in `CONF_OCCUPANCY_SENSORS` is classified `"occupancy"`, so the gate rejects it regardless of hardware. This feeds `_compute_fan_interference_rooms` (`presence.py:4356`) → `_compute_mmwave_fan_demoted_rooms` → `is_room_mmwave_fan_demoted(room)` (`presence.py:4415`), which D2 reads at `coordinator.py:4204-4209`. **Consequence:** even if we fix `coordinator.py:4179` to pass under capability, D2 still does not demote in rooms whose radar is filed under `occupancy_sensors` — because `is_room_mmwave_fan_demoted` returns False. The Rev 1 "no census/presence consumer" statement was wrong: the presence side keys on TIER1 kind labels, not on the `"mmwave"` string, so a string grep could not find it. (Bug Class #53 — one missed site invalidates the ship.)

**List-keyed D2 flap latch (new in Rev 2 — Finding 5):**

- **D2 flap latch clear + suppression** — `_evaluate_mmwave_demoted_latch` clears on `not presence_detected` (`coordinator.py:2878-2879`); the latch's suppression predicate at `coordinator.py:3590-3597` is `presence_detected and not motion_detected and not occupancy_detected`. For a radar filed in `occupancy_sensors`, `presence_detected` goes False the next tick and the latch clears → occupancy recreates → re-demotes → oscillation. The latch exists precisely to stop this oscillation; without routing, we lose it.

**Recheck window family factor (new in Rev 2 — Finding 6):**

- **`_room_families`** at `presence_fan_recheck.py:1140-1158` reads only `CONF_MMWAVE_SENSORS` to pick the per-family window factor (ZK/ZX = 1.5, LD2410 = 1.0, etc). An occupancy-list MS600 room gets factor 1.0 (default) instead of 1.5, a shorter window, and so more false VACATEDs.

**Dormant list-keyed sites (NOT in scope):**

- **Fan-transition CREATION gate** — `coordinator.py:3655-3657` uses `presence_detected and not motion_detected and not occupancy_detected`. **Dormant** today (C5 Rev 2 shipped `FAN_TRANSITION_SUSPECT_WINDOW_S = 0.0`). Fixing routes dead code; carded as `FAN-TRANSITION-GATE-FOLLOWS-CAPABILITY-1` (follow-up, Tier 1) — fire only if a future cycle un-retires the window.

**Pre-existing adjacent leak observed by Rev-2 review (Finding 8), NOT in scope of this card:**

- `coordinator.py:3831-3837` stamps `_last_pir_motion_time` on ANY `motion_detected` tick — including the Meross MS600 motion-bit (radar-derived). That stamp refreshes PIR-only staleness, so a fan-faked bit holds D2 off even after this card ships. **Separate card:** `D2-PIR-STAMP-FOLLOWS-FAN-IMMUNE-WITNESS-1` (Tier 1). Not folded in because: (a) it is a different predicate (motion-bit stamp vs occupancy-source gate), (b) it would widen this cycle's blast radius into the motion-timeout machinery, (c) it is trivially card-sized on its own. We flag it; we do not ship it here.

**The underlying concept split** (Bug Class #63, feedback memory `coincidental_equality_masks_concept_split`): the label `"mmwave"` names the CONF LIST a tick's trigger entity was filed under. It is coincidentally equal to "the device is radar-bearing" only when **every radar in the house is filed in `presence_sensors`**. Combined-sensor devices (Matter MS600, ESPHome LD2410 variants, future Zigbee combined radars) legitimately live in `occupancy_sensors`, and the equality breaks.

**v5.103.51 shipped the primitives this plan needs** — `sensor_capability.is_fan_immune_witness`, `FAMILY_BY_MODEL_ID`, `family_for_model`, `RADAR_SENSOR_FAMILIES`, `fan_veto.resolve_sensor_family` (per-boot `hass.data` cache). **No new primitive. No new CONF field.** This card routes those producers down into the six consumer sites named above.

---

## 2. Institutional context verified — prior-art audit

Operator directive 2026-10-11: *"context-wide prior-art audit FIRST (code + plans + memory); REUSE > EXTEND > BUILD only if nothing fits."*

### 2a. Code surfaces grepped (file:line, verified against `develop` 2026-10-12)

| Area | File:line | Finding |
|---|---|---|
| `occupancy_source` producer sites | `coordinator.py:3832 (motion), 3839 (mmwave), 3841 (occupancy_sensor), 3858 (timeout), 3869/3873 (none), 3909 (camera), 4083 (ble), 4344 (grace_hold), 4593 (failsafe), 5027/5033 (override), 5513 (fan_recheck_release)` | 10 distinct writers. Only ONE sets `"mmwave"` (3839); it is PURELY a function of `presence_detected` (produced only by `mmwave_sensors` at `:3479-3482`). Other writers unaffected by this card. |
| `occupancy_source` STRING consumers (trust) | `coordinator.py:4179` (D2 gate), `presence_fan_recheck.py:520, 802, 1005` | 4 trust-decision sites. Also: `binary_sensor.py:458` reads `== "timeout"` (display reader — unchanged, label semantics preserved). |
| `occupancy_source` STRING consumers (display / DB) | `binary_sensor.py:444-491` (`occupancy_source` attribute surfaced to Lovelace); `coordinator.py:5305-5310` (`database.log_occupancy_event(entry_id, "entry", trigger=occupancy_source)`); `coordinator.py:5117` (activity log). | **D5 Rev-2 correction:** the string IS persisted via `log_occupancy_event.trigger`. This card does NOT change which string the producer writes, so DB/activity rows remain byte-identical label-wise. D5 AC restated accordingly. |
| `_recent_occupancy_sources` ring | `coordinator.py:316, 545 (init maxlen 10), 5470 (single tail append), 5496-5498 (public read)` | Read ONLY by recheck (`presence_fan_recheck.py:516, 795`). `_last_occupancy_source` is a separate scalar used by BLE→motion re-entry logic. |
| **Presence-side provenance gate (NEW in Rev 2)** | `presence.py:3997-4001` (predicate); `presence.py:4356` (`_compute_fan_interference_rooms`); `presence.py:4415` (`is_room_mmwave_fan_demoted`); classifier `presence.py:352-391` (`_classify_entity_kind` — pure CONF-list lookup). D2 consumes it at `coordinator.py:4204-4209`. | Capability-driven, not list-driven, with **override honoured**: the plan does NOT loosen `_classify_entity_kind` (that function is also the seed-vs-live classifier for OTHER consumers, B-HIGH-1 invariant). Instead, we add a per-room **capability-radar-on** boolean to provenance alongside the kind labels — the gate at `:3997-4001` reads the new boolean; the kind-label classifier is unchanged. See §5 D1b. |
| **D2 flap latch (NEW in Rev 2)** | `coordinator.py:2878-2879` (clear on `not presence_detected`); `coordinator.py:3590-3597` (suppression predicate `presence_detected and not motion and not occupancy`). | Routed through the same per-tick `radar_sole` boolean (§5 D1) so an occupancy-list radar does not oscillate the latch. |
| **Recheck window family factor (NEW in Rev 2)** | `presence_fan_recheck.py:1140-1158` `_room_families` reads only `CONF_MMWAVE_SENSORS`. | Extended to walk **all radar-bearing sensors** across all three lists via `fan_veto.resolve_sensor_family` + `RADAR_SENSOR_FAMILIES`. See §5 D4. |
| `presence_detected` producer | `coordinator.py:3479-3483` | Still reads `mmwave_sensors` only — intentionally, as a producer-label axis. The VACATED gate stops relying on `presence_detected` as a trust axis (see F2). |
| Capability primitives (REUSE) | `sensor_capability.py:349-370 is_fan_immune_witness`, `:385-405 FAMILY_BY_MODEL_ID`, `:408-412 RADAR_SENSOR_FAMILIES`, `:434-448 family_for_model`; `fan_veto.py:79-109 resolve_sensor_family` | All present on `develop`. No new primitive. |
| Operator override surface (REUSE) | `const.py:559 CONF_SENSOR_CAPABILITIES`; validator `sensor_capability.py:247+ validate_capabilities_payload`; D-MEDIUM-1 rule `_NON_CORROBORATOR_KINDS` at `sensor_capability.py:60-69`. | Rev-2 confirms: validator rejects motion-wired→{mmwave, occupancy} (`:306-313`). An entity filed in `CONF_OCCUPANCY_SENSORS` CAN carry `kind: mmwave` override (allowed). An entity in `CONF_MOTION_SENSORS` cannot — this card does NOT loosen D-MEDIUM-1. **However** (Rev 2 Finding 4, Q5): the override only changes `derive_capability` — `presence_detected` and `_classify_entity_kind` ignore it. This card routes the override through at the capability predicate; overrides win over family (both ways: `kind: pir` override declassifies a family-radar; `kind: mmwave` override promotes an occupancy-list entity). |
| Chatter / stuck / substrate | `chatter_detector.py`, `coordinator.py:1947,3155`, `occupancy_substrate.py:79-84` | Independent of `occupancy_source`. Out of scope. |

**Full grep for `"mmwave"` string consumers:** 4 trust sites + binary_sensor display + log_occupancy_event (producer-path label). No HVAC / zone / house / census / egress / perimeter / person_coordinator / camera_census / memory_writer trust consumer. Verified 2026-10-12.

### 2b. Plans / audits / catalogs consulted (unchanged from Rev 1)

| Doc | Relevance |
|---|---|
| `PLANNING_fan_noise_running_rejection.md` v5.103.51 | Introduces the capability + model primitives this plan threads down. §D row "C2 recheck eligibility" explicitly deferred the capability routing to this card. |
| `AUDIT_motion_sensors_live_models.md` 2026-10-11 | Living fixture, both houses. Rev-2 §7 live-impact table re-derived against it. |
| `PLANNING_sensor_capability_vs_role.md` | Gold pattern. "ANY classification question about a sensor" → capability layer, never regex. |
| `PLANNING_fan_recheck_d2_deadlock_fix.md` + `PLANNING_fan_noise_mode2_ble_pause_recheck.md` | `recent_occupancy_sources` ring origin + semantics (history check, not point check). Preserved. |
| `PLANNING_occupancy_substrate_unification.md` + `AUDIT_occupancy_substrate_consumer_ripple.md` | Substrate kind labels are an independent axis. No ripple into substrate. |
| `AUDIT_mmwave_only_rooms_2026-07-31.md` Finding 6 | "Classify by capability, not by list." |
| `docs/articles/mmwave_fans_transition_gate.md` + `alignment_probe_results.md` | **Not re-cited** — PRESENCE §10.1 correction stands. |

### 2c. Memory bodies pulled

- `feedback_context_wide_scoping.md` — now informs the Rev-2 consumer enumeration **including the presence-side provenance gate** and the **D2 flap latch** (Rev-1 missed both because they do not reference `"mmwave"` as a string).
- `feedback_tier2plus_prior_art_scan.md` — the discipline this §2 implements.
- `feedback_config_first_before_code.md` — "move to presence_sensors" workaround not sufficient as the ONLY answer (silent-gap on new installs; D-MEDIUM-1 blocks motion→mmwave override).
- `feedback_extend_existing_never_rebuild.md` — REUSE verdict table §2d.
- `feedback_coincidental_equality_masks_concept_split.md` — the label equality is the concept split, Bug Class #63.
- `reference_code_tracing_methodology.md` — producer→entry/exit→consumers→cross-cycle walk.
- `project_single_user_no_backcompat.md` — URA rolling to additional homes; configuration-first assumptions break on install #N.
- **(Rev 2 new)** PRESENCE §10 item 8 — `CONF_MMWAVE_SENSORS == "presence_sensors"` the live key. Code says.
- **(Rev 2 new)** PRESENCE Addendum 2026-10-11 — ZV fan susceptibility, Study A ZK operator ruling, D2 reachability name-regex root cause (fixed by v5.103.51 C2).

### 2d. REUSE-or-BUILD verdict per piece (Rev 2)

| Piece | Verdict | Gold pattern reused | File:line |
|---|---|---|---|
| **Per-tick `radar_sole` boolean** (producer, same-tick-consistent — replaces Rev-1's sticky `_last_trigger_entity` approach) | **BUILD (small)** — computed at the same site as `any_sensor_active` (around `coordinator.py:3524`) as the set-expression `bool(on_set) and all(is_radar(e) for e in on_set)`. Written into `data[STATE_RADAR_SOLE_TICK]` on each tick. | mirrors `any_sensor_active` + mmwave-sole computation at `:3524 / :3590-3597` | new sibling var at same site |
| `is_radar(e)` predicate | **BUILD (small)** — ~15-line helper on coordinator. **Positive-evidence only** (F4): True iff (override `kind == mmwave`) OR (no override AND (CONF-list kind == mmwave OR `resolve_sensor_family(hass, e) in RADAR_SENSOR_FAMILIES`)). Override wins over family **both ways**: a `kind: pir` / `kind: bed` / `kind: occupancy` override declassifies a family-radar entity. Unknown-kind, bed, PIR, and unconfigured entities return **False**. | capability layer + model safety net | — |
| `_recent_radar_sole_ring: collections.deque[bool]` on coordinator | **BUILD (small)** — parallel to `_recent_occupancy_sources`, same maxlen, same single tail append at `coordinator.py:5470`. Each entry is the `radar_sole` boolean for that tick. Rings a **boolean per tick**, not an entity id (F2). | mirror of `_recent_occupancy_sources` | — |
| Presence-provenance "capability-radar-on" flag | **BUILD (small)** — new boolean on `_room_provenance[room_name]["radar_capable_on"]`. Written in `_update_room_provenance` (presence.py — the same site that stamps `mmwave/motion/occupancy`); computed as `any(is_radar(e) for e in on_entities_this_tick)`. `_classify_entity_kind` is NOT changed (preserves the B-HIGH-1 invariant). The gate at `presence.py:3997-4001` reads the new boolean instead of the kind-label-sole predicate. | sensor-capability + override-aware | — |
| Rewrite D2 gate at `coordinator.py:4179` | **REWRITE** — replace the `"mmwave"` string arm with `data.get(STATE_RADAR_SOLE_TICK, False)`. **No OR-arm with the old string** (clarified vs Rev 1 — Finding 10d). The kill-switch flips the whole path (§6). | — | — |
| Rewrite recheck eligibility N-tick history | **REWRITE** `presence_fan_recheck.py:508-521` to call `room_coord.recent_radar_sole_ring()[-ticks_required:]` and require all True. | mirror of recent_occupancy_sources read | — |
| Rewrite `_still_armed_eligible` live-tick | **REWRITE** `presence_fan_recheck.py:1005` to read `data.get(STATE_RADAR_SOLE_TICK, False)`. | — | — |
| Rewrite VACATED defensive gate | **REWRITE** `presence_fan_recheck.py:800-802`: replace `not presence_now and current_source != "mmwave"` with **"no radar-bearing entity is currently on"** — i.e. `not any(is_radar(e) and self._is_sensor_on(e) for e in all_lists)`. This is **live on-set**, not `_last_trigger_entity` and not `presence_detected` (F2). Expose as `room_coord.any_radar_bearing_on_now() -> bool`. | — | new coordinator read |
| Rewrite D2 flap latch clear + suppression | **REWRITE** `coordinator.py:2878-2879` and `:3590-3597` to clear / suppress on `radar_sole` for the tick, so an occupancy-list radar does not oscillate the latch. | — | — |
| Extend recheck window family factor | **EXTEND** `presence_fan_recheck.py:1148` `_room_families` to walk **all radar-bearing sensors** across `CONF_MMWAVE_SENSORS + CONF_MOTION_SENSORS + CONF_OCCUPANCY_SENSORS`, filtering by `is_radar(e)`. | capability + resolver | — |
| Dashboard `occupancy_source` attribute | **NO CHANGE** — the producer label-of-list stays. Dashboards unaffected. | `binary_sensor.py:444-491` | — |
| `database.log_occupancy_event` trigger | **NO CHANGE** — the trigger string remains the producer label (list semantics; useful for analytics asking "which CONF-list fired entry?"). Byte-identical label values. **D5 AC restated as label-value stability**, not "no persistence". | `coordinator.py:5305-5310` | — |
| Fan-transition CREATION gate (`coordinator.py:3655-3657`) | **DEFER** — dormant (window = 0.0). Follow-up card. | — | — |
| `_last_pir_motion_time` MS600-motion-bit refresh (`coordinator.py:3831-3837`) | **DEFER** — separate card `D2-PIR-STAMP-FOLLOWS-FAN-IMMUNE-WITNESS-1` (Tier 1). Different predicate; different blast radius. | — | — |
| New CONF field | **NONE.** | — | — |
| New sensor / entity | **NONE.** | — | — |
| **Kill switch** (Rev 2 new) | **BUILD (rung-1 module constant)** `OCCUPANCY_SOURCE_CAPABILITY_ROUTING_ENABLED` in a central place (candidate: `coordinator.py` module-top or `sensor_capability.py` next to `_FAN_IMMUNE_WITNESS_KINDS`). Default `True`. When False, every consumer falls back to the pre-cycle `"mmwave"` string gate — byte-identical old behaviour. The `hasattr` "staged deploy" fallback is removed (reviewer finding: both rings co-created in one atomic ship). | module-constant knob-ladder rung 1 | — |

Verdict: ZERO new primitives, ZERO new CONF fields, ZERO new entities. One kill-switch constant + one new per-tick data key + one new ring + one new coordinator read + one new presence provenance key + six consumer rewrites. All driven by two existing primitives (`is_fan_immune_witness` / override + `resolve_sensor_family` + `RADAR_SENSOR_FAMILIES`).

---

## 3. Producer AND Consumer check (operator-mandated 2026-08-16) — Rev 2

**Producer** of the new `radar_sole` boolean:
- Site: `coordinator.py` around `:3524` (where `any_sensor_active` is computed).
- Arithmetic: let `on_set = { e | e ∈ mmwave_sensors ∪ motion_sensors ∪ occupancy_sensors AND self._is_sensor_on(e) AND e passes fusion filter }`. Then `radar_sole = bool(on_set) AND all(is_radar(e) for e in on_set)`.
- Dependencies: (a) three CONF lists (always present), (b) `_is_sensor_on` (healthy), (c) fusion filter (healthy), (d) `is_radar` ← override OR CONF-list kind OR device-registry family. Dependency health: all healthy; family resolution per-boot cached in `fan_veto.resolve_sensor_family`.
- **Discriminating property vs the old string:** sole-source is intrinsic — a tick with ZK on AND ZV on evaluates `radar_sole = False` even though `occupancy_source == "mmwave"` would be True (because `presence_detected` fires regardless of co-firing motion). This is the Rev-2 Finding-3 case; the test fixture is explicit.

**Consumers** (trust-decision vs display vs persistence) — Rev 2 complete table:

| Consumer | File:line | Decision kind | Correct source under this card |
|---|---|---|---|
| D2 sustain demotion string gate | `coordinator.py:4179` | TRUST (gate) | `data[STATE_RADAR_SOLE_TICK]` |
| Presence-side fan-interference provenance gate (NEW consumer identified Rev 2) | `presence.py:3997-4001` | TRUST (gate feeding D2) | `prov["radar_capable_on"] and not motion_on and not occupancy_on` → simplified to `prov["radar_sole_capable"]` written by provenance updater |
| D2 flap latch clear + suppression (NEW consumer identified Rev 2) | `coordinator.py:2878-2879, 3590-3597` | TRUST (oscillation guard) | `data[STATE_RADAR_SOLE_TICK]` |
| Fan-recheck eligibility N-tick history | `presence_fan_recheck.py:520` | TRUST (gate) | `room_coord.recent_radar_sole_ring()` |
| `_still_armed_eligible` live-tick | `presence_fan_recheck.py:1005` | TRUST (gate) | `data[STATE_RADAR_SOLE_TICK]` |
| Recheck VACATED defensive gate | `presence_fan_recheck.py:800-802` | TRUST (gate) | `not room_coord.any_radar_bearing_on_now()` — live on-set, not `_last_trigger_entity`, not `presence_detected` |
| Recheck window family factor | `presence_fan_recheck.py:1140-1158` | TUNING (window length) | iterate all three CONF lists, filter by `is_radar` |
| `binary_sensor.<room>_occupied` `occupancy_source` attribute | `binary_sensor.py:491` | DISPLAY | LIST LABEL (unchanged) |
| `binary_sensor.py:458` timeout_at reader | `binary_sensor.py:458` | DISPLAY (reads `== "timeout"`) | unchanged |
| `database.log_occupancy_event(trigger=…)` | `coordinator.py:5305` | PERSISTENCE (label) | LIST LABEL (byte-identical) |
| Activity log | `coordinator.py:5117` | PERSISTENCE (label) | LIST LABEL (byte-identical) |
| `_recent_occupancy_sources` ring | `coordinator.py:5470, 5496` | INTERNAL (feeds eligibility history today) | **Preserved** as LIST LABEL for backwards compat / future label-based analytics; the recheck now reads `_recent_radar_sole_ring` instead. |
| `_last_occupancy_source` BLE→motion re-entry | `coordinator.py:316, 5075-5180, 5305` | INTERNAL (unrelated to fan rejection) | LIST LABEL (unchanged) |

**Discriminating ACs (operator rule — must distinguish fix from a plausible different failure):** see §5 D-ACs, every "Live" bullet names an entity+attribute+expected value under the fix AND under a plausible miss. E.g. Guest Bedroom 2 revert test: under fix, D2 reaches sustain demotion AND the latch does not oscillate (two independent observables); under a half-fix (coordinator.py:4179 rewritten but presence.py:3997-4001 missed), D2 still skips because `is_room_mmwave_fan_demoted` returns False.

---

## 4. Falsifiable invariant (Rev 2 restatement)

**Invariant (restated per Finding 11):** the **radar-sourced input** to each fan-noise trust gate (D2 sustain demotion gate at `coordinator.py:4179`, presence-side fan-interference provenance at `presence.py:3997-4001`, D2 flap latch clear + suppression, recheck eligibility N-tick history, `_still_armed_eligible` live-tick, recheck VACATED defensive gate) is a **pure function of the capability of the SET of Tier-1 entities on this tick** — invariant under moving any entity between CONF lists, honouring operator overrides (override wins over family both ways), and classifying unknown/occupancy-kind/bed/PIR entities as NOT radar. The other gates on each site (debounce, boot-settle, house-state, staleness, FAN_TRUST_STATES, flap-quarantine, manual-ON hold) continue to apply unchanged.

**Falsifying tests (every consumer site + the invariant itself):**
- Per-site mutation anchor (Tier-3 framing C discipline, applied here even for a Tier 2): neuter each consumer's `radar_sole` read to the pre-cycle `occupancy_source == "mmwave"` arm; a SPECIFIC named test fails per site. The six anchors are named in §5.
- **Filing-permutation invariant test:** fix the set of entities on this tick (e.g. {MS600 Matter occupancy}); run the predicate under three filings (MS600 in `presence_sensors` / `motion_sensors` / `occupancy_sensors`); the verdict must be **identical** across all three. Test: `test_filing_permutation_same_on_set_same_verdict`. (Finding 11.)
- **Sole-source discriminator (Finding 3):** fix the on-set to {MS600 (occupancy list), ZV (motion list)}; the predicate must return `radar_sole = False` because ZV is not radar. Test: `test_combined_sensor_plus_zv_not_radar_sole`.
- **Override-both-ways:** `kind: pir` override on a family-radar entity → `is_radar = False`; `kind: mmwave` override on an occupancy-list entity (allowed under D-MEDIUM-1) → `is_radar = True`. Tests: `test_pir_override_declassifies_family_radar`, `test_mmwave_override_promotes_occupancy_entity`.
- **Negative evidence:** every entity in {ZV, PIR, bed presence, 3rd-Reality night-light occupancy, unconfigured/unknown} → `is_radar = False`. Test: `test_bed_sensor_not_radar_sole` — this is the Master Bedroom regression guard Rev-2 Finding 4 named (bed-occupancy-while-fan-on must NOT trigger a recheck pause).

---

## 5. Deliverables (Rev 2)

Build only after plan review (incorporating Rev-2 Must-fix list below). Tier 2 → one adversarial plan review, then build, then two framing-disjoint code reviews (A = correctness + edge cases + override/positive-evidence; B = async / lifecycle + presence-side provenance alignment + latch oscillation + boot order) plus live validation.

### D1 — Producer: per-tick `radar_sole` boolean + ring (replaces Rev-1 D1)

- **D1a `is_radar(e)` helper** on `UniversalRoomCoordinator`:
  - `room_config = {**self.entry.data, **(self.entry.options or {})}`.
  - Override wins first: if `CONF_SENSOR_CAPABILITIES` for `e` declares `kind` → `kind == "mmwave"` ⇒ True; `kind in {"pir", "motion", "bed", "occupancy", "camera_presence", "ble_presence", "pir_split"}` ⇒ False; unrecognised override ⇒ fall through to family.
  - No override: CONF-list kind (via `derive_capability`): kind `"mmwave"` ⇒ True; else fall through to family.
  - Family: `fan_veto.resolve_sensor_family(hass, e) in RADAR_SENSOR_FAMILIES` ⇒ True.
  - Default (unknown kind, no family): **False** (positive-evidence only).
  - Exception during resolution: **False** (fail-closed).
- **D1b `radar_sole` per tick** at the producer site (around `coordinator.py:3524`, same place that computes `any_sensor_active`): `on_set = { e ∈ all three CONF lists | self._is_sensor_on(e) AND passes fusion filter }`; `radar_sole = bool(on_set) and all(self.is_radar(e) for e in on_set)`. Stamped into `data[STATE_RADAR_SOLE_TICK]` (new STATE_* in `const.py`, module-level string key).
- **D1c `_recent_radar_sole_ring: collections.deque[bool]`** on coordinator, maxlen 10, co-created with `_recent_occupancy_sources` at `coordinator.py:545`. **Single tail append** at `coordinator.py:5470`, same statement — the Rev-2 reviewer's ring-lifecycle note: builder must confirm there are NO early-return paths between the compute site and the append site that would skip one ring but not the other. Test: `test_rings_same_length_always`.
- **D1d public reads:** `recent_radar_sole_ring() -> list[bool]`; `any_radar_bearing_on_now() -> bool` (live on-set, same math as D1b but without the "all" quantifier).
- **D1e presence-side provenance key:** in presence.py's `_update_room_provenance` (same site that stamps `mmwave/motion/occupancy`), stamp an additional per-room key `radar_sole_capable = bool(on_set) and all(is_radar(e) for e in on_set)` using the same `is_radar` helper (import from coordinator, or lift to `sensor_capability` module — builder choice; prefer the latter for test authority). `_classify_entity_kind` is NOT changed.

#### D1 AC
- **Verify (code):** `is_radar` exists and consults override → CONF kind → family in that order with positive-evidence default False. Mutation: force `is_radar` to return `derive_capability(...).kind != "pir"` reds `test_bed_sensor_not_radar_sole` AND `test_pir_override_declassifies_family_radar`.
- **Verify (code):** `data[STATE_RADAR_SOLE_TICK]` is written on EVERY tick (not only `any_sensor_active`). Mutation: moving write inside `if any_sensor_active:` reds `test_radar_sole_written_every_tick`.
- **Verify (ring lifecycle):** both rings have equal length at all times post-boot. Mutation: skip one append reds `test_rings_same_length_always`.
- **Tests:**
  - `test_combined_sensor_only_tick_radar_sole_true` — MS600 Matter occupancy in `occupancy_sensors` firing alone → True (family lookup).
  - `test_zk_only_tick_radar_sole_true` — ZK in presence_sensors alone → True (CONF-list kind).
  - `test_combined_sensor_plus_zv_not_radar_sole` (Finding 3) — MS600 + ZV both on → False.
  - `test_bed_sensor_not_radar_sole` (Finding 4) — Master Bedroom bed presence firing → False.
  - `test_pir_override_declassifies_family_radar` (Finding 4) — a family-radar entity with `kind: pir` override → False.
  - `test_mmwave_override_promotes_occupancy_entity` — occupancy-list entity with `kind: mmwave` override → True.
  - `test_filing_permutation_same_on_set_same_verdict` (Finding 11) — same on-set, three different CONF-list filings → identical verdict.
  - `test_is_radar_fail_closed_on_exception`.
  - `test_rings_same_length_always`.
- **Live:** no behaviour change observable from D1 alone; the predicate is exposed, not yet consumed.

### D2 — Rewrite D2 sustain demotion gate + flap latch (coordinator.py)

- `coordinator.py:4179` — replace `and str(data.get(STATE_OCCUPANCY_SOURCE, "")) == "mmwave"` with `and data.get(STATE_RADAR_SOLE_TICK, False)`. **No OR-arm with the old string** (Rev-1 Finding 10d resolved: the kill switch in §6 is the only backwards-compat path).
- `coordinator.py:2878-2879` (latch clear) — replace `if not presence_detected: reason = "mmwave_off"` with `if not data.get(STATE_RADAR_SOLE_TICK, False): reason = "radar_absent"` (new reason label — operator-visible).
- `coordinator.py:3590-3597` (latch suppression predicate) — replace `mmwave_sole_here = presence_detected and not motion_detected and not occupancy_detected` with `mmwave_sole_here = data.get(STATE_RADAR_SOLE_TICK, False)`.

#### D2 AC
- **Verify (code):** three sites rewritten; literal `"mmwave"` string gone from all three. Mutation per site:
  - Neuter 4179 to the string → `test_d2_fires_on_combined_sensor_only_tick` reds.
  - Neuter 2878-2879 to the string → `test_latch_does_not_oscillate_in_occupancy_list_radar_room` reds.
  - Neuter 3590-3597 to the string → `test_latch_suppresses_on_capability_radar_sole` reds.
- **Verify (behavior):** with a radar entity filed under `occupancy_sensors` AND the presence-side gate also routed (D3), D2 reaches sustain demotion AND the latch does not oscillate across ticks (count of latch clear→set→clear within 60 s = 0).

### D3 — Presence-side provenance gate (coordinator-adjacent — the Finding-1 fix)

- `presence.py:3997-4001` — replace `if not (mmwave_on and not motion_on and not occupancy_on): continue` with `if not prov.get("radar_sole_capable", False): continue`.
- Producer side: in `_update_room_provenance` (presence.py — the method that writes `_room_provenance[room]["mmwave"] = ...`), additionally stamp `_room_provenance[room]["radar_sole_capable"] = bool(on_entities_this_tick) and all(is_radar(e) for e in on_entities_this_tick)`. Reuse the capability helper via module-level import; prefer lifting `is_radar` to `sensor_capability.py` for test authority.
- `_classify_entity_kind` (`presence.py:352-391`) **NOT changed** — preserves B-HIGH-1 seed-vs-live invariant for all other consumers of TIER1 kinds.

#### D3 AC
- **Verify (code):** the gate at `presence.py:4001` consults the new boolean; the kind-label-sole predicate is retired here. Mutation: revert to `mmwave_on and not motion_on and not occupancy_on` reds `test_fan_interference_rooms_includes_occupancy_list_radar`.
- **Verify (code):** `is_room_mmwave_fan_demoted(room)` returns True in a legal fixture where the room's only radar is filed under `occupancy_sensors` and all other D2 preconditions hold. Mutation anchor: `test_is_room_mmwave_fan_demoted_covers_occupancy_list_radar`.

### D4 — Rewrite recheck eligibility (three sites) + VACATED defensive gate + family factor

- `presence_fan_recheck.py:520` — read `room_coord.recent_radar_sole_ring()[-ticks_required:]`; require all True. On short ring (`len < ticks_required`): **veto with `"capability_bootstrap"`** (Rev-2 Q3 answer: fail-closed, no `hasattr` fallback — both rings co-created atomically).
- `presence_fan_recheck.py:1005` — read `data.get(STATE_RADAR_SOLE_TICK, False)`.
- `presence_fan_recheck.py:800-802` — replace `not presence_now and current_source != "mmwave"` with `not room_coord.any_radar_bearing_on_now()`. **Important:** this reads the LIVE on-set, not the ring and not `_last_trigger_entity` (Rev-2 Finding 2 — a stale entity would strand ZK rooms in paused state).
- `presence_fan_recheck.py:1140-1158` `_room_families` — walk `set(CONF_MMWAVE_SENSORS + CONF_MOTION_SENSORS + CONF_OCCUPANCY_SENSORS)`, filter by `self._room_coord.is_radar(e)`, dedupe families.

#### D4 AC
- **Verify (code):** three literal `"mmwave"` occurrences removed; three predicate consultations added; VACATED gate reads live on-set.
- **Verify (bootstrap):** on cold boot before ring fills, recheck eligibility vetoes `"capability_bootstrap"` (NOT falls back to the string gate). Mutation: `hasattr(room_coord, "recent_radar_sole_ring")` fallback reds `test_recheck_vetoes_capability_bootstrap_pre_warmup`.
- **Tests:**
  - `test_recheck_arms_on_combined_sensor_only_history`.
  - `test_recheck_still_vetoes_on_motion_mixed_history` — one non-radar entry in ring → vetoed `not_radar_sole`.
  - `test_still_armed_eligible_combined_sensor_live_tick`.
  - `test_vacated_defensive_gate_reads_live_on_set` (Finding 2) — ZK room where radar has gone off, recheck sees no radar on → VACATED. Then with ZK still on but occupancy_source == "timeout" → NOT vacated (regression guard for ZK rooms covered today).
  - `test_vacated_defensive_gate_occupancy_list_radar_still_firing_not_vacated`.
  - `test_room_families_covers_radar_in_occupancy_sensors` (Finding 6) — MS600-only Media room gets factor 1.5, not 1.0.

- **Live (DISCRIMINATING — Finding 7 fix):** recheck arm count on **GB1 / GB2 / Media** rises from 0 to non-zero within 1 week on ticks where only MS600 entities are on. **BLE-present-vacate guard** (fan-recheck Rev 2 Guard A metric) does NOT rise vs the 2026-10-04→10-11 baseline replay — this discriminates "fix" from "wrong vacates".

### D5 — Dashboard + persistence preservation (NO CODE CHANGE in label writers)

- `binary_sensor.py:444-491` `occupancy_source` attribute writer: byte-identical post-cycle (git diff empty on the writer).
- `binary_sensor.py:458` reads `== "timeout"`: label unchanged, unaffected.
- `coordinator.py:5305-5310` `log_occupancy_event(trigger=occupancy_source)`: byte-identical label values (DB row label stability).
- `coordinator.py:5117` activity log: byte-identical.

#### D5 AC (Rev 2 restatement per Finding 9)
- **Verify (code):** git diff on `binary_sensor.py` display writer and on `log_occupancy_event` call is empty. Mutation: changing the attribute to the capability result reds `test_occupancy_source_attribute_preserves_list_label`.
- **Verify (DB):** `database.occupancy_event.trigger` label distribution over the first 24 h post-ship is within ±5 % per label vs the 24 h pre-ship baseline, per room — label values stable, not "zero persistence". Query: `SELECT trigger, COUNT(*) FROM occupancy_event WHERE event_type='entry' AND created_at BETWEEN … GROUP BY trigger` for pre and post windows.

### D6 — Kill switch + knob ladder (Rev 2 new deliverable)

- **D6a** module constant `OCCUPANCY_SOURCE_CAPABILITY_ROUTING_ENABLED` (default `True`), placed next to `_FAN_IMMUNE_WITNESS_KINDS` in `sensor_capability.py` (rung 1 — module constant, review-only to change).
- **D6b** When False, every consumer site falls back to the pre-cycle `"mmwave"` string gate. Byte-identical old behaviour; CI test asserts this by diffing a mocked recheck under both toggle values with the same inputs where the only radar is filed in `presence_sensors`.
- **Rationale:** Rev-2 Finding 4 showed the predicate now actuates fan pauses in rooms that were inert before (Media, Master Bedroom). An operator-override "same day" failsafe does not hold (overrides route through capability only in the new code path). A rung-1 kill switch is the proportional containment. No CM-entry switch (parsimony).

#### D6 AC
- `test_kill_switch_disables_capability_routing_all_six_sites` — toggle to False, every consumer reads the string gate; identical verdict to pre-cycle master in a known fixture.
- **Live:** operator can flip the constant and reload via code change; if post-ship a bad classification surfaces, the operator can additionally declare a per-entity `CONF_SENSOR_CAPABILITIES` override — rung 3, same day.

### D7 — SENSOR_FLEET_CLASSES.md + PRESENCE §10 + Gold Patterns update (same commit as code)

- SENSOR_FLEET_CLASSES.md footer: replace the "Gap:" paragraph with the "Resolved" paragraph; note that filing MS600 in `occupancy_sensors` is now safe for fan rejection; GB2 revert is an **organic follow-up** (Rev-2 Q4 answer — NO-GO at ship, see §11), not a ship-time change.
- PRESENCE §10 corrections ledger — add item 10: *"`occupancy_source == "mmwave"` is sufficient to detect a radar-sourced tick."* **FALSE (vX.Y.Z).** The string names the CONF list, not the device capability. Trust decisions read `data[STATE_RADAR_SOLE_TICK]` (coordinator) and `prov["radar_sole_capable"]` (presence).*
- PRESENCE §Gold patterns index — add row: *"Capability-radar-sole boolean | `coordinator.py` producer + `_recent_radar_sole_ring` + `presence.py` provenance stamp | Any trust-decision that must distinguish 'a radar is the sole tick driver' from 'a radar-list entity fired' — never use the `occupancy_source` string for this."*

---

## 6. Knob ladder (Numbers Get Knobs) — Rev 2

| Value | Rung | Where | Rationale |
|---|---|---|---|
| `OCCUPANCY_SOURCE_CAPABILITY_ROUTING_ENABLED` | **1 (module constant, default True)** | `sensor_capability.py` | **Kill switch** (Rev-2 Must-fix). False restores byte-identical pre-cycle string gates at all 6 sites. Reviewed-only change to flip; no runtime UI (parsimony). |
| `_FAN_IMMUNE_WITNESS_KINDS` | 1 | `sensor_capability.py:349` | Reviewed-only. |
| `FAMILY_BY_MODEL_ID` / `RADAR_SENSOR_FAMILIES` | 1 | `sensor_capability.py:385, 408` | Reviewed-only; empirical device-model map. |
| Per-entity capability override | 3 (operator-settable, live) | `CONF_SENSOR_CAPABILITIES` options flow | Already live. The override wins over family both ways in D1a; operator can declassify a false-positive family hit (e.g. a one-off radar firmware we misclassify) OR promote an occupancy-list entity. |
| Capability-bootstrap veto reason | 1 (literal string) | `presence_fan_recheck.py` | Operator-visible reason in recheck logs; renaming is a code change by design. |

---

## 7. Live impact enumeration — Rev 2 (CORRECTED per Finding 7)

Source: `AUDIT_motion_sensors_live_models.md` 2026-10-11, both-house registry audit. Read-only.

**Reality check (Finding 7 correction):** no live room currently has a radar filed in `occupancy_sensors`. GB2's MS600 Matter occupancy was moved to `presence_sensors` on 2026-10-11 — so the "D2 fires on radar-in-occupancy" live AC in Rev 1 was **vacuous at ship**. The real live win today is on the **recheck**, not on D2:

**GB1 / GB2 / Media motion bits are in `motion_sensors`.** On any tick where the MS600 motion bit is on alongside the Matter occupancy, pre-cycle `occupancy_source == "motion"` (motion wins at `coordinator.py:3831`), so the recheck N-tick history gets `"motion"` → eligibility vetoed. **Recheck is largely blind in GB1 / GB2 / Media today.** Post-cycle: `radar_sole = True` on those ticks (both entities are radar-bearing per family lookup), so recheck arms.

Entities / rooms impacted (verified 2026-10-11):

| Room | Entity | List | Family | Pre-cycle recheck behaviour | Post-cycle |
|---|---|---|---|---|---|
| Guest Bedroom 1 | Matter MS600 occupancy + meross_lan `…_sensor_presence_motion` | presence_sensors + motion_sensors | generic_radar + generic_radar | Recheck blind (motion-bit tags tick as `"motion"`) | **Recheck arms on radar-sole ticks** |
| Guest Bedroom 2 | same (post-2026-10-11 move) | presence_sensors + motion_sensors | generic_radar + generic_radar | Same as GB1 | Same — arms |
| Media | same (motion bit is Media's ONLY motion sensor) | presence_sensors + motion_sensors | generic_radar + generic_radar | Recheck completely blind (every tick stamps `"motion"`) | **Recheck arms when combined-sensor-sole** |
| Study A / Jaya / Ziri / Exercise / Living Room / Kitchen / Master Bedroom | ZK/ZX in presence_sensors + ZV in motion_sensors | mixed | zigbee_zk / zigbee_zx / zigbee_zv | ZK/ZX-only tick: `occupancy_source == "mmwave"` → recheck eligible as today. | **No change** (ZK/ZX-sole → radar_sole = True); ZK+ZV co-firing was already not radar-sole under the old gate (presence vs motion), remains not-radar-sole under the new. |
| Master Bedroom (bed-only tick) | ZG-204 bed sensors in `occupancy_sensors` | occupancy_sensors | zigbee_bed / unknown | Not radar-sourced; recheck does not arm. | **No change** (bed sensor returns False from `is_radar` — Finding 4 guard). |
| 3rd-Reality night-light occupancy (Powder, Staircase, Master Closet) | occupancy_sensors | unknown (not radar family, no override) | Not radar-sourced. | **No change** — unknown-kind, no family hit → False. |
| ANY future room whose combined radar occupancy lands in `occupancy_sensors` | — | occupancy_sensors | generic_radar / zigbee_zk / zigbee_zx / etc | Silently invisible to fan rejection. | **Covered**, no operator action. |

**D2 live impact:** vacuous at ship (no live room has a radar-only in `occupancy_sensors` AND lacks a PIR, which is the D2 fail-closed path separately gated by `_d2_motion_sensors_present`). The GB2 revert (D7 doc note) is the discriminating test — see §11 Q4. Deferred to organic follow-up, gated on live validation.

**D2 flap latch impact:** no live oscillation to measure today (no radar-in-occupancy room). The latch rewrite is a **correctness guard** against a future install, verified in-suite only. In-suite oracle: `test_latch_does_not_oscillate_in_occupancy_list_radar_room`.

**Discriminating live ACs (Rev 2 restatement):**
- Media recheck arm count on radar-sole-only ticks > 0 within 1 week (where "radar-sole-only" = MS600 Matter occupancy AND/OR motion bit on, nothing else).
- GB1 / GB2 recheck arm count on radar-sole-only ticks > 0 within 1 week.
- **Counter-check:** BLE-present-vacate count ≤ baseline (fan-recheck Rev 2 Guard A metric) — guards against "wrong vacates".
- Master Bedroom bed-occupancy ticks DO NOT trigger a recheck pause (Finding 4 regression guard): count of recheck arms during bed-only on-set over 1 week = 0.
- Dashboard `occupancy_source` attribute still displays list-label values on sampled rooms (GB1, Living Room, Media): verify entity attribute `== "motion"` / `"mmwave"` / `"occupancy_sensor"` as before.

---

## 8. Non-goals (Rev 2)

- **No change to the dashboard `occupancy_source` attribute** (`binary_sensor.py:444-491`). List labels remain.
- **No change to `log_occupancy_event.trigger` label values** — list semantics (`coordinator.py:5305-5310`).
- **No change to the fan-transition CREATION gate** (`coordinator.py:3655-3657`). Dormant; carded as `FAN-TRANSITION-GATE-FOLLOWS-CAPABILITY-1` (Tier 1 follow-up).
- **No change to `_last_pir_motion_time` stamp** (`coordinator.py:3831-3837`). Finding-8 motion-bit stamp refresh is a separate card `D2-PIR-STAMP-FOLLOWS-FAN-IMMUNE-WITNESS-1` (Tier 1). Trivially in scope was considered and rejected (different predicate, different machinery, widens blast radius).
- **No change to `_classify_entity_kind`** (`presence.py:352-391`). B-HIGH-1 seed-vs-live invariant preserved; the capability routing happens via a new sibling boolean on provenance.
- **No new CONF field.** `CONF_SENSOR_CAPABILITIES` covers operator overrides.
- **No change to `_NON_CORROBORATOR_KINDS` / `validate_capabilities_payload` D-MEDIUM-1 rule.** Motion-wired → mmwave override remains rejected.
- **No change to `occupancy_substrate` kind precedence.**
- **No DB migration.** Row LABEL semantics preserved; see D5 AC.
- **No change to BLE / camera / failsafe / override / timeout / fan_recheck_release / grace_hold label producer paths.**
- **No change to chatter detector / stuck-sensor machinery.**
- **No change to any HVAC / zone / house / census / egress / perimeter consumer** — grep confirms none consume `occupancy_source` or `_room_provenance.radar_sole_capable` for trust decisions outside D2 / recheck.
- **No GB2 revert at ship.** Operator may revert as an organic follow-up (§11 Q4).

---

## 9. Rejected options (Rev 2)

1. **"Just move every radar-bearing combined sensor to `presence_sensors`."** Rejected — see Rev 1 §9.1. (Operator vigilance per install; D-MEDIUM-1 blocks motion-wired overrides; silently invisible failure mode on new installs.)
2. **"Change the `occupancy_source == 'mmwave'` producer to also fire for radar-bearing entities in other lists."** Rejected — collapses LIST-LABEL semantics (used by dashboards + log + ring + BLE→motion re-entry) into capability semantics; breaks display + DB + three unrelated internal consumers. The concept split (§2c, Bug Class #63) IS the lesson.
3. **"Introduce a new label `occupancy_source == 'radar'`."** Rejected — forces reader migration across binary_sensor + tests + dashboards + per-room analytics tooling, zero marginal benefit over the predicate helper.
4. **"Inline `is_fan_immune_witness` at each site."** Rejected — duplicates helper + fallback across six files; the centralised predicate + per-tick boolean is byte-cheaper to mutation-test.
5. **"Add a new per-tick `data['tick_radar_sourced']` written by the producer."** **ACCEPTED in Rev 2** — this IS the design (Rev-2 Finding 2). The Rev-1 rejection reasoning ("adds persistent per-tick state") was wrong: `data` is already a per-tick dict and already carries dozens of keys; the predicate is naturally same-tick-consistent only when stamped at the producer. Rev 1's `_last_trigger_entity` approach was the wrong design because the field is a sticky rising-edge latch cleared nowhere.
6. **"Loosen D-MEDIUM-1 so motion→mmwave overrides are accepted."** Rejected — breaks the invariant protecting D2 from an operator unknowingly making a motion-wired entity invisible. Orthogonal.
7. **"Delete `_recent_occupancy_sources` and use only `_recent_radar_sole_ring`."** Rejected — the ring is also useful for future label-based analytics; deletion is a cross-cutting ripple out of scope. We ADD the new ring alongside.
8. **(Rev 2 new)** **"Also change `_classify_entity_kind` to be capability-aware."** Rejected — that classifier is the SINGLE source for seed-vs-live classification across the presence module (B-HIGH-1). Threading capability through it risks a wider invariant violation. The sibling-boolean approach on `_room_provenance` is the proportional fix.
9. **(Rev 2 new)** **"Fold the Finding-8 `_last_pir_motion_time` motion-bit refresh into this card."** Rejected — different predicate (motion-bit vs occupancy-source), different code path, different blast radius. Separate card `D2-PIR-STAMP-FOLLOWS-FAN-IMMUNE-WITNESS-1` (Tier 1). Will cite this card as the sibling.
10. **(Rev 2 new)** **"Keep an OR-arm on the `"mmwave"` string at `coordinator.py:4179` as backwards-compat."** Rejected — the kill switch (D6) is the proper backwards-compat path; OR-arms at six sites would be confusing and would mask a bad kill-switch default.
11. **(Rev 2 new)** **"Use `_last_trigger_entity` as the per-tick identity for the ring and VACATED gate."** Rejected (replaces Rev-1 D1) — `_last_trigger_entity` is set only on rising edges (`coordinator.py:3499-3521`) and never cleared (`:612` init only); after the radar clears it still names the stale entity. Would unreach VACATED in every ZK/ZX room today AND would miscount the ring on `"ble"` / `"timeout"` / `"camera"` ticks. The per-tick boolean at the producer site is the only same-tick-consistent design.

---

## 10. Review protocol (Rev 2)

Tier 2:
1. **Plan review (adversarial, Tier 2 standard) — second pass REQUIRED.** The first pass (2026-10-12, this document) ran against Rev 1 and found CRITICAL × 2, HIGH × 3, MEDIUM × 4, LOW × 2. Rev 2 fixes every finding (table in §12). A second plan review verifies, with greps:
   - All six consumer sites named in §1 are covered by one of the deliverables D1–D6.
   - The `is_radar` predicate is positive-evidence only (Finding 4); unknown/occupancy-kind/bed/PIR entities return False.
   - Override wins over family both ways (Finding 4).
   - VACATED gate reads live on-set, not `_last_trigger_entity`, not `presence_detected` (Finding 2).
   - `_classify_entity_kind` is NOT modified (B-HIGH-1 preserved).
   - Kill switch exists (Finding 4 containment).
   - Live ACs discriminate (Finding 7): Media / GB1 / GB2 recheck arm count rising on radar-sole-only ticks; BLE-present-vacate guard not rising; Master Bedroom bed-only ticks do NOT arm recheck.
   - D5 ACs are label-stability, not "no DB persistence" (Finding 9).
2. **Build.**
3. **Code reviews (2 framing-disjoint).** A = correctness + edge cases + override/positive-evidence + sole-source semantics + ring lifecycle (per-tick alignment, no early-return skip). B = async / lifecycle + presence-side provenance alignment + latch oscillation + boot-order fallback (fail-closed `capability_bootstrap`) + cross-mechanism interaction (debounce, FAN_TRUST_STATES, flap-quarantine).
4. **Live validation (3rd pass):** per §7 discriminating ACs.
5. **README post-deploy write-back:** PASS/FAIL table citing entity_id + attribute + DB row evidence.

---

## 11. Open questions — answered in Rev 2 (per plan-review §Open questions answered)

1. **Motion bit (Q1).** Classify as radar via family lookup (correct). **D2 win: NO** — Finding 8 shows `_last_pir_motion_time` is refreshed on any motion-bit tick, so PIR-staleness never trips. **Recheck win: YES** — GB1 / GB2 / Media (Finding 7). The §7 "D2 can now demote on an MS600 motion-bit tick" Rev-1 claim is withdrawn and replaced with the recheck framing.
2. **Kill switch (Q2).** YES — rung-1 module constant `OCCUPANCY_SOURCE_CAPABILITY_ROUTING_ENABLED`, default True. No CM-entry switch (parsimony). D6.
3. **Boot fallback direction (Q3).** FAIL CLOSED for the recheck — veto `capability_bootstrap`. The Rev-1 `hasattr`-fallback "staged deploy" story was wrong: both rings are co-created atomically in one coordinator `__init__`. D2 predicate False is already fail-closed; the latch clears to the same reason.
4. **GB2 revert (Q4).** **NO-GO at ship** — under Rev 1 the revert would have lost GB2 coverage (Findings 1, 2, 5). Under Rev 2 the revert IS the discriminating live test for D2 + flap latch + presence provenance. **Organic follow-up only**, gated on live validation after the ship confirms the recheck-arm-count ACs. Not shipped in the same cycle.
5. **`occupancy→mmwave` override legality (Q5).** Confirmed legal — `validate_capabilities_payload` rejects only motion-wired → {mmwave, occupancy}. **However**, before this card the override only changed `derive_capability`; `presence_detected` and `_classify_entity_kind` ignored it. Rev 2 routes the override through the capability predicate (D1a), honouring it at all six consumer sites. Overrides win over family both ways.

---

## 12. Rev-2 changelog (what changed from Rev 1 — Plan review 2026-10-12 findings → disposition)

| Finding | Severity | Disposition in Rev 2 |
|---|---|---|
| 1. Missing presence-side provenance consumer (`presence.py:3997-4001` + `_classify_entity_kind` seed) | CRITICAL | **FIXED** — new deliverable D3; §1 lists the gate as a trust consumer; §2a code-surface table includes `presence.py:352-391` + `:3997-4001` + `:4356` + `:4415`; `_classify_entity_kind` NOT changed (preserves B-HIGH-1); new provenance key `radar_sole_capable` added at `_update_room_provenance`. |
| 2. `_last_trigger_entity` wrong per-tick identity; VACATED substitution regresses ZK/ZX rooms | CRITICAL | **FIXED** — Rev-1 D1 design abandoned. D1 Rev 2 computes `radar_sole` per tick at the producer (around `coordinator.py:3524`) as `bool(on_set) and all(is_radar(e) for e in on_set)`; rings a BOOLEAN not an entity id; VACATED gate reads live on-set via `any_radar_bearing_on_now()`. Rejected option 5 is now the accepted design (§9.5). |
| 3. Sole-source semantics violated | HIGH | **FIXED** — `all(is_radar(e) for e in on_set)` quantifier enforces sole-source. Test: `test_combined_sensor_plus_zv_not_radar_sole`. |
| 4. `NOT is_fan_immune_witness` classifies bed/PIR/unknown as radar; override-vs-family precedence wrong | HIGH | **FIXED** — D1a is **positive-evidence only** (override → CONF kind → family). Override wins over family both ways. Default False. Tests: `test_bed_sensor_not_radar_sole`, `test_pir_override_declassifies_family_radar`, `test_mmwave_override_promotes_occupancy_entity`. Master Bedroom regression guard explicitly named. |
| 5. D2 flap latch missed (`coordinator.py:2878-2879, 3586-3597`) | HIGH | **FIXED** — D2 Rev 2 rewrites both the latch clear and the suppression predicate to read `data[STATE_RADAR_SOLE_TICK]`. |
| 6. `_room_families` list-keyed (`presence_fan_recheck.py:1140-1158`) | MEDIUM | **FIXED** — D4 extends `_room_families` to walk all three lists filtered by `is_radar`. Test: `test_room_families_covers_radar_in_occupancy_sensors`. |
| 7. §7 live impact wrong (GB1 / GB2 / Media motion-bit recheck blindness) | MEDIUM | **FIXED** — §7 rewritten. The live win is the recheck arming in GB1 / GB2 / Media on radar-sole ticks today, not a vacuous D2 fire; D2 and latch rewrites are correctness guards verified in-suite. Discriminating live ACs restated. |
| 8. MS600 motion-bit refreshes `_last_pir_motion_time` (pre-existing leak) | MEDIUM | **ACKNOWLEDGED, out of scope** — carded as `D2-PIR-STAMP-FOLLOWS-FAN-IMMUNE-WITNESS-1` (Tier 1 follow-up). §1 Problem explicitly notes it; §8 Non-goals explicitly excludes it; §9.9 explains why not folded in. |
| 9. D5 "no DB persistence" false (`log_occupancy_event.trigger`) | MEDIUM | **FIXED** — D5 AC restated as "label values byte-identical", with a specific SQL query and ±5% tolerance per label; `binary_sensor.py:458` added as a second display reader. |
| 10a. `data["_last_trigger_entity"]` doesn't exist | LOW | **FIXED** — the sticky-entity design is dropped; the per-tick boolean key `STATE_RADAR_SOLE_TICK` IS defined. |
| 10b. GB2 live declaration claim | LOW | **FIXED** — §2a now says live GB2 has `sensor_capabilities = None`; cited lines are config_flow code paths, not live config. |
| 10c. `_recent_occupancy_sources` reader claim | LOW | **FIXED** — §2a / §3 corrected to say the ring is read ONLY by recheck; `_last_occupancy_source` is a separate scalar used by BLE→motion re-entry. |
| 10d. OR-arm at `coordinator.py:4179` vs replace | LOW | **FIXED** — Rev 2 replaces (no OR-arm). The kill switch (D6) is the backwards-compat path. §9.10 explains. |
| 11. Invariant overstated | LOW | **FIXED** — §4 restates: "radar-sourced INPUT to each gate is a pure function…" preserving the other gates; filing-permutation test named (`test_filing_permutation_same_on_set_same_verdict`). |
| Ring lifecycle Q3 | — | **ANSWERED** — both rings co-created, single tail append, no early-return skip. Test: `test_rings_same_length_always`. Fail-closed on short ring. |
| Q1–Q5 | — | **ANSWERED** — §11. |
| Kill switch | Must-fix | **FIXED** — D6, rung-1 module constant. |

**Other Rev-2 changes to the document:**
- Status line → Rev 2 (2026-10-12).
- Mandatory reads line expanded with the Rev-2 pass of both canonical docs.
- §1 Problem fully rewritten with the complete list of six consumer sites + two deferred sibling cards.
- §2a code-surface table rewritten (new rows for presence provenance, D2 flap latch, recheck family factor, DB persistence; corrected override-interaction note).
- §2d REUSE-or-BUILD table rewritten for the per-tick boolean design.
- §3 Producer/Consumer map rewritten to include all six trust sites + display + persistence + both rings.
- §4 falsifiable invariant restated; filing-permutation test and sole-source discriminator added.
- §5 Deliverables fully re-architected: D1 producer boolean + presence provenance stamp; D2 three-site coordinator rewrite; D3 presence-side gate; D4 four-site recheck rewrite with fail-closed bootstrap and live on-set VACATED; D5 label-stability ACs; D6 kill switch; D7 doc updates.
- §6 Knob ladder adds the kill switch at rung 1.
- §7 live impact fully rewritten per Finding 7, with discriminating ACs.
- §8 Non-goals extended (motion-bit stamp, `_classify_entity_kind`, OR-arm, GB2 revert).
- §9 Rejected options extended (items 8, 9, 10, 11; item 5 now ACCEPTED as the design).
- §10 Review protocol notes second plan review required.
- §11 Open questions answered.
- §12 (this changelog) added.

---

**End of plan Rev 2.** Awaiting second Tier-2 adversarial plan review per `CLAUDE.md` → "Plan Review — TIERED" → Tier 2 — before build dispatch.

---

## Plan review 2026-10-12 (preserved from Rev 1 for audit trail)

[Rev-1 plan-review findings retained unchanged below — do NOT edit; §12 above records disposition.]

**Reviewer:** ura-reviewer, Tier 2 adversarial plan pass, read-only. **Mandatory reads done completely:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`. Every finding below was checked against `develop` source (file:line) and the live `.storage/core.config_entries` (read-only). Nothing in the PRESENCE §10 ledger is re-asserted.

**Verdict: PLAN-FIX-REQUIRED.** The direction is right: trust decisions should follow capability, not the CONF list. The mechanism is wrong in four places. The D2 rewrite cannot work while the presence-side gate stays list-keyed. `_last_trigger_entity` is a sticky rising-edge latch, not a record of what fired this tick. The proposed predicate classifies every occupancy-list sensor (beds, PIRs) as radar. And the VACATED substitution breaks the recheck in rooms that are covered today.

### Findings

1. **CRITICAL: the D2 rewrite at `coordinator.py:4179` alone cannot make D2 fire for a radar in `occupancy_sensors`. A list-keyed consumer was missed.** D2 only demotes when `presence.is_room_mmwave_fan_demoted(room)` is true (`coordinator.py:4204-4209`, `presence.py:4415`). That reads a snapshot from `_compute_mmwave_fan_demoted_rooms` → `_compute_fan_interference_rooms` (`presence.py:4356`), which requires provenance `mmwave and not motion and not occupancy` (`presence.py:3997-4001`). Provenance kind comes from `_classify_entity_kind` (`presence.py:352-391`), which is a pure CONF-list lookup: an entity in `occupancy_sensors` is classified `"occupancy"`. Repro: put the GB2 Matter MS600 back in `occupancy_sensors`, run the fan, keep BLE absent and PIR stale. The new gate at 4179 passes, but `demoted=False`, so D2 never fires. D2 AC and the live AC ("0 → non-zero") cannot pass. The plan's statement "No census/presence consumer" is wrong because presence keys on TIER1 kind labels, not on the `"mmwave"` string, so a string grep can't find it. **Fix:** add `_compute_fan_interference_rooms` condition 2 (and the provenance kind it reads) to scope, routed through the same capability predicate. Or state explicitly that radar-in-occupancy D2 is out of scope and drop D2's ACs. (Bug Class #53.)

2. **CRITICAL: `_last_trigger_entity` is the wrong per-tick identity, and the VACATED substitution regresses rooms covered today.** It is set only on rising edges (`coordinator.py:3499-3513`; the occupancy branch sets it only when motion and presence are both off, at 3518). It is never cleared (`:612` init only). After a pause clears the radar, `occupancy_source` goes to `"timeout"` but `_last_trigger_entity` still names the ZK. The proposed `not _is_tick_radar_sourced(data)` at `presence_fan_recheck.py:802` then evaluates False, so **VACATED becomes unreachable in every ZK/ZX room that works today.** That turns the recheck into a periodic fan-pause that never releases. The ring has the same flaw: a `"ble"`/`"timeout"`/`"camera"` tick would be ringed with a stale radar entity and count toward eligibility. **Fix:** at the producer (where `any_sensor_active` is computed, around `coordinator.py:3524`), compute the set of currently-on, fusion-filtered entities across all three lists. Define `radar_sole = bool(on_set) and all(is_radar(e) for e in on_set)` and stamp it into `data` for this tick. Ring that boolean, not an entity id. Rejected option 5 (§9) is in fact the correct design, because the value must be same-tick-consistent and `_last_trigger_entity` cannot be. The VACATED leg must also replace `presence_detected` (mmwave list only, `:801`) with "no radar-bearing entity on now". Otherwise an occupancy-list radar still firing after the pause reads as vacated.

3. **HIGH: sole-source semantics are violated (the question in your brief).** With a stale or most-recent trigger entity, a tick with ZV/PIR on plus a radar on can be classed radar-sourced. Example: ZV already on, ZK rises → `_last_trigger_entity = ZK` while `occupancy_source = "motion"`. The string gate rejects that today; the plan's predicate accepts it at the 1005 and ring sites. A combined sensor plus a ZV both on must count as **not** radar-only. Finding 2's `all(...)` over the on-set enforces this. Add a test: MS600 (occupancy list) and ZV both on → recheck vetoes `not_radar_sourced`.

4. **HIGH: the predicate arm `NOT is_fan_immune_witness` classifies every occupancy-list entity, and every unconfigured or empty entity, as radar.** `_FAN_IMMUNE_WITNESS_KINDS` (`sensor_capability.py:349-357`) excludes `occupancy`, and `derive_capability` returns None for unknown ids, so `not` yields True. Live repro, Master Bedroom: `occupancy_sensors = [bed_presence_…_bed_occupied_left_slow, …right_slow]`, no overrides. Bed occupied with the fan on in HOME_DAY/EVENING (the FAN_TRUST_STATES sleep veto doesn't apply) passes the "radar-sourced" check. The recheck then pauses the fan on a person lying in bed, every cooldown. The same applies to `pir_zigbee_upguesthallway_occupancy` and the 3rd-Reality night-light occupancy entities (Powder, Staircase, Master Closet). **Fix:** `is_radar(e) = (override kind == mmwave) or (no override and (conf-list kind == mmwave or resolve_sensor_family(e) in RADAR_SENSOR_FAMILIES))`. Positive evidence only, with the override taking precedence over family. Also fix the plan's statement that the operator can correct a misclassification with an override "same day": as drafted, the family arm is OR'd in after the override, so a `kind: pir` override cannot declassify a family-radar entity.

5. **HIGH: a fifth list-keyed trust site is missing: the D2 flap latch.** `_evaluate_mmwave_demoted_latch` clears on `not presence_detected` (`coordinator.py:2878-2879`). The latch's suppression predicate is `presence_detected and not motion and not occupancy` (`coordinator.py:3586-3592`). For an occupancy-list radar the latch clears on the very next tick, and occupancy recreates and re-demotes. That is the oscillation the latch exists to stop. Route both through `radar_sole` (finding 2), or keep the D2 scope at mmwave-list only.

6. **MEDIUM: the recheck window family factor is list-keyed** (`presence_fan_recheck.py:1140-1158`, `_room_families` reads only `CONF_MMWAVE_SENSORS`). An occupancy-list MS600 room gets factor 1.0 instead of 1.5, a shorter window, and so more false VACATEDs. Add it to D3 or declare it a non-goal explicitly.

7. **MEDIUM: §7 live-impact table is wrong for GB1, GB2 and Media.** Live `motion_sensors` contain the meross_lan `…_sensor_presence_motion` bit: GB2 alongside a ZV, GB1 alongside a ZV, **Media with the bit as its only motion sensor**. The radar fires both its Matter occupancy (presence list) and its motion bit (motion list), so `occupancy_source` reads `"motion"` whenever the bit is on. The recheck is therefore largely blind in these three rooms **today**. The real live win of a correct capability predicate is that the bit is counted as radar, and the combined tick becomes radar-sole. That is "no change (preserved)" in the plan, which is wrong. Conversely, no live room currently has a radar in `occupancy_sensors`, so the D2/D3 live ACs as written are vacuous at ship. **Fix:** rewrite §7 and make the live AC for the recheck "Media/GB1 recheck arm count > 0 on ticks where only MS600 entities are on" (discriminating), with the BLE-present-vacate guard as the counter-check.

8. **MEDIUM (Q4, MS600 motion bit): the family arm does classify it** (`ms600` token → `generic_radar`, `sensor_capability.py:427-448`). That is right whether the bit means motion or presence, because it is radar-derived and fan-fakeable. The §7 claim "D2 can now demote on an MS600 motion-bit tick" is **false**, though. Any `motion_detected` tick stamps `_last_pir_motion_time` (`coordinator.py:3831-3837`), so `pir_stale` stays False, and provenance `motion=True` blocks the presence-side suspect. That stamp also points to a **pre-existing leak** v5.103.51 didn't close: the radar motion bit refreshes the "PIR-only" staleness clock, so in GB1/GB2 a fan-faked bit holds D2 off. Stamp `_last_pir_motion_time` only when a fan-immune witness (`is_fan_immune_motion_witness`) is on, or card it. The UNVERIFIED value==2 semantics in SENSOR_FLEET_CLASSES don't change the radar verdict.

9. **MEDIUM: D5's "no DB persistence" claim is false.** `occupancy_source` is persisted via `database.log_occupancy_event(entry_id, "entry", trigger=occupancy_source)` (`coordinator.py:5305-5310`) and the activity log (`:5117`). The label is unchanged, so this is harmless, but the D5 AC as written would fail. Restate it as "label values unchanged; DB/activity rows byte-identical". `binary_sensor.py:458` (timeout_at reads `== "timeout"`) is a second display reader. Add it.

10. **LOW: factual errors in §2.** (a) `data.get("_last_trigger_entity")` doesn't exist; there is no such data key. (b) "Guest Bedroom 2 Matter already declares `kind: mmwave`": live GB2 has `sensor_capabilities = None`; the cited lines are config_flow code, not live config. (c) Rejected option 7: `_recent_occupancy_sources` is read only by the recheck (`presence_fan_recheck.py:516, 795`). `_last_occupancy_source` is a separate scalar. (d) §2d says to keep an OR-arm on the string at 4179, but D2 says replace it. Pick one; finding 2's design makes the OR-arm unnecessary.

11. **LOW: the invariant is overstated.** "Fire if and only if radar-bearing" ignores the other gates (debounce, boot-settle, house-state, staleness). Restate: "the radar-sourced input to each fan-noise gate is a pure function of the capability of the set of Tier-1 entities on this tick, invariant under moving any entity between CONF lists". Add a list-permutation test: same on-set, different filing, same verdict. The existing mutation anchor is good. Add a per-site anchor for each of the (now ≥6) consumer sites.

### Ring lifecycle (Q3)
Both rings are constructed together in `__init__` (`coordinator.py:545`, maxlen 10), appended at the single tail site (`:5470`), and recreated on reload/restart. No persistence, so nothing goes stale across a restart. Alignment holds if the new value is appended at that **same statement**. Require one append site and a test asserting equal lengths. Early-return paths before 5470 would skip both rings equally; the builder should confirm there are none. Per finding 2, ring a per-tick boolean, not an entity id.

### §11 open questions, answered
1. **Motion bit:** classify it as radar (correct), but it gives no D2 win (finding 8). The real win is the recheck in GB1/GB2/Media (finding 7).
2. **Kill switch:** yes, add a rung-1 module constant (`OCCUPANCY_SOURCE_CAPABILITY_ROUTING_ENABLED`, True; False = byte-identical string gates). The "override same day" failsafe doesn't hold (finding 4), and this predicate now actuates fan pauses in rooms that were inert before (Media, Master Bedroom). No CM switch is needed (parsimony).
3. **Boot fallback direction:** fail closed (veto `capability_bootstrap`) for the recheck, since a fan pause is an actuation. The `hasattr` "staged deploy" case doesn't exist (one integration ships atomically; both rings are co-created). Real boot is already covered by `mmwave_history_short` (len < N). For D2, a False predicate is already fail-closed.
4. **GB2 revert:** NO-GO at ship. Under the current plan it would *lose* GB2's coverage (findings 1, 2, 5). After the fixes, make it an organic follow-up gated on live validation, and use it as the discriminating live test.
5. **occupancy→mmwave override legality:** confirmed legal. `validate_capabilities_payload` rejects only motion-wired → {mmwave, occupancy} (`sensor_capability.py:306-313`). Note, though, that the override changes only `derive_capability`. `presence_detected` (`coordinator.py:3479`) and `_classify_entity_kind` (`presence.py:385-391`) ignore it, so today the override does **not** make D2 or the recheck see the entity. That is the same root cause as findings 1 and 5.

### Must-fix before build
F1 (presence-side provenance gate in scope, or D2 descoped), F2 (per-tick sole-radar boolean at the producer; VACATED reads the live radar on-set), F3 (sole-source test), F4 (positive-evidence predicate with the override taking precedence), F5 (latch), F7 (discriminating live ACs), kill-switch constant. F6, F8, F9 and the LOWs: fix in the plan text.
