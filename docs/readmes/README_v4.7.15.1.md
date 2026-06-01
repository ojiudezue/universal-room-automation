# Universal Room Automation — v4.7.15.1

**Cycle scope:** consolidate v4.7.14.1's H1/H2/H3 trust filters into v4.7.15's shared Pattern A helper. No new operator-facing behavior; runtime semantics are unchanged. Diagnostic surface gains consistency — `last_veto_decision` is now populated by the same code path that drives the authoritative house-state transition.

**Tier:** 2-DB (three parallel reviewers — A correctness, B signal-chain integrity, C test fixture authority).
**Predecessor:** v4.7.15 (D1-D6 shipped).
**Sibling cycle:** v4.7.16 (room-level Pattern F — separate branch, not in scope).
**Bug Class focus:** #48 (transient-vs-reliable arbitration); secondary #44 (test fixture authority).
**Risk premium:** see plan §"CRITICAL RISK PREMIUM" — write-ordering of `_last_veto_decision` and zero-net-behavioral-regression guarantees.

---

## Operator runbook (post-install)

1. Confirm HACS shows `update.universal_room_automation_update.installed_version = "v4.7.15.1"` after install. The matching `latest_version` must also be `v4.7.15.1` (per memory `feedback_verify_hacs_install.md`).
2. Restart Home Assistant.
3. Verify `sensor.ura_presence_coordinator_presence_house_state` exposes ALL four diagnostic attributes and they update each inference tick:
   - `tracked_persons_count` (raw, pre-filter count)
   - `tracked_persons_count_trusted` (post-H2/H3 filter count)
   - `excluded_persons` (name → reason map)
   - `last_veto_decision` (dict with keys: `fired`, `confidence`, `reason`, `scope`)
4. Confirm `sensor.ura_presence_coordinator_house_state_confidence = 0.95` during a confirmed-AWAY window.

---

## Pre-deploy snapshot procedure

Snapshot the count of `last_veto_decision.fired = true` events over a 1-hour window from `sensor.ura_presence_coordinator_presence_house_state` attribute history.

Post-deploy diff must be **±25%** of pre-deploy count.

*Why ±25%:* v4.7.15.1 does NOT change firing semantics; it consolidates HOW they're computed. Authoritative `new_state` is still produced by `_inference_engine.infer()` (which retained the v4.7.14.1 H1 predicate inline). The helper Pattern A's veto decision is a diagnostic mirror. Both paths read the same H1/H2/H3 data, so they MUST agree per cycle. A >25% delta in either direction indicates the consolidation introduced semantic drift — STOP and investigate.

---

## Post-deploy validation procedure

Specific entity IDs + expected values:

1. **Within 10 min of restart:** `sensor.ura_presence_coordinator_presence_house_state.attributes.last_veto_decision` is a dict with keys `fired, confidence, reason, scope`.
2. `last_veto_decision.scope` is one of:
   - `"house_inference"` (most common — written by v4.7.15.1 D1's consolidated call at end of each `_run_inference` cycle, AFTER the WAKING + GUEST exit gates)
   - `"waking_transition"` (when SLEEP→WAKING gate fired this tick)
   - `"guest_exit"` (when GUEST→HOME_* gate fired this tick)
   - `""` (engine returned None / no transition)
3. **Sentinel:** `tracked_persons_count_trusted <= tracked_persons_count` ALWAYS. If `>`, the helper's `trusted_count` derivation is broken — file as CRITICAL.
4. If `excluded_persons` is non-empty, every reason value is one of:
   - `"phone_left_behind=on"` (H2 firing)
   - `"tracking_status=stale"` or `"tracking_status=lost"` or `"tracking_status=unknown"` (H3 firing)
5. **Veto-fired log signature:** when the veto actually fires, exactly one INFO line matches:
   ```
   v4.7.14.1: Person-tracker veto fired — N trustworthy persons confirmed away (...), M excluded (...), no unidentified people, census_count=0; forcing AWAY (was X, any_zone_occupied=Y, confidence=0.95)
   ```
   If this log fires WITHOUT `last_veto_decision.fired = true` showing on the sensor within 1-2 ticks, the consolidated helper is out of sync with the inline path — CRITICAL.

---

## Rollback procedure

1. In HACS: select Universal Room Automation → "Three dots" → "Redownload" → version `v4.7.15`.
2. Restart Home Assistant.
3. Verify `update.universal_room_automation_update.installed_version = "v4.7.15"`.
4. Confirm `sensor.ura_presence_coordinator_presence_house_state` still publishes `last_veto_decision`. **Note:** v4.7.15 also writes this surface (its fix-up A1-M1 added the parallel diagnostic path). Rollback does NOT lose the surface — it just reverts to the pre-consolidation behaviour where the helper saw a stale signal set (no H1/H2/H3 plumbing).
5. v4.7.15's pre-D1 inline veto path inside `_inference_engine.infer()` (with v4.7.14.1's H1 predicate baked in there) remains authoritative for `new_state` regardless of rollback — operator-visible AWAY transitions are unaffected.

