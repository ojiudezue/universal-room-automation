# Plan review 1 (completeness): PLANNING_ec_reserve_false_revert_fixup.md rev 1

Reviewer framing: Tier-3 plan review #1, completeness / independent re-enumeration. Plan at commit 18c84aa11.
HVAC/presence state-of-play docs not applicable (energy-only surface; read not required).

## Verdict: FIX-PLAN (1 HIGH, 3 MEDIUM, 3 LOW)

## Independent re-enumeration (greps re-run)

- `write_reverted` anomaly + `alert_type="reverted"` NM: exactly one emission site, `_sweep_surface`
  energy_write_verify.py:1216-1235. Repo-wide grep for `reverted` outside the verifier finds only comments
  (energy.py:5528, 9777) and an unrelated HVAC switch docstring. **Plan section 4 confirmed.**
- `STATUS_REVERTED` set only at :1178. Gate order :1021 STALE → :1030 ledger → :1034 window → :1036-1041 oracle →
  :1046 unit → :1065 matched → :1095 retire → :1144-1166 stale-desire → :1173 coalesce → :1192 D3 → :1209 pending.
  Confirmed.
- Other `alert_type=` emitters in the verifier: 680 cloud_write_leg_unavailable, 769 self_heal_starvation,
  955 mismatch, 1234 reverted, 1542 dispatch_failed, 1594 write_churn, 1670 ev_toggle_tripwire,
  2089 reserve_enforced_divergence, 2487 hardware_noncompliance, 2680/2730 pending ladder. None is a
  "reverted" page.
- Ledger writers `_last_reserve_level_at`: energy.py:5682, 5778, 10000; energy_battery.py:8197; **restore
  from persistence at energy.py:2105-2107** (see H1).
- Attempt stamps `_reserve_last_attempt_value/_at`: energy.py:9797-9798 (every status). Landed stamps
  :9803-9805 APPLIED only. Plan's rejection of `_reserve_last_ok_*` (3.1) is correct and well argued.
- Witness producer: `trusted_local_reserve` :520-571; `"unavailable"` covers state None / unavailable /
  unknown / non-numeric. Downward contrary readings are always trusted (low-SOC guard only covers
  `local > target`), so a downward real revert with the Envoy up always clears the memory. Holds.
- Sweep cadence: called once per decision cycle from energy.py:7410.

## Findings

### HIGH-1 — Restart defeats the fix: restored T_c vs post-boot `last_changed` (INV-F1 coverage gap, unstated residual)
`_last_reserve_level_at` is restored from persistence on boot (energy.py:2105-2107) and moves only on a value
change. The cloud oracle `number.iq_battery_hacs_battery_reserve` gets a fresh `last_changed` at boot when its
integration first writes state. After ANY HA restart, `oracle.last_changed (boot) > T_c (restored)` and helper
clause 4 is False until the commanded value next changes. The memory re-stamps after the restart, but the gate
still refuses, so the false page returns.
Repro (legal): 21:00 command C=20, T_c restored after a 22:00 restart, local reads 20 at 22:01 → memory
(20, 22:01). Cloud stale 10, last_changed 22:00:30. Nightly drop at 23:06 → clause 4 False → `write_reverted`
+ NM. This is the 10-30 incident shape plus one restart. Restarts are frequent (restart-storm memo), and C can
stay unchanged for days, so the window where the fix is disabled is large.
The plan's R1 covers only an unavailable blip. Restart is not stated, INV-F2(e) only tests "memory None", and no
test covers restart → re-witness → drop.
Fix options for the plan to choose between:
(a) Value-based staleness. At the first stamp for (C, T_c), record the oracle raw value. Qualify only while the
oracle raw value still equals that recorded value. Restarts and unavailable blips that come back to the same
value then no longer re-open the page. F2(b) is kept (cloud moved means a different value). The only new blind
spot, A→B→A during an outage, is a subset of R2.
(b) Keep `last_changed`, but compare it to `memory.first_at` instead of T_c, and add R3 + a test.
Whichever is chosen, a measure-first probe is MANDATORY: count recorder transitions of the cloud oracle through
`unavailable`/`unknown` and restarts per night between 21:00 and 23:15 over 14 days. If the predicate fails on
most nights, the fix does not deliver INV-F1 in practice. (Measure-before-build rule.)

