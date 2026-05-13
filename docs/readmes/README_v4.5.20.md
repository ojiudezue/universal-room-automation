# v4.5.20 — Anomaly Refresh Signals (Presence + MF) + DOMAIN NameError Fix

**Date:** 2026-05-12 CDT
**Type:** Tier 1 bundle — two unrelated fixes
**Predecessor:** v4.5.19 (listener leak fix + swallow escalations, deployed earlier this evening)

## Summary

Two fixes shipping together because they were both discovered/built in the same window:

1. **Anomaly refresh signals (Presence + MF)** — completes the v4.5.14 visibility cycle. Two anomaly sensors that had `extra_state_attributes` since v4.5.14 but no per-cycle refresh signal now subscribe to new SIGNAL_PRESENCE_/_MUSIC_FOLLOWING_ENTITIES_UPDATE constants. Mirrors the HVAC/Safety/Security pattern.

2. **DOMAIN NameError fix in arbitrage code** — surfaced by v4.5.19's swallow escalations on the very first cycle after deploy. `energy.py` imports `DOMAIN as _DOMAIN` at module scope (for lambda closures), but two arbitrage functions used bare `DOMAIN`. NameError silently swallowed at debug level for who-knows-how-long. Every arbitrage decision cycle was throwing → arbitrage savings rows never landing in DB.

This is the **second long-latent NameError** caught by the v4.5.16/v4.5.20 swallow-escalation pattern this session (first was Bayesian eval `dt_util`). The audit + escalations are paying off.

## Part 1: Anomaly refresh signals

### Pattern audit

HVAC + Safety + Security all had `SIGNAL_*_ENTITIES_UPDATE` constants and per-cycle dispatches. Presence + MF were missing — their anomaly sensors had visible attrs (v4.5.14) but stale-until-HA-naturally-queries refresh behavior.

### Implementation

- `signals.py` — added `SIGNAL_PRESENCE_ENTITIES_UPDATE` and `SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE`
- `presence.py:_run_inference` — dispatches `SIGNAL_PRESENCE_ENTITIES_UPDATE` at end of cycle (after `_check_zone_anomalies`)
- `music_following.py:_on_transfer_outcome` — dispatches `SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE` after recording observations. MF is event-driven (no periodic tick) — fires only on actual transfers, which is the right cadence
- `sensor.py:PresenceAnomalySensor` + `MusicFollowingAnomalySensor` — subscribe via `async_added_to_hass` with `async_on_remove(async_dispatcher_connect(...))` (Bug Class #38 prevention pattern from v4.5.19)
- Stale comment removed from MF anomaly sensor noting "no signal exists" — signal exists now

### Why MF dispatch is in `_on_transfer_outcome` (not a timer)

MF is fundamentally event-driven. Its state changes only when a transfer happens. Adding a periodic tick would dispatch every N seconds even when nothing changed (wasted refreshes). Dispatching from `_on_transfer_outcome` fires at exactly the moments MF state can have shifted.

Trade-off: in long quiet periods between transfers, the MF anomaly sensor's attrs may be slightly stale. Acceptable — the underlying anomaly state can't have changed either.

## Part 2: DOMAIN NameError fix

### The bug

`energy.py:30` imports `DOMAIN as _DOMAIN` (the alias is for lambda closures at line 303). Two arbitrage code paths used bare `DOMAIN`:

- `_account_arbitrage_cycle` (line 1654)
- `_refresh_arbitrage_status_cache` (line 1694)

Both threw `NameError: name 'DOMAIN' is not defined` on every decision cycle. The pre-v4.5.19 outer try/except in `_async_decision_cycle` swallowed at debug level. v4.5.19 escalated that swallow to WARNING + `exc_info=True`, surfacing the NameError immediately.

### How long has this been broken?

Unknown without DB inspection. Arbitrage savings sensors have likely been reading stale-or-zero data the entire time. The arbitrage feature is the v4.5.0 "Battery Strategy Redesign" headline — possibly broken in production since that cycle shipped.

### The fix

Two-character change × 2 sites: `DOMAIN` → `_DOMAIN`. Matches the existing module-scope alias convention.

### Why this is good news despite being a real production bug

This is exactly what the v4.5.20 audit (run in v4.5.19) was designed to catch — a v4.5.17-shape NameError hidden by a debug-level swallow in a periodic closure. The pattern works:

- v4.5.16 Part B (Bayesian eval diagnostic) → caught the first NameError → v4.5.17 fix
- v4.5.20 swallow escalation (now in v4.5.19) → caught the second NameError → this fix

Pattern detection: when an integration relies on periodic background work, exception swallows must be at WARNING level minimum. URA now enforces this systematically.

## Tier 1 Review

Single staff-engineer review per CLAUDE.md (both fixes are minor; bundle is non-coupling because anomaly signals touch `signals.py`+`presence.py`+`music_following.py`+`sensor.py`, DOMAIN fix touches only `energy.py`).

Findings to be appended after review.

## Test count

- v4.5.19: 461 tests
- **v4.5.20: 476** (+15 across `test_v4520_anomaly_refresh_signals.py`)

Tests pin:
- Both new signal constants exist
- Presence coord dispatches at end of `_run_inference` (after `_check_zone_anomalies`)
- MF dispatches inside `_on_transfer_outcome`
- Both sensors subscribe via `async_added_to_hass` with `async_on_remove` wrapper
- Stale "no signal exists" comment removed
- Both DOMAIN fix sites use `_DOMAIN` (the existing module alias)
- Module-level `from ..const import DOMAIN as _DOMAIN` import preserved

## Live validation plan (post-restart)

### Anomaly refresh signals

1. **Trigger a Presence inference cycle** by movement in any tracked room. `sensor.ura_presence_coordinator_presence_anomaly` attrs should refresh.
2. **Trigger an MF transfer** (move from one room to another while music plays — if anyone is listening). `sensor.ura_music_following_coordinator_music_following_anomaly` attrs should refresh on the transfer.
3. Or just check periodically — even without manual triggers, normal household activity will drive both.

### DOMAIN fix

1. **First arbitrage decision cycle (every 5 min)** should NOT log the "Arbitrage cycle accounting skipped" warning anymore. Check `ha_get_logs source=system search="Arbitrage cycle"` ~10 min post-restart.
2. **`sensor.ura_energy_coordinator_arbitrage_savings_today` etc.** should start populating with non-zero values (assuming arbitrage actually fires this cycle — depends on battery SOC + TOU period).

### Carry-over

- v4.5.16 Part A failsafe still gated on motion freshness
- v4.5.17 Bayesian eval still writes prediction rows (next bin at 21:05 CDT)
- v4.5.19 listener leak still fixed — no NEW duplicate writes post-restart
- All v4.5.20 swallow escalations still active and ready to surface any new bugs

## Deploy notes

- 5 files touched (signals.py, presence.py, music_following.py, sensor.py, energy.py)
- HACS download required
- HA restart required
- No DB schema changes, no entity unique_ids changed, no config keys

## Documents

- BACKLOG entries closed: anomaly refresh signals (Presence + MF) — was filed since v4.5.14, now shipped
- DOMAIN NameError finding folded inline (no separate BACKLOG entry needed — discovered + fixed within hours)
- v4.5.x Phase-2 carry-overs entry remains for other items not yet shipped

## Next

- **B — Device-page ordering HC experiment** — being built in parallel via background agent right now. Ships next after this validates.
- v4.6.x — likely_next_room accuracy pipeline (the OTHER prediction-quality cycle)
- v4.6.0 — Routine Awareness Phase 1
