# PLANNING — Path-α LOST dissolution + memory writers for the new away logic

**Current rev:** 3.5.1 (2026-08-16). Final before build. See §"Operator checkpoint history" for the full rev chain (1 → 2 → 3 → 3.1 → 3.2 → 3.3 → 3.4 → 3.5 → 3.5.1).

**Rev-3.5.1 representational pin:**
**Case-(b) phone-on-charger / BLE-silent-at-home is `ACTIVE` + `location="home"` + `tracking_reason="home_ble_silent"` WHEN there is affirmative home evidence from GPS or WiFi.** NOT `LOST`. Rationale (forest-level, operator): an ACTIVE-home charger-phone correctly **BLOCKS the house going away** — the owner is presumably home; putting the person in LOST would silently remove that block and re-open exactly the vacuity class this cycle exists to prevent. **True `LOST` = `no_signal` (row 16) or `entity_missing` (pre-matrix guard) only.** For a BLE-only person (WiFi and GPS both MISSING) with BLE silent, the cell is the AWAY-voting row 14 (`away_ble_silent_only`) — that is NOT case-(b), because case-(b) requires an active home affirmation from a non-BLE axis. The unified matrix (§THE UNIFIED MATRIX) already reflected this via rows 2/3/5/10 being `ACTIVE`; rev-3.5.1 (a) fixes the stale rev-3 H2-adoption note that said "case-(b) stays under LOST"; (b) renames the rev-3.5 `bermuda_degraded` tracking_reason on rows 2 and 3 to `home_ble_silent` so the value string matches the operator's canonical name for the state; (c) folds the operator's forest-check + full state-model table into a summary section (§SIX-STATE SUMMARY).

**Rev-3.5:** unified matrix (one table, axis-MISSING first-class); BLE liveness gate in axis vocabulary; row 15 DELETED; row 16 KEPT with epistemic-null rationale; row 17 → PRE-MATRIX GUARD; Ziri corrected to BLE-only via IRK; FIVE phone-left-behind consumers; calibration knob for row 14.

**Cycle IDs:** PATH-ALPHA-DENOM-1 + MEMORY-WRITERS-1 + GUEST-FP-RESIDUALS-1 A1.
**Tier:** 2-DB. Rev-3.5.1 is FINAL — ready for build dispatch pending operator sign-off.
**Depends on:** ZONE-TIER-DIVERGE-1 trace merged; MEMORY-COMPACTOR-1 shipped.
**Non-goal:** does NOT fix the phantom-zone / fan-loop side of AWAY-BLOCK-1.

---

## SIX-STATE SUMMARY (rev-3.5.1 — operator-canonical forest-check)

The classifier's output space is SIX states plus TWO overlays. This is the clearest statement of the cycle's outcome and the plan's authoritative representation.

### Six base states

| # | State (tracking_status + location) | Canonical `tracking_reason` values | Matrix rows | I-α vote | Meaning |
|---|---|---|---|---|---|
| S1 | **`ACTIVE` + `home` (Bermuda-authoritative)** | `bermuda` | 1 | no away-vote | Physical presence confirmed at a home room by BLE. Blocks house-away. |
| S2 | **`ACTIVE` + `home` (case-(b), BLE-silent with non-BLE affirmation)** | **`home_ble_silent`** | **2, 3, 5, 10** | no away-vote | Non-BLE axis (GPS or WiFi or both) affirms home; BLE is silent/indeterminate/MISSING. Owner presumably home (phone on charger, cold BLE, etc.). **Blocks house-away — the forest-level correction rev-3.5.1 pins.** |
| S3 | **`ACTIVE` + `away` (multi-source agreement)** | `away_all_agree`, `away_wifi_silent_local`, `away_wifi_only`, `away_gps_only`, `away_ble_silent_only` | 6, 9, 11, 13, 14 | **AWAY** | ≥1 source affirmatively reports away and the vote isn't neutralized by H2 or anomaly. Contributes to `all_tracked_persons_away`. |
| S4 | **`ACTIVE` + <deferred>** (anomalous / contradictory) | `anomalous_gps_stale_local_gone`, `anomalous_gps_lag_arrival`, `anomalous_wifi_gone_local_home` | 4, 5 (WiFi-anom variant), 8 | excluded (defer) | Signals contradict; classifier stamps ACTIVE with low confidence (~0.5–0.85) and defers voting rather than picking a wrong side. Instrumented by D6 `tracker_trust_excluded` writer for recurrence. |
| S5 | **`LOST` + `unknown` (NO_SIGNAL, epistemic null)** | `no_signal` | **16 only** | excluded (fail-safe) | All axes unknown/unavailable/MISSING/indeterminate. Refuses to vote either way. Residual all-persons-in-S5 case is the intentional vacuity fail-safe (no house transition on zero evidence); instrumented by D5 `away_transition_blocked` writer. |
| S6 | **`LOST` + `unknown` (`entity_missing`, PRE-MATRIX GUARD)** | `entity_missing` | (guard, not in matrix) | excluded (structural) | `person.<name>` entity does not exist in HA. Persistent config error; distinct from S5's transient no-signal. **One-time NM note per boot** (does not self-heal). |

