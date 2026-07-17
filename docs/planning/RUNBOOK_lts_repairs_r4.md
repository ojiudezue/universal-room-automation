# RUNBOOK — LTS statistics repairs R4a / R4b / R4c (Envoy uint32 rollover)

**Status:** PREPARED 2026-07-16 — dry-run evidence gathered live (read-only);
NOTHING EXECUTED against the recorder DB.
**Origin:** `B0_net_energy_classification_probe.md` found the HA consumption
statistic corrupt (92.4% MAPE, multi-million-kWh cumulative spikes) for every
Envoy serial; operator ordered R4 root-cause + repair (no symptom-patching).

## Root cause (confirmed by live probe)

Envoy firmware transiently reports **uint32-max Wh** (2^32 Wh =
4,294,967.296 kWh) on the consumption-today endpoint. HA's
`total_increasing` statistics bake each spike into the cumulative `sum`
permanently; the drop back to a normal value is absorbed as a "counter
reset" (the echo artifact), so the error never reverses. Only
`sensor.envoy_<serial>_energy_consumption_today` (kWh) is affected — every
`lifetime_*` (MWh) statistic probed clean (max hourly deltas < 20 MWh-units,
0 spike rows). 4 Envoy serials (hardware swaps) fragment the history.

## Live-probe facts (2026-07-16, read-only, `/config/home-assistant_v2.db`, HA 2026.7.2)

### R4a targets — corrupted `energy_consumption_today` statistics

| Serial | metadata_id | window | rows | spike events | net spurious offset (kWh) | final `sum` (kWh) | poisoned rows (sum>1e6) |
|---|---|---|---|---|---|---|---|
| 202442014493 (dead) | **108** | 2025-03-10 → 2025-08-04 | 3,258 | 2 | 8,576,091.293 | 8,768,769.775 | 1,905 |
| 202504003374 (dead) | **2464** | 2025-08-12 → 2025-10-02 | 873 | 18 | 77,304,134.870 | 77,309,264.294 | 860 |
| 202428004328 (dead) | **3066** | 2025-10-03 → 2026-03-29 | 3,209 | 1 (2025-12-16 10:00) | 4,294,356.343 | 4,378,478.035 | 1,755 |
| **482543015950 (LIVE)** | **5651** | 2026-04-11 → now | 1,973 | 1 (**2026-05-31 00:00**, row_id 23651000, delta 4,294,629.126) | 4,294,629.126 | 4,315,690.212 | 897 LTS + **1,972 short-term** |

Full per-event list (row_ids, timestamps, deltas) is reproduced by the
dry-run script; the 18-event list for 202504003374 clusters 2025-08-13 →
2025-09-27.

Key sequencing insight: **three of the four corrupted statistics belong to
dead serials that R4c deletes wholesale.** If R4c executes, R4a only needs
to repair the live serial (metadata_id **5651**, one event, one adjustment
of **−4,294,629.126 kWh at 2026-05-31 00:00 local**, plus its poisoned
`statistics_short_term` rows).

### R4c targets — dead-serial statistics (no matching entity-registry entity)

- **53 dead `statistics_meta` rows**, **109,935 `statistics` rows**, 0
  short-term rows. All belong to serials 202442014493 / 202504003374 /
  202428004328 (registry check: only 482543015950 has its envoy_* sensor
  entities live; the stragglers on dead serials are network/diagnostic
  entities, not these statistics).
- Operator decision point: dead-serial **production/battery MWh stats are
  CLEAN** — purging removes that period from Energy-dashboard history
  permanently. Options: purge all 53 (clean slate; the xlsx/Enlighten
  export in `data/enphase/` is the durable history per R5-closed), or purge
  only the 3 corrupt consumption stats + junk CT diagnostics and keep the
  clean production/battery series. The dry-run prints a per-statistic table
  to mark up.

## Artifacts

- R4a script: `scripts/maintenance/lts_repair_r4a_sum_adjust.py` (dry-run default)
- R4c script: `scripts/maintenance/lts_repair_r4c_dead_serial_purge.py` (dry-run default)
- R4b issue draft: `docs/planning/DRAFT_upstream_enphase_envoy_uint32_issue.md` (do not post yet)

