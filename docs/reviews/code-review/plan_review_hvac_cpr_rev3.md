# Plan review: Enable Custom Preset Ranges, REV 3 (adversarial, one pass)

**Date:** 2026-09-29. **Plan:** `docs/planning/PLANNING_hvac_enable_custom_preset_ranges.md` REV 3. **Base:** `develop` @ `66950d1cf`.
**Read first:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, all of it (589 lines, including §9e and the §10 ledger C1–C29). This review re-asserts no §10 claim.

**Verdict: REVISE.** 1 HIGH, 4 MEDIUM, 3 LOW. The core design holds: a named-profile edit never creates `manual`, and the arrester's named-preset ignore is at `hvac_override.py:3619-3622`. The fixes needed are all in the plan text; no redesign is required.

---

## 1. Anchor spot-check (14 sites)

**The S10 block anchors are accurate on develop.** All of these match: `hvac.py:664`, `:667`, `:2382`, `:3849`, `:3906`, `:3923`, `:4055-4056`, `:4074`, `:4115`, `:4139`, `:4151`, `:4153`.

**The anchors outside the S10 block are stale.** These are in the §2.1, §3.2 and §6.3 tables and in the D-deliverables:

| Plan cite | Actual |
|---|---|
| `_corrective_writes_suppressed` `hvac_override.py:672` | `:806` |
| `has_active_ac_reset` `:2183` | `:2484` |
| arrester "preset range adjustment. Ignore." `:3216-3226` / `:3220-3223` | `:3619-3622` |
| `_build_zone_state_snapshot` `hvac.py:2081-2103` | `:2329` |
| `_rehydrate_arrester_state` boot `:1059` | defined `:1981` |
| `_note_s1_reclaim` `:1653-1695` | `:1854` |
| `_zones_written_this_cycle` `:455/:1879/:3194` | `:505/:2096/:3672` |
| switch `_last_emitted_range` clear `switch.py:2037-2039` | `:2046-2047` |
| switch paths `:2027/:2035/:2069/:2097` | shifted by roughly 5–10 lines |

There is also a **third `unsuppress` at `hvac.py:4168`** (the exception roll-back). The plan's DELETE list names only `:4150-4151`.

## 2. Write-path re-enumeration: is it really ONE emission site?

**The claim holds in the strong sense.**
- `grep set_activity_setpoint` finds zero callers in URA today. So S10 apply and S10 restore will be the only writers of a named profile's range.
- Every other writer changes something else:
  - S1, S4, S7, the auto-return and the S11/S13 presets-only returns change the *selected* preset.
  - S5, S6 (the HUMAN_MANUAL restore and the INFO-1 person restore), S3, and the S11/S13 human-manual branches write `set_temperature`. That goes to the MANUAL profile and leaves the zone in `manual`, so S10 step 6 skips it.
  - B1, the AC reset and egress change the mode. P2 and skip 5 cover these.

The skip matrix covers every interaction I found (egress, a/b, same-tick, gate e, AC reset, manual, `heat_cool`, unreadable).

## 3. The three blockers

- **Compose-away storm.** Resolved by construction. D3 deletes the only storm source, `hvac.py:4108` (the F2 bypass). **HOLDS.**
- **S10 vs S1.** Resolved by the named-profile write, and D0 item 5 proved no `manual` over about 10 hours. **HOLDS.**
- **Restore writers strand an empty night zone.** The conclusion holds, but the plan cites the wrong proof. The strand mechanism was this: restore writers did not update `_last_emitted_range`, so S10's throttle at `hvac.py:4108` suppressed D9's corrective re-emit.
  - `hvac.py` has exactly one reader of the map (`:4108`) and one writer (`:4153`), and D3 deletes both. With the throttle gone, the strand is impossible by construction. Empty-zone retreat is then S1 row-1 alone, and the presets-only returns land on a preset that S1 flips next tick.
  - D0 item 4 is not the proof; it is still unrun ("Items 1-4 to be filled"). W1-B D2.4 is also not the proof.
  - **See F5.**

## 4. Findings

**F1 — HIGH — a reload-time race with D8 default-OFF fires restore writes while the operator's switch is ON (Bug Class: boot ordering / RestoreEntity).**
- **Evidence:**
  - D8 changes `hvac.py:664` to `False`.
  - §3.2 makes the restore pass *state-driven* on every tick while the flag is False and any snapshot exists.
  - The switch applies its restored value either synchronously (`switch.py` fast path) or later, via `SIGNAL_HVAC_COORDINATOR_READY` (`_handle_hvac_ready`, deferred path). That deferred path exists precisely because the coordinator and the switch start in either order.
  - On a non-cold boot, boot-settle releases at once (`hvac.py:1169-1170`, `not_cold_boot`), and the initial cycle (`hvac.py` ~1363) can run before the switch lands `True`.
