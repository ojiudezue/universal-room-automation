# PLANNING — Egress-Identity Producer (Frigate + Protect fusion)

**Card:** `EGRESS-IDENTITY-JOIN-GAP-1`
**Tier:** **2-DB** (identity trust ripple: `person_id` becomes advisory
for egress rows, feeds the census union, and is the 6.0.0 gate). Three
framing-disjoint code reviews + orchestrator verification + live
validation. One adversarial plan review is required before build
dispatch.
**Posture:** EXTEND-EXISTING — no new fusion layer. The one accepted
scope addition is a NEW leg-set accessor `_resolve_face_legs` that
sits alongside the existing single-best-face helper; every other
change is a delta on prior-art surfaces that already carry the multi-
platform substrate.
**Date:** 2026-08-28.

The fusion model is **corroboration by independent recognizers**:
legs on DIFFERENT physical cameras naming the same person are
independent by construction — they stamp HIGH; two legs on the SAME
physical camera via different engines (Protect + Frigate) share the
video stream and stamp a bounded BOOST; a single leg stamps MEDIUM;
two or more different names abstain.

---

## 0. Falsifiable invariant

**Sign convention (single, canonical).** `delta = (T_face - T_crossing)`
in seconds. `delta < 0` means the face was seen BEFORE the crossing;
`delta > 0` means AFTER. All windows in this plan use this convention.
Probe medians under this convention: **exits `delta ≈ -53s`** (face
leads the crossing) and **entries `delta ≈ +14s`** (face trails the
crossing). Both medians sit inside the intervals below.

> **INV-EGRESS-ID.** No row in `person_entry_exit_events` is stamped
> with a non-NULL `person_id` unless, at the crossing timestamp `T_x`,
> there exists at least one **named** face leg (Frigate
> `_last_recognized_face[_2]` OR the Protect bridge entity from §D1,
> which publishes under the already-discovered `_face_recognized`
> suffix) on a camera in the **evaluation leg-set** — the UNION of
> the egress/door camera's own stem AND
> `_get_interior_cameras_near(egress_camera_id)` — whose `last_changed`
> yields a `delta` inside the direction-keyed window:
> `exit  ∈ [-FACE_MATCH_EXIT_WINDOW_BEFORE_S, +FACE_MATCH_EXIT_WINDOW_AFTER_S]` = `[-180s, +30s]` (median `-53s` inside),
> `entry ∈ [-FACE_MATCH_ENTRY_WINDOW_BEFORE_S, +FACE_MATCH_ENTRY_WINDOW_AFTER_S]` = `[-60s, +300s]` (median `+14s` inside),
> AND the agreement classification of the set of in-window canonical
> slugs is not `CENSUS_AGREEMENT_DISAGREE`. Whenever two or more
> distinct canonical slugs are in-window (regardless of temporal
> separation), the row emits `person_id=None`. The DB `confidence`
> column and the bus `confidence` field keep their pre-cycle
> crossing/direction semantics. Identity confidence is carried
> SEPARATELY in the D3 observability attrs and takes exactly one of
> three values:
> `CONFIDENCE_HIGH (0.9)` when two or more legs naming the same
> canonical slug come from DIFFERENT physical cameras (predicate:
> distinct `FaceLeg.base_stem` — the stem IS the physical-camera
> identity, since all legs enumerated for one camera share it);
> `FACE_MATCH_CORRELATED_BOOST (0.75)` when two or more legs naming
> the same slug come from the SAME physical camera (same `base_stem`)
> via DIFFERENT engines (independent recognizers, shared stream —
> e.g. Protect + Frigate, or F1 + F2, on one camera);
> `CONFIDENCE_MEDIUM (0.6)` when exactly one leg names the slug.
> `person_id` is **advisory**: every consumer must accept NULL.

**Falsifiers.**
1. A row exists with `person_id=X` but no in-window named leg for
   that canonical slug on any camera in the evaluation leg-set (use
   the probe medians above to construct the fixture).
2. Two distinct canonical slugs appeared in-window and a row was
   still stamped rather than emitting NULL.
3. A row's `person_id` is a first-name string (`"Oji"`) rather than a
   canonical slug (`"oji_udezue"`) — namespace break with
   `person.<slug>`, census union, `ble_persons`, `identified_persons`.
4. Byte-diff on the no-name / abstain path versus pre-cycle behaviour
   (kill-switch OFF and all-abstain fixture); DB `confidence`
   bit-equal to pre-cycle heuristic.
5. Identity confidence is stamped as `CONFIDENCE_HIGH (0.9)` when the
   agreeing legs share `base_stem` (same physical camera) — HIGH is
   only reachable through a leg pair with DIFFERENT `base_stem`.
   Enforced directly by the independence predicate in D2b step 7
   (`_independent(a, b) = a.base_stem != b.base_stem`).

---

## 1. Institutional context verified

### 1.1 Prior-art surfaces the extension lands on (REUSED)

