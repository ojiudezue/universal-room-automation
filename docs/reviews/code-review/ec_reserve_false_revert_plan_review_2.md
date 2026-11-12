# Plan review #2 (adversarial build-prediction): EC reserve false-revert fix-up

Plan: `docs/planning/PLANNING_ec_reserve_false_revert_fixup.md` @ 18c84aa11 (rev 1). Tier 3, review 2 of 2.
Framing: "what will the builder get wrong reading this?" Code read: `energy_write_verify.py` 515-614, 961-980, 1015-1240, 1316-1350; `energy.py` 2107, 7385-7415, 9785-9810.
HVAC/presence state-of-play docs not read (energy-only surface, no HVAC/presence touch).

**Verdict: FIX-PLAN** (2 HIGH, 4 MEDIUM, 4 LOW). The core design (a witnessed-confirm memory, `last_changed <= T_c`, untrusted != contrary) holds up. The gaps are about ordering, restart, and D2's value.

## HIGH

### H1. HA restart kills D1 for the rest of the command. The plan does not say so, and INV-F2(e) states the wrong reason
- Code: the reserve ledger `(C, T_c)` is **restored** across restart (`energy.py:2107`, `_last_reserve_level_at = _parse(r.get("commanded_at"))`). The cloud number's State is recreated at boot, so its `last_changed` = boot time, which is later than the restored T_c.
- Effect: after any HA restart between the 21:00 write and the ~23:05 drop, the stamp re-arms (local is live) but condition 4 (`last_changed <= T_c`) is False for the rest of that command. The false page comes back that night. This is fail-closed, but restarts are frequent in this house (restart-storm memory), so the fix is silently void on those nights.
- What the builder will do wrong: write `test_restart_memory_none_fail_closed` with a fresh verifier and **no** restored ledger, so the test stays green and says nothing about the restored-ledger case. Or "fix" it by ignoring `last_changed` when it equals boot time, which is an unreviewed widening.
- Plan fix: add to §10 "**R3** HA restart after T_c: the ledger is restored (energy.py:2107), but the oracle `last_changed` resets to boot time, so condition 4 fails and the nightly page can recur that night (fail-closed, accepted)". Re-word INV-F2(e) to "memory None, and oracle `last_changed` = boot > restored T_c, so both block". The restart test must seed the restored ledger plus an oracle set after T_c, and assert a page. If the operator wants restart coverage, that is a separate, reviewed design (the age-bounded park). Do not let the builder improvise it.

### H2. D2 only ever delays a true page. Its own acceptance tests show that. One option is correct: drop it, or justify it with a measured case
- Under D1, the 10-30 case (same-value re-send at 23:06, Envoy down, memory set) is already CLOUD_STALE. D2 only changes the outcome when **there is no memory**: either the local never confirmed C (the 10-24 real divergence) or the memory was lost on restart (H1). D2's first Verify ("no memory → no page; next tick → page") shows it buys one tick of silence on exactly the cases that should page.
- What the builder will do wrong: build it faithfully (~40 LoC, a new latch, a new knob, a fifth mutation anchor, more review surface) for zero false-page reduction under D1.
- Plan fix: either (a) delete D2 and the `RESERVE_REVERT_REDISPATCH_GRACE_S` knob, recording in §9 "D2 is subsumed by D1. Revival trigger: a live false page with no witness memory and a same-tick re-send". Or (b) state the concrete false-page instance that D1 does not cover, with its timeline. This is the marginal-benefit rule. Recommend (a).

## MEDIUM

### M1. Stamp placement relative to the STALE fast path and the ledger read is under-specified, and one reading leaks INV-F2(a)
- `_sweep_surface` order: STALE fast path (:1021) → ledger read (:1029) → ledger-None (:1030) → window (:1034). The plan says only "top … before the verify-window early return".
- If the builder puts the stamp after the STALE return, contrary readings seen while the record is STALE never clear the memory. `schedule()` revives the record on a **same-value** re-dispatch, and the ledger does not move (value-change only). The old memory then still satisfies `value == C and at >= T_c`. Repro: memory (15, 21:01) → strategy retires STALE → Envoy reads 10 (contrary; not cleared because the sweep is skipped) → same-value re-dispatch revives the record → Envoy drops → the cloud is still 10 with `last_changed` before T_c → CLOUD_STALE, and the real revert goes unpaged. This breaks INV-F2(a).
- Plan fix: "The stamp/clear step runs as its own call at the very start of `_sweep_surface` for the reserve surface. It reads `_commanded_ledger` itself, and runs **before** the STALE fast path, returning silently if the ledger is None. It runs on every sweep regardless of record status." Add `test_contrary_while_stale_clears_memory`.

