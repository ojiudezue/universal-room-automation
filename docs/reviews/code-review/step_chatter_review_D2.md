# STEP Chatter-Quarantine — Review D (RE-RUN, adversarial completeness)

- **Cycle:** STEP chatter-quarantine (`feature/step-chatter`)
- **Fix-up commit under review:** `569b7848a` ("STEP Tier-3 fix-up: D-HIGH-1/2 + D-MED-1/2 + M-A1 + C-CRIT-1/2/3 + B-LOWs")
- **Prior D pass:** DO-NOT-SHIP, 2 HIGH + 2 MED (D-HIGH-1 healthy-fast false-quarantine, D-HIGH-2 boot-transient primes quarantine, D-MED-1 numeric-id Z2M classifier escape, D-MED-2 no rung-2 backout).
- **Companion evidence:** `docs/planning/PROBE_mmwave_healthy_cadence.md` (7-day recorder, 5-min windows: healthy worst burst = 7, weakest chatterer = 13 → clean [8,12] gap).
- **Scope:** worktree `.claude/worktrees/step-chatter` at `569b7848a`; whole exclusion/occupancy surface, not just the fix diff. Read-only except this file.

## Verdict: **SHIP-WITH-CONDITIONS**

Both HIGHs closed. Both MEDs closed. The ~85 LoC helper extraction is disciplined — tick ordering preserved, Reading-A byte-identity preserved on the D2-raise no-op path, all 6 fusion sites route through the extracted helper. Invariants INV-CHATTER-1/2/3/4 hold across the whole surface.

**Ship conditions (all pre-deploy, none require another cycle):**
1. **D2-MED-1** — Run `git status` in the worktree immediately before `deploy.sh` and `git restore` any working-tree file left mutated by the batch test suite. Verified twice this session that a batch run of the cycle tests leaves the tree modified (see finding).
2. **D2-LOW-1** — Remove the dead bare-attribute-read line in `_discharge_chatter_latches` (`coordinator.py:2331`).
3. **D2-LOW-2** — Comment-only: document the T_floor-knob-requires-room-reload asymmetry (K is live, T_floor is baked at register time).

None of the three condition items require a re-review pass; the operator can apply them inline pre-deploy.

## Per-finding closure verification

### D-HIGH-1 (healthy fast mmWave false-quarantine) — **CLOSED**

**Recalibrated defaults** (`const.py:3822`, `3828`, `3847`, `3848-3853`) match the probe:
- `DEFAULT_CHATTER_BURST_K = 10` (was 20 — K=20 missed invisoutlet at burst=13).
- `DEFAULT_CHATTER_T_FLOOR_S = 1.0` unified across all four blind-time families (`pir`/`mmwave`/`opener`/`reed`).
- `CHATTER_OBSERVATION_WINDOW_S = 300.0` (was 600) — matches the probe's rolling-window basis.

**Falsification re-attempt against the whole detector surface:** the healthy-worst-vs-chatterer-weakest gap [8,12] gives K=10 a symmetric margin. A legal-config sensor whose healthy operation produces ≥10 sub-1.0s edges in 300s? Under normal residential PIR/mmwave/occupancy motion, no reachable repro. The probe did not directly measure OPENER healthy cadence — a plausible-but-atypical stress pattern (kids repeatedly cycling a garage door within 5 min at sub-second cadence) is the only construct I can build, and it is mitigated by the rung-2 knob and per-sensor `T_floor=0` kill switch. Residual is **accepted** (see D2-INFO-1).

**Backout wired:** `CONF_CHATTER_BURST_K` + `CONF_CHATTER_T_FLOOR_S` register in `_NM_A2_KEYS` (`__init__.py:5640-5641`), no CM reload needed.

### D-HIGH-2 (boot-transient primes quarantine) — **CLOSED**

`chatter_detector.py:477-492` — the boot-settle early-return moved BEFORE the deque append AND before `_last_edge_ts`/`_last_edge_state` mutation. Traced:

```
prev_state_val = _last_edge_state.get(...)  # pure read
if prev_state_val == state_val: return       # dedupe (pure)
if not boot_settled: return                  # ← EARLY RETURN, no writes
now = ...; prev_ts = ...; _last_edge_ts[eid] = now; _last_edge_state[eid] = state_val
```

