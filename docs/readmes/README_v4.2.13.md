# v4.2.13 — Startup Catch-Up Delay + Bayesian Init Hardening

**Date:** 2026-04-28

## Summary

Delays startup catch-up prune from 5 min to 30 min. Registers Bayesian predictor before DB load so button/sensors survive DB failures. Superseded by v4.2.14 which removes catch-up entirely (30 min delay still caused 15-20 min of write queue saturation).

## Changes
- Catch-up delay: 300s → 1800s (both paths) — superseded by v4.2.14
- Bayesian init: register before initialize, inner try/except — retained in v4.2.14

## Files Modified (1)
- `__init__.py`
