# v3.13.0 — DB Infrastructure Repair

**Date**: 2026-03-12
**Scope**: Database resilience refactor, circuit state persistence, energy_history schema migration
**Tests**: 16 new (test_database_resilience.py), 933+ total passing

---

## Summary

Production database had B-tree corruption in `energy_snapshots` table. The single `try/except` wrapping all table creation in `database.py:initialize()` meant corruption at one table prevented ALL tables defined after it from being created — including `energy_daily`, `energy_peak_import`, and `evse_state`.

This release refactors `initialize()` to per-table isolation so that any single table failure does not block others.

## Changes

### 1. Per-Table Isolation (`_create_table_safe`)
- Each of 26 tables is now created in its own `try/except` with explicit rollback
- Failure in one table is logged but does not prevent subsequent tables
- On failure, the error is captured in `_last_table_error` for caller inspection
- Commits are per-table to ensure isolation

### 2. Corruption-Aware Auto-Repair (`_repair_corrupt_table`)
- `energy_snapshots` gets special handling: if creation fails with corruption/malformed error, the table is dropped and recreated
- Only tables in `_REPAIRABLE_TABLES` whitelist can be repaired (prevents accidental data loss on transient errors like SQLITE_BUSY)
- Error string is checked for "corrupt" or "malformed" keywords before triggering repair

### 3. Circuit State Persistence
- New `circuit_state` table: `(circuit_id PK, was_loaded, zero_since, alerted, updated_at)`
- `save_circuit_state()`: Persists SPAN circuit monitor state (was_loaded, zero_since as float, alerted)
- `restore_circuit_state()`: Restores state after restart, converts `zero_since` back to `float`
- Empty dict guard, rollback on failure, `dt_util.utcnow()` timestamps
- **Wiring to energy coordinator deferred to v3.13.1 (M2)**

### 4. Energy History Schema Migration
- Added `tou_period TEXT` column to `energy_history` via PRAGMA-based migration
- Column is created in M1 but **populated by `log_energy_history` in M2 (v3.13.1)**
- Idempotent: re-running initialize() with column already present is a no-op

## Review Findings Fixed

All CRITICAL and HIGH issues from 3-review protocol addressed:
- **SQL injection protection**: `_REPAIRABLE_TABLES` frozenset whitelist
- **Corruption-only repair**: Error message checked before drop+recreate
- **Transaction safety**: Rollback added to `save_circuit_state` error path
- **Type mismatch**: `zero_since` stored as str(float), restored as float
- **Timestamp consistency**: Uses `dt_util.utcnow()` not deprecated `datetime.utcnow()`
- **Empty state guard**: `save_circuit_state({})` returns immediately
- **False-positive test**: Isolation test rewritten to actually trigger table creation failure

## Files Modified

| File | Changes |
|------|---------|
| `database.py` | Refactored initialize(), added _create_table_safe, _repair_corrupt_table, circuit_state table, save/restore methods, tou_period migration |
| `quality/tests/test_database_resilience.py` | 16 tests: table creation, isolation, circuit CRUD, tou_period migration, edge cases |

## Deferred to M2 (v3.13.1)

- `log_energy_history()` does not yet populate `tou_period` column
- Circuit state save/restore not yet wired into energy coordinator shutdown/startup
- Energy history missing columns (house_avg_temp, etc.) — M2 scope
- D3-D7 wiring verification — M2 scope
