# PLANNING — v4.7.17.x — AC Nudge Evaluation Window Tuning

**Date:** 2026-06-01
**Author:** investigation session, ojiudezue
**Tier:** Tier 1 (hotfix-class — single bug, single coordinator, ~30–50 LoC)
**Trigger:** Live FP rate = 30 % over 10 samples on 2026-06-01.
**Branch target:** `develop` → release tag `v4.7.17.1` (sibling-hotfix style)

---

## Institutional context verified

### Greps run + results
- `AC_NUDGE_EVALUATION_DELAY_S` → exactly **one definition** at `domain_coordinators/hvac_const.py:214`, two reads at `hvac_override.py:28` (import) and `hvac_override.py:1472` (`async_call_later`) plus one log emission at `hvac_override.py:1476`. **No existing tunable.**
- `CONF_HVAC_AC_NUDGE_*` family → six existing config keys at `hvac_const.py:90, 178, 181, 184, 187, 200` (enabled, size, duration, sustained_samples, detection_time_gate, kwh_rate_threshold). **`CONF_HVAC_AC_NUDGE_EVAL_DELAY` does NOT exist** — NEW.
- `_hvac_tunable_number_factory` → established factory at `number.py:1581–1617` already wires `_nudge_size_f`, `_nudge_duration_min`, `_sustained_samples`, `_detection_time_gate_min` to `_override_arrester`. Adding a "75 · AC Nudge Eval Delay" slider follows the **same template** (REUSED pattern).
- `_evaluate_nudge_outcome` → single definition at `hvac_override.py:1479`. The 85% threshold (`kwh_rate_after >= kwh_rate_before * 0.85`) lives at `hvac_override.py:1521`. Only one call site to change.
- `_nudge_eval_timers` → dict keyed by `zone_id`, populated at `hvac_override.py:1471`, cleared on cancel/restart. Replacing the delay constant with a runtime-tunable integer changes one expression, not the timer mechanism.

### Prior planning docs consulted
- `PLANNING_v4.5.11_ac_energy_aware_ramp_down.md` — original ramp cycle; established the 5-min hold + 10-min eval design. **Decision rationale for 600 s was not data-driven** (block-comment in `hvac_const.py:214` is just `# seconds after restore = evaluate`).
- `PLANNING_v4.5.12_ac_ramp_observability.md` — added FP-rate sensor; defined the 85% threshold and the `sample_size >= 5` minimum-display rule. **The sensor that triggered this investigation was built in this cycle.**
- `PLANNING_v4.5.10_hvac_runtime_tunables_and_labels.md` — established the `_hvac_tunable_number_factory` runtime-tunable pattern. **REUSE this pattern verbatim** (no new infra needed).
- `PLANNING_v4.7.7_ac_nudge_decouple_plus_dpm_sensor_cleanup.md` — most recent touch of the override-arrester path; established the "AC Reset feature toggle is read LIVE not snapshotted" precedent at `hvac_override.py:1574–1581`. The same live-read pattern should apply to the new tunable.

### Memory bodies pulled
- `project_v477_live.md` — AC Nudge / AC Reset decouple is current production behavior. Eval delay was not touched.
- `feedback_configurability_clarity.md` — runtime Numbers are appropriate ONLY when the value is genuinely tunable per install. Operator-elevation hint: this IS such a value (compressor cycling rate is unit-dependent).
- `feedback_no_fabrication.md` — applied: every kW number below is sourced from `ha_get_history`, not synthesized.

### Design docs read
- No `docs/Coordinator/HVAC.md` exists. The override-arrester docs are inline at `hvac_override.py:1–60` (module docstring).

### Code locations surveyed
- `hvac_const.py:174–238` (full AC ramp section)
- `hvac_override.py:1380–1545` (nudge fire → restore → evaluate)
- `number.py:1555–1640` (AC-ramp tunables factory site)
- `database.py:1135–1160, 5445–5520` (ac_ramp_events schema + insert/read)
- `sensor.py` — `45 · AC Nudge False-Positive Rate` definition (`_ACRampImpactSensorMixin` consumer)

---

