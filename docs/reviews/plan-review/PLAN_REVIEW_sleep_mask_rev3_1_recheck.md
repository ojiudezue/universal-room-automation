# Plan re-check — sleep-mask plan §R3.1 (Rev 3.1 fold of R1 + R2)

- **Plan:** `docs/planning/PLANNING_house_state_sleep_mask_ble_memory_observability.md` §R3.1 @ `0620ae63b` (develop).
- **Code:** `feature/house-state-sleep-mask-ble-memory` @ `dad3bf6e7`, read with `git show`. HA core is the installed `.venv-ha` (2026.2.3).
- **Scope:** for each HIGH and MEDIUM in R1 (`PLAN_REVIEW_sleep_mask_rev3_R1_completeness.md`) and R2 (`PLAN_REVIEW_sleep_mask_rev3_R2_build_prediction.md`), check that the §R3.1 resolution closes it and can be built as written. Also look for new hazards, with extra attention on the HVAC D6 cap (PICK R3-4).
- **Read completely first:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, including the §10 ledger C1–C38. No ledger claim is re-asserted here.
- **Line numbers** below are for `dad3bf6e7` unless marked.

**Verdict: FIX-PLAN.** Every R1/R2 HIGH and MEDIUM is closed in design, and I confirmed each one against the code. Two MEDIUMs and four LOWs are left. All of them are plan-text fixes:
- **M1:** the HVAC cap should be carded on its own, not built in this cycle.
- **M2:** the kill-switch test mechanism is underspecified across three modules.

No HIGH.

---

## 1. R1/R2 HIGH and MEDIUM: does §R3.1 close them?

