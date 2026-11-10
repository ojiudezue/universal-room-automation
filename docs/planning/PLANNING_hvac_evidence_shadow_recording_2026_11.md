# PLANNING: HVAC evidence-rule shadow recording (display only), rev 2

**Card:** HVAC-GUEST-EVIDENCE-RULE-1, phase 1. **Operator approval:** 2026-11-10, "HVAC recording ok".
**Rev 2 (2026-11-10):** revised for the plan review `docs/reviews/code-review/PLANREVIEW_hvac_evidence_shadow_recording.md` (FIX-PLAN, F1-F13). The finding-to-fix map is in §12.
**Tier:** **2-DB** (rev 2 adds a small table, §8). One plan review is done; this revision answers it.
**Source audit:** `docs/planning/AUDIT_guest_onset_thresholds_and_hvac_evidence_states_2026_11_10.md` Part 2 (§2.5 item 1 is this plan).

## 0. Goal and shape

In every house state OUTSIDE `HVAC_EVIDENCE_RULE_STATES` (`hvac_const.py:1097`, `("home_day","home_evening")`), compute what the evidence rule WOULD decide per room, roll it up per zone, and record each zone-level divergence from the decision HVAC actually used. Record the exposure as well. Change no actuation. After the next guest stay, one SQL query (§7) labels each state SAFE / NOT SAFE / INSUFFICIENT.

The evidence states are recorded too, as the reference arm. There the evidence rule is live and the legacy shadow is the counterfactual. The same row shape therefore gives an in-system home_day baseline, not the audit's reconstruction (model error 4.3 % / 2.0 %, audit §2.2).

New behaviour, all of it diagnostic:
- one new table `hvac_evidence_shadow`, with episode rows and daily exposure rows;
- its nightly prune.

No entity, attribute, signal, config field, bus event or `ura_activity_log` row is added.

## 1. Institutional context verified

**Read completely:**
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (all lines, 2026-11-10; the §2 drift was fixed in `60b423a1`, C39);
- the audit above (all 169 lines);
- the plan review (all of it).

Presence is not touched: the plan reads the room evidence stamp that HVAC already reads.

**Prior planning docs:**
- `PLANNING_hvac_fast_occupancy_response.md` REV 7: the evidence rule, INV-5 "shadow untouched", D5.
- `AUDIT_hvac_raw_evidence_gaps_2026_09_26.md`.
- `AUDIT_exit_evidenced_vacancy_probe.md` (header skim, no overlap).
- `PLANNING_baec_config_flow_and_shadow_eval.md` (energy shadow, not reusable).
- W1-C P1 golden precedent (State of Play W1-C P1 note, `quality/tests/golden/w1c_p1_goldens.json`).

### 1.1 Prior-art scan of shadow, diagnostic and persistence surfaces

| Surface | Site | Verdict |
|---|---|---|
| Legacy shadow `_shadow_hvac_occupied` | `hvac_zones.py:2133`, called `:1561` on every pass in every state | **REUSED** as the legacy side. Nothing added to it |
| `_hvac_shadow_release_at` (exact legacy release instant per room) | `hvac_zones.py:348`, written `:1567-1576` | **REUSED** for release timing (F2). Rev 1 missed it |
| `_hvac_last_ev` / `_hvac_last_active` | written `:1632-1633`, before the early return | **REUSED** as the evidence inputs |
| `_evidence_hold_seconds` | called `:1650` | **REUSED**, read-only |
| Legacy early return | `hvac_zones.py:1634-1647` | **The blocker.** The shadow term is computed before it (E1) |
| Live `_d5_update` | `:1672-1693` | **NOT called** by the shadow (it writes D5 dicts). D5 is handled by exclusion instead (§3.3) |
| `hvac_occupied_diag` | `:2685` → `binary_sensor.py:959-968` | **NOT extended** (recorder churn on ~43 entities) |
| Zone status daily counters | `:1190-1212` | **NOT used** (8-day recorder; no outcome field) |
| Degraded-events queue/drain (sync producer → async side-effect) | `_pending_degraded_events` `hvac_zones.py:404`, `drain_degraded_events` `:2415`; `hvac.py:2341` "no create_task from a sync tick path" | **REUSED pattern** for the writes (F11, §5 D3) |
| `climate_write` direct DB write (bypasses ActivityLogger) | `hvac_setpoint.py:285-306` | **REUSED pattern**: direct `database` call, fire-and-forget, coroutine duck-check (F3) |
| `ura_activity_log` + `ACTIVITY_LEDGER_RETAINED_ACTIONS` | `database.py:1719`; `const.py:5434-5445` | **REJECTED** (F3, F4). Its own budget rule (`const.py:5434-5436`: "<= ~1,000 rows/yr, revisit with a dedicated table above 5,000/yr") points to a dedicated table at this plan's ~20k rows/yr. Writing there also reaches `URALastActivitySensor` (`sensor.py:15150-15240`, a live v8 tile), the `ura_action` bus event and `ura/logs/subscribe` |
| `optimizer_shadow_samples` + `prune_optimizer_shadow_samples` + nightly registration | `database.py:1343`, `:7636`; `nightly_maintenance.py:56` | **REUSED pattern** for the new table's DDL, batched prune and nightly hook. The table itself is rejected (no duration/outcome/state; optimizer-owned) |
| `house_state_log` | `database.py:1494` | **No longer used** as the denominator (F1, F13). In-system exposure rows replace it |
| `decision_log` | `database.py:1148` | rejected: reads as an actuation |
| Zone-delete purge | `database.py:9986` (`DELETE ... WHERE zone = zone_name`, house-zone NAME) | **Not extended** (§5 D3, "Orphans") |

