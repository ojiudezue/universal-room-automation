# Code Review B — GUEST-CENSUS (branch `feature/guest-census`) — REVISED

**Range reviewed:** `develop...feature/guest-census` (merge-base `3b373d3db`, tip `c7c308a53`).
Five commits: **D1** (`eae92423c` PRE-BLE-cancel clamp + G2 diagnostics), **D2** (`7f7c15d20`), **D3** (`36d92bc6e`), **D2b** (`44ccfabc6`), test collateral (`c7c308a53`).
**Framing:** consumer ripple of the count change, lifecycle, restart resilience, D3 registry-lookup live verification, mutation drills D3-M1/D3-M2.

## Correction — my initial revision was wrong about scope (B-INFO-1 retracted)

**First-pass error.** I ran `git log eae92423c..c7c308a53` and saw only four commits. `eae42..c7c30` is a two-dot range with `eae42` as the EXCLUSIVE lower bound, so the D1 commit itself (`eae92423c`) was silently dropped from the diff. I then concluded `camera_census.py` and `sensor.py` were untouched. That is false. The real merge base is `3b373d3db`; the correct log includes D1 as its first commit.

**Root cause of the mistake:** I trusted the orchestrator brief's "commits eae42..c7c308a53" as a diff range without cross-checking that `eae42` was the merge base or an ancestor. It was neither — it was the first commit of the branch. `git merge-base develop feature/guest-census` returns `3b373d3db`; `git log 3b373db..c7c308a53` returns five commits. The right diff for a branch review is either `develop...feature/guest-census` (three-dot) or `merge-base..tip`, never the tip of some earlier commit as `A..B`.

**Impact of the mistake:** my first-pass ripple analysis was vacuous — I claimed the payload was byte-identical because D1 was absent. In fact D1 IS present and the payload's `total_persons` and `unidentified_count` values DO change live tonight (per plan's re-derivation: identified=4, held=6 → additive 10, ceiling 6 (pre_cancel), clamped total 6, clamped unidentified 2). Everything downstream that keys on those numbers needs a real assessment.

The findings below preserve what was independent of that error (RAM-only guest_room_state answer, D3 live-registry verification, D3-M1 / D3-M2 drill records) and replace the rest.

---

## Verdict — **SHIP-WITH-1-MEDIUM**

D1 + D2 + D2b + D3 are behaviorally sound. No CRITICAL / HIGH findings. One MEDIUM (B-MEDIUM-1: restart re-arm latency amplified by D2 for genuine mid-visit guests — plain answer below with minimal fix). D2b is a strict-improvement guard against terminal-GUEST latching under D1's expected residual (unid=2). D3 verified against the live entity registry — it does fix the Upstairs Guestroom subscription gap. Mutation drills D3-M1 and D3-M2 both anchor to specific named tests.

---

## Directed answer — is RAM-only `_guest_room_state` a NEW regression?

**Mixed. The RAM-only lifetime is pre-existing. The user-visible latency it produces IS newly amplified by D2, from ~5 min to 30 min, for the specific case of a genuine in-progress guest visit interrupted by an HA restart. Under the operator's "no debt" rule for this cycle, this qualifies as a NEW regression worth calling out.**

Evidence:
- `PresenceCoordinator._guest_room_state` initialised empty in `__init__` at `presence.py:1628`; cleared+repopulated at each `_discover_guest_rooms()` call (`:4706` + `:4743`); never persisted / restored.
- Pre-cycle: after a restart mid-visit, Path A (`_guest_gate_armed` driven by `unidentified_count`) could re-arm GUEST in ~5 min via the `guest_mode_persistence_seconds` (300 s default) window. Path B's `first_seen=None` needed 30 min to re-arm.
- Post-D2: Path A no longer arms GUEST at all in the home-like branch (`presence.py:5426`). Only Path B, whose `first_seen` is reset on setup, so the effective re-arm is 30 min from scratch.
- Net: restart cost 5 min → 30 min for the ongoing-visit case.

The plan's M1 trade-list (§D2) explicitly accepts "guests present under 30 min no longer trigger GUEST" (new arrivals), but does NOT enumerate the restart-mid-visit case. Under "no debt" it belongs on the list.

**Minimal fix (~10-25 LoC):** in `_discover_guest_rooms`, after resolving `occupancy_entity_id` and initialising `self._guest_room_state[room_name]`, peek the current occupancy state and seed `first_seen` when currently `on`:

