# URA Plan Inventory + Scoring — 2026-05-19

User ask: "I am trying to read/score and prioritize our plans. They are piling up."

This inventory groups every planning artifact by **status**, **scope**, **effort**, **dependencies**, and a **suggested priority score (1–5; 5 = ship next)**. Use it as a triage worksheet — mark or strike items as you decide.

The two docs you specifically asked for are surfaced at the top.

---

## Docs you asked about

### 1. Guest Mode Actuation — preset range adjustments under guest mode
- **Where:** Memory `project_guest_mode_actuation.md` + line in `docs/BACKLOG.md` "Guest Mode Actuation"
- **Status:** Design cycle FILED, not built. Detection ships (v4.6.2.2 hardened false-positives); actuation has zero callers.
- **Your concrete ask (2026-05-15):** Back Hallway `home` preset narrows from 70–77 → 70–75 when guest mode active. `sleep` unchanged (70–78). `away` always 65–80. **Generalize across zones + presets so it can be tuned.**
- **Framework:** per-coordinator `guest_mode_overrides` config schema. HVAC opts in with per-(zone, preset) range overrides. Other coordinators opt in incrementally.
- **Effort:** Phase 1 (HVAC-only, validates framework) ~10–14h, Tier 2. Phases 2 (other coords) + 3 (observability) follow incrementally.
- **Composability gotcha:** overlaps schema-wise with Dynamic Preset Management below — design the per-zone/per-preset override structure to compose with weather-driven overrides, not conflict.
- **Score:** **4** — concrete user ask, modest effort, validates a framework reused by Dynamic Preset.

### 2. Dynamic Preset Management — weather-forecast-driven daily preset adjustment
- **Where:** Memory `project_dynamic_preset_management.md`
- **Status:** Future candidate. Hard-dep on multi-provider weather forecast redundancy.
- **Idea:** Each morning, evaluate forecast + adjust each zone's `home`/`sleep` preset range to a per-zone, per-condition table. Buckets (cool/mild/hot/extreme), not continuous.
- **User policy:** Always use ranges, never absolute temps. Don't ask user to "fart around" with temps day-to-day.
- **Effort:** **Two cycles** — Weather Redundancy first (~12–16h), then preset adjustment (~10–14h). Total 22–30h.
- **Composability gotcha:** Share per-zone/per-preset override schema with Guest Mode (above). Sequence: ship Guest Mode Phase 1 → ship Weather Redundancy → ship Dynamic Preset.
- **Score:** **3** — high value but needs Weather Redundancy first and Guest Mode framework probably first.

---

## In flight RIGHT NOW

| Cycle | Status | Notes |
|---|---|---|
| v4.6.11 | Shipped to GitHub; **awaiting HACS install + restart + live-validation** on your end | `scripts/post_restart_validation.py v4.6.11` to verify after restart |
| v4.6.12 | Shipped to GitHub; **awaiting HACS install + restart + live-validation** | Same script: `v4.6.12` |
| v4.6.13 | Build paused — was the third dashboard-prep Python cycle (coordinator telemetry sensors). Builder agent has been timing out on read phase. **Can be resumed any time** OR you can pre-empt with one of the items below. |

---

## Pending / Queued plans

### A. Dashboard-related (the v5.0 push)

