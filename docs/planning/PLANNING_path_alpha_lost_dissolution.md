# PLANNING — Path-α LOST dissolution + memory writers for the new away logic

**Current rev:** 3.4 (2026-08-16). See §"Operator checkpoint history" at the end for the full rev chain (1 → 2 → 3 → 3.1 → 3.2 → 3.3 → 3.4).

**Rev-3.4 additions:** (a) live per-person source inventory folded in as concrete worked examples — Ziri is the canonical stress-case (SINGLE tracker), Oji is the maximal case (19 trackers incl. companion GPS + Bermuda BLE); (b) explicit **dynamic-source-inventory** constraint — the classifier reads the person entity's `attributes.source` list per evaluation, never bakes in who-has-what, because GPS presence is per-person MUTABLE config (operator: companion GPS is on for Oji + Ezinne "for now"); (c) D1 must verify entity-registry PLATFORM for `jjs_iphone` (Jaya) and `ziri_iphone` (Ziri) — router-tracker vs companion-without-permission determines which Matrix-B row Ziri lands on and validates the app-less discriminator.

**Cycle IDs:** PATH-ALPHA-DENOM-1 + MEMORY-WRITERS-1 + GUEST-FP-RESIDUALS-1 A1.
**Tier:** 2-DB. Rev-3.4 ready for dispatch pending operator sign-off.
**Depends on:** ZONE-TIER-DIVERGE-1 trace merged; MEMORY-COMPACTOR-1 shipped.
**Non-goal:** does NOT fix the phantom-zone / fan-loop side of AWAY-BLOCK-1.

---

## Household source inventory + worked examples (rev-3.4)

**Live inventory** (verified against `person.*` entities 2026-08-16; operator confirms):

| Person | # trackers | Companion GPS | Bermuda BLE | Router/other | Notes |
|---|---|---|---|---|---|
| **person.oji_udezue** | 19 | ✓ `phalanxiphone15promax` (companion app, GPS) | ✓ `iphone_oji_bermuda_tracker` | fleet of device/network trackers | **Maximal case** — full 3-axis Matrix-A applies. Worked example: A1-A12. |
| **person.ezinne** | 2 | ✓ `ezinne_iphone` (companion GPS per operator) | ✓ `ezinne_iphone_bermuda_tracker` | — | Matrix-A applies (GPS + BLE, no router listed for this person). |
| **person.jaya** | 3+ | ✗ operator says no companion GPS | ✓ `private_ble_device_249050` + bermuda BLE | `jjs_iphone` — **platform TBD in D1** (likely router/UniFi; possibly companion-sans-location-permission) | Matrix-B applies. Whether `jjs_iphone` reports `not_home` on network departure or `unknown` on companion-without-permission determines row 3B vs 6B fallthrough for Jaya. |
| **person.ziri** | 1 | ? | ? | `ziri_iphone` ONLY | **CANONICAL APP-LESS STRESS CASE** — a single tracker. D1 verification: is `ziri_iphone` a router device_tracker (source_type=router → not_home on `consider_home` timeout = row 3B AWAY) or companion-without-GPS-permission (source_type=gps but state=unknown = row 6B LOST-no-signal)? This one entity-registry platform lookup determines whether Ziri is app-less-router-tracked (works) or app-broken (visible in `tracker_sources` diagnostic as `no_signal`, surfaced for operator remediation). |

**Worked example — Ziri (minimal, Matrix-B, single tracker):**

- IF `ziri_iphone` platform == `router`/`unifi`/`dhcp`/similar network integration:
  - Ziri at home + on WiFi → WiFi=`home`, BLE=`absent`, → HA aggregates `person.ziri.state == "home"` → Matrix-B row **8B** (`ACTIVE`, `bermuda_degraded` — reason string is a misnomer here since he has no BLE, but the value "no away-vote" is right; refine reason value if needed at build).
  - Ziri leaves house, `consider_home` elapses → WiFi=`not_home`, BLE=`absent` → HA aggregates `person.ziri.state == "not_home"` → Matrix-B row **7B** (`ACTIVE`, `away_wifi_only`, confidence 0.90) → **AWAY vote**.
  - Router integration breaks → WiFi=`unavailable`, BLE=`absent` → HA aggregates `unknown` → Matrix-B row **6B** (`LOST`, `no_signal`, confidence 0.0) → excluded from denominator.
