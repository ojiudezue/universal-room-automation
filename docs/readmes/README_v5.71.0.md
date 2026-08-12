# URA v5.71.0 — Security images arrive, immediately (NM-IMAGE-1) + honest DP sensors (DP-OBSERVABILITY-1)

Two Tier-2 cycles, one deploy. Both ran the full quality-up-front pipeline: adversarial plan
review (NM plan went to rev-2 on a genuine global-DND leg the review caught), two
framing-disjoint code reviews each, fix-up rounds, orchestrator re-drills.

## NM-IMAGE-1 — the founding complaint: perimeter alert photos never arrived

Diagnosis (live-tested): capture worked, WhatsApp worked (a hand-sent `media_path` delivered),
but the operator's digest delivery preference routed security alerts through a digest pipeline
that is image-blind — and hours late.

**What ships:**
- **Security-class alerts with a captured image force-immediate delivery** — a single
  predicate (`hazard ∈ NM_SECURITY_HAZARDS` + truthy snapshot) consulted at BOTH suppression
  sites (the global quiet-hours early-return AND the per-person preference override) plus the
  channel-gate mirror. Exterior-person/vehicle photos now land in WhatsApp within the same
  event-loop turn as detection.
- **`[audit]` sentinel leak fixed reader-side**: digest SELECT + formatter filter (the writer
  is working-as-designed); dashboard readers (`notifications_today`, `last_notification`)
  also filter — no more "[audit]" as your last notification.
- Named route reasons for the new branches; `NM_SECURITY_HAZARDS` is rung-1 (empty set = kill).
- Deliberate trades, per plan: force-immediate rows do NOT re-appear in the morning digest
  (immediate delivery is authoritative); the predicate does NOT bypass silence, dedup,
  boot-settle, or per-recipient DND-bypass rules.

**Known interactions (Review B):** a channel whose global severity floor excludes MEDIUM will
still gate a MEDIUM security image (intersection semantics preserved); the token bucket applies
to forced-immediate sends exactly as it does to CRITICAL alerts — sustained MEDIUM/LOW noise
can starve a security image. Both by design; revisit only on live evidence.

**Out of scope:** iMessage attachments (BlueBubbles integration structurally drops them —
tracked); CONSOL-1 universal-llmvision rides on this cycle next.

## DP-OBSERVABILITY-1 — the sensor that misled two diagnoses in one day

`ev_charging_plan` presented a 4-day-old eval snapshot as current and its resting state read
as "blocked" — it cost both the orchestrator and the operator a misdiagnosis during the
Garage-A investigation. Decisions are byte-identical (guarded by dedicated tests); only
presentation changed:
- `eval_age_min` (int minutes, restart-honest), `state_meaning` per state ("hold_only =
  resting — no drain-pause active"), `eval_gate` labels distinguishing "eval not running"
  (dp_disabled / not_off_peak / force_charge_active) from "eval ran, nothing to arm"
  (`no_evse_charging_no_arm`), expired `must_start_by` never rendered as current.
- **Anti-churn contract** (Review B HIGH): `reasons_last_changed_at` is event-anchored (stamps
  only when the pause set actually changes) and attributes are byte-identical across quiescent
  polls — anchored by its own test. No recorder-row flood.

## Acceptance criteria

- **Live:** loads, zero URA errors; DP plan sensor shows `state_meaning` + `eval_age_min` +
  `eval_gate`; ev_charging_status carries `reasons_last_changed_at` that does NOT advance
  per-poll while quiescent.
- **Live (founding case, organic):** next exterior person detection delivers to WhatsApp
  WITH the image, immediately (not at digest time); ledger row carries
  `force_immediate_security_image`.
- **Live:** `last_notification` sensor never shows "[audit]".

## Live Validation

### Validated 2026-08-11 (v5.71.0 boot, evening)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Loads, zero URA errors | **PASS** | `system_log` ERROR search for `universal_room` empty post-restart |
| L2 | DP honesty attrs live | **PASS** | `ev_charging_plan`: `state_meaning` "resting — no drain-pause active…", `eval_gate: not_off_peak` (correct — evening mid-peak), `eval_age_min: null` (honest fresh-boot), `must_start_by_expired: false` |
| L3 | Reason stamp event-anchored, no churn | **PASS (falsification attempted)** | Three reads across 4 min: stamp advanced ONLY alongside real reason-content changes (idle/all-off → garage_a TOU-paused during boot settling). No stamp movement without content movement observed; quiescent byte-identity pinned in-suite by the anti-churn anchor |
| L4 | `last_notification` sentinel-free | **PASS** | `sensor.ura_notification_manager_last_notification` = real severity row, no "[audit]" |
| L5 | Founding case — security image immediate | **ORGANIC (open)** | Next exterior-person detection must land in WhatsApp WITH image at detection time, ledger row `force_immediate_security_image`. Two-site predicate + gate mirror mutation-anchored in-suite (8 drills, site-isolating) |

PR #500: +2974/−104 (non-empty verified). Suite at merge: 23 failed / 8708 passed — 21 pre-existing
+ 2 disclosed order-dependent `energy_restart_resilience` flakes (pass 64/64 in targeted runs;
pre-existing isolation-pollution class).
