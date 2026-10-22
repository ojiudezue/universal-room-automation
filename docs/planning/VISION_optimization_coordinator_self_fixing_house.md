# VISION — The Optimization Coordinator as a self-fixing house

Card: `OC-SELF-OPTIMIZING-HOUSE-REDESIGN-1` (Tier 3, thread optimization). Folds in `OC-SHADOW-SAMPLES-EMPTY-1` (operator 10-17: first slice) and the residual of `OC-STUCK-SENSOR-GENERALIZE-1`. Gates on `HVAC-OPTIMIZER-CLIMATE-FUNNEL-ROUTING-1`.
Status: vision for operator approval. Not a build plan; each slice gets its own plan and plan review.
Written 2026-10-21. I read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` in full before writing §5, and nothing here re-asserts a claim from its §10 ledger.

**Operator framing (binding).** "Optimization coordinator is meant to diagnose the house and self fix it. It's supposed to reason over issues in the house." Correction 10-16: the OC never acted *by operator choice*, because the operator sensed the noise. Shadow mode was a deliberate trust withhold. So the failure is signal quality, and the right to act has to be earned by measured precision the operator can see.

---

## 1. What the OC is today, and why it has not earned trust

**Its parts** (all in `domain_coordinators/optimization.py` unless noted):

- A 5-minute cycle (`run_cycle`, :1015) runs about 14 dimension evaluators: comfort, sensor_health, occupancy_accuracy, prediction_accuracy, camera_stuck, never-fires, camera_input_dark, and others. Each produces `OptimizationFinding`s (:226).
- An LLM tier (`optimization_llm.py`, `created_by=tier2_llm`) reasons over a truncated snapshot.
- A six-rung autonomy ladder (`const.py:4100-4123`): advisory, **shadow** (live value, CM options `optimizer_autonomy_level: shadow`), reversible_device, propose_config, immediate_config, unbounded. It has a per-dimension cap, confidence gate, rate cap, quiet hours, kill switch and safety deny-list (`_check_safety_denylist` :4221).
- A battery-reserve hard deny (:4514) and an intent broker that opens the HVAC arrester's suppression window (:407).
- A shadow-accuracy validator (:1449) feeding `_compute_promotion_readiness` (:5180). That output is shown only as a sensor attribute (`sensor.py:18403`).

**Measured today** (live URA DB, read-only, 2026-10-08 to 10-22 UTC):

| Measure | Value |
|---|---|
| Finding rows, 14 days | **5,305** (about 640/day since 10-14; 10-09..10-13 ran 8-39/day, cause not investigated) |
| Distinct (dimension, target) pairs | **72**. Four problems make up about 80% of rows |
| `meta` "cycle_ok" sentinel | 2,199 rows (41%), one heartbeat per cycle |
| `prediction_accuracy` "top-1 hit-rate 21.1% < 35%" | 1,980 rows (37%), **one** problem re-emitted every cycle |
| `comfort` (room) | 655 rows over 8 rooms in the last 7 days. Jaya Bedroom alone: 359 |
| `occupancy_accuracy` Master Bedroom provenance disagreement | 71 rows, one problem |
| `sensor_health` | 353 rows over 32 targets (7 days) |
| LLM findings | 122. Most say it cannot see the cause ("findings truncated", "operator is running blind") |
| Rows with a proposed action / applied / observed effect | **0 / 0 / 0** |
| `optimizer_shadow_samples` rows, ever | **0** |

**Why it has not earned trust:**

1. **It reports cycles, not problems.** No dedup survives across cycles or restarts. One unchanged fact (prediction skill is low) produced 1,980 rows. Fresh 10-21 evidence from the coordinator: the never-fires detector found 7 sensors, all verified truly silent, with 0 false findings. Yet each one was re-reported after every HA restart (4 times in 10 hours), because its `("sensor_never_fires", eid)` dedup key lives in memory. The finding was correct and the delivery was noisy.
2. **It has no scored track record.** The validator scores only `self._last_findings` (:1498). Those are replaced by the current cycle just before it runs (:1231), and it requires findings to be 900 s old (`const.py:4176`). So nothing is ever old enough, and 0 samples exist. Fixing that alone would still score little, because tier-1 findings carry no proposed action (`_consider_apply` :4895 stamps "no proposed action emitted"). The OC never says what it would do, so there is nothing to grade.
3. **It does not reason across signals.** Each dimension speaks alone. The LLM gets a truncated corpus and mostly reports that truncation. Five room-score findings caused by one dead device stay five findings.
4. **Its precision is invisible.** The operator has no number that says "when the OC claims X, it is right N% of the time".

---

## 2. The target: a house that diagnoses and fixes itself

Five parts. Each is marked REUSE (prior art exists) or NEW.

| Part | What it is | REUSE / NEW |
|---|---|---|
| **A. Problems, not findings** | A persistent `problem` record keyed by a stable fingerprint (kind, subject entity or room, cause). It holds first_seen, last_seen, occurrence count, evidence links, state (open → acknowledged → fixing → verifying → resolved / wont_fix) and resolution. Per-cycle evaluators **update** problems instead of inserting rows, so one fact is one row. Survives restart. | REUSE the `dedup_key` field (:246) as the fingerprint, the evaluators, the batched writer `_persist_findings_batch` (:5109) and the 1/day `_filter_repeat_sensor_health` (:5047) as the precedent. NEW: the persisted problem table/DAO. It takes the kanban card's lifecycle shape (states, evidence, disposition) without its YAML. |
| **B. Reasoning across coordinators** | A root-cause pass over open problems: "these five room-score drops share one unavailable device", "comfort misses in zone 2 coincide with a manual hold". It links child problems to a parent, so the operator sees the cause once. Deterministic joins first; the LLM tier then gets the deduped problem list, which is small, instead of a truncated snapshot. | REUSE `optimization_llm.py` and the corpus builder, `anomaly_log` / `AnomalyDetector` (`coordinator_diagnostics.py:981`), the `RoomDwellModel` (`room_dwell_model.py:92`, v5.103.83) as the "is this room's occupancy normal" oracle, and the predictions audit (`AUDIT_predictions_room_zone_house_2026_10_21.md`) as the list of which predictors are fit to reason with (today: none of the occupancy ones). NEW: the parent/child linking. |
| **C. A toolbox ranked by reversibility** | A fixed catalogue of fix types, each with preconditions, an owning coordinator, a revert and a verifier (§3). The OC proposes a *fix type plus arguments*, never a free-form service call. | REUSE the ladder's reversible_device / config split, `_clamp_numeric_to_band` (:4152), the denylists and the broker veto. NEW: the catalogue as data. |
| **D. Autonomy earned per fix type** | Each fix type climbs the existing ladder on its own **measured precision**: was the diagnosis right, and did the fix work? This is shown to the operator as a scoreboard. Promotion is always an operator tap. Demotion is automatic when precision falls. | REUSE `CONF_OPTIMIZER_DIMENSION_AUTONOMY`, `_compute_promotion_readiness`, `optimizer_shadow_samples` and the confirm-guard pending rung. CHANGE: key readiness by **fix type**, not dimension, and score **problems**, not rows. |
| **E. Verify-and-rollback loops** | Every applied fix arms a verifier with a deadline ("the entity is available within 10 min", "the counter is monotonic for 1 h"). It passes, or it reverts and the problem escalates to the operator. Outcomes feed D. | REUSE the `observed_effect_json` / `applied_outcome` columns (never written so far), the NM, and the HVAC-style "suppression needs a discharge" discipline. NEW: the verifier registry. |

The operator surface is one dashboard card or page: open problems ranked by impact, each with evidence and cause; a precision scoreboard per fix type; and the "promote / demote" buttons. NM sends only state changes of problems (opened HIGH, fix failed, needs you), never cycles.

---

## 3. What "self fix" means here, concretely

Drawn from this house's real recurring problems. Ordered by reversibility.

| # | Fix type | Real instance | Owner / route | Automate? |
|---|---|---|---|---|
| 1 | **Open or update a card / problem record** | never-fires sensors, the zone_1 manual strands | OC itself | **First.** No house effect. It is the base everything else stands on. |
| 2 | **Page the operator with one deduped, evidenced ask** | a dead Shelly relay behind AV Closet lights (CLAUDE.md troubleshooting); S10 latch NMs that went unseen at MEDIUM | NM | **First**, with severity chosen so it reaches a channel (companion = HIGH+). |
| 3 | **Flag a dead actuator** | room lights/fans `unavailable` that `sensor.<room>_unavailable_entities` cannot see (inputs only) | OC → room/NM | **First** (read-only diagnosis; only the flag is automatic). |
| 4 | **Reload one stuck config entry** | Shelly / cloud entries loaded but device back on WiFi; Carrier freshness reload (already an adapter verb `remediate_stale`) | owning integration via a sanctioned reload helper. **Never** the URA parent entry (watchdog hazard) | **Second**, after precision is shown. Only for an entry whose devices are reachable again, rate-capped to 1 per entry per day, verifier = entities available. |
| 5 | **Re-seed a flapping counter / stale baseline** | Envoy counter flapping (220-324/day measured); poisoned energy_daily predictions (10-02..10-04) | owning coordinator's own reset verb | **Third.** Reversible only if the old baseline is snapshotted. |
| 6 | **Retune a threshold within bounds** | per-room night vacancy hold (Jaya Bedroom); the 4 h stuck-sensor literal (`coordinator.py:364`) | config write, clamped ±20%, through the options/Number path | **Later** (propose_config with veto). It changes behaviour for days, so the verifier window is long. |
| 7 | **Actuate a device** (setpoints, presets, fans, EVSE) | comfort misses | **only via the owning coordinator's funnel** (§5) | **Last**, and never for climate until §5 is built. |
| — | **Never automate** | battery reserve / grid charge (already hard-denied :4514), safety/security entities (smoke, CO, locks, alarm), URA parent reload, HA restart, deleting anything, editing `.storage`, physical fixes (re-aiming the Jaya radar) | — | Operator-only. The OC may diagnose and page. |

The rule of thumb: diagnosis and paging are automatic from slice 1. Any write to the house needs a verifier, a revert and a scoreboard row before it is offered for promotion.

---

## 4. Slices

Each slice is separately planned and reviewed. Tier 3 overall, but slices 1-2 do not actuate, so each is Tier 2-DB (new DAO and changed write volume; the 2026-06-09 write-flood incident is the ingredient risk).

**Slice 1: Problems, a track record, and visible precision** (no actuation)
- Persistent problem records with restart-safe dedup. This closes the never-fires restart re-reports and the in-memory dedup on every evaluator.
- `cycle_ok` leaves the findings table (heartbeat becomes a sensor timestamp).
- Fix the shadow validator (OC-SHADOW-SAMPLES-EMPTY-1): score problems carried across cycles in a capped pending buffer, not `_last_findings`.
- Every non-meta problem states a falsifiable prediction ("sensor X will stay silent 24 h", "room Y comfort miss persists 30 min"), so scoring has something to grade.
- Operator-visible precision per problem kind.
- *Acceptance:* over 7 days, the problem table holds ≤ 1 row per distinct fact, so restarts add 0 rows (today: 4 re-reports in 10 h). `optimizer_shadow_samples` > 0 within 1 h of deploy, and ≥ 20 samples per scored kind within 7 days. Daily OC DB writes fall from about 640 to under 50. A precision figure per kind is visible on the dashboard. Per-table write count per cycle ≤ 2 (the write-flood test, extended to the new table).

**Slice 2: Cross-signal root cause**
- Deterministic parent/child linking: a device unavailable explains room-score and comfort problems that share it.
- The LLM tier gets the deduped problem list.
- *Acceptance:* in a fixture with one dead device and five dependent problems, the operator sees one parent problem. Live: LLM "truncated / can't see" findings drop to 0, and ≥ 1 linked parent is confirmed by hand.

**Slice 3: Toolbox, tier A (no house writes): cards, pages, dead-actuator flags**
- Fix types 1-3 automated, each with a precision row.
- *Acceptance:* every paged problem reached a channel (no MEDIUM-into-void). Operator-rated precision for paged problems ≥ 80% over 2 weeks, or the kind is demoted to digest.

**Slice 4: Reversible fixes with verify-and-rollback**
- Fix type 4 (entry reload), then 5, each starting in shadow ("would have reloaded"), scored, then promoted by operator tap.
- *Acceptance:* each promoted fix type shows ≥ 20 shadow decisions at ≥ 90% precision before its promote button enables. Each applied fix has a verifier verdict row. A failed verifier reverts and pages within its deadline.

**Slice 5: Bounded config retunes** (propose + veto). **Slice 6: device actuation through owner funnels**, which is gated by §5.
- *Acceptance:* same precision gate. Every write lands as the owning coordinator's own ledger row (for climate, a `climate_write` row with an OC site id).

---

## 5. Precondition for any OC actuation: route through the owner's funnel

**Proposed rule:** before the OC may actuate anything climate-related, `HVAC-OPTIMIZER-CLIMATE-FUNNEL-ROUTING-1` is built. I recommend making the rule **broader**: the OC never calls a device service directly in **any** domain that has an owning coordinator. It asks that coordinator to act through its funnel. HVAC is the first and most dangerous instance.

**Why, from code.** The OC dispatches with raw `hass.services.async_call(domain, action, data)` at `optimization.py:4677` (device) and `:4826` (config). For climate its only courtesy is opening the arrester's TTL window (`suppress_climate` :407) and an egress-pause check (:4568). It is lint-allowlisted out of the funnel rule (`hvac_const.py:1546`). Against the HVAC state of play, that bypass would cause these failures:

- **No ledger row.** W1-A made every thermostat write produce one `climate_write` row through the five `emit_*` funnels (`hvac_setpoint.py`, state of play §4.1/§4.3). An OC write would be invisible there. That is the exact gap that caused the wrong exoneration recorded in §10 C1.
- **A double writer and a fight with S1.** A raw `set_temperature` on Carrier rewrites the MANUAL profile and sets `hold=manual` (`ha_carrier climate.py:467-537`, §5). Since W1-B, S1 reclaims any `manual` unless one of the four §9e gates holds. None of those gates knows the OC, so S1 reverts the OC on the next 5-minute tick, or the arrester books it as a human override once the suppression window lapses. The window is 15 s for temperature and 120 s for presets, against Carrier echoes of 42-79 s (§2, §7). The result is churn plus false overrides: the C23 echo class again.
- **Presets and profiles.** Zone 3 runs Custom Preset Ranges (S10 edits named profiles via `emit_set_activity_setpoint`, §4.2). Ecobee zones are commanded by an adapter that selects comfort or writes ranges (`hvac_strategy`). A raw OC preset or setpoint write skips the brand adapter, the freeze/deadband guards and S10's settle gate.
- **Borrow and arrester state.** Gate (e) (live borrow row) and the arrester's grace/compromise timers protect nudges, pre-cool, banking and egress (§6, §9e). The OC checks only egress. A write mid-nudge or mid-compromise would be overwritten by the borrow's restore, or would corrupt its snapshot.
- **Precedence.** Rulings D13/D48-D52 (nudge wins, person interrupts end borrows, immune persons) live inside HVAC. A second writer outside it has no place in that ladder.

**Why broader than HVAC.** The same shape exists elsewhere. Battery decisions emit only through `_result` (`energy_battery.py:7068`); the reserve is already hard-denied to the OC for this reason. EVSE is one switch with many owners arbitrated by owner-set/peer-hold (`energy_pool_owners.py`). Room lights and fans have a Fan Mode owner rule (`const.fan_owner`, state of play §4.2b). A raw OC write in any of these is a second writer the owner cannot see. So the precondition I propose is: **"request, don't write". The OC emits a typed fix request; the owning coordinator accepts, defers or refuses it under its own precedence and logs it in its own ledger.** The HVAC card becomes the first implementation of that contract. It only bites at slice 6, so it does not delay slices 1-5.

---

## 6. Non-goals, risks, decisions

**Non-goals.**
- No actuation in slices 1-3.
- No new optimizer engine (MILP/emhass stays rejected per the 2026-05 research correction).
- No room-agents build (`ROADMAP-STALE-AGENTIC-LAYER-1` stays a separate card).
- No change to the autonomy ladder's rungs.
- No touching battery reserve, safety or security entities, ever.

**Risks.**
- **Write volume:** a new table on the shared write queue (the 2026-06-09 incident). Mitigation: batch per cycle, and add a per-table write-count test.
- **Precision theatre:** scoring cheap predictions that are trivially right. Mitigation: score against an independent oracle (entity state, recorder), and include operator ratings on paged problems.
- **Dedup hiding a recurrence:** a resolved problem that reopens must count again. The fingerprint must include the episode.
- **The LLM tier stays noisy** even on deduped input. If so, demote it to a digest.

**Decisions needed from the operator.**

1. **Approve the vision and slice order.** *Recommend yes.* Slices 1-3 carry no house risk and produce the precision numbers the trust decision needs.
2. **Broaden the precondition to "request, don't write" for every owning coordinator, with HVAC first.** *Recommend yes.* The HVAC card alone leaves EVSE and fans open to the same double-writer failure.
3. **Score by fix type, not by dimension.** *Recommend yes.* A dimension mixes fixes of very different risk.
4. **Promotion is always an operator tap; demotion is automatic.** *Recommend yes.* This matches the 10-16 correction that trust is yours to grant.
5. **Precision bars:** ≥ 80% for paging and ≥ 90% over ≥ 20 decisions for any house write. *Recommend these as starting knobs* (Number entities, rung 3).
6. **Retire `meta cycle_ok` rows** from the findings table in slice 1. *Recommend yes.* They are 41% of rows and carry no information a timestamp cannot.
