# PATH-ALPHA Tier 2-DB Review A — Correctness + Invariant Integrity

**Branch reviewed:** `feature/path-alpha` (worktree `.claude/worktrees/path-alpha-build`) vs `develop`
**Spec:** `docs/planning/PLANNING_path_alpha_lost_dissolution.md` rev-3.5.1 (normative 16-row matrix), `docs/planning/AUDIT_tracking_status_consumers.md` (D1)
**Framing:** local correctness + invariant integrity (I-α) — hostile inputs across the full 16-row matrix + pre-matrix guards, row-tier confidence floor, Gap A wiring, liveness-gate discipline, per-tick dynamic inventory
**Date:** 2026-08-16
**Reviewer:** ura-reviewer (framing A, independent of B/C)

---

## Verdict — SHIP

**Falsifiable invariant I-α ("a tracker with NO location signal can NEVER contribute an away vote") HOLDS across every reachable path I could enumerate**, including the pre-matrix `entity_missing` guard, all 16 matrix rows, the two outer wrapper branches (Bermuda-sensor-unresolved and no-Bermuda-sensor), and the HA-aggregation fallback. Three independent source-mutation drills each reddened a specifically-named test. No CRITICAL or HIGH findings. Four sub-critical findings below (1 MEDIUM, 3 LOW) — none block ship.

---

## Drills (independent re-runs, cache-purged, `PYTHONDONTWRITEBYTECODE=1`)

Each drill mutated ONE load-bearing site in `person_coordinator.py`, ran the covering test file, verified the specifically-named test failed, then restored via backup and re-verified `git status --porcelain` clean on the touched file.

| # | Mutation site | Expected red test | Result |
|---|---|---|---|
| A-D1 | `_classify_matrix_row` row 16 stamp `TRACKING_STATUS_LOST/"unknown"` → `TRACKING_STATUS_ACTIVE/"away"` (would violate I-α) | `test_no_signal_never_votes_away`, `test_matrix_row_coverage[row16_no_signal]`, `test_matrix_row_coverage[row14_liveness_gate_degrades]` | 3 failed, 18 passed — **PASS** (invariant test caught it) |
| A-D2 | Case-(b) home stamp `TRACKING_STATUS_ACTIVE/"home"/home_ble_silent` → `TRACKING_STATUS_LOST/"unknown"/no_signal` (would violate rev-3.5.1 pin) | `test_case_b_never_lost`, `test_matrix_row_coverage[row2_…]`, `test_matrix_row_coverage[row3_…]` | 3 failed, 18 passed — **PASS** |
| A-D3 | BLE liveness gate `if ble=="silent" and not ble_liveness_provable: ble="indeterminate"` → dead-branched (`if False and …`) so BLE=silent always admissible regardless of fleet liveness | `test_matrix_row_coverage[row14_liveness_gate_degrades]` | 1 failed, 20 passed — **PASS** (liveness gate is load-bearing) |

Restore verified after each drill: `git status --porcelain custom_components/universal_room_automation/person_coordinator.py` empty.

---

## Hostile-input enumeration — 16 rows + guards

I hand-traced the classifier (`person_coordinator.py:274-382`) plus the two outer wrappers (`:644-727`, `:729-803`) against every combination in the rev-3.5.1 matrix. Notation: G/W/B ∈ axes' allowed values including MISSING.