### M2. Mutation anchor (3) is contrived, and the claimed reason for the ordering is wrong
- §3.1 says the pre-window placement "is needed because the 21:00:14 confirmation falls inside the first window". But the local reading stays live for about 2 h after the write, and post-window sweeps run every decision cycle (`energy.py:7410`, about 5 min). A stamp below the window return would still be made at 21:15. The live false cases were all classified CLOUD_STALE post-window, so the stamp is not missed in practice.
- What the builder will do wrong: write a test where the Envoy drops inside the first 900 s, purely to make anchor (3) go RED. That pins an unrealistic shape and hides the M1 ordering that actually matters.
- Plan fix: replace the justification with "the ordering is defensive (Envoy drop inside the window)". Replace anchor (3) with "move the stamp below the STALE fast path → `test_contrary_while_stale_clears_memory` RED" (M1).

### M3. `last_changed` vs T_c: types and the oracle source
- T_c comes from `utcnow()` or `_parse(...)` (energy.py:2107, 5682, 5778, 10000, energy_battery.py:8197). It is tz-aware UTC, and `State.last_changed` is tz-aware UTC. A builder who compares against `last_updated` or `last_reported` breaks the semantics, because `last_updated` moves on attribute-only writes and a cloud poll can refresh attributes.
- Plan fix: "Use `hass.states.get(oracle).last_changed` (never `last_updated` / `last_reported`). `oracle` is the same eid `_oracle_entity_for(surface)` returned in this sweep. If the State is None, condition 4 is False. Compare aware datetimes; if T_c is naive, the helper returns False (fail-closed), never raises." Add a test where the oracle gets an attribute-only update after T_c and the result is still CLOUD_STALE.

### M4. "Unavailable vs untrusted" needs one concrete sentence, and condition 3 needs its `soc` argument pinned
- `trusted_local_reserve` returns `"unavailable"` for a State that is None, for `unavailable` / `unknown`, **and for any non-numeric state** (:546-551). It also returns before the SOC checks, so it does not depend on SOC. The plan's list in §3.1 is right but scattered across two places.
- What the builder will do wrong: call `trusted_local_reserve(battery, C, None)` for condition 3. A live local above C would then return `soc_unknown_high` and not `local`, which is harmless here but drifts from `_local_confirms`. Or call it twice per sweep with SOC reads in between, which gives inconsistent reasons in one sweep.
- Plan fix: "Read once per sweep: `soc = self._read_soc_via_resolver(battery)`, `local, reason = trusted_local_reserve(battery, C, soc)`, and reuse it for the stamp, the clear, and condition 3. Concretely, 'Envoy down' = `reason == "unavailable"`, which means the State is missing, unavailable/unknown, or non-numeric. Every other non-`local` reason is 'untrusted' and is neither a stamp, nor a clear, nor qualifying."

## LOW

- **L1. D2 placement (if kept).** "Before the REVERTED stamp at :1173 (after the D1 stamp and the window check)" could mean right after the window. That would defer the matched, desire-retire and stale-desire paths too. Pin it: "immediately before `rec = self._records[surface]` / `was_reverted` (after the stale-desire block, :1166)". Compare `int(attempt_value) == int(C)`, because the attempt is an int (`value_i`, energy.py:9786) and the ledger may be float after a restore.
- **L2. §3.1 date typo.** "10-22: stale since 18:27" does not match the instance list (10-24/29/30/31). Fix it, and cite the recorder query that shows oracle `last_changed <= T_c` for all three false instances. That is the empirical premise of condition 4 (measure-before-build), and the plan currently asserts it without evidence.
- **L3. Diagnostic attributes.** `reserve_witness_confirm_at` must be emitted as an ISO string. A raw datetime in `extra_state_attributes` serializes, but the existing verifier attrs block uses strings. State that `None` renders as null.
- **L4. Test authority.** Require the tests to drive `WriteVerifier._sweep_surface` with real `hass.states.async_set` under the time freezer, so `last_changed` is produced by HA core. Do not mock `hass.states.get` to return a hand-built State with an injected `last_changed`: mutation (1) would still go RED, but the test would no longer check core's same-state preservation (`core.py:2315`), which is the premise. Assert on `_emit_anomaly` rows and the `_maybe_fire_nm` call, not on `rec.status` alone.

## Checks that hold (no change needed)
- Only one `write_reverted`/`reverted` NM emitter (:1216-1235). D1 sits at the existing D3 gate after the coalesce and before pending suppression, as the plan says.
- Rejecting `_reserve_last_ok_*` is correct. It is stamped on APPLIED at the attempt instant (energy.py:9803-9805), so it would mask 10-24.
- The memory keyed on `(value == C, at >= T_c)`, plus the ledger moving only on a value change, does invalidate old memory on a new command.
- The strict `< RESERVE_DISPATCH_DEADBAND_PCT` comes from `_local_confirms` (:586), so the "±2" boundary is strict with no int/float hazard (local is float, C is int/float).

## Must-fix list before build dispatch
H1 (state R3, fix INV-F2(e) and the restart test), H2 (drop D2 or justify it with evidence), M1 (stamp before the STALE fast path, plus a test), M2 (re-anchor mutation 3), M3 (pin `last_changed` and types), M4 (single read, a concrete definition of "unavailable"). LOWs are optional, but L2's evidence citation is strongly recommended.