## Two repair paths for R4a

1. **PREFERRED — HA's supported statistics-adjustment API.** Developer Tools
   → Statistics → the affected statistic → "Adjust sum" (outlier icon), or
   WebSocket `recorder/adjust_sum` with `{statistic_id, start_time,
   adjustment, adjustment_unit_of_measurement: "kWh"}`. One call per spike
   event with `adjustment = −delta`. Runs through recorder-supported code,
   no core stop, no raw SQL. The dry-run script prints the exact WS payloads.
   **Caveat to verify at execution time:** whether `adjust_sum` also fixes
   `statistics_short_term` (live serial has 1,972 poisoned short-term rows).
   Short-term retention is ~10 days, so even if not, those rows age out;
   but confirm the Energy dashboard "today" view before declaring done.
2. **Fallback — raw SQL** (exact statements printed by the dry-run): per
   event, `UPDATE statistics SET sum = sum - <delta> WHERE metadata_id = <id>
   AND start_ts >= <event_ts>;` and the same against
   `statistics_short_term`. Requires HA core stopped + backup. Note: the
   spike rows' `state` column keeps the garbage 4.29e6 value either way
   (dashboards read `sum` deltas; cosmetic only — optionally NULL it).

## Execution order (nothing below has been run)

1. **Backup** (mandatory, either path):
   ```
   ssh ha 'sqlite3 /config/home-assistant_v2.db ".backup /config/home-assistant_v2.db.pre_r4"'
   ssh ha 'ls -lh /config/home-assistant_v2.db.pre_r4'   # sanity: size ≈ live DB
   ```
2. **R4a dry-run** → capture output:
   `ssh ha "python3 -" < scripts/maintenance/lts_repair_r4a_sum_adjust.py`
3. **Operator review** of the printed UPDATE/WS plan (this runbook's table is
   the expected shape: 4 statistics, 22 events, offsets as above).
4. **Decide R4c scope first** (see decision point above). If purging all
   dead serials: skip R4a for metadata_ids 108/2464/3066 and repair only
   5651.
5. **R4a execute** — preferred path: the `recorder/adjust_sum` WS call(s) /
   Developer-Tools Adjust-sum for `sensor.envoy_482543015950_energy_consumption_today`
   at 2026-05-31 00:00, adjustment −4,294,629.126 kWh. Fallback: stop core,
   `ssh ha "python3 - --execute" < scripts/maintenance/lts_repair_r4a_sum_adjust.py`,
   start core.
6. **Verify dashboards + queries** (below). Energy dashboard consumption for
   a known day should be O(100 kWh), not O(1e6).
7. **R4c dry-run** → `ssh ha "python3 -" < scripts/maintenance/lts_repair_r4c_dead_serial_purge.py`
8. **Operator review** of the 53-row table (mark keep/purge).
9. **R4c execute** (stop core or accept WAL race; backup from step 1 still
   valid only if taken same day — retake if not):
   `ssh ha "python3 - --execute" < scripts/maintenance/lts_repair_r4c_dead_serial_purge.py`
   (or per-statistic via Developer Tools → Statistics FIX buttons /
   `recorder/clear_statistics`).
10. **R4b**: operator reviews + posts the issue draft; attach integration
    diagnostics; confirm exact firmware string first.

## Verification queries (post-R4a)

```sql
-- expect 0:
SELECT COUNT(*) FROM statistics WHERE metadata_id=5651 AND sum > 1e6;
-- expect < 100 (kWh/hour):
SELECT MAX(d) FROM (SELECT sum - LAG(sum) OVER (ORDER BY start_ts) AS d
                    FROM statistics WHERE metadata_id=5651);
-- expect ~21,061 kWh (pre-repair final_sum 4,315,690.212 − 4,294,629.126):
SELECT sum FROM statistics WHERE metadata_id=5651 ORDER BY start_ts DESC LIMIT 1;
-- short-term (if raw-SQL path): expect 0
SELECT COUNT(*) FROM statistics_short_term WHERE metadata_id=5651 AND sum > 1e6;
```