---

## Live validation checklist (Reviewer D — post-restart)

PASS criteria:

- [ ] Zero new ERROR log entries referencing `presence.py` or `should_veto_due_to_reliable_signals` in `ha_get_logs(source="system_service", slug="core")` for 15 minutes post-restart.
- [ ] All four `TestSiblingCyclePreservation` tests pass against the deployed binary if the operator runs the test suite locally: `PYTHONPATH=quality python3 -m pytest quality/tests/test_v4715_universalize_veto.py::TestSiblingCyclePreservation -v`.
- [ ] Operator's known forgotten-phone scenario (Gap B from v4.7.14.1): when the operator's phone is at home but the operator is at work, `sensor.ura_presence_coordinator_presence_house_state.attributes.excluded_persons` contains the operator's name with reason `"phone_left_behind=on"` AND `tracked_persons_count_trusted` = `tracked_persons_count - 1`.
- [ ] Helper-vs-engine agreement: when `last_veto_decision.fired = true` with `scope=house_inference`, the same tick produced an AWAY transition (visible in activity log).
- [ ] `last_veto_decision` is written every cycle (timestamp on the sensor attribute updates each `_run_inference` tick).

---

## Known limitations

1. **Test mirror functions renamed but preserved.** The v4.7.14.1 in-test `_phone_trustworthy` / `_tracking_active` mirror functions are now back-compat shims that delegate to v4.7.15.1's INPUT BUILDERS (`_phone_trust_input` / `_tracking_active_input`). Tests now drive the production helper via `_compute_via_production_helper`. A reviewer expecting to find the OLD veto-math mirrors should re-read the test file — the math now lives in `presence.py::should_veto_due_to_reliable_signals` (Pattern A) and tests assert against its output.
2. **Pattern F is unchanged.** The unknown-scope fall-through at `presence.py:844-857` still returns `fired=False` for `scope="room_level_weighted"`. v4.7.16 owns Pattern F as a separate cycle.
3. **Write-ordering of `_last_veto_decision`.** The consolidated `house_inference` helper call now runs AFTER the WAKING and GUEST exit gates, becoming the authoritative LAST writer per cycle. Tick-internal `_last_veto_decision` snapshots will therefore always end with `scope = house_inference` (unless an exception was caught in the diagnostic-only `try`). Operators expecting `scope = waking_transition` or `scope = guest_exit` as the visible attribute will only see those for sub-tick transients via the sensor history — the steady-state read is always the house-inference scope.
4. **Backward compat for callers without per-person trust.** Pattern A falls back to `state_context["tracked_count"]` when the H2/H3 signal lists are empty. The v4.7.15 zone aggregator scope (Patterns B + C) does not pass per-person trust signals — preserved as-is. Only the v4.7.15.1 D1 consolidated `house_inference` call site populates the parallel lists.

---

## Cross-cycle reference

- **Predecessor:** v4.7.15 (D1-D6 shipped — VetoDecision dataclass, Pattern A/B/C/D/E, signal_consensus sensor, HVAC defer gates).
- **Sibling:** v4.7.16 (room-level Pattern F — separate cycle, intentionally not consolidated here).
- **Bug Class:** #48 (transient-vs-reliable arbitration); secondary #44 (test fixture authority drive-production rule).
- **Reviewer C of v4.7.14.1 §C4** (load-bearing instruction set for this cycle): `docs/reviews/code-review/v4.7.14.1_review_C_test_authority_merge_risk.md` lines 340-489.
- **Master sprint link doc:** `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md`.

---

## Deploy gate (per CLAUDE.md "Pre-Deploy Zero-Bugs Gate")

Six gates run before `./scripts/deploy.sh`:

1. Grep for merge-conflict markers in `custom_components/`, `quality/`, and v4.7.15.1 docs — zero matches.
2. `python3 -m py_compile` every changed `.py` file — all exit 0.
3. Cycle tests + sibling suites all green.
4. Suite-baseline-diff against `pre-review-v4.7.15.1` shows only planned changes.
5. Full pytest suite — net new failures = 0 (pre-existing unrelated failures in `test_activity_logger.py`, `test_data_pipeline.py`, etc. are baseline and tracked separately).
6. Three Tier 2-DB reviews complete with CRITICAL/HIGH all addressed.
