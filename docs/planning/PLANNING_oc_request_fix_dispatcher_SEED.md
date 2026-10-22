# SEED — `request_fix` dispatcher for the Optimization Coordinator agent

Status: SEED (not a plan yet). Card: OC-REQUEST-FIX-DISPATCHER-1. Parent: OC-SELF-OPTIMIZING-HOUSE-REDESIGN-1.
Source: VISION_optimization_coordinator_self_fixing_house.md rev 5 §3 ("Unified request API — revisited").

## Origin (operator, 2026-10-21)
- Decision 7: "Agree now. But really think about if we need an API that can cover all Coordinators."
- On my recommendation below: "Lets not lose this. Make this the seed of a plan."

## The idea (verbatim recommendation)
Owning paths for now. Later, a thin `request_fix(type, target, evidence)` dispatcher. It does the shared work
(tier check, sleep gate, action log, check-back) and then calls the owning coordinator's existing path, so it
adds no new way to actuate anything. Build it in slice 2; go further only if 3 or more coordinators need the
same request shape.

## What the plan must answer (open questions)
1. Shape: HA service (`universal_room_automation.request_fix`) vs internal Python API vs both. The agent
   runs outside HA first, so slice 2 needs a service surface.
2. Type registry: P1-P5 + R1 types (§2a, §2 of the vision) as a static table: type → owner path, tier,
   target class, check-back spec. Unknown type = refused.
3. Gates in order: kill switch → tier vs promotion state → house-sleep gate → per-type rate limit → budget.
4. Action-log schema and write path (batched; 2026-06-09 write-flood lesson) and the check-back scheduler
   (restart-safe).
5. Refusal semantics: every refusal logged with reason; never falls through to a raw service call.
6. Trigger for a deeper API: ≥ 3 coordinators sharing a request shape — define "same shape" concretely.

## Prior art to scan before planning (Tier 2+ rule)
- `optimization.py` autonomy ladder, kill switch, denylists (`:4514` reserve hard-deny).
- HVAC `emit_set_*` funnels + arrester `suppress()`; `fan_policy_oracle.py:588`.
- Existing services: `reapply_radar_settings` (`__init__.py:6213`), `fan_recheck_force_restore` (`:6186`),
  `memory_query` (`:6355`).
- `OC-SHADOW-SAMPLES-EMPTY-1` (action log replaces shadow samples).

## Not in scope
A new actuation path into any coordinator's domain. EVSE. Anything R3.