Post-R4c: `SELECT COUNT(*) FROM statistics_meta WHERE statistic_id LIKE
'sensor.envoy_%';` — expect only live-serial (482543015950) + kept rows;
orphan check `SELECT COUNT(*) FROM statistics s LEFT JOIN statistics_meta m
ON s.metadata_id=m.id WHERE m.id IS NULL;` — expect 0.

## Rollback

Restore the backup: stop HA core, `cp /config/home-assistant_v2.db.pre_r4
/config/home-assistant_v2.db` (remove `-wal`/`-shm` siblings), start core.
Statistics written between backup and restore are lost (acceptable — hourly
LTS only). The `adjust_sum` path is also reversible by re-applying the
adjustment with the opposite sign.

## Guard-rails

- NO writes to the live DB without the step-1 backup verified.
- Scripts default to dry-run with a read-only (`mode=ro`) connection;
  `--execute` requires typed confirmation.
- Never blanket-delete statistics for the LIVE serial (482543015950).

## EXECUTED 2026-07-17 00:05–01:10 CDT (orchestrator, operator-authorized)

- **Backup:** HA native `backup/generate` with `include_database: true` →
  backup_id **a9c52726**, 10.3 GB, database_included verified. (File-level
  `.backup` via ssh blocked — ssh user has no /config write; runbook step 1
  amended accordingly.)
- **R4a (live serial only, per sequencing insight):** executed via WS —
  command name is **`recorder/adjust_sum_statistics`** (NOT
  `recorder/adjust_sum` as drafted). Single call: statistic
  `sensor.envoy_482543015950_energy_consumption_today`, start
  2026-05-31T05:00:00+00:00, adjustment −4,294,629.126 kWh.
  Verification: poisoned LTS rows 0 ✓; final sum **21,061.086** (predicted
  ~21,061) ✓; **short-term poisoned rows 0 ✓ — the drafted caveat is
  RESOLVED: adjust_sum_statistics fixes statistics_short_term too.**
- **R4c:** executed via WS `recorder/clear_statistics` with the dry-run
  script's registry-checked 53 statistic_ids (guard-rail: 0 live-serial ids;
  the 5 serial-prefixed survivors are registry-LIVE cost/compensation
  entities, correctly kept). Verification: dead-serial meta 0 ✓, orphan
  rows 0 ✓, live-serial LTS intact (1,974 rows) ✓.
- **R4a dead serials:** SKIPPED per step-4 sequencing (R4c purged them wholesale).
- **R4b:** still pending operator firmware-string confirm + post.

### R4d follow-up (NEW, discovered post-R4a — measurement-gated, do NOT hot-fix)

Two residual sum-bakes on the live serial, different class from uint32
(counter-reset echo flavor, both on incident dates):
- 2026-06-12 00:00 — delta +8,453.2 kWh (state 7.713; Envoy boot incident day)
- 2026-07-02 03:00 — delta +12,092.1 kWh (state 0.0)
Removing both would leave ~523 kWh over the 96-day window (~5 kWh/day —
impossible), while keeping them reads ~219 kWh/day (plausible) — so they are
NOT cleanly spurious; offsetting under-accumulation likely exists elsewhere
(Envoy dropout flatlines). Sizing requires cross-reference against
Enlighten/SPAN data for those days (Measure Before You Build). Dashboard
impact bounded to those two days' readings. Candidate probe: diff HA daily
deltas vs data/enphase site consumption CSV per day across the window.

## R4d probe report (2026-07-17)

Read-only probe (ssh ha, sqlite3 `-readonly`): dumped all 1,976 LTS rows for
metadata_id 5651 (`sensor.envoy_482543015950_energy_consumption_today`) from
2026-04-10 onward; computed per-local-day (America/Chicago) consumption as the
sum of hourly `sum` deltas; diffed against ground truth
`data/enphase/site_energy_consumption_daily_2025-02-24_to_2026-07-15.csv`
over the live-serial window 2026-04-11 → 2026-07-15 (96 days).

### Verdict: "something else" — chronic near-total under-accumulation, not offsetting dropouts

