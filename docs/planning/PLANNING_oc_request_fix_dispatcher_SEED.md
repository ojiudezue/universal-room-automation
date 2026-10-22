# SEED — `request_fix` dispatcher for the Optimization Coordinator agent

Status: SEED (not a plan yet), updated 2026-10-21 for vision rev 6. Card: OC-REQUEST-FIX-DISPATCHER-1. Parent: OC-SELF-OPTIMIZING-HOUSE-REDESIGN-1.
Source: `VISION_optimization_coordinator_self_fixing_house.md` rev 6 §3 and §3c. Reviews answered: `REVIEW_oc_vision_rev5_completeness.md` (H4, L4) and `REVIEW_oc_vision_rev5_thinking.md` (M3).

## Origin (operator, 2026-10-21)
- Decision 7: "Agree now. But really think about if we need an API that can cover all Coordinators."
- On the recommendation below: "Lets not lose this. Make this the seed of a plan."

## The idea (rev 5 recommendation, kept)
Owning paths for now. A thin `request_fix(type, target, evidence)` dispatcher does the shared work (tier check, sleep gate, action log, check-back) and then calls the owning coordinator's existing path, so it adds no new way to actuate anything. Go further only if 3 or more coordinators need the same request shape.

## What changed in rev 6
- **It moves from slice 2 to slice 1** and becomes **the agent's only write path into HA**. The allowlist proxy (vision §3c) exposes R0 reads and `request_fix`, nothing else, so the dispatcher cannot be bypassed. Without that, `request_fix` is advisory.
- In slice 1 it accepts only types `digest` and `page` (the morning summary and one page, via NM `async_notify`, `notification_manager.py:1334`) and refuses everything else with a logged reason. That gives the refusal tests a real target from day one. R1 types arrive in slice 2 (conditional); R2 types are parked.
- **Prior art (REUSE vs BUILD):** the v2 chokepoint `optimization.py:4282` `_apply_action` already runs rung × kill switch × rate cap (`:4043`) × quiet hours (`:4021`) × hard denies (`:4514`) + broker. **REUSE those predicates; BUILD only the front end and the type registry; replace its dispatch legs** (`_dispatch_device_action` `:4552` → raw `async_call` `:4677`; `_dispatch_config_action` `:4707` → raw `:4826`) with owner-path calls. `request_fix` is an extension of the v2 chokepoint, not a replacement. Also read: `PLANNING_OPTIMIZATION_COORDINATOR_v2_agentic.md` (ladder, `SIGNAL_OPTIMIZER_INTENT`, Appendix C D3), `PLANNING_OC_phase5_handshake_and_admin_surface.md`, `CRITIQUE_audit_optimization_coordinator_2026-07-10.md`, `PLANNING_audit_optimization_coordinator.md`.

## What the plan must answer
1. **Shape:** an HA service `universal_room_automation.request_fix` with `SupportsResponse` (as `memory_query` does, `__init__.py:6355`). Response schema: `{accepted: bool, refusal_reason: str|null, action_id: str|null, checkback_due: iso|null, tier: str}`. An internal Python API for the in-HA phase sits behind the same handler.
2. **Type registry:** static table, type → owner path, tier, target class, check-back spec, refusal preconditions (vision §2a "Refuses when"). Unknown type = refused. Slice-1 types: `digest`, `page`. Later: `reload_entry` (R1, vision §2b allowlist + seven D3 conditions), `resync_device` (R1, once defined per integration), P1/P2/P4/P5, `fan_recheck`, `fan_recheck_force_restore`, `ec_hwm_reseed` (R2). Not types, ever: anything on the vision §3 never-grantable list.
3. **Gate order:** kill switch → budget (month-to-date spend sent by the runner on every call; the runner's own check is primary because only it sees spend) → type known → tier vs promotion state → sleep gate (vision §2d predicate, read live) → per-type rate limit → owner-path preconditions. Every refusal is logged with its gate and never falls through to a raw service call.
4. **Idempotency:** a repeated request for the same (type, target) inside that type's check-back window returns the existing `action_id` and does not act again. Key = (type, target, window start).
5. **Action log and check-back:** the agent store (vision §5c, SQLite on the agent host) holds the action log in slices 1-2. In HA the dispatcher writes only the heartbeat (dead-man, vision §5c) and, from slice 2, one row per accepted action, batched through the write queue (2026-06-09 lesson). Check-back scheduling is restart-safe; a check-back missed by `optimizer_agent_checkback_deadline_h` counts as failed.
6. **Deeper API trigger:** ≥ 3 coordinators sharing a request shape, where same shape = the same (verb, target class, check-back type) triple.
7. **Legacy executor coexistence:** with the executor clamped to shadow (vision §7a), confirm no path lets `_apply_action` actuate while `request_fix` exists.

## Acceptance seeds (for the plan to sharpen)
- Every vision §3 never-grantable item sent as a `request_fix` type or target is refused, with the gate named. The test fails before the dispatcher exists.
- A `digest` call lands one NM at the fixed coordinator id and severity and stamps the heartbeat.
- A duplicate request inside its window returns the same `action_id` and makes no second call.

## Not in scope
A new actuation path into any coordinator's domain. EVSE. Anything R3. Climate writes (vision P3 dropped).