Post-settle first edge sees `prev_ts=None` → no interval computed → no sub-floor recorded. No pre-settle state persists into the post-settle scoring. INV-CHATTER-2 holds. Anchored by `test_d_high_2_boot_transient_no_instant_quarantine_on_restart`.

### D-MED-1 (numeric-id Z2M classifier escape) — **CLOSED**

`chatter_detector.py:130-145` + `195-206` add the Zigbee-native platform fallback. A numeric-id Z2M entity `binary_sensor.0x00158d..._occupancy` on `mqtt`/`zha`/`zwave_js`/`deconz` with a device-class of `motion`/`occupancy`/`presence`/`opening`/`door`/`window`/`garage_door` now resolves to `zigbee_pir`/`zigbee_mmwave`/`zigbee_reed`/`garage_door` and matches the allow-list.

**Residual escape (accepted, silent-default-DENY design):** a Zigbee-native numeric-id entity with NO device_class on the registry AND NO device_class in state attributes still escapes. That is the plan's intentional contract — an uncategorised device is not scored. The state-attribute fallback (`chatter_detector.py:305-311`) shrinks this window further.

### D-MED-2 (no rung-2 backout for K/T_floor) — **CLOSED**

`config_flow.py:6916-6939` — both knobs wired as `NumberSelector`s in the coordinator-notifications-volume step, bounded (K: 1..10000; T_floor: 0..10.0 with step 0.1). Both keys registered in `_NM_A2_KEYS` (`__init__.py:5619,5640-5641`) so an options change takes effect via `nm_cycle_a_knob` without a CM reload. `_effective_burst_k()` (`chatter_detector.py:333-345`) reads on every edge (live). `_effective_t_floor_default()` (`chatter_detector.py:314-331`) is read only at `async_register_listeners()` — see D2-LOW-2 below.

## Refactor-induced NEW-leak re-enumeration

The fix-up extracts ~85 LoC into three methods on `RoomCoordinator`:
- `_fusion_filter_active(self, sensors)` — the single is_excluded consumer (6 fusion sites).
- `_apply_chatter_tick(self, stuck_sensors, room_name)` — chatter release + promote block.
- `_discharge_chatter_latches(self, room_name)` — B-LOW-4 kill-switch-flip discharge.

Checked properties (all preserved):

1. **§D1.1 tick ordering** — `_async_update_data` still does `reset_tick → P22 → snapshot prev-excluded → STUCK-1 D2 → _apply_chatter_tick(stuck_sensors, room_name)` (`coordinator.py:2743, 2745, 2789, 2798-2966, 2987`). Chatter tick still runs AFTER the D2-else branch, and its `_exclusion_set.promote("chatter", ...)` writes into the already-quiet set on the D2-raise path → Reading-A byte-identity holds because chatter's promotions are `chatter`-client-only and the fusion filter reads `is_excluded()` (a chatter promotion never blocks a dutycycle release that would have been visible pre-refactor).

2. **6 fusion sites route through the helper** — `coordinator.py:3000, 3006, 3012, 3026, 3034, 3042`. Structural asserted by `test_all_6_fusion_sites_route_through_fusion_filter_active` (count ≥ 6). Behavioural asserted by `test_fusion_filter_active_extracted_matches_coordinator` which AST-extracts the method from `coordinator.py` and drives it (a source mutation to `_fusion_filter_active` reds this test — confirmed by drill_1).

3. **Exception isolation** — outer `try/except` at `coordinator.py:2986-2992` wraps the helper call; inside, per-entity `try/except` guards each NM schedule (`2231-2248`, `2270-2297`). Pre-refactor semantics preserved: a mid-tick chatter exception never escapes to `_async_update_data`.

4. **`stuck_sensors` mutation across the helper boundary** — passed by reference, `stuck_sensors.add(_ceid)` inside `_apply_chatter_tick:2257` mutates the caller's set. Behaviour matches pre-refactor. Downstream code doesn't read `stuck_sensors` after the chatter tick (all fusion legs use `_fusion_filter_active`) — the add is effectively dead but harmless.

