# EC stream SOC tier: review summary (Tier 3)

Branch `feature/ec-stream-soc-tier`. Build d36ba1f5a, then fix-up 1 d1b06da71, then fix-up 2 7e078417b. Base f9a2ff33c. Plan: `docs/planning/PLANNING_ec_source_failover_class.md`. Detailed reviews: `ec_stream_soc_tier_review_{A,B,C,D}.md`.

## Findings

| ID | Sev | Finding | Bug class | Status |
|---|---|---|---|---|
| B-HIGH-1 | HIGH | The jump threshold for arm (b) ignored elapsed time, so at 5-min ticks the stream was served on alternate ticks | Time-unscaled threshold | Fixed d1b06da71 (rate × elapsed + margin) |
| D-HIGH-1 | HIGH | A second reconnect cleared the previous value, so the settle never re-armed | State reset on the wrong edge | Fixed d1b06da71 (prev value kept; junk arms settle; extension inside window) |
| D-MED-1 | MED | Stream entity set to the native SOC sensor was accepted | Self-referential config | Fixed d1b06da71 (options flow rejects it) |
| D2-MED-1 | MED | The options check compared against an empty CONF key; the native entity is derived | Wrong key / derived value | Fixed 7e078417b (derive via extract_envoy_serial; runtime guard + warn-once) |
| D2-LOW-1 | LOW | A value changing every tick could extend the settle forever | Unbounded extension | Fixed 7e078417b (cap at first anchor + 2 × 60 s) |
| C gaps F1/F2/F4/F5 | LOW | Untested sites found by mutation | Test authority | Filled d1b06da71 |
| A-LOW | LOW | Capacity entity without a unit is read as Wh | Unit assumption | Accepted, pre-existing; recorded as known limit |
| A-LOW | LOW | INV-SF4 attribute keys present when unset | Doc drift | Plan wording updated |
| A-LOW | LOW | Plan help text stale | Doc drift | Plan fixed |

## Totals

| Sev | Found | Fixed | Accepted |
|---|---|---|---|
| HIGH | 2 | 2 | 0 |
| MED | 2 | 2 | 0 |
| LOW | 6 | 4 | 2 (pre-existing / doc) |

## Verification

- Review C: 105 mutations, 83 RED before gap fill; gaps filled.
- Orchestrator mutation on 7e078417b: trust gate → 5 failed; same-native guard → 1 failed; slew call → 8 failed. Tree restored clean.
- Full-suite name-diff 7e078417b vs f9a2ff33c: 0 new failures (the one failure, `test_v4710_trap_restores_clean_url_on_sigint`, fails on both). +107 tests. Source-mutation and D7 hygiene modes not run.

## Bug-class notes for QUALITY_CONTEXT

- **Time-unscaled threshold**: a per-sample jump bound compared across variable tick spacing. Candidate addition (bound must scale with elapsed time).
- **State reset on the wrong edge**: clearing comparison state on a reconnect defeats the next reconnect check. Fits existing stale-data-source class #7; no new class.
