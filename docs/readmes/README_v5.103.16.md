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

## Live Validation — Validated 2026-09-26 (HACS v5.103.16, HA restarted 20:15:37Z, back 20:19:12Z; house EMPTY — all rows are URA's own)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Rows are written, one per attempted wire call | **PASS** | first post-boot write 15:25 CDT: `ura_activity_log` `climate_write` zone_1, site `S1_reason_ladder`, reason `vacant_past_grace`, `wire_ok=true`, `values_after={preset_mode: away}` |
| 2 | every `preset_change` has a row whose site starts `S1_` | **PASS (1/1 so far)** | 1 `preset_change` since restart ↔ 1 `S1_` row, same zone |
| 3 | `values_before` read before the write | **PASS** | 0 rows missing both feeds; the first row recorded `preset_mode=home` / `hold_activity=away` — the §9.7 feed split captured in the ledger at the moment URA acted on it |
| 4 | Borrow rows carry the borrow `excursion_id` | **PENDING** | no borrow (nudge / compromise / egress / pre-cool) since restart; house empty, so first exercise expected after return. Null everywhere on borrow sites = forwarding broken |
| 5 | Nudge start/restore ↔ S5/S6/S7 rows (plan §7 #1–#2) | **PENDING** | no nudge since restart |
| 6 | External-or-bypass recorder changes ≤ pre-ship baseline + 10 % | **PENDING (24 h)** | needs a full day of post-ship data |
| 7 | Zero URA ERROR after restart | **PASS** | error_log ERROR filter on `universal_room_automation`: none |
| 8 | Installed version | **PASS** | installed `manifest.json` = `v5.103.16` |

In-suite only: CancelledError row + re-raise, AI-rule climate refusal (no climate AI rules configured live), raise-path rows.

## Rollback
Revert the merge. Additive rows only; no schema change.