```python
occ_state = self.hass.states.get(occupancy_entity_id)
if occ_state is not None and occ_state.state == "on":
    # Boot-seed: preserve the pre-restart arming clock. Identity is
    # re-checked on the next real occupancy event (Transition 2 in
    # _handle_guest_room_occupancy_change resets first_seen to None
    # if a resident is detected there).
    self._guest_room_state[room_name]["first_seen"] = occ_state.last_changed
```

If "identity-aware boot seed" is preferred (avoids false-positive first_seen on a resident-occupied room until the next state-change), extract the known-occupant identity check into a helper and call it from both `_handle_guest_room_occupancy_change` and this seed site. Adds ~15 LoC.

Recorded as **B-MEDIUM-1** below.

---

## Consumer ripple — real, with D1 in the branch

The live tonight change per the plan re-derivation: `total_persons` drops 10 → 6, `identified_count` unchanged at 4, `unidentified_count` drops 6 → 2. `confidence` (string "low"/"medium"/"high"/"none") is UNCHANGED — D1 does not touch the raw_result confidence which is derived from source agreement, not the count (`camera_census.py:3187` `confidence=raw_result.confidence`).

### Threshold surface enumeration

All grep-hits on `total_persons`, `unidentified_count`, `identified_count`, `census_count`, `census_confidence` were traced. Only the threshold-crossing consumers matter for behavior change.

| Site | file:line | Threshold read | Live pre → post | Crossed? | Behavior change |
|---|---|---|---|---|---|
| Nobody-home → AWAY | `presence.py:1059-1063` (via `_census_count == 0`) | `== 0` | 10→6 | No | None |
| Path α away-veto | `presence.py:1091-1101` | `unidentified_count == 0` AND `face_recognized_count == 0` AND `all_tracked_persons_away` | unid 6→2 | No | None — gated by `all_tracked_persons_away`, which is false when identified≥1 |
| Path β immediate-engage | `presence.py:1168-1179` | `unidentified_count == 0 AND census_count == 0 AND all_trusted_or_lost_away` | 6→2 / 10→6 | No | None — same all-away gate |
| GUEST exit (D2b) | `presence.py:1249` | `not guest_gate_armed` — `unidentified_count == 0` conjunct **REMOVED** by D2b | n/a | n/a | GUEST now exits when Path B clears even if D1 residual keeps unid > 0. Strict improvement. |
| GUEST entry (D2) | `presence.py:5411-5426` | `guest_armed = guest_room_gate_armed` — Path A predicate **removed** | n/a | n/a | Only Path B arms GUEST |
| Path A `_guest_gate_armed` guard 1 | `presence.py:4914` | `unidentified_count > 0` | 6→2 | No | Same — Path A still armed on unid=2. Under D2 it is diagnostic-only. |
| Path A guard 2 (confidence) | `presence.py:4923` | `census_confidence >= high` | unchanged | No | None — confidence STRING unaffected by D1 |
| Sustained external empty | `presence.py:5730-5734` | `_unidentified_count == 0 AND _census_count == 0 AND _indoor_clear_debounced` | 6→2 / 10→6 | No | None — both gated by == 0 |
| has_people implicit | infer path | `census_count > 0` | 10→6 | No | None |
| Wake backstop | `presence.py:5946` | `_unidentified_count == 0` context | 6→2 | No | None |
| Veto oracle H1 | `presence.py:1877-1897` | both zero | 6→2 / 10→6 | No | None |
| Boot settle | `presence.py:5080-5093` | count of ready inputs (not persons) | n/a | No | None |
| Boot seeding | `presence.py:2641` | seeds `_census_count = total_persons` | 10→6 on next boot | n/a | Cold-boot seed now 6 not 10; downstream reads immediately (no threshold on the seed itself). |
| Security lockdown | `security.py:774-775, 969-1010` | reads `intent.source == "census_update"`, not the value | n/a | No | None — lockdown fires on every census tick regardless of value |
| Phone-left-behind suppression | `binary_sensor.py:1772` | `house.total_persons > 0` | 10→6 | No | None (both > 0) |
| Phone-left-behind attrs | `binary_sensor.py:1815` | numeric copy | 10→6 | No | Display only |
| UnexpectedPerson sensor | `binary_sensor.py:1549, 1573` | `total_persons` display + name diff | 10→6 | No | Display; may show fewer "unexpected" entries — desired |
| CensusMismatch tripwire | `binary_sensor.py:1610-1660` | numeric comparison to per-zone rollup | recalibrates | n/a | Mismatch value shifts; no on/off flip induced by D1 alone unless configured mismatch band is tight (grep found no static threshold — the band is derivational). |
| ZoneGuestCountSensor | `aggregation.py:5983-6001` | `max(0, camera_total - ble_total)` per zone | 6→2 (house) | n/a | Display sensor; dashboards see lower "zone guest count". Removes the phantom-guest number. Desired. |
| DB writer: `census_house_daily` / row insert | `database.py:3593-3634` | writes `unidentified_count`, `total_persons`, `identified_count`, `confidence` | 10→6 & 6→2 | No | Row content changes; column set unchanged; historical analytics will see a step-change post-deploy. Not a schema change, no migration. |
| Persons-in-house sensor + attrs | `sensor.py:3473-3529, 3612` | numeric + new G2 attrs (see next) | 10→6 & 6→2 | No | Value drops; new attrs appear (below) |
| Persons-on-property sensor | `sensor.py:3660-3681` | `unidentified_total = house.unid + exterior.unid` | interior 6→2 | No | Value drops |
| Zone-level `total_persons` attr | `sensor.py:3110` | `len(persons_in_zone)` — INDEPENDENT of house count | unchanged | No | Local computation; not affected |

