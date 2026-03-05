# v3.6.34 — Census Face Recognition Case-Sensitivity Fix

## Summary

Fixed a bug where Frigate's `sensor.*_last_recognized_face` value of `"Unknown"`
(capital U) passed the exclusion filter and was treated as an identified person,
inflating the house census by 1.

## Problem

`persons_in_house` was stuck at 5 when only 4 known persons (BLE-tracked) were home.
The census never decayed because the face recognition filter used exact string matching
against `"unknown"` (lowercase), while Frigate reports `"Unknown"` (capital U).

This phantom 5th person was `"Unknown"` being added to `face_ids`, merged with the 4
BLE persons via set union, producing `identified_count = 5`.

## Fix

Changed the filter in `_get_face_recognized_persons()` to use case-insensitive
comparison (`state.strip().lower() not in (...)`). Also added `"no_match"` to the
exclusion list for completeness.

## Files Changed

| File | Change |
|------|--------|
| `camera_census.py` | Case-insensitive filter for face recognition sensor values |
| `const.py` | VERSION → 3.6.34 |
