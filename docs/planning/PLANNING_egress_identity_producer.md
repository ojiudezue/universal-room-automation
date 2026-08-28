# PLANNING — Egress-Identity Producer (Frigate + Protect fusion)

**Card:** `EGRESS-IDENTITY-JOIN-GAP-1`
**Tier:** **2-DB** (identity trust ripple: person_id becomes advisory for
egress rows, feeds census union, and is the 6.0.0 gate). 3 framing-
disjoint reviews + orchestrator-verify + live validation. This plan
requires **one adversarial plan review** before build dispatch.
**Posture:** EXTEND-EXISTING — no new fusion layer. Every change lands on
prior-art surfaces already carrying the multi-platform substrate.
**Date:** 2026-08-28.

---

## 0. Falsifiable invariant (the property this cycle must guarantee)

> **INV-EGRESS-ID:** No row in `person_entry_exit_events` is stamped with
> a non-NULL `person_id` unless, at the crossing timestamp `T_x`, there
> exists a **named** face hit (Frigate `_last_recognized_face[_2]` OR the
> new Protect bridge entity — §D1) on a camera in the crossing camera's
> **interior-adjacent leg-set** (`_get_interior_cameras_near`) whose
> `last_changed` falls inside the direction-keyed signed-lag window
> — `exit ∈ [T_x-30s, T_x+180s]`, `entry ∈ [T_x-300s, T_x+60s]` —
> AND no second distinct canonical name is present in-window within the
> abstain-margin (else emit `person_id=None`). `person_id` is **advisory**:
> every current and future consumer must accept NULL / anonymous.

**Falsifiers (any one falsifies INV):**
1. A row exists with `person_id=X` but no in-window named hit for that
   canonical slug on any leg of the interior-adjacent set (grep DB +
   recorder cross-check).
2. Two distinct canonical names appeared in-window within the abstain
   margin and a row was still stamped rather than emitting NULL.
3. A row's `person_id` is a first-name string (`"Oji"`) rather than a
   canonical slug (`"oji_udezue"`) — namespace break with
   `person.<slug>`, census union, `ble_persons`, `identified_persons`.
4. Byte-diff on the no-name/abstain path vs pre-cycle (INV byte-identity
   check under kill-switch OFF and under all-abstain fixture).

---

## 1. Institutional context verified

### 1.1 Prior-art surfaces the extension lands on (REUSED)

| Surface | file:line | Role in the extend |
|---|---|---|
| `DetectionLeg(entity_id, engine, integration, device_id)` | `camera_resolver.py:164-185` | REUSED — already the multi-platform leg abstraction; carries `engine` tag (frigate/frigate2/protect/protect2/…). No shape change. |
| `_FACE_SUFFIXES` (includes Protect `_smart_detect_face` / `_face_recognized`) | `camera_resolver.py:246-252` | REUSED — face-capability suffix set is ALREADY multi-platform. No addition needed for the resolver ladder. |
| `resolve_detection_legs` / `enumerate_platform_cameras` | `camera_resolver.py:885, 1039` | REUSED — supplies the per-physical-camera leg-set to iterate for named-face reads. |
| `_resolve_face_entity_id(base_name)` | `camera_census.py:2615-2648` | **EXTEND** in D2a — currently returns a single Frigate `_last_recognized_face[_2]` entity; will be extended to consult all face-capable legs and return the highest-confidence NAMED hit across engines. Fail-CLOSED behaviour + `_face_lookup_missing_count` telemetry preserved. |
| `_resolve_egress_face_identity(egress_camera_id, timestamp)` | `transit_validator.py:1120-1226` | **EXTEND** in D2b — same-stem lookup → interior-adjacent stems; symmetric `[0, FACE_MATCH_WINDOW_S]` → asymmetric direction-keyed window; add abstain-on-conflict. Keeps the not_home veto (1211-1225), the kill-switch (1157-1161), and the canonical-slug guarantee (1208). |
| `_get_interior_cameras_near(egress_camera_id)` | `transit_validator.py:1346-1354` | REUSED — currently returns all interior entities; D2b iterates its output for face reads. Adjacency mapping refinement is out of scope. |
| Census identity UNION (union-cardinality-not-sum, divergence-downgrade) | `camera_census.py` (identity aggregation) | REUSED unchanged — no rewrite of the union. |
| `_canonical_person_slug(name)` | `camera_census.py:2883-2950` | REUSED — every named hit is normalized to the URA slug namespace before write / veto / event. |
| `_is_egress_identity_enabled()` (kill-switch: `switch.ura_name_people_at_doors`) | `camera_census.py:2964`, `switch.py:190`, `const.py:2172-2178` | REUSED unchanged — fresh-read gate. Default ON per DEFAULT_EGRESS_IDENTITY_ENABLED. |
| Writer `log_entry_exit_event(person_id, event_type, direction, egress_camera, confidence)` | `database.py:3903-3928` | REUSED unchanged — signature already accepts `Optional[str]` person_id; `confidence REAL NOT NULL` already exists (schema `database.py:794-802`). |
| Person-tracker veto pattern | `camera_census.py:3456` (mirrored at `transit_validator.py:1211-1225`) | REUSED — fail-open not_home veto stays; applied on the canonical slug. |
| v5.9.0 census-observability-attrs enrichment pattern | `sensor.py:3609-3699` | REUSED — D3 attaches new attrs to the SAME `attrs` dict on the existing census sensor. No new sensor. |
| Face-rec on/off + face_recognized_persons attrs | `sensor.py:3602`, `camera_census.py:1169` | REUSED — no touch. |