| Finding | §R3.1 resolution | Closed? | Evidence on `dad3bf6e7` |
|---|---|---|---|
| R1-F2 / R2-1 kill switch not byte-identical | R3.1.1: every Rev-3 site gated; limb and forcing line kept under `not` constant | **Closed in design.** Buildability gap, see M2 | Limb at `presence.py:4044-4061` and forcing line at `:6271-6276` both exist as cited. My own list of Rev-3 sites (D4a live, seed, D4b, D4c.1, D4c.2 hook and walk, D4c.3′, refresh restore, D4d, limb, forcing line) matches the matrix row for row. Nothing is missing. |
| R1-F3 / R2-2 seed reads old map | R3.1.2: map passed explicitly; seed passes `desired_entity_to_room_kind` | **Closed** | `_reset_and_seed_room_bucket` already receives `desired_entity_to_room_kind` (`occupancy_substrate.py:294-301`). Step 4 seed (`:482-485`) runs before the map swap (`:510`), so the passed map is the only correct source. Drills `d4a_seed_uses_live_map` cover both add and remove. |
| R1-F4 / R2-9 event entity read from `hass.states` | R3.1.2: payload for the event entity, `hass.states` for siblings only | **Closed** | Today's handler reads only `new_state` (`:668-687`). With no siblings, the new rule computes the same value from the same input, and `hass.states` is never touched. The MagicMock harnesses stay valid. |
| R1-F5 / R2-6 failed subscribe desyncs tracker | R3.1.5: seed into scratch `new_raw`; swap only after subscribe succeeds | **Closed.** See L2 | The failure path returns at `:506` before the map swap (`:510`) and before step 7 (`:535`). With a scratch seed, `_raw_state`, the map and the listener are all still old and consistent with each other. The retry snapshots the untouched old state, sees a non-empty diff (old map vs desired) and emits. |
| R1-F1 / R2-4 kind stuck True after boot settle | R3.1.3: `_reconcile_trackers_to_substrate()` right after `substrate.release_boot_settle()` | **Closed.** See L1 | `release_boot_settle` replays True only (`occupancy_substrate.py:643-647`). The `real_input` release runs inside `_run_inference` (`presence.py:5997`), before the zone-mode capture (`:6014`). The reconcile therefore lands before the same tick reads zone modes. The other two paths (`ha_started`, `timeout`) land before the next tick. |
| R1-F6 / R2-3 removed-room walk never runs | R3.1.4: `async_remove_entry` dispatches `"removed"`; step 7 walks snapshot rooms missing from the desired map | **Closed** | See the removal-order check below. The presence handler filters on no action (`presence.py:3597-3643`). `_discover_entity_map` enumerates `hass.config_entries.async_entries(DOMAIN)` (`occupancy_substrate.py:~197`). URA defines no `async_remove_entry` today; `__init__.py` hits are signal lines only. |
| R1-F7 / R2-10 D4d coverage overstated | R3.1.7: Frigate-dark only; Tier-1 holder required; reset stated | **Closed** (not in this re-check's main scope; text agrees with the census producer R1 cited) | — |
| R2-5 HVAC D6 gate claim wrong | R3.1.6: row corrected; cap proposed (PICK R3-4) | **The correction is right. The cap is the wrong vehicle.** See M1 | Consensus arithmetic verified at `presence.py:7596-7611`. A zone held by Tier-1 with all phones away gives 1 − 0.4 (− 0.1) = 0.5 or 0.6. That cannot engage (< 0.5), but it does pin an engaged gate (< 0.7, `hvac.py:2726-2742`). |

### Removal order in the installed HA core (R3.1.4)
`ConfigEntries._async_remove` (`.venv-ha/.../config_entries.py:2139-2156`, HA 2026.2.3), under `entry.setup_lock`:
1. `async_unload`. URA's `"unloaded"` dispatch fires here (`__init__.py:6140-6147`), and the eager refresh still sees the entry.
2. `del self._entries[entry.entry_id]` (`:2149`).
3. `await entry.async_remove(hass)` (`:2150`). This calls `component.async_remove_entry(hass, self)` (`:1053-1056`).

The hook therefore runs after the entry has left `_entries`. The `"removed"` refresh no longer enumerates the room, so the diff is non-empty and step 7 runs. Two more points:
- `async_remove_entry` is still called when the entry was not recoverable and unload was skipped (`:2145-2147`). That covers deleting a room that was in SETUP_ERROR.
- The plan's cites `:2148`/`:2149` are one line early for this core. Cosmetic.

**Other subscribers of the new `"removed"` action**, checked because the plan does not list them:
- `hvac.py:5441-5449` `_on_room_lifecycle` acts only on `unloaded`, `loaded` and `options_updated`. `"removed"` is a no-op.
- `binary_sensor.py:~1756` `_on_lifecycle` returns unless the entry id is its own. The deleted room's entity was already removed at unload. No-op.

Safe. Record this in the plan (L3).

---

## 2. Findings

### M1 — MEDIUM — the HVAC D6 30-minute cap (R3-4) is scope growth, and its cost side is unpriced. Card it; do not build it in this cycle
**Facts (code):**
- **What an engaged gate blocks.** `hvac.py:2711-2752` returns before the heat_cool enforcer, before S10 and before every S1 block. So an engaged gate pauses all of them, not just "preset writes". That is pre-existing.
- **What S1 writes under house AWAY.** The target preset is `away` for every zone (`hvac.py:2830`). Zone occupancy only retreats `home`/`sleep` and never overrides `away`: "Only override home/sleep presets — away/vacation are already correct", `hvac.py:2911`. The state of play agrees (§9e Q4).
- **What the gate was built for.** The −0.4 term is the v4.7.15 "phones say away, zones say occupied" disagreement. README_v4.7.15 §2 specifies that the gate holds "until `consensus >= 0.7`", with no time bound. The unbounded deferral is the shipped design, not a defect.

**What the cap trades.** After 30 minutes, HVAC writes `away` to all three zones while a Tier-1 sensor still says a zone is occupied.
- If the holder is a phantom (the Jaya LD2410 fan loop), that saves energy. This is the only side the plan priced.
- If the holder is a real person with no tracked phone and no camera hit (a guest, a resident whose phone is dead or left elsewhere), the cap takes away the only HVAC protection they had. The zone goes to Away after 30 minutes.
- Both shapes are legal and reachable today, and this week's household (operator away, Jaya + guest home) is the second shape. The plan doesn't price it.

**Answers to the operator's questions:**
- **Does it break an HVAC invariant or ledger item?** No §10 ledger item names the consensus gate, and none is contradicted. §9e gates, D5 transit, Q4 and the zone-scope constraint are untouched, because the gate is house-level and runs before all of them. It does change shipped v4.7.15 behaviour that the state of play doesn't document: there is no §-row for the consensus defer gate, only the §8 switch row ("Wait for Presence").
- **Is it scope growth?** Yes.
  - D4 cannot *engage* the gate (R3.1.6 says so). The pin is pre-existing for every single-sensor room, which D4 leaves byte-identical. D4 only removes accidental releases caused by wipe gaps in multi-sensor rooms.
  - The cap is an independent HVAC policy change. It has its own constant, outside INV-KILL-BYTE-ID, so the cycle's backout lever does not back it out.
  - It pulls a Tier-3 presence cycle into the HVAC review surface (the state-of-play read, HVAC reviewers).

**Measurement gaps:**
- **The plan's "Live" check can't be evaluated.**
  - `_d6_deferrals_today` is a RAM-only `DailyCounter` (`hvac.py:737`; `coordinator_diagnostics.py:880-920`, `persist=False`). Nothing exposes it; the only references are in `hvac.py`, and one source-grep test (`test_v4715_universalize_veto.py:1134`, a hollow anchor, #62).
  - The INFO lines aren't retained either (log level WARNING, state of play §4.3).
- **Nobody has measured whether the gate has ever engaged or pinned.** The data exists to check: the recorder has `sensor.ura_signal_consensus_confidence` (README_v4.7.15) and house-state history. Measure before building.

**Name collision.** "HVAC D6" is already the stale-occupancy failsafe (row-4) in the state of play §3.2 and §12, and also v5.103.23's D6. Calling the cap `HVAC_D6_MAX_ENGAGED_S` and writing an "HVAC D6" row in §9/§10 will confuse the two.

**Fix in plan:**
- Flip PICK R3-4's default to the plan's own alternative: accept the pinned-gate residual by name, with the Jaya hardware card as its remedy.
- Mint a separate card, e.g. `HVAC-CONSENSUS-GATE-PIN-1`. Its first step is a read-only recorder probe: engagements, hold durations, and whether the holder was a phantom or a real occupant. The policy question (time cap, or release only when the holder is a known phantom) goes to the operator with both sides priced.
- If the operator still wants the cap in this cycle, the plan must:
  - name it `HVAC_CONSENSUS_DEFER_MAX_ENGAGED_S`;
  - add a test for the real-occupant shape (house AWAY, all phones away, Tier-1 held by a real person → at the cap, Away is written to every zone; the operator must accept this);
  - expose the engage time and hold length (an attribute or a ledger row), so the live check can be evaluated;
  - add the missing consensus-gate row to the HVAC state of play.

### M2 — MEDIUM (build-prediction) — the kill-switch tests need one patch that reaches all three consumer modules
- The new constant is read in `presence.py`, `occupancy_substrate.py` and `__init__.py`.
- The precedent the builder will copy is `PRESENCE_NOBODY_HOME_READS_RAW_IN_SLEEP`. It is imported by name (`presence.py:66`) and patched on one module (`test_house_state_sleep_mask_ble_memory.py:502`, `monkeypatch.setattr(PR, ...)`).
- Copied as-is, `test_kill_switch_off_*` and the "whole suite with the constant False" conftest pass would patch `presence` only. The substrate and the `async_remove_entry` hook would stay True, so the run is a hybrid that passes while proving nothing about INV-KILL-BYTE-ID.

**Fix:** pick one of these and write it into the plan:
- every gate reads `const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED` as a module attribute at call time, and a lint test forbids `from ...const import ZONE_OCCUPANCY_PER_ENTITY_ENABLED`; or
- the conftest fixture patches all three module bindings, and a test asserts the set of binding modules equals the set the fixture patches.

Also state which tests are excluded from the constant-False pass: the tests Rev 3 rewrites (`test_boot_settle_replay_unchanged`, the re-driven `dh1_*` tests) assert Rev-3 behaviour and will fail under False by design. Name them in the plan; don't leave the builder to find out.

### L1 — LOW — the release reconcile should write only the slots that differ, and must not raise
`update_room_occupancy` has side effects beyond the provenance slot:
- a True write bumps `_last_activity` and auto-clears an AWAY override (`presence.py:857-872`);
- every write sets `_has_sensors` and `_has_room_sensors` to True (`:861-862`, `:895-896`).

`_has_sensors` decides UNKNOWN vs AWAY in `_derived_mode` (`:772-788`). R3.1.3 writes every kind of every tracker room. For a room `_discover_room_sensors` never walked, such as a room renamed through options (`presence.py:~3505-3524` walks by merged name; the tracker keeps the data name, R1-F11), the False writes flip a sensor-less, BLE-less, camera-less zone from UNKNOWN to AWAY at boot. That is a new behaviour, and INV-ZONE-ROOM-TRUTH does not ask for it.

**Fix:**
- Write only where the tracker slot differs from `substrate.get_room_kinds(room)`. In practice that is True→False pops; the True slots were already written by the replay. That also makes "a still-empty room stays `{}`" true without relying on pop.
- Wrap the call in its own `try/except` like its neighbours (`presence.py:2344-2351`). On the `real_input` path it runs inside `_run_inference`, and a raise there would abort the tick.

### L2 — LOW — the scratch seed needs a target parameter, and "self-heals" means one retry
- `_reset_and_seed_room_bucket` writes into `self._raw_state` through `setdefault` (`occupancy_substrate.py:288`). R3.1.5 needs it to write into `new_raw`. Specify a `target` dict parameter, with `async_setup` passing `self._raw_state`.
- The retry is one-shot (`_refresh_retry_pending`, `:566-568`). A second failure leaves the old state, which is coherent but stale until the next lifecycle event. That is acceptable. Say "one retry, then coherent-old", not "self-heals".

### L3 — LOW — record the other `SIGNAL_ROOM_ENTRY_LIFECYCLE` subscribers
Add `hvac.py:5441` and `binary_sensor.py:~1756` to R3.1.4 with "no-op on `removed`, verified". Add a line saying that any future subscriber must treat an unknown action as a no-op. Fix the HA line cites to `:2149`/`:2150` (2026.2.3).

### L4 — LOW — `dh1_*` drills under the constant-False pass
R3.1.10 item 6 keeps `dh1_live_limb_dropped` "valid with the constant monkeypatched False". That drill's anchor must run with the M2 patch, or it goes GREEN for the wrong reason. Tie the drill runner to the same fixture.

---

## 3. New-hazard sweep of the §R3.1 resolutions
- **R3.1.2 payload read:** no new hazard. A deleted sibling reads `None` from `hass.states` and counts as off, which matches D4c.1.
- **R3.1.3 reconcile:** L1. No ordering hazard: the replay and the reconcile write the same `_raw_state` values. The dispatcher calls `@callback` targets in-line, so their order doesn't matter.
- **R3.1.4 hook:** no new hazard (subscribers checked, §1). The hook runs under the entry's `setup_lock`. The eager refresh takes only `_refresh_lock`.
- **R3.1.5 scratch swap:** the body stays await-free, so no event can land between the seed and the swap. L2 only.
- **R3.1.1 gates:** M2 only.
- **R3.1.6 HVAC cap:** M1.

## 4. Invariant checklist (as amended by §R3.1)
| Invariant | Status |
|---|---|
| INV-ZONE-ROOM-TRUTH | PASS in design (reconcile and scratch swap); L1 narrows the writes |
| INV-NO-STUCK-THROUGH-REMOVAL | PASS (all three routes bound to triggers that run; removal order verified on the installed core) |
| INV-SLEEP-NOT-EMPTY | PASS both states (limb kept under the gate) |
| INV-BYTE-ID-SINGLE | PASS by construction (payload read, pop) |
| INV-KILL-BYTE-ID | PASS in design; **its test is hollow until M2 is fixed** |
| HVAC invariants (§9e, D5, Q4, zone scope) | Not broken by the cap; the cap changes the undocumented v4.7.15 deferral policy (M1) |

## 5. Must-fix before build dispatch
1. **M1:** set the R3-4 default to "accept and card", mint the HVAC card with a recorder probe as its first step, or, if the operator keeps the cap, apply all four conditions.
2. **M2:** specify how the constant is read and patched, and list the tests excluded from the constant-False pass.
3. **L1–L4:** one line each in the plan.
