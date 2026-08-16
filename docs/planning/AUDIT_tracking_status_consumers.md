# AUDIT — tracking_status consumer inventory (PATH-ALPHA-DENOM-1 D1)

**Date:** 2026-08-16. Base commit: `fa31c6d45` (feature/path-alpha branched from develop).
**Plan:** `PLANNING_path_alpha_lost_dissolution.md` rev-3.5.1 (FINAL).
**Purpose:** authoritative fixture that reviewer A diffs the build against. Every consumer of
`tracking_status`, `_tracking_active*`, `TRACKING_STATUS_*`, `phone_left_behind`,
`_lost_away_since`, and the new `tracking_reason` attribute is enumerated with file:line, current
behavior, and post-cycle disposition per rev-3.5.1.

**Method:** `git grep -n "TRACKING_STATUS_\|tracking_status\|_tracking_active" custom_components/`
plus targeted greps for `phone_left_behind`, `PhoneLeftBehind`, `_phone_trustworthy`,
`_ble_corroboration`, `BLE_SILENT`, `home_ble_silent`, `bermuda_degraded`, `home_gps_only`,
`BLE_SILENT_ONLY_AWAY`, `MEMORY_EPISODE_TYPES`, `MEMORY_FACT_TOPICS`. All hits inspected;
frontend-v3 minified JS hits excluded from ripple set (see §Frontend at bottom).

---

## Historical lineage — WHY THIS CYCLE EXISTS

The LOST-exclusion this cycle corrects originated as **H3 (Gap C) of v4.7.14.1**
(`docs/planning/PLANNING_v4.7.14.1_forgotten_phone_hotfix.md`, 2026-05-30). H3 rightly distrusted
stale-fallback locations but **lumped confidently-away trackers in with genuinely-unknown ones
under the LOST label**, emptying the trusted denominator in AWAY-BLOCK-1 three months later. The
unified matrix (rev-3.5.1) **preserves H3's correct half** (row 16 `no_signal` exclusion) and
**corrects the over-reach** (positive-away-evidence rows become ACTIVE voters via `tracking_reason`
attribute rather than a LOST enum). The v4.7.14 `tracked_count > 0` guard is preserved verbatim —
same fail-safe family as row 16 and MUST NOT be removed by the classifier rewrite. This lineage
note prevents a future cycle from "fixing" row 16 back into the H3 bug or vice versa.

---

## §1 — Six-state summary (rev-3.5.1 canonical)

Per PLANNING §SIX-STATE SUMMARY. Reproduced here so reviewer A has one place to check the
classifier's output space against consumer expectations.

| # | State (`tracking_status` + `location`) | Canonical `tracking_reason` values | Matrix rows | I-α vote |
|---|---|---|---|---|
| S1 | `ACTIVE` + `home` (Bermuda-authoritative) | `bermuda` | 1 | no (blocks away) |
| S2 | `ACTIVE` + `home` (case-(b) BLE-silent + non-BLE home affirmation) | `home_ble_silent` | 2, 3, 5, 10 | no (blocks away) |
| S3 | `ACTIVE` + `away` | `away_all_agree`, `away_wifi_silent_local`, `away_wifi_only`, `away_gps_only`, `away_ble_silent_only` | 6, 9, 11, 13, 14 | **AWAY** |
| S4 | `ACTIVE` + `<deferred>` (anomalous) | `anomalous_gps_stale_local_gone`, `anomalous_gps_lag_arrival`, `anomalous_wifi_gone_local_home` | 4, 5-anom variant, 8 | excluded (defer) |
| S5 | `LOST` + `unknown` (`no_signal` — epistemic null) | `no_signal`, `no_trackers_configured` | 16 only | excluded (fail-safe) |
| S6 | `LOST` + `unknown` (`entity_missing` — pre-matrix guard) | `entity_missing` | (guard) | excluded (structural) |

**Overlays:** O1 phone-left-behind (excludes at 5 consumer sites, see §5); O2 STALE-decay
(existing behavior, preserved).

---

## §2 — Per-person tracker inventory + platform findings

Compiled from repo evidence + operator's rev-3.5 pin (Ziri = BLE-only via IRK). **Live-HA
platform verification for `device_tracker.jjs_iphone` / `device_tracker.ziri_iphone` is
required at build-review time** (this artifact is repo-only). D1 acceptance criterion per plan
§D1: "per-person tracker inventory + platform + expected states."

