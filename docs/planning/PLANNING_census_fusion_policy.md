# PLANNING — Census Fusion Policy (divergence-aware confidence)

**Cycle date:** 2026-08-01
**Branch (proposed):** `feature/census-fusion-policy`
**Tier:** **Tier 2-DB** — payload/confidence semantics change on a shared primitive (`_cross_validate_platforms`) consumed by presence coordinator ripple (census_count → guest determination → comfort-fan away-veto laundering). Three framing-disjoint reviews + live validation.
**Scope guard (verbatim operator):** *policy only, no resolver work, no schema generalization.* CameraResolver abstraction, `source_counts` JSON generalization, and per-camera fusion sensors are the SEPARATE fusion cycle (`docs/planning/PLANNING_room_camera_fusion.md`) — do not smuggle them in here. Reference §4 for parked items.

Context (do not re-litigate): read the 2026-08-01 amendments in `PLANNING_room_camera_fusion.md` — especially "the gap is the FUSION POLICY, not the wiring." Today's playroom phantom (3rd instance) logged `frigate_count=1, unifi_count=0, source_agreement='close'`; Protect's correct zero was captured and ignored by max-wins.

---

## 1. Institutional context verified

### 1.1 Files read
- `custom_components/universal_room_automation/camera_census.py`
  - dataclass `CensusZoneResult` (l.143–145) — `source_agreement`, `frigate_count`, `unifi_count` columns.
  - `_calculate_house_census` merge (l.1124–1152) — dispatches to `_cross_validate_platforms` when both platforms available.
  - **`_cross_validate_platforms` (l.1309–1342)** — the exact site. Current behavior on divergence:
    - `frigate>0 AND binary==0` → returns `(frigate_count, CENSUS_AGREEMENT_CLOSE)` (l.1332–1334). **This is the max-wins bug the playroom phantom exploited.**
    - `frigate==0 AND binary>0` → symmetric (l.1336–1338).
  - `_cross_correlate_persons` (l.1348–1420) — maps `CLOSE → CENSUS_CONFIDENCE_MEDIUM` (l.1399–1400); `DISAGREE → LOW` (l.1401–1402). MEDIUM currently passes downstream guest gates; LOW does not (verify at build).
  - `_is_cross_validation_enabled` (l.1428–1435) — reads `CONF_CENSUS_CROSS_VALIDATION`.
- `custom_components/universal_room_automation/const.py`
  - `CENSUS_AGREEMENT_{BOTH,CLOSE,DISAGREE,SINGLE}` (l.1075–1078). REUSED.
  - `CENSUS_CONFIDENCE_{HIGH,MEDIUM,LOW,NONE}` (l.1070–1073). REUSED.
  - `CONF_CENSUS_CROSS_VALIDATION` (l.1080) — **gates whether cross-check runs AT ALL** (single-platform install fallback). Semantic mismatch with a divergence-downgrade kill switch → NOT reusable as the kill knob. Must mint a new rung-2 boolean.
- `custom_components/universal_room_automation/domain_coordinators/presence.py`
  - `census_count` consumed at l.4001, l.5395; `_census_confidence` at l.4028. Guest-determination path uses unidentified_count + confidence — verify at build which exact predicate flips to GUEST.
- Sensor surfacing: `sensor.py:3379–3380` (`source_agreement`, `frigate_count`).
- 9-camera census list incl. 3 Protect interiors (`playroom_high_resolution_channel`, `staircase_high_resolution_channel`, plus operator-added today) — integration-scoped, not touched.

### 1.2 Greps run

| Need | Result |
|---|---|
| Divergence-downgrade knob | none exists — NEW required |
| Existing kill switch fit | `CONF_CENSUS_CROSS_VALIDATION` gates whole cross-check (OFF = single-source path l.1154). Wrong semantic — turning it off DISABLES the check we want to harden. **NEW knob required.** |
| Guest-determination consumer | `presence.py` `_census_count` + `_census_confidence` (l.3994–4035, l.5395). Ripple confirmed. |
| Corroboration signals ready to consult | face IDs: `_get_face_recognized_persons` (used at l.1204); BLE persons: `ble_id_set` (l.1201); tier-1 room occupancy: `any_zone_occupied` predicate exists in presence.py (l.982, l.1123). All available at the merge site OR via presence coordinator state. |
| Single-source zones | `_calculate_property_census` (l.1225) uses `CENSUS_AGREEMENT_SINGLE` unconditionally — not touched. House-census `elif frigate_available and not binary_platforms_available` branch (l.1131–1134) — SINGLE, not touched. **Regression-critical:** exterior zones + camera-areas covered by only one platform must not be re-classified. |

### 1.3 Verdict on operator recollection
- "census_cross_validation flag" — EXISTS but wrong-semantic for kill-switch reuse (verified above). New boolean minted.
- "Protect covered playroom" — CONFIRMED live: both Protect interiors are in the CM census list; the 2026-08-01 phantom snapshot shows `unifi_count=0` was captured. Wiring works; policy is the gap.