| Cell class | Reachable stamp | I-α vote | Notes |
|---|---|---|---|
| Pre-matrix S6 `entity_missing` (`:413-449`) | LOST + unknown + `entity_missing` + one-time WARN | excluded ✓ | Fail-safe branch; `_person_lost_since`/`_lost_away_since` stamped for grace timing. |
| Row 1 (Bermuda BLE-visible@home_room, `:506-525`) | ACTIVE + `<room>` + `bermuda` + BLE="visible" | no vote (blocks away) ✓ | Confidence via `_calculate_confidence`. Room-level location. |
| Row 2 (G=home, W=home, B=silent+live) | ACTIVE + home + `home_ble_silent` conf 0.85 | no vote ✓ | |
| Row 3 (G=home, W=home, B=indet/MISSING) | ACTIVE + home + `home_ble_silent` conf 0.80 | no vote ✓ | |
| Row 4 (G=home, W=not_home) | ACTIVE + home + `anomalous_gps_stale_local_gone` conf 0.5 | no vote (S4 defer) ✓ | Note: this cell fires REGARDLESS of BLE axis — subsumes what plan-table Row-4/Row-5-BLE-silent split. Correct fallthrough since row-5 BLE-visible-in-home-room is intercepted by the Bermuda-authoritative branch upstream (see L1). |
| Row 6 (G=away, W=not_home, any B) | ACTIVE + away + `away_all_agree` conf 0.99 | **AWAY** ✓ | |
| Row 7 (G=away, W=not_home, B=visible@home) | overridden by O1 phone-left-behind at the 5 consumer sites; classifier stamps `away_all_agree` — H2 excludes | excluded via O1 ✓ | H2 filter is caller-side (not classifier); framing B territory. |
| Row 8 (G=away, W=home) | ACTIVE + home + `anomalous_gps_lag_arrival` conf 0.85 | no vote ✓ | |
| Row 9 (G=away, W∈{unavailable,MISSING}) | ACTIVE + away + `away_gps_only` conf 0.92 | **AWAY** ✓ | |
| Row 10 (G=home, W∈{unavailable,MISSING}) | ACTIVE + home + `home_ble_silent` conf 0.75 | no vote ✓ | Handled via the `gps_home and wifi in ("unavailable","MISSING")` branch at `:320-323`. |
| Row 11 (G∈{unk,MISSING}, W=not_home, B=silent+live) | ACTIVE + away + `away_wifi_silent_local` conf 0.95 | **AWAY** ✓ | |
| Row 12 (G∈{unk,MISSING}, W=not_home, B=visible@home) | O1 territory; classifier alone would stamp `away_wifi_silent_local` (BLE degraded from `visible` since caller passes silent/MISSING inside the classifier). H2 exclusion at 5 consumers takes precedence. | excluded via O1 ✓ | |
| Row 13 (G∈{unk,MISSING}, W=not_home, B∈{indet,MISSING}) | ACTIVE + away + `away_wifi_only` conf 0.90 | **AWAY** ✓ | |
| Row 14 (G∈{unk,MISSING}, W∈{unavail,MISSING}, B=silent+live) | ACTIVE + away + `away_ble_silent_only` conf `BLE_SILENT_ONLY_AWAY_CONFIDENCE`=0.82 | **AWAY** ✓ (below path-α threshold 0.9 — Ziri cannot solo-flip) | Liveness gate `_ble_fleet_live` degrades to indeterminate if fleet not proven live → falls to row 16. |
| Row 15 (DELETED rev-3.5) | n/a | n/a | Verified: no code path produces the retired hedge. |
| Row 16 (G∈{unk,MISSING}, W∈{unavail,MISSING}, B∈{indet,MISSING}) | LOST + unknown + `no_signal` conf 0.0 | excluded ✓ | S5 fail-safe. Only intentional non-vote cell. |

**HA-aggregation fallback (`:362-377`):** When source-derivation is silent but HA person `state` is "home"/"not_home"/named-zone, classifier stamps S2/S3 respectively. This is the "source-agnostic ladder" rev-3.1 constraint. I-α holds because `state=="not_home"` requires at least one tracker to have reported not_home — so a source-signal DID exist, we just didn't decompose it.

**Outer wrappers override classifier result** on:
- `_ps_state == "home"` → force ACTIVE-home, whitelist `tracking_reason` to case-(b) family. **Case-(b) never-collapses-to-LOST pin enforced.**
- `_ps_state in {"unknown","unavailable","","none"}` → force S5 LOST + no_signal + 0.0 conf, **DO NOT set `_person_was_away`.**
- else → force ACTIVE-away; substitute `away_wifi_only` if classifier said `no_signal`.

The outer wrappers are the last line of defense — the classifier's fallback + wrappers together cannot produce a "no location signal → away vote" outcome. Verified by mutation A-D1.

---

## Room-tier invariant (D1 §4.7.1) — no room-level location < 0.3 conf

Enumerated the cells that produce a room-name location (as opposed to `home`/`away`/`unknown`). Only Row 1 (Bermuda-authoritative BLE-visible) and the STALE-decay branch produce room names:

- **Row 1 (`:511-525`):** confidence from `_calculate_confidence(person_name, bermuda_area, resolved_room)`. Pre-existing helper; not modified by this cycle. Historical range 0.3-1.0 per D1 audit. ✓
- **STALE-decay (`:601`):** `confidence = max(0.1, old * 0.5)`. **Room location preserved with confidence floor 0.1.** This is `bermuda_decay` method — a room-tier location can carry confidence < 0.3. Not new to this cycle (pre-existing v3.2.8.1 decay logic). Whether the ≥0.3 room-tier invariant applies to STALE-overlay stamps is a plan/AUDIT interpretation question; the D1 §4.7.1 language reads as "cells yielding room-level location," which STALE does. **Not introduced by this cycle** — flagged for framing-B/C to weigh in. Not a blocker for A.

Test `test_matrix_room_locations_clear_room_occupancy_threshold` covers the classifier surface (which does not emit room names at all — only home/away/unknown). Coverage of STALE-decay's confidence floor vs. `get_room_occupants` 0.3 threshold is a pre-existing gap, not caused by PATH-ALPHA.

---

## Gap A (D8) — face_recognized_count threading

Verified end-to-end thread:

1. **Source:** `camera_census.py` maintains a face-only identity set gated by `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS=1800s` (`const.py:2702`). Tracker-not_home cross-check documented as fail-OPEN upper bound (30-min ceiling).
2. **Payload:** `presence.py:1358` initializes `self._face_recognized_count`; `:5788` passes as kwarg to `infer()`.
3. **Consumption:** `presence.py:1094` — path α gate `all_tracked_persons_away and unidentified_count == 0 and face_recognized_count == 0`.
4. **Path β asymmetry:** Path β at `:1168` gates on `census_count == 0` (not face_recognized_count). Since `census_count = max(camera_total, |face_ids ∪ ble_ids|)`, the forgotten-phone scenario keeps census>=1 via stale BLE and path β is blocked. **Asymmetry is intentional and safe** — census_count == 0 is strictly stronger than face_recognized_count == 0 for the forgotten-phone false-positive.

**Stale-face bound:** window 1800s at const.py, plus a fail-OPEN tracker cross-check. A face sighting cannot block the veto indefinitely — after 30 min it decays out. ✓

---

## Liveness-gated BLE axis — accused-witness discipline

`_ble_fleet_live` (`:244-272`) checks any tracked person's `last_bermuda_update` within `BLE_FLEET_LIVENESS_WINDOW_S`. Returns False if no person has a recent update. **Fails OPEN on empty `self.data` (boot) or exception.**

- **Runtime steady-state:** Correctly degrades BLE=silent → indeterminate when the fleet has no recent updates. Drill A-D3 confirmed the gate is load-bearing.
- **Boot edge:** On the very first coordinator tick, `self.data` is empty; `_ble_fleet_live` returns True. If a person's HA state is "not_home" AND their trackers all report MISSING (unusual), classifier could stamp `away_ble_silent_only` with 0.82 confidence when in fact the fleet is not proven live. **Net vote is still AWAY** (the outer wrapper's `_ps_state == "not_home"` branch coerces to ACTIVE-away regardless), so **I-α is NOT violated** — but the reason attribution is optimistic during boot. See M1 below.

For BLE-only Ziri: HA state has no non-BLE tracker → cannot become "not_home" → outer wrapper coerces to `no_signal`. Ziri is protected by the wrapper independently of `_ble_fleet_live`'s fail-OPEN. ✓

---

## Per-tick dynamic inventory

`_read_source_inventory` (`:186-242`) is called on every `_async_update_data` tick at three sites (`:509`, `:657`, `:736`). No caching (module- or instance-level) of who-has-which-tracker. `test_source_inventory_read_per_tick_not_cached` covers.

Verified no `@cache`/`@lru_cache`/`_source_cache` in `person_coordinator.py`. ✓

---

## Findings

### M1 (MEDIUM, audit fidelity) — `_ble_fleet_live` fails OPEN on empty `self.data`

**File:** `custom_components/universal_room_automation/person_coordinator.py:255-261`

```python
try:
    data = self.data or {}
except Exception:
    return True
if not data:
    return True
```

**Concern:** On the very first coordinator tick — before any person has had a `last_bermuda_update` recorded — the liveness gate reports "fleet live" and admits row-14 BLE=silent evidence. The plan text ("BLE=silent genuinely requires provable scanner liveness; a dead scanner fleet must yield indeterminate → no away vote") is stricter than the implementation on this edge.

