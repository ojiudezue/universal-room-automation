# AUDIT: crossing ledger terms all `applied=false, reason=unknown` (2026-11-17 10:50 CST)

Read-only. Did not re-read the full HVAC/presence STATE_OF_PLAY docs (not an HVAC/presence-sensor task); read crossing_ledger.py apply_term/anchor/evaluate, crossing_vision.py ledger wiring, plan P2-D2/D3, AUDIT_crossing_pipeline_after_v5_108_24.md section 5.

## Verdict: BY DESIGN (a), with the real finding being (c) BLOCKED. No defect in the reason field.
`reason="unknown"` is not an unset reason. It is the literal reason code for "ledger state is not `known`":
`crossing_ledger.py:445-446` `if self.state != STATE_KNOWN ... return LedgerEvent(applied=False, reason="unknown", ...)`. The other code is `"late"` (:447-449). Rows are written in `crossing_vision.py:2077-2107` (`_flush_ledger_events` -> `database.log_memory_episode`, type const.py:3875, payload `ev.as_dict()`; l_before/person null follow from the same branch, :443-446). `applied` is false only when the term was not folded into L. Awareness-only is a separate, unrelated gate (L reaches F2 only via census_tick; switch census_authority is on but INV-SHADOW).

## Why the ledger never becomes known
State starts `unknown` ("boot", crossing_ledger.py:239-240); only `_anchor()` (:516-538) makes it known. Anchor needs: fresh camera_bodies==0, no camera_input_dark, no held Tier-1 input (ANCHOR_NEEDS_NO_HOLD True, const.py:3889), no rising edge, no entry term, sustained EMPTY_RESET_S=900 s (const.py:3883), sampled every 60 s. State is RAM only; every restart returns it to unknown (ledger_disabled/set_unknown also on switch off/kill/cap 0, crossing_vision.py:1790-1803).

## 7-day DB count (memory_episodes, crossing_vision_ledger, started_at >= now-7d; script .claude/tmp/ledgerwhy_probe.py)
| kind | applied | reason | n |
|---|---|---|---|
| term | false | unknown | 77 |
| anchor | true | null | 1 |
Terms by day (UTC): 11-14 21, 11-15 27, 11-16 22, 11-17 7. First row ever 11-14 22:08Z (v5.108.23 ship 16:03 CST). Zero `late`, zero reconcile/lift rows.
The ONE anchor: 2026-11-17 14:42:32Z (08:42 CST), l_after=0. Next term 15:16Z (09:16 CST) is again `unknown`: v5.108.35 deployed 08:48 CST (git log), a restart reset RAM state (inferred from deploy time; HA log not reachable to confirm). Roughly 13 version deploys 11-14..11-17 (git log), each a restart.

## Falsification
If (b) were true, reason would be null/other on some rows; all 77 are the explicit string. If ledger evaluated and was known, the anchor row would precede terms with non-null l_before; the single anchor precedes none that survived a restart. The 11-14 audit (AUDIT_crossing_pipeline_after_v5_108_24.md:46) found state unknown 14.8 h after boot with five held inputs (media room mmWave x2, study A, upstairs guest room, master bath).

## Live state now
UNKNOWN. `crossing_ledger` lives only on `sensor.ura_security_coordinator_outside_open_tracks_diagnostic` (sensor.py:4651, 4671; registry-disabled by default, `_attr_entity_registry_enabled_default False`, :4690ish) which reads `unavailable` with no attributes (REST /api/states, 10:4x CST). Switches shadow/census_authority on; daily_calls number 93.

## Smallest fix / what unblocks
No code fix needed for the reason string. Optional: enable that diagnostic entity (operator config) to see state/last_anchor/holders. Real unblocker: stop restarting for ~15+ min of empty house with no held input; persistent ledger state across restart would be a new build (not recommended before measuring anchor yield; see AUDIT_ledger_checkpoint_window_sweep_2026_11_14.md).

## Impact on interior ledger FLOOR plan (PLANNING_vision_interior_sightings.md section 1b)
Yes. 1b.3 line 127: while unknown, no lift. Floor can only act while known, and the ledger was known for ~34 min in 3.5 days (anchor 14:42Z to restart). Floor's D0 fire-rate measure (c, line 180) must count known-time; expect near-zero effective lifts until anchor yield/restart-survival is fixed. The plan's assumption "the ledger evaluates" is false in practice today.
