# v4.7.21 — Cold-boot away-actuation storm mitigation (two settle gates)

**Feature cycle (operator-elevated Tier 2, two framing-disjoint reviews +
fix-up + live validation).** Holds presence dispatch and HVAC's first decision
cycle on a COLD BOOT until boot data settles, so URA stops flooding slow cloud
devices with `away`-actuation `turn_off` calls before census/zone state is real.
Reviews: A = correctness + reachability + edge cases, B = async / lifecycle /
race / restart resilience. 0 CRITICAL; all 3 HIGH fixed. Review docs:
`docs/reviews/code-review/boot_storm_review_{A_correctness,B_lifecycle}.md`;
plan: `docs/planning/PLANNING_cold_boot_away_actuation_storm_mitigation.md`.

## The problem — cold boot derives `away` before data exists

`HouseStateMachine` does NOT persist across restart. At cold boot URA derives
house_state = `away` before census/zone trackers have populated, runs
away-actuation, and fans out `light`/`switch`/`homeassistant.turn_off` calls to
slow cloud devices (meross_lan / tplink / smartthings / dreo / sonoff / mqtt)
that don't ACK promptly. The event loop saturates → `Setup timed out for stage
2` and the house-state aggregate sensor freezes ~15 min before recovering.
Observed recurring on the v4.7.19 and v4.7.20.1 boots (see
`project_v4_7_19_live` "boot storm" note). Per-room sensors update fine; it is
the aggregate + downstream actuation that stalls.

## The fix — two cold-boot-only settle gates

Both gates are **truth-preserving**: they only SUPPRESS dispatch/actuation
during the settle window, never fabricate state. Both are **cold-boot-only** —
if `hass.is_running` is True at `async_setup` (an options-flow reload), the gate
is born already-released with reason `not_cold_boot`, so reloads are unaffected.

### Gate 1 — Presence dispatch (D1)
In `_run_inference`, the `SIGNAL_HOUSE_STATE_CHANGED` dispatch is held until the
gate releases. Held away-transitions are suppressed (counter + log), so no
downstream coordinator receives an `away` signal to act on during the storm
window.

### Gate 2 — HVAC first decision cycle (D1b)
Scenario γ: even if presence holds its signal, HVAC's periodic-timer initial
tick + the explicit `async_setup` kickoff can independently fan `turn_off` /
preset re-apply. So HVAC's first `_async_decision_cycle` is held under the same
gate. On release, if any cycle was suppressed, HVAC re-runs ONE decision cycle
immediately (deferred via `async_call_later`, unsub tracked in
`_unsub_listeners`) so it catches up to settled presence without a 0-5 min lag.

### Release predicates
- **Predicate A (presence only) — DATA-DRIVEN:** `_census_count >=
  BOOT_SETTLE_MIN_INPUTS` OR any zone tracker already OCCUPIED. The inference
  *trigger label* is deliberately NOT consulted (Reviewer A HIGH-A1) — boot
  triggers like `camera_detection` / `occupancy_change` / `census_update` arrive
  before census settles and must not release the gate early.
- **Predicate B path 1:** `EVENT_HOMEASSISTANT_STARTED` (`async_listen_once`).
- **Predicate B path 2 (failsafe):** `async_call_later(BOOT_SETTLE_TIMEOUT_
  SECONDS = 60)`. Guaranteed-release backstop on EVERY lifecycle path, even if
  HA never reaches RUNNING.

## New surfaces

| Surface | What |
|---|---|
| `const.BOOT_SETTLE_TIMEOUT_SECONDS = 60` | Failsafe release timeout. Module constant, not a config knob (ship constant first, configurability later if live data warrants). |
| `const.BOOT_SETTLE_MIN_INPUTS = 1` | Min census count for Predicate A. |
| `sensor.ura_presence_coordinator_presence_house_state` attrs | `boot_settle_done`, `boot_settle_release_reason`, `boot_settle_presence_suppressed`, `boot_settle_hvac_suppressed`. |

**No new CONF fields, Number entities, switches, or DB tables.** Instrumentation
reuses the existing house-state sensor's `extra_state_attributes`.

## Fix-up (post-review)

| ID | Sev | Resolution |
|---|---|---|
| A1 | HIGH | Predicate A made data-driven only; dropped the trigger-label clause that would release Gate 1 on the storm tick. |
| A2 / B1 | HIGH | HVAC re-kicks one decision cycle on release (closes 0-5min lag), deferred via `async_call_later` with unsub in `_unsub_listeners` so a parent-reload teardown cancels it in the same envelope (no use-after-teardown). |
| A3 | MED | Defensive `(self._zone_trackers or {})` in Predicate A. |
| A4 | MED | `observation_mode` surfaced in the Gate 1 suppression log. |
| B2 | MED | `base._cancel_listeners` isolates each unsub in try/except — one stale handle can't leak the rest (all coordinators benefit). |
| B4 | MED | DEBUG log on the HVAC re-entrancy skip. |
| A5 | — | Investigated → FALSE ALARM; all 44 v472 tests pass. |

MED-A6, MED-B3, and 7 LOWs deferred (operability nits / unverified premise; see
plan §4 + review docs).

## Files changed

| File | What |
|---|---|
| `domain_coordinators/presence.py` | Gate 1: boot-settle state + `_release_boot_settle` + Predicate A in `_run_inference` + dispatch suppression + cold-boot/reload scoping in `async_setup`. |
| `domain_coordinators/hvac.py` | Gate 2: boot-settle state + release helpers + suppression in `_async_decision_cycle` + post-release re-kick + re-entrancy skip log. |
| `domain_coordinators/base.py` | `_cancel_listeners` per-unsub isolation. |
| `sensor.py` | 4 `boot_settle_*` instrumentation attrs on the house-state sensor. |
| `const.py` | `BOOT_SETTLE_TIMEOUT_SECONDS`, `BOOT_SETTLE_MIN_INPUTS`. |
| `quality/tests/test_boot_settle_gate.py` | 27 tests (gate wiring, release predicates, cold-boot vs reload, HVAC re-kick path). |

## Migration

Two module constants + sensor attrs only. **No DB migration. No CONF changes.**

## Live validation (post-restart)

1. **Gate engaged on cold boot:** `sensor...presence_house_state` shows
   `boot_settle_release_reason` ∈ {`real_input`, `ha_started`, `timeout`} (NOT
   `not_cold_boot` on a true restart), and `boot_settle_presence_suppressed` ≥ 0.
2. **No storm:** zero `Setup timed out for stage 2`; the house-state aggregate
   sensor does NOT freeze (updates within seconds of boot, not ~15 min).
3. **HVAC catches up:** if `boot_settle_hvac_suppressed` > 0, an HVAC decision
   cycle runs within ~1s of release (not 5 min later).
4. **Clean release:** the failsafe fires by +60s at worst; `boot_settle_done`
   becomes True. MCP HA API responsive within <3 min of boot.
5. **Clean logs:** zero ERROR matching `boot_settle`.

## Acceptance

```yaml
version: v4.7.21
hypotheses:
  - id: H1
    name: no_setup_timeout_storm
    description: |
      The cold-boot away-actuation storm no longer saturates the event loop.
      No "Setup timed out for stage 2" appears in the boot window. This is the
      headline pathology the gates exist to kill.
    query:
      kind: ha_log_count
      source: system_service
      search: "Setup timed out for stage 2"
      hours_back: 1
    expected:
      condition: "<="
      value: 0
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h
  - id: H2
    name: no_boot_settle_errors
    description: |
      Neither gate raises ERROR-level logs across the release predicates,
      suppression branches, or the HVAC re-kick path.
    query:
      kind: ha_log_count
      source: error_log
      search: "boot_settle"
      hours_back: 1
    expected:
      condition: "<="
      value: 0
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h
```

## Rollback

HACS install v4.7.20.1 — removes both gates. All gate state is in-memory and the
two new constants + sensor attrs are additive, so rollback is clean either
direction. Without the gates the cold-boot storm returns but causes no
persistent corruption (it self-recovers on a cleaner boot, as it did pre-fix).
