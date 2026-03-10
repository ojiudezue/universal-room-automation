# URA v3.9.13 — Energy Peak Import Persistence Review Fixes

## Overview
Code review fixes for v3.9.12's peak import history persistence. Removes dead code, fixes observation mode data loss gap, adds dirty flag to avoid unnecessary DB writes.

## Changes

### Review Fix 1: Remove `energy_learned_threshold` table (dead code)
- The learned threshold is always recomputed from `_peak_import_history` readings on every decision cycle via `_get_effective_shedding_threshold()`
- The restored threshold value was overwritten before any sensor poll could observe it
- Removed the single-row threshold table, simplified `save_peak_import_history()` and `get_peak_import_history()` signatures

### Review Fix 2: Move hourly save outside observation mode guard
- The hourly persistence save was inside `if not self._observation_mode:`, meaning an ungraceful restart during observation mode would lose up to 1 hour of peak data collected before observation was enabled
- Persistence is a data concern, not an action — moved outside the observation mode guard

### Review Fix 3: Add dirty flag to avoid unnecessary saves
- Previously, the hourly save fired even during off-peak when no new readings were added — DELETE+INSERT of 1500 rows with no changes
- Added `_peak_import_dirty` flag, set when `_peak_import_history.append()` runs, cleared after save

## Files Changed
- `database.py` — Removed `energy_learned_threshold` table creation, simplified save/get method signatures
- `domain_coordinators/energy.py` — Added `_peak_import_dirty` flag, moved save outside observation guard, simplified restore/save methods