### 1.2 Per-addition REUSED / NEW

| Addition | Verdict | Grep |
|---|---|---|
| Table `hvac_evidence_shadow` | NEW (dedicated table, per the `const.py:5434` rule) | `grep -n "evidence_shadow" database.py` → 0 |
| `prune_hvac_evidence_shadow` + `nightly_maintenance` entry | NEW method on the existing pattern | — |
| `HVAC_EVIDENCE_SHADOW_ENABLED`, `_MIN_EPISODE_S`, `_MAX_ROWS_PER_ZONE_DAY`, `_RETENTION_DAYS`, `_BOOT_EXCLUDE_S` | NEW rung-1 consts in `hvac_const.py` | `grep -n "SHADOW" hvac_const.py const.py` → none for HVAC occupancy |
| RAM dicts on `ZoneManager`: `_hvac_ev_shadow_out`, `_hvac_legacy_shadow_out`, `_ev_shadow_pass_rooms`, `_ev_shadow_ep`, `_ev_shadow_expo`, `_ev_shadow_rows_today`, `_ev_shadow_pending_rows` | NEW. Seven names; rev 1 said three and missed the legacy-output dict (F5) | the existing dicts at `hvac_zones.py:339-375` all feed live decisions; none may be reused |

## 2. Falsifiable invariant (byte-identical actuation)

**INV-SHADOW.** Take any sequence of producer inputs: room data, evidence stamps, refresh results, house states, `zone_ids` filters, entry-dwell / return-window values, and coordinator-absent and hallway rooms. In ANY house state, the following are identical to a **golden captured on pre-build source** (F10). This holds with `HVAC_EVIDENCE_SHADOW_ENABLED = True` AND with `False`.

- Every `RoomCondition.hvac_occupied`, plus `zone.any_room_hvac_occupied`.
- Every pre-existing `ZoneManager` dict the producer writes:
  - `_hvac_output`, `_hvac_rule`, `_hvac_day_release_at`, `_hvac_ev_released_at`;
  - `_hvac_pending`, `_hvac_cold`, `_hvac_exempt_reason`;
  - `_hvac_arm_onset`, `_hvac_ep_armed`, `_hvac_armed_at`, `_hvac_arm_class`, `_hvac_arm_span_s`, `_hvac_dwell_s`;
  - the episode dicts and `transit_filtered_today`;
  - the shadow's `_hvac_armed`, `_hvac_tail_until`, `_hvac_arm_source` and `_hvac_shadow_release_at`.
- `zone.last_occupied_time`, `continuous_occupied_since`, `zone_release_at`, `room_release_at`.
- Exit-timer arming, every S1 / row-1 / D6 / D7 / sweep decision, and every `climate_write` row.

The ONLY differences allowed are the seven dicts of §1.2 and rows in `hvac_evidence_shadow`.

**How to break it.** D-style review should try each of these:
- the shadow term writes `_hvac_day_release_at` (the live line `:1653` does);
- the shadow calls `_d5_update`;
- the shadow is computed after the early return mutates state;
- a tracker exception propagates out of `update_room_conditions`;
- the tracker runs before the rollup;
- the tracker or the drain awaits inside the producer;
- a live line inside `:1561-1747` is edited "harmlessly". The golden catches this; a const on/off diff would not.

## 3. Producer and consumer checks

### 3.1 Value 1: room shadow outputs (per pass)

**`ev_shadow(room)`.** Computed as `active' OR (last_ev is not None AND now < last_ev + hold_ev)`, where:
- `active' = evidence_active if refresh_ok is not False else False`;
- `hold_ev = _evidence_hold_seconds(room_type, override_day)`.

This is the live term at `:1650-1660`, without the refresh-fail hold (`:1661-1669`) and without D5. A pure static helper computes it. The result is written to `_hvac_ev_shadow_out[room]`.

**`legacy_shadow(room)`.** The `shadow_out` argument, written to `_hvac_legacy_shadow_out[room]` (F5). In evidence states `_hvac_output` holds the EVIDENCE output, so this dict is the only place the legacy answer survives the pass.

