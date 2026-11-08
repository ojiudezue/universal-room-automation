# Plan review 1 — PLANNING_sc_lock_exclude_and_door_regime.md rev 2

**Reviewed:** commit 56774965 (develop). Tier 2 adversarial plan review (CLAUDE.md "Plan Review — TIERED").
**Mandatory reads:** presence state-of-play and SENSOR_FLEET_CLASSES are cited by the plan. This review checks only the plan's use of raw `person.state` against `security_lock_regime.py`. No presence-ledger claim is re-asserted. HVAC: not applicable.
**Verdict: FIX-PLAN.** 2 HIGH, 6 MEDIUM, 5 LOW. The emission-site enumeration holds. The gaps are in the D3 restart, ownership and persistence specs, plus two consumers the plan does not name.

## Emission-site re-enumeration (independent)

Greps run: `'"lock"'`, `lock\.lock`, `lock\.unlock`, `SERVICE_(UN)?LOCK`, `ServiceCallAction`, and every file that both mentions `lock` and calls a service. The results match the plan's §3:

- `lock.lock`: `security.py:1705` (S1 lockdown, callers `:1086` and `:1629`), `security.py:1750` (S2 sweep), `security_lock_regime.py:1091` (S3).
- `lock.unlock`: `security.py:2160` (U1), `security_lock_regime.py:599` (SC disable) and `:948` (U2).
- AI-rule allowlist: `coordinator.py:1210`, `config_flow.py:3366` and `:15494` (C1).
- No lock writes in optimization, NM, safety or energy. **No missed emission site. INV-X1 surface: PASS.**

Consumers of `_lock_entities` / `CONF_SECURITY_LOCK_ENTITIES`: `security.py:690` (log), `:732` (sweep timer gate), `:1699`, `:1736`, `:2156`, `:2476/2482`, `:2581`, and `house_status.py:139`. Two consumers are missing from §2.1 (M1, M2).

## HIGH

- **H1. D3e boot recheck can never engage, so its test is unbuildable.** D3e engages at `_on_boot_recheck` only if every person has a non-restored `_last_real` older than the dwell. The recheck fires `GARAGE_LOCKOUT_BOOT_RECHECK_S` = 120 s after setup (`security_lock_regime.py:465-466, 473-476`). Every non-restored stamp is younger than 120 s, so it can never be older than 300 s. Without the recheck, a person still away after a restart is stamped `restored=True` (`:766-772`) and never moves again, so INV-X2 fails for the rest of the outing. §2.2 contradicts itself: it says either one real transition or the boot recheck. Restart mid-dwell has the same effect: the timer is lost and engage never happens. Fix: pick one rule and state it. Either (a) a restart forfeits the engage for this outing (the cheap option, a nuisance only), and delete `test_boot_recheck_engages_if_genuinely_away`; or (b) persist the per-person `not_home` since-timestamps and trust `person.last_changed` explicitly. With (b), say why the HA person restore that rewrites `last_changed` (see the `_boot_rebuild` docstring, `:483-488`) does not poison the dwell.
- **H2. A release inside the read-back window leaves the lock locked and owned by no one, and ownership can appear after the release.** Ownership is recorded only at the engage read-back, 20 s after the call (D3b). Release unlocks only `away_lock_owned` (D3c, INV-X3). Repro: both persons away for 300 s, engage issued at t. Oji arrives at t+10 s. Release finds nothing owned, so nothing is unlocked. At t+20 s the read-back sees `locked` and adds ownership. The bedroom stays locked with Oji home until the next all-away → arrival cycle. The garage policy covers this case with `_lock_in_flight` / `pending_lock` (`:891-894, 910-924`). Fix: release must also unlock entities in `_away_engage_inflight`. Cancel the pending engage read-back on release so it cannot record ownership afterwards. State this in INV-X3 ("owned **or engage in flight**") and add a test: arrival at t+10 s → `lock.unlock` issued, and E is not owned afterwards.

## MEDIUM

