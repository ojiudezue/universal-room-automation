# Plan review — SAFETY-NM-REFIRE-UNWIRED-1 (Tier 2-DB, single adversarial plan review)

- Plan: `docs/planning/PLANNING_safety_nm_refire.md` (develop HEAD, incl. "Orchestrator rulings")
- Reviewer: ura-reviewer (plan review), 2026-10-15
- Read first: `docs/Coordinator/SAFETY_COORDINATOR.md` §5 (line 297 known-gap note), `PLANNING_safety_hazard_clear_on_recovery.md` rev 4.

## Verdict: **FIX-REQUIRED** (plan-text fixes only; D1/D2 code shape is sound)

The two code deliverables are correct and minimal. But the plan misdescribes what D1 actually
changes in NM, states an invariant that is wider than the reachable path and false on one path,
and over-claims test red-ness. All fixes go in the plan text and test list; none needs a new mechanism.

## Verification results (greps, not trust)

| # | Question | Result |
|---|---|---|
| 1 | Only NotificationAction site in safety.py? | **Confirmed.** `grep -n "NotificationAction(" safety.py` → single hit `safety.py:2579`. Safety→NM has no other path: the only route is `manager.py:1070-1081` (forwards `action.hazard_type or None`, `action.location or None`). Signals in safety (`SIGNAL_SAFETY_HAZARD` etc.) do not reach NM. |
| 2 | NM re-fire trace | `async_acknowledge` (`notification_manager.py:2859`) → `_start_cooldown` (`:2955`, cooldown from `COOLDOWN_CONFIG[hazard_type]`, `:196-205`) → `_cooldown_expired` (`:3008`) → `_re_evaluate_hazard` (`:3020`) → `coordinator.is_hazard_active(hazard_type, location)` (`:3039`) → re-fire `async_notify(severity=CRITICAL)` (`:3046-3054`). **Cooldown/re-eval exists only after an ACK of a CRITICAL in ALERTING** (`_enter_alerting` `:2515`). |
| 3 | Q2 comfort re-paging | **No regression via the re-eval path.** Only CRITICAL enters ALERTING. Safety CRITICAL hazards are: SMOKE (`safety.py:1864`), CO ≥100 ppm (`NUMERIC_THRESHOLDS` CO CRITICAL), FLOODING (`:1917`, `:1938`). HIGH_CO2/HIGH_TVOC/humidity/OVERHEAT/FREEZE top out at HIGH/MEDIUM (`NUMERIC_THRESHOLDS`, `LOW_HUMIDITY_THRESHOLDS`). Nothing needed in NM policy for Q2. But see F1: D1 changes other NM policies. |
| 4 | Other `is_hazard_active` consumers | **Only NM `:3039`.** Repo grep: defs at `base.py:237`, `safety.py:3398`, `security.py:825`; sole caller `notification_manager.py:3039`. No sensor/dashboard/house-state reader. Hold-aware change is contained. `:roc` stripping preserved by the D2 reference code; existing test `test_safety_hazard_clear_on_recovery.py:515-525` keeps covering it. |

## Findings

**F1 — HIGH — plan omits D1's real blast radius in NM (§5 D1 "Blast radius", §10 Q2, ruling Q2).**
Today every Safety alert reaches NM with `hazard_type=None`, so `is_life_safety_hazard()` is False for
smoke/CO/flooding everywhere in NM. D1 flips all of these at once for safety life-safety tokens:
- CRITICAL repeat cadence: 300 s decay ladder (phase1→phase2→daily) → **30 s fixed, never decays** (`notification_manager.py:2578-2579`, `:2634`).
- Boot-settle collapse exemption (`:1508-1509`).
- DND safety-floor bypass (`:4184`), mute bypass in router (`:4235`), token-bucket bypass (`:3889-3892`, `:3925`, `:4028`).
- Security-image override guard (`:1480`).
- Boot-settle dedup bucket split: key `(coord, hazard_type)` (`:658`) goes from one shared `("safety","")` bucket to per-type buckets.
- Cooldown length: smoke/CO from `DEFAULT_NM_COOLDOWN_DEFAULT` to 2 min; flooding to 5 min (`COOLDOWN_CONFIG`).
These are mostly the intended life-safety contract, but the plan says the only effect is the re-fire gate
and that comfort hazards get "a 300 s non-life-safety re-fire" (wrong: non-CRITICAL never enters ALERTING).
Fix: rewrite D1 blast radius as this list; state each is intended; add a test that a safety smoke
CRITICAL gets `_repeat_phase()=="life_safety"` (fails on develop today).