### `unidentified_count == 0` — the only reachable threshold cross

D1 clamps `unidentified = max(0, clamped_total - identified_count)`. When `identified >= camera_total_pre_cancel`, ceiling = identified, clamped_total = identified, and `unidentified` collapses to 0 regardless of `held_unidentified`. Pre-D1 the same input could keep unidentified > 0 due to hold/decay.

Reachable consumers of `unid == 0`:
- **Path α / Path β AWAY vetoes** at `:1091-1101` / `:1168-1179`. Additionally gated by `all_tracked_persons_away` / `all_trusted_or_lost_away`. When identified ≥ 1 and all trusted are marked away, that's a legitimate identified-ghost situation — pre-D1 the held phantom kept the veto blocked; post-D1 the veto could fire. But if `identified_count ≥ 1` from the enhanced census, someone is asserting camera-recognised presence, and `all_tracked_persons_away` cannot be true for that identified person. So the cross is not reachable in practice.
- **`_guest_gate_armed` guard 1** at `:4914`. Pre-D1 an all-residents-home + decayed phantom could keep unid > 0 and hold Path A armed. Post-D1 unid = 0 disarms Path A. **Consequence: fewer spurious Path A firings — DESIRED, and moot under D2 (Path A no longer arms GUEST).**

**Net: no adverse threshold-cross behavior induced by D1.** The one cross that fires (Path A disarming) is a desirable side-effect of the clamp.

### `_d5_guest_confidence` — new value 0.95

The confidence bump 0.9 → 0.95 for room+census corroboration (`presence.py:5448`) flows to `_inference_engine._confidence` at `:5981` when transitioning to GUEST. Grep of `custom_components/` for `confidence >= 0.9`, `> 0.9`, `>= 0.95`, `> 0.95`, `_confidence >= 0.9`, `_confidence > 0.9`: **zero threshold consumers.** No downstream keys on the 0.9 vs 0.95 discriminator.

### G2 diagnostics — new attribute surface

`sensor.universal_room_automation_persons_in_house` (`sensor.py:3508-3540`) gains four new attributes, always published:
- `area_raw_max_pre_cancel` (dict[str, int])
- `ble_by_area` (dict[str, int])
- `ble_cancel_enabled` (bool)
- `camera_total_pre_cancel` (int)

Also **changed**: `area_contributions` sources from `_last_enhanced_area_contributions` when `enhanced_census=True`, else falls through to the raw producer's `_last_area_contributions` (unchanged pre-cycle behavior for the disabled-enhanced path).

