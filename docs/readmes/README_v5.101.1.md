# URA v5.101.1 — Optimizer noise, recorder bloat, EVSE onset resilience, flow timing

**Shipped:** 2026-09-13
**Tier:** 2 (multi-card bundle; each component independently reviewed)
**Cards:** OPTIMIZER-PAGING-PRIMITIVE-1 · OVERRIDE-COUNT-STARTUP-AUDIT-UNTESTED-1 ·
RECORDER-BLOAT-LOGFLOOD-1 · EVSE-CHARGE-ONSET-NOT-HELD-1 (+ instrumentation for
CONFIG-FLOW-SLOW-ONBOARDING-1, which stays open)

Bundled deliberately so the house restarts **once**.

---

## D1 — Optimizer paging: stop the corpus trimmer manufacturing a false CRITICAL (B1)

**Problem.** Every optimizer alert that reached the operator's phone in the preceding
7 days was the *same* self-referential artifact: *"open_findings_count reports N but
findings_recent is empty."* Six of six criticals; **none described a real house
condition.**

**Root cause.** `to_prompt_body` (`optimization_llm.py`) trims the LLM corpus greedily
in the order `findings_recent → prior_actions → rooms → zones`, while `house` — which
carries `open_findings_count` — is preserved until a last-resort stub. The code comment
states the intent: *"so a noisy findings_recent can't crowd out house."* Under corpus
pressure the model is handed `open_findings_count=N` beside `findings_recent=[]`, a
contradiction **we manufactured**, and correctly reports it as CRITICAL. CRITICAL
bypasses `should_defer_high_to_digest`, so our own truncation paged the operator.
Corpus pressure peaks exactly when findings are numerous.

**Fix.** Make the corpus honest rather than silence the model: emit a
`corpus_truncation_notice` naming each truncated section with shown-vs-total and
instructing the model not to treat a count-vs-truncated-list mismatch as an anomaly.
Counted **inside** the budget; rides every fallback depth.

**Invariant preserved:** a *genuinely* empty `findings_recent` (no truncation) produces
**no notice**, so a real inconsistency is still reportable. The in-budget path is
byte-identical.

### Acceptance Criteria
- **Verify:** an in-budget corpus is byte-identical to pre-fix (early return, no notice).
- **Verify:** a truncated corpus contains `corpus_truncation_notice` with `shown`/`total`.
- **Test:** `test_corpus_truncation_notice_absent_when_nothing_trimmed`,
  `..._present_when_findings_trimmed`, `..._survives_every_fallback_depth`.
- **Live:** no new `severity=critical` row in `optimization_findings` whose description
  matches `findings_recent.*empty` / `open_findings_count.*but` after restart.

---

## D2 — Optimizer volume: suppress unchanged repeat `sensor_health` rows (B2)

**Problem.** `_evaluate_sensor_health_dimension` dedups only *within* a cycle, so a
sensor that stays unavailable re-emits an identical row every ~5 minutes forever.
Measured over 7 days: **5026** `sensor_health/high` rows, of which **one** offline
entity accounted for **1550** (~288/day for a single unchanged fact). This floods the
findings table, bloats the daily digest, and crowds the LLM corpus — carrying zero new
information after the first row.

**Fix.** Cross-cycle suppression keyed `(dedup_key, stuck_state)`, bounded by
`OPTIMIZER_SENSOR_HEALTH_REPERSIST_INTERVAL_S = 86400` (24h). ~288 rows/day → ~1.
A stuck-state **change** re-emits immediately; **recovery** clears the key so a re-break
alerts at once; **interval 0 is a kill switch** restoring per-cycle persistence.

**Load-bearing design decision — do not "simplify" this into the evaluator.**
`_update_scoreboard` runs *earlier* in the cycle and derives `open_findings_count`,
`_room_scores` and `_house_score` from the full findings list. Suppressing at evaluation
time would make a room with a still-broken sensor score 100 and **raise the house
score** — hiding a fault would look like fixing it. Suppressing only the DB row keeps
every in-cycle consumer byte-identical (scoreboard, `_notify_if_severe`,
`_last_findings`/LLM corpus); only the persisted row-rate changes.

### Acceptance Criteria
- **Verify:** an unchanged stuck sensor persists once per 24h, not once per cycle.
- **Verify:** the scoreboard still counts the fault on **every** cycle.
- **Test:** 6 tests incl. **two wire-in anchors** driving `_persist_findings_batch`
  (helper-only tests stay green when the call site is removed — the wire-in anchors go red).
