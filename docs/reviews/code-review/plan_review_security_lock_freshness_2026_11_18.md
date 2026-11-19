# Plan review: PLANNING_security_lock_freshness.md (b2f5372ec)

Framings: completeness + build-prediction + G. Verdict: **PLAN-FIX-REQUIRED** (one HIGH, small fixes).

1. **HIGH (G, "only proven code supersedes correct code").** INV-2 and D2 stop `lock.lock` to a stale `unlocked` lock (security.py:1852-1864). Today that lock gets the command, and the command can work. A late report does not mean the radio is dead. That removes proven behaviour at the door the operator "found unlocked". Fix: stale+unlocked keeps the existing command path (retry cap intact) and also pages. Only stale+`locked` changes (page + refresh). Narrow INV-2 to "no new command".
2. **MEDIUM (completeness).** §4 lists three command sites. A grep finds eight: sweep security.py:1862, lockdown :1754, hazard egress unlock :2337, regime unlock :899/:2239/:2976, engage :2436, away-lock :2830. Ruling: none needs the gate. Lockdown, engage and away-lock commanding a silent lock is harmless and is how a dead lock shows itself. Unlocks are life-safety or resident-driven. List all eight in the plan with that ruling.
3. **MEDIUM (build-prediction).** D1/D4 must resolve siblings with `er.async_entries_for_device(..., include_disabled_entities=True)`. Otherwise the disabled garage `last_seen` looks absent, D4 cannot say "disabled", and a None state must not count as age 0 or as stale.
4. **MEDIUM (G).** HIGH reaches only recipients whose bypass set includes it during DND (notification_manager.py ~1685-1740). A night stale page can still go silent. Make promoting `lock_unverified` an explicit pre-deploy operator decision and a live-check row, not an optional aside.
5. **LOW.** D5 park is acceptable. Simulated 11-16..11-18: with the Store holding real_report_ts across restarts, D2 pages at ~12 h instead of never (holds even with last_seen disabled, using lock stamps). No registry lock-to-door mapping exists for the garage. Keep the trigger.

Holds: additive at one site, Store pattern (:721), knobs laddered, INV-4 kill switch N=0.
