# CRITIQUE — appliance management (v3 plan) + practical opportunity map (APPLIANCE-MGMT-REFINE-1)

**Date:** 2026-09-12 · **Card:** APPLIANCE-MGMT-REFINE-1 · **Status:** critique (pre-plan)
**Plan under review:** `docs/planning/PLANNING_v4.7.x_APPLIANCE_COORDINATOR_v3.md` (B5 in BACKLOG).

Planning basis for APPLIANCE-MGMT-REFINE-1. Read-only ground-truth gathered from the plan lineage,
the code (0 appliance files exist — confirmed), AND the **live HA device surface**.

## Faithful summary of the v3 plan
A new `ApplianceCoordinator` (+ `ApplianceProvider` ABC, `LGThinQProvider`/`RainbirdProvider`) that
(1) **defers** flexible LG appliance starts into the cheapest TOU window, (2) **interrupts** a manual
peak start when `interruptible_at_start` and re-schedules it (EV-charging precedent), (3) **skips**
Rainbird cycles when rain is forecast. Carries a persisted `INTERRUPTED` state machine (new
`appliance_state_machine` table + 4 DAOs), 2 new frozen-shape signals, a multi-vector
`PowerSignalAggregator`, a 14-sensor observability slate bound to the PWA. 12 deliverables, ~36-46h,
self-classified Tier 2-DB. **v3 is a thin re-skin of v2** (D1-D12 carried verbatim); the only real v3
deltas are the PWA dashboard target + EC rate-API rewiring.

## Live device ground-truth (richer than the plan assumed — re-ground against these)
- **LG laundry/dish (real, control-capable):** `washer`, `washer1`, `washtower_one`, `washtower_two`,
  `dishwasher_kitchen`, `dishwasher_washroom`. Control surface that maps directly onto the plan's ABC:
  **`number.*_delayed_start`** (write a delay — currently 0), **`select.*_operation`** (start/stop/
  cancel), **`sensor.*_remaining_time`** (cycle length), `sensor.*_current_status`,
  `binary_sensor.*_remote_start`, `event.*_notification`. **Plan Open-Q#1 (service names) is answerable
  now: control is entity writes (`number`/`select`), not bespoke `thinq.*` services** — and the
  provider must resolve by entity, not a `thinq_` name prefix (the appliances surface under friendly
  names).
- **Rainbird (real, but NOT as the plan assumes):** `switch.rain_bird_sprinkler_1..22` — **22 per-zone
  on/off switches, no confirmed `set_rain_delay` entity/service.** The plan's D7 assumes
  `set_rain_delay(n)`; that premise is unverified and may not exist.
- **SPAN:** `switch.span_panel_dryer_breaker` + dryer power/energy — breaker-level awareness (not LG
  control).

## Critique
1. **16 months stale, never built.** Dated 2026-05-23, targets **v4.7.x**; the repo is **v5.100.x**.
   Its whole dependency frame (v4.6.7/4.6.8 "just shipped," PWA v6.0 as *future*) is ~40+ versions old;
   the PWA is now live (v6.1.0). Every cited file:line (`energy.py:3552`, `energy_tou.py:194`, …) must
   be re-verified — 16 months of energy cycles have drifted them.
2. **The big marginal-benefit split the plan misses: DEFER is the cheap, high-value, low-risk win;
   INTERRUPT-at-start is the risky ingredient — and the plan bundles both into v4.7.0.** Deferral of a
   *queued/scheduled* start captures most of the TOU savings, and the LG devices **natively expose
   `number.*_delayed_start`** — so deferral may be achievable by *writing a delay value*, with **none**
   of the v3 state machine, new DB table, `INTERRUPTED` signals, or "materially started" power
   heuristic. Interrupt-a-human's-manual-start adds a synthetic persisted SM, 2 frozen-shape signals, an
   undefined "materially started >200W/60s" heuristic, and — by the plan's own Risk Register — two
   HIGH-rated UX hazards ("device suddenly stops", "false-positive interrupt during ramp-up"). Per the
   CLAUDE.md Marginal-Benefit doctrine: **ship deferral first (tiny), park interrupt behind evidence.**