- IF `ziri_iphone` platform == `mobile_app` (companion) but GPS permission never granted / device_tracker perpetually `unknown`:
  - Every classification lands in row **6B** (`no_signal`, excluded). Ziri **never votes** — a silent structural disenfranchisement. **THE `tracker_sources` DIAGNOSTIC ATTR SURFACES THIS**: `tracker_sources: {gps: "unknown", router: "missing", ble: "missing"}` on `person.ziri`'s aggregation sensor → operator-visible in dev-tools → operator-owned remediation (grant permission, add router tracker, or install BLE beacon). Plan does NOT silently work around this; D1 artifact surfaces it as a live-config gap.

**Worked example — Oji (maximal, Matrix-A, 19 trackers):**

- Home, all sources coherent → Matrix-A row **1A** (`ACTIVE`, `bermuda`, no away-vote).
- Leaves house, companion GPS updates first → Matrix-A row **8A** briefly (WiFi still home in `consider_home` window) → then row **4A** once WiFi disassociates + BLE decays (`ACTIVE`, `away_all_agree`, confidence 0.99) → **AWAY vote with maximum confidence**.
- Phone left on kitchen counter, Oji leaves → GPS may go stale (`home_zone` cached) OR update to `not_home` slowly; BLE stays visible@kitchen; WiFi stays `home`. Camera census sees Oji-elsewhere or no unidentified: **`PersonPhoneLeftBehindSensor` fires** → `_phone_trustworthy` returns False → Oji excluded from trusted denominator with `phone_left_behind=on`. Matrix cell would be **5A** (`phone_left_behind_confirmed`) but the H2 exclusion runs first and neutralizes the vote regardless. **No modeling gap.**
- Faraday moment (elevator, tunnel): all sources briefly go `unknown` → Matrix-A row **11A** (`no_signal`, excluded). Row is short-lived; recovers on emergence.

**Worked example — Jaya:**

- If `jjs_iphone` is router: same shape as Ziri (Matrix-B). Row 3B on departure.
- If `jjs_iphone` is companion-without-permission and reports `unknown` state permanently: Matrix-B row 6B (`no_signal`) — Jaya never votes. But Jaya has BLE (`private_ble_device_249050` + bermuda BLE), so when at home BLE reads home-room → Matrix-B row 1B (`ACTIVE`, `bermuda`, no away-vote). When BLE decays and phone (companion) still reports `unknown`, Jaya lands in row 6B (`no_signal`) and does NOT vote — safe but silent. D1 platform lookup + operator decision on whether this is acceptable.

**Dynamic-source-inventory constraint (rev-3.4, load-bearing):**

The classifier MUST read the person entity's `attributes.source` list — and each source entity's live state — **per evaluation tick**, never cache the tracker inventory at coordinator init. Rationale:

- **Operator verbatim:** *"'for now' — GPS presence is per-person MUTABLE config."*
- Operator adds/removes/reinstalls the companion app; permission grants/revokes; a person switches phones and the tracker's underlying entity swaps.
- Baked-in assumptions ("Oji has GPS, Ziri doesn't") turn into stale wrongness the moment config changes.
- The check is cheap: `hass.states.get("person.<name>").attributes.get("source", [])` is a hash-map lookup; iterating N sources per person per tick is N ≤ ~20 for the maximal case, well inside the 5-min tick budget.

**Implementation contract (folded into D2a):**

```python
def _person_source_snapshot(person_state) -> dict:
    """Read the live tracker inventory for this person, this tick.

    NEVER cache this at coordinator init — GPS presence is per-person
    mutable config (operator adds/removes companion app; permission
    grants/revokes). The A-vs-B matrix choice depends on the LIVE
    state of the source list, not a one-time enumeration.
    """
    sources = person_state.attributes.get("source", []) or []
    snapshot = {"gps": "missing", "router": "missing", "ble": "missing"}
    for entity_id in sources:
        source_state = hass.states.get(entity_id)
        if not source_state:
            continue
        source_type = source_state.attributes.get("source_type") or _infer_source_type(entity_id)
        # source_type ∈ {"gps", "router", "bluetooth_le", "bluetooth", ...}
        # HA convention: "gps" for companion app + geo trackers,
        #                "router" for network-based, "bluetooth_le" / "bluetooth" for BLE.
        if source_type == "gps":
            snapshot["gps"] = source_state.state
        elif source_type == "router":
            snapshot["router"] = source_state.state
        elif source_type in ("bluetooth_le", "bluetooth"):
            snapshot["ble"] = source_state.state
    return snapshot
```