The R4d hypothesis ("bakes partially offset by Envoy dropout flatlines
elsewhere") is REFUTED in its implied shape. The sensor is not a working
accumulator with occasional flatlines — it is a chronically dead accumulator
with occasional life:

- **Every single ordinary day under-reads.** HA daily delta is 0–45 kWh on
  all 94 non-bake days (median ≈ 0.0) vs Enlighten 30–231 kWh/day. Total
  real accumulation outside the two bake days: **~496 kWh vs Enlighten
  13,927 kWh** (96.4% missing). The "~219 kWh/day plausible" window average
  noted at discovery was an artifact of the bakes, not evidence of health.
- **Window totals:** HA 20,975.0 kWh vs Enlighten 13,927.1 kWh → net drift
  **+7,047.9 kWh** at window end.
- **The 2026-06-12 bake (+8,453.186, start_ts UTC 2026-06-12T05:00:00) is a
  near-exact accidental catch-up:** cumulative HA-vs-Enlighten drift the hour
  before was −7,700.3; the bake swings it to +594.8. Consistent with a
  counter-reset echo baking in a lifetime-counter value that itself tracks
  true consumption — coincidence of mechanism, not a correction.
- **The 2026-07-02 bake (+12,092.115, start_ts UTC 2026-07-02T08:00:00,
  state 0.0) over-corrects massively:** drift −2,796.9 before → +9,265.7
  after, decaying to +7,047.9 by 07-15 as daily under-reads continue.
- **NEW CRITICAL: a third, fresh uint32-class bake landed TODAY, post-R4a:**
  2026-07-17 06:00 CDT (start_ts UTC 2026-07-17T11:00:00), state
  4,294,298.13, delta **+4,294,298.130 kWh** — the same 2^32-Wh echo class
  R4a repaired on 2026-05-31. Current final `sum` = 4,315,359.216. The
  upstream emitter is still live; R4a-class repairs will keep being needed
  until R4b (firmware/source) closes it.

### Condensed discrepancy table (HA − Enlighten, kWh)

| Segment | Days | HA total | Enlighten | Diff | Character |
|---|---|---|---|---|---|
| 04-11 → 06-11 | 62 | 335.9 | 8,036.2 | −7,700.3 | flat/dead sensor, steady −124/day drift |
| 06-12 (bake 1) | 1 | 8,473.0 | 177.9 | +8,295.1 | echo; nets prior drift to +594.8 |
| 06-13 → 07-01 | 19 | 100.5 | 3,492.3 | −3,391.7 | dead again |
| 07-02 (bake 2) | 1 | 12,092.1 | 29.4 | +12,062.7 | echo; drift → +9,265.7 |
| 07-03 → 07-15 | 13 | 24.0 | 2,241.9 | −2,217.8 | dead again; window-end drift +7,047.9 |

### Recommendation

**Do NOT attempt to make HA daily deltas match Enlighten via adjust_sum.**
The defect is a chronically non-accumulating sensor, not two bad rows;
matching Enlighten "within noise" would require ~90 per-day adjustments —
that is a statistics *backfill/import* of the Enlighten CSV (separate,
measurement-gated cycle), not a surgical repair, and it would still leave
garbage hourly structure underneath.

**DO surgically remove all three echoes** so the series honestly reflects
what the sensor measured (~516 kWh) and the energy dashboard loses its two
absurd 8.4k/12.1k daily bars (and today's 4.29M one). Exact payloads
(WS `recorder/adjust_sum_statistics`, adjustment_unit_of_measurement kWh,
statistic_id `sensor.envoy_482543015950_energy_consumption_today` for all):

1. start_time `2026-06-12T05:00:00+00:00`, adjustment **−8453.186**
2. start_time `2026-07-02T08:00:00+00:00`, adjustment **−12092.115**
3. start_time `2026-07-17T11:00:00+00:00`, adjustment **−4294298.130**
   (NEW uint32 echo — same class and procedure as executed R4a)

Expected post-adjust final sum ≈ **515.785 kWh** (4,315,359.216 − the three).
Acceptance: no |hourly delta| > 100 kWh remains in the window; final sum
within ±0.01 of prediction. Backup before execution per runbook step 1.

**Escalations:** (a) R4b root-cause is now urgent — the echo recurred today;
(b) the 96%-missing accumulation means this statistic is unusable as a
consumption record regardless of repairs — decide between fixing the Envoy
consumption CT source or importing Enlighten dailies as the dashboard truth.

No writes were executed by this probe.
