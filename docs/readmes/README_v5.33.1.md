# URA v5.33.1 — AC-ramp kWh-avoided de-optimism (mean, not min)

Tier-1 hotfix. The v5.33.0 AC-ramp `kwh_avoided` estimate was wildly optimistic:
per-event `delta = kwh_rate_before − post_min`, and `post_min` reads ~0 because the
compressor **naturally cycles off** within the 30-min post-window — so each nudge was
credited as if it eliminated the *entire* AC load for 30 min (~1.6 kWh/nudge; 176 kWh/cycle,
≈ what the AC actually consumes). Diagnosed from the live `ac_ramp_events` table
(post_min = 0.00–0.01 on essentially every effective row).

## Fix (magnitude-only)
- `delta = kwh_rate_before − post_mean` (arithmetic mean of the post-window samples)
  instead of the minimum → credits the **average** reduction, not the peak dip.
- `_compute_post_restore_min_kw` now returns `(min, mean, count)`; `post_mean` added to
  the event `notes` for auditability.
- **Classification / escalation is byte-identical** — the `effective`/`ineffective`/
  `escalate` decision still keys exclusively on `post_min` and `AC_NUDGE_EVAL_MIN_DROP_FRAC`.
  Only the displayed kWh/$ magnitude changed. No decision behavior shifts.
- **Forward-only:** existing rows keep their recorded value; new nudges use the mean. The
  number re-baselines over the next day (today) / billing cycle (cycle); lifetime carries
  some legacy inflation until old rows age out (30-day retention on today/cycle).
- The 30-min projection cap is unchanged (operator-kept; separate lever).

Still explicitly **rough / not billing-grade** — this makes it *less wrong*, not exact.

## Review
Tier 1: build + orchestrator independent verification (grep-confirmed classification path
byte-identical, `delta` uses `post_mean`, no parallel post_mean classifier; 55 targeted
tests pass, full suite = known ordering-pollution baseline, zero new failures). Mutation-
anchored tests: `test_kwh_avoided_delta_uses_mean_not_min`, `test_classification_still_uses_min`,
`test_post_mean_in_notes`.

## Live Validation
- **H1 — Clean boot / no errors.**
- **H2 — Magnitude drops going forward.** New `nudge_evaluated` rows carry `post_mean` in
  notes and a smaller `kwh_avoided` than the pre-fix min-based value for a comparable nudge;
  `ac_kwh_avoided_today` grows more slowly than the pre-fix rate. Window: next effective nudges.
- **H3 — Classification unchanged.** Effective/ineffective mix and escalation frequency
  unchanged vs pre-fix (decision path byte-identical). Window: 24 h.
</content>
