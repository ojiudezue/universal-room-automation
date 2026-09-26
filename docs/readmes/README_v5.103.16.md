# v5.103.16 — Every URA thermostat write goes through one of three funnels and leaves a durable record (HVAC W1 Stage A, behaviour-neutral)

**Card:** `HVAC-SETHVACMODE-CHOKEPOINT-1` (workstream `HVAC-W1-THERMOSTAT-DEFINITION`, Stage A only — Stage B stays open) · Tier 2-DB · plan `docs/planning/PLANNING_hvac_w1a_thermostat_write_governance.md` (rev 2 + D5 narrowing + fix-up notes) · read-first `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`

## Problem
URA wrote to the thermostats through two governed funnels plus seven raw `set_hvac_mode` calls scattered across `hvac.py`, `hvac_egress.py` and `hvac_override.py`, and nothing recorded what URA actually sent. Every "who changed this thermostat?" question today — the zone 1 manual strands, the §9.7 away/home feed split, the zone 2 overnight manual 70 — had to be reconstructed from the recorder by inference. Stage B (the per-brand thermostat definition) needs ground truth about URA's own writes before it can decide which Carrier feed confirms a write (state-of-play C22: neither feed is always right).

## Fix (no gate, value, ordering or timing change)
- **Third funnel `emit_set_hvac_mode`** in `hvac_setpoint.py`; the 7 raw sites (B1 heat-cool enforcer, B2/B3 egress pause/resume, B4 override revert, B5/B6/B7 AC reset off/restore/retry) now call it with byte-identical service data and `blocking`.
- **One durable `climate_write` row per attempted wire call** in `ura_activity_log` (importance `notable`, 30-day retention), written fire-and-forget straight through `database.log_activity` (no dedup, no bus event). Each row carries: `site` (resume-then-pin shows as `<site>+resume` / `+pin` / `+pin_retry`), `zone_id`, `reason`, `excursion_id` of the borrow that caused it (forwarded at S3–S8, S11–S13 and egress), `values_before` read synchronously before the write (`preset_mode`, `hold_activity`, setpoints, mode), `values_after` = the exact service data, `wire_ok`/exception, and the **issue** wall-clock time (not return time — ha_carrier updates HA state before returning).
- A cancelled or failed write still records its row, then re-raises (all three funnels aligned).
- **AI rules can no longer write any `climate.*` service** (was 3 verbs). Intended side effect: an AI rule that turns off a non-zone climate device is now refused too; zero climate AI rules exist today.
- **Guards:** an AST completeness lint fails the suite on any raw climate write outside the funnels (dynamic-domain callers flagged only when paired with a climate verb — accepted narrowing, see plan D5), and a test fails if any production funnel call omits a required argument.

## Review ledger
Plan rev 2 (plan review F1–F15). Build `914baecd9` → orchestrator rejected (source-grep site anchors, `git stash`, widened grep window) → round 1 `6cf747569` (behavioural anchors, drills) → full name-diff 1 NEW (missed test caller) → round 2 `7abed3898` (+ required-kwarg guard) → reviews A (FIX-REQUIRED: `excursion_id` never forwarded), B (SHIP in lane; MEDIUM return-time timestamp), C (FIX-REQUIRED: `test_heatcool_enforcer` broken in isolation — invisible to the full run, now caught by `suite_namediff.py --isolate`; B4/B7 unreachable-branch drills green; 4 snapshot orderings untested; AI refusal only source-grepped) → round 3 `f0357f47d` (all fixed, 10-row drill table RED) → focused re-review SHIP (2 LOWs) → full name-diff 1 NEW (`test_heatcool_enforcer` B1 anchor order-dependent the OTHER way: green alone, red in suite order) → round 4 `3a30b7b63` (order-independent anchor via monkeypatch on the loaded module, B4 `excursion_id`, debug text). **Final gates:** full name-diff 0 NEW + isolated run of 98 affected files 0 NEW; merged tree == tested tree.

## Non-goals
Which Carrier feed confirms a write, presets-only returns, provenance ownership (Stage B / W1-B); occupancy fast path (W2).

## Live Validation (prospective — written back post-restart; plan §7)
- **Verify:** every `nudge_started` since restart has exactly one `S5_nudge_start` row on the same zone within ±5 s.
- **Verify:** every `nudge_restored` has one `S6_nudge_restore_setpoint` row and ≥1 row whose site starts `S7_nudge_restore_preset`.
- **Verify:** every `preset_change` has ≥1 `climate_write` row whose site starts `S1_`.
- **Verify (discriminating):** borrow rows (S3/S5–S7/S11–S13/egress) carry a non-null `excursion_id` matching the excursion / `ac_ramp_events` row — null everywhere = forwarding broken.
- **Verify:** `values_before.preset_mode`/`hold_activity` present on the large majority of rows.
- **Verify:** recorder climate changes with no `climate_write` row in the prior 90 s (external-or-bypass) ≤ pre-ship baseline + 10 %.
- **Verify:** zero URA ERROR after restart; zone_1 §9.7 re-issued away writes now appear as rows (≈ 6/h while the feeds disagree).

## Rollback
Revert the merge. Additive rows only; no schema change.
