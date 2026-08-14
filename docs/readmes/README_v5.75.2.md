# URA v5.75.2 — NM hardening pair: recovery age-bound + the "duke Nh" safe-word window

Two NM cycles, one deploy, both born from today's [audit]-resurrection incident and the operator's
window proposal.

## NM-RECOVERY-AGEBOUND-1 (Tier 1)
Boot recovery no longer resurrects unacked CRITICALs of arbitrary age — the months of twin-eaten
acks left 326 unacked historical rows that each restart would have walked backward through.
Caller-side bound (`NM_RECOVERY_MAX_AGE_H = 24.0`, rung-1, 0 = unbounded) at the recovery site only
(the two ack-path callers legitimately need unbounded reads — enumeration-adjudicated); tz-tolerant
age math failing open to recover; zombie-REPEATING restore guard for the one-time transition.
Historical rows stay for analytics, now permanently inert.

## SAFEWORD-WINDOW-1 (Tier 2-DB: plan review + 3 framing-disjoint reviews)
**"duke 2h"** — one safe-word reply now acks the current alert AND opens a perimeter-only silence
window (h/m units, hard cap 3h with reject-with-reply, minimum bound):
- **Scope is the whole design:** only `exterior_person`/`exterior_vehicle` first-fires are windowed.
  Life-safety (incl. operator-promoted hazards via the union helper) always bypasses. In-flight
  re-page loops are structurally untouched (window applies to NEW alerts; ack kills the current
  loop the normal way).
- **Authorization:** opening a window carries the same authority as an ack (Review A found any
  known person could otherwise silence the perimeter; gated + drill-anchored). Companion channel
  auto-authorized per existing convention.
- **Tuning signal preserved (the operator's stated goal):** every suppressed alert lands in a
  bounded ring (`perimeter_silence_recent_suppressions`, last 10, on diagnostics) + counter + INFO
  log — you can see exactly what a window caught.
- RAM-only (restart clears — resend to restore); window state + expiry surfaced as attrs; NM notes
  on open/expiry (DND-suppressed at night by design; the SMS reply is the guaranteed feedback);
  kill switch `NM_SAFEWORD_WINDOW_ENABLED`.
- Review chain: A DO-NOT-SHIP (auth gap) / B SHIP / C DO-NOT-SHIP (the suppression action itself
  had no behavioral anchor — drill 1 stayed green with the `return` removed; fixed with a real
  downstream spy). 6 drills all discriminating post-fix-up; orchestrator re-drilled the auth gate
  (1 named red, restored 25/25). Also fixed in-cycle: the latent `auth_reason` UnboundLocalError
  booby-trap in the safeword arm (pre-existing).

## Acceptance criteria
- **Test:** test_safeword_window.py (25) + test_nm_recovery_agebound.py (5), invariants I1-I5
  mutation-anchored.
- **Live:** loads, zero URA errors; no resurrection of any historical alert at boot (age-bound);
  NM status attrs show window fields (null when closed).
- **Live (organic):** first real "duke Nh" — reply confirms, window opens, suppressed events appear
  in the ring, resumed note at expiry; an unauthorized household member's "duke 2h" is politely
  refused.

## Live Validation

(prospective — replaced with Validated table post-restart)