### Two overlays (apply on top of the six base states)

| Overlay | Trigger | Effect | Consumer sites |
|---|---|---|---|
| **O1: H2 phone-left-behind exclusion** | `PersonPhoneLeftBehindSensor` for the person is `on` (BLE places phone at home + no camera-see + no unidentified-census + outside sleep hours) | Person excluded from trusted denominator AT ALL 5 CONSUMER SITES regardless of base state; base state can still be S1/S2/S3/S4 with a matching `tracking_reason` (e.g. `phone_left_behind_confirmed`). Overlay wins over base for I-α vote. | 5 sites (§Phone-left-behind — five consumers) |
| **O2: STALE-decay (existing rev-3-preserved behavior)** | Bermuda area sensor exists, no update in decay window, last-known location kept | `tracking_status=STALE`, location preserved (typically S1→STALE-home, or S3→STALE-away). STALE-away last-known counts as case-(a) affirmative per I-α source 3. STALE is a decay OVERLAY on ACTIVE, not a distinct base state. | classifier stamp, existing behavior |

**Forest check:** the ONLY state that produces a "silent no-vote" is S5/S6. Every other state either votes home-affirmatively (blocks away — S1/S2), votes away-affirmatively (S3), or defers-with-instrumentation (S4). **Case-(b) BLE-silent-at-home CANNOT collapse to LOST when there is any non-BLE home affirmation** — that would silently remove the away-block and reproduce the exact defect this cycle exists to prevent.

**Correspondence to operator's original direction ("dissolve LOST"):** LOST now means what it says — no signal (S5) or no entity (S6). Case-(a) confidently-away moved to S3 (ACTIVE-away). Case-(b) BLE-silent-at-home moved to S2 (ACTIVE-home). The historical overload where LOST conflated "no signal," "confidently away," and "at home but phone silent" is decomposed into three honest states with distinct behaviors.

---

## Pre-matrix guards (rev-3.5)

**Guard 1 — `entity_missing` (S6).** IF `person.<name>` entity does not exist in HA, classifier assigns S6 (`LOST` + `entity_missing` + one-time NM note per boot). Persistent config error; does not self-heal.

**Guard 2 — H2 phone-left-behind pre-filter (O1 overlay).** Runs BEFORE matrix vote consumption at presence.py:5122. Verified at all 5 consumer sites per §"Phone-left-behind — five consumers."

After guards, classifier maps (GPS, WiFi, BLE) tuple to a matrix row (S1–S5).

---

## THE UNIFIED MATRIX (rev-3.5.1)

**Axes.** Each with axis-absence as first-class value:
- **GPS** ∈ `{home, away, unknown, MISSING}`
- **WiFi** ∈ `{home, not_home, unavailable, MISSING}` (`not_home` = `consider_home`-timeout affirmative; `unavailable` = integration broken)
- **BLE** ∈ `{visible, silent, indeterminate, MISSING}` — `silent` MEANS scanner-fleet-provably-live AND this device unseen past decay; `indeterminate` = liveness not provable

**Precedence:** H2 first → affirmative GPS > affirmative WiFi > BLE > nothing = NO_SIGNAL.

