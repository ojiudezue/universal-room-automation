# Review A: SC lock exclude + Away Lock (local correctness)

Branch `feature/sc-lock-exclude-away-lock`, diff `3032edf6...53e488d9` (one commit). Spec: plan rev 3 plus binding amendments and the Build DO/DON'T list. Framing A covers local correctness, edge cases, None handling and HA patterns. Async/race, mutation and completeness belong to B, C and D.
Targeted tests: `test_sc_away_lock.py`, `test_sc_lock_exclude.py`, `test_sc_lock_exclude_options.py`: 91 passed.
Presence touch: the change reads raw `person.state` only. I checked the reader against the plan §2.2 description, which cites presence state-of-play §1. I did not re-read the full presence docs, and nothing in this finding set depends on them.

## Findings

| # | Sev | file:line | Finding | Bug class |
|---|---|---|---|---|
| A1 | HIGH | `security_lock_regime.py:768-777` (`_away_on_person` home branch), `:599` (`_on_boot_recheck`), `:720-724` (`_away_setup`) | **An owned away lock can stay locked with a listed person home, and nothing releases it.** Release fires only on an observed real `→home` edge where `_arrival_counts` holds, or on P2 behind `_really_away`. Repro 1 (restart): both away, E engaged and owned (persisted). HA restarts and Oji gets home during the downtime. At regime setup `person.oji` already reads `home` (old_state None, `restored=True`), so there is no release. `_away_setup` keeps ownership because E reads `locked`, and the boot recheck only re-arms. E stays locked until the next shared outing. Repro 2 (blip gate): engage at t=5 min, then Oji goes `not_home→unknown→home` at t=10 min. `_arrival_counts` falls through to `_really_away`, 10 min < 15 min `BLIP_MIN_AWAY_MIN`, so there is no release, and the stamp is popped and `_away_attempted` cleared. Same stuck state. The engage dwell (5 min) is shorter than the release blip gate (15 min). The plan's "late engage costs nothing" reasoning never covered the release side. **Fix:** a release-direction discharge. At `_on_boot_recheck`, and in `_away_on_person` whenever a listed person reads `home`, if `away_lock_owned` is non-empty then `_away_release(...)`. The away policy has no garage-style blip semantics to protect, and releasing is the fail-safe direction. Add tests for both repros. | Suppression needs a discharge / #53-adjacent |
| A2 | LOW | `security_lock_regime.py:1690-1692` (`_away_release`) | When an owned lock reads `jammed`/`locking`/`unlocking`, ownership is dropped silently with no unlock and no NM (the comment says "already unlocked"). `unavailable`/`unknown` keep ownership instead. Treat any `!= unlocked` real state as unlock-worthy, or keep ownership. | edge case |
| A3 | LOW | `security_lock_regime.py:1711-1714` (`_away_release_on_disable`) | Ownership is discarded before the state check, so an owned lock that is `unavailable` at SC disable loses ownership. `_away_release` keeps it in the same case. Make the two consistent. | edge case |
| A4 | LOW | `security_lock_regime.py:1566-1590` (`_async_away_engage`) | `cfg` is captured once and reused across the `await` for later entities. The kill switch is re-read only from that snapshot. This only matters with 2 or more away entities and a switch flip inside a non-blocking call. Re-read `cfg` per entity. | stale snapshot (#7) |
| A5 | LOW | `security_lock_regime.py:1590-1597` | `_away_engage_inflight` is not persisted. A restart inside the 20 s read-back window leaves E locked and unowned, so an arrival will not unlock it. Very rare. Accept and document, or fold into the A1 boot discharge (unlocking E when a listed person is home and E is listed and locked is a policy choice for the operator). | restart |

### Cleared (holds because…)
- **INV-X1 S1/S2:** `security.py:1729-1747` filters lockdown. `:1781-1784` `continue`s excluded locks before the unlocked branch and before `actions`. `excluded` is captured before the loop. Its value is exclude ∩ locks, which is correct because only registered locks are iterated.
- **INV-X1 S3:** `_engage_predicate` returns `"excluded"` (`:1217-1221`) on the raw exclude set, without intersecting the lock list. That is stricter, which is fine.
- **S4 sanctioned path:** `away_lock_predicate` requires the switch ON, SC alive, E in away ∩ exclude, E not a lockout, every listed person exactly `not_home` with a stamp ≥ dwell, and E `unlocked`. Observation mode is checked before the write (`:1574`). Nothing is awaited between the predicate and `async_call`. INV-X2 holds locally.
- **`not_home`-only:** `_away_due_ts` compares `== "not_home"`. A named zone pops the stamp (`:763-767`). `unknown`/`unavailable` cancel the dwell but keep the stamp. Empty persons gives None, so the rule is inert.
- **Validators:** all three checks run, errors are collected per field, and the form saves only when there are none. away ⊆ exclude ⊆ locks, plus lockouts ∩ locks = ∅, transitively forbids away ∩ lockouts. The argument order of `lock_exclude_not_subset(exclude, away)` is correct (away − exclude). Setup re-validation (D3i) logs a warning, and the predicate skips the entity.
- **Store:** `_store_payload` always writes all three keys. The loader handles each key independently and rejects malformed values.
- **#64 @callback:** `_on_away_dwell`, `_on_away_readback` and `_on_away_lock_event` are decorated. `_away_on_person` is sync and called from a callback.
- **Garage byte-identity:** the resident gate is kept on the old-None garage effects, P1 and approach-zone. `_garage_release_on_disable` keeps its early `return` locally. `on_kill_switch_changed` with key None or the garage key is unchanged.
- **Display:** the aggregator excludes interior locks and adds `locks_excluded`. The sensor fallback has the key. The compliance numerator is filtered by key, so the rate never exceeds 100 %. `doors` flags an excluded lock only for `jammed`.

### Builder deviations (judged from the code; no list was found in the commit message)
1. `_on_away_lock_event` does not forget in-flight on `locked` (the docstring states this). **Accept**: it is safer for H2.
2. `_away_attempted` is not cleared on `unknown`/`unavailable`. **Accept**: the conservative choice.
3. S2 `continue` sits after the compliance write, against develop, because the retry cap is not merged. **Accept**: `test_sweep_excluded_no_retry_episode` must be re-checked when the retry cap rebases.
4. The SC-disable away release uses direct blocking unlocks instead of `_spawn_unlock`. **Accept**: it mirrors the garage teardown. See A3.
5. Policy-aware NM / `_record` wording through a `policy` kwarg. **Accept.**
6. `sweep_exclude()` in the regime is not intersected with the lock list. **Accept**: stricter for S3 and the predicate.

## Verdict: **FIX-REQUIRED**
Must fix: **A1** (release discharge for owned locks when a listed person reads home, at boot recheck and on any home reading, plus tests for both repros). The LOWs A2-A4 are cheap and should be fixed in the same pass. A5: accept or fold into A1.
