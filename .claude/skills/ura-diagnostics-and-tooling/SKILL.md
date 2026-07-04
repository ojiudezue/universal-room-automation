---
name: ura-diagnostics-and-tooling
description: Measure-don't-eyeball runbook for URA — live entity reads via home-assistant MCP, URA sqlite via ura-sqlite MCP, log-scan grep patterns (signal vs boot-transient noise), Samba mount for .storage, sensor.<room>_unavailable_entities semantics, per-coordinator diagnostics, and pre/post-deploy row-rate snapshots. Triggers — "check live", "verify shipped", "read the DB", "why did X not fire", "did this actually work", "live validation", "row rate", "MCP down", "mount is stale", "did the actuator fire". Fact-home for Samba mount + live DB path.
---

# ura-diagnostics-and-tooling

Written 2026-07-02 against URA v5.7.2 for a lone Sonnet-class session or
mid-level engineer with **no subagent fleet**. Copy-paste commands
directly; every path and constant here was verified this session
against the repo. Re-verify anything volatile with the one-liners in
"Provenance and maintenance" at the bottom before quoting it in a
review.

## When to use vs when NOT to use

| Use this skill | Use sibling skill instead |
|---|---|
| Reading live entity state, logs, DB rows to answer a factual question | `deploy` when you're running the release pipeline |
| Post-restart live validation (Review 3 / Review D of Tier 2-DB / Tier 3) | `homeassistant_coding` when you're WRITING a new sensor / integration |
| Pre-deploy row-rate snapshot for a DB-sensitive cycle | `ha-dashboard` when the question is a Lovelace card layout |
| "Why didn't the automation fire?" incident triage | `documenter` when the change has already been proven and you're writing it up |
| Confirming an actuator is (in)accessible before blaming URA logic | `verify` (global) for a generic "does this PR work" flow |

If the question is *what to build*, this skill is the wrong tool.

## Core rules (read every session)

1. **No fabrication.** If the mount is stale or MCP is down, say so and
   fall back — do not invent values. Every "value" you cite in a
   review must have a concrete provenance (entity_id + attribute, DB
   row, log line + timestamp).
2. **Silent-actuator first.** Before blaming URA logic when a light
   "didn't turn on/off", check `sensor.<room>_unavailable_entities`
   AND the actuator device state. `unavailable_entities` covers
   **input sensors only, not actuators** (verified — see the
   Reference Table below). A dead actuator = URA calls
   `turn_on`/`turn_off` and it no-ops. Full runbook in the project
   `CLAUDE.md` "Troubleshooting" section.
3. **Provenance ≠ presence.** "This *should* be there" is not a
   measurement. Read it or admit you didn't.
4. **Date-stamp what you find.** Live values drift; a value read
   without a timestamp is worthless in a review 24h later.

## Reference table — where facts live

Verified 2026-07-02.

| Fact | Source | How to read |
|---|---|---|
| Live entity state | HA WS API | `mcp__home-assistant__ha_get_state entity_id=sensor.foo` |
| Historical state | HA recorder | `mcp__home-assistant__ha_get_history entity_id=... start_time=... end_time=...` |
| Recent HA logs | HA log stream | `mcp__home-assistant__ha_get_logs` (see log-scan section) |
| Config-entry / integration health | HA registry | `mcp__home-assistant__ha_get_integration domain=<domain>` |
| Template render (server-side eval) | HA WS | `mcp__home-assistant__ha_eval_template template="{{ ... }}"` |
| URA sqlite DB | ura-sqlite MCP OR direct sqlite3 over Samba | see "URA DB" section |
| `.storage/core.config_entries` | Samba mount of HA `/config` | see "Samba mount" section |
| Room config (which entities a room drives) | `.storage/core.config_entries`, `domain == universal_room_automation`, match room title | see silent-actuator runbook in `CLAUDE.md` |
| Coordinator diagnostics API | `custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py` (verified: `_LOGGER = logging.getLogger(__name__)` line 32; `log_decision` at line 218; `get_decisions_count` at line 299) | Do not call directly; read the exposed sensors |
| DB single-writer queue | `database.py:45-51` (per project-root context) | Row-rate snapshots below |

## Live entity/state reads (home-assistant MCP)

Canonical URA sensors (grep-verified in `sensor.py` this session):