| # | GPS | WiFi | BLE | HA `person.state` | Reading | State | `tracking_reason` | Conf | I-α vote |
|---|---|---|---|---|---|---|---|---|---|
| 1 | any | any | `visible@<home_room>` | `home` | Present at home, BLE authoritative | S1 | `bermuda` | 0.90 | no |
| 2 | `home` | `home` | `silent` | `home` | Case-(b): affirmed home (GPS+WiFi), BLE cold with liveness proof | **S2** | **`home_ble_silent`** (rev-3.5.1 renamed from `bermuda_degraded`) | 0.85 | no (blocks away) |
| 3 | `home` | `home` | `indeterminate`/`MISSING` | `home` | Case-(b): affirmed home (GPS+WiFi), BLE mute or absent | **S2** | **`home_ble_silent`** (rev-3.5.1) | 0.80 | no (blocks away) |
| 4 | `home` | `not_home` | `silent` | `home` (GPS wins) | Anomalous: GPS home + WiFi off — likely GPS stale/cached | S4 | `anomalous_gps_stale_local_gone` | 0.5 | excluded (defer) |
| 5 | `home` | `not_home` | `visible@<home_room>` | `home` (GPS+BLE win) | Phone at home; WiFi flake OR device on cellular | S2/S4 mix | `anomalous_wifi_gone_local_home` | 0.85 | no (blocks away via home affirmation) |
| 6 | `away` | `not_home` | `silent` | `not_home` | All three agree away — strongest away signal | S3 | `away_all_agree` | 0.99 | **AWAY** |
| 7 | `away` | `not_home` | `visible@<home_room>` | `not_home` (GPS+WiFi win) | **Phone-left-behind confirmed** (H2 detects) | S3+O1 | `phone_left_behind_confirmed` | 0.95 | excluded (O1) |
| 8 | `away` | `home` | `visible@<home_room>` | `home` (WiFi+BLE win) | GPS lag — person just arrived | S4 | `anomalous_gps_lag_arrival` | 0.85 | no |
| 9 | `away` | `unavailable`/`MISSING` | `silent`/`indeterminate`/`MISSING` | `not_home` | GPS-only away | S3 | `away_gps_only` | 0.92 | **AWAY** |
| 10 | `home` | `unavailable`/`MISSING` | `silent`/`indeterminate`/`MISSING` | `home` | Case-(b): affirmed home (GPS-only), BLE mute or absent, WiFi absent | **S2** | **`home_ble_silent`** (rev-3.5.1 — was `home_gps_only`; unified under case-(b) canonical name since GPS is the affirmation source) | 0.75 | no (blocks away) |
| 11 | `unknown`/`MISSING` | `not_home` | `silent` | `not_home` | WiFi affirmative away + BLE silent (liveness-proven) | S3 | `away_wifi_silent_local` | 0.95 | **AWAY** |
| 12 | `unknown`/`MISSING` | `not_home` | `visible@<home_room>` | `not_home` (WiFi wins) | **Phone-left-behind suspected** (H2 detects) | S3+O1 | `phone_left_behind_suspected` | 0.75 | excluded (O1) |
| 13 | `unknown`/`MISSING` | `not_home` | `indeterminate`/`MISSING` | `not_home` | WiFi-only away, BLE offers nothing | S3 | `away_wifi_only` | 0.90 | **AWAY** |
| 14 | `unknown`/`MISSING` | `unavailable`/`MISSING` | `silent` | `unknown` (aggregation) → treated per row-14 vote-shape | S3 | `away_ble_silent_only` | **0.82** | **AWAY** (calibration-critical) |
| 15 | — | — | — | — | **DELETED rev-3.5** (was: GPS-only home hedge 0.70) — see §"Design rationale — deleted row 15" | — | — | — | — |
| 16 | `unknown`/`MISSING` | `unavailable`/`MISSING` | `indeterminate`/`MISSING` | `unknown` | **NO_SIGNAL — epistemic null (KEPT rev-3.5)** — refuses to vote | **S5** | `no_signal` | 0.0 | excluded (fail-safe) |

**Rev-3.5.1 rename summary:** rows 2, 3, and 10 all now emit `tracking_reason="home_ble_silent"` — the canonical case-(b) name — because they all represent the same operator-legible state: "affirmative home evidence from a non-BLE axis, BLE not contributing positive presence." Value `bermuda_degraded` retired from `TRACKING_REASON_VALUES`; value `home_gps_only` retired as a distinct value (folded into `home_ble_silent`). One less name in the vocabulary, more accurate coverage of the state.

