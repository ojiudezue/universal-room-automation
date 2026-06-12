# URA v5.3.5 — OC Button Availability Push (Tier 1 hotfix)

**Trigger:** Operator hands-on validation of v5.3.3/v5.3.4 — staged an escalation
and Confirm/Cancel stayed greyed out indefinitely.

**Root cause:** The OC admin buttons derive `available` from CM entry.options
(pending-escalation key, kill switch), but nothing ever pushed a state write
after options changed — ButtonEntity doesn't poll, and the refresh-slot
mechanism built for the autonomy select was never wired to the buttons.
Review A-L9 had graded this "≤30s poll lag"; reality was infinite staleness.

**Fix:** `_OptimizerCMButtonBase` subscribes each button to the CM entry's
update listener (auto-removed with the entity) and rewrites its own state on
ANY CM options change — stage / cancel / confirm / kill / form save all flip
availability instantly. ~20 LoC, commit fa20139.

Also rides along: v5.3.4 Review-D README write-back + VibeMemo entry 022.

## Live Validation (Review D) — Validated 2026-06-10 ~23:20 UTC

| Criterion | Result | Observed evidence |
|---|---|---|
| Clean restart | PASS | select restored `shadow`, optimizer reached **healthy** (first time — recalibrated vocab + findings cleared) |
| Pending survives restart | AS-EXPECTED N/A | operator had already cleared the staged escalation pre-restart via the kill-switch toggle (documented workaround) — `pending_level: null`, Confirm/Cancel correctly unavailable with nothing pending |
| **NEW live finding** | PATCHED (rides next deploy) | **Run Cycle Now stale-unavailable post-boot**: its availability depends on optimizer REGISTRATION (hass.data), not options — entry-listener never fires for that. Follow-up `1bc4f1b`: two bounded one-shot post-boot refreshes (30s/180s). Until then it self-heals on the operator's first options write (e.g. staging an escalation) |
| Operator hands-on (stage→instant buttons→Cancel; Run-Now ×2; options-flow labels) | OPERATOR PENDING | the staging action now exercises the v5.3.5 fix directly |
