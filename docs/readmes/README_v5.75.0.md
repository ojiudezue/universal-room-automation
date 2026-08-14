# URA v5.75.0 — Stuck sensors get consequences (STUCK-SENSOR-1) + renames become safe (ROOM-NAME-DESYNC-1)

Two Tier 2-DB presence cycles, one deploy. Both born from the 2026-08-13 away-transition incident
(house held home_day 2h by a fan-fed mmWave while everyone was out). Each ran: plan → adversarial
plan review (8 HIGH-grade defects caught pre-build across the two) → build → 3 framing-disjoint
reviews → consolidated fix-up → orchestrator re-drills.

## STUCK-SENSOR-1 — detection finally has a consequence

- **Duty-flagged sensors are excluded from occupancy** when ALL of: exclusion enabled (rung-1 +
  rung-2 kill switches), house state allows (sleep/waking/home_night defer — a sleeper's fan can
  never be killed by this), a role-resolved corroborator is wired, and that corroborator has
  disagreed ≥ `CORROBORATOR_DISAGREE_S` = **900s** (must exceed the detector's own 300s PIR-quiet
  shield to add real evidence — a still TV-watcher is safe by construction, test-pinned).
- No corroborator = notify-only stays (explicit; the no-PIR rooms await operator hardware; the new
  Living Room Hobeian 10GHz counts as corroborator for non-fan pathologies per operator taxonomy).
- Exclusion surfaces: `excluded_sensors` attr on room insight + NM engage/release notes (own
  latch — the 1-stuck-NM/day contract preserved); exclusion state RAM-only (re-earned per tick);
  stuck tallies persist restart via dirty-gated `async_delay_save(60s)` (write-flood class
  explicitly avoided + write-volume regression test) with boot-guarded restore (no
  restore-poisoning: consequence requires live-ON observed post-boot + boot-settle).
- P18 zone-stale NM rows now carry the zone name (diagnosability fix folded per operator sign-off).
- Ledger-golden signed fixtures byte-identical (`exclusion_engaged` emitted only-when-True;
  replay-harness preserve rule intact).

## ROOM-NAME-DESYNC-1 — "we should be able to rename rooms and be correct"

- **Write-through at all FIVE name/zone producer sites** in the options flows: room rename
  (basic_setup), legacy-zone rename (update + create branches), and the two zone-rooms loops
  (assign/remove — the drift factories the 08-13 house-tier blindness came from). Single combined
  `async_update_entry(data=, options=, title=)` per site — HA-source-verified single listener fire;
  flow ends via `async_abort` (no second write).
- **Boot migration** syncs any existing desync (idempotent, ordered before all listener
  registrations — no setup-time reload; no-op for the three hand-synced rooms).
- **Runtime desync tripwire**: NM note if the twins ever diverge again (boot-order-safe via
  background task + retry).
- Known follow-up carded: ROOM-NAME-UNIQUE-1 (rename collision unguarded — latent, pre-existing;
  do not rename a room to another room's exact name until it ships).

## Also riding
- Switch relabel: "Duty Off-Phase Honesty" → **"Coast Preset Preservation"** (operator-chosen;
  entity_id unchanged). Its retirement is parked on PRESET-FLAP L3+L4 organic proof.

## Acceptance criteria
- **Test:** stuck files 16 (incl. 7 production-anchored drills' anchors) + rename file 18; suite
  23 pre-existing failures byte-identical, zero new.
- **Live:** loads, zero URA errors; migration log line present; NO desync NM at boot; all
  URA entries data==options for the three write-through keys.
- **Live (stuck knobs):** exclusion config toggle present; toggling does NOT reload the CM (both
  keys in the A2 no-reload set).
- **Live (organic):** first real duty-flag + corroborator-disagree episode excludes (attr + NM
  note); Coast Preset Preservation label visible; next operator zone-rooms save produces coherent
  data+options twins (spot-check after next rename/reassign).
- **Note (honesty, per Review C):** the substrate read-shape convergence is simulated in-suite
  (plan-authorized fallback); the runtime dispatch chain is proven organically at the next real
  rename.

## Live Validation

(prospective — replaced with Validated table post-restart)
