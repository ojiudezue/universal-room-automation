# URA v4.7.29 — Day-Boundary-Blind TOU Decision Fix (summer mid_peak hold)

**Release date:** 2026-06-08
**Tier:** Tier 2-DB — **operator-elevated** (regression-prone: battery-strategy decision with
battery↔grid↔cost ripple + touches a shared primitive, the TOU engine). 3 framing-disjoint
reviews + live validation. Per standing policy (CLAUDE.md, 2026-06-08).

**Files:** `domain_coordinators/energy_tou.py` (new `peak_ahead_before_offpeak`; `get_next_transition`
season-wrap hardening), `domain_coordinators/energy_battery.py` (summer mid_peak gate),
`quality/tests/test_day_boundary_tou.py` (NEW, 17 tests), `docs/QUALITY_CONTEXT.md` (Bug Class #51),
planning + review docs.

---

## Trigger

Operator observed URA forcing grid import during the summer **post-peak** mid_peak window
(8–9pm CDT) while the battery sat idle at 68% SOC. The summer mid_peak "hold-for-peak" branch
(`energy_battery.py`, v3.10.5) held the battery for **both** the pre-peak (14–16) and post-peak
(20–21) mid_peak windows, never reconciled with the v4.5.0 arbitrage redesign. Post-peak, holding
pins the battery and imports grid for an hour with off_peak ($0.043) imminent and tomorrow's solar
pending. Bug class: **Day-Boundary-Blind TOU Decision** (#51).

## Headline changes

- **`peak_ahead_before_offpeak(now)`** — new TOU primitive: real-time, season/midnight-safe forward
  walk answering "is a real peak still ahead before the next off_peak" from inside a mid_peak tick.
- **Summer mid_peak hold gated on it** — hold only when a peak genuinely precedes the next off_peak
  (pre-peak); otherwise discharge (post-peak). Pre-peak behavior byte-unchanged.
- **`get_next_transition` season-wrap hardened** — next-day transition uses tomorrow's season table
  (season-boundary correctness; intra-day unchanged) — de-risks the HVAC `max_runtime` consumer.

## Review

3 parallel framing-disjoint reviews → **0 CRITICAL, 0 HIGH, 3 MED (test coverage), several LOW** —
all MED + actionable LOW fixed in-cycle. Review B confirmed the fix **removes two reserve-write
storms** (20:00 + 21:00 boundaries) — no oscillation. Pre-existing MED (`_apply_evse_battery_hold`
could re-hold the battery if an EVSE charges during post-peak) deferred + flagged below. Detail:
`docs/reviews/code-review/day_boundary_tou_tier2db.md`. Gate: 17 cycle tests, full-suite zero new
failures, py_compile clean.

---

## Live Validation — prospective (Review D, time-windowed)

The fix's signal is confined to the **summer post-peak mid_peak window, 20:00–21:00 CDT**:
- **Live:** during 20:00–21:00 CDT, `sensor.envoy_482543015950_current_battery_discharge` > 0
  (battery discharges) and grid net import drops toward 0; `sensor.ura_energy_coordinator_battery_strategy`
  `reason` contains "post-peak … discharging".
- **Live (regression guard):** during 14:00–16:00 CDT (pre-peak), the battery still holds
  (reason "holding charge for … peak", reserve_level ≈ SOC).
- **Live:** no URA ERROR attributable to the new helper within an hour of restart.
- **Watch (deferred MED):** if an EVSE is charging during 20:00–21:00, confirm
  `_apply_evse_battery_hold` does not silently re-pin the battery (reason↔action divergence).

## Acceptance

```yaml
version: v4.7.29
hypotheses:
  - id: H1
    name: battery_discharges_not_pinned
    description: |
      After the fix, the battery is used (discharged) over a normal day rather than
      pinned by the summer mid_peak hold. NOTE: the fix-specific signal is the 20:00–21:00
      CDT post-peak window, which shipwatch's deploy-relative window cannot isolate; this
      hypothesis is a best-effort proxy (battery discharges meaningfully at some point over
      the window). The precise post-peak confirmation is the time-windowed Review D above.
    query:
      kind: ha_history_max
      entity: sensor.envoy_482543015950_current_battery_discharge
      hours_back: 24
    expected:
      condition: ">"
      value: 1.0
    window:
      first_check_after: 24h
      confirm_after: 48h
      alert_if_violated_after: 120h
  - id: H2
    name: peak_ahead_helper_never_raised
    description: |
      The new peak_ahead_before_offpeak helper must never throw — a traceback naming it
      would appear in the error log. Fix-specific correctness guard.
    query:
      kind: ha_log_count
      source: error_log
      search: "peak_ahead_before_offpeak"
      hours_back: 24
    expected:
      condition: "<="
      value: 0
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h
```
