# STEP chatter-quarantine — Tier-3 Review B (integration + lifecycle + §D1.1 ordering)

**Branch:** `feature/step-chatter` @ `07b3ad116`
**Base:** `develop`
**Framing (B):** Integration / state-machine integrity; §D1.1 tick ordering; chatter listener lifecycle (Bug Class #38); chatter accumulation vs tick-site consumption; D3 auto-release; restart/boot; CONF flip reach.
**Scope:** `custom_components/universal_room_automation/{coordinator.py, __init__.py, const.py, config_flow.py, sensor.py, domain_coordinators/sensor_exclusion.py, domain_coordinators/chatter_detector.py}` + cycle tests. Adversarial, read-only.
**Verdict:** **SHIP** — B-scope integration is sound. Four LOW cleanups recommended; none block deploy.

---

## Headline verdicts

### §D1.1 tick-ordering verdict — SEMANTICALLY CORRECT (comment drift is a LOW).
Plan text and the coordinator's own comment at `coordinator.py:2555-2559` describe the sequence as
`reset_tick → snapshot _prev_excluded → P22 → STUCK-1 → chatter`.

Actual code sequence:
1. `self._exclusion_set.reset_tick()` — `coordinator.py:2560`
2. `stuck_sensors = self._p22_stuck_sensor_set(now)` — `:2562`
3. P22 mirror-promotion loop into `_exclusion_set` — `:2567-2570`
4. P22 logging + STUCK NM latch — `:2574-2601`
5. `_prev_excluded = set(self._dutycycle_excluded_last_tick)` snapshot — `:2634`
6. `self._dutycycle_excluded_now = {}` — `:2635`
7. `try:` D2 detector loop, STUCK-1 D1 promotions (its own book + mirror into `_exclusion_set`) — `:2637-2723`
8. `except:` D2-raise branch preserves STUCK-1 book — `:2775-2791`
9. Chatter tick site — `:2798-2884`

So the true order is `reset_tick → P22 (populate + promote + NM) → snapshot → STUCK-1 → chatter`.

Why this is still safe: `_prev_excluded` snapshots `self._dutycycle_excluded_last_tick` — STUCK-SENSOR-1's OWN book — which P22 never touches. P22 promotes into the shared `_exclusion_set`, not into `_dutycycle_excluded_last_tick`. The release-scan integrity property that §D1.1 point 2 buys (STUCK-1's release-scan sees an honest last-tick engaged set) is unaffected by P22 running before the snapshot.

The B-MED-1 guard survives byte-identical: on D2-raise, `_dutycycle_excluded_last_tick = _prev_excluded` and `_dutycycle_excluded_now = {s: now for s in _prev_excluded}` preserve STUCK-1's book, and the shared `_exclusion_set` — cleared by `reset_tick()` and re-populated ONLY by the P22 loop that already ran — contains ONLY P22 promotions. That is Reading A byte-identity to shipped v5.75.0 as spec'd in §D1.1 point 3. No compensating `promote("stuck_dutycycle", ...)` in the failure branch (verified: `git grep -n 'promote("stuck_dutycycle"' coordinator.py` yields exactly one site, inside the successful D1 promotion loop). The forbidden Reading-B mutation is not present.

Stuck-recovery NM (`fire_stuck_signal_recovered` for `kind="dutycycle_excluded"`) still fires — the release-edge scan at `:2748-2775` is guarded by `_release_edge_scan_should_run()` and iterates `_prev_excluded - set(self._dutycycle_excluded_now)` from STUCK-1's OWN authoritative book. Grep verified: `fire_stuck_signal_recovered` for `kind="dutycycle_excluded"` fires at `:2755`, unmodified by this cycle.