### 1.2 NEW (only what does not exist)

| Item | Rung | Justification (grep-verified absence) |
|---|---|---|
| `sensor.<cam>_protect_recognized_face` (one per Protect-face-capable camera) | HA entity, **outside URA** (bridge) | NEW — grep confirms no Protect NAME entity exists in HA today; the `unifiprotect` HA integration exposes DETECTION only (manual §1). URA reads the entity, does not create it. |
| `FACE_MATCH_EXIT_WINDOW_LEAD_S`, `FACE_MATCH_EXIT_WINDOW_LAG_S`, `FACE_MATCH_ENTRY_WINDOW_LEAD_S`, `FACE_MATCH_ENTRY_WINDOW_LAG_S` (const.py) | Module constant (§Numbers-Get-Knobs rung 1) | NEW — the current `FACE_MATCH_WINDOW_S=60` (`const.py:2162`) is symmetric and same-stem; the measured signed-lag geometry needs four bounds. Rung-1 (module const) because a change materially alters yield-vs-ambiguity trade and must go through review. `FACE_MATCH_WINDOW_S` retained for backward reference; new constants take precedence in D2b. |
| `FACE_MATCH_ABSTAIN_MARGIN_S` (const.py) | Module constant | NEW — tie-break window for the abstain rule. |
| `FACE_MATCH_MIN_CONFIDENCE` (const.py) | Module constant | NEW — floor for a Protect / Frigate hit to be considered named (defaults align with §D1 bridge attrs). |
| Census observability keys: `egress_identity_attach_rate_24h`, `egress_identity_abstain_rate_24h`, `egress_identity_ambiguity_rate_24h`, `egress_identity_last_attach` | Attribute on existing sensor | NEW keys, EXISTING sensor (D3). |

### 1.3 Prior planning + memory + design docs consulted

- `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` — §1 platforms, §1.1 `_2` permanence, §4 architecture, §5 the JOIN, §2.3 Protect (canonical). Read end-to-end for §1.
- `docs/planning/PLANNING_paper_and_oss_fusion_library.md` — reviewed for
  cross-modal doctrine; no rewrite implied.
- `docs/planning/AUDIT_census_identity_supersession_and_consumers.md` —
  reviewed for downstream should-be-consuming gaps (out of scope; see §Non-Goals).
- Kanban card body `EGRESS-IDENTITY-JOIN-GAP-1` (`kanban.data.yaml:29-138`)
  — root cause, probe result, Protect-API findings, architecture ruling.
