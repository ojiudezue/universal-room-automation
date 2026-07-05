# Verified anchors — 2026-07-02 (fixer pass, repo tip develop @ v5.7.2)

Ground-truth corrections produced by the skill-library review fixer. Any ura-* skill citing
the "do not cite" anchors below must be updated to the corrected ones. Prefer `grep -n`
re-verification over literal line numbers whenever quoting.

## Energy — arbitrage phase floor
(applies to: ura-energy-strategy-reference, ura-energy-invariants-campaign, ura-failure-archaeology, ura-optimizer-autonomy-campaign)
- `_floor_reserve` defined at `energy_battery.py:1519` (`max(existing, effective_reserve)` when `hold_depth == "partial_hold"`).
- All three arbitrage branches clamp: HOLD :1568, CHARGE :1591, **WAIT :1617 (the v5.5.3 fix)**. Additional clamp sites at :2115, :2169, :2400, :3000. **Total 7 call sites** (excluding def).
- QUALITY_CONTEXT.md #53's `energy_battery.py:1521` cite is a **pre-fix historical line** — do not present as current.
- Tier routing: any change to `_floor_reserve` or its emission set is **Tier 3** (canonical per v5.5.3, 2026-06-16).

## Presence — v4.7.14 away-veto
(applies to: ura-debugging-playbook, ura-presence-reliability-campaign, ura-failure-archaeology, ura-architecture-contract)
- Current anchors: params at `presence.py:910` (`unidentified_count`) and `:912` (`all_tracked_persons_away`); v5.7.0 invariant I3 marker at `:976` (byte-identical to v4.7.14); away-veto branch `:980-981`; instance init `:1184, :1194`; census refresh `:3528, :3544, :3546`.
- **Do not cite (drifted):** `presence.py:391, :1367, :1502, :3281`.

## HVAC — night-trust person check
(applies to: ura-architecture-contract, ura-failure-archaeology, ura-presence-reliability-campaign)
- Block spans ~`hvac.py:1245-1290`. Stable grep anchor: log message `"HVAC: night-trust person check errored for zone %s: %s"` at `:1275`.
- Gate uses `FAN_TRUST_STATES` (NOT sleep-only). The 2026-06-05 "zone away when occupied home_night" gap **appears CLOSED** — re-grep before any skill states it open.
- **Do not cite (drifted):** `hvac.py:1151` (now `zone_vacant_past_grace = False` in the v4.7.8 egress-skip block).

## Optimization coordinator
(applies to: ura-failure-archaeology, ura-optimizer-autonomy-campaign)
- `optimization.py:688` is `async_teardown`, NOT the per-finding write site. `optimization.py:691` (cited across MEMORY.md) is **stale**.
- Current post-flood anchors: `_cap_findings` calls :822, :878; `_dispatch_findings_updated_signal` call :896; `_resolve_effective_level` def :2612 (callers :2672, :2874); `log_findings_batch` invocation :3434; helper defs :3470 (dispatch), :3492 (cap).
- `database.py:5034` = `log_findings_batch` DAO; `database.py:5150` = `prune_optimization_findings` DAO — **verified accurate**.
- `database.py:45-51` single-writer queue anchor — **verified accurate** (comment 45-48, queue attrs 49-51).

## Architecture contract
- `_HVAC_TUNABLE_DISPATCH` at `__init__.py:4228` has **exactly 14 rows** (author's "13" hedge was wrong).
- `OPTIONS_RELOAD_SUPPRESS_KEYS` at `__init__.py:4314` is the real constant name; apply-in-place check at :4757.
- `_NO_LIVE_ATTR_KEYS` starts near :4275. `_EC_SETTER_DISPATCH` = 5 rows. `_OFFPEAK_DRAIN_QUALITY` = 4 quality tiers.
- CM allowlist "5 → 37" claim: **unverified** — re-grep before quoting.

## Bug-class catalog
- Header at `QUALITY_CONTEXT.md:7` says "51 documented" — **STALE**; body runs to #53 (= 53 documented). Re-verify: `grep -c '^### Bug Class #' docs/QUALITY_CONTEXT.md`.
- #46 at `QUALITY_CONTEXT.md:1766` (async_update_entry re-entrant reload). #52 (RestoreEntity unavailable-coercion) at :2101-2164. #53 at :2168.

## Diagnostics scripts
- `ura_log_triage.sh` was salvaged to `ura-diagnostics-and-tooling/scripts/`; `db_row_rate_snapshot.py` was never written — create it (and `bash -n` / `py_compile` both) or mark as "design to be created before first use" in SKILL.md.
- `scripts/deploy.sh` exists and is authoritative — cross-reference the pre-existing `deploy` skill, do not duplicate.

## Library-wide rules
- Fact homes: bug-class catalog → ura-failure-archaeology; deploy commands → pre-existing `deploy` skill; Samba mount + live DB path → ura-diagnostics-and-tooling; Tier protocol + institutional-context-first + README write-back → ura-change-control (whose "When NOT to use" table MUST include pre-existing `transition-doc` AND `deploy`); `_floor_reserve` table + Tier-3 routing → ura-energy-invariants-campaign; v4.7.14 away-veto detail → ura-presence-reliability-campaign.
- Frontmatter descriptions: max ~3 sentences, strongest 5-6 operator trigger phrases (the overlong-description finding on ura-optimizer-autonomy-campaign applies library-wide).
- Tier-routing rule: no ura-* skill may present a "just run tests + deploy" path for regression-prone / DB / shared-primitive / cost-and-safety work.

## Provenance
Produced by the wf_afc57b07-be2 fixer agent (2026-07-02) during the claude-fable-5 classifier
outage; persisted by the orchestrator post-salvage. Delete once all corrections are threaded
into the skills and re-verified.

Applied to skills 2026-07-02 by fix pass; sheet retained as audit record.