**Notes preserved from rev-3.5:**
- Row 1 fires whenever BLE is visible at a home room (any GPS/WiFi).
- Rows 7/12 are the confounder diagonal — H2 + 4 downstream consumers exclude.
- Row 4 defers rather than voting; row 5 grants home-block via BLE room + GPS home despite WiFi flake.
- Row 14 is the BLE-only away vote — Ziri's canonical away path.
- Row 16 is the ONLY intentional non-vote cell.

### Design rationale — deleted row 15 (unchanged from rev-3.5)

Prior text hedged BLE-only home evidence with a 0.70 confidence. Operator challenged; hedge conflated scanner-liveness-provable-but-silent (row 14 semantics) vs scanner-liveness-unprovable (row 16 semantics). Resolution: liveness either provable (row 14) or not (row 16). No hedged middle. Row 15 deleted.

### Design rationale — kept row 16 (unchanged from rev-3.5)

Epistemic null, not a hedge. Only intentional refusal-to-vote. Residual all-excluded → no house transition on zero evidence is CORRECT fail-safe (the alternative — fabricate a vote on zero evidence — is what caused AWAY-BLOCK-1). Instrumented by D5 `away_transition_blocked` writer with full gate-input snapshot; observable, diagnosable, remediable.

---

## ZIRI — worked example (rev-3.5 corrected, unchanged in rev-3.5.1)

`ziri_iphone` is an **IRK tracker (BLE)** — Ziri is the household's **BLE-ONLY person**. Inventory: GPS=MISSING, WiFi=MISSING, BLE=`ziri_iphone`.

Ziri's states:
- **Home, BLE resolves to room** → row 1 → S1 (`ACTIVE` + `bermuda`, no away-vote).
- **Leaves house, BLE decay elapses, scanner fleet provably live** → row 14 → S3 (`ACTIVE` + `away_ble_silent_only`, conf 0.82, **AWAY vote**).
- **BLE integration broken OR scanner fleet dark** → row 16 → S5 (`LOST` + `no_signal`, no vote).

Ziri is NEVER in S2 (case-b) — case-b requires non-BLE home affirmation, and Ziri has no non-BLE axis. Consistent with the operator's forest-check: BLE-only + silent is either away (row 14) or NO_SIGNAL (row 16), never case-b.

Whether Ziri can solo-transition the house depends on `BLE_SILENT_ONLY_AWAY_CONFIDENCE` (0.82) vs the path-α threshold (0.9) — §"Calibration knob."

---

## Phone-left-behind — five consumers (unchanged from rev-3.5)

Five sites (all must exclude a case-(a) ACTIVE-away person who is ALSO phone-left-behind):

1. `PersonPhoneLeftBehindSensor` (binary_sensor.py:1681) — detector.
2. H2 filter `_phone_trustworthy` (presence.py:176, consumed :5115-5133).
3. Forgotten-phone FP veto (Gap A, presence.py:1042).
4. Veto-density weighting excluding phone-left-behind persons' locations (presence.py:5010-5050).
5. `_ble_corroboration.py:43`.

Plus `TRANSIT_PHONE_LEFT_BEHIND_HOURS = 4.0` at const.py:1972.

**D1 acceptance:** enumerate all 5 sites in artifact.
**D2 acceptance:** per-site source-mutation drill; case-(a) ACTIVE-away + phone-left-behind ON person is excluded at every site with a distinct named test failure per site.

---

## Calibration knob (unchanged from rev-3.5)

`BLE_SILENT_ONLY_AWAY_CONFIDENCE` (rung-1 constant, default 0.82) vs path-α threshold (0.9). Decides whether a BLE-only person (Ziri) can solo-transition house-away. Default recommendation: keep below threshold (conservative — solo-BLE cannot flip the house alone; requires corroborating votes). Operator decides at build-review.

---

## Falsifiable invariant (rev-3.5.1 restated)