| Person | GPS source | WiFi source | BLE source | Expected states | Notes |
|---|---|---|---|---|---|
| **Oji Udezue** | `device_tracker.oji_iphone` (HA companion — assumed GPS-capable) | Router (`device_tracker.*_router`) if present | `oji_iphone` IRK on Bermuda | S1, S2, S3, S4, occasionally S5 | Full-signal person; expected to exercise the most matrix rows. |
| **Ezinne (JJ)** | `device_tracker.jjs_iphone` — **PLATFORM VERIFICATION PENDING** (see below) | Router if present | `jjs_iphone` IRK on Bermuda | S1, S2, S3, S5 | If the companion app is NOT installed on this device, GPS axis = MISSING and rows 9/8/4 become unreachable — matches "app-less person" class the rev-3.1 dynamic-inventory contract exists to serve. |
| **Jaya** | `device_tracker.jaya_iphone` if HA companion installed | Router if present | `jaya_iphone` IRK on Bermuda | S1, S2, S3, S5 | Same platform-verification caveat. |
| **Ziri** | **MISSING** (rev-3.5 corrected — BLE-only via IRK) | **MISSING** | `ziri_iphone` IRK on Bermuda | S1 (row 1), S3 (row 14 only), S5 (row 16) | **Solo BLE person.** Row 14 confidence 0.82 vs path-α threshold 0.9 — CANNOT solo-transition the house to away by design. See §Calibration knob. Never S2 (case-b requires non-BLE home affirmation Ziri lacks). |

### Platform-verification protocol (BUILD-REVIEW STEP)

The plan's D1 acceptance names "jjs_iphone platform verification" specifically. Reviewer A / D
must run at live-HA time:

```
ha_get_entity_details device_tracker.jjs_iphone
# check .attributes.source_type == "gps" (companion) or "router" (WiFi-only)
# check .attributes.platform == "mobile_app" (companion) or "asuswrt_ssh"/similar (router)

ha_get_entity_details device_tracker.ziri_iphone
# EXPECTED per rev-3.5: no such entity, OR router-only. Ziri's presence is Bermuda IRK.
```

**If `device_tracker.jjs_iphone` reports `source_type=router`** → JJ is a router-only person with
GPS axis MISSING; her rows collapse to {1, 2, 3, 5, 10, 11, 12, 13, 14, 16} and case-(b)
`home_ble_silent` via WiFi-only becomes her primary at-home stamp (row 3 or row 10).

**If `device_tracker.ziri_iphone` reports `source_type=gps` unexpectedly** → rev-3.5 Ziri
worked-example is wrong and the plan must be re-adjudicated before build. Flag as a Review-B
finding. Repo evidence (no HA companion config for Ziri surfaced in grep) is consistent with
BLE-only.

### Ziri BLE-only worked example (rev-3.5.1 canonical)

- **Home, BLE resolves to room:** row 1 → S1 (`ACTIVE` + `home` + `bermuda`), no away-vote.
- **Leaves, BLE decay elapses, scanner fleet provably live:** row 14 → S3 (`ACTIVE` + `away` +
  `away_ble_silent_only`, conf 0.82), **AWAY vote** but insufficient alone to flip house.
- **BLE integration broken OR scanner fleet dark:** row 16 → S5 (`LOST` + `unknown` +
  `no_signal`), no vote — path-α refuses to transition.
- Ziri is **NEVER** in S2 (case-b) — case-b requires a non-BLE home affirmation Ziri does not have.

---

## §3 — tracking_status write sites (person_coordinator.py — CLASSIFIER)

Every site that stamps a `tracking_status` value. All are in `person_coordinator.py`. Post-cycle
these become the six matrix-row / pre-matrix-guard emitters. Line numbers are current
(fa31c6d45); post-classifier-rewrite line numbers WILL shift.

| Line | Current stamp | Trigger | Post-cycle disposition (rev-3.5.1) |
|---|---|---|---|
| **:168** | `TRACKING_STATUS_LOST`, `location="unknown"`, `confidence=0.0`, `method="none"` | `person.<name>` entity does not exist | **S6 — pre-matrix guard**. `tracking_reason="entity_missing"`. One-time NM note per boot (does not self-heal). |
| **:228** | `TRACKING_STATUS_ACTIVE`, room-resolved via Bermuda | Bermuda area sensor resolves to a home room | **S1 — row 1**. `tracking_reason="bermuda"`. Conf 0.90. No away-vote. **PRESERVE `_person_was_away` clearing behavior**. |
| **:294** | (gate) `if tracking_status == TRACKING_STATUS_LOST` inside branch that just stamped ACTIVE | Dead post-cycle | **DELETE or comment out** (plan L1). |
| **:314** | `TRACKING_STATUS_STALE` via bermuda_decay | Decay window elapsed but area sensor exists | **PRESERVE as O2 overlay on top of S1/S3**. Existing behavior, no rev-3.5.1 change. `tracking_reason` inherits from last active stamp. |
| **:365** | `TRACKING_STATUS_LOST`, `location="home"`, `confidence=0.3`, `method="person_state"` | Area sensor exists but no room resolved AND `person_state.state == "home"` | **S2 — row 2 or 3 (`home_ble_silent`)**. Stamp ACTIVE + `home` + `home_ble_silent`. Confidence per row (0.85 row 2, 0.80 row 3). **BLOCKS house-away — this is the load-bearing case-(b) forest-check pin (rev-3.5.1).** MUST NOT stay LOST. Clear `_person_lost_since` and `_lost_away_since` as today. |
| **:385** | `TRACKING_STATUS_LOST`, `location="away"`, `confidence=0.9`, `method="person_state"` | Area sensor exists but no room resolved AND `person_state.state != "home"` | **Three-way split per Review-A C1**:<br>• `state == "not_home"` OR non-home zone → **S3 — row 6/9/11/13**. Stamp ACTIVE + `away` + appropriate reason. AWAY vote.<br>• `state in ("unknown", "unavailable", None)` → **S5 — row 16** (`no_signal`). Stamp LOST + `unknown`. No vote.<br>Preserve `_person_was_away = True` on the away path (Review M3). |
| **:428** | `TRACKING_STATUS_LOST` catch-all in the "no Bermuda sensor at all" branch — SINGLE stamp for BOTH home and away | Person has no Bermuda area sensor at all | **Split conditional per Review-A C3**:<br>• `person_state.state == "home"` → **S2 — row 10** (`home_ble_silent`, conf 0.75).<br>• `person_state.state == "not_home"` / non-home zone → **S3 — row 9** (`away_gps_only` if companion GPS present, else `away_wifi_only`, else `away_ble_silent_only`). AWAY vote.<br>• `state in ("unknown", "unavailable", None)` → **S5 — row 16** (`no_signal`).<br>Currently at :422-432 the branch already computes `location`/`confidence` two-way; expand to three-way.<br>**PRESERVE `_person_was_away = True` on the away path (Review M3).** |

