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

## Live Validation (Review D) — prospective criteria

- [ ] Clean restart; zero new URA ERRORs.
- [ ] The operator's staged `pending_propose_config` (options-persisted from
      2026-06-10 22:38) survives the restart: autonomy select restores to
      "Pending — Propose config changes" and **Confirm + Cancel Escalation are
      AVAILABLE immediately** (this is the bug's exact reproduction case).
- [ ] Operator presses **Cancel** → select returns to Shadow committed,
      buttons grey out instantly (no poll wait) — completes the v5.3.3
      hands-on item.
- [ ] Run Cycle Now fires a manual shadow cycle; second press within 30s
      debounces (carried-forward hands-on item).
- [ ] Options-flow label rendering check (carried forward — note which
      translation shape resolved).

*Replaced with observed results post-restart per the README write-back rule.*