5. **`_stuck_sensor_kinds` pop is provenance-guarded (B-LOW-2)** — `_apply_chatter_tick:2226-2227` checks `self._exclusion_set.clients_for(_rel)` AFTER the chatter release. When stuck_dutycycle still promotes the entity, `clients_for` returns non-empty → label preserved. Anchored by `test_apply_chatter_tick_b_low_2_pop_guarded_by_provenance` + positive control `test_apply_chatter_tick_release_pops_label_when_no_other_client`.

6. **Kill-switch state machine (B-LOW-4)** — flip-detection `if self._chatter_kill_switch_last and not enabled` (`2200`) fires discharge for exactly the True→False edge. Combinatorial extremes checked: True→False→True across ticks correctly re-arms fresh (discharge cleared `_chatter_nm_fired`; next enabled tick re-populates from `chatter_detector.chattering_entities()`). Initial value `_chatter_kill_switch_last=True` on a kill-switch-off-at-boot deployment fires an empty-drain discharge (harmless). Diagnostic-surface population happens BEFORE the early return (`2208-2213`), so D5 stays useful even when chatter is disabled.

7. **`_LATCHES` process-locality** — `_stuck_signal_nm._LATCHES` is a module-level dict (`_stuck_signal_nm.py:47`), cleared on restart. `_chatter_nm_fired` is also process-local. Both clear in sync → B-LOW-4 discharge semantics survive restarts correctly.

8. **`_discharge_chatter_latches` per-room isolation** — `drain = [k for k in list(self._chatter_nm_fired) if k[1] == room_name]` (`2308`) filters to THIS room only — doesn't discharge sibling rooms' latches.

## NEW findings from D re-run

### D2-MED-1 — Mutation-drill framework is NOT crash-safe under batch pytest (test hygiene / pre-deploy hazard)

**Bug class:** unrestored-mutation-drill (see `feedback_unrestored_mutation_drill_poisons_evidence.md`).

**Reachable repro (confirmed twice this session):** running the batch
```
PYTHONPATH=quality PYTHONDONTWRITEBYTECODE=1 python3 -m pytest \
  quality/tests/test_chatter_tick_helper.py quality/tests/test_chatter_detector.py \
  quality/tests/test_chatter_wire_in.py quality/tests/test_sensor_exclusion.py \
  quality/tests/test_unavailable_entities_chatter.py -q
```
leaves `custom_components/universal_room_automation/coordinator.py` with an uncommitted diff — first time `_fusion_filter_active` body was replaced with `return list(sensors)`, second time `coordinator.py:3000` was replaced with `for s in motion_sensors  # MUTATION drill: bypass fusion helper`. `git diff` after the run confirms real working-tree modification.

Root cause: `_SourceMutation.__exit__` writes-back succeed under normal flow, but if the enclosed subprocess `pytest -x` triggers unusual pytest exit conditions (mid-drill import failure in the subprocess, restore-race between overlapping drills that mutate the same file, or an outer error swallowing the context manager exit path), the file is left mutated. Empirically the batch does leave residue.

**Blast radius pre-deploy:** if the Pre-Deploy Zero-Bugs Gate runs this batch and the operator does not `git status` immediately before `scripts/deploy.sh`, a **shipped release could contain the mutation** — e.g. `_fusion_filter_active` returning `list(sensors)` would completely defeat chatter + stuck-sensor exclusion in production. This is worst-case a silent CRIT in production; the mitigation is a `git status` gate the operator already runs, but the risk is real.

**Ship condition:** operator MUST `git status` before `deploy.sh` and restore any file the batch left modified. Verified restore is a no-op semantic — the commit `569b7848a` itself is clean; the mutations are only working-tree artifacts.

**Recommended follow-up card (not blocking):** wrap the drill framework with a `pytest_sessionfinish` hook that runs `git checkout -- custom_components/universal_room_automation/ quality/tests/` unconditionally, OR add a per-drill session-scoped fixture that snapshots + restores the affected files via git regardless of `__exit__` success.

### D2-LOW-1 — Dead-code line in `_discharge_chatter_latches`

`coordinator.py:2331`:
```python
        self._exclusion_set  # keep attribute alive across restart
```

