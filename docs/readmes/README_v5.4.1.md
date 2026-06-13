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

## Live Validation — Validated 2026-06-13 (restart 14:44 CDT)

The EV shed tier is unsafe to live-toggle and load-shedding is `off` in this install's config, so the cascade's runtime behavior is in-suite validated; the deploy itself is health-validated live.

| Criterion | Result | Evidence |
|---|---|---|
| Clean restart, zero URA ERRORs, 40/40 entries | PASS | 40/40 loaded; zero URA ERROR lines (only benign WARNINGs: person-sensor polling fallback, operator-intentional messaging suppression, the unregistered "Outside" zone). Envoy decoupling held again ("deferred re-validation… still degraded… runtime continues, no repair issue") |
| Load-shedding switch state intact | PASS | `switch.ura_energy_coordinator_load_shedding` = `off` (its configured state; `energy_load_shedding_enabled: false` in CM options) — restore didn't corrupt it |
| F1 EVSE shed↔TOU collision; F2 orphan-restore (period-flip + watchdog); F3 manual-off-wins | IN-SUITE | Mutation-anchored (6 fix-up mutations + 5 build mutations, all kill named tests); cross-owner precedence proven via real `determine_actions` calls. Not live-exercised — EV tier unsafe to toggle and shedding disabled in config |
| Safe live path (obs-mode + low threshold + 1 plug) | DEFERRED | Available when the operator wants a live shed/restore demo on a single plug (NOT the EV tier); no grid-stress shed performed |

*Cascade runtime behavior is in-suite-authoritative; deploy is live-healthy. Re-validate the obs-mode single-plug shed/restore if/when a live demo is wanted.*
