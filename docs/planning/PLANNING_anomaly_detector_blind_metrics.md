# PLANNING — Anomaly detector must not say "nominal" when it cannot see (shared AnomalyDetector coverage state)

**Date:** 2026-09-29 · **Author:** ura-planner · **Status:** DRAFT REV 1. Needs ONE adversarial plan review (Tier 2+ rule) before build dispatch. D0 is a read-only measurement gate and runs first.
**Cards:** `HVAC-ANOMALY-BLIND-1` (residual A, operator "Fix it" 2026-09-29), `HVAC-BASELINE-MAXSAMPLES-1` (considered for merge; decision: keep separate, §7).
**Operator question answered here:** "Do other coordinators have the same problem?" Yes. See §2.

---

## 0. Headline

Every URA coordinator that owns an `AnomalyDetector` projects its sensor state with the same three-line rule: aggregate `learning_status`, else `get_worst_severity()`. Neither input looks at whether each declared metric has data. Three separate defects in the shared primitive let a blind detector print `nominal`:

1. **The floor(n/2) gate.** `get_learning_status` returns ACTIVE when `max(1, n // 2)` metrics are mature (`coordinator_diagnostics.py:1138`). For HVAC (n=5) that is 2 metrics, and for Security (n=2) it is 1.
2. **Severity only sees anomalies that fired.** `get_worst_severity` returns NOMINAL when no anomaly has fired (`:1156-1158`). A metric with no data can never fire, so it always reads as "fine".
3. **Scope blindness.** Every status read uses `scope="house"` (`:1132`, `:1193`, `:1229`) through `_get_baseline`, which creates the row if it is missing (`:1030-1039`). A metric fed only at zone scope therefore shows as silent. On top of that, a phantom `(metric, "house", 0)` row is created and later saved by `save_baselines` (`:1392`). This hits `hvac.short_cycle_rate` (zone_1/2/3) and `presence.zone_occupied_count` (`zone:<name>`).

The fix goes in the shared detector. It adds one new method that projects the state and one per-metric coverage classifier. The five duplicated sensor projections are replaced by one call. Four new attributes are added, and every existing attribute keeps its key and type.

---

## 1. Institutional context verified

### 1.1 Prior-art scan: REUSE or BUILD, per piece

