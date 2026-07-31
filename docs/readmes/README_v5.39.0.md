# URA v5.39.0 — House-State Rung 2a: security auto-follow (SHIPS OFF)

State-driven arming per `PLANNING_house_state_utilization.md` rung 2a. **Flag
(`CONF_SECURITY_AUTO_FOLLOW`) remains OFF** — enabling live is an explicit operator
checkpoint; zero behavior change until then.

## Policy (review-hardened defaults, ratify at enable)
- Map restricted to the plan's table: away→ARMED_AWAY, vacation→ARMED_VACATION,
  guest→ARMED_HOME, arriving/waking→DISARMED. home/sleep = no-op (rung 2b decides).
  Side effect: post-boot HOME_* transitions no-op (no deploy-time arming noise).
- **Manual actions win** for the remainder of that house-state (source-tagged
  arm/disarm; auto-follow re-enables on the next distinct state).
- **Disarm immediate; arm debounced 30s** (SECURITY_AUTO_FOLLOW_ARM_DELAY_S, rung 1)
  — de-escalation is time-critical, escalation is flap-guarded.
- **Severity by direction:** escalation HIGH (instant push), de-escalation MEDIUM.
- Fire-time gate re-checks: shutting-down / disabled / auto-follow-off / observation
  mode — each recorded with its reason; observation mode = visible intent, zero
  actuation. All through the coordinator's public arm/disarm path (no bypass).

## Observability (plan INV-1/INV-3)
- `sensor.ura_coordinator_manager_house_policy` (CM device): active policies +
  last state-driven action (state bounded <255; push-driven, no polling).
- `state_driven_arming_last` attr on the security armed-state sensor (incl.
  suppressed reasons + failure records, all dispatch-refreshed).

## Review provenance
Tier 2-DB: three framing-disjoint reviews — A: 3 HIGH (map scope-creep beyond plan,
missing fire-time gates, no manual-override hold); B: private NM reach + boot-arm
adjudication (resolved by the map restriction); C: #62 cleared via 3 real source
mutations. All fixed; orchestrator re-verified with a fire-path gate mutation
(first attempt hit the wrong occurrence — corrected, FAIL confirmed, restored).
20 targeted tests; zero new suite failures.

## Live Validation
- H1: clean boot (verified by boot signature); flag OFF → no arming activity on
  house-state changes; house_policy sensor live reading "idle"/no auto_follow.
- H2 (at operator enable): away transition → HIGH NM + ARMED_AWAY after 30s;
  arriving → immediate disarm + MEDIUM NM; manual disarm holds until next state.

### Validated 2026-07-30 (~22:12 CDT)
| # | Result | Evidence |
|---|---|---|
| H1 | **PASS** | Fresh boot (restart confirmed by warmup window); `sensor.ura_coordinator_manager_house_policy` registered on the CM device; flag OFF → zero arming activity; no rung-2a errors. |
| H2 | pending-operator | Fires at enable-checkpoint (away→HIGH+ARMED_AWAY/30s; arriving→immediate disarm; manual-hold). |