### Chatter listener lifecycle verdict — CORRECT (Bug Class #38 discipline preserved).
- Registered exactly once per setup via `ChatterDetector.async_register_listeners()` — `chatter_detector.py:254`.
- `async_register_listeners()` calls `_drain_listener()` at entry, guaranteeing idempotency across the two callers: initial `_update_signal_subscriptions()` at first-refresh (`coordinator.py:1421`) and the `_on_entry_update` in-place options-save rebuild (`coordinator.py:1435`). No leaked prior-listener across rebuilds.
- `_entity_to_meta` is rebuilt from scratch each `async_register_listeners()` call — `chatter_detector.py:266`. A config-change room-rebuild picks up new sensors on the very next rebuild; the map cannot go stale past one setup.
- Torn down on config-entry unload: `__init__.py:4817` `chatter.async_teardown()` runs inside `async_unload_entry`. `async_teardown()` at `chatter_detector.py:317-332` calls `_drain_listener()` (releases the stored `_chatter_unsub`) then clears every per-entity tracker. Test `test_chatter_detector_unsubscribe_called_on_teardown` at `quality/tests/test_chatter_detector.py:435` pins the invariant; the neuter drill `test_drill_7_subscribe_teardown_wire` at `quality/tests/test_chatter_wire_in.py:247` proves the teardown is load-bearing (deleting the unsub call reds a NAMED test — mutation-anchored).
- Room-entry reload (individual ROOM entries can reload; CM reload-suppression covers only the parent): `async_unload_entry` runs teardown; the fresh setup constructs a new `ChatterDetector` in `RoomCoordinator.__init__` at `coordinator.py:584` and arms a fresh listener in `_update_signal_subscriptions()`. No inherited state, no leaked callback.

---

## Findings

### B-LOW-1 — Ordering comment vs. code drift (§D1.1 point 2)
**File:** `custom_components/universal_room_automation/coordinator.py:2555-2559`
**Severity:** LOW (documentation only; semantics correct)
**Bug class:** Doc/code drift (recurring — see PLAN vs code review findings).