| Piece | Verdict | Evidence |
|---|---|---|
| Per-metric silence data (`metrics_silent`, `metrics_active_ratio`) | **REUSE + FIX (scope-aware)** | `coordinator_diagnostics.py:1182-1197`, v4.5.14. The data exists and the state projection ignores it (GATE_2026_09_15 step 2) |
| Per-metric maturation gate | **REUSE** `_min_samples_for` | `coordinator_diagnostics.py:999-1008` (HVAC-ANOMALY-BLIND-1 D1a) |
| Suppression registry (fed but muted) | **REUSE** `suppressed_metric_names` / `_persisted_active_anomalies` | `:934`, `:983-986`, `:1010-1023`; per-coordinator constants `hvac_const.py:1282`, `security.py:94`, `presence.py:159`, `safety.py:86`, `music_following.py:63` |
| Nested per-scope surface | **REUSE** D1b `scopes` dict pattern | `:1228-1255`, which reads `self._baselines` without creating rows |
| Sensor state projection | **BUILD** `AnomalyDetector.get_sensor_state()`, replacing 5 duplicates | Duplicates: `sensor.py:6213-6216` (presence), `:6828-6831` (safety), `:7791-7794` (MF), `hvac.py:6820-6830`, `security.py:2478-2488`. The 3 inline ones plus 2 coordinator methods are byte-identical logic (Bug Class #33 sibling-drift risk). Grep for `get_anomaly_status\|get_sensor_state\|coverage` in `domain_coordinators/` found no existing projection helper |
| Per-metric coverage classifier | **BUILD** `AnomalyDetector.get_coverage()` | No equivalent. Grep `coverage\|blind\|unwired` in `coordinator_diagnostics.py`, `sensor.py`, `manager.py`, `base.py` found nothing |
| "Deliberately unwired" declaration | **BUILD** ctor param `unwired_metric_names` + per-coordinator `*_UNWIRED_METRICS` frozenset (HVAC and Security only) | Today "unwired" lives only inside the `*_SUPPRESSED_FROM_PERSISTENCE` sets together with "fed but degenerate shape" (`hvac_const.py:1254-1286` comments). That is two concepts under one name (Bug Class #63). You cannot infer "unwired" from `suppressed ∧ n==0` without mislabelling a broken producer of a suppressed metric (for example zone_call_frequency on a fresh install) as by-design. So the concept split is made explicit |
| Non-mutating baseline lookup | **BUILD** private `_peek_baseline` / `_scopes_for(metric)` | `_get_baseline` (`:1030`) creates rows on read. No read-only peer exists |
| Manager roll-up | **REUSE + additive key** in `get_summary` / `get_system_anomaly_status` | `manager.py:743-808`, `:888-939` |
| Staleness (metric fed, then stopped) | **PARKED behind D0 gate G-STALE** | No live evidence yet of a producer that stopped while in-memory. Residual B was a DB-persistence lag, not a producer stop (card MEASURED_2026_09_16 (c)). Marginal-benefit rule: a state × time seam needs evidence first |
| Baseline forgetting (`max_samples`) | **NOT MERGED** (§7) | `MetricBaseline.max_samples` exists (`:148`, `:169`) and is not set by any AnomalyDetector. This plan does not touch `update()` / Welford |

### 1.2 Prior planning docs consulted
- `docs/planning/PLANNING_hvac_short_cycle_producer.md`: skimmed. Source of the D1a/D1b/D1c shared-detector edits and the "surfaces are not scope-aware" finding (plan-review F6).
- `docs/planning/PLANNING_hvac_w3_energy_aware.md` §5.4 / §3 G0-Q10: read. **Interaction.** W3 renames `short_cycle_rate` to `compressor_short_cycle_rate` and resets it to learning for about 14 days. G0-Q10 measured zone_1/2/3 `sample_count=14`, house scope `0`, at 2026-09-28 05:04Z.
- `docs/planning/AUDIT_restart_safety_classification.md` (through the RESTART-SAFETY-DOCTRINE-1 card body): the rule that accumulators are hazardous when they are "in-memory AND event-driven".
- `docs/planning/PLANNING_v4.6.5_in_memory_anomaly_persistence.md`: filename and header only. The origin of the suppression doctrine.
- `docs/readmes/README_v4.5.14.md`: origin of `metrics_active_ratio` / `metrics_silent`. It states the masking concern this plan finally closes.

### 1.3 Card / memory bodies pulled
- `HVAC-ANOMALY-BLIND-1`: full body, including VERIFIED_2026_09_15, GATE_2026_09_15, MEASURED_2026_09_16, RESIDUAL_B_FIX_SCOPED, RESIDUAL_A_ESCALATED_2026_09_16, NOMINAL_IS_ACTIVELY_MISLEADING_2026_08_23 and HIGHEST_LEVERAGE_FIX_2026_08_23.
- `HVAC-BASELINE-MAXSAMPLES-1`: full body, including gate_2026_09_12 and disposition_2026_09_12_sweep3.
- `RESTART-SAFETY-DOCTRINE-1`: instances, the doctrine, DENOMINATOR_MEASURED_2026_08_21 (2.9 restarts/day, median 5.55h).
- Memory: `feedback_marginal_benefit_pushback`, `feedback_measure_before_build`, `feedback_coincidental_equality_masks_concept_split`, `feedback_hollow_test_anchors`, `feedback_wire_in_anchor_mandatory` (from the MEMORY.md index lines; they are applied in §9 / §10).

### 1.4 Design docs read
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` was **not** read end-to-end in this pass. This plan touches no HVAC control path: it changes only the anomaly projection plus one constant and one ctor kwarg in HVAC. **The builder and the plan reviewer must read it in full before touching `hvac.py`/`hvac_const.py`, per CLAUDE.md 5b.** If §10 of that doc makes any claim about the anomaly sensor, the build follows it.

### 1.5 Code surveyed (read, not just grepped)
- `domain_coordinators/coordinator_diagnostics.py:43-58, 133-186, 915-1457`.
- AnomalyDetector construction sites (6): `hvac.py:1670-1690`, `security.py:755-774`, `safety.py:1155-1178`, `music_following.py:225-249`, `presence.py:2355-2384`, `manager.py:229-243`.
- Every `record_observation` call site (§2).
- Every `save_baselines` call site: `hvac.py:6651` (rollover), `:7116` (teardown); `presence.py:7470`, `security.py:840`, `music_following.py:687`, `safety.py:3092`, `manager.py:488` (all teardown); `__init__.py:4241` (CM per observation).
- Sensor classes: `sensor.py:6180-6240, 6800-6850, 7051-7094, 7765-7815, 12291-12335`.
- `base.py:241-265`, `manager.py:743-808, 888-939`.
- Dashboard consumers (§4).

---

## 2. Step 1 — Measurement: every AnomalyDetector, every metric

### 2.0 Method and its limits (read this first)
**This planning pass had no shell, no `ha-mcp` and no sqlite access, so the live numbers could not be pulled here.** What the table does rest on:
(a) the code: every `record_observation` call site, its scope and its cadence, read at file:line;
(b) the most recent dated **live** measurements already recorded on cards and plans (cited per row);
(c) the live HA `.storage` over the Samba mount (text files only), used for the dashboard consumer check (§4).

Cells marked **UNMEASURED** are filled by **D0** (§5). D0 is a read-only probe script (included inline) that the orchestrator runs with `ssh ha "python3 -" < …` before build. The structural answer ("same problem elsewhere") does not depend on D0: it follows from the code. D0 confirms the numbers and decides gate G-STALE.

### 2.1 Table

| Coordinator | Metric | Producer (file:line), scope, cadence | Fed? | sample_count (latest recorded) | Last update | Can move sensor severity? | Sensor state / attrs today |
|---|---|---|---|---|---|---|---|
| **hvac** | zone_call_frequency | `hvac.py:6716`, house, 5-min tick | YES | 2675 live / 2664 DB (2026-09-16) | ticking | NO (suppressed) | **`nominal`**, `metrics_active_ratio "2/5"`, `metrics_silent [short_cycle_rate, comfort_deviation_hours, egress_pause_frequency]` (live 2026-09-15/16). Zero hvac rows in `anomaly_log` ever (2026-08-23) and zero in the last 3 days (2026-09-26) |
| hvac | override_frequency | `hvac.py:6760`, house, 5-min tick | YES | 2670 live / 2659 DB (2026-09-16) | ticking | YES | ″ |
| hvac | short_cycle_rate | `hvac.py:6547`, **zone_1/2/3**, daily at local rollover; saved at rollover `:6651` | YES at zone scope; **house = 0 phantom** | 14 / 14 / 14 zone, 0 house (2026-09-28 05:04Z, W3 G0-Q10) | daily | YES (zone anomalies are not scope-filtered; matured 09-28) | Still listed in `metrics_silent`, because the house-scope read is scope-blind (defect 3) |
| hvac | comfort_deviation_hours | **none**. The meta-test confirms no call site | **NEVER** | 0 | — | NO (suppressed) | in `metrics_silent` |
| hvac | egress_pause_frequency | **none** (deferred in v4.7.8 §13, never built) | **NEVER** | 0 | — | NO (suppressed) | in `metrics_silent` |
| **presence** | census_count | `presence.py:6810`, house, on house-state change | YES | UNMEASURED | UNMEASURED | NO (suppressed) | UNMEASURED. Predicted `nominal` (threshold `max(1, 3//2)=1`) |
| presence | zone_occupied_count | `presence.py:7140`, **`zone:<name>`** (`:7137`), per zone with sensors | YES at zone scope; **house = 0 phantom** | UNMEASURED | UNMEASURED | NO (suppressed) | Predicted: appears in `metrics_silent` although fed (**same scope blindness as HVAC**) |
| presence | transition_count_daily | `presence.py:7215`, house, per transition | YES | UNMEASURED | UNMEASURED | YES (the only one of 3) | ″ |
| **security** | alert_trigger_frequency | `security.py:916`, house, per entry intent | YES | UNMEASURED | UNMEASURED | YES | UNMEASURED. Predicted **`nominal` with 1 of 2 metrics never fed** (threshold `max(1, 2//2)=1`). **Same laundering as HVAC** |
| security | entry_anomaly_score | **none** (`security.py:92-96` "silent slot") | **NEVER** | 0 | — | NO (suppressed) | in `metrics_silent` |
| **safety** | active_hazard_count | `safety.py:2412`, house, **only inside `_respond_to_hazard` (`:2266`)**, i.e. rare events; gate 720 (`:1170`) | Rare-event only | UNMEASURED | UNMEASURED | YES once mature (effectively never) | Predicted **`learning` / `insufficient_data` permanently**. That is honest (not "nominal") but structurally never matures: rare event × 720 samples × teardown-only save (RESTART-SAFETY class "in-memory AND event-driven") |
| **music_following** | transfer_success_rate | `music_following.py:354`, house, per transfer outcome | YES | 1594 (v4.6.5 era, stale datum) | UNMEASURED | YES | UNMEASURED. Predicted `nominal` or `learning`; both metrics wired. **Clean by code** |
| music_following | cooldown_frequency | `music_following.py:383`, house, per transfer outcome | YES | UNMEASURED | UNMEASURED | YES | ″ |
| **coordinator_manager** | setup_duration_seconds | `__init__.py:4226`, house, once per boot; saved each time (`:4241`) | YES | UNMEASURED (fresh 2026-09-16 per card) | per boot | n/a | **No sensor.** The detector is `_setup_anomaly_detector` and is not in `coordinator.anomaly_detector`, so it is invisible to `manager.get_system_anomaly_status` |

**Not AnomalyDetector-backed (out of scope, listed so nobody asks):** the NM heuristic `notification_manager.py:845-867` `anomaly_status`; energy's standalone `MetricBaseline`s (`energy.py:876-895`, `energy_circuits.py:260`); the safety rate detector (`safety.py:681`, coordinator_id `safety_rate`); the Bayesian occupancy anomaly (`binary_sensor.py:3107-3239`).

### 2.2 Answer: do other coordinators have the same problem?
**Yes, so the fix is in the shared detector, not HVAC-only.**
- **Security:** the same laundering. One of two metrics has never been fed, and the floor(n/2) gate still lets the sensor say `nominal`.
- **Presence:** the same scope blindness. `zone_occupied_count` is fed but reported silent. Only 1 of 3 metrics can move the state.
- **Safety:** a different failure. It is honestly `learning`, but that can never end. A card is needed (§6); the state projection is not wrong.
- **Music following:** clean by code, pending D0.
- **CM setup detector:** no sensor, so no surface lie.

---

## 3. Why each unfed metric is unfed (producer bug vs legitimately absent), and whether it needs its own card

| Metric | Why | Class | Own card? |
|---|---|---|---|
| hvac.short_cycle_rate @house | Zone-scoped by design. The house row is a phantom created on read by `_get_baseline` from the status surfaces | **Projection bug** (shared detector) | NO. Fixed in this cycle (D1 peek + scope-aware aggregation) |
| presence.zone_occupied_count @house | Same as above (zone scope `zone:<name>`) | **Projection bug** | NO. Fixed in this cycle |
| hvac.comfort_deviation_hours | No producer was ever built. The input (zone temperature vs setpoint) exists. The 2026-08-23 "rare event-driven, not recommended" objection is now answerable: short_cycle_rate proved a **daily per-zone emit + rollover save** pattern that is not event-rare | **Producer absent (by deferral), input present** | **YES, NEW card** `HVAC-COMFORT-DEVIATION-PRODUCER-1` (Tier 2): daily per-zone "minutes outside comfort band" reusing the short-cycle rollover emitter. Adjacency sweep: no existing card (board grep for `comfort_deviation_hours` hits only HVAC-ANOMALY-BLIND-1 and RESTART-SAFETY-DOCTRINE-1 text). Its value case: it is the trip-wire for the zone-2 212-min +8°F excursion (card `why`). Until built, this metric shows as `not_wired` |
| hvac.egress_pause_frequency | Deferred in v4.7.8 §13 "once a baseline is available", never built. Egress pauses are rare events | **Producer absent; rare input** | **YES, disposition card** `ANOMALY-UNWIRED-METRIC-DISPOSITION-1` covering this and `entry_anomaly_score`: wire as a daily count (same pattern) or undeclare (remove from `HVAC_METRICS`; the orphan prune at `:1351-1372` cleans the row). Recommendation: **undeclare**, since there is no stated samples/day and the value is unclear. "Dead ≠ delete" is satisfied because the concept is preserved in the card |
| security.entry_anomaly_score | Declared since v3.6.0, no producer ever. The entry processor emits verdicts, which already feed alert_trigger_frequency | **Producer absent; likely redundant** with alert_trigger_frequency | Same disposition card. Recommendation: **undeclare** (redundant input) |
| safety.active_hazard_count | Recorded only on hazard response (rare), gate 720, saved only at teardown | **Accumulator structurally unreachable** (RESTART-SAFETY "in-memory AND event-driven") | **YES** `SAFETY-ANOMALY-STRUCTURALLY-INERT-1`: move to a periodic tick sample (the value is "current active hazards", which is meaningful on any tick) or drop the gate to a reachable value. D0 supplies the current count. Not in this cycle: it changes a safety producer, not the projection |
| (all teardown-only savers) presence / security / MF / safety | In-RAM accrual since the last clean shutdown is lost on an unclean restart: the Residual-B mechanism, confirmed for hvac + presence 2026-09-16 (card (a): 21s-apart freeze) | **Persistence lag**, not unfed | **Conditional on D0 (Q3):** if live-vs-DB drift is >10% or the DB `last_updated` lags by more than 24h on an event-driven metric, card `ANOMALY-BASELINE-DIRTY-SAVE-1` (shared detector: save when dirty on a bounded cadence). Not folded in here: it is a write path, and this cycle is read-only (see §7 for the same logic applied to MAXSAMPLES) |

---

## 4. Consumers of the sensor state (producer / consumer check)

**Producers of the state string (all replaced by one shared call):** `sensor.py:6202-6216` (Presence), `:6818-6831` (Safety), `:7070-7078` → `security.py:2478-2488`, `:7781-7794` (MF), `:12309-12316` → `hvac.py:6820-6830`.

**Consumers**, from a grep of repo + live `.storage` + `automations.yaml`:

| Consumer | file:line | Reads | Trust vs display | Effect of the new `partial` value |
|---|---|---|---|---|
| PWA Security tab | `dashboard-v3/src/components/tabs/Security.tsx:44-45, 85, 331` | sensor state as raw text | display | Renders "partial". No switch, so no breakage |
| PWA Presence tab | `Presence.tsx:49, 382` | raw text | display | ″ |
| PWA Safety tab | `Safety.tsx:45, 311` | raw text | display | ″ (Safety is not predicted to reach `partial`) |
| PWA Diagnostics / Home | `Diagnostics.tsx:81-90`, `Home.tsx:570-575`, `data/statusColors.ts:22-52` | **`status_per_coordinator[*].status`** from `manager.get_summary` (`manager.py:779`), i.e. **severity, not the sensor state** | display | **Unchanged**, because severity semantics are kept. The badge still says "healthy" while the coordinator is partial. That second-surface gap is addressed additively by D3 (`coverage` key). The TS badge change is **carded** (`DASH-ANOMALY-COVERAGE-BADGE-1`, dashboard workstream), not built here |
| Live Lovelace v8 "URA Anomalies" auto-entities | `.storage/lovelace.ura_v8:~9985-9996` (snapshot `docs/ha-config-snapshots/lovelace_ura_v8_backup_2026_09_29.json:9971-9996`) | `sensor.ura_*_anomaly`, **exclude `state: nominal`** | display | **HVAC + Security will now be LISTED as anomalies (state `partial`).** Operator-side fix: add `{"state": "partial"}` to that exclude list, or leave them listed as a deliberate coverage nag. **Operator action item (config, not code), §9** |
| Live Lovelace v8 tile | snapshot `:9678` `sensor.ura_hvac_coordinator_hvac_anomaly` | state | display | Shows "partial" |
| Live Lovelace v7 | `.storage/lovelace.ura_v7:59` exclude nominal | display | Same as v8 |
| Legacy Lovelace v4 / v5 | `.storage/lovelace.ura_v4:3458, 3469, 3480, 3507`; `lovelace.ura_v5:3431, 3442, 3453, 3480` | Jinja `is_state(…,'nominal') or …'learning'` → green, else **red** | display | `partial` renders **red** on legacy dashboards. Accepted: legacy, superseded by v8. Noted in the README |
| HA automations | `/Users/okosisi/ha-config/*.yaml` grep `_anomaly` | none | — | **No automation consumers** (only a tuya_local device yaml matched, unrelated) |
| NM / other coordinators | `domain_coordinators/*` grep | none read the sensor state; `manager.py` reads `get_worst_severity()` directly | trust (roll-up) | Unchanged (severity kept) |
| Tests | `quality/tests/test_v4514_anomaly_visibility.py` (14 refs), `test_v465_observability_gap.py:835, 1312` | summary keys / projection | test | Must stay green. Existing keys are unchanged; projection tests are updated to the shared method |

**Conclusion:** no trust consumer reads the state string. It is display-only (GATE_2026_09_15 already established this for HVAC; now verified for all five). Adding a state value is safe, provided severity semantics stay untouched for `manager.py`.

---

## 5. Deliverables

### D0 — Read-only measurement gate (run BEFORE build)
Probe (orchestrator runs `ssh ha "python3 -" < probe.py`; stdout only, `mode=ro`):

```python
import sqlite3, json
URA = "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro"
HA  = "file:/config/home-assistant_v2.db?mode=ro"
COORDS = ("hvac","presence","security","safety","music_following","coordinator_manager")
u = sqlite3.connect(URA, uri=True)
print("== Q1 metric_baselines")
for r in u.execute("SELECT coordinator_id,metric_name,scope,sample_count,round(mean,3),"
                   "round(variance,3),last_updated FROM metric_baselines WHERE coordinator_id IN "
                   "(%s) ORDER BY 1,2,3" % ",".join("?"*len(COORDS)), COORDS): print(r)
print("== Q4 anomaly_log 30d")
for r in u.execute("SELECT coordinator_id,metric_name,count(*),max(timestamp) FROM anomaly_log "
                   "WHERE timestamp>=datetime('now','-30 days') AND coordinator_id IN (%s) "
                   "GROUP BY 1,2" % ",".join("?"*len(COORDS)), COORDS): print(r)
ENT = ["sensor.ura_hvac_coordinator_hvac_anomaly","sensor.ura_presence_coordinator_presence_anomaly",
       "sensor.ura_security_coordinator_security_anomaly","sensor.ura_safety_coordinator_safety_anomaly",
       "sensor.ura_music_following_coordinator_music_following_anomaly"]
h = sqlite3.connect(HA, uri=True)
Q = ("SELECT s.state,a.shared_attrs,s.last_updated_ts FROM states s JOIN states_meta m "
     "ON s.metadata_id=m.metadata_id LEFT JOIN state_attributes a ON s.attributes_id=a.attributes_id "
     "WHERE m.entity_id=? AND s.last_updated_ts>=strftime('%s','now','-7 days') ORDER BY s.last_updated_ts")
for e in ENT:
    rows = h.execute(Q,(e,)).fetchall()
    print("==", e, "rows7d", len(rows), "states", sorted({r[0] for r in rows}))
    if not rows: continue
    st, attrs, ts = rows[-1]; a = json.loads(attrs or "{}")
    print("  Q2 latest", st, a.get("learning_status"), a.get("metrics_active_ratio"), a.get("metrics_silent"))
    for m, d in (a.get("metrics") or {}).items():
        print("   ", m, d.get("sample_count"), d.get("minimum_samples"),
              {k: v.get("sample_count") for k, v in (d.get("scopes") or {}).items()})
    # Q3 cadence: per metric, the largest gap between sample_count increments (seconds), 7d
    last = {}; gap = {}
    for st, attrs, ts in rows:
        for m, d in (json.loads(attrs or "{}").get("metrics") or {}).items():
            n = d.get("sample_count")
            if m in last and n is not None and n != last[m][0]:
                gap[m] = max(gap.get(m, 0), ts - last[m][1]); last[m] = (n, ts)
            elif m not in last: last[m] = (n, ts)
    print("  Q3 max-gap-s", {m: round(g) for m, g in gap.items()})
```

The probe's report is appended to this doc as §2.3 and replaces every UNMEASURED cell.

**Gates:**
- **G-PREDICT:** write the predicted post-ship state per sensor (§8 table) from the Q1/Q2 numbers. If the prediction shows Presence or MF going `partial` for a reason not in §3, stop and re-plan.
- **G-STALE:** if Q3 shows any **tick-driven** metric (hvac zone_call_frequency / override_frequency) with a max gap above 3× its cadence (above 900s) that is **not** explained by a `homeassistant_start` in the window, build D-STALE (§5 D5). Otherwise D5 stays parked with that exact trigger.
- **G-PERSIST:** if Q1 vs Q2 shows live-vs-DB sample_count drift above 10%, or a DB `last_updated` older than 24h for an event-driven metric, mint `ANOMALY-BASELINE-DIRTY-SAVE-1` (§3). Otherwise record "no drift" and close the question.

#### Acceptance Criteria
- **Verify:** the probe output is pasted into §2.3; every UNMEASURED cell is filled; G-PREDICT / G-STALE / G-PERSIST verdicts are written as PASS/FIRE with the number that decided each.
- **Live:** this deliverable is itself a live read.

### D1 — Shared coverage classifier + non-mutating reads (`coordinator_diagnostics.py`)
- `_scopes_for(metric_name) -> dict[str, MetricBaseline]`: returns the existing entries of `self._baselines` for that metric. It **never creates**.
- `get_coverage() -> dict`: per declared metric, a reason, derived from the **best scope**. The best scope is the scope with the highest `sample_count` among existing entries; if there are none, n=0. Reasons:
  - `ok`: best n ≥ `_min_samples_for(metric)`
  - `learning`: 0 < best n < gate
  - `never_fed`: n == 0 in every scope AND the metric is not in `unwired_metric_names` (this means a wired producer is starved, i.e. a bug)
  - `not_wired`: in `unwired_metric_names` (by design, no producer)
  - `stale`: reserved value. Emitted only if D5 ships. It is defined now so the vocabulary is stable
  - The dict also carries `suppressed: bool`, a per-metric annotation that is not a reason. A suppressed metric with data is **seeing, not blind**; it is only muted.
- **Blind set** = metrics whose reason is in {`learning`, `never_fed`, `not_wired`, `stale`}. Rule: blindness is about DATA. "Suppressed" means muted, not blind.
- Ctor gains `unwired_metric_names: Optional[frozenset[str]] = None` (default empty; the backward-compatible default). It is validated at init: every entry must be in `metric_names`, otherwise it logs a warning and the entry is dropped.
- `get_learning_status`, `get_status_summary` (top-level `metrics_active_ratio`, `metrics_silent`, and the requested-scope `metrics` entries) switch from `_get_baseline` to a non-creating peek. For a metric with no requested-scope row, the entry reports `sample_count 0` exactly as today, but **without inserting**. `metrics_active_ratio` / `metrics_silent` / `get_learning_status` become **scope-aware** (best scope). This is **byte-identical for every house-only metric**; it changes only `hvac.short_cycle_rate` and `presence.zone_occupied_count` (the intended fix).
- `get_worst_metric` (`:1172-1177`) switches to `_persisted_active_anomalies()`. This is an in-cycle LOW: today it can name a suppressed metric as the "worst" in `manager.get_system_anomaly_status:927` while severity is filtered (Bug Class #33, sibling helper skipped).
- **No change** to `record_observation`, `MetricBaseline.update`, `load_baselines`, `save_baselines`, `_classify_severity`, `get_worst_severity`.

#### Acceptance Criteria
- **Test:** `test_coverage_reasons_each_class`. A real `AnomalyDetector` (not a stub) with 5 metrics covering ok / learning / never_fed / not_wired / suppressed-with-data. The oracle is an independently authored dict literal.
- **Test:** `test_zone_scoped_metric_not_reported_silent`. Feed only `("m","zone_1")` ≥ gate. Assert the reason is `ok`, `metrics_silent` excludes it, and `metrics_active_ratio` counts it.
- **Test:** `test_status_reads_do_not_create_baselines`. Call `get_learning_status()`, `get_status_summary()`, `get_coverage()`, `get_sensor_state()`, then assert `set(det._baselines)` is unchanged. **Drill:** reverting any one read site to `_get_baseline` must turn this RED.
- **Test:** `test_house_only_detector_summary_byte_identical`. Compare the `get_status_summary()` dict, minus the 4 new keys, against a golden captured from the **pre-change** code in the same test (AST-extract the old method, or a committed fixture JSON produced from `develop` before the build).
- **Test:** `test_worst_metric_excludes_suppressed`.
- **Test:** `test_unwired_names_must_be_declared` (unknown name dropped + warning).

### D2 — Shared sensor-state projection; replace the 5 duplicates
- `AnomalyDetector.get_sensor_state() -> str`, precedence:
  1. aggregate `get_learning_status()` ∈ {insufficient_data, learning} → that value (existing behaviour)
  2. `get_worst_severity()` ≠ nominal → the severity (**a real anomaly always outranks coverage**)
  3. blind set non-empty → **`partial`**
  4. otherwise → `nominal`
- New `AnomalySeverity`-adjacent constant: `COVERAGE_PARTIAL = "partial"` in `coordinator_diagnostics.py`. It is a module constant, **not** added to the `AnomalySeverity` StrEnum, because `partial` is not a severity and adding it would put it into `_SEVERITY_RANK` / `map_diag_severity` paths (Bug Class #22).
- Replace: `sensor.py:6213-6216`, `:6828-6831`, `:7791-7794` → `…anomaly_detector.get_sensor_state()`. `hvac.py:6820-6830` and `security.py:2478-2488` keep their names (they have callers and tests) but their bodies delegate to `self.anomaly_detector.get_sensor_state()`. `not_configured` / `disabled` / `not_initialized` stay in the sensor/coordinator layer, unchanged.

#### Acceptance Criteria
- **Test:** `test_sensor_state_precedence_matrix`. Real detector; the matrix is {aggregate learning, severity advisory+blind, blind only, all ok}, with expected values {learning, advisory, partial, nominal}.
- **Test:** `test_all_five_sensors_route_through_get_sensor_state`. This is a **behavioural** wire-in anchor, not a source grep (Bug Class #62). Build each sensor with a manager stub whose coordinator carries a real detector in the blind-only configuration, and assert `native_value == "partial"` for all 5 (HVAC and Security through their coordinator methods). **Drill:** restore the old inline body at any ONE of the 5 sites and exactly that sensor's case turns RED.
- **Verify:** `grep -n "get_worst_severity().value" sensor.py hvac.py security.py` returns 0 hits. This is a supplementary check only; the anchor above is the proof.

### D3 — Additive attributes + roll-up keys (no existing key changes type or meaning, except the scope-aware fix in D1)
- `get_status_summary` adds: `coverage` ("full" | "partial"); `metrics_blind` ({metric: reason} for blind metrics only); `metrics_unwired` (list); per-metric `reason`, `suppressed`, `last_updated` (the max ISO string across scopes, raw; no parsing, so no clock seam).
- `manager.get_summary` → `status_per_coordinator[coord]["coverage"]` (additive; `status` stays severity). `manager.get_system_anomaly_status` → `coordinators_partial: list[str]` (additive). `base.get_diagnostics_summary` → `anomaly["coverage"]`.

#### Acceptance Criteria
- **Test:** `test_manager_summary_status_unchanged_coverage_added`. With a blind-only detector, `status == "nominal"` (severity is preserved for `statusColors.ts`) and `coverage == "partial"`.
- **Test:** `test_system_anomaly_lists_partial_coordinators`.
- **Sensor:** `sensor.ura_hvac_coordinator_hvac_anomaly` attrs contain `coverage`, `metrics_blind`, `metrics_unwired`.

### D4 — Declare the deliberately unwired metrics (constants + ctor wiring)
- `hvac_const.py`: `HVAC_UNWIRED_METRICS: Final = frozenset({"comfort_deviation_hours", "egress_pause_frequency"})`. `security.py`: `SECURITY_UNWIRED_METRICS = frozenset({"entry_anomaly_score"})`. Presence / Safety / MF: empty frozensets (explicit, same as the suppression doctrine).
- Pass `unwired_metric_names=` at all 5 coordinator ctor sites (`hvac.py:1670`, `security.py:765`, `safety.py:1166`, `music_following.py:238`, `presence.py:2369`). The CM detector (`manager.py:232`) gets none: it has one wired metric.
- Extend the meta-test `test_every_metric_is_wired_or_suppressed` (`test_v465_observability_gap.py:835`): each `*_UNWIRED_METRICS` ⊆ `*_SUPPRESSED_FROM_PERSISTENCE`, AND no unwired metric has a `record_observation` call site. That catches a future builder who wires a metric but forgets to remove it from UNWIRED.
- Extend `test_all_coordinators_pass_suppression_set_to_anomaly_detector` (`:1312`) with a behavioural twin: construct each coordinator's detector through its real setup path (or AST-extract the ctor kwargs) and assert `det._unwired_metric_names == <CONST>`. **Drill:** delete the kwarg at one site and that coordinator's case turns RED.

#### Acceptance Criteria
- **Test:** the two meta-tests above, plus the per-site drill result recorded in the build report.
- **Live:** HVAC attrs `metrics_unwired == ["comfort_deviation_hours","egress_pause_frequency"]`; Security `["entry_anomaly_score"]`.

### D5 — Staleness (PARKED; built only if D0 G-STALE fires)
If it fires: ctor `max_silence_s_by_metric: dict[str,int]`. `stale` applies iff `now - max(last_updated_best_scope, detector_started_at) > window`. `detector_started_at` gives a boot grace, so there is no boot flap. Parse `last_updated` tolerating naive or aware timestamps (naive is treated as UTC; Bug Classes #11/#13/#21). Windows are set only for tick-driven metrics, never for event-driven ones (no event = no data, legitimately). Knob: `HVAC_ANOMALY_TICK_MAX_SILENCE_S = 900` (module constant, rung 1: a producer-cadence correctness contract; changing it should need review). **If parked**, the revival trigger is written on the card: "a tick-driven anomaly metric observed with a sample_count gap > 3× cadence not explained by a restart."

---

## 6. Falsifiable invariant

> **INV-COVERAGE.** For every AnomalyDetector-backed anomaly sensor, in any reachable state, the sensor reports `nominal` **only if** every declared metric has at least one existing scope baseline with `sample_count ≥ _min_samples_for(metric)` and is not in `unwired_metric_names`. If any declared metric fails that, the state ∈ {insufficient_data, learning, partial, advisory, alert, critical}, and `metrics_blind` names **every** such metric with its reason.

> **INV-SEVERITY-PRECEDENCE.** If `get_worst_severity() ≠ nominal` and aggregate learning is ACTIVE, the state equals the severity, whatever the coverage (partial never masks a real anomaly).

> **INV-NOOP.** For a detector whose metrics are all house-scoped and all `ok` with an empty unwired set, `get_sensor_state()` and every pre-existing `get_status_summary()` key/value equal the pre-change output, and no read path adds a key to `_baselines`.

**Legal configurations reviewer D should try to break these with:** `unwired_metric_names` naming a metric that is also fed (the meta-test forbids it; what does the runtime do?); a zone-scoped metric that is mature in zone_1 and at 0 in zone_2 (best scope = ok; documented limitation, per-scope detail in `scopes`); `minimum_samples_by_metric` override lower than the scalar; a phantom `(metric, house, 0)` row **loaded from the DB** from before this change (it must not win the best-scope pick over a mature zone row); aggregate ACTIVE plus a blind metric whose anomaly list contains only suppressed anomalies (must be `partial`, not the suppressed severity).

---

## 7. HVAC-BASELINE-MAXSAMPLES-1: merge or keep separate? **KEEP SEPARATE. Re-park with a new trigger.**
- **Revival trigger (a) fired** (the operator picked on HVAC-ANOMALY-BLIND-1), so the question is evaluated here, and the answer is no merge.
- **Different accumulator path.** This plan is read-only projection (`get_*`). MAXSAMPLES changes `MetricBaseline.update` Welford math and both creation sites (`_get_baseline :1034`, `load_baselines :1340`; the cap is **not** persisted and **not** restored today, so it must come from ctor config at both). The brief's merge condition ("if the plan touches the same accumulator") is not met.
- **Different risk class.** Changing the accumulator shifts every z-score for every opted-in metric, which is a regression-prone write-path change. Coupling it to a display fix would force this cycle's reviews to cover live alerting behaviour for no display benefit.
- **The seasonal victim is being reset anyway.** W3 renames `short_cycle_rate` → `compressor_short_cycle_rate`, and the orphan prune deletes the cooling-season baseline. The heating-season baseline therefore starts fresh in October. Trigger (b) ("first heating-season week judges with a cooling baseline") is mooted for the only daily metric. `override_frequency` (tick, unbounded) is the remaining exposure and has no evidence of seasonality.
- **New revival trigger** (write onto the card): *"after W3 ships, the compressor_short_cycle_rate baseline matures (≥14/zone) and then crosses a heating↔cooling mode boundary, OR any hvac anomaly is traced to a baseline whose mean is dominated by >90-day-old samples."* Also record the precondition found here: `load_baselines` does not restore `max_samples`, so the cap must be applied from ctor config at both creation sites.

## 8. Predicted post-ship states (G-PREDICT fills and confirms from D0)

| Sensor | Predicted state | Why |
|---|---|---|
| HVAC | **`partial`** (until the disposition card acts) | comfort_deviation_hours + egress_pause_frequency are `not_wired`; short_cycle_rate is now `ok` (zone scope). **After W3's rename: still partial**, with `compressor_short_cycle_rate: learning` for ~14 days |
| Security | **`partial`** | entry_anomaly_score is `not_wired` |
| Presence | `nominal` if census_count / transition_count_daily are mature (D0 Q1) | zone_occupied_count is now correctly `ok` via zone scope |
| Safety | unchanged (`learning` / `insufficient_data`) | Aggregate precedence; SAFETY-ANOMALY-STRUCTURALLY-INERT-1 addresses it |
| MF | `nominal` or `learning` (D0) | Both wired |

The permanent `partial` on HVAC and Security is **intended and truthful**. GATE_2026_09_15 rejected a permanently *degraded* (alarm) state. `partial` is a coverage label and does not change severity: the manager roll-up and the PWA badge are unchanged. It ends when `ANOMALY-UNWIRED-METRIC-DISPOSITION-1` wires or undeclares the metrics. That gives it a forcing function instead of a laundered `nominal`. **Rejected alternative:** exclude `not_wired` from the blind set (the sensor would say `nominal` with an attribute list). That re-creates the exact complaint ("nominal while N metrics have no data") and relies on nobody opening the attributes. This was the v4.5.14 approach, which the card has now proven insufficient.

## 9. Config-first / operator actions
- **Config-first check:** no knob, option or HA setting changes the projection. `CONF_*_ANOMALY_SENSITIVITY` only scales z-thresholds (`coordinator_diagnostics.py:963-966`). Code is required.
- **Operator action at deploy:** in live Lovelace **ura_v8** (and v7 if still used), add `{"state": "partial"}` to the "URA Anomalies" auto-entities exclude list. Otherwise HVAC and Security appear in the anomalies list permanently. Or keep them listed deliberately as a coverage nag; this is the operator's pick and does not block the build.
- **Cards to mint at build dispatch** (after the adjacency sweep per ura-kanban): `HVAC-COMFORT-DEVIATION-PRODUCER-1`, `ANOMALY-UNWIRED-METRIC-DISPOSITION-1`, `SAFETY-ANOMALY-STRUCTURALLY-INERT-1`, `DASH-ANOMALY-COVERAGE-BADGE-1`; `ANOMALY-BASELINE-DIRTY-SAVE-1` only if G-PERSIST fires. Re-park `HVAC-BASELINE-MAXSAMPLES-1` with the §7 trigger.

## 10. Knob ladder
No new behavioural number in D1–D4: the blind rule is "any blind metric" (no threshold), and the frozensets are declarations, not numbers. The only number is `HVAC_ANOMALY_TICK_MAX_SILENCE_S = 900`, **only if D5 is built**. That is rung 1 (module constant): it encodes the producer's cadence contract (3 × 5-min tick), and changing it should require review. It is not operator policy.

## 11. Tier: **Tier 2-DB** (standing policy: a shared primitive consumed by 6 detectors; a state vocabulary change visible on 5 sensors and live dashboards; a summary payload shape change)
- **Plan review:** ONE adversarial pass before build. It re-greps the 5 projection sites and every `_get_baseline` read site independently, verifies INV-NOOP is testable, and checks that the D0 gates are binary.
- **Build review framings (3, disjoint):** A = correctness of the reason classifier + scope aggregation + edge cases (§6 configs); B = shape/back-compat: every pre-existing summary key byte-identical on the no-op path, manager/base roll-ups, dashboards, W3 rename interplay, no phantom rows persisted; C = test authority: real-detector behavioural anchors, per-site mutation at the 5 projection sites + 5 ctor kwarg sites + each read-site peek, no source-grep-only assertions.
- **Not Tier 3:** no actuation, cost or safety path is touched. Severity semantics are unchanged by construction (INV-SEVERITY-PRECEDENCE).
- **Sequencing with W3:** independent files except `hvac.py`/`hvac_const.py`, where W3 renames `short_cycle_rate`. Tests in this cycle must not hard-code `short_cycle_rate`; use a synthetic metric name against a real detector. Whichever ships second rebases. Build in `.claude/worktrees/<agent-id>-anomaly-coverage`.

## 12. Live validation (feeds the README `Validated <date>` table)
- **Live:** `sensor.ura_hvac_coordinator_hvac_anomaly` state = `partial`; attrs `coverage: partial`, `metrics_blind: {comfort_deviation_hours: not_wired, egress_pause_frequency: not_wired}`; `short_cycle_rate` **absent** from `metrics_silent` and `metrics_active_ratio` ≥ `"3/5"`. **Discriminating:** under the old code the same read gives `nominal` + `"2/5"` + short_cycle_rate silent. Under a plausible different failure (projection wired but the scope fix missing), it gives `partial` with `short_cycle_rate: never_fed`. All three are distinguishable.
- **Live:** `sensor.ura_security_coordinator_security_anomaly` = `partial`, `metrics_blind: {entry_anomaly_score: not_wired}`.
- **Live:** `sensor.ura_presence_coordinator_presence_anomaly`: `zone_occupied_count` is not in `metrics_silent`. State per G-PREDICT.
- **Live:** `sensor.ura_coordinator_manager_coordinator_summary` attr `status_per_coordinator.hvac.status == "nominal"` (severity unchanged) and `.coverage == "partial"`.
- **Live (DB, one-shot after the next clean or rollover save):** `SELECT count(*) FROM metric_baselines WHERE coordinator_id='hvac' AND metric_name='short_cycle_rate' AND scope='house'` shows no NEW phantom rows created after deploy (a pre-existing loaded row may remain; it must not be re-created if deleted manually). `anomaly_log` hvac/presence/security row rates within ±25% of the D0 Q4 snapshot (severity path untouched).
- **Log scan:** no new WARNING/ERROR from `coordinator_diagnostics` beyond the one-time unwired-validation warning (expected: zero).

## 13. Non-goals (explicit)
- Wiring comfort_deviation_hours / egress_pause_frequency / entry_anomaly_score (cards, §3).
- Fixing Safety's unreachable gate (card).
- Periodic or dirty-save of baselines (card, if G-PERSIST fires).
- `max_samples` forgetting (§7).
- Changing `status_per_coordinator.status` / `health_status` semantics or the PWA badge (card).
- Exposing the CM setup detector as a sensor.

## D0 results (measured 2026-09-29 by the orchestrator; probe = the D0 block above, read-only)

Confirmed across every coordinator:
- **HVAC:** state `nominal`, active 2/5. Silent: short_cycle_rate (fed per zone, 15 samples each; house row 0 = the scope bug), comfort_deviation_hours (0, never fed), egress_pause_frequency (0, never fed). zone_call / override live 4624 / 4616. 0 hvac rows in `anomaly_log` in 30 d.
- **Presence:** `nominal`, active 2/3. zone_occupied_count is fed per zone (122,447 per zone live), yet listed silent (the scope bug). **G-STALE-adjacent finding:** the DB baselines for presence were last written **2026-09-14** (live census 535 vs DB 528). Persistence lags by 2 weeks, so the "save baselines more often" card condition is MET.
- **Security:** `nominal`, active 1/2. entry_anomaly_score never fed. **alert_trigger_frequency is degenerate:** mean 1.0, std 0.0 over 317 samples (only ever records 1), so it can never flag anything either.
- **Safety:** `learning` 42/720. Degenerate the same way (mean 1.0, std 0.0; recorded only on hazard response). It will never finish learning (confirms the plan).
- **Music following:** `nominal` 2/2, but both metrics have mean 0.0, std 0.0, with 1572 samples and the DB last updated **2026-05-12**. So no transfers have been recorded for 4.5 months: the feature is idle or dead. A "nominal" there means nothing.
- **Coordinator manager:** setup_duration_seconds 367 samples, and 27 anomaly_log rows in 30 d (the only coordinator that ever fires, driven by the restart storm).

Implication for the plan: besides `partial` for unfed metrics, **degenerate metrics** (std 0 with n ≥ min_samples: security alert_trigger_frequency, safety active_hazard_count, music_following both) are also blind and must be reported as such (reason `degenerate`). Add this to D1 before build.