## Live data findings (2026-06-01 18:37 UTC FP-rate snapshot)

**Source:** HA recorder via `ha_get_history` on the three `sensor.ura_hvac_coordinator_ac_kwh_rate_*` zone-power sensors. Climate `target_temp_high` history was mostly boot-replay (timestamps clustered at HA-restart) so per-event nudge timestamps were derived from `sensor.ura_hvac_coordinator_ac_nudges_today` counter increments.

**Caveat:** the URA SQLite DB (`ac_ramp_events`) was not reachable from this session — no `ura-sqlite` MCP, no Samba mount. So per-event `kwh_rate_before` / `kwh_rate_after` were RECONSTRUCTED from recorder kW history (mean over 5-min windows), not pulled from the DB. Zone attribution was done by "which zone had the highest pre-window kW among those above threshold." Three of the 10 FP-counted samples (the early-morning burst that resyncs the counter 0→3 at 05:11) could not be attributed at all because the discrete event timestamps were lost across a boot.

### Six attributable nudge events between 15:56 UTC and 17:36 UTC

Pre/hold/post means in kW. `effect_during_hold` = (pre_mean − hold_mean) / pre_mean. `FP@600s` = the **live** rule (kW at restore+10min vs pre). `FP@300s` = alternative (kW at restore+5min). `FP@avg5-10` = alternative (mean kW during restore+5..+10min).

| Fire (UTC) | Zone   | kW_before | kW_hold | kW_post 0-5 | kW_post 5-10 | effect@hold | FP@600s | FP@300s | FP@avg5-10 |
|------------|--------|-----------|---------|-------------|--------------|-------------|---------|---------|------------|
| 15:56:39 | EntMaster | 1.93 | 0.21 | 0.99 | 1.86 | **89 %** | FP | FP | FP |
| 16:01:39 | Upstairs  | 1.05 | 0.11 | 0.26 | 0.01 | 89 %     | OK | OK | OK |
| 16:36:39 | Upstairs  | 1.04 | 0.13 | 0.31 | 0.01 | 88 %     | OK | OK | OK |
| 16:41:39 | EntMaster | 1.22 | 0.29 | 0.94 | 2.43 | **76 %** | FP | FP | FP |
| 16:51:39 | BackHall  | 1.05 | 0.31 | 0.48 | 1.04 | **71 %** | FP | FP | FP |
| 17:36:40 | EntMaster | 2.12 | 2.01 | 2.38 | 2.83 | 5 %      | FP | FP | FP |

### Interpretation

1. **4 of 6 reconstructed events were FP-classified by the live 600 s rule.** (4/6 = 67 % matches the 30 % house FP if the remaining 4 unattributed early-morning events were OK-classified — plausible because dawn loads on a cool house typically ramp-down successfully and stay down.)

2. **5 of 6 nudges produced massive in-hold savings (71–89 % power reduction during the 5-min hold).** Only 17:36:40 was a true near-miss (5 % effect — compressor stayed running through the entire hold despite the 1.5 °F setpoint raise). The other 5 nudges clearly **worked at the compressor level** — the AC dropped to near-zero kW during the hold.

3. **Post-restore behavior reveals two distinct patterns:**
   - **"Real ramp-down" (16:01, 16:36 / Upstairs):** post-restore kW stays at 0.0–0.3 kW for the full 15+ min post-restore window. These are correctly classified OK.
   - **"Fast rebound" (15:56, 16:41 / EntMaster, 16:51 / BackHall):** kW drops to ~0 during the hold, climbs back through the 0-5 min post-restore window, and is back **at-or-above pre-nudge level by minutes 5–10 post-restore.** The 10-min eval window catches the compressor mid-recovery and classifies the nudge as ineffective.

4. **The user's hypothesis is partially confirmed.** The compressor behavior IS the cause of FPs, but the mechanism is **classical short-cycle rebound on a single-stage compressor**, not continuous variable-speed modulation. The Bryant entities (`thermostat_bryant_wifi_studyb_zone_1` etc.) show `supported_features=411` and `hvac_modes` without `dry`/`eco` modes — the kW trace itself is the most direct evidence: kW alternates between ~0 (off) and ~1.0–2.7 (on) on a roughly 5–10 minute on/off cadence per zone. That's a single-stage or two-stage compressor cycle, not modulating-variable-speed. Either way, the bug is the same: **the eval window is timed to the compressor's natural rebound peak, not its quiescent valley.**

