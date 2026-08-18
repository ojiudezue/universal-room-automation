# AUDIT — Roadmap Undone-but-Worthwhile Reconciliation

**Card:** ROADMAP-UNDONE-REVIEW-1
**Date:** 2026-08-18
**Type:** READ-ONLY reconciliation (no code, no plan)
**Live version:** v5.80.0 · **Roadmap doc pins:** v3.22.0 ("Next: Bayesian v4.0.0")

## Why this exists

`docs/ROADMAP_v11.md` (last touched 2026-03-30 at v3.22.0), `docs/VISION_v7.md`
(v3.2.9), and `docs/ROADMAP_REMAINING.md` (v3.9.5) all predate ~2 years and
~55 shipped releases. The roadmap's "FUTURE" section describes work that has in
large part **already shipped under different names**. This audit reconciles the
roadmap/vision against what actually shipped (READMEs v5.x, git log, code greps,
MEMORY.md) and separates genuinely-valuable undone work from
superseded/obsolete items.

Sibling card: `ROADMAP-STALE-AGENTIC-LAYER-1` (inbox) tracks re-writing the
roadmap doc itself + the unplanned room-to-room agentic layer. This audit is the
evidence base for that rewrite.

## Method / evidence

- Read: ROADMAP_v11 / v10 / v9 / REMAINING, VISION_v7, kanban.data.yaml (all
  cards), MEMORY.md index + relevant project bodies.
- Code greps against `custom_components/universal_room_automation/`:
  - `appliance_coordinator`→0, `thinq|rainbird|dishwasher`→0 files
  - `subentr`→0 files, `runtime_data`→1 file, `hass.data[DOMAIN]`→189 sites
  - `EntityDescription`→0 files, `async_on_unload`→2 sites
  - `optimization.py`+`optimization_llm.py` present, `weather_manager.py` present,
    `OverrideEngine`→5 files, `arbitrage_savings`→3 files, `chatter`→0 files,
    floorplan/heatmap only in a bundled dashboard asset (not core).

---

## Classification table

