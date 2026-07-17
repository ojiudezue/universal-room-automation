# DRAFT — upstream issue for home-assistant/core (`enphase_envoy`)

> Status: DRAFT ONLY — do NOT post until the operator reviews. R4b of the
> LTS-repair chain (see `RUNBOOK_lts_repairs_r4.md`).
> Firmware version below is stated from local context (Envoy metered,
> firmware 8.3.x); CONFIRM the exact firmware string from the Envoy local UI
> or Enlighten before posting.

---

**Title:** `enphase_envoy`: transient uint32-max (2^32 Wh) consumption readings permanently corrupt long-term energy statistics — integration should reject physically-implausible deltas

## The problem

The Envoy consumption CT occasionally returns a transient garbage reading of
~`4294967296` Wh (exactly uint32 max) for daily consumption. The
`sensor.envoy_<serial>_energy_consumption_today` entity (kWh,
`total_increasing`) then reports a state of ~`4,294,629 kWh` for one update
cycle before returning to normal (~hundreds of kWh).

Because the statistic is `total_increasing`, the recorder treats the spike
as real consumption and bakes ~4.29 million kWh into the statistic's
cumulative `sum` **permanently**. When the counter drops back, HA treats it
as a normal counter reset, so the spike is never reversed. Each occurrence
adds another ~4.29e6 kWh step. The Energy dashboard and any consumer of the
consumption statistic are unusable afterwards without manual DB surgery.

## Evidence (from my recorder DB, HA 2026.7.2)

All spike deltas cluster at 2^32 Wh = 4,294,967.296 kWh (minus the real
consumption in the hour):

| Serial | spike events | example event (local time) | hourly `sum` delta (kWh) | baked-in error (kWh) |
|---|---|---|---|---|
| 202442014493 | 2 | 2025-05-05 08:00 | 4,294,684.702 | 8,576,091 |
| 202504003374 | 18 | 2025-08-19 21:00 | 4,294,963.763 | 77,304,135 |
| 202428004328 | 1 | 2025-12-16 10:00 | 4,294,356.343 | 4,294,356 |
| 482543015950 | 1 | 2026-05-31 00:00 | 4,294,629.126 | 4,294,629 |

Example raw statistics rows (serial 482543015950, metadata_id 5651):
state jumps `276 → 4,294,629.126 → ~277` in adjacent hours; `sum` steps up
by 4,294,629 and stays there for every subsequent row (897 rows and
counting).

Four different Envoy serials (hardware swaps) all exhibit it, across
firmware in the 8.3.x line — it is a device/firmware artifact, not a
one-off. Notably the **lifetime** (MWh-scaled) statistics from the same
device are clean; only the "today" Wh-scaled consumption endpoint produces
the uint32-max readings.

## Suggested guard

The integration (or pyenphase) should reject physically implausible values
before they reach the state machine, e.g.:

- Reject/skip an update where daily consumption ≥ 2^32 − ε Wh (a sentinel
  for a failed CT read), or
- Reject deltas that exceed a plausible bound (e.g. >1 MWh change in a
  single poll for a residential "today" counter), returning the previous
  value / marking unavailable for that cycle.

Precedent: other energy integrations clamp or drop known firmware sentinel
values rather than publishing them into `total_increasing` statistics,
because a single bad publish is unrecoverable without manual statistics
surgery.

## Environment

- Home Assistant Core 2026.7.2 (recorder on SQLite)
- Integration: `enphase_envoy` (core)
- Hardware: Envoy metered w/ consumption CTs + Enpower/IQ batteries;
  4 serials over the install's life (RMA swaps): 202442014493,
  202504003374, 202428004328, 482543015950 (current)
- Firmware: 8.3.x (exact string to confirm before posting)

## Diagnostics

Happy to attach integration diagnostics and the raw statistics rows for the
spike windows on request.