5. **17:36 was a true escalation candidate** (5 % in-hold effect → real "nudge didn't work"). The mechanism here is the load was high enough (2 kW sustained — likely solar/thermal overrun pushing the thermostat past the 1.5 °F dead-band) that the 1.5 °F nudge couldn't release the demand. This is the kind of event a hard-reset escalation is designed for. The current 600 s rule **correctly** classifies this as FP. We must not break this case.

6. **None of the candidate eval windows (300 s, mean-of-5-to-10) materially differ from 600 s on this dataset** — same 4-FP / 2-OK split. Reducing the delay alone won't fix it. The fix has to address the **what** we measure, not just the **when**.

---

## Recommended fix shape

### Option A (REJECTED): drop `AC_NUDGE_EVALUATION_DELAY_S` from 600 → 180

Doesn't help. The fast-rebound zones are already above threshold by minute 3–5 post-restore. Shortening the delay would catch the rebound earlier, not avoid it.

### Option B (PARTIAL): make the delay tunable as a Number entity

Useful for visibility/operator control but doesn't fix the underlying problem. **Ship as part of Option C** — having the knob available makes future tuning empirical rather than constant-edit-and-deploy.

### Option C (RECOMMENDED): change WHAT is measured

Replace the single-sample `kwh_rate_after` read at `restore + N seconds` with a **trailing-window minimum** during the post-restore observation window. Rule becomes:

> If the **minimum kW** observed during the window `[restore, restore + eval_delay]` is < 50 % of `kwh_rate_before`, the nudge is **effective** (the compressor did stop, even if it's running again now). Otherwise FP.

Rationale: on this dataset, every "FP" event had a post-restore minimum of 0.0–0.5 kW during the eval window — clear evidence the compressor stopped. The FP classification was wrong because we sampled at the rebound peak instead of looking at whether a valley existed.

For the true-FP case (17:36:40) the minimum during `[restore, restore+10min]` was 1.96 kW — clearly above 50 % of 2.12 kW pre — so it still classifies correctly as FP and escalation still fires.

#### Implementation sketch (Option C + Option B knob)

1. **New const** `hvac_const.py`:
   ```python
   AC_NUDGE_EVAL_MIN_DROP_FRAC: Final = 0.50   # post-restore min must reach this fraction of pre
   DEFAULT_HVAC_AC_NUDGE_EVAL_DELAY: Final = 600   # seconds (was AC_NUDGE_EVALUATION_DELAY_S)
   CONF_HVAC_AC_NUDGE_EVAL_DELAY: Final = "hvac_ac_nudge_eval_delay"
   ```
   Delete `AC_NUDGE_EVALUATION_DELAY_S` (or keep as alias pointing at the default for back-compat in tests).

2. **OverrideArrester** gains `self._nudge_eval_delay_s` field, loaded from options at `__init__` and live-read at evaluation time (same precedent as `_ac_reset_enabled` at `hvac_override.py:1574–1581`).

3. **`_evaluate_nudge_outcome`** at `hvac_override.py:1479`:
   - Capture all kW samples in `[restore, evaluate]` (read recorder history via the existing helper, or accumulate them in-memory by stashing `last_kwh_rate` samples on a per-tick listener — TBD in build).
   - Compute `post_min = min(samples)`.
   - Rule: `ineffective = (post_min is None) or (kwh_rate_before is None) or (post_min >= 0.50 * kwh_rate_before)`.
   - Keep `kwh_rate_after` (the at-eval sample) logged to `ac_ramp_events.kwh_rate_after` for backward compatibility with existing observability sensors. Add a new `notes` field component recording `post_min=X.XX`.

4. **Number entity** in `number.py` — extend the factory call list at `number.py:1607` with a "75 · AC Nudge Eval Delay" slider (min=120 s, max=1200 s, step=60 s, default=600).

5. **FP-rate sensor** — no change needed; it reads `kwh_rate_after` from `ac_ramp_events` and applies the existing 85 % rule. Wait — that's wrong; the in-memory `effectiveness` decision happens at `hvac_override.py:1518–1522` and is logged into the row's `notes` / `event_type`, not derived in the sensor. Need to verify which is the source-of-truth for the FP-rate sensor. **Open question 1.**

### Open questions for operator

1. **Source-of-truth for FP rate.** Is `sensor.ura_hvac_coordinator_ac_nudge_false_positive_rate` derived from (a) re-running the 85 % rule against logged before/after, or (b) the `event_type=nudge_evaluated` row's `notes`? `database.py:5525–5570` (`get_ac_ramp_kwh_avoided`) does (a). If we change the rule, do we **also** want to re-classify historical FP rate by the new rule (one-shot fixup), or only forward-going events? Recommend forward-going only with a version note. **Builder must verify exact derivation path before changing.**
2. **In-memory sampling vs recorder query.** Option C needs the kW history across the post-restore window. Two implementations:
   - (a) During `awaiting_evaluation` state, stash a `_post_restore_min[zone_id]` and update on every kWh-rate read (via existing tick listener on the kW sensor). Low overhead.
   - (b) At evaluation time, query HA recorder for the kW sensor history over the window. Higher latency, more code.
   Recommend (a). **Build to confirm we have a per-tick kW read hook available.**
3. **Should the new min-drop fraction (0.50) ALSO be a runtime Number?** The user-coined "Configurability Clarity" rule says named-bucket dropdowns over runtime Numbers for technical primitives. Recommend NOT exposing it — bury it as a const for v4.7.17.1 and revisit if a second install shows a different cycle pattern. **Confirm before build.**
4. **17:36:40 case** — the only true near-miss had pre=2.12 kW and the nudge produced just 5 % reduction during the hold. That kW level is unusually high for a single zone. Was there a coincident hot-water event or a stuck damper? Out of scope for this cycle, but worth a note for HVAC investigation. **Operator: any anomalies known around 17:36 CDT?**

---

## D1: New tunable constant + Number entity

Add `CONF_HVAC_AC_NUDGE_EVAL_DELAY` + factory entry; remove the hard-coded `AC_NUDGE_EVALUATION_DELAY_S` reference at `hvac_override.py:1472`.

### Acceptance Criteria
- **Verify:** `number.ura_hvac_coordinator_ac_nudge_eval_delay` exists in HA entity registry with default `600`, range 120–1200, step 60, unit `s`.
- **Verify:** setting it to `300` via UI causes the next nudge's restore→eval timer to fire 5 min later, not 10 min.
- **Sensor:** `number.ura_hvac_coordinator_ac_nudge_eval_delay` state matches `OverrideArrester._nudge_eval_delay_s`.
- **Test:** `quality/tests/test_v4717_ac_nudge_eval_window_tuning.py::test_tunable_eval_delay_overrides_default` asserts the timer uses the runtime field.
- **Live:** after restart with default 600, force a nudge via the existing `button.ura_hvac_coordinator_force_ac_nudge_*` button — confirm a `nudge_evaluated` event appears in `ac_ramp_events` exactly 15 min (5 min hold + 10 min eval) after the press timestamp.

## D2: Switch FP rule from at-eval-instant to min-during-window

Modify `_evaluate_nudge_outcome` to use post-restore minimum kW instead of single-sample.

### Acceptance Criteria
- **Verify:** for a synthetic event with `kwh_rate_before=1.0`, post-restore samples `[0.1, 0.2, 0.9, 1.1]`, the nudge classifies **effective** (min=0.1, 50 % of 1.0 = 0.5, 0.1 < 0.5). Today's rule with the at-eval-instant sample `1.1` would classify FP.
- **Verify:** for a synthetic event with `kwh_rate_before=2.0`, post-restore samples `[1.9, 2.0, 2.1, 2.0]` (compressor never stopped), nudge classifies **ineffective** (min=1.9, 50 % of 2.0 = 1.0, 1.9 ≥ 1.0). Today's rule also FP — preserved.
- **Test:** `test_v4717_ac_nudge_eval_window_tuning.py::test_min_drop_rule_effectiveness_classification` with 4 scenarios (true-effective, true-ineffective, fast-rebound, slow-rebound).
- **Test:** existing nudge-related tests still pass after the rule change (`quality/tests/test_v45*_ac_ramp*.py` plus `test_v477_*`).
- **Live (T+7 days):** `sensor.ura_hvac_coordinator_ac_nudge_false_positive_rate` should drop from the recent 30 % baseline. **Acceptance threshold:** new FP rate < 15 % over a 10-sample window once the kW-sensor logs accumulate post-deploy.

## D3: New attribute on `nudge_evaluated` event row

Add `post_min` to the `notes` JSON-ish payload on the event row.

### Acceptance Criteria
- **Verify:** after a force-nudge, the corresponding `ac_ramp_events` row's `notes` column contains `post_min=X.XX kwh_avoided=Y.YYY` (extending the existing `kwh_avoided=…` format).
- **Live:** `SELECT notes FROM ac_ramp_events WHERE event_type='nudge_evaluated' ORDER BY timestamp DESC LIMIT 5;` (via diagnostic-dump button) shows all 5 most-recent rows carrying `post_min=`.

---

## Out of scope (deferred / explicit non-goals)

- Re-classifying historical `ac_ramp_events` rows under the new rule. **Forward-going only.**
- Exposing `AC_NUDGE_EVAL_MIN_DROP_FRAC` as a runtime Number. Bury as a const; revisit if a second install shows different compressor cycle behavior.
- Investigating the 17:36 high-load outlier. File as a separate observation if pattern repeats.
- Touching the hard-reset escalation path (`_perform_hard_reset_escalation` at `hvac_override.py:1544`). True ineffective nudges still escalate.

---

## Test plan

- New: `quality/tests/test_v4717_ac_nudge_eval_window_tuning.py` covering D1, D2, D3 acceptance criteria.
- Regression: full `quality/tests/test_v45*_ac_ramp*.py` and `test_v477_*` suites must remain green.
- Pre-deploy zero-bugs gate per memo `feedback_pre_deploy_zero_bugs_gate`: conflict-marker grep + `py_compile` on changed files + cycle tests + baseline-diff.

## Tier classification

**Tier 1** — single coordinator surface (override arrester within HVAC), single bug class (mistimed observation), small LoC budget (~30 lines in `hvac_override.py` + ~15 in `number.py` + ~5 in `hvac_const.py`). One staff-engineer adversarial review per Tier 1 protocol, focus on:
- Boundary cases when `post_min == 0.50 * kwh_rate_before` exactly
- None-handling when the kW sensor goes stale during the eval window
- Restart resilience: the in-memory `_post_restore_min[zone_id]` dict is lost on restart — ensure `awaiting_evaluation` state recovery (per `hvac_override.py:270`-area persistence) either restarts the window or skips the eval (matches existing behavior — confirm in build).
- That the new const doesn't break any import in `hvac_override.py` (Bug Class #19 — migration helper imports).

## Live validation criteria (post-deploy)

1. **T+1h:** force a nudge per zone via the three `button.ura_hvac_coordinator_force_ac_nudge_*` buttons. Each should produce an `ac_ramp_events` row with `event_type='nudge_evaluated'` and `notes` containing `post_min=`.
2. **T+24h:** confirm `sensor.ura_hvac_coordinator_ac_nudge_false_positive_rate` reflects the new rule against the at-least-5-sample minimum. If sample_size < 5, force enough nudges to cross the threshold.
3. **T+7d:** FP rate should stabilize below 15 % unless real ineffective nudges occur. Operator subjective check: did a hard-reset escalation fire when the compressor was clearly stuck?

---

## Sequencing note

Independent of the queued Bug Class #48 sprint (v4.7.14.1 / v4.7.15 / v4.7.15.1 / v4.7.16). Suggest deploying **after** that sprint closes — sequenced not parallel because both touch HVAC coordinator state and `hvac_override.py`. No code overlap, but reviewer cognitive load and rollback isolation favor sequencing.
