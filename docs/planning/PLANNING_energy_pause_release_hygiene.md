# PLANNING — Energy Pause-Release Hygiene Cycle

**Filed:** 2026-07-13
**Author:** ura-planner
**Target branch:** `develop` (feature branch: `feature/energy-pause-release-hygiene`)
**Tier:** **Tier 2-DB** (3 framing-disjoint reviews) — operator-elevated per CLAUDE.md standing policy (regression-prone, trust-hierarchy ripple across energy_battery ↔ energy ↔ energy_pool).
**Skills loaded:** `ura-energy-invariants-campaign`, `ura-energy-strategy-reference`.
**Sequencing (MANDATORY):** This cycle builds AFTER the concurrent **write-verification** cycle merges to `develop`. Same files (`energy.py`, `energy_battery.py`, `energy_pool.py`). Do NOT branch from current tip until write-verification is in `develop`; builder MUST rebase and **re-run every grep in the Institutional-Context-Verified section at build-time** — line anchors below are 2026-07-13 snapshots and WILL drift. The concurrent HVAC/config-flow and presence cycles do not touch these files; no direct conflict expected but merge order matters for the shared write-queue.

---

## Executive-summary hook

Three related defects in the EV/plug pause-owner machinery:
- **D1 (D-HIGH-3, "do #5"):** three pause sets have their release paths *conditionally compiled* behind the feature toggle that installed them, and DB restore blindly re-adds membership. Flipping a toggle OFF while a pause is active permanently orphans the device across cycles and restarts.
- **D2 (E-MED-1, "do #6a"):** the multi-EVSE battery-hold overlay mutates the emit dict AFTER `determine_mode`, so its elevated reserve never lands in `_last_reserve_level`. `current_park_floor()` under-reports, and `compose_release_floor` cedes early — a second EVSE can't release during the hold.
- **D3 ("do #6b"):** `energy.py` is unimportable from the test suite due to a missing `homeassistant.helpers.dispatcher` stub. Add the stub + author the direct call-site mutation-anchor tests the v5.15.0 cycle could not (Review C was forced to use a compensating helper-extraction construction).

---

## Institutional context verified (2026-07-13)

**Re-verify at build-time.** The write-verification cycle currently in flight touches all three files. Every anchor below is a 2026-07-13 snapshot; re-grep BEFORE editing. Any drift > ±10 lines requires re-planning that deliverable.

### Greps run

```bash
grep -n "_paused_by_us\|_paused_by_grid_cap\|_paused_by_fill_priority" \
  custom_components/universal_room_automation/domain_coordinators/energy_pool.py \
  custom_components/universal_room_automation/domain_coordinators/energy.py

grep -n "_ev_tou_enabled\|_excess_solar_enabled\|_grid_import_cap_enabled" \
  custom_components/universal_room_automation/domain_coordinators/energy.py

grep -n "_apply_evse_battery_hold\|_last_reserve_level\|current_park_floor\|compose_release_floor" \
  custom_components/universal_room_automation/domain_coordinators/energy_battery.py \
  custom_components/universal_room_automation/domain_coordinators/energy.py

grep -rn "async_dispatcher_connect" quality/ | head
```

### D1 anchors — toggle-pinned release paths

| Owner set | Toggle attr | Toggle-gated release path (current) | Restore site |
|---|---|---|---|
| `_paused_by_us` (TOU) | `self._ev_tou_enabled` (`energy.py:281,5428`) | EVSE release inside off_peak branch gated `if self._ev_tou_enabled:` — **energy.py:2943** (verify range ~2943-2960; operator memo cited ~3327/2944 pre-write-verify — re-anchor) | `_paused_by_us` DB re-add `energy.py:1127`; ≤10h staleness restore path `energy.py:1096-1327` (re-add unconditional) |
| `_paused_by_fill_priority` | `self._excess_solar_enabled` (`energy.py:264`) | Release only inside `if self._excess_solar_enabled:` — **energy.py:2888** (EVSE) and **energy.py:2974** (plug mirror). Discards live in `energy_pool.py:1246,1279,1338,1360,2165,2192,2229,2248` but the *scheduling* to enter that path is gated. | Restore `energy.py:1168` (unconditional re-add) |
| `_paused_by_grid_cap` | `self._grid_import_cap_enabled` (`energy.py:275`) | Release only inside `if self._grid_import_cap_enabled:` — **energy.py:2818**. `energy_pool.py:840-871` discards live in EVSE tick but only if outer gate lets tick run for the grid-cap arm. | Restore `energy.py:1146` (unconditional re-add) |

