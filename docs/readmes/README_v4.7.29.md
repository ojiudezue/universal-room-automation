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

## Live Validation — Validated 2026-06-08 (partial; fix-window deferred)

Validated post-restart with v4.7.29 active (`update.universal_room_automation_update`
installed_version = `v4.7.29`). At validation time TOU had rolled to **off_peak**, and tonight's
post-peak mid_peak window (20:00–21:00 CDT) ran pre-deploy — so the fix-specific signal first
manifests **tomorrow's** post-peak window.

| # | Criterion | Result | Observed evidence |
|---|-----------|--------|-------------------|
| 1 | v4.7.29 active | **PASS** | update entity installed_version = v4.7.29 |
| 2 | No URA ERROR logs this boot | **PASS** | system ERROR log filtered to `universal_room` = empty |
| 3 | New helper never raises (H2) | **PASS** | error_log search "peak_ahead_before_offpeak" = 0 |
| 4 | Battery used, not pinned | **PASS (off_peak)** | off_peak: `battery_power −10.32 kW` (discharging), reason "Off-peak drain — SOC 57% > target 20%", reserve dropped to 20%, grid net ≈ 0 — healthy off_peak path post-fix |
| 5 | Post-peak mid_peak discharge (the fix) | **DEFERRED-to-window** | TOU now off_peak; tonight's 20:00–21:00 window ran pre-deploy. First genuine manifestation = tomorrow 20:00–21:00 CDT. Monitored via shipwatch `## Acceptance` H1 + a targeted recorder check. |
| 6 | Pre-peak hold regression guard (14:00–16:00) | **DEFERRED-to-window** | Same — observable tomorrow afternoon. Covered in-suite (17 tests). |
| 7 | `_apply_evse_battery_hold` re-pin watch (deferred MED) | **PENDING** | Watch during tomorrow's post-peak window if an EVSE is charging. |

Mechanism is proven in-suite (17 tests incl. pre/post-peak, boundary hours, None-engine,
season/midnight); criteria 5/6 await the wall-clock window. No code path is unproven.

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