**Mutation-drill acceptance (per plan D2):** for each of the six writer sites above, source-mutate
the stamp to a distinct sentinel value and confirm a NAMED test reddens. E.g.:
- Neuter :168 → `test_entity_missing_guard_stamps_S6` reddens.
- Neuter :228 → `test_bermuda_room_resolved_stamps_S1_bermuda` reddens.
- Neuter :365 → `test_case_b_never_lost.py::test_area_sensor_no_room_home` reddens.
- Neuter :385 away-path → `test_matrix_row_coverage.py::test_row_9_gps_only_away` reddens.
- Neuter :385 unknown-path → `test_matrix_row_coverage.py::test_row_16_no_signal_from_person_state_unknown` reddens.
- Neuter :428 home-path → `test_matrix_row_coverage.py::test_row_10_home_ble_silent_no_bermuda` reddens.
- Neuter :428 away-path → `test_matrix_row_coverage.py::test_row_9_gps_only_away_no_bermuda` reddens.

**Two neuter shapes per site** (hollow-anchor variant 7 rule): (a) return the stamp early with a
sentinel value, (b) mutate the enum constant reference to an unrelated value. Both must produce
the named test failure. AST-anchor: assert the FunctionDef `_update_person_data` contains a Call
to `_classify_matrix_row` at each of the six branch points.

---

## §4 — tracking_status READ sites (consumers)

Ordered by risk. Each site's post-cycle disposition specified.

### 4.1 — CRITICAL / classifier + display

| File:Line | Read | Current behavior | Post-cycle disposition |
|---|---|---|---|
| `aggregation.py:5286` | init `self._tracking_status = TRACKING_STATUS_LOST` | Default at construction, recomputed each tick | KEEP — restart-safe default. `tracking_reason` init to `no_signal` alongside. |
| `aggregation.py:5490-5525` | tick-driven CLASSIFIER: reads `person_info["tracking_status"]` and reduces to zone-level `self._tracking_status` | ACTIVE/STALE/LOST elif chain at zone level | **PRESERVE** — this is zone-level aggregation, not person-level classification. Passthrough of person_coordinator's already-classified value. Add pass-through for `tracking_reason` attribute so aggregation propagates it. |
| `aggregation.py:5531 / :5552 / :5554` | display / icon selectors | `if ACTIVE / elif STALE` | No BLE_SILENT enum added (rev-3.5.1 attr-only per plan H2 adoption) — these selectors need no edit. Optional: add `tracking_reason` sub-icon at :5566 later. |
| `aggregation.py:5566` | `ATTR_TRACKING_STATUS: self._tracking_status` | Sensor attribute | **ADD** `ATTR_TRACKING_REASON: self._tracking_reason` alongside. Also add `ATTR_TRACKER_SOURCES` for the dynamic-inventory diagnostic (rev-3.4). |

### 4.2 — HIGH / trusted-denominator (path-α + path-β)