- **Repro:** CPR ON, a snapshot exists for (zone_3, away), zone_3 is on away, and the CM entry reloads. Cycle 1 sees the flag False and makes one restore call with the originals. The switch then lands True. Cycle 2's apply pass finds the apply record's value unchanged, so it is a "retry of the same value", gated 130 min. **Zone_3 runs Carrier originals for up to 130 min on every reload.** Each such reload also costs a restore-record attempt and an apply-record attempt, which can walk toward the LIMIT latch and send a spurious NM.
- **Fix in the plan:**
  - Make the flag tri-state: `None` means not yet resolved.
  - S10 does nothing, neither apply nor restore, until the switch has resolved it. That is either the restored value or the no-last-state default.
  - Add `test_s10_no_restore_before_switch_resolved`.
  - Also state that a lost restore-state (default OFF) starts restores **without** the user-OFF NM. Either send the NM or document the silence.

**F2 — MEDIUM — step 3.5 (the interrupt-latch skip) is unreachable, so T10 can only pass with an impossible fixture (Bug Class #62, hollow anchor).**
- **Evidence:**
  - The latch discharges at LEVEL whenever the state is readable, named and not `manual` (`hvac_override.py:1308-1318`).
  - `latch_level_check()` runs at `hvac.py:2226`, before `_apply_house_state_presets` at `:2258`, and so before S10.
  - A latched zone is therefore in `manual` or unreadable, and step 6 or step 0.5 already skips it.
- **Fix:** do one of these:
  - (a) Drop step 3.5, T10, Q8 and L11, and record why ("subsumed by step 6 because of the level discharge at `hvac.py:2226`").
  - (b) Keep it as defence in depth, drop the mutation-anchor claim, and name the predicate exactly: `self._override_arrester.interrupt_latched(zone.climate_entity) is True`. That is the only reader (see `hvac_predict.py:1281-1291`); there is no HVACCoordinator predicate. "grep for it" is not a spec.
- Q8's join against "`preset_change_deferred` rows with `reason=interrupt_latched`" names a reason I did not find emitted. It is UNVERIFIED as written.

**F3 — MEDIUM — D1 contradicts §14 on where the `ha_carrier` literal lives (build-prediction).**
- **Evidence:**
  - D1 puts `async_call("ha_carrier", "set_activity_setpoint")` in the funnel and extends the lint to fail on `"ha_carrier"` *outside* `hvac_setpoint.py`.
  - §14 says the funnel must NOT name `ha_carrier`, that the strategy supplies it, and that the lint should forbid the literal in the funnel body.
  - These are mutually exclusive. The strategy file (`hvac_strategy.py`) would trip D1's lint.
- **Fix:** pick one, and rewrite D1, its lint test and §14 to agree. The lint today keys on the `async_call` domain argument. If the domain comes from the strategy, the lint must also allow a non-literal domain at exactly one site.

**F4 — MEDIUM — INV-RATE is per-value, so the total rate is unbounded under a legal DPM config (config-boundary).**
- **Evidence:**
  - §6.2 says a changed value resets the record and writes immediately.
  - The budget table assumes "DPM change (dwell ≥60 min)". But DPM dwell and hysteresis are operator knobs (`CONF_DYNAMIC_PRESET_DWELL_MINUTES`, `CONF_DYNAMIC_PRESET_HYSTERESIS_F`, `dynamic_preset.py:53-54`).
- **Repro:** dwell 0 with hysteresis 0 near a bucket edge lets cool_high flap 75↔76 each tick. Every change is a "new value", so one call per visit tick. The A→B→A cycle also re-opens A's budget.
- **Fix:** add a per-(zone, preset, mode) minimum spacing across values (a rung-1 constant), or state INV-RATE conditional on the DPM dwell and clamp that dwell's floor. Add a test that flaps two values.

**F5 — MEDIUM — the strand card is closed on the wrong evidence, and `_last_emitted_range` loses its main producer (Bug Class #53 residue).**
- **Evidence:**
  - After D3, the only writer of the map is S13 at `hvac_predict.py:1900-1903`. It writes the pre-heat *pre-borrow* values, possibly days old.
  - S11's `_resolve_baseline_range` still *prefers* the map (`hvac_predict.py:932-948`). Its human-manual raw restore (`emit_set_temperature` with `base_low`/`base_high`) would then write a stale S13 pair, not the preset-resolved fallback.
  - The plan's "KEEP; S11/S13 still use it" is true but hides this producer loss.
  - The map is also no longer cleared on switch OFF (§3.5 deletes `switch.py:2046-2047`).
- **Fix:**
  - Close `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` on the by-construction argument in §3 above, with the grep as evidence.
  - Keep D0 item 4 as corroboration, not the gate.
  - Either make S11 ignore the map entries S13 wrote, or retire the map (S13 as the sole writer and S11 as the sole reader is now a private channel) and put it in the §8 table.
  - Update the stale comments at `hvac_predict.py:933-941, :995-1000`.

**F6 — LOW — stale anchors.** See §1. Refresh the §2.1, §3.2 and §6.3 tables, and add `hvac.py:4168` to the unsuppress DELETE list.

**F7 — LOW — the snapshot capture's "only if the HA view differs" rule interacts with P4.** If the HA view already matches desired because of a guard-masked optimistic copy (C16/C21), no snapshot is taken for a range the cloud may not hold. Harmless for restore, since nothing was edited, but say so in §3.4.

**F8 — LOW — the §7.1 Q7 falsifier is mis-keyed.** An unreadable entity has `state` in {unavailable, unknown}; `values_before.hvac_mode` is not where that shows. Key Q7 on the captured state, or on the absence of an S10 row inside a `climate_write_held_unreadable` episode.

## 5. The invariants, knobs, acceptance criteria and restore-on-off

- **INV-S10 and INV-RESTORE are falsifiable, with good one-shot queries.** INV-RESTORE survives a restart between enable and disable: the snapshot is saved write-ahead, never overwritten, rehydrated, and the restore pass is state-driven. The one exception is F1: a *restart while ON* can execute restore writes. F1's fix is required for INV-RESTORE's intent ("restore only when the operator turned it off") to hold.
- **INV-RATE needs F4.**
- **Knobs:** the two rung-1 constants have rationale; switch 01 is the kill switch. Fine.
- **Acceptance criteria discriminate** (the §7.1 table). L3's app check is correctly the only oracle.

## 6. Tier recommendation

Stay at Tier 2-DB, and **add a mandatory fourth reviewer (D, adversarial completeness) scoped to INV-RESTORE and the switch/boot lifecycle.**
- The "one emission site" argument is correct for *writes*, so full Tier 3's threaded-value trigger does not strictly fire.
- But the change is comfort-impacting and its effects persist on the device. The persisted snapshot is the operator's only path back.
- F1 is exactly the class A/B/C converge on missing: a pre-existing boot-ordering path combined with a changed default plus a new state-driven pass.
- A D pass costs one reviewer. A wrong restore costs a manual app repair per zone × preset.
- The operator checkpoint before deploy already exists (deploy is held), so the rest of Tier 3's stringency is already present.

## 7. What the builder will get wrong

1. Carrying D1's literal placement *and* §14's rule, then fighting the lint (F3).
2. Guessing the latch predicate, or writing a T10 fixture with a named-and-latched zone that cannot happen (F2).
3. Using the stale §2.1 anchors for `_corrective_writes_suppressed` and `has_active_ac_reset` and the arrester-ignore lines, and missing the `:4168` unsuppress (F6).
4. Flipping the default to False without guarding the first cycles (F1).
5. Deleting the switch-OFF map clear while leaving S11's preference for a now-S13-only map (F5).
6. Calling `_climate_unreadable` a second time in S10. It is episode-idempotent per zone, but the builder must not add a second ledger write. The plan says this; a test should assert one row per episode with both S1 and S10 active.

## Must-fix before build dispatch
F1, F2, F3, F4, F5 (plan text only). F6–F8 in the same edit.

---

## REV 3.1 re-check (errata only, grep-verified on `66950d1cf`)

**Verdict: REVISE (small).** F2, F3, F6, F7 and F8 are closed. F1, F4 and F5 need one more pass each: R1 and R2 below must be fixed, and R3–R5 are small.

| Finding | Closed? | Note |
|---|---|---|
| F1 | Partly | See R2 (a gap where the flag stays None forever) and R4 |
| F2 | Yes | Step 3.5, T10, Q8 and L11 are dropped. The note names the one real reader. |
| F3 | Yes | One rule: the literal lives only in `hvac_strategy.py`. Build-time check: the existing lint must accept the funnel's *non-literal* `async_call(service_domain, …)`. Verify that the AST test does not reject a Name-typed domain argument. |
| F4 | Yes, with arithmetic fixed | See R5. Rung 1 is correct: 600 s is a Carrier call-rate bound, the same governance as `HVAC_DECISION_TICK`. |
| F5 | **No** | See R1 and R3 |
| F6 | Yes | Anchors match my spot-check, and `:4168` is added. |
| F7, F8 | Yes | — |

**R1 — MEDIUM — D3c misses a second producer of the map.** The errata say S13 is the map's only producer after D3. That is false.
- S11 writes the map itself at `hvac_predict.py:1153-1154` (`last_emitted[zone_id] = (emit_low, emit_high)` when `update_throttle`).
- The `update_throttle` kwarg is defined at `:974` and passed at `:482` and `:1260`.
- D3c must delete the S11 write, the kwarg and both call-site arguments.
- Its "grep returns empty" build check would catch this, but the deliverable text would steer the builder wrong.
- **Test files:** 11 test files reference `_last_emitted_range`: `test_arrester_comfort_delay`, `test_freeze_floor`, `test_hc_precool_oc_observability`, `test_hvac_excursion_banking_migration`, `test_hvac_excursion_preheat_migration`, `test_hvac_live_room_hold_wire_in`, `test_hvac_w1b_returns_and_strategy`, `test_hvac_w1w2_finish_part_b`, `test_v471_fixup_d2_d3_d4`, `test_v5_7_1_energy_precool`, `test_zzz_hvac_conditioning_demand`. D3c must list them for rewrite or retirement, like D3 does.

**D3c safety (the coordinator's question).**
- **What S11 writes now:** S11's values matter only on its HUMAN_MANUAL branch, the raw `emit_set_temperature(base_low, base_high)`. The named-snapshot branch pins the preset and writes no values.
- **Before:** that branch could write the map's pair. That was either S13's pre-heat pre-borrow values or an earlier S11/S10 pair, possibly days old.
- **After:** it writes `_resolve_baseline_range`'s fallback (`hvac_predict.py:951-968`): the configured `(heat, cool)` of the house-state target preset. This is well-defined and never stale, and the low side is fixed since v5.103.22.
- **The change for a pre-heat case:** when the map entry came from S13 on a human-manual pre-heat snapshot, S11 used to write the person's own pre-heat values by accident. It now writes URA's baseline. That is a small behaviour change on a rare path, and it is arguably more correct (the person's values are the pre-*heat* token's, not the banking token's). **Safe. State it in D3c.**
- **Other readers:** outside tests, only `hvac.py:4108` (deleted by D3), `hvac_predict.py:932` and `:1003`, and `switch.py:2046`. No sensor, diagnostics or frontend reads it. Safe to retire.

**R2 — MEDIUM — the tri-state flag can stay None forever, so restores never run.**
- The flag is resolved only by the switch entity (`async_added_to_hass` / `_handle_hvac_ready`).
- If the entity is disabled in the registry, or the switch platform fails to set up, no entity is added and the flag stays `None`. S10 is then inert permanently: no apply (fine) and **no restore**. Edited presets keep URA's ranges indefinitely.
- **Repro:** CPR ON with snapshots; the operator disables the switch entity (a legal registry action) to "turn it off". The originals are never restored, and there is no NM.
- **Fix:** add a backstop. After boot-settle release plus N ticks (or a timeout), a still-`None` flag resolves `False` via `set_custom_ranges_enabled(False, source="unresolved_backstop")` and sends the F1 NM. Add a test.

**R3 — LOW — `test_s13_no_map_write_after_retirement` is a grep-as-test (Bug Class #62).** Keep the grep as the build-time check. Anchor the test behaviourally instead: run the S13 return and the S11 release, and assert which values S11 writes.

**R4 — LOW — `None`-unsafe readers the tri-state must handle.**
- `hvac.py:3923` `if not self._guest_mode_actuation_enabled` treats `None` as OFF, which is exactly the F1 bug. The `is None` return must come BEFORE it.
- `hvac.py:3940`, `sensor.py:10199/10231` and switch `is_on` (`getattr(..., True)`) read the flag. They need an explicit `None` rendering: unknown or pending, not `True`.
- D8's "change all four defaults to False" should now read "init `None`; readers render `None` explicitly".

**R5 — LOW — F4 test arithmetic.** A flap over 30 min with 600 s spacing allows calls at 0, 10, 20 and 30 min, which is 4, not "≤3". Either assert ≤4 or run the flap for 25 min.

**Must-fix before build dispatch:** R1, R2 (plan text). R3–R5 in the same edit. No re-review needed if they are applied as written; the build's Reviewer D covers the lifecycle.
