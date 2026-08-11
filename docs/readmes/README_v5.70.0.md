# URA v5.70.0 — FanPolicyOracle: fan actuation gets one brain (FAN-LAYER-1)

**Tier 2-DB** — the fan-abstraction layer the FAN-MANUAL cycle proved we needed ("Do we have a
fan abstraction in our roadmap? This is why."). Three staged build sessions + three
framing-disjoint reviews (A SHIP-w/2-HIGH, B DO-NOT-SHIP, C DO-NOT-SHIP w/ 3 hollow anchors)
+ one consolidated 16-finding fix-up, orchestrator re-drilled.

## What ships

- **`fan_policy_oracle.py`**: `FanPolicyOracle` — per-room fan-policy ledger with
  `may_turn_on`/`may_turn_off` verdicts (ALLOW/DEFER/VETO), frozen `FanDecisionSnapshot`,
  per-room `asyncio.Lock` via `oracle.actuate()`, edges-only actuation ledger, closed
  `FAN_TRIGGER_*` enum. Exception posture: OFF-errors → ALLOW (never block a stop),
  ON-errors → VETO.
- **State in ONE place**: room-tier `_fan_manual_off_until`/`_fan_manual_on_until` delegate to
  the oracle (class-level properties, local-dict fallback). Post-review hardening: ledger keyed
  by **config entry_id** (not friendly name — collision-proof), **hydration** of pre-oracle
  writes on first read (no boot-race hold loss), **CM-reload reuse** of the existing oracle
  (holds survive reloads — a strict-regression fix).
- **W11 safety-stop + W12 pre-arrival ON** route through `oracle.actuate()`: safety ALWAYS
  allows OFF (drilled: manual-ON hold active → fan still stops), one bad room can't abort
  safety for siblings; pre-arrival defers under manual-OFF cooldown with the reason in
  diagnostics.
- **Real behavioral anchors** (hollow-anchor purge): the three source-presence tests C caught
  are deleted, replaced by tests driving the real `_stop_all_fans_safety` / `_activate_zone_fans`
  with service-call recorders. C's semantic neuters (MUT-STOP, MUT3-4, MUT3-6) all red now.
- **Suite health**: the two long-standing collection ERRORs fixed — the v5.68.0 vacancy-sweep
  parity anchor now actually executes (it had never run in the merged suite). Adjacency audit
  un-vacuoused (verifies the emit lives INSIDE the actuate wrap).
- **Deferred to FAN-LAYER-2** (carded): RoomFanState HVAC-tier delegation (W4-W6, ~34 sites),
  actuate wraps on W1-W3/W8-W10, reverse adjacency scan.

## Acceptance criteria

- **Live:** loads, zero URA errors; fan behavior byte-equivalent (delegation is transparent).
- **Live (holds preserved):** manual fan holds/cooldowns behave as v5.68.0 (organic: Living
  Room manual-ON test still open from v5.68.0).
- **Live (safety):** no safety-stop regressions (organic — next hazard event; drilled in-suite).
- **Live (no flap):** currently-ON fans hold steady post-restart.

## Live Validation

_(prospective — to be replaced post-restart)_
