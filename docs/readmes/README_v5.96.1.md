# v5.96.1 — Egress EXIT identity via backfill (conservative, exclusive attribution)

**Card:** EGRESS-EXIT-IDENTITY-BACKFILL-1. Completes the egress producer (v5.96.0 = entry). Under 6.0.0 IDENTITY-DRIVEN AUTONOMY.
**Tier:** 3 — prior-art-scanned plan + 1 plan-review (FIX-REQUIRED, fixed) + 3 framing-disjoint build reviews (all FIX-REQUIRED) + consolidated fix-up + adversarial re-review (found a residual) + targeted fix + orchestrator independent mutation-verify.

## Problem
Exit crossings were never named: the departer's BLE `not_home` edge lags the door crossing by ~369s (D0 median, p90 612s) — long past the +45s resolver read that writes the row. So every exit row stayed `person_id = NULL`.

## Solution — backfill, exclusive-attribution only
The exit crossing is written NULL immediately (unchanged); when a resident's `bluetooth_le` tracker fires a `home→away` edge, an async task backfills that crossing's `person_id` — but ONLY when attribution is unambiguous (operator: accuracy over coverage — "someone exited; that someone is 'person' after a few minutes is ok; leave null otherwise").
- **UTC-naive timestamp contract** — bounds match the INSERT's `datetime.utcnow().isoformat()` byte-for-byte (the silent-zero-match trap, designed against + tested).
- **Deferred window-close decision** — the attribution waits until the candidate row's full 600s window has elapsed, then counts DISTINCT departing residents in `[row_ts, row_ts+window]`; attributes only if exactly one. This makes competing-edge detection symmetric with the lookback, closing the co-departer swap even under >90s device skew / partial face-naming.
- **Flap guard** — re-reads the tracker live state at the decision point; a resident who flapped `home→not_home→home` (BLE noise) never names a guest's exit.
- **Per-slug cooldown** — a multi-tracker resident (phone+watch) can't double-consume two crossings.
- **Idempotent single-use** — `UPDATE … WHERE id=? AND person_id IS NULL` (person_id only; the direction-`confidence` column is NOT clobbered).
- **Task discipline** — the backfill tasks are tracked and cancelled on unload only (not on routine listener refresh).
- Observability: `_ble_exit_backfilled / _no_match / _ambiguity_abstain / _flap_aborted / _backfill_noop / _error` counters on the persons-in-house sensor.

## Reviews (each framing found what the others missed)
Plan-review caught 2 CRITs pre-build (DB access from a @callback sync context; the tz convention). Build A/B/D all FIX-REQUIRED — the "no exclusive attribution" family: co-departer swap, multi-tracker double-consume, flap-names-guest, teardown over-cancel, confidence clobber. Consolidated fix-up made attribution conservative; the adversarial re-pass then found the asymmetric-window residual (90s lookahead vs 600s lookback); the targeted fix deferred the decision to window-close. Orchestrator independently mutation-verified the tz bound, the IS-NULL guard, the multi-row abstain, the flap guard, and the distinct-departer scan (each RED-on-neuter). 13 exit tests + 33 fusion tests green; zero net-new suite regressions.

### Acceptance criteria
- **Verify:** a solo resident's `not_home` edge backfills their (only, in-window) exit crossing ~window-close later; two co-departers → BOTH stay null (no swap); a flap → no attribution; a multi-tracker resident → at most one backfill.
- **Test:** 13 exit anchors, each RED-on-neuter incl. the deferred late-competing-edge abstain.
- **Live:** next real solo departure → its exit row's `person_id` fills within ~10 min; `_ble_exit_backfilled_count` moves; co-departures show `_ble_exit_ambiguity_abstain_count` rising and stay null.

## Known scope (deliberate)
Co-departures (a couple leaving together) stay `null` by design (accuracy-first) — naming them needs edge↔crossing pairing, a carded future refinement. Pre-restart crossings whose edge fired during downtime are not backfilled (fail-safe null). Sensor-reader TZ over-count + exit-list display-not-re-read after backfill: pre-existing, carded separately.

## Live Validation — post-restart (to record as `Validated <date>`)
- A real solo departure fills its exit-row person_id within ~10 min; counters move.
- A flap / co-departure does NOT produce a wrong name.
