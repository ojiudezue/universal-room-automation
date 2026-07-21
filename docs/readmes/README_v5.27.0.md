# URA v5.27.0 — NM Cycle C: Per-Recipient Routing Matrix (Tier 3)

Per-recipient notification routing for the NM, per
`docs/planning/PLANNING_nm_cycle_c_routing_matrix.md`. NM remains in observe
mode live (blank per-person targets in the classic sense; routing machinery
honors persisted keys — authoring UI ships in Cycle C-2). Review record:
`docs/reviews/code-review/v5.27.0_nm_cycle_c.md` — Tier 3: five reviews
(A/B/C/D + mandatory D re-pass) + orchestrator mutations; 2 CRITICAL +
9 HIGH found, ALL fixed. Operator checkpoint passed 2026-07-21.

## What ships

1. **Per-recipient router** `_route_for_recipient` — precedence: mute →
   hazard-override → severity×channel matrix → legacy fallback
   (byte-identical to v5.26.0 when no matrix is set; proven by a full
   fixture sweep against the legacy oracle). Live options changes apply
   (coordinator-owned materialization, hash-rebuilt — no frozen routing).
2. **DND-bypass** — per-recipient `dnd_bypass_severities` (default
   {CRITICAL}); hard life-safety floor: life-safety hazards ALWAYS deliver.
   Global TTS/alert-lights gate on the global predicate only — one person's
   personal bypass can no longer wake the house (D-R1).
3. **Mute shortcut** — `ura.nm_mute_person_channel` service (per person ×
   channel × duration; 0 clears; tts/lights rejected) + one button per
   person (primary channel) + mute-duration Number. Restart-safe.
4. **Audit UX** — 5 nullable columns on notification_log (recipient_id,
   route_reason, dnd_bypass_applied, bucket_outcome, matrix_branch) +
   `get_recent_routing_decisions` DAO. O(persons) write volume.
5. **Ratified policy** (operator 2026-07-21): life-safety hazards ignore
   mutes AND DND on messaging (a muted person still gets smoke CRITICAL
   pages; explicit matrix stays authoritative); non-CRITICAL life-safety
   bypasses quiet hours (documented C-INV-1 exception); digest rows no
   longer starve behind the token gate (behavior improvement).
6. **Repeat path rebuilt** — per-person router+DND intersection on repeats
   (review caught a NameError that would have killed life-safety repeat
   paging after the first tick — the cycle's headline save).

## Follow-ups filed
- Cycle C-2 (`PLANNING_nm_cycle_c2_routing_ui.md`, in planning): routing
  matrix options UI + `CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS` additive-only
  tunable (operator: promote overheat/high_co2 without code change) +
  control-surface consolidation.
- Cycle D (deferred register): overflow drain, monotonic refill clock,
  boot-settle set cleanup.

## Test evidence
7321 passed ×2 consecutive runs; failure set = exact pre-existing env-drift
baseline (36+14); 46 cycle tests; 20+ mutation anchors each killed by a
named test (orchestrator re-ran 4 personally, incl. one that exposed a
masked site and gained its own test).

## Live Validation — Validated 2026-07-21 (restart, boot 18:31 CDT)

| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Clean boot, no URA ERROR logs, house state + EC resolve | PASS | Zero URA ERROR lines post-boot (checked T+4 and T+8 min). House state `home_evening` by 18:34:29; EC resolved `self_consumption` at 18:38:29 (normal warm-up). |
| L2 | New surfaces exist | PASS | Service `universal_room_automation.nm_mute_person_channel` registered (verified via services list, duration-0-clears semantics in description); `number.ura_notification_manager_mute_default_duration` = 60.0; NM diagnostics `healthy`; live DB `PRAGMA table_info(notification_log)` shows all 5 audit columns (15 recipient_id, 16 route_reason, 17 dnd_bypass_applied, 18 bucket_outcome, 19 matrix_branch). Mute BUTTONS: zero live — CORRECT-BY-DESIGN (button.py:98 skips persons with no configured primary channel; observe mode = blank targets). Buttons materialize when Phase 2 configures a recipient. |
| L3 | Legacy routing unchanged (0 rows/day shape holds) | PENDING-24H | Due 2026-07-22 evening. |
| L4 | Dry-run sweep Phase 1 | PENDING-OPERATOR | Flip `switch.ura_notification_manager_dry_run` ON + trigger a synthetic notify; expect dry_run=1 rows, zero transport calls. |
| L5 | Audit rows with route_reason=legacy_fallback | PENDING-ORGANIC | First real/dry-run notification writes them; rides L4 or the next organic event. |

Phase 2 (single-recipient live pilot, iMessage) remains checkpoint-gated
per the plan — not part of this validation.