The comment claims "reset_tick -> snapshot prev-excluded -> P22 -> STUCK-1 -> chatter". Actual: `reset_tick → P22 (populate+promote+NM) → snapshot → STUCK-1 → chatter`. Semantically equivalent because `_dutycycle_excluded_last_tick` (STUCK-1's snapshot source) is disjoint from P22's writes. But the comment lies; a future reader trying to reason about ordering will be misled.

**Fix (5 lines):** rewrite the block comment at `:2555-2559` to reflect actual order AND note why P22 running before the snapshot is safe (disjoint books). Add the same note near `:2634` where `_prev_excluded` is snapshotted.

### B-LOW-2 — Diagnostic-label loss on chatter release when entity is concurrently stuck-engaged
**File:** `custom_components/universal_room_automation/coordinator.py:2810`
**Severity:** LOW (self-heals within one tick; no fusion regression)
**Bug class:** Cross-writer coupling in a shared diagnostic surface.

`self._stuck_sensor_kinds.pop(_rel, None)` fires unconditionally on chatter release. If the released entity is ALSO stuck-dutycycle-engaged this tick (STUCK-1's promotion loop ran EARLIER in the tick and set `_stuck_sensor_kinds[_rel] = "dutycycle"` at `:2632`) OR P22-engaged (`_stuck_sensor_kinds[_rel] = "continuous"` at `:2578`), this `pop` clears the legit label. The diagnostic surface (D5 `UnavailableEntitiesSensor`) transiently loses the kind for ONE tick. Self-heals next tick because P22/STUCK-1 re-populate. The exclusion itself is unaffected — STUCK-1 still promotes the entity into `_exclusion_set` — but operators looking at D5 will see the entity briefly missing.

Trace: tick T. P22 excluded `s`, `_stuck_sensor_kinds[s] = "continuous"`. Later same tick chatter releases `s`. `pop(s)` at `:2810` drops the label. Fusion still correctly excludes `s` via `_exclusion_set` (P22 still promoting). D5 attribute for `s` becomes empty this tick.

**Fix (2 lines):** guard the pop with `_exclusion_set.clients_for(_rel)` emptiness:
```
if not self._exclusion_set.clients_for(_rel):
    self._stuck_sensor_kinds.pop(_rel, None)
```
`clients_for` at `sensor_exclusion.py:145` is exactly the API for this. Alternative: check `if _rel not in self._exclusion_set` (uses `__contains__` at `:163`). Either is fine.

### B-LOW-3 — Confusing comment at chatter kind-label overwrite
**File:** `custom_components/universal_room_automation/coordinator.py:2841-2844`
**Severity:** LOW (documentation only)

Comment reads "Chatter kind label wins over dutycycle/continuous for the diagnostic surface iff the entity is exclusively chattering (else keep the pre-existing kind — a genuinely stuck-AND-chattering sensor is legitimately reported as its more-actionable kind; here chatter is more actionable = hardware fault)." The code at `:2844` UNCONDITIONALLY sets `self._stuck_sensor_kinds[_ceid] = "chatter"` — chatter always wins, not "iff exclusively chattering". Rewrite the comment to just say "chatter kind wins over dutycycle/continuous — hardware fault is the more-actionable diagnosis". No code change.

### B-LOW-4 — Kill-switch flip suppresses without discharge
**File:** `custom_components/universal_room_automation/coordinator.py:2876-2880`
**Severity:** LOW (rare operator action; latch self-clears at calendar-day rollover)
**Bug class:** Suppression without discharge (`feedback_suppression_needs_discharge.md`).

When the operator flips `CONF_CHATTER_QUARANTINE_ENABLED` from True → False while entities are chatter-quarantined, the else-branch runs and mirrors the detector's `chattering_entities()` into `_chattering_entities` for D5 visibility — but does NOT release the shared `_exclusion_set` (in fact `reset_tick()` will clear it next tick, so exclusion is discharged in-band; that part is fine) AND does NOT fire recovered NM for the chatter entities that WERE flagged. The per-day chatter latch in `_stuck_signal_nm._LATCHES` remains set for `(kind="chatter", key=(eid,))`. If the operator re-enables the flag SAME day and the entity re-chatters, the NM re-fire is suppressed by the day-latch — until the day rolls over via `_prune_stale_latches`. Not a correctness bug, but violates the "any suppression on an event-driven path must specify what re-fires it + backstop" doctrine. Latch self-clears at calendar rollover (`_LATCH_MAX_AGE_DAYS`), so the backstop exists.

**Fix (optional, ~5 lines):** in the else-branch, before setting `_chattering_entities`, iterate the currently-flagged chatter set and fire `fire_stuck_signal_recovered(kind="chatter", key=(eid,))` once each so the latch clears. Same shape as the release loop at `:2811-2828`. Alternative: accept the boundary explicitly and document it (add a note that the flag is expected to be operator-toggled at day boundaries, not intraday).

---

## Areas verified, no finding

- **D2-raise Reading-A byte-identity.** The failure branch at `:2775-2791` sets `_dutycycle_excluded_last_tick = _prev_excluded` and `_dutycycle_excluded_now = {s: now for s in _prev_excluded}`, preserving STUCK-1's book. No compensating `promote("stuck_dutycycle", ...)` in the failure branch (grep verified). The shared `_exclusion_set` on the failure tick contains ONLY the P22 promotions performed earlier in the tick — byte-identical to shipped v5.75.0's P22-only exclusion on a D2-raise tick. `test_d2_raise_fusion_byte_identity_reading_a` at `quality/tests/test_sensor_exclusion.py:222` pins this.

- **Stuck-recovery NM still fires.** `fire_stuck_signal_recovered(kind="dutycycle_excluded", ...)` at `coordinator.py:2755` is unchanged by this cycle; grep confirms it survives the migration. The B-MED-1 `_release_edge_scan_should_run()` guard preserves the "no mass-release NM storm on partial detector failure" property.

- **CONF flip reaches detector live.** `CONF_CHATTER_QUARANTINE_ENABLED` is in `_NM_A2_KEYS` at `__init__.py:5634`, plumbed through the NM-Cycle-A live-knob path at `coordinator.py:2168-2176` via `nm_cycle_a_knob(self.hass, CONF_..., default)`, which reads live from the source-of-truth (options + Number/Switch entity states). No CM reload required; effect is next-tick.

- **Chatter accumulation vs sync tick consumption.** `_on_edge` (event-loop callback) is the only writer that ADDs to `_chattering`; `check_release` is the only writer that DISCARDs from `_chattering`. Both run on the same event loop — no threading race. An edge mid-tick simply gets counted in the next tick's `chattering_entities()` snapshot. Double-promote is guarded by `entity_id not in self._chattering` at `chatter_detector.py:406`. Re-flag after release requires K NEW sub-floor events post-release (the `_sub_floor_events` deque is popped at `chatter_detector.py:470`) — correct.

- **Auto-release invariants.** `check_release` at `chatter_detector.py:442-477` correctly (a) requires `CHATTER_RELEASE_QUIET_S` of no edges via `_last_edge_ts`, (b) skips release when currently unavailable/unknown (matches `ActuatorReconciler.check_quarantine_release` doctrine at `actuator_reconciler.py:949-1000` — quiet-on-dead-hardware ≠ stability), (c) clears the per-entity trackers, (d) returns the released set for the caller to `.release("chatter", eid)` on the shared set AND fire `fire_stuck_signal_recovered(kind="chatter", key=(eid,))` (which clears the per-day latch at `_stuck_signal_nm.py:293`, satisfying INV-CHATTER-3 discharge).

- **STEP-EXCLUDE-3 client isolation on chatter release.** Chatter release calls `_exclusion_set.release("chatter", _rel)`. If the entity is also promoted by `stuck_dutycycle` or `p22_continuous`, `SensorExclusionSet.release` at `sensor_exclusion.py:108-120` only removes the `"chatter"` client entry; the entity stays excluded. Test coverage present. No cross-client discharge.

- **Restart/boot semantics.** `async_teardown` clears `_chattering`, `_chatter_since`, `_sub_floor_events`, `_last_edge_ts`, `_last_edge_state`, `_edge_windows` — the plan's "restart → chatter re-detected from live edges" semantics. No RestoreEntity path. `_d2_boot_settle_done()` gate at `chatter_detector.py:371-375` samples edges but does not score during boot — the boot-flurry cannot false-fire, and after settle the K-burst count starts from zero (both `_sub_floor_events` and `_edge_windows` are fresh from teardown, then reseeded from real edges).

- **Fail-safe posture.** Every layer has try/except: `_on_edge` at `chatter_detector.py:344-420`, `check_release` at `:462-467`, the tick-site chatter block at `coordinator.py:2802-2884`. Any raise from the chatter path is swallowed and the tick continues with byte-identical pre-chatter behaviour (except for the P22 + STUCK-1 promotions already applied).

---

## Summary

| Finding | Severity | Blocks ship? | Fix cost |
|---|---|---|---|
| B-LOW-1 ordering comment drift | LOW | No | ~5 LoC comment |
| B-LOW-2 diagnostic label loss on release | LOW | No | 2 LoC guard |
| B-LOW-3 confusing kind-label comment | LOW | No | comment rewrite |
| B-LOW-4 kill-switch flip no-discharge | LOW | No | ~5 LoC in else-branch OR doc note |

**Ship verdict: GO.** All four LOWs are safe to fix in a same-cycle fix-up pass (per `feedback_fix_lows_in_cycle.md`) or deferred with a card each. §D1.1 ordering and chatter listener lifecycle both verify clean. Reading-A byte-identity holds; the forbidden Reading-B mutation is not present.