**Per-pass membership (F6).** E1 adds the room to `_ev_shadow_pass_rooms`, which is cleared at the top of `update_room_conditions` beside `_rooms_processed_this_pass` (`:930`). The tracker reads ONLY rooms in that set. Rooms excluded this way contribute False to both sides for this pass:
- a coordinator-absent room (the `continue` at `:893-930`);
- a room re-typed to hallway (marked processed at `:1005-1025` but never reaching `_evidence_rule_output`).

The stale dict values are never read. Sides are taken from the per-pass set: the evidence side is `_hvac_ev_shadow_out` in legacy and night states, and the live `_hvac_output` in evidence states; the legacy side is `_hvac_legacy_shadow_out`.

**Dependency health.**
- `last_evidence` comes from the room's single stamp, `_stamp_hvac_evidence` (State of Play §3.1), live in all states since v5.103.20.
- After a restart it is `None` until the room's first evidence (`coordinator.py:6013-6019`).
- The shadow's `_hvac_armed` is RAM-only.
- Both make the first passes after boot unreliable, so boot passes are excluded (§3.3, F9).

**Consumers.** One: the zone tracker (D2). Display/diagnostic only. The D4 lint pins this.

### 3.2 Value 2: zone episode and exposure

**Producer.** The tracker runs after the zone rollup in `update_room_conditions` (after `:1096-1110`), only for zones processed in this pass.

Sides, each an OR over the zone's per-pass rooms:
- `L` (legacy side) = `legacy_shadow`.
- `E` (evidence side) = `ev_shadow` in legacy/night states, and `_hvac_output` (the live evidence decision) in evidence states.
- In legacy states `L` equals `zone.any_room_hvac_occupied`. In evidence states `E` does. Night states decide on `L OR E`.

Kinds:
- `less` = `L and not E`;
- `more` = `E and not L`.

**Exposure (F1).** `_ev_shadow_expo[(zone_id, house_state)]` accumulates the seconds `L` was True between consecutive passes. The interval runs from the previous pass to this one and is charged to the previous pass's `L` and house state; intervals longer than 2 × `HVAC_DECISION_TICK` are capped at that length (HA-down time is not exposure, F13). Passes inside the boot window (§3.3) are excluded.

Once per local day, at `reset_daily_counters` (`hvac_zones.py:2725`), each zone writes one row per state with non-zero exposure (`row_type='exposure'`). On orderly shutdown nothing is flushed; a restart loses at most the partial day's exposure. That is symmetric with the lost episodes, and stated.

**Episode close (F2).** An episode opens on the first pass with a divergence. It closes on the first pass where any of the following holds.

1. **`E` returned while `L` is still True.** Classification:
   - Let `t_ret` = this pass's time.
   - Let `R` = the rooms that were legacy-occupied at open (`legacy_rooms`).
   - If any room in `R` has `_hvac_shadow_release_at[room] < t_ret` recorded during the episode, legacy actually released and re-armed between passes. The episode closes `released`, with `ended_at` = the EARLIEST such release instant.
   - Otherwise it closes `resumed`.

   So a release that no pass observed (guest/away/arriving/home_night have no exit timer) cannot be booked as premature. The release dict is snapshotted per room at each tracker pass, because the shadow pops it on re-arm (`:1566`). An entry seen on any pass during the episode is kept in the episode record.
2. **`L` released.** Closes `released`, with `ended_at` = the earliest `_hvac_shadow_release_at` of the `legacy_rooms`, else the pass time.
3. **The kind flips.** Closes `flipped`.
4. **The house state changes, or the zone is removed.** Closes `interrupted`, recorded under the OLD state.

`duration_s` = `ended_at − started_at`. An episode shorter than `HVAC_EVIDENCE_SHADOW_MIN_EPISODE_S` writes no row.

**Episode fields**, each the union over the whole episode (F8):
- `legacy_rooms`;
- `resumed_rooms`;
- `refresh_failed_rooms` (`refresh_ok is False` on any pass);
- `pending_rooms` (rooms with `_hvac_pending` True on any pass; evidence states only).

**Restart (F9).** Open episodes are RAM-only and are lost. That biases against long episodes, which are exactly the decision-relevant ones. Accepted: phase 1 measures a rate, and the bias is the same in both arms because restarts do not depend on house state. The row cap (`_ev_shadow_rows_today`) is RAM-only, so a restart resets it. Accepted: at worst it allows one extra day's cap per restart.

**Consumers.** The table (D3) and the §7 query. Nothing in HA reads the table.

### 3.3 Exclusions applied symmetrically (F8, F9)