- **M1. Aggregator sensor passthrough drops `locks_excluded`.** `SecurityAggregatorSensor.extra_state_attributes` (`sensor.py:7745-7777`) copies 9 named keys and has a stable-shape fallback (Bug Class #37). A new key in `get_security_aggregator_state` never reaches the entity. D2d must edit both dicts, and `test_aggregator_excludes_excluded` must assert on the sensor attributes, not on the coordinator dict.
- **M2. Unnamed consumer: the optimizer SECURITY_POSTURE anomaly** (`optimization.py:3911-3965`) reads `locks_unlocked` from the aggregator. Dropping excluded locks changes when the anomaly fires, which is the intended effect. List it in §2.1 as a trust-adjacent consumer, add a test that an excluded unlocked lock raises no posture anomaly, and confirm that is what the operator wants.
- **M3. The Store save would wipe `away_lock_owned`.** `_save_residents` writes `lambda: {"residents": ...}` (`security_lock_regime.py:1226-1233`), replacing the whole payload. Every resident add or remove would erase the persisted owned set. The plan says only "next to residents". Specify one save function that writes both keys, and test it: add a person, reload the Store, and `away_lock_owned` is still there.
- **M4. The SC-disable release is gated on the garage kill switch.** `async_release_if_disabled` returns early on `not self.kill_switch_on()` (`:592-593`), and `kill_switch_on()` reads the garage key (`:222-233`). Repro: garage lockout OFF (the default), away lock ON and owned, SC disabled → the bedroom stays locked. D3c lists SC disable as a release trigger without saying the early return has to be split. `_release(force=False)` (`:875`) and `engage_predicate` (`:1048`) use the same accessor. Spec: a separate `away_lock_on()` accessor; the garage path stays byte-identical; the away-lock path is not gated by the garage switch. Add a test: garage OFF + away owned + SC disable → unlock.
- **M5. The reload-key policy for the away-lock lists is missing.** D2 and D4 add exclude and the kill switch to `_NO_LIVE_ATTR_KEYS` and `OPTIONS_RELOAD_SUPPRESS_KEYS` (`__init__.py:7348-7358, 7640-7656`). D3d registers the ownership state listener at setup. If `security_away_lock_entities` is reload-suppressed, a newly added lock is never tracked. If it is not, every edit reloads the CM. State which one applies for `_ENTITIES` and `_PERSONS` (recommended: entities reload on change, like `lockout_entities`, which is not in the suppress set; persons read live). Add `_away_dwell_unsub` and the engage read-back unsubs to the `async_teardown` loop (`:537-548`); the plan never mentions teardown for the new timers.
- **M6. The "one advisory per outing" latch is missing from D3a.** D3b's no-retry, one-LOW-per-formation behaviour needs explicit state, for example `_away_attempted: bool`, set on attempt and cleared when any listed person leaves `not_home`. It is not in the D3a state list. A builder will either re-attempt on every person event (an NM stream) or never re-arm. Also specify the timer arming rule. "Latest dwell expiry across listed persons" is undefined while any listed person is not `not_home`. Arm only when every listed person currently reads `not_home`.

## LOW

- **L1.** The §2.1 fallback text cannot be implemented and contradicts itself. `_cfg()` never raises (`_cm_entry` swallows errors and returns `{}`, `:201-220`), so a failed read means "exclude nothing". For S1, "skip all lock commands" on a read failure would also suppress the egress lockdown. Simplify to: the read cannot raise; a missing CM entry means SC is not running.
- **L2.** D2b's compliance change must filter `_lock_compliance` **by key**. `get_compliance_summary` (`security.py:2579-2590`) sums values. Excluded entries are still written (the `continue` comes after the write), so an away-locked bedroom would count as compliant while missing from `total`, giving a rate above 100 %.
- **L3.** Validators (a), (b), (c) are written as independent `errors[...]` keys, but the existing code is an if/else that returns on success (`config_flow.py:9058-9070`). The spec should say: collect all errors, then save only if none. Add a test that clearing the exclude field to `[]` persists. `vol.Optional(default=current)` together with `{**options, **user_input}` merge is a known risk for "can't clear". I have not verified HA's behaviour here; test it, don't assume.
- **L4.** D2 Live says "two sweep intervals (60 min)". The interval is 60 **minutes** (`security.py:737`, live value 60), so two intervals take 120 min.
- **L5.** INV-X1 repro: a legacy entry with X in exclude ∩ lockout. D2c guards the garage engage, but the garage `_release` would still unlock X, and X could also be in the away-lock list (two owners of one entity sharing `_release_inflight` / `_readback_unsubs` keyed by entity). The validators prevent this from now on. Add one sentence saying the overlap is unsupported and that `lock_exclude_not_subset` plus the overlap check are re-run at regime setup with a WARNING.

## Builder-prediction (what will be built wrong)

1. Moving the `_is_resident` filter in `_on_person_event` (`:753-780`). The early `return` also guards the `old is None` restored stamp and the approach-zone release. Byte-identical for residents means: the `_last_real` update runs for everyone, and the P1 and approach `_release` calls stay resident-gated. The away-lock P1 release is a separate call gated on the away-lock persons list. `test_garage_policy_unaffected` should include a non-resident person event that triggers no garage release.
2. Reusing `_release` / `_on_readback` / `_notify_failure` with a `policy` argument. `_release` bumps `release_gen` and calls `_after_release`, which changes `reason` and re-engage. The away-lock release must not go through `_release`. Use `_spawn_unlock` directly with `policy`. The plan says it "does not touch release_gen"; name the exact entry point.
3. The switch routing. `SecurityLockoutOptionSwitch._write` calls `regime.on_kill_switch_changed(False)` with no key (`switch.py:5240-5245`). Pass `self._conf_key`. With the garage key, the call must be byte-identical (`on_kill_switch_changed` cancels re-engage and backstop and force-releases lockouts).
4. `_record` hard-codes "Garage lockout" (`:1276`) and `snapshot()` keys are `lock_regime_garage_lockout_*`. D3f adds new keys. Leave the existing keys unchanged.

## Knob ladder / acceptance
Every number has a rung (§5). The dwell at rung 1 is justified. No unlisted numbers found. The acceptance tests are discriminating, with the exceptions in H1 (unbuildable test), H2 and M3-M5 (missing tests). D3 Live depends on the operator's next shared outing. That is acceptable as a one-shot disposition with a binary discriminator (the entity state).

## Off-release routing per switch
The garage lockout release must stay byte-identical. Achievable if M4 and builder-prediction items 2 and 3 are written into the plan. Today the plan says "dispatch by conf key" but does not name the `async_release_if_disabled` early-return coupling.

## Must-fix before build
H1, H2, M1-M6. Fix the LOWs in the plan as well (each is one line).

| Severity | Found |
|---|---|
| HIGH | 2 |
| MEDIUM | 6 |
| LOW | 5 |

Bug classes: #53 one-missed-consumer (M1, M2), suppression needs a discharge / restart (H1), lifecycle and untracked timers (M5), shared-primitive coupling (M4, builder items 2-3), persisted-state clobber (M3).
