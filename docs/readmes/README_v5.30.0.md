# URA v5.30.0 — Owner-Set Registry Refactor (Tier 3, behavior-frozen)

Structural release: the EVSE pause-owner machinery's plumbing (persistence,
restore, prune, peer-holds, status classification) now derives from 17+6
single-source declarations in `energy_pool_owners.py`. **Zero intended
behavior change** — that is the acceptance, held by:

- Golden oracle v3: 3,158 rows across five output surfaces, driving the
  PRODUCTION save/restore path, SHA-256 + source-commit pinned.
- Permanent in-suite mutation matrix (8 real-source mutations per run).
- All owner attr names preserved (S3: sets stay separate; external tests +
  dashboard `pause_reason_human` contracts character-exact).
- Preserved quirks DECLARED (load_shed prune absence — Tier-1 fix queued).

Review: `docs/reviews/code-review/v5.30.0_owner_set_registry.md` — 4 HIGH
(all test-authority escapes found by mutation execution) + 4 MED + 6 LOW,
all closed; orchestrator severed both production call sites as the final
tautology check (caught by named tests both directions).

Why it matters: adding a future owner is one declaration, not a nine-site
scavenger hunt (the blind-window guard's review history is the evidence).
LKG wave 1 and the load_shed/arbitrage Tier-1 pair land next on this base.

## Live Validation — Validated 2026-07-23 (restart ~17:25 CDT)

| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Clean boot | PASS | Zero URA ERROR lines post-boot; house `home_day`; EC normal warm-up (SOC 100 — battery full from the day's excellent solar). |
| L2 | Owner-state restart round-trip | **PASS — byte-identical** | Pre-deploy snapshot 17:21 vs post-restart: identical `paused_by_energy` (both L1 plugs), identical empty `paused_by_fill_priority`, identical `pause_reason_human` strings ("TOU peak/mid-peak pause" ×2, "off" ×2) — character-exact through the new registry restore path. |
| L3 | Nothing else changed | PASS | EV status state + attrs identical; no new/missing attrs; dashboards unchanged. For a behavior-frozen refactor, boring = success. |