- Memories: `reference_egress_face_coverage_7pct_not_a_ceiling.md`,
  `reference_frigate1_retired_2suffix_permanent.md`,
  `reference_architecture_map.md`, `reference_code_tracing_methodology.md`,
  `feedback_coincidental_equality_masks_concept_split.md`,
  `feedback_verify_claim_types_not_felt_uncertainty.md`.

### 1.4 Code locations surveyed end-to-end during scoping

- `custom_components/universal_room_automation/transit_validator.py:1080-1360`
- `custom_components/universal_room_automation/camera_census.py:2600-2700, 2860-3060`
- `custom_components/universal_room_automation/camera_resolver.py:115-270, 880-1140`
- `custom_components/universal_room_automation/database.py:790-810, 3900-3960`
- `custom_components/universal_room_automation/sensor.py:3580-3700`
- `custom_components/universal_room_automation/const.py:2140-2200`
- `custom_components/universal_room_automation/switch.py:180-210`

### 1.5 Producer / Consumer discipline

- **Producer arithmetic:** two producer legs (Frigate `_last_recognized_face[_2]`, new Protect bridge entity per D1). Dependency health: face-rec engine on (Frigate healthy since 08-27 tuning; Protect enrollment gap operator-owned, parallel). NO INTERNAL fusion invention — the producer is "highest-confidence named hit on the interior-adjacent leg-set within the direction-keyed window."
- **Consumer sites (grep-verified):**
  1. `ura_person_egress_event` bus payload (`transit_validator.py:1284-1290`).
  2. Writer `database.log_entry_exit_event` (`transit_validator.py:1336`, `database.py:3903`).
  3. Census union feed `register_egress_face` / `evict_egress_face` (`transit_validator.py:1321-1323`, `camera_census.py:2964+`).
  4. Downstream 6.0.0 gate consumers (guest gate, arrival/departure) — DEFERRED (see Non-Goals). Every consumer, current AND future, must accept NULL.

---

## 2. Deliverables

### D1 — Protect face-NAME bridge entity (OUTSIDE URA)

**What.** One HA entity per Protect-face-capable camera:

- `sensor.<cam>_protect_recognized_face`
- `state` = `recognized_person_name` (empty string on unnamed cluster; mirrors the Frigate `_last_recognized_face` semantics — the manual §1 recognizer contract).
- `attributes`:
  - `person_id`: Protect `recognized_person_id` (string) — enrolled Known Face ID; empty when auto-cluster.
  - `confidence`: `recognized_person_confidence` (float 0.0–1.0).
  - `event_start`, `event_end`: ISO-8601 timestamps of the Protect event window.
  - `camera_id`: Protect camera device id.
  - `engine`: constant `"protect"` (matches DetectionLeg engine tag vocabulary at `camera_resolver.py:174-176`).

**Transports (URA reads the entity either way — vendor-agnostic).**

- **(a) Preferred: fix the v2 Alarm Manager webhook body (Protect UI) + a small HA template automation** that maps the `ura_kp_face_probe_received` event body onto the entity above. This is the FINISH-THE-PROBE task already carded in the kanban body (`PROTECT_FACE_SOURCE_2026_08_28`). The automation is authored in the HA UI per `home-assistant-best-practices` (entity_id-first, no YAML edits to `configuration.yaml`).
- **(b) Fallback: a small HA poll component over the Protect events API** (`protect_list_smart_detections` / `protect_list_events` — verified in the kanban body under `PROTECT_API_2026_08_28`, Oji named at 82% at 21:32). Polls a bounded lookback (e.g. 30s) at ~5s cadence; publishes the same entity contract.

**Contract discipline.** The entity contract is designed against a REAL events-API record (kanban body `PROTECT_API_2026_08_28`). The two transports are swappable at the HA-side layer without any URA change.

**NON-GOAL** (see §Non-Goals): URA does not call the Protect API at runtime. Coupling lives in the bridge.

### D2a — Extend `_resolve_face_entity_id` to read across camera legs

**File:** `camera_census.py:2615-2648`.

