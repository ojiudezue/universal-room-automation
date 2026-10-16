# PLANNING — Egress exit identity backfill: disposition + residuals

**Card:** EGRESS-EXIT-IDENTITY-BACKFILL-1 (operator 2026-10-16: "do it first").
**Author:** ura-planner, 2026-10-16. **Status:** plan, awaiting D0.
**Headline:** the card's Tier-3 build **already shipped** (v5.96.1, 2026-09-05; co-departure v5.97.1, 2026-09-06). The board status `parked` is stale. This plan does not re-plan that build. It (1) disposes the card against ground truth, (2) gates any further code on a one-shot D0 measurement, and (3) scopes the small residuals the read-through found.

---

## 0. Mandatory reading — done

Read completely before planning: `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`, `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 corrections ledger), `docs/architecture/SENSOR_FLEET_CLASSES.md`, `PLANNING_ble_crossing_device_tracker_rearch_2026_09.md`, `PLANNING_egress_exit_identity_backfill_2026_09.md` (the shipped plan), `AUDIT_v6_milestone_candidates.md` (identity rows), memory `reference_egress_face_coverage_7pct_not_a_ceiling.md` (all amendments). No corrections-ledger claim is re-asserted here.

**Doc contradictions found (code wins; fix in the D3 commit):**
- Manual §4.3/§5.5 describe `person_id` as face-only and list four bus-reading display sensors. Code: exit `person_id` is also written after the fact by the BLE backfill (`camera_census.py:4508-4709`, DAO `database.py:4385`), and `PersonsExitedTodaySensor` re-reads the DB on `SIGNAL_EGRESS_EXIT_BACKFILLED` (`sensor.py:4754-4794`). The manual has no backfill section.
- Manual §4.6 cites `database.py:793-808` for the table. The table DDL is now at `database.py:1032-1048`.
- Card `refs` say INSERT-only at `database.py:3915`. Wrong today: INSERT `:4262/4285`, UPDATE `:4385-4411`.

## 1. Institutional context verified (prior-art scan by FUNCTION)

Method: grep (read-only) across `const.py`, `camera_census.py`, `transit_validator.py`, `database.py`, `sensor.py`, `signals.py`, `__init__.py`, `docs/planning/*egress*`, the kanban, memory.

| Function the card asks for | Verdict | Existing symbol (file:line) |
|---|---|---|
| Write exit row immediately with null `person_id` | **EXISTS** | `transit_validator.py:2094-2119` INSERT on every non-ambiguous crossing, `person_id` from face resolver (often None) |
| Detect resident BLE departing edge | **EXISTS** | `_on_crossing_tracker_state_change` departing branch `camera_census.py:4457-4506` |
| Row UPDATE write path (idempotent, single-use) | **EXISTS** | `database.backfill_entry_exit_person_id` `database.py:4385-4420`, `WHERE id=? AND person_id IS NULL`, via write queue `_db()` |
| Window SELECT, naive-UTC bounds | **EXISTS** | `find_unnamed_exit_crossings` `database.py:4347-4383` (read ctx, `LIMIT 2`, nearest first) |
| Matcher + settle + flap re-read + retry-claim | **EXISTS** | `_backfill_exit_identity` `camera_census.py:4508-4709` |
| Multi-resident co-departure | **EXISTS** (EGRESS-EXIT-COMULTI-DEPART-1, done v5.97.1) | retry-claim loop `camera_census.py:4587-4707`; `BLE_EXIT_CLAIM_MAX_ATTEMPTS=6` `const.py:2934` |
| Multi-tracker dedup (phone+watch) | **EXISTS** | per-slug cooldown `camera_census.py:4475-4489`; `BLE_EXIT_PER_SLUG_COOLDOWN_S` `const.py:2941` |
| Pending-backfill teardown | **EXISTS** | `_backfill_tasks` set `camera_census.py:1551`, cancel `:5204-5218`, wired at unload `__init__.py:5839-5842` |
| Window knob | **EXISTS** | `BLE_EGRESS_EXIT_BACKFILL_WINDOW_S=600` `const.py:2907` (rung 1) |
| Settle knob | **EXISTS** | `BLE_EXIT_DEPARTURE_SETTLE_S=300` `const.py:2923` (rung 1, wrong-WHO guard) |
| Display re-read on backfill | **EXISTS for exits list** | signal `SIGNAL_EGRESS_EXIT_BACKFILLED` `signals.py:33`, fired `camera_census.py:4681`, consumed `sensor.py:4754-4794` |
| Observability counters | **EXISTS** | 9 `_ble_exit_*` counters `camera_census.py:1553-1589`, surfaced `sensor.py:3891-3919` on `sensor.ura_census_persons_in_house` attrs (unique_id `sensor.py:3649`) |
| Last-exit display re-read on backfill | **MISSING** — residual R1 | `LastPersonExitSensor` `sensor.py:4880-4910` listens to the bus event only |
| Row-level provenance (face vs BLE backfill) | **MISSING** — residual R4 | DAO deliberately leaves `confidence` untouched (`database.py:4404-4406`). DB cannot tell a backfilled row from a face row |

Prior plans consulted: `PLANNING_egress_exit_identity_backfill_2026_09.md` (the shipped design; full), `PLANNING_egress_exit_comulti_depart_2026_09.md` (filename + card), `PLANNING_ble_crossing_device_tracker_rearch_2026_09.md` (full; D0 lag numbers). Kanban: EGRESS-EXIT-DISPLAY-REREAD-1 (done v5.96.2), EGRESS-SENSOR-READER-TZ-OVERCOUNT-1 (done), EGRESS-EXIT-COMULTI-DEPART-1 (done v5.97.1).

**Process gap found:** `README_v5.96.1.md:30` and `README_v5.97.1.md:24` still carry the prospective "Live Validation — to record as `Validated <date>`" header. Neither cycle wrote back a validation table. Under CLAUDE.md that means neither cycle is closed. D0 here is that missing validation.

### Verifying the AUDIT_v6 claim "exit attach already happens"

From AUDIT_v6 (live, 14d 10-02..10-16): entry 75/279 = 26.9%, exit 59/213 = 27.7%. **Exits do attach at parity with entries.** But the audit cannot say via which path, and neither can the DB alone. Exit `person_id` has two writers:
1. **Face at crossing time:** `_resolve_egress_face_identity` (`transit_validator.py:2000`), stamped into the INSERT.
2. **BLE backfill ~5-11 min later:** `_backfill_exit_identity` UPDATE, `person_id` only (confidence column untouched).

So "59 named exits" mixes both. Provenance is only recoverable from the `ble_exit_backfilled_count` attribute history (recorder) or `exit-backfill: row_id=` INFO logs (journald). D0 does that split.

## 2. Falsifiable invariant (re-stated for the shipped surface; D0 + R-deliverables must not break it)

> **INV-EXIT-BACKFILL:** An exit row's `person_id` transitions NULL → R only if one of R's `bluetooth_le` trackers made a home→away edge at time E, the tracker was still away at E + `BLE_EXIT_DEPARTURE_SETTLE_S`, the row's timestamp T satisfies E − `BLE_EGRESS_EXIT_BACKFILL_WINDOW_S` < T ≤ E, R ∈ `tracked_persons`, and `switch.ura_name_people_at_doors` is on at UPDATE time (**violated today**, see §5; R1 closes it). In every reachable path: (a) a non-NULL `person_id` is never overwritten, by backfill or anything else; (b) one edge names at most one row; (c) any failure (DB error, flap, `unknown`/`unavailable` re-read, task cancelled at teardown/restart, no row in window) leaves the row NULL; (d) no notification, census mutation, or other actuation fires off a backfill. Only the DB row, the exits-list display, and (after R1) the last-exit display change.

Falsified by: a row whose `person_id` changed from one non-NULL slug to another; a backfilled row with T > E or T ≤ E − 600; a backfill with no in-window edge for that slug; a second `notification_log` row for the same crossing; a census `evict_egress_face` call from the backfill path.

(d) is new as a written invariant but already true in code. The backfill path only calls the DAO and the dispatcher (`camera_census.py:4650-4690`). R-deliverables must keep it true.

## 3. Producer and consumer checks

### Producer: `person_entry_exit_events.person_id` on exit rows
- **Face leg** — healthy-ish, intermittent. Per memory, Frigate face has flapped at the service level. AUDIT_v6 shows named rows only for `jaya` and `oji_udezue` in 14d.
- **BLE backfill leg** — dependencies:
  - Bermuda / private_ble trackers with `source_type==bluetooth_le`. Oji has one tracker, no redundancy (rearch plan :32).
  - INSERT timestamp = `datetime.utcnow()` **at INSERT time** (`database.py:4290`), which is about crossing + 45s (`ENTRY_WINDOW_SECONDS`). It is not the camera crossing time. The SELECT bound is `T ≤ E`.
  - **Structural miss A (unmeasured):** an edge E earlier than the INSERT timestamp is excluded, even though the row exists by the time the SELECT runs after the 300s settle. The rearch D0 reported a p-tail "earliest −281s" (an edge *before* the crossing). Those departures can never be named.
  - **Structural miss B:** E − T > 600s. D0 p90 was 612s, so about 10% or more by construction.
  - **Miss C:** the flap re-read aborts on `unknown`/`unavailable` (`camera_census.py:4578`). A Bermuda tracker that goes `unavailable` rather than `not_home` on departure is never named. Rate unmeasured.
  - **Miss D:** a restart within settle + lag of a departure cancels the task. No startup sweep (accepted non-goal of the shipped plan).
  - Healthy? Unknown. The counters exist but nobody has read them since ship. D0 reads them.

### Consumers of exit `person_id` and what a later UPDATE means for each

| Consumer | file:line | Trust/display | Reads when | Effect of after-the-fact UPDATE | Decision |
|---|---|---|---|---|---|
| Arrival/departure notification | `transit_validator.py:2031` → `_arrival_departure_notify` `:2124-2160` | notification | bus-time, synchronously at crossing | Already sent "Someone left". Note: even if re-sent, backfill identity = `BLE_TRANSITION_ONLY_CONFIDENCE` 0.72 (`const.py:2885`), **below** `ARRIVAL_NAME_CONFIDENCE_THRESHOLD` 0.75 (`:2122`). A re-notify would still say "Someone". | **No re-notify** (non-goal). This also reconciles part of AUDIT_v6's "27% attach vs 40% named notifications" puzzle: backfilled exits count as attached but can never be named in a notification. |
| Census union evict | `transit_validator.py:2059-2079` | trust (census) | bus-time | Not evicted on backfill. Harmless: the union TTL `EGRESS_FACE_UNION_TTL_S=300` (`const.py:2836`) has already expired by settle(300) + lag, and the departer's own BLE not_home removes them from `ble_ids`. | **No census recount** (non-goal). Keeps INV (d). |
| `PersonsExitedTodaySensor` | `sensor.py:4722`, re-read `:4782-4794` | display | DB re-read on signal | Named row appears in the list | Already correct. |
| `LastPersonExitSensor` | `sensor.py:4880-4910` | display | bus only | Stays "unidentified" even after the row is named | **R1** (fix). |
| `PersonsEnteredTodaySensor` / `LastPersonEntrySensor` | `sensor.py:4588`, `:4850` | display | entry only | none (backfill touches exit rows only, `direction='exit'` in SELECT) | none |
| Guest gate / security / arm-away | none today (`GUEST-GATE-DOOR-IDENTITY-1`, `LAST-RESIDENT-EGRESS-ARM-1` parked) | — | — | Future consumers must read the DB *after* the backfill window, or treat exit identity as late-binding. | Documented in D3 for the manual. |
| Dashboards / PWA | grep found no other `person_entry_exit_events` reader in the integration. PWA not inspected (separate repo). | display | — | — | orchestrator confirm |

## 4. Deliverables

### D0 — Measure-before-build gate (read-only, orchestrator runs; ~10 min). Also the overdue v5.96.1/v5.97.1 live validation.

`ssh ha` against the live DB (`/config/universal_room_automation/data/universal_room_automation.db`) plus the HA recorder (`/config/home-assistant_v2.db`):

```sql
-- Q1: attach by direction, last 14d (naive-UTC column)
SELECT direction, COUNT(*) n, SUM(person_id IS NOT NULL) named,
       ROUND(100.0*SUM(person_id IS NOT NULL)/COUNT(*),1) pct
FROM person_entry_exit_events
WHERE timestamp >= datetime('now','-14 days') AND direction IN ('entry','exit')
GROUP BY direction;

-- Q2: named exits by camera + person (provenance split comes from Q3)
SELECT egress_camera, person_id, COUNT(*) FROM person_entry_exit_events
WHERE direction='exit' AND timestamp >= datetime('now','-14 days')
GROUP BY 1,2 ORDER BY 3 DESC;
```

- **Q3 (provenance split):** recorder history of `sensor.ura_census_persons_in_house` attributes `ble_exit_backfilled_count`, `ble_exit_edge_no_match_count`, `ble_exit_flap_aborted_count`, `ble_exit_row_lost_count`, `ble_exit_backfill_noop_count`, `ble_exit_error_count`, `ble_exit_per_slug_cooldown_skipped_count`, `ble_departing_edge_seen_count` over 14d. Sum the per-boot deltas, because counters reset on restart. Cross-check with `journalctl -u ... | grep "exit-backfill: row_id="` for the window journald retains.
  - BLE-named exits = backfilled count.
  - Face-named exits = Q1 exit named − backfilled.
- **Q4 (lag distribution, the core gate):** for each resident `bluetooth_le` tracker home→away edge in the recorder (14d), compute signed `E − T_row`, where T_row is the nearest exit row timestamp (naive-UTC → epoch, **TZ-aligned**; the memory's false-oracle lesson is a 5h skew). Bucket it:
  - `< 0` (miss A)
  - `0-600` (in window)
  - `600-900`, `900-1800` (miss B)
  - no exit row within ±1800s
  - Also count edges whose next state was `unavailable`/`unknown` (miss C).
- **Q5 (recoverable ceiling):** of the null exit rows in 14d, how many have a resident tracker home→away edge within [T − 300, T + 1800]? That count is the upper bound on what any backfill change could add.

**Go/no-go:**
- **Disposition (always):** write Q1+Q3 results back as the `Validated 2026-10-xx` tables in `README_v5.96.1.md` and `README_v5.97.1.md`. If backfilled count > 0 and no wrong-WHO evidence (see the falsifier list in §2: spot-check 5 backfilled rows against BLE history), move the card to **done (met)**.
- **R2 GO** only if Q5 recoverable ≥ 10 rows/14d **and** Q4 shows ≥ 50% of them in a single structural bucket (A or B). Otherwise **PARK R2** with the trigger "Q5 ≥ 10/14d".
- **Discriminates:** "backfill working" = backfilled > 0, most Q4 edges in 0-600, and Q5 small. "Backfill dead" = backfilled ≈ 0 while Q4 0-600 is populated: regression, open a bug card, not R2. "Backfill working but structurally capped" = Q4 mass in `<0` or `>600` with Q5 large: R2. The three outcomes look different, so the gate discriminates.

### R1 — Last-exit display re-reads on backfill (Tier 1, ~15 LoC)
Subscribe `LastPersonExitSensor` to `SIGNAL_EGRESS_EXIT_BACKFILLED` (REUSE `signals.py:33`, same pattern as `sensor.py:4754-4760`, unsubscribe via `async_on_remove`). On a payload, update `_last_person_id` only if the backfilled row is the row this sensor is showing. That needs the row id, so the payload has `row_id` (`camera_census.py:4684`). The sensor does not hold a row id today, so match on "most recent exit row" via one `get_entry_exit_events_since(..., direction='exit')` read, taking the newest row. Do not change `native_value` (the timestamp).

**Acceptance**
- **Test:** `test_last_exit_sensor_updates_on_backfill_signal`: fire bus exit with `person_id=None`, then dispatch the signal for that row with the DB row named. Attribute goes `unidentified` → slug.
- **Test:** `test_last_exit_sensor_ignores_backfill_of_older_row`: a newer unnamed exit exists and the backfill names an older row. Attribute stays `unidentified`. This discriminates "re-read newest row" from "blindly copy payload".
- **Live:** after the next resident departure, `sensor.ura_last_person_exit` attr `person_id` flips from `unidentified` to the slug about 5-11 min later, in step with the matching row in Q1.

### R2 — Recover structurally missed exits (CONDITIONAL on D0; Tier 2-DB elevation if GO)
Shape depends on which bucket D0 shows. Pick the cheapest rung first (config-first):
- **Miss B only (late edges):** a **knob turn** on `BLE_EGRESS_EXIT_BACKFILL_WINDOW_S` (rung 1, needs review) to the measured p95. No new code. Risk: a later unrelated departure binds to an earlier null row. Bounded by the IS-NULL claim plus per-slug cooldown, which derives from the same const (`const.py:2941`). Note the coupling: widening the window also widens the cooldown. Review must accept or decouple it.
- **Miss A (edge before the INSERT timestamp):** add a lower slack `BLE_EGRESS_EXIT_BACKFILL_PRE_S` (NEW rung-1 const; grep found no equivalent in const.py) so the SELECT upper bound becomes `E + PRE_S`. The SELECT runs after the 300s settle, so a row inserted after E already exists. Wrong-WHO risk: a resident whose tracker drops while still inside, just before someone else exits, gets the other person's row. That is why it is Tier 2-DB with an adversarial reviewer.
- **Miss C:** **not in this plan.** Admitting `unavailable` as a durable departure weakens the wrong-WHO flap guard. Park it with the trigger "Q4 miss-C ≥ 5/14d", plus a separate design.

**Acceptance (if GO)**
- **Test:** a replayed D0 edge in the target bucket names the row.
- **Test:** an edge outside the new bound stays NULL.
- **Test:** co-departure with one edge inside the new pre-slack names two distinct rows.
- **Test:** INV (a) holds under the new bound, via mutation drill on the bound site.
- **Live:** Q5-style recount 7 days post-deploy shows recoverable nulls dropped by at least half the D0-predicted number, with no wrong-WHO (5-row spot check). Predict the number before deploy.

### R4 — Row provenance (OPTIONAL; recommend PARK)
Exit rows can't say whether the name came from face or BLE. A clean fix is a column, which means a schema migration (Tier 2-DB). **Marginal benefit:** today it only serves measurement, and Q3's counter-history path answers that once. Park it with the trigger "first trust consumer of exit `person_id` (guest gate / arm-away) is scoped": that consumer will need provenance for the §5.5 confidence doctrine.

### D3 — Doc + board hygiene (same commit as R1)
- Card → done after D0, with the disposition text.
- Manual: add §4.3a "Exit backfill (late-binding identity)", fix the `:793-808` cite, add the consumer-row facts from §3 (notification never names a backfilled exit, 0.72 < 0.75).
- Card refs: fix the `database.py:3915` cite.
- PRESENCE state-of-play §9: replace the stale "EGRESS-BLE-ENTRY-ATTACH-1" pointer line if D0 changes it. Otherwise, no change.

## 5. Knobs (all existing unless noted)
| Knob | Rung | Value | Why / kill semantics |
|---|---|---|---|
| `BLE_EGRESS_EXIT_BACKFILL_WINDOW_S` | 1 | 600 | attribution window; 0 → empty SELECT range → backfill effectively off (kill) |
| `BLE_EXIT_DEPARTURE_SETTLE_S` | 1 | 300 | wrong-WHO flap guard; do NOT lower for latency |
| `BLE_EXIT_CLAIM_MAX_ATTEMPTS` | 1 | 6 | co-departure retry bound |
| `BLE_EXIT_PER_SLUG_COOLDOWN_S` | 1 | = window | multi-tracker dedup; coupled to window (see R2) |
| `BLE_EGRESS_EXIT_BACKFILL_PRE_S` | 1 | NEW, only if R2-A GO; default 0 = today's behaviour (kill) | edge-before-INSERT slack |
| `switch.ura_name_people_at_doors` | 3 | — | **Gap (confirmed by grep):** neither `_on_crossing_tracker_state_change` (`camera_census.py:4332`) nor `_backfill_exit_identity` (`:4508-4709`) reads `_is_egress_identity_enabled`. With the switch OFF, exits are still named via BLE, which goes against operator intent. Fix in R1's commit: a fresh read before the DAO UPDATE, skip + count when off (Tier 1, ~5 LoC). **Test:** `test_exit_backfill_honours_name_people_kill_switch` (switch off → row stays NULL). |

## 6. Non-goals
- Re-notifying on backfill, or raising backfill confidence to cross 0.75. That would be a policy change to notification doctrine, so it needs its own card if wanted.
- Census recount or evict on backfill.
- Startup sweep for departures missed across a restart (miss D).
- Treating `unavailable` as a departure (miss C).
- Face-side exit naming changes; Protect D1 bridge.
- Provenance column (R4 parked).
- Any change to entry attribution.

## 7. Marginal-benefit statement
The operator asked for the backfill. It exists. The simplest version (shipped) already brings exit attach to parity with entry, per AUDIT_v6. Further gains are capped by Q5, which is unmeasured. Building R2 before D0 would add wrong-WHO surface for an unknown number of rows. Recommendation: run D0, ship R1 (+ the kill-switch check) as Tier 1, close the card, and let Q5 decide R2. AUDIT_v6 named "exit backfill" as a coverage-raise lever toward 6.0.0. D0 tells us whether there is anything left in that lever.

## 8. Tier
- **D0:** read-only, no tier.
- **R1 + kill-switch fix:** **Tier 1** (display-only sensor + a gate that can only reduce writes; one review).
- **R2 (if GO):** **Tier 2-DB elevated** (regression-prone attribution change on an identity producer; 3 framing-disjoint reviews: A bound arithmetic/TZ, B lifecycle/co-departure/cooldown coupling, C mutation on the bound site), plus an adversarial wrong-WHO pass.
- **Not Tier 3:** the Tier-3 ingredient (a new UPDATE write path / state machine) already shipped and was reviewed in v5.96.1/v5.97.1. None of the residuals adds a new writer.