| File:Line | Read | Current behavior | Post-cycle disposition |
|---|---|---|---|
| `presence.py:169` def `_tracking_active_or_lost_away` + `:186-189` body | Module-level helper | `ACTIVE` OR `(LOST/STALE AND location=="away")` | **DELETE HELPER wholesale** (plan Review-A C3 adopted option a). Every case-(a) "confidently away" tracker is now stamped ACTIVE by the classifier so the helper's OR-clause is behavior-equivalent to `== ACTIVE`. |
| `presence.py:5081-5085` `_tracking_active_or_lost_away_local = _tracking_active_or_lost_away` alias | Local alias | Dispatches to module helper | **DELETE** with helper. |
| `presence.py:5147-5182` path-β `relaxed_persons` construction + `lost_away_persons` attribute | Builds relaxed denominator | Iterates `person_data`, calls `_tracking_active_or_lost_away_local`, computes `all_trusted_or_lost_away_persons_away`, populates `lost_away_persons` list | **DELETE WHOLESALE** (Review-A C3 option a). Post-cycle, path-α already admits every case-(a) tracker as ACTIVE — path-β denominator becomes empty-of-purpose. Retire `lost_away_persons` sensor attribute and any dashboard consumer. Test migration required (§7). |
| `presence.py:5068-5079` `_tracking_active` (H3 inner) | `ACTIVE` predicate for reliable-signal emission | `info.get("tracking_status", ACTIVE) == ACTIVE` | KEEP — this is the current-tick H3 predicate; unchanged semantically post-cycle. Now includes person_state-derived ACTIVE (S3) as well as Bermuda ACTIVE (S1), which is CORRECT — case-(a) confidently-away persons SHOULD emit `person_tracking_active=True` per rev-3.5.1 (they contribute to the denominator). |
| `presence.py:5123` `track_ok = _tracking_active(info)` | H3 signal gate | as above | KEEP — semantic-widening review (Review-B H1) handled by comment update. |
| `presence.py:5136` `f"tracking_status={info.get('tracking_status','unknown')}"` | Log/reason string fed to `excluded_persons` map, consumed by guest-FP diagnostic at :5758 (D3 target) | Emits `tracking_status=<value>` | **ADD** `tracking_reason=<value>` to the reason string so D3's exact-match classifier can key on `tracking_reason` (per D3 spec + Review-M4). |
| `presence.py:5178-5180` `ts = info.get("tracking_status", ACTIVE); if ts != ACTIVE:` | Path-β `lost_away_persons` filter | Filters to non-ACTIVE contributors | **DELETE** with path-β block. |

**H2 phone-left-behind — path-α + path-β share the filter.** Post-cycle, only path-α remains.
`_phone_trustworthy` at `presence.py:5040-5050` is preserved verbatim (Review-A explicit).

### 4.3 — MEDIUM / attr string-literal consumers (safe by default, catalog only)

Each site tests `info.get("tracking_status") == "active"` string-literally. Because the cycle
adds NO new enum values (H2 attr-only adoption per rev-3.5.1), these sites remain semantically
correct: ACTIVE (post-cycle) is a superset (Bermuda + person_state), and the sites want
"reliable current tracking" which is exactly what post-cycle ACTIVE means (see H1 semantic-widening
note). No code change needed; catalog for reviewer completeness.

| File:Line | Read | Post-cycle |
|---|---|---|
| `aggregation.py:5187` | `status = person_info.get("tracking_status", "lost")` — attr passthrough | KEEP; comment updated to note ACTIVE now includes person_state |
| `aggregation.py:5242` | dict passthrough | KEEP |
| `aggregation.py:5908` | `if info.get("tracking_status") == "active"` | KEEP; **semantic widening documented** in const.py comment (Review-B H1) |
| `aggregation.py:5933` | `if info.get("tracking_status") == "active"` | KEEP; ditto |
| `binary_sensor.py:1556` | `if info.get("tracking_status") == "active"` | KEEP; ditto |
| `binary_sensor.py:1578` | `if info.get("tracking_status") == "active"` | KEEP; ditto |
| `sensor.py:3039` | `"status": person_info.get("tracking_status", "lost")` — attr passthrough | KEEP; **also add** `"tracking_reason": person_info.get("tracking_reason", "no_signal")` to the passthrough dict |
| `sensor.py:3088` | same passthrough at different sensor | KEEP; same addition |

### 4.4 — MEDIUM / camera_census

| File:Line | Read | Post-cycle |
|---|---|---|
| `camera_census.py:2334-2335` | `if tracking_status in (TRACKING_STATUS_STALE, TRACKING_STATUS_LOST)` | KEEP as-is. Rationale: STALE (O2 overlay) + LOST (S5/S6) are the "don't trust the location without corroboration" set — post-cycle ACTIVE-via-person_state is still trustworthy at census tier because it's a live tick. Update doc comment at :2288-2299 to note S5/S6 distinction. |

### 4.5 — MEDIUM / fan_veto — SEMANTIC WIDENING (Review-B H1)

| File:Line | Read | Post-cycle |
|---|---|---|
| `fan_veto.py:233-234` | `if info.get("tracking_status", TRACKING_STATUS_ACTIVE) == TRACKING_STATUS_ACTIVE` | KEEP; **CRITICAL comment update at :222-234** — document that ACTIVE now includes person_state-derived stamps, not just Bermuda-derived. house_state gate (AWAY/VACATION only) closes the loop, so behavior is correct-by-construction, but reviewer B must sign off explicitly. |

### 4.6 — LOW / const.py comment lattice