> **I-α:** A person tracker's contribution to `all_tracked_persons_away` is governed by (1) two pre-matrix guards (`entity_missing` → S6 with NM note; H2 phone-left-behind → O1 overlay excludes at 5 consumer sites), THEN (2) the unified matrix — one table, axis absence first-class, precedence H2 > GPS > WiFi > BLE > nothing.
>
> **A person contributes an away-vote iff:** (a) both pre-matrix guards pass, AND (b) their tuple resolves to a matrix row voting **AWAY** (S3 rows 6, 9, 11, 13, 14). Row 14 requires scanner-fleet liveness proof.
>
> **A person BLOCKS house-away (no vote, but denominator-contributing) iff:** their tuple resolves to S1 (row 1) or **S2 (rows 2, 3, 5, 10 — case-(b) with affirmative non-BLE home evidence)**. Case-(b) is ACTIVE-home, NOT LOST — an owner presumably home must not be silently reclassified as no-signal (rev-3.5.1 pin).
>
> **Refusal to vote (excluded, no denominator contribution)** iff S5 (row 16 NO_SIGNAL) OR S6 (entity_missing) OR O1 overlay (phone-left-behind) OR S4 deferred (rows 4, 8).
>
> **A tracker with no location signal, or a phone-left-behind person, can NEVER contribute an away vote.** Residual all-excluded → no house transition is the intentional vacuity fail-safe.
>
> **Source-agnostic + dynamic-inventory:** classifier reads `person.<name>.state` via HA aggregation and `person.<name>.attributes.source` per tick (never cached).
>
> **Discriminator:** WiFi `not_home` is affirmative; WiFi `unavailable` is not. BLE `silent` (liveness-proven) is affirmative; BLE `indeterminate` is not.
>
> **Case-(b) never-collapses-to-LOST pin (rev-3.5.1):** any tuple with GPS=`home` OR WiFi=`home` classifies as S1 or S2 (both ACTIVE + location=home) — NEVER S5 LOST. Silently removing an ACTIVE-home block is a defect this cycle prevents by construction.

Break invariant → plan falsified. D produces per-row fixtures (16 rows; row 15 deleted) + two pre-matrix guards + 5-consumer phone-left-behind + case-(b) never-LOST assertion + row 14 liveness gate + row 16 fail-safe.

**I-M** on write-rate discipline: unchanged.

---

## Institutional context verified (rev-3.5.1 vocabulary update)

**`TRACKING_REASON_VALUES` frozenset (rev-3.5.1 tightened):**

```python
TRACKING_REASON_VALUES: Final = frozenset({
    "bermuda",                          # S1
    "home_ble_silent",                  # S2 — canonical case-(b) name; covers
                                        # rows 2, 3, 10 (formerly bermuda_degraded,
                                        # home_gps_only)
    "away_all_agree", "away_wifi_silent_local",
    "away_wifi_only", "away_gps_only",
    "away_ble_silent_only",             # S3 — row 14 BLE-only away
    "anomalous_gps_stale_local_gone",
    "anomalous_gps_lag_arrival",
    "anomalous_wifi_gone_local_home",   # S4 anomalous / deferred
    "phone_left_behind_confirmed",
    "phone_left_behind_suspected",      # S3+O1 overlay-marked
    "no_signal",                        # S5 — row 16 only
    "entity_missing",                   # S6 — pre-matrix guard
    "no_trackers_configured",           # S5 sub-case (person with 0 configured trackers)
})
```

Removed vs rev-3.5: `bermuda_degraded`, `home_gps_only` — both folded into `home_ble_silent` per rev-3.5.1 semantic unification.

All other institutional context unchanged from rev-3.5 (5 phone-left-behind consumers, `BLE_SILENT_ONLY_AWAY_CONFIDENCE` knob, entity registration, HA aggregation semantics, etc.).

---

## H2 adoption note (rev-3.5.1 CORRECTED — supersedes rev-3 text)

BLE_SILENT enum DROPPED; `tracking_reason` attribute on existing enum values. **CORRECTED (rev-3.5.1):** case-(b) BLE-silent-at-home is `ACTIVE + location="home" + tracking_reason="home_ble_silent"` WHENEVER there is affirmative home evidence from GPS or WiFi (rows 2, 3, 5, 10 = state S2). Case-(b) is NOT LOST. TRUE `LOST` is reserved for S5 (`no_signal`, row 16) and S6 (`entity_missing`, pre-matrix guard) only. The prior rev-3 text asserting "case-(b) stays under LOST" was semantically wrong and would have re-opened the vacuity class this cycle exists to prevent — a case-(b) person is presumably home and their state must BLOCK house-away, not silently exclude from the denominator. Corrected here as the load-bearing forest-level statement.