**F2 — HIGH — INV-REFIRE clause 2/3 is false on the unacked REPEATING path (§1).**
`_repeat_alert` (`notification_manager.py:2645+`) never consults `is_hazard_active`, and NM has no hazard-cleared hook from Safety (grep of NM/safety for a clear signal: none). Repro: smoke at Study A, nobody acks; detector recovers at t=60 s; hold clears at t=360 s; NM keeps paging CRITICAL every **30 s** (post-D1) indefinitely until someone acks. Today it decays (300 s→1800 s→daily). This matters this week (operator away, D1 makes the repeat 10x faster for an already-cleared detector). Fix (pick one, in the plan): (a) narrow INV-REFIRE to "after ACK, at cooldown expiry" and card the repeat-path stop-on-clear as a sibling; or (b) add an `is_hazard_active` check in `_repeat_alert` that drops to IDLE when the source says cleared. (b) touches NM's shared repeat loop; if chosen, it needs its own mutation-anchored test and the security caveat in F4.

**F3 — MEDIUM — invariant set is wrong (§1).**
OVERHEAT is listed as life-safety but is not in `NM_LIFE_SAFETY_HAZARDS` (`const.py:3391-3399`) and is never CRITICAL. FIRE is never emitted by Safety (plan Q3 agrees). WATER_LEAK (HIGH, `safety.py:1868`) and FREEZE_RISK (max HIGH) never enter ALERTING, so clause 1 is vacuous for them. Restate the invariant's domain as CRITICAL safety hazards: `{smoke, carbon_monoxide (≥100 ppm), flooding}`. Note flooding's 5-min cooldown ≥ the 300 s hold, so clause 3 only bites for smoke/CO (120 s).

**F4 — LOW — pre-existing token mismatch in `security.py:825-828`.**
`is_hazard_active` checks `"intrusion"` but security emits `"intruder"` (`const.py:3393-3396` comment). Security alerts therefore never re-fire after cooldown either. Out of this card's scope; card it (do not fold in).

**F5 — MEDIUM — test claims (§5 D3, §8 D3).**
- "All five functions" but six are listed.
- `_true_when_active`, `_false_when_cleared`, `_true_on_relapse_during_hold` **pass on develop today** (D2 only changes the pending-clear branch). They are regression guards, not RED-first tests; say so. Only the D1-carry test, `_false_during_clear_hold`, and the round-trip are RED on develop.
- Round-trip test omits the ACK step. Cooldown starts only in `async_acknowledge` (`:2953`); without an ack the test exercises nothing. Also "re-fired exactly once" is ambiguous, because the re-fire re-enters ALERTING and starts repeats. Specify: count `async_notify` calls from `_re_evaluate_hazard` only, plus a negative twin (recover inside the cooldown, so the hold is pending at expiry → no re-fire, state IDLE). The twin is the discriminating test for clause 3 end to end.
- The relapse test should drive relapse through `_respond_to_hazard` (smoke detector re-on), not by calling `_record_sensor_relapse` directly. The real smoke path re-arms via `had_pending_clear` + `_LIFE_SAFETY_REARM_TYPES` (`safety.py:2487-2492`) and re-pages, which also covers clause 4 when NM is already IDLE.

**F6 — LOW — live acceptance (§8 D1) uses columns not verified.**
The query names `ts`/`coordinator_id`/`hazard_type`/`location` on `notification_log`; verify against the `database.py:4444-4485` DDL in the plan. The D2 live criterion keys on a log string; prefer a `notification_log` re-fire row (ground truth) per the no-display-prose rule.

**F7 — LOW — FLOODING location is a `", ".join(set(...))` (`safety.py:1919`).**
Iteration order of a rebuilt set can differ, so the stored NM `location` may not equal a later re-keyed `_active_hazards` entry → `is_hazard_active` False on a still-active multi-sensor flood. Rare. Note it; a `sorted()` there is a 1-line fix the builder could take in-cycle (Fix LOWs In-Cycle).

## Checklist
- Single emission site: PASS
- Knobs: PASS (no new numbers; the ladder table is accurate, though NM_REPEAT 30 s is newly *reached* by safety, per F1)
- Falsifiable invariant: present but over-broad (F3) and false on REPEATING (F2)
- D2 consumer safety: PASS (sole consumer NM)
- `:roc` behaviour: PASS
- Tests RED on develop: PARTIAL (F5)

## Must-fix before build
F1, F2 (choose a or b and record it), F3, F5. F4 → card. F6/F7 → plan edits (cheap).