| File:Line | Read | Post-cycle |
|---|---|---|
| `const.py:167` | `TRACKING_STATUS_ACTIVE = "active"    # Recently updated by Bermuda` | **UPDATE COMMENT** — "Recently updated by Bermuda OR classified as case-(a)/(b) by matrix rows 1-14 via person_coordinator. See rev-3.5.1 six-state summary." |
| `const.py:168` | `TRACKING_STATUS_STALE = "stale"      # Not updated within decay timeout` | **UPDATE COMMENT** — clarify STALE is O2 overlay on ACTIVE (bermuda_decay); last-known `location=="away"` counts as case-(a) AWAY per I-α source 3. |
| `const.py:169` | `TRACKING_STATUS_LOST = "lost"        # No recent Bermuda data, cleared location` | **UPDATE COMMENT** — "S5 (`no_signal`, row 16) OR S6 (`entity_missing`, pre-matrix guard). REFUSES to vote; residual all-LOST = intentional fail-safe (instrumented by D5 `away_transition_blocked` writer). See rev-3.5.1 lineage note in AUDIT_tracking_status_consumers.md — H3 origin, MUST NOT be widened back to include case-(a)." |
| `const.py:1180` | `ATTR_TRACKING_STATUS: Final = "tracking_status"` | KEEP; **ADD alongside**: `ATTR_TRACKING_REASON: Final = "tracking_reason"`, `ATTR_TRACKER_SOURCES: Final = "tracker_sources"`, `ATTR_LOST_AWAY_PERSONS_RETIRED: Final = ...` — or simply delete the old `ATTR_LOST_AWAY_PERSONS` if it exists. |

---

## §4.7 — ROOM TIER + ZONE TIER consumers (added 2026-08-16, operator-raised gap)

The room and zone tiers both consume person data and were under-specified in
the initial §4 write-up. Both must be reviewed against the unified matrix.

### §4.7.1 — ROOM TIER (coupled to CONFIDENCE, NOT tracking_status)

`coordinator.py:3106-3121` calls `person_coordinator.get_persons_in_room()`
→ `get_room_occupants()` at `person_coordinator.py:1164-1200`. The filter
predicate is:

- `person_data["location"]` must be a room (not `"unknown"`, `"away"`,
  `"home"`, or `None`), AND
- `person_data["confidence"] >= 0.3` (the v3.2.6 threshold).

**`tracking_status` is NOT READ here.** The room tier is insulated from
the enum semantics, but is directly coupled to the per-cell **confidence
values** the matrix classifier assigns.

**INVARIANT I-α-room (added rev-3.5.1):** every matrix cell that can
produce a ROOM-level `location` must carry `confidence >= 0.3`. A cell
that pairs a room location with `confidence < 0.3` silently vanishes
the person from room-occupancy consumers (lights, comfort, fan_veto by
proxy) — a regression class that would look like "the room stopped
seeing me even though person tracking is ACTIVE."

**Matrix-cell audit against I-α-room (rev-3.5.1 matrix as of this doc):**

| Row | Location produced | Confidence | I-α-room verdict |
|---|---|---|---|
| 1 | room (BLE visible@home_room) | 0.90 | PASS |
| 2 | `home` (zone-level, not room) | 0.85 | N/A — no room location |
| 3 | `home` (zone-level, not room) | 0.80 | N/A |
| 4 | `home` (GPS wins, no room resolve) | 0.5 | N/A |
| 5 | room (BLE visible@home_room via row-1-like resolve) | 0.85 | PASS |
| 6 | `away` | 0.99 | N/A |
| 7 | room (`visible@home_room` — phone-left-behind) | 0.95 | PASS (O1 O-overlay excludes for I-α, but room occupancy still fires — this is CORRECT: the phone is physically in that room) |
| 8 | room (BLE `visible@home_room`) | 0.85 | PASS |
| 9 | `away` | 0.92 | N/A |
| 10 | `home` (zone-level) | 0.75 | N/A |
| 11 | `away` | 0.95 | N/A |
| 12 | room (visible@home_room — phone-left-behind suspected) | 0.75 | PASS |
| 13 | `away` | 0.90 | N/A |
| 14 | `away` | 0.82 | N/A |
| 16 | `unknown` | 0.0 | N/A |

**Verdict:** NO cell pairs a room-level `location` with `confidence < 0.3`.
Row-1/5/7/8/12 are the room-producing cells and all carry ≥ 0.75. The
invariant holds by construction under rev-3.5.1.

**REQUIRED TEST (new — assigned to D-tests deliverable):**
`test_matrix_room_locations_clear_room_occupancy_threshold` — parametrize
over every matrix row that can produce a room-level location; assert
`confidence >= 0.3`. Any future cell rescaling that drops a room-producing
cell below 0.3 reddens this test before shipping.

**Stop-rule:** if any future revision would place a room-producing cell
below 0.3, DO NOT silently rescale — surface it as a matrix-design
question because it changes who lights/comfort see.

### §4.7.2 — ZONE TIER (consumes `tracking_status` directly)

`aggregation.py:5180-5195` (`ZonePersonPresenceSensor._compute_zone_counts`
or equivalent per current line numbers — verify at build) buckets persons
by `person_info.get("tracking_status", "lost")` into
`active_count` / `stale_count` / `lost_count`, filtered to
`person_info.get("location") in zone_rooms`.

**Post-cycle behavioral shifts (README write-back required):**

