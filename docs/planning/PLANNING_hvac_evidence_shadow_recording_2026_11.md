# PLANNING: HVAC evidence-rule shadow recording (display only)

**Card:** HVAC-GUEST-EVIDENCE-RULE-1, phase 1. **Operator approval:** 2026-11-10, "HVAC recording ok".
**Tier:** 2, with one adversarial plan review before build (see §8).
**Source audit:** `docs/planning/AUDIT_guest_onset_thresholds_and_hvac_evidence_states_2026_11_10.md` Part 2 (§2.5 item 1 is this plan).

## 0. Goal and shape

In every house state OUTSIDE `HVAC_EVIDENCE_RULE_STATES` (`hvac_const.py:1097`, `("home_day","home_evening")`), compute what the evidence rule WOULD decide for each room, roll it up per zone, and record each zone-level divergence against the decision HVAC actually used. Change no actuation. After the next guest stay, one SQL query (§7) labels each state SAFE / NOT SAFE / INSUFFICIENT.

The evidence states are recorded too, as the reference arm. There the evidence rule is live and the legacy shadow is the counterfactual, so the same row shape gives the home_day baseline that the other states are compared against, measured in-system and not reconstructed (the audit's model error was 4.3 % / 2.0 %, §2.2).

One new behaviour: rows in `ura_activity_log` with `action = 'hvac_evidence_shadow'`. No new table, entity, attribute, signal or config field.

## 1. Institutional context verified

**Read completely:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (all 727 lines, 2026-11-10; §2 drift fixed in the same commit, see §10). The audit above (all 169 lines). Presence is not touched: the plan reads the room evidence stamp HVAC already reads; it changes no presence producer.

**Prior planning docs:** `PLANNING_hvac_fast_occupancy_response.md` (REV 7; defines the evidence rule, INV-5 "shadow untouched", D5), `AUDIT_hvac_raw_evidence_gaps_2026_09_26.md` (the measurement behind the two evidence states), `AUDIT_exit_evidenced_vacancy_probe.md` (skimmed header, no overlap), `PLANNING_baec_config_flow_and_shadow_eval.md` (energy shadow, different domain; not reusable).

### 1.1 Prior-art scan of shadow and diagnostic surfaces (hvac_zones.py, hvac.py, DB)

| Surface | Site | What it holds | Verdict |
|---|---|---|---|
| Legacy shadow machine `_shadow_hvac_occupied` | `hvac_zones.py:2133`, called `:1561` on every pass in every state | the v5.103.19 output, `_hvac_armed` / `_hvac_tail_until` | **REUSED** as the legacy side in evidence states. Already runs everywhere; nothing added to it |
| `_hvac_last_ev` / `_hvac_last_active` | written `hvac_zones.py:1632-1633` BEFORE the early return | last evidence time + active flag, every state | **REUSED** as the evidence-rule inputs in legacy states |
| `_evidence_hold_seconds` | `hvac_zones.py` (called `:1650`) | per-room-type evidence hold | **REUSED**, called read-only for the shadow term |
| Legacy early return | `hvac_zones.py:1634-1647` (`if rule == "legacy": ... return shadow_out`) | ends the function before `ev_out` exists | **The blocker.** The shadow term is computed before it (D1) |
| Night rule `ev_out` | `hvac_zones.py:1659-1660`, OR-ed at `:1696` | evidence term in sleep/waking | **REUSED**: captured before the OR |
| `hvac_occupied_diag` | `hvac_zones.py:2685` → `binary_sensor.py:959-968` attrs | per-room diagnostic incl. `shadow_armed`/`shadow_source` | **NOT extended.** Any key added here publishes on ~43 recorded entities (recorder churn, see State of Play header 2026-10-20). Non-goal |
| Zone status attrs (`transit_filtered_today`, `pending_hold_s_today`) | `hvac_zones.py:1190-1212` | daily counters on `sensor.ura_hvac_coordinator_zone_{n}_status` | **NOT used.** Recorder keeps 8 days (audit §2.1); a guest stay plus the decision delay can exceed that. A counter also loses the per-episode outcome |
| `ura_activity_log` | DDL `database.py:1719-1735`; writer `ActivityLogger.log` (`activity_logger.py:63`) → `database.log_activity` `database.py:6925`; prune `database.py:6962` (info 7 d, notable 30 d, retained-actions exempt) | free-form `details_json`, zone, importance | **REUSED.** HVAC already writes episode rows here (`pending_hold_capped` `hvac.py:5540-5575`, same pattern) |
| `ACTIVITY_LEDGER_RETAINED_ACTIONS` | `const.py:5440` | actions never pruned | **REUSED** (one entry added, D3) |
| `house_state_log` | DDL `database.py:1494`; never pruned (no `DELETE FROM house_state_log`) | state transitions | **REUSED** as the exposure denominator in the query |
| `decision_log` | `database.py:1148` | coordinator decisions with action_json | rejected: a decision row per divergence would read as an actuation in every consumer of decision_log |
| `optimizer_shadow_samples` | `database.py:1343` | optimizer `(dimension, target_id, matched)` | rejected: no duration / outcome / house state; owned by the optimizer |

### 1.2 Per-addition REUSED / NEW

| Addition | Verdict | Grep |
|---|---|---|
| Action `hvac_evidence_shadow` (+ `hvac_evidence_shadow_capped`) | NEW action name in an existing table | `grep -rn "evidence_shadow\|shadow_divergen" custom_components docs/planning` → 0 hits |
| `HVAC_EVIDENCE_SHADOW_ENABLED` (kill switch) | NEW const | `grep -n "SHADOW" domain_coordinators/hvac_const.py const.py` → no HVAC-occupancy shadow const |
| `HVAC_EVIDENCE_SHADOW_MIN_EPISODE_S` | NEW const | no episode-length floor for occupancy rows exists |
| `HVAC_EVIDENCE_SHADOW_MAX_ROWS_PER_ZONE_DAY` | NEW const | no per-zone row cap exists in HVAC ledger code |
| Room dict `_hvac_ev_shadow_out`, zone dict `_ev_shadow_ep`, `_ev_shadow_rows_today` | NEW RAM state on `ZoneManager` | the existing dicts listed `hvac_zones.py:339-375` all feed live decisions; none may be reused (invariant §2) |
| Exposure denominator | REUSED `house_state_log` | — |

## 2. Falsifiable invariant (byte-identical actuation)

**INV-SHADOW.** For any sequence of producer inputs (room data, evidence stamps, refresh results, house states, zone_ids filters, entry-dwell / return-window values), in ANY house state, the following are identical with `HVAC_EVIDENCE_SHADOW_ENABLED = True` and `False`:
- every `RoomCondition.hvac_occupied` and `zone.any_room_hvac_occupied`;
- every pre-existing `ZoneManager` dict the producer writes: `_hvac_output`, `_hvac_rule`, `_hvac_day_release_at`, `_hvac_ev_released_at`, `_hvac_pending`, `_hvac_cold`, `_hvac_exempt_reason`, `_hvac_arm_onset`, `_hvac_ep_armed`, `_hvac_armed_at`, `_hvac_arm_class`, `_hvac_arm_span_s`, episode dicts, `transit_filtered_today`, and the shadow machine's `_hvac_armed` / `_hvac_tail_until` / `_hvac_arm_source` / `_hvac_shadow_release_at`;
- `zone.last_occupied_time`, `continuous_occupied_since`, `zone_release_at`, `room_release_at`, exit-timer arming, and every S1 / row-1 / D6 / D7 / sweep decision and `climate_write` row.

The ONLY differences are the three new dicts of §1.2 and `ura_activity_log` rows whose action is `hvac_evidence_shadow` or `hvac_evidence_shadow_capped`.

**How to break it (what D-style review should try):** the shadow term writes `_hvac_day_release_at` (the live code at `:1653` does, and a copy-paste would too; `zone_release_at` reads it); the shadow term calls `_d5_update` (writes D5 dicts and `transit_filtered_today`); the shadow is computed AFTER the early return mutates state; a recorder exception propagates out of `update_room_conditions`; the new zone loop runs before the rollup and reads a partly-built `room_conditions`.

## 3. Producer and consumer checks

### 3.1 Value 1: room shadow evidence output `ev_shadow(room)`

**Producer.** `active' OR (last_ev is not None AND now < last_ev + hold_ev)`, where `active' = evidence_active if refresh_ok is not False else False` and `hold_ev = _evidence_hold_seconds(room_type, override_day)`. This is the evidence rule's own term, `hvac_zones.py:1650-1660`, WITHOUT:
- the refresh-failure hold (`:1661-1669`, evidence-only by design; in a legacy state a failed refresh makes the shadow read empty after the hold, which records a "less" episode a live evidence rule would have bridged for up to `HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S`). The row carries `refresh_failed_rooms` so the query can drop them;
- D5 (`:1672-1693`). D5 only delays ARMING after an away edge; it cannot make a room read occupied later than its evidence hold, so leaving it out can only make the shadow MORE occupied at entry, never change a release. Recorded as a known bias (fewer "more" episodes), irrelevant to the unsafe "less → resumed" signal.

Dependencies and health: `last_evidence` comes from the room coordinator's one stamp `_stamp_hvac_evidence` (State of Play §3.1), live in all states since v5.103.20; `_read_room_evidence` already runs for every room every pass (`update_room_conditions` passes it in). Hallways are filtered upstream (`hvac_zones.py:650-665`) and never reach the function; a coordinator-absent room gets a synthetic `RoomCondition` (`:616-641`) and also never reaches it, so it contributes False to both sides.

In evidence states `ev_shadow(room)` equals the live output minus D5 and minus the refresh-fail hold; the recorder uses the LIVE output `_hvac_output[room]` there (it is the decision), and the legacy shadow `shadow_out` as the counterfactual.

**Consumers.** Exactly one: the zone episode tracker (D2). Display/diagnostic only. No trust decision reads it. Pinned by a lint test (D4).

### 3.2 Value 2: zone episode (per zone, per pass)

**Producer.** After the zone's rollup in `update_room_conditions` (after the `zone.any_room_hvac_occupied` block, `hvac_zones.py:1096-1110`):
- `decided = zone.any_room_hvac_occupied` (what HVAC used).
- `counterfactual`: legacy and night states → OR of `ev_shadow` over the zone's processed rooms; evidence states → OR of `shadow_out` (legacy machine) over the same rooms.
- `kind`: `less` when the evidence side is empty and the legacy side occupied, `more` for the reverse. In legacy/night states the evidence side is the counterfactual; in evidence states it is the decision.

An episode opens on the first pass with a divergence and closes on the first pass where:
- the evidence side becomes occupied again while legacy is still occupied → `outcome = resumed` (the evidence rule would have let the zone go and a person was still there: the CRIT-1 failure; it is premature only if `duration_s ≥ grace`, applied in the query);
- the legacy side releases too → `released` (the evidence rule only saved lag);
- the `kind` flips (rare; closes as `flipped`);
- the house state changes, or the zone is removed → `interrupted`.

`duration_s` = close pass time − open pass time. Resolution is the pass cadence: the 5-min tick, plus fast ENTRY runs, which run in EVERY house state (State of Play §2, ruling R7) and so catch the resumption pass within ~45 s of the room's evidence refresh. Exit timers run only in evidence/night states, so in guest/away/arriving/home_night a `released` close can lag up to one tick; this lengthens `released` episodes only, never turns one into `resumed`.

Restart: open episodes are RAM-only and are lost (not written). Accepted; bounded to one episode per zone per restart.

**Consumers.** The DB row (D3) and nothing else. Readers of `ura_activity_log` that would see it (checked):
- `sensor.py:17574` (per-coordinator count today) and `:18061` (last activity per coordinator) filter `coordinator IN (labels)`. Rows are written with `coordinator = "hvac_shadow"` so they do not change any HVAC activity count or "last HVAC action" display. Builder must verify the label lists at those two sites do not include `hvac_shadow`.
- `hvac.py:8234` reads only `action = 'preset_change'`. Unaffected.
- `database.get_recent_activities` (`database.py:7825`, unfiltered) and the `ura/logs/subscribe` websocket (`websocket_api.py:291`, via `SIGNAL_ACTIVITY_LOGGED`) WILL show the rows. Importance `info` keeps them below the notable feeds; accepted as diagnostic noise at ≤ ~40/day (§6).

## 4. Emission and decision sites (enumerated)

| # | Site | Change |
|---|---|---|
| E1 | `_evidence_rule_output`, before the `if rule == "legacy"` early return (`hvac_zones.py:1634`) | compute `ev_shadow` via a NEW pure helper and store it in `_hvac_ev_shadow_out[room]`; nothing else above or below changes |
| E2 | same function, night branch | store the existing local `ev_out` (captured after `:1669`, before `:1696`) into `_hvac_ev_shadow_out[room]` — or simply let E1's helper compute it for night too (preferred: one code path, the live `ev_out` stays untouched) |
| E3 | `_compute_hvac_occupied` `apply_evidence_rule=False` path (`:1577-1580`) | NO change: only direct legacy callers/tests; the producer always passes `apply_evidence_rule=True` (`:1067`). The tracker ignores rooms with no `_hvac_ev_shadow_out` entry this pass |
| E4 | `update_room_conditions`, after the zone rollup | the zone tracker (D2), only for zones processed in this pass (honours the `zone_ids` filter of fast runs) |
| E5 | daily counter reset `reset_daily_counters` (`hvac_zones.py:2725`) | clear `_ev_shadow_rows_today` |
| E6 | zone removal / rediscovery | drop `_ev_shadow_ep[zone_id]` without a row (or close `interrupted`, builder's choice; test pins it) |

Grep the builder must re-run: `grep -n "_hvac_output\[\|_hvac_rule\[\|_hvac_day_release_at\[" domain_coordinators/hvac_zones.py` before and after; the counts must not change.

## 5. Deliverables

### D1: shadow evidence term before the early return
A pure `@staticmethod _shadow_evidence_term(*, active, refresh_ok, last_evidence, hold_s, now) -> bool` in `hvac_zones.py`. Called at the top of `_evidence_rule_output` when `HVAC_EVIDENCE_SHADOW_ENABLED`, result into `_hvac_ev_shadow_out[room_name]`. The live lines `:1631-1747` are not edited.

**Acceptance criteria**
- **Verify:** in `guest`, a room whose last evidence is 200 s old, type bedroom (hold 240): `_hvac_ev_shadow_out[room] is True`; at 250 s it is False while `_hvac_output[room]` (legacy shadow, still in its tail) stays True.
- **Verify (discriminating):** with the const False, `_hvac_ev_shadow_out` is empty and every dict in INV-SHADOW is equal to the const-True run. Under a plausible wrong build (helper writes `_hvac_day_release_at`), the same comparison fails on `_hvac_day_release_at` in a legacy state, where today it is popped (`:1636`).
- **Test:** `test_hvac_evidence_shadow.py::test_shadow_term_matches_evidence_rule_in_evidence_states` (helper vs the live `ev_out` on 200 random input tuples with refresh_ok True and W = 0), `::test_shadow_term_computed_in_legacy_states`, `::test_inv_shadow_byte_identical_replay` (one producer replay over every house state, const on vs off, snapshot of every INV-SHADOW item).

### D2: zone divergence tracker
In `update_room_conditions` after the rollup, per processed zone, open/close episodes per §3.2. `MIN_EPISODE_S` filter: an episode shorter than `HVAC_EVIDENCE_SHADOW_MIN_EPISODE_S` is dropped with no row. The tracker body is wrapped in `try/except Exception` with one DEBUG log; it never raises into the producer.

**Acceptance criteria**
- **Verify:** guest state, zone with one bedroom: evidence stops at t0; legacy tail holds to t0+600; evidence returns at t0+420 → one row `kind=less outcome=resumed duration_s≈(420-240)`. Same but no return → `outcome=released`. A plausible wrong build that compares against `zone.any_room_occupied` (the lighting denomination) produces a different open time in a zone with a hallway occupant; the test includes one.
- **Verify:** a house-state change mid-episode closes it `interrupted`, with the OLD state in `house_state`.
- **Verify:** a zone-scoped fast run on zone 2 leaves zone 1's open episode untouched.
- **Test:** `::test_episode_resumed`, `::test_episode_released`, `::test_episode_interrupted_on_state_change`, `::test_fast_run_zone_filter_isolated`, `::test_tracker_exception_does_not_raise`, `::test_evidence_state_reference_arm_uses_legacy_shadow`.

### D3: the row
`ActivityLogger.log(coordinator="hvac_shadow", action="hvac_evidence_shadow", zone=zone_id, importance="info", description=f"{zone_name} {kind} {outcome} {duration_s}s in {house_state}", details={...})` via `hass.async_create_task`, as `_log_pending_hold_capped` does (`hvac.py:5557`). The ZoneManager has no logger handle today: pass the HVAC coordinator's `activity_logger` the same way `update_room_conditions` already receives callables (`away_edge_fn`), or resolve it from `hass.data[DOMAIN]` at write time; builder picks, test pins that a missing logger writes nothing and does not raise.

`details`: `kind`, `outcome`, `rule` (evidence / night / legacy), `house_state`, `started_at`, `ended_at` (ISO UTC), `duration_s`, `legacy_rooms` (rooms legacy-occupied at open), `resumed_rooms` (rooms whose evidence came back, `resumed` only), `refresh_failed_rooms`, `grace_s_at_close` (the live knob 48/49 value the HVAC coordinator holds, for the record; the query does not depend on it).

Retention: add `"hvac_evidence_shadow"` to `ACTIVITY_LEDGER_RETAINED_ACTIONS` (`const.py:5440`), because the decision waits for a guest stay of unknown date and info rows prune at 7 days. Phase 2 (the decision) removes the entry and the rows.

Cap: after `HVAC_EVIDENCE_SHADOW_MAX_ROWS_PER_ZONE_DAY` rows for a zone in one local day, write one `hvac_evidence_shadow_capped` row (importance `notable`) and stop writing for that zone until the daily reset.

Dedup: `ActivityLogger._should_log` keys on description (`activity_logger.py:182-194`, 30 s for info); the description includes duration and outcome, so two real episodes do not collide except by exact coincidence. Accepted.

**Acceptance criteria**
- **Verify:** the row lands with all `details` keys non-null where defined (sentinel check: `duration_s > 0`, `house_state` not null).
- **Verify:** `prune_activity_log` leaves a 40-day-old `hvac_evidence_shadow` row and deletes a 40-day-old `hvac_evidence_shadow_capped` row.
- **Verify:** the HVAC activity-count sensor (`sensor.py:17574` path) does not change when a shadow row is written.
- **Test:** `::test_row_shape`, `::test_row_cap_per_zone_day`, `::test_prune_retains_shadow_rows` (drives the real `prune_activity_log` against the real DDL), `::test_hvac_activity_count_excludes_shadow`.
- **Live:** within 24 h of restart, `SELECT COUNT(*), MIN(timestamp) FROM ura_activity_log WHERE action='hvac_evidence_shadow'` > 0, at least one row with `json_extract(details_json,'$.rule')='night'` (sleep happens daily) and one with `rule='evidence'`; `duration_s` > 0 on all rows. Sentinel-only rows (nulls) = payload broken.

### D4: containment tests
- `::test_shadow_dicts_have_one_reader`: AST/grep lint that `_hvac_ev_shadow_out` and `_ev_shadow_ep` are read only inside the tracker and `reset_daily_counters`.
- `::test_hvac_occupied_diag_keys_unchanged`: the key set of `hvac_occupied_diag` equals today's list (no recorder churn).
- Mutation drill for review C: delete the E1 call → the D1 legacy-state test fails; make the helper write `_hvac_day_release_at` → `test_inv_shadow_byte_identical_replay` fails.

## 6. Knobs, volume and write cost

| Knob | Rung | Default | Why this rung | Kill semantics |
|---|---|---|---|---|
| `HVAC_EVIDENCE_SHADOW_ENABLED` (`hvac_const.py`) | 1, module const | `True` | Display-only recorder with no actuation; a live switch would add an entity, restore and READY-landing surface for a value the operator turns at most once (marginal benefit fails, §9) | `False` = no helper call, no dict writes, no rows; byte-identical to today |
| `HVAC_EVIDENCE_SHADOW_MIN_EPISODE_S` | 1 | `60` | Below one minute a divergence is pass jitter; any value below the 300 s grace keeps every decision-relevant episode | `0` = record every divergence |
| `HVAC_EVIDENCE_SHADOW_MAX_ROWS_PER_ZONE_DAY` | 1 | `96` | Write-flood guard (Optimizer DB write-flood incident 2026-06-09): 96 = one row per 15 min per zone, ~10x the expected rate | lower = earlier cap |

**Expected volume.** The audit's proxy and Table B give divergence runs ≥ 300 s at 0.10-0.22 per zone-hour; with a 60 s floor assume up to ~0.5 per zone-hour. 3 zones × ~24 h × 0.5 ≈ **up to ~36 rows/day**, typically 15-25 (all states, incl. the home_day reference arm). Each row ≈ 400-600 bytes (details ≤ 2 KB cap). ~13k rows/year ≈ 6 MB if never cleaned; phase 2 deletes them.

**Write path cost.** `database.log_activity` opens one connection and commits per row (`database.py:6938-6960`); it does NOT go through the batched `_write_queue`. At ≤ 36 rows/day (≤ 1 per pass even in the worst case, 3 per tick at the cap of one per zone) that is far below any queue-pressure regime. The producer itself adds O(rooms) arithmetic per pass and no I/O; the DB write is a scheduled task off the producer path. If the builder finds `log_activity` routed through `_write_queue` on the current branch, the row count does not change this conclusion.

## 7. The query that settles each state

Run after the guest stay (via `ssh ha sqlite3` or MCP `ura-sqlite`). `:since` = when D3 went live; `:grace` = 300 (knob 48 live value; re-read before running).

```sql
WITH ep AS (
  SELECT json_extract(details_json,'$.house_state') AS st,
         json_extract(details_json,'$.kind')        AS kind,
         json_extract(details_json,'$.outcome')     AS outcome,
         json_extract(details_json,'$.duration_s')  AS dur,
         json_extract(details_json,'$.refresh_failed_rooms') AS rf
  FROM ura_activity_log
  WHERE action = 'hvac_evidence_shadow' AND timestamp >= :since
),
hs AS (
  SELECT state,
         (julianday(COALESCE(LEAD(timestamp) OVER (ORDER BY timestamp), datetime('now')))
          - julianday(timestamp)) * 24.0 AS h
  FROM house_state_log
  WHERE timestamp >= :since
),
expo AS (SELECT state AS st, SUM(h) * 3 AS zone_h FROM hs GROUP BY state),
agg AS (
  SELECT st,
         SUM(kind='less' AND dur >= :grace AND (rf IS NULL OR rf = '[]'))                         AS eligible,
         SUM(kind='less' AND dur >= :grace AND outcome='resumed' AND (rf IS NULL OR rf = '[]'))  AS premature,
         SUM(kind='less' AND dur >= :grace AND outcome='released')                               AS saved,
         ROUND(SUM(CASE WHEN kind='less' THEN dur ELSE 0 END) / 3600.0, 2)                       AS less_h,
         SUM(kind='more')                                                                        AS more_eps
  FROM ep GROUP BY st
),
ref AS (
  SELECT SUM(a.premature) * 1.0 / SUM(e.zone_h) AS ref_rate
  FROM agg a JOIN expo e USING (st) WHERE st IN ('home_day','home_evening')
)
SELECT e.st, ROUND(e.zone_h,1) AS zone_h, a.eligible, a.premature, a.saved, a.less_h, a.more_eps,
       ROUND(a.premature / e.zone_h, 4) AS premature_per_zone_h, ROUND(r.ref_rate, 4) AS ref_rate,
       CASE
         WHEN e.st IN ('home_day','home_evening') THEN 'REFERENCE'
         WHEN e.zone_h < 30 THEN 'INSUFFICIENT'
         WHEN a.premature >= 3 AND a.premature / e.zone_h > 1.5 * r.ref_rate THEN 'NOT SAFE'
         WHEN a.premature / e.zone_h <= 1.5 * r.ref_rate THEN 'SAFE'
         ELSE 'INSUFFICIENT'
       END AS verdict
FROM expo e LEFT JOIN agg a USING (st) CROSS JOIN ref r
ORDER BY e.st;
```

Decision rule in words: a state is SAFE when it has ≥ 30 zone-hours of exposure and its premature-retreat rate is no worse than 1.5x the home_day/home_evening rate measured by the same recorder over the same window; NOT SAFE with ≥ 3 premature events above that bar. The three numbers (30 zone-h, 1.5x, 3 events) are analysis parameters, not runtime knobs; the operator may change them at decision time. Guest exposure: the October stay had 18.7 h of guest house state (audit §2.3 proxy) = 56 zone-h, so one stay of that shape clears 30.

Caveat carried into the decision: the query is zone-level. A premature event in a guest room is in `resumed_rooms`; for guest, also run `SELECT json_extract(details_json,'$.resumed_rooms') ... WHERE outcome='resumed' AND st='guest'` and read the rooms.

## 8. Tier classification

**Tier 2** (operator asked for Tier 2; matches the trigger). No actuation change, but the code sits inside the HVAC occupancy producer that every retreat decision reads, so one missed write to a live dict (INV-SHADOW) is a real comfort regression. Not Tier 2-DB: no DDL, no DAO change, one new action string in an existing free-form table. Not Tier 3: no value threads into a decision site. Review: ONE adversarial plan review before build; build gets two framing-disjoint reviews (A: local correctness of the term + tracker; B: INV-SHADOW byte-identity + lifecycle: restart, zone_ids filter, exceptions, task scheduling) plus the C mutation drills in D4.

## 9. Non-goals and marginal-benefit notes

- No change to `HVAC_EVIDENCE_RULE_STATES` or any actuation. Promotion of a state is phase 2, a separate reviewed change.
- No new table, entity, sensor attribute, config field or switch. No key added to `hvac_occupied_diag`.
- No modelling of D5 or the refresh-fail hold in the shadow (§3.1 biases stated).
- No persistence of open episodes across restart.
- No backfill from the recorder (the audit already did that; 8-day retention).
- No anomaly / NM trip-wire on the shadow (it decides nothing).
- **Parked, with revival trigger:** a live rung-3 switch for the recorder. Revive if the cap row `hvac_evidence_shadow_capped` ever appears, or the operator asks to toggle recording without a deploy.
- **Simplest version check:** a per-state daily counter on the zone status sensor would be cheaper but cannot carry outcome or duration, and dies with the 8-day recorder window. The episode row is the smallest thing that answers "premature or not".

## 10. Same-commit doc fix (State of Play §2)

Verified against code 2026-11-10:
- The periodic tick is registered at `hvac.py:1692-1695` (`self._decision_timer_unsub = async_track_time_interval(..., HVAC_DECISION_TICK)`), not `:1356-1360`.
- The occupancy fast path SHIPPED in v5.103.20 (`_setup_fast_path_listeners` `hvac.py:5419`, called `:1519`; `_on_room_refresh` `:5823`; State of Play header "SHIPPED v5.103.20, validated 09-29"). The §2 bullet "DESIGNED, never built" is corrected and the old claim recorded as C39 in §10.

## 11. Plan completion accounting (for the build)
The builder lists any of D1-D4 not done, with reason and card. The README carries the Live row from D3 and the post-restart validation table.