| Bias | Arm affected | Handling |
|---|---|---|
| D5 pending spell (W up to 15 min, `number.py:446-447`). The evidence side is held empty while legacy is armed, which reads as `less → resumed` | reference (evidence states) | Rows carry `pending_rooms`. §7 excludes any episode with a non-empty `pending_rooms` in BOTH arms. The candidate arm never has one, because D5 runs only in evidence states, so the filter is a no-op there and the arms are treated alike |
| D5 omitted from `ev_shadow` | candidate | D5 only delays ARMING. The shadow evidence side can be MORE occupied at an entry edge, never later at a release. It affects `more` counts only |
| Refresh-fail hold omitted | candidate | §7 excludes episodes with a non-empty `refresh_failed_rooms` from every count, in both arms |
| Boot transients (`last_evidence` None, shadow re-arming) | both | No episode opens and no exposure accrues for `HVAC_EVIDENCE_SHADOW_BOOT_EXCLUDE_S` after the ZoneManager's first pass. The row also carries `opened_s_after_boot`, so the query can widen the window |

## 4. Emission and decision sites

| # | Site | Change |
|---|---|---|
| E1 | `_evidence_rule_output`, before `if rule == "legacy"` (`hvac_zones.py:1634`) | Only when `HVAC_EVIDENCE_SHADOW_ENABLED`: write `_hvac_ev_shadow_out[room]` (helper), `_hvac_legacy_shadow_out[room] = shadow_out`, and add the room to `_ev_shadow_pass_rooms`. Lines `:1631-1747` are not edited |
| E2 | `update_room_conditions` top (`:930`) | clear `_ev_shadow_pass_rooms` |
| E3 | `update_room_conditions`, after the zone rollup | the tracker (D2), per processed zone, inside `try/except Exception` with one DEBUG log |
| E4 | `reset_daily_counters` (`:2725`) | queue the exposure rows; clear `_ev_shadow_expo` and `_ev_shadow_rows_today` |
| E5 | zone removal / rediscovery | close the episode `interrupted` (row queued); drop the zone's exposure without a row |
| E6 | `HVACCoordinator`: one drain call after each `update_room_conditions` caller (`hvac.py:1581` boot, `:2334` tick, `:5959` fast run) | `drain_shadow_rows()` hands the queued rows to the DB, fire-and-forget (D3). A missed caller only delays rows to the next drain, and is pinned by a test |
| E7 | `_compute_hvac_occupied` `apply_evidence_rule=False` path (`:1577-1580`) | NO change. Such rooms never enter `_ev_shadow_pass_rooms` |

The builder re-runs `grep -n "_hvac_output\[\|_hvac_rule\[\|_hvac_day_release_at\[" domain_coordinators/hvac_zones.py` before and after the change; the counts must be unchanged. The golden is the real oracle.

## 5. Deliverables

### D0: pre-build golden (F10)
Before any production edit, on the current `develop` source, add a replay fixture. It drives `ZoneManager.update_room_conditions` (the real producer, fake room coordinators) through every house state, including:
- a hallway re-type;
- a coordinator-absent room;
- a refresh failure;
- a D5 away edge with W = 5 min;
- a `zone_ids` fast run;
- a restart re-seed.

Snapshot every INV-SHADOW item per pass and commit it as `quality/tests/golden/hvac_evidence_shadow_inv.json`, with the capture commit recorded in the file.

**Acceptance criteria**
- **Verify:** the golden is committed in its own commit, before the first production edit (`git log --follow` order).
- **Test:** `test_hvac_evidence_shadow.py::test_inv_shadow_golden_const_on` and `::test_inv_shadow_golden_const_off` both equal the golden.
- **Mutation (review C):**
  - an edit inside `:1650-1660` → both tests fail;
  - the helper writing `_hvac_day_release_at` → `_on` fails.

### D1: shadow terms before the early return
Implement E1 and E2.

**Acceptance criteria**
- **Verify:** guest state, bedroom (hold 240), last evidence 200 s old → `_hvac_ev_shadow_out` True; at 250 s → False while `_hvac_legacy_shadow_out` stays True (tail).
- **Verify:** evidence state → `_hvac_legacy_shadow_out[room]` equals the shadow's output, and differs from `_hvac_output` when the evidence hold has expired inside the legacy tail.
- **Test:**
  - `::test_shadow_term_matches_evidence_rule_in_evidence_states` (200 random tuples, `refresh_ok` True, W = 0);
  - `::test_shadow_term_computed_in_legacy_states`;
  - `::test_legacy_shadow_dict_in_evidence_states`.

### D2: zone tracker and exposure
Implement E3 to E5 per §3.2 and §3.3.

**Acceptance criteria**
- **Verify:** guest state, one bedroom. Evidence stops at t0, the legacy tail holds to t0+600, evidence returns at t0+420 → `less / resumed`, `duration_s` ≈ 180.
- **Verify (F2):** legacy releases at t0+300, the person re-enters at t0+360, and the next pass is a fast ENTRY run → `released`, with `ended_at` = t0+300. Under the rev-1 rule the same input gives `resumed`, so the test discriminates.
- **Verify (F6):**
  - a room re-typed to hallway mid-episode drops out of both sides that pass;
  - a coordinator-absent room's previous True is not read.