## Memory intent & limits — unchanged from rev-2/rev-3

## Why occupancy flips are memory-ineligible — unchanged from rev-2/rev-3

## Rev-3.1 app-less + rev-3.3 evidence hierarchy + rev-3.4 dynamic-inventory + rev-3.5 unified matrix — all preserved and reinforced by rev-3.5.1's forest-level pin.

---

## Scope A — LOST-state dissolution

### D1 — Consumer enumeration artifact (rev-3.5.1)

Filed as `docs/planning/AUDIT_tracking_status_consumers.md`. Includes:

- Full tracking_status consumer inventory (all rev-3 sites).
- Five phone-left-behind consumers section (rev-3.5) with per-site verification.
- Per-person tracker inventory + platform + expected states (S1-S6) + expected matrix rows.
- Ziri BLE-only worked example.
- Pre-matrix guard `entity_missing` documentation with NM-note behavior.
- Calibration knob relationship.
- **Six-state summary table (rev-3.5.1)** with overlays and canonical `tracking_reason` values per state.

### D2 — Classifier rewrite (rev-3.5.1)

**D2a — `person_coordinator.py` unified-matrix classifier.** Pre-matrix guards → `_classify_matrix_row(source_snapshot) -> MatrixRow` → returns S1-S6 + `tracking_reason` per rev-3.5.1 vocabulary. Case-(b) rows 2/3/5/10 emit `home_ble_silent` uniformly. Dynamic-inventory contract preserved. Row 14 confidence from `BLE_SILENT_ONLY_AWAY_CONFIDENCE`.

**D2b — presence.py path-β relaxed-predicate + LOST-admission-list retirement**: (A-L2 fix, 2026-08-16 — corrected from prior "wholesale delete" wording). The commit narrowed to retiring the `_tracking_active_or_lost_away` relaxed predicate and its associated LOST-admission list; the path-β *branch* itself is preserved and now shares path-α's denominator (`all_trusted_or_lost_away_persons_away = all_tracked_persons_away`). Path β remains as a strict-subset gate of path α post-cycle (see Review B §2 F2 for follow-up on the now-vestigial machinery — carded separately, NOT bundled here).
**D2c — aggregation.py `tracking_reason` + `tracker_sources` passthrough**: unchanged.
**D2d — const.py `TRACKING_REASON_VALUES` frozenset (rev-3.5.1 vocabulary) + `BLE_SILENT_ONLY_AWAY_CONFIDENCE` knob + comment updates**: as documented above.

**D2 acceptance criteria (rev-3.5.1 additions in bold):**

All rev-3.5 criteria preserved. Add:

- **Verify:** case-(b) never-collapses-to-LOST — fixture with GPS=home (or WiFi=home) + BLE=silent → classifier produces S2 (`ACTIVE + home + home_ble_silent`), NOT S5 LOST. Mutation drill: any code path that stamps LOST for a home-affirmed person reddens a specific named test (`test_case_b_never_lost.py`).
- **Verify:** value `bermuda_degraded` and `home_gps_only` no longer written anywhere; all case-(b) rows emit `home_ble_silent`. Grep-asserted in a boot-time invariant test.
- **Verify:** the six-state summary correctly enumerates every classifier output — no reachable output falls outside S1-S6 (with S3+O1 as the only overlay combination that changes vote behavior).

### D3 — Rider

Guest-FP diagnostic classifier keys on `tracking_reason` (rev-3.5.1 vocabulary).

---

## Scope B — memory writers (unchanged from rev-3)

D4/D5/D6/D7 unchanged. D5 `away_transition_blocked` remains the instrumentation for the S5-all-excluded fail-safe.

---

## D-tests deliverable (rev-3.5.1 additions)

All rev-3.5 tests preserved. **Add / update (rev-3.5.1):**