---

## 2. Falsifiable invariant (for Reviewer D)

> A lone unidentified count originating from ONE source, contradicted by a SECOND source that covers the same interior zone and reports zero, with ZERO corroboration (no face-recognized persons, no BLE persons, no tier-1 room occupancy anywhere in the zone), can NEVER alone flip house state to GUEST.

Corollaries reviewers must also try to break:
- Two sources AGREEING (both > 0) — behavior unchanged; guest flip still possible on genuine unknown.
- Single-source zones (only one platform covers) — behavior unchanged; no false suppression.
- Corroborated divergence (one source > 0, other 0, BUT a face ID or BLE ID or tier-1 room-occupied predicate is live in the zone) — behavior unchanged; the observation is trusted.
- Exterior/property census — unchanged.

---

## 3. Deliverables

### D1 — Divergence-aware count merge in `_cross_validate_platforms`

**Site:** `camera_census.py:1309–1342`.

**Change:** replace the two divergence branches (l.1332–1338) with a **min-instead-of-max on the uncorroborated component**. Signature grows to accept a corroboration bundle so the merge knows whether to trust the higher source:

```
def _cross_validate_platforms(
    self,
    frigate_count: int,
    binary_platform_count: int,
    *,
    corroborated: bool,   # face_ids ∪ ble_ids ∪ any_zone_occupied (in this zone)
) -> tuple[int, str]:
```

Rules (only the divergence branches change):
- `f>0 AND b==0` (or symmetric): if `corroborated` → keep current `(max, CLOSE)`. If NOT corroborated → return `(min(f,b), DISAGREE)` — i.e. `(0, DISAGREE)` — the uncorroborated higher reading is downgraded, not adopted.
- `f>0 AND b>0` — unchanged (`BOTH`).
- `f==0 AND b==0` — unchanged.
- Single-source (only one platform available at merge site — l.1131–1150) — unchanged.

Caller (`_calculate_house_census`, l.1128) computes `corroborated` BEFORE the merge from already-available data (`face_id_set` is computed post-merge today at l.1204 — reorder OR pass a lazy predicate; see build note). BLE and any-zone-occupied come from presence coordinator state already threaded into census.

**Downstream confidence mapping** (`_cross_correlate_persons` l.1399–1402): DISAGREE → LOW is already correct. LOW is below the guest-determination bar (verify at build — if presence still flips GUEST on LOW+unidentified, add an explicit `CENSUS_AGREEMENT_DISAGREE → suppress guest` gate in presence; document as sub-deliverable D1b if needed).

**Knob (Numbers-Get-Knobs):**

| Name | Rung | Default | Purpose |
|---|---|---|---|
| `CONF_CENSUS_DIVERGENCE_DOWNGRADE` | Config/options flow (integration-scope, alongside `CONF_CENSUS_CROSS_VALIDATION`) | `True` | Kill switch. `False` restores pre-cycle max-wins behavior (fire axe). |
| `CENSUS_DIVERGENCE_CORROBORATION_KINDS` | Module constant (`const.py`) | `frozenset({"face", "ble", "zone_occupied"})` | The corroboration source set. Rung-1 because changing it (e.g. adding "mmwave") requires review — it defines what "corroborated" means to the invariant. |

No new numeric threshold (no factor, no ratio) — the rule is min-vs-max, boolean-gated on corroboration. Marginal-benefit check: a downgrade *factor* was considered and rejected — it adds a tunable with no evidence trigger and doesn't materially harden the invariant beyond min-wins.

**Acceptance criteria:**
- **Verify:** replay the exact 2026-08-01 playroom snapshot shape (`frigate=1`, `binary=0`, `face_ids=∅`, `ble_ids=∅`, `any_zone_occupied=False`) → merge returns `(0, DISAGREE)` → confidence LOW → no GUEST flip in presence.
- **Verify:** agreeing sources (`frigate=1`, `binary=1`, any corroboration state) → `(1, BOTH)` → confidence HIGH → unchanged.
- **Verify:** single-source zone (only Frigate available) → SINGLE branch unchanged → no regression on exterior/single-platform interiors.
- **Verify:** corroborated divergence (`frigate=1`, `binary=0`, BUT `face_ids={"jaya"}` OR `ble_ids={...}` OR `any_zone_occupied=True`) → `(1, CLOSE)` — trusted, unchanged from today.
- **Verify:** kill switch `CONF_CENSUS_DIVERGENCE_DOWNGRADE=False` restores pre-cycle behavior byte-identically (golden test on the snapshot).
- **Test:** `tests/test_census_divergence_policy.py::{test_playroom_snapshot_replay, test_agreement_unchanged, test_single_source_unchanged, test_corroborated_divergence_trusted, test_kill_switch_reverts, test_no_regression_property_census}`.
- **Live:** post-restart, next organic divergence event on any interior zone with no corroboration shows `census_snapshots.source_agreement='disagree'` and NO `presence_events` GUEST transition within the same tick. Playroom phantom recurrence (any of the 3 known camera areas) does NOT laundering the comfort-fan away-veto.