- (a) **Bucket rebalancing — INTENDED.** Case-(a) confidently-away persons
  currently stamped LOST become ACTIVE post-cycle → the zone
  `active_count` metric grows and `lost_count` shrinks, without any
  physical change in who is where. This IS the point of the cycle
  (dissolving LOST) — it must be called out in the README so operators
  reading zone-count history don't chase a phantom regression. Case-(b)
  BLE-silent-at-home persons currently under LOST also become ACTIVE
  (state S2, `tracking_reason=home_ble_silent`).
- (b) **Default value `"lost"` — REVIEWED AND KEPT (rev-3.5.1).** The
  `.get(..., "lost")` fallback fires when `tracking_status` is missing
  from the person_info dict entirely (a structural fault: person_coordinator
  emitted an entry with no status). Post-cycle "no signal" is the
  fail-safe direction — treating a structurally-broken emit as `lost`
  correctly denies it any away-vote authority AND correctly excludes it
  from `active_count` (so a broken emit doesn't silently inflate
  "people present here" either). BEHAVIOR PRESERVED; comment updated
  at the call site explaining the choice. If a future cycle proposes
  changing the default, it needs its own regression test — flag as
  finding rather than silently update.

**REQUIRED CHECKS (assigned to D2c + D-tests):**

- D2c: at `aggregation.py:5180-5195`, add an explicit comment documenting
  the default choice and its fail-safe rationale (rev-3.5.1).
- D-tests: `test_zone_bucket_default_is_lost` — a `person_info` dict
  with no `tracking_status` key must count into `lost_count` (not
  `active_count`, not `stale_count`, not be excluded).
- README write-back item: "zone `active_count` metric will step up on
  first tick post-restart as confidently-away persons migrate from
  LOST→ACTIVE per matrix rows 6/9/11/13/14; not a regression."

### §4.7.3 — Cross-tier summary

| Tier | Reads | Coupled to matrix via | Post-cycle behavior change | Required checks |
|---|---|---|---|---|
| Room | `location` + `confidence >= 0.3` | Per-cell confidence values | None if all room-producing cells stay ≥ 0.3 (they do under rev-3.5.1) | `test_matrix_room_locations_clear_room_occupancy_threshold` |
| Zone | `tracking_status` bucket | Enum stamp value directly | `active_count` grows, `lost_count` shrinks (INTENDED) | `test_zone_bucket_default_is_lost`; README write-back note |
| Path-α | `tracking_status == ACTIVE` predicate | Enum stamp value | ACTIVE now includes person_state-derived (matrix rows 2-14); denominator widens | §4.2 disposition + §7 test migration |

---

## §5 — Phone-left-behind — FIVE consumer sites (plan §"Phone-left-behind — five consumers")

Per-site table with drill acceptance. **Every drill must use ≥2 neuter shapes**
(hollow-anchor variant 7); each site's drill must red a distinctly-named test.

