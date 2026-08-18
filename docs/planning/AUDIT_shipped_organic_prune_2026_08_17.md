# AUDIT — `shipped_organic` backlog prune (2026-08-17)

READ-ONLY verification pass over the 44 cards in `status: shipped_organic`
in `docs/planning/kanban.data.yaml`. Goal: per card, decide whether the
ORGANIC PROOF has landed against LIVE state. Board NOT edited — the
orchestrator applies closes.

Method: live entity/config reads via `/Users/okosisi/ha-config/.storage`,
URA DB via `ssh ha` (`mode=ro`), and `.vibememo/` shipwatch confirmations.
Conservative bar: CLOSE only on POSITIVE live evidence; when in doubt, KEEP.

---

## CLOSE — positive live evidence the organic proof landed

| card_id | proof criterion | live evidence | source |
|---|---|---|---|
| MEMORY-COMPACTOR-1 | compactor runs nightly and writes `memory_facts` once episode volume >50 | `memory_facts`=53 rows, dated 08-02(4)/08-15(20)/08-16(15)/**08-17(14)** — nightly compaction confirmed, matches card's "wrote 14 at 02:30 CT today". Trigger long met (exterior_track 1327 etc.) | `ssh ha` DB: `SELECT substr(created_at,1,10),COUNT(*) FROM memory_facts GROUP BY 1` |
| FAN-LAYER-1 | transparent FanPolicyOracle delegation → no fan flap post-restart (L2) | shipwatch CONFIRMED v5.70.0 L2: Jaya fan held 12.5h post-boot, no rapid cycling on any managed fan, 0 `max_active_failsafe` log entries | `.vibememo/users/ojiudezue/entries/shipwatch_confirmed_v5.70.0_L2.json` |
| GUEST-ROOM-CONFIG-1 | designated guest-room set = the 2 real guest bedrooms only (bathroom unflagged) | LIVE config: `room_is_guest_room=True` on **Guest Bedroom 1** and **Upstairs Guestroom** only; "Guest Bedroom 1 Bathroom" carries NO guest flag. Proof is a static config check, not occupancy-gated | `/Users/okosisi/ha-config/.storage/core.config_entries` |
| v5.59.0 (resolver-legs) | leg_firing_by_camera populated from real events; one alert per track | Card `organic_open` self-records "CLOSED 2026-08-07: leg_firing_by_camera POPULATED from real events... Acceptance met." + live PASS note (zero multi-key WARN / _2 storm / URA ERROR) | card body `note`/`organic_open`; `README_v5.59.0.md` |
| CAM-AREA-PENDING | camera area corrections resolved | Title "RESOLVED"; every sub-item adjudicated by operator (front_porch reassigned; pantry D3 = orphan, no camera; typos = no cameras). No pending organic proof; not a code-ship at all | card `resolved` block |

## KEEP — organic proof genuinely still open

| card_id | why still open |
|---|---|
| CENSUS-GHOST-DEDUP-1 | **MANDATORY KEEP** — v5.79.0 shipped tonight; L3/L8 discriminating tests need occupancy, house empty until residents return Wed |
| STUCK-SENSOR-1 | BLOCKED on SENSOR-CAPABILITY-1; exclusion not yet scoped |
| SENSOR-CAPABILITY-1 | Plan written; AWAITING OPERATOR GO (Tier 3, not implied-approval) |
| WATCHDOG-INERT-1 | D1/P24 silence still under investigation (AUDIT_detector_silence...) |
| EV-SENSOR-CLEANUP-1 | Committed-not-shipped; rides the PATH-ALPHA deploy (future) |
| HVAC-PRESET-FLAP-1 | Now a design question (arbitration rule undecided), not yet built |
| ARREST-COMFORT-1 | Build queued after FAN-LAYER slots clear (serialized on hvac.py) |
| BLE-WARM-CREATE-1 | AWAITING TIER-3 OPERATOR CHECKPOINT; branch not merged |
| FAN-MANUAL-1 | Consolidated fix-up in flight; not final |
| KHOST-2 | Not built (webhost micro-API + board JS) |
| NM-REPAGE-IMG-1 | "Fold into next NM build" — not yet shipped |
| NM-RECOVERY-AGEBOUND-1 | "Fold into next NM deploy" — not yet shipped |
| SAFEWORD-WINDOW-1 | Awaiting operator shape confirmation → Tier 2 |
| IMSG-IMAGE-FAIL-1 | Active organic FAIL (images NOT arriving) + investigation open |
| OPT-META-BOOT-TRANSIENT-1 | Tier-1 hotfix, batch with next deploy — not shipped |
| MEMORY-WRITERS-1 | Needs operator go to start Tier-2 cycle |
| ROOM-NAME-DESYNC-1 | Operator (a)-vs-(b) pick pending → Tier 2-DB not built |
| PATH-ALPHA-DENOM-1 | GATED on ZONE-TIER-DIVERGE-1 trace; not built |
| AWAY-BLOCK-1 | Operator pick pending |
| CIRCLING-LABEL-1 | planner → plan review → build (not started) |
| GAP-A-CENSUS-HOLE-1 | Build on feature/path-alpha after its D1-D9 land |
| GUEST-FP-RESIDUALS-1 | Fold A1+B1 into next presence hotfix; operator answer pending |
| DP-REASON-NULL-1 | One-line fix, fold into next Tier-1 batch — not shipped |
| NM-BB-IMAGE-1 | Image delivery organically FAILED (see IMSG-IMAGE-FAIL-1 L5) |
| SUITE-HYGIENE-1 | Small cycle, not done; acceptance = 3 identical-failure-set runs |
| NM-IMAGE-1 | Operator approval → plan → build (not started) |
| DP-OBSERVABILITY-1 | Small cycle (age-stamp snapshot etc.) not built |
| FAN-LAYER-2 | Completion cycle after FAN-LAYER-1 validates; not built |
| CIRCLING-SEVERITY-1 | Trace/decision open |
| XCORR-1 | Burst-demotion not built |
| DIMMER-REBOOT-1 | Power-on-default not yet set; reboot cause unchased |
| ARREST-SUNSET-1 | Fold into SECC-1 batch (Tier 2-DB) — not built |
| CONSOL-1 | Fold SNAP-1 + TEST-1/2 — cycle not built |
| SNAP-1 | Core shipped v5.63.0 but card carries open follow-ups (bluebubbles attach, protect-thumb source, capture-latency sensor, FRIG2SNAP-1) |
| TRANSIT-1 | Build not started (Protect checkpoint resolver) |
| RELOAD-WATCHDOG-HAZARD | "(tonight) build" — INTEGRATION suppress set + re-subscribe not shipped |
| KHOST-1 | Generator built+merged; remaining = operator one-command to activate hosting (agent lacks creds) — hosted board not yet live |

## UNCLEAR — cannot verify organic proof from available data

| card_id | what's missing |
|---|---|
| D3-AREA-INHERIT | Fix (set area at D3 sensor creation) shipped v5.74.0, but organic proof = a NEW room's D3 sensor inheriting area automatically. Existing sensors were hand-patched band-aids, so their current area doesn't discriminate the fix. Needs a new-room creation (or code confirmation) to prove — `next` still reads as a TODO. Operator input: is this considered done at ship, or does it await the next new-room event? |
| PLAN-TIER-1 | Organic proof defined as "a plan-review finding that demonstrably prevents a build round." The FAN-LAYER-1 / ARREST-COMFORT-1 plans were the first subjects, but whether a plan-review finding measurably averted a build round is a process-narrative judgment not observable in live system state. Operator to confirm whether the FAN-LAYER-1 plan reviews met the bar. |

---

## Summary

- **CLOSE: 5** — MEMORY-COMPACTOR-1, FAN-LAYER-1, GUEST-ROOM-CONFIG-1, v5.59.0, CAM-AREA-PENDING
- **KEEP: 37**
- **UNCLEAR: 2** — D3-AREA-INHERIT, PLAN-TIER-1

### CLOSE list (for one-edit application)
1. `MEMORY-COMPACTOR-1` — memory_facts=53, 14 written 2026-08-17; nightly compaction confirmed live.
2. `FAN-LAYER-1` — shipwatch v5.70.0 L2 confirmed: no fan flap post-FanPolicyOracle restart (Jaya held 12.5h).
3. `GUEST-ROOM-CONFIG-1` — live config: `room_is_guest_room=True` only on Guest Bedroom 1 + Upstairs Guestroom; bathroom unflagged.
4. `v5.59.0` — card+README record CLOSED 2026-08-07, leg_firing_by_camera populated from real events, live PASS.
5. `CAM-AREA-PENDING` — title RESOLVED; all sub-items adjudicated; no code/organic proof pending.

### Operator input needed
- `D3-AREA-INHERIT` and `PLAN-TIER-1` (UNCLEAR) — is each considered done-at-ship, or does its proof await a specific future event?