| Surface | file:line | Role |
|---|---|---|
| `DetectionLeg(entity_id, engine, integration, device_id)` | `camera_resolver.py:164-185` | Reference vocabulary for `engine` and `device_id`. `_resolve_face_legs` populates a `FaceLeg` with the same shape at the decision site. |
| `_FACE_SUFFIXES` includes `_face_recognized` (`:247`), `_smart_detect_face` (`:249`), `_last_recognized_face` (`:251`) | `camera_resolver.py:246-252` | The two NAME-carrying suffixes used by `_resolve_face_legs` are `_last_recognized_face` (Frigate) and `_face_recognized` (D1 Protect bridge). The DETECTION-only suffixes `_face_detected` / `_smart_detect_face` / `_ai_face` carry no name and are NOT enumerated by the accessor. |
| `_infer_integration(device)` and engine tagging | `camera_resolver.py:1013` (comment) + the `_infer_integration` helper on `CameraResolver` | Reused by `_resolve_face_legs` to tag each returned leg's `engine`. |
| `resolve_entity_to_device_id(entity_id)` | `CameraResolver` (used at `camera_resolver.py:931`) | Reused by `_resolve_face_legs` to populate `FaceLeg.device_id`. |
| `_resolve_face_entity_id(base_name) -> str \| None` | `camera_census.py:2615-2648` | UNCHANGED this cycle (Frigate-only, byte-identical to develop). Its five callers (§1.5) keep the single-best-face contract; Protect is reached only via the new `_resolve_face_legs`. |
| `_resolve_egress_face_identity(egress_camera_id, timestamp)` | `transit_validator.py:1120-1226` | D2b extends: evaluation leg-set union, direction-keyed asymmetric window, cross-camera + cross-engine corroboration classifier. |
| `_get_interior_cameras_near(egress_camera_id)` | `transit_validator.py:1346-1354` | Returns full interior ENTITY_IDs (not stems); D2b extracts stems before feeding the accessors. |
| `_extract_camera_stem(entity_id)` | `transit_validator.py:1114-1118` (delegates to `CameraIntegrationManager._extract_camera_stem`) | Normalizes both the egress cam and each interior entity to a base_name. |
| `_canonical_person_slug(name)` | `camera_census.py:2883-2950` | Every named hit is canonicalized before agreement grouping / veto / write / event. |
| `_is_egress_identity_enabled()` (kill-switch `switch.ura_name_people_at_doors`) | `camera_census.py:2964`, `switch.py:190`, `const.py:2172-2178` | Fresh-read gate; default ON. |
| `CONFIDENCE_HIGH = 0.9`, `CONFIDENCE_MEDIUM = 0.6`, `CONFIDENCE_LOW = 0.3` | `const.py:254-256` | The agreement→confidence ladder. Reused as-is. |
| `CENSUS_AGREEMENT_BOTH / _CLOSE / _DISAGREE / _SINGLE` (values `"both_agree" / "close" / "disagree" / "single_source"`) | `const.py:1431-1434` | Agreement-classification vocabulary D2b assigns per crossing. |
| `CONF_CENSUS_CROSS_VALIDATION` + `_cross_validate_platforms` | `const.py:1436` + census cross-validation helper | Pattern reference for grouping distinct evidence by canonical identity. |
| `FAILURE_MODE_PHYSICAL_INDEPENDENT / _CORRELATED_WIRELESS / _CORRELATED_BRIDGE / _UNKNOWN` | `const.py:488-499` | Independence taxonomy used by the classifier. Same-camera legs tag `FAILURE_MODE_CORRELATED_BRIDGE`; different-camera legs tag `FAILURE_MODE_PHYSICAL_INDEPENDENT`. |
| Person-tracker fail-OPEN `not_home` veto | `camera_census.py:3714-3731` (inside `_get_face_recognized_person_names` at `:3650`) | The canonical fail-OPEN veto D2b mirrors. |
| Sibling veto in D2b's existing body | `transit_validator.py:1211-1225` | Preserved unchanged. |
| Writer `log_entry_exit_event(person_id, event_type, direction, egress_camera, confidence)` | `database.py:3903-3928` | Signature and `confidence` semantics unchanged this cycle. |
| v5.9.0 census-observability-attrs pattern | `sensor.py:3609-3699` | D3 attaches new attrs to the same synchronous block; no I/O in the property. |
| Crossing dedup literal `5.0` | `transit_validator.py:1240` | Left as-is. Unrelated to identity independence. |

### 1.2 NEW (only what does not exist)

| Item | Rung | Justification |
|---|---|---|
| `_resolve_face_legs(self, base_name: str) -> list[FaceLeg]` on `PersonCensus` | Additive helper on the census, used ONLY by D2b | The old `_resolve_face_entity_id` returns a bare `entity_id` — engine and device_id are lost at the decision site. The accessor is additive; the five existing callers stay on the old helper. |
| `FaceLeg` dataclass (frozen) — fields `entity_id: str`, `engine: str`, `device_id: str \| None`, `base_stem: str`, `canonical_slug: str \| None`, `last_changed: datetime \| None`, `confidence: float \| None` | Dataclass adjacent to `_resolve_face_legs` | Carries the substrate the D2b classifier needs at the decision site. |
| `sensor.<cam>_face_recognized` per Protect-face-capable camera | HA entity, outside URA (bridge) | Publishes under the existing `_face_recognized` suffix (`camera_resolver.py:247`); no `camera_resolver.py` change is required. |
| `_egress_identity_outcomes: collections.deque[tuple[float, str]]` on `PersonCensus` (bounded, 24h prune) | In-memory rolling window on the census | Producer for `egress_identity_attach_rate_24h` and `egress_identity_ambiguity_rate_24h` inside the synchronous attrs property (`sensor.py:3609-3701` cannot await a DAO). See §D3 for the append rule + prune. |
| `FACE_MATCH_EXIT_WINDOW_BEFORE_S / _AFTER_S` | Module constant | Measured signed-lag geometry (probe median exit `delta = -53s`). |
| `FACE_MATCH_ENTRY_WINDOW_BEFORE_S / _AFTER_S` | Module constant | Measured signed-lag geometry (probe median entry `delta = +14s`). |
| `FACE_MATCH_ABSTAIN_MARGIN_S` | Module constant | Observability split only; does NOT gate the abstain decision. |
| `FACE_MATCH_MIN_CONFIDENCE` | Module constant | Per-leg admission floor. Byte-equal to `CONFIDENCE_MEDIUM (0.6)` is incidental — admission floor ≠ output level. |
| `FACE_MATCH_CORRELATED_BOOST` | Module constant | Bounded identity confidence for same-camera / cross-engine agreement; strictly `>0.6` and `<0.9`. |
| `CENSUS_AGREEMENT_DISABLED` | Module constant adjacent to `const.py:1431-1434`; value `"disabled"` | Distinct sentinel for kill-switch traffic so it does NOT pollute abstain/ambiguity observability (L3 discriminator). |
| Census observability keys (D3) | Attrs on existing sensor | See §D3. |
| Pre-deploy one-shot probe report | Analysis artifact under `docs/planning/artifacts/` | Measures per-camera named-face production rate over the last 7d; gates L1 (face rec has been observed down house-wide per `reference_egress_face_coverage_7pct_not_a_ceiling`). |