- **Verify:**
  - a house-state change closes the episode `interrupted` under the old state;
  - a fast run on zone 2 leaves zone 1's episode and exposure untouched;
  - a lighting-only hallway occupant does not open or close an episode.
- **Verify (F1):** one zone legacy-occupied for exactly 2 h in guest → that zone's exposure row reads 7200 ± one pass. A gap of 3 × tick between passes adds at most 2 × tick.
- **Verify (F9):** no episode opens and no exposure accrues inside the boot window.
- **Test:**
  - `::test_episode_resumed`, `::test_unobserved_release_then_reentry_is_released`;
  - `::test_hallway_retype_mid_episode`, `::test_absent_room_not_read`;
  - `::test_episode_interrupted_on_state_change`, `::test_fast_run_zone_filter_isolated`;
  - `::test_exposure_seconds_and_gap_cap`, `::test_boot_window_excluded`;
  - `::test_pending_and_refresh_rooms_are_episode_unions`;
  - `::test_tracker_exception_does_not_raise`.

### D3: the table, the write, the prune (F3, F4, F11)

DDL, created in `database.py` beside `optimizer_shadow_samples`, via `_create_table_safe`:

```sql
CREATE TABLE IF NOT EXISTS hvac_evidence_shadow (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL,          -- UTC ISO, row write time
  row_type TEXT NOT NULL,           -- 'episode' | 'exposure' | 'capped'
  zone_id TEXT NOT NULL,            -- HVAC zone id (thermostat-keyed)
  house_state TEXT NOT NULL,
  rule TEXT,                        -- evidence | night | legacy
  kind TEXT,                        -- less | more (episode)
  outcome TEXT,                     -- resumed | released | flipped | interrupted
  started_at TEXT, ended_at TEXT,
  duration_s REAL,                  -- episode length, or exposure seconds
  opened_s_after_boot REAL,
  details_json TEXT                 -- room lists (legacy/resumed/refresh_failed/pending), grace_s_at_close
);
CREATE INDEX IF NOT EXISTS idx_hvac_ev_shadow_ts ON hvac_evidence_shadow(timestamp);
```

The columns used by §7 are typed. Only the room lists go into JSON. There is no 2 KB truncation path: the builder caps each list at 20 names.

**Write.**
- `ZoneManager` queues row dicts (`_ev_shadow_pending_rows`, the degraded-events pattern).
- `HVACCoordinator` drains them (E6) and calls a new `database.log_hvac_evidence_shadow(rows)`. One connection and ONE `executemany` per drain, batched, never per row.
- The call is scheduled fire-and-forget with the `climate_write` coroutine duck-check (`hvac_setpoint.py:301-306`). It never awaits on the producer path.
- No database (`hass.data[DOMAIN].get("database")` is None) → rows are dropped, with one DEBUG log.
- Write-queue routing: if `database` writes go through `_write_queue` on this branch, use it. Either way it is one task per drain.

**Cap.** After `HVAC_EVIDENCE_SHADOW_MAX_ROWS_PER_ZONE_DAY` episode rows for a zone in a local day, queue one `row_type='capped'` row and stop that zone's episode rows until reset. Exposure rows are not capped.

**Prune.**
- `prune_hvac_evidence_shadow(window_days=HVAC_EVIDENCE_SHADOW_RETENTION_DAYS)` uses the batched-DELETE shape of `prune_optimizer_shadow_samples` (`database.py:7636`).
- It is registered in `nightly_maintenance.py` beside `:56`.
- This is the discharge (Suppression-needs-discharge). Nothing is retained forever.

**Orphans.**
- The zone-delete purge (`database.py:9986`) is keyed by HOUSE-zone NAME. These rows are keyed by HVAC `zone_id`, and one HVAC zone fans out to several house zones (State of Play §1; House zones ≠ HVAC zones). So a house-zone delete is the wrong scope to purge them, and the plan adds no delete-time purge.
- Orphans of a removed thermostat age out under the same retention knob, which is the knob for that purge. A delete-time purge keyed by HVAC zone is parked (§9).

**Acceptance criteria**
- **Verify:** schema is created on a fresh DB and on an existing DB (idempotent); no other table changes.
- **Verify:** one drain of 5 rows → one connection, one `executemany` (spy).
- **Verify:** `prune_hvac_evidence_shadow` deletes a row older than retention and keeps a newer one, against the real DDL extracted from `database.py` (no hand-copied DDL).
- **Verify:** no `ura_activity_log` row, no `SIGNAL_ACTIVITY_LOGGED`, no `ura_action` event per shadow write (`URALastActivitySensor` state unchanged).
- **Test:**
  - `::test_table_created_idempotent`, `::test_drain_batches_one_executemany`;
  - `::test_prune_window`, `::test_no_activity_log_or_signal`;
  - `::test_row_cap_per_zone_day`, `::test_no_database_drops_quietly`;
  - `::test_every_update_room_conditions_caller_drains` (the three `hvac.py` callers).