**Change.**
- Consult all face-capable legs for the base camera (Frigate `_last_recognized_face[_2]` AND the new Protect entity from D1 — enumerated via the existing multi-platform `_FACE_SUFFIXES` at `camera_resolver.py:246-252`; no new suffix set).
- Return the entity_id of the leg with the **highest current confidence NAMED state** (see §2.3 selection rule). Ties resolved by the leg with the more recent `last_changed`.
- Result is fed to `_canonical_person_slug` upstream (unchanged), preserving namespace invariant.
- Preserve fail-CLOSED behaviour (all legs unusable → `None`, increment `_face_lookup_missing_count`).
- Frigate-only until D1's bridge entity exists (Protect legs simply don't resolve to a live state). Gains Protect automatically the moment the bridge publishes.

**Selection rule (§2.3).** For each leg, read `state` (name) and — if the leg exposes it as an attribute — `confidence`. A leg is a **named** hit iff `state` normalizes to a non-empty non-sentinel value (mirrors the existing sentinel filter at `camera_census.py:2639-2643`) AND (if `confidence` attr present) `confidence >= FACE_MATCH_MIN_CONFIDENCE`. Frigate `_last_recognized_face` has no confidence attr today → treated as passing the floor (backward-compatible).

### D2b — Extend `_resolve_egress_face_identity` with interior geometry, signed-lag window, abstain

**File:** `transit_validator.py:1120-1226`.

**Changes (each is a delta to the existing method — no rewrite):**

1. **Interior-adjacent stems** — swap the single `stem` read for iteration over `self._get_interior_cameras_near(egress_camera_id)` (already used at `transit_validator.py:1249` for direction). For each interior camera, use D2a's extended `_resolve_face_entity_id` on its stem.
2. **Asymmetric signed-lag window** — replace the current single-bound freshness check at `transit_validator.py:1193-1201` (`age < 0 or age > FACE_MATCH_WINDOW_S`) with:
   - `direction == "exit"` → `age ∈ [-FACE_MATCH_EXIT_WINDOW_LEAD_S, +FACE_MATCH_EXIT_WINDOW_LAG_S]`, defaults `(30, 180)`.
   - `direction == "entry"` → `age ∈ [-FACE_MATCH_ENTRY_WINDOW_LEAD_S, +FACE_MATCH_ENTRY_WINDOW_LAG_S]`, defaults `(300, 60)`.
   - `direction == "ambiguous"` → return `None` (unchanged: ambiguous crossings do not stamp identity — matches the existing DB-write gate at `transit_validator.py:1332`).
   - Sign convention: `age = (T_x - last_changed).total_seconds()`. Positive `age` = face BEFORE crossing (exit case); negative `age` = face AFTER crossing (entry case). Kanban probe: exits face-leads (+53s median), entries face-trails (-14s median).
3. **Abstain-on-conflict** — collect ALL named canonical hits across interior legs falling inside the direction-keyed window. Compute set of DISTINCT canonical slugs. If `|distinct| >= 2`:
   - Order by absolute `|age|`. If `|age_1 - age_2| < FACE_MATCH_ABSTAIN_MARGIN_S` (default 15s) → **abstain**, return `None`.
   - Otherwise the nearest-in-time hit wins.
4. **Ordering (subtle).** Direction is computed at `transit_validator.py:1248-1265` BEFORE `_resolve_egress_face_identity` is called at `:1279`. D2b takes `direction` as a new parameter (added to the call site at `:1279-1281`). Signature becomes `_resolve_egress_face_identity(egress_camera_id, timestamp, direction) -> str | None`.
5. **Preserved unchanged** — the kill-switch check at `:1157-1161`, the canonical-slug pass at `:1208`, the fail-open `not_home` veto at `:1211-1225`.
6. **Confidence stamp.** The existing `confidence` column on `person_entry_exit_events` is already `REAL NOT NULL` (`database.py:801`). The current writer receives `confidence` from `_resolve_direction` at `transit_validator.py:1268-1272` (platforms-fired heuristic, 0.3–0.9). NO SCHEMA CHANGE. The face-side confidence is captured in the census observability attrs (D3) as `last_attach.confidence` — not persisted to the row today; a schema addition is out of scope.

### D3 — Observability on the existing census sensor (no new sensor)