### 1.3 Prior planning + memory + design docs consulted

- `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` (canonical) — §1 platforms, §1.1 `_2` permanence, §4 architecture, §5 the JOIN, §2.3 Protect.
- Kanban card `EGRESS-IDENTITY-JOIN-GAP-1` (`docs/planning/kanban.data.yaml:29-138`).
- `docs/planning/PLANNING_paper_and_oss_fusion_library.md` — cross-modal doctrine.
- `docs/planning/AUDIT_census_identity_supersession_and_consumers.md` — downstream gaps (Non-goals).
- Memories: `reference_egress_face_coverage_7pct_not_a_ceiling.md`, `reference_frigate1_retired_2suffix_permanent.md`, `reference_architecture_map.md`, `reference_code_tracing_methodology.md`, `feedback_coincidental_equality_masks_concept_split.md`, `feedback_verify_claim_types_not_felt_uncertainty.md`.

### 1.4 Code locations surveyed end-to-end

- `transit_validator.py:1080-1360`
- `camera_census.py:2600-2700, 2860-3060, 3340-3400, 3640-3740`
- `domain_coordinators/presence.py:4560-4660`
- `camera_resolver.py:115-270, 880-1140`
- `database.py:790-810, 3900-3960`
- `sensor.py:3580-3700`
- `const.py:250-260, 485-500, 1425-1440, 2140-2200`
- `switch.py:180-210`

### 1.5 Producer / consumer discipline

**Producer arithmetic.** D2b assembles the evaluation leg-set (egress-
cam stem ∪ interior-adjacent cameras), calls `_resolve_face_legs(stem)`
for each stem, filters to in-window named legs above the floor,
canonicalizes each hit, then classifies agreement per §2 D2b step 6/7.

**Dependency health.** Frigate face-rec engine (tuning history mixed;
face rec has been observed down house-wide) and Protect Known-Face
enrollment (operator-owned, parallel). The pre-deploy probe measures
current production rate before L1 is evaluated so "producer dead" is
distinguishable from "fusion broken."

**All five callers of the OLD `_resolve_face_entity_id`
(grep-verified, D2a-signature-safe).**

1. `camera_census.py:2783` — fresh-set / face-freshness path.
2. `camera_census.py:2818` — fresh-set / face-freshness path.
3. `camera_census.py:3369` — CENSUS-ACCURACY-1 D2 face-recognition path.
4. `transit_validator.py:1163` — D2b's own site; this cycle migrates it to `_resolve_face_legs`. The old helper stays available.
5. `domain_coordinators/presence.py:4623` — face-arrival accelerator. Reads the returned entity's `state.state` raw on a 30s window and fires `_handle_face_arrival` (`:4649`). **Verified safe:** D2a keeps `str -> str | None`; presence's raw-read is unaffected. Does not consume `_resolve_face_legs`.

**Egress-side consumer sites (grep-verified).**

1. `ura_person_egress_event` payload — `transit_validator.py:1284-1290`.
2. Writer `database.log_entry_exit_event` — `:1336`, `database.py:3903`.
3. Census union feed `register_egress_face` / `evict_egress_face` — `:1321-1323`, `camera_census.py:2964+`.
4. Downstream 6.0.0 consumers — deferred (Non-goals). All accept NULL.

---

## 2. Deliverables

### D1 — Protect face-name bridge entity (outside URA)

A small HA-side poll component queries the Protect events API
(`protect_list_smart_detections` / `protect_list_events` /
`protect_get_event`) on a bounded lookback (~30s) at ~5s cadence and
publishes one HA entity per Protect-face-capable camera:

- `sensor.<cam>_face_recognized` — suffix already present in
  `_FACE_SUFFIXES` at `camera_resolver.py:247`; no resolver change.
- `state` = `recognized_person_name` (empty string on unnamed
  cluster; mirrors Frigate `_last_recognized_face` semantics).
- Attributes: `person_id`, `confidence` (0.0–1.0), `event_start`,
  `event_end`, `camera_id`, `engine = "protect"`.

URA reads this entity via `hass.states.get` only; it never imports or
calls a Protect API at runtime.

### D2a — Keep `_resolve_face_entity_id` unchanged; add `_resolve_face_legs` (new accessor)

**File:** `camera_census.py:2615-2648` — the old helper is UNTOUCHED — plus a new sibling method.

**Old helper (`_resolve_face_entity_id`) — UNCHANGED from develop.** Its
candidate set stays exactly
`(sensor.<base>_last_recognized_face, sensor.<base>_last_recognized_face_2)`
(Frigate only) and its five existing callers (§1.5) keep their
single-best-face contract byte-for-byte. It is deliberately NOT
widened to see the Protect `_face_recognized` leg: those five callers
include the guest-count path (`_count_unrecognized_interior_faces`),
the corroboration bundle, and the presence pre-arrival accelerator
(`presence.py:4623`), and none of them is behind this cycle's kill
switch — feeding Protect names into them would change trust decisions
on surfaces this cycle does not own. **All Protect coupling lives in
exactly one place: the new `_resolve_face_legs` accessor, which is
kill-switch-gated via D2b.** (A future, separately-gated cycle may
teach the census fresh-set to consume Protect names; that is a
non-goal here.)

