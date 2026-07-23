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

## Live Validation (prospective — write back post-restart)

| # | Criterion | How to check |
|---|---|---|
| L1 | Clean boot; house + EC resolve; zero URA ERRORs | logs + sensors |
| L2 | Restart round-trip: any live owner pauses survive the restart (fill-priority morning holds if SOC<80, TOU pauses if mid/peak) and pause_reason_human strings byte-identical to pre-deploy | EV charging status attrs pre/post |
| L3 | NOTHING ELSE observable changed — decisions, sensor attrs, dashboards identical | spot-check battery strategy + EV status vs pre-deploy |
