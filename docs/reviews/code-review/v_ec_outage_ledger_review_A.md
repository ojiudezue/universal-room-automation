# EC Outage Ledger (Stage L) — Review A: Data integrity + DB architecture

Branch `worktree-agent-aa2c92f9aca51a4f2`, diff `b003a64cd..ea7999889` (3 commits, base verified).
Framing A of Tier 2-DB. Targeted tests: `quality/tests/test_ec_outage_ledger.py` 35 passed.

## Verdict: SHIP (one MEDIUM recommended before deploy, not blocking)

## Findings

| # | Sev | Where | Class | Finding |
|---|-----|-------|-------|---------|
| A-M1 | MEDIUM | `energy_outage_ledger.py:120,236` | Dedup not durable across restart | `_seen_alerts` is RAM-only. Every HA restart re-writes one `nws_alert` row per alert still in the feed. Rows are prune-exempt, so duplicates are permanent. Repro: 3 active alerts plus the restart-storm pattern seen in 2026-09 (~8 restarts/night) gives 24 duplicate rows that night, which inflates any per-alert count read from the ledger. Volume stays inside the 1k/yr budget in normal weather, but the ledger's integrity does not. Fix: seed `_seen_alerts` once from `query_activities(action="nws_alert", since=now-72h, columns=("details_json",))` keyed on `details.id`, the same way `_seed_cloud_seen` does for cloud rows. |
| A-L1 | LOW | `energy_outage_ledger.py:283` | Unbounded event-driven write | The local witness writes on every False to True edge with no minimum interval. `unavailable` is mapped to None and skipped without resetting the baseline, so availability flapping is safe. A real on/off flap of `binary_sensor.enpower_*_grid_status` or `grid_enabled` would still write up to 288 rows/day/sensor that are never deleted. Suggest a per-sensor minimum spacing (for example 30 min) as a rung-1 constant. |
| A-L2 | LOW | `energy_outage_ledger.py:345` | Retry gap | `_cloud_seeded=True` is set before the DB read. If the DB is absent or the query fails on the first sweep, the seed is never retried for that boot. That sweep can then duplicate cloud rows written by a previous boot (at most one batch per boot). Fix: set the flag only after a successful query. |

## Cleared (holds because)

- **Prune exemption** (`database.py:36-55, 6307-6311`): the literal is rendered once at import from a const tuple. Identifiers are checked against `[a-z_]` and anything else raises. The exemption is appended to both tiers as `AND action NOT IN (...)`, and the cutoff is still bound as `?`. With an empty tuple the result is `""`, which is byte-identical to the old SQL. All other actions are pruned exactly as before; the real-DB test at test lines 189-192 covers the mixed kept/deleted case.
- **`query_activities(action=)`** (`database.py:6789, 6841-6844`): parameterized and appended only when not None, so existing callers produce the same SQL and results. There is no `action` index, but `(coordinator, timestamp)` covers the only new caller (`coordinator="energy"` plus `since`), and the ledger volume is trivial.
- **Action-name collisions**: none of the four retained actions is written by any pre-existing path. `"grid_outage"` in `energy_write_verify.py:1956` is a return value, not a `log_activity` action. `inclement_code_drift`/`inclement_memory_cleared` currently have no writers (reserved for later stages; harmless).
- **Writes go through the `log_activity` DAO** (`:159`), which is the serialized write queue. There is no per-row bypass. Each event writes one row, so batching is not applicable.
- **Row shape**: `nws_alert` details always carry `id`, `local`, `decision_age_s`, and the 11 NWS fields (values may be null when the feed omits them, as intended). Cloud rows always carry `witness`, `event_start`, `event_start_utc`, `summary`, `generator_events`, and `corroborated_by_local`. The non-null columns (`timestamp`, `coordinator`, `action`, `importance`, `description`) are always populated.
- **Cloud sweep volume**: runs every 24h with a 48h lookback, deduplicated by event-start in RAM plus a DB seed. Rows exist only for real off-grid events.
- **Update storms**: NWS Update messages carry new IDs, so each one gets its own row by design (each is a distinct message). Volume is bounded by the NWS cadence.

## Stats
CRITICAL 0 · HIGH 0 · MEDIUM 1 · LOW 2. Bug classes: dedup-not-durable (1), unbounded event write (1), retry gap (1).