| Entity | Meaning | Grepped at |
|---|---|---|
| `sensor.ura_house_state` | Aggregate house state (home/away/sleep/…) | `sensor.py:3876` |
| `sensor.ura_presence_house_state` | Presence coordinator's own house-state read | `sensor.py:3970` |
| `sensor.ura_house_state_confidence` | Inference engine certainty | `sensor.py:4171` |
| `sensor.ura_signal_consensus_confidence` | Cross-signal agreement | `sensor.py:4270` |
| `sensor.ura_presence_anomaly` | Presence anomaly summary | `sensor.py:4331` |
| `sensor.ura_presence_coordinator_next_state` | Predicted next state | `sensor.py:4480` |
| `sensor.ura_coordinator_manager` | Coordinator manager top-level | `sensor.py:3825` |
| `sensor.ura_coordinator_summary` | Per-coordinator health summary | `sensor.py:3918` |
| `sensor.ura_<room>_automation_health` | Per-room automation health | `sensor.py:2086` |
| `sensor.ura_<room>_signal_inventory` | Per-room signal count/kinds | `sensor.py:2260` |
| `sensor.ura_<room>_ai_automation_status` | Per-room AI status | `sensor.py:2412` |
| `sensor.<room>_unavailable_entities` | Count of unavailable **input** entities in the room (NOT actuators) | class `UnavailableEntitiesSensor` at `sensor.py:1623` |
| `sensor.ura_energy_coordinator_battery_strategy` | Battery TOU strategy + attrs (inclement hold, arbitrage, reserve floor) | memory-of-record: v5.5.0 |

Read pattern — always pull attributes, not just state:

```
mcp__home-assistant__ha_get_state entity_id=sensor.ura_energy_coordinator_battery_strategy
```

Then in the review, cite `state=... attrs.<key>=... read_at=<ISO ts>`.

### Interpretation guide

- **`state == unknown` right after HA restart** = coordinator hasn't
  completed first update yet. Wait one update tick before flagging.
  Only becomes a bug if it persists past coordinator's declared update
  interval.
- **`state == unavailable` on a URA sensor** (not a room device) = the
  coordinator failed to setup. Check `ha_get_integration
  domain=universal_room_automation` and logs.