3. **Tier is probably understated.** Interrupt-at-start threads the interrupt decision through a state
   machine + multiple emission sites and is cost-AND-UX-impacting with HIGH user-surprise — that is the
   **Tier 3** signature (one-missed-site / delicate), not the self-assigned Tier 2-DB. The doc predates
   the Tier 3 protocol (2026-06-16), so it never got that scrutiny. Deferral-only, by contrast, is a
   clean Tier 2 (or even Tier 1 if it's just a guarded delay-start write).
4. **Rainbird D7/D8 is the weakest-grounded deliverable AND the lowest marginal benefit.** Premise
   (`set_rain_delay`) unverified; live surface is 22 switches (skip would have to be switch-suppression,
   a different design). And weather-based irrigation skip is a **commodity** — Rain Bird's own app and
   stock HA blueprints already do it. Marginal-benefit scrutiny says: verify the service first, and if
   it's not there, **DROP/park** rather than build a bespoke switch-suppression skip for a solved
   problem.
5. **Cross-repo PWA contract (D10)** — the 14-sensor "published contract" against the PWA's
   `useUraSensor.ts` is in a separate repo that has since evolved (v6.1.0); re-verify before treating it
   as authoritative. D10 is also the single largest deliverable — not first-cycle material.
6. **Device inventory must be re-enumerated** against the live entities above (washtowers ≠ washers,
   two dishwashers, oven excluded, SPAN dryer) rather than the plan's assumed "6 LG appliances."

## Practical home-automation opportunity areas (ranked, grounded in real devices)
| # | Opportunity | Value | Effort/risk | Verdict |
|---|---|---|---|---|
| 1 | **TOU delay-start for LG washers + dishwashers** — when a cycle is queued/remote-start-ready, write `number.*_delayed_start` to land it in the cheapest off-peak window (respect a must-finish-by). | **High $ + convenience** | **Low** — native entity write; likely NO SM/DB/interrupt | **BUILD FIRST (simplest-first)** |
| 2 | **Cycle-complete / appliance-done notifications** via `event.*_notification` + `remaining_time` → NM. | Med (quality-of-life) | Low | BUILD (cheap, additive) — or fold as a bonus of #1 |
| 3 | **"Clean by morning" dishwasher** — defer overnight to the cheapest pre-wake window. | Med-High | Low (same mechanism as #1) | BUILD with #1 |
| 4 | **Peak co-run avoidance / load awareness** — don't start a 2nd high-draw appliance during peak / near a grid-cap (ties to EC + SPAN dryer breaker). | Med | Med (cross-coordinator) | PARK — revisit after #1, ties to EC |
| 5 | **Interrupt a manual peak start + reschedule** (the v3 centerpiece). | Med (marginal over #1) | **High** — SM + DB + signals + "materially started" heuristic + HIGH UX-surprise | **PARK behind evidence** (Tier 3; build only if #1 data shows manual peak starts are frequent + costly) |
| 6 | **Rainbird rain-skip** | Low-Med (commodity; Rainbird app does it) | Med + **premise unverified** (22 switches, no rain-delay) | **VERIFY then likely DROP/park** |

## Recommendation (marginal-benefit decomposition)
**Ship the simplest version first: TOU delay-start for the LG washers + dishwashers (opportunity #1,
+ #2/#3 as cheap riders).** It captures the large share of the benefit, uses the devices' native
`number.*_delayed_start` / `select.*_operation` / `remaining_time` surface, and plausibly needs **no
state machine, no new DB table, no interrupt path, no new frozen signals** — a fraction of the v3
plan's 36-46h and risk, and a clean Tier 2 (possibly Tier 1). **Park the interrupt-at-start (Tier 3,
HIGH UX risk) behind measured evidence** that manual peak starts are frequent and costly. **Verify the
Rainbird service before committing**; if `set_rain_delay` doesn't exist, drop it (commodity).

### Next
Operator picks the first-cycle scope. Recommended: a fresh, lean **APPLIANCE-DEFERRAL** plan (not a v3
revival) scoped to opportunity #1 — with a measure-first probe (how often are washer/dishwasher cycles
started during peak today? via `sensor.*_current_status` history) to size the win and to gate whether
#5 is ever worth it. Re-verify all device entities + the delay-start write path against live HA before
build (the v3 plan's 16-month-stale refs are not trustworthy).