- **Live (F12):**
  - Within 24 h of restart, `SELECT row_type, rule, COUNT(*) FROM hvac_evidence_shadow GROUP BY 1,2` shows `episode` rows with `rule='night'` and `rule='evidence'`, and `exposure` rows after the first local midnight.
  - For one `less` episode in an EVIDENCE state (the decided side is the evidence side there), `started_at` matches within one pass the recorder flip of `sensor.ura_hvac_coordinator_zone_N_status` attribute `any_room_hvac_occupied` to false. Under a wrong build that reads the lighting denomination, the two disagree by about one occupancy timeout (~300 s), so the check discriminates.

### D4: containment
- `::test_shadow_dicts_have_one_reader`: AST lint. The seven dicts are read only by E1, the tracker, the drain and `reset_daily_counters`.
- `::test_hvac_occupied_diag_keys_unchanged`.
- `::test_no_await_in_tracker`: the tracker and queue functions are sync.

### D5: the §7 query as a tested artifact (F7)
Put the query in `scripts/probes/hvac_evidence_shadow_verdict.sql`, with a runner `scripts/probes/hvac_evidence_shadow_verdict.py` (`--since`, `--grace`, `--boot-exclude`).

**Test:** `::test_verdict_query_branches` builds an in-memory DB from the real DDL with synthetic rows covering:
- a SAFE state with zero episode rows;
- NOT SAFE;
- INSUFFICIENT on exposure;
- a reference state with no episode rows;
- a zero reference rate with 1, 2 and 3 premature events;
- rows excluded by `pending_rooms` / `refresh_failed_rooms` / the boot window.

It asserts each verdict.

## 6. Knobs, volume and write cost

| Knob (`hvac_const.py`) | Rung | Default | Why | Kill semantics |
|---|---|---|---|---|
| `HVAC_EVIDENCE_SHADOW_ENABLED` | 1 | `True` | Display-only recorder; a live switch would add entity/restore/READY surface for a value turned at most once | `False` = no helper call, no dict writes, no rows. Equal to the golden |
| `HVAC_EVIDENCE_SHADOW_MIN_EPISODE_S` | 1 | `60` | Below a minute is pass jitter; anything below the 300 s grace keeps every decision-relevant episode | `0` = record all |
| `HVAC_EVIDENCE_SHADOW_MAX_ROWS_PER_ZONE_DAY` | 1 | `96` | Write-flood guard (2026-06-09 incident); about 10x the expected rate | lower = earlier cap |
| `HVAC_EVIDENCE_SHADOW_RETENTION_DAYS` | 1 | `180` | Must outlast the wait for the next guest stay. It is also the orphan purge for removed thermostats | larger = keep longer; `0` = invalid, clamped to 1 |
| `HVAC_EVIDENCE_SHADOW_BOOT_EXCLUDE_S` | 1 | `600` | Covers the first-evidence gap after restart and shadow re-arming; 2 ticks | `0` = no exclusion (the query can still filter on `opened_s_after_boot`) |

The §7 analysis parameters are NOT runtime knobs: `:grace`, the 30 legacy-occupied zone-hour floor, the 1.5x ratio, the absolute floor and the 3-event minimum. They are stated in the runner's `--help`.

**Volume.**
- Episodes: up to about 0.5 per legacy-occupied zone-hour with the 60 s floor, so ≤ ~36/day across 3 zones and all states.
- Exposure: ≤ 3 zones × ~6 states = 18/day.
- Total ≤ ~54/day ≈ 20k/yr. At 180-day retention that is ≤ ~10k live rows of about 300 bytes, about 3 MB.
- This is why the rows do not go in the retained activity list (`const.py:5434` budget ≤ 1k/yr, dedicated table above 5k/yr).

**Write cost.**
- One batched write per drain that has rows. Most passes have none; a typical day has tens.
- The producer adds O(rooms) arithmetic per pass and no I/O.
- The nightly prune is batched.

## 7. The query that settles each state (F1, F7, F13)

The SQL below is the content of `hvac_evidence_shadow_verdict.sql`. Parameters:
- `:since` = D3 live date;
- `:grace` = live knob 48 in seconds (re-read before running);
- `:boot` = 600;
- `:floor_h` = 30;
- `:ratio` = 1.5;
- `:abs_floor` = 0.02 premature per legacy-occupied zone-hour (an absolute bar so a zero reference rate cannot turn one event into NOT SAFE, nor make SAFE unreachable).