**Impact:** I-α NOT violated (verified — Ziri is protected by the wrapper's HA-state coercion; a non-BLE person with HA `state=="not_home"` votes AWAY through the wrapper regardless of which reason was stamped). What CAN happen is a mis-attributed `tracking_reason=away_ble_silent_only` conf 0.82 (rather than `away_wifi_only` conf 0.90) for a fraction of the first boot minute. Downstream analytics that key on `tracking_reason` (D3 rider) may see spurious BLE-only-away attribution during boot.

**Recommendation (non-blocking):** Change the empty-data fast-path to `return False` (fleet-not-yet-proven-live) OR gate on an explicit "any Bermuda area sensor has ever been in a resolved state" flag. Do NOT ship-block on this — the wrapper coercion neutralizes the vote-shape risk, and boot-transient mis-attribution is instrumented via the D6 `tracker_trust_excluded` writer.

### L1 (LOW) — Dead vocabulary value `anomalous_wifi_gone_local_home`

**File:** `custom_components/universal_room_automation/const.py:208`

The vocabulary includes `anomalous_wifi_gone_local_home` (plan Row 5 variant) but the classifier never emits it. Row 5 (G=home, W=not_home, B=visible@home_room) is intercepted upstream by the Bermuda-authoritative branch (`:506-525`) which stamps `tracking_reason="bermuda"`. The row-4 GPS-home-WiFi-not_home branch (`:315-319`) unconditionally stamps `anomalous_gps_stale_local_gone` regardless of BLE.

**Recommendation:** Either remove from vocabulary OR add a branch in the classifier for the (rare) case where row-4 tuple is entered with independent evidence that BLE has already placed the person at home. Not a bug — vocab-with-dead-value is warning-safe. Keep as-is if intentional forward-compatibility.

### L2 (LOW, plan/build divergence) — D2b scope narrower than plan header wording

Plan §Scope A reads: "D2b — presence.py path-β wholesale delete: unchanged." The D2b commit (`9f3529e76`) explicitly narrows to "retire relaxed predicate + LOST-admission list" while keeping the path-β branch shape (`:1103-1208`) sharing path-α's denominator. Commit body justifies: "matrix classifier (D2a) already stamps case-(a) confidently-away trackers as ACTIVE so the relaxed OR-clause was behavior-equivalent."

Verified behaviorally equivalent: `all_trusted_or_lost_away_persons_away = all_tracked_persons_away` (`:5796`); `lost_away_persons_present` defaults False; the OR-clause `or not lost_away_persons_present` (`:1175`) always satisfies. Kill-switch coercion `all_tracked_persons_away = False` (`:5768`) coerces both denominators via the single rebinding.

**Recommendation:** Update the plan text at rev-3.5.2 to match actual D2b scope (predicate + LOST-admission list only, not the wholesale branch). Non-blocking; behavior is correct.

### L3 (LOW, cosmetic) — Asymmetric ble_location guard in D9 sensor

**File:** `custom_components/universal_room_automation/binary_sensor.py:1747` vs `:1827`

`is_on` uses `ble_location not in ("home",)`; `extra_state_attributes` uses `ble_location not in ("home","unknown","away")`. Both fail-OPEN correctly (`is_on` early-returns at `:1733` for unknown/away, so the guard set difference has no live behavioral divergence).

**Recommendation:** Align to the tighter attribute-side set for readability. Non-blocking.

---

## Summary table

| Severity | Count | Description |
|---|---|---|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 1 | M1 (`_ble_fleet_live` boot fail-OPEN) |
| LOW | 3 | L1 (dead vocab value), L2 (plan/build scope divergence), L3 (cosmetic asymmetric guard) |

## Bug-class map

| Finding | Bug class |
|---|---|
| M1 | #23 observation-mode/boot-transient gating (fail-open on empty state) |
| L1 | Vocabulary drift / unreachable value |
| L2 | Plan/build divergence (scope wording) |
| L3 | Micro-inconsistency between decision-site and diagnostic-surface guards |

## Ship rationale

Load-bearing invariant I-α (the entire cycle's raison d'être) is preserved across every reachable path I enumerated and every mutation I drilled. Case-(b) never-collapses-to-LOST is enforced structurally by both the classifier's precedence and the outer wrappers' `_ps_state=="home"` coercion. Row 14's confidence knob is below the path-α 0.9 threshold so BLE-only Ziri cannot solo-flip the house. Vocabulary gate is present. Dynamic per-tick source inventory is verified.

M1 is a boot-window audit-fidelity concern that does not violate I-α; the wrapper coercion neutralizes any vote-shape risk. Recommend fix-in-place in a follow-up cycle; not a ship blocker.

**Verdict: SHIP.**
