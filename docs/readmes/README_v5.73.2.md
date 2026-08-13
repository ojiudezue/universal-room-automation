# URA v5.73.2 — Fan-oracle orphan sweep + DP ledger honesty (batch hotfix)

Two Tier-1 fixes, one deploy.

## FAN-LAYER-2 B-LOW-1 — orphan fan-oracle row sweep

`migrate_legacy_entry_keys` gains opt-in `current_room_keys`; `discover_fans` passes the live
room-key set. Unmapped legacy `entry:*` rows and `room:*` rows for rooms that no longer exist are
dropped (with their per-room locks), one INFO summary log. Live rows byte-identical; kwarg omitted
= old preserve-in-place behavior; idempotent. Reality check vs the original finding: the store is
RAM-only, so orphans were session-scoped, not forever — sweep still keeps `debug_snapshot` honest
and the lock dict bounded.

Review: SHIP, 0 CRIT/HIGH. Partial-map false-sweep risk dismissed by trace (HA's config-entry
registry is fully loaded before any setup; `discover_fans` cannot see a partial room map). One
accepted LOW: lock split-brain reachable only for a room being deleted mid-hold (blast radius one
hold window on a room being removed). Wire-in anchor: kwarg deletion reds a named test.

## DP-REASON-NULL-1 — decision_log rows carry the real eval reason

`_log_dp_eval_decision` read `getattr(carrier, "reason", None)` — a field that doesn't exist — so
all 4,181 `dp_eval` ledger rows since ship carried `reason: null` (found by
`AUDIT_dp_live_behavior.md`). Now reads `last_eval_snapshot["decision"]["reason"]`
("l1_only", "already_below_target", …) with a safe None for pre-eval ticks. Orchestrator-verified
one-liner; wire-in drill: reverting to the dead getattr reds the post-eval test.

## Acceptance criteria

- **Test:** `test_fan_layer_2_b_low_1_orphan_sweep.py` (6) + `test_dp_reason_null_1.py` (2), all
  mutation-anchored at their call sites.
- **Live:** loads, zero URA errors post-restart.
- **Live (DP, first off-peak EVSE eval):** newest `decision_log` `dp_eval` row carries a non-null
  reason string.
- **Live (fan oracle):** one INFO sweep summary at HVAC setup (count may be 0 — fine).

## Live Validation

### Validated 2026-08-12 (v5.73.2 boot, 22:08 CT)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Loads, zero URA errors | **PASS** | error_log `universal_room` post-restart: boot-transient WARNINGs only |
| L2 | HACS installed = v5.73.2 | **PASS** | HACS download confirmed v5.73.2; PR #504 diff verified to carry both fixes |
| L3 | dp_eval rows carry real reason | **PASS (immediately)** | decision_log: 03:08:53Z row (first post-restart eval) = `l1_only`; last pre-deploy row (03:02Z) = None. Before/after pair in one table |
| L4 | Fan-oracle sweep INFO at setup | **In-suite** | INFO level not retained in retrievable logs (journald ERROR/WARNING only); sweep behavior mutation-anchored in 6 tests; live orphan count expected 0 |