Cross-owner deferral: `energy_pool.py:558-570` — ensure-on defers if any other owner set contains the device (verified). Drain release similarly defers (`energy_pool.py:751-757`, `:1332-1338`).

### D2 anchors — EVSE-battery-hold ledger gap

- Overlay helper: `_apply_evse_battery_hold` — `energy.py:2614` (mutates decision dict).
- Applied at: `energy.py:2737` and `energy.py:3143` (both AFTER `determine_mode` returns).
- Comment at `energy_battery.py:2990` explicitly notes this happens after: *"NOTE: _apply_evse_battery_hold (energy.py:2453) runs AFTER this"* — that stale line ref (2453) confirms drift; builder must re-verify at build.
- `_last_reserve_level` stamped only inside `_result`: `energy_battery.py:3345` (`self._last_reserve_level = int(max(0, min(100, reserve_level)))`). Because overlay runs *after* `_result`, its elevated reserve never lands here.
- `current_park_floor()` reads `_last_reserve_level` at `energy_battery.py:760-761`; returns None otherwise.
- `compose_release_floor(battery, tou_period)` at `energy_battery.py:146-190` — the single-source composition; consumes `battery.current_park_floor()` at `:173`.
- Invariant INV-EV-DEADBAND (v5.15.0) and off_peak gating (commit `853827b0`) — MUST remain intact.

### D3 anchors — test harness

- energy.py imports `async_dispatcher_connect` (v5.12.0 substrate resubscribe). Quality suite lacks the stub.
- v5.15.0 Review C compensating construction: helper extracted so that tests can exercise composition without importing energy.py. This cycle removes that compromise.
- Existing scaffolding: `quality/` (per CLAUDE.md `PYTHONPATH=quality python3 -m pytest quality/tests/ -v`). Locate the HA stubs directory used by existing energy_battery tests and add the missing dispatcher siblings (`async_dispatcher_connect`, `async_dispatcher_send`, `dispatcher_connect`, `dispatcher_send` as needed).

### Prior planning docs consulted
- `docs/planning/PLANNING_arbitrage_wait_inclement_floor.md` — reserve-floor plumbing precedent.
- `docs/planning/PLANNING_arbitrage_solar_attainability_ladder.md` — attain-adjacent for D2 impact assessment.
- v5.15.0 write-verify plan (in-flight; re-read after merge) — precedent for the extracted-helper pattern this cycle backfills.

### Memory bodies pulled
- `project_load_shedding_audit_backlog` — Bug Class #46 owner-set collision history (pause-set discipline lineage).
- `project_ev_offpeak_cycle_pickup` — v4.7.28 ensure-on semantics.
- `project_v5_5_0_inclement_weather_shipped` — hold-depth surface D2 must respect.

### Design docs read
- `docs/Coordinator/ENERGY_COORDINATOR_DESIGN_v2.3.md` — release-floor composition contract.

### Code locations surveyed end-to-end
- `energy_pool.py` L163-870 (EVSE controller) and L1780-2400 (smart-plug mirror).
- `energy.py` L2600-3200 (decision + overlay + toggle branches), L1080-1330 (restore path), L5400-5700 (toggle setters + fill-priority edge detect).
- `energy_battery.py` L146-190 (`compose_release_floor`), L740-780 (`current_park_floor`), L2985-3020 and L3330-3360 (`_result`).

**NEW vs REUSED classifications:** Every code change proposed below is REUSED — no new CONF_*, no new sensor, no new switch, no new signal, no new set. Only behavior changes on existing owner sets, existing overlay function, existing composition helper. D3 adds test infra only.

---

## Operator standing directives

- **Units-and-signs vigilance.** Any threshold, floor, or SOC arithmetic touched or introduced by this cycle must state its unit (% SOC / W / kW / minutes) inline in code AND in this doc, and its sign convention (floor = minimum, ceiling = maximum, positive = import). See D2 §Units block.
- **Deploy from `develop`, not the feature branch.** Standing rule after 2026-07-05 codeless-release incident.
- **No emojis in code or docs.** Per project convention.

---

## Falsifiable invariants (Phase 0)