**New accessor (`_resolve_face_legs`).**

```
@dataclass(frozen=True)
class FaceLeg:
    entity_id: str
    engine: str                 # matches DetectionLeg.engine vocabulary
    device_id: str | None
    base_stem: str
    canonical_slug: str | None  # populated post-state-read
    last_changed: datetime | None
    confidence: float | None

def _resolve_face_legs(self, base_name: str) -> list[FaceLeg]: ...
```

**Enumeration approach.** The accessor does NOT use
`resolve_detection_legs` — that helper filters to
`binary_sensor.` entities only (`camera_resolver.py:993`), and the
NAME-carrying face legs are `sensor.*`, not `binary_sensor.*`. The
accessor enumerates the NAME-carrying suffixes directly:

- `sensor.<base>_last_recognized_face` and its `_2` variant — Frigate.
- `sensor.<base>_face_recognized` and its `_2` variant — Protect via
  the D1 bridge.

The DETECTION-only face suffixes `_face_detected`, `_smart_detect_face`,
`_ai_face` carry no recognized name and are NOT enumerated here (they
would produce `canonical_slug is None` and be dropped downstream).

For each enumerated entity_id present in `hass.states`:
- Read `state`, `last_changed`, and the optional `confidence` attr.
- Drop when `state` is sentinel (`unavailable / unknown / empty / none / no_match`).
- Drop when `confidence is not None and confidence < FACE_MATCH_MIN_CONFIDENCE`.
- Populate `canonical_slug` via `_canonical_person_slug(state)`.
- Populate `device_id` via `CameraResolver.resolve_entity_to_device_id(entity_id)`.
- Populate `engine` via the CameraResolver's `_infer_integration` /
  engine-tagging path (the same source used by `resolve_detection_legs`
  at `camera_resolver.py:1013` context). The `_2` variant maps to the
  disambiguated engine tag (e.g. `frigate2`, `protect2`) mirroring the
  DetectionLeg convention at `camera_resolver.py:174-176`.
- `base_stem` is `base_name`.