| Item | Status | Effort | Dep | Priority hint |
|---|---|---|---|---|
| **v4.6.13 Coordinator Telemetry sensors** (Cycle C — `decisions_today`, override frequency via compliance_log.override_detected, success_rate via get_compliance_rate DAO) | Plan ready, build paused mid-session | ~6–8h | None blocking | **5** if you want dashboard data complete; **2** if dashboard polish is more urgent |
| **Dashboard v5.0 D3-D7 live wiring** + D8 polish | Plan ready (`PLANNING_v5.x_dashboard_v4_react_port.md`); shell shipped, tabs are dangerouslySetInnerHTML stubs | ~3–4 weeks | v4.6.13 sensors land first | **4** — closes the dashboard loop |
| **v5.0.x performance polish** | Backlog'd in `DASHBOARD_BACKLOG.md` | ~1h investigation + ~50–100 LoC | Live-wiring shipped first | **2** — quality-of-life |
| **v5.0.1 hakit issue #304 mitigation** (iframe destroy/recreate) | 3 fix options in backlog (option 1 = cache iframe; option 3 = direct mount refactor) | Option 1 ~30 LoC, option 3 = refactor | Live-wiring shipped first | **3** — fixes a reported UX bug |
| **v5.1+ background images variant (P7)** | Filed | ~4h | v5.0 ships | **1** — nice-to-have |
| **Telemetry layer doc + synthesis** (your earlier ask) | Filed (task #63) | ~3h | v4.6.13 ships | **3** — needed before you can confidently extend or modify the layer |

### B. Energy

| Item | Status | Effort | Dep | Priority hint |
|---|---|---|---|---|
| **v4.7.x Appliance Scheduler** (B5 — LG ThinQ + Rainbird + forecast-aware skip) | Plan v1.1 just revised today with your feedback | ~28–36h | EC TOU engine (shipped) | **4** — concrete dollar savings, you've iterated on the plan twice |
| **v4.7.x Advanced Energy Management** (forecaster-first) | Plan filed, parked | ~30–40h | v4.6.x close-out (✓ done after dashboard) | **3** — large scope; promote after Appliance |
| **`RESEARCH_2026-05-13_HEMS_optimization_landscape.md`** | Research note, not a build cycle | N/A | N/A | reference doc |

### C. Quality / hardening / debt

| Item | Status | Effort | Dep | Priority hint |
|---|---|---|---|---|
| **EC startup-race resilience** | Investigation Candidate — needs boot-timeline evidence before code | unknown until repro | A 3rd incident with timeline | **2** — defer until evidence |
| **Test-infra debt: production-class drive** | Same class as v4.6.11 C.H2 / v4.6.12 C.C1. Behavioral tests use inline replicas in v4.6.10/11/12/13 | ~6–10h (mock-patch coord helpers) | None | **2** — accumulating but not breaking |
| **AnomalyType discriminator** (mentioned in near-term roadmap memory) | Filed informally | ~10h Tier 2 | None | **3** — natural follow-on to v4.6.6 severity refactor |
| **`PLANNING_v4.6.x_winter_morning_peak_strategy.md`** | Plan exists, never shipped | ~12–16h Tier 2 | None blocking | **2** — seasonal; winter-relevant only |
| **`PLANNING_v4.5.10_hvac_runtime_tunables_and_labels.md`** | Plan filed, status unclear (predates current v4.6.x roadmap) | likely small if cleanup | — | **2** — needs status check |
| **`PLANNING_v4.5.11_ac_energy_aware_ramp_down.md`** | Plan filed | Tier 1 ~6h | EC shipped | **2** |
| **`PLANNING_v4.5.12_ac_ramp_observability.md`** | Plan filed | Tier 1 ~4h | v4.5.11 first | **1** |
| **`PLANNING_v4.6.5_in_memory_anomaly_persistence.md`** | Plan; may have shipped under different number (v4.6.5 series did ship) | check vs `docs/readmes/` | N/A | likely DONE — needs verification |

### D. Larger architectural

| Item | Status | Effort | Dep | Priority hint |
|---|---|---|---|---|
| **v5.0 subentries + arch debt** | Mentioned in `project_roadmap_decisions_2026_05_06.md` memory; no planning doc yet | ~30h+ | v4.7.x close | **2** — large refactor, plan first |
| **`PLANNING_v4.x_B3_PREEMPTIVE_ACTIONS.md`** | B-series Bayesian plan | Tier 2 | B1 (✓) + B2 (✓) | **3** — natural progression |
| **`PLANNING_v4.x_B4_ENERGY_INTEGRATION.md`** | B-series | Tier 2 | B3 | **3** |
| **`PLANNING_EV_BATTERY_DRAIN_PAUSE.md`** | Filed; date unknown | unknown | — | needs read |
| **`PLANNING_OPTIMIZATION_COORDINATOR.md`** | Filed; pre-v4.6.x | likely large | — | likely superseded by Appliance + Advanced Energy |
| **`PLANNING_SMART_PLUG_HARDENING.md`** | Filed | Tier 1 likely | — | **2** |
| **`PLANNING_UTILITY_METER_INTEGRATION.md`** | Filed | unknown | — | needs read |
| **`PLANNING_v4.0.15_FAN_CONTROL_TOGGLE.md`** | Predates v4.6.x | unclear if relevant | — | likely OBSOLETE — check |
| **`PLANNING_v4.5.4_room_config_cleanup.md`** | Predates v4.6.x | unclear | — | needs read |
| **`PLANNING_v4.5.9_hvac_cover_intent.md`** | Predates v4.6.x | unclear if shipped (v4.5.9 in version list ✓) | — | likely SHIPPED — verify |
| **`PLANNING_v4.6.0_likely_next_room_accuracy.md`** | v4.6.0 shipped per version list | — | — | DONE |

### E. Already shipped (verified vs git tags)

These planning docs map to versions in the master history — **no action needed**:
- v4.5.0 (battery strategy redesign), v4.5.2, v4.5.10, v4.6.0, v4.6.1, v4.6.2 + sub-versions, v4.6.3 + sub-versions, v4.6.4, v4.6.5 + sub-versions, v4.6.6, v4.6.7, v4.6.8, v4.6.9, v4.6.10, v4.6.10.1, v4.6.11, v4.6.12.

---

## Suggested priority stacking (one plausible ordering)

**Right now (next 1–2 cycles):**
1. Finish v4.6.13 (small, completes dashboard data prep).
2. HACS install v4.6.11 + v4.6.12 + v4.6.13; run `post_restart_validation.py all`.
3. Write **Telemetry layer doc** (your earlier ask) — locks in what was built so future-you can extend it.

**Next 3–4 cycles (medium-term):**
4. **Guest Mode Actuation Phase 1 (HVAC preset overrides)** — concrete ask, validates the override framework that Dynamic Preset will reuse.
5. **Dashboard v5.0 D3-D7 live wiring** — pays off the v4.6.10-13 sensor investment.
6. **Dashboard v5.0.1 hakit #304 mitigation** if iframe issue is real-world annoying.

**Larger pushes (pick one):**
- **v4.7.x Appliance Scheduler** — biggest dollar savings, longest cycle. Plan is now solid post-2026-05-19 revisions.
- **Weather Redundancy → Dynamic Preset** — two-cycle chain.

**Defer / low priority:**
- EC startup-race investigation (needs evidence).
- Test-infra debt cleanup (accumulating but not blocking).
- Pre-v4.6.x planning docs — most are either shipped or obsoleted by newer cycles; needs an explicit audit pass to confirm.

---

## How to use this doc

1. **Strike** anything you don't want anymore. Commit the strikethrough — the doc becomes the source of truth.
2. **Reorder** Section A/B/C/D items per your priorities.
3. **Mark** with `← NEXT` arrow on the cycle you want me to start.
4. When you want detail on any single item, point at it and I'll pull the full planning doc.

Last updated: 2026-05-19. Re-run on each cycle close-out.