| # | Site | File:Line | Role | Drill acceptance (2 shapes) |
|---|---|---|---|---|
| 1 | Detector | `binary_sensor.py:1681` (`PersonPhoneLeftBehindSensor.is_on`) | Produces the `on` signal per person | Shape A: force `is_on = lambda self: False` → `test_phone_left_behind_five_consumer_exclusion.py::test_site1_detector_neutered` reddens (asserts detector is source-of-truth for all four downstream sites). Shape B: mutate the unique_id template so downstream lookups miss → same test reddens with a different assertion path. |
| 2 | H2 filter | `presence.py:5040-5050` (`_phone_trustworthy` inner in `_run_inference` denominator computation) — CANONICAL H2 filter feeding path-α trusted_persons at `:5115-5133` | Excludes phone-left-behind persons from trusted denominator | Shape A: force `_phone_trustworthy = lambda name: True` → `test_site2_h2_filter_neutered` reddens. Shape B: mutate `unique_id` string template so registry lookup returns None → same test reddens (fail-OPEN default trips a different assertion). |
| 3 | Forgotten-phone FP veto (Gap A) | `presence.py:1042` region (verify at build-time — the plan cites `:1042` as the Gap-A veto site; grep hit at `:3667-3697` shows a second `_phone_trustworthy` inner used by `raw` filter) | Excludes phone-left-behind from FP veto denominator | Shape A: neuter the `_phone_trustworthy` call at the FP veto site → `test_site3_gapA_veto_neutered` reddens. Shape B: mutate the filter's list-comp predicate to always True → same test reddens. |
| 4 | Veto-density weighting | `presence.py:5010-5050` (veto-density block that excludes phone-left-behind persons' locations) | Down-weights vetoes where the phone-left-behind owner "location" is present | Shape A: neuter the exclusion → `test_site4_veto_density_neutered` reddens. Shape B: mutate the weight-computation to ignore the exclusion set → same test reddens. |
| 5 | BLE corroboration | `_ble_corroboration.py:43` (`trustworthy_persons_in_room` / `_in_zone`; unique_id lookup at :43) | Excludes phone-left-behind persons from BLE-corroboration counts consumed by presence_fan_recheck | Shape A: force the `_ble_corroboration` helper to return the input unchanged → `test_site5_ble_corroboration_neutered` reddens. Shape B: mutate the unique_id template → same test reddens (fail-OPEN trips different assertion). |

Plus `TRANSIT_PHONE_LEFT_BEHIND_HOURS = 4.0` at `const.py:1972` — knob (rung-1 constant), no code
change; document in D1 for completeness.

**AST anchor requirement:** each drill's test uses `ast.parse` on the target source module + walks
for the specific `FunctionDef` name to prove the mutation removed a real call-site guarantee, not
just a string. Grep-only anchors are hollow (variant 7).

---

## §6 — Calibration knob relationship

`BLE_SILENT_ONLY_AWAY_CONFIDENCE` (rung-1 constant, default **0.82**) placed in `const.py`
alongside the vocabulary frozenset.

**Path-α threshold:** the existing house_state away-transition confidence gate — verify at build
time; the plan cites 0.9 as the operative threshold. If house_state uses a different value, the
D1 relationship shifts but the design principle stays: **row 14 confidence (0.82) MUST be strictly
below the path-α threshold, so a solo BLE-only person cannot flip the house to away alone.**
Corroboration required.

**Consequence — Ziri:** cannot solo-transition the house to away (0.82 < 0.9). Any transition
Ziri participates in requires ≥1 corroborating source (another person's ACTIVE-away vote, camera
census, motion decay, etc.). This is the operator's rev-3.5 conservative default.

**Knob rung (per CLAUDE.md Numbers Get Knobs):** rung 1 (module constant) — this value governs a
protocol-level fail-safe (single-source house transition) and any change should require code
review; not operator-tunable via config flow.

**Comment at the const site (mandatory, per operator directive):**

```python
# BLE_SILENT_ONLY_AWAY_CONFIDENCE governs row 14 ("away_ble_silent_only") of the unified
# matrix — the ONE cell where a single BLE-only person (typically Ziri) contributes an
# away-vote. Default 0.82 is intentionally < path-α threshold (0.9) so a solo BLE-only
# person CANNOT flip the house to away without corroboration. If path-α threshold is
# lowered, this value MUST be re-adjudicated. Historical lineage: this knob replaces the
# v4.7.14.1 H3 blanket LOST-exclusion which erroneously suppressed ALL BLE-only away
# evidence. See docs/planning/AUDIT_tracking_status_consumers.md §6.
```

---

## §7 — Test migration (Deliverable M2 in plan)

### DELETE

- `_tracking_active_or_lost_away` helper — all references.
- Path-β `relaxed_persons` block assertions (any tests that assert on `lost_away_persons`
  sensor attribute or on the path-β denominator).

### MIGRATE

Files that reference `_tracking_active_or_lost_away`, `TRACKING_STATUS_LOST`, or the retired
`lost_away_persons` attribute:

| Test file | Reference | Migration |
|---|---|---|
| `test_v570_fixup_wiring.py` | `_tracking_active_or_lost_away` + WS-A1 relaxed-denominator surface | Rewrite cases to assert path-α admits case-(a) trackers as ACTIVE post-cycle; delete relaxed-denominator assertions. |
| `test_v570_guest_detection_trust.py` | `_tracking_active_or_lost_away` | Same treatment. |
| `test_census_ble_cancel_unrecognized.py` | `TRACKING_STATUS_LOST` constant | Update to match new S5 vs S6 distinction where relevant; where LOST is asserted, verify test intent and remap to `no_signal` or `entity_missing` explicitly. |
| `test_cycle4_slim.py` | `TRACKING_STATUS_LOST` | Same. |
| `test_v4714_1_forgotten_phone_hotfix.py` | `TRACKING_STATUS_LOST` | Same — but PRESERVE the H3 correct-half assertions (row 16 no-vote fail-safe + `tracked_count > 0` guard); those are the invariant this cycle exists to preserve. |

### NEW (per plan §D-tests deliverable rev-3.5.1)

| Test | Purpose |
|---|---|
| `test_case_b_never_lost.py` | GPS=home OR WiFi=home + BLE=silent → S2 not S5. Mutation drill: any code path that stamps LOST for a home-affirmed person reddens a named test. |
| `test_tracking_reason_vocabulary_pin.py` | Assert `bermuda_degraded`, `home_gps_only` NOT in `TRACKING_REASON_VALUES` and NOT emitted anywhere in the classifier or writers. Grep-asserted at test time. |
| `test_six_state_summary_coverage.py` | Classifier output space is exactly S1-S6; any output outside the set fails. |
| `test_matrix_row_coverage.py` | 16-row fixture — every row is a test case. Rows 2/3/10 assert `tracking_reason == "home_ble_silent"` (was `bermuda_degraded` / `home_gps_only`). Row 15 fixture DELETED. Row 16 asserts refusal-to-vote. Row 14 asserts `AWAY` at conf 0.82. |
| `test_phone_left_behind_five_consumer_exclusion.py` | Per-site drills (5 sites, 2 neuter shapes each) — each drill reddens a distinctly-named test per §5. |
| `test_pre_matrix_entity_missing_guard.py` | Guard 1 — missing `person.<name>` entity → S6 + one-time NM note per boot. |
| `test_tracker_trust_excluded_60_flip_debounce.py` | Synthetic 60-flip minute → row-count ≤ N per I-M literal. |
| `test_house_state_transition_boot_suppression.py` | Restart mid-day; first post-boot emission is suppressed OR distinctly tagged with `trigger="boot"`. Both alternatives acceptable; test PIN the choice. |
| `test_away_transition_blocked_coalesce_and_restart_discharge.py` | D5 writer: coalesce within window; restart drains any suppression pending. |
| `test_phantom_retro_writer.py` | D4 writer basic emission. |

### VERIFY (existing tests, no change but re-run)

Full `PYTHONPATH=quality python3 -m pytest quality/tests/ -v` should stay green post-cycle;
name-diff vs develop baseline should be **+N new tests, 0 removed** where N matches the "NEW"
list above.

---

## §8 — Memory vocabulary additions (Scope B — D4/D5/D6/D7)

`const.py:3642` `MEMORY_EPISODE_TYPES` frozenset — MUST ADD (all four writers are
episode-type-gated):

- `"phantom_retro"` — D4 writer
- `"away_transition_blocked"` — D5 writer (with coalesce + restart discharge)
- `"tracker_trust_excluded"` — D6 writer (with 60s debounce per plan H3)
- `"house_state_transition"` — D7 writer (with first-tick boot suppression per plan H4)

`const.py:3660` `MEMORY_FACT_TOPICS` frozenset — verify each writer's fact rows use topics that
already exist; if not, add. To be enumerated at D4-D7 build time.

**Vocabulary-gate test:** `test_memory_vocabulary_pin.py` asserts each of the 4 new episode types
is a member of `MEMORY_EPISODE_TYPES` and any emit path that tries to write a non-member episode
raises at test time (existing `_assert_episode_type_allowed` gate covers this — verify at build).

---

## §9 — Frontend consumers (excluded from ripple set)

`frontend-v3/assets/Presence-CdANkhW1.js` (minified bundle) references entities including
`sensor.universal_room_automation_person_tracking_status`. Frontend consumes the sensor attribute,
not the internal `tracking_status` field on person_data dicts. Because the sensor attribute
passthrough at `sensor.py:3039/:3088` PRESERVES the string value with post-cycle-added
`tracking_reason` alongside, frontend behavior is:

- Value column: unchanged (`active` / `stale` / `lost`).
- Optionally: frontend can surface `tracking_reason` later; not required by this cycle.
- Deleted `lost_away_persons` attribute at `presence.py:5171-5182`: if the frontend or any
  dashboard reads it, migration required. **BUILD-TIME CHECK:** `grep -r "lost_away_persons"
  ~/Code/ura-dashboard-pwa /config/.storage` before delete.

---

## §10 — Completeness self-check (falsifiable invariant I-α coverage)

Per plan §"Falsifiable invariant":

- [x] Two pre-matrix guards enumerated: entity_missing (§3 :168), phone-left-behind (§5).
- [x] 16 matrix rows enumerated in §1 (row 15 deleted per rev-3.5).
- [x] Case-(b) never-collapses-to-LOST pin — §3 :365 disposition + §7 `test_case_b_never_lost.py`.
- [x] Row 14 liveness gate — §6 calibration knob + §7 `test_matrix_row_coverage.py`.
- [x] Row 16 fail-safe — §3 :385 unknown-path disposition + §8 D5 writer.
- [x] Ziri BLE-only worked example — §2.
- [x] 5 phone-left-behind consumers with 2 neuter shapes each — §5.
- [x] Vocabulary tightening (`bermuda_degraded`, `home_gps_only` retired) — §1 + §7.
- [x] Semantic widening of ACTIVE documented — §4.2 :5068-5079, §4.5 fan_veto, §4.6 const.py.
- [x] Path-β wholesale delete — §4.2 :5147-5182.
- [x] Test migration list — §7.
- [x] Historical lineage (H3 correct half preserved, over-reach corrected) — top of doc + §4.6.
- [ ] **PLATFORM VERIFICATION** for `device_tracker.jjs_iphone` / `ziri_iphone` — PENDING
      live-HA lookup at build-review time per §2 protocol.
- [ ] **path-α confidence threshold** for row-14 comparison — verify at build time; §6.

**Second-pass reviewer greps that MUST return zero new hits** (D1 acceptance criterion):

```
git grep -n "_tracking_active_or_lost_away"          # → 0 hits post-cycle
git grep -n "TRACKING_STATUS_LOST"                    # → still present in const.py + S5/S6 sites only
git grep -n "bermuda_degraded"                        # → 0 hits post-cycle
git grep -n "home_gps_only"                           # → 0 hits post-cycle
git grep -n "lost_away_persons"                       # → 0 hits post-cycle (attribute retired)
git grep -n "BLE_SILENT"                              # → 0 hits (H2 attr-only adoption; no enum)
```

Any nonzero return on the "0-hits" rows falsifies the completeness claim.
