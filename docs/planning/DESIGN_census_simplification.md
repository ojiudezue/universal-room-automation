# DESIGN — Census subsystem simplification (show the work)

**Status:** DRAFT 2026-10-05 (not committed, not shipped). Companion to
`PLANNING_census_inputs_first.md` (Rev 3) and
`PLANNING_census_occupancy_estimator.md`.
**Operator ruling (2026-10-05):** "Rely on prior art where it is correct and
do not invent duplicate concepts. The state and arch diagram is a mess —
simplify where possible but show the work and the gains from it."
**Reads prerequisite:** `IDENTITY_FUSION_CAMERAS_MANUAL.md` (canonical);
`AUDIT_census_subsystem_2026_10_04.md` (current-state Mermaid at §2);
inputs-first Rev 3 (R3.0–R3.14); estimator plan (hybrid formula, D5/D6
tables).

Three bucket triage per CLAUDE.md: **KEEP** / **MERGE-INTO-X** /
**DELETE** (dead AND no use case AND footgun) / **FIX**. Dead ≠ delete.

---

## 1. Current map — component ledger with verdicts

Pulled from the audit Mermaid (§2 of `AUDIT_census_subsystem_2026_10_04.md`)
plus a re-grep against develop. One row per node/edge concept.

### 1.1 Producers (camera_census.py and friends)

| # | Component | File:line | Consumers (verified) | Verdict | Rationale |
|---|---|---|---|---|---|
| C1 | `_calculate_house_census` (raw per-area max → `camera_total`) | `camera_census.py:1690` | `_apply_enhanced_house_census :5681-5754` | **KEEP + FIX** | Sole producer of raw interior count. Dedup rule stays; estimator plan replaces `M_cam` definition with per-area-max-at-instant + short hold (R2.4 / estimator §7.2). |
| C2 | `_get_unrecognized_camera_count` (per-camera minus fresh face, minus BLE-here) → `camera_unrecognized`, `camera_total_pre_cancel` | `:5198-5381` | `:5661`, `:5728-5748` | **MERGE-INTO-C9 (estimator)** | Produces TWO numbers (`camera_unrecognized`, `camera_total_pre_cancel`) that the estimator's single FLOOR term `max(M_cam − R, 0)` subsumes. BLE-cancellation + resident subtraction live inside the estimator's one chokepoint (per CR-2 of the estimator plan: "residents subtracted ONCE from the camera term"). Legacy `pre_cancel` attribute goes KEEP+DOCUMENT (observability) until estimator ships. |
| C3 | `_build_frigate_person_last_camera_map` → face-name resolver | `:3192-3263` | `_get_face_recognized_person_names :5550` → `_apply_enhanced_house_census` | **FIX (R1 hotfix, dead face feed)** | `er.async_entries_for_platform(registry, "frigate")` does not exist on HA registry → map always `{}` → `face_recognized_count=0` for 8+ days. Replace with `[e for e in registry.entities.values() if e.platform == "frigate"]` or `async_entries_for_config_entry`. Not duplicate; broken. |
| C4 | `_apply_hold_decay` (15 s sustain, 3 min hold, instant drop) | `camera_census.py:5034` | `:5716` (unidentified hold), `:5799` (property hold) | **KEEP + CLARIFY SCOPE** | Only ONE hold mechanism in code — the audit's "two hold mechanisms" claim refers to (a) this one and (b) the estimator's PROSPECTIVE `FLOOR_WINDOW_S` (held camera max, 1200 s default). Those are different-purpose, different-scope (per-camera smoother vs house-wide FLOOR memory). KEEP C4 as the per-camera smoother; estimator introduces `FLOOR_WINDOW_S` additively — do NOT fold or rename. Document this in `IDENTITY_FUSION_CAMERAS_MANUAL.md` to kill the recurring "duplicate hold" confusion. |
| C5 | `_apply_enhanced_house_census` (chokepoint: `total = min(id + held_unrec, max(camera_pre_cancel, id))`) | `:5638-5770` | SIGNAL_CENSUS_UPDATED | **FIX (chokepoint replacement, D6)** | THE chokepoint. Current clamp = "visible-now ceiling" (audit F1). Estimator D6 keeps this method as the single writer but changes the formula to FLOOR = `R + max(M_cam−R, U_gr, T)` and adds additive `floor` key. Byte-identical on D6-OFF. |
| C6 | `_calculate_property_census` (perimeter, with its own hold) | `:1971` | SIGNAL_CENSUS_UPDATED → security | **KEEP** | NOT a duplicate of house census — different scope (perimeter rings) and different consumers (security/perimeter). The audit diagram listing it next to house census creates the impression of duplication; it is a sibling, not a copy. |
| C7 | `_get_wifi_guest_count` (Revel SSID, 4-hour recency) | `:5383-5548` | `_apply_enhanced_house_census` `_wifi_guest_floor` attr | **KEEP + DOCUMENT (dormant) → FIX (D4)** | Diagnostic-only today (not in formula). Estimator D4 FIXES filter (hostname denylist + MAC allowlist + "since last empty anchor"). Code stays; semantics change. Retire `WIFI_GUEST_RECENCY_HOURS` on D4 ship (per `KEEP + DOCUMENT` bucket in estimator §2.1). |

