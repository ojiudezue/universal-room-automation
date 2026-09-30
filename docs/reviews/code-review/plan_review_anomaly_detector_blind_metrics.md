# Plan review: PLANNING_anomaly_detector_blind_metrics.md (Tier 2-DB, one adversarial plan pass)

**Date:** 2026-09-29 · **Reviewer:** ura-reviewer (plan review, read-only) · **Target:** `docs/planning/PLANNING_anomaly_detector_blind_metrics.md` @ `2c87d49a3`, including the appended "D0 results (measured 2026-09-29)" section.
**HVAC read-first:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` was read completely (lines 1-552) before this review. Its §10 ledger makes no claim about the anomaly sensor. §11 W4 lists `ANOMALY-SAVE-BASELINES-DICT-MUTATION-1` as a parked residual; that card bears on this plan (M3). No contradiction between that doc and the code was found in the anomaly area.

## Verdict: **FIX-PLAN-FIRST**

The core design is sound and should be built: the shared projection, the non-creating peek, scope-aware coverage, the unwired split, and severity kept for `manager.py`. What blocks the build is the D0 addendum. It adds a "degenerate" blindness class in one line without integrating it, and it tripped the plan's own G-PREDICT stop gate. The rule is also wrong as specified. Separately, D0's persistence finding has a different mechanism from the one the plan states.

---

## Findings (ranked)

### HIGH-1: the plan's own G-PREDICT gate fired, and D0's acceptance criteria are not met
- **Where:** §5 D0 gates (lines 193-199) and the D0 addendum (lines 324-334).
- **What:**
  - G-PREDICT says: *"If the prediction shows Presence or MF going `partial` for a reason not in §3, stop and re-plan."* The addendum makes MF `partial` for `degenerate`, a reason that is not in §3. The plan answered with one sentence ("Add this to D1 before build") instead of re-planning.
  - D0's acceptance criterion (line 199) is also unmet:
    - §2.1 still carries every UNMEASURED cell.
    - No §2.3 exists.
    - G-STALE has no PASS/FIRE verdict (Q3 max-gap numbers are absent).
    - G-PERSIST is described but not written as FIRE with its deciding number.
- **The addendum contradicts the body in four places:**
  - **INV-COVERAGE (line 265):** a metric with n ≥ gate and not unwired satisfies the "nominal only if" clause, so a degenerate metric does not make `nominal` a violation. The invariant must be amended.
  - **§8 (line 290):** predicts MF as "`nominal` or `learning`". The addendum makes it `partial`.
  - **§12 (line 310):** the Security live criterion expects `metrics_blind: {entry_anomaly_score: not_wired}` only. If degenerate is built, it also lists `alert_trigger_frequency: degenerate`, and the criterion as written fails.
  - **§9 operator action:** says only HVAC and Security will appear in the v8 "URA Anomalies" list. MF would now appear too.
- **Class:** process (plan-gate bypass) + Bug Class #53 (a rule computed in the appendix but consumed nowhere in the invariants, tests or acceptance criteria).
- **Fix in plan:** re-plan D1/D2/§6/§8/§12 around the resolved HIGH-2 design. Fill §2.3 and write G-STALE / G-PERSIST / G-PREDICT verdicts with their numbers.

### HIGH-2: the "degenerate ⇒ blind" rule is wrong as specified
- **Claim under test (addendum):** "alert_trigger_frequency is degenerate: mean 1.0, std 0.0 … so it can never flag anything."
- **The code refutes it:**
  - `MetricBaseline.std` floors variance at `_MIN_VARIANCE = 0.01`, so std ≥ 0.1 (`coordinator_diagnostics.py:151-158`).
  - The `z_score` guard `if self.std < 0.001: return 0.0` (`:174-176`) therefore never trips.
  - A variance-0 baseline scores any deviation d as z = d / 0.1. At sensitivity 1.0, CRITICAL is z ≥ 4 (`:923-924`), so a deviation of 0.4 is enough.
- **Concrete repro (Security):**
  - Live DB row: `('security','alert_trigger_frequency','house',315, 1.0, 0.0, …)`.
  - The producer records the verdict severity score (`security.py:914-917`).
  - The first entry whose verdict is not LOW records score ≥ 2, giving z ≥ 10 and CRITICAL.
  - So the detector is **hair-triggered, not blind**. Labelling it `partial` misreports it.
- **Legitimately constant metrics:**
  - "Every entry verdict was LOW" is the healthy state of a quiet house.
  - Under the rule, Security reads `partial` permanently. That removes the §8 forcing function ("`partial` ends when ANOMALY-UNWIRED-METRIC-DISPOSITION-1 acts"): after `entry_anomaly_score` is undeclared, Security still stays `partial`.
  - That is a permanent false nag, which is the failure GATE_2026_09_15 rejected for a permanent degraded state.
- **Builder trap (Bug Class #53):**
  - The addendum says "std 0". That number came from the probe's raw `variance` column, since `metric_baselines` stores variance.
  - The live `.std` property can never be 0 (floored at 0.1), and the summary's `"std"` attribute shows 0.1.
  - A builder who codes `baseline.std == 0` or `std < 0.001` ships a rule that never fires.
- **MF is not a coverage problem at all:**
  - Its two rows have mean 0.0 and variance 0.0, last_updated `2026-05-12T04:48:24` (naive, pre-A-M2).
  - That is a legacy baseline from the pre-v4.6.5.2 denominator (the docstring at `music_following.py:320-325` predicted exactly this "mean=0.0 over 1594 samples" drift). The feature has had no music attempts since then (emits require `music_attempts > 0`, `:339`).
  - The truthful finding is "feature idle / baseline legacy", which is a card, not a coverage label.
- **Recommended resolution (pick one in the plan):**
  1. **Preferred: an annotation, not a blind reason.** Emit a per-metric `constant_baseline: true` next to `suppressed`, and add a top-level `metrics_constant` list. Keep it out of the blind set.
     - Card the real per-metric problems: Security's verdict-score shape (an ordinal per-event score is the wrong input for a z-score model), MF's legacy baseline plus idle feature, and Safety (already `SAFETY-ANOMALY-STRUCTURALLY-INERT-1`).
     - This preserves §8's forcing function.
  2. **If the operator wants it in the blind set:**
     - Define it on raw `variance` (never `.std`), with n ≥ `_min_samples_for`, evaluated on the best scope.
     - For a threshold, REUSE `MetricBaseline._MIN_VARIANCE` (rung 1: it is exactly the point where the z-score runs on a synthetic std, not learned data).
     - Specify hysteresis. An ε-floor flaps: after one deviation d = 2 at n = 315, variance ≈ 4/316 ≈ 0.0127, which is not degenerate. Welford decay brings it back under 0.01 after roughly 80 more constant samples, so the state goes partial → critical → (restart clears the anomaly) → partial.
     - Exact `== 0.0` does not flap, because variance never returns to exactly 0 after a deviation. Exact zero is the non-flapping choice.
     - Add the knob to §10 if one is introduced.
  - Either way, amend INV-COVERAGE and add a precedence-matrix row plus a discriminating test: a real detector with n ≥ gate and constant values; the expected state depends on the choice made.

### MEDIUM-1: the G-PERSIST mechanism is wrong. Teardown saves never run on an HA restart (card it with the corrected mechanism)
- **Plan claim (§3 line 117):** "In-RAM accrual since the last clean shutdown is lost on an **unclean** restart."
- **Code truth:**
  - HA does not unload config entries on stop. `ConfigEntries._async_shutdown` calls `entry.async_shutdown()` (venv HA 2026.2.3, `homeassistant/config_entries.py:2176-2180`), which only cancels a retry (`:931-933`). `async_unload_entry` is not called.
  - URA registers **zero** `EVENT_HOMEASSISTANT_STOP` / `FINAL_WRITE` listeners (repo grep: 0 hits).
  - So `save_baselines` in `presence.py:7470`, `security.py:840`, `safety.py:3092`, `music_following.py:687` and `manager.py:488` runs only on an entry unload or reload, **never on a restart, clean or not**.
- **Physical corroboration (live DB, read `immutable=1` on 2026-09-29):**
  - Teardown-only savers are stale: presence 2026-09-14, security 2026-09-04, safety 2026-09-04, MF 2026-05-12.
  - Savers with a non-teardown path are fresh: hvac 2026-09-29 04:55 (rollover save `hvac.py:6651`) and coordinator_manager 2026-09-29 08:06 (per-boot save `__init__.py:4241`).
  - D0 measured presence census live 535 vs DB 528 over 15 days at about 2.9 restarts/day. The in-RAM count reverts to the DB value on every boot.
- **Caveat:** verified against the venv HA (2026.2.3), not the live 2026.9.x core source. The DB freshness split (teardown-only stale vs other-path fresh) is the discriminating live evidence.
- **Scope decision:** agree it is a **separate card**, because it is a write path, and this cycle is read-only. It must be minted now (G-PERSIST fired) with the corrected mechanism, ranked high. Every event-driven metric on the four teardown-only savers is capped by what accrues between restarts.
- **Interplay to record in this plan:** a slow metric on a teardown-only saver that matures in RAM reverts to `learning` at every boot. That is a nominal → partial flap per restart. It is not reachable today (all live presence metrics are mature in the DB; Safety is learning either way), but it is reachable for any new event-driven metric. The card should cross-reference `RESTART-SAFETY-DOCTRINE-1` (the plan's "(a): 21s-apart freeze" reading should be re-checked against this).

### MEDIUM-2: learning-first precedence can mask a real anomaly; putting severity first is free
- **Plan (D2 steps 1-2, INV-SEVERITY-PRECEDENCE):** precedence is learning → severity, and INV-SEVERITY-PRECEDENCE only guarantees the state "if … aggregate learning is ACTIVE".
- **Reachable mask:** in the HVAC detector (n = 5, threshold `max(1, 5//2) = 2`, `coordinator_diagnostics.py:1138`), with exactly one mature metric firing, the aggregate reads LEARNING and the sensor says `learning` while a persisted anomaly is active.
- **Why severity-first is safe:** a persisted anomaly can only come from a mature metric (`record_observation` gates on `baseline.sample_count >= _min_samples_for`, `:1068`), so it is never a learning artifact. Ordering severity → learning → partial → nominal masks nothing. It is also byte-identical on the whole INV-NOOP domain, where the aggregate is ACTIVE.
- **No flap from this ordering:** `_active_anomalies` latches until restart; the only clear site is the HVAC short-cycle rollover, `hvac.py:6538`.
- **Fix:** reorder, or state the masking residual explicitly in INV-SEVERITY-PRECEDENCE and D2.

### MEDIUM-3: fold the one-line `save_baselines` snapshot fix into D1 and correct the parked card's premise
- **Code:** `save_baselines` iterates `self._baselines.items()` across `await db.execute(...)` (`coordinator_diagnostics.py:1392-1407`). Card `ANOMALY-SAVE-BASELINES-DICT-MUTATION-1` (HVAC W4) has `why:` "NOT reachable from the new rollover save, because every place that adds a baseline in the HVAC coordinator runs under the decision-cycle lock."
- **That premise is false today:** the sensor properties call `get_learning_status` / `get_status_summary`, which call `_get_baseline` (`:1132`, `:1193`, `:1229`) outside the lock and create a key for any metric without a row.
- **Concrete repro:** after W3 renames `short_cycle_rate` to `compressor_short_cycle_rate`:
  1. The orphan prune drops the old rows.
  2. The first rollover's `record_observation` creates only zone keys.
  3. During the save's `await`, an `SIGNAL_HVAC_ENTITIES_UPDATE`-driven state write runs `get_anomaly_status()`, which creates `(compressor_short_cycle_rate, house)`.
  4. `RuntimeError: dictionary changed size during iteration` is swallowed by `except Exception` (`:1409`), and the save is partial.
- **What the peek does:** it removes this trigger. The plan should claim that explicitly.
- **Recommended fix:** also land `for _key, baseline in list(self._baselines.items()):`, one line in the same file with no behaviour change (the Fix-LOWs-in-cycle rule). A new creator added later would otherwise bring the race back.
- **Card update:** mark it folded, with the corrected `why`.

### MEDIUM-4: two classifier ambiguities a builder will resolve arbitrarily
- **(a) An unwired metric that is fed.** D1 lists `ok` (by n) and `not_wired` (by declaration) without precedence. Specify: the data-derived reason wins (`ok`/`learning`), and a one-time WARNING names the stale declaration. The D4 meta-test still catches it in CI.
- **(b) The `scope` argument.** `get_learning_status(scope)` / `get_status_summary(scope)` take a `scope` argument. Specify what "best scope" means when `scope != "house"`. No production caller passes one; say "best-scope aggregation applies to the default house call only" or "always".

### LOW-1: D3 roll-up edits land on surfaces with no production reader
- `manager.get_system_anomaly_status` (`manager.py:888`), `manager.get_diagnostics_summary` (`:941`) and `base.get_diagnostics_summary` (`base.py:241`) are called only by tests and by the subclass `super()` chain. Grep: no sensor, button or service reaches them.
- The `get_worst_metric` fix (D1) therefore changes only a test-visible path. That is fine to keep; label it as such.
- The one live roll-up is `manager.get_summary` → `sensor.py:5426` (the PWA `status_per_coordinator`); D3's `coverage` key there is the valuable part.
- Pre-existing: `button.py:1486-1487` calls `manager.get_anomaly_summary`, which **does not exist** (hasattr-guarded), so the anomaly diagnostic dump silently omits the anomaly section. This is a natural KEEP+WIRE target for `get_coverage()`; card it.

### LOW-2: the §4 dashboard census is incomplete (display-only, harmless)
- Not listed: `lovelace.ura_v6` (in the sidebar; raw-text templates at `:2809`, `:2823`, entity rows `:1093`, `:2347`), `ura_v2:892`, `ura_v3:678/834/844`, `ura_diagnostics:630/717/786`, and the second v7 auto-entities card (`ura_v7:4022-4040`, no exclude).
- All render raw state; `partial` shows as text.
- No automation, template helper or script reads the sensors: grep of `/Users/okosisi/ha-config/*.yaml` and `.storage` (the only hit is the `presence_anomaly_sensitivity` option key).
- PWA `Safety.tsx:59-72` `safetyCardCls` maps an unknown state to no class; Security/Presence render raw text. Confirmed display-only.

### LOW-3: two acceptance criteria do not discriminate
- **Phantom check (§12 line 313):** `count(*) … short_cycle_rate … scope='house'` is 1 before and after, because the row exists (`('hvac','short_cycle_rate','house',0,0.0,1.0,None)`). Use instead either:
  - after W3, no `(compressor_short_cycle_rate, house)` row ever appears; or
  - the count of rows with `sample_count=0 AND last_updated IS NULL` does not grow (5 today: hvac ×3, presence ×1, security ×1).
- **anomaly_log ±25%:** hvac has 0 rows in 30 days, so ±25% of 0 is vacuous. State the hvac criterion as "still 0", or drop it.

### LOW-4: spec the synthetic per-metric entry
- When a requested-scope row is absent, the entry must equal a fresh `MetricBaseline` (mean 0.0, std 1.0 from default `variance = 1.0`), built but not stored. Otherwise the golden diff in `test_house_only_detector_summary_byte_identical` drifts for fresh installs.
- Also document that per-metric `active` stays requested-scope. `short_cycle_rate` shows `active: False` at the top level while `metrics_active_ratio` counts it; the new per-metric `reason` explains why.

### LOW-5: mixed naive and aware `last_updated`
- D3 `last_updated` = "max ISO string across scopes, raw". MF rows are naive (`2026-05-12T04:48:24.220732`); newer rows are `+00:00`.
- A lexicographic max within one metric is safe while formats do not mix across scopes. Say so, or normalise.

---

## Checks that hold (with evidence)

| Question | Result |
|---|---|
| Can a scope-aware status read create or erase baseline rows? | **Holds, as specified.** `_scopes_for` iterates only existing `self._baselines` keys. The only other creator stays `record_observation` (`:1066`), and the only eraser is the load-time orphan prune for undeclared metrics (`:1351-1372`), which is unchanged. Test `test_status_reads_do_not_create_baselines` with its drill is discriminating. |
| Can a phantom `(metric, house, 0)` row loaded from the DB win the best-scope pick? | **No.** Best scope is the max `sample_count`, so the live zone rows (15/15/15) beat the phantom (0). |
| Does any trust consumer read the state string? | **No.** `manager.get_summary` / `get_system_anomaly_status` read `get_worst_severity()`. The NM `anomaly_status` (`notification_manager.py:846`) is an independent heuristic. No automation reads it. Adding `partial` is safe while severity is untouched. |
| Five projection duplicates | Confirmed: `sensor.py:6213-6216`, `:6828-6831`, `:7791-7794`, `hvac.py:6820-6830`, `security.py:2478-2488`. The HVAC and Security coordinator methods have only `sensor.py:7078` / `:12316` as callers. There is no sixth AnomalyDetector sensor. `sensor.ura_notification_anomaly` and `sensor.ura_circuit_anomaly` are not detector-backed. |
| AnomalyDetector construction sites | 6, as the plan says (`hvac.py:1670`, `security.py:765`, `safety.py:1166`, `music_following.py:238`, `presence.py:2369`, `manager.py:232`). No subclass or other instance. |
| Partial/nominal flap from coverage | **None from time.** D5 is parked, and counts only increase within a process. The only flap sources are the restart regression (M1) and an ε-floored degenerate rule (HIGH-2). |
| Knob ladder | D1-D4 add no number. The degenerate rule adds one if a floor is used; REUSE `_MIN_VARIANCE` at rung 1 (HIGH-2). The D5 constant is correctly rung 1. |
| Invariants are falsifiable | INV-COVERAGE, INV-SEVERITY-PRECEDENCE and INV-NOOP are each falsifiable by a concrete detector state. INV-COVERAGE needs amending for the degenerate choice (HIGH-1), and INV-SEVERITY-PRECEDENCE should drop its ACTIVE precondition (M2). |
| HVAC live-criterion discrimination (§12 line 309) | Good. The old code gives `nominal`, `2/5` and `short_cycle_rate` silent; a half-fix gives `partial` + `never_fed`; the full fix gives `partial` + `≥3/5`. HVAC metrics are not degenerate (live variances 4.04 / 1.11 / 6.52 / 0.60 / 3.82). |
| MAXSAMPLES kept separate (§7) | Agree. Different accumulator path; `load_baselines` does not restore `max_samples` (`:1340-1347`), which is verified. |

## Must-fix before build dispatch
1. **HIGH-1:** re-plan around the degenerate decision. Fill §2.3, write G-STALE / G-PERSIST / G-PREDICT verdicts with their numbers, and reconcile INV-COVERAGE, §8, §9 and §12.
2. **HIGH-2:** choose annotation vs blind-reason. If blind: raw `variance`, n ≥ gate, best scope, exact-0 or hysteresis, knob rung. Card the Security metric shape and the MF idle/legacy baseline.
3. **M1:** mint `ANOMALY-BASELINE-DIRTY-SAVE-1` with the corrected mechanism (teardown never runs on an HA restart) and fix the §3 text.
4. **M2:** reorder to severity-first, or document the masking residual.
5. **M3:** fold the `list(self._baselines.items())` snapshot and correct the W4 card's premise.
6. **M4:** specify both classifier ambiguities.

LOW-1 to LOW-5 can be fixed in the plan text in the same pass.

## Bug-class tally
| Class | Findings |
|---|---|
| #53 computed-but-not-consumed | HIGH-1 (addendum rule unconsumed), HIGH-2 (`.std == 0` never fires) |
| #63 coincidental equality / concept split | HIGH-2 (constant ≠ blind; MF legacy ≠ coverage) |
| Restart safety / in-memory accrual | M1, M3 |
| Precedence masking | M2 |
| #62 hollow anchor (avoided) | LOW-3 (non-discriminating live criteria) |

---

## Re-check (REV 2), 2026-09-29

**Scope:** a targeted re-check of REV 2 against the round-1 findings, plus the pieces REV 2 added (D3b button wiring, D6 dashboard edits, best-scope rule). Read-only. The code was verified at `4233304dc`. Live `.storage/lovelace.ura_v8` and `lovelace.ura_v7` were read over Samba, and the v8 JSON was diffed against the committed snapshot.

### Verdict: **FIX-PLAN-FIRST (text-only)**

Every round-1 finding is closed. Three new issues need a sentence or two each in the plan. Without them, the D6 dashboard edit can wipe out live v8 edits, and one or two live-validation checks can fail for reasons that have nothing to do with the code. No code design changes. **No third review round is needed**: the orchestrator can check the edits against the list below.

### Round-1 closure

| Finding | Status | Where in REV 2 | Evidence |
|---|---|---|---|
| **HIGH-1** D0 incomplete / G-PREDICT bypass | **CLOSED** | §2.1 (every cell filled), §2.3 (numbers verbatim, 5 phantom rows), gate table (G-PREDICT re-planned, G-STALE, G-PERSIST FIRED with dates), §8, §12 | The §8 predictions match INV-COVERAGE: HVAC `partial` 3/5 (two `not_wired`, short_cycle_rate `ok` via zone), Security `partial` (one `not_wired`), Presence `nominal` 3/3, Safety `learning` 42/720 (its 1-metric threshold is `max(1,0)`=1, not met), MF `nominal` + constant. The blind set {learning, never_fed, not_wired, stale} covers exactly best-n < gate, so `nominal` (precedence step 4) can only be reached when no metric is blind. Wording nit: G-STALE is really "not evaluable" (Q3 was absent) rather than "not fired". It is acceptable because D5 is parked with an explicit revival trigger and the probe fix makes an empty Q3 visible. |
| **HIGH-2** degenerate ⇒ blind | **CLOSED** | D1 "Annotations", §1.1 row, §6 INV-COVERAGE last sentence, D2 matrix row "active + constant-mature only → nominal", `test_constant_baseline_is_annotation_not_blind`, §12 Security/MF rows | The rule reads raw `variance == 0.0` (stored field, loaded verbatim at `coordinator_diagnostics.py:1340-1347`), never `.std` (floored at `:153-157`). The no-flap claim holds. Uncapped Welford (`:167-172`) after a deviation gives v_k = v0·n0/(n0+k), which never reaches 0.0. With `max_samples` > 0 the decay is geometric and would take about 10^5–10^6 samples to underflow, so it is unreachable in practice. The test arithmetic checks out: \|3−1\|/0.1 = 20 → CRITICAL, and the post-deviation variance is > 0. |
| **M1** persistence mechanism | **CLOSED** (text) | §3 last row, §13 | The mechanism is corrected. Nit: the card now exists as **`ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1`** (`kanban.data.yaml:30363`). Cite that ID in §3, §9 and §13 in place of "the M1 card". |
| **M2** severity first | **CLOSED** | D2 precedence 1-4, INV-SEVERITY-PRECEDENCE (precondition removed), matrix row 1 | The `record_observation` gate is at `:1069` (the plan says `:1070`; immaterial). `get_learning_status` has display-only consumers (grep: `sensor.py` ×4, `hvac.py:6824`, `security.py:2482`, `manager.py:909`, and none in the severity path), so the reorder cannot change severity. |
| **M3** snapshot + premise | **CLOSED** | D1 "Other changes", §3a, `test_save_baselines_survives_concurrent_key_insert` + drill, §11 state-of-play update | — |
| **M4** reason precedence + best scope | **CLOSED** | D1 "Reasons (M4a)" (first match wins; data beats declaration; one-time WARNING), "Best scope (M4b)", "`scope` argument semantics" | — |
| **LOW-1** | **CLOSED** | D3b, §1.1, D1 `get_worst_metric` note | See N-3 for a small residual. |
| **LOW-2** | **CLOSED** | §4 rows v6/v2/v3/ura_diagnostics, v7 (2) | — |
| **LOW-3** | **CLOSED** | §12 phantom count ≤ 5 + post-W3 key check; ±25% dropped with reason | — |
| **LOW-4 / LOW-5** | **CLOSED** | D1 "Synthetic entry"; D3 `last_updated` parse → aware max; `test_last_updated_mixed_naive_aware_normalised` | — |

### New findings

#### N-1 (MEDIUM): D6 can overwrite the v8 edits applied at 00:53 today. Pin the write mode and add a backup step
- **Evidence:**
  - Live `.storage/lovelace.ura_v8` has mtime 2026-09-29 **00:53**.
  - The committed snapshot `docs/ha-config-snapshots/lovelace_ura_v8_backup_2026_09_29.json` has mtime **00:51**.
  - A semantic diff of `live['data']['config']` against the snapshot shows **2 changed cards**: the HVAC zone markdown, which now reads `away_due_at` (v5.103.22), and the arrester markdown, which now reads `grace_until` / `compromise_until`.
  - **The snapshot the plan cites (§4 row "v8 URA Anomalies", `:9971-9996`) is already stale and does not contain those edits.**
- **Hazard:**
  - D6 says only "ha-mcp dashboard save". `ha_config_set_dashboard` has three modes, and `config` **replaces the whole dashboard**.
  - A builder or deployer who takes the snapshot, edits the two cards and pushes it with `config=` would silently revert the v5.103.22 dashboard work.
  - There is also no pre-write backup step. "Refresh the snapshot afterwards" is not a backup.
- **Fix (plan text, D6):**
  1. Before writing, read the **live** config with `ha_config_get_dashboard(url_path=…)`. Save it as `docs/ha-config-snapshots/lovelace_ura_v8_backup_<date>_pre_d6.json` and commit it. Do the same for v7.
  2. Write with **`patch` (or `python_transform`) plus the `config_hash`** from that read. Never use `config=`. The hash gives optimistic locking: a concurrent edit makes the write fail instead of being lost.
  3. Locate cards by content, not by index or line number:
     - v8 anomalies = `/views/6/sections/3/cards/1` today (`custom:auto-entities`, title "URA Anomalies");
     - hero = `/views/6/sections/1/cards/0` (`custom:button-card`, name "Coordinators");
     - v7 = `/decluttering_templates/ura_anomaly_list/card`.
     Assert these with `test` ops before `add`/`replace`.
  4. After the write, re-read and diff against the pre-D6 backup. The **only** differences allowed are the two exclude entries and the hero `label`. Then refresh the snapshot.
- **Hero label:** the current label is a full expression that returns `'mem '+…+ba` (the memory value plus Bayesian accuracy). D6's snippet elides it with "…". Specify **append** to the existing return value (`return 'mem '+…+ba+partialSeg;`), not replacement. As written, a builder may drop the memory and accuracy segments.
- **Class:** shared-config overwrite (a sibling of Bug Class #53: the recent edit is a consumer the change fails to account for).

#### N-2 (LOW-MEDIUM): the MF card is a duplicate, and the MF/Security live criteria are not robust to today's operator test
- **Duplicate card:** `MUSIC-FOLLOWING-NO-TRANSFERS-SINCE-MAY-1` already exists (`kanban.data.yaml:30379`, status investigating). Operator 2026-09-29: "Rarely use it. But will test today." §3 and §9 propose minting `MUSIC-FOLLOWING-IDLE-LEGACY-BASELINE-1`. Per the adjacency sweep, **extend the existing card**; don't mint a new one.
- **Live-criterion fragility (discriminating repro):**
  - MF metrics are not suppressed (`MUSIC_FOLLOWING_SUPPRESSED_FROM_PERSISTENCE = frozenset()`, `music_following.py:62`).
  - The legacy baseline has mean 0.0, variance 0.0, n = 1572 ≥ gate.
  - If the operator's test records one successful transfer, `transfer_success_rate` = 1.0 gives z = 1.0/0.1 = 10, which is **CRITICAL**. That writes a persisted `anomaly_log` row, and the MF sensor reads `critical` until restart.
  - It also clears `constant_baseline`, because variance becomes > 0.
  - The §12 MF criterion "`nominal`, `metrics_constant` lists both" then FAILS, even though the code is correct: INV-SEVERITY-PRECEDENCE requires exactly this outcome.
  - The same applies to Security if any non-LOW entry verdict occurs before validation.
- **Fix:**
  - Condition both criteria: "if no MF transfer / non-LOW security verdict since D0; otherwise expect state = the persisted severity and `constant_baseline: false` on that metric (INV-SEVERITY-PRECEDENCE)."
  - Check it by one-shot query of `anomaly_log` at validation time.
  - Also warn the orchestrator/operator that a test transfer today will likely raise a CRITICAL MF anomaly. It comes from the pre-existing hair trigger, not from this cycle, and it is evidence for the MF card.

#### N-3 (LOW): D3b's failure path is silent
- **Evidence:** `button.py:1484-1489` wraps the call in `except Exception: pass`. D3b makes `manager.get_diagnostics_summary()` the first production reader of `get_system_anomaly_status`, `base.get_diagnostics_summary` and three subclass overrides (`presence.py:7707`, `safety.py:2743`, `music_following.py:698`, all read and synchronous). A latent exception in any of them would drop the whole `anomaly_summary` section, and the §12 button check would fail with no reason logged.
- **Fix:** `except Exception as e: dump["anomaly_summary_error"] = repr(e)`. That is one line, and it follows the existing `db_error` pattern at `:1463-1464`.
- **Otherwise the wiring is sound:**
  - `get_diagnostics_summary` exists (`manager.py:941`), is synchronous, and its output is JSON-able under `default=str`.
  - Its read paths become non-creating under D1, so pressing the button cannot create phantom rows. **D3b must not land without D1**; they are in the same cycle, so this is satisfied.
  - `get_system_anomaly_status` calls `_maybe_reset_daily_counters()`, the same side effect `get_summary` already has on every summary-sensor read.

#### N-4 (LOW): best-scope rule: the phantom tie is harmless; state one expected outcome
- **Phantom tie:** a phantom `(m, house, 0)` can only tie with another n = 0 scope. Tie-break picks `house` (`"house" < "zone…"`), and n = 0 either way, so the reason is the same (`not_wired`/`never_fed`). `constant_baseline` requires n ≥ gate, so it is unaffected, and `last_updated` skips the phantom's None. **Harmless.**
- A tie between two fed scopes with different variance makes `constant_baseline` depend on name order. That is deterministic, annotation only, and harmless.
- **One gap:** §6 lists "zone_1 mature with zone_2 at 0" as a config to break but gives no expected result. Under the best-scope definition, the expected result is `ok` + `nominal`: a starved *sibling scope* is invisible at the top level and visible only in the nested `scopes`. State that expectation, and list per-scope starvation as a non-goal in §13. Otherwise build-review A will flag the designed behaviour as an INV-COVERAGE leak.

#### N-5 (nit): `metrics_constant` for Presence
- §2.1 marks Presence as "not reported" for the constant column, although the D0 Q1 output printed raw variance for every row. Fill it in, or add `metrics_constant == []` to the Presence §12 row so it discriminates.
- Out of scope, pre-existing: the v8 anomalies exclude has no `learning`, so Safety (`learning`) is already listed there today. Mention it to the operator alongside the D6 ruling ("is `learning` an anomaly?"); don't change it here.

### Must-fix before build dispatch (plan text only)
1. **N-1:** D6 procedure: back up the live config first, use patch/python_transform with `config_hash` (never `config=`), locate cards by content with `test` ops, append the hero label rather than replace it, diff after the write, and cite live paths instead of the stale snapshot's line numbers.
2. **N-2:** reuse `MUSIC-FOLLOWING-NO-TRANSFERS-SINCE-MAY-1`; make the MF and Security §12 criteria conditional on no severity event since D0.
3. **N-3/N-4/M1-ID:** the one-line error capture in D3b; the expected outcome for a starved sibling scope plus the non-goal; cite `ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1`.

After these edits, the plan is **APPROVE** for build. The orchestrator can verify the edits; no further reviewer pass is needed.