The classifier's matrix-A-vs-B branch is `snapshot["gps"] != "missing"`. The `_tracker_sources` diagnostic attr is populated from the same snapshot.

**D1 verification requirements (rev-3.4 additions):**

- **Pull entity-registry platform for `person.oji_udezue`'s 19 trackers, `person.ezinne`'s 2, `person.jaya`'s trackers (esp. `jjs_iphone`), and `person.ziri.ziri_iphone` (CRITICAL — single-tracker).** State per tracker: `platform`, `source_type`, `can-report-not_home` verdict.
- **State the expected matrix (A or B) for each person** in the D1 artifact, and cross-reference the worked examples above.
- **Flag Ziri explicitly** as the canonical stress case; if `ziri_iphone` platform is `mobile_app` and state is stably `unknown`, D1 records this as a live-config gap for operator remediation before the plan builds. (Alternative: build proceeds; Ziri lands in row 6B and never votes; operator accepts + remediates later. Operator's call at plan-review time.)
- **D1 acceptance:** the artifact makes the current household's coverage of case-a legible per-person — the operator can read "Ziri can vote away iff `ziri_iphone` platform == router" as a factual statement backed by entity-registry evidence.

**Live D validation (rev-3.4 additions):**

- Verify each of the 4 configured persons lands in the expected matrix over 24h; each person's `tracker_sources` attr shows the live inventory; any person stably in row 6B for the whole window is called out.
- Verify that if the operator adds or removes a companion-app permission during the window (any time-of-day), the classifier's matrix branch flips on the NEXT tick — dynamic-inventory contract satisfied.

---

## Rev-3.3 content preserved

**Evidence hierarchy (rev-3.3 — operator-ratified):**

Signals ranked by away-evidence strength (operator: *"BLE trackers not seeing a phone can be definitive. But seeing their path out through egress beacons or network not there is higher confidence. Small chances it's phone dead or a faraday cage — but smaller chances."*):

1. **GPS affirmatively `not_home` or named-non-home zone** — SINGLE STRONGEST for a GPS-holder. Overrides BLE/WiFi ambiguity. Confidence 0.98.
2. **WiFi `not_home` + BLE silent + GPS `not_home`** — three independent signals agree. Confidence 0.99 (all-agree cell).
3. **WiFi `not_home` + BLE silent (GPS absent or unknown)** — two independent local signals agree. Confidence 0.95. Named residuals retired: WiFi + BLE both failing simultaneously for a device physically at home is extremely unlikely; would be visible in `tracker_sources`.
4. **BLE silent alone** (WiFi absent for this person, GPS absent) — STRONG away evidence with named residuals: phone dead, faraday cage. Rare. Confidence 0.85. NOT weak or ambiguous.
5. **WiFi `not_home` alone** (BLE absent, GPS absent) — STRONG. Confidence 0.90.
6. **Exterior-path (transit_validator egress witness) — FUTURE THIRD BOOSTER**, not built this cycle. If ever consumed, combines with BLE-silence + WiFi-gone to push confidence to 0.99. Matrix reserves comment; no code hook.

**Phone-left-behind integration (rev-3.3):** existing machinery — `PersonPhoneLeftBehindSensor` (binary_sensor.py:1681), `_phone_trustworthy` (presence.py:176-190), `TRANSIT_PHONE_LEFT_BEHIND_HOURS` (const.py:829) — retires the BLE-visible + person-away confounder. H2 pre-filter runs BEFORE trusted-denominator vote consumption; matrix cells 5A / 12A / 4B route through H2. Scope A does not modify H2; D2 acceptance verifies precedence.

---

## THE MATRIX

### Matrix-A (GPS-holders, 3-axis)

For persons with a live companion-app GPS device_tracker (`tracker_sources.gps != "missing"`).

| # | WiFi | BLE | GPS | HA `person.state` | Reading | `tracking_status` | `tracking_reason` | Conf | I-α vote |
|---|---|---|---|---|---|---|---|---|---|
| 1A | `home` | visible@home_room | `home_zone` | `home` | All three agree home | `ACTIVE` | `bermuda` | 0.95 | no |
| 2A | `home` | `silent` | `home_zone` | `home` | At home, BLE cold | `LOST` | `home_ble_silent` | 0.85 | excluded |
| 3A | `not_home` | `silent` | `home_zone` | `home` (GPS wins) | **Contradictory**: GPS stale/cached | `ACTIVE` | `anomalous_gps_stale_local_gone` | 0.5 | excluded |
| 4A | `not_home` | `silent` | `not_home`/zone | `not_home` | **All-agree away** | `ACTIVE` | `away_all_agree` | 0.99 | **AWAY** |
| 5A | `not_home` | visible@home_room | `not_home` | `not_home` | **Phone-left-behind confirmed** (H2 detects) | `ACTIVE`, **H2-EXCLUDED** | `phone_left_behind_confirmed` | 0.95 | excluded (H2) |
| 6A | `home` | visible@home_room | `not_home` | `home` (WiFi+BLE win) | GPS lag — person just arrived | `ACTIVE` | `anomalous_gps_lag_arrival` | 0.85 | no |
| 7A | `unavailable`/`absent` | `silent` | `home_zone` | `home` | GPS-only home | `ACTIVE` | `home_gps_only` | 0.7 | no |
| 8A | `unavailable`/`absent` | `silent` | `not_home`/zone | `not_home` | GPS-only away (router down) | `ACTIVE` | `away_gps_only` | 0.9 | **AWAY** |
| 9A | `home` | `silent` | `unknown` | `home` | GPS permission decayed; collapse to 2B | `LOST` | `home_ble_silent` | 0.85 | excluded |
| 10A | `not_home` | `silent` | `unknown` | `not_home` | GPS decayed; collapse to 3B | `ACTIVE` | `away_wifi_silent_local` | 0.95 | **AWAY** |
| 11A | `unavailable` | `unavailable` | `unknown` | `unknown` | Total infra failure | `LOST` | `no_signal` | 0.0 | excluded |
| 12A | `not_home` | visible@home_room | `unknown` | `not_home` | Phone-left-behind suspected (GPS didn't confirm) | `ACTIVE`, **H2-EXCLUDED** | `phone_left_behind_suspected` | 0.7 | excluded (H2) |

### Matrix-B (non-GPS-holders, 2-axis)

For persons with no live companion-app GPS (`tracker_sources.gps == "missing"`).

| # | WiFi | BLE | HA `person.state` | Reading | `tracking_status` | `tracking_reason` | Conf | I-α vote |
|---|---|---|---|---|---|---|---|---|
| 1B | `home` | visible@home_room | `home` | At home, WiFi+BLE agree | `ACTIVE` | `bermuda` | 0.9 | no |
| 2B | `home` | `silent` | `home` | At home, BLE cold | `LOST` | `home_ble_silent` | 0.85 | excluded |
| 3B | `not_home` | `silent` | `not_home` | Both local signals agree away | `ACTIVE` | `away_wifi_silent_local` | 0.95 | **AWAY** |
| 4B | `not_home` | visible@home_room | `not_home` (WiFi wins) | Phone-left-behind suspected | `ACTIVE`, **H2-EXCLUDED** | `phone_left_behind_suspected` | 0.7 | excluded (H2) |
| 5B | `absent` | visible@home_room | `home` | BLE-only person at home | `ACTIVE` | `bermuda` | 0.85 | no |
| 6B | `absent`/`unavailable` | `silent`/`unavailable`/`absent` | `unknown` | Genuine no-signal | `LOST` | `no_signal` OR `no_trackers_configured` | 0.0 | excluded |
| 7B | `not_home` | `unavailable`/`absent` | `not_home` | WiFi-only away, BLE broken/absent | `ACTIVE` | `away_wifi_only` | 0.9 | **AWAY** |
| 8B | `home` | `unavailable`/`absent` | `home` | WiFi-only home | `ACTIVE` | `bermuda_degraded` | 0.85 | no |

**Person entity missing entirely:** matrix-independent — `LOST` + `entity_missing`, confidence 0.0, excluded.

**Completeness (mechanical):** every reachable (WiFi, BLE, GPS-if-present) tuple maps to exactly one row across the two tables. Reviewer C's completeness check = per-row synthetic fixtures (12 in A + 8 in B) + unenumerated-cell guard test.

---

## Falsifiable invariant (rev-3.3 + rev-3.4 dynamic-inventory)

> **I-α:** A person tracker's contribution to `all_tracked_persons_away` is governed by (1) the matrix (Matrix-A applies iff `tracker_sources.gps != "missing"` **as read live per tick, never cached**; otherwise Matrix-B); AND (2) the H2 `_phone_trustworthy` filter, which runs FIRST and can exclude any person from the trusted denominator regardless of matrix classification.
>
> **A person contributes an away-vote iff:** (a) `_phone_trustworthy(person)` returns True, AND (b) the person's (WiFi, BLE, GPS-if-present) tuple resolves to a matrix row marked **AWAY** in "I-α vote."
>
> **A tracker with no location signal, or a phone-left-behind person, can NEVER contribute an away vote.**
>
> **Source-agnostic:** classifier consumes `person.<name>.state` via HA aggregation; matrix branch determined by LIVE per-person source inventory, never baked-in.
>
> **Degradation:** GPS `unknown`/`absent` collapses Matrix-A to Matrix-B — degradation, never wrongness.
>
> **Discriminator:** WiFi `not_home` (device left network) is affirmative; WiFi `unavailable` (integration broken) is not.
>
> **Dynamic-inventory (rev-3.4):** classifier reads `person.<name>.attributes.source` per evaluation tick; adding/removing a companion app (GPS permission grant/revoke, app install/uninstall, phone swap) flips the matrix branch on the next tick without code change.

Break the invariant → plan falsified. D produces per-row fixtures (20 total) + phone-left-behind fixtures + dynamic-inventory fixtures.

**I-M** on write-rate discipline: unchanged.

---

## Institutional context verified (all revs, current state)

- `TRACKING_STATUS_{ACTIVE,STALE,LOST}` — const.py:167-169. REUSED unchanged in vocabulary; comments updated (H1/L2).
- `_tracking_active_or_lost_away` (presence.py:169) — DELETED in D2b.
- `person_state` (HA `person.<name>` entity) at `person_coordinator.py:150`, branched at :352 and :394-432. Current 2-way replaced with 3-way (C1) driven by matrix helpers (rev-3.2/3.3/3.4).
- `person.<name>.attributes["source"]` — REUSED as live per-tick source of truth for per-person tracker inventory (rev-3.1/3.4).
- Path-β relaxed-denominator block (presence.py:5147-5182) + `lost_away_persons` attr — DELETED wholesale in D2b.
- **NEW attributes `tracking_reason` + `tracker_sources`** on the person_data dict / per-person sensor. Diagnostic only; never trust gates.
- All rev-3 consumer sites (aggregation classifier :5490-5525 + display selectors + string-literal gates + camera_census + fan_veto + presence.py:5136 + person_coordinator :168/:294/:391 + the five test files).
- **HA `device_tracker` `consider_home` semantics** — router integrations transition `not_home` on timeout (affirmative), `unavailable` only on integration failure.
- **`PersonPhoneLeftBehindSensor`** (binary_sensor.py:1681) + **`_phone_trustworthy`** (presence.py:176-190) + **`TRANSIT_PHONE_LEFT_BEHIND_HOURS`** (const.py:829) — REUSED as H2 pre-filter; Scope A does not modify.
- **`TRACKING_REASON_VALUES` frozenset** (rev-3.2, expanded rev-3.3) — new registry with WARN gate on unregistered writes:

```python
TRACKING_REASON_VALUES: Final = frozenset({
    "bermuda", "bermuda_degraded",
    "home_ble_silent", "home_gps_only",
    "away_all_agree", "away_wifi_silent_local", "away_gps_only", "away_wifi_only",
    "anomalous_gps_stale_local_gone", "anomalous_gps_lag_arrival",
    "phone_left_behind_confirmed", "phone_left_behind_suspected",
    "no_signal", "entity_missing", "no_trackers_configured",
})
```

---

## H2 adoption note (rev-3, unchanged)

BLE_SILENT enum DROPPED; `tracking_reason` attribute on existing enum values. Case-(b) BLE-silent-at-home stays under `LOST` with `tracking_reason=home_ble_silent`. All LOST sub-cases distinguished by `tracking_reason`. Zero enum surface change.

## Memory intent & limits — unchanged from rev-2/rev-3

## Why occupancy flips are memory-ineligible — unchanged from rev-2/rev-3

---

## Scope A — LOST-state dissolution

### D1 — Consumer enumeration artifact (rev-3.4 requirements)

Filed as `docs/planning/AUDIT_tracking_status_consumers.md`. Contents:

- Full consumer inventory (all rev-3 sites).
- H2 phone-left-behind machinery section (rev-3.3).
- **Per-person tracker inventory table with entity-registry PLATFORM per tracker** (rev-3.4) — pull `platform` and `source_type` for every tracker on person.oji_udezue (19), person.ezinne (2), person.jaya (3+, esp. `jjs_iphone`), person.ziri (1 = `ziri_iphone`).
- **Expected matrix (A/B) per person** + row coverage.
- **Ziri stress-case call-out** — is `ziri_iphone` router (works, row 3B on departure) or companion-without-permission (silent, row 6B)? Live-config gap surfaced.

### D2 — Classifier rewrite

**D2a — `person_coordinator.py` 3-way conditional with matrix-driven helpers + dynamic-inventory contract.** Pseudocode from rev-3.2 preserved. Helper functions (`_classify_home_side`, `_classify_away_side`, `_classify_no_signal`) call `_person_source_snapshot(person_state)` per-tick to decide Matrix-A vs Matrix-B branch and to match the (WiFi, BLE, GPS?) tuple to a matrix row. **Explicit contract: no coordinator-init caching of per-person source inventory** (rev-3.4).

Phone-left-behind respect (rev-3.3): Scope A does not touch H2; H2 pre-filter at :5122 runs first, exclusion holds regardless of matrix classification. Regression test in D-tests verifies precedence.

**D2b — presence.py path-β wholesale delete** (C3(a)): unchanged.

**D2c — aggregation.py `tracking_reason` + `tracker_sources` passthrough**: unchanged from rev-3.1/3.2/3.3.

**D2d — const.py `TRACKING_REASON_VALUES` frozenset + comment updates**: unchanged.

**D2 acceptance criteria (all revs consolidated):**

- I-α holds for every legal-config repro (per matrix row).
- `_tracking_active_or_lost_away` and `lost_away_persons` are gone.
- `tracking_reason` populated at every stamp site; every value ∈ `TRACKING_REASON_VALUES`.
- `tracker_sources` populated per tick; **read live from `person.<name>.attributes.source`, never cached** (rev-3.4 mutation drill: swap a person's source list mid-test → next-tick classification reflects the new inventory).
- 20 matrix-row fixtures assert classifier output.
- Phone-left-behind fixture: H2 exclusion holds ahead of vote consumption for rows 5A/12A/4B.
- GPS degradation fixture: Matrix-A person forced GPS=`unknown` → next-tick reclassifies to Matrix-B rows.
- **Ziri worked-example fixture** (rev-3.4): configure a single-tracker person; verify Matrix-B row selection based on the tracker's `source_type`; the `no_trackers_configured`/`no_signal` case surfaces via `tracker_sources`.
- `_person_was_away` preservation (M3): mutation-drill neuters case-(a) write → BLE pre-arrival test reddens.
- `person_coordinator.py:168` disposition = `entity_missing` (M5).
- `person_coordinator.py:294` dead-gate deleted (L1).
- Live: each of 4 configured persons lands in expected matrix over 24h; anomalous rows captured; phone-left-behind exclusion visible; dynamic-inventory flip observable if operator toggles a permission mid-window.

### D3 — Rider

Guest-FP diagnostic classifier keys on `tracking_reason` (expanded vocabulary).

---

## Scope B — memory writers (unchanged from rev-3)

D4 `occupancy_phantom_retro`, D5 `away_transition_blocked`, D6 `tracker_trust_excluded` (H3 debounce, `TRACKER_TRUST_MIN_HOLD_S=60s`), D7 `house_state_transition` (H4 boot suppression). Drops: `zone_phantom`, exterior multi-source witnesses.

---

## D-tests deliverable (all revs consolidated)

- **DELETE / MIGRATE:** `test_v570_fixup_wiring.py`, `test_v570_guest_detection_trust.py` — assertions on `_tracking_active_or_lost_away` / `lost_away_persons` migrated to case-a fixtures under I-α.
- **VERIFY UNCHANGED:** `test_census_ble_cancel_unrecognized.py`, `test_cycle4_slim.py`, `test_v4714_1_forgotten_phone_hotfix.py`.
- **NEW Scope A:** `test_path_alpha_lost_dissolution.py`, `test_ble_pre_arrival_after_case_a.py`, `test_case_c_no_signal_denominator_exclusion.py`, `test_tracking_reason_attribute_roundtrip.py`, `test_case_a_router_only_person.py`, `test_case_a_permission_decay.py`, `test_case_c_router_unavailable.py`, `test_tracker_sources_attribute.py`, `test_matrix_a_row_coverage.py` (12 params), `test_matrix_b_row_coverage.py` (8 params), `test_tracking_reason_registry_gate.py`, `test_matrix_unenumerated_cell_guard.py`, `test_phone_left_behind_h2_precedence.py`, `test_gps_degradation.py`, **`test_dynamic_source_inventory_flip.py`** (rev-3.4 — swap tracker inventory mid-test, assert next-tick matrix branch flips), **`test_ziri_single_tracker_case.py`** (rev-3.4 — worked-example fixture).
- **NEW Scope B:** `test_occupancy_phantom_retro_writer.py`, `test_away_transition_blocked_writer.py`, `test_tracker_trust_excluded_writer.py`, `test_tracker_trust_excluded_debounce_60_flips.py`, `test_house_state_transition_boot_suppression.py`, `test_house_state_transition_roundtrip.py`.

---

## Deliverables summary

| ID | Description | Files touched |
|---|---|---|
| D1 | Consumer enumeration + per-person tracker inventory + platform verification + Ziri stress-case | `docs/planning/AUDIT_tracking_status_consumers.md` |
| D2a | person_coordinator 3-way conditional + matrix-driven helpers + dynamic-inventory contract + :168/:294/:391 dispositions | `person_coordinator.py` |
| D2b | presence.py path-β wholesale delete + helper delete + `lost_away_persons` attr retire | `domain_coordinators/presence.py` |
| D2c | aggregation.py `tracking_reason` + `tracker_sources` passthrough | `aggregation.py` |
| D2d | const.py comment updates + `TRACKING_REASON_VALUES` frozenset | `const.py` |
| D3 | Guest-FP diagnostic classifier keys on `tracking_reason` | `domain_coordinators/presence.py` |
| D4 | `occupancy_phantom_retro` writer + registry + compactor rule | `const.py`, `coordinator.py`, `memory_compactor.py` |
| D5 | `away_transition_blocked` writer + registry + fact topic + compactor rule | `const.py`, `domain_coordinators/presence.py`, `memory_compactor.py` |
| D6 | `tracker_trust_excluded` writer + H3 debounce + registry + fact topic + compactor rule | `const.py`, `domain_coordinators/presence.py`, `memory_compactor.py` |
| D7 | `house_state_transition` writer + H4 boot suppression + registry | `const.py`, `domain_coordinators/presence.py`, `memory_compactor.py` |
| D-tests | Full test set per §"D-tests deliverable" | `quality/tests/*` |

**Non-goals (consolidated):**

- Does NOT fix the phantom-zone side of AWAY-BLOCK-1.
- Does NOT build `zone_phantom` or exterior multi-source witnesses.
- Does NOT introduce memory-driven actuation.
- Does NOT add BLE_SILENT enum (H2 adopted — attribute-only).
- Does semantically widen `TRACKING_STATUS_ACTIVE` (string unchanged; person_state-derived confident locations now qualify).
- Does NOT touch sleep-only trust doctrine.
- Does NOT add exterior-path/transit signal to case-(a).
- Does NOT special-case any tracker source type in the classifier — reads HA aggregation via `person_state.state`.
- Does NOT gate on which sources a person "should have" — the plan surfaces inventory diagnostically; remediation is operator-owned.
- Does NOT introduce weighted confidence into consumer decisions this cycle.
- Does NOT cache per-person tracker inventory at coordinator init (rev-3.4 dynamic-inventory contract).
- Does NOT modify H2 `_phone_trustworthy` filter or `PersonPhoneLeftBehindSensor`.
- Does NOT re-implement HA's person-entity aggregation logic.

---

## Tier-2-DB review framings

- **Review A** — correctness + matrix completeness: every stamp site produces matrix-defined output; helpers total over reachable inputs; `TRACKING_REASON_VALUES` gate fires; **dynamic-inventory contract holds** (rev-3.4).
- **Review B** — cross-coordinator + H2 respect + no-flap + restart: path-β delete correct; H2 pre-filter runs first; fan_veto unchanged; matrix confidence values diagnostic-only; `tracker_sources` not hot path; person-entity aggregation not re-implemented.
- **Review C** — mechanical completeness: 20 matrix-row source-mutation drills + H2 precedence + GPS degradation + **dynamic-inventory flip** + **Ziri single-tracker** drills each redden a NAMED test.

**Live D** — per-person matrix cells observed; `tracker_sources` populated per person; anomalous rows captured; phone-left-behind exclusion visible; **dynamic-inventory flip observable** if operator toggles permission in-window; Ziri classification observed and matches D1 platform verdict.

**Post-restart README write-back** per CLAUDE.md.

---

## Vibememo / Sequencing — unchanged from rev-2/rev-3

---

## Operator checkpoint history

- **Rev-1:** 6 design choices.
- **Rev-2:** all 6 accepted; 4 writers built this cycle; 2 dropped, 0 parked; companion GPS incorporated; exterior-path DROP; memory-ineligible rationale; vibememo directive.
- **Rev-3:** C1 (unknown-state leak) + C2 (aggregation classifier) + C3 (path-β wholesale delete) resolved; H2 adopted (BLE_SILENT enum DROPPED; `tracking_reason` attr); H1/H3/H4 folded; D-tests deliverable.
- **Rev-3.1:** app-less-person constraint — source-agnostic ladder via HA `person` aggregation; permission-decay graceful; `not_home` (affirmative) vs `unavailable` (broken) discriminator; per-person `tracker_sources` diagnostic (no new entity); four fixtures.
- **Rev-3.2:** matrix as authoritative organizing structure (16 rows); `TRACKING_REASON_VALUES` frozenset with WARN gate; classifier helpers matrix-driven; reviewer C mechanical completeness.
- **Rev-3.3:** (1) evidence hierarchy corrected — BLE-silence is STRONG (not weak) with named residuals; confidence values re-ordered per operator ranking (GPS-agree > all-agree > two-local-agree > single-source > infra-fail); exterior-path noted as future third booster. (2) Existing phone-left-behind machinery integrated: cells 5A/12A/4B route through H2 pre-filter; Scope A does not modify H2 but verifies precedence. (3) GPS first-class: Matrix-A (3-axis, 12 rows) for GPS-holders + Matrix-B (2-axis, 8 rows) for non-holders; same `tracking_reason` vocabulary; GPS `unknown`/`absent` collapses axis (degradation, never wrongness).
- **Rev-3.4 (2026-08-16):** live per-person source inventory folded in — Oji (19 trackers, maximal Matrix-A), Ezinne (2, Matrix-A), Jaya (3+, Matrix-B pending `jjs_iphone` platform lookup), **Ziri (1 tracker = canonical app-less stress case, D1 must verify `ziri_iphone` platform)**. Worked examples for Ziri and Oji added. **Dynamic-source-inventory contract** made load-bearing — classifier reads `person.<name>.attributes.source` per evaluation tick, never caches — operator emphasis: *"'for now' — GPS presence is per-person MUTABLE config."* D1 must pull entity-registry platform for every tracker across all 4 persons; Ziri stress-case flagged for operator review before build. D-tests grows by 2 (dynamic-inventory flip + Ziri single-tracker). **Ready for build dispatch pending operator sign-off on the matrix + evidence hierarchy + H2 integration + H2 adoption + app-less ladder + dynamic-inventory contract + Ziri D1 outcome.**
