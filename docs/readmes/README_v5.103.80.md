# v5.103.80: four notification calls that never delivered now work

Card: NM-NOTIFY-SIGNATURE-MISMATCH-1. Tier 2, two reviews (A correctness + call-site re-enumeration: SHIP; B delivery consequences: SHIP). Deploy risk: LOW.

## Problem

Four `NotificationManager.async_notify` call sites passed arguments the method never accepted, so each raised `TypeError` inside the call and the alert was never sent:

- `presence.py` wake-backstop: no `coordinator_id`, string severity, unknown `source`.
- `binary_sensor.py` room occupancy-anomaly alert: same three problems.
- `perimeter_alert.py` enriched person/vehicle legs and the test-perimeter button: `route_reason` was not a parameter.
- `optimization.py` `_notify_if_severe`: unknown `event_class`/`dedup_key`; the first call always failed and a TypeError retry delivered.

## Fix

- Each site now binds to the real signature, with `Severity` enum values.
- `route_reason` is a new optional NM parameter; a caller-supplied value replaces the computed audit label on the delivered path (None = unchanged).
- The optimizer's dead kwargs and its TypeError retry are removed (the retry could also hide real TypeErrors).
- AST bind-check (review A): all 33 call sites bind.

## What you will newly receive (review B, on live config)

- Wake-backstop: at most once a day, in the digest (MEDIUM).
- Occupancy-anomaly: about zero; the sensor never evaluates (carded: BAYES-OCCUPANCY-ANOMALY-NEVER-EVALUATES-1).
- Enriched perimeter alerts: no change while enrichment is off (it is).
- Nothing new is spoken: TTS and alert lights are off in NM options.

## Tests

- `test_nm_notify_signature_sites.py`: per-site behavioural tests binding against `inspect.signature(NotificationManager.async_notify)`; every site mutation-drilled RED.
- Full-suite name-diff vs develop 42d143f60 with URA_SOURCE_MUTATION=1: CLEAN, 11 = 11, 0 new / 0 gone.

## Live validation (to fill after restart)

- No `NM notify failed` / TypeError lines from URA notify call sites in the core log.
- 50/50 URA entries loaded, 0 URA ERRORs.
