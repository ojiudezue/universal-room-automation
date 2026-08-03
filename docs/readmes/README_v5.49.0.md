# v5.49.0 — Notification Hygiene (repeat decay, suppression age gate, ack authority)

From the 2026-08-03 repeat-storm + 6-day silent-suppression incidents.

## Ships
- **Suppression age gate**: a messaging-suppression restored at boot that
  is >24h old (NM_SUPPRESSION_RESTORE_MAX_AGE_S, 0=legacy) comes up
  UNSUPPRESSED with a HIGH one-shot notice. Origin timestamp persisted on
  the switch itself (restore-ordering independent). Operator toggles
  always supersede pending restores.
- **CRITICAL repeat decay ladder**: 5-min cadence for the first hour →
  30-min until 24h → daily thereafter; age survives restarts (DB
  timestamp); life-safety hazards keep their 30s cadence on all paths
  (mutation-anchored). Kill: NM_REPEAT_PHASE1_WINDOW_S=0 → legacy flat.
  Diagnostics: unacked_critical_age_s, repeat_phase.
- **Write-verify severity split**: retry attempts are HIGH (no repeat
  engine); only the final attempt + STAND-DOWN are CRITICAL.
- **Ack audit**: who acked what, via which channel, with what authority
  and safe-word source, into the notification audit trail.
- **Per-person safe words + ack authority**: optional per-person words
  (global fallback retained); security-family alerts (intruder,
  security_state_change, exterior_person, envoy_write_verification)
  ackable only by nm_security_ack_persons; unauthorized acks get a
  polite refusal and repeats continue. Companion-app acks are
  operator-grade (authenticated session). Unresolvable inbound senders
  stay denied for security classes.

## Review
3 framing-disjoint reviews (record: docs/reviews/code-review/
notification_hygiene_v5490.md): A 2 HIGH (toggle-vs-restore race;
security-ack default resolves to persons[0] = NOT the operator in this
household) + B SHIP (safety contract verified; "20th failure" was
builder miscount — sets identical) + C 2 HIGH (authority + safe-word
predicates had ZERO behavioral coverage — both neutered guards left
23/23 green; now exec-driven behavioral tests, orchestrator re-drilled
red). +32 tests, 19-failure baseline, zero drift.

## Live Validation — prospective
- **Live (MANDATORY config step):** set nm_security_ack_persons =
  [person.oji_udezue] via CM options; verify the NM init WARNING about
  fallback no longer appears on next reload.
- **Live (age-gate proof):** simulate a >24h-old suppression
  (set switch ON, backdate suppressed_since in persistence), restart:
  WARNING logged + HIGH one-shot lands + switch comes up OFF.
- **Live:** the 7/26 reserve_soc alert (if still unacked/recovered):
  daily cadence, not 5-min.
- **Live:** safe-word ack from operator thread acks; wife's thread on a
  security-family alert gets the polite refusal (test with
  test_safety_hazard hazard_type=intruder... use care: intruder is
  life-safety cadence — prefer a test_notification-based check).

### Validated 2026-08-03 (~13:20 CDT, first post-deploy boot)
| Criterion | Result | Evidence |
|---|---|---|
| Clean boot | **PASS** | Zero URA ERRORs; NM loaded; CM reloaded post-options. |
| nm_security_ack_persons configured | **PASS** | Set to ['person.oji_udezue'] via options flow driven end-to-end with exact current values — person credentials, cooldowns, global safe word all verified intact post-save. NOTE: the persons[0] fallback would ALSO have resolved correctly here (nm_persons contains only the operator; review A's concern keyed off tracked_persons order — real risk in multi-recipient households, moot in this one). |
| Fallback WARNING absent | **PASS** | Not present post-config in the boot window. |
| Age-gate live proof | **pending-next-restart** | Procedure: turn suppression ON, backdate suppressed_since (switch attr), restart → expect WARNING + HIGH one-shot + switch OFF. Deliberately NOT burning a family-daytime restart for it; behavioral tests + switch-attr persistence cover the mechanics; rides the next natural deploy restart. |
| Repeat decay on old alerts | **PASS-structural** | The 7/26 reserve_soc alert was acked earlier today (repeat chain ended); next unacked CRITICAL exercises the ladder organically. |