Bare attribute read; the comment ("keep attribute alive across restart") describes no real Python semantic. Almost certainly a stray from an earlier draft. Remove.

### D2-LOW-2 — Rung-2 knob asymmetry: `CONF_CHATTER_T_FLOOR_S` is NOT live

`_effective_burst_k()` (`chatter_detector.py:333`) is called from within `_on_edge` — the operator's K change takes effect on the very next edge. `_effective_t_floor_default()` (`chatter_detector.py:314`) is called ONLY from `async_register_listeners()` (line 364) — the T_floor is baked into `_entity_to_meta` at register time. Changing `CONF_CHATTER_T_FLOOR_S` at runtime requires a room-entry reload (or the `_update_signal_subscriptions` rebuild hook to fire) before it takes effect.

Not a leak (rung-2 backout still works, just with an extra operator step). Recommend: either read the operator override live in `_on_edge` (one dict lookup per edge — negligible cost) OR add a `_NM_A2_KEYS`-adjacent hook that re-registers the chatter listener when this key changes. Cheapest fix: document in `const.py:3846` that T_floor override requires a room reload, so the operator doesn't puzzle over why nothing changed.

### D2-INFO-1 — Opener healthy cadence not empirically probed (accepted residual)

The 7-day probe measured PIR/mmwave/occupancy healthy cadence but did not enumerate a healthy ratgdo/reed opener stress pattern. K=10 is not directly probe-anchored for openers. The only construct that plausibly breaks it (garage door cycled sub-second, 10 times in 5 min) is atypical + operator-visible. Rung-2 knobs are the backout. Live-watch first-week `sensor.<room>_unavailable_entities` for any opener that lands in `chatter` unexpectedly; if one appears, per-sensor `T_floor=0` disables scoring for that sensor without redeploy.

## Combinatorial-extreme table (Tier-3 mandate, all pass)

| K | T_floor (s) | enabled | Reachable? | Behaviour | Verdict |
|---|-------------|---------|------------|-----------|---------|
| 1 | 0.0 | True | legal | Every sensor skipped (kill switch per-sensor) — no promotions possible | safe |
| 1 | 10.0 | True | legal | Any interval <10s → sub-floor; K=1 → instant quarantine on any real motion | operator-shot-foot; rung-2 backout is meant to allow this |
| 10000 | 1.0 | True | legal | K never reached → nothing quarantined (effective kill) | safe |
| 10 | 1.0 | False | legal (rung-2 off) | Zero promotions (INV-CHATTER-4); diagnostic-surface still populates | safe |
| default | default | True→False→True across ticks | legal | Discharge fires on T→F; re-arms fresh on next F→T tick | safe |
| default | default | boot with rung-2 off (init _last=True, enabled=False) | legal | Empty-drain discharge on tick 0; _last=False afterwards | safe |

Reading-A byte-identity on D2-raise path: chatter's promotions are chatter-client-only and don't cross-contaminate the (empty-this-tick) dutycycle exclusion. Preserved.

## Invariant conclusion

**INV-CHATTER-1 (no healthy sensor false-quarantined at normal cadence):** HOLDS. Empirical gap [8,12] at unified T_floor=1.0s with K=10; residual for openers is accepted with rung-2 backout.

**INV-CHATTER-2 (boot-transient does not prime quarantine):** HOLDS. `_on_edge` early-return before any state-mutating write when `_d2_boot_settle_done()` is False.

**INV-CHATTER-3 (every blind-time-gated family is classifiable):** HOLDS. Substring path + D-MED-1 Zigbee-native device_class fallback. Silent-default DENY is intentional; an uncategorised device is not scored.

**INV-CHATTER-4 (kill switch off → zero promotions into `SensorExclusionSet` + zero NM):** HOLDS. Rung-1 module const AND rung-2 options-flow AND-composed via `_chatter_quarantine_enabled`. Diagnostic-surface (`_chattering_entities`) still populates when off — this is deliberate (D5 diagnostic stays useful in dogfood).

No new HIGH invariant leak introduced by the ~85 LoC helper extraction.

---

*Reviewer D re-run, 2026-08-19. Adversarial-completeness pass over the entire chatter/exclusion surface, including pre-existing code, not just the fix-up diff.*
