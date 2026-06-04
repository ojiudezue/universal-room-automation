# DECISION: house_state restart-persistence — REJECTED / DROPPED

**Date:** 2026-06-03
**Status:** CLOSED — will NOT build. Risk/reward not there (operator call, 2026-06-03).
**Context:** v4.7.18.1 follow-up (SLEEP→WAKING deadlock hotfix).

---

## Verdict

`HouseStateMachine._state` will continue to default to `AWAY` and re-derive from
live signals on every boot. We are **not** adding restart-persistence. This matches
what every prior version of URA has shipped.

## Why dropped

The only material upside was being able to *validate v4.7.18.1 via a night restart* —
which is not worth the cost. Persisting state is not free of risk: a naive restore of
a stale `SLEEP` row at boot re-creates a smaller version of the very deadlock
v4.7.18.1 just fixed (SLEEP hysteresis re-arms on load, blocking `SLEEP→WAKING` for up
to the 10-min dwell — `house_state.py:93`). Doing it safely needs a freshness/age
guard (~30 LoC + an additive DAO). That's real surface area and boot-path complexity
to buy a validation convenience and a rare-case resilience win. v4.7.18.1's
raw-signal wake timer + daytime backstop already neutralize the live deadlock; the
fix being "inert at boot" is harmless because boot defaults to AWAY, not SLEEP.

**Net:** the in-memory default is good enough. v4.7.18.1 validates organically at the
next morning wake, not via restart.

## Preserved for the record (NOT being acted on)

- If this is ever reopened, the safe mechanism was: re-derive last state from the
  existing `house_state_log` table (`database.py:830-842`) with a 15-min freshness
  guard that discards stale SLEEP/WAKING. Re-derive beats Store/RestoreEntity (no new
  schema; single source of truth). See git history of this file for the full analysis.
- The `Restorability Gap` bug-class candidate from v4.7.18.1 reviewer notes is a
  SEPARATE question — it can still be considered for `docs/QUALITY_CONTEXT.md`
  independently of this decision.
