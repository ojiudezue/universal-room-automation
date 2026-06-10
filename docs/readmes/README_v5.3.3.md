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

## Live Validation (Review D) — prospective criteria

- [ ] Clean restart; zero new URA ERRORs; no write-queue saturation.
- [ ] `sensor.ura_whole_house_power` reads plausible W (vs ~0.29 pre-fix); `solar_power_w` attr consistent.
- [ ] OC device shows: relabeled select (Shadow default), 4 new buttons, kill switch.
- [ ] **Operator hands-on:** select "Reversible devices only" from Shadow → select shows pending state, Confirm button available → press Cancel → returns to Shadow committed. (Real escalation NOT committed during validation.)
- [ ] **Run Cycle Now** press → optimizer logs a manual cycle within seconds (shadow mode, no actuation); second press inside 30s debounces.
- [ ] Options flow → URA Optimizer step renders English labels + section headers; **note WHICH translation shape resolved** (nested sections vs flat) and prune the loser in a follow-up.
- [ ] Status sensor: `last_cycle_findings_count` + `window_findings_count` both present and self-consistent; `next_cycle_eta_seconds` counting down.
- [ ] No CM reload when staging/cancelling pending (sibling entity last_changed invariant).

*Replaced with observed results post-restart per the README write-back rule.*