Consumer surface for these attrs (grep across `custom_components/`, `docs/dashboard-prototypes/`, `docs/planning/`): the attribute names are new; no existing HA/URA consumer reads them. Dashboards that already surface `area_contributions` will now see the enhanced-path dedup dict (was `{}` empty in the plan's Before-picture) — an improvement in observability, not a schema break. Recorder will start persisting the new attribute names automatically (standard HA attr recording), consuming small extra rows in `states_meta` / `state_attributes` — trivial.

RestoreEntity: `URAPersonsInHouseSensor` is a standard `SensorEntity`. Attributes are not restored, they are recomputed on next tick. No boot-poison hazard.

### Cross-coordinator ripple — real check against the full diff

- **PresenceCoordinator ↔ census fan-out**: no signal/payload key changes. Every subscriber gets the same `SIGNAL_CENSUS_UPDATED` with the same keys; only the values differ.
- **HVAC (`hvac.py`, `hvac_coordinator.py`, etc.)**: no grep hits on `total_persons`, `unidentified_count`, `identified_count`, `census_confidence`. Not a consumer.
- **Security / lockdown (`security.py:774-775, 969-1010`)**: keys on `intent.source == "census_update"`, not the value. Unaffected.
- **Anomaly / NM**: no direct consumption of census counts as a threshold. Anomaly on `unexpected_person` / `census_mismatch` binary sensors is state-flip-driven, and the flips remain plausible (the flip direction after D1 is fewer FPs, not new FPs).
- **DB write path**: writes clamped values into existing columns; no schema change, no new writes/tick. Row rate unchanged.
- **Optimization coordinator / EC / battery / arbitrage**: no consumers.

Conclusion: **no cross-coordinator ripple** in the correctness sense. The change is contained within PresenceCoordinator's own inference + the census sensor's attribute surface + row values written to `census_house_daily`.

### Payload-shape audit

D1 changes VALUES of existing `CensusZoneResult` fields (`total_persons`, `unidentified_count`). No new keys, no removed keys. Field types unchanged (`int`). No new SIGNAL_* introduced. Payload shape is byte-key-identical.

---

## Findings

### B-INFO-1 — RETRACTED (my first-pass diff error)

See "Correction" section above. D1 IS in the branch; the ripple is real; I corrected the diff basis to `develop...feature/guest-census` (merge-base `3b373d3db`).

### B-MEDIUM-1 — `_guest_room_state.first_seen` unseeded on boot; D2 amplifies restart re-arm 5→30 min for genuine in-progress guests

**Files:** `custom_components/universal_room_automation/domain_coordinators/presence.py`, `_discover_guest_rooms` (`:4682-4762`).
**Mechanism + minimal fix:** see Directed answer above.
**Class:** Restart Resilience / RestoreEntity-adjacent (RAM-only state loss). Under the operator's cycle-scope "no debt" rule this should be fixed in-cycle.

### B-LOW-1 — Plan M1 trade-list omits restart-mid-visit case

**File:** `docs/planning/PLANNING_guest_census_correctness.md` §D2 M1 (lines 373-411). Add a bullet for the restart-mid-visit re-arm latency; either declare it accepted or land B-MEDIUM-1's fix.

### B-LOW-2 — Dead-branch comment at `presence.py:5453`

`_d5_guest_confidence = 0.8  # unreachable under D2; shape-preserved`. Consider `assert False, "unreachable under D2"` as a canary if a future edit resurrects the branch. Cosmetic.

### B-LOW-3 — Analytics discontinuity in `census_house_daily`

D1 changes column values written to `census_house_daily` (`database.py:3593-3634`) starting at deploy time. Any dashboard/analytics that draws a trailing curve of `total_persons` / `unidentified_count` will show a step-change from ~10 → ~6 at deploy. Not a defect — desired — but the README's post-deploy validation table should call it out so nobody re-diagnoses it as a data outage.

### B-INFO-2 — CensusMismatch band

`binary_sensor.py:1610-1660` (CensusMismatch) compares house `total_persons` to a per-zone rollup. D1 clamps the house total but the per-zone rollup path (via `aggregation.py:5281 total_persons = len(persons_in_zone)`) is independent of D1. Mismatch magnitudes shift post-deploy. If a tripwire threshold on the mismatch value is later configured (not seen today), that would be a new consumer to check — currently derivational, not a fixed cutoff.

---

## D3 live registry verification (unchanged from first pass)

Verified via `ha_get_entity` on `binary_sensor.upstairs_guest_bedroom_occupied`:
- `config_entry_id = "01KCYSBVA2RMB5C3F1Z90F9X72"`
- `unique_id = "01KCYSBVA2RMB5C3F1Z90F9X72_occupied"`
- `platform = "universal_room_automation"` (= `DOMAIN`)

D3's `ent_reg.async_get_entity_id("binary_sensor", DOMAIN, f"{entry_id}_occupied")` returns `binary_sensor.upstairs_guest_bedroom_occupied`. Pre-cycle slug-string `binary_sensor.upstairs_guestroom_occupied` does not exist in the registry. **D3 genuinely fixes the Upstairs Guestroom subscription.**

Sibling: `binary_sensor.guest_bedroom_1_occupied` (config_entry `01KE2CP30H1251F10K5R1YJRCC`) also resolves cleanly.

---

## Mutation drills D3-M1 and D3-M2 (unchanged from first pass)

Performed in isolated worktree `.claude/worktrees/review-B-guest-census-drill` (detached at `c7c308a53`, `PYTHONDONTWRITEBYTECODE=1`, cache cleared, restored + worktree removed after).

- Baseline: `test_discover_uses_registry_lookup` PASS, `test_unresolvable_room_warns` PASS.
- **D3-M1** (restore slug-string, remove registry lookup + WARNING at `presence.py:4728-4739`): `test_discover_uses_registry_lookup` FAILED at `assert 'async_get_entity_id' in body`. Anchor confirmed.
- **D3-M2** (WARNING is deleted as part of the same M1 patch, since removing the entire block eliminates both surfaces): `test_unresolvable_room_warns` FAILED at `assert '_LOGGER.warning' in body`. Anchor confirmed — the WARNING-log grep is uniquely load-bearing on this test.
- Restore via `git restore`; re-run: 2 passed. Worktree removed with `git worktree remove --force`.

Both drills are properly anchored to specific named tests. Test authority under Review C's framing is intact for D3.

---

## D2b behavior tests (also re-verified)

- `test_d2b_guest_exits_when_room_clears_even_if_unidentified_stuck`: PASS. Verifies D2b unlocks the terminal-GUEST latch that D1's expected residual (unid=2) would otherwise induce.
- `test_d2b_real_guest_holds_when_room_still_occupied`: PASS.
- `test_d2b_guest_non_terminal_from_room_clear`: PASS.
- Source-shape guard `test_d2b_exit_predicate_source_shape`: PASS; would trip on silent revert of the conjunct.

D2b + D1 together: D1 leaves unid > 0 pinned at the expected +1-2 residual (broken defenses); D2b drops the `unidentified_count == 0` conjunct so GUEST can still exit on room-clear. This pairing is correct and load-bearing — without D2b, D1 alone would produce a permanently-latched GUEST any night the residual persists.

---

## Summary statistics

| Severity | Count | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 0 | — | — |
| HIGH | 0 | — | — |
| MEDIUM | 1 (B-MEDIUM-1) | 0 | recommended to fix in-cycle per operator "no debt" |
| LOW | 3 (B-LOW-1 doc, B-LOW-2 comment, B-LOW-3 analytics readme note) | 0 | acceptable |
| INFO | 1 (B-INFO-2 mismatch band future risk) | n/a | monitor |

Bug-class frequency:
- Restart Resilience / RAM-only state persistence: 1 (B-MEDIUM-1)
- Doc gap: 1
- Analytics-continuity note: 1
- Cosmetic: 1

**Process observation to record for future reviewers:** the initial-pass diff error came from trusting a brief-supplied "commits X..Y" range as a diff base. For a branch review the canonical bases are `git merge-base <target> <branch>` or the three-dot `<target>...<branch>` — never the tip of an inclusive endpoint dropped into `A..B`. Verify with `git log <base>..<branch> --oneline | wc -l` against the branch's expected commit count before proceeding.

---

## Ship guidance for orchestrator

1. D1 + D2b + D3 are correct and mutation-anchored. Payload shape byte-identical; values shift as expected (tonight: `persons_in_house` 10 → 6). Recommend ship.
2. **B-MEDIUM-1** — land the boot-seed fix in-cycle to keep "no debt" honest, or explicitly accept the 5→30-min restart re-arm latency on the record.
3. **B-LOW-3** — README's Live Validation section should mention the expected step-change in `census_house_daily` at deploy time so it isn't mis-diagnosed later.
4. Fold B-LOW-1 update into the plan M1 list.