### D2 — Options-flow surface + strings

**Site:** `config_flow.py:2846` (integration `async_step_camera_census`) — add the new boolean beside `CONF_CENSUS_CROSS_VALIDATION`. Mirror strings.json/translations/en.json (matching the existing `census_cross_validation` label/description pair).

**Acceptance:**
- **Verify:** options-flow round-trip persists the flag; default True on new installs; existing entries default True on reload (no migration; single-user policy).
- **Live:** flag visible in integration options; toggling it OFF and reloading restores max-wins in the merge (log scan).

---

## 4. Parked (evidence triggers, NOT built this cycle)

- **`source_counts` JSON generalization** of `census_snapshots` — belongs to the fusion cycle; the two vendor columns are preserved as-is for analytics compatibility.
- **CameraResolver abstraction / cross-platform sensor discovery** — fusion cycle.
- **Per-source-key generalization of `_cross_validate_platforms` beyond 2 sources** — deferred until a 3rd platform lands. Today's fix is binary-vs-Frigate min-wins-on-uncorroborated; N-source min-generalization is trivial later.
- **Divergence-downgrade factor** — rejected (no evidence trigger; boolean min-wins is sufficient).
- **Explicit `DISAGREE → suppress guest` gate in presence** — build under D1b IF LOW confidence still flips GUEST today; otherwise unneeded.

---

## 5. Files touched

| File | Change |
|---|---|
| `const.py` | ADD `CONF_CENSUS_DIVERGENCE_DOWNGRADE`, `DEFAULT_CENSUS_DIVERGENCE_DOWNGRADE=True`, `CENSUS_DIVERGENCE_CORROBORATION_KINDS`. |
| `camera_census.py` | Modify `_cross_validate_platforms` signature + divergence branches (l.1332–1338); modify `_calculate_house_census` to compute `corroborated` and pass it (l.1124–1152); add `_is_divergence_downgrade_enabled` sibling to `_is_cross_validation_enabled`. |
| `config_flow.py` | Add flag to `async_step_camera_census` (~l.2882). |
| `strings.json`, `translations/en.json` | Label + description for `census_divergence_downgrade`. |
| `domain_coordinators/presence.py` | ONLY if D1b needed — explicit gate on `CENSUS_AGREEMENT_DISAGREE` at guest-flip predicate. |
| `tests/` | `tests/test_census_divergence_policy.py`. |
| `docs/readmes/README_v<version>.md` | Pre-deploy prospective + post-deploy Validated table (per CLAUDE.md). |

Not touched: `sensor.py` payload (attributes still expose `source_agreement` and the two vendor counts — analytics unchanged), CENSUS hold/decay (v5.9.0), the census camera list, single-source path (l.1154–1198), property census (l.1225–1303), `resolve_cross_platform_sensors`.

---

## 6. Review protocol (Tier 2-DB, three framing-disjoint reviews)

- **A — Data integrity + policy correctness.** The min-wins rule, corroboration bundle assembly, confidence mapping post-change, `census_snapshots` row shape byte-identical (columns/values), no reader downstream sees a new key/value.
- **B — Ripple + no-regression.** Presence coordinator guest-flip predicate under the new DISAGREE/LOW output; comfort-fan away-veto laundering path (the specific incident); exterior and single-source unchanged; `CONF_CENSUS_CROSS_VALIDATION=False` path unchanged (still bypasses the whole cross-check); kill-switch `CONF_CENSUS_DIVERGENCE_DOWNGRADE=False` restores byte-identical pre-cycle output on the playroom fixture.
- **C — Test authority via per-site source mutation.** Neuter EACH of: the min-vs-max branch, the corroboration-True short-circuit, the kill-switch check, the DISAGREE→LOW mapping — ONE at a time; verify a SPECIFIC test fails per site; restore. `PYTHONDONTWRITEBYTECODE=1` + clear `__pycache__` per run.

**Pre-deploy snapshot** of `census_snapshots` row rate by `(source_agreement, confidence)` for ±25% post-deploy comparison.

**Live Validation (Review D):** post-restart, verify (a) the playroom snapshot replay (or next organic recurrence) records `source_agreement='disagree'` with NO GUEST flip; (b) an agreeing-sources sample from the same window is untouched; (c) a single-source zone sample is untouched. Write results back into README.

---

## 7. Summary

Behavioral change: ONE branch of `_cross_validate_platforms` — divergent counts without corroboration return `min` (which is 0) tagged `DISAGREE` instead of `max` tagged `CLOSE`. Everything else — agreement, single-source, exterior, cross-validation off, hold/decay, schema, camera list — is untouched. One new operator-facing kill switch, one module constant defining "corroborated." Live evidence trigger already exists (the 2026-08-01 snapshot) so the fix is replay-testable in-suite.