**File:** `sensor.py:3609-3699` (existing v5.9.0 attrs block on the census sensor).

**New attrs on the SAME dict:**
- `egress_identity_attach_rate_24h`: fraction of egress rows in the last 24h with non-NULL `person_id` (rolling DB query, cached per-tick).
- `egress_identity_abstain_rate_24h`: fraction of crossings where D2b returned `None` due to the 2-name abstain rule (in-memory counter on the resolver, reset at UTC-day boundary — pattern mirrors `_face_lookup_missing_count` at `camera_census.py:2647`).
- `egress_identity_ambiguity_rate_24h`: fraction of crossings where `|distinct in-window names| >= 2` regardless of margin.
- `egress_identity_last_attach`: `{person, camera, confidence, signed_lag_seconds, direction}` from the most recent successful attach.

Values are read directly from the `TransitValidator` and `PersonCensus`
instances via the same defensive-getattr pattern already used in the
attrs block (`sensor.py:3612-3697`). Failures degrade silently (existing
`try/except` at `:3698-3699`).

---

## 3. Numbers on the knob ladder

| Constant | File | Rung | Rationale |
|---|---|---|---|
| `FACE_MATCH_EXIT_WINDOW_LEAD_S = 30` | `const.py` | Module (rung 1) | Fitted to signed-lag probe; change must go through review (correctness bound). |
| `FACE_MATCH_EXIT_WINDOW_LAG_S = 180` | `const.py` | Module | " |
| `FACE_MATCH_ENTRY_WINDOW_LEAD_S = 300` | `const.py` | Module | " |
| `FACE_MATCH_ENTRY_WINDOW_LAG_S = 60` | `const.py` | Module | " |
| `FACE_MATCH_ABSTAIN_MARGIN_S = 15` | `const.py` | Module | Load-bearing tie-break — a change silently permits ties to attach; review-required. |
| `FACE_MATCH_MIN_CONFIDENCE = 0.60` | `const.py` | Module | Fitted-model coefficient; Protect Known-Face median 0.82 in kanban probe. |

**Kill-switch semantics (unchanged).** `switch.ura_name_people_at_doors`
OFF → `_resolve_egress_face_identity` returns `None` immediately
(`transit_validator.py:1157-1161`) AND census fuse sites become no-ops
(`camera_census.py:3001, 3055`). Byte-identity of the no-name path is
part of INV-EGRESS-ID (falsifier #4).

`FACE_MATCH_WINDOW_S` (existing, `const.py:2162`) is **retained**
(referenced by census `_get_egress_face_ids_fresh`) but the new
direction-keyed constants take precedence in `_resolve_egress_face_identity`.

---

## 4. Acceptance criteria — DISCRIMINATING

### D1 — Protect bridge

- **Verify:** at least one `sensor.<cam>_protect_recognized_face` exists
  in the HA registry post-deploy and, for at least one camera, its state
  updates within 60s of a Protect event carrying `recognized_person_name`
  (query via `ha_get_states` on the entity after a live crossing).
- **Verify (transport-agnostic):** URA does not import or call any
  Protect API (`grep -R "protect_list_\|unifi_protect\." custom_components/universal_room_automation/` returns nothing new).
- **Live:** the entity is readable via `hass.states.get` and its state is
  a recognized name (or empty string), never `unavailable` while Protect
  is up.

### D2a — Extended `_resolve_face_entity_id`

- **Test:** with a Frigate leg in a named state and no Protect leg, the
  helper returns the Frigate entity (backward-compat).
- **Test:** with a Frigate leg unnamed and a Protect bridge leg named
  and above `FACE_MATCH_MIN_CONFIDENCE`, the helper returns the Protect
  entity.
- **Test:** with both legs named on DIFFERENT names, the highest-
  confidence hit wins (Frigate treated as passing the floor).
- **Discriminator:** a leg reporting `unavailable` never wins over a
  legitimately named sibling (rules out the resolver returning a stale/
  broken entity).

### D2b — Extended `_resolve_egress_face_identity`

- **Verify (attach rate):** `sensor.<census>.attributes.egress_identity_attach_rate_24h`
  rises from ~0 toward the measured **~63%** Frigate-only floor within
  ~24h of enable, then higher as D1 Protect coverage lands.
- **Test (abstain):** fabricated fixture — two distinct canonical
  identities appear in-window within `FACE_MATCH_ABSTAIN_MARGIN_S` →
  helper returns `None` AND the observability abstain counter
  increments. Discriminator: an equivalent fixture with one identity
  returns the correct slug (not conflated with abstain).
- **Test (INV byte-identity):**
  1. Kill-switch OFF → resolver returns `None` before any leg read;
     `ura_person_egress_event` payload identical to pre-cycle
     (`person_id: None`); DB row `person_id IS NULL`.
  2. All-abstain fixture → same byte-identity as (1).
- **Test (namespace):** every non-NULL `person_id` on
  `ura_person_egress_event` matches `^[a-z0-9_]+$` and equals a
  configured `person.<slug>` known to the census (rules out first-name
  string leak).
- **Test (advisory):** an in-code consumer stub (guest-gate test double)
  that receives `person_id=None` continues to function — no NoneType
  branches.

### D3 — Observability attrs

- **Live:** `sensor.<census>.attributes.egress_identity_last_attach` is
  populated within ~1 crossing after enable and carries the expected
  keys.
- **Verify:** post-deploy DB query
  `SELECT COUNT(*), SUM(CASE WHEN person_id IS NOT NULL THEN 1 ELSE 0 END) FROM person_entry_exit_events WHERE timestamp > <T_deploy>` — the
  ratio matches the observability attach-rate within ±5 pts.

### Live-validation table (to be written back into the README per
`Record Live Validation Back Into the README`).