Return the populated `FaceLeg` list (may be empty). On any lookup
error the accessor returns `[]` and increments
`_face_lookup_missing_count` (mirrors the old helper's telemetry).
The accessor is used ONLY by D2b in this cycle.

### D2b — Extend `_resolve_egress_face_identity` with leg-set union, signed-lag window, and cross-camera + cross-engine corroboration

**File:** `transit_validator.py:1120-1226`; sole call site updated at
`:1279-1290`.

**Signature.**
```
_resolve_egress_face_identity(
    egress_camera_id: str,
    timestamp: datetime,
    direction: str,
) -> tuple[str | None, float | None, str]
```
Returns `(canonical_slug_or_None, identity_confidence_or_None, agreement_class)`
where `agreement_class ∈ {CENSUS_AGREEMENT_BOTH, CENSUS_AGREEMENT_SINGLE, CENSUS_AGREEMENT_DISAGREE, CENSUS_AGREEMENT_DISABLED}`
(`CENSUS_AGREEMENT_CLOSE` reserved). The DB `confidence` column and
the bus `confidence` field continue to carry the pre-cycle platforms-
fired crossing/direction value (`transit_validator.py:1266-1272`)
unmodified — no bus-vs-DB split.

**Algorithm.**

1. **Kill-switch check.** If `_is_egress_identity_enabled()` is False,
   return `(None, None, CENSUS_AGREEMENT_DISABLED)`. Canonicalization
   namespace and `not_home` veto (`transit_validator.py:1211-1225`,
   which mirrors the canonical fail-OPEN veto in
   `_get_face_recognized_person_names` at `camera_census.py:3714-3731`)
   preserved.
2. **Assemble the evaluation leg-set (stems).** UNION of:
   - the egress camera's own stem via
     `self._extract_camera_stem(egress_camera_id)` (`transit_validator.py:1114-1118`), and
   - each entity from `self._get_interior_cameras_near(egress_camera_id)`
     run through `_extract_camera_stem` — the helper returns full
     ENTITY_IDs, not stems.
   Deduplicate stems.
3. **Per stem, call `census._resolve_face_legs(stem)`** to obtain a
   `list[FaceLeg]` with engine + device_id + canonical_slug + timing +
   optional confidence populated.
4. **Direction-keyed signed-lag window.** For each leg, compute
   `delta = (last_changed - timestamp).total_seconds()`.
   - `exit`   → `delta ∈ [-FACE_MATCH_EXIT_WINDOW_BEFORE_S, +FACE_MATCH_EXIT_WINDOW_AFTER_S]` = `[-180, +30]` (probe median `-53s`).
   - `entry`  → `delta ∈ [-FACE_MATCH_ENTRY_WINDOW_BEFORE_S, +FACE_MATCH_ENTRY_WINDOW_AFTER_S]` = `[-60, +300]` (probe median `+14s`).
   - `ambiguous` → return `(None, None, CENSUS_AGREEMENT_DISAGREE)`
     immediately (matches the DB-write gate at `:1332`).
5. **Drop** legs with `canonical_slug is None` or
   `confidence is not None and confidence < FACE_MATCH_MIN_CONFIDENCE`
   (re-check for defence-in-depth). Let `H` be the surviving in-window
   legs.
6. **Agreement classification.** Let
   `S = { h.canonical_slug for h in H }`.
   - `|S| ≥ 2` → **`CENSUS_AGREEMENT_DISAGREE`** → return
     `(None, None, DISAGREE)` regardless of temporal separation.
     Abstain and ambiguity are one unified 24h rate off
     `_egress_identity_outcomes` (the `"ambiguous"` outcome);
     `FACE_MATCH_ABSTAIN_MARGIN_S` affects observability granularity
     only, never the decision.
   - `|S| == 1` — let `s` be the sole slug and
     `Hs = [h ∈ H : h.canonical_slug == s]`.
     - If any pair `(h_i, h_j) ∈ Hs × Hs` satisfies the **DIFFERENT-
       CAMERA predicate** in step 7 → `(s, CONFIDENCE_HIGH, CENSUS_AGREEMENT_BOTH)`.
     - Else if `|Hs| ≥ 2` (all pairs share the same physical camera) →
       `(s, FACE_MATCH_CORRELATED_BOOST, CENSUS_AGREEMENT_BOTH)`. The
       boost (0.75) is strictly less than `CONFIDENCE_HIGH` (0.9) —
       correlated agreement never emits HIGH (falsifier #5).
     - Else (`|Hs| == 1`) → `(s, CONFIDENCE_MEDIUM, CENSUS_AGREEMENT_SINGLE)`.
7. **Independence predicate (base_stem only, time-independent).** Two
   legs `h_i`, `h_j` are **INDEPENDENT** iff their physical cameras
   differ: `_independent(h_i, h_j) = h_i.base_stem != h_j.base_stem`.

   `base_stem` is the physical-camera identity — every leg enumerated
   for one camera shares it, so Protect + Frigate (or F1 + F2) on ONE
   physical camera share a stem and are CORRELATED, while two DIFFERENT
   cameras naming the same person are INDEPENDENT. `device_id` is NOT
   used for independence: two engines on one physical camera surface as
   two DIFFERENT HA devices (distinct `device_id`), so a device-based
   predicate would wrongly score them independent → false HIGH. The
   predicate uses no time-proximity clause and no same-engine clause.
   This makes falsifier #5 a direct consequence: HIGH is unreachable
   unless at least one pair spans different `base_stem`. (`FaceLeg`
   still carries `device_id`, but only for observability /
   `contributor_engines`, never for the independence decision.)
8. **Emit and write.** The caller at `transit_validator.py:1279-1344`:
   - Sets `person_id` on the `ura_person_egress_event` payload to the
     returned slug (may be `None`).
   - Passes the pre-cycle `confidence` from `:1266-1272` UNMODIFIED to
     `database.log_entry_exit_event(...)` and the bus payload.
   - Publishes identity confidence + `agreement_class` +
     `contributor_engines` (list of engine tags in the agreeing set)
     into D3 attrs.
   - Appends one entry `(now_ts, outcome)` to
     `census._egress_identity_outcomes` where
     `outcome ∈ {"attached", "ambiguous", "no_leg", "disabled"}`
     Outcome label per crossing, one of:
     `"attached"` (returned slug non-None);
     `"ambiguous"` (identity DISAGREE — ≥2 distinct in-window slugs);
     `"direction_ambiguous"` (crossing direction itself was ambiguous —
     no leg was read; excluded from the rate denominators);
     `"vetoed"` (a named leg existed but the `not_home` veto rejected
     it — distinct from `no_leg`);
     `"no_leg"` (step 6 reached with `|H| == 0`);
     `"disabled"` (kill-switch short-circuit; excluded from the rate
     math). See §D3.
   - Census `register_egress_face` / `evict_egress_face` gating at
     `:1316-1329` is unchanged.

### D3 — Observability on the existing census sensor

**File:** `sensor.py:3609-3699`. Add to the same synchronous attrs
block (no I/O; no `await`):

- `egress_identity_attach_rate_24h` and
  `egress_identity_ambiguity_rate_24h`. **Producer.**
  `PersonCensus._egress_identity_outcomes` is a bounded
  `collections.deque[tuple[float, str]]` of `(monotonic_or_wall_ts, outcome)`.
  D2b appends one entry per crossing on the post-decision path
  (§D2b step 8). **Prune-on-append:** every append pops from the left
  while `now - ts > 24h`. **Rate math (read-only in the sensor) ALSO
  filters by the 24h cutoff at read time** — the reader does not trust
  prune-on-append alone, so an idle producer never divides over stale
  entries:
  - Denominator = count of entries within 24h whose `outcome` is NOT
    in `{"disabled", "direction_ambiguous"}` (these never involved an
    identity decision, so they cannot dilute a producer-health rate).
  - `attach_rate_24h = count("attached") / denominator`
    (returns `0.0` when denominator is 0).
  - `ambiguity_rate_24h = count("ambiguous") / denominator`.
  Cached values are recomputed inside the attrs property from the
  deque snapshot — no `await`, no DAO call.
- `egress_identity_abstain_rate_24h` — DERIVED from the same
  `_egress_identity_outcomes` deque as a 24h-windowed rate
  (`count("ambiguous") / denominator`, identical denominator rule).
  The earlier standalone int counter with a UTC-day rollover was
  removed (it under-reset on zero-abstain days — stale-data class #7);
  all three rates now share one deque and one cutoff.
- `egress_identity_last_attach = {person, camera, identity_confidence, signed_lag_delta_seconds, direction, agreement_class, contributor_engines}` — most recent successful attach; `contributor_engines` lists engine tags so L5 is evaluable from the sensor alone.
- `egress_identity_agreement_class_last` — last emitted class
  including `DISABLED / BOTH / SINGLE / DISAGREE`.
- `egress_identity_correlated_boost_count_24h` — count of BOTH cases
  stamped at `FACE_MATCH_CORRELATED_BOOST` rather than HIGH.

No new sensor; failures degrade silently under the existing
`try / except` at `:3698-3699`.

---

## 3. Numbers on the knob ladder

| Constant | File | Rung | Default | Why |
|---|---|---|---|---|
| `FACE_MATCH_EXIT_WINDOW_BEFORE_S` | `const.py` | Module (review-required) | `180` | Exits face-lead (probe median `delta = -53s`); accepts up to 180s before. |
| `FACE_MATCH_EXIT_WINDOW_AFTER_S` | `const.py` | Module | `30` | Small tail for post-exit recognitions. |
| `FACE_MATCH_ENTRY_WINDOW_BEFORE_S` | `const.py` | Module | `60` | Small lead for pre-entry recognitions. |
| `FACE_MATCH_ENTRY_WINDOW_AFTER_S` | `const.py` | Module | `300` | Entries face-trail (probe median `delta = +14s`); accepts up to 300s after. |
| `FACE_MATCH_ABSTAIN_MARGIN_S` | `const.py` | Module | `15` | Observability split only; does NOT gate the abstain decision. |
| `FACE_MATCH_MIN_CONFIDENCE` | `const.py` | Module | `0.60` | Per-leg admission floor. Byte-equal to `CONFIDENCE_MEDIUM` is incidental — admission floor ≠ output level. |
| `FACE_MATCH_CORRELATED_BOOST` | `const.py` | Module | `0.75` | Bounded identity confidence for same-camera / cross-engine agreement; strictly `>0.6` and `<0.9`. |
| `CENSUS_AGREEMENT_DISABLED` | `const.py` (adjacent to `:1431-1434`) | Module | value `"disabled"` | Distinct sentinel for kill-switch traffic; excluded from abstain/ambiguity observability. |

Reused as-is: `CONFIDENCE_HIGH = 0.9`, `CONFIDENCE_MEDIUM = 0.6`,
`CONFIDENCE_LOW = 0.3` (`const.py:254-256`);
`CENSUS_AGREEMENT_BOTH / _CLOSE / _DISAGREE / _SINGLE` (`:1431-1434`);
`FAILURE_MODE_*` (`:488-499`);
`FACE_MATCH_WINDOW_S = 60` (`:2162`, retained for its existing census
fresh-set consumer; the new direction-keyed constants take precedence
inside `_resolve_egress_face_identity`).

Kill-switch semantics: `switch.ura_name_people_at_doors` OFF makes
`_resolve_egress_face_identity` short-circuit to
`(None, None, CENSUS_AGREEMENT_DISABLED)` — byte-identity on the
no-name path (falsifier #4).

---

## 4. Acceptance criteria — discriminating

### Pre-deploy probe (gates L1)

A one-shot read-only probe over the last 7d of the HA recorder counts
named `_last_recognized_face[_2]` / `_face_recognized[_2]` state
transitions per interior + egress camera. Report committed under
`docs/planning/artifacts/PROBE_face_production_2026-08.md` and gates
L1: the report's aggregate interior named rate (per day, per camera)
is the `probe_floor` used by L1.

### D1 — Protect bridge

- **Verify:** at least one `sensor.<cam>_face_recognized` published by
  the D1 bridge exists post-deploy and, for at least one camera, its
  state updates within ~60s of a Protect event carrying
  `recognized_person_name`.
- **Verify:** URA imports no Protect API — `grep -R "protect_list_\|unifi_protect\." custom_components/universal_room_automation/` returns nothing new.
- **Live:** entity is readable via `hass.states.get`; state is a
  recognized name (or empty string), never `unavailable` while
  Protect is up.

### D2a — `_resolve_face_entity_id` (UNCHANGED) + `_resolve_face_legs`

- **Test (old-helper UNCHANGED — no Protect):** with a Protect
  `_face_recognized` leg named and no Frigate leg, the old
  `_resolve_face_entity_id(base_name)` returns `None` (it is Frigate-
  only, byte-identical to develop). Guards against re-widening the
  helper and leaking Protect into its five callers (guest-count,
  corroboration bundle, `presence.py:4623` pre-arrival).
- **Test (old-helper contract preserved):** the five callers (three
  in `camera_census.py:2783, :2818, :3369`; one in
  `transit_validator.py:1163`; one in
  `domain_coordinators/presence.py:4623`) invoke
  `_resolve_face_entity_id(base_name)` and receive `str | None`
  unchanged.
- **Test (`_resolve_face_legs` multi-engine enumeration):** fixture
  with a physical camera exposing both `sensor.<base>_last_recognized_face`
  (Frigate, named) and `sensor.<base>_face_recognized` (Protect,
  named) → accessor returns TWO `FaceLeg` entries with
  `engine ∈ {"frigate", "protect"}` and the SAME `base_stem` (one
  physical camera). Both entries carry populated `canonical_slug`.
- **Test (`_resolve_face_legs` `_2` engine tagging):** an entity_id
  ending `_last_recognized_face_2` returns a FaceLeg with
  `engine == "frigate2"` (or the disambiguated equivalent), matching
  the DetectionLeg vocabulary at `camera_resolver.py:174-176`.
- **Test (`_resolve_face_legs` sentinel / floor drop):** legs whose
  state is sentinel OR whose confidence attr is below the floor are
  excluded from the returned list.
- **Test (`_resolve_face_legs` DETECTION-only suffix ignored):** an
  entity_id ending `_face_detected` / `_smart_detect_face` /
  `_ai_face` is NOT enumerated by the accessor even if present.

### D2b — `_resolve_egress_face_identity` (cross-camera + cross-engine corroboration)

- **Test (HIGH via different cameras, distant in time):** same
  canonical slug on legs from two DIFFERENT `base_stem` cameras in
  the leg-set, at deltas `-100s` and `-15s` (both inside the exit
  window, separated by 85s) → returns
  `(slug, CONFIDENCE_HIGH, CENSUS_AGREEMENT_BOTH)`;
  `_last_attach.identity_confidence == 0.9`;
  `_last_attach.contributor_engines` covers ≥2 distinct cameras.
  Proves distance-in-time does NOT demote a cross-camera pair, and
  (mutation-anchor) that a base_stem-blind predicate would fail.
- **Test (BOOST via same camera, different engines, ANY in-window
  deltas):** same canonical slug on TWO legs sharing `base_stem` via
  engines `frigate` and `protect` (distinct `device_id`s — the exact
  case a device-based predicate would misclassify), at deltas `-120s`
  and `+20s` (both inside the exit window; separation 140s) → returns
  `(slug, FACE_MATCH_CORRELATED_BOOST, CENSUS_AGREEMENT_BOTH)`;
  identity_confidence `== 0.75`;
  `_correlated_boost_count_24h` increments. Proves BOOST does NOT
  require time-proximity and is driven by shared `base_stem`.
- **Test (BOOST via same camera, same engine `_2`):** two legs sharing
  `base_stem` (e.g. `frigate` + `frigate2` on the same base_name) →
  `(slug, FACE_MATCH_CORRELATED_BOOST, CENSUS_AGREEMENT_BOTH)`.
- **Test (SINGLE → MEDIUM):** exactly one leg names the slug in-window
  → `(slug, CONFIDENCE_MEDIUM, CENSUS_AGREEMENT_SINGLE)`.
- **Test (DISAGREE close → abstain, deque outcome):** two distinct
  canonical slugs in-window within `FACE_MATCH_ABSTAIN_MARGIN_S` →
  `(None, None, CENSUS_AGREEMENT_DISAGREE)` AND the crossing records
  the `"ambiguous"` deque outcome (abstain and ambiguity are one
  unified rate off `_egress_identity_outcomes`).
- **Test (DISAGREE separated → still abstain, deque outcome):** two
  distinct slugs in-window separated by MORE than the margin → still
  `(None, None, CENSUS_AGREEMENT_DISAGREE)` and still the `"ambiguous"`
  outcome. Proves strict abstain (judgement-call #7) never picks a
  winner regardless of temporal separation; `FACE_MATCH_ABSTAIN_MARGIN_S`
  affects observability granularity only, not the decision.
- **Test (window signs anchored to probe medians):** exit face at
  `delta == -53s` accepted; exit face at `delta == -181s` rejected;
  entry face at `+14s` accepted; entry face at `+301s` rejected.
- **Test (leg-set union includes egress cam):** a fixture where the
  ONLY named leg is on the egress/door cam's own stem produces a
  SINGLE stamp, not a miss.
- **Test (base_stem independence, device_id irrelevant):** two legs on
  DIFFERENT `base_stem` but IDENTICAL `device_id` → treated as
  DIFFERENT-camera → HIGH (proves the predicate ignores `device_id`);
  two legs on the SAME `base_stem` but DIFFERENT `device_id` →
  treated as SAME-camera → BOOST (0.75). This pair is the direct
  guard against a device-based predicate regressing back in.
- **Test (INV byte-identity):**
  1. Kill-switch OFF → resolver returns
     `(None, None, CENSUS_AGREEMENT_DISABLED)` before any leg read;
     `ura_person_egress_event.person_id` is `None`; DB row
     `person_id IS NULL`; DB `confidence` bit-equal to pre-cycle
     platforms-fired value. `_abstain_rate_24h` and
     `_ambiguity_rate_24h` do NOT increment. The
     `_egress_identity_outcomes` deque records `"disabled"` — this
     class is excluded from `attach_rate_24h` /
     `ambiguity_rate_24h` denominators.
  2. All-abstain fixture (kill-switch ON) → row shape identical to
     (1) except `agreement_class == DISAGREE` and abstain observability
     increments as specified.
- **Test (namespace):** every non-NULL `person_id` matches
  `^[a-z0-9_]+$` AND equals a configured `person.<slug>` known to
  the census.
- **Test (advisory consumer):** a downstream test double receiving
  `person_id=None` continues to function.

### D3 — Observability

- **Test (deque prune):** append 100 synthetic outcomes at
  `now - 25h` and 5 at `now`; the sensor property reports
  `attach_rate_24h` computed off 5 entries only.
- **Test (attrs property is sync):** `pytest` reads the census-sensor
  extra_state_attributes without any awaitable in-play (asserts no
  `await` in the property body).
- **Live:** `egress_identity_last_attach` populated within ~1
  crossing; carries `agreement_class`, `identity_confidence`,
  `contributor_engines`.
- **Live:** `egress_identity_agreement_class_last` reports one of
  `BOTH / SINGLE / DISAGREE / DISABLED`.

### Live-validation table (write back into the README)

| # | Criterion | Method | Expected |
|---|---|---|---|
| L1 | Producer alive under strict abstain | read `egress_identity_attach_rate_24h` AND `egress_identity_ambiguity_rate_24h` 24h post-deploy | **PASS** = `attach_rate_24h ≥ probe_floor` OR `(attach_rate_24h + ambiguity_rate_24h)` rises materially above 0 within 24h (a live-but-ambiguous producer under all-interior adjacency is expected common per the ~28% ambiguity probe cap; producer-alive is any signal it has legs to fuse). **FAIL (producer dead)** = both flat at 0 for 24h despite non-zero egress crossings. |
| L2 | Namespace invariant | `SELECT DISTINCT person_id FROM person_entry_exit_events WHERE timestamp > T_deploy` | all rows NULL or a canonical slug in `tracked_persons` |
| L3 | Abstains fire organically AND kill-switch is excluded | `egress_identity_abstain_rate_24h` + audit of `_agreement_class_last` history | abstain non-zero within a week; zero abstain increment on kill-switch OFF traffic |
| L4 | INV byte-identity on kill-switch OFF | flip switch off, force a crossing | row inserted with `person_id IS NULL`; DB `confidence` bit-equal to pre-cycle heuristic; `agreement_class == DISABLED` |
| L5 | Corroboration model is intact | for each `_last_attach` with `identity_confidence == 0.9`, verify `agreement_class == CENSUS_AGREEMENT_BOTH` AND `contributor_engines` covers ≥2 DIFFERENT physical cameras. Any BOOST (0.75) attach carries two engines on the SAME camera in `contributor_engines`. Keyed on `agreement_class` + `contributor_engines`, not on the number alone. | no `0.9` attach whose contributors are all on one camera; no BOOST attach that spans two cameras |

---

## 5. Non-goals

- URA runtime Protect-API client — coupling lives in the D1 bridge.
- A new fusion coordinator or resolver class — the accessor is
  additive on the census.
- Wiring downstream 6.0.0 consumers (guest gate, arrival/departure,
  egress-keyed identity policy) — separate follow-on cards.
- Blocking on Protect Known-Face enrollment.
- Schema change to add face-side / identity confidence to
  `person_entry_exit_events` — deferred. The DB `confidence` column
  keeps its pre-cycle crossing/direction semantics.
- Adjacency-mapping refinement in `_get_interior_cameras_near` —
  separate card. Direction-keyed windows discriminate temporally in
  the meantime.
- Widening `_resolve_face_entity_id` signature — kept intact.
- A template sensor to surface Frigate face confidence as an
  attribute — deferred.
- Refactoring the `5.0` crossing-dedup literal at
  `transit_validator.py:1240` — unrelated to identity independence.
- Extending `_FAMILY_SUFFIXES` with a `"face"` family — not needed;
  `resolve_detection_legs` filters to `binary_sensor.` only and face
  NAME legs are `sensor.*`.

---

## 6. Review protocol (Tier 2-DB)

1. **Plan review** (one adversarial pass, before build dispatch).
2. **Three framing-disjoint code reviews** (post-build):
   - **A — data integrity + old-helper stability.** Old helper
     byte-identical to develop (Frigate-only, NOT widened);
     canonicalization invariant
     preserved; `_face_lookup_missing_count` still increments on real
     misses only; DB writer signature and `confidence` semantics
     unchanged; INV byte-identity under kill-switch OFF proven by
     mutation-restored source drill; all five old-helper callers
     (§1.5) unaffected.
   - **B — corroboration classifier + leg-set union + independence
     predicate + window geometry.** Every direction branch audited;
     sign convention `delta = T_face - T_crossing` applied
     consistently; classifier correct at extremes (`|S|==1` with 3+
     hits mixing same/different device; `|S|==2` at margin boundary;
     egress-cam-only fixture stamps SINGLE; same-`base_stem`
     Protect+Frigate stamps BOOST not HIGH at ANY in-window
     separation; different-`base_stem` pair stamps HIGH at ANY
     in-window separation; `device_id` never affects the decision;
     census register / evict gating unaffected on abstain; restart
     behaviour (no persisted state).
   - **C — new surfaces + test fixture authority.**
     `_resolve_face_legs` fixture built from real registry shapes
     (not hand-typed); D1 bridge entity contract shape matches a real
     Protect events-API record; D3 attrs round-trip through the
     existing SYNCHRONOUS attrs property (no `await`); deque prune
     rule verified; `CENSUS_AGREEMENT_DISABLED` correctly excluded
     from denominators.
3. **Orchestrator independent verification** — re-grep every
   `_resolve_face_entity_id` caller (must be 5) and every
   `_resolve_face_legs` caller (must be 1, D2b only); re-run a
   mutation-restored source drill on the D2b agreement + independence
   predicate before ship.
4. **Live validation (Review D)** — post-restart, populate the L1–L5
   table back into `docs/readmes/README_v<version>.md`.

---

## 7. Files touched

| File | Change |
|---|---|
| `const.py` | Add 8 new constants (§3). Retain `FACE_MATCH_WINDOW_S`, `CONFIDENCE_*`, `CENSUS_AGREEMENT_*`, `FAILURE_MODE_*` — all reused. |
| `camera_census.py` | `_resolve_face_entity_id` UNCHANGED (Frigate-only). Add `FaceLeg` dataclass + `_resolve_face_legs(base_name) -> list[FaceLeg]` accessor (enumerates NAME-carrying suffixes directly on `sensor.*`, tags engine via `_infer_integration`, resolves `device_id` via `resolve_entity_to_device_id` — for observability only, not independence). Add `_egress_identity_outcomes` bounded deque + append/prune. |
| `transit_validator.py` | Extend `_resolve_egress_face_identity` (D2b) with leg-set union, `_extract_camera_stem` normalization, `_resolve_face_legs` iteration, direction-keyed signed-lag window, agreement classifier, device-only independence predicate, tuple return. Update sole call site at `:1279-1290` to consume the tuple; publish identity_confidence + agreement_class + contributor_engines into D3 attrs; append outcome into the census deque. DB `log_entry_exit_event` call passes the pre-cycle `confidence` UNMODIFIED. |
| `sensor.py` | Add 6 attrs to the existing SYNCHRONOUS census attrs block (D3). Attach/ambiguity rates computed from the census deque; abstain / boost counters read from census counters. |
| `docs/planning/artifacts/PROBE_face_production_2026-08.md` | Pre-deploy one-shot probe report; gates L1. |
| (HA-side, outside URA) | D1 poll bridge publishing `sensor.<cam>_face_recognized`. |

**No changes** to `camera_resolver.py`, `database.py` schema,
`config_flow.py`, `switch.py`, or `__init__.py`.

---

## 8. Rollback

- Kill-switch OFF restores INV byte-identity;
  `CENSUS_AGREEMENT_DISABLED` keeps abstain observability clean.
- No schema migration.
- Disabling the D1 bridge quietly removes Protect legs from the
  accessor's output; D2b degrades to Frigate-only SINGLE → MEDIUM +
  same-Frigate BOOST; cross-engine BOOST stops firing; cross-camera
  HIGH continues wherever ≥2 different `base_stem` Frigate cameras
  recognize.