```sql
WITH ep AS (
  SELECT house_state AS st, kind, outcome, duration_s AS dur
  FROM hvac_evidence_shadow
  WHERE row_type = 'episode' AND timestamp >= :since
    AND COALESCE(opened_s_after_boot, 1e9) >= :boot
    AND COALESCE(json_array_length(json_extract(details_json,'$.refresh_failed_rooms')),0) = 0
    AND COALESCE(json_array_length(json_extract(details_json,'$.pending_rooms')),0) = 0
),
expo AS (
  SELECT house_state AS st, SUM(duration_s) / 3600.0 AS occ_zone_h
  FROM hvac_evidence_shadow
  WHERE row_type = 'exposure' AND timestamp >= :since
  GROUP BY house_state
),
agg AS (
  SELECT st,
         SUM(kind='less' AND dur >= :grace)                       AS eligible,
         SUM(kind='less' AND dur >= :grace AND outcome='resumed') AS premature,
         SUM(kind='less' AND dur >= :grace AND outcome='released') AS saved,
         SUM(CASE WHEN kind='less' THEN dur ELSE 0 END) / 3600.0  AS less_h,
         SUM(kind='more')                                         AS more_eps
  FROM ep GROUP BY st
),
j AS (
  SELECT e.st, e.occ_zone_h,
         COALESCE(a.eligible,0) AS eligible, COALESCE(a.premature,0) AS premature,
         COALESCE(a.saved,0) AS saved, COALESCE(a.less_h,0) AS less_h,
         COALESCE(a.more_eps,0) AS more_eps
  FROM expo e LEFT JOIN agg a USING (st)
),
ref AS (
  SELECT SUM(premature) * 1.0 / NULLIF(SUM(occ_zone_h),0) AS ref_rate,
         SUM(occ_zone_h) AS ref_h
  FROM j WHERE st IN ('home_day','home_evening')
)
SELECT j.st, ROUND(j.occ_zone_h,1) AS occ_zone_h, j.eligible, j.premature, j.saved,
       ROUND(j.less_h,2) AS less_h, j.more_eps,
       ROUND(j.premature / j.occ_zone_h, 4) AS rate,
       ROUND(r.ref_rate, 4) AS ref_rate,
       ROUND(MAX(:ratio * COALESCE(r.ref_rate,0), :abs_floor), 4) AS bar,
       CASE
         WHEN j.st IN ('home_day','home_evening') THEN 'REFERENCE'
         WHEN COALESCE(r.ref_h,0) < :floor_h THEN 'INSUFFICIENT (reference)'
         WHEN j.occ_zone_h < :floor_h THEN 'INSUFFICIENT'
         WHEN j.premature / j.occ_zone_h <= MAX(:ratio * COALESCE(r.ref_rate,0), :abs_floor) THEN 'SAFE'
         WHEN j.premature >= 3 THEN 'NOT SAFE'
         ELSE 'INSUFFICIENT'
       END AS verdict
FROM j CROSS JOIN ref r
ORDER BY j.st;
```

**Rule in words.** A state is SAFE when it has at least 30 legacy-occupied zone-hours, and its premature rate is no worse than the larger of 1.5x the in-system home_day/home_evening rate and an absolute 0.02 per occupied zone-hour. It is NOT SAFE when it is above that bar with at least 3 premature events. Otherwise it is INSUFFICIENT.

A state with exposure but zero episode rows reads SAFE once it clears the floor. A missing or thin reference reads INSUFFICIENT (reference).

The exposure comes from in-system legacy-occupied seconds, so the `× 3` literal and the `house_state_log` time-zone and seeding issues are gone (F1, F13).

**Guest caveat.** For guest, also list `json_extract(details_json,'$.resumed_rooms')` on `resumed` rows, and read whether the events are in the guest rooms.

## 8. Tier classification

**Tier 2-DB.** Rev 2 adds a table (DDL in `database.py`) and a new DAO write and prune. That meets the CLAUDE.md Tier 2-DB triggers. Actuation is not touched, but the code sits inside the HVAC occupancy producer that every retreat decision reads.

The build gets three framing-disjoint reviews:
- **A:** data integrity and DB. DDL idempotence, batched write, prune, no effect on existing tables or readers.
- **B:** INV-SHADOW and lifecycle. Golden diff, boot window, `zone_ids` fast runs, drain at all three callers, exceptions, restart.
- **C:** test authority via per-site mutation (D0, D4), and the D5 query fixture.

Then live validation and the README write-back. Not Tier 3: no value threads into a decision site.

## 9. Non-goals and parked items