| ID | Falsifiable invariant | Falsified by |
|---|---|---|
| INV-D1-RELEASE | For every pause-owner set `S` gated by feature toggle `T`, when `T` transitions from ON → OFF, no device remains in `S` for more than one full decision cycle (≤ 6 min = one 5-min tick + slack). | Any legal-config repro where operator flips `T` off with a pause active and the device remains paused > 6 min or across a restart. |
| INV-D1-RESTORE | The ≤10h staleness restore in `energy.py:1096-1327` MUST NOT re-add a device to `S` when `T` is currently OFF. | A restart with `T=OFF` + persisted `S` non-empty producing a non-empty in-memory `S`. |
| INV-D1-TOGGLE-CYCLE | A toggle transition OFF → ON while a device was pause-orphaned during the OFF window MUST NOT cause double-release (no thrash, no "ensure-on then re-pause" flap). | Any tick sequence around T-off→T-on where the device switch state toggles more than once. |
| INV-D2-LEDGER | For every emitted decision, `battery.current_park_floor()` in the NEXT tick equals the reserve level that was ACTUALLY sent to the Enpower `reserve_battery_level` number (including any post-`_result` overlay). | A tick where `_apply_evse_battery_hold` raises the reserve to R but the next tick's `current_park_floor()` returns something < R. |
| INV-D2-DEADBAND | INV-EV-DEADBAND from v5.15.0 remains byte-identical for the non-hold path; the overlay ledger update is byte-identical on the pre-overlay path when overlay is inactive. | Diff of emit sequence on the no-hold path pre/post cycle. |
| INV-D3-AUTHORITY | For each load-bearing call site of `compose_release_floor` at the EV/plug arms (`energy.py:~2871-2974`), mutating that site's `reserve_soc=_release_floor` to `reserve_soc=0` (or equivalent neuter) causes at least one NAMED test to fail. | A neutered site produces a green test suite. |

---

## Deliverables

### D1 — Toggle-pinned pause-owner release (D-HIGH-3)

**Bug (repro, legal config).**
1. `switch.ura_energy_coordinator_ev_tou_management` = ON, TOU peak hits, `garage_a` added to `_paused_by_us`.
2. Operator flips the switch OFF mid-peak.
3. The off_peak branch containing the release path (`energy.py:~2943`) is gated on `self._ev_tou_enabled`, so release never runs. `garage_a` remains in `_paused_by_us` forever; ensure-on defers to the set (`energy_pool.py:558-570`); restore path re-adds after restart.

Symmetric bugs for `_paused_by_fill_priority` (`_excess_solar_enabled`, `energy.py:2888/2974`) and `_paused_by_grid_cap` (`_grid_import_cap_enabled`, `energy.py:2818`).

**Design options considered.**

- **Option A (RECOMMENDED) — release-only path always runs.** Split each gated branch into a two-part structure:
  ```
  # Feature-active decisions (add-to-set + evaluate rules)
  if self._<feature>_enabled:
      <existing decision logic that may ADD to set S>
  # RELEASE-ONLY path: runs unconditionally each tick
  self._release_orphans(S, reason=<owner>)
  ```
  `_release_orphans` iterates `list(S)` and discards any device where the pause condition no longer holds (mirrors the existing "should still be paused?" predicate but with the feature-off short-circuit inverted to "always clear"). Preserves ONE decision code path per toggle transition. Restart behaviour: same path drains the restored set on first tick.

- **Option B — clear-on-transition + skip restore.** Add a setter side-effect on the toggle (`energy.py:5432` for `_ev_tou_enabled`; add symmetric for the other two): when transitioning ON→OFF, `S.clear()`. Modify restore (`energy.py:1096-1327`) to skip re-adding when the corresponding toggle is OFF.
  - Weakness: race between toggle-off and in-flight EV controller tick; requires transactional clear. Also: OFF→ON mid-night edge — restored set was cleared, so any legitimate "should still be paused" state is lost (fine for TOU because next tick re-evaluates, but adds a re-latch cycle).

- **Recommendation: Option A.** Single code path, matches "compose then decide" pattern already used in `compose_release_floor`. OFF→ON mid-night edge is naturally handled — the feature-active decision block re-adds on next tick if warranted. Add DEBUG log on any orphan-drain event to make the transition observable.

**Files touched.**

