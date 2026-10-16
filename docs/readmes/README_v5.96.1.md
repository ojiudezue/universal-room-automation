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

## Live Validation — Validated 2026-10-16

Source: `docs/planning/AUDIT_exit_backfill_d0.md` (read-only D0, run 2026-10-16 ~00:20 CDT against the live URA DB and the HA recorder). The recorder only covers 2026-10-08 09:12 UTC onward (~7.5 days), so the counter rows are for that window. Counters reset on every restart (14 resets in the window) and increments between the last sample and a reset are lost, so every counter figure is a **lower bound**. journald was not reachable from the `ssh ha` shell, so the `exit-backfill: row_id=` INFO lines could not be read; the counters are the evidence used.

| Criterion | Result | Evidence |
|---|---|---|
| A real departure fills its exit row's `person_id` (~5-11 min later); counters move | **PASS** | `ble_exit_backfilled_count` attribute on `sensor.universal_room_automation_persons_in_house` (the census sensor; the plan's `sensor.ura_census_persons_in_house` name was wrong): **≥11 backfills** in 7.5 days, increments at 10-08 19:57, 10-09 12:33, 10-09 21:46, 10-11 14:42, 10-12 15:36 (x2), 10-13 00:33, 10-13 12:14, 10-14 10:21, 10-14 12:35, 10-15 12:37 UTC. In the window, 25 of 78 exit rows are named; ≥11 of those (44%) came from the backfill. |
| Backfill not regressed: edges land in the window | **PASS** | 65 home→not_home edges on 6 `bluetooth_le` trackers. Signed edge-minus-row lag: <0 s: 8, 0-600 s: 33, 600-900 s: 1, 900-1800 s: 3, no row within ±1800 s: 20. 73% of edges with a nearby row are in-window. |
| Exit attach rate at parity with entry (14 d, URA DB) | **as-expected** | entry 75/279 = 26.9%, exit 59/213 = 27.7%. |
| A flap does NOT produce a wrong name | **as-expected** | `ble_exit_flap_aborted_count` ≥15: the settle re-read is aborting flaps. `ble_exit_error_count` 0, `ble_exit_backfill_noop_count` 0. Departures to `unavailable`/`unknown` (miss C): 0 measured. |
| Multi-tracker resident → at most one backfill | **as-expected** | `ble_exit_per_slug_cooldown_skipped_count` ≥29. |
| No row-level wrong-WHO | **NOT RUN** | The 5-row spot check of backfilled rows against BLE history was not done in D0. The flap guard counter is the only evidence. Open item on the card. |

Not provable from the DB alone: which named exits came from face vs backfill before 10-08 (recorder gap). Of the 12 null exit rows in the window with an edge nearby, 7 sit at 600-1800 s (the R2 window-widening question; parked per D0).

**Follow-up shipped on branch `fix/exit-backfill-r1` (2026-10-16):** the backfill now honours `switch.ura_name_people_at_doors` (it did not before), and `sensor.universal_room_automation_last_person_exit` picks up the name when a backfill names the newest exit row.