### MEDIUM-1 — Stamp placement relative to the STALE fast path and the ledger guard is unspecified (INV-F2 clear-miss)
The plan says only "top of `_sweep_surface`, before the window return at :1034". If the stamp goes after the
STALE fast path (:1021), contrary readings during a STALE period are never seen. Repro: memory (20, t). The
blind-hold stale-desire branch retires the record STALE (:1144-1166). A real revert follows, local reads 10, and
the sweep returns at :1021, so nothing clears. `schedule()` re-fires 20 (same value, so T_c does not move) and
the record revives. The Envoy drops before the next sweep, the cloud is stale at 10, and the page is suppressed
until the Envoy returns. The bound in F2(c) then fails for a revert that happened while the Envoy was UP.
Plan fix: put the stamp/clear step **above :1021** (after the ledger read only), or clear the memory whenever the
record is replaced by `schedule()`. Add a test.

### MEDIUM-2 — INV-F2(c) understates the blind window
F2(c) only covers "an external change during the outage". A revert landing between the last confirming sweep and
the drop (gap of up to 1 tick, more with MEDIUM-1) is also hidden for the whole outage (586/714 min measured).
Restate R2 to cover "a revert after the last confirming sweep" and bound it as last-confirm-tick + outage + 1 tick.

### MEDIUM-3 — Live criterion observes the wrong value
D1 Live expects `reserve_witness_confirm_at ≈ 21:00`. The stamp sets `(C, now)` on every confirming sweep, so
`_at` will be the last confirmation before the drop (≈23:0x), not 21:00. As written, a correct build fails this
check. Change it to "≤ drop time and ≥ T_c", or store `first_at` and `last_at` separately (H1(b) needs
`first_at` anyway).

### LOW-1 — D2 placement is ambiguous
"Before :1173 (after the D1 stamp and the window check)" leaves room for a placement right after the window
check. There it would consume the one-shot `(C, T_c)` key on a matched or retired sweep. T_c only moves on a
value change, so the key could be spent days before it is needed. Pin it to directly above the :1173 coalesce,
after the stale-desire branch. (Review 2's lane, noted for completeness.)

### LOW-2 — Stale line references in 3.2 and 4
`schedule` self-heal starvation is :769, not :586-621 (that range is `_note_cloud_stale` / `_local_confirms`).
`_check` is :826-955, with its mismatch NM at :955, not :702-789. "`_check` write_verification_failed (:769-789)"
points at the starvation NM. Correct these so the builder's "must not change" list is accurate.

### LOW-3 — Live check depends on a stale-cloud night happening
This is acceptable, but add the in-suite replay as the accepted fallback in the README table if no stale-cloud
drop happens before close.

## Checks

| Item | Result |
|---|---|
| Institutional-context section (prior art, greps, REUSE/BUILD) | PASS, apart from LOW-2 line drift. Greps reproduce |
| INV-F1 falsifiable | PASS as stated, but its premise (clause 4) is defeated by restarts (HIGH-1), so practical coverage is unproven |
| INV-F2(a) Envoy up, contrary | PASS (downward reading always trusted) |
| INV-F2(b) cloud moved | PASS |
| INV-F2(c) unchanged-cloud external change | LEAK in its bound: MEDIUM-1, MEDIUM-2 |
| INV-F2(d) never-landed (10-24) | PASS. The `_reserve_last_ok_*` rejection plus mutation anchor 4 is the right discriminator |
| INV-F2(e) restart | PASS for paging (fail-closed). The restart case also breaks INV-F1 (HIGH-1) |
| INV-F3 byte-identity | PASS (scoped to `_sweep_surface`; the new attribute is outside it and that is acceptable) |
| Knob ladder | PASS (both rung 1, kill semantics stated; no-max-age rationale and parked revival trigger given) |
| Acceptance testable / discriminating | PASS except MEDIUM-3; add the restart and STALE-period tests |
| Non-goals explicit | PASS (N1-N5) |
| Parked-plan triggers fired | Phase-2 INV-R3 narrowing documented (2.3). Age-bounded design parked with a trigger. None missed |

## Must-fix before build
HIGH-1 (choose a/b, add the residual or remove it, add the restart test, run the 14-day probe), MEDIUM-1,
MEDIUM-2, MEDIUM-3. LOW-1 and LOW-2 are cheap. Fix them in the same revision.