- **Entity present with a real value but attrs missing** = attribute
  writeback bug (Bug Class #53-adjacent, "computed but not
  consumed"). Grep the sensor class for the attr key.
- **`sensor.<room>_unavailable_entities > 0`** = an input signal
  (motion / lux / occupancy) is dead. Does NOT mean the actuator is
  dead. See silent-actuator runbook.

## URA sqlite DB reads

DB filename: **`universal_room_automation.db`**, mounted at
`/Users/ojiudezue/ha-config/universal_room_automation/data/universal_room_automation.db`
(verified against `CLAUDE.md` line 84).

Key tables (verified in `database.py`, `CREATE TABLE IF NOT EXISTS` positions in parentheses):

| Table | line | Purpose |
|---|---|---|
| `occupancy_events` | 393 | Per-room occupancy transitions |
| `environmental_data` | 408 | Env samples (temp/hum/lux) |
| `energy_snapshots` | 423 | Per-room energy snapshots |
| `external_conditions` | 452 | External weather / grid |
| `zone_events` | 471 | Zone-level transitions |
| `energy_history` | 486 | Longitudinal energy |
| `person_visits` | 517 | Per-person room visits |
| `person_presence_snapshots` | 537 | Person presence snapshots |
| `room_transitions` | 552 | Person room→room transitions |
| `unknown_devices` | 572 | Unregistered BLE/WiFi |
| `census_snapshots` | 586 | Presence census |
| `person_entry_exit_events` | 607 | Entry/exit events |
| `decision_log` | 625 | Coordinator decisions |
| `compliance_log` | 668 | Compliance / override tracking |
| `anomaly_log` | 737 | Coordinator anomalies (v4.7.12 shape) |
| `optimization_findings` | 770 | Optimization Coordinator outputs |
| `optimization_daily_digest` | 811 | Daily rollup |
| `metric_baselines` | 829 | Baseline metrics |
| `outcome_log` | 844 | Decision → outcome |
| `parameter_beliefs` | 865 | Bayesian priors |
| `parameter_history` | 878 | Belief history |
| `notification_log` | 894 | NM outbound |
| `notification_inbound` | 919 | NM inbound |
| `house_state_log` | 937 | House-state transitions |
| `energy_daily` | 952 | Daily energy rollup |
| `energy_peak_import` | 969 | Peak-import events |
| `evse_state` | 981 | EVSE state cache |
| `circuit_state` | 992 | Circuit state cache |
| `envoy_cache` | 1004 | Envoy poll cache |
| `energy_midnight_snapshot` | 1024 | Midnight snap |
| `energy_state` | 1045 | Rolling energy state |
| `room_state` | 1055 | Room state cache |
| `room_energy_baselines` | 1078 | Per-room energy baselines |
| `arbitrage_cycles` | 1095 | Battery arbitrage cycles (v5.5.x) |
| `ura_activity_log` | 1114 | Cross-coordinator activity |

**Do not blindly write DDL yourself in a review** — always extract
schema from `database.py`. Behavioral tests hand-copying DDL is
QUALITY_CONTEXT Bug Class C-family (v4.6.3 test-infra defect).

### Two paths to the DB

1. **ura-sqlite MCP (preferred, hot path).** Verify `--db-path` in
   `~/.claude.json` points at the live Samba path above, not
   `~/.cache/ura/`. If it points at cache, remount and re-configure
   before quoting numbers.
2. **Direct sqlite3 over the mount (fallback when MCP down).** Use
   the row-rate script below or:
   ```
   sqlite3 -readonly \
     "file:/Users/ojiudezue/ha-config/universal_room_automation/data/universal_room_automation.db?mode=ro" \
     "SELECT COUNT(*) FROM anomaly_log WHERE timestamp > datetime('now','-1 hour');"
   ```
   Use `?mode=ro` so a stale writer lock doesn't error you out.

### Common quick queries

```sql
-- Anomalies in the last hour by coordinator + severity
SELECT coordinator, severity, anomaly_type, COUNT(*)
FROM anomaly_log
WHERE timestamp > datetime('now','-1 hour')
GROUP BY 1,2,3 ORDER BY 4 DESC;

-- Optimization findings shipped this deploy
SELECT dimension, severity, level, target, outcome, COUNT(*)
FROM optimization_findings
WHERE timestamp > datetime('now','-30 minutes')
GROUP BY 1,2,3,4,5;

-- Occupancy churn per room, last 4h
SELECT room, COUNT(*) as events
FROM occupancy_events
WHERE timestamp > datetime('now','-4 hours')
GROUP BY room ORDER BY events DESC LIMIT 20;

-- Decision→outcome pairs missing an outcome (stuck)
SELECT d.coordinator, COUNT(*)
FROM decision_log d
LEFT JOIN outcome_log o ON o.decision_id = d.id
WHERE d.timestamp > datetime('now','-1 day') AND o.id IS NULL
GROUP BY 1 ORDER BY 2 DESC;
```

### Sentinels-only = payload shape broken

If a table has rows in the last hour but every non-key column is NULL
or a sentinel constant, the payload writer is likely broken (v4.6.1.1
and v4.6.3-initial-build failure mode). Assert **at least one row
with non-zero NOT NULL columns within an hour of restart** as Live
Validation Review D — one query per DB-sensitive table.

## Log-scan runbook — what matters vs boot-transient noise

Read via `mcp__home-assistant__ha_get_logs`. When MCP is down, SSH
into HA and `journalctl` / `tail -n 5000
/config/home-assistant.log`.

### Signal grep patterns (URA-specific)

```
# Real URA errors — investigate every one, always
grep -E "ERROR .*universal_room_automation" home-assistant.log

# Untracked / unhandled task exceptions (Bug Class #34 family)
grep -E "UnboundLocalError|Task exception was never retrieved|coroutine .* was never awaited" home-assistant.log

# "connection lost set_value" = websocket backpressure, NOT a crash
# (memory-of-record: CM reload-suppression cycle 2026-06-07). Do NOT auto-flag.

# Coordinator setup failures
grep -E "Setup (of|timed out).*universal_room_automation" home-assistant.log

# Reload cascades (parent-entry reload watchdog hazard, 2026-06-03)
grep -E "Reloading config entry.*universal_room_automation" home-assistant.log
```

### Noise to dismiss (do not alarm)

| Pattern | Why it's noise |
|---|---|
| Shelly `Not connected` at boot | Cloud device slow to reconnect; recovers within ~2min |
| Template sensor `from_json` errors at boot | Downstream template runs before upstream sensor has a value |
| `appletv` errors at boot | Non-URA integration |
| `restored:true` on an actuator right after restart | HA is repopulating state; wait one poll cycle |
| "No room coordinators found after 60s" (post-v4.7.18.2) | Should be 0 or 1 post-fix; >4 = regression |

### Boot storm shape

The v4.7.19 / v4.7.21 memories describe a **cold-boot away-actuation
storm** where slow cloud devices saturate the event loop and
`house_state` aggregate freezes ~15 min while per-room sensors update
fine. If you see this shape, do not blame the current cycle — verify
against the boot pattern first. `sensor.ura_house_state`
`last_changed` should advance within one settle-gate window.

## Samba mount for `.storage/core.config_entries`

Verified against `CLAUDE.md:84-86`. Mount path is `/Users/ojiudezue/ha-config`
(operator's account). Adjust to your account when re-running.

```
# Check the mount
ls /Users/ojiudezue/ha-config/.storage/core.config_entries >/dev/null && echo MOUNTED

# Remount if stale/down (copy verbatim from CLAUDE.md — the URL-encoded
# password matters; do not "fix" the %40 or %5E)
mount_smbfs '//homeassistant:Verycool9277%40%5E@192.168.13.13/config' /Users/ojiudezue/ha-config

# Find URA config entries by title
python3 -c "import json,sys;
d=json.load(open('/Users/ojiudezue/ha-config/.storage/core.config_entries'));
for e in d['data']['entries']:
  if e.get('domain')=='universal_room_automation':
    print(e['title'], '::', e.get('entry_id'), '::', list((e.get('data') or {}).keys())[:6])
"
```

Read-only access; never write into `.storage/`.

## Diagnostics sensors per coordinator

Each URA domain coordinator exposes a health / diagnostics surface.
Read these before diving into logs:

- `sensor.ura_coordinator_summary` — overall coordinator manager health
- `sensor.ura_presence_coordinator_next_state` — presence prediction
- `sensor.ura_energy_coordinator_battery_strategy` — energy strategy
  + reserve floor + arbitrage state (attrs are the story)
- `sensor.ura_<room>_automation_health` — per-room summary
- `sensor.ura_<room>_signal_inventory` — signal count / kinds present

For anything beyond these, grep `sensor.py` for the coordinator name
+ `DiagnosticSensor` class:

```
grep -n "class.*DiagnosticSensor\|class.*DiagSensor" \
  custom_components/universal_room_automation/sensor.py
```

Verified example: `HVACPreArrivalDiagnosticSensor` at `sensor.py:10306`.

## Pre/post-deploy row-rate snapshots (DB-sensitive cycles)

Tier 2-DB and Tier 3 cycles MUST take a **pre-deploy row-rate
snapshot** of every affected table, keyed by
`(coordinator, severity, type)` or the table's analogous shape.
Without this, the ±25% post-deploy comparison is impossible and the
cycle is not deploy-ready (per project `CLAUDE.md` "Tier 2-DB").

Use the packaged script (v1 — minimal, read-only sqlite):

```
python3 .claude/skills/ura-diagnostics-and-tooling/scripts/db_row_rate_snapshot.py \
  --db-path /Users/ojiudezue/ha-config/universal_room_automation/data/universal_room_automation.db \
  > /tmp/ura_rows_pre_v<version>.txt

# ... deploy + restart + wait an hour ...

python3 .claude/skills/ura-diagnostics-and-tooling/scripts/db_row_rate_snapshot.py \
  --db-path /Users/ojiudezue/ha-config/universal_room_automation/data/universal_room_automation.db \
  > /tmp/ura_rows_post_v<version>.txt

diff /tmp/ura_rows_pre_v<version>.txt /tmp/ura_rows_post_v<version>.txt
```

The script uses `sqlite3` in read-only mode (`?mode=ro`) so it cannot
corrupt the live DB. It discovers timestamp columns dynamically via
`PRAGMA table_info` — missing tables/columns are reported, never fatal.
Key tables covered: `anomaly_log`, `optimization_findings`,
`ura_activity_log`. Pass `--all` to also snapshot every user table.
Bucketed-by-`(coordinator, severity, type)` reporting is a
**planned enhancement** — v1 reports per-table totals only. If your
Tier 2-DB cycle needs bucketed rates today, run a targeted sqlite3
query with the exact `GROUP BY` shape you need and save the output
alongside the snapshot files.

## Live validation (Review D / Review 3) checklist

Do this AFTER `scripts/deploy.sh` has flipped the HACS version and
HA has restarted. Write results back into `docs/readmes/README_v<ver>.md`
(mandatory — the README git history is the validation ledger).

- [ ] `mcp__home-assistant__ha_get_integration domain=universal_room_automation`
      returns `state=loaded`
- [ ] For each acceptance criterion in the planning doc: run the
      concrete `ha_get_state` / `ha_eval_template` / DB query that
      proves it. Record `entity_id + attribute + observed value +
      read_at`.
- [ ] Log scan clean: no new `ERROR` lines from
      `universal_room_automation` in the 10 min after restart other
      than known boot transients (see noise table above).
- [ ] For any new/changed DB table: at least one row with non-zero
      NOT NULL columns within one hour of restart (sentinels-only =
      broken payload shape).
- [ ] Row-rate post-snapshot within ±25% of pre-snapshot per
      `(coordinator, severity, type)` bucket.
- [ ] For actuator-visible changes: pull `sensor.<room>_unavailable_entities`
      AND the actuator device availability before concluding
      "actuation worked".

Rewrite the README's prospective "Live Validation" bullet list into a
`Validated <ISO date>` results table with observed values.

## Silent-actuator triage (short form)

Full runbook lives in project `CLAUDE.md` "Troubleshooting". Short
form when someone says "room stopped working":

1. Read the room's config from `.storage/core.config_entries` — find
   the actual entities (`lights`, `night_lights`, `alert_lights`,
   `climate_entity`, motion / lux / humidity sources). Do not assume
   friendly names.
2. `ha_get_state entity_id=<the-actuator>` — if `unavailable` /
   `restored:true`, it's offline. Cross-check its sibling
   power/voltage sensors.
3. `ha_get_integration domain=<vendor>` — a Shelly/etc. entry can
   stay `loaded` while a specific device is off-WiFi.
4. `sensor.<room>_unavailable_entities` tracks **input sensors, not
   actuators** — a dead light is invisible there (class
   `UnavailableEntitiesSensor` at `sensor.py:1623`; verified 2026-07-02).
5. Recovery: reload the specific stuck config entry via
   `homeassistant.reload_config_entry` — do not blanket-reload. Do
   NOT reload the URA parent entry (watchdog restart hazard,
   2026-06-03 memory).

## Fallbacks when MCP or mount is down

| Down | Fallback |
|---|---|
| home-assistant MCP | `scripts/post_restart_validation.py <cycle>` uses HA WS directly with the long-lived token from `.mcp.json` (verified this session; script lives in repo `scripts/`) |
| ura-sqlite MCP | Direct `sqlite3 -readonly file:<path>?mode=ro` over the Samba mount |
| Samba mount stale | `mount_smbfs` command above; if that fails, SSH into HA at `192.168.13.13` and read `/config/...` directly |
| Everything down | Log the outage in the review, mark all live checks as UNVERIFIED, do NOT deploy — the cycle is blocked, not passing |

## Scripts shipped with this skill

- `scripts/ura_log_triage.sh` — greps a home-assistant.log for the
  patterns above, splits signal vs noise, prints a compact report.
- `scripts/db_row_rate_snapshot.py` — read-only sqlite; per-table
  row totals + last-24h counts + rows/hour for the key URA tables
  (`anomaly_log`, `optimization_findings`, `ura_activity_log`),
  with `--all` to walk every user table. Schema-agnostic (uses
  `PRAGMA table_info`). Bucketed `(coordinator, severity, type)`
  reporting is a planned v2 enhancement.

Both are wired to the verified paths above. Run `bash -n
scripts/ura_log_triage.sh` and `python3 -m py_compile
scripts/db_row_rate_snapshot.py` to confirm they parse before use.

## Provenance and maintenance

Volatile facts — re-verify with these one-liners if you're going to
quote them in a review more than ~30 days after 2026-07-02:

```
# Table names + line numbers in database.py
grep -n "CREATE TABLE IF NOT EXISTS" custom_components/universal_room_automation/database.py

# UnavailableEntitiesSensor location + semantics
grep -n "class UnavailableEntitiesSensor\|_get_unavailable_entities\|_unavailable_details" \
  custom_components/universal_room_automation/sensor.py

# Canonical ura_ entity_ids in the sensor module
grep -nE "Entity: *sensor\.ura_" custom_components/universal_room_automation/sensor.py

# Samba mount + DB path
grep -nE "mount_smbfs|universal_room_automation\.db" CLAUDE.md

# Coordinator diagnostics API (log_decision / get_decisions_count / …)
grep -nE "def (log_decision|get_decisions|schedule_check|_store_compliance)" \
  custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py
```

If any of these greps returns a different line number than the
Reference Table above, update this SKILL.md — do not silently quote
stale numbers in a review.