| File | Change |
|---|---|
| `energy.py` | Extract release predicates into `_should_release_from_<owner>(evse_id) -> bool`. Add unconditional `_release_orphans_<owner>()` calls immediately after each of the three gated branches (~2818 grid-cap, ~2888 fill-priority, ~2943 TOU, plus plug mirrors ~2974 and ~2818 if applicable). |
| `energy.py:1096-1327` | Guard restore: skip re-add for each owner set when its owning toggle is currently OFF. Cite the toggle attribute in the guard for grep-ability. |
| `energy.py:5428-5440` (+ new symmetric setters) | On toggle ON→OFF transition, log DEBUG "toggle_off_orphan_drain_scheduled owner=<name>" (no clear — the release path handles it next tick, keeping one code path). Add setters for `_excess_solar_enabled` and `_grid_import_cap_enabled` if not already present. |
| `energy_pool.py` | No structural change — existing discard predicates remain. Confirm they still evaluate correctly when called from the new release-only path (they were called from the feature-active path before). |

**Units-and-signs.** No new arithmetic. All values are set-membership (device_id strings). No unit ambiguity.

**Acceptance criteria.**
- **Verify (unit):** `test_tou_orphan_drains_within_one_tick_after_toggle_off` — set up `_paused_by_us = {"garage_a"}`, flip `_ev_tou_enabled = False`, run one decision cycle → set empty.
- **Verify (unit):** `test_fill_priority_orphan_drains_across_restart_with_toggle_off` — persist non-empty `_paused_by_fill_priority` with `_excess_solar_enabled=False` in restore payload → restore leaves set empty.
- **Verify (unit):** `test_toggle_off_then_on_no_double_release` — set membership toggles at most once during OFF→ON→OFF sequence.
- **Verify (unit):** `test_orphan_drain_defers_when_other_owner_holds` — device in both `_paused_by_us` and `_paused_by_grid_cap`; flip TOU toggle off; `_paused_by_us` clears but device remains paused via `_paused_by_grid_cap`.
- **Live:** With `garage_b` unplugged (safe test-plug substitute), pause it via `_paused_by_fill_priority`, then flip `switch.ura_energy_coordinator_excess_solar_charging` OFF. Within 2 decision cycles (~10 min), plug is released. Sensor attribute `paused_by_fill_priority` on `sensor.ura_energy_ev_status` (or equivalent) drops the entry.
- **Live:** Same test, then restart HA. Post-restart set does not contain the plug.

---

### D2 — EVSE-battery-hold reserve visible to release floor (E-MED-1)

**Bug (repro, legal config).**
`_apply_evse_battery_hold` at `energy.py:2614` mutates `decision["reserve_level"]` to elevate it during an active EVSE charging session (any EVSE `power > EVSE_CHARGING_POWER_THRESHOLD`). Applied AFTER `determine_mode` returns (call sites `energy.py:2737` and `energy.py:3143`). `_result` inside `determine_mode` (`energy_battery.py:3345`) has already set `_last_reserve_level` from the PRE-overlay value. Result: `current_park_floor()` (`energy_battery.py:760-761`) reads the pre-overlay reserve. `compose_release_floor` (`energy_battery.py:146-190`) uses that floor at `:173`, so a second EVSE (or a smart plug in the fill-priority arm) checking "may I release?" believes the release floor is lower than the hardware actually sees. Second EVSE's drain-paused release path fires early, defeating the hold.

**Fix.** Stamp the hold-adjusted reserve into the same ledger. Two shapes considered:

- **A (RECOMMENDED) — stamp inside overlay.** After `_apply_evse_battery_hold` mutates `decision["reserve_level"]`, and if the mutated value ≠ pre-overlay value, write it back to `battery._last_reserve_level` and update `_last_reserve_level_at`. Preserves `_result` as the write path for the base case; the overlay explicitly announces "I raised the emitted floor and here's the ledger to match." Include comment linking to INV-D2-LEDGER.
- **B — compose overlay inside `compose_release_floor`.** Teach `compose_release_floor` to consult `_apply_evse_battery_hold` (or a pure function it factors out) and return the effective floor. More elegant but changes the contract of `compose_release_floor` and risks INV-D2-DEADBAND drift on the non-hold path. Higher blast radius.

**Recommendation: A.** Contained mutation; the overlay already exists as the "post-decision fix-up" surface — this is codifying what it already logically does.

**Files touched.**