| # | Criterion | Method | Expected |
|---|---|---|---|
| L1 | Attach rate rises from ~0 toward ~63% floor within 24h | DB ratio query above | ratio ≥ 0.30 within 24h (Frigate-only floor; higher with D1 Protect live) |
| L2 | Namespace invariant holds | `SELECT DISTINCT person_id FROM person_entry_exit_events WHERE timestamp > T_deploy` | all rows either NULL or canonical slug present in `tracked_persons` |
| L3 | Abstain counter fires organically | `egress_identity_abstain_rate_24h` attr | non-zero within a week (ambiguity ~28% per probe) |
| L4 | INV byte-identity on kill-switch OFF | flip `switch.ura_name_people_at_doors` off, force a crossing | row inserted with `person_id IS NULL`, `ura_person_egress_event.person_id is None` |

---

## 5. Non-goals (explicit)

- **URA runtime Protect-API client** — coupling lives in the bridge
  (D1). URA reads HA entities only.
- **A new fusion layer** — no new coordinator, no new resolver class,
  no new census-union pathway. Every change is an extension of an
  existing method.
- **Wiring downstream 6.0.0 consumers** (guest gate consuming
  door-identity, arrival/departure keyed to `person_id`, egress-keyed
  identity policy) — those are separate follow-on cards. This cycle
  ships the PRODUCER; consumers are graceful-null today and can be
  upgraded independently.
- **Blocking on Protect Known-Face enrollment** — operator-side and
  parallel. The producer degrades gracefully when Protect names are
  sparse (falls back to Frigate).
- **Schema change to add face-side confidence to
  `person_entry_exit_events`** — deferred; captured in D3
  observability attrs today.
- **Adjacency-mapping refinement in `_get_interior_cameras_near`**
  (currently returns all interior entities) — sufficient for the join
  because the direction-keyed window discriminates temporally; a per-
  door adjacency table is a separate card.

---

## 6. Judgement calls needing operator confirmation

1. **D1 transport priority.** Preferred path is fixing the Alarm
   Manager webhook (already carded as FINISH-THE-PROBE); the poll
   fallback is a HA custom component effort. Operator to confirm the
   webhook-fix has priority OR authorize the poll fallback as the
   initial transport. Either way URA D2a/D2b ship first (Frigate-only)
   and gain Protect automatically when the bridge entity exists.
