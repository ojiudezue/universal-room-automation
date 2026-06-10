# URA v5.3.3 — OC Admin Surface (Pillar B) + Whole-House Power Unit Fix

Combined release of two reviewed cycles (one restart, per operator):

1. **OC Pillar B admin surface** — Tier 2 (2 disjoint reviews + fix-up; 4 HIGH + 5 MED fixed)
   Plan: `docs/planning/PLANNING_OC_phase5_handshake_and_admin_surface.md` (operator-approved knob table)
   Ledger: `docs/reviews/code-review/oc_pillar_b_admin_surface.md`
2. **Whole-house + room power unit normalization** — Tier 2-DB (3 disjoint reviews; 2 HIGH + 3 MED fixed)
   Ledger: `docs/reviews/code-review/whole_house_power_unit_normalization.md`

## What ships

### OC admin surface (zero new CONF keys, zero new DB writes)
- Autonomy select with plain-English rung labels ("Shadow mode — predicted actions, no actuation (default)" …)
- **Confirm-guard**: escalating to L2+ stages `Pending: <rung>` until the new Confirm Escalation button is pressed; Cancel clears; de-escalations + L0↔L1 commit immediately; kill switch wipes pending; pending survives restart; the coordinator NEVER reads the pending key
- 4 new buttons on the OC device: Confirm/Cancel Escalation, Reset Optimizer Settings (preserves kill switch), **Run Cycle Now** (30s debounce; review caught it calling a nonexistent method — now drives the real `run_cycle()` with a new reentrancy guard)
- Full options-flow translations (14 fields, 2 collapsed sections — nested + flat shapes shipped, see Live criteria)
- Status sensor observability: `last_cycle_findings_count` vs `window_findings_count` (resolves the documented disagreement), `next_cycle_eta_seconds`, `last_action`, merged `effective_level_per_dim` + raw `dimension_autonomy_caps`, `llm_invocations_today` (24h-filtered)

### Power units (Bug Class #30, power device class)
- New `power_state_to_w` helper (W/kW exact + case-significant mW/MW, isfinite guard, debug-logged refusals)
- Fixes live `whole_house_power` = 0.29 W at ~2.7 kW (Envoy kW read raw); room coordinator power sum normalized (protects RoomPowerProfile/waste-idle/zone-power/cost-per-hour from any future kW source)
- `WholeHouseCostTodaySensor` energy sum normalized (was raw — Wh source would have inflated cost 1000×)

## Pre-deploy snapshot

| Sensor | Pre-deploy | Expected post-fix |
|---|---|---|
| `sensor.ura_whole_house_power` | 0.29 W (kW misread) | ~house actual draw in W (thousands) |
| OC autonomy select | raw token, no guard | "Shadow mode —…" label; L2+ staging flow |
| OC options flow | ~14 raw snake_case fields | English labels + helper text + 2 collapsed sections |

## Live Validation (Review D) — Validated 2026-06-10 ~15:32 UTC (automated portion, T+8min)

| Criterion | Result | Observed evidence |
|---|---|---|
| Clean restart, zero URA ERRORs | PASS | system_log ERROR + URA filter: 0 entries |
| Whole-house power sane | PASS | `sensor.universal_room_automation_whole_house_power` = **4,228.0 W** (pre-fix 0.29 W — Envoy kW source now normalized) |
| Select relabeled + pending vocab | PASS | state `shadow`, `committed_level: shadow`, 12 options incl. `pending_*` tokens |
| 4 admin buttons present | PASS | Confirm/Cancel **unavailable** (correct — no pending staged), Reset + Run Cycle Now available |
| Forecaster regression check | PASS | post-settle prediction live: home_day → guest @ 0.547, ETA 18 min, model `house_state_log_freq_v1` |
| Status sensor new attrs | PENDING first cycle | optimizer `initializing`/shadow at T+8min (v5.2.2 boot-settle gate holds ~3 cycles); attrs populate after first real cycle |
| Operator hands-on: stage→Cancel escalation; Run Cycle Now + debounce; options-flow label rendering (which translation shape resolved) | OPERATOR PENDING | to be appended on report-back |
| No CM reload on pending stage/cancel | OPERATOR PENDING | proven via sibling last_changed during hands-on |