| Roadmap / Vision item | Verdict | Evidence / by what |
|---|---|---|
| **v4.3.0 Grid Arbitrage Hardening** (D1 reserve fix, D2 live sliders, D3 reconciliation, D4 ROI sensor, D5 threshold diag) | **SUPERSEDED (shipped)** | Shipped across v5.5.x: WAIT/inclement floor, import-guard expose (v5.5.6), attain ladder, `arbitrage_savings` sensor (D4) present, `arbitrage_charge_lead_time` live knob (D2). See MEMORY "guest expose shipped", "inclement WAIT floor". |
| **v4.0.0 Bayesian — B1/B2 core + prediction sensors** | **SUPERSEDED (partial ship)** | 5 Bayesian sensors resurrected v4.0.2 (roadmap tech-debt #0); `Bayesian` in 20 files, `pattern_learning` present. |
| **v4.0.0 Bayesian — B3 pre-emptive actions / room-to-room prediction** | **WORTHWHILE — CARDED** | The predictive/agentic pre-emption layer is NOT built. Tracked by `ROADMAP-STALE-AGENTIC-LAYER-1` (inbox, room-to-room agentic layer). |
| **v4.7.x Guest Mode Actuation Phase 1** (OverrideEngine, preset-range overrides) | **SUPERSEDED (shipped)** | `OverrideEngine`→5 files; GUEST latch v5.16.0 (MEMORY "guest latch"). |
| **v4.7.x Dynamic Preset Management** (WeatherProviderManager + weather-driven overrides) | **SUPERSEDED (shipped)** | `weather_manager.py` present (v4.7.0); DP durable ledger live (kanban DP-REASON-NULL-1). |
| **Vision backlog: Weather Integration** (pre-cool, blinds, solar-forecast HVAC) | **SUPERSEDED (shipped)** | WeatherProviderManager + inclement-weather hold v5.5.0 + HVAC cover solar-gain (v3.8). |
| **Optimization Coordinator** (implied "next coordinator", tech-debt #3) | **SUPERSEDED / CARDED** | `optimization.py`+`optimization_llm.py` shipped at L1 shadow; autonomy promotion tracked by the optimizer-autonomy campaign (skill + v5.0.0–v5.2.1 rollback history). |
| **Appliance Coordinator v3** (LG ThinQ washer/dishwasher cost-deferral, interrupt-at-start, Rainbird sprinkler skip) | **WORTHWHILE — UNCARDED** | `appliance_coordinator`/`thinq`/`rainbird`→0 files. NOT built, no card. The deferrable-load cost-shift is genuinely undone and distinct from the load-shed cascade (which sheds, doesn't time-shift). |
| **Sensor Health Surfacing** (chattering detector, `sensor_health` table, `ura_unhealthy_sensors`, NM "replace this sensor" hook) | **WORTHWHILE — UNCARDED (partial)** | `chatter`→0 files. Stuck-on watchdog + corroboration-gated exclusion shipped (STUCK-SENSOR-1), but the operator-facing "which physical unit to swap" surface is NOT built. Live gap proven by `INCIDENT_chatter_class_missed_by_watchdog_2026-08-09`. |
| **Tech-debt #1 Setup/unload symmetry** (services/panels never torn down; `async_on_unload` for every listener/timer) | **WORTHWHILE — UNCARDED** | `async_on_unload`→2 sites only. Reload-safety class (same family as v4.2.24 silent-save + parent-reload watchdog hazard). |
| **Tech-debt #2 Tracked background tasks** (untracked `async_create_task`) | **WORTHWHILE — UNCARDED** | Matches known bug class "Untracked Background Tasks". Correctness-relevant. |
| **Tech-debt #3 EntityDescription rollout** | **WORTHWHILE (LOW) — UNCARDED** | `EntityDescription`→0 files. Pure code-shrink hygiene; fold into next coordinator/refactor. |
| **Tech-debt #4 runtime_data migration** | **WORTHWHILE (LOW) — UNCARDED** | `runtime_data`→1 file, `hass.data[DOMAIN]`→189 sites. Typing hygiene; do during next major refactor, not standalone. |
| **v5.0 Config Subentries Migration** | **WORTHWHILE (MEDIUM, risky) — UNCARDED** | `subentr`→0 files; still flat 34-entry topology. Fixes orphan-device residue + per-entry migration drift + setup/unload ownership. Benefit is largely cosmetic; migration of live entries carries real downside. Recommend park-with-trigger, not schedule. |
| **Vision backlog: Vacation Mode Detection** | **WORTHWHILE — CARDED (folds in)** | Under-consumed AWAY house state; covered by `HOUSE-STATE-UTILIZATION-EPIC` (parked). |
| **Vision backlog: Time Period Profiles** | **SUPERSEDED / CARDED** | Largely covered by the 9-state house-state machine + sleep-hours; residual meaning tracked by HOUSE-STATE-UTILIZATION-EPIC. |
| **Vision backlog: Guest Mode** | **SUPERSEDED (shipped)** | Guest detection + latch + veto shipped (v5.16.0); guest-room designation cards active. |
| **v4.5.0 Visual 2D Mapping** (floor plan, person positions, heatmaps) | **OBSOLETE / SUPERSEDED** | Dashboard direction moved to external PWA v6 (`~/Code/ura-dashboard-pwa`, live). In-integration floor-plan feature not built and LOW value; no core code. Do not re-card. |
| **Dashboard Iteration** (in-repo `dashboard/` v1 + `dashboard-v3/`) | **OBSOLETE / SUPERSEDED** | Superseded by external PWA v6 + `/ura-v6`/v8 HA dashboards (MEMORY "PWA v6 shipped"). |
| **Comfort Coordinator** (standalone) | **OBSOLETE (already cut)** | Absorbed into HVAC v3.18.4; circadian + per-person temp permanently cut. Documented in roadmap. |
| **Circadian lighting / Per-person temp / Portable device control** | **OBSOLETE (permanently cut)** | Roadmap "Permanently Cut" section. |
| **BlueBubbles webhook registration / Envoy replacement** (operational items) | **DONE** | iMessage images arriving + operator-confirmed (NM-BB-IMAGE-1); Envoy self-healed (MEMORY). |
| **ROADMAP/VISION/REMAINING doc currency** (tech-debt pre-existing #6) | **OBSOLETE (this audit + rewrite)** | Superseded by ROADMAP-STALE-AGENTIC-LAYER-1 rewrite; mark v9/v10/v11 + VISION_v7 + REMAINING as historical. |

---

## WORTHWHILE items — value + tier + card status

| Item | One-line value | Rough tier | Card |
|---|---|---|---|
| Room-to-room agentic / pre-emptive prediction (Bayesian B3) | Proactively prep rooms (light/HVAC) on high-confidence occupancy prediction — the roadmap "capstone" | Tier 2-DB+ | **CARDED** ROADMAP-STALE-AGENTIC-LAYER-1 |
| Sensor Health Surfacing (chatter + stuck-on operator surface) | Tell the operator which physical sensor to swap before it silently poisons occupancy/energy | Tier 2 | **UNCARDED** |
| Appliance cost-deferral (LG ThinQ + Rainbird skip) | Time-shift deferrable appliance starts to cheap TOU windows → recurring $ | Tier 2-DB | **UNCARDED** |
| Setup/unload symmetry (#1) + tracked background tasks (#2) | Reload-safety + task-leak correctness; same family as prior live incidents | Tier 2 | **UNCARDED** |
| Config Subentries Migration | Kills orphan-device residue + per-entry migration drift; HA-native lifecycle | Tier 2 (risky) | **UNCARDED** (recommend park-with-trigger) |
| EntityDescription (#3) + runtime_data (#4) hygiene | Code-shrink + edit-time typing; fold into next refactor | Tier 1–2 | **UNCARDED** (opportunistic) |
| Vacation Mode / house-state utilization | Give operational meaning to under-consumed AWAY/HOME_DAY states | Tier 2 | **CARDED** HOUSE-STATE-UTILIZATION-EPIC (parked) |

---

## TOP UNCARDED worthwhile items (for the orchestrator to card)

1. **Sensor Health Surfacing** — chattering detector + `sensor.ura_unhealthy_sensors`
   + `sensor_health` table + NM "consider replacing this sensor" hook. *Live incident
   already exists* (chatter class missed by watchdog, 2026-08-09); cheapest high-value
   gap. Tier 2.
2. **Appliance cost-deferral coordinator** — LG ThinQ washer/dishwasher start-deferral
   + interrupt-at-start + Rainbird sprinkler skip. Genuine recurring $; large (~30-40h),
   so **run a marginal-benefit decomposition first** (what does the simplest single-appliance
   deferral capture vs the full provider-plugin framework). Tier 2-DB.
3. **Setup/unload symmetry + tracked background tasks** (tech-debt #1 + #2) — reload-safety
   and task-leak correctness; `async_on_unload` used in only 2 sites today. Matches known
   bug classes; pairs naturally into one hardening cycle. Tier 2.
4. **Config Subentries Migration** — card as **parked-with-trigger** (revisit when orphan-device
   residue or per-entry migration drift actually bites), not scheduled. MEDIUM value, real
   migration risk.
5. **EntityDescription + runtime_data hygiene** (#3 + #4) — opportunistic; attach to whichever
   coordinator gets touched next rather than a standalone cycle.

## Housekeeping recommendation

Mark `ROADMAP_v9/v10/v11.md`, `VISION_v7.md`, `ROADMAP_REMAINING.md` as **HISTORICAL**
and let ROADMAP-STALE-AGENTIC-LAYER-1 produce the replacement, using this audit's
classification table as its "already shipped / superseded" ledger so the rewrite
doesn't re-list done work.
</content>
</invoke>