2. **Default value of `FACE_MATCH_MIN_CONFIDENCE`.** 0.60 chosen from
   the kanban probe's Protect Known-Face floor. Frigate's
   `_last_recognized_face` has no confidence attr today → treated as
   passing the floor (backward-compat). Alternative: emit face-side
   confidence as an attr on the Frigate sensor via a template. Default
   0.60 is the minimum-surprise choice; confirm.
3. **Attach-rate floor for L1 acceptance.** The kanban probe reports
   ~63% under 48h re-tuned face-rec. Setting the L1 gate at ≥0.30
   accepts a partially-degraded face-rec engine (health varies).
   Confirm the floor OR lower it to ≥0.20 to allow for engine-health
   variability without an incident flag.
4. **Frigate confidence attr absence.** Do we add a template sensor to
   surface Frigate face confidence (parallel to the Protect bridge
   attr), or leave the current "Frigate named ⇒ passes floor"
   equivalence? The latter is simpler and matches today's producer
   trust posture; the former enables a uniform confidence-margin
   abstain rule across engines. Recommend deferral to a follow-on card
   unless operator disagrees.

---

## 7. Review protocol (Tier 2-DB)

1. **Plan review (one adversarial pass, before build dispatch).**
   Reviewer verifies §1 institutional context by re-grepping the cited
   file:line anchors; re-enumerates emission/consumer sites for
   `person_id`; confirms the invariant §0 is falsifiable and the
   acceptance criteria discriminate; challenges the four judgement
   calls in §6.
2. **Three framing-disjoint code reviews (post-build):**
   - **A — data integrity + resolver correctness.** DetectionLeg
     iteration exhaustive; canonicalization invariant preserved on
     every path; `_face_lookup_missing_count` still increments on real
     misses only; DB writer signature unchanged; INV byte-identity
     under kill-switch OFF proven by mutation-restored source drill.
   - **B — signed-lag geometry + abstain correctness + cross-
     coordinator ripple.** Every direction branch (`exit`, `entry`,
     `ambiguous`) audited; abstain-margin tie-break correct at extremes
     (`|age_1 - age_2| == margin`, exactly-2-in-window, 3+-in-window);
     census union register/evict gating at
     `transit_validator.py:1316-1329` unaffected on the abstain path;
     restart behaviour (no persisted resolver state).
   - **C — new surfaces + test fixture authority.** D1 bridge entity
     contract shape matches the real Protect events-API record (fixture
     built from a live capture, not hand-typed); D3 attrs round-trip
     through the existing sensor's attrs block; kill-switch state
     round-trips via the existing switch (no new persistence).
3. **Orchestrator independent verification.** Re-grep every named-hit
   read site and re-run the source-mutation drill on
   `_resolve_egress_face_identity`.
4. **Live validation (Review D).** Post-restart, populate the table in
   §4 back into `docs/readmes/README_v<version>.md`.

---

## 8. Files touched

| File | Change |
|---|---|
| `custom_components/universal_room_automation/const.py` | ADD 6 new constants (§3). Retain `FACE_MATCH_WINDOW_S`. |
| `custom_components/universal_room_automation/camera_census.py` | EXTEND `_resolve_face_entity_id` (D2a). |
| `custom_components/universal_room_automation/transit_validator.py` | EXTEND `_resolve_egress_face_identity` + call site at `:1279-1281` (add `direction` arg). D2b. |
| `custom_components/universal_room_automation/sensor.py` | ADD 4 attrs to existing census attrs block (D3). No new sensor. |
| (HA-side, outside URA) | Bridge automation + entity per D1 transport (a) or (b). |

No changes to: `database.py` schema, `config_flow.py`, `switch.py`,
`__init__.py`, `camera_resolver.py`.

---

## 9. Rollback

- Kill-switch `switch.ura_name_people_at_doors` OFF → INV byte-identity
  to pre-cycle behaviour (falsifier #4 is the acceptance test for this).
- No schema migration → no rollback obstacle at the DB layer.
- D1 bridge is a HA-side entity; disabling the automation makes the
  Protect leg silently disappear from D2a's selection (Frigate-only
  falls out).