| File | Change |
|---|---|
| `energy.py:2614` (`_apply_evse_battery_hold`) | After mutating `decision["reserve_level"]`, if changed vs pre-overlay: `self._battery._last_reserve_level = int(max(0, min(100, decision["reserve_level"])))` and set `_last_reserve_level_at = utcnow()`. Comment: "INV-D2-LEDGER: overlay must persist to ledger so `current_park_floor()` reads the value the hardware sees." |
| Same helper | Add explicit unit comment: `# reserve_level unit = % SOC (0-100), sign = floor (minimum)`. |
| `energy_battery.py:2990` | Update stale line ref in NOTE comment (currently says `energy.py:2453`) to the live line, and note ledger-stamp behavior. |

**Preserve.**
- INV-EV-DEADBAND (v5.15.0). Overlay must remain byte-identical on the no-EVSE-charging path (`decision["reserve_level"]` unchanged → no ledger write).
- Off_peak gating from `853827b0` — the overlay's activation predicate is unchanged.

**Units-and-signs (mandatory block).**
- `reserve_level`: unit = **% SOC**, range [0, 100], semantic = **discharge floor** (battery may not discharge below this). Sign: **positive**, monotone-in-conservatism.
- `_last_reserve_level`: same unit/semantic; must always equal the value last written to Enpower.
- `_last_reserve_level_at`: unit = UTC datetime; sign = wall-clock forward.
- No thresholds newly introduced; existing `EVSE_CHARGING_POWER_THRESHOLD` (100 W, `energy_pool.py:305`) untouched.

**Acceptance criteria.**
- **Verify (unit):** `test_evse_battery_hold_stamps_ledger` — force overlay to raise reserve from 20 → 60; assert `battery._last_reserve_level == 60` post-overlay.
- **Verify (unit):** `test_second_evse_release_defers_during_hold` — overlay active on EVSE-A, EVSE-B in drain-pause; `compose_release_floor` returns hold-elevated floor; EVSE-B release path defers.
- **Verify (unit):** `test_overlay_no_op_byte_identical` — no EVSE charging → decision dict and ledger unchanged pre/post overlay.
- **Verify (unit):** `test_deadband_preserved_under_overlay` — INV-EV-DEADBAND regression fixture from v5.15.0 still passes.
- **Live:** Observe on `sensor.ura_energy_coordinator_battery_strategy` during an EVSE charging session: `current_park_floor` attribute equals the value being written to `number.enpower_*_reserve_battery_level` at the same wall-clock instant.

---

### D3 — Coordinator-tick test harness (test infra only, zero runtime change)

**Problem.** `energy.py` imports `homeassistant.helpers.dispatcher.async_dispatcher_connect` (v5.12.0 substrate resubscribe). Quality-suite HA stubs lack this symbol; the file is unimportable. v5.15.0 Review C therefore accepted an extracted-helper compensating construction (tests exercised the helper, not the call site).

**Fix.**

1. Locate the HA stubs directory (grep `quality/` for `sys.modules["homeassistant"`, `class HomeAssistant`, existing dispatcher stubs).
2. Add symbols to the dispatcher stub module:
   - `async_dispatcher_connect(hass, signal, target) -> callable` (returns a no-op unsubscribe).
   - `async_dispatcher_send(hass, signal, *args)` (records into a list the test can assert against).
   - `dispatcher_connect`, `dispatcher_send` if any file in URA still uses the sync forms.
3. Add any adjacent missing sibling that surfaces during import (record every ImportError; fix and re-run).
4. Add a smoke test: `test_energy_module_imports_cleanly` — literally `import custom_components.universal_room_automation.domain_coordinators.energy` under the stub scaffolding; must pass.
5. Author the mutation-anchor tests the v5.15.0 cycle deferred:
   - `test_ev_tou_release_call_site_is_authoritative` — mutate `energy.py:~2943` to replace `reserve_soc=_release_floor` (or equivalent) with `reserve_soc=0`; a NAMED test (`test_ev_tou_release_honors_compose_floor`) must fail.
   - Same shape for `energy.py:~2888` (fill-priority) and `energy.py:~2974` (plug mirror).
   - Table shape (mandatory in the test docstring):

     | Site (file:line) | Neuter | Anchoring test | Expected on neuter |
     |---|---|---|---|
     | energy.py:~2943 | `reserve_soc=0` | `test_ev_tou_release_honors_compose_floor` | FAIL |
     | energy.py:~2888 | `reserve_soc=0` | `test_fill_priority_release_honors_compose_floor` | FAIL |
     | energy.py:~2974 | `reserve_soc=0` | `test_plug_release_honors_compose_floor` | FAIL |

