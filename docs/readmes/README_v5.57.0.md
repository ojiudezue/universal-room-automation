# v5.57.0 — Arrester Operator-Immunity + Temp Arrester Override (+ linker ingress hotfix)

Livability cycle (operator-requested): the OverrideArrester could shave
the operator's own manual quick-cool during peak — undocumented. Ships:

- **Person-scoped hold immunity**: holds traced to a listed HA user are
  never compromised/shaved (all NINE corrective-write sites gated, incl.
  the startup ramp audit and the DPM setpoint apply — the "operator holds
  are untouchable" claim is complete). DORMANT until the operator sets
  `hvac_arrester_immune_persons` in HVAC options (no silent defaults —
  WARNING until configured). Voice ruling (b): voice/assist-mediated
  calls do NOT inherit immunity (parent_id discriminator, best-effort;
  manual documents the dedicated-HA-user enforcement for full coverage).
- **Immune-hold sunsets, first-of**: durable house-state transition
  (sleep/away/vacation), the thermostat's own next_activity_time
  boundary (ISO or "HH:MM", verified live), or a 4h cap. Sunset restores
  jurisdiction, never force-clears.
- **Temp Arrester Override switch** (operator-named): house-wide arrester
  stand-down; auto-sunsets on sleep-transition or 6h; visible state
  always mirrors governance reality (dispatcher-pushed on every path);
  reload-drop leaves an NM note; never restores ON.
- **AC Ramp master reload fix**: persisted as a config-entry option
  (write-through, reload-suppressed key, RestoreEntity one-shot
  migration) — survives restarts AND options-flow reloads.
- **HC manual §3.4b**: the arrester chapter that never existed —
  detection/severe/compromise paths, immunity, sunsets, voice caveat.
- Rides with the **linker ingress hotfix** (canonical camera keys +
  perimeter allowlist — fixes interior-camera leak + case-split census).

Reviews: Tier 2-DB ×3 — 1 CRIT (alphabetical immunity default → dormant)
+ 5 HIGH (ninth site, voice scope, task leak, stale switch UI, boundary
attribute) all fixed; C's battery 6/6 bound. Orchestrator drills: DPM
gate red-verified; voice gate red-verified (after one mis-aimed
docstring drill — noted honestly); builder's stash mishap recovered via
fsck, no loss. Suite 8284 passed, 21 pre-existing.

## Live Validation (prospective)
- **Live:** switches present (Temp Arrester Override OFF, AC Ramp per
  option); dormant-immunity WARNING in log until operator configures
  persons list.
- **Live:** operator sets immune persons + hand-sets a hold during a
  ramp window → no shave, ledger "shave_skipped"; sunset at next
  boundary/durable transition (ledger row).
- **Live:** options-flow save no longer resets the AC Ramp master.
- **Live:** exterior diagnostic shows ONLY exterior cameras;
  ignored_offlist_events counts any interior leak attempts; census
  case-splits gone.
- **Live:** zero URA ERROR lines first hour.
