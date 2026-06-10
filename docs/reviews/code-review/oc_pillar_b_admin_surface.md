# Code Review — OC Pillar B: Admin Surface Redesign

**Branch:** `feature/oc-pillar-b-admin-surface` (3809315 build → 71ab650 fix-up)
**Plan:** `docs/planning/PLANNING_OC_phase5_handshake_and_admin_surface.md` (Pillar B, D1–D6; operator approved the D1 knob table as proposed 2026-06-10)
**Protocol:** Tier 2 — two framing-disjoint reviews + main-session gate recovery.
**Date:** 2026-06-10

## Findings ledger

| ID | Sev | Finding | Bug class | Status |
|---|---|---|---|---|
| B-H1 | HIGH | Run Cycle Now awaited `async_request_refresh()` — method does not exist on OptimizationCoordinator (not a DataUpdateCoordinator); swallowed AttributeError = silent no-op button. Test passed only because MagicMock accepts any method. | #44 mock-masked dead call | FIXED (71ab650) — calls `run_cycle()`; reentrancy guard added to `run_cycle` (no cycle lock existed); test now uses a spec'd fake exposing ONLY `run_cycle` |
| A-H1 / B-M2 | HIGH | Options form bypassed the confirm-guard AND preserved a staged pending key — later Confirm would commit a stale escalation | #14 staleness / state-machine hole | FIXED — form save strips pending + refreshes select |
| A-H2 / B-M1 | HIGH | Kill-switch engage stripped pending but never refreshed the select → stuck `pending_*` display | Stale entity state | FIXED — refresh slot invoked; two options writes merged into one (A-L11) |
| A-H3 | HIGH | Section field translations placed top-level; HA sections schema nests them under `sections.<id>.{name,data,data_description}` — in-section labels likely wouldn't resolve | Translation schema | FIXED — nested shape added to strings.json + en.json, flat duplicates retained (schema unverifiable offline; Review D proves rendering) |
| A-M4 | MEDIUM | Confirm-guard fired for ANY upward move incl. advisory→shadow; plan says L2+ only | Plan deviation | FIXED — threshold = reversible_device rank |
| A-M5 | MEDIUM | Picking a visible `pending_*` dropdown entry was a silent no-op | UX dead end | FIXED — maps through to the bare level |
| A-M6 | MEDIUM | Garbage pending value left Confirm permanently lit (no-op without strip) | Self-heal gap | FIXED — strips + WARN |
| A-M7 / B-L2 | MEDIUM | `effective_level_per_dim` was a raw caps echo, not the merged effective value its name/plan promised | Misleading observability | FIXED — min(committed, cap) per dim; raw caps exposed as `dimension_autonomy_caps` |
| A-M8 | MEDIUM | `llm_invocations_today` overcounted (lazy 24h eviction) via private coupling | Stale counter | FIXED — 24h read-time filter; private-coupling noted |
| A-L10 | LOW | `_OPTIMIZER_RESET_KEYS` string literals | Drift risk | FIXED — CONF_* constants |
| A-M3-adj | — | Main-session gate recovery findings: select.py missing `from __future__ import annotations` (py3.9 import-fatal); Run-Now debounce 0.0-sentinel swallowed first press when monotonic() starts near zero (real post-reboot window on HA OS); allowlist test harness namespaces + 49-key exact-membership | — | FIXED pre-review (folded into 3809315) |
| A-L9 | LOW | Confirm/Cancel availability lags ≤30s platform poll after staging | — | ACCEPTED |
| A-L12 | LOW | `_attr_name` set alongside translation_key (translated names ignored) | Cosmetic | ACCEPTED — entity_id stability |
| B-L1 | LOW | 6 `pending_*` entries visible in the dropdown | HA requires state ∈ options | ACCEPTED — A-M5 makes them act sanely |
| B-L3 | LOW | `data_entry_flow.section` import + collapsed-section prefill unverifiable offline | — | Review D criterion |

**Verified clean (both reviewers):** coordinator never reads the pending key (effective level from committed key only, read fresh per cycle — rung changes apply without reload); options writes merge-not-clobber with no await between read and write (loop-serialized, no interleave clobber); pending key reload-suppressed + no-live-attr (49-key allowlist, removal detected via key-union diff); restart restore from options without RestoreEntity; hass.data select slot cleared with identity check on remove; zero new DB writes; 12/12 select state translations.

## Statistics

| Severity | Found | Fixed | Accepted |
|---|---|---|---|
| HIGH | 4 | 4 | 0 |
| MEDIUM | 5 | 5 | 0 |
| LOW | 8 | 1 | 7 (documented) |

Suite: 5483 passed / 44 failed / 14 errors / 29 skipped — exact pre-existing baseline, +24 cycle tests, zero new failures.

## QUALITY_CONTEXT recommendations

1. **Bug Class #44 reinforcement (mock-masked dead call):** any test that exercises a cross-object call via MagicMock MUST use `spec=`/a minimal fake so nonexistent methods fail loudly. B-H1 shipped a fully dead button through a green test.
2. **Sentinel-zero monotonic trap:** `monotonic()` can start near 0 (process-relative builds; time-since-boot right after HA OS host reboot) — debounce/throttle code must use a `None` sentinel, never `0.0`.
