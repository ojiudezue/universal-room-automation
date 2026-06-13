# URA v5.4.1 — Load-Shedding Correctness Fixes

Correctness-only repair of the existing 4-level load-shedding cascade (from the 2026-06-08 audit). NO capability expansion — progressive pool sub-tiers / forecast-coupled shedding remain a separate foundations track. The three audit findings, plus seven more surfaced by the three-framing-disjoint Tier 2-DB review (including two introduced by the cycle's own first-pass fix).

Tier 2-DB: build + 1 fix-up + validator + 3 framing-disjoint reviews + focused confirm. Ledger: `docs/reviews/code-review/load_shedding_correctness.md`. Plan: `docs/planning/PLANNING_load_shedding_correctness.md`.

## What ships

### F1 (CRIT) — EVSE shed↔TOU pause-ownership collision fixed
Load-shed EV + smart-plug tiers moved off the shared `_paused_by_us` set onto a dedicated `_paused_by_load_shed` set per controller (reuses the v5.3.9 `_paused_by_arbitrage` pattern — no shared arbiter). All six EV resume paths + the plug resume paths now defer to `_paused_by_load_shed`, so a sibling owner (TOU, arbitrage, grid-cap, fill-priority, excess-solar) can't turn a shed device back on; shed release defers to every other owner. Durable EV philosophy preserved (`_paused_by_battery_drain` stays in precedence).

### F2 (CRIT×2) — orphan-restore fixed on both the period-flip and restart paths
- **Period flip:** the off-peak / disabled short-circuit now releases all active tiers (`_release_all_active_tiers`) before zeroing the level — previously it stranded every claim, and the new ownership made that orphan *permanent*.
- **Restart:** state persists as a single atomic JSON bundle, now written via `_periodic_db_writes` (write-on-change throttled) — so it survives a **watchdog kill** (this house's dominant restart mode), not just graceful teardown. Restore re-populates state without re-issuing `turn_off` (live state is authority) and sets `_pool._state = REDUCED` so the pool isn't stranded at reduced speed.

### F3 (HIGH) — manual-off-wins
Release turns ON only devices that were ON at shed-time (`was_on_at_shed`, round-tripped through the bundle). A device the operator had manually turned OFF stays off. Re-escalation re-sheds a device the operator manually turned back on mid-shed. (The first-pass build wrote the manual-off infra but never read it — a no-op caught in review.)

## Out of scope (parked — foundations/IP track)
Progressive pool sub-tiers, forecast-coupled proactive shedding, new sheddable domains, release deadband. Hard scope boundary held (review-confirmed clean).

## Live Validation (Review D) — prospective criteria — SAFE-TEST ONLY
Per the audit, the EV shed tier is unsafe to live-toggle; its collision is proven in-suite only. Safe live path = observation mode + a LOW threshold + ONE smart plug:
- [ ] Clean restart; zero URA ERRORs; 40/40 entries; load-shedding switch state intact.
- [ ] **Obs-mode + low threshold + one plug:** drive a sustained import above the threshold → the plug sheds (level 1); condition clears → plug restores. Flip TOU period mid-shed → plug still restores (no orphan).
- [ ] Manually turn the test plug OFF before a shed elsewhere → it stays OFF through release.
- [ ] `load_shedding_active` + the new status/activity-log surfaces reflect the cascade correctly.
- [ ] EV-tier collision, watchdog-restart bundle survival, pool restore — IN-SUITE (mutation-anchored); not live-exercised (EV tier unsafe; no real grid-stress shed).

*Replaced with observed results post-restart per the README write-back rule.*