- No change to `HVAC_EVIDENCE_RULE_STATES` or to any actuation. Promotion is phase 2.
- No entity, attribute, switch, config field, signal, bus event or activity-log row. No key added to `hvac_occupied_diag`.
- D5 and the refresh-fail hold are not modelled in the shadow. They are handled by exclusion (§3.3).
- Open episodes and partial-day exposure are not persisted across restart.
- No recorder backfill. No anomaly or NM trip-wire.
- **Parked:** a live rung-3 recorder switch. Revive if a `capped` row appears, or if the operator wants to toggle it without a deploy.
- **Parked:** a delete-time purge keyed by HVAC `zone_id`. Revive if thermostat removal becomes routine (multi-home rollout).
- **Simplest-version check:** a daily counter cannot carry outcome or release timing, and it dies with the 8-day recorder. The episode row plus the exposure row is the smallest thing that settles "premature or not, per occupied hour".

## 10. Same-commit doc fix (State of Play §2), done in `60b423a1`
- The tick is at `hvac.py:1692-1695`.
- The fast path SHIPPED in v5.103.20.
- Recorded as C39. Rev 2 makes no further State of Play change. The build commit adds the shadow recorder to §3.1 and §4.3 of State of Play.

## 11. Plan completion accounting
The builder lists any of D0 to D5 not done, with the reason and the card. The README carries the D3 Live rows and the post-restart validation table.

## 12. Rev 2 changelog: review finding → fix

| Finding | Sev | Fix in rev 2 | Where |
|---|---|---|---|
| F1 wrong exposure denominator | HIGH | In-system legacy-occupied seconds per (zone, state), with daily `exposure` rows; the query divides by them; `× 3` removed | §3.2 Exposure, D2, §7 |
| F2 unobserved release → false `resumed` | HIGH | Close classification uses `_hvac_shadow_release_at` (snapshotted per pass, earliest release); test with a re-entry inside one tick | §3.2 close (1)(2), D2 |
| F3 ActivityLogger side-effects | MED | No `ActivityLogger`, no `ura_activity_log`. Direct DB write in the `climate_write` style, into a dedicated table; no signal/bus event; no 2 KB truncation (typed columns, capped lists). The boot-seed residual of the Last Activity sensor no longer applies (no activity rows) | §1.1, D3 |
| F4 retention forever / budget / orphans | MED | Dedicated table chosen by the `const.py:5434` rule (≈20k/yr > 5k/yr); batched nightly prune at `HVAC_EVIDENCE_SHADOW_RETENTION_DAYS` = 180; orphans age out under that knob (house-zone purge is wrong scope) | §1.1, D3, §6 |
| F5 missing fourth dict | MED | `_hvac_legacy_shadow_out` named; all seven dicts listed in §1.2, INV-SHADOW and the D4 lint | §1.2, §2, §3.1, D4 |
| F6 stale room entries | MED | Per-pass `_ev_shadow_pass_rooms`; the tracker reads only those; hallway-retype and absent-room tests | §3.1, E2, D2 |
| F7 §7 SQL mislabels | MED | `expo LEFT JOIN agg` with COALESCE; `ref` from the joined exposure; absolute floor `:abs_floor` beside the ratio; exclusions applied uniformly in `ep`; fixture test per branch | §7, D5 |
| F8 D5 reverse bias + refresh union | MED | `pending_rooms` recorded and excluded in both arms; all room lists are episode unions | §3.2, §3.3, §7 |
| F9 restart effects | MED | Boot window `HVAC_EVIDENCE_SHADOW_BOOT_EXCLUDE_S` = 600 s (no open, no exposure) + `opened_s_after_boot` column; length bias and RAM cap reset stated and accepted | §3.2, §3.3, §6 |
| F10 weak oracle | MED | D0 golden on pre-build source, committed first; const on AND off both diffed against it | §2, D0 |
| F11 logger handle | LOW | Queue then drain (degraded-events pattern); drain at all three `update_room_conditions` callers including the fast run, pinned by a test | E6, D3 |
| F12 non-discriminating Live | LOW | Live criterion tied to the recorder flip of the zone's decided side vs the lighting denomination | D3 Live |
| F13 `house_state_log` tz / seeding | LOW | `house_state_log` no longer used; exposure intervals capped at 2 ticks so HA-down time is not exposure | §3.2, §7 |

### Where this revision disagrees with or narrows the review
- **F4 "zone-id purge".** The review suggests fixing the zone-delete key. The existing purge is keyed by HOUSE-zone name, and an HVAC zone maps to several house zones, so wiring these rows into it is a scope error. Rev 2 uses the retention knob as the purge, and parks a thermostat-keyed purge.
- **F3 "write through `database.log_activity` directly".** Applied as "direct DB write in the `climate_write` style", but into the dedicated table F4 implies, not `ura_activity_log`. Writing activity rows directly would still feed `get_recent_activities` and the Last Activity boot seed.
- **F9 length bias.** Accepted, not mitigated. It acts on both arms equally (restarts do not depend on house state), so the ratio test is unbiased to first order. Persisting episodes would add a restore path to a diagnostic and is not worth it.
