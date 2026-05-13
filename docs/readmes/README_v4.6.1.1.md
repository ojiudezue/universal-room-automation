# v4.6.1.1 — Hotfix: `anomaly_log` NOT NULL constraint

**Date:** 2026-05-13 CDT
**Type:** Tier 1 hotfix
**Predecessor:** v4.6.1 (anomaly reconciliation foundation, just deployed)
**Severity:** Production warning — both canaries failing + presence-coord legacy path failing

## Problem

v4.6.1's `save_anomaly_event()` DAO passed `None` for 5 `anomaly_log` columns the LEGACY schema declares as `NOT NULL`: `observed_value`, `expected_mean`, `expected_std`, `z_score`, `sample_size`. Result: every anomaly write — from both new canaries AND the legacy `store_anomaly` wrapper (which routes through the DAO since v4.6.1) — failed with:

```
sqlite3.IntegrityError: NOT NULL constraint failed: anomaly_log.observed_value
```

Production trace observed within 30 sec of v4.6.1 deploy:
```
Error saving AnomalyEvent (coordinator=energy type=energy.crosscheck_divergence ...)
Error saving AnomalyEvent (coordinator=presence type=presence.census_count ...)
```

**Why Tier 2 review missed this:** both reviewers read the diff, not the live schema at `database.py:666-691`. The diff showed ALTER TABLE ADD COLUMN for the 6 NEW columns but didn't surface the existing NOT NULL constraints on the legacy metric columns. A behavioral test against a real schema would have caught it; source-grep tests didn't.

## Fix

DAO extracts the metric fields from `event.payload` when callers pack them there (legacy `store_anomaly` wrapper already does), with 0.0/0 sentinel defaults for new AnomalyEvent-style emitters (canaries, future regime detector):

```python
payload_dict = event.payload if isinstance(event.payload, dict) else {}
observed_value = payload_dict.get("observed_value", 0.0)
expected_mean  = payload_dict.get("expected_mean", 0.0)
expected_std   = payload_dict.get("expected_std", 0.0)
z_score        = payload_dict.get("z_score", 0.0)
sample_size    = payload_dict.get("sample_size", 0)
house_state    = payload_dict.get("house_state")
```

INSERT VALUES tuple updated to pass these locals (was passing `None, None, None, None` for the four floats and `None, None` for sample_size + house_state).

**Result:**
- Legacy callers (presence, hvac, safety, security, energy via `store_anomaly`) retain their actual metric data — wrapper packs them into payload, DAO unpacks them back
- New AnomalyEvent emitters (canaries) write 0.0 sentinels in the obligatory columns; the actual data lives in `payload` JSON
- NOT NULL constraint satisfied
- No data loss for legacy path

## What's NOT done in this hotfix

**Schema modernization** — making `observed_value` and friends nullable via table-rebuild dance — is deferred to v4.6.2. The sentinel approach is pragmatic but lossy at scale for AnomalyEvent-style writes. v4.6.2's regime detector will benefit from a proper nullable column; today's 0.0 sentinel is fine for the 2 canaries that emit infrequently.

## Test

`test_save_anomaly_event_handles_legacy_not_null_columns` added to `test_v461_store_event_writer.py`:
- Pins `payload_dict.get("observed_value", ...)` etc. extraction pattern in DAO
- Pins INSERT VALUES tuple references the locals, not None
- Pin all 5 legacy NOT NULL fields

## Live validation plan

1. After restart, the `Error saving AnomalyEvent (...): NOT NULL constraint failed` warnings should stop
2. New `anomaly_log` rows from canaries should land:
   ```sql
   SELECT coordinator_id, type, observed_value, severity, event_class, timestamp
   FROM anomaly_log
   WHERE timestamp >= datetime('now', '-1 hour')
   ORDER BY timestamp DESC LIMIT 10;
   ```
   Expect rows for `energy.crosscheck_divergence` and `presence.census_count` (or whatever legacy + canary emitters fire next).

## Files changed

- `database.py:4195-4239` — DAO now extracts metric fields from payload with safe defaults

## Test count

- v4.6.1: 2774 passing
- **v4.6.1.1: 2775 passing** (+1 hotfix regression guard)