- **Live:** `sensor_health/high` row-rate drops sharply while
  `sensor.*_optimizer_*` open-findings count is unchanged for a still-broken sensor.

---

## D3 — Startup-audit override count: real test anchor

**Problem.** The `override_count_today` increment in `async_startup_audit` had no
behavioural test. An in-repo comment claimed it *"is exercised by an independent test
that drives async_startup_audit"* — **false**. The only coverage naming the method
(`test_v478_egress_window.py:961`) is a **source grep** asserting strings exist in the
file, so deleting the increment would not have failed it (hollow anchor).

The path is load-bearing: wired at `hvac.py:1540`, and `override_count_today` feeds 7
consumers including the optimizer override-frequency advisory (`≥10 → medium`,
`optimization.py:2342`) and the zone efficiency score
(`override_penalty = count * 5`, `sensor.py:1590`). An uncounted stale override
silently understates both.

**Fix.** Behavioural anchor + a **discriminating negative** (manual-but-within-tolerance
stays 0, so the anchor cannot pass by counting every manual zone) + a mutation anchor.

### Acceptance Criteria
- **Test:** `test_startup_audit_counts_stale_override`,
  `test_startup_audit_ignores_zone_within_tolerance`,
  `test_mutate_startup_audit_site_breaks_anchor`.
- **Verify:** deleting the real increment in source turns the behavioural anchor RED.

---

## D4 — Recorder bloat / log flood (inherited, reviewed)

Churning diagnostic timestamp attributes marked unrecorded and the churning
`last_check*` keys dropped. Addresses 31 GB of recorder DB for 7 days of history on
flash at 51% life.

### Acceptance Criteria
- **Live:** recorder growth rate per day falls; no `last_check*` attribute churn in
  `states_attributes`.

---

## D5 — EVSE charge-onset reload resilience (inherited, reviewed)

The onset enable flag restored `off` during a config-entry reload, so the charge-onset
gate read "feature disabled" and let both chargers run ~2h early (battery 46%→9%).
Makes the flag reload-resilient.

**Caveat carried forward:** the *reload storm itself* is still un-root-caused
(URA-CONFIG-ENTRY-RELOAD-STORM-1). This hardens the consumer; it does not remove the
trigger.

### Acceptance Criteria
- **Live:** `switch.ura_energy_coordinator_ev_charge_onset_overnight` survives a
  config-entry reload without a transient `off`.

---

## D6 — Config-flow per-step timing instrumentation (diagnostic only)

Wraps all 44 ConfigFlow + 56 OptionsFlow `async_step_*` handlers with ENTER/EXIT timing
(gated `CONFIG_FLOW_TIMING`). **This is not a fix** — it is the measurement that will
finally pin the 25-minute Foyer room setup: large `elapsed_ms` = URA-side cost; a large
wall-gap between EXIT(N) and ENTER(N+1) on an instant submit = event-loop stall.

CONFIG-FLOW-SLOW-ONBOARDING-1 **stays open** until the next room setup produces data.

### Acceptance Criteria
- **Live:** next Add-Entry / room setup emits ENTER/EXIT WARNING lines with `elapsed_ms`.

---

## Verification performed pre-deploy

| Check | Result |
|---|---|
| Conflict markers | none |
| `compileall` on the integration | rc=0 |
| `test_optimization_coordinator.py` (B1+B2 together) | **107 passed** |
| arrester + recorder + evse + cflow suites (`.venv-ha`) | **115 passed** |
| B1 mutation drill (neuter notice) | 2 tests RED → restored, residue 0 |
| B2 mutation drill (neuter **call site**) | 2 wire-in anchors RED → restored, residue 0 |
| D3 mutation drill (delete real increment in source) | behavioural anchor RED → restored, residue 0 |
| Board | `kanban_render.py --check` = 0 |

**Note on the B2 drill:** the first attempt neutered the call site and all four
helper-only unit tests stayed **green** — a hollow anchor. The wire-in anchors were
added specifically because of that failure.

---

## Live Validation — to be completed post-restart

Per CLAUDE.md this README is **not done** until the observed results are written back
here as a `Validated <date>` table, one row per acceptance criterion with concrete
evidence (entity_id + attribute, log scan, DB row read).

- [ ] D1 — no new self-referential meta CRITICAL rows
- [ ] D2 — `sensor_health` row-rate down; scoreboard unchanged for a broken sensor
- [ ] D3 — in-suite only (startup-audit path is not externally observable)
- [ ] D4 — recorder growth rate
- [ ] D5 — onset flag survives a reload
- [ ] D6 — timing lines present on next room setup