### 1.2 Door / egress pipeline (transit_validator.py)

| # | Component | File:line | Consumers | Verdict | Rationale |
|---|---|---|---|---|---|
| C8 | `_resolve_direction` + `_get_interior_cameras_near` | `transit_validator.py:1724-1963` | ledger write `:1879`, census register/evict `:1840`, notify `:1812`, face identity resolver `:1253` | **FIX (D1 — four changes in one site)** | Single site, four fixes: (i) `_extract_camera_stem` strip `_person_occupancy_2`/`_person_count_2` via REUSED `_strip_disambiguation_suffix` (R3.3); (ii) 30 s `DOOR_STEM_DEDUP_S` knob (R3.9); (iii) door-group dedup scope (R2.2 item 4); (iv) newest-first neighbour window with `CONF_DOOR_INTERIOR_NEIGHBOURS` fallback to today's full-interior-set on unset (R3.1). The 60 s `_last_resolved` prune ties to the knob (R3.9). No new site; same chokepoint. |
| C9 | Door ledger direction/dedup (duplicated in `_resolve_direction` AND documented in `camera_census._resolve_ble_legs` lead-window logic) | `transit_validator.py:1724` / `camera_census.py:4497-4555` | — | **NOT duplicate — KEEP both** | Audit implied duplication. In fact: `_resolve_direction` is the DIRECTION resolver; `_resolve_ble_legs` is the IDENTITY-leg attach helper. They read the same event but produce disjoint outputs (direction vs person_id). Documenting as "two concepts, one event" in the manual kills the duplication smell. |
| C10 | Stem dedup inline literal `5.0` | `transit_validator.py:1736` | — | **FIX → named knob** | Numbers-Get-Knobs violation. Becomes `DOOR_STEM_DEDUP_S` (default 30 s) in D1. |
| C11 | Ledger `person_entry_exit_events` | `database.py:4041-4066` | 10 downstream readers (sensor.py restore + 4 bus-listener sensors; BLE backfill `:4099-4177`; estimator replay) | **KEEP + EXTEND** | Add `peak_person_count INTEGER` (R3.6). Idempotent `ALTER TABLE … ADD COLUMN` per existing precedent (`database.py:972/1819/1957/2012/2057`). Non-dup. |

### 1.3 Identity union + guest arming (presence.py, camera_census.py)