6. **Prove the harness proves itself.** Include a self-test that intentionally neuters one site (via a fixture that patches the module source or monkeypatches at import time — NOT an aggregate `_floor_reserve` monkeypatch) and asserts the corresponding anchor test FAILS. This is the check Review C could not perform.

**Files touched.**

| File | Change |
|---|---|
| `quality/<ha_stubs_path>/dispatcher.py` (or equivalent) | Add the missing symbols. |
| `quality/tests/test_energy_module_import_smoke.py` (NEW) | Import smoke test. |
| `quality/tests/test_energy_release_call_sites.py` (NEW) | Mutation-anchor tests + self-proving fixture. |

**Units-and-signs.** N/A — test infra.

**Acceptance criteria.**
- **Verify:** `PYTHONPATH=quality python3 -m pytest quality/tests/test_energy_module_import_smoke.py -v` passes.
- **Verify:** Each anchor test in the D3 table FAILS on its neutered site and PASSES on unmodified source.
- **Verify:** Self-proving fixture PASSES (i.e. it correctly observes the anchor test failing).
- **Live:** None — pure test infra.

---

### D4 — L1 plug off-peak proactive ensure-on (post-plan operator addition, 2026-07-13)

**Origin.** Post-plan live incident 2026-07-13, 01:04 local: operator
manually flipped `switch.socket_2` on because URA would NOT start it —
plug was off at boot and the L1 pool controller had no proactive
turn-on path. Added to the cycle after the plan doc was filed.

**Bug.** `SmartPlugController.determine_actions(period)` (`energy_pool
.py:1864` pre-build) has a peak/mid_peak pause branch but the `else`
branch ONLY resumes plugs already in `_paused_by_us`. A plug that was
never paused by URA (fresh boot, manually toggled off, plugged in late)
sits idle through the entire off_peak window regardless of TOU.

**Fix.** Mirror the EVSE proactive off_peak ensure-on
(`EVChargerController.determine_actions` off_peak branch,
`energy_pool.py:528-636`) — carry-over guards win (drain / fill /
load-shed / TOU-us), force-charge cedes, else ensure-on and claim
`_proactive_offpeak_holds`. New `_proactive_offpeak_holds: set[str]`
added to SmartPlugController init. New `prune_removed_plugs()` mirrors
`_prune_removed_evses` for options-flow reload cleanup.

**Files touched.**

| File | Change |
|---|---|
| `energy_pool.py` `SmartPlugController.__init__` | Add `self._proactive_offpeak_holds: set[str] = set()` |
| `energy_pool.py` `SmartPlugController.determine_actions` | Split off_peak branch into carry-over guards → force-charge cede → ensure-on + claim hold. Signature adds `force_charge_active: bool = False`. |
| `energy_pool.py` `SmartPlugController.prune_removed_plugs` (NEW) | Drop stale membership from all owner sets when a plug is removed from options. |
| `energy.py` decision cycle | Thread `force_charge_active=self._ev._is_force_charge_active()` into `_smart_plugs.determine_actions(period, ...)`. |

**Preserve.**
- Peak / mid_peak pause behavior byte-identical (`_paused_by_us` still
  populated, `switch.turn_off` still issued).
- Load-shed carry-over precedence unchanged.
- Unknown-period safe no-op behavior preserved (legacy TOU
  bookkeeping still drops; no proactive-on issued).

**Acceptance criteria.**
- **Verify (unit):** `test_plug_offpeak_ensure_on_starts_off_plug` —
  plug off at off_peak with no carry-over guard → turn_on issued and
  `_proactive_offpeak_holds` claims it.
- **Verify (unit):** `test_plug_offpeak_defers_to_battery_drain_
  carryover` — battery-drain carry-over holds, no turn_on.
- **Verify (unit):** `test_plug_offpeak_ceded_when_force_charge_active`
  — force-charge cedes, plug not claimed.
- **Verify (unit):** `test_plug_peak_still_pauses` — regression guard on
  the unchanged peak branch.
- **Verify (unit):** `test_plug_prune_drops_removed_plug_membership` —
  reload discipline.
