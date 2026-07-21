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

## Live Validation (prospective — write back observed results post-restart)

| # | Criterion | How to check |
|---|---|---|
| L1 | Clean boot, no URA ERROR logs, house state + EC resolve | log scan + sensors |
| L2 | New surfaces exist: mute service registered, per-person mute buttons, mute-duration Number, audit columns in notification_log | entity registry + DB PRAGMA + services list |
| L3 | Legacy routing unchanged: notification_log stays at ~0 rows/day (observe mode; quieting shape holds) | DB query next 24h |
| L4 | Dry-run sweep (Phase 1 per plan): with dry_run ON, synthetic notify produces dry_run=1 rows and zero transport calls | operator-triggered or next organic event under dry-run |
| L5 | Audit rows appear with route_reason=legacy_fallback on first real/dry-run notification | DB query |

Phase 2 (single-recipient live pilot, iMessage) remains checkpoint-gated
per the plan — not part of this validation.