| # | Component | File:line | Consumers | Verdict | Rationale |
|---|---|---|---|---|---|
| C12 | Identified union = BLE ∪ face-name ∪ egress-face | `camera_census.py:5681-5699` | `_apply_enhanced_house_census` | **KEEP + FIX (via C3)** | NOT three competing paths — it is a documented UNION. The audit's "identified union paths (BLE/face/egress-face)" is one function; the failure is that face is dead (C3). Fix C3 and the union restores. Keep the union; delete nothing. |
| C13 | **Path A guest gate** `_guest_gate_armed` | `presence.py:5355` | **NONE at runtime** (`guest_armed = guest_room_gate_armed` only at `:5891`, since GUEST-CENSUS D2 commit 2026-08-16) | **DELETE (dead + footgun)** | Dead since 2026-08-16; its presence invites "why doesn't the census arm GUEST?" cycles (we're in one). Three-bucket triage: dead (no readers) + no current use case (D5 flag supersedes census-as-trust-input via `source=estimate` on the new orthogonal flag) + footgun (misleads planners). **Delete when D5 ships** (not before — removal removes the on-ramp if D5 slips). Carries kill-switch REUSE `switch.ura_presence_guest_detection_enabled` → re-point switch to gate D5 estimate-path contribution. |
| C14 | **Path B guest gate** `_guest_room_gate_armed` (30 min sustained-unknown-occupied) | `presence.py:5303` | `presence.py:5885` (sole GUEST arm) | **KEEP → MERGE-INTO D5 flag as `source=guest_room`** | Sole live arm today. Estimator D5-2 migrates it to flag `source=guest_room`, orthogonal to house state. House-state transition dies; predicate stays. |

### 1.4 House-state consumers

| # | Component | File:line | Verdict | Rationale |
|---|---|---|---|---|
| C15 | 16 real `HouseState.GUEST` readers | estimator §6.2.a D5-1..D5-16 | **FIX (D5 migration)** | Each site reads flag instead of state; `HouseState.GUEST` enum deprecated one minor release then removed. Zero duplicate concepts; one semantic shift. |
| C16 | 21 `total_persons` / `census_count` readers | estimator §6.2.b D6-1..D6-21 | **FIX (D6 semantic shift)** | Payload shape unchanged (int). `interior_count` key byte-identical; additive `floor` key. |

### 1.5 Diagram-level duplicate concepts the audit flagged — adjudicated

| Flagged duplicate | Verdict | Evidence |
|---|---|---|
| "Two hold mechanisms" (`_apply_hold_decay` vs estimator FLOOR hold) | **NOT duplicate** | C4 (per-camera smoother, 3 min) vs `FLOOR_WINDOW_S` (house-wide FLOOR memory, 1200 s). Different scope, different purpose. Document in manual. |
| `camera_total` vs `camera_unrecognized` vs `camera_pre_cancel` | **MERGE-INTO-C9 (estimator D6)** | Three publishings of adjacent arithmetic from one function (C2). Estimator FLOOR term `max(M_cam − R, 0)` is their one true replacement; legacy attributes KEEP+DOCUMENT for observability through the D3 shadow period, then DELETE at D6 ship. |
| Identified union paths (BLE / face / egress-face) | **NOT duplicate** | One function (C12). The appearance of three paths is a UNION, not three competing writers. |
| Path A guest gate vs Path B | **Path A DELETE after D5** (C13); **Path B MERGE-INTO D5 `source=guest_room`** (C14) | File:line evidence above. |
| WiFi Revel diagnostics (`_wifi_guest_floor` 5 → 0 at 15:00) | **KEEP + FIX (D4)** | Attribute diagnostic today; estimator D4 upgrades filter. Non-duplicate (nothing else emits WiFi-sourced guest count). |
| Property vs house census | **NOT duplicate — sibling scopes** | C1 (interior) vs C6 (perimeter). Both produce `total_persons` but into DIFFERENT keys (`interior_count` vs `property_count`) with DIFFERENT consumers. |
| Door ledger direction/dedup "duplicated in transit_validator vs census" | **NOT duplicate** (C9) | Direction resolver vs identity-leg attach helper; disjoint outputs on the same event. Manual gets a one-paragraph section to end the recurring confusion. |

---

## 2. Target map — simplified Mermaid (after inputs-first D1 + hybrid D3-D6)

```mermaid
flowchart LR
  subgraph SRC[Sources — unchanged list, cleaner wiring]
    FPC["Frigate person_count\n(interior cams, _2 suffix tolerant via\nREUSED _strip_disambiguation_suffix)"]
    PRB["Protect/Reolink/Dahua/Amcrest\nbinary person"]
    FFACE["Frigate face-name feed\n(C3 fixed)"]
    BLE["PersonCoordinator → ble_persons"]
    WIFI["UniFi Revel\n(allowlist+anchor filter, D4)"]
    EGR["Egress cams (5) — door_groups\nvia CONF_DOOR_GROUPS"]
    PER["Perimeter cams"]
    GR["Guest-room occupancy\n(sustained-unknown predicate)"]
  end

  subgraph CEN["PersonCensus.async_update_census — one chokepoint"]
    MCAM["M_cam = per-area MAX @ instant\n+ short overlap-dedup\n(estimator §5.2 CONF_INTERIOR_CAMERA_OVERLAP_GROUPS)"]
    UGR["U_gr = sustained-unknown guest rooms"]
    T["T = door tally (unattributed)\npost: leg-collapse → same-person\n→ round-trip → resident-attrib\n(ONE pipeline, §7.1)"]
    FLOOR["FLOOR = R + max(M_cam−R, U_gr, T)\nguest-side MAX (H1 r6)\n= THE one chokepoint"]
    ANCH["Empty anchor (3-way AND, held)\n→ T=0, M_cam buffer cleared,\nin-flight priors cleared"]
    PROP["Property census (perimeter) — unchanged"]
  end

  subgraph TV["TransitValidator — one site"]
    DIR["_resolve_direction (D1 fixed)\n_2 stem dedup via REUSED normalisers\ndoor-group scope · 30s knob\nneighbours fallback → today on unset"]
    PEAK["peak_person_count (R3.6)\nmax-across-group, sampled at resolve"]
  end

  SIG(("SIGNAL_CENSUS_UPDATED\n+ floor key (additive)"))
  FLAG["guests_present FLAG\n(orthogonal to HouseState)\nsource ∈ {estimate, guest_room, revel, manual}"]
  HS["House state machine\n(no GUEST state post-D5;\nAWAY veto on FLOOR==0)"]

  FPC --> MCAM
  PRB --> MCAM
  FFACE --> FLOOR
  BLE --> FLOOR
  GR --> UGR
  EGR --> DIR --> T
  DIR --> PEAK --> LEDGER[("person_entry_exit_events\n+peak_person_count")]
  LEDGER --> T
  MCAM --> FLOOR
  UGR --> FLOOR
  ANCH --> T
  ANCH --> MCAM
  FLOOR --> SIG
  PROP --> SIG
  SIG --> FLAG
  SIG --> HS
  WIFI -. corroborator .-> FLAG
  FLAG --> HVAC[HVAC guest-mode]
  FLAG --> PRES[dynamic preset / overrides / NM severity]
  FLOOR --> SEC[security.authorized_guests]
  FLOOR --> ANOM[anomaly z-score]
```

Fewest components: **one producer per value, one chokepoint (FLOOR), one
orthogonal flag, one door-event site.**

---

## 3. GAINS — before / after

| Dimension | Before (today) | After (D1 + hybrid landed) | Delta |
|---|---|---|---|
| **Diagram nodes (producers)** | 11 (RAW, UNREC, FACEN, HOLD, ENH, PROP, DIR, EID, Path A, Path B, hold-decay) | 8 (M_cam, U_gr, T, FLOOR, anchor, direction, peak, property) | **−3** |
| **Published count-adjacent values** | `camera_total`, `camera_unrecognized`, `camera_total_pre_cancel`, `area_raw_max_pre_cancel`, `total_persons`, `interior_count` (6) | `interior_count` (byte-identical), additive `floor`, `estimate_band`, retired at D6 ship: 3 `pre_cancel` legacy attrs → observability-only, deleted next cycle | **−3 published** at D6+1 |
| **Guest-arming predicates** | 2 (Path A dead; Path B live) | 1 (D5 flag with 3 sources inside) | **−1 dead code path** |
| **House-state enum members** | 8 incl. `GUEST` | 7 (`GUEST` removed one release after D5 ship) | **−1** |
| **`HouseState.GUEST` string / enum readers** | 16 (D5 table) | 0 | **−16 call-sites touching state for guest-ness** |
| **`_last_camera_total_pre_cancel` / `_last_area_raw_max_pre_cancel` observability attrs** | 2 instance attrs + 2 sensor attrs | DELETED one cycle post-D6 | **−4** |
| **Dead-code lines (Path A `_guest_gate_armed`)** | ~70 lines (`presence.py:5355` + helpers) | 0 (deleted at D5 ship) | **−70 LoC** |
| **Direction-resolver code paths** | 2 (`_resolve_direction` + its degenerate "ALL interior cams" fallback) | 1 (narrowed on configured, byte-identical fallback on unset — one branch) | **−1 effective path** |
| **Stem-matching rules** | hand-maintained in `_extract_camera_stem` + `_PERSON_SUFFIXES` (duplicated knowledge) | REUSED composed normalisers (`_strip_disambiguation_suffix` + `_strip_suffix`) — single source of truth per manual §1.1 | duplicate concept **eliminated** |
| **Bug classes closed** | #22 (enum/suffix mismatch — `_2`), #7 (stale data source — face map `{}`), #23 (observation-mode gating — AWAY-while-occupied), #53 (computed-but-not-consumed — Path A), the "fake-API test anchor" class | — | **5 bug classes retired or defused** |
| **Test surface** | 2 tests monkeypatch non-existent `async_entries_for_platform` (hollow anchor) | Replaced by real registry fixture + mutation drill (R1); 10 new behavioural tests enumerated in D1/estimator plans | **−2 hollow anchors, +10 behavioural** |
| **Code paths removed (LoC estimate)** | — | Path A gate ~70 LoC; `pre_cancel` attribute block + sensor attr ~25 LoC; `WIFI_GUEST_RECENCY_HOURS` + 4h filter ~15 LoC; `HouseState.GUEST` enum branch + hysteresis ~40 LoC | **~150 LoC removed** (staged: D5 ship −70, D6+1 cleanup −80) |

**Measurement caveat:** LoC are grep-based estimates from `presence.py`
`:5355`-block, `camera_census.py` `pre_cancel` attribute writers + sensor
attrs at `sensor.py:3707-3717`, and `house_state.py:60-139`. Final cuts
confirmed at delete-PR time.

---

## 4. Sequencing — which simplifications ride which cycle

Per CLAUDE.md soak-exit discipline: simplifications ride with the cycle
that already touches the surface; stand-alone cleanup cycles only for
items with no natural carrier.

### 4.1 Inside the inputs-first build (D1, Tier 2-DB — PLANNING_census_inputs_first.md Rev 3)

| Simplification | Carrier | Prior art REUSED |
|---|---|---|
| `_extract_camera_stem` `_2`-suffix fix | R3.3 | `camera_resolver.py:214-270` + `:291/305` + `:317`; composed already at `camera_census.py:712-720` |
| Stem dedup literal → `DOOR_STEM_DEDUP_S` knob | R3.9 / R2.2 item 2 | `transit_validator.py:1736` single call-site |
| `_get_interior_cameras_near` neighbour narrowing (configured only; byte-identical fallback) | R3.1 | `transit_validator.py:1955-1963` + second caller `:1253` |
| `peak_person_count` column + sampler + reader | R3.6 | `database.py:4041-4066` writer + `:972/1819/1957/2012/2057` migration precedent; sampler uses existing `DOOR_STEM_DEDUP_S` + `EGRESS_ENTRY_WINDOW_SECONDS` |
| `_last_resolved` prune tied to dedup knob | R3.9 | `transit_validator.py:2001-2008` |

### 4.2 Inside the hybrid build (D3 shadow → D5 flag → D6 FLOOR; Tier 2-DB then Tier 3 — PLANNING_census_occupancy_estimator.md)

| Simplification | Carrier |
|---|---|
| `_apply_enhanced_house_census` clamp replaced by FLOOR formula (single chokepoint, additive key) | D3 shadow + D6 producer-side (`camera_census.py:5740-5754`) |
| Path B guest-room predicate re-pointed to flag `source=guest_room` (state transition dropped) | D5-2 |
| 16 `HouseState.GUEST` readers migrated to flag | D5-1..D5-16 |
| 21 `total_persons` readers byte-identical on D6-OFF; FLOOR when D6-ON | D6-1..D6-21 (`domain_coordinators/presence.py`, `sensor.py`, `binary_sensor.py`, `aggregation.py`, `camera_census.py`, `database.py`) |
| C3 face-name resolver fix (REUSE `registry.entities.values()` or `async_entries_for_config_entry`) | R1 (Tier 1 hotfix, carded; estimator plan §2.1 lists candidate home `CENSUS-FACE-RESOLVER-MIGRATE-1`) |
| C7 Revel filter (allowlist + anchor-since filter) | D4 |
| Empty anchor (3-way AND independent of AWAY, clears M_cam buffer) | §7.4 — new chokepoint, no duplicate |
| INV-NO-LATCH + anchor-erasure accepted exception (still-guest) | §7.4 / §0 ruling 14 |

### 4.3 Separate cleanup (one minor release after D5 / D6 soak out)

| Simplification | Why separate |
|---|---|
| DELETE Path A `_guest_gate_armed` + related persistence rows | Risk-isolate from D5 migration; delete only after flag ON-path is live-validated. Target: cycle N+1 after D5 ship. |
| DELETE `_last_camera_total_pre_cancel` / `_last_area_raw_max_pre_cancel` + sensor attrs | Keep as observability through D3 shadow; delete after FLOOR is the sole consumer. |
| REMOVE `HouseState.GUEST` enum member + `"guest"` strings in `const.py:3055/3447` | Gated on operator-side `/config/automations.yaml:8308` migration (D5-16). |
| RETIRE `WIFI_GUEST_RECENCY_HOURS` | After D4 ships allowlist+anchor filter; keep documented. |
| Document "two different holds / direction vs identity-leg / property≠house / identified-union-is-one-function" in `IDENTITY_FUSION_CAMERAS_MANUAL.md` | Not duplicate code — duplicate CONCEPT confusion. One doc PR kills the recurring triage spin. |

### 4.4 Items that do NOT ship this arc (parked with triggers)

- **D7 vision group count** — park; revival trigger = R2 shadow shows multiplicity is the residual error (estimator §4.1 option B).
- **Resident-at-room BLE presence corroborator** (D2 Path-β) — park `CENSUS-ATHOME-RESIDENT-CORROBORATOR-1`; trigger = at-home-wandering Path-β exceeds operator budget of ~4 episodes/day over 30 days.
- **Entry-side BLE attach new producer** — REFUTED (R3.4); do NOT re-mint.
- **`CONF_MAIN_ENTRY_DOOR`** — deferred to estimator cycle where it consumes (R3.7).

---

## 5. Alignment checks

- **No new chokepoint added** — FLOOR replaces the existing clamp inside
  `_apply_enhanced_house_census`; keeps "one writer of the house total"
  invariant from audit §3.
- **No new producer per value** — `M_cam` subsumes `camera_total` + two
  `pre_cancel` observability siblings; `T` subsumes door direction counts;
  flag subsumes two gates.
- **Degrades gracefully by what is configured** (per project-single-user-
  no-backcompat memory, 2nd install 2026-10-03/04): unset `CONF_DOOR_*`
  → today's behaviour byte-identical (R3.1); no interior cams → camera
  term absent (not zero) in FLOOR max; no trackers → `guests_present
  source=unknown`, anchor disabled.
- **Prior-art REUSE preserved** (operator ruling 2026-10-05): no symbol
  renamed where the existing one is correct; `_strip_disambiguation_suffix`,
  `_PERSON_SUFFIXES`, `_apply_hold_decay`, `_calculate_property_census`,
  `_guest_room_gate_armed` predicate body, `CONF_CAMERA_PERSON_ENTITIES`,
  `CONF_ROOM_IS_GUEST_ROOM`, `switch.ura_presence_guest_detection_enabled`
  all kept; cited file:line in §1.

---

## Changelog
- 2026-10-05: initial draft (ura-planner).