- **Live:** After deploy, `switch.socket_2` (or any managed L1 plug)
  observed OFF at off_peak start receives `switch.turn_on` within 5 min
  and appears in the coordinator's `_proactive_offpeak_holds` diagnostic
  attribute.

---

## Tier classification and review framings

**Tier 2-DB** (three framing-disjoint reviews). Rationale: pause-owner release paths are cross-coordinator (energy ↔ energy_pool ↔ energy_battery) with restart-persistence surface AND toggle-transition matrix — classic regression-prone shape. Not Tier 3: no state-machine invariant threading; no monetary/safety single-path failure mode (release-late is a comfort/efficiency issue, not a money-losing silent-drain).

If during build the write-verification cycle merge reveals wider ripple (e.g. `compose_release_floor` semantics changed), **escalate to Tier 3** and add a fourth adversarial-completeness pass.

| Pass | Framing | Focus |
|---|---|---|
| A — release-path correctness incl. toggle-transition matrix | Per-site correctness of the new release-only paths; truth table over `(toggle ∈ {ON, OFF}) × (owner set ∈ {∅, {a}, {a,b}}) × (transition ∈ {none, ON→OFF, OFF→ON, restart})` for each of the 3 owners. Cross-owner deferral preserved (`energy_pool.py:558-570`, `:751-757`). D2 ledger stamp is byte-identical on the no-hold path. |
| B — restore/persistence + cross-owner deferral | ≤10h staleness restore behavior when toggles are OFF at boot AND when they flip during the restore window. Restart with mixed set membership. Order of restore vs. first tick vs. toggle read. Ensure INV-EV-DEADBAND is preserved end-to-end (restore → first tick → overlay → emit). |
| C — test-authority via real mutation incl. D3 harness proving itself | The D3 table above. Reviewer C personally neuters each named site in the source, runs `pytest`, and confirms the anchor test FAILS. Green suite on any neutered site = fail C. Also: verifies the self-proving fixture actually proves what it claims. |

Pre-review baseline tag: `git tag pre-review-v<version>` before any review-fix commit.

---

## Live-validation table (populate post-deploy per README write-back MANDATE)

| ID | Criterion | Entity/attr | Expected | Observed | PASS/FAIL |
|---|---|---|---|---|---|
| D1-L1 | Fill-priority orphan drains within 2 cycles after toggle OFF | `sensor.ura_energy_ev_status` attr `paused_by_fill_priority` | plug id absent within 10 min | | |
| D1-L2 | Restart with toggle OFF leaves set empty | Same attr, post-restart tick 1 | empty | | |
| D2-L1 | `current_park_floor` matches Enpower reserve during hold | `sensor.ura_energy_coordinator_battery_strategy` `current_park_floor` vs. `number.enpower_*_reserve_battery_level` | equal | | |
| D2-L2 | INV-EV-DEADBAND preserved | v5.15.0 acceptance fixture | PASS in suite | | |
| D3-L1 | Import smoke test green in CI | pytest output | 0 failures | | |

---

## Open operator questions (truly undecidable)

1. **D1 Option A vs Option B semantics on OFF→ON mid-night edge.** Option A re-adds on next tick if the feature-active predicate still fires (natural), whereas Option B leaves the set empty until next full re-evaluation. Both are correct; A minimizes surprise, B minimizes thrash. Recommendation stated (A) but operator may prefer B if any of the three features has slow-to-re-latch semantics I have not seen in `energy.py`. Please confirm A is acceptable OR name the feature that benefits from B.
2. **D2 EVSE-battery-hold overlay semantic when active on `full_hold` from inclement.** If inclement `full_hold` has already set reserve = `_full_hold_floor(current_soc)` and overlay would set it lower (unlikely but combinatorially reachable if EVSE draw drops), do we take `max()` (safe — pick the more conservative floor) or defer to inclement always? Recommend `max()` for symmetry with `_floor_reserve`, but this is a policy call. Confirm before build.

---

## Deferred / not in this cycle

- Sweep for other feature-toggle-gated release paths in HVAC / presence coordinators (out of scope; different files).
- Making the `_apply_evse_battery_hold` overlay a formal branch of `determine_mode` rather than a post-hoc mutation. Larger refactor; risks INV-D2-DEADBAND.
- Any change to `compose_release_floor` signature (kept stable this cycle to avoid contract churn with the in-flight write-verification cycle).