- `test_case_b_never_lost.py` — GPS=home OR WiFi=home + BLE=silent → S2 not S5; mutation reddens named test.
- `test_tracking_reason_vocabulary_pin.py` — asserts `bermuda_degraded` and `home_gps_only` are NOT in `TRACKING_REASON_VALUES` and NOT emitted anywhere.
- `test_six_state_summary_coverage.py` — classifier output space is exactly S1-S6; any output not in the set fails.
- `test_matrix_row_coverage.py` — 16-row fixture updated: rows 2/3/10 assert `tracking_reason == "home_ble_silent"` (was `bermuda_degraded` / `home_gps_only`).

---

## Deliverables summary — unchanged from rev-3.4 structure

D2d gains the rev-3.5.1 vocabulary tightening. D-tests grows per above.

**Non-goals (rev-3.5.1 additions):**
- Does NOT reclassify case-(b) as LOST under any circumstance — S2 is ACTIVE-home, permanently.
- Does NOT keep `bermuda_degraded` or `home_gps_only` as `tracking_reason` values — folded into `home_ble_silent`.
- Does NOT introduce a seventh base state — the six enumerated in §"SIX-STATE SUMMARY" are exhaustive.

---

## Tier-2-DB review framings (rev-3.5.1 refinements)

- **Review A** — completeness: 16 matrix rows + 2 pre-matrix guards → exactly six base states (S1-S6) + one overlay (O1). Case-(b) rows 2/3/5/10 all emit `home_ble_silent`, all stamp S2, all block away. Row 15 deleted, row 16 refuses. Vocabulary reduced correctly.
- **Review B** — cross-coordinator + case-(b) home-block preservation: no code path silently reclassifies case-(b) as LOST; five phone-left-behind consumers exclude case-(a) ACTIVE-away independently; person aggregation not re-implemented.
- **Review C** — mechanical completeness: 16 matrix-row drills + 2 guard drills + 5 phone-left-behind drills + row 14 liveness + row 16 fail-safe + calibration knob + Ziri + dynamic-inventory flip + **case-(b) never-LOST drill + vocabulary-tightening drill + six-state coverage drill** — each reddens a NAMED test.

**Live D** — per-person matrix cells observed; each of the 6 base states observed (S1/S2 easy; S3 daily; S4 anomaly-dependent; S5/S6 only if triggered — S6 surfaces via NM note); phone-left-behind exclusion visible across all 5 sites.

**Post-restart README write-back** per CLAUDE.md.

---

## Vibememo / Sequencing — unchanged from rev-2/rev-3

---

## Operator checkpoint history

- **Rev-1:** 6 design choices.
- **Rev-2:** all 6 accepted; 4 writers; companion GPS incorporated; exterior-path DROP; memory-ineligible rationale; vibememo.
- **Rev-3:** C1/C2/C3 CRITs; H2 adopted (BLE_SILENT enum DROPPED, `tracking_reason` attr); H1/H3/H4; D-tests.
- **Rev-3.1:** app-less-person constraint — source-agnostic ladder; permission-decay graceful; discriminator; `tracker_sources` diagnostic.
- **Rev-3.2:** matrix as authoritative organizing structure; `TRACKING_REASON_VALUES` frozenset with WARN gate.
- **Rev-3.3:** evidence hierarchy; phone-left-behind (2 consumers cited); GPS first-class Matrix-A/B split.
- **Rev-3.4:** live per-person source inventory; dynamic-inventory contract; Ziri stress-case (D1 platform-lookup pending).
- **Rev-3.5:** UNIFIED matrix (axis-MISSING first-class); BLE liveness gate in axis vocabulary; row 15 DELETED; row 16 KEPT as epistemic null + fail-safe; row 17 `entity_missing` → PRE-MATRIX GUARD with NM note; Ziri = BLE-only via IRK; FIVE phone-left-behind consumers; calibration knob `BLE_SILENT_ONLY_AWAY_CONFIDENCE`.
- **Rev-3.5.1 (2026-08-16, FINAL):** representational pin — case-(b) BLE-silent-at-home is `ACTIVE + home + home_ble_silent` (S2), NOT LOST, whenever there is affirmative non-BLE home evidence. Rows 2/3/5/10 all emit `home_ble_silent` (rev-3.5's `bermuda_degraded` and `home_gps_only` values retired). True `LOST` reserved for S5 (`no_signal` row 16) and S6 (`entity_missing` guard) only. Operator's forest-check + full state-model summary (6 states + 2 overlays) folded in as §SIX-STATE SUMMARY. **Ready for build dispatch.**
